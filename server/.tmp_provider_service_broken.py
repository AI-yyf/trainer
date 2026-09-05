from __future__ import annotations

import json
import re
import socket
from contextvars import ContextVar
from importlib import import_module
from time import monotonic
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from ..core.models import ProviderConfig, ProviderModelsResponse, ProviderTestResponse, UserProfile
from .provider_protocols import normalize_provider_protocol
from .prompts import (
    _looks_like_first_turn,
    build_coaching_messages,
    coaching_scenario_label,
    extract_coaching_context,
    infer_coaching_scenario,
    infer_learner_signal,
    normalize_answer_policy,
)


def _compact_text(value: object | None, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 1)].rstrip()}..."


_MOJIBAKE_FALLBACK_MARKERS = (
    "\ufffd",
    "\ue000",
    "\ue1ec",
    "?",
    "?",
    "?",
    "?",
    "?",
    "?",
    "?",
    "?",
)


def _looks_like_mojibake_text(value: object) -> bool:
    text = str(value or "")
    return any(marker in text for marker in _MOJIBAKE_FALLBACK_MARKERS)


def _localized_text(english: str, chinese: str, response_language: str | None) -> str:
    if _prefers_chinese(response_language) and _looks_like_mojibake_text(chinese):
        return english
    return chinese if _prefers_chinese(response_language) else english


_THINK_BLOCK_PATTERN = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_THINK_CLOSE_TAG_PATTERN = re.compile(r"</think\b[^>]*>", re.IGNORECASE | re.DOTALL)
_THINK_TAG_PATTERN = re.compile(r"</?think\b[^>]*>", re.IGNORECASE | re.DOTALL)
_PROVIDER_CONTROL_MARKER_PATTERN = re.compile(
    r"\]\s*<\]\s*minimax\s*\[>\s*\[",
    re.IGNORECASE | re.DOTALL,
)
_PSEUDO_TOOL_CALL_BLOCK_PATTERN = re.compile(
    r"<tool_call\b[^>]*>.*?(?:</tool_call\s*>|$)",
    re.IGNORECASE | re.DOTALL,
)
_PSEUDO_TOOL_CALL_TAG_PATTERN = re.compile(r"</?tool_call\b[^>]*>", re.IGNORECASE | re.DOTALL)
_VISIBLE_MODEL_PUNCTUATION_MAP = str.maketrans(
    {
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
    }
)
_CJK_CHAR_PATTERN = re.compile(r"[\u3400-\u9fff]")
_LATIN_CHAR_PATTERN = re.compile(r"[A-Za-z]")
_CYRILLIC_CHAR_PATTERN = re.compile(r"[\u0400-\u04FF]")
_QUESTION_RUN_PATTERN = re.compile(r"\?{4,}")
_VISIBLE_TOKEN_PATTERN = re.compile(r"\S+")
_LANGUAGE_PROBE_VARIANTS = (
    (
        "Repeat exactly: \u4e0d\u8981\u76f4\u63a5\u8003\u8bd5\uff0c\u5148\u5b66\u518d\u6d4b\u3002\u8bf7\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\u3002ABC123",
        "\u4e0d\u8981\u76f4\u63a5\u8003\u8bd5\uff0c\u5148\u5b66\u518d\u6d4b\u3002\u8bf7\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\u3002ABC123",
    ),
    (
        "\u8bfb\u8fd9\u53e5\u8bdd\uff0c\u53ea\u56de\u590d\u6700\u540e\u56db\u4e2a\u6c49\u5b57\uff0c\u4e0d\u8981\u89e3\u91ca\uff1a\u4e0d\u8981\u76f4\u63a5\u8003\u8bd5\uff0c\u5148\u7528\u6700\u5c0f\u6559\u5b66\u6b65\u9aa4\u6559\u6211\u5982\u4f55\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\uff0c\u518d\u7ed9\u6211\u4e00\u4e2a\u5f88\u5c0f\u7684\u9a8c\u8bc1\u52a8\u4f5c",
        "\u9a8c\u8bc1\u52a8\u4f5c",
    ),
)
_NATURAL_LANGUAGE_PROBE_PROMPT = (
    "?????????????????????????VS Code?????????????"
)
_NATURAL_LANGUAGE_PROBE_FRAGMENTS = ("????", "VS Code")
_INPUT_CORRUPTION_MARKERS = (
    "question mark",
    "question marks",
    "garbled",
    "corrupted",
    "cannot read",
    "can't read",
    "could not read",
    "only saw",
    "only see",
    "\u95ee\u53f7",
    "\u4e71\u7801",
    "\u53ea\u80fd\u770b\u5230\u4e00\u4e32",
    "\u770b\u8d77\u6765\u4f60\u53d1\u8fc7\u6765\u7684\u5185\u5bb9\u91cc\u4e2d\u6587\u90fd\u53d8\u6210\u4e86\u95ee\u53f7",
    "\u7f16\u7801",
    "\u8f93\u5165\u6cd5",
)


def _strip_provider_control_markers(text: str) -> str:
    if not text:
        return ""
    cleaned = _PROVIDER_CONTROL_MARKER_PATTERN.sub("", text)
    cleaned = _PSEUDO_TOOL_CALL_BLOCK_PATTERN.sub("", cleaned)
    cleaned = _PSEUDO_TOOL_CALL_TAG_PATTERN.sub("", cleaned)
    return cleaned.strip()


def _strip_reasoning_blocks(text: str) -> str:
    if not text:
        return ""
    cleaned = _THINK_BLOCK_PATTERN.sub("", text)
    cleaned = _THINK_TAG_PATTERN.sub("", cleaned)
    return _strip_provider_control_markers(cleaned)


def _visible_model_text(value: object | None) -> str:
    if not isinstance(value, str):
        return ""
    return _strip_reasoning_blocks(value).translate(_VISIBLE_MODEL_PUNCTUATION_MAP)


def _agentic_visible_retry_messages(
    messages: list[dict[str, Any]],
    *,
    response_language: str | None,
) -> list[dict[str, Any]]:
    language = (response_language or "user default").strip() or "user default"
    instruction = (
        "The previous provider turn returned no visible assistant text. "
        "Answer the same Trainer coaching turn again now. Return visible user-facing "
        "coaching text only; do not output only reasoning, <think> blocks, tool silence, "
        "or metadata. Keep the current teaching lane and include one tiny "
        "Learn -> Try -> Verify move. Match the requested response language "
        f"({language}); if it is zh-CN, write Chinese while keeping technical terms such "
        "as API, protocol, provider, model, debug, remote, and VS Code in English."
    )
    retry_messages: list[dict[str, Any]] = []
    inserted = False
    for message in messages:
        copied = dict(message)
        if not inserted and str(copied.get("role") or "") == "system":
            existing = str(copied.get("content") or "").rstrip()
            copied["content"] = f"{existing}\n\n{instruction}" if existing else instruction
            inserted = True
        retry_messages.append(copied)
    if not inserted:
        retry_messages.insert(0, {"role": "system", "content": instruction})
    return retry_messages


def _agent_tool_events(result: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for step in list(getattr(result, "steps", []) or []):
        step_index = getattr(step, "index", -1)
        for call in list(getattr(step, "tool_calls", []) or []):
            if isinstance(call, dict):
                events.append({"type": "tool_call", **call, "step": step_index})
        for tool_result in list(getattr(step, "tool_results", []) or []):
            if isinstance(tool_result, dict):
                events.append({"type": "tool_result", **tool_result, "step": step_index})
    return events


def _agent_result_visible_text(result: Any) -> str:
    return _visible_model_text(getattr(result, "final_content", "") or "")


def _agentic_retry_text_is_usable(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return False
    lowered = normalized.casefold()
    retry_placeholders = {
        "(scripted provider exhausted)",
        "scripted provider exhausted",
    }
    if lowered in retry_placeholders:
        return False
    return True


def _agentic_final_event_from_result(result: Any) -> dict[str, Any]:
    return {
        "type": "final",
        "content": _agent_result_visible_text(result),
        "summary": getattr(result, "summary", None),
        "next_step": getattr(result, "next_step", None),
        "stop_reason": getattr(result, "stop_reason", "completed"),
        "decision": getattr(result, "decision", None),
        "blocker": getattr(result, "blocker", None),
        "teaching_note": getattr(result, "teaching_note", None),
        "resume_thread": getattr(result, "resume_thread", None),
        "confidence": getattr(result, "confidence", None),
        "evidence": getattr(result, "evidence", None),
    }


_INTERNAL_COACH_META_MARKERS = (
    "current coaching focus:",
    "current focus:",
    "current focus to continue:",
    "review rhythm:",
    "memory scope is",
    "preferred teaching asset:",
    "reusable teaching asset:",
    "resume the live thread around",
    "evidence to anchor on:",
    "keep the next move as",
    "keep the blocker in view:",
    "build on the verified result:",
    "carry this teaching note forward:",
    "coach confidence:",
    "useful recalled memory:",
    "relevant recalled memory:",
    "continuity evidence:",
    "this follows the teaching lane from",
    "reuse the saved teaching asset",
    "saved teaching asset",
    "\u5f53\u524d\u805a\u7126\uff1a",
    "\u5f53\u524d\u805a\u7126\u70b9\uff1a",
    "\u590d\u4e60\u8282\u594f\uff1a",
    "\u8bb0\u5fc6\u8303\u56f4\u662f",
)
_INTERNAL_COACH_META_LABELS = {
    "project implementation",
    "idea implementation guidance",
    "project idea mining",
    "existing project adaptation",
    "project adaptation",
    "principle explanation",
    "review and reflection coaching",
    "plan and review rhythm",
    "plan and review",
    "task execution coaching",
    "next task coaching",
    "next step after review",
    "general coaching",
}
_INTERNAL_COACH_META_PREFIXES = (
    "current coaching focus:",
    "current focus:",
    "current focus to continue:",
    "review rhythm:",
    "preferred teaching asset:",
    "reusable teaching asset:",
    "resume the live thread around",
    "build on the verified result:",
    "keep the blocker in view:",
    "coach confidence:",
    "\u5f53\u524d\u805a\u7126\uff1a",
    "\u5f53\u524d\u805a\u7126\u70b9\uff1a",
    "\u590d\u4e60\u8282\u594f\uff1a",
)
_VISIBLE_COACH_PARAGRAPH_SPLIT_PATTERN = re.compile(r"\n\s*\n")
_VISIBLE_COACH_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?\u3002\uff01\uff1f])\s+")


def _normalize_coach_meta_candidate(text: str) -> str:
    return " ".join(text.strip().split())


def _strip_leading_coach_meta_prefix(text: str) -> str:
    normalized = _normalize_coach_meta_candidate(text)
    lowered = normalized.casefold()
    for prefix in _INTERNAL_COACH_META_PREFIXES:
        if lowered.startswith(prefix):
            return normalized[len(prefix) :].strip()
    return normalized


def _looks_like_internal_coach_meta(text: str) -> bool:
    normalized = _normalize_coach_meta_candidate(text)
    if not normalized:
        return False
    lowered = normalized.casefold()
    if any(marker in lowered for marker in _INTERNAL_COACH_META_MARKERS):
        return True
    label = lowered.strip(" -:*_#>~`[](){}")
    return label in _INTERNAL_COACH_META_LABELS


def _strip_internal_coach_meta(text: str) -> str:
    normalized_text = _visible_model_text(text)
    if not normalized_text.strip():
        return ""

    kept_paragraphs: list[str] = []
    for paragraph in _VISIBLE_COACH_PARAGRAPH_SPLIT_PATTERN.split(normalized_text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        kept_lines: list[str] = []
        for line in paragraph.splitlines():
            stripped_line = line.strip()
            if not stripped_line:
                continue
            stripped_line_without_prefix = _strip_leading_coach_meta_prefix(stripped_line)
            if (
                stripped_line_without_prefix
                and stripped_line_without_prefix != _normalize_coach_meta_candidate(stripped_line)
            ):
                stripped_line = stripped_line_without_prefix
            elif _looks_like_internal_coach_meta(stripped_line):
                continue
            kept_fragments: list[str] = []
            for fragment in _VISIBLE_COACH_SENTENCE_SPLIT_PATTERN.split(stripped_line):
                stripped_fragment = fragment.strip()
                if not stripped_fragment:
                    continue
                stripped_fragment_without_prefix = _strip_leading_coach_meta_prefix(stripped_fragment)
                if (
                    stripped_fragment_without_prefix
                    and stripped_fragment_without_prefix
                    != _normalize_coach_meta_candidate(stripped_fragment)
                ):
                    stripped_fragment = stripped_fragment_without_prefix
                elif _looks_like_internal_coach_meta(stripped_fragment):
                    continue
                kept_fragments.append(stripped_fragment)
            if not kept_fragments:
                continue
            joined = " ".join(kept_fragments)
            joined = re.sub(r"\s+([,.;:!?])", r"\1", joined).strip()
            if joined:
                kept_lines.append(joined)
        if kept_lines:
            kept_paragraphs.append("\n".join(kept_lines))

    cleaned = "\n\n".join(kept_paragraphs).strip()
    if not cleaned:
        return ""

    for prefix in _INTERNAL_COACH_META_PREFIXES:
        if cleaned.casefold().startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    return cleaned


_LEADING_HTML_SHELL_PATTERN = re.compile(
    r"^\s*(?:<!doctype\s+html\b[\s\S]*?</html>|<html\b[\s\S]*?</html>)\s*",
    re.IGNORECASE,
)
_PROVIDER_HTML_SHELL_MARKERS = (
    '<div id="root"></div>',
    "<div id='root'></div>",
    "<title>new api</title>",
    "unified ai api gateway",
    "/static/js/",
    "/static/css/",
)


def _looks_like_provider_html_shell(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if not (lowered.startswith("<!doctype html") or lowered.startswith("<html")):
        return False
    marker_hits = sum(1 for marker in _PROVIDER_HTML_SHELL_MARKERS if marker in lowered)
    return marker_hits >= 1 or ("<head" in lowered and "<body" in lowered and "id=\"root\"" in lowered)


def _strip_leading_html_shell_artifact(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    stripped = _LEADING_HTML_SHELL_PATTERN.sub("", cleaned, count=1).strip()
    if stripped:
        return stripped
    if _looks_like_provider_html_shell(cleaned):
        return ""
    return cleaned


def _openai_chat_response_visible_text(response: object | None) -> str:
    if isinstance(response, str):
        return _visible_model_text(response)
    choices = getattr(response, "choices", None)
    choice = None
    if isinstance(choices, list) and choices:
        choice = choices[0]
    elif choices is not None:
        choice = choices
    message = getattr(choice, "message", None) if choice is not None else None
    content = getattr(message, "content", None) if message is not None else None
    if isinstance(content, str):
        return _visible_model_text(content)
    return ""


def _malformed_provider_html_shell_detail() -> str:
    return (
        "Provider returned an HTML app shell instead of a chat payload. "
        "Check the base URL and protocol."
    )


def _contains_cjk(text: str | None) -> bool:
    if not text:
        return False
    return bool(_CJK_CHAR_PATTERN.search(text))


def _contains_latin(text: str | None) -> bool:
    if not text:
        return False
    return bool(_LATIN_CHAR_PATTERN.search(text))


def _contains_cyrillic(text: str | None) -> bool:
    if not text:
        return False
    return bool(_CYRILLIC_CHAR_PATTERN.search(text))


def _compact_visible_text(value: object | None, limit: int = 220) -> str:
    visible = _visible_model_text(value)
    normalized = " ".join(visible.split()).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 1)].rstrip()}..."


def _message_probe_fragment(message: str | None, limit: int = 120) -> str:
    normalized = " ".join(str(message or "").split()).strip()
    if not normalized or not _contains_cjk(normalized):
        return ""
    if len(normalized) <= limit:
        return normalized
    cjk_index = next((index for index, char in enumerate(normalized) if _contains_cjk(char)), 0)
    start = max(0, min(cjk_index, max(0, len(normalized) - limit)))
    fragment = normalized[start : start + limit].strip()
    if not _contains_cjk(fragment):
        fragment = normalized[:limit].strip()
    ascii_match = re.search(r"[A-Za-z][A-Za-z0-9._/-]{1,}", normalized)
    if ascii_match:
        ascii_token = ascii_match.group(0)
        if ascii_token not in fragment:
            remaining = limit - len(fragment) - 1
            if remaining > 0:
                fragment = f"{fragment} {ascii_token[:remaining]}".strip()
    return fragment


def _message_probe_variant(message: str | None) -> tuple[str, str] | None:
    fragment = _message_probe_fragment(message)
    if not fragment:
        return None
    return (f"Repeat exactly: {fragment}", fragment)


def _looks_like_input_corruption_reply(
    reply: str,
    *,
    expected_probe: str | None = None,
) -> bool:
    visible = _compact_visible_text(reply, limit=400)
    if not visible:
        return False
    lowered = visible.casefold()
    has_marker = any(marker.casefold() in lowered for marker in _INPUT_CORRUPTION_MARKERS)
    if expected_probe and expected_probe in visible:
        return False
    if has_marker and (
        "?" in visible
        or _QUESTION_RUN_PATTERN.search(visible)
        or "question mark" in lowered
    ):
        return True
    if expected_probe:
        ascii_tail = "".join(char for char in expected_probe if char.isascii() and char.isalnum())
        cjk_chars = "".join(char for char in expected_probe if _contains_cjk(char))
        if (
            ascii_tail
            and ascii_tail in visible
            and cjk_chars
            and cjk_chars not in visible
            and "?" in visible
        ):
            return True
    return False


def _normalize_script_token(token: str) -> str:
    return re.sub(r"^[^A-Za-z\u0400-\u04FF]+|[^A-Za-z\u0400-\u04FF]+$", "", token)


def _normalize_cjk_script_token(token: str) -> str:
    return re.sub(r"^[^A-Za-z\u3400-\u9fff]+|[^A-Za-z\u3400-\u9fff]+$", "", token)


def _dedupe_fragments(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _strip_short_cyrillic_noise(
    reply: str,
    *,
    message: str | None = None,
) -> str:
    if not reply or not _contains_cyrillic(reply):
        return reply
    if message and _contains_cyrillic(message):
        return reply

    parts = re.split(r"(\s+)", reply)
    visible_positions = [index for index, part in enumerate(parts) if part and not part.isspace()]
    changed = False

    for visible_index, part_index in enumerate(visible_positions):
        token = parts[part_index]
        normalized = _normalize_script_token(token)
        if not normalized or not _contains_cyrillic(normalized):
            continue
        if _contains_latin(normalized):
            updated = re.sub(r"[\u0400-\u04FF]{1,2}", "", token)
            if updated != token and _contains_latin(updated):
                parts[part_index] = updated
                changed = True
            continue

        cyrillic_only = "".join(char for char in normalized if _contains_cyrillic(char))
        if len(cyrillic_only) > 2:
            continue
        previous_token = parts[visible_positions[visible_index - 1]] if visible_index > 0 else ""
        next_token = (
            parts[visible_positions[visible_index + 1]]
            if visible_index + 1 < len(visible_positions)
            else ""
        )
        if _contains_latin(previous_token) and _contains_latin(next_token):
            parts[part_index] = token.replace(normalized, "")
            changed = True

    if not changed:
        return reply
    sanitized = "".join(parts)
    sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
    return sanitized or reply


def _mixed_script_corruption_fragments(
    reply: str,
    *,
    message: str | None = None,
) -> list[str]:
    visible = _compact_visible_text(reply, limit=480)
    if not visible or not _contains_cyrillic(visible):
        return []
    if message and _contains_cyrillic(message):
        return []

    mixed_tokens: list[str] = []
    short_cyrillic_tokens: list[str] = []
    for match in _VISIBLE_TOKEN_PATTERN.finditer(visible):
        raw_token = match.group(0)
        token = _normalize_script_token(raw_token)
        if not token or not _contains_cyrillic(token):
            continue
        if _contains_latin(token):
            mixed_tokens.append(token)
            continue
        if len(token) <= 3:
            context_window = visible[max(0, match.start() - 12) : min(len(visible), match.end() + 12)]
            if _contains_latin(context_window):
                short_cyrillic_tokens.append(token)

    mixed_tokens = _dedupe_fragments(mixed_tokens)
    short_cyrillic_tokens = _dedupe_fragments(short_cyrillic_tokens)
    if mixed_tokens:
        return mixed_tokens[:2] + [
            token for token in short_cyrillic_tokens if token not in mixed_tokens
        ][:1]
    if len(short_cyrillic_tokens) >= 2 and _contains_latin(visible):
        return short_cyrillic_tokens[:3]
    return []


def _unexpected_cjk_corruption_fragments(
    reply: str,
    *,
    message: str | None = None,
    response_language: str | None = None,
) -> list[str]:
    visible = _compact_visible_text(reply, limit=480)
    if not visible or not _contains_cjk(visible):
        return []
    if _prefers_chinese(response_language):
        return []
    if message and _contains_cjk(message):
        return []

    mixed_tokens: list[str] = []
    short_cjk_tokens: list[str] = []
    for match in _VISIBLE_TOKEN_PATTERN.finditer(visible):
        raw_token = match.group(0)
        token = _normalize_cjk_script_token(raw_token)
        if not token or not _contains_cjk(token):
            continue
        if _contains_latin(token):
            mixed_tokens.append(token)
            continue
        cjk_only = "".join(char for char in token if "\u3400" <= char <= "\u9fff")
        if not cjk_only or len(cjk_only) > 3:
            continue
        context_window = visible[max(0, match.start() - 12) : min(len(visible), match.end() + 12)]
        if _contains_latin(context_window):
            short_cjk_tokens.append(cjk_only)

    mixed_tokens = _dedupe_fragments(mixed_tokens)
    short_cjk_tokens = _dedupe_fragments(short_cjk_tokens)
    if mixed_tokens:
        return mixed_tokens[:2] + [
            token for token in short_cjk_tokens if token not in mixed_tokens
        ][:1]
    if len(short_cjk_tokens) >= 2 and _contains_latin(visible):
        return short_cjk_tokens[:3]
    return []


def _mixed_script_reply_corruption_detail(
    reply: str,
    *,
    message: str | None = None,
    response_language: str | None = None,
) -> str | None:
    fragments = _mixed_script_corruption_fragments(reply, message=message)
    if fragments:
        return (
            "The provider returned suspicious mixed-script fragments in an otherwise readable "
            "coaching reply. Trainer cannot trust this text as a clean coaching turn."
        )
    unexpected_cjk_fragments = _unexpected_cjk_corruption_fragments(
        reply,
        message=message,
        response_language=response_language,
    )
    if unexpected_cjk_fragments:
        return (
            "The provider returned unexpected CJK fragments in an otherwise English coaching "
            "reply. Trainer cannot trust this text as a clean coaching turn."
        )
    return None


def _is_think_tag_prefix(text: str) -> bool:
    if not text.startswith("<"):
        return False
    lowered = text.lower()
    if lowered.startswith("</think"):
        remainder = text[7:]
        if not remainder:
            return True
        first = remainder[0]
        return not (first.isalnum() or first == "_")
    if lowered.startswith("<think"):
        remainder = text[6:]
        if not remainder:
            return True
        first = remainder[0]
        return not (first.isalnum() or first == "_")
    if "</think".startswith(lowered) or "<think".startswith(lowered):
        return True
    return False


def _reasoning_prefix_start(text: str) -> int | None:
    last_lt = text.rfind("<")
    if last_lt < 0:
        return None
    suffix = text[last_lt:]
    if _is_think_tag_prefix(suffix):
        return last_lt
    return None


def _trim_trailing_reasoning_prefix(text: str) -> str:
    prefix_start = _reasoning_prefix_start(text)
    if prefix_start is None:
        return text
    return text[:prefix_start]


class _ReasoningBlockFilter:
    def __init__(self) -> None:
        self._buffer = ""
        self._inside_think = False

    def push(self, chunk: str) -> str:
        self._buffer += chunk
        emitted: list[str] = []

        while self._buffer:
            if self._inside_think:
                close_match = _THINK_CLOSE_TAG_PATTERN.search(self._buffer)
                if close_match:
                    self._buffer = self._buffer[close_match.end() :]
                    self._inside_think = False
                    continue

                tail_length = len("</think>") - 1
                if len(self._buffer) > tail_length:
                    self._buffer = self._buffer[-tail_length:]
                break

            open_match = _THINK_BLOCK_PATTERN.search(self._buffer)
            if open_match:
                emitted.append(self._buffer[: open_match.start()])
                self._buffer = self._buffer[open_match.end() :]
                continue

            start_match = re.search(r"<think\b[^>]*>", self._buffer, re.IGNORECASE | re.DOTALL)
            if start_match:
                emitted.append(self._buffer[: start_match.start()])
                self._buffer = self._buffer[start_match.end() :]
                self._inside_think = True
                continue

            prefix_start = _reasoning_prefix_start(self._buffer)
            if prefix_start is None:
                emitted.append(self._buffer)
                self._buffer = ""
            elif prefix_start > 0:
                emitted.append(self._buffer[:prefix_start])
                self._buffer = self._buffer[prefix_start:]
            break

        return "".join(emitted)

    def flush(self) -> str:
        if self._inside_think:
            self._buffer = ""
            self._inside_think = False
            return ""
        buffered = _trim_trailing_reasoning_prefix(self._buffer)
        self._buffer = ""
        return _strip_reasoning_blocks(buffered)


class ProviderService:
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
        self._language_integrity_success: dict[str, float] = {}
        self._last_reply_failure: ContextVar[dict[str, Any] | None] = ContextVar(
            f"provider_service_last_reply_failure_{id(self)}",
            default=None,
        )
        self._last_reply_override: ContextVar[dict[str, Any] | None] = ContextVar(
            f"provider_service_last_reply_override_{id(self)}",
            default=None,
        )

    @property
    def has_api_key(self) -> bool:
        return bool(self._api_key)

    def clear_last_reply_state(self) -> None:
        self.clear_last_reply_failure()
        self.clear_last_reply_override()

    def clear_last_reply_failure(self) -> None:
        self._last_reply_failure.set(None)

    def clear_last_reply_override(self) -> None:
        self._last_reply_override.set(None)

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

    def has_recent_language_integrity_success(
        self,
        *,
        message: str | None = None,
        response_language: str | None = None,
    ) -> bool:
        cache_key = self._language_integrity_cache_key(
            message=message,
            response_language=response_language,
        )
        if not cache_key:
            return False
        cached_at = self._language_integrity_success.get(cache_key)
        if cached_at is None:
            return False
        if monotonic() - cached_at > self._LANGUAGE_INTEGRITY_SUCCESS_TTL_SECONDS:
            self._language_integrity_success.pop(cache_key, None)
            return False
        return True

    def mark_language_integrity_success(
        self,
        *,
        message: str | None = None,
        response_language: str | None = None,
    ) -> None:
        cache_key = self._language_integrity_cache_key(
            message=message,
            response_language=response_language,
        )
        if not cache_key:
            return
        self._language_integrity_success[cache_key] = monotonic()

    def clear_language_integrity_success(
        self,
        *,
        message: str | None = None,
        response_language: str | None = None,
    ) -> None:
        cache_key = self._language_integrity_cache_key(
            message=message,
            response_language=response_language,
        )
        if not cache_key:
            return
        self._language_integrity_success.pop(cache_key, None)

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
        self._last_reply_failure.set(
            {
                "error_category": category,
                "detail": detail,
                "retryable": retryable,
                "status_code": status_code,
                "provider_reachable": provider_reachable,
                "model_supported": model_supported,
                "error": str(error).strip(),
            }
        )

    def _record_last_reply_override(self, **payload: Any) -> None:
        self._last_reply_override.set(dict(payload))



    def provider_failure_summary(self, category: str, response_language: str | None) -> str:
        summary_map: dict[str, tuple[str, str]] = {
            "invalid_key_or_permission": (
                "The provider rejected this turn's API key or permissions.",
                "杩欎釜 provider 鎷掔粷浜嗚繖杞姹備娇鐢ㄧ殑 API key 鎴?permission銆?,
            ),
            "model_unsupported": (
                "The provider reached the endpoint, but this model name is not accepted there.",
                "杩欎釜 provider 鍙互杩為€氾紝浣嗗綋鍓?model name 涓嶈杩欎釜 endpoint 鎺ュ彈銆?,
            ),
            "model_not_found": (
                "The provider reached the gateway, but no available channel matched this model.",
                "杩欎釜 provider 鍙互杩為€氾紝浣?gateway 閲屾病鏈夊彲鐢?channel 鑳藉尮閰嶅綋鍓?model銆?,
            ),
            "language_corruption": (
                "The provider returned a visibly corrupted coaching reply on this turn.",
                "杩欎釜 provider 鍙揪锛屼絾杩欎竴杞繑鍥炰簡鑲夌溂鍙鐨勪贡鐮佸洖澶嶃€?,
            ),
            "malformed_response": (
                "The endpoint responded, but the payload was not a valid OpenAI-compatible response.",
                "杩欎釜 endpoint 鏈夊搷搴旓紝浣嗚繑鍥?payload 涓嶆槸鏈夋晥鐨?OpenAI-compatible response銆?,
            ),
            "rate_limit": (
                "The provider rate-limited this turn before Trainer could continue.",
                "杩欎釜 provider 瀵硅繖杞姹傝Е鍙戜簡 rate limit锛孴rainer 鏆傛椂鏃犳硶缁х画銆?,
            ),
            "timeout": (
                "Trainer could not get a response from the provider before the timeout.",
                "Trainer 鍦ㄨ秴鏃跺墠娌℃湁浠?provider 鏀跺埌鍝嶅簲銆?,
            ),
            "network": (
                "Trainer could not reach the provider over the network.",
                "Trainer 鐩墠鏃犳硶閫氳繃 network 杩炲埌杩欎釜 provider銆?,
            ),
        }
        english, chinese = summary_map.get(
            category,
            (
                "Trainer is blocked on the provider path for this turn.",
                "Trainer 杩欒疆琚?provider path 鍗′綇浜嗐€?,
            ),
        )
        return _localized_text(english, chinese, response_language)

    def provider_failure_next_step(self, category: str, response_language: str | None) -> str:
        next_step_map: dict[str, tuple[str, str]] = {
            "invalid_key_or_permission": (
                "Check the API key or provider permissions, retest the connection, and resend this exact turn.",
                "鍏堟鏌?API key 鎴?provider permission锛岄噸鏂版祴璇曡繛鎺ュ悗鍐嶉噸鍙戣繖涓€杞€?,
            ),
            "model_unsupported": (
                "Switch to a model name that this provider actually supports, retest, and resend this exact turn.",
                "鍏堟崲鎴愯繖涓?provider 鐪熸鏀寔鐨?model name锛岄噸鏂版祴璇曞悗鍐嶉噸鍙戣繖涓€杞€?,
            ),
            "model_not_found": (
                "Pick a channel-backed model at this gateway, retest, and resend this exact turn.",
                "鍏堟崲鎴愯繖涓?gateway 閲岀湡姝ｆ湁 channel 鐨?model锛岄噸鏂版祴璇曞悗鍐嶉噸鍙戣繖涓€杞€?,
            ),
            "language_corruption": (
                "Switch provider or gateway first, then resend this same turn after the visible corruption disappears.",
                "鍏堝垏鎹?provider 鎴?gateway锛岀‘璁や贡鐮佹秷澶卞悗鍐嶉噸鍙戣繖涓€杞€?,
            ),
            "malformed_response": (
                "Check that the endpoint really speaks the OpenAI-compatible protocol, then retest and resend this exact turn.",
                "鍏堢‘璁よ繖涓?endpoint 鐪熸杩斿洖 OpenAI-compatible protocol锛屽啀娴嬭瘯骞堕噸鍙戣繖涓€杞€?,
            ),
            "rate_limit": (
                "Wait briefly, then retry this same turn once the rate limit clears.",
                "鍏堢瓑涓€浼氬効锛岀瓑 rate limit 杩囧幓鍚庡啀閲嶈瘯杩欎竴杞€?,
            ),
            "timeout": (
                "Retry once after checking provider latency or gateway load.",
                "鍏堟鏌?provider 寤惰繜鎴?gateway 璐熻浇锛屽啀閲嶈瘯杩欎竴杞€?,
            ),
            "network": (
                "Check the network path or proxy settings, then resend this exact turn.",
                "鍏堟鏌?network 璺緞鎴?proxy 璁剧疆锛屽啀閲嶅彂杩欎竴杞€?,
            ),
        }
        english, chinese = next_step_map.get(
            category,
            (
                "Repair the provider path, then resend this exact coaching turn.",
                "鍏堜慨濂?provider path锛屽啀閲嶅彂杩欎竴杞?coaching銆?,
            ),
        )
        return _localized_text(english, chinese, response_language)

    def provider_failure_reply(
        self,
        category: str,
        detail: str | None,
        response_language: str | None,
    ) -> str:
        detail_text = _compact_text(detail)
        if _prefers_chinese(response_language):
            category_hint = {
                "invalid_key_or_permission": "鍏堟鏌?API key / permission 鏄惁鏈夋晥銆?,
                "malformed_response": "鍏堢‘璁?endpoint 鐪熸杩斿洖鐨勬槸 OpenAI-compatible protocol銆?,
                "rate_limit": "鍏堢瓑涓€浼氬効锛屽啀閲嶈瘯鍚屼竴杞€?,
                "model_unsupported": "鍏堟崲涓€涓繖涓?provider 鏀寔鐨?model name銆?,
            }.get(category, "鍏堜慨澶?provider path锛屽啀閲嶈瘯鍚屼竴杞€?)
            lines = [
                "Trainer 鐩墠鍗″湪 provider path锛屾殏鏃舵棤娉曠户缁繖杞?coaching銆?,
                "",
                category_hint,
            ]
            if detail_text:
                lines.append(f"璇︽儏: {detail_text}")
            lines.append("涓嬩竴姝? 鍏堟妸 provider 鎭㈠鍒板彲鐢ㄧ姸鎬侊紝鍐嶉噸鏂板彂閫佽繖杞€?)
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

    @staticmethod
    def _openai_base_url_endpoint_path(path: str) -> bool:
        normalized = path.rstrip("/")
        return normalized.endswith(("/chat/completions", "/responses", "/models", "/messages"))

    @staticmethod
    def _ensure_openai_api_base_url(
        base_url: str | None,
        *,
        append_for_non_root_paths: bool,
    ) -> str | None:
        raw = str(base_url or "").strip()
        if not raw:
            return None
        stripped = raw.rstrip("/")
        parsed = urlsplit(stripped)
        path = parsed.path.rstrip("/")
        if path.endswith("/v1") or path.endswith("/v1beta") or ProviderService._openai_base_url_endpoint_path(path):
            return stripped
        if path and not append_for_non_root_paths:
            return stripped
        next_path = f"{path}/v1" if path else "/v1"
        return urlunsplit((parsed.scheme, parsed.netloc, next_path, parsed.query, parsed.fragment))

    def _effective_openai_base_url(self, provider: ProviderConfig | None) -> str | None:
        if provider is None:
            return None
        base_url = str(provider.base_url or "").strip()
        if not base_url:
            return None
        protocol = self._configured_protocol(provider)
        if protocol == "gemini_generate_content" and not self._gemini_base_url_is_google_native(provider):
            return self._ensure_openai_api_base_url(
                base_url,
                append_for_non_root_paths=True,
            )
        if protocol in {
            "openai_chat_completions",
            "openai_chat_completions_compatible",
            "openai_responses",
        }:
            return self._ensure_openai_api_base_url(
                base_url,
                append_for_non_root_paths=False,
            )
        return base_url

    def _raise_for_provider_html_shell(self, text: str) -> None:
        if _looks_like_provider_html_shell(text):
            raise RuntimeError(f"Malformed response: {_malformed_provider_html_shell_detail()}")

    def _get_client(self) -> Any:
        if self._client is None:
            async_openai_cls = self._get_async_openai_class()
            base_url = self._effective_openai_base_url(self._config)
            self._client = async_openai_cls(api_key=self._api_key, base_url=base_url)
        return self._client

    def _create_sync_client(self, provider: ProviderConfig, api_key: str) -> Any:
        openai_cls = self._get_sync_openai_class()
        return openai_cls(api_key=api_key, base_url=self._effective_openai_base_url(provider))

    def _provider_request_defaults(self, provider: ProviderConfig | None = None) -> dict[str, Any]:
        config = provider or self._config
        if config is None:
            return {}
        defaults = getattr(config, "request_defaults", None)
        if not isinstance(defaults, dict):
            return {}
        return dict(defaults)

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
        if not request_defaults:
            return payload

        merged = {**payload}
        chat_key_aliases = {
            "maxOutputTokens": "max_tokens",
            "max_output_tokens": "max_tokens",
            "maxTokens": "max_tokens",
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
                merged["extra_body"] = self._merge_request_records(existing_record, value)
                continue
            normalized_key = chat_key_aliases.get(key, key)
            if normalized_key not in chat_allowed_keys:
                continue
            if isinstance(value, str) and value.strip().lower() in skipped_values:
                continue
            if normalized_key == "max_tokens" and isinstance(value, int) and value > 0:
                merged[normalized_key] = value
                continue
            if normalized_key == "stop" and key == "stopSequences":
                merged[normalized_key] = value
                continue
            merged[normalized_key] = value

        return merged

    def _provider_cache_key(self, provider: ProviderConfig, api_key: str | None) -> tuple[str, str]:
        try:
            provider_fingerprint = json.dumps(
                provider.model_dump(mode="json", by_alias=True, exclude_none=True),
                ensure_ascii=True,
                sort_keys=True,
            )
        except Exception:
            provider_fingerprint = repr(provider)
        return (
            provider_fingerprint,
            api_key.strip() if isinstance(api_key, str) else "",
        )

    def _get_cached_models(self, provider: ProviderConfig, api_key: str | None) -> ProviderModelsResponse | None:
        cache_key = self._provider_cache_key(provider, api_key)
        cached = self._models_cache.get(cache_key)
        if not cached:
            return None
        cached_at, response = cached
        if monotonic() - cached_at > self._MODEL_CACHE_TTL_SECONDS:
            self._models_cache.pop(cache_key, None)
            return None
        return response.model_copy(update={"cache_hit": True})

    def _store_cached_models(
        self,
        provider: ProviderConfig,
        api_key: str | None,
        response: ProviderModelsResponse,
    ) -> None:
        if not response.listed:
            return
        cache_key = self._provider_cache_key(provider, api_key)
        self._models_cache[cache_key] = (monotonic(), response.model_copy(update={"cache_hit": False}))

    def _resolve_model(self, override: str | None = None) -> str:
        if override and override.strip():
            return override.strip()
        if self._config and self._config.model.strip():
            return self._config.model.strip()
        return "gpt-4o-mini"

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
        capabilities = getattr(config, "capabilities", None) if config is not None else None
        tools_enabled = bool(getattr(capabilities, "tools", False))

        if not attachments_present:
            return {
                "attachments_present": False,
                "image_attachment_count": 0,
                "attachments_delivered_to_model": False,
                "attachments_delivery_path": "not_sent",
                "attachments_delivery_reason": "no_attachments",
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

        if not tools_enabled:
            return {
                "attachments_present": True,
                "image_attachment_count": image_attachment_count,
                "attachments_delivered_to_model": False,
                "attachments_delivery_path": "not_sent",
                "attachments_delivery_reason": "tools_not_available",
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

    def _model_candidates(self, override: str | None = None) -> list[str]:
        primary = self._resolve_model(override)
        normalized = primary.strip()
        candidates: list[str] = []

        def add(candidate: str | None) -> None:
            value = candidate.strip() if isinstance(candidate, str) else ""
            if value and value not in candidates:
                candidates.append(value)

        add(normalized)
        lowered = normalized.lower()
        add(lowered)
        add(lowered.replace(".", "-"))
        add(lowered.replace("-", "."))
        add(lowered.replace("_", "-"))
        add(lowered.replace("_", "."))
        add(lowered.replace(".", "").replace("-", "").replace("_", ""))

        if lowered == "mimo-v2.5" or normalized == "MiMo-V2.5":
            add("mimo-v2.5")
            add("mimo-v2.5-pro")

        return candidates

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
        match = re.search(r"(?:status|error code:)\s*(\d{3})", str(error), re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _classify_error(self, error: Exception) -> tuple[str, bool, int | None, bool, bool | None]:
        message = str(error).strip()
        lowered = message.lower()
        status_code = self._extract_status_code(error)

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
        if isinstance(error, TimeoutError) or isinstance(error, socket.timeout) or "timeout" in lowered:
            return ("timeout", True, status_code, False, None)
        if isinstance(error, OSError) or "connection refused" in lowered or "name or service not known" in lowered:
            return ("network", True, status_code, False, None)
        if "malformed" in lowered or "invalid json" in lowered or "unexpected response" in lowered:
            return ("malformed_response", False, status_code, True, None)
        if status_code and 500 <= status_code <= 599:
            return ("network", True, status_code, False, None)
        return ("unknown", False, status_code, False, None)

    def _detail_from_category(
        self,
        category: str,
        *,
        provider: ProviderConfig,
        error: Exception | None = None,
    ) -> str:
        error_message = str(error) if error is not None else ""
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

    def _normalize_model_id(self, value: object) -> str | None:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return None

    def _resolve_model_from_list(self, requested_model: str, available_models: list[str]) -> str | None:
        requested = requested_model.strip()
        if not requested or not available_models:
            return None

        requested_lower = requested.lower()
        normalized_candidates = self._model_candidates(requested)
        available_by_lower = {model.lower(): model for model in available_models}
        available_by_flat = {
            model.lower().replace(".", "").replace("-", "").replace("_", ""): model
            for model in available_models
        }

        for candidate in normalized_candidates:
            direct = available_by_lower.get(candidate.lower())
            if direct:
                return direct

            flattened = candidate.lower().replace(".", "").replace("-", "").replace("_", "")
            fuzzy = available_by_flat.get(flattened)
            if fuzzy:
                return fuzzy

        return available_by_lower.get(requested_lower)

    def _models_response_from_ids(
        self,
        provider: ProviderConfig,
        models: list[str],
        *,
        diagnostics: list[str],
        listed: bool = True,
    ) -> ProviderModelsResponse:
        unique_models = sorted({model for model in models if model}, key=str.lower)
        resolved = self._resolve_model_from_list(provider.model, unique_models)
        resolved_from_input = bool(resolved and resolved != provider.model)
        detail = (
            f"Fetched {len(unique_models)} models."
            if unique_models
            else "Provider responded, but did not return any visible models."
        )
        if resolved:
            detail += f" Resolved configured model to {resolved}."
        return ProviderModelsResponse(
            ok=bool(unique_models),
            detail=detail,
            available_models=unique_models,
            resolved_model=resolved,
            resolved_from_input=resolved_from_input,
            listed=listed,
            diagnostics=[
                *diagnostics,
                f"Listed {len(unique_models)} models from provider {provider.name}.",
                *( [f"Resolved configured model to {resolved}."] if resolved else [] ),
            ],
        )

    def _anthropic_list_models(self, provider: ProviderConfig, api_key: str) -> ProviderModelsResponse:
        diagnostics = ["Using native anthropic_messages model listing."]
        with httpx.Client(timeout=60.0) as client:
            response = client.get(
                f"{self._anthropic_base_url(provider)}/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Anthropic Models list failed (status {response.status_code}): "
                f"{response.text[:500]}"
            )
        body = response.json()
        models: list[str] = []
        for item in body.get("data") or []:
            if not isinstance(item, dict):
                continue
            model_id = self._normalize_model_id(item.get("id"))
            if model_id:
                models.append(model_id)
        return self._models_response_from_ids(provider, models, diagnostics=diagnostics)

    def _gemini_models_endpoint(self, provider: ProviderConfig) -> str:
        base_url = str(provider.base_url or "").strip().rstrip("/")
        if not base_url:
            base_url = "https://generativelanguage.googleapis.com/v1beta"
        if base_url.endswith(":generateContent"):
            base_url = base_url.rsplit("/models/", 1)[0] if "/models/" in base_url else base_url
        if "/models/" in base_url:
            base_url = base_url.rsplit("/models/", 1)[0]
        if base_url.rstrip("/").endswith("/models"):
            return base_url
        if base_url.endswith("/v1") or base_url.endswith("/v1beta"):
            return f"{base_url}/models"
        return f"{base_url}/v1beta/models"

    def _gemini_base_url_is_google_native(self, provider: ProviderConfig) -> bool:
        return "googleapis.com" in str(provider.base_url or "").strip().lower()

    def _gemini_fallback_to_openai_model_list(
        self,
        provider: ProviderConfig,
        api_key: str,
        *,
        diagnostics: list[str],
        failure_detail: str,
    ) -> ProviderModelsResponse:
        diagnostics = [
            *diagnostics,
            "Native Gemini model listing failed on a non-Google endpoint; trying OpenAI-compatible /models for this gateway.",
            failure_detail,
        ]
        fallback = self._openai_list_models(provider, api_key)
        return fallback.model_copy(
            update={
                "diagnostics": [*diagnostics, *fallback.diagnostics],
            }
        )

    def _gemini_list_models(self, provider: ProviderConfig, api_key: str) -> ProviderModelsResponse:
        diagnostics = ["Using native gemini_generate_content model listing."]
        with httpx.Client(timeout=60.0) as client:
            response = client.get(
                self._gemini_models_endpoint(provider),
                headers={
                    "x-goog-api-key": api_key,
                    "content-type": "application/json",
                },
            )
        if response.status_code >= 400:
            if not self._gemini_base_url_is_google_native(provider):
                return self._gemini_fallback_to_openai_model_list(
                    provider,
                    api_key,
                    diagnostics=diagnostics,
                    failure_detail=(
                        f"Gemini Models list failed (status {response.status_code}): "
                        f"{response.text[:500]}"
                    ),
                )
            raise RuntimeError(
                f"Gemini Models list failed (status {response.status_code}): "
                f"{response.text[:500]}"
            )
        body = response.json()
        models: list[str] = []
        for item in body.get("models") or []:
            if not isinstance(item, dict):
                continue
            raw_name = self._normalize_model_id(item.get("name"))
            if not raw_name:
                continue
            models.append(raw_name.removeprefix("models/"))
        return self._models_response_from_ids(provider, models, diagnostics=diagnostics)

    def _openai_list_models(self, provider: ProviderConfig, api_key: str) -> ProviderModelsResponse:
        client = self._create_sync_client(provider, api_key)
        response = client.models.list()
        models: list[str] = []

        for item in response:
            model_id = self._normalize_model_id(getattr(item, "id", None))
            if model_id:
                models.append(model_id)

        return self._models_response_from_ids(
            provider,
            models,
            diagnostics=[f"Using OpenAI-compatible model listing for provider {provider.name}."],
        )

    def list_models(self, provider: ProviderConfig, api_key: str | None) -> ProviderModelsResponse:
        if not api_key:
            return ProviderModelsResponse(
                ok=False,
                detail="Provider config is saved, but no API key is available. Trainer cannot fetch models until you add one.",
                error_category="missing_api_key",
                retryable=False,
                diagnostics=["No API key supplied for model listing."],
            )

        cached = self._get_cached_models(provider, api_key)
        if cached is not None:
            return cached

        try:
            protocol = self._configured_protocol(provider)
            if protocol == "anthropic_messages":
                result = self._anthropic_list_models(provider, api_key)
            elif protocol == "gemini_generate_content":
                result = self._gemini_list_models(provider, api_key)
            else:
                result = self._openai_list_models(provider, api_key)
            self._store_cached_models(provider, api_key, result)
            return result
        except Exception as exc:  # pragma: no cover - network dependent
            category, retryable, status_code, _, _ = self._classify_error(exc)
            return ProviderModelsResponse(
                ok=False,
                detail=self._detail_from_category(category, provider=provider, error=exc),
                error_category=category,
                retryable=retryable,
                status_code=status_code,
                diagnostics=[
                    "Model listing request failed.",
                    str(exc),
                ],
            )

    async def _create_chat_completion(
        self,
        *,
        client: Any,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        stream: bool = False,
    ) -> tuple[Any, str]:
        last_error: Exception | None = None
        last_model = self._resolve_model(model)

        for candidate in self._model_candidates(model):
            last_model = candidate
            try:
                request_payload = self._apply_request_defaults(
                    {
                        "model": candidate,
                        "messages": messages,  # type: ignore[arg-type]
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "stream": stream,
                    }
                )
                response = await client.chat.completions.create(**request_payload)
                return response, candidate
            except Exception as exc:
                last_error = exc
                if not self._is_model_not_supported_error(exc):
                    raise

        if last_error is not None:
            raise last_error

        raise RuntimeError(f"Unable to resolve a usable model for {last_model}.")

    def _language_probe_result(
        self,
        *,
        client: Any,
        model: str,
        provider: ProviderConfig | None = None,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> dict[str, object]:
        def natural_language_probe_result() -> dict[str, object]:
            if not _prefers_chinese(response_language):
                return {"ok": False}
            try:
                request_payload = self._apply_request_defaults(
                    {
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Reply in Chinese only. Keep required phrases exactly. Do not explain or add quotes.",
                            },
                            {
                                "role": "user",
                                "content": _NATURAL_LANGUAGE_PROBE_PROMPT,
                            },
                        ],
                        "temperature": 0,
                        "max_tokens": 96,
                    },
                    provider,
                )
                response = client.chat.completions.create(**request_payload)
            except Exception:  # pragma: no cover - network dependent
                return {"ok": False}
            content = response.choices[0].message.content if response.choices else None
            preview = _compact_visible_text(content)
            if not preview:
                return {"ok": False}
            if _looks_like_input_corruption_reply(preview):
                return {"ok": False}
            if not _contains_cjk(preview):
                return {"ok": False}
            if not all(fragment in preview for fragment in _NATURAL_LANGUAGE_PROBE_FRAGMENTS):
                return {"ok": False}
            return {
                "ok": True,
                "detail": _localized_text(
                    (
                        "Natural-language zh-CN probe succeeded after the strict echo probe was unstable. "
                        "Trainer can keep using this connection for Chinese coaching."
                    ),
                    "鑷劧涓枃鎺㈡祴閫氳繃浜嗭細铏界劧涓ユ牸鍥炴樉鎺㈡祴涓嶇ǔ瀹氾紝浣嗚繖鏉¤繛鎺ヤ粛鑳借緭鍑哄彲鐢ㄧ殑涓枃鏁欏鍙ュ瓙銆?,
                    response_language,
                ),
                "preview": preview,
                "kind": "natural_language_fallback",
            }

        previews: list[str] = []
        probe_variants: list[tuple[str, str, str]] = []
        message_probe = _message_probe_variant(probe_message)
        if message_probe is not None:
            probe_variants.append((message_probe[0], message_probe[1], "message"))
        if _prefers_chinese(response_language):
            probe_variants.extend(
                (prompt_text, expected_output, "generic")
                for prompt_text, expected_output in _LANGUAGE_PROBE_VARIANTS
            )
        if not probe_variants:
            return {
                "ok": True,
                "detail": "Language integrity probe skipped for this English-only flow.",
                "preview": "",
                "skipped": True,
            }
        for _attempt in range(2):
            for prompt_text, expected_output, probe_kind in probe_variants:
                try:
                    request_payload = self._apply_request_defaults(
                        {
                            "model": model,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": "Return exactly the requested text. Do not explain or add quotes.",
                                },
                                {
                                    "role": "user",
                                    "content": prompt_text,
                                },
                            ],
                            "temperature": 0,
                            "max_tokens": 96,
                        },
                        provider,
                    )
                    response = client.chat.completions.create(**request_payload)
                except Exception as exc:  # pragma: no cover - network dependent
                    return {
                        "ok": False,
                        "category": "language_probe_inconclusive",
                        "detail": _localized_text(
                            (
                                "Language integrity probe could not complete after connectivity succeeded. "
                                f"Follow-up check failed: {exc}"
                            ),
                            f"璇█瀹屾暣鎬ф帰娴嬪湪杩為€氭€ф垚鍔熷悗娌¤兘瀹屾垚銆傚悗缁鏌ュけ璐ワ細{exc}",
                            response_language,
                        ),
                        "preview": "",
                    }

                content = response.choices[0].message.content if response.choices else None
                preview = _compact_visible_text(content)
                if not preview:
                    return {
                        "ok": False,
                        "category": "language_probe_inconclusive",
                        "detail": _localized_text(
                            (
                                "Language integrity probe returned no visible content after connectivity succeeded. "
                                "Trainer cannot verify non-English input on this connection."
                            ),
                            (
                                "璇█瀹屾暣鎬ф帰娴嬪湪杩為€氭€ф垚鍔熷悗娌℃湁鎷垮埌鍙鍐呭銆?
                                "Trainer 鐜板湪杩樹笉鑳介獙璇佽繖鏉￠摼璺笂鐨勯潪 English 杈撳叆銆?
                            ),
                            response_language,
                        ),
                        "preview": "",
                    }
                previews.append(preview)
                if expected_output in preview:
                    continue
                fallback_probe = natural_language_probe_result()
                if fallback_probe.get("ok") is True:
                    return fallback_probe
                if _looks_like_input_corruption_reply(preview, expected_probe=expected_output):
                    if probe_kind == "message":
                        detail = _localized_text(
                            (
                                "Provider reachable, but it corrupted the actual mixed-language coaching "
                                "message into question marks before the model saw it."
                            ),
                            "杩欎釜 provider 鍙揪锛屼絾鍦ㄦā鍨嬬湅鍒颁箣鍓嶅氨鎶婂綋鍓嶈繖鏉℃贩鍚堣瑷€鏁欏娑堟伅鍙樻垚浜嗕竴涓查棶鍙枫€?,
                            response_language,
                        )
                    else:
                        detail = _localized_text(
                            (
                                "Provider reachable, but it corrupted Chinese input into question marks "
                                "before the model saw it."
                            ),
                            "杩欎釜 provider 鍙揪锛屼絾鍦ㄦā鍨嬬湅鍒版秷鎭箣鍓嶆妸涓枃杈撳叆鍙樻垚浜嗕竴涓查棶鍙枫€?,
                            response_language,
                        )
                    return {
                        "ok": False,
                        "category": "language_corruption",
                        "detail": detail,
                        "preview": preview,
                    }
                detail = _localized_text(
                    (
                        "Language integrity probe was inconclusive. The provider replied, but it did not preserve "
                        "the message-derived probe text exactly enough for Trainer to trust it."
                        if probe_kind == "message"
                        else (
                            "Language integrity probe was inconclusive. The provider replied, but it did not preserve "
                            "the mixed-language probe text exactly enough for Trainer to trust it."
                        )
                    ),
                    (
                        "璇█瀹屾暣鎬ф帰娴嬫病鏈夐€氳繃銆俻rovider 铏界劧鍥炲浜嗭紝"
                        "浣嗘病鏈夋妸鍩轰簬褰撳墠娑堟伅鐢熸垚鐨勬帰娴嬫枃鏈畬鏁翠繚鐣欎笅鏉ワ紝Trainer 杩樹笉鑳戒俊浠昏繖鏉￠摼璺€?
                        if probe_kind == "message"
                        else (
                            "璇█瀹屾暣鎬ф帰娴嬫病鏈夐€氳繃銆俻rovider 铏界劧鍥炲浜嗭紝"
                            "浣嗘病鏈夋妸娣峰悎璇█鎺㈡祴鏂囨湰瀹屾暣淇濈暀涓嬫潵锛孴rainer 杩樹笉鑳戒俊浠昏繖鏉￠摼璺€?
                        )
                    ),
                    response_language,
                )
                return {
                    "ok": False,
                    "category": "language_probe_inconclusive",
                    "detail": detail,
                    "preview": preview,
                }

        final_detail = _localized_text(
            (
                "Language integrity probe preserved the message-derived and mixed CJK/ASCII probe text across all checks."
                if message_probe is not None or _prefers_chinese(response_language)
                else "Language integrity probe preserved the mixed CJK/ASCII probe text across all checks."
            ),
            (
                "璇█瀹屾暣鎬ф帰娴嬮€氳繃浜嗭細鍩轰簬褰撳墠娑堟伅鐢熸垚鐨勬帰娴嬫枃鏈拰 mixed CJK/ASCII 鎺㈡祴鏂囨湰閮借瀹屾暣淇濈暀涓嬫潵浜嗐€?
                if message_probe is not None or _prefers_chinese(response_language)
                else "璇█瀹屾暣鎬ф帰娴嬮€氳繃浜嗭細mixed CJK/ASCII 鎺㈡祴鏂囨湰鍦ㄦ墍鏈夋鏌ラ噷閮借瀹屾暣淇濈暀涓嬫潵浜嗐€?
            ),
            response_language,
        )
        return {
            "ok": True,
            "detail": final_detail,
            "preview": previews[-1] if previews else "",
            "kind": "strict_integrity",
        }

    def _language_probe_result_resilient(
        self,
        *,
        client: Any,
        model: str,
        provider: ProviderConfig | None = None,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> dict[str, object]:
        zh_natural_success = (
            "\u81ea\u7136 zh-CN \u63a2\u6d4b\u5df2\u901a\u8fc7\uff1a"
            "\u867d\u7136\u4e25\u683c\u56de\u663e\u63a2\u6d4b\u4e0d\u7a33\u5b9a\uff0c"
            "Trainer \u4ecd\u7136\u80fd\u5728\u8fd9\u6761\u8fde\u63a5\u4e0a\u7ee7\u7eed zh-CN \u6559\u7ec3\u3002"
        )
        zh_probe_failed = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u5728\u8fde\u901a\u6027\u6210\u529f\u540e\u6ca1\u80fd\u5b8c\u6210\u3002"
            "\u540e\u7eed\u68c0\u67e5\u5931\u8d25\uff1a"
        )
        zh_no_visible = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u5728\u8fde\u901a\u6027\u6210\u529f\u540e\u6ca1\u6709\u62ff\u5230\u53ef\u89c1\u5185\u5bb9\u3002"
            "Trainer \u73b0\u5728\u8fd8\u4e0d\u80fd\u9a8c\u8bc1\u8fd9\u6761\u94fe\u8def\u4e0a\u7684\u975e English \u8f93\u5165\u3002"
        )
        zh_message_corruption = (
            "\u8fd9\u4e2a provider \u53ef\u8fbe\uff0c"
            "\u4f46\u5728\u6a21\u578b\u770b\u5230\u4e4b\u524d\u5c31\u628a\u5f53\u524d\u8fd9\u6761\u6df7\u5408\u8bed\u8a00\u6559\u7ec3\u6d88\u606f"
            "\u53d8\u6210\u4e86\u4e00\u4e32\u95ee\u53f7\u3002"
        )
        zh_generic_corruption = (
            "\u8fd9\u4e2a provider \u53ef\u8fbe\uff0c"
            "\u4f46\u5728\u6a21\u578b\u770b\u5230\u6d88\u606f\u4e4b\u524d\u628a\u4e2d\u6587\u8f93\u5165\u53d8\u6210\u4e86\u4e00\u4e32\u95ee\u53f7\u3002"
        )
        zh_message_inconclusive = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u6ca1\u6709\u901a\u8fc7\u3002provider \u867d\u7136\u56de\u590d\u4e86\uff0c"
            "\u4f46\u6ca1\u6709\u628a\u57fa\u4e8e\u5f53\u524d\u6d88\u606f\u751f\u6210\u7684\u63a2\u6d4b\u6587\u672c\u5b8c\u6574\u4fdd\u7559\u4e0b\u6765\uff0c"
            "Trainer \u8fd8\u4e0d\u80fd\u4fe1\u4efb\u8fd9\u6761\u94fe\u8def\u3002"
        )
        zh_generic_inconclusive = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u6ca1\u6709\u901a\u8fc7\u3002provider \u867d\u7136\u56de\u590d\u4e86\uff0c"
            "\u4f46\u6ca1\u6709\u628a mixed CJK/ASCII \u63a2\u6d4b\u6587\u672c\u5b8c\u6574\u4fdd\u7559\u4e0b\u6765\uff0c"
            "Trainer \u8fd8\u4e0d\u80fd\u4fe1\u4efb\u8fd9\u6761\u94fe\u8def\u3002"
        )
        zh_retry_success = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u5728\u91cd\u8bd5\u540e\u6062\u590d\u6210\u529f\uff1a"
            "\u81f3\u5c11\u6709\u4e00\u6761\u57fa\u4e8e\u5f53\u524d\u6d88\u606f\u6216 mixed CJK/ASCII \u7684\u63a2\u6d4b\u6587\u672c"
            "\u88ab\u53ef\u7528\u5730\u5b8c\u6574\u4fdd\u7559\u4e86\u3002"
        )
        zh_strict_success = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u901a\u8fc7\u4e86\uff1a"
            "\u57fa\u4e8e\u5f53\u524d\u6d88\u606f\u751f\u6210\u7684\u63a2\u6d4b\u6587\u672c\u548c mixed CJK/ASCII \u63a2\u6d4b\u6587\u672c"
            "\u90fd\u88ab\u5b8c\u6574\u4fdd\u7559\u4e0b\u6765\u4e86\u3002"
        )
        zh_generic_success = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u901a\u8fc7\u4e86\uff1a"
            "mixed CJK/ASCII \u63a2\u6d4b\u6587\u672c\u5728\u6240\u6709\u68c0\u67e5\u91cc\u90fd\u88ab\u5b8c\u6574\u4fdd\u7559\u4e0b\u6765\u4e86\u3002"
        )
        zh_no_signal = (
            "\u8bed\u8a00\u5b8c\u6574\u6027\u63a2\u6d4b\u5728\u8fde\u901a\u6027\u6210\u529f\u540e\u4ecd\u6ca1\u6709\u62ff\u5230\u53ef\u7528\u4fe1\u53f7\u3002"
            "Trainer \u73b0\u5728\u8fd8\u4e0d\u80fd\u9a8c\u8bc1\u8fd9\u6761\u94fe\u8def\u4e0a\u7684\u975e English \u8f93\u5165\u3002"
        )

        def natural_language_probe_result() -> dict[str, object]:
            if not _prefers_chinese(response_language):
                return {"ok": False}
            try:
                request_payload = self._apply_request_defaults(
                    {
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Reply in Chinese only. Keep required phrases exactly. Do not explain or add quotes.",
                            },
                            {
                                "role": "user",
                                "content": _NATURAL_LANGUAGE_PROBE_PROMPT,
                            },
                        ],
                        "temperature": 0,
                        "max_tokens": 96,
                    },
                    provider,
                )
                response = client.chat.completions.create(**request_payload)
            except Exception:  # pragma: no cover - network dependent
                return {"ok": False}
            content = response.choices[0].message.content if response.choices else None
            preview = _compact_visible_text(content)
            if not preview:
                return {"ok": False}
            if _looks_like_input_corruption_reply(preview):
                return {"ok": False}
            if not _contains_cjk(preview):
                return {"ok": False}
            if not all(fragment in preview for fragment in _NATURAL_LANGUAGE_PROBE_FRAGMENTS):
                return {"ok": False}
            return {
                "ok": True,
                "detail": _localized_text(
                    (
                        "Natural-language zh-CN probe succeeded after the strict echo probe was unstable. "
                        "Trainer can keep using this connection for Chinese coaching."
                    ),
                    zh_natural_success,
                    response_language,
                ),
                "preview": preview,
                "kind": "natural_language_fallback",
            }

        previews: list[str] = []
        probe_variants: list[tuple[str, str, str]] = []
        message_probe = _message_probe_variant(probe_message)
        if message_probe is not None:
            probe_variants.append((message_probe[0], message_probe[1], "message"))
        if _prefers_chinese(response_language):
            probe_variants.extend(
                (prompt_text, expected_output, "generic")
                for prompt_text, expected_output in _LANGUAGE_PROBE_VARIANTS
            )
        if not probe_variants:
            return {
                "ok": True,
                "detail": "Language integrity probe skipped for this English-only flow.",
                "preview": "",
                "skipped": True,
            }

        last_inconclusive: dict[str, object] | None = None
        saw_blank_preview = False
        for _attempt in range(2):
            natural_fallback_attempted = False
            for prompt_text, expected_output, probe_kind in probe_variants:
                try:
                    request_payload = self._apply_request_defaults(
                        {
                            "model": model,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": "Return exactly the requested text. Do not explain or add quotes.",
                                },
                                {
                                    "role": "user",
                                    "content": prompt_text,
                                },
                            ],
                            "temperature": 0,
                            "max_tokens": 96,
                        },
                        provider,
                    )
                    response = client.chat.completions.create(**request_payload)
                except Exception as exc:  # pragma: no cover - network dependent
                    return {
                        "ok": False,
                        "category": "language_probe_inconclusive",
                        "detail": _localized_text(
                            (
                                "Language integrity probe could not complete after connectivity succeeded. "
                                f"Follow-up check failed: {exc}"
                            ),
                            f"{zh_probe_failed}{exc}",
                            response_language,
                        ),
                        "preview": "",
                    }

                content = response.choices[0].message.content if response.choices else None
                preview = _compact_visible_text(content)
                if not preview:
                    saw_blank_preview = True
                    last_inconclusive = {
                        "ok": False,
                        "category": "language_probe_inconclusive",
                        "detail": _localized_text(
                            (
                                "Language integrity probe returned no visible content after connectivity succeeded. "
                                "Trainer cannot verify non-English input on this connection."
                            ),
                            zh_no_visible,
                            response_language,
                        ),
                        "preview": "",
                    }
                    if not natural_fallback_attempted:
                        natural_fallback_attempted = True
                        fallback_probe = natural_language_probe_result()
                        if fallback_probe.get("ok") is True:
                            return fallback_probe
                    continue

                previews.append(preview)
                if expected_output in preview:
                    recovered = saw_blank_preview or last_inconclusive is not None
                    detail = _localized_text(
                        (
                            "Language integrity probe recovered after retry and preserved usable message-derived or mixed "
                            "CJK/ASCII text."
                            if recovered
                            else (
                                "Language integrity probe preserved the message-derived and mixed CJK/ASCII probe text across all checks."
                                if message_probe is not None or _prefers_chinese(response_language)
                                else "Language integrity probe preserved the mixed CJK/ASCII probe text across all checks."
                            )
                        ),
                        zh_retry_success
                        if recovered
                        else (
                            zh_strict_success
                            if message_probe is not None or _prefers_chinese(response_language)
                            else zh_generic_success
                        ),
                        response_language,
                    )
                    return {
                        "ok": True,
                        "detail": detail,
                        "preview": preview,
                        "kind": "strict_integrity",
                    }

                if _looks_like_input_corruption_reply(preview, expected_probe=expected_output):
                    return {
                        "ok": False,
                        "category": "language_corruption",
                        "detail": _localized_text(
                            (
                                "Provider reachable, but it corrupted the actual mixed-language coaching "
                                "message into question marks before the model saw it."
                            )
                            if probe_kind == "message"
                            else (
                                "Provider reachable, but it corrupted Chinese input into question marks "
                                "before the model saw it."
                            ),
                            zh_message_corruption if probe_kind == "message" else zh_generic_corruption,
                            response_language,
                        ),
                        "preview": preview,
                    }

                if not natural_fallback_attempted:
                    natural_fallback_attempted = True
                    fallback_probe = natural_language_probe_result()
                    if fallback_probe.get("ok") is True:
                        return fallback_probe

                last_inconclusive = {
                    "ok": False,
                    "category": "language_probe_inconclusive",
                    "detail": _localized_text(
                        (
                            "Language integrity probe was inconclusive. The provider replied, but it did not preserve "
                            "the message-derived probe text exactly enough for Trainer to trust it."
                        )
                        if probe_kind == "message"
                        else (
                            "Language integrity probe was inconclusive. The provider replied, but it did not preserve "
                            "the mixed-language probe text exactly enough for Trainer to trust it."
                        ),
                        zh_message_inconclusive if probe_kind == "message" else zh_generic_inconclusive,
                        response_language,
                    ),
                    "preview": preview,
                }

        return last_inconclusive or {
            "ok": False,
            "category": "language_probe_inconclusive",
            "detail": _localized_text(
                (
                    "Language integrity probe returned no usable signal after connectivity succeeded. "
                    "Trainer cannot verify non-English input on this connection yet."
                ),
                zh_no_signal,
                response_language,
            ),
            "preview": previews[-1] if previews else "",
        }

    def detect_language_corruption(
        self,
        *,
        message: str,
        reply: str,
        response_language: str | None = None,
    ) -> bool:
        if (
            (_contains_cjk(message) or _prefers_chinese(response_language))
            and _looks_like_input_corruption_reply(reply)
        ):
            return True
        return (
            _mixed_script_reply_corruption_detail(
                reply,
                message=message,
                response_language=response_language,
            )
            is not None
        )

    def _language_corruption_lane_note(
        self,
        scenario: str | None,
        response_language: str | None,
    ) -> str:
        normalized = str(scenario or "").strip().lower()
        if normalized == "remote_workspace":
            return _localized_text(
                "I am still keeping this turn in the VS Code remote lane.",
                "褰撳墠杩欒疆鎴戜粛鐒朵繚鐣欏湪 VS Code remote 杩欐潯涓荤嚎閲屻€?,
                response_language,
            )
        if normalized == "debug_loop":
            return _localized_text(
                "I am still keeping this turn in the VS Code debug lane.",
                "褰撳墠杩欒疆鎴戜粛鐒朵繚鐣欏湪 VS Code debug 杩欐潯涓荤嚎閲屻€?,
                response_language,
            )
        if normalized == "function_guidance":
            return _localized_text(
                "I am still keeping this turn in the function-guidance lane.",
                "褰撳墠杩欒疆鎴戜粛鐒朵繚鐣欏湪 function guidance 杩欐潯涓荤嚎閲屻€?,
                response_language,
            )
        if normalized == "project_adaptation":
            return _localized_text(
                "I am still keeping this turn in the existing-project adaptation lane.",
                "褰撳墠杩欒疆鎴戜粛鐒朵繚鐣欏湪 existing-project adaptation 杩欐潯涓荤嚎閲屻€?,
                response_language,
            )
        return ""

    def language_corruption_summary(
        self,
        response_language: str | None,
        scenario: str | None = None,
    ) -> str:
        summary = _localized_text(
            "This provider is reachable, but it corrupted Chinese input into question marks before the model saw the message.",
            "杩欎釜 provider 鍙揪锛屼絾鍦ㄦā鍨嬬湅鍒版秷鎭箣鍓嶆妸涓枃杈撳叆鍙樻垚浜嗕竴涓查棶鍙枫€?,
            response_language,
        )
        lane_note = self._language_corruption_lane_note(scenario, response_language)
        if lane_note:
            return f"{summary} {lane_note}"
        return summary

    def language_corruption_next_step(
        self,
        response_language: str | None,
        scenario: str | None = None,
    ) -> str:
        normalized = str(scenario or "").strip().lower()
        if normalized == "remote_workspace":
            return _localized_text(
                "Switch provider or gateway, or continue this remote lesson in English first. If you stay here, tell me whether the workspace is SSH, tunnels, dev container, WSL, or local, plus one real path or host label.",
                "鍏堝垏鎹?provider 鎴?gateway锛屾垨鑰呭厛鐢?English 缁х画杩欒妭 remote lesson銆?
                "濡傛灉缁х画鐣欏湪杩欓噷锛岃鍛婅瘔鎴戞槸 SSH銆乼unnels銆乨ev container銆乄SL 杩樻槸 local锛屽苟缁欐垜涓€涓湡瀹炵殑璺緞鎴?host label銆?,
                response_language,
            )
        if normalized == "debug_loop":
            return _localized_text(
                "Switch provider or gateway, or continue this debug lesson in English first. If you stay here, tell me where you will pause first and which single value, branch, or stack frame you expect to inspect.",
                "鍏堝垏鎹?provider 鎴?gateway锛屾垨鑰呭厛鐢?English 缁х画杩欒妭 debug lesson銆?
                "濡傛灉缁х画鐣欏湪杩欓噷锛岃鍛婅瘔鎴戜綘浼氬厛鍋滃湪鍝釜鏂偣锛屼互鍙婂噯澶囨鏌ュ摢涓€涓€笺€佸垎鏀垨 stack frame銆?,
                response_language,
            )
        if normalized == "function_guidance":
            return _localized_text(
                "Switch provider or gateway, or continue this function-guidance lesson in English first. If you stay here, give me the function name and one call site you can open right now.",
                "鍏堝垏鎹?provider 鎴?gateway锛屾垨鑰呭厛鐢?English 缁х画杩欒妭 function-guidance lesson銆?
                "濡傛灉缁х画鐣欏湪杩欓噷锛岃缁欐垜鍑芥暟鍚嶏紝浠ュ強浣犵幇鍦ㄥ氨鑳芥墦寮€鐨勪竴涓?call site銆?,
                response_language,
            )
        if normalized == "project_adaptation":
            return _localized_text(
                "Switch provider or gateway, or continue this project-adaptation lesson in English first. If you stay here, tell me what must stay stable, what must change, and the first boundary you want to adapt.",
                "鍏堝垏鎹?provider 鎴?gateway锛屾垨鑰呭厛鐢?English 缁х画杩欒妭 project-adaptation lesson銆?
                "濡傛灉缁х画鐣欏湪杩欓噷锛岃鍛婅瘔鎴戜粈涔堝繀椤讳繚鎸佺ǔ瀹氥€佷粈涔堝繀椤诲彉鍖栵紝浠ュ強浣犳兂鍏堥€傞厤鐨勭涓€鏉¤竟鐣屻€?,
                response_language,
            )
        return _localized_text(
            "Switch provider or gateway, or continue this test in English first, before resuming the coach thread.",
            "鍏堝垏鎹?provider 鎴?gateway锛屾垨鑰呭厛鐢?English 瀹屾垚杩欐娴嬭瘯锛屽啀鍥炴潵缁х画 coach thread銆?,
            response_language,
        )

    def language_corruption_reply(
        self,
        response_language: str | None,
        scenario: str | None = None,
    ) -> str:
        summary = self.language_corruption_summary(response_language, scenario=scenario)
        next_step = self.language_corruption_next_step(response_language, scenario=scenario)
        if _prefers_chinese(response_language):
            return (
                f"{summary}\n\n"
                "Trainer "
                "\u4e0d\u4f1a\u628a\u8fd9\u79cd\u574f\u8f93\u5165\u5047\u88c5\u6210\u6b63\u5e38\u6559\u5b66\uff0c"
                "\u56e0\u4e3a\u6a21\u578b\u6839\u672c\u6ca1\u770b\u5230\u4f60\u7684\u539f\u53e5\u3002"
                f"\n\n\u4e0b\u4e00\u6b65\uff1a{next_step}"
            )
        return (
            f"{summary}\n\n"
            "Trainer will not pretend this is a normal coaching turn, because the model never saw your actual sentence."
            f"\n\nNext step: {next_step}"
        )

    def _record_reply_language_corruption(self, detail: str) -> None:
        self._record_last_reply_failure(
            category="language_corruption",
            detail=detail,
            retryable=False,
            status_code=200,
            provider_reachable=True,
            model_supported=True,
            error=ValueError(detail),
        )

    def _configured_protocol(self, provider: ProviderConfig) -> str:
        return normalize_provider_protocol(getattr(provider, "protocol", None))

    def _plain_completion_protocol(self) -> str:
        provider = self._config or ProviderConfig(
            name="unspecified-provider",
            base_url="",
            api_key_ref="trainer.unspecified",
            model=self._resolve_model(),
        )
        return self._configured_protocol(provider)

    def _plain_completion_uses_agent_binding(self) -> bool:
        return self._plain_completion_protocol() not in {
            "openai_chat_completions",
            "openai_chat_completions_compatible",
        }

    async def _completion_via_agent_binding(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> str:
        provider, _binding = self.build_agent_provider(
            protocol=self._plain_completion_protocol(),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        result = await provider.call(messages, None)
        content = _visible_model_text(result.get("content"))
        self._raise_for_provider_html_shell(content)
        return content

    async def _completion_stream_via_agent_binding(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
    ):
        provider, _binding = self.build_agent_provider(
            protocol=self._plain_completion_protocol(),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        emitted = ""
        async for event in provider.call_stream(messages, None):
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

    def _native_probe_preview(self, content: object | None) -> str:
        return _compact_visible_text(content, limit=240)

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
    ) -> ProviderTestResponse:
        return ProviderTestResponse(
            ok=False,
            detail=(
                f"Provider reachable, but the native {protocol} probe returned no usable visible reply "
                f"for model {provider.model}."
            ),
            error_category="empty_response",
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
        if protocol == "openai_responses":
            client = self._create_sync_client(provider, api_key)
            payload: dict[str, Any] = {
                "model": provider.model,
                "input": prompt,
                "temperature": 0,
                "max_output_tokens": max_tokens,
            }
            if system:
                payload["instructions"] = system
            response = client.responses.create(**payload)
            return self._native_probe_preview(getattr(response, "output_text", ""))

        if protocol == "anthropic_messages":
            payload = {
                "model": provider.model,
                "max_tokens": max(64, max_tokens),
                "system": system
                or "Return visible text in the message content. Do not answer only with hidden reasoning.",
                "messages": [{"role": "user", "content": prompt}],
            }
            payload = self._apply_anthropic_native_probe_defaults(payload, provider)
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{self._anthropic_base_url(provider)}/v1/messages",
                    json=payload,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Anthropic Messages probe failed (status {response.status_code}): "
                    f"{response.text[:500]}"
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
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    self._gemini_endpoint(provider),
                    json=payload,
                    headers={
                        "x-goog-api-key": api_key,
                        "content-type": "application/json",
                    },
                )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Gemini GenerateContent probe failed (status {response.status_code}): "
                    f"{response.text[:500]}"
                )
            body = response.json()
            text_parts: list[str] = []
            for candidate in body.get("candidates") or []:
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content") or {}
                for part in content.get("parts") or []:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
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
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> ProviderTestResponse:
        if not preview:
            return self._native_provider_empty_response(
                protocol=protocol,
                provider=provider,
                diagnostics=diagnostics,
            )

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
                "请只输出可见文字：provider ready。不要只返回 reasoning、tool call 或 hidden text。",
            ]
        return [
            "Reply with exactly: pong",
            (
                "Return one short visible sentence only: provider ready. "
                "Do not return only reasoning, tool calls, or hidden text."
            ),
        ]

    def _apply_anthropic_native_probe_defaults(
        self,
        payload: dict[str, Any],
        provider: ProviderConfig,
    ) -> dict[str, Any]:
        defaults = self._provider_request_defaults(provider)
        if not defaults:
            return payload
        merged = dict(payload)
        extra_body = defaults.get("extra_body")
        if isinstance(extra_body, dict):
            merged.update(extra_body)
        max_tokens = defaults.get("max_tokens", defaults.get("maxTokens"))
        if isinstance(max_tokens, int) and max_tokens > 0:
            merged["max_tokens"] = min(max_tokens, max(64, int(merged.get("max_tokens") or 64)))
        for key in ("temperature", "top_p", "top_k", "stop_sequences"):
            if key in defaults and defaults[key] is not None:
                merged[key] = defaults[key]
        thinking_budget = defaults.get("thinking_budget", defaults.get("thinkingBudget"))
        if isinstance(thinking_budget, int) and thinking_budget > 0:
            merged["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        elif isinstance(thinking_budget, str) and thinking_budget.strip().lower() == "disabled":
            merged.pop("thinking", None)
        return merged

    def _apply_gemini_native_probe_defaults(
        self,
        payload: dict[str, Any],
        provider: ProviderConfig,
    ) -> dict[str, Any]:
        defaults = self._provider_request_defaults(provider)
        if not defaults:
            return payload
        merged = dict(payload)
        extra_body = defaults.get("extra_body")
        if isinstance(extra_body, dict):
            merged.update(extra_body)
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
        return merged

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
            last_error: Exception | None = None
            response = None
            chosen_model = provider.model
            preview = ""
            for candidate in self._model_candidates(provider.model):
                chosen_model = candidate
                try:
                    for attempt, prompt in enumerate(
                        self._native_probe_prompts(response_language),
                        start=1,
                    ):
                        response = client.responses.create(
                            model=candidate,
                            input=prompt,
                            temperature=0,
                            max_output_tokens=32,
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
            diagnostics.append(f"Responses probe succeeded with model {chosen_model}.")
            return self._finalize_native_protocol_test(
                protocol="openai_responses",
                provider=provider,
                api_key=api_key,
                preview=preview,
                diagnostics=diagnostics,
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
                diagnostics=[*diagnostics, str(exc)],
                provider_reachable=provider_reachable,
                model_supported=model_supported,
            )

    def _anthropic_base_url(self, provider: ProviderConfig) -> str:
        base_url = str(provider.base_url or "").strip().rstrip("/")
        if base_url.endswith("/v1"):
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
            with httpx.Client(timeout=60.0) as client:
                for attempt, prompt in enumerate(
                    self._native_probe_prompts(response_language),
                    start=1,
                ):
                    payload = {
                        "model": provider.model,
                        "max_tokens": 64,
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
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                    )
                    if response.status_code >= 400:
                        raise RuntimeError(
                            f"Anthropic Messages probe failed (status {response.status_code}): "
                            f"{response.text[:500]}"
                        )
                    body = response.json()
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
                diagnostics=[*diagnostics, str(exc)],
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
            with httpx.Client(timeout=60.0) as client:
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
                        headers={
                            "x-goog-api-key": api_key,
                            "content-type": "application/json",
                        },
                    )
                    if response.status_code >= 400:
                        raise RuntimeError(
                            f"Gemini GenerateContent probe failed (status {response.status_code}): "
                            f"{response.text[:500]}"
                        )
                    body = response.json()
                    text_parts: list[str] = []
                    for candidate in body.get("candidates") or []:
                        if not isinstance(candidate, dict):
                            continue
                        content = candidate.get("content") or {}
                        for part in content.get("parts") or []:
                            if isinstance(part, dict) and isinstance(part.get("text"), str):
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
                diagnostics=[*diagnostics, str(exc)],
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

    def test(
        self,
        provider: ProviderConfig,
        api_key: str | None,
        *,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> ProviderTestResponse:
        if not api_key:
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
            api_key,
            probe_message,
            response_language,
        )
        if native_result is not None:
            return native_result
        try:
            client = self._create_sync_client(provider, api_key)
            try:
                chosen_model = None
                response = None
                compact_probe, visible_probe = self._native_probe_prompts(response_language)
                diagnostics = []
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
                                "max_tokens": 32,
                            },
                            provider,
                        )
                        response = client.chat.completions.create(**request_payload)
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
                preview = _openai_chat_response_visible_text(response)
                if not preview and isinstance(response, str):
                    raise RuntimeError(f"Malformed response: {_malformed_provider_html_shell_detail()}")
                self._raise_for_provider_html_shell(preview)
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
                                    "max_tokens": 32,
                                },
                                provider,
                            )
                            retry_probe_response = client.chat.completions.create(**retry_probe_request)
                            preview = _openai_chat_response_visible_text(retry_probe_response)
                            self._raise_for_provider_html_shell(preview)
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
                                "max_tokens": 48,
                            },
                            provider,
                        )
                        visible_probe_response = client.chat.completions.create(**visible_probe_request)
                        preview = _openai_chat_response_visible_text(visible_probe_response)
                        self._raise_for_provider_html_shell(preview)
                        if preview:
                            break
                        diagnostics.append("Visible-text probe also returned no usable text.")
                    if not preview:
                        return ProviderTestResponse(
                            ok=False,
                            detail=(
                                "Provider reachable, but the chat probe returned no usable visible reply "
                                f"for model {chosen_model or provider.model}."
                            ),
                            error_category="empty_response",
                            retryable=True,
                            status_code=200,
                            diagnostics=diagnostics,
                            provider_reachable=True,
                            model_supported=True,
                        )
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
                diagnostics.append(f"Probe response preview: {preview}")
                probe_detail = str(language_probe.get("detail") or "").strip()
                if probe_detail:
                    diagnostics.append(probe_detail)
                self.mark_language_integrity_success(
                    message=probe_message,
                    response_language=response_language,
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
                            str(chat_exc),
                        ],
                        provider_reachable=provider_reachable,
                        model_supported=model_supported,
                    )
                models_result = self.list_models(provider, api_key)
                count = len(models_result.available_models)
                if models_result.ok:
                    detail = f"Provider reachable. Listed {count} models."
                    if models_result.resolved_model:
                        detail += f" Resolved configured model to {models_result.resolved_model}."
                    diagnostics = [
                        "Chat probe failed, but model listing succeeded.",
                        str(chat_exc),
                        *models_result.diagnostics,
                    ]
                else:
                    detail = self._detail_from_category(category, provider=provider, error=chat_exc)
                    diagnostics = [
                        "Chat probe failed.",
                        str(chat_exc),
                        *models_result.diagnostics,
                    ]
                return ProviderTestResponse(
                    ok=models_result.ok,
                    detail=detail,
                    error_category=None if models_result.ok else category,
                    retryable=models_result.retryable if not models_result.ok else False,
                    status_code=models_result.status_code if not models_result.ok else None,
                    diagnostics=diagnostics,
                    provider_reachable=models_result.ok or provider_reachable,
                    model_supported=None if models_result.ok else model_supported,
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
                    str(exc),
                ],
                provider_reachable=provider_reachable,
                model_supported=model_supported,
            )

    async def coaching_reply(
        self,
        profile: UserProfile | None,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        self.clear_last_reply_state()
        if not self.has_api_key:
            if not profile:
                return self._missing_api_key_reply(response_language)
            return self._missing_api_key_reply_with_scaffold(
                profile,
                message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
        if not profile:
            return self._onboarding_reply(response_language)
        return await self._llm_reply(
            profile,
            message,
            current_file,
            response_language,
            answer_mode,
            coach_context=coach_context,
            history=history,
        )

    async def _llm_reply(
        self,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        messages = build_coaching_messages(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            history=history,
        )
        model = self._resolve_model()
        try:
            if self._plain_completion_uses_agent_binding():
                content = await self._completion_via_agent_binding(
                    messages,
                    temperature=0.7,
                    max_tokens=1024,
                )
                return self.finalize_coaching_reply(
                    content or "",
                    profile=profile,
                    message=message,
                    current_file=current_file,
                    response_language=response_language,
                    answer_mode=answer_mode,
                    coach_context=coach_context,
                )
            client = self._get_client()
            response, _ = await self._create_chat_completion(
                client=client,
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
            )
            content = _openai_chat_response_visible_text(response)
            self._raise_for_provider_html_shell(content)
            return self.finalize_coaching_reply(
                content or "",
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
        except Exception as exc:
            category, retryable, status_code, provider_reachable, model_supported = self._classify_error(exc)
            provider_config = self._config or ProviderConfig(
                name="unspecified-provider",
                base_url="",
                api_key_ref="trainer.unspecified",
                model=self._resolve_model(),
            )
            detail = self._detail_from_category(
                category,
                provider=provider_config,
                error=exc,
            )
            self._record_last_reply_failure(
                category=category,
                detail=detail,
                retryable=retryable,
                status_code=status_code,
                provider_reachable=provider_reachable,
                model_supported=model_supported,
                error=exc,
            )
            return self._error_reply_with_scaffold(
                exc=exc,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )

    def finalize_coaching_reply(
        self,
        content: str,
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        visible_content = _strip_internal_coach_meta(content)
        if not visible_content.strip():
            return self._fallback_empty_reply(
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
        return self._postprocess_coaching_reply(
            visible_content,
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )

    def _postprocess_coaching_reply(
        self,
        content: str,
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        reply = _strip_leading_html_shell_artifact(content)
        if not reply:
            if _looks_like_provider_html_shell(content):
                detail = _malformed_provider_html_shell_detail()
                self._record_last_reply_failure(
                    category="malformed_response",
                    detail=detail,
                    retryable=False,
                    status_code=200,
                    provider_reachable=True,
                    model_supported=None,
                    error=ValueError(detail),
                )
                return self.provider_failure_reply(
                    "malformed_response",
                    detail,
                    response_language,
                )
            return self._fallback_empty_reply(
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )

        raw_reply_corruption_detail = _mixed_script_reply_corruption_detail(
            reply,
            message=message,
            response_language=response_language,
        )
        if raw_reply_corruption_detail:
            self.clear_language_integrity_success(
                message=message,
                response_language=response_language,
            )
            self._record_reply_language_corruption(raw_reply_corruption_detail)
            recovery_override = _build_language_corruption_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(recovery_override, dict):
                reply_override = str(recovery_override.get("reply") or "").strip()
                if reply_override:
                    return reply_override
            return self.provider_failure_reply(
                "language_corruption",
                raw_reply_corruption_detail,
                response_language,
            )

        reply = _strip_short_cyrillic_noise(reply, message=message)
        reply_corruption_detail = _mixed_script_reply_corruption_detail(
            reply,
            message=message,
            response_language=response_language,
        )
        if reply_corruption_detail:
            self.clear_language_integrity_success(
                message=message,
                response_language=response_language,
            )
            self._record_reply_language_corruption(reply_corruption_detail)
            recovery_override = _build_language_corruption_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(recovery_override, dict):
                reply_override = str(recovery_override.get("reply") or "").strip()
                if reply_override:
                    return reply_override
            return self.provider_failure_reply(
                "language_corruption",
                reply_corruption_detail,
                response_language,
            )
        if _prefers_chinese(response_language):
            if _contains_cjk(reply):
                self.mark_language_integrity_success(
                    message=message,
                    response_language=response_language,
                )
        elif _contains_cjk(message) and _contains_cjk(reply):
            self.mark_language_integrity_success(
                message=message,
                response_language=response_language,
            )

        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario") or "idea_implementation").strip()
        relationship_stage = str(context.get("relationship_stage") or "").strip().lower()
        history_mode = str(context.get("history_mode") or "").strip().lower()
        first_turn_priority = str(context.get("first_turn_priority") or "").strip()
        execution_ready = bool(context.get("execution_ready"))
        supports_intake_reframe = scenario not in {"principle", "review"}
        if (
            not execution_ready
            and
            supports_intake_reframe
            and (
                (
                    relationship_stage == "intake"
                    and _reply_needs_first_turn_reframe(reply)
                ) or (
                    _looks_like_first_turn(context) and _reply_needs_first_turn_reframe(reply)
                ) or (
                    relationship_stage == "intake"
                    and first_turn_priority
                    and _reply_needs_first_turn_reframe(reply)
                )
            )
        ):
            reframed = self._postprocess_first_turn_reply(
                reply,
                response_language=response_language,
                learner_message=message,
                scenario=scenario,
            )
            if history_mode == "fresh_lane":
                reframed = _strip_fresh_lane_cross_lane_carryover(
                    reframed,
                    scenario=scenario,
                    learner_message=message,
                    chinese=_prefers_chinese(response_language),
                )
            return reframed
        chinese = _prefers_chinese(response_language)
        learner_signal = str(
            context.get("learner_signal") or infer_learner_signal(message, current_file)
        ).strip()
        reply = _strip_generic_lane_prompt_artifacts(
            reply,
            scenario=scenario,
            learner_message=message,
            chinese=chinese,
        )
        if history_mode == "fresh_lane":
            reply = _strip_fresh_lane_cross_lane_carryover(
                reply,
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
            )
        file_path = str(context.get("file_path") or "").strip() or None
        pace_signal = str(context.get("pace_signal") or "").strip()
        mode = normalize_answer_policy(answer_mode or profile.answer_policy)

        implementation_guide = (
            context.get("implementation_guide") if isinstance(context.get("implementation_guide"), dict) else {}
        )
        adaptation_guide = (
            context.get("project_adaptation_guide")
            if isinstance(context.get("project_adaptation_guide"), dict)
            else context.get("adaptation_guide")
            if isinstance(context.get("adaptation_guide"), dict)
            else {}
        )
        principle_note = (
            context.get("principle_notes")
            if isinstance(context.get("principle_notes"), dict)
            else context.get("principle_note")
            if isinstance(context.get("principle_note"), dict)
            else {}
        )
        project_ideas = (
            [item for item in context.get("project_ideas", []) if isinstance(item, dict)]
            if isinstance(context.get("project_ideas"), list)
            else []
        )
        exercise_prompt = context.get("exercise_prompt") if isinstance(context.get("exercise_prompt"), dict) else {}
        failing_checks = [
            str(item).strip() for item in context.get("failing_checks", []) if str(item).strip()
        ] if isinstance(context.get("failing_checks"), list) else []
        project_entry_points = [
            str(item).strip() for item in context.get("project_entry_points", []) if str(item).strip()
        ] if isinstance(context.get("project_entry_points"), list) else []
        learning_outcomes = [
            item for item in context.get("learning_outcomes", []) if isinstance(item, dict)
        ] if isinstance(context.get("learning_outcomes"), list) else []
        recalled_coaching_memories = [
            item for item in context.get("recalled_coaching_memories", []) if isinstance(item, dict)
        ] if isinstance(context.get("recalled_coaching_memories"), list) else []

        has_structured_context = any(
            (
                current_file,
                implementation_guide,
                adaptation_guide,
                principle_note,
                project_ideas,
                exercise_prompt,
                failing_checks,
                project_entry_points,
                learning_outcomes,
                recalled_coaching_memories,
                pace_signal,
            )
        )
        if not has_structured_context:
            return reply

        next_step_hint = _prefer_structured_next_step(
            scenario=scenario,
            next_step_hint=_extract_next_step_hint_text(context.get("next_step_hint")),
            implementation_guide=implementation_guide,
            adaptation_guide=adaptation_guide,
            principle_note=principle_note,
            project_ideas=project_ideas,
            exercise_prompt=exercise_prompt,
        )

        additions: list[str] = []

        principle_patch = _compose_principle_followthrough_patch(
            reply=reply,
            principle_note=principle_note,
            chinese=chinese,
        )
        if principle_patch:
            additions.append(principle_patch)

        guided_lane_patch = _compose_guided_lane_continuity_patch(
            reply=reply,
            scenario=scenario,
            chinese=chinese,
        )
        if guided_lane_patch:
            additions.append(guided_lane_patch)

        next_step_patch = _compose_missing_next_step_patch(
            reply=reply,
            scenario=scenario,
            next_step_hint=next_step_hint,
            file_path=file_path,
            project_entry_points=project_entry_points,
            learner_signal=learner_signal,
            mode=mode,
            chinese=chinese,
        )
        if not next_step_patch:
            next_step_patch = None
        if next_step_patch:
            additions.append(next_step_patch)

        review_patch = _compose_review_tightening_patch(
            reply=reply,
            scenario=scenario,
            failing_checks=failing_checks,
            learning_outcomes=learning_outcomes,
            pace_signal=pace_signal,
            learner_signal=learner_signal,
            chinese=chinese,
        )
        if review_patch:
            additions.append(review_patch)

        success_signal_patch = _compose_success_signal_patch(
            reply=reply,
            exercise_prompt=exercise_prompt,
            chinese=chinese,
        )
        if success_signal_patch:
            additions.append(success_signal_patch)

        recalled_memory_patch = _compose_recalled_memory_patch(
            reply=reply,
            recalled_coaching_memories=recalled_coaching_memories,
            chinese=chinese,
        )
        if recalled_memory_patch:
            additions.append(recalled_memory_patch)

        if not additions:
            return reply
        return _append_unique_paragraphs(reply, additions[:3])

    def _postprocess_first_turn_reply(
        self,
        reply: str,
        *,
        response_language: str | None = None,
        learner_message: str,
        scenario: str | None = None,
    ) -> str:
        chinese = _prefers_chinese(response_language)
        condensed = _compact_first_turn_reply(
            reply,
            chinese=chinese,
            scenario=scenario,
            learner_message=learner_message,
        )
        if condensed:
            return condensed

        learner_excerpt = learner_message.strip()
        guided_lane = _resolve_first_turn_guided_lane(
            scenario=scenario,
            learner_message=learner_message,
            reply=reply,
        )
        guided_note = _first_turn_lane_continuity_note(guided_lane, chinese=chinese)
        guided_close = _first_turn_lane_next_step(guided_lane, chinese=chinese)
        if guided_note and guided_close:
            if chinese:
                lead = "\u5148\u522b\u76f4\u63a5\u7ed9\u7b54\u6848\u3002\u5148\u5b9a\u4f4f\u8fd9\u4e00\u8f6e\u7684\u8d77\u6b65\u52a8\u4f5c\uff0c\u518d\u7ee7\u7eed\u3002"
                if learner_excerpt:
                    lead += f" \u4f60\u521a\u521a\u5e26\u6765\u7684\u91cd\u70b9\u662f\uff1a{_trim_sentence(learner_excerpt, 72)}\u3002"
                return f"{lead}\n\n{guided_note}\n\n{guided_close}"

            lead = (
                "I do not want to jump straight into a solution yet. "
                "First I want to anchor this round in one trustworthy starting move and keep the thread continuous."
            )
            if learner_excerpt:
                lead += f" What you just brought in is: {_trim_sentence(learner_excerpt, 72)}."
            return f"{lead}\n\n{guided_note}\n\n{guided_close}"
        if not _should_offer_generic_first_turn_lane_prompt(
            scenario=scenario,
            learner_message=learner_message,
            reply=reply,
        ):
            lead = "I do not want to jump straight into a solution yet. First I want to stay on the concrete task you already named."
            if chinese:
                lead = "\u5148\u522b\u76f4\u63a5\u7ed9\u7b54\u6848\u3002\u5148\u6cbf\u7740\u4f60\u521a\u624d\u5df2\u7ecf\u8bf4\u6e05\u695a\u7684\u5177\u4f53\u4efb\u52a1\u7ee7\u7eed\u5f80\u524d\u3002"
            if learner_excerpt:
                lead += (
                    f" \u4f60\u521a\u521a\u5e26\u6765\u7684\u91cd\u70b9\u662f\uff1a{_trim_sentence(learner_excerpt, 72)}\u3002"
                    if chinese
                    else f" What you just brought in is: {_trim_sentence(learner_excerpt, 72)}."
                )
            return f"{lead}\n\n{_first_turn_concrete_followthrough(chinese=chinese)}"
        if chinese:
            lead = "\u5148\u522b\u76f4\u63a5\u7ed9\u7b54\u6848\u3002\u5148\u5bf9\u9f50\u8fd9\u4e00\u8f6e\uff0c\u518d\u9009\u5408\u9002\u7684\u5f15\u5bfc\u65b9\u5f0f\u3002"
            if learner_excerpt:
                lead += f" \u4f60\u521a\u521a\u5e26\u6765\u7684\u91cd\u70b9\u662f\uff1a{_trim_sentence(learner_excerpt, 72)}\u3002"
            return (
                f"{lead}\n\n"
                "\u7b2c\u4e00\u8f6e\u901a\u5e38\u4f1a\u5148\u843d\u5230\u4e09\u6761\u8def\u5f84\u4e4b\u4e00\uff1a\u5b9e\u73b0\u4e00\u4e2a idea\u3001\u6539\u9020\u73b0\u6709\u9879\u76ee\uff0c\u6216\u5148\u5b9a\u8bad\u7ec3\u4e3b\u7ebf\u3002\n\n\u544a\u8bc9\u6211\u73b0\u5728\u66f4\u63a5\u8fd1\u54ea\u4e00\u6761\u3002"
            )

        lead = "I do not want to jump straight into a solution yet. First I want to align on this round and choose the right way to guide you."
        if learner_excerpt:
            lead += f" What you just brought in is: {_trim_sentence(learner_excerpt, 72)}."
        return (
            f"{lead}\n\n"
            "I usually sort the first turn into one of three lanes: turning an idea into code, guiding changes inside an existing project, or shaping the longer training thread and rhythm first. I will also remember the goal, project context, and coaching preference we make clear here so the next turn can continue the same thread.\n\n"
            "Tell me which lane is closest right now: implementing an idea, adapting an existing project, or shaping the training thread first."
        )

    def _scaffold_reply(
        self,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        chinese = _prefers_chinese(response_language)
        mode = normalize_answer_policy(answer_mode or profile.answer_policy)
        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario", "idea_implementation"))
        learner_signal = str(context.get("learner_signal", infer_learner_signal(message, current_file)))
        file_path = context.get("file_path")
        diagnostics_count = int(context.get("diagnostics_count", 0) or 0)
        current_focus = str(context.get("current_focus") or "").strip()
        recent_wins = [str(item) for item in context.get("recent_wins", []) if str(item).strip()]
        weak_spots = [str(item) for item in context.get("weak_spots", []) if str(item).strip()]
        due_reviews = context.get("due_reviews", [])
        review_rhythm = str(context.get("review_rhythm") or "").strip()
        teaching_observations = [
            str(item) for item in context.get("teaching_observations", []) if str(item).strip()
        ]
        coach_defaults = context.get("coach_defaults") if isinstance(context.get("coach_defaults"), dict) else {}
        summary = str(context.get("thread_summary") or context.get("summary") or "").strip()
        next_step_hint = _extract_next_step_hint_text(
            context.get("thread_next_step") or context.get("resume_hint") or context.get("next_step_hint")
        )
        teaching_decision = context.get("teaching_decision") if isinstance(context.get("teaching_decision"), dict) else {}
        tone_decision = context.get("tone_decision") if isinstance(context.get("tone_decision"), dict) else {}
        implementation_guide = (
            context.get("implementation_guide") if isinstance(context.get("implementation_guide"), dict) else {}
        )
        adaptation_guide = (
            context.get("project_adaptation_guide")
            if isinstance(context.get("project_adaptation_guide"), dict)
            else context.get("adaptation_guide")
            if isinstance(context.get("adaptation_guide"), dict)
            else {}
        )
        principle_note = (
            context.get("principle_notes")
            if isinstance(context.get("principle_notes"), dict)
            else context.get("principle_note")
            if isinstance(context.get("principle_note"), dict)
            else {}
        )
        project_ideas = [
            item for item in context.get("project_ideas", []) if isinstance(item, dict)
        ] if isinstance(context.get("project_ideas"), list) else []
        exercise_prompt = (
            context.get("exercise_prompt") if isinstance(context.get("exercise_prompt"), dict) else {}
        )
        verbosity_bias = str(tone_decision.get("verbosity_bias") or "medium").strip()
        tone_name = str(tone_decision.get("tone") or "").strip()

        goal_line = profile.long_term_goal or (profile.long_term_goals[0] if profile.long_term_goals else "")
        anchor = _scaffold_anchor(
            scenario=scenario,
            goal=goal_line,
            file_path=str(file_path) if file_path else None,
            current_focus=current_focus,
            chinese=chinese,
        )
        diagnosis = _scaffold_diagnosis(
            scenario=scenario,
            learner_signal=learner_signal,
            diagnostics_count=diagnostics_count,
            weak_spots=weak_spots,
            teaching_observations=teaching_observations,
            summary=summary,
            teaching_decision_reason=str(teaching_decision.get("reason") or "").strip(),
            chinese=chinese,
        )
        next_step = _scaffold_next_step(
            scenario=scenario,
            mode=mode,
            learner_signal=learner_signal,
            file_path=str(file_path) if file_path else None,
            weak_spots=weak_spots,
            next_step_hint=_prefer_structured_next_step(
                scenario=scenario,
                next_step_hint=next_step_hint,
                implementation_guide=implementation_guide,
                adaptation_guide=adaptation_guide,
                principle_note=principle_note,
                project_ideas=project_ideas,
                exercise_prompt=exercise_prompt,
            ),
            chinese=chinese,
        )
        teaching_note = _scaffold_teaching_note(
            scenario=scenario,
            mode=mode,
            recent_wins=recent_wins,
            weak_spots=weak_spots,
            due_reviews=due_reviews,
            review_rhythm=review_rhythm,
            coach_defaults=coach_defaults,
            tone_name=tone_name,
            verbosity_bias=verbosity_bias,
            chinese=chinese,
        )
        close = _scaffold_close(
            learner_signal=learner_signal,
            mode=mode,
            verbosity_bias=verbosity_bias,
            chinese=chinese,
        )

        paragraphs = _compose_scaffold_paragraphs(
            scenario=scenario,
            mode=mode,
            learner_signal=learner_signal,
            anchor=anchor,
            diagnosis=diagnosis,
            next_step=next_step,
            teaching_note=teaching_note,
            close=close,
            chinese=chinese,
        )
        resolved = [part for part in paragraphs if part.strip()]
        if verbosity_bias == "short":
            resolved = resolved[:3]
        return "\n\n".join(resolved)

    def _onboarding_reply(self, response_language: str | None = None) -> str:
        if _prefers_chinese(response_language):
            return (
                "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棗鏆欏┑鈥炽偢閺屽秷顧侀柛鎾存皑閹广垽宕煎┑鎰婵犵數濮甸懝楣冨础閹惰姤鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú鐔奉潖閾忓湱纾兼俊顖氭惈琚濋梻浣告啞閹歌鐣濋幖浣哥畺闁汇垻顭堢猾宥夋煕椤愩倕鏆遍柟閿嬫そ濮婅櫣娑甸崨顓濇睏闂佺顑嗙粙鎺撶┍婵犲啰闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛濠傜秺瀹曟垿濡疯閸嬫挸鈻撻崹顔界仌濡炪倖娉﹂崶褏鍙€婵犮垼鍩栭崝鏇綖閸涘瓨鐓熸俊顖氬悑閺嗏晠鏌℃径濠冨暈濞ｅ洤锕幃娆擃敂閸曘劌浜鹃柡宥庡亝閺嗘粌鈹戦悩鎻掝仾濠殿垰銈搁弻锛勪沪鐠囨彃濮庨梺鍛婂灩婵數鎹㈠☉銏犲耿婵☆垵顕ч棄宥夋⒑閹惰姤鏁遍柛銊ユ贡濡叉劙骞樼€涙ê顎撻梺鍏肩ゴ閸撴繈宕圭憴鍕洸闁归棿绶￠弫鍌炴煕椤愩倕鏋旈柛姗€浜堕弻鐔兼嚌閻楀牆娑х紓浣圭叀缁犳牕顕ｉ幎绛嬫晢闁稿本顨呮禍鐐箾閸繄浠㈤柡瀣⊕閵囧嫰顢橀悩鎻掑箣濡ょ姷鍋涢崯瀛樻叏閳ь剟鏌曢崼婵囧櫣缂佹劖绋掔换婵嬫偨闂堟刀銏ゆ倵濮樼厧鏋﹂柛濠冩尦濮婂宕掑顑藉亾妞嬪海鐭嗗〒姘ｅ亾妤犵偛顦甸弫鎾绘偐閼碱剦鍞堕梻浣虹《閸撴繄绮欓幋婵愬晠婵犻潧娲㈡禍婊堟煛閸愩劌鈧骞楅崒鐐寸厱闁绘棃鏀遍崳鐣岀磼鏉堛劍宕岀€规洘甯掗～婵嬵敄閽樺澹曢梺褰掓？缁€浣哄閻熼偊娓婚悗锝庝簻椤掋垹鈹戦姘ュ仮闁哄矉绱曟禒锔炬嫚閹绘帒顫撶紓浣哄亾閸庢娊鈥﹂悜钘夎摕闁绘梻鍘х粈鍫㈡喐韫囨洘鏆滄繛鎴欏灪閻撶喖鏌熼幆褏鎽犵紒鈧崼銉︾厓鐟滄粓宕滃▎鎾冲偍婵犲﹤鐗嗙壕濠氭煙閸撗呭笡闁绘挸鍟伴幉绋款煥閸繄顦梺缁樻椤ユ捇寮抽敃鍌涚厵閺夊牓绠栧顕€鏌涙繝鍕幋闁哄矉缍侀獮瀣倶濞茶绨肩紒鍌氱Т铻栭柛娑卞枓閹锋椽姊洪崨濠勭畵閻庢凹鍘奸蹇撯攽鐎ｎ偆鍘遍梺缁樏鍫曀夐悙鐢电＜闁稿本姘ㄥ瓭濡炪値鍘归崝鎴濈暦婵傚憡鍋勯柛婵嗗缁犮儵姊婚崒娆戭槮闁圭⒈鍋婅棟妞ゆ牜鍋為崐鑸电節闂堟侗鍎嶉柍褜鍓欓崐鍧楃嵁鎼淬劍鍤嶉柕澹啫绠ュ┑锛勫亼閸婃牠寮婚妸鈺傚€舵繝闈涙川椤╂煡鏌涢敂璇插箻缁炬儳銈稿鍫曞醇濞戞ê顬堝┑鐐存儗閸ｏ綁寮婚悢纰辨晩閻熸瑥瀚悵姘舵⒑閸︻厼甯剁紓宥咃躬閵嗕線寮撮姀鐙€娼婂銈庡亽閸犳碍寰勯崟顖涒拻闁稿本鑹鹃埀顒勵棑缁牊绗熼埀顒勭嵁閺嶎収鏁冮柨鏃囨閸撹绻濋姀锝嗙【闁活剝鍋愮划鍫熺節閸屾ǚ鍋撻幒鎴僵闁挎繂鎳嶆竟鏇㈡⒒娴ｈ櫣甯涘〒姘殜瀹曟娊鏁愭径灞界ウ闂佸湱鍎ら崵锕傚籍閸繄鍔﹀銈嗗笒閸婄粯绋夊澶嬬叆婵犻潧妫欓ˉ鐘电磼閻樿崵鐣洪柡灞剧洴閸╁嫰宕橀悙顒傛毉缂傚倷鑳舵刊瀵哥礊娓氣偓瀵鈽夐姀鐘殿唺闂佽宕樺▍鏇犳嫚閻愭祴鏀芥い鏃傘€嬮崝鐔虹磼椤曞懎鐏︽鐐茬箻瀹曘劑寮堕幋婵堢崺濠电姷鏁告慨鎾疮椤愶箑绀堥柣銏犳啞閳锋帒霉閿濆牜娼愰柕鍥╁枛閺屾盯骞樼€靛憡鍣版繝纰樷偓鍐差暢缂侇喗鐟ч幑鍕Ω閿旂瓔鍟庢繝鐢靛仦濞兼瑩宕ョ€ｎ亶鐒芥繛鍡樻尭缁€鍐煃瑜滈崜娆撯€旈崘顔嘉ч柛鈩兠棄宥嗙節閵忥綆娼愭繛鑼枎閻ｇ兘骞嬮敃鈧粻濠氭倵闂堟稒鎲搁柟铏箞濮婃椽鏌呴悙鑼跺濠⒀屽枟閵囧嫰寮撮鍡櫳戠紓浣稿€圭敮鐐哄焵椤掑﹦鍒伴柣蹇斿哺瀵煡鏁愭径瀣ф嫼缂傚倷鐒﹂敋濠殿喖顦甸弻鈩冩媴鐟欏嫬鈧劗鈧鍠涘▍鏇犫偓浣冨亹閳ь剚绋掗…鍥储娴犲鈷戠紓浣股戦悡銉╂煙閼恒儳鐭掗柟顖氭湰缁绘繈宕熼鐙呯床濠电姰鍨煎▔娑㈠嫉椤掑嫬姹叉い鎺嶇贰濞堜粙鏌ｉ幇顖氱毢濠⒀嶇畱閳规垿鍩勯崘鈺佲偓鎰版煕閳规儳澧茬紒妤冨枛瀹曞爼濡歌琚╅梻鍌氬€搁崐鐑芥嚄閸撲礁鍨濇い鏍仦閺呮繈鏌嶉崫鍕櫣缁炬儳顭烽弻娑樷槈濞嗘劗绋囧┑鈽嗗亝閿曘垽寮诲鍫闂佸憡鎸鹃崰搴綖韫囨洜纾兼俊顖濐嚙椤庢捇姊洪幆褏绠抽柟铏尵缁參鏁撻悩鏂ユ嫼闂佸憡绋戦敃銉╁煕閹扮増鐓熼柣鏃€娼欓崝锕傛煃閵夘垳鐣电€规洖鐖奸、鏂款吋閸犻偊鍓熷缁樻媴閼恒儯鈧啰绱掔拋鍦瘈鐎规洘濞婇弫鎰板川椤栨稒顔曞┑鐘绘涧閸婂鈥﹂崼銉ョ闁规儼濮ら悡鐔兼煛閸屾稑顕滈柟顖氱墛椤ㄣ儵鎮欓懠顒€鈪靛┑顔硷功缁垶骞忛崨瀛樻優闁荤喐澹嗛濂告⒒娴ｅ憡鎯堥悶姘煎亰瀹曟繈骞嬮敂鎯хウ婵犮垼鍩栭崝鏍疾椤掑嫭鐓曢柡鍥ュ妺缁ㄤ粙鏌涢幘鍗炲婵﹥妞介獮鎰償閳垛晜瀚介梻浣哄劦閸撴繈寮婚妸鈺佺厺闁规儳顕々鐑芥倵閿濆骸浜為柛妯圭矙濮婇缚銇愰幒鎴滃枈闂佸憡鎸婚悷褔鎯€椤忓浂妲奸梺闈涙搐鐎氱増淇婇悜鑺ユ櫜闁告侗鍨槐鏇㈡⒒娓氣偓閳ь剛鍋涢懟顖涙櫠閸欏浜滄い鎰╁焺濡叉悂鎮￠妶鍡欑瘈濠电姴鍊绘晶鏇犵磼閹邦収娈滈柡灞糕偓鎰佸悑閹肩补鈧磭顔夐梻渚€鈧偛鑻崢鍝ョ磼閳ь剚鎷呴悾灞艰埅闂備浇宕甸崑鐐电矙閸儱绀堟繝闈涱儜缂嶆牜鈧箍鍎遍幊澶愬绩娴犲鐓冮柦妯侯槹椤ユ粓鏌ｈ箛銉хМ闁哄瞼鍠栭幖褰掝敃閿濆懐锛撻梺鑺ヮ焽閸犳劙骞堥妸銉建闁糕剝顨呯粻鑽ょ磽娴ｅ弶顎嗛柛瀣崌濮婄粯鎷呴崷顓熻弴闂佹悶鍔忓Λ鍕€﹂崶顏嶆Ъ缂備礁鍊圭敮锟犲极閸愵喖纾兼繛鎴炶壘楠炲牓姊绘笟鈧褔鈥﹂崼銉ョ？闁规儼妫勯弰銉╂煥濠靛棙顥撳ù婊勭矒閺屾洝绠涙繝鍌氣拤濡炪們鍎遍悧濠囧Φ閸曨垰顫呴柍鈺佸枤濡啴鎮楃憴鍕闁靛牊鎮傞妴渚€寮撮姀鈩冩珳闂佺硶鍓濋…鍥亹閸℃稒鈷掗柛灞捐壘閳ь剟顥撶划鍫熺瑹閳ь剟鐛径鎰労闁告劦浜為幊婵嗏攽鎺抽崐鏇㈠箠鎼淬劌纾奸柕濞炬櫆閻撴洟鏌熼悙顒夋當闁硅櫕鍔欓悰顕€骞樼紒妯锋嫼缂傚倷鐒﹂敋濠殿喖顦甸弻娑欐償濞戞ǚ鍋撳┑鍡欐殾闁圭増婢橀崹鍌涖亜閹伴潧浜濇い鏃€妫冨铏圭磼濡搫顫戦柣蹇撶箲閻燂妇绮嬮幒妤€顫呴柕鍫濇閸橀亶姊洪崫鍕殜闁稿鎸鹃埀顒€鍘滈崑鎾绘煙闂傚顦﹂柦鍐枛閺岋綁寮崒姘粯缂備讲鍋撻柛鎰典簴閸嬫捇鎮烽弶娆炬闂佸摜濮甸〃鍫ユ偡瑜斿缁樻媴閸涘﹤鏆堝銈冨妼閿曘儳绮嬪澶婇唶闁哄洨鍋犻幗鏇炩攽閻愭潙鐏熼柛鈺佸瀵偊宕橀鐣屽幗濠碘槅鍨甸褏寰婄拠娴嬫斀妞ゆ棁濮ょ粈瀣叏婵犲懏顏犵紒杈ㄥ笒铻ｉ悹鍥ㄧ叀閻庢椽姊绘担钘夊惞闁哥喎娼″鏌ユ偐瀹割喖娈ㄩ柣鐘叉处缁佹潙危閸儲鐓忛煫鍥ㄦ礀鍟稿銈嗘⒐鐢帡鍩為幋鐐茬疇闂佺锕ラ崝娆忕暦閹达箑绠荤紓浣诡焽閸樻儳鈹戦悙璺鸿敿妞ゆ泦鍥ㄥ€堕柨鐔哄У閻撴瑥銆掑顒備虎濠殿喖鍊婚埀顒侇問閸犳骞愰搹顐ｅ弿闁逞屽墴閺屽秹鏌ㄩ姘闂備礁缍婇弨鍗烆渻娴犲钃熼柨婵嗩槹閸婄兘鎮楅悽鐢点€婇柡瀣濮婃椽鏌呴悙鑼跺濠⒀屽櫍閺屾稑螣閼姐倕顫х紓浣规⒒閸犳牕顕ｉ幘顔藉€烽柍鍝勫€归弶鎼佹⒒娴ｈ櫣甯涢柨姘舵煟韫囨柨鍝虹€殿喗濞婇崺鈩冩媴閸欏鏉告俊鐐€栧濠氬磻閹捐姹查柍鍝勬噺閻撴洟鏌ｅΟ娆惧殝鐎规悶鍎查妵鍕箻閸愬弶鍊悗鍨緲鐎氼噣鍩€椤掑﹦绉靛ù婊勭懅閼洪亶宕归銈囩槇闂佹眹鍨藉褎绂掗敃鍌涚厱闁靛鍎抽崺锝団偓瑙勬礃濡炶棄鐣峰鈧、娆撴嚃閳哄骞㈤梻鍌欐祰椤鐣峰鈧、姘愁槾缂侇喖鐗撳畷鎺戭潩閼测晛鏁搁梺鑽ゅЬ濞咃絿浜搁妸銉綎婵°倐鍋撴い顓℃硶閹叉挳宕熼鍌ゆЧ婵犳鍠栭敃锔惧垝椤栨粎绠旈柣鏃傚帶閻掑灚銇勯幒鎴濐仼闁绘帒鐏氶妵鍕箳閹存績鍋撻崨濠勵浄婵犲﹤鐗婇悡鐘崇箾閼奸鍤欓柣蹇ョ節閺岋繝宕ㄩ鐑嗘殺闂侀€炲苯澧伴柡浣告憸濞戠敻宕奸弴鐐碉紱闂佽宕橀崺鏍窗閸℃稒鐓曢柡鍥ュ妼婢х増銇勯敂璇插箺缂佺粯绻堥崺娑㈠焵椤掑嫬绀嬮柛顭戝亞閺夎淇婇妶鍥ラ柛瀣☉铻炴繝闈涙－閸ゆ洘銇勯弴妤€浜鹃悗瑙勬礈閸樠団€﹂崸妤婃晜濞达綀顫夐悵姘舵⒑閸濆嫯顫﹂柛鏂跨焸閸╃偤骞嬮敃鈧獮銏′繆閻愰鍤欏ù婊堢畺閺屾稑鈽夊鍫濆濡炪倐鏅滆ぐ鍐亙闂佹寧绻傞幊搴ㄥ汲閻愮儤鐓熼柟鎯х摠缁€鍐磼缂佹娲存鐐差儏閳规垿宕卞顒傚幋闂傚倷绀侀幖顐︻敄閸愵喖纾规繝闈涙－濞兼牕鈹戦悩瀹犲缂佲偓鐎ｎ偁浜滈柟鎵虫櫅閻掑搫霉鐏忔牕浜剧紓鍌氬€搁崐宄懊归崶銊ｄ粓闁告縿鍎查弳婊堟煟閹邦剚鎯堥柣鎺戠仛閵囧嫰骞掗幋顖氬缂備礁顦靛褔婀佸┑鐘诧工鐎氼喚绮婚悙纰樺亾鐟欏嫭绀冮柛銊﹀娣囧﹪鎮滈挊澶屽幐闂佺鏈划宀勭嵁閸儲鈷掑ù锝堟鐢盯鏌涢弮鈧敃銏犵暦濞差亜鍐€妞ゆ劧绲介崢褰掓⒑缂佹ê濮﹂柛蹇旂懄缁傚秴顭ㄩ崟鈺€绨婚棅顐㈡处閹告悂顢旈埡鍛厸闁糕槅鍘鹃崚浼存煃鐟欏嫬鐏撮柛銊﹀劤閻ｇ兘宕惰閸樹粙鏌ｆ惔銈庢綈婵炲弶鐗曢悾鐑筋敆閸愵亙绨烽梻鍌欑閹诧繝宕濋敂鐣岊洸婵犻潧顑呴梻顖涖亜閺嶎偄浠﹂柍閿嬪浮閺屾稓浠﹂崜褎鍣梺绋跨箰閺堫剟濡甸崟顖ｆ晣闁绘劙娼ч埅鐢告⒑鏉炴壆顦﹂柛鐔风摠娣囧﹪鎳滈棃娑氱獮闂佺硶鈧磭绠板ù婊堢畺閺屻劑寮撮悙娴嬪亾瑜版帒纾绘い蹇撴噷娴滄粓鏌″鍐ㄥ缂佹儼椴告穱濠囶敃閻樻彃顬堥梺瀹狀潐閸ㄥ潡寮澶婄妞ゆ劏鍓濆鈧梻鍌欒兌椤牓鏁冮妷鈺傚亱闁哄洨濮村鏌ユ煟鎼达紕鐣柛搴ㄤ憾钘濇い鏍ㄧ矊椤ユ艾鈹戦悩宕囶暡闁绘挻鐟╅弻鐔碱敍閸℃鍣洪柟鎻掋偢濮婃椽宕ㄦ繝鍕櫑缂備胶绮崝娆撳春閻愬搫绠ｉ柨鏃囨娴滃綊姊洪崨濠勬噧妞わ富鍨伴埢宥夊Χ閸滀焦瀵岄梺闈涚墕閹虫劗绮婚崘娴嬫斀妞ゆ洍鍋撴い銉︽尭鍗遍柟鐗堟緲缁犺櫕淇婇妶鍜冩敾闁哄應鏅犲鐑樺濞嗘垵鍩岄梺鍝勭墱閸撶喎鐣烽幎绛嬫晪闁逞屽墮椤繐煤椤忓嫭宓嶅銈嗘尵閸犲骸鈻撳畝鍕厽閹兼番鍨洪惃鎴濐熆瑜庨〃鍡欑矚鏉堛劎绡€闁稿被鍊栧銊╂倵閸忓浜炬繝鐢靛Т閸犳岸鍩€椤掆偓濞差厼顫忕紒妯诲闁告稑锕ラ崰鎰版⒑缁嬫鍎愰柣鈺婂灦楠炲啴濡烽埡鍌氫簵闁瑰吋鎯岄崰妤冪礊鎼达絿纾介柛灞剧懅閸斿秹鎷戦崡鐐╂斀妞ゆ牗绋掔亸锕傛煛鐏炵喎妫涢悿鈧梺鍝勬川閸犲骸鈻撳畝鈧槐鎾存媴楠炲じ绮堕梺閫炲苯澧柛鎾磋壘閵嗘帗绻濆顓犲帾闂佸壊鍋呯换鍌炲汲濞嗗繆鏀介柍銉у仺閸嬨垽鏌″畝鈧崰鏍箹瑜版帩鏁冩い鎺戝暊閸嬫挾鎹勯妸銏犱壕婵炲牆鐏濆▍姗€鏌涚€ｎ亷宸ラ柣锝呭槻椤粓鍩€椤掑嫨鈧礁鈻庨幘鍐茬哎婵犮垼娉涢悧鍡樻叏閸岀偞鐓涢悘鐐额嚙婵倻鈧鍣崳锝呯暦婵傚憡鍋勯柛娑橆煬閸炲爼姊婚崒娆愮グ闁靛棌鍋撻梺绋款儐閹瑰洭寮昏缁犳盯鏁愰崨顒傛晼缂傚倷璁插褔宕戦幘缁樷拻濞达絽婀卞﹢浠嬫煕閵娿劍顥夋い顓炴穿椤︽煡鏌ｉ埥鍡楀箺缂佺粯绻堥幃浠嬫濞戞鎹曢梻浣规た娴滄瑩宕￠崘鑼殾闁圭増婢橀崡鎶芥煏韫囧﹥娅嗛柡鍛櫊濡懘顢曢姀鈥愁槱闂佺懓鎲￠幐鍐差嚕閵婏妇顩烽悗锝庡亞閸橀亶姊洪悙钘夊姎缁剧虎鍘剧划濠氬蓟閵夛妇鍘搁梺绋挎湰椤ㄥ懏绂嶆ィ鍐┾拻闁稿本鑹鹃埀顒傚厴閹虫宕滄担绋跨亰濡炪倖鐗楃换鍐箠瀹€鍕厽闁绘柨鎽滈惌瀣節閵忊槄鑰跨€规洦鍨跺鍫曞箣椤撶偞顓块梻浣筋潐閸庣厧螞閸曨垰纭€闁规儼濮ら悡鐔兼煛閸愩劌浜為柣鎺戝⒔閳ь剚顔栭崰鏍倶濠靛鐓橀柟杈惧瘜閺佸﹦绱掑☉姗嗗剱闁伙絽鐖煎铏圭磼濮楀棙鐣剁紓浣虹帛閿曘垽鐛崘鈹垮亝闁告劏鏅濋崝鍫曟倵楠炲灝鍔氭俊顐ｇ洴瀹曘垽骞樼紒妯煎幗闂佺粯鏌ㄩ幗婊堝箠閸愵喗鍊垫慨妯煎帶婢ф挳鏌熼鏂よ€挎鐐达耿椤㈡瑩鎮剧仦钘夌濠碉紕鍋戦崐鏍ь潖婵犳艾鐤炬い鎰剁畱缁犵娀鏌涢妷銏℃澒闁稿鎸鹃幉鎾礋椤掑倵鏁嶇紓鍌欑瀵爼宕曢幎绛嬫晪闁靛鏅涚粈瀣亜閹邦剦鍎戦柛鐘冲姉閳ь剛鏁搁崢褔鍩㈡惔銊ョ闁绘瑥鎳愭惔濠囨⒒閸屾艾鈧悂宕愰幖浣哥９闁绘垼濮ら崐鍧楁煥閺囩偛鈧綊宕曢幋鐘冲枑闁绘鐗嗙粭鎺楁煛閸曗晛鍔﹂柡灞剧洴瀵挳濡搁妷褌鍝楅梻浣规偠閸斿矂宕愰崸妤€钃熼柣鏃傚帶缁犳岸鏌ｅΔ鈧悧婊兾涢崟顓犵＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭峰鎾閻樿鏁规繝鐢靛█濞佳兠洪妶澶樻晛婵炴垯鍨洪埛鎴︽煙閼测晛浠滈柍褜鍓氶悧鏇犲弲闂佺粯姊婚崢褔鎷戦悢鍏肩厽闁哄倸鐏濋幃鎴︽煃闁垮娴柟顔筋殜濡啫鈽夊鍡橆棏婵犵鈧櫕鈻曢柛鐘虫皑濡叉劙骞掑Δ浣糕偓閿嬨亜閹哄棗浜鹃梺鍛婃煟閸婃繈寮婚弴銏犻唶闁绘梻顭堥埀顒佸姉閳ь剚顔栭崰鏍€﹂悜钘夋瀬闁归偊鍘肩欢鐐测攽閻樻彃顏柡澶婃啞娣囧﹪鎮欓鍕ㄥ亾閺嶎偅鏆滈柟鐑橆檪閸ヮ剦鏁嶆慨姗堢稻閻忎線姊洪崜鎻掍簼婵炲弶锕㈤崺娑㈠箣閿旂晫鍘卞┑鐐村灦鑿ゅ┑顔兼喘閺屻倕霉鐎ｎ偅鐝旈梺鎼炲妽缁诲啰鎹㈠☉銏犲耿婵°倓鑳堕々鏉库攽閻愭彃鎮戦柣妤侇殘閹广垹鈽夊鍡楁櫊濡炪倖妫佸畷鐢稿礄閻熼偊娓婚柕鍫濆暙閸旀岸鏌ｅΔ鈧敃锕傚箲閵忕姭妲堥柕蹇曞Х椤撴椽姊洪幐搴ｇ畵閻庢凹鍓熼獮鍡涘醇閵夛腹鎷洪梺鍛婄☉閿曘儵鍩涢幇鐗堢厵妞ゆ梻鍘ч埀顒佹倐閿濈偠绠涘☉娆愬劒闂侀潻瀵岄崢楣冩偂閹剧粯鈷戠紒澶婃鐎氬嘲鈻撻弮鍌楀亾濞堝灝鏋ゅ褎顨堥幑銏犫槈濮橈絽浜炬繛鎴炵懐閻掍粙鏌ｉ鐑囪含闁哄矉缍佸鍊燁槹闁稿鍨归埞鎴﹀灳瀹曞洦鎲肩紓浣诡殘閸犳牠宕洪埀顒併亜閹哄棗浜惧銈嗘穿缂嶄線銆佸璺虹劦妞ゆ巻鍋撻柣锝夋敱缁轰粙宕滈崣澶嬫珖闂備焦瀵х换鍌毼涘▎鎾村仧闁哄稁鍘介埛鎺楁煕鐏炲墽鎳呴柛鏂跨Ч閹绮☉妯诲櫤鐎规洘鐓￠弻娑氫沪缂併垹娈у┑鐐叉▕娴滄粍鍎梻浣稿暱閹碱偊鏁冮妷鈺佺柧闁冲搫鎳忛埛鎴︽煕濠靛棗顏柛灞诲姂閺屾盯濡搁敂濮愪虎闂佺硶鏅滈惄顖炵嵁閹烘绠ｉ柡鍐ｅ亾闁哄倵鍋撻梻鍌欒兌缁垵鎽梺缁樻惈缁绘繈銆侀幘婢勬棃鍩€椤掑嫭绠掓繝鐢靛Т鑹岄柛瀣尵缁辨帡顢欓悾灞惧櫚閻庢鍠涢褔鍩ユ径濞㈢喎顭ㄩ崨顓熺亪闂佽鍠掗崜婵嬪箚閺冨牆鐏抽柤纰卞墮缁楋繝姊婚崒姘偓宄邦渻閹烘梹顫曟い鏃€鍎崇欢銈夋煕瑜庨〃鍛村几娓氣偓閹綊宕堕鍕闂佸搫妫寸粻鎾诲蓟濞戞鏃堝礃閵娿倖鐫忛梻浣告惈椤戝懘鏌婇敐澶婄畺婵せ鍋撻柟顔界懇瀵爼骞嬮悩鍗炴瀳婵犵數濮伴崹濂革綖婢跺⊕娲冀椤撶偟鍘撮梺纭呮彧闂勫嫰宕愰悜鑺ョ厾缁炬澘宕晶顔姐亜閿濆棙銇濇慨濠呮閹风娀鎳犻鍌ゅ敼缂傚倷娴囬褔鎮ч崱娑辨晪闁挎繂娲ㄩ惌娆撳箹鐎涙ɑ灏伴柣搴☆煼濮婃椽鎮烽柇锕€娈舵繝娈垮枤閸忔﹢寮鍜佺叆闁告劗鍋撶€靛矂姊洪棃娑氬婵☆偅鐟╅崺娑㈠箳濡や胶鍘搁梺鍛婄矆缁€浣圭閻楀牜娈介柣鎰嚋闊剛鈧娲橀敃銏ゃ€佸▎鎾村仼閻忕偠妫勭粻娲⒒閸屾瑧鍔嶉悗绗涘懏宕查柛灞绢嚔濞差亜围濠㈣泛锕ら崑宥夋煟鎼达絾鏆╃痪顓炵埣瀹曟垿骞橀懜闈涙瀭闂佸憡娲﹂崜娑⑺囬妷鈺傗拺闂傚牊绋撴晶銏°亜椤撶偟澧︽い銏″哺閺佹劖寰勬繝鍕靛晪婵＄偑鍊栧Λ浣肝涢崟顖氱劦妞ゆ帒瀚峰Λ鎴︽煃瑜滈崜娆戠不瀹ュ纾块梺顒€绉撮悿顔姐亜閹板墎绋婚柛娆忕箻閺屾稑鐣濋埀顒勫磻閻愮儤鍋傛繛鎴欏灪閸婂爼鏌ｉ幇鐗堟锭濞存粌澧界槐鎺楀焵椤掍礁绶炵€光偓閳ь剛澹曟總鍛婄厽婵☆垵娅ｉ敍宥嗙箾閹绘帩鍤熼柍褜鍓氶鏍窗濡ゅ懎绠伴柟鎯版缁犳牗绻涢崱妯诲碍缂佺姵鐩弻鏇熺箾閸喚浠兼繛瀛樼矒缁犳牠寮婚悢闈╃矗濞达綀妫勯崢锟犳⒑閸濄儱浠ч柡浣割煼瀵鏁愭径瀣簻闂佸憡绺块崕鏌ュ闯瑜旈弻锝嗘償閵忕姴姣堥梺鍛娒晶浠嬪礆閹烘閱囬柕澶堝劤椤︺劌顪冮妶鍛婵☆偅鐩弫宥咁煥閸涱垳锛濋梺绋挎湰閻熝囧礉瀹ュ棎浜滄い鎾跺仦閹兼劙鎮￠妶澶嬪€垫繛鎴炵懕娓氭稒绻涢崼婊呯煓闁哄矉缍侀獮鍥敍濞戞ɑ閿梻浣稿悑婵棄鈻旈弴銏犵劦妞ゆ帊绶￠崯蹇涙煕閻樺磭澧甸柟顔哄劜缁轰粙宕妷銉с偊闂佽鍑界紞鍡涘窗濡ゅ懎纾婚柟鎵閻撴瑧绱撴担濮戭亪鏌嬮崶顒佺厽婵☆垵鍋愮敮娑㈡煃闁垮娴柡灞剧〒娴狅箓宕滆閸ｎ垶姊虹粙璺ㄧ闁哄牜鍓熸俊鐢稿礋椤栵絾鏅ｉ梺缁樺姍濞佳囧焻闂堟侗娓婚柕鍫濆暙閻忣亪鏌ｅΔ鍐ㄐ㈤柣锝囧厴瀹曪繝鎮欓埡鍌ゆ綌婵犵妲呴崹鎶藉煕閸儱鑸圭憸鐗堝笚閳锋帒霉閿濆牜娼愰柛瀣█閺屾稒鎯旈姀掳浠㈤悗瑙勬礃缁矂鍩㈡惔銊ョ闁哄鍨硅ぐ鍛存⒒娴ｈ櫣甯涢柡灞诲姂瀹曘儳鈧綆鍠楅崑鍌涚箾閹存瑥鐏柣鎾存礋閺屾洘寰勫☉姘煂闂佸憡姊瑰畝鎼佸蓟閿濆牏鐤€濠电姴鍟悵鏇烆渻閵堝啫濡搁柛搴ｆ暬楠炲啫鈻庨幙鍐╂櫆闂佸憡娲﹂崢娲儉椤忓嫧鏀介柣鎴濇川閸掔増绻涚仦鍌氣偓婵嬪极閸愵噮鏁傞柛娑卞墰缁犳岸姊洪崜鎻掍簼婵炲弶鐗曢蹇撯攽閸ャ儰绨婚梺瑙勫礃濞夋盯寮搁幋鐐电闁割偒鍋勬晶鎾煛瀹€瀣М闁诡喓鍨藉畷顐﹀Ψ瑜忛崢鎴炵節绾版ɑ顫婇柛瀣瀹曨垶顢曢敂缁樻櫔闂佹寧绻傚Λ娑氬姬閳ь剙鈹戦鏂や緵闁告ê鍚嬬粋宥咁煥閸涱垳锛滈梺缁樺姦閸撴瑩顢撳鍐炬富閻庢稒蓱閸婃劗鈧鍠楅悡锟犮€佸Δ鍛劦妞ゆ帒瀚悡姗€鏌熸潏鎯х槣闁轰礁锕弻锟犲磼濡　鍋撻幘鑸殿偨闁汇垹鎲￠埛鎴︽煕濞戞﹫鏀婚柟顖氱墦濮婂宕熼銏╀紑闂侀€炲苯澧存繛浣冲洤围缂佸娉曢弳锔芥叏濡炶浜鹃梺鐐藉劵缁犳捇鐛€ｎ喗鍊烽柤纰卞墯琚欓梻鍌氬€搁崐椋庢濮橆剦鐒界憸鏃堝箖瑜斿畷鍗炩槈濡吋鐒炬俊鐐€栭崝褔姊介崟顖氱９闁煎摜鍋ｆ禍婊堢叓閸ャ劍灏靛褎鐩弻锝夊箻鐠虹儤鐏堥梺鍝勭焿缂嶄礁顕ｉ鈧崺鈧い鎺嗗亾妞ゎ厼娲ら埢搴ㄥ箻瀹曞浂妲烽梻浣瑰濞叉牠宕愯ぐ鎺撳亗闁哄洢鍨洪悡鍐煟閻旂顥嬪ù鐘灲閺岋綀绠涢敐鍕仐闂佸搫鐬奸崰鏍€佸☉妯锋婵炲棙蓱椤ュ牆鈹戦悩娈挎毌闁告挻绻堥獮鍐磼濞戞绠氶梺姹囧€ら崹鐓幬ｆィ鍐┾拺闁告繂瀚ˉ娆撴煕濡や礁鈻曠€殿喖顭烽弫鎰緞鐎ｎ亙绨婚梻浣告啞缁哄潡宕曢幎鑺ュ亗闁逞屽墴濮婂宕掑▎鎴М闁圭厧鐡ㄧ划搴ｆ閻愬鐟归柍褜鍓氭穱濠勨偓娑櫳戞刊鎾煕閹惧啿绾х€点倖妞藉娲焻閻愯尪瀚板褎鎸抽弻锝呪槈閸楃偞鐝濋悗瑙勬礀瀹曨剟锝炲┑瀣濠㈣泛绠嶉崕闈涱潖缂佹ɑ濯村┑顔藉姀閸嬫捇鍩€椤掑嫭鐓曢悗锝庡亝鐏忣參妫佹径鎰厽婵☆垳鍎ら埢鏇㈡煕鎼淬垹濮嶉柡宀嬬秮楠炴鎹勯悜妯尖偓楣冩⒑闁稓鈹掗柛鏂跨焷閻忓啴姊洪柅鐐茶嫰婢ь噣鎽堕悙缈犵箚闁靛牆瀚崗灞俱亜閳轰礁绾х紒缁樼箞濡啫鈽夊▎妯活棓闂備浇銆€閸嬫捇鏌ら幁鎺戝姌濞存粍绮撻弻鈥愁吋閸愩劌顬嬮梺鐟板暱閸熶即鍩€椤掑喚娼愰柟鍝ヮ焾铻炴繝闈涱儏閽冪喖鏌ㄥ☉妯侯仹婵炲矈浜弻娑㈠箻濡も偓鐎氼剟宕规潏銊ょ箚闁靛牆娲ゅ暩闂佺顑嗙粙鎴犲弲濡炪倖鎸堕崹褰掑及閵夆晜鐓冮柍杞扮閺嗙偛鈹戦娑欏唉闁哄本鐩獮姗€鎮烽幍顔筋嚄闂備線鈧偛鑻晶顕€鏌ｆ幊閸斿酣骞戦姀鐘斀閻庯綆鍋勬禒娲⒒閸屾氨澧涚紒瀣姉閸掓帡宕奸弴鐔叉嫼缂傚倷鐒﹂敃鈺佲枔閺囩姷纾兼い鏃囧Г鐏忣參鏌ｉ敐鍥у幋闁轰焦鍔栧鍕節閸曞灚袨濠碉紕鍋戦崐銈夊储娴犲鍨傞柛鎾茶兌缁€濠囧箹閹碱厽绶氱紒璇叉閺屾洟宕煎┑鍫㈩唺闂佷紮绲炬繛濠囧蓟閵娾晜鍋勯柡澶嬪灥婵洜绱撴担绋库偓鍝ョ矓閻戣棄桅闁圭増婢樼粻鎶芥煙閹规劖纭炬鐐茬Ч濮婄粯鎷呴搹鐟扮闂佹悶鍔岄悥濂稿灳閿曞倸鐐婇柍鍝勫暕缁楀姊洪崫鍕犻柛鏂匡攻缁傚秴顭ㄩ崼鐔哄帾婵犮垼鍩栫粙鎴︺€呴鈧…鑳檨闁告挻绋撳Σ鎰板箳閺冨倻锛滃┑鈽嗗灥閸嬫劙鎮块崟顖涒拺缂侇垱娲樺▍鍡涙煟閳哄﹤鐏︾€规洘妞介崺鈧い鎺嶉檷娴滄粓鏌熼悜妯虹仴妞ゅ繆鏅濈槐鎺楀焵椤掑倵鍋撻敐搴℃灍闁绘挻娲橀妵鍕敇閻旈浠存繛瀛樼矌閸嬨倝寮婚埄鍐ㄧ窞閹兼惌鍠楃紞鍫熺箾閿濆懏鎼愰柨鏇ㄤ簼娣囧﹪宕奸弴鐐靛€炲銈庡墻閸犳捇宕曢悽绋胯摕婵炴垶鍩冮崑鎾绘晲鎼粹€茬敖闂侀潧妫欑敮锟犲蓟閻旇偐宓侀柛顭戝枤娴犲ジ鏌ф导娆戠М闁哄睙鍡欑杸婵ê鍚嬬紞鍫濃攽閻愯尙澧︾紒鐘崇墪椤繐煤椤忓拋妫冨┑鐐寸暘閸婃牠鎯勯鐐叉槬闁逞屽墯閵囧嫰骞掗幋婵愪患缂佺偓鍎抽…鐑藉蓟閻斿吋鍊锋い鎺嶈兌娴煎洤鈹戦埄鍐ㄧ祷闁绘锕﹂幑銏犫槈閵忕姵銇濇繛杈剧悼椤牏鈧冻绲剧换娑氣偓娑欘焽閻绱掔拠鎻掝伀闁告帗甯為埀顒婄秵娴滃爼宕ョ€ｎ喗鐓曟い鎰剁悼閳笺儲鎱ㄧ憴鍕垫疁婵﹥妞藉畷鐑筋敇閻愭彃顬嗛梻浣烘嚀閹诧繝骞愰幎鐣屽祦闊洦鎷嬪ú顏嶆晜闁告侗浜濈€氬ジ姊洪懡銈呅㈡繛鑼█閸┾偓妞ゆ巻鍋撶痪缁㈠弮閸┾偓妞ゆ巻鍋撴い顓犲厴瀵鈽夐姀鐘插祮闂侀潧顭堥崕杈┾偓娑崇到閳规垿鎮欓弶鎴犵シ闂佺粯鐗滈崢褔锝炶箛鏇犵＜婵☆垵顕ч鎾寸箾閹炬潙鍤柛銊﹀▕瀹曟繄绮欏▎鐐瘜闂侀潧鐗嗗Λ妤呮倶閵夆晜鐓欓柛鎰级閸炲鏌ｈ箛鎿冨剰闁宠鍨块幃鈺冪磼濡鏁繝纰樻閸嬪懘鎯勯姘煎殨闁规儼濮ら弲婊堟煟閿濆懐鐏辨い鏃€娲熷铏瑰寲閺囩偛鈷夐梺鎸庤壘閳规垿顢欑喊杈ㄐч梺闈涙搐鐎氫即宕洪敓鐘茬闁靛鍎辩粻锝夋⒒娴ｇ瓔鍤冮柛鐘愁殜閵嗗啯绻濋崶褎鐎梺褰掑亰閸樹粙宕曢悢鍏肩厓闁靛鍔岄惃娲煟閺嶎厺鎲炬慨濠勭帛閹峰懘宕妷顬劌顪冮妶鍐ㄥ姕闁规悂绠栧畷姘跺箳濡ゅ﹥鏅┑鐘诧工鐎氼剚鎯旀繝鍌楁斀闁绘劖娼欓悘鐔兼煕閵娿儲璐＄紒顔碱煼閹筹繝濡堕崶顭掔础闂備浇顕栭崹搴ｄ沪閽樺顥嶅┑锛勫亼閸婃垿宕曢懠顒佸床闁稿瞼鍋涢悡姗€鏌熸潏楣冩闁稿﹦鍏橀弻銈囧枈閸楃偛顫梺鍛婃礋缁犳牕顫忛搹鍦煓闁告牑鍓濋弫楣冩⒑缂佹﹩娈曠紒顔奸叄瀹曟岸骞掗弬鍝勪壕闁挎繂绨奸幉楣冩煕濮橆剦鍎旈柡灞剧☉椤劑鍩€椤掑嫭鍤勯柛顐ｆ礀閻鏌涢埄鍐姇闁抽攱鍨块弻娑㈠箻閺夋垹绁锋繛瀛樼矌閸嬨倝寮诲☉銏″亹闁惧浚鍋勭壕鎶芥倵鐟欏嫭纾搁柛銊ユ惈椤洩绠涘☉妯溾晝鎲歌箛娑欏剨闁割偁鍎查埛鎴炴叏閻熺増鎼愰柣蹇撳级缁绘稒鎷呴崘鎻掓殶闁瑰鍎靛濠氬磼濞嗘埈妲梺纭呭Г缁挸鐣烽幎钘壩ㄩ柍杞扮閻庮參鏌ｉ悩鑽ょ窗婵炲拑缍佸鎶芥晝閸屾稓鍘甸梺缁橆殔閻楀﹦娆㈤懠顒傜＜闁绘ê纾埊鏇㈡煏閸パ冾伃妤犵偞锚铻栭柍褜鍓涢埀顒佹皑閸忔ê鐣烽姘煎悑濠㈣泛顑傞幏缁樼箾鏉堝墽绉繛鍜冪悼閺侇喖鈽夐姀锛勫幈闂佸搫鍟犻崑鎾绘煟濡ゅ啫浠卞┑锛勬暬楠炲洭寮剁捄顭戞О婵＄偑鍊栭弻銊╁触鐎ｎ偅缍囬柛顐犲劜閳锋垹绱撴担濮戭亝鎱ㄦ径鎰厱閹煎瓨绋戦埀顒佺箞楠炲啴鍨鹃弬銉︾€婚梺瑙勫閺呮瑧鑺辨繝姘拺闁告繂瀚ⅹ闂佸憡鏌ㄩ柊锝夊春婵犲洤鍗抽柣鏃傜節缁ㄥ姊洪棃娑辨Ф闁稿氦娅曢弲鍫曞即閵忥紕鍘撻柣鐔哥懃鐎氼剟鎮橀幘顔界厱闁宠桨绀侀顓犫偓瑙勬礃閿曘垽宕洪埄鍐╁闁圭粯甯婃竟鏇㈡⒑鐟欏嫬顥嬪褎顨婇幃鈥斥槈濡繐缍婇弫鎰板炊閸撲礁濮奸梻浣告惈濡绱炴笟鈧璇测槈閵忕姷鍘撮梺璇″瀻閸屾凹妫滃┑鐘殿暜缁辨洟宕戦幋锕€纾归柡宥庡亝閺嗘粓鏌熼悜妯荤厸闁稿鎸搁～婵嬫偂鎼粹槅娼剧紓鍌欑贰閸犳牠鎮ч幘宕囨殾濠靛倸鎲￠崑鍕磽閸垹啸闁烩晛閰ｅ缁樻媴缁涘缍堥梺绋块閸熷潡鎮鹃悜绛嬫晢闁告洦鍓欓埀顒冨煐閵囧嫯绠涢幘璺侯杸闂佺粯鎸搁崯鏉戭潖濞差亜鍨傛い鏇炴噹閸撲即姊虹拠鑼闁瑰憡濞婂濠氭晬閸曨亝鍕冮梺鍛婃寙閳ь剙危閸儲鈷戦悗鍦У椤ュ銇勯敂璇茬仸闁挎繄鍋涢…銊╁醇濠靛鏁归梻浣虹帛閺屻劑骞夐垾鎵挎帗鎯旈姀銏㈢槇闂佹眹鍨藉褑鈪烽梻浣规偠閸斿酣宕㈣閸┿垽寮惔鎾搭潔濠殿喗锕徊鑺ョ閻愵剚鍙忔慨妤€妫楁禍婊呪偓瑙勬尭濡盯鍩€椤掍緡鍟忛柛鐘崇洴椤㈡俺顦归柛鈹垮劜瀵板嫭绻濇惔銏犲厞闂備焦瀵х换鍌炲箠瀹ュ棛鐝堕柡鍥ュ灪閳锋垿鏌熺粙鎸庢崳缂佺姵鎸剧槐鎺楀Ω閵娿儰姹楅梺鍏兼そ娴滆泛鐣峰Δ鍐當閺夌偞澹嗛惄搴ㄦ⒒娓氣偓濞佳嚶ㄩ埀顒傜磼闊厾鐭欓柟顔斤耿椤㈡岸鍩€椤掑嫬钃熺€广儱鐗滃銊╂⒑閸涘﹥灏扮€光偓閹间降鈧礁鈻庨幘鍐插敤濡炪倖鎸鹃崑銈呂涘畡閭︽富闁靛牆妫欑壕鐢告煕鐎ｎ偅灏甸柍褜鍓濋～澶娒哄鈧畷褰掑礈娴ｇ懓搴婂┑鐘绘涧椤戝懐绮堥崘顏呭枑闊洦娲滄稉宥嗘叏濡灝鐓愰柍閿嬪灩閹叉悂鎮ч崼婵堢懖闂佹寧绋撻崰鏍蓟閿濆绠抽柣鎰暩閺嗐倝鎮楀▓鍨灍鐟滄澘鍟撮垾锕傚Ω閳轰線鍞堕梺缁樻煥閹碱偊鐛崼銉︹拻濞达絽鎲＄拹锟犳煕鐎ｎ偅宕岄柕鍡楀暣瀹曘劎鈧稒锚濞堬絽顪冮妶鍡欏⒈闁稿鐩幃鍧楁倷椤戝彞绨婚梺瑙勫礃濞夋盯寮搁弮鍌滅＜闁抽敮鍋撻柛瀣崌濮婄粯鎷呴崷顓熻弴闂佹悶鍔忓Λ鍕€﹂崶顏嶆▉闂佹剚浜為崗妯侯潖缂佹ɑ濯撮悷娆忓娴犫晠姊洪崨濠冪叆闂佸府绲介悾鐑藉閿濆孩鈻岄梻浣虹《閺傚倿宕归挊澶樺殨妞ゆ帊鐒﹂崕鐔兼煙閻愵剚鍎楁繛鍏兼濮婄粯绗熼埀顒€顭囪閹广垽宕卞☉妯兼煣濠电姴锕ら悧鍡涙偪妤ｅ啯鐓熼柟閭﹀枛閸斿鏌嶉柨瀣仼缂佽鲸甯￠、娑樷槈濞嗘埈妲┑鐘媰閸曨厼寮ㄩ梺鍝勭焿缂嶄線骞冮姀鐘斀闁糕剝锚椤︹晠姊虹粙鍨劉妞ゃ劌锕璇测槈閵忕姷鍔撮梺鍛婂姦娴滄牗鎱ㄩ崶顒佲拺缂備焦蓱鐏忣參鏌涢悢璺哄祮妤犵偛顦辩划娆忊枎閸撗冨汲闂備礁澹婇崑鍛崲閸曨垁鍥敇閻愨晜鏂€闂佺粯鍔曞鍫曀夐悙鐑樼厵闁告稑锕ョ亸锕傛煕閳规儳浜炬俊鐐€栫敮濠囨倿閿曞伖澶愬醇閳垛晛浜鹃悷娆忓缁€鍐煥閺囨ê鐏查柕鍡曠閳诲酣骞橀崘鑼搸濠电姰鍨奸鏍垂閺夋５娲晝閸屾稑浜楅梺鍝勬储閸ㄦ椽鎮￠崘顔界厓閺夌偞澹嗛ˇ锔筋殽閻愮摲鎴﹀Φ閸曨喚鐤€闁规崘娉涢幃瀣⒑閹肩偛鍔撮柛鎾寸懇閹€斥槈閵忥紕鍘卞┑鐐村灥瀹曨剟寮搁幘缁樼厵闂佸灝顑嗛妵婵囨叏婵犲啯銇濈€规洏鍔嶇换婵嬪礋椤撶姷鐛ラ梻鍌欒兌椤牆顫濋敂濮愪粓闁归棿鐒﹂崑瀣箹閹碱厽绶氱紒璇叉閺岋綁骞囬崗鍝ョ泿闂侀€炲苯澧柛銊ョ仢閻ｅ嘲鈹戦崱娆愭畷闂佸憡娲﹂崜姘枍閸パ屾富闁靛牆鎳愮粻浼存煟濡も偓濡繂鐣疯ぐ鎺戠＜婵絽鍚嬪Λ鍐极閹版澘宸濇い鎾跺枑椤斿嫰姊绘担鍛婂暈闁告柨绻樺畷鎴﹀箻缂堢姷绠氶梺缁樺姦娴滄粓鍩€椤掍胶澧垫鐐村姈閵堬綁宕橀妸褝绱遍梻浣虹帛濮婂宕㈣婢规洝銇愰幒鎾跺幗闂佸綊鍋婇崜姘跺煝閺囩喓绠鹃柟鐐墯閻撳ジ鏌＄仦鐐鐎规洜鍘ч埞鎴﹀炊閼告妫ч梻鍌欒兌椤宕橀懗顖氭儓闂備礁鎼張顒傜矙閹捐鐒垫い鎺戯功缁夌敻鏌涚€ｎ亝鍣藉ù婊勬倐閹粙鎮介悽纰夌床闂佸搫顦悧鍕礉鐏炵煫褰掝敋閳ь剟寮婚悢纰辨晩閻熸瑥瀚悵鏃堟⒑娴兼瑧鎮奸柛蹇斆悾鐑藉醇閺囩喐娅滈梺鍛婄矆閻掞妇绱炵€ｎ喗鈷掗柛灞捐壘閳ь剟顥撳▎銏狀潩椤掑鍔烽悷婊冪Ф閸欏懘姊洪棃娑氬婵炶尙濞€瀹曟垿骞橀幇浣瑰兊濡炪倖鎸鹃崰鎾诲礄閳ユ剚娓婚柕鍫濇缁岃法绱掗幓鎺戔挃缂侇喖顑夐獮鎺楀棘閸濆嫪澹曢梺鎸庣箓缁ㄥ爼宕戦幘娲绘晣婵炴垶鐟﹂悵鏍⒑鐟欏嫬绲婚柟娴嬧偓鎰佸殫闁告洦鍓涚粻鐐亜椤愵偄鏋ょ紒澶樺枤閳ь剝顫夊ú鏍Χ閸涘﹣绻嗛柣鎴ｅГ閺呮粓鎮峰▎蹇擃仼妞ゅ繑妞藉濠氬磼濞嗘帒鍘″銈庡幖閻楁挸顕ｉ悽鍓叉晢闁告洦鍓欏▓鐐烘⒑缂佹ê濮﹂柛鎾寸洴閵嗗懘寮婚妷锔惧幗闂佸綊鍋婇崰鏍礉鐎ｎ喗鐓熼柟鎯х摠缁€瀣煛鐏炵偓绀冪紒缁樼洴瀹曞綊顢欑喊杈┾偓瀵哥磽娴ｉ缚妾搁柛姗€绠栧畷鎴﹀箻鐠囧弬锕傛煕閺囥劌鐏遍柡浣稿暣閺屾洝绠涚€ｎ亞浼勫銈嗘煥濞差參寮婚敐澶婄闁告鍋愰崑鎾诲冀椤撶倣锕傛煕閺囥劌鏋ら柣銈傚亾闂備礁婀遍崑鎾诲礈濮橆厾顩烽柛锔诲幘绾捐棄霉閿濆浂鐒鹃柤绋跨秺閺岋綁寮介銏犱粯濡炪値鍋勭换鎰弲濡炪倕绻愮€氼剛绮ｅ☉娆戠瘈闁汇垽娼у瓭闂佸摜鍠嶉崡瀹犳闂侀潧顦弲婊堝煕閹达附鍋ｉ柛銉簻閻ㄨ櫣绱掗悩鍐茬祷閼挎劙鏌涢妷锝呭闁靛洦绻勯埀顒冾潐濞叉﹢宕濆▎鎾跺祦婵せ鍋撴い銏＄懅閹叉挳鏁愰崱妤婁紲闂傚倸鍊烽懗鍫曗€﹂崼銉ュ珘妞ゆ帒瀚崑锟犳煏婵炵偓娅呯紒鈧崒鐐村€堕柣鎰緲鐎氬骸霉濠婂嫮鐭嬮柕鍥у楠炴鎹勬潪鐗堝煕濠电姭鎷冩担鍝ヤ紙闂佸搫鑻粔鐑铰ㄦ笟鈧弻娑㈠箻鐎靛憡鍣伴梺璇″枟閿氭い顐ｇ箖濞煎繘濡搁敂绛嬪敹闂傚倷鑳堕崑銊╁磿鏉堚晛顥氭い鎾卞灩濮规煡鏌ㄩ弮鍌氫壕闁哥姵鍔欓弻锝呂旈埀顒勬偋閸℃瑧绠旈柟鐑橆殕閳锋垿鏌涘Δ鍐ㄤ沪闁哥姵锕㈤弻鈥崇暆鐎ｎ剛鐦堥悗瑙勬礀閻栧ジ宕洪埄鍐╁闂佸灝顑呮刊鏉库攽閻樻鏆柍褜鍓濆▍鏇㈠煝閺囥垺鐓曢柟鎹愭硾閺嬪孩銇?"
                "\n\n"
                "婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽弫鎰板川閸屾粌鏋庨柍璇查叄楠炲棜顦虫い鏂垮缁辨捇宕掑▎鎺戝帯婵犳鍠楅幐鎶藉箖濡警娼╅悹杞扮秿閿曞倹鐓曢柡鍥ュ妼閺嬨倝鏌ｉ妶鍌氫壕闂傚倷绀佸﹢閬嶅磻閹捐绠氶悘鐐跺▏濞戙垺鍊烽柣銏㈡暩閿涙繃绻涙潏鍓ф偧闁哄拋鍋婂畷濂割敂閸喓鍘辨繝鐢靛Т閸熸壆绮婚悙纰樺亾濞堝灝鏋涙い顓犲厴楠炲啴濮€閵堝棙鍎梺闈╁瘜閸橀箖宕㈤鐐粹拻濞达絿顭堥ˉ蹇涙煟閹惧磭澧︾€规洘濞婇、姘跺焵椤掆偓閻ｅ嘲鈹戦崶褏绐為梺褰掑亰閸樻悂骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囶亞鐣垫鐐诧躬瀹曟﹢顢旈崱娆欑床缂傚倸鍊烽悞锕傛晪濠电偞鎯岄崳锝夊蓟閻旂⒈鏁嶆俊銈傚亾濞存粎鍋撴穱濠囨倷椤忓嫧鍋撻弴鐘冲床闁规壆澧楅崑瀣煕閳╁啰鎳呭☉鎾崇У閹便劌螣閸ф鎽甸梺鍝ュУ閸旀牜鎹㈠┑鍥╃瘈闁稿本绮岄。铏圭磼閻愵剙绀冩繛澶嬫礋閸┾偓妞ゆ巻鍋撶紒鐘茬Ч瀹曟洟鏌嗗鍛暫闂佺鍕垫畷闁稿绻濆娲敇閵娿儺娲梺鍛婄懃濡繂顫忓ú顏勫窛濠电姴鍊歌濠电偛鐡ㄧ划搴ㄥ磻閻愭亽鈧啫鈻庨幘绮规嫽闂佺鏈悷褔藝閿曞倹鐓欑痪鏉垮船娴滄壆鈧鍠氶弫濠氥€佸Δ鍛＜婵犲﹤鎳愰崢顖炴⒒娴ｄ警鏀伴柟娲讳簽缁骞嬮敂钘変簵濠电娀娼ч鍛不鐟欏嫮绠鹃柨婵嗛婢ь噣鏌嶈閸撴岸銆冩繝鍥х畺闁秆勵殔閻掑灚銇勯幒鎴濐仾闁抽攱鍨块弻鐔虹矙閹稿孩宕崇紓浣哄У閹瑰洭寮婚敍鍕勃闁哄倶鍊涢崥顐ｇ節绾版ê澧查柟顔煎€规穱濠囨倻缁涘鏅╅梺鑺ッˇ鍗炍ｉ敐澶嬧拻闁稿本鐟х粣鏃€绻涙担鍐叉处閸嬪鏌涢埄鍐槈缁炬儳缍婇弻锝夋偄缁嬫妫庨梺鍝勵儏缁夊綊寮诲☉銏犖ㄦい鏃傚帶椤亪姊虹紒妯诲鞍婵炶尙鍠栭幃锟狀敃閿曗偓閻愬﹪鏌曟繝蹇撶槣婵☆偅鐗犲娲礂閻撳寒鈧粍绻涙径瀣闁糕斁鍋撳銈嗗笂缁讹繝宕箛娑欑厱闁绘ê纾晶鐢告煃閵夘垳鐣遍柣锝忕節閺屽洭鏁冮埀顒€鈻撻妸鈺傗拺闁革富鍙€濡炬悂鏌涢悩鎰佹疁鐎规洘鍨垮畷鐔碱敃椤愶絽鐦滈梺璇插嚱缂嶅棙绂嶅┑瀣闁挎繂顦伴悡鐔哥箾閹存繂鑸规繛鍛У閹便劍绻濋崟顓炵闂佺懓鍢查幊鎰垝濞嗗繆鏋庨柣鎰靛墻濡繘姊婚崒娆掑厡妞ゎ厼鐗撻、鏍川閺夋垹鐤囬梺鍦濠㈡绮婚弻銉︾厪闊洤顑呴埀顒佹礈婢规洟宕楅懖鈺冾啎闂佺懓顕崑鐔煎箠閸愵亖鍋撳▓鍨灈婵炵》绻濆濠氭偄閻撳海顦ч梺鍏肩ゴ閺呮粌鈻撻鍕拺闁告稑锕ラ悡銉х磼婢跺﹦绉烘鐐插暣閺佹捇鎮╅崘韫盎闂備胶顭堢换妤呭磻閹版澘鍌ㄦい蹇撶墛椤ュ﹥銇勯幇鈺佺仾闁瑰吋鍔欓弻銊╁即濡搫濮庨梺瀹狀嚙缁夌懓鐣烽妸褉鍋撳☉娆樼劷闁告ü绮欏Λ鍛搭敃閵忊€愁槱濠殿喖锕ㄩ褏鍙呴梺鍦檸閸犳鎮″☉銏″€堕柣鎰絻閳锋棃鏌嶉娑欑闁哄瞼鍠栭、娑樷槈濞嗘ɑ顥堝┑鐘殿暯閸撴繈骞冮崒娑楃箚闁割偅娲栭獮銏′繆閵堝嫯鍏屽ù婊呭亾缁绘繈鎮介棃娴躲儵鏌℃担鍛婂暈闁逛究鍔戦、姗€濮€閻樼绱遍梻浣烘嚀婢т粙宕戦妸鈺佺劦妞ゆ帊绀佺粭鎺撱亜椤愶絿绠為柡浣瑰姍瀹曘劑顢楅埀顒勊夊顑芥斀闁绘ɑ鍓氶崯蹇涙煕閻樺磭澧甸柡浣稿暣婵℃悂濡烽姀锛勨偓娲⒑閹稿海绠撴繛璇х畵閿濈偤寮撮姀锛勫幍闂佺粯鍨堕敋婵炲牓绠栭弻锝夊籍閸屾艾浠橀梺鍛婎殕婵炲﹪寮婚敐澶婄睄闁割偒鍋呴ˉ鏍ㄧ箾鐎电甯舵繛宸幖椤繐煤椤忓拋妫冨┑鐐村灦閻熴儵藝閳哄懏鈷戦柛娑橈攻閳锋劙鏌ｉ悢鏉戝姦闁诡喗鍎抽悾锟犳焽閿旇棄缂撻梻渚€鈧偛鑻晶鎾煏閸℃洜顦︽い顐ｇ箘閹瑰嫰宕崟顓犲春濠碉紕鍋戦崐鏍涙担瑙勫弿闁靛牆顦伴崑鐔哥節婵犲倻澧涢柍閿嬪浮閺屾稓浠﹂崜褎鍣紓浣瑰姈濮婂湱鎹㈠☉娆愬闁告劖褰冮瀛樼箾閸粎鐭欓柣鎿冨亰瀹曞爼濡搁敂缁㈡О婵＄偑鍊ら崑鍛洪悢鐓庤摕闁跨喓濮撮悙濠囨煃鏉炴壆鎮奸柕澶堝劗濡插牓鏌熼幆褏锛嶇€涙繈鏌х紒妯煎⒌闁哄被鍔岄埞鎴﹀幢濡儤顏犻梻浣告惈濡盯宕戦妶澶婅摕闁挎繂顦粻濠氭倵闂堟稒鍟為柛锝勫嵆濮婃椽宕崟顓犱紘闂佸摜濮甸悧鐘诲Υ娴ｇ硶妲堥柕蹇曞Т閼板灝鈹戞幊閸婃挾绮堟笟鈧幃鐢稿籍閸屾粎锛濇繛杈剧稻閸ㄦ繈宕ラ锔界厱閻庯絻鍔岄埀顒佹礋閿濈偠绠涘☉娆愬劒闂佽崵鍠愬姗€顢氳濮婃椽宕崟顒€绐涢梺鍝ュУ閸旀瑩骞冮悽绋课╃憸蹇曞娴犲鐓曢悘鐐靛亾閻ㄦ垹浜歌箛鏇犵＝濞达綀妫勯悡鎰版煠瑜版帞鐣烘い銏″哺閺佹劙宕卞▎鎴犳婵犳鍠楅敃鈺呭储閽樺鏋嶉柡宥庡幗閳锋垿鏌涘☉姗堟敾濠㈣泛瀚湁婵犲﹤瀚粻鐐碘偓瑙勬礈閸犳牕鐣峰鈧、娆戞喆閿濆棗顏圭紓鍌氬€风粈渚€顢栭崨顖欑剨闁告稒娼欑粈澶愭煟閺傚灝鎮戦柣鎾存礋閺岋絽螣閼姐倕寮ㄩ梺鍛婄懃鐎氼參濡甸崟顖氼潊闁斥晛鍠氬Λ鍐渻閵堝啫鐏柨鏇樺灲楠炲啫顭ㄩ崼婵嗚€垮┑鈽嗗灥濞咃絽危閿濆鈷掗柛灞剧懅缁愭梹绻涙担鍐叉处閸嬪鏌涢埄鍐︿簵婵炴垶菤閺嬪酣鏌熺€涙鐭岄柛鎾卞妼椤啴濡堕崱妯鸿敿闂佹悶鍔嶅浠嬪箖闄囩粻娑樷槈濞嗘垵骞堟俊鐐€栭崝妤佹叏閹绢喗鍊挎繛宸簼閻撶喖鏌熼悜姗嗘畼闁伙絾妞介弻鈥崇暆鐎ｎ剛袦闂佽桨鐒﹂崝鏍ь嚗閸曨厸鍋撻敐搴′簼婵炲牆鎽滅槐鎾诲磼濞嗘劗銈板┑鈩冦仠閸斿酣宕氶幒鎴旀瀻闊洦娲樺▓鎯р攽閻樿宸ラ柣妤€妫濋幆灞轿旈埀顒勨€︾捄銊﹀磯濞撴凹鍨伴崜閬嶆⒑缂佹绠栭柣妤冨Т椤繑绻濆顒傦紲濠电偛妫欓崹鍨繆娴犲鐓熼幖杈剧悼閹虫鏌涘☉鍗炴灈閹兼潙锕铏圭矙閹稿孩鎷卞銈嗘磸閸ㄥ湱鍙呭銈呯箰鐎氣偓闁冲搫鎳忛悡鍐级閻愭潙顥嬫い锔肩畵閺屾稓鈧綆浜炲瓭濡炪値浜滈崯瀛樹繆閸洖骞㈡俊銈呭暟閹冲棝姊虹拠鎻掝劉闁告垵缍婂畷锝夊礃椤斿吋妲┑鐐村灟閸ㄥ湱绮婚搹顐＄箚闁靛牆瀚崗宀勬煕濮椻偓娴滃爼寮婚敐鍫㈢杸闁哄洨鍋樼划鑸电節閳封偓閸屾粎鐓撳Δ鐘靛仜閿曨亜鐣烽妸褉鍋撳☉娆樼劷闁告﹢浜跺娲传閸曨偀鍋撻挊澶嗘灃闁哄洨鍠愬▍蹇涙⒒閸屾瑧顦﹂柟纰卞亰閹本寰勫畝鈧粈濠傘€掑锝呬壕闂侀潧妫旂欢姘嚕椤曗偓瀹曠厧鈹戦崼顐Ｐу┑锛勫亼閸婃牠骞愰悙顒佸弿鐎光偓閸曨倠鈺呮煃閸濆嫬鈧悂鍩€椤掑倹鏆柟顔煎槻閳诲氦绠涢幙鍐х棯缂傚倷璁查崑鎾绘煕閹板吀绨界痪鎯с偢閹綊宕堕妸銉хシ闂侀€炲苯澧繛纭风節閻涱噣宕橀鑲╃暰閻熸粌顦靛銊︾鐎ｎ偄鈧敻鏌ㄥ┑鍡欏嚬缂併劋绮欓弻娑㈠籍閹惧墎鏆犲銈庝簻閸熷瓨淇婇崼鏇炲耿婵°倕鍟伴幊鍡涙⒑鐠囨彃顒㈤柛鎴濈秺瀹曟粓鎮㈤悡搴ｇ暫闂佺粯鍔曢幖顐﹀垂閸屾稏浜滈柟閭﹀枛灏忕紓浣靛妼椤嘲顫忓ú顏呭仭闁绘鐗婇崕鎾剁磽娴ｅ壊妲搁柣鏍濡喖姊洪幐搴㈢闁稿﹤缍婇幃锟犲即閵忥紕鍘梺鍓插亝缁诲牓顢撳Δ鈧…鑳槼闁瑰憡濞婂濠氭晬閸曨亝鍕冮梺鍛婃寙閸曨偄鐏″┑掳鍊楁慨鐑藉磻閻愯　鈧箓宕堕鈧粻鏌ユ煕閺囥劌鐏￠柛濠勭帛娣囧﹪顢涘杈ㄧ檨闂佺顑嗛幐鑽ゆ崲濠靛棭娼╂い鎾寸⊕鐎氱厧鈹戦悙瀛樼稇闁告艾顑夐幃鐤樄妤犵偛鍟缓浠嬪川婵犲嫬骞堥梻濠庡亜濞诧箑螞閹达附鍤€闁圭瀵掑▓浠嬫煟閹邦厼绲婚柡鍡秮閺岀喖顢欓挊澶婂Б闂佷紮绲剧换鍫ュ春閳ь剚銇勯幒鎴濐仾闁稿孩顨嗙换娑㈠幢濡闉嶉梺绋款儜缁蹭粙濡撮幒鎴僵闁绘挸娴锋禒顖炴⒑閸涘鎴︽儎椤栫偛钃熸繛鎴烇供濞尖晜銇勯幒宥囶槮婵炲牊顨呴埞鎴︻敊绾嘲濮涚紓渚囧櫘閸ㄥ爼鐛箛娑樺窛閻庢稒蓱閸庮亪姊洪懡銈呮瀾濠㈢懓妫濋、鏇熺附閸涘ň鎷绘繛杈剧到閹诧繝宕悙瀛樺弿濠电姴鍊荤粔娲煙椤斻劌娲﹂崑鎰叏閻熺増绀岄柛瀣尰閹峰懐鍖栭弴鐔衡偓濠氭⒑鐟欏嫬鍔ら柛鐔锋健瀹曨剟濡搁妷顔藉瘜闂侀潧鐗嗘鎼佸储閹绢喗鐓冪憸婊堝礈濞嗘垵顥氭い鎾跺Х閻捇鏌ц箛鎾冲辅闁稿鎸鹃幉鎾礋椤掑偆妲堕梻浣告憸婵敻鎮ч悩璇参ュù锝囩《濡插牊淇婇鐐存暠妞ゎ偄绉瑰娲捶椤撶偛濡洪梺鐟版啞閹倿銆侀弮鍥ヤ汗闁圭儤鎸撮幏濠氭⒑缁嬫寧婀伴柣鐔濆泚鍥晝閸屾稓鍘甸柣鐘叉厂閸涱垽绱甸梻浣烘嚀缁犲秹宕归挊澶屾殾闁圭儤鍨熼弨锕傛煙椤栧棗鍊搁ˉ姘節濞堝灝鏋熸い顓炴喘瀹曘垼顦圭€殿喗鎮傞幃銏ゅ礂閼测晛骞愰梻浣告啞娓氭宕㈡ィ鍐ㄦ槬闁挎繂鎳夐弨鑺ャ亜閺冨倹鍤€濞存粓绠栧缁樼瑹閳ь剙顭囪閹囧幢濡炪垺绋戦埥澶愬閻樻彃浜堕梻浣告啞缁嬫垿鏁冮敂鍓т笉濡わ絽鍟痪褔鏌涢锝囩畵闁抽攱姊荤槐鎺撳緞濡搫顫梺闈涙搐鐎氫即銆侀弴銏狀潊闁冲搫鍊甸弸鍛存煟鎼淬値娼愭繛鍙夛耿瀹曟繂鈻庨幘璺虹ウ闂佹悶鍎洪崜姘跺磻鐎ｎ喗鐓曟い鎰Т閻忊晜顨ラ悙鑼ｅǎ鍥э躬閹瑩顢旈崟銊ヤ壕闁哄稁鍘介崑瀣繆閵堝懏鍣洪柛銈呰嫰铻栭柨婵嗘噹閺嗘瑦鎱ㄧ憴鍕弨闁哄被鍔岄埞鎴﹀幢濮楀牏绀婃繝鐢靛仜閻楀懐鍒掑▎鎾宠摕闁挎繂顦粻娑欍亜閹哄秷顔夐柡瀣懇濮婅櫣绮欓崹顕呭妷濠碘槅鍋勯崯鏉戭嚕婵犳艾鐒洪柛鎰ㄦ櫅椤庢挾绱撴担鍓插剰缂併劑浜跺畷鎴﹀箻鐠囨煡鏁滃┑掳鍊愰崑鎾剁磼閻樿櫕绶查柍瑙勫灴閹晠骞撻幒鎾搭唲缂傚倷绀佹晶搴ㄥ磻濞戔懇鈧妇鎹勯妸锕€纾梺缁樼濞兼瑦瀵奸幇顒夋富闁靛牆妫欓懖鐘绘煕閵夛絽濡烽柟宄邦煼濮婅櫣绮欓幐搴㈡嫳闂佺厧缍婄粻鏍春閳ь剚銇勯幒鎴濃偓鎼佸储閹绢喗鐓欐い鏃€鍎虫禒閬嶆煛娴ｇ鏆ｇ€规洘甯掗～婵囨綇閳哄倹鐦掗梻鍌氬€风粈浣圭珶婵犲洤纾婚柛娑卞姸濞差亜鍐€妞ゆ劑鍩勫Λ婊堟⒑閸︻収鐒剧紒銊у劋缁傚秴顭ㄩ崼鐔哄幐闂佹悶鍎洪悡鍫濃枔閺傛５鐟邦煥閸垻鏆梺璇″枟椤ㄥ懘鍩㈤幘璇插瀭妞ゆ梻鏅禍鍫曟⒒娴ｈ櫣甯涢柟纰卞亞閹广垹鈹戦崱娆愭濠电偛妯婃禍婊堟倿濞差亝鐓曢柟鑸妽濞呭懏銇勬惔銏″磳婵﹥妞藉畷銊︾節閸愵煈妲遍梻浣告啞閹稿鎯勯鐐叉槬濠电姴娲ら崡鎶芥煏韫囥儳纾块柛姗€娼ч—鍐Χ閸℃瑥顫х紓浣割儐鐢ゆ＂闂佸壊鍋呯缓楣冨绩娴犲鐓冮柍杞扮閺嗙偤鏌涙繝鍐ㄥ闁哄备鍓濋幏鍛矙鎼存挸浜鹃柛褎顨堝畵渚€鏌涢埄鍐ㄥ毈婵¤尪宕电槐鎾存媴閸濆嫅鐐烘煕鎼淬劍娑фい顐㈢箲缁绘繂顫濋鍌︾床婵犵數鍋涘Λ娆撳礉濡ゅ懎围濞寸厧鐡ㄩ埛鎴炵箾閼艰泛鍚归柛妯荤洴閺屾稓鈧綆浜峰銉╂煟閿濆懎妲绘い顐ｇ矒閸┾偓妞ゆ帒瀚弰銉╂煥閻斿搫孝缁炬儳鍚嬮幈銊ヮ潨閸℃绠婚梺閫炲苯澧褏鏅Σ鎰板箻鐠囪尙锛滃┑顔斤供閸忔﹢宕戦幘鎼Ч閹艰揪绲块悞鍏肩箾閹炬潙鐒归柛瀣崌閹稿﹤鈹戦崰銏犵秺閹晛顔忛鐓庡闂傚倸鍊搁崑鍡涘垂閸洖钃熼柕濞垮劗閺€浠嬫煕閳锯偓閺呮粎鐟ч梻鍌欐祰濡嫰宕导鏉戠獥闁哄稁鍘奸拑鐔衡偓骞垮劚椤︻垶鎮″☉妯忓綊鏁愰崨顔兼殘濠电偛鐗嗗鍓佹崲濠靛棌鏋旈柛顭戝枤娴狀參姊洪悷鐗堝暈濠电偛锕ら锝囨嫚濞村顫嶅┑鈽嗗灦閺€閬嶅棘閳ь剟姊绘担鍛婂暈婵炶绠撳畷鎴﹀礋椤掑倻褰惧┑顔姐仜閸嬫挻鎱ㄦ繝鍐┿仢婵☆偄鍟埥澶婎潩瀹曞洨顔夋繝纰樻閸嬪﹪銆傞敃鍌涘殑闁割偅娲橀崕搴ㄥ箹閹碱厽绶氱紒璇叉閺岋綁骞囬崗鍝ョ泿闂侀€炲苯澧柣妤冨Т閻ｅ嘲鈹戞繝搴⑿柣搴＄仛濠㈡﹢鏁冮敃鍌氱闁告洦鍨版儫閻熸粌鐬肩划顓熷緞閹邦厸鎷虹紓鍌欑劍閿氬┑顔肩墦閺岋綁鏁愭惔婵堝嚬缂備礁鍊哥粔鎾€﹂妸鈺侀唶闁绘柨鎼敮楣冩⒒婵犲骸浜滄繛灞傚€濋弫鍐Χ閸℃ɑ鐝烽梺鑲┾拡閸撴稓澹曟總鍛婄厓鐟滄粓宕滃☉銏犵劦妞ゆ帒锕︾粔闈浢瑰鍕⒌鐎殿喓鍔嶇粋鎺斺偓锝庡亞閸樻捇姊洪棃娑辨Ф闁稿孩濞婇弫宥咁吋婢跺鍘遍梺鍐叉惈椤戝洭骞冩總鍛婄厓鐟滄粓宕滃┑瀣剁稏濠㈣泛鈯曞ú顏勫唨妞ゆ挾鍠庢禍顖涚節闂堟稑鈧鈥﹂崼銉ュ嚑濞撴埃鍋撻柡宀€鍠栭幃褔宕奸悢鍝勫殥婵°倗濮烽崑鎴﹀垂娴犲钃熺€广儱顦导鐘绘煕閺囥劌浜愰柛瀣崌閹筹繝濡堕崶鈺冨帬濠德板€х徊浠嬪疮椤栫偛鐓曢柟鐑橆殕閻撴洟鎮橀悙鏉戠濠㈣锕㈤弻宥堫檨闁告挻宀搁獮鍐磼濮樿鲸娈鹃梺鍦濠㈡绮婚悷鎳婂綊鏁愰崨顔藉枑闂佹寧绋掗悷鈺侇潖閾忓湱纾兼俊顖濇娴煎洦绻濆▓鍨灁闁稿﹥绻傞悾鐑藉箛閺夊潡鏁滃┑掳鍊撻懗鍫曞矗閸℃稒鈷戦柛婵嗗瀹告繈鏌涚€ｎ偆娲撮柛鈹惧亾濡炪倖宸婚崑鎾剁磽瀹ュ拑宸ラ柣锝囧厴瀵挳濮€閻樻鍚呴梻浣虹帛閿氶柛鐔锋健瀵悂骞嬮敂瑙ｆ嫼缂傚倷鐒﹂敃鈺佲枔閺冨牊鐓熸俊銈傚亾婵☆偅绋撻崚鎺楊敇閵忕姷顔婇梺鍝勫暙閸婂鏁嶅鍫熲拺闂侇偆鍋涢懟顖涙櫠椤栨壕鍋撻崹顐ｇ凡閻庢凹鍠楃粋鎺楁晜閸撗呯厯婵犮垹澧庨…鍫ニ夊鑸碘拻濞达絼璀﹂悞鍓х磼缂佹ê濮嶉挊婵囥亜閺嶃劎銆掓い鈺傚絻铻栭柨婵嗘噹閺嗙偤鏌嶉柨瀣伌婵﹥妞介、鏇㈠Χ閸涱剛鎹曢梻浣稿悑濡炲潡宕归柆宥呯柧闁割偅娲栫粻缁樸亜閺冨倹娅曢柛姗€浜跺铏光偓鍦濞兼劙鏌涙惔銈嗙彧缂佸倸绉归幃娆擃敄鐠恒劎鐣鹃梻浣虹帛閸旓附绂嶅鍫濈劦妞ゆ帊鑳舵晶閬嶆煛娓氬洤鏋熺紒缁樼箞瀹曠喖顢橀悩闈涘Ц婵犵數鍋為幐濠氬春閸愵喖纾婚柟鎯х亪閸嬫挾鎲撮崟顒傤槶闂佽桨绀侀…鐑藉Υ娴ｈ倽鏃堝川椤撶媭妲规俊鐐€栫敮鎺楀磹閹间胶宓侀柛顐犲劜閳锋帒霉閿濆牊顏犻悽顖涚洴閺屻劌顫濇潏鈺傦紡缂傚倷闄嶉崹褰掔嵁濡ゅ懏鐓涢柛娑卞幘閸╋綁鏌＄仦鑺ヮ棞妞ゆ挸銈稿畷鍗炩枎韫囨挾鐤勬繝鐢靛Х閺佹悂宕戝☉妯滄稑螖閸愨晛搴婇梺纭呮彧缁犳垿姊婚鐐寸叄闊洦鎸荤拹锛勭棯閹规劕浜圭紒杈ㄦ尰閹峰懐鎷犻敍鍕Ш婵犵數鍋炶ぐ鍐敋椤撱垹鐒垫い鎺嶇贰閸熷繘鏌涢悩宕囧⒌闁诡喓鍎茬缓浠嬪传閵夈儳銈﹂梺璇插嚱缂嶅棙绂嶉弽顓炵哗濞寸姴顑嗛悡鏇㈡煏婢跺鐏嶉柛瀣崌閺屾稓鈧綆鍋呭畷灞俱亜閵忥紕鈽夋い顐ｇ箞閺佹劙宕卞Ο缁樼帆闂傚倸鍊烽懗鍓佸垝椤栫偛绀夐柡宥庡厵娴滃綊鏌涢幇闈涙灈缂佺姵鐗犻弻鐔告綇妤ｅ啯顎嶉梺缁樻尵閸犳牠寮婚敐澶婃闁割煈鍠氭鍥р攽閻愬弶鍣归柟铏耿瀵鏁愭径瀣珳闂佸憡渚楅崢鎴掔昂濠碉紕鍋戦崐銈夊磻閸涱垰鍨濋柟鎹愵嚙閺勩儵鏌嶈閸撴岸濡甸崟顖氱闁瑰瓨绻嶆禒濂告⒑閸濆嫬顏ラ柛搴ｆ暬瀵顓奸崼顐ｎ€囬梻浣告啞閹歌鐣濋崨濠佺箚闁汇垻顭堢粈瀣亜閺嶃劍鐨戞い鏂匡躬濮婃椽鎮烽幍顔芥喖缂備浇顕х粔鐢电矉閹烘挶鍋呴柛鎰ㄦ杹閹锋椽姊虹憴鍕姸濠殿喓鍊濆顐︽焼瀹ュ棛鍘遍梺闈涱焾閸庢煡宕戦妷褉鍋撳▓鍨灈妞ゎ厾鍏橀獮鍐閵堝懐顦ч梺缁樻尭鐎涒晠鎮炬导瀛樷拻濞达絽鎽滈弸鍐╀繆濡炵厧濡兼い顏勫暣楠炴帡寮崹顔句喊闂備礁澹婇崑鍛哄鈧崺娑㈠箣閿旂晫鍘卞┑鐐村灦閿曨偊寮ㄦ繝姘厓闂佸灝顑呮慨宥夋煛鐏炶濮傜€殿喗娼欒灒闁惧繘鈧稓绀勯梺璇插椤旀牠宕板☉銏╂晪鐟滄棃宕洪妷锕€绶炲┑鐐靛亾閻庡姊鸿ぐ鎺戜喊闁告挻鐟︽穱濠囨惞椤愶紕绠氶梺缁樺姦娴滄粓鍩€椤掍胶澧电€殿喖顭锋俊鎼佸煛娴ｅ彨鏇㈡煟鎼搭垳绉甸柛鐘愁殜瀹曟垿鎮㈤崫銉х槇闂傚倸鐗婃笟妤呭磿閹扮増鐓曞┑鐘插閺嗩剟鏌熼鐓庢Щ闁宠姘︾粻娑㈠箼閸愌呮／缂傚倸鍊风拋鏌ュ磻閹剧粯鐓曢柟浼存涧閺嬬喖鏌ｉ幘瀛樼闁哄本娲樼换娑㈠垂椤旂厧顫氶梻浣侯焾椤戝啴宕曢悽绋胯摕闁挎繂鎳夊Σ鍫ユ煕濡ゅ啫浠﹂柣蹇撶墦閺屟勫濞嗘垹袦闂佽鍠楅…鍫㈢不濞戙垹绫嶉柛灞惧焹閸氬倸鈹戦悙鑼憼缂侇喖閰ｅ畷鎴﹀箻閼搁潧搴婂┑鐐村灟閸ㄥ湱绮婚敐澶嬬厽闁瑰瓨绻冮ˉ娆撴煟閵夘喕绨绘い顏勫暣婵″爼宕ㄩ婊庡敹闂備胶绮〃鍡欏垝閹炬剚鍤曟い鎰剁悼閻熷綊鏌嶈閸撶喎顕ｆ繝姘亜闁绘挸娴烽ˇ顓㈡偡濠婂啰绠崇€殿啫鍥х劦妞ゆ帒鍊荤壕钘壝归敐鍥╂憘闁搞倖鐟︽穱濠囶敃閿濆洨鐤勯悗娈垮枛椤兘寮幇顓炵窞濠电姴瀚弶鍛婁繆閻愵亜鈧牜鏁繝鍕闁哄被鍎遍崙鐘崇箾閸℃ɑ灏伴柍閿嬪灩缁辨帞鈧綆浜濋崑銉︺亜鎼淬埄娈樼紒杈ㄥ笧缁辨帒螣閾忛€涙偅闂備胶鎳撶粻宥夊垂瑜版帒鐓″璺侯煬濞尖晠鏌ㄥ┑鍡樺櫢濠㈣娲熷鍝勑ч崶褏浠惧銈嗘⒐閻楃娀骞冮悙娣亝闁告劏鏅濋崢鍗炩攽閳藉棗鐏ｇ紒顕呭灣娴滄悂鏁冮崒娑氬幐闁诲繒鍋涙晶钘壝洪幘顔界厱闁冲搫鍟禒杈┾偓瑙勬礀缂嶅﹪銆佸▎鎾村亗閹兼惌鍠楀〒鎰版⒒娴ｇ瓔鍤欏Δ鐘虫倐閹ê顫濋澶屽數濠碘槅鍨伴惃鐑藉磻閹炬剚娼╂い鎰╁灩缁侇噣姊虹紒妯圭繁闁革綇绲介悾鐑藉醇閺囥劍鏅㈡繝銏ｆ硾椤戝棗鈻嶅鍡欑瘈闁汇垽娼ф禒锕傛煕閵娿儳鍩ｉ柟顔惧厴婵＄兘鍩℃繝鍐╂珕闁荤喐绮庢晶妤冩暜濡ゅ懎鐓曢柟杈鹃檮閻撶姴鈹戦钘夊闁逞屽墯濞茬喎顕ｉ幖浣哥闁绘鏁搁敍婊冾渻閵堝棙鈷掗柛妯犲浂鏁嗛柕蹇嬪€栭悡娑㈡煕濞戞艾顣肩痪顓㈢畺閹藉爼寮介鐔哄幈闂佺鍩囬崝宥呪枍閸℃绠鹃柛顐ゅ枑缁舵煡鏌嶇憴鍕仸妤犵偛锕弻娑欑節閸愩劌顫掗悗瑙勬礃閸ㄥ潡鐛Ο鑲╃＜婵☆垳鍘х敮妤呮⒒娴ｈ棄袚闁挎碍銇勯敃浣诡棄閸楅亶鏌涜箛鏇ㄥ劆濞存粍绮撻弻銊╁籍閸ヮ煈妫勯梺宕囩帛濞茬喖寮婚敍鍕勃闁绘劦鍓涢ˇ浼存倵鐟欏嫭绀冮柛搴°偢钘濋柛娆忣槶娴滄粓鐓崶椋庡埌妤犵偞顨嗛妵鍕Ω閿濆懎濮﹂梺璇″枟閻熴儵顢欒箛娑辨晩闁绘挸楠搁ˉ宥夋⒒閸屾瑧顦﹂柣銈呮喘閿濈偞寰勯幇顒€鐎梺鍓茬厛閸犳岸寮抽敃鍌涒拺妞ゆ巻鍋撶紒澶嬫尦閹€斥槈閵忥紕鍘撻悷婊勭矒瀹曟粌鈽夊Ο婊愮秮楠炲洭寮剁捄顭戝悈闂備胶绮…鍥极閹间焦鏅繝闈涱儐閳锋垹绱掔€ｎ偄顕滄繝鈧导瀛樼厽闁绘梹绻傞幊蹇曗偓姘愁嚙闇夐柣鎾虫捣閹界娀鏌ｉ幘瀛樼闁哄被鍔岄埞鎴﹀幢濞戞墎鍋撳Δ浣虹闁告侗鍘捐倴闂侀€炲苯澧叉い顐㈩槸鐓ら柍鍝勫暟缁€濠偯归敐鍛喐闁哄棴闄勯幈銊ヮ渻鐠囪弓澹曞┑鐘殿暯閸撴繈鎮洪弴鈶哄洭鎼归銈囶啎闂佸壊鍋侀崕鎶芥偩閻戞ɑ鍙忓┑鐘插暞閵囨繄鈧娲滈崗姗€銆佸鈧幃娆撳箵閹烘繄鈧崬鈹戦敍鍕杭闁稿﹥鍨垮畷婵堜沪鏉炴寧绋戦埞鎴﹀幢濞嗘劖顔曢梻浣筋潐婢瑰棙鏅跺Δ鍛９濠电姵纰嶉悡鐘绘煙椤撶喎绗掗柛鏂诲€濋弻娑樜熼悜妯烘殘缂備胶绮换鍫熸叏閳ь剟鏌ㄥ┑鍡橆棤闁靛棙鍔曢—鍐Χ閸℃浠撮梺纭呮珪閿曘垽鐛崘顭戞建闁逞屽墯娣囧﹪鎮滈挊澹┿劍銇勯弮鈧崕鎶藉极閹间焦鈷掑ù锝堟閸氬綊鏌涢悩鍐插妞ゎ厼鐏濋～婊堝焵椤掑嫨鈧線寮崼顐ｆ櫍闂佺粯姊婚…鍫濐嚕閹稿海绡€闁汇垽娼у瓭闁诲孩鍑归崰姘跺极椤斿皷妲堥柕蹇ョ磿閸樼敻鎮楅悷鏉款伀濠⒀勵殜瀹曠敻宕堕埞鎯т壕閻熸瑥瀚壕鎼佹煕閺傝法肖闁瑰箍鍨归埞鎴犫偓锝庝簽閿涙粌鈹戦悙鏉戠仸闁荤啙鍥ф辈妞ゆ挾鍠撶弧鈧梺姹囧灲濞佳冩毄闂備浇妗ㄩ悞锕傚箖閸屾氨鏆﹂柟杈鹃檮閸嬫劖绻涢懠顒傚笡闁哄拋浜滈埞鎴︽偐鐠囇冧紣闂佺娅曢崝鏍矙婢跺鍚嬪璺侯儑閸樼敻姊虹拠鈥崇€婚柛婊冨暟缁€濠囨⒒娴ｅ憡鎯堟俊顐㈢摠娣囧﹪宕堕鈧粻鐔兼煙闂傚鍔嶉柛瀣儔閺屾盯顢曢敐鍥╃暠闂佸憡甯掗敃顏勵潖閻戞ɑ濮滈柟娈垮櫘濡差喖鈹戦埥鍡椾簼缂佽鐗嗛锝囨嫚濞村顫嶉梺闈涚箳婵潙鐣甸崱娑欌拺闂傚牊渚楅悞楣冩煕鎼淬垹顥嬮柤楦块哺缁傛帞鈧綆鍋€閹锋椽姊洪崨濠勨槈闁挎洏鍎佃棢闁哄稁鍋嗙壕濂告煟濡搫鏆遍柣蹇旀尦閺屽秹濡烽敂绛嬫閻庤娲橀敃銏ゃ€佸▎鎾冲簥濠㈣鍨板ú锕傛偂閺囥垺鐓冮柍杞扮閺嬨倖绻涢崼鐔糕拹缂佺粯鐩畷妤呮偂鎼达絼绱濇繝娈垮枛閿曘劌鈻嶉敐鍥у灊婵炲棗绻嗛弸搴ㄦ煙椤栧棗鍟ˉ搴ㄦ⒒閸屾瑧顦︽繝鈧柆宥佲偓锕傚醇閻斿憡鐝烽梺鑺ッ敍澶愭晲婢跺﹦鐤€闂佸搫顦冲▔鏇㈩敊婵犲洦鈷戦悷娆忓閸斻倗鐥紒銏犲箻缂侇噯缍侀幃娆戔偓闈涙憸閻﹀牓姊哄Ч鍥х伈婵炰匠鍐懃闂備浇顕х€涒晠宕欒ぐ鎺戠獥婵°倕鎳岄埀顒€鍟埢搴ょ疀婵犲啯鏉搁梺鍦劋婵炲﹤鐣烽幇顑╂梹鎷呴悷鏉夸紟闂備胶绮崹鐓幬涢崟顓烆棜缂備焦顭囩粻楣冩煙鐎电鍓遍柣鎺戞啞缁绘盯骞嬮悙鍐╁哺瀵劍绂掔€ｎ偆鍘遍梺鏂ユ櫅閸熶即骞婇崟顒傜闁割偁鍎抽悾鐑樻叏婵犲懏顏犵紒杈ㄥ笒铻ｉ柣鎴旀櫆鐎氫粙姊绘担绋挎毐闁搞垺鐓￠幃褔骞橀幇浣告濡炪倖鍔戦崺鍕触鐎ｎ亶鐔嗛悹杞拌閸庢垿鏌涘▎蹇旑棞闁宠鍨块幃鈺冪磼濡鏁繝纰樻閸嬪懘鎮烽埡鍕紓闂備胶绮崝鏇㈩敋椤撶姷涓嶅Δ锝呭暞閻撴洘绻涢幋婵嗚埞闁哄鍠撻埀顒冾潐濞叉牠寮甸鍕疄闁靛濡囩弧鈧梺鍛婂姀閺傚倹绂掗姀銈嗏拺闁革富鍙庨崝婊呯磼缂佹绠栧ǎ鍥э躬瀹曞ジ寮撮悙鑼崺婵＄偑鍊栫敮濠勭矆娴ｇ懓鍨旈柟娈垮枤绾句粙鏌涚仦鎹愬闁逞屽墴椤ユ挾鍒掗崼鐔虹懝闁逞屽墴閵嗕線寮介鐐茬獩闁诲孩绋掗敋濞存粓浜跺铏规喆閸曨偆顦ㄥ銈嗘肠閸パ冨挤闂侀潧顦弲婊堟偂閸愵亝鍠愭繝濠傜墕缁€鍫熸叏濡寧纭惧鍛存⒑閸涘﹥澶勯柛銊﹀缁骞庨懞銉у幈闂佹枼鏅涢崯銊︾閿曗偓椤法鎲撮崟顒傤槹濠殿喖锕︾划顖炲箯閸涙潙宸濆┑鐘插€瑰▓姗€姊洪挊澶婃殻濞存粌鐖煎濠氭晲閸涘倹姊圭粭鐔煎炊閵娧勬瘔缂傚倸鍊风欢锟犲窗閹烘鐤鹃柣妯款嚙缁犳牠鏌曡箛瀣偓鏍磻閸岀偛绠圭紒顔煎帨閸嬫挸鐣烽崶銉ヤ粡闂傚倸鍊搁崐鐑芥嚄閸撲礁鍨濇い鏍嚤濞戞瑦濯寸紒顖涙礃閻庢椽姊洪幐搴ｇ畵妞わ缚绮欏顐ｇ節閸ャ劎鍘搁梺鎼炲劘閸庨亶鎮橀鍫熺厽闁规儳顕埥澶嬨亜椤撯剝纭堕柟鐟板閹噣寮堕幋婵愭浆婵犵數濮幏鍐礋椤掑偆妲俊鐐€ら崣鈧柛搴☆煼钘濋柟缁㈠枟閻撴盯鏌涘鈧粈浣圭閻愮儤鐓曢柟鐑樻尭濞搭喚鈧鍣崳锝呯暦婵傚壊鏁冮柨婵嗘閻濓附绻濋悽闈浶ｆい鏃€鐗犲畷鏉课旈崨顓狀槷闂佸湱鍎ゅΛ浣规叏閸愭祴鏀介柣妯虹－椤ｆ煡鏌嶉柨瀣伌婵﹤顭峰畷濂告偄閸撲胶绠掓繝纰夌磿鐎氬繘宕堕妸銏″闂備礁鎲″ú锕傚磻閸曨垼鏁傛い鎰ㄦ寣閻熼偊鐓ラ柛鏇ㄥ墮閳ь剚鍔欓弻鐔碱敊閼姐倗鐓撻梺璇″枙缁瑩骞冮悾灞芥瀳濠㈣泛鑻花銉︾節绾板纾块柛瀣灴瀹曟劙寮借濞兼牕鈹戦悩瀹犲闁汇倗鍋撻妵鍕箛閸撲胶鏆犵紓浣哄Х婵炩偓闁哄本鐩俊鐑筋敊閹冨紬婵犵數鍋涢悧鍛垝濞嗘挸钃熼柨婵嗩槸缁犳稒銇勯幒宥堫唹闁哄鐟╁铏圭矙閸噮鍔夊┑鈽嗗亜閸熸潙顕ｆ繝姘労闁告劏鏅涢鎾剁磽娴ｅ壊鍎忕紒銊╀憾瀹曟垿骞樼拠鏌ユ暅濠德板€愰崑鎾剁磼閻樺磭澧甸柡灞剧洴楠炴ê螖閳ь剟宕愯ぐ鎺戠闁告劦鍠楅埛鎴︽煠閹帒鍓い蹇撶吇閸ヮ剚鐒肩€广儱瀛╅弲鈺呮⒑閻熼偊鍤熼柛瀣枔瀵囧焵椤掑嫭鈷戞慨鐟版搐閻忓弶绻涙担鍐插暞濮ｅ嫰姊婚崒娆愮グ婵℃ぜ鍔庣划鍫熺瑹閳ь剟鐛径鎰櫢闁绘灏欓悿鍕⒑闂堟单鍫ュ疾濞戞氨涓嶇紓浣骨滄禍婊堟煛閸愩劍鎼愮悮姘攽閻愬弶鍣规繛宸幖椤繐煤椤忓拋妫冨┑鐐村灦閼归箖銆傞崫鍕ㄦ斀闁绘劘娉涢惃鍝勨攽閻愨晛浜鹃柣搴ゎ潐濞叉﹢宕归崸妤冨祦婵せ鍋撴鐐叉处閹峰懘鎮烽弶鍨釜闂傚倸鍊烽懗鍓佸垝椤栫偛绠伴柛娑橆煬濞堜粙鏌涘┑鍕姢濞戞挸绉归幃褰掑炊閵娧佸仦闂佽　鍋撳ù鐘差儐閻撶喖鏌熼柇锕€澧紒鐙欏嫨浜滈柕澶涢檮瀹曞矂鏌＄仦鍓ф创濠碘剝鎮傛俊鎼佹晜缂佹﹩妫勯梻鍌欐缁鳖喚寰婇崸妤€绀傛慨妞诲亾鐎殿噮鍋婇獮鍥级閸喛鈧灝鈹戞幊閸婃洟宕导瀛樺仒妞ゆ洍鍋撻柡宀嬬稻閹棃鍨鹃崘鑼剁窡闂備胶顭堥鍡涘箲閸ヮ剙钃熺€广儱鐗滃銊╂⒑閸涘﹥灏甸柛鐘崇墵閻涱噣宕卞Ο鑲╂嚌闂侀€炲苯澧柣锝夋敱缁虹晫绮欑拠淇卞姂閺屻劑寮崶鑸电秷闁诲孩鑹鹃妶绋款潖婵犳艾纾兼繛鍡樺灱缁愭姊虹粙娆惧剰婵☆偅绻傞悾鐑藉箣濠靛啯顫嶉梺闈涚箚閳ь剝娅曢鐑樹繆閻愵亜鈧牠鎮уΔ鍐煓闁圭儤鍨熼弸宥夋煟濡偐甯涢柛濠傜仛缁绘盯骞嬮悜鍡曠磿濠电姴锕ょ€氼噣銆呴崣澶岀瘈濠电姴鍊绘晶娑㈡煟閹惧磭绠婚柣鎿冨亰瀹曟儼顧傜€规悶鍎遍…鑳槻鐎殿喖鐖兼俊鐢稿礋椤栨銊╂煏婢诡垰鍟犻崣锟犳⒒娓氣偓閳ь剛鍋涢懟顖涙櫠閸欏浜滄い鎰╁焺濡叉悂鎮￠妶澶嬬厸鐎广儱楠搁獮鏍炊閹绢喗鈷戠憸鐗堝笚閿涚喓绱掗埀顒佹媴閾忛€涚瑝闂佸搫绋侀崢浠嬫偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔告倐濮婃椽宕崟顒夋濡炪倖鍨甸ˇ闈涱嚕婵犳艾鐒洪柛鎰╁妿缁愮偤鏌ｆ惔顖滅М婵炰匠鍥х閻忕偠袙閺€浠嬫煃閽樺顥滃ù婊勭矒閹顫濋鐔哄嚒濡炪値鍋勭换鎴犳崲濠靛棭娼╂い鎺戝亰缁卞弶绻濆▓鍨灍闁挎洍鏅犲畷妤€顫滈埀顒€鐣烽幋锕€绠婚柟纰卞幗鏁堥梺纭呭閹活亞寰婇崸妤佸€块柛蹇氬亹缁犻箖鏌熼悙顒佺稇闁绘帒缍婇弻娑氣偓锝庡亝鐏忕増銇勯妸锝呭姦闁诡喗鐟ラ蹇涱敊鐟欙絾鐎伴梻鍌欑劍閹爼宕濈仦鐐珷濞寸姴顑呯粻褰掓煟閹伴潧澧┑顖涙尦閹嘲鈻庤箛鎿冧淮婵炲濮伴崹钘夘潖閻戞ɑ濮滈柟娈垮櫘濡差噣姊洪崫銉ユ瀾婵炲吋鐟╅幃楣冩倻閽樺顔婇梺瑙勬儗閸樹粙宕撻悽鍛娾拺閻熸瑥瀚徊缁樸亜閹存繃鍠橀柣娑卞櫍婵偓闁靛牆妫岄幏濠氭⒑缁嬫寧婀伴柣鐔村姂瀹曟鐣濋埀顒勬儉椤忓牜鏁囬柣鎰版涧閻撶喖鎮楃憴鍕缂侇喖鐭傞崺鐐哄箣閿曗偓闁卞洭鏌曡箛瀣伄闁告﹩鍨跺缁樻媴娓氼垱鏁梺瑙勬た娴滎亜顫忔禒瀣妞ゆ牗鑹鹃幆鐐烘煟鎼搭垳绉甸柛鎾村哺瀹曚即骞囬悧鍫㈠幗濠德板€愰崑鎾绘煟濡も偓濡稓鍒掗鐑嗘僵闁煎摜鏁搁崢浠嬫⒑鐟欏嫬鍔ょ痪缁㈠幘缁粯瀵肩€涙鍘撻柣鐔哥懃鐎氼剟鎮橀幘顔界厵妞ゆ梻鏅幊鍥殽閻愬樊鍎忛柍瑙勫灴瀹曞崬螣濞茶鏁奸梻鍌氬€风欢姘焽閼姐倕绶ら柟顖嗗本瀵屾繛瀵稿Т椤戝懘鎷戦悢鍏肩厪濠电偛鐏濋崝妤佷繆閹绘帞澧涘ǎ鍥э躬椤㈡稑鈹戦崱鏇熺潖婵＄偑鍊栭弻銊ッ洪妶澶嗏偓鏃堝礃椤斿槈褔骞栫€涙绠橀柣鈺侀叄濮婃椽宕妷銉︾€婚梺瀹︽澘濡界紒宀冮哺缁绘繈宕惰閸炲爼姊洪崫鍕窛闁稿鐩幊鎾诲垂椤旇鏂€闂佸疇妫勫Λ妤呮倶閳╁啩绻嗛柣鎰閻瑩鏌熼绛嬫疁闁圭厧缍婂畷鐑筋敇閻欏懐闂梻鍌欒兌椤牓寮甸鍕仭鐟滄棁妫熼梺鎸庢煥椤洘绂嶅鍫熺厵閻庢稒顭囩粻鏍ㄣ亜閵夛絽鐏柍褜鍓濋～澶娒洪弽顐ょ濠电姴鍊婚弳锔界節婵犲倸顏┑顖涙尦閺屟嗙疀閹剧纭€闂佸憡鏌ㄧ紞濠囧蓟閿濆棙鍎熼柨娑樺閺嗘盯姊虹粙鍧楊€楃€规洦鍓濋悘瀣煙閸忚偐鏆橀柛鏂跨灱婢规洘绻濆顓犲幈濠电偞鍨堕…鍥箺閻樼粯鐓熼柟鎯х摠缁€瀣煛瀹€鈧崰鏍箠濠婂牜鏁嗛柍褜鍓氭穱濠冪鐎ｎ偆鍘告繝銏ｆ硾閿曪妇绮斿ú顏呯厸?"
                "婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽弫鎰板川閸屾粌鏋庨柍璇查叄楠炲棜顦虫い鏂垮缁辨捇宕掑▎鎺戝帯婵犳鍠楅幐鎶藉箖濡警娼╅悹杞扮秿閿曞倹鐓曢柡鍥ュ妼閺嬨倝鏌ｉ妶鍌氫壕闂傚倷绀佸﹢閬嶅磻閹捐绠氶悘鐐跺▏濞戙垺鍊烽柣銏㈡暩閿涙繃绻涙潏鍓ф偧闁哄拋鍋婂畷濂割敂閸喓鍘辨繝鐢靛Т閸熸壆绮婚悙纰樺亾濞堝灝鏋涙い顓犲厴楠炲啴濮€閵堝棙鍎梺闈╁瘜閸橀箖宕㈤鐐粹拻濞达絿顭堥ˉ蹇涙煟閹惧磭澧︾€规洘濞婇、姘跺焵椤掆偓閻ｅ嘲鈹戦崶褏绐為梺褰掑亰閸樻悂骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囶亞鐣垫鐐诧躬瀹曟﹢顢旈崱娆欑床缂傚倸鍊烽悞锕傚煟閵堝鏁傞柛顐墰缁嬪繘妫呴銏″婵﹨宕靛褔鍩€椤掆偓閳规垿顢欓弬銈勭返闂佸憡鎸鹃崰鏍х暦椤掑嫬閱囬柡鍥╁暱閹疯櫣绱撻崒娆戝妽閽冮亶鏌嶉柨瀣诞闁哄本绋掗幆鏃堟晲閸℃ɑ鐦撻柣搴ゎ潐濞叉﹢宕归崸妤冨祦婵☆垵鍋愮壕鍏间繆椤栨繃顏犳俊缁㈠枛閳规垿鎮╅鑲╀紘濡炪値鍋勯ˇ閬嶅箲閵忋倕绀冩い顓熷灦鐎靛本绻涚€电孝妞ゆ垵鍟撮崺鈧い鎴ｆ硶缁愭梻鈧鍣崳锝呯暦閻撳簶鏀介柛顐亝鏁堟繝纰夌磿閸嬫垿宕愰弽顓熷亱婵°倕鍟伴惌娆撴煙閻戞ê鐏嶉柡瀣閺岋繝宕掑杈ㄧ殤闂佽　鍋撳ù鐘差儐閻撶喐淇婇姘变虎闁汇劎鍎ゆ穱濠囶敃閵忕媭浼冮梺鍝勫閸撴繂顕ラ崟顒傜瘈闁告洦鍓涘▓銈夋⒒娴ｄ警鐒炬い鎴濇楠炴垿宕堕鍌氱ウ闂佹悶鍎洪崜娆戠棯瑜旈幃瑙勭瑹椤栨粌甯ㄧ紓渚€浜舵禍璺侯潖缂佹ɑ濯寸紒娑橆儐缂嶅牓姊虹粙鎸庡攭婵炲懏娲熷鏌ユ嚋閸偄鍔呴梺鎸庣箓閹峰螞濠婂嫮绡€闂傚牊绋戦埀顒佹倐楠炲鏁撻悩鍐蹭簵濠电偛妫欓幐濠氬煕閹寸偑浜滈柟鎯у船婵″潡鏌ｉ敐鍫滃惈闁逞屽墯椤旀牠宕板璺虹；闁规崘鍩栧畷鍙夌箾閹存瑥鐏╅梺鍗炴喘閺岋綁寮幐搴㈠枑濡炪倧瀵岄崢鍓ф閹惧瓨濯村ù鐘差儏閹界敻鏌ｉ姀鈺佺仯闁稿鍠庡嵄闁圭増婢樼粻鎶芥煙閸愯尙锛嶉柛鐘崇墵楠炲﹪寮介鐐靛幐闂佸憡鍔忛弲婊堟儊閹烘梻纾介柛灞捐壘閳ь剚鎮傚畷鎰版倻閼恒儱娈戦梺鍛婃尫缁€渚€宕瑰┑鍥ヤ簻闁哄秲鍔庨惌瀣偓瑙勬礃閻擄繝寮诲☉銏╂晝闁挎繂娲ㄩ悾濂告⒑閸濆嫭锛旂紒鐘虫崌瀵鎮㈤崗鐓庘偓缁樹繆椤栨繃顏犻柛鏃傤焾閳规垿鎮欓懠顒佺檨闂佸搫鎳愭慨鎾綖韫囨梻绡€婵﹩鍓涢敍婊冣攽椤旂瓔鐒介柛妯犲啠鏋旈柛鎾茶兌绾捐棄霉閿濆棗绲诲ù婊呭亾缁绘繈濮€閿濆懐鍘梺鍛婃⒐閻楃娀宕哄☉銏犵婵°倓鑳堕崢閬嶆煟韫囨洖浠滃褌绮欓獮濠囧幢濞戞瑧鍘遍棅顐㈡处閹歌锕㈡导瀛樼厪闁搞儜鍐句純濡炪們鍨洪敃銏ゅ箖濞嗘挻顥堟繛鎴炲笒瀵板秴鈹戦敍鍕杭闁稿﹥鍨垮畷鐟懊洪鍛罕闂佺粯顭堢亸娆撳汲閿旇姤鍙忔俊鐐额嚙娴滄儳顪冮妶鍐ㄧ仾闁荤啿鏅犻獮濠囧冀椤撶偟鍘告繝鐢靛Т閸烆參濡烽埡鍌楁嫽闂佺鏈悷銊╁礂鐏炰勘浜滈柕蹇曞闊剚顨ラ悙瀛樺磳妞ゃ垺妫冨畷鍗炩枎鎼达絿鎲归梻鍌欒兌椤㈠﹪骞撻鍫熲挃闁告洦鍘搁崑鎾愁潩椤掍礁娈楅梺鍝勭焿缂嶄礁顕ｉ鍕瀭妞ゆ棁妫勯埀顒夊灦濮婅櫣绱掑Ο璇叉殫闂佸摜濮甸悧鐘差嚕婵犳碍鏅搁柣妯垮皺椤︺劑姊洪棃娑辩叚缂佺姵鍨垮畷鎴濐吋婢跺鎷洪梻渚囧亞閸嬫盯鎳熼鐐插偍闁圭虎鍠楅悡鏇㈡倵閿濆骸浜濈€规洖鏈幈銊︾節閸涱噮浠╃紓渚囧枟閻熴儵鍩㈡惔銊ョ畾鐟滃秵绔熸径鎰拻濞达絿鍎ら崵鈧梺纭咁嚋缁绘繈鐛崘顔肩＜闁绘劕寮跺Σ顒勬⒑闂堟侗妾х紒鐘冲灩濞嗐垽鎮欏ù瀣杸闂佺粯鍔欏褎绂嶆ィ鍐╃厽閹肩补鍓濋幆鍫熴亜椤忓嫬鏆ｅ┑鈥崇埣瀹曞崬螣閾忚鈻婇梻鍌欒兌椤牓鎯夋總绋跨；婵炴垶鐟ч々鐑芥煙閹殿喖顣奸柍閿嬪笒闇夐柨婵嗘川閹藉倿鏌涢妶鍛殻闁哄本鐩幃鈺呭箛娴ｅ湱鏉归梻浣芥〃缁€渚€宕€涙ɑ鍙忛柍褜鍓熼弻鏇㈠醇濠靛洤娅ら梺璇插瘨閸撶喎顫忓ú顏勫窛濠电姴鍊歌闂備礁鎽滄慨鐢告偋濠婂嫮鐝堕柡鍥ュ灩缁€鍌炴煠濞村娅囨い鏃€娲熷娲偡闁箑娈堕梺绋款儑婵數绮╅悢濂夋建闁逞屽墴楠炲啯绂掔€ｅ灚鏅┑鐐村灱妞存悂鎮挎笟鈧娲传閸曨厾鍔圭紓鍌氱С缁舵岸鐛崘顔碱潊闁靛牆鎳嶇槐鍫曟⒑闂堟冻绱￠柛娑卞幖缁楁帞绱撻崒姘偓鎼佸磹妞嬪孩顐介柨鐔哄Т缁愭淇婇妶鍛櫣缂佺姳鍗抽弻鐔兼⒒鐎电濡介梺绋款儌閺呮繈鍩€椤掑倹鍤€閻庢矮鍗冲畷鎴炵節閸ャ劌浜楅梺闈涱槴閺呮粓鎮￠弴銏＄厵闁哄鐏濋。宕囩磼鐎ｎ亶鐓奸柡宀嬬稻閹棃鍩ラ崱娆忔倯婵犳鍠栭敃銊モ枍閿濆應妲堥柣銏㈩焾瀹告繃銇勯弬鍨倯闂佹鍘剧槐鎾诲磼濞嗘劗銈伴柣蹇撴禋娴滄粏鐏嬮梺鍛婃处閸ㄩ亶宕曞鍡愪簻闁圭儤鍨甸顏堟煃闁垮娴柡灞剧〒娴狅箓宕滆閸ｎ喖顪冮妶蹇氼吅缂佺姵鎹囧璇测槈濮楀棙鍍靛銈嗗笒椤︻垶宕滃畷鍥╃＝濞撴艾娲ら弸娑㈡煥閺囥劋閭柣娑卞枛椤粓鍩€椤掑嫨鈧礁鈻庨幘鏉戞異闂佸啿鎼崐濠氬矗閸曨偀鏀介柣妯虹仛閺嗏晛鈹戦悙鈺佷壕婵犵數鍋橀崠鐘诲礂閻樿櫕銇濆┑鈩冩倐閸┾剝鎷呴崫鍕闂傚倷绀侀幖顐﹀疮椤愶箑纾归柣銏㈩焾绾惧鏌熼幑鎰惞鐎规挷绶氶弻娑⑩€﹂幋婵囩亪婵犳鍠栨鎼佲€旈崘顔嘉ч煫鍥ㄦ礈缁愭姊洪崨濠庢畷濠电偛锕悰顕€宕橀鑺ユ闂佺粯锚閸熸寧绂嶅鍫熲拺缂佸娉曠粻娲煕鐎ｎ偄濮嶇€规洏鍨介幃浠嬪川婵炵偓瀚藉┑鐐存尰閼规儳煤閵堝拋鍤曢悹鎭掑妿绾惧ジ鏌ｅΟ鍝勬毐闁诲骏绠撻弻锟犲川椤撶姴鐓熼悗娈垮枦濞夋稖鐏嬮梻鍌氱墛缁嬫挾绮斿ú顏呯厵妞ゆ棁顫夊▍鍛存煟閿濆洤鍘寸€规洖鐖兼俊鎼佸Ψ閵壯傜敾闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敂钘夊壒婵犮垼娉涢張顒€鐣烽崣澶岀瘈闂傚牊绋掗ˉ鐘绘煛閸☆厾鐣甸柡灞剧☉铻栭柛鎰╁妷閸嬫捇鏁愭径瀣簻闂佺绻掗崢褍鈻撻幇鐗堚拺闁告劕寮堕幆鍫ユ煕閻曚礁浜為柡渚囧櫍婵℃悂鍩￠崒妤佸闂備胶顭堥張顒勬偡瑜旇棟闁挎洖鍊归悡娆戠棯閺夊灝鑸瑰ù婊呭仱閺岀喖顢氶崨顓熺彎濡炪們鍨哄ú鐔煎极閸愵喖鐒垫い鎺戝€婚惌鍡楊熆閼搁潧濮堥柣鎾寸懇閹鈽夊▎妯煎姺缂備胶濮伴崕鐢稿蓟濞戙垹围闁糕剝顭囬ˇ銊╂⒑闂堟稒鎼愰悗姘緲椤曪綁寮堕幊铏閸┾偓妞ゆ帊鑳堕々鎻捨旈敐鍛殲闁稿﹦鏁婚幃宄扳枎韫囨搩浠剧紓浣插亾闁告劦鍠楅悡鏇㈠箹缂佺増婢樻禒顕€鏌﹀Ο鑽ょ疄鐎殿喖鐖煎畷鐓庘槈濡警鐎撮梻浣告啞閻熴儳鎹㈠鈧獮鍐ㄧ暋閹佃櫕鐎婚棅顐㈡处閹尖晜瀵肩仦瑙ｆ斀闁绘劘灏欐晶娑欍亜椤撶偞宸濇俊鍙夊姍楠炴帡骞樼€靛摜肖闂備線娼ч…顓犵不閹达附顥夌€广儱顦伴埛鎴︽煟閻斿憡绶叉俊鎻掝煼閺岀喖鎼归顒冣偓鍧楁煟濞戝崬娅嶆鐐搭焽閹风娀鎳犻澶婃暯闂佽楠哥粻宥夊磿闁秴绠悗锝庘偓顓熺☉椤劑宕橀敐鍡樻澑闂備胶绮敋闁诲繑宀稿鎶藉煛娴ｅ弶鏂€濡炪倖妫侀褍鐣甸崱娆屽亾鐟欏嫭绀€缂傚秴锕獮鍐焺閸愨晛鍔呭┑鈽嗗灥瀹曞灚绂嶅▎鎰瘈闁汇垽娼ф禒锕傛煕椤垵鐏︾€规洜顢婇妵鎰板箳閹惧厖绨甸梻渚€鈧偛鑻晶瀛樻叏婵犲啯銇濈€规洦鍋婂畷鐔碱敆閸屾稈鏋旀繝纰樻閸嬪﹪銆傞敃鍌涘€块柨鏇炲€归崕鎾荤叓閸ャ劎鈯曢柍閿嬪笒闇夐柨婵嗘噺閸熺偤鎮归幇鍓佺瘈闁哄本绋掗幆鏂库槈濡嘲浜炬繝闈涱儑瀹撲線鏌熼悧鍫熺凡鐎瑰憡绻傞埞鎴︽偐閹绘帩浼屽┑鐐插级閹倸顫忓ú顏呭殥闁靛牆鎳忛悘鍫ユ⒑缁嬫鍎忛柨鏇樺€濇俊鎾箳閹惧墎鐦堝┑顔斤供閸橀箖宕㈤鍫熲拺闁告挻褰冩禍婵堢磼鐠囨彃鏆ｉ挊鐔兼煟閹邦喖鍔嬮柣鎾冲暣濮婃椽宕归鍛壈濠电偞鎯岄崳锝夊蓟閿涘嫪娌柛鎾椻偓濡插牓鏌ф导娆戠М闁哄矉绲借灒閻犲洩灏欑粊宄邦渻閵堝懏绂嬪ù婊庝邯瀵鈽夊Ο閿嬬€婚棅顐㈡处濞叉粓顢欓幒鎳虫棃鎮╅棃娑楁勃闂佺粯顨嗗ú婵娿亹娴ｅ壊娓婚柕鍫濇閸у﹪鏌涚€ｎ偅灏柍瑙勫灴閸ㄩ箖鎳犻鍌滃幆闂備礁鎼張顒傜矙閹烘梹宕叉繝闈涱儏绾惧吋绻濇繛鎯т壕缂備緡鍠氶弫鍝ユ閹惧瓨濯撮柧蹇曟嚀缁楋繝姊洪悜鈺傛珦闁搞劋鍗抽幃楣冩倻閼恒儱浜楅柟鐓庣摠钃遍柡鍌楀亾闂傚倷绀佹竟濠囧磻閸涱垰鍨濋煫鍥ㄦ惄閻庡爼鏌涘☉姗堝姛缂佲檧鍋撻梻浣圭湽閸ㄨ棄顭囪缁傛帒顭ㄩ崼鐔哄幍闂佸憡鍔曞鍫曞箲閿濆洨纾兼い鏃囧Г椤ュ棝鏌曢崶銊ュ妤犵偞甯￠獮瀣晲閸℃ê鏆梻鍌氬€峰ù鍥р枖閺囥垹绐楅柟鎯х摠閸欏繘鏌熺紒銏犳灍闁稿﹤娼￠弻娑⑩€﹂幋婵呯按婵炲瓨绮嶇划鎾诲蓟閻斿吋鍊绘俊顖濇娴犳潙顪冮妶鍛濞存粠浜濠氭晲婢跺﹦顔婇梺鍝勬川閸嬫ê效濡ゅ懏鈷戦梺顐ゅ仜閼活垱鏅堕鍓х＜闁绘灏欐晥閻庤娲樺ú鐔煎蓟閸℃鍚嬮柛娑卞灣閺嬪啴姊绘笟鈧埀顒佺☉瀹撳棝鏌涚€ｎ亷韬€殿噮鍋呯换婵嬪炊閵娧冨箞闂備焦鏋奸弲娑㈠疮娴兼潙鐓€闁哄洢鍨洪悡鍐⒑閸噮鍎忛柣蹇旀尦閺岋紕浠﹂崜褉妲堥梺瀹犳椤︻垶锝炲鍫濋唶婵犻潧妫顒勬⒒閸屾瑧顦﹂柣銈呮搐铻為柛鏇ㄥ瀬閸ヮ剚鍋ㄧ紒瀣劵閹芥洟姊洪幐搴ｇ畵婵☆偅顨堢划濠氭偐缂佹ǚ鎷洪梺鍛婄☉閿曘儵鍩涢幇鐗堢厱闁靛ě鍕瘓闂佽鍣ｇ粻鏍箖濠婂牊瀵犲璺虹焾閸氬懘姊绘担鐟邦嚋婵炴彃绉瑰畷鎴﹀箻閸撲胶锛滈梺缁樏壕顓灻洪幘顔界厸鐎光偓鐎ｎ剙鍩岄柧缁樼墵閺屽秷顧侀柛鎾跺枛楠炲啳顦剁紒鐘崇☉閳藉螣閼测晛骞€闂傚倷绀侀幉鈥趁洪敃鍌氬瀭闂侇剙鍗曟径瀣瘈闁告劧缂氱花濠氭⒑鐟欏嫬顥愰柡鍛洴閹﹢顢旈崟鐢靛數闁荤姴鎼幖顐︻敂椤撱垺鐓涚€光偓閳ь剟宕版惔顭掔稏闁靛浚婢€濞岊亪鏌﹀Ο渚Ч闁稿寒浜缁樻媴閻戞ê娈岄梺鎼炲灱鐏忔瑧妲愰悙瀵哥瘈闁搞儜鍕氶梻浣告啞濞诧箓宕归幍顔剧焼闁告劦鍠楅悡銉╂煛閸愩劍澶勭痪顓炵埣閺岋綁鍩℃笟鈧崣鍕叏婵犲嫮甯涢柟宄版嚇瀹曘劍绻濋崘銊ュ闂傚倷绀侀幗婊堝窗閹惧绠鹃柍褜鍓涢埀顒冾潐濞叉﹢宕归崸妤冨祦婵☆垵鍋愮壕鍏间繆椤栨粌甯舵鐐茬墦濮婄粯鎷呴崨濠冨創闂佸摜鍠撴繛鈧€规洘鍨块獮妯肩磼濡厧骞楅梻浣虹帛閺屻劌顕ｇ捄琛℃瀺闁告侗鍠撴禍婊堟煛閸ユ湹绨界紒瀣吹缁辨帞绱掑Ο鑲╃暤濡炪値鍋呯换鍫ャ€佸Δ鍛＜婵﹩鍎烽妶澶嬧拻闁稿本鐟чˇ锕傛煙鐠囇呯瘈鐎规洘绻堥獮瀣晝閳ь剛绮堟径鎰閺夊牆澧介幃濂告煟濠婂喚鐓奸柡宀嬬秮楠炲洭顢欓悡搴☆瀱闂備胶绮幐楣冨窗閺嶎厽鍋傛い鎰剁畱閻愬﹪鏌曟繝蹇擃洭妞わ负鍎茬换娑氣偓鐢殿焾琚ラ梺鍝勬噺缁秶绮氭潏銊х瘈闁搞儴鍩栭弲婵嬫⒑闂堟稓绠冲┑顖ｅ幗缁傛帡宕滆绾捐棄霉閿濆牜娼愰柍閿嬪浮閺屾盯鎮╅崘鎻掝潓濡炪倖娲忛崕闈涚暦閻旂⒈鏁嶆慨妯夸含閺夊憡淇婇悙顏勨偓鏍箰閼姐倗鐭欓柟鐑樻煛閸嬫挸顫濋鎯т划濠殿喖锕︾划顖炲箯閸涙潙宸濆┑鐘插€瑰▓妯肩磽閸屾瑧顦﹂柟纰卞亜椤洭鍨惧畷鍥ㄦ闂佸搫娲ㄩ崰鎰礊閸ヮ剚鐓忓┑鐐戝啫鏆婇柛娆戝仜閳规垿鎮╁▓鎸庢缂備浇椴稿ú鐔风暦閹达箑绠ｉ柨鏇楀亾缁炬儳缍婇弻鐔告綇閸撗呮殸缂備讲鍋撳璺哄閸嬫捇宕楁径濠佸闂備礁鎲″ú锕傚磻閸℃稒鍋柛銉戔偓閺€浠嬫煃閽樺顥滈柣蹇嬪劜閵囧嫰寮崠鈥冲闂佺懓绠嶉崹钘夌暦閸楃偐妲堟繛鍡樺灥楠炲秶绱撻崒姘偓鐑芥⒔瀹ュ鍨傜憸鐗堝笒閸戠姵绻涢幋鐐寸殤缁炬儳銈搁弻锝呂熼悡搴″闂佺粯绻嶆禍婊嗗絹闂佹悶鍎滃鍫濇儓濠电姷顣介埀顒€纾崺锝団偓瑙勬礃鐢帡锝炲┑瀣垫晝闁靛繆鏅滈ˉ锟犳⒒閸屾艾鈧悂宕愰幖浣哥９濡炲娴烽惌鍡椕归敐鍛喐闁哄棴闄勯妵鍕箳閸℃ぞ澹曢梺缁樻尪閸婃牠濡甸崟顖氱闁告鍋熸禒濂告⒑閽樺鏆熼柛鐘崇墵瀵濡搁埡鍌氫簻闂佸憡绻傜€氬懘濮€閵堝棛鍘介梺褰掑亰閸撱劑鐓鍕厸閻忕偟鏅牎濠电偟鈷堟禍顏堝箖瑜斿畷濂割敃閿濆倹鐎抽梻鍌氬€烽懗鍫曞箠閹炬椿鏁嬫い鎾卞灩缁€鍌涗繆椤栨瑨顒熸繛鍏肩墵閺岋綁骞嬮悘娲讳邯椤㈡碍娼忛妸褏顔曢梺绯曞墲閿氶柣蹇婃櫇閹噣鏁傞崜褏锛濋梺绋挎湰閻熴劑宕楃仦瑙ｆ斀妞ゆ梻鍋撻弳顒勬煙椤斻劌娲ら崡铏亜椤愵偄鏋ょ紒瀣箻濡懘顢曢姀鈥愁槱闂佺懓鍢查鍛弲濡炪倕绻愮粔鐢稿疾濠婂牊鈷戦柛娑橈攻婢跺嫰鏌涘鈧粻鏍ь嚕閾忣偄顕遍悗娑欘焽閸樹粙姊虹紒妯荤叆闁硅姤绮撻幆灞剧節閸愵亞顔曢梺鍦檸閸ｎ喖螞閹达附鐓曢柟鐑樻尭缁椦囨煃瑜滈崜銊х礊閸℃稑绀傛慨妞诲亾鐎规洘鍨块獮妯肩磼濡粯鐝抽梺纭呭亹鐞涖儵宕滃┑瀣€剁€广儱顦伴埛鎴犵磽娴ｈ偂鎴犱焊閻楀牏绠鹃柤纰卞墮閺嬫稒顨ラ悙鎻掓殭閾绘牠鏌涘☉鍗炴灍婵炲懏绮撻弻鐔兼偂鎼达絾鎲肩紓浣筋嚙鐎氫即骞嗛崟顒佸劅闁宠棄妫欑€靛矂姊洪棃娑氬闁瑰啿绻掔划瀣偓锝庡枟閻撴洘绻涢崱妤冪闁哄棴绲块埀顒侇問閸犳牠鈥﹂悜钘夌畺闁靛繈鍊曠粈鍌炴煕韫囨洖甯堕柛鏃€甯楁穱濠囨倷椤忓嫧鍋撻弽顓炵闁硅揪绠戠壕褰掓煛瀹ュ骸骞栭梻鍌ゅ灡閵囧嫰寮介顫勃闂佹娊鏀遍崹鍨潖婵犳艾閱囬柣鏃囥€€婵洦绻濋姀锝嗙【閻庢矮鍗冲璇测槈閵忕姷鐫勯梺閫炲苯澧撮柟顔惧厴閸╋繝宕ㄩ闂寸钵婵＄偑鍊栧ú宥夊磻閹炬惌娈介柣鎰綑缁楁帡鎽堕弽顓熺厓鐟滄粓宕滃☉姘灊濠电姵纰嶉弲鎻掝熆鐠轰警鍎戦柛妯挎閳规垿鍩ラ崱妤冧哗闂佽绻戠换鍫濈暦閵夆晛鎹舵い鎾寸☉娴滈箖鎮峰▎蹇擃仾缂佲偓閸愵亞纾兼い鏃囧Г鐏忣厽銇勯銏㈢缂佺粯绻傞～婵嬵敆閸岋妇搴婂┑鐘垫暩閸嬫稑螞濞嗘挸鏄ラ柛顐ｆ儕閿濆鏁嬮柍褜鍓欓～蹇撁洪鍕炊闂侀潧顦崕鏌ユ倵鐠囨祴鏀介柣鎰仯閳ь剙顑囬幑銏犫攽鐎ｎ偄浠掑銈嗘磵閸嬫挾鈧鍠曠划娆撱€佸Ο娆炬Ъ闂佸搫鎳忕换鍫濐潖濞差亜绠伴幖娣灮閿涙洟姊虹粙娆惧剱闁规悂绠栭幆鈧い蹇撶墕缁€鍫㈡喐鎼淬劌鍚归柍褜鍓熷铏光偓鍦濞兼劙鏌涢妸銉﹀仴妤犵偛鍟撮崺锟犲礃閿濆懍澹曢梺闈╁瘜閸樼厧鐡俊鐐€戦崕鑼崲閸繍娼栭柧蹇撴贡绾惧吋淇婇婵愬殭闁汇劍鍨垮铏圭矙濞嗘儳鍓遍梺鍦嚀濞层倝锝炶箛鏇犵＜婵☆垵顕ч鎾绘⒑閸涘﹦鈽夐柨鏇樺劦瀹曟洟骞橀弬銉︽杸闂佺粯鍔樼亸娆忥耿閹绢喗鐓曢柕濞垮妽椤ュ鏌ｉ敐鍥у幋闁诡喚鍏橀獮濠冪節閸愨斂浠㈠銈冨灪濡啫鐣烽妸鈺婃晣婵犻潧鐗婂▓顐︽⒒閸屾艾鈧绮堟笟鈧獮鏍敃閳锋碍妞芥慨鈧柕鍫濇噹閻庮厼鈹戦悙鍙夆枙濞存粍绻堝畷鎴﹀磼閻愰潧褰勯梺鎼炲劘閸斿秶浜搁妸鈺傜厸闁逞屽墯缁傛帞鈧綆鍋嗛崢钘夆攽閳藉棗鐏犻柣蹇旂箞閹啴鎼归崷顓狅紲闂佺粯锚閸熷潡鍩㈤弴銏＄厸閻忕偛澧藉ú瀛橆殽閻愭潙娴鐐搭焽閳ь剛鏁搁…鍫ュ吹閹烘鈷掑ù锝呮憸閺嬪啯銇勯銏╂█鐎规洖缍婂畷绋款渻鐏忔牕浜惧ù锝囩《閺嬪酣鏌熼悙顒佺稇濞存粍顨婇弻鐔兼偂鎼达絾鎲奸梺鎸庤壘闇夋繝濠傚閸斻倝鏌嶇憴鍕伌闁诡喒鏅濋埀顒€婀辨慨鎾夊┑瀣拺缂備焦锚缁楁帡鏌ｈ箛鏂垮摵濠碉紕鏁诲畷鐔碱敍濮橀硸鍞洪柣搴＄畭閸庡崬煤閳哄啰鐜绘俊銈呮噺閳锋垿鏌涘┑鍕姎闁哄娴风槐鎺旂磼濮楀牐鈧法鈧鍠涢褔鍩ユ径鎰潊闁炽儱鍘栧Ч妤呮⒒娴ｅ憡鍟為柛鏃€鐗為妵鎰板礃椤旇偐顔戦梺姹囧灩閹诧繝宕愰崹顐ょ闁割偅绻勬禒銏＄箾閸涱噯鑰块柡灞剧〒閳ь剨缍嗘禍婵嬪闯娴犲鐓欐鐐茬仢閻忊晠鏌嶇憴鍕伌鐎规洟浜堕崺锟犲磼濮橆剙甯繝纰夌磿閸嬫垿宕愰弽顐ｆ殰濠电姴娲﹂崐鍧楁煥閺囨俺顔夐柛娆嶅灲濮婂宕掑顑藉亾閹间礁纾瑰瀣椤愯姤鎱ㄥΟ鎸庣【闁绘帒鐏氶妵鍕箳閹存績鍋撻崨濠勵浄婵犲﹤鐗婇悡鐘崇箾閼奸鍤欓柣蹇ョ節閺岋繝宕ㄩ鐘茬厽濡炪們鍨洪惄顖炲箖濞嗘垟鍋撻悽娈跨劸閻㈩垶绠栧缁樻媴鐟欏嫬浠╅梺绋垮缁挸鐣峰鈧畷锝夊Ψ瑜忛敍鐐寸節瀵伴攱婢橀埀顒侇殕閹便劑鎮滈挊澶岋紱闂佺粯鍔曢悘姘跺汲濠婂牊鐓ラ柣鏂挎惈鍟搁悗瑙勬尫缁舵岸骞冨Δ鍛櫜閹煎瓨绻勯幐澶愭⒑鐞涒€充壕婵炲濮撮鍡涙偂濞嗘挻鈷戞い鎾卞妿缁辨壆绱掗妸銉ｅ仮闁哄本绋撻埀顒婄秵娴滄繈宕抽悾宀€纾奸弶鍫涘妽瀹曞瞼鈧娲樼敮鎺楀煝鎼淬劌绠抽柟瀛樼箓閼垫劙姊婚崒娆戝妽闁稿骸纾幑銏ゅ箛閻楀牏鍘愰梺鎸庣箓閹虫劙寮抽敃鍌涚厪闊洤顑呴埀顒佹礈缁鎮烽幊濠傜秺閺佹劙宕ㄩ钘夋瀾闂備焦瀵х粙鎺楁儎椤栨凹娼栨繛宸簼閸嬶繝鏌℃径濠勬皑闁圭鍟扮槐鎾寸瑹閸パ勭彯闂佹悶鍔岄悥鐓庣暦閸濆嫧妲堥柕蹇曞Х椤斿﹪姊洪崷顓炰缓闁告柨鐬肩槐鐐寸節閸パ勭€梺鍦濠㈡﹢鎮欐繝鍥ㄧ厪濠电偛鐏濋崝婊堟煟閿濆骸澧ǎ鍥э躬閹瑩顢旈崟銊ヤ壕闁哄稁鐏愰崫鍕庣喖鎮℃惔锛勪喊闂佺澹堥幓顏嗗緤妤ｅ喛缍栭柡鍥ュ灪閻撴瑩鏌ｉ幋鐐嗘垿鎮″☉銏＄厱閻庯綆鍋呭畷宀勬煛娴ｇ懓濮堥柟顖涙閸ㄩ箖鎳犻鍌涙櫒闂傚倸鍊峰ù鍥敋瑜忛幑銏ゅ幢濞戞鏌ч梺缁橆焾椤曆囨嫅閻旇　鍋撻獮鍨姎闁绘绮岄‖濠囧Ω閳哄倵鎷洪梺鍛婄☉閿曘儳浜搁幍顔瑰亾閸忓浜剧紓浣割儓濞夋洟寮抽敂鐣岀闁糕剝锚缁旀儳霉濠婂啰绉洪柡宀€鍠栭幃婊兾熼搹閫涙偅闂備胶绮幐濠氬垂閸噮娼栨繛宸簻瀹告繂鈹戦悩鎻掆偓姝岊杺闂傚倷绀侀幗婊勬叏閻㈠憡鍋嬫繝濠傛噹閸ㄦ繂鈹戦悩瀹犲闁告劏鍋撴俊鐐€ら崜锕傚礈濮橆儵娑㈠礃椤斿吋鐎梺鍦濠㈡ê顔忓┑鍥ヤ簻闁规崘娉涢弸鎴炪亜閺傛妯€婵﹦绮幏鍛存惞閻熸壆顐奸梺姹囧焺閸ㄦ娊宕伴弽褏鏆﹂柟杈剧畱缁犳盯鏌℃径搴㈢《闁告棑绠戦—鍐Χ閸℃娼戦梺绋款儐閹稿墽妲愰幒妤佸亹闁肩⒈鍎疯閳ь剝顫夊ú妯好洪悢椋庢殾闁跨喓濮甸崐椋庘偓骞垮劚濡盯鍩ユ径鎰厓闁芥ê顦藉Ο鈧繝娈垮枓閸嬫捇姊虹紒妯曟垼銇愰崘鈺冾洸閻犻缚銆€閺€浠嬫煟閹邦剚鈻曢柛銈囧枎閳规垿顢欓懞銉ュ攭濡炪們鍨洪悧鐘茬暦閸楃偐妲堟俊顖滃帶楠炲牓姊绘担鐑樺殌妞ゆ洦鍘介幈銊╂偨缁嬭法鐛ラ梺瑙勫婢ф鎮￠悢闀愮箚闁靛牆鍊告禍楣冩⒑缂佹﹩娈旀俊顐ｇ〒閸掓帡顢橀姀鐘殿唺闂佸湱鍋ㄩ崝搴ㄥ箠閹剧儵鈧箓濡搁埡浣哄姦濡炪倖甯掔€氼剛娑甸埀顒勬⒑鐟欏嫬鍔舵俊顐㈠閹锋垿鎮㈤崫銉ь啎闂佺懓鐡ㄩ悷銉╂倶閳哄啰纾奸柣妯烘▕閻撳ジ鏌熼绛嬫疁婵☆偄鍟埥澶娾枎韫囨梹鐣奸梻鍌欑閹诧紕鏁Δ鍛剮妞ゆ牗鍑瑰鏍煣韫囨凹娼愰悗姘哺閺屽秹濡烽妸锔惧涧闂佺粯绻冪换鍕閹惧瓨濯撮柛婵嗗珔閿濆鐓熸俊銈呭暙閳诲牆鈹戦垾宕囨憼闁瑰嘲鎳樺畷婊堝矗婢跺﹦绱﹂梻鍌欑窔閳ь剛鍋涢懟顖涙櫠椤栫偞鐓欏〒姘仢婵倿鏌涢埞鎯т壕婵＄偑鍊栫敮鎺斺偓姘煎弮閹繝濡烽敂鍓ь啎闂佺懓顕导婵嬵敂閸偅鏅滈梺鍐叉惈閹冲繘宕?"
                "\n\n"
                "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棗鏆欏┑鈥炽偢閺屽秷顧侀柛鎾存皑閹广垽宕煎┑鎰婵犵數濮甸懝楣冨础閹惰姤鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú鐔奉潖閾忓湱纾兼俊顖氭惈琚濋梻浣告啞閹歌鐣濋幖浣哥畺闁汇垻顭堢猾宥夋煕椤愩倕鏆遍柟閿嬫そ濮婅櫣娑甸崨顓濇睏闂佺顑嗙粙鎺撶┍婵犲啰闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛瀣閹剝绺介崨濠勫幈闂佸疇顫夐崕铏閻愵兛绻嗛柣鎰典簻閳ь剚鐗滈弫顕€骞掑Δ鈧粣妤佹叏濮楀棗澧婚柣鎺嶇矙閺岀喖鏌囬敃鈧獮妯肩磼閻樿崵鐣洪柡灞剧☉閳诲氦绠涢敐鍠般劍绻濋埛鈧仦濂稿仐闂佽鍣换婵囦繆閼搁潧绶為悗锝庡墮瀵娊姊绘担鍛婃儓婵炲眰鍔戝畷鎴濃槈濞嗘埈娲搁梺瑙勵問閸犳氨澹曢悾灞稿亾楠炲灝鍔氭俊顐ｇ⊕閺呭爼鎮介崨濠勫幐閻庡厜鍋撻悗锝庡墰閻﹀牓鎮楃憴鍕闁绘牕銈稿畷娲晸閻樿尙鍔﹀銈嗗笒閸婂綊锝為弴鐘亾鐟欏嫭绀€婵炶绠撳畷浼村箛閻楀牏鍘藉┑掳鍊愰崑鎾绘煟濡も偓濡稓鍒掗銏犵闁哄啫鍊婚敍婊堟⒑闁偛鑻晶瀵糕偓瑙勬礃鐢繝骞冨▎鎴斿亾閻㈡鐒炬鐐茬墦濮婄粯绻濇惔鈥茬盎濠电偠顕滅粻鎾诲箠濠靛鍊锋い鎺戝亞濞叉悂姊洪棃鈺佺槣闁告ê澧芥竟鏇熺附閸涘﹤鈧敻鏌ㄥ┑鍡欏嚬缂併劏鍋愰埀顒傛嚀閹诧紕鎹㈤崟顓燁潟闁圭儤鎸荤紞鍥煏婵犲繒鐣遍梻澶婄Ч濮婃椽鎮烽弶鎸幮╅梺纭呮珪閿曘垽鎮伴鈧獮妯兼嫚閼碱剦鍞洪柣搴＄畭閸庨亶骞忕€ｎ€稑顭ㄩ崼鐔叉嫽闂佺鏈懝楣冨焵椤掑倸鍘撮柟铏殜瀹曞ジ寮村璇蹭壕闁挎洖鍊搁柋鍥煏婢舵稓鐣遍柛鎾瑰煐缁绘繈妫冨☉妯峰亾婵犳埃鈧箓宕奸姀鐙€妫滄繝鐢靛У绾板秹鎮￠悢鍏肩厵闂侇叏绠戦弸娑㈡煕閺傛鍎旈柡灞剧〒閳ь剨缍嗘禍婊堝焵椤掆偓濞尖€愁嚕婵犳碍鏅搁柣妯垮皺閸婄偤姊虹€圭姵銆冮柣鎺炵畵閹顢橀悢铏诡啎闁诲孩绋掗…鍥儗鐎ｎ剛纾兼い鏃囧Г瀹曞瞼鈧鍠栭…鐑藉箖閵忋倖鍋傞幖杈剧秮閻涙捇姊绘担绋款棌闁绘挸鐗撳畷鎶筋敋閳ь剙顕ｉ幎钘夘潊闁靛牆妫岄幏娲煟閻樺弶绀岄柍褜鍓濆▍鏇㈡倶閺囥垺鈷戠紒瀣儥閸庢劙鏌涢弮鈧〃鍛祫闂佸湱澧楀妯肩不閾忣偂绻嗛柕鍫濆椤︼箑霉濠婂啰绉烘慨濠冩そ楠炲棜顦崇紒鍌氼儔閺屾稓鈧綆浜滈顐㈩熆鐟欏嫭绀嬫鐐查叄閹崇偤濡烽姀鈥愁伖闂傚倷绀侀幉锛勬崲閸屾壕鍋撳鐓庢珝闁诡喚鍋熼幑鍕Ω瑜忛敍婵嬫倵楠炲灝鍔欑紒鈧担鍦洸闁告挆鍛紳闂佺鏈悷銊╁礂鐏炶В鏀芥い鏃傚亾閺嗩剟鏌熼姘伃妞ゃ垺绋戦～婵嬫偂鎼淬埄鍚欏┑锛勫亼閸婃牕煤瀹ュ纾婚柟鎯х亪閸嬫挾鎲撮崟顒傤槰闁汇埄鍨辩敮锟犳晲閻愭祴鏀介悗锝呯仛閺呫垽姊虹粙鎸庢拱缁炬澘绉归獮澶愬閵堝棌鎷婚梺绋挎湰閼归箖鍩€椤掍焦鍊愮€规洘鍔栭ˇ鐗堟償閿濆洨鍔跺┑鐐存尰閸╁啴宕戦幘鎼闁绘劕顕晶鍨亜閵忊剝绀嬮柡浣稿€块幐濠冨緞婵犲偆妫楀┑鐘垫暩婵即宕归悡搴樻灃婵炴垯鍨圭€氬銇勯幒鍡椾壕闂佷紮绲块崗妯虹暦閿濆棗绶炵€光偓閳ь剟鎯侀崼銉︹拻闁稿本姘ㄦ晶娑氱磼鐎ｎ偄娴挊鐔兼煟濡偐甯涢柣鎾寸洴閺屾盯鍩ラ崱妤€绠婚梺浼欑悼閺佸寮婚垾宕囨殕闁逞屽墴瀹曚即寮介鐐电暫濠电姴锕ら崰姘焽閵娾晜鐓曢柍鈺佸枤閻掍粙鏌￠崱鎰姦婵﹥妞介獮鏍倷閹绘帒顫氶梻浣告贡椤牓宕崸妤嬬稏闊洦鎷嬪ú顏嶆晜闁告洦鍋嗛悰鈺佲攽閻樺灚鏆╁┑顔藉▕閹虫宕滄担鐟板簥婵炴挻鍩冮崑鎾存叏婵犲啯銇濈€规洏鍔嶇换婵婄疀濮橈絽浜鹃悹鎭掑妿绾惧ジ鏌ｅΟ铏癸紞濠⒀屼邯閺岋綁鏁愰崶褍骞嬪銈冨灪濞茬喖宕哄Δ鍛殟闁靛瀵屽Λ鍐倵鐟欏嫭绀冮柨鏇樺灲閵嗕線寮崼婵嗚€垮銈嗘尵婵炩偓婵☆偆鍏樺濠氬磼濮橆兘鍋撻悜鑺ュ殑闁割偅娲嶉埀顒婄畵瀹曞ジ濡烽妷銉у綁婵＄偑鍊栫敮鎺斺偓姘煎弮瀹曟垿鏁撻悩宕囧帾婵犵數鍋熼崑鎾斥枍閸涱垳纾奸柍褜鍓熷畷鎺戔攦閹傚闂佺绻愰ˇ顖涚妤ｅ啯鈷戦梺顐ゅ仜閼活垱鏅堕悧鍫滅箚闁告瑥顦慨宥嗩殽閻愭潙绗掗摶鏍р攽閻樻彃鏆炴繛鍛濮婄粯鎷呴崨濠傛殘婵炴挻纰嶉〃濠傜暦閵忋倖鍊锋い鎺戝亞濞村嫰姊鸿ぐ鎺擄紵闁绘帪绠撻崺娑㈠箣閿旇棄浠梺鎼炲劵缁叉椽宕戦幘缁樻優妞ゆ劧缍嗛崬鏌ユ⒒閸屾瑨鍏屾い顓炵墢閹广垽骞掑Δ鈧壕濠氭煙閻愵剛绐炴繛鎴欏灩缁€鍐┿亜閺傚灝鎮戞俊宸墴濮婃椽鏌呴悙鑼跺濠⒀屽灦閺屾洟宕惰椤忣厽顨ラ悙鏉戞诞妤犵偛顑呴埞鎴﹀箛椤忓拋娼熼梻鍌氬€风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼宕滆绾惧ジ鏌ｅΟ鎸庣彧閻忓浚鍙冮弻锝夋晲閸パ冨箣閻庤娲栭妶绋款嚕閹绢喖惟闁挎棁濮ら悵婊勭節閻㈤潧袨闁搞劎鍘ч埢鏂库槈閵忊晜鏅為梺绯曞墲閵囨盯寮稿澶嬬厱闁斥晛鍟伴埊鏇㈡煃闁垮绗掗棁澶愭煥濠靛棙绁╅柣鎺斿亾閵囧嫰濡烽妷褏顔掗梺鍝勬湰缁嬫捇鍩€椤掑﹦绉甸柛瀣闇夋い鏃堟暜閸嬫挾鎲撮崟顒傤槰闂佹悶鍔岄悘婵嬫偩閻戣棄惟闁宠桨鑳舵鍥⒑閻熼偊鍤熷┑顔炬暬閹繝鏁愭径瀣ф嫽婵炶揪绲介幗婊堝几閸愨晙绻嗘俊鐐靛帶婵″潡鏌熷畡閭﹀剶鐎殿喖顭锋俊鐑藉Ψ瑜嶉幗瀣攽閻愬樊鍤熷┑顔芥尦椤㈡牠宕卞☉娆忎簵闂佺粯鏌ㄩ崥瀣偂濞嗘挻鈷戞い鎾卞妿閻ｅ崬顭胯閸犳氨妲愰幒妤佸亼婵炲棗绻愰銉ッ瑰鍕煉闁哄本娲樼粩鐔碱敍濮橆剚娈ㄥ┑鈥冲级閸旀瑥顫忓ú顏勪紶闁告洦鍓氶幏杈╃磽娴ｅ壊鍎愰悽顖ょ節閻涱噣宕卞☉妯肩潉闂佸壊鍋呯换鍕鐎ｎ喗鈷戦柟顖嗗嫮顩伴梺绋款儏閹虫﹢骞嗘笟鈧弫鎰緞鐎Ｑ勫濠电偠鎻徊浠嬪箺濠婂牊鏅€广儱娲ㄧ壕鍏笺亜閺囩偞鍣归柣蹇ラ檮椤ㄣ儵鎮欓弶鎴濐潚濡ょ姷鍋為悧妤呭箯閸涙潙浼犻柕澶堝劚缁犳娊姊绘担鐑樺殌闁告艾顑夐幃楣冾敂閸繄顦悗鍏夊亾闁逞屽墰閸掓帗绻濆顓炴闂侀潧鐗嗗ú銊╂晬濠婂喚娓婚柕鍫濇閳锋劖銇勯幋鐐垫噧妞ゎ厼娲獮鍥偋閸績鍋撻崹顐ｅ弿婵☆垰鎼弳鍗灻瑰鍐╄础缂佽鲸甯楀蹇涘Ω閿曗偓绾炬娊鎮楃憴鍕閻㈩垱甯￠崺銏℃償閵娿儳顓哄銈嗘尵閸熸ê顭ㄩ崟顏嗙畾闂佺粯鍔︽禍婊堝焵椤掍胶澧电€规洖缍婇幃浠嬪川婵犲倷缃曢梻浣虹《閸撴繄绮欓幋锔藉亗婵犻潧顑嗛悡娑㈡煕閹扳晛濡垮褎娲熼弻娑樜旀担绯曟灆闂佸搫鐭夌徊鍊熺亽闂佸憡绻傜€氼參宕愭惔锝囩＝濞达綀顕栧▓鏃€銇勯敂钘夘棆闁瑰箍鍨归埥澶婎潩閿濆懍澹曢梺姹囧灪椤旀牠鎮炴ィ鍐╁仺妞ゆ牗姘ㄩ崺锝夋煛瀹€瀣ɑ妤犵偛锕弻娑㈠籍閳ь剟宕归崸妤冨祦闁告劦鍠楅弲鎼佹煟濡搫鏆卞ù婊勭矒濮婂宕掑Δ鈧禍楣冩⒑瑜版帒浜伴柛鐘冲哺閹偓銈ｉ崘鈹炬嫽婵炴挻鍩冮崑鎾寸箾娴ｅ啿娲﹂崑瀣煕閳╁啰鈽夌痪鎯х秺閺屾稑鈽夊鍫濆濡炪倐鏅滈悡锟犲蓟閻旂⒈鏁嶉柛鈥崇箰娴滈箖姊虹悰鈥充壕婵炲濮撮鍡涙偂閸愵喗鐓㈡俊顖欒濡茶銇勯妷锔剧煀闂囧绻濇繝鍌氼伀缂佺姵顭囩槐鎺撴綇閵娿儳顑傞梺褰掝棑婵炩偓闁瑰磭濞€椤㈡鍩€椤掑嫬鐒婚柣銏犳啞閳锋垹绱撴担濮戣偐娆㈤柆宥嗙厱闁挎繂绻掗崚浼存煟閿濆懎妲绘い顐ｇ矒閸┾偓妞ゆ帒瀚弰銉╂煥閻斿搫孝缂佲偓閸愵喗鐓熼柟浼存涧婢т即鏌曢崼顐喊婵﹦绮幏鍛驳鐎ｎ亝顔勯梻浣告啞閸ㄥ綊寮查銏╁殫濠电姴鍟伴々鐑芥倵閿濆骸浜滈柍褜鍓濋崺鏍箞閵娿儙鐔煎箰鎼达絻鈧劙姊哄Ч鍥р偓妤呭磻閹捐埖宕叉繝闈涱儐椤ュ牊绻涢幋婵嗚埞闁告捇浜跺娲箮閼恒儲鏆犻梺鎼炲妼濞尖€愁嚕婵犳碍鍋勯柧蹇撴贡閻撴捇姊洪崷顓х劸閻庢稈鏅涢悾宄扮暦閸モ晝锛濇繛杈剧到閹碱偅鐗庨梻浣烘嚀閹芥粎鍒掗婊呯煔閺夊牄鍔庣弧鈧梺鎼炲劥閸╂牠寮插┑瀣拺闁圭娴风粻鎾绘倵濞戞帗娅婇柟顔藉閹峰懘宕滈崣澶婄槣闂備線娼ч悧鍡涘疮椤愶附鍊舵い蹇撶墛閻撴瑩鏌ｉ悢鍝勵暭闁哥姵锕㈤弻锝呪槈閸楃偞鐏堥柧浼欑秮閺屻倕霉鐎ｎ偅鐝栭梺鎸庣⊕缁矂鍩為幋锕€鐓￠柛鈩冾殘娴犳悂姊虹悰鈥充壕闁哄鐗冮弬渚€宕戦幘鎰佹僵闁告劘寮撳Ч妤冪磽娴ｄ粙鍝洪柟鐟版搐閻ｇ兘骞掗幋顓熷兊濡炪倖鍨煎Λ鍕妤ｅ啯鐓熼柟杈剧到琚氶梺绋匡工濞硷繝寮婚妸鈺佸嵆闁绘劖绁撮崑鎾诲箹娴ｇ懓浜楅梺缁樻煥閸氬鎮¤箛娑欑厱妞ゆ劧绲跨粻銉︿繆椤栨氨澧﹂柡灞稿墲閹峰懐绮欐惔鎾充壕闁秆勵殔閽冪喐绻涢幋娆忕労闁轰礁鍟撮弻銊モ攽閸℃ê绐涢梺浼欑到閵堢顫忓ú顏勪紶闁告洦鍠栭顓㈡⒑缂佹﹩娈曢柟鍛婃倐閿濈偠绠涘☉娆愬劒闂侀潻瀵岄崢楣冩偂鐎ｎ喗鈷戠紒顖涙礀婢у弶銇勯妸銉﹀殗妞ゃ垺姊婚埀顒佺⊕椤洨绮绘ィ鍐╃厱妞ゆ劧绲块埥澶愭煟韫囨梻鍙€闁?idea闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃闁硅櫕鎹囬垾鏃堝礃椤忎礁浜鹃柨婵嗙凹缁ㄧ粯銇勯幒瀣仾闁靛洤瀚伴獮鍥敍濮ｆ寧鎹囬弻鐔哥瑹閸喖顬堝銈庡亝缁挸鐣烽崡鐐嶆棃鍩€椤掑嫬鐓曢柟鐑橆殕閳锋垹绱撴担濮戭亞绮閺岋繝宕担闀愬枈濡ょ姷鍋涢ˇ杈╁垝濞嗗繆鏋庨柟顖嗗嫬鈧垶姊绘担绋款棌闁稿甯掗…鍧楀焵椤掑倻纾介柛鎰ㄦ櫆缁€瀣叏婵犲偆鐓肩€规洘甯掗埢搴ㄥ箣椤撶啘婊堟⒒娴ｅ憡璐￠柍宄扮墦瀹曟垶绻濋崒婊勬濡炪倖鐗滈崕鎰板极閸愵喗鐓ラ柡鍐ㄦ处椤ュ霉濠婂棝鍝虹紒缁樼箞閹粙妫冨ù韬插灪缁绘稓浠﹂崒姘ｅ亾濡や胶鐝堕柡鍤堕姹楅梺鍦劋閹搁箖宕㈤柆宥嗗仭婵犲﹤鍟撮崣鍕煏閸℃鏆ｇ€规洖宕埥澶娾枎韫囧海鏆楅梻鍌欑窔濞佳囁囬锕€鐤炬繝濠傜墛閸嬪倹绻涢幋娆忕仾闁绘挻娲熼弻鐔煎箥閾忣偅鐝旀繝纰樷偓宕囦虎妞ゎ叀鍎婚ˇ鎶芥煟閳哄﹤鐏︾€殿喖顭烽弫鎾绘偐閹绘帟鈧灝鈹戦埥鍡楃仴闁稿鍔欓幃鈩冨緞閹邦厸鎷洪梺鍛婄箓鐎氼厼锕㈤幍顔剧＜閻庯綆鍋呭畷宀勬煕閳规儳浜炬俊鐐€栫敮鎺楁晝閿斿墽鐭撻柣銏犳啞閻撴洟鎮楅敐搴濈凹闁革絽缍婇弻锝夋晲閸涱厽些闂佷紮绲剧换鍫ュ春閳ь剚銇勯幒鎴濐仼闁绘帒鐏氶妵鍕箳閹存繃鐏撳┑鐐插悑閸旀牜鎹㈠☉銏犵煑濠㈣泛鑻埛鍫㈢磽娴ｆ垝鍚柛瀣仧閹广垹鈹戠€ｎ亞鍊為梺闈涱槶閸ㄨ绂嶉幆褋鈧帒顫濋敐鍛闁诲孩顔栭崰妤呭箰閾忣偅鍙忛柍褜鍓熼弻锝呂熼懡銈呯仼闂佹悶鍎崝搴ㄥ储闁秵鈷戦梻鍫熶緱濡插爼鏌涢妸銉︽儓闁宠绉瑰畷銊р偓娑櫭禒鍝勵渻閵堝棛澧紒瀣灥闇夋い鏃囧Г閸欏繐鈹戦悩鎻掍簽闁绘捁鍋愰埀顒冾潐濞叉鏁幒妤€鐓濋幖娣妼缁犳娊鏌熺€涙绠撻柤鍨姍濮婂宕掑▎鎺戝帯濡炪們鍨归敃銈夊煝瀹ュ鍗抽柕蹇曞Х椤斿姊洪幖鐐插妧闁告侗鍠楅鏇㈡⒒娴ｅ憡鎯堥悶姘煎亰瀹曟洟鏌嗗鍡楃彅闂佺粯鏌ㄩ崥瀣偂韫囨搩鐔嗛悹楦挎婢ф洟鏌涢弬璇测偓婵嬪蓟閿濆围闁告侗鍠楅幃娆撴⒑鐎圭媭娼愰柛銊ユ健閵嗕礁鈻庨幇顓炲伎闂佸綊鍋婃禍鐐哄箲閺囥垺鈷掑ù锝勮閻掔偓銇勯幋婵囶棦妤犵偞鍔栫换婵嗩潩閵夈垹浜鹃柛鎰靛枛鍞梺鍐叉惈閸婃悂鍩€椤掑倸鍘撮柡宀€鍠撶槐鎺懳熼搹鍦嚃婵犵數鍋涢悧鍡涒€﹀畡閭︽綎闁惧繒鎳撶€垫煡鏌￠崶鈺佹瀾闁绘縿鍔庣槐鎾存媴閾忕懓绗＄紓浣筋嚙閸婂潡骞冩ィ鍐╁€婚柦妯猴級閳哄懏鐓冮柛婵嗗閺€濠氭煛閸滃啰绉慨濠呮缁辨帒螣閸濆嫷娼曟俊鐐€х徊鑲╁垝濞嗗繒鏆﹂柟杈剧畱缁犵粯绻涢懠顒傚笡闁哄拑缍佸铏圭磼濡櫣浠村┑鈽嗗亝閻熝囧焵椤掑嫭娑ч柣顓炲€搁～蹇撁洪鍜佹濠电偞鍨堕懝楣冦€傞崫鍕ㄦ斀闁宠棄妫楁禍婵囥亜閵娿儲顥㈡鐐茬墦婵℃悂鍩℃担鐚寸床闂備胶绮崝鏇㈩敋椤撱垹鍌ㄩ弶鍫涘妿缁♀偓闂佹眹鍨藉褍鐡梻浣告憸閸犳挻鏅跺Δ鍛柧闁割偅娲﹂弫鍌炴煕椤愩倕鏋旈柛妯绘尵缁辨捇宕掑▎鎴濆闁藉啳浜埀顒冾潐濞叉牠寮甸鍕┾偓鍐Ψ閳哄倸鈧兘鎮楅悽娈跨劸妞ゎ値鍥ㄢ拺闁荤喐婢樺Σ濠氭煙閾忣個顏堟偩瀹勬嫈鏃€鎷呴崫銉х嵁闂佽鍑界紞鍡樼閼搁潧顕辨繝濠傚暊閺€浠嬫煟濡櫣浠涢柡鍡忔櫅閳规垿顢欓幆褍骞嬮悗娈垮櫘閸嬪﹤鐣烽妸锔剧瘈闁告劑鍔屾导搴ㄦ⒑鐠囨彃顒㈢紒瀣浮閺佸啴鍩℃担鍙夌亖婵炲濮撮鍡涙偂閺囩喓绠鹃柟瀵稿剳閸忣剟鏌涢弮鍌氭瀾闁靛洤瀚伴崺鈩冩媴閸濄儵鐛撶紓鍌欒兌缁垳鎹㈤崘顏呭床婵犻潧顑呯壕鍏兼叏濮椻偓濡法妲愰幋鐘电＝闁稿本鐟ㄩ崗灞解攽閻愨晛浜剧紓鍌欒兌婵敻鎮ч悩鑽ゅ祦闁告劦鐓堝銊╂煃瑜滈崜鐔肩嵁閸愩劉鏋庨柟鎯х－椤斿矂姊洪悷鐗堟儓婵☆偅顨嗙粋宥嗐偅閸愨晝鍘甸梻鍌氬€搁顓⑺囬敃鍌涚厽闁圭儤鍨规禒娑㈡煏閸パ冾伃妤犵偞甯掗濂稿醇濠靛棗鑵愮紓鍌氬€烽懗鑸垫叏閻㈢绠查柛銉墮閽冪喖鏌ㄥ┑鍡╂Ч闁哄懏鐓￠弻娑㈠Ψ閹存繂鏆欑紒鐙呯稻娣囧﹪鎮欓鍕ㄥ亾閹达箑鍨傛繛宸簼閸庡孩銇勯弽顐粶缂佺姵鐗楃换婵囩節閸屾粌顣哄Δ鐘靛亼閸ㄧ儤绌辨繝鍥舵晬婵犲﹤鎳庣粭锟犳⒑缂佹绠ラ柛瀣工椤繑绻濆顒傦紲濠电偛妫欑敮鎺楀储閿涘嫮纾藉〒姘搐濞呮﹢鏌涢妸銊︾【闁伙絽鍢查埞鎴﹀窗椤旀儳鏋涙慨濠呭吹閳ь剛鏁搁…鍫熸櫠閻愵剛绡€闁汇垽娼ф禒婊勪繆椤愶絿鎳囨鐐茬箻瀵濡烽妷褍鈧偛顪冮妶鍡楃瑨妞わ缚鍗冲鏌ユ晲婢跺鎷虹紓鍌欑劍钃辨い銉ユ缁绘盯宕崘顏喰滃銈冨灪閻熲晛顕ｉ幘顔碱潊闁抽敮鍋撻柟閿嬫そ濮婃椽宕ㄦ繝鍕暤闁诲孩鑹鹃崲鎻掑祫閻熸粎澧楃敮妤呮偂閺囥垺鐓忓┑鐐戝啫顏慨锝呯墕铻栭柣姗€娼ф禒婊堟煕閻斿憡灏﹂柣娑卞枤閳ь剨缍嗛崰妤呭磹閻戣姤鐓熼柕蹇婃閸熷繘鏌涢悢鐑藉弰婵﹦绮幏鍛瑹椤栨粌濮肩紓鍌欒兌缁垶銆冩繝鍌滄殾闁硅揪绠戠粻娑㈡煛婢跺孩纭堕柣銈呮喘濮婃椽宕ㄦ繝浣虹箒闂佹悶鍔岀壕顓熺珶閺囩喓闄勭紒瀣硶妤犲洭姊洪崜鎻掍簼缂佸鍨舵穱濠囧礂閼测晝顔曢梺鍦拡閸樼厧鈻嶅澶嬬厸閻忕偛澧藉ú鎾煕閳哄纾块柍褜鍓ㄧ紞鍡涘礈濞戙垺鍎婇柛顐犲劜閸婄敻鎮峰▎蹇擃仾缁剧偓鎮傞弻娑㈠籍閳ь剟宕归崸妤€违濞达絿纭堕弸搴ㄦ煙閹咃紞闁伙綁绠栭幃宄邦煥閸愵€倗绱掗纰辩吋闁诡喗鐟╅幃婊兾熼柨瀣伜闂傚倷鑳堕…鍫ュ嫉椤掑嫭鍋＄憸鏂跨暦濠靛棭鍚嬪璺侯儏閳ь剛鏁哥槐鎺懳旀担琛℃闂佸憡纰嶉敋闁宠棄顦埢搴ㄥ箣閻樺啿娈為梻鍌欑窔閳ь剛鍋涢懟顖涙櫠閹绢喗鐓忛柛鈩冩礈椤︼附銇勯锝囩疄妤犵偛娲﹂幏鍛村礂婢跺鈧悂姊婚崒姘偓鐑芥嚄閸撲礁鍨濇い鏍ㄧ〒閻熻淇婇妶鍛櫣闂傚偆鍨堕弻銊モ攽閸℃ê顎涢梺鎼炲€栧ú鏍箒闂佺粯锚濡﹪宕曞☉銏＄厸濞达絿顭堥弳锝夋煛鐏炵偓绀嬬€规洜鍘ч埞鎴﹀炊閳瑰灝浜界紓鍌氬€峰ù鍥ㄣ仈閹间焦鍋傞柍銉﹀墯濞兼牜绱撴担鑲℃垶鍒婇幘顔界叄闊洦娲橀崵鈧紓浣诡殣缁绘繂顫忓ú顏勭閹兼番鍨诲▓銈夋⒑濮瑰洤鍔村ù婊呭仧濡叉劙骞掑Δ鈧～鍛存煟濡灝鐨烘い鏃€鍔欏铏圭磼濡钄奸梺绋匡攻缁诲牆顕ｆ繝姘亜闁惧繐婀遍敍婊堟⒑闂堟稓绠冲┑顔炬暬閹ê顓兼径瀣ф嫼缂傚倷鐒﹁摫閻忓繑澹嗙槐鎺斺偓锝庡亝瀹曞矂鏌涢埞鎯т壕婵＄偑鍊栧濠氬磻閹剧粯鐓曟俊顖濆吹閻帞鈧娲橀崹鍧楃嵁濡偐纾兼俊顖濄€€閸嬫捇鎮介崨濠勫弳濠电娀娼уΛ婵嬵敁濡も偓椤儻顦遍柛妤佸▕瀵鏁愭径瀣珖闂侀€炲苯澧撮柟顔ㄥ洤绠婚悹鍥皺閻ｅ搫鈹戞幊閸婃洟宕鐐茬獥闁糕剝绋掗悡鏇㈡煛閸ャ儱濡煎褏澧楅妵鍕晜鐠囨彃绫嶅┑顔硷攻濡炶棄鐣烽妸锔剧瘈閹艰揪绲芥慨鎼佹⒒娴ｈ鍋犻柛搴㈢矒瀹曘劑顢橀悙娈垮悈闂傚倸鍊搁崐鐑芥嚄閸洏鈧焦绻濋崶褏顔屽銈呯箰濡稒绋夊澶嬬厵閻庣數顭堝暩婵炴垶鎸哥粔鐢垫崲濞戙垹绠ｉ柣鎰仛閸ｏ絾绻涚€涙鐭嬬紒顔芥崌瀵鎮㈤悡搴ｇ暰閻熸粍绮撳畷鐢告偄閸忚偐鍘撳銈嗙墬缁嬫帞绮堢€ｎ喗鐓涚€光偓鐎ｎ剛蓱闂佽鍨遍弻銊╁煘閹达箑骞㈡俊銈呭暔閸嬫牕鈹戦悩鎰佸晱闁哥姵鐗犻弫鍐Χ婢跺棌鍋撻敃鈧悾锟犲箥椤旇姤顔曢梻浣告贡閸庛倝宕归悢鐓庡嚑閹兼番鍔嶉悡娆撴倵閻㈡鐒鹃崯鎼佹倵鐟欏嫭绀€鐎殿喖澧庨幑銏犫攽鐎ｎ偄浠洪梻鍌氱墛缁嬫劗鍒掕濮婃椽宕ㄦ繝鍕拡婵犵數鍋愰崑鎾绘倵鐟欏嫭绀冩い銊ワ躬楠炲啫鈻庨幙鍐╂櫌闂佺鏈〃鍡涳綖瀹ュ鈷戦柛鎾楀懎绗￠梺缁橆殘婵炩偓鐎殿喛顕ч埥澶愬閻樼數鏉搁梻浣侯焾缁绘劙骞楀鍫濇瀬闁哄稁鍘介埛鎴犵磽娴ｈ偂鎴犱焊椤撶喆浜滈柟瀛樼箥濡偓濡ょ姷鍋涢崯顐︽偩閿熺姵鐒介柨鏃€鍎冲鎶芥⒒娴ｅ憡鍟炲〒姘殜瀹曪絾鎯旈妸銉﹁緢濡炪倖鎸堕崹娲偂閻斿吋鐓忛煫鍥э攻濞呭懘鏌ｈ箛銉х瘈闁诡喕绮欓、娑橆煥閸愌勫煕闂備礁鎲＄敮妤冩暜閻愬搫绠柣妯烘▕閸熷懏銇勯弮鍥棄闁稿繐锕缁樻媴閸濆嫬浠橀梺纭呭Г缁挸顕ｉ锕€绠瑰ù锝囶焾閸嬪秹姊绘笟鍥у缂佸鏁婚崺娑㈠箣閿旂晫鍘卞┑鐘绘涧濡顢旈鍫熺厱閻忕偠顕ф慨鍌炴煛鐏炲墽娲寸€殿噮鍓涢幑鍕Ω瑜嶆慨閬嶆⒒娴ｇ瓔鍤冮柛鐘愁殜閺佸啴濮€閵堝懓鎽曢梺绯曞墲椤ㄥ繘宕ョ€ｎ喗鐓曢柍鈺佸暟閹冲啯顨ラ悙鏉戝闁宠鍨块幃娆撴嚋闂堟稒閿紓鍌氬€哥粔宕囩矆娓氣偓閳ワ箓宕堕妸褏鐦堝┑顔矫畷顒冦亹閸℃娓婚柕鍫濇缁楁帡鎮楀鐓庡籍闁诡喒鈧枼鏋庨柟鎵虫櫃缁ㄥ姊洪崫鍕殜闁稿鎹囬幃妤冪箔濞戞ɑ鍣洪柛蹇旂矊铻栭柨婵嗘噹閺嗙偤鏌ｉ幘鍐叉殻闁哄矉绠戣灒濞撴凹鍨遍埢鎾斥攽閳藉棗鐏欓柛瀣尰娣囧﹪濡堕崶顬儵鏌涚€ｎ剙浠ч柡渚囧櫍閸ㄦ儳鐣烽崶銊︻啎闂備礁鎲￠〃鍫ュ磿閹邦兙鈧帗绻濆顓犲幍濡炪倖鐗曞Λ妤呭嫉椤掑媻澶愭晸閻樻枼鎷婚梺绋挎湰閼归箖鍩€椤掑倸鍘撮柟铏殜瀹曞ジ寮村璇蹭壕闁挎洖鍊搁柋鍥煏韫囧ň鍋撻崘鑼搸闂傚倷绀佸﹢杈ㄦ櫠濡も偓椤灝螣閼测晙绗夐梺缁橆焾椤曆呯不鐟欏嫮绠鹃柨婵嗛婢ь喖顭块悷鏉库偓鎼佲€︾捄銊﹀磯濞撴凹鍨抽崣鏇炩攽閻愯尙姣為柡鍛矒婵＄敻宕熼姘鳖吅闂佹寧绻傞幉娑㈠箻缂佹鍘搁梺绋挎湰椤ㄥ懏绂嶆ィ鍐┾拻闁稿本鑹鹃埀顒傚厴閹虫宕滄担绋跨亰濡炪倖鐗滈崑娑氱矆婢跺鍙忔俊鐐额嚙娴滈箖鎮楃憴鍕婵＄偠妫勯锝嗙鐎ｅ灚鏅為梺鍛婄懀閸庢煡鎯堣箛娑欑厽闁绘柨鎽滈惌濠勭磼缂佹ê绗掗崡閬嶆煙閻楀牊绶茬紒鐘烘珪娣囧﹪濡堕崒姘缂傚倷鑳舵慨鐑藉极婵犳艾钃熼柣鏂垮悑閸婄粯淇婇婵愬殭缁炬澘绉电换娑氣偓鐢殿焾鏍￠梺鍦焾閸熷潡锝炶箛娑欐優閻熸瑥瀚悵浼存⒑閻愯棄鍔ユ繛鍛礋閹ê顓奸崨顏呮杸闂佹寧绋戠€氼剚绂掗埡鍌欑箚妞ゆ劑鍨归顓熴亜閵忊€冲摵闁轰焦鍔栧鍕熺紒妯荤彣闂傚倷绶氶埀顒傚仜閼活垱鏅堕鈧弻锝夋晲閸パ冨箣闂佽鍠掗崜婵嬪箚閺傝鐔虹磼濡粯绶┑鐘垫暩婵兘寮崨濠冨弿闁圭虎鍠栫壕鐟扳攽閻樺疇澹橀柛灞诲姂閺岀喓绱掗姀鐘崇亶闂佹娊鏀辩敮鎺楁箒闂佹寧绻傞悧濠囁夋径鎰厱婵﹩鍓涚粔娲煛鐏炲墽娲撮柟顔规櫊瀹曟﹢骞撻幒婵囩稈闂傚倷娴囬鏍窗濮樿泛绀傛俊顖濐唺缁诲棝鏌ｉ妶搴＄伇婵¤尙鍏樺铏圭矙濞嗘儳鍓遍梺鐟版啞閹倿鏁愰悙娴嬫斀閻庯綆鍋勬禍妤呮煙閸忚偐鏆橀柛銊х帛缁傚秹宕滆绾句粙鏌涚仦鍓ф噮閻犳劒鍗抽弻娑㈡偐閾忣偆娈ら梺鍛婂笚鐢繝銆佸☉銏″€烽柛娆忓€戦崶銊у弳濠电娀娼уΛ顓炍ｉ崫銉х＜闁逞屽墴瀹曟﹢顢欓悾灞藉笚闂備礁鎲＄换鍌溾偓姘煎墴瀵啿鈻庨幇鍨啍闂佺粯鍔樼亸娆愭櫏婵犳鍠栭敃锔惧垝椤栫偛绠柛娑卞枤閻熻銇勯弽銊р姇闁哄棛鍋炴穱濠囨倷椤忓嫧鍋撻妶澶婄；闁告洦鍨侀崶顒侇棃婵炴垶纰嶅▓鎯р攽閻樼粯娑фい鎴濇嚇瀹曟﹢鍩€椤掆偓椤啴濡堕崱妯烘殫闂佸摜濮寸€涒晝绮嬮幒鏇ㄦЩ濡炪値浜滈崯瀛樹繆閸洖宸濇い鏍ㄧ矤閸炲爼姊绘担铏瑰笡妞ゃ劌鎳橀弫鍐敂閸繄鐣洪梺璺ㄥ枔婵挳宕￠幎鑺ョ厪闊洢鍎崇壕鍧楁煕濞嗗繑顥滈柍瑙勫灴閹晝绱掑Ο濠氭暘婵犵妲呴崑鍛存偡閳轰胶鏆﹂柟鎯板Г閸嬧晝鈧厜鍋撻柍褜鍓涙竟鏇㈡偂鎼搭喚鍞甸柣鐘烘〃鐠€锕傚磿閹扮増鐓忛柛銉ｅ妿缁犵偤鏌＄仦绯曞亾瀹曞洦娈曢梺閫炲苯澧寸€规洑鍗冲浠嬵敇濠ф儳浜惧ù锝囩《閺嬪酣鏌熼悙顒佺稇婵炲牄鍎靛娲濞戞艾顣哄┑鐐茬湴閸旀垵鐣烽姀銈庢晬婵炴垶顨堢粻姘舵⒑缂佹ê濮﹀ù婊勭矒閸┾偓妞ゆ帊绀侀悘瀵糕偓瑙勬礈閹虫挾鍙呭銈呯箰閹冲酣宕滈纰辨富闁靛牆妫涙晶閬嶆煕鐎ｎ偆娲寸€殿喖鎲＄粭鐔煎焵椤掑嫬钃熼柣鏂垮悑閸嬪鏌涢銈呮灁闁告埊绻濋幃妤呮偡閻楀牆鏆堢紓浣筋嚙閸熷瓨淇婇悽绋跨妞ゆ牗姘ㄩ濠囨⒑缁洖澧查柕鍥╁仦缁旂喖寮撮姀鈾€鎷绘繛杈剧到閹诧繝骞嗛崼鐔翠簻闁瑰瓨绻冮崵鍥煙椤斻劌娲ょ粻濠氭煙妫颁胶鍔嶇紓宥呮捣缁辨捇宕掑▎鎴濆闁藉啫宕埞鎴︻敍濮樼厧娈剁紓浣介哺鐢帡鍩ユ径濠庢建闁糕剝顨呮竟鍫熺節閻㈤潧浠滈柣妤€锕畷婵嗏枎韫囷絾缍庡┑鐐叉▕娴滄粍瀵奸悩缁樼厪濠㈣泛鐗嗛崜楣冩煥濠靛棭妲归柣鎾跺枑娣囧﹪濡堕崨顓熸闂佸疇顕ч悧濠囥€冮妷鈺傚€烽柟缁樺笚濞堢粯绻濈喊澶岀？闁稿繑锕㈠畷娲晸閻樿尙锛滃┑顔斤供閸嬪棝寮冲Δ鍛拻濞达絼璀﹂弨鏉款熆閻熸壆澧︽鐐存崌椤㈡棃宕卞Δ鍐摌闂備浇顕栭崹搴ㄥ焵椤掑嫬鍑犻柡鍌濐嚦閺冨牊鏅查柛娑卞幗濞堟煡姊洪幎鑺ユ暠閻㈩垱甯℃俊鎾箳閹搭厽鍍靛銈嗗笂閻掞箓骞冨▎鎰瘈闁冲皝鍋撻悘鐐跺Г閻忔挾绱撴担浠嬪摵閻㈩垳鍋ら崺鈧い鎺戯功瀹€娑㈡煛閸涱喚绠樼紒顕嗙秮瀵噣宕掑Δ鈧禍鐐箾閸繄浠㈡繛鍛耿閺屾稓鈧綆浜峰銉╂煟閿濆洤鍘寸€规洖銈稿鎾Ω閿旇姤鐝滄繝鐢靛仩閹活亞寰婃禒瀣妞ゆ劧濡囧畵浣逛繆閵堝嫯鍏岀紒鈾€鍋撶紓浣稿⒔婢ф鎽銈庡亜閿曨亪寮诲☉銏犖╅柕澶堝劥閸╃偛顪冮妶搴濈盎闁哥喐娼欓悾椋庣矙鐠囩偓妫冮崺鈧い鎺戝閸嬵亝銇勯弴妤€浜鹃梺缁樻惄閸嬪﹤鐣烽崼鏇炍╅柨鏃€鍎冲鎵磽閸屾瑦绁版い鏇嗗吘娑樷攽鐎ｎ亣鎽曢梺闈涚墕濞层倝寮搁崼銉︾厱婵°倕鍟禒婊勩亜椤愮喐娅婃慨濠冩そ瀹曘劍绻涢幒婵呴偗闁诡喗妞芥俊鎼佸煛娴ｈ櫣鏉介梻渚€娼ч…顓熶繆閸モ晛濮柍褜鍓熷娲川婵犲倸顫呴梺鍝勫€搁崐鍦矉閹烘顫呴柕鍫濇閳ь剛鏁婚幃宄扳枎韫囨搩浠炬繝銏ｆ硾鐎氫即寮诲☉姘ｅ亾閿濆簼鎮嶇€规悶鍎甸弻锝夋晲閸パ冨箣闂佽鍠撻崹浠嬪箖閳╁啯鍎熼柨娑樺閸嬫捇顢橀悜鍡樺瘜闂侀潧鐗嗗Λ妤佹叏閸モ晝纾煎璺侯儑閸欌偓閻庤娲栫紞濠囧箰婵犲啫绶炴俊顖濆吹缁嬩焦绻濋悽闈涗粶婵☆垰锕ョ粋宥咁煥閸曨偒鍤ら梺缁橆焽缁垶鎮￠弴銏＄厸闁搞儯鍎辨俊鐓庮熆瑜滈崰妤冩崲濞戙垹宸濇い鎰ㄦ噰閸嬫挸螖閸愨晩娼熼梺瑙勫劤椤曨參鎮疯ぐ鎺撶厱闁靛鍨电€氼喗绂嶉鍡欑＝闁稿本鐟ㄩ崗宀€绱掗鍛仸闁轰礁鍟存慨鈧柕鍫濇娴犳帒顪冮妶鍡樼叆婵℃彃鐗撳顕€宕煎┑鍥ヤ虎濠电偠鎻紞鈧い顐㈩槸閳诲秹宕堕浣叉嫽婵炶揪绲块…鍫ュ汲闁秵鐓熼煫鍥ㄦ尵婢э妇鈧鍠楄ぐ鍐€﹂妸鈺侀唶婵犻潧娴傚Λ鐔兼⒒娓氣偓閳ь剛鍋涢懟顖涙櫠鐎涙ɑ鍙忓┑鐘插鐢盯鏌熷畡鐗堝殗鐎规洦鍋婂畷鐔碱敂閸℃瑥顦╅梻鍌氬€烽懗鍫曗€﹂崼銉︾厐闁挎繂妫涢々鏌ユ偣妤︽寧顏犻柡鍡檮閵囧嫰寮介妸褏鐓侀悗瑙勬礀椤︾敻寮婚弴鐔虹鐟滃秶鈧艾鎽滃Σ鎰版晸閻樺磭鍘介梺缁樻煥閹芥粓鎯岀€ｎ偂绻嗘い鎰╁灩閺嗘瑦銇勯弴顏嗙ɑ缂佺粯绻傞～婵嬵敇閻愭壆鐩庣紓鍌欒兌閸嬫挻鍒婇懞銉ｄ粓闁归棿绀侀悿楣冩煃閸濆嫭鍣洪柍閿嬪灩缁辨挻鎷呴懖鈩冨灩娴滄悂顢橀悩鐢碉紲闂侀潧顭堥崕鎶藉春閿濆洠鍋撶憴鍕闁搞劌娼￠悰顔嘉熼崗鐓庣彴闂佽偐鈷堥崜锕傚疮閸パ€鏀介柣鎰煐瑜把呯磼閹绘帗鍋ユ鐐诧躬楠炴鈧潧澹婂ù鍕節闂堟稑鈧悂骞夐敓鐘茬９闁汇垹鎲￠悡鐔兼煟閺傛寧鍟炵紒璺哄级閵囧嫯绠涢敐鍕仐闂佽鍠楅〃鍛达綖濠靛鏁嗛柛灞惧焹閸欐椽鏌ｆ惔銏╁晱闁革綆鍣ｅ畷鎶芥晲閸涱垱娈鹃梺缁樻尭缁ㄥ爼寮ㄦ禒瀣厱闁斥晛鍟伴幊鍛偓瑙勬礀閹碱偊鍩為幋锔芥櫖闁告洦鍋傞弶顓㈡⒑缁嬪尅鏀婚柣妤冨█閻涱噣骞囬弶鍧楀敹闂佸搫娲ㄩ崑娑㈡倵椤撱垺鍋℃繝濠傛噹椤ｅジ鎮介娑樻诞鐎殿喖鎲＄粭鐔煎焵椤掑嫬绠栫€瑰嫭澹嬮弸搴ㄧ叓閸ャ劍鎯勫ù灏栧亾缂傚倸鍊风拋鎻掝瀶瑜斿畷鎴﹀箻缂佹ǚ鎷绘繛杈剧到濠€鍗烇耿娴犲鐓曢柕濞垮妽椤ュ銇勯鐐寸┛妞わ附鐓￠弻锝夊煡閸℃绫嶅┑顔硷功缁垶骞忛崨瀛樺仭闂侇叏绠戝▓婵囩節閻㈤潧浠︾憸鏉垮暟閹广垹螣閾忚娈鹃梺褰掑亰閸忔﹢寮ㄦ禒瀣€甸柨婵嗛婢ь喚绱掓笟濠勭暤婵☆偄鎳橀、鏇㈠閳ユ剚妲辨繝鐢靛仦瑜板啰绮旈悷鎵殾闁硅揪绠戠粻鑽ょ磽娴ｈ偂鎴濃枍濠婂牊鐓欓柤娴嬫櫈钘熼梺閫炲苯澧查悘蹇旂懇閹嫭鎯旈～顓犵畾闂佺粯鍔︽禍婊堝焵椤掍胶澧悡銈夋煟閺傛寧鎲告い鈺傜叀閺屾盯顢曢敐鍡欘槬闂佽棄鍟伴崰鎰崲濞戙垹绠ｆ繛鍡楃箳娴犲ジ鏌涢悜鍡楃仩妞ゎ亜鍟存俊鍫曞幢濡攱瀚介梻浣告啞椤棝宕舵搴ｂ棨婵＄偑鍊曠换鎰版偋婵犲洤鐓曢柟瀵稿Х绾捐棄霉閿濆牆浜楅柟瀵稿С閻掑﹪鏌ｉ姀鐘冲暈闁绘挻娲熼弻锝呂熼搹鐧哥礊婵犫拃鍛毄闁逞屽墯椤旀牠宕伴弽顓涒偓锕傛倻閽樺鐎梺鍦濠㈡ê顔忓┑瀣厱閻忕偛澧介惌濠囨煛鐎ｎ偆娲撮柡宀€鍠撶划鐢稿捶椤撶姷妲囧┑鐘殿暯閳ь剙纾崺锝団偓瑙勬礀瀹曨剝鐏冩繛杈剧到閹碱偆绱為幘缁樷拻闁稿本鑹鹃埀顒佹倐瀹曟劖顦版惔锝囩劶婵炴挻鍩冮崑鎾搭殽閻愭惌娈旀い顓滃姂瀹曠厧鈹戠€ｎ偓绱梻鍌欑窔濞佳囁囬锕€鐤炬繛鎴炶壘椤ユ艾鈹戦悩宕囶暡闁绘挻娲熼弻锟犲炊閵夈儱顬堟繛瀛樼矋缁海妲愰幒鎾剁懝闁搞儜鍌滅泿闂備礁鐤囬～澶愬垂閸ф绠栭柍鍝勬噹閸ㄥ倹銇勯幇鍓佺ɑ闁伙箑楠搁埞鎴︽偐閹颁礁鏅遍梺鍝ュУ瀹€绋款嚕椤愶箑绠瑰ù锝呮憸閻涖儲绻濋悽闈浶㈤柛瀣瀹曘儳鈧綆浜堕悢鍡涙偣鏉炴媽顒熼柛搴＄箰闇夋繝濠傚濞堟粍鎱ㄦ繝鍛仩缂佽鲸甯掕灒闁煎鍊曞鎶芥⒒娴ｅ憡鍟為柤褰掔畺椤㈡牗寰勯幇顒傜暫闂佽法鍠撴慨鏉戞暜闂備焦瀵ч弻銊︽櫠娴犲鍎婇柛顐犲劜閳锋帡鏌涚仦鐐殤濠⒀勭〒缁辨帞鈧綆鍋勫ù顕€鎸婇悢鍏肩厽闁归偊鍠栭崝瀣煟閹惧瓨绀嬮柡灞诲妼閳规垿宕卞Ο鐑橆仱缂傚倷绀侀ˇ鏉款渻娴犲钃熼柨娑樺濞岊亪鏌ｉ敐鍛健鐟滄棃寮婚敍鍕勃閻犲洦褰冮‖瀣⒑闁偛鑻晶鍓х磽瀹ュ懏顥㈢€规洘鍨块獮鎺楀箠閾忣偆娲寸€规洘锕㈤、娆戞喆閿濆棗顏归梻鍌欑閹诧紕鎹㈤崒婧惧亾濮樼厧娅嶉柟顔斤耿閺屽棗顓奸崱娆忓箞闂備胶绮摫闁绘搫绻濆畷锝夊礋椤栨稓鍘靛銈嗘磵閸嬫挾绱掗悩宕囧⒌鐎殿噮鍋婇獮妯肩磼濡桨姹楅柣搴ゎ潐濞叉牕煤閵堝棙鍙忔繛宸簼閳锋帒霉閿濆洦鍤€妞ゆ洘绮嶇换娑㈠箵閹烘枬褏鈧娲橀崹鍧楃嵁濡偐纾兼俊顖滃帶楠炲牓姊绘担绛嬫綈鐎规洘锕㈤敐鐐村緞鐏炴儳鍘归梺缁樺姦閸忔瑦绂嶅鍕╀簻闊洦鎸搁鈺呮煛閸☆厾鍒伴柍瑙勫灴閸ㄦ儳鐣烽崶褏鍘介柣搴ゎ潐濞叉﹢鏁冮姀鈥茬箚婵繂鐭堝Σ娲⒑濮瑰洤鍔村ù婊庝簻椤繒绱掑Ο璇差€撻梺鑽ゅ枛閸嬪﹪宕电€ｎ亖鏀介柣鎰綑缁茶崵绱掔紒妯忣亪鎮炬搴㈠枂闁告洦鍙庡ù鍕煟鎼搭垳绉甸柛鎾寸懅缁﹪鏁冮崒娑掓嫼闂佸憡绋戦敃銈嗘叏閿曞倹鐓曢柣妯虹－婢х敻鏌熼鍏夊亾閺傘儲顫嶉梺闈涢獜缁辨洟宕㈤崡鐐╂斀闁绘劖娼欓悘銉р偓瑙勬处閸撶喎顕ｇ粙搴撴婵☆垰绻愮紞濠囧箖閳哄懏鎯炴い鎰С閾忓孩绻濆▓鍨灈闁挎洏鍊濋獮鏍敃閿濆棙鐝￠梻鍌欑劍閹爼宕曞鍫濆窛妞ゆ帒鍊婚ˇ鈺傜節閻㈤潧啸闁轰焦鎮傚畷鎴濐潨閳ь剙鐣烽悩缁樺亹閻犲洦褰冪粣娑橆渻閵堝棙顥嗗┑顔哄€濋、娆撳炊椤掍讲鎷洪梺鑽ゅ枑濠㈡﹢骞冮幋锔界厽闁挎繂绨奸柇顖溾偓瑙勬礃缁诲倿顢橀崗鐓庣窞濠电姴瀚獮鍫ユ⒒娴ｅ憡璐￠柛搴涘€濆畷闈涱潩閻愭垝姹楅梺鍦劋閹歌鈻嶅鍫熲拺闁告挻褰冩禍鐐烘煕閿濆啫鍔氶摶鐐烘煕閺囥劌鐏￠柍閿嬪灴閺屾稑鈽夊鍫熸暰闂佹眹鍔嶉崹鍧楀蓟閻斿吋鎯炴い鎰剁到绾炬娊姊虹化鏇熸珖闁稿鍊濋悰顔锯偓锝庡枟閺呮粎绱撴担鑲℃垵鈻嶉幘缁樷拻濞达絿顭堥幃鎴犵磼娴ｈ灏︾€殿喗鐓￠、鏃堝幢濮楀棙缍楅梻浣虹帛閸旀宕曢妶澶婄厱闁硅揪闄勯悡鐔兼煟閺傛寧鍟炵紒璺哄级娣囧﹪鎳犻鍌氱闂侀潧娲ょ€氫即鐛€ｎ亖鏀介柟閭﹀帨閿曗偓椤啴濡堕崱妯尖敍缂備焦褰冩晶浠嬪箲閵忕姭鏀介柛鈾€鏅滈崓闈涱渻閵堝棗鐏嶉柡鍌氬€垮畷婵嬪箣閿曗偓閽冪喖鏌￠崶鈺佹灁闁绘繆鍩栭妵鍕冀閵娿劌顥濋梺鍝勬閻熝囧箖椤斿皷鏀介柛銉㈡櫇閻﹀牏绱掗悙顒佺凡妞わ箒浜竟鏇㈠锤濡や胶鍘遍柣搴秵閸嬪嫰鎮樼€电硶鍋撶憴鍕闁告梹鐟ラ锝夊磹閻曚焦顎囬梻浣告憸閸犲酣骞婃惔銊ョ厴闁硅揪闄勯崑鎰版倵閸︻厼孝妞ゃ儲绻勭槐鎺楁倷椤掆偓閸斻倖銇勯鐘插幋鐎殿喖顭烽幃銏ゆ偂鎼达綆妲堕柣鐔哥矊缁绘帡寮灏栨闁靛骏绱曢崢浠嬫⒑鐟欏嫬鍔ら柣掳鍔庣划鍫⑩偓锝庡枟閻撴稓鈧厜鍋撻悗锝庡墰琚﹂柣搴㈩問閸ｎ噣宕抽敐鍛殾濠靛倸鎲￠崑鍕煕濞戞﹫鏀绘い鏂跨箻濮婂宕掑▎鎺戝帯濡炪値鍘奸悧鎾汇€侀弽顓炵妞ゆ棁鍋愰敍鐔兼⒑濮瑰洤鐏い顓炵墦閹锋垿鎮㈤崗鑲╁幗闂佸搫鍟崐鐢稿箯閿熺姵鐓涘ù锝夋交閸旂喓绱掓潏銊﹀磳鐎规洘甯掗～婵囨綇閵婏箑鏋涢梻鍌欑劍閹爼宕濆畝鈧槐鐐寸節閸モ晛绁﹂梺纭呮彧缁犳垿锝為崨瀛樼厽婵妫楁禍婵嬫煛閸屾浜鹃梻鍌欐祰椤曆囧礄閻ｅ瞼绀婇柛鈩冾焽椤╂煡鏌ｉ幇顒佹儓缁炬儳缍婇弻锝夊箛椤旂厧濡洪梺鎶芥敱閸ㄥ灝顫忔繝姘唶闁绘梹鍎奸崥鍌氣攽閻愭潙鐏熼柛銊ユ贡缁牓宕橀鐣屽帾婵犵數濮寸换鎺楁偩瀹曞洨纾?"
                "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛橆殽閻愯揪鑰块柟宕囧█椤㈡寰勭€ｆ挻绮撳缁樻媴鐟欏嫬浠╅梺鍛婃煥缁夊爼骞戦姀銈呯妞ゆ柨妲堥敃鍌涚厱闁哄洢鍔岄悘鐘绘煕閹般劌浜鹃梻鍌欑窔濞佳嗗櫣闂佸憡渚楅崹鎵暜閹烘鈷掗柛灞剧懅椤︼箓鏌熺喊鍗炰簻閾荤偞绻涢崱妯虹仴闁搞劍绻堥弻鐔煎箲閹伴潧娈梺钘夊暟閸犳牠寮婚妸銉㈡斀闁糕檧鏅滅瑧婵犵妲呴崑鍛存晝閵忋倕绠栫憸鐗堝笒缁犳帡鏌熼悜妯虹仴妞ゎ剙顦—鍐Χ閸℃鍙嗛梺缁橆殕閹告悂锝炶箛鎾佹椽顢旈崟顏嗙倞闂備礁鎲″ú鐔奉焽瑜斿畷婊堟焼瀹ュ棌鎷虹紓鍌欑劍閿曗晛鈻撻弴鐔翠簻闁靛鍎虫晶锔筋殽閻愭潙鐏村┑顔瑰亾闂佺粯锕╅崑鍛达綖瀹ュ鈷戦梻鍫熺〒缁犲啿鈹戦鎯у幋妞ゃ垺锕㈠畷顐﹀礋閵婏附鏉搁梻浣虹帛閸旀洖顕ｉ崼鏇€澶婎煥閸涱垳锛滅紓鍌欑劍閿氱紒妤佹皑缁辨帡宕掑☉妯昏癁闂佺娅曢悧鐘诲春閿熺姴绀冩い蹇撴捣闂傤垱绻濋悽闈涗哗闁规椿浜炲濠冪鐎ｎ亞顔愬銈嗗姧缁叉寧鏅堕敓鐘斥拻闁稿本鐟ㄩ崗宀€绱掗鍛仸闁靛棗鍟村畷鍗炩槈閺嶃倕浜鹃柛鎰靛枛楠炪垺绻涢崱妯虹仼闁绘挻妫冮弻鈩冨緞婵犲嫬顣堕梺鍛婃煥濞村嘲顕ｈ閸┾偓妞ゆ帒瀚埛鎴︽煙閼测晛浠滈柛鏃€鎸抽弻锝堢疀閺冨偆鐏卞銈忕畱缂嶅﹪寮婚敍鍕勃闁告挆鈧Σ鍫ユ⒑鐎圭姵顥夋い锕傛涧閻ｇ兘鏁撻悩鍐测偓鐑芥倵閻㈠憡娅滈梺顓у灠閳规垿鎮╅崹顐ｆ瘎闂佺顑嗛惄顖炵嵁韫囨稑绠ｉ柣妯垮皺缁涘繘鏌ｉ悩鍏呰埅闁告柨绉归敐鐐哄即閵忥紕鍘甸梺璇″瀻閸涱喗鍠栧┑鐘愁問閸ㄩ亶骞愰幎钘夎摕婵炴垶菤閺€浠嬫煕閳╁喚娈㈠ù鐓庣焸濮婃椽鏌呴悙鑼跺濠⒀屽櫍閺岋綁顢橀悙娴嬪亾閸噮鍤曢悹鍥ㄧゴ濡插牓鏌曡箛濞惧亾閸忓懏鐫忛梺璇叉唉椤煤閺嶎灐娲Χ婢跺﹦鍘遍悗鍏夊亾闁告洦鍏橀幏铏圭磽娓氬洤鐏℃繛鍙壝埢宥夊炊椤掍胶鍘遍柣搴祷閸斿矂鍩€椤掍胶绠為柟顔诲嵆椤㈡瑩鏌ㄩ姘闂佹寧绻傛鎼佸几閻斿吋鐓涢柛娑卞枤閻帡鏌″畝瀣暠閾伙絽銆掑鐓庣仭閸熷憡绻濆▓鍨灕妞ゎ偄顦甸妴鍐╃節閸屻倖缍庣紓鍌欑劍钃卞┑顖涙尦閺屾稑鈽夊鍫濅紣闂佸搫妫楅悧鎾愁潖濞差亝鍤掗柕鍫濇噺閻庮參姊虹粙璺ㄥ嚬缂佽尪顕ц灋闁绘柨顨庡〒濠氭煏閸繃顥犲褜鍓熼弻娑㈠煛娴ｅ憡娈婚悗娈垮枤椤牓顢樻總绋跨倞闁靛鍎查悗楣冩⒒婵犲骸浜滄繛璇х畱鐓ゆ慨妞诲亾闁挎繄鍋ゅ鎾閿涘嫬骞嶉梻浣筋嚃閸ㄥ酣宕ㄩ钘夋灈婵犵數濮甸鏍垂闁秴绠伴柟鎯版閽冪喐绻涢幋鐐冩岸寮ㄦ禒瀣厱闁斥晛鍠氬▓妯兼喐閺夋寧鍤囨慨濠冩そ濡啫鈽夋潏銊愩垽姊洪崫鍕櫤缂侇喗鎹囬獮鍐灳閺傘儲鐎婚梺瑙勫劤椤曨參宕ｉ崟顖涱棅妞ゆ劑鍨虹粊顐ょ磼閼艰泛袚缂佸倸绉撮埞鎴﹀醇濮橆兛澹曢柣鐔哥懃鐎氼厾绮堥埀顒勬⒑閸濆嫮澧遍柛鎾寸洴楠炴垿濮€閻橆偅鏂€闁诲函缍嗘禍鐐哄礉閿曗偓椤啴濡堕崱妤冪憪闂佺粯甯梽鍕礆婵犲嫧鍋撻棃娑欐喐缁炬儳鍚嬮妵鍕冀閵娧€濮囩紓浣插亾闁告劦鍠楅悡娑㈡煕鐏炵虎娈斿ù婊堢畺濮婂宕掑顑藉亾閻戣姤鍤勯柛鎾茬閸ㄦ繃銇勯弽顐汗闁逞屽墾缁犳挸鐣锋總绋课ㄦい鏃囧Г濞呮梹绻濋悽闈浶㈤柨鏇樺€濆畷鏉款潩鐠鸿櫣鏌堥梺鍛婄☉閻°劑鎮¤箛鎿冪唵閻犺櫣鍎らˉ鐐寸箾閸涱厽顥㈤柡灞剧⊕缁绘繈宕掑鈧划鐢告⒑闁稓鈹掗柛鏂跨焷閻忔帡姊虹紒妯诲碍濡ょ姴鎲＄粋鎺懳熺悰鈩冩杸闂佺粯鍔曞鍫曞闯閸︻厾纾煎璺猴功缁夎櫣鈧鍠涢褔鍩ユ径鎰潊闁绘﹢娼ч獮瀣⒒娴ｇ顥忛柣鎾崇墦瀹曚即寮介妸锕€寮块梺鍝勬储閸ㄦ椽宕愰悽鍛婄厱妞ゎ厽鍨垫禍婵堢磼閼哥數鍙€闁诡喗顨呴～婵嬵敃閵忕姷銈梻浣虹帛娓氭宕抽敐鍛殾闁割偅娲﹂弫鍡楊熆鐠轰警鍎愭繛鍛Ч濮婄粯鎷呴搹鐟扮闁藉啳浜幉鎼佸级閸喗娈剁紓渚囧枛椤兘骞冨▎鎾村€绘俊顖炴敱鐎氫粙姊绘担渚劸闁哄牜鍓熼幃鐤槾缂侇噯缍佸顕€鍩€椤掑倹宕叉繛鎴炵懄婵挳鏌涢幇顒€绾х紒鈧畝鍕厓鐟滄粓宕滈妸褏涓嶉柟鎯х－閺嗭箑鈹戦崒婊庣劸閸烆垶姊洪棃娑崇础鐎广儱娲ｇ憰鍡樼節閻㈤潧孝闁汇儱顦靛鑸垫償閹惧厖澹曢梺鍝勬储閸ㄥ湱绮婚悩鑽ゅ彄闁搞儯鍔庨埥澶岀棯閻愵剙顕滃ǎ鍥э躬婵″爼宕熼鐓庡腐缂傚倷鑳舵繛鈧紒鐘崇墵瀵鈽夐姀鐘靛姶闂佺绻掓刊顓熺椤忓牆绠栨俊顖欒閸氬顭跨捄渚剳闁告﹢浜堕弻锝嗘償椤栨粎校闂佺顑呴幊鎰閹间緡鏁囬柕蹇ョ磿閸樻挾绱撻崒娆戝妽閽冭京鈧娲栭惉濂稿焵椤掑喚娼愭繛鍙夌墱缁辩偞绻濋崶銉㈠亾娴ｇ硶鏋庨柟鐐綑娴犲ジ鏌ｈ箛鏇炰粶闁逞屽墰閸犳劗鈧凹鍓熷濠氬磼濮橆兘鍋撻幖浣哥９濡炲娴烽惌鍡椼€掑锝呬壕濡ょ姷鍋涢ˇ鐢稿极閹剧粯鍋愰柤纰卞墻閸炶泛鈹戞幊閸娧呭緤娴犲鐤い鎰╁€楅悳缁樹繆閵堝懏鍣洪柣鎾寸〒閳ь剙绠嶉崕杈殽閹间胶宓侀柡宥冨妽娴溿倖绻濋棃娑欏窛缂佺娀绠栧鍫曞醇濠靛棌鎸冮梺鍛婂笚濠㈡﹢鈥﹂崸妤佸仭閻㈩垼鍠栨导鎰渻閵堝骸骞栨繛宸幗娣囧﹪骞栨担鍝ュ幐闂佺鏈划宀€鏁Δ鍛厽闁绘柨鎽滈惌瀣磼椤旇姤灏柣锝呭槻椤劑宕奸悢铚傜盎濠碉紕鍋涢鍛偓娑掓櫅閳绘捇骞嗚閺€浠嬫煟閹邦剙绾ч柍缁樻礀闇夋繝濠傚閻﹪鏌℃笟鍥ф珝婵﹦绮幏鍛村传閵夛妇鈧喖鈹戦埄鍐︿粻闁告柨娴烽崚鎺楀醇閻旇櫣鎳濋梺閫炲苯澧存鐐诧躬楠炴鎷犻幓鎺斺偓顓烆渻閵堝棙顥嗘い顐㈩樀瀵剟鍩€椤掑嫭鈷戦柛锔诲幖閸斿鈹戦悙璇у伐闁伙絿鍏橀獮鍥级鐠侯煈鍟嬬紓鍌氬€烽悞锕傛晪闂侀€炲苯澧繛纭风節瀵濡搁埡浣稿祮濠德板€愰崑鎾趁瑰鍫㈢暫闁诡喛娉涢～婵嬵敇閻樺啿娅氶梻浣告惈閺堫剟鎯勯鐐叉槬闁告洦鍨扮粈鍐煕閹炬鍟缂傚倸鍊搁崐椋庢媼閹绘帩鐎剁憸鏂跨暦閹达箑绠荤紓浣骨氶幏缁樼箾鏉堝墽鍒版繝鈧崡鐑囪€垮ù鐘差儐閻撴洟鏌曟繛鍨妞ゃ儱顦伴妵鍕敇閻愬鈹涘銈忕畱绾绢厾妲愰幒妤€纾兼繛鎴炆戠拠鐐烘⒑缁洘娅旂紒缁樼箓閻ｇ兘濡搁埡濠冩櫓闂佽鍨庨崘顏嶅悑濠电姷鏁告慨鐑藉极閹间礁纾婚柣妯哄悁閻掑﹥銇勮箛鎾跺⒈闁轰礁锕ら埞鎴︽偐閹绘帩浼傛繝娈垮枟婵炲﹪寮婚敐澶嬫櫜闁告侗鍙庡Σ鐢告⒑缁嬫鍎愰柟鐟版搐閻ｇ柉銇愰幒婵囨櫇闂佹寧绻傚ú銈夊吹閹烘鈷掑ù锝囨嚀椤曟粍绻涚拠褔妾紒鍌氱Ч椤㈡棃宕奸姀鐘点偊濠电姷鏁告慨鏉懨洪敃鍌氱９闁绘垼濮ら悡鏇熺節闂堟稒顥滈柣婵嗩儔閺屾洘绻濊箛姘鳖槹婵炲瓨绮嶇划鎾诲蓟閿熺姴绀冮柕濞垮劗閸嬫挻绻濆顒傤啈闂佺鐬奸崑鐐烘偂閺囥垺鐓熼柡鍐ㄧ墱濡垿寮崼婵冩斀妞ゆ梻銆嬮崝鐔虹磼椤曞懎鐏ｉ柟骞垮灩閳规垿宕堕妸銉ュΤ闂備胶鍋ㄩ崕瀵镐焊濞嗘挻鍎庨幖娣灮缁♀偓闂佹眹鍨藉褎绂掗埡鍌樹簻闁哄洨鍠撻惌宀€绱掗纰辩吋妤犵偛顑夐幃鈺呭箵閹烘梹鐓ｅ┑鐘垫暩婵敻顢欓弽顓炵獥婵°倕鎳庢濠电偞鍨崹鍦婵犳碍鐓欓柛鎾楀懎绗￠梺缁樻尪閸庤尙鎹㈠┑瀣棃婵炴垶鑹鹃。鐑樼箾鐎电鞋濞存粠鍓熼崺鈧い鎺嶇贰閸熷繘鏌涢悩鎰佹疁妤犵偞鍔欓獮搴ㄦ寠婢跺瞼鏆梻渚€娼х换鍫ュ磹閺嶎厼绠氶柣鎰劋閻撴洟鏌ㄩ弮鍥跺殭妤犵偞顨嗛妵鍕敃閵忋垻鍔┑顔硷工椤嘲鐣烽幒鎴僵妞ゆ垼妫勬禍楣冩煙闂傚顦︾痪鎯х秺閺岀喖姊荤€电濡介梺绋款儏椤戝懘鍩為幋锔藉亹闁圭粯甯楀▓鍫曟⒑閼姐倕鏋欐い顐㈩槹缁岃鲸绻濋崶顬囨煕濞戝崬鏋涙繛鍜冪悼缁辨帡鎮欓鈧崝銈嗙箾绾绡€闁诡噯绻濋、鏇㈡晝閳ь剟鎮欐繝鍥ㄧ厪濠电倯鈧崑鎾斥攽椤斿吋鍠樻慨濠呮缁瑥鈻庨幆褍澹冮梻浣告啞閹歌崵鎹㈤崟顖氱闁靛繒濮Σ鍫ユ煏韫囨洖孝闁兼澘鐏濋埞鎴﹀煡閸℃浠╅梺鍛婅壘椤戝鐣烽幎绛嬫晪闁逞屽墮椤繘鎮滃Ο渚殼濠电偛妫欓崹鐢稿春瀹€鍕拺閻犲洩灏欑粻鑼偓鍏夊亾闁归棿绀佽繚闂佸憡鍔﹂崰鏍ф暜闂備礁鍟块幖顐﹀磹閹间礁鐒垫い鎺戝€搁崢鎾煙椤旂瓔娈滈柟顔挎閳绘挾鎹勯妸銉バ梻鍌欑劍閸撴碍绂嶅鍛濠电姴娲ら拑鐔兼煏閸繍妲哥紒鐘卞嵆楠炴牜鍒掗崗澶婁壕闁归鐒︾紞宀勬⒒閸屾瑧绐旀繛浣冲厾娲Χ閸ワ絽浜炬慨姗嗗亜瀹撳棝鏌ｅ☉鍗炴珝妤犵偞甯掕灃闁逞屽墴閻涱噣濮€閳ヨ尙绠氶梺缁樺姈濞兼瑩宕濋妶鍡愪簻闁靛濡囬。鑼磼缂佹绠為柟顔荤矙濡啫霉闊彃鐏查柡宀嬬秮婵＄兘濡烽瑙ｆ瀰濠电姷顣介埀顒€纾崺锝団偓瑙勬磸閸旀垵鐣烽妸鈺婃晩闁芥ê顦遍。鏌ユ⒑閸忕厧顕滈柛鏃€鐟╁璇测槈閵忕姈銊╂煙鐎涙绠樼€涙繃绻涢弶鎴濇倯闁告梹娲熼垾鏃堝礃椤斿槈褔骞栫€涙绠橀柣鈺侀叄濮婃椽宕妷銉︾€鹃梺鐟版啞婵炲﹪鎮伴鈧畷姗€顢欓懖鈺佸Ф闂備礁鎲￠崝蹇涘疾濞戙垹绀夐柛娑樼摠閳锋垿鎮楅崷顓炐ｆい銉ヮ槹娣囧﹪顢曢敐鍥ㄥ垱闂佺硶鏂侀崑鎾愁渻閵堝棗绗掗柛鐕佸灦閹敻顢旈崟鍕叄瀹曟儼顧傞棅顒夊墴閺岀喖顢欓悾灞惧櫚濡炪們鍨哄Λ鍐ㄧ暦閻旂厧惟闁靛鍊曢ˉ姘舵⒒娓氣偓濞佳囨偋閸℃あ娑樷槈椤兘鍋撻崨鏉戠煑濠㈣泛鐬奸惁鍫熺節閻㈤潧孝闁稿﹦绮弲鍫曞即閵忥紕鍘介梺闈涚墕妤犵鈻嶅澶嬬厵妞ゆ梻鐡斿▓鏃堟煃閽樺妲搁柍璇茬Ч椤㈡﹢鍨鹃崗鍛潖闂備胶鎳撶粻宥夊垂閽樺鏆﹂柛妤冨亹濡插牊绻涢崱妯虹仴妤犵偛鐗婃穱濠囨倷椤忓嫧鍋撻弽顓炵鐟滃繐顕ユ繝鍥х鐟滃繘鎯岄崱娑欑厓鐟滄粓宕滈悢濂夋綎缂備焦蓱婵绱掔€ｎ厼鍔甸柛鈺冨仜閳规垿鎮欓崣澶嗘灆闂佸憡鐟ラ崯顐︻敋閿濆棛绡€婵﹩鍘藉▍婊勭節閵忥絾纭鹃柨鏇樺€曢悾鐢稿幢濡炵粯鏂€濡炪倖姊归弸缁樼瑹濞戙垺鐓曟繛鍡楃箻椤庢鎽堕敐澶嬬厱鐎光偓閳ь剟宕戦悙鍝勭厱闁硅揪闄勯悡鏇熺箾閹寸儑鍏柛鏃傚枔缁辨帡鎮╁畷鍥ь潷闂侀潧娲ょ€氱増淇婇幖浣肝ㄩ柨鏃傜帛閿熴儵姊绘担鐑樺殌缂佺姴绉瑰畷纭呫亹閹烘垹鍘撮梺鐟邦嚟婵參宕戦幘缁樻櫜閹肩补鈧尙鐩庡┑鐐差嚟婵潧顪冮挊澶樻綎濠电姵鑹剧壕鍏兼叏濡搫鑸规い銈傚亾缂傚倸鍊风粈渚€顢栭崱娑樼婵炲棙鎸惧畵渚€鎮楅敐搴℃灍闁稿﹤顭烽弻銈夊箒閹烘垵濮夐梺褰掓敱濡炶棄顫忓ú顏勫窛濠电姴瀚уΣ鍫濐渻閵堝骸寮鹃柛鎾跺枛楠炲啴鎮欑€垫悂妾梺鍛婄☉閿曪箓宕㈤柆宥嗏拺闂傚牊渚楀Σ褰掓煕閵娧勬毈妤犵偛锕ㄧ粻娑樷槈濞嗗繆鍋撻崹顔ユ棃鏁愰崨顓熸闂佹娊鏀辩敮鎺楁箒闂佹寧绻傞幊蹇涘疮閻愮儤鐓欐い鏍ㄦ皑婢ф盯鏌曢崶褍顏柡浣稿€垮畷褰掝敊閼测斂鍋栭梺璇叉唉椤煤濠婂牄鈧焦绻濋崶顬箓鏌熼悧鍫熺凡缂佺姵濞婇弻鐔衡偓鐢殿焾娴犫晝绱掗煬鎻掔伈婵﹦绮幏鍛存偡闁箑娈濇繝鐢靛仜瀵爼鎮ч悩鑼殾闁归偊鍨禍褰掓煙閻戞ɑ灏ù婊勵殜濡懘顢曢姀鈥愁槱闂佺懓鐨烽弲鐘诲箖閵忋倕骞㈡繛鎴炵懃娴狀垶姊洪幖鐐插姷缂佸弶妞藉畷鎴﹀箻瀹曞洦娈鹃梺鎼炲劵缁犳垿骞楃€ｎ喗鈷掗柛灞剧懆閸忓本銇勯鐐靛ⅵ闁轰礁鍟存俊鍫曞炊閳哄喚妲稿┑鐘垫暩婵挳宕愭繝姘辈闁挎洖鍊归悡鐔兼煛閸愩劌鈧摜鏁崜浣虹＜闁逞屽墴瀹曟﹢鍩炴径鍝ョ泿闂備礁鎼崯顐⑩枖閿曞倸绠虫俊銈傚亾缂佺媭鍨辩换娑橆啅椤旇崵鍑归梺鎶芥敱閸ㄥ湱妲愰幒鏂哄亾閿濆骸骞楃痪顓炲缁辨帡鎮╅搹顐犱虎闂佸搫鏈粙鎾诲焵椤掑﹦绉甸柛瀣閹便劌顓奸崨顏呮杸闂佺偨鍎辩壕顓㈠春閿濆棭娈介柣鎰彧閼版寧銇勯姀锛勬噰闁诡喖澧芥禒锕傛寠婢跺矈鍞堕梻鍌氬€搁崐椋庣矆娓氣偓楠炲鍩勯崘顏嗘嚌濠德板€撻懗鍫曘€呴崣澶岀瘈闂傚牊绋掗ˉ鎴︽煛鐎ｎ亞效闁哄本鐩崺鍕礃椤忎礁顫岄梻浣侯焾閿曪箓寮拠宸綎濠电姵鑹鹃柋鍥煟閺冨洢鈧偓婵☆偁鍔戝铏圭矙濞嗘儳鍓梺鎼炲妼椤兘宕洪埀顒併亜閹烘垵鏋ゆ繛鍏煎姈缁绘盯宕ｆ径灞解拰闂佽鍠撻崕鑼紦娴犲绠归柣鎰ㄦ櫅娴滄儳霉閿濆牆鈧粙寮埀顒勫箯閸涘瓨鍋￠梺顓ㄨ吂閸嬫捇骞樼紒妯锋嫼闂佸憡绋戦敃锕傚箠閸愨斂浜滈柨鏃囶嚙閻忥附銇勯姀鈩冾梿闁靛洦鍔欓獮鎺楀箻椤栨稑顏洪梻鍌欒兌椤牓寮甸鍕仭鐟滄棁妫熼梺鎸庢礀閸婂綊鎮″▎鎾村仯闁搞儱娲ら幊鎰版晬閻斿吋鈷戦柣鐔稿閻ｎ參鏌涢妸銊︻棄闁伙絿鍏橀獮鎺楀箣閺冣偓閺佺娀姊虹拠鈥崇€婚柛灞惧嚬濡粌鈹戦悩鎰佸晱闁哥姵顨婇弫鍐煛閸涱厾顦┑鐐叉缁箖鏁愰崱娆戠槇濠殿喗锕╅崜娑€侀崨瀛樷拻濞撴艾娲ゆ晶顔剧磼婢跺本鏆柟顔光偓鏂ユ瀻闁瑰濮烽敍婵囩箾鏉堝墽绉繛浣冲洦鍊堕柍鍝勬噺閻撴盯鎮楅敐搴″闁哄鐩弻鈥崇暆鐎ｎ剛袦濡ょ姷鍋為敃銏犵暦濮椻偓瀹曪絾寰勭€ｉ潧鏅欓梻鍌氬€烽懗鍫曘€佹繝鍕剨婵炲棙鎸撮埀顒婄畵瀹曞ジ濡烽埗鈺佷壕闁挎洖鍊告儫闂佸疇妗ㄧ欢姘跺船鐠鸿　鏀介柣妯肩帛濞懷囨煟濡や胶鐭婇崡閬嶆煠閸濄儲鏆╃紒鈾€鍋撴繝鐢靛仜閻楀棝鎮樺┑瀣嚑闁绘梹鎮舵禍婊勩亜閹捐泛浠﹂柛鐘愁焽閳ь剝顫夊ú姗€宕归幐搴濈箚闁归棿鐒﹂弲婊呯磽娴ｉ潧鐏梺瑁ゅ€濋弻锝夋偄閸濄儳鐓傛繝鈷€鍕垫畼闁轰緡鍠栬灃闁告侗鍠栨禍妤呮⒑閸濆嫭鍌ㄩ柛銊︽そ閹€斥枎瀵版繂缍婇幃鈩冩償閿濆棙鍠栨繝鐢靛仦閸ゎ亪宕堕妸褍骞愰梺璇插嚱缂嶅棝宕滃▎鎾冲嚑婵炴垯鍨洪悡娑㈡倶閻愭彃鈷旈柍顖涙礋閺岀喖顢涘☉娆樻闂佺硶鏂傞崕闈涚暦閵娾晩鏁婇柤鎭掑劜閻︾偟绱撻崒姘偓鎼佸磹閻戣姤鍤勯柛鎾茬閸ㄦ繃銇勯弽銊х煁鐎规洘鐓￠弻娑㈠箛閸忓摜鍑归悗瑙勬礀瀵墎鎹㈠┑瀣棃婵炴垵宕崜鎵磼閻愵剙鍔ら柛姘儑閹广垹鈽夐姀鐘殿吅闂佺粯鍔曞Λ娆撳垂閸фぜ鈧線寮崼婢囨煕閵夈垺娅囬柨娑欑箖缁绘稒娼忛崜褍鍩岄梺鍦拡閸嬪懐绮嬪鍡愬亝闁告劏鏅濋崢閬嶆煙閸忚偐鏆橀柛銊ョ秺閸┿垽寮撮悙鈺傛杸闂佺偨鍎辩壕顓㈠春閿濆棭娈介柣鎰嚟婢ь剟鏌熷畡鐗堝櫣妞ゎ偁鍨绘禒锕傛倷椤掆偓閺嗩偊姊婚崒姘偓鐑芥嚄閸撲礁鍨濇い鏍ㄥ嚬濞兼牕鈹戦悩瀹犲闁绘挻娲熼弻娑㈩敃閻樻彃濮庨梺鍝勵儎閼冲爼鍩€椤掆偓缁犲秹宕曢柆宓ュ洦瀵肩€涙ê浜楅梺鍝勬储閸ㄦ椽鎮￠崘顔界厓閺夌偞澹嗛ˇ锕傛煛鐎ｃ劌鈧牜鎹㈠☉銏犻唶闁绘梻纭堕幏褰掓⒑闂堟稒鎼愰悗姘煎灣缁鈽夊▎鎴犵槇闂佸憡鍔忛弲婵娿亹閸涘瓨鈷掗柛灞剧閹兼劖銇勯敂鐐毈鐎殿喖顭烽弫鎰板川閸屾粌鏋涙鐐村姈閹棃鏁愰崨顕€鏁梻鍌欐祰椤曆呮崲閹邦収娈介煫鍥ㄧ⊕閳锋棃鏌涢弴銊ョ仩缂佺姷鍋ら弻鏇熺節韫囨搩娲紓浣叉閸嬫捇姊绘担鍛婂暈闁告柨绻樺顒勫磼濞戞凹娴勯梺闈涚箞閸婃牠宕愰悽鍛婂仭婵炲棗绻愰顏勵熆鐠哄搫顏柡灞剧〒閳ь剨缍嗘禍宄邦啅閵夆晜鐓熼柨婵嗘搐閸樻挳鏌熼鍝勭伄闁哥姴锕ュ蹇涘Ω閿旂晫褰嶅┑鐘垫暩婵即宕归悡搴樻灃婵炴垯鍩勯弫鍕煙鐎电校妞ゎ偅娲樻穱濠囧Χ閸曨喖鍘＄紓浣叉閸嬫捇姊绘担鍦菇闁搞劏妫勯…鍥槼缂佸倹甯掗…銊╁醇閻斿搫骞楅梺鍦劋婵炲﹤鐣峰┑鍥ㄥ劅闁靛鍎抽ˇ顐︽⒑閸︻厼鍔嬫繛鍙夌矒閹潡鍩€椤掑嫭鈷戦柛锔诲弨濡炬悂鏌涢妸鈺€鎲鹃柟顔斤耿瀹曟﹢濡搁姀鈩冩澑闂備胶绮崝鏍ь焽濞嗘挻鍊堕柣鏂垮悑閻撴洟鏌嶆潪鎵槮妞ゅ浚鍘鹃埀顒侇問閸ｎ噣宕戦崱娑樼劦妞ゆ帒锕︾粔鐢告煕閻樻剚娈滈柟顕嗙節婵＄兘鏁傞崜褏妲囬梻鍌氬€搁悧濠勭矙閹烘鏅€广儱妫旂换鍡涙煙缂佹ê绗х紒澶嬫そ閺岋紕浠﹂崜褋鈧帡鏌嶈閸撱劎寰婃繝姘閻忕偟鍋撻崣蹇涙煕瀹€鈧崑鐐烘偂濞戙垺鍊堕柣鎰絻閳锋棃鏌嶉挊澶樻█闁哄苯绉归幐濠冨緞濡亶锕€顪冮妶搴′簼缂侇喗鎸搁悾鐑芥偂鎼存ɑ鏂€闂佸憡渚楅崹鎶芥偂閹存績鏀介柣妯虹仛閺嗏晠鏌涚€ｎ偆娲撮柟顔芥そ婵℃瓕顦查柛銊︾箘閳ь剙绠嶉崕鍗灻洪妶澶婂瀭婵犻潧顑呯粻褰掑级閸繂鈷旂紒瀣帛閵囧嫰顢曢敐鍡欘槹闂佸搫鐬奸崰鏍嵁閸℃凹妲鹃梺鍦櫕婵挳鍩為幋锔绘晬婵炴垶鐟ラ崬澶愭⒑閸濆嫭婀伴柣鈺婂灦閻涱喖顫滈埀顒€顕ｉ崼鏇炵闁绘鍋ｉ崑锟犳⒒閸屾瑧顦﹂柟璇х節楠炴劙鎮滈挊澶岊攨闂佸憡鍔曞Ο濠傤焽閺嶎厽鐓ｉ煫鍥ㄥ嚬濞兼劙鎮楀顓炲摵闁哄被鍊楅崰濠囧础閻愬樊娼炬俊鐐€栭弻銊┧囨潏鈺傤潟闁规儳鐡ㄦ刊瀵哥磼濞戞﹩鍎忔繛鍫弮濮婅櫣绱掑鍡樼暦闂佸憡姊瑰ú婵嬫倶鐎ｎ喗鈷戠紓浣股戦悡銉╂煕濮橆剦鍎旈柛鈺傜洴楠炲鏁傞悾灞藉箞婵犵數鍋為崹鍫曟晝椤愶箑绀夐柣鏂垮悑閻撴瑩鏌涢幇顓炵祷闁哄棛鍋ら弻鏇㈠炊瑜嶉顓㈡煛娴ｇ鏆為柟宄版噹閻ｏ繝鎮ч崼婵嗗缂傚倸鍊搁崐椋庢閿熺姴绐楁慨妯哄船閸ㄦ繃銇勯弽顐粶閸ユ挳姊洪幐搴ｇ畵妞わ富鍨崇划鍫ュ礃椤旂晫鍘繝鐢靛€崘鈺佺獩閻庤娲樼划鎾愁潖婵犳艾纾兼繛鍡樺焾濡差喗绻濋姀銏″殌闁挎洦浜滈悾鐑藉箣閿曗偓瀹告繃銇勯弽銊р槈閹兼潙锕铏圭矙鐠恒劎浼囬梺绋款儐閻╊垶骞冮敓鐘插嵆闁靛骏绱曢崢鎼佹⒑閸涘﹤濮傞柛鏂垮閺呰泛鈽夐姀锛勫幗闂佽鍎抽悺銊х矆鐎ｎ喗鐓涚€光偓閳ь剟宕伴弽顓炵畺婵犲﹤鍚橀悢鐑樺珰闁肩⒈鍓﹂弳鈥斥攽閿涘嫬浜奸柛濠冨灴瀹曟洟鏌嗗搴㈡櫈闂佹悶鍎弲婊堬綖閺囥垺鐓欓柣鎴炆戠亸鎵磽瀹ュ懏鍠橀柡灞炬礃缁绘盯宕归鐓幮戞俊鐐€栭崹鐢稿磹閸噮娼栧Δ锕侊骏娴滃綊鏌熼悜妯肩畺妞ゃ儲鐗楃换婵嗏枔閸喗鐏嶉梺鐟版啞婵炲﹪濡存担绯曟瀻闁圭儤姊婚弶绋库攽閻愭潙鐏卞瀛樻倐瀵煡鍩￠崨顔规嫼缂傚倷鐒﹁摫閻忓浚鍘艰灃闁绘娅曢崐鎰版寠閻斿吋鐓欓梺顓ㄧ畱閺嬨倗鐥崣銉х煓闁哄本绋撴禒锕傚箲閹邦剦妫熼梻渚€鈧偛鑻晶顕€鏌涢姀锛勫弨婵犫偓娓氣偓濮婃椽骞栭悙鎻掑闂佸憡鏌ㄩ柊锝夊Υ閸涙潙鐭楀璺虹墔缁ㄥ姊洪崷顓炲妺闁搞劎鏁婚、鏃堝煛閸愵亝锛忛梺鍛婃寙閸涱厾顐肩紓鍌欒兌缁垶鎯勯鐐靛祦閻庯綆鍣弫鍥煟閺冨洦顏犻柣娴瑰懐纾介柛灞捐壘閳ь剙鎽滅划鏃堟偨閸涘﹤浜卞┑掳鍊曢崯顖氱暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸曗斁鍋撻崒姣椽顢旈崨顏呭缂傚倸鍊烽悞锕傛晪缂備焦顨嗙敮锟犲蓟閿濆牏鐤€闁哄倸鐏濋幗鍨節绾板纾块柡浣筋嚙閻ｇ兘鎮㈢喊杈ㄦ櫖濠殿喗锕㈢涵鎼佸船濞差亝鐓熼幖杈剧磿閻ｎ參鏌涙惔鈥宠埞閾荤偞銇勯幘璺衡偓锝夋偄閻撳海锛滃┑鐘诧工閹虫劙鏁?"
                "\n\n"
                "婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鈽夊Ο閿嬵潔濠殿喗顨呴悧濠囧极妤ｅ啯鈷戦柛娑橈功閹冲啰绱掔紒姗堣€跨€殿喖顭烽弫鎰緞婵犲嫷鍚呮繝鐢靛Т閻忔岸宕濋弽顐ょ婵°倕鎳忛埛鎴︽⒑椤愩倕浠滈柤娲诲灡閺呭爼顢氶埀顒勫蓟濞戞瑧绡€闁稿本绋栫涵鈧紓鍌欑贰閸犳牠顢栨径鎰祦闁圭儤顨呭Λ姗€鏌涘┑鍡楊仹濠㈣娲熷娲箰鎼达絿鐣电紓浣靛姀閸嬫劙鎳炴潏銊ь浄閻庯綆鍋嗛崢閬嶆⒑閸濆嫬鏆為柟鎼佺畺閹偓娼忛妸锝勭盎濡炪倕绻愮€氼剟寮抽敐鍛斀闁炽儱纾崺锝団偓瑙勬礀瀹曨剝鐏冮梺閫炲苯澧い顓炴喘楠炲鏁傜憴锝嗗缂傚倷绀侀鍡涱敄濞嗘挸纾块柟鎵閻撴瑩鏌ｉ悢鍝勵暭闁哥姵顭囬埀顒侇問閸犳盯顢氳閸┿儲寰勯幇顒夋綂闂佺偨鍎遍崢鏍姳婵犳碍鈷掗柛灞剧懅椤︼箓鏌ｈ箛鏃傜疄妞ゃ垺鐗犲畷銊╊敊缂併垺绁梻浣告贡閾忓酣宕板Δ鍛厱闁瑰濮风壕鍏笺亜閺嶃劎鈯曠紒鈧崘顔界厸濠㈣泛锕︾粔娲煛鐏炲墽銆掗柍褜鍓ㄧ紞鍡涘磻閸涱垯鐒婃い鎾跺枂娴滄粍銇勮箛鎾愁仼闁哄棴绲介埞鎴﹀灳瀹曞洤鐓熼悗瑙勬礀瀹曨剝鐏冮梺閫炲苯澧い顓炴喘楠炲鏁傜憴锝嗗缂傚倷绀侀鍡涱敄濞嗘挸纾块柟鎵閻撴瑧绱掔€ｎ亞浠㈤柍閿嬫⒐娣囧﹪宕ｆ径濠傤潚濡ょ姷鍋為敃銏ょ嵁閸ャ劍濯撮柛娑橈工閳ь剦鍨跺缁樻媴閸涘﹤鏆堢紓渚囧枛閻倸鐣烽鐐茬闁芥ê顦宠婵＄偑鍊栭崝蹇涘箠閿熺姴绫嶉柛顐ゅ枎娴滃綊姊婚崒姘卞缂佸鍔楅崚鎺楀醇閺囩啿鎷洪梺鍛婄缚閸庡崬鈻嶈箛娑欑厱閻庯綆浜跺Ο鈧梺璇″枟閿曘垽鐛幒鎳虫梹鎷呴崫鍕闂傚倷鑳剁划顖炴晪閻庢鍠栨晶搴ｅ垝濮樿泛閿ゆ俊銈勭閳ь剙鐖奸悡顐﹀炊閵婏腹鎷婚梺鐟板暱閹虫劗妲愰幒妤婃晪闁糕剝鐟цⅵ闂備浇顕栭崰妤呮偡閳哄懎绠栨繝濠傚悩閻斿吋鍋傞幖杈剧磿椤旀垿姊婚崒娆掑厡闁硅櫕鎹囧畷銉р偓锝庡枛缁犳氨鈧厜鍋撻柛鏇ㄥ亜閻庮參鎮楃憴鍕婵炲眰鍔戦幆宀勫箻缂佹鍘介梺闈涚箳婵敻宕悙鐑樼厽闁规儳鐡ㄧ粈瀣煙椤旂瓔娈滈柡浣瑰姈閹柨鈹戦崼銏℃櫒濠碉紕鍋戦崐鏇灻瑰璺哄偍濞寸姴顑呮闂佸憡娲﹂崹浼达綖閸涘瓨鐓冮柍杞扮閺嗘瑧鐥幆褍鏆遍摶鏍煟濮椻偓濞佳勭閿斿浜滄い鎾跺仦瀹告繃淇婇崣澶婂妤犵偞甯￠獮濠傜暦閸パ勭亪闂佸搫琚崝搴ㄥ焵椤掑﹦绉靛ù婊嗗煐鐎靛ジ寮介銈囷紳闂佺鏈懝楣冨焵椤掍焦鍊愮€规洘鍔欓獮鏍ㄦ媴閸濄儻绱梻浣虹帛閸ㄥ吋鎱ㄩ妶澶婄９闁秆勵殕閻撱儵鏌￠崶鈺佷粶闁逞屽墯閹倿骞冮敓鐘冲亜闁稿繗鍋愰崢顏堟⒑閸撴彃浜濈紒璇茬Т铻ｉ柛顐犲劜閻撴稑霉閿濆浂鐒鹃柍褜鍓欏鈥愁嚕鐠囨祴妲堥柕蹇婃櫆閺呮繈姊洪幐搴ｇ畵婵炲眰鍔戦幃鐐附閸涘ň鎷洪梺鍛婄箓鐎氼垳鈧矮鍗抽弻锝呂旀担鐟扮濡炪値鍋勭换鎰弲濡炪倕绻愮€氼厼鐣靛鍜佹富闁靛牆妫欑€垫瑩鏌涘☉鍗炲箹濮濆洭姊婚崒娆愮グ妞ゆ泦鍛亾濞戞帗娅囩紒顔界懇瀹曞ジ濡烽妷褎鐓ｉ梻浣虹帛椤牏浜稿▎鎾虫辈闁挎洖鍊归悡銉︾節闂堟稒顥犲褋鍨介弻锝夊Χ閸屾矮澹曢梻鍌氬€烽懗鍫曞箠閹惧箍浜归柣鎰暩閻棗霉閿濆牊顏犵紒鈧繝鍌楁斀闁绘ê寮堕幖鎰磼閻樺磭澧甸柡灞界У濞碱亪骞嶉璺ㄧ崶闂備礁鎽滈崰搴ㄥ箠韫囨稑桅闁告洦鍨扮猾宥夋煕鐏炴崘澹樺ù鐘成戠换婵嬪閵忊€虫畬濡炪倧绠撳褔锝炶箛鏇犵＜婵☆垵顕ч鎾绘⒑閹呯闁硅櫕鎸剧划顓㈡晸閻樻枼鎷洪梺闈╁瘜閸欏酣鎮為悙顑句簻妞ゆ挾濮撮崢瀛橆殽閻愭彃鏆ｉ柟顔界矒閹稿﹥寰勭仦钘夌闂傚倷绀侀幉鈩冪瑹濡ゅ懎鐭楅柍褜鍓熼弻鐔兼嚍閵夛妇顦板┑顔硷攻濡炶棄顕ｉ鍕ㄩ柨鏃傛櫕瑜板懘姊绘担鍛婃喐闁革絻鍎靛畷鎴﹀幢濡炵粯鐎婚梺闈涚箞閸婃牠宕愰柨瀣闁哄鍩堥崕鎰版煛閸屾浜鹃梻鍌氬€烽懗鍓佸垝椤栨繃鎳岄柣鐔哥矋濠㈡﹢宕弶鎴殨闁告劖绁撮弸搴ｂ偓鐢靛缁诲倻绱炴繝鍥х畺闁冲搫鎳忛幆鐐淬亜閹扳晛鐏╅柡鈧鐔虹瘈婵炲牆鐏濋弸娑㈡煥閺囨ê濡奸柍璇茬Ч閺佹劙宕堕…鎴炵稐闂備礁婀遍崕銈夊吹閿曞倹鍋勯弶鐐村閸撱劑姊洪崫鍕檨閻忕偛澧界粔鑲╃磽閸屾艾鈧悂宕愰幖浣哥９濡炲瀛╅浠嬫煥閻斿搫孝缂佹劖顨婇弻鈥愁吋鎼达絼姹楅梺鑽ゅ枑婢瑰棝寮崇€ｎ喗鐓欓梺鍨儐椤ユ牜绱撳鍕獢闁绘侗鍣ｅ畷鍫曨敆閳ь剛鐥閹绗熼婊冨弗闂佸摜鍋炲钘夘潖缂佹ɑ濯寸紒娑橆儐缂嶅牓姊虹粙鍨劉濠电偛锕妴浣割潩妫版繃鏅ｉ梺缁橆焽閺佹悂鎮＄€ｎ喗鈷戦柛鎾村絻娴滄繃绻涢崣澶涜€块柛鈺傜洴楠炲鏁傜憴锝嗗闂備礁澹婇崑鍡涘窗瀹ュ鍤堥悷娆忓缁犻箖鏌熺€涙鎳冮柣蹇婃櫇閳ь剛鎳撻幉锛勬崲閸愵喖桅闁告洦鍨伴崘鈧梺闈浤涢埀顒佹叏閸モ晝纾藉ù锝堫潐閺嬪嫰鏌涘Δ鈧崯鍧楋綖韫囨洜纾兼俊顖濐嚙椤庢挾绱撴担鍦槈妞ゆ垵鎳庨埢鎾活敇閻愨晜鏂€濡炪倖姊归弸濠氬礂椤掑倻纾奸柣妯挎珪瀹曞矂鏌℃担鐟板闁诡喗鐟╁鍫曞箣閻樼數宓佹繝鐢靛Х閺佹悂宕戦悙鍨殰闁圭儤顨呯粻瑙勩亜閹版儼顓虹紓宥嗙墬缁绘繃绻濋崒婊冾暫闂佺粯甯掗悘姘跺Φ閸曨垰绠抽柟瀛樼箥娴犲ジ寮堕埡鍌滅疄婵﹥妞藉畷銊︾節閸屾凹娼婇梻浣告惈閹冲繒鎹㈤崟顐殨鐟滄棃宕洪埀顒併亜閹烘垵顏柍閿嬪灩缁辨帞鈧綆鍋勯婊勭節閳ь剟骞嶉鍓э紲濡炪倖妫侀崑鎰摥闂備礁纾划顖炲箰婵犳艾围闁挎繂顦粈鍐煃閸︻厼浜鹃悗姘冲亹缁辨捇宕掑顑藉亾閻戣姤鍊块柨鏇氱劍閹冲矂姊虹拠鑼婵炲瓨宀稿畷銏ゅ礈瑜庨～鏇㈡煙閻戞﹩娈旈幆鐔兼⒑闂堟冻绱￠柛鎰典簻楠炴姊虹拠鎻掝劉妞ゆ梹鐗犲畷浼村箻鐠囪尙顦悗骞垮劚濞层劑鎯屾径鎰厵闁绘垶蓱閻撴盯鏌涚€ｎ偅宕岄柡浣瑰姈閹棃鍨鹃懠顒佹櫦闂傚倷绀侀幉锟犳晝閵忥紕顩查悹杞拌濞兼牗绻涘顔荤盎婵☆偅锕㈤弻鏇熷緞濞戙垺顎嶉梺缁樼箖濡啫顫忓ú顏勪紶闁靛鍎涢敐澶嬬厽闁冲搫锕ら悘锔筋殽閻愯韬鐐搭焽閹风娀寮婚妷锔芥當濠电姴鐥夐弶搴撳亾閹剧粯鍤勯柛顐ｆ礀閸屻劑鏌涘☉姗堝姛缂佺娀绠栭弻鐔煎礈瑜滃Λ搴☆熆鐟欏媶鎴犳崲濞戞碍瀚氱憸蹇曠矓椤曗偓閺岋紕浠﹂懞銉ユ灎濡炪們鍨虹粙鎴﹀煡婢跺ň鏋庨煫鍥ㄦ尫缁辩喐绻濋悽闈浶ラ柡浣告啞閹便劎鈧數纭堕崑鎾愁潩閻撳孩鐏撻梺杞扮贰閸犳牠鍩ユ径鎰潊闁挎稑瀚獮宥夋煟鎼达絾鍤€閻庢凹鍠楅弲璺何旈崨顓㈡７婵炲濮撮鍡涙偂濞嗘挻鐓曟繛鍡楁禋濡插綊鎮樿箛銉ヮ洭闁逞屽墲椤煤濠婂牆绐楅柡宥庡幑閳ь兛绶氬鎾閻樺吀绱滈梻浣瑰劤濞存岸宕戦崨鏉戠柈闁绘柨鍚嬮埛鎺楁煕鐏炴崘澹橀柍褜鍓氶幃鍌氱暦閹扮増鍊婚柤鎭掑劚濞堟垿姊洪崜鎻掍簼婵炴彃绉归崺鈧い鎺戯功閻ｇ數鈧娲栭妶鎼佸春濡ゅ懎鐓涘ù锝呭槻椤ユ碍绻濋悽闈涗沪闁搞劌澧庨弫顔嘉旈埀顒勫煝瀹ュ骞㈡繛鍡樺灩閿涙粎绱撻崒娆戝妽妞ゎ厼娲崺濠囧即閻樼數锛滅紓鍌欑劍椤洨绮婚悙纰樺亾鐟欏嫭绀冮悽顖涘浮閳ワ箓濡搁埡浣侯槹濡炪倖甯掗ˇ顖炲疾椤撱垺鈷掗柛灞捐壘閳ь剛鍏橀幊妤呭醇閺囨ǚ鍋撴担鍦瘈闁搞儜鍜佸斀婵＄偑鍊曠换鎰版偋婵犲洤鐓曢柡鍐ㄧ墛閻撴洟鏌￠崶銉ュ闁诲繒濮烽惀顏堝箚瑜滈悡濂告煛鐏炲墽娲寸€殿喗鎸虫俊鎼佸Ψ瑜岄悽濠氭⒒娴ｈ櫣甯涢柟姝岊嚙鐓ら柣鏂垮悑閸嬪倹銇勯幇鍓佺暠闁绘劕锕弻鏇熺節韫囨搩娲銈忚礋閸庣敻寮婚敐澶婎潊闁宠桨鑳舵禒鏉戔攽閻愬樊妲归柣鈺婂灠閿曘垺绗熼埀顒€顫忛搹鍦＜婵妫涢崝绋款渻閵堝棙鐓ラ柨鏇ㄤ邯閻涱喗寰勯幇顓炩偓閿嬨亜閹哄秶顦︾€殿喗瀵х换婵嬫偨闂堟刀銏ゆ煙閸愯尙绠绘い銏℃閹晠鎮介悽纰夌床闂佸搫顦悧鍕礉瀹€鈧划顓㈠箳濡や焦鍤夐梺鎸庣箓椤︿即鎮￠悩娴嬫斀妞ゆ棁妫勬慨鍥煃瑜滈崜姘洪弽顓ф晪闁挎繂顦粻顕€鏌ら幁鎺戝姉闁归绮换娑欐綇閸撗冾嚤闁荤姭鍋撻柨鏇炲€哥紒鈺呮煛婢跺﹦姘ㄩ柡鈧懞銉ｄ簻闁哄倹瀵ч幆鍫ユ煃瑜滈崜姘躲€冩繝鍌滄殾婵娉涚粻铏繆閵堝倸浜剧紓浣哄Т椤兘骞冭ぐ鎺戠倞鐟滃秶鐥娣囧﹤顔忛鐓庘拫濠殿喖锕ュ钘壩涢崘銊㈡婵浜弶浠嬫⒒娴ｄ警鐒鹃柨鏇樺劚鐓ゆ繝濠傜墛閸嬫牠鏌熼鍡楄嫰閹垶绻濋姀锝嗙【妞ゆ垵娲畷銏ゅ础閻戝棙瀵岄梺闈涚墕濡鎱ㄩ崒鐐寸厱濠电姴鍟粈瀣偓娈垮枟閹倸顕ｉ鈧畷濂告偄閸濆嫬绠炲┑鐘殿暯濡插懘宕瑰畷鍥у灊妞ゆ牗姘ㄩ弳锔锯偓鍏夊亾闁告洦鍓涢崢闈涱渻閵堝棙鈷掗柛妯犲吘锝囩磼濡晲绨诲銈嗘尰缁本鎱ㄩ崒婧惧亾鐟欏嫭绀堥柛鐘崇墵閵嗕礁顫滈埀顒勫箖閳哄懏顥堟繛鎴烆焾缁剁喖姊婚崒娆愮グ妞ゆ泦鍐炬僵闁挎洖鍋婄紞鏍ь熆鐠鸿　濮囬柛婵嗗珋閻斿吋鍋傞幖杈剧磿娴滀即姊绘担绛嬫綈鐎规洘锕㈤、姘愁槾缂侇喖顭峰浠嬵敇閻斿搫甯鹃梻濠庡亜濞层倝鏁冮妷鈺嬬稏濠电姴鍟╃换鍡涙煙缂佹ê绗х紒澶屽劋椤ㄣ儵鎮欑€电鈪归柤鎸庡姈閵囧嫰骞掗崱妞惧闂備浇顕уù姘濠靛桅闁告洦鍨扮猾宥夋煃瑜滈崜娆戝弲闂佺粯鏌ㄩ〃搴☆焽閺嶎偆纾藉ù锝堝亗閹寸偛鍨旈柟缁㈠枟閻撶喖鏌ｉ弮鍌氬付濞存粈鍗抽弻娑㈠Χ閸滀礁鍓崇紓浣介哺閹稿骞忛崨顖滈┏閻庯綆浜濋鍕⒒娴ｄ警鐒鹃柨鏇樺姂瀹曟洜鎷犻崣鍌涚洴閹垺绺芥径瀣槣闂備線娼ч悧鍡椢涘☉娆愭珷妞ゆ帒鍊诲Λ顖炴煛婢跺孩纭堕弫鍫ユ倵濞堝灝鏋涢柛鐔锋健閳ワ箓濡搁埡渚€鍞堕梺缁樻煥瀵墎鈧矮绮欏缁樻媴娓氼垳鍔搁梺鍝勭墱閸撶喖骞冮悿顖ｆЬ缂備緡鍣紞浣割嚕椤曗偓閸┾偓妞ゆ帒鍊瑰畷鍙夌箾閹寸偟鎳勫┑顖涙尦閺屾盯骞囬鈧痪褔鏌ｉ敂璺ㄧ煓闁哄本娲樼换娑㈡倷椤掍胶褰呴梻浣虹帛鐢帡鎮樺璺何﹂柛鏇ㄥ灠缁犳娊鏌涢埄鍐︿沪濠㈣娲熷缁樻媴閸濄儲鐎銈庡亜椤﹂潧鐣疯ぐ鎺戦敜婵°倐鍋撻柛銊ュ€歌灃闁挎繂鎳庨弳鐐烘煙椤栨粌浠﹂柕鍥у楠炲洭宕滄担鑽锋垿姊虹粙鍖″姛闁稿繑锚椤繒绱掑Ο璇差€撻梺鍛婄缚閸庤崵妲愰悙鐢电＝濞撴艾娲ゅ▍姗€鏌涢妸銉у煟闁绘侗鍣ｉ獮瀣晝閳ь剟鎮欐繝鍥ㄧ厪濠电偛鐏濋埀顒侇殘缁顫濋懜纰樻嫼闂佺绻愰崥瀣磹閹邦厾绠惧ù锝呭暱閹冲繘顢曟禒瀣厽闁归偊鍠栭崝瀣煕婵犲嫭鏆柡灞诲妼閳藉螣妤﹀灝鐓橀梺璇插閸戝綊宕滈悢绗衡偓渚€寮崶銉ゆ睏闂佸湱鍎ら幐鎾箯婵犳碍鈷戠紒瀣濠€浼存煟閻旀繂娉氶崶顒佹櫇闁稿本绋撻崢鐢告煟閻樺弶鍘傞柛娑卞灲缁辩數绱撻崒娆戣窗闁哥姵顨婇幃鐑藉煛閸涱垰绁﹂柣搴秵閸犳寮插鍫熺厾闁诡厽甯掗崝婊堟煟濠靛洨澧垫慨濠勭帛閹峰懘鎮烽柇锕€娈濇繝鐢靛仜瀵爼鎮ч悩鑼殾闁圭増婢樻导鐘绘煏婢诡垰鍊婚悷婵嬫⒒娴ｈ櫣甯涙い顓炴川閸掓帡顢涢悙鏉戜簵濠电偛妫欓幐濠氭偂濞嗘劗绠鹃柛顐ｇ箘娴犮垽鏌＄€ｎ偆鈯曢柕鍥у閺佹劙宕ㄩ顫垝闂備礁鎼惌澶岀礊娓氣偓閻涱喖螣鐏忔牕浜炬繛鎴炵懐閻掕姤銇勯敂鍝勫婵﹥妞藉Λ鍐ㄢ槈濞嗘劖鍊烽梺璇插閻噣宕￠幎钘壩ュù锝呭濞笺劑鏌嶈閸撶喖鐛崘顔碱潊闁宠棄妫欐晥闂佸湱鍘ч悺銊ф崲閸愩剮鐔哥節閸ャ劉鎷婚梺绋挎湰閻燂妇绮婇悧鍫涗簻闁哄洤妫楃€氬嘲鈻撴禒瀣彄闁搞儯鍔嶇粈鍐┿亜椤愶絾绀嬮柡宀嬬節瀹曞爼鍩℃担鍥风稻閵囧嫰顢曢敐鍡欘槹闂佸搫鐬奸崰鏍箖濠婂喚娼ㄩ柛鈩冾焽閺嗐儳绱撴担鍝勪壕闁稿孩濞婂畷銉р偓锝庡枛缁犵偤鏌曟繛鍨壔闁绘柨鍚嬮崵鎺楁煏閸繃顥戦柡瀣墦閺岋綁鎮㈤崫銉х厐闂備礁搴滅紞浣逛繆閹绢喖绀冩い鏂挎閵娾晜鐓冮柛婵嗗閳ь剚鎮傞崺鈧い鎺戝€搁崢鎾煛鐏炵澧茬€垫澘瀚埀顒婄秵娴滅偞绂掓總鍛娾拺闁煎鍊曢弸鍌炴煕閺冣偓閸ㄥ灝顕ｉ弰蹇ｆЬ缂備浇椴哥敮鎺曠亽闂佺粯鎸哥花鍫曞触閸岀偞鈷掗柛灞剧閹兼劖銇勯敂鐐毈鐎殿喖顭锋俊鎼佸Ψ閵忊剝鏉搁梻浣虹《閸撴繈鎮烽妷鈺佺厱闁割偅绺鹃弨浠嬫煟閹邦厼绲婚柟顔藉灴閺屾盯寮埀顒勬偡閳轰緡鍤曞┑鐘崇閺呮煡鏌涘☉鍙樼凹闁哄倵鍋撻梻鍌欑缂嶅﹪宕戞繝鍥х婵炴垶淇烘慨鎶芥煠濞村娅囩痪鎹愭闇夐柨婵嗙墛椤忕娀鎮介娑氥€掔紒杈ㄥ笧閹风娀骞撻幒鍡椾壕闁秆勵殔閺勩儵鏌曡箛瀣偓鏇犵不婵犳碍鍋ｉ柛銉ｅ妼缁插鏌ｆ惔顔煎箹妞ゎ亜鍟存俊鍫曞幢濡攱瀚介梻浣告惈閹峰宕戦崨顖滅焿鐎广儱顦柋鍥煛閸モ晛鏆遍柟椋庣帛缁绘稒娼忛崜褎鍋ч梺纭呮珪閹瑰洭銆佸顒夌叆闁告洦鍘鹃鏇㈡⒑閸︻厾甯涢悽顖滃仦閺呫儵鏌ｆ惔銏╁晱闁哥姵顨婇幃锟犳晸閻樿尙鐣洪梺鍐叉惈閹冲繘宕甸幋鐐簻闁瑰搫绉堕崝宥嗐亜閺冣偓濞茬喎顫忕紒妯诲濞撴凹鍨遍弫顖炴⒑鐟欏嫭銇熷ù婊呭仧閸掓帗绻濆顒傤吅闂佹寧姊归崕宕囩矈閿曞倹鈷戦梻鍫熺洴閻涙粎绱掓潏銊︾缂侇喚绮妶锝夊礃閳哄啫骞堥梻浣规灱閺呮盯宕㈡ィ鍐炬晜闁割偆鍠庨埀顒€鐖奸弻宥夊传閸曨剙娅ら梺缁樻尵閸犳牠寮婚悢鐓庣畾鐟滃繘骞楅悩纰樺亾鐟欏嫭绀€闁哄牜鍓熼獮鍫ュΩ閿斿墽鐦堥梺鍛婁緱閸ｎ喗绂掗埡浣叉斀闁绘劖娼欓悘鈺呮煛娴ｇ瓔鍤欓柣锝囧厴婵℃悂鍩℃繝鍐╂珦闂備胶顭堢换鎰板Χ閹间礁鏋佹い蹇撶墛閳锋帡鏌涚仦鎹愬闁逞屽墯閹倸鐣烽幇鏉夸紶闁靛鍨规禍鐐叏濡厧甯跺褌鍗抽弻宥堫檨闁告挻宀搁幆宀勵敋閳ь剙鐣烽敓鐘茬闁伙絽鑻粊锕傛⒑閸涘﹤濮﹂柛鐘愁殜瀵煡骞栨担鍦幗濠碘槅鍨伴幖顐﹀汲閸楃伝鐟邦煥閸曨厾鐓夊┑顔硷攻濡炶棄鐣烽妸锔剧瘈闁告洦鍘剧粣妤呮⒒娴ｄ警鐒鹃悗娑掓櫆缁绘稒绻濋崶褏鐣炬繛鎾村焹閸嬫挾鈧娲栭妶鎼佸箖閵忋倖鎯為柛锔诲幗椤矂姊婚崒娆戝妽闁活亜缍婂畷褰掓寠婢舵鍔烽悷婊冪Ч閹椽顢橀姀鈾€鎷绘繛杈剧导鐠€锕傛倿妤ｅ啯鐓ラ柡鍥崝锔筋殽閻愭彃鏆ｇ€规洘甯￠幃娆擃敂娴ｉ晲澹曟繛鎾村焹閸嬫挾鈧鍣崳锝呯暦婵傚壊鏁冮柨婵嗘閻濇洟姊婚崒娆掑厡缁绢厼鐖煎畷婊冣攽鐎ｎ偄浠悷婊勬瀵偄顓奸崪浣哄弳闂佸壊鍋嗛崰鎾诲储娴犲鈷戠紓浣光棨椤忓嫷鍤曢柛顐ｆ礀缁犳岸鏌涢鐘插姕闁绘挻鐟ч惀顏堝级閸喛鍩炴繛瀛樼矌閸嬨倝寮婚敐澶娢ㄦい鏃傜帛閹癸絽顪冮妶蹇曠暠妞ゆ洦鍘惧Σ鎰板箳閹惧绉堕梺闈涱焾閸庢娊顢栭崒婊呯＝濞达絼绮欓崫娲偨椤栨稑绗╅柣蹇斿浮濮婃椽宕楅懖鈹垮仦闂佸搫鎳忕换鍫濐嚕閼哥數顩烽悗锝庡亐閹风粯绻涙潏鍓хК婵炲拑缍佹俊瀛樼節閸ャ劎鍘搁梺绋挎湰閻熝呯玻閺冨倵鍋撶憴鍕闁搞劌娼￠悰顔碱潨閳ь剟鐛崶銊﹀闁荤喐澹嗗Σ锝夋⒒閸屾瑧绐旀繛浣冲洦鍋嬮柛鈩冦亗濞戞鏃堝礃椤忓棛鏆ラ梻浣告贡閸庛倝銆冮崱娑樼９闁割煈鍋呴崣蹇斾繆椤栨碍鎯堥柤绋跨秺閺屾稑螣娓氼垰娈堕梺閫炲苯澧い鏃€鐗犲畷鎶筋敋閳ь剙鐣烽幋鐐电瘈闁稿本绮嶅▓楣冩⒑閸︻厼鍔嬫い銊ユ瀹曟劙鎮滈懞銉モ偓鐢告煟閵忊槅鍟忛柣鎺斿亾椤ㄣ儵鎮欓懠顒€顤€婵烇絽娲ら敃顏堝箖濞嗘搩鏁傞柛鏇樺妼娴滈箖鏌″搴″箹缂佲偓婢跺本鍠愰煫鍥ㄦ惄閸ゆ鈹戦悩鎻掝仾鐎规洖顦甸弻鏇熺箾瑜嶉崐濠氭偡濠靛鈷掑ù锝囩摂濞兼劙鏌涙惔銏犫枙闁诡喗锕㈠畷濂稿Ψ閵壯嶇幢闂備浇顫夊畷姗€宕洪弽顓炵獥闁糕剝绋掗悡鏇㈡煛閸ャ儱濡煎褜鍠氶惀顏堝级鐠恒剱銏ゆ煃鐟欏嫬鐏撮柛鈹垮劦瀹曞崬顪冮崜褍鍤紓鍌氬€峰ù鍥敋瑜斿畷鎰板锤濡や焦娅滈梺缁樺姇婢у酣鎮块埀顒勬⒑閻熸澘缍栭柣鎺炵畱椤啯绂掔€ｃ劉鍋撴笟鈧顕€宕煎┑鍫Ч婵＄偑鍊栧濠氬磻閹惧墎纾煎ù锝堟閻撴劕菐閸パ嶈含闁诡喗鐟╅、鏃堝礋閵娿儰澹曢梺鍝勭▉閸樿偐绮绘导瀛樼厵缂備降鍨归弸娑氱磼閳ь剟宕奸悢铏圭槇闂傚倸鐗婃笟妤呭磿濞戙垺鐓涘ù锝夘棑閸斿秴菐閸パ嶈含濠碘€崇埣瀹曘劑顢欓崗纰变画闂傚倷鐒︽繛濠囧绩闁秴鍨傞柛褎顨呴拑鐔哥箾閹寸們姘跺绩娴犲鐓曢柡鍥ュ妼娴滄粌鈹戦濂稿弰闁哄备鈧剚鍚嬪ù锝嗗絻娴滈箖鏌熸０浣哄妽閻庨潧鐭傚娲濞戞艾顣洪梺鍝ュ櫏閸嬪懏绌辨繝鍥х闂傚倸顕粻姘渻閵堝棗濮х紒鎻掓健婵℃挳骞掑Δ浣哄幈闂佸湱鍎ら幐鍝ョ箔瑜旈弻宥堫檨闁告挶鍔庣槐鐐哄幢濞戞鐛ラ梺鍝勭▉閸嬪棙绋夊澶嬬厵闁诡垱婢樿闂佺粯鎸婚悷鈺呭蓟閻斿搫鏋堥柛妤冨仜缁犵懓螖閻橀潧浠︽い銊ョ墦閸┾偓妞ゆ帒鍊告禒顖炴煕婵犲啰澧い顏勫暣閹稿﹥寰勫Ο鑽ょ▉婵犵數鍋涘Ο濠冪濠靛鍊垮┑鐘崇閻撶喖鏌熼柇锕€鐏犻柦鍕偢閹顫濋鐔哄嚒濡炪値鍙€閸庡藝閺屻儲鐓熼幒鎶藉礉閹达箑违闁告劦鍠栧敮闂佸啿鎼崐鎼佸焵椤掑倸鍘撮柡宀€鍠撶槐鎺懳熼搹鍦嚃婵犵數鍋涢悧鍡涒€﹀畡閭︽綎闁惧繗顫夌€氭岸鏌嶉妷銊︾彧闁诲繐绉剁槐鎾寸瑹閸パ勭亶闂佸湱鎳撳ú顓㈡偘椤曗偓楠炲洭顢橀悩鐢垫闂備礁鎲￠崝鎴﹀礉鎼达絿鐜婚柣鎰嚟缁♀偓闂佹眹鍨藉褍鐡梻浣侯焾閿曘倝鈥﹂柨瀣╃箚闁割偅娲﹂弫濠囨倶韫囨梻澧柡鍌楀亾闂傚倷鑳剁划顖濇懌闂佸憡鎸诲畝绋跨暦椤栨繄鐤€婵炴垶鐟ч崢閬嶆⒑缂佹〞鎴﹀礈濮橆兘鏋旀繝濠傜墛閻撴稑霉閿濆浂鐒鹃柡鍡到閳规垿顢欓悷棰佸闂傚倷绶氬褏鎹㈤崱娑樼劦妞ゆ巻鍋撻柛鐔锋健閻涱噣骞嬮悩鐢碉紳闂佺鏈悷褔藝閿斿浜滈柟瀛樼箘婢э附銇勯姀鈥冲摵妤犵偛閰ｉ幊鐐哄Ψ閿旂晫褰告繝鐢靛О閸ㄥジ宕洪弽顒佹噷闂備礁鎼幏瀣椤忓嫷娼栨繛宸簼閻掑鏌ｉ幇顖氳敿閻庢碍婢橀…鑳檨闁哥姵顨婃俊鐢稿礋椤栵絾鏅濋梺闈涚箞閸ㄥ顢欓崶顒佺厽闁规儳宕埀顒佺墵婵＄敻宕熼鍓ф澑闂佸湱鍋撳娆忊枍閿濆棛绠鹃悗鐢殿焾椤庡矂鏌涘▎蹇撴殭妞ゎ偄绻掔槐鎺懳熼懖鈺傚殞闂備焦鎮堕崕婊堝礃瑜忕粈瀣⒒閸屾艾鈧悂宕愰崫銉㈠亾濮樼厧澧伴柍褜鍓氶崙褰掑窗濮橆儵锝夊箛閻楀牆鈧兘鏌涘▎蹇撯偓鐟拔涢崘銊ф殾闁靛ň鏅╅弫濠囨偡濞嗗繐顏╂い蹇撶秺濮婂宕掑▎鎺戝帯濡炪們鍨归敃顏勭暦閹达箑绠涢柡澶庢硶閿涙稑鈹戦悙鏉戠仸闁荤噦绠撳畷锝堢疀濞戞瑧鍘撻悷婊勭矒瀹曟粌鈻庨幘宕囧幋闂佺鎻梽鍕磹閻戣姤鐓曟繛鍡楁禋濡叉悂鏌ｅ┑鍥ㄢ拻缂佽鲸鎸婚幏鍛存偡閹殿喚銈锋繝鐢靛仜閻ㄧ兘鍩€椤掆偓绾绢參寮抽敂鑺ュ弿婵☆垱瀵х涵鍓х磼閻樺啿鈻曢柡宀€鍠撻埀顒佺⊕钃遍柍閿嬪姍閺岋絾鎯旈埥鍡欏悑濠殿喖锕紓姘跺Φ閹版澘绠抽柟瀛樼矊閺嬪牓姊绘担鍛婂暈闁规瓕宕电划娆撳箻鐠哄搫鐏婇梺鎸庣箓椤︿即宕愰悜鑺ョ厽闁瑰鍊戝璺虹婵炲樊浜濋崑鈩冪節婵犲倹鍣规い锝呫偢閹粙顢涘☉妯肩懖缂備礁鍊哥粔鐢碘偓浣冨亹閳ь剚绋掗…鍥储闁秵鈷戦悷娆忓閸斻倖銇勯弴銊ュ箹閻撱倝鎮楅悽鐢点€婇柛瀣尵閹叉挳宕熼鍌ゆО缂傚倷娴囬褔鎮ч幘鎰佸殨妞ゆ劧绠戠粈鍐┿亜閺冨洤浜归柛鏃撶畱椤啴濡堕崱妤冪懆闁诲孩鐨滈崶褏鍔﹀銈嗗笂閻掞箓藟閸懇鍋撶憴鍕闁挎洏鍨介妴浣糕枎閹惧啿绨ユ繝銏ｎ嚃閸ㄦ澘煤閿曞倹鍋傞柡鍥ュ灪閻撳啴鏌嶆潪鎵槮闁哄鍊栫换娑㈠醇閻曞倽鈧潡鏌″畝瀣М闁诡喓鍨藉鍫曞箣濠垫劖缍嗗┑鐘愁問閸犳牠鏁冮妸銉㈡瀺闁挎繂娲ら崹婵囩箾閸℃ɑ灏紒鈧畝鍕厓闁靛鍎辩敮鐘电磼閹插绋诲ǎ鍥э躬閹瑩顢旈崟銊ヤ壕闁靛牆顦崒銊ノ旈敐鍛殭缂佲偓閸屾稒鍙忔俊鐐额嚙娴滈箖姊虹紒妯圭繁闁革綇绲介悾鐑藉础閻愬秵妫冨畷姗€鍩￠崒婊勬闂傚倸鍊风粈渚€骞夐垾瓒佹椽鏁冮崒姘憋紱闂佺硶鍓濇笟妤呭极婵犲洦鐓欓柣鎴烇供濞堟洟鏌嶉柨瀣伌闁哄瞼鍠栭幊鏍煛娴ｉ鎹曞┑鐘殿暜缁辨洟寮查銈嗩潟闁圭儤鏌￠崑鎾绘晲鎼粹€茬盎闂佽楠忔俊鍥╂閹烘纾兼慨妯荤樂瑜旈弻鐔碱敊閻ｅ本鍣板銈冨灪椤ㄥ棗顕ラ崟顓涘亾閿濆娑ч柡鍜佸墴濮婂宕掑▎鎺戝帯缂備緡鍣崹璺虹暦濠靛柈鐔兼⒒鐎电澧炬繝鐢靛仜濡瑩宕濆Δ鍛偓鍛存倻閼恒儳鍘棅顐㈡搐椤戝懘鍩€椤掍胶澧甸柟顕嗙節瀵挳濮€閿涘嫬骞愰梻浣告啞閸斞呭緤閼恒儳顩查柟顖嗏偓閺€鑺ャ亜閺冨浂娼℃繝濠傜墕缁€澶愬箹缁懓鐏抽柨婵嗩槸缁犳盯鏌℃径搴㈢《妞ゆ柨锕娲传閸曨偅娈梺绋匡工椤兘寮鍜佺叆闁告劧绲鹃弬鈧梻浣哥枃濡嫬螞濡ゅ懏鍊堕柕澶涘缁犻箖鏌涘鍐ㄦ殶缂佸鍠楅妵鍕閿涘嫬鈷岄悗瑙勬礃鐢帡鈥﹂妸鈺佸窛妞ゆ牓鍊楅梻顖涚節閻㈤潧浠﹂柟绋款煼閹虫繈骞嗛‖鈩冩そ婵¤埖寰勬繝鍌氭婵犵數鍋為崹顖炲垂濞差亝鍋傞柣鏃堟櫜缁诲棝鏌曢崼婵嗏偓鍛婄妤ｅ啯鈷戦柟绋垮绾炬悂鏌涙繝鍐疄闁靛棔绀侀～婵堟崉娴ｆ洏鍔戦弻宥嗘姜閹峰苯鍘″銈忛檮濠㈡﹢鈥旈崘顔嘉ч柛鈩冪懃椤冣攽椤旇婊堝礉閹达箑绠栭柛褎顨呴悞鍨亜閹哄秵顦风紒璇叉閺岋綁骞囬崗鍝ョ泿闂侀€炲苯澧柣妤冨█閻涱噣骞囬悧鍫濃偓閿嬨亜閹哄秶顦︾€殿喖娼″娲捶椤撯剝顎楅梺鍝ュУ閼归箖鎮?idea闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃闁硅櫕鎹囬垾鏃堝礃椤忎礁浜鹃柨婵嗙凹缁ㄧ粯銇勯幒瀣仾闁靛洤瀚伴獮鍥敍濮ｆ寧鎹囬弻鐔哥瑹閸喖顬堝銈庡亝缁挸鐣烽崡鐐嶆棃鍩€椤掑嫬鐓曢柟鐑橆殕閳锋垹绱撴担濮戭亞绮閺岋繝宕担闀愬枈濡ょ姷鍋涢ˇ杈╁垝濞嗗繆鏋庨柟顖嗗嫬鈧垶姊绘担绋款棌闁稿甯掗…鍧楀焵椤掑倻纾介柛鎰ㄦ櫆缁€瀣叏婵犲偆鐓肩€规洘甯掗埢搴ㄥ箣椤撶啘婊堟⒒娴ｅ憡璐￠柍宄扮墦瀹曟垶绻濋崒婊勬濡炪倖鐗滈崕鎰板极閸愵喗鐓ラ柡鍐ㄦ处椤ュ霉濠婂棝鍝虹紒缁樼箞閹粙妫冨ù韬插灪缁绘稓浠﹂崒姘ｅ亾濡や胶鐝堕柡鍤堕姹楅梺鍦劋閹搁箖宕㈤柆宥嗗仭婵犲﹤鍟撮崣鍕煏閸℃鏆ｇ€规洖宕埥澶娾枎韫囧海鏆楅梻鍌欑窔濞佳囁囬锕€鐤炬繝濠傜墛閸嬪倹绻涢幋娆忕仾闁绘挻娲熼弻鏇熷緞閸繄浠惧┑鐐叉噹閹冲酣婀侀梺缁樏壕顓㈡儗閹烘鐓涢悘鐐垫櫕鍟稿銇卞倻绐旈柡灞剧洴楠炴﹢寮堕幋婵囨嚈婵°倗濮烽崑娑㈠疮閺夋垹鏆﹂柟鐑樺焾濞尖晠鏌ｉ幘鍐差劉妞ゆ挸娼″缁樻媴閸涘﹤鏆堢紓浣割儐閸ㄥ潡寮崘顔芥櫇闁稿本绋戞禒顓㈡偡濠婂懎顣奸悽顖涱殜閹繝宕橀鍛瀾濠电姴锕ら悧鍡欑矆閸儲鐓熼柡鍌涱儥濞堢娀鏌涢妶鍡樼闁诡喖缍婂畷鍫曞Ω瑜嬮崑鐐测攽閳╁啫绲婚柣妤€锕﹂幑銏犫攽閸モ晝鐦堥梺绋挎湰缁嬫垵鈻嶈濮婃椽宕崟鍨ч梺璇″枛閸婃悂锝炶箛鎾佹椽顢旈崟顏嗙倞闂備礁鎲″ú锕傚礈濞嗘挸纾荤€广儱顦伴埛鎴︽煕濞戞﹫鏀婚柣鎾卞劦閺岋綁顢橀悙娴嬪亾閹间焦鍋╃€瑰嫭澹嬮弨浠嬫倵閿濆簼绨婚柤鏉跨仢閳规垿鍩ラ崱妤冧淮闂佺顑嗛崝娆撱€佸▎鎾冲嵆闁靛骏绱曢崢浠嬫煙閸忚偐鏆橀柛銊ヮ煼閸╁﹪寮撮悢缈犵盎濡炪倖鎸鹃崑鐐哄窗濮椻偓閺岀喖顢涘杈╀紘闂侀€炲苯澧剧紓宥呮瀹曟粌鈽夊顒夋闂佺绻掗鏇熺濠婂牊鐓涢柛鎰╁妽閹兼劗鎮鑸靛€甸悷娆忓缁€鈧梺娲诲墮閵堟悂宕洪埀顒併亜閹哄秶璐伴柛鐔风箻閺屾盯鎮╁畷鍥ㄥ垱濡炪們鍨烘穱娲囪ぐ鎺撶厱闁崇懓鐏濋崝婊呪偓鍨緲鐎氫即鐛崶顒夋晢濠㈣泛顑囩粔閬嶆⒒閸屾瑧鍔嶉柡瀣偢瀵彃鈽夐姀鐘垫焾濡炪倖鐗滈崑鐐哄磻閻斿吋鐓涢柛銉ｅ劚閻忣亪鏌嶉柨瀣伌闁哄被鍊栭幈銊╁箛椤戣棄浜鹃柡鍥╁仧閹姐儱鈹戦悩鍨毄闁稿濞€椤㈡艾顭ㄩ崨顖欑瑝闂佸湱鍎ら〃鍛攰闂備礁婀辨晶妤€顭垮Ο鑲╃焼闁告劏鏂傛禍婊堢叓閸ャ劍灏版い銉︾懅缁辨帒螖閳ь剟藝闂堟侗娼栨繛宸簻缁犳氨鎲歌箛鏇犱笉闁绘鐗忕弧鈧梺閫炲苯澧繛鐓庣箻閸┾剝绗熼崶顭戞％闂傚倷娴囨慨銈夋晪濡炪們鍎崹濂稿Φ閹版澘绠抽柟鎯х摠閻濇娊姊绘担瑙勫仩闁稿寒鍨跺畷婵堜沪鐟欙絾鐏侀柣蹇曞仜婢х晫寮ч埀顒€鈹戦悙鑼闁诲繑绻堝绋库槈閵忥紕鍘藉┑掳鍊愰崑鎾绘煥閺囥劋绨煎ǎ鍥э躬閹晫绮欑捄顭戞Ч婵＄偑鍊栭悧妤咁敋闁秴鐓涢柛娑卞枤閸橆亝绻濋姀锝呯厫闁挎岸鏌ｈ箛瀣姦闁哄本绋戦～婵嬫偂鎼存繂鏋堥梻浣筋嚃閸犳銆冮崨鏉戠厺闁规崘顕ч崹鍌涖亜閺冨倹娅曞ù婊庝簼娣囧﹪鎮欓鍕ㄥ亾閵堝鐭楅柛鎰靛枛缂佲晠寮堕崼娑樺闁崇懓绉撮埞鎴︽偐閸欏鎮欑紓浣哄Х閹虫捇婀侀梺鎸庣箓閻楀棝鍩€椤戣法鐭欏┑鈩冩倐閸╋繝宕掑鍐ㄥ闂傚倸顭崑鍕洪妶澶嬫櫇闁靛鏅紞鏍р攽閻樻彃鏆熺紒鐘荤畺閺屾稖绠涢幘铏€梺鎶芥敱閸旀妲愰幒鏃傜＜婵☆垵鍋愰悾濂告⒑閸濄儱孝闁挎洏鍊涢悘鎺戔攽閻愯泛鐨虹紒顕呭灣缁辩偞寰勯幇顓涙嫽婵炶揪缍€椤宕戦悩缁樼厱闁哄倸娼￠崣鍕偓娈垮櫘閸嬪棝骞忛悩缁樺殤妞ゆ帊鐒﹂鏇㈡⒒娴ｄ警鏀伴柟娲讳簽缁骞嬮悩鍏哥瑝濠电偞鍨崹娲偂濞戞﹩鐔嗛悹鍝勬惈椤掋垻鐥鈥崇厫闁靛洤瀚伴弫鍌滄嫚閸欏浜俊鐐€ゆ禍婊堝疮鐎涙ü绻嗛柛顐ｆ礀楠炪垺淇婇婊冨付鐎殿喖鍟块埞鎴︽偐椤愶絽顎忛梺鍛婁緱閸犳鎮甸鍛瘈闁靛骏缍嗗鎰箾閼碱剙鏋涙鐐村姈缁绘繈宕橀鍡楅獎婵犵數濞€濞佳兾涘☉姘辩煋婵炲樊浜濋悡娑樏归敐鍥ㄥ殌濠殿喖绉堕埀顒冾潐濞叉牠濡堕幖浣哥畺闁靛牆妫欐刊瀵糕偓鐟板婢ф骞夐姀銈嗏拻闁稿本鐟ч崝宥夋煟椤忓嫮绉虹€规洘妞藉畷鐔碱敍濮橆剛鈧參鏌℃径濠勫闁哄懏绻堥幆灞解枎閹惧鍘甸梺缁樺灦钃遍柍閿嬪姉閳ь剝顫夊ú鏍ь嚕閸撲焦宕叉繛鎴欏灩缁狅絾绻涢崱妤冪濞寸娀绠栧娲箹閻愭祴鍋撻弽顓炲瀭闁割偅娲栨闂佸憡娲﹂崹鎵不閹惰姤鐓曢柍鈺佸暔娴狅箑顭跨憴鍕婵﹦绮幏鍛村川婵犲啫鍓垫俊鐐€栭崹鐢稿箠閹版澘鐒垫い鎺嶈兌閳绘捇鏌￠崨顖毿ｅǎ鍥э躬閹晫绮欑捄顭戞Ч婵＄偑鍊栭悧妤呮嚌閹呮殼闁糕剝顨忓〒濠氭煏閸繃鍣界紒鐘靛娣囧﹪顢曢敐鍥剁伇闂佸湱鐡旈崑濠傤潖缂佹ɑ濯寸紒娑橆儏濞堫參姊绘担绋跨盎缂佽弓绮欓垾锕傚炊椤忓秵鈻屽┑鐘殿暯閳ь剙纾崺锝嗩殽閻愬澧柟宄版嚇瀹曨偊宕熼婊冧喊闂傚倸鍊风粈渚€骞栭銈囩煓濞撴埃鍋撶€规洩绲鹃幆鏃堝Ω閵夛妇鈧剟姊洪幖鐐插姶闁告挻宀搁幃锟犳偄閸忚偐鍘搁梺绋挎湰缁嬫垿顢氬鍫熺厱闁绘柨鎼禒閬嶆煛瀹€瀣埌闁宠鍨块獮鍥敄鐠恒劎娉块梻鍌欑閻ゅ洭锝炴径鎰瀭闁秆勵殔缁犳牠鏌嶉崫鍕櫣缂佺姵绋戦湁闁挎繂鎳忛崯鐐寸箾閸涱喚娲存慨濠勭帛閹峰懘宕ㄦ繝鍐ㄦ瀾濠电姵顔栭崰姘跺极婵犳艾违闁告劏鏅濈弧鈧梺鎼炲劀閸曨厸鍋撻鍕拺闁告稑锕ゆ慨锕傛煕閻樺磭澧甸柟顔光偓鏂ユ闁靛骏绱曢崢鍗炩攽閻愭潙鐏ョ€规洦鍓熼悰顔嘉熷Ч鍥︾盎闂佹寧妫侀褔鐛弽顓熺厓閻熸瑥瀚悘鎾煙椤旂晫鎳囩€规洩绲惧鍕熷ú缁橈紘婵犵數濮烽弫鎼佸磻濞戙垺鍋ら柕濞垮劤閺嗗棛绱掔€ｎ厽纭堕柡鍡畵閺岋綁濮€閵忊晝鍔搁梺鍛婎殕婵炲﹪寮婚敐澶婃闁割煈鍣弳銏㈢磽娴ｅ搫校鐎光偓缁嬫娼栨繛宸簼椤ュ牊绻涢幋鐐跺妞わ絾妞藉娲偡閺夋寧姣愮紓浣虹帛閿氶柣锝囧厴瀹曟鎲楁担瑙勩仢妞ゃ垺妫冨畷銊╊敍濮橆剛顔戦梻鍌氬€峰ù鍥綖婢跺﹦鏆︽俊顖濄€€閺嬫牗绻涢幋娆忕仼闁告垹濮电换娑㈠箣閻愬灚鍣藉┑鐐茬墔缁瑩寮婚敐澶婄疀妞ゆ帒顦▓鑸电節閳封偓鐏炲ジ鍋楅梺鍦劜缂嶄線鐛崶顒夋晣婵犲ň鍋撶紒銊ヮ煼濮婃椽鎮烽悧鍫熷創濠碘槅鍋呴〃鍡欑矉瀹ュ棎鍋呴柛鎰ㄦ杹閹锋椽姊绘笟鍥т簽闁稿鐩幊鐔碱敍閻愭彃鍋嶉梺姹囧灩閹诧繝鎮￠弴鐐╂斀闁绘ɑ褰冮弳鐐电磼閳ь剛鈧綆鍠楅悡鍐煏婢舵ê鐏ｉ柣锝囨暩閳ь剝顫夊ú鏍偉婵傛悶鈧礁螖閸涱厾鍔﹀銈嗗笒閸婄粯绋夊鍡欑闁瑰鍋熼幊鈧繛瀛樼矋缁捇寮婚悢琛″亾濞戞瑯鐒介柟鍐插暣閺岋綀绠涙繝鍐╃彋濠殿喖锕ㄥ▍锝夊极椤曗偓椤㈡瑩骞嗚閻撳倿姊绘担椋庝覆缂佹彃娼″畷妤€螣閾忚娈炬繝闈涘€婚…鍫ュ础閹惰姤鐓熼柟閭﹀墰琚﹂梺鍝勬噽婵炩偓鐎殿喖顭锋俊鎼佸煛娴ｈ櫣娼夐梻浣规偠閸庮垶宕濇繝鍥х劦妞ゆ巻鍋撻柛鐔告尦瀵槒顦剁紒鐘崇洴楠炴﹢骞囨担绋课ㄦ繝鐢靛剳缁茶棄煤閵堝鏅濇い蹇撶墕缁犳牗绻涢崱妯绘儎闁轰礁鍊块弻娑㈠即濡搫顬堟繛瀛樼矒缁犳牠寮婚悢鍛婄秶闁告挆鍛闂備焦鎮堕崝宀勫磹閸︻厽宕叉繛鎴烇供閸熷懏銇勯弮鍥у惞闁告垵缍婂铏圭矙濞嗘儳鍔€缂備胶绮换鍫濐嚕鐠囧樊鍚嬮柛鈩兠～锟犳⒑閻熸澘妲婚柤娲诲灦瀹曘垽鏁撻悩鏂ユ嫼闂佸憡绻傜€氼參鏁嶉弮鍌滅＜闁绘娅曞畷宀€鈧鍠栭…鐑藉极閹邦厼绶炲┑鐘插濞煎姊绘担渚劸闁哄牜鍓熼妴鍐幢濞嗗苯浜炬慨姗嗗幘濞插瓨鎱ㄦ繝鍕妺婵炵⒈浜獮宥夘敋閸涱啩婊勭節閻㈤潧浠滄俊顖氾躬瀹曪綁宕橀…鎴濇婵犵數濮电喊宥夊疾閺屻儲鐓曟繛鎴灻埀顒€顭峰畷浼村箻鐠囪尙鐛ユ繝鐢靛Т閸燁垳绱為崶顒佺厪濠电姴绻愰惁婊堟煕閻愭彃顣崇紒杈ㄦ崌瀹曟帒顫濋钘変壕鐎瑰嫭鍣磋ぐ鎺戠倞闁靛绲肩划鎾绘⒑瑜版帗锛熼柣鎺炵畵瀹曟垿宕掗悙瀵稿帗闂侀潧顧€缁犳垶鏅堕娑氱闁稿繗鍋愭晶杈╃磼鏉堛劍灏伴柟宄版嚇閹虫牠鍩勯崘銊т桓闂佸憡甯掗敃顏堢嵁濮椻偓椤㈡瑩鎮剧仦钘夌疄濠电姷鏁搁崑鐐哄垂閸洘鏅濇い鎰╁焺閸熷懘鏌曟径鍡樻珕闁绘挻鐩弻娑㈠焺閸愮偓鐣兼繝鈷€宥夋闁逛究鍔嶇换婵嬪礃閳瑰じ铏庨柣搴ゎ潐濞插繘宕濆鍥ㄥ床婵犻潧顑呯粈鍐煃鏉炴壆顦﹀鐟版濮婂宕掑▎鎴М闂佺顕滅换婵嬬嵁閹邦厹鍋呴柛鎰╁妿閻涖儵鏌熼崗鑲╂殬闁告柨绉瑰畷鎴﹀煛閸愶絽浜鹃柣鐔告緲椤忣參鏌涚€ｎ亷宸ユい顓炴喘婵℃悂鍩￠崒婊冨笚闁荤喐绮嶇划鎾崇暦濠婂牊鍋勯柣鎾冲閵夈儯鈧帒顫濋敐鍛闁诲孩顔栭崳顕€宕抽敐鍛殾闁绘挸绨堕弨浠嬫煕閳╁啰鎳呯€规洘妞藉濠氬磼濞嗘埈妲梺瑙勭ゴ閸撴繄绮悢鑲烘棃宕ㄩ鐘靛炊闂備礁鎼粙渚€宕戦崱娆戜笉闁哄啫鍊归崰鎰扮叓閸ャ劍绀冩い顐ｆ礋閺岀喖鎮滃Ο璇查瀺缂傚倸绉村ú顓㈠蓟閺囩喓绡€闊洦娲滈弳鐘电磼閸撗冧壕濠电偛锕獮鍐ㄎ旈崘鈺佹瀭闂佸憡娲﹂崜娑⑺囬妸鈺傜厽闁靛繆鏅涢悘锟犳偨椤栥倗绡€鐎规洘妞芥慨鈧柍鈺佸暙閸斿懘姊洪棃娑辩劸闁稿孩濞婇、姗€宕崟銊︽杸闂佺粯顭囩划顖氣槈瑜庢穱濠囶敃椤愩垹绫嶉梺璇″枟椤ㄥ﹪鐛鈧、娆戞喆閿濆棗顏洪梻鍌欒兌椤牓寮甸鍕仭闁靛ň鏅涚粈鍌炴倶閻愭澘瀚庡ù婊勭矋閵囧嫰骞樼捄杞版埛婵犫拃鍕姇闁靛洤瀚版俊鎼佹晲閸涱厼袝闁诲氦顫夊ú锕傚磻婵犲啩绻嗛柣鎴ｆ鍞銈嗘⒒閻℃柨螞閵夈儮鏀介柨娑樺娴滃ジ鏌涙繝鍐⒌妤犵偞鍔栭妶锝夊礃閵娧呭炊闂備礁婀遍崑鎾绘儑瑜版帒鐒垫い鎺嗗亾闁硅櫕锚椤曪絾绻濆顑┿劑鏌ㄩ弮鈧崕鎶界嵁瀹ュ鈷掗柛灞捐壘閳ь剚鎮傚畷鎰板箹娓氬洦鏅銈嗘尨閹崇偤宕堕浣规珕闂備焦顑欓崹鐗堢妤ｅ啯鐓熼柣鏂挎惈椤ｅジ鏌涢悢鍝勪户缂佽鲸甯為幏鐘诲箵閹烘挻顔掑┑鐘殿暜缁辨洟寮拠鑼殾闁绘梻鈷堥弫宥嗘叏濮楀棗澧柡浣靛€濆缁樼瑹閳ь剙顭囪閳ワ箓宕奸妷銉э紮濠德板€曢崯顖氱暦閹绘崡褰掓晲閸モ斂鈧﹪鏌￠埀?"
            )
        return (
            "Let's not jump straight into a solution yet. First I want to align on your goal, project context, and the coaching lane that fits you best."
            "\n\n"
            "Start with the few things that matter most right now: your goal, the project in front of you, your current level, "
            "how you prefer to be coached, and the point you most want to move forward or feel stuck on."
            "\n\n"
            "Then I can decide whether this should become an idea implementation discussion, an existing-project adaptation lane shaped around your intent, "
            "a principle explanation, or a training plan we shape together and keep over time."
            "\n\n"
            "If you want to keep it simple, answer just one thing first: do you mainly want to implement an idea, adapt a project, or shape the training thread?"
        )

    def _error_reply(self, exc: Exception, response_language: str | None = None) -> str:
        if _prefers_chinese(response_language):
            return (
                "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婃笟妤呭磿閹邦厹浜滈柕澶堝劤婢ф稓绱掔紒妯兼创妤犵偛顑呴埞鎴﹀幢濮橆剛鍘撮梻鍌欑閹诧繝骞愮紒妯肩彾闁糕剝鐟﹂～鏇㈡煙閻戞﹩娈曢柛濠囨敱閵囧嫰骞掗崱妞惧闂備礁鎲￠弻锝夊磹閺嶎厼桅闁告洦鍨奸弫鍥煟濡绲绘鐐差儔閹鈻撻崹顔界亪濡炪値鍘鹃崗妯侯嚕椤愶箑绠涙い鎾跺仧缁愮偞绻濋悽闈浶㈤悗姘煎櫍瀵爼宕ㄦ繝浣虹畾闂佺粯鍔︽禍婊堝焵椤掍胶澧遍柡渚囧櫍楠炴帒螖閳ь剛澹曢悷閭︽富閻庯綆浜妤呮煕閵婏妇绠為柡宀嬬秮婵偓闁绘ê鍟块弳鍫ユ⒑閹惰姤鏁遍柛銊ユ健瀵鈽夊Ο閿嬫杸闂佺硶鍓濋〃蹇旂閹屾富闁靛牆鍟崝銈夋煕鐎ｎ剙鏋旀俊鍙夊姍楠炴帒螖婵犲啯娅撻梻浣稿悑娴滀粙宕曟潏鈺侇棜闁规儼濮ら崐鍨箾閸繄浠㈤柡瀣⊕閵囧嫰顢橀悩鎻掑箣濡ょ姷鍋涢崯瀛樻叏閳ь剟鏌曢崼婵囶棡闁稿寒浜娲閳轰胶妲ｉ梺鍛婄懃缁绘帒危閹版澘钃熼柕澶涜吂閹风粯绻涢幘鏉戠劰闁稿鎸荤换娑欐媴閸愬弶鍣虹€规洘鐓￠弻鐔兼倻濡闉嶉梺鍛婄懃缁绘﹢寮婚敐澶婎潊闁绘ê鍟块弳鍫ユ⒑缁嬪尅宸ラ柣鏍с偢瀵鈽夐姀鈺傛櫇闂佺粯蓱瑜板啯鎱ㄩ弴銏♀拺闁规儼濮ら弫閬嶆煕閵娿儲鍋ョ€殿喛顕ч埥澶娢熼柨瀣澑闂備胶纭堕崜婵嬨€冭箛鏂款嚤鐎光偓閸曨兘鎷虹紓浣割儏濞硷繝顢撳Δ鍛拺閻㈩垼鍠氱粔顔锯偓娈垮枛椤兘寮幇顓炵窞濠电姴瀚烽崬娲⒒娴ｈ櫣甯涢柛鏃€娲栬灒濠电姴浼呭ú顏嶆晣闁靛繆妾ч幏娲⒑閼姐倕鏋戝鐟版閹箖顢橀姀锛勫幈闂侀潧顭堥崕宕囩矓濞差亝鐓曢柍鐟扮仢閸旀粎鈧灚婢樼€氫即鐛崶顒夋晢濠㈣泛顑囩粔閬嶆⒒閸屾瑨鍏岀紒顕呭灦閳ワ箓宕奸～顓犲墾濡炪倕绻愰悧鍡涙倿閸偁浜滈柟鍝勬娴滈箖姊虹拠鑼缂佽鐗撳畷娲倷閸濆嫮顓洪梺鎸庢磵閸嬫捇鏌ｉ幙鍕瘈闁哄本鐩崺鍕礃閻愵剛鏆┑鐐差嚟婵潧顭囧▎鎾崇厴闁硅揪闄勯崐鐑芥煕濞嗗浚妲搁柣婵囨⒒缁辨挻鎷呴悷鎵シ婵犫拃鍛珪闁告帗甯為埀顒婄秵閸犳牜绮婚幎鑺ョ厵闁诡垎鍛厽濠碉紕铏庨崳锝咁潖濞差亜宸濆┑鐘插濡插牓鏌ら悷鎵劯闁哄瞼鍠庨悾锟犳偋閸喎鍓甸梻浣哥枃椤宕归崸妤€绠栨繛鍡樺灦瀹曞螖閿旇棄顕滈柡鍡氶哺娣囧﹪鎮欓鍕ㄥ亾閺嵮€鏋栭柨鏇炲€搁悙濠囨煃鏉炴媽鍏岄柕鍫畵濮婄粯鎷呴崨濠冨創缂備礁顑勭欢姘暦閵忥紕顩烽悗锝庡亜娴滄姊洪棃娑辨Т闁哄懏绮撻幃鈥斥槈閵忥紕鍘遍梺闈涱檧缁蹭粙宕濆顑芥斀闁斥晛鍟妵婵囨叏婵犲啯銇濇い銏☆焾椤︽煡鏌ｈ箛銉хМ闁哄苯绉烽¨渚€鏌涢幘鏉戝摵妞ゃ垺鐟╁浠嬵敇閻愮數宕堕梻浣告惈缁嬩線宕㈤幖浣哥劦妞ゆ帒锕﹂悾鐢告煙椤旂晫鐭掗柟绋匡攻瀵板嫮鈧綆鍏橀崑鎾活敆閸曨兘鎷洪梺鑽ゅ枑濠㈡﹢鍩涢弮鍌滅＜妞ゆ洖鎳庨悘锔锯偓瑙勬礃閸ㄥ潡鐛崶顒佸亱闁割偁鍨归獮鎰版⒑鐠囪尙绠抽柛瀣█椤㈡俺顦圭€规洘绻傞～婵嬫嚋閻㈤潧骞愬┑鐐舵彧缁插潡鎮洪弬娆剧劷闁归偊鍠氱壕鑲╃磽娴ｈ鐒界紒鐘靛仱閺岀喖顢欓懡銈囩厯濠碘槅鍋勯崯顐﹀煡婢舵劕绠抽柟鎯х亪閸嬫捇鎮ч崼銏㈢槇闂佹眹鍨藉褎绂掗幒妤佺厱闁哄稁鍋勯埢鍫⑩偓瑙勬礀閻栧吋淇婇幖浣肝ㄩ柕鍫濇川濞夊潡姊婚崒姘偓鐑芥嚄閸撲焦鍏滈柛顐ｆ礀缁€鍫熺節闂堟稓澧㈤柣顓熺懇閺岀喐娼忛幑鎰靛悈缂傚倸绉甸悧鐘诲蓟濞戞ǚ妲堟俊顖氬悑閹插ジ姊虹紒妯诲暗闁哥姵鍔欓獮鍫ュΩ閵夊孩妫冮崺鈧い鎺嗗亾閾荤偞淇婇妶鍕厡妞も晛寮剁换婵嬫濞戝崬鍓遍梺缁樻尰閻╊垶寮诲☉姘勃缂備降鍨洪悾鑸电箾鐎涙鐭岄柛瀣尵閹广垹鈹戦崼婵囩€虫繝銏ｆ硾閻ジ鏁嶉悢鍏尖拺缂佸顑欓崕鎰版煕閵娿儳浠㈤柣锝囧厴楠炲洭寮堕崹顔兼暏闁荤喐绮嶇划宀勨€﹂崶顒€鍐€妞ゆ劧绲介弸鎴︽⒑缂佹﹩娈旈柣妤€妫涚划顓㈠箳閺冨倹锛忛梺璇″瀻閸曨偂娣梻浣告惈閻ジ宕伴弽顓犲祦闁糕剝绋掗崑瀣煕椤愵偄浜濇い銉ヮ樀濮婄粯鎷呴崨濠傛殘闂佹悶鍔忛～澶愬箞閵娾晜鍋ㄩ柛顭戝亜鎼村﹤鈹戦悙鏉戠仧闁搞劌婀辩划濠氭晲婢跺鍘介梺褰掑亰閸ㄤ即鎯冨ú顏呯厱闁哄倹鍎冲畵鍡樻叏婵犲懏顏犵紒顔界懃閳诲酣骞嗚婢瑰姊绘担鐑樺殌闁硅绻濋獮鍐磼閻愬弶妲梺闈涚箞閸婃洜绮绘繝姘仯闁搞儯鍔岀徊濠氭煟鎼搭喖骞栨い顏勫暣婵″爼宕卞Ο閿嬪闂備礁鎼幏瀣磻婢舵劕桅闁逛即鍋婇弫宥夋煟閹邦喛藟闁归绮换娑欐綇閸撗冨煂闂佺顕滅换婵嬬嵁婢跺瞼鐭欓幖瀛樻尰閺傗偓婵＄偑鍊栧ú宥夊磻閹惧绠惧ù锝呭暱濞诧箓宕戦埡鍌滅瘈闂傚牊渚楅崕蹇曠磼閻樺灚鍤€闂囧鏌ㄥ┑鍡樺櫤闁诡垰鐗忕槐鎺撶瑹婵犲嫮鏆ゅ┑顔硷龚濞咃絽鈽夐悽绋垮窛妞ゆ柨鍚嬮柨顓犵磽閸屾瑨鍏屽┑顔炬暬瀹曞綊宕烽鐐茬亰闂佸壊鍋€閹冲洭宕戦幘缁樻櫜閹肩补鈧尙鎸夊┑鐐茬摠缁秶鍒掗幘璇茶摕闁炽儲鍓氶崥瀣煕閹扳晛濡兼い顒€顑夊铏圭磼濡粯鍎庨梺鎼炲妼绾绢厼危閹版澘绠虫俊銈傚亾缁绢厸鍋撻梻浣虹帛閸旀瑥顭囪閹繝鎮㈢亸浣规杸濡炪倖姊婚妴瀣绩缂佹ü绻嗛柣鎰煐椤ュ鏌ｉ敐鍥у幋濠碘剝鎮傞弫鍌炲礈瑜忓Σ鍥⒒娴ｅ憡鍟為柛鏃撶畵閹繝宕煎顏庣秮閺屽棗顓奸崱蹇斿濠电偠鎻徊浠嬪箟閿熺姴鐤柣鎰劋閻撴瑦鎱ㄥ┑鍡氬闁告艾婀辩槐鎺楊敊閻ｅ本鍣板Δ鐘靛仜椤戝懘鍩為幋锕€骞㈡繛鍡楃Т娴滆棄鈹戦悩鍨毄濠殿喚鍏橀妴鍌炴寠婢光晪缍佸畷銊╁级閹存繄鈧參姊哄Ч鍥х伄妞ゎ厼鐗愮换姘舵⒒娓氣偓閳ь剛鍋涢懟顖涙櫠閹绢喗鐓涚€光偓鐎ｎ剛鐦堥梺绯曟杹閸嬫挸顪冮妶鍡楃瑐闁煎啿鐖奸妴鍛存倻閼恒儱鈧敻鏌ㄥ┑鍡涱€楀ù婊呭仱閺屾稑螣閸︻厾鐓撳┑顔硷躬缂傛岸濡甸幇鏉跨闁瑰瓨绮岄弸鍫ユ⒒娴ｈ鍋犻柛鏂款儔瀹曪繝骞庨挊澶岀暰闂佸憡鍔﹂悡浣该洪宥嗘櫆闂佸憡渚楅崹浼寸嵁瀹ュ鈷掑ù锝夘棑娑撹尙绱掗煫顓犵煓闁瑰磭鍠栭、娑橆潩椤撶喓妲戠紓鍌氬€搁崐鎼佸磹瀹勬噴褰掑炊閵婏絼绮撻梺鍛婄缚閸庢煡寮冲鍫熺叆闁绘柨鎼ⅷ闂侀€炲苯鍘哥紒鈧笟鈧崺銏℃償閵娿儳顔掗梺鍝勵槹閸ㄥ爼鎮块崟顖涒拻濞达絽鎲￠幆鍫熴亜閿斿灝宓嗘い銏＄墪閳诲酣骞囬澶婃闂備礁鎲￠崝锕傚窗濡ゅ懎鐓曢柟杈鹃檮閻撴瑩鎮峰▎蹇擃仼濠殿喖娲弻娑橆潩椤掑倻楔闂佸搫鏈粙鎾诲焵椤掑﹦绉甸柛鎾寸懄缁傛帟顦归柡宀€鍠栭悰顕€宕归鍙ユ偅闂備礁鐤囧Λ鍕囬崹顐ｅ弿闁逞屽墴閺岋絽螣濞茶鏅遍梺鍛婅壘閹冲繒鎹㈠┑瀣仺闂傚牊绋愮划璺衡攽閳藉棗浜濇い銊ョ墦楠炴垿濮€閵堝懐顔婇梺褰掔畺椤ゅ倸霉閸曨垱鈷戦柛蹇氬亹閵堟挳鏌￠崨顔剧畼濠㈣娲樼缓浠嬪川婵犲嫬骞楅梻渚€鈧稑宓嗘繛浣冲嫭娅犳い鏇楀亾闁哄本鐩顒傛嫚濞村浜鹃柡宥庡幖妗呴梺鍛婃处閸ㄥジ寮崶顒佺厽婵☆垵顕х徊缁橆殽閻愬樊鍎旈柟顔筋殔閳绘捇宕归鐣屼邯婵＄偑鍊ら崣鍐绩鏉堛劎鈹嶅┑鐘叉搐缁犵懓霉閿濆牆鈧粙濡搁埡鍌滃帾闂婎偄娲ら敃銈嗘櫠閺屻儲鐓涘璺侯儐閸婃劖鎱ㄦ繝鍕笡闁瑰嘲鎳橀幖褰掔嵁鎼存挸浜惧┑鐘插暕缁诲棝鏌ｅ▎鎰噧婵炲眰鍊濋幃鍧楁倷椤掑倻鐦堟繝鐢靛Т閸婃悂顢旈鍛闁告侗鍘剧粻缁樻叏婵犲偆鐓肩€规洘甯掗～婵嬵敄閽樺澹曢梺缁樺灱婵倝宕愰崸妤佺叆闁哄啫鍊瑰▍鏇犵磼閻樺啿鍔ら柍瑙勫灴閹晠宕ｆ径瀣€风紓鍌氬€风拋鏌ュ疾閻樺樊鍤曢柛顐ｆ礀闁卞洦鎱ㄥ鍡楀箺闁绘繃娲熷娲传閸曨剦妫＄紓渚囧枛缁夌數绮氭潏銊х瘈闁搞儺鐏涜閺屾稑鈽夐崡鐐寸亪濠电偛鎷戠徊鐐┍婵犲伣鏃堝焵椤掑嫬绠犳俊顖欒濞兼牗绻涘顔荤盎鐎瑰憡绻傞埞鎴︽偐閹绘帗娈銈忚吂閺呯姴顫忓ú顏勭闁绘劖褰冮‖鍡涙⒑閸涘娈旈柛鐔锋健閹箖鎮滈懞銉︽闂佺粯顭堝▍鏇㈠磿椤忓嫷娓婚柕鍫濇婵呯磼鏉堛劍绀堢紒顔款嚙椤繈鎳滅喊妯诲闂傚倸鍊搁悧濠勭矙閹惧瓨娅犻柡鍥ュ灪閻撴洖鈹戦悩鎻掆偓褰掑疮閻愮數纾奸柛灞炬皑鏁堥梺璇″枟閻熲晠銆佸Δ鍛＜婵犲﹤楠搁弲顓㈡⒒娴ｇ瓔鍤欓悗娑掓櫇缁瑩骞掑鐑╁亾閿曞倸鐐婃い鎺嶇閸撳綊鏌ｆ惔顖滅У闁哥姵顨婇幃锟犲即閵忕姷顔愬┑鐑囩秵閸撴瑩鎮橀埡鍛厓缂備焦蓱缁€瀣煛鐏炵晫效濠碉紕鍏橀弫鍌滅驳鐎ｎ偒妫冮梺璇叉唉椤煤濮椻偓閺佸啴濮€閵堝啠鍋撴担绯曟瀻闁规儳鍟跨花銉︾節閵忥綆鍤冮柛銊︽緲鐓ら柕濞炬櫅閻鏌熼崜褏甯涢柣鎾存礋閺屾洘寰勫☉姘煂婵犵绱曢弲顐ゆ閹烘鐒垫い鎺戝閻掑灚銇勯幒鍡椾壕濡炪値浜滈崯瀛樹繆閸洖骞㈡俊顖溾拡濡插嘲鈹戦悙鑼憼缂侇喚濞€瀹曟粌鈽夊Ο婊愮秮楠炲洭寮剁捄顭戝晪闂佽閰ｅ褔骞楀鍫濈疇婵犻潧顑嗛埛鎴︽煙閼测晛浠滈柛鏂哄亾闂備礁鎲″ú锕傚储濞差亜绠熷Δ锝呭暞閳锋帡鏌涚仦鍓ф噭缂佷焦澹嗛埀顒冾潐濞叉粓寮拠鑼殾闁规儼濮ら弲婵嬫煕鐏炲墽鈻撻柟绋垮暣濮婃椽宕ㄦ繝鍐槱闂佸憡锕㈢粻鏍箚鐏炵瓔娼╅悹楦挎妤犲洭姊洪崜鎻掍簼缂佸鍨舵穱濠勬崉閵娧咃紲闂佹娊鏁崑鎾绘煕鐎ｎ偅宕屾慨濠勭帛閹峰懐鎲撮崟顐″摋闂備胶顭堢€涒晝鍒掗幘宕囨殾妞ゅ繐鎳忔刊鎾煕濞戞﹫鏀婚柣婵勫妼閳规垿鎮╁▓鎸庢缂備浇椴稿ú鐔风暦閹达箑绠ｉ柨鏇楀亾缁炬儳缍婇弻鈥愁吋鎼达絼绮跺┑鐐村灦閻熝囨偡瑜版帗鐓冪憸婊堝礈濞嗘挻鍋╅柣鎴ｆ缁狅綁鏌ㄩ弴妤€浜剧紓浣哄У閻╊垶寮婚敐鍛傛棃鍩€椤掑嫭鍋嬪┑鐘插€甸弸宥夋煛瀹擃喒鍋撻柡鈧禒瀣厽婵☆垱顑欓崵瀣偓瑙勬偠閸庣敻寮诲☉銏″亜闁告繂瀚ч弸鍛存倵濞堝灝鏋旈柛鏃€鍨块獮濠囨倷閸濆嫀銊╂煥濠靛棗顏柣鈺侀叄濮婄粯鎷呴崨濠冨創闂佸摜鍠撴繛鈧€规洘鍨块獮妯肩磼濡厧骞愰梺璇插嚱缂嶅棝宕滃☉姘殰婵炴垶姘ㄧ壕鍏间繆閵堝懎鏆欓柡瀣叄閺屽秹鎸婃径妯烩枅婵犳鍠掗崑鎾绘⒑閹稿海鈽夐悗姘煎墴閻涱噣宕奸妷锔规嫽婵炶揪绲块悺鏂款焽閹扮増鐓曢幖娣灩閳绘洘銇勯姀鈥冲摵妞ゃ垺锕㈡慨鈧柣妯兼暩閺嬪啴姊绘担鍛婂暈闁告柨绻樺顒勫磼濞戞凹娲稿┑鐘诧工閻楀﹪鎮″☉銏＄厱闁靛闄勯弸鍕磼閵娿倗鐭欓柡灞剧洴楠炴帒顓奸崨顓犮偖闂備胶顢婂Λ鍕偉閻撳寒鍤曞ù鐘差儛閺佸洭鏌ｉ弬鎸庢儓閻㈩垱顨婇弻锝夋偄閸濄儳鐓佺紓渚囧枟閹告悂鎮惧畡閭︾叆闁割偆鍠庢禍婊堟⒑缂佹ɑ灏悗娑掓櫅鍗辨い鎺戝閳锋垹绱撴担濮戭亝鎱ㄩ崶顒佺厵缁炬澘宕禍鐐电磼椤旂⒈鐓奸柡浣瑰姈瀵板嫮鈧綆鍓欏鎶芥⒒娴ｅ憡鎯堟繛璇х畵閵嗗啴宕ㄩ缁㈡锤婵°倧绲介崯顖炲煕閹寸姷纾藉ù锝堝亗閹达箑绠氶柛顐犲灮绾捐偐绱撴担璇＄劷缂佺姷鍋熼埀顒侇問閸犳盯顢氳閸┿儲寰勯幇顒夋綂闂佺粯锕㈠褎鎱ㄩ崼鏇熲拻濞达絽鎲￠崯鐐烘煕閺傜偛鎳愮壕鑺ユ叏濮楀棗鍘撮柡宀嬮檮閵囧嫯绠涢幘鎼￥缂佺偓宕樺Λ鍕Υ閹烘埈娼╂い鎺嶇缁愭盯姊洪崨濞氭垿鎯勯鐐茶摕婵炴垯鍨洪弲鏌ョ叓閸ャ劍绀€闁糕晛鑻—鍐Χ鎼粹€茬盎缂備胶绮敃銏ょ嵁閺嶎兙浜归柟鐑樺灦瀹撳秴顪冮妶鍡樺暗濠殿喚鍏樺畷銏ゎ敍濞戞氨鐦堥梺姹囧灲濞佳勭濠婂嫪绻嗘い鎰剁悼閹冲洨鈧娲樺ú鐔肩嵁鎼淬劍瀵犲璺虹焾濡插爼姊婚崒娆戣窗闁告挻鐟х划鏃堟偨缁嬭法鍘遍梺纭呮彧闂勫嫰鎮￠弴銏＄叆闁哄啫娴傞崵娆愵殽閻愭惌娈滈柡灞剧洴婵″爼宕掑顐㈩棜濠电姷鏁告慨鐑藉极閹间礁纾绘繛鎴烆焸閻斿摜绡€闁搞儜鍐ㄤ憾濠电娀娼ч崐鍛婄珶婵犲洤鏋侀悗锝庡枟閻撱儲绻濋棃娑欘棡妞ゃ儳濮风槐鎺楀煢閳ь剟宕戦幘瀵哥瘈婵炲牆鐏濋弸鐔兼煥閺囨娅婄€规洏鍨介幐濠冨緞閸℃鈧椽姊洪崫鍕枆闁告ü绮欓崺娑㈠箣閿旂晫鍘卞┑鐐村灦閿曨偊寮ㄧ拠宸唵閻犲搫鎼鈺呮婢跺绡€濠电姴鍊搁顐ょ磼閻橀潧浠ч柍褜鍓濋～澶娒哄鍫濈獥闁哄诞鍛濠殿喗銇涢崑鎾淬亜閵忥紕鎳囬柟顔煎⒔娴狅箓鎸婃径宀婂晥闂傚倸鍊搁崐鐑芥嚄閸撲礁鍨濇い鏍仦閺咁亪鏌ｆ惔銏╁晱闁哥姵鐩畷娲冀瑜滈崵妤呮煕閺囥劌鐏犵紒鈧€ｎ偁浜滈柟鎹愭硾閺嬪酣鏌＄€ｎ偄鐏存慨濠冩そ瀹曨偊宕熼崹顐嶏箓姊虹拠鑼缂佽鐗嗛锝夊箮閼恒儱鈧兘鏌ｉ幋鐑嗙劷闁告ê鐏氱换娑㈠箻绾惧顥濋梺璇茬箲缁诲啯绌辨繝鍥х缂佹妗ㄧ花濠氭⒑閻熸澘鈷旈柛瀣ㄥ姂瀹曟垿濮€閳垛晛浜鹃悷娆忓缁€鈧梺缁樼墪閵堢鐣峰ú顏呮櫢闁绘灏欓ˇ銊╂煟閻樺厖鑸柛鏃€鍨佃灋鐎瑰嫭澹嬮弨浠嬫煟濡櫣浠涢柡鍡忔櫊閺屾稓鈧綆鍓欓埢鍫燁殽閻愬瓨宕屾い銏℃瀹曞崬鈻庨幋顓熜﹂梻鍌欑窔閳ь剛鍋涢懟顖涙櫠椤栫偞鐓忛柛銉戝喚浼冨銈冨灪濞茬喐鎱ㄩ埀顒勬煃閸濆嫬鈧敻寮搁崨瀛樷拻濞达絿鐡旈崵鍐煕閿濆骸鐏ｉ柟骞垮灩閳规垿宕堕敂鍓х暰闂備胶绮崹鐓幬涢崟顖涘亗婵炴垯鍨洪悡鏇㈡倶閻愭彃鈷旈柣顓烇攻椤ㄣ儵鎮欓幖顓熺杹濠殿喖锕ュ钘夌暦閻戠瓔鏁囬柣鎰絻椤棗鈹戦悩鍨毄闁稿鐩弫鍐Χ婢跺浠奸悗鐟板婢瑰寮ㄦ禒瀣厱闁靛绲芥俊濂告煕閺傛寧鍤囨慨濠冩そ楠炴劖鎯旈敐鍥╂殼闂備胶鎳撻崯鍧楁煀閿濆绠栨俊顖濆吹缁♀偓闂佺鏈〃鍡涘棘閳ь剟姊绘担铏瑰笡闁告梹娲栭锝夊醇閺団偓婢舵劖鍊烽柣鎴烆焽閸橀亶姊洪崫鍕殜闁稿鎸荤换娑㈠矗婢跺瞼鐓€闂佸疇顕ч柊锝嗘叏閳ь剟鏌曢崼婵囶棞闁逞屽墰閸忔﹢寮婚敐澶婄闁诲繑妞挎禍顏堝春閳ь剚銇勯幒鍡椾壕闂佺粯鐗曢妶绋款嚕婵犳碍鏅插璺猴功閻も偓婵＄偑鍊栭幐鍡涘礃閳哄倻褰甸梻鍌氬€烽懗鍓佸垝椤栨粍鏆滄俊銈呮噹绾惧潡鏌熼幆鏉啃撶紒鐘冲笚缁绘繈鎮介棃娴躲垽鏌ㄩ弴妯衡偓婵嬪箖瑜戠粻娑樷槈濞嗗繋鎮ｆ繝鐢靛仜濡﹥绂嶅┑瀣亗婵炴垯鍨洪崐鍫曟煟閹伴偊鏉洪柛銈嗙懃閳规垿鍨鹃悙钘変划闂佸搫鑻粔鍫曞箟閹绢喖绀嬫い鎰╁€撶槐婵嬫煟鎼淬値娼愭繛鍙夌墪閻ｇ兘顢楅崟顐ゅ弨婵犮垼鍩栭崝鏇犵不閵夈儍褰掓晲婢跺鐝虫繝銏ｎ潐濞叉牠鍩為幋鐐茬疇闂佺锕ュú鐔肩嵁婵犲懐鐤€婵炴垶鐟ユ禍妤呮⒑閸涘﹤濮﹀ù婊勭箞瀹曚即骞囬鐘电槇婵犵數濮撮崐缁樻櫠閺囩姷纾奸柍褜鍓熷畷濂告偄閾忚鍟庨梻浣虹《閸撴繈鏁嬮梺璇茬箰缁夊綊寮诲☉姘ｅ亾閿濆骸浜濋悘蹇ｅ弮閺屽秹鎸婃径妯烩枅濡ょ姷鍋炵敮锟犵嵁濡皷鍋撻悽娈跨劸缂佽尪娉曠槐鎾诲磼濮橆兘鍋撴搴㈩偨闁跨喓濮撮梻顖涖亜閺囨浜鹃悗瑙勬穿缂嶄礁鐣峰鈧、娆撴嚃閳哄啯姣囬梻鍌欑窔濞佳呮崲閸儱纾归柡宥庡幖绾惧鏌涘畝鈧崑娑氱不瑜版帒绾ч柛顐ｇ箓閳锋棃鏌涢幒鎾寸凡闁宠鍨块、姘跺幢濞戞瑯鈧秵绻涢敐鍛悙闁挎洦浜獮鍐ㄢ枎閹垮啯鏅滈梺鍛婃磸閸斿本绂嶆ィ鍐╃厸鐎规搩鍠栭懟顖炲疾閻樺磭绡€闁汇垽娼ф牎闂佽偐鎳撴晶鑺ョ珶閺囩喓绡€婵﹩鍘鹃崢鐢告⒑閸涘﹥瀵欓柛娑卞幘椤愬ジ姊绘担铏瑰笡闁规悂绠栧畷浼村冀椤撶偠鎽曢梺闈涱焾閸庮噣寮ㄦ禒瀣厱闁斥晛鍙愰幋锕€绠栨繛鍡樻尰閳锋垿鏌涘☉妯峰妞ゅ繐鐗滈弫瀣亜閹惧崬鐏╅柣鎺戠仛閵囧嫰骞掗幋婵囩亾濠电偛鍚嬮崝鏍崲濞戙垹鐭楀璺虹灱閻撳鎮楃憴鍕妞ゃ劌鎳橀敐鐐差煥閸繄鍔﹀銈嗗笒鐎氼剝绻氬┑鐐舵彧缂嶁偓闁稿﹣绮欓幃銏ゆ倻濡桨绮ч梻浣规灱閺呮盯宕板顒夌劷闁哄啠鍋撶紒缁樼箘閸犲﹤螣濞茬粯缍夐梻浣规偠閸斿秵绻涙繝鍥╁祦濠电姴娲ょ粻濠氭煕閹寸偞绶叉い锔诲灦閿濈偛鈹戠€ｎ偄娈濈紒鍓у钃遍悗姘虫閳规垿鎮欓懜闈涙锭缂備焦褰冨锟犵嵁婵犲洤绠绘繛鑼帛閺咁亜鈹戦悩璇у伐闁硅櫕鍔楁竟鏇熺附閸涘﹤浠梺鎼炲劘閸斿瞼寰婃繝姘厓鐟滄粓宕滃▎鎴犵濠电姴娲よ繚闂佸憡鍔﹂崰鏍ф暜闂備礁鐤囧銊╂嚄閸洦鏁婇柟閭﹀幘缁犻箖寮堕崼婵嗏挃闁诡喖鍚嬮妵鍕敇閻愰潧鈪甸悗瑙勬礈閺佸鐛€ｎ亖鏀介柛鎰ㄦ櫆閺夋悂姊绘担铏瑰笡闁告梹鐗曢…鍥р枎閹炬潙鈧爼鏌ｉ弬鍨倯闁绘挻娲熼弻鏇熺節韫囨稒顎嶉梺闈涙处缁诲嫰鍩€椤掑喚娼愭繛鍙夛耿瀹曞綊骞愭惔婵堢畾闂佸綊妫块悞锕傚疾濠婂牆绾ч柣鎰綑椤ュ鏌ｉ埡渚€鍙勬慨濠勭帛閹峰懘宕ㄦ繝鍐ㄥ壍缂傚倷绀侀ˇ浼存偂閳ュ磭鏆︽繝闈涙－閸氬顭跨捄渚剰闁告搩鍙冨铏规兜閸涱喖娑ч梻鍌氬鐎氫即骞冮敓鐘参ㄩ柨鏂垮⒔椤旀洟姊洪悷閭﹀殶闁稿孩鍔欓幃鐐寸鐎ｎ偄娈愰梺鍝勭▉閸嬪棛澹曢挊澹濆綊鏁愰崟顓犵厯闂佸憡绻冨浠嬪箖娴犲鏁嶆繛鎴ｉ哺閻ｈ泛顪冮妶搴″箹婵炴祴鏅濈划璇测槈濡攱顫嶅┑鈽嗗灡婢规洟寮查悩璇茶摕闁靛ň鏅涢崡铏繆閵堝倸浜炬繛瀛樼矊婢х晫妲愰幒妤€绀堢憸宥嗙閹€鏀介柣鎰嚋闊剚顨ラ悙鎻掓殭閾绘牠鏌涢幇銊︽珔闁哄鍊垮娲川婵犲啫顦╅梺鍛婃尰閻╊垵妫熼梺闈浥堥弲婊堝煕閹达附鐓欑紒瀣仢椤掋垻鐥悙顒佸€愰柡灞剧洴婵℃悂濡堕崶鈺冨幆闂備浇顕栭崰鏇㈠础閹跺鈧礁顫濈捄铏瑰姦濡炪倖宸婚崑鎾绘煟閿濆洤鍘寸€规洩绻濋幃婊堝幢濡搫鍘為梻鍌欒兌椤牏鎹㈤幇鏉课︽繛鍡樻惄閺佸倿鏌涢銈呮毐闁归绮换娑欐綇閸撗勫仹闂佺儵鍓濆Λ鍐ㄧ暦闂堟稈鏋庨柟瀵稿Х閿涙粎绱撻崒娆戝妽闁挎艾鈹戦纰辨Ш缂佽鲸甯￠、娆撴嚍閵夘喗顥堥梻浣筋嚃閸犳岸宕楀鈧濠氬炊椤掍焦娅嗛梺浼欑到閻ジ鍩?API 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婃笟妤呭磿閹邦厹浜滈柕澶堝劤婢ф稓绱掔紒妯兼创妤犵偛顑呴埞鎴﹀幢濮橆剛鍘撮梻鍌欑閹诧繝骞愮紒妯肩彾闁糕剝鐟﹂～鏇㈡煙閻戞﹩娈曢柛濠囨敱閵囧嫰骞掗崱妞惧闂備礁鎲￠弻锝夊磹閺嶎厼桅闁告洦鍨奸弫鍥煟濡绲绘鐐差儔閹鈻撻崹顔界亪濡炪値鍘鹃崗妯侯嚕椤愶箑绠涙い鎾跺仧缁愮偞绻濋悽闈浶㈤悗姘煎櫍瀵爼宕ㄦ繝浣虹畾闂佺粯鍔︽禍婊堝焵椤掍胶澧遍柡渚囧櫍楠炴帒螖閳ь剛澹曢悷閭︽富閻庯綆浜妤呮煕閵婏妇绠為柡宀嬬秮婵偓闁绘ê鍟块弳鍫ユ⒑閹惰姤鏁遍柛銊ユ健瀵鈽夊Ο閿嬫杸闂佺硶鍓濋〃蹇旂閹屾富闁靛牆鍟崝銈夋煕鐎ｎ剙鏋旀俊鍙夊姍楠炴帒螖婵犲啯娅撻梻浣稿悑娴滀粙宕曟潏鈺侇棜闁规儼濮ら崐鍨箾閸繄浠㈤柡瀣⊕閵囧嫰顢橀悩鎻掑箣濡ょ姷鍋涢崯瀛樻叏閳ь剟鏌曢崼婵囶棡闁稿寒浜娲閳轰胶妲ｉ梺鍛婄懃缁绘帒危閹版澘钃熼柕澶涜吂閹风粯绻涢幘鏉戠劰闁稿鎸荤换娑欐媴閸愬弶鍣虹€规洘鐓￠弻鐔兼倻濡闉嶉梺鍛婄懃缁绘﹢寮婚敐澶婎潊闁绘ê鍟块弳鍫ユ⒑缁嬪尅宸ラ柣鏍с偢瀵鈽夐姀鈺傛櫇闂佺粯蓱瑜板啯鎱ㄦ惔锝囩＝?"
                "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃闁硅櫕鎹囬垾鏃堝礃椤忎礁浜鹃柨婵嗙凹缁ㄧ粯銇勯幒瀣仾闁靛洤瀚伴獮鍥敍濮ｆ寧鎹囬弻鐔哥瑹閸喖顬堝銈庡亝缁挸鐣烽崡鐐嶆棃鍩€椤掑嫬鐓曢柟鐑橆殕閳锋垹绱撴担濮戭亞绮崒婊呯＜妞ゆ梻鏅幊鍥┾偓娈垮枛椤攱淇婇崼鏇炲耿婵☆垰鎼导搴ㄦ⒒娴ｅ摜绉洪柛瀣躬瀹曟顫滈埀顒€鐣烽幋锕€绠婚悹鍥ㄥ絻閸炪劌顪冮妶鍡楀闁哥姴瀛╃粋宥夋倷椤掍礁寮垮┑顔筋殔濡鏅舵繝姘厽闁瑰墽鍋ㄩ崑銏ゆ煛鐏炵硶鍋撳畷鍥ㄦ畷闁诲函缍嗛崜娑溾叺闂佽瀛╅鏍闯椤曗偓瀹曟娊鏁愰崨顖涙闂佸湱鍎ら崺鍫濐焽閳哄倶浜滈柟杈剧稻绾爼鎮介娑氥€掔紒杈ㄦ崌瀹曟帒顫濋钘変壕濡炲瀛╂刊濂告煛鐏炶鍔氱痪鎯ь煼閺岀喖鎮欓鈧晶顖炴煟閺傛寧顥㈤柡灞诲€濋獮鏍ㄦ媴鐟欏嫰鏁┑鐘愁問閸犳牠藝閻㈢钃熸繛鎴炃氶弸搴ㄦ煙闁箑骞栫痪鐐▕濮婃椽宕崟顒佹嫳闂佺儵鏅╅崹杈ㄧ┍婵犲洦鍊婚柤鎭掑劜濞呮粓姊洪崨濠佺繁闁告瑥閰ｉ幃妤冣偓闈涙憸绾句粙鏌涚仦鍓ф噯妞ゆ柨顦甸弻娑氣偓锝庡亝瀹曞矂鏌＄仦鍓ф创妤犵偛娲畷妤呭传閵夛箑鐦婚梻鍌欒兌椤牓顢栭崱娑樼濡わ絽鍟粻鐔兼煙缂併垹鏋涚紒鈧€ｎ偁浜滈柟鐑樺灥娴滅偞淇婇煫顓炲祮婵﹦绮幏鍛存惞閻熸壆顐奸梻浣告贡閳峰牓宕戦崱娑樼闁靛繒濮弨浠嬫煕閳锯偓閺呮稑鈻撻妸锔剧瘈闁汇垽娼ф牎闂佺厧缍婄粻鏍箖濡櫣鏆﹂柛銉到娴滈箖鎮峰▎蹇擃仾缂佲偓閳ь剙鈹戦悙棰濆殝缂佺姵鍨块崺銏ゅ箻缂佹ê浜楅柟鍏兼儗閸犳鈧潧鐭傚娲濞戞艾顣哄┑鈽嗗亝閻熲晠宕哄☉銏犵婵°倓鑳堕崢鐢告⒑閹勭闁稿鎳愭禍鎼佸箥椤斿墽锛滈梺绋挎湰濮樸劍鐗庨梻渚€娼ч悧鐐电礊娴ｅ摜鏆︽慨妞诲亾闁糕晝鍋ら幃娆擃敆閳ь剟顢旇ぐ鎺撯拻闁稿本鐟чˇ锕傛煙鐠囇呯？闁瑰箍鍨藉畷鎺戔攦閹傚濠殿喗锚瀹曨剟宕㈢€电硶鍋撶憴鍕婵炶尙鍠栭悰顕€宕堕澶嬫櫍濠电娀娼ч悧蹇涙偩閻愵兛绻嗛柣鎰典簻閳ь剚鐗犲畷婵嬪箣閿曗偓閸ㄥ倻鎲搁悧鍫濈瑨婵鐓￠弻銊モ攽閸℃顦遍梺绋款儐閹告悂鍩㈤幘璇插瀭妞ゆ梻鏅禒灞句繆閻愵亜鈧牕鈻旈敃鍌氱倞鐟滃繘宕ｉ埀顒€鈹戦悩顔肩伇闁糕晜鐗犲畷婵嬪即閵忊€充簵闂佺鎻梽鍕偂閸愵喗鍋℃繛鍡楃箰椤忊晠鏌涢弬璇测偓鏇㈡箒濠电姴锕ら悧蹇涙偩濞差亝鐓涢悘鐐额嚙婵倻鈧鍠楅幐鎶藉箖濞嗗緷鍦偓锝庝簷婢规洟姊洪崨濠勭細闁稿氦娅曠粙澶婎吋婢跺鍙嗗┑鐘绘涧濡瑩藟閻樼數纾奸柍閿亾闁稿鎹囧濠氬磼濮橆兘鍋撻幖浣瑰亱濠电姴瀚惌娆撴煙閻戞﹩娈旈梻鍌ゅ灠闇夐柣妯烘▕閸庢劙鏌ｉ幘瀛樼闁哄瞼鍠愬蹇涘礈瑜忔牎婵犵數鍋涢崥瀣礉閺団€崇倒闂備焦鎮堕崕婊冾吋閸繃鍎撻梻鍌欐祰椤曟牠宕板Δ鍛仭闁冲搫鎳岄埀顑跨窔瀵噣宕煎┑鍫О婵＄偑鍊曠换鎰涢鐐嶏綁顢楁担铏圭槇闂佹眹鍨藉褎绂掗埡鍛厵婵炶尪顔婄花鐣屸偓鍨緲閿曘儳绮嬮幒鏂哄亾閿濆簼绨介柣銈呮嚇濮婃椽寮妷锔界彅闂佸摜鍣ラ崑鍡椻枎閵忋倖鍊烽柣鎴烆焽閸橀亶姊洪崫鍕偍闁告柨鐭傞幃姗€鏁撻悩宕囧幗闂佽鍎抽崯鍧楀汲閿濆棙鍙忓┑鐘插暞閵囨繄鈧娲栫紞濠囥€佸璺哄窛妞ゆ挾鍋涢ˉ宥呪攽閻樺灚鏆╅柛瀣仱楠炲棗鐣濋崟顐︽７闂佹寧绻傞ˇ顖炴嫅閻斿吋鐓ユ繛鎴灻褎绻涘畝濠侀偗闁哄本鐩獮妯侯渻閹规劦鍞归梺绋款儐閹瑰洭鐛幒妤€绠犻柕濞垮劤缁夋椽鏌熼鍛偗鐎规洏鍔戦、娑橆煥閸曨剦鍟岄梻浣筋嚙濮橈箓锝炴径濞掑搫螣閻撳骸鐏婇棅顐㈡处閾斿宕堕澶嬫櫓闁诲繐绻戦悧妤呭棘閳ь剚淇婇悙顏勨偓鏍蓟閵娾晛瑙﹂悗锝庡枛缁愭鎱ㄥ璇蹭壕闂佸搫澶囬埀顒€纾弳鍡涙倵閿濆骸澧扮悮锝囩磽閸屾瑨鍏屽┑顔炬暬閹嫰顢涢悙闈涚ウ濠殿喗銇涢崑鎾绘煙缁涘湱绡€濠碘€崇埣瀹曘劑顢欐潪鎷屾缂傚倸鍊搁崐鎼佸磹閹间礁纾归柣鎴ｅГ閸ゅ嫰鏌ょ粙璺ㄤ粵闁告瑥绻橀弻锝夊閵忊晝鍔哥紓浣哄У閻擄繝寮诲☉銏犖ㄩ柟瀛樼箚鐎氱増绻涢崼娑樺闁哄矉缍侀幃鈺呭矗婢跺妲辩紓鍌欐閻掞箑顭囧▎蹇撶カ闂備礁澹婇崑渚€宕曢弻銉﹀亗闊洦绋撻崣鎾绘煕閵夋垵绉存导鎰節閳封偓閸愩劎楠囩紓浣虹帛閻╊垰鐣烽妸鈺婃晩闁告挆鍛笒缂傚倸鍊烽懗鍓佸垝椤栨粍宕查柛顐ゅ枑閸欏繘鏌嶈閸撶喖寮婚妸銉㈡斀闁糕剝锕╁Λ銈夋⒑闂堟稒顥為柛鏃€娲熼垾鏃堝礃椤斿槈褔鏌涢埄鍐炬畼濞寸姵娼欓埞鎴﹀煡閸℃ぞ绨肩紓浣筋嚙閸婂潡銆佸鑸垫櫜濠㈣泛锕﹂鍛存⒑閸忛棿鑸柛搴ら哺缁傚秷銇愰幒鎾嫼濠殿喚鎳撳ú銈夋倶椤曗偓閺屸剝鎷呯憴鍕偓鎰版煛娴ｅ摜孝闁宠鍨垮畷鍫曞煛閸愭儳鏅梻浣告惈椤︻垶鎮ч崱妯绘珷濞寸姴顑呯粈鍡涙煛婢跺鍎ラ柣鏂挎閺岋綁鎮㈠畡鎵泿闂傚鍓﹂崜娑㈠焵椤掑喚娼愭繛鍙壝叅婵犻潧鐗忔稉宥嗙箾閹存瑥鐏╂俊顐ｏ耿閹鎷呴崫銉礊闂佺儵鏅涢柊锝咁潖缂佹ɑ濯撮柣鐔煎亰閸ゅ鈹戦埥鍡椾簵缂佽埖宀搁妴浣割潩閹颁焦鈻岄梻浣筋嚃閸犳鏁冮姀銈呮瀬闁稿本绋掗崣蹇涙煙闁缚绨介柣鈺侀叄濮婄粯绗熼埀顒€顭囪閹广垽宕卞☉妯绘К闂佸憡娲﹂崹鎵不閿濆鐓熸俊顖氬悑閺嗏晛顭跨捄鍝勵伃婵﹦鍎ょ€电厧鈻庨幋婵嗙厒闂備焦妞块崜娆撳Χ閹间礁绠氶悘鐐缎掗弸搴ㄦ煙閹屽殶闁告﹢浜堕幃宄邦煥閸愵喖寮伴梺闈涙閸熸潙鐣烽妸鈺佺骇闁瑰鍋熼埀顒夊墴閺岋綁鎮㈤崫銉﹀櫑闁诲孩鍑规禍鐐哄箲閵忋倕骞㈡繛鎴炵懅閸樹粙姊虹憴鍕凡闁告埃鍋撶紓浣靛妼椤兘寮诲鍫闂佸憡鎸诲畝鎼佸箖瑜旈幃鈺呮嚑椤掍焦顔曟繝鐢靛█濞佳団€﹂鈧嵄濡わ絽鍟崐鐢告煕椤垵浜濈紒鑸电叀閺屻劑寮撮妸銈囩泿闂佷紮缍侀ˉ鎾跺垝濞嗘垶瀚氶柣鎰靛墯閳锋劙鏌熷畡鐗堝殗婵﹤缍婇獮鍥敊閼恒儺鍞梻鍌氬€搁崐鎼佸磹閻戣姤鍤勯柛顐ｆ磸閳ь兛鐒︾换婵嬪炊瑜忛灞筋渻閵堝懐绠伴柣妤€锕崺娑㈠籍閸喓鍘遍梺鍝勬储閸斿矂鎮橀悩缁樼厽闁规儳鐡ㄧ粈瀣煛瀹€鈧崰鏍箖濠婂吘鐔兼倻濮楀棗鏁堕梺鑽ゅ枑缁孩鏅跺Δ鍐╂殰婵°倕鎳庨悿楣冩煛鐏炶鍔滈柣鎾存礋閺岋繝宕堕妷銉ヮ瀳濠电偛鎳忛敃銏ゅ蓟濞戙垹妫橀柟绋块濞堟鈹戦纭烽練婵炲拑绲垮Σ鎰板箳閹冲磭鍠栭幖鍦嫚閳ュ啿澹冮梻鍌氬€烽懗鍫曗€﹂崼銉晞闁糕剝绋戠粻鏌ユ煕閵夛絽濡虹紒璇叉閺岋綁濮€閵忊晝鍔哥紓浣插亾閻庯綆鍋佹禍婊堟煛瀹ュ啫濡介柣銊﹀灦閵囧嫰骞橀搹顐ｅ創闂佸疇顫夐崹鍧楀箖閳哄啰纾兼俊顖氼煼閺侇亝绻濋悽闈涗沪婵炲吋鐟╁畷鎰潰瀹€鈧禍閬嶆⒒娓氣偓濞佳囨偋閸℃蛋鍥ㄥ閺夋垹鍘遍梺纭呮彧闂勫嫰鎮￠弴鐔虹闁瑰鍎戦崗顒傗偓瑙勬偠閸庡磭妲愰幒鎳虫梹鎷呯粙鎸庢嚈闂備浇顕栭崰鏇犲垝濞嗘挶鈧礁鈽夐姀鐘栄囨煕閵夈垺娅囨俊鎻掓喘閺岋絾鎯旈姀鈺佹櫛闂侀潻缍嗛崳锝呯暦閹寸偟绡€闁搞儮鏅涚粊锕傛⒑閹肩偛鍔撮柛鎾寸懅閻ヮ亣顦归柟顔肩秺楠炰線骞掗幋婵愮€抽梻渚€鈧偛鑻晶浼存煕鐎ｎ偆娲撮柍銉︽瀹曟﹢顢欓崲澹洤绠圭紒顔煎帨閸嬫挸鐣烽崶璺烘櫏闂傚倸鍊烽悞锕傚箖閸洖绀夐悘鐐靛亾濞呯娀骞栨潏鍓хɑ妞ゎ偅娲熼弻锝夊箛椤掆偓濡﹢鏌￠崘锝呬壕闂佺懓鍢查幊姗€骞栬ぐ鎺戞嵍妞ゆ挾鍣ュ鎾绘⒒閸屾艾鈧兘鎮為敃鍌涘剳鐟滅増甯掗崹鍌炴煢濡警妯堥柣鎺旀櫕閹叉悂寮崼婵囨К闂侀潧绻堥崐鏇㈡煁閸ヮ剚鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú妯兼崲濞戞瑦缍囬柛鎾楀啫鐓傞梻浣告憸閸犲酣鎮樺┑瀣畳闂備胶顭堥惉濂稿磻濞戙垹鍑犲〒姘ｅ亾闁哄本鐩鎾Ω閵壯傜敾闂備胶绮幐璇裁哄Ο鍏煎床婵炴垯鍨圭粻锝嗙節闂堟稒顥￠柛鈺冨仱濮婅櫣鎷犻弻銉у椽缂傚倸绉崇欢姘嚕婵犳碍鏅插鑸瞪戦弲锝夋⒑缂佹ê濮堥柟顖氳嫰铻為柨鏇炲€归埛鎴︽煕濠靛棗顏繝鈧幍顔剧＜閻庯綆鍋勯悘鎾煙椤旇棄鍔ら柍瑙勫灩閳ь剨缍嗘禍鐐哄礉閿曗偓椤啴濡堕崱妤冪懆闁诲孩鍑归崜娑欑珶閺囩喓绡€婵﹩鍘鹃崢浠嬫⒑瑜版帒浜伴柛鐘崇墵瀹曟繄鈧綆鍠楅悡鏇㈡倵閿濆簼绨婚柍褜鍓欏鈥愁嚕婵犳碍鏅搁柣妯垮皺閸婄偤姊虹€圭姵銆冮柣鎺炵畵閹顢橀悢铏诡啎闁诲孩绋掗…鍥儗鐎ｎ剛纾兼い鏃囧Г瀹曞瞼鈧鍠栭…鐑藉箖閵忋倖鍋傞幖杈剧秵閸氬姊绘担鐟板姢婵炲瓨宀稿畷鎴﹀川鐎涙ê浠ч梺鍝勫暙閻楀﹪鍩涢幋锔解拺妞ゆ劑鍊曟禒婊堟煠濞茶鐏￠柡鍛埣椤㈡稑鈽夊槌栧晭闂備浇鍋愰埛鍫ュ礈濞嗘挸鍑犻幖鎼娇娴滄粓鏌￠崶鏈电敖缂佸鍠氶埀顒冾潐濞插繘宕濆鍥ㄥ床婵犻潧顑呯粈鍐煏婵炲灝鍔氶棅锕傛⒒閸屾艾鈧娆㈠顒夌劷鐟滄棃鍨鹃敃鍌氶唶闁靛鍎抽敍鐔兼⒑鐟欏嫬鍔跺┑顔哄€濆畷鎴﹀煛娴ｅ嫭妫冮弫鎰板川椤撶喐顔夐梻浣瑰▕閺€閬嶅垂閸︻厽顫曢柟鎯х摠婵挳鏌ゅù瀣⒉闁搞劌娼￠獮鍐晸閻樺弬銊╂煃閸濆嫬鈧宕㈤崡鐐╂斀妞ゆ梹鏋绘笟娑㈡煕閹垮嫮鐣电€规洘娲熷顕€宕奸悢鍝勫箞闂備礁鍟块幖顐﹀磹鐠囪铏光偓娑欙供濞堜粙鏌ｉ幇顒佲枙闁稿孩妫冮弻鈩冩媴缁嬪簱鍋撻崸妤€绠栭柛鎾楀倹鍕冮梺鑺ッˇ閬嶎敊閹达附鈷掗柛灞捐壘閳ь剛鍏橀幊妤呭醇閺囩偟鐤囬梺鐟板⒔缁垶宕戦妶澶嬬厪濠电偛鐏濋崝瀛樼箾閸忚偐澧甸柡宀嬬秮閹垻绮欏▎鐐棑闂備礁鎼鍛矓瑜版帒钃熸繛鎴欏灩閻掓椽鏌涢幇顒€鈷旈柛鏃堫棑缁辨挻鎷呴崫鍕ㄦ瀰缂備胶濮甸悧鐘差嚕鐠囨祴妲堟俊顖炴敱椤秹姊洪崨濠庢畼闁稿鍋ら幃妯侯吋婢跺鈧敻鎮峰▎蹇擃仾缂佲偓閳ь剟姊哄ú璇插箹闁稿﹤鐏濋锝嗙節濮橆厽娅栭梺鍛婃处娴滄繈宕熼崘顔解拺闁告稑锕ョ€垫瑩鏌涢弴銊ヤ簻闁诲骏绻濆濠氬磼濞嗘劗銈板銈嗘礃閻楃姴鐣锋导鏉戠婵°倐鍋撻柣銈夌畺閺岋絽螣閸喖鎯為悗瑙勬尫缁舵岸寮诲☉銏犖ㄩ柨婵嗘噹椤绻濆▓鍨仭闁瑰憡濞婂璇测槈閵忊剝娅嗛柣鐘叉处瑜板啰绮婚崫鍕ㄦ斀闁绘﹩鍠栭悘顏堟偨椤栨せ鍋撻幇浣圭稁婵犵數濮甸懝鍓у閸忚偐绠鹃柛鈩兠慨澶愭煏閸喐绶叉い顏勫暣婵″爼宕卞Ο纰辨О闂備胶绮〃鍫熸叏閹绢喗鍋╅梺鍨儏椤曢亶鏌℃径瀣仼妞ゆ梹甯￠弻锝夋偐閸欏鈹涢柣蹇撶箲閻熲晠寮澶嬪亜闁稿繐鐨烽幏鍝勨攽椤旂偓鍤€婵炲眰鍊濋幃姗€顢欐慨鎰盎濡炪倖鎸鹃崑鐔告櫠閿旈敮鍋撳▓鍨灈闁硅绱曠划顓㈡偄閻撳海鍔﹀銈嗗笒鐎氼剟鎷戦悢鍏肩厽闁哄倸鐏濋幃鎴︽煕鐎ｎ亶鍎旈柡灞剧洴椤㈡洟濡堕崨顔句簴闂備礁鎲￠崺濠勬崲濠靛棭娼栭柧蹇撴贡绾惧吋淇婇姘儓妞ゎ偄鐭傚娲箰鎼淬垹顦╂繛瀛樼矤娴滄粓顢氶敐鍡欑瘈婵﹩鍓欏畵鍡涙⒑缂佹ɑ顥嗘繛鍜冪秮椤㈡瑩寮撮姀鈾€鎷洪梺鍛婃崄鐏忔瑩宕㈠☉銏＄厱闁绘ê纾晶顒勬煙娓氬灝濡兼い鎾炽偢瀹曞爼鍩￠崘璺ㄩ棷婵犵數鍋為幐濠氭嚌閹灐娲Χ婢跺﹥杈堝┑鐐叉閹稿鎮￠弴銏＄厪濠㈣埖绋撻崚鏉库攽閿涘嫬鍘撮柡宀€鍠栭弻銊р偓锝庡亖娴犮垽姊洪崫鍕効缂傚秳绶氶獮鍐煛閸涱厾鐓戞繝銏ｆ硾婢跺洭寮澶嬧拺閻犲洩灏欑粻鎵磼缂佹ê鐏撮柟顔炬焿椤︽挳鏌涢幒鎾崇瑲缂佺粯绻傞～婵嬵敆閸屻倕鏁堕梻鍌欑閸氬绂嶆禒瀣？闁规儼妫勯崒銊╂⒑椤掆偓缁夌敻鎮￠悢鐓庣闁圭⒈鍘奸悘锝囩磼婢跺本鏆柡灞剧洴楠炴鈧潧鎲￠崳顓㈡⒑缂佹﹩娈旀繛鎾棑濡叉劙骞樼拠鑼紲濠电偛妫欓崹鍨繆閽樺鏀芥い鏃傘€嬪銉︺亜椤撶偛妲婚柣锝夋敱鐎靛ジ寮堕幋婵嗘暏闁荤喐绮岀换妯侯嚕閹惰姤鏅濋柍褜鍓熼崺鐐哄箣閿曗偓绾惧吋绻濇繝鍌涙崳闁告梻顭堥—鍐Χ鎼粹€茬盎闂佺娅曢敃銏狀嚕婵犳艾鍗抽柨娑樺閺夋悂鏌ｆ惔顖滅У濞存粎鍋炵€靛ジ宕熼娑掓嫼闂佸憡绋戦敃銉╂偂閵夆晜鐓熼柡宥庡亜鐢埖銇勯銏㈢闁圭厧婀遍幉鎾礋椤愩倕閰遍梻鍌欑濠€杈╁垝椤栨粍鏆滈柟鐑樺毄閹烘绠涙い鏂垮⒔閿涙繈姊虹粙鎸庢拱婵ǜ鍔岄悺顓熺節绾版ɑ顫婇柛瀣噽閹广垽宕掗悙鏉戜患闂佺粯鍨煎Λ鍕棯瑜旈幃褰掑炊閳轰椒澹曞┑鈽嗗亜閸燁偊鎮鹃悜钘壩╅柍鍝勶攻閺咃綁姊虹紒妯曟垼銇愰崘顏嗕笉闁绘劗鍎ら埛鎺楁煕鐏炲墽鎳嗛柛蹇撴湰閵囧嫰濮€閻欏懓鍚Δ鐘靛仦閹瑰洭銆侀弮鍫濋唶闁绘柨寮剁€垫牠姊绘担鍛婂暈婵炶绠撳畷褰掓焼瀹ュ懐锛涢梺绋挎湰缁嬫挾绮绘ィ鍐╃厱闁斥晛鍘鹃鍫熷€堕柍鍝勫暟濡垶鏌熺憴鍕妞ゃ儱顦靛Λ浣瑰緞閹邦厾鍙嗗┑鐘绘涧濡瑦鍒婇崗鑲╃闁兼祴鏅涙牎闂侀潧娲ょ€氼垳绮诲☉銏犵闁圭⒈鍘介敓銉х磽閸屾瑨鍏屽┑顕€娼ч～蹇旂節濮橆剛鐤呴梺褰掓？缁€浣肝涘Ο鑽ょ闁糕剝锚閸斻倖绻涢崼娑樺缂佺粯绋撻埀顒傛暩椤牆鐡俊鐐€栭崹闈浳涘┑鍡╁殨闁哄被鍎辩粻鐟懊归敐鍛础闁告妫勯埞鎴﹀煡閸℃浠紓渚囧櫘閸ㄥ爼骞冨鈧弻鍡楊吋閸℃瑥骞嶉梻鍌欑閻忔繈顢栭崱娑樜︽繝闈涙处閸欏繐鈹戦悩鎻掓殲闁靛洦绻勯埀顒冾潐濞插繘宕濆鍥ㄥ床婵犻潧顑呯粈瀣亜閹捐泛校婵炲牆銈稿缁樻媴缁涘娈柣搴㈢▓閺呯姴鐣峰▎鎺嬩汗闁圭儤鍨甸悗顓㈡⒑鐟欏嫬鍔舵俊顐㈠閹偤宕归鐘辩盎闂佺懓鎼粔鐑藉礂瀹€鍕厽闁瑰灝鍟悘锕傛煛鐏炲墽鈽夐摶鏍归敐鍥┿€婇柡瀣懇閹鈻撻崹顔界亪濡炪値鍙冮弨杈ㄧ┍婵犲洤绠瑰ù锝呮憸閸樺憡绻涙潏鍓ф偧妞ゎ厼鐗忕划濠囶敊閹存帞绠氶梺缁樺姦娴滄粓鍩€椤掍焦绀堥柟骞垮灲楠炲洭顢栭埡鍌溾槈闁宠棄顦垫慨鈧柣妯虹枃缁躲垽姊绘笟鈧褔鎮ч崱娑樼疅婵せ鍋撶€殿噮鍣ｅ畷濂告偄閾氬倹鐫忛梻鍌氬€搁崐鎼佹偋婵犲嫮鐭欓柟閭﹀枛閸ㄦ繈鏌涢幘鑼跺厡缁炬崘妫勯湁闁挎繂鐗婇鐘绘偨椤栨稓娲撮柡灞诲姂瀵潙螣閾忛€涚礄闂備胶绮笟妤呭闯閿濆懐鏆︽慨妞诲亾妞ゃ垺鐟╅幊鏍煛娴ｅ摜顔囬梻鍌氬€风粈渚€骞夐敓鐘茬闁硅揪绠戠粈澶屸偓骞垮劚椤︿即宕愰悽鍛婄厱闁归偊鍘鹃妶鎾煛閳ь剚绂掔€ｎ偆鍘撻梺鑺ッˇ浼此夊鍫熺厽闊洤顑呴崝婊兦庨崶褝宸ユい顏勫暣閹剝鎯旈埥鍡欌偓瀵哥磽閸屾瑧鍔嶆慨濠傤煼瀹曚即寮借閸ゆ洟鏌熺紒銏犳灍闁稿﹦鍏橀弻宥夊传閸曨偀鍋撹ぐ鎺戠骇闁归棿鐒﹂埛鎺懨归敐鍫燁仩閻㈩垱鐩弻娑㈠籍閳ь剟鎮ч弴鈶┾偓锕傚炊瑜夐弸搴ㄦ煙閻愵剚缍戦柍褜鍓欓悥濂稿蓟閵娾晛鍗抽柣鎰ゴ閸嬫捁銇愰幒鎾充簵闂佺粯鏌ㄩ崥瀣偂閻斿吋鐓涢柛銉ｅ妽閻ㄦ垶銇勯敂鑲╃暤闁哄矉缍€缁犳盯濡疯閺嗐倝姊洪崫鍕伇闁哥姵鐗犻妴浣糕枎閹惧磭鐣鹃悷婊冭嫰鍗遍柟鎵閳锋垿鏌ｉ悢绋款棆闁挎稑绉归弻娑氣偓锝冨妼閳ь剚鐗楃粚杈ㄧ節閸ャ劌鈧鏌ら幁鎺戝姕婵炲懏绮撳娲川婵犲啫顦╅梺鍛娚戦崕鎶藉煝閺冨牆閿ゆ俊銈勮閹峰姊虹粙鎸庢拱闁告垵缍婇幃锟狀敆閸曨剛鍘遍柣搴秵娴滄粓顢旈埡鍛亗闁靛牆顦伴悡銉╂煛閸モ晛浠滈柍褜鍓欓幗婊呭垝婵犳艾绾ч幖瀛樻尰閺傗偓闂備胶绮敋闁汇倕娲︾粩鐔奉潨閳ь剟寮婚敐澶娢ч幖绮瑰墲閻濇繈姊洪崫鍕効缂傚秳绶氶悰顕€宕堕澶嬫櫓闂佽姤锚椤︻偊寮歌箛娑欌拺闁荤喐婢橀幃鎴︽煟閿濆簼閭€规洘绻傞悾婵嬪礋椤掆偓閳ь剙鍢查埞鎴︽偐閹绘帩浠鹃梺鍝ュУ閸旀牜鎹㈠┑瀣棃婵炴垵宕崜鎶芥⒑閸涘﹦鎳勬繛鍙夛耿婵＄敻宕熼姘鳖唺闂佺硶鍓濋妵鐐寸珶閺囥垺鈷掑ù锝呮憸閺嬪啯銇勯銏╂█鐎规洖缍婂畷绋课旈埀顒勫垂閸岀偞鐓欐い鏍ф閹冲繐鈻撴ィ鍐┾拺闁硅偐鍋涢崝鈧梺鍛婁緱閸樿偐绮诲ú顏呪拻濞达絿鐡旈崵娆愭叏濮楀牏鐣甸柨婵堝仦瀵板嫭绻涢幒鎾淬仢鐎殿喖鈧噥妲鹃梺鍝勬４闂勫嫰濡甸崟顖氱闁瑰瓨绻嶆禒濂告⒑缂佹ɑ灏扮紒璇茬墦閻涱噣寮介‖銉ラ叄椤㈡鍩€椤掑嫬鐒垫い鎺嶇贰濞堟粓鏌熼鍏煎仴闁糕斁鍋撳銈嗗笒鐎氼參鍩涢幋锔界厱婵犻潧妫楅鈺呮煛閸℃韬柡灞剧〒閳ь剨缍嗛崑鍛焊娴煎瓨鐓忛柛銉戝喚浼冮悗娈垮櫘閸ｏ綁宕洪埀顒併亜閹烘垵顏╃紒鈧径瀣╃箚闁靛牆鎳庨弳鐐淬亜椤愶絾绀嬮柡宀€鍠栭獮鎴﹀箛闂堟稒顔勭紓浣哄亾閸庢娊宕ョ€ｎ喖绠為柕濞垮労濞笺劑鏌涢埄鍐炬當妤犵偛顑夊铏圭矙濞嗘儳鍓遍梺鐟版啞閹倿骞冩ィ鍐╂櫢闁绘灏欓悿鍥ㄧ節閻㈤潧孝闁稿﹨宕电划鏃堟惞閸忓浜鹃悷娆忓缁€鈧梺缁樼墪閸氬绌辨繝鍥х濞达綀顫夊▍婊堟⒑閸涘﹥澶勯柛姗€绠栭幃鈩冨緞閹邦厸鎷婚梺绋挎湰閻熝囁囬敃鍌涚厵閻犲泧鍛紵缂傚倸鍊归幑鍥х暦缁嬭鏃堝焵椤掑倸顥氶柛褎顨嗛悡娆戠磽娴ｅ顏嗙箔瑜旈弻锟犲幢椤撶姷鏆ら梺鍝勭焿缁辨洘绂掗敂鐐珰闁圭粯甯掗～姘舵⒒娴ｈ櫣甯涢柟姝岊嚙鐓ゆ慨妞诲亾濠碉紕鏁诲畷鐔碱敍濮樿京鏉告俊鐐€栭弻銊╁Φ濞嗘挸顫呴柕鍫濇閸橀亶姊洪崫鍕偓浠嬵敋瑜旈崺鈧い鎺嶇贰濞堟粓鏌涢埞鎯т壕婵＄偑鍊栫敮鎺楀窗濮橆剦鐒介柟鎵閻撴瑩鏌涘┑鍕姎闁告ɑ鎸抽弻鐔兼惞椤愵偅鐤侀悗瑙勬礀閵堢顕ｉ幘顔藉€烽梻鍫熺☉琚濇繝纰夌磿閸嬫垿宕愰弽褜鍟呭┑鐘宠壘绾惧鏌熼幆褍顣崇痪鎯с偢閺岋絽螣閸喚姣㈤柡浣哥墦閹鎲撮崟顒傤槰濠电偠灏欓崰鏍ь嚕婵犳艾骞㈡俊銈呭暞濞堝ジ姊洪棃娑辨Ф闁稿孩鐓″畷鏉课熷Ч鍥︾盎闂侀潧楠忕槐鏇㈠煡婢跺浜滄い鎾寸矊婵倻鈧娲忛崝鎴︺€佸Δ鍛＜婵犲﹤瀚弸鎾斥攽閻樺灚鏆╁┑顔炬暬椤㈡瑩寮介鐐电崶濠德板€曢幊澶愬焵椤掑﹦鐣电€规洖銈搁幃銏㈢礄閻樼數鐓夐梻鍌欑缂嶅﹤螞鐠恒劎鐭嗗ù锝堟閻滅粯淇婇妶鍛櫤闁绘挻鐟╁娲敇閵娧呮殸闂佸搫顑嗛幑鍥蓟濞戞埃鍋撻敐搴′簼鐎规洖鐭傞弻锝呪槈閸楃偞鐝濋悗瑙勬礀缂嶅﹪銆佸▎鎾村亗閹兼惌鍠楃紞鎾绘⒒閸屾艾鈧兘鎳楅崼鏇炵疇闁圭偓鍓氶崵鏇㈡煕椤愶絾绀冮柛搴″閵囧嫰寮介顫埛閻庤鎸风欢姘跺蓟閻斿吋鍊绘慨妤€妫欓悾鍓佺磽娴ｅ搫鞋鐎规洜鏁婚崺鈧い鎺戝枤濞兼劖绻涢崣澶屽ⅹ閻撱倝鏌曟繛鐐珕闁稿蓱閵囧嫰寮村Δ鈧禍鎯р攽椤旂》榫氭繛鍜冪秮楠炲繘鎮╃紒妯烘濡炪倖甯掗崑鍡涘船濞差亝鈷掑ù锝勮閻掔偓銇勯幋婵囧枠鐎规洘鍨挎俊鍫曞川椤栨稒顔曢梻浣告惈濞层垽宕归崷顓犱笉妞ゆ洍鍋撻柡宀嬬畱铻ｅ〒姘煎灡绗戦梻浣规偠閸婃牠宕归崹顕呮綎闁惧繗顫夐崗婊堟煕濞戝崬鏋涙繛鎳峰洦鈷掗柛灞捐壘椤忊晠鎮楀顐㈠祮鐎规洖鎼埥澶愬閻樻鍚呴梻浣虹帛椤洭寮幖浣规櫖婵犻潧娲ㄧ粻楣冨级閸繂鈷旈柟顔煎悑缁绘盯宕ㄩ銏痪缂備焦顨堥崰搴ㄥ煡婢跺ň鏋庨柟瀵稿閸熷酣姊绘担绋款棌闁稿妫濆畷浼村箛閸忣偄顦靛畷濂稿Ψ閿旀儳骞愰柣搴″帨閸嬫捇鎮楅敐搴″闁糕晛鐭傞弻褏绱掑Ο鐓庘拰闂佸搫鑻粔鐑铰ㄦ笟鈧弻娑㈠箻鐠虹儤鐏堥悗娈垮櫘閸嬪﹤鐣峰鈧、娆撴嚍閵夛妇褰嗛梻鍌欐缁鳖喚寰婃禒瀣剹闁割偅绶峰ú顏勭濞达絽鍘滈幏娲偡濠婂懎顣奸悽顖涱殜閺佸秹鎮㈤搹鍦紲闁荤姳绀佸﹢杈╁姬閳ь剟鎮楀▓鍨珮闁稿锕ら悾鐑藉醇閺囥劍鏅㈡繛杈剧到閹碱偊鐛Δ鍛拻濞达絿鍎ら崵鈧梺瀹︽澘濡块柟骞垮灲瀹曟﹢顢欓姀鐙€妯€闁诡喒鏅濈槐鎺懳熼悡搴＄疄闂傚倷鑳剁划顖炲礉閺囥垺鍊舵慨妯挎硾濮瑰弶銇勯幒鎴濐仾闁绘挻鐟﹂妵鍕籍閸屾艾浠樺┑陇灏欑划顖炲Φ閸曨垼鏁囨繝濠傚暙椤洭鎮楃憴鍕闁挎洏鍨介妴渚€寮崼婵嗚€块梺瀹犳〃閻掞箓寮抽鐘电＝闁稿本鑹鹃埀顒佹倐瀹曟劙鎮滈懞銉ユ畱闂佸憡鎸风粈渚€宕瑰┑鍥ヤ簻闁哄稁鍋勬禒锕傛煕鎼粹€愁劉闁靛洤瀚板浠嬵敃椤厾鎹曢梻浣告惈鐎氥劑宕曢悽绋胯摕鐎广儱鐗滃銊╂⒑閸涘﹥灏扮€光偓閸涘﹣绻嗛柣銏㈩焾缁€瀣亜閺嶃劍鐨戞い鏂匡躬濮婃椽鎮烽幍顔芥喖缂備焦妞界粻鏍х暦閹达箑绠荤紓浣姑禒铏圭磽娴ｅ壊鍎撴繛澶嬫礋閺佸秴鈽夐姀鈾€鎷洪梺闈╁瘜閸樺吋绂嶆ィ鍐╃厸閻庯綆浜楅崑銏⑩偓娈垮枟閹倸顕ｉ鈧畷濂告偄閸濆嫬绠炲┑锛勫亼閸娿倝宕㈡禒瀣瀭闁汇垻顭堥崙鐘绘煟閺傚灝鎮戦柣鎾跺枛閻擃偊宕堕妸锔规嫻閻庤娲栭張顒勫箞閵婏妇绡€闁告洦鍋勬俊鍝勨攽閻愮鎷″ù婊庝邯閻涱喖顓兼径妯绘櫔闂佸憡渚楅崯鈺侇煥閸曨亞绠氶梺缁樺姦娴滄粓鍩€椤戞儳鈧繂鐣烽姀锛勯檮缂佸鐏濈花銉╂⒑閸濆嫯顫﹂柛搴㈢叀瀹曟垿鍩￠崘锝呬壕闁荤喐婢橀顏堟煕閿濆棙缍戦悡銈嗐亜韫囨挾校闁哄懏绮撳娲川婵犲啫顦╅梺鍛娒崥瀣箞閵娾晜鏅滈柟瀛樺笧缁犳岸姊虹紒妯哄Е濞存粍绮撻崺鈧い鎺嶈兌婢ч亶鏌℃笟鍥ф灍缂佺粯绻堝畷鍫曞Ω閵忊€崇槺闂佽楠哥粻宥夊磿閸楃倣娑樷槈椤兘鍋撻崨鏉戠煑濠㈣泛鐬奸惁鍫熺節閻㈤潧孝闁稿﹦绮弲璺衡槈閵忥紕鍘介梺瑙勫劤椤曨參骞婇崶顒佺厸閻忕偛澧介埥澶愭煃鐟欏嫬鐏寸€规洖宕灃濠电姳鑳剁壕濠氭⒒娴ｅ憡鎲搁柛鐘冲姍楠炲啴宕掑鍏肩稁闂佹儳绻愬﹢閬嶆儗濞嗘挻鍋ｉ柟顓熷笒婵℃寧銇勯弬鎸庡枠婵﹤鎼叅閻犲洦褰冪粻褰掓⒑缁嬪尅宸ラ柣蹇旂箞椤㈡岸鏁愰崶銊ョ彴閻庣懓澹婇崰鏍箖閹达附鈷戦柟鑲╁仜閸旀鏌￠崨顔剧疄闁轰礁绉撮…銊╁礃閿濆棙鏉搁梻浣哥枃濡嫬螞濡ゅ懏鍊堕柨婵嗩槹閻撴洟骞栨潏鍓хɑ闁哄棭鍓氶〃銉╂倷閼碱剛顔夌紓浣虹帛缁诲倿锝炲┑瀣垫晣婵炴垶鐟ラ褰掓⒒閸屾艾鈧娆㈤敓鐘茬；闁糕剝绋戠壕缁樼箾閹存瑥鐏柛銈嗗姈閵囧嫰寮介妸褉濮囧┑鐐叉噽婵敻濡甸崟顖氭闁割煈鍠掗幐鍐磼閻愵剙鍔ら柕鍫熸倐瀵鏁愰崨鍌滃枛瀹曞綊顢欓悙顒夊殑闂備浇妗ㄧ粈渚€鎮ч幘璇茬畺婵°倕鍟崰鍡涙煕閺囥劌澧版い锔哄妼閳规垿鎮欑捄铏规闂佸摜濮撮柊锝夊箖妤ｅ啯鍊婚柤鎭掑劜濞呫垽姊虹紒妯忣亪宕崸妤€鐒垫い鎺嗗亾濠⒀冩捣濡叉劙骞樼€涙ê顎撻梺鍏肩ゴ閸撴繈宕归幐搴濈箚闂傚牊绋堥弨浠嬫倵閿濆骸浜為柛姗€娼ч—鍐Χ閸℃﹩姊垮銈庡亜椤︻垶鍩㈠澶婄倞妞ゆ帊鑳堕崢鍨繆閻愬樊鍎忓Δ鐘虫倐閸┿垽宕奸妷锔惧幍閻庤娲栧ú銈夊煝閸喆浜滈柕蹇婃濞堟粓鏌涢埞鎯т壕婵＄偑鍊栫敮濠囨倿閿曞倸鐭楅煫鍥ㄧ⊕閻撱儵鏌￠崘锝呬壕闂佹悶鍔嶇换鍕箲閵忋倕骞㈡繛鎴炵懅閸樹粙姊虹憴鍕凡闁告埃鍋撶紓浣靛妼椤兘寮诲鍫闂佸憡鎸诲畝鎼佸箖瑜嶉…銊╁醇濠靛洨鈧剙顪冮妶鍡樷拻闁哄拋鍋嗗褔鍩€椤掑嫭鈷戦柛娑橈攻婢跺嫰鏌涢幙鍕暤鐎规洘鍨挎俊鎼佸煛閸屾瀚奸梺鑽ゅУ娴滀粙宕濆畝鍕嚑闁哄倸绨遍弨鑺ャ亜閺冨倸浜鹃柡鍡╁墰閳ь剝顫夊ú姗€宕濆▎蹇曟殾鐟滅増甯╅弫濠冩叏濮楀棗澧扮紒澶嬫そ閺岀喖顢欑憴鍕彅濡炪倖鏌ㄧ换姗€銆佸▎鎾村亗閹肩补妲呭Λ濠囨⒒閸屾艾鈧兘鎳楅崜浣稿灊妞ゆ牜鍋涚粻浼存煙闂傚顦﹂柣銈庡枛闇夐柛蹇撳悑缂嶆垹绱掗悩闈涙灁缂佽鲸甯為埀顒婄秵閸嬫帡宕曢妷鈺傜厽闁规儳宕崝锕傛煛鐏炲墽娲存い銏℃礋閺佹劙宕堕埡鍐╂瘔濠碉紕鍋戦崐褏鈧潧鐭傚畷銏＄附缁嬭法鍘撮梺纭呮彧闂勫嫰宕戦幇顔剧＝濞达綀鍋傞幋锔界叆妞ゆ挾鍎愬〒濠氭煏閸繃顥滈柣蹇ョ畵閺屾盯濡搁妷锕佺濠碘€冲级閸旀瑩骞冨▎鎾充紶闁告洦鍋勯弫銈夋煟閻斿摜鐭嬬紒顔芥崌楠炲啴濮€閵堝懎鑰垮┑鐐村灦閻熴儲绂掗鐐寸厸濠㈣泛鑻禒锕€鈹戦娆戠煓妞ゃ垺顨婇幃銏ゅ礂閼测晛骞楅梻浣烘嚀閻忔繈宕锝嗘珷妞ゆ牗绮庣壕鑲╃磽娴ｈ鐒介柕鍡樺笒闇夋繝濠傚閸婃劗鈧鍠曠划娆愪繆閹间焦鏅滈柟顖嗗懐袪闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧€氬銇勯幒鍡椾壕闁绘挶鍊栨穱濠囶敍濮橆剚鍊悗瑙勬礀瀵墎鎹㈠☉銏犵婵炲棗绻掓禒濂告⒑閹肩偛濡奸柛濠傜秺婵＄敻宕熼姘辩潉闂佺鏈懝鐐濡警娓婚柕鍫濋娴滄粓姊虹敮顔惧埌妞ゎ偄绻掔槐鎺懳熺拠宸偓鎾绘⒑閸涘﹦鈽夐柨鏇樺劦瀹曟洟骞橀幇浣瑰瘜闂侀潧鐗嗗Λ妤呮倶閵夛缚绻嗘い鎰剁秵濞堟瑩鏌ｈ箛鎿冨剶婵﹥妞藉畷銊︾節閸屾鏇㈡⒑閸濄儱校闁绘濞€楠炲繘骞嬮敂钘変簻闂佺绻楅崑鎰板储娴犲鈷戦柛婵嗗閺嗘瑦绻涚仦鍌氱伈闁糕斁鍋撳銈嗗灱濡嫭绂嶆ィ鍐┾拻濞达絼璀﹂悞鐐亜閹存繃顥㈡鐐村灴瀹曞爼顢楅埀顒傜不閺嶎厽鐓㈡俊顖欒濡叉挳鏌＄€ｎ偅顥堥柟顔肩秺楠炰線骞掗幋婵愮€冲┑鐘愁問閸犳岸宕㈣閸╃偤骞嬮敂钘夆偓椋庘偓鐟板閸犳牕鈻撻懜鐢电瘈婵炲牆鐏濋弸娑氱磼婢跺本鍤€闁伙絿鍏樺畷濂稿即閻愬秮鏅濋幉绋款吋閸ャ劍娈板┑掳鍊曢崯鎵娴犲鐓曢悘鐐村礃婢规﹢鏌嶈閸撴盯宕楀鈧獮鍐倷閻戞ɑ娅囨繛杈剧秬椤宕冲畡鎵虫斀闁挎稑瀚禍濂告煕婵犲啫鐏寸€规洘娲熼弻鍡楊吋閸℃ぞ缃曢梻浣筋潐瀹曟﹢顢氳閹锋垿鎮㈤崗鑲╁弳濠电偞鍨堕敋妞ゅ景鍕鐎光偓婵犱線鍋楅梺鍝勭焿缂嶄線寮幇鏉垮窛妞ゆ牗绋戞禒鎾⒒娓氣偓濞佳嚶ㄩ埀顒勬偣閹邦喖鏋戠紒鍌氱Т椤劑宕ㄩ鍏肩€鹃柣搴″帨閸嬫捇鏌嶈閸撴瑩鍩㈡惔銊ヮ潊闁绘瑢鍋撴繛灏栨櫊閹懓煤椤忓棛绐楅梺纭呭Г濞叉牠鍩為幋锔藉€烽柡澶嬪灩娴犙囨⒑閹肩偛濡兼繝鈧潏鈺佸灊缂備焦顭囩弧鈧┑顔斤供閸樺吋绂掗鐐粹拺闁诡垎鍛唺闂佺娅曢幑鍥х暦濠靛牃鍋撻敐搴℃灍闁绘挾鍠栭悡顐﹀炊閵婏箑鏆楁繝鈷€鍕闁硅棄鐖煎浠嬵敇閻斿搫骞楁繝娈垮枟閵囨盯宕戦幘瀵哥濞达絽鍟跨€氼噣銆呴柨瀣瘈濠电姴鍊绘晶娑㈡煟閹惧瓨绀嬮柡宀嬬秮瀵潙顫濇鏍ㄐ滃┑鐐茬摠缁牓宕￠幎钘夎摕婵炴垯鍨归悡姗€鏌涢…鎴濇灓濞寸娀绠栧铏规嫚閳ュ磭浠┑鈽嗗亜閸燁垱绌辨繝鍥х濞达綀鍊介妸褎鍠愭繝濠傜墕閻ゎ噣鎮楅敐搴℃灍闁抽攱甯掗湁闁挎繂鎳忛崯鐐烘煙椤栨氨澧涢柕鍥у閺佸倿宕归鑲┿偖闁诲氦顫夊ú鏍礊婵犲倻鏆︾憸鐗堝俯閺佸啴鏌曢崼婵囨悙濡ょ姴瀚板缁樻媴閸涘﹤鏆堥梺鍛婃缁犳挸鐣烽弶璇炬棃宕ㄩ鐘插箞闂備礁婀遍崕銈夊吹濮樼偨浜归柟鐑樻尰濞呮粓姊洪崨濠佺繁闁哥姵鐗犲鎶藉醇閵夛腹鎷洪梺鍛婄缚閸庨亶寮搁弮鍫熺厱閻庯綆鍓欓弸鏃€淇婇崣澶婂妤犵偞甯掕灃闁逞屽墯鐎靛ジ鎮╃紒妯煎幈闂佸搫娲㈤崝灞炬櫠椤旀祹褰掓偐閾忣偄鍞夐梺璇″枟椤ㄥ牓骞夐幘顔肩妞ゆ帒鍋嗗Σ鐗堢節閻㈤潧浠╅悘蹇旂懇瀹曚即寮介鐔蜂粧濡炪倖妫佹慨銈夊磿閻斿吋鐓忓┑鐐茬仢閸斻倖銇?"
                "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃闁硅櫕鎹囬垾鏃堝礃椤忎礁浜鹃柨婵嗙凹缁ㄥジ鏌熼惂鍝ョМ闁哄矉缍侀、姗€鎮欓幖顓燁棧闂備線娼уΛ娆戞暜閹烘缍栨繝闈涱儐閺呮煡鏌涘☉鍗炲妞ゃ儲鑹鹃埞鎴炲箠闁稿﹥顨嗛幈銊╂倻閽樺锛涘┑鐐村灍閹崇偤宕堕浣镐缓缂備礁顑嗙€笛囨倵椤掑嫭鈷戦柣鐔告緲閳锋梻绱掗鍛仸鐎规洘鍨块獮鍥偋閸垹骞堥梻浣哥秺閸嬪﹪宕归幍顔筋潟闁挎洖鍊归悡鐔兼煏韫囧鐏悽顖涚☉鑿愰柛銉戝秷鍚梺璇″枟閻熲晠銆侀弮鍫濈闁靛鍎版竟鏇㈡⒑閸濆嫮鈻夐柛妯圭矙瀹曟垹鈧綆鍋傜换鍡涙煏閸繃鍣归柡鍡欏枛閺岋綁顢橀悢鐑樺櫚闂佸搫鐬奸崰鏍箖濞嗘搩鏁嗛柛灞剧瀵挳姊绘笟鈧埀顒傚仜閼活垱鏅堕鈧弻鐔兼惞椤愨偓椤忓牊鍋╅柣鎴ｅГ閺呮煡鏌涢埄鍐炬畼缂佹劗鍋ら幃妤呭礂婢跺﹣澹曢梻渚€鈧偛鑻晶鎾煙椤栨瑧绐旂€规洖銈搁幃銏ゆ惞閸︻厽顫岄梻鍌欑劍閻綊宕归挊澶樼劷鐟滃秹鎮洪銏♀拻濞达絼璀﹂悞楣冩煥閺囶亜顩柛鎺撳浮椤㈡盯鎮欓懠顒佺叄闂佽崵濞€缂傛岸濡撮埀顒佷繆閹绘帞澧﹂柡灞炬礉缁犳盯濡疯閿涚喖姊洪崨濠忚€垮ù婊冪埣瀵鏁愰崱妯哄妳濡炪倖鐗楃划宀勫春瀹€鍕拺闁告稑锕ら悞褰掓煕鐎ｎ偅宕屾慨濠勭帛缁楃喖宕惰鐎涳綁姊洪幖鐐插闁绘牜鍘ч锝嗙節濮橆厽娅栭梺鍛婃处娴滄繈宕熼崘顔解拺闁告稑锕ョ€垫瑩鏌涢弴銊ヤ簻闁诲骏绻濆铏规嫚閹绘帩鍔夊銈嗘⒐閻楃姴鐣烽弶璇炬棃宕ㄩ鐙€鍞堕梻浣瑰劤濞存岸宕戦崒婊勫床闁糕剝绋掗悡娆撴⒒閸屾凹鍤熸い锔肩畵瀹曨剟顢涢悙鏉戜画濠电姴锕ら崯浼存倿閹间焦鐓欐い鏂跨仢琚氱紓浣虹帛缁诲倿锝炲┑瀣垫晣婵炴垶鐟ラ鐑樼節閻㈤潧浠╅柟娲讳簽瀵板﹪鎳栭埡鍌氼€忛梺鎸庢礀閸婂綊宕愰崸妤佺厽闁逛即娼ч崢闈浢瑰鍕煉闁哄瞼鍠撻埀顒佺⊕椤洨绮婚弽銊ｄ簻闁靛／鍐ｆ瀰闂佸搫鐬奸崰鏍偘椤曗偓瀹曞綊顢欓崣銉х闂佽姘﹂～澶娒哄Ο鍏兼殰闁圭儤顨呴悡姗€鏌熸潏鍓х暠闂佸崬娲︾换婵囩節閸屾稑娅х紓浣割槹鐎笛呮崲濠靛鍋ㄩ梻鍫熷垁閵夛负浜滈柨婵嗙墛椤ュ宕￠柆宥嗙厱婵炴垶鐟︾紞鎴犵棯閹规劦鍤欓柍瑙勫灴閹晠宕ｆ径濠備憾闂備線鈧偛鑻晶顕€鏌涙繝鍌涘仴鐎殿噮鍋婂畷姗€顢欓懖鈺佸Е婵＄偑鍊栫敮鎺斺偓姘煎幘缁骞掑Δ浣叉嫽婵炶揪缍€椤宕戦悩缁樼厱閹兼番鍨洪妵婵堚偓瑙勬礃缁矂鍩㈡惔銊ョ闁绘鏁搁崝鍫曟⒒娴ｄ警鐒鹃柣顒€銈稿畷鎴︽倷閸濆嫮锛欓梺鍓插亝濞叉﹢鎮￠悢鍏肩厵闂侇叏绠戦獮妤冪磼閼哥數鍙€闁诡喗顨呴～婵嬵敆閸曠鍋撳Δ鍛梿濠㈣泛顑囩弧鈧繝鐢靛Т閸婃悂顢旈锔界厽妞ゆ挾鍠庡ù顕€鏌″畝瀣М妤犵偞鐟╁畷姗€濡搁妶鍛€抽梺璇叉唉椤煤閺嶎厽鍋夐柛蹇涙？缁诲棝鏌熼梻瀵稿妽闁哄懏绻堥弻宥堫檨闁告挻鐩畷鐗堢節閸屻倕鎮戞繝銏ｆ硾椤戝倿骞忓ú顏呪拺闁稿繗鍋愰妶鎾煛閸涱亝娅婇柟顔惧仱瀹曟粏顦寸痪鍓ф櫕閳ь剙绠嶉崕閬嶅箯閹达妇鍙曟い鎺戝€甸崑鎾斥枔閸喗鐏曞銈嗘肠閸ヨ埖鏅ｉ梺绋跨箳閸樠呮閻愮儤鍊甸柨婵嗙凹缁ㄨ姤淇婄紒銏犳灈闁宠鍨块幃鈺咁敊閼测晙绱橀梻浣虹《閺呮粓鎮ч悙鍝勭妞ゆ劧闄勯埛鎴︽倵閸︻厼顎岄柛銈嗙懇閺岋絽螖閳ь剙螞濠婂牊鍊堕柛鎰靛枟閳锋垹绱撴担鐧稿叕闁肩増瀵х换娑欐媴閸愭彃顏い鈺冨厴閺屻劑寮撮悙娴嬪亾瑜版帗鍋傞柣鏂垮悑閻撶喖鏌￠崒姘变虎缂佺嫏鍕闁告侗鍘介崵鍥煛瀹€瀣М闁轰焦鍔欏畷銊╊敇閻旀壕鏅犻弻褎瀵煎▎鎴犐戠紓浣虹帛閻╊垰鐣烽崡鐐╂瀻闊洤楠搁ˉ姘攽椤旂晫绠撴繛宸幖椤繑绻濆顒傦紲濠电偛妫欓崺鍫澪ｉ灏栨斀闁绘﹩鍋勬禍楣冩⒑閸涘娈橀柛瀣姍瀵顓兼径瀣帾闂婎偄娲ら鍛存倶椤斿墽纾奸柍褜鍓氱换婵嬪磻椤栨氨绉洪柡浣瑰姍瀹曘劑顢樿椤ユ垶绻濋悽闈涗粶闁告艾顑夐幃褔鎮╃拠鑼舵憰閻熸粍鍨圭划璇测槈閵忕姷顔掔紒鐐劤椤戝洭銆侀崨瀛樷拻濞达綀顫夐妵鐔兼煕濡湱鐭欓柟顔惧厴閸╋繝宕ㄩ鐘垫毇闁荤喐绮庢晶妤冩暜閹烘梻涓嶉柟鐑橆殕閻撴瑩鏌ｉ幋鐏活亪鎮橀妷锔轰簻妞ゆ巻鍋撴い鎴濇嚇閳ユ棃宕橀鍢壯囨煕閳╁喚鐒介柛娆忔椤啴濡惰箛鏇犳殼濠电偘鍖犻崶椋庣◤闂婎偄娲﹂幏瀣洪宥嗘櫆闂佸憡娲﹂崣搴ㄥ船閸洘鈷戠痪顓炴噹椤ュ秹鏌熷ú璁崇敖缂佽京鍋ゅ畷鍗炩槈濡槒绶㈤梻浣芥硶閸犳挻鎱ㄩ悽绋跨厱闁硅揪闄勯埛鎺楁煕椤愩倕鏋旈柍顖涙礋閺岀喖宕楅悡搴☆潚闂佽鍠楅〃鍛达綖濠靛鏁囬柣鏂挎惈閸ゆ帗淇婇悙顏勨偓鏍洪埡鍐濞达絽澹婇崵鏇㈡煕椤愶絾绀€缂佺姷濮烽埀顒冾潐濞叉牕煤閵堝鍑犳繛鎴炲焹閸嬫挾鎲撮崟顒€顦╅梺绋款儏閿曘倝鎮鹃悜鑺ュ亜缁炬媽椴搁弲婵嬫倵楠炲灝鍔氭俊顐ｇ懅缁牏鈧綆鍠楅悡娑氣偓鍏夊亾閻庯綆鍓涜摫闂備浇顕栭崹鍗炍涢崘鈺€绻嗛柤绋跨仛閸庣喖鏌曡箛瀣伄閸熷憡绻濋悽闈浶ラ柡浣规倐瀹曟垵鈽夊鍡楁闂佸憡鎸风粈渚€宕瑰┑瀣厵闁诡垎鍜冪礊闂佸搫妫寸粻鎾诲蓟閺囷紕鐤€闁靛／鍛咃絽鈹戦埥鍡楃仩閻庢碍婢橀～蹇涙惞閻熸澘顕ч梺鍝勬川閸犳劙鎮甸弽顓熲拺缂佸顑欓崕宥夋煕婵犲啰绠為柟顔诲嵆椤㈡瑩鏌ㄩ姘闂佹寧绻傛鎼佸几閻斿吋鐓涢柛娑卞枤缁犵偤鏌＄仦鐣屝ユい褌绶氶弻娑㈠箻鐠虹儤鐏堝Δ鐘靛仜閸燁偊鍩㈡惔銊ョ疀妞ゆ柨澧藉Σ鍥⒒娴ｅ憡鍟炴繛璇х畵瀹曟粌鈻庨幘鍐插殤闂佺鎻梽鍕偂濞嗘挻鐓犻柛锔诲幖椤ｈ偐鎲搁幎濠傛噽绾惧ジ鏌ら懝鏉跨厫缁绢厼澧庣槐鎺楊敊绾拌京鍚嬮悗娈垮櫘閸ｏ絽鐣烽悡搴樻斀闁割偒鍋勯弲锝囩磽閸屾艾鈧娆㈤敓鐘茬獥婵炴埈婢佺紞鏍ь熆閼搁潧濮﹂柡浣风窔閺屾盯鍩勯崘顏佸闂佺粯鎸婚惄顖炲蓟瀹ュ牜妾ㄩ梺鍛婃尰濮樸劎鍒掔€ｎ喖绠抽柡鍌氭惈娴滈箖鏌ㄥ┑鍡欏嚬缂併劏濮ら妵鍕棘閸柭ゅ惈濠殿喖锕ㄥ▍锝夊箟閹绢喖绀嬫い鎰╁灩绗戝┑鐘殿暯濡插懘宕戦崟顓涘亾濮樼厧鏋熺紒鏃傚枛瀵挳鎮╅崘鍙夌€梻浣告啞濞诧附绂嶉悙鐢典笉婵鍩栭埛鎴︽⒒閸喓銆掑褎娲熼幃妤€顫濋悡搴㈢彎閻庤娲樼换鍌烆敇閸忕厧绶為悗锝庡墮楠炲牊绻濋悽闈涗粶婵☆偅顨堥幑銏ゅ箳閺冨倷绗夋繝鐢靛У绾板秹鎮″☉姘ｅ亾閸忓浜鹃梺閫炲苯澧寸€规洑鍗抽獮姗€鎳滃▓鎸庣稐闂備礁婀遍崕銈夈€冮崨杈剧稏闁告稑鐡ㄩ悡鐔镐繆椤栨繃顏犻柨娑樼Т闇夋繝濠傚暟閸╋絾鎱ㄦ繝鍕笡闁瑰嘲鎳忕粭鐔碱敍濠婂啫歇闂備浇顕х€涒晝绮欓崼銉ョ柧闁绘顕ц繚闂佸憡鍔﹂崰鏍ь啅濠靛鐓涘璺侯儏濞堥箖鏌曟径鍡樻珕闁绘挻鐟╅弻锝夊箣閻忔椿浜幃鐐烘倷椤掑倻顔曢柣蹇撶箲閻楁鈻嶆繝鍥ㄧ厸閻忕偠顕ф俊濂告煃鐟欏嫬鐏寸€规洖宕灒闁绘垶锕╂禒褎绻濋悽闈浶為柛銊ャ偢閿濈偞寰勬繛鎺撴そ閹垺绺芥径瀣▉缂傚倸鍊烽悞锕佹懌婵犳鍨伴顓犳閹烘垟妲堟慨妤€妫楅崜鏉库攽閻愯尙澧涢柛鏃€鐟ラ～蹇撁洪鍕槶闂佽偐鈷堥崜娆戞暜閵夆晜鈷戦柟鑲╁仜婵″ジ鏌ｉ弽褋鍋㈤柣娑卞櫍瀹曟﹢顢欓挊澶嗗亾閻戣姤鐓熼柟瀵稿€栭幋婵冩瀺闁搞儺鍓氶埛鎴︽⒑椤愩倕浠滈柤娲诲灡閺呭墎鈧稒菧娴滄粓鏌曡箛濞惧亾閸愬弶鎳欏┑鐘殿暜缁辨洟宕楀鈧畷娲焺閸愨晛顎撴繛鎾村嚬閸ㄨ鲸鏅ュ┑鐘殿暜缁辨洟宕戦幋锕€纾归柡宥庡幗閸嬪淇婇妶鍌氫壕濡炪値鍋呯换鍫熶繆閹间礁鐓涢柛灞剧煯閻ヮ亪姊绘笟鈧埀顒傚仜閼活垱鏅堕姣插酣宕惰闊剟鏌熼鐣屾噰妞ゃ垺妫冨畷鐔煎Ω閵夈倕顥氶梻浣告惈缁嬩線宕㈤懖鈺冧笉闁哄顕抽弮鍫熸櫜闁告侗鍘藉▓顓犵磼閹冣挃缂侇噮鍨抽幑銏犫槈閵忕姷顓洪梺缁樺姇閻忔岸宕抽鈧铏圭磼濡偐鐣甸梺缁樼墪閵堢顕ｇ拠娴嬫闁靛繒濮村畵鍡涙⒑闂堟侗鐒鹃柛搴ゆ珪缁傛帡顢橀姀鈾€鎷洪梺瑙勫劶婵倝寮柆宥嗗仺妞ゆ牗绋戝ù顔界節閳ь剚绗熼埀顒€顫忓ú顏勭閹艰揪绲块悾鐢告⒑閻熸澘鏆辩紒缁樏悾鐑筋敍閻愭潙鈧兘鏌ｉ幋鐑嗙劷闁告﹢浜跺铏圭磼濡崵鍙嗛梺鍦拡閸嬪懐绮嬮幒妤佹櫆闁告挆鍜冪床缂傚倸鍊烽悞锕傗€﹂崶顒€违闁圭儤顨嗛悡娆忣渻鐎ｎ亪顎楅棄瀣渻閵堝繘妾柟鍛婂▕瀵鏁愭径瀣珳闂佹悶鍎崝宥呅掗崟顖涒拺闂侇偆鍋涢懟顖涙櫠閸欏浜滄い鎰╁焺濡叉悂鎮￠妶鍡樺弿婵＄偠顕ф禍楣冩倵鐟欏嫭绀€缂傚秴锕ら悾鐤亹閹烘繃鏅╅梺缁樺姦閸撴岸顢欓弴銏♀拻濞达絽鎲￠崯鐐淬亜閵娿儳澧︾€规洘娲熼獮鍥敄闁款垰浜鹃柟鐑樻尵缁♀偓濠殿喗锕╅崢楣冨储椤忓懐绡€闁靛骏绲介悡鎰磼鐎ｎ偅宕岄柟顔惧亾濞煎繘濡歌椤旀洟姊洪崷顓涙嫛闁告ê銈稿鎼佸Χ婢跺鍘撻悷婊勭矒瀹曟粌鈹戠€ｅ墎绋忔繝銏ｆ硾閳洖煤椤忓嫬鍞ㄥ銈嗘尵閸婏綀顦归柡灞剧☉閳藉顫滈崼鐕佹毉缂傚倷娴囬褍螞濠靛钃熼柨婵嗩槸缁狅綁鏌ㄥ┑鍡樺晽闁瑰墽绮悡娑㈡煕濞戝崬鏋ら柣顓熷浮閺屸€崇暆閳ь剟宕伴弽顓溾偓浣糕槈閵忕姴鑰垮┑掳鍊愰崑鎾绘煛閸℃瑥鏋戦柕鍥у瀵剟骞愭惔鈩冪亷婵犳鍠栭敃銈夆€﹀畡鎵殾闁圭儤鍩堝鈺傘亜閹达絾顥夊ù婊勫劤椤啰鈧綆浜滈銏°亜閹邦垰袚闁逛究鍔岃灒闁圭娴烽妴鎰版⒑缂佹ê绗掗柣蹇斿哺婵＄敻宕熼姘鳖唺闂佺懓鐡ㄧ缓楣冨磻閹捐宸濆┑鐘插濞村嫬鈹戦悩璇у伐闁绘锕幃锟犳偐瀹曞洨顔曢梺鐓庛偢椤ゅ倿宕靛▎鎾寸厽闊洢鍎崇弧鈧梺鍝勭焿缁绘繂鐣烽妸鈺婃晣闁绘灏欓崢鑺ヤ繆閵堝洤啸闁稿鍋ら弫鍐閵堝啠鍋撴担绯曟瀻闁圭偓娼欐禒濂告煟韫囨洖浠╂俊顐㈠缁濡烽妷銏℃杸闂佹寧绋戠€氼剚绂嶆總鍛婄厱濠电姴鍟版晶顏呫亜椤愩垻绠洪柕鍥ㄥ姍楠炴帡骞嬮悪鍛惞闂傚倷娴囬～澶愬磿閻撳宫娑㈠礋椤栨氨锛滈梺闈浥堥弲婊堝磹閻㈠憡鐓熼柕蹇嬪灪閺嗏晠鏌曢崱妤嬭含闁哄本绋撻埀顒婄秵閸嬪懐浜搁銏＄厓缂備焦蓱瀹曞瞼鈧娲栫紞濠囥€佸▎鎾村仼閻忕偛銈搁崑妤呮⒒閸屾艾鈧兘鎳楅崜浣稿灊妞ゆ牜鍋為崑瀣節婵犲倻澧曢柛灞诲妿閹叉悂寮崼婵堢暫婵°倧绲介崯顖炲磹閼姐倗纾兼繛鎴烇供閸庢劙鏌￠崪浣稿⒋婵﹨娅ｇ槐鎺懳熼崫鍕垫綑闂佽绻愮换鎴︽偡閳哄嫭顥ら梻渚€娼ц墝闁哄懏绮撻崺娑㈠箣閿旂晫鍘遍梺褰掑亰閸撴瑧鐥閺岀喖顢涘鍗炩叺闂佸搫琚崝鎴濐嚕閺夋嚦鐔煎传閸曨倣鏇㈡⒒娴ｇ瓔鍤冮柛鐘愁殘閳ь剛鐟抽崨顖滅暥闂佺粯姊婚崢褔鎮為崹顐犱簻闁瑰搫妫楁禍鎯ь渻?"
                ""
            )
        return (
            "I hit an issue connecting to the coaching service. Please check your provider configuration and try again. "
            "While that is blocked, keep moving: restate the target behavior, identify the single highest-uncertainty point, "
            "and implement the smallest change you can verify quickly. "
            f"Error: {exc}"
        )

    def _error_reply_with_scaffold(
        self,
        *,
        exc: Exception,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        error_line = self._error_reply(exc, response_language=response_language).strip()
        scaffold = self._scaffold_reply(
            profile,
            message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        ).strip()
        if not scaffold:
            return error_line
        return f"{error_line}\n\n{scaffold}"

    def _missing_api_key_reply(self, response_language: str | None = None) -> str:
        if _prefers_chinese(response_language):
            return "Trainer 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛橆殽閻愯揪鑰块柟宕囧█椤㈡寰勭€ｆ挻绮撳缁樻媴鐟欏嫬浠╅梺鍛婃煥缁夊爼骞戦姀銈呯妞ゆ柨妲堥敃鍌涚厱闁哄洢鍔岄悘鐘绘煕閹般劌浜鹃梻鍌欑窔濞佳嗗櫣闂佸憡渚楅崹鎵暜鎼淬劍鈷掗柛灞剧懅閸斿秹鏌熼鑲╁煟鐎规洘绻傞濂稿炊閵娿儱绨ラ梻浣告啞濞诧箓宕规导瀛樺€块柛顭戝亖娴滄粓鏌熼崫鍕棞濞存粌澧界槐鎾存媴閸濆嫅銏㈢磼婢跺本鍤€闁伙絿鍏樺鎾閿涘嫬濮搁柣搴＄畭閸庨亶骞婇幇閭︽晩闁糕剝绋掗悡鐔煎箹閹碱厼鐏ｇ紒澶屾暬閺屾盯鎮╅幇浣圭杹閻庤娲橀崹鍨暦閻旂⒈鏁嶆繛鎴炶壘楠炲牓姊绘担瑙勭伇闁哄懏鐩畷銏°偅閸愨晛娈愰梺鍐叉惈閸婂憡鎯旀繝鍥ㄢ拺缂侇垱娲栨晶鏌ユ嚕瑜嶉湁婵犲﹤瀚惌鎺楁煛鐏炵硶鍋撻幇浣告倯闂佸憡鍔戦崝宀勨€栫€ｎ喗鈷戞繛鑼额嚙楠炴牠鏌ㄩ弴銊ら偗鐎殿喖顭烽弫鎰緞婵炩懇鏅犻弻銊╁即濡も偓娴滈箖姊虹拠鑼闁瑰憡濞婂濠氭晬閸曨亝鍕冮柣鐘叉处缁佹挳宕戦幘鏂ユ斀閻庯綆浜為悾娲偡濠婂嫭鐓ラ柣锝囧厴閹剝鎯斿Ο缁樻澑闂備礁缍婇崑濠囧礈濮樿埖鍋柛宀€鍋為埛鎺楁煕鐏炲墽鎳呯紒鎰⒐缁绘稒鎷呴崘鎻掑箻婵炲樊浜滃洿闂佹悶鍎荤徊鑺ョ閻愵剚鍙忔俊顖滃帶鐢爼鏌ｈ箛銉ф偧缂佽鲸甯￠、娆忊枎閹勵唲闂備礁鐤囧Λ鍕囬崹顐ｅ弿闁逞屽墴閺岋絽螣濞茶鏅遍梺鍝ュ枎椤戝顫忕紒妯诲闁告稑锕ラ崕鎾愁渻閵堝繒绱伴柛妤€鍟块悾鐤亹閹烘垿鍞堕梺鍝勬储閸斿秹寮插鍫熲拺闁绘劘妫勯崝婊堟煛鐎ｎ亗鍋㈢€殿喓鍔嶇粋鎺斺偓锝庡亞閸樹粙姊鸿ぐ鎺戜喊闁搞劋鍗抽幆鍐洪鍛幍闂佷紮绲介懟顖炲煝閸儲鐓涢悘鐐插⒔濞叉潙鈹戦垾宕囧煟鐎规洏鍔戝鍫曞箣濠靛棗鎸ら梻浣筋嚙濮橈箓锝炴径濞掑搫顫滈埀顒€鐣峰┑鍡忔瀻闊浄绲藉▓銊︾箾鐎电孝妞ゆ垵鎳忛崕顐︽煟閻斿摜鐭婃い锕傛涧椤曪綁濡搁埡鍌涘劒濡炪倖鍔戦崐妤呮儊閸儲鈷戞慨鐟版搐閻忓弶绻涙担鍐插暟閹姐儱鈹戦悩鍨毄闁稿鍋涢…鍥р枎閹惧磭锛欓梺鍓茬厛閸ｎ噣宕甸弴鐔翠簻闁规壋鏅涢悞娲煕濮橆剦鍎旈柡灞剧洴閸╁嫰宕楅悪鈧禍婊堫敋閿濆鍨傛い鏃囶潐閺傗偓婵＄偑鍊栧濠氭偤閺傚簱鏋旈柡鍐ｅ亾濞ｅ洤锕、鏇㈡晲鎼淬垻鏆ユ俊鐐€栧ú鈺冪礊娴ｉ€涚箚婵繂鐭堝Σ鎯р攽閳藉棗浜介柛銊╀憾婵＄敻宕熼姘鳖啋闁诲海鏁哥涵璺何ｉ崼鐔虹閻庢稒顭囬惌鎺旂磼閻樺磭澧い顐㈢箲缁绘繂顫濋鍌︾床婵犳鍠楅敃鈺呭礂濮椻偓瀹曟垿骞樺畷鍥ㄦ疂闂佺懓鍟块敃銈囩礊婵犲倻鏆﹂柟顖炲亰濡查箖姊洪崫鍕紨缂佺姵鎹囧濠氭晲婢跺娼婇梺闈涚箚閺呮繈宕濋崫銉х＝濞达絿鎳撴慨鍫熴亜閵娿儻韬€殿喖顭烽幃銏ゅ礂閼测晛濮洪梻浣瑰濞插秹宕戦幘缁樼厸閻庯綆鍓欓弸鏃堟煃瑜滈崜婵嬶綖婢跺⊕鍝勵潨閳ь剟骞冮敓鐘虫櫢闁绘灏幗鏇炩攽閻愭潙鐏熼柛鈺佸瀵偊宕橀鐣屽幗濠碘槅鍨甸褏寰婄拠娴嬫斀妞ゆ柨銈搁崣鍕叏婵犲啯銇濋柟绋匡攻瀵板嫭绻濋崘鈺婂晙闂傚倷绀侀幗婊勬叏閻㈠憡鍋嬮柣妯烘▕閸ゆ洖鈹戦悩瀹犲闁告濞婇弻鏇＄疀閺囩偐鏋呴梺鍝ュ仩濞夋盯鍩為幋锔藉亹缂備焦蓱闁款厼鈹戦悙鑼勾闁告梹鍨煎Λ鐔兼⒒娓氬洤澧紒澶屾暬閸╂盯骞嬮悩鐢碉紲闁诲函缍嗛崑鎺楀磿閵夆晜鐓曢幖娣灩婵秹鏌″畝鈧崰鏍箖閻戣姤鍋嬮柛顐ゅ枑閸婄兘姊绘担椋庝覆缂佹彃娼″畷妤€顫滈埀顒勭嵁閸愵煈鐓ラ柛娑卞灦閳瑰繘鏌ｆ惔顖滅У闁稿鎳庨埢宥咁吋婢跺鎷绘繛杈剧秬濞咃絿鏁☉銏＄厱闁哄啠鍋撻柣妤冨Т閻ｅ嘲鈹戞繝搴⑿柣搴＄仛濠㈡﹢鏁冮妷鈺佄ч柨婵嗩槸缁€鍐煏婵犲倸鍤辩紒鐘虫崌瀵鈽夐姀鐘插祮闂侀潧顭堥崕铏閳哄懏鐓曢柣鎴濇閻忥附鎱ㄦ繝鍐┿仢婵☆偄鍟埥澶嬫綇閵娿垺鐏侀梻鍌欑閹芥粍鎱ㄩ悽鎼炩偓鍐幢濞戞牑鍋撻崘銊㈡瀻闁瑰濮烽敍婵嬫⒑缁嬫寧婀伴柤褰掔畺閸┾偓妞ゆ巻鍋撻柛銏＄叀濠€渚€姊洪幖鐐插姌闁告柨锕ョ粋鎺楀醇閵夛妇鍘卞┑鐘绘涧鐎氼剟宕濆鍫熺厸闁糕剝顭囬惌瀣庨崶褝韬┑鈥崇埣瀹曟帒顫濋銏╂婵犵绱曢崑鎴﹀磹閵堝鍌ㄩ柣鎾崇瘍濞差亜鐓涢柛鎰典簷缁楀鈹戦悙鏉戠仸閼裤倖淇婇幓鎺斿濞ｅ洤锕、娑樷槈濮楀棙顥￠梻浣告惈閹虫劖绻涢埀顒傗偓娈垮枛椤嘲顕ｉ幘顔藉亜闁惧繒鎳撴鍕繆閻愵亜鈧牠鎮уΔ鍛殞濡わ絽鍟悞鍨亜閹哄棗浜剧紓鍌氱Т閿曨亝淇婄€涙ɑ濯撮柛鎾冲级瀵ゆ椽姊洪柅鐐茶嫰婢ь喗銇勯銏㈢缂佺粯绻傞～婵嬵敆閸岋妇搴婂┑鐘垫暩閸嬫稑螞濞嗘挸鍨傜憸鐗堝笚閸嬫﹢鏌曡箛瀣偓鏍煕閹达附鈷戞い鎰╁€曟禒婊堟煠濞茶鐏￠柡鍛埣椤㈡稑顭ㄩ崨顖ょ床闂佽鍑界紞鍡涘磻閸涱厾鏆︾€光偓閸曨剛鍘遍梺鍐叉惈閸燁偅绂掓潏顭戞闁绘劖娼欑粭鎺楁懚閺嶎灐褰掓晲閸涱喗鍎撳Δ鐘靛仜閻楁挸顫忕紒妯诲闁告稑锕ラ崕鎾绘⒑缁嬪尅鍔熸い顓炵墦閳ワ箓宕堕浣规闂佺粯顭堢亸娆撴偂閹达附鈷戦柛娑橈攻婢跺嫰鏌涢妸鈺€鎲鹃柟顕嗙節瀵挳濮€閿涘嫬甯楅梺鑽ゅ枑閻熴儳鈧凹鍓熷畷婵嬪Χ閸氥倗鎳撻…銊╁川椤撴繂顥氬┑鐑囩到濞层倝鏁冮鍫濈畺婵炲棙鎼╅弫鍌炴煕閺囨ê濡煎ù婊堢畺閺屸€愁吋鎼粹€茬凹闂佸搫妫欑划鎾诲蓟閻斿吋鍊绘慨妤€妫欓悾鐑芥⒑閸濆嫭鍣虹紒璇茬墦瀵濡搁埡浣诡棟闂佸壊鐓堥崰鎺楀箰閸愵喗鈷戞繛鑼额嚙楠炴鏌熼悷鐗堟悙妞ゎ偄绻戠换婵嗩潩椤掑嫬鏁归梻浣虹帛濮婂宕曢悽绋跨；闁规儳顕々鐑芥倵閿濆骸浜滃ù鐙€鍙冨缁樼瑹閸パ冧紟婵犵鈧櫕鍠樼€规洩缍佸畷鍗炩槈濞嗗本瀚奸梻浣告啞缁嬫垿鏁冮妷锕€绶為柛鏇ㄥ灡閻撴洘淇婇姘础闁活厽鐟ч埀顒冾潐濞叉ɑ绻涙繝鍥モ偓浣糕枎閹存粎鍓ㄩ梺鍝勭Р閸斿秹寮堕幖浣光拻濞达絽鎼禒娲煕鎼淬劋鎲剧€规洦鍨抽幑鍕Ω瑜庨敍蹇涙偡濠婂嫭顥堢€殿喛顕ч埥澶愬閻樼數娼夐梻渚€鈧偛鑻晶鎾煙椤旀儳鍘撮柛鈹惧墲缁楃喖宕惰椤撴寧淇婇悙顏勨偓鏍礉瑜忕划濠氬箣閻樺吀绗夊┑鐐村灟閸ㄦ椽鎮″☉姗嗙唵閻犵儤妞介妤呮煕閺冨倹鏆╅柟顕呭枛閳规垹鈧綆鍋€閹风粯绻涢幘鏉戠劰闁稿鎸荤换娑欐媴閸愬弶澶勯柛瀣儔閺屾盯鍩勯崘顏佹缂備胶濮锋繛鈧柡宀€鍠栭弻鍥晝閳ь剟寮搁妶澶嬬厽妞ゆ挾鍠愮亸鎵磼缂佹鈽夋い鏂跨箻椤㈡瑩鎳￠妶鍛瘓闂傚倷鑳剁划顖炲箰閼姐倗鐭欓柟杈鹃檮缁犳帡姊绘担鐟邦嚋缂佽鍊哥叅闁挎洖鍊搁崥褰掓煃瑜滈崜姘辨崲濠靛棌鏋旈柛顭戝枟閻忓牏绱撴担鍓叉Ц闁绘牕銈稿畷娲焵椤掍降浜滈柟鐑樺灥閺嬨倖绻涢崗鐓庡缂佺粯鐩畷锝嗗緞鐏炶В鍚傞梻浣风串缁插潡宕楀鈧妴浣肝旈崨顓狀槹濡炪倖鍔戦崐鏇㈢嵁閹烘鈷戦柣鐔告緲閹垿鏌ｉ敐搴濋偗鐎规洘绻傞悾婵嬪焵椤掑倸鍨濆┑鐘崇閺呮煡鏌涢埄鍐噮闁伙箑鐗撳濠氬磼濮樺崬顤€缂備礁顑嗛幐濠氬疾閸洘鐒肩€广儱妫涢崢閬嶆⒑缂佹ê濮囬柣蹇旇壘閳诲秹寮撮悩鐢碉紲闁哄鐗勯崝宥呯暦瀹€鈧埀顒冾潐濞叉鏁幒妤嬬稏婵犻潧顑愰弫鍕煢濡警妲峰瑙勬礋濮婇缚銇愰幒鎿勭吹缂備讲鍋撳ù锝呮惈椤ユ岸鏌涢敂璇插箰闁稿鎹囬幃鐑藉级濞嗗彞鐥梻渚€娼荤徊鍧椝夐幇鏉课﹂柟鐗堟緲缁犳娊鏌熺€电孝闁逞屽墰閸嬨倕顫忓ú顏咁棃婵炴垼浜崣姘辩磽娴ｈ棄钄奸柛瀣姍瀹曟岸骞掑Δ鈧粻鑽ょ磽娴ｉ姘跺箯濞差亝鈷戦柛娑橈功閳藉鏌ㄩ弴顏勵洭缂佽鲸鎸搁～婵嬫嚋閻㈤潧骞堥梺鐟板悑閻ｎ亪宕归崷顓炵筏濠电姵纰嶉悡鐔兼煥濠靛棙鎼愰柛妯侯嚟閳ь剚顔栭崰鏍€﹂柨瀣╃箚闁绘垼濮ら弲婊堟煙椤栧棗鍟伴悿鍕節绾板纾块柛瀣灴瀹曟劙寮介鐐殿槷閻熸粌绻愰銉︾節閸曨剙纾梺闈浤涢崒婊呮喒濠电姵顔栭崰妤呭Φ濞戙垹纾婚柟鍓х帛閻撴稓鈧厜鍋撻悗锝庡墰閻﹀牓鎮楃憴鍕濞存粌鐖奸妴浣割潨閳ь剟骞冮埡鍛瀭妞ゆ劧缍嗛崯宀勬⒒閸屾艾鈧绮堟笟鈧獮鏍敃閿曗偓鐎氬銇勯幒鎴濐仾闁稿骸瀛╅妵鍕冀椤愵澀鏉梺閫炲苯鍘哥紒鑸佃壘椤曪綁骞橀纰辨綂闂佹枼鏅涢崯顖炴偟閹惰姤鈷掑ù锝堟閵嗗﹪鏌涢幘瀵哥疄闁诡喚鍏橀、娑樞掔涵椋庣ɑ閻庝絻鍋愰埀顒佺⊕鑿ら柟椋庣帛缁绘稒娼忛崜褍顕遍柣鐘亾闁挎洖鍊归崐鍧楁煟閹伴潧鍘靛ù婊勭矒閺岀喓鈧稒顭囩粻鏍ㄣ亜閵夛絽鐏柍褜鍓濋～澶娒哄Ο鍏煎床闁稿瞼鍋涢悡婵嬪箹濞ｎ剙鈧鎮块埀顒勬⒑閹稿海绠撻柟鍐茬箻椤㈡﹢宕稿Δ浣叉嫽婵炶揪绲块…鍫ニ夎箛娑欑厱閻庯綆浜濋崳褰掓偂閵堝鐓涚€广儱楠搁獮妤呮煟閹捐尙绐旈柡灞剧洴婵＄兘鏁愰崨顓団晜绻涚€涙鐭嬬紒顔芥崌瀵鎮㈤悡搴ｉ獓闁荤姵浜介崝瀣垝閻㈢數纾藉ù锝堟閻撴劖鎱ㄥΟ绋垮婵″弶鍔欓獮鎺懳旈埀顒佸劔闂備線娼ч…顓犫偓闈涜嫰铻為柛鏇ㄥ亽濞撳鏌曢崼婵堝嚬缂併劌顭烽弻娑㈡偄妞嬪孩鎲兼繛锝呮搐閿曨亪鐛崱娑樼妞ゆ梻鍋撳鎴︽⒒娴ｅ憡鎯堟繛灞傚妽閹便劑鎮滈懞銉ヤ粧闂侀潧顦弲婊堝煕閹烘嚚褰掓晲閸涱喖鏆堥梺鍝ュ枔閸嬬偤濡甸崟顖毼╅柕澶涘瘜濡紕绱撴担铏瑰笡缂佸甯為幑銏犫攽鐎ｎ亞锛滈梺闈涚墕閹冲繘顢橀崹顔规斀闁绘ê鐏氶弳鈺佲攽椤旂偓鏆柟铏箖閵堬綁宕橀埡浣插亾閹稿海绠剧€瑰壊鍠曠花濂告煟閹惧瓨绀嬮柡宀€鍠栭獮宥夋惞椤愶絿褰呭┑鐘茬棄閵堝棛銆婄紓浣介哺鐢繝鐛崶顒夋晩闂傚倸鐡ㄩ～鏇熺節濞堝灝鏋涢柨鏇樺妼閳诲秹鏁愭径濠勵槺闂佸搫绋侀崢濂稿础閹惰姤鐓熼柟閭﹀幘閵堟挳鏌熼弸顐⑩偓婵嗩潖濞差亝瀵犲璺猴攻濞堢粯绻涚€涙鐭婇柣鏍帶椤曪絾绻濆顓熸珳闂佸憡渚楁禍婵嬪棘閳ь剟姊绘担瑙勫仩闁稿寒鍨跺畷婵囨償閵婂娲︾€佃偐鈧稒菤閹锋椽姊洪崨濠勭畵閻庢凹鍣ｉ幃鐐垫崉閵娧咃紲闂佺粯顭堝▍鏇犱焊椤撱垺鐓熼柨婵嗘噹濡茬粯銇勯锝囩煉闁糕斁鍋撳銈嗗笒鐎氥劑鍩€椤戣法顦﹂柍璇查叄楠炲鎮╃喊澶屽簥濠电姷顣藉Σ鍛村垂閹惰棄纾块柕鍫濐槹閸婂爼鏌熼崜褏甯涢柍閿嬪浮閺屾稓浠﹂崜褎鍣銈忚缁犳捇寮婚悢鍝勬瀳闁告鍋橀崰濠囨⒑鐠団€崇仩闁哄牜鍓欓銉╁礋椤愩倖娈曢梺閫炲苯澧扮紒顔肩墛缁绘繈宕戦姘辩Ш闁轰焦鍔栧鍕幢濡炴儳顥氭繝鐢靛仦閸ㄨ泛顫濋妸鈺傚仼濡わ絽鍟埛鎺懨归敐鍫燁仩閻㈩垱鐩弻娑㈠Ω瑜嶇敮鍫曟懚閻愮儤鐓曢柡鍥ュ妼娴滄繈鏌￠崱妯肩煉婵﹤顭峰畷鎺戔枎閹存繂顬夐梺璇叉捣閻熸娊宕楅悩鍙夋儓妞ゆ挸鍚嬪鍕節閸曞墎骞㈤梻鍌欐祰椤宕曢幎绛嬫晪妞ゆ挾濮锋稉宥呂旈敐鍛殲闁绘挻娲橀妵鍕箛閳轰讲鍋撻弴鐐╂瀺闊洦姊荤粻楣冩煕椤愩倕鏋旈柣顓熷浮閺屸€崇暆閳ь剟宕伴弽顓溾偓浣糕枎閹寸娀鈹忛柣搴秵閸嬪棝寮抽妷鈺傗拻濞达絽鎽滈敍宥囩磼椤曞懎鐏︽鐐村灴瀹曟儼顦撮柡鍡閹叉悂鎮ч崼婵呭垔闂佽桨绀侀敃顏堝蓟閿濆鏅查柛娑卞弾濞堫參姊绘笟鍥у季闁搞劏娉涢～蹇旂節濮橆剛锛滃┑鐐叉閸旀濡堕弶娆炬富闁靛牆妫欓懖鐘绘煕濞戝崬鏋涢幖鏉戯躬濮婅櫣娑甸崨顔兼锭闂傚倸瀚€氭澘鐣烽悽鍏告勃閺夌偞瀵уΛ鍐极閹版澘宸濇い鎾跺枔娴滈箖姊绘担鑺ャ€冪紒鈧笟鈧、鏍ㄥ緞閹邦剝鎽曢梺鍝勬川閸犲海娆㈤悙鐑樼厱闁斥晛鍙愰幋锔藉仧闁哄啫鍊荤壕钘壝归敐鍡楃祷濞存粓绠栭弻锝嗘償椤栨粎校闂佺顑勯悞锔剧矉瀹ュ拋鐓ラ柛顐ゅ枔閸樼敻姊虹紒妯虹仸闁挎岸鏌ｈ箛瀣姦闁哄苯绉烽¨渚€鏌涢幘瀵告噰闁炽儻绠撻幃婊堟寠婢跺瞼鏆板┑鐐存尰閸╁啴宕戦幘鍨涘亾鐟欏嫭绀€闁靛牆鎲℃穱濠囨倻閼恒儲娅嗛柣鐔哥懃鐎氼剟顢旈崷顓犵＝闁稿本鑹鹃埀顒勵棑缁牊绗熼埀顒勩€侀弽顓炲耿婵炲棗鑻禍鍓х磼濡や胶鈽夐柛鐘崇洴閹虫捇宕稿Δ浣哄幍濠电偛鐗嗛悘婵嬪几閵堝洨妫柟顖嗕礁浠梺璇″枛缂嶅﹤鐣烽崼鏇ㄦ晜闁告洦鍘介妤呮⒑鏉炴壆顦﹂柣妤佹崌楠炲啫螖閸愨晛鏋傞梺鍛婃处閸撴瑩藝閳哄懏鈷戦柛娑橈攻鐏忔壆绱掔拠鑼濞ｅ洤锕幃鐣岀矙鐠恒劎鏉搁梻浣告惈椤﹀啿鈻旈弴銏╂晩濠电姴娲﹂埛鎴︽煕閿旇寮ㄦ俊鐐倐閺屾盯濡搁妸銈呮儓闂侀€炲苯澧ǎ鍥ф惈铻為柛鏇ㄥ灠閻撴﹢鏌熸潏楣冩闁稿﹦鍏橀弻銈夊箹娴ｈ閿┑鐐村毆閸涱垳锛濋梺绋挎湰濮樸劏鈪甸梻浣侯焾椤戝棝骞愰幖浣测偓鏃堝礃椤斿槈褔骞栫划鍏夊亾閼碱剛娉垮┑锛勫亼閸娧呯不閹达附鍊舵慨姗嗗幘閳瑰秴鈹戦悩鍙夊闁稿鍔戦弻娑樷槈濮楀牆浼愭繛瀛樼矋缁挸顫忓ú顏勫窛濠电姴瀚槐浼存⒑缁嬪灝顒㈠┑鐐诧躬閵嗕礁鈻庨幘鍐插祮闂侀潧绻嗗褔骞忛搹鍦＝闁稿本鐟ч崝宥夋嫅闁秵鍊堕煫鍥风到瀵噣鏌熼绛嬫當闁宠棄顦甸獮鎺楀箻鐎电缍冮梺璇叉唉椤煤濮椻偓瀹曞綊骞愭惔婵堢畾闂佹眹鍊ら崹鐓幬ｉ悜鑺モ拺缂佸顑欓崕鎰版煙閹间胶鐣烘鐐差樀楠炴﹢顢欓懖鈺婃Ч婵＄偑鍊栫敮鎺楀磻閸℃あ锝夊箥椤斿墽锛濋梺绋挎湰閻燂妇绮婇悧鍫涗簻闁哄洤妫楀ú銈夋偪椤曗偓閺岀喓绱掗姀鐘崇亾閻庤鎸风欢姘跺蓟濞戙垹鐒洪柛鎰典簴濡插牏绱撴笟鍥т簻缂佸缍婂璇测槈閵忊晜鏅濋梺鎸庣箓濞层劑鎮炬總鍛娾拺闁告稑锕﹂幊鍐煕閻斿憡缍戞い顐㈢箰鐓ゆい蹇撴噽閸旂敻姊虹紒妯哄閻忓浚浜為埀顒佺濠㈡﹢鈥﹂懗顖ｆЩ濡炪倖娲﹂崣鍐春閳?API key闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃闁硅櫕鎹囬垾鏃堝礃椤忎礁浜鹃柨婵嗙凹缁ㄧ粯銇勯幒瀣仾闁靛洤瀚伴獮鍥敍濮ｆ寧鎹囬弻鐔哥瑹閸喖顬堝銈庡亝缁挸鐣烽崡鐐嶆棃鍩€椤掑嫬鐓曢柟鐑橆殕閳锋垹绱撴担濮戭亞绮閺岋繝宕担闀愬枈濡ょ姷鍋涢ˇ杈╁垝濞嗗繆鏋庨柟顖嗗嫬鈧垶姊绘担绋款棌闁稿甯掗…鍧楀焵椤掑倻纾介柛鎰ㄦ櫆缁€鈧梺瀹狀潐閸ㄥ潡骞冮埡鍛殤妞ゆ帊绶″Λ鍕⒒娴ｅ憡鎯堟い锔诲灣閼洪亶鏌嗗鍛紱闂佽宕橀褔宕￠幎鑺ョ厪闊洦娲栧暩闂佹眹鍊曞ú顓㈠蓟閻斿吋鍤岄柣妤€鐗嗗☉褏绱撴担钘夌处缂侇喗鐟ㄥΛ銏犫攽椤旂瓔鐒鹃柛鈺傜墵閹繝鎮㈤崗鑲╁幗闂佸搫鍟崑鍡涙倿閻愵剛绠鹃柛娑卞灠娴犙囨煙閸欏鍊愰柟顔ㄥ洤閱囨繝闈涚墢閹虫牠姊绘担渚劸妞ゆ垵妫濆畷婵單旈崨顓犲姦濡炪倖甯掗崐褰掑吹閳ь剚绻濋姀銏″殌闁挎洦浜滈悾閿嬪閺夋垵鍞ㄥ銈嗘尵閸嬬喖藝椤撶喍绻嗛柕鍫濈箳閸掍即鏌涢悤浣哥仸闁糕晜鐩獮瀣晝閳ь剛鐥閺岋綁骞囬鐔虹▏濡炪們鍎遍鍡涘Φ閸曨垱鏅滃┑鍌氭啞椤庡秹姊洪棃娑欐悙閻庢矮鍗抽悰顔锯偓锝庝簴閺€浠嬫煕閵夈劌鐓愰柨娑樻閳规垿鎮╁▓鎸庢缂備浇椴稿ú鐔奉嚕椤愩倖瀚氶柤纰卞墯濞堥箖姊虹紒妯烩拻闁冲嘲鐗撳顐㈩吋閸℃ê寮垮┑顔姐仜閸嬫挾鐥鐔稿€愮€规洦鍓欑叅妞ゅ繐鎳夐幏缁樼箾鏉堝墽鎮奸柛搴涘€濆畷鐢稿焵椤掑嫭鈷戦悗鐧搁檮濠㈡ɑ淇婇崸妤佺厵妤犵偛鐏濋悘鈺傘亜閹剧偨鍋㈢€规洖宕埢搴∥熼懡銈冨亽闂傚倸鍊风粈渚€宕ョ€ｎ剛鐭堥柟缁㈠枛閻ょ偓绻濋棃娑氬妞ゃ儲宀搁弻锕€螣娓氼垱锛嗛悷婊呭鐢寮查弻銉︾厱闁斥晛鍠氬▓妯肩磼娓氣偓閺€杈╂崲濞戞埃鍋撳☉娆樼劷闁活厽甯炵槐鎺楁偐瀹曞洤鈪瑰銈庡亜缁绘﹢骞栬ぐ鎺戞嵍妞ゆ挾濮烽崢顖炴⒑閼姐倕校濞存粈绮欏畷婵囨償閵忕媭鍤ら梺鎼炲労閸撴岸鍩涢幋鐘电＜閻庯綆鍋掗崕銉╂煕鎼淬垹鐏撮柡灞剧〒閳ь剨绲婚崝宀勫焵椤掍胶绠為柣娑卞櫍瀹曟﹢顢欓懞銉︻仧闂備胶绮摫鐟滄澘鍟悾鐢稿幢濞戞瑢鎷虹紓鍌欑劍钃遍柍閿嬪笧缁辨帞绱掑Ο鑲╃暭闂佸ジ缂氭ご鍝ユ崲濠靛棭娼╂い鎾寸⊕鐎氬ジ姊洪懡銈呮瀾闁荤喆鍎抽埀顒佸嚬閸樻儳鈻庨姀銈呯闁圭儤绻勯崬鐢告偡濠婂啰效闁哄苯锕弫鎰緞鐏炵晫銈﹂梻浣告啞閸旓箓宕板Δ鍛惞闁告劦鍠楅悡鍐煕濠靛棗顏╅柡鍡欏枛閺屻劌鈽夊▎鎴犵厜濠殿喖锕ㄥ▍锝囨閹烘埈娼ㄩ柛鈩冪懃婵吋绻濋悽闈涗粶闁瑰啿绻愮叅闁哄稁鍘介崑鈺冣偓鐟板婢瑰棝寮抽崱娑欑厱闁哄洢鍔屾晶浼存煕濡粯鍊愰柟顔筋殜瀹曟寰勬繝浣割棜闂備浇顕ч崙鐣岀礊閸℃稑绀堟繛鎴炲閸欑儤绻濆閿嬫緲閳ь剚顨嗛幈銊╂倻閽樺锛涢梺缁樺姉閸庛倝寮插┑瀣厪闊洦娲栧暩闂佸搫妫撮梽鍕┍婵犲浂鏁嶆慨妯稿劚娴犳椽姊洪棃鈺佺槣闁告ɑ鎮傚畷鎴﹀箻缂佹ɑ娅滈柟鐓庣摠缁诲嫰鎳楅悜妯肩瘈闁靛骏缍嗗鎰箾閼碱剙鏋庢い顐㈢箻閹煎綊宕烽鐘靛帬闂備胶纭堕崜婵嬨€冮崨鎼晜閻庢稒顭囩粻楣冩煕椤愩倕鏋戦柍閿嬪笧缁辨帗娼忛妸銉﹁癁闂佽鍠掗弲娑㈡偩閻戣棄鐐婄憸澶愬箯娴煎瓨鈷掑ù锝囩摂閸ゅ啴鏌涢悩宕囧⒌鐎规洘鐓″濠氬Ψ閵壯冨箳闂佺懓鍚嬮悾顏堝磹濡ゅ懏鍋柍褜鍓熷娲偡閹殿喕铏庨梺鍝ュ暱閺呯娀骞嗛埀顒併亜韫囨挸顏ら柡鈧禒瀣厽婵☆垵顕ф晶顖炴煕閻旈绠婚柡灞剧洴婵℃悂濡堕崨顓犮偖婵＄偑鍊戦崹鍝勭暆閹间降鈧礁顫滈埀顒勫箖閳哄懎绠涘ù锝呮贡缁嬫劙姊婚崒娆戭槮婵犫偓闁秴纾块柕鍫濐槸閽冪喖鏌ㄩ悢鍝勑㈢痪鎯ь煼閺岀喖宕滆鐢盯鏌￠崨顔惧弨妤犵偞鐗滈埀顒佺⊕椤洨绮诲鈧弻鈩冩媴閸︻厼鈪归梺瀹狀潐閸ㄥ潡銆佸▎鎴炲枂闁圭儤鎸鹃惌鎺斺偓瑙勬礃缁诲牓鐛€ｎ喗鏅濋柍褜鍓熼幏鎴︽偄閸忚偐鍘介梺鍝勫暙濞诧箓顢旈悩缁樼厽妞ゆ挾鍠撻幊鍥煛鐏炲墽娲撮柍銉畵楠炲鈹戦崶鈺€鎲惧┑鐘垫暩閸嬫盯鎮ч幇閭︽晪鐟滄棃宕洪悙鍝勭闁挎梻绮弲鈺冪磼缂併垹骞栭柛銏犲级鐎靛ジ骞囬悧鍫氭嫼闂侀潻瀵岄崢鎼佸箯閿熺姵鐓曢悗锝庝簼閸ゅ洨鈧鍠楅悡鈩冧繆閻戣棄鐓涢柛灞绢殕鐎氬ジ姊绘担渚敯闁稿鍔欏畷鎴濃槈閵忕姷顦梺閫炲苯澧存慨濠冩そ閺屽懘鎮欓懠璺侯伃婵犫拃鍐惧殶闁逞屽墲椤煤濮椻偓瀹曞綊宕稿Δ鍐ㄧウ濠碘槅鍨伴崥瀣偓姘哺閺岀喓绱掑Ο铏圭懆缂備椒绶￠崳锝咁潖缂佹ɑ濯撮柧蹇曟嚀缁楋繝姊洪崨濠冣拹婵炲弶绮庨崚鎺楀籍閸喎浠洪梺姹囧灮閺佹悂鎮￠幘缁樷拺缁绢厼鎳忚ぐ褏绱掗悩鍐茬伌闁诡喒鈧剚娼ㄩ柍褜鍓熷濠氭偄鐞涒€充壕闁汇垺顔栭悞鍓ф偖閵夆晜鈷戠紒瀣儥閸庢劙鏌熼悷鐗堝枠鐎殿噮鍋婇獮鍥敇閻斿嘲濡虫繝鐢靛█濞佳兠洪敃鈧悾鐑藉箮閼恒儮鎷绘繛杈剧导鐠€锕傚绩閺夊簱鏀芥い鏂挎惈閳ь剚娲滈崣鍛存⒑缂佹ɑ鈷掗柛妯犲懐涓嶉柡宥冨妺缁诲棝鏌曢崼婵囧櫤闁革絽婀辩槐鎺楀焵椤掑嫬纾兼慨妯垮亹閸炵敻鏌ｉ悩鐑橆仩閻忓繈鍔岄～蹇撐旈埀顒勨€︾捄銊﹀枂闁告洦鍓涢ˇ鏉库攽椤旂》鍔熺紒顕呭灣缁參鎮㈤悡搴ｅ姦濡炪倖甯掔€氼剟鎮為崹顐犱簻闁圭儤鍨甸埀顒€鎲＄粋鎺戭煥閸喓鍘惧┑鐐跺蔼椤曆囨倶閿熺姵鐓涢柛娑卞幘閸╋絾銇勯姀锛勨槈妞ゎ厹鍔戝畷銊╊敍閵堝洤绨ラ梻鍌氬€烽懗鍫曗€﹂崼銉ュ珘妞ゆ帒鍊婚惌娆撴煙鐎涙璐╃憸鐗堝俯閺佸鏌嶈閸撶喎顕ｆ繝姘労闁告劏鏅涢鎾剁磽娴ｅ壊鍎愰悗绗涘啠鏋斿┑鐘崇閸婄敻鎮峰▎蹇擃仾缂佲偓閸愵喗鍋ㄦい鏍ㄧ☉濞搭噣鏌涢埞鍨姕鐎垫澘瀚换娑㈠閵忕姵鐏堥梺鍦劜缁绘繃淇婇崼鏇炲耿婵妫楅弲娆撴⒒閸屾艾鈧悂宕愰幖浣哥９闁归棿绀佺壕鐟邦渻鐎ｎ亝鎹ｉ柣顓炴閵嗘帒顫濋敐鍛闁诲氦顫夊ú锕傚垂鐠鸿櫣鏆︾紒瀣嚦閺冨牆鐒垫い鎺戝€绘稉宥夋偡濞嗗繐顏ュù婊勭矒閺岀喖寮堕崹顕呮殺闂佷紮缍€娴滎剛妲愰幒妤€绠涙い鎾楀嫮鏆﹂梻渚€鈧稓鈹掗柛鏂跨焷閻忔帡姊洪崷顓х劸婵炲鍏樻俊鎾箛閻楀牃鎷哄┑顔炬嚀濞层倝鍩€椤戞儳鈧繂鐣烽弶娆炬僵閻犻缚娅ｉ崝锕€顪冮妶鍡楀潑闁稿鎸剧槐鎺楁偐閼碱儷褏鈧娲樺ú鐔煎蓟閸℃鏆ら柕澶堝劜婢跺嫰鎮楅棃娑栧仮鐎殿喖鐖奸獮瀣偐閹绘帞鐤勯梻鍌氬€烽懗鍫曘€佹繝鍥х妞ゅ繐鐗婇埛鏃堟煕閺囥劌鐏犵痪鎯ь煼閺屻劌鈹戦崱鈺傂ч梺缁樻尰濞茬喖寮婚弴鐔风窞婵炴垶鑹鹃崺灞剧節瀵版灚鍊曟禍鍦磼鏉堛劌娴柟宕囧█椤㈡宕掑槌栧仹闂傚倷绶氬褍煤閵堝洠鍋撳顐㈠祮闁绘侗鍣ｉ獮鎺楀棘閸濆嫪澹曢梺鎸庣箓缁ㄨ偐鑺遍挊澹濆綊鎮℃惔鈽嗕紑缂備浇椴搁幐濠氬箯閸涱喚顩烽悗锝庝簼閹虫瑩姊哄Ч鍥х労闁搞劍濞婂畷鎴﹀Χ婢跺﹥妲梺閫炲苯澧柕鍥у楠炴帡骞嬮姘潬缂傚倷绀侀ˇ閬嶅极婵犳艾钃熸繛鎴炲焹閸嬫捇鏁愭惔婵堢泿濡炪倕绻嗛弲鐘参涙担鐟扮窞閻庯絻鍔嬬花濠氭⒑閸濆嫭澶勬い銊ユ噺缁傚秵銈ｉ崘鈹炬嫼闂佸憡绻傜€氼剟藝椤掑嫭鐓曢柟鎯ь嚟缁犵偞顨ラ悙鑼鐎规洏鍔戝鍫曞箣閻欌偓濡插爼姊绘担鍛婅础缂侇噮鍨抽弫顕€骞掗幘鍓佸骄闁瑰吋鐣崹鑽ゅ姬閳ь剙鈹戦悙鑼闁诲繑绻堝绋库槈閵忥紕鍙嗛梺鍝勬处閿氶柛鏃€纰嶉妵鍕敂閸曨偅娈婚梺鍦焾閿曘儳绮╅悢鐓庣厸闁稿本绮嶉崚娑㈡倵鐟欏嫭绀冮柨鏇樺灪娣囧﹪骞栨担鍓叉綂闂佸疇妫勫Λ娆戠礊鐏炶В鏀介柣妯虹仛閺嗏晠鏌涚€ｎ偆鈽夐摶鐐寸箾閸℃ɑ灏紒鈧径鎰厸鐎广儱楠搁獮鏍棯閹呯Ш婵﹥妞藉畷褰掝敋閸涱厼澹嬬紓鍌欒濡狙囧磻閹剧粯鈷掑ù锝呮贡濠€浠嬫煕閵娿劍顥夋い顓炴穿椤﹀磭绱掗崒娑樼瑨妞ゎ厹鍔戝畷濂告偄閸濆嫬绠哄┑锛勫亼閸婃洜鎹㈤幇鏉跨柈妞ゆ劑鍨婚弳銈夋煕閳╁啰鎲块柛瀣尵閹叉挳宕熼鍌ゆО闂備礁鎲″鐟懊洪悢鐓庢槬闁靛绠戠欢鐐烘煙闁箑澧绘繛鐓庯躬濮婃椽鎮欓挊澶婂闂佸搫顑呴妶绋跨暦閹达箑绠婚悹鍥ㄧ叀閸炲爼姊洪崫鍕窛闁哥姵鎹囧畷銏ゆ偨閸涘ň鎷虹紓鍌欑劍閿氶柣蹇ョ畵閺屻劑寮村Δ浣圭彅闂佸磭绮幑鍥ь嚕閹绢喖顫呴柨娑樺鐢姊婚崒娆戭槮闁诲繑绻堥、鏍川鐎涙ê鈧爼鏌熺紒銏犳灍闁绘挻绋撻埀顒€鍘滈崑鎾绘倵閿濆骸澧扮悮锔戒繆閵堝洤啸闁稿绋戠叅妞ゆ搩娼块埀顑跨閳藉螣闁垮娼旈梺鍝勵槸閻楁粓鎮￠崼婢盯宕熼娑掓嫽闂佺鏈悷褔藝閿曞倹鐓欐繛鏉戭儌閸嬫捇骞囨担鍦▉闂備浇宕甸崰鏍磻婵犲偆鐒介柍鍝勬噺閻撳繐鈹戦悙闈涗壕婵炲懎妫濋弻娑欐償閳藉棙效闂侀潧娲ょ€氼垳绮诲☉銏犵闁圭⒈鍘介敓銉х磽娴ｅ搫浜鹃柛搴㈠▕婵″爼骞栨担姝屾憰闂佸搫娴勭槐鏇㈡偪閳ь剟姊洪崫鍕窛闁稿鍋婃慨鈧柕蹇嬪灮閿涙粌顪冮妶鍡楀闁搞劎绮弲銉︾節濞堝灝鏋涢柨鏇樺妼閳诲秹鏁愭径濠勵槺闂佸搫绋侀崢濂稿础閹惰姤鐓熼柡鍌涘閸熺偟绱掓０婵嗗⒋婵?provider 闂?API key闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘辨繝鐢靛Т閸婂綊宕戦妷鈺傜厸閻忕偠顕ф慨鍌溾偓娈垮櫘閸ｏ絽鐣锋總鍛婂亜闁告稑顭崬鍫曟⒒閸屾瑨鍏屾い顓炵墦椤㈡牠宕卞☉妯碱唶闂佸憡鎸嗛崘銊т喊婵＄偑鍊栭幐楣冨磻閹邦儵锝夊醇閻斿墎绠氬銈嗙墬缁诲秹宕靛▎鎰闁告稑娲ゅú锕傚煕閹寸偟绠鹃柤濂割杺閸ゆ瑦顨ラ悙鎼疁闁哄矉缍侀幃銏ゅ矗婢跺褰嬮柣搴㈩問閸犳牠鈥﹂悜钘夌畺闁靛繈鍊曞婵嗏攽閻樻彃顏懖鏍ㄧ節瀵伴攱婢橀埀顑懎绶ゅù鐘差儏閻ゎ喗銇勯弽顐㈠壉闁轰椒鑳堕埀顒€绠嶉崕閬嵥囨导鏉戠厱闁瑰濮风壕濂告倵閿濆簼绨藉ù鐘灪閵囧嫰骞掔€ｎ亞浠鹃梺闈涙搐鐎氱増淇婇幖浣肝ㄩ柨鏇楀亾婵炲牊顨呴埞鎴︽偐椤愵澀澹曞┑鐐存尰閸╁啴宕戦幘瀛樺弿濠电姴鍟妵婵囶殽閻愭潙濮堥柟顖涙閺佹劙宕堕埡鍌涱啌婵犵數濮烽弫鎼佸磻濞戙垺鍎戝ù鍏兼綑绾捐绻濋棃娑欘棤闁哄棴闄勭换婵嬫濞戞艾顣甸梺绋款儐閹瑰洭寮幇顓熷劅闁炽儱鍟跨粻锝夋⒒娴ｄ警鐒炬い鎴濇楠炴劖銈ｉ崘銊х枀闂佸湱铏庨崰鏍矆鐎ｎ偁浜滈柟鐑樺灥娴滅偞淇婂顔煎⒋闁哄矉绲鹃幆鏃堝閳轰焦娅涢梻浣告憸婵敻鎮уΔ鍛柧闁肩鐏氶崕鐔兼煏婵炲灝鍔ゆい鏂款樀濮婃椽妫冨☉姘鳖唺婵犳鍣崢鐓庡祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔侯焾椤啴濡堕崱妯洪瀺濠碉紕鍋犲Λ鍕綖韫囨稒鎯為柛锔诲幘閿涙粌鈹戦埥鍡楃仩闁圭⒈鍋婇敐鐐茬暆閸曨兘鎷洪柣鐘叉穿鐏忔瑧绮婚懠顑藉亾閸忓浜剧紓浣割儓濞夋洟寮抽敃鍌涚厵闁告挷鑳堕幗鍌炴煛娴ｅ壊鍎旈柡灞界Х椤т線鏌涢幘瀵告噰闁挎繄鍋犵粻娑樷槈濡湱鐐婇梻浣告啞濞诧箓宕㈤挊澶嗘灁濡わ絽鍟埛鎴︽煙閼测晛浠滈柛鏃€顨婇弻锟犲川椤斾勘鈧帞绱掗鍛籍闁轰焦鎹囬幃鈺呭棘閵夛箑顏归梻鍌欑閹诧紕鎹㈤崒婧惧亾濮樼厧鐏﹂柨婵堝仱閺佸啴宕掑☉姘箞闂備礁鎼崯鐘诲磻閹剧粯鐓曢柕濞垮劤娴犮垽鏌ｉ敐鍛Щ閻撱倖銇勮箛鎾村櫣闁逞屽墰閸忔﹢寮诲☉妯锋斀闁糕剝顨忔导鈧俊鐐€栭幐璇差渻閽樺娼栨繛宸簻缁犱即骞栧ǎ顒€鐒烘慨濠傜仢閳规垿鍩ラ崱妞剧盎闁诲孩鍑归崢鍓у垝鐎ｎ亶鍚嬮柛顐ｇ◥濮规姊洪崷顓炲妺闁瑰憡鎸抽獮蹇撁洪鍛嫼闂傚倸鐗冮弲娑㈡儊濠婂牊鐓曟俊顖氭惈閳锋棃鏌℃笟鍥ф灈闁宠棄顦垫慨鈧柍銉ュ帠缂傛挻淇婇悙顏勨偓鏍偋濡ゅ啰鐭欓柟瀵稿Х缁犳梻鎲歌箛鏇燁潟闁圭儤鎸荤紞鍥煏婵炲灝鍔滈悹鍥╁仱濮婅櫣鍖栭弴鐔哥彣缂備胶绮换鍌炴偩閻戣棄绠抽柟鎼幘閸欏棝姊洪崨濠勭焼缂佲偓娓氣偓瀵煡顢橀姀鈾€鎷婚梺绋挎湰閻熝囁囬敂鐣岀瘈闁逞屽墴閺屽棗顓奸崨顖ょ幢闂備礁婀遍崑鎾诲礈濮樿埖鍊块柤鎭掑劤缁犻箖鏌涢埄鍏╂垹浜告导瀛樼厱濠电姴鎳忕涵鍫曟煙閸欏鍊愰柟顔ㄥ洤閱囨繝闈涚墢閹虫牠姊绘担铏瑰笡闁规瓕顕х叅闁绘梻鍘х粻鏍ㄤ繆閵堝懏鍣洪柡鍛叀楠炴牜鍒掗崗澶婁壕闁肩⒈鍓欓崵顒勬⒒娴ｇ瓔鍤欑紒缁樺姉閹广垽骞掑Δ鈧弸浣糕攽閻樺疇澹橀柦鍐枔閳ь剙绠嶉崕閬嶆偋濠婂喚鐎堕柕濞炬櫆閳锋垿鏌涘☉姗堟敾閻忓繑澹嗙槐鎺旀嫚閼碱剙鈪甸梺杞扮劍閸旀瑩骞冨▎鎾崇骇闁瑰濮烽悰顔尖攽閻樺灚鏆╅柛瀣仧閺侇喖螖閳ь剟鈥旈崘顔藉癄濠㈣埖锚濞堛劑姊虹粙鍖″姛闁革絻鍎遍‖濠囶敂閸啿鎷洪梺绋跨箰閸氬娆㈤崣澶岀閻忓繑鐗戦崑鎾诲箛娴ｅ湱绋佹繝鐢靛仜濡﹥绂嶉崼鏇炴瀬闁糕剝绋掗悡鍐喐濠婂牆绀堟繛鎴炶壘閸ㄦ繈鏌￠崘銊у缂佺姷绮妵鍕籍閸ヮ煈妫勯梺閫炲苯澧繛纭风節瀵鈽夐埗鈹惧亾閿曞倸绠ｆ繝闈涙噽閹稿鈹戦悙鑼憼缂侇喖绉堕崚鎺楀箻鐠囪尪鎽曢梺缁樻煥閸氬宕愮紒妯圭箚妞ゆ牗绻冮鐘绘煕濡濮嶆慨濠冩そ瀹曘劍绻濋崘锝嗗闂備礁鎽滄慨鐢稿箰閹灛锝夊箛閺夎法顔婇梺瑙勫劤绾绢厾绮ｉ悙鐑樷拺鐟滅増甯掓禍浼存煕濡湱鐭欓柡灞诲姂椤㈡﹢濮€閳锯偓閹峰姊洪幖鐐插妧閻忕偞瀚庤缁辨挻鎷呴搹鐟扮缂備浇顕ч崯浼村箲閵忕姭鏀介悗锝庝簽閿涙粌鈹戦鏂よ€挎俊顐ユ硶濡叉劙骞嬮悩鐢碉紳闂佺鏈悷銊╁礂鐏炶В鏀芥い鏃€鍎抽崢瀵糕偓瑙勬礃閸ㄥ潡骞冮姀銈嗗亗閹艰揪绲芥慨锔戒繆閻愵亜鈧牜鏁幒妤€绐楁慨姗嗗墻閻掍粙鏌熼柇锕€骞樼紒鐘荤畺閺屾稑鈻庤箛锝嗩€嗛梺鍏煎濞夋洟鍩€椤掑喚娼愭繛鍙夘焽閹广垽宕掗悙鑼幒闁瑰吋鐣崝宀€绮婚懡銈傚亾鐟欏嫭绀€婵炲眰鍔戝鎶筋敃閳垛晜鏂€闂佺粯鍔曞Ο濠囧吹閻斿皝鏀芥い鏃囧Г鐏忥附銇勯姀锛勫⒌鐎规洏鍔戦、妯款槻闁哄懐濮撮埞鎴︽偐缂佹ɑ閿┑鈽嗗亜閻倸顕ｉ妸锔绢浄閻庯綆鍋嗛崢钘夆攽閳藉棗鐏ユい鏇嗗懎绶ょ紓浣骨滄禍婊堢叓閸パ嶆敾婵炲懎妫欓妵鍕Ω閿濆懎濮﹂梺璇″枟閻熲晠骞婇悩娲绘晞妞ゆ劕楠哥€氼參宕ｈ箛鎾斀闁绘ê寮堕崳鐑樸亜韫囨洖鈻堥柡宀€鍠愰ˇ鐗堟償閳锯偓閺嬪懎螖閻橀潧浠﹂柟鐟版喘閻涱噣骞掗幋鏃€鏂€闂佺硶鍓濋妵鍌炲Ω瑜忕壕浠嬫煕鐏炴崘澹橀柍褜鍓熼ˉ鎾跺垝閸喓鐟归柍褜鍓熼妴渚€寮介鐐茶€垮┑鐐叉閸旀牕鈻撴导瀛樷拺閻犳亽鍔岄弸鏂库攽椤旇姤灏︾€殿喖鎲＄粭鐔煎焵椤掑嫬绠栨俊銈呮噺閺呮煡骞栫划鐟板⒉闁诲繐绉瑰娲箮閼恒儲鏆犻梺鎼炲妼濞硷繝鐛崘顓滀汗闁圭儤鍨归崐鐐烘⒑闂堟丹娑㈠礃閵娧冩憢闂傚倸鍊烽懗鍓佸垝椤栨粎鐭欓柟鐑樻煥閸ㄦ繈骞栨潏鍓хɑ妞ゎ偅娲熼弻鐔兼倻濮楀棙鐣烽梺绋款儐閸旀瑩寮诲☉銏犵疀妞ゆ牗姘ㄥВ銏＄箾鐎电甯堕柣顓炲€搁～蹇撁洪鍛偓鐑芥煢濡警妲稿┑顕€顥撶槐鎾存媴閸濆嫅锝夋煙閻熺増鍠橀柣娑卞枟缁绘繈宕戦懞銉︻棃鐎规洦浜濋幏鍛喆閸曨剛褰ㄩ梻鍌氬€烽悞锔锯偓绗涘懏宕查柛宀€鍋涢拑鐔封攽閻樺弶绁╅柡浣告閺屽秷顧侀柛鎾跺枛瀹曟椽鎮欓崫鍕吅闂佹寧妫佸Λ鍕瑜版帗鈷戦柛鎾瑰皺閸樻盯鏌涚€ｎ亝鍣圭悮娆撴煕閺囥劌鐏￠柍閿嬪灩缁辨帞鈧綆鍋掗崕銉╂煕鎼淬垹濮嶉柡灞剧洴瀵噣鍩€椤掑嫭鍋￠柕澶嗘櫆閸嬧晠鏌ｉ幋锝嗩棄缂佺媴缍侀弻銊╁即濡も偓娴滃墽绱撴担鍝勑€规洜鏁稿Σ鎰板箻鐎涙ê顎撴俊銈囧О閸斿秴鐣濋幖浣哄祦闊洦绋掗幆鐐烘煕閿旇骞橀柨娑欑矌缁辨捇宕掑▎鎾搭€栭梺鎼炲妼缂嶅﹪鎮伴鈧浠嬵敇閻斿搫骞嶉梻浣告啞閸旀浜稿▎鎴犱笉濠电姵纰嶉悡娆愩亜閺冨倸浜鹃柡鍡╁墯閵囧嫰濮€閳╁喚妫冮悗瑙勬磸閸旀垿銆侀弴銏℃櫖闁告洦鍘介弲銊╂⒒閸屾艾鈧娆㈠顒夌劷鐟滄棃鍨鹃敃鍌氶唶闁靛鍎抽敍鐔哥節閻㈤潧校婵ǜ鍔戝畷锝夊即閻旂繝绨婚梺鐟版惈缁夊墎鎷归悧鍫㈢闁割偅绮庨惌娆撴煛瀹€瀣М妤犵偛娲、姗€鎮欓悽鐐瑰仭闂傚倷绀侀幖顐⑽涚€电绶ら柛褎顨呴悞鍨亜閹烘垵鏋ゆ繛鍏煎姈缁绘盯宕ｆ径妯煎姺闂佸憡甯楃敮鐔虹不濞戞◤褰掑级閹稿骸顦╁┑鐐靛帶缁绘ɑ淇婂宀婃Ь濡炪倖姊瑰ú鐔煎箖濡ゅ懎绀傚璺猴梗婢规洖鈹戦悩鍨毄濠殿喖纾▎銏狀潩鐠鸿櫣锛涘┑掳鍊曢幊蹇涘煕閹达附鐓曟繝闈涙椤忣偊鏌ｈ箛娑楁喚闁哄本鐩幃鈺佺暦閸パ€鎷伴梻渚€娼уΛ鏃傜矆娓氣偓閸┿儲寰勯幇顒夋綂闂佺粯顭堢亸顏堝焵椤掆偓閻忔繈鍩為幋鐐茬疇闂佺锕ラ幐鍓у垝閸喐濯寸紒顖涙礃閻庢椽姊洪幐搴ｇ畵婵☆偅绋撳褔鍩€椤掆偓閳规垿鎮欓懠顒€顣洪梺璇茬箲缁诲牆顕ｇ粙搴撴婵﹫绲芥禍楣冩偡濞嗗繐顏璺哄閺屾盯骞樼捄鐑樼亪閻庤娲樺浠嬪箖濞嗘挸浼犻柛鏇ㄥ弾閸氬懘姊绘担鐟邦嚋婵☆偂绀佽灋闁告洦鍓涢々鑼喐閻楀牆绗氶柍閿嬪灩閹叉悂鎮ч崼婵呭垔闂佸搫妫欑敮鐐垫閹烘鐒垫い鎺嶈兌閻熷綊鏌嶈閸撴瑩顢氶敐澶婅摕闁靛濡囬崝鍫曟倵楠炲灝鍔氭俊顐㈢焸楠炲繐煤椤忓應鎷洪梺鍛婄☉閿曪妇绱撳鑸电厱閹兼番鍊濋崫娲煟濡も偓鐎涒晜绌辨繝鍥ㄥ€锋い蹇撳閸嬫捇骞嬮敃鈧粈澶屸偓鍏夊亾闁告洦鍓欐禍閬嶆⒑鐟欏嫬绀冪€规洟娼ч悾鍨瑹閳ь剟寮婚悢鍛婄秶闁告挆鍛婵＄偑鍊ら崑鍕箠濮椻偓瀵寮撮姀鐘诲敹濠电娀娼уú銈呪枍瑜斿鍝勑ч崶褉鍋撻幇鏉跨；闁圭偓鏋奸弨浠嬫煥濞戞ê顏╁ù婊冦偢閺屾稒绻濋崘顏勨吂闁捐崵鍋涢妴鎺戭潩閿濆懍澹曢柣搴ゎ潐濞叉﹢宕归崸妤冨祦闁搞儺鍓﹂弫濠偽旈敐鍛殜闁衡偓濞差亝鈷掑┑鐘查娴滄粍绻涚拠褍顩紒顔界懇楠炴帒螖閳ь剟鎮￠弴銏＄厵閻庢稒顭囩拹鈺冩喐閻楀牆绗掔紒鈧崒鐐寸厾婵炴潙顑嗗▍鍡涙煕閿濆骸娅嶆慨濠冩そ瀹曘劍绻濋崒婊呮啰闂備礁鎲￠〃鍡樼箾婵犲偆鍤曞┑鐘崇閺呮悂鏌ｅΟ鑽ゅ弨闁哥偠娉涢—鍐Χ閸℃顫囬梺鎼炲妼缂嶅﹪宕哄☉姘ｅ亾閿濆骸鏋熼柍閿嬪灴閺岀喓绮欓幐搴㈠闯缂備胶濮甸敃銏ゅ蓟濞戞埃鍋撻敐鍐ㄥ闁逞屽墯濞茬喖銆佸鑸垫櫜濠㈣泛锕﹂鎺戭渻閵堝棙鈷掗柍宄扮墕椤洦绻濋崶銊㈡嫼闂佸湱顭堝ù鐑藉煡婢舵劖鍊垫慨妯煎帶婢ф挳鏌ｅ☉鍗炴灈妞ゆ挸鍚嬪鍕偓锛卞嫬顏归梻浣藉吹婵潙煤閵堝拋鍤曢柛顐ｆ礀缁犳煡鏌ㄥ┑鍡╂Ч闁绘挻绋戦湁闁挎繂鐗滃鎰版煕婵犲啫濮嶉柡灞界Ч婵＄兘顢涘鍛闁诲氦顫夊ú鏍Χ閹间礁绠栭柕蹇ョ磿閻熻銇勯弽銊с€掗柕鍫亰濮婂宕掑▎鎴濆闁诲海鐟抽崗鐘虫そ瀵粙顢橀悙纰夌串闁荤喐绮庢晶妤冩暜濡ゅ懎纾婚柛宀€鍋為悡娑㈡煕閵夈垺娅呴柡瀣⒒缁辨帡鎮╅懡銈囨毇闂佸搫鏈惄顖炲春閸曨垰绀冮柣鎰靛墰閺嗩厾绱撻崒娆掑厡濠殿喖顕竟鏇㈩敇閻樻剚娼熼梺鍦劋椤ㄥ棝宕戦幇顔瑰亾閻熸澘顥忛柛鐘冲哺瀹曘儳鈧綆鍠楅埛鎴︽煕濠靛棗顏柣蹇涗憾閺屾盯鎮╁畷鍥р拰闂侀潧妫旂粈渚€鍩㈡惔銊ョ闁绘鍎甸弨娲⒑鐠囨彃鍤辩紓宥呮瀹曟垿宕卞☉妯奸獓閻熸粎澧楃敮妤呭煕閹烘嚚褰掓晲閸粳鎾绘煏閸℃鏆ｉ柡宀嬬秮楠炴帡鎮欓悽鍨闁诲氦顫夊ú妯兼崲閸繍鍤曞ù鐘差儛閺佸洭鏌ｉ幇顔芥毄闁哄棔鍗冲缁樻媴閸涘﹥鍎撻梺鍝ュ櫏閸嬪﹪骞冭瀹曞崬鈽夊▎蹇婂亾閹稿海绠剧€瑰壊鍠曠花濂告煟閹惧瓨绀嬮柡宀€鍠栧鍫曞垂椤旇棄鈧海绱撴担闈涘闁稿繑锕㈠濠氭偄閻撳氦鎽曢梺闈涳紡閸涱喗鐦掑┑鐘愁問閸犳牠鏁冮妶澶嗏偓锕€鐣￠幍顔芥闂佸湱鍎ら崹鐔煎几鎼淬劍鐓欓柣鎴灻悘銉╂偨椤栵絽鐏ｇ紒杈ㄦ崌瀹曟帒鈻庨幋锝囩崶闂備線娼荤紞鍡涘闯閿濆懐鏆﹂柣鐔稿閺嗭箓鏌涢妷銏℃珖闁挎稒绻堝铏规喆閸曨偆顦ㄥ銈嗘肠閸ャ劎鍙嗛梺闈涚墕濡梻鎹㈤崱娑欑厪闁割偅绻傞埀顒€鎲＄粋宥夊礈瑜忕壕钘壝归敐鍡楃祷濞存粎鍋撶换婵嬪閿濆棛銆愭繝銏ｆ硾濞差厼鐣烽幋锕€绠婚悹鍥皺椤ρ勭節閵忥絾纭鹃柨鏇稻缁旂喖寮撮姀鈾€鎷绘繛杈剧到閹诧繝宕悙瀵哥閻犲泧鍛殼閻庤娲樼划宀勫煡婢舵劕顫呴柍銉ュ帠閹綁姊绘担绛嬫綈闁稿骸鍚嬮幈銊╁Χ婢跺﹦鍘遍梺鍦劋椤ㄥ棝鎮￠弴銏″€堕柣鎰絻閳锋棃鏌熼崘鍙夊殗闁哄本鐩顒傛崉閵婃剬鍥ㄧ厵妞ゆ梻鐡斿▓妯肩磼椤曞懎骞栭柍钘夘槸铻ｉ悹鍥у级椤忥繝鏌ｆ惔銈庢綈婵炲弶锕㈤幃锟犳晸閻樿尪鎽曞┑鐐村灦閻喖鈻介鍡欑＝濞达綁娼ч悘鈺傜箾閸礁鍟犻弨浠嬫煟閹邦剙绾ч柍缁樻礀闇夋繝濠傚閻﹥绻涢幓鎺斾虎闁宠鍨块幃鈺咁敊閼测晙绱樻繝鐢靛仜椤︽壆绮欓幒鎴殫闁告洦鍨伴悙濠冦亜閹哄棗浜剧紒鐐劤椤兘寮婚悢鐓庣鐟滃繒鏁☉銏＄厽闁规儳宕崝锕傛煙椤旂瓔娈滈柡浣瑰姍瀹曟帒鈽夊▎鎴濈悼缂傚倸鍊烽懗鑸垫叏闂堟稓鏆嗙紒瀣儥濞兼牠鏌ц箛鎾磋础缁炬儳鍚嬫穱濠囶敍濮橆厽鍎撻悶姘箓閳规垿鎮欓懠顒佹喖缂備緡鍠栫粔鍫曞礆閹烘绠婚悹鍥у级濡差剟姊洪柅鐐茶嫰婢ь垶鏌曢崶褍顏鐐村笒椤撳ジ宕煎┑鍡楄厫婵犵數濮幏鍐川椤旇姤鐦庨梻渚€鈧偛鑻晶顖涖亜閺冣偓閻楃姴鐣锋导鏉戝唨妞ゆ挻绋堥崑鎾绘晝閸屾稓鍙嗛柣搴岛閺呮繄绮诲顑芥斀妞ゆ梻鏅粻鎾绘煟椤撶偟澧曢崡閬嶆煟閹达絽袚闁抽攱鍨圭槐鎺斺偓锝庡亽閸庛儵鏌涙惔銏犲闁哄瞼鍠栧畷銊︾節閸愩劉鍋撻幇鐗堢叆婵犻潧鐗嗘禒婊堟煃鐟欏嫬鐏╅柍褜鍓ㄧ紞鍡涘磻閸曨剛顩叉俊銈呮噺閻撴瑩鏌涜箛姘汗闁哄棙锕㈤弻娑㈠Ω瑜忕敮娑氱磼閸屾氨效闁诡喗鐟╅、妤呭磼濠婂懏顫岀紓鍌欑婢ц姤鏅跺Δ鍕稊闂備胶顭堥鍡涘箲閸パ呮殾婵せ鍋撻柟宕囧█椤㈡宕熼鐐殿槶闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鍨鹃幇浣圭稁閻熸粎澧楃敮妤呭磻閿熺姵鐓冮柛婵嗗閸ｆ椽鏌涚€ｎ倖鎴﹀Φ閸曨垰鍗虫俊銈傚亾濞存粍鍎宠灃闁绘﹢娼ф禒锕傛偨椤栥倗绡€闁绘侗鍠楃换婵嬪炊閵婏箑鍔掓俊鐐€栭崝褏绱為崱妞㈡盯宕橀瑙ｆ嫼缂備緡鍨卞ú姗€寮惰ぐ鎺撶厱閻庯綆鍋呯亸顓熴亜椤忓嫬鏆ｅ┑鈥崇埣瀹曞崬螖閸愵亝鍣梻鍌欒兌椤牓鏁冮妶澶嗏偓锕傛倻閽樺鐣鹃悗鍏夊亾闁告洦鍋勯懓鍨攽閻愭潙鐏﹂柣鐔濆洤鍌ㄩ梺顒€绉甸埛鎴︽⒑椤愶絿鈽夌€规挸妫欑换娑欐媴閸愬弶鎼愰柛鎴犲█閺岋綁寮崹顔藉€梺缁樻尵閸犳牠寮婚悢鐓庣畾鐟滃秹鎳滆ぐ鎺撶厱闁哄啯鎸鹃悾鐢告煛鐏炵硶鍋撳畷鍥ㄦ畷闁诲函缍嗛崜娑㈡儊閸儲鍊甸悷娆忓缁€鍐煥閺囨ê鐏ǎ鍥э躬楠炴牗鎷呴懖婵勫姂閺屾洝绠涢弴鐐愨€愁熆鐟欏嫭绀嬮柟顔煎槻椤劑宕ㄩ褎姣夐梺姹囧焺閸ㄨ京鏁垾宕囨殾闁靛鍔婃禍褰掓煙閻戞ɑ灏甸柛妯绘崌閹嘲顭ㄩ崟顓犵厜閻庤娲樼划宀勶綖濠靛洦缍囬柕濞垮劚缁?"
        return "Trainer cannot start working yet because there is no usable API key. Save a large-model provider and API key in Settings, then I can properly start coaching."

    def _missing_api_key_reply_with_scaffold(
        self,
        profile: UserProfile,
        message: str,
        *,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        missing_key_line = self._missing_api_key_reply(response_language=response_language).strip()
        scaffold = self._scaffold_reply(
            profile,
            message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        ).strip()
        if not scaffold:
            return missing_key_line
        return f"{missing_key_line}\n\n{scaffold}"

    def _fallback_empty_reply(
        self,
        *,
        profile: UserProfile | None = None,
        message: str = "",
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        self._record_last_reply_override(
            **_build_empty_reply_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
        )
        return self._visible_empty_reply_guidance(
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        lead = _localized_text(
            "The provider finished this turn without any visible coaching reply, so I am keeping the same learning lane moving locally.",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欓崑宥夋⒑閹肩偛濡肩紓宥咃躬瀵崵鈧綆鍠栭悙濠囨煏婵炑冩噽濡插洭姊绘担绋款棌闁绘挸鐗撳畷鎴﹀礋椤掍礁寮块梺鍓插亖閸庨亶寮告笟鈧弻娑㈩敃閻樻彃濮曢梺?provider 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欓崑宥夋⒑閹肩偛濡肩紓宥咃躬瀵崵鈧綆鍠栭悙濠囨煏婵炑冩噽濡插洭姊婚崒姘偓鎼佹偋婵犲嫮鐭欓柟鐑橆殔缁犲綊鏌熼柇锕€鏋ょ痪鎯с偢閺岀喖鏌囬敃鈧獮妯荤箾閹绘帞鎽犻柟渚垮妽缁绘繈宕橀埞澶歌檸闁诲氦顫夊ú蹇涘礉瀹ュ洦宕叉繝闈涙处閸庣喖鏌曡箛瀣仾婵炲牓绠栧铏规嫚閺屻儺鈧鏌涘Ο鑽ょ煉鐎规洘鍨块獮妯肩磼濡厧骞嶉梻鍌氬€搁崐鎼侇敋椤撯懞鍥晜閸撗咃紲闂佺粯锚绾绢厽鏅堕鈧彁闁搞儜宥堝惈婵犵鈧磭鍩ｇ€规洘甯掗～婵嬵敃閵忊晜顥￠梻鍌氬€搁崐椋庣矆娓氣偓閹潡宕堕‖顒佺洴瀹曠喖顢涢埀顒勫炊椤掑鏅梺缁樺姌鐏忔瑩宕㈠ú顏呭€垫鐐茬仢閸旀碍銇勯敂鍨祮妤犵偛妫濋幃娆徢庨璺ㄧ泿闂備浇顫夋竟瀣疾濞戙垺鍊舵い鏃€绁硅ぐ鎺撳亹闁惧浚鍋勯埀顒佸姈閹便劍绻濋崘鈹夸虎闂佸搫鑻幊搴ㄥ煡婢跺娼╅柨婵嗘濞呭啴姊婚崒娆戭槮闁硅绻濆濠氬Ω閳哄倸鍓归梺绋跨灱閸嬫盯鎮橀幎鑺ョ叆闁哄洨鍋涢埀顒€鎲￠崕顐︽⒒娴ｅ摜鏋冩俊妞煎姂閹虫宕奸弴鈧崶銊ヮ嚤閻庢稒菤閹锋椽鏌ｆ惔鈩冭础濠殿喕鍗抽崺鈧い鎴ｆ娴滈箖姊绘担渚劸妞ゆ垵妫濋獮鎰板礈瑜庨～鏇㈡煙閻戞﹩娈旈幆鐔兼⒑闂堟侗妯堥柛鐘冲哺瀹曘儳鈧綆浜栭弨鑺ャ亜閺冨倶鈧寮ㄧ紒妯圭箚闁绘劘鍩栭ˉ澶愭煟閿濆洤鍘存い銏℃礋閺佸啴鍩€椤掑倻鐭嗛悗锝庡亖娴滄粓鏌熼弶鍨暢缂佸绮妵鍕棘閸噮浼冨┑顔硷功缁垶骞忛崨顔剧懝妞ゆ牗绮屾慨濂告⒒娴ｇ懓顕滄繛娴嬫櫇缁骞橀懡銈呯ウ婵犵數濮村ú銈囩不婵犳碍鍋ｉ柛銉簻閻ㄦ椽鏌涘Ο缁樸仢闁诡喗顨婇悰顕€宕归鐓庮潛婵＄偑鍊х€靛矂宕圭捄铏规殾闁跨喓濮寸粻顕€鏌ら幁鎺戝姢闁告ü绮欏娲传閸曨偅娈梺绋款儏濡繈骞冮悙鍝勭鐟滃宕戦幘鏂ユ灁闁割煈鍠楅悘宥夋煟鎼达絿鎳楅柛娑卞枛鎼村﹤鈹戦悩缁樻锭妞ゆ垵妫濆畷鎴﹀Ω閳哄倵鎷婚梺鍓插亞閸犲酣宕规笟鈧弻鏇＄疀閵壯咃紵缂備胶濞€缁犳牠骞冨鈧幃娆撳箵閹哄棗浜鹃柛娑橈攻閸欏繘鏌涘畝鈧崑鐐烘偂濞嗘劑浜滈柡鍐ㄦ处椤ュ鏌涢弬璇测偓婵嬪箖閿熺姴围闁糕剝鍔掔花濠氭椤愩垺澶勯柟绋款煼瀹曡櫕绂掔€ｎ偆鍘卞┑鈽嗗灣缁垶宕愰幇鐗堢厵妞ゆ梻鐡斿▓婊呪偓瑙勬礃椤ㄥ棗顕ラ崟顒傜瘈濞达絽澹婂Λ婊堟⒒閸屾瑦绁版い鏇嗗洤绀勯柣锝呯灱缁€濠囨煕閳╁啰鈽夌紒鈧崼鐔虹闁瑰瓨鐟ラ悘顏堟煕鎼粹槄韬柡灞剧洴椤㈡洟鎮╅幓鎺戭潥闂備胶顭堥敃锕傚极婵犳艾绠栫€瑰嫭澹嬮弸搴ㄧ叓閸ャ劍鎯勫ù鐘插⒔缁辨挻鎷呴幓鎺嶅闂備礁澹婇崑渚€宕曢弻銉﹀亗闁哄洨鍠嶇换鍡樸亜閺嶃劎鐭婄€涙繂鈹戦悙鑼勾闁稿﹥绻堥獮鍐灳閹颁焦寤洪梺閫炲苯澧寸€殿喖顭烽幃銏ゅ川婵犲嫮肖闂備礁鎲￠幐鍡涘川椤旂瓔鍟呯紓鍌氬€搁崐鐑芥嚄閼稿灚鍙忛柣銏㈡暩閻瑩鏌熼悜姗嗘當濡楀懘姊洪崨濠冨闁搞劍澹嗙划缁樼節濮橆厾鍘垫俊顐︻暒閼冲爼宕濆澶嬬厓缂備焦蓱鐏忔壆绱掔紒妯笺€掗柍褜鍓氱粙鎺椻€﹂崶顒佸剹鐎光偓閸曨剛鍘遍柣搴秵閸撴瑩寮告惔銊ョ闂侇剙绉甸悡娆撴煟濡も偓閻楀﹦娆㈤懠顒傜＜闁绘ê妯婇悡濂告煙椤旂瓔娈旈柍钘夘槸閳诲秹顢樿闁垱銇勯姀鈩冨磳妤犵偞顭囩槐鎺懳熼柨瀣伖闂傚倷娴囬鏍垂鎼淬劌宸濇い鏍电到閺佷粙姊婚崒娆掑厡妞ゃ垹锕ら埢宥夊即閵忕姷顔囬梺鍛婃寙閸愩劎浜版俊鐐€栭幐鍫曞垂濞差亜鐤鹃柟闂寸劍閻撶喐淇婇婊呭笡闁诲繘浜堕弻鐔兼煥鐎ｎ偁浠㈠┑顔硷龚濞咃絽鈽夐悽绋垮窛妞ゆ挻绻冮惈蹇涙⒒娴ｄ警鐒炬い鎴濇缁瑩骞掗幘鍨涙敵婵犵數濮撮崯浼存⒔閸曨垱鐓曟繛鎴烇公閸旂喖鏌涘Ο鍦煓婵☆偄鎳橀、鏇㈠閳ユ剚妲辨繝娈垮枛閿曘劌鐣烽悽闈涘灊濠电姵纰嶉崐鐑芥煟閹寸儐鐒介柛姗€娼ч—鍐Χ閸℃锛曢梺绋款儐閹稿墽妲愰幒妤佸亹鐎规洖娲ら埛灞轿旈悩闈涗粶闁哥噥鍋婇垾锕傚Ω閳轰線鍞堕梺缁樻椤ユ挸顬婇灏栨斀闁绘﹩鍠栭悘閬嶆煕閳哄倻澧电€规洘绻堝鎾閻樺磭鈧剟鎮峰鍛暭閻㈩垱顨婇崺娑㈠箳閹炽劌缍婇弫鎰板川椤斿吋娈橀梻浣筋嚃閸ㄤ即鎮ф繝鍕床婵炴垶鐭▽顏堟煕鐏炴崘澹樻い顐㈡喘閹鎲撮崟顒傤槶婵犫拃鍕垫疁妤犵偛妫濆顕€宕煎顏佹櫊閺屾洘绔熼姘殭鐞氭繃绻濈喊澶岀？闁稿鍨垮畷鎰板冀椤愶絾娈伴梺鍦劋椤ㄥ懐澹曡ぐ鎺撶厵闂傚倸顕ˇ锕傛煕鐏炶濮傞柡宀€鍠撶槐鎺楀閻樺磭浜堕梻浣虹帛閹歌崵绮欓幘璇茬劦妞ゆ巻鍋撻柛妯荤矒瀹曟垿骞樼紒妯煎帗閻熸粍绮撳畷婊堟偄妞嬪孩娈炬繛鏉戝悑濞兼瑧绮绘繝姘厾闁告稑顭崯蹇旂箾閼测晛鏋涙慨濠冩そ瀹曠兘顢橀悙鎻掝瀱闂備焦鎮堕崐褏绮婚幘璇茬畺闁靛繈鍊曠粈鍌炴煕韫囨洖甯堕柛鏃€甯″娲嚒閵堝憛銏＄箾閼碱剙鈻堥柛鈹惧亾濡炪倖宸婚崑鎾绘煕閻旂顕滅紒鏃傚枛瀹曞崬螣閼测晝妲囩紓浣哄亾濠㈡﹢藝鏉堚晛顥氶柛褎顨嗛悡鏇㈡倵閿濆骸浜滈柣蹇擃嚟閳ь剝顫夊ú姗€宕濆▎蹇ｅ殨濞寸姴顑愰弫鍥煟閹邦垰鐓愰柟韫嵆濮婄粯绗熼埀顒€顭囪婢ф繈姊烘潪鎵瓘缂佺粯绻傞悾鐑藉醇閺囥劍鏅㈡繛杈剧秮閺呰尙绱撻幘鍓佺＝闁稿本鐟чˇ锔姐亜閹存繄澧︾€规洘娲樼换婵嗩潩椤掑偆鍟堥梻浣告惈濞层垽宕瑰ú顏勭厱闁硅揪闄勯悡娆戠磼鐎ｎ偄顕滈柟鐧哥悼缁辨帡鎮╅搹顐㈤瀺闂侀潧娲ょ€氫即寮崒鐐插瀭妞ゆ棁鍋愰妶顕€鏌ｆ惔銈庢綈婵炲弶锕㈠畷褰掑垂椤旂偓娈鹃梺缁樻⒒閳峰牓寮鍡欑闁瑰鍋犳竟妯活殽閻愯尙澧涚紒缁樼箞閹粙妫冨☉鎺撶€版繝鐢靛仒閸栫娀宕ㄩ鍕濠殿喗顭囬崢褎鏅剁€电硶鍋撶憴鍕缂佽鍊块垾锕傚Ω閳轰線鍞堕梺缁樻煥閹碱偊鐛崼銉︹拻濞达絿鎳撻婊呯磼鐠囨彃鈧灝鐣烽鐑嗘晝闁挎洍鍋撶紒鈧径鎰叆闁哄啫娲よ闂佸憡鐟ョ换鎰板煘閹达附鍋愰柟缁樺笚濞堟煡姊洪棃娑欏缂佽鐗撳濠氭偄绾拌鲸鏅╅梺鑽ゅ枑濠㈡﹢鍩涙径鎰拺閻犲洠鈧磭浠┑鈽嗗亜閸熸潙顕ｉ锕€绠涢柡澶婄仢閼板灝鈹戦悙鍙夘棞闁兼椿鍨辩粋宥夋倷椤戝彞绨婚梺鍝勫€藉▔鏇炐掗悙鐑樼厸闁逞屽墯缁傛帞鈧綆鍋嗛崢浠嬫⒑瑜版帒浜伴柛鎾村哺閸┿垽寮撮悢鍓佺畾闂佸湱绮敮鐐电矓濞差亝鐓涚€光偓鐎ｎ剛袦闂佺硶鏂侀崜婵堟崲濠靛纾兼繝濞惧亾婵℃鎹囬弻锝嗘償閵堝孩缍堝┑鐐插级閿氭い顏勫暣閹崇偤濡烽敃鈧鍧楁⒑闁偛鑻晶鎾煛鐏炵偓绀嬬€规洜鍘ч埞鎴﹀炊瑜庨銈嗕繆閻愵亜鈧牕顫忛崷顓熸殰闁跨喓濮撮拑鐔兼煥濠靛棭妲归柛瀣姍閺屾稑鈻庤箛锝喰ㄩ梺瀹狀潐閻╊垶寮婚敐鍫㈢杸闁规儳澧庨澶愭⒑閼姐倕鏆遍柡鍛█婵″瓨鎷呴懖婵堝枑缁轰粙鎳為妷锔轰虎濡炪們鍨哄Λ鍐ㄧ暦閵娾晩鏁傞柛娑卞弾娴兼牠姊婚崒姘偓椋庣矆娴ｉ潻鑰块梺顒€绉埀顒婄畵瀹曞ジ鍩楅埡浣峰濠电偞鍨剁敮妤€鈻嶉崶褜鐔嗛悷娆忓缁€瀣煙椤旇崵鐭欑€规洏鍔嶇换婵嬪礋椤愩垻鐤勯梻鍌欐祰椤曆囧礄閻ｅ瞼绀婇柛鈩冪☉绾惧鏌涘☉鍗炲箻闁哄棴濡囬埀顒€鍘滈崑鎾绘煕閺囥劌澧伴柛妯绘倐閹宕楁径濠佸闂佽鍑界紞鍡涘礈濞戙垺鏅柣鏂垮悑閳锋垿姊洪銈呬粶闁兼椿鍨遍弲鍫曞礈瑜忕壕濂告煕濞嗗浚妲归柕鍥ㄧ箘閳ь剚顔栭崰妤勩亹閸愵喖鐓橀柟瀵稿Л閸嬫捇鏁愭惔婵堟晼濡炪倧瀵岄崳锝夊箖濡ゅ懐宓侀柛顭戝枛婵骸鈹戦悙鑼勾闁告柨瀛╃粩鐔煎即閵忊€虫異闂佸啿鎼崯浼存晬濠靛洨绠鹃弶鍫濆⒔缁夘剚銇勯弴鐔哄⒌闁诡喚鍋ら幊鐐哄Ψ瑜忛鏇㈡⒑閸︻厾甯涢悽顖楁櫊瀹曠敻鎮㈤崗鑲╁帗閻熸粍绮撳畷婊冣攽鐎ｅ墎绋忔繝銏ｆ硾閳洖煤椤忓嫬鍞ㄩ悷婊冪箻瀵娊鏁傛慨鎰盎闂佸湱鍎ら崹鐢稿汲閻旇鐟邦煥閳ь剛鍒掑▎蹇ｆ綎缂備焦蓱婵挳鏌ｉ悢鍛婄凡濠殿喓鍨荤槐鎾存媴閾忕懓绗￠梺鎸庢磸閸ㄨ棄鐣峰ú顏勭劦妞ゆ帊闄嶆禍婊堟煙閸濆嫮啸闁稿繐鐭傞弻宥夘敍濞戞瑧顦伴梺鍝勬湰缁嬫捇鍩€椤掑﹦绉靛ù婊勭箞瀹曠敻宕堕妸锕€寮挎繝鐢靛Т閸嬪棝鎮￠懖鈹惧亾鐟欏嫭绀冮悽顖涘浮閸┿垺鎯旈妸銉ь吅濠电娀娼уΛ顓㈡倵閺夋垟鏀介柣妯活問閺嗘粎绱掓潏銊︾鐎规洘鍨甸埥澶婎潨閸℃瑥濮洪梻浣哄仺閸庤京澹曢銏犳辈闁挎洖鍊归悡蹇涚叓閸ャ儱鍔ょ痪鎯ф健濮婂宕熼銏╀純闂佸搫鏈粙鎴﹀煡婢跺娼ㄩ柛顐ゅ枑閺嗙増绻濋悽闈涗粶闁瑰啿楠哥叅闁靛牆顦埀顒佹瀹曟﹢顢欓崲澹洦鐓曟繛鎴濆船閻忥絾銇勯弬鎸庡枠婵﹨娅ｇ槐鎺戭潨閸℃鏆ユ繝纰樻閸嬪懐鎹㈤崼銉у祦闊洦绋戠粻锝夋煥閺冨洦顥夊ù婊勭矒濮婃椽宕ㄦ繝鍕窗闂佺瀛╂繛濠囥€佸▎鎾冲嵆闁靛繆妾ч幏娲⒑閼姐倕鏋戝鐟版楠炴鎮╃紒妯煎幗闂佺粯姊瑰娆撳礉閿曞倹鐓欐い鏃€鏋婚懓鍧楁煕閳哄绡€鐎规洏鍔戦、姗€鍨惧畷鍥у箣婵犵绱曢崑鎴﹀磹閺嶎厽鍋嬫繝濠傜墕绾惧鏌ｉ幇顒佹儓缁炬儳顭烽弻宥夊煛娴ｅ憡娈剁紓浣叉閸嬫挸鈹戦悩鍨毄濠殿喗鎸冲畷鎰板箹娴ｅ憡杈堥梺缁樻⒒閸樠囧礃閳ь剟姊洪幐搴ｂ槈閻庢凹鍠氭竟鏇㈡寠婢规繂缍婇弫鎰板炊閸撲礁濮奸梻渚€鈧偛鑻晶顔界節閳ь剟鏌嗗鍛€銈嗘磵閸嬫挻顨ラ悙鏉戠瑨妞ゎ亜鍟撮幃婊堝煛娴ｅ嘲顥氶梻浣瑰濞叉牠宕愰崨濠傚姅闂傚倷绀侀悿鍥ь浖閵娾晜鍤勯柛顐ｆ硻閸ャ劌顕遍悗娑櫱氶幏娲煟鎼粹剝璐″┑顔诲嵆閸┾偓妞ゆ垼妫勬禍楣冩⒒娴ｄ警鐒炬い鎴濇楠炴劙宕滆椤洟鏌熼悜姗嗘當閹喖姊洪棃娑辨▓闁哥姵宀稿畷銉р偓锝庝簴閺€鑺ャ亜閺冨倶鈧寮ㄧ紒妯圭箚闁绘劖澹嗛惌娆撴煟濞戝崬娅嶆鐐叉喘椤㈡﹢鎮㈠畡鏉课ら梻鍌欑閸熷潡鎮橀崼銉ョ柧婵犲﹤鎳夐崑鎾愁潩椤愩倗鐓撳┑顔硷功缁垶骞忛崨鏉戝窛濠电姴鍟崜鐢告⒒娴ｇ儤鍤€闁搞垺鐓￠、鏍ㄥ緞婵犲嫭娈鹃梺鐟邦嚟閸嬬喓寮ч埀顒勬⒑缁嬫寧婀扮紒顔肩Т閳绘挻銈ｉ崘鈹炬嫼闂佸湱顭堝ù椋庣不閹炬番浜滈柨鏃囶嚙閻忥箓鏌熼鎯т槐鐎规洖缍婇、鏇㈡偐鏉堚晝娉块梻鍌欑濠€閬嶅磿閵堝鍨傞柣銏犲閺佸倹銇勮箛鎾跺闁绘挸鍟村娲垂椤曞懎鍓伴梺璇茬箰椤曨參鍩€椤掍緡鍟忛柛鐘崇墵閹儲绺界粙璺ㄧ暫濠电偛妫欓幐鍝ョ棯瑜旈弻鐔煎箹椤撶偛绠哄銈冨劚椤戝棙绌辨繝鍥ㄥ€锋い蹇撳閸嬫捁顦撮柟宄邦儔閺佹劙宕遍弴鐘电暰闂備焦鎮堕崕顕€寮插鍫稏闁哄洢鍨洪悡娆撴煟閹寸倖鎴犱焊椤撶姷纾奸柛鎾茬娴犺鲸顨ラ悙瀵稿婵炵厧绻樺畷婊嗩槾闁挎稓鍠栧娲川婵犲繋绶甸梺绋款儏濡稑危閹版澘绠婚悗娑櫭鎾剁磽娴ｅ壊鍎忕紒銊╀憾瀹曟垿骞樼拠鍙夊祶濡炪倖鎸鹃崰鎰枔娴煎瓨鈷戦悹鎭掑妼閺嬫柨鈹戦鑺ュ唉鐎殿喖鎲＄粭鐔煎焵椤掑嫬钃熸繛鎴欏灩缁犳盯姊婚崼鐔衡姇闁诲繐鐗忕槐鎺楁倷椤掆偓閸斻倝鏌涘顒夊剶妤犵偛鐗撴俊鎼佸Ψ鎼达絽鏋戠€垫澘瀚划娆撳箰鎼粹€冲闂傚倸鍊风粈渚€骞栭鈶芥盯寮崼婵堫攨闂佽鍎煎Λ鍕嫅閻斿吋鐓ユ繝闈涙－濡插綊鏌涚€ｎ亜顏柡灞剧☉閳规垿宕熼銏犘戦梻浣虹帛閹哥兘鎳楅崜浣诡潟闁规儳顕悷褰掓煕閵夋垵瀚禍鍫曟⒒娴ｇ儤鍤€闁硅绻濋獮鍐磼閻愵亖鍋撴担鍓叉僵闁肩鐏氬▍婊勭節閵忥絾纭鹃柨鏇畵椤㈡瑩宕ㄧ€涙ǚ鎷洪梺鍏间航閸庡秹顢旈崺璺烘喘閺屽棗顓奸崨顖ｆХ闂備礁婀遍搹搴ㄥ窗濡ゅ懎鐓曢柟杈鹃檮閻撴洘绻涢幋鐑囧叕鐎规悶鍎遍埞鎴︻敋閸℃瑧鏆犻梻鍥ь槹缁绘繃绻濋崒娑樻婵炲濮炬ご鎼佸Φ閸曨垰顫呴柨娑樺閸ｄ即鎮楀▓鍨灍闁规瓕娅曢幈銊╁焵椤掑嫭鐓ユ繛鎴灻鈺傤殽閻愭惌娈滄慨濠呮濞戠敻宕ㄩ褎顥嶉梻浣筋潐濡炴寧绂嶉悙宸殫濠电姴鍟ㄩ崑鍛存煕閹扳晛濡介弶鍫濈墦濮婃椽宕橀崣澶嬪創闂佺锕ㄩ崺鏍矉瀹ュ拋鐓ラ柛鏇楁櫃缁ㄥ姊虹憴鍕婵炲绋掔粋鎺曨槻妞ゎ叀鍎婚¨鍌滅磽瀹ュ嫮绐旂€殿喛顕ч鍏煎緞濡粯娅嗛梻浣虹《閸撴繈銆冮崨瀵稿祦閻庯綆浜栭弨鑺ャ亜閺冨倶鈧宕濋悢铏圭＜妞ゆ洖鎳庨悘锔筋殽閻愯尙绠荤€规洏鍔戦、娆撳礈瑜庨崵灞句繆閻愵亜鈧牠鎮уΔ鍐ㄥ灊閻忕偟鍋撻崣蹇撯攽閸屾碍鍟為柍閿嬪灴閹綊宕堕妸銉хシ濡炪倖甯囬崹鑽ゆ閹烘柡鍋撻敐搴濈敖濠⒀嶅閳ь剚顔栭崰妤呮偂閿熺姴绠栭柍鍝勫暞鐎氭岸鏌ょ喊鍗炲闁哄棭鍋婂缁樻媴閼恒儳銆婇梺鍝ュУ閹稿骞堥妸鈺佺妞ゆ棁妫勯埀顒€澧庨埀顒冾潐濞叉牕煤閻樿纾婚柟鎹愬煐閸犲棝鏌涢弴銊ュ妞わ负鍎遍埞鎴︽倷妫版繂娈濈紓浣哄У閸ㄥ潡宕洪姀銈呯婵烇綆鍓欐禍婵嬫⒑閸涘﹤濮€闁哄倷绶氶獮蹇撁洪鍛嫼闂佺粯鎸哥€垫帒顭囬悢鍏肩厱濠电姴鍟粈瀣偓娈垮枤椤牓鍩ユ径鎰潊闁挎稑瀚獮鍫ユ⒑鐠囨彃鍤辩紓宥呮缁傚秹鎮滈悾灞藉絾濡炪倖甯掔€氼參鎮″▎鎰╀簻闁哄洨鍋為ˉ鐘电磼閳锯偓閸嬫挸鈹戦悩娈挎殰缂佽鲸娲熷畷妤€顫滈埀顒€鐣峰ú顏呮櫢闁绘灏欓敍婊冣攽閻樿宸ラ柛鐕佸亞缁鎮欏ù瀣杸闂佹寧绋戠€氼剚绂嶆總鍛婄厱濠电姴鍟版晶鐢碘偓瑙勬礃缁诲棝藝鐎电硶鍋撻崹顐ｇ凡闁挎洩绠撻獮鎴﹀礋椤栨鈺冩喐瀹€鈧划顓熷緞婵炵偓鏂€闂佸疇妫勫Λ妤呮倶閿熺姵鐓熸い蹇撴祩濞兼劗绱掗崒姘毙㈡い顓滃姂瀹曞ジ鎮㈤崨濠勫将婵犵數濮烽弫鍛婃叏閻㈠憡鍤屽Δ锝呭暞閸婂嘲鈹戦悩鍙夊闁绘挸绻愰埞鎴︽倷閼碱兛铏庨梺璇叉禋娴滎亪骞冨Δ鈧～婵嬵敄閹傚垝婵犳鍠栭敃锔惧垝椤栫偛绠柛娑欐綑瀹告繂鈹戦悩鎻掆偓鐟扳枔濮椻偓濮婄粯鎷呴悜妯烘畬闂佽绁撮埀顒佺窞閿濆绠虫俊銈傚亾濡楀懘姊洪崷顓烆暭婵犮垺顭囩划鍫ュ礃椤旂晫鍘撻梺鍛婄箓鐎氼剟寮搁妶鍡欑闁肩⒈鍓﹂悞楣冩煃鐟欏嫬鐏撮柟顔规櫇缁辨帒螣婵犳碍鏆橀梻鍌欒兌缁垶銆冮崨顖涘床闁圭儤鎸鹃悵鍫曟煛閸モ晛鏋旈梻鍕閺屾稑鈽夊鍫濅紣婵炲濯崹璺侯潖濞差亜绠归柣鎰絻婵矂姊洪崨濠冪叆闁活剛鍘ч銉︾節閸愵亞鐦堝┑顔斤供閸橀箖宕㈤幖浣光拺缂侇垱娲橀～濠囨煕濡搫鈷旂紒顔芥椤㈡岸鍩€椤掑嫬钃熼柍銉ョ－閺嗗棝鎮楅敐搴″鐞氾附淇婇妶鍥ラ柛瀣仱閹兘鍩℃担鐑樻濠殿喗銇涢崑鎾斥攽閳╁啯鍊愬┑锛勫厴婵偓闁炽儲鍓氭禒鐓庘攽閻樻鏆滅紒杈ㄦ礋瀹曟垿骞嬮敃鈧壕褰掓煙鏉堝墽鐣遍柛銊ュ€圭换娑橆啅椤旇崵鏆楅梺閫炲苯澧柛鐕佸灣閹广垹鈹戠€ｎ亞锛滃┑鐘诧工鐎氼參顢欓弴銏♀拻濞达綀娅ｇ敮娑欐叏婵犲偆鐓奸柛鈺傜洴瀹曞ジ濡烽妷锔锯偓顒勬⒑缁洖澧茬紒瀣浮閹繝寮撮姀鈥斥偓鍫曟煟閹邦厽缍戠紒鈧崘顭戠唵閻熸瑥瀚烽悞鐣岀磼鏉堛劌娴柟顔规櫊瀹曪繝鎮欓懠顑惧仏濠电姵顔栭崰鏍晝閵堝鈧箑鐣￠幍顔芥闂佸湱鍎ら崹鐔煎几鎼淬劍鐓欓柟纰卞幖楠炴鎮敂鐣岀瘈闁汇垽娼цⅷ闂佹悶鍔岄…鐑界嵁婵犲洤绠荤紓浣股戝▍鍥ь渻閵堝懐绠伴悗姘煎櫍瀵娊鏁冮崒娑氬幍闁哄鐗嗘晶浠嬫偩鏉堚晝纾奸柣妯煎劋閻濐亜菐閸パ嶈含濠碘€崇埣瀹曟帒顫濋銏╂缂傚倸鍊烽懗鍫曞磻閹捐纾块柟鎯靶掗埀顒婄畵閹粓鎸婃径搴㈡啺婵犵數鍋為崹顖炲垂瑜版帒纭€闁规儼濮ら悡蹇撯攽閻愯尙浠㈤柛鏃€纰嶉妵鍕敃椤愶紕鐩庨梺瀹狀潐閸ㄥ潡骞冨▎鎾崇煑濠㈣泛锕ラ銈呪攽閻樻剚鍟忛柛鐘冲哺瀵偆绱掑Ο鍦畾闂佹眹鍨婚…鍫㈢矆鐎ｎ偁浜滈柡宥冨妽閻ㄦ垿鏌ｉ銏狀伃婵﹨娅ｇ划娆撳箰鎼淬垺瀚崇紓鍌欑椤戝棛鏁敓鐘茬畺闁汇垹澹婇弫鍌炴煕閳╁啰鎳呴柨娑欑箖缁绘稒娼忛崜褍鍩岄悗娈垮枛閻栧ジ銆侀幘璇插耿婵炴垶鐟ч崢閬嶆煟鎼搭垳绉甸柛瀣噹閻ｉ浠﹂悙顒€寮挎繝鐢靛Т鐎氼喚鏁☉姘辩＜婵°倕鍟弸娑㈡煕閳规儳浜炬俊鐐€栫敮鎺斺偓姘煎墴閹偤宕归鐘辩盎闂佸湱鍎ら崹鐢稿焵椤掆偓閹诧紕绮嬮幒鎴叆闁割偆鍠撻崢鎯р攽閻愯泛钄兼い鏇嗗洦鍊堕柨鐔哄У閻撴盯鏌涘☉鍗炲箹妞わ絾濞婇弻宥堫檨闁告挻姘ㄧ划娆撳箳濡や焦娅囬梺瀹犳〃鐠佹煡寮搁弬妫靛綊鎮╁顔煎壉闂佺粯鎸鹃崰鏍蓟閻斿吋鐒介柨鏇楀亾闁诲骏绱曢幉鎼佸箮婵犲倹澶勯柣鎾跺█閺岋絽螖閳ь剟鎮ч崱娑辨晪婵犲﹤鐗婇悡蹇涙煕閵夋垵鍠氭导鍐╃節濞堝灝鏋撻柛瀣崌濮婃椽骞愭惔锝傛闁诲孩鍑归崣鍐ㄧ暦閾忣偄顕遍悗娑櫱氶幏铏圭磼缂併垹骞栭柟鍐茬箻閹敻顢旈崼鐔哄幗濠德板€曢崯顐﹀煝閸懇鍋撶憴鍕婵＄偘绮欏畷娲礋椤栨氨顦ㄥ銈呯箰濡稑危閸ヮ剚鈷掑ù锝勮閻掗箖鏌￠崼顐㈠缂侇喗鐟╅獮鎺楀箣閺冣偓閻忎線姊洪崗闂磋埅闁稿骸纾褔鍩€椤掑嫭鈷戞慨鐟版搐閻忓弶绻涙担鍐插暞濮ｅ嫰姊婚崒娆愮グ婵℃ぜ鍔庣划鍫熺瑹閳ь剟鐛径鎰櫢闁绘灏欓悿鍕⒑闂堟单鍫ュ疾濠婂牆纾瑰┑鐘崇閻撱垺淇婇娆掝劅婵℃彃缍婇弻锝嗘償椤旂厧鈷嬪┑顔硷攻濡炶棄鐣烽妸锔剧瘈闁告洏鍔嶉～宥夋⒒娴ｇ懓顕滄繛鎻掔箻瀹曟洟妫冨☉姘闂佹寧绻傞悧蹇涙偪閳ь剙鈹戦悙鏉戠仸闁荤啙鍥у偍闁汇垻鏁哥壕浠嬫煕鐏炲墽鎳囨俊鍓у厴閺屾盯濡搁妷褏楔閻庢鍠氶…鍫ュ煡婢跺娼╅弶鍫厜缁憋繝姊绘担绛嬪殐闁搞劌閰ｅ畷鐔碱敊缂併垺鏁ら梻鍌氬€烽懗鍫曞箠閹炬剚鍤曢柛顐ｆ礀缁犳牠鏌涘畝鈧崑娑氱不閺嶎偅鍠愰柡鍌濇硶閺嗭箓鏌ｉ幘宕囧哺闁衡偓娴犲鐓曟い鎰Т閻忣亪鏌涢敐搴＄仯缂佽鲸鎹囧畷鎺戔枎閹烘垵甯梻浣侯焾椤戝棝骞戦崶褏鏆﹂柡鍥╁仧閺嗭箓鏌涢妷銏℃珖妞わ富鍨辩换婵嬫偨闂堟刀銏＄箾鐏炲倸鈧繈骞忛幋锔藉亜闁告縿鍎抽鏇㈡⒑閻熼偊鍤熼柛搴㈠姍閹偤骞栨担鍦幐闂佸憡鍔戦崝搴㈡櫠閺囩姷纾奸柍褜鍓熷畷姗€顢欓悾灞藉妇濠电姷鏁搁崑娑㈡倶濠靛鐒垫い鎺嶈兌婢х敻鏌熼姘卞ⅲ缂佺姵鐩顕€宕掑鍛潓缂傚倷绀佹晶鑺ユ櫠濡ゅ懏鏅┑鐘媰閸℃姣㈤梺鐟板级閹倸顕ｉ崼鏇炲瀭妞ゆ棁濮ら鎺楁⒒娴ｇ瓔鍤冮柛鐕佸亰瀹曟儼顦存い鏃€甯￠弻锝夋偐閸欏鈹涢柣蹇撴禋娴滎亪鐛Δ鍛嵆闁靛繆妾ч幏铏圭磽閸屾瑧鍔嶉拑杈ㄣ亜閵夈儲顥炵紒缁樼洴瀹曨亪宕橀鍛还濠电姰鍨奸～澶娒哄Ο鑲╃处濞寸姴顑呭婵嗏攽閻樻彃顏╅悽顖炵畺濮婄粯绻濇惔鈥茬盎濠电偠顕滅粻鎴犲弲闂佸搫璇為崟顒傛婵犵數濮烽弫鎼佸磻濞戙埄鏁嬫い鎾跺枑閸欏繑銇勯幘鍗炵仼闁汇倗鍋撶换婵囩節閸屾稑娅ら悗瑙勬礀瀵墎鎹㈠☉銏犵闁绘劘灏欓崝浼存⒑缁嬫鍎愰柟鍛婃倐閸┿儲寰勬繛鐐€诲┑鈽嗗灣閸樠勬叏濞差亝鈷掑ù锝堫潐閵囩喖鏌涘Ο鍏兼珪闁轰緡鍣ｉ幃娆撳垂椤愵偅缍楅梻浣告贡閸庛倝銆冮崱娑樼；闁归偊鍠掗崑鎾舵喆閸曨剛顦ュ┑鐐茬湴閸婃繈宕洪崨瀛樺仭闂侇叏闄勭€靛矂姊洪棃娑氬濡ょ姴鎲＄粋宥咁煥閸涱垳锛滅紓鍌欑劍閿氬┑顔碱樀閺屾稑鈻庤箛鏂挎濡炪値浜滈崯瀛樹繆閸洖宸濇い鏍ㄧ矤閸炲爼姊虹拠鎻掝劉闁告垼顫夌粋宥夋倷閸欏偊缍侀獮鍥级閸ф鏁归梻浣告惈濞层劑宕崸妤€绠繛宸簼閳锋垿鏌涘☉姗堝姛闁宠棄顦甸弻銊╁即濡搫濮㈢紓渚囧枛閻楁捇宕洪埀顒併亜閹烘垵顏柍閿嬪灴閹綊宕堕鍕缂備胶濮甸悡锟犲蓟閵堝牄浜归柟鐑樻⒒閺嗩偊姊虹拠鈥虫灍婵＄偘绮欓妴浣割潨閳ь剚鎱ㄩ埀顒勬煃闁款垰浜鹃梺鐟板槻椤嘲顫忛搹鍦煓闁圭瀛╅幏閬嶆⒑閼姐倕鏆€闁告侗鍨抽獮鎾绘⒑閸濆嫬鏆欓柣妤€锕幃锟犲礃椤忓懎鏋戝┑鐘诧工閻楀棛绮堥崼鐔虹闁瑰瓨鐟ラ悘鈺冪棯閸撗呭笡缂佺粯鐩獮瀣枎韫囨洑鐥梻浣规偠閸婃牠宕濋弽顓炍﹂柛鏇ㄥ灠閸愨偓闂侀潧臎閳ь剚鎱ㄩ崶褉鏀介柣鎰级閸ｈ棄鈹戦鐐毈濠碉紕鏁诲畷鐔碱敍濮橆剙鏁ゆ俊鐐€栭崝锕€顭块埀顒佺箾瀹€濠侀偗婵﹨娅ｇ槐鎺懳熺拠鏌ョ€烘繝鐢靛仩鐏忔瑩宕伴弽褜鍤曞┑鐘崇閸嬪嫰鏌涜箛鏇炲付闁逞屽墴閺€閬嶅Φ閸曨垰绠崇€广儱鐗嗛崢锛勭磽娴ｅ壊鍎忔繛宸幖椤繐煤椤忓嫬绐涙繝鐢靛Т鐎氼噣鎮鹃幆褉鏀介柣鎰级鐎氬懐绱撳鍕獢鐎规洘妞介崺鈧い鎺嶉檷娴滄粓鏌熼悜妯虹仴闁哄鍊栫换娑㈠礂閻撳骸顫嶇紓浣虹帛閻╊垰鐣烽敐鍡楃窞婵☆垳鍘ф慨娲⒒娴ｇ儤鍤€缂佺姴绉瑰畷褰掓寠婢跺本娈鹃梺缁樻尭缁ㄥ爼寮ㄦ禒瀣厱妞ゆ劑鍊曢弸鎴炪亜閺冣偓濞茬喎顫忕紒妯肩懝闁逞屽墮椤洩顦跺褎绻堝娲传閸曨剙娅濋梺鍝勬噽婵挳顢氶敐澶樻晝闁挎洍鍋撻柣鎰躬閺屾洘绻涜閹峰宕惔銊︹拻濞达絿鍎ら崵鈧銈嗘处閸欏啫鐣烽幋锔藉亜闁绘挸娴烽悿鍥⒑瑜版帒浜伴柛妯哄⒔缁粯銈ｉ崘鈺冨幈闂婎偄娲﹂幐鎼佸箖閹寸偑浜滈柕澶堝劤婢ф盯鏌熸笟鍨缂佺粯绻堝畷鐔碱敇閻愭鍋ч梻鍌欒兌閹虫捇宕查弻銉ョ疇婵☆垵娅ｉ弳锕傛煏婵犲繐顩紒鈾€鍋撻梻浣告啞閸旀垿宕濈仦鍓х彾鐎广儱顦伴埛鎺楁煕鐏炲墽鎳呮い锔肩畵閺岀喖鎳為妷褏鐓夐悗瑙勬礃婵炲﹥淇婇悜钘夌厸濞达絿灏ㄧ槐鍗炩攽閻樺灚鏆╁┑顔芥尦瀹曟劖绻濆顒佽緢闂佹寧娲栭崐褰掓偂濞嗘挻鈷戞い鎾卞妿閻ｉ亶鏌＄€ｃ劌鈧繈寮婚敐澶樻晣闁绘梻鍎ら崳浼存⒑閸濆嫮鐏遍柛鐘虫尵閸掓帒鈻庨幘鍐茬€銈嗘礀閹冲孩淇婇悜鑺モ拻濞达綁顥撴稉鑼磼閻樺啿鐏撮柡灞斤躬閺佹劙宕担鍦▉濠电姷鏁告慨鐢告嚌閸撗冾棜闁稿繐鍚嬮崣蹇旀叏濡も偓濡宕㈤幘顔界厱閻庯綆鍋呭畷宀勬煙椤旂晫鐭掗柟宕囧仱婵＄兘濡烽姀鐘卞闂佺鍕垫畷闁绘挶鍎甸弻锟犲炊閳轰椒绮堕梺閫炲苯澧柟鑺ョ矌閸掓帗绻濆顒€鍞ㄥ銈嗘尵閸犳捇宕㈤崡鐑嗘富闁靛牆妫楁慨褏绱掗幓鎺戔挃缂侇喖鐗撻崺鈧い鎺戝€荤壕濂告煟閹伴潧澧柛鏂诲€楃槐鎾愁吋閸滃啳鍚悗娈垮枛椤兘寮幘缁樺亹闁肩⒈鍓欓埀顒傚仱濮婅櫣鈧湱濮伴埀顑藉亾闂佺顑嗛幐鍓ф閹烘挻缍囬柕濞垮劗閺嬫瑩姊虹拠鈥虫灈闁搞垺鐓￠崺銏℃償閵堝洨鏉搁梺鐟扮仢閸熲晝妲愬┑鍥╃瘈缁剧増锚婢ц尙鎲搁弶鍨殶缂佽京鍋炵换婵嬪炊閳轰胶銈﹂梻浣告惈缁嬩線鎮橀弮鈧幆鏃堚€﹂幋鐐存珜闂備線鈧偛鑻晶鎾煙椤旀儳浠遍柟顔界矊铻ｉ柤娴嬫櫓閸熷酣姊绘担绋挎倯缂佷焦鎸冲鎻掆槈閵忕姴鍤戝┑鐐村灦閻燂箓宕ｈ箛鎾斀闁绘ɑ褰冮弳鐐烘煏閸ャ劎绠橀柍褜鍓濋～澶娒哄鍫濈婵せ鍋撻柕鍡曠椤粓鍩€椤掑嫬绠栨繛鍡樻尭缁犵敻鏌熼悜妯肩畼闁逞屽墮瀹曨剟鍩為幋锔藉亹闁割煈鍋呭В鍕⒑缁嬫鍎戝┑鐐╁亾濡炪們鍨洪懝楣冣€﹂妸鈺佸窛妞ゆ牗鐟ч悷婵嬫⒒娴ｇ儤鍤€闁宦板妿閹广垽宕掑鍛劸濡炪倖鍔忛幊鍥绩娴犲绠抽柟鎯版绾惧湱鎲歌箛鎿冨殫濠电姴鍟伴々鐑芥倵閿濆簼绨介柡灞界墕椤啴濡堕崱娆忊拡闂佺顑嗛惄顖炲箖閿熺姴鍗抽柕蹇ョ磿閸樼敻鏌ｆ惔锝嗘毄妞ゎ厼鐗婄粋鎺楁晝閸屾稓鍘卞┑鐐叉缁绘帞绮绘繝姘厸鐎光偓鐎ｎ剛袦闂佽鍠撻崹钘夌暦椤愶箑绀嬮柛顭戝亝閻︽棃姊婚崒娆掑厡闁硅櫕鎹囧畷銉р偓锝庡枛缁€澶嬬箾閸℃ɑ灏柦鍐枛閺屻劌鈹戦崱娆忊叡闂佹眹鍊愰崑鎾斥攽閻樺灚鏆╁┑顔芥尦瀹曨垶顢涢悙鏉戜户闂佸搫娲㈤崹娲煕閹达附鈷掗柛顐ゅ枔閳洟鏌熼崗鐓庡闁诡喗顨呴～婵嬵敃閵忕姷銈梻渚€娼уΛ鏃傜矆娓氣偓閿濈偛顭ㄩ崼婵堝姦濡炪倖甯掔€氼剛绮婚弽顓熺厓闁告繂瀚崳鍦磼閻樺灚鏆柡宀€鍠栭幃婊兾熼搹閫涙偅婵＄偑鍊栭幐璇差渻閽樺娼栧┑鐘宠壘绾惧吋绻涢崱妯虹瑨闁告﹫绱曠槐鎾寸瑹閸パ勭彯闂佹悶鍔忔禍顒傚垝椤撱垺鍋勯柤鑼劋濡啫鐣烽妸鈺婃晣闁靛繆妲勭槐顒勬⒒閸屾瑧鍔嶉悗绗涘懏宕查柛宀€鍊涢崶顒€纭€闁绘劕鐏氬▓鍏肩箾閹炬潙鐒归柛瀣崌閺屸€崇暆閳ь剟宕伴弽顓炵畺婵犲﹤鍚橀悢鍏煎€绘慨妤€妫楅弲顓㈡⒒閸屾瑧顦﹂柟纰卞亰瀹曨垶顢曢敂钘変罕闂佺硶鍓濈粙鎺楀磹閸ф鐓曟い顓熷灥娴滄牕霉濠婂嫮鐭掗柡宀€鍠栧畷顐﹀礋椤撳鍊栭妵鍕晜閼测晝鏆ら梺鍝勬湰閻╊垰顕ｉ鈧崺鈧い鎺嗗亾閾荤偤鏌涢幇鐢靛帥婵炲吋鐗曢埞鎴︽偐鐎圭姴顥濈紒鐐劤閸氬鎹㈠☉銏犲耿婵☆垵娅ｆ禒濂告⒑缂佹鈼ら柛銊ョ秺閸╃偤骞嬮敂钘夆偓鐑芥煛婢跺﹦浠㈤柣銊у枛濮婅櫣鍖栭弴鐐测拤濡炪們鍔屽Λ婵嬨€侀弮鍫熷亹缂備焦菤閹峰姊虹粙鎸庢拱闁荤啙鍥佸洭鏁冮崒娑氬幍闁荤姴娉ч崨顖ょ吹闂備礁鎲＄敮妤冩暜閳ュ磭鏆﹀┑鍌滎焾椤懘鏌曡箛瀣伄闁告棁娉涢埞鎴︽倷鐎涙ê闉嶉梺绯曟櫅閸熸潙鐣烽幋锕€绠婚柛銊︾☉娴滅偓绻涢崼婵堜虎闁哄鍠栭弻锝夊箼閸曨厾鐦堥梺闈涙缁舵艾顕ｉ鈧畷鐓庘攽鐎ｎ亝鏆梻鍌欒兌缁垶寮婚妸銉殨闁告挷璁查崑?",
            response_language,
        )
        guided_lane_reply = _guided_domain_empty_reply(
            message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if guided_lane_reply:
            return f"{lead}\n\n{guided_lane_reply}"

        if profile is not None:
            scaffold = self._scaffold_reply(
                profile,
                message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            ).strip()
            if scaffold:
                return f"{lead}\n\n{scaffold}"

        file_path = current_file.get("path") if current_file else None
        if _prefers_chinese(response_language):
            if file_path:
                return (
                    f"闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棗鏆欏┑鈥炽偢閺屽秷顧侀柛鎾存皑閹广垽宕煎┑鎰婵犵數濮甸懝楣冨础閹惰姤鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú鐔奉潖閾忓湱纾兼俊顖氭惈琚濋梻浣告啞閹歌鐣濋幖浣哥畺闁汇垻顭堢猾宥夋煕椤愩倕鏆遍柟閿嬫そ濮婅櫣娑甸崨顓濇睏闂佺顑嗙粙鎺撶┍婵犲啰闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛濠傜秺瀹曟垿濡疯閸嬫挸鈻撻崹顔界亪濡炪値鍙冮弨杈ㄧ┍婵犲洤閱囬柡鍥╁仩琚濋梻渚€娼ч悧鍡涘箠韫囨洘瀚婚柨鐔哄У閻撳啰鎲稿鍫濈闁靛ě鍛槸闂佺硶鍓濈粙鎴犲婵犳碍鐓曟繛鎴烆焽閹界娀鏌涚€ｎ剙鏋涢柡宀嬬節瀹曞爼濡烽妷褌鐥梻浣侯焾閿曪箓寮繝姘畺鐎瑰嫭澹嬮弸搴ㄧ叓閸ャ劍鎯勫ù鐘插⒔缁辨挻鎷呴幓鎺嶅闂備礁鎲￠崝锕傚窗濡ゅ懏鍋傞柣鏂垮悑閻撴瑩鏌涢…鎴濇灈妞ゅ浚鍋嗙槐鎺楀煢閳ь剟宕戦幘缁樼厽閹兼番鍩勯崯蹇涙煕閻樺磭澧甸柍銉畵閹粓鎸婃径瀣偓顒勬⒑閻熸澘鈷旂紒顕呭灦瀹曟垿骞囬悧鍫㈠幘缂佺偓婢樺畷顒佹櫠椤曗偓閺屽秷顧侀柛鎾寸洴瀹曟垿濡堕崪浣圭稁濠电偛妯婃禍婵嬎夐崼鐔虹闁硅揪缍侀崫娲嚃閺嶎厽鈷掑ù锝勮閻掔偓鎱ㄥ鍫㈢暠闁宠绉瑰鎾偐閻㈢數鍔归梻浣告贡閸庛倝骞愭ィ鍐┾挃闁告洦鍨遍悡鏇熺箾閹寸偐妲堥柛顐犲劚缁狀垱绻涘顔荤凹闁抽攱鍨垮濠氬醇濮橆厽鐝旈梺浼欓檮缁捇寮诲☉妯滅喖宕烽鐘靛幆闁诲氦顫夊ú婊堝极婵犳艾鏄ラ柍褜鍓氶妵鍕箳閹存繍浠鹃梺鎶芥敱閸ㄥ湱妲愰幘瀛樺閻犲浄绱曢崝閿嬬節閳封偓鐏炲ジ鍋楅梺鍝勬湰濞茬喎鐣锋總绋款潊闁冲搫鍟慨鍏间繆閻愵亜鈧牕煤閳哄啫绶ら柛鎾楀嫬搴婂┑鐘绘涧濡厼顭囬埡鍌樹簻闁瑰搫妫楁禍楣冩倵鐟欏嫭灏俊顐ｇ箓椤繘鎼归崷顓狅紲濠碘槅鍨卞鍨潖閸喒鏀介柣鎰级鐎氬懐绱撳鍕獢闁靛棔绀侀埢搴ㄥ箻閸愭彃绁梻渚€娼х换鍡楊瀶瑜旈獮蹇撁洪鍛嫼闂佸憡绋戦敃銉ョ暦閸曨垱鍊堕煫鍥ㄦ⒒閹冲洨鈧娲忛崹褰掑煡婢舵劕顫呴柨娑樺楠炲牓姊绘担铏瑰笡闁挎氨鐥紒銏犲箺闁哄懎鐖奸幃浠嬪川婵犲嫬甯楅梻渚€娼ч¨鈧┑鈥虫处閺呭爼鏌嗗鍡欏帗閻熸粍绮撳畷婊堝Ω瑜忕粈濠囨煕閳╁喚鐒芥い鈺傜叀閹綊鎮滃Ο纭呭焻闂侀€炲苯澧悽顖涱殘閹广垹鈹戦崱鈺傚兊濡炪倖鎸炬慨瀵告暜妤ｅ啯鈷掑ù锝囶焾椤ュ繘鏌涚€ｎ亝鍣介柟骞垮灲瀹曟﹢顢欐總鍛婏紬闂備椒绱徊鑺ュ緞閸ヮ剙纾婚柟鎹愵嚙缁€鍌氼熆鐠虹尨姊楀瑙勬礋濮婄粯鎷呴崫銉ㄥ┑鈽嗗亜濞硷繝骞冮悙鐑樻櫇闁稿本绋戞禍妤呮⒑閸濆嫭鍌ㄩ柛銊︽そ瀹曟劙鎮介崨濠勫弳濠电娀娼уΛ婵嬵敁濡も偓闇夋繝濠傚缁犳﹢鏌嶈閸撴繈锝炴径濞掓椽寮介鐐茬彉濡炪倖甯掔€氼剛绮婚悙鐑樼厪濠电姴绻愰々顒傜磼閳锯偓閸嬫捇姊绘担鍛婂暈婵炶绠撳畷銏ゆ嚃閳哄啰鐣堕梺璺ㄥ枔婵敻鍩涢幋锔界厽闁绘柨鎲＄欢鍙変繆閹绘帩鐓奸柡宀€鍠栭幖褰掝敃閵忕媭娼氭俊銈囧Х閸嬫盯藝閻㈠摜宓佹慨妞诲亾妞ゃ垺鐟╅幊鏍煛婵犲唭褔姊婚崒娆戭槮闁汇倕娲俊鎾焵椤掑嫭鐓曢悗锝庡亝瀹曞矂鏌″畝鈧崰鎾诲焵椤掑倹鏆╂い顓炵墦瀹曘垻鈧稒蓱閸欏繐鈹戦悩鎻掝伀閻㈩垱鐩弻鐔风暋閻楀牆娅ょ紓浣诡殘閸犳牠銆佸☉姗嗙叆闁告劑鍓遍鍕ㄦ斀闁挎稑瀚禍濂告煕婵犲啰澧电€规洖缍婇幃鐣岀矙鐠侯煉绱梻浣稿閻撳牓宕板璺烘辈闁挎洖鍊归悡娆撳级閸繂鈷旈柣锝堜含缁辨帡鎮╅崫鍕優缂備浇椴搁幐濠氬箯閸涱噮娈介柕濠忕畱閸濈儤顨ラ悙鑼闁圭厧缍婂畷鐑筋敇閻欏懐闂繝鐢靛仩閹活亞寰婇懞銉х彾濠电姴娲ょ壕鍧楁煙闁箑骞戝ù婊勭矒閺岀喓鈧數顭堟禒褔鏌熼崘鍙夊窛闁逞屽墲椤煤濡ソ娲偄閼测晛绁﹂梺鎼炲労閸撴岸宕戠€ｎ喗鐓曟い鎰Т閻忊晜顨ラ悙鑼ф慨濠勭帛閹峰懘宕ㄦ繝鍌涙畼缂傚倷绀侀鍡涘垂閸ф鏋侀柛鎰靛枛鍞梺瀹犳〃閼冲爼鏁嶅▎鎾粹拺鐟滅増甯掓禍浼存煕濡搫鈷旂€殿啫鍥х劦妞ゆ帒瀚埛鎴︽⒑椤愩倕浠滈柤娲诲灡閺呭爼顢涘鍛紲濠德板€曢崯顐﹀几濞戙垺鐓曢柍瑙勫劤娴滅偓淇婇悙顏勨偓鏍ь啅婵犳艾纾婚柟鐐暘娴滄粍銇勯幇鈺佺伄缂佺姳鍗抽幃锟犲Χ閸℃劒绨婚棅顐㈡处閹告悂顢旈锝冧簻闁哄倹瀵ч崰姗€鏌″畝鈧崰鏍箠濠靛鍋嬮柛顐ｇ箖闁款厾绱撻崒娆戝妽鐟滄澘鍟…鍥晸閻樿尙鐣烘俊銈忕到閸燁垶藟閸喓绠鹃柟瀵稿仜缁楁岸鏌￠崒妤€浜鹃梻鍌氬€烽懗鍓佸垝椤栫偛绀夋俊顖炴？閻掑﹥绻涢崱妤呯崪闁兼澘娼￠弻鐔虹磼閵忕姵鐏嶉梺缁樻尰濞叉牠鍩為幋锔藉亹闁圭粯甯楀▓璺衡攽閻愭彃绾ч柟鍛婂▕瀵鈽夐姀鐘靛幐婵炶揪绲块幊鎾斥枔濡ゅ懏鈷戦悹鍥ｂ偓铏亶缂備緡鍠楅幑鍥嵁婵犲洦鍊烽柛婵嗗珋閵娾晜鐓忛煫鍥堥崑鎾诲箛娴ｉ搴婂┑鐘垫暩婵兘寮幖浣哥；闁绘劕鎼粻鏉库攽閻樺疇澹橀柡鍕╁劦閺屾盯骞囬棃娑欑亪缂佺偓鍎抽…鐑藉蓟閻旂厧绀堢憸蹇曟暜濞戙垺鐓熼柟鎯у暱閺嗙喖鏌熼懠顒夌劸妞ゎ厹鍔戝畷鐓庘攽閸偅肖濠电姷鏁搁崑鐐哄垂椤栫偛鍨傞柛锔诲幖椤ユ氨绱撴担璇＄劷缂佺娀绠栭弻鐔衡偓娑欘焽閹冲啴鏌ｈ箛锝勯偗闁哄本鐩俊鍫曞幢濡も偓椤秹姊洪棃娑欐悙閻庢碍婢橀锝嗙鐎ｎ€晝鎲告径瀣弿闁搞儜鈧弨浠嬫煟閹邦剙绾ч柛锝堟閳规垿顢欓悙顒佹瘓婵犵绱曢弫璇茬暦閻旂⒈鏁嶆慨姗嗗墮缁侇喗绻濆閿嬫緲閳ь剚鍔欏畷鎴﹀箻鐡掍胶鎳撻…銊╁醇閵忋垺姣囨繝娈垮枛閿曘儱顪冮挊澶屾殾妞ゆ劧绠戠粈瀣亜閹哄秶鍔嶉悗姘－缁辨捇宕掑▎鎴М濡炪倖鍨靛Λ娑㈠极椤曗偓閹瑩宕崟顓у敼闂備線娼х换鎺撴叏椤撱垹缁╁ù鐘差儐閸婄敻鏌ㄥ┑鍡欏嚬缂併劏濮ら妵鍕晜閸濆嫬顫囧┑顔硷龚濞咃綁鍩€椤掆偓濠€杈ㄦ叏閻㈢违闁告劦鍠楅崑锝吤归敐鍛础闁告瑢鍋撻柣搴ゎ潐濞叉﹢宕归崸妤冨祦婵☆垰鍚嬬€氭岸鏌ょ喊鍗炲闁哄鎲℃穱濠囨倷椤忓嫧鍋撻弽褜娼栧┑鐘宠壘缁犵娀鏌熼幆褜鍤熸い鈺傚絻铻栭柨婵嗘噹閺嗙偤鏌涚€Ｑ冨⒉缂佺粯鐩畷鍗炍旈崘顏嶅敹婵＄偑鍊曞ù姘閻愮儤鍎夋い蹇撶墛閸婇攱銇勯幒宥囶槮闁逞屽墯閸旀瑩寮婚敍鍕勃闁告挆鍕灡濠电姷顣介崜婵嬪箖閸屾稐绻嗛柣銈庡灱濡茬偓淇婇妶鍡橆棃婵﹦绮幏鍛存惞楠炲簱鍋撴繝鍥ㄧ厸闁稿本鑹鹃埀顒€鐏濋悾鐑藉即閵忕姷顔岄梺鍦劋缁诲倸鈻撻锔解拺闁告稑锕ユ径鍕煕閵婏箑顥嬬紒顔款嚙閳藉鈻庡鍕泿闂備礁婀遍崕銈夊春閸惊锝夊捶椤撶姷锛濋悗骞垮劚閹冲酣鍩€椤掆偓閻忔繈锝炶箛鏇犵＜婵☆垵顕ч鎾绘⒑閹呯闁硅櫕鎸剧划顓㈡晸閻樻枼鎷洪梺鍦焾鐎涒晝澹曢幖浣圭厱闁靛鍎崇粔娲煃閵夘垳鐣电€规洖鐖奸、鏂款吋閸″繑鐎搁梻鍌氬€烽懗鍓佹兜閸洖妫樺〒姘ｅ亾鐎规洘鍨块獮姗€骞囨担鐟扮槣闂備線娼ч悧鍡椢涘Δ鍐當闁圭儤顨嗛悡鏇炩攽閻樻彃鈧綊宕悙鐢电＜闁稿本绋戠粭姘箾閻撳海绠诲┑鈩冩倐閺佸啴鍩€椤掆偓椤曪綁骞愭惔锝囩槇闂佹眹鍨藉褍鐡梻浣烘嚀閸熻法鎹㈠鈧妴渚€寮崼鐔蜂汗闂佹眹鍨婚弫鎼佹晬濠婂牊鐓涘璺猴功婢ф垿鏌涢弬璺ㄧ伇缂侇噮鍙冮獮鎺懳旀担鐟版畽闂備焦瀵х换鍌炈囨导瀛樺亗闁哄洨鍠撶弧鈧梻鍌氱墛缁嬫帡藟濠婂嫨浜滈煫鍥ㄦ尵閹界姷绱掔紒妯兼创鐎规洘顨婂畷妤冨枈鏉堫煈妫冮梻鍌欑閹碱偊鎯屾径宀€绀婂〒姘ｅ亾妤犵偛鍟存慨鈧柕鍫濇噸缁卞爼姊洪棃娑崇础闁告侗鍘肩粭鎺撶節閻㈤潧啸闁轰礁鎲￠幈銊﹀閺夋垵鐎┑鐐叉▕娴滄繈寮插┑瀣厪闊洦娲栧暩闂佸搫妫撮梽鍕Φ閸曨垰鍐€妞ゆ劦婢€缁墎绱撴担鍝勑ョ紒顕呭灦婵＄敻宕熼姘辩潉闂佹悶鍎滈崒娑氭綎闂?`{file_path}` 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏咁棃婵炴番鍎遍悧鎾愁嚕閹绘巻妲堥柕蹇曞Х椤㈠懘姊洪幆褎绂嬮柛瀣€婚幑銏ゅ幢濞戞瑧鍘梺鍓插亝缁诲倿鍩€椤掆偓閹诧紕绮嬪澶嬪€锋い鎺戝€婚鏇㈡煟鎼淬垻鈯曟い顓炴喘閹瞼鈧綆鍠楅悡鏇㈠箹濞ｎ剙鐏╅柍缁樻礋閺屽秹濡烽敂绛嬫閻庤娲橀敃銏ゃ€佸▎鎾冲簥濠㈣鍨板ú銈囩不閸︻厾纾兼い鏃傚帶鐢劑鏌涚€ｎ偅灏柣锝囧厴瀹曞墎鎹勯悜妯荤彎婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柟闂寸绾剧粯绻涢幋鐑嗙劯闁绘柨鎽滅弧鈧梺鎼炲劀閸涱垰骞€闂傚倷绀侀幉锟犲礉閿曞倸绐楅柡宥庡墰缁犺姤绻濋悽闈涗哗闁规椿浜炲濠勬崉閵婏箑鍘归柣鐘烘〃缂嶅秹鏁愭径濠囧敹闂侀潧顧€婵″洭宕㈤鍫燁棅妞ゆ劑鍨洪幖鎰版嚌瀹€鍕厱閻庯綆鍋呭畷宀€鈧鍣崜鐔镐繆閻戣棄唯闁靛牆鎷嬪Λ婊堟⒒閸屾瑨鍏岀紒顕呭灦瀹曞綊宕楅崗鐓庡伎闂侀潧鐗嗛ˇ顖滃瑜版帗鐓熼柕蹇曞У閸熺偤鏌ｉ幘璺烘灈闁哄本娲濈粻娑欑節閸愮偓缍夐梻浣告憸閸犲海鎹㈠鈧濠氭晲婢跺﹦顔婇梺鐟扮摠缁洪箖骞愰崘顔解拺闂侇偆鍋涢懟顖涙櫠椤栨稏浜滈柡鍐ｅ亾闁绘濮撮悾閿嬪閺夋垵宓嗛梺闈涚箳婵兘銆侀崨瀛樷拺闁告稑锕ゆ慨鍥ㄤ繆椤栨熬宸ユい顓炴喘瀵粙顢曢妶鍥风闯濠电偠鎻紞鈧柛瀣€块獮瀣倷閹绘帞浜栭梻浣告惈椤︿即宕归鐐茬劦妞ゆ帊绀佺粭鎺撱亜椤愶絿绠為柟顔瑰墲閹棃鏁愰崟顓熸毎闂傚倸鍊峰ù鍥ь浖閵娧勵偨闁跨喓濮撮崹鍌毭归懖鈺勊夐柍褜鍓氬Λ鍐ㄧ暦濮椻偓椤㈡瑩宕叉竟顖氭搐缁犲湱绱掗鐓庡辅闁稿鎹囬幊鐘活敆閸屾稒娅掑┑鐘殿暜缁辨洟宕戦幋锕€纾圭憸蹇曞垝婵犳艾绠婚柟棰佽兌閸旂兘鎮峰鍕棃妤犵偛鍟撮獮鍡氼槾闁哄棗顑夐弻鐔告媴閸愨晝褰ч梺鍝勫€甸崑鎾绘⒒閸屾瑧顦﹂柟鑺ョ矋閸掑﹪顢橀姀鐘电崶濠德板€愰崑鎾绘懚閻愮儤鐓曢柟鎵虫櫅婵″潡鏌￠崱顓犵暤闁哄本娲樼换娑㈡倷椤掍胶褰熼梻浣芥〃缁€渚€鏁冮鍕垫綎濠电姵鑹剧壕鍏兼叏濡厧甯舵繛鍫濈埣濮婃椽鎮滈埡鍌涚彅闂備礁搴滅徊浠嬶綖韫囨梻绡€婵﹩鍓涢敍婊冣攽閻愬弶顥為柛鈺佺墕鍗辨い鏇楀亾婵﹨娅ｅ☉鐢稿椽娴ｅ憡鐤傜紓鍌欐祰妞寸煤濠婂牆绀嗛柟鐑樺灍閺嬪酣鏌熼幆褏锛嶆い鎾存そ濮婃椽骞愭惔銏╂⒖濠碘槅鍋勭€氼厾绮嬮幒妤佺劶鐎广儱妫岄幏娲⒒閸屾氨澧涢柛妤佹礋瀹曞ジ濡烽妷褎鐓ｆ繝鐢靛Т閿曘倝鎮ч崱娆忣棜濠电姵纰嶉悡鏇犫偓鍏夊亾闁逞屽墴瀹曟垿鎮欓悜妯轰簵闂婎偄娲﹂幖鈺呮偄閸℃稒鐓犻柛婵勫劜閺嗏晠鏌嶉挊澶樻Ч闁靛洤瀚伴崺鈩冪節閸屾凹娼剧紓鍌欐祰妞村摜鏁敓鐘茬畺闁冲搫鎳忛崵鎺楁煏閸繃澶勬慨锝呮喘濮婄粯鎷呴崨濠冨創闂佹椿鍓欓妶绋跨暦娴兼潙绠婚悹鍥皺閸旓箑顪冮妶鍡楃瑨闁稿﹤缍婂鎶藉煛閸屾ü绨诲銈嗘尵閸嬬喐鏅堕敂閿亾鐟欏嫭绀冪紒顔芥崌瀵宕卞Δ濠傛倯闂佺硶鍓濋悷銉╃嵁濡ゅ懏鈷掑ù锝囧劋閸も偓闂佸湱鈷堥崑鍡欏垝閺冨牆閱囬柡鍥╁枎閸撶懓鈹戦悙鍙夘棡闁圭顭烽幃鈥斥槈濮橈絽浜鹃柛蹇擃槸娴滈箖鏌ｆ惔顖滅У闁告挻绋栭埅闈涒攽鎺抽崐妤佹叏閻戣棄纾婚柣鎰仛閺嗘粓鏌ㄩ悢鍝勑ョ€规挷鐒﹂幈銊ヮ渻鐠囪弓澹曢柣搴㈩問閸犳牠鎮ユ總鍝ュ祦閻庯綆鍠栧Λ妯侯熆閸撲緡鐒炬い銉﹀哺濮婄粯鎷呯粵瀣秷婵犮垻鎳撳Λ娆撳疾鐠轰綍鏃堝川椤旈棿绨垫繝鐢靛仦閸垶宕瑰ú顏勭９闁割偅娲橀悡鐔兼煙闁箑骞栫紒鎻掝煼閺屽秹鏌ㄧ€ｎ偀鎷圭紓浣虹帛閻╊垰鐣烽敐鍡楃窞閻庯綆浜滈弨顓㈡⒒娴ｅ憡鎯堝璺烘喘瀹曟粌鈹戠€ｎ亞顔嗛梺鍛婄☉閻°劑宕戦敓鐘崇厸濠㈣泛顑愰崕銉︾箾閸忕厧鍝洪柡宀嬬稻閹棃濡舵惔銏㈢Х婵犵數鍋涘鍫曟偋閺囥垺鍋╅柣鎴犵摂閺佸棝鏌涢幇鍏哥胺闁煎壊浜缁樻媴閽樺鎯為梺绋款儑閸嬬喓鍒掑▎鎾抽唶闁靛鍎抽崝锕€顪冮妶鍡楀潑闁稿鎹囬弻娑樜熼懡銈咁潷缂備焦姊婚崰鏍ь嚕閹绢喖顫呴柍閿亾闁归攱妞介幃宄邦煥閸涱収鏆柣銏╁灡鐢绮嬪鍡楊嚤閻庢稒顭囬崢閬嶆⒑缂佹◤顏堝疮閸啔褰掝敊闁款垰浜鹃悷娆忓缁€鍐煕閵娿儲鍋ラ柣娑卞枛椤粓鍩€椤掆偓椤曪綁顢楅崟顐嬨劑鏌ㄩ弬鍨稏缂併劍鎸冲濠氬磼濞嗘埈妲繝銏㈡嚀閿曨亪骞冮敓鐘查唶闁靛鍎抽悰銉モ攽鎺抽崐鏇㈠箠韫囨稑纾婚柣鏃€鎮舵禍婊堟煛閸ヮ煈娈斿ù婊勫劤閳规垿顢欑涵閿嬫暰濠碉紕鍋犲Λ鍕偩閻戣棄惟闁挎柨澧介惁鍫ユ⒑閸涘﹤濮傞柛鏂跨Т閳绘捇顢曢敂瑙ｆ嫽婵炶揪绲介幉锟犲箟缁嬪簱鏀芥い鏃傚亾閺嗩剟鏌熼銊ユ处閸嬫劙鎮归崶顏勭毢闁伙絿鍎ょ换娑㈠级閹存繃鍊梺璇″灠閻倸顕ｉ锝囩瘈闁告洦鍘介敍蹇涙⒑閸濆嫷妲搁柣蹇旂箞閹虫粏銇愰幒鎾跺幍濡炪倖妫佸Λ鍕倶閿斿墽纾肩紓浣诡焽缁犵偛鈹戦鐟颁壕闂備焦瀵х换鍌炲箠閹版澘鍌ㄦい鎰堕檮閻撱垽鏌涢幇闈涙灆闁规煡绠栭弻鈥崇暆鐎ｎ剛鐦堥悗瑙勬磸閸旀垿銆侀弮鍫濆窛妞ゆ梹鍎崇紞鍐ㄢ攽閻樻剚鍟忛柛鐘崇墵閺佸啴濡搁妷銏＄€洪梺鎸庣箓濞层倝宕瑰┑鍥╃闁糕剝锚閻忥妇鈧娲栭ˇ鐢稿蓟閺囩喓绠剧憸宥夋嚐椤栫偛鏋侀柣鐔稿閺€浠嬫煥濞戞ê顏╁ù婊冦偢閺屾稒绻涜閹冲宕戦幘缁橆棃婵炴垶姘ㄩ崝顖炴倵鐟欏嫭绀夋い顐㈩槸椤洩绠涘☉妯煎幐闂佸憡鍔︽禍鐐哄礉瑜版帗鐓熼幖杈剧磿閻ｎ參鏌涙惔銊ゆ喚閽樻繂霉閸忓吋缍戠痪鎯х秺濮婃椽宕归鍛壄婵炲瓨绮嶇划鎾诲蓟閻斿憡缍囬柛鎾楀惙鎴犵磼缂併垹骞栧褍娴峰Σ鎰板箳濡や礁浜归柣搴℃贡婵挳藟濠靛棭娓婚柕鍫濈凹缁ㄥ鏌涢悢椋庢憼濞ｅ洤锕畷濂稿即閻愯尪鈧灝鈹戦悙鍙夘棞婵炲瓨鑹鹃…鍥倻閼恒儮鎷绘繛杈剧到閹碱偆鏁崜浣虹＝鐎广儱鎷戦崝鐔虹磼椤旂⒈鐓肩€殿喕绮欓、姗€鎮╅懠顑惧亰闂傚倷绀侀幉锟犲礉閿曞倸绐楅柡宥庡亞娑撳秹鏌ㄥ┑鍡橆棤缂佲檧鍋撻梻鍌氬€搁悧濠勭矙閹达箑姹查柣鎰劋閻撴盯鏌涚仦缁㈡當濞存粎鍋撶换婵堝枈婢跺瞼锛熼梺绋款儐閸ㄥ灝鐣烽幇鏉垮唨妞ゆ挾鍠庢禍鍗炩攽鎺抽崐鏇㈠箠鎼淬垹顕遍柣妯款嚙缁犺绻涢敐搴″濠德ゅ亹閻ヮ亪骞嗚閻撳ジ鏌＄仦鐐缂佺姵绋撻埀顒婄秵娴滄牠宕戦幘璇插唨妞ゆ挾鍠庢禍妤€鈹戦悙鏉戠仧闁搞劍妞藉畷鎰板醇閺囩喓鍘介梺瑙勫婢ф鈽夎闇夋繝濠傚暙閳锋梻绱掓潏銊ユ诞闁糕斁鍋撳銈嗗笒閸婄敻宕戦幘缁樻櫜閹肩补鈧啿绠ｉ梻浣侯焾椤戝棝骞愭ィ鍐ㄧ疅闁圭虎鍠栫粈瀣亜閹烘垵浜炴俊鎻掔埣濮婄粯鎷呴崨濠傛殘濡炪値鍘煎Λ婵嗙暦閹偊妲鹃梺鍛娚戦幐鍐差潖閾忚鍏滈柛娑卞枛濞懷呯磽娴ｅ搫校闁搞劌娼￠獮鍐ㄢ枎閹邦喚鐦堥梺鍛婃处閸撴瑩寮搁幋婵冩斀闁绘顕滃銉╂煕濮橆叏鑰块柡浣瑰姍瀹曞崬螣閼测敩銈夋⒒娴ｇ鏆遍柟纰卞亰瀹曨垱瀵肩€涙ɑ娅栧┑鐘绘涧椤戝棝鍩涢幋鐘电＜閻庯綆鍋勯婊勭節閳ь剚瀵肩€涙鍘介梺缁樻⒐缁诲倸煤閵堝洨鐭嗗璺哄閸嬫捇鐛崹顔煎濡炪倧缂氶崡鎶藉箖閿熺姴鍗抽柕蹇ョ磿閸樻悂姊洪崨濠傚Ё缂佽尪濮ょ粋宥嗐偅閸愨斁鎷虹紓鍌欑劍閿曗晛鈻撳Ο琛℃斀闁绘劏鏅涙禍鎯р攽閻樻鏆柛鎾寸箞楠炴劙宕橀懠顒佹濠殿喗銇涢崑鎾绘煕閳哄绡€鐎规洘锕㈤、鏃堝幢濮楀棙缍嬮梻鍌氬€搁崐鐑芥倿閿曞倸绠栭柛顐ｆ礀绾炬寧绻濇繝鍌滃妤犵偑鍨烘穱濠囶敍濠垫劕娈梺鍝勬－閸嬪﹤顫忔繝姘＜婵﹩鍏橀崑鎾绘倻閼恒儱娈戦梺鍓插亝濞叉牜澹曟繝姘厪濠电偟鍋撳▍鍛棯閹勫仴闁哄矉绱曟禒锔炬嫚閹绘帒顫撶紓鍌欒閸嬫捇鏌涢銈呮瀾闁告瑥绻戞穱濠囶敍濞戞﹩鍤嬬紒缁㈠弮缁犳牠骞冨畡鎵虫瀻婵炲棙鍨归弳銈夋⒑鐠団€虫灍妞ゃ劌锕顐﹀箛椤撶喎鍔呴梺鏂ユ櫅閸熺増绂嶉崼鏇熲拻濞达綀娅ｇ敮娑㈡煙濮濆矈鍤欓悡銈嗕繆椤栨艾鎮戠€规洖寮剁换娑㈠箣濞嗗繒浠肩紓浣哄缁插墽鎹㈠┑瀣棃婵炴垶鐟Λ銉╂⒑缁洘娅囬柛瀣ㄥ€曢～蹇撁洪鍕炊闂佸憡娲熷褔宕滈銏♀拺缂佸灏呴弨鑽ょ磼鐠囪尙澧曟い鏇悼閹风姴顔忛鍏煎€梻浣规偠閸庮垶宕濆畝鍕嚑闁稿瞼鍋為埛鎴︽煕濞戞﹫鏀诲璺哄閺屾稑螣绾拌京鍔搁柛妤呬憾閺屾盯顢曢敐鍥╊吋濠电偞鎸搁…鐑藉蓟閺囥垹閱囨繝闈涚墕閸ゎ剛绱撴担闈涘妞ゎ厾鍏樺璇测槈閵忊€充簻婵＄偛顑呯€涒晠骞夐崗鑲╃闁挎繂鎳忛幖鎰版煥閺囥劋绨婚柣锝夋敱缁虹晫绮欓崹顔肩ギ闂備胶绮崝鏍敊閺嶎灛锝嗗鐎涙ǚ鎷绘繛鎾村焹閸嬫挻绻涙担鍐叉濞咃綁姊绘担渚劸闁哄牜鍓涢崚鎺戭吋婢跺娅栭棅顐㈡处缁嬫帡鍩涢幒妤佺厱閻忕偞宕樻竟姗€鏌嶈閸撴盯宕楀鈧獮鍐倷閻戞ɑ娅囬梺绋挎湰濮樸劑鎮惧ú顏呪拺闁告挻褰冩禍婵囩箾閸欏澧辩紒顔肩墛瀵板嫰骞囬鐐╁亾閸洘鐓熼柟鎵濞懷兠瑰鍛壕缂佺粯鐩畷銊╊敍濮橈絾鐎版俊銈囧Х閸嬬偤鎮уΔ鈧…鍥疀濞戞顦悷婊冪Ч瀹曞搫鐣濋崟顑芥嫼闂佺鍋愰崑娑欎繆閻ｅ瞼纾奸悹鍥ㄥ絻閺嗙喖鏌熼獮鍨仼闁宠棄顦垫慨鈧柣妯垮蔼閳ь剙鐏濋埞鎴﹀煡閸℃浠╅梺鍦拡閸嬪﹪鏁愰悙鑼殕闁逞屽墰濡叉劙骞樼€涙ê顎撶紓浣割儐椤戞瑩寮抽姀銈嗏拺缂佸顑欓崕宥夋煕婵犲啰绠撴い鏇稻缁绘繂顫濋鐐扮盎闂備胶顭堢换妤呭磻閹版澘绀夐柣鎴ｅГ閳锋垿鏌熺粙鍨劉缁惧墽鏁婚弻娑氣偓锝庡亝鐏忕増銇勯妸锝呭姦闁诡喗鐟ч埀顒傛暩椤牓鍩呰ぐ鎺撯拻闁搞儜灞锯枅闂佸搫鐭夌徊鍊熺亽闂佸壊鐓堥崰姘掗姀銏㈢＝濞达絽鎼瓭濡炪値鍘鹃崗妯侯嚕婵犳艾鐏崇€规洖娲﹀▓鏇㈡煟鎼搭垳绉甸柛鎾寸閹筋偊姊婚崒娆愮グ妞ゆ洘鐗犲畷褰掑础閻愬秵鐩畷姗€鍩￠埀顒傛崲閸℃稒鐓欓梻鍌氼嚟閸斿秹鏌￠崨顔剧煀闂囧鏌ｅΟ鐑樷枙闁稿孩鍔欓弻锟犲幢濮楀牐鈧寧鎱ㄦ繝鍌ょ吋鐎规洘甯掗埢搴ㄥ箳閹存繂鑵愬┑锛勫亼閸婃垿宕硅ぐ鎺撴櫇闁靛鏅涚粻鐐烘煏婵炵偓娅呴崶鎾⒑閹肩偛鍔€闁告劦浜欓崰濠囨⒒閸屾瑦绁版い顐㈩槸閻ｅ嘲顫滈埀顒勬晲閻愭潙绶為柟?"
                    "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛橆殽閻愯揪鑰块柟宕囧█椤㈡寰勭€ｆ挻绮撳缁樻媴鐟欏嫬浠╅梺鍛婃煥缁夊爼骞戦姀銈呯妞ゆ柨妲堥敃鍌涚厱闁哄洢鍔岄悘鐘绘煕閹般劌浜鹃梻鍌欑窔濞佳嗗櫣闂佸憡渚楅崹鎵暜閹烘鈷掗柛灞剧懅椤︼箓鏌熺喊鍗炰簻閾荤偞绻涢崱妯虹仴闁搞劍绻堥弻鐔煎箲閹伴潧娈梺钘夊暟閸犳牠寮婚妸銉㈡斀闁糕檧鏅滅瑧婵犵妲呴崑鍛存晝閵忋倕绠栫憸鐗堝笒缁犳帡鏌熼悜妯虹仴妞ゎ剙顦—鍐Χ閸℃鍙嗛梺缁橆殕閹告悂锝炶箛鎾佹椽顢旈崟顏嗙倞闂備礁鎲″ú鐔奉焽瑜斿畷婊堟焼瀹ュ棌鎷虹紓鍌欑劍閿曗晛鈻撻弴鐔翠簻闁靛鍎虫晶锔筋殽閻愭潙鐏村┑顔瑰亾闂佺粯锕╅崑鍛达綖瀹ュ鈷戦梻鍫熺〒缁犲啿鈹戦鎯у幋妞ゃ垺锕㈠畷顐﹀礋閵婏附鏉搁梻浣虹帛閸旀洖顕ｉ崼鏇€澶婎煥閸涱垳锛滅紓鍌欑劍閿氱紒妤佹皑缁辨帡宕掑☉妯昏癁闂佺娅曢悧鐘诲春閿熺姴绀冩い蹇撴捣闂傤垱绻濋悽闈涗哗闁规椿浜炲濠冪鐎ｎ亞顔愬銈嗗姧缁叉寧鏅堕敓鐘斥拻闁稿本鐟ㄩ崗宀€绱掗鍛仸闁靛棗鍟村畷鍗炩槈閺嶃倕浜鹃柛鎰靛枛楠炪垺绻涢崱妯虹仼闁绘挻妫冮弻鈩冨緞婵犲嫬顣堕梺鍛婃煥濞村嘲顕ｈ閸┾偓妞ゆ帒瀚埛鎴︽煙閼测晛浠滈柛鏃€鎸抽弻锝堢疀閺冨偆鐏卞銈忕畱缂嶅﹪寮婚敍鍕勃闁告挆鈧Σ鍫ユ⒑鐎圭姵顥夋い锕傛涧閻ｇ兘鏁撻悩鍐测偓鐑芥倵閻㈠憡娅滈梺顓у灠閳规垿鎮╅崹顐ｆ瘎闂佺顑嗛惄顖炵嵁韫囨稑绠ｉ柣妯兼暩椤︻垱绻涢幘鏉戠劰闁稿鎸婚〃銉╂倷閹绘帗娈柧缁樼墵閺屾稑鈽夐崡鐐寸亪婵炲濯崣鍐潖閾忓湱纾兼慨妤€妫欓悾鍫曟⒑缂佹﹩娈旀俊顐ｇ箓椤曪綁骞庨挊澶愬敹闂侀潧绻堥崹濠氭晬濠靛洨绠鹃弶鍫濆⒔閹ジ鏌ｉ埄鍐╊棃鐎规洟娼ч埢搴ㄥ箻鐎电骞堝┑鐘垫暩婵挳宕愯ぐ鎺戠；闁靛／鈧崑鎾舵喆閸曨剛顦ㄥ┑锛勫仒缁瑩鐛崘銊㈡瀻闁规儳鍘栫槐鍫曟⒑閸涘﹥澶勯柛娆忛叄瀹曘儵宕ㄧ€涙ǚ鎷绘繛杈剧悼閹虫捇顢氬鍕箚妞ゆ劧绱曢ˇ锕傛懚閻愮儤鐓曢柡鍥ュ妼婢х増銇勯埡鍕毢闁瑰弶鎮傞幃褔宕煎┑鍫㈡嚃闂備焦濞婇弨閬嶅垂閸ф钃熸繛鎴炃氬Σ鍫熸叏濡も偓閻楀棙鎱ㄥ☉銏♀拺闁荤喐婢橀弳閬嶆煕閻曚礁鐏﹀┑锛勬暬瀹曠喖顢涘☉娆愮彆闂佽崵濮村ú鈺冧焊濞嗘劗顩烽柍鍝勬噺閳锋垿鎮楅崷顓烆€岄柛銈嗙懅缁辨帗寰勭仦钘夊箣闁芥ɑ绻堥弻锛勪沪鐠囨彃濮曢梺缁樻尭閸熸挳骞冨畡鎵虫瀻闊洦鎼╂禒濂告⒑鐠囪尙绠查柟鍛婂▕瀵鈽夐姀鐘栤晠鏌嶉崫鍕殶闁哄棭鍋婇幃妤冩喆閸曨剛顦ㄩ梺鎸庢磸閸ㄤ粙鐛繝鍥ㄥ亹婵炶尙绮弲銏ゆ⒑閸涘﹥澶勯柛妯垮亹缁牓宕奸妷锔规嫽闂佺鏈懝楣冨焵椤掑倸鍘撮柟顔惧仱閺佸倿鏌ㄩ姘缂備焦顨嗙粙鎴﹀储閻愵兙鍋婇悹鎭掑妿閺夌鈹戦悙鏉戠仸闁挎岸鏌ｆ惔顔煎籍婵﹥妞介幊鐐哄Ψ閸愬彞閭挊婵喢归悩宸剰闁告艾缍婇弻锟犲炊閳轰椒姹楅梺琛″亾濞寸姴顑嗛悡鐔镐繆椤栨繃顏犻柨娑樼У閵囧嫰鏁愰崱娆忓绩闂佸搫鏈粙鎾诲焵椤掑﹦绉靛ù婊勭矒椤㈡棃顢橀姀锛勫幍濡炪倖姊圭€笛呮兜妤ｅ啯鐓冮柦妯侯樈濡偓濡ょ姷鍋炵敮鈥崇暦閸楃儐娓婚柟顖嗗本顥￠梻鍌氬€烽懗鍫曗€﹂崼銏″床闁圭増婢樼粻鐘诲箹濞ｎ剙澹傚璺侯煬濞尖晜銇勯幘璺盒ラ柣锕€鐗撳鍝勑ч崶褏浼堝┑鐐板尃閸曨収娴勯梺鎸庢礀閸婂綊鎮￠弴銏＄厪濠电偛鐏濋崝銈夋煕閳哄绋婚柕鍥у婵偓闁斥晛鍠氬Λ鍐渻閵堝啫鐏俊顐㈠暙閻ｉ攱绺介崜鍙夋櫇闂佹寧绻傚Λ娆撴偟閺囥垺鈷掗柛灞剧懅椤︼箑顭块悷甯含鐎规洘鍨垮畷鍗炩槈濡偐宕堕梺鐟板悑閻ｎ亪宕濆畝鍕€块柛顭戝亖娴滄粓鏌熼崫鍕棞濞存粓绠栧铏圭磼濡厧鈪归梺闈涚墢椤牓顢氶敐鍡欑瘈婵﹩鍎甸埡鍛厪濠㈣泛鐗嗛悘顏堟煛閸屾浜鹃梻鍌氬€烽懗鍓佹兜閸洖绀堟繝闈涱儐閺咁亞绱撻崒娆戝妽闁告梹鐗滅划娆撳箻閼告娼熼梺鍦劋椤ㄥ懐绮诲杈ㄥ枑鐎广儱顦悡鏇㈡煛閸愩劎澧涢柣鎾寸洴閺屾稑顭ㄩ埀顒傜矆娴ｅ湱顩插ù鐓庣摠閻撴洟鏌嶇憴鍕姢濞存粎鍋撴穱濠囨倷椤忓嫧鍋撻弽褜鍟呭┑鐘宠壘绾惧鏌熼幆褍顣崇痪鎯с偢閺岋絽螣閸喚姣㈤柡浣哥墦閹鎲撮崟顒傤槰濠电偠灏欓崰搴ㄦ偩閻戣姤鏅搁柣妯哄暱閳ь剟顥撻埀顒€绠嶉崕鍗炍涘☉妯忚櫣鈧稒锕╁▓浠嬫煟閹邦垱褰ч柤鐗堝閵囧嫰濮€閿涘嫭鍣伴梺鍦焾閿曘儱顕ラ崟顓涘亾閿濆骸澧繛鍫櫍濮婂宕掑▎鎰偘閻庤娲栭悘姘跺箞閵娾晛鍨傛い鎰╁€ゅú鍛婄箾鐎电孝妞ゆ垵鎳愮划鍫熷緞婵犲海鍞甸梺鍏兼倐濞佳勬叏閸モ晝妫柟顖嗗瞼鍚嬮梺鍝勭灱閸犳牠骞冨▎鎿冩晢濞达綀妗ㄧ槐姗€姊绘担鍛婃儓妞ゆ垵妫楄灋闁告劦鍠栭拑鐔哥箾閹存梹鍣伴柍褜鍓ㄧ粻鎾荤嵁鐎ｎ亖鏀介柛銉㈡櫃閹查箖姊婚崒娆愮グ妞ゆ泦鍛床闁硅揪绠戠粻鏌ユ煕閵夋垵鏈紞搴ㄦ⒑缂佹ê鐏﹂拑鍗炩攽椤旂晫鐭掗柡宀€鍠庨埢鎾诲垂椤旂晫褰繝纰樷偓铏枙闁哥姵鐗犻垾鏃堝礃椤斿槈褔骞栫划鍏夊亾瀹曞浂鍟囬梻鍌欑劍閹爼宕瑰ú顏呭亗闁跨喓濮寸粻鏍煙椤栧棗鎳忓▓婵嬫⒑閻熸澘鏆遍柨鏇樺劚椤啯绂掔€ｃ劉鍋撴笟鈧顕€宕煎┑鍫Ч婵＄偑鍊栭幐楣冨磻濞戞粠鏉烘繝鐢靛Х椤ｎ喚妲愰弴銏犵；闁硅揪绠戠壕褰掓煛瀹ュ骸浜濋柡鍡樼矊閳规垿鎮╅崣澶婎槱闂佹娊鏀卞濠氬焵椤掆偓缁犲秹宕曢崡鐐嶆稑鈽夐～顑藉亾閸涙潙鐭楀璺虹灱閻﹀牊绻濋悽闈浶㈤柛濠勭帛閺呰泛鈽夐姀锛勫幗闂佽鍎抽顓㈠箠閸ヮ剚鐓涢悘鐐插⒔閳藉鏌嶇憴鍕伌鐎规洖宕灃濠电姳鑳剁壕濠氭⒒娴ｅ憡鎲搁柛鐘冲姍楠炲啴宕掑鍏肩稁闂佹儳绻愬﹢閬嶆儗濞嗘挻鍋ｉ柟顓熷笒婵℃寧銇勯弬鎸庡枠婵﹤鎼叅閻犲洦褰冪粻褰掓⒑缁嬪尅宸ラ柣蹇旂箞椤㈡岸鏁愰崶銊ョ彴閻庣懓澹婇崰鏍箖閹达附鈷戦柟鑲╁仜閸旀鏌￠崨顔剧疄闁轰礁绉撮…銊╁礃閿濆棙鏉搁梻浣哥枃濡嫬螞濡ゅ懏鍊堕柨婵嗩槹閻撴洟骞栨潏鍓хɑ闁哄棭鍓氶〃銉╂倷閼碱剛顔夌紓浣虹帛缁诲倿锝炲┑瀣垫晣婵炴垶鐟ラ褰掓⒒閸屾艾鈧娆㈤敓鐘茬；闁糕剝绋戠壕缁樼箾閹存瑥鐏柛銈嗗姈閵囧嫰寮介妸褉濮囧┑鐐叉噽婵敻濡甸崟顖氭闁割煈鍠掗幐鍐磼閻愵剙鍔ら柕鍫熸倐瀵鏁愰崨鍌滃枛瀹曞綊顢欓悙顒夊殑闂備浇妗ㄧ粈渚€鎮ч幘璇茬畺婵°倕鍟崰鍡涙煕閺囥劌澧版い锔哄妼閳规垿鎮欑捄铏规闂佸摜濮撮柊锝夊箖妤ｅ啯鍊婚柤鎭掑劜濞呫垽姊虹紒妯忣亪宕崸妤€鐒垫い鎺嗗亾濠⒀冩捣濡叉劙骞樼€涙ê顎撻梺鍏肩ゴ閸撴繈宕归幐搴濈箚闂傚牊绋堥弨浠嬫倵閿濆骸浜為柛姗€娼ч—鍐Χ閸℃﹩姊垮銈庡亜椤︻垶鍩㈠澶婄倞妞ゆ帊鑳堕崢鍨繆閻愬樊鍎忓Δ鐘虫倐閸┿垽宕奸妷锔惧幍閻庤娲栧ú銈夊煝閸喆浜滈柕蹇婃濞堟粓鏌涢埞鎯т壕婵＄偑鍊栫敮濠囨倿閿曞倸鐭楅煫鍥ㄧ⊕閻撱儵鏌￠崘锝呬壕闂佹悶鍔嶇换鍕箲閵忋倕骞㈡繛鎴炵懅閸樹粙姊虹憴鍕凡闁告埃鍋撶紓浣靛妼椤兘寮诲鍫闂佸憡鎸诲畝鎼佸箖瑜嶉…銊╁醇濠靛洨鈧剙顪冮妶鍡樷拻闁哄拋鍋嗗褔鍩€椤掑嫭鈷戦柛娑橈攻婢跺嫰鏌涢幙鍕暤鐎规洘鍨挎俊鎼佸煛閸屾瀚奸梺鑽ゅУ娴滀粙宕濆畝鍕嚑闁哄倸绨遍弨鑺ャ亜閺冨倸浜鹃柡鍡╁墰閳ь剝顫夊ú姗€宕濆▎蹇曟殾鐟滅増甯╅弫濠冩叏濮楀棗澧扮紒澶嬫そ閺岀喖顢欑憴鍕彅濡炪倖鏌ㄧ换姗€銆佸▎鎾村亗閹肩补妲呭Λ濠囨⒒閸屾艾鈧兘鎳楅崜浣稿灊妞ゆ牜鍋涚粻浼存煙闂傚顦﹂柣銈庡枛闇夐柛蹇撳悑缂嶆垹绱掗悩闈涙灁缂佽鲸甯為埀顒婄秵閸嬫帡宕曢妷鈺傜厽闁规儳宕崝锕傛煛鐏炲墽娲存い銏℃礋閺佹劙宕堕埡鍐╂瘔濠碉紕鍋戦崐褏鈧潧鐭傚畷銏＄附缁嬭法鍘撮梺纭呮彧闂勫嫰宕戦幇顔剧＝濞达綀鍋傞幋锔界叆妞ゆ挾鍎愬〒濠氭煏閸繃顥滈柣蹇ョ畵閺屾盯濡搁妷锕佺濠碘€冲级閸旀瑩骞冨▎鎾充紶闁告洦鍋勯弫銈夋煟閻斿摜鐭嬬紒顔芥崌楠炲啴濮€閵堝懎鑰垮┑鐐村灦閻熴儲绂掗鐐寸厸濠㈣泛鑻禒锕€鈹戦娆戠煓妞ゃ垺顨婇幃銏ゅ礂閼测晛骞楅梻浣烘嚀閻忔繈宕锝嗘珷妞ゆ牗绮庣壕鑲╃磽娴ｈ鐒介柕鍡樺笒闇夋繝濠傚閸婃劗鈧鍠曠划娆愪繆閹间焦鏅滈柟顖嗗懐袪闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧€氬銇勯幒鍡椾壕闁绘挶鍊栨穱濠囶敍濮橆剚鍊悗瑙勬礀瀵墎鎹㈠☉銏犵婵炲棗绻掓禒濂告⒑閹肩偛濡奸柛濠傜秺婵＄敻宕熼姘辩潉闂佺鏈懝鐐濡警娓婚柕鍫濋娴滄粓姊虹敮顔惧埌妞ゎ偄绻掔槐鎺懳熺拠宸偓鎾绘⒑閸涘﹦鈽夐柨鏇樺劦瀹曟洟骞橀幇浣瑰瘜闂侀潧鐗嗗Λ妤呮倶閵夛缚绻嗘い鎰剁秵濞堟瑩鏌ｈ箛鎿冨剶婵﹥妞藉畷銊︾節閸屾鏇㈡⒑閸濄儱校闁绘濞€楠炲繘骞嬮敂钘変簻闂佺绻楅崑鎰板储娴犲鈷戦柛婵嗗閳ь剙婀遍埀顒傜懗閸パ呮焾闂佺粯鍔楅弫鍝ュ閻ｅ备鍋撻獮鍨姎闁瑰啿绻橀獮鏍箛閻楀牊鍤夐梺鍝勭▉閸樹粙鎮￠妷锔剧瘈闂傚牊绋掗ˉ鐐烘煕閿濆懐绉洪柡宀嬬節瀹曞崬鈻庤箛搴㈠媰闂備線娼уú銈団偓姘煎弮楠炲棝寮崼鐔告珫闂佸憡娲橀崵顏堝礋椤掆偓瀵寧绻濋悽闈浶㈤柟鍐茬箻椤㈡棃鎮╅悽鐢碉紲闁哄鐗勯崝宀€绮幒妤佹嚉闁挎繂顦伴悡锝夌叓閸ャ劍灏伴悹鎰剁節閺岀喎顔忛鑽ゆ晼缂備浇椴搁幑鍥х暦閹烘垟鏋庨柟杈剧悼閻涖儵姊绘担鍛婃喐濠殿喚鏁婚妴鍐╃節閸パ呯暫闂佺粯鍨煎Λ鍕偂濞戞ǜ鈧帒顫濋浣规倷濠电偛鐗勯崝宥囨崲濠靛鍋ㄩ梻鍫熷垁閿濆鐓犻柛锔诲幖娴滈箖鏌涙惔顔间喊婵﹦绮粭鐔煎焵椤掆偓椤洩顦归挊婵囥亜閹惧崬鐏╅柛銊ュ€圭换娑橆啅椤旇崵鐩庡┑鈽嗗亝閿曘垽寮诲鍫闂佸憡鎸鹃崰搴綖韫囨洜纾兼俊顖濐嚙椤庢捇姊洪幆褏绠扮紒鐘茬Ч閸┾偓妞ゆ巻鍋撻柨鏇ㄤ邯瀵鈽夐姀鐘殿啋闁诲酣娼ч幗婊堟偪閸曨垱鈷戦梻鍫熺⊕椤ユ粓鏌涢悢椋庯紞缂侇喛顕ч埥澶愬閻樻剚妫熸繝鐢靛仜濡瑩宕曢崘娴嬫灁濠靛倸鎲￠埛鎺戙€掑锝呬壕闂侀€炲苯澧伴柛瀣洴閹崇喖顢涘☉娆愮彿濡炪倖鐗楅褎鎯旈妸銉у€為悷婊勭箞閻擃剟顢楅崟顒傚幍濡炪倖姊婚弲顐﹀箠閸ャ劊浜滈柕蹇婂墲椤ュ牏鈧娲滈崰鏍ㄤ繆閹间礁唯闁靛牆鎷嬪Λ婊堟⒒閸屾瑧顦﹂柟纰卞亜鐓ら柕濠忛檮閸欏繘姊婚崼鐔恒€掗柡鍡畵閺岋紕浠︾拠鎻掑闂佺粯鎸婚悷鈺侇潖濞差亶鏁囬柕濞у懏娈稿┑鐘媰閸屾艾绁梺鍝勭焿缁绘繂鐣烽柆宥庢晣闁靛繆妲呴埀顒€绉瑰娲濞戞瑦鎮欓柣搴㈢煯閸楁娊鎮伴鈧獮鎺懳旈埀顒傜不閿濆棛绡€闁割煈鍋勬慨鍐煙椤曞棛绉慨濠勭帛閹峰懘鎼归悷鎵偧闂備胶鎳撻幉锟犲箰閹惰棄鏄ラ柍褜鍓氶妵鍕箳瀹ュ浂妲繝鈷€灞界仸闁哄矉缍佸顒勫箰鎼搭喗锛嗛梻浣告惈鐞氼偊宕愬┑瀣祦闁哄秲鍔嶆刊鎾偡濞嗗繐顏柡渚囦簻閳规垿鎮╅幇浣告櫛闂佸摜濮甸悧鏇犲弲闂侀潧臎閸曞灚缍楅梻浣告贡閸庛倝銆冮崱娑樼；闁规壆澧楅崐鍫曟煟閹邦厼绲婚柍褜鍓欓幉锛勭矉閹烘鏁嬮柍褜鍓欓～蹇撁洪鍕炊闂佸憡娲﹂崜姘跺箯闁秵鈷戦柣鎴旀櫆濞呮捇鏌涢妸銉у煟闁诡喕鍗抽、姘跺焵椤掆偓閻ｇ兘宕奸弴鐐靛幐闂侀€炲苯澧柍璁崇矙椤㈡棃宕奸悢鍝勫箻闂備浇顕栭崢鐣屾暜閹烘绀夋慨姗嗗幘缁犻箖鏌涘☉妯绘悙闁哥喓濞€瀵劍绂掔€ｎ偆鍘介梺褰掑亰閸撴岸鍩㈤弴鐔剁箚闁圭粯甯楅崯鐐电磼缂佹銆掑ù婊勬倐瀵粙濡堕崨顒€顥氶梻浣哥秺椤ｏ箓鎮為敂鍓х閹艰揪绲跨壕浠嬫煕鐏炲墽鎳呴柛鏂跨Ч閹锋垿宕￠悙鈺傛杸濡炪倖鐗楃粙鎺斾焊閿曞倹鐓欐い鏃傚帶濡插鏌嶇拠鍙夊攭缂佺姵鐩獮娆撳礃瑜庨崑鍛節閻㈤潧浠滄い鏇ㄥ幗閹便劑顢橀姀鐘垫煣闂佺粯锚濡﹤顭囬弽銊х鐎瑰壊鍠曠花鑽も偓鐟版啞缁诲倿鍩為幋锔藉亹闁圭粯甯楀▓鍫曟⒑閸涘﹦鎳冩俊顐ｎ殜閳ユ棃宕橀鍢壯囨煕閳╁喚娈樺ù鐘虫綑閳规垿鎮欓崣澶嗘灆闂佸憡锚閵堟悂骞冮幆褏鏆嬮梺顓ㄩ檮閸嶇敻鏌ｉ悩鑽ょ窗婵炲拑缍侀、娆愮節閸ャ劉鎷洪梺鑽ゅ枑婢瑰棝骞楅悩铏弿濠电姴鍊荤粔娲煙椤旂瓔娈曠紒缁樼箓椤繈顢樿椤ュ﹥淇婇悙顏勨偓鏍礉閹达箑鍨傞柧蹇撴贡閻牊銇勯幇鈺佲偓妤冨婵傚憡鐓犻柤瑙勬緲閻撴劖銇勯妷銉█闁哄苯绉剁槐鎺懳熺拠鑼紦濠电姷顣介崜婵嬪箖閸屾稐绻嗛柣鎴犵摂閺佸﹪鏌﹀Ο渚Ш婵¤缍佸濠氬磼濞嗘垹鐛㈠┑鐐板尃閸ャ劌浜遍梺绯曞墲閵囧倸鈽夊Ο婊勬瀹曟﹢顢旈崱娆愭闂傚倷绀佸﹢閬嶅磿閵堝鈧啴宕卞☉妯硷紮闂佸壊鐓堥崑鍛村矗韫囨柧绻嗘い鏍ㄧ閹牓鏌ょ粙璺ㄧШ闁哄本绋戣灒濞撴凹鍨板▓鍫曟⒑闁偛鑻晶顖涖亜閺冣偓閻楃姴鐣烽幎绛嬫晪闁逞屽墮閻ｇ兘骞嬮悙鐢电槇闂佺鏈划宥呪枔妤ｅ啯鈷戦柛鎾村絻娴滄繃绻涚拠褏鐣电€殿噮鍋婂畷鍗烆渻閺囩偟绉洪柡浣瑰姍瀹曘劑顢欓挊澶婂濠德板€楁慨鐑藉磻閻愭亽鈧啴宕卞▎鎰簥濠电娀娼ч悧鍡涘几閸喍绻嗘い鏍ㄧ⊕閵囩喐绻涢崗鐓庣伌婵﹥妞介獮鏍倷閹绘帩鐎遍梻浣告啞椤ㄥ棙绻涙繝鍥╁祦闁告劑鍓悢鐑樺仒闁斥晛鍟弶鎼佹⒒娴ｇ顥忛柛瀣瀹曟娊濡烽妷顔惧姺闂佺粯鏌ㄩ崥瀣煕閹达附鐓欑紒瀣仢椤掋垻绱掗埀顒勫焵椤掑嫭鈷戠紒瀣皡瀹搞儳绱撳鍜冭含妤犵偛鍟撮弫鎾绘偐閹绘帒绁梻渚€娼ф蹇曟閺囥垹鍌ㄩ柟闂寸劍閸婂灚顨ラ悙鑼虎闁告梹宀搁弻娑㈡偆娴ｉ晲绨兼繛锝呮搐閿曨亜鐣疯ぐ鎺濇晪闁告侗鍨伴弫鎼佹煟閻斿摜鐭婄紒澶婄秺楠炲啫螣娓氼垱鍍甸柣鐘荤細濞咃綁鎮块崟顖涒拺闂傚牊渚楅悡顓炩攽閳ヨ櫕宸濈€殿啫鍥х劦妞ゆ帒瀚埛鎴︽煕濞戞﹫宸ュ┑顔瑰亾闂備礁鎼崐鎼佸磹閸︻厾鐭夐柟鐑橆殔椤懘鏌ｅΟ鑽ゅ婵☆偄鍟撮獮鍐煛閸涱噮妫冨┑鐐村灦椤ㄥ棝宕熼崘顔解拻濞达絽鎲￠崯鐐存叏婵犲倻绉洪柟顔ㄥ洦鍋愰柤濮愬€曠粊锕傛⒑缁洖澧茬紒瀣灩閻氭儳顓兼径瀣幈濡炪倖鍔戦崐鏇㈠几閹寸偟绠鹃柛娑卞枤閻帗鎱ㄦ繝鍛仩缂侇喗鐟╅獮鎰償閵忊€愁伆婵犵數鍋為幐鑽ゅ枈瀹ュ鈧啴宕ㄧ划鍏夊亾閿曞倸鐐婃い鎺嗗亾缂侇偄绉归弻娑㈩敃閵堝懏姣愰梺鐟板槻椤嘲顫忛搹鍦煓闁圭瀛╅幏閬嶆⒑閼姐倕鏆€闁搞儰绀佸ú顓㈠极閸愵喖纾兼繛鎴炶壘楠炲秶绱撴担鍝勪壕婵犮垺锚閻ｇ兘顢楁担渚锤婵炲鍘ч悺銊╂偂濞嗘劑浜滈柡鍌濐嚙婵″ジ鏌涢悩鍐插摵闁诡噯绻濇俊鐑藉煛閸屾粌骞堟俊鐐€栭崝褏寰婄捄銊т笉婵☆垱鐪规禍婊堟煥閺冨浂鍤欑€殿噮鍠楅幈銊︾節閸涱噮浠╃紓浣介哺鐢帟鐏掑┑鐐跺皺缁垶藟閸喍绻嗛柣鎰典簻閳ь剚鍨垮畷鏇㈠蓟閵夈儳顔夐梺鎼炲劀鐏炶姤顓块梻浣筋潐閸庡吋鎱ㄩ妶澶婄柧婵犻潧顑嗛悡鏇㈡倶閻愭彃鈷旈柕鍡樺浮閺屾稑螣閸︻厾鐓撳┑顔硷龚濞咃絿妲愰幒鎳崇喖鎮滈埡鍌氼伜闂傚倷绀侀幉锟犫€﹂崱娑樼妞ゆ挆鍕暅婵犵數鍋涢顓㈠储瑜旈幃娲Ω閳哄倸浜楅梺缁樻煥閸氬鎮″▎鎾寸厵妞ゆ牕妫楅崯鎶藉春閻愮儤鈷戦柛娑橈攻椤ユ牜绱掗悩铏磳鐎殿喖顭烽弫宥夊礋椤忓懎濯伴梻浣告啞閹稿棝宕熼銏画闂備浇顕х€涒晠顢欓弽顓炵獥婵°倕鎳庣粻浼存煣韫囷絽浜楃紒璇叉閺岀喖姊荤€靛壊妲柛鐑嗗灦濮婃椽妫冨☉杈ㄐら梺绋垮濡炶棄鐣峰┑瀣劦妞ゆ帊鑳剁弧鈧梺姹囧灲濞佳冩毄闂備浇妗ㄩ悞锕傚箖閸屾氨鏆﹂柟杈鹃檮閸婇鈧懓澹婇崰姘跺礉瀹勬壋鏀介柣鎰级椤ョ偤鏌涢妸褍鏋涚€规洘鍨块獮姗€骞囨担鐟板厞闂備胶绮幐鍛婎殽閹间礁鐓曢悗锝庡枟閳锋垿鏌ｉ幇顖涱棄闁告梹绮嶆穱濠囶敃閵忕姵娈梺浼欑到閸㈡煡锝炲鍫濈劦妞ゆ帒瀚ㄩ埀顑跨閳诲酣骞橀崘鑼搸濠电姰鍨奸鏍垂閺夋５娲晝閸屾稑浜楅梺鍝勬储閸ㄦ椽鎮￠崘顔界厓閺夌偞澹嗛ˇ锕傛煛鐎ｃ劌鈧牜鎹㈠☉銏犻唶闁绘洖鍊介埀顒€娼￠弻鈥崇暆鐎ｎ剛袦闂佽鍠撻崹鑽ゅ垝濞嗘挸鍨傛い鏇炴噺缂嶅秶绱撻崒姘偓宄懊归崶銊ｄ粓闁归棿绀佺粻鏉库攽閻樺疇澹樼紒鐙€鍨堕弻娑樷槈濞嗘劗绋囩紓浣哄Х閺佸寮婚悢鐓庝紶闁告洦鍘滈姀掳浜滈柕澶涘椤ｈ尙绱掔紒妯肩疄闁诡喕绮欏Λ鍐ㄢ槈濡も偓閹藉姊绘担绛嬫綈婵＄偞瀵х粋宥夋倷瀹割喖娈繝鐢靛Т濞层倝鏌ㄩ妶鍡曠箚闁靛牆鍊告禍鍓х磽娴ｅ搫啸濠电偐鍋撻梺鍝勭灱閸犳牠鐛幋锕€绠涢梻鍫熺⊕椤斿嫮绱撻崒娆掝唹闁稿鎸搁…鍧楁嚋闂堟稑顫嶉梺缁樻尰閻╊垶寮诲☉銏犵疀闁宠桨绀侀‖瀣節閳封偓閸曨厽鍒涢梺鍝勮嫰缁夊綊寮婚妸褉鍋撻敐搴濈敖闁荤喆鍔戝濠氬炊瑜滃Ο鈧梺鍝勮閸斿矂鍩為幋锕€骞㈡俊顖濇閻涒晠姊绘担渚敯婵☆偄瀚板畷鎰板锤濡も偓閽冪喐绻涢幋娆忕仼閸ユ挳姊虹化鏇炲⒉闁荤噦绠撳畷鎶筋敇閻樼數锛濇繛杈剧秬濞咃絿鏁☉姘辩＜閻庯綆鍋呭畷宀勬煕閳规儳浜炬俊鐐€栫敮鎺楀磹瑜版帒姹查柍鍝勫€舵禍婊勩亜閹捐泛浠у褝濡囬埀顒冾潐濞插繘宕规繝姘劦妞ゆ帊鑳堕埊鏇㈡煥閺囨娅呴柍缁樻尰缁傛帞鈧綆鍋嗛崢浠嬫⒑瑜版帒浜伴柛銊ャ偢瀹曠數鈧綆鍠楅ˉ濠冦亜閹烘埈妲稿褜鍨遍妵鍕Ω閿濆懎濮﹂梺璇″枟閻熲晠鐛弽顓ф晣闁绘ɑ褰冩闂傚倸鍊风粈浣虹礊婵犲泚澶愬箻鐎靛摜顔曢梺閫炲苯澧撮柡宀€鍠庨悾鐑藉炊瑜夐弸鍛渻閵堝啫鐏い銊ユ楠炲繘宕ㄩ弶鎴滅炊闂佸憡娲﹂崐锝夘敂閸曘劍鏂€闂佺粯蓱椤旀牠寮冲鍛＜閺夊牄鍔嶇粈瀣偓瑙勬礃閸ㄥ潡鐛€ｎ喗鏅濋柍褜鍓涙竟鏇°亹閹烘挾鍘搁悗骞垮劚妤犳悂鐛弽顐ょ＜闁逞屽墯瀵板嫰骞囬鐘插箥闂佸搫顦悧鍡樻櫠娴犲鍋╅弶鍫氭櫇濡垶鏌熼鍡楁噽妤旈梻浣告惈婢跺洭鍩€椤掍礁澧柛姘儔楠炴牜鍒掗崗澶婁壕鐎规洖娴傞崯鍥р攽閻樻剚鍟忛柛鐘冲哺楠炲﹪骞橀幇浣告闂佸憡鎸烽悞锕€鐣烽崣澶岀瘈闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆牊顏犻悽顖涚洴閺岀喎顫㈠畝濠傛闁绘挶鍊濋弻锝夊籍閸屾艾浠橀梺钘夊暟閸犳牠寮婚敓鐘茬倞闁宠桨鐒﹂悗鑽ょ磽娴ｇ顣抽柛瀣ㄥ€濆璇测槈閵忊晜鏅濋梺鎸庣箓濞层劑鎮鹃崗鑲╃閻庣數顭堟牎闂佺瀛╂繛濠囧春閻愬搫绠ｉ柨鏃囨閳ь剛鍏橀弻娑樷枎韫囷絾笑濠电偛鎷戠徊浠嬪煘閹达附鍊烽柤纰卞墯閸曢箖姊洪崨濠冣拹闁搞劌娼￠悰顕€宕卞☉妯煎姦濡炪倖甯婇梽宥嗙濠婂牏鍙撻柛銉ｅ妽鐏忛潧顭胯濞茬喖寮婚敐澶樻晣闁绘洑鐒﹂悿渚€姊洪崫鍕拱婵炲弶顭囩划鈺呮偄绾拌鲸鏅┑顔斤供閸樼厧鈻嶈濮婃椽宕ㄦ繝蹇庣返闂佹悶鍔忓▔娑綖韫囨洜纾兼俊顖濐嚙椤庢捇姊洪崨濠勨槈闁挎洏鍎靛畷鏇㈠箻缂佹ǚ鎷洪梺绋跨箰閸氬濡甸悢鍏肩厱闁靛鍎抽敍宥夋煕閹烘挸娴€殿噮鍣ｅ畷濂告偄閾氬倻鏁鹃梻鍌欐祰椤顢欓弽顓炵獥婵°倐鍋撻柍缁樻崌楠炲棜顧佹繛鎾愁煼閺屾洟宕煎┑鍥舵婵犳鍟崨顖滐紲闂佺粯锚閸熷潡鎮橀埡鍐＜妞ゆ棁鍋愭晶銏ゆ煃瑜滈崜銊х礊閸℃稑纾诲ù锝呮贡椤╁弶绻濇繝鍌滃闁绘挻鐟╁娲敇閵娧呮殸闂佸搫顑嗛惄顖炲蓟閿涘嫧鍋撻敐搴濋偗妞ゅ孩顨婂Λ浣瑰緞鐎ｎ剛鐦堟繝鐢靛Т閸婄粯鏅堕姀銈嗙厽闁挎繂妫欓妵婵嬫煛鐏炵硶鍋撳畷鍥ㄦ畷闂侀€炲苯澧寸€规洑鍗冲鍊燁檨婵炲吋鐗犻弻銈嗘叏閹邦兘鍋撻幇鏉跨；闁瑰墽绮崑銊︾箾閸絾纭堕柛鏂挎啞缁绘繄鍠婂Ο宄颁壕闁肩⒈鍓涢悡鎾斥攽椤旂》榫氭繛鍜冪悼閸掓帒鈻庨幘宕囶槺闂佺偨鍎遍崢鏍閿濆鈷掑ù锝堟鐢盯鏌ｅΔ浣圭濠碘€冲缁瑥鈻庨幆褎顓块梺鑽ゅТ濞诧妇绮婇弶鎳筹綁宕奸妷锔惧帾闂婎偄娲﹀ú鏍綖瀹ュ鐓忓┑鐐靛亾濞呭棝鏌ｉ幘瀵告噰闁诡喗顨呴埥澶娾枍閾忣偄鐏撮柟顕嗙節婵＄兘濡烽崘顏呭殌妞ゎ厹鍔戝畷鐔碱敃閵忕姌鎴︽⒒娴ｅ摜鏋冩い顐㈩樀瀹曞綊宕稿Δ鈧弰銉╂煕閺囥劌鐏犵紒鈧崘顔界厪濠电倯鍐╁櫡闁稿绻濆濠氬磼濞嗘帒鍘＄紓渚囧櫘閸ㄥ爼濡撮崘顔煎耿婵炴垶顭囬澶愭⒑閹肩偛鍔€閻忕偠濮ら鍨攽閻樺灚鏆╁┑顔炬暩閸犲﹤顓兼径濠勶紱闂佸憡娲﹂崹閬嶆偂閿濆鍙撻柛銉ｅ妽鐏忎即鎮归幇鍓佺瘈闁哄被鍔岄埥澶娾枎閹寸姷鍘滄繝娈垮枛閿曘儱顪冮挊澹╂盯宕橀妸銏☆潔濠殿喗锕㈢涵鎼佸船閸濆嫧鏀介柣妯诲墯閸熷繘鏌涢敐蹇曠М鐎殿喓鍔嶅蹇涘煛閸愵亞鍔归梻浣告贡閸庛倝銆冮崨瀛樺亗婵炴垯鍨洪悡鏇㈡倶閻愭彃鈷旈柣顓炴湰閵囧嫰寮埀顒€煤閻旂厧钃熼柨婵嗘閸庣喖鏌曡箛濠冨櫚濠殿喖娲ら—鍐Χ鎼粹€崇濠电偛妯婇崣鍐嵁閸℃瑤娌柣锝呮湰濞堟洟姊洪崨濠冨闁告挻鐩畷銏ゆ焼瀹ュ棛鍘介柟鍏兼儗閸ㄥ磭绮旈悽鍛婄厱閻庯綆浜濋崳钘壝瑰鍕€愰柟顔荤矙瀹曘劍绻濋崟顐㈢濠德板€楁慨鐑藉磻濞戙垺鍊舵繝闈涱儐閸婂爼鏌嶉崫鍕櫤闁绘挸鍟撮弻锕€螣娓氼垱鈻撳┑鈽嗗灙閸嬫挸鈹戦悩鎰佸晱闁哥姵甯″畷鎴﹀箻缂佹ǚ鎷虹紓鍌欑劍閵嗙偤骞嬮敂缁樻櫓闂佸搫绋侀崢鑲╂喆閿曞倹鐓曟繛鎴烆焽閹界娀鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡欏妞ゅ繒濞€閹粙顢涘☉姘垱闂佸搫鏈惄顖氼嚕椤曗偓閸┾偓妞ゆ巻鍋撻悡銈夋煟閺冨倸甯剁紒鐘崇墬缁绘稑顔忛鑽ょ泿闁诡垳鍠栧铏光偓鍦У閵嗗啴鏌ら崘鑼煟闁轰礁绉归幃銏ゅ礂閼测晛骞嶉梻浣侯焾缁绘宕戦幇鏉挎辈婵せ鍋撻柡灞剧洴婵℃悂濡搁妷銉﹀劒缂傚倷绶￠崰姘卞垝椤栫偛围闁挎繂顦粈鍐煃鏉炴媽顔夐柛瀣崌瀹曞綊顢曢妶鍥跺晭闂備胶鎳撻顓㈠磻閻旂厧绠犻柟鎵閻撶喖鏌熼崫鍕ら柣顓熺懇閺屸€崇暆鐎ｎ剛袦濡炪們鍨洪敃銏ゅ箖濠婂牆骞㈡俊銈傚亾濠㈢懓顑囩槐鎾诲磼濞嗘劗銈版俊鐐存綑閹芥粓寮鈧幃娆撳传閸曨収鍞甸梻浣虹帛椤牓顢氳缁鎮介崨濠勫幍闂佸憡绻傜€氼參藟濠婂厾鐟邦煥閸垻鏆梺鍝勭灱閸犳挾鍒掑▎鎴炲磯闁靛鍎卞В鍫㈢磽閸屾瑦绁版い鏇嗗吘娑樷攽鐎ｎ亣鎽曢梺缁樻濞咃絿澹曟總鍛婄厪闊洦娲栨牎闂佽绻愰悧蹇曟閹惧瓨濯撮柛婵嗗珔椤掍胶绠鹃柛娑卞枟缁€鍐磼瀹€鍐摵缂佺粯绻堝畷鍫曗€栭顒€娲﹂悡鏇㈡倶閻愭彃鈷旈柣鎿冨灠椤法鎲撮崟顒傤槶缂備浇椴搁幑鍥х暦閹烘垟鏋庨柟鐑樼箓閺佸ジ姊绘担渚劸妞ゆ垵妫濋獮鎴﹀炊椤掆偓閽冪喐绻涢幋娆忕労闁轰礁鍟撮弻銊モ攽閸℃鈹涚紓浣歌嫰濞硷繝骞冨畡閭︾叆闁告侗鍙庨弳顓㈡煟閵忊晛鐏℃い銊ワ工椤曪綁寮婚妷銉ь唽闂佸湱鍎ょ换鍕船閻㈠憡鈷戦柣鎾冲閹叉悂鏌ｈ箛鏃傛噰妤犵偛顑勭紞鍛熆閼搁潧濮囬柛鎰ㄥ亾婵＄偑鍊栭幐楣冨疮閸ф绠繛宸簼閳锋垿鏌涘☉姗堝姛闁宠棄顦甸弻銊╁即濡搫濮㈡繛瀛樼矋閹倿銆侀弮鍫濋唶闁绘柨鎼獮鍫ユ⒒娴ｅ憡鎯堥柛鐔哄█瀹曟垿骞樼紒妯煎幈闂侀潧顭堥崐妤冪矈閻戣姤鐓熼煫鍥ㄦ惄閸庢梹鎱ㄦ繝鍐┿仢鐎规洏鍔嶇换婵嬪礋閵娿儺娼撻梻鍌欐祰椤曟牠宕规导瀛樺剹闁稿本鍑归崵鏇熴亜閹板墎鐣辩紒鈧崘鈹夸簻闁哄啫鍊瑰▍鏇㈡煕濮楀棔閭俊顐㈡嚇椤㈡洟濮€閳╁啯鍊烽梺鑲╂嚀閻倿寮诲☉姘ｅ亾閿濆骸浜濈€规洖鏈〃銉╂倷閸欏顦╅梺鐟板槻閹虫ê鐣峰鍫濈疀妞ゆ柨鍚嬮悘鍫濃攽椤旂》宸ユい顓炲槻閻ｇ兘骞掗幋鏃€鐎婚梺瑙勬儗閸樺€熲叺婵犵數濮烽弫鍛婃叏椤撱垹纾婚柟鍓х帛閳锋垶銇勯幒鍡椾壕缂備礁顦介崳锝夊春閳ь剚銇勯幒鎴姛闁伙絿鏁搁埀顒冾潐濞叉牠濡堕崨濠佺箚闁绘垼妫勫敮閻熸粍绮撳畷顖炲醇閻旇櫣鐦堥梺姹囧灲濞佳冪摥闂備焦瀵уú蹇涘磹濠靛绠栫憸鏂跨暦閸楃偐鏋庨柟瀛樼矌閻熸繃淇婇悙顏勨偓鏍偋濠婂牆纾婚柣鎰惈绾惧綊鏌ｉ姀鐘冲暈闁绘挶鍎茬换婵嬫濞戞瑯妫﹀銈呭椤ㄥ﹪寮婚敍鍕ㄥ亾閿濆骸浜為柕鍡樺笧缁辨帗娼忛妸銉﹁癁闂佽鍠掗弲鐘茬暦瑜版帩鏁冮柨婵嗘濡叉姊婚崒娆戭槮闁圭⒈鍋婇幆澶嬬附缁嬭法鐛ラ梺鍝勭▉閸樹粙宕戝Ο姹囦簻闁哄洦顨呮禍楣冩倵鐟欏嫭绀€缂傚秴锕妴浣糕枎閹存繃鐎抽柡澶婄墐閺備線宕戦幘鍨涘亾濞戞瑯鐒界紒鈾€鍋撶紓浣稿⒔婢ф鎽銈庡亜閿曨亪寮诲☉姘ｅ亾閿濆簼绨绘い蹇ｅ幘閳ь剝顫夊ú锕傚垂閸洜宓佹慨妞诲亾妞ゃ垺鐟╅獮鍡氼槾闁靛牞绠撳缁樻媴閸涘﹤鏆堥梺鍛婃缁犳挸鐣锋导鏉戝唨妞ゆ挾鍠庢禍妤€鈹戦悙鏉戠仧闁搞劍妞介幃锟犲即閻旇櫣顔曢梺鐟扮摠缁诲倿鎳滆ぐ鎺撶厸閻庯綆鍋嗛埊鏇犵磼缂佹娲寸€规洜鍘ч埥澶娢熷畡棰佸闂佸搫娲犻幊鍥焵椤掍焦顥堢€规洘锕㈤、娆撳床婢诡垰娲﹂悡鏇㈡煃閳轰礁鏋ゆ繛鍫燂耿閺岋綁鎮㈤弶鎴濐潎濠殿喖锕ㄥ▍锝囧垝濞嗘挸绀岄柍銉ュ帠缁憋綁姊绘担渚敯妞ゆ洘绮庨幑銏犫攽鐎ｎ剙绁﹂梺鍓插亖閸庤鲸鍎梻浣瑰濞插秹宕戦幘娣簻闁哄浂婢€閹查箖鏌熼绛嬫當闁宠棄顦埢宥嗘綇閵娿儱鎽靛Δ鐘靛仜缁绘帞妲愰幒鎳崇喖鎳栭埡濠傛櫗闂備礁鎼ˇ顖炴偋閸℃ɑ娅犻柣锝呯灱閻挻銇勯弬娆炬綗濞存粍绮撻弻鏇熷緞濞戙垺顎嶉柣蹇撶箲婢瑰棛妲愰幒鏂哄亾閿濆簼鎲炬俊顖楀亾闂備胶鎳撶壕顓熺箾閳ь剚銇勯姀鈽嗘疁鐎规洘甯掗…銊╁箛椤旇偐鍝庨梻鍌氬€搁崐鐑芥嚄閸撲礁鍨濇い鏍仦閺咁亪姊绘担鍛婃喐闁哥姴楠搁…鍥晸閻樿尙鐣哄┑顔姐仜閸嬫挻顨ラ悙杈捐€挎い銏＄懇閹稿﹥寰勭仦缁⑩偓宥呪攽閻樺灚鏆╁┑鐐╁亾濠电偘鍖犻崶鑸垫櫈闂佺硶鍓濈粙鎴︽偂閺囥垺鐓欓柣鎴烇供濞堟洟鏌ｉ幘瀛樼闁靛洤瀚伴獮鍥煛娴ｆ彃浜鹃柡鍥ュ灩閸戠娀鏌￠崘銊у闁绘挸绻橀弻娑㈠焺閸忕媭浜滈湁妞ゆ洍鍋撻柡灞糕偓宕囨殕閻庯綆鍓涢惁鍫ユ倵鐟欏嫭绀嬪ù婊冪埣閵嗕礁顫滈埀顒佹叏閳ь剟鏌嶉挊澶嬵棏闁稿鎸搁濂稿炊閳哄喛绱冲┑鐐舵彧缂嶁偓婵炲拑绲块弫顔尖槈濮樿京锛滈柣鐘叉穿鐏忔瑦鏅堕弴銏℃嚉闁绘劗鍎ら悡鏇㈡煙閹佃櫕娅呭┑锟犳敱娣囧﹪骞撻幒鏂库叺闂佸搫鏈粙鎴ｇ亙闂佸憡鍔戦崝瀣垝閼哥數绡€闁靛繈鍨洪崵鈧梺缁橆殕閹告悂锝炶箛娑欐優閻熸瑥瀚悵浼存⒑閻愯棄鍔氱痪缁㈠幗缁傛帡顢涢悙绮规嫼闂佸憡绺块崕杈ㄧ墡闂備胶绮〃鍡椕洪悢鍏兼櫜闁绘劕澧庨悿鈧梺鐟板綖閻掞箑顪冩禒瀣ㄢ偓渚€寮崼婵囥仢婵炶揪缍€椤曟牕螞閸愩劉鏀介柣妯虹仛閺嗏晠鏌涚€ｎ剙浠辩€规洖缍婂畷濂稿即閻旈攱鐤勫┑掳鍊х徊浠嬪疮閵娾晛鐒垫い鎺嗗亾闁稿﹤鐏濋悾鐑筋敃閿曗偓缁€瀣煏婵犲繘妾柡澶嬫倐濮婄粯鎷呴搹鐟扮闂佸憡姊归…鍥ㄧ缁嬪簱鏋庨煫鍥ュ劥閳ь剙娼￠弻鐔虹磼閵忕姵鐏嶉梺缁樻尰濞茬喖寮婚敓鐘茬闁挎繂鎳嶆竟鏇㈡⒒娴ｈ鍋犻柛鏂跨焸閹ê鈹戠€ｎ偄浠奸悗鐟板閸ｆ潙煤椤忓秵鏅滈梺鍛婃礀閻忔氨绱為崒鐐粹拻濞撴埃鍋撴繛浣冲洦鍋嬮柛鈩冪☉缁犵娀骞栨潏鍓х？闁哄棎鍊濋弻娑㈠焺閸愵亖濮囬梺鎶芥敱閸ㄥ灝顫忔繝姘唶闁绘梹浜介埀顒佸笧缁辨帡鎮╁畷鍥舵殹婵烇絽娲ら敃顏堝箖椤忓嫧鏋庨煫鍥ㄦ⒐閹瑧绱?"
                )
            return "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棗鏆欏┑鈥炽偢閺屽秷顧侀柛鎾存皑閹广垽宕煎┑鎰婵犵數濮甸懝楣冨础閹惰姤鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú鐔奉潖閾忓湱纾兼俊顖氭惈琚濋梻浣告啞閹歌鐣濋幖浣哥畺闁汇垻顭堢猾宥夋煕椤愩倕鏆遍柟閿嬫そ濮婅櫣娑甸崨顓濇睏闂佺顑嗙粙鎺撶┍婵犲啰闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛濠傜秺瀹曟垿濡疯閸嬫挸鈻撻崹顔界亪濡炪値鍙冮弨杈ㄧ┍婵犲洤閱囬柡鍥╁仩琚濋梻渚€娼ч悧鍡涘箠韫囨洘瀚婚柨鐔哄У閻撳啰鎲稿鍫濈闁靛ě鍛槸闂佺硶鍓濈粙鎴犲婵犳碍鐓曟繛鎴烆焽閹界娀鏌涚€ｎ剙鏋涢柡宀嬬節瀹曞爼濡烽妷褌鐥梻浣侯焾閿曪箓寮繝姘畺鐎瑰嫭澹嬮弸搴ㄧ叓閸ャ劍鎯勫ù鐘插⒔缁辨挻鎷呴幓鎺嶅闂備礁鎲￠崝锕傚窗濡ゅ懏鍋傞柣鏂垮悑閻撴瑩鏌涢…鎴濇灈妞ゅ浚鍋嗙槐鎺楀煢閳ь剟宕戦幘缁樼厽閹兼番鍩勯崯蹇涙煕閻樺磭澧甸柍銉畵閹粓鎸婃径瀣偓顒勬⒑閻熸澘鈷旂紒顕呭灦瀹曟垿骞囬悧鍫㈠幘缂佺偓婢樺畷顒佹櫠椤曗偓閺屽秷顧侀柛鎾寸洴瀹曟垿濡堕崪浣圭稁濠电偛妯婃禍婵嬎夐崼鐔虹闁硅揪缍侀崫娲嚃閺嶎厽鈷掑ù锝勮閻掔偓鎱ㄥ鍫㈢暠闁宠绉瑰鎾偐閻㈢數鍔归梻浣告贡閸庛倝骞愭ィ鍐┾挃闁告洦鍨遍悡鏇熺箾閹寸偐妲堥柛顐犲劚缁狀垱绻涘顔荤凹闁抽攱鍨垮濠氬醇濮橆厽鐝旈梺浼欓檮缁捇寮诲☉妯滅喖宕烽鐘靛幆闁诲氦顫夊ú婊堝极婵犳艾鏄ラ柍褜鍓氶妵鍕箳閹存繍浠鹃梺鎶芥敱閸ㄥ湱妲愰幘瀛樺閻犲浄绱曢崝閿嬬節閳封偓鐏炲ジ鍋楅梺鍝勬湰濞茬喎鐣锋總绋款潊闁冲搫鍟慨鍏间繆閻愵亜鈧牕煤閳哄啫绶ら柛鎾楀嫬搴婂┑鐘绘涧濡厼顭囬埡鍌樹簻闁瑰搫妫楁禍楣冩倵鐟欏嫭灏俊顐ｇ箓椤繘鎼归崷顓狅紲濠碘槅鍨卞鍨潖閸喒鏀介柣鎰级鐎氬懐绱撳鍕獢闁靛棔绀侀埢搴ㄥ箻閸愭彃绁梻渚€娼х换鍡楊瀶瑜旈獮蹇撁洪鍛嫼闂佸憡绋戦敃銉ョ暦閸曨垱鍊堕煫鍥ㄦ⒒閹冲洨鈧娲忛崹褰掑煡婢舵劕顫呴柨娑樺楠炲牓姊绘担铏瑰笡闁挎氨鐥紒銏犲箺闁哄懎鐖奸幃浠嬪川婵犲嫬甯楅梻渚€娼ч¨鈧┑鈥虫处閺呭爼鏌嗗鍡欏帗閻熸粍绮撳畷婊堝Ω瑜忕粈濠囨煕閳╁喚鐒芥い鈺傜叀閹綊鎮滃Ο纭呭焻闂侀€炲苯澧悽顖涱殘閹广垹鈹戦崱鈺傚兊濡炪倖鎸炬慨瀵告暜妤ｅ啯鈷掑ù锝囶焾椤ュ繘鏌涚€ｎ亝鍣介柟骞垮灲瀹曟﹢顢欐總鍛婏紬闂備椒绱徊鑺ュ緞閸ヮ剙纾婚柟鎹愵嚙缁€鍌氼熆鐠虹尨姊楀瑙勬礋濮婄粯鎷呴崫銉ㄥ┑鈽嗗亜濞硷繝骞冮悙鐑樻櫇闁稿本绋戞禍妤呮⒑閸濆嫭鍌ㄩ柛銊︽そ瀹曟劙鎮介崨濠勫弳濠电娀娼уΛ婵嬵敁濡も偓闇夋繝濠傚缁犳﹢鏌嶈閸撴繈锝炴径濞掓椽寮介鐐茬彉濡炪倖甯掔€氼剛绮婚悙鐑樼厪濠电姴绻愰々顒傜磼閳锯偓閸嬫捇姊绘担鍛婂暈婵炶绠撳畷銏ゆ嚃閳哄啰鐣堕梺璺ㄥ枔婵敻鍩涢幋锔界厽闁绘柨鎲＄欢鍙変繆閹绘帩鐓奸柡宀€鍠栭幖褰掝敃閵忕媭娼氭俊銈囧Х閸嬫盯藝閻㈠摜宓佹慨妞诲亾妞ゃ垺鐟╅幊鏍煛婵犲唭褔姊婚崒娆戭槮闁汇倕娲俊鎾焵椤掑嫭鐓曢悗锝庡亝瀹曞矂鏌″畝鈧崰鎾诲焵椤掑倹鏆╂い顓炵墦瀹曘垻鈧稒蓱閸欏繐鈹戦悩鎻掝伀閻㈩垱鐩弻鐔风暋閻楀牆娅ょ紓浣诡殘閸犳牠銆佸☉姗嗙叆闁告劑鍓遍鍕ㄦ斀闁挎稑瀚禍濂告煕婵犲啰澧电€规洖缍婇幃鐣岀矙鐠侯煉绱梻浣稿閻撳牓宕板璺烘辈闁挎洖鍊归悡娆撳级閸繂鈷旈柣锝堜含缁辨帡鎮╅崫鍕優缂備浇椴搁幐濠氬箯閸涱噮娈介柕濠忕畱閸濈儤顨ラ悙鑼闁圭厧缍婂畷鐑筋敇閻欏懐闂繝鐢靛仩閹活亞寰婇懞銉х彾濠电姴娲ょ壕鍧楁煙闁箑骞戝ù婊勭矒閺岀喓鈧數顭堟禒褔鏌熼崘鍙夊窛闁逞屽墲椤煤濡ソ娲偄閼测晛绁﹂梺鎼炲労閸撴岸宕戠€ｎ喗鐓曟い鎰Т閻忊晜顨ラ悙鑼ф慨濠勭帛閹峰懘宕ㄦ繝鍌涙畼缂傚倷绀侀鍡涘垂閸ф鏋侀柛鎰靛枛鍞梺瀹犳〃閼冲爼鏁嶅▎鎾粹拺鐟滅増甯掓禍浼存煕濡搫鈷旂€殿啫鍥х劦妞ゆ帒瀚埛鎴︽⒑椤愩倕浠滈柤娲诲灡閺呭爼顢涘鍛紲濠德板€曢崯顐﹀几濞戙垺鐓曢柍瑙勫劤娴滅偓淇婇悙顏勨偓鏍ь啅婵犳艾纾婚柟鐐暘娴滄粍銇勯幇鈺佺伄缂佺姳鍗抽幃锟犲Χ閸℃劒绨婚棅顐㈡处閹告悂顢旈锝冧簻闁哄倹瀵ч崰姗€鏌″畝鈧崰鏍箠濠靛鍋嬮柛顐ｇ箖闁款厾绱撻崒娆戝妽鐟滄澘鍟…鍥晸閻樿尙鐣烘俊銈忕到閸燁垶藟閸喓绠鹃柟瀵稿仜缁楁岸鏌￠崒妤€浜鹃梻鍌氬€烽懗鍓佸垝椤栫偛绀夋俊顖炴？閻掑﹥绻涢崱妤呯崪闁兼澘娼￠弻鐔虹磼閵忕姵鐏嶉梺缁樻尰濞叉牠鍩為幋锔藉亹闁圭粯甯楀▓璺衡攽閻愭彃绾ч柟鍛婂▕瀵鈽夐姀鐘靛幐婵炶揪绲块幊鎾斥枔濡ゅ懏鈷戦悹鍥ｂ偓铏亶缂備緡鍠楅幑鍥嵁婵犲洦鍊烽柛婵嗗珋閵娾晜鐓忛煫鍥堥崑鎾诲箛娴ｉ搴婂┑鐘垫暩婵兘寮幖浣哥；闁绘劕鎼粻鏉库攽閻樺疇澹橀柡鍕╁劦閺屾盯骞囬棃娑欑亪缂佺偓鍎抽…鐑藉蓟閻旂厧绀堢憸蹇曟暜濞戙垺鐓熼柟鎯у暱閺嗙喖鏌熼懠顒夌劸妞ゎ厹鍔戝畷鐓庘攽閸偅肖濠电姷鏁搁崑鐐哄垂椤栫偛鍨傞柛锔诲幖椤ユ氨绱撴担璇＄劷缂佺娀绠栭弻鐔衡偓娑欘焽閹冲啴鏌ｈ箛锝勯偗闁哄本鐩俊鍫曞幢濡も偓椤秹姊洪棃娑欐悙閻庢碍婢橀锝嗙鐎ｎ€晝鎲告径瀣弿闁搞儜鈧弨浠嬫煟閹邦剙绾ч柛锝堟閳规垿顢欓悙顒佹瘓婵犵绱曢弫璇茬暦閻旂⒈鏁嶆慨姗嗗墮缁侇喗绻濆閿嬫緲閳ь剚鍔欏畷鎴﹀箻鐡掍胶鎳撻…銊╁醇閵忋垺姣囨繝娈垮枛閿曘儱顪冮挊澶屾殾妞ゆ劧绠戠粈瀣亜閹哄秶鍔嶉悗姘－缁辨捇宕掑▎鎴М濡炪倖鍨靛Λ娑㈠极椤曗偓閹瑩宕崟顓у敼闂備線娼х换鎺撴叏椤撱垹缁╁ù鐘差儐閸婄敻鏌ㄥ┑鍡欏嚬缂併劏濮ら妵鍕晜閸濆嫬顫囧┑顔硷龚濞咃綁鍩€椤掆偓濠€杈ㄦ叏閻㈢违闁告劦鍠楅崑锝吤归敐鍛础闁告瑢鍋撻柣搴ゎ潐濞叉﹢宕归崸妤冨祦婵☆垰鍚嬬€氭岸鏌ょ喊鍗炲闁哄鎲℃穱濠囨倷椤忓嫧鍋撻弽褜娼栧┑鐘宠壘缁犵娀鏌熼幆褜鍤熸い鈺傚絻铻栭柨婵嗘噹閺嗙偤鏌涚€Ｑ冨⒉缂佺粯鐩畷鍗炍旈崘顏嶅敹婵＄偑鍊曞ù姘閻愮儤鍎夋い蹇撶墛閸婇攱銇勯幒宥囶槮闁逞屽墯閸旀瑩寮婚敍鍕勃闁告挆鍕灡濠电姷顣介崜婵嬪箖閸屾稐绻嗛柣銈庡灱濡茬偓淇婇妶鍡橆棃婵﹦绮幏鍛存惞楠炲簱鍋撴繝鍥ㄧ厸闁稿本鑹鹃埀顒€鐏濋悾鐑藉即閵忕姷顔岄梺鍦劋缁诲倸鈻撻锔解拺闁告稑锕ユ径鍕煕閵婏箑顥嬬紒顔款嚙閳藉鈻庡鍕泿闂備礁婀遍崕銈夊春閸惊锝夊捶椤撶姷锛濋悗骞垮劚閹冲酣鍩€椤掆偓閻忔繈锝炶箛鏇犵＜婵☆垵顕ч鎾绘⒑閼姐倕鏋涢柛瀣躬瀹曠數鈧綆鍓涚壕钘壝归敐鍛棌闁稿孩鍔欓弻娑㈠Ω閵壯呅ㄩ梺绯曟杹閸嬫挸顪冮妶鍡楃瑐缂佲偓娓氣偓瀹曠敻顢楅崟顒傚幈闂佽鍎抽顓灻虹€电硶鍋撳▓鍨珮闁稿锕妴浣割潩鐠鸿櫣鍔﹀銈嗗笒鐎氼喖鐣垫担閫涚箚妞ゆ牗绻傛禍鍦棯閹冩倯濞ｅ洤锕、娑橆煥閸愩劋绮俊銈囧Х閸嬬偤銆冩繝鍌ゆ綎闁惧繗顫夐崗婊堟煕濞戝崬寮炬俊顐㈢墦濮婅櫣鎲撮崟顑句户婵炲瓨绮庨崑娑樺祫闂佸湱澧楀姗€宕￠幎鑺ョ厪闊洤艌閸嬫捇宕楅崨顔间簼婵犵绱曢崑鎴﹀磹閺嶎厼绠伴柛顐ｆ礀閸ㄥ倹绻涘顔荤凹闁稿鍊块弻锟犲炊閵夈儳浠肩紓浣哄Т濠€杈╂閹烘鏁婇柣鎾抽鏉堝懘姊虹粙娆惧剱闁规悂绠栭崺鈧い鎺嗗亾婵犫偓鏉堛劍鍙忛柟缁㈠枟閸嬪倹鎱ㄥ璇蹭壕濠殿喖锕ュ浠嬬嵁閹达箑绠涙い鎺嗗亾闁诡垳鍋ゅ铏圭矙濞嗘儳鍓抽梺绋款儑閸犳牠鐛幋锕€顫呴柣姗嗗亝椤秹姊洪棃娑氱濠殿喗鎸抽幊鎾诲垂椤旇鏂€闂佸疇妫勫Λ妤呮倶閵夛负浜滈柡鍥ф濞诧箓藟婢跺备鍋撻獮鍨姎妞わ缚鍗抽崺娑㈠箣閻樼數锛滈柣搴秵閸嬫帡宕曢妷鈺傜厱閹艰揪绱曠粻濠氭煛鐏炲墽鈯曠紒缁樼箞瀹曟帒鈽夊Ο瑙勬▕闂佽瀛╅鏍窗濞戙埄鏁嬬憸鏃堛€佸Ο鑽ら檮缂佸娼￠崬璺侯渻閵堝棗濮х紓宥呮閸┾偓妞ゆ巻鍋撴繛宸幖椤繒绱掑Ο璇差€撻梺鍛婄☉閿曘倝寮抽崼銉︹拺閻熸瑥瀚幗鍐偓瑙勬礈閺佹悂宕氶幒鎴旀瀻闁规儳纾鎺戔攽閻橆喖鐏╅悗姘憸缁辩偞绗熼埀顒勬偘椤曗偓瀹曞爼顢楅埀顒傜棯瑜旈幃瑙勭瑹椤栨粌甯ラ梺鍝ュ仦濡炶棄顫忕紒妯诲闁告稑锕ラ崕鎾绘⒑閸濄儱娅忛柛瀣工閻ｇ兘骞囬鐘电槇濠殿喗锕╅崢钘夆枍閺嵮€鏀介柣妯款嚋瀹搞儵鏌ｅΔ鈧敃顏堝春濞戙垹绠ｉ柨鏃囆掗幏濠氭⒑閸撴彃浜為柛鐘虫崌婵℃挳骞掗弮鍌滐紲闂佺粯蓱瑜板啴寮抽柆宥嗙厓閻熸瑥瀚悘瀛樸亜閵忥紕鎳呴柛鐘诧躬瀹曪繝鎮欓幖顓炴櫃闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼顢涢悙瀵稿幈闂佸綊鍋婇崹浼村触閸︻厾纾奸弶鍫氭櫅娴狅箓鏌熷畡鐗堝殗鐎规洘绮撳畷锝嗗緞瀹€鈧埢澶娾攽閻樺灚鏆╅柛瀣☉铻ｅ┑鐘插暟椤╁弶绻濇繝鍌氼仼妞ゆ洟浜堕弻锝呂熼懖鈺佺闂佺粯鎸哥换鎰扳€︾捄銊﹀磯闁惧繒鎳撻。娲⒑閸涘﹥宕岀紒鐘崇墵瀵濡搁妷銏℃杸闂佺硶妾ч弲婊勬櫏闂傚倷鑳剁划顖炲箰妤ｅ啫绐楅柡宥庡幖閽冪喓鈧箍鍎遍ˇ顖涘閻樼粯鐓曢柡鍥ｅ墲绾儳霉閸忕厧濮嶆慨濠呮閹风娀寮婚妷褍妞界紓鍌欒兌婵敻骞戦崶褜鍤曞┑鐘宠壘閸楁娊鏌曡箛鏇炐㈤柤鏉挎健濮婃椽宕崟顒€绐涙繝娈垮灱閸樼厧宓勫銈嗘磵閸嬫捇鏌＄仦鐔峰椤曡鲸绻涢崱妯虹仼鐞氾箓姊绘担鍛婃儓閻炴凹鍋婂畷鎰板冀椤撶偟鐤勯梺闈浥堥弲娑氱不濞戞瑣浜滈柟杈剧稻椤ュ霉濠婂懎浜惧ǎ鍥э躬婵″爼宕ㄩ鍏碱仭闂備胶顭堟鎼佹晝椤忓牆钃熸繛鎴欏焺閺佸啴鏌ㄥ┑鍡樻悙妞も晩鍓熷铏规偘閳ュ厖澹曢梻浣稿悑娴滀粙宕曢娑氼洸婵犲﹤鐗婇悡娑㈡煕閹板墎鍒板ù婊堢畺濮婃椽宕崟闈涘壋缂備緡鍣崹宕囧垝椤撱垺鍋勯悘蹇庣劍椤秹姊洪棃娑㈢崪缂佽鲸娲熷畷銏ゅ础閻愨晜鏂€闂佸疇妫勫Λ妤呮倶閳ヨ秮鐟邦煥閳ь剛鍒掑▎蹇曟殾闁硅揪绠戦～鍛存煃閸ㄦ稒娅呭ù婊堢畺閹嘲鈻庤箛鎿冧痪缂備讲鍋撻柛鎰典簽绾惧吋銇勯弮鍥撶€规洖鐭傞弻鏇㈠幢閺囩媭妲梺瀹狀嚙闁帮綁鐛€ｎ亖鏀介柛銉㈡杹閸嬫捇骞庨懞銉у幐婵犮垼娉涢敃锔芥櫠閹达附鐓曢柡鍌濇硶閻掓悂鏌熼娆戭槮妞ゎ厹鍔戝畷濂告偄閸欏顏烘繝鐢靛仦閹稿宕洪崘顔肩；闁规儳顕粻鎯归敐鍛毐婵炶绠撳畷鎴犫偓锝庡枟閻撴洟鏌嶉埡浣告殧濞存粍顨嗙换娑㈠箣閻愬啯宀稿鍛婃償閵婏妇鍘甸梺璇″瀻閸滃啰绀婇梻浣告啞閿曘垺绂嶇捄渚綎婵炲樊浜滈幑鑸点亜閹捐泛浠滃┑鈥虫惈椤啴濡堕崘銊ヮ瀳濠碘槅鍋呯换鍫ョ嵁閸愵喖鐏抽柡鍌樺劜椤秹姊洪棃娑㈢崪缂佽鲸娲熷畷銏ゅ础閻愨晜鏂€闂佺粯蓱婢х娀宕奸妷銉э紱闂佽鍎虫晶搴ｅ婵傚憡鐓冪憸婊堝礈濮樿泛绠柛娑欐綑閹硅埖銇勯幘妤€瀚伴弫婊堟⒒閸屾瑦绁版い顐㈩樀椤㈡瑩寮介鐐电崶闂佸湱鍎ら〃鍛婵犳碍鐓欓柟瑙勫姇閻撴劙鏌涢悩鍙夘棦闁哄本鐩鎾Ω閵夈儺娼炬俊鐐€х€靛矂宕伴弽顓涒偓鏃堝礃椤斿槈褔骞栫划鍏夊亾閼碱剛娉垮┑锛勫亼閸娧呯不閹烘挾顩叉い鎺戝€归～鏇㈡煙閹规劦鍤欑紒鐘差煼閹妫冨☉姗嗘濠电偞娼欑€氫即寮婚敐鍡樺劅妞ゆ牗绮庢牎濠电偛鐡ㄧ划宥囧垝鎼达絽鍨濋柨婵嗘噳濡插牊绻涢崱妯虹仼闁伙箑鐗撳鍝勑ч崶褏浼堝┑鐐板尃閸愵亝鎳冮梻鍌氬€烽懗鍫曗€﹂崼銉︽櫇闁挎洖鍊哥粈鍌涗繆椤栨繃顏犻柡鍡檮閵囧嫰骞囬妸锕€娈ラ梺鍝勫暊閸嬫捇鏌熷畡鐗堝殗闁圭厧缍婂畷鐑筋敇閻曚焦缍嬮梻鍌氬€搁崐鐑芥倿閿曞倹鍎戠憸鐗堝笒閸ㄥ倿鏌﹀Ο渚▓闁绘帞鏅幉鍛婃償閿濆洨鐒块梺鍦劋椤ㄥ棝寮插┑瀣厱閻忕偛澧介妴鎺楁煕濮椻偓娴滆泛顫忓ú顏咁棃婵炴垼浜崝鎼佹⒑缁嬪灝顒㈠┑鐐诧工閻ｅ嘲煤椤忓懏娅滄繝銏ｆ硾椤戝洭宕㈤崨濠勭閺夊牆澧介崚鏉款熆閻熷府韬€规洘娲濈粻娑㈠棘鐠佸磭鐩庢俊鐐€曠换鎰偓姘煎墴瀵娊鏁愰崨顏呮杸闂佺偨鍎辩壕顓㈠春閿濆洠鍋撶憴鍕闁挎洏鍨烘穱濠囧箹娴ｈ倽銊︺亜閺冨牊鏆滈柛瀣崌楠炴﹢顢欑憴锝嗗濠电偠鎻紞鈧俊顐㈠瀹曘儴銇愰幒鎾跺幈闂佺粯妫冮弨閬嶅磻閵壯€鍋撳▓鍨灍闁绘搫绻濋獮鍐煛閸涱喖娈ラ梺闈涚墕閹虫劙濡堕敃鍌涒拻濞达絽鎲￠崯鐐烘煕閺冩挾鐣电€规洏鍨婚幉鎾礋椤撗勯敜闁荤喐绮庢晶妤冩暜濡ゅ懏鍋傛繛鍡樻尰閻撶喖鏌熺€甸晲绱虫い蹇撶墛閸婂爼鏌嶉崫鍕櫤闁绘挾鍠栭弻鏇㈠醇濠靛棌鍋撻崨濠勵洸闁绘劦鍓涚弧鈧紒鐐緲椤﹁京澹曢崸妤佺厱閻庯綆鍋勯悘瀵糕偓瑙勬礃閸旀瑥顕ｆ禒瀣垫晣闁绘劘鍩栭幉浼存⒒娓氣偓濞佳嗗闂佸搫鎳忕粙鎾诲箟閹绢喗鏅濋柛灞剧☉閳ь剛鏁婚弻銊モ攽閸℃侗鈧鏌＄€ｎ剙鏋涢柡灞剧⊕缁绘繈宕掑鍐幗闂備礁鎼張顒勬儎椤栫偑鈧線寮撮姀鈥充汗闂佸湱绮敮鎺楋綖濮樿埖鈷掑ù锝囨嚀閳绘洟鏌￠埀顒勬焼瀹ュ懎鐎梺鍓茬厛閸ｎ噣宕甸弴銏＄厱妞ゆ劧绲剧粈鍐煕婵犲嫬鍘撮柡灞稿墲瀵板嫮鈧綆浜為崝绋库攽閳藉棗浜滄俊顐ｎ殜閳ユ棃宕橀鍢壯囩叓閸ャ劌鍤柛姘噺缁绘繄鍠婂Ο宄颁壕闁惧浚鍋勭粣娑樷攽閳ュ啿绾ч柛鏃€鐟╅悰顕€骞掑Δ鈧粻鑽も偓瑙勬礀濞层劑鎮伴鈧铏规兜閸涱収妫堥梺瑙勬た娴滅偛危閹版澘鍗抽柕蹇曞Т閸嬪秴顪冮妶鍡楀闁稿﹥顨堟竟鏇㈡寠婢规繂缍婇弫鎰板炊閸撲礁濮奸梻渚€鈧偛鑻晶顔界節閳ь剟鏌嗗鍛€銈嗘磵閸嬫捇鏌℃担瑙勫磳闁诡喒鏅犲畷锝嗗緞鐏炵浜炬い鎺戝閳锋垿鏌涘☉姗堝伐濠殿噯绠撻弻娑㈡偐瀹曞洤鈷堟繝銏ｎ潐濞茬喎鐣峰Δ鍛殐闁冲搫鍠氶崯搴ㄦ⒒娴ｇ儤鍤€妞ゆ洦鍙冨畷鏇㈠箛閻楀牆鈧潡鏌ら幁鎺戝姍缂佽妫涚槐鎾存媴闂堟稓浠奸梺鍝勵儐閻╊垶寮诲鍥ㄥ枂闁告洦鍋嗘导宀勬⒑鐠団€虫灀闁哄懐濞€閵嗕礁鈻庨幘鏉戞異闂佸疇銆€閸嬫挾绱掓潏銊夋垹鎹㈠┑瀣仺闂傚牊绋愮划璺侯渻閵堝繒绱伴柛妤佸▕楠炲棝宕熼锝嗘櫖闂佺粯鍔︽禍鏍磻閹惧鐟归柍褜鍓欓锝嗙鐎ｅ灚鏅ｉ梺缁樺姌鐏忣亪鍩€椤掆偓閻忔繈鍩為幋锔藉€烽柡澶嬪灩娴犳悂姊洪懡銈呮瀭闁稿氦灏欑划瀣箳閺囥劍鈻屾繝娈垮枛閿曘儱顪冮挊澶屾殾闁绘垹鐡旈弫鍥煟閹邦厼绲绘い顒€妫欐穱濠囨倷椤忓嫧鍋撻幋锕€绀夐悘鐐跺▏濞戞ǚ鏀介悗锝庝簼濡差剙鈹戦悙鏉戠仧闁搞劌婀辩划濠氬箮閼恒儳鍘甸梺缁樺姌濡嫭淇婇懖鈺冪＝鐎广儱鎷戦煬顒傗偓娈垮櫘閸嬪﹪鐛崶顒€绾ч柛顭戝枤閻涒晜淇婇悙顏勨偓鏍蓟閵娾晛瑙﹂悗锝庝簴閺嬫梹鎱ㄥ璇蹭壕濠殿喖锕︾划顖炲箯閸涙潙宸濆┑鐘插暙閺嬫垿姊绘担鍛婃喐濠殿喚鏁婚獮鎴﹀炊瑜忛弳锕傛煙鏉堥箖妾柛瀣閺岋綁骞嬮悜鍥︾返濠电偠鍋愰崰鏍ь潖濞差亜鎹舵い鎾跺仜婵℃椽姊洪崫鍕効缂佺粯绻傞悾鐑藉箣閿曗偓缁犺崵绱撴担鑲℃垵鈻嶅鍫熺厵闁兼祴鏅炶棢闂侀€炲苯澧查悘蹇旂懇閹嫭鎯旈妸锔规嫽婵炶揪绲块悺鏃堝吹濞嗘垹纾肩紓浣姑悘瀛橆殽閻愭潙濮嶆鐐查叄閹稿﹥寰勬惔銏″暫闂傚倷鐒﹂弸濂稿疾濞戙垹鐤い鏍ㄧ☉閸ㄦ棃鎮楅棃娑欐喐缁炬儳銈搁幃妤呮晲鎼粹€茬盎濡炪倖娲樼划宥囨崲濞戙垹閱囬柕蹇嬪灩缁楋紕绱撴担铏瑰笡缂佽瀚板畷鐗堢節閸嬬晫鍠栧畷顐﹀礋閵婏箑鐝堕梻鍌氬€峰ù鍥敋閺嶎厼绐楅柡宥庡幖绾惧綊鏌涢…鎴濇灓闁哄棴闄勭换娑橆啅椤旇崵鍑归梺鍝勬噺閹倿寮婚敐鍛傜喖宕归鐐嚄闂備焦瀵х粙鎺斿垝瀹€鍕厴闁硅揪瀵岄弫濠囨煛閸屾ê鈧挾娆㈤悽鍛娾拺闁告稑锕ョ亸浼存煟閻斿弶娅婄€规洖鎼埥澶愬閻樻彃绁梻渚€娼х换鍡楊瀶瑜旈獮蹇旂節濮橆厸鎷虹紓浣割儐鐎笛冿耿娴煎瓨鐓熼柣鏃€绻傚▔姘跺炊椤掍焦娅囬梺绋挎湰缁嬫捇宕㈤悽鐢电＜闁绘劦鍓氱欢鑼偓瑙勬处閸撴氨绮嬪澶婄妞ゆ梻鎳撴禍楣冩偡濞嗗繐顏璺哄閺屾盯濡搁妷褍鐓熼梺闈涙缁舵艾顕ｉ幘顔碱潊闁斥晛鍟悵鏇㈡⒒娴ｈ棄袚闁挎碍銇勯敂璇叉灓缂佽鲸妫冨鎾閳锯偓閹风粯绻涙潏鍓хК婵炲拑缍佹俊瀛樼節閸ャ劎鍘遍梺瑙勫劤椤曨厾绮婚悙鐑樼厵妞ゆ梻鍋撻悞鎸庛亜閿曗偓绾绢厾妲愰幒鏂哄亾閿濆簼鎲炬俊鎻掓啞閵囧嫰骞橀崘鍙夊€悗鍨緲鐎氼噣鍩€椤掑﹦绉甸柛鎾寸懃椤曪綁鎼归銈囩槇闂佹眹鍨藉褔鍩㈤崼鐔虹濞达絽鍟块崥妯衡槈閵忊晜鏅ｉ梺缁樺姇缁嬪嫮绱為埀顒勬煏閸ャ劌濮嶆鐐村浮楠炴鎹勯崫鍕啈闂傚倸鍊峰ù鍥綖婢舵劕纾块柟鍓佺摂閺佸銇勯幘鍗炵仼缂佺姷濞€閺屾盯濡烽鐓庮潽闂佺粯鎸婚悷锕傚Φ閸曨垰绫嶉柛灞剧矋閹叉ê鈹戦悙鑼婵☆偄鍟村璇差吋婢跺鐧勬繝銏ｅ煐钃辩粭鎴︽⒒娴ｅ摜鏋冩い鏇嗗嫷娈芥慨婵嗙灱娴滀粙姊绘担铏瑰笡闁圭鎲￠〃銉╁川婵犲孩顔勯梻鍌氬€搁崐鎼佸磹閹间礁纾归柣鎴ｅГ閸婂潡鏌ㄩ弴妤€浜惧銈庝簻閸熸潙鐣风粙璇炬棃鍩€椤掑嫬纾奸柕濞垮劗閺€浠嬫煕鐏炲墽顣查柛鐔哄仱閺屾稒鎯旈姀鈽嗘闂佸搫琚崐鏇㈡箒闁诲函缍嗛崑鍛存偟閺囩儐娓婚柕鍫濋娴滄繃绻涢懠顒€鏋涚€殿喖顭烽幃銏ゅ礂閻撳簶鍋撶紒妯圭箚妞ゆ牗绻傞崥褰掓煕濡粯鍊愭慨濠呮缁瑥鈻庨幆褍澹夐梻浣告贡閹虫挸煤椤撶儐鍤曟い鎰剁畱缁犳稒銇勯幘璺烘瀻闁告柨鎳樺娲倷閽樺濮ら柣蹇撶箲閻熲晠骞嗛崟顒佸劅闁靛鑵归幏缁樼箾鏉堝墽鎮奸柣鈩冩瀹曢潧鈻庨幋鐘碉紲缂傚倷鐒﹂敋闁诲繐鐡ㄩ〃銉╂倷閺夋垵顫掑Δ鐘靛仜闁帮綁骞愭繝鍐ㄧ窞閹兼番鍨洪崯娲⒒閸屾瑨鍏岄柛瀣ㄥ姂瀹曟洘娼忛埡渚囨濡炪倖鎸堕崹鐟靶ч弻銉︾厱闁斥晛鍟伴埊鏇㈡煕婵犲嫭鏆柡灞诲妼閳规垿宕卞☉鎵佸亾濡も偓椤儻顧侀柛锝忕秮瀵鈽夐姀鐘靛幐婵炶揪缍€濡嫰顢旈鐑嗘富闁靛牆绨肩花濠氭煕閻旈鎽犲ǎ鍥э躬閹虫粓宕归銏犲Τ闂備胶鍋ㄩ崕杈╁椤撱埄鏁婂鑸靛姈閳锋帒霉閿濆懏鍟為柛鐔哄仦閹便劍绻濋崒婊呅ㄩ悗瑙勬礀缂嶅﹪骞冩禒瀣窛濠电姴鍊烽幃锝夋⒒娴ｈ櫣甯涢柛銊ュ悑閹便劑濡舵径濠勶紱闂佸憡娲﹂崢鎯涢鐐寸厵鐎瑰嫭澹嗛悞鎼佹煕濠靛洦銇濋柡宀嬬節瀹曘劑顢曢姀顫礄婵犳鍠栭敃銊モ枍閿濆洤鍨濇繛鍡樻尭缁犱即骞栧ǎ顒€鐏悗姘▕濮婄粯鎷呴挊澶樻濡炪値鍋勯ˇ闈涚暦閺囥垹绠柦妯侯槺閸樻椽姊虹憴鍕妞ゆ泦鍐╂殰闂傚倷绶氬褔藝椤撱垹鍨傛繛宸簻濡﹢鏌嶈閸撶喎顫忕紒妯诲闁惧繒鎳撶粭锟犳⒑閹稿骸鍝洪柡宀嬬秬缁犳盯寮崹顔芥嚈闁诲孩顔栭崰妤佺箾婵犲洤鏄ラ柍鈺佸暞婵挳鏌涘▎蹇ｆЧ闁哄鎲℃穱濠囨倷椤忓嫧鍋撻弽顬℃椽寮介鐐电枃闁硅偐琛ュΣ鍛村吹閺囩喆浜滈柡鍐ㄧ墛閺嗘粓鏌涚€ｎ偅灏甸柟鍙夋尦瀹曠喖顢楅崒銈喰為梻鍌欑劍閹爼宕濈仦绛嬬劷闁跨喓濮甸崑妯汇亜閺傛寧顫嶉柣鏃傚帶瀹告繈姊婚崼鐔烘创闁告瑥瀚妵鍕閿涘嫬鈷堥梺鍦嚀鐎氱増淇婂宀婃Ъ闂佸搫鎳岄崝鎴濐潖婵犳艾纾兼慨姗嗗厴閸嬫捇骞栨担娴嬪亾閿曞偆鏁嗛柛鏇ㄥ亞閿涙盯姊洪崨濠冨闁稿﹤顑呯叅妞ゅ繐鎳忓▍鍥⒑缁嬫寧婀版慨妯稿姂椤㈡瑩宕堕浣叉嫼缂傚倷鐒﹂敋濠殿噯绠撻弻娑㈠箻绾惧顥濋梺瀹狀嚙缁夊綊骞冮埡鍐＜婵☆垳鍘ч獮鎰版⒒娴ｈ鍋犻柛搴灦瀹曟洟鏌嗗鍡椻偓鑸点亜韫囨挾澧涢柣鎾存礀閳规垿鎮╅幓鎺嗗亾缂佹顩锋繛鎴欏灪閻撴瑥銆掑顒備虎濠碘€冲悑閵囧嫰顢曢敐鍥╃厜閻庤娲栧畷顒冪亙闂侀€炲苯澧撮柛鈺傜洴楠炴帡骞嬮弮鈧弬鈧梻浣哥枃濡嫬螞濡ゅ懏鍊舵繛鍡樻尰閻撴洟鎮楅敐搴′簼鐎规洖鏈幈銊︾節閸曨厼绗￠梺鐟板槻閹虫ê鐣烽妸锔剧瘈闁告劑鍔屾竟宥夋⒒閸屾瑧顦﹂柛姘儏椤啴宕稿Δ鈧崹鍌溾偓瑙勬礀濞层倝宕瑰┑瀣厸闁告劑鍔庢晶娑㈡煕婵犲偆鐓兼慨濠冩そ楠炴垿骞囬鍌氬Ш闂備礁鎲￠弻銊х矓閸撲礁鍨濇い鎾卞灪閸嬪嫰鏌ｉ幘铏崳闁告棑绠戦—鍐Χ閸℃鐟ㄩ柣搴㈠嚬閸撶喖骞忛幋锔藉亜闁告縿鍎抽鏇㈡⒑閻熸壆鎽犻柣鐔村劦閹﹢鍩￠崘顏嗭紲闂佺粯锚濡﹪鎮℃總鍛婄厵妞ゆ梻鐡斿▓鏃堟煃閽樺妲搁柍璇查铻ｉ柣鎾抽妤旀繝鐢靛Х閺佹悂宕戝☉銏″亱闁告洦鍨扮壕瑙勪繆閵堝懎鏆炴い顐ｆ礋閺岀喖骞嗚閸ょ喖鏌ｉ悢椋庣Ш闁哄本鐩俊鐑藉箣濠靛棭浼€婵炲瓨绮岄悥鐓庮潖缂佹ɑ濯撮柦妯侯槸閹偤姊洪棃鈺冪Ф濠碘€虫川閸掓帗绻濆顒傤吅闂佹寧姊荤划顖炲疾椤忓牊鈷戦梻鍫熶緱濡叉挳鏌￠崨顔俱€掔紒顔肩墢閳ь剨缍嗛崑浣圭濠婂牊鐓欓柣鎴灻悘銉╂煃瑜滈崜娆撯€﹂悜钘夌畾濞撴埃鍋撶€规洖銈告俊鐑芥晜閹冪闂傚倷绀侀崥瀣矈閹绢喖鐤鹃柣鎰煐閿涘倿姊婚崒娆戭槮闁硅绻濋獮鎰版嚒閵堝棗搴婇梺鍓插亝缁诲嫰寮抽敃鍌涚厵濞村吋娼欐禍浼存煛娴ｅ摜效闁哄矉缍侀獮鍥敊閸忓顦甸弻鐔割槹鎼达絽绗＄紓浣虹帛缁嬫帒顭囪箛娑樼鐟滃繗鈪插┑锛勫亼閸娿倝宕戦崟顖€鍥濞戞碍娈鹃梺纭呮彧闂勫嫰宕戦幇顔剧＝濞达綀顕栭悞浠嬫煕濮椻偓娴滃爼寮婚悢鐓庣闁兼祴鏅滃▓顒勬⒑缁嬪尅鏀绘繛鑼枎閻ｇ兘濡烽埡浣瑰祶濡炪倖鎸荤粙鎴炵妤ｅ啯鐓曟い顓熷灥娴滄繄绱掗懜鐢靛弨闁哄被鍔戝鏉懳熺悰鈥充壕婵°倕鎳庨惌妤呮煕濞戝崬寮炬繛鎾愁煼閺屾洟宕煎┑鍥ф缂備胶濮抽崡鎶藉箖濡も偓椤繈鎮℃惔銏㈠綆闂備浇妗ㄧ粈浣虹矓閹绢喖鐓″鑸靛姇椤懘鏌嶉柨顖氫壕闂佸綊鏀卞钘夘潖濞差亝顥堥柍杞拌兌濡诧綁姊洪崨濞掝亪宕ョ€ｎ剛鐭夌€广儱顦粈鍫㈡喐韫囨洖顥氬┑鍌氭啞閻撴洟鏌熼幑鎰毢妞わ讣绠戦湁闁绘顔婇幉楣冩煛瀹€鈧崰鏍€佸▎鎾充紶闁告洦鍘洪惀顏呯節閻㈤潧浠ч柍宄扮墛缁傚秹顢旈崼銏犵ウ閻庡箍鍎遍ˇ浠嬪极婵犲洦鐓熼柟鎯х－瀹€鎼佹煙缁嬪灝顏慨濠傤煼瀹曟帒顫濋钘変壕濡炲娴烽惌鍡椼€掑锝呬壕濡ょ姷鍋為悧鐘汇€侀弴銏犖ч柛鈩冾殘瑜版挳姊绘担铏瑰笡闁告梹娲熼獮鏍敃閵堝拋妫滈梺绋跨箰閸氬宕ｈ箛鏂剧箚妞ゆ牗纰嶉幆鍫ユ煙椤旇棄鐏﹂柕鍥у婵＄兘顢涘鍛婵犳鍠栭敃銈夆€﹀畡鎵殾闁圭儤鍨熼弸搴ㄦ煙闁箑鏋旈柛瀣耿閺岋絾鎯旈妶搴㈢秷濠电偛寮剁划鎾愁嚕椤愩倖瀚氶柤纰卞墯濞堢偓绻涢弶鎴濇倯婵炲吋鐟х划璇测槈閵忥紕鍘藉┑掳鍊愰崑鎾绘煟濡も偓濡瑧绮嬮幒妤婃晣闁靛繆妾ч幏娲⒒閸屾氨澧涢柛鎰吹濡叉劙鏁撻悩宕囧帗閻熸粍绮撳畷婊堟偄妞嬪孩娈鹃梺纭呮彧缁犳垹绮绘繝姘厵濡鑳堕崝宥夋煕瀹ュ洦鏆慨濠呮缁辨帒螣鐠囪尙顣插┑掳鍊楁慨鎾箺濠婂牊鍋栭柟顖嗗苯鎮戞繝銏ｆ硾椤戝倿骞忓ú顏呯厽闁绘ê寮剁粈宀勬煃瑜滈崜娆戝椤撶喓顩烽柍鍝勬噺閳锋垿鏌涘┑鍕姎闁哄鍨块弻鐔煎川婵犲倵鏋欓梺璇″枙閸楁娊銆佸▎鎾寸叆妞ゆ牗鐭竟鏇㈡⒑閹稿海绠撳Δ鐘虫倐瀵悂鎮㈤崗鑲╁幈婵犵數濮寸€氼剟宕㈤幘顔界厸鐎光偓鐎ｎ剛袦婵犳鍠掗崑鎾绘⒑鐎圭姵顥夋俊顐ｎ殜瀵煡鏌嗗鍡忔嫼闂佸憡绺块崕閬嶅几鎼淬劍鈷戦悽顖ｅ枤閸掔増銇勯銏㈢缂佽鲸甯掕灒閻犲洤妯婇埀顒佹尵缁辨挻鎷呴崜鎻掑壉濡炪倖鍨堕悷銉ㄧ亱閻庡厜鍋撻柛鏇ㄥ厴閹疯櫣绱撴担鍓插剱妞ゆ垶鐟╁畷鏇＄疀閺傚墽绠氬銈嗗姧缁茶法绮婚幘缁樼厽闁挎繂娲ら崢鎾煙椤斻劌娲ら柋鍥煟閺傚灝妲诲┑鈩冨▕濮婄粯绗熼埀顒€顭囪閳ワ箓顢橀悩鍏哥瑝闂佺鎻粻鎴︽倿閸偁浜滈柟鍝勬娴滈箖姊虹紒妯煎ⅹ闁靛牏顭堥锝嗙節濮橆儵鈺呮煃鏉炴壆鍔嶆い銉︾箞濮婃椽宕滈懠顒€甯ラ梺鍝ュУ鐢繝鐛幇鏉跨妞ゅ繐妫涢敍婊堟⒑缂佹ê濮﹂柛鎾寸懇瀹曟繈濡舵径瀣帾闂佸壊鍋嗛崰鎰板磹閹邦収娈介柣鎰絻閺嗘瑩鎽堕弽顓熺厱婵炴垵宕弸鐔哥箾閸涱喚鐭掗柡宀€鍠栭幃鈩冩償閿濆棙鍠栫紓鍌欐祰椤曆囧疮閺夋垹鏆﹂柡澶嬵儥濞尖晜銇勯幋锝呅撻柡鍌楀亾闂傚倷绀侀悿鍥涢崟顐嬫稑螖閸涱喖鈧埖绻涢崱妯诲鞍闁绘挻娲熼幃妤呮晲鎼粹€茬凹閻庤娲栭張顒勫箞閵婏妇绡€闁告洦鍘肩粭锟犳⒑閻熸澘妲婚柟铏耿楠炴牞銇愰幒鏂跨ウ闁圭厧鐡ㄩ幐鍛婄閹€鏀介柣妯哄级婢跺嫰鏌ｉ幘瀵告创闁哄本绋撴禒锕傚礈瑜庨崳顔剧磽娴ｇ懓濮堟慨濠傤煼閸┾偓妞ゆ帒鍠氬鎰箾閸欏鑰跨€规洖缍婂畷绋课旈崘銊с偊婵犳鍠楅妵娑㈠磻閹炬惌娈介柣鎰级婢跺嫰鏌熷畡鐗堝殗闁诡喚鍏橀獮宥夘敊閸欘偅甯″濠氬磼濮橆兘鍋撴搴㈩偨婵﹩鍓﹂悞鐣屾喐閺冨牆绠栫憸鏂跨暦閸楃儐娓婚柕蹇ョ磿閳藉鎽堕弽顓熺厱闁规澘鍚€缁ㄤ粙鏌ｉ敐鍛煟婵﹥妞藉畷鐑筋敇閻愭彃顬嗘俊鐐€戦崝灞轿涘┑鍡欐殾闁圭増婢橀崹鍌涖亜閹板墎鍒扮€殿喖鐏濋埞鎴﹀煡閸℃浠梺鍛婎焼閸涱喗娈伴梺鍛婃尫鐠佹煡宕戦幘鏂ユ灁闁割煈鍠楅悵顕€姊洪崫銉バｇ€光偓閹间礁鏄ラ柍褜鍓氶妵鍕箳閹存繃鐏撳┑鐐插悑閸旀牜鎹㈠☉銏犵煑濠㈣埖绋栭埀顒冩硶閳ь剝顫夊ú妯兼崲閸岀偛鐓濋幖娣妼缁犺崵鈧娲栧ú銊╁汲椤愶絿绡€闁汇垽娼у瓭闂佹寧娲忛崐婵嬪箖瑜庣换婵嬪炊瑜嶉幆鐐烘倵楠炲灝鍔氭い锔垮嵆閹ょ疀閹垮啰鍞甸柣鐘叉礌閳ь剙纾禒鈺呮⒑閸濄儱娅忛柛瀣閸掓帞鎷犵憗浣规そ椤㈡棃宕ㄩ鍛伖闂傚倷鑳堕崢褔锝為弴銏犵９闁哄洢鍨归崙鐘绘煙鐎电啸缁炬儳鍚嬮妵鍕籍閸パ傛睏闂佽绻楁禍顒傛閹烘鏁婇柤鎭掑労濮婂潡姊洪棃娑欏闁告梹鐟╅悰顕€骞掑Δ鈧Λ姗€鎮归幁鎺戝Ω闁稿锕ら埞鎴︽偐閼碱剚顥夐梺鍝勵槸缁ㄩ亶宕戦幘璇茬疀闁哄娉曢敍娑㈡⒑閸︻厼浜鹃柣锝庝簼缁傚秴顭ㄩ崟鈺€绨婚梺瑙勫劤椤曨參鎯屾繝鍌楁斀妞ゆ梻鍘ч埀顒€顭烽崺鈧い鎺戝枤濞兼劖绻涢幓鎺旂鐎规洘绻堥獮瀣晜鐞涒€充壕濞达絿纭跺Σ鍫熸叏濡も偓濡盯宕ｉ崱娑欌拺闁告稑锕ｇ欢閬嶆煕濡灝浜归柣鐔濆啠鏀介柣妯虹仛閺嗏晛鈹戦鎯у幋鐎殿噮鍋婂畷銊︾節閸愩劌浼庡┑鐐存綑閸氬顭囧▎鎾冲瀭闁稿本鍩冮弨浠嬫煕鐏炲墽鐭ら柣鎺楃畺閺岋繝宕熼埡浣稿Е闂佸搫澶囬埀顒佸墯閸氬骞栫划鍏夊亾瀹曞浂鍟囩紓鍌氬€风拋鏌ュ磻閹炬剚鐔嗛柤鎼佹涧婵牓鏌ｉ幘瀵搞€掗柍褜鍓欑粻宥夊磿鏉堫煈娈介柟闂磋兌瀹撲焦淇婇妶鍛櫤闁绘挻娲熼幃妤呮晲鎼存繄鐩庨梺閫炲苯澧繝鈧柆宥呯闁靛繒濮Σ鍫ユ煏韫囨洖孝闁兼澘鐏濋埞鎴﹀煡閸℃浠村銈嗘肠閸ヮ煈妫勯悗骞垮劚椤︿即鍩涢幋鐘电＜閻庯綆浜滈惃锛勨偓瑙勬偠閸庣敻寮婚敐鍫㈢杸闁哄啠鍋撻柣銊﹀灴閺岀喖鐛崹顔句患闂佸疇妫勯ˇ鍨叏閳ь剟鏌ｅΟ娲诲晱闁告艾鎳樺缁樻媴閾忕懓绗￠梺鎼炲姂濞佳嗙亱闂佸搫鍟悧濠囧磿婢跺浜滈煫鍥ㄦ尭椤忓瓨绻涢幘鎰佺吋闁哄本娲熷畷鐓庘攽閸パ勵仱缂傚倷鑳舵慨鎶藉础閹惰棄钃熼柨婵嗘啒閺冨牆鐒垫い鎺戝閺呮繃銇勮箛鎾愁伀闁哄棴绠撻弻鐔兼偋閸喓鍑￠梻浣稿船濞差參寮婚敓鐘茬倞闁宠桨鐒﹂悘渚€姊洪崨濠勬噧婵☆偅顨婇崺鐐哄箣閿旇棄浜圭紓鍌欑劍钃遍梺娆惧幖閳规垿鍩ラ崱妞剧凹闂佽崵鍟块弲鐐参涢姀銈嗏拺缂備焦锕╅悞浠嬫煛娴ｅ憡鎲稿瑙勬礃缁轰粙宕ㄦ繝鍕笚闂傚倷鐒﹂娆撳垂閻楀牏顩插Δ锝呭暞閳锋垹绱掔€ｎ偒鍎ラ柛搴㈠姍閺岀喖宕ㄦ繝鍐ㄢ偓鎰版煕閳哄啫浠辨鐐差儔閺佸倿鎸婃径澶嬬潖闂傚倷绀佹竟濠囨偂閸儱纾婚柛娑卞帨閹烘绀嬫い鎺戝€婚惁鍫濃攽閻愯尙澧曢柣蹇旂箞瀵悂鎮㈤崗鑲╁幍缂備礁顑呴悘婵嬪汲闁秵鐓熼柨婵嗘搐閸樺瓨銇勯姀锛勬创闁诡喗绮撳畷鍗炍熺紒妯煎絿闂傚倸鍊烽悞锔锯偓绗涘吘娑欐媴閼叉繃鐩畷鐔碱敍濮樺崬濮︽俊鐐€栧濠氬磻閹剧粯鐓熼柡宓礁浠Δ鐘靛仜閸燁偉鐏冮梺閫炲苯澧撮柛鈹垮劜瀵板嫭绻涢悙顒傗偓璇测攽閻愬弶顥滄繛鎾敱濞煎寮埀顒傛崲濠靛鍋ㄩ梻鍫熺◥缁爼姊虹紒姗嗘當闁硅櫕鍔欏畷姘跺箳閹存梹鐎婚梺瑙勫劤閻ゅ洭骞楅弴銏♀拺闁圭娴风粻鎾淬亜閿旇鐏ｇ紒顔款嚙閳藉鈻庡鍕泿闂備浇顫夊畷妯衡枖濞戞瑧顩风憸蹇曟閹烘挻濯寸紒瀣浜涙俊鐐€ゆ禍婊堝疮鐎涙ü绻嗛柛顐ｆ礀楠炪垺淇婇妶鍛灓濞村吋绻堝缁樻媴鐟欏嫬浠╅梺鍛婃煥缁绘劙鎮鹃悜鑺ヮ棃婵炲顒茬紞渚€鐛崶顒€绾ч悹渚厛閸炴椽姊绘担鍛婃儓闁哥噥鍋婂畷鎰節濮橆厽娅栧┑鐘诧工閸熺娀寮ㄦ禒瀣厓闁芥ê顦伴ˉ婊堟煟韫囧鍔﹂柡灞剧〒閳ь剨缍嗛崑鍕叏瀹ュ鐓欐い鏂垮悑閸嬨儳鈧娲滈崰鏍€佸☉妯锋婵☆垰鍢叉禍楣冩煟閵忕姵鍟為柛瀣у墲缁绘盯宕卞Δ鍐唶濡炪倕娴氭禍鐐垫閹烘鐒垫い鎺戝缁€鍐┿亜閺冨洦顥夊ù鐘叉惈椤啴濡堕崱娆忣潷缂備礁顑嗛崹鐢告箒濡炪倖娲嶉崑鎾绘煛鐏炵晫效濠碉紕鍏橀、娑橆煥閸涱喗顔撴繝鐢靛Х椤ｄ粙宕滃┑瀣畺闁稿瞼鍋涢弰銉╂煃閳轰礁鏆炲┑顖涙綑閵嗘帒顫濋悡搴ｄ画闁轰礁鐗婄换婵堝枈婢跺瞼锛熼梺绋款儐閸ㄥ灝鐣烽幇鏉垮唨妞ゆ劧绲惧▓浼存⒑閸︻厼鍔嬫い銊ユ噽婢规洝銇愰幒鎾跺幗闂佺粯姊婚崢褎绂嶆导瀛樼厽闁哄倹瀵чˉ銏ゆ煛瀹€鈧崰鏍箖濠婂喚娼ㄩ柛鈩冾焽閺嗭箓姊绘担鐟扳枙闁衡偓鏉堚晜鏆滈柨鐔哄Т閽冪喐绻涢幋鐐电叝婵炲矈浜弻鐔烘喆閸曨偄顫屽銈冨劜缁诲牆顫忓ú顏呯劵闁绘劘灏€氭澘顭胯閻°劑濡甸崟顖毼ㄩ柨鏃囨閺嗘姊洪崨濠傜瑲閻㈩垪鈧磭鏆﹀┑鍌氭啞閸嬪嫰鏌ц箛姘兼綈闁搞倕鐭傚缁樼瑹閳ь剟鍩€椤掑倸浠滈柤娲诲灡閺呭爼骞橀鐣屽幗濠电偞鍨靛畷顒勫几閻旇　鍋撻崹顐ｇ凡閻庢矮鍗抽悰顕€宕堕澶嬫櫍闂佺粯鏌ㄦ竟濠冪瑜斿濠氬磼濞嗘帒鍘＄紓渚囧櫘閸ㄥ爼鍨鹃敃鍌氶唶婵犻潧鍟悗娲⒑閸濆嫭宸濋柛瀣姍瀵顓兼径瀣幐闂佺鏈銊ヮ潩閵娾晜鐓涢柍褜鍓氱粋鎺斺偓锝庡亞閸欏棗鈹戦悙鏉戠仸闁挎碍銇勮箛濠冩珔闂囧绻濇繝鍌氭殧闁稿鍨介弻锛勪沪閸撗€濮囩紓浣虹帛缁诲牆鐣峰鈧、鏃堝礋閵婏箑顏梻浣筋嚙濮橈箓锝炴径濞掓椽寮介銈囶槸婵犵數濮存导锝呪槈閵忕姷顦ㄥ銈庡幖椤戝懐绱炴繝鍐╁弿闁逞屽墴閺屽秹鍩℃担鍛婃婵炲濮伴崹铏规崲濠靛牆鏋堟俊顖氭惈閳峰姊洪悜鈺佸⒉婵炶尙鍠曞Λ鐔兼⒑閹勭闁稿鐒︾粋宥咁煥閸曗晙绨婚梺瑙勬緲婢у海绮欓懡銈囩＜闁逞屽墰閳ь剨缍嗛崰妤呮偂濞戞埃鍋撻崗澶婁壕闂侀€炲苯澧寸€规洑鍗冲浠嬵敇閻愮數鏆繝鐢靛仜濡瑩骞栭埡鍛瀬闁糕剝顦鸿ぐ鎺撴櫜闁割偆鍣ユ禒鈺呮⒑鐎圭媭鍤欑紒缁樺笧濡叉劙骞樼拠鑼紲濠电偛妫欓崺鍫澪ｉ鐣岀瘈闁冲皝鍋撻柛鎰靛枛瀵即鎮楃憴鍕闁搞劍瀵ф穱濠囨嚋闂堟稓绐炴繝鐢靛Т閹冲繘骞夋导瀛樷拻濞达綀娅ｇ敮娑㈡煛鐏炶濮傜€规洏鍎抽埀顒婄秵閸犳宕愰崹顔氬綊鎮╁顔煎壉闂佺粯鎸堕崕鐢稿蓟閿熺姴鐐婃い顓熷灦閻ｈ埖绻涚€涙鐭岄柛瀣尵閹广垹鈹戠€ｎ亞鍘遍梺閫炲苯澧寸€规洏鍔戦、妯款槼婵絽顦靛缁樼瑹閳ь剙顭囪鐓ら柕鍫濇礌閸嬫挸顫濋銏犵ギ闂佺粯渚楅崰鏍亽闁诲繐绻戦悧鏇熺閻愵剛绠鹃柟瀵稿剱娴煎嫭绻濇繝鍌氼伀妞も晝鍏橀弻鏇＄疀閺囩倫娑㈡煛閳ь剟鎳為妷锝勭盎闂佸搫鍟崐鍫曞焵椤掆偓椤戝鎮￠鍕垫晢闁稿本绮庨敍婵嬫⒑缁嬫寧婀扮紒瀣灴瀹曨偊宕崟銊︽杸闂佹寧绋戠€氼參寮抽渚囨闁绘劕寮堕崰妯尖偓娈垮枛婢у酣骞戦崟顖椻偓锕傚箣濠靛洦姣岄梻鍌氬€搁崐鐑芥嚄閸洖绠犻柟鍓х帛閸嬨倝鏌曟繛褍鍟悘濠囨倵閸忓浜鹃梺鍛婃处閸嬪嫰宕甸幋锔解拺闁告挻褰冩禍婵堢磼濞差亞鐣虹€殿喓鍔嶇粋鎺斺偓锝庡亞閸樹粙姊鸿ぐ鎺戜喊闁搞劋鍗抽幆鍐洪鍛幍闂佷紮绲介懟顖氭毄缂傚倷娴囨ご鍝ユ暜閿熺姰鈧礁鈻庨幇顕€妾紓浣割儏閻忔繈宕ｆ繝鍥ㄧ厽閹兼番鍊ゅ鎰箾閸欏鑰跨€规洖缍婇獮鎰償濠靛牏鐣鹃梻浣稿悑閹倸顭囪濞嗐垽鎮欓悜妯煎幈濡炪倖鍔х紞鈧瑙劽湁婵犲﹤瀚崝銈夋煏閸℃ê绗掓い顐ｇ箞閺佹劙宕ㄩ鈧ˉ姘舵⒑鐠囨彃顒㈡い鏃€鐗犲畷鎶筋敋閳ь剙鐣烽幎鑺ユ櫜闁告侗鍨卞▓楣冩⒑缂佹ɑ灏紒銊ョ埣瀵劍绂掔€ｎ偆鍘卞銈嗗姦閸嬪嫭绂嶅┑瀣厸濞达綁娼ч埀顒佺箓椤繑绻濆顒傦紲濠电偛妫欑敮鎺楀储閿涘嫮纾藉〒姘搐濞呮﹢鏌涢妸銊︾【闁伙絽鍢查埞鎴炵節閸曨厽婢戞繝鐢靛仦閸ㄥ爼鈥﹂崶顒€钃熺憸宥夊煘閹达附鍋愰悹鍥囧啩绱ｉ梻浣虹帛椤ㄥ牓宕戦悢鐑橆潟闁绘劕鎼崘鈧銈嗗姉閸犲孩绂嶉悙顒夋闁绘劘灏欐禒銏ゆ煕閺冣偓绾板秹濡甸崟顖涙櫆闁割煈鍠栫粊顕€姊虹化鏇熸珕闁烩晩鍨堕悰顔锯偓锝庡枟閺呮粓鏌ｉ敐鍛板妤犵偞顨婂缁樻媴閾忕懓绗″┑顔硷工椤兘鍨鹃敃鍌氶唶闁靛顑呴ˇ閬嶅焵椤掑﹦绉甸柍褜鍏欓崹鍦礊婵犲洤绠栭柍鍝勬媼閺佸﹪鏌ゅù瀣珒缂佽鲸鐟╁缁樻媴閸涘﹥鍎撻梺鍝勭墱閸撶喖骞嗛崟顖ｆ晬闁绘劘灏欓悾娲⒑闂堟稓绠為柛濠冩礋閹苯螖閳ь剟鈥︾捄銊﹀磯濞撴凹鍨伴崜鎶芥偡濠婂嫭绶叉繛宸幖椤繒绱掑Ο璇差€撶紓浣割儐鐎笛囧磹椤栨埃鏀介柨娑樺娴犫晛鈹戦鍝勨偓妤冨垝鐎ｎ亶鍚嬮柛銉ｅ妼绾绢垶姊洪幆褏绠烘い顐㈩槸閳绘捇骞嗚閺€浠嬪箳閹惰棄纾归柡鍥ュ灩缁犵娀鐓崶銊р槈闁告艾缍婇弻娑㈠箛闂堟稒鐏嶉梺缁樻尭閸熸挳寮诲☉妯锋斀闁糕剝顨忔禒濂告⒑閸濆嫷鍎嶉柛濠冪箞瀵鈽夐姀鈥充簻闂佺粯鍨煎Λ鍕嚕閺夊簱鏀芥い鏃傘€嬮崝鐔虹磼椤曞懎鐏︽鐐茬箻瀹曘劑顢涘鍫氭敽闂佽鍑界紞鍡涘磻閸℃瑧鐭撻柣鎴ｅГ閳锋帒霉閿濆嫯顒熼柣鎺楃畺閹鈽夐幒鎾寸彆缂備胶绮粙鎺旀崲濠靛纾兼繝濠傚椤旀洘淇婇悙顏勨偓鏍偋濠婂牆纾绘繛鎴欏灪閻撱儵鏌曢崼婵囶棛缂佽妫濋弻锝夊箛椤栨氨姣㈠┑顕嗙悼閸嬨倝寮诲☉姘ｅ亾閿濆骸浜濈€规洖鐬奸埀顒冾潐濞叉鏁敓鐘茬畺婵炲棙鎸婚崵鎴炪亜閹烘埈妲圭悮銊╂⒒閸屾瑦绁扮€规洜鏁诲畷鏉款吋閸滀焦瀵岄梺鍦劋椤ㄥ棝宕甸崟顖涚厱妞ゆ劧绲剧粈鈧紓浣哄Х婵炩偓闁哄瞼鍠栧畷婊嗩槻闁告棑绠撻弻宥堫檨闁告挶鍔庣划濠氬箻缂堢姷绠氶梺褰掓？缁€渚€鎮″☉妯忓綊鏁愰崟顕呭妳濠德ゅ蔼椤绌辨繝鍥ㄥ€锋い蹇撳閸嬫捇寮介鐐殿唶婵°倧绲介崯顐ょ玻濡ゅ懏鐓欓柣妤€鐗婄欢鏌ユ煟閵堝骸娅嶉柡宀€鍠栭獮鍡氼槻妞わ絽纾惀顏堝矗閵壯呯厯闂佸搫鏈粙鎾寸閿曞倸绀堢憸搴ㄥ闯椤栫偞鈷戠紒瀣硶缁犱即鏌ゅú璇茬仸闁糕晝鍋ら獮瀣晜缂佹ɑ娅撻梻浣虹帛閸旓箓宕滃顑帡宕奸妷锔规嫼闁荤姴娲犻埀顒€纾禒鈺呮煟鎼淬垻鐓柛妤佸▕婵″瓨鎷呯化鏇燁潔闂侀潧绻嗛埀顒佹灱閸嬫捇鎮滈懞銉㈡嫽闂佸壊鍋嗛崰鎾诲Υ閹烘鐓忛柛顐墴濡绢喚绱掔紒妯肩畼闁哥姴锕よ灒婵炶尙绮紞澶愭⒒娴ｈ鍋犻柛鏂款儔瀹曪繝骞庨挊澶岀暰闂佸憡鍔﹂崰妤呭磹婵犳碍鐓㈡俊顖欒濡叉椽鏌ㄥ☉娆戞创婵﹨娅ｉ幉鎾礋椤愩値妲版俊鐐€栧▔锕傚炊瑜忛澶愭⒑閻撳孩鎲搁柛瀣剁稻缁傚秴顭ㄩ崼鐔哄幍闂佺顫夐崝鏍兜妤ｅ啯鐓曢柟鎹愵唺閹查箖鏌＄仦鐣屝ユい褌绶氶弻娑㈠箻鐎靛憡鍣伴梺璇″灠閻倸鐣烽幒妤佸€烽柤鑹板煐閹茬増绻濋悽闈涗沪闁割煈鍨跺畷鐟懊洪鍕紮闂佺粯鍨兼慨銈夋偂閺囩喆浜滄い鎾跺枎閻忋儱霉濠婂嫮鐭嬬紒缁樼洴瀹曠厧鈹戦崼銏犲П婵犳鍠栭敃銊モ枍閿濆鐒垫い鎺嗗亾婵犫偓鏉堛劌鍨旀い鎾跺剱閻掍粙鏌熼幍顔碱暭闁绘挻娲熼弻鏇熺箾閸喖濮㈤梺绯曟櫔缂嶄線寮婚敐鍛闁告鍋為悘宥囩磽娴ｈ櫣甯涚紒璇茬墕閻ｇ兘宕奸弴鐐嶁晝鎲稿澶屽祦闁割偅绺鹃弨浠嬫煟濡櫣浠涢柡鍡忔櫅閳规垿顢欓懞銉ュ攭閻庤娲樺姗€锝炲┑瀣垫晞闁兼亽鍎虫禍鏍⒒娴ｅ憡鎯堟繛灞傚灲瀹曠懓煤椤忓懎浜楀┑鐐叉缁诲牓鍩€椤掍礁绗掓い顐ｇ箞椤㈡宕掑▎鎺擃€楁繝鐢靛У椤旀牠宕伴弽顓炵９鐟滅増甯囬埀顒€鍟存俊鐑藉煛閸屾埃鍋撻悜钘夌骇闁割偆鍠庣粈鍐煃瑜滈崜姘扁偓绗涘洤桅闁告洦鍨伴～鍛存煥濞戞ê顏柛锝勫嵆濮婃椽宕烽褏鍔搁梺鎸庢磸閸庨亶顢氶妷鈺佺妞ゆ帒鍊婚惁鍫ユ⒑缁嬭儻顫﹂柛濠冪墵钘熸繝濠傚缁♀偓闂佹眹鍨藉褍鏆╅梻浣芥〃閻掞箓骞冮崒姘辨殾闁硅揪闄勯崐鐑芥煕濠靛棗顏い鏂挎处缁绘繈鎮介棃娴讹綁鏌よぐ鎺旂暫鐎殿喕鍗虫俊鐑藉煛閸屾粌骞堥梻渚€鈧稑宓嗘繛浣冲洤鍑犳繛鎴炴皑濡垶鏌熼鍡楃灱閸氬姊洪崫鍕伇闁哥姵鐗曢悾宄邦煥閸♀晜鞋闂佹眹鍩勯崹閬嶆儎椤栫偛钃熼柨婵嗩槸缁犲鎮楅棃娑欏暈闁革綆鍙冨娲濞戞瑦鎮欓柣搴㈢濠㈡﹢顢氶敐鍡欘浄閻庯綆鈧厸鏅濋幉鍛婃償閵娿儵妫峰銈嗘磵閸嬫挻鎱ㄦ繝鍐┿仢鐎规洏鍔嶇换婵嬪礃椤忓嫬姹茬紓鍌氬€风粈渚€藝椤栫偞鍋夊┑鍌滎焾閺勩儵鏌嶈閸撴岸濡甸崟顖氱闁糕剝銇炴竟鏇㈡⒒娴ｇ瓔鍤欑紒缁樺灴閹虫繃銈ｉ崘锝傚亾閿曞倸鍨傛い鏂诲劤閸犳挻绂嶉幖浣稿唨鐟滃本绔熼弴鐐╂斀妞ゆ梹鏋绘笟娑㈡煕鐎ｎ亜顏╅柣锝囨暬瀹曞崬鈽夊▎鎴濆箺婵犵數鍋為崹闈涚暦椤掆偓閳诲秴顓奸崶锝呬壕閻熸瑥瀚粈鈧梺缁樼墪閵堟悂濡存担鑲濇梹鎷呴崫銉х嵁闂佽鍑界紞鍡涘磻閸涘瓨鍋熸繝濠傜墛閳锋帡鏌涚仦鍓ф噯闁稿繐鏈妵鍕敇閻愰潧鈪遍梺璇″櫘閸ｏ綁銆侀弴銏℃櫇闁逞屽墰婢规洝銇愰幒鎾跺幐閻庤鎼╅崰鏍偓姘煎弮閹焦鎯旈妸锔规嫽闂佺鏈懝楣冨焵椤掍焦鍊愮€规洘鍔欓獮鏍ㄦ媴閸濄儻绱梻浣哥秺濡法绮堟担鍝勵棜闁荤喖鍋婂〒濠氭倵閿濆簼绨绘い鎺嬪灪閵囧嫰骞囬姣挎捇鏌熸笟鍨妞ゎ偅绮撳畷鍗炍旈埀顒勫煕閹烘鈷戠紓浣姑粭褔鏌￠崪浣镐喊妤犵偛顦甸獮鏍ㄦ媴閸濄儳娼夐梻浣稿閸嬪懐鎹㈤崟顒€顕遍悗锝庡枟閳锋垿鏌熺粙鍨劉缂佲偓閳ь剟姊虹粙鍖℃敾闁诡喖鍊垮鑽も偓锝庡枛閻愬﹥銇勯幒宥堝厡闁告﹩浜濈换婵嬪閿濆棛銆愰梺缁橆殔濡繂鐣峰┑瀣у璺侯儑閸欏棗鈹戦悙鏉戠仸闁荤啙鍥х疇闁告劦鍠楅悡鍐偡濞嗗繐顏╅柣蹇ラ檮椤ㄣ儵鎮欑拠褑鍚梺鍝勬湰缁嬫帞鎹㈠┑瀣闁冲搫鍠氬Σ褰掓煟鎼淬値娼愭繛璇х畵瀹曡娼忛埞鎯т壕濞达絽鍟禍褰掓煃瑜滈崜姘辩矙閹烘鏅梻浣告啞閹搁箖骞婇幘璇茬厴闁硅揪闄勯崐鐑芥煕濞嗗浚妯堟俊顐ゅ仧缁辨挻鎷呯粵瀣濠碘槅鍋呯换鍌烆敋閿濆惟闁挎梻铏庡ù鍕煟鎼搭垳绉甸柛瀣瀹曘垽鎸婃径鍡樻杸闂佸疇妫勫Λ妤呮倶閻樼粯鐓欑痪鏉垮船娴滅偤鏌ｉ妷顔绘捣妞わ箑寮堕妵鍕敇閳╁啰銆婇梺鍦嚀鐎氭澘鐣烽锕€绀嬮柛蹇撴憸绾鹃箖姊?"
        if file_path:
            return (
                f"I am still with you. Re-anchor on `{file_path}`, restate the target behavior, "
                "and tell me the one decision that feels most uncertain so we can reduce it to the next smallest verifiable step."
            )
        return (
            "I am still with you. Re-anchor on the target behavior and tell me the one decision that feels most uncertain "
            "so we can reduce it to the next smallest verifiable step."
        )

    def _visible_empty_reply_guidance(
        self,
        *,
        profile: UserProfile | None = None,
        message: str = "",
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        guided_lane_reply = _guided_domain_empty_reply(
            message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if guided_lane_reply:
            return guided_lane_reply

        if profile is not None:
            scaffold = self._scaffold_reply(
                profile,
                message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            ).strip()
            if scaffold:
                return scaffold

        file_path = current_file.get("path") if current_file else None
        if file_path:
            return _localized_text(
                f"I am still with you. Re-anchor on `{file_path}`, restate the target behavior, and tell me the one decision that feels most uncertain so we can reduce it to the next smallest verifiable step.",
                f"\u6211\u8fd8\u5728\u8ddf\u7740\u4f60\u3002\u5148\u56de\u5230 `{file_path}` \u8fd9\u6761\u94fe\u8def\uff0c\u91cd\u65b0\u786e\u8ba4\u76ee\u6807\u884c\u4e3a\uff0c\u7136\u540e\u544a\u8bc9\u6211\u4f60\u6700\u4e0d\u786e\u5b9a\u7684\u90a3\u4e00\u4e2a\u5224\u65ad\u70b9\uff0c\u6211\u4eec\u628a\u5b83\u538b\u7f29\u6210\u4e00\u4e2a\u6700\u5c0f\u53ef\u9a8c\u8bc1\u52a8\u4f5c\u3002",
                response_language,
            )
        return _localized_text(
            "I am still with you. Re-anchor on the target behavior and tell me the one decision that feels most uncertain so we can reduce it to the next smallest verifiable step.",
            "\u6211\u8fd8\u5728\u8ddf\u7740\u4f60\u3002\u5148\u91cd\u65b0\u786e\u8ba4\u76ee\u6807\u884c\u4e3a\uff0c\u518d\u544a\u8bc9\u6211\u4f60\u73b0\u5728\u6700\u4e0d\u786e\u5b9a\u7684\u4e00\u70b9\uff0c\u6211\u4eec\u628a\u5b83\u538b\u7f29\u6210\u4e00\u4e2a\u6700\u5c0f\u53ef\u9a8c\u8bc1\u52a8\u4f5c\u3002",
            response_language,
        )

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        if not self.has_api_key:
            raise RuntimeError(
                "API key not configured. Please set up your provider API key in settings."
            )
        model = self._resolve_model(model)
        try:
            if self._plain_completion_uses_agent_binding():
                return await self._completion_via_agent_binding(
                    messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            client = self._get_client()
            response, _ = await self._create_chat_completion(
                client=client,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = _openai_chat_response_visible_text(response)
            self._raise_for_provider_html_shell(content)
            return content
        except Exception as exc:
            raise RuntimeError(f"Chat completion failed: {exc}") from exc

    async def chat_completion_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ):
        if not self.has_api_key:
            raise RuntimeError(
                "API key not configured. Please set up your provider API key in settings."
            )
        model = self._resolve_model(model)
        try:
            if self._plain_completion_uses_agent_binding():
                async for chunk in self._completion_stream_via_agent_binding(
                    messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    yield chunk
                return
            client = self._get_client()
            stream, _ = await self._create_chat_completion(
                client=client,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
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

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    visible_chunk = _normalize_stream_chunk(
                        reasoning_filter.push(chunk.choices[0].delta.content)
                    )
                    if visible_chunk:
                        yield visible_chunk
            tail = _normalize_stream_chunk(reasoning_filter.flush())
            if tail:
                yield tail
        except Exception as exc:
            raise RuntimeError(f"Chat completion stream failed: {exc}") from exc

    async def coaching_reply_stream(
        self,
        profile: UserProfile | None,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
    ):
        self.clear_last_reply_state()
        if not self.has_api_key:
            raise RuntimeError(
                "API key not configured. Please set up your provider API key in settings."
            )
        if not profile:
            yield self._onboarding_reply(response_language)
            return
        messages = build_coaching_messages(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            history=history,
        )
        model = self._resolve_model()
        try:
            if self._plain_completion_uses_agent_binding():
                raw_content = ""
                pending_visible = ""
                holdback_chars = 32
                async for chunk in self._completion_stream_via_agent_binding(
                    messages,
                    temperature=0.7,
                    max_tokens=1024,
                ):
                    raw_content += chunk
                    pending_visible += chunk
                    reply_corruption_detail = _mixed_script_reply_corruption_detail(
                        raw_content,
                        message=message,
                        response_language=response_language,
                    )
                    if reply_corruption_detail:
                        self._record_reply_language_corruption(reply_corruption_detail)
                        return
                    if len(pending_visible) > holdback_chars:
                        safe_prefix = pending_visible[:-holdback_chars]
                        pending_visible = pending_visible[-holdback_chars:]
                        if safe_prefix:
                            yield safe_prefix
                reply_corruption_detail = _mixed_script_reply_corruption_detail(
                    raw_content,
                    message=message,
                    response_language=response_language,
                )
                if reply_corruption_detail:
                    self._record_reply_language_corruption(reply_corruption_detail)
                    return
                if pending_visible:
                    yield pending_visible
                final_content = self.finalize_coaching_reply(
                    raw_content,
                    profile=profile,
                    message=message,
                    current_file=current_file,
                    response_language=response_language,
                    answer_mode=answer_mode,
                    coach_context=coach_context,
                )
                if not raw_content and final_content:
                    yield final_content
                    return
                if final_content.startswith(raw_content) and final_content != raw_content:
                    yield final_content[len(raw_content) :]
                return
            client = self._get_client()
            stream, _ = await self._create_chat_completion(
                client=client,
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
                stream=True,
            )
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

            raw_content = ""
            pending_visible = ""
            holdback_chars = 32
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = _normalize_stream_chunk(
                        reasoning_filter.push(chunk.choices[0].delta.content)
                    )
                    if not text:
                        continue
                    raw_content += text
                    pending_visible += text
                    reply_corruption_detail = _mixed_script_reply_corruption_detail(
                        raw_content,
                        message=message,
                        response_language=response_language,
                    )
                    if reply_corruption_detail:
                        self._record_reply_language_corruption(reply_corruption_detail)
                        return
                    if len(pending_visible) > holdback_chars:
                        safe_prefix = pending_visible[:-holdback_chars]
                        pending_visible = pending_visible[-holdback_chars:]
                        if safe_prefix:
                            yield safe_prefix
            tail = _normalize_stream_chunk(reasoning_filter.flush())
            if tail:
                raw_content += tail
                pending_visible += tail
            reply_corruption_detail = _mixed_script_reply_corruption_detail(
                raw_content,
                message=message,
                response_language=response_language,
            )
            if reply_corruption_detail:
                self._record_reply_language_corruption(reply_corruption_detail)
                return
            if pending_visible:
                yield pending_visible
            final_content = self.finalize_coaching_reply(
                raw_content,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
            if not raw_content and final_content:
                yield final_content
                return
            if final_content.startswith(raw_content) and final_content != raw_content:
                yield final_content[len(raw_content) :]
        except Exception as exc:
            category, retryable, status_code, provider_reachable, model_supported = self._classify_error(exc)
            provider_config = self._config or ProviderConfig(
                name="unspecified-provider",
                base_url="",
                api_key_ref="trainer.unspecified",
                model=self._resolve_model(),
            )
            detail = self._detail_from_category(
                category,
                provider=provider_config,
                error=exc,
            )
            self._record_last_reply_failure(
                category=category,
                detail=detail,
                retryable=retryable,
                status_code=status_code,
                provider_reachable=provider_reachable,
                model_supported=model_supported,
                error=exc,
            )
            yield self._error_reply_with_scaffold(
                exc=exc,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )

    # ------------------------------------------------------------------
    # Agent-loop based coaching
    # ------------------------------------------------------------------

    def build_agent_provider(
        self,
        *,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ):
        """Return a (AgentProvider, binding) tuple for this provider instance.

        Imported lazily so the heavy ``agent_binding`` module is only loaded
        when an agent loop turn actually runs.
        """
        from .agent_binding import build_agent_provider_for

        if protocol is None and self._config is not None:
            protocol = getattr(self._config, "protocol", None)
        return build_agent_provider_for(
            self,
            protocol=protocol,
            attachments=attachments,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def coaching_reply_agentic(
        self,
        profile: UserProfile | None,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        max_steps: int = 6,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Drive the coach agent loop and return a structured outcome.

        On any agent error, the result falls back to ``coaching_reply``'s
        text output so callers always have something to show. The dict
        shape is::

            {
              "content": str,           # final assistant text
              "steps": [...],           # AgentStep dicts (best-effort)
              "summary": str | None,
              "next_step": str | None,
              "stop_reason": str,
              "tool_events": [...],     # tool_call+tool_result pairs
              "fell_back": bool,
            }
        """
        self.clear_last_reply_state()
        attachment_delivery = self.describe_attachment_delivery(
            attachments=attachments,
            protocol=protocol,
            use_agent_loop=True,
        )
        provider_attachments = (
            list(attachments or [])
            if bool(attachment_delivery.get("attachments_delivered_to_model"))
            else None
        )
        if not self.has_api_key:
            return {
                "content": self._missing_api_key_reply(response_language),
                "steps": [],
                "summary": None,
                "next_step": None,
                "stop_reason": "missing_api_key",
                "tool_events": [],
                "fell_back": True,
                **attachment_delivery,
            }
        if not profile:
            return {
                "content": self._onboarding_reply(response_language),
                "steps": [],
                "summary": None,
                "next_step": None,
                "stop_reason": "onboarding",
                "tool_events": [],
                "fell_back": True,
                **attachment_delivery,
            }
        from .agent_loop import CoachAgentLoop
        from .tools import ToolContext, build_default_tool_registry

        messages = build_coaching_messages(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            agent_loop_enabled=True,
            history=history,
        )
        provider_obj, binding = self.build_agent_provider(
            attachments=provider_attachments,
            protocol=protocol,
        )
        registry = build_default_tool_registry()
        runtime_obj = (coach_context or {}).get("__runtime__") if coach_context else None
        workspace_id = str((coach_context or {}).get("workspace_id") or "workspace-default")
        session_id = str((coach_context or {}).get("session_id") or "")
        context = ToolContext(
            runtime=runtime_obj,
            workspace_id=workspace_id,
            session_id=session_id or None,
            profile=profile,
            response_language=response_language,
            extra=_build_agent_tool_context_extra(
                coach_context=coach_context,
                attachment_delivery=attachment_delivery,
                answer_mode=answer_mode or profile.answer_policy,
                current_file=current_file,
            ),
        )
        loop = CoachAgentLoop(
            provider=provider_obj,
            registry=registry,
            context=context,
            max_steps=max_steps,
        )
        try:
            result = await loop.run(messages)
        except Exception as exc:
            fallback = await self._llm_reply(
                profile,
                message,
                current_file,
                response_language,
                answer_mode,
                coach_context=coach_context,
                history=history,
            )
            fallback_summary, fallback_next_step = _agentic_fallback_continuity(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            fallback_resume_thread = _agentic_resume_thread_text(
                fallback_summary,
                fallback_next_step,
                response_language=response_language,
            )
            return {
                "content": fallback,
                "steps": [],
                "summary": fallback_summary,
                "next_step": fallback_next_step,
                "stop_reason": f"agent_error: {exc.__class__.__name__}",
                "resume_thread": fallback_resume_thread,
                "tool_events": [],
                "fell_back": True,
                **attachment_delivery,
            }
        fell_back = False
        recovered_stop_reason: str | None = None
        tool_events = _agent_tool_events(result)
        # When the model never produced text (e.g. only tool calls then max_steps)
        # surface a short scaffold so the bubble isn't empty.
        final_text = _agent_result_visible_text(result)
        if (
            not final_text.strip()
            and result.stop_reason == "empty_response"
            and not tool_events
        ):
            try:
                retry_result = await loop.run(
                    _agentic_visible_retry_messages(
                        messages,
                        response_language=response_language,
                    )
                )
            except Exception:
                retry_result = None
            if retry_result is not None:
                retry_text = _agent_result_visible_text(retry_result)
                retry_tool_events = _agent_tool_events(retry_result)
                if _agentic_retry_text_is_usable(retry_text) or retry_tool_events:
                    result = retry_result
                    final_text = retry_text
                    tool_events = retry_tool_events
        if not final_text.strip() and result.stop_reason == "empty_response":
            if not tool_events:
                self.clear_last_reply_state()
                plain_reply = await self._llm_reply(
                    profile,
                    message,
                    current_file,
                    response_language,
                    answer_mode,
                    coach_context=coach_context,
                    history=history,
                )
                plain_failure = self.consume_last_reply_failure()
                plain_override = self.consume_last_reply_override()
                plain_stop_reason = (
                    str(plain_override.get("stop_reason") or "").strip()
                    if isinstance(plain_override, dict)
                    else ""
                )
                if (
                    plain_reply.strip()
                    and plain_failure is None
                    and plain_stop_reason != "empty_response"
                ):
                    final_text = plain_reply
                    result.stop_reason = "completed"
                    result.summary = None
                    result.next_step = None
                    result.resume_thread = None
            if not final_text.strip():
                guided_recovery = _guided_domain_empty_reply_override(
                    message,
                    current_file=current_file,
                    coach_context=coach_context,
                    response_language=response_language,
                )
                final_text = self._visible_empty_reply_guidance(
                    profile=profile,
                    message=message,
                    current_file=current_file,
                    response_language=response_language,
                    answer_mode=answer_mode,
                    coach_context=coach_context,
                )
                if isinstance(guided_recovery, dict) and final_text.strip():
                    recovered_stop_reason = "empty_response"
                    result.stop_reason = "completed"
                    result.summary = guided_recovery.get("summary") or result.summary
                    result.next_step = guided_recovery.get("next_step") or result.next_step
                    result.teaching_note = (
                        guided_recovery.get("teaching_note")
                        or getattr(result, "teaching_note", None)
                    )
                    result.resume_thread = _agentic_resume_thread_text(
                        result.summary,
                        result.next_step,
                        response_language=response_language,
                    )
        if not final_text.strip() and result.summary:
            final_text = result.summary
        if not final_text.strip():
            final_text = self._scaffold_reply(
                profile,
                message,
                current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
        reply_corruption_detail = _mixed_script_reply_corruption_detail(
            final_text,
            message=message,
            response_language=response_language,
        )
        if reply_corruption_detail:
            self._record_reply_language_corruption(reply_corruption_detail)
            recovery_override = _build_language_corruption_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(recovery_override, dict):
                result.summary = str(recovery_override.get("summary") or "").strip() or (
                    self.provider_failure_summary("language_corruption", response_language)
                )
                result.next_step = str(recovery_override.get("next_step") or "").strip() or (
                    self.provider_failure_next_step("language_corruption", response_language)
                )
                result.teaching_note = str(recovery_override.get("teaching_note") or "").strip()
                result.blocker = reply_corruption_detail
                result.stop_reason = "language_corruption_recovered"
                result.resume_thread = str(recovery_override.get("resume_thread") or "").strip() or (
                    _agentic_resume_thread_text(
                        result.summary,
                        result.next_step,
                        response_language=response_language,
                    )
                )
                final_text = str(recovery_override.get("reply") or "").strip() or self.provider_failure_reply(
                    "language_corruption",
                    reply_corruption_detail,
                    response_language,
                )
                fell_back = True
            else:
                result.summary = self.provider_failure_summary(
                    "language_corruption",
                    response_language,
                )
                result.next_step = self.provider_failure_next_step(
                    "language_corruption",
                    response_language,
                )
                result.stop_reason = "language_corruption"
                result.resume_thread = _agentic_resume_thread_text(
                    result.summary,
                    result.next_step,
                    response_language=response_language,
                )
                final_text = self.provider_failure_reply(
                    "language_corruption",
                    reply_corruption_detail,
                    response_language,
                )
        tool_events.extend(
            await _maybe_auto_verify_practice_current_file(
                registry=registry,
                context=context,
                tool_events=tool_events,
                message=message,
                content=final_text,
                current_file=current_file,
                coach_context=coach_context,
            )
        )
        guard = _agentic_practice_completion_guard(
            content=final_text,
            tool_events=tool_events,
            message=message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if guard is not None:
            final_text = guard["content"]
            result.summary = guard["summary"]
            result.next_step = guard["next_step"]
            result.stop_reason = guard["stop_reason"]
        else:
            summary, next_step = _agentic_completion_continuity(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
                content=final_text,
            )
            if not str(result.summary or "").strip():
                result.summary = summary
            if not str(result.next_step or "").strip():
                result.next_step = next_step
        if not str(getattr(result, "resume_thread", "") or "").strip():
            result.resume_thread = _agentic_resume_thread_text(
                result.summary,
                result.next_step,
                response_language=response_language,
            )
        return {
            "content": final_text,
            "steps": [self._step_to_dict(step) for step in result.steps],
            "summary": result.summary,
            "next_step": result.next_step,
            "stop_reason": result.stop_reason,
            "decision": getattr(result, "decision", None),
            "blocker": getattr(result, "blocker", None),
            "teaching_note": getattr(result, "teaching_note", None),
            "resume_thread": getattr(result, "resume_thread", None),
            "confidence": getattr(result, "confidence", None),
            "evidence": getattr(result, "evidence", None),
            "tool_events": tool_events,
            "fell_back": fell_back,
            "recovered_stop_reason": recovered_stop_reason,
            **attachment_delivery,
        }

    async def coaching_reply_agentic_stream(
        self,
        profile: UserProfile | None,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        max_steps: int = 6,
        history: list[dict[str, str]] | None = None,
    ):
        """Yield the agent-loop's typed events (text deltas, tool calls,
        tool results, final, error). Every event is a dict 闂?callers SHOULD
        translate them to SSE frames.
        """
        attachment_delivery = self.describe_attachment_delivery(
            attachments=attachments,
            protocol=protocol,
            use_agent_loop=True,
        )
        provider_attachments = (
            list(attachments or [])
            if bool(attachment_delivery.get("attachments_delivered_to_model"))
            else None
        )
        if not self.has_api_key:
            yield {
                "type": "final",
                "content": self._missing_api_key_reply(response_language),
                "summary": None,
                "next_step": None,
                "stop_reason": "missing_api_key",
                **attachment_delivery,
            }
            return
        if not profile:
            yield {
                "type": "final",
                "content": self._onboarding_reply(response_language),
                "summary": None,
                "next_step": None,
                "stop_reason": "onboarding",
                **attachment_delivery,
            }
            return
        from .agent_loop import CoachAgentLoop
        from .tools import ToolContext, build_default_tool_registry

        messages = build_coaching_messages(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            agent_loop_enabled=True,
            history=history,
        )
        provider_obj, binding = self.build_agent_provider(
            attachments=provider_attachments,
            protocol=protocol,
        )
        registry = build_default_tool_registry()
        runtime_obj = (coach_context or {}).get("__runtime__") if coach_context else None
        workspace_id = str((coach_context or {}).get("workspace_id") or "workspace-default")
        session_id = str((coach_context or {}).get("session_id") or "")
        context = ToolContext(
            runtime=runtime_obj,
            workspace_id=workspace_id,
            session_id=session_id or None,
            profile=profile,
            response_language=response_language,
            extra=_build_agent_tool_context_extra(
                coach_context=coach_context,
                attachment_delivery=attachment_delivery,
                answer_mode=answer_mode or profile.answer_policy,
                current_file=current_file,
            ),
        )
        loop = CoachAgentLoop(
            provider=provider_obj,
            registry=registry,
            context=context,
            max_steps=max_steps,
        )
        try:
            buffered_text = ""
            guard_sensitive_stream = _agentic_practice_verification_context_active(
                message=message,
                current_file=current_file,
                coach_context=coach_context,
            )
            tool_events: list[dict[str, Any]] = []
            async for event in loop.run_stream(messages):
                event_type = str(event.get("type") or "")
                if event_type == "tool_call" or event_type == "tool_result":
                    tool_events.append(dict(event))
                if event_type == "text" and guard_sensitive_stream:
                    buffered_text += str(event.get("delta") or "")
                    continue
                if event_type == "final":
                    if guard_sensitive_stream and not str(event.get("content") or "").strip():
                        event = {**event, "content": buffered_text}
                    event = await self._recover_agentic_stream_final_event(
                        event,
                        profile=profile,
                        message=message,
                        current_file=current_file,
                        response_language=response_language,
                        answer_mode=answer_mode,
                        coach_context=coach_context,
                        history=history,
                        tool_events=tool_events,
                        loop=loop,
                        messages=messages,
                    )
                    auto_events = await _maybe_auto_verify_practice_current_file(
                        registry=registry,
                        context=context,
                        tool_events=tool_events,
                        message=message,
                        content=str(event.get("content") or ""),
                        current_file=current_file,
                        coach_context=coach_context,
                    )
                    for auto_event in auto_events:
                        tool_events.append(auto_event)
                        yield auto_event
                    event = self._visible_agentic_final_event(
                        event,
                        profile=profile,
                        message=message,
                        current_file=current_file,
                        response_language=response_language,
                        answer_mode=answer_mode,
                        coach_context=coach_context,
                        tool_events=tool_events,
                    )
                yield event
        except Exception as exc:
            scaffold = self._error_reply_with_scaffold(
                exc=exc,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
            fallback_summary, fallback_next_step = _agentic_fallback_continuity(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            fallback_resume_thread = _agentic_resume_thread_text(
                fallback_summary,
                fallback_next_step,
                response_language=response_language,
            )
            yield {"type": "error", "detail": str(exc), "category": exc.__class__.__name__}
            yield {
                "type": "final",
                "content": scaffold,
                "summary": fallback_summary,
                "next_step": fallback_next_step,
                "resume_thread": fallback_resume_thread,
                "stop_reason": "agent_error",
                **attachment_delivery,
            }

    async def _recover_agentic_stream_final_event(
        self,
        event: dict[str, Any],
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None,
        response_language: str | None,
        answer_mode: str | None,
        coach_context: dict[str, Any] | None,
        history: list[dict[str, str]] | None,
        tool_events: list[dict[str, Any]],
        loop: Any | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        final_event = dict(event)
        content = _strip_internal_coach_meta(str(final_event.get("content") or ""))
        final_event["content"] = content
        if content.strip() or str(final_event.get("stop_reason") or "").strip() != "empty_response":
            return final_event
        if tool_events:
            return final_event

        if loop is not None and messages is not None:
            try:
                retry_result = await loop.run(
                    _agentic_visible_retry_messages(
                        messages,
                        response_language=response_language,
                    )
                )
            except Exception:
                retry_result = None
            if retry_result is not None:
                retry_event = _agentic_final_event_from_result(retry_result)
                retry_tool_events = _agent_tool_events(retry_result)
                if (
                    _agentic_retry_text_is_usable(str(retry_event.get("content") or ""))
                    or retry_tool_events
                ):
                    tool_events.extend(retry_tool_events)
                    return retry_event

        self.clear_last_reply_state()
        plain_reply = await self._llm_reply(
            profile,
            message,
            current_file,
            response_language,
            answer_mode,
            coach_context=coach_context,
            history=history,
        )
        plain_failure = self.consume_last_reply_failure()
        plain_override = self.consume_last_reply_override()
        plain_stop_reason = (
            str(plain_override.get("stop_reason") or "").strip()
            if isinstance(plain_override, dict)
            else ""
        )
        if (
            plain_reply.strip()
            and plain_failure is None
            and plain_stop_reason != "empty_response"
        ):
            final_event["content"] = plain_reply
            final_event["stop_reason"] = "completed"
            final_event["summary"] = None
            final_event["next_step"] = None
            final_event["resume_thread"] = None
            return final_event
        guided_recovery = _guided_domain_empty_reply_override(
            message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if isinstance(guided_recovery, dict):
            guided_reply = _guided_domain_empty_reply(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if guided_reply.strip():
                summary = guided_recovery.get("summary") or final_event.get("summary")
                next_step = guided_recovery.get("next_step") or final_event.get("next_step")
                final_event["content"] = guided_reply
                final_event["stop_reason"] = "completed"
                final_event["recovered_stop_reason"] = "empty_response"
                final_event["summary"] = summary
                final_event["next_step"] = next_step
                final_event["teaching_note"] = guided_recovery.get("teaching_note")
                final_event["resume_thread"] = _agentic_resume_thread_text(
                    str(summary or "").strip(),
                    str(next_step or "").strip(),
                    response_language=response_language,
                )
        return final_event

    @staticmethod
    def _step_to_dict(step: Any) -> dict[str, Any]:
        return {
            "index": getattr(step, "index", -1),
            "assistant_content": getattr(step, "assistant_content", ""),
            "tool_calls": list(getattr(step, "tool_calls", []) or []),
            "tool_results": list(getattr(step, "tool_results", []) or []),
            "stop_reason": getattr(step, "stop_reason", None),
        }

    def _visible_agentic_final_event(
        self,
        event: dict[str, Any],
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None,
        response_language: str | None,
        answer_mode: str | None,
        coach_context: dict[str, Any] | None,
        tool_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        final_event = dict(event)
        content = _strip_internal_coach_meta(str(final_event.get("content") or ""))
        final_event["content"] = content
        if str(final_event.get("summary") or "").strip():
            final_event["summary"] = _strip_internal_coach_meta(str(final_event.get("summary") or ""))
        if str(final_event.get("next_step") or "").strip():
            final_event["next_step"] = _strip_internal_coach_meta(str(final_event.get("next_step") or ""))
        if str(final_event.get("resume_thread") or "").strip():
            final_event["resume_thread"] = _strip_internal_coach_meta(
                str(final_event.get("resume_thread") or "")
            )
        reply_corruption_detail = _mixed_script_reply_corruption_detail(
            content,
            message=message,
            response_language=response_language,
        )
        if reply_corruption_detail:
            self._record_reply_language_corruption(reply_corruption_detail)
            recovery_override = _build_language_corruption_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(recovery_override, dict):
                summary = str(recovery_override.get("summary") or "").strip() or (
                    self.provider_failure_summary("language_corruption", response_language)
                )
                next_step = str(recovery_override.get("next_step") or "").strip() or (
                    self.provider_failure_next_step("language_corruption", response_language)
                )
                final_event.update(
                    {
                        "content": str(recovery_override.get("reply") or "").strip()
                        or self.provider_failure_reply(
                            "language_corruption",
                            reply_corruption_detail,
                            response_language,
                        ),
                        "summary": summary,
                        "next_step": next_step,
                        "stop_reason": "language_corruption_recovered",
                        "teaching_note": str(recovery_override.get("teaching_note") or "").strip(),
                        "blocker": reply_corruption_detail,
                        "resume_thread": str(recovery_override.get("resume_thread") or "").strip()
                        or _agentic_resume_thread_text(
                            summary,
                            next_step,
                            response_language=response_language,
                        ),
                        "fell_back": True,
                    }
                )
            else:
                summary = self.provider_failure_summary("language_corruption", response_language)
                next_step = self.provider_failure_next_step("language_corruption", response_language)
                final_event.update(
                    {
                        "content": self.provider_failure_reply(
                            "language_corruption",
                            reply_corruption_detail,
                            response_language,
                        ),
                        "summary": summary,
                        "next_step": next_step,
                        "stop_reason": "language_corruption",
                        "resume_thread": _agentic_resume_thread_text(
                            summary,
                            next_step,
                            response_language=response_language,
                        ),
                    }
                )
            return final_event
        guard = _agentic_practice_completion_guard(
            content=content,
            tool_events=tool_events or [],
            message=message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if guard is not None:
            final_event.update(guard)
            resume_thread = _agentic_resume_thread_text(
                final_event.get("summary"),
                final_event.get("next_step"),
                response_language=response_language,
            )
            if resume_thread:
                final_event["resume_thread"] = resume_thread
            return final_event

        summary, next_step = _agentic_completion_continuity(
            message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
            content=content,
        )
        if not str(final_event.get("summary") or "").strip():
            final_event["summary"] = _strip_internal_coach_meta(summary)
        if not str(final_event.get("next_step") or "").strip():
            final_event["next_step"] = _strip_internal_coach_meta(next_step)
        if not str(final_event.get("resume_thread") or "").strip():
            final_event["resume_thread"] = _agentic_resume_thread_text(
                final_event.get("summary"),
                final_event.get("next_step"),
                response_language=response_language,
            )

        if content.strip():
            return final_event

        summary_text = str(final_event.get("summary") or "").strip()
        if summary_text:
            final_event["content"] = summary_text
            return final_event

        final_event["content"] = self._scaffold_reply(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        return final_event


def _build_agent_tool_context_extra(
    *,
    coach_context: dict[str, Any] | None,
    attachment_delivery: dict[str, Any],
    answer_mode: str | None,
    current_file: dict[str, object] | None,
) -> dict[str, Any]:
    normalized_answer_mode = normalize_answer_policy(answer_mode)
    extra: dict[str, Any] = {
        "attachments_will_send": bool(attachment_delivery.get("attachments_delivered_to_model")),
        "answer_mode": normalized_answer_mode,
        "allow_coach_only_tools": normalized_answer_mode in {"guided", "balanced"},
    }
    if not isinstance(coach_context, dict):
        if isinstance(current_file, dict):
            extra["current_file"] = dict(current_file)
        return extra

    if isinstance(current_file, dict):
        extra["current_file"] = dict(current_file)

    explicit_tool_scope = coach_context.get("allow_coach_only_tools")
    if isinstance(explicit_tool_scope, bool):
        extra["allow_coach_only_tools"] = explicit_tool_scope

    def _add_if_present(key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        extra[key] = value

    for key in (
        "scenario",
        "learner_signal",
        "current_focus",
        "summary",
        "continuity_summary",
        "review_queue_summary",
        "next_step_hint",
        "pace_signal",
        "first_turn_priority",
    ):
        _add_if_present(key, coach_context.get(key))

    thread_summary = _compact_text(coach_context.get("thread_summary"), 140)
    thread_next_step = _compact_text(coach_context.get("thread_next_step"), 110)
    resume_hint = _compact_text(coach_context.get("resume_hint"), 160)
    active_thread = coach_context.get("active_thread")
    if isinstance(active_thread, dict):
        if not thread_summary:
            thread_summary = _compact_text(active_thread.get("summary"), 140) or _compact_text(active_thread.get("focus_area"), 140)
        if not thread_next_step:
            thread_next_step = _compact_text(active_thread.get("next_step"), 110)
    if not resume_hint:
        resume_hint_parts: list[str] = []
        if thread_summary:
            resume_hint_parts.append(f"Resume the live thread around {thread_summary}.")
        if thread_next_step:
            resume_hint_parts.append(f"Keep the next move as {thread_next_step}.")
        if isinstance(active_thread, dict):
            blocker = _compact_text(active_thread.get("blocker"), 96)
            verified_result = _compact_text(active_thread.get("verified_result"), 96)
            if blocker:
                resume_hint_parts.append(f"Keep the blocker in view: {blocker}.")
            if verified_result:
                resume_hint_parts.append(f"Build on the verified result: {verified_result}.")
        resume_hint = " ".join(resume_hint_parts).strip()
    _add_if_present("thread_summary", thread_summary)
    _add_if_present("thread_next_step", thread_next_step)
    _add_if_present("resume_hint", resume_hint)

    implementation_guide = coach_context.get("implementation_guide")
    if isinstance(implementation_guide, dict):
        for key in ("current_step", "scope_boundary", "validation_strategy"):
            _add_if_present(f"implementation_{key}", implementation_guide.get(key))

    exercise_prompt = coach_context.get("exercise_prompt")
    if isinstance(exercise_prompt, dict):
        for key in ("prompt", "success_signal", "fallback_step"):
            _add_if_present(f"exercise_{key}", exercise_prompt.get(key))

    active_thread = coach_context.get("active_thread")
    if isinstance(active_thread, dict):
        for key in ("focus_area", "verified_result", "blocker", "next_step"):
            _add_if_present(f"thread_{key}", active_thread.get(key))

    return extra


def _agentic_practice_completion_guard(
    *,
    content: str,
    tool_events: list[dict[str, Any]],
    message: str,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, str] | None:
    if not _agentic_practice_verification_context_active(
        message=message,
        current_file=current_file,
        coach_context=coach_context,
    ):
        return None
    if not _claims_verified_practice_completion(content):
        return None
    verification_result = _current_file_practice_verification_result(tool_events)
    if isinstance(verification_result, dict) and verification_result.get("passed") is True:
        return None

    chinese = _prefers_chinese(response_language)
    if isinstance(verification_result, dict):
        tool_summary = str(verification_result.get("summary") or "").strip()
        tool_next_step = str(verification_result.get("next_step") or "").strip()
        if chinese:
            summary = tool_summary or "\u5f53\u524d\u6587\u4ef6\u7684\u7ec3\u4e60\u9a8c\u8bc1\u8fd8\u6ca1\u901a\u8fc7\u3002"
            next_step = tool_next_step or "\u5148\u6839\u636e\u9a8c\u8bc1\u7ed3\u679c\u4fee\u8865\u5f53\u524d\u6587\u4ef6\uff0c\u7136\u540e\u518d\u9a8c\u8bc1\u4e00\u6b21\u3002"
            content = f"\u6211\u68c0\u67e5\u4e86 IDE \u91cc\u7684\u5f53\u524d\u6587\u4ef6\uff0c\u4f46\u8fd8\u4e0d\u80fd\u628a\u8fd9\u6b21\u52a8\u624b\u7ec3\u4e60\u6807\u8bb0\u4e3a\u901a\u8fc7\u3002\n\n{summary}\n\n{next_step}"
        else:
            summary = tool_summary or "Current-file practice verification did not pass."
            next_step = tool_next_step or "Patch the current file against the verification result, then verify again."
            content = (
                "I checked the active IDE file, but I cannot mark this practice as passed yet.\n\n"
                f"{summary}\n\n{next_step}"
            )
    elif chinese:
        summary = "\u8fd9\u6b21\u7ec3\u4e60\u8fd8\u6ca1\u6709\u53ef\u7528\u7684 current-file verification evidence\u3002"
        next_step = "\u6253\u5f00 implementation file\uff0c\u8fd0\u884c Verify current file\uff0c\u8ba9 Trainer \u68c0\u67e5\u6587\u4ef6\u3001diagnostics \u548c acceptance signals\u3002"
        content = (
            "\u6211\u8fd8\u4e0d\u80fd\u628a\u8fd9\u6b21\u52a8\u624b\u7ec3\u4e60\u6807\u8bb0\u4e3a\u901a\u8fc7\u3002"
            "Trainer \u8fd8\u9700\u8981\u6765\u81ea VS Code \u7684 current-file verification evidence\uff1a"
            "active file\u3001diagnostics \u548c acceptance signals\u3002\n\n"
            f"{next_step}"
        )
    else:
        summary = "Practice is not marked passed yet because current-file verification evidence is missing."
        next_step = "Open the implementation file and run Verify current file so Trainer can check the file, diagnostics, and acceptance signals."
        content = (
            "I cannot mark this hands-on practice as passed yet. The coach still needs current-file "
            "verification evidence from VS Code: the active file, diagnostics, and acceptance signals.\n\n"
            f"{next_step}"
        )
    return {
        "content": content,
        "summary": summary,
        "next_step": next_step,
        "stop_reason": "practice_verification_required",
    }


async def _maybe_auto_verify_practice_current_file(
    *,
    registry: Any,
    context: Any,
    tool_events: list[dict[str, Any]],
    message: str,
    content: str,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if _current_file_practice_verification_result(tool_events) is not None:
        return []
    if not _agentic_practice_verification_context_active(
        message=message,
        current_file=current_file,
        coach_context=coach_context,
    ):
        return []
    if not _practice_verification_requested_or_claimed(message=message, content=content):
        return []
    if not isinstance(current_file, dict):
        return []
    file_content = current_file.get("content") or current_file.get("content_excerpt") or ""
    if not str(file_content).strip():
        return []
    arguments = _practice_verification_arguments(
        current_file=current_file,
        coach_context=coach_context,
    )
    if not arguments.get("acceptance_criteria") and not arguments.get("expected_symbols"):
        return []

    tool_id = "auto_verify_practice_current_file"
    tool_call = {
        "type": "tool_call",
        "id": tool_id,
        "name": "verify_practice_current_file",
        "arguments": arguments,
        "step": "auto",
        "auto": True,
    }
    tool_result = await registry.invoke(context, "verify_practice_current_file", arguments)
    return [
        tool_call,
        {
            "type": "tool_result",
            "id": tool_id,
            "name": "verify_practice_current_file",
            "ok": bool(tool_result.get("ok")) if isinstance(tool_result, dict) else False,
            "result": tool_result,
            "step": "auto",
            "auto": True,
        },
    ]


def _practice_verification_requested_or_claimed(*, message: str, content: str) -> bool:
    combined = f"{message}\n{content}".lower()
    if _claims_verified_practice_completion(content):
        return True
    return any(
        phrase in combined
        for phrase in (
            "can i mark",
            "mark it",
            "mark this",
            "verify",
            "verification",
            "passed",
            "complete",
            "done",
            "review my practice",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棗鏆欏┑鈥炽偢閺屽秷顧侀柛鎾存皑閹广垽宕煎┑鎰婵犵數濮甸懝楣冨础閹惰姤鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú鐔奉潖閾忓湱纾兼俊顖氭惈琚濋梻浣告啞閹歌鐣濋幖浣哥畺闁汇垻顭堢猾宥夋煕椤愩倕鏆遍柟閿嬫そ濮婅櫣娑甸崨顓濇睏闂佺顑嗙粙鎺撶┍婵犲啰闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛濠傜秺瀹曟垿濡疯閸嬫挸鈻撻崹顔界仌濡炪倖娉﹂崶褏鍙€婵犮垼鍩栭崝鏇㈡偂閹达附鐓冮悷娆忓閸斻倕霉濠婂牏鐣洪柡灞诲姂瀵挳鎮欏ù瀣壕闁告縿鍎虫稉宥夋煥濠靛棙顥犵紒鈾€鍋撻梻鍌氬€搁悧濠勭矙閹烘闂ù鐘差儐閻撴稑霉閿濆懏璐″褜鍓欒彁闁搞儜宥堝惈闂佽鍠楅悷鈺呫€侀弮鍫濈闁靛鍎版竟鏇㈡⒑閸︻厼顣兼繝銏★耿閹寧銈ｉ崘鈺冨幗濠碘槅鍨遍娆撳吹濞嗘垹纾藉ù锝呭级濞呭﹦鈧鍠栭悥鐓庣暦閻撳寒娼╂い鎾跺枔瑜板棝鏌ｆ惔銈庢綈婵炲弶鐗曢锝夊礈娴ｇ懓搴婂┑鐐村灟閸ㄥ湱绮婚敐鍡欑闁糕剝顨堢粻鍐裁归悩鍝勪汗缂佽鲸鎸婚幏鍛村传閸曠鍋撻幘鍓佺＝鐎广儱瀚粣鏃傗偓娈垮枛椤兘寮幇顓炵窞濠电姴瀚弶鍛婁繆閻愵亜鈧牠鎮уΔ鈧～婵嬪Ω閵夋劖甯℃慨鈧柕鍫濇閹锋椽姊洪崨濠勨槈闁挎洏鍎甸幃锟犳晲婢跺鍘卞┑掳鍊愰崑鎾绘煕閻旈攱鍋ラ柨?",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡▎鎴犫敍闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼宕滆绾惧ジ鏌ｅΟ鎸庣彧閻忓浚鍙冮弻锝夋晲婢跺鏆犵紓浣芥閺咁偆鍒掑▎鎴炲珰濞ｅ洤宕俊浠嬫煏閸パ冾伃鐎殿噮鍣ｅ畷鍫曗€栭鑺ュ鞍缂佺粯鐩畷銊╊敇閻樻祴鍙烘繝娈垮枛閿曪妇鍒掗鐐茬闁告稑鐡ㄩ幆鐐搭殽閻愯尙姘ㄩ柛瀣尰缁绘繈宕堕妸褍骞堥梻浣筋潐閸庢娊顢氶鐘典笉婵☆垵鍋愮壕鍏笺亜閺冨倹娅曢柟鍐叉处椤ㄣ儵鎮欓弶鎴犵懆闁剧粯鐗犻弻宥堫檨闁告挾鍠庨悾鐑藉Ψ閵婏絼姹楅梺鍦劋閹告悂鍩€椤掆偓閻栧ジ寮婚敐澶婄疀妞ゆ牗绋撻妴鎰版⒑鐎圭媭鍤欑紒缁橈耿瀵鏁撻悩鑼槰闂侀潧臎閸愮偓婢戦梻鍌欑閹碱偊骞婅箛娑欏亗闁跨喓濮撮拑鐔哥箾閹寸們姘ｉ崼銉︾厱婵°倕鍟禒婊呯磼閻樺弶鎯堥柍瑙勫灴閹瑩鎳犻鈧·鈧梻浣虹帛閹告挳鍩€椤掍礁澧繛鍏肩墵閺屟嗙疀閹剧纭€闂佹椿鍘介悷锔炬崲濞戙垹骞㈡俊顖氭惈婵垽姊洪崨濠冩儎闁告挾鍠庨～蹇撁洪鍕炊闂佸憡娲﹂崜娆忊枍閵堝洨纾藉〒姘搐閺嬬喖鏌熼崫銉у笡缂佸矁椴哥换婵嬪炊閵娿儰缂撶紓鍌欑椤戝牆鈻旈弴鈶哄洭寮跺▎鐐瘜闂侀潧鐗嗗Λ娑欐櫠椤掍焦鍙忔俊顖滎焾婵倹銇勯姀锛勬噭缂佺粯绻堝畷鍫曞Ω閵夈垹浜鹃柛顭戝亽濞堜粙鏌ｉ幇顖氱毢濞寸姰鍨介弻娑㈠籍閳ь剙鐣濋幖浣歌摕闁挎繂鎲橀弮鍫濈劦妞ゆ巻鍋撻摶鐐寸節闂堟稒顥犻柡鍡畵閺屾洝绠涚€ｎ亖鍋撻弴銏″€堕柟鎯板Г閻撴瑥螞妫颁浇鍏岄柛鏂跨Ч閹?",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆岸姊婚崒娆掑厡妞ゎ厼鐗忛幃顕€顢曢敃鈧粈澶愬箹濞ｎ剙濡肩紒鐘靛枛閺岀喖姊荤€靛壊妲紓渚囧亜缁夊綊寮诲☉銏╂晝闁挎繂娲ㄩ悾濂告⒑娴兼瑧绋绘俊鐐舵椤繘鎼归崷顓犵厠闂佺硶鍓濋〃鍛搭敂鐎涙绠鹃柛顐ゅ枑椤ュ牓鏌″畝瀣М妤犵偛娲、妤佺節閸涱厽鍎撻梻鍌欑閹碱偊寮甸鈧叅婵☆垰鍚嬪畷鍙夌節闂堟冻鍔熼柣銈傚亾闂備礁鎼ú銊︽叏闂堟稈鏋旈柟闂寸劍閻撶喖骞栧ǎ顒€鐒洪柛鐔风箻閺屾盯鎮╁畷鍥р吂濡炪値鍘煎ú顓㈠垂妤ｅ啫绠涘ù锝呮贡缁嬩焦绻濋悽闈涗粶婵☆垰锕ョ粋宥呪攽鐎ｅ骸顦靛畷濂告偄閾忚鍟庨梻浣烘嚀椤曨參宕戦悩宕囩彾婵☆垱鐪规禍婊堟煥濠靛棙鍣洪柟顖氱墛閵囧嫰顢旈崟顐ｆ婵犵鍓濋崕鑲╃不濞戙垹鍗抽柣妯兼暩瀹曞爼姊婚崒娆戭槮闁硅绻濋妴鍐川閺夋垹鏌堥梺绉嗗嫷娈曢柛瀣ф櫊閺岋綁骞嬮敐鍡╂缂備胶濯寸紞渚€寮婚敐澶婄疀妞ゆ牗姘ㄥВ銏㈢磽娴ｇ懓濮夐柛瀣ㄥ€曢～蹇斻偊鐟併倓姹楅梺鍦劋閸ㄦ娊宕版繝鍥ㄢ拺闁告稑顭懓璺ㄧ磼閻樺磭澧柣锝囧厴閺佹劖寰勬繝鍌濃偓鍨攽閿涘嫬浠х紒顕呭灦瀵剟鍩€椤掑嫭鈷掑ù锝堟鐢稒銇勯鐐村窛闁告帗甯￠、娑橆潩閿濆棭娼旈柣鐔哥矊鐎涒晝绮氭潏銊х瘈闁搞儴鍩栭弲婵嬫⒑閹稿海绠撴繛璇х畵瀹曟娊顢橀姀鈥斥偓鐢告煕椤垵浜濈紒鑸电叀閹顫濋鐔哄嚒闂佷紮绲块崗姗€骞冮姀銏犳瀳閺夊牄鍔嶅▍鍥⒒娴ｈ櫣甯涢柡灞诲姂楠炲鏁撻悩鑼獓?",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃闁硅櫕鎹囬垾鏃堝礃椤忎礁浜鹃柨婵嗙凹缁ㄥジ鏌熼惂鍝ョМ闁哄矉缍侀、姗€鎮欓幖顓燁棧闂備線娼уΛ娆戞暜閹烘缍栨繝闈涱儐閺呮煡鏌涘☉鍗炲妞ゃ儲鑹鹃埞鎴炲箠闁稿﹥顨嗛幈銊╂倻閽樺锛涘┑鐐村灍閹崇偤宕堕浣镐缓缂備礁顑嗙€笛囨倵椤掑嫭鈷戦柣鐔告緲閳锋梻绱掗鍛仸鐎规洘鍨块獮鍥偋閸垹骞堥梻浣哥秺閸嬪﹪宕归幍顔筋潟闁挎洖鍊归悡鐔兼煏韫囧鐏悽顖涚☉鑿愰柛銉戝秷鍚梺璇″枟閻熲晠銆侀弮鍫濈闁靛鍎版竟鏇㈡⒑閸濆嫮鈻夐柛妯圭矙瀹曟垹鈧綆鍋嗙弧鈧繝鐢靛Т閸婄粯鏅堕弴鐘垫／闁告挆鍛缂備胶绮惄顖炵嵁鐎ｎ亖鏋庨煫鍥ㄦ磻閹綁姊绘担瑙勫仩闁告柨鐭傚畷鎰板锤濡も偓閽冪喐绻涢幋鐐电叝婵炲矈浜弻娑㈠箻濡炶浜惧┑鈽嗗亖閸斿秶鎹㈠☉姘ｅ亾濞戞瑯鐒介柣顓烆儑缁辨帡顢欓懞銉ョ３閻庢鍠栭…鐑藉垂妤ｅ啫绠涘ù锝呮啞閸婎垶姊绘担鍛婂暈闁告梹鍨垮畷婵嗙暆閸曘劉鍋撻弽顐熷亾閿濆骸鏋熼柍閿嬪灴濮婂宕奸悢琛″濡炪們鍎抽崑銈夊箖娴犲鏁嶆繛鎴ｉ哺閻や焦绻濈喊澶岀？闁轰浇顕ч悾鐑芥偄绾拌鲸鏅┑顔矫畷顒勭嵁閹扮増鈷掑ù锝勮閻掗箖鏌￠崼顐㈠闁告帗甯炴禒锔剧驳鐎ｎ亝顓块梻渚€娼ц墝闁哄懏绮撻崺娑㈠箣閿旂晫鍘卞┑鐘绘涧濡顢旈锔界厽闊洦绋愰幉楣冩煛鐏炲墽娲撮柟顔规櫅閻ｇ兘宕惰閹风増淇婇妶鍥ラ柛瀣洴瀹曨垶顢曢敂鍏夊亾閿曞倸惟闁宠桨鑳堕ˇ銊╂⒑缂佹ê濮﹂柛鎾寸懅缁辨捇骞樼紒妯锋嫽婵炶揪缍€濞咃綁濡存繝鍥ㄧ厱闁规儳顕粻鐐烘煃閵夘垳鐣电€规洖鐖奸、妤呭焵椤掆偓鏁堥柡灞诲劜閻撳繐顭跨捄鐑橆棡婵炲懎妫濋弻宥夋煥鐎ｎ亞鐟ㄩ梻鍥ь樀閺屻劌鈹戦崱妯烘闂佸摜鍠撻崑銈夊蓟濞戙垺鍋勯柛婵嗗濡叉劙姊洪崫鍕拱闁烩晩鍨伴锝夘敆閸屾稑纾梺闈浤涚仦鑺ユ珨闂備浇顕у锕傦綖婢跺⊕鍝勵潨閳ь剙鐣疯ぐ鎺戦敜婵°倕鍟粊锕€鈹戦埥鍡楃仴闁稿鍔楁竟鏇㈠礂闂傚绠氬銈嗙墱閸嬬偤寮柆宥嗗€垫慨妯挎珪椤ュ鏌嶇憴鍕伌闁诡喗鐟╅幊婊堟濞戞瑩鏁紓鍌氬€搁崐鍝ョ矓椤曗偓瀹曟垿骞橀幇浣瑰瘜闂侀潧鐗嗘鍛婄濠婂嫨浜滈柨鏇炲€瑰☉褔鏌ｉ敐鍥у幋妤犵偛顑夐弫鍌炴寠婢跺鐫忕紓鍌氬€搁崐鐑芥倿閿曞倵鈧箓宕堕鈧崒銊╂⒑椤掆偓缁夌敻鎮″▎鎾寸厾闁革富鍘奸。鑲╂喐閹跺﹤鎳愮壕濂告椤愵偄骞橀柣顓熺懅閳ь剝顫夊ú妯兼崲閸曨垰鐒垫い鎺戯功缁夌敻鏌涢幘瀵搞€掑瑙勬礃缁轰粙宕ㄦ繝鍕箞闂佽绻掗崑鐔煎磻閹剧粯鍎嶉柟杈剧畱閺嬩線鏌涢鐘插姕闁稿﹦鏁婚幃宄扳枎韫囨搩浠剧紓浣插亾闁逞屽墴濮婃椽妫冨☉姘叡濡炪値鍘奸悧鎾汇€佸鑸垫櫜濠㈣泛锕﹂鎺戭渻閵堝棙顥嗘俊顐㈠閸┾偓妞ゆ帒鍊搁崢鎾煙椤旀娼愰柕鍫畵楠炴劖鎯旈璇叉憢闂?",
            "婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚悢铏圭＜闁靛繒濮甸悘宥夋⒑缁嬪潡顎楁い锔诲灦閳ワ箓宕稿Δ浣告疂闂傚倸鐗婄粙鎴︼綖瀹€鈧槐鎾存媴閸濆嫮褰欓梺鎼炲劀閸滀礁鏅ｉ梻浣筋嚙鐎涒晝绮欓幒鏇熸噷闂佽绻愬ù姘跺储婵傚憡绠掓繝鐢靛Т閿曘倝骞婃惔銏㈩洸闁诡垼鐏旀惔銊ョ倞鐟滄繈鐓鈧埞鎴﹀灳瀹曞洤鐓熼悗瑙勬礈閸犳牠銆佸鈧幃娆忣啅椤旈敮鍋撻幘顔解拻闁稿本鐟чˇ锕傛煙鐠囇呯瘈闁诡喚鍏樻俊鐤槼鐎规洖寮堕幈銊ヮ渻鐠囪弓澹曢柣搴㈩問閸犳牠鈥﹂悜钘夌畺闁靛繈鍊栭幆鐐烘煕閿旇寮跨紒杈ㄧ叀濮婄粯绗熼埀顒€顭囪閹广垽骞掗幘鏉戝伎闂佹眹鍨归幉锟犲磹閸撲讲鍋撻獮鍨姎妞わ缚鍗抽崺娑㈠箣閻樼數锛滈柣搴秵娴滅偞绂掗姀掳浜滈柟鍝勵儏閻忣亪鏌曢崶褍顏┑鈩冩倐婵＄兘鏁冮埀顒€鈻撳Δ浣虹瘈缁剧増锚婢ф煡鏌熼崨濠傗枙闁绘侗鍣ｉ獮鎺懳旈埀顒傜不閿濆棎浜滈柟鎹愭硾閺嬪酣鏌涜箛鎿勮含婵﹦绮幏鍛存偡闁箑娈濈紓鍌欐祰椤曆囧磹閸ф宓佸┑鐘插亞閸氬鏌涢埄鍐噮鐟滀即绠栧娲传閸曨剙鍋嶉梺鎼炲妽濡炰粙宕哄☉銏犵闁圭偨鍔岀紞濠囧极閹版澘鐐婇柍鍝勫€归崯鎺楁⒒娴ｈ鍋犻柛濠冩礋瀹曨垶骞橀鑹版憰濠电偞鍨熼幊鍥焵椤掑﹦鐣垫鐐差儏閳规垿宕煎鍕垫晣闂傚倸鍊峰ù鍥敋閺嶎厼绐楁慨妯挎硾绾惧鏌曢崼婵愭Ц闁哄绶氶弻娑㈠箛闂堟稒鐏堥梺缁樺笒閻忔岸濡甸崟顖氱闁瑰瓨绻嶆导宀勬⒑鏉炴壆顦︽い鎴濐樀瀵寮撮悢椋庣獮闂佺硶鍓濊摫闁绘繃姊荤槐鎾存媴閹绘帊澹曢梺璇插嚱缂嶅棝宕戞担鍦洸婵犲﹤鐗婇悡娆撴煙椤栧棗鑻▓鍫曟⒑鐎圭姵顥夋い锔诲灦濠€浣糕攽閻樿宸ラ柣妤€绻橀幃鎯洪鍛幐闁诲繒鍋犻褎淇婃總鍛婄厓閻熸瑥瀚悘瀵糕偓瑙勬礀瀹曨剟鍩ユ径鎰濞达綁鏅叉竟鏇炩攽鎺抽崐鏇㈠箠韫囨稒鍋傞柡鍥╁枍缁诲棙銇勯弽銊х煂閻㈩垱鐩幃妯跨疀閵壯呮殼闂佸搫澶囬埀顒€纾弳鍡涙倵閿濆骸澧伴柨娑氬枛濮婃椽鏌呴悙鑼跺濠⒀冨⒔缁辨挸顓奸崨顕呮＆閻庤娲橀崹鍨暦閸楃倣鐔虹磼濡厧濞囬梻鍌欑婢瑰﹪鎮￠崼銉ョ；闁告稒娼欓惌妤呯叓閸ャ劍灏ㄩ柡鈧禒瀣厽婵☆垵顕х徊濠氭煛閸℃瑥浠遍柡灞炬礋瀹曞爼濡歌閻ゅ嫰姊洪崫鍕効缂佽鲸娲樼粋鎺楁晝閸屾稑娈熼梺闈涱槶閸庢煡鎮炬繝姘拻濞达絿鐡旈崵鍐煕閻樻剚娈滈柟顔惧厴閸╋繝宕ㄩ鐘垫瀮闂備胶绮敋闁诲繑鑹鹃悾閿嬪緞婵炲簱鍋撻幒鎴僵闁绘挸娴锋禒褏绱撴担浠嬪摵婵﹤婀遍幑銏犫攽鐎ｎ偄浠洪梻鍌氱墛閸掆偓婵炴垯鍨洪悡娆戔偓鐟板濠㈡﹢寮抽悢璁垮綊鎮崨顖滄殼闂佽鍠栨晶鑺ョ閿曞倹鍋傞幖绮规閸ゆ瑧绱?",
            "濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮诲☉妯锋婵鐗婇弫楣冩⒑閸涘﹦鎳冪紒缁橈耿瀵鏁愭径濠勵吅濠电姴鐏氶崝鏍礊濡ゅ懏鈷戦梺顐ゅ仜閼活垱鏅堕鈧弻娑欑節閸屾稑浠村Δ鐘靛仦閸旀牜鎹㈠┑瀣妞ゅ繐妫楁鍕⒒娴ｇ鏆遍柟纰卞亰椤㈡牠宕堕埡鍐厠濡炪倖妫冮弫顕€宕戦幘鑸靛枂闁告洦鍓涢敍姗€姊洪崨濠冣拹闁搞劎鏁婚、姘舵晲婢跺﹪鍞堕梺鍝勬川閸嬬喖顢樺ú顏呪拺缂備焦顭囬幊鍐煙閾忣偄濮嶉柣娑卞櫍婵偓闁靛牆妫岄幏濠氭⒑缁嬫寧婀伴柣鐔濆懐鐜婚柡鍐ㄧ墛閻撳啰鎲稿鍫濈婵炴垯鍨圭壕缁樼箾閹存瑥鐏柛銈嗗姈閵囧嫰寮介妸褉濮囧┑鐐叉噽婵炩偓闁哄瞼鍠撶槐鎺楀閻樺磭浜堕梻浣虹帛閹稿鎯勯鐐茬畺婵せ鍋撻柟顔界懇楠炴捇骞掗崱妯虹槺闂傚倷绶氬褍螞濞嗘垶鏆滈柨鐔哄Т閽冪喓鈧箍鍎遍悧婊冾瀶閵娾晜鈷戦柛娑橈攻鐏忣亪鏌涢弬鎸庢崳婵″弶鍔欓幃娆撳传閸曨偉鈧灝鈹戦悙鏉戠仸妞ゎ厼娲弫宥呪槈閵忊檧鎷洪梺鍛婄☉閿曪絿娆㈤柆宥嗙厱婵せ鍋撶紒鐘崇墪椤曪綁骞庨懞銉︽珕闂備焦顑欓崹鐗堢妤ｅ啯鐓曢煫鍥ㄦ惄濡茬霉濠婂牏鐣烘慨濠冩そ瀹曘劍绻濋崘顭戞П闂備礁鎲￠幐濠氭儎椤栨氨鏆﹂柕蹇嬪€曠粻鐟懊归敐鍥ㄥ殌闁逞屽墰閺佸寮诲☉婊呯杸闁瑰灝鍟瑧濠电偛鐡ㄧ划鎾剁不閺嶎厼钃熼柨婵嗘閸庣喐銇勯弽銊х煂閺嶏繝姊绘担鍛婂暈闁圭顭烽幆鍕敍閻愬弶鐎悗骞垮劚椤︿即宕戦崟顖涚厱婵犻潧瀚崝銈嗐亜閺冣偓濞茬喖寮婚敐鍡樺劅闁挎繂妫欏В鍕渻閵堝骸骞栭柣妤佹崌閵嗕線骞樼拠鑼啋闂佸搫鍊堕崕鏌ュ棘閳ь剟姊绘担鍝勪缓闁稿孩娼欓埢宥夊即閵忕姷鐛ュ┑鈽嗗灡濡炲灝鈻撴禒瀣厽闁归偊鍨伴惃铏圭磼閻樺樊鐓奸柡宀€鍠栭、娆戞喆閸曨剛褰囬梻浣哥秺椤ユ挻绻涢埀顒勬煙瀹曞洤鈻堟い銏☆殕瀵板嫭绻濋崘鈺傜帆闂傚倸鍊搁崐鎼佸磹妞嬪海鐭嗗ù锝夋交閼板潡姊洪鈧粔瀵稿閸ф鐓忛柛顐ｇ箥濡叉悂鏌￠崟鈺佸姦闁哄本鐩、鏇㈡晲閸モ晩鍚嬮梻浣虹帛鐢喐鎱ㄩ妶澶婄疄闁靛鍎欓悢绋跨窞缂佸瀵ч崕鎾剁磽娴ｇ懓鍔ょ憸鎵仧閸掓帒鈻庨幘瀹犳憰濠电偞鍨堕惌顔尖柦椤忓牊鐓欓悷娆忓婵洦銇勯妷锔剧疄婵﹥妞介弻鍛存倷閼艰泛顏繝鈷€鍌氬祮闁哄本绋栫粻娑㈠籍閹惧厜鍋撻幐搴闁绘劖褰冮弳锝夋煙椤旂晫鎳囬柟顔界矊铻ｇ紓浣诡焽瑜板洭姊婚崒娆掑厡妞ゎ厼鐗撳鐢割敆娴ｈ　鏀冲┑鐐叉▕娴滄粎绮诲ú顏呯厸闁搞儯鍎遍悘顏堟煃闁垮鐏存慨濠傤煼瀹曞ジ鎮㈠畡鎵槹闂備礁澹婇崑渚€宕曢柆宥嗗仾闁绘劦鍓涚弧鈧繝鐢靛Т閸婄粯鏅堕弴鐘垫／闁诡垎宀€鍚嬮梺鍝勬湰濞茬喎鐣烽悡搴樻斀闁归偊鍘滆濮婅櫣绱掑Ο璇茬缂備胶绮崝娆撳春閻愬搫绠ｉ柨鏃囨閳ь剛鍏橀弻鐔衡偓娑欘焽缁犳捇鏌￠崱娆忎槐闁哄本鐩弫鎰板礋椤撶姷鍘梻?",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁诡垎鍐ｆ寖闂佺娅曢幑鍥灳閺冨牆绀冩い蹇庣娴滈箖鏌ㄥ┑鍡欏嚬缂併劎绮妵鍕箳鐎ｎ亞浠鹃梺闈涙搐鐎氫即鐛崶顒夋晜闁糕剝鐟ч崢顖炴⒒娴ｅ憡鎯堥悶姘煎亰瀹曟繈骞嬮敃鈧粻鏍煏韫囧鈧洘瀵奸悩缁樼厱闁哄洨鍠庨悘鐔兼煕閵娿儺鐓奸柟顖楀亾濡炪倕绻愰悧鍡欑不濮樿鲸鍠愭繝濠傜墛閸嬪倸鈹戦崒姘暈闁绘挻鐩幃姗€鎮欓幓鎺嗘寖闂佸疇妫勯ˇ鐢稿蓟瀹ュ瀵犲鑸瞪戦埢鍫ユ倵鐟欏嫭绌跨紒缁樼箞楠炲啫鈻庨幋鏂夸壕闁汇垹鎲″▍婊冾熆鐟欏嫭绀嬫慨濠傤煼瀹曟帒鈻庨幋顓熜滅紓浣稿⒔閾忓酣宕ｉ崘顔惧祦濠电姴娲ょ粻濠氭煕閹捐尪鍏岄柣鎾愁儔閹嘲顭ㄩ崨顓ф毉闁汇埄鍨辩敮锟犲箯閹达附鍋勯柣鎴灻弸鎴︽⒑閻熼偊鍤熷┑顕€鏀辩粙澶婎吋閸℃瑧顔曢梺鐟邦嚟閸庢垶绗熷☉娆戠閻忓繑鐗楀▍濠囨煛鐏炲墽顬肩紒鐘崇☉椤繈顢栭幐搴ｆ綎缂傚倸鍊风粈渚€藝闁秴绀傛慨妞诲亾鐎殿喖顭烽弫鎰板幢濡搫濡抽梻渚€娼ч悧鍡欌偓娑掓櫇缁辩偤宕煎┑鍐╂杸闂佺粯鍔栬ぐ鍐棯瑜旈弻銊╁即濡櫣浼堝Δ鐘靛仜閸熸挳寮幘缁樺亹闁惧浚鍋呴鐔兼⒒娴ｈ櫣甯涙い顓炵墢娴滄悂顢旈崼婵堫啈闂佸搫娲ㄩ崑鎰板绩娴犲鐓熼柟閭﹀幗缂嶆垿鏌ｈ箛鏇炴灈闁哄本鐩俊鎼佸Ψ閿曚胶顢呯紓鍌欑贰閸犳盯顢氳閸┿儲寰勯幇顒夋綂闂佹寧绋戠€氼剛鏁幆褉鏀介柣妯虹仛閺嗏晛鈹戦纰卞殶闁瑰箍鍨硅灒濞撴凹鍨抽埀顒冨煐閵囧嫰寮村Δ鈧禍楣冩⒑閸濆嫮鐒跨紒韫矙閸╃偤骞嬮敃鈧悙濠囨煃鏉炴媽顔夐柛姘€规穱濠囨倷椤忓嫧鍋撻妶鍡欘洸婵犲﹤鐗嗛悿顕€鎮楀☉娅偐鎹㈤崱娑欑厱妞ゆ劧绲剧粈鈧紒鐐劤閸氬鎹㈠☉銏犵闁绘劕鐏氶崳顕€鎮峰鍕凡婵☆偅绻傞～蹇曠磼濡顎撻梺鎯х箳閹虫挾绮敓鐘斥拺闁革富鍘搁幏锟犳煕鐎ｎ亝顥㈡鐐村灴婵偓闁绘﹩鍋呴弬鈧梻浣虹《濡狙囧疾濞戞ǚ鏋旈柕濞炬櫆閻撶喖鏌ｅΟ鍝勭骇濠㈣泛瀚槐鎺撴媴鐟欏嫮绋囬柛妤呬憾閺屾盯顢曢悩鎻掑闂佺粯鎸哥换姗€鎮￠锕€鐐婇柕濠忓椤︺儵鏌涢悢鍛婂€愭慨濠冩そ瀹曘劍绻濋崘锝嗗闂備礁婀遍…鍫ュ疮閸ф缍栭煫鍥ㄦ媼濞差亶鏁傞柛鏇ㄥ亞閻涒晛鈹戦悩鍨毄濠殿喗鎸冲畷鎰板箹娓氬﹦绋忛柟鍏肩暘閸斿秹鍩涢幋鐘电＜閻庯綆鍋掗崕銉╂煕鎼淬垹濮嶉柡宀€鍠栭幃鐑芥偋閸繃鐏庢俊銈囧Х閸嬫盯宕鐐参ч柨婵嗩槸缁€鍐煃鏉炴媽顔夐柛瀣尰缁绘繂顫濋鐘插箻闂備浇顕栭崢鐣屾暜閹烘绀夋俊銈呮噺閻?",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤濠€閬嶅焵椤掑倹鍤€閻庢凹鍙冨畷宕囧鐎ｃ劋姹楅梺鍦劋閸ㄥ綊宕愰悙宸富闁靛牆妫楃粭鎺撱亜閿斿灝宓嗙€殿喗鐓￠、鏃堝醇閻旇渹鐢绘繝鐢靛Т閿曘倝宕悧鍫熸珡濠电姷鏁告慨顓㈠磻閹剧偨鈧帒顫濋敐鍛婵犳鍠栭敃銊モ枍閿濆洦顫曢柟鐑樺殾閻斿吋鎯為梺顐ｇ〒缁€鍐ㄢ攽閻樻鏆俊鎻掓嚇瀹曟垿宕熼娑樹壕婵鍘ч弸銈夋煕閹烘挸绗氱紒缁樼箓椤繈顢橀悙鐗堢潖缂傚倸鍊搁崐鐑芥倿閿曞倵鈧箓宕堕鈧崒銊╂煟閵忕姵鍟為柍閿嬪灩閻ヮ亪顢橀悙鏉戭€涘┑鐐插悑閸旀瑩寮诲☉銏犵睄闁规儳澧庨弳銈夋倵鐟欏嫭绀嬫繛浣冲洤鐓濋幖娣妼缁犲鏌℃径瀣亶闁稿鎹囧畷褰掝敃閿濆懎浼庢繝娈垮枟椤ㄥ懎螞濡や焦娅犵紓浣姑肩换鍡涙煙缂佹ê绗х紒澶嬫そ閺岋紕浠﹂悙顒傤槹閻庤娲橀崕濂杆囬崣澶堜簻闊浄绲介獮妤併亜閵婏絽鍔﹂柟顔界懇瀵爼骞嬮悙鍓佹濠德板€楁慨鐑藉磻濞戙埄鏁勯柛娑欐綑閻撴﹢鏌熸潏鍓х暠缂佺姵绋掗妵鍕疀閹炬潙娅ｆ繛瀛樼矋缁诲牆顫忔繝姘＜婵﹩鍏橀崑鎾绘倻閼恒儱鈧潡鏌ㄩ弴鐐测偓鍝ョ不閺嶎厽鐓曟い鎰剁稻缁€鈧紓浣插亾濠㈣泛澶囬崑鎾诲礂婢跺﹣澹曢梻浣告啞濞诧箓宕戦崱娑欐櫖婵炲棙鎸婚崑鈩冪節婵犲倹鍣规い锝呫偢閹粙顢涘☉妯碱儌缂備緡鍠栭…鐑藉箖濞嗘挻鍊绘俊顖滃帶鐢儳鈹戦悩鍨毄闁稿鐩幃妯衡攽鐎ｎ亞顦柣搴㈢⊕椤洨绮婚崜褏纾兼俊銈傚亾闁圭⒈鍋呴幈銊╁磼閻愬鍘搁柣蹇曞仜婢ц棄煤閹绢喗鐓曢柍杞扮椤忣厾鈧娲橀敃銏ゅ箖濞嗘搩鏁嗛柛灞剧⊕椤旀梻绱撻崒姘偓鎼佸磹閻戣姤鍤勯柤绋跨仛閸欏繐螖閿濆懎鏋ら柡浣割儑閹叉悂寮崼婵堜紜闂佸搫鍟悧鍡欑矆閸愨斂浜滈柡鍌涘椤秶鎲搁弮鍫濊摕婵炴垶鐭▽顏堟煕閹炬せ鍋撳┑顔兼喘濮婅櫣绱掑Ο鑲╃暫濠电偠灏欓崰搴綖韫囨稒鎯為柛锔诲幘閿涙粌鈹戦埥鍡楃仯缂侇噮鍨跺畷鏇㈠箻閸撲胶锛濇繛杈剧秬濞咃絿鏁☉姘辩＜閻犲洦褰冮埀顒€娼￠妴浣割潩閼稿灚娅滈梺鎼炲劘閸斿矂鎮甸弶搴撴斀闁绘劕鐡ㄧ紞鎴炪亜閹存繃顥㈤柨婵堝仜椤撳吋寰勭€Ｑ勫闂傚倸鍊搁悧濠勭矙閹惧墎涓嶉柛鎰ゴ閺€鑺ャ亜閺冣偓閸庢娊宕㈢€电硶鍋撶憴鍕缂佽鐗撻悰顔碱潨閳ь剟銆佸▎鎴炲枂闁挎繂妫楅褰掓⒒閸屾瑧顦﹂柟璇х磿缁瑩骞嬮敂鑺ユ珖闂侀潧鐗嗗Λ娆撳矗韫囨搩鐔嗛柤鎼佹涧婵牓鏌ｉ幘瀛樼闁诡喗顨婇弫鎰償閳ヨ尙鍑归柣搴ゎ潐濞叉牠鎯岄崒鐐茶摕闁绘梻鈷堥弫瀣煃瑜滈崜娑氬垝婵犳艾鍐€妞ゆ挾鍋熼悾鍝勨攽閻樿宸ラ柣妤€锕畷闈涱吋婢跺鍘繝銏ｆ硾閻楀棝鎮橀鍫熷€?",
        )
    )


def _practice_verification_arguments(
    *,
    current_file: dict[str, object],
    coach_context: dict[str, Any] | None,
) -> dict[str, Any]:
    criteria: list[str] = []
    expected_symbols: list[str] = []

    def add_text(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in criteria:
            criteria.append(text)

    def add_list(value: Any) -> None:
        if not isinstance(value, list):
            return
        for item in value:
            add_text(item)

    def add_symbol(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in expected_symbols:
            expected_symbols.append(text)

    def add_symbol_list(value: Any) -> None:
        if not isinstance(value, list):
            return
        for item in value:
            add_symbol(item)

    def collect_from_record(record: Any) -> None:
        if not isinstance(record, dict):
            return
        add_list(record.get("acceptance_criteria") or record.get("acceptanceCriteria"))
        add_list(record.get("learner_deliverables") or record.get("learnerDeliverables"))
        add_list(record.get("verification_steps") or record.get("verificationSteps"))
        add_list(record.get("self_check") or record.get("selfCheck"))
        add_list(record.get("constraints"))
        for key in (
            "success_signal",
            "successSignal",
            "deliverable",
            "problem_statement",
            "problemStatement",
            "suggested_workspace_action",
            "suggestedWorkspaceAction",
        ):
            add_text(record.get(key))
        add_symbol_list(record.get("expected_symbols") or record.get("expectedSymbols"))
        add_symbol_list(record.get("api_hints") or record.get("apiHints"))

    collect_from_record(current_file)
    if isinstance(coach_context, dict):
        collect_from_record(coach_context.get("exercise_prompt"))
        collect_from_record(coach_context)
        routing = coach_context.get("active_training_card_routing") or coach_context.get("activeTrainingCardRouting")
        if isinstance(routing, dict):
            collect_from_record(routing.get("selected_card") or routing.get("selectedCard"))
        memory = coach_context.get("memory")
        if isinstance(memory, dict):
            routing = memory.get("active_training_card_routing") or memory.get("activeTrainingCardRouting")
            if isinstance(routing, dict):
                collect_from_record(routing.get("selected_card") or routing.get("selectedCard"))
            ledger = memory.get("training_event_ledger") or memory.get("trainingEventLedger")
            if isinstance(ledger, list):
                for item in ledger[-4:]:
                    collect_from_record(item)

    return {
        "acceptance_criteria": criteria[:12],
        "expected_symbols": expected_symbols[:12],
        "max_evidence": 8,
    }


def _agentic_practice_verification_context_active(
    *,
    message: str,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> bool:
    context = extract_coaching_context(message, current_file, coach_context)
    scenario = str(context.get("scenario") or "").strip().lower()
    if isinstance(context.get("exercise_prompt"), dict):
        return True

    coaching_state = context.get("coaching_state")
    if isinstance(coaching_state, dict):
        teaching_mode = str(coaching_state.get("teaching_mode") or "").strip().lower()
        if teaching_mode == "practice":
            return True

    if isinstance(current_file, dict):
        for key in ("evaluation_source", "source", "mode"):
            if str(current_file.get(key) or "").strip().lower() == "training":
                return True

    if scenario in {"task", "next_task", "engineering_challenge"}:
        return _text_has_practice_verification_terms(
            " ".join(
                str(value or "")
                for value in (
                    message,
                    context.get("summary"),
                    context.get("current_focus"),
                    context.get("next_step_hint"),
                )
            )
        )
    return _text_has_practice_verification_terms(message)


def _text_has_practice_verification_terms(text: str) -> bool:
    lowered = text.lower()
    return any(
        term in lowered
        for term in (
            "practice",
            "training card",
            "hands-on",
            "acceptance",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤濠€閬嶅焵椤掑倹鍤€閻庢凹鍙冨畷宕囧鐎ｃ劋姹楅梺鍦劋閸ㄥ綊宕愰悙宸富闁靛牆妫楃粭鎺撱亜閿斿灝宓嗙€殿喗鐓￠、鏃堝醇閻旇渹鐢绘繝鐢靛Т閿曘倝宕幘顔肩煑闁告洦鍨遍悡蹇涙煕閳╁喚娈旈柡鍡到閳规垿鏁嶉崟顒傚姽濡炪倧闄勯幐鎶藉蓟閿濆鏁囬柣鏃傚劋閸ｄ即姊洪崫鍕拱闁烩晩鍨伴锝嗙節濮樺吋鏅ｅ┑鐘诧工閸熺娀宕戦幘璇茬疀闁哄娉曢敍娑㈡⒑鐟欏嫬绀冩い鏇嗗洦鐓ラ柕鍫濇缁诲棝鏌曢崼婵嗩伂妞ゆ柨顦甸弻鐔风暋閻楀牊鍎撳銈庝簻閸熷瓨淇婇崼鏇炲耿婵°倐鍋撴繛鍏煎灴濮婅櫣绮欏▎鎯у壉闂佸湱顭堟晶钘壩ｉ幇鏉跨闁规儳纾粣鐐寸節閻㈤潧孝濡ょ姷顭堥埢鎾绘嚋閻㈢數鐦堥梺闈涢獜缂嶅棗顭囬幇顓犵闁告瑥顦介悞浠嬫煙楠炲灝鐏╅柍瑙勫灴瀹曢亶鍩￠崒姘帪濠碉紕鍋戦崐鏍箰閻愵剚鍙忛柟缁㈠枤瀹撲焦淇婇妶鍛櫤闁抽攱甯掗湁闁挎繂鎳忛幉鍝ョ磼婢跺銇濋柡灞剧〒閳ь剨缍嗘禍鐑界叕椤掑倵鍋撶憴鍕缂侇喖鐭傞敐鐐测攽閸喎纾梺鎯х箰濠€閬嶅汲娴煎瓨鈷掑ù锝囶焾椤ュ繘鏌涚€ｂ晝绐旂€规洘娲熷濠氬Ψ閿曗偓娴?",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤濠€閬嶅焵椤掑倹鍤€閻庢凹鍙冨畷宕囧鐎ｃ劋姹楅梺鍦劋閸ㄥ綊宕愰悙鐑樺仭婵犲﹤鍟扮粻鑽も偓娈垮枟婵炲﹪寮崘顔肩＜婵炴垶鑹鹃獮鍫熶繆閻愵亜鈧倝宕㈡禒瀣瀭闁割煈鍋嗛々鍙夌節闂堟侗鍎愰柣鎾存礃缁绘盯宕卞Δ鍐唺缂備胶濮垫繛濠囧蓟瀹ュ牜妾ㄩ梺鍛婃尰缁诲牓鏁愰悙鏉戠窞濠电偞甯楀钘夘嚕娴犲鈧牠鍩勯崘鈹夸虎闂佽桨绀侀崯鏉戠暦閹烘围闁糕剝蓱閻濇牗绻濋悽闈涗粶妞ゆ洦鍘介幈銊╁箻椤曞懏鏅為梺绯曞墲缁嬫帡宕戦崒鐐寸厪濠㈣泛妫欏▍鍡涙煟閹捐泛鏋涢柡宀嬬節瀹曟帒鈽夊鍡楁疂闂備浇顕栭崹浼存偋韫囨稑鐒垫い鎺嶈兌閳洜绱掔拠鑼妞ゎ偄绻橀幖褰掑捶椤撶姷鍘梻浣稿悑閸撴岸宕归悡搴劷闁割偅娲橀埛鎴︽煕濞戞﹫鏀婚柍閿嬪姍閺屾盯濡搁妷褌铏庡銈嗘穿缁插潡骞忛悩瑁佸湱鈧綆鍋掑鏃堟⒒娓氣偓濞佳呮崲閹烘挻鍙忛柣鎴犵摂閺佸﹪鏌熼悜妯虹亶闁衡偓娴犲绠抽柟鎯版绾惧綊鏌熼悧鍫熺凡缁炬儳顭烽弻鐔煎礈瑜忕敮娑㈡煟閹惧瓨绀嬮柡宀嬬秮瀵潙顫濇鏍ㄐ滃┑鐐茬摠缁牓宕￠幎钘夎摕闁绘梻鈷堥弫濠勭磽閸屾氨鎽犻柛銊ョ秺楠炴垿濮€閻橆偅鏂€闁诲函缍嗘禍鐐哄磹閻愮儤鈷戦梻鍫熶緱閻掗箖鏌涙惔顔兼珝鐎规洘鍨块獮妯肩磼濡桨缂撻梻浣告啞缁嬫垿鏁冮敃鍌氬偍闂侇剙绉甸ˉ濠冦亜閹扳晛鐏璺哄閺岀喓浜搁弽銊︾彅闁告浜槐鎺斺偓锝庡亾缁扁晠鏌ｉ悢鐓庝喊闁绘挶鍎甸弻娑㈩敃閻樿尙浼勯梺鍝勬－閸嬪嫰鍩為幋锔绘晩缁绢參鏀遍弫鎯р攽閿涘嫬浠╂俊顐㈠閹箖鎮滈挊澹┾晠鏌ㄩ弬鍨挃闁伙箑鐗撳娲川婵犲倸袝闂佺粯鎸搁悧鍡楀祫闂備緡鍓欑粔鐢稿煕閹烘嚚褰掓晲閸曨噮鍔呴梺缁樺笧閸嬫捇濡甸崟顖氱婵犻潧娲ゅ▍锝夋煣閼姐倕浠︾紒缁樼箞濡啫鈽夐崡鐐插闁?",
            "婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚悢铏圭＜闁靛繒濮甸悘宥夋⒑缁嬪潡顎楁い锔诲灦閳ワ箓宕稿Δ浣告疂闂傚倸鐗婄粙鎴︼綖瀹€鈧槐鎾存媴閸濆嫮褰欓梺鎼炲劀閸滀礁鏅ｉ梻浣筋嚙鐎涒晝绮欓幒鏇熸噷闂佽绻愬ù姘跺储婵傚憡绠掓繝鐢靛Т閿曘倝骞婃惔銏㈩洸闁诡垼鐏旀惔銊ョ倞鐟滄繈鐓鈧埞鎴﹀灳瀹曞洤鐓熼悗瑙勬礈閸犳牠銆佸鈧幃娆忣啅椤旈敮鍋撻幘顔解拻闁稿本鐟чˇ锕傛煙鐠囇呯瘈闁诡喚鍏樻俊鐤槼鐎规洖寮堕幈銊ヮ渻鐠囪弓澹曢柣搴㈩問閸犳牠鈥﹂悜钘夌畺闁靛繈鍊栭幆鐐烘煕閿旇寮跨紒杈ㄧ叀濮婄粯绗熼埀顒€顭囪閹广垽骞掗幘鏉戝伎闂佹眹鍨归幉锟犲磹閸洘鐓曟い鎰Т閸旀粓鏌ｉ幘璺烘灈妤犵偞鐗曡彁妞ゆ巻鍋撻柣蹇撳船椤法鎲撮崟鍡樺灴婵＄敻宕熼娑欐珕闂佸壊鐓堥崰鏍矈椤旂晫绡€缁炬澘顦辩壕鍧楁煛娴ｇ瓔鍤欓柣锝囧厴閹垻鍠婃潏銊︽珫婵犳鍠楅敃銏㈡兜閹间礁鑸规繛宸簼閳锋帒霉閿濆洤鍔嬮柛銈傚亾闂備礁顓介弶鍨瀷闂佺懓绠嶉崹褰掝敇婵傜骞㈡繛鍡樕戠粊顐⑩攽閻樼粯娑ч柛濠冩倐楠炲鏁撻悩鑼幈?",
        )
    )


def _claims_verified_practice_completion(content: str) -> bool:
    lowered = content.lower()
    if any(
        phrase in lowered
        for phrase in (
            "not passed",
            "did not pass",
            "does not pass",
            "not verified",
            "cannot mark",
            "can't mark",
            "needs review",
            "need current-file",
            "needs current-file",
            "missing current-file",
            "\u8fd8\u6ca1\u901a\u8fc7",
            "\u4e0d\u80fd\u6807\u8bb0\u4e3a\u901a\u8fc7",
            "\u7f3a\u5c11 current-file",
            "verification evidence",
        )
    ):
        return False
    return any(
        phrase in lowered
        for phrase in (
            "practice passed",
            "you passed",
            "verification passed",
            "verified",
            "this passes",
            "meets the acceptance",
            "mark it complete",
            "mark this complete",
            "ready to mark complete",
            "passed the practice",
            "\u5df2\u901a\u8fc7",
            "\u9a8c\u8bc1\u5df2\u901a\u8fc7",
            "\u53ef\u4ee5\u6807\u8bb0\u5b8c\u6210",
        )
    )

def _has_passed_current_file_practice_verification(tool_events: list[dict[str, Any]]) -> bool:
    result = _current_file_practice_verification_result(tool_events)
    return isinstance(result, dict) and result.get("passed") is True


def _current_file_practice_verification_result(tool_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in tool_events:
        if str(event.get("type") or "") != "tool_result":
            continue
        if str(event.get("name") or "") != "verify_practice_current_file":
            continue
        result = event.get("result")
        if isinstance(result, dict):
            return result
    return None


def _agentic_fallback_continuity(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> tuple[str, str]:
    context = extract_coaching_context(message, current_file, coach_context)
    chinese = _prefers_chinese(response_language)
    summary = str(
        context.get("thread_summary")
        or context.get("summary")
        or context.get("current_focus")
        or context.get("continuity_summary")
        or context.get("review_queue_summary")
        or ""
    ).strip()
    if not summary:
        summary = (
            "This turn needs a fresh provider retry, but the same thread can continue."
            if not chinese
            else "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁诡垎鍐ｆ寖闂佺娅曢幑鍥灳閺冨牆绀冩い蹇庣娴滈箖鏌ㄥ┑鍡欏嚬缂併劎绮妵鍕箳鐎ｎ亞浠鹃梺闈涙搐鐎氫即鐛崶顒夋晜闁糕剝鐟ч崢顖炴⒒娴ｅ憡鎯堥悶姘煎亰瀹曟繈骞嬮敃鈧粻鏍煏韫囧鈧洘瀵奸悩缁樼厱闁哄洨鍠庨悘鐔兼煕閵娿儺鐓奸柟顖楀亾濡炪倕绻愰悧鍡欑不濮樿鲸鍠愭繝濠傜墛閸嬪倸鈹戦崒姘暈闁绘挻鐩幃姗€鎮欓幓鎺嗘寖闂佸疇妫勯ˇ鐢稿蓟瀹ュ瀵犲鑸瞪戠瑧闂佸彞绱紞渚€寮诲☉婊呯杸闁规崘娅曢崐顖炴⒑閸濄儱校闁绘濮撮～蹇曠磼濡顎撴繛鎾村嚬閸ㄦ娊宕濈粙娆炬富闁靛牆妫楅悘锕傛煕閵娿儳绉烘鐐村灴婵偓闁绘﹩鍋呴弬鈧梺璇插嚱缂嶅棙绂嶉敐澶婄闁哄洢鍨洪埛鎴︽煕濠靛棗顏柛灞诲姂閺屾盯濡搁妷褏楔闂佸搫鑻澶婄暦閸洖惟鐟滃繘鎯侀崼銉︹拻闁稿本姘ㄦ晶娑氱磼鐎ｎ偄娴鐐寸墵楠炲洭顢欓崜褝绱查梻浣哥秺閸嬪﹪宕㈤幆顬¤櫣鈧稒蓱閸欏繐鈹戦悩鎻掓殲闁靛洦绻勯埀顒冾潐濞插繘宕濆鍥ㄥ床婵犻潧娲﹂崕鐔兼煏韫囧鐏繛鍫ョ畺濮婅櫣鎷犻弻銉偓妤呮煕濡崵鐭掔€规洘鍨块獮妯肩磼濡厧骞嶉梻鍌氬€搁崐鎼侇敋椤撯懞鍥晜閸撗咃紲闂佺粯锚绾绢厽鏅堕鈧彁闁搞儜宥堝惈婵犵鈧磭鍩ｇ€规洘甯掗～婵嬵敃閵忊晜顥￠梻鍌氬€搁崐椋庣矆娓氣偓閹潡宕堕‖顒佺洴瀹曠喖顢涢埀顒勫炊椤掑鏅梺缁樺姌鐏忔瑩宕㈠ú顏呭€垫鐐茬仢閸旀碍銇勯敂鍨祮妤犵偛妫濋幃娆徢庨璺ㄧ泿闂備浇顫夋竟瀣疾濞戙垺鍊舵い鏃€绁硅ぐ鎺撳亹闁告繂瀚Ч妤冪磽娴ｄ粙鍝洪柟绋款煼楠炲繘宕ㄩ弶鎴狀吅闂佸湱鍎ら崹鍫曞磿閹剧粯鈷掑ù锝勮閻掔偓銇勯幋婵嗘殻鐎规洘鍔曢埞鎴犫偓锝庡亜娴犳帒顪冮妶鍡樼叆婵℃彃鐗撻幃銏ゆ偂鎼达紕鐛╅梻鍌氬€搁悧濠囨儎椤栫偛鐭楅柛鏇ㄥ厵娴滄粓鏌曡箛銉х？濠⒀囦憾閺岀喖鎮烽弶娆句純婵犵鍓濋悺鏇⑺囬幎鑺ョ厸闁告侗鍋勬慨鍌涙叏婵犲偆鐓肩€规洘甯掗～婵嬵敄閽樺澹曢梺褰掓？鐠佹煡鍩€椤掑﹦鐣垫い銏☆殜瀹曠喖顢曢妶蹇曞耿闂傚倷绀侀幉鈥趁洪敃鍌氱９閻庯綆鈧垺妞介、鏃堝川椤旂晫褰囬梻鍌欒兌椤牓寮甸鈧～婵嬪Ω閳哄﹥鏅╅梺鎼炲労閸撴岸鍩涢幋鐘电＝濞达絽顫栭鍛弿闁挎洖鍊归悡鏇㈡煙閸撗屾濠㈣锕㈤弻宥囨嫚閼碱儷褔鏌熼瑙勬珔闁伙絿鍏樺畷鍫曞煛婵犲倹娅楅梻鍌氬€烽懗鍫曞箠閹炬椿鏁嬫い鎾卞灩绾惧鏌熼柇锕€鍔︽繛鎴欏灩鎯熼悷婊冮叄瀹曚即骞囬悧鍫㈠幗濠德板€愰崑鎾绘煟濡も偓濡稓鍒掗鐑嗘僵闁煎摜鏁搁崢閬嶆煟鎼搭垳绉甸柛瀣閹便劍寰勫畝鈧壕濂稿级閸稑濡肩紒妤佸浮閺屽秹鎸婃径妯恍﹀銈庡亝缁诲牆鐣峰Δ鍛闁稿繐鍚嬮澶愭⒒閸屾艾鈧娆㈠璺虹劦妞ゆ帒鍊告禒婊堟煠濞茶鐏￠柡鍛埣椤㈡瑩鎮惧畝鈧鏇犵磼缂併垹寮い銉︽尵瀵囧焵椤掑嫭鍊垫繛鍫濈仢閺嬫稒銇勯鐘插幋妤犵偛鍟存慨鈧柕蹇曞У閻庢娊鏌℃径濠勫闁告柨绉撮埢宥夊箻缂佹ǚ鎷绘繛杈剧悼閻℃棃宕甸崘顔界厱闁靛鍎甸崣鍕偓瑙勬礃閿曘垺淇婂宀婃闂佸憡鑹鹃幊妯侯潖缂佹ɑ濯寸紒娑橆儏濞堫參鏌ｆ惔銏⑩枔闁哄懐濞€閵嗕礁鈻庨幘鍐插敤濡炪倖鎸鹃崑鐔兼偘閵夈儮鏀介幒鎶藉磹閹版澘纾婚柟鐐暘娴滄粍銇勯幘璺轰沪闁瑰吋鍔欓弻宥囨嫚閺屻儱寮板Δ鐘靛仦閻熲晛鐣烽悢纰辨晣闁绘﹩鍋呴敍鍫熺節閻㈤潧啸闁轰礁鎲＄换娑㈠焵椤掍胶绠惧ù锝呭暱閸樻儳煤椤忓懏娅嗛梺鍛婃寙閸滀焦笑闂傚倷鐒﹂幃鍫曞磿濞差亜绀堟慨妯垮煐閸嬪倿鏌涢幇闈涙灍闁绘挻娲樼换婵嬫濞戞瑯妫炲銈呯箚閺呯娀寮婚敓鐘插耿婵☆垰鍚嬮崳鏉课旈悩闈涗沪闁绘濮撮锝夊醇閺囩偟顓哄銈嗙墬缁诲倿骞嗛崼鐔虹瘈婵炲牆鐏濋弸娑㈡煥閺囨ê鈧繈鍨鹃敃鈧悾锟犲箥椤旇姤顔曢梻浣告贡閸庛倝宕归悢鐓庡嚑閹兼番鍔嶉悡娆撴倵閻㈡鐒鹃崯鎼佹倵鐟欏嫭绀€鐎殿喖澧庨幑銏犫攽鐎ｎ偄浠洪梻鍌氱墛缁嬫劙宕Δ浣虹瘈闁靛繈鍨洪崵鈧梺缁橆殔濡繈骞冩ィ鍐╁€婚柤鎭掑労濡啫鈹戦悙鏉戠仴鐎规洦鍓欓埢鎾活敃閿濆洨鐦堥梺姹囧灲濞佳冪摥闂備礁鎽滈崰鍡涘礉閹存繄鏆﹂柟杈剧畱瀹告繈鎮楀☉娆樼劷闁告﹢浜跺铏规喆閸曨偒妫庨梺鍝勬噺缁嬫帗绌辨繝鍥ч敜婵°倓鑳堕崢浠嬫⒑閹稿海绠撴俊顐ｇ懇婵￠潧鈹戦崶銊ュ伎婵犵數濮撮幊蹇涱敂閻樼數纾兼い鏃傛櫕閹冲洦顨ラ悙鏉戝闁诡垱妫冩慨鈧柍銉﹀墯娴煎棝姊婚崒姘偓椋庣矆娓氣偓楠炲鏁撻悩鎻掔€梺姹囧灮閺佸摜绮堟繝鍌楁斀闁绘ɑ褰冮埀顒€顭峰鎶芥晝閸屾稓鍘介梺闈涚箞閸╁嫰鎮炴ィ鍐╃厱婵°倓绀侀埢鏇㈡煛瀹€瀣М鐎殿噮鍣ｅ畷鎺戭煥閸涱垱顫岀紓鍌氬€烽梽宥夊礉瀹€鍕ㄢ偓锕€鐣￠柇锔界稁濠电偛妯婃禍婊堝箲閼哥偣浜滈柟鎹愭硾娴犳粌鈹戦埄鍐┿仢婵﹥妞介獮鏍倷閹绘帩鐎烽梻浣芥〃缁€渚€鈥﹂悜钘壩ュ〒姘ｅ亾鐎殿噮鍣ｅ畷鐓庘攽閸繂绠伴梻鍌欑閹诧繝宕濋敂鐣岊洸闁绘劗鍎ら弲顒佺節婵犲倻澧涢柍閿嬪灩缁辨挻鎷呯拠锛勫姺闂佽褰冨锟犲蓟濞戞埃鍋撻敐搴′簼鐎规洖鐭傞弻锛勪沪閸撗勫垱婵犵鍓濋幃鍌炲极閸愵喖鐒垫い鎺戝閻撴繈鏌￠崶銉ョ仾闁绘挻娲熼弻宥囨喆閸曨偄濮㈡繛瀛樼矌閸嬫挻绌辨繝鍥ㄥ€锋い蹇撳閸嬫捇寮借閸熷懎鈹戦悩瀹犲缁炬儳顭烽弻鐔煎礈瑜忕敮娑㈡煟閹惧瓨绀冨ǎ鍥э躬椤㈡稑鈹戦崱妤佸劒闂備焦妞块崢鐣屾暜閻愬搫鐒垫い鎺戝枤濞兼劖绻涢崣澶涜€跨€规洖缍婂畷绋课旈崘銊с偊婵犵妲呴崹鐢稿磻閹邦喖顥氶柛蹇涙？缁诲棙銇勯弽銊х煀閻㈩垵鍩栭〃銉╂倷閼碱剙鈪靛┑顔硷功缁垶骞忛崨顔剧懝妞ゆ牗绋掗弳鐐烘⒒娴ｈ櫣銆婇柡鍛☉鐓ゆい鎾跺仧閺嗭附绻濋棃娑欙紞闁告艾顑夐弻娑樷槈閸欐鍑归梺璇插濡炶棄顫忓ú顏勫窛濠电姴瀚уΣ鍫ユ⒑鐎癸附婢樻慨鍌炴煙?provider闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘辨繝鐢靛Т閸婂綊宕戦妷鈺傜厸閻忕偠顕ф慨鍌溾偓娈垮櫘閸ｏ絽鐣锋總鍛婂亜闁告稑顭崬鍫曟⒒閸屾瑨鍏屾い顓炵墦椤㈡牠宕卞☉妯碱唶闂佸憡鎸嗛崘銊т喊婵＄偑鍊栭幐楣冨磻閹邦儵锝夊醇閻斿墎绠氬銈嗙墬缁诲秹宕靛▎鎰闁告稑娲ゅú锕傚煕閹寸偟绠鹃柤濂割杺閸ゆ瑦顨ラ悙鎼疁闁哄矉缍侀幃銏ゅ矗婢跺褰嬮柣搴㈩問閸犳牠鈥﹂悜钘夌畺闁靛繈鍨洪崑姗€鏌嶉妷銉ュ笭濠㈣娲熷鍝勑ч崶褏浠惧銈嗘⒐閻楃娀骞冮悙鍝勭畾妞ゎ兘鈧磭绉洪柟顔规櫅閳诲氦绠涢弬娆炬П闂備焦濞婇弨杈╂暜閿熺姴钃熸繛鎴欏灩閸楁娊鏌曟繛鍨姍缂併劏顕ч—鍐Χ閸涱喚顩伴梺鍛婄懃閸熸潙顕ｆ繝姘伋鐎规洖娲﹀▓鏇㈡煟鎼搭垳绉甸柛鎾寸洴閹線宕奸妷锕€鈧敻鎮峰▎蹇擃仾缂佲偓閸愵喗鐓ラ柡鍥悘顏勄庨崶褝韬鐐寸墬閹峰懘鎳栧┑鍕闁哄本娲濈粻娑㈠即閻愭劏鈧剚鐔嗛悷娆忓缁€瀣叏婵犲啯銇濈€规洏鍔嶇换婵嬪礋椤撶姷鐛ラ梻鍌欒兌椤牏鈧稈鏅犻幃锟犳晸閻橆喒鍋撴笟鈧鎾偄娓氼垱绁梺璇插嚱缂嶅棝宕戦崱娑樺偍妞ゅ繐鐗婇埛鎴︽煕閹炬潙绲诲ù婊勭箘缁辨帞鎷犻幓鎺撴閻庤娲﹂崹鍫曠嵁閹烘嚦鏃€鎷呴崫鍕闂傚倷绀侀幉锟犲礉閹达箑绀夐幖娣灪濞呯姵绻涢幋娆忕仾闁绘挻鐩弻娑樷槈閸楃偞鐏撻梺鍛婄憿閸嬫捇姊绘担鍛婃儓闁哄牜鍓涚划娆撳箣閿曗偓閻撯€愁熆閼搁潧濮囩痪顓涘亾闂備胶绮崝妯间焊濞嗘搩鏁婇柟瀵稿仧缁♀偓闂佹眹鍨藉褎绂掑鍫熺厽婵°倓鑳堕惌鎺斺偓瑙勬穿缂嶄礁鐣峰鈧、娆撴嚌閻楀牊鍟洪梻鍌欑劍鐎笛呮崲閸岀倛鍥ㄥ閺夋垹锛涢梺鍛婃处閸ㄩ亶鎮￠弴鐔虹瘈闂傚牊绋戦鈺呮煕閺冣偓缁捇寮诲☉銏犖ч柛娑卞幐閸嬫捇鎳￠妶鍡╂綗闂佽鍎抽悺銊﹀垔閹绢喗鐓曟繝闈涙閻濇棃鏌ㄥ┑鍡╂Ч闁绘挻鐟╅弻锝夋偄閸濆嫷鏆梺鍝ュУ閿曘垽寮婚敐鍛闁告鍋為悵婵嬫倵鐟欏嫭绀冮柨鏇樺灲閸ㄩ箖鏁冮崒姘鳖吅闂佺粯鍔樼亸娆戞閿曞倹鈷掗柛灞剧懅缁愭棃鏌嶈閸撴盯宕戝☉銏″殣妞ゆ牗绋掑▍鐘绘倵濞戞瑱渚涙繛鍫滅矙閺岋綁骞囬鐐电シ闂佸搫妫欓悷鈺呭蓟瀹ュ洦瀚氶柡灞诲劚瀵澘螖閻橀潧浠滄い鎴濐樀楠炲啫鈻庨幘鏉戞濡炪倖甯掗敃锔炬兜閳ь剟姊婚崒姘偓椋庣矆娓氣偓楠炴牠顢曚綅閸ヮ剚鐒肩€广儱鎳愰敍娑㈡⒑缂佹ɑ鐓ラ柟娴嬧偓鏂ユ瀺闁绘ê鍘栫换鍡涙煏閸繃鍣洪柛锝嗘そ閺屾稒鎯旈姀鈥崇３闂佺粯鎼╅崑濠傜暦閸洖惟闁挎梹鍎冲鎵磽閸屾瑦绁版い鏇嗗吘娑樷攽鐎ｎ亣鎽曢梺鎸庣箓椤︻垳绮诲☉銏＄厱闊洦鎸婚幉鎼佹煟閳轰線鍙勬慨濠冩そ閺屽懘鎮欓懠璺侯伃婵犫拃灞界仭缂佺粯鐩畷锝嗗緞瀹€鈧悡澶娢旈悩闈涗沪闁搞劍瀵ч幈銊╁焵椤掑嫭鐓熸俊顖濆吹婢ь剚鎱ㄦ繝鍌滅Ш妤犵偛绻樺畷銊╁级閹寸媭妲梻浣告啞缁哄潡宕曢幎鑺ュ亗濠㈣埖鍔栭埛鎺楁煕鐏炲墽鎳呮い锔煎缁辨挸顓奸崪鍐ㄤ紣闁捐崵鍋ら幃褰掑箒閹烘垵顬嬮梺娲诲幖濡婀侀梺鎸庣箓閻楀﹪顢旈悩娴嬫闁规儳纾晥闂佸搫鐭夌紞渚€鐛崶顒夋晩闁绘挸楠搁‖鍡涙⒒娴ｈ櫣甯涢柟绋挎憸閹广垽骞囬弶璺ㄥ幋闂佺鎻梽鍕磻閹扮増鐓犵痪鏉垮船婢х増銇勯弬鎸庢悙妞ゎ亜鍟存俊鍫曞磼濞戞瑧褰熼梻浣告啞閹歌崵绮欓幘婢勶綁骞囬弶璺唺濠德板€愰崑鎾绘煟閹惧崬鐏查柡灞界Х椤т線鏌涢幘璺烘瀻闁伙絿鍏橀獮瀣晝閳ь剛绮婚懡銈囩＝濞达綁顎囧璺虹缂備焦顭囩粻楣冨级閸繂鈷旈柛鎺嶅嵆閺岀喓鎷犺缁♀偓閻庤娲﹂崹鍫曞箖濞嗘挻鍊绘俊顖滃帶楠炲牓姊绘担鍛婃儓闁哥噥鍨堕獮鎴﹀炊瑜滈悗鑸点亜閺傚灝鈷旂痪鎯с偢閺屾稓浠﹂悙顒傛闁轰礁鐗撳铏规嫚閳ヨ櫕鐏嶉梺鑽ゅ暱閺呯娀鐛崘顭戠叆闁稿繐澧介崰鎰焽椤忓牊鍋嬮柛顐ｇ箑缁ㄥジ姊婚崒姘偓鎼佸磹閹间礁纾瑰瀣椤愪粙鏌ㄩ悢鍝勑㈢紒鈧崼鐔虹闁糕剝锚閻忊晠鏌ｉ鐔稿磳闁哄矉缍佹慨鈧柣妯哄暱閺嗗牓姊虹粙娆惧剰闁稿﹤娼″濠氭晲婢跺﹦鐫勯梺绋挎湰閼圭偓绂掑Ο鑲╃＝濞达絽鎼瀷濡炪値鍋勯ˇ閬嶅箲閵忕姭妲堥柕蹇婂墲濞呮粓鏌熼懖鈺勊夐柍褜鍓氶崜姘焽鐠囨祴鏀介柣妯垮皺濡嫰鏌曢崼婵囧晽闁规儳澧庣壕鑲╃磽娴ｈ鐒芥繛鎻掔摠椤ㄣ儵鎮欑拠褍浼愰梺浼欑秶缁绘繈骞冭瀹曠厧鈹戦幇顓夌喖姊婚崒娆掑厡缂侇噮鍨堕獮鎰偅閸愩劎鐛ラ梺鍦濠㈡ɑ顢婇梻浣告啞濞诧箓宕归幍顔句笉闁规儼濮ら悡娆撴倵濞戞瑯鐒藉┑鈥虫喘閺屾稓鈧綆鍋呭畷宀€鈧娲﹂崑濠冧繆閻戣姤鏅滈柤鎭掑労閸炲爼姊婚崒娆戭槮濠㈢懓锕畷鎴﹀川椤掔厧鎼～婊堝焵椤掑嫬绠栭柨鐔哄Т缁€鍐┿亜閺冨洦顥夊ù鐙€鍨跺娲箹閻愭彃濮岄梺鍛婃煥闁帮絽鐣烽敐澶婄劦妞ゆ帒瀚埛鎴︽煕濞戞﹫鍔熼柟鍐插暣閹顫濋悡搴♀拫闂佺硶鏅濋崑銈夌嵁鐎ｎ喗鏅滅紓浣股戝▍鎾绘⒒娴ｈ棄鍚归柛鐘崇墵閵嗗倿鏁傞悾宀€褰鹃梺鍝勬储閸ㄦ椽鍩涢幒妤佺厱閻忕偛澧介幊鍡涙煕韫囨挾鐏辩紒杈ㄥ浮椤㈡岸宕ㄩ鐘辨闂備浇顕栭崰姘跺礂濡粯鍙忛柍褜鍓熼弻鏇㈠醇濠靛洤娅ч梺鎸庣⊕閻╊垰顫忛搹瑙勫枂闁告洦鍋勬慨銏狀渻閵堝棙澶勯柛妯哄⒔閸掓帞绱掑Ο绋夸簼闂佸憡鍔忛弲娑㈠焵椤掆偓閻栧ジ鎮￠锕€鐐婇柕濠忚吂閹风粯绻濋埛鈧仦钘夘潽缂備胶绮惄顖氱暦閵娾晩鏁囬柕濞垮妼閹牓姊绘担鍛婃儓闁活剙銈稿畷浼村冀椤撴壕鍋撴担绯曟瀻闊洤锕ラ悗濠氭⒑缂佹ê濮﹂柛鎾寸〒缁棃鎮滈懞銉㈡嫽婵炴挻鍩冮崑鎾寸箾娴ｅ啿娲﹂崑瀣煟閹邦喚绡€缂佽妫濋弻娑㈠Ψ椤旂厧顫╃紓浣哄Х閸犳劖绌辨繝鍥ч柛娑卞枛濞咃綁鏌涢妷锔藉唉婵﹨娅ｇ划娆撳箰鎼淬垺瀚抽梻浣规た閸欏酣宕板Δ鍐崥闁绘梻鍘ч崡鎶芥煏韫囧﹥顎嗛柟閿嬫そ濮婄粯绗熼崶褌绨介梺绋款儐閻╊垶骞婇悢纰辨晬婵炴垶鐟﹂悵鐑芥⒑閸︻叀妾搁柛鐘愁殜閹€斥槈閵忊€斥偓鍫曟煟閹邦厼绲婚柍閿嬫閺屾洟宕卞Ο鐑樿癁闂佸搫鑻粔鐑铰ㄦ笟鈧弻娑㈠箻閸楃偛顬嬬紓浣戒含閸嬨倕鐣烽崡鐐╂婵☆垳銆嬬槐閬嶆⒒娴ｅ憡鍟炲〒姘殜瀹曘垺銈ｉ崘銊﹁緢闂佹寧娲栭崐褰掑磹閸洘鐓熼柟閭︿簽缁侀攱淇婇幆褎鍟炵紒缁樼洴瀹曠厧顭ㄩ崨顖滃幆闂備礁鎼惌澶岀礊娓氣偓閻涱噣宕堕澶嬫櫍闂佺粯鏌ㄩ崲鍙夌珶閹烘鈷掑ù锝堟鐢盯鎮介婊冧槐鐎殿喗鐓￠、鏇㈠Χ閸♀晜缍楅梻浣告贡閸庛倝骞愰懡銈囩闁搞儺鍓氶悡蹇撯攽閻愯尙浠㈤柛鏂诲€濋弻锝夋偄閺夋垵顫囬梺鍝勭潤閸曨偒鍤ゅ┑鐐叉閸ㄧ鈪甸梻鍌欑閹碱偊鎯屾径宀€绀婂〒姘ｅ亾闁绘侗鍠氶埀顒婄秵閸犳宕愭繝姘厱闁斥晛鍟伴幊鍐ㄢ攽椤旇姤銇濇慨濠勭帛閹峰懘宕ㄦ繝鍐ㄥ壍婵犵妲呴崑鍛矙閹烘梹宕叉繛鎴欏灩閻掑灚銇勯幒宥囧妽闁告瑥绻愰埞鎴︽偐閹绘帊绨介梺缁樻崄閸嬫劙鍩€椤掑喚娼愭繛鍙夘焽閺侇噣骞掑Δ鈧悡婵嬪箹濞ｎ剙濡肩紒鐙呯稻閵囧嫰骞樼捄鐑樻濠电姴锕ら悧濠囧煕閹烘嚚褰掓晲閸涱喖鏆堥梺鍝ュ枔閸嬨倝寮婚妶鍫涗汗闁圭儤姊婚弳顐㈩渻閵堝啫鐏柣妤冨Т閻ｇ兘宕￠悙鈺傜€婚梺鐟邦嚟婵兘宕濊ぐ鎺撶厽閹艰揪绱曢悾顓㈡煕鎼粹€宠埞閾荤偞绻涢幋顓熷▏闁逞屽墮閹虫﹢骞冨鍫熷殟闁靛鍎崑鎾绘偨閸涘﹦鍙嗗┑鐘绘涧濡盯宕欓崷顓犵＜闁靛鍊楅惌娆撴煛鐏炶濡奸柍钘夘槸椤繈顢楁担杞伴偗闂傚倷绀侀幖顐ｅ緞閸ヮ剙绀堟繝闈涙－閸ゆ鏌涢弴銊ュ缂佲檧鍋撻梻浣告啞濞诧箓宕戦幒妤€姹查柕澶嗘櫆閳锋帒霉閿濆懏鍟為柛鐔哄仱閺岋紕浠︾拠鎻掝潎闂佽鍨伴ˇ鐢稿箖閳╁啯鍎熸俊顖濆吹閳ь剙顭峰娲濞戞氨鐤勯梺绋匡攻閻楃姴鐣烽幇顓фЧ閹艰揪绲鹃敍蹇涙⒑缂佹﹩娈旈柣鎿冨亰椤㈡棃宕ㄩ锝嗛敜闂備胶绮崝锕傚礈閿曗偓閳绘挻绂掔€ｎ偆鍘介梺褰掑亰閸ㄤ即鎯冮崫鍔藉綊鎮╅鑲╀紙闂佸搫鏈惄顖氼嚕椤曗偓閸┾偓妞ゆ帒鍊搁弸鍫⑩偓骞垮劚椤︻垱顢婇梻浣告啞濞诧箓宕归柆宥呯柧婵犲﹤鐗婇悡鏇熴亜椤撶喎鐏ラ柡瀣〒缁辨帗绗熼崶褎鐝濆┑顔硷龚濞咃綁骞忛悩璇茬伋闁惧浚鍋嗚ぐ鑼磽閸屾瑨鍏岀紒顕呭灣閹广垽宕橀鑲╃杽闂侀潧艌閺呮盯鎮為崹顐犱簻闁圭儤鍨甸顏堟煟閹捐泛鏋戝ǎ鍥э躬椤㈡稑顭ㄩ崘銊ヮ瀱婵＄偑鍊戦崕鑼垝鎼达絾顫曢柟鐐墯閸氬鏌涘鍐ㄦ殺闁告凹鍋婇幃妤€鈻撻崹顔界彯闂佺顑呴敃顏堟偘椤曗偓瀹曞爼顢楅埀顒傜棯瑜旈弻娑滎槼妞ゃ劌鎳樺顐ゆ喆閸曨亞绠氶梺缁樺姦娴滄粓鍩€椤掍胶澧电€规洘绻堥獮瀣晝閳ь剟宕归崒娑氱鐎瑰壊鍠曠花濂告煕鐎Ｑ勬珚闁哄矉绲借灃闁逞屽墴閹嗙疀閺囩偛袣闂侀€炲苯澧存慨濠傛惈鏁堥柛銉戝懍绱欐繝鐢靛仒閸栫娀宕熼褎绁繝鐢靛Т閿曘倝鎮ф繝鍥ㄥ亗闁绘棃鏅茬换鍡涙煏閸繂鈧憡绂嶆ィ鍐┾拺闁圭瀛╃壕鎼佹煕婵犲啰绠為柡浣瑰姍閹瑩宕滄担鐑樻緫婵犵數鍋為崹鍫曟偡閵夈儮鏋旈柕澶嗘櫆閳锋垿姊婚崼鐔恒€掑褎娲樻穱濠囶敃椤愩垹绠瑰銈庡幖濞差參骞冮姀銈呯閻忓繑鐗楃€氬ジ姊绘笟鈧鑽も偓闈涚焸瀹曘垺绺界粙璺槷闁诲函缍嗛崑浣圭濠婂牊鐓忓┑鐐茬仢閸旀粍銇勯妷锝呯伄闁逞屽墲椤煤濠婂牆鏋侀柟闂寸閻掑灚銇勯幒鎴姛缂佸鏁婚弻娑㈡偐閹颁焦鐤侀梺璇″櫙缁绘繈骞冮姀銈呯闁兼祴鏅涚敮楣冩⒒婵犲骸浜滄繛灞傚€濋弫鍐Ψ閳哄绋忔繝鐢靛Т濞诧箓鎮￠弴銏＄厽闁哄啫鐗滃Λ鎴犵磼閻樺樊鐓奸柡灞糕偓宕囨殕閻庯綆鍓涢惁鍫ユ倵鐟欏嫭绀嬪ù婊冪埣閵嗕礁顫滈埀顒勫箖閳哄啫鏋堝璺鸿嫰閹偟绱撻崒姘偓鎼佸磹瀹勬噴褰掑炊閵婏絼绮撻梺褰掓？缁€浣虹不閺夊簱鏀介柣妯虹枃婢规绱掗悪鈧崹鍫曞蓟濞戞ǚ妲堟繛鍡樺姉缁嬪洨绱撴担鎻掍壕闂佸壊鍋侀崕鏌ユ偂濞嗘垹纾藉ù锝咁潠椤忓棛绠旈柟鐑樺焾閻斿棝鏌ｉ悢绋款棆濠⒀勭☉鑿愰柛銉戝秷鍚梺璇″枟閻熲晠銆侀弮鍫濈闁靛鍎版竟鏇㈡偡濠婂啰绠抽柛鎺撳笚缁绘繂顫濋鍌ゅ晪闂佽閰ｅ褎绔熸繝鍋椽骞栨担鍏夋嫼闂佸憡鎸昏ぐ鍐╃濠靛洨绠鹃柛娆忣槺婢х數鈧鍠曢崡铏繆閻戣棄鐓涢柛灞剧矊鐢鏌ｉ悢鍝ョ煁缂侇喗鎸搁悾宄邦煥閸愮偓鍍甸柣鐘烘〃缂嶅秹鏁冮崒娑氬幈闂佸搫娲㈤崝宀勬倶閻樼數纾奸柣妯哄暱閳绘洟鏌″畝鈧崰鏍嵁閺嶎収鏁囬柣鎰悁閸濇鈹戦悩鎰佸晱闁哥姵顨堢划娆撳箻閼告娼熼梺瑙勫劤閻°劍鍒婇幘顔界厽闁靛牆楠搁悘鐘绘煕濮楀牏绡€婵﹨娅ｇ划娆戞崉閵娧屽敼闂備焦瀵уú蹇涘垂瑜版帩鏁嬮柨婵嗘处鐎氭碍绻涢弶鎴剱妞ゎ偄绉瑰娲濞戞氨顔婃繝娈垮枤閺佹槒妫㈠┑鐘绘涧濡矂寮ㄦ禒瀣厽闁归偊鍓欑痪褎銇勯妷褍鈻堥柡灞剧〒閳ь剨缍嗛崑鍛暦瀹€鍕厱闁崇懓鐏濋悘鑼偓瑙勬礀閵堝憡淇婇悜鑺ユ櫇闁逞屽墴閸┾偓?"
        )

    scenario = str(context.get("scenario") or "general").strip()
    next_step_hint = _prefer_structured_next_step(
        scenario=scenario,
        next_step_hint=_extract_next_step_hint_text(
            context.get("thread_next_step") or context.get("resume_hint") or context.get("next_step_hint")
        ),
        implementation_guide=context.get("implementation_guide") if isinstance(context.get("implementation_guide"), dict) else {},
        adaptation_guide=context.get("project_adaptation_guide") if isinstance(context.get("project_adaptation_guide"), dict) else context.get("adaptation_guide") if isinstance(context.get("adaptation_guide"), dict) else {},
        principle_note=context.get("principle_notes") if isinstance(context.get("principle_notes"), dict) else context.get("principle_note") if isinstance(context.get("principle_note"), dict) else {},
        project_ideas=[item for item in context.get("project_ideas", []) if isinstance(item, dict)] if isinstance(context.get("project_ideas"), list) else [],
        exercise_prompt=context.get("exercise_prompt") if isinstance(context.get("exercise_prompt"), dict) else {},
    )
    next_step = str(
        next_step_hint
        or context.get("thread_next_step")
        or context.get("resume_hint")
        or context.get("next_step")
        or context.get("continuity_summary")
        or context.get("review_queue_summary")
        or ""
    ).strip()
    if not next_step:
        next_step = (
            "Retry from the smallest verified step after checking the provider connection."
            if not chinese
            else "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡▎鎴犫敍闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼宕滆绾惧ジ鏌ｅΟ鎸庣彧閻忓浚鍙冮弻锝夋晲婢跺鏆犵紓浣芥閺咁偆鍒掑▎蹇婃瀻闁绘劦鍓涚粔閬嶆⒒閸屾瑨鍏岄柛瀣ㄥ姂瀹曟洟鏌嗗鍛焾闁荤姵浜介崝蹇旀叏閹惰姤鐓忓璺烘濞呭棝鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡樺窛闁硅棄鍊圭换娑㈠礂閻撳骸顫屽銈庡幖濞硷繝骞冮悜鑺ュ亱闁割偒鍋呴敍渚€姊绘担鍛婃儓闁硅櫕鎸搁埢鏂库槈濠婂懍绨烽梻鍌欑閹测剝绗熷Δ鍛偍濡わ絽鍟弲顒佺箾閹存瑥鐏柣鎾跺枛楠炴牠骞栭鐐典化缂備礁顦靛褔婀佸┑鐘诧工鐎氼喗鏅堕悽纰樺亾濞堝灝鏋旈柛鏂跨Ф缁骞掗弬鍝勪壕闁挎繂楠告禍鐐烘煕濡寧顥夐柍瑙勫灴閸┿儵宕卞Δ鍐у摋闂備礁婀遍埛鍫ュ磻閸℃稒鍎夋い蹇撴祩濡查箖姊哄Ч鍥у姶濞存粠浜妴浣割潨閳ь剟宕洪崟顖氱闁绘劦鍓﹀Λ鍕攽閿涘嫬浜奸柛濞垮€濆畷銏ゆ偂鎼搭喚鍔烽梺璺ㄥ枔婵绮婚悩宕囩瘈濠电姴鍊绘晶娑欍亜閵夈儳澧涚紒缁樼洴楠炲鎮滈崶锔捐繑婵犵數鍋涢崥瀣箲閸ヮ剙钃熼柨婵嗘閸庣喖鏌ㄥ┑鍡橆棞婵炲牆鐭傚铏规兜閸滀礁娈濈紓浣介哺濞茬喖鐛幋锕€顫呴柕鍫濇嚇閸炲爼姊洪棃娑辨Ф闁稿孩鎸抽獮妤呭即閵忊檧鎷洪梺鍝勫€堕崕鎻掆枍閸涘瓨鐓曢柣鏇氱娴滅偞绻涢崱鎰伈闁诡喗鐟╅幃婊兾熺悰鈥充壕闁汇垹鎲￠悡銉︾節闂堟稒顥犻柛鎴濇贡缁辨帡濡搁妸锔绘闂傚洤顦甸弻锝夊箻閸愬樊鍔夐梺鍝ュУ钃遍柟?provider 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婃笟妤呭磿閹邦厹浜滈柕澶堝劤婢ф稓绱掔紒妯兼创妤犵偛顑呴埞鎴﹀幢濮橆剛鍘撮梻鍌欑閹诧繝骞愮紒妯肩彾闁糕剝鐟﹂～鏇㈡煙閻戞﹩娈曢柛濠囨敱閵囧嫰骞掗崱妞惧闂備礁鎲￠弻锝夊磹閺嶎厼桅闁告洦鍨奸弫鍥煟濡绲绘鐐差儔閹鈻撻崹顔界亪濡炪値鍘鹃崗妯侯嚕椤愶箑绠涙い鎾跺仧缁愮偞绻濋悽闈浶㈤悗姘煎櫍瀵爼宕ㄦ繝浣虹畾闂佺粯鍔︽禍婊堝焵椤掍胶澧遍柡渚囧櫍楠炴帒螖閳ь剛澹曢悷閭︽富閻庯綆浜妤呮煕閵婏妇绠為柡宀嬬秮婵偓闁绘ê鍟块弳鍫ユ⒑閹惰姤鏁遍柛銊ユ健瀵鈽夊Ο閿嬫杸闂佺硶鍓濋〃蹇旂閹屾富闁靛牆鍟崝銈夋煕鐎ｎ剙鏋旀俊鍙夊姍楠炴帒螖婵犲啯娅撻梻浣稿悑娴滀粙宕曟潏鈺侇棜闁规儼濮ら崐鍨箾閸繄浠㈤柡瀣⊕閵囧嫰顢橀悩鎻掑箣濡ょ姷鍋涢崯瀛樻叏閳ь剟鏌曢崼婵囶棡闁稿寒浜娲閳轰胶妲ｉ梺鍛婄懃缁绘帒危閹版澘钃熼柕澶涜吂閹风粯绻涢幘鏉戠劰闁稿鎸荤换娑欐媴閸愬弶鍣虹€规洘鐓￠弻鐔兼倻濡闉嶉梺鍛婄懃缁绘﹢寮婚敐澶婎潊闁绘ê鍟块弳鍫ユ⒑缁嬪尅宸ュ褍閰ｉ崺鈧い鎺嗗亾缂佺姴绉瑰畷鏇㈡焼瀹撱儱娲︾€靛ジ寮堕幋鐘插箞闂備胶顢婇幓顏堟⒔閸曨垱鍋傞柡鍥╁枔缁♀偓闂傚倸鐗婄粙鎺椝夊鍕╀簻闊浄绲肩花濠氭煃鐟欏嫬鐏存い銏＄☉椤繈濡烽妷銈呭灊闂傚倷绀侀幖顐﹀嫉椤掑嫭鍎庢い鏍仧瀹撲焦淇婇姘倯鐎规洖顦甸弻锝夊箣閻戝棛鍔锋繛瀛樼矤娴滄繃绌辨繝鍥ч柛銉仢閵夆晜鐓曢悗锝庡亞濞插鈧娲﹂崹鍫曘€侀弴銏℃櫆闁兼祴鏅濋埣銈嗙節閻㈤潧孝闁挎洏鍊濋幃褔宕卞☉娆忊偓鍧楁煕椤垵浜栧ù婊勭矒閺岀喖鎮滃Ο铏逛淮濡炪倕绻嗛弲婵堟閹烘鍋愮€规洖娲ら～褏绱撴担铏瑰笡闁烩晩鍨伴悾鐑藉础閻愬秶鍠撻幏鐘诲蓟閵壯€鍋撳ú顏呪拻濞达綀顫夐崑鐘绘煕婵犲啯绀嬫い銏＄墵瀹曞崬鈻庨幇顒€绨ユ繝鐢靛仦閸垶宕硅ぐ鎺撶厑闁搞儺鍓氶悡鐔兼煛閸屾侗鍎ユ繛鍫㈠█閺屾盯濡堕崪浣稿壈濡炪値浜滈崯瀛樹繆閸洖绀冮柕濞垮劚椤挻淇婇悙顏勨偓褏绮婚幘鎰佺劷鐟滄棃鏁愰悙鍓佺杸闁哄洨濮烽敍婊冣攽閳藉棗鐏ユい鏇嗗浂鏁侀柟鍓х帛閳锋垿鏌涘☉姗堝姛闁宠棄顦甸弻銊╁即濡搫濮﹂悗瑙勬礃濞茬喖鐛Ο鑲╃＜婵☆垶鏀辩€氬ジ姊绘担钘夊惞闁哥姵鍔曢…鍨潨閳ь剙顕ｉ搹顐ｇ秶闁冲搫鍟伴敍婊呯磽閸屾瑧鍔嶉柨鏇ㄥ亰閹虫捇骞愭惔顔筋啍闂佺粯鍔栬ぐ鍐汲閿濆鐓欐い鏃傛櫕閻帡鏌熺粙鍖℃敾缂佹梻鍠栭崺鐐哄垂椤旂⒈娼庨梻浣告惈閼活垳绮旈悷鎵殾妞ゆ劧绠戠粈瀣亜閹邦喖鏋庡ù婊勫劤閳规垿鎮╁畷鍥舵殹闂佺顑傞弲鐘诲蓟閻旂厧绠氶柡澶婃櫇閹剧粯鐓冮梺鍨儏濞搭噣鏌＄仦鍓с€掑ù鐙呯畵瀹曟粏顦抽柛锝庡灦濮婅櫣绮欑捄銊ь唶闂佹椿鍓濋崑鎰ｉ幇鏉跨婵°倕锕ラ弲顏堟⒑閸涘﹣绶遍柛妯煎亾缁傛帡骞橀瑙ｆ嫼闂侀潻瀵岄崢楣冨箺閸岀偞鐓曢悗锝庝悍闊剚顨ラ悙鎻掓殭闁伙綇绻濋弻鍥晜閹冩辈闂傚倷绀侀幉鈥趁洪敃鍌氱婵炴垯鍨圭粈鍕煥閻斿搫校闁抽攱鍨块弻娑樷攽閸曨偄濮庨梺鍝勵儐閸ㄥ潡寮婚悢鐓庡窛濠电姴鍊甸弸娆愮節绾版ǚ鍋撳畷鍥ㄦ喖闂佺懓鍢查幊姗€骞婇弽褉鏀介柛銉厛濡啴鎮楃憴鍕８闁告梹鍨块妴浣肝熷▎鐐紓鍌氬€哥粔鎾磹閸噮娼栫紓浣股戞刊鎾煟閻旂厧浜伴柛銈咁儑缁辨挻鎷呴崜鎻掑壉闂佹悶鍔岀紞濠囧春閳ь剚銇勯幒宥囶槮闁搞値鍓熼弻娑㈡晲韫囨洜袦闂侀潧妫旂粈渚€鍩㈡惔銊ョ闁告劖褰冪粊顕€姊绘笟鈧褏鎹㈤崱妤婄€剁憸鏃堢嵁韫囨拋娲敂閸涱垰骞楅梻浣虹帛閺屻劑骞楀鍫濈疇闁告劦鍠楅崐鍨叏濡厧甯跺褍顕埀顒冾潐濞叉鎹㈤崼鐔剁箚闁兼悂娼х欢鐐烘倵閿濆骸澧鐐茬墦濮婄粯鎷呴搹鐟扮濠碘槅鍋勯崯鏉戭嚕閵娾晜鐒肩€广儱鎳愰敍娑㈡⒑闂堟侗妲撮柡鍛矒閹ょ疀濞戞瑧鍘遍梺鏂ユ櫅閸犳艾鈻撻弮鍫熺厓鐟滄粓宕滃▎鎾村€舵繝闈涱儐閸嬧晝鈧懓瀚€氬牓鎮㈤悡搴ｎ槯闂佺粯鎸哥€涒晛鈻嶅┑鍡忔斀闁绘劘鍩栬ぐ褏绱掗幓鎺撳仴鐎规洘娲熸俊鑸靛緞婵犲倹鍎梻渚€鈧偛鑻晶顔姐亜椤忓嫬鏆ｅ┑陇鍩栭幆鏃堝灳瀹曞浂鍞归梻鍌欑閹测€愁潖瑜版帒鍨傞柣銏犳啞閸嬧晠鏌ｉ幋锝呅撻柛瀣閻ヮ亪骞忓畝鍕懙闂佸搫鎷戠紞浣割潖閾忓湱纾兼俊顖滃劦閹疯顪冮妶搴″箹闁绘鎸搁锝夊蓟閵夈儰绱堕梺闈涳紡閸滃啰闂梻鍌欒兌椤牓寮甸鍕殞濡わ絽鍟悞鍨亜閹烘垵鈧悂宕㈤幘顔界厵闁惧浚鍋掑▓婊堟煙閾忣偆鐭掔€规洖缍婇、鏇㈠閻樿京绀嬮梻鍌氬€烽悞锕傛儑瑜版帒鍨傜憸鐗堝笒缁犵喖鏌ㄩ悢鍝勑㈢痪鎯ф健楠炴牠骞栭鐔封枏婵炲瓨绮嶇划鎾诲蓟閳ユ剚鍚嬮幖绮光偓鑼泿濠电偛顕慨宥夊川椤忓嫪澹曢柣鐔哥懃鐎氼厾浜搁锔界厽闁硅櫣鍋ゅ顔剧磼瀹€鍐摵缂佺粯绻堝畷鍫曟嚋閸偅鐝┑鐘愁問閸犳鈥﹂崼鐔翠粓闁归棿鐒﹂崕灞姐€掑锝呬壕濠殿喖锕ㄥ▍锝囧垝濞嗗繆鏋庨柟顖嗗啫顥庨梻鍌欑濠€閬嶅箠閹捐秮娲Χ婢跺浠奸梺缁樺灱婵倝宕愰懡銈囩＜婵炴垶锕╅崕鎰版煛閸滃啰绉慨濠呮缁辨帒螣閾忛€涙樊婵犵妲呴崑鍕儗閸屾氨鏆﹂柟杈剧畱缁犺崵鈧娲栧ú锕€鈻撻弴銏♀拺闁告稑锕ユ径鍕煕閹惧娲寸€规洏鍨介弻鍡楊吋閸″繑瀚肩紓鍌氬€烽悞锕傛晪婵犳鍠栧ú顓㈠蓟閿濆牏鐤€闁哄倸鐏濋幗鐢告倵鐟欏嫭绀堥柡浣割煼瀹曟椽鍩€椤掍降浜滈柟鐑樺灥椤忣亪鏌嶉柨瀣伌闁诡喗顨婂畷鐑筋敇閻戝棌鍋撶仦鍓х闁稿繒鍘ф慨宥夋煛鐏炲墽娲村┑鈩冩倐婵＄柉顦查柣鎾跺枛濮婅櫣绱掑Ο鍦箒闂佸摜濮甸〃鍫ュ箲閵忕姭鏀介悗锝庝簽閸婄偤姊洪棃娴ゆ盯宕橀妸褏鏉芥繝鐢靛Х閺佸憡鎱ㄩ悜钘夋瀬闁告稑锕ラ崣蹇涙煙缂併垹鏋涚紒鎰殕閹便劌顫滈崱妤€骞嬮梺鍝勵儐濡啴寮婚敓鐘茬倞闁靛鍎虫禒楣冩⒑缂佹ɑ灏伴柣鐔村劦婵℃挳骞掗幋顓熷兊濡炪倖甯掗崐鐑芥惞鎼淬垻绡€婵炲牆鐏濋弸娑㈡煕婵犲倻绉洪柕鍡楀暣婵＄兘鍩￠崒姘ｅ亾閻戣棄绾ч柛顐ゅ枎缁€鍐煃瑜滈崜姘扁偓绗涘洤桅闁告洦鍨伴～鍛存煥濞戞ê顏柛锝勫嵆濮婃椽宕烽褏鍔搁梺鎸庢磸閸庨亶顢氶妷鈺佺妞ゆ帒鍊婚惁鍫ユ⒑缁嬭儻顫﹂柛濠冪墵钘熸繝濠傚缁♀偓闂佹眹鍨藉褍鏆╅梻浣芥〃閻掞箓骞冮崒姘辨殾闁硅揪闄勯崐鐑芥煕濠靛棗顏い鏂挎处缁绘繈鎮介棃娴讹綁鏌よぐ鎺旂暫鐎殿喕鍗虫俊鐑藉煛閸屾粌骞堥梻渚€鈧稑宓嗘繛浣冲洤鍑犳繛鎴炴皑濡垶鏌熼鍡楃灱閸氬姊洪崫鍕伇闁哥姵鐗曢悾宄邦煥閸♀晜鞋闂佹眹鍩勯崹閬嶆儎椤栫偛钃熼柨婵嗩槸缁犲鎮楅棃娑欏暈闁革綆鍙冨娲濞戞瑦鎮欓柣搴㈢濠㈡﹢顢氶敐鍡欘浄閻庯綆鈧厸鏅濋幉鍛婃償閵娿儵妫峰銈嗘磵閸嬫挻鎱ㄦ繝鍐┿仢鐎规洏鍔嶇换婵嬪礃椤忓嫬姹茬紓鍌氬€风粈渚€藝椤栫偞鍋夊┑鍌滎焾閺勩儵鏌嶈閸撴岸濡甸崟顖氱闁糕剝銇炴竟鏇㈡⒒娴ｇ瓔鍤欑紒缁樺灴閹虫繃銈ｉ崘锝傚亾閿曞倸鍨傛い鏂诲劤閸犳挻绂嶉幖浣稿唨鐟滃本绔熼弴鐐╂斀妞ゆ梹鏋绘笟娑㈡煕鐎ｎ亜顏╅柣锝囨暬瀹曞崬鈽夊▎鎴濆箺婵犵數鍋為崹闈涚暦椤掆偓閳诲秴顓奸崶锝呬壕閻熸瑥瀚粈鈧梺缁樼墪閵堟悂濡存担鑲濇梹鎷呴崫銉х嵁闂佽鍑界紞鍡涘磻閸涘瓨鍋熸繝闈涱儐閳锋帡鏌涚仦鍓ф噯闁稿繐鐬肩槐鎺楊敋閸涱厾浠搁悗瑙勬礃缁诲牆顕ｆ禒瀣垫晞闁告瑣鍎查惈蹇涙⒒娴ｅ憡鍟為柛鏃撶畵瀹曨垶鎮㈢粙璺ㄧ獮闁诲函缍嗘禍鐐电玻閻愮儤鈷戠憸鐗堝笒娴滀即鏌涘Ο缁樺€愭鐐茬箲缁绘繂顫濋娑欏缂傚倷绀侀鍡欌偓绗涘喛鑰垮ù鐓庣摠閻撶喖鏌ｉ弮鈧换鍌氣枖濮樿泛鐐婃い鎺嶇劍濞呭洭姊虹粙鎸庢拱缂佸鎹囧畷銏ゆ濞戞帗鏂€闂佺粯鍔曢悺銊х礊閹寸偑浜滈柟瀛樼箓閳ь剙鐏濋悾鐑藉箣閿曗偓缁犲鏌ょ粙璺ㄤ粵闁稿氦椴哥换娑欐綇閸撗呅氬銈庡亜椤﹀灚淇婇棃娑掓斀閻庯綆鍋嗛崢鍛婄箾鏉堝墽鎮兼い顓炵墦閸┾偓妞ゆ巻鍋撴繛纭风節閻涱噣宕橀鑲╃暰閻熸粌绻樺鎶藉幢濡炵粯鏂€闂佺粯蓱瑜板啴寮抽敐澶嬬厸濞达絽婀遍惌鎺撴叏婵犲偆鐓肩€规洘甯掗埢搴ㄥ箳閹存繂鑵愮紓鍌氬€风欢锟犲闯椤曗偓瀹曞湱鎹勯搹瑙勬濠电娀娼ч鍛不閹惰姤鐓涢柛鎰剁到娴滅偓绻濆▓鍨仧闁告濞婂濠氬Ω閳轰礁宓嗛梺缁樺姈缁佹挳宕戦幘璇茬濞达絿顭堥崵鎴炵箾閹炬潙鐒归柛瀣崌閺岋紕浠﹂崜褉妲堥梺浼欑稻缁诲牓宕洪埀顒併亜閹烘垵顏╃痪鍓х帛缁绘盯骞嬮悙瀵告濠碘槅鍋掗崹鎶藉箟閹间礁绫嶉柛顐ｇ箚閹芥洖鈹戦悙鏉戠仧闁糕晛瀚板顐﹀礃椤旂晫鍙嗗┑鐘绘涧濡瑧绮堢仦鍙ョ箚闁圭粯甯炴晶娑氱磼缂佹绠橀柛鐘诧工铻ｇ€瑰嫰顣︽竟鏇㈡⒑閼测斁鎷￠柛鎾寸洴閹繝骞樼紒妯锋嫼闂佸憡绻傜€氼厼锕㈤幍顔剧＜閻庯綆鍋勯悘鎾煕閳瑰灝鐏柟顖涙婵″爼宕堕埡鍌涚帆闂傚倷绀侀幖顐⒚洪妸锕€鍨旀い鎾卞灩閼稿綊鏌涢敂璇插箻缁惧彞绮欓弻娑氫沪閸撗勫櫙闂佺绻愰惉鑲╂閹烘鏁嬮柛娑卞幘娴狀垶姊洪悷鎵暛闁搞劏妫勯悾鐑芥偂鎼搭喚鍞靛銈呯箰閹虫劕煤鐎电硶鍋撶憴鍕闁挎洏鍨烘穱濠囧箹娴ｅ壊娼婇梺瀹犳濡瑧绱炵仦瑙ｆ斀闁绘ɑ鍓氶崯蹇涙煕閻樻剚娈滈柕鍡楀暣瀹曘劑顢橀崶銊ф创鐎殿噮鍣ｅ畷鐓庘攽閸垺姣囬梻鍌欑劍鐎笛呮崲閸岀倛鍥ㄥ閺夋垹鍘遍梺鍦劋閸ゆ俺銇愰幒鎾存珳闂佸憡渚楅崰鏍汲閸儲鈷戦柛婵勫劚閺嬫棃鏌涚€ｎ剙浠︾紒宀冮哺缁绘繈宕堕懜鍨珖闂備焦瀵х换鍌炲箠閹邦厾顩烽柤娴嬫櫇绾捐棄銆掑顒佹悙闁哄绋掗妵鍕敇閻樻彃骞嬮梺缁樹緱閸犳牞鐏掗梺绋跨箳閸樠囨偟娴煎瓨鈷戦柤瑙勬緲椤ュ秹鏌涢埡鍌滃⒌妤犵偛顦甸幃褔宕奸姀銏㈡闂備焦鐪归崹钘夘焽瑜庣粋鎺楁晝閸屾稓鍘卞銈庡幗閸ㄧ敻鎮橀敂閿亾鐟欏嫭绀堥柟铏尵閸欏懎顪冮妶鍛閻庢凹鍣ｅ鏄忣樄婵﹥妞藉畷顐﹀礋椤曞懏钑夐梻浣侯焾鐎涒晠鎮￠敓鐘茬畺闁跨喓濮撮崡鎶芥煏韫囥儳纾块柛妯绘崌濮婅櫣鈧湱濮甸妴鍐磼閳ь剚绗熼埀顒勬偘椤斿槈鐔沸ч崶锔剧泿闂傚鍋勫ú锕傚箰閻愵剚娅犻柡鍥ュ灪閻撶喖鏌熼悜妯虹仼濞寸姵鐩弻鏇㈠炊瑜嶉顓燁殽閻愭潙绗掓い鎾炽偢瀹曞爼鎳滈弫灞剧矊閳规垿鎮╅幇浣告櫛闂佸摜濮甸悧鐘烘闂佹眹鍨婚…鍫ユ嫅閻旇　鍋撻獮鍨姎闁绘绮岄‖濠囧Ω閳哄倵鎷洪梺鍛婄☉閿曘儳浜搁幍顔瑰亾閸忓浜鹃梺褰掓？闂勫秹鍩€椤戣法顦﹂柍璇查叄楠炴﹢宕橀幓鎺撴殢濠碉紕鍋戦崐鏍箰妤ｅ啫纾婚柕鍫濇啒濞戞鏆嬮梺顓ㄩ檮鐎靛矂姊洪棃娑氬婵☆偅鐟ф竟鏇㈡偨閸涘﹦鍘遍柣搴秵閸嬪懐浜搁悽鍛婄厓鐟滄粓宕滃┑瀣剁稏濠㈣泛鈯曢崫鍕庣喖鎮℃惔锛勪喊闂備浇顫夊畷姗€顢氳缁寮介鐔哄帾闂婎偄娲㈤崕宕囧閸ф鈷掗柛鏇ㄥ亜椤忊晜銇勯鈩冪《闁圭懓瀚伴幃顔锯偓娑櫳戦弳鐗堜繆閻愵亜鈧牠骞愮粙娆剧劷闁炽儲鍓氬鏍磽娴ｈ偂鎴炲垔閹绢喗鐓曟繛鎴烇公瀹搞儵鏌￠崱妤冨ⅵ婵﹥妞介幃鐑芥偋閸喎鏋戦梻浣侯焾缁绘垿鏁冮姀銈囧祦闁告劦鍠楅崐鐑芥煟閹寸倖鎴濃枍閸ヮ剚鈷戦梺顐ゅ仜閼活垱鏅堕幘顔界厵妞ゆ洍鍋撶紒鐘崇墵瀵濡歌閸嬫捇鏁愭惔婵堟晼缂備焦鍔楅崑銈咁潖妤﹁￥浜归柟鐑樺灣閸犲﹪姊洪崨濠忚€跨紒鐘崇墪閻ｇ兘濮€閵堝孩鏅滈梺鍛婁緱閸ㄦ娊鎯侀崼銉︹拺婵懓娲ら悘鍙夌箾娴ｅ啿娲ら悞鍨亜閹烘埈妲搁柣蹇ュ閳ь剝顫夊ú姗€鏁冮姀銈冣偓渚€骞樺ú缁樻櫖濠碘槅鍨甸妴鈧柛瀣崌瀵粙顢樺┃鎯т壕闁告劦鍠栧敮闂佸啿鎼崐鎼佸焵椤掑嫭鏁遍柕鍥у缁犳盯骞橀幇浣风磻濠电偛顕慨瀛樻櫠閻ｅ本顫曢柟鎯х摠婵挳鏌ц箛鏇熷殌缂佹绱曠槐鎾存媴缁涘娈梺缁橆殕閹瑰洭鎮伴鈧畷姗€鍩￠崘鐐カ闂佽鍑界紞鍡涘磻閹烘嚦娑㈠礃閵娿垺鏂€闂佺粯鍔栭鏍涙惔顫簻闁哄啠鍋撻柛鏃€顨呴銉︾節閸愶箑浜濋梺鍛婂姂閸擃噣鏁冮崒娑氬幈闂佸搫娲㈤崝宀勬倶閻樼數纾兼い鎰╁灮鏁堥梺鍝勮嫰缁夌兘篓娓氣偓閺屾盯骞樼捄鐑樼亪濡ょ姷鍋涢崯鎶剿囪ぐ鎺撶厵妞ゆ棁顫夊▍濠囨煙瀹曞洤鈻堟い銏☆殕閹峰懐鎷犻垾铏珬婵犵數濮烽弫鎼佸磻閻愬樊鐒芥繛鍡樻尭鐟欙箓鎮楅敐搴濇喚闁绘帟濮ょ换娑㈠幢濡纰嶇紓浣插亾闁告劦鍠楅悡鍐喐濠婂牆绀堟繛鍡樻尨閳ь剚妫冨畷姗€顢欓崲澹洦鐓曢柍鈺佸幘椤忓牊鍎婇柣鎴ｅГ閳锋垿鏌涘☉姗堟敾濠㈣泛瀚伴弻娑㈠箻閺夋垵鎽甸梺璇″櫍濞佳嗙亙闂佸憡渚楅崰鎺楀箯婵犳碍鈷戠紒瀣濠€浼存煟閻旀繂娉氶崶顒佹櫇闁稿本绋撻崢鐢告煟閻樺弶鍘傞柛娑卞灣濡插洭鏌ｆ惔銈庢綈婵炲弶顭囬幑銏ゅ醇閵夈儲鐎梺鍛婂姦閸犳牜澹曢崗鍏煎弿婵☆垰銇橀崥顐も偓瑙勬礀閻栫厧顫忕紒妯诲闁告稑锕ラ崕鎾剁磽娴ｅ壊鍎庣紒鑸佃壘閻ｇ兘濮€閿涘嫷娴勯柣搴秵娴滅偤鏁?"
        )
    return summary, next_step


def _agentic_completion_continuity(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
    content: str,
) -> tuple[str, str]:
    context = extract_coaching_context(message, current_file, coach_context)
    chinese = _prefers_chinese(response_language)

    summary_candidates: list[Any] = [
        context.get("thread_summary"),
        context.get("summary"),
        context.get("current_focus"),
        context.get("continuity_summary"),
        context.get("review_queue_summary"),
        context.get("project_summary"),
    ]
    active_thread = context.get("active_thread")
    if isinstance(active_thread, dict):
        summary_candidates.extend(
            [
                active_thread.get("summary"),
                active_thread.get("focus_area"),
                active_thread.get("verified_result"),
            ]
        )
    exercise_prompt = context.get("exercise_prompt")
    if isinstance(exercise_prompt, dict):
        summary_candidates.extend(
            [
                exercise_prompt.get("summary"),
                exercise_prompt.get("prompt"),
                exercise_prompt.get("success_signal"),
            ]
        )
    implementation_guide = context.get("implementation_guide")
    if isinstance(implementation_guide, dict):
        summary_candidates.extend(
            [
                implementation_guide.get("current_step"),
                implementation_guide.get("scope_boundary"),
            ]
        )

    summary = next(
        (
            text
            for text in (_compact_text(candidate, 140) for candidate in summary_candidates)
            if text
        ),
        "",
    )
    if not summary:
        summary = _trim_sentence(content, 140)
    if not summary:
        summary = (
            "This turn is complete; keep the same coaching thread moving."
            if not chinese
            else "\u8fd9\u4e00\u8f6e\u5df2\u7ecf\u6536\u675f\uff0c\u4fdd\u6301\u540c\u4e00\u6761\u6559\u7ec3\u7ebf\u7a0b\u7ee7\u7eed\u5f80\u524d\u8d70\u3002"
        )

    next_step = _prefer_structured_next_step(
        scenario=str(context.get("scenario") or "general").strip(),
        next_step_hint=_extract_next_step_hint_text(
            context.get("thread_next_step") or context.get("resume_hint") or context.get("next_step_hint")
        ),
        implementation_guide=implementation_guide if isinstance(implementation_guide, dict) else {},
        adaptation_guide=context.get("project_adaptation_guide")
        if isinstance(context.get("project_adaptation_guide"), dict)
        else context.get("adaptation_guide")
        if isinstance(context.get("adaptation_guide"), dict)
        else {},
        principle_note=context.get("principle_notes")
        if isinstance(context.get("principle_notes"), dict)
        else context.get("principle_note")
        if isinstance(context.get("principle_note"), dict)
        else {},
        project_ideas=[item for item in context.get("project_ideas", []) if isinstance(item, dict)]
        if isinstance(context.get("project_ideas"), list)
        else [],
        exercise_prompt=exercise_prompt if isinstance(exercise_prompt, dict) else {},
    )
    if not next_step and isinstance(active_thread, dict):
        for candidate_key in ("next_step", "blocker", "verified_result"):
            text = _compact_text(active_thread.get(candidate_key), 120)
            if text:
                next_step = text
                break
    if not next_step:
        next_step = _compact_text(context.get("thread_next_step"), 120) or ""
    if not next_step:
        next_step = _compact_text(context.get("resume_hint"), 120) or ""
    if not next_step:
        next_step = _trim_sentence(content, 120)
    if not next_step:
        next_step = (
            "Continue from the same thread and verify the smallest concrete result."
            if not chinese
            else "\u6cbf\u7740\u540c\u4e00\u6761\u7ebf\u7a0b\u7ee7\u7eed\uff0c\u5148\u9a8c\u8bc1\u6700\u5c0f\u7684\u5177\u4f53\u7ed3\u679c\u3002"
        )

    return summary, next_step


def _agentic_resume_thread_text(
    summary: object | None,
    next_step: object | None,
    *,
    response_language: str | None,
) -> str:
    chinese = _prefers_chinese(response_language)
    summary_text = _compact_text(summary, 160) or ""
    next_step_text = _compact_text(next_step, 160) or ""
    if not summary_text and not next_step_text:
        return ""
    if summary_text and summary_text[-1] not in ".!?銆傦紒锛?:
        summary_text = f"{summary_text}{'銆? if chinese else '.'}"
    if summary_text and next_step_text:
        if chinese:
            return f"\u56de\u5230\u540c\u4e00\u6761\u6559\u7ec3\u7ebf\u7a0b\uff1a{summary_text}\n\n\u4e0b\u4e00\u6b65\uff1a{next_step_text}"
        return f"Resume the live thread around {summary_text} Next: {next_step_text}"
    if summary_text:
        if chinese:
            return f"\u56de\u5230\u540c\u4e00\u6761\u6559\u7ec3\u7ebf\u7a0b\uff1a{summary_text}"
        return f"Resume the live thread around {summary_text}"
    if chinese:
        return f"\u6cbf\u7740\u540c\u4e00\u6761\u7ebf\u7a0b\u7ee7\u7eed\u3002\u4e0b\u4e00\u6b65\uff1a{next_step_text}"
    return f"Resume the live thread. Next: {next_step_text}"


_GUIDED_DOMAIN_SCENARIOS = frozenset(
    {
        "remote_workspace",
        "debug_loop",
        "function_guidance",
        "project_adaptation",
    }
)


def _guided_domain_inference_coach_context(
    coach_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(coach_context, dict):
        return None
    scenario = str(coach_context.get("scenario") or "").strip().lower()
    history_mode = str(coach_context.get("history_mode") or "").strip().lower()
    if scenario not in _GUIDED_DOMAIN_SCENARIOS:
        return None
    if history_mode == "fresh_lane":
        return {"scenario": scenario}
    return coach_context


def _guided_domain_blob(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> str:
    parts: list[str] = [message]
    if current_file:
        for key in ("path", "language_id", "content"):
            value = current_file.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    inference_context = _guided_domain_inference_coach_context(coach_context)
    if isinstance(inference_context, dict):
        for key in ("current_focus", "summary", "thread_summary", "thread_next_step", "scenario"):
            value = inference_context.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    return " ".join(parts).lower()


def _infer_guided_coaching_domain(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> str | None:
    blob = _guided_domain_blob(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    if not blob:
        return None

    for domain in (
        "remote_workspace",
        "debug_loop",
        "function_guidance",
        "project_adaptation",
    ):
        if domain in blob:
            return domain

    remote_tokens = (
        "remote ssh",
        "remote workspace",
        "remote tunnel",
        "remote tunnels",
        "vscode remote",
        "dev container",
        "dev containers",
        "devcontainer",
        "wsl",
        "credential mode",
        "ssh",
        "杩滅▼",
        "杩滅▼寮€鍙?,
        "杩滅▼宸ヤ綔鍖?,
        "杩滅▼杩炴帴",
        "闅ч亾",
        "瀹瑰櫒",
        "鍑嵁妯″紡",
    )
    if any(token in blob for token in remote_tokens):
        return "remote_workspace"

    debug_tokens = (
        "debug",
        "launch.json",
        "breakpoint",
        "debug console",
        "watch expression",
        "stack trace",
        "step into",
        "step over",
        "exception breakpoint",
        "璋冭瘯",
        "鏂偣",
        "璋冪敤鏍?,
        "鍫嗘爤",
        "鍗曟",
        "鍚姩閰嶇疆",
    )
    if any(token in blob for token in debug_tokens):
        return "debug_loop"

    function_tokens = (
        "signature help",
        "function hint",
        "parameter hint",
        "hover",
        "call site",
        "function call",
        "peek definition",
        "go to definition",
        "find all references",
        "intellisense",
        "autocomplete",
        "completion",
        "function contract",
        "typescript function",
        "ts function",
        "api call",
        "鍑芥暟鎻愮ず",
        "鍑芥暟绛惧悕",
        "鍙傛暟鎻愮ず",
        "鎮仠",
        "鏌ョ湅瀹氫箟",
        "杞埌瀹氫箟",
        "寮曠敤",
        "琛ュ叏",
    )
    if any(token in blob for token in function_tokens):
        return "function_guidance"

    project_tokens = (
        "existing project",
        "project adaptation",
        "adaptation",
        "migration",
        "migrate",
        "鏀归€?,
        "閫傞厤",
        "杩佺Щ",
        "鎺ュ叆鐜版湁椤圭洰",
    )
    if any(token in blob for token in project_tokens):
        return "project_adaptation"
    return None

def _clean_guided_domain_empty_reply(
    domain: str | None,
    *,
    response_language: str | None,
) -> str:
    if domain == "remote_workspace":
        return _localized_text(
            (
                "Remote work gets easier once the workspace boundary stops moving. "
                "Stay in the VS Code remote lane for one more turn: identify whether "
                "this workspace is SSH, tunnels, dev container, WSL, or local, then "
                "verify which machine owns the files and whether the API key should "
                "stay local or remote. Return in 2 short lines: one real workspace "
                "label or path, and one sentence about the safe credential mode."
            ),
            (
                "鍏堟妸宸ヤ綔鍖鸿竟鐣岃娓呮锛宺emote 鎵嶄細鍙樼畝鍗曘€傜户缁仠鍦?VS Code remote 杩欐潯绾夸笂锛?
                "鍏堢‘璁ゅ綋鍓嶆槸 SSH銆乼unnels銆乨ev container銆乄SL 杩樻槸 local锛屽啀纭鏂囦欢瀹為檯鍦ㄥ摢鍙版満鍣ㄤ笂锛?
                "浠ュ強 API key 搴旇鐣欏湪 local 杩樻槸 remote銆傝鍙洖 2 琛岋細涓€琛岀湡瀹炵殑宸ヤ綔鍖烘爣绛炬垨璺緞锛?
                "涓€琛屽畨鍏?credential mode 鐨勫垽鏂€?
            ),
            response_language,
        )
    if domain == "debug_loop":
        return _localized_text(
            (
                "Keep this in one trustworthy VS Code debug loop. Reproduce once, pause at "
                "the first meaningful state change, and inspect one value, branch, or stack "
                "frame before widening the story. Return in 2 short lines: where you will "
                "pause first, and what single thing you expect to inspect there."
            ),
            (
                "鍏堟妸杩欎竴杞敹鏉熸垚涓€涓彲淇＄殑 VS Code debug loop銆傚厛澶嶇幇涓€娆★紝鍦ㄧ涓€涓湁鎰忎箟鐨?"
                "state change 鍋滀笅锛屽啀妫€鏌ヤ竴涓€笺€佸垎鏀垨 stack frame锛屼笉瑕佸厛鎶婂彊杩伴摵寮€銆?
                "璇峰彧鍥?2 琛岋細绗竴琛屽啓浣犲噯澶囧仠鍦ㄥ摢閲岋紝绗簩琛屽啓浣犲噯澶囧厛妫€鏌ュ摢涓€涓偣銆?
            ),
            response_language,
        )
    if domain == "function_guidance":
        return _localized_text(
            (
                "Keep this in the function-guidance lane. Start from one live call site, then "
                "use hover, signature help, and definition in that order until the contract "
                "stops moving. Return in 2 short lines: the function name, and the call site "
                "or evidence that proves what the function expects."
            ),
            (
                "鍏堟妸杩欎竴杞暀鍦?function guidance 杩欐潯绾夸笂銆傚厛浠庝竴涓?live call site 寮€濮嬶紝鍐嶆寜椤哄簭鐢?"
                "hover銆乻ignature help銆乨efinition 鎶?contract 璇荤ǔ銆傝鍙洖 2 琛岋細绗竴琛屽啓鍑芥暟鍚嶏紝"
                "绗簩琛屽啓鑳借瘉鏄庡畠鏈熸湜浠€涔堢殑 call site 鎴栬瘉鎹€?
            ),
            response_language,
        )
    if domain == "project_adaptation":
        return _localized_text(
            (
                "Keep this in the project-adaptation lane. First separate what must stay "
                "stable from what must change, then land one narrow adaptation before "
                "widening scope. Return in 2 short lines: one stable behavior you must keep, "
                "and one boundary you want to adapt first."
            ),
            (
                "鍏堟妸杩欎竴杞暀鍦?project adaptation 杩欐潯绾夸笂銆傚厛鍒嗘竻鍝簺蹇呴』绋冲畾銆佸摢浜涘繀椤绘敼鍙橈紝"
                "鍐嶅厛钀戒竴涓獎鑼冨洿 adaptation锛屼笉瑕佷竴寮€濮嬪氨閾哄ぇ銆傝鍙洖 2 琛岋細涓€琛屽啓蹇呴』淇濇寔绋冲畾鐨勮涓猴紝"
                "涓€琛屽啓浣犳兂鍏堥€傞厤鐨勭涓€閬撹竟鐣屻€?
            ),
            response_language,
        )
    return ""

def _clean_guided_domain_empty_reply_override(
    domain: str | None,
    *,
    response_language: str | None,
) -> dict[str, str] | None:
    if domain == "remote_workspace":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so I kept this turn in the VS Code remote lane.",
                "provider 娌℃湁杩斿洖鍙鍐呭锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦?VS Code remote 杩欐潯绾夸笂銆?,
                response_language,
            ),
            "next_step": _localized_text(
                "Return one real workspace label or path and one sentence about the safe credential mode.",
                "璇疯繑鍥炰竴涓湡瀹炵殑宸ヤ綔鍖烘爣绛炬垨璺緞锛屽啀琛ヤ竴鍙ュ畨鍏?credential mode 鐨勫垽鏂€?,
                response_language,
            ),
            "teaching_note": _localized_text(
                "Keep the lesson grounded in the real workspace boundary before widening the remote story.",
                "鍏堟妸鐪熷疄宸ヤ綔鍖鸿竟鐣岃绋筹紝鍐嶅睍寮€ remote 缁嗚妭銆?,
                response_language,
            ),
        }
    if domain == "debug_loop":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so I kept this turn in one trustworthy debug loop.",
                "provider 娌℃湁杩斿洖鍙鍐呭锛屾墍浠ユ垜鍏堟妸杩欎竴杞敹鏉熸垚涓€涓彲淇＄殑 debug loop銆?,
                response_language,
            ),
            "next_step": _localized_text(
                "Tell me where you will pause first and which single value, branch, or stack frame you expect to inspect there.",
                "璇峰憡璇夋垜浣犲噯澶囧厛鍋滃湪鍝噷锛屼互鍙婁綘鍑嗗鍏堟鏌ュ摢涓€涓€笺€佸垎鏀垨 stack frame銆?,
                response_language,
            ),
            "teaching_note": _localized_text(
                "Pause at one meaningful state change before widening the debug story.",
                "鍏堝湪涓€涓湁鎰忎箟鐨?state change 鍋滀笅锛屽啀灞曞紑 debug 鍙欒堪銆?,
                response_language,
            ),
        }
    if domain == "function_guidance":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so I kept this turn in the function-guidance lane.",
                "provider 娌℃湁杩斿洖鍙鍐呭锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦?function guidance 杩欐潯绾夸笂銆?,
                response_language,
            ),
            "next_step": _localized_text(
                "Return the function name, what it expects, and which call site proves that reading.",
                "璇疯繑鍥炲嚱鏁板悕銆佸畠鏈熸湜浠€涔堬紝浠ュ強鍝釜 call site 鑳借瘉鏄庤繖涓垽鏂€?,
                response_language,
            ),
            "teaching_note": _localized_text(
                "Keep the contract anchored to one live call site before widening the explanation.",
                "鍏堟妸 contract 閿氬畾鍦ㄤ竴涓?live call site 涓婏紝鍐嶅睍寮€瑙ｉ噴銆?,
                response_language,
            ),
        }
    if domain == "project_adaptation":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so I kept this turn in the project-adaptation lane.",
                "provider 娌℃湁杩斿洖鍙鍐呭锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦?project adaptation 杩欐潯绾夸笂銆?,
                response_language,
            ),
            "next_step": _localized_text(
                "Tell me which existing behavior must stay stable, what must change, and the first boundary you want to adapt.",
                "璇峰憡璇夋垜鍝釜鐜版湁琛屼负蹇呴』绋冲畾銆佸摢涓€閮ㄥ垎蹇呴』鏀瑰彉锛屼互鍙婁綘鎯冲厛閫傞厤鐨勭涓€閬撹竟鐣屻€?,
                response_language,
            ),
            "teaching_note": _localized_text(
                "Separate stable behavior from change scope before widening the adaptation plan.",
                "鍏堝垎娓呯ǔ瀹氶潰鍜屽彉鏇撮潰锛屽啀鎵╁ぇ adaptation 璁″垝銆?,
                response_language,
            ),
        }
    return None

def _guided_domain_empty_reply(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> str:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    return _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
    )

def _guided_domain_empty_reply_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, str] | None:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    return _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
    )

def _build_empty_reply_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, object]:
    domain_override = _guided_domain_empty_reply_override(
        message,
        current_file=current_file,
        coach_context=coach_context,
        response_language=response_language,
    )
    summary = (
        str(domain_override.get("summary") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    next_step = (
        str(domain_override.get("next_step") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    teaching_note = (
        str(domain_override.get("teaching_note") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    if not summary:
        summary = _localized_text(
            "The provider returned an empty visible answer, so I kept the same coaching thread moving locally.",
            "provider 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告洍鏂侀崑鎾诲磼濮ｎ厽妞介、鏃堝川椤忓懎顏归梻鍌欐祰婵倝鏁嬪銈忓瘜閸ㄨ泛顕ｉ幎鑺ュ亜闁稿繗鍋愰崢閬嶆⒑缂佹◤顏嗗椤撶喐娅犻柣銏㈩暯閸嬫挸鈻撻崹顔界亪濡炪値鍘奸崲鏌ヮ敋閿濆绠绘い鏃囨娴滄粓姊洪幆褏绠烘い鏇熺墵瀹曨垱鎯旈妸锔规嫽婵炶揪绲块…鍫ニ夎箛娑欑厽闁规儳纾晶锔锯偓瑙勬磻閸楀啿顕ｆ禒瀣╃憸蹇氥亹妤ｅ啯鈷戦柛娑橈攻婢跺嫰鏌涚€Ｑ冧壕闂備浇銆€閸嬫挸霉閻樺樊鍎愰柣鎾跺枛閺岀喖鏌囬敃鈧晶顔剧磼閻欐瑥娲﹂悡鍐磽娴ｈ偂鎴犵矆閳ь剟姊婚崶褜妲圭紒缁樼箖缁绘繈宕掑闂寸磻闂備焦妞块崢鐣屾暜閻愬搫鐒垫い鎺戝枤濞兼劖绻涢崣澶涜€块柡浣稿暣婵偓闁靛牆鎳忓Σ顒勬⒑闁偛鑻晶顖炴煏閸パ冾伃妤犵偞甯￠獮瀣攽閹邦亞妫梻鍌欑劍婵炲﹪寮ㄩ柆宥呭瀭闁割煈鍣鏍р攽閻樺疇澹橀梺鍗炴喘閺岋綁寮埀顒勫磿婵傜瑙﹂柛灞惧焹閺€浠嬫煟閹邦厽缍戦柣蹇ョ畵閺岋綁顢樿閺嬫盯鏌嶇拋宕囩煓妞ゃ垺妫冨畷鐔告償閵忊槅妫冮梺杞扮劍閸旀瑥鐣烽妸鈺婃晣闁绘柨澹婇崬褰掓⒒閸屾瑧顦﹂柟纰卞亜铻炴俊銈呮噹缁犵姵淇婇娆掝劅婵炲吋鐗曢埞鎴︽偐鐎圭姴顥濈紒鐐劤閸氬骞堥妸銉建闁糕剝顨呴獮瀣⒑缁嬫鍎愰柟鐟版喘楠炲啫顭ㄩ崼鐔锋疅闂侀潧顦崕鏌ユ偩闁秵鈷掑ù锝呮啞閸熺偤鏌熼崫銉ュ幋闁诡喚鍋ら弫鍐磼濮橀硸妲繝鐢靛Т閿曘倝鎮ф繝鍥ㄥ亗闁哄洨鍠嗘禍婊堟煙閺夊灝顣崇紒瀣吹缁辨帡鍩€椤掑嫬鐒垫い鎺戝€荤壕钘壝归敐鍡楃祷濞存粓绠栧娲礈閹绘帊绨介梺鍝ュУ閹告儳顕ｈ閸┾偓妞ゆ帒瀚埛鎺楁煕鐏炵偓鐨戝褎绋戦妴鎺戭潩椤撗勭杹閻庤娲樺ú鐔肩嵁閸ヮ剚鍋嬮柛顐犲灩楠炲牓姊虹拠鎻掑毐缂佽尪濮ら弲鑸垫償閿濆懎袣闂侀€炲苯澧存慨濠冩そ瀹曨偊宕熼浣瑰婵犵數鍋涘鍓佹崲閸曨厼鍨濋悹鍥ㄧゴ濡插牊鎱ㄥ鍫㈠埌濞存粓绠栭弻銊モ攽閸℃瑥鍤紓浣靛妽閹告娊寮诲☉姘ｅ亾閿濆骸浜濈€规洖鐬奸埀顒侇問閸犳骞愰搹顐ｅ弿闁逞屽墴閺岋絽螣鐠囪尙绁峰┑鐐茬墑閸婃洟鍩為幋锔藉€烽悗娑櫭棄宥夋⒑缁洘娅呴柛鐔告綑閻ｇ兘骞嬮敃鈧粻鑽ょ磽娴ｈ鐒介柛妯绘倐閺岋綀绠涢弴鐐扮捕婵犫拃鍡橆棄閻撱倝鎮楅悽鐢点€婇柛瀣尭閳绘捇宕归鐣屼憾闂備浇顫夐悺鏇炩枍閺囩喓鈹嶅┑鐘叉搐缁犵懓霉閿濆牆鈧粙濡歌閸犳劗鈧厜鍋撻柛鏇ㄥ墮娴犵儤绻濋悽闈浶ｇ痪鏉跨Ч閸╂盯骞掗幊銊ョ秺閺佹劙宕奸悤浣峰摋闂佹眹鍩勯崹閬嶆儎椤栫偛钃熼柣鏃傚帶缁犵懓霉閿濆牊顏犻柡鍡╁亰閹鎲撮崟顒傦紱闂佸憡顨呴崯鍧楊敋閿濆棛顩烽悗锝呯仛閺咃綁姊虹紒妯哄闁糕晜鐗犻獮澶嬪鐎涙ǚ鎷绘繛杈剧到閹诧繝骞嗛崼鐔虹閻忕偛鍊告慨鍌溾偓瑙勬磻閸楁娊鐛鈧畷婊勬媴妞嬪海鎲规繝寰锋澘鈧呭緤娴犲鐤い鏍仦閸嬪倿鏌￠崶鈺佹瀭濞存粍绮嶉妵鍕箻鐠虹儤鐎婚梺璇茬箞閸庣敻寮婚敍鍕ㄥ亾閿濆骸浜為柍钘夘樀閺屽秶鎲撮崟顐や紝濡炪們鍨洪悷锔剧紦娴犲绀堟繛鏉戭儏娴滅偓淇婇妶鍕濞存粍绮嶉妵鍕疀閹炬剚浠奸梺鍝勬４缁蹭粙鍩為幋锕€鐏崇€规洖娲ら悡鐔兼倵鐟欏嫭纾搁柛鏃€鍨块妴浣糕槈濮楀棛鍙嗛梺鍛婁緱閸犳鎯侀悙鐑樷拻闁稿本鑹鹃埀顒勵棑缁牊绗熼埀顒勭嵁閺嶎収鏁冮柨鏇楀亾缂佺姷濞€閻擃偊宕堕妸锔绢槰閻庤娲橀悡锟犲蓟濞戙埄鏁冮柣妯诲絻婵垽鎮楃憴鍕矮缂佲偓娓氣偓閳ワ箓宕稿Δ浣告疂闂傚倸鐗婄粙鎴︼綖瀹€鈧槐鎾存媴閸濆嫅銉╂煙閾忣偅宕屾繝鈧笟鈧娲箰鎼达絿鐣甸梺鐟板暱缁绘﹢鐛径鎰窛濠电偛銇樼花濠氭⒑閸濆嫬鈧湱鈧瑳鍥佸濮€閵堝棛鍘搁悗鍏夊亾閻庯綆鍓涜ⅲ缂傚倷鑳舵慨鐢告儎椤栨凹鍤曢柟缁㈠枟閸婄兘鏌ｅΔ鈧悧鍡涙偂閺囥垺鈷掗柛灞剧懅椤︼箓鏌熺喊鍗炰喊妤犵偛绻掗埀顒婄秵閸犳牜澹曟繝姘厱闁哄洢鍔屽▍姗€鏌￠崱鏇炲祮婵﹦绮粭鐔煎焵椤掆偓椤洩顦撮柟骞垮灲瀹曞ジ濡烽妷褝绱梻浣告惈缁嬩線宕㈡總鍛婂亗闁哄洢鍨洪悡娆撳级閸儳鐣烘俊缁㈠櫍閺屾稓鈧急鍐ㄢ拤缂備胶绮惄顖氱暦閸楃倣鏃堝礃椤忓秴鏁瑰┑锛勫亼閸婃洜鎹㈤崱娑樼柧婵犻潧鐗婇～鏇㈡煙閻戞﹩娈旂紒鐘垫暬閺岀喖鎮滃Ο鑲╃暭闂佸憡鑹鹃澶婎潖濞差亜浼犻柛鏇ㄥ幘閸斿湱绱撴担鍦弨缂佺姵鐗犻幃浼搭敊閻ｅ瞼鐦堥梺鎼炲劘閸斿酣宕㈤柆宥嗏拺闁告繂瀚弳濠囨煕鐎ｎ偅宕岄柡灞剧洴婵℃悂濡烽敃鈧禒鎾⒑鐠団€虫灆闁告濞婇妴浣糕枎閹寸偛纾梺闈浤涢崟顒傚竼婵犵數濮烽弫鎼佸磻閻愬搫鍨傞柛顐ｆ礃閺咁亞绱撻崒娆戝妽闁告梹鐗犻幆鍕敍閻愯尪鎽曢梺鎸庣箓濡瑩宕曢悢鍏肩厪闊洤锕ラ崳鏉库攽椤斿吋鍠橀柡宀嬬畵瀹曟﹢顢欑紒妯烘灓闂備礁鎼張顒傜矙閹烘绠氶柡鍐ㄧ墱閺佸﹤鈹戦悩瀹犲濞寸姵鍔欏缁樻媴閸涘﹥鍎撻梺娲诲幖椤﹁京妲愰悙瀵哥懝闁逞屽墴閻涱噣宕橀纰辨綂闂侀潧鐗嗛幊宥囨閸洘鈷戦梻鍫熶緱濡狙呯磼閻樺啿鐏ラ柍璇茬Ч楠炲鏁傜憴锝嗗闂佽崵濮村ú锕併亹閸愵噮鏁嗛柕蹇嬪€栭悡鏇㈡煙鐎涙绠樼紒澶庢閳ь剝顫夊ú鈺冪礊娴ｅ摜鏆︽慨妞诲亾濠碘剝鐡曢ˇ铏箾閸喎鍔ゆい顏勫暣婵″爼宕卞▎蹇婃嫛闂備胶顭堥鍥磻閵堝懐鏆﹂柟閭﹀枤绾惧吋淇婇姘础缂佺姵鑹鹃—鍐Χ閸℃瑥顫х紓浣筋嚙閸婂湱绮嬪鍫涗汗闁圭儤鎸鹃崢浠嬫⒑閹稿孩纾甸柛瀣崌閺岋絽螖閳ь剛鎹㈤幒鎳筹綁骞囬弶璺唺濠德板€愰崑鎾剁磼閳ь剟宕奸姀鈥虫瀾閻庡箍鍎遍ˇ顓㈠焵椤掆偓閸婂湱缂撴禒瀣窛濠电姴瀚铏節濞堝灝鏋熼柨鏇楁櫊瀹曟粓鏁冮崒娑樹簻闂佺硶鍓濋悷锕傚窗閹邦喒鍋撻獮鍨姎闁瑰嘲顑夊畷鐢稿即閵忥紕鍘卞銈嗗姧缁插墽绮堥埀顒佷繆濡も偓閹虫ê顫忓ú顏勫窛濠电姴鍟ˇ鈺呮⒑閹肩偛濡垮褎顨婂畷鏇㈩敃閿旇В鎷绘繛鎾村焹閸嬫挻绻涙担鍐叉瘽閵娾晛鐒垫い鎺戝€荤壕濂告煟濡搫鏆遍柣蹇嬪劦閺屽秶绱掑Ο璇茬闁剧粯鐗犻弻娑樷槈閸楃偞鐏€闂佸綊鏀卞浠嬪蓟閿濆鍋愰柛娆忣槺椤﹂亶姊洪柅鐐茶嫰婢у弶绻涢崨顔界闁崇粯鎹囬、姗€濮€閳锯偓閹锋椽姊虹涵鍛汗闁稿鐩畷婵嗩潨閳ь剟寮诲☉銏犳閻犳亽鍔庨崝顖炴⒑缁洘鏉归柛瀣尭椤啴濡堕崱妤冪懆闂佺锕ラ幃鍌氱暦閵忋倕绠绘い鏃傛櫕閸樻悂鏌ｈ箛鏇炰粶濠⒀嗘鐓ら柟缁㈠枟閻撳啴鏌曟径妯虹仯闁伙絽鐏氶〃銉╂倷瀹割喖鍓伴梺瀹狀潐閸ㄥ灝鐣烽妸鈺佺骇閻犳亽鍔屾慨宄扳攽閻樺灚鏆╁┑顔惧厴瀵偊骞栨担鍝ワ紱闂佺粯顭堥褏澹曟繝姘厵闁绘鐗婄欢鑼磼閹邦収娈滄鐐寸墪鑿愭い鎺嗗亾濠碘€炽偢閺岋綁骞樻潏鎹愨偓鍧楁煛瀹€鈧崰鎰焽韫囨柣鍋呴柛鎰ㄦ櫓閳ь剙绉瑰铏圭矙濞嗘儳鍓遍梺鍛婃⒐椤ㄥ牆危閹版澘绠婚悗娑櫭鎾绘⒑閸忚偐銈撮柛鎾寸箞瀹曞綊宕稿Δ鈧拑鐔兼煏婵炵偓娅撻柡浣告喘閺岋綁骞嬪┑鍥舵！闁诲酣娼ч惌鍌氼潖濞差亝顥堟繛鎴炶壘椤ｅ搫鈹戦埥鍡椾簼妞ゃ劌锕獮鍐潨閳ь剚淇婇悜钘夌厸闁稿本绮岄獮宥夋⒒娴ｇ懓鍔ゆ繛瀛樺哺瀹曟垿宕熼浣稿伎婵犮垼鍩栭崝鏍偂閺囥垺鐓欓柣鎴炆戠亸顓犵磼濡や焦鐨戠紒杈ㄥ笧缁辨帒螣閼测晝鏆ゆ俊鐐€ら崑鍛崲閸儯鈧線寮介鐐靛幋闂佸壊鐓堥崰鏍綖閸ヮ剚鈷戦柛婵嗗鐎氭壆绱掓径灞惧殌闁伙絿鍏橀、鏇㈡晝閳ь剛绮堢€ｎ偁浜滈柟閭﹀枛閺嬪骸霉濠婂嫬鍔ら柍瑙勫灴閹晝鈧湱濮撮ˉ婵嬫⒑缁嬭儻顫﹂柛鏃€鍨垮濠氭偄閻撳海顦悷婊冪箳閺侇喖鈽夐姀锛勫幈闁诲函鎬ラ崘銊㈡嫟缂傚倷鑳剁划顖滄崲閸愵亝宕叉繝闈涱儏绾惧吋鎱ㄥ鈧Λ璺ㄦ閹达附鈷掑ù锝堫潐閵囩喖鏌涘Ο鍏兼珪闁轰緡鍣ｉ幃娆撳传閸曨厼濮︽俊鐐€栫敮鎺楀窗濮橆剦鐒介柟閭﹀幘缁犻箖鏌涘▎蹇ｆ▓闁绘帊绮欓弻娑㈠箳閹惧磭鐟ㄩ梺浼欑稻缁诲牆鐣烽悢鐓庣濞达綀銆€濡劌鈹戦悩鍨毄濠电偐鍋撳┑鐐板尃閸忕姵妞介弫鍌炲礈瑜忛ˇ顖炴⒑閹肩偛鍔撮柛鎾村哺閹繝宕橀鐣屽幈濠电娀娼уΛ妤咁敂閳哄懏鐓涢柛鈩冪懃閺嬫盯鏌＄仦鍓ф创鐎殿噮鍓涢幑鍕Ω椤喓鍔岄埞鎴︻敊绾嘲濮涚紓渚囧櫘閸ㄥ爼鐛箛娑樺窛闁哄鍨电粣娑欑節閻㈤潧孝闁硅櫕鍔欓妴渚€宕ㄧ€涙ǚ鎷绘繛杈剧导鐠€锕傛倿閸撗呯＜闁靛闄勯妵婵堚偓瑙勬礃閸旀洟鍩為幋鐘亾閿濆簶鍋撻婊冨姦闁哄本鐩獮鍥濞戞瑧浜柣搴ｆ嚀閹诧紕鎹㈤崘顔嘉﹂柛鏇ㄥ灠缁犲鎮归搹鐟板妺闁诲孩鍎抽埞鎴︽倷閼碱剙顣归梺鍛婎殔閸熷潡锝炶箛鏃傜瘈婵﹩鍓涢敍婊冣攽椤旀枻渚涢柛蹇旓耿瀹曟垿骞樼紒妯衡偓濠氭煠閹帒鍔氶柍褜鍓欏锟犲蓟閵娾晛绫嶉柛顐ゅ枑濞堜即姊虹粙娆惧剱闁圭澧介崚鎺楊敇閻愨晜顫嶅┑鈽嗗灠閹碱偆绮绘繝姘拺闁告稑锕︾粻鎾绘倵濮樺崬鍘寸€规洏鍎抽埀顒婄秵娴滃爼鎮㈤崱娑欏仯闁惧繒鎳撻惃鎴︽煕閺冨倸鏋涢柡灞诲妼閳藉鈻庨幋鐐插灡婵犳鍠栭敃銉ヮ渻娴犲绠栭柣鎴ｆ缁狙囧箹鐎涙ɑ灏伴悗鍨墱缁辨捇宕掑▎鎴ｇ獥闂侀潻缍嗛崳锝呯暦瑜版帒閱囬柡鍥╁仧閻ｆ椽姊虹捄銊ユ灁濠殿喚鏁诲畷鎴﹀礋椤栨稓鍘惧┑鐐存綑椤戝棗鈻嶉崨顖涘枑闁哄鐏濋顓熸叏婵犲啯銇濇鐐寸墵閹瑩骞撻幒鎴綑闂傚倷绀侀幉锟犲蓟閵娧呯煋鐟滅増甯炲畵渚€鏌涢埄鍐槈缂佲偓鐎ｎ偁浜滈柟杈剧稻绾墎绱掗悩瀹犲妞ゎ亜鍟存俊鍫曞幢濞嗗浚娼锋俊鐐€戦崝宀勫箠韫囨洜鐭夌€广儱妫庨崑鍛存煕閹般劍鏉归柟宄邦煼濮婅櫣绮欓幐搴㈡嫳闂佽崵鍟欓崶浣告喘閺佸啴宕掑☉姘箥缂備胶鍋撳妯虹暦椤掍胶顩查柟娈垮枓閸嬫挸鈻撻崹顔界亾闂佽桨绀侀…鐑藉Υ娴ｈ倽鏃堝川椤撶媴绱叉繝鐢靛Т閿曘倝骞婇幇鏉垮偍妞ゆ牜鍋為埛鎺懨归敐鍛暈闁诡垰鐗忕槐鎺斺偓锝傛櫇缁愭梻鈧娲橀崹鍨暦閸楃倣鐔轰焊閺嶃劎浜欓梺璇查缁犲秹宕曢崡鐐嶆稑鈽夊鍙樼瑝婵°倧绲介崯顖炴偂濞嗘挻鍊垫繛鎴炵懐閻掍粙鏌熼崘鎻掓殻闁哄矉缍€缁犳稒绻濋崘鈺冨絿缂傚倷娴囨ご鍝ユ暜閿熺姴绠栭柍杞扮贰閸熷懏銇勯弮鈧崕鎶藉箖閹达附鈷掑ù锝囩摂閸ゅ啴鏌涢悩宕囨创闁挎繄鍋炲鍕節鎼达絽濮烘俊鐐€曠换鎰版偋閸℃瑧涓嶆い鏍ㄥ閸嬫捇宕楁径濠佸濠电姷鏁告慨鎾磹閹间胶鍙冮梻鍌氬€搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偞鐗犻、鏇㈠煑閼恒儳娲存い銏★耿婵偓闁绘顣槐閬嶆⒒娴ｅ憡鍟炲〒姘殜瀹曞綊宕￠悙鍨闂佸憡鐟ラˇ杈╁姬閳ь剟姊婚崒姘卞濞撴碍顨婂畷鏇㈠箛閻楀牏鍘遍柣搴祷閸斿本鎱ㄩ崒娑欏弿濠电姴鍋嗛悡鑲┾偓瑙勬礀閵堟悂骞冮姀鐘垫殝闁规鍠掗崑鎾活敆閳ь剟鍩為幋锔藉€烽柡澶嬪灩娴犙囨⒑閹肩偛濡芥俊鐐扮矙楠炲啴鏁撻悩鎻掑祮闂侀潧绻嗛埀顒佹灱閸嬫捇鎮介崨濠勫弳濠电娀娼уΛ婵嬵敁濡も偓闇夋繝濠傚缁犵偤鏌熼绛嬬劸缂佺姵绋掗幆鏃堝灳瀹曞洢鍋栭梻鍌欑閹碱偊寮甸鈧叅闁绘棃顥撻弳锕傛煙椤栫偛浜版俊鑼额嚙椤啴濡堕崨顔绢洶闂佸憡鎸荤粙鎾澄ｉ幇鏉跨婵°倓绀佹禍褰掓倵鐟欏嫭绀€婵炶绠撳畷姘槈濡粍妫冮幃鈺呮濞戞鍕冩俊鐐€ら崢鐓幟洪銏㈠祦闁硅揪绠戠粈瀣亜閹烘垵鈧骞婂┑鍡╂富闁靛牆妫涙晶顒傜磼鐎ｎ偄娴柟顖欑窔楠炴帒螖娴ｅ弶瀚介梻浣侯焾閺堫剟鎮烽敂鍓х焾闁绘鐗勬禍婊堟煛閸パ勵棞闁瑰啿顦靛畷鎴﹀箻閺傘儲顫嶉梺鍦劋閹稿鎮靛鑸碘拺缁绢厼鎳忛悵顏嗙磼鐠囨彃鏆ｅ┑鈥崇埣閺佹劖寰勬繝鍕垫Н婵＄偑鍊栭悧妤冨枈瀹ュ棗绶為柛鏇ㄥ灡閸婄敻姊婚崼鐔衡棨闁稿鍨婚埀顒侇問閸犳牠鎮ユ總鍝ュ祦濠电姴瀚す鎶芥煕閿旇骞橀柡鍡愬€濆娲传閸曨剚鎷遍梺鐑╂櫓閸ㄤ即顢氶敐澶婄妞ゆ柨妲堥埡鍛厪濠㈣鍨伴崐鎼佸箺鐎ｎ剛纾介柛灞捐壘閳ь剛鍏橀幊妤呮嚋閸偄寮块梺鍓茬厛閸嬪棛绮婚幆褉鏀介柣妯哄级閹兼劙鏌﹂崘顏勬瀾缂佺粯鐩獮瀣枎韫囨洑鎮ｉ梻浣虹帛鐢顪冩禒瀣摕婵炴垯鍨圭粻娑㈡煕閹捐尪鍏岀紒鎰殔閳规垿鎮欓懠顒傚姼婵炲瓨绮嶇换鍕箲閵忕姭鏀介悗锝庝憾濞煎﹪姊洪幐搴ｇ畵閻庢稈鏅濈槐鐐哄醇濠靛啯鏂€闂佺粯鍔栬ぐ鍐棯瑜庨妵鍕敇閻愭潙鏋犲Δ鐘靛仦閸ㄦ寧鎱ㄩ埀顒勬煟濮楀棗浜濋柡鍌楀亾闂備浇顕ч崙鐣岀礊閸℃稑纾婚柛鏇ㄥ墰椤╅攱绻涘顔荤凹闁抽攱甯￠弻娑氫沪閻愵剛娈ゆ繝鈷€鍕创闁哄本鐩獮鎺楀幢濡炴儳顥氭繝鐢靛Х閺佹悂宕戦悙鍝勫瀭妞ゆ牜鍋涢崹鍌涚箾瀹割喕绨奸柛瀣€块弻锟犲炊閵夈儳浠鹃梺绋匡功閺佸寮婚妸銉㈡斀闁糕剝渚楅埀顒侇殔闇夋繝濠傚缁犳﹢鏌嶈閸撴繈锝炴径濞掓椽寮介鐔峰壒闂佺鐬奸崑娑㈡嫅閻斿吋鐓冮柕澶堝劤閿涘秹鏌￠崱妤侇棦闁哄苯绉烽¨渚€鏌涢幘璺烘瀻闁伙綁鏀辩€靛ジ寮堕幋鐙€鍟嬮梻浣哄帶閹诧繝顢欓弽褜鐒介柣鏂垮悑閳锋垿鏌涢敂璇插箹闁告柨顑嗛妵鍕Ω閵夛箑娈楅梺鎸庣箘閸嬨倕鐣烽妸褉鍋撳☉娆樼劷闁告妫勯埞鎴﹀煡閸℃浠村┑鐐叉嫅缂嶄線寮鍜佸悑闁告哎鍊楅幊鎾烩€﹂妸锔藉劅婵犻潧鐗婇弲鑲╃磽閸屾瑦绁板瀛樻倐楠炴垿宕惰閺嗭箓鏌熼悜妯虹亶闁哄閰ｉ弻鐔兼倻濡櫣浠撮柣銏╁灱閸ㄤ即鍩為幋锔藉亹闁归绀侀弲閬嶆⒑閹肩偛濡奸柕鍫㈩焾閻ｇ兘鏁愭径濠勵槰闂侀潧臎閸曨剦鍟庢繝鐢靛仦濞兼瑩宕ョ€ｎ亶鐒芥繛鍡樻尭缁€鍐煃瑜滈崜娆撯€旈崘顔嘉ч柛鈩兠弳妤呮⒑缁嬫鍎戦柛鐘崇墪閻ｇ兘濮€閵堝懐顔掑銈嗘琚欓柟鐤缁辨帞绱掗姀鐘茬闂佺懓鍟跨换妤呭Φ閹邦垼妯勫┑顔硷工椤嘲鐣烽悢纰辨晝闁靛繆鏅欑槐鏃堟煟鎼淬値娼愭繛鍙夛耿瀹曞綊宕稿Δ鍐ㄧウ闂佹悶鍎洪崜姘跺磻鐎ｎ喗鐓曟い鎰Т閻忊晜顨ラ悙鑼ょ紒杈ㄦ崌瀹曟帒顫濋钘変壕闁绘垼濮ら崐鍧楁煥閺囩偛鈧綊寮查鍫熲拻濞达絼璀﹀鎺楁煕閹邦垰鍔甸柛姘煎亰濮婃椽宕崟顒佹嫳缂備礁顑嗛幑鍥春閳ь剚銇勯幒鎴姛缂佸鏁婚弻娑氣偓锝庝簼閸ｅ綊鏌ｉ敐鍥у幋鐎规洜鍠栭、娑樷槈濮橆剙濡囬梻鍌欑劍閹爼宕曢鐐茬閻忕偟鍋撻崣蹇曗偓骞垮劚濡厼鈻撴禒瀣厽闁归偊鍘界紞鎴炵箾閹碱厼鏋熸い銊ｅ劦閹瑥顔忛鐓庡闂備浇顕栭崳顔界椤忓嫮鏆﹂柕濞炬櫓閺佸秵绻涢崱妯轰刊婵炲樊鍓熷濠氬磼濮橆兘鍋撻幖浣哥９闁归棿绀佺壕鐟邦渻鐎ｎ亝鎹ｉ柣顓炴閵嗘帒顫濋敐鍛婵°倗濮烽崑娑⑺囬悽绋挎瀬闁瑰墽绮崑鎰亜閺冨倹鍤€濞存粓绠栭弻娑㈠箛闂堟稒鐏堥梻浣稿船濞差參寮婚弴鐔风窞闁割偅绻傛慨銏ゆ⒑閹稿海鈯曢柣鈺婂灠椤繑銈︾憗銈勬睏闂佸湱鍎ら崹鎶藉窗婵犲洦鈷戠紒瀣閹癸綁鏌℃担鍓茬吋鐎殿噮鍋婇獮鍥敇閻愮數鐛┑鐘垫暩婵潙煤閵堝鏋佺憸鐗堝笚閳锋帒銆掑锝呬壕濠电偘鍖犻崵韬插姂閸┾偓妞ゆ巻鍋撻柍瑙勫灴閸ㄩ箖鎼归銏＄亷闁诲氦顫夊ú蹇涘垂娴犲绠栧ù鐘差儐閸嬨劑鏌ｉ姀銏╂殰缂佽鲸濞婂缁樻媴娓氼垳鍔搁梺鍝勭墱閸撶喖骞冮悜钘夌厸濞撴艾娲ㄩ埀顒€鐖奸弻锝夊箣閿濆憛鎾绘煟閹惧瓨绀嬮柡灞炬礃缁绘盯宕归鐓幮戠紓鍌欑椤︽澘顪冩禒瀣摕闁绘梻鈷堥弫濠囨煛閸屾ê鈧盯鍩€椤掆偓濞硷繝寮婚悢纰辨晩閻熸瑥瀚悵鏍⒑閻熸澘绾фい銊ユ楠炲繘宕ㄧ€涙ê鈧粯淇婇婊冨妺闁伙綆鍓氭穱濠囨倷椤忓嫧鍋撻妶澶婂偍鐟滅増甯掔粈澶愭煙鐎涙绠橀柡鍡畱閳规垿宕掑搴ｅ姼濡炪値鍋勯幊姗€寮婚弴锛勭杸濠电姴鍊搁埛澶愭⒑娴兼瑩妾悽顖涘浮閸╃偤骞嬮敂钘変汗闂佸綊顣︾粈渚€寮查柆宥嗏拺闁告縿鍎辨牎闂佺粯顨堟繛鈧€殿噮鍋婂畷姗€顢欓崲澶堝姂閺屾洘寰勫Ο鐑樼亶闁诲酣娼ч惌鍌氼潖濞差亝鍤嶉柕澶婂枤娴滎亣妫熼梻渚囧墮缁夋潙效閺屻儲鐓ラ柡鍌涱儥濞肩喎霉濠婂嫮鐭掗柡宀€鍠栧鍫曞垂椤曞懏娈洪梻浣风串缂嶁偓濞存粠鍓涘Σ鎰板箳濡も偓閻掑灚銇勯幒鎴濃偓鐢稿磻閹剧粯鏅查幖绮瑰墲閻忓秹姊虹紒妯诲鞍婵炲弶锕㈡俊鐢稿礋椤栵絾鏅ｉ梺缁樻椤ユ挻绂掗幘顔解拺闂侇偆鍋涢懟顖涙櫠閸撗呯＝鐎广儱瀚崝宥夋煙娓氬灝濮傞柛鈹惧亾濡炪倖甯掔€氼參鎮¤箛娑欑厱妞ゆ劧绲跨粻鏍ㄣ亜閵夛箑鐏撮柡宀€鍠栭弻銊р偓锝庡亖娴犮垹鈹戦纭锋敾婵＄偠妫勯悾鐑藉Ω閿斿墽鐦堥梺鍛婃磸閸斿秹锝炲澶嬧拻濞达絿鎳撻婊勭箾閹绘帞绠荤€规洘娲熼幖褰掝敃閵堝孩閿ら梻浣哥秺濡法绮堟担铏逛笉闁靛璐熸禍婊堟煛閸屾氨浠㈤柍閿嬫閺屻劌鈽夊▎鎴犵厜闂佸搫鐭夌紞渚€骞冮埡鍛煑濠㈣泛澶囬弫宥夋⒑鐠囪尙绠扮紒缁樺灴閹兘鏁冮崒姘辨煣闂佸壊鍋呭ú鏍础閹惰姤鐓熼柡鍐ㄥ€荤弧鈧紓浣靛妼椤嘲顫忓ú顏勪紶闁告洦鍓涢妶鈺傜箾鐎涙鐭岄柛瀣枔閸掓帡寮崼顐ｆ櫓缂備焦绋戦鍡涱敊閺冨牊鈷戠紓浣姑慨鍫ユ煟閹垮嫮绡€鐎规洩缍佸畷鐔碱敍濞戞艾骞嶇紓鍌欑椤戝懐浜搁崨鏉戠哗闁煎鍊愰崑鎾诲垂椤愶絿鍑￠柣搴㈠嚬閸犳绮嬮幒妤佹櫇闁稿本绋戦惂鍕節閵忥綆鍤冮柛妯挎鐓ら柡宥庡幖閻撴﹢鏌熸潏楣冩闁哄拋鍓熼弻娑㈠即閵娿儰绨甸梺鍝勵樈閸欏啫顫忛搹鍦煓闁告牑鍓濋弫楣冩⒑缂佹﹩娈曠紒顔芥尭椤曪綁顢曢敂缁樻櫔闂侀€炲苯澧撮柣娑卞櫍楠炴帡骞婇搹顐ｎ棃闁糕斁鍋撳銈嗗笒閸婃悂藟濮樿鲸鍠愰柣妤€鐗嗙粭姘舵煟閹捐泛孝闁宠鍨块、娆撴寠婢跺娼撻梻渚€鈧偛鑻晶顖涚箾閼碱剙鏋欐俊顐犲灩閳规垿顢欑粵瀣姼闂佺硶鏅滈悧鐘诲箖閿熺姴顫呴柍銉ㄥ皺缁犳艾顪冮妶鍡欏闁荤喆鍔戦、妤呮偄闂€鎰畾濡炪倖鍔﹂崜娆撱€呴鍕厵闁告瑥顦伴崐鎰版煙椤斻劌娲ら柋鍥ㄧ節闂堟稓澧㈤柟铏墵濮婄粯鎷呴崨濠冨創闂佺懓鍟跨换姗€骞冮敓鐘虫櫢闁绘灏幗鏇炩攽閻愭潙鐏熼柛銊ф嚀閺侇噣姊绘笟鈧褔藝椤撱垹纾挎繛宸簻濮规煡鏌曡箛瀣偓鏍煕閹达附鐓曟繛鎴烇公閺€濠氭煃闁垮濮嶉柡宀€鍠栭、娆撴偂鎼存ê浜鹃柟闂寸筏缂嶆牠鐓崶銊﹀婵炲樊浜堕弫鍌炴煕閺囥劋绨介柣鎰躬濮婄粯鎷呴崨濠傛殘濠电偠顕滅粻鎾崇暦濠婂牊鏅濋柍褜鍓濋悘瀣⒑閻愯棄鍔滈柡瀣偢瀵劍绂掔€ｎ偆鍘介梺褰掑亰閸ㄨ京娑垫ィ鍐╃厽闁靛闄勯妵婵嬫煛鐏炲墽娲撮柟顔规櫅閻ｇ兘宕惰閹蜂即姊绘担铏瑰笡濞撴碍顨婂畷鎶芥晲閸涱垱娈惧┑顔姐仜閸嬫挸鈹戦垾铏暈闁诡垱妫冩慨鈧柍钘夋椤ュ牓鏌ｆ惔銈庢綈婵炴彃绻樺畷婵嬪箣閿旇　鍋撴担鍓叉僵閻犲搫鎼粣娑橆渻閵堝棙绀€闁瑰啿绻樿棢闁割偆鍠撶弧鈧梺姹囧灲濞佳冩毄闂備浇妗ㄩ悞锕傚箖閸屾氨鏆﹂柟杈鹃檮閸婄兘鏌涘┑鍡楊仼闁诲寒鍙冮弻锝夋偐閻戞ǜ鈧啴鎮归埀顒勬晝閳ь剟鈥﹂崶顒€鐓涢柛娑卞枤閸橆亝绻濋悽闈浶㈢紒缁樺浮閹偓娼忛妸锝勭盎闂佸搫娴傚鈧柟鏌ョ畺閺岋紕浠﹂崜褎鍒涙繝纰夌磿閸忔﹢銆佸▎鎾村亗閹兼惌鍠楀ù鍥⒒閸屾瑧鍔嶅┑鐐诧躬瀵劑鏌嗗鍛€梺鍓插亝濞叉牜绮婚悙鐑樼厪濠电偟鍋撳▍鍡涙煕鐎ｅ墎绡€闁哄矉绲借灃闁逞屽墴閹勭節閸パ呯暫濠电偛妫欓幐濠氬煕閹达附鐓曟繛鎴烇公閺€濠氭煃闁垮濮堢紒缁樼洴瀹曟鎳栭埡鍌氭珰婵犵數濮崑鎾趁归敐鍥┿€婇柡鈧禒瀣厽婵☆垱顑欓崵瀣偓瑙勬偠閸庣敻寮婚悢鐓庣闁圭粯甯╅崝澶岀磽娴ｇ鈧湱鏁Δ鈧…鍥疀濞戞巻鍋撻敃鍌氱闁绘垵妫楅弲顒勬⒒閸屾瑨鍏岀紒顕呭灦瀹曟繈寮借閻掕姤绻涢崱妯诲鞍闁稿﹤鐖奸幃妤呮偨閻㈢偣鈧﹪鏌涚€ｎ偅灏甸柟鍙夋尦瀹曠喖顢楅崒銈喰ら梻鍌欑閹芥粍鎱ㄩ悽鍛婂亱闁绘顕ц繚婵炶揪绲跨涵璺何ｉ崼鐔剁箚妞ゆ牗绮屾禒锕傛偨椤栨粌浠︾紒鍌氱Ч楠炴牗鎷呯粙鍨暏闂備線娼ч…顓熶繆閸ヮ亗浜归悗锝庡枟閳锋帒霉閿濆懏鍟為柟顖氱墦閹泛顫濋悡搴濆枈閻庤娲樼换鍫ョ嵁鐎ｎ亖鏀介柟閭﹀墯椤撳潡姊绘担鍛婃儓妞わ缚鍗冲畷鐢告晝閸屾氨鐫勯梺鍓插亝缁诲嫰宕濋敃鈧—鍐Χ閸℃鐟愰梺鐓庡暱閻栧ジ濡撮崨鏉戠闁瑰箍鍔嶅Λ鍐极閹版澘宸濇い鎾跺枑椤斿姊绘担鐟扳枙闁衡偓闁秴鍨傞柛锔诲幗椤洟鏌熼幆褏鎽犲┑顖涙尦閺屻倕霉鐎ｎ亜鈷夐梺鎼炲姀椤绮嬪澶婄濞达絿鎳撴禍閬嶆⒑閸撴彃浜栭柛銊ヮ煼椤㈡瑩寮撮姀鈾€鎷洪梺鍛婄☉閿曪箓骞婇崘鈹夸簻闁挎洖鍊烽幉楣冩煙椤栨氨鐏卞ù鐙呯畵瀹曪綁濡疯閻ｉ箖姊绘担鍛婂暈闁荤喆鍎佃棟妞ゆ牗绋掗崣蹇曗偓骞垮劚濡厼鈻撴禒瀣厽闁归偊鍘介崕妤呮煟閹哄秶鐭欓柡宀€鍠愰ˇ鐗堟償閳锯偓閺嬪懘姊洪悷鎵紞濠电偐鍋撳銈冨灪椤ㄥ棛鎹㈠┑瀣妞ゆ劑鍊曢幖鍛婄節閻㈤潧啸闁轰礁鎲￠幈銊╂倻閽樺鐎梺褰掓？缁€浣哄缂佹绠鹃柟瀵稿剱閻掑憡绻涢幋鐐冩岸寮告惔銊︾厵闁诡垎鍐╂瘣闂佽瀵掗崣鍐潖濞差亜绀傞柤娴嬫杺閸嬬偤姊洪崫鍕櫤缂佽鐗撻獮鍐ㄧ暦閸モ晝锛滃┑鈽嗗灠濠€杈╃不濮樿埖鈷戦梻鍫熺〒婢ф洟鏌熼崘鑼鐎规洖鍟跨叅妞ゅ繐鎳愰崢鎾绘⒒娴ｅ摜浠㈡い鎴濇嚇閹﹢骞橀鐣屽幐闁诲繒鍋涙晶浠嬪煡婢舵劖鐓冮柦妯侯樈濡插憡銇勯锝囩煉鐎规洖宕埢搴ょ疀閹惧墎蓱闂傚倸鍊搁崐鐑芥嚄閸撲礁鍨濇い鏍ㄧ矋閺嗘粌鈹戦悩鎻掝仼闁搞劍绻冪换娑㈠幢濡纰嶉梺钘夊暟閸犳牠寮婚妸鈺傚亜闁告繂瀚呴姀鈥茬箚闁绘劘鍩栭ˉ澶愭婢舵劖鐓ユ繝闈涙－濡茶绻涢崨顔剧煉闁哄本鐩幃鈺冩嫚瑜戦崥顐︽⒑鐠団€虫灍妞ゃ劌鎳橀崺銏ゅ箻鐠囨彃鐎銈嗘⒒閺咁偉銇愰鐐粹拻濞达絼璀﹂悞鐐亜閹存繃鍤囬柡浣稿暣椤㈡棃宕煎顏傚劚闇夐柨婵嗘川閵嗗﹪鏌＄€ｎ亪鍙勯柡宀€鍠栭幃娆擃敆娴ｈ櫣鈻忛梻渚€鈧偛鑻晶鎾煛閳ь剟鏌嗗鍛傦箓鏌涢弴銊ョ仩缂佺姵濞婇弻娑㈠焺閸愶缚娌繝銏ｎ潐濞茬喎顫忕紒妯诲闁告稑锕ラ崕鎾愁渻閵堝棗鐏ラ柟铏悾鐑藉箛閺夊灝鐎銈嗘礀閹冲繒绱炴惔鈾€鏀介柣鎰级閳绘洖霉濠婂嫮鐭婃い鏂跨箰閳规垿宕辫箛鏃€鏉搁梻浣虹帛钃辩憸鏉垮暣瀵啿鈻庨幇鈺€绨婚梺鎸庢椤鈻嶆繝鍐╁弿濠电姴鍟妵婵堚偓瑙勬磸閸斿秶鎹㈠☉姗嗘僵妞ゆ挾鍋熸导灞轿旈悩闈涗粶闁哥喐娼欓悾鐑藉箳閹搭厽鍍甸梺缁樻尭鐎涒晠顢橀崸妤佲拻濞达絽鎽滅粔鐑樹繆椤愩儲纭剁紒顔肩墛缁楃喖鍩€椤掆偓閻ｅ嘲顫滈埀顒勫春閳ь剚銇勯幒鍡椾壕濡炪値浜滈崯瀛樹繆閸洖骞㈡俊顖滃劋濞堫偊姊绘担鍛婃喐濠殿喚鏁婚獮鎴﹀炊瑜忛弳锕傛煏韫囥儳纾挎い鈺冨厴閹鏁愭惔鈥茬敖闂佸憡顭囬弫璇差潖閾忓湱鐭欓悹鎭掑妿椤斿洭姊洪崨濠呭妞ゆ垵顦悾鐑藉即閻愬秵妫冨畷銊╊敊閹冪疄闂傚倷绶氬褔鈥﹂崼銉ョ？闁规儼濮ら弲顒傗偓骞垮劚濞层劎澹曢崗绗轰簻闁哄啫娲よ濡炪們鍎遍悧濠冪┍婵犲浂鏁冮柕蹇曞У濞堫參姊婚崶褜妯€闁哄本娲濈粻娑氣偓锝庝簽娴犻箖姊洪幖鐐测偓鎰板磻閹剧繝绻嗛柣鎰典簻閳ь兙鍊濆畷銏ｃ亹閹烘垹顦梺鐟扮摠缁诲嫰寮抽敃鍌涚厽闁哄啫鍊甸幏锟犳煛娴ｅ憡鍠橀柡宀嬬到椤粓鍩€椤掆偓椤洩顦撮柡渚囧櫍楠炴﹢宕滄担鐚寸闯闂備胶顭堥張顒勬嚌妤ｅ啫鐒垫い鎺戝濡垶绻涢崱鎰伈闁轰焦鎹囬幃鈺呮嚑椤掑倸鐐婇梻鍌欑閹碱偆绮欐笟鈧畷銏ゅ箹娴ｅ摜鍔﹀銈嗗笒閿曪箓鎮鹃悽鍛婄厵妞ゆ梻鏅惌鎺楁煙缁嬪尅鏀荤€垫澘瀚悾婵嬪焵椤掑嫬姹叉い鎰ㄦ噰閺€浠嬫煟閹邦剚鈻曢柛銈囧枎閳规垿顢欓懞銉ュ攭濡炪們鍨洪悧鐘茬暦閵娾晩鏁囩憸宥夊疾閻樻祴鏀介柣妯肩帛濞懷勪繆椤愩垻鐒哥€殿喓鍔嶇粋鎺斺偓锝庡亞閸樿棄鈹戦埥鍡楃仴妞ゆ泦鍛筏缂備焦菧娴滄粓鐓崶褝鏀绘繛鍛躬閺?",
            response_language,
        )
    if not next_step:
        next_step = _localized_text(
            "Restate the target behavior and the one decision that still feels uncertain, then reduce it to the next smallest verifiable step.",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈囩磽瀹ュ拑韬€殿喖顭烽弫鎰緞婵犲嫷鍚呴梻浣瑰缁诲倿骞夊☉銏犵缂備焦顭囬崢杈ㄧ節閻㈤潧孝闁稿﹤缍婂畷鎴﹀Ψ閳哄倻鍘搁柣蹇曞仩椤曆勬叏閸屾壕鍋撳▓鍨灍婵炲吋鐟╅敐鐐测攽鐎ｎ偄娈濆┑鐐茬墕缁ㄩ亶宕戦幘璇插唨闁靛ě鍜佸晭闂佽瀛╃粙鎺椻€﹂崶顒佸剹濠电姴瀚壕鐣屸偓骞垮劚閹锋垿鐓鍌楀亾濞堝灝鏋︽い鏇嗗洤鐓″鑸靛姇椤懘鏌ｅΟ鍏兼毄闁哄鎮傚缁樻媴娓氼垳鍔哥紓浣虹帛閸旀瑩鐛Δ鈧…銊╁醇濠靛洨鈧剟姊洪崫鍕枆闁告ü绮欓崺娑㈠箣閻愮數顔曢梺鐓庛偢椤ゅ倿宕靛▎鎰垫闁绘劖鎯屽▓婊堟煛瀹€鈧崰鏍箖閻戣姤鍋嬮柛顐ｇ箖閻忓酣鏌ｆ惔銏╁晱闁哥姵鐗犻垾锕傛倻閽樺鐎梺褰掑亰閸樿偐娆㈤悙娴嬫斀闁绘ɑ褰冮銏㈢磽瀹ュ懎鈧灝顫忕紒妯肩懝闁逞屽墮椤洩顦撮柟骞垮灲瀹曞崬鈽夊Ο鍏肩叄婵犵數濞€濞佳囶敄閸涱垳鐭嗗鑸靛姈閻撴瑩姊婚崒姘煎殶闁告柨绉归弻宥夋煥鐎ｎ亞浼岄梺鍝勭焿缁犳垼鐏掓繛鎾村嚬閸ㄨ京鐟ч梻鍌欑閹碱偄螞濞戙垹绐楅柡宥庡幖閽冪喐绻涢幋娆忕仾闁稿鍔欓弻锛勪沪鐠囨彃濮庨悗娈垮枙閸楀啿顫忛搹鐟板闁哄洨鍠愰悵鏍⒑缁嬫鍎嶉柛濠冪箞閹即顢欓柨顖氫壕闁挎繂楠搁弸鐔兼煛閸涱喚鐭掗柡宀嬬畱铻ｅ〒姘煎灡鍟告繝娈垮枦椤銆冩繝鍌ゆ綎缂備焦蓱婵挳鏌涘☉姗堥練缁绢厸鍋撶紓鍌氬€风欢锟犲闯椤曗偓瀹曞綊骞庨挊澶嬬€銈嗘磵閸嬫捇鏌涢埡瀣瘈鐎规洘甯掗…銊︽償閵忣潿鍋掑┑鐘茬棄閺夊簱鍋撹瀵板﹥绂掔€ｎ亞鏌堝銈嗙墱閸嬬偤宕戦崒鐐寸厽闁哄啫鍊哥敮鍓佺磼閻樹警娼愮紒缁樼洴閺佹劖鎯旈垾鎰佹交闂備浇顕уù姘跺窗濡ゅ懎桅闁告洦鍨遍弲鏌ユ煕椤愶絿绠樻慨锝冨灲濮婃椽鏌呴悙鑼跺濠⒀屽櫍閺屾稑螣閼姐倗鐓夐悗瑙勬礃閸ㄥ潡鐛Ο鑲╃＜婵☆垳鍘ч獮宥夋⒒閸屾艾鈧悂宕愰幖渚囨晪妞ゆ挴鎳為崶顒佹櫆闁告挆鍜冪床闂備胶绮敋缁剧虎鍘介弲鍫曨敆閳ь剝褰侀梺鎼炲劀瀹ュ牆鎯堝┑鐘殿暯閳ь剙纾崺锝団偓瑙勬礃鐢帡锝炲┑瀣垫晝闁靛繆鏅滈ˉ锟犳⒒閸屾艾鈧悂宕愭搴ｇ焼濞撴埃鍋撻柟顔兼健瀹曞爼鈥栭浣烘创鐎规洜鍠栭、娑㈠焵椤掑嫬鐐婃い鎺戭槹閺咁剟姊虹紒妯哄閻忓繑鐟╁畷銏犆洪鍛幍闂佸吋绁撮弲鐐舵＂闂備焦鎮堕崝鎴犵不閺嶎厼绠栭柕蹇嬪€曠粈鍌炴煟閹惧磭鍑圭紒銊ф暬濮婅櫣娑甸崨顓濇睏闁荤偞绋忛崕鎶藉焵椤掍緡鍟忛柛鎾跺枑娣囧﹪骞栨担鑲濄劑鏌曡箛濠傚⒉闁哄鎮傚缁樻媴閻熼偊鍤嬬紓浣割儐閸ㄥ綊鍩€椤掍礁鍤柛鎾存皑缁顓奸崱娆撴闂佸憡绋戦敃锕傚储鏉堛劎绡€闁汇垽娼у瓭闂佸摜鍣ラ崹宕囧垝閸儱閱囬柕澶涘閸橀潧螖閻橀潧浠滈柣蹇旂箞閹﹢宕ｆ径妯活啍闂佺粯鍔曞Ο濠囧磿閺冨牊鐓涘ù锝囶焾閺嗭綁鏌涢埞鎯т壕婵＄偑鍊栫敮鎺楀磹缂佹鈻旂€广儱顦伴悡娑氣偓骞垮劚妤犳悂鐛Δ鍛厽闁规儳鐡ㄧ粈鍫ユ煃瑜滈崜娆撳储濠婂牆纾婚柟鍓х帛閻撳啰鎲稿鍫濈闁绘棃顥撻弳锕傛煙鐎涙濡囨俊鎻掔墦閺屾洝绠涙繛鎯т壕鐎规洖娲ょ徊浠嬫⒒閸屾瑨鍏岀紒顕呭灦瀵濡搁埡浣叫曢柣搴秵閸犳宕戦崒鐐寸厪濠㈣埖绋戦々顒傜磼閳锯偓閸嬫捇姊婚崒姘偓鎼佹偋婵犲嫮鐭欓柟鐑橆殕閺咁剛鈧箍鍎卞Λ鏃傛崲閸℃稒鐓曟繛鍡楁禋濡插綊鏌涙繝鍐ㄥ闁哄备鈧磭鏆嗛悗锝庡墰琚︽俊銈囧Х閸嬬偤鈥﹂崶顒€鐒垫い鎺戝€归弳鈺冪棯椤撯剝纭鹃崡閬嶆煕椤愮姴鍔滈柍閿嬪灴閹宕烽鐑嗏偓灞剧箾閸忕厧濮嶉柡灞剧洴婵℃悂濡烽敃鈧禒鏉懳旈悩闈涗粶闁哥喐鎸冲畷娲晸閻樻彃绐涘銈嗘尵婵參宕禒瀣拻濞达絿鍎ら崵鈧梺鍦拡閸嬪嫯鐏嬪┑掳鍊撻懗鍫曘€呴弻銉︾厱闁圭偓顨呯€氼剟寮搁幋锔解拺缂備焦锕╁▓鏃堟煟濡も偓濡稓鍒掗鐑嗘僵闁煎摜鏁搁崢杈ㄧ節閻㈤潧孝闁稿﹥鎮傞妴鍌炲箮閼恒儳鍘撻悷婊勭矒瀹曟粌鈻庨幋鐘辩瑝閻庡箍鍎遍ˇ顖滃閸ф鈷戞い鎺嗗亾闁告娲熷畷鍫曞Ω閵夘喖娈奸梻浣告惈椤︿即宕硅ぐ鎺戝偍闂侇剙绉甸埛鎴︽煟閻旂厧浜伴柛銈囧枎閳规垿顢氶埀顒勊夐幘瀵哥彾闁哄洢鍨虹€电姴顭跨憴鍕畵缂傚秴锕顐﹀箛閺夊潡鍞跺銈嗗姂閸ㄦ椽鎮炬导瀛樷拻濞达綀娅ｇ敮娑㈡偨椤栨粌鏋庨摶鐐烘煕閺囥劌鐏欓柍褜鍓ㄧ粻鎾崇暦缁嬭鏃€鎷呴梹鎰暰闂傚倷绀侀幖顐λ囨导鎼晞婵炲棙鍔曢閬嶆煃瑜滈崜娑氭閹捐纾兼繛鍡樺姉閵堢増淇婇悙瀛樼稇闁硅姤绮撳顐︻敋閳ь剟寮幘缁樺亹闂傚牊绋撻妶锕傛⒒娴ｇ瓔娼愮€规洘锕㈤、姘愁槾缂侇喖顭烽獮搴ㄦ嚍閵壯冨箥闂備浇顕栭崹搴ㄥ礃閵娧屽創濠电姷鏁搁崕鎴犵礊閸℃稑绐楁俊銈勮兌閳瑰秴鈹戦悩鍙夋悙閸ユ挳姊洪幖鐐插姶闁诲繑绻堟俊鐑藉煛閸屾粌骞堥梺璇插嚱缂嶅棝宕戦崱妞曡櫣鈧數纭堕崑鎾舵喆閸曨剙顦╅梺鎼炲妼閻栧ジ鎮伴纰辨建闁逞屽墴閵嗕礁鈻庨幘宕囩暰閻熸粌绻樻俊鍫曟晝閸屾稓鍘介柟鑹版彧缁辨洟鎮鹃銏＄厱閹兼番鍔嬮幉楣冩寠濠靛枹褰掓偐瀹割喖鍓伴梺鍝勵儎缁€渚€鍩為幋锔藉亹闁圭粯甯╂导鈧紓浣哄亾瀹曟ê螞閸曨垱绠掗梻浣瑰缁诲倿骞忕€ｎ亶鐒介柣妯煎仺娴滄粓鐓崶銊﹀鞍闁革絽缍婇弻娑㈠Ω閿旂晫鍙嗛梻鍥ь樀閺岋綁骞橀搹顐ｅ闯闂佸湱鏅繛鈧柡灞界Ч閺屻劎鈧綆浜為悷銊╂⒒閸パ屾█闁哄被鍔岄埞鎴﹀幢濞嗗浚鏉告俊鐐€戦崕閬嵥囨导鏉懳﹂柛鏇ㄥ灠鍞梺闈涱樈閻忔繈鏁愭径瀣帾闂佹悶鍎滈崘鍙ョ磾婵＄偑鍊戦崹鍝劽洪悢鍛婂弿闁逞屽墴閺屽秹宕崟顐熷亾閹邦垼妲剧紓浣介哺閹稿骞忛崨顖涘枂闁告洏鍔嶇€氫粙姊绘担鍛婃喐濠殿喚鏁婚幃褔寮撮姀鈥充患闂佺粯鍨煎Λ鍕兜閳ь剟姊虹拠鑼妞ゆ泦鍛濠电姴鍋嗛崵鏇㈡煕椤愶絾绀€缂佺姳鍗抽獮鏍垝鐟欏嫷娼戝┑鈩冪叀娴滆泛顫忛搹瑙勫珰闁肩⒈鍓欓崵顒傜磽娴ｇ懓绲绘い顓炲槻閻ｇ兘骞嬮敃鈧粻娑㈡煛婢跺孩纭堕柛鏃撶畱椤啴濡堕崱妤冪憪闂佺厧鍟块悥濂稿春婵犲洤鍗抽柕蹇娾偓铏吙闂備線娼ч悧鍡浰囨导瀛樺亗婵炲棙鎸婚埛鎴︽煕椤垵娅橀柛搴㈠姍閺屾洟宕堕妸褏鐣洪梺閫涚┒閸斿秶鎹㈠┑瀣闁崇懓銇橀搹搴ㄦ煟鎼淬値娼愭繛鎻掔箻瀹曟繂顓奸崶銊ュ簥濠电娀娼ч鍛矆鐎ｎ喗鐓忓┑鐘茬箰閻︽粍绻涢崗鍏碱棃婵﹤顭峰畷鎺戔枎閹存繂顬夐梺璇叉捣閻熸娊宕楅悩铏仢闁糕晪绻濆畷姗€顢旈崘顏嗘喒闂傚倷娴囬～澶婄暦濮椻偓椤㈡俺顦寸紒顔款嚙椤繈鎳滈棃娑掑亾閸洘鐓熼柟閭﹀幖缁插鏌嶉柨瀣拻缂佽鲸甯￠崺锕傚焵椤掑嫬纾婚柟鍓х帛閳锋帒霉閿濆牜娼愰柛瀣█閺屾稒鎯旈鑲╀桓閻庤娲樼换鍐箚閺冨牆惟闁靛鍎辨禍鍫曟⒒娴ｈ棄袚闁挎碍銇勯敃浣诡棄闁靛棙甯楃换婵嗩潩椤撶姴甯鹃梻浣稿閸嬪懐鎹㈤崘顔㈠顭ㄩ崨顖滐紲濠德板€撶粈浣该归鈧弻锛勪沪閸撗€濮囩紓浣虹帛缁诲牆鐣烽幒鎴旀婵炲棗绻戦悗楣冩⒒閸屾瑦绁版俊妞煎妿濞嗐垽鏁撻悩鏌ユ７闂佹寧绻傞幊鎰板汲閿曗偓閳规垿宕掑搴ｅ姼闂佸憡顨嗘繛濠囧蓟閿濆妫橀柟绋垮閸庢捇鏌ｉ姀鈺佺仭妞ゃ劌锕ら～蹇曠磼濡顎撻梺鑺ッˇ顖炲箚閻愮儤鈷戦柛婵勫劚鏍￠梺鍛婃⒐濞茬喖鍨鹃敃鍌氬瀭妞ゆ洖鎳忓娲⒑闁偛鑻晶顔姐亜閺囶亞绉鐐查叄閹崇偤濡烽敂鐣屽礁闂傚倷鐒﹂幃鍫曞磿閼姐倕绶ら柤鎭掑劤椤╂彃螖閿濆懎鏆為柛瀣у墲缁绘盯宕卞Δ鍐唶濡炪倕娴氭禍鐐垫閹烘鐒垫い鎺戝缁€鍐┿亜閺冨洦顥夊ù鐘叉惈椤啴濡堕崱娆忣潷缂備礁顑嗛崹鐢告箒濡炪倖娲嶉崑鎾绘煛鐏炲墽娲撮柛鈺冨仱瀹曞綊顢欓悡搴渐闂佽楠搁悘姘熆濡皷鍋撳鐓庡箻闁瑰箍鍨归埞鎴﹀炊閵娿儱濡抽梻渚€娼х换鎺撴叏閹绢喖鍌ㄩ柣鎰劋閳锋帡鏌涚仦鍓ф噮闁告柨绉归幃妤冪箔濞戞ɑ鍣虹€规洘鐓￠弻娑氫沪缂併垹娈煎┑鐐村灦鑿ゆ俊鎻掔墛缁绘盯宕卞Ο铏瑰姼濠电偠灏欓…鍫ュ煘閹达附鍊烽柛娆忣樈濡繝姊洪崷顓х劸妞ゎ厾鍏樺畷鍝勨槈閵忕姷顔婇梺鍦仺閸斿瞼绱炴繝鍥ф瀬闁圭増婢橀悙濠囨煃閸濆嫬鈧綊宕幒妤佲拻濞达綀顫夐崑鐘绘煕婵犲啰澧甸柟顔惧厴閸╋繝宕ㄩ鈩冩啺婵犵數鍋為崹顖炲垂閸︻厾涓嶉柨婵嗩槹閻撶喐淇婇娑橆嚋闁绘繍浜弻锝呪攽閹邦亞鏁栫紓浣介哺閹稿骞忛崨鏉戠闁圭儤鍨堕崕鎾绘⒒娴ｄ警鐒炬い鎴濆暣瀹曟劙寮撮姀鈥充患闂佺粯鍨煎Λ鍕兜閳ь剟姊虹紒妯哄闁哄懏绮撻敐鐐差吋閸涱亝鏂€闂佸疇妫勫Λ妤呮倶閿濆鐓忛柛鈩冾殢閸庢垶淇婇崣澶婂闁哄苯妫楅濂稿幢韫囨柨顏烘繝鐢靛仩閹活亞寰婃禒瀣疅闁跨喓濮撮悿顕€鏌ｉ幇顒傛勾闁逞屽墯鐢帡锝炲┑瀣垫晣鐟滃酣鎮挎笟鈧幃妤冩喆閸曨剛顦ㄥ┑鐘灪閿曘垽鏁愰悙娴嬫斀閻庯綆鍓欒ぐ鍡椻攽閻愬瓨缍戞い鎴濇噺缁傚秵銈ｉ崘鈺冨幈濠电偞鍨堕…鍥箺閻樼粯鐓熼柟鎯у船閸旓箓鏌熼绛嬫疁闁轰焦鍔欏畷鎺戔槈濞嗘垵绲跨紓鍌氬€烽懗鑸垫叏閻㈠憡鍤屽Δ锝呭暊閳ь剚妫冨畷姗€顢欓崲澹洦鐓曢柍鈺佸暟閹冲啯銇勯搴℃噽绾捐棄霉閿濆懏鍟為柟顖氱墛缁绘稓娑垫搴ｇ槇閻庤娲樺浠嬪春閳ь剚銇勯幒宥夋濞存粍绮撻弻鐔告綇閸撗吷戝銈冨劚椤︻垶婀佸┑鐘诧工閹冲孩绂嶉崜褏纾肩紓浣诡焽缁犳﹢鏌涢悩璇у伐閾伙綁鏌涘┑鍡楊仱闁规灚鍊濋弻锝夋偄閸濄儳鐓佸┑鐘灪閿曘垹鐣烽鐐茬妞ゆ棁鍋愰悾娲偡濠婂嫭顥堥柣娑卞枛铻ｉ柛蹇曞帶閻濅即姊洪懝鏉款棈闁糕晜鐗犻獮澶嬪鐎涙ǚ鎷绘繛杈剧秬濞咃絿鏁☉娆愬弿濠电姴鍋嗛悡鑲┾偓瑙勬磸閸ㄥジ藝鐎靛摜纾兼い鏃€顑欓崵娆愩亜椤愶絿绠栨繛鐓庣箻婵℃悂濡烽敂閿亾妤ｅ啯鈷掑┑鐘查娴滄粍绻涚拠褍顩紒顔界懇楠炴帒螖閳ь剟鎮块悙顑句簻闁圭儤鍨甸埀顒傛暬瀹曟垿骞橀懡銈呯ウ闂佸壊鐓堥崰鏍ㄦ叏鎼粹槅娓婚柕鍫濈箳缁变即鏌涘Δ鈧崯鍧楁偩閻戣姤鍋ㄧ紒瀣硶椤︺劌顪冮妶鍡樷拻闁哄拋鍋婂畷銏ゅ箹娴ｇ懓鈧灚顨ラ悙鑼虎闁告梹鑹捐灃闁绘娅曢崐鎰版煟濞戝崬鏋涢摶鏍煕濞戝崬鏋ら柛妯绘崌濮婄粯鎷呴崫銉よ檸濡炪倖鍨甸幊姗€骞冨鈧獮姗€顢欓悾灞藉箰闁诲骸鍘滈崑鎾绘倵閿濆骸澧扮悮锔戒繆閵堝洤啸闁稿绋戠叅妞ゆ搩娼块埀顑跨閳藉螣闁垮娼旈梺鍝勵槸閻楁粓鎮￠崼婢盯宕熼娑掓嫽闂佺鏈悷褔藝閿曞倹鐓欐繛鏉戭儌閸嬫捇骞囨担鍦▉闂備線娼荤€靛矂宕㈡總绋垮瀭婵犻潧鐗冮崑鎾荤嵁閸喖濮庡銈忓瘜閸ㄩ亶銆佹繝鍥ㄢ拻濞达絽鎲￠崯鐐寸箾鐠囇呯暤鐎规洝顫夌缓鐣岀矙閹稿海鈧剟姊洪幖鐐插姶闁告挻宀搁幃锟犳偄閸忚偐鍘甸梻渚囧弿缁犳垿鐛Δ鍐＝鐎广儱妫楅悘鎾煛瀹€瀣？闁逞屽墾缂嶅棝宕滃▎鎾崇厺闁割偆鍠愰崣蹇撯攽閻樺弶鍣烘い蹇曞█閺屾盯寮介妸褍鈷岄悗娈垮枟閹告娊骞冮姀銈呭窛濠电姴瀚弳姗€姊婚崒姘偓鐑芥嚄閸洍鈧箓宕奸妷顔芥櫈闂佺硶鍓濈粙鎴犵不娴煎瓨鐓欓梻鍌滎棎椤斿鏌嶈閸撴艾螞閸愩劎鏆︽慨妞诲亾妞ゃ垺鐟╁畷鍙夌珶椤栨碍澶勯柣鎾存礋閺屽秹鍩℃担鍛婄亾濠电偛鐗婇敃銏ゅ蓟閿濆鍋勯柡澶嬪灥椤洤鈹戦纭锋敾婵＄偠妫勯悾鐑筋敃閿曗偓鍞梺闈涱槹閸斞呯礊娓氣偓瀵濡堕崼娑楁睏闂佸湱鍎ゅ濠氬汲椤愶附鈷戦柣鎰閸旂數绱掗悩铏碍闁伙絿鍏樺畷濂稿即閵婏附娅岄梻渚€鈧偛鑻晶鎵磼椤旀鍤欓柍钘夘槸閳诲骸顓奸崟顓犳晨闂傚倷娴囬～澶婄暦濡　鏋栨繛鎴欏灩閸戠娀骞栨潏鍓у矝闁稿鎸搁埢鎾诲垂椤旂晫浜梻浣筋嚙缁绘垹鎹㈤崼銉ユ槬闁绘劕鎼粻锝夋煥閺囨浜鹃梺缁樻惈缁绘繈寮诲☉銏犵労闁告劗鍋撻悾鍏肩箾鐎电顎岄柛銊ゅ嵆閳ユ棃宕橀鍢壯囧箹缁厜鍋撳畷鍥跺晣闂傚倷鑳剁划顖炪€冮崨瀛樻櫇闁靛／鍛厰闁哄鐗勯崝搴ｅ姬閳ь剟姊洪崨濠傚Е濞存粠浜滈‖濠囶敋閳ь剙顫忓ú顏勫窛濠电姴瀚уΣ鍫ユ⒑閹稿孩绌跨紒鐘虫尭閻ｇ兘濮€閵堝懐顔掗梺鍛婃尫閼冲爼鏁嶅┑瀣拺缂佸瀵у﹢浼存煟閻旀繂娲ょ粈澶屸偓骞垮劚椤︽壆鈧艾鎳樺鍫曞醇濮橆厽婢掗梺绋款儐閹搁箖骞夐幘顔肩妞ゆ帒鍋嗗Σ顒勬⒒娴ｅ憡鎯堥柣妤佺矒瀹曟粓鎮㈤悡骞儵鏌涢幇闈涙灈閸烆垶姊洪崘鍙夋儓闁稿﹥鎮傞崺鈧い鎺戝濡垿鏌嶈閸撴盯骞婇幘瀵哥彾濠电姴娲ょ粣妤呮煛瀹ュ骸骞栫紒鈧崼銉︾厱妞ゆ劧绲剧粈鍐煃闁垮鐏寸€殿喖鐖奸幃娆撳级閹搭厽顥嬫俊鐐€х拋锝囩不閹捐钃熸繛鎴炵懅缁♀偓闂佺鏈粙鎴炵閺夋嚦鏃堟偐闂堟稐绮堕梺鍝ュ枑濞兼瑩鎮惧畡閭︾叆闁糕檧鏅滄濠电姷鏁搁崑娑㈡儗閸喓顩叉い蹇撶墕閽冪喖鏌ㄩ弴妤€浜鹃柧浼欑秮閺岋絽顫濋澶婃缂備讲鍋撳┑鐘叉处閳锋垿姊婚崼鐔峰礋闁割偁鍎遍悿鐐節婵犲倻澧曢柣鎾存礋閺岀喖鎮滃鍡樼暦闂佺粯鎸诲ú鐔煎箖濮椻偓閹瑩骞撻幒鍡樺瘱闂備胶鎳撻崯鍧楀箠濮椻偓瀵鈽夐姀鐘愁棟闁荤姵浜介崜杈樄闁哄瞼鍠栭、娆戠驳鐎ｎ偆鏆紓鍌欑贰閸ｎ噣宕㈡總绋跨叀濠㈣泛谩閻旂儤瀚氶柛娆忣樈娴狀參姊虹拠鍙夊攭妞ゎ偄顦叅婵せ鍋撻柟顕嗙節閺佹捇鎮╅懠鑸垫啺婵犵數鍋為崹鍫曟儗椤斿皷鏌︽い蹇撶墛閻撴瑦銇勯弽褎顥滈柡鍫墴钘熼柨鐔哄У閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬪┑鍥舵＆濡ょ姷鍋為崝娆撶嵁閺嶃劎鐟瑰┑鐘插閳笺倖绻濋悽闈涒枅婵炰匠鍥舵晞闁圭増婢橀弸渚€鏌涢幇闈涙灍闁绘挸绻橀悡顐﹀炊閵婏妇顦ラ柛鐔告倐濮婃椽妫冨☉姘拡闂侀潻缍囩紞浣割嚕婵犳碍鏅查柛鈩兠崝鍛存⒑闂堟稓澧曢悗娑掓櫇缁辩偤宕煎┑鍐╂杸闂佺粯鍔栬ぐ鍐棯瑜忕槐鎺楊敊閼恒儱纰嶅銈嗘穿缂嶄線銆侀弴銏℃櫇闁逞屽墰缁鎮烽幊濠傜秺閺佹劙宕ㄩ钘夋瀾闂備礁鎲″Λ鎴犵不閹达腹鈧棃宕橀鍢壯囨煕閳╁喚娈橀柣鐔村姂濮婃椽骞愭惔銏⑩敍婵犵鈧櫕宸濋柛鎺撳浮瀵噣宕奸悢铚傜紦闂備礁鎲＄粙鎴︽晝閿曞倸鍌ㄩ梺顒€绉甸埛鎴犵磽娴ｅ箍鈧偤骞嬮敃鈧粈鍫熸叏濮楀棗鍘撮柡瀣⒐缁绘繃绻濋崒婊冾杸闂佺粯鎸婚悷锕傚Φ閸曨垰鍗抽柣鎰儗濡倗绱撴担鍙夘€嗛柛瀣崌閺岋絾鎯旈姀鈺佹櫛闂佸摜濮甸〃濠囩嵁閹扮増鎯炴い鎰剁到瀵潡姊洪柅鐐茶嫰婢ф挳鏌＄仦璇插闁宠棄顦灒濞撴凹鍨幃锝嗕繆閵堝洤啸闁稿绋撶划鏃堟偡闁附缍庣紓鍌欑劍钃卞┑顖涙尦閺屾稑鈽夊鍫濅紣闂佸搫妫楅悧蹇曟閹惧瓨濯寸紒娑橆儏濞堫參姊虹粙鍖″伐妞ゎ厾鍏樺畷娲焵椤掍降浜滈柟鍝勭Ф閸斿秹鏌ｉ妸锕€鐏撮柡灞剧缁犳盯寮崱鈺€閭柟顕€绠栭幃婊堟寠婢跺﹤绁梻浣瑰缁嬫垹鈧凹鍣ｅ鍓佺矙鎼存挻鏂€闂佺粯鍔栧娆撴倶閿曞倹鐓熼柣鏃€绻傚ú銈夊磼閵娾晜鐓欓柛鎾楀懎绗￠梺绋款儌閸撴繄鎹㈠┑鍥╃瘈闁稿本鍑规导鈧梻浣规た閸樼晫鏁悙鍝勭劦妞ゆ帒鍠氬鎰箾閸欏鐒介柛鎺撳笒閻ｆ繈宕熼崜浣衡棨婵犵數濞€濞佳囶敄閸℃稑鍚归悗锝庡枟閳锋帡鏌涢銈呮灁闁崇鍎崇槐鎾诲礃閳哄倻顦板┑顔硷功缁垶骞忛崨瀛樻優闁荤喐澹嗛濂告⒒娴ｇ懓顕滅痪鏉跨У缁岃鲸绻濋崶鑸垫櫖濠殿喗蓱瀹曟﹢宕ラ锔藉€甸悷娆忓缁€鍫ユ煛娴ｇ瓔鍤欐い鏇秮楠炴﹢顢欓挊澶嗗亾閻戣姤鐓冮柛婵嗗閳ь剙缍婂鍫曞箹娴ｅ厜鎷绘繛杈剧秬濞咃絿鏁☉銏＄叆婵鍩栭悡鐔兼煏閸繃鍣哄璺哄缁辨帡寮崒姘€诲銈庡亝缁捇宕洪埀顒併亜閹烘垵顏╅柦鍐枛閺屻劌鈹戦崱鈺傂︾紓浣哄У缁嬫帡濡甸崟顖氱闁规惌鍨遍弫楣冩⒑鏉炴壆绐旂紒鐘崇墪椤繐煤椤忓拋妫冨┑鐐村灦閻燂箓骞冨▎鎾寸厽閹兼番鍨婚悡顖炴煕濡や礁鈻曢柟顔诲嵆椤㈡岸鍩€椤掑嫮宓侀柟鐑橆殔缁狅絾銇勯幘璺轰沪闁稿鍨跺缁樻媴鐟欏嫬浠╅梺绋垮缁挸鐣峰鈧畷婊嗩槷闁稿鎹囧鍫曞箣閺冣偓閺傗偓闂備胶绮敋闁诲繑宀稿鎶藉煛閸涱喚鍘遍柣搴秵閸嬪棗煤鐎涙﹩娈介柣鎰嚋姒氨绱掗悩宕団槈闁宠棄顦埢搴ょ疀鎼达絿绉块梻鍌氬€烽懗鍓佸垝椤栫偐鈧箓宕奸妷顔芥櫔閻熸粍妫冮獮蹇涘箣閿旇棄浜滈梺绋跨箺閸嬫劙宕ｉ崱妞绘斀闁绘绮☉褎淇婇锝団姇闁哄懎鐖兼慨鈧柕鍫濇閸樹粙姊洪棃娑氬闁稿﹤鎲＄粋宥嗐偅閸愨斁鎷婚梺绋挎湰閻熝囁囬敃鍌涚厵缁炬澘宕禍婊堟偂閵堝鐓忓┑鐐靛亾濞呭懐鐥崜褏甯涢柟渚垮妼椤啰鎷犻煫顓烆棜闂佽姘﹂～澶娒洪敃鍌氱；闁告洦鍠氭禍娆撴⒒娓氣偓閳ь剛鍋涢懟顖涙櫠閹绢喗鐓曢柍鍝勫暙娴犺鲸顨ラ悙宸剶闁轰礁鍟撮崺鈧い鎺戝閸嬪倿鏌ㄩ悢鍝勑ｉ柣鎾存礋閺屽秹鍩℃担鍛婃婵炲濯存俊鍥╂閹烘惟闁靛鍠氶崥瀣⒑閸濆嫮鐒跨紒鏌ョ畺楠炲棝寮崼婵愭綂闂侀潧绻嗛弲婊冣枔鐟欏嫮绡€闁汇垽娼цⅷ闂佹悶鍔嶅浠嬪极閸愵喖顫呴柕鍫濆暊閸嬫挻鎷呴崜鍙夊兊闂佽偐顭堥悘姘枍濠婂嫮绡€闁靛骏绲剧涵楣冩煥閺囶亞鐣垫い銏＄懃閻ｆ繈宕熼鑺ュ闂備浇宕甸崰鎾存櫠濡ゅ懎绠氶柛顐ゅ枍缁诲棙銇勯幇鍓佹偧闁瑰啿娲弻鐔碱敊缁涘鐣风紓浣虹帛缁诲倿锝炲┑瀣垫晣婵炴垶鐟ラ褰掓⒒娴ｈ棄鍚归柛鐘冲姍閹兘濡疯閸嬫挸顫濋悡搴♀拫閻庤娲樼换鍫熶繆閸洖骞㈤柟閭︿簽閻╁酣姊绘担鍛婃儓婵炲眰鍨藉畷婵堜沪缁涘娈ㄥ銈嗘閺侇噣宕戦幘鑸靛枂闁告洦鍓涢敍姗€姊洪幖鐐插缂侇喗鐟╅悰顕€宕橀埡鍐炬祫闁诲函缍嗘禍婊呯玻濞戞瑧绡€闁汇垽娼у瓭闁诲孩鍑归崜鐔兼偘椤斿槈鏃堝川椤旇瀚藉┑鐐舵彧缂嶁偓婵炲拑绲块弫顔尖槈濞嗗秳绨诲銈嗘尵閸嬬偤宕板Ο灏栧亾鐟欏嫭绀冩繛鑼枑娣囧﹪鎳滈棃娑氱獮濠碘槅鍨崇划顖氣枍閸℃稒鈷掑ù锝堟鐢稒銇勯鐐村窛闁告帗甯￠、娑㈡倷閼碱剨绱梻浣稿閸嬪懎煤濠婂牆鐭楅柟鍓х帛閻撴洟鏌曟径瀣仴闁兼椿鍨跺畷婊堟偋閸垻鐦堢紒鍓у鑿ら柛瀣崌瀹曟﹢宕ｆ径濞惧亾椤栫偞鈷戦梻鍫熺⊕閹兼劙鎮楀顓熺凡妞ゆ洩缍侀、妤呭磼濞戞锛忛梻渚€娼ц噹閻忕偠濮ゅ▍鏂库攽閻樺灚鏆╁┑顔惧厴閵嗗倿顢欓悙顒夋綗闂佸搫娲㈤崹鍦矆閸屾稒鍙忔俊鐐额嚙娴滈箖鎮楃憴鍕婵＄偘绮欏顐﹀箻缂佹ê浜归梺鑲┾拡閸撱劎妲愰崣澶岀瘈闁汇垽娼у瓭闂佹寧娲忛崐婵嗙暦椤栫儐鏁冮柕鍫濇矗缁楀鈹戦悙鍙夆枙濞存粍绻堥崺娑㈠箳濡や胶鍘遍柣蹇曞仜婢т粙骞婇崨瀛樼厱闁哄倽娉曟晥闂佽鍠楅〃鍫㈠垝椤撶偐妲堟俊顖濐嚙濞呫倝鎮楃憴鍕闁绘搫绻濆璇测槈濮橆偅鍕冪紓鍌欓檷閸ㄧ懓鈻撹閳规垿鎮欓崣澶嗘灆婵炲瓨绮嶇划灞矫洪崹顔规斀闁绘﹩鍠栭悘杈ㄧ箾婢跺娲撮柡浣稿暣閺佸啴宕掑顒€浜舵繝鐢靛仜濡﹥绂嶅┑瀣厱闁硅揪闄勯悡鏇㈡煙閻愵剚缍戠紒鑼额嚙闇夋繝濠傚婵秹鏌″畝鈧崰鏍х暦濮椻偓瀹曪絾寰勬繝鍐悍闂佽姘﹂～澶娒哄鈧畷褰掑锤濡ゅ啫绁﹀┑顔姐仜閸嬫捇鏌熼搹顐ょ煉婵☆偄鍟埥澶娾枎閹存柨浜炬い鎾卞灪閳锋帒霉閿濆懏鍟為柛鐔哄仦缁绘稓鎷犺閻ｇ數鈧娲樼划宀勫煡婢舵劕顫呴柍鈺佸暞閻濐偅绻濆▓鍨灍闁靛洦鐩畷鎴﹀箻鐎涙ê寮挎繝鐢靛Т閸燁垶濡靛┑鍥舵闁绘劕顕晶鐢告煙椤旂晫鎳囨鐐存崌楠炴帒鈹戦崼姘壕闁惧浚鍋傜换鍡涙煟閹板吀绨婚柍褜鍏欓崐婵嗙暦閵徛板亝闁告劑鍔庨ˇ褍鈹戦埥鍡楃仴婵炲拑缍佸鎶芥晜閻ｅ瞼顔曢悗鐟板閸犳洜鑺辨繝姘厽闁圭儤鍨规禒娑㈡煏閸パ冾伃妤犵偞甯掗鍏煎緞鐎ｇ鍋撻弽銊х閻庢稒顭囬惌瀣磼椤旇姤宕岀€殿喖顭烽幃銏ゅ礂閻撳簶鍋撶紒妯圭箚妞ゆ牗绻冮鐘绘煕濡濮嶆慨濠冩そ瀹曘劍绻濋崘锝嗗闂備礁鎽滄慨鐢稿箰閹灛锝夊箛閺夎法顔婇梺瑙勫劤绾绢厾绮ｉ悙鐑樼厽闊洦娲栨禒褔鏌涚€ｎ偅灏悮娆撴煕椤愮姴鍔滈柍閿嬪灴閺屾稑鈹戦崱妤婁痪濠电姭鍋撻柟娈垮枤绾惧ジ鎮楅敐搴′簼鐎规洖鐭傞弻娑㈠煘閹傚濠碉紕鍋戦崐鏍暜閹烘鏅濋柨鏂垮⒔閻捇姊婚崼鐔烩偓浠嬫偡闁妇鍙嗛梺鍛婃处閸橀箖鎮℃径濠庢富闁靛牆鍟悘顏呬繆椤愩垹鏆ｉ柕鍡曠椤粓鍩€椤掍焦鍙忛柍褜鍓熼弻銊モ槈濡警浠煎Δ鐘靛仜缁夊灚绌辨繝鍥ㄥ€锋い蹇撳閸嬫捇寮借濞兼牜鎲搁悧鍫濈瑨闁告垹濮撮埞鎴︽偐瀹曞浂鏆￠梺鎼炲€愰崑鎾绘⒑閼姐倕校濞存粈绮欏畷婵囧緞閹邦剛锛涢梺瑙勫礃閸╂牠宕伴崱娑欑厱闁哄洢鍔屾晶鐗堛亜閿斿搫濮傛慨濠呮缁瑩宕稿Δ濞惧亾濡ゅ懏鐓忛柛顐ゅ枔閹藉啯淇婇銈呮瀻妞ゎ亜鍟存俊鍫曞幢濡攱瀚婚梻浣规偠閸斿秶鎹㈤崟顖氱闁靛繈鍊曢獮銏＄箾閹寸偟鎳呴柛妯兼暩缁辨捇宕掑▎鎴濆闂佹寧姘ㄧ槐鎺戭渻閿曗偓閸犳岸鎮㈤崱娆愬枑婵犻潧鐗忔稉宥夋煙閹规劦鍤欓柦鍐枛閺屽秹濡烽妷褝绱為梺鍝勬濡繈寮诲鍫闂佸憡鎸鹃崰搴ㄦ偩闁垮顕遍柡澶嬪灥閸炪劌顪冮妶鍡樺暗闁稿鍠栭幃楣冨传閸曘劍鏂€闂佺粯鍔曞鍫曀夐悙鐑樼厵閻忓繑鐗楀▍濠勨偓娈垮櫘閸嬪﹤鐣烽崡鐐╂婵炲棙鍨电敮妤呮煟閻斿摜鐭嬬紒顔芥尭閻ｅ嘲顭ㄩ崘鐐兊闁荤娀缂氬▍锝夊蓟瑜斿娲礈閹绘帊绨煎┑鐐额嚋缁犳挸顕ｉ銏╁悑濠㈣泛顑囬崢浠嬫⒑瑜版帒浜伴柛鎿勭畵瀹曠敻鎮㈤崗鑲╁幈濠殿喗銇涢崑鎾趁瑰鍐煟鐎殿喖顭烽幃銏ゅ礂閻撳孩鐣伴梻浣稿暱閹碱偅鍒婄紒妯虹窞闁归偊鍘鹃崢閬嶆⒑鐟欏嫬鍔ゆい鏇ㄥ幘缁鎮欓幖顓燁啍闂佺粯鍔栧娆撴倶閹绢喗鐓涘ù锝囨嚀婵秶鈧娲栭悥濂稿春閿熺姴绀冮悹鎭掑妼缁ㄣ儵姊婚崒娆戭槮闁圭⒈鍋婅棟妞ゆ牜鍋為崑瀣煕閺囥劌鐏犵紒鈧径鎰€堕柣鎰暩閸欐挾鎲搁悧鍫濅刊闁轰礁锕鍝勨枎閹呬哗婵炲瓨绮庨崑鎾舵崲濞戙垹閱囨繝闈涚墔閾忓骸鈹戦悙鍙夊櫤闁挎洏鍨藉璇测槈閵忕姷顔掗柣搴ㄦ涧閹诧繝宕氬☉妯滄棃鎮╅棃娑楁勃闂佹悶鍔岄悘婵嬫偩閻戣姤鍋勭痪鎷岄哺閺咁剙鈹戦鍡欏埌闁汇劎鍏樺鏌ユ偐鐠囪尪鎽曢梺闈浥堥弲娑氱尵瀹ュ鐓曢柕澶樺枤閸樻稒淇婇銏狀伃婵﹥妞藉畷顐﹀礋闂堟稑澹夌紓鍌欑椤戝棝骞愰幆顬綁骞囬弶璺啋闁荤姴娲╃亸娆撴晬濠婂啠鏀芥い鏃€鏋绘笟娑㈡煕韫囨棑鑰跨€规洘鍨块獮姗€骞栭鐔溠囨煙閼圭増褰х紒鎻掓健閹偤宕楅懖鈺冾啎闂佸湱鍋撳娆撴倿瑜版帗鐓曢悗锝庡亝鐏忎即鏌曢崶褍顏┑顔瑰亾闂佹寧绋戠€氼剟鍩涘畝鍕€甸悷娆忓绾炬悂鏌涢弬璺ㄧ劯闁挎繄鍋ゆ慨鈧柕鍫濇啒瑜旈弻娑樷槈閸楃偞鐏堥梺鍝勵儑婵炩偓婵﹨娅ｉ幏鐘诲灳閾忣偆浜炵紓鍌欑贰閸犳鎮烽埡鍛仒妞ゆ洍鍋撶€殿喕绮欓、姗€鎮㈢亸浣镐壕闁绘垼濮ら悡鍐级閻愰潧顣兼い锕€鍢查…璺ㄦ喆閸曨剛顦ㄧ紓浣虹帛閻╊垶鐛鈧鍫曞箣閻樻彃袪闂傚倷鑳堕…鍫ヮ敄閸℃稑绠板Δ锝呭暙閻掑灚銇勯幒宥囪窗闁哥喎绻橀弻娑㈡晲鎼粹剝鐝濋悗瑙勬礃婵炲﹪寮幇鏉垮窛妞ゆ牗绋掗鏇㈡⒒娴ｈ櫣甯涢柟绋挎憸閼洪亶宕奸弴鐐靛摋婵炲濮撮鍡涙偂閺囥垺鐓冮柍杞扮閺嗙喖鏌熼崘鍙夊櫧闁逞屽墲椤煤閺嶎厼绠规い鎰剁畱閻撴﹢鏌熸潏楣冩闁哄拋鍓熼弻娑㈠即閵娿儰绨甸梺鍝勵樈閸欏啫顫忛搹鍦煓闁告牑鍓濋弫楣冩⒑缂佹﹩娈曟繛鍙夌箞閹鈧綆鍋嗙粻楣冨级閸繂鈷旈柛鎺嶅嵆閺岀喖鎳為妷褏鐓夐悗娈垮枟婵炲﹪寮崘顔肩＜婵炴垶鑹鹃獮妤呮⒒娓氣偓濞佳呮崲閹烘挻鍙忛梺鍨儑椤╅攱绻涢幋娆忕仾闁绘挻鐩弻娑㈠焺閸愬墽鍔烽梺娲诲幖椤戝洨妲愰幒鏃傜＜婵☆垰鍚嬮崚娑樜旈悩闈涗粶妞ゆ垵鎳橀崺銏℃償閵堝洨鏉搁梺鍝勬处濮樸劌螞椤栫偞鈷掗柛灞剧懅閸斿秴鈹戦悙璇ц含鐎殿喓鍔戦弻鍡楊吋閸涱厾鈧參姊虹粔鍡楀濞堟梻绱掗悩宕囧⒈闁瑰弶鎮傞幃褔宕煎┑鍫㈡噯闂備胶绮崝鏇㈡晝閵夆晛桅闁告洦鍠氶悿鈧梺鍦亾閸撴碍瀵奸埀顒佺節濞堝灝娅欑紒鎻掝煼瀹曞綊鎳￠妶鍡╂綗闂佽鍎抽悺銊﹀垔閹绢喗鐓曟繝闈涙閻濇棃鏌ㄥ┑鍡樺闁绘柨妫濋弻锝夋偄閸濆嫷鏆銈冨劤婵灚绌辨繝鍥х煑濠㈣泛锕ら～鎺懳旈悩闈涗沪閻㈩垪鈧剚鍤曟い鏇楀亾鐎规洘甯掗…銊╁箛椤旇偐鍝庡┑鐘垫暩婵兘銆傞挊澹╋綁宕ㄩ弶鎴濈€繛鏉戝悑濞兼瑧绮荤憴鍕╀簻闁圭増鍎奸铏圭磽瀹ュ棛澧垫鐐寸墪鑿愭い鎺嗗亾濠碘€茬矙閺屽秹鏌ㄧ€ｎ亞浼岄梺鍝勭焿缂嶄線骞冮姀銏㈢煓婵炲棛鍋撻ˉ瀣⒒娴ｉ涓茬紓宥呮瀹曪綁宕橀鑹版憰濠电偞鍨崹瑙勫劔闂備線娼ч悧鍡椕洪妸鈺傚亗闁瑰墽绮埛鎴犵磽娴ｅ鑲╂闁秵鐓曢柨婵嗙箳閸掍即鏌ｉ敐鍥у幋鐎规洖銈稿鎾Ω閿旇姤鐝滄繝鐢靛О閸ㄧ厧鈻斿☉銏╂晞闁糕剝銇涢弸宥夋煛瀹ュ啫濡跨紒鈾€鍋撶紓浣稿⒔婢ф鎽銈庡亜閿曨亪寮诲☉銏犖╃憸搴ㄥ汲椤掑嫭鐓ユ繝闈涚墕娴狅妇鈧灚婢樼€氫即鐛崶顒夋晣闁绘劖褰冮ˉ鎺楁⒒閸屾凹鐓柛瀣鐓ら柨鏂垮⒔閻瑩鏌熼悜姗嗘當闁绘挻娲熼弻鐔兼倻濡儤顔呴悷婊呭鐢寮查弻銉︾厱婵炴垵宕弸娑㈡煛閸℃澧︽慨濠冩そ瀹曨偊濡烽妷锔句簴闂備胶顭堥鍐磹濠靛棭鍤曞┑鐘崇閺呮彃顭跨捄渚剰濞存粍绮撳娲传閸曞灚效闂佹悶鍔岄悘姘跺箞閵娾晜鏅濋柛灞剧〒閸欏啫鈹戦埥鍡楃仴鐎规洜鏁哥划濠氭倷閻戞鍘搁悗鍏夊亾閻庯綆鍓涢弳鐘绘煣娴兼瑧鍒伴柕鍡樺笒椤繈鎮℃惔锝勭敾闁诲孩绋掔换鍫濐潖缂佹ɑ濯撮柛娑橈攻閸庢挸顪冮妶鍡楃仴婵☆偅顨夐悘瀣⒑閸涘﹤濮﹂柛鐘崇墵閹锋垿鎮㈤崗鑲╁弳濠电娀娼уΛ顓炍ｈぐ鎺撶厸闁告侗鍠氶崣鈧梺鍝勬湰缁嬫垿鍩ユ径鎰闁绘劖褰冮婊勭節瀵版灚鍊曢惃娲煛娴ｇ瓔鍤欐い顐㈢箻閹煎綊宕烽鐘靛幆婵犵數鍋涘Λ娆撳磿閹惰棄绀堥梺顒€绉甸埛鎴︽煕閿旇骞楅柛銈傚亾婵犵數鍋涢惇浼村磹濠靛绠栭柟顖嗗懏娈濋梺褰掓敱濮婄懓顫忚ぐ鎺戠闁告稒娼欐导鐘绘煏婢诡垰鎳庣粊锕€鈹戦悩鍨毄濠殿喚鍏樺顐﹀川婵犲啫寮块悗瑙勬礀濞层劑鎯岄崱妞尖偓鎺戭潩閿濆懍澹曢梺鑺ヮ焽閸犳劙骞堥妸銉庣喖宕归鎯у缚闂備焦濞婇弨杈╂暜閿熺姴钃熸繛鎴炵煯濞岊亪鏌涢幘妤€瀚▍妯讳繆閻愵亜鈧呮媼閿濆洨涓嶉柟鎹愵嚙閽冪喖鏌ｉ弮鍌氬妺閻庢碍姘ㄩ幉姝岀疀閺囩偛袣闂侀€炲苯澧撮柟顔筋殘閹叉挳宕熼鍌ゆО缂傚倷娴囬褔鎮ч幘鎰佸殨妞ゆ劧绠戠壕濂告煟閹邦厽缍戝ù鐘层偢閹宕楁径濠佸濠电姷鏁告慨鎾疮閹绢喖鏋佹繝濠傚暊閺€浠嬫煟濡櫣浠涢柡鍡忔櫅閳规垿鎮欓埡浣峰濠电姷鏁搁崑姗€宕犻悩璇茬倞闁肩鐏氬▍鍫ユ⒒娴ｇ儤鍤€妞ゆ洦鍘介幈銊︻槹鎼达絿鐒兼繝鐢靛Т濞诧箓鎮″☉姘ｅ亾楠炲灝鍔氬Δ鐘叉啞缁傚秹骞囬悧鍫㈠幈闁诲函缍嗛崑鍛暦瀹€鍕厽婵炴垵宕▍宥団偓瑙勬礀缂嶅﹪銆佸▎鎾村亗閹兼惌鍠楃紞鎾绘⒒閸屾艾鈧兘鎳楅崼鏇炵疇闁规崘顕ч悿顕€鏌涜椤у倿宕堕渚囨濠电偞鍨靛畷顒€鈻撻妸鈺傗拺闂傚牊鍗曢崼銉ョ柧婵犲﹤鐗嗛崥鍦偓骞垮劚椤︿即鎮¤箛鎿冪唵闁煎摜鏁搁妴鎺楁倵娴ｅ啫浜圭紒杈ㄥ浮婵℃悂濡烽鎯ф倯婵犳鍠栭敃銉ヮ渻閽樺鏆︽い鎰剁畱缁€瀣亜閹板墎绋绘い鏂垮濮婄粯鎷呮笟顖滃姼闂佹寧娲╃粻鎾荤嵁婵犲洤绠婚悹鍥皺閸樻椽鎮楅獮鍨姎妞わ富鍨跺畷锟犲箮閼恒儳鍘藉┑鈽嗗灠閸氬寮抽埡鍛叆婵炴垶鐟х粻鐐存叏婵犲懏顏犵紒顔界懇楠炴劖鎯旈姀鈥愁伆缂傚倸鍊风粈渚€顢栭崱娑樺瀭闁割煈鍠氶弳锔姐亜閹般劍瀵ｆ繛宸憾閺佸倿鏌涘☉鍗炵仩妤犵偞鍔欏铏规嫚閼碱剛顔婇梺绋款儐缁嬫帡寮查懜鐢殿浄閻庯綆浜為崢鎰版⒑閸濆嫭鍌ㄩ柛銊︽そ閹€斥枎閹扳晙绨婚梺鍝勭Р閸斿酣鍩婇弴鐔翠簻闁靛鍎虫晶锕傛煛鐏炵澧查柟宄版嚇閹兘寮跺▎鐐稈闂佽姘﹂～澶娒洪弽褏鏆︽い鎺戝暟娴滀粙姊绘担鍝勫付妞ゎ偅娲熷畷鎰板冀椤撱劎绋忓┑鐘诧工鐎氼喚寮ч埀顒傜磼閻愵剚绶叉い锕佷含婢规洟宕稿Δ浣哄幈闁诲函缍嗛崑鍕倶鐎电硶鍋撶憴鍕闁告梹鐟╅悰顔锯偓锝庡枟閺呮繈鏌嶈閸撶喎鐣疯ぐ鎺戠＜婵炴垶姘ㄩ鏇㈡倵閻熸澘顥忛柛鐘虫礈閼洪亶鎳￠妶鍥╋紲闂佺粯锚绾绢參宕ｉ埀顒勬⒑閸濆嫭婀伴柣鈺婂灡娣囧﹪鎮滈挊澶岊吅濠电娀娼уú銈呪枍閵堝應鏀介柣鎰皺婢ф盯鏌涙惔銏犫枙闁糕晝鍋ら獮瀣晜缂佹ɑ娅撳┑鐘愁問閸犳宕濋幒鏂垮灊闁割偅娲橀埛鎴犵磼鐎ｎ偒鍎ラ柛搴㈠姍閺岀喓绮欏▎鍓у悑婵犵绱曢弫璇茬暦閻旂⒈鏁嶆慨妯哄悑缂嶅倿姊绘担鐟邦嚋缂佸鍨归埀顒佸嚬閸欏啫鐣烽搹顐㈩嚤閻庢稒锚閳?",
            response_language,
        )
    if not teaching_note:
        teaching_note = _localized_text(
            "Keep the same lane and ask for one visible, verifiable conclusion on the next turn.",
            "缂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈囩磽瀹ュ拑韬€殿喖顭烽幃銏ゅ礂鐏忔牗瀚介梺璇查叄濞佳勭珶婵犲伣锝夘敊閸撗咃紲闂佽鍨庨崘锝嗗瘱闂備胶顢婂▍鏇㈠箲閸ヮ剙鐏抽柡鍐ㄧ墕缁€鍐┿亜韫囧海顦﹀ù婊堢畺閺屻劌鈹戦崱娆忓毈缂備降鍔岄妶鎼佸蓟閻斿吋鍎岄柛婵勫劜閸嬔呯磽娴ｄ粙鍝洪悽顖ょ節瀹曟椽鍩€椤掍降浜滈柟鍝勭Х閸忓瞼绱掗埦鈧崑鎾绘⒒娴ｈ鍋犻柛搴灦瀹曟繃鎯旈妸銉ュ亶闂佺懓澧界划顖炲磻閳╁啰绡€濠电姴鍊搁顐︽煟椤撶喎绗ч柍褜鍓濋～澶娒哄Ο鐓庡灊闁规崘顕х粻鏍煏韫囧鈧牠宕戦崒鐐茬婵烇綆鍓欓埀顒佺墵楠炲鎮ч崼銏㈢槇闂佹眹鍨藉褎绂掗敃鍌涚厱闁靛绠戦崝鍓佹喐閻楀牏鐭婇柍瑙勫灴閸╁嫰宕橀妸褏銈烽梻浣虹帛椤ㄥ棝骞戦崶褜鍤曢悹鍥ㄧゴ濡插牊淇婇娑氱煁婵☆偄鍟悾宄邦潨閳ь剚淇婇幖浣肝ч柛鈩冾殘閸樺崬鈹戦悩鍨毄闁稿鐩、姘额敇閻斿嘲鐏佸銈嗘尪閸ㄥ綊鎯屽Δ鍛厱闁规壆鏁搁崢娑欑箾閸忚偐澧紒缁樼☉椤斿繘顢欓懡銈囨晨濠电偟顥愰崑鎰箾閳ь剟鏌＄仦鍓ф创鐎殿喗鎸虫俊鎼佸Ψ閵夈垺瀚藉┑鐘殿暯濡插懘宕戦崨瀛樺剮妞ゆ牗鍑瑰鏍ㄧ箾瀹割喕绨荤€瑰憡绻傞埞鎴︽偐閹绘帩鍔夐梺浼欑到閻栫厧顫忓ú顏勪紶闁靛鍎查悗璇测攽閻愮偣鈧鎹㈠┑瀣瀬闁规壆澧楅崐鐑芥煕閹捐尪鍏岄柡澶岊焾閳规垿鎮欓弶鎴犱桓闂佽崵鍠嗛崕鐢稿春閳ь剚銇勯幒鎴濃偓鑽ゆ暜濞戞〒搴ㄥ炊瑜濋煬顒併亜閵忥紕鈽夐柍璇查叄楠炴帒鈹戦崱妞倝姊婚崒娆戝妽闁诡喖鐖煎畷鎰板箣閿曗偓绾惧綊鏌￠崶銉ョ仼闁绘挻锕㈤弻鐔告綇妤ｅ啯顎嶉梺绋匡功閸忔﹢寮诲☉妯锋瀻闊浄绲鹃埢鎾斥攽閳藉棗浜剧紒缁樼箓椤繐煤椤忓嫮顔愰梺缁樺姈瑜板啴鈥栫€ｎ亶娓婚柕鍫濆暙閻忊晠鏌ㄩ弴銊ら偗闁绘侗鍠栬灃闁告粈鐒﹂弲婵嬫⒑閹稿孩顥嗙悮娆撴煙瀹勯偊鐓兼慨濠呮缁瑩骞愭惔銏″闂備浇宕甸崳锔戒繆閸モ晛鍨濆┑鐘叉搐缁犮儲銇勯弮鍌涘殌濞存粓绠栭幃宄扳枎韫囨搩浠剧紓浣插亾闁割偁鍎查悡娑樏归敐鍥╂憘闁搞倖鐟╅弻锝夋晲婢跺鏆犻柣搴ㄦ涧閵堢顕ｉ崼鏇炵婵犻潧艌閸嬫捇宕归瑙勬杸闂佺粯鍔栧娆撴倶閿斿浜滄い鎾跺仦閸犳﹢鏌℃担鍝バч柟顔哄灲瀹曟浜搁弽銊ヮ伜婵犵數鍋為幐濠氭嚌閹灐娲Χ閸℃ɑ鐝峰銈嗘煥婢х晫澹曢悡搴唵閻犺櫣鍎ゅ﹢浼存煛閸♀晛澧伴柍褜鍓氶鏍窗濡ゅ嫨浜归柛鎰靛枛閻撴﹢鏌熺€电袥闁稿鎹囬弫鎰償閳ヨ尙鏁栭梻浣告啞閿曗晜绂嶉鍕庢盯宕ㄩ幖顓熸櫇闂侀潧绻嗛崜婵嬪箖濞嗗浚娓婚柕鍫濇閻忋儵鏌熼搹顐€跨€规洘妞介崺鈧い鎺嶉檷娴滄粓鏌熺€电浠滈柛鏂诲€濋弻宥堫檨闁告挻姘ㄩ幑銏ゅ磼閻戝棙鏅梺鎸庣箓椤︿粙寮崘顔界叆闁哄洦顨呮禍鍓х磼閻愵剙鍔ら柕鍫熸倐瀵鏁愭径濠勭杸濡炪倖甯掗ˇ顖氣枔閸洘鈷戦柛娑樷姇椤忓嫮鏆︽い鎺戝閳ь剚妫冨畷姗€顢欓崲澹洦鐓曢柍鈺佸枤濞堟梻鎮伴懖鈺冪＝闁稿本鐟︾粊浼存倶韫囷絼绨婚柍缁樻瀵挳鎮╅幓鎺斾喊闂佽崵濮村ú銈呂熸繝鍌ょ劷闁冲搫鎳庣痪褔鏌涢锝団槈濠碉紕鍘ч湁闁绘灏欑粻浼存煃鐟欏嫬鐏撮柟顔规櫇缁辨帒螣婵犳碍鏆樺┑锛勫亼閸婃牠宕归棃娴虫稑鈹戠€ｎ亝妲┑鐐村灟閸ㄥ湱绮婚敐澶嬬叆闁哄啫娲﹂ˉ澶娒归悪鈧崹璺侯潖濞差亜绠归柣鎰絻婵埖绻涚€涙鐭嬬紒顔芥崌楠炲棝宕橀鑺ュ劒闂侀潻瀵岄崢楣冩晬濠婂牊鈷戠紓浣光棨椤忓牆鐤柛褎顨呴悡婵嬫煛閸ャ儱鐏柣鎾寸洴閹﹢鎮欓幓鎺嗘寖闂侀潧妫欑敮锟犲蓟瀹ュ牜妾ㄩ梺鍛婃尪閸斿海妲愰悙鍝勫耿婵炴垶顭囬ˇ顓炩攽閻愬弶顥為柟鍛婃倐閹€斥攽鐎ｎ偆鍘卞銈嗗姉閸犳劙宕虫导瀛樼厱閻庯綆鍋呯亸鐢告煙閸欏灏︾€规洜鍠栭、妤呭磼閵堝柊鐐烘⒒閸屾瑧鍔嶉柟顔肩埣瀹曟繄浠︾粵瀣姺闂佽法鍠撴慨鐢稿磻濡眹浜滈柡鍥殔娴滈箖鎮楃憴鍕闁绘牕銈搁妴浣肝旀担鐟邦€撻梺鍛婄箓鐎氼剚顨欓梻鍌氬€搁崐鐑芥倿閿旈敮鍋撶粭娑樺悩濞戞瑦濯撮悷娆忓瀵潡姊洪棃娑氬闁瑰啿顦靛绋款吋婢跺鍘遍梺鏂ユ櫅閸熶即鍩婇弴銏＄厓闂佸灝顑呭ù顕€鏌＄仦鍓с€掑ù鐙呯畵瀹曟粏顦抽柛锝庡櫍閺岋綁鎮╅崘鎻掝潏闂佸憡顨嗘繛濠傤嚕鐠囨祴妲堥柕蹇曞Х椤旀帡鏌ｆ惔銊︽锭闁硅绻濆畷鎶筋敊閸撗咃紳婵炴挻鑹惧ú銈夊几閻旈晲绻嗘い鎰╁灩閺嗭絾顨ラ悙鎻掓殲缂佸倹甯為埀顒婄秵娴滄粎绮ｅ☉娆戠瘈闁汇垽娼у瓭闂佺锕ˉ鎾绘嚍闁秴鍨傛い鎰╁€楅惁鍫ユ⒑濮瑰洤鐏叉繛浣冲嫮顩烽柨鏇炲€归悡鏇㈡煏婵炲灝鍔ら柛鈺嬬秮閺屸剝鎷呯粙鎸庢闂佺硶鏅换婵嗙暦閵娾晩鏁婇梻鍌氼嚟閻╁酣姊婚崒娆掑厡缁绢厼鐖煎畷婊冣攽閸垻鐓撻梺鍦劋椤ㄥ懐澹曟繝姘叆婵犻潧妫Σ褰掓煟閹垮嫮绉柣鎿冨亰瀹曞爼濡搁敂缁㈡О闂備焦鎮堕崐鎰板磻閹剧粯鈷掑ù锝呮啞閸熺偤鏌＄仦璇插妞ゃ垺鐗犲畷鍗炩槈濡粣绠撻弻娑㈠即閵娿儳浠╅柛鐑嗗灦濮婃椽骞愭惔銏㈠弳婵犫拃鍌滅煓闁诡噯绻濋崺鈧い鎺嶆缁诲棝鏌ｉ幇鍏哥盎闁逞屽厵閸婃繂鐣烽敐澶婄劦妞ゆ帒瀚悡鏇㈠箹缁顫婇柣鎾炽偢閹稿﹤鈹戠€ｎ偆鍘甸梺璇″灡濠㈡顣块梻浣虹帛閹搁箖宕伴弽顓炶摕闁绘梻鍘ч崹鍌涖亜閺冨倵鎷″ù灏栧亾缂傚倸鍊风拋鎻掝瀶瑜斿畷鎴﹀箻缂佹鍘介柟鍏肩暘閸╁嫰宕箛娑欑厱闁绘ê纾晶鐢告煃閵夘垳鐣甸柟顔界矒閹稿﹥寰勭€ｎ兘鍋撻鍕拺闁荤喐婢橀埛鏃傜磼椤曞懎鐏︾€规洘鍨块獮鍥偋閸垹骞嶇紓鍌氬€烽悞锕傛晪缂備焦銇涢弲鐘诲蓟瀹ュ牜妾ㄩ梺鍛婃尰閻熴儵鈥﹂崶顒€鐏虫繝銏犲閻╊垰鐣烽妸鈺佺妞ゆ挾鍠愬▍鍥⒒娓氣偓濞佳呮崲閸℃稑鐒垫い鎺嶇婢ь垱淇婇弻銉ゆ喚婵﹦绮幏鍛驳鐎ｎ偆绉烽梻浣筋嚃閸犳牠宕愰崹顕呭殨闁靛闄勭紞鍥煃閸濆嫬鏆欑€规洏鍎靛铏圭磼濡儵鎷婚梺鍛婎焼閸パ咁攨闂佽鍎兼慨銈夋偂韫囨稓鍙撻柛銉戝秵鏁惧銈呴濡繈寮婚悢鍓叉Ч閹艰揪绲界粭锛勭磽娴ｈ櫣甯涚紒瀣笒椤洩绠涘☉妯碱槶閻熸粌閰ｅ畷鎴ｎ樄婵﹥妞介幃婊堝煛娴ｇ硶鎷ゆ繝纰樻閸嬪嫰宕锔藉仼闁绘垼濮らˉ鍫熺箾閹寸偛绗氶柣搴☆煼濮婃椽宕烽鐐板濠电偛鍚嬮悷鈺呭春閳ь剚銇勯幒鍡椾壕闂佽绻戝銊╁箲閵忕姭妲堥柕蹇曞Х椤撴椽姊虹紒妯哄閻忓繑鐟╅幃鐑藉箵閹哄棙鏂€闂佺粯鍔曞鍫曞闯瑜版帗鐓ラ柡鍥朵簽閻ｇ敻鏌涢埞鎯т壕婵＄偑鍊栫敮鎺楀窗濮橆剦鐒介柟閭﹀幘缁犻箖鏌涘▎蹇ｆ闁兼澘娼￠弻宥夊Ψ椤栨粎鏆ら悗瑙勬礀閻栧ジ宕洪敓鐘茬＜闁靛牆妫涚粙鎰版⒒閸屾瑧顦︽繝鈧柆宥呯？闁靛牆顦崥褰掓煥閺囩偛鈧綊宕戦崟顖涚厽闁规儳鍟块銏⑩偓瑙勬尭缁夋挳鈥旈崘顔嘉ч柛鈩兠弳妤佺節濞堝灝鏋ら柛蹇斆锝夋惞椤愩埄鍤ら柣搴㈢⊕鑿ら柟宄邦煼濮婅櫣绮欓幐搴㈡嫳闂佽崵鍟欓崶褏顦悗骞垮劚椤︿即鎮″▎鎰╀簻闁哄啫娲ゆ禍褰掓煕閳哄鎮奸柍褜鍓濋～澶娒哄Ο濂芥椽寮介銏犵柧濠碉紕鍋戦崐鏇犳崲閹邦喒鍋撳鐓庢珝閽樻繃銇勯幘璺轰汗闁衡偓娴犲鐓熼柟閭﹀墮缁狙勩亜閵壯冧槐闁哄瞼鍠撶划娆撳箰鎼淬垹鏋戦梻浣烘嚀瀵爼骞愰幎钘夋瀬闁稿瞼鍋為崐閿嬨亜閹哄棗浜鹃梺鍝勵儐閸ㄥ灝顫忛搹鍦＜婵妫欓悾鍫曟⒑缂佹﹩娈旀俊顐ｇ〒閸掓帡顢橀姀鐘殿唺闂佸搫鍟崐濠氭晬濠婂牊鈷戠紓浣光棨閼测晜濯伴柨鏇楀亾妞ゎ厼娲獮鍥敊閸撗嶇床缂傚倸鍊烽悞锕傗€﹂崶顬℃椽骞橀鐣屽幐婵炶揪绲块幊鎾存叏閸儲鐓欐い鏍ㄧ⊕椤ュ牓鏌涢妸鈺冪暫妤犵偛娲﹂幏鍛存焻濞戞瑥鏀┑鐘垫暩婵兘寮崨濠冨弿闁绘垵顫曢埀顒€鍊圭粋鎺斺偓锝庝簽閸旓箑顪冮妶鍡楃瑨闁哥噥鍋婇幆鍐洪鍛幗濡炪倖鎸鹃崰鎾诲箠閸ヮ剚鐓涢悘鐐电《閸嬫挸鐣烽崶銊︾暦闂佽鍑界紞鍡涘礈濞戞壕鍙烘繝寰锋澘鈧鎱ㄩ悜钘夌；闁绘劗鍎ら弲婵嬫煏韫囨洖啸闁哄棴闄勬穱濠囶敍濮樸儱浠洪梺闈╁瘜閸樻悂宕戦幘缁樻櫜閹煎瓨绻勯懗鐑樼節閵忥綆娼愭繛鍙夘焽閹广垹鈹戠€ｎ偄浠洪梻鍌氱墛閸掆偓闁挎繂顦伴悡鐘垫喐閻楀牆绗ч柣锝嗘そ閺岀喖顢欓幆褌妲愰悗瑙勬礀缂嶅﹪銆侀弴銏″亹閺夊牃鏅濆▔鍧楁⒒閸屾瑨鍏岄柟铏崌楠炴牠顢曢埗鑺ョ☉铻栧ù锝勮濞插憡淇婇妶蹇曞埌闁哥噥鍨堕崺娑㈠箣閿旂晫鍘卞┑鐐村灦閿曗晠鎮為悽鍛婄厵閻庣數顭堝瓭闂佹悶鍔嶇换鍫ュ蓟閻旂厧绠氱憸蹇涙晬瀹ュ鐓涢柛鈽嗗幘閻ｇ敻鏌″畝鈧崰鎰焽韫囨稑绀堢憸蹇涘汲閻樼數纾藉ù锝呮惈闉嬮悗瑙勬礈閺佺危閹版澘绠婚悗娑櫭鎾寸節濞堝灝鏋熼柛鈺佺墛缁傚秹顢旈崼婵囨К闂侀€炲苯澧柕鍥у楠炴帡骞嬪┑鍐ㄤ壕鐟滅増甯掑Ч鍙夈亜閹烘垵顏柣鎾寸洴閹﹢鎮欐０婵嗘婵犵鈧偨鍋㈤柡灞界Ф閹叉挳宕熼銈勭礉闁诲氦顫夊ú鏍х暦椤掑嫬鐓″鑸靛姇缁犮儱霉閿濆娅滃瑙勬礀閳规垶骞婇柛濠冨姍瀹曟垿骞樺ǎ顑跨盎濡炪倖鎸撮埀顒€鍟挎慨宄邦渻閵堝繘妾繛鍏肩懇閳ワ箓鎳楅锝喰俊鐐€戦崝宀勬晝閵夛妇鈹嶅┑鐘叉处閸嬨劎绱掔€ｎ厽纭舵い锔芥緲椤啴濡堕崱娆忣潷缂備礁顑嗙敮鎺楀煝瀹ュ骞㈡繛鎴炵懅閸樹粙姊虹紒妯忣亜顕ｉ崼鏇炵闁归偊鍠掗崑鎾斥枔閸喗鐏堥梺缁樼墪閵堟悂鐛崘銊庣喐绗熼姘€梻浣规偠閸庮噣寮插┑瀣櫖婵犻潧娲ㄧ粻楣冨级閸繂鈷旂紒澶樺墯缁绘盯宕崘顏呭仹闂佽桨绶￠崰鏍煡婢舵劕顫呴柨娑樺楠炴姊绘担绋挎毐闁圭⒈鍋婇弫鍐Χ婢跺鈧爼鏌ㄩ弴鐐测偓褰掓偂閻斿摜绠鹃柟瀛樼箓閼稿綊鏌＄€ｃ劌鈧繈寮诲鍫闂佸憡鎸堕崝搴ｆ閻愬搫骞㈡繛鎴烆焽閻涖儱鈹戞幊閸婃洟骞婃惔锝咁棜鐟滅増甯楅悡鐔兼煙鏉堝墽鍒扮悮姘舵⒑缂佹ɑ灏扮紒瀣灴閳ワ妇鎹勯妸锕€纾繛鎾村嚬閸ㄤ即宕滄导瀛樷拺閻犲洩灏欑粻姘舵煛閸涱喚鐭掑┑锛勬暬瀹曠喖顢涘☉娆愮彸闂備礁鎲℃笟妤呭储閻愵剦娈介柛銉ｅ妿缁犻箖鏌ㄥ┑鍡樺櫤闁瑰吋鍔欓弻銊╁即閵娿倝鍋楀Δ鐘靛仜閸燁偊鍩㈡惔銊ョ闁告劏鏅滃▍鍡涙⒒娴ｅ憡鍟炴繛鎻掔箻瀹曟繄浠﹂崜褜娲告俊銈忕到閸燁垶鎮″☉姘ｅ亾楠炲灝鍔氬Δ鐘虫倐閻涱噣寮介鐔哄幈闂侀潧顭堥崕閬嶅焵椤掆偓濞尖€愁嚕婵犳碍鏅插璺侯煬濞煎﹪姊洪棃娑氱畾闁哄懏绮岃鐎光偓閸曨兘鎷虹紓浣割儐椤戞瑩宕曢幇鐗堢厵闁告稑锕ラ崐鎰版煥濠靛牆浠滈柍瑙勫灩閳ь剨缍嗛崑鍕濡ゅ懏鐓欓柛蹇氬亹閺嗘﹢鏌涢妸褏甯涚紒鍌氱У閵堬綁宕橀埞鐐濠电偠鎻徊浠嬪箟閿熺姴鐤柣鎰劋閸嬨劍銇勯弽銊ょ繁婵炲牊锕㈤弻鈩冪瑹閸パ勭彎闂佽桨鐒﹂幑鍥箖閳哄懎鐭楀璺虹懇濮樿埖鈷掑ù锝堝Г绾爼鏌涢悩铏鞍闁逛究鍔庨埀顒勬涧閹芥粓鎯岄崱娑欑厱闁逛即娼ч弸鐔兼煟閹惧崬鍔滅紒缁樼箞濡啫鈽夊▎妯伙紒闂備線娼荤徊鍧椻€﹂崼銉⑩偓锔炬崉閵婏箑鏋傞梺鍛婃处閸撴盯藝閵夆晜鈷戦悗鍦濞兼劙鏌涢妸銉﹀仴妤犵偛鍟埢搴ㄥ箻瀹曞洭鐛撻梻浣烘嚀椤曨厽鎱ㄩ崘宸禆闁瑰墽绻濈换鍡涙煟閹板吀绨婚柍褜鍓氬ú婊堝箲閵忊懇鍋撻敐搴℃灈缁绢厸鍋撻梻浣烘嚀婢у酣寮查銏㈡殼濞撴埃鍋撻柟顔筋殜閺佹劖鎯旈埄鍐憾闂備胶顭堥敃锕傚礂濮椻偓瀵鍩勯崘銊х獮闁诲函缍嗘禍鐐寸鐎涙绠鹃悗鐢殿焾鐢爼鎮楀☉鎺撴珖闁瑰箍鍨归埞鎴犫偓锝庡亜娴犳椽姊婚崒姘卞闁告巻鍋撻梺闈涚箞閸婃牠鎮￠妷鈺傜厸闁搞儺鐓侀鍫濈劦妞ゆ帊绶″▓婊堟煕閳规儳浜炬俊鐐€栫敮濠勭矆娓氣偓楠炴牠骞栨担鍦幈闂佸搫鍊藉▔鏇″€寸紓鍌欑贰閸犳牠顢栭崨鎼晣濠靛倻顭堝钘壝归敐鍛儓鐎殿喗濞婂缁樻媴缁嬫妫岄梺绋款儏濡繂鐣锋导鏉戠閻犲洦褰冮崑宥夋⒑瑜版帗锛熼柣鎺炵畵閸╂盯骞嬮敂鐣屽幈濠电偞鍨堕敃顐㈩啅閵夈儮鏀芥い鏃傚帶閳ь剙娼″璇测槈閵忕姵顥濋柣鐘充航閸斿酣宕濋鐐粹拺缂侇垱娲橀弶褰掓煕鐎ｎ偅灏い顏勫暣婵″爼宕卞Δ鈧鎴︽⒑缁嬫鍎愰柟鐟版喘瀵鎮㈤崗鐓庢疅闂侀潧锛忛崨顖氬辅闂佽瀛╅鏍闯椤曗偓瀹曟垶绻濋崶銉㈠亾娴ｅ壊娼╅悹楦挎閸旓箑顪冮妶鍡楃瑨閻庢凹鍓涚划濠氭偐瀹曞洨鐦堟繝鐢靛Т閸婄粯鏅跺☉銏＄厱閻庯絻鍔屾慨鍌炴煛瀹€瀣М濠殿喒鍋撻梺瀹犳濡寮查柆宥嗏拺闁告縿鍎遍弸搴ㄦ⒑鐢喚鍒版い顐㈢箳缁辨帒螣鐠囧樊鈧捇姊虹紒妯虹仸闁挎碍绻涢崼婵堢劯婵﹥妞藉畷顐﹀Ψ閵夛妇鈧鈹戦悙鑼癁闁逞屽墮绾绢參寮抽敃鍌涚厸閻忕偠顕ч崝姘辩磼閻樺灚鏆柡宀€鍠撻幉鎾礋閸偆鏆︽繝纰夌磿閸嬫鍒掑▎蹇ｅ殨妞ゆ劧绠戠粈鍐┿亜閺冨洤浜归柨娑欑矊閳规垿顢欑紓瀛樺灴瀹曨剟鎳￠妶鍡╂綗闂備緡鍓欑粔鐢稿煕閹烘嚚褰掓晲閸粳鎾剁棯椤撶偟鍩ｉ柡灞剧洴閹晠鎼归銏ょ€洪梻渚€鈧稓鈹掗柛鏃€鍨块獮鍐╃鐎ｎ亜绐涙繝鐢靛Т閸婇鑺遍崹顐ょ瘈闁汇垽娼ф禒锕傛煕椤垵鐏︾€规洜鎳撶叅妞ゅ繐鎳庢禍妤呮⒑閸濆嫭鍌ㄩ柛銊︽そ閹ょ疀閹垮啰鍞甸梺鐓庢憸閺佹悂濡撮幒妤佺厱闁圭儤鎸荤欢鏌ユ煃鐟欏嫬鐏撮柛銊╃畺閹崇娀顢楅崒婊冨箚闂傚倷绀侀幖顐︽儗婢跺瞼绀婂ù锝夆偓娑氱畾闂佸綊妫块悞锕傚疾濠靛鐓冪憸婊堝礈閻旂厧绠栨慨妞诲亾妤犵偞锕㈤、娆撴偩鐏炶棄绠伴梻浣筋嚙缁绘帡宕戝☉娆愭珷闁芥ê顥㈤搹鍏夊亾閻㈢數銆婇柛瀣尭閳绘捇宕归鐣屽蒋闂備礁鎲￠幐濠氭儎椤栫偟宓侀柟杈剧畱缁€瀣亜閺嶎煈鍤ら柍鍝勬噺閻撴瑩鏌℃径搴″姷閻庢氨澧楃换娑氭嫚瑜忛悾鐢告煙椤斿厜鍋撻弬銉︻潔濠殿喗锕徊鑺ョ妤ｅ啯鐓曢煫鍥ㄦ惄濡茬霉濠婂牏鐣洪柡宀嬬稻閹棃顢涘鍛咃綁姊洪崨濠冨鞍缂佸鐗犻崺鍛存濞戞帗鏂€闂佹寧绋戠€氼剚绂嶆總鍛婄厱濠电姴鍟悘瀵糕偓瑙勬礀缂嶅﹤鐣烽锕€绀嬮幖娣灮濞插鈧娲橀敃銏′繆濮濆矈妲煎┑鐐茬墦缁犳牕顫忓ú顏勫窛濠电姴瀛╅悾濂告⒑缁嬫鐓紓宥勭椤曪綁顢氶埀顒勫春閳ь剚銇勯幒鎴濃偓鐟扮暦閸欏绡€闂傚牊渚楅崕蹇曠磼閳ь剟宕橀鐣屽帗闂佸憡绻傜€氼剟寮抽悙娣簻妞ゆ劧绲跨粻妯肩磼鏉堛劍宕岀€规洘甯掗～婵嬵敄閽樺澹曢梺褰掓？缁€浣哄瑜版帗鐓欓梻鍌氼嚟椤︼妇鐥崜褎鍤€妞ゎ亜鍟伴埀顒婄秵娴滄繈骞戦敐澶嬬厽妞ゆ挾鍋為ˉ婊堟煏閸℃ê绗掓い顐ｇ箞閺佹劙宕ㄩ鈧ˉ姘攽閿涘嫬浜奸柛濠冨灴瀹曠懓煤椤忓懎浜遍梺缁橆焾鐏忔瑩寮抽敃鍌涚厪濠电偛鐏濋崝瀛樼箾闂傛潙宓嗛柡灞炬礋瀹曠厧鈹戦崶褎顏￠梻浣告憸婵敻鏁冮姀銈呰摕闁绘梻鈷堥弫濠囨煟閹伴潧澧柣婵愪簽缁辨挻绗熼崶褎鐏嶉梺鑽ゅ暱閺呯娀鎮伴鈧獮鍥敇閻斿嘲濡抽梻浣哥枃閸╂牜鈧瑳鍐殕缂佸顑欏鏍磽娴ｈ鐒介柣鐔风秺閺屽秷顧侀柛鎾跺枛瀹曟椽鍩€椤掍降浜滈柟鐑樺灥閳ь剙鎲＄粋鎺戭煥閸喓鍘惧┑鐐跺蔼椤曆囨倶閿熺姵鐓涢柛娑卞幘閸╋絾銇勯姀锛勬创闁诡喗鐟ч埀顒傛暩椤牏鏁ィ鍐┾拻濞达綀顫夐崑鐘绘煕鎼淬垻鐭掔€规洘锕㈠畷锝夊Ψ瑜忛敍鐐寸節瀵伴攱婢橀埀顒侇殕閹便劑鎮滈挊澶岋紱闂佺粯鍔曢悘姘跺汲濠婂牊鐓欓柣鎴烇供濞堛垽鏌℃担鍛婃悙闁宠鍨垮畷鎺戭煥鎼达絽濮奸梻鍌欑瀹曨剙煤閿旂偓宕叉繝闈涱儐椤ュ牊绻涢幋鐐垫噽婵☆偆鍋ゅ娲偂鎼达絼绮甸梺鍛婃⒐閻熴儵锝炶箛鏃傜瘈婵﹩鍓涢敍婊冣攽閻愬弶顥為柛鈺佺墕鍗辨い鏂垮⒔绾惧ジ鏌涢幘妤€妫欓妤呮⒑閸涘鑰跨紒鐘崇墪閻ｅ嘲顫濈捄铏诡唺濠德板€曢敃銉╁疾椤掆偓閳规垿顢欓惌顐邯瀹曘儳鈧綆鍓涚粈濠囧箹濞ｎ剙濡介柛瀣у墲缁绘繃绻濋崒娑樻濡炪倧绲介妶鎼佸箖娴犲鏁嶆繛鎴烆焽閻熸彃顪冮妶鍐ㄧ仼闁挎洦浜滈～蹇曠磼濡顎撻梺鍛婄☉閿曘倝寮抽崼婵冩斀闁绘劙顤傞崵瀣磼閻樿櫕灏柣锝囧厴瀵泛鈻庨悙顒€鍏婇梻浣稿悑閹倸顭囪缁傛帗銈ｉ崘鈹炬嫼闂備緡鍋嗛崑娑㈡嚐椤栨稒娅犻悗娑櫳戦崣蹇撯攽閻樻彃鏆為柕鍥ㄧ箘閳ь剝顫夊ú婊堝礂濮椻偓閵嗕礁顫滈埀顒勫箖濞嗘挸绾ф繛鍡欏亾椤ワ繝姊婚崒姘偓椋庣矆娓氣偓楠炲鏁撻悩鑼唶闂佺厧顫曢崐鏇㈠几閸懇鍋撻獮鍨姎婵炲眰鍔戦幆灞惧緞閹邦厾鍘甸梺缁樺灦钃遍悘蹇曟暬濮婂宕熼銏╀純闂佸搫鏈粙鎴﹀煡婢跺娼ㄩ柛顐ｇ箓椤娀姊绘担鍛婂暈閻绱掗鐣屾噧妞ゎ偄绻橀幖褰掑捶椤撶媴绱叉繝娈垮枟椤ㄥ懎螞濞戙垹绀夐柛娑橈功缁犻箖鎮楀☉娆樼劷闁活厹鍊濋弻娑㈠箻鐠虹儤鐎婚梺浼欑到閸㈡煡鍩為幋锕€骞㈤柍杞扮劍閸婎垰鈹戦悩顔肩伇婵炲鐩、鏍炊椤掆偓閸屻劌霉閻樺樊鍎愰柍閿嬪灴閺岋綁鎮㈢粙娆炬婵炲濮伴崹浠嬪箖濡も偓椤繈鎮℃惔銏壕闁诲孩顔栭崯顐﹀炊瑜忛崝锕€顪冮妶鍡楀潑闁稿鎹囬幗鍫曞冀椤撶喓鍘藉┑顔姐仜閸嬫挻绻涙担鍐插椤╅攱绻濇繝鍌滃闁绘挻娲熼弻锝夊即濮橀硸妲繛瀛樼矆閸楁娊寮婚悢纰辨晪闁逞屽墰缁寮介鐐寸€梺鐟板⒔缁垶宕戦幇鐗堢厾缁炬澘宕晶濠氭煕濮橆剦鍎旀慨濠勭帛閹峰懘鎮烽弶鍨戞繝鐢靛仜閻°劌鐣濈粙璺ㄦ殾闁硅揪绠戦獮銏＄箾閹寸儐鐒介柛鏃撶畱椤啴濡堕崱妤€娼戦梺绋款儐閹稿濡甸崟顖ｆ晣闁绘ɑ褰冮獮瀣倵濞堝灝鏋涙い顓犲厴楠炲啴濮€閵堝棗浜楅柟鑹版彧缂嶅棗危椤栫偞鈷掑ù锝囶焾閹垹绱掓担瑙勫唉鐎殿喗褰冮…銊╁礃閿濆棛浜栨俊鐐€栫敮鎺斺偓姘煎弮閸╂盯骞嬮敂鐣屽幈濠电偞鍨堕敃顐﹀绩婵犳碍鐓熼柟鎯у船閸斻倗绱掓潏銊ョ瑲鐎垫澘瀚换婵嬪礋椤撳鍔戝娲濞戞瑯妫涚紓浣藉煐瀹€鎼佹偘椤斿槈鐔煎礂閻撳海褰撮梻浣告贡缁垳鏁幒妤€鏋侀柕鍫濇缁诲棝鏌ｉ幇鍏哥盎闁逞屽墯閻楃娀鐛幇顓滃亝闁告劑鍔庨弻鍫ユ⒑缁夊棗瀚峰▓鏃傜磼閻欌偓閸ㄨ京鎹㈠☉姗嗗晠妞ゆ棁宕甸崙褰掓⒑閹惰姤鏁遍悽顖涘浮婵℃挳骞掗幋顓熷兊濡炪倖甯婇悞锕傚箖濞嗘劗绠鹃悗娑欘焽閻矂鏌涚€ｃ劌鈧繂顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棝顎楀ù婊呭仦缁绘盯宕ｆ径瀣攭闂佸搫鐬奸崰搴ㄦ偩閻戣棄鐐婄憸搴ㄦ倶閸繍娓婚柕鍫濆暙閻忣亪鏌ｉ埡濠傜仸妤犵偛鍟埢搴ㄥ箻瀹曞浂鍞介梻浣告贡閸庛倝宕归幎钘夌疅濡わ絽鍟埛鎺楁煕鐏炲墽鎳呮い锔肩畵閺岀喓鎷犺绾捐法绱撻崒娑欏磳鐎规洜顭堣灃闁逞屽墰婢规洜鎹勯妸銏犱壕閻熸瑥瀚粈鈧┑鐐茬湴閸婃繆妫㈠┑顔斤供閸忔﹢寮ㄦ禒瀣厱閻忕偛澧介。鏌ユ煕閻斿搫浠遍柡宀嬬秮楠炴﹢宕橀崣澶嬵啀闂備胶顢婄亸娆撯€﹂崼銉⑩偓锕傚Ω閳轰線鍞跺┑鐘绘涧閻楁粌危閼哥數绡€婵炲牆鐏濋弸鐔搞亜椤撶偟澧曢柍缁樻煥閳藉顫濋崣妯肩憹婵＄偑鍊栭悧婊堝磻閻愮儤鍋傞柡鍥╁枔缁犻箖鏌熺€涙绠撻柤绋跨秺閺岋紕鈧綆鍓欓弸娑㈡煛鐏炲墽鈽夐柍璇叉唉缁犳盯寮撮悪鈧崯瀣⒒娴ｅ憡鎯堥柣顒€銈稿畷浼村冀椤撶偠鎽曢梺鎼炲労閸撴岸寮插鍫熷仯闁诡厽甯掓俊濂告煕閵堝骸澧存慨濠勭帛閹峰懐鎲撮崟鈺€鎴烽梻浣侯焾椤戝懐鈧凹鍣ｉ獮鎴﹀閻樻牜鍠愮粭鐔碱敍濞戞氨鈻夌紓鍌氬€搁崐鐑芥倿閿曚焦鎳屽┑鐘愁問閸ㄩ亶骞愰幎钘夎摕婵炴垶菤濡插牊鎱ㄥΔ鈧悧鍡樺閹扮増鈷戦柛婵嗗椤ユ粓鏌ｅΔ浣瑰碍妞ゎ偄绻愮叅妞ゅ繐鎳庡▓銉╂⒑闂堟稓澧曢柟鍐茬箻閹顢橀姀鈾€鎷虹紓浣割儓濞夋洟宕欓崷顓犵＜闁煎ジ顤傞崵娆撴懚閻愮儤鐓熼柡鍌氱仢閹垿鏌嶉柨瀣伌闁哄被鍊濋獮渚€骞掗幋婵嗩棄婵＄偑鍊曠换鎰版偂婵犳艾鐐婃い鎺戭槹閺呮繈姊洪幐搴㈢５闁稿鎹囬弻娑㈠箣閻樻祴鏋呴梺鍝勭焿缁绘繂鐣峰鈧俊姝岊槻妞ゃ倐鍋撻梻鍌欒兌缁垶骞愭ィ鍐ㄧ獥闁哄稁鍘奸拑鐔兼煏婵炲灝鍔楅柡鈧禒瀣厱闁斥晛鍘鹃鍕ㄦ瀺闁挎繂鎷嬪〒濠氭煏閸繄绠伴柣锔界矒閺屾盯骞樼捄鐑樼亪閻庢鍠涢褔鍩ユ径濠庢僵闁挎繂鎳嶆竟鏇㈡⒑閹稿海绠撳Δ鐘叉啞缁傚秴鈹戦崼姘壕閻熸瑥瀚粈鈧梺娲诲墮閵堟悂宕洪埀顒併亜閹烘垵鏋ゆ繛鍏煎姈缁绘盯宕ｆ径娑溾偓鍧楁煏閸℃鏆ｇ€规洖宕灃濠电姴鍊归鍌炴⒒娴ｅ憡鍟炴繛璇х畵瀹曟粌鈽夊顒€袣闂侀€炲苯澧紒缁樼⊕濞煎繘宕滆閸╁本绻濋姀銏″殌闁挎洏鍊涢悘瀣攽閻樿宸ラ柣妤€锕崺娑㈠箳濡や胶鍘遍柣蹇曞仦瀹曟ɑ绔熷鈧弻宥堫檨闁告挾鍠栬棢闁规崘娉涢崹婵嬫煕椤愩倕鏋旈柣鐔风秺閺屽秷顧侀柛鎾跺枛閹即顢欓挊澶岀獮闂佸綊鍋婇崢钘夆枍閵忋倖鈷戠紓浣癸供閻掗箖鎮樿箛鏃傛噰閽樻繃銇勯弴妤€浜惧┑顔硷攻濡炰粙鐛幇顓熷劅闁冲灈鏅滅€氫粙姊绘担鍛婃儓闁瑰嘲顑夊畷鎴炵節閸ヮ灛銉╂煕濞戞瑦缍戦柣顓燁殔椤法鎹勯搹鍦紘闂佷紮绠戦悧鎾愁潖婵犳艾纾兼慨妯哄船椤も偓濠电偞鎸荤喊宥夈€冩繝鍌滄殾闁哄洨鍎愰悡銉╂煕濞戝崬鐏ｉ柨娑欑箞閹鐛崹顔煎濠碘槅鍋呯粙鎺楀疾閸洘鐒肩€广儱妫涢崢鎾绘偡濠婂嫮鐭掔€规洘绮岄埢搴ㄥ箣閻樿京鐟濋柣搴＄畭閸庨亶藝椤栨粌顥氶柛褎顨嗛埛鎴炪亜閹哄棗浜鹃梺鍛婎殕濞茬喎鐣烽崼鏇炍╅柕澶樺枛濞堝ジ姊绘担鍛婃儓妞わ缚鍗冲畷纭呫亹閹烘垵鍋嶉梻渚囧墮缁夌敻鍩涢幋锔界厽闁绘梻鍘ф禍浼存煕閵堝洤鏋涢柡灞剧〒閳ь剨缍嗛崜娆愮鏉堚斁鍋撶憴鍕┛缂傚秮鍋撶紓浣哄У缁嬫垿鍩ユ径濞炬瀻闁瑰瓨绻傜粻娲⒒閸屾瑨鍏岀紒顕呭灦瀵濡搁埡浣侯啇濡炪倖鍔х拹鐔煎焵椤掆偓閸婂湱缂撴禒瀣窛濠电姴瀚獮宥夋⒒娴ｄ警鐒剧紒缁樺浮瀹曘垼顦抽柟渚垮姂瀹曞爼顢楁担鍝勫笚闂佽崵鍠愰悷銉р偓姘煎墴閹﹢骞橀鐣屽幈闂侀潧艌閺呮繈鎮惧ú顏呯厵妞ゆ梻鏅幊鍥煙缁嬪尅鏀荤€垫澘瀚鍕節閸屾粈鍠婇梻鍌氬€搁崐鎼佸磹瀹勬噴褰掑炊椤掑鏅梺鍝勭▉閸樿偐绮ｅΔ浣风箚闁靛牆鎳忛崳鐑芥煃瑜滈崜娆撳疮閺夋垹鏆﹂柕濠忛檮缂嶅洭鏌涢幘妤€鎳夊Λ銊モ攽閻樺灚鏆╁┑鐐╁亾濠电偘鍖犻崶鑸垫櫈闂佺硶鍓濈粙鎴犲婵犳碍鐓曠€光偓閳ь剟宕戝☉姘变笉閻熸瑥瀚粻楣冩煥濠靛棝顎楀褜鍣ｉ弻锝堢疀閿濆懏鐏堥梻鍥ь槹缁绘繃绻濋崒婊冣叡闂佷紮绲块崕銈夊箞閵婏妇绡€闁告洦鍘肩粭锟犳⒑閻熸澘妲婚柟铏悾鐑藉Ω閿斿墽鐦堥梺绋挎湰缁嬫帡鎮炬總鍛娾拻濞达絽婀卞﹢浠嬫煕閳轰礁顏€规洖缍婇弻鍡楊吋閸愶絽浜鹃柛鎰靛枛闁卞洭鏌曟径鍫濆姕闁诲寒鍓欓—鍐Χ閸℃锛曢梺绋款儐閹瑰洭寮诲☉銏犵厸濞达絽澹婃导鍐倵鐟欏嫭绀冩い顓炵墦钘濋悗闈涙憸绾惧ジ鏌ｅΟ铏规瀮濠㈣锕㈤弻宥囨喆閸曨偆浼屽銈冨灪閻熲晠骞冮幆褏鏆嗛柍褜鍓熼幃楣冩偨閸涘ň鎷哄┑鐐跺蔼椤曆囩嵁閺嶎厽鐓熸俊銈傚亾婵☆偅顨呴悾鐢稿礋椤栨稈鎷虹紓浣割儓濞夋洜绮诲ú顏呯厱閻庯綆鍋勬慨澶屸偓娈垮暙閸パ呭姦濡炪倖宸婚崑鎾绘煃鐟欏嫬鐏撮柟顔界懇閹崇娀顢楅埀顒勩€傚ú顏呪拺閻犲洩灏欑粻鑼磼鐠囪尙澧︽鐐插暙椤粓鍩€椤掑嫬绠栭柍鍝勫暟绾惧吋淇婇婊冨付閻㈩垶绠栧缁樻媴缁嬫妫岄梺绋款儏濡繂鐣锋导鏉戠疀闁哄娉曢敍娆撴⒑瑜版帒浜伴柛鐘冲浮瀹曟垿骞橀弬銉︾亖闂佸壊鐓堥崰妤呮倶閸繍娓婚柕鍫濋楠炴﹢鏌涜箛鏃撹€块柣娑卞櫍瀹曟﹢顢欑喊杈ㄧ秱闂備線娼х换鎺撴叏閻㈠憡鍊甸柟鎯板Г閻撴稑顭跨捄鐚村姛濠⒀勫灴閺屾盯寮捄銊愩垽鏌嶇拠鑼㈡い鎾冲悑瀵板嫮鈧急鍕伜婵犵數鍋犻幓顏嗙礊閳ь剚绻涢崪鍐偧闁轰緡鍠栭埥澶愬閿涘嫬骞愰梺璇茬箳閸嬬娀顢氳閹便劑宕掑┃鎯т壕閻熸瑥瀚粈鍐煟閹垮嫮绡€闁绘侗鍣ｉ獮妯兼嫚閼碱剦鍞烘繝鐢靛█濞佳囨偋閸℃ɑ鍙忔繛宸簼閳锋帒霉閿濆嫯顒熼柡鈧导瀛樼厵婵炶尪顔婇柇顖涙叏婵犱胶鐭欑€规洜鍠栭、娑橆潩閸楃偛绠?",
            response_language,
        )
    resume_thread = _agentic_resume_thread_text(
        summary,
        next_step,
        response_language=response_language,
    )
    return {
        "summary": summary,
        "next_step": next_step,
        "blocker": summary,
        "teaching_note": teaching_note,
        "resume_thread": resume_thread,
        "stop_reason": "empty_response",
        "fell_back": True,
    }


def _prefers_chinese(response_language: str | None) -> bool:
    return bool(response_language and response_language.lower().startswith("zh"))


def _mode_style_label(mode: str, chinese: bool) -> str:
    if chinese:
        return {
            "guided": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棗鏆欏┑鈥炽偢閺屽秷顧侀柛鎾存皑閹广垽宕煎┑鎰婵犵數濮甸懝楣冨础閹惰姤鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú鐔奉潖閾忓湱纾兼俊顖氭惈琚濋梻浣告啞閹歌鐣濋幖浣哥畺闁汇垻顭堢猾宥夋煕椤愩倕鏆遍柟閿嬫そ濮婅櫣娑甸崨顓濇睏闂佺顑嗙粙鎺撶┍婵犲啰闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛瀣閹剝绺介崨濠勫幈闂佸疇顫夐崕铏閻愵兛绻嗛柣鎰典簻閳ь剚鐗滈弫顕€骞掑Δ鈧粣妤佹叏濮楀棗澧婚柣鎺嶇矙閺岀喖鏌囬敃鈧獮妯肩磼閻樿崵鐣洪柡灞剧☉閳诲氦绠涢敐鍠般劍绻濋埛鈧仦濂稿仐闂佽鍣换婵囦繆閼搁潧绶為悗锝庡墮瀵娊姊绘担鍛婃儓婵炲眰鍔戝畷鎴濃槈濞嗘埈娲搁梺瑙勵問閸犳氨澹曢悾灞稿亾楠炲灝鍔氭俊顐ｇ⊕閺呭爼鎮介崨濠勫幐閻庡厜鍋撻悗锝庡墰閻﹀牓鎮楃憴鍕闁绘牕銈稿畷娲晸閻樿尙鍔﹀銈嗗笒閸婂綊锝為弴鐘亾鐟欏嫭绀€婵炶绠撳畷浼村箛閻楀牏鍘藉┑掳鍊愰崑鎾绘煟濡も偓濡稓鍒掗銏犵闁哄啫鍊婚敍婊堟⒑闁偛鑻晶瀵糕偓瑙勬礃鐢繝骞冨▎鎴斿亾閻㈡鐒炬鐐茬墦濮婄粯绻濇惔鈥茬盎濠电偠顕滅粻鎾诲箠濠靛鍊锋い鎺戝亞濞叉悂姊洪棃鈺佺槣闁告ê澧芥竟鏇熺附閸涘﹤鈧敻鏌ㄥ┑鍡欏嚬缂併劏鍋愰埀顒傛嚀閹诧紕鎹㈤崟顓燁潟闁圭儤鎸荤紞鍥煏婵犲繒鐣遍梻澶婄Ч濮婃椽鎮烽弶鎸幮╅梺纭呮珪閿曘垽鎮伴鈧獮妯兼嫚閼碱剦鍞洪柣搴＄畭閸庨亶骞忕€ｎ€稑顭ㄩ崼鐔叉嫽闂佺鏈懝楣冨焵椤掑倸鍘撮柟铏殜瀹曞ジ寮村璇蹭壕闁挎洖鍊搁柋鍥煏婢舵稓鐣遍柛鎾瑰煐缁绘繈妫冨☉妯峰亾婵犳埃鈧箓宕奸姀鐙€妫滄繝鐢靛У绾板秹鎮￠悢鍏肩厵闂侇叏绠戦弸娑㈡煕閺傛鍎旈柡灞剧〒閳ь剨缍嗘禍婊堝焵椤掆偓濞尖€愁嚕婵犳碍鏅搁柣妯垮皺閸婄偤姊虹€圭姵銆冮柣鎺炵畵閹顢橀悢铏诡啎闁诲孩绋掗…鍥儗鐎ｎ剛纾兼い鏃囧Г瀹曞瞼鈧鍠栭…鐑藉箖閵忋倖鍋傞幖杈剧秮閻涙捇姊绘担绋款棌闁绘挸鐗撳畷鎶筋敋閳ь剙顕ｉ幎钘夘潊闁靛牆妫岄幏娲煟閻樺弶绀岄柍褜鍓濆▍鏇㈡倶閺囥垺鈷戠紒瀣儥閸庢劙鏌涢弮鈧〃鍛祫闂佸湱澧楀妯肩不閾忣偂绻嗛柕鍫濆椤︼箑霉濠婂啰绉烘慨濠冩そ楠炲棜顦崇紒鍌氼儔閺屾稓鈧綆浜滈顓犫偓娈垮枛閸熻儻鐏冮梺鍛婂姦娴滅偤鏁嶅┑鍥╃閺夊牆澧界€佃偐绱掗鐣屾噰鐎规洦鍋勭叅妞ゅ繐鎳庢禒鍝勵渻閵堝棛澧い銊ユ噺閺呭爼骞撻幑娑橀叄瀹曟儼顧傞棅顒夊墯椤ㄣ儵鎮欑€电顫ч梺鐟板槻閹冲酣婀侀柣搴秵娴滄瑦绔熼弴銏♀拺闁圭瀛╃粈鈧梺绋匡工閹芥粎鍒掓繝姘櫜闁糕剝鐟ч惁鍫ユ⒒閸屾氨澧涚紒瀣笧缁﹪鍩￠崨顔惧幈闂佺粯鍔曢顓㈠矗閳ь剙鈹戦纭峰伐妞ゎ厼鍢查悾鐑藉箳閹搭厽鍍靛銈嗗灱濡嫭绂嶉崜褏纾奸悗锝庡亾缁扁晜绻涘顔荤盎閸ュ瓨绻濋姀銏☆仧缂佺姵鍨电叅妞ゆ挶鍨圭粻鏍煟閿濆懐鐏遍柣顓熺懇閺屻倝骞囨担鍝ヤ画闂佺寮撻崡鍐差潖缂佹鐟归柍褜鍓欓…鍥樄闁炽儻绠撳畷濂稿Ψ閵壯嶇吹婵＄偑鍊栧ú宥夊磻閹惧灈鍋撳▓鍨灁闁告柨绉剁划瀣箳閺傚搫浜鹃柨婵嗛娴滅偤鏌涘鈧禍璺侯潖濞差亜妫橀柕澶涢檮閻濇棃姊洪崨濠勬噭闁告梹鐟╅悰顔锯偓锝庡枟閺呮繈鏌嶈閸撴稓鍒掓繝姘唨闁靛ě鍜佸晭闂備胶纭堕崜婵婃懌闁诲繐绻嬮崡鎶藉蓟閿濆绠婚悗娑欘焽椤︿即姊洪崫鍕効缂傚秳绀侀锝夘敆閸曨偆顔囬柟鑲╄ˉ閸撴繂鈻撳鈧缁樻媴娓氼垳鍔搁梺鎸庢磸閸庨潧鐣峰┑鍡忔瀻闁规儳鐤囬幗鏇㈡⒑閹稿海鈽夐悗姘间簻閳讳粙顢旈崼鐔蜂化闂佹悶鍎崝搴ㄥΧ閹绢喗鐓曢悗锝庡亝鐏忣參鏌嶇憴鍕仼闁逞屽墾缂嶅棝宕滃▎鎴犵焾闁挎洖鍊归埛鎴犳喐閻楀牆绗掑ù婊€鍗抽弻娑樜熼崷顓犵厯閻庤娲樺ú鐔煎箖閵忋倕绀傞柤娴嬫櫅瀵櫕绻濋悽闈涒枅婵炰匠鍏炬稑鈻庨幘宥咁槸椤劑宕熼鐙€鍟庨梻浣告啞娓氭宕伴弽顓熷€堕悗娑櫳戦崣蹇撯攽閻樻彃浜為柣鎾瑰亹閳ь剝顫夊ú妯兼暜閹烘缍栨繝闈涱儛閺佸洭鏌ｉ弮鍌ょ劸闁逞屽墴閺€杈ㄧ┍婵犲洦鍊锋い蹇撳閸嬫捁顦冲ǎ鍥э躬瀹曞爼顢楅埀顒勫几娓氣偓閹綊宕惰閳绘洟鏌涢妶鍡樼闁宠鍨块幃鈺冣偓鍦Т椤ユ繈鏌熼婊冩灈婵﹥妞藉Λ鍐ㄢ槈鏉堛剱銈夋⒑閹肩偛濡芥俊鐐舵椤曪綁顢楅崟顐ゅ姦濡炪倖甯掔€氼參鍩涢幒鎳ㄥ綊鏁愰崼鐕佷哗闂侀潧妫楅敃顏堝蓟濞戙垹绠婚悗闈涙憸閻ゅ嫰姊烘潪鎵槮妞ゆ垵鎳橀崺鐐哄箣閿旇棄鈧兘鏌涘▎蹇ｆЦ闁哄棔绶氬娲川婵犱胶绻侀梺鎼炲妽婵炲﹪寮鍛斀闁搞儮鏅濋鏇㈡煛婢跺﹦澧曞褌绮欏畷姘鐎涙鍘电紒鐐緲瀹曨剚绂嶆导瀛樼厽閹兼番鍔嶉弫杈╃磼缂佹绠為柟顔荤矙濡啫鈽夊Δ鍐╁礋闂傚倷鑳堕幊鎾诲疮鐠恒劍宕查柟閭﹀枛瀵弶绻濋悽闈浶㈤柨鏇樺€濋幃褔宕卞▎鎴滅瑝闂佸搫琚崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧悶姘ュ劚閳规垿鍩勯崘銊хシ闂佺粯顨嗛幑鍥ь嚕婵犳艾鍗抽柨娑樺閺夋悂鏌ｆ惔顖滅У濞存粎鍋炵粋鎺撶附閸涘﹤浠┑鐘诧工鐎氼厾娆㈤弻銉﹀€垫慨妯煎帶婢ф挳鏌嶉妷锔筋棃鐎规洘锕㈤、娆撳床婢诡垰娲﹂悡鏇㈡煃閳轰礁骞樻い蹇撶墕濮瑰弶淇婇妶鍛櫤闁抽攱鍨圭槐鎺斺偓锝庡亽閸庛儵鏌涙惔銏犲缂佽鲸甯為埀顒婄秵閸嬪懐浜搁悽鍛婄厱闁圭儤鎸哥粭姘辩磼缂佹绠炵€规洖鐖奸幊婊堝垂椤愶絿褰ｉ梻鍌氬€风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭墎鈧稒锕╁▓浠嬫煟閹邦厼绲婚柡鍡樼懇閹藉爼寮介鐔哄帗閻熸粍绮撳畷婊堟偄閻撳孩妲梺闈涚箞閸婃洜绮绘繝姘仯闁搞儯鍔岀徊濠氭煟鎼搭喖骞栨い顏勫暣婵″爼宕卞Ο閿嬪闂備礁鎼幏瀣磻閸涱垳鐭夌€广儱顦伴崐鐑芥煟閵忋垺鏆╅柨娑欑箞濮婅櫣绮欓幐搴㈡嫳闂佽崵鍟欓崨顔碱伕婵炲鍘ч悺銊╂偂閺囥垺鐓熸俊顖濐嚙婢ь垱绻涢崼鐔虹煉闁哄瞼鍠栭、娆撳箚瑜嶉獮瀣節绾板纾块柛蹇旓耿瀹曟椽鏁撻悩鑼紲濠殿喗锕╅崑鍛村磻閸涘瓨鈷掗柛灞剧懆閸忓瞼绱掗鍛仸鐎规洖缍婇幃锟犵嵁椤掍胶娲寸€规洜鍠栭、姗€鎮╂潏鈺冩喒濠电姵顔栭崰妤呪€﹂崼銉ユ槬闁哄稁鍘奸悡鏇㈡煙鐎电浜煎ù婊勭矒閺岀喖骞嗚閼哥懓鈹戦鐓庘偓瑙勭┍婵犲嫮纾奸柕蹇曞У閻忓牆顪冮妶搴′簴闁搞劏妫勯悾鐑藉醇閺囥劍鏅㈡繛杈剧到瀵墎鈧俺妫勯埞鎴︽倷閼搁潧娑х紓浣瑰絻濞硷繝骞冨ú顏勭睄闁割偅绻傞幆鐐测攽閻愬弶顥為柟绋款煼瀹曟劙宕归銈囶啎闂佺懓顕崑娑氱箔濮橆厾绠鹃柛娑卞幗椤ョ姷绱掓潏銊ョ瑨闁伙絾绻堝畷鐔碱敂閸涱厽鐏撻梻鍌欑濠€閬嶅储瑜忕槐鐐寸節閸パ嗘憰闂佸憡渚楅崢绋课ｉ崼鐔稿弿婵妫楁晶顕€鏌嶉柨瀣闁宠鍨块幃鈺呭垂椤愶絾鐦庨梻浣侯焾椤戝棛绮欓幋锝囦罕婵犵數鍋涘Λ娆撳箰閹间礁鍨傞柛宀€鍋為悡鏇熴亜閹板墎绋荤紒宀冩硶缁辨挸顓奸崱娆忊拰闂佸搫鐭夌换婵嗙暦閸洖唯闁靛／鍌滄／闂傚倷鑳剁划顖炲箰婵犳碍鍋￠柍鍝勬噹閽冪喖鏌ｉ弮鍌氬妺闁哥姴妫濋弻娑㈠即閵娿儰绨婚悶姘箞濮婄粯鎷呯憴鍕哗闂佺锕ラ悧鐘诲箖閻ゎ垼妯勯梺璇″灙閸嬫挸顪冮妶鍛闁绘妫涚划璇差潩鏉堛劌鏋戦悗骞垮劚椤︻垳绮婚弽顓熺厵閺夊牓绠栧顕€鏌ｉ幘瀵告噧闁靛棙甯掗～婵嬵敆閸屾瑨妾稿┑鐘殿暯閳ь剙鍟块幃鎴︽煏閸パ冾伃妞ゃ垺娲熼弫鎰板炊閳哄啫甯ㄩ梺璇叉唉椤煤閺嵮呮殾妞ゆ帒鍟版禍娆撴⒒娓氣偓閳ь剛鍋涢懟顖涙櫠閹殿喚纾兼い鏃€顑欓崵娆撴偂閵堝棎浜滈煫鍥ㄦ尰閸ｆ娊鏌熼悿顖涱仩缂佽鲸鎸婚幏鍛村礈閹绘帒澹堥梻浣筋嚙缁绘垹鎹㈤崼銉ｂ偓浣肝旈崨顓ф綂闂侀潧鐗嗗Λ娑㈠储閻㈠憡鈷戦柤濮愬€曢弸鏂款熆瑜庨〃濠傜暦閺夎鐔访虹紒姗嗗晬闂備胶绮崝鏍亹閸愵喖姹叉繛鍡樻尰閻撶喖鏌ㄥ┑鍡欑缂佲檧鍋撻梻浣告惈閼活垰煤椤撱垹鏋侀柛宀€鍋涚粻姘辨喐瀹ュ憛褔寮婚妷锔规嫽闂佺鏈悷褔藝閿曞倹鐓欐繛鏉戭儏婢ц尙绱掑Δ鍐ㄦ瀻閾绘牠鏌涘☉鍗炲箻闁绘挻鍨块弻鐔煎礂閼测晜娈梺鍛婃煥閼活垱鏅ラ梺鍛婄懃椤︻厽绂嶅鍫熺厵闁诡垎鍐煘闂佽娴氭禍顏堝蓟瀹ュ鐓ラ悗锝庝簽娴煎矂姊洪崫鍕効缂傚秳绶氶悰顔锯偓锝庡枛缁秹鏌嶈閸撴瑩鍩㈠澶婂耿婵☆垵鍋愰鏇㈡⒑閸涘﹣绶遍柛鐘愁殔閻ｅ嘲鐣濋崟顒傚幐闁诲繒鍋涙晶钘壝洪弶鎴旀斀闁斥晛鍟崐鎰攽閳╁啯鍊愰柡浣稿€圭粚閬嶅箥娴ｉ晲澹曢梺褰掑亰閸擄箑銆掓繝姘厪闁割偅绻冮ˉ鐐电磼瀹€鍐╃《缂佽鲸鎸搁濂稿礋椤撶姷宕查梻渚€娼уΛ鏃傛濮橆剦鍤曢柟缁㈠枛椤懘鏌ｅ▎灞戒壕濠电偟鍘ч敃顏勵潖閾忓厜鍋撻崷顓炐ｉ柕鍡楀暣閺岋綁骞掗悙鐢垫殼閻庤娲橀崝娆撱€佸☉銏″€风紒顔款潐鐎氳棄鈹戦悙鑸靛涧缂傚秮鍋撳銈庡亜椤﹂潧鐣烽幋锔藉亹缂備焦顭囬崢閬嶆煙閼测晞藟婵℃彃鎳橀幃锟犲礂閸忕厧寮挎繝鐢靛С閼冲爼鎯屽▎鎴斿亾鐟欏嫭绀堥柛鐘崇墵閵嗕礁鈽夊鍡樺兊婵℃彃鏈悧妤佹櫏闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鑼槷闂佹寧娲栭崐鍝ョ玻濡や椒绻嗛柕鍫濇噺閸ｅ綊鏌ｉ幘瀛樼闁哄瞼鍠愬蹇斻偅閸愨晩鈧秹姊虹紒妯诲暗濠电偐鍋撻梺鍝勭灱閸犳牠銆佸鈧幃銏☆槹鎼达絾鍣梻鍌欑閹诧繝骞栭埡鍛偍濞寸姴顑呮闂佸憡娲﹂崰姘舵偪閳ь剟姊虹憴鍕婵炲鐩獮鍐偓锝庡枟閳锋垿鏌熼懖鈺佷粶闁告梹鎸抽弻娑㈠箻鐎靛憡鍣梺姹囧労娴滐綁藝鐟欏嫷娈介柣鎰嚟婢ч亶鏌嶈閸撴氨绮欓幒鏇熸噷闂佽绻愮换瀣础閹惰棄钃熼柨婵嗘閸庣喖鏌曞娑㈩暒閾忓孩绻濆▓鍨灈闁挎洏鍎遍—鍐寠婢跺本娈鹃梺闈涱煭婵″洨寮ч埀顒勬⒑缁嬫寧婀版い鏇熸尦瀵挳濮€閳锯偓閹锋椽姊洪崨濠勭細闁稿氦椴搁悧搴繆閻愵亜鈧垿宕濆畝鍕櫇妞ゅ繐瀚弳锕傛煕濠靛棗顏ゆ俊鎻掔墦閺屾洝绠涢弴鐐愩儲銇勯幘瀛樸仢婵﹨娅ｇ槐鎺懳熻箛锝勯偗闁诡喗锚椤繈鎳滈崹顐ｇ彨闂傚鍋勫ú锕傚箹閳轰降鈧帗绻濆顓犲帾闂佸壊鍋呯换鍐夐悙鐑樺€堕煫鍥ㄦ礃閺嗩剟鏌＄仦鍓с€掗柍褜鍓ㄧ紞鍡涘礈濞嗘劗顩烽弶鍫氭杹閸嬫挾鎲撮崟顒傤槰婵犵數鍋涢敃顏堢嵁閺嶎兙浜归柟鐑樺灦瀹撳秴顪冮妶鍡樺暗闁革綇濡囧Σ鎰板焺閸愌呯畾闂佺粯鍔︽禍婊堝焵椤掍胶澧垫鐐村姍瀹曞ジ寮撮悙鑼偓顓熺節閻㈤潧校缁炬澘绉瑰畷鎴﹀煛閸屾粎顔曢悗鐟板閸犳洜鑺辨總鍛婄厽闁规儳顕ú鎾煙椤旀枻鑰块柟顔界懄閿涙劕鈹戦崱姗嗗敳婵犵數濮甸鏍窗閺嶎厼纾瑰┑鐘宠壘閻掑灚銇勯幒宥囪窗闁哥喎绻橀弻娑㈡偐閹颁焦鐣跺銈庡幖濞层倝鍩㈡惔銊ョ闁哄倹宕橀崺鍛存⒒閸屾瑦绁扮€规洜鏁诲畷鎴︽倷閻㈢數鐓撻梺鍓插亖閸庨亶鎮為崹顐犱簻闁瑰搫妫楁禍楣冩⒑閸涘鎴︽偋濡ゅ啰鍗氶柣鏃傚帶閸楁娊鏌曡箛濠冾€嗛柟閿嬫そ濮婃椽宕ㄦ繝鍕暤闁诲孩鍑归崳锝夊春閵忊€崇窞闁归偊鍘鹃崢鍗炩攽閳藉棗鐏犻柣蹇旂箖缁傚秹宕烽鐘碉紲濡炪倖姊婚埛鍫ユ偂婵傚憡鐓欐い鏃傛櫕閹冲洭鏌熼鐣岀煀閾伙綁鏌ｉ幘鎶筋€楀┑鈥虫处缁绘繈鎮介棃娴躲儵鏌℃担瑙勫€愮€规洘鍨块幃銏ゆ偂鎼达綇绱遍梻浣告贡閸嬫捇寮告總绋垮嚑鐎广儱顦伴悡鏇熺箾閹寸儐鐒介柟鐣屽█閺岋綁骞樼捄鐑樼亪闂佸搫鐬奸崰鏍嵁閸℃凹妾ㄩ梺鎼炲€楅崰鎰崲濞戙垹鐭楀璺侯儏閸炲姊洪崫鍕効缂佽鲸娲樼粋鎺楁晝閸屾氨顦悷婊冾儔閸┾偓妞ゆ帊绀佺粭鎺楁婢舵劖鐓熸繛鍡楃箲閸ｄ粙鏌ｉ敐鍥ㄦ毄闁逞屽墲椤煤濡厧鍨濋煫鍥ㄨ泲閸ヮ剦鏁婇柟瀛樺笧缁犳岸姊洪崷顓犲笡閻㈩垳鍋為弲鍫曞即閻旂繝绨诲銈呯箰鐎氼剟寮抽敐鍛斀闁炽儱纾崺锝団偓瑙勬磸閸旀垿銆佸Ο娆炬Щ婵犵绱曢崗妯侯潖缂佹ɑ濯撮柣鎴灻▓宀勬⒑绾拋鍤嬬紒缁樼箞閻涱噣宕橀鑲╋紲闂佺粯鍔曞璺何ｉ鍕拺缂備焦锚婵洭鏌熺喊鍗炰簽缂侇喖顭烽弫鎰緞鐎ｎ剙寮抽梻浣告惈閸燁偄煤閿曞伖澶嬪緞婵炴帞鎳撻…銊╁礃椤忓柊銊╂⒑閸濆嫮鐒跨紓宥勭窔楠炲啴鍩￠崨顓犵厬婵犮垼娉涢敃銈夋嚑閸愵喗鈷掑ù锝呮啞閸熺偤鏌涢幙鍐ㄥ⒋鐎规洏鍔戦、娑橆煥閸愩劎鐣遍梻鍌氬€搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌ｉ幋锝呅撻柛銈呭閺屾盯顢曢敐鍡欙紭闂侀€炲苯鍘搁柣鎺炲閹广垹鈹戠€ｎ亞锛滃┑掳鍊撻懗鍫曞焵椤掍焦銇濇慨濠冩そ瀹曨偊宕熼鈧崑宥夋⒑閹肩偛濡兼繝鈧潏鈺佸灊闁割偆鍠庣欢鐐烘倵閿濆倹娅囩紒鐘冲哺濮婃椽妫冨☉姘暫闂佺锕ら幉锛勭矉瀹ュ棎鍋呴柛鎰ㄦ櫇閸樺崬鈹戞幊閸婃洟骞婂澶婄疅濡わ絽鍟悡娑氣偓鍏夊亾闁逞屽墴瀹曚即寮介鐐舵憰闂佹悶鍎洪崜姘跺疾濠靛鐓冪憸婊堝礈濮樿泛鐤鹃柛鎾茶兌绾惧吋淇婇婵嗕汗妞ゆ梹娲熼弻锝堢疀閹惧墎顔夐梺缁橆殕椤ㄥ懘鍩㈠鍡欑瘈闁搞儯鍔庨崢鎼佹煟韫囨洖浠╂い鏇嗗洤鐒垫い鎺嶈兌缁犳捇鏌ｉ敐鍥у幋妞ゃ垺娲熼弫鍐焵椤掆偓閺侇噣姊绘担鐟邦嚋婵☆偂鐒﹂幈銊╁Χ婢跺鍓ㄩ柟鍏肩暘閸斿秹鍩涢幒鎳ㄥ綊鏁愰崨顔兼殘闂佸摜鍠撻崑銈夊蓟閵娾晛鍗虫俊顖濇娴犲墽绱撴担绋库偓鍝ョ矓閸洖绠查柛鏇ㄥ墰閻熻銇勯弽銊с€掔紒瀣╃劍缁绘繈鎮介棃娑楃捕濠碘槅鍨伴敃銉х矉瀹ュ拋鐓ラ柛顐ｇ箘椤斿姊洪悡搴㈡喐闁稿绲剧粋宥咁煥閸喓鍘甸梺纭咁潐閸旀牜娑甸幆顬″綊鎮╁畷鍥╃厐闂佸疇顫夐崹鍧楀春閸曨垰绀冮柍鐟般仒閾忓孩绻濆▓鍨灈闁挎洏鍎遍—鍐寠婢跺本娈惧銈嗗姧缁犳垹绮堢€ｎ偁浜滈柡鍥╁仦閸ｆ椽鏌﹂幋婵愭█婵﹦绮幏鍛村川婵犲倹娈樻繝娈垮枛閿曘倗绱炴繝鍌滄殾鐟滅増甯掔粻浼村箹鐎涙绠樼紒鐘冲哺濮婃椽宕烽鈩冾€楅梺鍝ュУ閻楁粍绔熼弴鐔洪檮闁告稑锕﹂崢浠嬫⒑瑜版帒浜伴柛銊ゅ嵆閹啴鎮滃Ο闀愮盎闁挎粌顭峰畷鍫曞Ω閵忊€愁伖闂傚倷鑳堕…鍫㈡崲濡ゅ懎纾婚柟鐗堟緲鍥撮梺鍦檸閸犳鎮″☉銏＄厱婵炴垵宕弸銈囩磼閻橀潧浠﹂柕鍥у婵偓闁挎稑瀚崳浼存倵濞堝灝鏋熼柟姝屾珪閹便劑鍩€椤掑嫭鐓冮梺娆惧灠娴滈箖姊鸿ぐ鎺撴暠婵＄偘绮欏濠氭晲婢跺浜滈梺鍛婄缚閸庢煡宕宠閺岋絾鎯旈姀鐘叉瘓闂佸憡鎸鹃崰搴ㄦ偩瀹勬壋鏀介悗锝庘偓顓婂喚鐔嗛悹杞拌閸庢垿鏌涘鈧禍璺侯潖閾忓湱纾兼俊顖涙た濡啴姊虹悰鈥充壕闂備緡鍓欑粔瀵稿婵犳碍鐓忓璺烘濞呭棝鏌ｉ幘宕囩闁哄本鐩崺鍕礃閻愵剛鏆ラ梻渚€鈧偛鑻晶顕€鏌ｈ箛鏃傜疄闁诡喗鍎抽悾锟犲箯閺冨倸鏋涚€规洘顨婇幃鈩冩償閵忥紕褰哄┑鐘垫暩閸嬬娀骞撻鍡楃筏闁秆勵殔绾惧潡鏌曢崼婵愭Ц闁告艾缍婇弻宥堫檨闁告挻鐟╅垾鏃堝礃椤斿槈褔骞栫划鍏夊亾瀹曞浂鍞归梻鍌欑閹测€愁潖瑜版帒鍨傞柣銏犳啞閸嬧晠鏌ｉ幋锝呅撻柛瀣閻ヮ亪骞忓畝鍕懙闂佸搫鎷戠紞浣割潖閾忓湱纾兼俊顖滃劦閹疯顪冮妶搴″箹闁绘鎸搁锝夊蓟閵夈儰绱堕梺闈涳紡閸滃啰闂梻鍌欒兌椤牓寮甸鍕殞濡わ絽鍟悞鍨亜閹烘垵鈧悂宕㈤幘顔界厵闁惧浚鍋掑▓婊堟煙閾忣偆鐭掔€规洖缍婇、鏇㈠閻樿京绀嬮梻鍌氬€烽悞锕傛儑瑜版帒鍨傚┑鐘宠壘閺嬩線鏌熼梻瀵稿妽闁稿孩顨嗙换娑㈠幢濡闉嶉梺缁樻尰閻熲晠寮婚悢鐑樺枂闁告洦鍋勮闂備焦鎮堕崐鏍偡閳哄懎钃熼柨婵嗩槸缁犳娊鏌熺€电小缂侇喚鏁诲娲濞戞瑦鎮欓柣搴㈢煯閸楁娊鎮伴鈧獮鎺懳旈埀顒傜不閿濆棎浜滈柡宥冨妿閳洟鏌￠崱鏇炲祮婵﹦绮粭鐔煎焵椤掑嫬鐒垫い鎺戝€告禒婊堟煠濞茶鐏︾€规洏鍨介幃浠嬪川婵犲嫬骞堥梺鐟板悑閻ｎ亪宕濆鍛鐟滄棃寮婚敐澶嬫櫜闁告侗鍘戒簺闂佸彞绱徊鍓ф崲濞戙垹骞㈡繛鍡楃箣婢规洖霉濠婂嫮鈽夐柍?",
            "balanced": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棗鏆欏┑鈥炽偢閺屽秷顧侀柛鎾存皑閹广垽宕煎┑鎰婵犵數濮甸懝楣冨础閹惰姤鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú鐔奉潖閾忓湱纾兼俊顖氭惈琚濋梻浣告啞閹歌鐣濋幖浣哥畺闁汇垻顭堢猾宥夋煕椤愩倕鏆遍柟閿嬫そ濮婅櫣娑甸崨顓濇睏闂佺顑嗙粙鎺撶┍婵犲啰闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛瀣閹剝绺介崨濠勫幈闂佸疇顫夐崕铏閻愵兛绻嗛柣鎰典簻閳ь剚鐗滈弫顕€骞掑Δ鈧粣妤佹叏濮楀棗澧婚柣鎺嶇矙閺岀喖鏌囬敃鈧獮妯肩磼閻樿崵鐣洪柡灞剧☉閳诲氦绠涢敐鍠般劍绻濋埛鈧仦濂稿仐闂佽鍣换婵囦繆閼搁潧绶為悗锝庡墮瀵娊姊绘担鍛婃儓婵炲眰鍔戝畷鎴濃槈濞嗘埈娲搁梺瑙勵問閸犳氨澹曢悾灞稿亾楠炲灝鍔氭俊顐ｇ⊕閺呭爼鎮介崨濠勫幐閻庡厜鍋撻悗锝庡墰閻﹀牓鎮楃憴鍕闁绘牕銈稿畷娲晸閻樿尙鍔﹀銈嗗笒閸婂綊锝為弴鐘亾鐟欏嫭绀€婵炶绠撳畷浼村箛閻楀牏鍘藉┑掳鍊愰崑鎾绘煟濡も偓濡稓鍒掗銏犵闁哄啫鍊婚敍婊堟⒑闁偛鑻晶瀵糕偓瑙勬礃鐢繝骞冨▎鎴斿亾閻㈡鐒炬鐐茬墦濮婄粯绻濇惔鈥茬盎濠电偠顕滅粻鎾诲箠濠靛鍊锋い鎺戝亞濞叉悂姊洪棃鈺佺槣闁告ê澧芥竟鏇熺附閸涘﹤鈧敻鏌ㄥ┑鍡欏嚬缂併劏鍋愰埀顒傛嚀閹诧紕鎹㈤崟顓燁潟闁圭儤鎸荤紞鍥煏婵犲繒鐣遍梻澶婄Ч濮婃椽鎮烽弶鎸幮╅梺纭呮珪閿曘垽鎮伴鈧獮妯兼嫚閼碱剦鍞洪柣搴＄畭閸庨亶骞忕€ｎ€稑顭ㄩ崼鐔叉嫽闂佺鏈懝楣冨焵椤掑倸鍘撮柟铏殜瀹曞ジ寮村璇蹭壕闁挎洖鍊搁柋鍥煏婢舵稓鐣遍柛鎾瑰煐缁绘繈妫冨☉妯峰亾婵犳埃鈧箓宕奸姀鐙€妫滄繝鐢靛У绾板秹鎮￠悢鍏肩厵闂侇叏绠戦弸娑㈡煕閺傛鍎旈柡灞剧〒閳ь剨缍嗘禍婊堝焵椤掆偓濞尖€愁嚕婵犳碍鏅搁柣妯垮皺閸婄偤姊虹€圭姵銆冮柣鎺炵畵閹顢橀悢铏诡啎闁诲孩绋掗…鍥儗鐎ｎ剛纾兼い鏃囧Г瀹曞瞼鈧鍠栭…鐑藉箖閵忋倕绀傞柤娴嬫櫅婵椽姊绘担鐟邦嚋婵炴彃绉瑰畷鎴﹀箻缂佹鍘搁柣搴秵閸嬪棝濡撮幒妤佺厓鐟滄粓宕滃杈╃煓闁圭儤姊瑰畷鏌ユ煕椤愶絿绠ユ繛鍏肩墵閺屟嗙疀濮樺吋缍堥柣搴㈢瀹€鎼佸蓟濞戞ǚ鏋庨煫鍥风稻妤旀俊鐐€愰弲娆撳础閸愬樊娼栨繛宸簼椤ュ牓鏌嶉崫鍕殶閼叉牜绱撻崒姘偓鍝ョ矓瀹曞洨鐭嗗〒姘ｅ亾妞ゃ垺宀搁弫鎰板幢濞嗘垹妲囨繝娈垮枟閿曗晠宕曟担鍐炬▌闂佸搫鏈惄顖涗繆閻戣棄顫呴柍鈺佸暟瑜板洭姊绘担铏瑰笡闁圭顭烽獮鎴﹀炊椤掆偓閽冪喖鏌ㄥ┑鍡╂Ч闁稿鍔欓弻娑滅疀閹炬潙娈岄梺绯曟櫅閹虫ê顫忓ú顏勫窛濠电姴鍟伴崣鍡涙⒑濞茶骞栭柛濠傛健閻涱噣宕橀鑺ユ闂佺粯锚閸熸寧绂嶅鍫熲拺缂佸娉曠粻浼存煟閵娧冨幋妤犵偛绻愮叅妞ゅ繐鎳夐幏娲⒑閸涘﹦鈽夐柨鏇缁骞樼紒妯衡偓鍨叏濡厧甯舵繛鍛Ч閺岀喖顢欓幆褌鎴烽梺鍦嚀鐎氱増淇婂宀婃Ь闂佹寧绋掔划搴ｆ閹捐纾兼繛鍡樺灥婵¤棄顪冮妶搴″箹婵炲眰鍔庨崚鎺撶節濮橆剛顔掔紓鍌欑劍椤洭宕㈡禒瀣拺闁圭娴风粻鎾寸箾鐏炲倸鈧繂鐣烽姀鈶╁亾濞戞瑱渚涙繛鍫滅矙閺岋綁骞囬鐔虹▏濠电偞鎯岄崰妤呫€冮妷鈺傚€风€瑰壊鍠栭崜璺侯渻閵堝啫鐏柨鏇樺灲楠炲啴鍩￠崨顓狀唽闂佸湱鍎ら幑浣烘閵忋倖鈷掗柛灞捐壘閳ь剚鎮傚畷鎰槹鎼达絿鐒兼繛鎾村焹閸嬫挻顨ラ悙宸█闁搞劌澧介幖鐐媴鐟欏嫨浠㈤梺杞扮閸熸潙鐣烽幒鎴僵闁规彃顑囬獮銏ゆ⒒閸屾瑧顦﹂柟璇х磿缁瑩骞嬮敂钘変槐闂侀潧艌閺呮稓澹曟繝姘厓闁告繂瀚埀顒冨煐缁傚秴顭ㄩ崼鐔哄幍闂佺粯鍨堕敋闁诲繈鍎查妵鍕疀閿濆嫰鍋楅梺鍝勮嫰缁夊綊寮婚妸褉鍋撻敐搴濈敖闁荤喆鍔戝濠氬炊瑜滃Ο鈧梺鍝勮閸斿矂鍩為幋锕€骞㈡俊顖濇閻涒晠姊绘担渚敯婵☆偄瀚板畷鎰板锤濡も偓閽冪喐绻涢幋娆忕仼閸ユ挳姊洪崨濠佺繁闁告妫勯埢鎾寸節濮橆厸鎷洪梺鍛婄箓鐎氼厼锕㈡导瀛樼厽闁冲搫锕ら悘锔筋殽閻愭彃鏆ｉ柛鈺嬬節瀹曘劑顢橀悩鍨緫婵犵數鍋犻幓顏嗗緤閽樺鑰块梺顒€绉村Ч鍙夈亜閹惧崬鐏柍閿嬪笒闇夐柨婵嗘噺閸熺偤鏌涢悢鍝勪槐闁诡喕绮欓、娑樷槈鏉堛劎鏆梻浣芥〃缁讹繝宕抽敐澶婃瀬闁瑰墽绮崑鎰版⒒閸喓銆掗柕鍫檮缁绘繄鍠婂Ο娲绘綉闂佹悶鍔戝褔鍩㈠澶嬫櫜濠㈣泛锕ユ潏鍫ユ⒑閹稿孩绀€闁稿﹤缍婇幃锟犲即閵忥紕鍘繝銏ｅ煐缁嬫捇宕氶弶搴撴斀闂勫洦鎱ㄩ妶澶娢﹂柛鏇ㄥ灠缁秹鏌嶈閸撴瑧鍙呭┑鈽嗗灥瀹曠敻鍩炲鍛斀闁绘ê寮舵径鍕煕婵犲洦鏁遍柕鍥у缁犳盯骞橀幇浣锋闂備胶顭堥鍡涘箲閸パ屽殨闁圭虎鍠楅崑鎰版煕閹邦厼绲荤紒銊ｅ劦濮婄粯鎷呴崫銉ㄩ梺绋款儏閿曨亜鐣烽弴銏☆棃婵炴垶甯楅～宥夋⒑闂堟稓绠冲┑顔炬暬钘熸繝闈涱儐閻撴瑩鏌ｉ幘铏崳闁圭晫濞€閺岀喓绮欏▎鍓у悑闂佽鍣换婵囨叏閳ь剟鏌ｅ▎灞戒壕濠电偞鎸搁…鐑藉蓟閺囥垹閱囨繝闈涙搐濞呇呯磽娴ｅ搫小闁告濞婂濠氭晲閸涘倹妫冮崺鈧い鎺戝閺呮繃銇勮箛鎾跺缂佺姵鐗犻弻銊╂偄閸濆嫅锝夋煕鐎ｎ亜顏柡灞剧缁犳稑顫濋鎸庣潖闂備礁鎲￠悷銉ノ涘Δ鍛厴闁硅揪闄勯崑鎰磽娴ｈ偂鎴︽煥椤撶偐鏀介柍钘夋娴滄繈鏌ｉ悢鍙夋珔闁伙絿鍏橀獮搴ㄦ嚍閵夈儮鍋撶紒妯圭箚妞ゆ牗绻傛禍褰掓煟閿曗偓閻楁挸顫忓ú顏呯劵闁绘劘灏€氭澘顭胯閹告娊寮婚悢纰辨晩闁靛鍎查幖鎰版⒑閸楃偞鍠橀柡灞炬礉缁犳稓鈧綆浜炴导鍕攽閳╁啫绲绘繛宸幖椤繒绱掑Ο鑲╂嚌闂侀€炲苯澧い顓炴穿椤﹁櫕銇勯妸锝呭姤缂佺姵鐩鎾偆娴ｅ湱绋愰梻鍌欑閹碱偄煤閵娾晛绐楅柟閭﹀厴閺嬪秹鏌ｅΟ鑲╁笡闁绘挻娲橀妵鍕敇閻旈浠存繛瀛樼矋缁诲牓寮诲☉妯锋瀻闊洦娲滈鍥⒑鐎圭媭娼愰柛銊ユ健楠炲啴鍩￠崨顓犵厬婵犮垼娉涢敃銉╊敂閳╁啩绻嗛柣鎰典簻閳ь剚娲滈幑銏ゅ箳閹炬潙寮挎俊鐐差儏鐎涒晠锝為弴銏＄厵闁绘垶蓱鐏忔壆绱撳鍛枠闁哄本娲樼换娑㈠垂椤旂厧袘闂備浇宕甸崰鍡涘礉閹达箑钃熺憸搴ｂ偓鐢靛帶閳诲酣骞嬮悩妯荤矒濮婃椽宕崟顕呮蕉闂佺锕ュú鐔凤耿娓氣偓閺岋絾鎯旈婊呅ｉ梺绋款儏閹虫﹢骞冮悽绋垮唨妞ゆ挾鍟块幏娲⒑閸涘﹦鈽夋い顓涘亾闂佺懓顕慨鐢稿汲濠婂牊鐓欓柣鎴烇供濞堟棃鏌ｉ幘杈捐€块柡宀€鍠愬蹇斻偅閸愨晩鈧秹姊虹粙娆惧剱闁告梹鐗犳俊鐢稿礋椤栨氨鐤€闂佸憡鎸风粈渚€宕虹仦绛嬫富闁靛牆鎳橀妤冪磼缂佹◤顏堬綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕导姝ゅ洭濡烽埡鍌楁嫼闁荤姴娲╃亸娆戠不閼碱兘鍋撻崗澶婁壕闂佸綊妫跨粈浣虹不閺嶎灛鏃堟晲閸涱厽娈查梺绋匡工椤兘寮婚妶澶婄畳闁圭儤鍨垫慨澶愭⒑瑜版帗鏁辨俊鐐舵椤繒绱掑Ο鑲╂嚌闂佹悶鍎滈崒婊冨毈缂傚倸鍊风粈渚€顢栭崱娑樼闁搞儺鍓欓弰銉╂煟閹邦剚鎯堢紒鐘烘珪娣囧﹪濡堕崟顔煎帯闂佸憡锕㈡禍璺侯潖濞差亜浼犻柛鏇ㄥ亝濞堟粓姊虹粙娆惧剱闁圭懓娲璇测槈閵忕姈鈺冩喐鎼淬劌姹叉い鎺戝閻撴瑦銇勯弴妤€浜剧紓浣哄У閻楃娀鐛崘顭戠叆闁割偆鍠庡▓鐔兼⒑闂堟侗妲堕柛搴㈠閼洪亶鎳￠妶鍥╋紳婵炶揪绲介幖顐ｇ閹€鏀芥い鏍ㄧ箓琚氶梺闈涙处濡啴鐛弽銊﹀闁告縿鍎查悡锝嗕繆閻愵亜鈧牕顔忔繝姘；闁瑰墽绮悡鍐偡濞嗗繐顏╅柣蹇撶摠閵囧嫰濮€閿涘嫭鍣伴悗娈垮櫘閸撶喐淇婇崼鏇為唶婵﹩鍏涙竟鏇㈡煟閻樺厖鑸柛鏂块铻炴い鏍ㄧ◤娴滄粓鏌熼幑鎰【闁哄鍨块弻娑欑節閸愩劌顫庨梺閫炲苯澧叉い顐㈩槸鐓ら煫鍥ㄧ☉绾惧潡鏌熼幆鐗堫棄闁绘帒鐏氶妵鍕箳閹搭垰濮涚紓浣割槺閺佸寮诲☉銏″亹闁归鐒﹂悿渚€姊虹化鏇熸珕闁烩晩鍨堕悰顔锯偓锝庡枟閺呮粓鏌﹀Ο渚Х闁告牗鐗犲缁樻媴鐟欏嫬浠╅梺绋垮瘨閸ㄨ泛鐣峰┑鍡欐殕闁逞屽墮椤曘儲绻濋崘顏嗙槇濠殿喗锕╅崢楣冨储闁秵鈷戦梻鍫熺〒婢ф洟鏌ｅΔ鈧幊妯虹暦閵夆晩鏁冮柕鍫濇川閿涙粓鏌℃径濠勫闁告柨鑻湁妞ゆ洍鍋撻柡宀€鍠庨悾鐑藉炊椤喓鍎甸弻鐔兼偡閺夋浼冮梺璇″灠鐎氫即鐛幒妤€绠婚柡澶嬪灩閿涙捇姊绘担鍛婃儓闁活厼顦遍幑銏犫攽閸℃瑦娈鹃梺闈浥堥弲娑氱棯瑜旈幃褰掑箒閹烘垵顬堥柣銏╁灠濞尖€愁潖缂佹ɑ濯寸紒娑橆儏濞堟劙姊洪幖鐐插鐎规洦鍓濋悘瀣⒑閸涘﹤濮﹂柛鐘崇墵瀵憡绗熼埀顒勫蓟閻斿吋鍋嬮柛顐ゅ枔閸戯繝姊虹紒妯哄闁挎洦浜璇差吋婢跺﹣绱堕梺鍛婃处閸嬪懎鈻撻鐔虹瘈婵炲牆鐏濋弸娑㈡煙鐠囇呯？闁瑰箍鍨归埞鎴犫偓锝庡亜娴犳椽姊婚崒姘卞闁告巻鍋撻梺缁樺姉閸庛倝鎮￠弴銏＄厪濠电偛鐏濋崝姗€鏌涚€ｃ劌鐏柍褜鍓濋～澶娒哄Ο渚富闁芥ê顦介崵鏇灻归悩宸剾闁轰礁娲弻锝夊箛椤撗冩櫛濠德ゅ皺閸忔ê顫忕紒妯诲闁告稑锕ラ崕鎾剁磽娴ｅ壊鍎庣紒鑸佃壘閻ｇ兘濮€閿涘嫷娴勯柣搴秵娴滅偤鏁嶅☉銏♀拺缂佸娉曢悘閬嶆煕鐎ｎ剙浠遍柟顔光偓鏂ユ闁靛骏绱曢崢閬嶆⒑闂堟侗妾х紒韫矙瀹曟繂顫濋懜鐢靛幗闂婎偄娴勭徊濂告焽椤栫偞鐓涚€光偓鐎ｎ剛袦濡ょ姷鍋為…鍥焵椤掑嫭娑ч柟璇х節瀹曟娊寮舵惔鎾存杸濡炪倖姊婚妴瀣绩缂佹ü绻嗛柣鎰閻瑩鏌曢崱鏇狀槮妞ゎ偅绮撻崺鈧い鎺嶆缁诲棙鎱ㄥ┑鍡欑劸婵℃煡绠栧娲传閸曨剦妫ゆ繝娈垮枤閺佹悂骞戦姀鐘斀閻庯綆浜為崢閬嶆⒑闁偛鑻晶瀵糕偓瑙勬礈閸犳牠銆侀弴銏╂晝闁挎繂瀛╅ˉ瀣⒒閸屾艾鈧娆㈠璺虹劦妞ゆ帒鍊告禒婊堟煠濞茶鐏￠柡鍛埣椤㈡稑顭ㄩ崨顖ょ床闂佽鍑界紞鍡涘磻閸曨厾绠旂憸鏃堝蓟閻旇偐宓侀柛顭戝枤娴煎牓鎮楃憴鍕闁告鍥х厴闁硅揪绠戠粻娑欍亜閹捐泛啸闁宠顦埞鎴︽偐閸偅姣勯梺绋款儐缁嬫垼鐏掓繝鐢靛Т閸熶即銆呴崣澶岀瘈濠电姴鍊搁鈺傘亜閺囶澀鎲鹃柡宀嬬到铻ｉ柤娴嬫櫅缁楋繝姊虹紒妯诲碍缂佺粯鍔欓垾锔炬崉閵婏箑纾梺鎯х箳閹虫捇銆傚ú顏呪拺闁告稑锕ュ畷宀€绱掗悩宕囧⒌鐎殿喖顭峰鎾晬閸曨厽婢戦梺璇插嚱缂嶅棙绂嶉弽顓炵；闁规崘顕ч崘鈧銈嗘尵閸犲孩绂嶅Δ鈧埞鎴︽倷閸欏妫￠梺鍦焾椤兘骞冮敓鐘虫櫜濠㈣泛鑻ぐ鍕⒑閹肩偛鍔︽い銉︽崌瀹曟岸寮跺Λ鐢垫嚀椤劑宕熼鐘靛帎闂備礁鐤囬～澶愬垂閸фぜ鈧礁鈻庨幘鏉戞異闂佸疇顕栭崕鎼佸炊閵娧冨箰闂佽绻掗崑娑欐櫠閽樺娲箻椤旂晫鍘遍梺鍐叉惈閸燁偅绂掓潏顭戞闁绘劕寮堕ˉ鈩冦亜閿曗偓瀹曨剟鈥︾捄銊﹀枂闁告洦鍓涢ˇ銉╂⒑鐎圭媭娼愰柛銊ユ健瀵偄顓兼径濠勵槹濡炪倖鍔忛崜婵嗩熆閳ь剟姊婚崒娆掑厡妞ゎ厼鐗撻弫鍐Ψ閳哄倸浜卞┑鐘诧工閻楀棝寮告担骞夸簻闁哄洦顨呮禍鎯旈悩闈涗沪閻㈩垱甯熼悘鍐⒑闁偛鑻晶鎵磼椤曞棛鍒伴摶鏍归敐鍥ㄥ殌鐎殿喖鐏濋埞鎴︻敊缁涘鐣跺┑鈽嗗亝椤ㄥ棝寮查懜鐢电瘈婵﹩鍘鹃崢浠嬫⒑閻熺増鎯堢紒澶婄埣閹苯鈻庨幘瀵稿幐閻庡厜鍋撻柍褜鍓熷畷浼村冀椤撶偠鎽曢梺鎼炲労閸撴岸寮插┑瀣厓鐟滄粓宕滈悢椋庢殾婵犻潧鏌堥弮鍫濆窛妞ゆ挾濯崯鍥ㄧ節閻㈤潧鍓崇紓宥呮瀹曟粌鈻庨幇顏嗙畾婵犻潧鍊搁幉锟犳偂閻斿吋鐓欓梺顓ㄧ畱婢ч箖妫呴澶婂⒋闁哄矉绱曟禒锕傛倷椤掑偆妲扮紓鍌欒兌缁垳鎹㈤崱娆戜笉婵炴垶锕╁鈺佄ｇ仦鍓у閺佸牆鈹戦悩鍨毄闁稿鐩、姘额敇閻旂寮挎繛鏉戝悑濞兼瑩宕归崒鐐寸參婵☆垯璀﹀Ο鍫熺箾閸忚偐澧紒缁樼☉椤斿繘顢欓懡銈呭毈婵＄偑鍊戦崕閬嶆偋婵犲嫭宕叉繛鎴欏灩缁狅綁鏌ｉ幇顒備粵闁革綀妫勯埞鎴﹀煡閸℃ぞ绨介梺绋款儍閸婃洟锝炶箛娑欐優閻熸瑥瀚崢褰掓⒑閸涘﹣绶遍柛鐘充亢閵囨劘顦规慨濠冩そ楠炴劖鎯旈姀顫喘闂備焦鎮堕崝宀€绱炴繝鍥モ偓浣割潩閼稿灚娅滄繝銏ｅ煐钃遍柡鍛箞濮婃椽骞愭惔銏紩闂佺顑嗛幐楣冩儉椤忓牆绠氱憸瀣磻閵忋倖鐓涚€光偓鐎ｎ剛袦濡ょ姷鍋涘ú顓€佸鈧幃銏ゆ惞閸忓鐎煎┑鐘垫暩閸嬫盯顢氶鐔稿弿闁圭虎鍠栧洿闂佸綊妫跨粈渚€鎷戦悢鍏肩叆婵犻潧妫涙晶銏ゆ煟閵堝倸浜鹃梻鍌欑閹碱偄煤閵娾晛纾绘俊顖滃帶閸ㄦ繈鏌涢锝嗙闁抽攱鍨归惀顏堫敇閻愭潙顎涢梺鎼炲€曢鍥╂閹烘梻纾兼俊顖濆亹閻ゅ嫬螖閻橀潧浠滈柛鐕佸亰閿濈偛顭ㄩ崼婵堝姦濡炪倖宸婚崑鎾绘煟閿濆懎妲绘い顐ｇ矒閸┾偓妞ゆ帒瀚ㄩ埀顑跨閳诲酣骞橀弶鎴滄偅闂佽绻掗崑鐘参涢崟顓犱笉婵炲樊浜濋埛鎺懨归敐鍕劅闁衡偓閺夋鐔嗛柣鐔稿婢э附顨ラ悙瀛樺磳妞ゃ垺妫冨畷鍗烆潨閸℃绋愰梻鍌欑閹碱偄煤閵忋倕鍨傛繛宸簻绾惧鏌嶉崫鍕偓鑸电濠婂牊鐓欓柟顖嗗啳鍩為梺璇叉禋娴滎亪寮婚敐澶婄閻庢稒顭囬ˇ鏉课旈悩闈涗沪闁绘娲濊ぐ浣割渻閵堝棗鍧婇柛瀣尭閳规垿鍩勯崘鈹夸虎闂佸搫鐬奸崰鏍ь嚕婵犳艾唯鐟滃繘寮抽锔解拺闁告繂瀚悘閬嶆煕閻樺磭澧甸柕鍡曠閳诲酣骞樺鍕ㄦ櫊閺屾洘寰勯崼婵嗗闂佽绻戦幑鍥ь潖閾忓湱纾兼俊顖濐嚙閽勫ジ姊虹粙鎸庢崳闁轰浇顕ч锝囨嫚濞村顫嶅┑鐘诧工閹虫劙寮堕幖浣光拺闁告繂瀚婵嬫煕婵犲骸浜伴柡浣瑰姍瀹曢亶寮撮悩鐢垫毎闂傚倷鑳剁划顖炲礉閺嶃劎鐝堕柛鈩冪⊕閸庢绻涢崱妯虹亶闁稿鎸搁埢鎾诲垂椤旂晫褰梻浣侯焾椤戝懘鏁冮鍫熷仒妞ゆ洍鍋撶€规洖鐖奸、妤呭焵椤掑倻妫憸鏃堝箖瑜版帒绠掗柟鐑樺灥椤牓姊洪柅鐐茶嫰婢т即鏌涚€ｃ劌鈧洟锝炶箛鎾佹椽顢旈崟顓фО闂備礁鎲￠悷銉┧囨导鏉戠？闁瑰墽绮埛鎴︽煕濠靛嫬鍔氶弽锛勭磽娴ｅ壊鍎愰柟鍝ヮ焾瀹撳嫰姊洪崷顓烆暭婵犮垺顭囩划鍫ュ礃閳哄啰顔曢梺鍝勵槹閸╁牓宕曢幇鐗堢厸闁稿本顨呮禍楣冩⒒閸屾艾鈧兘鎳楅崜浣稿灊妞ゆ牜鍋涚粈澶嬫叏濡炶浜鹃悗瑙勬礃濡炶棄顕ｆ禒瀣垫晞闁告瑣鍎查惈蹇涙煟閻斿摜鐭婄紒缁樺笒鍗遍柟鐗堟緲缁犺櫕淇婇妶鍛殭鐟滄澘瀚—鍐Χ閸℃ê鏆楁繝娈垮枤閸忔﹢骞冮敓鐘茬缂備焦菤閹锋椽鏌ｉ悩鍙夌闁逞屽墲濞呮洖鈻撻銏♀拺闁硅偐鍋涢崝鈧梺鍛婂姦閸樻悂宕戦幘璇插瀭妞ゆ棁顫夐弬鈧梻浣虹帛閸旀牕顭囧▎鎾村€堕柨鏂款潟娴滄粍銇勯幘璺轰沪闁哥姵锕㈤弻鐔碱敊閸忕厧浠撮悗瑙勬礀閻栧ジ銆佸Δ浣瑰闁告瑥顦褰掓⒒閸屾瑧绐旀繛鑹板吹閳ь剟娼ч惌鍌氱暦閵忥紕闄勯柟鑲╁亹閸嬫捇宕掗悙鑼槯闂佸吋绁撮弲婵嬫儊閸儲鈷戦梻鍫熺〒缁犳碍淇婇幓鎺戭伃闁硅櫕鎸鹃幑鍕Ω閵忕姳澹曞┑鐐茬墕閻忔繈寮稿☉銏＄厵閻犲泧鍛槇濡ょ姷鍋涚换妯虹暦閵娧€鍋撳☉娅亜鈻撻幇顑芥斀闁绘绮☉褎绻涚拠褏鐣甸挊鐔兼煕椤愮姴鍔滈柣鎾寸☉闇夐柨婵嗘处閸も偓婵犳鍠栫粔鍫曞焵椤掑喚娼愭繛鎻掔箻瀹曟繈骞嬮敂琛″亾娴ｅ壊娼ㄩ柍褜鍓熼獮鍐閵堝懐顦梺鍦帛鐢寮抽銏♀拻闁稿本鑹鹃埀顒佹倐瀹曟劙鎮滈懞銉ユ畱闂佸壊鍋呭ú宥夊焵椤掑﹦鐣电€规洖銈告俊鐑芥晜閼恒儳褰囬梻鍌欑窔濞佳囨偋閸℃蛋鍥ㄥ閺夋垹锛涙繝銏ｆ硾鑹岄柡鈧禒瀣厱閻忕偛澧介惌銈夋煟閹烘鐣洪柡宀嬬畵瀹曟﹢顢旈崟顒備邯闂備礁鎼悮顐﹀礉瀹€鍕厴闁硅揪绠戦獮銏ゆ煃閸濆嫬鈧劙鏁傞崜褏锛濇繛杈剧到閹碱偅鐗庣紓鍌欑椤戝棛鏁埄鍐х箚闁汇垻顭堢粈瀣亜閺嶃劍鐨戞い鏂匡躬濮婃椽鎮烽幍顔芥喖缂備焦妞界粻鏍х暦閹达箑绠绘鐐层仒濮规姊洪崷顓炲妺闁搞劌缍婇幃鍧楀川鐎涙ǚ鎷洪梺绋跨箺閸嬫劙濡堕幘顔界厸闁告侗鍠氱粻妯侯熆鐟欏嫭绀嬮柟绋匡攻缁旂喎鈹戦崱娆懶ㄩ梺杞扮劍閸旀瑥鐣烽崡鐐嶆棃宕橀鍌氫画濠电姷鏁搁崑娑㈡偤閵娧冨灊闁规儳澧庢稉宥夋煛瀹擃喖鏈紞搴♀攽閻愬弶鈻曞ù婊勭箞閹偞绻濆顓犲幗闂佸綊鍋婇崹浼存嫊婵傚憡鍊垫慨姗嗗幗缁跺弶銇勯鈥冲姷妞わ箑鍟块…鍧楁偡閻楀牜妫ゅ┑鈥冲级閸旀瑩鐛幒妤€绠婚悗闈涙憸鑲栭梻鍌欑窔濞佳団€﹂鐘典笉闁硅揪闄勯ˉ澶屸偓骞垮劚椤︿即鍩涢幋锔界厽闁绘柨鎲＄欢鍙変繆閹绘帩鐓奸柡宀€鍠栧畷姗€鎳犻鍌ゅ敽缂傚倷绶￠崰鏍敄婢舵劗宓侀柟鐑橆殔濡﹢鏌涘┑鍡楊仹濠㈣娲熷娲箰鎼达絿鐣电紓浣靛姀閸嬫劙鎳炴潏銊ч檮闁告稑锕﹂崢鐢告⒑閹勭闁稿妫濋獮濠囧炊閵婏箑寮挎繝鐢靛Т鐎氼喚鏁☉銏＄厵鐎瑰嫮澧楅崳浠嬫煙閸欏灏︾€规洜鍠栭、鏇㈠灳閾忣偅鍟熼梻鍌氬€搁崐椋庣矆娓氣偓楠炲鏁撻悩鑼舵憰闂侀潧臎閸涱垳鍘犻梻浣稿閸嬪懎煤閺嶎厽鍊块柛顭戝亖娴滄粓鏌熼悜妯虹仴闁逞屽墮椤兘鐛繝鍋芥棃宕ㄩ鎯у箞闂備礁鎼ú銏ゅ礉瀹€鍕祦闁规壆澧楅悡娑㈡煃?",
            "direct": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棗鏆欏┑鈥炽偢閺屽秷顧侀柛鎾存皑閹广垽宕煎┑鎰婵犵數濮甸懝楣冨础閹惰姤鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú鐔奉潖閾忓湱纾兼俊顖氭惈琚濋梻浣告啞閹歌鐣濋幖浣哥畺闁汇垻顭堢猾宥夋煕椤愩倕鏆遍柟閿嬫そ濮婅櫣娑甸崨顓濇睏闂佺顑嗙粙鎺撶┍婵犲啰闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛瀣閹剝绺介崨濠勫幈闂佸疇顫夐崕铏閻愵兛绻嗛柣鎰典簻閳ь剚鐗滈弫顕€骞掑Δ鈧粣妤佹叏濮楀棗澧婚柣鎺嶇矙閺岀喖鏌囬敃鈧獮妯肩磼閻樿崵鐣洪柡灞剧☉閳诲氦绠涢敐鍠般劍绻濋埛鈧仦濂稿仐闂佽鍣换婵囦繆閼搁潧绶為悗锝庡墮瀵娊姊绘担鍛婃儓婵炲眰鍔戝畷鎴濃槈濞嗘埈娲搁梺瑙勵問閸犳氨澹曢悾灞稿亾楠炲灝鍔氭俊顐ｇ⊕閺呭爼鎮介崨濠勫幐閻庡厜鍋撻悗锝庡墰閻﹀牓鎮楃憴鍕闁绘牕銈稿畷娲晸閻樿尙鍔﹀銈嗗笒閸婂綊锝為弴鐘亾鐟欏嫭绀€婵炶绠撳畷浼村箛閻楀牏鍘藉┑掳鍊愰崑鎾绘煟濡も偓濡稓鍒掗銏犵闁哄啫鍊婚敍婊堟⒑闁偛鑻晶瀵糕偓瑙勬礃鐢繝骞冨▎鎴斿亾閻㈡鐒炬鐐茬墦濮婄粯绻濇惔鈥茬盎濠电偠顕滅粻鎾诲箠濠靛鍊锋い鎺戝亞濞叉悂姊洪棃鈺佺槣闁告ê澧芥竟鏇熺附閸涘﹤鈧敻鏌ㄥ┑鍡欏嚬缂併劏鍋愰埀顒傛嚀閹诧紕鎹㈤崟顓燁潟闁圭儤鎸荤紞鍥煏婵犲繒鐣遍梻澶婄Ч濮婃椽鎮烽弶鎸幮╅梺纭呮珪閿氶柣锝囧厴椤㈡洟鏁冮埀顒傜矆鐎ｎ剛妫柣妤€鐓鍛洸闁告挆鈧崑鎾诲礂婢跺﹣澹曢梻浣告啞濞诧箓宕滃☉銏犲偍闂侇剙绉甸埛鎴犵磽娴ｅ厜妫ㄦい蹇撴椤ユ碍銇勯幘璺烘瀾婵炲懐濞€閺岋綁濮€閻樺啿鏆堥梺缁樻尰濞茬喖寮诲澶婁紶闁告洦鍋呭▓顓熺箾鐎电鞋濡炲瓨鎮傞妴鍐Ψ閳哄倸鈧鈧懓澹婇崰鏍礈閸洘鈷戦弶鐐村椤︼箓鏌涙繝鍌涘仴妤犵偞鍔栫换婵嬪礃閵娧呯嵁濠电姰鍨煎▔娑㈩敄閸パ岀劷闁哄稁鍘介埛鎺楁煕鐏炴崘澹橀柍褜鍓熼ˉ鎾跺垝閸喐濯撮梻鍫氭櫈閳ь剙娼″鍫曞醇濮橆厽鐝旈梺鎼炲妽缁诲啴濡甸崟顖氬唨闁靛鍎卞В鍫ユ⒑閸濄儱鏋庨柟鍐查叄閸╃偤骞嬮敂钘変汗闁诲骸婀辨慨鎾夊┑鍫㈢＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽幃銏ゆ偂鎼达絿鏆伴柣鐔哥矋缁挸鐣烽悽鍛婂亜闁惧繐婀遍敍婊堟⒑閹惰姤鏆滈柛瀣崌閺屾稓鈧綆鍋呯亸鎵磼缂佹绠撻柍缁樻崌瀹曞綊顢欓悾灞兼喚闂傚倷鐒︾€笛兠哄澶婄柧闁绘灏欓弳锔界節婵犲倸鏆婃俊鎻掔墛缁绘盯宕卞Ο鏇熷灴椤㈡瑩寮崼鐔叉嫼闂佺鍋愰崑娑㈠礉濮椻偓閺屾盯寮幐搴㈠闯缂備緡鍠氱划顖炲Χ閿濆绀冮柍杞拌閸嬫捇鎮介崨濠勫幗闂侀潧绻嗗Σ鍛村疮韫囨稒鐓熼柟鐑樺灥閳锋棃鏌嶈閸撴氨绮欓幒鏃€宕查柛宀€鍋愰埀顒佹瀹曟﹢顢欓崲澹洦鐓曢柍鈺佸枤濞堟ê霉閻樿櫕缍戦柍瑙勫灴閸┿儵宕卞鍓у嚬缂傚倷娴囬褔鎮ч幘缁樺仒妞ゆ洍鍋撶€规洘锕㈤、娆撴嚍閵夛富浠ч梻鍌欒兌缁垶鏁嬮梺鍝ュ枑鐎笛呯矉瀹ュ拋鐓ラ柛顐ゅ暱閹锋椽姊洪崨濠勨槈闁挎洩濡囩槐鎾愁潩閼哥數鍘遍柟鍏肩暘閸ㄥ綊鍩㈤弴銏＄厵妞ゆ牗鐟х粣鏃傗偓瑙勬礀閵堟悂骞冮姀銈嗘優闁革富鍘介～宀勬⒒閸屾瑧鍔嶉柣顏勭秺瀹曞綊鎸婃径妯煎姺閻熸粌绉归幃娲敇閵忊檧鎷绘繛杈剧导鐠€锕傛倿妤ｅ啯鐓ラ柡鍥崝锔筋殽閻愭彃鏆ｇ€规洘甯￠幃娆擃敂娴ｉ晲澹曟繛鎾村焹閸嬫挾鈧鍣崳锝呯暦閻撳簶鏀介柛顐ｇ箓缁犱即姊婚崒娆掑厡妞ゎ厼鐗撳鐢割敆閸屾稓鐣崇紓鍌氬€烽梽宥夊礉瀹€鍕ㄢ偓锕傛倻閽樺鎽曢梺缁樻⒒閸樠呯矆閸岀偞鐓犳繛鏉戭儐濞呭棙绻涢崼顐㈠⒋婵﹥妞介獮鏍倷閹绘帩鐎虫俊鐐€ら崢楣冨礂濮椻偓閻涱噣宕卞Δ鍐╂畷闂佸憡娲﹂崑鍡涱敊婵犲倵鏀介幒鎶藉磹閹剧粯鍤勯柛顐ｆ礀閸屻劑鏌熼梻瀵稿妽闁稿﹦鏁婚弻娑滅疀閹垮啯笑婵炲瓨绮撶粻鏍蓟閿濆棙鍎熸い鏍ㄧ矌鏍￠梻浣告啞閹歌崵绮欓弽顓炵劵闂傚牊绋堥弨浠嬫煥濞戞ê顏╁ù婊冦偢閺屾稒绻濋崘銊т紝閻庤娲滈幊鎾跺弲濡炪倕绻愰幊蹇撯枍閸ヮ剚鈷戦梻鍫熺〒缁犵偤鏌涙繝鍐╃缂侇喖顭峰浠嬵敇閻斿搫甯鹃梻濠庡亜濞诧箑煤閺嵮勬瘎闂傚倷绀侀幖顐⑽涘Δ鍜佹晞濠㈣埖鍔曢拑鐔兼煃閳轰礁鏆欑紒鍓佸仜閳规垿鎮╅幓鎺撴闂佺粯绻冮悧鐘差潖濞差亝鍋￠梺顓ㄧ畱濞堝爼姊虹粙娆惧剱妞ゎ厼娲獮鎴﹀閵堝懎鑰垮┑鐐村灦閻熝囧储娴犲鈷戦悷娆忓缁舵煡鏌涘锝呬壕缂傚倷闄嶉崝宀勨€﹂悜钘夎摕鐎广儱鐗滃銊╂⒑閸涘﹥灏扮€光偓閹间礁绠栫憸鏂款嚕閹绢喗鍋愰柟缁樺笧閺屟囨⒒閸屾艾鈧悂鈥﹂鍕；闁告洦鍊嬪ú顏呮櫆闁告挆鍛幆闂備胶鎳撻顓熸叏閹绢啟澶婎潩閼哥數鍘遍悷婊冮叄閵嗗啴宕卞☉妯煎幈闂佸湱鍎ら〃鍡涙偂閺囩喆浜滈柟鎵虫櫅閳ь剚娲熷鎼佸籍閸喓鍘梺绯曞墲閿氭繛鎼櫍閺屸€崇暆鐎ｎ剛鐦堥悗瑙勬礋娴滃爼銆佸鈧幃鈺呭垂椤愶綆鍟岄梻鍌氬€风粈渚€骞栭锔藉剹濠㈣泛鐬肩粈濠偯归敐鍛棌闁搞倖娲橀妵鍕即濡も偓娴滈箖鎮楃憴鍕閻㈩垱甯熼悘鍐╃箾鏉堝墽鍒伴柟鑺ョ矎閵囨劙鎮介崨濞炬嫽闂佺鏈悷锔剧矈閻楀牅绻嗘俊鐐靛帶婵¤法绱掗鑲╁缂佹鍠栭崺鈧い鎺戝閳ь兛绶氬浠嬪Ω閵壯呯嵁闂備礁缍婇崑濠囧礈濠靛绠洪柡鍥╁亹閺€浠嬫煟閹邦厽缍戦柣蹇ョ畵閹筹綁濡堕崱鏇犵畾闂佸湱绮敮鐐存櫠閿曞倹鐓涢悘鐐插⒔閳藉鎽堕弽顓熺厱闁规壋鏅涙俊铏圭磼椤旂厧顣崇紒杈ㄦ尰閹峰懘宕崟鎴稻娣囧﹪鎮欓懜娈挎濡炪値鍋勭换鎰弲濡炪倕绻愮€氼亞妲愰崼鏇熲拺闁告稑锕ユ径鍕煕閹惧崬濡挎俊鍙夊姍閹瑩鎮滃Ο閿嬪闂備礁鎲＄粙鎴︹€﹂鍕€垮ù鐘差儐閻撴盯鏌涘鈧粈浣圭閻楀牜娈介柣鎰綑閻忔潙鈹戦鐟颁壕闂備胶绮敃鈺呭磻閸涙潙妫橀柍褜鍓熷铏规嫚閹绘帒姣愮紓鍌氱Т濡繂鐣烽幋锕€绀嬫い鎺戝亞濞村嫬鈹戦悙鍙夆枙濞存粍绻堥崺娑㈠箳濡や胶鍘遍柣蹇曞仧閸嬫捇鎯冮幋婵愮唵鐟滃海绮欓幘鑸殿潟闁圭儤鏌￠崑鎾绘晲鎼粹€茬盎婵犳鍠栧ú顓㈠蓟瀹ュ洦濯肩€规洖娲ㄩ悡鎾愁渻閵堝啫鐏俊顐㈠暙閻ｉ攱绺介崨濠備簻闂佸憡鐟ラˇ顖烆敂瑜版帗鈷掗柛灞剧懄缁佹壆鈧娲滈弫璇茬暦娴兼潙绠婚悗娑櫳戦悵宄扳攽鎺抽崐鏇㈠箠鎼淬劍鍋い鏇楀亾闁哄矉缍侀獮鍥敊閻撳骸顬嗛梻浣虹帛閹稿鎮烽敃鍌毼﹂柛鏇ㄥ灠缁秹鏌涚仦鎹愬濞寸姵锕㈠娲焻閻愯尪瀚板褜鍠楃换娑氭兜妞嬪海鐦堝Δ鐘靛仜閸燁垳鈧潧銈搁獮鏍敇閻斿憡鐝﹂梻鍌欐缁鳖喚寰婃禒瀣剶濠靛倸鎲￠崕濠囨煕椤愮姴鍔滈柍閿嬪灴閺屾稑鈽夊鍫燁暭缂備礁鐖兼禍鍫曞蓟濞戙垹惟闁挎洍鍋撻柍缁樻礈閳ь剚顔栭崰鏍ㄦ櫠鎼达絽鍨濇繛鍡樺姈閸庣喖鏌熼幆褏鎽犻柡澶嬫倐濮婄粯鎷呴搹鐟扮闂佸憡姊归悧鏇⑩€﹂崶褉鏋庨柟鐐綑閳ь剙鐖奸弻銊╁即閻愭祴鍋撹ぐ鎺撳亗闁绘棃鏅茬换鍡涙煏閸繂顏い锔肩畵閺岋綀绠涢幙鍐ㄦ闂侀€炲苯澧叉い顐㈩槸鐓ゆ慨妞诲亾鐎规洖缍婂畷绋课旈崘銊с偊婵犵妲呴崹浼村触鐎ｎ兘鍋撳顓炲摵闁哄被鍊楅崰濠囧础閻愭祴鎷绘繝寰枫倕鐨哄褎顨嗙粚杈ㄧ節閸ャ劌鈧攱銇勮箛鎾愁仱闁稿鎹囧浠嬧€栭浣衡姇闁瑰嘲鎳橀幊鏍р攽閸モ晜鍒涢悗瑙勬礈閸犳牠銆佸Δ鍛＜闁靛牆妫濋弫婊冣攽閻樺灚鏆╁┑顔芥尦閺佸啴濡舵径瀣罕婵犵數濮村ú銈夋偂閺囥垺鐓欓悗鐢殿焾鍟哥紒鐐劤閵堟悂骞冨Δ鍛櫜閹肩补鈧磭顔戠紓浣鸿檸閸樺吋鏅舵惔锝嗩潟闁圭儤顨嗛崑鎰版煕濡ゅ啫浠滅紒渚囧櫍濮婃椽宕崟顒佹嫳缂備礁顑嗛崹鍧楁晲閻愭祴鏀介悗锝呯仛閺呫垺绻濋姀锝嗙【闁挎洏鍊栫粩鐔煎醇閵夛腹鎷绘繛杈剧到閹芥粓寮搁崘鈹夸簻闁哄洤妫楅幊鎰版儗閹剧粯鐓熼柣鏃傚帶娴滀即鏌涢妶鍡樼闂囧鏌ｅΟ鐑樷枙闁稿孩鐩弻鈩冩媴閸涘﹤鏋犻梺鍝勭焿缂嶄礁顕ｉ鍕閹兼番鍨归崜鍨繆閵堝洤啸闁稿鍋ら妴鍐╃節閸屻倖缍庣紓鍌欑劍椤洨寮ч埀顒勬煙閼测晞藟闁逞屽墲鐏忔瑩鎯勬惔銏㈢瘈闁汇垽娼ф禒鈺傘亜閺囩喓鐭岀紒顔碱煼楠炲鎮╅幓鎺旀煣闂傚倸鍊风粈渚€骞栭銈囩煋闁哄被鍎辩粈澶愬箹濞ｎ剙濡搁柍褜鍓欓幊姗€骞冨鍫熷殟闁靛／鍐ㄧ瑲闂傚倷绀侀幉锛勬崲閸屾壕鍋撳鐓庡籍鐎规洖鍟跨叅妞ゅ繐鎳愰崢浠嬫⒑鐟欏嫬鍔ら柣掳鍔庣划鍫⑩偓锝庡枟閻撴瑦銇勯弮鍌滄憘婵炲牊绮撻弻鈩冩媴閻熸澘顫嶉梺璇″灡濡啴宕规ィ鍐╁殤妞ゆ帒鍊归弲銊モ攽閻樺灚鏆╁┑顔炬暬椤㈡瑩寮介鐐电崶闂佸搫绋侀崢鏃堝炊閵婏妇绉堕梺鍐叉惈閸嬪棗顭囬悢鍏尖拺闁革富鍘奸崝瀣亜閵娿儳绠荤€殿噮鍋呯换婵嬪炊閵娧冨箺闂備焦瀵х换鍌炲箠韫囨搫鑰垮ù鐓庣摠閻撴洟鏌ㄥ┑鍡涱€楁鐐搭焽缁辨帗娼忛妸锕€闉嶉梺鐟板槻閹虫﹢骞栬ぐ鎺撳仭闁规鍣崑褏绱撻崒姘偓宄懊归崶顒夋晪鐟滄柨鐣烽幇鏉块敜婵°倓鐒﹀▍婊堟⒑缂佹ê濮堢紒浣规尦瀵劍绂掔€ｎ偄鈧敻鏌ㄥ┑鍡樺櫧濞寸姵鐩弻锟犲川椤愩垻浼堝┑顔硷龚濞咃絿鍒掑▎鎴炲磯闁靛ě鍌滅闂傚倷鑳堕…鍫ヮ敄閸ヮ剙绐楅幖娣妽閸嬧晝鈧懓瀚伴崑濠囨偂閵夆晜鐓曟い鎰╁€曢弳閬嶆煙瀹勯偊鐓兼慨濠呮缁瑩骞愭惔銏″闂備浇宕甸崯娆撳炊娴ｅ憡鍠橀柡浣稿暣瀹曟帒鈽夊顒€绠為梻鍌欒兌缁垰螞閸愵喖缁╅梺顒€绉寸壕濠氭煏婢舵稑鐦滄繛鍫滅矙閺岋綁骞囬澶婃婵犫拃鍐粵闁靛洤瀚版慨鈧柍鈺佸暟椤︿即姊烘潪鎵妽闁告梹鐟ラ悾鐑筋敂閸涱喖顎撻梺鍛婄☉椤剟宕畝鍕拻闁稿本鑹鹃埀顒勵棑缁牊鎷呴棃鈺勨偓鍧楁⒑椤掆偓缁夊澹曢崸妤佺厪闁割偅绻嶅Σ鍫曟煃瑜滈崜娆撳疮閺夋垹鏆﹂柕濞炬櫓閺佸秵绻濇繛鎯т壕缂備焦顨呴ˇ闈涱潖濞差亜绠伴幖杈剧悼閻ｉ潧鈹戦埥鍡椾簼缂佸鎸搁锝堫樄闁糕斁鍋撳銈嗗笒鐎氼參鍩涢幋锔解拻闁割偆鍠撻妴鎺旂磼閻樺啿鍝洪柡宀嬬節瀹曘劑顢欓悙顒€娅氭俊銈囧Х閸嬫盯宕锔绘晣濠靛倻顭堥悙濠囨煃閸濆嫬鏋︾紒杈ㄥ▕閺岋絾鎯旈敍鍕殯闂佺姘︽禍顒勫焵椤掍礁鍤柛锝忕秬濡喖姊洪幐搴㈢闁稿﹤缍婇幃锟犳偄閸忚偐鍙嗗┑鐘绘涧濡瑩骞栭幇鐗堢厱婵☆垳绮紞鎴︽煃鐟欏嫬鐏撮柛鈺佸瀹曟﹢鍩℃担鎻掍壕闁规壆澧楅悡娑樏归敐鍥剁劸闁逞屽墮閻忔繈鎮惧畡閭︾叆闁糕檧鏅滈瀷濠电姷顣介崜婵娿亹閸愵煁娲敇閻戝棙缍庣紓鍌欑劍钃卞┑顖涙綑閵嗘帒顫濋悡搴ｄ化闂佸憡姊归幃鍌炲蓟閿濆鍊烽柡澶嬪灥濮ｅ牓姊虹粙娆惧剰闁挎洏鍊濋幃楣冩倻閽樺鐤€闂佸搫顦悘婵嗙暤閸℃稒鈷戠紓浣姑慨鈧梺鍝勬噺缁捇骞冨Ο鑽ょ懝闁逞屽墮椤繘鎼归崷顓犵厯闁荤姵浜介崝搴敊閹达附鈷戠紒瀣儥閸庢劙鏌涢弮鈧〃鍛搭敋閿濆牜妯勯梺绯曟杹閸嬫挸顪冮妶鍡楀潑闁稿鎹囬弻宥囨喆閸曨偆浼岄梺璇″枟閻熲晠骞婇悩娲绘晢闁逞屽墴閵嗗倸煤椤忓應鎷洪柣鐘叉穿鐏忔瑧绮婚懠顒傜＜閻犲洩灏欐晶鏇熴亜閺囶亞绉鐐寸墬閹峰懘鎮锋０浣虹泿闂傚倷鑳堕…鍫㈡崲濡ゅ懎纾婚柟鐗堟緲閻鏌涢埄鍐姇闁抽攱鍨块弻娑樷攽閸℃浠炬繝銏ｆ硾鐎氼參濡甸崟顖毼╅柕澶涘瘜濡偤姊虹€圭媭鍤欑紒澶屾暩閹广垹鈹戠€ｎ亞顦伴梺闈涱焾閸庣増绔熼弴銏＄厽闁绘柨鎽滈幊鍐倵濮樼厧骞樼紒顔肩墦瀹曟﹢顢旈崱娆欑床婵＄偑鍊栧Λ渚€宕戦幇鐗堝€块柟闂寸劍閻撱儲绻濋棃娑氬濞寸姵绮撻弻宥囨喆閸曨偆浼岄悗瑙勬礀閵堟悂骞冮姀鈽嗘Ч閹兼惌鍨崇涵鈧梻鍌氬€搁崐鐑芥倿閿曞倸纾跨€规洖娲﹀畷鍙変繆閵堝懏瀚呯紓宥嗙墪椤潡鎳滈棃娑橆潔闂佺锕ら悘婵婄亙闂佹寧绻傞幊搴ㄥ汲閻愮儤鐓冮梺鍨儏缁楁帡妫佹径鎰叆婵犻潧妫涙晶娑欍亜韫囨洖鈻堥柟顔荤矙椤㈡稑鈽夊顓炲灡闂備礁鎼張顒勬儎椤栨凹鍤曟い鏇楀亾闁糕斁鍋撳銈嗗笒鐎氥劑鍩€椤掆偓閸燁垳鎹㈠┑瀣＜婵犲﹤瀚鏇㈡⒒娴ｅ憡鎯堟繛灞傚灲瀹曞綊鎮烽悧鍫㈠嚱濠电姷鏁告慨浼村垂閻撳簶鏋栨繛鎴欏灪閺呮繈鏌ㄩ弴鐐测偓褰掑疾椤掍胶绠鹃柟瀛樼懃閻忣亪鏌嶉柨瀣伌闁哄瞼鍠撶划娆撳箰鎼淬垹闂紓鍌欒兌婵敻骞愭繝姘﹂柛鏇ㄥ灡閺呮粓鏌涢…鎴濇灈缂佷緡鍣ｅ铏规嫚閳ヨ櫕鐝紓浣虹帛缁诲倿顢氶敐澶婄妞ゆ梻鈷堝濠囨⒑閹稿海鈽夐悗姘煎墰閺侇噣骞嗚閺€浠嬫煟濮楀棗鏋涢柣蹇氶哺缁绘稒寰勭€ｎ剚鍒涘銈冨灪閻楃姴鐣烽妸褉鍋撳☉娅亪鍩€椤掆偓閻栧ジ寮婚弴鐔风窞闁糕剝蓱閻濇洟姊虹紒妯诲鞍闁烩晩鍨跺璇测槈閵忊晜鏅濆銈嗗姦濠⑩偓缂併劎绮换婵嬪煕閳ь剛浠﹂懞銉у綆闂備礁鎼惌澶屾崲濠靛棛鏆﹂弶鍫亞閻も偓闂佸搫鍟犻崑鎾绘煟濠靛洨澧辩紒杈ㄦ尰閹峰懏绂掔€ｎ亝鎳欓梻浣告贡閹虫挸煤閵堝鍋╅柣鎴ｆ缁犳娊鏌熼幖顓炲箺闁稿秹娼ч—鍐Χ閸℃浼囧┑鈽嗗亜鐎氼厾绮嬪鍡愬亝闁告劏鏅濋崢鐢告⒒閸屾艾鈧悂顢氶鈶哄洭鏁傞崜褎锛忛梺璇″瀻閸涱垍銊╂⒑閸濆嫭婀扮紒瀣灴閸╃偤骞嬮敃鈧粈瀣亜閹扳晛鐏╃悮姗€姊婚崒娆戝妽婵＄偛娼″畷銏＄鐎ｎ亞顔囬梺褰掓？閻掞妇绮婚幒妤佲拻濞达絿鎳撻婊呯磼鐠囨彃鈧潡鐛繝鍐╁劅闁靛鍎叉潏鍫ユ⒑缂佹ê濮夐柛搴涘€濋幃鈥斥枎閹惧鍘遍梺褰掑亰閸ㄤ即鎯冨ú顏呯厽闊洦鐭崥顐ょ磼鏉堛劌绗氭繛鐓庣箻婵℃悂鏁冮埀顒傚閹惰姤鍊甸悷娆忓缁€鍐偨椤栨稑娴柛鈹垮灪閹棃濡搁妷褜鍚呮俊鐐€栭幐楣冨疮濡警鐓ラ柛鏇ㄤ簽缁犳岸姊虹紒妯哄Е濞存粍绮撻崺鈧い鎺嶈兌婢х數鈧娲栫紞濠囧箖閻ｅ瞼鐭欓悹鎭掑妿閺嬪啯绻濈喊妯活潑闁搞劏浜埀顒傜懗閸ヤ礁顦垫俊鑸靛緞鐎Ｑ勫濠电偠鎻徊浠嬪箟閿熺姴绠氶柛顐ゅ枂娴滄粓鏌ㄩ弬璺ㄤ虎鐎规挸妫欓妵鍕閿涘嫬鈪归梺瀹狀嚙闁帮綁鐛鈧鍫曞箣閺傚じ澹曢梺绉嗗嫷娈曢柣鎾跺█閺岀喖顢橀悢椋庣懆闂佸憡姊归敋闂囧绻濇繝鍌氼伀闁活厽甯￠弻锝夊箼閸愩劋鍠婇悗瑙勬礀閻栧吋淇婇幖浣规櫇闁逞屽墴瀵啿螖娴ｈ櫣鐦堥梺鍐茬殱閸嬫捇鏌涢弴銊ュ妞わ富鍘剧槐鎾存媴娴犲鎽甸柣銏╁灲缁绘繈鐛崘顔肩厸闁告粈鐒﹂弲鈺呮⒑缂佹ɑ灏Δ鐘虫倐閿濈偛顫濋懜纰樻嫽婵炴挻鍩冮崑鎾寸箾娴ｅ啿鍘惧ú顏勎ч柛銉到娴滅偓鎱ㄥ鍡楀箺缂佽泛寮堕妵鍕即椤忓棛袦濡炪們鍨洪〃濠傜暦閻旂⒈鏁冮柕蹇婃噰閸嬫捇顢橀悜鍡樺瘜闂侀潧鐗嗗Λ娆撍夐崱妯镐簻妞ゆ劑鍩勫Σ娲煃瑜滈崜娆撴倶濮樿埖鍋嬮柣妯烘▕濞兼牜绱撴担鑲℃垶鍒婇幘顔界厱婵炴垶锕銉╂煛閸℃澧曢柍瑙勫灴閸┿儵宕卞鍓ф殫缂傚倷璁查崑鎾炽€掑锝呬壕闂佺硶鏂傞崹钘夘嚕椤掍焦鍎熼柟鐐儗濞兼棃姊绘笟鈧褏鎹㈤幒鎾村弿闁绘垼妫勯崒銊╂煙缂併垹鏋熼柍閿嬪灩閻ヮ亪顢橀悙鏉戞閻熸粍濡搁崶銊㈡嫽闂佸憡娲﹂崑鍕敂椤撶姭鍋撶憴鍕闁告梹鐟╅獮鍐煥閸喎娈熼梺闈涳紡閸愩劎顔囧┑鐘垫暩婵即宕归悡搴樻灃婵炴垯鍩勯弫鍕煕濞戞鎽犻柛濠傜埣閺屽秵娼悧鍫氬亾閵夈劊浜归柟鐑樻尭娴滃綊姊洪幆褎绂嬮柛瀣閸┾偓妞ゆ帊绀佹慨鍫ユ煙娓氬灝濡界紒缁樼箞瀹曟﹢鍩炴径姝屾闂佽姘﹂～澶娒洪敃鍌氱；濠电姴鍊婚弳锕傛煟閺冨倵鎷￠柡浣割儔閺屾稑鈽夐崡鐐寸仌闂佸搫鎲為崶銊㈡嫽闂佺鏈悷褔藝閿曞倹鐓欐繛鏉戭儌閸嬫捇骞囨担鍦▉闁荤喐绮庢晶妤冩暜閹烘鍨傞柛宀€鍋為悡鏇犳喐鎼淬劊鈧啴宕煎┑鍫熸婵炴挻鍩冮崑鎾绘煛鐏炲墽娲存鐐叉喘濡啫鈽夊Ο渚妧濠电姷顣藉Σ鍛村垂閹殿喒鍋撳鐓庡⒉闁诲繐鍟村铏圭磼濮楀牐鈧寧绻涙担鍐插椤╅攱绻濇繝鍌氼伀缂佺姴澧介埀顒傛嚀婢瑰﹪宕伴弽褜鍤曟い鏇楀亾闁哄本娲熷畷閬嶅即閻欌偓濡差噣姊虹€圭媭鍤欓梺甯秮閻涱喖顫滈埀顒€顕ｉ崼鏇炵闁绘ɑ鍓氶埀顒€绉电换婵嬫偨闂堟刀鐐烘煕閵娧冨付闁崇粯鏌ㄩ埥澶愬閳╁啯鐝栭梻浣瑰濞叉牠宕愰崨濠傤嚤闁绘顕х粻瑙勭箾閿濆骸澧┑鈥茬矙閺屽秹鏌ㄧ€ｎ亝璇為梺鍝勬湰缁嬫挻绂掗敃鍌氱鐟滃酣宕抽纰辨富闁靛牆绻楅铏圭磼閻樿櫕宕岀€殿喖顭烽幃銏ゅ传閸曨剛鈧娊姊洪崨濠庢畼闁稿顭囬懞閬嶆偩瀹€鈧壕钘夈€掑顒佹悙闁哄鍠栭弻锝夋偆閸屾凹娲紓渚囧櫘閸欏啴骞冮姀銈嗗亗閹艰揪绲芥慨锔戒繆閻愵亜鈧牕顔忔繝姘；闁瑰墽绮悡鐔兼煥濠靛棙鎼愰柛妯绘綑閳规垿顢欓悷棰佸闂傚倷鐒︾€笛呯矙閹寸姭鍋撳顓熺凡妞ゎ剙锕、娆撳礈瑜忛敍婵囩箾鏉堝墽鍒板鐟帮躬瀹曟洟骞樼€靛摜顔曟繝銏ｆ硾椤戝棛绮堢€ｎ喗瀵犳繝闈涱儐閻撳繐鈹戦悙闈涗壕婵炲懎妫濋弻宥夋煥鐎ｎ亞浼屽┑顔硷攻濡炰粙銆侀弴銏犖ч柛娑卞墰閹规洟姊绘担绋挎倯婵＄偛娼″畷褰掓焼瀹ュ懐鏌ч梺鍓插亝濞叉牜绮荤紒妯镐簻闁哄啫鍊瑰▍鏇㈡煕濮椻偓濞佳団€旈崘顔嘉ч柛鈩兦氶幏濠氭⒑閻戔晛澧查柡灞诲姂閸┿垽骞橀幇浣哄弳闂佸壊鍋嗛崰鎾诲储闂堟侗娓婚柕鍫濇閳锋劙鏌涙惔銏犫枙鐎规洏鍨婚埀顒傛暩绾爼宕戦幘鏂ユ灁闁割煈鍠楅悘鏇炩攽閻愬樊妲归柣鈺婂灦瀹曟椽濮€閳╁啫鍔呴梺闈涱焾閸庢娊鎮￠幋锔解拺闂傚牊鍐荤槐锟犳煕濠婂啫鏆熼柛鎺撶⊕缁绘繈鎮介棃娴躲儲銇勯敐搴℃灓婵″弶鍔欏鎾閻樼绱遍梻浣侯攰閹活亞绮婚幋鐘差棜闁革富鍘介崰鎰扮叓閸ャ劍绀冩い顐ｆ礋閺岋綁骞囬浣瑰創闂佺粯鍔曢敃顏堝蓟閺囩喓绠鹃柛顭戝枓閸嬫挸螖閸愵亙绗夊┑顔筋焾閸╂牠鍩涢幋锔界厵闁兼祴鏅涙禒婊堟煕閺冣偓閹告娊寮诲☉銏犵閻庨潧鎲￠崳顔剧磽娓氬洤鏋涢柣妤佹尭閻ｇ兘宕￠悙鈺傤潔濠电偛妫欓崹鐢哥嵁瀹ュ鈷掑ù锝堟鐢盯鏌涢妸銉у煟闁轰礁鍟撮崺鈩冩媴閸欏浜栭梻浣告惈濞层垽宕瑰ú顏呭亗闁哄洢鍨洪崐鐢告煥濠靛棗鏆欏┑锛勫帶閳规垿顢欓悡搴樺亾閸ф钃熼柨娑樺濞岊亪鏌涢幘妞诲亾婵℃彃鐗撳铏光偓鍦У椤ュ銇勯敂璇茬仸闁挎繄鍋涢…銊╁醇濠靛鏁规繝鐢靛█濞佳兾涢鐑嗙劷妞ゆ帒瀚埛?",
        }.get(mode, "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棗鏆欏┑鈥炽偢閺屽秷顧侀柛鎾存皑閹广垽宕煎┑鎰婵犵數濮甸懝楣冨础閹惰姤鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú鐔奉潖閾忓湱纾兼俊顖氭惈琚濋梻浣告啞閹歌鐣濋幖浣哥畺闁汇垻顭堢猾宥夋煕椤愩倕鏆遍柟閿嬫そ濮婅櫣娑甸崨顓濇睏闂佺顑嗙粙鎺撶┍婵犲啰闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛瀣閹剝绺介崨濠勫幈闂佸疇顫夐崕铏閻愵兛绻嗛柣鎰典簻閳ь剚鐗滈弫顕€骞掑Δ鈧粣妤佹叏濮楀棗澧婚柣鎺嶇矙閺岀喖鏌囬敃鈧獮妯肩磼閻樿崵鐣洪柡灞剧☉閳诲氦绠涢敐鍠般劍绻濋埛鈧仦濂稿仐闂佽鍣换婵囦繆閼搁潧绶為悗锝庡墮瀵娊姊绘担鍛婃儓婵炲眰鍔戝畷鎴濃槈濞嗘埈娲搁梺瑙勵問閸犳氨澹曢悾灞稿亾楠炲灝鍔氭俊顐ｇ⊕閺呭爼鎮介崨濠勫幐閻庡厜鍋撻悗锝庡墰閻﹀牓鎮楃憴鍕闁绘牕銈稿畷娲晸閻樿尙鍔﹀銈嗗笒閸婂綊锝為弴鐘亾鐟欏嫭绀€婵炶绠撳畷浼村箛閻楀牏鍘藉┑掳鍊愰崑鎾绘煟濡も偓濡稓鍒掗銏犵闁哄啫鍊婚敍婊堟⒑闁偛鑻晶瀵糕偓瑙勬礃鐢繝骞冨▎鎴斿亾閻㈡鐒炬鐐茬墦濮婄粯绻濇惔鈥茬盎濠电偠顕滅粻鎾诲箠濠靛鍊锋い鎺戝亞濞叉悂姊洪棃鈺佺槣闁告ê澧芥竟鏇熺附閸涘﹤鈧敻鏌ㄥ┑鍡欏嚬缂併劏鍋愰埀顒傛嚀閹诧紕鎹㈤崟顓燁潟闁圭儤鎸荤紞鍥煏婵犲繒鐣遍梻澶婄Ч濮婃椽鎮烽弶鎸幮╅梺纭呮珪閿曘垽鎮伴鈧獮妯兼嫚閼碱剦鍞洪柣搴＄畭閸庨亶骞忕€ｎ€稑顭ㄩ崼鐔叉嫽闂佺鏈懝楣冨焵椤掑倸鍘撮柟铏殜瀹曞ジ寮村璇蹭壕闁挎洖鍊搁柋鍥煏婢舵稓鐣遍柛鎾瑰煐缁绘繈妫冨☉妯峰亾婵犳埃鈧箓宕奸姀鐙€妫滄繝鐢靛У绾板秹鎮￠悢鍏肩厵闂侇叏绠戦弸娑㈡煕閺傛鍎旈柡灞剧〒閳ь剨缍嗘禍婊堝焵椤掆偓濞尖€愁嚕婵犳碍鏅搁柣妯垮皺閸婄偤姊虹€圭姵銆冮柣鎺炵畵閹顢橀悢铏诡啎闁诲孩绋掗…鍥儗鐎ｎ剛纾兼い鏃囧Г瀹曞瞼鈧鍠栭…鐑藉箖閵忋倖鍋傞幖杈剧秮閻涙捇姊绘担绋款棌闁绘挸鐗撳畷鎶筋敋閳ь剙顕ｉ幎钘夘潊闁靛牆妫岄幏娲煟閻樺弶绀岄柍褜鍓濆▍鏇㈡倶閺囥垺鈷戠紒瀣儥閸庢劙鏌涢弮鈧〃鍛祫闂佸湱澧楀妯肩不閾忣偂绻嗛柕鍫濆椤︼箑霉濠婂啰绉烘慨濠冩そ楠炲棜顦崇紒鍌氼儔閺屾稓鈧綆浜滈顓犫偓娈垮枛閸熻儻鐏冮梺鍛婂姦娴滅偤鏁嶅┑鍥╃閺夊牆澧界€佃偐绱掗鐣屾噰鐎规洦鍋勭叅妞ゅ繐鎳庢禒鍝勵渻閵堝棛澧い銊ユ噺閺呭爼骞撻幑娑橀叄瀹曟儼顧傞棅顒夊墯椤ㄣ儵鎮欑€电顫ч梺鐟板槻閹冲酣婀侀柣搴秵娴滄瑦绔熼弴銏♀拺闁圭瀛╃粈鈧梺绋匡工閹芥粎鍒掓繝姘櫜闁糕剝鐟ч惁鍫ユ⒒閸屾氨澧涚紒瀣笧缁﹪鍩￠崨顔惧幈闂佺粯鍔曢顓㈠矗閳ь剙鈹戦纭峰伐妞ゎ厼鍢查悾鐑藉箳閹搭厽鍍靛銈嗗灱濡嫭绂嶉崜褏纾奸悗锝庡亾缁扁晜绻涘顔荤盎閸ュ瓨绻濋姀銏☆仧缂佺姵鍨电叅妞ゆ挶鍨圭粻鏍煟閿濆懐鐏遍柣顓熺懇閺屻倝骞囨担鍝ヤ画闂佺寮撻崡鍐差潖缂佹鐟归柍褜鍓欓…鍥樄闁炽儻绠撳畷濂稿Ψ閵壯嶇吹婵＄偑鍊栧ú宥夊磻閹惧灈鍋撳▓鍨灁闁告柨绉剁划瀣箳閺傚搫浜鹃柨婵嗛娴滅偤鏌涘鈧禍璺侯潖濞差亜妫橀柕澶涢檮閻濇棃姊洪崨濠勬噭闁告梹鐟╅悰顔锯偓锝庡枟閺呮繈鏌嶈閸撴稓鍒掓繝姘唨闁靛ě鍜佸晭闂備胶纭堕崜婵婃懌闁诲繐绻嬮崡鎶藉蓟閿濆绠婚悗娑欘焽椤︿即姊洪崫鍕効缂傚秳绀侀锝夘敆閸曨偆顔囬柟鑲╄ˉ閸撴繂鈻撳鈧缁樻媴娓氼垳鍔搁梺鎸庢磸閸庨潧鐣峰┑鍡忔瀻闁规儳鐤囬幗鏇㈡⒑閹稿海鈽夐悗姘间簻閳讳粙顢旈崼鐔蜂化闂佹悶鍎崝搴ㄥΧ閹绢喗鐓曢悗锝庡亝鐏忣參鏌嶇憴鍕仼闁逞屽墾缂嶅棝宕滃▎鎴犵焾闁挎洖鍊归埛鎴犳喐閻楀牆绗掑ù婊€鍗抽弻娑樜熼崷顓犵厯閻庤娲樺ú鐔煎箖閵忋倕绀傞柤娴嬫櫅瀵櫕绻濋悽闈涒枅婵炰匠鍏炬稑鈻庨幘宥咁槸椤劑宕熼鐙€鍟庨梻浣告啞娓氭宕伴弽顓熷€堕悗娑櫳戦崣蹇撯攽閻樻彃浜為柣鎾瑰亹閳ь剝顫夊ú妯兼暜閹烘缍栨繝闈涱儛閺佸洭鏌ｉ弮鍌ょ劸闁逞屽墴閺€杈ㄧ┍婵犲洦鍊锋い蹇撳閸嬫捁顦冲ǎ鍥э躬瀹曞爼顢楅埀顒勫几娓氣偓閹綊宕惰閳绘洟鏌涢妶鍡樼闁宠鍨块幃鈺冣偓鍦Т椤ユ繈鏌熼婊冩灈婵﹥妞藉Λ鍐ㄢ槈鏉堛剱銈夋⒑閹肩偛濡芥俊鐐舵椤曪綁顢楅崟顐ゅ姦濡炪倖甯掔€氼參鍩涢幒鎳ㄥ綊鏁愰崼鐕佷哗闂侀潧妫楅敃顏堝蓟濞戙垹绠婚悗闈涙憸閻ゅ嫰姊烘潪鎵槮妞ゆ垵鎳橀崺鐐哄箣閿旇棄鈧兘鏌涘▎蹇ｆЦ闁哄棔绶氬娲川婵犱胶绻侀梺鎼炲妽婵炲﹪寮鍛斀闁搞儮鏅濋鏇㈡煛婢跺﹦澧曞褌绮欏畷姘鐎涙鍘电紒鐐緲瀹曨剚绂嶆导瀛樼厽閹兼番鍔嶉弫杈╃磼缂佹绠為柟顔荤矙濡啫鈽夊Δ鍐╁礋闂傚倷鑳堕幊鎾诲疮鐠恒劍宕查柟閭﹀枛瀵弶绻濋悽闈浶㈤柨鏇樺€濋幃褔宕卞▎鎴滅瑝闂佸搫琚崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧悶姘ュ劚閳规垿鍩勯崘銊хシ闂佺粯顨嗛幑鍥ь嚕婵犳艾鍗抽柨娑樺閺夋悂鏌ｆ惔顖滅У濞存粎鍋炵粋鎺撶附閸涘﹤浠┑鐘诧工鐎氼厾娆㈤弻銉﹀€垫慨妯煎帶婢ф挳鏌嶉妷锔筋棃鐎规洘锕㈤、娆撳床婢诡垰娲﹂悡鏇㈡煃閳轰礁骞樻い蹇撶墕濮瑰弶淇婇妶鍛櫤闁抽攱鍨圭槐鎺斺偓锝庡亽閸庛儵鏌涙惔銏犲缂佽鲸甯為埀顒婄秵閸嬪懐浜搁悽鍛婄厱闁圭儤鎸哥粭姘辩磼缂佹绠炵€规洖鐖奸幊婊堝垂椤愶絿褰ｉ梻鍌氬€风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭墎鈧稒锕╁▓浠嬫煟閹邦厼绲婚柡鍡樼懇閹藉爼寮介鐔哄帗閻熸粍绮撳畷婊堟偄閻撳孩妲梺闈涚箞閸婃洜绮绘繝姘仯闁搞儯鍔岀徊濠氭煟鎼搭喖骞栨い顏勫暣婵″爼宕卞Ο閿嬪闂備礁鎼幏瀣磻閸涱垳鐭夌€广儱顦伴崐鐑芥煟閵忋垺鏆╅柨娑欑箞濮婅櫣绮欓幐搴㈡嫳闂佽崵鍟欓崨顔碱伕婵炲鍘ч悺銊╂偂閺囥垺鐓熸俊顖濐嚙婢ь垱绻涢崼鐔虹煉闁哄瞼鍠栭、娆撳箚瑜嶉獮瀣節绾板纾块柛蹇旓耿瀹曟椽鏁撻悩鑼紲濠殿喗锕╅崑鍛村磻閸涘瓨鈷掗柛灞剧懆閸忓瞼绱掗鍛仸鐎规洖缍婇幃锟犵嵁椤掍胶娲寸€规洜鍠栭、姗€鎮╂潏鈺冩喒濠电姵顔栭崰妤呪€﹂崼銉ユ槬闁哄稁鍘奸悡鏇㈡煙鐎电浜煎ù婊勭矒閺岀喖骞嗚閼哥懓鈹戦鐓庘偓瑙勭┍婵犲嫮纾奸柕蹇曞У閻忓牆顪冮妶搴′簴闁搞劏妫勯悾鐑藉醇閺囥劍鏅㈡繛杈剧到瀵墎鈧俺妫勯埞鎴︽倷閼搁潧娑х紓浣瑰絻濞硷繝骞冨ú顏勭睄闁割偅绻傞幆鐐测攽閻愬弶顥為柟绋款煼瀹曟劙宕归銈囶啎闂佺懓顕崑娑氱箔濮橆厾绠鹃柛娑卞幗椤ョ姷绱掓潏銊ョ瑨闁伙絾绻堝畷鐔碱敂閸涱厽鐏撻梻鍌欑濠€閬嶅储瑜忕槐鐐寸節閸パ嗘憰闂佸憡渚楅崢绋课ｉ崼鐔稿弿婵妫楁晶顕€鏌嶉柨瀣闁宠鍨块幃鈺呭垂椤愶絾鐦庨梻浣侯焾椤戝棛绮欓幋锝囦罕婵犵數鍋涘Λ娆撳箰閹间礁鍨傞柛宀€鍋為悡鏇熴亜閹板墎绋荤紒宀冩硶缁辨挸顓奸崱娆忊拰闂佸搫鐭夌换婵嗙暦閸洖唯闁靛／鍌滄／闂傚倷鑳剁划顖炲箰婵犳碍鍋￠柍鍝勬噹閽冪喖鏌ｉ弮鍌氬妺闁哥姴妫濋弻娑㈠即閵娿儰绨婚悶姘箞濮婄粯鎷呯憴鍕哗闂佺锕ラ悧鐘诲箖閻ゎ垼妯勯梺璇″灙閸嬫挸顪冮妶鍛闁绘妫涚划璇差潩鏉堛劌鏋戦悗骞垮劚椤︻垳绮婚弽顓熺厵閺夊牓绠栧顕€鏌ｉ幘瀵告噧闁靛棙甯掗～婵嬵敆閸屾瑨妾稿┑鐘殿暯閳ь剙鍟块幃鎴︽煏閸パ冾伃妞ゃ垺娲熼弫鎰板炊閳哄啫甯ㄩ梺璇叉唉椤煤閺嵮呮殾妞ゆ帒鍟版禍娆撴⒒娓氣偓閳ь剛鍋涢懟顖涙櫠閹殿喚纾兼い鏃€顑欓崵娆撴偂閵堝棎浜滈煫鍥ㄦ尰閸ｆ娊鏌熼悿顖涱仩缂佽鲸鎸婚幏鍛村礈閹绘帒澹堥梻浣筋嚙缁绘垹鎹㈤崼銉ｂ偓浣肝旈崨顓ф綂闂侀潧鐗嗗Λ娑㈠储閻㈠憡鈷戦柤濮愬€曢弸鏂款熆瑜庨〃濠傜暦閺夎鐔访虹紒姗嗗晬闂備胶绮崝鏍亹閸愵喖姹叉繛鍡樻尰閻撶喖鏌ㄥ┑鍡欑缂佲檧鍋撻梻浣告惈閼活垰煤椤撱垹鏋侀柛宀€鍋涚粻姘辨喐瀹ュ憛褔寮婚妷锔规嫽闂佺鏈悷褔藝閿曞倹鐓欐繛鏉戭儏婢ц尙绱掑Δ鍐ㄦ瀻閾绘牠鏌涘☉鍗炲箻闁绘挻鍨块弻鐔煎礂閼测晜娈梺鍛婃煥閼活垱鏅ラ梺鍛婄懃椤︻厽绂嶅鍫熺厵闁诡垎鍐煘闂佽娴氭禍顏堝蓟瀹ュ鐓ラ悗锝庝簽娴煎矂姊洪崫鍕効缂傚秳绶氶悰顔锯偓锝庡枛缁秹鏌嶈閸撴瑩鍩㈠澶婂耿婵☆垵鍋愰鏇㈡⒑閸涘﹣绶遍柛鐘愁殔閻ｅ嘲鐣濋崟顒傚幐闁诲繒鍋涙晶钘壝洪弶鎴旀斀闁斥晛鍟崐鎰攽閳╁啯鍊愰柡浣稿€圭粚閬嶅箥娴ｉ晲澹曢梺褰掑亰閸擄箑銆掓繝姘厪闁割偅绻冮ˉ鐐电磼瀹€鍐╃《缂佽鲸鎸搁濂稿礋椤撶姷宕查梻渚€娼уΛ鏃傛濮橆剦鍤曢柟缁㈠枛椤懘鏌ｅ▎灞戒壕濠电偟鍘ч敃顏勵潖閾忓厜鍋撻崷顓炐ｉ柕鍡楀暣閺岋綁骞掗悙鐢垫殼閻庤娲橀崝娆撱€佸☉銏″€风紒顔款潐鐎氳棄鈹戦悙鑸靛涧缂傚秮鍋撳銈庡亜椤﹂潧鐣烽幋锔藉亹缂備焦顭囬崢閬嶆煙閼测晞藟婵℃彃鎳橀幃锟犲礂閸忕厧寮挎繝鐢靛С閼冲爼鎯屽▎鎴斿亾鐟欏嫭绀堥柛鐘崇墵閵嗕礁鈽夊鍡樺兊婵℃彃鏈悧妤佹櫏闂傚倸鍊搁崐椋庣矆娓氣偓楠炲鏁撻悩鑼槷闂佹寧娲栭崐鍝ョ玻濡や椒绻嗛柕鍫濇噺閸ｅ綊鏌ｉ幘瀛樼闁哄瞼鍠愬蹇斻偅閸愨晩鈧秹姊虹紒妯诲暗濠电偐鍋撻梺鍝勭灱閸犳牠銆佸鈧幃銏☆槹鎼达絾鍣梻鍌欑閹诧繝骞栭埡鍛偍濞寸姴顑呮闂佸憡娲﹂崰姘舵偪閳ь剟姊虹憴鍕婵炲鐩獮鍐偓锝庡枟閳锋垿鏌熼懖鈺佷粶闁告梹鎸抽弻娑㈠箻鐎靛憡鍣梺姹囧労娴滐綁藝鐟欏嫷娈介柣鎰嚟婢ч亶鏌嶈閸撴氨绮欓幒鏇熸噷闂佽绻愮换瀣础閹惰棄钃熼柨婵嗘閸庣喖鏌曞娑㈩暒閾忓孩绻濆▓鍨灈闁挎洏鍎遍—鍐寠婢跺本娈鹃梺闈涱煭婵″洨寮ч埀顒勬⒑缁嬫寧婀版い鏇熸尦瀵挳濮€閳锯偓閹锋椽姊洪崨濠勭細闁稿氦椴搁悧搴繆閻愵亜鈧垿宕濆畝鍕櫇妞ゅ繐瀚弳锕傛煕濠靛棗顏ゆ俊鎻掔墦閺屾洝绠涢弴鐐愩儲銇勯幘瀛樸仢婵﹨娅ｇ槐鎺懳熻箛锝勯偗闁诡喗锚椤繈鎳滈崹顐ｇ彨闂傚鍋勫ú锕傚箹閳轰降鈧帗绻濆顓犲帾闂佸壊鍋呯换鍐夐悙鐑樺€堕煫鍥ㄦ礃閺嗩剟鏌＄仦鍓с€掗柍褜鍓ㄧ紞鍡涘礈濞嗘劗顩烽弶鍫氭杹閸嬫挾鎲撮崟顒傤槰婵犵數鍋涢敃顏堢嵁閺嶎兙浜归柟鐑樺灦瀹撳秴顪冮妶鍡樺暗闁革綇濡囧Σ鎰板焺閸愌呯畾闂佺粯鍔︽禍婊堝焵椤掍胶澧垫鐐村姍瀹曞ジ寮撮悙鑼偓顓熺節閻㈤潧校缁炬澘绉瑰畷鎴﹀煛閸屾粎顔曢悗鐟板閸犳洜鑺辨總鍛婄厽闁规儳顕ú鎾煙椤旀枻鑰块柟顔界懄閿涙劕鈹戦崱姗嗗敳婵犵數濮甸鏍窗閺嶎厼纾瑰┑鐘宠壘閻掑灚銇勯幒宥囪窗闁哥喎绻橀弻娑㈡偐閹颁焦鐣跺銈庡幖濞层倝鍩㈡惔銊ョ闁哄倹宕橀崺鍛存⒒閸屾瑦绁扮€规洜鏁诲畷鎴︽倷閻㈢數鐓撻梺鍓插亖閸庨亶鎮為崹顐犱簻闁瑰搫妫楁禍楣冩⒑閸涘鎴︽偋濡ゅ啰鍗氶柣鏃傚帶閸楁娊鏌曡箛濠冾€嗛柟閿嬫そ濮婃椽宕ㄦ繝鍕暤闁诲孩鍑归崳锝夊春閵忊€崇窞闁归偊鍘鹃崢鍗炩攽閳藉棗鐏犻柣蹇旂箖缁傚秹宕烽鐘碉紲濡炪倖姊婚埛鍫ユ偂婵傚憡鐓欐い鏃傛櫕閹冲洭鏌熼鐣岀煀閾伙綁鏌ｉ幘鎶筋€楀┑鈥虫处缁绘繈鎮介棃娴躲儵鏌℃担瑙勫€愮€规洘鍨块幃銏ゆ偂鎼达綇绱遍梻浣告贡閸嬫捇寮告總绋垮嚑鐎广儱顦伴悡鏇熺箾閹寸儐鐒介柟鐣屽█閺岋綁骞樼捄鐑樼亪闂佸搫鐬奸崰鏍嵁閸℃凹妾ㄩ梺鎼炲€楅崰鎰崲濞戙垹鐭楀璺侯儏閸炲姊洪崫鍕効缂佽鲸娲樼粋鎺楁晝閸屾氨顦悷婊冾儔閸┾偓妞ゆ帊绀佺粭鎺楁婢舵劖鐓熸繛鍡楃箲閸ｄ粙鏌ｉ敐鍥ㄦ毄闁逞屽墲椤煤濡厧鍨濋煫鍥ㄨ泲閸ヮ剦鏁婇柟瀛樺笧缁犳岸姊洪崷顓犲笡閻㈩垳鍋為弲鍫曞即閻旂繝绨诲銈呯箰鐎氼剟寮抽敐鍛斀闁炽儱纾崺锝団偓瑙勬磸閸旀垿銆佸Ο娆炬Щ婵犵绱曢崗妯侯潖缂佹ɑ濯撮柣鎴灻▓宀勬⒑绾拋鍤嬬紒缁樼箞閻涱噣宕橀鑲╋紲闂佺粯鍔曞璺何ｉ鍕拺缂備焦锚婵洭鏌熺喊鍗炰簽缂侇喖顭烽弫鎰緞鐎ｎ剙寮抽梻浣告惈閸燁偄煤閿曞伖澶嬪緞婵炴帞鎳撻…銊╁礃椤忓柊銊╂⒑閸濆嫮鐒跨紓宥勭窔楠炲啴鍩￠崨顓犵厬婵犮垼娉涢敃銈夋嚑閸愵喗鈷掑ù锝呮啞閸熺偤鏌涢幙鍐ㄥ⒋鐎规洏鍔戦、娑橆煥閸愩劎鐣遍梻鍌氬€搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌ｉ幋锝呅撻柛銈呭閺屾盯顢曢敐鍡欙紭闂侀€炲苯鍘搁柣鎺炲閹广垹鈹戠€ｎ亞锛滃┑掳鍊撻懗鍫曞焵椤掍焦銇濇慨濠冩そ瀹曨偊宕熼鈧崑宥夋⒑閹肩偛濡兼繝鈧潏鈺佸灊闁割偆鍠庣欢鐐烘倵閿濆倹娅囩紒鐘冲哺濮婃椽妫冨☉姘暫闂佺锕ら幉锛勭矉瀹ュ棎鍋呴柛鎰ㄦ櫇閸樺崬鈹戞幊閸婃洟骞婂澶婄疅濡わ絽鍟悡娑氣偓鍏夊亾闁逞屽墴瀹曚即寮介鐐舵憰闂佹悶鍎洪崜姘跺疾濠靛鐓冪憸婊堝礈濮樿泛鐤鹃柛鎾茶兌绾惧吋淇婇婵嗕汗妞ゆ梹娲熼弻锝堢疀閹惧墎顔夐梺缁橆殕椤ㄥ懘鍩㈠鍡欑瘈闁搞儯鍔庨崢鎼佹煟韫囨洖浠╂い鏇嗗洤鐒垫い鎺嶈兌缁犳捇鏌ｉ敐鍥у幋妞ゃ垺娲熼弫鍐焵椤掆偓閺侇噣姊绘担鐟邦嚋婵☆偂鐒﹂幈銊╁Χ婢跺鍓ㄩ柟鍏肩暘閸斿秹鍩涢幒鎳ㄥ綊鏁愰崨顔兼殘闂佸摜鍠撻崑銈夊蓟閵娾晛鍗虫俊顖濇娴犲墽绱撴担绋库偓鍝ョ矓閸洖绠查柛鏇ㄥ墰閻熻銇勯弽銊с€掔紒瀣╃劍缁绘繈鎮介棃娑楃捕濠碘槅鍨伴敃銉х矉瀹ュ拋鐓ラ柛顐ｇ箘椤斿姊洪悡搴㈡喐闁稿绲剧粋宥咁煥閸喓鍘甸梺纭咁潐閸旀牜娑甸幆顬″綊鎮╁畷鍥╃厐闂佸疇顫夐崹鍧楀春閸曨垰绀冮柍鐟般仒閾忓孩绻濆▓鍨灈闁挎洏鍎遍—鍐寠婢跺本娈惧銈嗗姧缁犳垹绮堢€ｎ偁浜滈柡鍥╁仦閸ｆ椽鏌﹂幋婵愭█婵﹦绮幏鍛村川婵犲倹娈樻繝娈垮枛閿曘倗绱炴繝鍌滄殾鐟滅増甯掔粻浼村箹鐎涙绠樼紒鐘冲哺濮婃椽宕烽鈩冾€楅梺鍝ュУ閻楁粍绔熼弴鐔洪檮闁告稑锕﹂崢浠嬫⒑瑜版帒浜伴柛銊ゅ嵆閹啴鎮滃Ο闀愮盎闁挎粌顭峰畷鍫曞Ω閵忊€愁伖闂傚倷鑳堕…鍫㈡崲濡ゅ懎纾婚柟鐗堟緲鍥撮梺鍦檸閸犳鎮″☉銏＄厱婵炴垵宕弸銈囩磼閻橀潧浠﹂柕鍥у婵偓闁挎稑瀚崳浼存倵濞堝灝鏋熼柟姝屾珪閹便劑鍩€椤掑嫭鐓冮梺娆惧灠娴滈箖姊鸿ぐ鎺撴暠婵＄偘绮欏濠氭晲婢跺浜滈梺鍛婄缚閸庢煡宕宠閺岋絾鎯旈姀鐘叉瘓闂佸憡鎸鹃崰搴ㄦ偩瀹勬壋鏀介悗锝庘偓顓婂喚鐔嗛悹杞拌閸庢垿鏌涘鈧禍璺侯潖閾忓湱纾兼俊顖涙た濡啴姊虹悰鈥充壕闂備緡鍓欑粔瀵稿婵犳碍鐓忓璺烘濞呭棝鏌ｉ幘宕囩闁哄本鐩崺鍕礃閻愵剛鏆ラ梻渚€鈧偛鑻晶顕€鏌ｈ箛鏃傜疄闁诡喗鍎抽悾锟犲箯閺冨倸鏋涚€规洘顨婇幃鈩冩償閵忥紕褰哄┑鐘垫暩閸嬬娀骞撻鍡楃筏闁秆勵殔绾惧潡鏌曢崼婵愭Ц闁告艾缍婇弻宥堫檨闁告挻鐟╅垾鏃堝礃椤斿槈褔骞栫划鍏夊亾瀹曞浂鍞归梻鍌欑閹测€愁潖瑜版帒鍨傞柣銏犳啞閸嬧晠鏌ｉ幋锝呅撻柛瀣閻ヮ亪骞忓畝鍕懙闂佸搫鎷戠紞浣割潖閾忓湱纾兼俊顖滃劦閹疯顪冮妶搴″箹闁绘鎸搁锝夊蓟閵夈儰绱堕梺闈涳紡閸滃啰闂梻鍌欒兌椤牓寮甸鍕殞濡わ絽鍟悞鍨亜閹烘垵鈧悂宕㈤幘顔界厵闁惧浚鍋掑▓婊堟煙閾忣偆鐭掔€规洖缍婇、鏇㈠閻樿京绀嬮梻鍌氬€烽悞锕傛儑瑜版帒鍨傚┑鐘宠壘閺嬩線鏌熼梻瀵稿妽闁稿孩顨嗙换娑㈠幢濡闉嶉梺缁樻尰閻熲晠寮婚悢鐑樺枂闁告洦鍋勮闂備焦鎮堕崐鏍偡閳哄懎钃熼柨婵嗩槸缁犳娊鏌熺€电小缂侇喚鏁诲娲濞戞瑦鎮欓柣搴㈢煯閸楁娊鎮伴鈧獮鎺懳旈埀顒傜不閿濆棎浜滈柡宥冨妿閳洟鏌￠崱鏇炲祮婵﹦绮粭鐔煎焵椤掑嫬鐒垫い鎺戝€告禒婊堟煠濞茶鐏︾€规洏鍨介幃浠嬪川婵犲嫬骞堥梺鐟板悑閻ｎ亪宕濆鍛鐟滄棃寮婚敐澶嬫櫜闁告侗鍘戒簺闂佸彞绱徊鍓ф崲濞戙垹骞㈡繛鍡楃箣婢规洖霉濠婂嫮鈽夐柍?")
    return {
        "guided": "I will steady the target and gap first, then reduce the work to the smallest move.",
        "balanced": "I will give you direction and implementation traction first, then expand only as needed.",
        "direct": "I will give you the implementation path directly, while still explaining why it works.",
    }.get(mode, "I will steady the target and gap first, then reduce the work to the smallest move.")


def _compose_scaffold_paragraphs(
    *,
    scenario: str,
    mode: str,
    learner_signal: str,
    anchor: str,
    diagnosis: str,
    next_step: str,
    teaching_note: str,
    close: str,
    chinese: bool,
) -> list[str]:
    if chinese:
        if scenario in {"review", "task", "next_task", "engineering_challenge"}:
            return [
                anchor,
                f"{diagnosis} {next_step}".strip(),
                teaching_note,
                close,
            ]
        if scenario in {"principle", "plan", "concept_teaching"}:
            return [
                anchor,
                diagnosis,
                f"{next_step} {teaching_note}".strip(),
                close,
            ]
        if learner_signal == "blocked" or mode == "direct":
            return [
                anchor,
                f"{diagnosis} {next_step}".strip(),
                close,
            ]
        return [
            anchor,
            diagnosis,
            next_step,
            teaching_note,
            close,
        ]

    if scenario in {"review", "task", "next_task", "engineering_challenge"}:
        return [
            anchor,
            f"{diagnosis} {next_step}".strip(),
            teaching_note,
            close,
        ]
    if scenario in {"principle", "plan", "concept_teaching"}:
        return [
            anchor,
            diagnosis,
            f"{next_step} {teaching_note}".strip(),
            close,
        ]
    if learner_signal == "blocked" or mode == "direct":
        return [
            anchor,
            f"{diagnosis} {next_step}".strip(),
            close,
        ]
    return [
        anchor,
        diagnosis,
        next_step,
        teaching_note,
        close,
    ]


def _scaffold_anchor(
    *,
    scenario: str,
    goal: str,
    file_path: str | None,
    current_focus: str,
    chinese: bool,
) -> str:
    scenario_text = coaching_scenario_label(scenario)
    localized_focus = _surface_context_text(current_focus, chinese=chinese)
    if chinese:
        anchor = "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棗鏆欏┑鈥炽偢閺屽秷顧侀柛鎾存皑閹广垽宕煎┑鎰婵犵數濮甸懝楣冨础閹惰姤鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú鐔奉潖閾忓湱纾兼俊顖氭惈琚濋梻浣告啞閹歌鐣濋幖浣哥畺闁汇垻顭堢猾宥夋煕椤愩倕鏆遍柟閿嬫そ濮婅櫣娑甸崨顓濇睏闂佺顑嗙粙鎺撶┍婵犲啰闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛濠傜秺瀹曟垿濡疯閸嬫挸鈻撻崹顔界仌濡炪倖娉﹂崶褏鍙€婵犮垼鍩栭崝鏇綖閸涘瓨鐓熸俊顖氬悑閺嗏晠鏌℃径濠冨暈濞ｅ洤锕幃娆擃敂閸曘劌浜鹃柡宥庡亝閺嗘粌鈹戦悩鎻掝仾濠殿垰銈搁弻锛勪沪鐠囨彃濮庨梺鍛婂灩婵數鎹㈠☉銏犲耿婵☆垵顕ч棄宥夋⒑閹惰姤鏁遍柛銊ユ贡濡叉劙骞樼€涙ê顎撻梺鍏肩ゴ閸撴繈宕圭憴鍕洸闁归棿绶￠弫鍌炴煕椤愩倕鏋旈柛姗€浜堕弻鐔兼嚌閻楀牆娑х紓浣圭叀缁犳牕顕ｉ幎绛嬫晢闁稿本顨呮禍鐐箾閸繄浠㈤柡瀣⊕閵囧嫰顢橀悩鎻掑箣濡ょ姷鍋涢崯瀛樻叏閳ь剟鏌曢崼婵囧櫣缂佹劖绋掔换婵嬫偨闂堟刀銏ゆ倵濮樼厧鏋﹂柛濠冩尦濮婂宕掑顑藉亾妞嬪海鐭嗗〒姘ｅ亾妤犵偛顦甸弫鎾绘偐閼碱剦鍞堕梻浣虹《閸撴繄绮欓幋婵愬晠婵犻潧娲㈡禍婊堟煛閸愩劌鈧骞楅崒鐐寸厱闁绘棃鏀遍崳鐣岀磼鏉堛劍宕岀€规洘甯掗～婵嬵敄閽樺澹曢梺褰掓？缁€浣哄閻熼偊娓婚悗锝庝簻椤掋垹鈹戦姘ュ仮闁哄矉绱曟禒锔炬嫚閹绘帒顫撶紓浣哄亾閸庢娊鈥﹂悜钘夎摕闁绘梻鍘х粈鍫㈡喐韫囨洘鏆滄繛鎴欏灪閻撶喖鏌熼幆褏鎽犵紒鈧崼銉︾厓鐟滄粓宕滃▎鎾冲偍婵犲﹤鐗嗙壕濠氭煙閸撗呭笡闁绘挸鍟伴幉绋款煥閸繄顦梺缁樻椤ユ捇寮抽敃鍌涚厵閺夊牓绠栧顕€鏌涙繝鍕幋闁哄矉缍侀獮瀣倶濞茶绨肩紒鍌氱Т铻栭柛娑卞枓閹锋椽姊洪崨濠勭畵閻庢凹鍘奸蹇撯攽鐎ｎ偆鍘遍梺缁樏鍫曀夐悙鐢电＜闁稿本姘ㄥ瓭濡炪値鍘归崝鎴濈暦婵傚憡鍋勯柛婵嗗缁犮儵姊婚崒娆戠獢闁逞屽墯缁嬫挾绮婇柨瀣闁告侗鍠楃粈鈧梺瀹狀嚙缁夌懓鐣烽妸褉鍋撳☉娆樼劷闁告ɑ鎹囬幃宄邦煥閸曨厾鐓夐悗瑙勬礃缁矂锝炲┑瀣垫晞闁绘劕鐡ㄩ妵婵嬫煙椤斿搫鐏紒楦垮Г瀵板嫭绻濋崘鎯ф偑闂傚倸鍊风粈渚€骞夐敍鍕煓闁硅揪闄勯弲婵嬫煏婢跺棙娅呯痪鎯ф健閺岋綁寮崹顔藉€梺缁樻尭缁绘劙鍩為幋锔藉€烽柤纰卞厸閾忓酣姊洪崨濠冪厽闁稿﹥绻堝濠氭晲婢跺娅滄繝銏ｆ硾閻ジ寮抽鈶╂斀妞ゆ梻銆嬫Λ姘箾閸滃啰鎮兼俊鍙夊姍楠炴帡骞婂畷鍥ф灈闁圭绻濇俊鍫曞川椤撶喕绶㈤梻鍌氬€搁崐椋庣矆娓氣偓楠炲鏁撻悩鍐叉疄婵°倧绲介崰姘跺极閸曨偒鐔嗛柤鎼佹涧婵洨绱掗悩宕囧⒌闁哄苯绉规俊鐑芥晜閻ｅ奔绱樻繝纰樺墲瑜板啴鎮ф繝鍥х疄闁靛鍎欓弮鍫濈劦妞ゆ巻鍋撻摶鐐寸箾閹存瑥鐏╅柤绋跨秺閺岋綁濮€閻樺啿鏆堥梺缁樻尵閸犳牠寮婚敐鍛傜喖鎮℃惔鈥愁瀱婵＄偑鍊曠换鎺撶箾閳ь剟鏌＄仦鍓р姇闁诡垱鏌ㄩ埥澶娢熷畡棰佸濠电娀娼ч敃銉╂晬閸岀偞鈷掑ù锝堟鐢盯鏌涢弮鈧ú鐔笺€佸棰濇晣闁绘ê鍚€缁楀淇婇妶蹇曞埌闁哥噥鍨堕幃锟犲即閻旇櫣顔曢梺鐟扮摠缁诲倿鎳滅憴鍕垫闁绘劖鎯屽▓鏇㈡煏閸パ冾伃濠碉紕鍏橀弫鎰板川椤栨瑧绀勯梻鍌欑閹碱偅寰勯崶顒€鐒垫い鎺嗗亾缁剧虎鍙冨鎶藉幢濞戞瑥鈧敻鏌ㄥ┑鍡涱€楀褎澹嗛幃顕€鏁冮崒娑掓嫽婵炶揪绲块悺鏃堝吹閸愵喗鐓曢柣妯挎珪瀹曞瞼鈧娲栫紞濠囧箰婵犲啫绶炴俊顖滃劋椤撳潡姊绘担绋款棌闁稿鎳庣叅闁哄稁鍋嗘稉宥夋煥濠靛棭妲归柣鎾寸洴閺屾稓浠﹂幆褎鎯涙繛瀵稿У鐢帡鈥︾捄銊﹀枂闁告洦鍓涢ˇ銉╂⒑鐎圭媭娼愰柛銊ョ埣閻涱喗绻濋崶銊у幈婵犵數濮撮崯顖滅矆鐎ｎ兘鍋撶憴鍕闁搞劌鐖奸妴渚€寮撮姀鈩冩珖闂侀€炲苯澧寸€规洖缍婂畷鎺戔槈濮樿京妲囬梻鍌氬€搁悧濠冪瑹濡ゅ懎纾块柟鎵閻撶喖鏌熼幆褍鏆遍柡鍡秮閺岋紕浠﹂崜褉妲堥梺瀹狀潐閸ㄥ灝鐣烽崡鐐嶆梹绻濇担鐑橈紡闂傚倸鍊风欢姘焽閼姐倕绶ら柦妯侯檧閼板潡寮堕崼姘珕妞ゎ偅娲熼弻鐔兼倻濮楀棙鐣烽梺绋款儐閸ㄥ墎鎹㈠☉銏犲耿婵°倕鍟伴澶嬬節閵忥絾纭鹃悗姘嵆瀵鏁愭径濠勵啋闁诲酣娼ч幉锟犲闯娴煎瓨鈷戦柛婵嗗閻忛亶鏌涢悩铏磳鐎规洜澧楃换婵嬪炊瑜忛、鍛存⒑缂佹ê濮岄悘蹇旂懇椤㈡瑩骞囬婵堢畾闂侀潧鐗嗗ú銈呮毄闂備胶顭堥鍥磻閵堝违闁告劦鍠栭獮銏′繆椤栨氨姣為柡鈧搹顐ょ瘈闁汇垽娼у瓭闂佺顑呭Λ妤呭Υ閹烘挾绡€婵﹩鍘鹃崢浠嬫⒑閸︻厼浜惧┑鐐诧躬椤㈡挸螖娴ｅ吀绨诲銈嗗姂閸ㄦ椽骞栭幇鐗堢厓閻熸瑥瀚悘瀛樸亜閵忥紕鎳呮繛鎴犳暬閺屻劎鈧綆鍋呭В搴♀攽閻樻鏆滅紒杈ㄦ礋瀹曟垿鎮╅崣鍌涚洴瀹曠喖顢欓崣銉х秿闂傚倸鍊风粈渚€骞夐敓鐘茬闁硅揪绠戠粈澶婎熆鐠哄ソ锟犳晲婢跺﹪鍞堕梺鍐茬亪閺呮稒绂嶆ィ鍐╁仭婵炲棗绻愰顏嗙磼閳ь剟鍩€椤掆偓閳规垿鎮欓懠顒佸嬀闂佸憡姊归崹鎸庝繆鐎涙鐟归柍褜鍓欓悾鐑藉Ω瑜夐崑鎾斥槈濞呰鲸宀搁獮蹇曠磼濡偐顔曢柡澶婄墕婢т粙宕氭导瀛樼厵閻犲泧鍛槇閻庤娲﹂崹鍫曞箖濞嗘垟鍋撻棃娑欐喐妞ゆ梹娲熼弻锝夋偐閸欏宸堕梺鍛婁緱閸ㄥ崬鈻撴總鍛婄厽閹兼番鍊ゅ鎰箾閹绘帞绠荤€规洝顫夌粋鎺斺偓锝庝簽椤斿洦绻濋悽闈浶㈤柛鐕佸亞濞嗐垽鎮欓悜妯煎幈闂佹枼鏅涢崰姘舵倿閽樺鐟邦煥閸曨厼鈷屽┑顔硷功缁垶骞忛崨鏉戜紶闁靛鐏濋妸銉㈡斀闁宠棄妫楁禍婊勭箾绾绡€妤犵偛鍟撮幃娆撴倻濡粯鐝栭梻浣侯焾閺堫剙顫濋妸鈺佸偍闂侇剙绉甸埛鎴︽煕閿旇骞栭柛鏂款儔閺屾盯濡堕崱鏇氬闂侀潧娲﹂崝娆撶嵁閹烘绠婚悗娑欘焽瑜版悂姊婚崒娆戭槮闁规祴鍓濈粭鐔肺旈崨顓犵崶濠德板€曢幊搴ｅ閸ф鐓欓柛鎾楀懎绗￠梺鎶芥敱閸ㄥ潡寮诲☉妯锋婵鐗婇弫鎯ь渻閵堝啫鍔滈柣妤佺矌濡叉劙骞掑Δ浣镐汗闂佹儳娴氶崑鍕閹惰姤鍊垫繛鍫濈仢閺嬫稒銇勯鐘插幋鐎殿噮鍋婇獮妯肩磼濡桨姹楅梻浣告贡缁垳鏁悙鐑樺仒闁冲搫鍊风换鍡涙煟閹板吀绨婚柍褜鍓氬ú婊堝箲閵忋倕绠涢柡澶庢硶閻ゅ洭妫呴銏″缂佸甯″畷鎴︽偄閸涘﹤寮垮┑鈽嗗灠閻忔繈鎮￠幇鐗堢厱濠电姴瀚弳顒勬煙椤旂厧妲婚柍璇叉唉缁犳盯骞欓崘褏妫紓鍌氬€风拋鏌ュ磻閹剧粯鐓曢柟鑸妽濞呭洨绱掗埦鈧崑鎾绘⒒娓氣偓濞佳呮崲閸℃あ锝夊川鐎涙ê鈧灝螖閿濆懎鏆為柣鎾跺枛閻擃偊宕堕妸锕€纰嶉梺鍝勬４缁查箖骞堥妸锔剧瘈闁告劏鏂傛禒銏ゆ倵鐟欏嫭纾搁柛鏂跨Ф閹广垹鈹戦崶銊ヮ€撻梺鎯х箰濠€閬嶆偩閹惰姤鈷掗柛灞剧懅椤︼箓鏌熼懞銉х煁闁逛究鍔戦幃浠嬪川婵犲倷缃曟繝寰锋澘鈧洟宕导瀛樺剹濠㈣泛澶囬崑鎾荤嵁閸喖濮庡銈忕細缁瑥顕ｉ銏╁悑濠㈣泛顑囬崢浠嬫⒑瑜版帒浜伴柛鐘崇濡垽姊绘担鍝ョШ闁衡偓閸楃儐娓婚柦妯侯樈濞兼牗绻涘顔荤盎闁圭鍩栭妵鍕箻濡も偓閹冲孩鎱ㄩ崗鑲╃瘈闁汇垽娼ф禒锕傛煙閸涘﹤鈻曢挊鐔兼煙閹规劖纭鹃柛銊︾箓閳规垿鎮╃€圭姴顥濈紓浣哄Х缁垳鎹㈠☉銏℃櫜閹肩补鈧啿绠扮紓鍌欓檷閸斿矂鈥﹀畡閭︽綎婵炲樊浜滅粻浼村箹濞ｎ剙鐏柛娆忔濮婅櫣鎷犻懠顒傤唹缂備浇顕ч崐鍧楀箖妤ｅ啯鍋ㄧ紒瀣仢閼板灝鈹戦悙鏉戠仸闁荤啙鍥у偍闂傚牊渚楀〒濠氭煏閸繃顥炵紒鈧埀顒€鈹戦埥鍡椾簼缂佸鎸搁锝堫樄闁糕斁鍋撳銈嗗笒鐎氼參宕愰悽鍛婂仭婵炲棗绻愰顏嗙磼閳ь剟宕橀钘変缓濡炪倖鐗楃粙鎴澝归鈧弻娑㈠煛閸愩劋妲愰悗瑙勬礃閿曘垽銆佸▎鎾村殐闁冲搫鍟В搴ㄦ⒑閼姐倕鏋戠紒顔肩焸瀵敻顢楅崒婊冨触闂佺粯姊婚崢褔宕￠幎鑺ョ厽闁归偊鍓涙牎濠碘槅鍋勯崯鎾嵁閸愵喖鐓涢柛娑卞櫘濡啫鈹戦悙鏉戠仸妞ゃ劌鐗撻獮鎴﹀即閵忊檧鎷绘繛杈剧悼閻℃棃宕靛▎鎴犵＜缂備焦锚閻忊晠鏌熼獮鍨伈鐎规洜鍘ч埞鎴﹀醇閻斿壊鍟庡┑鐘垫暩婵炩偓婵炰匠鍏炬盯顢橀悜鍡欏姺闂佸啿鎼崐鑸电濠婂牊鐓欓柟顖嗗苯娈剁紓浣哄У椤洨妲愰幒妤佸亹閻庡湱濮撮ˉ婵嗩渻閵堝簼绨婚柛鐔风摠娣囧﹪宕奸弴鐐茶€垮┑掳鍊愰崑鎾舵偘閼测晝纾介柛灞剧懅閸斿秶鎲搁弶鍨殭妞ゎ厼娲弫鎾绘偐闂堟稓銈﹀┑鐘垫暩婵潙煤閵堝鍊峰┑鐘插暔娴滄粓鏌熼崫鍕ラ柛蹇撶焸閺屾稑顫滈埀顒€顭囪閳ユ棃宕橀鍢壯囨煕閳╁喚鐒芥い锔哄劚閳规垿鍩ラ崱妞剧凹缂備礁顑嗛幐鎼侇敋閿濆牜妯勯梺绯曟杹閸嬫挸顪冮妶鍡楃瑨閻庢凹鍙冮崺娑㈠箣閻樼數锛滃銈嗙墬缁嬫帞绮堥崘顔界厸濠㈣泛锕︾粔娲煛鐏炲墽銆掗柍褜鍓ㄧ紞鍡涘磻閸涱垯鐒婃い鎾跺枂娴滄粍銇勮箛鎾愁仼闁哄棴绲介埞鎴﹀灳瀹曞洤鐓熼悗瑙勬礀瀹曨剝鐏冮梺鍛婂姦娴滄繈宕抽鐐粹拻濞达絿鐡旈崵娆撴倵濞戞帗娅婄€规洘鐟ㄩ妵鎰板箳閹寸姷鍘梻浣告啞閸旓箓宕伴弽顓炲強闁靛濡囩粻楣冩煙鐎涙鎳冮柣蹇婃櫇缁辨帡鎮崨顖溞滈梺鍝勮閸旀垵顕ｉ鈧畷鎺戔槈濞嗘垵娑ч梻鍌欑閹诧繝鏁嬮悗瑙勬处閸撶喖宕洪悙鍝勭闁挎棁妫勯埀顒傚厴閺屸剝寰勭€ｎ亞浠兼繛瀵稿У閹倿寮婚妶鍥ㄥ晳闁靛牆鎳夐崑鎾诲即閵忕姷鍘撮梺纭呮彧鐎靛矂寮繝鍥ㄧ厱闊洦娲栫敮鑸点亜閿旇娅婃慨濠冩そ濡啫鈽夊▎鎰€烽梺璇插閸戝綊宕瑰畷鍥у灊閻犲洦绁村Σ鍫ユ煏韫囨洖啸妞ゆ梹甯￠弻锝夋偐閼姐倗绐楅梺闈涙閸嬫捇姊洪悷鏉挎缂佺粯绻傞～蹇曠磼濡顎撻梺鍏间航閸庮垶鍩€椤掆偓閸熸壆妲愰幒妤€鐒垫い鎺嶇劍婵挳鎮跺☉鎺嗗亾閸忓懎顥氭繝娈垮枟閿曗晠宕戦崟顐ゆ殼闁糕剝鐟㈤崑鎾斥枔閸喗鐏曞銈嗘肠閸パ呭弨婵犮垼娉涜癌闁绘柨鍚嬮悡銉╂倵閿濆懐浠涚紓宥呰嫰閳规垿鎮╁▓鎸庢瘜濠碘剝褰冮幊妯虹暦鐟欏嫬顕遍柡澶嬪灱琚濋梺璇插嚱缂嶅棝宕伴弽顐や笉闁绘柨鐨濋弨浠嬫煕鐏炲墽顣查柛鐔哄仱閺屽秹鏌ㄧ€ｎ亞浠肩紓浣介哺鐢偤鍩€椤掑﹦绉甸柛瀣浮瀹曟洟濡烽埡鍌滃幈闁瑰吋鐣崹濠氬煡婢舵劖顥嗗璺侯儑缁♀偓婵犵數濮撮崐濠氬礄瑜版帗鈷戞い鎾楀啰浠梺閫炲苯澧い鏃€鐗犲畷鏉库槈閵忊晜鏅悷婊勬瀹曟椽濡烽敃鈧欢鐐烘煙闁箑澧绘繛鐓庯躬濮婅櫣绱掑Ο鏇熷灱閵囨劙宕橀鍡欑劸濡炪倖娲嶉崑鎾存叏婵犲嫮甯涚紒妤冨枛閸┾偓妞ゆ巻鍋撴い顓炴穿椤﹀綊鏌嶉妷顖滅暤鐎规洖銈告俊鐑藉Ψ瑜濈槐鐢告⒒娴ｇ懓鍔ゆ繛瀛樺哺瀹曟垿宕卞☉鏍ゅ亾閸涘瓨鍊婚柤鎭掑劤閸樻捇姊洪崨濠勭畵閻庢凹鍙冨畷鎶藉捶椤撶姷锛?"
        if goal:
            anchor += ""
        if localized_focus:
            anchor += ""
        elif current_focus:
            anchor += "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳婀遍埀顒傛嚀鐎氼參宕崇壕瀣ㄤ汗闁圭儤鍨归崐鐐烘偡濠婂啰绠荤€殿喗濞婇弫鍐磼濞戞艾骞楅梻渚€娼х换鍫ュ春閸曨垱鍊块柛鎾楀懐锛滈梺褰掑亰閸欏骸鈻撳鍫熺厸鐎光偓閳ь剟宕伴弽顓炶摕闁搞儺鍓氶弲婵嬫煃瑜滈崜鐔奉嚕缁嬪簱妲堥柕蹇ョ磿閸橀亶姊洪棃娑辩叚濠碘€虫川缁鎮欓幖顓燁啍闂佺粯鍔曢顓熸櫠椤忓牊鍤曢柟閭﹀幑娴滄粓鏌熼崫鍕棞濞存粓绠栧铏规嫚閸欏顩版繛瀛樼矋缁诲嫰骞戦姀鐘闁靛繒濮寸粣娑橆渻閵堝棛澧い鏇熸尦閺佹劙宕ラ崘鏌ュ弰鐎规洘鍎奸¨鍌炴椤掑澧柍瑙勫灴閸ㄦ儳鐣烽崶褏鍘介柣搴ゎ潐濞插繘宕濋幋锔衡偓浣糕枎閹惧磭顦х紒鐐緲瑜板宕Δ鍐＝闁稿本鑹鹃埀顒佹倐瀹曟劙鎮滈懞銉ユ畱闂佽偐顭堥悘姘跺矗韫囨稒鐓欓柟顖滃椤ュ鐥娑樹壕闂傚倷娴囬～澶愬磿閻撳宫娑㈠礋椤栨稑鐝旈梺缁樻煥閹芥粎绮绘ィ鍐╃厵閻庣數顭堥埀顒佸灥椤繈顢栭埡瀣М鐎规洖銈搁幃銏㈢矙閸喕绱熷┑鐘茬棄閺夊簱鍋撻幇鏉跨；闁瑰墽绮悡鐔镐繆閵堝倸浜鹃梺鎸庢处娴滄粓顢氶敐澶樻晝闁挎洍鍋撶紒鐘虫皑閹插憡寰勯幇顒傚摋婵炲濮撮鍡涙偂閻斿吋鐓欓梺顓ㄧ畱婢ь喚绱掗悪娆忔处閻撴洟鏌ㄥ┑鍡欏妞ゃ儱顦甸弻宥囨喆閸曨偆浼岄梺璇″枟閻熲晠宕洪埄鍐╁鐎瑰嫰鍋婂Λ婊堟⒒閸屾艾鈧悂宕愭搴ｇ焼濞撴埃鍋撴鐐寸墵椤㈡洟鏁傞挊澶婂濠电姰鍨煎▔娑㈡嚐椤栨粍顐介柕鍫濐槹閻撴洖鈹戦悩鎻掝仼闁哄鏌ㄩ湁婵犲﹤妫楄缂備胶绮换鍫ュ箖娴犲顥堟繛鎴烆殘閹规洘绻濈喊妯活潑闁稿鎳橀幃鐑藉煛娴ｇ儤娈鹃梺鍝勬储閸ㄥ湱绮堥崘鈺冪闁哄鍩堥崕鎰版煟韫囧海顦︽い顏勫暣婵″爼宕卞Ο楦挎暱闂備焦鎮堕崝宥咁渻娴犲绠栭柨鐔哄У閸嬪嫰鏌ｉ幘铏崳妞ゆ梹鍔曢埞鎴︽倻閸モ晝校闂佸憡鎸婚悷鈺呭箖濮椻偓瀹曪繝鎮滈崱娆忔暩闂佽崵鍠愰悷銉﹀垔閸洖绠ｉ柨鏇楀亾濡楀懘姊洪崨濠冨闁搞劑浜跺鎻掝煥閸喓鍘介梺閫涘嵆濞佳勬櫠椤栨稒鍙忛柨婵嗘噽婢э箓鏌熼绛嬫當闁崇粯鎹囧畷褰掝敊閻ｅ奔绮氬┑锛勫亼閸婃牕鈻旈敃鍌氱倞闁肩鐏氬▍宥呪攽閻樼粯娑ч柛濠傤煼閳ワ箓宕奸妷锔惧帒闂佹悶鍎崝濠冪濠婂牊鐓欓柡澶婄仢椤ｅ磭绱掓径灞炬毈闁哄苯绉烽¨渚€鏌涢幘瀵告噧閻撱倖銇勯幘璺哄壉婵炲吋鐗滅槐鎾存媴閼测剝鍨堕崚濠囧箻椤旂晫鍘卞┑鐐村灦閿曨偄顔忛妷鈺傜厸闁糕剝顨堟晶锔芥叏婵犲啯銇濈€规洜鍏橀、妯款槾闁告梻顭堥—鍐Χ鎼粹€崇闂佺绻戦敃銏ゆ偘椤曗偓瀹曞崬鈽夊Ο纰辨Ч婵＄偑鍊栭悧顓犲緤妤ｅ啫鐤炬い鎺戝閳锋垹绱撴担濮戭亝鎱ㄥ鍡欑濞达絽鍟块幊鎰版儗閸儲鐓ラ柡鍥╁仜閳ь剙缍婅棢濠电姴鍟ㄦ禍婊堟煙閹佃櫕娅呴柣蹇ｄ簻椤法鎹勯崫鍕典紑缂備浇椴哥敮鐐哄焵椤掑﹦绉甸柛瀣闇夋い鏃堟暜閸嬫挾鎲撮崟顒傤槰闂佹悶鍔屽锟犳偘椤曗偓瀹曞爼顢楁担闀愮綍闂備礁澹婇崑鍛崲閳ь剟鏌涢弽銊у⒌婵﹦绮幏鍛喆閸曨偂鍝楅梻浣侯焾鐎涒晝鍒掗幘宕囨殾婵せ鍋撻柛鈹惧墲缁绘繈宕橀悙顒婄礄闂傚倸鍊搁崐鎼佸磹妞嬪孩顐芥慨姗嗗墻閻掔晫鎲搁幋鐐存珷婵犻潧顑嗛埛鎴︽煕濠靛棗顏柛锝堟缁辨帡顢欓懞銉ョ３濡ょ姷鍋涢崯鏉戭瀶鏉堚晝纾奸柣妯虹－濞插瓨顨ラ悙瀵告噰鐎规洘锕㈤、鏃堝礋椤掍焦鐦庨梻鍌氬€峰ù鍥х暦閸偅鍙忛柡澶嬪殮濞差亝鍋愰悹鍥皺閸旓箑顪冮妶鍡楀潑闁稿鎸鹃惀顏嗙磼閵忕姴绠虹紓浣稿€圭敮锟犲春閿熺姴宸濇い鏃€鍎抽獮妤呮⒑閻熸澘鎮戦柣锝庝邯瀹曠銇愰幒鎴濇優濡炪倖甯掔€氼參鎮￠弴鐔虹闁糕剝顨堢粻浼存煛閸☆厾绉柡灞炬礋瀹曢亶寮撮悪鈧Σ顔碱渻閵堝骸浜濈紒顔芥崌瀹曟椽鍩€椤掍降浜滈柟鐑樺灥椤忊晝绱掗悩铏凡闁宠鍨块幃鈺呭箵閹烘挻顔勭紓鍌欑婢у酣宕戦妶澶婅摕婵炴垯鍨归悞娲煕韫囧﹥娅嗛柛銊ョ仢椤曪綁宕奸弴鐐殿啇婵炶揪绲介崢婊堝箯缂佹绠鹃弶鍫濆⒔缁夘剚绻涢崪鍐偧闁轰緡鍠栭埥澶愬閿涘嫬骞堥梻浣告惈閸熺娀宕戦幘缁樼叆闁哄洦锚閻忊晠鏌ｉ敐鍛Щ閻撱倖銇勮箛鎾愁仼闁哥偑鍔岄—鍐Χ閸℃浠撮悷婊勫閸嬫稒鏅ュ┑掳鍊曢幊蹇涘磻閳╁啰绡€濠电姴鍊搁弳鐔虹磼閻樼儤鐝ǎ鍥э躬瀹曪絾寰勬繝鍌ゆ綒婵°倗濮烽崑鐐垫暜閹烘洜浜欏┑鐐舵彧缁蹭粙骞夐敓鐙€鏁囩紓浣姑肩换鍡涙煟閹板吀绨婚柍褜鍓氶悧婊堝极椤旂晫绡€闁搞儯鍔岄埀顒€娼￠弻銊╁即閻愭祴鍋撹ぐ鎺戠；闁绘梹鎮舵禍婊堢叓閸ャ劍灏靛褎鐩弻宥夋煥鐎ｎ亞浼岄梺鍝勭焿缂嶄線骞冮姀銏㈢煓婵炲棛鍋撻ˉ瀣⒒娴ｉ涓茬紓宥呮瀹曪綁宕橀鑹版憰濠电偞鍨崹瑙勫劔闂備線娼ч悧鍡椕洪妸鈺傚亗闁瑰墽绮埛鎴犵磽娴ｅ鑲╂闁秵鐓曢柨婵嗙箳缁夘噣鏌ｅ☉鍗炴珝妤犵偞甯￠獮濠囨惞椤愶綆妫冮梺绯曟杹閸嬫挸顪冮妶鍡楃瑨闁稿﹦绮粙澶婎吋婢跺鍙嗗┑鐘绘涧濡厼危瑜版帗鐓熼柟鎯ь嚟濞叉挳鏌＄仦鍓ф创妤犵偛娲畷婊勬媴缁嬭法鍘掓繝鐢靛仜閻°劎鍒掗幘鍓佷笉闁哄诞灞剧稁闂佹儳绻楅～澶屸偓姘哺閺屻倗鍠婇崡鐐差潾濡炪倖鎹佸▍锝囨閹惧瓨濯撮柦妯侯槺閸橆偊姊洪悡搴ｇШ缂佺姵鐗犻弫鎰版倷閸撲胶鏉稿┑鐐村灦閻燂箓宕曢鍫熺厽闁绘柨鎽滈幊鍐倵濮樼厧澧寸€规洏鍨奸妵鎰板箳閹绢垱瀚奸梻浣告啞缁嬫垿鏁冮敐鍥偨闂侇剙绉甸悡鏇㈡煟濡櫣锛嶅褜浜弻宥夋寠婢舵ɑ歇濡炪倧绠戦顓犳閹烘挻缍囬柕濠忕畱闂夊秹姊洪悷鏉挎Щ闁硅櫕锚閻ｇ兘顢曢敃鈧粈瀣煙閹碱厼鐏ｇ紒澶樺櫍閺岋紕浠﹂崜褎鍒涙繝纰樺墲閹倹淇婇悿顖ｆШ闂佹儳绻愰柊锝咁潖閻戞ê顕辨繛鍡樺灦閸嬔囨⒑缁嬭法绠查柨鏇樺灩椤曪綁顢曢敃鈧粻娑㈡煛婢跺﹦浠㈤柤鏉跨仢閳规垿鎮欓崣澶樻！闂佹悶鍔庨幊鎾冲祫闂佹悶鍎洪崜姘跺煕閹烘嚚褰掓晲閸涱喖鏆堥梺鍝ュ枔閸嬨倝寮诲☉銏犳闁绘劕寮堕崳鐣岀棯閹规劕袚闁逛究鍔岃灒閻犳亽鍔庣紙杈ㄧ節濞堝灝鏋涢柛鐔锋健閸╃偤骞嬮敂钘変汗閻庤娲栧ù鍌炲汲閿熺姵鈷戦柟鎯板Г閺侀亶鏌涢妸銉﹀仴鐎殿喛顕ч埥澶娢熼柨瀣澑闂備胶纭堕崜婵嬨€冭箛鏂款嚤闁逞屽墴閺岋綁鎮欓弶鎴濇瘓婵炲瓨绮犳禍婊堬綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕导鏉戠煑闁糕剝绋掗埛鎺懨归敐鍥剁劸缂併劏宕电槐鎾愁吋閸曨厾鐛㈤梺缁樹緱閸ｏ絽鐣烽崡鐐嶆棃宕橀埡鍌滄殾闂傚倷绶氶埀顒傚仜閼活垱鏅堕幘顔界厱闁宠鍎虫禍鐐繆閻愵亜鈧牜鏁幒妤佹櫇闁挎柨澧介惌鎾绘煟閵忕姵鍟為柣鎾存礋閺岀喖骞嗚閸ょ喖鏌曢崱妯虹瑨妞ゎ叀娉曢幉鎾礋椤掑偆妲扮紓鍌欐祰濡椼劎鍒掑▎蹇曟殾闁靛濡囩弧鈧梺鍛婃处閸嬪嫭淇婇崶銊х瘈闁汇垽娼у暩闂佽桨绀侀幉锟犲箞閵娧€鍋撻棃娑欏暈鐎规洘鐓￠弻鐔煎箯鐏炵晫鍔烽梺閫炲苯澧柟铏耿閵嗕礁螖閸涱厾顦板銈嗗笒閸婃悂鐛Δ浣风箚闁绘劦浜滈埀顒佺墵楠炴劖銈ｉ崘銊х崶闁硅偐琛ラ崺妤勩亹閹烘繃鏅梺閫炲苯澧寸€殿喖顭烽崹鎯х暦閸ャ劍鐣烽梺璇插嚱缂嶅棝宕滃☉銏℃櫖闁绘柨鎽滅粻楣冩倵閻㈡鐒炬い搴㈡尵缁辨帡鎮╅搹顐㈢闂佷紮绲介崲鏌モ€﹂妸鈺佸耿闁冲搫鍊愰鍫熲拻濞达絽鎲￠崯鐐烘偨椤栨侗娈樼紒顔界懇楠炲鏁愰崶锔捐兒闂傚倸鍊烽懗鍓佸垝椤栫偞鏅濋柕蹇曞閻掔晫鎲告惔锝囩焿闁圭儤顨嗛弲婵嬫煕鐏炲墽銆掗柛娆忔閳规垿顢欑粵瀣姼闂佺硶鏅滈悧鐘诲箖閿熺姵鍋勯柛蹇氬亹閸欏棗鈹戦悩缁樻锭婵☆偅鐟╅獮鏍箛閻楀牏鍘卞┑鈽嗗灟鐠€锕傚吹閻斿吋鐓冪憸婊堝礈濠靛缍栧璺衡姇濞差亜鍐€妞ゆ挾鍠庢禍顖炴⒑缂佹ɑ灏繛瀵稿厴瀵娊鏁冮崒娑掓嫼濡炪倖宸婚崑鎾剁磼婢跺鍤熺紒顔款嚙閳藉鈻庡鍕泿闂備胶鎳撻幖顐⑽涘Δ浣侯洸闁绘劦鍓涚弧鈧┑鐐茬墕閻忔繈寮搁弮鍫熺厱闁靛鍔岄崥瑙勪繆閸欏濮嶆鐐搭焽閳ь剚绋掗敋妞ゅ孩鎸荤换娑氣偓鐢殿焾瀛濆銈嗗灥閹虫﹢鐛Δ鍛仺闁告稑锕﹂崢浠嬫⒑闂堟稓绠氶柡鍛洴閹﹢鏁愭径瀣幈闁诲函缍嗛崜娆撳几鎼淬劌纭€闂侇剙绉甸悡娆撴煟濡も偓閻楀﹦娆㈤懠顒傜＜闁绘ê鍟块埢鏇㈡煛瀹€鈧崰鏍х暦濮椻偓閹崇娀顢楁繝鍕槸闂傚倷绀侀幗婊勬叏閻㈠憡鍋嬮柣妯垮吹瀹撲線鏌涢幇闈涙灈闁绘帗妞介弻娑㈠箛閵婏附鐝旈梺鍛婃煥閹冲酣鍩為幋锕€鐓￠柛鈩冾殘娴犳潙顪冮妶鍡樿偁闁搞儴鍩栭弲婊冾渻閵堝棛澧遍柛瀣仱閸╂盯骞掗幊銊ョ秺閺佹劙宕堕埡鍌涘晵闂備焦鎮堕崐鏍偡閳哄懎绠栨俊銈傚亾闁宠棄顦甸獮鎺楀箻鐎电缍冨┑锛勫亼閸婃垿宕瑰ú顏呭仭闁宠桨绶￠崵鏇灻归悩宸剾闁轰礁娲弻锝夊箛椤旇姤姣勯悗瑙勬礀閻栫厧顫忕紒妯诲闁告稑锕ラ崕鎾剁磽娴ｅ壊鍎庣紒鑸佃壘閻ｇ兘濮€閿涘嫷娴勯柣搴秵娴滅偤鏁嶅☉娆戠瘈闁靛骏绲剧涵楣冩嚌瀹€鍕厸闁逞屽墯缁傛帞鈧綆鍋嗛崢閬嶆煟韫囨洖浠滃褌绮欓幆宀勫Χ婢跺鍘介梺鍦劋椤ㄥ牓鎮惧ú顏呯厸閻忕偛澧藉ú鏉戔攽閳╁啯鍊愬┑锛勫厴婵＄兘濮€閻樺崬顥氭繝娈垮枟缁诲倿鎯夐崗鑲╊洸婵炲棙鎸婚埛鎺懨归敐鍥ㄥ殌妞ゆ洘绮庣槐鎺旀嫚閹绘巻鍋撻崸妤冨祦濠电姴鍟崕鐔兼煏婵炲灝鍔滈弶鍫濈墕閳规垿鎮欓崣澶樻！闂佹悶鍔屽﹢杈ㄧ珶閺囩喓闄勯柛娑橈功閸樿棄鈹戦埥鍡楃仴婵炲拑绲剧粋鎺戔槈閵忥紕鍘搁梺绯曟閺呮稒鏅堕幘顔界厸閻忕偟纭堕崑鎾崇暦閸ャ劍鐣烽梻渚€鈧偛鑻晶瀵糕偓瑙勬磻閸楀啿顕ｆ禒瀣垫晣闁绘劗鏁搁弳顐ｇ節閻㈤潧孝闁挎洏鍊濆畷銉ヮ潨閳ь剟骞冮姀銈呯闁绘挸绨堕崑鎾寸節濮橆厾鍘撻梺鍛婄箓鐎氼剟鍩€椤掍焦鍊愭い銏℃楠炴牗鎷呴崗澶嬪闂備胶鍘ч～鏇㈠磹閺囩喓顩烽柨鏂垮⒔濡垶鏌℃径搴㈢《閺佸牓姊虹拠鈥虫灓闁稿繑锕㈠畷娲焺閸愵亞鎳濋梺鎼炲劘閸斿海绮欐担绯曟斀闁绘ê鐏氶弳鈺佲攽椤旂偓鏆柟铏箞瀹曟粏顦叉い銉﹀哺閺屾稖绠涘顑挎睏缂備胶濞€缁犳牠寮诲☉銏犵労闁稿繒濯禍顏堝箖閻愮儤鍊锋い鎴ｆ硶缁犳岸鎮楅悷鏉款棌闁哥姵鐗曢埢宥咁吋閸℃ê寮挎繝鐢靛Т閹冲繘顢旈悩宕囩闁瑰濮甸弳顒傗偓瑙勬处娴滄繈骞忛崨鏉戝窛濠电姴瀚鎾剁磽閸屾艾鈧悂宕愰悜鑺ュ殑闁告挷绀侀崹婵囥亜閺嶃劎鐭嬬€规洘鐓￠弻娑㈩敃閻樻彃濮㈤悗瑙勬尫缁舵岸寮诲☉銏犵疀闂傚牊绋掗悘宥夋⒑缁嬪尅宸ユい顓犲厴瀵鏁冮埀顒冪亽闂佺粯鑹鹃顓犵矆閸℃稒鈷戦梻鍫熶腹濞戙垹绀嬫い鎰剁悼閳ь剟绠栧缁樼節鎼粹€茬盎濠电偠顕滄俊鍥╁垝濞嗘挸绠虫俊銈傚亾缁剧偓瀵ф穱濠囧Χ閸涱喖娅ら梺缁樻尰閻熲晠寮婚悢鐑樺枂闁告洦鍋勯～宀勬⒑缂佹ɑ灏伴柛鏃€鐟╁璇测槈閵忊€充汗闂佸憡鍔栬ぐ鍐綖閹烘鈷戦柛婵嗗閻掕法绱掗幓鎺嗗亾閻旇桨绨烽梻鍌欑窔閳ь剛鍋涢懟顖涙櫠閹绢喗鐓欐い鏂诲妼濞层倝鐛姀锛勭闁糕剝锚閻忋儳鈧娲忛崕鍙夌┍婵犲洤围闊洦娲栭崺宀勬⒑閸濄儱娅忛柛銊ョ埣楠炲啴鏁撻悩鑼槰濡炪倕绻愰幊搴ㄥ几閹存績鏀介柣妯款嚋瀹搞儵鏌ｅΔ鈧Λ娑氬垝閸儱閱囬柣鏃囨椤旀洟姊虹化鏇炲⒉閽冮亶鎮樿箛锝呭箻缂佽鲸甯￠幃鈺呮濞磋缍侀弻鐔哥瑹閸喖顬堝銈庝簻閸熶即骞忛悩鑽ゅ彄妞ゆ挾鍎愬Λ婊堟⒒閸屾艾鈧娆㈠顒夌劷鐟滃秷鐏嬮梺鍝勫暙閸婂鎯岄崱妞尖偓鎺戭潩閿濆懍澹曢梻浣瑰缁诲嫰宕戝☉鈶┾偓锕傚Ω閳轰線鍞跺┑鐘绘涧閻楀棙鎱ㄩ敂鎴掔箚闁绘劦浜滈埀顒佺墱閺侇喗绻濋崶銊モ偓鍧楁煥閺囩偛鈧悂鎯屽Δ鍛彄闁搞儯鍔庨埊鏇㈡煟閹惧啿鏆熼柟鑼焾椤劑宕煎┑鍫Ф闂備胶绮濠氬储瑜旈幏鎴︽偄閸忚偐鍘繝鐢靛仜閻忔繈宕濆Δ浣风箚闁圭粯甯炴晶娑樓庨崶褝韬い銏＄☉閳诲酣骞掑┑鍡椢ゆ繝鐢靛仜椤曨厽鎱ㄩ幘顔嘉ч柟闂寸缁犳牗淇婇妶鍌氫壕闂佸磭绮幑鍥х暦瑜版帩鏁婇柣锝呭缁ㄤ粙姊婚崒娆戭槮闁硅绻濋妴鍐川閺夋垹鏌堥梺绉嗗嫷娈ｇ紓宥嗙墵閻擃偊宕堕妸锔绢槶缂佺偓鍎抽崥瀣┍婵犲浂鏁嶆繝鍨姇濞堫厼顪冮妶鍛劉闁规瓕宕甸幑銏犫槈閵忕姷顔掗梺鍝勵槹閸ㄩ潧袙閸儲鈷戦柟鑲╁仜婵倸霉濠婂棙纭炬い鏇秮椤㈡洟鏁傜紒妯绘珫婵犳鍠楅敋闁告艾顑囬埀顒勬涧閻倸顫忓ú顏咁棃婵炴垶鑹鹃。鐑樹繆閵堝洤孝闁硅绱曠划瀣吋閸滀胶鍙嗛梺鍛婃磵閺呮瑧鑺辨繝姘拺闁圭瀛╃粈鈧梺绋匡功閹虫捇鍩ユ径搴▌闂佸搫鐭夌紞渚€寮幇鏉垮窛妞ゆ挾鍟橀埡鍛拺閻庡湱濯鎰版煕閵娿儳浠㈤柣锝夋敱鐎靛ジ骞栭鐔告珦闂備礁鍚嬫禍浠嬪磿閸濆嫀娑㈠礃椤旇棄鈧敻鎮峰▎蹇擃仾缁剧偓鎮傞弻娑㈠籍閳ь剟宕归崸妤€违濞达絿纭堕弸搴ㄦ煙閸撗喫夐柟宄邦煼閺岋絾鎯旈妸锔介敪闂佺濮ょ划宀勫煝閺冨牆閿ゆ俊銈勮閹峰姊虹粙鎸庢拱闁煎綊绠栭崺鈧い鎺戝濡垹绱掗鑲╁缂佹鍠栭崺鈧い鎺戝瀹撲礁顭块懜闈涘闁哄拋鍓熼弻娑㈠即閵娿儱绠婚梺缁樻尰閹瑰洤顫忛搹瑙勫厹闁告侗鍠栧☉褔姊婚崒姘仼閻庢碍婢橀悾鐑藉箣閿曗偓鍥存繝銏ｆ硾椤戝洭宕㈤鍛瘈闁汇垽娼ф禒褔鏌涚€ｎ偅灏柍璇茬Ч瀹曞崬鈽夊▎鎴濆箞闂佽鍑界紞鍡樼濠婂牆鐒垫い鎺嗗亾婵炲皷鈧剚鍤曞┑鐘宠壘閸楁娊鏌ｉ弮鍫缂佹劗鍋涢埞鎴︽倷閺夋垹浠搁梺鎸庢磵閺呮稓鍙呭銈嗘尵婵澹曢挊澹濆綊鏁愰崨顔藉創闂佸疇顕ч悧蹇曟閹烘鍋愮€规洖娲ら埛宀勬倵濞堝灝鏋涙い顓犲厴楠炲啴濮€閵忊€充粧闂佺偨鍎遍崢鏍ㄧ珶閺囥垺鈷戞慨鐟版搐閻忊晠鏌熷ù瀣у亾閺傘儲鐎哄┑鐘诧工閹虫劗澹曟總绋跨骇闁割偒鍋勬禍婵嬫煟濠垫劒閭柡灞炬礋瀹曟儼顦叉い蹇ｅ墰缁辨帡鎮╁畷鍥ㄥ垱濡ょ姷鍋為…鍥箲閸曨剛鐟规い鏍ㄧ⊕椤旀棃姊婚崒姘偓椋庢濮樿泛鐒垫い鎺戝€告禒婊堟煠濞茶鐏￠柡鍛埣椤㈡岸鍩€椤掑嫬钃熸繛鎴欏灪閸嬪棗霉閿濆娅滈柛鐘诧躬濮婅櫣鍖栭弴鐔告緭闂佹悶鍔嶅浠嬬嵁閸℃稑绫嶉柛顐ｆ儕閳哄懏鐓忓璇″灠閼活垶骞冮崼銉︹拻闁稿本鐟ㄩ崗宀€绱掗鍛仸闁炽儻绠撳畷鍫曨敄闁款垰浜鹃柛宀€鍎愰弫濠囨煟閹伴潧澧绘繛鑲╁枛濮婃椽宕ㄦ繝鍕櫑濡炪倧绠掓禍顒€顕ｈ閸┾偓妞ゆ帒瀚崐鐢告煕韫囨洦鐒剧€规挸妫濋弻锟犲焵椤掑嫬纭€闁绘垵妫涢崬闈涒攽椤斿浠滈柛瀣崌閺屾盯鍩為幆褌澹曞┑锛勫亼閸婃牜鏁繝鍕焼濞达綀顫夐崣蹇曗偓骞垮劚濞茬娀宕戦幘鑸靛枂闁告洦鍓涢ˇ銊╂⒑閹肩偛濡兼繛纭风節閹即顢欓崲澶屽枛瀹曘劑妫冨☉銏犲及濡炪們鍨洪悧婊堝箲閸曨垰惟鐟滃酣寮查妸鈺傗拻闁稿本鑹鹃埀顒傚厴閹偤鏁傞柨顖氫壕缂佹绋戦崢鎯洪鍕敤濡炪倖鎸鹃崑鐔兼晬濞嗘挻鈷戠紓浣姑悘杈ㄤ繆椤愩垹顏紒顔碱煼閹垽宕楅懖鈺佸箺闂備線鈧稑宓嗘繛浣冲嫭娅犵紓浣诡焽缁犻箖鏌涢锝囩煂闁活厽鐟╅弻鈥崇暆鐎ｎ剛袦濡ょ姷鍋涘ú顓€佸Δ浣瑰闁告瑥顦辨禍鐐测攽閻樻鏆俊鎻掓嚇瀹曞綊顢旈崼婵堬紱闂佺懓澧界划顖炲煕閹烘嚚褰掓晲閸モ晜鎲橀梺鎼炲€曢崯鎾蓟濞戙垺鍋嗗ù锝夋櫜閸犲﹪鎮楃憴鍕闁稿骸銈歌棟鐟滅増甯楅悡鏇㈡煟閹邦垰鐨洪柛鈺嬬稻閹便劍绻濋崨顕呬哗缂備浇椴哥敮鎺曠亽闂佺厧顫曢崐鏇烆嚕閾忣偂绻嗛柣鎰典簻閳ь剚鍨垮畷婵嗙暆閸曨剛鍘愰梺鎸庣箓椤︻垶寮伴妷鈺傜厓鐟滄粓宕滃璺何﹂柛鏇ㄥ灠缁犲磭鈧箍鍎卞ú銈嗕繆娴犲鐓熼煫鍥ㄦ尵缁犲弶绻濋姀鈽嗙劸鐟滈绶氬娲箹閻愭彃濡ч悗骞垮劚閻楀棝骞嗛崼銉︹拻濞达絿鐡旈崵鍐煕閻樻剚娈滈柟顔惧厴婵＄兘鍩℃繝鍐╂珦闂傚鍋勫ú锔界瑹濡ゅ懎鏋佸┑鐘叉处閻撶喖鏌熼悙顒€鈻曟い搴㈩殕閵囧嫰濡烽妷顬勬叏婵犲嫮甯涢柟宄版噽缁數鈧綆浜濋鍕攽鎺抽崐妤佹叏閻㈢绠栭柛宀€鍋涚粻鏍ㄤ繆椤栨瑨顒熸繛灏栨櫊瀵爼宕煎☉妯侯瀴濠电偛鐗婂姗€鍩為幋鐐茬疇闂佺锕ュú鐔风暦椤栫偞鍋愰悹鍥皺閿涙盯姊洪悷鏉库挃缂侇噮鍨惰棢闁割偆鍠撶粻楣冩煙鐎电浠у褜浜滈湁闁绘瑢鍋撻柛锝忕秮楠炲啫螖閸愨晛鏋傞梺鍛婃处閸撴盯藝閵夆晜鈷戠紓浣诡焽婢ь亪鏌涘顒夊剱缂佸矁椴哥换婵嬪磼閵堝棙銆冮柣搴″帨閸嬫挸鈹戦悩鎻掓暘妞ゆ帊妞掔换鍡涙煟閹板吀绨婚柍褜鍓氶悧鏇綖韫囨稒鍋￠柟鍐诧攻濡炰粙骞冮姀锛勯檮濠㈣泛顑囩粙浣圭節閻㈤潧浠滄俊顖氾攻缁傚秴鈹戠€ｎ亞锛涢梺璺ㄥ枔婵敻鍩涢幋鐐簻闁规儳宕俊鍧楁煟閿濆牓鍝虹紒缁樼洴瀹曠厧鈹戦崼婵堝幗婵犳鍠栭敃銊モ枍閿濆洤鍨濇繛鍡楃箚閺嬪酣鏌熼鍡楀暙椤ユ劙姊婚崒娆掑厡妞ゎ厼鐗撻、鏍炊椤掆偓缁愭鏌熼柇锕€鏋ら柣顓烆槺閳ь剙绠嶉崕閬嵥囬婊呬笉闁荤喕鍩囬埀顒佸笒椤繈顢楁担鍓叉П闂備礁鎼幏鎴犵礊娴ｅ壊娼栨繛宸簼椤ュ牊绻涢幋娆忕伄鐎规洦浜炵槐鎾存媴娴犲鎽靛┑鐐跺皺閸犲酣鎮鹃悜鑺ユ櫜濠㈣泛锕ら懓鍨攽閻愭潙鐏﹂柣鐔村灲楠炲繐煤椤忓應鎷洪梺鍛婄☉閿曪妇绮婚幘缁樺€垫慨妯煎帶楠炴鈧灚婢樼€氭澘鐣烽悢纰辨晬婵炴垶鑹惧铏節濞堝灝鏋熸い顓炵墦瀹曟椽寮介鐔蜂簵闂佸搫娲㈤崹娲偂濞戙垺鐓曢柟鏉垮閸掓澘霉濠婂啫鈷旂紒杈ㄥ浮閹瑩顢楁担鍝勫殥缂傚倷绀侀ˇ鎶斤綖婢跺鈹嶅┑鐘叉处閸嬨劎绱掔€ｎ厽纭舵い锔芥緲椤啴濡堕崱娆忣棄缂備焦鐓＄粻鏍ь嚕閺屻儲鏅插璺侯儌閹疯櫣绱撻崒娆戝妽闁挎艾鈹戦鑲╁缂佺粯鐩畷妤呮嚃閳哄倸娅氶柣搴㈩問閸犳骞冮崒鐐茬畺闁冲搫鍟扮壕鍏间繆椤栫偞鏁遍悗姘偢濮婃椽鎳￠妶鍛呫垺绻涢懠顒€鈻堥柛鈹惧亾濡炪倖甯掗崯顖炴偟椤忓牊鐓熼煫鍥ㄦ尰椤ョ姷绱掓潏銊﹀鞍缂佹鍠栧畷鎯邦槼闁诲繐绉瑰娲嚒閵堝懏鐎梺绋挎捣閺佸鐛崘顔肩畾鐟滃繘寮崇€ｎ喗鐓欓梺鍨儐閳锋劖淇婇銏犳殭闁伙絿鍏樻俊鎼佸煛婵犲啯娅嶆繝鐢靛█濞佳囨偋韫囨稑纾归柣鎰劋閳锋帡鏌涚仦鍓ф噮缂佹劖姊圭换娑欐媴閸愬弶纭介柛銉墻閺佸洭鏌曡箛鏇炐ラ柨娑氬枛濮婄粯绗熼崶褍顫╃紓浣割槹閹告娊骞冮敓鐘插嵆闁靛骏绱曢崢鎼佹⒑閹肩偛鍔橀柛搴ㄤ憾閹﹢顢旈崼鐔哄帗闂備礁鐏濋鍛箔閹烘顥嗗鑸靛姈閻撱儲绻濋棃娑欘棡闁革絾妞介弻娑㈡偄閸濆嫪妲愰梺鍝勭灱閸犳牠銆佸☉姗嗘僵闁告鍎愰弶鎼佹⒒娓氣偓濞佳兠洪妶鍥ｅ亾濮橆偄宓嗙€殿噮鍋婂畷鎺戭煥閸曨偆褰撮梻浣藉亹閳峰牓宕楀☉姗嗘禆闁瑰墽绮埛鎺懨归敐鍥╂憘闁搞倕鍟撮弻娑㈡偆娴ｉ晲鍠婇悗瑙勬礃閸庡ジ藝鐎涙ǜ浜滈柨鏃囧Г缁跺弶銇勯鍕殻濠碘€崇埣瀹曞崬鈻庤箛锝嗘濠电姵顔栭崰妤勫綘闂佸憡姊归崹鐓幬涢悢濂夋富闁靛牆妫欑壕鐢告煕鐎ｎ偅宕岄柡灞糕偓宕囨殕閻庯綆鍓涜ⅲ缂傚倷鑳舵慨鐢告儎椤栨凹鍤曢柟缁㈠枟閸婄兘鏌ｅΔ鈧悧鍡樺垔娴煎瓨鈷掗柛灞剧懆閸忓本銇勯鐐靛ⅱ闁逞屽墯缁嬪牓寮插鍛床婵炴垶鐟х弧鈧梺绋挎湰缁秴鈻撻幆褉鏀介柣妯肩帛濞懷勩亜閹存繃鍣介柣姘劤椤撳吋寰勭€ｎ剙骞堟俊鐐€栭崝鎴﹀磹閺囥垹姹查梺顒€绉甸悡娆戔偓鐟板閸嬪﹪鎮￠崗鍏煎弿濠电姴鎳忛鐘电磼椤旂晫鎳囨鐐村姈閹棃濮€閳ユ剚浼嗛梻鍌氬€峰ù鍥х暦閻㈢闂柨鏃€鍨濈换鍡涙煕閵夈垺娅呴柛銊︾箓閳规垿鎮╅幓鎺撴濡炪倖娲熸禍鍫曞箖濡も偓閳藉鈻庡Ο鐓庡Ш闂備礁鎲￠敃銏＄閸洖钃熼柨婵嗘閸庣喐銇勯弽銊х煂閺嶏繝姊绘担渚劸妞ゆ垵鎳愰埀顒佸嚬閸欏啴鐛崼銉ノ╅柕澶樺枛閹垿姊洪幖鐐插姷缂佽尪濮ょ粋宥嗐偅閸愨晛浠┑鐐叉缁绘劙顢旈鍡欐／闁绘劦鍓氶崐鎰版煛鐏炲墽娲村┑鈩冩倐婵＄兘鏁愰崨顒€鍨濋梻浣藉Г钃辩紒璇茬墦瀵鈽夐姀鈩冩珕闁荤姴娲﹁ぐ鍐不娴煎瓨鈷戠紒瀣儥閸庢劙鏌熼幖浣虹暫妤犵偛顦甸獮姗€顢欓懖鈺婃Ч婵＄偑鍊栧濠氬磻閹炬番浜滈柨鏃囶潐濞呭﹥鎱ㄦ繝鍐┿仢妤犵偞鐗犻幃娆撳箵閹烘繄鈧娊姊绘担铏瑰笡闁绘娲熸俊鍫曞川婵犱胶绠氶柣搴㈢⊕椤洭鎮疯ぐ鎺撶厓鐟滄粓宕滃▎鎿冩晪闁挎繂顦粻缁樸亜閺冨倵鎷℃繛鐓庯躬濮婅櫣绱掑鍫ｂ偓鎸庣箾娴ｅ啿娲ㄥ畵渚€鏌涢銈呮灁缂佲檧鍋撴繝鐢靛仜閻楀棝鎮樺┑瀣嚑闁绘柨鍚嬮悡銉╂煛閸ヮ煈娈曟繛鍛功閳ь剝顫夊ú蹇涘垂閾忓湱鐭夐柟鐑樻煛閸嬫捇鏁愭惔妯轰壕妞ゆ挶鍔戝顔剧磼缂佹绠炴俊顐㈠暙閳藉顫濋澶嬫闂傚倷鑳堕…鍫ヮ敄閸℃稑绠板Δ锝呭暙缁犵喖鏌熺紒銏犳灈缂佲偓鐎ｎ偁浜滈柟鐑樺灥娴滅偞淇婇懠璺虹厫濞ｅ洤锕幃娆擃敂閸曘劌浜鹃柕鍫濐槸閸屻劌鈹戦崒姘暈闁稿顑夐弻鐔煎箥椤旂⒈鏆梺绋匡工閻栧ジ寮诲☉銏犵疀闂傚牊绋掗悘宥夋⒑閹惰姤鏁遍柛銊ョ仢椤繐煤椤忓秵鏅濋梺闈涚墕閹冲秶鍒掗崼鏇熲拺闁稿繐鍚嬮妵鐔兼煕閵娾晙鎲剧€殿喗鐓″畷濂稿即閻愭鍚嬫俊鐐€栭弻銊︽櫠娴犲鏅繝濠傜墛閻撴稑顭跨捄鐚村姛濠⒀勫灴閺屾盯寮懗顖氼伃闂傚洤顦伴妵鍕即濡も偓娴滈箖姊洪崫鍕拱闁烩晩鍨跺畷娲晬閸曘劌浜鹃柨婵嗛婢т即鏌ｉ敃鈧悧鎾诲箖濡ゅ啯鍠嗛柛鏇ㄥ墰閿涙﹢姊洪崨濠冣拹闁搞劌娼℃俊瀛樻媴缁洘鐎婚梺瑙勫劤绾绢參鎮炬ィ鍐╁仭婵犲﹤鍟拌倴缂備緡鍠栭…閿嬩繆閻戣棄唯闁靛繆鍓濋弶鎼佹⒒娴ｇ懓顕滅紒瀣灩閳ь剚鍑归崜姘辩矉瀹ュ棛闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛鐔哄閺呭爼鎮介崨濠勫幍濡炪倖鏌ｉ崝灞矫洪妶澶婄闁规儼濮ら悡鐔兼煙闁箑澧伴弽锟犳⒑閻戔晜娅撻柛銊ゅ嵆椤㈡岸鏁愭径妯绘櫌闂侀€炲苯澧撮柛鈹垮灪閹棃濡搁敃鈧埀顒勬敱閵囧嫰骞掗崱妞惧闂備椒绱梽鍕垝閹炬剚娼栫紓浣股戞刊鎾煕濞戞﹫榫氱痪顓涘亾闂傚倷鑳堕…鍫㈣姳濞差亜纾规繝闈涙閺嗭箓姊婚崼鐔剁繁婵炲皷鏅犻弻锝夊箛椤撶偟浜板┑顔款潐椤ㄥ﹤顫忓ú顏勬嵍妞ゆ挾鍋涙俊娲⒑閻熺増鍟為柟顔煎€垮畷娲焵椤掍降浜滈柟鍝勬娴滄儳顪冮妶搴″箻闁稿繑锚椤曪絾绻濆顑┭冾熆鐠虹尨鍔熼柣锝嗗▕濮婃椽宕烽鐐插闂佹悶鍔岄悘姘跺箞閵婏箑绶為柟閭﹀幐閹?"
        elif file_path:
            anchor += f"闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欑粣娑㈡⒑閸濄儱校闁圭澧介崚鎺旂磼濡浜濋梺鍛婂姀閺呮繈宕㈡禒瀣拺闂侇偅绋戝畵鍡樼箾娴ｅ啿瀚▍鐘炽亜閺嶎偄浠﹂柣鎾跺枑缁绘繈妫冨☉娆忣槱缂備讲鍋撻悗锝庡亝閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濮风槐鎺楊敊閻ｅ本鍣ч梺瀹狀嚙闁帮綁鐛崱姘兼Щ婵犮垼顫夐敋闁宠鍨块幃娆撴嚑椤掍焦鍠栫紓鍌欑贰閸犳碍鎱ㄩ悽鐢电焿鐎广儱顦介弫鍌炴煕閺囥垺娑ф繛鍫涘姂閺岋綁鎮╅崣澶婎槱缂備椒鐒﹀娆忓祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔告倐濮婃椽宕ㄦ繝鍐ｆ嫻闂佸湱顭堥崯鍧楋綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愬宀婃澓濠电姷鏁搁崑娑㈡偤閵娧冨灊鐎广儱顦伴崑瀣煛閸モ晛浠滅紒渚囧亰濮婄粯鎷呯粙娆炬闂佺顑勭欢姘暦瑜版帗鍤掗柕鍫濇媼濡粓姊洪懞銉冾亪藟閵忥絻浜归柟鐑樻尰濞呮粓姊虹化鏇炲⒉妞ゃ劌鐗忕划濠囨煥鐎ｎ剛顔曢柣搴㈢⊕椤洭鎯岄幒鏃傜＜闁绘ê纾晶顏呫亜椤愩垻绠婚柟鐓庣秺瀹曠兘顢橀悩闈涘箚闂備浇宕垫慨鍨娴犲绀夐幖娣灩椤曢亶鏌涢妷顔煎闁抽攱鍨圭槐鎺斺偓锝庡亽閸庛儵鏌涙惔銏犵伌闁哄本绋撻埀顒婄祷閸斿矂鍩€椤掍胶绠為柣娑卞櫍瀹曟﹢顢欓懞銉︻仧闂備胶绮摫鐟滄澘鍟悾鐢稿幢濞戞瑢鎷虹紓鍌欑劍钃遍柍閿嬪笧缁辨帞绱掑Ο鑲╃暭闂佸ジ缂氭ご鍝ユ崲濠靛棭娼╂い鎾寸⊕鐎氬ジ姊洪懡銈呮瀾闁荤喆鍎抽埀顒佸嚬閸樻儳鈻庨姀銈呯闁圭儤绻勯崬鐢告偡濠婂啰效闁哄苯锕弫鎰緞鐏炵晫銈﹂梻浣告啞閸旓箓宕板Δ鍛惞闁告劦鍠楅悡鍐煕濠靛棗顏╅柡鍡欏枛閺屻劌鈽夊▎鎴犵厜濠殿喖锕ㄥ▍锝囨閹烘嚦鐔荤疀閿濆嫮鏁栨繝銏ｎ潐濞茬喖銆佸鈧幃銏ゅ川婵犲嫬濞囬梻浣告惈椤︻垶鎮ч崘顔肩柧婵犻潧鐗嗛ˉ姘攽閸屾粠鐒剧紒鐙欏洦鐓曟い鎰剁悼閳藉鈹戦檱閸嬫劗妲愰幒鎴富闁挎洍鍋撻柟铏姉婢规洘绺界粙璺ㄩ獓闂佸壊鍋呯粙鎴炰繆閸忚偐绠鹃柟纰卞幖閺嬫盯鏌嶇憴鍕伌妞ゃ垺鐟╅幃閿嬶紣娴ｅ壊妫滈梻鍌氬€搁崐鐑芥嚄閸撲礁鍨濇い鏍仦閺咁亪姊绘担鍛婂暈闁糕晛鍟村畷鎴﹀箻缂佹ǚ鎷洪梺鍛婄☉閿曪附鏅堕鍕厽婵°倓鑳堕惌灞句繆?`{file_path}` 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏咁棃婵炴番鍎遍悧鎾愁嚕閹绘巻妲堥柕蹇曞Х椤㈠懘姊洪幆褎绂嬮柛瀣€婚幑銏ゅ幢濞戞瑧鍘梺鍓插亝缁诲倿鍩€椤掆偓閹诧紕绮嬪澶嬪€锋い鎺戝€婚鏇㈡煟鎼淬垻鈯曟い顓炴喘閹瞼鈧綆鍠楅悡鏇㈠箹濞ｎ剙鐏╅柍缁樻礋閺屽秹濡烽敂绛嬫閻庤娲橀敃銏ゃ€佸▎鎾冲簥濠㈣鍨板ú銈囩不閸︻厾纾兼い鏃傚帶鐢劑鏌涚€ｎ偅灏柣锝囧厴瀹曞墎鎹勯悜妯荤彎婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柟闂寸绾剧粯绻涢幋鐑嗙劯闁绘柨鎽滅弧鈧梺鎼炲劀閸涱垰骞€闂傚倷绀侀幉锟犲礉閿曞倸绐楅柡宥庡墰缁犺姤绻濋悽闈涗哗闁规椿浜炲濠勬崉閵婏箑鍘归柣鐘烘〃缂嶅秹鏁愭径濠囧敹闂侀潧顧€婵″洭宕㈤鍫燁棅妞ゆ劑鍨洪幖鎰版嚌瀹€鍕厱閻庯綆鍋呭畷宀€鈧鍣崜鐔镐繆閻戣棄唯闁靛牆鎷嬪Λ婊堟⒒閸屾瑨鍏岀紒顕呭灦瀹曞綊宕楅崗鐓庡伎闂侀潧鐗嗛ˇ顖滃瑜版帗鐓熼柕蹇曞У閸熺偤鏌ｉ幘璺烘灈闁哄本娲濈粻娑欑節閸愮偓缍夐梻浣告憸閸犲海鎹㈠鈧濠氭晲婢跺﹦顔婇梺鐟扮摠缁洪箖骞愰崘顔解拺闂侇偆鍋涢懟顖涙櫠椤栨稏浜滈柡鍐ｅ亾闁绘濮撮悾閿嬪閺夋垵宓嗛梺闈涚箳婵兘銆侀崨瀛樷拺闁告稑锕ゆ慨鍥ㄤ繆椤栨熬宸ユい顓炴喘瀵粙顢曢妶鍥风闯濠电偠鎻紞鈧柛瀣€块獮瀣倷閹绘帞浜栭梻浣告惈椤︿即宕归鐐茬劦妞ゆ帊绀佺粭鎺撱亜椤愶絿绠為柟顔瑰墲閹棃鏁愰崟顓熸毎闂傚倸鍊峰ù鍥ь浖閵娧勵偨闁跨喓濮撮崹鍌毭归懖鈺勊夐柍褜鍓氬Λ鍐ㄧ暦濮椻偓椤㈡瑩宕叉竟顖氭搐缁犲湱绱掗鐓庡辅闁稿鎹囬幊鐘活敆閸屾稒娅掑┑鐘殿暜缁辨洟宕戦幋锕€纾圭憸蹇曞垝婵犳艾绠婚柟棰佽兌閸旂兘鎮峰鍕棃妤犵偛鍟撮獮鍡氼槾闁哄棗顑夐弻鐔告媴閸愨晝褰ч梺鍝勫€甸崑鎾绘⒒閸屾瑧顦﹂柟鑺ョ矋閸掑﹪顢橀姀鐘电崶濠德板€愰崑鎾绘懚閻愮儤鐓曢柟鎵虫櫅婵″潡鏌￠崱顓犵暤闁哄本娲樼换娑㈡倷椤掍胶褰熼梻浣芥〃缁€渚€鏁冮鍕垫綎濠电姵鑹剧壕鍏兼叏濡厧甯舵繛鍫濈埣濮婃椽鎮滈埡鍌涚彅闂備礁搴滅徊浠嬶綖韫囨梻绡€婵﹩鍓涢敍婊冣攽閻愬弶顥為柛鈺佺墕鍗辨い鏇楀亾婵﹨娅ｅ☉鐢稿椽娴ｅ憡鐤傜紓鍌欐祰妞寸煤濠婂牆绀嗛柟鐑樺灍閺嬪酣鏌熼幆褏锛嶆い鎾存そ濮婃椽骞愭惔銏╂⒖濠碘槅鍋勭€氼厾绮嬮幒妤佺劶鐎广儱妫岄幏娲⒒閸屾氨澧涢柛妤佹礋瀹曞ジ濡烽妷褎鐓ｆ繝鐢靛Т閿曘倝鎮ч崱娆忣棜濠电姵纰嶉悡鏇㈡倶閻愭彃鈷旈柕鍡樺笧缁辨帡鎮╅懡銈囨毇闂佸搫鏈惄顖炲春閸曨垰绀傞柍鍝勫€搁悘鈺伱瑰鍐╁暈閻庝絻鍋愰埀顒佺⊕椤洭宕㈡禒瀣拺閻熸瑥瀚崝銈嗐亜閺囥劌寮鐐诧躬瀹曠喖顢涘☉姘妇闂備焦鎮堕崕婊堝礃閸欍儳纾惧┑掳鍊楁慨鐑藉磻閻愯　鈧箓宕堕鈧粻鏌ユ煕閺囥劌鐏￠柛濠勭帛娣囧﹪顢涘杈ㄧ檨闂佺顑嗛幑鍥箠閿熺姴围闁搞儮鏅槐鍐测攽閻愯埖褰х紓宥佸亾濡炪倖娲橀悧鏇㈠煝閹捐鍗抽柕蹇娾偓鍏呯紦婵＄偑鍊栭悧妤冪矙閹存緷褰掝敋閳ь剟寮诲☉銏犵厸闁告劑鍔嬪Σ鎰旈悩闈涗粶妞ゆ垵顦靛顐﹀磼濠婂懐锛滃┑鈽嗗灣缁垶鎮甸敃鍌涒拻闁稿本鐟︾粊鎵偓瑙勬礈閺佽鐣锋导鏉戝唨妞ゆ挻澹曢崑鎾诲磼閻愬瓨娅嗛梺浼欑到閻壈銇愭ィ鍐┾拺闁告繂瀚婵嗏攽椤曗偓椤ユ挻绔熼弴鐔侯浄閻庯綆鍋嗛崢閬嶆煟韫囨洖浠︾€规洘蓱缁旂喎顫滈埀顒勫蓟瀹ュ牜妾ㄩ梺鍛婃尰瀹€鎼佺嵁閸愵喖纾兼慨妯块哺濞堥箖姊虹憴鍕棆濠⒀勵殜瀹曟劖绻濆顓犲幘闂佽鍘界敮鎺楀礉濮橆厾绠鹃柛顐ゅ枎閻忓瓨鎱ㄦ繝鍐┿仢鐎规洏鍔嶇换婵嬪礃閵娧呭彎缂傚倸鍊风拋鏌ュ磻閹剧偨鈧帒顫濋敐鍛闁诲氦顫夊ú婊堝箠閹捐鐓橀柟杈剧畱閻愬﹪鏌曟径鍫濃偓妤呮儎鎼淬劍鈷掑ù锝呮啞閹牏绱掔€ｂ晝绐旂€规洘鍨垮畷鐔碱敆閸屻倖绁梻浣瑰濞叉牠宕愯ぐ鎺撳亗婵炴垯鍨洪悡鏇熺箾閹存繂鑸归柡瀣ㄥ€楃槐鎺楁偐闂堟稐妲愰梺鍝勭焿缁辨洘绂掗敃鍌涘€锋い鎺戝亞濡查绱撻崒娆掑厡濠殿喚鏁哥划娆撳箳閺冣偓瀹曞弶绻涢幋娆忕仼缂佺姵姘ㄩ幉鍝ヤ沪閸撗呭骄闂佸搫娲㈤崹娲煕閹达附鐓犳繛鏉戭儐閺夊綊鏌熼崙銈囩瘈闁哄本鐩獮妯尖偓闈涙啞閸掓盯姊?"
        else:
            anchor += "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欑粣娑㈡⒑閸濄儱校闁圭澧介崚鎺旂磼濡浜濋梺鍛婂姀閺呮繈宕㈡禒瀣拺闂侇偅绋戝畵鍡樼箾娴ｅ啿瀚▍鐘炽亜閺嶎偄浠﹂柣鎾跺枑缁绘繈妫冨☉娆忣槱缂備讲鍋撻悗锝庡亝閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濮风槐鎺楊敊閻ｅ本鍣ч梺瀹狀嚙闁帮綁鐛崱姘兼Щ婵犮垼顫夐敋闁宠鍨块幃娆撴嚑椤掍焦鍠栫紓鍌欑贰閸犳碍鎱ㄩ悽鐢电焿鐎广儱顦介弫鍌炴煕閺囥垺娑ф繛鍫涘姂閺岋綁鎮╅崣澶婎槱缂備椒鐒﹀娆忓祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔告倐濮婃椽宕ㄦ繝鍐ｆ嫻闂佸湱顭堥崯鍧楋綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愬宀婃澓濠电姷鏁搁崑娑㈡偤閵娧冨灊鐎广儱顦伴崑瀣煛閸モ晛浠滅紒渚囧亰濮婄粯鎷呯粙娆炬闂佺顑勭欢姘暦瑜版帗鍤掗柕鍫濇媼濡粓姊洪懞銉冾亪藟閵忥絻浜归柟鐑樻尰濞呮粓姊虹化鏇炲⒉妞ゃ劌鐗忕划濠囨煥鐎ｎ剛顔曢柣搴㈢⊕椤洭鎯岄幒鏃傜＜闁绘ê纾晶顏呫亜椤愩垻绠婚柟鐓庣秺瀹曠兘顢橀悩闈涘箚闂備浇宕垫慨鍨娴犲绀夐幖娣灩椤曢亶鏌涢妷顔煎闁抽攱鍨圭槐鎺斺偓锝庡亽閸庛儵鏌涙惔銏犵伌闁哄本绋撻埀顒婄祷閸斿矂鍩€椤掍胶绠為柣娑卞櫍瀹曟﹢顢欓懞銉︻仧闂備胶绮摫鐟滄澘鍟悾鐢稿幢濞戞瑢鎷虹紓鍌欑劍钃遍柍閿嬪笧缁辨帞绱掑Ο鑲╃暭闂佸ジ缂氭ご鍝ユ崲濠靛棭娼╂い鎾寸⊕鐎氬ジ姊洪懡銈呮瀾闁荤喆鍎抽埀顒佸嚬閸樻儳鈻庨姀銈呯闁圭儤绻勯崬鐢告偡濠婂啰效闁哄苯锕弫鎰緞鐏炵晫銈﹂梻浣告啞閸旓箓宕板Δ鍛惞闁告劦鍠楅悡鍐煕濠靛棗顏╅柡鍡欏枛閺屻劌鈽夊▎鎴犵厜濠殿喖锕ㄥ▍锝囨閹烘埈娼ㄩ柛鈩冪懃婵吋绻濋悽闈涗粶闁瑰啿绻愮叅婵犲﹤瀚々鏌ユ煙闂傚顦︾紒鐘劜閵囧嫰寮崹顔规寖闂佹寧绋掔划搴ｆ閹捐纾兼繛鍡樺灥婵¤棄顪冮妶搴″箹婵炲眰鍊楅崣鍛存煟鎼淬垻鈯曢柨鏇楁櫅閳绘挻绂掔€ｎ偆鍘介梺褰掑亰閸ㄥジ宕电€ｎ兘鍋撶憴鍕仩闁稿海鏁诲濠氭晲婢跺娅滈棅顐㈡处濞叉粓鎯侀崼銉﹀€垫繛鍫濈仢閺嬫盯鏌ｉ弽褋鍋㈤柣娑卞櫍楠炲洭顢橀悢宄板Τ闂備焦瀵х换鍌溾偓姘煎墴钘熸慨妯垮煐閳锋帡鏌涚仦鎹愬闁逞屽墰閸忔﹢骞婂Δ鍛濞达絿顭堥悘濠傤渻閵堝棛澧遍柛瀣洴閹锋垿鎮㈤崗鑲╁帾婵犵數鍋涢悘婵嬪礈缂佹绠鹃柟瀵稿€戝璺虹哗濞寸姴顑嗛崐鐢告煥濠靛棛鍑圭紒銊ょ矙閺岋綁鏁愰崱妯镐虎闂佽鍠栭崲鏌モ€﹂妸鈺佸窛妞ゆ挆鍕様闂備焦鐪归崺鍕垂鏉堚晜鏆滄俊銈呭暊閸嬫捇妫冨☉鏍т划闂佽鍠掗弲婵堟閹烘嚦鐔兼偂鎼达紕鐤勯梻鍌氬€风粈渚€骞栭鈷氭椽濮€閵堝懐顦柣蹇曞仧閸嬫挸鈻嶉悩鐐戒簻闁哄稁鍋勬禒锕傛煟閹惧瓨绀嬫鐐寸墪鑿愭い鎺嗗亾闁诲浚浜幃妯跨疀閿濆懎绠洪梺闈涙搐鐎氫即銆侀弮鍫濈妞ゆ劧绲鹃鎺戔攽閻樻鏆柍褜鍓欑壕顓㈠春閿濆洠鍋撶憴鍕８闁告梹鍨块妴浣糕枎閹寸姷锛滈梺闈涢獜缁辨洟宕愰悙鐑樷拻闁稿本鑹鹃埀顒傚厴閹虫宕奸弴妞诲亾閿曞倸閱囬柕澶樺枟閺呯偤姊洪崨濠勨槈闁宦板姂瀵彃鈹戦崶銉ょ盎闂婎偄娲﹂幐鎼侇敂閹绢喗鐓曢柕鍫濇缁€鈧梺瀹狀潐閸ㄥ潡骞冮埡浣烘殾闁搞儴鍩栧▓褰掓⒒娴ｄ警鐒炬い鎴濇噽閳ь剚鍑归崳锝夊箚閳ь剚銇勮箛鎾跺缂佺媭鍨抽埀顒€鍘滈崑鎾绘煕閺囥劌浜濋柟铏懇濮婄粯鎷呴崨濠冨創闂佺懓鍟块ˇ闈涱嚕閹绘巻鏀介柛顐ゅ櫏濞肩喖姊洪崷顓炲妺婵﹨宕垫竟鏇熺附閸涘﹦鍘棅顐㈡处濞叉牕鐡紓鍌欒兌婵挳鈥﹀畡閭︽綎婵炲樊浜滄导鐘绘煕閺囥劌鏋涙い蹇ｅ幖椤啴濡惰箛鏇犳殼濠电偘鍖犻崶銊ヤ患闂佺粯鍨煎Λ鍕暜闂備礁鍟块幖顐︽晝閵夆晛鐤炬繝闈涱儐閳锋垿鏌熺粙鍨劉妞ゃ儱妫涢幃顔尖枎閹惧鍘甸梻浣哥仢椤戝棝濡靛┑瀣厸鐎光偓鐎ｎ剛袦闂佽鍠掗弲鐘茬暦閿濆棗绶炵€光偓婵犲唭銊╂⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栨稒娅犳い鏂垮⒔濡垳绱撴担闈涚仼妤犵偞顨堢槐鎺楀磼濞戞ɑ璇為梺绯曟杹閸撴繈骞忛崨鏉戠煑濠㈣泛顑嗗鎴︽⒒閸屾瑨鍏岀紒顕呭灦瀹曟繈寮撮悜鍡楁闂佸壊鍋呭ú鏍偂濠靛鐓涢柛銉ｅ劚閻忣亪鏌ｉ幘瀛樼缂佺粯鐩畷鍗炍旈崘顏嶅敹闂備礁鎼Λ瀵哥礊娓氣偓瀵鏁愰崨顏咁潔闂佸憡顨堥崑鐐烘偟濠靛鍊甸悷娆忓缁€鍐煥閺囨ê鐏查柕鍡曠閳诲酣骞橀弶鎴炵暟闂備礁鐤囧銊х矆娴ｈ棄鈧挳姊婚崒姘偓鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偛顦甸弫鎾绘偐閼碱剦妲烽梻濠庡亜濞诧妇绮欓幋锔藉仾闁绘劦鍓涚粻楣冩煙鐎涙鎳冮柣蹇婃櫇缁辨帡鍩€椤掍礁绶為柟閭﹀幘閸樺崬鈹戦悙鏉戠仸妞ゎ厼娲獮妤呮偐缂佹鍘撻梻浣哥仢椤戝懘鎮橀幘顔界厵妞ゆ梻鐡斿▓婊呪偓瑙勬礈閸忔﹢銆佸鈧幃娆撳箛閸撲胶蓱闂侀潧娲ょ€氱増淇婇悜钘壩ㄦい鏂垮建瑜庣换娑㈡晲閸涱喗鎮欓梺鎸庢处娴滎亪濡存笟鈧鎾閳╁啯鐝抽梻浣规偠閸庮垶宕濈仦瑙ｆ瀺婵鍩栭埛鎺懨归敐鍥╂憘闁搞倕鍟撮弻娑㈡偐閹颁焦鐤侀梺闈涙閸燁垳鎹㈠┑瀣倞闁靛鍨规禍鎯с€掑锝呬壕閻庢鍠楅幐铏叏閳ь剟鏌嶉埡浣告殲闁绘繃娲熷娲嚒閵堝懏鐎鹃梺鑽ゅ枙娴滎剙顕ユ繝鍥х鐟滃宕戦幘鎰佹僵妞ゆ垶鍎虫禒顔尖攽椤旂》鍔熺紒顕呭灦楠炲繘宕ㄩ弶鎴濈獩婵犵數濮撮崐鐟扳枔濡偐纾介柛灞剧懄缁佺増銇勯弴鍡楁搐绾剧懓鈹戦悩瀹犲闁绘帒鐏氶妵鍕箳瀹ュ棛銈版繝銏ｎ潐閿曘垽寮诲☉銏狀潊闁炽儱纾粊鐑芥倵鐟欏嫭灏悗姘緲椤繐煤椤忓嫭宓嶅銈嗘尨閸撴繈顢撳Δ鍛拺闁告縿鍎辨牎濡炪們鍔岄敃顏堢嵁閸愵喖鐏抽柡鍌樺劜椤秹姊洪棃娑㈢崪缂佽鲸娲熷畷銏ゅ础閻愨晜鏂€闂佺粯鍔栧娆撴倶閵壯€鍋撶憴鍕闁告挾鍠庨锝夊箹娴ｈ倽褍顭跨捄渚剳闁告妫勯—鍐Χ閸℃ê鏆楅梺鍝ュТ妤犳悂婀佸銈嗘磵閸嬫捇鏌＄仦绯曞亾瀹曞洦娈曢梺閫炲苯澧寸€规洑鍗冲浠嬵敇濠ф儳浜惧ù锝囩《閺嬪酣鏌熼幆褏锛嶉柣锝夌畺閹嘲顭ㄩ崘顎囨煟濞戝崬鏋ら柍褜鍓ㄧ紞鍡涘磻閸℃瑥濮柍褜鍓涚槐鎺楀礈瑜嶉。濂告嚕閵堝鐓曢悗锝庡亝鐏忣參鏌ｉ敐鍥у幋鐎规洘鍎奸ˇ鎾煕濡湱鐭欓柡宀嬬稻閹棃濡舵惔銏㈢Х婵犵數鍋涘鍫曟偋閻樿绠栭柕澶涘闂勫嫮绱掔€ｎ偄顕滄俊宸墴濮婃椽寮妷锔界彅闂佸摜鍣ラ崹閬嶅礆婵犲嫧鍋撳☉娅虫垿宕ｈ箛鏃傜瘈闂傚牊绋掗ˉ鐘崇箾绾绡€闁哄矉绻濆畷鍫曞Ψ閵壯傜棯闂備焦濞婇弨杈╂暜閹烘绠掗梻浣瑰缁诲倸煤閵娾晛绠洪柛宀€鍋為悡鏇㈡煏閸繃顥犻柟鍐叉喘閺岀喖顢欑粵瀣暥闂佸疇妫勯ˇ鐢哥嵁閹烘绠婚悗鐢殿焾缁茶法绱撻崒姘偓椋庢閿熺姴绐楁俊銈呮噺閸嬶繝鏌嶉崫鍕櫧鐎规挷绶氶弻鐔兼倻濡櫣鍔稿┑鐐存尭椤兘寮婚敐澶婄闁哄啠鍋撴繛鍛噹闇夋繝濠傜墢閻ｆ椽鏌＄仦璇插鐎殿喗鎸抽幃娆徝圭€ｎ亙澹曢梺褰掓？閻掞箓宕愬畡鎵虫斀闁绘ɑ褰冮弳鏂棵瑰鍕煉闁哄瞼鍠栧畷顐﹀礋椤掑顥ｅ┑鐐茬摠缁挾绮婚弽褜娼栭柧蹇撴贡绾惧吋淇婇婵愬殭闂傚绉剁槐鎾存媴缁涘娈梺缁橆殕閹告悂顢氶敐鍡欑瘈婵﹩鍘藉▍銏ゆ⒑缂佹﹩鐒鹃悘蹇旂懇钘濋柕濞炬櫆閳锋垿鏌熺粙鎸庢崳缂佺姵鎹囬弻鐔煎礃閼碱儷锝囩磼閺冨倸鏋涚€殿喗鎸虫慨鈧柍閿亾闁归绮换娑㈠箻閺夋垹鍔伴梺绋款儐閹歌崵鎹㈠☉娆愬闁告劖褰冮獮妯荤箾瀹割喕绨婚崶鎾⒑閹肩偛鍔电紒鑼跺Г缁傚秹鎮欓浣稿伎濠碘槅鍨抽崢褏鏁崼鏇熺厽闊洢鍎抽幃鑲╃磼鏉堛劌娴い銏＄懃閳诲酣骞嗚椤斿嫰姊绘担鍝ユ瀮婵☆偄瀚拌棟闁割煈鍋呴崣蹇涙煃瑜滈崜鐔煎蓟閿濆憘鐔访虹拠鍙夋珱闂備礁鎽滈崰搴敄婢跺娼栫紓浣股戞刊鎾煕濞戞﹫鏀婚柛搴㈡尭椤啴濡惰箛鏇犵獥闂佸憡顨呴崯鍧楁偩閻ゎ垬浜归柟鐑樺灴閸炲爼姊洪崫鍕偍闁告柨绉瑰鎻掝煥閸啿鎷洪梺缁樺姌濡嫰宕濆鍫熺厸閻庯綆浜楅崑銏⑩偓娈垮枔閸斿秶绮嬮幒鏂哄亾閿濆骸浜為柛妯圭矙濮婇缚銇愰幒鎴滃枈闂佸憡鎸诲畝鎼佸春閵忋倕鍗抽柕蹇ョ磿閸橀亶姊洪棃娑氬婵炲眰鍊濆鍛婃償閵婏妇鍘撻柣鐔哥懃鐎氼剟鎮樼€涙ǜ浜滈柕蹇ョ磿閹冲洭鏌熼鐣屾噰妞ゃ垺顨嗛幏鍛村捶椤撶噥娼ㄩ梻鍌氬€搁崐宄懊归崶褜娴栭柕濞у懐鐒兼繛鎾村焹閸嬫挾鈧娲﹂崹鎶藉焵椤掍胶鈯曢拑閬嶆煕濞嗗繒绠婚柡灞界Х椤т線鏌涢幘璺烘灈鐎殿喖顭峰鎾閻樿鏁规繝鐢靛█濞佳兠洪妶鍛灁鐎光偓閸曨兘鎷虹紒缁㈠幖閹冲氦顣挎繝鐢靛仜瀵爼鎮ч悩璇叉槬闁绘劕鎼粻锝夋煥閺冨洦顥夐柍褜鍓涢崗姗€寮婚埄鍐ㄧ窞閻庯綆浜炴禒鍏肩箾鐎电校闁诡喖鍊搁～蹇撁洪鍛闂侀潧鐗嗛幊蹇撯枔瀹€鍕拺闁告稑锕ｇ欢閬嶆煕濡灝顥嶉柍顏呯叀濮婂宕掑▎鎴犵崲闂侀€炲苯澧伴柛瀣洴閹崇喖顢涘☉娆愮彿闁诲孩绋掕摫闁告瑥绻愰埞鎴︽偐閹绘帗娈查梺闈涙处缁诲嫰鍩€椤掑喚娼愭繛鎻掔箻瀹曟繂顓奸崶銊ュ簥濠电娀娼ч鍛矆閸愨斂浜滄い鎾跺枎閻忥妇鎮埡鍛拻闁稿本鑹鹃埀顒傚厴閹虫宕奸弴妞诲亾閿曞倸閱囬柕澶樺枟閺呯偤姊洪崨濠佺繁闁割煈浜畷鎴﹀箻閹颁焦鍍甸梺缁樻尭妤犲摜绮婚懡銈囩＝濞撴艾娲ら弸娑欍亜閹存繍妯€闁绘侗鍣ｉ獮鎺懳旈埀顒傜不閻樼鍋撶憴鍕婵炲眰鍊濆绋库槈閵忥紕鍘甸梺鎯ф禋閸嬪棙鏅堕悽鍛婄厱闁冲搫顑囩弧鈧悗瑙勬礃椤洭骞戦崟顖毼╅柍鍝勫亰缁鳖剙鈹戦悩鍨毄濠殿喚鍏樺顐﹀箹娴ｅ摜锛涢梺缁橆焾椤曆呯不閸偁浜滈煫鍥ㄦ尰椤ユ粎绱掗煬鎻掆偓鏇㈡箒闂佺粯锚濡﹪宕曡箛鏇犵＜闁绘﹢娼ч崝瀣磼缂佹绠栫紒缁樼箞瀹曟帒顭ㄩ崘鐐瘒闂傚倷绀侀幖顐も偓姘ュ姂瀹曟洟鎮界粙鑳憰闂侀潧顭堥崕顕€寮ㄦ禒瀣厱闁斥晛鍘鹃鍛浄濡わ絽鍟埛鎴︽煠婵劕鈧洟寮稿☉銏＄厱閻庯綆浜烽煬顒勬煙椤曞棛绡€濠碉紕鍏橀崺锟犲磼濠婂啫绠為梻鍌欐祰椤顭垮鈧畷銉╁焵椤掑倻纾奸柕濞垮労閻撳ジ鏌″畝瀣М妤犵偞顭囬幑鍕倻濡棿閭┑鐘愁問閸犳牠鏁冮妸銉㈡瀺闁挎繂娲﹂～鏇㈡煙閻戞ê娈鹃柣鏃傚帶閹硅埖銇勯幘璺盒ラ柣锝嗗▕濮婂宕掑▎鎴犵崲濠电偠澹堝畷鐢垫閻愬搫鐐婇柍鍝勫暟椤︻垱绻涢幘鏉戠劰闁稿鎹囬弻鐔碱敊鐠囨彃绁銈冨灪瀹€鎼佸春閳ь剚銇勯幒鎴濐伀鐎规挷绶氶弻鐔兼倻濮楀棙鐣剁紓浣哄Х婵炩偓闁哄睙鍡欑杸闁挎繂鎳嶇花鐓庮渻閵堝啫鍔氶柣妤佹崌瀵鈽夐姀鐘靛幋闂佽鍨庨崒姘兼濠电姷顣槐鏇㈠磻閹达箑纾归柡宥庡亝閺嗘粌鈹戦悩鎻掝伀闁活厼妫楅妴鎺戭潩閿濆懍澹曢柣搴ゎ潐濞叉鎹㈤崼婵愬殨妞ゆ洍鍋撶€规洖銈搁幃銏ゅ矗婢跺浼滈梻鍌氬€烽懗鍫曗€﹂崼銉ュ珘妞ゆ帒瀚崑锛勬喐韫囨洖鍨濋柨婵嗩槸缁秹鏌嶈閸撴盯骞戦姀鐘婵炲棙鍔曢鎾绘⒑閸涘﹤濮囩€殿喖鐖艰棢婵犲﹤瀚粻楣冩煕濠婂啫鏆熺紒澶樺枟閹便劍绻濋崟顓炵闂佺懓鍢查幊妯虹暦閵婏妇绡€闁稿本绋掗悾鑲╃磽閸屾艾鈧娆㈤敓鐘茬獥闁哄稁鍘介崑瀣叓閸ャ劍绀€闁搞劍绻堥弻娑㈩敃閵堝懏鐏侀梺鑽ゅ枎缂嶅﹪寮诲鍫闂佸憡鎸婚悷鈺呫€佸鑸垫櫜濠㈣泛锕ㄩ幗鏇㈡⒑闂堟侗妯堥柛鐘愁殜瀵彃顭ㄩ崼鐔叉嫼闂佸憡鎸昏ぐ鍐╃閻愮儤鐓曢柣鏃堟敱閸嬨儲顨ラ悙鑼缂佺粯绻傞～婵嬵敇濞戞瑥顏圭紓鍌氬€风粈渚€顢栭崱娆屽亾缁楁稑鍠涢懓鍨归悡搴ｆ憼闁绘挾鍠栭弻锝夊籍閳ь剛鎹㈤崒姣椽濡堕崶鈺冪劶婵犮垼娉涙径鍥磻閹捐崵宓侀柛顭戝枛婵骸顪冮妶蹇曠窗闁告濞婇獮鍐晸閻樺啿浜滈梺纭呭亹閸嬫鑺辨繝姘棅妞ゆ劑鍨烘径鍕煙閸涘﹥鍊愭い銏℃椤㈡洟濡堕崶鈺嬬床濠电姰鍨煎▔娑氣偓娑掓櫊椤㈡棃鎮╃紒妯煎帗閻熸粍绮撳畷婊冣攽鐎ｅ墎绋忔繝銏ｆ硾閳洟宕崟搴ｅ枛瀹曟鎮℃惔锛勫搸闂傚倷鑳堕…鍫ユ儔婵傜纾婚柣鎰惈绾惧鏌嶉崫鍕偓鑽ゅ姬閳ь剟姊婚崒姘卞濞撴碍顨婂畷鏇＄疀濞戞瑧鍘介梺鍦劋閸ㄨ绂掑☉銏＄厪闁搞儜鍐句純濡ょ姷鍋炵敮锟犵嵁鐎ｎ亖鏀介柟閭︿簼閸嬪懘姊婚崒娆掑厡缂侇噮鍨抽弫顕€骞掑Δ浣糕偓鑸垫叏濡寧纭惧鍛存⒑閸涘﹥澶勯柛銊﹀缁鐣烽崶锝呬壕妤犵偛鐏濋崝姘舵煟濡も偓濡繂鐣烽姀銈呯伋闁归鐒︾€靛矂姊洪棃娑氬缂佺粯甯″畷姘跺箥椤旂懓浜炬繛鍫濈仢閺嬫稑顭胯闁帮綁鐛幋锕€顫呴柣姗嗗亝閺傗偓闂佽鍑界紞鍡樼鐠轰警鐒藉┑鐘叉处閳锋垿鎮楅崷顓炐ｆい銉ヮ槹娣囧﹪顢曢敐鍥ㄥ垱閻庤娲樼换鍫ョ嵁閺嶃劍濯撮柛蹇擃槹鐎氬ジ姊洪懡銈呅㈡繛娴嬫櫇娴滅鈻庨幋鐘辩瑝闂佺粯顨呴悧鍕濠婂牊鐓欓悗娑欘焽缁犮儲淇婇幓鎺撳暈闁靛洤瀚伴、鏇㈠閵忋埄鍞堕梺缁樻尪閸婃牠濡甸崟顔剧杸闁圭偓娼欏▍锝嗙箾鐎涙鐭嬫い銊ワ躬瀵鎮㈤悡搴ｎ槯闂佸吋绁撮弲婊冣枔椤掑嫭鈷戦柟鑲╁仜婵¤姤淇婇悙鑸殿棄闁伙綁鏀辩€靛ジ寮堕幋鐘垫澑婵＄偑鍊栫敮鎺椝囬幍顔瑰亾闂堟稓鐒告慨濠冩そ濡啫鈽夊顒夋毇缂傚倷鑳剁划顖滄暜閻愰潧鍨濋柡鍐ㄧ墛閸嬨劑鏌涘☉姗堝姛闁告﹢浜跺铏圭磼濡浚浜幃鍧楀炊閵娧呭骄濠殿喗銇涢崑鎾垛偓瑙勬穿缁绘繈寮婚崱妤婂悑闁糕剝鐟ラ獮宥夋⒒娴ｇ瓔娼愭い鏃€鐗犲畷浼村冀椤撴壕鍋撻崒娑氶檮闁告稑锕﹂崢鎼佹⒑閸涘﹣绶遍柛鐘冲哺瀹曪綁鍩€椤掑嫭鈷戦柛婵嗗濠€浼存煟閳哄﹤鐏︾€规洘妞藉畷鐔碱敍濮橀硸妲伴梻浣稿暱閹碱偊宕板顑╋綁宕滄担铏癸紳闂佺鏈悷銊╁礂鐏炶В鏀芥い鏃傚亾閺嗩剟鏌熼搹顐ょ畺闁靛牞缍佸畷姗€鏁愰崒姘闂佸搫鍟悧鍡欑矆閸愨斂浜滈柡鍌涘椤秶鎲搁弮鍫濊摕婵炴垯鍨归悞娲煕閹板吀绨奸柛锛卞喚娓婚柕鍫濋閳ь兙鍊濆畷銊╊敍濠婃劗闂繝鐢靛仦閹稿鎳濋幆顬℃椽濡舵径濠傚殤濠电偞鍨崹娲煕閹达附鍋ㄦい鏍电到閺嬨倗绱掔€ｎ収鍤欓懣鎰版煕閵夋垵绉存慨娑㈡⒑闁偛鑻晶顖滅磼鐎ｎ偄娴柍銉畵瀹曞爼鍩℃担鎰熸岸姊洪柅鐐茶嫰婢у瓨鎱ㄦ繝鍐┿仢妤犵偞鐗犻幃娆撳箵閹烘埈娼欓梻鍌欑閹诧繝寮婚妸鈺傜厐闁挎繂鎳愰弳?"
        if scenario == "principle":
            anchor += " 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏咁棃婵炴番鍎遍悧鎾愁嚕閹绘巻妲堥柕蹇曞Х椤㈠懘姊虹憴鍕姸濠殿喓鍊濋幃锟犳偄閸忚偐鍘甸梻渚囧弿缁犳垿鎮橀悩鐢电＜闁规彃顑呴々顒傜磼鏉堛劌娴┑鈩冩倐婵″爼宕堕埡鍐ㄥ箚濠电姵顔栭崰鏍晝閿曞倸纾块柕鍫濇媼閻掕姤銇勮箛鎾跺缂佺姰鍎查妵鍕即閻愭潙娅ら悶姘剧畵濮婂宕掑▎鎴М闂佺濮ょ划鎾崇暦閹惰棄唯闁宠桨鑳堕敍娑欑節閻㈤潧孝婵炲眰鍊濆浼村Ψ閳哄倻鍘介梺褰掑亰閸撴岸骞嗛崼銏㈢＜闁绘瑥鎳愮粔顕€鏌＄仦璇插鐎殿喗娼欒灃闁逞屽墯缁傚秹宕滆绾惧ジ鏌ｉ幇闈涘闁告柣鍊濋弻娑橆潩椤掑鍓跺Δ鐘靛仜閻楁挻淇婇幖浣肝ㄦい鏃囨缂傛捇姊绘担铏广€婇柛鎾寸箞閵嗗啴宕ㄩ婊€绗夐悷婊呭鐢鍩涢幋锔界厱婵犻潧妫楅顏呫亜閵夛妇鐭掗柡宀嬬到铻栧ù锝囨嚀绾板秴顪冮妶搴′簻缂佺粯锕㈤獮鏍亹閹烘垶宓嶅銈嗘尵婵妲愰崣澶岀瘈缁剧増蓱椤﹪鏌涢妸褎鏆い銏′亢椤︽挳鏌涢悩璇у伐妞ゆ挸鍚嬪鍕偓锛卞嫬顏圭紓鍌氬€风粈渚€顢栭崨顖欑剨闁告侗鍙庨崯鍛存煏婢舵稖绀嬪ù婊勭矋閵囧嫰骞樼捄鐩掋垽鏌涘Ο渚殶闁逞屽墲椤煤濡警娓诲ù鐘差儏閺勩儵鏌嶈閸撴岸濡甸崟顖氱鐎广儱顦伴鏍ㄧ箾鐎涙鐭嬬紒顔芥崌瀵鎮㈤悡搴濈炊闂佸憡娲﹂崜锕€螞閻愬绠鹃悗娑欘焽閻﹤顭胯閺咁偄危閹版澘绠婚悗娑櫭鎾绘⒑閸涘﹦绠撻悗姘嚇婵偓闁靛繈鍨婚敍婊勭節閵忥絾纭鹃柡鍫墴瀹曠敻鍩€椤掑嫭鈷戝ù鍏肩懅閹ジ鏌涜箛鏂嗩亪顢氶敐澶婄妞ゆ梻鈷堝濠囨⒑缂佹〞鎴︻敊閺嶎厼缁╅柕濞炬櫆閳锋帒霉閿濆洨鎽傞柛銈嗙懅缁辨帞绱掑Ο铏诡儌闂佸憡甯楃敮锟犮€佸☉姗嗘僵闁稿繒鍘ч惁婊堟⒒娴ｇ鎮戝ù婊€绮欏畷鏇㈠箥椤旇棄搴婇梺绯曞墲缁嬫帡鎮￠弴鐔翠簻闁规澘澧庣粙鑽ょ磼閳ь剟鍩€椤掆偓铻栭柣姗€娼ф禍濂告煕閵娿劍顏犻柟骞垮灩閳藉濮€閻樿尪鈧灝鈹戦埥鍡楃仭婵炲弶锕㈠畷褰掑捶椤撶偛鐏婃繝鐢靛Т濞村倿寮崘顔界叆婵犻潧妫楅顐ょ磼閻樺啿鍝烘慨濠呮缁辨帒螣閸濆嫅鏇熺箾鐎涙鐭嬬紒顔芥崌瀹曟椽鍩€椤掍降浜滈柟鍝勭Х閸忓苯顭胯閺佸寮婚悢纰辨晩闁靛鍎遍幃鈺呮煛閸愩劎澧曠€瑰憡绻冮妵鍕箻鐠虹儤鐎鹃悶姘剧秮濮婂宕掑▎鎴М闂佺顕滅换婵嗙暦濠靛绠ｉ柨鏇楀亾缂佲偓閸喆浜滈柡鍥殔娴滈箖姊烘潪鎵妽闁告梹鐗曢銉╁礋椤掑倻鐦堥梺鎼炲劀閸曨剚鐦戦梻鍌氬€搁崐椋庢濮橆剦鐒界憸鏃傜槵闂侀€炲苯澧柍瑙勫灴閸ㄩ箖鎼归銏＄亷闁诲氦顫夊ú蹇涘垂娴犲绠栧ù鐘差儏瀹告繂鈹戦悙闈涗壕閻庢艾銈稿娲嚒閵堝憛銏＄箾閼碱剙鈻堥柛鈹惧亾濡炪倖宸婚崑鎾剁棯缂併垹寮柛鈹惧亾濡炪倖宸婚崑鎾淬亜椤撶姴鍘寸€殿喛顕ч埥澶婎潨閸℃瑥寮抽梻浣告啞閸旀垿宕濆鍛灁闁告挷鑳剁壕钘壝归敐鍡楃祷濞存粎鍋撶换婵嬫偨闂堟刀銏＄箾鐠囇呯暤闁糕晜鐩獮瀣晜閻ｅ苯骞堟繝鐢靛█濞佳兾涘Δ鍜佹晜妞ゆ劑鍊栭崑鏍煥閺囩偛鈧綊鍩涢幋锔解拺妞ゆ劑鍊曟禒婊堟煠濞茶鐏￠柡鍛埣椤㈡盯鎮欑€电骞愰梺璇插嚱缂嶅棙绂嶅Δ鍛；闁靛繆鎳囬崑鎾斥枔閸喗鐏侀梺鍛婃煥缁夊墎鍒掔€ｎ喖绠抽柡鍌氭惈娴滈箖鏌ㄥ┑鍡涱€楀ù婊呭仱閺屾稑螣缂佹ê纾冲┑顔硷龚濞咃綁鍩€椤掆偓濠€杈ㄦ叏閻㈢违闁告劦浜炵壕濂告煃瑜滈崜姘辩箔閻旂厧鐒垫い鎺嗗亾妞ゆ洩缍佸畷妯好圭€ｎ偆鈧姊洪悷閭﹀殶濠殿喚鍏橀弫宥咁煥閸啿鎷洪梺闈╁瘜閸樺墽鏁☉銏″仺妞ゆ牗顨嗗▍濠囨煙椤旂懓澧茬紒杞扮矙瀹曘劍绻濋崟顐㈢闂佽楠搁崢婊堝磻閹剧粯鐓冪憸婊堝礈閻旈鏆﹂柣妤€鐗婇崕鐔兼煏婵犲繐顩柣锝嗗▕濮婄粯鎷呯粵瀣闂佸憡鍨崇划娆撶嵁閳ь剟鏌曟径鍡樻珔缂佲偓閸愵亝鍠愮€广儱锛嗘径濠庢僵闁煎摜顣介幏缁樼箾鏉堝墽鍒伴柟鑺ョ矌缁棃鎮滃Ο闀愮盎闂佹寧绻傜换鎰般€呴鍌滅＜妞ゆ棁鍋愭晶娑㈡煙瀹勭増鍣介柛鏍ㄧ墵瀵挳鎮㈡潪鎵寜婵犵绱曢崑鎴﹀磹閺嶎厼绀夌憸鏂款潖娴犲绀嬫い鏍ㄦ皑閸橀亶姊虹涵鍛涧闂傚嫬瀚伴幃锟犲即閻旇櫣顔曢梺鐟邦嚟閸庢垿宕楅鍕厸闁逞屽墰閹风姴顔忛鎯ф暩闂佽崵濮撮幖顐﹀箹椤愶富鏁傛い鎾卞灪閻撴盯鎮橀悙鎻掆挃闁靛棙甯￠弻宥堫檨闁告挶鍔庣槐鐐哄幢濞戞锛涢梺鍛婃处閸樺墽绮婚弮鍫熺厵闁绘垶蓱鐏忣亜霉濠婂嫮鐭嬮柕鍥у楠炴鎹勬潪鐗堝媰闂備礁鎽滄慨鐢告晝閵忋倕钃熸繛鎴欏灩閻撴盯鎮楅敐搴″闁伙箑鐗撻幃妤冩喆閸曨剛顦ㄩ柣銏╁灡鐢喖鎮橀幒妤佲拺闂傚牃鏅涢惁婊堟煕濡鍔ら柍缁樻瀹曠螖娴ｅ弶瀚介梻浣侯焾閺堫剟鎮烽妸鈺佺鐎光偓閸曨剛鍘甸梺鎯ф禋閸嬪懎鐣风仦缁㈡闁绘劕顕晶鍨亜閵忊剝绀嬮柛鈺傤殜閹崇偤濡疯濡插牓鏌х紒妯煎ⅹ闂囧鏌ㄥ┑鍡楊伂妞ゆ帞鍠愮换娑㈠箵閹烘挸鏆堟繛锝呮搐閿曨亝淇婇幆鎵杸闁哄洨鍋涢悡鍌炴⒒娴ｅ憡鎲搁柛锝冨劦瀹曞綊宕奸弴鐐存К濠电偞鍨崹鍦不閿濆鐓ラ柡鍐ㄥ€瑰▍鏇㈡煕濡搫鑸归柍瑙勫灴閹晝绱掑Ο濠氭暘婵犵妲呴崑鍛淬€冩繝鍥モ偓渚€寮崼顐ｆ櫆闂佸壊鍋嗛崰鎾诲储闁秵鈷戦柟绋挎捣缁犳捇鏌ｅΔ鈧Λ婊堛€傞崸妤佲拻濞撴埃鍋撴繛浣冲厾娲Χ閸ワ絽浜炬慨姗嗗亜瀹撳棝鏌曢崱鏇狀槮妞ゎ偅绮撻崺鈧い鎺戝缁犳牗绻涢崱妯诲鞍妞ゃ儱鐗婄换娑㈠箣閻愯尙鐟ㄩ悗鍨緲缁夋挳鍩為幋锔藉亹闁割煈鍋呭В鍕節濞堝灝娅橀柛娆忓暙閻ｇ兘骞嬮敃鈧粻濠氭煟閹邦垍鎺楀磻閹捐绠抽柟鎼幗閸嶇敻姊洪幐搴ｇ畵闁瑰啿绉电粩鐔煎即閻旇櫣鐦堝┑鐐茬墕閻忔繈寮稿☉銏＄叆闁哄洦锚婵″ジ鏌嶇拠鑼ч柡浣瑰姍瀹曞爼鈥﹂幋鐐电◥闂傚倷绀佸﹢閬嶅磿閵堝鍚归柨鏇炲€归崑鍕煟閹捐櫕鎹ｆい蟻鍥ㄢ拺缂備焦蓱鐏忣參鎮楀☉鎺撴珚闁诡喚鏁婚弫鎰緞鐎Ｑ勫闂備胶顭堥張顒勬偡閵娾晛绀傞悘鐐板嫎娴滄粓鏌曡箛鏇烆€撶€规悶鍎甸弻宥囨嫚閼碱儷褏鈧鍠楅幐铏叏閳ь剟鏌ｅΟ娲诲晱婵℃煡鏀辩换婵嬫偨闂堟稐绮跺┑鈽嗗亝閻熲晠鐛幇鏉跨畾鐟滃繘寮抽妶鍛偓鎺戭潩閿濆懍澹曢梻浣告惈閺堫剟鎯勯鐐靛祦闁搞儺鍓欐儫闂佹寧姊婚弲顐ャ亹閸ヮ剚鈷掗柛灞捐壘閳ь剙鎽滈埀顒佸嚬閸撴盯鍩€椤掍胶鐓柛妤€鍟块锝囨嫚濞村顫嶅┑鈽嗗灦閺€閬嶏綖瀹ュ應鏀芥い鏃傜摂濞堟棃鏌ｅΔ鈧Λ娆撳箞閵娿儮妲堥柕蹇婃閹锋椽姊洪崨濠勨槈闁愁垱娲熼幊鏍煛娴ｅ摜浜版繝鐢靛仜濡霉濮橆剦鐒介柡宥冨妿缁犲墽鈧懓澹婇崰鏇犺姳鐠囪褰掓嚃閳轰讲鏋呴梺鍝勬湰閻╊垰顕ｉ幘顔嘉╅柕澶堝劥缁剁喖姊绘担铏瑰笡妞ゎ厼娲ㄩ崚鎺楊敍閻愭潙浜楅梺鍝勬储閸ㄦ椽鎮″☉銏＄厱閻忕偛澧介。鏌ユ煕鐎ｃ劌鍔﹂柡灞剧☉閳诲氦绠涢幙鍐х磾闂備礁鎼惉濂稿窗閺嶎厹鈧礁鈽夊鍡樺兊闁哄鐗冮弲娑欐叏鏉堛劋绻嗛柕鍫濇搐鍟搁梺绋款儑閸嬬喖寮鈧獮鎺楀即閻樿京鑳哄┑鐘垫暩閸嬬娀骞撻鍡楃筏濞寸姴顑呯粻瑙勩亜閹拌泛顩€规挷绶氶弻鐔兼焽閿曗偓閸樻挳鏌￠埀顒佺鐎ｎ偆鍘介梺褰掑亰閸ㄤ即鎮￠幇顔藉枑闁硅泛锕ら幊鎰婵傚憡顥婃い鎰靛亜楠炴﹢鏌ｉ鐔烘噭妞ゃ劊鍎甸幃娆撳箹椤撶喓鏆ユ俊鐐€ら崢褰掑礉閹存繄鏆︽慨妞诲亾妞ゃ垺妫冨畷銊╊敊閸忚偐褰涢梻鍌氬€搁崐鎼佸磹閹间礁纾归柟闂寸绾惧湱鈧懓瀚伴崑濠傘€掓繝姘厵闁绘垶蓱閳锋劖銇勯锝嗙闁靛洤瀚板顕€鍩€椤掑嫬纾跨€规洖娲﹂浠嬫煏閸繍妲归柣鎾存礋閺岀喖鎮欓澶嬬暥闁诲孩鍑归崜姘跺箚閺冣偓缁绘繈宕堕妸銏″闂備礁鎲￠幐鏄忋亹閸愨晝顩叉繝闈涚墢绾惧ジ鎮归崶銊ョ祷妞ゅ浚鍘鹃埀顒侇問閸犳绻涙繝鍥ф瀬闁稿瞼鍋為崵宥夋煏婢跺牆鍔氬ù鐓庡缁绘繄鍠婃径宀€锛熼梺绋款儑婵炩偓妞ゃ垺淇洪ˇ宕囩磼閸屾氨校闁靛牞缍佸畷姗€鍩為悙顒€顏归梻浣告惈椤﹂亶宕戦悙瀵哥彾闁糕剝绋戠粈澶屸偓骞垮劚椤︿即鎮￠弴銏＄厸闁告劧绲芥禍楣冩⒑閼姐倕鏋傞柛搴ｆ暬楠炲啯銈ｉ崘鈺佲偓濠氭煢濡尨绱氶柍鍝勬噺閻撳啴鏌涘┑鍡楊伒闁衡偓婵犳碍鐓涢柛娑卞亜閻忓弶鎱ㄦ繝鍐┿仢闁哄苯鎳橀幃娆撴嚑鐠轰警浼冨┑鐘媰閸曨剙鍞夐梺鍦焾閿曨亪骞冮姀銈呭窛濠电姴鍊告导搴㈢節绾版ɑ顫婇柛銊ゅ嵆閹ê鈹戠€ｎ偄浜楅梺瑙勫婢ф鎮￠崘顔解拺闁割煈鍣崕蹇涙煟韫囨梹灏﹂柡宀€鍠栭、娆撴嚃閳哄唭銊╂倵鐟欏嫭绀€闁绘牕銈搁妴渚€寮崼婵堫槹濡炪倖鎸鹃崳銉╁吹閸曨厾纾介柛灞捐壘閳ь剛鍏橀幊妤呮嚋閸偄寮块梺鍓茬厛閸嬪棛绮婚幆褉鏀介柣妯哄级閹兼劙鏌﹂崘顏勬瀾缂佺粯鐩獮瀣倷閼碱剙濮查梻浣侯焾椤戝棝骞戦崶顒€鏋侀柟閭﹀幗閸庣喖鏌嶉妷锕€澧繛鐓庮煼濮婄粯鎷呴崨濠冨創濡炪倖鍨靛Λ娑氬垝濞嗘挸绠婚悹鍥皺閸旓箑顪冮妶鍡楃瑨闁哥姵鑹鹃…鍥箛椤撶姷顔曢梺鍛婄懃椤р偓闁兼媽娉曢埀顒冾潐濞叉牜绱炴繝鍌滄殾缂佸顕抽弮鍫濈闁靛ě浣镐喊婵犵數濮甸鏍窗濡ゅ懎桅婵炴垯鍨圭壕濠氭煙閹呬邯闁稿鎸鹃幉鎾礋椤掑偆妲扮紓鍌欑贰閸犳牜绮旇ぐ鎺斿祦闊洦绋戝婵嬫倵濞戞顏呯椤撱垺鈷戠紓浣癸供濞堟棃鏌ｅΔ鈧换妤呭Φ閹伴偊鏁嶉柣鎰ˉ閹峰姊虹粙鎸庢拱闁煎綊绠栭崺鈧い鎺嶇劍閸婃劗鈧娲橀崝娆撶嵁閺嶃劍濯撮柛婵勫劵缁鳖噣姊绘担鍝ョШ婵☆偉娉曠划鍫熸媴閸濆嫷妫滈悷婊呭鐢鎮￠悢鍏肩厵閺夊牆澧介崚鎵偖濮樿埖鈷戦柟鑲╁仜閳ь剚娲滈埀顒佺煯閸楀啿顕ｇ拠娴嬫闁靛繆鏅滈弲婵嬫⒑閹稿海绠撴俊顐ｇ洴閺佸秴顫滈埀顒€顫忓ú顏呯劵闁绘劘灏€氫即鏌涘Ο缁樺€愰柡宀嬬秮楠炴帡鎮欏顔藉枠闂備胶鎳撶粻宥夊垂瑜版帒鐓橀柟瀵稿Л閸嬫捇鏁愭惔婵堟晼闂佹寧绋掔划宀勫煘閹寸偛绠犻梺绋匡攻閹瑰洭骞婂Δ鍛殝闁汇垺顔栧ú绋库攽閻愬弶顥為柛鏃€顨堝褔鍩€椤掑嫭鈷戞慨鐟版搐閻忓弶绻涙担鍐插椤╃兘鏌ㄩ弴鐐测偓褰掓偂閺囩喆浜滄い鎾跺枎閻忋儵鏌ｈ箛銉ヮ洭闁逞屽墲椤煤濠婂牆绠犻柟鎹愭硾瀵弶淇婇悙顏勨偓鏇犳崲閹邦喒鍋撳鐓庢珝鐎殿喗妲掗ˇ鏌ユ煃鐟欏嫬鐏撮柟顔规櫇缁辨帒螣婵犳碍鏆樺┑锛勫亼閸婃牠宕归棃娴虫稑鈹戠€ｎ亞鐣洪梻鍕川缁鈽夐姀鐘殿啌闂佸憡鍔︽禍婊堝极閹间焦鈷戦柤濮愬€曢埢鍫㈢磽閸屾稖澹橀柍璇茬Ч閺佹劙宕卞Ο鑽ゅ娇闂備礁鎼ú銏ゅ垂濞差亝鍋傞柡鍥ュ灪閻撴盯鏌涢幇鍓佸埌濞存粍鍎抽—鍐Χ閸愩劌顬堥梺鎸庢处娴滄粓顢氶敐鍡欑瘈婵﹩鍘藉▍銏ゆ⒑缂佹﹩鐒鹃悘蹇旂懇瀹曟繈鏁冮埀顒勨€旈崘顔嘉ч柛鈩冾殘閻熴劑鏌ｆ惔銏犲毈闁告瑥鍟锝夊箵閹哄棙鏂€闁诲函缍嗛崑鍡涘储闁秵鐓熼煫鍥ㄦ礀娴犳粌顭胯缁瑦淇婇幘顔肩婵°倓鑳堕崢鍗炩攽閳藉棗鐏ｇ紒顕呭灠閻ｅ嘲鐣濋崟顒傚幍濡炪倖姊婚崢褍危缂佹ǜ浜滄い鎾寸矊婵倻鈧娲滈崰鏍€佸鈧幃鈺呮濞戞绶熼梻鍌欐祰椤曆冾潩閿曞偊缍栧璺衡姇閸濆嫀鐔兼偂鎼达紕浜伴梻浣筋潐瀹曟﹢顢氳缁寮介鐔哄帾闂婎偄娲ら鍛村焵椤掍胶澧电€规洘鍨垮畷鎺楁倷閼碱剦鍟囨繝鐢靛剳缂嶅棝宕滃▎鎾崇劦妞ゆ帊鑳舵晶鍨殽閻愬樊妯€闁诡啫鍥ч唶闁靛繈鍨诲Σ鍥⒒娴ｅ湱婀介柛銊ㄦ椤洩顦崇紒鍌涘浮閺佸啴宕掑☉姘箞婵＄偑鍊ら崢浠嬪垂閻㈠憡鍊堕柨鏃堟暜閸嬫挾鎲撮崟顒傤槬缂傚倸绉撮敃銈夋偩閻戣姤鍊荤紒娑橆儐閺咃綁姊虹紒姗嗙劸濞存粠鍓熼幃宄扳攽鐎ｎ偀鎷绘繛杈剧悼閻℃柨顭囬幇鐗堢厱閹肩补鈧櫕鍊梺閫涚┒閸旀垶淇婇懜闈涚窞閻庯綆浜欑花鍨節閻㈤潧浠滄俊顐ｇ懇楠炴劖绻濆顒傦紮闂佸壊鐓堥崑鍡欑不妤ｅ啯鐓欓悗鐢殿焾娴犙囨煙閾忣偄濮嶉柡宀嬬秮楠炴帡寮埀顒€鈻嶉弴鐘电＜閺夊牄鍔屽ù顕€鏌熼瑙勬珚妞ゃ垺鐟╅幃鈩冩償閳辨帗娲熷缁樻媴閸涘﹥鍎撻梺娲诲幖椤﹂亶骞戦姀鐘斀闁糕剝鐟﹀▓楣冩⒒娓氬洤澧紒澶婎嚟缁鈽夊▎宥勭盎闂佸湱鍎ら崹鐢稿焵椤掑倸鍘存鐐插暣閺佹劖寰勭€Ｑ勫濠电偠鎻徊浠嬪箺濠婂牆鍑犻柛鎰ㄦ杺娴滄粍銇勯幇鈺佺労婵☆垪鍋撻柣搴ゎ潐濞叉牜绱炴繝鍌滄殾缂佸顕抽弮鍫濈劦妞ゆ帒鍊绘稉宥夋煛瀹ュ骸骞楅柣鎾冲暣閺屾稑鈹戦崱妤婁痪婵犳鍨伴妶鎼佸蓟閳╁啯濯寸紒瀣濞堟煡姊洪棃娑欐悙閻庢矮鍗抽妴渚€寮撮姀鈺傛櫇闂侀潧绻掓慨鐑筋敊閹邦厺绻嗛柣鎰典簻閳ь剚鍨垮畷鏇㈠箵閹烘梹娈曠紓浣割儐椤戞瑥顭囬弽褉鏀介柣妯虹枃婢规鐥幆褍鎮戠紒缁樼洴瀹曞崬螣閾忓湱鎳嗛梻浣告啞閿曨偆鎹㈠┑鍡╂綎闁惧繐婀遍惌娆愮箾閸℃ê鍔ら柛鎿冨弮濮婃椽宕ㄦ繝鍐ｆ嫻闂佹悶鍔庨弫濠氬箖妤ｅ啯鍊婚柦妯侯槸瀹撳棝姊洪棃娑氱濠殿噣绠栭獮妤呭即閵忊檧鎷洪梻鍌氱墛娓氭危閸洘鐓曢幖娣灩閳绘洟鎸婂┑鍥ヤ簻闁规崘娉涙禍褰掓煛閳ь剟鎳為妷锝勭盎闂佸搫鍟犻崑鎾绘煛鐎ｎ剛甯涚紒妤冨枎閳藉濮€閿涘嫬骞堥梻浣烘嚀閻忔繄鈧凹鍣ｉ幃楣冩偨閸涘﹦鍘靛銈嗘⒐閸庤櫕绂掗柆宥嗙厵缂佸灏呴弨鑽ょ磼閺冨倸鏋庨柍瑙勫灴瀹曞崬鈻庨幊韬插姂濮婅櫣鎷犻垾铏亐闂佸憡鎸荤换鍫ョ嵁閸℃稑绫嶉柛顐ゅ枑濞呮粓姊虹化鏇炲⒉闁挎岸鏌＄€ｎ偆娲存慨濠傤煼瀹曟帒鈻庨幒鎴濆腐缂傚倷绶￠崳顕€宕归崼鏇犲祦闁圭増婢橀柋鍥煛閸モ晛浠ч柨娑氬枛濮婃椽鎳栭埞鐐珱闂佸憡鎸婚懝楣冩偩閻戣棄鐭楀璺虹灱閻﹀牓姊婚崒姘卞濞撴碍顨婂畷鏇㈠箛椤撴粈绨婚梺闈涱槶閸庤櫕鏅跺☉姘辩＜缂備焦顭囧ú瀛橆殽閻愬樊鍎旈柟顔界懇瀹曞綊顢曢姀鈽嗕槐婵犵數濮烽。钘壩ｉ崨鏉戠；濞撴埃鍋撶€规洘鍔欏浠嬵敃閿濆懎绨ユ繝鐢靛█濞佳囶敄閸涘瓨鍋傞柡鍥ュ灪閻撳啰鎲稿鍫濈闁绘棃顥撻弳锕傛煕椤愶絾绀冮柡鍛矒閺岋箑螣娓氼垱效闂佽绻戦幑鍥ь潖婵犳艾纾兼繛鍡樺焾濡差噣姊洪崷顓涙嫛闁稿锕ら锝夋偨閸撳弶鏅㈤梺鍛婃处閸撴瑩宕滈纰辨富闁靛牆妫涙晶閬嶆煕鐎ｎ偆銆掔紒顔碱煼瀵粙濡歌椤旀洟姊虹化鏇炲⒉閽冮亶鎮樿箛搴″祮闁哄本鐩俊鍫曞幢濡ゅ啩妗撻梻渚€娼уú銈団偓姘嵆閻涱噣骞掑Δ鈧粻锝嗙節闂堟稑鏆欏ù婊堢畺閺岀喖鎮ч崼鐔哄嚒闁诡垳鍠栧娲濞戣鲸肖闂佹悶鍔嶅钘夘嚕椤掑嫬鐒垫い鎺嶆缁诲棝鏌ｉ幇鍏哥盎闁逞屽墯閻楁洟锝炶箛鏃傜瘈婵﹩鍎甸妷鈺傚€甸柨婵嗛閺嬫稓绱撴担鍙夋珖缂佽鲸鎸婚幏鍛叏閹达絽浜归柟骞垮灲瀹曞崬鈽夊▎鎴濆箺闂備礁缍婇崑濠囧储婵傛潌澶屸偓锝庡枟閻撶喐銇勯幘璺烘灁闁瑰啿娲弻锛勪沪閻愵剛顦伴悗瑙勬礋娴滆泛顕ｉ幘顔藉亹闁汇垽娼ф惔濠囨⒑鐠囨彃顒㈡い鏃€鐗犲畷鏉课旈崨顓狀唶闂佹儳娴氶崑鍛村矗韫囨稒鐓冪憸婊堝礈閻旂厧钃熼柨婵嗘噳閺嬪酣鎮橀悙鏉戠亰濠㈣娲樼换婵嬫偨闂堟稐鎴烽梺鍛婎焼閸ャ劍娅囧銈呯箰鐎氬嘲顭囬弽銊х鐎瑰壊鍠曠花鍏笺亜閵夈儳澧涚紒缁樼洴楠炲鎮欑€靛憡顓婚梻浣圭湽閸婃洜鈧碍婢橀～蹇撁洪鍕啇闂佺粯鍔栬ぐ鍐€栭崼婵愭富闁靛牆楠搁獮鏍煕閵忥紕鍙€妞ゃ垺宀搁弫鎰緞鐎ｎ亝鐤傞梻浣圭湽閸ㄦ椽顢欓弽顬″綊宕熼娑氬幗闁瑰吋鎯岄崹宕囩矓閻㈠憡鐓曢悗锛卞啩澹曢梻?"
        elif scenario == "concept_teaching":
            anchor += " 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏咁棃婵炴番鍎遍悧鎾愁嚕閹绘巻妲堥柕蹇曞Х椤㈠懘姊虹憴鍕姸濠殿喓鍊濋幃锟犳偄閸忚偐鍘甸梻渚囧弿缁犳垿鎮橀悩鐢电＜闁规彃顑呴々顒傜磼鏉堛劌娴┑鈩冩倐婵″爼宕堕埡鍐ㄥ箚濠电姵顔栭崰鏍晝閿曞倸纾块柕鍫濇媼閻掕姤銇勮箛鎾跺缂佺姰鍎查妵鍕即閻愭潙娅ら悶姘剧畵濮婂宕掑▎鎴М闂佺濮ょ划鎾崇暦閹惰棄唯闁宠桨鑳堕敍娑欑節閻㈤潧孝婵炲眰鍊濆浼村Ψ閳哄倻鍘介梺褰掑亰閸撴岸骞嗛崼銏㈢＜闁绘瑥鎳愮粔顕€鏌＄仦璇插鐎殿喗娼欒灃闁逞屽墯缁傚秹宕滆绾惧ジ鏌ｉ幇闈涘闁告柣鍊濋弻娑橆潩椤掑鍓跺Δ鐘靛仜閻楁挻淇婇幖浣肝ㄦい鏃囨缂傛捇姊绘担铏广€婇柛鎾寸箞閵嗗啴宕ㄩ婊€绗夐悷婊呭鐢鍩涢幋锔界厱婵犻潧妫楅顏呫亜閵夛妇鐭掗柡宀嬬到铻栧ù锝囨嚀绾板秴顪冮妶搴′簻缂佺粯锕㈤獮鏍亹閹烘垶宓嶅銈嗘尵婵妲愰崣澶岀瘈缁剧増蓱椤﹪鏌涢妸褎鏆い銏′亢椤︽挳鏌涢悩璇у伐妞ゆ挸鍚嬪鍕偓锛卞嫬顏圭紓鍌氬€风粈渚€顢栭崨顖欑剨闁告侗鍙庨崯鍛存煏婢舵稖绀嬪ù婊勭矋閵囧嫰骞樼捄鐩掋垽鏌涘Ο渚殶闁逞屽墲椤煤濡警娓诲ù鐘差儏閺勩儵鏌嶈閸撴岸濡甸崟顖氱鐎广儱顦伴鏍ㄧ箾鐎涙鐭嬬紒顔芥崌瀵鎮㈤悡搴濈炊闂佸憡娲﹂崜锕€螞閻愬绠鹃悗娑欘焽閻﹤顭胯閺咁偄危閹版澘绠婚悗娑櫭鎾绘⒑閸涘﹦绠撻悗姘嚇婵偓闁靛繈鍨婚敍婊勭節閵忥絾纭鹃柡鍫墴瀹曠敻鍩€椤掑嫭鈷戝ù鍏肩懅閹ジ鏌涜箛鏂嗩亪顢氶敐澶婄妞ゆ梻鈷堝濠囨⒑缂佹〞鎴︻敊閺嶎厼缁╅柕濞炬櫆閳锋帒霉閿濆洨鎽傞柛銈嗙懅缁辨帞绱掑Ο铏诡儌闂佸憡甯楃敮锟犮€佸☉姗嗘僵闁稿繒鍘ч惁婊堟⒒娴ｇ鎮戝ù婊€绮欏畷鏇㈠箥椤旇棄搴婇梺绯曞墲缁嬫帡鎮￠弴鐔翠簻闁规澘澧庣粙鑽ょ磼閳ь剟鍩€椤掆偓铻栭柣姗€娼ф禍濂告煕閵娿劍顏犻柟骞垮灩閳藉濮€閻樿尪鈧灝鈹戦埥鍡楃仭婵炲弶锕㈠畷褰掑捶椤撶偛鐏婃繝鐢靛Т濞村倿寮崘顔界叆婵犻潧妫楅顐ょ磼閻樺啿鍝烘慨濠呮缁辨帒螣閸濆嫅鏇熺箾鐎涙鐭嬬紒顔芥崌瀹曟椽鍩€椤掍降浜滈柟鍝勭Х閸忓苯顭胯閺佸寮婚悢纰辨晩闁靛鍎遍弸銈夋煟閹惧崬鍔﹂柡灞剧洴椤㈡洟鏁愰崶鈺冩毉闂備焦瀵х粙鎺楁儎椤栨凹娼栭柧蹇撴贡绾惧吋淇婇姘儓妞ゎ偄閰ｅ铏圭矙鐠恒劍妲€闂佺锕ョ换鍌炴偩閻戣棄绠ｉ柨鏇楀亾缁炬儳鍚嬬换娑㈠箣閻愬娈ゅ銈嗘⒐濞茬喎顫忓ú顏呭仭闁规鍠楅幉濂告⒑閼姐倕鏋傞柛搴ｆ暬楠炲啫顫滈埀顒勩€侀弮鍫濋唶闁绘柨鎼獮妤呮⒒娴ｇ瓔娼愰柛搴㈠▕閹椽濡歌閻棝鎮楅敐搴℃灍闁绘挻绋撻埀顒€鍘滈崑鎾绘倵閿濆骸澧伴柣锕€鐗撻幃妤冩喆閸曨剛顦ラ梺缁樼墪閸氬绌辨繝鍥ㄥ€婚柦妯猴級閵娧勫枑鐎光偓閸曨剙鍓﹀銈呯箰閹虫劗寮ч埀顒勬⒑濮瑰洤鐏叉繛浣冲嫮顩烽柨鏇炲€归悡鏇㈡煏閸繄鍑归梺顓у灣閳ь剝顫夊ú鏍偉閸忛棿绻嗘慨婵嗙焾濡茶螖閻橀潧浠︽い銊ワ工椤繒绱掑Ο鑲╃槇闁硅偐琛ラ埀顒冨皺閻╁孩绻濋悽闈涗粶闁活亙鍗冲畷鎰槈濞嗘劖鐝峰┑鐘绘涧椤戝棝鍩涢幋鐘电＜閻庯綆鍋掗崕銉╂煕鎼淬垹濮嶉柡宀€鍠栭幃鐑芥偋閸喐鍊锋俊鐐€栧ú鈺冪礊娓氣偓閵嗕礁螖閸涱厾顦板銈嗗姇椤戝啴宕濋幋锕€钃熼柕濞炬櫅缁秹鏌涢妷顔句虎闁规儳顕弧鈧梺闈涚箚閳ь剙纾导灞解攽椤旂》宸ユい顓炲槻閻ｇ兘骞掗幋鏃€鐎婚梺鐟扮摠缁诲倿鈥栨径鎰拺閻犲洤寮堕幑锝夋煟閻旂鈻曠€规洏鍔戦、娑橆煥閸涱厼绠氶梻鍌氬€烽懗鍫曞箠閹炬椿鏁嬫い鎾跺枑閸欏繑銇勯幘鍗炵仼缁炬儳顭烽弻鐔兼倷椤掆偓婢ь垱绻涚亸鏍ㄦ珚闁哄本绋戣灃闁告劑鍔嬬划璺何旈悩闈涗粶妞ゆ垵顦～蹇涙惞鐟欏嫬鐝伴梺鐐藉劥濞呮洟鎮橀幘缁樷拺缂佸顑欓崕宥夋煕婵犲啰绠為柣娑卞櫍瀹曟﹢濡搁姀锛勨偓濠氭⒑閻熸壆浠㈤柛鐕佸灦瀵煡鎮欓悜妯锋嫼闂佸憡绋戦敃锕傚箠閳ь剟姊虹粙鍨劉濠电偛锕獮鍡涘礋椤掍礁鍔呭銈庡亽閸樺墽绮诲鑸碘拺缂備焦锚婵箑霉濠婂嫮鐭掗柛鈹惧亾濡炪倖甯婇懗鑸垫櫠閻㈢鍋撶憴鍕缂佽妫濊棟閻庨潧鎽滅壕濂稿级閸碍娅呭ù鐘轰含閳ь剝顫夊ú鏍х暦椤掑嫧鈧棃宕橀鍡欙紲濠碘槅鍨跺Λ璺ㄨ姳閺夋垟鏀介柣妯虹仛閺嗏晛鈹戦鑺ュ唉闁轰礁鍟存俊鑸靛緞婵犲嫮鏋冨┑鐘灱閸╂牠宕濋弴鐘差棜濠电姵纰嶉悡娆撴煙鐟欏嫬濮囬柣鎾村姍閺屾盯鎮╅崣澶樻＆闂佸搫鏈惄顖氼嚕閹绢喖惟闁靛鍎哄鐐繆閻愵亜鈧呮嫻閻旂厧绀夐柟杈剧畱閽冪喖鏌ㄥ┑鍡╂Ц妞ゎ偄鎳橀弻宥嗘姜閹峰苯鍘℃繛瀵稿閸欏啴寮婚敐澶婎潊闁宠桨鑳舵导鍫㈢磽娴ｈ櫣甯涚紒璇茬墕椤曪綁顢曢敃鈧粻娑㈡煟濡も偓閻楀棝鍩€椤掑嫭鏁辩紒缁樼洴瀵爼骞嬮鐐插闂備礁鎼崐鐢稿磻閹剧粯鈷掑ù锝囩摂閸ゆ瑩鏌涢幋鐘虫珪鐎垫澘锕ョ粋鎺斺偓锝庡亜閳ь剝鍩栭幈銊ノ熼幐搴ｃ€愰梺姹囧€濈粻鏍蓟閺囷紕鐤€闁靛／鍜冪吹缂傚倷鑳舵繛鈧紒鐘崇墪椤曪綁宕奸弴鐐哄敹濠电娀娼уΛ宀勫箰閸愵喗鈷戦悹鍥ｂ偓铏仌闂佺顑嗛崝娆撳箚閳ь剚銇勮箛鎾跺⒈闁轰礁娲弻锝夊箛閻楀牊閿梺缁樻尵閸犳牠骞冨Δ鍐╁枂闁告洦鍓涢ˇ銊╂⒑閹肩偛濡兼繛纭风節閹即顢欓崲澶屽枛閹虫牠鍩￠崘璺ㄥ簥濠电姷顣藉Σ鍛村垂瀹曞洤鍨濇い鏍仦閸嬬喖鏌涢幇顓犮偞闁衡偓娴犲鐓熸慨妤€妫楅弸娑㈡煟韫囨岸鍝虹紒缁樼⊕瀵板嫮鈧綆鍓氶崚娑橆渻閵堝啫鐏柣妤冨Т閻ｇ兘骞掑Δ浣糕偓鐑芥煠绾板崬澧婚柛鐐垫暩缁辨捇宕掑顑藉亾閻戣姤鍊块柨鏇炲€甸埀顒婄畵瀹曞爼鍩￠崘褏鐟濆┑掳鍊х徊浠嬪疮椤愩倗妫憸鏃堝蓟濞戙埄鏁冮柨婵嗘川閻ｇ敻姊洪幎鑺ユ暠婵﹨宕靛Σ鎰板箳閹惧磭绐炲┑鈽嗗灠閹碱偊锝為埡鍛拺閻庡湱濯鎰版煕閵娿儲鍋ラ柕鍡曠閳诲酣骞橀崗鍛倞闂備礁鎲″ú蹇涘礉鐏炲墽顩查柣鎰靛墰缁♀偓闂傚倸鐗婇崘濠氬绩婵犳碍鐓ユ繛鎴灻埀顒佹倐閸╃偤骞嬮敂钘変汗濡炪倖妫侀崑鎰閸パ€鏀介柣鎰▕濡插綊鏌ｉ埡濠傜仸闁靛棔绶氬浠嬵敇閻愭妲伴梻浣稿暱閹碱偊宕板顑炶櫣绮欐惔鎾存杸闂佺粯顭堥婊冾啅閵夆晜鐓熸俊銈傚亾闁挎洦浜獮鍐晸閻樺弬銊╂煃閸濆嫬鈧宕㈤幖浣光拺闁告稑锕ゆ慨鍌炴煕閺傝法肖缂侇喖锕崺锟犲川椤旀儳骞堥梻渚€娼ч悧鍡椢涘☉銏犵疇闁搞儺鍓氶悡娑氣偓鍏夊亾閻庯綆鍓涜ⅲ缂傚倷鑳舵慨鐢告儎椤栨凹鍤曢柟缁㈠枟閸婄兘鏌嶉崫鍕偓濠氬焵椤戝灝宓嗘慨濠勭帛閹峰懘宕ㄦ繝鍐ㄥ壍闂佽崵鍋為崙褰掑磻婵犲倻鏆︽繝闈涱儏缁狅絾绻濋崹顐㈠婵炲牄鍔戝娲传閸曞灚效闂佹悶鍊х粻鎾诲箖閵忋倕绀傞柛蹇曞帶閸旀帡姊婚崒娆戣窗闁稿鎳愮划娆撳箻閸撲胶鐒奸梺鍛婃处閸嬧偓闁衡偓娴犲鐓ユ繛鎴灻鈺伱瑰鍐﹀仮闁哄本绋掔换婵嬪礃閵娧傜礉闁诲氦顫夊ú鏍礊婵犲倻鏆︽い鎰剁畱缁€瀣箹濞ｎ剙鐏繛鎻掝嚟閳ь剝顫夊ú姗€鏁冮姀鈥茬箚婵繂鐭堝Σ鐓庘攽閻愯尙澧︾紒鐘崇墪椤繐煤椤忓嫮顦梺鍦帛鐢﹦鑺遍悡搴樻斀闁绘劖褰冪痪褔鏌ｅΔ浣圭鐎殿噮鍋婇、姘跺焵椤掆偓椤繒绱掑Ο鑲╂嚌闂侀€炲苯澧い顓炴穿椤﹀綊鏌熼銊ユ搐楠炪垺淇婇悙顏勭仾缂佸鍨块崺銉﹀緞婵犲孩寤洪梺绯曞墲閻熴儲鎱ㄥú顏呪拻濞达絽鎲￠幆鍫㈢磼鐎ｂ晝绐旂€规洏鍨虹粋鎺斺偓锝庝簽閸橀亶姊洪崷顓炲妺妞ゃ劌妫濋幃锟犲即閵忊€斥偓鍫曟煟閹邦厼绲婚柍閿嬫閺岀喖宕橀幓鎺濅紑缂備浇椴哥敮妤呭箯閸涙潙浼犻柛鏇炵仛濮ｅ姊绘笟鈧褍煤閵堝洠鍋撳顐㈠祮闁靛棔绶氬鎾閻欌偓濞煎﹪姊洪崘鍙夋儓闁稿﹦鏁诲鎼佸川鐎涙鍘介柟鍏肩暘閸娿倕顭囬幇顓犵闁告瑥顥㈤鍡楀疾闂備胶绮Λ渚€宕戦幇顒傛殼濞撴埃鍋撴鐐寸墪鑿愭い鎺嗗亾濠碘€茬矙閹鎮介棃娴躲垺銇勯鈩冪《闁圭懓瀚伴幃婊兾熺紒妯侯伆闂傚倷鑳剁划顖滄暜閿涘嫮涓嶉柡宓本缍庣紓鍌欑劍钃卞┑顖涙綑閵嗘帒顫濋悡搴ｄ画缂傚倸绉撮敃顏勵潖濞差亜宸濆┑鐘插暟椤︺儵姊虹拠鑼鐎光偓閹间礁鏄ラ柕蹇曞Х閺嗗棝鏌涢弴銊ュ幋闁圭柉娅ｇ槐鎾诲磼濞嗘垵濡介梺鎸庡哺閺岋綀绠涘璺烘懙婵烇絽娲ら敃顏堛€侀弴銏狀潊闁绘瑢鍋撳ù鐘靛帶椤啴濡堕崱妯煎弳缂備胶绮崝娆撳春閻愬搫绠ｉ柨鏇楀亾闁绘劕锕弻鏇熷緞閸績鍋撳Δ鍛剮閹兼番鍔嶉埛鎺懨归敐鍛暈閻犳劧绻濋弻娑欐償濞戞ǚ鍋撳┑鍡╁殨濠电姵鑹炬儫閻熸粌閰ｅ鍐差煥閸喓鍘遍梺瑙勫礃鐏忣亪宕楀畝鈧惀顏堝礈瑜庡▍鏇㈡煃瑜滈崜娆戠不瀹ュ纾块梺顒€绉寸粻顖炴煙鏉堟儳顩柛娆愭礃閵囧嫰骞掑鍥獥濠电偛鐗呯划娆撳蓟閿濆绠涙い鎾跺仧缁佺兘姊洪崫鍕紨缂佹煡绠栨俊鐢稿礋椤栨凹娼婇梺鏂ユ櫅閸犳艾螞閸愵喗鍊甸悷娆忓缁€鍫ユ煕濡姴娲ら悡姗€鏌熸潏鍓х暠妤犵偑鍨虹换娑㈠幢濡櫣浠撮梺鍝勫閸庤尙鎹㈠┑鍫濇瀳濠㈣泛鐬奸敍鐔兼⒑缁嬫鍎愰柛銊ョ仢閻ｇ兘骞囬弶鍨敤濡炪倖鎸鹃崰搴㈢閸楃偐鏀介幒鎶藉磹閺囥垹鐤ù鐓庣摠閸庢绻涢崱妯诲鞍闁绘挻鐟╅幃妤呮偨濞堣法鍔告繛瀵稿閸曗晙绨婚梺鍐叉惈閹峰螞閹达附鐓欓柛娆忣槹閸婃劙鏌熼銊ユ搐闁卞洦绻濋棃娑氬ⅱ闁硅櫕鐗犲缁樻媴閻熸壋鏋欓梺琛″亾閺夊牃鏅滈弳婊堟煙閻戞﹩娈曠紒鐘冲浮濮婄粯鎷呴悷閭﹀殝缂備浇顕ч崐鍧楀箖瑜庣换婵嬪炊閼稿灚娅嗛梻浣虹帛椤洨鍒掗鐐茬；闁靛璐熸禍婊堟煛瀹ュ啫濡块柕鍡樺笚缁绘盯宕ｆ径瀣攭闂佸搫澶囬埀顒€纾弳鍡涙倵閿濆骸澧柛鈺佺焸閺屟呯磼濡厧鈪归梺闈涙鐢帡锝炲┑瀣垫晢濞达絽澹婂Σ閬嶆⒒娴ｉ涓茬紒韫矙婵″墎绮欏▎鐐稁濠电偛妯婃禍婊冾啅濠靛棌鏀介柣妯诲絻閳ь剙顭烽幃鐑藉蓟閵夛妇鍘介梺闈涚箚閺呮盯鎮橀懠顒傜＜缂備焦顭囩粻鐐烘煙椤旇宓嗘い銏＄懇瀹曞弶寰勭仦鑺ョ亪闂佸湱鍘у﹢閬嶅箟閹绢喖绀嬫い鎺戭槸閺咁參姊婚崒姘偓鐑芥倿閿曞倸绠栭柛顐ｆ礀绾炬寧銇勯弽顐粶缂佲偓婢跺备鍋撻獮鍨姎妞わ缚绮欏顐ｇ節閸ャ劎鍘搁梺鎼炲劗閺呮盯寮稿鍥╃＜閻犲洤寮堕ˉ銏ゆ煛瀹€瀣М妤犵偛娲畷妤呭传閵壯勬櫒闂傚倷绶氶埀顒傚仜閼活垱鏅堕娑氱闁告瑥顦遍惌鎺擃殽閻愭潙鐏村┑顔瑰亾闂侀潧鐗嗛幊鎰版偪閳ь剚淇婇悙顏勨偓鏍ь潖婵犳艾绠犻柟鎯ь嚟椤╂煡鏌ｉ幇闈涘闁告瑥绻戞穱濠囶敍濠婂啫浠橀柣銏╁灥閸╂牜鎹㈠☉銏犲窛妞ゆ挾濮岄妶澶嬬厓鐟滄粓宕滃棰濇晩闁哄稁鍘肩粣妤佷繆閵堝嫯鍏岀紒鐘冲劤閳规垿鎮╅幓鎺嗗亾婵犳艾姹查柨鏇炲€归悡鏇熶繆閵堝懎鏆欏ù婊嗩潐娣囧﹪骞撻幒鏂款杸缂備胶绮惄顖氱暦閸楃倣鐔兼惞闁稒妯婂┑掳鍊楁慨鐑藉磻濞戙垺鍋嬮柟鐐墯濞兼牜绱撴担鑲℃垶鍒婇幘顔界厱婵炴垶锕弨濠氭煕鎼淬垺灏柍瑙勫灴閹瑩鎳犻浣稿瑎闂備焦鎮堕崝蹇撐涢崟顖涘仼鐎瑰嫭澹嬮弨浠嬫煕椤愶絿鐭嬮柛鏇炲暣濮婅櫣绱掑Ο鍝勑曢梺鍛婃尰瀹€鎼佸箖闂堟稓鏆嬮梺顓ㄩ檮鐎靛矂姊洪棃娑氬婵☆偅绋掗弲鍫曨敆閸屾粎锛滈柣搴秵閸嬪懐浜搁悽鐢电＜妞ゆ柨澧界敮娑㈡煏閸剛绉€规洘锕㈤崺锟犲礃閵娿儳鐤勬繝鐢靛Х閺佹悂宕戦悙鍝勫瀭闂傚牊绋撻弳锔姐亜閹烘垵顏╅柛鎴犲█閺岋綁寮崶銉㈠亾閳ь剟鏌涚€ｎ偅灏甸柟鍙夋尦瀹曠喖顢楅崒銈喰氶梻鍌欑劍濡炲潡宕㈡總绋跨９闁割煈鍣崵鏇炩攽閻樺疇澹橀柣蹇撶－閳ь剝顫夊ú鏍洪敃鈧埢鎾诲即閵忥紕鍘介柟鍏兼儗閸ㄥ磭绮旈悽鍛婄厱闁规儳顕‖濂告煃椤忓棙鏆慨濠傤煼瀹曟帒鈻庨幇顔哄仒婵＄偑鍊栧ú姗€鎮ч悩鑼殾濞村吋娼欑粻铏繆閵堝倸浜鹃梺姹囧€濈粻鏍蓟閿濆憘鐔煎垂椤旂偓顕楅梻浣告惈濡绮婚幘璇茶摕闁靛鍎弨浠嬫煕閳╁喛渚涙俊顐ゅ仧缁辨挻鎷呯粙娆炬殺闂佺顑冮崐婵嬬嵁閸愵煈娼ㄩ柍褜鍓熼獮鍐ㄢ枎閹板墎鐭楀┑鐘绘涧濡瑩顢欓崟顐熸斀闁绘劘灏欓幗鐘电磼椤旇偐鐏辩紒杈╁仦缁绘繈宕掗妶鍡欑▉濠电姷鏁告慨鐢告嚌閸撗冾棜闁稿繗鍋愮粻楣冩煕閳╁厾顏堟倶閵夈儮鏀介柍銉ㄥ皺閻瑦鎱ㄦ繝鍛仩闁归濞€閸ㄩ箖鎼归銈勯偗闂傚倷鑳剁划顖炴偋濠婂牆鍌ㄧ憸鏃堝箖閹呮殝闁逛絻娅曢弬鈧┑鐘垫暩婵鈧凹鍣ｅ鍫曞箹娴ｅ厜鎷洪梺鍛婄箓鐎氼厼顔忓┑瀣厱閻庯綆鍋嗗ú鎾煙椤旂即鎴犳崲濠靛绀冪憸蹇曠不濮樿埖鈷戦梻鍫熺〒婢ф洜绱掔紒妯烘诞鐎规洘纰嶇€佃偐鈧稒顭囬崢閬嶆⒑缂佹ɑ纾荤紒鈧担鍦洸濞寸厧鐡ㄩ悡娆愩亜閺傚灝鎮戦柛瀣ㄥ劜閵囧嫰濮€閿涘嫭鍣梺閫涚┒閸旀垿鐛崶顒夋晜闁糕剝鐟﹂弲銊╂⒒閸屾艾鈧绮堟笟鈧獮鏍敃閵堝洨鐓撴繛鎾村焹閸嬫挾鈧娲橀崹鍨暦閻旂⒈鏁嗛柛灞诲€栫粊顐︽⒒娴ｇ懓顕滄繛鍙夌墵瀹曟劘銇愰幒鎾充簵闂佸搫娲ㄩ崑鎰板绩娴犲鐓熸俊顖濐嚙缁插鏌嶈閸撴稓鍒掗婊呯焿闁圭儤鍨熷Σ鍫熸叏濡じ鍚柨娑欑矌缁辨捇宕掑▎鎴濆濡炪値鍘煎ú銈囧弲闁诲海鏁哥涵鍫曞磻閹捐埖鍠嗛柛鏇ㄥ墰椤︻參姊洪崨濠庣劶闁搞儜鍛箣闂備胶顢婇幓顏嗙不閹达附鐓侀柛銉ｅ妿缁♀偓婵犵數濮撮崐褰捤夐悙娣簻閹兼番鍩勫▓婊勬叏婵犲偆鐓肩€规洘甯掗埢搴ㄥ箣椤撶啘婊堟⒒娴ｅ憡璐￠柍宄扮墦瀹曟垶绻濋崶銉㈠亾娓氣偓瀵粙顢橀悙鑼垛偓鍨攽閻愬弶顥為柛銊ョ秺閹繝骞樼紒妯锋嫼闁荤喐鐟ョ€氼剛绮堥崘顔界厱闁冲搫鍊绘晶鐢告煥濠靛牆浠辩€殿喗鎸虫慨鈧柨娑樺楠炲秹姊绘担铏瑰笡闁搞劍鍎奸幗顐︽⒑閹惰姤鏁遍柛鏃€鐟╅獮鍐ㄎ旈埀顒勶綖濠靛鏁囬柣鏃傚劋椤撳姊绘笟鈧埀顒傚仜閼活垱鏅舵导瀛樼厵闁惧浚鍋呯亸鎵磼閺冨倸鏋戠紒缁樼箞瀹曟儼顦撮柣娑栧劦濮婃椽宕崟顓涙瀱闂佸憡顭堥崑鎰垝閸儱閱囬柍鍨涙櫅娴滈箖鎮峰▎蹇擃仾缂佲偓閳ь剙鈹戦悙鑼勾闁告柨瀛╃粩鐔煎即閵忊€崇檮婵犮垼娉涢悧鍐磻閹捐绠抽柟鎼幗閸嶉潧顪冮妶鍡楃瑐闁绘帪绠撻獮鍐ㄢ枎韫囧﹥鏂€闂佺粯鍔曞鍫曞闯濞差亝鐓ラ柡鍥悘鑼偓娈垮枦椤曆囧煡婢跺á鐔兼煥鐎ｎ兘鍋撴繝姘棅妞ゆ劑鍨烘径鍕煙濮濆矈鍤欓柍缁樻崌椤㈡﹢濮€閳锯偓閹风儤绻涢弶鎴濇倯闁荤啙鍥х畺濠靛倸鎲￠悡鏇㈢叓閸ャ劍顥栭柤鏉挎健閺岋絽鈽夐崡鐐寸彎濡ょ姷鍋炵敮锟犵嵁婵犲洦鎯炴い鎰剁岛閹峰綊姊洪悷鏉挎Щ闁硅櫕鍔欏畷鐘诲冀椤撶偛宓嗛梺缁樺姈濠㈡﹢藟濮樿埖鈷掑ù锝堟鐢盯鏌涢妸銉ユ倯闁逛究鍔戞俊鑸靛緞婵犲嫸绱梻浣稿閻撳牓宕戦崱娆戜笉濡わ絽鍟悡娆撴倵閻㈡鐒鹃柛鎾冲船闇夐柣鎾冲椤ャ垽鏌″畝鈧崰鎰焽韫囨柣鍋呴柛鎰ㄦ櫓閳ь剙绉瑰铏圭矙濞嗘儳鍓抽梺鍝ュУ閸旀瑦淇婇悽绋跨妞ゆ牗姘ㄩ悿鈧梻浣稿閸嬪懎煤濮椻偓椤㈡挸顓兼径瀣ф嫼缂傚倷鐒﹁摫閻忓繒鏁婚弻娑㈡偐瀹曞洤鈷岄梺缁樹緱閸ｏ絽顕ｆ禒瀣垫晝闁靛繒濮锋禍浼存⒒娴ｄ警鐒剧紒缁樺姍钘濇い鏍ㄧ〒椤╂彃螖閿濆懎鏆為柣鎾存礋閺岀喖鏌囬敃鈧悘鐘绘煢閸曨喖浜圭紒杈ㄥ浮瀹曟粍鎷呴崨濠勪邯婵犳鍠栭敃锔惧垝椤栫偛绠柛娑卞枤閻熻銇勯弽銊х煀濠殿喖鍚嬫穱濠囨倷椤忓嫧鍋撻弽顓炲瀭闂傚牊鍏氬☉妯锋斀閻庯綆鍓欑粊锕傛⒑绾懏褰х紒鐘冲灴閹瑦绻濋崘锔跨盎闂佺懓鎼Λ妤佺妤ｅ啯鈷戦柦妯侯槸閺嗙喖鏌涢悩鍐插闁瑰箍鍨归埥澶愬閻樻鍚呮繝鐢靛仜濡鎹㈤幒鎾额浄闁兼祴鏅濈壕钘壝归敐鍛儓閺嶏繝姊洪悜鈺傛珦闁搞劏娉涢锝囨嫚濞村顫嶉梺闈涚箳婵兘顢欓幒妤佲拺闁兼祴鏂侀幏锟犳煕閹垮嫮鐣遍崡杈ㄣ亜閺囨浜惧┑顔硷龚濞咃綁宕犻弽顓炲嵆闁绘柨鎽滆ぐ鍛存⒒娴ｅ憡鎯堥柣妤佺矒瀹曟粌鈽夐姀鐘殿唹闂侀潧绻掓慨顓炍ｉ崼鐔稿弿婵鐗忛崚鏉棵瑰鍛壕缂佺粯鐩獮瀣倷閸偄娅ч梻浣虹帛鐢﹦鍒掑▎鎾宠摕闁挎繂顦介弫鍥煟閺冨牜妫戞い鎴濆€荤槐鎾存媴娴犲鎽甸柣銏╁灲缁绘繈鐛崘顔肩厸濞达絿鍎ゅ▓楣冩⒑閹肩偛鍔€闁逞屽墴楠炲繘鎮ч崼婊呯畾闂侀潧鐗嗗ú銈呮毄闂備胶顭堥鍡涙儎椤栨氨鏆︽い鏍剱閺佸啴鏌ㄩ弮鍥т汗缂佸绻愰埞鎴︽偐鐠囇冧紣闂佺粯顨呭Λ婵嬪箖閻愬搫鍨傛い鎰С缁ㄥ姊洪崷顓炲妺闁搞劎鏁婚、鏃堝煛閸愵亞锛滈梺缁樏壕顓熸櫠椤掑倻纾肩紓浣诡焽濞插鈧娲栧畷顒冪亽闂佹儳绻橀埀顒佺⊕椤㈡﹢姊虹拠鍙夊攭妞ゎ偄顦叅闁哄稁鍘旈崶顒侇棃婵炴垵宕▓銊╂⒑閸撴彃浜濇繛鍙夛耿瀹曟劙鎮滈懞銉㈡嫽闂佸壊鍋嗛崰宥囨闁秵鐓涢柛鈾€鏅涘顔芥叏婵犲倹鎯堥悡銈夋偣閸ヮ亜绱︾紒銊ㄥ吹缁辨挻鎷呴搹鐟扮闂佹寧纰嶉妵鍕敃閵忋垻顔婄紓浣介哺鐢帟鐏掗柣鐘叉搐濡﹪鍩€椤掍焦宕屾慨濠冩そ閹崇偤濡烽崘鍙ラ偗閽樻繃銇勯弽顐粶缂佺姵宀搁弻锝夊箛椤旂厧濡洪梺鎶芥敱閸ㄥ潡寮诲☉妯锋斀闁告洦鍋勬慨搴ㄦ煛瀹ュ繒绡€婵﹥妞藉畷銊︾節閸愶絾瀚绘俊鐐€戦崝宀勬晝椤忓牊鍋樻い鏇楀亾妤犵偛顑夐弫鍐焵椤掑嫸缍栭柛娑樼摠閻撳繘鏌涢锝囩畺闁搞倕娲弻娑㈡倷閼碱剙鐓熷┑顔硷攻濡炶棄螞閸愩劉妲堥弶鍫涘壉閵堝鈷戠紒瀣仢椤掋垽鏌熼崨濠傗枙闁绘侗鍠栬灃闁告侗鍘煎畵鍡涙⒑闂堟稓绠氭俊鐙欏洤绠繛宸簼閻撶喖鏌ｅΟ鍝勫笭闁煎壊浜弻娑㈠棘鐠恒劎鍔悗娈垮枟閹倸顕ｉ浣瑰劅闁规儳鐡ㄩ弶鍛婁繆閻愵亜鈧牕顫忔繝姘厱闁割偁鍎遍崥褰掓煟閺冨洦顏犵痪鎯у悑閵囧嫰寮崶褌姹楁繝鈷€浣哥伈闁哄苯绉烽¨渚€鏌涢幘鍗炲缂佽京鍋ゅ畷鍗炩槈濡偐宕舵繝寰锋澘鈧洟骞婃惔銊﹀亗闁哄洢鍨洪悡娆撴煟閹寸儑渚涙繛鍫熸礋閺岋綁骞樼€涙顦ㄩ梺闈涙搐鐎氫即鐛崶顒€鐓涘ù锝嗗絻娴滈箖鏌￠崶銉ョ仼闁告垹濞€閺岋繝宕橀妸褍顤€闂佺粯鎸哥换姗€寮诲☉銏犵労闁稿繒濯禍鐐靛垝椤撱垹绠虫俊銈勭贰濮婃寧绻濋姀锝呯厫闁告梹鐗犻幃锟犳偄閸濄儳顔曢梺绯曞墲椤ㄥ鈧碍婢橀湁婵犲﹤鐗忛悾鐑樻叏婵犲啯銇濇鐐寸墵閹瑩骞撻幒婵囩秱濠电姷鏁搁崑娑⑺囨导瀛樺剮妞ゆ牜鍋為弲鏌ユ煟閹邦剙顣抽柣銈傚亾婵犵數鍋為崹鍫曟偡閿曞倸纾挎い蹇撶墛閳锋垹绱掔€ｎ厽纭剁紒鐘靛閵囧嫰鏁傜拠鑼画缂備礁鍊哥粔鐢稿Χ閿濆绀冮柍鍝勫暙楠炲牓姊绘担鐟邦嚋婵☆偂绶氶、姘愁樄闁绘侗鍣ｅ浠嬪Ω閿濆嫮鐩庨梺纭呭亹鐞涖儵宕滃┑鍡€块柟娈垮枤绾捐偐绱撴担璇＄劷婵炴彃顕埀顒冾潐濞叉﹢銆冩繝鍥х畺闁斥晛鍟崕鐔兼煃閽樺顥炵紓宥嗗浮濮婂宕掑▎鎴М闂佸湱鈷堥崑濠囧箚鐏炴儳绶為悘鐐垫櫕缁涘繘姊虹粙鍖″姛闁哥姵鎸荤粋宥呪枎韫囧﹥鏂€闂佺粯鍔橀崺鏍亹瑜忕槐鎾愁吋娴ｉ晲澹曞┑鐘垫暩閸嬫盯骞忛幋鐘电濞撴埃鍋撴鐐插暣閸╁嫰宕橀妸褏鐛┑鐘垫暩閸嬫垿宕归崫鍕庢盯宕橀鑲╃暫闂佸啿鎼幊蹇浰夐崼鐔虹闁瑰鍎愬▓姗€鏌熺憴鍕缂佽鲸鎹囧畷鎺戔枎閹烘垵甯紓鍌欑贰閸ｎ噣宕归幎钘夋瀬妞ゆ洍鍋撻柡浣规崌閹晠宕ｆ径瀣撴岸姊绘笟鈧埀顒傚仜閼活垱鏅堕鐐寸厪闁搞儜鍐句純濡ょ姷鍋炵敮锟犵嵁鐎ｎ噮鏁嶆慨姗嗗墻濞碱剛绱撻崒姘偓椋庣矆娓氣偓钘濋梺顒€绉撮弸浣糕攽閻樺疇澹橀柦鍐枑缁绘盯骞嬪▎蹇曚痪闂佺顑嗛崝妤呭焵椤掑喚娼愭繛鍙夌墪鐓ら柕鍫濐槸閻撴洟鏌涢鐘茬伄缁炬崘妫勯妴鎺戭潩椤掍焦鎮欓梺鍝勵儐缁嬫帡濡甸崟顖ｆ晣闁绘ɑ褰冮獮瀣旈悩闈涗粶闁哥噥鍨崇划瀣箳閺傚搫浜鹃柨婵嗙凹缁ㄨ崵绱掗幇顓犫姇缂佺粯绻堥幃浠嬫濞磋翰鍨介幃妤€顫濋悡搴♀拫闂佺粯渚楅崰鏍敇閸忕厧绶為悗锛卞嫬顏烘繝鐢靛仩閹活亞绱為埀顒佺箾閸滃啰鎮奸柡渚囧枛閳藉濮€閿涘嫬骞堥梻渚€娼ч…顓犵不閹达箑绀夐柛顐ｆ礃閻撴瑧绱掑☉姗嗗剰濞存粎澧楅幈銊︾節閸愨斂浠㈠Δ鐘靛仜闁帮綁骞婇悙鍝勎ㄩ柨鏃囧Г椤斿繘姊婚崒娆戭槮闁规祴鈧剚娼栫憸鐗堝笚閸嬪鏌ｅΟ鍨惞鐎规挷绶氶弻娑㈩敃閻樻彃濮庨柟顖滃枛濮婃椽宕橀崣澶嬪創闂佺锕﹂幊鎾诲煝瀹ュ拋鐓ラ柛顐ゅ暱閹锋椽姊洪崨濠勨槈闁挎洩绲垮▎銏ゆ焼瀹ュ棛鍘卞┑鐐叉缁绘﹢宕ｉ崟顓涘亾鐟欏嫭绀冪紒璇插暙椤曘儵宕熼銈嗘畷闂侀€炲苯澧板瑙勬礋閹稿﹥绔熷┑鍡欑Ш闁轰焦鍔欏畷濂告偆娴ｅ嘲鎽嬮梻浣圭湽閸╁嫰宕归柆宥嗗剮妞ゆ牜鍋涢拑鐔兼煥濠靛棭妲搁柣鎾寸☉閳规垿鎮╅幓鎺嗗亾缂佹顩烽柟闂寸劍閳锋垹绱撴担濮戣偐娆㈤柆宥嗙厱闁绘ê鍟块崫娲煕閳规儳浜炬俊鐐€栫敮鎺楁晝閿斿墽鐭撻柣銏犳啞閻撴洟鏌ｅΟ璇插婵炲牊绮庨埀顒冾潐濞叉﹢宕濆▎鎾崇畺婵犲﹤鐗婇崵宥夋煏婢跺牆鍔楅柛瀣崌閹粙宕ㄦ繝鍕箺闂備線娼х换鍡椢ｉ崨鏉戠柈闊洦绋掗悡鐔兼煙閻戞ê鐏ラ柍閿嬫閺屽秷顧侀柛鎾村哺椤㈡瑩寮介鐐电崶濠电偞鍨惰彜闁哄绉归弻锟犲炊閳轰焦鐏侀梺宕囨嚀缁夋挳鍩為幋锔藉亹闁告瑥顦ˇ鈺呮⒑缁嬪尅韬柡鈧柆宥呂﹂柛鏇ㄥ枤閻も偓闂佸湱鍋撻崜姘闁秵鈷戠紒瀣儥閸庢劙鏌熼柅娑氱獢閽樻繈鏌熺紒銏犳灍闁绘挸鍟伴幉绋款煥閸繄顦梺缁樻煥椤ㄥ酣鎮為悾灞惧枑闁哄啫鐗嗙粻姘扁偓鍏夊亾闁告洦鍋嗛敍婊冣攽椤旂瓔鐒惧瀵割焾閳绘挻銈ｉ崘鈹炬嫼闂佸湱顭堝ù椋庣不閹炬番浜滈柨鏃囶嚙閻忥絿绱掗鑲╁ⅵ鐎规洘锕㈤崺鐐村緞閸濄儳娉块梻鍌欑閹碱偊宕愰幖浣瑰€舵繝闈涱儏缁犳牠鏌熺€电浠掔紒璇叉閳ь剛鎳撴竟濠囧窗閺嶃劍娅犻悗娑櫳戦崣?"
        elif scenario == "engineering_challenge":
            anchor += " 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏咁棃婵炴番鍎遍悧鎾愁嚕閹绘巻妲堥柕蹇曞Х椤㈠懘姊虹憴鍕姸濠殿喓鍊濋幃锟犳偄閸忚偐鍘甸梻渚囧弿缁犳垿鎮橀悩鐢电＜闁规彃顑呴々顒傜磼鏉堛劌娴┑鈩冩倐婵″爼宕堕埡鍐ㄥ箚濠电姵顔栭崰鏍晝閿曞倸纾块柕鍫濇媼閻掕姤銇勮箛鎾跺缂佺姰鍎查妵鍕即閻愭潙娅ら悶姘剧畵濮婂宕掑▎鎴М闂佺濮ょ划鎾崇暦閹惰棄唯闁宠桨鑳堕敍娑欑節閻㈤潧孝婵炲眰鍊濆浼村Ψ閳哄倻鍘介梺褰掑亰閸撴岸骞嗛崼銏㈢＜闁绘瑥鎳愮粔顕€鏌＄仦璇插鐎殿喗娼欒灃闁逞屽墯缁傚秹宕滆绾惧ジ鏌ｉ幇闈涘闁告柣鍊濋弻娑橆潩椤掑鍓跺Δ鐘靛仜閻楁挻淇婇幖浣肝ㄦい鏃囨缂傛捇姊绘担铏广€婇柛鎾寸箞閵嗗啴宕ㄩ婊€绗夐悷婊呭鐢鍩涢幋锔界厱婵犻潧妫楅顏呫亜閵夛妇鐭掗柡宀嬬到铻栧ù锝囨嚀绾板秴顪冮妶搴′簻缂佺粯锕㈤獮鏍亹閹烘垶宓嶅銈嗘尵婵妲愰崣澶岀瘈缁剧増蓱椤﹪鏌涢妸褎鏆い銏′亢椤︽挳鏌涢悩璇у伐妞ゆ挸鍚嬪鍕偓锛卞嫬顏圭紓鍌氬€风粈渚€顢栭崨顖欑剨闁告侗鍙庨崯鍛存煏婢舵稖绀嬪ù婊勭矋閵囧嫰骞樼捄鐩掋垽鏌涘Ο渚殶闁逞屽墲椤煤濡警娓诲ù鐘差儏閺勩儵鏌嶈閸撴岸濡甸崟顖氱鐎广儱顦伴鏍ㄧ箾鐎涙鐭嬬紒顔芥崌瀵鎮㈤悡搴濈炊闂佸憡娲﹂崜锕€螞閻愬绠鹃悗娑欘焽閻﹤顭胯閺咁偄危閹版澘绠婚悗娑櫭鎾绘⒑閸涘﹦绠撻悗姘嚇婵偓闁靛繈鍨婚敍婊勭節閵忥絾纭鹃柡鍫墴瀹曠敻鍩€椤掑嫭鈷戝ù鍏肩懅閹ジ鏌涜箛鏂嗩亪顢氶敐澶婄妞ゆ梻鈷堝濠囨⒑缂佹〞鎴︻敊閺嶎厼缁╅柕濞炬櫆閳锋帒霉閿濆洨鎽傞柛銈嗙懅缁辨帞绱掑Ο铏诡儌闂佸憡甯楃敮锟犮€佸☉姗嗘僵闁稿繒鍘ч惁婊堟⒒娴ｇ鎮戝ù婊€绮欏畷鏇㈠箥椤旇棄搴婇梺绯曞墲缁嬫帡鎮￠弴鐔翠簻闁规澘澧庣粙鑽ょ磼閳ь剟鍩€椤掆偓铻栭柣姗€娼ф禍濂告煕閵娿劍顏犻柟骞垮灩閳藉濮€閻樿尪鈧灝鈹戦埥鍡楃仭婵炲弶锕㈠畷褰掑捶椤撶偛鐏婃繝鐢靛Т濞村倿寮崘顔界叆婵犻潧妫楅顐ょ磼閻樺啿鍝烘慨濠呮缁辨帒螣閸濆嫅鏇熺箾鐎涙鐭嬬紒顔芥崌瀹曟椽鍩€椤掍降浜滈柟鍝勭Х閸忓苯顭胯閺佸寮婚悢纰辨晩闁靛鍎遍弸銈夋煟閹惧崬鍔﹂柡灞剧洴椤㈡洟鏁愰崶鈺冩毉闂備焦瀵х粙鎺楁儎椤栨凹娼栭柧蹇撴贡绾惧吋淇婇姘儓妞ゎ偄閰ｅ铏圭矙鐠恒劍妲€闂佺锕ョ换鍌炴偩閻戣棄绠ｉ柨鏇楀亾缁炬儳鍚嬬换娑㈠箣閻愬娈ゅ銈嗘⒐濞茬喎顫忓ú顏呭仭闁规鍠楅幉濂告⒑閼姐倕鏋傞柛搴ｆ暬楠炲啫顫滈埀顒勩€侀弮鍫濋唶闁绘柨鎼獮妤呮⒒娴ｇ瓔娼愰柛搴㈠▕閹椽濡歌閻棝鎮楅敐搴℃灍闁绘挻绋撻埀顒€鍘滈崑鎾绘倵閿濆骸澧伴柣锕€鐗撻幃妤冩喆閸曨剛顦ラ梺缁樼墪閸氬绌辨繝鍥ㄥ€婚柦妯猴級閵娧勫枑鐎光偓閸曨剙鍓﹀銈呯箰閹虫劗寮ч埀顒勬⒑濮瑰洤鐏叉繛浣冲嫮顩烽柨鏇炲€归悡鏇㈡煏閸繄鍑归梺顓у灣閳ь剝顫夊ú鏍偉閸忛棿绻嗘慨婵嗙焾濡茶螖閻橀潧浠︽い銊ワ工椤繒绱掑Ο鑲╃槇闁硅偐琛ラ埀顒冨皺閻╁孩绻濋悽闈涗粶闁活亙鍗冲畷鎰槈濞嗘劖鐝峰┑鐘绘涧椤戝棝鍩涢幋鐘电＜閻庯綆鍋掗崕銉╂煕鎼淬垹濮嶉柡宀€鍠栭幃鐑芥偋閸喐鍊锋俊鐐€栧ú鈺冪礊娓氣偓閵嗕礁螖閸涱厾顦板銈嗗姇椤戝啴宕濋幋锕€钃熼柕濞炬櫅缁秹鏌涢妷顔句虎闁规儳顕弧鈧梺闈涚箚閳ь剙纾导灞解攽椤旂》宸ユい顓炲槻閻ｇ兘骞掗幋鏃€鐎婚梺鍦劋閸ㄧ數鏁鐐粹拻濞达絼璀﹂悞鐐亜閹存繂鏆ｇ€规洘绻堥獮瀣攽閸喐顔曢梻浣告惈濞层垽宕归崷顓犳／鐟滄棃寮婚悢琛″亾濞戞鎴﹀煕閹扮増鐓熼幖娣灪閵囨繃鎱ㄦ繝鍐┿仢鐎规洦鍋婂畷鐔碱敆閳ь剟宕戝澶嬧拺闁硅偐鍋涙俊鍏肩節閳ь剚娼忛埡浣哥亰婵犵數濮电喊宥夊磻閸曨垱鐓曢煫鍥ㄨ壘娴滃綊鏌涘Ο鍏兼毈婵﹤顭峰畷鎺戭潩椤戣棄浜鹃柟闂寸贰閺佸銇勯幘鍗炵仼缂佲偓婢跺备鍋撻獮鍨姎妞わ缚鍗抽幃锟犳偄閸忚偐鍘甸梺璇″瀻鐏炶姤顔嶉梻浣烘嚀閸熷潡骞婂鈧璇差吋閸偅顎囬梻浣告啞閹稿鎯勯鐐靛祦濠电姴娲ょ粻濠氭煕閵婏妇鈽夊ù婊呭亾閹便劌顫滈崱妞剧盎閻庤鎸稿Λ娑㈠焵椤掑喚娼愭繛鍙夛耿瀹曞綊宕滄担鐟板簥濠电娀娼ч鍛存倷婵犲嫭鍠愰煫鍥ㄧ⊕閺咁剟鏌ｉ弬鍨倯闁抽攱鍨块弻娑樷攽閸℃浠奸梺鍝勬閿曨亪寮诲☉姘ｅ亾閿濆骸浜濈€规洖鐭傞弻锛勪沪閻愵剛顦伴悗瑙勬礃閸庡ジ藝閸欏浜滈煫鍥风到楠炴牠鏌嶇憴鍕伌妞ゃ垺鐟╅幃閿嬶紣娴ｅ壊妫滈梻鍌氬€搁崐椋庣矆娓氣偓閹潡宕堕‖顒佺洴瀹曠喖顢涘杈╂瀮闂備浇顫夊畷姗€顢氳閹偤宕归鐘辩盎闂佺懓鎼Λ妤佺閹€鏀介柣鎰仯閳ь剙顑囬幑銏犫攽閸♀晛娈ㄦ繝鐢靛У绾板秹宕戦崟顓犳／闁瑰嘲鐭傞崫娲煛閸涱亝娅婇柡宀嬬秮閹垽宕妷锕€娅戦梺璇插閸戝綊宕ｉ崘顔肩畺闂傚牊渚楀鈺呮煠閸濄儺鏆柟閿嬫そ閺岋綁鎮╅崣澶岊槺闂侀€炲苯澧叉繛鍛礋閹﹢宕卞▎鎴狅紳婵炴挻鑹惧ú銈夊几閻斿吋鐓熼柣鏂垮级濞呭﹪鏌ｅ☉鍗炴珝鐎规洘锕㈤崺锟犲礃閻愵剛銈梻浣筋嚙閸戠晫绱為崱娑樼；闁圭儤鍤﹀☉銏犵闁靛鍨洪弬鈧梻浣虹帛閸旀牕顭囧▎鎾村€堕柨鏂款潟娴滄粍銇勯幘璺轰沪闁哥姵锕㈤弻鐔碱敊閹冨箣婵犳鍠掗崑鎾绘⒑閹稿海鈽夐悗姘煎櫍閹線宕奸妷锔规嫼濠殿喚鎳撳ú銈夋倶閸欏绠惧ù锝呭暱閸燁垰袙閸曨偀鏀介柨娑樺娴滃ジ鏌涙繛褍鎳愮粈濠囨煃瑜滈崜姘┍婵犲浂鏁冮柕蹇曞娴犲ジ鎮楃憴鍕碍閻庢碍婢橀～蹇撁洪鍕獩婵犵數濮寸€氀勬叏閸パ€鏀介柣鎰絻閹垿鏌ｉ悢婵嗗閻濆爼鏌￠崶鈺佹灁缂佲檧鍋撴繝娈垮枟閿曗晠宕㈡ィ鍐ㄥ偍闂侇剙绉甸埛鎴︽煛閸屾ê鍔滄繛鍛嚇閺屾稑鈻庨幇顒€顫掑Δ鐘靛仜椤戝懘鍩為幋锕€绀冮柍鍝勫暊閸嬫挸煤椤忓應鎷虹紓鍌欑劍閳笺倝顢旈崼婵嗗亶闂佸搫绋侀崑鍛暦閺屻儲鐓曢柍鈺佸暟閳洟鏌ｉ幘宕囩闁哄本鐩、鏇㈡晲閸モ晝鏆梻渚€娼荤紞鈧い顐㈩樀婵＄敻宕熼鍓ф澑闂佹寧绻傜€氫即宕戝Δ鍛拺闁告繂瀚悘閬嶆煕閻樺磭澧柣锝呭槻椤粓鍩€椤掑嫬绠犻柣妯虹仛瀹曞銆掑鐓庣仧缂佽鲸妫冨濠氬磼濞嗘埈妲梺姹囧€曞ú顓㈡晲閻愭潙绶為柟閭﹀墮閻庮參姊虹粔鍡楀濞堟梻绱掗悩宕囧⒌闁哄苯绉瑰畷顐﹀礋椤掆偓椤庢盯姊烘潪鎵槮闁哥喐鎸冲濠氬Ω閵夈垺鏂€闂佺硶鍓濋敋妞ゅ孩鐩娲焻閻愯尪瀚板褜鍠氱槐鎺旂磼濮楀牐鈧寧顨ラ悙鎻掓殭閾绘牠鏌涘☉鍗炵仩缂佷緤绠撳娲礈閼碱剙甯ラ梺鍝ュУ閻楁骞堥妸锔藉劅闁抽敮鍋撻柡鈧禒瀣厽闁归偊鍨伴惃鐑樼節閳ь剟骞橀鐣屽幈闂佸搫鍟犻崑鎾绘煕閵娿儲鍋ラ柣娑卞櫍瀹曞崬螣閼测晜鍤岄梻渚€鈧偛鑻晶顕€鏌ｉ敐澶嬫暠缂佽櫣鏅划娆戞嫚娣囧崬濮傞柡灞诲姂瀵潙螖閳ь剚绂嶆ィ鍐┾拺闂侇偆鍋涢懟顖涙櫠娴煎瓨鐓涘ù锝呭閻撳吋顨ラ悙鎻掓殭闁伙綇绻濋獮宥夋惞椤愩倐鍋撴繝姘棅妞ゆ劑鍨烘径鍕煙鐏忔牗娅嗙紒鍌涘浮瀹曟粏顦寸痪鎹愭闇夐柨婵嗘缁茶霉濠婂牏鐣烘慨濠冩そ瀹曟粓骞撻幒宥囨寜闂備胶顭堢€涒晠鎮￠敓鐘茬畺闁跨喓濮撮崡鎶芥煏韫囧鐏╃憸鏉垮濮婃椽骞栭悙鎻掑闂佸憡鏌ㄧ粔褰掑箖濡や胶闄勯柛娑橈功閸樼敻鏌ｆ惔锝嗘毄妞ゎ厼鐗婄粋鎺曨樄闁哄苯绉归幃鐑藉箥椤斞佸灲閺屽秶鎲撮崟顐や紝闂佽鍠掗弲鐘茬暦閿濆棗绶為悗锝庡亜閳ь剟顥撶槐鎾诲磼濞嗘帒鍘℃繝娈垮枤閸忔﹢鐛繝鍥х缂備焦顭囬悾鎶芥⒒閸屾瑧鍔嶉悗绗涘懏宕查柛宀€鍋為崑瀣煕閳╁啰鈽夐柣鎺戠仛閵囧嫰骞嬮敐鍡欍€婇梺娲诲幗閻熴儵鍩為幋锕€鐒洪柛鎰典簼閹叉瑥顪冮妶蹇涙濠电偛锕璇测槈閵忊€充汗闂佸憡鍔栬ぐ鍐綖閹烘鈷戠紓浣股戦幆鍕煕鐎ｎ亷宸ラ柣锝囧厴瀹曞ジ寮撮悙宥佹櫊閺屻劑寮崶鑸电秷闁诲孩鐭划娆忣潖缂佹ɑ濯撮柛娑橈龚绾偓闂備礁鎲￠…鍡涘川椤栨粠妲稿┑鐘垫暩婵挳宕戦崱妤婄劷闁哄诞鈧弨浠嬫煟濡櫣鏋冨瑙勵焽閻ヮ亪骞嗚閹垿鏌熸笟鍨妞ゎ偅绮撳畷鍗炍旈埀顒勭嵁鐎ｎ喗鈷戠紒瀣儥閸庢劙鏌熺粙娆剧吋閽樻繈鏌ｅΔ鈧悧濠囧磿閻斿吋鐓ユ繝闈涙瀹告繈鏌涢弮鍥ㄧ【闁宠鍨块幃娆戔偓娑櫭棄宥夋⒑缁洘娅呴柛鐔告綑閻ｇ兘骞嬮敃鈧粻濠氭煙绾板崬骞楁い鏃€妫冨铏圭磼濡搫顫屽┑鈽嗗灠閿曘倛鐏掗梺閫炲苯澧存慨濠勫劋濞碱亪骞嶉鐓庮瀴闂備礁婀遍幊鎾趁洪銏㈠祦闁告劦鍠栭悡娑㈡煕濞戝崬鏋涙繛鍫涘€曢—鍐Χ閸℃鐟ㄥ銈忓瘜閸ㄨ泛顕ｉ銉ｄ汗闁圭儤鎸撮幏濠氭⒑缁嬫寧婀伴柣鐔濆泚鍥晝閸屾稓鍘甸柣鐘叉厂閸涱垽绱电紓鍌氬€搁崐褰掑箲閸パ呮殾缂佸顕抽弮鍫濈劦妞ゆ帒鍊搁ˉ姘舵煕瑜庨〃鍡涙偂濞嗘挻鐓欐い鏍ㄧ⊕缁惰尙鎮鑸碘拺缂佸鐏濋銏°亜閵娿儻韬€殿喖顭烽幃銏ゆ偂鎼达綆鍞归梻浣哥秺閸嬪﹪宕滃☉銏犲偍妞ゆ劧闄勯埛鎴︽煕濠靛嫬鍔氶弽锟犳⒑閸涘﹥鈷愰柣鐔叉櫅椤曪絾绻濆顓熸珳闂佸憡绋戦崐鐟拔涢崘顔兼槬闁逞屽墯閵囧嫰骞掗幋婵愪痪闂佺顑呴澶愬蓟濞戙垹鐒洪柛鎰典簼閸ｎ喚绱撴担鍝勑ｆ俊顐㈠暣瀵鎮㈤崗鐓庘偓缁樹繆椤栨繍鍤欓梻澶婄У缁绘稓鈧稒锚濞堢娀鏌涙繝鍐⒈闁瑰箍鍨归埞鎴犫偓锝庡亽濡啫鈹戦悙鏉戠仴鐎规洦鍓熷畷婊堟焼瀹ュ棌鎷虹紓浣割儏鐏忓懎顔忛妷鈺傜厽闊洦鏌ㄩ崫娲煏閸℃鏆ｅ┑锛勫厴閸╋繝宕掑锝呬壕闁绘垼濮ら悡鐘电棯閺夊灝鑸归柛妯绘倐閺屟嗙疀閹捐寮板┑顔硷攻濡炶棄鐣烽妸锔剧瘈闁告劧绲剧€氳崵绱撴担鍝勪壕婵犮垺顭囩划鏃傛喆閸曨亞绠氶梺姹囧灮椤牏绮堢€ｎ偁浜滈柡宥冨妿閳洘绻涢崨顓燁棦婵﹥妞藉畷婊堟嚑椤掆偓鐢儵姊洪崫銉バｉ柣妤佺矌閸掓帗绻濋崶鑸垫櫔闂侀€炲苯澧存鐐插暙铻栭柛鎰ㄦ櫅閺嬪倿姊洪崨濠冨闁告挻鐩棟闁靛鍎弨浠嬫煟閹邦厼绲荤紒鐙欏洦鐓ラ柡鍥悘鏌ユ煟濞戝崬娅嶇€规洖宕埥澶娢熼懖鈺傜秮闂傚倷绀佹竟濠囧磻閹烘绀堟繛鎴炴皑閻瑩鐓崶銊︽儎婵炴挸顭烽弻鏇㈠醇濠靛浂妫為梺璇茬箺妞村摜鎹㈠☉娆忕窞閻庯綆鍋嗛ˇ浼存⒑鐠団€崇仩閻庢凹鍙冮獮鍡涘籍閸惊鈺呮煥閺冨浂娼愰悗姘虫閳规垿鎮欓懜闈涙锭缂備浇寮撶划娆撶嵁婢舵劖鏅搁柣妯垮皺閻ｉ箖姊洪崜鎻掍簽闁哥姵鎸剧划缁樸偅閸愨晛浠梺鎼炲劚濞层倝骞婇幇鏉挎辈闁靛牆顦伴埛鎴︽⒒閸喓鈯曟い銉︾矒閺屾盯鎮㈤崨濠勭▏闂佷紮绲块崗妯讳繆閹间礁鐓涘┑鐘插暞濞呮挾绱撻崒姘偓鐑芥⒔瀹ュ鍨傛繛宸簼閻撱儵鏌曢崼婵囧櫝闁衡偓娴犲绠抽柟鎯版绾惧湱鎲歌箛鎿冨殫濠电姴鍟伴々鐑芥倵閿濆簼绨介柡灞界墕椤啴濡堕崱娆忊拡闂佺顑嗛惄顖炲箖閿熺姴鍗抽柕蹇ョ磿閸樼敻鏌℃径濠勫ⅵ缂佺姵鐗曢‖濠囶敋閳ь剟寮诲澶嬬叆閻庯綆浜濈拠鐐烘⒑閸濆嫭婀伴柣鈺婂灦閵嗕線寮撮姀鈩冩珳闂佹悶鍎撮崺鏍р枔鐟欏嫮绡€闁汇垽娼ф禒婊堟煙閸愭煡顎楅悡銈嗐亜閹惧崬鐏╅柦鍐枛閺岋綁寮崒妤佸珱闂佽桨绀侀敃锔炬閹烘嚦鏃堝焵椤掑嫬绠规い鎰剁悼椤╅攱銇勯弴妤€浜惧┑顔硷攻濡炶棄鐣烽锕€绀嬫い鎺嶇劍鐎氬磭绱撻崒娆戭槮妞ゆ垵妫濋幃褍顭ㄩ崨顓炵亰闁荤姴娲︾粊鏉懳ｉ崼銉︾厪闊洦娲栧暩闂佹椿鍋勭€氭澘顫忛搹瑙勫枂闁告洦鍋勬慨銏ゆ⒑閸涘鎴犲垝閹惧磭鏆﹂柟杈剧畱缁犲鏌ら幖浣规锭缁剧虎鍨跺娲濞戣京鍔搁梺鎼炲姀椤绮嬪澶嬪€锋い鎺戝€婚鏇㈡⒑閸撴彃浜濈紒璇插缁傛帡濮€閿涘嫮顔曢梺鍛婁緱閸ｎ垶鎳撻崸妤佺厸閻忕偛澧介妴鎺楁煃瑜滈崜銊х礊閸℃顩叉繝濠傜墱閺佸倹銇勯幘璺烘瀭濞存粍绮撻弻鏇＄疀婵犲倻鍔撮梺鐟邦嚟婵妲愰敃鍌涚厽闁挎繂鎳愰悘閬嶆煟椤撶喓鎳囬柡灞剧洴閳ワ箓骞嬪┑鍥╀壕闂備胶绮粙鍫ュ疾濠婂嫮鈹嶅┑鐘叉处閸婇攱銇勮箛鎾愁仱闁稿鎹囧浠嬵敇閻旇渹缃曟繝寰锋澘鈧洟宕导瀛樺剹婵炲棙鎸婚悡娆撴煟閹寸儑渚涙繛鍫熸礋閺屾稓鈧急鍕彋闂佸搫鐭夌紞渚€鐛€ｎ喗鏅查柛娑樻噺閹瑰洭寮诲澶嬬叆閻庯綆浜為悷銊╂⒒閸パ屾█闁哄被鍔岄埞鎴﹀幢濡儤顏￠梻浣告憸閸犳捇宕戦妶澶婅摕婵炴垯鍨洪崑鍕煕濠靛棗顏ф俊鍙夊姍濮婃椽宕崟顒佹嫳闂佺儵鏅╅崹浼搭敋閿濆鏁嗛柛鏇ㄥ墮閳ь剛鍏橀弻娑樷枎韫囷絾笑濠电偛鎷戠徊璺ㄦ閹惧瓨濯撮柣锝呰嫰閻楁岸姊虹粙鍖℃敾缂佽鐗嗛锝嗙節濮橆儵褍顭跨捄鐚村姛闁伙絾濞婂娲捶椤撶偛濡洪梺鎼炲妼閻忔岸骞堥妸鈺侇潊闁绘瑢鍋撴繛鎾愁煼閺屾洟宕煎┑鍡忓亾閻熸壋鏋嶉柛鈩冪懄閸犳劙鏌℃径濠勪虎闁哄棎鍨介弻锝堢疀閹捐櫕娈诲┑顔硷攻濡炰粙鐛幇顓熷劅闁挎繂娲ㄩ弳銈夋⒒娴ｇ儤鍤€闁哥喎娼￠弻濠囨晲閸滀礁娈ㄩ梺瑙勫劶婵倝宕愰悜鑺ョ厽闁瑰鍎愰悞浠嬫煕濡潡鍝虹紒缁樼箞閹粙妫冨ù韬插灲閺屾稒绻濋崒銈囧悑閻庤娲樺浠嬪极閹邦厼绶為悗锝庡墮楠炴劙鏌ｆ惔鈥冲辅闁稿鎹囬幃妤呮晲鎼粹€愁潾閻炴熬闄勬穱濠囧Χ閸ヮ灝銉╂煕鐎ｎ偆鈽夐悡銈嗐亜閹垮啯濞囬柍褜鍏涚粈渚€鍩ユ径濞㈢喖鏌ㄧ€ｅ灚缍屽┑鐘愁問閸犳褰犻梺绋垮瘨閸ｏ絽鐣烽幋锕€绠婚悹鍥皺閻も偓婵＄偑鍊栭幐鐐叏閻戠瓔鏁婇柡鍥ュ灪閻撶喖骞栧ǎ顒€鐏柍顖涙礃閵囧嫰顢橀悙鏉戞灎闂佽鍨伴張顒傛崲濠靛绀嬫い鎾跺缁辨娊鏌ｆ惔锛勭暛闁稿酣浜堕獮蹇涘箣閿旀儳褰嗗銈嗗笒閸婄敻宕戦幘鏂ユ灁闁割煈鍠楅悘鍫濐渻閵堝骸骞橀柛蹇斆锝夘敃閿曗偓缁犳稒銇勯幘璺轰户缂佹劗鍋ら弻锝嗘償椤栨粎校婵炲瓨绮嶉悷褔鎳炴潏銊х瘈婵﹩鍘搁幏缁樼箾鏉堝墽鍒伴柟璇х節瀹曨垶鎮欓悽鐢碉紲闂佸憡绻傜€氼參宕戦妷褉鍋撶憴鍕婵炶尙鍠栭悰顔芥償閵婏箑娈熼梺闈涱槶閸庝即鎯€椤忓牊鈷掑ù锝呮啞閸熺偞绻涚拠褏鐣电€规洖缍婇弻鍡楊吋閸涱垰骞堥梻浣侯攰閹活亪姊介崟顖涘亗闁哄洨鍠撶弧鈧梻鍌氱墛缁嬫帡藟濠婂嫨浜滈煫鍥风到娴滀即鏌″畝瀣М妤犵偞甯″鎾偄閹巻鍋撴繝鍕＝濞达絼绮欓崫娲偨椤栨粌浠ф俊鍙夊姍楠炴帡骞婂畷鍥ф灈闁硅櫕鐗犻崺锟犲礃閳哄偆鍟岄梻鍌氬€搁崐宄邦渻閹烘梹顫曟い鏃€鍎崇欢銈夋煕瑜庨〃鍛矆閸屾稒鍙忔俊鐐额嚙娴滄儳螖閻橀潧浠滈柛鐔风摠閹便劑鍩€椤掑嫭鐓忛柛顐ｇ箖閸ｈ姤銇勮熁閸涱垳锛滈梺缁樺姦閸撴瑩顢撳鍐炬富閻庢稒蓱閸婃劙鎸婇悢鍏肩厱妞ゆ劑鍊曢弸鏃傜磼閳锯偓閸嬫捇姊绘担鍦菇闁搞劏妫勯…鍥槼缂佸倹甯￠弫鍐磼濞戞艾骞堥梻渚€娼ч…鍫ュ磿閹惰棄鏄ラ柨婵嗩槹閻撴瑦銇勯弽銊︾殤闁绘帒鎲￠妵鍕閳ュ啿鎽甸梺绯曟杹閸嬫挸顪冮妶鍡楀潑闁稿鎹囬弻锝夋晲閸パ冨箣濡炪們鍨哄ú鐔煎春濡ゅ懏鍤嶉柕澶涘瘜濡啴姊虹化鏇熸澒闁稿鎸搁—鍐Χ閸℃鐟ㄩ柣搴㈠嚬閸撶喖骞冮垾鎰佹建闁逞屽墴瀵鎮㈤崨濠勭Ф婵°倧绲介崯顖烆敁瀹ュ鈷戠紒瀣皡闊剚銇勯妷锔藉磳闁糕斁鍋撳銈嗗笒閸婂綊宕甸埀顒佺節閵忋垺鍤€闁挎洦浜滈悾閿嬪閺夋垵鍞ㄩ悷婊冾樀瀵悂寮崼鐔哄幘闂佸憡绺块崕鏌ュ汲閳哄啰纾奸柍閿亾闁稿鎸荤换婵嬫偨闂堟稐绮堕梺缁橆殔濡繈骞冨Ο琛℃斀閻庯綆浜滈崵鎴︽⒑闂堟稓澧曟い锔垮嵆閹€斥槈濡繐缍婇弫鎰板川椤斿吋娈橀梻浣烘嚀瀵爼骞冮崒鐐茶摕婵炴垯鍨圭粻鎶芥煙閹咃紞闁荤喆鍔戝铏光偓鍦閸ゆ瑩姊虹敮顔剧М闁绘侗鍠栬灒闁惧繗顫夊▓楣冩⒑閹肩偛鍔ユ繛澶嬬洴瀵偅绂掔€ｎ偀鎷婚梺绋挎湰閻熝囁囬敃鍌涚厵缁炬澘宕禍鎵偓瑙勬处閸ㄥ爼銆侀弴銏℃櫇闁逞屽墰婢规洟鎮烽幍铏杸闂佺粯锚绾绢參銆傞弻銉︾厱閻庯綆浜滈埀顒€娼″濠氭偄閻撳海鐣鹃悷婊勭矒瀹曠敻鎮㈤搹鍦紲闂佹娊鏁崑鎾绘煕鐎ｎ偅宕屾慨濠勭帛缁楃喖鍩€椤掆偓椤洩顦虫い銊ｅ劥缁犳盯寮撮悙鐢电摌濠电偛顕慨鎾敄閸℃稑纾婚柛宀€鍋為悡娆撴煙濞堝灝鏋涙い锝呫偢閺岋綁骞樼€涙顦伴梺鍝勭焿缁绘繂鐣峰鈧弫鎰板川椤掆偓椤ユ艾鈹戦悩鍨毄闁稿濮锋禍绋库枎閹惧磭鐛ラ梺鍝勭▉閸樻儳鐣垫笟鈧弻娑㈠箛闂堟稒鐏嶉梺绋匡功閸忔﹢寮诲☉妯锋斀闁糕剝顨忔禒濂告⒑鐠囨彃鐦ㄩ柛妯恒偢閳ユ棃宕橀鍢壯囨煕閳╁喚娈旀い顐㈠缁绘繂鈻撻崹顔界亪缂佸墽铏庨崣鍐箠閻愬瓨缍囬柕濞у懐妲囨繝娈垮枟閿曗晠宕㈤幖浣哥婵炲樊浜濋埛鎴︽煠婵劕鈧洟寮搁弬娆剧唵鐟滃酣銆冩繝鍥╁祦闁糕剝绋戦柋鍥煏韫囧鐏柨娑欑矋缁绘繈濮€閿濆棛銆愰梺鎸庢磸閸婃繈濡撮崒姘辨殾闁搞儮鏅濋敍婊冾渻閵堝棙顥嗙€规洜鏁哥划濠冾槹鎼达絿锛滈梺缁樏壕顓灻虹€电硶鍋撳▓鍨灍闁瑰憡濞婇獮鍐煛閸愩劍鐎虫繝銏ｆ硾閼活垳鑺遍妷鈺傗拻闁稿本鑹鹃埀顒€鍢查湁闁搞儺鍓ㄧ紞鏍ь熆鐠鸿櫣鏄傚ù婊冪秺閺屾盯骞囬棃娑欑彯闂佽桨绀佺€氫即寮诲☉銏犖ㄩ柕蹇婂墲閻濇牠姊哄ú璇插箺闁荤啿鏅犻獮鍐亹閹烘垹鍊為梺鍐叉惈閸婃悂鍩㈣箛娑欑厵闁稿繗鍋愰弳姗€鏌涢弬璺ㄧ劯闁诡喗鐟︾换婵嬪礋椤掆偓閺嬫垵鈹戦悩缁樻锭妞ゆ垵娲畷锝夊即閻旂繝绨婚梺鐟版惈缁夌懓顬婂畡鎳婄懓顭ㄩ崟顓犵厜闂佸搫鏈ú婵堢不濞戙垹唯鐟滃繘鏁嶉悢鍏尖拺閻庡湱濮甸ˉ澶嬨亜閿斿灝宓嗗┑锛勬暬瀹曠喖顢涢敐鍡樻珖闂備焦瀵х换鍌毭洪妸鈺傚仾闁告洦鍨遍崐鐢告偡濞嗗繐顏紒宀冩硶缁辨帡骞撻幒鍡椾壕闁绘棁妗ㄩ懜顏堟⒒閸屾瑧顦︽繝鈧柆宥佲偓锕傚醇閳垛晛浜鹃柛顭戝亜濞搭噣鏌涢埞鎯т壕婵＄偑鍊栫敮濠勬閳ユ枼鏋旈柡鍥╁Х绾捐偐绱撴担璇＄劷缂佺姷鍋ら弻鐔碱敊閼姐倗鐓撳┑鈽嗗亜閸燁偊婀侀柣鐘辩濠€杈╃矙婵犳碍鐓忛柛銉戝喚浼冮悗娈垮櫘閸ｏ綁宕洪埀顒併亜閹烘垵顏柛瀣儔閺岋絽螣閸喚姣㈤梺鍝勬４缁犳垿婀侀梺绋跨箰閸氬绱為幋锔界厱闁硅埇鍔屾禍鎯р攽閿涘嫬浜奸柛濞垮€濆畷鏇㈠煛閸涱厙褔骞栧ǎ顒€鐏紒澶愭敱娣囧﹪鎮欓鍕ㄥ亾瑜庢穱濠囧炊閵婏附鐝峰┑掳鍊曢幊搴ｇ不濮樿埖鐓涢柛鎰╁妿婢ф洘銇勯銏″殗闁哄苯绉瑰畷顐﹀礋椤愮喎浜鹃柤濮愬€楅惌娆撴煙閹殿喖顣奸柍閿嬪浮閺屾稓浠﹂崜褎鍣銈忚闂勫嫮鎹㈠┑瀣劦妞ゆ帒瀚悞鑲┾偓骞垮劚閹虫劙鏁嶉悢鍏尖拺闂傚牊绋撴晶鏇熴亜閿旇寮柛鈹惧亾濡炪倖宸婚崑鎾绘煕閻斿憡缍戦柣锝囧厴婵℃悂鍩℃繝鍐╂珫婵犳鍠楅敋闁告艾顑夎棢闁跨喓濮甸埛鎺懨归敐鍕劅闁绘帒澧界槐鎺旂磼濮楀棙鐤侀悗瑙勬礃閸ㄥ潡鐛崶顒夋晩闁绘挸宸╁鑸碘拺闂侇偆鍋涢懟顖涙櫠鐎涙ɑ鍙忓┑鐘插暞閵囨繄鈧娲樼划鎾诲箠閻樻椿鏁嗛柍褜鍓涢弫顕€濡烽埡鍌楁嫼缂備礁顑嗛娆撳磿韫囨稒鍊垫慨妯煎帶瀵喗顨ラ悙鑼ⅵ濠碘剝鎮傞崺鈩冩媴閸濆嫧鍋撻悙宸富闁靛牆妫楃粭鍌炴煠閸愯尙鍩ｇ€规洏鍨藉畷銊︾節閸曨収鍟庨梺鍝勵槸閻楀棙鏅堕悾宀€鐭撴い鏂款潟娴滄粓鏌曟径娑㈡鐎规洖鐭傞弻鐔碱敍濮樺啿顏梺瀹狀嚙闁帮綁鐛崶顒夋晣闁绘劘寮撶槐鐔哥節閻㈤潧啸闁轰礁鎲￠幈銊╁箻椤旇偐鏌堝銈嗙墱閸嬫稒顢婃繝鐢靛█濞佳囨偋閸愵喖纾婚柟鎹愬煐閸犲棝鏌涢弴銊ュ妞わ腹鏅犲铏圭矙濞嗘儳鍓伴梺鎸庢磸閸庤尙绮氭潏銊х瘈闁搞儯鍔岄埀顒€顭烽弻锕€螣閻氬绀嗛梺闈浥堥弲婊堟偂韫囨搩鐔嗛悹楦挎婢ф洟鏌涢弬璺ㄦ憼濞ｅ洤锕、鏇綖椤斿灝鎯堟繝娈垮枛閿曘倝鈥﹀畡鎵殾闁圭儤鍨熼弸搴ㄦ煙閹碱厼骞楃悮锕傛⒒閸屾瑨鍏屾い銏狅躬椤㈡艾顭ㄩ崨顔煎簥濠电娀娼ч鍥х暤娓氣偓閺岀喖鏌囬敃鈧獮鎴︽煕鐎ｎ亝鍤囬柡灞剧洴楠炲洭鍩℃担鍓茬€烽梻浣虹帛缁嬪繘宕曢棃娑辨綎婵炲樊浜滄导鐘绘煕閺囥劌骞愰柡瀣濮婃椽宕ㄦ繛姘灴瀹曟洟骞庨懞銉ヤ患闂佸壊鐓堥崑鍡涙偡瑜版帗鐓冪憸婊堝礈閻斿鍤曢悹鍥ㄧゴ濡插牓鏌曡箛鏇炐ラ柛鏃€鎸冲娲川婵犲倸顫庨梺绋款儐閹瑰洭銆佸Ο瑁や汗闁圭儤鎸撮幏娲⒑閸涘﹦鈽夐柨鏇樺妽缁旂喎螣濮瑰洣绨婚梺鐟扮摠缁诲秴螣閳ь剟鎮楀▓鍨灕妞ゆ泦鍥х叀濠㈣埖鍔曢～鍛存煟濮椻偓濞佳勬叏閸洘鈷掑ù锝勮閻掑墽绱掔紒妯虹瑲闁告帒锕、姗€鎮㈡笟顖涢敜婵＄偑鍊曠换鎰版偋閸曨垰鐒垫い鎴ｆ硶缁愭梹顨ラ悙鎼劷闁归濞€閹崇娀顢楁径濠冩珨缂傚倸鍊搁崐鎼佸磹閻戣姤鍊块柨鏇氱缂嶆棃姊绘担鍝ョШ闁衡偓閸楃儐娓婚柦妯侯樈濞兼牗绻涘顔荤盎鐎瑰憡绻傞埞鎴︽偐閹绘帩浠卞┑鈩冨絻閻楁挸顫忓ú顏勭閹兼番鍨婚埞娑欑節绾版ǚ鍋撻搹顐㈢獩濠碘€冲级閸旀瑩鐛鈧獮鍥ㄦ媴閻熸澘鍘為梻鍌欒兌閸樠囧箺濠婂牆鏋侀柟闂寸閸屻劑姊洪鈧粔鐢告偂濞嗘挻鐓曢煫鍥ㄨ壘娴滃綊鏌￠崱姗堣€块柡灞剧洴婵℃悂濡烽鎯ф倯闁诲氦顫夊ú鈺冪礊娓氣偓瀹曟椽鍩€椤掍降浜滈柟鐑樺灥椤忣亪鏌嶉柨瀣伌闁诡喖缍婂畷鍫曟晲閸屾矮澹曢悗瑙勬礀濞诧綁宕Δ鍛拻濞达絽鎲￠幉鎼佹煕閻樺啿濮嶆鐐村姍楠炲酣鎳為妷銉ょ钵婵＄偑鍊栧Λ鍐极椤曗偓瀹曟垿骞樼紒妯绘珳闁硅偐琛ラ崜婵嬫倶瀹ュ鈷戦柛婵嗗閸ｈ櫣绱掗鑺ュ磳妤犵偛鍟悾锟犲箥閾忣偆鈧鈹戦悙鍙夘棡闁搞劎顢婇幗顐︽⒒娴ｇ瓔鍤欓悗娑掓櫊閹虫繃銈ｉ崘銊ㄐ曢柣搴秵閸撴艾鐣烽崣澶岀瘈闂傚牊绋掗ˉ鎴︽煛鐎ｎ偅顥堥柡灞剧洴閳ワ箓骞嬪┑鍥╀憾闂備浇顕х换鎴﹀箲閸パ屾綎闁惧繗顫夐崗婊堟煕濞戝崬鏋ょ憸鎶婂洦鈷戦柛锔诲弾閻掗箖鏌熼懞銉х煉鐎规洩缍佸畷銊р偓娑櫱氶幏娲⒒閸屾氨澧涚紒瀣尰閺呭爼寮撮悢鍓佺畾濡炪倖鍔х徊楣冨煕閹烘鐓欐鐐茬仢閻忚尙鈧娲栧畷顒勨€旈崘顏嗙＜婵☆垳绮鎴︽⒒閸屾瑨鍏屾い顓炵墦瀵敻顢楅崒姘€抽悗骞垮劚椤︻垶鎮块鈧弻锝夊箛椤旂厧濡洪梺缁樻尰濞叉牠鍩為幋锔藉亹闁圭粯宸婚崑鎾剁磼濡⒈娴勫┑鐐村灟閸ㄦ椽鎮″▎蹇嬧偓鎺戭潩椤掑倷铏庢繝纰樷偓鐐藉仮闁硅棄鐖奸弫鎰緞鐎ｎ剙骞楅梻浣告贡閸嬫挻绻涙繝鍥舵晛婵°倐鍋撻棁澶愭煟濡⒈鍔滈柤鐗堝閹便劍绻濋崘鈹夸虎閻庤娲﹂崑濠傜暦閻斿吋顥堟繛鎴灻ˉ澶愭⒒閸屾瑨鍏屾い顓炵墦閺佸啴濡疯瀹曟煡鏌涢锝囩闁搞倖娲栭埞鎴︽偐鐎圭姴顥濋梺缁樺笚濡炰粙寮诲☉銏犵疀闁稿繐鎽滈弫鏍⒑绾懏鐝紒璇茬墕椤繐煤椤忓嫮顔愰梺缁樺姈瑜板啯淇婅濮婃椽宕ㄦ繝鍐槱闂佸憡蓱濡炰粙寮婚崶顒夋晬闁绘劗琛ラ幏缁樼箾鏉堝墽绉繛鍜冪悼閺侇喖鈽夐姀锛勫幍缂備礁顑堝▔鏇㈠春閿濆洠鍋撶憴鍕闁告梹鐟ラ锝嗙鐎ｅ灚鏅ｉ梺缁樺姇缁嬪嫮绮婚幘璇茶摕婵炴垯鍨归崡鎶芥煏婵炲灝鍔滈柣蹇旀崌濮婂搫效閸パ€鍋撻幇鏉跨；闁瑰墽绮埛鎺懨归敐鍛暈閻犳劧绻濋弻娑氣偓锝庡亝瀹曞瞼鈧娲樼划宀勶綖濠靛鏁囬柣鎴濇濞堝ジ姊绘笟鈧埀顒傚仜閼活垱鏅堕姣插酣宕惰闊剟鏌熼鐣屾噰妞ゃ垺妫冨畷姗€顢旈崱鈺傂氬┑鐘垫暩閸嬬娀骞撻鍡楃筏濞寸姴顑呯粻鐔兼煃閳轰礁鏆欑紒鍓佸仱閺屾盯寮撮妸銉т画闂佺粯鎸搁崯鏉戭潖濞差亜鍨傛い鏇炴噹閸撲即姊虹拠鑼畾闁哄懏绻勫Σ鎰板箳閹惧绉堕梺闈涱煭缁犳垿妫勫澶嬧拺闁荤喐婢樺Σ濠氭煙閸愯尙绠绘鐐茬墦婵℃悂鍩℃担渚悈婵＄偑鍊栭幐鑽ゆ崲閸儱纾绘俊銈呮噺閳锋垿鎮归崶锝傚亾閾忣偆浜堕梻浣瑰濞插繘宕归挊澶屾殾婵炲樊浜濋弲鎼佹煟濡绲荤紒鎰☉椤啴濡堕崱妯锋嫻闂佺瀛╂繛濠囨偘椤斿槈鏃堝川椤旇瀚藉┑鐐舵彧缂嶁偓妞ゎ偄顦甸幃姗€鏌嗗鍡欏幐闂佸憡渚楅崰姘虹€电硶鍋撶憴鍕闁搞劌鐖奸妴浣糕槈閵忊€斥偓鐑芥煕椤愶絿绠ユ俊顖楀亾闁诲氦顫夊ú鏍Χ閹间礁鏄ユ俊銈呮噹閻撴稑霉閿濆懎妲绘い銉︾缁绘繈鎮介棃娑楃捕闂佺粯顨呭Λ婵嬪箖濡　鏀介悗锝庝簻閸ゆ垿姊虹紒妯荤叆闁汇劍绻堝銊︾鐎ｎ偆鍘介梺褰掑亰閸ㄥジ宕电€ｎ喗顥婃い鎺戭槸婢ф挳鏌＄仦鐐鐎规洟浜跺鎾偑閳ь剙危椤曗偓濮婅櫣鈧湱濮甸ˉ澶嬨亜閿曗偓閻忔岸骞堥妸鈺佺劦妞ゆ帒瀚悡鍐煏婢舵盯妾柣蹇涗憾閺屾稓鈧綆鍋呭畷宀勬煙椤旂晫鐭掗柟宕囧仱婵＄兘濡烽姀鐘卞闂佹眹鍨归幉锟犳偂閻斿吋鐓忛煫鍥э攻椤﹪鏌涢悢椋庣闁哄矉缍侀獮鎺懳旈崘顏呮瘒闂?"
        elif scenario == "plan":
            anchor += " 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏咁棃婵炴番鍎遍悧鎾愁嚕閹绘巻妲堥柕蹇曞Х椤㈠懘姊虹憴鍕姸濠殿喓鍊濋幃锟犳偄閸忚偐鍘甸梻渚囧弿缁犳垿鎮橀悩鐢电＜闁规彃顑呴々顒傜磼鏉堛劌娴┑鈩冩倐婵″爼宕堕埡鍐ㄥ箚濠电姵顔栭崰鏍晝閿曞倸纾块柕鍫濇媼閻掕姤銇勮箛鎾跺缂佺姰鍎查妵鍕即閻愭潙娅ら悶姘剧畵濮婂宕掑▎鎴М闂佺濮ょ划鎾崇暦閹惰棄唯闁宠桨鑳堕敍娑欑節閻㈤潧孝婵炲眰鍊濆浼村Ψ閳哄倻鍘介梺褰掑亰閸撴岸骞嗛崼銏㈢＜闁绘瑥鎳愮粔顕€鏌＄仦璇插鐎殿喗娼欒灃闁逞屽墯缁傚秹宕滆绾惧ジ鏌ｉ幇闈涘闁告柣鍊濋弻娑橆潩椤掑鍓跺Δ鐘靛仜閻楁挻淇婇幖浣肝ㄦい鏃囨缂傛捇姊绘担铏广€婇柛鎾寸箞閵嗗啴宕ㄩ婊€绗夐悷婊呭鐢鍩涢幋锔界厱婵犻潧妫楅顏呫亜閵夛妇鐭掗柡宀嬬到铻栧ù锝囨嚀绾板秴顪冮妶搴′簻缂佺粯锕㈤獮鏍亹閹烘垶宓嶅銈嗘尵婵妲愰崣澶岀瘈缁剧増蓱椤﹪鏌涢妸褎鏆い銏′亢椤︽挳鏌涢悩璇у伐妞ゆ挸鍚嬪鍕偓锛卞嫬顏圭紓鍌氬€风粈渚€顢栭崨顖欑剨闁告侗鍙庨崯鍛存煏婢舵稖绀嬪ù婊勭矋閵囧嫰骞樼捄鐩掋垽鏌涘Ο渚殶闁逞屽墲椤煤濡警娓诲ù鐘差儏閺勩儵鏌嶈閸撴岸濡甸崟顖氱鐎广儱顦伴鏍ㄧ箾鐎涙鐭嬬紒顔芥崌瀵鎮㈤悡搴濈炊闂佸憡娲﹂崜锕€螞閻愬绠鹃悗娑欘焽閻﹤顭胯閺咁偄危閹版澘绠婚悗娑櫭鎾绘⒑閸涘﹦绠撻悗姘嚇婵偓闁靛繈鍨婚敍婊勭節閵忥絾纭鹃柡鍫墴瀹曠敻鍩€椤掑嫭鈷戝ù鍏肩懅閹ジ鏌涜箛鏂嗩亪顢氶敐澶婄妞ゆ梻鈷堝濠囨⒑缂佹〞鎴︻敊閺嶎厼缁╅柕濞炬櫆閳锋帒霉閿濆洨鎽傞柛銈嗙懅缁辨帞绱掑Ο铏诡儌闂佸憡甯楃敮锟犮€佸☉姗嗘僵闁稿繒鍘ч惁婊堟⒒娴ｇ鎮戝ù婊€绮欏畷鏇㈠箥椤旇棄搴婇梺绯曞墲缁嬫帡鎮￠弴鐔翠簻闁规澘澧庣粙鑽ょ磼閳ь剟鍩€椤掆偓铻栭柣姗€娼ф禍濂告煕閵娿劍顏犻柟骞垮灩閳藉濮€閻樿尪鈧灝鈹戦埥鍡楃仭婵炲弶锕㈠畷褰掑捶椤撶偛鐏婃繝鐢靛Т濞村倿寮崘顔界叆婵犻潧妫楅顐ょ磼閻樺啿鍝烘慨濠呮缁辨帒螣閸濆嫅鏇熺箾鐎涙鐭嬬紒顔芥崌瀹曟椽鍩€椤掍降浜滈柟鍝勭Х閸忓苯顭胯閺佸寮婚悢纰辨晩闁靛鍎遍弸銈夋煟閹惧崬鍔﹂柡灞剧洴椤㈡洟鏁愰崶鈺冩毉闂備焦瀵х粙鎺楁儎椤栨凹娼栭柧蹇撴贡绾惧吋淇婇姘儓妞ゎ偄閰ｅ铏圭矙鐠恒劍妲€闂佺锕ョ换鍌炴偩閻戣棄绠ｉ柨鏇楀亾缁炬儳鍚嬬换娑㈠箣閻愬娈ゅ銈嗘⒐濞茬喎顫忓ú顏呭仭闁规鍠楅幉濂告⒑閼姐倕鏋傞柛搴ｆ暬楠炲啫顫滈埀顒勩€侀弮鍫濋唶闁绘柨鎼獮妤呮⒒娴ｇ瓔娼愰柛搴㈠▕閹椽濡歌閻棝鎮楅敐搴℃灍闁绘挻绋撻埀顒€鍘滈崑鎾绘倵閿濆骸澧伴柣锕€鐗撻幃妤冩喆閸曨剛顦ラ梺缁樼墪閸氬绌辨繝鍥ㄥ€婚柦妯猴級閵娧勫枑鐎光偓閸曨剙鍓﹀銈呯箰閹虫劗寮ч埀顒勬⒑濮瑰洤鐏叉繛浣冲嫮顩烽柨鏇炲€归悡鏇㈡煏閸繄鍑归梺顓у灣閳ь剝顫夊ú鏍偉閸忛棿绻嗘慨婵嗙焾濡茶螖閻橀潧浠︽い銊ワ工椤繒绱掑Ο鑲╃槇闁硅偐琛ラ埀顒冨皺閻╁孩绻濋悽闈涗粶闁活亙鍗冲畷鎰槈濞嗘劖鐝峰┑鐘绘涧椤戝棝鍩涢幋鐘电＜閻庯綆鍋掗崕銉╂煕鎼淬垹濮嶉柡宀€鍠栭幃鐑芥偋閸喐鍊锋俊鐐€栧ú鈺冪礊娓氣偓閵嗕礁螖閸涱厾顦板銈嗗姇椤戝啴宕濋幋锕€钃熼柕濞炬櫅缁秹鏌涢妷顔句虎闁规儳顕弧鈧梺闈涚箚閳ь剙纾导灞解攽椤旂》宸ユい顓炲槻閻ｇ兘骞掗幋鏃€鐎婚梺鐟扮摠缁诲倿鈥栨径鎰拻濞达絽鎲￠幆鍫熴亜閹存繃鍤囧┑鈥冲缁瑥鈻庨幆褎顓块梻浣告贡缁垰顔忕拠鍙傦綁宕奸妷锔惧帾闂婎偄娲﹀ú鏍ф毄闂備礁鎼懟顖炴偋閸℃稈鈧棃宕橀鍢壯囨煕閳╁啰鎳冮柍宄扮墦濮婅櫣绮欏▎鎯у壉缂備礁顑嗛幐鑽ょ博閻旂厧鍗抽幒铏瑜版帗鐓欓柣鎴炆戠亸鐢告煕濡吋鏆慨濠呮閹叉挳宕熼棃娑欐珱闂備礁鎽滄慨鐢告偋閻樿违闁稿本绋撻梽鍕煕濞戞﹫鍔熼柛妯圭矙濮婅櫣鎲撮崟顐㈠Б濡炪倖娲﹂崣鍐嵁婵犲洤宸濋悗娑欘焽閸樻捇鎮峰鍕煉鐎规洘绮岄埞鎴犫偓锝呭缁嬪繑绻濋姀锝嗙【闁愁垱娲栫叅妞ゅ繐瀚崬銊ヮ渻閵堝骸鍘撮柛鎾寸箓椤啴鎳為妷銈囩畾闂佸壊鍋呭ú鏍嵁閵忥紕绠鹃柛鈩冦€為幋鐘电焾妞ゆ劧闄勯埛鎴︽煕濠靛棗顏存俊鍙夋倐閺岋絽螖閳ь剟宕弶鎴殨妞ゆ帊鑳堕悷褰掓煃瑜滈崜娆撴偩閻戣棄绠ｉ柨鏇楀亾缂佺姴顭烽弻銈夊箹娴ｈ閿梺鍝勵儏閸婂灝顫忓ú顏勫窛濠电姴鍟ˇ鈺呮⒑閸涘﹥灏伴柣鈺婂灥濡喖姊洪棃娴ュ牓寮插鍫熷亗闁绘柨鍚嬮悡蹇涚叓閸パ嶆敾婵炲懎鎳橀弻锝堢疀閵壯呯槇闂佽鍠曠划娆撱€佸☉銏犖ч柛銉㈡櫇濡插洭姊绘担鑺ャ€冮柣鎺炵畵瀹曟繂鈻庨幘宕囩暫濠电偛妫楃欢鐑藉捶椤撴稑浜鹃柨婵嗛娴滄繈鏌℃径瀣€愭慨濠呮閹风娀骞撻幒鎴炵槪缂傚倸鍊哥粔鏉懳涘▎鎴犵焿鐎广儱顦伴崐鐑芥煛瀹ュ浂鐒炬繛娴嬫櫊钘濋悗闈涙憸绾惧ジ寮堕崼娑樺婵炴惌鍣ｉ弻鐔碱敊閻ｅ本鍣板銈冨灪椤ㄥ棝骞忛崨鏉戜紶闁告洦鍋呴濂告⒒娴ｇ瓔鍤欐慨姗堢畵閿濈偞寰勬繛鎺撴そ閺佸啴宕掑槌栨Ф闂備胶绮Λ渚€宕戦幇顒傛殼濞撴埃鍋撻柡灞剧洴楠炲洭妫冨☉娆戜邯闂備胶绮幐濠氭儎椤栫偛钃熸繛鎴炃氬Σ鍫ユ煕濡ゅ啫浠﹂柣蹇婂亾闂傚倷鑳堕幊鎾诲床閺屻儮鈧箑鐣￠柇锔界稁闂佹儳绻愬﹢閬嶆儗濞嗘挻鐓欑紒瀣仢椤掋垽鏌熼悜鎴掓喚婵﹥妞介幊锟犲Χ閸涱喗鐣梻浣规偠閸庢壆绮堟担璇ユ椽顢橀姀鐘崇€梺鍛婂姦閸犳牜澹曢崗鑲╃闁瑰鍋犳竟妯活殽閻愯尙效婵﹥妞介幊锟犲Χ閸涘懌鍨虹换娑欑珶椤栨碍鎼愮€瑰憡绻冮妵鍕冀閵夈儮鍋撳Δ鍛Е鐟滅増甯楅埛鎺楁煕鐏炲墽鎳呮い锔肩畵閺岀喓鎷犺绾惧潡鏌℃笟鍥ф灈閾绘牠鏌涢幇銊︽珕婵炲牅鍗冲铏圭磼濡搫顫屽銈嗘处閸欏啴濡撮崨瀛樺€婚柤鎭掑劤閸欏棝姊洪崫鍕窛闁稿鐩崺鈧い鎺嗗亾闁硅姤绮庨崚鎺楀醇閵夈儵鍞堕梺闈涚箚閳ь剝娅曢悗楣冩⒒娴ｅ憡鎯堥柛濠傜秺椤㈡牕鈻庨幘鏉戔偓鐢告煠閸濄儱浠ù婊勭矒閺岋繝宕堕…鎴炵暥婵炲瓨绮嶉崕鎶藉煘閹达富鏁婄痪顓㈡敱閺佹儳鈹戦敍鍕哗婵☆偄瀚伴幃楣冩倻缁涘鏅濋梺鎸庢磵閸嬫挾绱掗埀顒傗偓锝庡亖娴滄粓鏌熼弶鍨暢缂佸绮妵鍕棘閸噮浼冨┑顔硷功缁垶骞忛崨顔剧懝妞ゆ牗绮屾慨濂告⒒娴ｇ懓顕滄繛鎻掔箻瀹曟劕螖閸愨晩娼熼梺缁樺姇椤曨厾寮ч埀顒勬⒑閹肩偛鍔橀柛鏂跨Т閳诲秴顭ㄩ崼鐔叉嫼缂傚倷鐒﹂敋濠殿喖娲弻鐔哄枈閸楃偘鍠婇悗瑙勬穿缁绘繈鐛惔銊﹀殟闁靛／鍐ㄧ闂傚倷绀侀幖顐﹀疮椤愶箑纾归柤濮愬€曟慨顒勬煃瑜滈崜娑氭閹惧瓨濯撮梻鍫熺☉椤牆顪冮妶搴″箹闁搞垺鐓￠敐鐐剁疀濞戞瑦鍎柣鐔哥懃鐎氼剟寮搁崒鐐粹拺闁告稑锕ユ径鍕煕鐎ｎ亜顏柟渚垮姂婵偓闁靛牆妫楅埀顒傛暬閹嘲鈻庤箛鎿冧痪婵犮垼娉涚€氫即寮诲☉銏犵閻犺櫣鍎ら悘鍫澪旈悩闈涗粶闁哥噥鍋婇敐鐐差煥閸繄鍔﹀銈嗗笒鐎氼剟寮伴妷鈺傜叆闁绘柨鎼瓭缂備讲鍋撻柛鎰ㄦ杺娴滄粓鐓崶銊﹀鞍闁挎稒姊荤槐鎺撴綇閵娧冨绩濠殿喖锕︾划顖滅箔閻旂厧鐒垫い鎺戝閻掑灚銇勯幒鎴濃偓鍛婄濠婂牊鐓犳繛鑼额嚙閻忥繝鏌￠崨顓烆暢闁逞屽墰閺佸摜娑甸崼鏇炵；闁规崘鍩栭崰鍡涙煕閺囥劌澧版い锔哄姂閺岋綁濮€閳轰胶浼堢紓浣虹帛缁诲牓鎮伴鈧畷姗€濡搁姀锛勨偓濠氭⒑閻熸壆鎽犻柡灞诲妽缁傚秵銈ｉ崘鈺冨幗闂侀潧绻嗗Σ鍛村疮韫囨稒鐓熼柟鐑樻煥娴滅偓銇勯妸锝呭姦闁诡喗鐟╅幊鐘活敆閳ь剟路閳ь剙鈹戦悜鍥╁埌婵炲眰鍊濋弫鍐敂閸繄鐣哄┑鐐叉閹尖晠寮崒鐐寸厱闁哄洦锚婵＄厧霉濠婂牏鐣洪柡灞糕偓鎰佸悑閹肩补鈧磭顔愮紓鍌欒閸嬫挸顭跨捄渚剮缂佽妫濋弻鏇㈠醇濠靛棭浼€闂佸憡鏌ㄧ粔褰掑蓟濞戞ǚ鏋庨煫鍥ㄦ礈椤旀帡姊洪崫鍕伇闁哥姵鎸惧Σ鎰板箳濡も偓椤懘鏌ｅΟ铏癸紞濞存粌鐖煎缁樻媴娓氼垳鍔搁梺鎸庢磸閸婃繈骞冮妷锔鹃檮缂佸鍎婚幗鏇㈡⒑閹稿海鈽夐悗姘间簻閳讳粙顢旈崼鐔蜂化闂佹悶鍎崝宀€寰婄拠娴嬫斀妞ゆ棁濮ょ粈瀣叏婵犲懏顏犵紒杈ㄥ笒铻ｉ悹鍥у级濞堫偊姊绘担鍛婃喐濠殿喚鏁诲畷婵單旈崨顓狀唹闂侀潧绻掓慨顓炍ｉ崼銉︾厪闊洦娲栧暩濡炪倖鎸诲钘夘潖閾忓湱纾兼俊顖氭惈椤矂姊虹拠鑼鐎光偓缁嬭法鏆﹂柟鍓佺摂閺佸洭鏌曡箛濞惧亾閺傘儱浜鹃柣銏犳啞閸嬧剝绻涢崱妤冪妞ゅ浚浜炵槐鎺楀焵椤掑嫬鐒垫い鎺戝閳锋垶绻涢懠棰濆殭妤犵偞鐗犻弻娑欑節閸屾粈铏庡銈嗘穿缁插墽鎹㈠┑鍡╂僵妞ゆ帒鍊风槐婊堟煟鎼淬値娼愭繛鍙夌墪鐓ら柨鏇楀亾闁崇粯鎹囧鎾閿涘嫬骞楅梺鐟板悑閹矂宕瑰畷鍥╃煋闁汇垹鎲￠悡鏇㈡煙閹屽殶婵炲弶鎸抽弻鐔碱敍濞嗘垹鐛㈤悗瑙勬礀閵堝憡淇婇悜鑺ユ櫆閻熸瑥瀚鍦磽閸屾艾鈧娆㈤敓鐘插瀭闁告浼濋崫鍕垫建闁逞屽墮椤曪綁骞嗛懜顑挎睏闂佸湱鍎ら幐楣冨储闁秵鐓熼幖鎼灣缁夌敻鏌涚€ｎ亝鍣藉ù婊勬倐椤㈡﹢鎮㈢紙鐘电泿婵＄偑鍊曠换鎰偓姘煎墴瀵娊鏁愰崨顏呮杸闂佺偨鍎辩壕顓㈠春閿濆洠鍋撶憴鍕鐎规洦鍓濋悘鍐⒑閸涘﹤濮﹀ù婊勭箞瀹曟娊顢涢悙绮规嫽婵炶揪绲块悺鏃堝吹濞嗘挻鍊垫繛鎴炲笚濞呭﹦鈧娲橀悷銊╁Φ閹版澘绠抽柟瀵稿Х閸橆剟姊绘担鍛婂暈闁告梹鍨垮畷婵囨償閵娿儲杈堥梺鎸庢礀閸婂綊鎮￠悢鍏肩厪闊洤顑呴悞娲煛閸♀晛鐏﹂柡灞剧〒閳ь剨缍嗛崑鍛暦瀹€鍕厸濞达絿鎳撴慨鍫ユ煙椤栨稒顥堥柛鈺佸瀹曟﹢顢旈崘鈺佹灓闂傚倸鍊搁崐鐑芥倿閿旂晫绠惧┑鐘叉搐缂佲晠寮堕崼姘珕闁哄棙绮撻弻銊╂偄閸濆嫅銏ゆ煢閸愵亜鏋戠紒缁樼洴楠炲鈻庤箛鏇炲Ф闂備浇妗ㄧ粈渚€宕幘顔艰摕闁哄洢鍨归柋鍥ㄧ節闂堟稒鎼愭繛鍛€濆铏规嫚閼碱剛顓虹紓浣藉煐閼归箖锝炶箛鎾佹椽顢旈崪浣诡棃婵犵數鍋為崹鍫曟偡椤栨娑㈡晸閻樺磭鍘介梺闈涚箚閺呮盯鎮橀敐澶嬬厱閻庯絻鍔岄埀顒佺箞閹即顢欓挊澶岀獮闂佸綊鍋婇崜娑㈩敊閹邦厾绠鹃弶鍫濆⒔閸掍即鏌熼懞銉х煁妞ゃ劊鍎靛畷鍫曨敆娴ｅ弶瀚奸梻渚€娼荤€靛矂宕ｆ惔銊﹀€垮Δ锝呭暞閸婂灚绻涢幋鐐茬瑲婵炲懎锕﹂埀顒冾潐濞叉ê煤閻旇偐宓佹俊顖濆亹绾惧吋淇婇鐐存暠閻庢艾銈稿铏规嫚閺屻儺鈧绻濋埀顒佹綇閵娿儱鐏佸銈嗘尵閸庢劙鎮炴禒瀣厵闁规鍠栭。濂告煟閹惧瓨绀嬮柡灞炬礃缁绘盯宕归鐓庮潥闂備胶顭堥鍐磿閺屻儯鈧啴濡烽埡鍌氣偓鐑芥煙缂佹ê绗氭繛鍫弮濮婅櫣鈧湱濯崵娆撴⒑鐢喚绉柣娑卞枤閳ь剨缍嗛崰鏍涘Ο渚唵闁告挷绶￠悞鐐亜閵夛妇顣茬紒缁樼箞閹粙妫冨☉妤佸媰闂備焦鎮堕崝宀勬偉婵傛悶鈧線寮崼顐ｆ櫆闂佸壊鍋掗崑鍛村疾濠婂牊鈷戠紒顖涙礀婢у弶銇勯妸銉︻棦闁诡喗顨婇獮搴ㄦ嚍閵夈儮鍋撻崹顐闁绘劘灏欐禒銏ゆ煕閺冣偓绾板秹濡甸崟顖涙櫆闁割煈鍠栫粊顕€姊虹化鏇熸珕闁烩晩鍨堕悰顔锯偓锝庡枟閺呮粓鏌ｉ敐鍛板妤犵偞顨婂缁樻媴閾忕懓绗￠梺鍝勮閸旀垿鐛径鎰櫖闁告洦鍓﹂崑銊╂⒑閸濆嫯顫﹂柛搴㈢叀閹€斥槈閵忥紕鍘遍梺鏂ユ櫅閸熶即鎮￠鐐寸厱婵鍘ф禍鐐电磼鏉堛劌绗氭繛鐓庣箻婵℃悂濡疯閸庡瞼绱撻崒娆愮グ濡炴潙鎽滈弫顕€骞掑Δ瀣◤濠电姴锕ら悧鍡涙煁閸ヮ剚鐓ユ繝闈涙閳ь剙鎲＄粋宥嗐偅閸愨晝鍘卞銈庡幗閸ㄧ敻寮搁幘缁樼厸闁逞屽墯缁傛帞鈧綆鍋嗛崢鎾绘⒑鐎圭姵銆冪紒鈧笟鈧鎶芥倷閻戞ê鈧爼鐓崶銉ュ姎妞も晩鍓熼弻宥堫檨闁告挻绻堥敐鐐村緞婵炴帒鎼～婊堝焵椤掑嫬鏋侀柛鎰靛枛椤懘鏌曢崼婵嗘殜闁稿鎸婚幏鍛寲閺囩喓鈧姊洪崷顓炰壕婵炲吋鐟╅幆鍌炲礋椤掑倻鐦堥梺闈涢獜缁插墽娑甸悙顑句簻闁挎洖鍊烽幉楣冩煙椤栨艾顏柟顖涙婵℃悂鏁傜憴鍕伜闂傚倷鑳堕…鍫ュ嫉椤掑嫭鍋￠柕濞炬櫅缁€鍌溾偓鍏夊亾闁逞屽墰濡叉劙骞掑Δ濠冩櫔闂佸憡渚楅崢鐐缁嬭鏃堟偐闂堟稐娌梺鍛婃⒐閻熴儵鎮鹃悜绛嬫晝闁挎洍鍋撻崬顖炴⒑闂堟稓绠冲┑顔挎珪缁?"
        return anchor
    anchor = "Let's re-anchor the goal for this turn."
    if goal:
        anchor += f" Your longer arc is still '{goal}',"
    if current_focus:
        anchor += f" and the main thing to protect right now is '{current_focus}'."
    elif file_path:
        anchor += f" For this turn, we should stay grounded in `{file_path}`."
    else:
        anchor += " For this turn, we should stay focused on the single highest-value problem."
    if scenario == "principle":
        anchor += " The priority here is understanding the mechanism, not adding more code too early."
    elif scenario == "concept_teaching":
        anchor += " The priority here is to pin the concept to the live code and the real failure mode, not to recite a definition."
    elif scenario == "engineering_challenge":
        anchor += " The priority here is to keep the challenge rooted in the current project instead of drifting into a toy exercise."
    elif scenario == "plan":
        anchor += " The priority here is tightening sequencing and pacing."
    else:
        anchor += f" I am treating this as {scenario_text}."
    if file_path:
        anchor += f" We should stay grounded in `{file_path}` while we do it."
    return anchor


def _scaffold_diagnosis(
    *,
    scenario: str,
    learner_signal: str,
    diagnostics_count: int,
    weak_spots: list[str],
    teaching_observations: list[str],
    summary: str,
    teaching_decision_reason: str,
    chinese: bool,
) -> str:
    localized_weak_spot = _surface_context_text(weak_spots[0] if weak_spots else "", chinese=chinese)
    localized_observation = _surface_context_text(
        teaching_observations[0] if teaching_observations else "",
        chinese=chinese,
    )
    localized_summary = _surface_context_text(summary, chinese=chinese)
    if chinese:
        parts: list[str] = []
        if learner_signal == "blocked":
            parts.append("婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽弫鎰板川閸屾粌鏋庨柍璇查叄楠炲棜顦虫い鏂垮缁辨捇宕掑▎鎺戝帯婵犳鍠楅幐鎶藉箖濡警娼╅悹杞扮秿閿曞倹鐓曢柡鍥ュ妼閺嬨倝鏌ｉ妶鍌氫壕闂傚倷绀佸﹢閬嶅磻閹捐绠氶悘鐐跺▏濞戙垺鍊烽柣銏㈡暩閿涙繃绻涙潏鍓ф偧闁哄拋鍋婂畷濂割敂閸喓鍘辨繝鐢靛Т閸熸壆绮婚悙纰樺亾濞堝灝鏋涙い顓犲厴楠炲啴濮€閵堝棙鍎梺闈╁瘜閸橀箖宕㈤鐐粹拻濞达絿顭堥ˉ蹇涙煟閹惧磭澧︾€规洘濞婇、姘跺焵椤掆偓閻ｅ嘲鈹戦崶褏绐為梺褰掑亰閸樻悂骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囶亞鐣垫鐐诧躬瀹曟﹢顢旈崱娆欑床缂傚倸鍊烽悞锕傛晝椤愶附鍤€閻犳亽鍔夐崑鎾斥枔閸喗鐏堝銈庡幘閸忔ê顕ｉ锕€绠涙い鎾跺仧缁愮偞绻濋悽闈浶㈤悗姘卞厴瀹曘儵宕ㄧ€涙ǚ鎷绘繛杈剧秬濞咃絿鏁☉娆嶄簻妞ゆ挾鍋熸晶鏇㈡煃鐠囪尙效鐎殿喗鎸虫慨鈧柍銉ュ帠閹撮攱淇婇悙顏勨偓鏇犳崲閹扮増鍋嬪┑鐘叉搐绾惧綊鏌ｉ姀鐘冲暈闁稿鍓濈换娑㈠幢濡ゅ啰顔囧銈呮禋娴滎亪骞冨Ο璺ㄧ杸闁挎繂鎳嶇花鐣岀磽娴ｄ粙鍝洪悽顖ょ節楠炲﹤顭ㄩ崼鐕佹濠电偞鍨惰摫闁硅櫕鐟╅弻锝嗘償閵忊晛鏅遍梺鍝ュУ閻╊垶銆佸鎰佹▌闂佺硶鏂傞崕鎻掝嚗閸曨垰绠涙い鎺戭槹缂嶅倿姊绘担铏瑰笡閽冮亶鏌ｅΔ浣瑰磳鐎规洘绻傞鍏煎緞婵烆澁绠撻弻娑㈠即閵娿儳浠╃紓渚囧亜缁夊綊寮诲☉姘勃闁硅鍔曢ˉ婵囩箾鐎电校闁挎碍銇勯鍕殻濠德ゅ煐閹棃鍨鹃懠顒傚煃闂傚倷绀侀幖顐﹀箠閹邦厽鍙忛柟缁㈠櫙缂嶆牠鐓崶銊﹀婵炲樊浜堕弫鍌炴煕閺囥劌澧紒浣藉煐娣囧﹪鎮欓鍕ㄥ亾閺嶎厼绠板Δ锝呭暙缁愭骞栫划瑙勵€嗛柡瀣⒒閳ь剙鍘滈崑鎾绘煕閺囥劌鍘撮柟鐤缁辨捇宕掑▎鎴濆濡炪値鍘煎ú锕傚疾閸洦鏁傞柛顐ゅ枔閸橆亪姊洪崜鎻掍簴闁糕晛瀚伴幃鐐烘倷椤戝彞绨婚梺鍝勬祩娴滅偟绮欓懡銈囩＜缂備焦顭囩粻鎾淬亜椤愶絿绠炴い銏☆殜閸┾偓妞ゆ巻鍋撻柣锝囨暬瀹曞崬鈽夊▎灞惧缂傚倸鍊烽悞锕佹懌濡炪們鍎卞Λ娆戞崲濞戙垹妞介柛鎰典簽琚﹂梻浣筋嚃閸垳娆㈠顒傛殾濠靛倻顭堝敮闂佹寧姊荤划顖炈夋繝鍐х箚闁绘劦浜滈埀顒佺墵瀹曟繈骞嬮敃鈧崹鍌炴煟閹寸伝顏嗘閻愮儤鐓曢柡鍥ュ妼楠炴鐥幆褋鍋㈤柟顔筋殜閺佹劖鎯旈垾鑼泿婵犵數鍋為幆宀勫窗濡ゅ懎桅闁告洦鍨伴～鍛存煃閳轰礁鏆欑痪鏉跨Т椤啴濡堕崱妯虹闂侀潧鐗忛…鍫ユ偩閻戣棄閱囬柡鍥╁仧閸樻悂姊洪崨濠傚婵炲娲熷濠氼敍濞戞氨鐦堥梺姹囧灲濞佳勭閳哄懏鐓欐繛鑼额唺缁ㄧ晫绱掓潏鈺佷沪闁瑰嘲鎳橀幖褰掑捶椤撱劎闂┑鐘愁問閸犳鏁冮埡鍛闁挎洖鍊归崐鐢告煕椤愶絾绀冮柣鎾寸懇濮婂宕掑鐓庢闂佸憡鏌ㄧ粔褰掑蓟閿濆绠婚悗娑欘焽椤︿即姊洪崫鍕拱婵炲弶顭囬幑銏犫槈閵忕姴鐎銈嗘⒒閸樠嗩暯闂傚倸鍊烽懗鍓佹兜閸洖鐤炬い蹇撴缁躲倝鏌涜椤ㄥ懘鎮為崹顐犱簻闁瑰搫绉剁拹浼存煕閻旈绠婚柡灞剧洴閹晛鐣烽崶銊ュ灡婵＄偑鍊戦崹鐑樼┍濞差€洩銇愰幒鎾跺幈闂佸磭鎳撻悘婵嬪礉濠婂應鍋撻崹顐ｇ凡閻庢凹鍘鹃幑銏犫攽閸ャ劌鍔呴梺闈涚箳婵妲愰敃鍌涒拻闁稿本鐟ㄩ崗宀€鐥鐐靛煟鐎规洘绮岄埞鎴犫偓锝冨妷閸嬫捇宕橀鐓庤€垮┑鐐村灦椤洭鏁嶅▎蹇ｆ富闁靛牆妫涙晶閬嶆煕鐎ｎ剙浠遍柛鈺傜洴楠炴帡骞婇妸銉хШ闁轰焦鍔欏畷銊╊敊閸忓吋鐣奸梻鍌欑閹芥粓宕伴幘璇茬；婵炴垯鍨硅繚闂佸湱鍎ら崺鍫濐焽閳哄倶浜滈柟鐐殔鐎氼噣寮惰ぐ鎺撶厽閹兼番鍊ゅ鎰箾閸欏澧辩紒杈╁仦缁绘繈宕堕埡浣恒偊闂佺澹堥幓顏嗗緤閹稿簺浠氶柟鎯板Г閸婄敻鏌ㄥ┑鍡涱€楀ù婊勭箖缁绘盯宕ㄩ钘夌闂佸疇顫夐崹鍧楀箖閳哄拋鏁婇柤娴嬫櫃缁辨ɑ绻濋悽闈涗粶妞わ附澹嗙划娆撳冀閵婏附鐝峰┑鐘绘涧椤戝棝鍩涢幋锔藉仩婵炴垶宸婚崑鎾诲礂閸涱収妫滃┑鐘垫暩閸嬫盯顢氶鐔稿弿闁圭虎鍣弫鍕煕閳╁啰鈯曢柛瀣€块弻娑㈠箛闂堟稒鐏嶉梺缁樻尭閸熸潙顕ｉ崼鏇熷€烽柡澶嬪焾濡棗顪冮妶蹇氼吅缂佺姵鎹囧濠氭晸閻樻彃鑰垮┑鈽嗗灠閸氬宕抽鍓х＝濞达絼绮欓崫娲偨椤栥倗绡€闁绘侗鍣ｉ獮妯兼嫚閼碱剦鍞烘繝鐢靛█濞佳囨偋閸℃稑绠栭柟杈鹃檮閳锋帒霉閿濆懏鍟為柟顖氱墦閺岋綁顢楅埀顒勫Χ缁嬭法鏆﹀ù鍏兼綑閸愨偓濡炪倖鎸鹃崑鐔兼偪閸ヮ剚鈷戠紓浣姑慨鍥煙绾板崬浜滈柡渚囧櫍閺岋綁鎮㈤崫銉х厐缂備胶绮敃銏ょ嵁閸愵喖鐒洪柛鎰╁妿缁愮偞绻濋悽闈涗杭闁搞劌鎼灋闁告劦鍠栫粻鏍煃閸濆嫭鍣烘い銉ョ墛缁绘盯骞嬮悜鍡樼暭闂佺顫夊ú鐔奉潖缂佹ɑ濯撮柛娑橈攻閸犳劙姊洪崫銉バｉ柛鏃€鐟╅悰顕€骞囬弶璺唴闂佽姤锚閿涘濡烽妷鍐ㄧ秺閺佹劙宕ㄩ褎顥戞繝鐢靛仜閻ㄧ兘寮查悩璇茬畺閻熸瑥瀚ㄩ崑濠囨煙缁嬪灝鐦ㄥù鐘櫊濮婃椽宕ㄦ繝鍐炬缂備胶濮甸崹鍧楀灳閺冨牆绀冩い鏂挎瑜旈弻娑㈠焺閸愮偓鐣奸梺鑽ゅ枂閸旀垿寮婚敐鍡樺劅闁靛繒濮甸幆娑㈡⒑閸涘﹥鈷愰柛銊ョ仢閻ｅ嘲煤椤忓嫮鍔﹀銈嗗笂闂勫秵绂嶅鍫熺厵閺夊牆澧界粙鑽ょ棯椤撶偛顣崇紒杈ㄥ浮楠炲洭顢橀悢鍙夊闂備線鈧偛鑻晶顖涖亜閺冣偓閻楃姴鐣烽弶璇炬棃宕ㄩ鐙€鍞堕梻浣瑰劤濞存岸宕戦崨鏉戠煑闊洦绋掗悡鍐喐濠婂牆绀堥柣鏃傚帶閽冪喓鈧箍鍎遍ˇ顖炴偂濞戞◤褰掓晲閸涱喖鏆堝┑鐐茬墛閻撯€愁潖閾忓湱纾兼俊顖濆亹閻ｇ儤绻濋悽闈涗粶闁挎洏鍊濋敐鐐剁疀閺囩姷锛滃┑鈽嗗灥椤曆囶敁閹剧粯鐓熼柣鏂挎憸閹冲啴鎮楀鐓庡缂佸倹甯￠崺锟犲川椤旇瀚肩紓鍌欑椤戝懘鎮樺┑瀣垫晢闁靛繈鍨荤壕鍏笺亜閺冨洤袚閻忓浚鍙冮弻锝夋晲閸涱厽些濡炪値鍋呯划鎾诲春閳ь剚銇勯幒鎴濐仴闁逞屽厸缁舵艾顕ｉ鈧埢搴ㄥ箚瑜庨崐顖炴⒒娴ｈ櫣銆婇柛鎾寸箞閹兘濡烽埡浣告優闁哄鐗勯崝搴ｅ姬閳ь剟姊哄Ч鍥х伈婵炰匠鍐╂瘎闂傚倷娴囧銊х矆娓氣偓楠炲鏁撻悩鑼杽闂侀潧艌閺呮粓宕愭繝姘參婵☆垯璀﹀Σ褰掓煟鎼搭喖澧存慨濠囩細閵囨劙骞掗幙鍕惞缂傚倷璁查崑鎾趁归敐鍛儓妞ゃ儲鑹鹃埞鎴︽偐瀹曞浂鏆￠梺缁樻尵閸犳牠寮婚悢鍏肩劷闁挎洍鍋撳褜鍨堕弻鐔碱敍濮樺崬鈪甸梺鍝勬湰閻╊垱淇婇幖浣肝ㄩ柕澶堝灩娴滈箖鏌涜椤ㄥ懘鎷戦悢鍝ョ闁瑰瓨鐟ラ悞娲煛娴ｇ鏆ｉ柡灞诲妼閳规垿宕卞鍡橈骏婵＄偑鍊х拹鐔煎磿瀹曞洦顫曢柟鎯х摠婵挳鏌涘┑鍡楃彅闁靛繈鍨荤壕鐣屸偓骞垮劚閹锋垿鐓鍌楀亾濞堝灝鏋︽い鏇嗗浂鏁囬柛蹇曞帶缁剁偛鈹戦悩杈厡闁绘劕锕缁樻媴閸涘﹤鏆堝┑鐐额嚋缁犳挸鐣烽幋锕€鐒垫い鎺戝閻撴洟鎮楅敐搴′簼閻忓繑澹嗙槐鎺旂磼濡偐鐣靛銈庡亝缁诲牊淇婇悜钘夘潊闁绘ê宕ˉ姘舵⒒娴ｅ憡鍟炵紒瀣笒椤洤鈻庨幘鏉戝壒濠德板€愰崑鎾淬亜椤撯剝纭堕柟鐟板閹煎綊宕烽婵堢闂傚倷妞掔槐顔剧不閹达附鍋嬪┑鐘插瀹曞弶绻濋棃娑卞剱闁稿鍔戝濠氬醇閻斿嘲鐎梺闈涚箞閸婃牠鎮￠弴鐐╂斀闁绘ɑ褰冮顐︽偨椤栨稓娲撮柡宀嬬節瀹曘劑顢橀悩鑼幗闁诲孩顔栭崰妤呭箰閾忣偅鍙忛柍褜鍓熼弻銊モ槈濡警浠煎Δ鐘靛仜閻楁挸顫忕紒妯肩懝闁逞屽墮椤洩顦归柍銉畵瀹曞ジ濡烽妷褝绱甸梻鍌欑贰閸撴瑧绮旈幘顔藉€块柛顭戝亖娴滄粓鏌熼崫鍕ら柛鏂跨Ч閺屾稒绻濋崘銊ヮ潔缂備胶绮换鍫ュ春閳ь剚銇勯幒宥堝厡闁荤喎缍婇弻宥堫檨闁告挻鐟╅敐鐐剁疀濞戞瑦鍎梺闈╁瘜閸橀箖鏁嶅鍐ｆ斀闁宠棄妫楅悘鐘崇箾鐎涙顣茬紒鍌氱Т椤劑宕卞▎搴ゅ焻濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柡澶嬪殮濞差亜围闁搞儜灞绢棥闂備胶顫嬮崟鍨暭闂佸憡鐟﹂幑鍥蓟濞戙垹唯闁挎繂鎳庨‖澶愭⒑缂佹ɑ鎯堢紒鑼舵硶濡叉劙骞掗弮鈧€氭岸鏌涘▎蹇ｆ▓婵☆偓绻濆娲濞戞瑦鎮欓柣搴㈢煯閸楁娊鎮伴鈧畷鍫曨敆閳ь剛绮堥崼婢濆綊鏁愰崼鐕佷哗濡炪倧瀵岄崑濠傤潖缂佹ɑ濯村〒姘煎灡閺侇垶姊虹憴鍕仧濞存粎鍋熼崚鎺撶節濮橆剛顓洪梺缁樺灥濡瑩寮鐐粹拻闁稿本鑹鹃埀顒勵棑缁牊绗熼埀顒勭嵁婢舵劕鐏抽悺鎺嶇劍濡炰粙寮崘顔肩＜婵﹩鍓涢埀顒夊弮濮婅櫣鎲撮崟闈涙櫛闂佸摜濮电喊宥囩矙婢跺鍚嬮柛娑变簼閺傗偓闂備胶绮敋缁剧虎鍙冮妴鍌炲蓟閵夛妇鍘遍柣搴到婢у海绮旈鈧弻锛勪沪閻旈攱顥犻柣銈傚亾婵犳鍠楅敋闁告艾顑囩槐鐐哄醇閵忋垻锛滈梺鍛婃寙閸℃﹩鈧绻涚€涙鐭ゅù婊庝簻椤曪絾绻濆顒€宓嗛梺鎸庣☉鐎氼噣寮堕幖浣光拺闁告繂瀚婵嬫煕婵犲繒绉┑锛勬焿椤︽娊鏌涢悩鍐插闁哄矉绲借灃闁逞屽墴閹囧幢濞嗘垹鐣跺┑顔筋焾閸╂牠鎮￠弴銏″€甸柨婵嗛娴滄粓鏌ｈ箛鏃€灏﹂柡宀嬬磿娴狅箓鎮剧仦婵勫劜閵囧嫯顦辩紒鑸靛哺瀵鈽夐姀鐘殿啋闁荤姾娅ｉ崕銈夋倵婵犳碍鈷戝ù鍏肩懅閹ジ鏌＄仦绛嬫█濠碉紕鏁婚獮鍥级鐠侯煈鍞洪梻浣侯攰閹活亞绮婚幋锕€鏋佺憸鐗堝笚閳锋帒霉閿濆懏鍟為柟顖氱墛缁绘稓浠﹂崒姘潎閻庤娲橀崹鍧楀箖閳哄啯瀚氶柤纰卞墻閸熷牓姊绘担鍛婃儓婵炲眰鍔戝畷鎴﹀箛閺夎法鍝楁繛瀵稿Т椤戝棝鎮￠悢鍏肩厵闂侇叏绠戦獮妤冪磽瀹ュ棗鐏撮柡宀嬬秬缁犳盯濡疯閺嗐倝姊洪崫鍕潶闁告梹鍨甸锝夊级閹宠櫕姊归幏鍛村捶椤撶偟鍒伴梻鍌氬€风欢姘焽瑜嶈灋婵炲棙鍨堕弳婊勪繆閵堝懎鏆炵€规洖寮剁换婵嬫濞戞瑱绱炲┑鐐茬毞閺呮粓濡甸崟顖氱閻犺櫣娲呴姀鈽嗘闁绘劖鎯屽▓婊勬叏婵犲嫮甯涢柟宄版嚇閹粌螣閻戞鏆氶梻鍌欑椤撲粙寮堕崹顕呯€虫俊鐐€ら崑鍕崲濮椻偓楠炲啴鎮滈挊澶岊吋闂佹儳娴氶崑鍡涘焵椤掍焦銇濇慨濠冩そ瀹曘劍绻濇担铏圭畳闂備礁鎲￠弻銊╂偉婵傜绠栭柣鎴ｅГ閻掍粙鏌ㄩ弮鈧崕鍐差嚕閹惰姤鈷掑ù锝囶焾椤ュ繘鏌涚€ｂ晝绐旂€规洝顫夌换婵嗩潩椤掍浇绶㈡俊鐐€栭崝褔姊介崟顖氱厱闁硅揪闄勯悡鏇熺節闂堟稒顥滄い蹇ｅ墯閵囧嫰顢曢鍌滄殼闂佸搫鏈粙鎺旀崲濠靛绀冮柣鎰靛墰閺夊綊鏌ｆ惔銈庢綈婵炲弶绮嶉弲璺何旈崘鈺佸簥濠电娀娼ч鍛存倷婵犲嫭鍠愰煫鍥ㄧ◤閳ь兛绶氬畷銊р偓娑櫱氶幏铏圭磽閸屾瑧鍔嶉柨姘攽椤斿吋澶勫ǎ鍥э躬椤㈡稑顫濋幆褌绱ｆ俊鐐€ら崢鐓幟洪敃鍌毼ч柨婵嗩槸缁€鍐煃閸︻厼浜鹃悗姘偢濮婄粯鎷呴搹鐟扮闂佸湱顭堥幉锟犮€冮妷鈺佷紶闁靛／鍕剁础闁荤喐绮嶅Λ鍐嚕婵犳碍鏅查柛娑樺€瑰褰掑箯閸涙潙鎹舵い鎾楀嫅褔姊婚崒娆掑厡缁绢厼鐖煎鎻掆攽鐎ｎ亞锛涢梺闈涚墕椤﹀崬鐣垫笟鈧幃妤呮晲鎼粹剝鐏嶉梺鍝勬噺缁捇寮婚敃鈧灒濞撴凹鍨卞瓭闂備胶顭堥鍡涘箲閸ヮ剙绠栨繝濠傜墛閸ゅ秹鏌曟竟顖氬暙缁犺崵绱撻崒娆掑厡闁稿鎸搁…鍨熼搹瑙勬濡炪倖甯婇悞锕€鈻嶉悩鐐戒簻闁哄稁鍋勬禒锕傛煟閹惧鎳囬柡灞诲€濋幊婵嬫偋閸潿鈧劖绻涚€涙鐭婃繝鈧潏鈺傤潟闁圭儤鎸荤紞鍥煏婵犲繒鐣遍梻澶婄Ф缁辨挻鎷呯拠鈩冪暭闂佸摜濮甸悧鏇㈡偩閻戣棄绠氶梺顓ㄩ檮姝囬梻鍌欐祰椤曆呮崲閹扮増鍋嬮柟鐐墯濞兼牗绻涘顔荤盎缂佲偓閸岀偞鐓曢煫鍥ㄦ处閸庣姴霉閻樻瑥娲﹂埛鎴︽煙閼测晛浠滃┑鈥虫健閺屸剝鎷呴崜鑼悑濡ょ姷鍋涢崯顐ョ亽闁诲繐绻戦悧鏇熺妤ｅ啯鐓ユ繝闈涙椤庢鏌＄€ｎ剙鏋涢柡宀嬬秮楠炴鎹勯悜妯间邯婵°倗濮烽崑鐐烘偋閺団€崇倒婵＄偑鍊栧濠氬磻閹炬枼鏀介梽鍥ㄦ叏閵堝洦宕叉繛鎴欏灩缁犵姷鈧懓瀚晶妤佸緞閸曨垱鐓熼柟鎯ь嚟閹冲洭鏌熼鑲╃Ш鐎规洖鐖煎畷鎯邦槼闁革絼绮欓弻锝夋晝閳ь剟鎮ч幘鎰佹綎婵炲樊浜滅粻浼村箹鏉堝墽鎮奸柣锝呫偢濮婅櫣绮欏▎鎯у壄闂佺锕ュú鐔笺€佸鑸垫櫜濠㈣泛锕﹂鎺戭渻閵堝棙顥嗘俊顐㈠缁傚秴顭ㄩ崼鐔叉嫼闂佽鍨庨崨顖ｅ敹婵犵數濮崑鎾绘煕濡ゅ啫鈧綁鏁愭径濠勫€炲銈嗗笂鐠佹煡骞忔繝姘拺缂佸瀵у﹢浼存煠瑜版帞鐣洪柛鈹惧亾濡炪倖甯婇悞锕傚磹閹扮増鐓欐い鏂诲妼鐎氼喚寮ч埀顒勬⒑閸涘﹤濮﹀ù婊呭仱楠炲﹤鈹戦崱蹇旀杸闁圭儤濞婂畷鎰板即閵忕姷鐤囬柟鑹版彧缁蹭粙藟濮樿埖鐓曠憸搴ㄣ€冮崼銉ョ煑闁瑰墽绮悡鏇㈡煏婢舵稓鍒板┑锛勬櫕缁辨帡鍩€椤掑嫬閱囬柕蹇嬪灪閿涘繘姊虹拠鈥崇€诲ù锝夋櫜閸掓帡姊绘担鍛婃儓闁活厼顦卞濠冪鐎ｅ墎绋忓┑鐘诧工閻楀棝鐛姀鈥茬箚闁靛牆瀚崗灞矫瑰搴濋偗婵﹦绮幏鍛村川婵犲倹娈樻繝纰樻閸嬪懘宕归崷顓炲灊濠电姵鑹剧粻濠氭偣閸ヮ亜钄奸柟鑺ユ礋濮婃椽骞愭惔锝傛闁诲孩鍑规禍婊堝煝娴犲鏁傞柛顐ゅ枔閸樹粙姊洪幐搴ｇ畵闁硅櫕鍔曢…鍥晸閻樺磭鍘繝銏ｅ煐缁嬫牜绮堢€ｎ€㈢懓顭ㄩ崟顓犵厒闂佺灏欓…鍫ユ偩濠靛鐒垫い鎺嗗亾闁宠閰ｆ慨鈧柣娆屽亾婵炲皷鏅犻幃鐟懊洪鍡欑獥闂佺濮ゅú鏍煘閹达附鍊烽柡澶嬪灩娴犙囨⒑閹肩偛濡兼繝鈧潏鈺佸灊缂備焦顭囩弧鈧┑顔斤供閸樺ジ鍩€椤掆偓閻忔氨鎹㈠☉銏犵闁绘劕鐏氶崳浠嬫⒑缂佹ê绗╁┑顔哄€楅幑銏犫槈閵忕娀鍞跺┑鐐村灦鑿ら柛瀣尭铻栭柛鎰ㄦ櫓濞肩喖姊虹憴鍕姢妞ゆ洦鍙冮幃鐤亹閹烘挾鍘遍梺闈涱槹閸ㄧ數鈧凹鍠楃粋宥夘敂閸涱剛绠氶梺缁樺姦娴滄粓鍩€椤掍胶澧电€规洖缍婇幃浠嬪级閸℃鍠橀柟顔荤矙瀹曘劍绻濋崒娆戦挼濠碉紕鍋戦崐鏍哄澶婄；闁圭偓鎯屽▓浠嬫煟閹邦厽缍戞繛鎼枟椤ㄣ儵鎮欑拠褑鍚梺鍦帶缂嶅﹪銆侀弴銏℃櫜閹兼番鍩勫Λ鍐⒒閸屾瑨鍏岀痪顓炵埣瀵剚绗熼埀顒€鐣烽幋锕€绠婚柟棰佺劍鐎靛矂姊洪棃娑氬婵☆偅顨婂畷鍛婄節閸ャ劎鍘遍柣搴秵閸嬪懎鐣峰畝鍕厸閻忕偟顭堟晶鑼磼濡ゅ啫鏋涚€规洘鍎奸ˇ鎶芥煟濠靛洨绠撻柍瑙勫灴椤㈡瑧娑靛畡鏉款潬缂傚倷绶￠崳顕€宕瑰畷鍥у灊妞ゆ挶鍨洪崑鍕煟閹捐櫕鎹ｉ柛鏃撶畱椤啴濡堕崱妤€娼戦梺绋款儐閹稿濡甸崟顖ｆ晣闁绘劕顕埞娑橆渻閵堝繒鐣辩紓宥咃躬瀵鎮㈢喊杈ㄦ櫓闂侀潧顭堥崕鏌ュ箹閹邦収娈介柣鎰典簻閻忣亜菐閸パ嶈含闁诡喗鐟ч埀顒佺⊕椤洭藝閵娿儮鏀介柨娑樺娴犫晛鈹戦鍝勨偓鏍矚鏉堛劎绡€闁搞儜鍜佸晣濠电偠鎻徊浠嬪箺濠婂牆鍌ㄩ柛娑橈功缁犻箖寮堕崼婵嗏挃缂佸鍓氱换娑㈠椽閸愵亞袦閻庢鍠楅幃鍌炲春閳ь剚銇勯幒鎴濐仾闁抽攱鍨块弻銈嗘叏閹邦兘鍋撻弴銏犲嚑闁瑰濮风壕鍏笺亜閺冨倸甯舵い鎺嬪灲閺岋繝宕ㄩ悧鍫€愰柧缁樼墵閺屾盯骞囬妸锔界彆濠电偛鐗婂姗€鍩為幋鐐茬疇闂佺锕ュú鐔肩嵁婵犲懐鐤€婵炴垶顭囬敍娑㈡⒑缁嬭法鐏遍柛瀣仱閹繝鎮㈤崗鑲╁幐闂佺鏈銊︾閵忋倖鐓欐い鏃囨閻忔挳鏌″畝瀣М妤犵偞顭囬幑鍕倻濡皷鍋撻悙顒傜闁挎繂鎳忛幖鎰版煥閺囥劋閭柕鍡曠閳藉顫滈崱妯哄厞婵＄偑鍊栭幐楣冨窗鎼淬劌绀堥柣銏㈡暩绾句粙鏌涚仦鍓ф噯闁稿繐鐭傞幃妤€顫濋鍌滎啋閻庤娲栭悥鍏间繆濮濆矈妲诲Δ鐘靛仜閻楁挸顫忛搹瑙勫珰闁肩⒈鍓涢濠囨⒑缁嬫鍎戝┑鐐╁亾濡炪們鍨烘穱娲囬幎鑺ョ厵濞撴艾鐏濇慨鍌溾偓瑙勬礃鐢繝骞冨▎鎴斿亾閻㈡鐒炬鐐村姍濮婅櫣鎷犻懠顒傤唺闂佺顑嗙粙鎺楀疾閼哥數顩烽悗锝庝簽閸樻劙姊洪崫鍕偍闁搞劍妞介幃鈥斥枎閹扳晙绨婚梺鍝勭Р閸斿酣鍩婇弴鐔翠簻闁靛鍎虫晶鏇㈡煃鐟欏嫬鐏撮柛鈺佸瀹曟﹢鍩℃担鎻掍壕闁归偊鍏橀弨浠嬫煃閵夈儳锛嶉柛鈺嬬悼閳ь剝顫夊ú鏍х暦椤掑啰浜欏┑鐐舵彧缂嶁偓婵℃ぜ鍔嶇粩鐔煎即閵忊檧鎷婚梺绋挎湰閻燂妇绮婇悧鍫涗簻闁哄洤妫楅崰姘焽閳哄懏鐓ラ柡鍥╁仜娴滄壆绱撳鍡欏ⅹ妞ゎ叀娉曢幑鍕偘閳ユ剚娼撴繝鐢靛仜濡﹥绂嶅┑瀣柧婵犻潧顑嗛悡鏇㈡倶閻愭潙绀冨瑙勶耿閺岋絾鎯旈鐓庣睄濠殿喖锕ュ钘夌暦濠婂牆绠甸柟鍝勭Ф閸戣绻濋悽闈涗粶鐎殿喖鐖奸幃褔鎮╁顔兼婵炴潙鍚嬪娆忔暜闂備礁鍟块幖顐﹀磹婵犳艾鍌ㄩ柟鍓х帛閸嬧剝绻濇繝鍌氼伀闁活厽甯為埀顒冾潐濞叉鍒掑畝鍕剁稏婵犻潧鐗婂畷澶娒归敐鍡樼┛缂佺姵鎹囧璇测槈閵忕姴宓嗛梺闈涱焾閸庤櫕绂掗埡鍐＝濞达絽鎼牎婵犵數鍋涢敃顏勵嚕婵犳碍鍋勯悶娑掆偓鍏呭濠电偞鍨堕悷顖炴倿閽樺鏀介柍銉ㄦ珪閸犳﹢鏌＄仦鍓с€掗柍褜鍓ㄧ紞鍡涘磻閸涱厾鏆︾€光偓閸曨剛鍘电紓浣圭☉濠€杈╁姬閳ь剚绻濈喊妯峰亾瀹曞洤鐓熼悗瑙勬处娴滄繈骞忛崨顖涘珰闁斥晛鍠涚槐鏍⒒閸屾艾鈧悂宕愬畡鎳婂綊宕堕妸锕€寮块梺闈涚墕椤︿即寮查鍛箚闁绘劦浜滈埀顒佸灴瀹曟洟顢涢悙鎻掔€繝闈涘€婚…鍫燁攰闂備礁婀辨晶妤€顭垮Ο鑲╀笉闁规儼濮ら悡娆撴煙椤栧棗鎳忛幉濂告⒑缂佹绠栧┑鐐诧工椤繒绱掑Ο璇差€撻梺鍛婄☉閿曘倝寮抽崼鐔虹闁规儳顕。鍙夈亜閵娿儻宸ラ柣锝夘棑閹叉挳宕熼顐㈡婵犵數鍎戠紞鍡涘礂濮椻偓瀹曟垿骞樼拠鑼紲濠殿噯缍嗛崢钘夘渻娴犲鈧線寮崼婵嗙獩濡炪倕绻愰幊搴敂閸︻厾纾介柛灞剧懆閸忓矂鏌ц箛鎾诲弰鐎规洏鍨虹缓鐣岀矙鐠恒劎鏋冮梻濠庡亜濞诧妇绮欓幒妤€纾婚柣鏃€鎮舵禍婊堢叓閸ャ劍灏靛褎鐩弻锝夊箻鐎涙顦伴梺鍝勭焿缁绘繂鐣峰鈧弫鎰板川椤掆偓椤ユ岸姊婚崒娆愮グ鐎规洜鏁诲畷浼村幢濞戞锛熼梺姹囧灪閹爼鍩€椤戣法顦︽い顐ｇ箞閹虫粓宕归锝囧礁婵犵數濮伴崹濂稿春閺嶎剚鎳岄梻浣告惈閹冲繒鎹㈤崼婵愭綎婵炲樊浜滅粻浼村箹鏉堝墽鎮奸柣锝囨暬濮婃椽宕妷銉︾彙闂佺顑呴幊鎰垝鐎ｎ亶鍚嬮柛娑变簼閺傗偓闂佽鍑界紞鍡涘磻閳ь剟鏌熼柨瀣仢婵﹥妞藉畷銊︾節閸曘劍顫嶉梻浣瑰濞插繘宕愰弽顓炵疄闁靛ň鏅涢悞鍨亜閹烘垵顏柍閿嬪灴閺屾稑鈹戦崱妤婁患闂侀€炲苯澧存い銉︽尭閳诲酣濮€閻欌偓濞尖晠鏌涢幘鑼槮缂佷緤绠撳Λ鍛搭敃閵忊€愁槱闂佺懓鍢查鍛弲濡炪倕绻愮粔鐢稿疾濠婂牊鈷戦柛娑橈梗缁跺崬霉濠婂嫮绠橀柍褜鍓氶懝楣冨Χ缁嬫娼栨繛宸簼閸ゆ帡鏌曢崼婵囧晽闁靛骏绱曠粻楣冩煠绾板崬澧柍璇茬墦閺屾盯鍩為幆褌澹曞┑锛勫亼閸婃牕顔忔繝姘；闁规儳澧庡Λ顖滅磽娴ｉ潧鐏╃€殿噮鍣ｉ弻娑㈠煘閹傚濠碉紕鍋戦崐鏍ь啅婵犳艾纾婚柟鐐暘娴滄粍銇勯幘璺盒㈤柛妯侯嚟閳ь剚顔栭崰娑㈩敋瑜旈崺銉﹀緞閹邦剦娼婇梺缁樕戣ぐ鍐矈椤曗偓濮婄粯绗熼埀顒€顭囪閳ワ箓宕奸妷銉э紵闂備緡鍓欑粙鍕礊閺嶎厽鐓冮柛婵嗗閸ｆ椽鏌嶉柨瀣伌闁哄本绋戦埥澶婎潨閸喐鏆伴梺璇茬箰缁绘帡寮繝姘摕闁斥晛鍟刊瀵哥磼濞戞﹩鍎忔繛鍫幖椤啴濡舵惔鈥茬盎缂備胶绮敮鐐参ｉ幇鏉跨闁瑰啿纾崰鏍箠閺嶎厼鐓涢柛灞剧閻ゅ嫰姊婚崒姘偓椋庢濮樿泛鐒垫い鎺戝€告禒婊堟煠濞茶鐏￠柡鍛埣椤㈡瑦鎱ㄩ幇顏嗙泿婵＄偑鍊栭幐楣冨磻閻愮數鐭氶柟绋跨昂娴滄粓鏌ㄩ弮鍌涙珪闁告瑢鍋撻梻浣筋嚃閸ｎ垳鎹㈠┑鍥︾箚闁兼悂娼х欢鐐烘倵閿濆骸澧悽顖炵畺濮婄粯鎷呯粙娆炬闂佺顑呴幊鎰板箲閵忋倕绀冩い鏃囧亹閿涙稑顪冮妶鍛闁硅櫕鍔楃划濠氬礈瑜夐崑鎾绘偡閺夋妫岄梺鍝ュУ濞茬喖鐛径瀣ㄥ亝闁告劏鏅濋崢鍛婄箾鏉堝墽鍒伴柟璇х節瀹曟澘顫滈埀顒勫蓟閳ュ磭鏆嗛悗锝庡墰琚︽俊銈囧Х閸嬫稑煤椤擃潿鈧礁螖閸涱厾锛滈梺绋跨焿婵″洨绮旈鈧弻鈥崇暆鐎ｎ剛袦闂佺硶鏂侀崜婵堟崲濠靛纾兼繝濞惧亾闁告繃顨婂缁樻媴妞嬪簼瑕嗙紓浣藉紦缁瑥鐣烽弻銉ヨ摕闁靛鍨崇粙蹇撯攽閻樿宸ラ柣妤€妫濋幃鐐哄垂椤愮姳绨婚梺鍦劋閸ㄧ敻顢旈妷鈺傜厓鐟滄粓宕楀☉姘辩焼濞撴埃鍋撻柨婵堝仜閳规垿宕奸悢椋庯紡闂備礁鎲＄换鍌溾偓姘煎灦閸┾偓妞ゆ巻鍋撻柣蹇旂箞閸╃偤骞嬮敂钘夆偓鐑芥煕濞嗗浚妯堟俊顐節濮婃椽骞栭悙鎻掝瀷闂佸摜濮村锕傛倶鐎ｎ喗鈷戦梻鍫熶緱閻掗箖鏌涙惔顔兼珝鐎殿喓鍔嶇粋鎺斺偓锝庡亞閸欏棗鈹戦悙鏉戠仸闁挎碍銇勮箛濠冩珔闂囧绻濇繝鍌氭殧闁稿鍨介弻锛勪沪閸撗€濮囩紓浣虹帛缁诲牆鐣峰鈧、鏃堝礋閵婏箑顏梻浣筋嚙濮橈箓锝炴径濞掓椽寮介銈囶槸婵犵數濮村ú銈囩不閺嶎厽鐓ラ柣鏂挎惈鍟搁悗瑙勬尫閻掞箓濡甸崟顖氱鐎广儱鐗嗛崢鈥斥攽閻愭潙绲绘い鏇ㄥ弮閸┾偓妞ゆ帒鍠氬鎰箾閸欏鐭掔€规洑鍗冲浠嬵敇濠ф儳浜惧ù锝堝€介弮鍫濆窛妞ゆ挾濯寸槐鏌ユ⒒娓氣偓濞佳囨偋閸℃あ娑樷攽鐎ｎ亝鐎?")
        elif learner_signal == "uncertain":
            parts.append("婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽弫鎰板川閸屾粌鏋庨柍璇查叄楠炲棜顦虫い鏂垮缁辨捇宕掑▎鎺戝帯婵犳鍠楅幐鎶藉箖濡警娼╅悹杞扮秿閿曞倹鐓曢柡鍥ュ妼閺嬨倝鏌ｉ妶鍌氫壕闂傚倷绀佸﹢閬嶅磻閹捐绠氶悘鐐跺▏濞戙垺鍊烽柣銏㈡暩閿涙繃绻涙潏鍓ф偧闁哄拋鍋婂畷濂割敂閸喓鍘辨繝鐢靛Т閸熸壆绮婚悙纰樺亾濞堝灝鏋涙い顓犲厴楠炲啴濮€閵堝棙鍎梺闈╁瘜閸橀箖宕㈤鐐粹拻濞达絿顭堥ˉ蹇涙煟閹惧磭澧︾€规洘濞婇、姘跺焵椤掆偓閻ｅ嘲鈹戦崶褏绐為梺褰掑亰閸樻悂骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囶亞鐣垫鐐诧躬瀹曟﹢顢旈崱娆欑床缂傚倸鍊烽悞锕傛晝椤愶附鍤€閻犳亽鍔夐崑鎾斥枔閸喗鐏堝銈庡幘閸忔ê顕ｉ锕€绠涙い鎾跺仧缁愮偞绻濋悽闈浶㈤悗姘卞厴瀹曘儵宕ㄧ€涙ǚ鎷绘繛杈剧秬濞咃絿鏁☉娆嶄簻妞ゆ挾鍋熸晶鏇㈡煃鐠囪尙效鐎殿喗鎸虫慨鈧柍銉ュ帠閹撮攱淇婇悙顏勨偓鏇犳崲閹扮増鍋嬪┑鐘叉搐绾惧綊鏌ｉ姀鐘冲暈闁稿鍓濈换娑㈠幢濡ゅ啰顔囧銈呮禋娴滎亪骞冨Ο璺ㄧ杸闁挎繂鎳嶇花鐣岀磽娴ｄ粙鍝洪悽顖ょ節楠炲﹤顭ㄩ崼鐕佹濠电偞鍨惰摫闁硅櫕鐟╅弻锝嗘償閵忊晛鏅遍梺鍝ュУ閻╊垶銆佸鎰佹▌闂佺硶鏂傞崕鎻掝嚗閸曨垰绠涙い鎺戭槹缂嶅倿姊绘担铏瑰笡閽冮亶鏌ｅΔ浣瑰磳鐎规洘绻傞鍏煎緞婵烆澁绠撻弻娑㈠即閵娿儳浠╃紓渚囧亜缁夊綊寮诲☉姘勃闁硅鍔曢ˉ婵囩箾鐎电校闁挎碍銇勯鍕殻濠德ゅ煐閹棃鍨鹃懠顒傚煃闂傚倷绀侀幖顐﹀箠閹邦厽鍙忛柟缁㈠櫙缂嶆牠鐓崶銊﹀婵炲樊浜堕弫鍌炴煕閺囥劌澧紒浣藉煐娣囧﹪鎮欓鍕ㄥ亾閺嶎厼绠板Δ锝呭暙缁愭骞栫划瑙勵€嗛柡瀣⒒閳ь剙鍘滈崑鎾绘煕閺囥劌鍘撮柟鐤缁辨捇宕掑▎鎴濆濡炪値鍘煎ú锕傚疾閸洦鏁傞柛顐ゅ枔閸橆亪姊洪崜鎻掍簴闁糕晛瀚伴幃鐐烘倷椤戝彞绨婚梺鍝勬祩娴滅偟绮欓懡銈囩＜缂備焦顭囩粻鎾淬亜椤愶絿绠炴い銏☆殜閸┾偓妞ゆ巻鍋撻柣锝囨暬瀹曞崬鈽夊▎灞惧缂傚倸鍊烽悞锕佹懌濡炪們鍎卞Λ娆戞崲濞戙垹妞介柛鎰典簽琚︽俊鐐€戦崹娲偡閳轰緡鍤曢柟缁㈠枛椤懘鏌嶉柨顖氫壕闂佸綊鏀卞钘夘潖濞差亜宸濆┑鐘插暙绾锯晠鏌ｈ箛鎾剁闁荤啿鏅涢悾鐑藉閻橆偅顫嶉梺闈涢獜缁辨洟宕㈤柆宥嗏拺缂備焦鈼ら鍫濈柈闁割煈鍟旇ぐ鎺濇晩闂佹鍨版禍楣冩偡濞嗗繐顏紒鈧崘顔界厱闁靛鍎查崑銉╂煟濞戝崬鏋涢摶锝呫€掑鐓庣仯闁哥偟鏁诲娲川婵犲啫顦╅梺鍛婃尰瀹€姝屾＂闂佸壊鍋€閹冲洭宕戦幘鑸靛枂闁告洦鍓涢敍姗€姊洪崨濠冣拹闁搞劌娼℃俊瀛樻媴缁洘鐎婚梺鐟板⒔鐞涖儵骞忔繝姘厽閹兼番鍔嶅☉褔鏌熺拠褏绡€鐎殿喗濞婇幃褔宕奸姀銏㈡闂備焦鐪归崹钘夘焽瑜嶉弳鈺呮⒒娴ｈ姤銆冪紒鈧笟鈧獮澶愭晬閸曨剙搴婂┑鐐村灟閸ㄥ綊鎮為崹顐犱簻闁瑰搫绉烽崗宀€绱掗悩鍐插姢闂囧鏌ㄥ┑鍡樺櫣闁哄棜椴哥换娑㈠级閹存績鍋撻崹顕呭殨妞ゆ劧绠戠粈瀣亜閺嶃劎銆掗柛姗€浜跺娲棘閵夛附鐝旈梺鍝ュ枍閸楁娊宕烘繝鍥у嵆闁靛骏绱曢崢閬嶆煟鎼搭垳绉靛ù婊勭矒閸┾偓妞ゆ巻鍋撴繝鈧柆宥呯闁靛繒濮Σ鍫ユ煏韫囨洖啸妞ゆ挸鎼埞鎴︽倷閸欏妫炵紓浣虹帛鐢绮嬮幒鎾卞亝闁告劏鏂侀幏铏圭磽閸屾瑧鍔嶉拑閬嶆倶韫囨洖顣肩紒缁樼洴閹崇娀顢楅埀顒勫几濞戞埃鍋撳▓鍨灈妞ゎ厾鍏樺顐﹀箻缂佹ê浜归梺鑲┾拡閸撴瑩鍩€椤掑倸浠辨慨濠冩そ濡啫鈽夋潏銊愩倝姊虹粙鎸庡攭婵炲懏娲滅划瀣箳濡も偓缁犳氨鎲告径鎰哗濞寸姴顑嗛悡鐔兼煙闁箑骞楃紓宥嗗灦閹便劑鏁愰崨顕呮＆闂佸搫鏈惄顖涗繆閻戣姤鏅查柛娑卞弾閻庣兘姊绘担鍛婂暈閻绱掗鐣屾噧閾荤偤鏌涘☉娆愬剹闁轰礁鍟撮弻鏇＄疀婵炴儳浜鹃柛鎰紦閹查箖姊婚崒娆掑厡妞ゎ厼鐗忛埀顒佺▓閺呮粎鎹㈠☉娆戠瘈闁搞儮鏅涚粊锕傛⒑閸涘﹤濮€闁哄懏绻堝浠嬪礋椤栨稓鍘卞┑鐐村灦閿曨偊宕濋悢鍏肩厱婵☆垳绮畷宀勬煙椤旂厧妲绘い顓滃姂瀹曠喖顢橀悩闈涘辅闂佽姘﹂～澶娒哄Ο鐓庡灊鐎光偓閸曨偆鍘撮梺鐟邦嚟婵參宕戦幘缁樻櫜闁告侗鍙庨弳銏㈢磽娴ｅ壊鍎忕紒缁樺灩閹广垹鈹戠€ｎ亶娼婇梺鎸庣箓閹虫劙宕㈤锔解拺闁告稑锕ラ埛鎰箾閸欏鐭岄柛鎺撳笚缁绘繂顫濋鈧崬銊ヮ渻閵堝棙灏甸柛鐘虫崌瀹曘垽鏌嗗鍡欏幗闂婎偄娲﹀ú鏍ㄧ濠婂喚鐔嗙憸宀€鍒掑▎鎰箚闁圭虎鍠栫粻鎶芥煙閹冪秮缂併劌顭峰娲礃閸欏鍎撻梺绋匡工椤嘲鐣烽敐澶婄劦妞ゆ帒瀚埛鎴︽偣閸ワ絺鍋撻搹顐や粚婵＄偑鍊ら崑鍕囬崹顐＄箚闁割偅娲橀弲婵嬫煕鐏炵偓鐨戞い鏂挎喘閺岀喖宕楅崗鐓庡壒闂佸摜濮靛ú鐔风暦椤愨懡鏃堝川椤旇瀚藉┑鐐舵彧缁蹭粙骞夐敓鐘茬畾闁割偆鍠嶇换鍡樸亜閹板墎绋婚悘蹇ラ檮閹便劍绻濇担铏圭厯閻庤娲滈崰鏍€佸鈧幃銏犵暋閹殿喖鎼告繝鐢靛Х閺佸憡绻涢埀顒佺箾娴ｅ啿娴傞弫鍕煕閳╁啳娉插鑸靛姇闁卞洭鏌ｉ弮鍥仩妞ゆ梹娲熷娲偡閹殿喗鎲肩紓浣筋嚙閸婂潡骞婂鍡愪汗闁圭儤鎸鹃崢閬嶆⒑鐟欏嫬绀冪€规洜鏁婚幃楣冩倻濡寮挎繝鐢靛Т鐎氼剟宕濈€ｎ偆绠剧痪鏉垮綁闁垱顨ラ悙鑼фい銏″哺瀹曘劑顢欒缁挸顫忕紒妯诲濞撴凹鍨抽崝鎼佹⒑閹稿孩纾搁柛濠冩礋閳ワ箓宕堕鈧悘鎶芥煙妫颁胶顦︽繛鍫涘姂閺岋綁鎮╅崣澶婎槱缂備椒鐒﹀娆忓祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧悗娑欑箞閹鎲撮崟顒€纰嶅┑鈽嗗亝缁诲倿锝炶箛鎾佹椽顢旈崪浣诡棃婵犵數鍋為崹鍏肩椤掑嫬绀夐柟闂寸劍閳锋垹绱掔€ｎ厽纭堕柛鎴濈秺閺屾稑螖娴ｇ硶鏋欏Δ鐘靛仜閿曘倝鈥﹂妸鈺侀唶妞ゆ劧绲惧▍鍡涙⒒娴ｅ憡鍟炴繛鎻掔箻瀹曟繂顓兼径濠冾棟闂侀€炲苯澧存慨濠勭帛閹峰懘鎼归悷鎵偧闂備礁鎲″褰掓偋閻愬搫桅闁圭増婢樼粈鍐┿亜閺冨洤浜归柣锝嗘そ濮婃椽鎮烽柇锕€娈舵繝娈垮櫍椤ユ挻绔熼弴鐔洪檮闁告稑锕ゆ禒顖炴⒑閹肩偛鍔村ù婊勭矒閹啴宕崟鐢靛數閻熸粌楠哥叅婵せ鍋撳┑锛勬暬瀹曠喖顢涢敐鍡樻珖闂備線娼х换鍫ュ垂婵犳凹鏁婇柛銉墯閻撶喖鏌熼幆褍鑸归柍褜鍓氶悧鐘充繆閻㈢绀嬫い鏂垮⒔閺夋悂姊洪崷顓炰壕闁告挻纰嶇€靛ジ鍩€椤掍椒绻嗛柣鎰典簻閳ь剚鐗犲濠氬Ω閵夊啯妞介、姗€濮€閻樼儤鎲伴梻浣虹帛閺屻劑宕ョ€ｎ喖鍚圭€光偓閸曨剛鍘藉┑掳鍊愰崑鎾绘煟濡も偓濡鍩ユ径搴Ь缂備浇椴搁幐濠氬箯閸涘瓨鍋￠柟娈垮枤閵堢兘姊绘担鍛婅础闁冲嘲鐗撳畷鎴﹀礋椤愩倖娈奸梺鍛婃处閸ㄩ亶鍩涢幋锔界厱闁圭偓娼欑徊璇裁瑰鍕⒌闁哄本绋掗幆鏃堝閵忕姴缁╅梻浣虹《閺呮粓鎯勯鐐靛祦閻庯綆鍠楅崐鐑芥煟閵忊槅鍟忛柛鐔烽叄濮婄粯鎷呴崫鍕粯闂侀潧鐗婇幃鍌濈熅闂佺鐬奸崑娑㈠触鐟欏嫮绠鹃柛鈩兠慨锔界箾閸粎鐭欓柡宀嬬秮楠炲洭顢橀悢铏光枏缂傚倷鐒﹂妵鍡涘川椤栨粣绱查梺鍝勵槸閻楀嫰宕濈仦鐭綊顢氶埀顒勫蓟閻斿吋鎯炴い鎰╁€楅悡澶娾攽閳藉棗浜滈柛鐕佸亰閸┿儲寰勬繛銏㈠枔缁辨帒螣閻戞鏆梻鍌氬€峰ù鍥敋瑜嶉～婵嬫晝閸岋妇绋忔繝銏ｆ硾閳洟宕崟搴ｅ枑缁楃喖顢涘☉妯兼В婵犵數鍋涢顓熸叏閹绢噮鏁勯柛娑欐綑閸欏﹪鏌曟径鍡樻珕闁绘挸鍟伴幉绋款煥閸繄顦┑顔筋焾濞夋稒顢婇梻浣告啞濞诧箓宕归幍顔句笉鐎规洖娲犻崑鎾荤嵁閸喖濮庡銈忕細閸楁娊銆侀幘璇插唨闁靛ě鍜佸晭闂佽瀛╃粙鎺椻€﹂崶顒佸剹閻庯綆鍓涚壕鍏笺亜閺冨洤袚鐎规洖鐬奸埀顒侇問閸犳牠鈥﹂悜钘夌畺闁靛繈鍊栭崑鍌炲箹鐎涙绠橀柣鎰躬濮婄粯鎷呴崨濠傛殘濠电偠顕滅粻鎾崇暦濠婂牊鏅濋柍褜鍓濋悘瀣⒑缂佹ê濮囨い鏇ㄥ幘缁粯銈ｉ崘鈺佲偓鍨箾閹寸偟鎳愰柣鎺嶇矙閺岋綁顢橀悢椋庮儌缂備浇椴哥敮锟犲箖閳轰胶鏆﹂柛銉戔偓閸氬倹淇婇悙顏勨偓銈夊磻閸曨厽宕查柟閭﹀枛瀵弶淇婇悙顏勨偓鏇犳崲閹邦喒鍋撳闂寸敖婵″弶鍔欏畷濂稿即閻斿弶瀚奸梻浣告啞缁嬫垿鏁冮妷锕€绶為柛鏇ㄥ灡閻撴洘淇婇娑楄埅闁稿鍨介弻娑㈠煛閸屾粍鍒涢悗瑙勬礀閵堝憡淇婇悜鑺ユ櫆閻熸瑥瀚褰掓⒒閸屾瑧顦﹂柟璇х磿缁瑩骞嬮敂鑺ユ珖闂侀潧锛忛崒婊冨⒕濠电偛顕崢褔鎮洪妸鈺傚亗闁绘柨鍚嬮悡鐔兼煛閸愶絽浜惧┑鐐插悑閻熲晛鐣峰┑鍡╂僵闁煎摜鏁搁崢浠嬫⒑閹稿海绠撴繛璇х畵瀵娊顢楅崒妤€浜鹃悷娆忓缁€鍫ユ煕閻樺磭澧甸柕鍡曠閳藉螣闁垮娼旈梻浣告贡閸庛倝骞愰幖渚囨晜鐟滅増甯楅埛鎺楁煕鐏炲墽鎳呮い锔肩畵閺岀喓鎷犺绾捐法绱掗鐣屾噰妤犵偛顑夐弫鍌炴嚍閵夛妇褰囬梻鍌欑劍鐎笛囧蓟閵婏附娅犻柣锝呰嫰椤ユ岸鏌ら幁鎺戝姕闁告瑥绻戞穱濠囶敍濮樺彉铏庨梺缁樻尰閸旀瑩寮婚敐澶婄閻庢稒顭囬ˇ鏉课旈悩闈涗沪闁绘顨呴…鍥疀濞戞顦悷婊冪箻閺佸秹鎮㈤崗灏栨嫼闂佸湱顭堝ù鐑藉煡婢跺瞼纾煎璺侯儐鐏忥箓鏌嶉妷顖氼洭闁圭懓瀚版俊鎼佹晝閳ь剟寮搁崒鐐粹拺闁告稑锕ユ径鍕煕閹惧娲撮挊婵嬫煏婵炑冩噽閿涙繃绻涙潏鍓ф偧妞ゎ厼鐗撻崺鈧い鎺嗗亾婵犫偓闁秴鏋佹い鏇楀亾闁诡喗鐟╁畷顐﹀礋椤撶偛袝濠碉紕鍋戦崐鏍暜閹烘鏅濋柨鏂垮⒔閻捇姊婚崼鐔烩偓浠嬫偡闁妇鍙嗛梺鍛婁緱閸樺搫鈻介鍕垫富闁靛牆鍟俊鎼佹煕鎼淬劍娑ч柣锝囧厴瀹曞ジ寮撮妸锔芥珜濠电偠鎻徊钘夘嚕閸撲讲鍋撳鍐蹭汗缂佽鲸鎹囧畷鎺戭潩椤戣棄浜鹃柣鎴ｅГ閸婂潡鏌ㄩ弴鐐测偓褰掑疾椤忓嫧鏀介柣妯诲墯閸熷繘鏌涢悩宕囧⒌闁诡啫鍕瘈闁告洦鍓欐惔濠傗攽閻愭潙鐏熼柛銊ユ贡缁牓宕掗悙瀵稿幘濠电偞娼欓鍡椻枍閸℃稒鐓曢柨婵嗗瀹撳棝鏌″畝瀣暠閾伙綁鏌ｉ幘鍐差劉闁诲繐鐗撳铏规嫚閳ヨ櫕鐏嶅銈冨妼閿曨亜顕ｉ锕€绠涙い鎾跺枎閸斿懘姊洪悙钘夊姤閻忓繑鐟╅獮鎰緞婵炵偓鏂€闂佺粯鍔樼亸娆撳箺閻樼數纾兼い鏃囧亹鑲栭梺鍛婂笚鐢繝鐛Ο鑲╃＜婵☆垵妗ㄧ花鍨繆閻愵亜鈧牠宕濊缁骞嬮敂钘夆偓宄扳攽閻樺弶澶勯柣鎾崇箰閳规垿鎮╅懠顒傤唺闂佷紮缍€娴滎剟鎯€椤忓牆绾ч悹鎭掑壉瑜庨幈銊︾節閸愨斂浠㈤梺纭呮珪閻楃娀宕洪埄鍐瘈闁告洦鍋勬瓏缂傚倸鍊搁崐鎼佸磹閸濄儳鐭撻柟缁㈠枟閺呮繃銇勮箛鎾愁伌闁搞倖娲熼幃褰掑炊瑜庨埢鏇㈡煕濮橆剦鍎忔い顓℃硶閹瑰嫭绗熼姘闂備浇鐨崘顭戜痪缂備胶绮换鍫熸叏閳ь剟鏌ㄥ┑鍡樺櫧闁告﹩鍋婇弻锕傚礃椤旂粯鍠氶梺鍝勮嫰缁夊爼骞忛悩缁樺殤妞ゆ巻鍋撴い锝嗘そ閺屟呯磼濡厧鈷岄梺鍝勭焿缁蹭粙锝炲鍫濈劦妞ゆ巻鍋撴い顓炴穿椤﹀磭绱掗崒娑樻诞闁轰礁鍟村畷鎺戔槈濮橆剙绠洪梻鍌欒兌缁垶寮婚妸銉殨閻犻缚銆€閺嬪秹鏌涘☉妯兼憼闁绘挾鍠栭弻銊モ攽閸℃ê娅ｅ┑鈩冨絻椤兘骞楅崼鏇熸櫜闁糕剝鐟ч鏇㈡⒑缁洖澧查柣鐔村劜缁傚秵銈ｉ崘鈺婃闁诲函缍嗛崰妤呭煕閹烘鐓曢悘鐐插⒔閹冲懏銇勯敂鑲╃暤闁哄瞼鍠撻幏鐘侯槾缂佲檧鍋撻柣搴ゎ潐濞叉粓銆佹繝鍥﹂柟鐗堟緲缁犳娊鏌熺€电啸闁哄鍟村缁樻媴缁涘缍堥悗瑙勬礃閿曘垽銆佸鎰佹▌闂佽鍠掗埀顒佸墯濞笺劑鏌嶈閸撶喎顕ｆ繝姘亜闁告稑锕︾粔鑸典繆閵堝繒鍒伴柛鐕佸灦椤㈡挸顓兼径瀣ф嫼缂備礁顑呯亸鍛村礉閻斿吋鐓曢煫鍥ㄦ閼版寧顨ラ悙鎻掓殻闁诡喚鍏橀獮濠冪節閸愨斂浠㈠銈冨灪濡啫鐣烽崡鐐╂瀻闁瑰濮撮悙濠囨⒒閸屾艾鈧嘲霉閸パ屾禆闁靛ě鍛劶婵炴挻鍩冮崑鎾绘煙椤旂煫顏堝煘閹寸姭鍋撻敐搴濈敖闁告ɑ鎸冲铏规兜閸涱喖娑ч梻鍌氬鐎氭澘鐣烽幇顓фЧ閹煎瓨锚娴滈箖鏌ｉ悢鍛婄凡妞ゃ儱绻橀弻娑㈡偐閹颁焦鐣烽梺鍝勬噷閸庨亶鍩為幋锔藉亹闁割煈鍋呭В鍕⒑缁嬫鍎愮紒瀣灴椤㈡岸鏁愭径濠勵槶婵炶揪绲块…鍫ユ倶婵犲洦鈷戦悷娆忓閸斻倗鐥紒銏犲籍鐎殿喗濞婇弫鍌炴嚍閵夈儱浼庢繝纰樻閸ㄨ京鈧瑳鍛厹闁告挆鍛紲闂佺粯锚閸熷潡鍩㈤弴銏＄厸鐎光偓閳ь剟宕伴幘璇茬劦妞ゆ帊鑳堕埊鏇㈡嫅闁秵鐓冮梺鍨儏婵秹鏌″畝瀣ɑ闁诡垱妫冮崺銉╁幢濞嗗繑鍊┑鐘愁問閸犳牠鏁冮妸銉㈡瀺闁挎繂顦粻鐔兼煙缂併垹鏋涚紒鈧€ｎ偁浜滈柟鎵虫櫅閻忊晝鎮Ο鑲╃＝闁稿本鐟чˇ锕€顭胯缁瑩骞栫憴鍕劅闁靛鍎抽悡鎴︽⒑閸涘﹤濮﹂柛妯圭矙钘熼柕鍫濐槹閳锋帒銆掑锝呬壕濠电偘鍖犻崱妤婃澓闂傚倷绀侀幖顐﹀箠韫囨洖鍨濋柟鎹愵嚙閺勩儲绻涢幋娆忕仼缂佺媴缍侀弻銊╁籍閸屾稒鐝梺鍛娚戦崕鎶藉煘閹达附鍊烽悗娑欘焽缁嬪洤顪冮妶鍡楃仴婵☆偅绻傞锝夊箚閼割兛姹楅梺鍦劋閹搁箖宕㈤悽鍛娾拺闁告稑锕ら悘鐔兼煕婵犲喚娈樼€殿啫鍥х劦妞ゆ帒瀚埛鎴︽煕濠靛棗顏繝鈧导瀛樼厽闁冲搫锕ら悘锕傛煟濞戝崬鏋涢摶锝夋煟閹惧啿鐦ㄦ俊顐ｇ矒閺岋絾鎯旈婊呅ｆ繛瀛樼矎濞夋稖鐏嬮梺缁樻煥閸氬鎮￠悢鍏肩厽闁归偊鍓﹂崵鐔搞亜閿濆棛鍙€闁哄矉缍侀幃銏ゅ矗婢跺褰嬮梻浣虹帛娓氭宕抽敐鍜佸殨濞寸姴顑傞埀顒佺墵婵＄兘濡烽埡浣稿強婵＄偑鍊戦崹娲€冩繝鍥ф槬闁逞屽墯閵囧嫰骞掑鍡╂▊缂備浇顕уΛ妤呮箒闂佺粯锚濡﹪宕曢幇鐗堢厽闁规儳鍟块弳锝嗘叏婵犲啯銇濈€规洖缍婇、姘跺川椤撶偛顥嶉梻鍌欐祰椤曆勵殽韫囨洜涓嶉柟鎹愵嚙閽冪喖鏌ｉ弬鎸庢喐闁荤喎缍婇弻娑⑩€﹂幋婵囩亪濡炪値鍋勫ú顓烆潖閾忚瀚氶柍銉ㄦ珪閻忔捇姊虹粙璺ㄧ闁挎洏鍨介悰顕€宕橀褎鈻岄柣搴ゎ潐濞叉牠濡堕幖浣哥畺闁靛繈鍨婚惌娆撳箹鐎涙ɑ灏ù婊冨⒔閳ь剛鎳撶€氼厽绔熺€ｎ喖缁╁ù鐘差儐閻撶喐淇婇娑欍仧闁哥喎绻橀弻锟犲幢閳轰胶浠搁梺鍝勮嫰缁夌兘篓娓氣偓閺屾盯骞樼€靛憡鍒涢悗瑙勬礃閸ㄦ寧淇婇幖浣哥厸濞达絿灏ㄧ槐閬嶆⒒娓氣偓濞佳呮崲閸儱纾归柡宥庡幗閸嬪倹绻涢崱妯哄濞存粍绮撻弻锟犲礃閵娿儮鍋撴繝姘闁稿本绋撶粻楣冩煕椤愩倕鏋戦柍閿嬪姍閺屾洟宕惰椤忣厽銇勯姀鈩冪闁轰焦鍔欏畷鍫曞煛閸愨晜绶伴梻鍌氬€峰ù鍥敋閺嶎厼绐楅柟鐑橆殔缁€鍫熺節闂堟侗鍎忕紒鐘冲哺閺岋繝宕橀妸褍顣洪梺缁樻尪閸ㄤ粙寮诲鍫闂佸憡鎸鹃崰鏍偘椤旇法鐤€婵炴垼椴搁弲婵嬫⒑閹稿孩鈷掗柡鍜佸亰瀹曘垺绂掔€ｎ偆鍘甸梺绋跨箺閸嬫劙寮冲鈧弻娑欑箾閸喒鍋撻弴鈶┾偓锕傚炊椤掆偓缁犳稒銇勯幘璺盒ユい鏃€娲熷娲川婵犲嫭鍣у銈忕畳娴滎剛鍒掓繝姘€烽柣鎴烆焽閸欏棗鈹戦悩缁樻锭闁绘妫欑粋鎺楁晜闁款垰浜鹃柛顭戝亝缁舵煡鎮楀鐓庡⒋闁诡喗鍎抽埞鎴犫偓锝庝簽閸旓箑顪冮妶鍡楃瑨閻庢凹鍙冨畷鏇炍旈埀顒勨€﹂崸妤佸殝闂傚牊绋戦～宥夋⒑缂佹ɑ灏伴柣鐔叉櫊瀵鏁愭径濠勵吅闂佺粯鍔曞Λ娆撳垂閸ф绠栭柍銉︽灱濡插牓鏌曡箛銉х？闁告﹢浜堕弻锝嗘償椤栨粎校闂佺顑呴幊搴ㄦ偩瀹勬壆鏆嗛柛鏇ㄥ墰閸樺憡绻涙潏鍓ф偧闁硅櫕鎸婚幈銊╁醇閵夛妇鍘靛銈嗙墬缁嬫帡鎮￠妷鈺傜厓閻熸瑥瀚悘瀵糕偓瑙勬礈閸樠囧煘閹达箑骞㈡俊顖氬悑椤粍绻濋悽闈浶ユい锝庡枤濡叉劙寮撮姀鐘碉紱闂佺鎻粻鎴犲瑜版帗鐓欓弶鍫濆⒔閻ｈ京鐥幆褎鍋ラ柡灞诲€楅崰濠囧础閻愬樊娼介柣搴ゎ潐濞叉﹢鎮￠敓鐘茶摕婵炴垶顭囬弳鍡涙煃瑜滈崜鐔风暦閹达箑绠涢柡澶庢硶閸旓箑顪冮妶鍡楃瑐闁绘帪绠撹棢闁割偀鎳囬崑鎾舵喆閸曨剛顦ㄩ梺鎸庢磸閸ㄤ粙濡存担绯曟瀻闁规儳鍟跨花銉︾節閵忥綆鍤冮柛銊︽緲鐓ら柨鏇炲€归崑鍌炴煛閸ャ儱鐏柣鎾冲暣閺屽秵娼幍顕呮М閻熸粓顣︾欢姘跺蓟閻斿憡缍囬柛鎾楀懏娈哥紓浣哄亾閸庡啿顭囬敓鐘靛祦闁哄稁鍋勯崹婵嬫偡濞嗗繐顏撮柍褜鍓欏Λ婵嬪蓟閿熺姴鐒垫い鎺嶈兌椤╃兘鎮楅敐搴′簽闁告ü绮欏铏规喆閸曨偒妫嗘繝鈷€鍕垫當闁宠棄顦抽ˇ褰掓煙椤旇崵鐭欐い銏＄☉閳规垿宕卞▎蹇撶細缂傚倸鍊烽懗鍓佸垝椤栨粎鐭欓柟鐐灱濡插牓鏌涢…鎴濅航婵℃彃缍婇獮鏍ㄦ綇閸撗勫仹濠碘剝褰冨ú顓㈠蓟閿濆棙鍎熼柕鍫濆缂嶅牆鈹戦悙鎻掔骇闁挎碍銇勯鍕殲缂佸倹甯為埀顒婄秵娴滄繂危椤掑嫭鈷戦梺顐ゅ仜閼活垱鏅堕鐐寸厪闁搞儜鍐句純濡ょ姷鍋炵敮鎺楊敇閸忕厧绶為悗锝囶暯閸嬫捇寮介妸褏顔曢柣搴㈢⊕椤洭鎯岀€ｎ剛纾兼い鏃囧Г瀹曞瞼鈧鍠栭…鐑藉箖閵忋倖鍋傞幖瀛樼箘閻愬﹪姊绘担鍛婂暈婵炶绠撳畷婊堟晝閳ь剝鐏嬮梺缁樺姇椤曨厾绮绘ィ鍐╁€垫繛鎴炵懐閻掍粙鏌ｉ鐔风缂佽鲸甯￠幃鈺佺暦閸パ€鎷伴柣搴㈩問閸犳牠鈥﹂悜钘夋瀬闁圭増婢橀獮銏′繆椤栨碍鎯堝┑鈩冨▕濮婄粯绗熼埀顒€顭囪閹广垽宕卞☉妯肩枃闂佹悶鍎洪崜娆撳礄閻樼粯鐓涢柛鎰╁妿婢ф盯鏌嶉柨瀣伌闁哄本绋戦埞鎴﹀幢濡ゅ﹣鐥梻渚€娼荤紞鈧俊顐㈠閸╃偤骞嬮敂钘夆偓鐑芥煃鏉炵増顦峰瑙勬礋濮婂宕掑▎鎺戝帯缂備緡鍣崹杈╃箔閻旇偤鏃堝川椤撱垺锛楅梻浣瑰缁诲倿骞婇幇鏉挎辈闁挎洖鍊归悡鏇熶繆閵堝懎鏆欏ù婊嗩潐娣囧﹪骞撻幒鏂款杸婵烇絽娲ら敃顏堛€佸☉妯锋斀闁糕剝娲橀惈蹇旂節閻㈤潧浠ч柛妯犲泚鍥濞戣鲸缍庣紓鍌欑劍钃卞┑顖涙尦閹嘲鈻庤箛鎿冧患婵炲濮弲鐘差潖閾忓湱鐭欓柛顭戝枤濡蹭即姊洪棃鈺冪Ф缂佽弓绮欓、姘舵晲婢跺﹦顔岄梺鐟版惈濡瑩寮埀顒勬⒑鐠囨彃鍤辩紓宥呮缁傚秹鎮欓幖顓燁啍闂佹悶鍎洪崜姘跺煕閹寸姵鍠愰柣妤€鐗嗙粭姘舵煥濞戞艾鏋涢柡宀嬬秮楠炴帡鎮欓悽鍨闂備浇顕栭崳顖滄崲濠靛绠栭柕蹇嬪€栭崑鍌炲箹鏉堝墽绉甸柛鐔锋喘濮婄粯鎷呴崨濠呯闂佸啿鍢查悧鎾崇暦閵忥紕闄勯柛娑橈工閳ь剙鐖奸弻銊╂偄閸濆嫅锝夋煟閹惧啿鏆熼柟鑼焾椤劑宕煎┑鍫Н婵犵數鍋涘Λ娆撳箰閸濄儱顥氶柛褎顨嗛埛鎺楁煕椤愩倕鏋旈柕鍡樺浮閺岋繝宕遍銏☆€嶆繛锝呮搐閿曨亪銆佸☉妯锋闁告鍋涙俊鍏肩節瀵版灚鍊曢拕鍏笺亜閺囧棗娲犻埀?")
        elif learner_signal == "curious":
            parts.append("婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽弫鎰板川閸屾粌鏋庨柍璇查叄楠炲棜顦虫い鏂垮缁辨捇宕掑▎鎺戝帯婵犳鍠楅幐鎶藉箖濡警娼╅悹杞扮秿閿曞倹鐓曢柡鍥ュ妼閺嬨倝鏌ｉ妶鍌氫壕闂傚倷绀佸﹢閬嶅磻閹捐绠氶悘鐐跺▏濞戙垺鍊烽柣銏㈡暩閿涙繃绻涙潏鍓ф偧闁哄拋鍋婂畷濂割敂閸喓鍘辨繝鐢靛Т閸熸壆绮婚悙纰樺亾濞堝灝鏋涙い顓犲厴楠炲啴濮€閵堝棙鍎梺闈╁瘜閸橀箖宕㈤鐐粹拻濞达絿顭堥ˉ蹇涙煟閹惧磭澧︾€规洘濞婇、姘跺焵椤掆偓閻ｅ嘲鈹戦崶褏绐為梺褰掑亰閸樻悂骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囶亞鐣垫鐐诧躬瀹曟﹢顢旈崱娆欑床缂傚倸鍊烽悞锕傛晝椤愶附鍤€閻犳亽鍔夐崑鎾斥枔閸喗鐏堝銈庡幘閸忔ê顕ｉ锕€绠涙い鎾跺仧缁愮偞绻濋悽闈浶㈤悗姘卞厴瀹曘儵宕ㄧ€涙ǚ鎷绘繛杈剧秬濞咃絿鏁☉娆嶄簻妞ゆ挾鍋熸晶鏇㈡煃鐠囪尙效鐎殿喗鎸虫慨鈧柍銉ュ帠閹撮攱淇婇悙顏勨偓鏇犳崲閹扮増鍋嬪┑鐘叉搐绾惧綊鏌ｉ姀鐘冲暈闁稿鍓濈换娑㈠幢濡ゅ啰顔囧銈呮禋娴滎亪骞冨Ο璺ㄧ杸闁挎繂鎳嶇花鐣岀磽娴ｄ粙鍝洪悽顖ょ節楠炲﹤顭ㄩ崼鐕佹濠电偞鍨惰摫闁硅櫕鐟╅弻锝嗘償閵忊晛鏅遍梺鍝ュУ閻╊垶銆佸鎰佹▌闂佺硶鏂傞崕鎻掝嚗閸曨垰绠涙い鎺戭槹缂嶅倿姊绘担铏瑰笡閽冮亶鏌ｅΔ浣瑰磳鐎规洘绻傞鍏煎緞婵烆澁绠撻弻娑㈠即閵娿儳浠╃紓渚囧亜缁夊綊寮诲☉姘勃闁硅鍔曢ˉ婵囩箾鐎电校闁挎碍銇勯鍕殻濠德ゅ煐閹棃鍨鹃懠顒傚煃闂傚倷绀侀幖顐﹀箠閹邦厽鍙忛柟缁㈠櫙缂嶆牠鐓崶銊﹀婵炲樊浜堕弫鍌炴煕閺囥劌澧紒浣藉煐娣囧﹪鎮欓鍕ㄥ亾閺嶎厼绠板Δ锝呭暙缁愭骞栫划瑙勵€嗛柡瀣⒒閳ь剙鍘滈崑鎾绘煕閺囥劌鍘撮柟鐤缁辨捇宕掑▎鎴濆濡炪値鍘煎ú锕傚疾閸洦鏁傞柛顐ゅ枔閸橆亪姊洪崜鎻掍簴闁糕晛瀚伴幃鐐烘倷椤戝彞绨婚梺鍝勬祩娴滅偟绮欓懡銈囩＜缂備焦顭囩粻鎾淬亜椤愶絿绠炴い銏☆殜閸┾偓妞ゆ巻鍋撻柣锝囨暬瀹曞崬鈽夊▎灞惧缂傚倸鍊烽悞锕佹懌濡炪們鍎卞Λ娆戞崲濞戙垹妞介柛鎰典簽琚﹂梻浣筋嚃閸垳娆㈠顒傛殾濠靛倻顭堝敮闂佹寧姊荤划顖炈夋繝鍐х箚闁绘劦浜滈埀顒佺墵瀹曟繈骞嬮敃鈧崹鍌炴煟閹寸伝顏嗘閻愮儤鐓曢柡鍥ュ妼楠炴鐥幆褋鍋㈤柟顔筋殜閺佹劖鎯旈垾鑼泿婵犵數鍋為幆宀勫窗濡ゅ懎桅闁告洦鍨伴～鍛存煃閳轰礁鏆欑痪鏉跨Т椤啴濡堕崱妯虹闂侀潧鐗忛…鍫ユ偩閻戣棄閱囬柡鍥╁仧閸樻悂姊洪崨濠傚婵炲娲熷濠氼敍濞戞氨鐦堥梺姹囧灲濞佳勭閳哄懏鐓欐繛鑼额唺缁ㄧ晫绱掓潏鈺佷沪闁瑰嘲鎳橀幖褰掑捶椤撱劎闂┑鐘愁問閸犳鏁冮埡鍛闁挎洖鍊归崐鐢告煕椤愶絾绀冮柣鎾寸懇濮婂宕掑鐓庢闂佸憡鏌ㄧ粔褰掑蓟閿濆绠婚悗娑欘焽椤︿即姊洪崫鍕拱婵炲弶顭囬幑銏犫槈閵忕姴鐎銈嗘⒒閸樠嗩暯闂傚倸鍊烽懗鍓佹兜閸洖鐤炬い蹇撴缁躲倝鏌涜椤ㄥ懘鎮為崹顐犱簻闁瑰搫绉剁拹浼存煕閻旈绠婚柡灞剧洴閹晛鐣烽崶銊ュ灡婵＄偑鍊戦崹鐑樼┍濞差€洩銇愰幒鎾跺幈闂佸磭鎳撻悘婵嬪礉濠婂應鍋撻崹顐ｇ凡閻庢凹鍘鹃幑銏犫攽閸ャ劌鍔呴梺闈涚箳婵妲愰敃鍌涒拻闁稿本鐟ㄩ崗宀€鐥鐐靛煟鐎规洘绮岄埞鎴犫偓锝冨妷閸嬫捇宕橀鐓庤€垮┑鐐村灦椤洭鏁嶅▎蹇ｆ富闁靛牆妫涙晶閬嶆煕鐎ｎ剙浠遍柛鈺傜洴楠炴帡骞婇妸銉хШ闁轰焦鍔欏畷銊╊敊閸忓吋鐣奸梻鍌欑閹芥粓宕伴幘璇茬；婵炴垯鍨硅繚闂佸湱鍎ら崺鍫濐焽閳哄倶浜滈柟鐐殔鐎氼噣寮惰ぐ鎺撶厽閹兼番鍊ゅ鎰箾閸欏澧辩紒杈╁仦缁绘繈宕堕埡浣恒偊闂佺澹堥幓顏嗗緤閹稿簺浠氶柟鎯板Г閸婄敻鏌ㄥ┑鍡涱€楀ù婊勭箖缁绘盯宕ㄩ钘夌闂佸疇顫夐崹鍧楀箖閳哄拋鏁婇柤娴嬫櫃缁辨ɑ绻濋悽闈涗粶妞わ附澹嗙划娆撳冀閵婏附鐝峰┑鐘绘涧椤戝棝鍩涢幋锔藉仩婵炴垶宸婚崑鎾诲礂閸涱収妫滃┑鐘垫暩閸嬫盯顢氶鐔稿弿闁圭虎鍣弫鍕煕閳╁啰鈯曢柛瀣€块弻娑㈠箛闂堟稒鐏嶉梺缁樻尭缁绘劙鈥︾捄銊﹀磯闁惧繒鎳撻。娲⒑閸涘﹥鈷愮€光偓閹间礁钃熼柨鐔哄Т楠炪垺鎱ㄥ鍡椾簻闁诡垰鐗忕槐鎾存媴娴犲鎽甸柣銏╁灲缁绘繈鐛崘顕呮晜闁告洏鍔嶉悗濠氭椤愩垺澶勯柡灞诲姂钘濋柍鍝勬噺閳锋垹绱撴担鑲℃垹浜告导瀛樼厽闁绘洖鍊婚悾闈涒攽閿涘嫭鏆€规洜鍠栭、娑橆潩鏉堚晜缍侀梻鍌欒兌椤牓寮甸鍕殞闁绘劦鍓涢々閿嬫叏濡炶浜惧┑顔硷攻濡炰粙寮婚崨瀛樺€烽柤鑹版硾椤忣厽绻濋埛鈧仦鐣屼桓闂佸搫鐬奸崰鏍€佸▎鎾村亗閹煎瓨锚娴滈箖鏌涜椤ㄥ牆鐣垫笟鈧弻娑㈠箛閵婏附婢撻梺绋款儏閹虫﹢寮诲☉銏犵疀闁靛闄勯悵鏃堟⒑闁偛鑻晶顔姐亜椤撶姴鍘寸€殿喖顭锋俊鑸靛緞婵犲嫮鏆㈤梻浣告贡閸庛倝宕归崹顐ｅ弿閹兼番鍔嶉埛鎴︽⒑椤愩倕浠滈柤娲诲灡閺呭爼顢欐慨鎰盎濡炪倖鎸炬慨鎾储鐎电硶鍋撳▓鍨灈妞ゎ厾鍏樺顐﹀礃椤旇偐鍔﹀銈嗗笒閸熺増绂嶆禒瀣拻濞达綀娅ｇ敮娑㈡煠瑜版帞鐣烘い銏″哺椤㈡﹢鎮╅悽鐢靛姸闂備胶纭堕崜婵堢矙閹烘鐓曢柟杈鹃檮閻撴洟鏌熼柇锕€澧紒鐙欏洦鐓欐い鏍ㄦ皑婢э箓鏌″畝鈧崰鏍х暦濮椻偓閹崇娀顢楅崒銈呮櫔闂傚倷娴囬鏍疮閹捐围闁搞儮鏅滃鎴︽⒒娴ｅ憡璐￠柧蹇撻叄瀹曞綊鏌嗗鍛棟闂侀€炲苯澧存慨濠勭帛閹峰懘鎼归悷鎵偧婵＄偑鍊ら崢濂告偋韫囨梻顩茬紒瀣氨閺嬪酣鏌熺€电小缂佹顦靛铏规喆閸曨偄濮告繝娈垮枔閸婃繈骞冮敓鐘冲亜闁稿繗鍋愰崣鍡椻攽閻樼粯娑ф俊顐ｇ⊕閺呭爼鏁冮崒娑氬幈濠电娀娼уú锕傚Φ濠靛鐓涢悘鐐靛亾缁€瀣偓瑙勬礃閸庡ジ藝閸欏浜滈煫鍥风到婢ф壆绱掓潏銊ユ诞闁诡喒鏅涢悾鐑藉炊閵娿儱鐏″┑掳鍊楁慨鐑藉磻閻愯　鈧箓宕堕鈧粻鏌ユ煕閺囥劌鐏￠柟顖滃仱閺岋綁鎮㈤崨濠勫嚒缂備胶濮烽崕銈囨崲濠靛鍋ㄩ梻鍫熷垁閿濆棎浜滈柡鍐ｅ亾闁绘濮撮悾閿嬪閺夋垵鍞ㄥ銈嗘尵閸犳劕鈻嶉崶顒佲拺闂傚牊渚楀Σ鍫曟煕鎼粹剝鎯堥柕鍡樺笚缁绘繂顫濋鐘插籍婵犵妲呴崹顖滄媰閿曗偓鍗辨繛宸簼閻撴盯鏌涢埥鍡楀籍婵＄虎鍣ｉ弻鏇㈠炊瑜嶉顓燁殽閻愬弶鍠樼€规洘绮嶉幏鍛存倻濡椿鍟呯紓鍌氬€搁崐椋庢媼閺屻儱纾婚柟鍓х帛閸婄敻鏌ㄥ┑鍡涱€楀ù婊勭墪闇夋繝濠傚閻帡鏌″畝鈧崰鏍嵁閹达箑绠涙い鎾跺О閳ь剚鍔欏娲川婵犲啫纾虫繛瀛樼矊閻栫厧顕ｆ繝姘櫢闁绘ɑ褰冮懓鍧楁⒑鐎圭姵銆冩俊鐐村浮瀹曠増绻濋崒妤佹杸濡炪倖姊婚妴瀣礉閻旇櫣纾兼い鏇炴噹閻忥附顨ラ悙鑼鐎规洏鍔戝鍫曞箣濠靛牏宕烘繝鐢靛Х閺佸憡鎱ㄩ幘顔肩疇闁规媽鍩囬埀顑跨窔瀹曘劎鈧稒菤閹风粯绻涙潏鍓ф偧妞ゎ厼鐗撳鎶芥焼瀹ュ棛鍘遍梺闈涢獜缁辨洟宕ｉ埀顒勬⒑鐠団€虫殭闁搞儜鍜佸晪闁诲氦顫夊ú鏍洪敃鈧埢鎾淬偅閸愨斁鎷洪梺鑽ゅ枛閸嬪﹪宕甸悢鍏肩厱閻庯綆鍓欓弸鏃傗偓娈垮暙閸パ呭姦濡炪倖甯掔€氼參鍩涢幋鐘电＜閻庯綆鍋勯婊勭節閳ь剟骞嶉鍓э紲濡炪倖妫侀崑鎰摥闂備礁纾划顖炲箰婵犳艾围闁挎繂顦粈鍐煃閸︻厼浜鹃悗姘偢濮婄粯鎷呴崨濠傛殘缂備礁顑嗛崹鍧楀极閸愵喗鏅滈柛鎾楀倻鐟濋梻浣烘嚀婢х晫鍒掗鐐茬９闁割煈鍋呴崣蹇旀叏濡も偓閻楀繘宕氶弶妫电懓顭ㄩ崼銏㈡毇濠殿喖锕︾划顖炲箯閸涙潙宸濆┑鐘插暙閸撶敻姊绘担鍛婃喐闁革絻鍎靛畷鎴炵節閸パ呯暫閻熸粍鏌ㄩ悾鐑藉础閻愬秵姊圭换婵嬪磼濞戞瑧褰嬫繝鐢靛Х閺佸憡绻涢埀顒佺箾娴ｅ啿鍘惧ú顏勵潊闁挎稑瀚峰ú绋库攽閻樿宸ラ柣妤€锕幃鈥斥槈閵忥紕鍘遍梺瑙勫閺呮稒淇婃禒瀣厵闁稿繒鍘ф慨澶愭煙椤曞懎鏋涙い顐ｇ箞閹虫粎鍠婂Ο璇差伖缂傚倸鍊搁崐鐑芥倿閿曞倵鈧箓宕堕埡鍐х瑝闂侀潧顦弲婊堟偂閺囥垺鍊甸柨婵嗙凹閹秹妫呴澶婂闁逞屽墯椤旀牠宕伴弽顓涒偓锕傛倻閽樺鐎梺鍦濠㈡﹢鐛姀鈥茬箚妞ゆ牗纰嶉幆鍫濃攽閳╁啫鈻曟慨濠勭帛閹峰懘宕崟顏嗙处闂備胶顭堥柊锝嗙鐠鸿櫣鏆︽い鏍仜缁犱即骞栧ǎ顒€鐏紒澶婄埣濮婃椽宕ㄦ繝鍕ㄦ闂佸鏉垮闁糕晜鐩獮瀣偐閻㈢绱查梺璇插嚱缂嶅棝宕戦幒妤€纾块柕澶嗘櫆閻撴洟骞栧ǎ顒€鐏╁┑顔肩Ч閺屸€崇暆閳ь剟宕伴弽顓炵畺闁绘垼濮ら崑瀣煕椤愶絿绠栭柣蹇撻叄閺岋絾鎯旈姀鈺佹櫛闂佸摜濮甸惄顖炪€佸鎰佹▌闂佺硶鏂傞崕鎻掝嚗閸曨垰绠涙い鎺戭槹缂嶅倿姊绘担铏瑰笡妞ゎ厼娲顐﹀箹娴ｅ摜楠囬梺褰掓？閻掞箓鍩涢幒鎳ㄥ綊鏁愰崟顕呭妳闂佺粯甯掓晶鐣屾閹烘梻纾兼俊顖氭惈椤帒螖閻橀潧浠︽い銊ユ嚇閳ワ箓濡搁埡渚€鍞跺┑鐘绘涧濞层劑鍩€椤掑澧存慨濠冩そ瀹曨偊宕熼鐐€囬梺璇茬箳閸嬬偤宕曢幎鑺ュ剨婵犲﹤鐗婇埛鎺戙€掑锝呬壕濠电偘鍖犻崶銊ヤ罕闂佺硶鍓濋妵鍌氣槈濡攱鐎婚梺瑙勫劤绾绢參宕㈤柆宥嗏拺閻熸瑥瀚ˉ瀣熆瑜庨〃濠囧箖閿熺姴鍗抽柕蹇ョ磿閸樻悂姊洪崨濠傚Ё缂佽尪濮ょ粋宥嗐偅閸愨斁鎷洪梺鐓庮潟閸婃洟寮抽柆宥嗙厸闁告侗鍨伴埢鍫ユ煙椤旇宓嗘い銏″哺閸┾偓妞ゆ巻鍋撻柣锝呭槻椤粓鍩€椤掍椒绻嗛柛娑橈攻閸庣喖鏌曡箛濠冾潑婵☆偄鍟撮幃妤冩喆閸曨剛锛橀梺鍛婃⒐閸ㄥ潡濡存担鍓叉建闁逞屽墴楠炲啫鈻庨幋婵囩€冲┑鈽嗗灥濡椼劍绔熼弴鐑嗘富闁靛牆妫欑亸鐢告煕鎼淬垹濮囬柕鍡樺笚缁绘繂顫濋鐘插妇闂備礁澹婇崑鍛崲閸愵啟澶婎煥閸愶絾鏂€濡炪倖鏌ｉ崝宀勫箠閹邦喖顥氬┑鍌氭啞閻撴瑧绱撴担濮戭亞绮鑸电厱閻庯絻鍔岄崝銈夋煃瑜滈崜婵嬶綖婢跺⊕鍝勵潨閳ь剟骞冮悜钘夌厸闁告侗鍘介悗顒勬⒑閻熸澘鈷旂紒顕呭灦瀹曟垿骞囬悧鍫㈠幐闂佺鏈敋闁告梹绮撻幃妤€顫濋崘韫睏缂備浇椴搁幑鍥х暦閹烘埈娼╂い鎴ｆ娴滈箖鏌ｉ幋锝呅撻柛濠傛健閺屻劑寮撮悙娴嬪亾瑜版帒鐤炬繝闈涱儐閻撳啴寮堕悙鏉戭€滄い鏂款樀閺岋紕鈧綆鍋呴ˉ鍫ユ煛瀹€瀣瘈鐎规洘锕㈤弫鎰板川椤掆偓椤ユ碍绻濋悽闈涘壋缂佽尪妫勭叅闁靛牆顦伴弲婵囥亜韫囨挾澧戦柍褜鍏涚欢姘嚕閹绢喖顫呴柍鈺佸暞閻濇娊姊绘担瑙勫仩闁稿寒鍣ｅ鎻掆攽鐎ｎ亝杈堝銈嗗姀閹冲洭寮ㄦ禒瀣厽闁瑰瓨绻冨婵嬫煕閹烘柨顣肩紒缁樼〒娴狅箓宕掑锝呬壕婵犻潧顑呴弸渚€鏌涢幇闈涙珮闁轰礁鍊块弻娑㈩敃閿濆洨鐣奸梺姹囧€曞ú銈夊煘閹达附鍋愰悹鍥囧啩绱ｉ梻浣虹帛椤ㄥ懘鏁冮鍕殾闁硅揪绠戞儫闂佹寧鏌ㄦ晶浠嬵敊閺囥垺鈷戦柛鎾村絻娴滅偤鏌涢悩鏌ュ弰妞ゃ垺鑹鹃…銊╁川椤栨粣绱插┑鐐存尰閼规儳煤閵堝棛顩查柣妤€鐗婇崣蹇撯攽閻樺弶鍣烘い蹇曞█閺岀喐顦版惔鈾€鏋呭Δ鐘靛仦閹瑰洭鐛幒妤€绠ｉ柣鎰仛琚犵紓鍌氬€搁崐鎼佸磹閹间礁纾归柛婵勫劤閻捇鏌℃径瀣婵炴垶菤閺€浠嬫煕閳╁啰鎳勬繛鍫ョ畺濮婅櫣娑甸崨顔兼锭缂備胶濮甸崹鐢割敊韫囨挴鏀介柛銉ｅ劙缁ㄥ姊虹憴鍕姢妞ゆ洦鍙冮崺濠囧即閵忥紕鍘介柟鍏肩暘閸ㄦ椽濡靛┑鍥ㄥ弿濠电姴鍟妵婵堚偓瑙勬处閸嬪﹤鐣烽悢纰辨晣婵炴垶鐟ч埀顒勪憾濮婄粯鎷呴崨濠傛殘闁活亜顦辩槐鎺楊敊閻ｅ本鍣板Δ鐘靛仜閸熸挳寮幘缁樺亹闁告劘寮撶花濠氭⒒娴ｇ鎮戠紒浣规尦瀵彃鈽夊┃澶告睏闂佸憡娲﹂崹閬嶅煕閹达附鐓欓柤娴嬫櫅娴犳粓鏌涢弮鈧敃銏ゅ蓟濞戙垹妫橀悹鎭掑壉閵堝洨纾兼い鏃囧亹婢э箓鏌涢埞鎯т壕婵＄偑鍊栫敮濠囨嚄閸撲胶涓嶅Δ锝呭暞閸婄敻鏌ｉ姀鈽嗗晱闁绘帒澧介幃顕€濡烽埡鍌楁嫼闂佸憡绻傜€氼參宕抽挊澶嗘斀闁绘劏鏅涙禍楣冩煟鎼淬埄鍟忛柛鐘崇洴椤㈡俺顦归柛鈹垮劜瀵板嫭绻濇惔銏犲厞闂備焦瀵х换鍌炲箠瀹ュ棛鐝堕柡鍥ュ灪閳锋垿鏌熺粙鎸庢崳缂佺姵鎸歌灃闁绘ê寮堕崯鐐电磼閸屾氨孝妞ゎ厹鍔戝畷姗€鏁愰崱妯绘緫濠碉紕鍋戦崐鏍ь潖婵犳艾鐓曢柛顐ｆ儕閿濆鎯為柛锔诲幘閿涙粓鏌℃径濠勫闁告柨鑻湁妞ゆ柨顫曟禍婊堟煏韫囥儳纾块柟鍐叉喘閺岀喖顢欓悡搴樻寖婵炲濯寸粻鎾荤嵁閸℃凹妲奸梺缁樼箥閸ｏ絽顫忔繝姘＜婵炲棙鍩堝Σ顔剧磽閸屾氨孝闁挎洦浜ｅΛ銏ゆ⒑鐟欏嫬鍔ら柣掳鍔戝畷锝堢疀濞戞瑧鍘电紓鍌欓檷閸ㄥ綊寮搁悢铏圭＜闁绘ê鍟垮ù顔芥叏婵犲懏顏犻柟椋庡█楠炴捇骞掗幋鐐垫И缂傚倸鍊搁崐鍝ョ矓閺夋嚦娑樷攽閸℃瑦娈鹃梺纭呮彧缁犳垹绮婚幎鑺ョ厵闁圭⒈鍘奸獮姗€鏌涢弮鍌氬幋婵﹥妞藉畷顐﹀礋椤愶絾顔勯梻浣虹帛椤ㄥ懘鏁冮鍫濇槬婵炴垯鍨圭粻鎶芥煙閻愯棄濡肩紓宥咃躬瀵偊骞囬弶鍨獩濡炪倖鏌ㄩ崥瀣枔濮椻偓濮婄粯鎷呯粵瀣異闂佹悶鍔嬮崡鎶藉箖瑜旈獮妯兼嫚閼艰埖鎲版繝鐢靛仦閸垶宕瑰ú顏勭；闁糕剝顦鸿ぐ鎺撴櫜濠㈣泛顑嗛悵鎶芥⒑閸濄儱孝闁挎洦浜獮鍐ㄎ旈崘鈺佹瀭闂佸憡娲﹂崜娑⑺囬妸鈺傗拺闁告稑锕ラ埛鎰版煟閻斿弶娅婇柟顔诲嵆椤㈡岸鍩€椤掆偓椤曪絾绂掔€ｎ€晠鏌ㄩ弴妤€浜惧銈呭閹稿墽妲愰幘瀛樺闁告挻褰冮崜浼存⒑鐠囪尙绠茬紒璇插€块崺銏ゅ箻鐠囧弬褔鏌涢埄鍐噮闁伙箑鐗撳鍝勑ч崶褏浼堝┑鐐板尃閸曨収娴勫┑鐘诧工鐎氼亞鎹㈤崱妯镐簻闁规澘澧庨幃濂告煙閸愬弶宸濋柍褜鍓濋～澶娒哄Ο鍏煎床闁割偁鍎冲畵渚€鎮楅敐搴℃灍闁稿﹪鏀辩换娑㈠醇閻斿鍤嬮梻浣斤骏閸婃牜鎹㈠┑瀣仺闂傚牊鍒€閵忋倖鐓ラ柡鍥埀顒佺箞楠炲啳顦崇紒缁樼箞瀹曞爼濡搁妷銈囨殫闂傚倷绀侀幉锟犲礉閿曞倸绐楁俊銈呮噺閸嬪倿鏌￠崶鈺佹灁缂佲檧鍋撻梻鍌氬€搁悧濠勭矙閹烘澶婎煥閸曗晙绨婚棅顐㈡处濮婂湱浜搁敃鍌涚厸閻忕偛澧介埊鏇㈡煙椤栨稒顥堝┑顔瑰亾闂佺粯锚閸氣偓缂佽鲸绻堝缁樻媴閸涘﹥鍎撻梺娲诲幖椤﹁京妲愰悙瀵哥懝闁逞屽墮椤曪綁顢曢敃鈧粻娑㈡煛婢跺﹦浠㈢紒鎰☉椤啴濡堕崱娆忣潷闂佽崵鍟欓崟鈺€绮撮梺瑙勫劶婵倝鍩涢幒鎴欌偓鎺戭潩閿濆懍澹曢梻渚€鈧偛鑻晶顖滅磼鐎ｎ偅宕岄柛鈺冨仱楠炴帒螖娴ｅ搫骞堥梻浣告惈閸婅棄鈻旈弴鈥斥偓鎾⒒娴ｇ儤鍤€缂佺姴绉瑰畷纭呫亹閹烘垹鍘撮梺鐟邦嚟婵參宕戦幘缁樻櫜閹煎瓨绻勯弫鏍⒑閹稿海鈯曠紒顔肩焸閸╃偤骞嬮敃鈧悡锟犳煕閳╁喚娈樺ù鐘虫綑閳规垿鍩勯崘锔跨不闂佸憡姊归崹鐢告偩瀹勯偊娼╅悹楦挎椤斿﹤鈹戞幊閸婃捇鎳楅崼鏇炲偍濞寸姴顑嗛悡娆撴煕韫囨艾浜归柡鍡橈耿閺屾稒绻涢崹顔瑰亾閺団懇鈧箓宕堕鈧粻娑欍亜閹捐泛啸妞ゆ梹娲栭埞鎴︽倷鐎涙绋囧銈嗗灥濡鍩㈠澶婄倞闁宠鍎虫禍楣冩煕椤垵浜濈紒鑸电叀閺屻劑寮撮妸銈夊仐闂佺粯渚楅崳锝呯暦閸楃儐娼╅柛蹇曗拡閳ь剙娲缁樻媴鐟欏嫬浠╅梺绋匡攻閻楃娀濡撮崘鈺冪瘈闁搞儜鍡樻啺婵犵數鍋為崹顖炲垂瑜版帒纭€闁规儼濮ら悡蹇撯攽閻愯尙浠㈤柛鏃€顨婇弻娑氣偓锝庡亝瀹曞矂鏌熼瑙勬珖缂佽鲸甯掕灒閺夌偞澹嗛惄搴ㄦ⒒閸屾瑨鍏岀紒顕呭灦楠炴劙宕妷銊バ￠梺鍏肩ゴ閺呮粓锝為弴銏＄厱妞ゆ劧绲剧粈鍐煃闁垮鐏撮柡灞剧☉閳藉顫滈崼鐔告毎缂傚倷璁查崑鎾绘煃瑜滈崜鐔奉潖閾忚瀚氶柤纰卞墰椤斿鎮楅崗澶婁壕濠殿喗绻傞張顒勬晬閸岀偞鈷掑〒姘ｅ亾婵炰匠鍥ㄥ亱闁糕剝铔嬮崶銊ヮ嚤闁哄鍨归崢閬嶆⒑閸︻厼鍔嬫い銊ユ閹繝寮撮姀鈥斥偓鍫曟煟閹邦厽缍戠紒鈧崘顭戠唵閻熸瑥瀚搁懓鍧楁煛鐏炵晫啸妞ぱ傜窔閺屾盯骞樼€靛憡鍣伴悗瑙勬礃閻撯€愁嚕婵犳艾唯闁挎柨澧介弳銏ゆ⒒閸屾艾鈧兘鎮為敃鍌氱畺闁割偅娲栫壕鎸庣節婵犲倻澧曠€瑰憡绻冮妵鍕籍閸屾粍鎲橀梺鍝ュ枎闁帮絽顫忔繝姘＜婵炲棙鍨垫俊浠嬫⒑濞茶绨荤紓宥咃工閻ｉ鎲撮崟顓犵槇濠殿喗锕徊娲磻閹剧粯鏅濋柛灞惧哺閸炲爼姊洪棃娑氱濠殿垼鍘艰灋婵犲﹤鎳愮壕浠嬫煕鐏炲墽鎳呴柛鏂跨У閵囧嫰顢橀悙鏉戠獩缂備緡鍠氱划顖炲Χ閿濆绀冮柍鍝勫暙楠炲秹姊虹拠鍙夋崳闁轰焦鎮傞垾锕傚醇閵夈儳顦梻渚囧墮缁夌敻鎮￠悢鍏肩厵闁绘垶锚閻忥箓鏌涢悢鍝勪户缂佽鲸甯炵槐鎺懳熼崗鐓庡灡婵°倗濮烽崑娑㈩敄婢舵劕绠栨繝濠傜墕閻愬﹪鏌ㄩ弮鈧畷妯兼崲閹达附鈷掗柛灞剧懆閸忓瞼绱掗鍛仸妤犵偞鍔欏畷濂稿即閻愮绱甸梻浣圭湽閸ㄥ鈥﹂崼銉﹀珔闁绘柨鎽滅粻楣冩煙鐎涙鎳冮柣蹇婃櫊閺岋綁骞橀崡鐐典紙闂佸搫鑻粔鐑铰ㄦ笟鈧弻娑㈠箻鐠虹儤鐎诲銈嗘穿缂嶄線鐛幘璇茬婵犻潧鐗嗗鎶芥⒒娴ｅ憡鍟為柛鏃€娲熷畷顖烆敍濠婂嫭娈板┑掳鍊曢幊搴ｇ不濮樿埖鐓涢柛鎰╁妿婢ф洟骞嗛悢鍏尖拺闁圭瀛╅ˉ鍡樸亜椤愩埄妲洪柍褜鍓氶惌顔惧垝濞嗗浚娼栫紓浣股戞刊鏉戙€掑鐓庣仯闁告梹鎮傚娲传閸曨厼鈷堥梺鍛婃尵閸犳牠鐛崘顔藉仾妞ゆ牭绲鹃埢宀勬⒑閼恒儔鎴犳崲閸儱钃熼柕濞炬櫅閸楁娊鏌ｉ幇顓犮偞闁稿鎹侀妵鎰板箳閹惧厖绨垫繝鐢靛仜濡瑩骞愭繝姘；闁挎繂顦伴悡鏇㈡煏婢跺牆鍔滈柟鍏煎姍閺岀喖鎼归銏狀潚闂佽鍨欢姘暦婵傜唯闁挎棁顫夌€氬ジ姊洪懡銈呅㈡繛鑼█閸┾偓妞ゆ帒鍟悵顏堟煟韫囨梹宕屾慨濠呮缁瑧鎹勯妸褜鍞归梻浣瑰濞插繘宕硅ぐ鎺濇晪闁挎繂顦介弫鍐煥閺囨浜剧紓浣插亾闁告劏鏂傛禍婊堟煛閸愩劍鎼愬ù婊冪秺閺屻劌鈽夊▎鎴犵厐闂佸疇顫夐崹鍧椼€佸▎鎾虫闁靛牆瀚潻鏃堟⒒娴ｅ憡鍟為柟绋款煼閹嫰顢涢悙鍙夋К闂侀€炲苯澧柕鍥у楠炴帡骞嬮鐔滐箓鎮楀▓鍨珮闁哥姵顨婇獮鍫ュΩ閿斿墽鐦堥梺鍛婂姀閺傚倹绂掗姀銈嗗€甸悷娆忓缁€鍐磼椤旇姤宕岄柣娑卞櫍楠炴鎷犻懠顒夊敽闁诲骸绠嶉崕鍗灻洪妶澶婂惞妞ゆ巻鍋撻柍瑙勫灴閹晠宕归锝嗙槑闂備胶顭堥鍡欑矙閹达富鏁嬮柨婵嗩槸闁卞洭鏌￠崶鈺佹瀻濞存粓浜跺娲传閸曨剙绐涢梺鍝ュУ閸旀洟鍩㈠鍫㈢杸婵炴垶鐟㈤幏缁樼箾鏉堝墽鍒伴柟璇х節楠炲棝宕奸妷锕€浠╁┑顔筋焽閸樠勭閹殿喒鍋撶憴鍕婵炲弶锚椤洩绠涘☉妯煎幐闂佸憡鍓崨顖涘枓闂傚倷娴囧畷鐢稿窗閹扮増鍋￠柕澹偓閸嬫挸顫濋悡搴㈢亾缂備緡鍠氱划顖炲Χ閿濆绀冮柍鍝勫暙瀵櫕绻濋悽闈涒枅婵炰匠鍏炬稑鈹戠€ｅ灚鏅涘┑掳鍊愰崑鎾淬亜椤撯€冲姷妞ぱ傜窔閺屾盯鎮╁畷鍥р拰闂佺硶鏅濋崑銈夌嵁鐎ｎ喗鏅濋柍褜鍓熼幃姗€骞庨懞銉у幈闂佸綊鍋婇崜娆戠棯瑜旈弻娑欑節鎼达紕浠╅梺?")
        else:
            parts.append("婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽弫鎰板川閸屾粌鏋庨柍璇查叄楠炲棜顦虫い鏂垮缁辨捇宕掑▎鎺戝帯婵犳鍠楅幐鎶藉箖濡警娼╅悹杞扮秿閿曞倹鐓曢柡鍥ュ妼閺嬨倝鏌ｉ妶鍌氫壕闂傚倷绀佸﹢閬嶅磻閹捐绠氶悘鐐跺▏濞戙垺鍊烽柣銏㈡暩閿涙繃绻涙潏鍓ф偧闁哄拋鍋婂畷濂割敂閸喓鍘辨繝鐢靛Т閸熸壆绮婚悙纰樺亾濞堝灝鏋涙い顓犲厴楠炲啴濮€閵堝棙鍎梺闈╁瘜閸橀箖宕㈤鐐粹拻濞达絿顭堥ˉ蹇涙煟閹惧磭澧︾€规洘濞婇、姘跺焵椤掆偓閻ｅ嘲鈹戦崶褏绐為梺褰掑亰閸樻悂骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囶亞鐣垫鐐诧躬瀹曟﹢顢旈崱娆欑床缂傚倸鍊烽悞锕傛晝椤愶附鍤€闁圭瀵掑▓浠嬫煟閹邦厼绲婚柡鍡樼懇閹藉爼寮介鐔哄幈濠电偞鍨靛畷顒€鈻嶅Ο璁崇箚妞ゆ劑鍨归弳娆撴煃鐟欏嫬鐏撮柟顔界懇瀵爼骞嬮悩杈敇闂傚倷娴囧畷鐢稿闯閿斿墽涓嶉柟鎯х－閺嗭箑霉閸忓吋缍戠紒鐘崇⊕閵囧嫰寮崹顔规寖闂佹寧绋掔换鍐崲濞戞瑦缍囬柛鎾楀惙鎴︽偡濠婂嫭绶查柛鐕佸灣缁顓兼径瀣偓閿嬨亜閹烘垵鈧鎯侀崼銉︹拺婵懓娲ら悘鍙夌箾娴ｅ啿鍟伴幗銉モ攽閻樺灚鏆╅柛瀣█椤㈡艾顭ㄩ崨顖欑瑝闂佽鍎崇壕顓㈠汲閿曞倹鐓欓柟娈垮枛椤ｅジ鏌涚€ｃ劌濮傞柡灞剧☉閳藉顫滈崼婵嗩潬闂備礁鎲￠悷銉ノ涘Δ鍛厴闁硅揪闄勯崑鎰磽娴ｈ偂鎴︽煥椤撶偐鏀介柍钘夋娴滄繄绱掔拠鑼ⅵ闁靛棔绶氶獮妯侯熆閸曨剚顥堢€规洏鍔戦、娆撳箚瑜嶇粻浼存⒒娴ｇ瓔鍤欓柛鎴犳櫕缁辩偤宕卞☉妯硷紱闂佺硶鍓濈粙鎴ｇ箽闂備礁婀遍崕銈咁潖閼姐倕顥氬┑鍌滎焾缁狙囨煕椤愶絿鈽夊┑鈥冲悑缁绘盯骞栭鐐寸彎闂佸搫鏈惄顖炲春閻愬搫绠氱憸灞剧珶閺囩偐鏀介柨娑樺娴滃ジ鏌涙繝鍐⒈闁轰緡鍣ｉ獮鎺楀棘閸濆嫪澹曞┑顔筋焽閸樠勬櫠閹绢喗鐓涢悘鐐电摂閸庢梻鈧娲栭悥濂搞€佸Δ浣瑰闁告繂瀚粭姘舵⒒閸屾瑧鍔嶉柟顔肩埣瀹曟繂顓奸崶鈺冪厯闂佸湱鍎ら崹鐔煎几瀹ュ鐓曟繛鎴濆船婵悂鏌ｉ悢鐓庝喊闁绘挶鍎甸弻娑樷槈閸楃偛绠虫繝銏ｎ潐濞叉牠鈥旈崘顔嘉ч柛鎰╁妼鎯熼梻浣侯焾濞寸兘寮繝姘卞祦闁告劑鍔夐弸搴ㄦ煙閻愵剚缍戞繛鍫涘€曢—鍐Χ閸℃浼囬梺绋挎唉椤曆団€栨繝鍥х濞达絽鍘滈幏缁樼箾鏉堝墽鍒伴柟璇х節瀹曨垶鎮欑€涙ê寮挎繝鐢靛Т閸婂湱鎷归敓鐘崇厱闁绘顕滃銉︺亜閹剧偨鍋㈢€规洖鐖兼俊鎼佸Ψ閵壯冩惛婵犵數濮烽弫鎼佸磻閻愬搫鍨傞柛鎾茬閺嬪牏鈧箍鍎卞ú鐘诲磻閹炬剚娼╂い鎾跺枔濞堛倝姊洪悷鏉跨骇闁烩剝娲滅划璇测槈濡攱顫嶅┑鐐叉缁诲骞冮敐澶嬧拻濞达絽婀卞﹢浠嬫煕閵娿儳绉烘鐐差樀閺佹捇鎮╅崘韫暗婵犵數鍋涘Λ娆撳礉閹寸偟顩叉繝濠傜墛閻撴盯鏌涢妷顔惧帥婵炲牊鏌ㄩ湁婵犲﹤鍟埛鏃傜磼鏉堛劍灏伴柟宄版嚇瀹曨偊宕熼幋顖滅М闁哄矉绲借灃闁告劑鍓遍姀掳浜滈柡鍥朵簽缁嬭崵绱掔紒妯肩畵妞ゎ偅绻堥、妤呭焵椤掑嫭鍤€闁割煈鍠掗弨浠嬪箳閹惰棄纾归柡鍥ュ灪閺呮繈鏌曢崼婵愭Ц缂佺姵鐗犻弻鐔告綇妤ｅ啯顎嶉梺鎶芥敱閸ㄥ湱妲愰幒妤婃晬婵炴垶鐟чˇ銉︾節閳封偓閸曨厼寮ㄩ梺鍝勭焿缂嶄線骞冮姀銈呯骇闁瑰瓨绻傝闂傚倷鑳剁划顖涚瑹濡ゅ懎绐楅柡宥庡弾閺佸洭鏌涜箛鏇炲付缂佸墎鍋ら幃妤呮晬閸楃偛顏╂い蹇曞劋缁绘繈鎮介棃娑楀摋闂佽妞挎禍鐐差嚗婵犲洤閿ゆ俊銈勭娴犻亶姊洪崫鍕殭闁绘妫濆畷銉ㄣ亹閹烘挾鍘遍梺閫涘嵆濞佳囧几閻斿吋鐓熼柟鎯х摠缁€鍐ㄇ庨崶褝韬い銏＄☉椤繈顢楁担绯曞亾椤栨埃鏀介柣鎰级閸ｇ儤绻涢懠顒€鏋涚€殿喖顭烽崺鍕礃椤忓棙鍤岄梻浣规偠閸庢粓宕熼鐐电У婵犲痉鏉库偓妤佹叏閻戣棄纾婚柣鎰仛閺嗘粓鏌ㄩ悢鍝勑ョ€规挷鐒﹂幈銊ヮ渻鐠囪弓澹曢柣搴㈩問閸犳牠鎮ユ總鍝ュ祦閻庯綆浜栭弨浠嬫煕濞戝崬鐏ｆい锔垮嵆濮婂宕掑顑藉亾閹间礁纾瑰瀣椤愯姤鎱ㄥΟ鎸庣【闁绘帒鐏氶妵鍕箳閹存績鍋撻崨濠勵浄婵犲﹤鐗婇悡鐘崇箾閼奸鍤欓柣蹇ョ節閺岋繝宕ㄩ鐘茬厽濡ょ姷鍋涚粔褰掋€佸▎鎾崇鐟滄繄妲愰弻銉︹拺闁告繂瀚峰Σ鎼佹煟濡も偓鐎氭澘鐣峰┑鍡╁悑闁搞儻濡囬崜銊︾箾鐎电甯堕柣掳鍔戦幃鈥斥枎閹存柨浜鹃柣鐔告緲椤忣偄顭胯椤ㄥ﹤鐣烽悽绋跨倞妞ゆ帊鑳堕崢鐢告⒑缂佹ɑ灏繛鎾棑缁柨煤椤忓懐鍘靛銈嗘⒐閸庢娊宕㈢€涙﹩娈介柣鎰皺鏁堝銈冨灪瀹€绋跨暦閵娾晩鏁囨繝闈涳功缁犵兘姊婚崒姘偓鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌ｉ幋锝呅撻柛濠傛健閺屻劑寮崼鐔告闂佺顑嗛幐鍓у垝椤撶偐妲堟俊顖氭惈缁犵粯淇婇妶蹇曠暢婵炲娲熼幃鍧楀焵椤掆偓閳规垿鎮欓弶鎴犱桓闂佹寧宀搁弻锝嗘償椤旂厧绠虹紓浣虹帛缁嬫捇鍩€椤掑倹鏆╂い顓炵墕閻☆厽淇婇悙顏勨偓鏍垂闂堟耽娲Χ婢跺浠奸梺鍓茬厛閸嬪懏鍒婄€靛摜纾兼い鏍ㄧ⊕缁€鍐煛閸屾浜鹃梻鍌氬€烽懗鍓佸垝椤栫偞鏅柣搴㈩問閸犳盯宕洪弽褜鍤楅柛鏇ㄥ灠缁€瀣亜閺嶃劎銆掗柛妯块哺缁绘繈鎮介棃娴躲垽鎮楀鐓庡⒋鐎规洏鍨介獮姗€顢欓悾灞藉箰闂佽绻掗崑娑欐櫠娴犲鐓″鑸靛姈閻撳啴鎮峰▎蹇擃仼闁诲繐顕埀顒冾潐濞叉牕鐣烽鍐簷濠电姷鏁告慨鎶芥嚄閸撲礁顥氬┑鐘崇閳锋帡鏌涚仦鍓ф噮闁告柨绉归幃妤冪箔濞戞ɑ鍣介柣顓熺懇閺岀喖鎮滃Ο鑽ゅ弳闂佹悶鍔嶇换鍕焵椤掆偓閸樻粓宕戦幘缁樼厱闁哄洢鍔屾禍鐐烘煕濡粯灏︽慨濠呮濞戠敻宕ㄩ鍏奸敪闂佽閰ｅ褔鎯岄崒姘煎殨妞ゆ劧绲跨弧鈧梺鎼炲劘閸斿酣宕㈤挊澶樻富闁靛牆妫欑€垫瑩鏌涢幇灞芥閻掔粯绻濋悽闈涗粶闁宦板妿閸掓帡鎮╁畷鍥舵锤濠电姴锕ら悧濠囧磻閳哄懏鐓熼柟杈剧稻椤ュ宕鐐村仭婵犲﹤鍠氬Ο鈧悗瑙勬礃閸ㄥ潡鐛Ο鑲╃＜婵☆垳绮悵鎶芥⒑绾懎浜归悶娑栧劦瀹曟粌鈹戠€ｎ偄浠у銈嗘磵閸嬫挻鎱ㄦ繝鍕妺婵炵⒈浜獮宥夘敋閸涱啩婊勭節閻㈤潧浠滈柣顏冨嵆瀹曟劕鈽夐姀鈥斥偓鍫曟煕閹伴潧鏋熼柍閿嬪灴閺岀喓绮欓幐搴㈠闯缂備胶濮甸幑鍥蓟閻旂厧绀冮柡灞诲劚瀵即鎮楀▓鍨灍濠电偛锕獮鍐ㄢ枎閹炬潙鈧粯淇婇婊冨付閻㈩垱顨婂濠氬磼濞嗘埈妲梺璇茬箲缁诲牓銆侀弽顓炲窛閻庢稒锚閳ь剙鐖奸弻鐔虹磼閵忕姵鐏嶉梺缁樻尰閻╊垶骞冨鈧幃娆撳箵閹哄棙瀵栭梻浣哥枃濡嫰藝閻㈢钃熺€广儱娲﹂崰鍡涙煕閺囥劌浜炲ù鐓庣焸閹鎲撮崟顒傤槬閻庤娲﹂崜婵嬫倶閸愨晝绡€闁汇垽娼у皬闂佺粯甯粻鎾崇暦閹达箑宸濇い鎾寸⊕閺傗偓闂備焦瀵х粙鎴犫偓姘煎墯缁傚秵绺介崨濠勫幈婵犵數濮撮崯顖滅矆閸儲鐓欐鐐茬仢閻忓弶顨ラ悙宸剶闁轰礁鍟撮崺鈧い鎺戝€绘稉宥吤归悡搴ｆ憼闁绘挻鐟╅弻鐔碱敍濠婂喚鏆銈冨劚椤︾敻寮婚敃鍌氱妞ゅ繐瀚悗鍓х磽娴ｈ櫣甯涢柣鈺婂灦閻涱喚鈧綆浜栭弸搴ㄧ叓閸ャ劍纾婚柟顕嗙秮濮婅櫣鎷犻垾宕囦化闂佸摜濮甸悧鏇綖韫囨拋娲敂閸滀焦顥堟繝鐢靛仦閸ㄧ數澹曢鐘冲厹闁逞屽墴濮婄粯鎷呴崨濠傛殘濠电偠顕滅粻鎾崇暦閵忋倕绠瑰ù锝呮憸閿涙盯姊洪崷顓炰壕婵＄偛娼″顐も偓锝庡枟閻撳啰鎲稿鍫濈闁绘棁鍋愬畵渚€鏌涢幇鈺佸闁哄棗顑夊娲敇閵娿儺娲梺鍛婄懃濡繂顫忓ú顏勫窛濠电姴鍟ˇ鈺呮⒑閸涘﹥灏伴柣鈺婂灠閻ｅ嘲鈻庨幘瀛樻闂佺粯蓱閺嬪ジ骞忓ú顏呪拺闁革富鍙庨悞楣冩倵濞戞帗娅嗙€垫澘瀚板畷鐔碱敃閳ь剟鎮烽柇锔惧弳闂佸憡娲﹂崢楣冩偂婢舵劖鈷戦柟绋挎捣缁犳﹢鏌涚€ｎ剙啸缂侇喛顕ч埥澶娢熼柨瀣垫綌婵犵妲呴崹鏉匡耿闁秵鍊峰┑鐘叉处閳锋帒霉閿濆懏鍟為柛鐔哄仦缁绘盯宕ｆ径娑溾偓璺ㄢ偓瑙勬礈閺佸銆侀弮鍫濋唶婵犻潧鐗嗛埀顒傚仱閹嘲顭ㄩ崘顏嗩啋閻庤娲橀崝娆撳箖濞嗘挻鍊绘俊顖濇〃閻㈢粯绻濋悽闈浶㈤柨鏇樺€濆畷顖炴偋閸喐鐝￠梻鍌氬€烽懗鍫曞磻閵娾晛纾块柡灞诲劜閸嬪鏌ｅΟ鍨毢闁哄棴绠戦埞鎴﹀磼濠婂海鍔搁柛鐑嗗灦濮婃椽骞愭惔鈶╂嫻闂佺瀛╂繛濠囨偘椤斿槈鏃堝川椤旇瀚奸梻浣藉吹閸犳劕顭垮鈧獮鍐箣閿旂晫鍘介梺鎸庣箓缁ㄥジ鏌囬婧惧亾鐟欏嫭绀€缂傚秴锕ら悾宄拔旈崨顔兼異闂佸啿鎼崯顐ｎ殽閸曨剛绡€婵炲牆鐏濋弸鐔兼煏閸ャ劎娲寸€规洘鍨块獮妯肩磼濡厧骞愰柣搴″帨閸嬫捇鏌嶈閸撶喎鐣锋导鏉戝唨妞ゆ挾鍋熼悿鍥⒑缂佹ê濮囬柟纰卞亜閺侇噣鏌ｉ悢鍝ョ煀缂佺粯锕㈤獮鍐晸閻樿尙鍔﹀銈嗗笒鐎氼參鍩涢幋锔界厱婵炴垶锕╅悡顒佺箾閸喓鐭婇棁澶嬬節婵犲倸鏆熼柛鈺嬬悼閳ь剚顔栭崰鏍€﹂悜钘夌畺闁靛繈鍊曠粈鍌炴煠濞村娅呭┑顔芥そ濮婄粯鎷呴悷閭﹀殝濠电偞褰冪粔鐟扮暦閹达箑绠荤紓浣诡焽閸樺崬鈹戦埥鍡楃仯缂侇噮鍨虫禍鎼佹晝閸屾稓鍘搁悗鍏夊亾閻庯綆鍓涢惁鍫ユ⒑缁洘鏉归柛瀣尭椤啴濡堕崱妤冪憪闂佺厧鍟块悥濂稿Υ閸涘瓨鍊婚柤鎭掑劚閳ь剛鏁婚弻銊モ攽閸℃侗鈧霉濠婂嫮鐭掗柡灞界Х椤т線鏌涢幘瀵告创鐎殿噮鍋呯换婵嗩潩椤掑啯鎲伴梻渚€娼ч…鍫ュ磿椤曗偓瀵劍绂掔€ｎ偆鍘遍梺鏂ユ櫅閸熶即骞婇崘顔界厱闁靛牆楠告晶鎵磼鏉堛劍灏伴柟宄版嚇濡啫鈽夊鍡欌偓杈╃磽閸屾瑧璐伴柛鐘愁殜閹兘鍩℃笟鍥ф婵犵數濮电喊宥夊疾閹绘帩鐔嗛悹铏瑰皑閸旂喐銇勯弮鈧敮鈥愁潖濞差亜浼犻柛鏇炵仛鏁堥梻浣规偠閸斿繘锝炴径宀€鐭夐柟鐑橆殔缁狙囨煙閹碱厼骞楅悗闈涚焸濮婃椽妫冨☉姘暫缂備降鍔忛崑鎰版嚍鏉堛劎绡€婵﹩鍘鹃崢閬嶆⒑缂佹ɑ顥堟い銉︽崌楠炴鎮╅惈顒€閰ｅ畷鎯邦檪闂婎剦鍓涢埀顒冾潐濞叉牠濡剁粙娆惧殨闁圭虎鍠楅崐鐑芥煠閻撳海浜柛瀣崌瀹曞綊顢欑憴鍕澑闂備胶绮崝鏇烆嚕閸泙澶婎煥閸曨厾顔曢柣搴㈢⊕椤牊绔熷Ο姹囦簻妞ゆ挾鍋為崰姗€鏌熼鐣岀煉闁瑰磭鍋ゆ俊鐑藉閳ユ剚浼滃┑鐘垫暩閸嬬娀骞撻鍡欑闁逞屽墯娣囧﹪顢曢姀鐙€浼冮悗瑙勬磸閸庢挳濡甸幇鏉跨闁规崘娉涢獮鍫ユ⒒娴ｈ櫣甯涢柨姘扁偓娈垮枛閻栬壈妫㈤梺闈涚箚閹冲洭宕戦幘鑸靛枂闁告洦鍓涢ˇ銊╂⒑閸涘﹥鈷愭繛鍙夌箞閹﹢宕橀瑙ｆ嫼闂佸憡绋戦敃锝囨闁秵鐓曢柣妯虹－婢ь亪鏌嶇紒妯诲磳闁诡喓鍨藉畷妤冧焊閺嶃劌顏烘繝鐢靛仦閹稿鎳濋幆顬℃椽濡堕崱妯荤彿濡炪倖鏌ㄦ晶鐣屽閻撳寒鐔嗛悹杞拌閻擃剟鏌涢妶鍥ф灁缂佽鲸甯￠、娆戝枈鏉堚晛鎮戝┑鐘殿暜缁辨洟宕楀鈧顐﹀磼濞戞瑥顫￠梺瑙勵問閸犳艾鈻旈崸妤佲拻闁稿本鐟чˇ锕傛煙绾板崬浜扮€规洘鍔欓獮鏍ㄦ媴閻熸壋鍋撻懜鐢电瘈闂傚牊渚楅崕蹇涙煟閹惧瓨绀嬮柡宀嬬節瀹曟﹢濡歌椤も偓闂備胶绮幐鍫曞磿閼碱剚宕叉繛鎴欏灩缁狅綁鏌ｉ幇顒備粵闁革綆鍠氱槐鎾存媴閸濆嫅锝夋煟濡や胶鐭屾俊鍙夊姍楠炴帡寮崒婊愮床婵犵妲呴崹浼存儍闁垮鍙忛柛銉戔偓閺€浠嬫煟閹扮増娑ч悽顖氬缁辨帞绱掑Ο蹇ｄ邯閹儳鐣￠柇锔惧弳闂佺硶妾ч弲婊€绨洪梻鍌氬€烽懗鍓佹兜閸洖鐤炬繛鎴欏灪閸庢鏌涚仦鎯у毈婵炲吋鐗犻弻褑绠涢幘纾嬬缂佺偓鍎抽崥瀣箞閵娿儙鏃堝焵椤掆偓铻炴繛鍡樻尰閸嬧晠鎮规ウ瑁も偓鈧柡鈧禒瀣厓闁芥ê顦伴ˉ婊兠瑰鍕畼缂佽鲸甯為幏鐘绘嚑椤掆偓閳敻姊虹拠鈥虫灆闁告濞婇妴浣糕枎閹炬潙浠奸悗鍏夊亾闁逞屽墴閹線宕奸妷锔规嫼闂佺鍋愰崑娑㈠礉閳ь剟姊洪崨濠佺繁闁搞劌宕…鍧楀箣閿旇В鎷婚梺绋挎湰閻熝囁囬敃鍌涚厵缁炬澘宕禍浼存寠濠靛鐓欐繛鍫濈仢閺嬫捇鏌涚€ｎ偅灏电紒顕呭幖閳藉螣鐠囧樊妲遍梻浣侯焾閿曘倝鎮樺璺何﹂柛鏇ㄥ灠缁犲磭鈧箍鍎卞Λ顓炍熼崒婊呯＝濞达絿鐡旈崵娆愪繆椤愶絿绠炵€殿喖顭峰鎾閻樿鏁规繝鐢靛█濞佳囨偋韫囨侗鏁婂┑鐘叉处閳锋垿鏌涘☉姗堝伐缂佹鍊块弻娑樜旀担绯曟灆閻庢鍠涢褔鍩ユ径鎰潊闁炽儱鍘栫花钘夆攽閻愯埖褰х紒韫矙楠炴顭ㄩ崟顓ф祫闂佸綊妫块悞锕傚煕閹达附鍋ｉ柛銉岛閸嬫捇鎼归銈呰缂傚倸鍊烽懗鍓佸垝椤栨粍宕查柛宀€鍎愰弫瀣煥濠靛棭妲哥紒鐘电帛閵囧嫰寮崶顭戞婵炲瓨绮嶇划鎾愁潖濞差亜宸濆┑鐘插暙閻噣姊洪悡搴℃毐闁绘牕銈搁獮鍐┿偅閸愨晛鈧攱銇勯幋锝嗙《缂佺姵宀稿铏圭磼濡搫袝婵炲瓨绮嶇划鎾诲春閳ь剚銇勯幒宥堝厡濠⒀呮暬閺岀喖顢欓妸銉ユ偐闁哄啫鐗嗗婵囥亜閺冨牊锛熼柣銏狀煼濮婄粯绗熼埀顒€顭囪婢ф繈姊洪崫鍕櫝闁哄懐濮撮锝夘敃閿曗偓楠炪垺绻涢幋鐐垫噮闁告ü绮欏娲传閸曨偀鍋撻幖浣瑰€舵繝闈涱儏缁犳牠鏌熸潏楣冩闁绘挾鍠栭弻鐔煎箚瑜忛幗鐘电磼閳ь剛鈧綆鍋掑▓浠嬫煟閹邦剦鍤熷褜浜幊锝夊箛椤撴粈绨婚梺鐟版惈濡绂嶆ィ鍐┾拺閻犲洩灏欑粻姘舵煛閸涱垰鈻堢€殿喖顭烽弫鎰板醇閵忋垺婢戝┑鐘垫暩婵挳宕鐐村仧闁哄稁鍋嗙壕钘壝归敐鍕煓闁告繃妞介幃浠嬵敍濞戣鲸鐣跺銈庡幖濞测晝绮诲☉妯锋婵☆垱澹曢弲鐘诲蓟閵娾晛鍗虫俊銈傚亾濞存粌澧界槐鎺楀礈瑜嶆禍鎯р攽閻愯韬鐐插暙铻栭柛鎰ㄦ櫅閺嬪倿姊洪崨濠冨闁告挻鐩棟闁靛ň鏅滈悡鐔兼煏韫囧﹥娅呴柣蹇ョ節閹粙顢涢妶鍥╃槇闂佽桨鐒﹂崝娆撳箖濞嗗緷鍦偓锝庡亝閺夋悂姊虹拠鎻掑毐缂傚秴妫欑粋宥夋倷閺嶇娲╅ˇ褰掓煛瀹€瀣К缂佺姵鐩獮姗€宕滄笟鍥ф暭闂傚倷鑳剁划顖炪€冮崱娑栤偓鍐╃節閸パ呯暫濠德板€曢幊搴ｇ棯瑜旈獮鏍偓娑櫳戠亸浼存煛閸屾浜鹃梻鍌氬€烽懗鍓佸垝椤栨繃鎳岄梻浣告啞閹歌鐣濈粙璺ㄦ殾妞ゆ牗绻勯悿鈧┑鐐村灦閻熝囧储闁秵鈷戠紓浣光棨椤忓棗顥氭い鎾跺枑濞呯娀鏌ｉ姀鐘冲暈闁绘挻绋戦湁闁挎繂娴傞悞楣冩煛閸☆厾鍒伴柍瑙勫灴濡鹃亶鏌涢埡鍌滃ⅹ妞ゆ洏鍎靛畷鐔碱敍濮橆剝鈧潡妫呴銏″闁规悂鏀辩粩鐔煎即閵忊檧鎷洪梺鍦焾鐎涒晝绮堥埀顒勬⒑缁嬪尅宸ョ紓宥咃工閻ｇ兘骞囬钘夌彴濠电偞娼欓鍡涘棘閳ь剚淇婇悙顏勨偓鏍涙担鑲濇盯宕熼浣稿伎闂侀€炲苯澧存慨濠呮缁瑥鈻庨幆褍澹夐梻浣告贡椤牓鈥﹂悜鐣屽祦闊洦绋戝婵嬫煛婢跺鐏╂い锔诲弮濮婃椽宕ㄦ繝鍕櫑濡炪倧瀵岄崹璺虹暦濡や胶绡€闁搞儯鍔夐幏娲⒑閻撳寒娼熼柛濠冩礋閸┿垽宕奸姀銏紳闂佺鏈粙鏍ㄧ珶濮椻偓閺屽秶鎷犻懠顑囨煛娴ｇ懓濮堢€垫澘瀚换婵嬪礋閸倣銉╂⒒閸屾瑧鍔嶉悗绗涘厾鍝勵吋婢跺﹦锛涢梺鍦亾閻ｎ亝绂嶅鍕╀簻闊洦鎸搁鈺呮煛閸☆厾鍒伴柍瑙勫灴閸ㄦ儳鐣烽崶褏鍘介柣搴ゎ潐濞叉牕鐣烽鍐簷闂備礁鎲￠崝锔界濠靛闂い鏍仦閳锋帒霉閿濆洨鎽傞柛銈嗙懇閹鈽夐幒鎾寸彋閻庤娲﹂崑鍛村箚閺冨牆惟闁靛／灞拘ラ梻鍌欒兌椤㈠﹪骞撻鍡欎笉闁硅揪绠戦崣濠囨煏婢跺棙娅嗛柣鎾冲暟閹茬顭ㄩ崼婵堫槶濠殿喗顭堝▔娑欘攰闂備礁鎲″ú锕傚垂閹殿喚涓嶉柟鎯板Г閻撴洟鏌嶉埡浣告殧濞寸媴绠戦…璺ㄦ喆閸曨剛顦板┑顔硷功缁垶骞忛崨顔剧懝妞ゆ牗绮屾慨濂告⒒娴ｇ懓顕滄繛鎻掔箻瀹曟劙寮撮埗鈹惧亾閿曞倸鐐婃い鎺嶇劍濞呫垽姊虹紒姗堣€挎繛浣冲懐鐭堥柨鏃傛櫕缁♀偓闂佹眹鍨藉褍鐡繝鐢靛仩椤曟粎绮婚幘宕囨殾闁规壆澧楅崐濠氭煠閹帒鍔ら柛妯哄船閳规垿鎮╃紒妯婚敪濠碘槅鍋呴〃濠囧箖閻㈢鍋撻敐搴℃灍闁绘挸绻愰埞鎴︽倷闂堟稐澹曞┑鐐叉噹濡繈寮婚敐澶婄闁告鍋涙慨锕傛⒑閸濆嫮鐒跨紒缁樼箓閻ｇ兘骞掗幋顓熷兊闂佸憡鐟﹂…鍫濐瀶閹间焦鈷掑ù锝囨嚀閳绘洟鏌￠埀顒勫础閻愬秵鐩畷姗€顢欓懖鈺冩瀮闂備礁鎼粙渚€宕㈡總绋跨闁逞屽墮椤啴濡堕崱妯烘殫闂佸摜鍠庡锟犵嵁韫囨梻绡€婵﹩鍘搁幏铏圭磽娴ｅ壊鍎愰悗绗涘喛鑰垮ù鐓庣摠閻撶喖鏌ｉ弮鈧换鍌炲箠閹扮増鍋濆┑鐘崇閻撴盯鏌涢幇鍓佸埌濞存粌澧界槐鎾存媴閾忕懓绗￠梺鐑╂櫓閸ㄥ爼鐛繝鍌楁斀閻庯綆浜炴鍥⒑閸撹尙鍘涢柛鐘愁殜瀹曟洟顢旈崼鐔叉嫽婵炴挻鍩冮崑鎾绘煃瑜滈崜娑㈠磻濞戙垺鍤愭い鏍ㄧ⊕濞呯娀鎮楀☉娆樼劷缂佺姵鍎抽湁闁挎繂鎳庨弳杈ㄧ箾鐠囇呯暤鐎规洘娲栬灃闁告侗鍠氶崢閬嶆煟韫囨洖浠ч柛瀣崌閹啴骞嬮敂鐣屽幐闂佺硶妲呴崢楣冩偩閻㈠憡鐓涢悘鐐靛亾缁€澶岀磼閻樺磭銆掗柍褜鍓ㄧ紞鍡樼閺嶎厼纾婚柟鎹愵嚙閸愨偓濡炪倖鍔楅崰搴㈢妤ｅ啯鐓熼柕蹇嬪€栧☉褏鈧稒绻傞—鍐Χ鎼粹€崇哗濠电偛顦板ú鐔肩嵁閹达箑绀嬫い鏍ㄧ☉閳ь剛绮幈銊ノ旈埀顒€螞濞嗘挻鏅〒姘ｅ亾婵﹦绮幏鍛驳鐎ｎ亝顔勯梺璇插缁嬪牓寮插☉鈶┾偓鏃堝礃椤旇棄鐧勬繝銏ｅ煐钃辩紓宥呴閳规垿鎮欓崣澶嗘灆婵炲瓨绮嶇划宥団偓闈涖偢閹晝绱掑Ο鐓庡箞闂備礁鎼ú銏ゅ礉鐏炵偓娅犳い鏇楀亾闁哄本绋撻埀顒婄秵娴滅偞鏅ユ繝娈垮枛閿曘儱顪冩禒瀣祦闁哄稁鍘介崐鐑芥煙缂佹ê淇柣搴＄摠缁绘繄鍠婃径宀€锛熼梺绋款儐椤洭宕氶幒鎴旀瀻闁规崘娉涚粊?")
        if diagnostics_count:
            parts.append(f"闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳婀遍埀顒傛嚀鐎氼參宕崇壕瀣ㄤ汗闁圭儤鍨归崐鐐烘偡濠婂啰绠荤€殿喗濞婇弫鍐磼濞戞艾骞楅梻渚€娼х换鍫ュ春閸曨垱鍊块柛鎾楀懐锛滈梺褰掑亰閸欏骸鈻撳鍫熺厸鐎光偓閳ь剟宕伴弽顓炶摕闁搞儺鍓氶弲婵嬫煃瑜滈崜鐔奉嚕缁嬪簱妲堥柕蹇ョ磿閸橀亶姊洪棃娑辩叚濠碘€虫川缁鎮欓幖顓燁啍闂佺粯鍔曢顓熸櫠椤忓牊鍤曢柟閭﹀幑娴滄粓鏌熼崫鍕棞濞存粓绠栧铏规嫚閸欏顩版繛瀛樼矋缁诲嫰骞戦姀鐘闁靛繒濮寸粣娑橆渻閵堝棛澧い鏇熸尦閺佹劙宕ラ崘鏌ュ弰鐎规洘鍎奸¨鍌炴椤掑澧柍瑙勫灴閸ㄦ儳鐣烽崶褏鍘介柣搴ゎ潐濞插繘宕濋幋锔衡偓浣糕枎閹惧磭顦х紒鐐緲瑜板宕Δ鍐＝闁稿本鑹鹃埀顒佹倐瀹曟劙鎮滈懞銉ユ畱闂佽偐顭堥悘姘跺矗韫囨稒鐓欓柟顖滃椤ュ鐥娑樹壕闂傚倷娴囬～澶愬磿閻撳宫娑㈠礋椤栨稑鐝旈梺缁樻煥閹芥粎绮绘ィ鍐╃厵閻庣數顭堥埀顒佸灥椤繈顢栭埡瀣М鐎规洖銈搁幃銏㈢矙閸喕绱熷┑鐘茬棄閺夊簱鍋撻幇鏉跨；闁瑰墽绮悡鐔镐繆閵堝倸浜鹃梺鎸庢处娴滄粓顢氶敐澶樻晝闁挎洍鍋撶紒鐘虫皑閹插憡寰勯幇顒傚摋婵炲濮撮鍡涙偂閻斿吋鐓欓梺顓ㄧ畱婢ь喚绱掗悪娆忔处閻撴洟鏌ㄥ┑鍡欏妞ゃ儱顦甸弻宥囨喆閸曨偆浼岄梺璇″枟閻熲晠宕洪埄鍐╁鐎瑰嫰鍋婂Λ婊堟⒒閸屾艾鈧悂宕愭搴ｇ焼濞撴埃鍋撴鐐寸墵椤㈡洟鏁傞挊澶婂濠电姰鍨煎▔娑㈡嚐椤栨粍顐介柕鍫濐槹閻撴洖鈹戦悩鎻掝仼闁哄鏌ㄩ湁婵犲ň鍋撶紒顔界懃椤繒绱掑Ο璇差€撻梺鍛婄☉閿曘劎娑甸埀顒佷繆閻愵亜鈧倝宕㈡總鍛婂亱闁糕剝绋掔粻鎺楁⒒娴ｅ湱婀介柛濞垮€濆畷褰掝敆娴ｄ警娲搁梺闈╁瘜閸樹粙宕伴幇鏉跨閺夊牆澧界粙鑽も偓瑙勬礀瀵墎鎹㈠☉銏犵闁绘劘灏欓崝浼存⒑缁嬫鍎愰柟鍛婃倐閸┿儲寰勬繛鐐€哄銈嗘寙閸屾粎娉块梻浣哥－缁垶骞戦崶顒€绠栭柍鍝勫暟绾惧吋淇婇婊冨付妤犵偛鐗嗛埞鎴︽偐閸偅姣勬繝娈垮枟閹稿啿鐣烽鐐村亱闁割偆鍠愰悵宄邦渻閵堝棗绗掗柛濠呭吹婢规洟鎳栭埞鎯т壕闁稿繐顦禍楣冩⒑閸涘﹤濮﹂柛鐘崇墵楠炴鎮介悽鐢碉紳婵炶揪缍€濞咃絿鏁☉姘辩＜閻犲洩灏欐晶鏇㈡煟閿濆洤鍘寸€规洖銈稿鎾偄闁垮鏉洪梻鍌欑婢瑰﹪鎮￠崼銉ョ；闁告稑鐡ㄩ崑鐔搞亜閹般劍鍣伴柡鈧禒瀣厽婵☆垵娅ｆ禒娑㈡煛閸″繑娅呴柍瑙勫灴閹瑩鍩℃担宄邦棜婵犵數濮烽弫鎼佸磻濮椻偓瀹曠娀鎮╃拠鑼槯闂佺粯顭堢亸娆戠矓閾忓厜鍋撶憴鍕閻㈩垱甯￠崺銉﹀緞婵犲孩鍍甸梺绋跨箺閸嬫劙濡堕锔解拻闁稿本鐟чˇ锕傛煕閻旈攱鍋ユ鐐寸墵椤㈡洟鏁冮埀顒傜不閻樿崵鍙撻柛銉ｅ妿閳藉鏌ｉ幘瀛樼闁哄瞼鍠愬蹇涘礈瑜忛弳鐘电磽娴ｅ搫鐝￠柛銉ｅ妿閸樹粙姊鸿ぐ鎺戜喊闁告鏅▎銏ゆ嚑椤戣棄浜鹃悷娆忓鐏忣厽淇婇锝囨噭缂佸矁椴哥换婵嬪炊瑜忛ˇ顓㈡偡濠婂啰效鐎规洏鍨介獮姗€顢欓悾灞藉箰闂佽绻掗崑娑欐櫠閽樺铏光偓鐢电《閸嬫挸鈻撻崹顔界彯闂侀潻缍囩紞浣哥暦濞差亜鐒垫い鎺嶉檷娴滄粓鏌熼悜妯虹仴妞ゅ繆鏅犻弻娑㈠Ω閵夈儮鍋撻崸妤€钃熸繛鎴旀噰閳ь剨绠撻獮瀣攽閸モ晛钂嬮梻鍌欑劍閹爼宕愰弽顬℃椽寮介鐐靛幋闂佺鎻梽鍕磻閹邦喒鍋撶憴鍕婵炴潙鍊垮鎶芥晸閻樻枼鎷洪梺鍛婄箓鐎氼參宕抽搹瑙勫枑闁哄鐏濋弳锝夋煃閵夘垳鐣电€规洜顭堣灃濞达絽鎲￠悿鍌炴⒒娴ｈ銇熼柛鎿勯檮缁傚秴鈹戠€ｎ亜鐎梺鍓茬厛閸ｎ噣宕甸弴銏＄厵缂備焦锚閸у﹪鏌￠埀顒佺鐎ｎ偄鈧敻鏌ㄥ┑鍡涱€楀ù婊勫姍閺岀喖鎮块娑变哗缂備浇椴搁幑鍥х暦閹烘垟鏋庨柟瀛樼箓椤姊洪挊澶婃殺濡炲瓨鎮傛俊鐢稿礋椤栨銊╂煏婢舵稑鐦滄俊顐磿缁辨挻鎷呴搹鐟扮闂佺儵鏅╅崹鍫曟偘椤斿槈鐔煎礂閻撳海褰撮梻浣规灱閺呮盯宕幍顔剧煋濡炲娴风壕?{diagnostics_count} 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃闁硅櫕鎹囬垾鏃堝礃椤忎礁浜鹃柨婵嗙凹缁ㄥジ鏌熼惂鍝ョМ闁哄矉缍侀、姗€鎮欓幖顓燁棧闂備線娼уΛ娆戞暜閹烘缍栨繝闈涱儐閺呮煡鏌涘☉鍗炲妞ゃ儲鑹鹃埞鎴炲箠闁稿﹥顨嗛幈銊╂倻閽樺锛涢梺缁樺姉閸庛倝宕戠€ｎ喗鐓熸俊顖濆吹濠€浠嬫煃瑜滈崗娑氭濮橆剦鍤曢柡澶嬪焾濞尖晠寮堕崼姘殨闁靛繒濮弨浠嬫煟濮楀棗鏋涢柣蹇涗憾閺屾盯鍩￠崒婊冣拰閻庤娲樼换鍫濐嚕娴犲鏁囬柣鎰仛閻擄綁姊绘担鍝ョШ婵☆偄娼￠幃鐐烘晝閸屾稑浜楅梺缁樻閺呰尙鎹㈤崱妯镐簻闁哄秲鍔庨。鏌ユ煙椤栨氨澧涘ǎ鍥э躬椤㈡洟鏁愭惔锝呭Ш闂備胶鎳撳鍫曞箖閸屾凹鍤曟い鏇楀亾鐎规洜鍘ч埞鎴炵節閸愨晛鏆繝鐢靛Х閺佹悂宕戦悙鍝勫瀭妞ゆ牜鍋涢崹鍌炴煟閻斿搫顣奸柡鍡樼矊閳规垿鏁嶉崟顐℃澀闂佺锕ラ悧鏇綖韫囨哎浜归柟鐑樺灩閿涚喖鎮楃憴鍕婵炶绠撳鍐差煥閸喓鍘繝銏ｆ硾閻楀棝宕濆Δ鍛厸闁逞屽墯缁傛帞鈧綆鍋嗛崢浠嬫⒑瑜版帒浜伴柛锝庡櫍瀵娊顢涢悙瀵稿幍闂佸憡鍨崐妤冨姬閳ь剟姊洪崫鍕拱缂佸鎹囬崺鈧い鎺戯功缁夐潧霉濠婂啫妲绘い鏂跨箻婵＄兘鏁傛潪鎵泿婵＄偑鍊栭崝鎴﹀垂閼姐倗涓嶇€规洖娲ㄧ壕濂稿级閸稑濡肩紒妤佸浮閹藉爼鏁愭径瀣化闂佹悶鍎滈崟銊︾亞闂備線鈧偛鑻晶顖炴煙閻熺増鎼愭い顐㈢箰鐓ゆい蹇撳缁愭稒绻濋悽闈浶㈤悗姘€鍏撅綁宕奸妷锔规嫼闂佸湱顭堢€涒晝澹曢幖浣圭厱閹兼番鍔嶅☉褔鏌ｉ敐鍥у幋鐎殿喗鎸虫慨鈧柣妯活問閸熷绱撻崒姘偓鐑芥倿閿曚礁缍旈梻浣告贡閺屽鈻嶉敐鍥潟闁规儳鐡ㄦ刊鎾煕閹炬潙绲婚柛鎾冲船椤啴濡堕崱妤冧桓闂佽崵鍟块弲娑㈡偩閻戣棄鍗抽柨娑樺閺夋悂姊洪崫鍕偓鍛婃櫠閻ｅ瞼涓嶆慨姗嗗墻濞撳鏌曢崼婵囶棞濠殿啫鍛＜闁艰壈鍩栫涵鍓佺磼椤旂⒈鐓兼鐐搭焽缁辨帒螣閻撳骸绠洪梻鍌欑劍鐎笛呮崲閸屾娲Χ婢跺﹤鍋嶉梺鍝勵槹閸ㄧ喖寮ㄩ懞銉ｄ簻闁哄啫鍊归崵鈧繛瀛樼矒缁犳牕顫忕紒妯肩懝闁逞屽墮椤洩顦归柟顔ㄥ洤骞㈡俊鐐灪缁嬫垼鐏冮梺鍛婁緱閸橀箖宕濋敃鈧—鍐Χ閸℃鐟ㄩ梺绋匡龚瀹曠敻寮灏栨婵☆垱鎸搁柊锝呯暦閹偊妾梻濠庡墻閸撴岸濡甸崟顖氼潊闁挎稑瀚уΣ鍫濐渻閵堝骸浜濈紒璇插暙椤洩绠涘☉妯溾晝鎲告惔顭戞晛闁搞儺鍓氶埛鎺楁煕鐏炲墽鎳勭紒浣峰嵆閺屾洟宕辫箛鎾插闂傚倷鑳堕…鍫ヮ敄閸℃稑绠查柛銉墮閽冪喓鎲搁幋鐘典笉婵炴垯鍨洪弲鏌ユ煕濞戝崬澧伴柡浣圭墱缁辨捇宕掑▎鎺濆敼濠碉紕瀚忛崶褏锛涢梺鐟板⒔缁垶鍩涢幒鎳ㄥ綊鏁愰崨顔跨濠电姭鍋撳ù鐘差儐閻撴洟鏌曟繛鍨妞ゃ儱顦伴妵鍕敇閻愬鈹涘銈忛檮閻擄繝寮婚敐澶婄叀闁糕剝顨呯粻铏圭磽娴ｈ櫣甯涚紒璇茬墦楠炲啯绂掔€ｎ偒妫冨┑鐐村灦椤ㄥ牓骞戦弴銏♀拻濞达綀顫夐妵鐔访瑰鍕噰鐎规洩绻濆畷姗€鎳犻浣诡啎闂備礁缍婇崑濠囧礂濮椻偓瀵劍绂掔€ｎ偄鈧敻鏌ㄥ┑鍡欏嚬缂併劋绮欓弻锝夋晲婢跺瞼鏆梺鍝勭焿缂嶁偓缂佺姵鐩鎾倷閺夋寧鎲㈡繝鐢靛Х閺佹悂宕戝☉妯忔椽顢橀悜鍡楁濡炪倖娲嶉崑鎾垛偓瑙勬礈閸樠囧煘閹达箑骞㈡繛鍡樺灥閺勩儲绻濈喊澶岀？闁稿鍨垮畷鎰板冀瑜滃鏍喐閻楀牆绗掔痪鎯ф健閺岀喖宕滄担瑙勭彧閻庤鎸风欢姘跺蓟濞戙埄鏁冮柣妯诲絻婵洟姊洪幎鑺ユ暠閻㈩垱甯″﹢渚€姊洪幐搴ｇ畵婵炲眰鍊濆畷婵堚偓锝庡枟閻撴洟鏌曢崼婵嗏偓鍛婄妤ｅ啯鈷掗柛灞剧懅椤︼附銇勯幘鑼煓鐎殿喖鐖煎畷褰掝敋閸涱喚绉甸梻鍌氬€峰ù鍥敋閺嶎厼绐楁慨妯挎硾缁€鍌涗繆椤栨繍鍞虹紒璇叉閺岋綁骞嬮敐鍡╂闂佺粯鎸荤粙鎴︽箒闂佹寧绻傞幊蹇涘箚閸績鏀芥い鏇炴濡绢喖菐閸パ嶈含闁诡喗鐟╅、鏃堝礋閵娿儰澹曢梺鍝勭▉閸嬪懘寮冲鍐ｆ斀闁绘ɑ褰冮顏呫亜閹邦亞鐭欓柡灞界Ч婵＄兘鏁傞悾灞肩礃闂備礁鎼鍡楊潖鐟欏嫮鈹嶅┑鐘叉祩閺佸秵绻濋棃娑欘棛婵顨堢槐鎺楁倷椤掆偓閸斻倝鏌涘顒夊剶濠碉紕鏁诲畷鐔碱敍濮樿京娼夐梻浣规偠閸庢粓宕掑☉姘稁濠电姷鏁告慨顓㈠箯閸愵喖绀嬫い鎾村閸嬫捇骞掑Δ浣哄帗閻熸粍绮撳畷婊冣枎閹炬潙鈧埖鎱ㄥ鍡楀⒒闁绘柨妫欐穱濠囶敍濮樿鲸鐧侀梺绋款儐閹告悂锝炲┑瀣垫晝闁靛繒濮烽妶顕€姊绘担铏瑰笡濞撴碍顨婂畷鎶芥晲閸涱垱娈鹃梺鍓插亝濞诧箓寮崱妤婄唵閻犺桨璀﹂崕鎰箾閸涱厾效婵﹦绮幏鍛存惞閻熸壆顐奸梻浣告啞濮婂綊鎮ч弴鈶┾偓锕傚垂椤斻儳鍠撴禍鎼佸冀瑜屾竟鏇㈡⒑閸撹尙鍘涢柛瀣瀹曪綁鍩€椤掆偓閳规垿顢欑涵宄颁紣濡炪値鍘奸崲鏌ユ偩閻戣棄绠抽柟瀛樻⒐閻庡姊洪悷鎵憼缂佽鍊块垾鏍ㄥ緞閹邦厸鎷绘繛杈剧悼閻℃棃宕甸崘顔界厱闁绘ê纾晶鐢告煙椤斿搫鍔﹂柟顔瑰墲閹棃鏁愰崱姗嗗晭闂傚倷绀侀幖顐⒚洪妸鈺佺？闁规壆澧楅崑鍌炴煏婢跺棙娅嗛柣鎾存礃閵囧嫰骞囬崜浣瑰仹缂備胶濮甸幐鍓ф閹烘绠涙い鎾跺Л濡插牆顪冮妶搴濈盎闁哥喎鐡ㄦ穱濠囧醇閺囩偛鑰垮┑顔筋殔濡瑩鍩涢弽銊х瘈缁剧増蓱椤﹪鏌涚€ｎ亜顏柍褜鍓氱喊宥咁熆濮椻偓椤㈡岸鏁愰崶鈺冪厯闁圭厧鐡ㄩ幐濠氾綖瀹ュ應鏀介柍钘夋閻忥箓鏌￠埀顒勬焼瀹ュ懏顥濋梺閫炲苯澧存慨濠勭帛閹峰懘鎼归悷鎵偧闂佽棄鍟虫ご鎼佸Φ閸曨垰绫嶉柍褜鍓熼幃褔鎮╁顔兼闂佺懓澧庨悺鏃堝极瀹ュ鐓熼柟閭﹀墻閸ょ喖鏌涘Ο缁樺磳闁诡喖鍢查…銊╁礋椤撶姷鍘滈柣搴ゎ潐濞叉鍒掑畝鍕厺閹兼番鍔岀粻鑽も偓瑙勬礀濞诧箓鎮炴ィ鍐┾拺闁煎鍊曟牎婵炲瓨绮堢划娆忕暦濠靛洦鍎熼柍顓滃劜閻╊垶銆佸☉姗嗙叆闁告洦鍋呴悗楣冩⒒娴ｅ憡鎯堥柛鐕佸亰閹囧幢濞戞瑥鐝旈梺缁樻煥閹芥粎绮绘ィ鍐╃厵閻庢稒顭囬幊鍐煟韫囧﹥娅婃鐐叉閹垽宕楃亸鏍ㄥ闂傚倸鍊搁悧濠冪瑹濡ゅ懏鍋傛い鎾跺亹閺€浠嬫煃閵夈劍鐝柛鐘趁埞鎴﹀焺閸愨晛鍞夊Δ鐘靛仜濞差參銆佸Δ浣哥窞閻庯綆浜炲Σ锝夋⒒閸屾瑧绐旀繛浣冲洦鍋嬮柛鈩冿供濞堜粙鏌熼梻纾嬪厡鐎规挷绶氶弻鈥愁吋閸愩劌顬嬬紓浣哄█缁犳牠骞冨鈧幃娆撳箵閹哄棗浜鹃柛娑橈攻閸欏繘鏌涚仦鍙ョ繁婵炲牅绮欓弻锝夊箛椤栨氨姣㈢紓浣哄Т椤兘寮婚悢纰辨晩閻熸瑥瀚悵鏍⒑閻熸澘绾фい銊ユ楠炲繘宕ㄩ弶鎴濈獩婵犵數濮撮幊鎰般€侀崨瀛樷拻濞撴埃鍋撻柍褜鍓涢崑娑㈡嚐椤栨稒娅犻柛鎾楀懐锛濋悗骞垮劚閹冲繘藟閵忊懇鍋撶憴鍕闁搞劌鐏濋悾鐑藉础閻愨晜顫嶅┑鈽嗗灣閸樠勬叏閿旀垝绻嗛柣鎰典簻閳ь剚鐗曢蹇旂節濮橆剛锛涢梺鍦亾閻ｎ亝绂嶅鍕╀簻闁规崘娉涙禒婊勪繆閼碱剛甯涢柕鍥у椤㈡洟濮€閵忋埄鍞堕梺缁樻尪閸婃牠濡甸崟顔剧杸闁圭偓鍓氭禒楣冩倵鐟欏嫭灏紒澶嬫尦閳ユ棃宕橀鍢壯囨煕閳╁厾顏堝汲濡ゅ懏鈷戠紒瀣儥閸庢劗绱掔€ｎ偄绗氱紒宀冮哺缁绘繈宕惰缁卞爼姊洪崨濠冪８闁告柨绉瑰顒勫焵椤掍椒绻嗛柣鎰典簻閳ь剚鐗曢～蹇旂節濮橆儵銉╂倵閿濆簼鎲鹃柛鐔锋嚇閺屾洘绔熼姘櫧闁挎稒绻堥幃妤呯嵁閸喖濮庨梺褰掓敱閸ㄥ潡鎮￠鍕垫晢濞撴艾娲﹂鏃堟⒑缂佹ê濮堢憸鏉垮暣瀵啿鈻庨幘瀛樺殙闂佸搫绋侀崢浠嬫偂閺囩喓绡€濠电偞鍎虫禍楣冩⒑缂佹ê閲滅紒鐘虫尭椤曪綁寮婚妷锔芥珳婵犮垼娉涢鍌炲箯濞差亝鈷掗柛灞炬皑婢ф稓绱掔€ｎ偅灏电紒顔款嚙椤繈顢樺┑鍫㈢暰闂備胶绮悷锕傛偡閵夈儍娲Χ閸モ晙绗夊銈嗙墬缁嬫挾绮婚崜褉鍋撻悷鏉款棌闁哥姵娲滈懞杈ㄧ附閸涘﹦鍘撻梻浣哥仢椤戝懘鎮橀幘顔界厸閻忕偛澧介埥澶愭煃閽樺妲告い顐ｇ矒瀹曠厧鈹戦崱鈺傛祮缂傚倸鍊搁崐鐑芥嚄閼稿灚鍙忛柣銏㈩焾缁犳煡鏌涢妷顔煎缂佺姵鐗楁穱濠囧Χ閸屾矮澹曟俊鐐€ら崑鍛崲閸儱绠栭柍鈺佸暞閸庣喖鏌曡箛锝嗙窔闁规煡绠栧濠氬磼濞嗘埈妲梺鍦拡閸嬪﹪鐛繝鍐╁劅闁靛绠戞禍顖涚節闂堟稑鈧悂骞楀鍐殼濞撴埃鍋撻柡灞剧洴婵＄兘顢欓悡搴浇闂備胶顭堥鍛搭敄婢舵劕钃熸繛鎴欏焺閺佸啴鏌ｅΟ鍨毢濞寸姷鍘ц灃闁绘﹢娼ф禒婊堟煟濡や焦灏い顐㈢箻閹煎湱鎲撮崟顐ゅ酱闂備礁婀辩划顖滄暜閹烘嚩鎺楀箛椤斿墽锛濋梺绋挎湰濮樸劌鐡繝纰樻閸嬪懐鎹㈤崒鐐村仼闁绘垼妫勭粻锝夋煥閺囨浜鹃悗鐟版啞缁诲啴濡甸崟顖氬唨闁靛ě鍕珮闂備礁鎲￠幐鍫曞礉瀹€鍕ㄢ偓鏃堝礃椤斿槈褔鏌涢埄鍏狀亪鎷曟總鍛娾拺闁硅偐鍋涙俊鑺ヤ繆閻愭壆鐭欐鐐插暣閺佹捇鎮╅懠顒夋О婵＄偑鍊栧Λ浣肝涢崟顒傤浄妞ゆ挾鍋愰弨浠嬫煟閹邦剙绾фい銉︾矌缁辨帞绱掑Ο鍝勵潚濡炪們鍨哄Λ鍐春閿熺姴宸濇い鏃€鍎抽獮妤呮⒒婵犲骸浜滄繛璇х畵楠炴牠鍩￠崨顓炴優闂佺粯鏌ㄩ崥瀣偂閸愵亝鍠愭繝濠傜墕缁€鍫熺節闂堟侗鍎滅紓宥嗙墪椤法鎹勭悰鈥愁潓闂佸憡绻傜€氣偓闁绘梻鍘х粈鍌炴煕韫囨挸鎮戞い鏂挎喘濮婄粯鎷呴崨濠呯闂佺绨洪崐婵嬪Υ閸愵喖宸濋悗娑櫭禍妤€鈹戦濮愪粶闁稿鎹囬弻鈥崇暆閳ь剟宕伴幇顒夌劷闊洦绋戠粈鍫㈡喐韫囨稑姹查柣妯肩帛閳锋垹绱撴担濮戭亝鎱ㄩ崶顒佺叆闁哄洢鍔嬮柇顖溾偓娈垮枛椤攱淇婇懜闈涚窞濠电姴鍊婚悰鈺佲攽閻樺灚鏆╁┑顔肩摠椤ㄣ儵骞栨担鍝ユ煣闂佸憡顨堥崑鎰板绩娴犲鐓冮柦妯侯槹椤ユ粌霉濠婂嫮鐭掗柟顔筋殔椤繈顢橀悢鍝勫殥婵＄偑鍊ら崑鍕崲閹寸姵宕叉繝闈涙－濞尖晜銇勯幒鎴濅喊缂佸崬寮剁换婵嬫偨闂堟稐绮跺┑鈽嗗亝閻熲晛鐣峰ú顏勯唶婵犮埄浜风紞渚€銆佸璺虹劦妞ゆ巻鍋撴い顐㈢箰鐓ゆい蹇撳瀹撳秴顪冮妶鍡樺暗闁稿孩鍔欏畷鐢稿Ψ閳哄倵鎷洪梻鍌氱墛缁嬫挻鏅堕弴鐔剁箚妞ゆ劧绲块幊鍥┾偓瑙勬礃婵炲﹪骞冨鍫熷殟闁靛鍨虹€氫粙姊绘担渚劸闁哄牜鍓熼幃鐑藉Ω閳轰胶顦ч悗鍏夊亾闁告洦鍓涢崢閬嶆煙閼圭増褰х紒鏌ョ畺瀵娊顢楅崒妤€浜炬繛鍫濈仢閺嬬喖鏌ｉ幙鍕瘈鐎规洘妞介弫鎾绘偐閹绘帞鐛╂俊鐐€栭幐楣冨磻閻旂厧鐒垫い鎺戭槸瀵喗鎱ㄦ繝鍐┿仢鐎规洘绮撻獮鎾诲箳瀹ュ洤鍤┑鐘垫暩閸嬫稑顕ｉ崼鏇熸櫇闁靛繒濮烽弳锕傛煙鐎涙ɑ鍎曢柣鏃€鍝鸿瀹曞爼鏁傞崜褎鏅ㄩ梻鍌氬€风粈渚€骞栭锕€鐤い鎰ㄦ寣濞差亜围闁割偒鍋呭В鎰版⒒閸屾艾鈧兘鎳楅崼鏇椻偓锕傚醇濠㈡繂缍婇幃婊堟寠婢跺瞼宕堕梻浣告惈缁嬩線宕㈡總鍛婂珔闁绘柨鍚嬮悡娑㈡煕閵夆晩妫戠痪鎯ф健閺岋綁濡堕崒姘闂傚倷娴囬褔宕欓悾宀€绀婇柛鈩冾焽椤╂煡鏌ｉ幇顓熺稇妞ゆ洟浜堕弻娑㈠即閵娿儳浠梺鎶芥敱閸ㄧ敻婀侀梺绋跨箺閸嬫劙骞婇崨瀛樼厽闁挎繂顦幉楣冩煛瀹€瀣埌閾绘牕霉閿濆洦鍤€缁炬澘绉撮—鍐Χ鎼粹€茬盎缂備胶绮敃銏ょ嵁閺嶎兙浜归柟鐑樺灦瀹撳秴顪冮妶鍡樺暗濠殿喚鍏樺畷銏ゎ敍閻愮补鎷绘繛杈剧到閹诧紕鎷归埄鍐︿簻妞ゆ挾鍋熸晶銏ゆ煃瑜滈崜姘辩矙閸儱鐤鹃柣妯垮吹瀹撲線鐓崶銊р姇闁绘帟鍋愰埀顒€绠嶉崕鍗炍涘畝鍕婵炲樊浜濋埛鎴犵磽娴ｈ偂鎴犱焊椤撶喓绠鹃柟缁㈠櫘濡垹绱掗鑺ヮ棃闁圭厧缍婂畷鐑筋敇閻欏懐搴婇梻鍌欒兌缁垶鏁嬬紒鍓ц檸閸樹粙寮查崼鏇ㄦ晜闁割偆鍠撻崢浠嬫⒑閹稿海绠撴繛灞傚€濆畷銏⑩偓娑櫱滄禍婊堟煏韫囧﹥顫婃繛鍫熺矌閳ь剝顫夊ú婊堝窗閺嶎厹鈧線寮撮悩顐壕闁挎稑宕€氼參鎮靛鑸碘拺闁告繂瀚～锕傛煕閺冣偓閸ㄧ敻顢氶敐澶樻晪闁逞屽墮閻ｇ兘宕奸弴鐐嶁晝鎲哥€ｎ喖鐒垫い鎺嗗亾闁挎洩濡囧Σ鎰板箻鐎涙ê顎撻梺鍛婄箓鐎氬懘鏁愭径瀣幘閻熸粎澧楃敮鐐烘偩濞差亝鐓冮柕澶涢檮椤ュ牏鈧娲橀敃銏ゃ€佸▎鎾冲簥濠㈣鍨板ú锕傛偂閺囥垺鐓冮柍杞扮閺嬨倖绻涢崼鐔糕拻闁诡噮鍠栭埞鎴犫偓锝庡亐閹风粯绻涙潏鍓у埌闁硅绻濆畷顖炴倷閻戞鍘电紓浣割儐椤戞瑩鎮℃總鍛婄厵妞ゆ牗鑹鹃顓熴亜閵忥紕鈽夋い顐ｇ箖濞煎繘濡搁敂璇叉櫗婵犵數濮甸鏍窗濡ゅ懏鏅濋柍鍝勬噹閸屻劌鈹戦崒姘棌闁轰礁顑夊娲敆閳ь剛绮旈悽绋跨９闁割煈鍋嗙粻楣冩煙鐎电浠ч柟铏姍閺岋綁骞掑鍥╃厯闂佸搫鏈粙鎴ｇ亽闂佸湱顭堢€垫帒螞閸曨垱鈷戦悗鍦濞兼劙鏌涢妸銉у煟闁绘侗鍠楃换婵嬪炊閵娧冨箞濠电姷鏁告慨鎾疮椤栨氨鏆︾€光偓閸曨剛鍘靛銈嗘⒐閸庤櫕绂掗柆宥嗙厸濞达絿顭堥弳锝夋煕閳规儳浜炬俊鐐€栫敮鎺斺偓姘煎弮瀹曟垿鍩℃笟鍥ㄥ瘜闁诲函缍嗘禍鐐哄礄鐟欏嫮绠剧€光偓婵犱胶鏁栫紓浣介哺閹稿骞忛崨瀛橆棃婵炴垶鐭惀顏呬繆閻愵亜鈧牕顫忛悷鎷旀盯宕橀…鎴炵稁闂佹儳绻愬﹢杈╁閸忛棿绻嗘い鏍ㄧ閹牊銇勯銏⑿ф慨濠呮閹风娀鍨惧畷鍥﹀摋闂備礁鍚嬪鍧楀垂閸洖鏄ラ柕蹇嬪€曠粻濠氭偣閸ャ劌绲荤€规挸妫濆铏圭磼濮楀棛鍔烽梺杞扮劍閹倿寮鍜佺叆闁割偆鍟块幏娲⒑鐠団€崇€婚柛娑卞灱閸熷牊淇婇悙顏勨偓銈夊磻閸曨垁鍥敍閻愯尙鍘洪悗骞垮劚椤︻垶宕￠幎鑺ョ厽婵☆垰鍚嬮弳鈺呮煥濞戞瑧鐭婃い顏勫暣婵″爼宕卞Ο閿嬪闂備礁鎼幏瀣磻婵犲洨宓佸┑鐘叉搐瀹告繈鎮楀☉娆樼劷闁告鏁诲娲嚒閵堝懏鐎惧┑鐘灪閿曘垽銆侀弮鍫晣闁靛骏绱曢崢鎾绘⒑闂堟侗妯堥柛銊﹀▕閹箖宕归顐ｎ啍闂佺粯鍔曞Ο濠囧磿韫囨稒鐓冮悷娆忓閻忓鈧娲橀崕濂杆囬鈧弻娑氣偓锝庡亝瀹曞本銇勯姀锛勬创闁诡喗鐟ч崚鎺旀喆閸曨偒浼滈梻鍌氬€烽懗鍫曗€﹂崼銉ュ珘妞ゆ帒瀚崵灞轿旈敐鍛殭闁绘帒鐏氶妵鍕箳閹存績鍋撻幖浣稿偍闁圭虎鍠楅悡娆撴煣韫囷絽浜芥繛鍫熺矌閳ь剝顫夊ú鏍Χ缁嬫鍤曢柟缁㈠枟閸婄兘鏌ｉ姀鐘典粵闁诲寒鍣ｅ濠氬磼濞嗘劗銈板銈庡亜椤﹂潧鐣烽弴銏犵闁兼亽鍎辨禒閬嶆⒑闂堟侗鐒鹃柛搴櫍瀵顓兼径瀣幗濠碘槅鍨遍娆忣潖鐠恒劍鍠愰柣妤€鐗嗙粭姘舵煕鐎ｎ偄濮夐柍褜鍓涢幊鎾寸珶婵犲洤绐楅柡宥庡幖缁€鍫ユ煙濞堝灝鏋ょ痪鎯с偢閺岋綁骞囬棃娑橆潻闂佸憡鏌ｉ崐鏍崲濞戞碍鍏滃瀣捣閻﹀牓鎮楀▓鍨灈妞ゎ厾鍏樺顐﹀箛椤撶偟绐炴繝鐢靛Т鐎涒晝绱為崒鐐粹拻濞撴埃鍋撴繛浣冲懏宕查柛鈩冪☉閻ょ偓绻濋棃娑卞剰缂佲偓婢舵劖鐓曟繝闈涘閸斻倗鐥幆褋鍋㈤柡宀嬬秮楠炲洭妫冨☉姗嗘交闂備礁鎲￠弻锝夊磹閺嶎厼桅闁告洦鍨奸弫鍥煟濡绲绘鐐差儔閹鈻撻崹顔界亪濡炪値鍘鹃崗姗€鐛崘顔碱潊闁靛牆鎳愰ˇ褔姊虹紒妯诲碍缂併劌鐖煎畷鎴﹀箻缂佹鍙嗛柣搴祷閸斿鑺辨繝姘拺闁荤喓澧楅幆鍫熶繆椤愶綆娈曠紒鍌氱Ч閹瑩顢楅崒婊呮闂備礁鍟块惃婵嬪磻閹剧粯鍊堕柣鎰仛濞呮洖霉閻欌偓閸樺墽妲愰幘瀛樺闁惧繒鎳撶粭锛勭磽娴ｅ壊鍎愰柟姝屽吹缁顓兼径濠勵啇婵炶揪绲块…鍫ュ船閵娾晜鈷戦梻鍫熶緱閻擃厼鈹戦垾铏┛闁靛洦鍔楅埀顒婄秵閸犳鍩涢幒鎳ㄥ綊鏁愰崨顔兼殘闂佽鍨伴悧鎾诲蓟閿熺姴閱囨い鎰╁灩椤晠鏌ｉ幘鍗炩偓鏍ㄧ┍婵犲浂鏁嶆繛鍡樺俯閸斿懘姊洪幖鐐测偓鏍€冩繝鍥ц摕婵炴垯鍨归崡鎶芥煏婵炲灝鍔ゅù鐘櫊濮婄粯鎷呯粙鑳煘濠电偠顕滄俊鍥箲閵忕姭鏀介悗锝庡亽濡啫鈹戦悙鏉戠仸闁煎綊绠栭妴鍌濄亹閹烘挴鎷洪柣鐘叉礌閳ь剝娅曢悵顖滅磽娴ｈ棄绱︾紒顔界懇瀹?")
        if weak_spots:
            if localized_weak_spot:
                parts.append("")
            else:
                parts.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棗鏆欏┑鈥炽偢閺屽秷顧侀柛鎾存皑閹广垽宕煎┑鎰婵犵數濮甸懝楣冨础閹惰姤鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú鐔奉潖閾忓湱纾兼俊顖氭惈琚濋梻浣告啞閹歌鐣濋幖浣哥畺闁汇垻顭堢猾宥夋煕椤愩倕鏆遍柟閿嬫そ濮婅櫣娑甸崨顓濇睏闂佺顑嗙粙鎺撶┍婵犲啰闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛瀣閹剝绺介崨濠勫幈闂佸疇顫夐崕铏閻愵兛绻嗛柣鎰典簻閳ь剚鐗滈弫顕€骞掑Δ鈧粣妤佹叏濮楀棗澧婚柣鎺嶇矙閺岀喖鏌囬敃鈧獮妯肩磼閻樿崵鐣洪柡灞剧☉閳诲氦绠涢敐鍠般劍绻濋埛鈧仦濂稿仐闂佽鍣换婵囦繆閼搁潧绶為悗锝庡墮瀵娊姊绘担鍛婃儓婵炲眰鍔戝畷鎴濃槈濞嗘埈娲搁梺瑙勵問閸犳氨澹曢悾灞稿亾楠炲灝鍔氭俊顐ｇ⊕閺呭爼鎮介崨濠勫幐閻庡厜鍋撻悗锝庡墰閻﹀牓鎮楃憴鍕闁绘牕銈稿畷娲晸閻樿尙鍔﹀銈嗗笒閸婂綊锝為弴鐘亾鐟欏嫭绀€婵炶绠撳畷浼村箛閻楀牏鍘藉┑掳鍊愰崑鎾绘煟濡も偓濡稓鍒掗鐑嗘僵闁煎摜鏁搁崢閬嶆煟鎼搭垳绉靛ù婊勭矒閸┾偓妞ゆ巻鍋撴繛纭风節閹即顢氶埀顒€顕ｆ禒瀣╅柨鏂垮⒔鑲栭梻鍌欑閹诧繝骞愰崱娑樿Е闂佸灝顑呴悘瀛樻叏婵犲懏顏犻柟鍙夋尦瀹曠喖顢曢妶鍥ュ仭闂傚倷绶氬褔鎮ц箛娑掆偓锕傚醇閵夘垳绋忛棅顐㈡处缁嬫帡骞嗛悙鐑樼厱闁挎棁顕ч獮姗€鏌ｉ幘瀛樺碍闁宠鍨块幃娆撳矗婢舵ɑ锛侀梻浣侯焾鐎涒晜绻涙繝鍌滄殾婵犲﹤鐗嗙痪褎绻涢崱娆忎壕閻庨潧鐭傚娲濞戞艾顣哄┑鈽嗗亝椤ㄥ﹪骞冨鈧俊鐑芥晜鏉炴壆鐩庨梻浣瑰濞叉牠宕愰悷鎵虫鐟滃酣濡甸崟顖氬嵆妞ゅ繐妫涜摫缂傚倷鑳剁划顖滄崲閸岀儑缍栨繝闈涱儛閺佸洭鏌ｉ弬鎸庢喐鐟滄澘鎲＄换婵嬫偨闂堟刀鐐烘煕閵娧冨付闁崇粯鏌ㄩ埥澶愬閳哄倹娅堥梻浣告啞娓氭宕板韬测偓鍛村矗婢跺瞼鐦堟繝鐢靛Т閸婄粯鏅跺☉銏＄厓闂佸灝顑呴悘鎾煛鐏炲墽鈽夐柍钘夘槸椤粓宕煎┑鍡╂浆闂傚倷绀侀悿鍥涢崟顖€鍥偨缁嬭儻鎽曢梺闈浥堥弲娑㈠础閾忣偁浜滈煫鍥ㄦ尰椤ョ娀鏌￠崱鎰偓婵嬪箖濡ゅ啯鍠嗛柛鏇ㄥ墰椤︺劑姊洪懡銈呮毐闁哄懐濮撮锝夘敃閿曗偓缁犺崵绱撴担濮戭亝绂嶈ぐ鎺撯拺闁告繂瀚埀顒€鐖煎畷鏇㈡嚑椤戣棄浜炬慨妯哄暱娴滃湱绱掓潏銊﹀磳鐎规洘甯掗～婵嬵敄閽樺澹曢梺缁樺灱婵倝宕愰崸妤佺叆闁哄洨鍋涢埀顒€缍婂鏌ヮ敂閸℃瑧锛濋梺绋挎湰閻熝囧礉瀹ュ棎浜滈柕濞垮劜椤ョ娀鏌℃笟鍥ф珝闁轰焦鎹囬幃鈺呮嚑閼稿灚鍟洪梻鍌欑閹碱偄煤閵忋倕鍨傜憸鐗堝笚閻撲線鏌涢妷顔煎闁绘挾鍠栭弻锟犲礃閵娿儰绨介梺缁樺浮缁犳牠寮诲鍫闂佸憡鎸诲畝绋跨暦濠靛柈鏃堝川椤撶姴濮︽俊鐐€栫敮濠勬閿熺姴鐤煫鍥ㄧ⊕閻撴洟鏌ｅΟ铏癸紞濠⒀呮暬閺屽秹濡烽婊呮殼闂佽鍠楃划鎾诲箰婵犲啫绶為悗锝庡厴閸嬫捇顢楅崟顑芥嫼閻熸粎澧楃敮鎺撶娴煎瓨鐓曟俊顖氱仢娴滆绻涢崱鎰伈闁诡喗鐟ラ湁閻庯綆鍋呴弶鎼佹⒒娴ｈ櫣甯涢拑杈╂喐閺夊灝鏆ｆい銏℃閸╋繝宕掗妶鍡╁晬闂備胶绮崝鏍ь焽濞嗘劖鍙忛柛銉墯閻撳啴鎮峰▎蹇擃仼闁诲繑鎸抽弻鐔碱敊鐟欏嫭鐝氶悗瑙勬礀缂嶅﹪銆侀弴銏℃櫜闁糕剝鐟﹂～鏍р攽閻樺灚鏆╁┑顔炬暬椤㈡瑩寮介鐐电崶濠德板€曢幊搴ｇ不娴煎瓨鐓曢柟閭﹀灠閻ㄦ椽鏌￠崱顓犵暤闁哄瞼鍠栭弻鍥晝閳ь剟寮搁妶鍥╂／闁诡垎鍐╁€繛锝呮搐閿曨亪銆佸☉妯锋敠闁绘劦鍓欓悵杈ㄧ節閻㈤潧浠︽繛鍏肩懅閳ь剚鐭崡鎶界嵁閸愩劎鏆嬮梺顓ㄥ閸欏棝姊洪崨濠傚Е濞存粎鍋ら、娆愮節閸屾鏂€闂佺偨鍎遍崯璺ㄧ棯瑜旈弻娑㈠籍閳ь剟鎮烽埡鍛仒妞ゆ柨妲堥悢鐓庣闁绘挸娴疯ぐ鎾⒒娴ｈ棄浜归柍宄扮墦瀹曟粓濡歌椤洟鏌涘▎蹇ｆШ缂佲檧鍋撴繝鐢靛仜閻楀棝鎮樺┑瀣嚑闁绘柨鍚嬬€氬懘姊洪鈧粔鐢告偂閻斿吋鐓ラ柡鍐ｅ亾闁稿孩濞婂畷銏ゅ级閹存梹鏂€濡炪倖姊婚幊鎾寸妤ｅ啯鈷掑ù锝囨嚀椤曟粎绱掔€ｎ偄鐏╅柍褜鍓氶崙褰掑闯閿濆鈧礁鈻庨幘鍐插祮闂侀潧楠忕槐鏇㈠储娴犲鈷戠紓浣光棨椤忓嫷鍤曢柛顐ｆ礀閸屻劑鏌涘畝鈧崑鐐烘偂閺囩喓绠鹃柟瀛樼箓閼稿綊鏌ｈ箛濠傚⒉缂佺粯鐩畷鐓庘攽閸℃ê鈧垱绻涢敐鍛悙闁挎洦浜濇穱濠囧醇閺囩偟鍊炲銈庡墻閸犳捇宕曢悽绋胯摕婵炴垶鍩冮崑鎾绘晲鎼粹€茬敖闂侀潧妫欑敮锟犲蓟閻旇偐宓侀柛顭戝枤娴犲ジ鏌ф导娆戠М闁哄睙鍡欑杸婵ê鍚嬬紞鍫濃攽閻愯尙澧︾紒鐘崇墪椤繐煤椤忓拋妫冨┑鐐寸暘閸婃牠鎯勯鐐叉槬闁逞屽墯閵囧嫰骞掗幋婵愪患缂佺偓鍎抽…鐑藉蓟閻斿吋鍊锋い鎺嶈兌娴煎洤鈹戦埄鍐ㄧ祷闁绘锕﹂幑銏犫槈閵忕姵銇濇繛杈剧悼椤牏鈧冻绲剧换娑氣偓娑欘焽閻绱掔拠鎻掝伀闁告帗甯為埀顒婄秵娴滃爼宕ョ€ｎ喗鐓曟い鎰剁悼閳笺儲鎱ㄧ憴鍕垫疁婵﹥妞藉畷鐑筋敇閻愭彃顬嗛梻浣烘嚀閹诧繝骞愰幎鐣屽祦闊洦鎷嬪ú顏嶆晜闁告侗浜濈€氬ジ姊洪懡銈呅㈡繛鑼█閸┾偓妞ゆ巻鍋撶痪缁㈠弮閸┾偓妞ゆ巻鍋撴い顓犲厴瀵鈽夐姀鐘插祮闂侀潧顭堥崕杈┾偓娑崇到閳规垿鎮欓弶鎴犵シ闂佺粯鐗滈崢褔锝炶箛鏇犵＜婵☆垵顕ч鎾寸箾閹炬潙鍤柛銊﹀▕瀹曟繄绮欏▎鐐瘜闂侀潧鐗嗗Λ妤呮倶閵夆晜鐓欓柧蹇ｅ€嬮鍫熷仼闁绘垼妫勭粻娑欍亜閹捐泛啸闁伙箑鐗嗛埞鎴︻敊閺傘倓绶甸梺鍛婃尰閻╊垵妫熷銈嗗姧闂勫嫰鍩涢幋锔界厱闁挎棁顕ч獮鏍煕閺傛鍎愰柕鍥у婵℃悂濡疯椤旀帡鎮楀▓鍨珮闁稿瀚伴、姗€宕楅悡搴ｇ獮闁诲函缍嗛崜娆撶嵁濡ゅ懏鈷掑ù锝呮憸缁夋椽鏌涚€ｎ亷韬€规洘绮撻弫鍐磼濮橆剚鍎梻浣虹帛閺屻劑宕ョ€ｎ喗鍋傞柡鍥╁枍缁诲棙銇勯弽銊х煀闁告柨顑夐弻娑㈡偄閸濆嫪鎴风紓浣介哺鐢偟妲愰幒鎳崇喖鎳栭埡鍐╂緰婵犵數濮甸鏍窗閹烘纾婚柟鍓х帛閳锋垿鏌熺粙鎸庢崳缂佺姵鎸绘穱濠囶敃閿濆洦鍒涙繝纰樺墲閹告娊鐛崶顒夋晞闁兼亽鍎查弶鎼佹⒒娴ｅ摜鏋冩俊顐㈠铻炴俊銈勮兌椤╁弶绻濋棃娑卞剱闁绘挾鍠栭弻锝夊籍閳ь剙顭囧▎鎾崇闁挎洖鍊归悡鏇㈡煃閻熸壆浠㈤柣蹇婃櫆閵囧嫰骞橀崘鍙夊€悗鍨緲鐎氼厾鎹㈠┑瀣＜婵犻潧鍟禍楣冩煕椤垵鏋撻柡鈧禒瀣厽闁归偊鍘界紞鎴︽煟韫囥儳鐣甸柡宀嬬秮閹垹鈹戦崱妯绘倷闂佺琚崝鎴濐潖濞差亶鏁嗛柍褜鍓涚划鏃堟偨缁嬭法鍘遍梺纭呮彧闂勫嫰鍩涢幒妤佺厱妞ゆ劑鍊曢弸搴ｂ偓瑙勬礈閸犳牠寮诲☉銏╂晝闁绘ɑ褰冩慨搴ㄦ⒑濮瑰洤鈧宕戦幘鑸靛床婵犻潧娲ㄧ弧鈧梺绋挎湰绾板秴鈻撳鍐ｆ斀闁斥晛鍟徊濠氭煟濡も偓缁绘﹢鐛径鎰窛濠电姴鍟崝鍛存⒑闂堟侗鐒鹃柛搴㈢懇閺佸啴宕掑☉姘箞闂備礁鎼ú銏ゅ礉瀹€鍕€堕柣妯肩帛閻撴洘淇婇妶鍛仾闁绘繍浜弻鏇㈠炊瑜嶉顒傜磼閻樺磭娲存鐐达耿楠炴牠顢橀悤鍌炵崪闂備浇宕甸崑鐐烘偄椤掑倻涓嶉柟鐐墯濞兼牜绱撴担鑲℃垶鍒婇幘顔界厽闁瑰浼濋鍕ㄦ灁鐎光偓閳ь剛妲愰幒妤€绀堢憸鎴濐瀶閹间焦鐓曟繛鍡楃箰閺嗘瑩鏌ｉ敐鍥у幋妤犵偛顑夐弫鍐焵椤掆偓濞插潡姊绘担铏广€婇柛鎾寸箓鐓ゆ繝濠傛噽娑撳秵鎱ㄥΟ鍨厫闁抽攱鍨圭槐鎾存媴婵埈浜幃妯绘綇閵娿倗绠氬銈嗗姂閸ㄥ綊顢旈埡鍛厸濞撴艾娲ゅ▍宥夋煛瀹€瀣М闁诡喓鍨藉畷顐﹀Ψ瑜忛崢鎰磽閸屾瑨鍏岀紒顕呭灦閺佸啴濮€閵堝洤绁﹂梺鍛婂姀閺呮盯顢氶柆宥嗙厵缁炬澘宕獮妤呮煛閸滀椒閭慨濠冩そ閺屽懘鎮欓懠璺侯伃婵犫拃鍐惧殶闁逞屽墯椤旀牠宕伴弽顓涒偓锕傛倻閽樺鐎梺鍦濠㈡﹢鐛姀鈥茬箚妞ゆ牗纰嶉幆鍫濃攽閳╁啫鈻曟慨濠勭帛閹峰懘鎮烽柇锕€娈濈紓鍌欑椤戝棝宕硅ぐ鎺戠劦妞ゆ帊绀侀崵顒勬煕閿濆繒鍒版い鏇秮瀹曟ê霉鐎ｎ偒娼旈梻渚€娼х换鍡楊瀶瑜旈獮蹇涙惞閸︻厾锛濇繛杈剧到婢瑰﹪宕曡箛鏃傜缁绢參顥撶弧鈧悗瑙勬穿缂嶄礁鐣烽悢纰辨晝闁逞屽墴閹兘鏌囬敂鎯у汲闂備礁鎲￠崝锔界濠婂牊鍋傞柣鏂垮悑閳锋垹绱撴担濮戣偐娆㈤柆宥嗙厱闁绘ɑ鍓氬▓姗€鏌熼獮鍨仼闁宠鍨归埀顒婄秵娴滅偤藝閵娾晜鈷戦悗鍦У閵嗗啰绱掗埀顒佹媴闁稓绠氶梺瑙勫劶婵倝鍩涢幒鎳ㄥ綊鏁愰崨顔藉枑闂佸搫顑呴崯顐︹€旈崘顔肩骇闁瑰鍋為崰鎰版⒑鏉炴壆璐伴柛鐘崇墳閻忓啴姊洪崨濠傚闁哄懏绮岄埢鎾诲级鎼存挻鏂€闁圭儤濞婂畷鎰板箛閺夎法锛涢梺鍦亾閻ｎ亝绂嶅鍫熺厸闁搞儺鐓侀鍫濈闁挎棃鏁崑鎾舵喆閸曨剛顦梺鍝ュУ閻楃娀濡存担绯曟婵妫欓崓鐢告煛婢跺﹦澧愰柡鍛矊椤潡骞嬪┑鍐╂杸闂佹寧绋戠€氼剚绂嶆總鍛婄厱濠电姴鍟版晶鍨殽閻愭潙濮嶉柟顔界懇椤㈡鎷呯粙澶哥礋闂傚倷绀佸﹢閬嶆惞鎼淬劌绐楁慨姗嗗墰閺嗐倕霉閿濆鍋撳☉姘辩暰闂備線娼ч悧鍡欌偓姘煎灦瀹曟鐣濋埀顒傛閹烘鐓㈤柍褜鍓熷畷鎴﹀箻缂佹ǚ鎷绘繛杈剧到濠€鍗烇耿娴犲鐓曢柕濞垮妽椤ュ銇勯鐐寸┛妞わ附鐓￠弻锝夊煡閸℃绫嶅┑顔硷功缁垶骞忛崨瀛樺仭闂侇叏绠戝▓婵囩節閻㈤潧浠︾憸鏉垮暟閹广垹螣閾忚娈鹃梺褰掑亰閸庣敻寮崼婵嗙獩濡炪倖鎸炬慨瀛樻叏閿旀垝绻嗛柣鎰典簻閳ь剚鐗滈弫顔界節閸曨厾鐒兼繛鎾村焹閸嬫挾鈧娲滈弫濠氥€佸Δ鍛妞ゆ帒鍊搁獮鍫ユ⒒娴ｇ瓔娼愮€规洘锚閳绘柨鈽夐姀鐘插殤濠电偛妫欓崝鎺旀崲閸℃ǜ浜滈柟閭﹀枛瀛濋梺璇茬箲閻擄繝寮婚垾宕囨殕閻庯綆鍓涜摫闂備浇顕栭崹鍗炍涢崘顔衡偓浣糕槈濮楀棛鍙嗛梺鍛婄☉閹锋垹绱炴担鍓叉綎闁惧繐婀遍惌娆愮箾閸℃ê鍔ら柛鎾存緲閳规垿鍩ラ崱妞剧凹缂備礁顑嗛幑鍥х暦濮樿泛绠抽柡鍐ㄥ€婚敍婊冣攽閳藉棗鐏ｆい顓炵墛缁傚秴鈹戠€ｎ偀鎷洪梺鍛婄☉閿曘倖鎱ㄩ埀顒勬⒑閸濆嫭鍣虹紒璇茬墕閻ｇ兘濮€閵堝懐顢呴梺缁樺灥濡瑧鈧潧鐭傚娲濞戞艾顣哄┑鈽嗗亝椤ㄥ棝骞堥妸鈺佺＜闁绘劕顕崢杈ㄧ節閻㈤潧孝闁哥噥鍨崇划鍫⑩偓锝庡厴閸嬫挸鈻撻崹顔界亪闂佺顕滅换婵嬬嵁閸℃稑绫嶉柛顐ｆ儕閳哄懏鐓ラ柡鍐ｅ亾闁稿孩濞婇悰顔嘉旈崨顔规嫽婵犵數濮存鍛婄濠婂嫮绠鹃悹鍥囧懐鏆犲銈庡亜缁绘ê鐣烽悜绛嬫晣婵犻潧鐗嗘晶楣冩⒒娴ｇ懓顕滄繛鍙夌墵瀹曟劘銇愰幒鎾充簵濠电偞鍨堕崺鍐磻閹捐绀傚璺猴梗婢规洟姊绘笟鈧埀顒傚仜閼活垱鏅剁€电硶鍋撶憴鍕；闁告鍟块锝嗙鐎ｅ灚鏅ｉ梺缁樺姈椤旀牠宕崶顒佺厽闁绘柨鎽滈惌灞筋熆瑜庨〃鍫ュ极椤曗偓閸╋繝宕ㄩ鐔衡偓顒勬⒑閸涘﹤濮﹂柛鐘愁殜閹繝濡烽敂鍓х槇闂傚倸鐗婄粙鎺椝夐悙鐑樼厱闁靛牆鎳忛崰姗€鏌″畝瀣ɑ闁诡垱妫冩俊鍫曞幢閳衡偓閸濇绱撻崒娆愮グ濡炲瓨鎮傞獮鎴﹀炊瑜忛弳锕傛煙閻戞ê鐏嶉柡瀣叄閺岀喓鈧稒顭囩粻鎾淬亜椤掆偓椤︾増绌辨繝鍥ㄥ€锋い蹇撳閸嬫捇骞嬮敃鈧粈澶屸偓鍏夊亾闁告洦鍓欐禍閬嶆⒑鐟欏嫬鍔ょ痪缁㈠弮瀵娊鏁冮埀顒勬箒闂佺绻愰崥瀣礊閹达附鐓曢柟鑸妼娴滄儳鈹戦敍鍕杭闁稿﹥鐗犻獮鎰偅閸愩劎锛涢梺缁樺姇瀵剟鏁愭径妯绘櫌闂佸憡娲﹂崗姗€骞忓ú顏呪拻濞撴艾娲ゆ禍鐐烘煕鐎ｎ偆娲撮柟宕囧枛椤㈡稑鈽夊▎鎰娇婵＄偑鍊栭悧婊堝磻閻愮儤鍋傞煫鍥ㄧ⊕閻撴洟鏌曟径瀣仴闁哥姵纰嶇€靛ジ宕橀妸搴㈡閹晠妫冨☉妤佸媰闂佹眹鍩勯崹顏堝焵椤掆偓绾绢參寮抽敃鍌涚厱婵°倕鍟崜杈ㄧ箾閹炬剚鐓奸柡宀€鍠栭、娑㈠幢濡や焦鎷卞銈冨劵缁绘繂顫忔繝姘＜婵﹩鍏橀崑鎾绘倻閼恒儱鈧潡鏌ㄩ弴妤€浜鹃梺浼欑到閸㈣尪鐏掗梺鎯х箺椤鈻撴ィ鍐┾拺婵懓娲ら悘顔姐亜椤撶偟澧㈠瑙勬礃缁绘繂顫濋鐘插妇闂備礁澹婇崑鍛崲瀹ュ憘锝夊箹娴ｅ湱鍙冮梺鍛婂姦娴滄粓寮稿☉銏＄厸閻忕偟鍋撶粈瀣偓瑙勬礈閸樠囧煘閹达箑绠涙い鎾愁檧闂勫嫮鎹㈠☉姘棜閻庯綆浜欏Ч妤佺節閻㈤潧浜归柛瀣崌濮婃椽宕崟顒佹嫳濠电偛寮堕敋妞ゆ洏鍎靛畷鐔碱敃鐎ｎ剙鏋涢柟顔界矊铻ｉ梻鍌氱摠閸犳碍绻濋悽闈浶ラ柡浣规倐瀹曟垵鈽夐姀鈥充罕婵犵數濮撮崯浼存偟閸洘鐓曢柍鈺佸暟閹冲嫭銇勯锝嗙闁哄瞼鍠栭獮鍡氼槾闁圭晫濮撮埞鎴︻敍濞戞瑥鍞夐梺鍝勭焿缂嶄線骞冮姀銈呬紶闁告洖鐏氬В澶愭⒒娴ｅ憡鎯堟俊顐ｇ懄缁旂喖宕卞▎鎰垫綗闂佽鍎抽悺銊﹀垔閹绢喗鐓曢柨鏃囶嚙楠炴牜鈧鍠撻崝搴ｆ閹惧瓨濯撮柛婵嗗珔閿濆鐓熸俊銈呭暙閳诲牓鏌熼璇插祮妞ゃ垺宀搁崺鈧い鎺嗗亾闁伙綁鏀辩缓鐣岀矙鐠囦勘鍔戦弻鏇熷緞婵犲嫬鍝洪梺鍝勬噽婵炩偓鐎殿喖顭峰鎾偄妞嬪海鐛┑鐘垫暩婵挳宕戦崱娑樼濠㈣泛艌閺€浠嬫煃閽樺顥滃ù婊勭矒閺屾盯鎮㈤崨濠勭▏闂佷紮绲介崲鑼弲濡炪倕绻愮€氼噣宕濋敃鈧—鍐Χ閸℃鐟愰梻鍌氬缁夌數绮嬪鍜佺叆闁割偆鍠撻崢鐢告⒑缂佹ê鐏﹂柨姘舵煟韫囧鍔滈柕鍥у缁犳盯鏁愰崟顖氫粣闂備礁鎼張顒傜矙閹捐鐒垫い鎺戯功缁夐潧霉濠婂啰鍩ｇ€规洘娲熷顕€宕奸悢鍝勫箺闂備胶鎳撻悘婵嬪疮椤愶絿顩查柟娈垮枓閸嬫挾鎲撮崟顒傤槬闂佺粯鐗曢崥瀣┍婵犲洤绠瑰ù锝堫潐濞呭棛绱撻崒娆撴闁搞劑缂氶崐鎾⒒閸屾艾鈧悂宕愰悜鑺ュ€块柨鏇楀亾妞ゎ亜鍟村畷绋课旈埀顒勫磼閵娾晜鐓熼柟鎯у暱椤斿倹绻涢幋鐑嗙劯闁哄啫鐗嗗婵囥亜韫囧海顦﹀ù婊堢畺閺屻劑寮撮悙娴嬪亾閹间焦鐓ラ柕鍫濇缁诲棝鏌曢崼婵嗩伀妞わ讣闄勭换娑㈠醇閻旇櫣鐤勫┑顔硷工椤嘲鐣烽幒鎴僵闁告鍎愰弶鍝ョ磽閸屾瑧顦︽い鎴濇瀹曞綊宕稿Δ浣规珳闂佺粯鍔曞Ο濠囧触鐎ｎ亶鐔嗛悹杞拌閸庡矂鏌熼柨瀣仢婵﹨娅ｉ幉鎾礋椤愩垹笑濠电姵顔栭崰鎾诲磹濠靛棭鍤曟い鎰堕檮閻掕偐鈧箍鍎卞Λ娑㈠储闁秵鈷戦梻鍫熶緱閻掗箖鏌涙惔銏犫枙鐎规洘妞介弫鎰板川椤忓懏鏉搁梻浣瑰缁嬫垹鈧凹鍙冨鎶筋敆閸屾浜鹃悷娆忓缁€鍫ユ煕閻樺磭澧甸柕鍡曠閳藉顫滈崱妯哄厞濠碘剝褰冮張顒勬偋閺囥垹鏋佸ù鐘差儐閳锋帡鏌涚仦鍓ф噯闁稿繐鐬奸惀顏堫敇閻愰潧鐓熼悗瑙勬礃缁矂鍩為幋鐘亾閿濆簶鍋撻銊х暤闁哄矉缍侀獮鍥敆婢跺﹥顔嶉梻浣虹帛缁诲倿鎮ユ總绋胯摕闁跨喓濮撮悙濠囨煏婢跺牆鍔ゅù鐘荤畺濮婃椽骞庨懞銉︽殸闁汇埄鍨辩敮鈥筹耿娓氣偓濮婃椽骞愭惔锝囩暤濠电偛鐪伴崝鎴︾嵁濡ゅ懎纾奸柣鎰嚟閸橀亶姊洪棃娑氬婵☆偅鐩獮濠囧川椤栨粎锛滈柡澶婄墑閸斿瞼绮缁辨帗娼忛妸銉х懆闁句紮缍侀弻褑绠涘☉鎺戜壕婵炴垶鐟ユ禍婵嬫⒒閸屾艾鈧兘鎳楅崼鏇炵疇闁规儳澧庢稉宥団偓骞垮劚椤︻垶宕归崒鐐寸參婵☆垯璀﹀Σ娲煛閸☆厾鐣甸柡宀嬬秮楠炴ê鐣烽崶褍鎽甸梻浣姐€€閸嬫挸霉閻樺樊鍎愰柣鎾存礃閵囧嫰骞囬埡浣插亾閺囥垹鍑犻柟瀵稿亼娴滄粓鏌￠崘锝呬壕濠电偠灏欓崰搴綖韫囨洜纾兼俊顖濆亹閹虫繈姊洪柅鐐茶嫰婢ь喗銇勯鐐寸┛妞わ附鎸抽弻鐔肩嵁閸喚浼堥悗瑙勬礀閵堝憡淇婇悜钘壩ㄧ憸婵堟椤曗偓濮婄粯鎷呴崨濠冨創濠电偛鐪伴崝鎴濈暦閹达附鍊烽柣銏犵仛閿涘繐顪冮妶鍡欏⒈闁稿鍋ら崺娑㈠箳濡や胶鍘遍柣蹇曞仜婢т粙骞婇崱娑欑厱闊洦鎸鹃悘閬嶆煟閵夘喕閭い銏★耿閹瑩妫冨☉姘箺闂佽姘﹂～澶娒哄Ο鐓庡灊鐎光偓閸曨偆鍘撮梺鐟邦嚟婵參宕戦幘缁樻櫜閹肩补鈧尙鐩庡┑鐐差嚟婵參宕ｉ崘顭戞綎婵炲樊浜濋ˉ鍫熺箾閹寸偞鐨戦柣銈呭濮婅櫣绮欓崠鈩冩暰濠电偠灏欓崰搴ㄦ偩瀹勬壋鏋庨柟鐐綑娴滃湱绱撻崒娆戝妽妞ゎ厼娲畷銏ゅ箹娴ｇ懓鈧灚顨ラ悙鑼虎闁告梹鑹捐灃闁绘娅曢崐鎰版煟濞戝崬鏋涢摶鏍煕濞戝崬鏋ら柛妯绘崌濮婄粯鎷呴崫銉よ檸濡炪倖鍨甸幊姗€骞冨Ο灏栧亾濞戞鎴﹀矗韫囨挴鏀介柣妯诲絻閺嗙偤鏌曢崶銊х畺闁靛洤瀚版慨鈧柍鈺佸暟椤︾増绻濈喊妯峰亾瀹曞洤鐓熼悗瑙勬磸閸旀垿銆佸Δ鍛＜婵炴垶顭囬ˇ浼存⒒閸屾艾鈧悂宕愭搴ｇ焼濞撴埃鍋撶€规洏鍎抽埀顒婄秵娴滆泛銆掓繝姘厱鐟滃酣銆冮崨鏉戝瀭闁稿瞼鍋為埛鎴炪亜閹哄棗浜剧紓浣割槹閹告娊骞冮幐搴涘亝闁告劏鏅濋崢鍗烆渻閵堝棗濮х紒鎻掑⒔缁牓宕橀鐣屽幈闁诲函缍嗘禍鍫曞磿閺冨牊鐓涢悘鐐插⒔濞插瓨銇勯姀鈩冪闁轰焦鍔欏畷鍫曞煛閸愩劌绗撶紓鍌氬€搁崐鐑芥嚄閼稿灚鍙忛梻鍫熺〒閺嗗棛绱掔€ｎ偒鍎ユ繛鍏肩墬缁绘稑顔忛鑽ょ泿閻庣懓鎲＄换鍌炲煘閹达附鍋愰柟缁樺俯娴犻箖姊洪棃鈺傗偓銉╁礃閻愵剙鐦滈梻渚€娼ч悧鍡欐崲閹扮増鍎婃繝濠傜墛閻撴洟鏌曟繛鐐珒闁硅尙鍋撻〃銉╂倷閼碱剙鈪垫繝纰樺墲閻℃洟藝鏉堛劎绠剧€光偓婵犱胶鐩庨柤鎸庡姍閺屾盯濡烽幋婵嗘殶缂佸鍠氱槐鎾存媴闂堟稑顬堝銈庡幖閸㈡煡锝炶箛鎾佹椽顢旈崟顓у敹闂佺懓鍚嬮悾顏堝垂婵犳碍鏅繛鎴炴皑绾捐棄霉閿濆棗绲诲ù婊呭亾缁绘盯骞橀弶鎴犲姲闂佺顑嗛幑鍥蓟閻旂⒈鏁嶆慨姗嗗墯濞堝姊洪崷顓炲付缂傚秴锕ら悾鐑芥倻缁涘鏅ｉ梺缁樼懃閹虫劖鎯旀繝鍥ㄢ拻濞达絽鎲￠幆鍫熴亜閿旇鐏﹂柟顔ㄥ洤绀嬫い鏍ㄦ皑椤︻噣鏌ｈ箛鏇炰户闁绘搩鍋夐妵鎰板箳濠靛洦娅撻梻鍌欑劍椤戞瑩宕归悧鍫㈩洸濡わ絽鍟崑鈩冪箾閸℃绠版い蹇ｄ簽缁辨帒鐣濋崘鈺冦€婄紓浣介哺鐢偟妲愰幒鎳崇喖鎳栭埡鍐╂緰濠德板€楁慨鐑藉磻濞戙垹鐤い鎰剁畱閻撴繈骞栧ǎ顒€鈧鎮块埀顒勬⒑閹稿海绠撻柟鍐茬箰閳诲秵绻濋崘褏绠氶梺缁樺姦娴滄粓鍩€椤掍胶澧摶鐐裁归敐鍫綈闁告瑥绻橀弻鏇㈠醇濠垫劖鈻撻梺杞扮閿曨亪寮婚悢琛″亾閻㈡鐒惧ù鐘欏懐纾奸柍閿亾闁稿鎹囧缁樻媴閸︻厽鑿囬梺鎼炲姀濡嫰鈥﹂崶顏嶆Ъ缂備礁鍊圭敮鎺椻€﹂妸鈺侀唶闁绘柨鎼獮妤呮⒑閸︻厼鍔嬪┑鐐诧工閻ｅ嘲鈹戦崶銊ュ妳闂侀潧顭堥崕鎶剿囬锔解拺闁革富鍘奸崝瀣煕閵娿儳绉虹€殿喗濞婂畷鍗炩槈濞嗘垵骞堥梻浣告惈濞层垽宕濈仦鍓ь洸闁绘劗鍎ら悡鐔兼煏閸繃鍣洪柛銈呮处閹便劍绻濋崘鈹夸虎闂佽鍠楅悷鈺呭箰婵犲啫绶炲┑鐘插亞濞笺儵姊婚崒娆戭槮闁硅绻濋獮鎰嫚閼碱剚娈曢梺褰掓？缁€浣虹不閺嶎厽鐓熼柟閭﹀墻閸ょ喐銇勯埡鍐ㄥ幋闁诡喗顨婇弫鎰償閳ユ剚娼婚柣鐔哥矋濠㈡鈧碍婢橀～蹇撁洪鍕啇闂佺粯鍔栬ぐ鍐╂叏瀹€鍕拺闁告稑锕ラ悡銉︺亜閹存繃鎼愰柍璇查叄婵偓闁靛牆妫涢崝鍫曟倵楠炲灝鍔氭俊顐ｇ洴瀹曘垽宕ㄦ繝鍕啎闁哄鐗嗘晶浠嬪箖閸忕浜滄い鎾跺仧婢э妇鈧鍠楁繛濠囧极閹邦厼绶為悗锝庡墮楠炴劙姊虹拠鑼闁稿鍠栧畷鎴﹀箻閸撲胶鐒奸柣搴秵閸忔﹢宕戦幘鑸靛枂闁告洦鍓涢ˇ顓㈡⒑閸涘鐒奸柛銉戝懎骞嬮梻浣侯攰閹活亞绮婚幋锔藉€峰┑鐘插閸犳劙骞栭幖顓犲帥闁轰礁鍊块弻锝呂熼懡銈冨仦闂佽　鍋撳ù鐘差儐閻撶喐淇婇婵愬殭濠⒀屽灦閺屾盯鎮㈡搴ｎ啋闂佸搫鏈惄顖炲箖閳哄懎绠涘ù锝呮贡閺嗐儵姊虹紒妯诲蔼闁稿﹥绻堝濠氭晲婢跺﹥顥濆┑鐐叉閸嬫捇鎮块崶褉鏀介柣鎰絻閹垿鏌ｅΔ渚囨畼闁瑰箍鍨归埥澶婎潨閸℃娅婃俊鐐€栧Λ浣哥暦閻㈠憡鍎庨幖娣灮缁犲墽鐥幆褜鍎忓ù婊呮嚀閳规垿鎮欓埡浣峰闂傚倷绀侀幖顐﹀嫉椤掑嫭鍎庢い鏍ㄥ嚬閸ゆ洟鏌熺紒銏犳灍闁稿﹦鍏橀弻娑滅疀閹惧瓨鍠愭俊鐐额潐婵炲﹪寮婚敐鍡樺劅闁靛繆鎳囨慨鍥╃磽娴ｇ瓔鍤欓柣妤€妫濋敐鐐剁疀閺囩姷锛滃┑鈽嗗灥椤曆囶敁閹剧粯鈷戦柛娑橈功閳藉鏌ㄩ弴妯哄姦鐎规洘娲熼獮妯肩磼濡攱瀚奸梻浣藉吹閸犳劕顭垮鈧铏綇閳哄啰锛滅紓鍌欑劍閿氱紒妞﹀洦鐓曢柟鐑樻尭缁楁帡鏌嶇拠鏌ュ弰妤犵偞锚閻ｇ兘宕剁捄鐑樺€涢梻鍌氬€烽懗鍓佸垝椤栨繃鎳岄柣鐔哥矋濠㈡﹢宕幘顔肩畺闁圭绨洪崑鍛存煕閹般劍鏉归柟宄邦煼濮婅櫣绮欓幐搴㈡嫳闂佽崵鍟欓崨顖滃箵闂佸搫鍟犻崑鎾剁磼缂佹鈯曢柟宄版嚇瀹曟﹢宕ｆ径宀婃Ш闂備線鈧偛鑻晶鍓х磼閻樿櫕灏柣锝夋敱缁虹晫绮欑拠淇卞姂閺屾洘绔熼姘毙ら柛姘秺濮婅櫣鎷犻弻銉偓妤冪磼閻樿尙效鐎规洘娲熼弻鍡楃暤閵夈儲澶勯悗闈涖偢瀵爼骞嬮悪鍛覆缂傚倸鍊搁崐鐑芥倿閿旂偓绠掔紓鍌欐祰椤曆兾涘▎鎾澄﹂柛鏇ㄥ灠閸愨偓闂侀潧臎閸曨偅鐝┑锛勫亼閸婃牜鏁悙鍝勭獥闁哄稁鍘奸拑鐔哥箾閹存瑥鐏╅崶鎾⒑閸涘﹤濮傞柛鏂款樀瀹曟垿骞橀弬銉︽杸闂佺硶妾ч弲婊呯礊鎼粹檧鏀介柣鎰级閳绘洖霉濠婂嫮鐭嬮悗闈涖偢閹晝绱掑Ο鐓庡箞闂備礁鎼ú銊╁磻閻斿摜顩锋繛鎴欏灩閺嬩線鏌涢鐘插姕闁抽攱甯掗湁闁挎繂鐗滃鎰版煕鐎ｎ剙鈻堥柡灞剧洴瀵剟宕稿Δ鈧浼存倵濞堝灝娅橀柛瀣楠炲繘鎮╃紒妯烘濡炪倖甯婇悞锕傤敊閺囩喍绻嗛柣鎰典簻閳ь剚鐗滈弫顕€骞掗弬鍝勪壕婵鍘ф晶顖炴煕鎼搭喖浜版慨濠勭帛閹峰懐绮欓幐搴㈢槪闂備礁婀遍埛鍫ュ磻婵犲倻鏆﹂柟鎵閸嬨劎绱掔€ｎ厽纭舵い鏂挎閳规垿鎮欓崣澶嗘灆婵炲瓨绮嶇换鍫ュ春濞戙垹绠ｉ柣妯虹仛閿涘繐顪冮妶鍡樺暗闁稿鍋ゅ畷鎶芥偡閹冲﹦鎳撻…銊╁礃椤忓柊銊╂⒑閸濆嫭婀扮紒瀣崌閸┾偓妞ゆ帒锕︾粔鐢告煕鐎ｎ亝顥滈悡銈夋倵閻㈢數銆婇柛瀣尵閹叉挳宕熼鍌ゆО缂傚倷娴囬褔宕愰崸妤佹櫜闁绘劕妯婇悡銉╂煕椤愶絿绠橀柛鏃撶畱椤啴濡堕崱妤冪懆闁诲孩鍑归崜鐔煎箯閹达附鍋勯柛婵勫劤椤旀洟姊洪悷鎵憼闁荤喆鍎甸幃姗€鍩￠崒娆戠畾濡炪倖鍔х紞鍥嚀閸ф鐓涚€光偓閳ь剟宕伴幘璺哄灊婵炲棙鎸搁崹鍌涖亜閺囩偞鍣瑰┑锛勫厴閺岋絾鎯旈妶搴㈢秷濠电偛寮堕悧婊勭珶閺囥埄鏁囬柣妯诲墯濞肩喖姊虹憴鍕姢妞ゆ洦鍙冮幃鐤亹閹烘挾鍘遍梺闈涱槹閸ㄧ數鈧凹鍠涢妵鎰版嚑椤掑倻锛濋梺绋挎湰閼归箖鍩€椤掆偓閹芥粎鍒掗弬璺ㄦ殾闁搞儺鐓堥崑銊モ攽椤旂煫顏呮櫠鎼达紕鏆ゅ〒姘ｅ亾闁哄本鐩獮鍥煛娴ｈ倽銊╂⒑閸濆嫷鍎忛梺甯秮瀵鎮㈢悰鈥充壕婵炴垶顏伴幋锔藉亗闁靛鍎嶉悷閭︾叆闁割偁鍨婚弳顐⑩攽椤旂》宸ユい顓炲槻閻ｉ攱绺介崨濠備簻闁荤偞绋堥埀顒佸墯濞兼捇姊婚崒娆愮グ妞ゎ偄顦抽妵鎰板礃椤旇偐鐤呴梺璺ㄥ枔婵瓨顢婇梻浣告啞濞诧箓宕归幍顔惧暗鐎广儱顦伴悡鍐喐濠婂牆绀堟繛鍡樺灥瀵煡姊绘担铏瑰笡闁哄被鍔戦妴鍐╂償閳藉棛鍔烽梺鍝勭▉閸樹粙鎮￠敐澶屽彄闁搞儯鍔岄崵顒佺箾閸忕厧濮嶉柡灞剧洴閹晠宕ｆ径妯伙紗闂備礁鎼張顒勬儎椤栨凹鍤曢柟缁㈠枛鎯熼梺闈涱槶閸婃寮弽銊ょ箚闁绘劦浜滈埀顑懏瀚婚柣鏃傚帶缁€澶屸偓鍏夊亾闁告洦鍋嗛崢鎾⒑绾懏褰ч梻鍕瀹曟劙鎮滈懞銉у幈濠电偛妫楀ù姘ｉ崨濠勭闁告侗鍋勯埀顒佹礋閸╃偤骞嬮敂钘夆偓鐑芥偣妤︽寧顏犳慨锝冨灲濮婃椽宕妷銉愩垽姊虹敮顔剧М妤犵偛鍟妶锝夊礃閳轰讲鍋撴繝姘參婵☆垯璀﹀Σ鐑樸亜閺傛寧鍤囨慨濠冩そ瀹曟姊荤壕瀣劵闂備胶顭堥柊锝嗙閸洖鏄ラ柍褜鍓氶妵鍕箳閸℃ぞ澹曟俊鐐€ら崢楣冨礂濡警鍤曞┑鐘宠壘鍥存繝銏ｆ硾閿曪箓鎮鹃幎鑺モ拺闁革富鍘奸崝瀣煕閵娿儳浠涢柟渚垮姂婵偓闁靛牆妫岄幏?")
        elif teaching_observations:
            if localized_observation:
                parts.append("")
            else:
                parts.append("婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁诡垎鍐ｆ寖缂備緡鍣崹鎶藉箲閵忕姭妲堥柕蹇曞Х椤撳搫鈹戦悙鍙夘棞缂佺粯甯″畷婵嬪箻椤旇В鎷洪柡澶屽仦婢瑰棝藝閿斿浜滈柟瀛樼箖椤ャ垹鈹戦敍鍕毈鐎规洜鍠栭、娑橆潩妲屾牕鏅梻浣藉吹婵儳鈻嶉敐澶婄？闁靛牆顦伴崐闈浳旈敐鍛殲闁抽攱鍨块弻娑樷槈濮楀牆濮涢梺鐟板暱閸熸壆妲愰幒鏃傜＜婵鐗愰埀顒佸椤ㄣ儵鎮欓幓鎺撴闁剧粯鐗犻弻娑樷槈閸楃偞鐏堟繛瀵稿У濡炶棄顫忛崫鍕懷囧炊瑜忔导鍕⒑缁嬫鍎滅紓宥勭窔瀹曟椽鍩€椤掍降浜滈柟鍝勬娴滈箖姊洪幐搴㈠濞存粠浜滈锝囨嫚濞村顫嶅┑顔斤公缁茶姤绂嶆ィ鍐╃叆婵犻潧妫濋妤€霉濠婂嫮绠為柟顔筋焾缁犳盯鏁愰崨顓犵潉闂備礁鎼懟顖滅矓瑜版帒绠板┑鐘插暙缁剁偞淇婇婊冨姦闁哄鎳忔穱濠囧Χ閸ヮ灝銉╂煕鐎ｎ剙浠ч柡渚囧櫍閺佹捇鎮╅棃娑氥偊婵犵妲呴崹浼存儍閻戣棄纾婚柟鍓х帛閸嬨劍绻涢崼锝嗙《闁告柨鎽滅槐鎾存媴閽樺澶勭紓渚囧枟閻熴儵锝炶箛鏃傜瘈婵﹩鍓涢敍婊冣攽閻愬弶顥為柛銊ョ秺閹即濮€閻橆偅鏂€闂佺粯鍔栧妯间焊閸愵喗鐓曢煫鍥ㄦ礀娴滃墽绱掔€ｎ偄鐏撮柛鈹垮灪閹棃濡搁妷褜鍚呴梻浣虹帛閸旀洟鎮洪妸鈺婃晩闁搞儺鍓氶埛鎺懨归敐鍫澬撶痪顓炵埣閺屾盯鎮╅搹顐㈤瀺闂侀€涚┒閸斿酣鍩€椤掑嫭娑ч柟鑺ョ矋缁嬪顓兼径瀣幗濠碘槅鍨靛▍锝夋晬瀹ュ洨纾奸柍閿亾闁稿鎸搁埞鎴︽偐閸偅姣勬繝娈垮枟閹稿啿鐣烽幇顔剧＜婵☆垳绮悵鐑芥⒑閸濆嫭鍌ㄩ柛銊︽そ閹繝寮撮姀锛勫帾婵犵數鍋涢悘婵嬪礉濮樿埖鐓冪憸婊堝礈濞嗘垹绀婂┑鐘插暕缁诲棝鏌ｉ姀銏╃劸缂佲偓鐎ｎ偁浜滈柡宥冨妽閻ㄦ垿鏌ｉ妶鍌氫壕闂傚倸鍊风欢姘焽瑜旈垾锕傚醇閵夈儳锛熼梻渚囧墮缁夋挳鎮￠弴鐑嗙唵闁兼悂娼ф慨鍫ユ煃闁垮鐏撮柡灞剧☉閳规垿宕熼銏狀潛濠电偛顕慨鐢靛垝瀹ュ桅闁告洦鍨遍弲婵嬫煕鐏炲墽鈯曢梺娆惧幖椤啴濡舵惔鈥茬盎缂備胶绮敮鐐参ｉ幇鏉跨闁瑰啿纾崰鎾诲箯閻樺樊鍟呮い鏃傛嚀娴滈箖鏌熼崜褏甯涢柍閿嬪灩缁辨挻鎷呮慨鎴邯閹﹢鏁冮崒娑氬弳濠殿喗锕╅崢鍓х不妤ｅ啯鐓曟い鎰剁悼缁犳岸鎮楀鍗烆暭闁靛洤瀚伴、鏃堝礋椤愶絾顔掑┑鐘殿暯閳ь剙纾崺锝団偓瑙勬礀瀹曨剝鐏掓繛鎾村嚬閸ㄨ精鈪搁梻鍌氬€搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒傜暢缂傚倸鍊风欢锟犲窗濡ゅ懏鍋￠柍鍝勬噺閸嬫ɑ銇勯弴妤€浜鹃悗瑙勬礀閵堝憡淇婇悜钘壩ㄩ幖瀛樕戝▍濠囨煛鐏炵晫效鐎规洦鍋婂畷鐔碱敃閻旇渹澹曢梺鍛婄☉閿曪箓銆呴柨瀣鐎瑰壊鍠曠花濂告煃闁垮鐏撮柡灞剧☉閳藉顫滈崼婵嗩潬闂備礁鐤囧Λ鍕囬悽绋胯摕闁靛ň鏅涢崡铏繆椤栨縿鈧偓闁稿鎹囧浠嬵敃閵堝洨鍔归梻浣告贡閸庛倝骞愭ィ鍐┾挃闁告洦鍨遍悡鏇熺箾閹寸偐妲堥柛顐犲劚缁狀垳绱撴担璇＄劷缂佺娀绠栭弻鐔煎礈瑜滃Λ搴☆熆鐟欏媶鎴犳崲濞戞矮娌柛灞惧焹閸嬫捇寮介鐐垫煣闂佸壊鍋呭ú锕傚极婵犲洦鐓曢柟鐐殔閹锋垹妲愰幓鎺嗘斀闁绘﹩鍠栭悘杈ㄧ箾婢跺娲寸€殿喚鏁婚、妤呭礋椤愶綀绶㈡俊鐐€栫敮鎺楀磹閻㈢纾婚柟鎹愬煐閸犲棝鏌涢弴銊ュ妞わ负鍔戝娲箹閻愭彃顬堝┑鐐茬毞閳ь剚鍓氶崵鏇熴亜閹板墎鐣辩紒鐘崇洴閺屸剝寰勬繝鍕檸缂備焦鍔栫粙鎴︹€旈崘顔嘉ч柛鈩冾殔椤酣姊洪崫銉バ㈤悗娑掓櫇缁顓奸崱鎰簼闂佸憡鍔忛弲婵嬪储閻㈠憡鈷戠紓浣姑悘锕傛煥濮樿埖鐓熼柟鐑樻煥娴滃墽绱掔紒妯笺€掑ù婊勬倐瀵粙濡搁敂鎯х稻闂傚倷绶氬褍煤閵堝洠鍋撳顐㈠祮闁绘侗鍣ｉ獮鎺楀箣椤撶偞鍊梻浣规偠閸庢粓宕橀崜褉鍋撻幘顔解拻闁稿本鐟︾粊鐗堛亜閺囩喓澧电€规洘婢樿灃闁告侗鍠栨禒顓㈡⒑闂堟侗妲堕柛鏂垮缁傚秴鈻庨幘绮规嫽婵炶揪缍€濞咃絿鏁☉銏＄叆闁哄洦锚閻忊晜銇勯鐐寸┛妞わ箑纾槐鎺楀磼濞戞ɑ璇為梺杞扮閸婂綊骞堥妸鈺佺疀妞ゅ繐妫涘▔鍨攽閿涘嫬浜奸柛濠冪墵楠炴劖銈ｉ崘銊э紱闂佺粯鍔曞Ο濠囧疮閸涱喚绡€闂傚牊绋掗惌妤冪磼鐠囧弶顥㈤柡灞剧☉閳诲氦绠涢敐鍠帮附绻濆▓鍨灈缂佸鏁婚妴鍐Ψ閳哄倸鈧兘鏌℃径瀣仼闁荤喆鍔戦弻褏绱掑Ο鐓庘吂闂佸疇顫夐崹鍧楀箖閳哄懎绠甸柟鐑樻尰椤斿绻濋悽闈涗粶闁瑰啿绻橀獮鎴﹀炊瑜滃鏍磽娴ｈ偂鎴炲垔鐎靛摜纾奸悗锝庡亜椤曟粓鏌涙繝搴＄仯缂佽鲸鎸婚幏鍛槹鎼粹€愁瀴闂備礁婀遍…鍫ュ疮閸ф鏁嬮柨婵嗩槸缁犵敻鏌熼崫鍕棡闁哄倵鍋撻梻浣筋嚙閸戠晫绱為崱妯碱洸闁绘劖鐗抽崶顒夋晩缁炬媽椴哥€靛矂姊洪棃娑氬婵☆偅绋掗弲鍫曟焼瀹ュ棛鍘遍柣搴秵閸撴瑦绂掗柆宥嗙厱闁冲搫鍊诲ú瀛橆殽閻愬樊鍎旈柡浣稿€块幐濠冨緞婢跺﹤顕ч梻鍌氬€烽悞锕傚箖閸洖纾块柤濮愬€曠欢銈嗙箾瀹割喕绨荤痪鎯ь煼閺岀喖骞嗚閿涘秹鏌￠崱顓犵暤闁哄本鐩俊鐑筋敍濠婂懏娈搁梻浣侯攰濡嫰顢栭崨鏉戠厴闁硅揪闄勯崑鎰版煕椤垵浜濇慨锝呭濮婅櫣绮欏▎鎯у壉闂佺儵鏅╅崹鍫曠嵁閸℃稑鐐婇柕濞垮労閸ゃ倝姊洪崫鍕垫Ч闁搞劌缍婅棟妞ゆ洍鍋撴慨濠呮濞戠敻宕ㄩ鍏奸敪缂傚倷鑳舵慨鐢稿垂閸噮鍤曞ù鍏兼綑鍞梺鍐叉惈閸婂宕㈤幘缁樺仭婵犲﹤瀚惌鎺斺偓瑙勬礃缁矂锝炲┑鍫熷磯濞达絾娲╃粻鎾诲蓟濞戙垹鍗抽柕濞垮劤娴犫晝绱撴担鍝勑ｅ┑鐐诧躬瀵鎮㈤悡搴ｎ啇濡炪倖鎸鹃崑鐔哥閳哄倻绡€婵炲牆鐏濋弸鐔兼煟閳哄﹤鐏犳い顐㈢箰鐓ゆい蹇撳缁愭稒绻濋悽闈浶㈤柛濠傤煼閹兘骞撻幒鍡樻杸闂佺粯锕╅崰鏍倶椤忓牊鐓ラ柡鍥悘鏌ユ煕閵娾晝鐣洪柡浣稿暣瀹曟帒鈽夊Ο鑽ゆ殸濠碉紕鍋戦崐鏍偋椤撶姴绶ら柛娆嶅劤閺勫倸鈹戦悩鍨毄濠殿喚鍏樺顐﹀箹娴ｅ摜锛涢梺缁樺姇閹碱偆绮绘导瀛樼厵閻犲搫鎼ˉ鐐差熆閼搁潧濮囩紒鐘差煼閹綊宕堕鍕濡炪倧瀵岄崑濠傤潖濞差亜鎹舵い鎾跺仜婵″搫顪冮妶鍐ㄥ闁硅櫕锕㈠鑽も偓锝庡枛閻愬﹥銇勯幒宥堝厡闁告ü绮欏娲传閸曨偅娈梺缁橆殕缁矁鐏嬮梺鐟邦嚟婵澹曟總鍛婄厵闂侇叏绠戦弸娑樏归悪鍛洭缂佽鲸甯炵槐鎺懳熼懖鈺冩澖闂備浇顕栭崰鏇犲垝濞嗗精娑㈠礃閵娿垺顫嶅┑掳鍊撶粈浣瑰垔娴煎瓨鈷掑ù锝呮贡濠€浠嬫煕閳轰礁顏€规洝顫夊蹇涘煛閸屾稒顔囬梻浣虹帛閸旀洟鎮樺璁圭稏闁哄洢鍨洪悡鐔兼煙闁箑澧婚柛銈囧枔缁辨帡鍩﹂埀顒勫磻閹剧粯鈷掑ù锝堫潐閸嬬娀鏌涙惔銏㈢煉鐎规洜鍠栭、妯衡槈濡懓顥氭俊鐐€栫敮鎺斺偓姘煎弮閸╂盯骞嬮敂鐣屽幈闂佹寧妫侀褔鐛弽銊ｄ簻闁挎繂鎳庨幃鎴犵磼缂佹绠炲┑顔瑰亾闂佸疇妫勯幊鎾诲焵椤掆偓濞硷繝寮婚悢纰辨晩闁伙絽鏈崳顓犵磽娴ｈ櫣甯涚紒璇茬墕閻ｅ嘲顫滈埀顒勫极閸屾粍宕夐柕濞у嫭娅掑┑鐘殿暜缁辨洟宕戦幋锕€纾归柡宥庡亝閺嗘粓鏌熼悜姗嗘闁搞儺鍓﹂弫宥嗘叏濮楀牏绋婚柣搴℃惈閳规垿鎮欓崣澶樻！闂佹悶鍔屽﹢杈ㄧ珶閺囩喓闄勭紒瀣硶妤犲洭姊洪崜鎻掍簼缂佸鍨舵穱濠囨偩瀹€鈧壕濂告煃瑜滈崜鐔风暦婵傚憡鍋勯柛鎾茶兌閻ｉ箖姊绘担鍛婂暈闁荤喆鍎佃棟妞ゆ牗绋掗崣蹇曗偓骞垮劚濡厼鈻撴禒瀣厽闁归偊鍘界紞鎴犵磼濡や礁娴柟钘夌埣瀵粙顢橀悢鍝勫笚闁荤喐绮嶇划鎾崇暦濠婂啠妲堥柕蹇娾偓鍏呯病闂備浇顕栭崹搴ｄ沪閼恒儱鈧垰鈹戦悩顔肩伇婵炲鐩、鏍炊椤掆偓閸屻劑鏌熼崜褏甯涢柛瀣у墲缁绘繃绻濋崒姘间紑闂佹椿鍘界敮鐐哄焵椤掑喚娼愭繛鍙夘焽閸掓帡骞樼拠鑼暫闂侀潧绻堥崐鏍吹閸愵喗鐓冮弶鐐村閸忓矂鏌曢崼顒傜暤婵﹦绮幏鍛村川婵犲懐顢呭┑鐘媰閸曞灚鐣跺銈庡幖閻忔繆鐏掗梺鍏肩ゴ閺呮繈鎮炴總鍛娾拺闁告稑锕ゆ慨锕€霉濠婂嫮澧电€规洘鍨块獮妯肩磼濡桨鐢婚梻浣告惈椤︿即顢栧▎寰稑鐣濋崟顑芥嫼闂佸憡绺块崕杈ㄧ墡闂備胶绮〃鍡椕洪悢鐓庢槬闁靛繈鍊曠粻濠氭偣閸パ冩闁冲搫鎳忛悡蹇擃熆閼稿緱顏堝几閻斿吋鍊甸梻鍫熺〒閻掑憡鎱ㄦ繝鍐┿仢婵☆偄鍟埥澶婎潩椤掑姣囧┑鐘殿暯濡插懘宕戦崨瀛樺仭鐟滃海绮╅悢鐓庡嵆闁靛繆鈧厖缂撻梻浣告啞缁嬫垿鏁冮敃鍌氬偍闂侇剙绉甸悡鐔煎箹閹碱厼鐏ｇ紒澶屾暬閺屾稓鈧綆浜濋崳褰掓煟閿濆懎妲婚柣锝嗙箞瀹曠喖顢楅崒姘闂備浇顕х换鎺楀磻閻斿皷鈧箓宕奸悢鍛婄彿闂佸搫琚崕鏌ユ偂濞嗘垟鍋撻悷鏉款伀濠⒀勵殜瀹曟娊鎮惧畝鈧壕鍏笺亜閺冨倹娅曢柟鍐插閺岀喖顢涘☉娆樻濡ょ姷鍋為敃銏犵暦濡ゅ懎宸濇い鎾楀嫷妫ラ梻鍌氬€搁崐鐑芥嚄閸洩缍栭悗锝庡枛缁€瀣煕椤垵浜為柡鍡愬劤缁辨捇宕掑▎鎺戝帯婵犳鍣ｅ褔鈥﹂崹顕呮建闁逞屽墴瀹曟椽鎮欓崫鍕吅闂佹寧妫佸Λ鍕瑜版帗鈷戦柛锔诲幘鐢盯鎮介娑辨當闁崇粯鎹囧畷濂稿即閻斿弶瀚肩紓鍌氬€烽悞锕傗€﹂崶鈺冧笉闁瑰墽绮悡鐔兼煛瀹擃喕绀佹禒顕€鎮楀▓鍨灕妞ゆ泦鍥舵晣闁稿繒鍘х欢鐐测攽閻樻彃鏆欑紒浣藉煐娣囧﹪鎮欓鍕ㄥ亾閺嶎厼绠板Δ锝呭暙绾剧粯淇婇婵嗗惞闁绘繂鐖奸弻锟犲炊閳轰椒姹楅梺琛″亾濞寸姴顑嗛悡鐔兼煙闁箑澧紒鐙欏洦鐓曢柨婵嗘噽缁夋椽鏌″畝鈧崰鏍箹瑜版帩鏁冩い鎺戝暊閸嬫挾鎹勯妸銏犱壕婵炲牆鐏濋弸锔姐亜閺囧棗娴傞弫鍥煕韫囨洖甯剁紒鍓佸仱閹鏁愭惔婵堟晼濠碉紕铏庨崰鏍煘閹达附鍋愭い鏃囧亹娴煎洭姊虹化鏇熸珕闁绘鍋ら獮妤咁敃閿旇В鎷洪柣搴℃贡婵參宕靛▎鎾寸厽婵°倐鍋撴俊顐ｇ矒閹﹢宕橀瑙ｆ嫼缂傚倷鐒﹂敃顐︽嚀閹稿海绠惧ù锝呭暱鐎氼噣銆呴悜鑺ョ叆闁哄洨鍋涢埀顒€缍婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撲線顢旈崼鐔封偓鍫曟煛鐏炶鍔滈柣鎾跺枑缁绘盯骞嬪┑鍡氬煘濠电偛鎳庣粔鍫曞焵椤掑喚娼愭繛鍙夌墵閹儵宕楅梻瀵哥畾闂佸綊妫块悞锕傚疾濠靛鐓冪憸婊堝礈閻旂鈧線骞樼拠鑼啋闂佸憡鎸烽懗鍫曟晬濠靛洨绠鹃弶鍫濆⒔閸掓澘顭块悷甯含鐎规洘娲濈粻娑樷槈濞嗘垵骞楅梻濠庡亜濞诧箑顫忛懡銈囦笉闁绘劗鍎ょ€电娀鏌ｉ弬鍨倯闁稿﹦鏁婚弻銊モ攽閸℃侗鈧顭胯婢瑰棝鎯€椤忓牆鐭楅柕澹懐鍘梻浣告惈閺堫剛绮欓幘瀵割浄闁挎洖鍊哥粻鏌ユ煙闁箑澧绘俊顐ゅ枛濮婄粯绗熼埀顒勫焵椤掑倸浠滈柤娲诲灡閺呰埖瀵肩€涙鍘遍棅顐㈡处濡垿鎳撻幐搴闁绘劖褰冮弳锝夋煙椤旂晫鎳囬柟顔界矊铻ｇ紓浣诡焽瑜板洭姊婚崒娆戠獢闁逞屽墰閸嬫盯鎳熼娑欐珷闁圭虎鍠楅悡銉︾節闂堟稓澧曞ù鐘櫇缁辨帡鎮╁畷鍥ｆ闂佸疇妫勯ˇ顖炲煝鎼淬倗鐤€閹艰揪绲鹃弳浼存⒒閸屾艾鈧悂宕愭搴㈩偨闁跨喓濮撮惌妤呯叓閸ャ劍鐓ｇ紒璇叉閺屾盯濡烽鐓庮潻缂備讲鍋撳璺哄閸嬫捇鎮烽弶娆句痪婵犮垻鎳撻澶婎嚕閵婏妇顩烽悗锝庡亞閸樹粙姊鸿ぐ鎺戜喊闁告挻鐟ч惀顏囶槼闁靛洤瀚版俊鐤槻濞寸娀浜堕弻鈥崇暆閳ь剟宕伴幘璇茬獥濠电姴娲ょ涵鈧梺缁樺姈婢瑰棝寮弽顐ょ＝闁稿本鐟︾粊鏉棵瑰搴″⒋鐎规洘鍨挎俊鍫曞椽娴ｅ憡顓垮┑鐐差嚟婵挳顢栭幇鏉挎瀬闁搞儺鍓氶悡鐔兼煛閸屾稑顕滈柟顖氱墦閹粙顢涢悙鐢垫毇濠殿喖锕︾划顖滄崲濠靛洦鍎熼柍銉ㄥ皺閻╁孩绻濋悽闈涗粶闁活亙鍗冲畷鎰攽鐎ｃ劉鍋撴笟鈧浠嬵敇閻愯尙鐛╅梻浣告惈椤︿即宕硅ぐ鎺戠闁挎洍鍋撴い顏勫暣婵″爼宕卞Δ鍐啰闂備胶绮敮顏呬繆閸モ晛鍨濋柛顐犲劚閻掑灚銇勯幒鎴濐仾闁抽攱鍨垮鍫曟倷閺夋埈妫嗛柣鐘冲姃閸楁娊寮诲☉銏℃櫜闊洦娲栭崺灞筋渻閵堝骸浜滅紒缁樺笧濡叉劙骞掗幊宕囧枛閹虫牠鍩￠崒姘杽闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼顢欐慨鎰盎濡炪倖鎸鹃崑鐐电矚閹稿簺浜滈柨鏇楀亾缂傚秴锕獮鎰節閸屾鏂€闂佹悶鍎崕鎵姳婵犳碍鈷戦悷娆忓閸斻倗鈧娲﹂崜鐔煎箖濮椻偓閸╋繝宕橀鍜冪础闂備浇顕栭崹搴ㄥ礋椤愨剝妯婇梻鍌欑閹碱偊鎯夋總绋跨獥闁哄诞鍛濠电姴锕ょ€氼厽鍒婇幘顔界厽闁瑰鍊栭幋锕€鐤柟鐑橆殕閳锋帒霉閿濆牆袚闁靛棗鍟扮槐鎺楀焵椤掍胶鐟归柍褜鍓欓悾鐑藉箛閺夊潡鏁滃┑掳鍊愰崑鎾绘煢閸愵亜鏋涢柡灞炬礋瀹曠厧鈹戦崶鑸碉紒闂備礁鎲￠悷銉ф崲濮椻偓瀵鎮㈤崗鑲╁姺闂佹寧娲嶉崑鎾绘煕濡粯灏﹂柡灞剧〒閳ь剨缍嗛崑鍛焊椤撱垺鎳氶柡宥庡幗閻撴洟鏌熼幍顔芥毄闁告ɑ绋掓穱濠囶敃閿濆洨鐓佺紓浣虹帛缁嬫捇鍩€椤掑倹鏆╂い顓炵墕閻☆厽淇婇悙顏勨偓鏍垂闂堟党娑樷攽鐎ｎ亞鐣洪梺璺ㄥ枔婵挳宕￠幎鑺ョ厪闊洤艌閸嬫捇寮妷銉ゅ闂佸壊鍋呭ú姗€鎮￠悢鍏肩厵闂侇叏绠戦獮妤冪磽瀹ュ棗鐏╃紒杈ㄥ浮閸┾偓妞ゆ帒瀚粈鍐┿亜椤撶喎鐏╅柛鐐垫暬閺岋綁鎮㈤崫銉﹀櫑闁诲孩纰嶉幃鍌炲箠閹捐閿ゆ俊銈勮兌閸樻悂鏌ｈ箛鏇炰户闁哄拋鍋勯弳鈺備繆閻愵亙绱橀柛灞剧矌閻涖垽姊洪崫鍕拱闁烩晩鍨堕悰顔嘉熺亸鏍т壕闂傚牊绋掗崯鐐烘煕閹烘挾娲撮柟顔筋殔閳绘捇宕归鐣屽蒋闂備胶顭堥鍛涘┑瀣祦闊洦绋掗崑鎰偓鐟板閸犳牠寮查悩宸富闁靛牆妫欓悡銉╂煕濮橆剦鍎旀い銏★耿瀹曠螖娴ｅ弶瀚藉┑鐐舵彧缁蹭粙骞夐敍鍕闁挎稑瀚壕鍏笺亜閺囩偞鍣归柣蹇ョ秮閺屸剝绗熼崶褎鐝濋梺绯曟櫔缁绘繂鐣烽妸鈺婃晩闂傚倸顕弳妤呮⒒閸屾瑧绐旀繛浣冲泚鍥敃閿曗偓閻ょ偓绻濇繝鍌滃闁稿鍊块弻锟犲炊閳轰焦鐎繛瀛樼矋缁捇寮婚悢鐓庣骇闁割煈鍣弳銏ゆ⒑鐠団€虫灕闁稿鍔楀Σ鎰板箳濡や礁浜归梺鎯ф禋閸嬪嫮澹曢幎鑺モ拺闁告繂瀚悞璺ㄧ磼閺屻儳鐣烘鐐叉瀵噣宕奸锝嗘珦闂備胶绮幐绋棵归悜绛嬫晩闁规壆澧楅埛鎺懨归敐鍛喐闁哄鍟妵鍕敃閵忊晜鈻堥悗瑙勬礀缂嶅﹤鐣风粙娆炬富閻忓繑鐗曟禍鎯归敐鍥┿€婇柡瀣叄閺岀喖骞戦幇顓犲涧濡炪們鍎茬换鍫濐潖濞差亝顥堟繛鎴炶壘椤ｆ椽鏌ｆ惔銏犲毈闁哥姵顨呴…鍥ㄧ節濮橆剛鐫勯梺鍓插亞閸熷潡骞忕紒妯肩閺夊牆澧介崚浼存煙鐠囇呯瘈鐎规洦鍨堕幃娆撴倻濡厧寮抽梻浣告惈濞诧箓鏁嬮梺璇叉禋閸犳氨妲愰幒妤婃晩缁炬媽浜崥瀣倵濞堝灝鏋欑紒顔界懇閵嗕礁顫滈埀顒勫箖濞嗘垟鍋撳☉娆樼労婵鍩栭埛鎺戙€掑锝呬壕濠电偘鍖犻崨顔煎簥闂佸壊鍋侀崕杈╁瑜版帗鐓涢柛銉㈡櫅鍟搁柣蹇撶箳閺佹悂鍩€椤掆偓缁犲秹宕曢柆宓ュ洦瀵肩€涙ê浜楅梺鍝勬川閸犲棙绂嶅鍫熺厵闁逛絻娅曞▍鍛存煃瑜滈崜姘洪悢濂夊殨闁归棿绀佺猾宥夋煕椤愩倕鏋旈柛妯哄船閳规垿鍩ラ崱妤冧化缂備緡鍣崹浼存偩瀹勬壆鏆嗛柛鏇ㄥ墰閸橀潧顪冮妶鍡樷拻闁告鍏撅絿绱掑Ο闀愮盎濡炪倖鎸荤划灞炬叏閸屾壕鍋撶憴鍕闁哥姵鐗犻妴浣割潨閳ь剟骞冮埡鍛棃婵炴垶顭堢欢鐔兼⒒閸屾瑦绁版い鏇嗗喚娼╅柨鏇炲亰缂嶆牕顭跨捄琛″闁告繂瀚€閻斿吋鍋傞幖杈剧磿娴滀即鏌ｆ惔鈥冲辅闁稿鎹囬弻娑㈠即閻愬樊鏆㈢紓浣割儏缁绘劙鍩為幋锔藉亹缂備焦蓱闁款厼鈹戦悙棰濆殝濠碘€虫川濡叉劙鎮欓崫鍕€炲銈嗗笂閼冲爼宕㈤幘缁樷拺闁告稑锕︾粻鎾绘倵濮樼厧澧寸€殿喗濞婇幃銏ゅ礂閼测晛骞堟繝娈垮枟椤ㄥ懎螞濡ゅ懏鍊堕柣妯肩帛閻撳啴鎮峰▎蹇擃仼闁诲繑鎸抽弻鐔碱敊鐟欏嫭鐝氬銈冨灪閻熲晠骞婇弽顓炵厸闁逞屽墰濡叉劕顫滈埀顒€顫忕紒妯诲闁惧繐绠嶉埀顒€锕弻锟犲川椤斿墽鐓夐梺璇″暙閸ャ劌浜归梺鑲┾拡閸撴艾鈻撻幆褉鏀介柣妯肩帛濞懷勩亜閹存繃顥㈢€殿喗褰冮埞鎴犫偓锝庡亞閸橀亶鏌ｈ箛鏇炰粶濠⒀傜矙閵嗗倿寮婚妷锔惧幗闁瑰吋鎯岄崰鏍ㄦ櫠鐎涙ɑ鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噮闁圭懓瀚版俊姝岊槺缂佽鲸锕㈠缁樻媴娓氼垳鍔稿銈嗗灥濞差厼鐣烽幋锕€围濠㈣泛锕﹂悾娲⒑鐠恒劌鏋斿┑顔芥尦瀹曪繝骞庨懞銉у幗闂佸搫鍟ú锕傤敂閻樼偨浜滈柡鍐ｅ亾婵炶尙鍠庨～蹇撁洪鍛画闂佽顔栭崰妤呭箟閼测晝纾藉ù锝囩摂閸ゆ瑩鏌涙繝鍌涘仴妤犵偛锕ら…銊╁幢閹邦亝鐫忛梻浣告贡閸庛倝骞愭ィ鍐ㄥ偍濞寸姴顑嗛ˉ濠冦亜閹扳晛鐏璺哄閺岀喖宕ㄦ繝鍐ㄢ偓鎰版煙閾忣偆鐭庨柕鍥ㄥ姍楠炴帡骞欓崘鈹炬寘婵犵數濮伴崹濂稿春閺嶎厼绀夐柡宥庡幗閸嬪倿鏌￠崶銉ョ伄闁告瑦鎹囬弻娑㈠Ψ閿濆懎顬夐柣蹇撴禋閸欏啴寮婚悢纰辨晩闁芥ê顦辨禒鑲╃磽娴ｄ粙鍝洪悽顖ょ節瀹曟椽鍩€椤掍降浜滈柟鐑樺灥椤忊晠鏌ｉ幒鎴犱粵闁靛洤瀚伴獮鎺楀箣濠垫劒鐥梻浣瑰▕閺€閬嶅垂閸ф绠栨俊銈呮噹閹硅埖銇勯幘璺哄壉闁逞屽墮閺堫剛鎹㈠☉銏犵闁绘挸楠搁～鎺楁⒑閸濆嫭婀伴柣鈺婂灡娣囧﹪骞栨担鑲濄劎鎲稿澶嬪亗闁绘柨鍚嬮埛鎴犵磽娴ｅ鑲╂闁秵鐓曢柣妯诲墯濞堟﹢鏌熼獮鍨仼闁宠鍨归埀顒婄秵娴滅偤宕愰悙鐑樷拺闂傚牊涓瑰☉銏犵闁靛ě鍛緰濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻鐔虹磼閵忕姵鐏堥梺姹囧€ら崳锝夊蓟閿濆憘鏃堝焵椤掑嫭鍋嬪┑鐘插€甸弸宥夋煟濡厧浠哄ù婊勭矒閻擃偊宕堕妸锕€闉嶉梺闈╃到閸㈡煡婀佸┑鐘诧工鐎氼噣鎯岀€ｎ喗鐓忛柛銉戝喚浼冨Δ鐘靛仜濞差厼鐣峰鍕闁荤喖顣︽潻妯肩磽閸屾艾鈧兘鎳楅懜鍨弿闁绘垼妫勭壕缁樼箾閹存瑥鐏╅柣鎾达耿閺岀喐娼忛崜褏鏆犻梺缁樺笚濡炰粙寮诲☉銏犵疀闁靛闄勯悵鏃堟⒑闁偛鑻晶顖炴煕閺冣偓濞茬喖宕洪悙鍝勭闁挎棁濮ゅ▍鏍⒑閸涘﹥澶勯柛瀣閻涱喚鈧綆鍋嗙弧鈧┑鐐茬墕閻忔繈寮搁幘缁樼厱閻庯綆鍋呭畷灞炬叏婵犲啯銇濇鐐村姈閹棃鏁愰崒娑辨綌闂備浇顕х€涒晠宕欑憴鍕洸闁绘劗鍎ら崵宥夋⒑椤掆偓缁夊绮荤紒妯镐簻闁哄啫娉﹂幒妤€绠┑鐘崇閳锋垹绱掔€ｎ偄顕滄繝鈧导瀛樼厽闁绘梹娼欐慨鍌溾偓瑙勬礃椤ㄥ懘鎮惧┑瀣妞ゆ帒鍊搁獮宥夋⒒娴ｇ懓鍔ゆ繛瀛樺哺瀹曟垿宕ㄩ鐘虫闁诲繒鍋橀崟妯荤濠婂牊鐓忛煫鍥堥崑鎾诲礃閸欏鍤堝┑锛勫亼閸婃垿宕瑰ú顏呮櫇闁靛繈鍊曠粻鏍煏韫囧鐏柣顓熺懇閺屾盯鈥﹂幋婵囩亞缂備浇浜崰鏍ь潖婵犳艾纾兼繛鍡樺姉閵堟澘顪冮妶搴′簻妞わ箓娼ч悾鐑藉即閵忕姷顦ч梺绋跨箳閸樠冾嚕閸ф鈷戦梻鍫熺〒婢ф洘銇勯敂璇茬仯濠㈣娲濋妵鎰板箳閹捐泛骞堟俊鐐€ら崢浠嬪垂閻㈢鍑犻柟鍓х帛閻撴盯鏌嶈閸撴氨绮嬮幒鏂哄亾閿濆骸浜為柛妯挎閳规垿鍩ラ崱妤冧哗闂佸湱鈷堥崑鍡涙儉椤忓浂妲鹃梺閫炲苯澧伴柟铏崌楠炲鏁嶉崟顒€搴婇梺鍓插亖閸庨亶鎷戦悢鍝ョ闁瑰鍊戝璺哄嚑閹兼番鍔嶉悡娆撴⒑椤撱劎鐣辨鐐寸墱閻ヮ亪鎮欓鈧埢鏇熸叏婵犲啯銇濈€规洦鍋婂畷鐔碱敆娴ｇ懓顏伴梻鍌欒兌閸庣敻寮查埡鍛瀭閺夊牄鍔庨埞宥呪攽閻樺弶澶勯柛濠呭吹缁辨帒鈽夊鍡楀壉闂佸搫鎳夐弲鐘差潖閾忚瀚氶柍銉ョ－閳ь剙顭烽弻娑㈠箛閳轰礁顬嬮梺鑲╊焾缂嶅﹤顫忔繝姘＜婵﹩鍏橀崑鎾绘倻閼恒儱鈧潡鏌ㄩ弴鐐测偓鍝ョ不閺嶎厽鐓曟い鎰剁稻缁€鈧紒鐐礃椤绌辨繝鍥ч柛娑卞枛濞咃絿绱撴担鐟板妞ゃ劌锕悰顕€寮介‖銉ラ叄椤㈡鍩€椤掍椒绻嗛柣鎴ｅГ閻撳啰鎲稿鍫濈闁靛缂氱换鍡涙煕閵夘喖澧紒鐘崇叀閺屾盯寮撮妸銉т哗闁诡垳鍠栧娲箰鎼淬垻锛曢梺绋款儐閹搁箖鎯€椤忓棛纾奸柕蹇曞Х娴狀厾绱撴担铏瑰笡闁烩晩鍨堕悰顔碱潨閳ь剙顕ｉ崼鏇炵婵犻潧娲ㄥΣ妤呮⒒閸屾瑧鍔嶉柟顔肩埣瀹曟繄鈧綆鍠栫涵鈧梺鍛婂姌鐏忔瑩寮抽敂鐣岀瘈濠电姴鍊绘晶鏇犵磼閻欌偓閸ｏ綁寮婚妶澶婄畳闁圭儤鍨垫慨澶愭⒑瑜版帗鏁辨俊鐐扮矙楠炲啫螖閸愨晛鏋傞梺鍛婃处閸撴盯藝閵夈儮鏀介柣鎰皺濠€鎾煕閺傚潡鍙勭€殿噮鍋婇、娆戜焊閺嶎煈娼旈梻渚€娼ф蹇曟閺囥垹鍌ㄩ柟闂寸劍閻撶喖鐓崶銊︾濞寸姭鏅滈妵鍕即閸℃顏柛娆忕箻閺屾稓浠﹂幆褏鍔伴梺琛″亾濞寸姴顑嗛悡鍐煃鏉炴壆顦﹂柡鍡欏仱閹绠涢妷鈺傤€嶅銈冨妸閸庣敻骞冨▎鎾崇骇闁瑰鍋犻惂浣逛繆閵堝洤啸闁稿鐩、鏍ㄥ緞閹扳斁鍋撴担鍓叉建闁逞屽墴楠炲啴濮€閻樺灚娈濋梺鍝勵槸閻忔繈鏌屽鍐ｆ斀闁绘ɑ顔栭弳婊呯磼鏉堛劍绀嬬€规洘鍨块獮瀣晝閳ь剛澹曡ぐ鎺撶厸鐎广儱楠告禍婵嬫煛閸℃鐭掗柡宀€鍠栭幃婊冾潨閸℃鏆﹂梻浣告惈閹冲繒鎹㈤崼銉ヨ摕闁哄洢鍨归柋鍥ㄧ節闂堟稒绁╂俊顐節濮婃椽宕ㄦ繝鍕櫑缂備胶绮崹褰掑箲閵忕姭妲堥柕蹇曞Х椤撴椽姊虹紒妯哄妞ゆ洦鍘奸埢鎾诲Χ閸モ晝锛滈梺缁樺姦閸撴瑧绮堥崘鈺€绻嗘い鎰╁灩椤忣厽绻濋埀顒佺瑹閳ь剙顫忓ú顏勭閹艰揪绲块悾闈涒攽閳藉棗浜濇い銊ョ墕椤曘儲绻濋崟顒€鐝伴柣鐔舵閼冲爼骞婇幘鐑┾偓锕傚Ω閳轰礁绐涘銈嗘尰缁诲倿藟濮樿京纾介柛灞剧懆閸忓瞼绱掗鍛仯闁瑰箍鍨藉畷濂告偄缁嬪灝浼庨梻渚€鈧偛鑻晶鎾煛鐏炶濡奸柍瑙勫灴瀹曞崬螣閻戞﹩浠遍梻鍌欑閹诧繝鏁冮埡鍛；濠电姴鍋嗗鏍ㄧ箾瀹割喕绨荤€瑰憡绻傞埞鎴︽偐閹绘帗娈滈梺鐟板槻缂嶅﹤顫忛搹鍦＜婵妫欓悾鍏肩節閻㈤潧浜归柛瀣尭铻栭柣姗€娼ф禒婊堟煕閻斿憡灏︾€规洝顫夐妶锝夊礃閵婏富妫熼梻渚€娼ч¨鈧┑鈥虫喘閸┾偓妞ゆ巻鍋撴い顓炲槻椤繘鎼圭憴鍕瀭闂佸憡娲﹂崑鍕叏閵忕媭娓婚柕鍫濇婢跺嫰鏌涘▎蹇撴殭闁伙絿鍏樻慨鈧柕鍫濇－濡啫鈹戦悙鏉戠伇濡炴潙鎽滈埀顒勬涧閻倸顫忓ú顏咁棃婵炴垶鑹鹃。鍝勨攽閳藉棗浜濋柣鐔濆嫮顩查柟闂寸劍閸嬨劑鏌涘☉姗堝姛闁告﹢浜跺铏圭磼濡浚浜滈锝夊醇閺囩偟顔夐梺鎸庣箓濞层劎澹曢崗绗轰簻闁哄洨鍋為崳鍦偓娈垮櫘閸犳銆冮妷鈺傚€烽柡澶嬪灦鐠囩偛螖閻橀潧浠滄い鎴濐槸椤曪綁顢氶埀顒勫春閳ь剚銇勯幒鎴濐仼婵☆偅锕㈤弻宥堫檨闁告挻纰嶇粚杈ㄧ節閸ャ劌鈧攱銇勮箛鎾愁仱闁稿鎹囧鍊燁檨婵炲吋鐗曢埞鎴︽偐鐎圭姴顥濈紓浣哄Х婵炩偓闁哄瞼鍠栭獮鍡氼檨闁搞倗鍠愰妵鍕煛閸屾粌寮ㄩ梺鍝勬湰閻╊垶鐛Ο浣曟棃鍩€椤掑嫬绠犻柟鎵閺咁剚绻濋棃娑卞剱闁抽攱鍨圭槐鎺斺偓锝庡亜椤曟粍绻濋埀顒佸鐎涙鍘鹃悷婊呭鐢偤鎮惧ú顏呯厱闁宠鍎虫禍鐐繆閻愵亜鈧牜鏁幒妤€纾归柟闂寸閸屻劑鏌熺紒銏犳灍闁绘挻鐟╅弻褑绠涢敐鍛埅濠电偛鐗婄划搴ㄥ焵椤掑喚娼愭繛鍙夘焽閸掓帒顓兼径濠勵唵闂佸憡渚楅崹鎶芥儗濞嗘挻鍋ｉ柟顓熷笒婵℃椽鏌涢悩璇у伐闁宠鍨块弫宥夊礋椤愨剝婢€闂備胶顭堥敃銉╂偋閻樿绠栫憸宥夆€﹂妸鈺侀唶婵犻潧鐗炵槐閬嶆⒒娴ｈ櫣甯涢柛鏃€娲熼獮鏍敃閿旇棄浠鹃梺缁樺姦閸撴稓寮ч埀顒勬⒒閸屾氨澧涘〒姘殜瀹曟洟骞囬悧鍫㈠幗闂佽鍎崇壕顓犵不婵犳碍鐓熼柟鍨暙娴滄壆鈧娲橀崕濂嘎ㄦ笟鈧弻娑欐償閿涘嫮顔掗梺鍝勮嫰缁夌兘篓娓氣偓閺屾盯骞樼壕瀣棟闁绘挶鍊濋弻锝夊籍閸屾艾浠樼紓浣哄閸ㄥ爼寮婚悢鍛婄秶濡わ絽鍟宥夋⒑缁嬫鍎忛悗姘嵆瀵鈽夊鍛澑濠殿喗锕╅崗娑樞уΔ鍛拺闁告稑鈯曢鍕殾妞ゆ帒瀚悡姗€鏌熸潏楣冩闁稿﹦鍏橀弻鈩冨緞鐎ｎ亞浠兼繛瀵稿Х椤牓鈥旈崘顔嘉ч幖绮光偓宕囶啇婵犵數鍋涘Ο濠囧矗閸愵喗鍋樻い鏂挎閺冨牆宸濇い鏃堟？濮规绱撻崒姘偓鐑芥倿閿曞倵鈧箓宕堕鈧崒銊╂⒑椤掆偓缁夌敻鎮￠悢鐓庣闁圭⒈鍘奸悘锝囩磼婢舵劖娑ч棁澶嬬節婵犲倸顏柣顓熷笚閵囧嫰濮€閳╁喚妫冨銈冨灪濞茬喖寮崒鐐村仼閻忕偠妫勭粭姘舵⒑閼姐倕鏋戠紒顔肩Ф閸掓帡骞樺畷鍥ㄦ濠电姴锕ら崯鐘参ｉ崼銉︾厪闊洦娲栧暩闂佹眹鍊曞ú顓烆潖閾忚鍠嗛柛鏇ㄥ亜婵垽姊虹拠鑼闁绘鎸搁悾鐑藉箣閿曗偓缁犲鏌熸０浣哄妽闁稿秹娼ч—鍐Χ閸℃顫囬梺鎼炲妼濠€杈╁垝婵犲浂鏁嬮柍褜鍓熼獮鍐ㄎ旈崘鈺佹瀭闂佸憡娲﹂崜娑⑺囬妸鈺傗拺闁硅偐鍋涙俊鐓庮熆瑜嶉柊锝夌嵁閹达箑顫呴柣姗嗗亝閺傗偓闂佽鍑界紞鍡樼閻愬搫纾归柣鎰劋閸嬧剝绻濇繝鍌氼仼闁诲繐顕埀顒冾潐濞叉ê顪冩禒瀣畺婵炲棙鎸婚崐缁樹繆椤栫偞鏁遍悗姘冲亹缁辨捇宕掑顑藉亾閻戣姤鍊块柨鏇炲€归弲顏堟⒒娴ｇ瓔鍤欏Δ鐘茬箻濮婁粙宕熼姣硷箓鏌涢弴銊ョ伇闁轰礁娲弻锝夊箛椤撶喓绋囩紓浣瑰姈缁嬫挾妲愰幘瀵哥懝闁搞儜鍕壕缂傚倷绶￠崳顕€宕归懜鍏哥箚闁割偅娲橀弲鎻掝熆鐠虹尨鍔熸い锔哄姂濮婃椽宕橀崣澶嬪創闂佸摜鍣ラ崑濠囨偘椤曗偓楠炲洭顢栭懞銉︽澑闂備胶绮敃鈺呭窗閺嶎厽鍊堕弶鍫涘妿缁犳儳顭跨捄渚剳婵炴彃鐡ㄩ妵鍕閿涘嫬鈷岄悗瑙勬磸閸斿酣鍩€椤掍胶鈯曢柨姘舵煃瑜滈崜娆撴偉婵傜钃熼柡鍥╁枎缁剁偤鏌涢埄鍏╂垿鎮甸弴銏♀拺缂備焦蓱鐏忎即鏌ｉ悤鍌滅暤濠碉紕鏁诲畷鐔碱敍濮樿京娼夐梻浣规偠閸庢椽鎮￠崼婢盯宕熼娑掓嫼闁荤姴娲╃亸娆戠不濮樿埖鐓涢柛娑卞灠閳诲牏鈧鍠栭…鐑藉极閹邦厼绶炲┑鐑嗘娇閸斿秹濡甸崟顖氭婵炲棗澧介崥瀣⒑缁嬫鍎愭い銊ワ躬楠炲啫螖閳ь剟鍩㈤幘璇插瀭妞ゆ梻鏅禍顏勨攽閻橆偅濯伴柛鎰靛枛瀵澘螖閻橀潧浠﹂柛銊ョ仢閻ｇ兘鎮㈢喊杈ㄦ櫖濠殿噯绲介惃鐑藉疾閻樿钃熼柣鏃傚帶缁犮儵鏌ц箛锝呬簼闁绘繃妫冨铏规嫚閼碱剛顔戦柣蹇撶箲閻熲晠宕洪埀顒併亜閹烘垵鏋ゆ繛鍏煎姈缁绘稑霉鐎ｎ偅鐝栭梺鐟扮畭閸ㄥ綊鍩為幋鐘亾閿濆簼娴烽柟鑺ユ礋濮婅櫣鍖栭弴鐐测拤濡炪們鍔岀换妯虹暦閵壯€鍋撻敐搴℃灍闁绘挻娲熼弻宥夊煛娴ｅ憡娈堕梺鐟板暱閸燁垶銆冮妷鈺傚€烽柤纰卞劮瑜庨幈銊︾節閸愨斂浠㈤悗瑙勬处閸嬪﹤鐣烽悢鐓庡瀭妞ゆ劕绋勭粻鎾愁潖閾忓湱纾兼慨妤€妫欓悾璺衡攽閳藉棗浜濋柣鐔叉櫅椤曪綁寮婚妷锕€娈濋梺姹囧灪椤旀牕霉閸曨垱鐓熼幖鎼灣缁夌敻鏌涚€ｎ亜顏紒鍌涘笚缁轰粙宕ㄦ繛鐐濠电偞鎸婚懝鎯洪妶鍡樻珷妞ゆ柨澧界壕鐓庮熆鐠虹儤婀伴柡鍡╁墴閺岀喖顢氶崱娆戠槇閻庢鍠楅幐鎶藉箖閵忋倖鎯為悹鍥ｂ偓铏珬闂傚倸鍊烽懗鍓佹兜閸洖绀堟繝闈涱儍閳ь剙鍟换婵嬪炊閵娿儰绮ф繝鐢靛Т閿曘倝鎮ф繝鍥佸绻濋崘锔跨盎闂佸湱鍎ら崺鍫澪ｇ粙娆剧唵鐟滃酣骞愰幎钘夎摕闁挎稑瀚▽顏嗙磼椤栨稒绀€濞存粌澧介埀顒冾潐濞叉牕煤閿曗偓閳绘捇寮撮姀锛勫幗闁瑰吋鎯岄崹宕囩矓閻㈠憡鐓曢柟鎯ь嚟椤ジ鏌嶉鍫熸锭闁宠鍨堕獮濠囨煕婵犲喚娈曢柟渚垮姂閹粓鎸婃径宀嬬幢婵犵數鍋為崹鍫曞煟閵堝悿娲敂瀹ュ棙娅嶉梻浣虹帛閸旀洜绮旈悽鍛婂剮妞ゆ牗姘ㄩ弳锔芥叏濡炶浜炬繝纰樺墲閹倹鎱ㄩ埀顒勬煃閽樺顥炵紓宥呰嫰閳规垿鎮╅幇浣告櫛闂佸摜濮甸〃濠囧Υ閸愵喖宸濇い鎾虫处缁嬫垿鍩㈡惔鈽嗗殫婵犻潧妫涚粔铏光偓瑙勬礀閻栧ジ宕洪敓鐘茬妞ゅ繐娴烽梻顖炴⒒閸屾瑨鍏屾い顓炵墦瀵敻顢楅崟顒€娈炴俊銈忕到閸燁偊鎮為崹顐犱簻闁圭儤鍨甸埀顒佹倐瀹曘垽骞橀鐣屽幍闂佹儳娴氶崑鎺戔枔濠婂應鍋撶憴鍕闁靛牏顭堥锝夊箻椤旇棄浜滅紓浣割儏閻忔繃鎱ㄩ崘顔解拻濞达絿鍎ら崵鈧梺鍛婅壘椤戝骞冩ィ鍐炬晜闁割偅绻勯ˇ顕€鎮楅崗澶婁壕闂佸憡娲﹂崑鍕倵椤撱垺鈷戠紒瀣濠€鏉款熆鐟欏嫭绀嬬€规洘鍨块獮姗€鎳滈棃娑欑€梻浣告啞濞诧箓宕滃☉鈶哄洭濡烽妷銏℃杸闂佺粯鍔欓·鍌炲吹鐎ｎ剛纾奸柣妯挎珪瀹曞矂鏌℃担鐟板闁诡喗鐟╁畷顐﹀礋椤愩垻銈梻鍌欑窔濞佳勵殽韫囨洘顫曢柡鍥ュ灩閸屻劑鏌ｉ姀鐘冲暈闁抽攱鍨圭槐鎾存媴婵埈浜幃姗€鏁冮崒娑樼彅闂備緡鍓欑粔鐢告偂閻斿吋鐓欓柟顖嗗苯娈跺┑鐐插级閹告娊寮婚敍鍕勃闁告挆浣插亾閹烘鐓冪憸婊堝礈閵娧呯闁糕剝绋戠壕濠氭煕濞戝崬骞橀柡鍡閳ь剙鍘滈崑鎾绘煕閺囥劌澧伴柛妯烘啞缁绘稒娼忛崜褎鍋ч梺纭呮珪閹稿骞堥妸鈺侀唶闁靛濡囬崢闈涱渻閵堝棛澧紒瀣浮钘熼柛顐犲劜閻撴洟鏌曟繛鐐珖闁伙絿鍎ら〃銉╂倷閸欏顦╅梺鐟板槻閹虫﹢寮婚崨顓涙婵炲棗绻戦弫顏呯節閻㈤潧啸闁轰礁鎲￠幈銊╂倻閽樺鐎梺褰掓？缁€浣哄缂佹绠鹃柟瀛樼懃閻掓椽鏌℃担鍓插剱闁靛洤瀚伴獮妯兼崉閻戞鈧箖姊洪崨濠勬噧缂佺粯锚椤繑绻濆顒勫敹闂佺粯鏌ㄦ晶搴ｆ崲娴ｇ硶鏀介柣鎰摠瀹曞嫭銇勯弴鍡楁处缁犳帡姊绘担铏瑰笡闁挎碍淇婇姘捐含鐎规洘娲濈粻娑樷槈濞嗘垵寮?")
        elif summary:
            parts.append(localized_summary or "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃闁硅櫕鎹囬垾鏃堝礃椤忎礁浜鹃柨婵嗙凹缁ㄥジ鏌熼惂鍝ョМ闁哄矉缍侀、姗€鎮欓幖顓燁棧闂備線娼уΛ娆戞暜閹烘缍栨繝闈涱儐閺呮煡鏌涘☉鍗炲妞ゃ儲鑹鹃埞鎴炲箠闁稿﹥顨嗛幈銊╂倻閽樺锛涢梺缁樺姉閸庛倝宕戠€ｎ喗鐓熸俊顖濆吹濠€浠嬫煃瑜滈崗娑氭濮橆剦鍤曢柟缁㈠枛椤懘鏌嶉埡浣告殲闁绘繃娲熷缁樻媴閽樺－鎾绘煥濮橆厹浜滈柨鏃囶嚙閺嬨倗绱掓潏銊︻棃鐎殿喗鎸虫慨鈧柍閿亾闁归绮换娑欐綇閸撗冨煂闂佺顕滅换婵嗙暦椤栫偞鍊烽柣鎴烆焽閸橀亶姊洪崫鍕殲闁规悂绠栭幃楣冩偨绾版ê浜鹃悷娆忓绾惧鏌涘Δ鈧崯鍧楊敋閿濆棛顩烽悗锝呯仛閺呮繈姊洪棃娑氱畾闁哄懏绮撹棢闁炽儲鏋奸弨浠嬫煟濡櫣浠涢柡鍡忔櫅閳规垿顢欓悙顒佹瘎闂佸摜濮撮敃銈夘敇閸忕厧绶為悗锝庝簷缁ㄥ灚绻濋悽闈涗粶婵☆偅鐟╅獮鎰節濮橆厼浜楀┑鐐叉閹稿宕戦埄鍐闁糕剝顨堢粻鐗堛亜韫囧﹥娅呴柍瑙勫灴椤㈡岸宕卞▎鎴炴闂備礁鎼張顒勬儎椤栨稐绻嗛柛顐ｆ礀楠炪垺绻涢崱妯哄婵炲懏顭囩槐鎾诲磼濞嗘劗銈版俊鐐存綑閹芥粓寮鈧弫鎾绘偐閼碱剛鏆俊鐐€曠换鎰偓姘€鍥у嚑閹兼番鍔庨崣鎾绘煕閵夛絽濡介柣鎾卞劜閵囧嫰鏁傜憴鍕彋濠殿喖锕ㄥ▍锝囨閹烘嚦鐔烘嫚閼碱剦鏆￠梻鍌欑閹芥粓宕伴幇鏉跨闁告劕妯婇崵鏇㈡偣閸ャ劎銈存俊鎻掔墛娣囧﹪顢涢悙瀛樻殸闂佸搫鍊甸崑鎾绘⒒閸屾瑨鍏岀痪顓炵埣瀹曟粌鈹戠€ｃ劉鍋撻崘顓犵杸闁哄啫鍋嗗ù鍕節闂堟稑鈧悂骞夐敓鐘茬厱闁硅揪闄勯埛鎴炪亜閹扳晛鈧洘绂掑鍫熺厾婵炶尪顕ч悘锟犳煛閸涱厾鍩ｆい銏＄洴閹瑧鈧數顭堥獮宥嗕繆閻愵亜鈧牕顫忔繝姘偍鐟滄棃宕洪埀顒併亜閹哄棗浜惧┑鐐点€嬬换婵嬪箖娴兼惌鏁嬮柍褜鍓欓悾宄邦潨閳ь剚淇婇崨濠冨劅闁挎繂鎳忛悘浣虹磽娴ｄ粙鍝洪悽顖涘笩閻忔帡姊洪崗鑲┿偞闁轰讲鏅犳俊鑸靛緞鐎Ｑ勫濠电偠鎻徊鍧椻€﹂崼銉ユ辈闂侇剙绉甸悡娆戠棯閺夊灝鑸瑰ù婊勫閳ь剝顫夊ú锕傚垂鏉堚斁鍋撴担鍐ㄤ汗闁逞屽墯缁嬫帟鎽┑鐐叉噺閻楁洟鍩為幋锔藉亹閻犲泧鍐х矗闂備胶顢婂▍鏇㈠礉濡や胶鐝堕柡鍥╁枔椤╃兘鎮楅敐搴′簽闁告﹢浜堕弻锝堢疀閺囩偘绮舵繝鈷€鍌滅煓妤犵偛锕畷銊р偓娑欘焽閸橀亶姊洪崫鍕偓钘夆枖閺囩喓澧￠梻鍌欑窔濞佳兠洪妶鍥ｅ亾濮橆偄宓嗛柕鍡曠椤粓鍩€椤掑嫬绠栨繛鍡樻尭缁狙囨煙閹碱厼骞楃悮鈺呮⒒閸屾艾鈧绮堟笟鈧獮鏍敃閿曗偓缁犵娀骞栧ǎ顒€濡介柛瀣槸閳规垿宕掑搴ｅ姼缂備胶濮甸悧鐘诲蓟閿濆鏅查柛娑欐緲椤忣參姊洪崫鍕靛剰闁绘锕ョ粚杈ㄧ節閸ヨ埖鏅┑鐘绘涧濞层垽鍩€椤掆偓閸燁偊鈥︾捄銊﹀枂闁告洦鍓涢ˇ銉╂⒑鐎圭媭娼愰柛銊ユ健楠炲啫鈻庨幘鏉戞濡炪倖宸婚崑鎾淬亜閿濆棙銇濇慨濠呮閹风娀鎳犻鍌ゅ敼缂傚倷娴囬褔鎮ч崱娑辨晪闁挎繂娲ㄩ惌娆撳箹鐎涙ɑ灏版い顐㈢Ч濮婃椽妫冨☉銏㈠椽缂備浇椴稿ú鐔风暦閵忥紕顩烽悗锝庡亐閹锋椽姊洪崨濠勭畵閻庢凹鍣ｉ崺銏″緞閹邦厾鍘遍柣搴秵娴滄粓顢旈锔界厸濞撴艾娲ゅ▍宥夋煙閾忣偆鐭掗柟顔界懇閺屽懎鈽夊杈ㄦ櫒婵犵绱曢崑鎴﹀磹閺嵮屽晠濠电姵鑹剧壕濠氭煙閸撗呭笡闁绘挶鍎甸弻锟犲炊椤浜畷婵嗩潩椤撴粈绨诲銈嗘尵閸嬬偟绮氱捄銊х＜闁绘ê纾埥澶愭煃閽樺妲搁摶锝嗙節瑜忛崑鎾斥枍婵犲洦鐓涢悘鐐额嚙婵″ジ鏌嶇憴鍕伌鐎规洖宕灃濠电姳鑳剁壕濠氭⒒閸屾瑨鍏岄柛搴ｆ暬瀵彃鈽夐姀锛勫帎闂佹寧绻傞幏瀣焽閺嶎偆纾藉ù锝堝亗閹寸偛鍨旈柟缁㈠枟閻撴洘绻涢幋鐑囧叕闁衡偓婵犳碍鐓曢幖娣灪瀹曞本鎱ㄦ繝鍛仩缂侇喗鐟╁畷鐘诲焺閸愨晜姣庨梻鍌欐祰椤曟牠宕伴弽顓炵９闁秆勵殘瀹撲線鏌涢幇鈺佸闁绘梻鍎ら崑姗€鏌嶉埡浣告殲闁哄鎮傚铏规嫚閹绘帒姣愮紓浣藉紦缁瑩骞冨Ο渚僵閻犻缚娅ｉ弻褍鈹戦悩璇у伐闁哥姵鑹鹃妴鎺撶節濮橆厾鍘梺鍓插亝缁诲啴藟濠婂啠鏀芥い鏃傚帶閳ь剙娼″璇测槈濞嗘垹鐦堥梺鍛婂姉閸嬫捇鎮鹃崗鑲╃瘈闁靛骏缍嗗鎰箾閸欏鐒界紓鍌涙崌閹儳鐣濋埀顒勬儗濞嗘挻鍋ｉ柟顓熷笒婵倿鏌ｅ☉娆愬磳婵﹦绮幏鍛矙濞嗙偓顥戦梻浣侯焾椤戝懘骞婇幇顔煎灊婵炲棙鎸哥粻锝夋煟閹邦厼顥嬬紒鐘冲哺濮婅櫣绮欑捄銊ь啈闂佺顑嗛崝妤冨垝缂佹ǜ鍋呴柛鎰ㄦ櫇閸樼數绱掗悙顒佺凡鐎规洦鍓熼悰顕€寮介鐔哄幐闁诲函绲婚崝宀勫焵椤掍胶绠炵€殿喛顕ч濂稿醇椤愶綆鈧洭姊绘担鍛婂暈闁规瓕宕甸幑銏ゅ醇閵夛附娅滈梺缁樺姈濞兼瑧娆㈤悙娴嬫斀闁绘劖娼欑粭鎺楁煙绾板崬浜伴柨婵堝仜椤劑宕煎┑鍫濆Е婵＄偑鍊栫敮鎺斺偓姘煎墴瀵憡绗熼埀顒勫蓟濞戙垹绠涢梻鍫熺⊕閻忓牆顪冮妶搴′簻闁硅櫕锕㈠濠氬即閵忕娀鍞跺┑鐘绘涧濡瑥鈻撳鍫熲拺缂佸顑欓崕鎰版煙濮濆苯鍚圭紒顕呭弮閹垽鎮℃惔锝呭Е婵＄偑鍊栧濠氬磻閹炬番浜滈柡鍥朵簽缁夘喗銇勯姀鈥冲摵闁糕斁鍋撳銈嗗坊閸嬫捇鏌ｉ敐鍥у幋闁诡喒鍓濋幆鏂课熺紒妯绘緫闂傚倷绀佹竟濠囧磻閹烘纾婚柛娑卞枟濞呭繑绻濋悽闈浶ユい锝庡枤濡叉劙寮撮姀鐘碉紱闂佺鎻粻鎴犲瑜版帗鐓涚€广儱楠告禍婵嬫煛閸℃鐭掗柡宀€鍠栭幃婊冾潨閸℃鏆ョ紓浣哄亾閸庡啿锕㈤柆宥呯疅闁归棿鐒﹂崑瀣煕椤愶絿绠橀柣鐔哥叀濮婅櫣绮欓崠鈥充紣闂佽绻戝畝鍛婁繆閻㈢绀嬫い鏍ㄨ壘瀹撳棗鈹戞幊閸婃劙宕戦幘瓒佺懓顭ㄩ崟顐㈠Б闂佸疇顫夐崹鍧椼€佸▎鎴炲厹鐎瑰嫭婢橀～鐘电磽閸屾瑧璐伴柛锝庡櫍瀹曞綊宕奸弴鐘茬ウ闂婎偄娲︾粙鎴濐啅濠靛鍊垫繛鎴烆仾椤忓牊鍎岄柛鏇ㄥ墰缁♀偓闂侀潧楠忕徊鍓ф兜妤ｅ啯鐓ラ柡鍥崝锔锯偓瑙勬礃濞茬喖銆侀弮鍫濈闁靛闄勯弶鎼佹⒒娴ｈ櫣甯涢拑閬嶆煕閹炬潙鍝虹€规洦鍨电粻娑樷槈濞嗘垵骞堥梻浣虹帛钃遍柛鎾磋壘閳绘捇寮埀顒勫Φ閸曨垼鏁囬柣鎰摠閹瑩姊虹€圭媭鍤欓梺甯秮閻涱喚鈧綆浜栭弨浠嬫煕閳╁啰鎳勯柣鎿勭秮濮婂宕掑顑藉亾閹间礁纾瑰瀣椤愯姤鎱ㄥ鍡楀⒒闁绘帞鏅幉鎼佸籍閸繄鐣洪悷婊勬煥閻ｇ兘宕￠悘璇茬秺瀵爼骞愭惔鈽嗘П闂佽閰ｅ褔濡剁粙娆惧殨闁割偅娲栫粻锝夋煟濞嗗繑鍣芥鐐灲濮婂宕掑▎鎴犵崲濠电偘鍖犻崶銊ヤ罕闂佺硶鍓濋摂瀣炊閵娿儺鍤ら柣搴㈢⊕閿氬ù婊勵殜濡懘顢曢姀鈥愁槱闂佺懓鎲￠幐鍐差嚕閵婏妇顩烽悗锝庡亞閸樹粙姊鸿ぐ鎺戜喊闁搞劋鍗抽幆鍐传閸旇棄缍婇幃鈺咁敊閼测晙绱欓梻浣告惈閺堫剟鎯勯鐐靛祦婵せ鍋撴鐐叉处閹峰懘宕崟顒€鈧垶姊婚崒娆戭槮闁圭⒈鍋嗛幃顕€顢曢敃鈧粈澶屸偓鍏夊亾闁告洦鍋嗛崢鎾⒑绾懏褰х紒鐘冲灴閻涱噣濮€閵堝棛鍘撻梺鍛婄箓鐎氼剟鍩€椤掍礁濮嶉柡浣稿€垮畷婊嗩槾闁挎稒绻冪换娑欐綇閸撗冨煂闂佸湱鈷堥崑濠囥€侀幘璇茬闁告挷鑳堕敍婵嬫倵楠炲灝鍔氶悗姘煎枤缁綁寮崒妤€浜炬繛鍫濈仢閺嬫稒銇勯銏℃暠濞ｅ洤锕獮鏍ㄦ媴閸濄儱骞愬┑鐐舵彧缂嶁偓婵炲拑绲介…鍥ㄥ緞閹邦厸鎷绘繛杈剧秬椤宕戦悩缁樼厱閹兼番鍨洪妵婵嬫煙椤旂煫顏堝煘閹寸姭鍋撻敐搴濈敖妞ゆ梹甯￠弻锝嗘償閵婏附閿梺纭呭Г缁捇銆佸▎鎾冲嵆闁靛繆妾ч幏娲⒑閸涘﹦鈽夐柨鏇悼濞嗐垽鏌嗗鍡欏幈闂佺粯锚绾绢參銆傞弻銉︾厸闁告侗鍘鹃崺锝夋煙椤旇崵鐭欑€规洏鍔嶇换婵嬪礋椤愩垻顔囬梻浣筋嚙妤犳悂宕㈠鍫濈；闁瑰墽绮崐鐢告煥濠靛棝顎楀褎澹嗛幃顕€鏁愰崶鈺冿紳闂佺鏈悷銊╁礂鐏炶В鏀芥い鏃傚亾閺嗩剟鏌熼姘伃妞ゃ垺绋戦～婵嬫偂鎼淬埄鍚欓梻鍌欑濠€閬嶆惞鎼淬劌绐楁俊銈呮噹绾惧綊鏌ｉ幋锝呅撻柣鎾寸☉椤法鎹勬笟顖氬壈濡炪倖娲樼划鎾诲蓟閻旇桨娌柛灞炬皑娴犲ジ姊虹€圭媭娼愰柛銊ユ健楠炲啴鍩℃担鍙夌亖闂佸湱顭堢€涒晠鎯佸鍕瘈缁剧増锚婢ц尙鎲搁弶鍨殻妤犵偛锕よ灒闁惧繗顫夊▓楣冩⒑绾懏褰х紒鐘冲灩缁牏鈧綆鍋佹禍婊堟煙閹屽殶闁宠棄顦湁婵犲﹤鎳庢禍楣冩煙娓氬灝濡奸摶锝夋煟閹炬娊顎楀ù鐘成戠换婵嬪煕閳ь剟宕熼鈧崬澶愭⒑閸濆嫭婀伴柣鈺婂灦瀹曟椽鎮欓崫鍕€銈嗘⒒閸樠囷綖濮樿埖鐓熼幖杈剧磿娴犳稒绻濋姀鈽嗙劷闁逞屽墯閸戝綊宕ｉ崘顔惧祦闁糕剝绋戠猾宥夋煕椤愵偄浜濋柡鍛櫊閺岋綁鎮㈤崫銉﹀殏缂備焦鐓＄粻鏍箖濡ゅ懎绠瑰ù锝呭帨閹峰姊虹粙鎸庢拱闁煎綊绠栭崺鈧い鎺嗗亾闁搞垺鐓″﹢渚€姊洪幖鐐插姶闁告搫绠撳顐も偓锝庡枟閻撴稓鈧箍鍎辨鎼佺嵁閺嶎偆纾奸柟閭﹀弾濞堟洟鏌熸笟鍨閾伙綁鏌熺粙鎸庢崳闁靛棙鍔楃槐鎾存媴閹绘帊澹曢梻浣侯焾閺堫剛绮欓幇顔藉床闁糕剝菧娴滄粓鏌″鍐ㄥ闁瑰啿妫欓妵鍕箳閺傛寧鐏堥梺鍝勬湰閻╊垱淇婇崼鏇炲耿婵☆垳鈷堝Σ褰掓⒒娴ｅ憡鎯堝璺烘喘瀹曟粌鈹戦崱鈺佹闂佸憡娲﹂崢鎼佸磻閹剧粯鏅查幖瀛樼箘閺佹牠姊洪崨濠冣拻妞ゎ厼鐗撻崺鐐哄箣閿旇棄鈧兘鏌ょ喊鍗炲闁谎傜窔濮婃椽宕崟顒€娅ょ紓浣割儐閸ㄧ敻鎮鹃悽绋跨妞ゆ牗绋撻崢浠嬫椤愩垺澶勬繛鍙夌墬缁傛帒顭ㄩ崘鍓у數閻熸粍鍨堕幈銊╁Χ婢跺﹦鏌ч梺鍓插亝濞诧箓寮崱娑欑厱閻忕偛澧介埥澶娒归悩鑼婵﹥妞介獮鎰償閵忋埄妲梻浣侯焾閿曘倗绱炴繝鍥ф槬婵炴垯鍨圭粻锝夋煥閺冨洦顥夊ù鐙€鍨跺娲箹閻愭彃濮岄梺鍛婃煥閻厧顕ユ繝鍕＜婵☆垶鏅茬花濠氭⒑閻熺増鎯堟い鎴濇嚇閹﹢顢旈崼鐔哄帾闂佹悶鍎滈崘鍙ョ磾闁诲孩顔栭崳顕€宕抽敐澶婃槬闁逞屽墯閵囧嫰骞掗幋婵愪痪闂佺顑呴澶愬蓟閿濆憘鐔煎垂椤旂偓顕楅梻浣告惈濡绮婚幘璇茶摕闁斥晛鍟欢鐐测攽閻樻彃顏柣銊﹀灥閳规垿鍩勯崘銊хシ闂佺粯顨呴敃锕傚箲閵忕姭妲堥柕蹇曞Т閼板灝鈹戦埥鍡楃仩闁圭⒈鍋婇敐鐐茬暆閸曨剙鈧灚绻涢崼婵堜虎闁哄绋掔换娑氫焊閺嶃倕浜鹃柟棰佺劍缂嶅骸鈹戦悙鍙夆枙濞存粍绻堣棢闁割偆鍠撶粻楣冩煙鐎电浠╁瑙勆戦妵鍕晲閸涱喗鍎撳銈庝簻閸熷瓨淇婇幆鎵杸闁哄洨濮烽悰銉╂⒒娴ｅ憡鍟炴い銊ユ嚇瀹曨垶宕稿Δ濠冩櫔闂佹寧绻傞ˇ顖炴嫅閻斿吋鐓忓鑸得弸鐔兼煛閸涱偄鐏叉慨濠冩そ瀹曘劍绻濋崘顭戞П闂備礁鎲￠幐濠氭儎椤栨氨鏆﹂柕蹇嬪€栭悞鑲┾偓骞垮劚濡矂骞忓ú顏呪拻濞撴艾娲ゆ禍婵堢磼鐎ｎ偄鐏ラ柣锝囨暬瀹曞崬螣閼测晩鍟庡┑鐐舵彧缁蹭粙宕崹顔氭椽濡舵径濠勵槱闂佺粯锚绾绢厾绮绘ィ鍐╃厵閻庢稒顭囬幊鍐煟韫囷絼閭柡灞界Ч閺屻劎鈧綆浜炴导宀勬⒑閸濆嫭婀扮紒瀣灱閻忓啴姊洪崨濠傚闁告柨顑呴埢浠嬵敂閸涱垳鐦堥梺闈涢獜缁插墽娑垫ィ鍐╁€垫慨妯煎帶閺嬨倖淇婇崣澶婂妤犵偞甯″顕€宕掑鎰簥濠电姷顣藉Σ鍛村垂閻㈢纾婚柟鎵閸嬵亪鏌涢弴銊ヤ簮闁衡偓娴犲鐓冮柦妯侯槹椤ユ粌霉濠婂嫮鐭掗柡灞剧洴閹倖鎷呴梹鎰瀳闂備胶纭堕弬鍌炲磿閹绘帩鍤楅柛鏇ㄥ墰缁犻箖鏌ｉ幇闈涘闁逞屽墮椤嘲螞閸涙惌鏁冮柕蹇娾偓鎰佹П婵犵數鍋涘鍓佸垝瀹€鍕仼闁绘垼妫勬导鐘绘煕閺囨ê濡介柡鍌楀亾闂傚倷鐒︾€笛呯矙閹寸姭鍋撳鐓庡缂佸倸绉电缓浠嬪川婵犲嫬骞堝┑鐘垫暩閸婎垶宕橀埡浣诡仭闂佽瀛╅懝楣冣€﹂悜钘夎摕闁挎繂顦猾宥夋煕鐏炴崘澹樺ù鐘愁焽缁辨帡鎮欓鈧崝銈嗙箾绾绡€鐎殿喖顭烽弫鎰緞婵犲孩缍傞梻渚€娼х换鍡涘疾濠靛绀夐柟闂寸劍閳锋垿鏌﹀Ο渚Ц闁哄棛鍠栭弻娑㈡偐瀹曞洤鈷岄悗娈垮枛椤攱淇婇幖浣肝ㄩ柕蹇婂墲閺夋悂姊绘担铏广€婃俊鐙欏洤鐤炬繝濠傚濞呭繘姊婚崒姘偓鐑芥嚄閸洍鈧箓宕奸妷顔芥櫈闂佺硶鍓濈粙鎴犵矆婢跺绠鹃柛鈩冾殕缁傚鏌涢妶鍡樼闁哄本鐩、鏇㈡晲閸℃瑯妲梻鍌欑瀹曨剙煤閿曞倸桅闁告洦鍨扮粻娑㈡煕椤垵浜炵紒鎰濮婃椽鎮℃惔鈽嗘婵炲瓨绮犳禍婊堬綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕导鏉戠煑闁糕剝绋掗埛鎴犵棯椤撶偞鍣洪柣婵愪邯閺屻劌顫濋婊€绨诲銈嗗姂閸ㄨ崵绮绘导瀛樺亗闁靛牆妫庢禍婊堢叓閸ャ劍灏い蹇ｅ亝閵囧嫰寮埀顒勫礉濞嗗浚娼栭柧蹇撴贡绾惧吋淇婇姘儓妞ゎ偄绉归幃宄邦煥閸曨剛鍑￠梺鍝ュ枑閹告娊宕规ィ鍐ㄥ唨妞ゆ挾鍋涢懓鍨攽閻愭潙鐏﹂柣鐔村灲楠炲繐煤椤忓應鎷洪梺鍛婄☉閿曪箓鍩ユ径瀣ㄤ簻妞ゆ挆鍐潻闂佸磭绮幑鍥ь嚕椤曗偓瀹曟帒顭ㄩ崟鍓佺缂傚倸鍊搁崐鐑芥⒔瀹ュ鍨傞柣鐔煎亰閸ゆ洘銇勯弴妤€浜鹃梺鍝勭灱閸犳牠銆佸☉妯锋瀻闁瑰濮峰畷鍙変繆閻愵亜鈧垿宕瑰ú顏傗偓鍐╃節閸屾粍娈鹃梺缁樻⒒閳峰牓寮崟顖涚厾闁诡厽甯掗崝姘亜韫囨挾绉烘慨濠傤煼瀹曟帒鈻庨幋顓熜滈梻浣侯攰椤曟粎妲愰弴鐘插灊婵炲棙鎸哥粻锝夋煥閺冨洤袚婵炲懎娲娲濞戣鲸顎嗙紓浣哄У閸ㄧ懓鈻庨姀銈嗗€烽柣鎴烆焽閸橀亶姊洪崫鍕偍闁告柨鐭傞幃姗€鏁撻悩宕囧幗闂佽鍎抽悺銊х矆鐎ｎ喗鐓涢悘鐐靛亾缁€鍐磼缂佹娲撮柟顔界懇椤㈡鎷呴崫鍕シ闂傚倸鍊峰ù鍥綖婢跺簺浜归柛鎰ㄦ櫆濞呯姴霉閻樺樊鍎忛柣鎺戠仛閵囧嫰骞掗幋婵囩亾濠电偛鍚嬮崝鏍崲濞戙垹鐭楀瑙勭箥娴滅偤宕ｉ崨瀛樷拺闁告繂瀚埢澶愭煕閹惧鈯曠紒鍌氱Т閳诲氦绠涙繝鍐╂澑闂備胶绮崝姗€宕洪弽顑句汗鐟滃繒妲愰幒妤冨彄妞ゆ挾濮烽悡鎾绘倵鐟欏嫭纾搁柛搴ｆ暬瀹曟椽鍩€椤掍降浜滈柟鐑樺灥閳ь剝宕垫竟鏇熺附閸涘﹦鍘繝鐢靛仜閻忔繈宕濋幘顔界厽闁规儳鍟块幃鎴︽煙娓氬灝濡界紒缁樼箞瀹曘劑顢氶崨顒€鎽嬮梻鍌欒兌閹虫挸顕ｉ崼鏇炵闁告劘灏欓弳锕傛煟閺冨倵鎷￠柡浣稿暣閺屾洝绠涢弴鐑嗘綑闂佺鎻梽鍕偂閻旂厧绠规繛锝庡墮閳ь兙鍊曢…鍥箛椤撶姷顔曢柣鐘叉厂閸涱垱娈奸柣搴ゎ潐濞叉鍒掑畝鍕剁稏婵犻潧顑愰弫鍥煟濮楀棗浜濋柡渚€娼ч埞鎴︽偐閸偅姣勬繝娈垮枛椤曨參鍩€椤掍礁鍤柛妯恒偢閹箖鏌ㄧ€ｎ亞绐為梺褰掑亰閸橀箖宕㈤鍛瘈闁汇垽娼ч埀顒夊灦瀹曟﹢鍩℃担鍝勭到缂傚倸鍊峰ù鍥ㄣ仈閹间焦鍋傞柍銉﹀墯濞兼牜绱撴担璇＄劷闁荤喎缍婇弻宥堫檨闁告挾鍠栧畷娲焵椤掍降浜滈柟鐑樺灥閳ь剙鎲＄粋鎺戭煥閸喓鍘惧┑鐐跺蔼椤曆囨倶閿熺姵鐓涢柛娑卞幘閸╋絾銇勯姀锛勨槈闁崇懓鍟撮獮鍡氼槺濠㈣娲熷娲礈閼碱剙甯ラ梺绋款儏閹虫劕鈻庨姀銈呰摕闁靛绠戦埀顒€鐏氶幈銊ノ熼悡搴′粯濡ょ姷鍋為敃銏ゅ蓟閻旇偐宓侀柛顭戝枤娴犲ジ姊虹€圭姵顥夋い锕€鐏氶幈銊╁焵椤掑嫭鐓熸俊顖涙た閸熷繘鏌涢悙瀛樸仢婵﹦绮幏鍛存倻濡儤鐣俊鐐€栧ú锕傚储娴犲绠為柕濞炬櫆閻撱儵鎮楅敐鍛粵妞ゆ柨瀚板濠氬磼濮橆兘鍋撻幖浣哥９鐎瑰嫭鍣磋ぐ鎺戠倞鐟滄粌霉閺嶎厽鐓忓┑鐐靛亾濞呭棝鏌涙繝鍌涘仴闁哄被鍔戝鎾倷濞村浜鹃柛婵勫劤閻棗顭跨捄渚剳缂佺娀绠栭弻娑㈠焺閸愮偓鐣肩紓浣哄У婵炲﹪寮婚敓鐘插耿妞ゆ挾濮烽弳銈夋⒑閸濆嫭婀伴柣鈺婂灦閵嗕線寮撮姀鈩冩珳闂佺硶鍓濋悷杈╂閳哄懏鈷掑〒姘ｅ亾闁逞屽墰閸嬫盯鎳熼娑欐珷妞ゆ牜鍋為悡鐔镐繆閵堝懎鏆欓柍璇茬墦閺屾洟宕遍弴鐙€妲梺瀹狀嚙闁帮綁鐛鈧畷妤呭川椤栨粌鈧偤姊婚崒娆戭槮闁规祴鈧秮娲晝閸屾氨锛涢梺鍛婃处閸ㄧ晫绱為弽銊﹀弿婵☆垰銇橀崥顐ょ棯閸欍儳鐭欓柡灞剧〒娴狅箓宕滆閸ｎ垶姊虹粙璺ㄧ闁活剝鍋愬Σ鎰板箳濡ゅ﹥鏅梺鍛婁緱閸樼偓绂掗幖浣光拺閻犲洠鈧磭浠╅柣搴㈢煯閸楁娊濡存担绯曟婵妫欓崓鐢告煛婢跺﹦澧戦柛鏂跨Ч椤㈡瑩寮撮悙鈺傛杸闂佺粯顭囩划顖氣槈瑜旈弻娑欑節閸愨晛鈧劖顨ラ悙宸█闁轰焦鎹囬幃鈺呮嚑椤掑﹦骞㈤梻鍌欑閹测€趁洪敃鍌氱；闁圭儤鍨埀顒佸笚缁绘繂顫濋鐐╁亾閻㈠憡鐓ユ繝闈涙閸戝湱绱掗妸銈囩煓闁哄本鐩獮瀣攽閸ヮ亞顢呯紓鍌欐祰妞村摜鏁Δ鈧…鍥疀濞戞鈺冩喐韫囨稒鍋╅柣鎴烆焽缁犻箖鏌ㄥ┑鍡樺櫤闁瑰吋鍔欓弻銊╁即閵娿倗鍑规繛锝呮搐閿曨亜鐣锋總绋垮嵆闁绘劙娼ч埀顒傚仜椤啴濡舵惔鈥斥拻闂佸摜濮甸幑鍥х暦閺囥垺鍋ㄧ紒瀣劵閹芥洖鈹戦悙鏉戠仸闁糕晛鍟村畷鎴﹀箻缂佹ɑ娅滈柟鑲╄ˉ閳ь剚鍓氬璇测攽閻愬樊鍤熷┑顔肩Ч瀹曞爼濡歌楠炴劕鈹戦悙瀛樺鞍闁艰鍎崇叅闁靛牆鎳夐弸宥団偓骞垮劚椤︿即鎮￠弴銏＄厓閺夌偞澹嗛ˇ锔姐亜韫囷絽骞橀柍褜鍓濋～澶娒哄鈧垾锕傚醇閵夊娲ㄩ埀顒勬涧閹芥粎澹曟總鍛婄厽婵☆垰鎼弳閬嶆煕濠靛牆鍔嬮柟渚垮妽缁绘繈宕堕埡鍐崶闂備線娼уú锕傚礉濞嗘挾宓侀柟鐑橆殔缁犲ジ鏌涢弴銊ュ箹闁诡垳鍋熺槐鎾诲磼濮橆兘鍋撴搴㈠闁哄被鍎辩壕濠氭煙閹规劗袦鐟滅増甯楅弲鏌ユ煕閵夛絽濡兼繛鍫濈焸濮婃椽宕ㄦ繝鍐ｆ嫻濠碘槅鍋勯崯顐︼綖韫囨拋娲敂閸涱厽顓奸梻渚€娼ч悧鍡涘箠韫囨稒鍊甸柛鎾楀懐锛濇繛鎾磋壘濞层倝寮稿☉銏＄厽妞ゆ巻鍋撻柕鍫熸倐閻涱噣骞嬮敃鈧～鍛存煟濞嗗苯浜惧┑鐐殿儠閸旀垿寮诲鍫闂佸憡鎸鹃崰鎰┍婵犲嫧鍋撳☉娅虫垶鍒婄€靛摜纾兼い鏍ㄧ⊕缁€鍐煟鎼粹槅鐓兼慨濠呮閹叉挳宕熼銏犘戠紓浣稿⒔閾忓酣宕ｉ崘顔衡偓浣糕枎閹邦喚鐦堥梺绋挎湰椤ㄥ棝寮埀顒勬⒑閸︻厼鍔嬪┑鐐诧工閻ｇ兘骞囬弶璺啋缂傚倷鐒﹂敋婵炲牊鍨垮娲礈閹绘帊绨煎┑鐐插级閻楃姴鐣烽幒妤€惟闁靛鍟紞濠囧箖閳轰緡鍟呮い鏃傚帶婢瑰姊绘担鐟扳枙闁衡偓闁秴鍨傞柛锔诲幗椤洟鏌熼幆褏鎽犲┑顖涙尦閺屾稖绠涢幙鍐┬ч梺鎸庣☉閻楀棝鈥旈崘顔嘉ч柛娑卞灣椤斿洭姊虹紒姗嗘當婵☆偅绻堥獮鍐锤濡ゅ﹥鏅梺閫炲苯澧寸€殿喖顭烽幃銏ゆ惞閸︻厾鍘梻浣稿閻撳牓宕抽鈧畷婵囧緞閹邦厸鎷洪梺鍛婄☉閿曪箓骞婇崘顏嗙＜缂備焦锕懓璺ㄢ偓娈垮枦椤曆囧煡婢跺á鐔煎礂閸忚偐鏆﹂梻鍌欑窔閳ь剛鍋涢懟顖涙櫠鐎电硶鍋撶憴鍕闁搞劌娼￠獮鍐ㄢ枎閹炬潙鈧粯淇婇婵囥€冪紒銊ф暬濮婄粯鎷呴崨濠冨創濠电偛鐪伴崹钘夌暦閻熸噴娲敂閸涱厺绨垫繝鐢靛仦閸垶宕瑰ú顏呭亗闁哄洢鍨洪悡娆撴煛婢跺﹦浠㈡い锝嗗▕閺屾盯骞掗幘瀵稿嚒闂傚洤顦扮换婵囩節閸屾粌鈪遍梺浼欑悼閸庛倝骞堥妸锔剧瘈闁告劏鏂傛禒銏犖旈悩闈涗沪闁绘濞€楠炲啫鈻庨幘宕囶唽闂佸湱鍎ょ换鍕焵椤掍礁鈻曟慨濠勭帛閹峰懐绮电€ｎ亝顔勭紓鍌欒兌缁垶宕硅ぐ鎺戠闁靛繈鍊曢柋鍥煏婢跺牆鍔ら柣锝囧劋娣囧﹪濡惰箛鏇炲煂闂佸摜鍣ラ崹璺虹暦閹邦厾绡€婵﹩鍘鹃崣鍐ㄢ攽閳藉棗鐏熼悹鈧敃鈧嵄闁绘垶菧娴滄粓鏌￠崒娑橆嚋闁搞倕娲﹂幈銊︾節閸愨斂浠㈤悗瑙勬礃椤ㄥ﹤顫忛懡銈咁棜閻庯綆浜為崝鐢告⒒閸屾瑨鍏屾い顓炵墢閳ь剚绋堥弲鐘诲箖閿熺姴鐏崇€规洖娲﹀▓楣冩⒑閸濆嫭鍌ㄩ柛鈺佸瀵偊宕掗悙瀵稿幈濡炪倖鍔戦崐鏇㈠汲闁秵鐓欏瀣捣鐢稓绱掔紒妯兼创妤犵偞顭囨竟鏇犫偓锝庝憾濡喐绻濋悽闈涗粶闁活亙鍗冲畷鎰板冀椤愩倗鐒块悗骞垮劚閹冲寮ㄦ禒瀣厱妞ゆ劗濮撮悘顕€鏌ㄥ☉娆戠煉闁哄矉绲鹃幆鏃堫敍濠婂憛锝夋⒑缁嬫鍎忛柟鍐查叄閹儳鐣￠幍顔芥畷闂侀€炲苯澧撮柛鈹惧亾濡炪倖甯掗崰姘焽閹邦厾绠鹃柛娆忣樈閻掍粙鏌涢幒鎾虫诞妤犵偞顭囩槐娆撴偐閻㈢數鏆伴梻鍌欑缂嶅﹤螞鐠恒劎鐭嗗〒姘ｅ亾闁诡喒鈧枼妲堥柕蹇ョ磿閸橀亶鏌ｈ箛鏇炰户闁惧繐楠搁埢鎾诲即閵忊€斥偓鍨叏濮楀棗鍘甸柛瀣ㄥ灪閹便劍绻濋崟顓炵闂佺懓鍢查幊妯虹暦閵婏妇绡€闁稿本绋掗悾鑲╃磽閸屾艾鈧绮堟笟鈧、鏍幢濞戞ê鐎梺绉嗗嫷娈旈柡瀣╃窔閺屾盯骞囬棃娑欑亶闂佸搫鎳忕换鍫ュ蓟濞戞矮娌柣鎰靛墰濞堛倝姊哄Ч鍥р偓鏇灻洪鐑嗘綎婵炲樊浜滃婵嗏攽閻樻彃鏆欐い锔规櫊濮婅櫣绮欑捄銊ь唹闂佽崵鍣︽俊鍥╁垝鐎ｎ亶鍚嬮柛婊€鑳堕崣鍡涙⒑閸涘﹥纾甸柡鍛懅閼鸿鲸绻濆顓涙嫼闁荤喐鐟ョ€氼剛绮堥崘鈺冪濠㈣泛顑囬埊鏇犵磼閸屾稑娴柡浣稿€块弻銊╊敍濮橆偄顥氶梻浣藉吹閸犳挻鏅跺Δ鍛柈闁绘劗鏁哥壕濂告偣閸ャ劌绲绘い蹇ｅ亝娣囧﹪宕ｆ径濠傤潚濡ょ姷鍋炵敮鎺曠亙婵犵數濮撮崯顖氣枍閺冨牊鈷掑ù锝堟閵嗗﹪鏌涢幘瀵哥疄闁诡喚鍏樻俊鐑藉煛娴ｈ袣闁诲骸鍘滈崑鎾绘煕閺囥劌澧伴柛娆忓缁辨捇宕掑▎鎴濆濡炪値鍘煎ú锕傚疾閸洘鍋ㄩ柛娑橈功閸樻悂鏌ｈ箛鏇炰粶濠⒀傜矙閸┿儲寰勯幇顓犲帗闂佽姤锚椤﹁棄螣閳ь剟鎮楃憴鍕┛缂佺粯绻堥獮鍐ㄢ枎閹存柨浜鹃柣銏犳啞濞呮粌顭跨憴鍕婵﹤顭峰畷鎺戔枎閹搭厽袦闂備礁婀辩€典粙濡堕崱妯烘闂傚倸鍊峰ù鍥敋閺嶎厼绐楅柡宥庡幖绾惧綊鏌熼梻瀵哥瓘缂傚秵鐗犻悡顐﹀炊閵婏箑顎涘┑鐐叉▕娴滃爼寮崒鐐寸厱闁哄洢鍔屾禍鐐烘煟濞戞帗娅呴柍瑙勫灴閹晠宕归锝嗙槑濠电姵顔栭崰妤呭箰閸愯尙鏆︽い鏍剱閺佸啯鎷呭澶婄倞妞ゆ巻鍋撻柣鎾寸洴閺屾稑鈽夐崡鐐寸亐闂佸湱鏌夊▍锝囨閹惧瓨濯撮柛鎾村絻閸撳崬顪冮妶鍡楃仸闁荤啿鏅涢悾鐑藉即閿涘嫮鏉稿┑鐐村灦閻熴儵鍩€椤掆偓閻忔岸骞堥妸銉建闁糕剝銇炵花濠氭倵鐟欏嫭灏俊顐ｇ箞瀵寮撮姀鐘茶€块梺鍝勬川婵厼危椤曗偓閺屟呯磼濡厧鈷岄梺鍝勬湰缁嬫垿鍩ユ径鎰闁绘劖褰冮婊勭節閻㈤潧浠ч柛妯犲洦鏅濇い蹇撳濞兼牗绻涘顔荤凹闁稿﹦鍏橀弻锕€螣娓氼垱笑婵犳鍠撻崐婵嬪蓟閿濆牏鐤€闁规儳澧庨澶愭⒑閼姐倕鏆€闁告侗鍘奸悘濠囨煟閻樺弶鎼愭俊顖氾工椤洭鍩￠崒妯圭盎闂佸湱鍎ら崺鍫澪ｈぐ鎺撳€甸梻鍫熺〒閻掑憡鎱ㄦ繝鍐┿仢婵☆偄鍟埥澶婎潩椤掑姣囧┑鐘殿暯濡插懘宕戦崨顖滅煓闁圭儤顨呴悿楣冩煕椤愶絾澶勯柡浣告閺屾盯寮撮妸銉ヮ潾闂佸憡锕㈡禍璺侯潖濞差亝鍋￠梺顓ㄧ畱濞堣埖绻濆▓鍨灓闁轰浇顕ч悾鐑芥偨缁嬭法鍔﹀銈嗗笒鐎氼參鎮￠敐鍚ゅ綊宕楅懖鈺傚櫘缂備礁顦介崳锝夊蓟閿涘嫪娌柣锝呯潡閵夛负浜滅憸宀€娆㈠璺鸿摕婵炴垯鍨圭粻濠氭偣閾忕懓鍔嬮柣蹇撶墕铻栭柣姗€娼ф禒婊堟煕閻曚礁浜柣蹇撳暣濮婃椽宕ㄦ繝鍌氼潊闂佸搫鎳忛惄顖氼嚕閹间礁纾奸柣鎰ˉ閹锋椽姊洪崨濠勨槈闁挎洏鍎插鍕礋椤栨稓鍘遍梺瑙勫劤椤曨厼煤閹绢喗鐓曢柍鍝勫暙娴犳粓鏌嶉挊澶樻Ц妞ゎ偅绻冨蹇涘煛鐎ｎ剟妫峰┑鐘垫暩閸嬬娀骞撻鍡楃筏闁秆勵殔缁犵娀鏌熼幑鎰【缂佽翰鍊曢埞鎴︽偐瀹曞浂鏆￠梺缁樻尭閸熶即骞夌粙娆剧叆闁割偅绻勯ˇ顓炩攽閻愭潙鐏熼柛銊ユ贡缁絽螖閸涱喚鍘甸梺璇″瀻鐏炶姤顔嶆俊鐐€愰弲婊嗐亹閸愵喗绠掗梻浣虹帛閿氭俊顖氾躬瀹曟洟骞囬悧鍫㈠帗闂備礁鐏濋鍛箔閹烘顥嗗鑸靛姈閻撱儲绻濋棃娑欘棡鐎瑰憡绻堥弻鐔兼寠婢跺ň鍋撻崸妤€钃熸繛鎴欏灩鍥撮梺鍛婁緱閸樿棄鈻撴繝姘拺闁告繂瀚﹢鎵磼鐎ｎ偄鐏遍柣蹇斿浮濮婅櫣绮欑捄銊ь唶闂佸憡鑹鹃澶愬箖閻㈠壊鏁傞柛顐ゅ暱閹锋椽鏌℃径灞戒沪濠㈢懓妫涢幏瑙勫鐎涙鍘遍梺鎸庣箓缁绘帞绮旈鈧弻锝呪槈閸楃偞鐝濆Δ鐘靛仦鐢帟鐏冮梺閫炲苯澧扮紒顔垮吹閹风娀宕ｉ崒娑氭创闁诡啫鍥ч唶闁靛繈鍨婚弳顐ょ磽閸屾瑦顦风紒璁圭節瀹曟垿宕ㄩ娑樺簥濠电娀娼ч鍡涘磻閵娾晜鈷掗柛顐ゅ枔閳笺儳绱掗鎸庣【闁宠鍨块崺銉╁幢濡ゅ啩鍝楅梻浣瑰濞插繘宕曞畷鍥у灊閻庯綆浜堕崥瀣煕濞戝彉绨奸柡鍌楀亾闂備浇顕ч崙鐣岀礊閸℃顩查柣鎰惈閸?")
        if teaching_decision_reason and not weak_spots:
            parts.append("")
        return "".join(parts)

    parts = []
    if learner_signal == "blocked":
        parts.append("You sound blocked on a decision point, which means we should reduce scope instead of widening it.")
    elif learner_signal == "uncertain":
        parts.append("You do not mainly need more effort right now; you need a steadier decision sequence.")
    elif learner_signal == "curious":
        parts.append("You are leaning into the mechanism, which is good, but we should keep the understanding tied to action.")
    else:
        parts.append("Your current pacing looks steady, so we can keep tightening the problem boundary.")
    if diagnostics_count:
        parts.append(f" There are also {diagnostics_count} diagnostic signals attached, so the feedback loop should be restored early.")
    if weak_spots:
        parts.append(f" I also want to watch for a repeated weak spot here: {weak_spots[0]}.")
    elif teaching_observations:
        parts.append(f" The most relevant teaching observation from recent work is: {teaching_observations[0]}.")
    elif summary:
        parts.append(f" {summary}")
    if teaching_decision_reason and not weak_spots:
        parts.append(f" Teaching reason: {teaching_decision_reason}.")
    return "".join(parts)


def _scaffold_next_step(
    *,
    scenario: str,
    mode: str,
    learner_signal: str,
    file_path: str | None,
    weak_spots: list[str],
    next_step_hint: str,
    chinese: bool,
) -> str:
    localized_hint = _surface_context_text(next_step_hint, chinese=chinese)
    if next_step_hint and (localized_hint or not chinese):
        if chinese:
            return ""
        return f"The next move I recommend is this: {next_step_hint}"

    scenario_step = _scenario_step_text(
        scenario=scenario,
        file_path=file_path,
        weak_spots=weak_spots,
        chinese=chinese,
    )
    mode_prefix = _mode_style_label(mode, chinese)
    if chinese:
        if learner_signal == "blocked":
            return ""
        return ""
    if learner_signal == "blocked":
        return f"{mode_prefix} So do not do too much at once; start by {scenario_step}"
    return f"{mode_prefix} The highest-value next move is to {scenario_step}"


def _scenario_step_text(
    *,
    scenario: str,
    file_path: str | None,
    weak_spots: list[str],
    chinese: bool,
) -> str:
    repeated_gap = weak_spots[0] if weak_spots else ""
    localized_repeated_gap = _surface_context_text(repeated_gap, chinese=chinese)
    if chinese:
        mapping = {
            "idea_implementation": (
                ""
            ),
            "engineering_challenge": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡▎鎴犫敍闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼宕滆绾惧ジ鏌ｅΟ鎸庣彧閻忓浚鍙冮弻锝夋晲婢跺鏆犵紓浣芥閺咁偆鍒掑▎蹇婃瀻闁绘劦鍓涚粔閬嶆⒒閸屾瑨鍏岄柛瀣ㄥ姂瀹曟洟鏌嗗鍛焾闁荤姵浜介崝蹇旀叏閹惰姤鐓忓璺烘濞呭棝鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡樺窛闁硅棄鍊圭换娑㈠礂閻撳骸顫屽銈庡幖濞硷繝骞冮悜鑺ュ亱闁割偒鍋呴敍渚€姊绘担鍛婃儓闁硅櫕鎸搁埢鏂库槈濠婂懍绨烽梻鍌欑閹测剝绗熷Δ鍛偍濡わ絽鍟弲顒佺箾閹存瑥鐏柣鎾跺枛楠炴牠骞栭鐐典化缂備礁顦靛褔婀佸┑鐘诧工鐎氼喗鏅堕悽纰樺亾濞堝灝鏋旈柛鏂跨Ф缁骞掗弬鍝勪壕闁挎繂楠告禍鐐烘煕濡寧顥夐柍瑙勫灴閸┿儵宕卞Δ鍐ф樊婵＄偑鍊栧▔锕傚川椤撶姷鐡樺┑鐘垫暩婵數鍠婂澶嬪亗婵炴垯鍨洪悡鏇㈡煃閳轰礁褰侀柟瀵稿Х閻棝鏌涢鐘茬伄缁炬儳銈稿鍫曞醇濞戞ê顬堢紓浣广亞閸ャ劎鍘垫俊鐐差儏妤犳悂鍩㈤崼鈶╁亾鐟欏嫭绌跨紒鍙夊劤椤曘儵宕熼瀣枑鐎电厧鈻庨幋鐙€妲梻鍌氬€搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偞鐗犻、鏇㈡晝閳ь剛鈧艾顦伴妵鍕箳閹存績鍋撴繝姘剹婵炲棙鎸婚悡娆撳级閸繂鈷旈柣锝変憾閺岋綁骞樻潏鎹愨偓鍧楁煛瀹€鈧崰鎰焽韫囨稑绀堢憸蹇涘汲閻樼數纾藉ù锝嗗絻娴滈箖鏌ｆ惔顖滅У闁稿鐒︾粋宥咁煥閸喓鍘甸梺閫涚祷濞呮洖鈻嶉崨瀛樼厽闊洤锕ュ▍鍡涙煏閸パ冾伃妞ゃ垺娲熼弫鎰板醇濠垫劖顥ら梻鍌欑閻ゅ洭锝炴径鎰瀭闁秆勵殔缁犳牠鏌嶉崫鍕櫣缂佺姵绋戦湁闁挎繂鎳忛崯鐐寸箾閸涱喚娲存慨濠勭帛閹峰懐鎲撮崟顐″摋闂備礁鎲￠弻銊╊敄婢跺﹦鏆﹂柨鐔哄Т缁€鍐煠绾板崬澧繛鍫ョ畺濮婃椽妫冨☉宕囩闂侀€炲苯澧寸€规洘鍨块獮妯肩磼濡粯鐝抽梺纭呭亹鐞涖儵宕滃┑瀣€堕柛顐ゅ枍缁诲棙淇婇妶鍌氫壕闂佺娅曢敋妞ゎ偄绻愮叅妞ゅ繐瀚粣娑欑節閻㈤潧孝闁哥噥鍋婅棟闁冲搫鎳忛埛鎴︽煙閼测晛浠滃┑陇妫勯…鍧楁偡閻楀牜妫ら梺鍛婂笚鐢偟妲愰幒鎳崇喖鎳栭埡鍐╊潓濠电姵顔栭崰妤呮晝閳哄懎鍌ㄩ柛蹇氬亹椤╅攱銇勯弽顐沪闁抽攱鍨块弻鐔碱敍閸℃鍣芥い鏃€鍨甸—鍐Χ鎼粹€茬盎濡炪倧绠掓ご鍝ョ博閻旂厧鍗抽柕蹇婃櫆閺呮粓姊洪崜鎻掍簽闁哥姵鎹囧畷銏ゎ敂閸涱垳鐦堥梺闈涢獜缁插墽娑甸悙顑跨箚妞ゆ劧绲块幊鍐煃鐠囪尙效鐎规洖宕埥澶娾枎閹存繂绠洪梻鍌欐祰椤鐣峰Ο琛℃灃婵炴垯鍨归崙鐘绘煙鏉堥箖妾柣鎾崇箻閺屾盯濡烽幋婵嗘灓濞寸厧鍟灃闁绘﹢娼ф禒锔姐亜椤撶偞鍠樻鐐村灴瀹曠喖顢涘顐ょ倞闂備礁鎲″ú锕傚磻閹烘嚦娑欐償閵婏腹鎷洪柣鐘叉搐瀵爼宕径瀣ㄤ簻妞ゆ劑鍩勫Ο鈧Δ鐘靛仜閸熸潙鐣锋總绋垮嵆闁绘劗顣槐鐢告⒒娴ｅ湱婀介柛銊ヮ煼閳ワ箓宕奸姀顫瑝濠电偛妯婃禍婵嬫偂閺囩喆浜滈柟鏉垮缁嬭崵绱掗埀顒勫礃椤旂晫鍘辨繝鐢靛Т鐎氼剟宕㈤幘顔界厸鐎光偓鐎ｎ剛袦濡ょ姷鍋涢澶愬箖濠婂牆骞㈡繛鍡楃箰妤旈梻鍌氬€风粈渚€骞夐敓鐘偓锕傚醇濠㈩亝鐩畷鐔碱敍濮樺崬骞嬮梻浣烘嚀椤曨參宕戝☉姘变笉闁绘绮埛鎴犵磼鐎ｎ亜鐨￠柡鈧繝姘厱闁哄啠鍋撻柣鐔村劦閹箖鎮滈挊澶岊吅闂佹寧娲嶉崑鎾剁磼閻樺搫鍚圭紒杈ㄦ尰閹峰懐鎷犻敍鍕Ш闂備礁鎲￠…鍫澪涢崟顖氱厴闁瑰鍋涚粻鐘绘⒑缁嬪尅鏀绘繛鑼枎閻ｇ兘顢涢悜鍡樻櫇闂佹寧绻傚ù鍌毭归崟顖涒拻濞撴艾娲ゆ晶顔剧磼婢跺本鏆柟顔光偓鏂ユ瀻闁规儳顕崣鍕椤愩垺绁紒鑼跺Г缁傚秴鈹戦崼姘壕閻熸瑥瀚粈鈧梺娲诲墮閵堟悂宕洪埀顒併亜閹烘垵鏋ゆ繛鍏煎姈缁绘盯宕ｆ径宀€鐓夐梺鐐藉劵缁犳挸鐣锋總鍛婃櫜闁搞儻濡囬懗鍝勨攽閻樺灚鏆╅柛瀣█楠炴捇顢旈崱妤冪瓘婵炲濮撮鍛不鐟欏嫨浜滈柟鎷屾硾椤╊剛鈧鎸烽懗鍫曞焵椤掆偓缁犲秹宕曢柆宓ュ洦瀵奸弶鎴犲幈闂佸湱鍎ら崵姘炽亹閹烘挻娅滈梺鍛婁緱閸犳牠寮抽崼銉︹拺閻犲洠鈧磭浠╅梺缁橆殔閿曨亝淇婇悽绋跨妞ゆ牗姘ㄩ娲⒑缂佹ê濮堢憸鏉垮暣閿濈偤骞掑Δ浣糕偓鐢告偡濞嗗繐顏紒鈧崘顔界厱闁靛鍎虫禒銏ゆ煟閿濆洤鍘撮柟顔哄灮閸犲﹥娼忛妸锔界彨濠电姵顔栭崰妤呮晪閻庤娲﹂崜姘跺箞閵娾晜鏅滈柟瀛樺笧缁犳岸姊虹紒妯哄Е濞存粍绮撻崺鈧い鎺嶈兌婢ч亶鏌℃笟鍥ф灍缂佺粯绻堝畷鍫曞Ω閵夛妇鏆犻梻鍌欑閹诧繝骞愰悜鑺ュ殑闁煎摜鏁搁埢鏃傗偓骞垮劚椤︿即鎮″▎鎾寸厱闁圭偓顨呴幊搴ｇ箔閿熺姵鈷戠紓浣股戠亸鐢告煕閻樺磭澧电€殿喖顭锋俊鎼佸Ψ閵忊剝鏉搁梻浣虹《閸撴繆鎽梺璇″枟閻熲晛顫忓ú顏勫窛濠电偞纰嶉崹鍧楃嵁閹版澘绠柦妯侯槼閹芥洟姊虹紒妯烩拻闁冲嘲鐗撳顐ｇ節閸ャ劎鍘介梺鎸庣箓閹虫劙鎮橀柆宥嗙厽闁圭偓鍓氬Ο鈧┑顔硷攻濡炶棄鐣烽悜绛嬫晣鐟滃繘宕濋幖浣光拺闁圭瀛╃壕鎼佹煕鎼达紕锛嶉柛鎺撳浮閸╋繝宕ㄩ闂寸盎闂備胶绮幐绋棵归悜钘夊偍闁圭虎鍠楅埛鎴犵磽娴ｅ顏呮叏閿曞倹鐓曢柟鐐綑閸濇椽鏌熼鈧褔锝炲┑瀣殝缁剧増蓱鐎氬ジ姊绘担鍛婂暈缂佽鍊婚埀顒佸嚬閸樺ジ鏁冮姀銈嗗亱闁割偁鍨婚鏇㈡⒑閸涘﹦鎳冩い锔跨矙閹偤鎮惧畝鈧壕鍏笺亜閺冨浂娼愭繛鍛躬閺岀喖顢欓崫鍕紕闂佸摜濮撮敃銉ヮ焽韫囨稑惟闁挎梻鏅ぐ銊︾節閻㈤潧校妞ゆ梹鐗犲畷鏉课旈崨顔芥珖闂佸啿鎼幊搴ㄥ磼閵娿儮鏀介柛灞剧矤閻掗箖鏌ｉ妶澶岀暫闁哄矉绠戣灒濞撴凹鍨遍埢鎾斥攽閻愬瓨灏い顓犲厴瀵寮撮姀鐘诲敹濠电娀娼уú銈呪枍瑜忕槐鎾存媴閸濆嫅锟犳煕濡や礁鈻曠€殿喖顭烽弫鎰板川閸屾稒顥堥柛鈹惧亾濡炪倖甯掔€氼參寮插┑鍥ヤ簻闊洦鎸炬晶鏇㈡煛閸曗晛鍔滅紒缁樼洴楠炲鈻庤箛鏇氭偅缂傚倷鑳舵刊瀵哥礊娓氣偓瀵濡搁埡浣虹潉闂佺鏈粙鎺楁偟椤忓牊鈷戦柛娑樷姇椤忓嫮鏆︽い鎺戝閻撴﹢鏌熸潏楣冩闁稿﹦鍏橀弻鈩冨緞鐎ｎ亞浠兼繛瀵稿У閹倸顫忓ú顏勭閹兼番鍨归ˇ鈺呮⒑缁嬫鍎忛柨鏇樺€濋、姘舵晲婢跺á鈺呮煥閺傚灝鈷旈柣锕€鐗嗛埞鎴︻敊閺傘倓绶甸梺鍛娒妶鎼佸春閳ь剚銇勯幒鍡椾壕闂佺粯鐗曢妶鎼佸箖閿熺媭鏁冮柨鏇楀亾闁绘劕锕ら—鍐偓锝庝邯椤庢鏌涢埡浣藉閾绘牠鏌ｅ鈧褎绂掗敂濮愪簻妞ゆ挾鍋炲婵囦繆閸欏濮嶆鐐村浮楠炴鈧潧鎽滆倴闂傚倷绶氬褔鈥﹂崼銉ョ？闁规儼濮ら崑锟犳煛鐏炶鍔滈柛濠勬暬閺屾盯鈥﹂幋婵呯凹缂備浇鍩栭悡锟犲箖濡も偓椤繈鎮℃惔锛勵啋闂備胶鎳撶粻宥夊垂瑜版帒鐓橀柟瀵稿Л閸嬫捇鏁愭惔婵堟晼濡炪倧闄勫姗€鈥旈崘顔嘉ч柛鈩兠喊宥咁渻閵堝繐鐦滈柛娆忓暙閻ｅ嘲鈹戦崱鈺佹倯闂佹悶鍎崝灞炬償婵犲倵鏀介柣妯肩帛濞懷囨煟濡も偓濡繂顕ｉ幖浣搁唶闁绘柨澧庣粻姘渻閵堝棛澧痪鏉跨Ч楠炲棝宕奸妷锔惧帗閻庣懓瀚伴崑濠偽ｉ幖浣圭厓閻熸瑥瀚悘鎾煙椤旂晫鎳囨鐐存崌楠炴帡骞橀弬銉ヤ壕妞ゆ牜鍋為埛鎴︽煠婵劕鈧洟寮抽柆宥嗙厸闁告侗鍨伴埢鍫濃攽閳ュ磭鎽犻柟宄版嚇瀹曟粓宕ｆ径濠勭处闂傚倷绶氶埀顒傚仜閼活垱鏅堕鈧弻锝夋晲閸涱厽些闁剧粯鐗犻弻娑樷槈閸楃偞鐏堟繛瀛樼矋椤ㄥ﹪寮婚悢鍏煎殞闁绘鐗嗗☉褏绱撴担鐟扮祷婵炵》绻濋獮鍐╁閹碱厽鏅梺閫炲苯澧い顐㈢箻閹煎湱鎲撮崟顐ゅ酱闂備礁婀辩划顖滄暜閹烘嚩鎺楀箛椤斿墽锛濋梺绋挎湰濮樸劌鐡繝纰樻閸嬪懘鎮疯閸掓帞鈧綆浜堕崥瀣煕濠娾偓閼冲爼宕ｉ崱娑欌拺闁告稑锕ユ径鍕煕濡绀冮柕鍥ㄥ姈閵堬綁宕橀埞鐐缂傚倷绶￠崹鍗灻洪弽銊︽珷闁哄被鍎查崕鎴濐熆鐠鸿櫣鐏辩痪鎯с偢閹綊宕惰缁狙勩亜閵夛絽鐏查柡灞糕偓宕囨殕閻庯綆鍓涜ⅵ婵°倗濮烽崑娑樏洪鐐垫殾婵°倕鎳庢导鐘绘煏婢诡垰瀚▍鎺楁⒒閸屾艾鈧娆㈠璺虹劦妞ゆ帒鍊告禒婊堟煠濞茶鐏￠柡鍛埣椤㈡盯鎮欑€电骞楁繝寰锋澘鈧捇鎮為敂鍓х焼閻庯綆鍠楅悡銉︾節闂堟稓澧曞ù鐘櫇缁辨帡鎮╁畷鍥ㄥ垱閻庢鍣崳锝呯暦閹烘埈鐓ラ柛娑卞櫘濞兼挻绻濋悽闈浶ｆい鏃€鐗犲畷鏉课旈崨顔芥珖闂佸啿鎼幊搴ｇ矆閸喓绠鹃柟瀛樼懃閻忣亪鏌￠崪浣稿缂佺粯鐩獮瀣枎韫囨洑鐥梻浣瑰▕閺€閬嶅垂閸ф钃熼柨婵嗩槹閸嬪嫰鏌涘☉姗堝姛闁告埊绻濆娲箮閼恒儲鏆犲┑顔硷龚瀹曢潧危閹版澘绠虫俊銈咃攻閺咁亪姊洪崨濠佺繁闁告鍋撶粋鎺楀箹娴ｇ懓鈧敻鎮峰▎蹇擃仾缂佲偓閸愵喗鐓曢柕濞垮劜閸嬨儳鈧娲樺浠嬪极閹剧粯鍋愰柟缁樺笧閻涒晜淇婇悙顏勨偓鏍ь潖瑜版帒纾块柟鍓佹櫕瀹撲線鏌涢銈呮灁缂佲檧鍋撻柣搴″悁閸楁娊寮ㄩ崡鐑嗙唵婵せ鍋撻柛鈹惧亾濡炪倖甯婇悞锔剧矆鐎ｎ兘鍋撶憴鍕闁搞劌鐖奸妴渚€寮撮姀鈩冩珳闂佹悶鍎撮崺鏍煥閵堝鈷戦柤濮愬€曢弸鎴︽煟閻旀潙鍔ら柍褜鍓氶崙瑙勭閻愬搫绠查柕蹇嬪€曢獮銏＄箾閹寸偟鎳呴柛妯兼暩缁辨捇宕掑▎鎴濆闂佹寧姘ㄧ槐鎺戭渻閿曗偓閸犳岸鎮㈤崱娆愬枑婵犻潧鐗忔稉宥夋煙閹规劦鍤欓柦鍐枛閺屽秹濡烽妷褝绱為梺鍝勬濡繈寮诲鍫闂佸憡鎸鹃崰搴ㄦ偩闁垮顕遍柡澶嬪灩椤旀帡姊洪悡搴㈠暈妞ゆ梹鐗曢…鍥偄閸忓皷鎷洪梺闈╁瘜閸樺ジ宕濈€ｎ偁浜滈柕濞垮劜閸ゅ洭鏌ㄥ┑鍫濅槐鐎规洏鍔庨埀顒佺⊕椤洭宕㈤挊澶嗘斀闁宠棄妫楅悘鐘绘煙绾板崬浜版鐐插暞缁楃喖鍩€椤掑嫬钃熸繛鎴炃氶弨浠嬫煕閵夈劌鐓愰柣锝呯埣濮婅櫣鈧湱濯鎰版煕閵娿儲鍋ユ鐐插暙閳诲酣骞橀弶鎴烆吇婵＄偑鍊栫敮濠囨倿閿曞倸绐楅柡宥庡亞绾句粙鏌涚仦鍓ф噮閻犳劒鍗抽弻娑㈡偐瀹曞洤鈷岄梺鍝勮嫰閿曨亪寮幇鏉垮窛妞ゆ牗绋掗鏇㈡⒒娴ｄ警鏀伴柟娲讳簽缁骞嬮悩鍏哥瑝婵犵數濮电喊宥夋偂閻樼粯鐓欓梻鍌氼嚟閸斿秵绻涢幊宄版搐缁犲綊鏌℃径瀣厐鐎规悶鍎甸弻宥囨喆閸曨偆浼岄梺璇″枓閺呮繄妲愰幒鎳崇喐绻濆顓熸婵犵绱曢崑鎴﹀磹閺嶎厼鍨傞柣銏㈩焾缁犵姵鎱ㄥ璇蹭壕闂佽桨鐒﹂崝娆撳箖濞嗘挸浼犻柛鏇ㄥ亞閻涒晠姊虹拠鎻掝劉缂佸甯￠垾锕傚炊椤掆偓閻鏌涢埄鍐︿粶闁衡偓娴犲鐓熸俊顖濆亹鐢稒绻涢幊宄板缁诲棙銇勯幇鍓佹偧闁瑰啿娲幐濠囨偄閸忚偐鍘藉┑鈽嗗灥閸嬫劗鏁☉銏＄厽闁规儳纾粻濠氭煛鐏炲墽娲撮柛鈺佸瀹曟鎮埀顒佺濠靛绠為柕濞垮労閸氬顭跨捄渚剳闁告ɑ鎮傞幃妤呭礂婢跺﹣澹曢梺璇插嚱缂嶅棝宕滃☉婊勬噷闂傚倸鍊峰ù鍥敋閺嶎厼鍨傞柛妤冨€ｅ☉銏犵闁冲搫鍊稿鍧楁⒑闁偛鑻晶鎾煛瀹€瀣埌閾伙綁鏌涘┑鍡楊伀濡ょ姴娲鐑樺濞嗘挻顎嶉梺鍦嚀濞层倝锝炶箛鏇犵＜婵☆垵顕ч鎾绘⒑閸涘﹦鈽夐柨鏇樺劦瀹曚即骞囬鐘电槇濠电偛鐗嗛悘婵嬪几閵堝鐓涘ù锝呭閻撳吋顨ラ悙鎻掓殺妞わ箑缍婇弻鐔碱敊鐟欏嫭鐝栭梺褰掝棑婵炩偓鐎规洩绲惧鍕沪缁嬪じ澹曞銈嗗笒鐎氼參鍩涢幋锔界厱婵炴垶锕銉モ攽椤曞棛鐣甸柡灞剧洴閹晛鐣烽崶褉鎷伴梻浣瑰缁诲嫰宕戦妶鍛殾闁靛ě鈧崑鎾斥槈濞嗘鍔烽梺鍛婏供娴滎亜顫忓ú顏勭闁圭粯甯婄花鑲╃磽娴ｇ瓔鍤欓柛鐔侯棎濡垽姊虹紒妯哄妞ゆ洦鍘剧划缁樸偅閸愨晝鍘卞┑鐐村灥瀹曨剟寮搁妶鍜佺唵鐟滃秹鎮樺璺虹疄闁靛濡囩弧鈧梺鍛婂姀閺傚倹绂掗姀銈嗗€甸悷娆忓绾炬悂鏌涢弬璺ㄐら柟骞垮灩閳规垹鈧綆浜為ˇ銊ヮ渻閵堝懐绠版繛瀵稿厴瀹曟澘顫滈埀顒€顫忔繝姘＜婵炲棙鍩堝Σ顕€姊虹涵鍜佸殝缂佺粯绻傞锝嗙節濮橆儵鈺呮煃鏉炴壆顦﹂柣婵嚸—鍐Χ閸℃鐟ㄩ梺绋匡工椤兘骞嗙仦鎯х窞閻忕偟顭堟禍鐐殽閻愯尙浠㈤柛鏃€纰嶆穱濠囶敃閵忋倕寮伴悗瑙勬礃閸ㄥ灝鐣烽妸褉鍋撳☉娆樼劷闁告﹢浜跺铏规兜閸涱厾鍔烽梺鍛婃煥缁夋挳鍩㈠澶婄倞妞ゆ帊鑳堕崢鍗炩攽椤斿浠滈柛瀣尭闇夋繝濠傛绾偓銇勯銏㈢閻撱倖銇勮箛鎾愁伀妞ゆ柨娲弻鐔煎礂閼测晜娈梺绯曟櫅鐎氼剟锝炶箛娑樺瀭妞ゆ洖鎳忕€靛矂姊洪棃娑氬婵☆偅鐟╅幊鏍偐缂佹鍘遍梺闈涱槶閸ㄥ搫鈻嶉崨顖滅＜濞撴艾锕﹂悾鍨叏婵犲啯銇濈€规洦鍋婂畷鐔碱敇濞戞瑧鈧亶姊绘担绛嬪殭缂佺粯鍨垮畷婵嗩潨閳ь剚淇婇悽绋跨疀闁哄娉曢濠囨⒑鐟欏嫬鍔ら柛妯荤墪鏁堟俊銈呮噺閳锋帒霉閿濆懏鍟為柛鐔哄仱閺屾盯寮埀顒€煤閺嶎収鏁嬮柨婵嗩槸缁€鍫澝归敐鍥ㄥ殌闁绘繀鍗冲铏圭磼濡搫顫庨梺绋跨昂閸婃繈宕哄☉銏犵闁挎梻鏅崢鍗炩攽閻樼粯娑ф俊顐ｎ殜椤㈡棃顢旈崨顖滅槇闂侀€炲苯澧悗浣冨亹閳ь剚绋掗…鍥储娴犲鈷戦柛鎰级閹牓鏌ㄩ弴妯衡偓婵嬪箖濮椻偓閺佸倻绮电€ｎ偒鍟嶉梻浣虹帛閸旀牞銇愰崘顔兼辈婵炲棙鍔戞禍婊勩亜閹惧鐭婂┑顔煎€婚埀顒冾潐濞叉粓宕㈣閸╃偤骞嬮敃鈧獮銏℃叏濮楀牏鍒板ù婊堢畺閺屾盯鈥﹂幋婵囩亐闂佽　鍋撳ù鐘差儏缁犳娊鏌熼幆鐗堫棄缁炬儳缍婇弻鐔兼偋閸喓鍑＄紒鐐劤椤兘寮婚悢鐓庣鐟滃繒鏁☉銏＄厽闁规儳鍟块弳鐔兼煃瑜滈崜娑㈠箠閹惧灈鍋撳顐㈠祮鐎规洘鍨剁换婵嬪炊瑜忛敍鐔兼⒑閸濆嫬鏆婇柛瀣崌閺岀喐绗熼崹顔碱瀴缂備胶绮换鍫濈暦閵娾晩鏁嬮柛娑卞墮閹藉姊婚崒娆戭槮缂傚秴锕棢闁规儳顕粻楣冩煃瑜滈崜鐔煎蓟濞戙垹惟闁挎洍鍋撻柛鏂诲€濋弻锝夋晲閸パ冨箣閻庤娲栭悥濂稿极閸愵喖鐒垫い鎺戝缁犳椽鎮楅敐搴″缁惧彞绮欓弻娑氫沪閹规劕顥濋梺閫炲苯澧存い銉︽尵閸掓帡宕奸悢铏规嚌闂侀€炲苯澧叉俊顐ゅ枛濮婄粯绗熼崶褍顫╃紓浣割槹閹稿啿顕ｉ崨濠冨缂侇垱娲橀弬鈧梻浣虹帛椤牆鈻嶉弴銏″剭闁瑰濮崑鎾舵喆閸曨剙鐭紓浣藉煐瀹€鎼佸箖閿熺媭鏁冮柨鏇楀亾闁绘劕锕弻鏇熺箾瑜夐崑鎾翠繆閹绘帞澧﹂柟顔筋殜閹兘鎮ч崼婵囨畼缂傚倷娴囬褔鎮ч幘鑽ゅ祦闁告劑鍓弮鍫濈劦妞ゆ帒瀚悡鈥愁熆鐠哄彿鍫ュ几瀹ュ棎浜滈柟鐐殔閸婂宕欓崷顓犵＝濞达絿顭堥埀顒€婀遍弫顔嘉旈崘顏嗗婵炲濮撮鍛啅濠靛棌鏀介柣妯诲絻閳ь剛鏁诲畷鎴﹀箻缂佹ê浠洪梺鍛婄☉閿曪箓宕㈤柆宥嗩棅妞ゆ劑鍨烘径鍕煙鐏忔牗娅呴崡杈╃磼鐎ｎ偓绱╅柣鐔煎亰閻撱儵鏌涢鐘茬伄闁哄棭鍋勯埞鎴︻敊绾攱鏁惧┑锛勫仒缁瑥顕ｆ繝姘窛閻庢稒锚閳ь剛鍏橀弻銈夋嚌閻楀牏銆愬銈呮禋閸樼晫鎹㈠┑瀣厱闁逞屽墴瀹曠喖顢橀悙鑼摋闂傚倷绀侀幖顐﹀嫉椤掆偓鐓ら柣鏃堫棑閺嗭箓鏌涢锝嗙閹喖姊洪棃娑辨Ф闁稿骸鎼…鍥籍閸啿鎷绘繛鎾村焹閸嬫挻绻涙担鍐叉处閸嬪鏌ｉ幇顔芥毄缂佲偓婵犲伅褰掓晲閸涱喗鍠愰梺鍝勬４闂勫嫰骞堥妸銉富閻犲洩寮撴竟鏇㈡⒒娴ｈ櫣銆婇柡鍛箞瀹曟垿濡舵径濠勭暫濠电偛妫欓幖鈺呭极閸℃稒鐓冪憸婊堝礈閻旂鈧線寮崒娑樻瀭闂佸憡娲﹂崢楣冩儊閸儲鈷戞慨鐟版搐閻忓弶绻涙担鍐插椤╃兘鏌ㄩ弮鍌涙珪缂佺娀绠栭弻娑滅疀濮橆兛姹楅梺鐟板暱濞层劑鍩€椤掑喚娼愭繛鎻掔箻瀹曟洟骞庨挊澶屽姦濡炪倖甯掗敃锔剧矓閻㈠憡鐓曢柣妯诲墯濞堟粎鈧娲橀崹鍧楀极瀹ュ绀嬫い鎺嗗亾闁哄鍨垮娲传閸曨偀鍋撻挊澶嗘灃闁哄洢鍨瑰Ч鏌ユ煥閺冨洤袚闁告瑥绻戞穱濠囶敍濞戞﹩鍤嬬紒缁㈠幖婢х晫妲愰幒妤佸亼婵炲棗绻戦幖鎰磼閻樿尙绉洪柟顔筋殔閳藉鈻嶉搹顐㈢仼濞存粌鎲＄€佃偐鈧稒顭囬崢鎼佹⒑缁嬫寧婀版い銊ユ噺缁傚秵銈ｉ崘鈹炬嫽闂佺鏈懝楣冨焵椤掑倸鍘撮柟铏殜瀹曞ジ寮村璇蹭壕闁挎洖鍊搁柋鍥煏婢跺牆鍔氶柣婵嚸—鍐Χ閸℃鐟ㄩ梺绋匡工椤兘骞嗙仦瑙ｆ瀻闁规儳顕崢鐢告⒑缂佹ê鐏﹂柨鏇楁櫅閳绘捇寮崼鐔哄幗闂佽鍎抽悺銊х矆鐎ｎ喗鐓涚€光偓閳ь剟宕伴弽顓炵畺婵犲﹤鍚橀悢鍏煎€婚柍鍝勫€搁铏圭磽閸屾瑨鍏岄柛瀣崌瀹曟洟骞庨挊澶幮曢柣搴秵閸犳牗顢婇梻浣告啞濞诧箓宕规导鏉戠闁规儼濮ら悡鐔兼煙闁箑骞楃紓宥嗗灦缁绘盯宕崘顏喰滈梺璇″枟椤ㄥ懘鍩㈤幘璇插瀭妞ゆ梻鏅ぐ顖炴⒒娴ｅ憡鎲稿┑顕€娼ч悾婵嬪箹娴ｅ憡妲梺閫炲苯澧柕鍥у楠炴帡骞嬪┑鍥╀壕婵犵數鍋涢崥瀣礉閺嶎偅宕叉繛鎴欏灩閻顭块懜娈跨劷闁告梻鍏樺鐑樻姜閹殿喛绐楅梺闈╃秶缂嶄礁顕ｉ锕€绠荤紓浣姑禍褰掓⒑閼测斁鎷￠柛鎾寸洴瀵娊顢曢敐鍥╃槇闂佹眹鍨藉褎绂掑鍕箚妞ゆ劧绲块幊鍥┾偓瑙勬礀缂嶅﹪骞冮姀銈嗗亗閹艰揪缍囩槐閬嶆⒒娴ｅ憡璐￠柛瀣崌瀵悂鎮￠獮顒婄秮瀹曞ジ鎮㈤搹璇″晭闂備礁鎲＄粙鎾存櫠濡ゅ懏鍋熸い蹇撶墛閻撴洟鏌曟繛鍨姕闁稿鍎查〃銉╂倷閹绘帗娈婚梺璇″枙缁瑥鐣峰鍫濈煑濠㈣泛顑嗛悵鏍⒒閸屾瑧鍔嶉悗绗涘吘娑欐媴缁涘姣庨梻鍌欑缂嶅﹪寮ㄩ崡鐑嗘富濞寸姴顑呴拑鐔兼煥濠靛棭妲归柛瀣姍閺屾稑鈻庤箛锝喰ㄩ梺瀹狀潐閻╊垶寮婚敐鍫㈢杸闁规儳澧庨澶愭⒑閼姐倕鏆€闁告侗鍘奸悘濠冪節閻㈤潧校闁肩懓澧界划濠氼敋閳ь剟寮婚妶澶婄畳闁圭儤鍨垫慨銏ゆ⒑閸涘鑰垮ù婊冪埣瀵鏁愰崱妯哄妳濡炪倖鐗楃划搴㈢墡闂傚倷绀侀幉锟犲箰婵犳碍鍋￠柕澶嗘櫆閸嬨倖銇勯幘鍗炵仾闁抽攱鍨块弻鐔烘喆閸曨偄顫岄梺鍛婅壘缂嶅﹪寮诲☉姘ｅ亾閿濆啫濡奸柍褜鍓氱换鍌烆敋閿濆洦瀚氭繛鏉戭儐椤秹姊洪棃娑氱濠殿喗娼欓悾鐢稿幢濞戞瑢鎷洪梻鍌氱墛娓氭鎮炴ィ鍐╃厱閹兼番鍊栭悵顏嗙磼閸屾稑娴柛鈺嬬節瀹曘劑顢欑憴鍕伖濠电姵顔栭崰姘跺箠閹捐秮娲Χ婢跺﹦鍔﹀銈嗗笂缁垛€斥枔濠婂應鍋撶憴鍕闁搞劌娼￠悰顔碱潨閳ь剟骞婂鍫燁棃婵炴垶顭囬崫搴♀攽閻樺灚鏆╅柛瀣仱瀹曞綊顢涢悙鎻掔€悷婊呭鐢偛鐣垫笟鈧弻鏇＄疀婵炴儳浜鹃柤纰卞墰閻ｇ偓淇婇悙顏勨偓鏍偋濡ゅ啯宕茬€广儱顦崥瑙勭箾閸℃ɑ灏伴柍閿嬪笒椤法鎹勯悮鏉戝闁轰礁鐗嗛埞鎴︻敊绾兘绶村┑鐐叉嫅缁插灝危閹版澘绠抽柟鍐茬－閸犳捇骞忛悩璇茶摕闁靛／鈧崑鎾绘倻濡偐鐦堥梺姹囧灲濞佳勭濠婂應鍋撳▓鍨灈闁绘牕銈搁崹楣冩晝閸屾氨鍊炲銈嗗坊閸嬫挾绱掗悩宕囧弨闁哄本娲濈粻娑㈠即閻愭劖绋掓穱濠囧箵閹烘柨鈪甸梺鍝勬湰濞叉繄绮诲☉銏犲嵆闁绘劖鍔戦崹浠嬪蓟閵堝绾ч悹鎭掑妺閾忓酣姊虹€圭媭娼愰柛銊ユ健瀹曟椽濡烽埡浣歌€垮┑掳鍊曢崯鈺呭传濡ゅ啰纾介柛灞剧懆閸忓瞼绱掗鍛仸闁靛棗鍟换婵嬪磼濠婂嫭顔曢梻浣侯攰閹活亞绮婚幋鐘典笉婵炴垯鍨洪悡鐔镐繆閵堝倸浜鹃梺缁橆殔濡鍩㈤幘缁樺亜闁稿繗鍋愰崢鍛婄節閵忥絾纭鹃柨鏇檮閺呭爼骞囬悧鍫㈠幐闂佸憡渚楅崰姘舵儗瀹€鍕厓鐟滄粓宕滃鍗炴瀳鐎广儱鎳愰弳鍡涙煙闂傚顦︾紒鐘崇墵濮婃椽宕归鍛壉婵犳鍨卞娆撯€旈崘顏佸亾閿濆簼绨婚柣锔哄妽娣囧﹤顔忛鍏肩亾缂備浇椴搁幑鍥х暦閹烘埈娼╂慨锝嗙懀閸ㄤ粙寮婚妸鈺佸嵆闁靛鍊濋崑妤呮⒑缂佹ü绶遍柛锝忕到閻ｅ嘲顫滈埀顒勩€佸▎鎾村殐闁宠桨绀佺粻鐗堢節閻㈤潧浠╅柟娲讳簽瀵板﹪宕稿Δ鈧壕鍧楁煏閸繃鍣抽柡瀣煥铻栭柨婵嗘噹閺嗙偤鏌嶉柨瀣伌闁哄瞼鍠栭幊鏍煛娴ｉ鎹曢梻浣告啞濮婂綊鏁冮姀銈呰摕婵炴垶鐟﹂崕鐔搞亜閺傚灝鎮戦柣婵囩箞閹鎲撮崟顒傤槰闂佹悶鍔屽锟犳偘椤斿槈鐔煎礂閻撳海褰撮梻浣藉亹閳峰牓宕滈敃鍌氳埞婵炲樊浜濋埛鎺懨归敐鍛暈闁诡垰鐗撻弻娑㈡偆娴ｉ晲鍠婇悗瑙勬礃閸旀牜鎹㈠┑鍡╂僵妞ゆ挾鍠愰悵顐ｇ節閻㈤潧孝闁挎洏鍊濆畷鏉款潩椤戦敮鍋撻幒鎾剁瘈婵﹩鍘鹃崢顏堟⒑閸撴彃浜濈紒璇插暣钘熼柣鎰暩绾惧ジ鏌嶈閸撶喖宕洪埀顒併亜閹烘垵顏柍閿嬪灴閺岋綁鎮㈤崨濠勫嚒闂佸搫妫楀畷顒冪亙闂佺粯顭堝▍鏇㈠磹閹邦厹浜滈柕蹇娾偓鍐叉懙闂佽桨鐒﹂崝鏍ь嚗閸曨倠鐔虹磼濡崵褰熷┑鐘垫暩婵敻顢欓弽顓炵獥婵°倕鎳庣粈澶愭煙閻戞ɑ顥嗗┑顔煎暱閳规垿鎮╁畷鍥舵殹闂佹娊鏀遍崹鍨潖婵犳艾閱囬柣鏃傚劋閸掓盯姊虹紒妯尖姇缂侇喖娴峰Σ鎰板箳閹惧绉堕梺闈涱煭婵″洭藝閵娾晜鈷戦柛婵嗗閸ｅ綊鏌ｉ弽褋鍋㈢€殿喖顭峰畷鍗炍旀繝鍌涘€梻浣虹《閸撴繈鎮烽妷鈺冨祦鐎广儱顦伴埛鎺懨归敐鍫燁棄闁告艾缍婇弻娑㈡偐閸愭彃顫屽銈庡幖閻忔繈锝炲鍫濈劦妞ゆ帒瀚ㄩ埀顑跨窔瀵噣宕奸锝嗘珝闂備線娼ф蹇曟閺囥垹鍌ㄩ柟鍓х帛閳锋垿姊婚崼鐔剁繁婵☆垰鐗撻弻娑㈠Ω閿曗偓閳绘洟鏌熼鈧粻鏍х暦瑜版帩鏁冩い鎰剁秵閸熷秹姊绘担铏瑰笡闁告梹娲栬灒濠电姴娲ょ壕鍧楃叓閸ャ劍鐓熷ù婊勭矋閵囧嫰骞樼€靛摜鐓€婵犳鍠栭崐濠氬焵椤掑喚娼愭繛鎻掔箻瀹曟繈骞嬮敂琛″亾娴ｇ硶妲堥柕蹇婂墲濞呮粓姊洪崫銉バｅ鐟版瀹曟垿濡堕崪浣圭稁婵犵數濮甸懝鍓у閸忓吋鍙忔慨妤€妫楅崢鎾煕鐎ｎ偅宕屾鐐寸墬閹峰懘宕妷顖滀覆闂傚倷绀佺紞濠偽涚捄銊х焼濞达絽鎼ˉ姘舵煟閻旂厧浜版繛鎾愁煼閹鏁愭惔婵堝嚬闂佸湱娅㈢紞渚€寮婚敐澶樻晣闁绘劖鎯屽Λ鐐烘⒑闂堟稒顥為悽顖涘浮閿濈偛鈹戠€ｎ偅娅滈梺鍛婁緱閸撴瑩藟濮橆兘鏀介幒鎶藉磹濡や焦鍙忛柣鎴ｆ绾剧粯绻涢幋鏃€鍤嶉柛銉墯閸嬨劎绱掔€ｎ亞浠㈤柣搴幗娣囧﹪濡惰箛鏇炲煂闂佸摜鍣ラ崑鍡欏垝鐠囨祴妲堟俊顖氱箰缂嶅﹪寮幇鏉垮窛妞ゆ柨鍚嬪▓妯荤節閻㈤潧浠滈柟鍐查叄閺佸啴濡舵径濠勫幋闂佺鎻梽鍕磻閹扮増鐓曟い顓熷灥娴滄繃鎱ㄩ敐鍛仾缂佺粯绻傞埢鎾诲垂椤旂晫浜鹃梻浣芥〃缁€渚€鈥﹂悜鐣屽祦濠电姴鍊甸弨浠嬫倵閿濆簼绨芥い锔诲弮閹嘲顭ㄩ崘顎囨寠閻斿憡鍙忔慨妤€妫楅崢鎾煛閳ь剚绂掔€ｎ偆鍘藉┑鈽嗗灥濞咃綁鏁嶅鍡愪簻闁挎繂妫涢崣鈧梺鍝勭焿缂嶄線鐛Ο灏栧亾闂堟稒鍟為柛锝勫嵆濮婃椽宕崟顒佹嫳闂佺儵鏅╅崹鍫曟偘椤斿槈鐔告媴閺囩喐顥堥柛鈹惧亾濡炪倖甯掔€氼剛绮婚悩璇茬閺夊牆澧介幃鑲╃磼閻樿櫕顥堥柡灞诲姂閹垽宕崟鎴秮閺屽秹鏌ㄧ€ｎ亞浠肩紓浣介哺閹稿骞忛崨瀛樺殐闁斥晛鍟悘鈺伱瑰鍐╁暈閻庝絻鍋愰埀顒佺⊕椤洭宕㈡禒瀣拺闁告劕寮堕幆鍫ユ煥閺囨ê鈧繈骞冨鈧弫鍌炴煥椤栨矮澹曞┑鐐茬墕閻忔繈寮搁敂濮愪簻闁哄洤妫楀ú銈夋偂閳ユ剚鐔嗛柤鎼佹涧婵洦銇勯銏″殗闁哄苯绉瑰畷顐﹀礋椤愮喎浜鹃柣鐔稿閺嬪秹鏌涢妷顔煎闁抽攱甯掗湁闁挎繂娲﹂崵鈧銈嗘礃缁海妲愰幒鏃€瀚氶柟缁樺坊閸嬫捇宕稿Δ鈧粻鏍喐閺傝法鏆﹂柛妤冧紳瑜版帒绾ф繛鍡欏亾绗戦梻浣哥枃椤宕归崹顔炬殾闁割偅娲栭悡娑㈡煕閹邦厼鍔ら柡鍜佸弮濮婄粯鎷呯粵瀣闁诲孩绋堥弲婵堝垝濞嗘挸绠虫俊鐐靛劦閸嬫捇鏁冮崒姘卞€炲銈嗗笂缁€渚€宕滆ぐ鎺撯拺闁革富鍘奸崝瀣叏婵犲懎鍚瑰瑙勬礃缁轰粙宕ㄦ繝鍕箺婵犵妲呴崹闈涒枍閿濆鏅€广儱鎷嬮悢鍡欐喐韫囨稑鏋侀柟闂寸閻掑灚銇勯幒宥囪窗闁哥喎绻橀弻娑㈡偐瀹曞洤鈷岄梺鐐藉劵缁犳捇骞冨鍫熷癄濠㈣泛顑囬埀顒夊墴濮婃椽宕烽鐑嗘毉濠电姰鍨洪敃銏ゅ蓟鐎ｎ喖鐐婃い鎺嶈兌閸橆亪妫呴銏℃悙妞ゆ垵鎳橀幃姗€顢旈崨顖滅槇闂侀潧绻嗛埀顒€纾导灞解攽椤旂》鍔熺紒顕呭灦楠炲繘宕ㄩ婊堚攺闁诲函缍嗛崑鍡欑矓閻戣姤鈷掑ù锝勮閻掔偓鎱ㄥ鍫㈢暠闁宠绉瑰鎾閻樺灚鐓ｉ梻浣藉亹椤牓鎮樺璺虹？闁绘梹鎮舵禍婊勩亜閹捐泛鏋庨柣蹇ョ畵閺岋繝宕ㄩ鍛彋濠殿喖锕ュ浠嬬嵁閺嶎厽鍊烽柟缁樺笒椤酣姊绘担鍛婃儓闁瑰啿绻掗幑銏ゅ礋椤掑倻褰鹃梺鍝勬储閸ㄨ櫣鈧數濮撮…璺ㄦ喆閸曨厾鐣电紓鍌氱Т閿曨亜顕ｉ锕€绠涢柡澶婃健閸炲爼姊虹紒妯荤；婵＄偞甯″畷顐⑽旈崨顔规嫼濠殿喚鎳撳ú銈夋倿濞差亝鐓曢柕濞炬櫃閹查箖鏌熼姘伃妞ゃ垺鐩幃娆撴嚑閼稿灚鍟哄┑鐘垫暩閸嬬偤宕归鐐插瀭闁革富鍘剧亸鐢碘偓骞垮劚椤︿即鎮￠崘顏呭枑婵犲﹤鐗嗙粈鍫ユ煟閺冨倸甯剁紒鐘崇墵閺岋綁骞嬮敐鍡╂闂佺粯鎸婚惄顖炲蓟濞戞ǚ妲堥柛妤冨仧娴犫晝绱撴担椋庣瓘缂佺姵鎸搁～蹇撁洪鍕獩婵犵數濮撮崐姝岊杺闂傚倷绀侀幗婊勬叏閻㈠憡鍋嬮柣妯款嚙閽冪喖鏌曟繛鐐珔閸ユ挳姊虹化鏇炲⒉婵炲弶绮庣划璇差潩閼哥鎷洪梻鍌氱墛缁嬫挻鏅堕弴銏＄厱濠电姴鍊归崯鐐电磼閸屾氨效鐎规洘绮忛ˇ瀵哥棯閹规劖顥夐棁澶愭煥濠靛棙顥滅紒鑼额嚙闇夋繝濠傜墢閻ｆ椽鏌″畝瀣ɑ闁诡垱妫冮、娑橆煥閸涘拑缍佸铏圭矙濞嗘儳鍓梺缁樺釜婵″洨鍒掔€ｎ亶鍚嬮柛婊€鑳堕崣鍡涙⒑閸撴彃浜為柛鐘虫崌瀹曘垽骞栨担鐟扳偓鍨殽閻愯尙浠㈤柛鏃€宀搁弻娑㈡偆娴ｉ晲绨兼繛锝呮搐閿曨亜鐣风粙璇炬梹鎷呴崫鍕瑲闂傚倷娴囨慨銈夋晪濡炪倧绠掑Λ鍕祫闂佸綊妫块悞锕偹夐崱妤婄唵闁兼悂娼ф慨鍫ユ煟閹捐泛鏋戦柟渚垮妼铻栭柍褜鍓欒灋婵°倕鎳庨崙鐘崇箾閹存瑥鐏柣鎾跺枛閻擃偊宕堕妸锕€纰嶇紓浣哄珡閸ャ劎鍘垫繛鎾磋壘閻忔繃淇婇悾宀€纾肩紓浣诡焽缁犵偟鈧娲橀敃銏ゅ春閻愭潙绶炴慨婵嗘湰椤庢姊绘担绛嬪殭婵﹫绠撻敐鐐村緞婵炴帗妞介弫鍐磼濮樻唻绱卞┑鐘垫暩婵挳宕愭繝姘辈闁挎洖鍊归悡鐔兼煛閸愩劌鈧摜鏁崼鏇熺厱闁靛鍎遍埀顒€缍婃俊鐢稿礋椤栨氨鐤€濡炪倖甯掗崐鐢稿几閸℃绠鹃悗娑欘焽閻倕霉濠婂嫮鐭掗柨婵堝仩缁犳稑鈽夊▎鎰姃闂備線娼荤€靛矂宕㈡ィ鍐╁亗闁瑰墽绮埛鎴︽煕閿旇寮鹃柣鎺撳劤铻栭柣妯挎珪閸婃劗鈧鍠撻崝鎴︺€佸鈧慨鈧柍銉︽灱閸嬫捇鎮介崨濠備画濠电偛妫楃换鎰邦敂椤忓棛纾奸柍褜鍓熷畷濂稿Ψ閿旀儳骞愬┑鐐舵彧缁茶姤绔熸繝鍥ㄥ亗闁兼祴鏂侀崑鎾舵喆閸曨剛顦ㄥ┑锛勫仒缁瑥鐣峰ú顏勭劦妞ゆ帊闄嶆禍婊堟煙閸濆嫮效婵℃儳鍢查湁婵犲﹤瀚惌鎺楁煛瀹€鈧崰鏍х暦椤愶箑绀嬫い鎾愁槶閸庣敻寮诲☉婊呯杸闁规儳鐡ㄩ幏閬嶆⒑闂堟稒鎼愰悗姘嵆瀵偊骞囬弶鍨€垮┑鐐叉缁绘劗绱掗埡鍛拻濞达絽鎲￠幆鍫ユ煟椤撶儐妲虹紒杈╁仦缁楃喖鍩€椤掑嫮宓侀柛鎰靛枛椤懘鏌ｅ鍡椾簼闁哄倵鍋撻梻鍌欒兌绾爼宕滃┑瀣櫔婵犵數鍋涢幊宀勫磹閺団懇鈧棃宕橀鍢壯囧箹缁厜鍋撻懠顒€鍤┑鐘垫暩閸嬬姷浜稿▎鎾崇獥闁哄诞灞芥婵犵數濮电喊宥夊磻閸曨垱鐓曢煫鍥ㄦ礀鐢爼鏌嶈閸撴稓鍒掗鐐茬疄闁靛鍎欓弮鍫濈劦妞ゆ巻鍋撻摶鐐寸箾閸℃ɑ灏伴柛瀣ф櫊閹銈︾憗銈傚亾閳ь剟鏌￠埀顒佺鐎ｎ偆鍘撻梺鑺ッˇ浼此夊鍏犵懓顭ㄩ崟顓犵杽闂佸綊鏀遍崹璺侯焽韫囨稑鐓涢柛鎰典悍缁辫尙绱撻崒姘偓鐑芥倿閿曞倵鈧箓宕堕‖陇娅ｉ埀顒傛暩绾爼宕戦幘鑸靛枂闁告洦鍓涢ˇ銉╂倵鐟欏嫭澶勯柛鎾寸箞閹﹢骞掑Δ浣叉嫼闂佸憡绋戦敃锔剧不閹剧粯鍊垫慨妯煎帶婢у弶銇勯敐鍕煓婵﹤顭峰畷鎺戭潩椤戣棄浜惧瀣捣閻棗銆掑锝呬壕濡ょ姷鍋涢ˇ鐢稿极閹剧粯鍋愰柤纰卞墻閸炲爼姊绘担铏瑰笡闁搞劎鍘ц灋闁告洦鍘介崗婊堟煃瑜滈崜鐔奉潖閾忚鍠嗛柛鏇ㄥ亜婵鈹戦埥鍡椾簻閻庢凹鍠氶崚鎺撶節濮橆剙鍞ㄩ梺闈涱焾閸婃绮诲鑸碘拺闂傚牊绋撴晶鏇㈡煙閸愭煡鍙勭€殿喗濞婇幃娆撴倻濡厧骞堥梻浣虹帛閿氱€殿喖鐖艰棢闁靛繈鍊栭悡娑㈡倶閻愭彃鈷旀繛鎻掝嚟閳ь剚顔栭崰妤呭箰閾忣偂绻嗛柟闂寸鍞梺闈涱樈閸犳绂嶉妶鍥╃＝闁稿本鐟ㄩ崗宀勬煕鐎ｎ偅灏い顓炵仢铻ｉ柤娴嬫櫇閻撳姊洪崷顓℃闁哥姵鐗犻幃鈥愁潨閳ь剟寮婚悢鍛婄秶闁告挆鍛闂備胶绮幖顐ゆ崲濠靛钃熸繛鎴欏灩閻掓椽鏌涢幇鍓佺窗婵炲矈浜炵槐鎾存媴闂堟稑顬堥梺闈涚墢椤牓锝炶箛鎾佹椽顢旈崨顓燁吋闂備線娼ч悧鍡涘箠韫囨挃鎺楀箛閻楀牃鎷洪梺鍛婄箓鐎氼參宕抽挊澶嗘斀妞ゆ棁鍋愭禒娑氱磼瀹€鍐摵缂佺粯绻堝畷鎯邦槾妞ゆ梹甯掗—鍐Χ閸℃﹩姊块梺绋款儐閸旀瑨妫熼梺闈涱焾閸庡搫銆掓繝姘厪闁割偅绻冮ˉ鐐烘煟閹惧崬鍔滃ǎ鍥э躬楠炴捇骞掗弬搴撳徍濠电姷顣介崜婵嬪箖閸岀偛鏄ラ柨鐔哄Т绾惧吋绻濇繝鍌氭殭濠碘€虫处缁绘繈鎮介棃娴剁偤鏌涢妸銉ｅ仮妞ゃ垺宀稿浠嬵敇閻愯尙鈧參姊虹憴鍕靛晱闁哥姵甯″畷鎴﹀箻閹颁焦鍍甸梺缁樻尭妤犲摜鐚惧澶嬧拺閻犲洠鈧櫕鐝濈紓浣哄У閻楃娀鐛崘顭戠叆闁割偆鍠庡▓鐔兼⒑闂堟侗妲堕柛銊ㄦ閳ь剚淇哄Λ鍕煘閹达附鍊烽柤鎼佹涧濞懷呯磽娴ｈ棄绱︾紒顔界懇閻涱喗寰勯幇顓熸闂佺粯顭堢亸娆撳蓟閸儲鈷戠紓浣姑慨澶愭煕鎼存稑鈧繈骞冮敓鐘插嵆闁靛骏绱曢崢鎼佹⒑閸涘﹤濮€闁哄懏绮岄悾椋庝沪閸欍儳绠氱紓鍌欓檷閸ㄥ綊寮搁妶鍥╃＜閺夊牄鍔屽ù顔锯偓瑙勬礃鐢帡锝炲┑鍠版帒鈻庡鍛紙闂佸搫鑻粔鍫曞箟閹绢喖绀嬫い鎰╁€撻幃锝夋⒒娓氣偓閳ь剛鍋涢懟顖涙櫠閸撗呯＜闁艰壈娉涜闂佸搫鎳撻崺鏍箚閺冨牊鏅查柛銉㈡櫇閸?",
            "project_idea": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡▎鎴犫敍闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼宕滆绾惧ジ鏌ｅΟ鎸庣彧閻忓浚鍙冮弻锝夋晲婢跺鏆犵紓浣芥閺咁偆鍒掑▎蹇婃瀻闁绘劦鍓涚粔閬嶆⒒閸屾瑨鍏岄柛瀣ㄥ姂瀹曟洟鏌嗗鍛焾闁荤姵浜介崝蹇旀叏閹惰姤鐓忓璺烘濞呭棝鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡樺窛闁硅棄鍊圭换娑㈠礂閻撳骸顫屽銈庡幖濞硷繝骞冮悜鑺ュ亱闁割偒鍋呴敍渚€姊绘担鍛婃儓闁硅櫕鎸搁埢鏂库槈濠婂懍绨烽梻鍌欑閹测剝绗熷Δ鍛偍濡わ絽鍟弲顒佺箾閹存瑥鐏柣鎾跺枛楠炴牠骞栭鐐典化缂備礁顦遍弫濠氬蓟濞戙垺鍋愰柟棰佺劍閻や線姊虹拠鈥虫珯缂佺粯绻傞锝夊箻椤旇棄浜滈梺鎯х箺椤曟牠宕惔銊︹拻濞达絿鍎ら崵鈧梺瀹︽澘濡块柟骞垮灲瀹曟帡鎮欓弶鎴炵杺闁荤喐绮庢晶妤冩暜濡ゅ懏鍋傞柣鏃囧亹閸欐捇鏌涢妷锝呭缂佲偓閳ь剟姊虹€圭媭鍤欓柣妤佹崌瀵鏁嶉崟顏呭媰闂佸憡鎸嗛崟顐㈢仭婵犵數濮烽。浠嬪礈濠靛绠栭柛宀€鍋涢弸渚€鏌涘畝鈧崑娑氱矆閸垺鍠愰煫鍥ㄧ☉缁狙兠归悩宸剱闁抽攱甯掗湁闁挎繂鎳忛崯鐐烘煙椤栨氨澧﹂柡宀嬬秮椤㈡﹢鎮滈崱妯炪劑鎮楅崹顐ｇ凡闁挎洦浜滈悾鐑藉箛閻楀牆浜滈柡澶屽仦婵粙宕洪崨瀛樷拻闁稿本鐟︾粊鎵偓瑙勬礀閻忔岸骞堥妸銉ф殾闁搞儮鏅濋悞鍏肩箾閹炬潙鐒归柛瀣崌閺岀喖顢欓崗鐓庝淮閻庤娲栭悥濂搞€佸Δ鍛劦妞ゆ帒瀚崣濠囨煏婢跺棙娅嗛柣鎾存礃缁绘盯骞嬪┑鍡氬煘闂佸搫顑冮崐妤冩閹烘鍋愰柤濮愬€楅弳顐︽⒑鐠団€虫灍妞ゃ劌鎳橀崺銉﹀緞婵炵偓鐎诲┑鈽嗗灣閸樠勬叏濞差亝鈷掑ù锝堫潐閵囩喖鏌涘Ο鎭掑仮闁轰礁鍟撮弫鍌炴倷椤掑缍楅梻浣告贡閸嬫捇宕滃璺鸿Е閻庯綆鍠楅悡鏇熺節婵犲倸鏆欓柡鍡愬灲閺屾稑顫濋悡搴濆枈闂佽鍠楅〃鍛村煝閹捐鍨傛い鏃傛櫕娴滎亝淇婇悙顏勨偓銈夊储妤ｅ啫绀傛慨妞诲亾闁绘侗鍣ｅ畷姗€顢欑喊杈ㄧ秱闂備線娼ч悧鍡椢涘Δ浣侯洸婵°倕鎳忛悡娆撴煠閸︻厼顣肩憸鎶婂懐纾奸柟缁樺笚閸嬨儳鈧鍠涘▍鏇犫偓浣冨亹閳ь剚绋掗…鍥储娴犲鈷戠紓浣股戦悡銉╂煙閼恒儳鐭掗柟顖氭湰缁绘繈宕熼鐙呯床濠电姰鍨煎▔娑㈠嫉椤掑嫬鍚归柍褜鍓欓—鍐Χ閸℃鈹涚紓鍌氱С缁舵岸鐛弽顑句汗闁圭儤绻冮弲婵嬫⒑閹稿海绠撴繛灞傚姀閸婃挳姊婚崒姘偓椋庢濮橆剦鐒界憸鏃堝灳閿曞偆鏁囬柣妯垮皺缁涘繘姊洪崗鑲┿偞闁哄懐鍋為幈銊╁礃濞村鏂€闂佺粯锚绾绢參銆傞弻銉︾厓闂佸灝顑呴悘瀛樻叏婵犲偆鐓肩€规洖銈搁幃銏ゅ箒閹哄棗浜鹃柟鐑樺焾閻斿棛鎲告惔鈭舵椽鎮㈤悡搴ゆ憰闂佺粯姊婚崢褏绮堥崘顔界厾缁炬澘宕晶鐗堛亜閺冣偓鐢繝骞冨Δ鍐╁枂闁告洦鍓涢ˇ銉х磼閸撗嗘闁告瑥鍟撮悰顔藉緞閹邦剛顔掑銈嗘閸嬫劙藝娴煎瓨鈷戦悗鍦О閳ь兘鍋撻梺绋款儐閹稿墽妲愰幒妤€惟妞ゎ厽鍨靛▓顓烆渻閵堝簼绨婚柛鐔风摠娣囧﹪宕奸弴鐐茬獩濡炪倖鐗楃划鐘诲船閸洘鈷戦悹鍥ㄥ絻椤掋垽鏌涢幋婵堢Ш鐎规洘绮撻幃銏＄附婢跺﹥顓块梻浣筋潐閸庡吋鎱ㄩ妶澶婄柧闁哄被鍎查悡鏇熺箾閹存繂缍佺紒銊ャ偢閺岋繝宕掑Δ鈧禍楣冩⒒閸屾艾鈧兘鎳楅崼鏇炵；闁靛ň鏅涚壕鍧楀级閸碍娅呮い銉︾閵囧嫰骞橀崡鐐典患闂佸搫瀚ㄩ崕鐢稿蓟閵娿儮鏀介柛鈩冾焽椤﹂亶姊虹粙娆惧剱闁规悂绠栭獮澶愬箻椤旇偐顦板銈嗗笒閸嬪﹦妲愰銏♀拻濞达絽鎲￠崯鐐存叏婵犲倻绉虹€规洖缍婂畷绋课旈埀顒冪箽濠电偠鎻徊璺ㄦ兜閸洖鍑犻幖娣妽閻撴瑩鎮楅悽娈跨劸濞寸姵绮庨惀顏嗙磼閵忕姷浠╁銈庝簻閸熷瓨淇婇懜鍨劅闁炽儱纾鎴︽⒒娴ｈ鍋犻柛鏂跨焸閹儵鎮℃惔顔兼濡炪倖鍔х粻鎴濇纯闂備胶纭堕崜婵嬫偡瑜旈幆渚€宕奸妷锔规嫼濠殿喚鎳撳ú銈夋倶閸欏绠惧ù锝呭暱閸燁垰袙閸曨垱鈷掗柛灞剧懄缁佺増淇婂鐓庡闁诡喚鍋ら弫鍐磼濮樿京鏆梻浣侯焾閺堫剙顫濋妸鈺佹辈闁挎洖鍊归悡娆撳级閸儳鐣烘俊缁㈠櫍閺屾稓鈧綆鍋勬慨澶愭煃瑜滈崜娑㈠箠閹惧鐝跺┑鐘叉搐缁愭鏌″畵顔瑰亾闁哄妫冮弻鏇熺箾閻愵剚鐝曢梺鎶芥敱閸ㄥ潡骞冨畡鎵虫瀻闊洦鎼╂禒鑲╃磽娴ｆ彃浜鹃梺鍛婂姀閺傚倹绂嶅鍫熺厸闁搞儜鍕垫闂佺懓鍟跨换妯虹暦濡も偓椤劑宕奸悢鍝勫笚闁荤喐绮嶇划鎾崇暦濠婂牊鍋勫┑鍌氼槹缂嶅酣姊洪幆褏绠烘い顐㈩樀瀹曚即宕卞☉娆戝幈闂佸搫娲㈤崝灞剧濠婂啠鏀芥い鏃傝檸閻掗箖鏌嶇憴鍕伌闁糕斂鍎靛畷鍗烆渻閸撗呮晨闂備浇顕х€涒晠鎯岄鈧畷锟犲箮閻ｅ苯绁﹂棅顐㈡处缁嬫垹绮婚敐澶嬬叆闁哄啫娲﹂ˉ澶娒瑰鍕煉闁哄矉缍侀幃娆戔偓鐢电《閺嬫棃姊洪柅鐐茶嫰婢ь噣鏌涘Ο鑽ゅ缂佹梻鍠栧鎾閳锯偓閹疯櫣绱撴担鍓插創婵炲娲滅划濠氭偋閸稐绨婚梺鎸庢椤曆囨倶閿涘嫮纾奸柛灞炬皑鏍￠梺闈涚墳缂嶄礁鐣峰鈧崺鐐烘倷椤掆偓椤忓綊姊婚崒姘偓椋庢閿熺姴纾婚柛鈩冪☉绾剧粯绻涢幋娆忕仾闁搞倖鍔栭妵鍕冀閵娧€濮囧┑鐐叉噽婵敻濡甸崟顖氬唨闁靛ě鍛帓缂備胶鍋撻崕鎶藉Χ閹间礁钃熸繛鎴炵煯濞岊亪鏌涢幘妞诲亾婵℃彃鐗嗛埞鎴︽倷鐎涙ê鍓归梺闈╃秶缂嶄礁顕ｆ繝姘労闁告劏鏅涢鎾剁磽娴ｅ壊鍎愰悗绗涘啠鏋斿┑鐘崇閸婄敻鎮峰▎蹇擃仾缂佲偓閸愵喗鍋ㄦい鏍ㄧ☉濞搭噣鏌ㄥ┑鍫濅粶闁宠鍨垮畷鍫曞Ω瑜忚倴闂傚倷绀侀崯鍧楀箹椤愶箑纾圭憸鐗堝笚閸庡﹪鏌ｉ幇顔煎妺闁抽攱甯掗湁闁挎繂鐗婇ˉ澶愭煕濮橆剛绉洪柡灞剧洴閹晠宕橀幓鎺濇綍闂備礁鎲＄敮妤冩暜閹烘鍋╂繝闈涱儏閻掑灚銇勯幒鎴濐仼缂佺姵鐓￠弻鏇＄疀閺囩儐娼旈梺缁樻煥閸氬骞嗛悙鐑樺仭婵炲棗绻愰顏呫亜閺冣偓濞茬喎顫忕紒妯诲闁告稑锕ㄧ涵鈧┑鐘媰閸曞灚鐣跺銈庡幖閻忔繆鐏掗梺鍏肩ゴ閺呮瑧绮径鎰拺闁诡垎鍕洶闂佺顑呴崐濠氬箲閵忋倕骞㈡繛鎴炵懅閸橆亪姊洪崜鎻掍簼缂佽鍊块、鏃堫敆娴ｅ吀绨婚梺鍝勫€归娆徫熼埀顒勬⒑閸濆嫮鐏遍柛鐘崇墵楠炲啴宕稿Δ濠冩櫖濠电偞鍨佃ぐ澶愬传濡ゅ啰纾介柛灞剧懄缁佹澘顪冪€涙ɑ鍊愭鐐村灴瀹曟儼顦撮柡鍡畵閺岀喖鎮滃Ο铏逛憾闂佸搫顑呴柊锝夊蓟閻旇　鍋撳☉娆樼劷缂佺姵鎸婚妵鍕敆閳ь剟藝闂堟侗娼栫紓浣股戞刊鎾煟閻旂厧浜伴柛銈咁儔濮婃椽鎮℃惔锝囆ㄧ紓浣哄У閻楃姴鐣峰ú顏呭€烽柛婵嗗椤撴椽姊洪幐搴⑩拻缂侇噮鍨跺鏌ュ煛閸涱喒鎷洪梺绋跨箺閸嬫劙濡堕幘顔界厸濞达絽寮跺▍濠囨煛娴ｇ懓濮嶇€规洏鍎靛畷姗€寮婚妷銉ュ強闁诲氦顫夊ú姗€宕曟總鍢庛劑宕掗悙鎼濡炪倖甯掗ˇ顖涙櫠椤栫偞鐓忛柛銉戝喚浼冩繝娈垮枓閸嬫捇姊洪弬銉︽珔闁哥喍鍗宠棟闁绘鐗忕弧鈧紒鐐緲椤﹁京澹曢崸妤佺厱闊洦妫戦懓璺ㄢ偓娈垮櫘閸嬪﹤鐣烽幒鎴旀婵﹫绲鹃弫鐢告⒒娴ｇ儤鍤€闁告埃鍋撶紓浣插亾濞达絽婀遍々鏌ユ煙椤栧棌鍋撻柡鈧禒瀣厽婵☆垵顕х徊缁樸亜韫囷絽浜為柣銉邯楠炴垿骞囬褎顥夐梻渚€娼уΛ娆戞暜閹烘缍栨繝闈涱儛閺佸棗霉閿濆牜娼愰柛濠勫厴濮婄粯鎷呴崨濠冨創濡炪倖鍨靛Λ婵嬬嵁閹达箑鐐婃い鎺嗗亾闁藉啰鍠栭弻銊╂偄閸濆嫅銏⑩偓鐟版啞缁诲啴濡甸崟顖氭闁割煈鍠掗幐鍐⒑濮瑰洤鈧洜鈧碍婢橀～蹇涙惞閻熸澘顕ч梺鍝勬川閸犳劕顭块幒妤佲拺缂佸顑欓崕鎰版煙閸涘﹥鍊愰柍銉︽瀹曟﹢顢欓崲澹洦鐓曢柍鈺佸枤濞堟﹢鏌ｉ悢绋垮婵﹥妞介幃鈩冩償閳╁啯鐦ｉ梻浣虹帛閻楁洟濡剁粙璺ㄦ殾闁绘垶顭囩弧鈧梺鎼炲劀閸愩劎銈梻鍌欒兌缁垰顫忛懡銈嗗床婵犻潧鐗愭慨鎶芥偣閸パ勨枙婵炴挸顭烽弻鏇㈠醇濠靛浂妫￠柣蹇撶箳閺佸寮诲☉姘ｅ亾閿濆骸澧ù鐘轰含閳ь剝顫夊ú妯侯熆濮椻偓閿濈偛顭ㄩ崼婵堝姦濡炪倖甯掔€氼剟鎷戦悢鍝ョ闁瑰瓨鐟ラ悘鈺呮煟閹捐揪鑰块柡灞剧洴閳ワ箓骞嬪┑鍥╀壕濠电偛顕崢褔鎮ч幘璇茬畺婵°倐鍋撻柍缁樻崌瀹曞綊顢欓悾灞借拫闂傚倷绶氬鑽ょ礊閸モ晝绀婂ù锝呮憸閺嗭附绻涘顔荤盎闁绘帒鐏氶妵鍕箳瀹ュ顎栨繛瀛樼矋缁捇寮婚悢鍏煎€绘俊顖濇娴犳潙顪冮妶鍛畾闁哄懏鐩妴鍛附缁嬪灝绐涢柣搴㈢⊕鑿ら柟閿嬫そ濮婃椽宕ㄦ繝鍕ㄦ闂佹寧娲忛崕鎻掝嚗閸曨垰绀嬫い鏍ㄧ〒閸橀亶姊虹紒妯忣亪宕崸妤€浼犳繛宸簼閻撴瑦銇勯弬鍨倯闁稿鍎甸弻娑㈠煘閹傚濠碉紕鍋戦崐鏍暜閹烘柡鍋撳鐓庡籍闁糕晜鐩獮瀣晜閻ｅ苯骞堥梻浣瑰濡線顢氳閻涱噣寮介‖锛勬嚀椤劑宕奸姀銏℃瘒闂備礁鎼惉濂稿窗閺嶎厹鈧礁鈽夊鍡樺兊闂佸憡鍔曞Ο濠冨閸愵喗鈷戦柟瑙勫姇閸氬綊鏌涚€ｃ劌鈧繂顕ｆ繝姘╅柍鍝勫€告禍婊堟⒑閸涘﹦绠撻悗姘嚇閺佹劖寰勭€ｎ剙甯楅梻鍌欑閻忔繈顢栭崨瀛樺€堕柍鍝勫暟绾惧ジ寮堕崼娑樺婵炴惌鍠楅妵鍕閿涘嫧妲堥梺瀹犳椤︻垶鍩㈡惔銊ョ妞ゆ挾鍟橀悙娴嬫斀闁绘ê鐏氶弳鈺呮煕鐎ｎ偆娲存鐐诧攻閹棃濡搁妷褏鏋冩繝娈垮枟閵囨盯宕戦幘鍨涘亾濞堝灝鏋︽い鏇嗗洤鐓″璺号堥弸搴ㄦ煙鐎电啸婵℃彃娲缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎾村劅闁靛繆鏅滈鍕攽閻樿尙妫勯柡澶婄氨閸嬫挸螖娴ｇ懓寮块梺缁樺灱濡嫮澹曠紒妯肩闁瑰瓨鐟ラ悘顏堟煕鐎ｎ亶鍎旈柡宀€鍠栧畷婊嗩槾缂佲檧鍋撶紓鍌欐祰椤曆兾涘┑瀣摕闁绘柨鍚嬮埛鎺楁倵闂堟稑顥忔俊宸櫍閺屾盯鎮滈崱妤冧桓濠殿喖锕ュ钘壩涢崘銊㈡婵浜弳浼存⒒娴ｅ憡鍟為柟姝屽吹閹广垽宕煎┑鎰闂佸壊鍋呭ú鏍不閻熸噴褰掓晲閸涱厼杈呴梺褰掝棑缁垳鎹㈠☉娆愮秶闁告挆鍕还闂備胶鍎甸崜婵嬪蓟閵娾斁鈧箓宕堕鈧粻娑㈡煟濡も偓閻楀繘宕㈤柆宥嗙厵闁稿繗鍋愰弳姗€鏌涙繝鍐⒌闁诡喚鏁婚、鏃堝醇閻斿搫骞愰梻浣告啞缁嬫帒顭垮鈧幃锟犲箛閻楀牏鍘靛銈嗙墬缁嬫帡藟閸績鏀介柍銉ョ－閸╋絿鈧娲樼敮鎺楋綖濠靛鏁嗛柛灞惧閺嬫棃姊婚崒姘偓鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎娆戠┛闂傚倷绶氶埀顒傚仜閼活垱鏅堕崜褏纾奸柣妯挎珪鐏忣參鏌ｉ敐澶嬫暠缂佽櫣鏅划娆忊枎閻愵剛绉遍梻鍌欒兌閸嬨劑宕曢柆宥呯柈閻犳亽鍔忔慨鎶芥煏婢跺棙娅嗛柍閿嬪笒闇夐柨婵嗗椤掔喖鏌￠埀顒佸鐎涙鍘靛┑鐐跺蔼椤斿﹪鏌囬娑欏弿濠电姳鑳堕惌娆戔偓瑙勬礈閸犳牠銆佸☉姗嗘僵閺夊牄鍔庨崣鍕攽閻樺灚鏆╁┑鐐╁亾濠电偘鍖犻崶鑸垫櫈闂佺硶鍓濈粙鎺楀磻閸岀偟鍙撻柛銉ｅ妿閵嗘帡鏌涘▎鎰磳闁哄本鐩俊鐑藉箣濠靛﹤顏梺鍛婃尫閸楀啿顫忓ú顏呯劵闁绘劘灏€氭澘顭胯閸ㄩ亶濡甸崟顖毼╅柕澶涚畱濞堟姊虹拠鈥虫珝缂佺姵鐗曢悾鐤亹閹烘繃鏅濋梺闈涚墕濞诧箓宕靛畝鍕拻濞撴埃鍋撻柍褜鍓涢崑娑㈡嚐椤栨稒娅犻悗鐢电《閸嬫挸鈻撻崹顔界亪濡炪値鍘鹃崗姗€鐛崘顔碱潊闁靛牆妫楁禍妤呮煙閼圭増褰х紓宥呮瀹曨剝銇愰幒鎾嫽婵炴挻鍩冮崑鎾绘煃瑜滈崜姘辩矙閹存繄鏆ら柛鈩冾焽缁犳儳霉閿濆懎鏆遍柛鐔哄█瀵悂寮埀顒勫Φ閸曨垰绠婚悹铏规磪閵壯呮／闁硅鍔栭ˉ澶愭婢舵劖鐓ユ繝闈涙閸ｆ椽鏌熼姘卞ⅵ鐎殿喕绮欓弫宥夊礋椤撶媴绱冲┑鐐舵彧缁茶姤绔熸繝鍥х？闁规壆澧楅崑銊︺亜閺嶎煈娈斿褎褰冭彁闁搞儜宥堝惈闂佽鍠氶弲顐ゅ垝濞嗘垶宕夋い顓熷灦鏁堟繝纰夌磿閸嬫垿宕愰弽顓熷亱婵°倐鍋撴い顐ｇ箞婵℃悂鍩℃繝鍐╂珦濠电姷鏁告慨鏉懨洪敃鍌氱厱闁瑰濮风壕鍏笺亜閺嶃劎鈯曠紒鈧埀顒佺節閳封偓閸曨厼寮ㄩ梺鍝勬湰濞茬喎鐣烽崼鏇炵厸濞达綁鏀遍崟鍐磽閸屾瑧鍔嶆慨濠傤煼瀹曚即寮借閸ゆ洟鏌熺紒銏犳灍闁稿鍔欓弻锝夊閵忊晜娈扮紓浣稿船閸熷潡鍩為幋锔藉€烽柤鎼佹涧濞懷呯磽娴ｈ棄绱︾紒顔界懇閻涱噣寮介褎鏅濋梺鎸庣箓濞村倸煤閸涘﹣绻嗛柕鍫濈箳閸掍即鏌涢悤浣哥仸闁诡噯绻濆鎾閻樻鍟囬梺鍝勵槸閻楀棙鏅堕悾灞筋棜闁秆勵殕閻撱儲绻涢幋鐑嗙劷鐎涙繂顪冮妶搴″绩婵炲娲熼獮澶愬箻椤旇偐顦板銈嗗笒閸嬪棗危鐟欏嫪绻嗛柣鎰典簻閳ь剚鍨垮畷鐟懊洪鍛珖闂侀潧绻嗛崜婵嬪矗韫囨稒鐓冪憸婊堝礈閻旂厧钃熼柨婵嗘媼濞笺劑鏌嶈閸撴瑩鈥﹂崶顏嶆Ъ闂侀€涚┒閸旀垿寮崒鐐茬闁圭儤姊婚悾楣冩⒒娴ｈ櫣甯涢柛鏃撻檮缁傚秴顭ㄩ崼婵堝姦濡炪倖甯婇懗鑸垫櫠闁秵鐓涘〒姘搐濞呭秵顨ラ悙鏉戠瑨閾绘牠鏌嶈閸撴稓鍒掗敐鍛傛梹鎷呴悷鏉夸紟婵犳鍠楅〃鍛涘Δ浣规珷濠电姵纰嶉悡鐔兼煙閸濆嫮肖闁活厽鐟╅弻鈥崇暆閳ь剟宕伴弽顓犲祦鐎广儱顦介弫濠勭棯閹峰矂鍝烘慨锝咁樀濮婄粯鎷呴搹鐟扮闂佸湱顭堥…鐑藉箖閻戣姤鏅濋柛灞绢嚤閿曞倹鐓曢柡鍥ュ妼閻忕姷绱掗銏⑿ч柡灞剧洴婵＄兘骞嬪┑鍡忓亾瑜版帗鍎撻煫鍥ㄧ⊕閳锋帒霉閿濆牊顏犻柕鍡楋躬閺岋繝宕担椋庢晼閻庡灚婢橀敃顏勭暦缁嬭鏃堝焵椤掑嫭鍊块柛顭戝亖娴滄粓鏌熼悜妯虹仴闁哄鍊栫换娑㈠礂閻撳骸顫嶇紓浣虹帛閻╊垰鐣烽敐鍡欑彾婵犲灚鍔掔花浠嬫煕濞嗗繑鍤囨慨濠呮缁辨帒螣濞茬粯鈷栭梻浣侯焾椤戝棝宕濋弴銏″仼闁割煈鍋嗛悷褰掓煃瑜滈崜鐔兼偘椤曗偓瀵粙鈥栭妷銉╁弰妞ゃ垺顨婇崺鈧い鎺嶆缁诲棗霉閻樺樊鍎愰柛濠勬暬閺岋綁濮€閵堝棙閿悗娑欑箓椤啴濡舵惔鈥崇哗濠电偛顦板ú鐔肩嵁閹达箑绀嬫い鎴炲劤娴滀即姊洪崜鑼帥闁革綆鍠楃€靛ジ宕橀埡鈧换鍡涙煏閸繃鎼愰崯鎼佹⒑缁嬫鍎戦柛瀣枛瀵偊顢氶埀顒勭嵁閹烘嚦鏃堝焵椤掑嫭鍋傛慨妞诲亾闁哄瞼鍠愬蹇斻偅閸愨晩鈧秹姊虹粙娆惧剱闁告梹顨堝Σ鎰板箻鐎涙ê顎撻梺鍏肩ゴ閸撴繈宕归崸妤€钃熼柕濞炬櫓閺佸洭鏌曡箛濠冾€嗛柟鐤缁辨挻鎷呴崜鎻掑壈闁诲繐绻愰幊搴敊韫囨稑唯闁挎棁妗ㄧ花璇差渻閵堝棙灏靛┑顔芥尦瀹曘垽骞橀鐣屽幈闂侀潧艌閺呮繈鎮惧ú顏呯厸濞达絿顭堥弳锝団偓瑙勬礃鐢帡锝炲┑鍫熷磯闁绘垶蓱濮ｅ棝姊婚崒姘偓椋庢濮橆剦鐒界憸蹇涘箲閵忋倕閱囬柕澶堝劚閻庮厽绻濋悽闈浶ｇ痪鏉跨Ч瀹曟劙宕归瑙勬杸闂佺鏈喊宥夊疮閻愮儤鐓冮梺鍨儏閻忊晝绱掓潏銊ユ诞妞ゃ垺绋戦埥澶娾枎閹搭厽袣婵犵數濮幏鍐幢濡ゅ啯顕楃紓鍌欐祰妞村摜鏁悙鍝勭劦妞ゆ帒锕︾粔鐢告煕鐎ｎ亜顏╅棁澶嬨亜閺囨浜鹃梺鍝勭灱閸犳牠銆佸▎蹇婃瀻鐎广儱鎳夐崑鎾澄旈崨顔间痪闂侀€炲苯澧柍瑙勫灴閹瑩寮堕幋鐘辨闂備浇宕甸崯娆撳炊瑜嶉崑宥夋⒑閸涘娈橀柛搴㈠姇閵嗘帗绻濆顓犲帾闂佸壊鍋呯换鍐夊鍐ｆ斀妞ゆ柣鍔岄幊鎰婵傚憡鐓犻柤瑙勬緲閻撴劗鐥鐐差暢缂佽鲸甯￠、娆戝枈鏉堚晛鎮戦柣搴㈩問閸犳洜鍒掑▎鎰箚闁归棿鐒﹂弲鏌ユ煕閺囥劌骞樻繛澶婃健濮婂宕掑▎鎴犵崲濠电偘鍖犻崶銊︽珫闂婎偄娲︾粙鎴犵矆閸愵亝鍠愰幖鎼厜缂嶆牠鏌￠崶銉ョ仾闁抽攱甯掗湁闁挎繂鎳忛崯鐐烘煙椤栨氨澧﹂柡宀嬬秮椤㈡﹢鎮滈崱妯炪劎绱撴担鎴掑惈闁稿鍋熺划顓㈡偄閻撳海鍔﹀銈嗗笒鐎氼參宕戝Ο姹囦簻闁哄洦顨呮禍鎯旈悩闈涗沪閻㈩垽绻濋悰顔锯偓锝庡櫘閺佸洭鏌ｉ幇顓熺稇闁逞屽墻閸ㄨ泛顫忕紒妯诲閻熸瑥瀚禒鈺呮⒑缁嬪灝鐦ㄩ柛锝忕到椤曪綁骞撻幒鍡樻杸闁诲函缍嗘禍婊堝磻瀹ュ拋娓婚柕鍫濇婢ч亶鏌涚€ｎ剙浠遍柛鈺傜洴楠炴帡骞婇妸銉хШ闁轰焦鍔欏畷銊╊敊閸忓吋鐣奸梻鍌欐祰椤曟牠宕规导瀛樺亱闁规崘顕ч拑鐔兼煥閻斿搫孝闂佸崬娲﹂妵鍕箛閳轰胶浠奸梺鍐插槻椤戝顫忛搹瑙勫珰闁炽儱纾禒鈺呮煟鎼淬垻鐓柛妤佸▕婵″瓨鎷呯化鏇燁潔濠殿喗顨呭Λ娆撳磽閻㈠憡鈷戠紓浣股戠亸顓㈡倵濞戞帗娅婃い銏★耿楠炴劖鎯斿┑鍫㈢暰闂備胶绮崝锔界濠婂牆鐒垫い鎺嶈兌婢ь亪鎮￠妶鍥ｅ亾楠炲灝鍔氭い锔诲灣婢规洘绻濆顓犲幍闂佸憡鎸嗛崨顓狀偧闂備胶绮幐璇裁洪悢鐓庤摕鐎广儱娲﹂崰鍡涙煕閺囥劌浜滃┑顔哄灪缁绘稓鈧稒顭囬惌宀勬煕鐎ｎ偅灏扮紒宀冮哺缁绘繈宕堕妸銉㈠亾闁垮浜滈煫鍥ㄦ尭椤忋倝鏌涚€ｎ偅宕岀€殿喕绮欓、鏇㈡晲閸℃﹩鍞堕梻鍌欑濠€閬嶅磿閵堝鈧啴宕ㄩ姘兼闂佽崵鍠愭竟瀣绩娴犲鐓熸俊顖濇閿涘秵銇勯敐鍡欏弨闁哄本绋掗幆鏃堝閳哄倻鏆︾紓鍌欒兌缁垶鎯勯姘辨殾闁告鍊ｉ悢鐑樺珰闁哄被鍎抽埀顒佹そ濮婄粯鎷呴搹鐟扮闂佸湱顭堥…鐑藉箖閻戣棄鐓涢柛娑卞弨閹芥洟姊洪幐搴ｇ畵妞わ富鍨崇划璇测槈閵忊檧鎷婚梺鍓插亞閸犳捇鍩ユ径瀣ㄤ簻妞ゆ劦鍋傞柇顖涙叏婵犲懏顏犻柟椋庡█閹崇娀顢楅崒銈呮櫔婵犵數鍋涢悺銊у垝瀹€鍕亯闁绘挸瀵掗崵鏇炩攽閻樺磭顣查柡鍜佸墴閺屾盯寮村Ο鍝勵瀳婵炲瓨绮撶粻鏍蓟閵娿儮鏀介柛鈩冧緱閳ь剚顨呴湁婵犲﹤瀚粻鏍煏閸パ冾伃濠碉紕鍏樻俊鐤槻闁愁亞鏁诲娲传閸曨偒妲甸梺閫炲苯澧痪缁㈠弮瀵娊宕卞☉娆戝帗閻熸粍绮撳畷婊堟偄妞嬪孩娈炬繛鏉戝悑濞兼瑧绮绘繝姘仯闁搞儺浜滈惃娲煕閺冩挾鐣辨い顏勫暣婵″爼宕卞Δ鍐噯闂備胶顭堥敃銈囩礊婵犲偆鍤曢柟鎯版閻撴盯鏌涚仦涔呰偐鑺辩拠宸富闁靛牆妫欑亸鐢告煕鐎ｎ剙鏋戦柡鍛埣瀵挳濮€閿涘嫬骞楁俊鐐€ら崢浠嬪垂閸偅娅犻悗娑櫳戦崣蹇撯攽閻樻彃顏悽顖涚洴閺岀喎鐣￠悧鍫濇畻闂佸湱鍘х紞濠囧箖閻戣棄绠ユい鏇炴噹娴犲綊姊婚崒娆戝妽闁活亜缍婂畷娲礋椤栨艾鐎柡澶婄墐閺呮粓寮冲鍫熺叆闁绘柨鎼瓭闂佸搫顑勭欢姘跺蓟濞戙垹绠涢梻鍫熺⊕閻濐噣姊烘潪鎵槮闁稿﹤娼″璇测槈閵忊晜鏅濋梺闈涚墕閹冲繘鎮楃紒妯肩閻庢稒顭囬惌瀣亜閵娿儲鍤囬柍銉︽瀹曟﹢顢欓崲澹洦鐓曢柍鈺佸枤濞堟梻鎮伴懖鈺冪＝闁稿本鐟ㄩ崗灞解攽椤旂偓鏆€规洖缍婂畷绋课旈埀顒傜不閺嶃劎绠鹃柛鈩兠慨澶岀磼閳锯偓閸嬫捇姊绘担瑙勫仩闁稿寒鍨跺畷婵囨償閵娿儱鍋嶅銈呯箰閹虫劗寮ч埀顒勬⒑濮瑰洤鐏叉繛浣冲嫮顩锋繝濠傜墛閻撶喖鐓崶銊︹拻缂佺姷鍋熼埀顒冾潐濞叉鎹㈤崒鐑囩稏婵犻潧顑愰弫鍥煟閺傚灝妲诲ù鐓庨叄濮婄粯鎷呴悷閭﹀殝缂備浇顕ч崐鍧楃嵁婵犲洤绠涙い鎾跺枑閻濈兘姊洪幐搴㈩梿濠殿喓鍊濆畷锝堢疀閹绢垱鏂€闂佺粯蓱瑜板啴寮抽悙鐑樼厪闁搞儯鍔庣粻姗€鏌嶈閸撴繈锝炴径濞掓椽鏁冮崒姘憋紱婵犵數濮撮崯鈺冩崲閸℃稒鐓熼柟杈剧稻椤ュ宕鐐粹拺闂傚牊绋撴晶鏇㈡煙閸愯尙绠绘鐐差樀婵偓闁靛牆妫岄幏缁樼箾鏉堝墽鎮奸柣鈩冩瀹曢潧鈻庨幋鐘碉紲缂傚倷鐒﹂敋濠殿喖顦甸弻鐔肩嵁閸喚浼堝Δ鐘靛仜椤戝寮崒鐐村癄濠㈣泛顦遍弫楣冩⒑閼姐倕鏋戠紒顔肩灱缁棃寮堕幋鐘虫闂佸憡娲﹂崹閬嶅煕閹达附鐓曢柨鏃囶嚙楠炴牗銇勯敐鍛倯缂佺粯绻堟慨鈧柍钘夋閸旈绱撴笟鍥ф灓缂侇噮鍨抽幑銏犫攽閸♀晜鍍靛銈嗘尵閸嬫劙宕戦幘璇插瀭妞ゆ劑鍊楅鏇㈡⒑閻熼偊鍤熼柛搴㈠姈缁傛帡鎮欓鍙ョ盎闂婎偄娲﹂幐鐐櫠闁秵鐓涘ù锝夘棑缁愭棃鏌″畝鈧崰鏍嵁閸℃凹妲诲銈忕到绾绢參鎯€椤忓牆绠查柟閭﹀弾濡嫰姊婚崶褜妯€闁哄被鍔岄埞鎴﹀幢濡儤顏犳俊鐐€戦崕杈╂崲濮椻偓瀵鈽夊▎鎰妳闂侀潧绻掓慨鎾綖閹烘鈷戦悹鍥ｂ偓铏亶濡炪們鍔岄悧蹇涘礆閹烘鏁囬柣鎰ㄦ櫆椤秴鈹戦埥鍡楃仯闁稿簺鍊曢埢鎾愁煥閸啿鎷洪梺鍛婄箓鐎氱兘宕曢幇顓濈箚妞ゆ劑鍨归弳锝嗩殽閻愭彃鏆㈤柕鍥ㄥ姍楠炴帡骞嬮悩娴嬪亾閻愮儤鍋℃繝濠傚暣閸欏嫰鏌涢埞鍨伈鐎殿喗鎸抽幃銏ゆ惞鐠団€虫櫗闂傚倷绀佸﹢閬嶅磻閹捐绀堟慨妯垮煐閸嬪倸鈹戦崒姘暈闁绘挻鐩幃姗€鎮欓棃娑楀缂備讲鍋撻悗锝庡厴閸嬫挾鎲撮崟顒傤槶闂佸憡顭嗛崶褏鍘撮梺纭呮彧缁犳垿鏌嬮崶顒佺厪闊洤锕ュ▍鍛存煛娴ｉ鐭欐慨濠勭帛閹峰懐绮电€ｎ亝顔勭紓鍌欓檷閸斿繘宕戦幇顒夊殫濠电姴鍟扮弧鈧┑顔斤供閸撴盯鏁嶅☉銏♀拺鐟滅増甯掓禍浼存煕閻樻剚娈滈柨婵堝仱瀵挳濮€閿涘嫬骞嶉梻浣虹帛閸ㄥ爼鏁冮埡浣叉灁闁靛繈鍊栭悡娑樏归敐澶嬩氦闂婎剦鍓熼弻鈥崇暆鐎ｎ剛袦闂佽桨鐒﹂崝娆忕暦閵娾晩鏁婇柤鎭掑劚椤忎即姊婚崒娆戠獢婵炶壈宕靛濠冪附缁嬭法顢呴梺瑙勫劶濡嫮绮婚弽銊ょ箚闁靛牆鍊告禍楣冩⒑瀹曞洨甯涢柟鐟版搐閻ｇ柉銇愰幒婵囨櫓闂佷紮绲介懟顖炴嫃鐎ｎ喗鈷掗柛灞剧懆閸忓本銇勯鐐靛ⅵ妞ゃ垺鐗犲畷銊╊敍濡も偓娴滅偓鎱ㄥ鍡椾簻鐎规挸妫濋弻鏇㈠幢閺囩媭妲柧浼欑秮閺屻倖鎱ㄩ幇顑藉亾濠靛棭鐎舵い鏂垮⒔绾捐棄霉閿濆懎顥忛柛搴㈡尰缁绘稒寰勭€ｎ偆顦伴悗瑙勬礃閸旀瑩骞冨▎鎾村€绘俊顖炴敱鐎氬ジ姊绘担鍛婅础妞ゎ厼鐗忛埀顒佺▓閺呯姾妫㈤梺绯曞墲鐪夌紒璇叉閵囧嫰骞囬埡浣轰患濡炪倕娴氭禍顏堝蓟濞戙垹绠抽柟鎼灡閺侀箖鏌ｆ惔婵堢シ闁稿鍔欓崺鈧い鎺嶈兌閳洟鎳ｉ妶澶嬬厵濡炲娴风敮娑氱磼缂佹鈯曟繛鐓庣箻瀹曟粏顦寸悮锝嗙節绾版ɑ顫婇柛瀣閳ь剚鍑归崹鍫曞Υ閸岀偛閿ゆ俊銈勮閹风粯绻涙潏鍓ф偧闁硅櫕鎹囬、姘煥閸涱垱锛忛梺鍝勵槼濞夋洘鏅ュ┑鐘殿暜缁辨洟寮拠鑼殾闁绘梻鈷堥弫宥嗙箾閹寸偟鎳勯柣婵囨礋濮婄粯鎷呯粙鎸庡€繛瀛樼矆缁瑥鐣烽弴銏犵闁芥ê顦遍ˇ鈺呮⒑鐠恒劌鏋斿┑顔炬暬閸╂盯骞嬮敂钘夆偓鐢告煕閿旇骞栨い搴＄焸閺屾盯濡堕崱娆愬櫘缂備浇椴哥敮妤€顕ラ崟顓濇勃闁诡垎鍕殮闂傚倷妞掔槐顔惧緤娴犲搴婇柡灞诲劵缂嶆牗绻濇繝鍌滃闁绘帒鐏氶妵鍕箳閹存繍浠撮梺閫炲苯鍘哥紒鈧笟鈧崺銏℃償閵娿儳顔掗梺鍝勵槹閸ㄦ娊骞冮敐澶嬧拺閻犲洩灏欑粻鎶芥煕鐎ｎ剙孝閾荤偤鏌涢弴銊ュ箻濞戞挸绉电换娑橆啅椤旇崵鍑归梺鎶芥敱鐢帡婀侀梺鎸庣箓濞层倝宕濈€ｎ喗鐓曢柕鍫濆€告禍楣冩⒒閸屾瑧顦﹂柟璇х節閹虫繃銈ｉ崘鐐櫈婵犮垼鍩栭崝鏇犵不閺嶎灛鏃堟晲閸涱厽鐏撻梺杞扮閸婂潡寮诲☉銏╂晝闁挎繂娲ㄩ悾濂告⒑閹稿海鈯曢柣鐔叉櫅椤繐煤椤忓拋妫冨┑鐐村灦閼归箖銆傚ú顏呪拺闁荤喐婢樺Σ缁樸亜閹存繍妯€妤犵偛鍟撮幃娆戔偓闈涘濞村嫰鏌ｆ惔顖滅У闁稿妫濆畷銏ゆ偨閸涘ň鎷洪柣鐔哥懃鐎氱兘宕箛娑欑厱闁绘ê纾晶鐢告煏閸℃鈧湱缂撴禒瀣窛濠电姴瀚獮妤呮⒒娴ｇ瓔娼愮€规洘锚閳绘柨鈽夐姀鐘插殤闂佺鎻梽鍕偂韫囨稒鐓曢柕澶嬪灥閸犳碍瀵奸崘銊庢棃鎮╅棃娑楁勃闂佹寧宀搁幗鍫曞冀椤撶喓鍘撻悷婊勭矒瀹曟粓鎮㈡搴㈡濡炪倖鐗滈崕鎰板极瀹ュ鐓熼柟閭﹀幗缂嶆垿鏌嶈閸撴瑩鎮ユ總绋胯摕闁绘梻鍘х粻姘辨喐瀹ュ鈧倸鐣烽崶鈺傦紡闂佺顫夐崝鏍夋径鎰厪闁糕剝锚缁楁帗銇勯锝囩疄妞ゃ垺顨嗛幏鍛喆閸曨偀鍋撻悜鑺モ拻濞达絽鎲￠幆鍫熴亜閹存繃顥犵紒顔界懇楠炴帒螖閳ь剚顢婇梻浣告啞濞诧箓宕规總绋挎瀬闁搞儺鍓氶悡鐔镐繆椤栨繍鍤欑紒鑼帛椤ㄣ儵鎮欏顔煎壈闁剧粯鐗犻弻锝咁潨閳ь剙顭囪缁傛帒顭ㄩ崼鐔哄幈闂佺粯妫冮ˉ鎾诲箺閻樼粯鐓欏〒姘仢婵倿鏌涢埞鎯т壕婵＄偑鍊栫敮鎺斺偓姘煎弮閹ょ疀濞戞艾褰勯梺鎼炲労閻忔帡宕奸妷銉э紱闂佽宕橀褏绮堥崒鐐寸厱婵炴垵宕悘锕傛煙缁嬭￥鍋㈡慨濠傤煼瀹曟帒顫濋钘変壕闁绘垼濮ら崵鍕煕椤愶絾绀€缁炬儳顭烽弻鏇熺箾閻愵剚鐝旂紒鐐劤濞尖€愁潖濞差亶鏁嗛柍褜鍓涚划鏃堝箻椤旇偐锛滈梺闈浥堥弲婊堟偂濞戞埃鍋撻獮鍨姎闁哥噥鍋呮穱濠囧锤濡や胶鍘藉┑鐘绘涧濡盯宕洪敐澶嬬厸鐎光偓鐎ｎ剛鐦堥悗瑙勬礀閻栧吋淇婇悜钘壩ㄧ憸宀勬儉椤忓牊鈷掑ù锝囨嚀閳绘洟鏌￠埀顒勬焼瀹ュ懎鐎梺绉嗗嫷娈旈柦鍐枛閺屾洟宕煎┑鍥舵！闂佸憡鐟ョ换姗€寮婚悢鍏肩劷闁挎洍鍋撻柛妯绘尦閺屾稓鈧綆鍋呭畷宀€鈧鍠楅幐铏叏閳ь剟鏌ｅΟ璇茬祷婵炲牄鍊濆缁樻媴閸涘﹥鍎撻梺绋匡工缂嶅﹪銆侀弽褉鏋庨柟鐐綑娴滄粓姊虹化鏇炲⒉闁荤噦绠撳畷浼村箛閺夎法顔愬┑鐑囩秵閸撴瑦淇婇幖浣圭厓鐟滄粓宕滃▎鎾崇柈闁哄鍨归弳锕傛煏婵炑€鍋撻柛瀣尭閳藉鈻嶉搹顐㈢仴闁宠绉瑰畷鍫曨敆娴ｅ弶瀚奸梻鍌氬€搁悧濠勭矙閹惧墎涓嶆慨妯垮煐閻撳啰鎲稿鍫濈婵娉涚粈鍫熸叏濡寧纭鹃柛姘秺閺屾洟宕煎┑鎰ч梺缁樻尵閸犳牠鐛弽顬ュ酣顢楅埀顒勬倶椤曗偓閺屽秹顢涘☉娆戭槰闂侀潧娲ょ€氫即銆佸鈧幃娆撳级閹寸偟浜烽梺璇叉唉椤煤韫囨稑鍨傚ù鐘差儏閽冪喖鏌涢埄鍐炬闁告艾顑夐弻娑㈠灳瀹曞洨顔夐柣搴㈣壘閵堢顫忔繝姘＜婵﹩鍏橀崑鎾诲箹娴ｇ懓浜辨繝鐢靛Т閸熶即鎮风憴鍕箚闁靛牆鎳忛崳娲煕鐎ｎ亜鈧綊濡甸崟顖氱閻犺櫣娲呴妷褏妫柟顖嗕礁浠梺鍝勭焿缁插€熺亽闂佸憡绻傜€氼厼袙閹扮増鈷戦悹鍥皺缁犵増銇勯弴銊ュ籍闁糕斁鍋撳銈嗗笒閸犳艾顭囬幇顓犵閻犲泧鍛殼閻庤娲橀崹鍓佹崲濠靛鐐婄憸蹇涱敊閹扮増鍋℃繝濠傛噹椤ｅジ鎮介娑樼缂侇喖鐗撳畷鎺戭潩閼测晛鏁搁梺鑽ゅЬ濞咃絿浜搁妸銉綎婵°倐鍋撴い顓℃硶閹叉挳宕熼鍌ゆК闂備礁鐤囬～澶愬垂閸ф绠栨繛鍡樻尰閸ゆ垶銇勯幒鍡椾壕濡炪倧绲惧钘夘潖閾忚瀚氶柤纰卞墰椤斿绱撴担绛嬪殭闁绘妫濋、姘舵晲閸モ晝鐓撻柟鐓庣摠閹稿鎮楁繝姘拺闁荤喖鍋婇崵鐔封攽椤旀儳鍘撮柡浣哥Т椤劑宕橀悙顒€鐦滈梻渚€娼ч悧鍡椢涘▎鎾崇厱闁圭儤顨嗛悡娑㈡煕濠娾偓缁€浣圭閻楀牜娈介柣鎰嚋闊剛鈧娲橀敃銏ゃ€佸▎鎾村仼閻忕偠妫勭粻娲⒒閸屾瑧鍔嶉悗绗涘懏宕查柛灞绢嚔濞差亜围濠㈣泛锕ら崑宥夋煟鎼淬垻鈯曢柨鏇楁櫅閳绘挻绂掔€ｎ偆鍘介梺褰掑亰閸撴瑧鐥閵囧嫰濡烽敐鍛紙闂佸搫鐭夌槐鏇熺閿曞倹鍤嶉柕澶堝劜閻忓酣姊绘担鑺ャ€冪紒鈧笟鈧畷鎰板垂椤旂偓娈鹃梺鎸庣箓椤︿粙寮崘顔界厽闁哄倹瀵ч崯鐐烘煟濠靛洦绀堢紒?",
            "project_adaptation": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡▎鎴犫敍闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼宕滆绾惧ジ鏌ｅΟ鎸庣彧閻忓浚鍙冮弻锝夋晲婢跺鏆犵紓浣芥閺咁偆鍒掑▎蹇婃瀻闁绘劦鍓涚粔閬嶆⒒閸屾瑨鍏岄柛瀣ㄥ姂瀹曟洟鏌嗗鍛焾闁荤姵浜介崝蹇旀叏閹惰姤鐓忓璺烘濞呭棝鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡樺窛闁硅棄鍊圭换娑㈠礂閻撳骸顫屽銈庡幖濞硷繝骞冮悜鑺ュ亱闁割偒鍋呴敍渚€姊绘担鍛婃儓闁硅櫕鎸搁埢鏂库槈濠婂懍绨烽梻鍌欑閹测剝绗熷Δ鍛偍濡わ絽鍟弲顒佺箾閹存瑥鐏柣鎾跺枛楠炴牠骞栭鐐典化缂備礁顦遍弫濠氬蓟濞戙垺鍋愰柟棰佺劍閻や線姊虹拠鈥虫珯缂佺粯绻傞锝夊箻椤旂⒈娼婇梺鎸庣☉鐎氼剛鏁Δ鍛拻濞达絽鎽滈弸鍐╀繆濡炵厧濡跨紒顔肩墛缁楃喖鍩€椤掆偓椤曪綁骞庨懞銉ヤ簻闂佺绻楅崑鎰板储閹剧粯鈷戦柤鎭掑剭椤忓煻鍥寠婢光晝鍠栭崺鈧い鎺戝閳锋垿鏌涘┑鍡楊仾婵犫偓娴煎瓨鐓熼柍鍝勶工閻忊€城庨崶褝韬鐐寸墬閹峰懘鎳栧┑鍕闁哄本娲樺鍕醇濠靛牅鎮ｅ┑鐐茬摠缁挾绮婚弽顓炶摕婵炴垶绮犲Σ鐓庮渻閵堝啫濡奸柣妤€妫濋幃楣冨垂椤愩倗鎳濋梺閫炲苯澧寸€殿喖顭烽崹楣冨箛娴ｅ憡鍊梺纭呭亹鐞涖儵鍩€椤掑啫鐨洪柡浣圭墱缁辨挻鎷呴崫鍕闂佺瀛╂繛濠冧繆閸洖绠瑰ù锝嗙摃閹芥洟姊洪幐搴ｇ畵闁瑰弶锕㈠顕€宕煎┑鍫濆Е婵＄偑鍊栫敮鎺斺偓姘煎弮瀹曟垹鈧綆鍠楅悡鏇㈡煃閳轰礁鏆㈡繛澶嬪絻椤潡鎳滈棃娑橆潓缂備胶濮甸惄顖炲蓟閿濆憘鏃堝焵椤掑嫭鍋嬮煫鍥ㄧ☉閸屻劑姊洪鈧粔鐢告偂閻旂厧绠归柟纰卞幖閻忥絿绱掓径灞炬毈闁哄本绋撻埀顒婄秵娴滄繈宕宠ぐ鎺撶厽闁挎繂顦藉Λ鎴澝归悪鍛洭缂佽鲸甯℃慨鈧柍钘夋閺咁剟姊婚崒娆掑厡缂侇噮鍨跺畷婵嬪冀瑜滈悞鑺ョ箾閸℃ê鐏╃紒鐘虫閺岀喖鎮滃鍡樼暦闂佺娅曞畝鎼佸蓟閳ユ剚鍚嬮幖绮光偓宕囶啈闂備胶绮幐鎼佸疮娴兼潙绠熺紒瀣儥閻撱儵鏌涢锝囩畼妞わ富鍘奸埞鎴︽倷閸欏妫￠梺鐟扮毞閺呯姴顕ｉ锝囩瘈闁搞儮鏅涜ぐ鍕⒑閹肩偛鍔橀柛鏂跨Ф娴滄悂濡搁埡鍌滃幐闂侀€炲苯澧紒鍌涘笧閳ь剨缍嗛崑鍡涘储闁秵鈷戦梻鍫熶緱濡狙呯磼闊厾鐭欑€规洘绻傞埢搴ㄥ箣閻樼绱查梻渚€娼ч…鍫ュ磿濞差亝鍋傞柛蹇撳悑閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濞€閺岀喖宕ｆ径瀣攭閻庤娲滈崰鏍€侀弴銏犖ч幖绮规嚕閻愭祴鏀介柣妯虹仛閺嗏晠鏌涚€ｎ偆娲撮挊婵喢归悡搴ｆ憼闁稿骸瀛╅妵鍕冀閵娿儱姣堥梺鎼炲€栧ú鐔煎蓟閻斿吋鈷掗悗闈涘濡差喚绱撴担鍝勵€撶紓宥勭窔瀵濡搁埡浣虹潉闂佺鏈粙鎺楁偟椤忓牊鈷戦柛娑橆煭閼板灝霉濠婂棙纭炬い顐㈢箻閹煎綊宕烽鐙呯床婵犵妲呴崹鏉棵瑰顓狀洸闁绘劕顕悵鍫曟煛閸ャ儱鐒洪柡浣告喘閺屾洝绠涢弴鐐愩儵鏌涘Ο璇插婵﹥妞藉畷顐﹀礋椤掆偓缁愭稒绻濆▓鍨珝妞ゃ儲鎸荤粩鐔煎即閵忊€虫異闂佸啿鎼崯浼存晬濠靛洨绠鹃弶鍫濆⒔缁夘剚銇勯弴鐔哄⒌闁诡喚鍋炵粋鎺斺偓锝庡亞閸橆亪姊虹化鏇炲⒉闁挎碍绻涢幖顓炴珝闁哄矉绱曟禒锕傛偩鐏炴縿鍎查妵鍕槺缂佽埖宀稿璇测槈閵忕姷顔掗柣搴㈢⊕椤洤鈻撻妶鍥╃＝濞撴艾娲ら弸鐔兼煟閻斿弶娅婇柣娑卞櫍楠炴帡骞嬮鐔风槣闂備胶绮崹鐔煎疾濞戞瑧顩插Δ锝呭暞閻撱儵鏌￠崶鈺佷粶闁逞屽墯閹倿骞冨▎鎰瘈闁告劧缂氱花濠氭⒑閻熺増鎯堢紒澶婄埣钘濋柨鏇炲€归悡鏇㈡煙閹咃紞缂佸妞介弻鈥崇暆鐎ｎ剛蓱闂佽鍨卞Λ鍐€佸☉姗嗙叆闁告稑鎷戠紞浣割潖濞差亜宸濆┑鐘插暙闂夊秶绱撴担鍓插剱闁规瓕宕电划鈺呮偄閻撳骸宓嗛梺缁樻⒐濡炶棄顬婇鈧娲川婵犲嫧妲堥梺鎸庢磸閸婃繈宕洪埀顒併亜閹烘垵鈧綊寮抽鍕厸閻忕偠顕ф俊濂告煃鐟欏嫬鐏寸€规洖宕埥澶愬箥娴ｉ晲澹曞┑掳鍊愰崑鎾绘婢跺绡€濠电姴鍊搁顐ょ磼閻橀潧浠遍柡宀€鍠栭、娆戠驳鐎ｎ剙濮肩紓鍌欒兌婵敻鎯勯姘煎殨闁圭虎鍠楅崑鍕煕濞戞﹫鍔熸俊鍙夘殜濮婂宕掑▎鎴М闂佸湱鈷堥崑濠傤嚕閻㈠壊鏁嗛柛鏇ㄥ墮閸擃喖顪冮妶鍡欏⒈闁稿鍠庨悾鍨瑹閳ь剟寮婚悢鍏煎€绘慨妤€妫欓悾鍓佺磽娴ｅ搫孝妞ゎ厾鍏樺鏄忣樁缂佺姵鐩弫鎰板川椤掆偓閸ら亶姊绘担鐣屾瘒闁稿本绮犲Σ顕€姊虹€圭媭娼愰柛銊ユ健楠炲啴鍩℃担鍙夌亖闂佸湱顭堢€涒晠鎯佸鍫熲拻濞达絽鎲￠崯鐐烘煙濮濆苯鍚归柟骞垮灲瀹曞ジ濡疯缁侊箓姊洪崨濠傚Е闁哥姵鐗滄竟鏇熺附閸涘﹦鍘介梺褰掑亰閸撴瑧鐥娣囧﹤顔忛鐓庘拫濠殿喖锕ュ钘夘嚕椤掑嫬唯闁挎梻鏅ぐ鍛存⒒娴ｅ憡鎲搁柛锝冨劦瀹曞綊鏌嗗鍛槴婵犵數濮寸€氀囧磻閹剧粯顥堟繛鎴炵懄閸犳劗绱掗悙顒€鍔ら柕鍫熸倐楠炲啫螖閸涱喗娅滈柟鑲╄ˉ閳ь剝灏欓惄搴繆閻愵亜鈧牕煤濡厧鍨濈€广儱顦闂佸憡娲﹂崹鎵不婵犳碍鐓欏Λ棰佹祰閸忓矂鏌涘顒夊剰闁宠鍨块、娆戞兜瀹勯绱ｆ俊鐐€ら崢濂稿床閺屻儲鍋╅柣鎴ｆ缁犳娊鏌熺€涙ɑ鈷愰柣搴☆煼濮婅櫣鎲撮崟顒€鍓归梺鍛娒埀顒傚暱閸欐椽姊婚崒姘偓鎼佸磹瀹勬噴褰掑炊椤掑﹦绋忔繝銏ｆ硾閻ジ鎯岄崼銉︾厵缂備降鍨归弸娑㈡煟閹烘垹浠涢柕鍥у楠炴帡骞嬪┑鍥啀闁荤偞鐔粻鎴﹀煘閹达附鍊烽柛娆忣槴閺嬫瑦绻涚€涙鐭嬬紒璇茬墕椤曪綁骞撻幒婵堝弳闂佸壊鍋嗛崰鎾诲储娴犲鈷戦柟绋挎捣缁犳捇鏌熼搹顐㈠闁诡喚鍋ら幃娆擃敆閸屾粠鍟庨梻浣告啞閻熴儵藝娴兼潙纾归柟閭﹀幗閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濮风槐鎺撴綇閵娿儳鐟ㄩ柧浼欑秮閺屾稑鈹戦崱妤婁紝濠电偛鍚嬪ú鐔奉潖缂佹ɑ濯撮柤鎭掑劘閳ь剙鍟扮槐鎺楀焵椤掍胶鐟归柍褜鍓熼悰顔藉緞閹邦厽娅栭梺鍛婃处閸橀箖鎮￠幘瀵哥瘈闁靛骏绲剧涵鐐亜椤撗冨⒋鐎规洏鍎抽埀顒婄秵閸犳鎮￠弴鐔稿弿婵☆垳顭堥崝姘舵煃瑜滈崜姘哄鍛潟闁绘劕顕弧鈧梺鎼炲劀閸涱垱姣囬梻鍌欑閻ゅ洤顩奸妸褎顐介柨鐔哄Т閻ゎ噣鏌涘☉鍗炴灁濞存粍绮撻弻锟犲礃閵娿儮鍋撻崫銉︽殰閻犺桨璀﹂悢鍡涙煟閻旂厧浜版俊顖楀亾婵犳鍠栭敃锔惧垝椤栫偛绠柛娑樼摠閹偤鏌ｉ悢绋款棆妞ゆ劕銈稿缁樻媴閸涘﹨纭€濡炪値鍘奸悧鎾诲灳閿曞倹鍊婚柦妯侯槺閻ｆ椽姊虹紒妯虹伇婵☆偄瀚伴幃鈥斥槈濡硶鍋撻幒鎴僵妞ゆ帊绀侀ˇ鈺冪磽閸屾氨孝閻庢稈鏅濋幑銏犫攽鐎ｎ偄浠洪梻鍌氱墛閸掆偓闁挎繂顦伴悡鐘垫喐閻楀牆绗ч柣锝嗘そ閺岀喖顢欓幆褌妲愰悗瑙勬礀缂嶅﹪銆侀弴銏″亹閺夊牃鏅濆▔鍧楁⒒閸屾瑧顦︽繝鈧柆宥呯？闁靛牆顦崹鍌炴煟閵忕姴顥忛柡浣稿€块弻宥夊传閸曨偅娈剁紒鐐劤閵堟悂寮婚敐鍛傜喖鎼归惂鍝ョ闂備焦鍓氶崹鍗灻洪悢鐓庤摕闁哄洢鍨归悙濠勬喐瀹ュ鏁傛い鎾跺櫏濞堜粙鏌ｉ幇顔界厪妞ゅ繐娲ㄦ禍娆撴⒒娓氣偓閳ь剛鍋涢懟顖涙櫠娴煎瓨鐓冪憸婊堝礈濮樿埖鍎嶆繝濠傜墕閻愬﹦鎲稿澶婂惞闁硅揪闄勯埛鎴︽煕閹炬潙绲诲ù婊勭墵閺屾盯濡搁妸銉ユ優婵犮垼顫夊ú妯肩矉閹烘柡鍋撻敐搴′簽闁告﹢浜堕弻锝堢疀閺囩偘娌悗瑙勬礃钃辩紒鏃傚枎椤粓鍩€椤掑嫬钃熺€广儱鐗滃銊╂⒑閸涘﹥灏伴柣鈺婂灠閻ｅ嘲螖閳ь剟锝炲鍫濈劦妞ゆ帒瀚畵渚€鏌涢幇闈涙灍闁稿﹦鍏橀弻锝夊箣閻愬棙鍨甸埢宥夊炊椤掍讲鎷虹紓浣割儐鐎笛冿耿娴煎瓨鍤曢柕鍫濐槹閻撴洟鎮楅敐搴′簼鐎规洖鐬奸埀顒冾潐濞叉﹢鏁冮姀銈冣偓浣糕枎閹炬潙浜楅柟鑹版彧缁插灝鐣烽崫鍕ㄦ斀闁绘ɑ鍓氶崯蹇涙煕閻樻剚娈樼紓鍌涙崌瀹曠螖閳ь剛澹曡ぐ鎺撶厸闁搞儮鏅欑槐铏箾瀹割喕鎲鹃柡浣告喘閺岋綁骞囬鍌傦綁鏌ｉ埡濠傜仩闁伙絽鍢查～婊堝焵椤掍椒绻嗛柟闂寸椤懘鏌嶉挊澶嬵棡缂傚秴鑻埞鎴︽偐閹颁礁鏅遍梺鍝ュУ椤ㄥ﹪寮崘顔肩厸闁告侗鍘奸崑宥嗙箾鐎电孝妞ゆ垶鍔欏顐ｇ節閸ャ劎鍘搁梺鎼炲劗閺呮盯寮搁弮鍌滅＜闁抽敮鍋撻柛瀣崌濮婄粯鎷呴崷顓熻弴闂佹悶鍔忓Λ鍕€﹂崶顏嶆▌闂佺硶鏂傞崹钘夌暦婵傚憡鍋勯柧蹇氼嚃閸熷骸鈹戦悙鑸靛涧缂佽弓绮欏畷顖炲垂椤旀艾缍婂畷鎺楁倷閸欏鈧剟姊洪崨濠冨闁搞劑浜堕幃锟犲即閻橆偄浜鹃柛蹇擃槸娴滈箖姊洪柅鐐茶嫰婢у鈧娲橀崹鐢稿煡婢舵劕顫呴柍銉︽灱閸嬫捇宕稿Δ浣哄幈濡炪値鍘介崹鍨閺嶎灐鐟邦煥閸曨厾鐓夐梺鍝勭灱閸犳牠骞冨鍏剧喖鎼归悷鏉跨瑢闂傚倷绀侀幉鈥愁潖婵犳艾绐楅柡宥庡幖閽冪喖鏌ㄥ┑鍡╂Ч闁哄懏鐓￠弻娑樷槈閸楃偟浠х紓渚囧櫍濞佳団€旈崘顔嘉ч柛鎰╁妼鎯熼梻浣侯焾濞寸兘寮繝姘卞祦闁告劑鍔夐弸搴ㄦ煙閹咃紞濡ょ姴娲娲偡闁箑娈堕梺绋款儑婵炩偓闁诡垰鍊圭粭鐔煎焵椤掑嫬钃熼柨婵嗘閸庣喖鏌曡箛濠冩珔闁哄懘浜跺娲閳哄啰校闂侀潻缍囩徊浠嬫偩閻戣棄绠柤鎭掑劜濞呮粓姊洪崨濠佺繁闁搞劌宕埢鎾淬偅閸愨斁鎷洪梺闈╁瘜閸樺ジ宕濈€ｎ偁浜滈柕濞垮劜閸ｈ绻涢幓鎺撳仴婵﹦绮幏鍛村川婵犲啫鏋戝┑鐘愁問閸ｏ絿绮婚弽褏鏆︽繛宸簻閻愬﹥銇勯幒鍡椾壕缂佺偓鍎冲鈥愁潖婵犳艾閱囬柣鏂垮缁讳礁鈹戦悙鎻掓倯闁绘娲熼崺鐐哄箣閿旇棄浜归柣搴℃贡婵挳藟濠靛牏纾奸柣鎰靛墮閸斻倝鏌涘顒夊剳闁瑰箍鍨归埥澶愬閻樿尪鈧灝鈹戦埥鍡楃仴婵炲拑缍佸畷婵堢矙鎼存挻鏂€闂佺偨鍎村▍鏇㈠煝閺囥垺鐓曢柨婵嗙箳閸掔増銇勯銏㈢闁圭厧婀遍幉鎾礋椤愩垹绠查梻鍌欑閹诧紕鍒掗崼銏㈢焼濞达絿纭堕弸鏃€绻濋棃娑氬ⅱ缁炬崘妫勯湁闁挎繂瀚惌娆撴煕濠靛牆鍔嬬紒缁樼洴閹崇娀顢楅埀顒勫几濞戙垺鐓熸繛鎴濆船濞呭秵顨ラ悙宸剶闁轰礁鍟撮崺鈧い鎺戝缂嶆牠鏌涘☉妯兼憼闁绘挾鍠愮换娑㈠幢濡ゅ嫬顏繛瀛樼矒缁犳牕顫忓ú顏勫窛濠电姴鎳庨ˉ婵嗩渻閵堝棗鐏ユい锕傛涧椤曪絿鎷犲ù瀣潔闂侀潧绻掓慨鐑藉礉閹绢喗鈷戦柛娑橈工婵箑霉濠婂嫮绠炵€规洘濞婇幐濠冨緞閸℃ɑ鏉搁梻浣虹帛閸旀ê鈻斿☉銏″剭闁绘垶菧娴滄粍銇勯幘璺轰户濠⒀嶇畵閺屾盯鍩￠崘銊ゆ濡ょ姷鍋涢澶愬极閸岀偞瀵犲璺烘娴滈箖鏌ｉ幋锝呅撻柣鎾存礃缁绘盯宕卞Δ浣侯洶濠碘槅鍨伴悧濠冪┍婵犲浂鏁冩い鎺戝€婚惁鍫濃攽椤旂》鏀绘俊鐐扮矙閻涱噣寮介鐔封偓鐑芥煙缂佹ê淇柣搴㈠▕濮婄粯鎷呴崨濠傛殘闂佺厧缍婄粻鏍€侀弽銊ョ窞闁归偊鍠栫粊锕傛⒑閸撴彃浜栭柛搴ら哺閸庮偊姊绘担绋挎毐闁圭⒈鍋婂畷鎰亹閹烘垹锛熷銈呯箰鐎氬嘲銆掓繝姘厪闁割偅绻冮ˉ婊冣攽椤旂厧鈧潡寮诲☉娆戠瘈闁告劗鍋撻悿浣割渻閵堝啫鐏柣鐔叉櫅椤曪綁骞橀纰辨綂闂佺偨鍎查弸濂稿磻閹剧粯鍋ㄩ柛娑橈功閸樹粙姊虹紒妯荤叆闁硅绱曞▎銏ゅ矗婢跺牅绨婚梺闈涱槶閸庡磭绮绘繝姘厸閻忕偛澧藉ú鎾煙椤旇娅婇柟鐓庣秺椤㈡洟濡舵惔鈶裤倝姊婚崒娆戭槮闁告艾顑呴—鍐嚍閵壯屾锤闂佸壊鍋呭ú鏍不閻樼粯鐓ラ柣鏂挎惈瀛濋柛銉︽尦濮婃椽骞栭悙鎻掑闂佸搫鎷嬫禍鐐参ｉ幇鏉胯摕闁靛鑵归幏缁樼箾鏉堝墽绉繛鍜冪悼閺侇喖鈽夐姀锛勫弳濠殿喗顭堥崺鏍偂閺囥垺鐓熼柡鍐ㄧ墛閺侀亶鏌涚€ｃ劌鍔﹂柡灞剧洴閸╃偤宕归鍙ョ礄闁诲孩顔栭崰妤呭箰閾忣偅鍙忛柍褜鍓熼弻銊モ槈濡警浠煎Δ鐘靛仦閸旀瑥顫忛搹瑙勫珰闁肩⒈鍓涢濠囨⒑缁嬫鍎戦柛鐘崇墪閻ｇ兘骞嬮敃鈧粻濠氭煕閹捐尪鍏岄柣鎺戙偢濮婃椽宕ㄦ繝鍌毿曟繛瀛樼矋閻楃姴鐣烽幋锕€绠婚悹鍥ㄥ絻閻庮厼顪冮妶鍡楀Ё缂佹彃娼″畷娆撴晸閻樺磭鍘介柟鍏肩暘閸ㄥ銆傞崣澶岀瘈闁靛繆妲勯懓鍧楁煙椤曗偓缁犳牠骞冨鍫熷殟闁靛鍎扮花鐢告⒑閸︻厼甯堕柣掳鍔忛幗顐︽⒑閸濆嫬鈧敻宕戦幘缁樷拻闁稿本鐟ㄩ崗宀€鐥鐐靛煟鐎规洘绮岄埞鎴犫偓锝冨妷閸嬫捇宕橀鐘垫澑闂佺懓鐏濋崯浼村礉瀹勬壋鏀介柣鎰綑閻忥附鎱ㄥΟ绋垮濠㈣娲樼粋鎺斺偓锝庡亞閸橀亶鏌ｈ箛鏇炰沪鐎规洘蓱缁旂喎顫滈埀顒勫蓟瀹ュ牜妾ㄩ梺鍛婃尰瀹€鎼佺嵁閸愵喖纾兼慨妯块哺濞堥箖姊洪崷顓烆暭婵犮垺蓱鐎靛ジ鎮╃紒妯煎帾婵犮垼顕栭崹浼村箠閹版澘鍌ㄩ柣妯肩帛閳锋帒霉閿濆懏璐℃繝鈧禒瀣厱闁靛鍎洪悡濂告煃閵夘垳鐣电€规洖銈告慨鈧い顐幘閻熸繈姊绘担鍛婃儓閻炴凹鍋婂畷鏇㈠蓟閵夛箑浜楅梺鍝勬储閸ㄦ椽鎮¤箛鎿冪唵闁肩绶遍鍫濆嚑婵炴垶锕╅悢鍡欐喐濠婂牆鍨傞柛顐ｆ礀閽冪喐绻涢幋鐐茬劰闁稿鎹囬弫鎰償濠靛牏娉块梻渚€鈧偛鑻晶顔剧磽瀹ュ拑鏀诲ǎ鍥э躬閹晫绮欑捄顭戞Ч婵＄偑鍊栭悧妤€顫濋妸鈺傚仾闁逞屽墴濮婄粯鎷呴崨濠傛殘闂佺懓鎽滈崗姗€骞婂Δ鍛唶闁哄洨鍋炴潏鍫ユ⒑缂佹﹩鐒界紒顕呭灦閸╂盯骞嬮悩鐢碉紳婵炶揪绲介～鏍敂閸涱喖寮块梺鎼炲労閸撴岸鎮￠妷鈺傜厸闁搞儲婀圭花浠嬫煟閿濆懐浠涙い銊ｅ劦閹瑥顔忛瑙ｆ瀰闁诲氦顫夊ú蹇涘礉瀹ュ洦宕叉繝闈涱儏缁€鍐煏婵炲灝鍔氶棅锕傛⒒閸屾艾鈧娆㈠顒夌劷鐟滄棃鍨鹃敃鍌氶唶闁靛鍎抽敍鐔兼⒒娓氬洤澧紒澶婎嚟缁顫濋懜鐢靛幗闂佸綊鍋婇崰鏍礉鐎ｎ喗鐓冮梺鍨儏閻忔挳鏌″畝鈧崰鏍箠閺嶎厼鐓涘ù锝夘棑閹规洟姊绘担鍛婂暈婵﹤缍婇獮鎰板箮閽樺鎽曞┑鐐村灟閸ㄥ湱绮绘繝姘厸濠㈣泛顑呴悘銉╂煙閻ｅ本鏆慨濠呮閹风娀鍨鹃搹顐ｎ仧闂備線娼ч悧鍡椕洪妸鈺佺骇缂佸绨遍弨浠嬫煟閹邦厽缍戦柣蹇ョ畵閺岋綁鎮㈠┑鍡樻悙闁稿被鍔戝娲敆閳ь剛绮旈悽绋跨厱闁硅揪闄勯悡娑㈡煕鐏炰箙顏堝礉濠婂嫮绠鹃柛娑卞幗閸ゅ洭鏌＄仦鍓ф创闁诡喒鏅濋埀顒€婀辨慨鎾夊┑瀣拺鐎规洖娲ㄧ敮娑㈡煙閸涘﹦鎽冮柣蹇斿浮濮婃椽宕楅懖鈹垮仦闂佸搫鎳忕换鍫ュ极瀹ュ拋鐓ラ柛顐ゅ暱閹疯櫣绱撻崒娆戝妽闁崇鍊濋、鏃堝醇濠靛牜鍟囨俊鐐€栭崝褏绮婚幋鐘冲枂闁挎梻鍋撻崰鎰版煟濡も偓閻楀棛绮鑸电厽闁规儳鍟块弳鐔兼煙閼碱剦鐒炬い顓滃姂瀹曠厧鈹戦崼顐Ｐゅ┑鐘愁問閸犳鏁冮姀銇㈢兘宕掗悙鍙夌€繝鐢靛Т濞诧箓鎮″☉姘ｅ亾楠炲灝鍔氬Δ鐘虫倐閻涱噣寮介銈囷紲闂佸綊鍋婇崣搴♀枔濠婂牊鐓涚€光偓閳ь剟宕伴弽顓犲祦闁硅揪绠戠粻娑㈡⒒閸喓鈯曟い鏂垮缁辨捇宕掑▎鎺濆敼闂佺顑嗛幐鎼佲€﹂崸妤佸殝闂傚牊绋戦～宥夋⒑缂佹ɑ灏伴柣鐔叉櫅椤曪綁宕奸弴鐐哄敹濠电娀娼уΛ宀勫箰閸愵喗鈷戝ù鍏肩懅缁夘剙霉濠婂骸澧版俊鍙夊姍楠炴帒螖娴ｉ晲姹楅梻浣告啞閸旀牞銇愰崘顔肩闁汇垹鎲￠埛鎴︽煕濠靛棗顏繝鈧幍顔剧＜閻庯綆鍋勯悘鎾煙椤旇棄鍔ら柍瑙勫灩閳ь剨缍嗘禍鐐哄礉閿曗偓椤啴濡堕崱妤冪懆闁诲孩鍑归崜娑欑珶閺囩姷纾兼俊顖濆亹椤旀洟姊洪悷閭﹀殶闁稿鍠栭獮濠囧礃閳瑰じ绨婚梺鍝勬祩濠⑩偓闁规煡绠栭弻鈥崇暆鐎ｎ剙鍩岄柧浼欑秮閺屻倕霉鐎ｎ偅鐝旂紓浣诡殣缁绘繂顫忛搹鍦＜婵☆垵顕х喊宥囩磽娴ｈ櫣甯涢柛鏃€鐟╅崹楣冩晜閻愵剙纾梺闈涱煭缁犳垿鎮垫导瀛樷拺闁绘劘妫勯崝姘辩棯缂併垹骞楃紒鍌涘浮閸╋繝宕ㄩ瑙勫闂備礁鎲＄换鍌溾偓姘煎枟閺呭爼鏌嗗鍡欏幈闂佽鍎抽顓㈠箠閸モ斁鍋撳▓鍨灍濠电偛锕畷娲晸閻樻彃绐涘銈嗘椤鈧矮绮欏缁樻媴娓氼垳鍔搁梺鍝勭墱閸撶喖骞婂┑鍥ュ亝闁告劑鍔庨崝锕€顪冮妶鍡楃瑐闁绘帪绠撳畷鎰板箛椤旂懓浜鹃悷娆忓缁€鍐煕閺冣偓閻楃姾妫熼梺缁橆殔閻楀﹪宕曢悢鍏肩叆婵犻潧妫欏婵嬫煕閺冨洦纭鹃柍瑙勫灴閹瑧鈧稒锚闂夊秹姊虹化鏇熸珔闁哥喐娼欓悾鐑藉箣閿曗偓缁犲鏌熺喊鍗炲箺妞ゆ梹妫冨铏圭磼濡搫顫屽┑鈽嗗灠閿曘倛鐏掗梺閫炲苯澧存慨濠勫劋濞碱亪骞嶉鐓庮瀴闂備礁婀遍幊鎾趁洪銏㈠祦闁告劦鍠栭悡娑㈡煕濞戝崬鏋涙繛鍫涘€曢—鍐Χ閸℃鐟ㄥ銈忛檮濠㈡﹢寮抽埡鍛拻闁稿本鑹鹃埀顒佹倐瀹曟劖顦版惔锝囩劶婵炴挻鍩冮崑鎾搭殽閻愬澧垫い銏℃礋閸╂稑顫濋鐔翠虎婵犵鍓濋幃鍌炲极閸岀偞瀵犲璺猴梗缁辩喖姊婚崒娆掑厡缂侇噮鍨跺畷褰掑礂閸忕厧寮块梺闈涚墕椤︻垳澹曢幐搴濈箚闁靛牆鎳忛崳娲煟閹惧鎳囬柡宀€鍠栭、娑㈠幢濡も偓閺嬨倝鏌￠崱鎰仼闁宠鍨块崺銉╁幢濡炴崘鍩呴梻浣规偠閸斿矂鎮ラ悡搴殨濠电姵纰嶉崑鍕棯閹峰矂鍝洪柡鍜佸墴濮婅櫣鍖栭弴鐐测拤濡炪們鍔岄ˇ閬嶅焵椤掍胶鐓柛妤佸▕瀵鈽夐姀鐘殿啌闂佸憡鍔戦崝宀€绮婚搹鍦＝濞达綀娅ｇ敮娑氱磼鐎ｎ偅宕岄柛鈹惧亾濡炪倖甯婇懗鍫曞煀閺囩喆浜滄い鎾跺仦閸犳﹢鏌熼姘拱缂佺粯绻堝畷姗€顢旈崱娆愵潓闂傚倷绶氶埀顒傚仜閼活垱鏅堕幘顔界厸閻忕偠濮らˉ婊勩亜閹剧偨鍋㈢€规洏鍔戦、娑橆煥閸曨厸鍋撻锔解拻闁稿本鐟чˇ锕傛煙鐠囇呯？缂侇喗鐟╅獮瀣晜閼恒儲鐝栭梻渚€娼чˇ顐﹀疾濞戞艾顥氶柛褎顨嗛悡鐔兼煛閸屾氨浠㈤柟顔藉灴閺岋綁骞樺畷鍥╊唶闂佸疇顫夐崹鍧楀箖閳哄懏鍤戞い鎺戝亞閸炴椽鏌ｆ惔鈥冲辅闁稿鎸荤换娑㈠箣濞嗗繒浠鹃梺缁樻尰濞茬喖骞冨Δ鍛櫜閹肩补鈧尙鍑归柣搴ゎ潐濞叉牠鎯夋總绋跨劦妞ゆ帒鍠氬鎰箾閸欏鑰块柡浣稿暣婵偓闁靛牆鍟犻崑鎾存媴缁洘鐎婚梺瑙勫劤閸熻法鑺遍妷锔剧瘈闁靛骏绲剧涵楣冩煟濡も偓濡瑩骞堥妸鈺佺＜闁绘劕顕崢鎼佹煟韫囨洖浠ч柛瀣尵缁牓宕橀鍡欙紲闂佸搫鍟崐鎼佸几濞戞瑣浜滈柕蹇ョ磿閳藉銇勯锝囩疄妞ゃ垺顨嗗鍕緞鐏炴拝绱￠梻鍌氬€搁崐宄邦渻閹烘梹顫曟い鏃€鍎崇欢銈夋煕瑜庨〃鍛矆閸屾稐绻嗘い鏍ㄧ懆椤掔喐绻涢崗鑲╁⒈缂佽鲸鎸婚幏鍛存嚃閳╁啫鐏﹂柛鎺戯躬楠炴﹢顢欓悾灞藉箞婵犵數鍋為崹鍫曟晝椤愩埄鍟呴柕澶嗘櫆閻撴盯鏌涢埄鍐炬畼濠⒀嶉檮閹便劍绻濋崘鈹夸虎閻庤娲忛崝宥囨崲濠靛绀冮柣鎰靛墻濡繈姊婚崒姘偓鎼佸磹閸濄儮鍋撳鐓庡闁逞屽墯閸戝綊宕板璺虹闁圭儤鏌￠崑鎾绘晲鎼存繃鍠氶梺鍛婅壘椤戝寮诲☉妯锋闁告瑦顭囬崙褰掓⒑閸濆嫬鈧敻宕戦幘缁樷拻濞达絿鐡旈崵娆撴煕閹寸姵娅曠€垫澘锕幊鐐哄Ψ閿旂晫褰块梺纭呭閹活亞寰婇崸妤佸剹婵炲棙鎸鹃崣鎾绘煕閵夛絽濡块柍顖涙礋閺屾稒绻濋崒婊€绮靛銈冨妸閸庣敻骞冨▎鎾村殤妞ゆ垼鍎诲鎼佹⒒娴ｅ憡鍟炴慨濠傛贡閸犲﹤顓奸崶銊ュ簥濠电偞鍨堕惌顔尖柦椤忓牊鐓曢悘鐐村礃婢规ɑ銇勯鈧鍡欐崲濠靛顫呴柨婵嗗缂嶅牆鈹戦悙璺虹毢闁哥姵鐗犻悰顕€骞囬鐘电槇闂佸憡鍔︽禍鐐躲亹閹€鏀介柣妯肩帛濞懷勪繆椤愶絿銆掔紒顔芥煥鐓ゆい蹇撴噽閸樺憡绻涙潏鍓ф偧闁硅櫕鎸婚幈銊ヮ吋閸ワ絽浜鹃悷娆忓缁€鈧梺闈涚墛閹倿濡存笟鈧鎾閻欌偓濞煎﹪姊洪幐搴ｂ槈閻庢凹鍘奸埢鎾绘嚋閻㈢數鐦堥梺姹囧灲濞佳冩毄闂備浇妗ㄩ悞锕傚箖閸屾氨鏆﹂柟瀛樼妇濡插牓鏌曡箛濞惧亾閸忓懐缍嶉梻鍌欑閹测€趁洪敃鍌氬瀭濞村吋娼欓崹鍌炴煕鐏炵虎鍤旂憸鐗堝笚閸嬫劗鈧懓澹婇崰鏍礈娴煎瓨鈷戦柦妯侯槸閺嗙喖鏌涢悩鍐插闁瑰箍鍨归埥澶愬閻樻鍚呴梻浣虹帛閸旀寮幖浣瑰亗闁稿瞼鍋為埛鎴炴叏閻熺増鎼愰柍褜鍓氶崝娆忕暦閹达箑绠荤紓浣骨氶幏缁樼箾鏉堝墽鍒伴柟璇х節楠炲棝宕奸妷锔惧幈闂佺粯娲戠粈浣圭閹殿喒鍋撶憴鍕闁告梹鐟ラ悾閿嬬附缁嬪灝宓嗛梺缁樺姍濞佳勬叏閿旀垝绻嗛柣鎰典簻閳ь剚鐗滈弫顔界節閸曨厾鐒兼繛杈剧秬濞咃絿绮婚弮鍌涘枑闊洦娲橀～鏇㈡煙閻戞ɑ灏扮紓宥呮喘閺屾洘绻涢崹顔煎闁荤姴娲ㄩ崑娑⑩€旈崘顔嘉ч柛鎰╁妿娴犻箖姊洪懡銈呮殌闁搞儜鍛瀫闂備礁婀遍搹搴ㄥ窗閺嶎偆鐭嗛悗锝庡亖娴滄粓鏌熼悜妯虹仴闁逞屽墮閹芥粌顕ユ繝鍥ч敜婵°倓璁查幏濠氭⒑缁嬫寧婀伴柣鐔濆懐鐜婚柡鍐ㄧ墛閻撳啰鎲稿鍫濈婵炴垯鍨圭壕缁樼箾閹存瑥鐏柛銈嗗姈閵囧嫰寮介妸褉濮囧┑鐐叉噽婵敻濡甸崟顖氬唨闁靛ě鍛帓缂備胶鍋撻崕鎶藉Χ閹间礁绠栨俊銈呮噺閺呮煡骞栫划鍏夊亾閼碱剛娉垮┑鐘垫暩閸嬬偤骞嗗畝鍕棷闁挎繂顦拑鐔兼煃閳轰礁鏆炲┑顖涙尦閺屾盯骞橀弶鎴犵シ闂佸憡鎸哥壕顓犳閹惧瓨濯村ù鐘差儏閹界敻姊洪崷顓х劸妞ゎ厾鍏橀悰顔跨疀濞戞ê绐涘銈嗙墬缁酣鎮￠幘鏂ユ斀闁绘劕寮堕ˉ鐘绘煕鐎ｎ偅灏柍缁樻尭鐓ゆい蹇撴噳閹风粯绻涙潏鍓у閻犫偓閿曞倹鍊块柣鎰靛厵娴滄粓鏌熺€涙绠撻柡鍡悼閳ь剝顫夊ú姗€宕濋弴銏犵厴闁硅揪绠戦獮銏ゆ煃鏉炴壆鍔嶆い鎾虫健濮婃椽鎳￠妶鍛呫垺绻涚拠褍顩紒顔硷躬瀵爼骞婄粵鍦М鐎规洖銈告俊鐑芥晜閹冨闂傚倸顭崑鍕洪敃鈧叅闁哄诞鍛噧闂備浇顕у锕傦綖婢舵劕绠扮紒瀣嚦濞戞ǚ鏀介柛鈾€鏅滅紞搴♀攽閻愬弶鈻曞ù婊勭箞钘熼柛顐ゅ枔缁犻箖鏌熸潏鍓у闁告凹鍋婇弻娑㈠籍閳ь剟骞冮崒姘兼綎闁惧繐婀遍惌娆撴煕椤垵娅橀柛鏂款槹缁绘繈濮€閵忊€虫畬濠碘槅鍋呯换鍫ョ嵁婵犲洦鍊烽悗娑欘焽缁夊爼姊洪棃娴ゆ盯宕ㄩ娑辨綋婵犵數濮甸鏍窗濡ゅ懏鏅濋柍鍝勬噹閸屻劑鏌涜箛姘汗妞も晠鏀遍妵鍕箻鐠鸿桨姹楅梺琛″亾濞寸姴顑嗛悡鐔镐繆椤栨侗鍎ラ柛銈咁儑閳ь剝顫夐幃鍫曞磿閻㈢绠栨俊銈傚亾妞ゎ偅绻堥幃鈩冩償閳锯偓閹奉偊姊洪懞銉劷闁哥姵鐗犻獮鍐ㄎ旈崨顔芥珳闁圭厧鐡ㄧ换鍕箰婢舵劖鈷戦悶娑掆偓鍏呭濠电偛顕慨鎾敄閸℃稒鍋傞柣鏂垮悑閻撴瑩鏌ら崜鎻掑濠德ゅГ缁绘盯宕ㄩ鐔锋闂傚洤顦扮换婵囩節閸屾稑娅ｆ繛瀛樼矊婢х晫妲愰幒鏃傜＜婵☆垵鍋愰悾鐢告⒑瀹曞洨甯涢柟鐟版搐閻ｇ柉銇愰幒婵囨櫓闂佷紮绲芥總鏃堟焽椤栫偞鈷掗柛灞剧懅閸斿秹鎮楃粭娑樺幘妤﹁法鐤€婵炴垶顭囬敍娆忊攽閻樼粯娑фい鎴濇搐閻ｅ灚绗熼埀顒勫蓟閳ユ剚鍚嬮幖绮光偓鍐差劀闂備浇妗ㄧ粈渚€宕幘顔艰摕闁靛ň鏅涢崡铏繆閵堝倸浜炬繛瀛樼矒缁犳牕顫忛搹鍦＜婵☆垵顕ч棄宥囩磽娴ｇ瓔鍤欓柣妤佹崌閹即顢氶埀顒€顕ｆ禒瀣р偓鏍Ψ閵夆晛寮板銈冨灪椤ㄥ﹪宕洪埀顒併亜閹哄秵顦风紒璇叉閺屻倕霉鐎ｎ偅鐝栫紒鐐劤閵堟悂寮婚敐鍛傜喖骞愭惔锝呮锭闂備焦鐪归崝宥夊垂閸ф钃熼柣鏃傚帶缁犵敻鏌熼悜妯诲碍闁哄棗鐗撳铏规嫚閳ュ磭浠┑鈽嗗亜閸燁垱绌辨繝鍥х濞达綀顫夊▍鍥⒑闁偛鑻晶鎾煕閳规儳浜炬俊鐐€栧濠氬磻閹炬剚鐔嗙憸宥夋煀閿濆鏄ラ柍褜鍓氶妵鍕箳閸℃ぞ澹曠紓鍌欒兌婵绮旈悷鎵殾闁哄洢鍨洪悞鑲┾偓瑙勬尪閸庡崬煤閿旈敮鍋撻棃娑栧仮鐎殿喖鐖奸獮瀣偐閹绘帞鐤勯梻鍌氬€烽懗鍫曘€佹繝鍥х妞ゅ繐妫涙稉宥夋煙鐎电啸婵☆偒鍨抽幉鎼佸籍閸繆鎽曢梺鎸庣箓椤︻垳绮诲☉娆嶄簻闁规崘娉涢弸鏃傜磼鐎ｎ亝鎼愭い顏勫暣婵″爼宕橀妸銉ヮ潛婵＄偑鍊栭崹闈浳涘┑鍥︾箚闁汇垻顭堢粈瀣亜閺嶃劎鈯曟繛鍛濮婃椽宕楅懖鈹垮仦闂佸搫鎳忕换鍫濐嚕閹惰棄围濠㈣泛顑傞幏娲⒑閸涘﹦绠撻悗姘煎幖閿曘垽鎮ч崼銏㈩啎闂佽偐鈷堥崜娆撳几鎼淬劍鐓熼柨婵嗩槹閺佽京绱掗搹瑙勬珪缂侇喗鐟ラ埢搴ㄦ倷椤掑倻袩闂傚倸鍊风粈渚€宕崸妤€绠规い鎰剁畱閻ゎ喗銇勯幇鍓佺ɑ闁告瑥绻愰埞鎴﹀磼濮橆厼鏆堥梺?",
            "principle": "",
            "concept_teaching": "",
            "review": "",
            "plan": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡▎鎴犫敍闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼宕滆绾惧ジ鏌ｅΟ鎸庣彧閻忓浚鍙冮弻锝夋晲婢跺鏆犵紓浣芥閺咁偆鍒掑▎蹇婃瀻闁绘劦鍓涚粔閬嶆⒒閸屾瑨鍏岄柛瀣ㄥ姂瀹曟洟鏌嗗鍛焾闁荤姵浜介崝蹇旀叏閹惰姤鐓忓璺烘濞呭棝鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡樺窛闁硅棄鍊圭换娑㈠礂閻撳骸顫屽銈庡幖濞硷繝骞冮悜鑺ュ亱闁割偒鍋呴敍渚€姊绘担鍛婃儓闁硅櫕鎸搁埢鏂库槈濠婂懍绨烽梻鍌欑閹测剝绗熷Δ鍛偍濡わ絽鍟弲顒佺箾閹存瑥鐏柣鎾跺枛楠炴牠骞栭鐐典化缂備礁顦遍弫濠氬蓟濞戙垺鍋愰柟棰佺劍閻や線姊虹拠鈥虫灀闁逞屽墯閺嬪ジ寮告惔銊︾厵闁诡垎灞芥闂佸憡顭囬弫濠氬蓟閿濆鍋勯柛婵勫劜閸Ｑ囨煟鎼淬垹鍤柛鎾村哺楠炲牓濡搁埡鍌涙珖闂佺鏈粙鎾诲储闁秵鈷戦梻鍫熺〒婢ф洘淇婇锝囨创妤犵偛锕畷銊╊敍濠婂拑绱查梺鍝勵槸閻楀嫰宕濆鍥︾剨濞寸厧鐡ㄩ悡娆戔偓鐟板婢ф宕甸崶鈹惧亾鐟欏嫭绌跨紒鍙夊劤椤曘儵宕熼娑樹壕闁挎繂楠告晶顔剧磽瀹ュ懎鏆ｆ慨濠傤煼瀹曟帒鈻庨幋顓熜滈梻浣告贡閳峰牓宕戦崱娑樼畺妞ゆ洍鍋撴い銏℃礋閺佸啴鍩€椤掑倻鐭嗗璺哄閸嬫捇宕楁径濠佸闂備礁鎲″ú锕傚磻閸℃稑鍌ㄩ柟缁㈠枟閳锋垹鐥鐐村櫤鐟滄妸鍛＜闁绘ê鍟块悘鎾煟濞戝崬娅嶅┑顔瑰亾闂佺偨鍎寸亸娆戠不濮橆剦娓婚柕鍫濇婢ь剙顭跨憴鍕妤犵偛绻橀崺鍕礃瑜忕粻姘舵⒑閸涘﹦鎳冩い锔垮嵆婵￠潧鈹戦崶銊ュ伎婵犵數濮寸€氼喚鏁☉銏＄厵鐎瑰嫮澧楅崳铏圭磼濡ゅ啫鏋涙い銏＄☉椤劑宕橀妸鎰典簻閳规垿鏁嶉崟顐℃澀闂佺锕ラ悧鐘茬暦瑜版帗顥堟繛纾嬫珪缁嬫垿鍩為幋鐘亾閿濆骸澧紒渚婄畵濮婇缚銇愰幒鎴滃枈闂佸憡锚缂嶅﹤鐣烽幋锕€宸濋悗娑欘焽閸橀亶姊虹憴鍕棎闁哄懏绋掓穱濠囧锤濡や胶鍘介梺闈涚墕閹冲繘宕甸崶銊﹀弿濠电姴鍟妵婵堚偓瑙勬礈閸忔﹢銆佸鈧崺鍕礃闁款垰浜炬俊銈呮噺閳锋垿鏌涘┑鍕姎閺嶏繝姊虹紒姗嗘畷缂侇喖閰ｅ畷姘跺箳濡も偓闁卞洭鏌嶉崹娑欐珔濞存粓绠栭弻銊モ攽閸℃侗鈧霉濠婂嫮澧棁澶嬬節婵犲倸顏柣顓熷浮閺屸€崇暆鐎ｎ剛鐦堥悗瑙勬礃閿曘垺淇婇幖浣肝ㄩ柕蹇曞С婢规洟姊哄Ч鍥х伄妞ゎ厼鐗忕划濠氼敍閻愬鍘撻梺瀹犳〃缁€渚€寮抽弴鐘电＜閻犲洤寮堕ˉ鐐烘煏閸パ冾伃妤犵偛娲崺鈩冩媴閹绘帊澹曢梺鍝勬储閸ㄥ綊宕欓悩缁樼厸闁告劑鍔岄埀顒冨吹婢规洘绺界粙璺ㄩ獓闂佸壊鍋呯粙鎴炰繆閻ｅ备鍋撶憴鍕闁活剙銈搁崺鈧い鎺戝枤濞兼劖绻涢崣澶樼劷闁轰緡鍣ｉ獮鎺懳旂€ｎ剛鈼ゆ繝鐢靛█濞佳囶敄閹版澘鏋侀柛鏇ㄥ灡閻撱垺淇婇娆掝劅婵℃彃鍢查…璺ㄦ喆閸曨剛顦板┑顔硷攻濡炶棄鐣烽妸锔剧瘈闁告洦鍘剧粣妤呮⒒娴ｄ警鐒鹃悗娑掓櫆缁绘稒绻濋崶褏鐣鹃悗鍏夊亾闁告洦鍋嗛鎺旂磽閸屾瑧鍔嶆い顓炴喘瀹曘垽鎮介悽鐢碉紳闂佺鏈悷鈺侇瀶閻戣姤鐓曢柕濞у嫬娈岄梺瀹狀嚙缁夋挳锝炲鍫濈劦妞ゆ帒瀚拑鐔兼煃閳轰礁鏆炲┑顖氼嚟缁辨帞鈧綆鍋掗崕銉ッ归悩闈涘付妞ゎ亜鍟存俊鑸垫償閳ュ磭鍝楁繝鐢靛仜椤︽澘煤閻旇偐宓侀柟杈剧畱缁€瀣亜閺嶃劎鈽夊ù鐘茬箻濮婃椽宕崟鍨ч梺鎼炲妿閺佸鏁愰悙鐑樺亹缂備焦菤閹风粯绻涙潏鍓у埌闁硅绻濋獮鍡涘醇閻斿墎绠氬銈嗗姧缁插墽浜搁敂鑺ュ弿濠电姳鑳堕惌娆戔偓瑙勬礈閸犳牠銆佸鈧幃銏犵暋閹殿喖鎼告繝鐢靛Х閺佸憡绻涢埀顒佺箾娴ｅ啿鍘惧ú顏勎╃憸宥嗘叏椤掑嫭鐓冪憸婊堝礈閻斿娼栭柧蹇撴贡閻瑩鏌熺粙鍨劉闁圭柉浜槐鎺楁倷椤掍胶鍑＄紓浣割槸缂嶅﹪鐛崘顭戞建闁逞屽墴閻涱喖螣閼测晝锛滃┑鈽嗗灦閺€杈┾偓姘偢濮婄粯鎷呴崨濠傛殘缂備礁顑嗛崹鍧楀极閸愵喖惟闁挎柨澧借ぐ鎯р攽閳藉棗鐏￠柣顏囶潐缁傚秴顭ㄩ崼鐔哄幍闁诲孩绋掗…鍥╃不閺嶎厽鐓曢柕鍫濇噺閸犳﹢鏌＄仦鐣屝у┑锛勫厴椤㈡稑顫濋崗鐓庢灎闂傚倷绀佸﹢閬嶅箠閹惧灈鍋撳鍗烆暭濞ｅ洤锕獮鏍ㄦ媴鐟欏嫭鐝栭梻渚€鈧偛鑻晶鏉款熆鐟欏嫭绀嬫い銏＄☉閳藉顫濇鏍ф櫗闂傚倷绀佸﹢閬嶅磻閹炬剚鐒芥繛鍡樻尭閸氳銇勯幒鎴濐仾闁绘挻娲熼弻鏇熺箾閸喒鍋撻弴鐐垫殼闁糕剝鐟㈤崑鎾舵喆閸曨剛顦ㄧ紓渚囧枟閹瑰洭濡存担鑲濇棃宕ㄩ鐙€妲规俊鐐€栭崹鍏兼叏閵堝洠鍋撳顑惧仮婵﹦绮幏鍛村川婵犲倹娈樼紓鍌欐祰椤曆囧磹婵犳艾鐒垫い鎺嶇劍閻ㄦ垿鏌涜箛鏂嗩亪鎮鹃悜钘夊嵆闁挎稑瀚弶鎼佹⒑閸濆嫬鈧憡鏅堕悾宀€涓嶆慨姗嗗墻濞撳鏌曢崼婵囶棞濠殿啫鍛＝鐎广儱鎳忛ˉ婊堟煃缂佹ɑ灏い顓滃姂瀹曞ジ鎮㈤崫鍕疄闂傚倷绀侀崯鍧楀箹椤愶箑鐤い鎰剁悼椤╃兘寮堕崼顐ゅ帥婵炲牅绮欓弻锝夊箛椤掍讲鏋欓梺绋垮濡啴寮婚埄鍐╁缂佸绨遍崑鎾诲锤濡も偓缁犳澘鈹戦悩鎻掓殭缂佸墎鍋ら弻娑㈠焺閸愶缚娌繝銏ｎ潐濞茬喎顫忛搹鍦＜婵☆垵娅ｆ导鍥ㄧ節濞堝灝鏋旈柛濠冪箞楠炲啴鏁撻悩鍐蹭汗闂佹眹鍨归悘姘舵晬韫囨稒鈷戦柛婵嗗濡叉悂鏌ｈ箛鏃傜疄闁硅櫕绮撻幃鐑芥焽閿旀儳鏁搁柣鐔哥矋缁挸鐣烽幎鑺ユ櫜濠㈣泛锕ㄩ幗鏇㈡倵楠炲灝鍔氭い锔跨矙瀵偊宕掗悙瀵稿幈濡炪倖鍔戦崐鏇㈠几閹达附鈷戞繛鍡樺劤瀵喗鎱ㄦ繝鍛仩闁逞屽墮濠€杈ㄥ垔椤撶儐鐒介柟鎵閻撴洟鏌曟繛鍨姕闁稿鍎查〃銉╂倷閹绘帗娈梺瀹狀嚙闁帮綁鐛Ο铏规殾闁搞儺鍓涘畷婊堟⒒閸屾瑧顦﹀鐟帮躬閹繝宕奸妷銉х崶濠殿喗锕╅崗姗€寮搁弮鍫熺厱妞ゆ劧绲剧粈鍐煃闁垮绗掗棁澶愭煥濠靛棛澧辨繛鍏煎姍閺屾稓鈧綆鍓欓埢鍫ユ煛鐏炲墽鈯曢柟顖涙婵偓闁靛繈鍨婚崢婊堟煟鎼淬値娼愭繛鍙夌矒瀹曚即寮介婧惧亾娴ｈ倽鐔烘偘閳╁喚娼旀繝纰樻閸ㄦ娊骞婇幘鍑板顫濋婵堢畾闂佺粯鍔︽禍婊堝焵椤掍胶澧い鏂跨箲缁绘繂顫濋鍌︾幢闂備礁婀遍崑鎾绘偩椤忓懐顩叉繝濠傚娴滄粓鐓崶銊﹀碍妞ゅ繆鏅犻弻锟犲幢椤撶姴鍩岄梺瀹狀潐閸ㄥ潡宕归幆褏鏆﹂柛銉戝懎骞楅梺璇叉唉椤煤閺嵮呮殾妞ゆ帒鍟版禍浠嬫⒒閸屾瑧顦﹂柣蹇旂箞椤㈡牠宕ㄩ幖顓熸櫆濠电偛妯婃禍婵嬪煕閹烘鐓曢悘鐐插⒔閹冲懏銇勯敂鑲╃暤闁哄瞼鍠撻崰濠囧础閻愭澘鏋堟俊銈囧Х閸嬫稓鎹㈤幒妤€鐒垫い鎺戯功缁夌敻鏌涢悩宕囧⒈濠㈣娲滈幏鐘裁圭€ｎ偅鏉搁梻浣虹帛閿氱€殿喖鐖奸獮鏍箛閻楀牏鍘搁梺鍛婃磵閺呮盯宕濋敃鍌涚厸閻忕偟鍋撶粈澶岀磼閻樺磭銆掗柍褜鍓ㄧ紞鍡樼閺嶎厼纾婚柟鎹愵嚙閸楁娊鏌ｅ鈧褔寮冲Δ鍛€垫鐐茬仢閸旀碍銇勯敂鍨祮闁诡噯绻濆鎾偄缂堢姷鐩庨梻浣筋潐婢瑰寮插☉銏犵劦妞ゆ帊鐒︾粈瀣偓娈垮枟閹倸顕ｉ鈧畷濂告偄閸濆嫬绠炲┑鐘殿暯濡插懘宕瑰畷鍥у灊妞ゆ牗姘ㄩ弳锔锯偓鍏夊亾闁告洦鍓涢崢闈涱渻閵堝棙鈷掗柛妯犲吘锝囩磼濡晲绨诲銈嗘尰缁本鎱ㄩ崒婧惧亾鐟欏嫭绀堥柛鐘崇墵閵嗕礁顫滈埀顒勫箖閳哄懏顥堟繛鎴烆焾缁剁喖姊婚崒娆愮グ妞ゆ泦鍐炬僵闁挎洖鍋婄紞鏍ь熆鐠鸿　濮囬柛婵嗗珋閻斿吋鍋傞幖杈剧磿娴滀即姊绘担绛嬫綈鐎规洘锕㈤、姘愁槾缂侇喖顭峰浠嬵敇閻斿搫甯鹃梻濠庡亜濞层倝顢栭崨鏉戠劦妞ゆ帊鑳舵晶鐢碘偓瑙勬礃閸ㄥ灝鐣烽幒妤佸€烽柤纰卞墻閸熷洭姊洪崫鍕垫Ц闁绘妫欓弲鑸电鐎ｎ亞鐣烘繝闈涘€搁幉锟犳偂濞戙垺鐓曢柍鈺佸暞缁€鈧悗瑙勬尭濡瑩骞堥妸锔剧瘈闁告洦鍘肩粭锟犳⒑閻熸澘妲婚柟铏悾鐑藉Ω閿斿墽鐦堥梺绋挎湰缁嬫帡鎮鹃悡搴樻斀闁绘ê鐏氶弳鈺呮煕鐎ｎ剙鈻堟い銏¤壘椤劑宕ㄩ娆戠憹闂備浇顫夐崕宕囧椤撱垹姹查柨鏇炲€归崑鈩冪箾閸℃绠版い蹇ｅ亰濮婂宕熼銏╀紑缂備浇椴哥敮鐐哄焵椤掑﹦绉甸柛瀣椤㈡艾顭ㄩ崼鐔哄幗闁瑰吋鎯岄崰鏍ㄦ櫠椤栨粎纾肩紓浣诡焽缁犵偤鏌熼鑽ょ煓婵☆偄鍟湁闂婎剚褰冮悘顏嗙磼缂佹銆掗柟椋庡Ь椤︽挳鏌ｉ敐鍥ㄦ毈闁哄瞼鍠栭、姘跺幢濞嗘垹妲囬梻浣筋嚃閸犳捇宕归挊澶屾殾婵°倕鎳忛崵鍐煃鏉炴壆顦︽慨瑙勫絻閳规垿鎮╅崹顐ｆ瘎婵犵數鍋愰崑鎾斥攽閻愭澘灏冮柛蹇曞亾缁嬫垿鍩㈡惔銊ョ闁告劕寮堕崕顏堟⒒娓氣偓閳ь剛鍋涢懟顖涙櫠閹绢喗鐓涚€光偓鐎ｎ剛蓱闂佽鍨卞Λ鍐╂叏閳ь剟鏌曡箛瀣仼鐟滄澘閰ｅ缁樻媴閸涘﹤鏆堝銈冨妼濡瑧鎹㈠☉娆戠瘈闁稿被鍊曞▓銊︾節閻㈤潧校缁炬澘绉瑰鏌ュ蓟閵夛妇鍘卞銈嗗姉婵挳鎮橀鈧弻鈩冨緞瀹€濠勫姼闂佸疇顫夐崹鍧楀箖濞嗘挸绾ч柟瀵稿С濡楁挻淇婇悙顏勨偓鎴﹀礉鐏炶娇娑樷攽閸℃瑦娈鹃梺鍝勵槹椤戞瑥顭囬埡鍌樹簻闁硅揪绲借闂佸搫鍊甸崑鎾斥攽閿涘嫬浜奸柛濠冪墪椤繑绻濆顑┿儵鎮楅敐搴℃灈缂備讲鏅濈槐鎾存媴婵垼鍋愰幑銏ゅ幢濞戞瑧鍘介梺褰掑亰閸樺ジ藟鐎ｎ喗鐓熸い鎾跺枔閹冲洭鏌″畝瀣埌闁宠棄顦靛畷锟犳倷鐎电缍嗗┑掳鍊楁慨鐑藉磻濞戞◤娲敇椤兘鍋撴担鍓叉建闁逞屽墴楠炲啴濮€閻樺灚娈濋梺鍝勵槼椤曟娊濡舵径瀣ф嫽闂佺鏈悷褔宕濆澶嬪€电紒妤佺☉閹冲繐鐣烽弻銉︾厱鐎光偓閳ь剟宕戝☉姘棜闁革富鍘介崰鎰版煟濡も偓閻楀棝鏌屽鍛＝鐎广儱妫涙晶閬嶆煃瑜滈崜娆戠不瀹ュ纾块梺顒€鍗曢崶銊ヮ嚤闁哄鍨归崢閬嶆⒑閸︻厼鍔嬮柛銈嗕亢閵囨劙骞掗幘瀛樼彸闂備焦鎮堕崕杈ㄦ櫠鎼淬劌绀夐柟闂寸劍閳锋垿鎮归崶锝傚亾閾忣偆浜堕梻浣规偠閸斿繘宕洪弽顐ょ煔閺夊牄鍔庣弧鈧梺鎼炲劘閸斿矂鍩€椤掑倸鍘撮柡灞剧☉閳诲氦绠涢敐鍠帮附绻涚€电校闁瑰憡濞婇獮鍐ㄎ旈崘鈺佹瀭闂佸憡娲﹂崜娑⑺囬妷銉㈡斀闁绘﹩鍋勬禍楣冩⒒娓氬洤澧紒澶婎嚟缁寮婚妷锔惧幈闂佸搫娲㈤崝宀勬倶閿熺姵鐓欐い鏍ㄧ矊娴犻亶鏌熼鐓庢Щ闁宠姘︾粻娑㈠箼閸愌呮／濠碉紕鍋戦崐鏍ь潖閻熸噴鍝勎熼懡銈傛敵婵犵數濮村ú锕傚磹闁垮浜滈煫鍥ㄦ尭椤忋倝鏌涚€ｎ偅宕岀€殿喕绮欓、姗€鎮㈤摎鍌滅秿濠电姷鏁告慨鎾晝閵堝鍋嬮柛鈩冪懃椤ユ氨绱撴担璇＄劷缂佺娀绠栭弻鐔衡偓娑欘焽閹冲啴鏌ｈ箛锝勯偗闁哄本绋掔换婵嬪磼濞戞ü娣梻浣告惈閺堫剟鎯勯鐐茬伋闁挎洖鍊哥粻锝嗙節闂堟稒鍣介柟绋款槸閳规垿鎮欓懠顒佹喖缂備緡鍠栫粔鍫曞礆閹烘绠婚悹鍥蔼閹芥洟姊虹紒妯荤叆闁告艾顑夊畷鎰磼濡湱绠氬銈嗙墬缁诲啴顢旈悩瑁佸綊鎮╅搹顐ょ▏濡炪値浜滈崯瀛樹繆閸洖宸濇い鏃傝檸濞茶泛鈹戦悙鑼憼缂侇喚濮电粋宥夘敂閸曢潧娈ㄦ繝鐢靛У绾板秹寮查幓鎺濈唵閻犺櫣灏ㄩ崝鐔搞亜閺冣偓鐢繝寮婚敐鍡樺劅闁靛闄勯柨顓㈡⒑绾拋鍤嬬紒缁樼箓閻ｇ兘鎼归銏╁殼闁诲孩绋掕彜闁归攱妞介弻锝夋偐閸欏顦遍梺閫炲苯澧叉繛鍛礋閹﹢宕奸姀銏紳闂佺鏈銊ョ摥闂備焦瀵уú锔界椤忓牊鍋樻い鏇楀亾鐎殿喕绮欓、鏍矗閵夛妇娼栭梻鍌欑濠€閬嶅磿閵堝绠伴柛娑橈功椤╅攱銇勯幘鍗炵仾闁抽攱鍨块幃宄扳枎韫囨搩浼岄梺鍝ュ枎缁绘﹢寮诲☉銏″亹闁归鐒﹂悿浣割渻閵堝啫鐏い顓炴川濡叉劙骞掗幊宕囧枛閹虫牠鍩￠崘鈺婃綋婵犵數濮烽弫鎼佸磻濞戙垺鍋嬮柛鈩冪⊕閸婅埖绻濋棃娑卞剰闁告垹濮电换娑㈠箣濞嗗繒浠鹃梺缁樻尪閸庣敻寮婚敓鐘茬倞妞ゎ厼顑愭禍顏勭暦濠靛鏅濋柛灞剧〒閸橆亪姊虹化鏇炲⒉妞ゃ劌鎳樺鎶芥晲閸ワ絽浜鹃悷娆忓缁€鈧梺闈涚墕閹诧繝骞堥妸鈺佺劦妞ゆ帒瀚悡鍐煢濡警妲规い銉у仧缁辨挸顓奸崱鈺傜杹濠殿喖锕︾划顖炲箯閸涙潙宸濆┑鐘叉噽椤㈠懘姊绘担渚劸缂併劍妞藉畷鎰攽鐎ｎ€儵鏌涢幇闈涘箻闁汇倐鍋撴繝鐢靛仦閸ㄦ儼鎽梺璇插瘨閸撴氨鎹㈠┑瀣仺闂傚牊鍒€閵忥紕绠鹃悹鍥囧懐鏆ら梺璇″櫙缁绘繈骞冮姀銈呯闁兼祴鏅涘铏節閻㈤潧鈻堟繛浣冲吘娑樷枎閹惧啿鎯為梺閫炲苯澧撮柡宀嬬稻閹棃濮€閿涘嫭顓诲┑鐘媰閸曞灚鐤佹繝纰夌磿閺佽鐣烽悢纰辨晬闁挎繂妫欏▍鍥⒑绾懎浜归悶娑栧劦瀹曟粌鈹戦崶褏绐為梺鍛婃处閸ㄩ亶鎮￠弴鐐╂斀闁绘ɑ褰冮顏堟煛閸♀晛澧撮柡宀嬬磿娴狅箓宕滆閸掓盯姊洪悙钘夊姷缂佺姵鎹囬悰顔锯偓锝庝簴閺€浠嬫煕濞戝崬鐏犻柛銈庡墰缁辨捇宕掑顑藉亾瀹勬噴褰掑炊椤掆偓閺勩儵鏌″搴″箺闁稿鍊块弻銊╂偄閸濆嫅銏㈢磼閻樺磭澧ǎ鍥э躬婵″爼宕掑顐㈩棜濠碉紕鍋戦崐銈夊磻閸涱垱宕查柛顐犲劘閳ь兛绶氬鎾閻欌偓濞煎﹪姊虹紒姗嗙劷闁稿缍佸畷鎴﹀冀椤撶啿鎷洪柣鐘叉搐瀵爼宕径瀣ㄤ簻妞ゆ劑鍩勫Σ鎼佹偂閵堝棔绻嗘い鏍ㄧ懆椤掔喐绻涢幘璇″殭闂囧鏌ｅΟ鐑樷枙闁稿骸绻橀弻锛勨偓锝傛櫇缁愭棃鏌″畝鈧崰鏍х暦濠婂棭妲鹃柣銏╁灡閻╊垶寮诲☉姘ｅ亾閿濆骸浜滃┑顔肩Ч閺岋紕浠︾拠娴嬪亾濡ゅ懎绐楀┑鐘叉搐绾偓闂佺粯鍔栫粊鎾箯缂佹绡€鐎电増鐏氶崐鏇犳閿曞倹鐓曟俊銈傚亾闁哥喎娼￠敐鐐剁疀閺囩姷锛滃┑鈽嗗灥椤曆囶敁閹惧墎纾藉ù锝呭閸庢劙鎮楃粭娑樺敪閹烘绠涢柣妤€鐗冮幏娲⒑闂堚晛鐦滈柛妯绘倐楠炲繘鏁撻悩宕囧幈闁诲函缍嗘禍宄邦啅閵夆晜鐓熼柨婵嗘搐閸樺瓨銇勯姀锛勬创闁诡喗绮撳畷鍗炍熺紒妯煎建婵犵數濮甸鏍窗濡ゅ懏鏅濇い鎰╁€曠欢銈呂旈敐鍛殲闁稿﹨娉涢妴鎺戭潩閿濆懍澹曟繝娈垮枛閿曨亞绱撳璺何﹂柟鐗堟緲缁犳娊鏌熼崹顔碱伀闁告艾缍婂缁樻媴閾忕懓绗￠柣銏╁灱娴滅偟鍒掓繝姘閻犲洤寮跺Σ顒€鈹戦悙鏉戠仧闁搞劌婀辩划濠氬箮閼恒儳鍘甸梺缁樺姌濡嫭淇婇懖鈺冪＝鐎广儱鎷戦煬顒傗偓娈垮櫘閸嬪﹪鐛崶顒€绾ч柛顭戝枤閻涒晜淇婇悙顏勨偓鏍蓟閵娾晛瑙﹂悗锝庝簴閺嬫梹鎱ㄥ璇蹭壕濠殿喖锕︾划顖炲箯閸涙潙宸濆┑鐘插暙閺嬫垿姊绘担鍛婃喐濠殿喚鏁婚獮鎴﹀炊瑜忛弳锕傛煙鏉堝墽鐣遍崶瀛樼節閵忥絾纭鹃柨鏇樺姂楠炴寮撮姀鈾€鎷洪梺缁樺姌濡嫰宕濆杈╂／缂備降鍨瑰顔锯偓娈垮枟婵炲﹤鐣烽崡鐐╂婵炲棗绻嗛崑鎾绘偨閸涘﹦鍙嗗┑鐘绘涧濡繈顢撳Δ鈧…鑳槼濠㈢懓妫濋獮鍐敋閳ь剟寮崘顔肩＜婵炴垶鑹鹃獮妤呮⒑閻熸澘鎮戦柣锝庝邯瀹曟劙濡堕崪浣哄姺闂佸綊鍋婇崢鍓х不妤ｅ啯鐓曟繛鍡楁禋濡牓鏌ｉ幒宥囩煓闁哄瞼鍠栭悰顕€宕归鍙ョ礄闁诲氦顫夊ú婊堝窗閺嶎厹鈧礁鈽夊鍡樺兊闂佸憡顨堥崑娑滎杺濠电姷顣槐鏇㈠磻閹达箑纾归柡宥庡亝閺嗘粓鏌熼悜姗嗘畷闁哄懏绻堥弻銊╁棘閸喒鎸冮梺娲诲幗閹瑰洭寮婚敐澶婎潊闁绘ê鍟块弳鍫ユ⒑缂佹ɑ灏版繛鑼枛瀵鎮㈤悡搴ｇ暰閻熸粍绮撳畷鐢告偄閸忚偐鍘梺绯曞墲閿氱紒妞﹀懐纾奸弶鍫涘妼濞搭喗銇勯姀锛勬噰闁硅櫕鐗犻崺鈩冪瑹閸ャ劍绶紓鍌氬€搁崐鐑芥嚄閸撲礁鍨濇い鏍ㄧ矋瀹曟煡鏌涢锝囩畼闁哄棴绠撻弻娑㈩敃閿濆棛顦ラ柟顖滃枛閹嘲顭ㄩ崘顎囨煟濞戝崬娅嶆鐐叉喘閹囧醇濮橆厼顏烘繝鐢靛仩閹活亞寰婃禒瀣疅闁跨喓濮撮悿顕€鏌ｉ幇顔煎妺闁绘挻娲熼弻锟犲礃閿濆懍澹曢梻浣规偠閸斿矂鎮樺┑瀣仼鐎瑰嫭澹嬮弨浠嬫煕閵夛絽濡奸柛鏂挎嚇濮婃椽妫冨☉姘辩暰闂佸憡鎸荤换鍫ュ箖閻㈠憡鍊婚柤鎭掑劗閹锋椽姊洪崨濠勭畵閻庢凹鍙冨畷鎺楀Ω閳哄倻鍘遍梺闈涱煭闂勫嫰濡靛┑瀣厵妞ゆ洖妫涚弧鈧悗娈垮枟閹歌櫕鎱ㄩ埀顒勬煃閵夛附鐏遍柛瀣崌瀹曞ジ寮撮悢鍝勫箺闂備線鈧稑宓嗛柛瀣躬瀵泛煤椤忓懐鍘遍梺闈涚墕濡盯骞婇崘顔界厓閻熸瑥瀚悘瀛樸亜閵忥紕鎳囬柟顔瑰墲閹柨螣鏉炴澘顥氶梻浣侯潒閸曞灚鐣堕梺钘夊暟閸犳牠寮婚敐澶婄睄闁稿本顨嗙€氭盯姊烘潪鎵槮闁挎洩濡囧Σ鎰板箳閹存梹顫嶅┑顔筋殔濡宕滈柆宥嗏拺婵懓娲ら埀顒佹尵濞嗐垹顫濋澶嬬稁闂佺粯鍨惰摫濠殿喗绮撻弻鐔封枔閸喗鐏堟繝纰樷偓鑼煓婵﹥妞藉畷銊︾節閸愶絾瀚婚梻浣虹帛椤ㄥ牊绻涢埀顒勬煟濞戝崬娅嶇€规洖宕埥澶娢熼懖鈺傜秮闂傚倷绀佹竟濠囧磻閸涱垱宕查柛鏇ㄥ墮椤曢亶鎮楅敐搴℃灍闁抽攱鍨归幉鎼佹偋閸繀鍒婇梺鍝勬鐢繝寮婚敐澶婄闁绘劗鍎ら宥咁渻閵堝啫濡搁柛搴ㄦ涧閻ｇ兘鎮㈢喊杈ㄦ櫍闂佺粯顭囬。顔炬閹惰姤鈷掑ù锝勮閻掗箖鏌￠崼顐㈠⒋闁硅櫕绻冮妶锝夊礃閵娧冨Е婵＄偑鍊栧濠氬磻閹剧粯鐓曢柕蹇ョ磿閸欌偓濠电姭鍋撳〒姘ｅ亾婵﹥妞介獮鏍倷閹绘帒顫戦梻浣告啞閺屻劑鏁冮妷褏鐭夐柟鐑橆殔闁卞洭鏌曡箛瀣伄闁挎稒绮撻弻锝嗘償椤栨粎校闂佸憡顭囬弲顐⑩槈閻㈢閱囬柡鍥╁枔閸樻悂姊虹化鏇炲⒉妞ゃ劌妫濊棢闁靛繈鍊栭悡娑氣偓鍏夊亾闁逞屽墴瀹曚即寮借濞兼牠鏌ゆ慨鎰偓鎰板磻閹剧粯顥堟繛鎴烇供濡苯鈹戦垾铏枙闁革綇绲介～蹇撁洪鍛檮婵犮垼娉涢敃銉モ枔閸洘鈷戦柛婵勫劚鏍￠梺鍛婃⒐椤ㄥ﹪鐛幋锕€顫呴柣姗嗗亝椤秹姊洪棃娑氱濠殿喚鍏橀、姗€宕崟銊︽杸闂佺粯鍔曞鍫曀夊鍛＜缂備焦锚缁楁氨绱掗崒娑樻诞闁硅櫕鐗犻崺锟犲礃椤忓海闂繝鐢靛仩閹活亞寰婃禒瀣妞ゆ劧濡囬埀顒勬敱缁绘繈鎮介棃娑楃捕闂佺懓鍟跨换鎰弲濠碘槅鍨甸崑鎰版儗濮樿泛绾ч柛顐ｇ☉婵¤法绱掗埦鈧崑鎾绘⒒娴ｈ鍋犻柛搴㈡そ閹ê鈽夊搴⑩枌闂備礁鎼張顒傜矙閹达腹鈧箓濡搁埡浣侯槰闂侀潧顭梽鍕敊婢舵劖鈷掑ù锝堝Г閵嗗啴鏌ｉ幒鐐电暤鐎规洘娲熼獮搴ㄦ寠婢跺苯骞嬮梻浣侯攰閹活亪姊介崟顖氱９闁绘垼濮ら悡鐘电棯閺夊灝鑸瑰褜鍠楅妵鍕晲閸涱垰鐓熷┑顔硷龚濞咃絿鍒掑▎鎾抽敜婵°倕艌閸嬫挸螖閸愵亝锛忕紓鍌欓檷閸ㄥ綊鐛弽顓炵闂侇剙绉甸悡娆撴煟濡も偓閻楀﹦娆㈤懠顒傜＜闁绘ê妯婇悡濂告煙椤旂瓔娈旈柍钘夘槸閳诲秹顢樿闁垱銇勯姀鈩冨磳妤犵偞顭囩槐鎺懳熼悡搴＄闂傚倷鑳剁划顖炲蓟閵娾晛绠烘繝濠傜墕缁犵娀鏌涢幇闈涙灍闁稿﹤鐏氶幈銊ノ熼悡搴′粯濠电偛鎳庣粔鍫曞焵椤掑喚娼愭繛娴嬫櫇缁辩偞鎷呴崫銉︽闂佸憡顨堥崑鎰ｉ崼鐔虹闁糕剝顨嗗﹢浼存倵濮橆兙鍋㈡慨濠呮閹风娀宕ｆ径瀣棷婵犵數鍋涢幊宀勫垂閽樺娼栧ù鐘差儏缁€瀣亜閹伴潧浜為柛鐐烘涧閳规垿鍩ラ崱妤冧淮濡炪倖鏌ㄩ敃锕傚箲閵忋倕骞㈡繛鎴炵懃娴狀垶姊虹拠鈥冲箺閻㈩垱甯楁穱濠勬崉閵娧勶紡闂佽鍨庨崘鈺佲偓顖炴⒑闂堟稒鎼愰悗姘緲椤曪綁顢氶埀顒€鐣烽幒鎴旀婵炲棙鍨靛☉褔姊婚崒娆掑厡闁硅櫕鎹囧畷顖滄崉閵娿垹浜炬慨妯煎帶濞呭秹鏌涢埞鎯т壕婵＄偑鍊栧濠氬磻閹剧粯鐓熼煫鍥ㄦ婢规ɑ銇勯鐐典虎閾伙綁鎮樿箛鏃傚ⅹ濞存粎鍋撻幈銊ヮ潨閸℃ぞ绨婚悗瑙勬尭濡繈寮婚敐鍛闁告鍋為悵婵嬫倵鐟欏嫭绀€闁绘牕銈搁妴浣肝旈崨顓犲姦濡炪倖甯掔€氼剟宕归崒鐐寸厱閻忕偛澧介埣銈吤瑰鍕煉闁哄瞼鍠栧鍫曞垂椤曞懏娈虹紓鍌欑椤戝懘鈥﹂悜钘夎摕闁挎繂鎳夐弨浠嬫煕閵夛絽濡挎い锔芥緲閳规垿顢欑涵宄颁紣濡炪値鍘奸崲鏌ユ偩閻戣棄绠抽柟瀛樻⒐閻庡姊洪悷鎵憼缂佽鍊块垾鏍ㄥ緞閹邦厸鎷绘繛杈剧悼閻℃棃宕甸崘顔界厱闁绘ê纾晶鐢告煙椤斿搫鍔﹂柟顔瑰墲閹棃鏁愰崱姗嗗晭闂傚倷绀侀幖顐⒚洪妸鈺佺？闁规壆澧楅崑鍌炴煏婢跺棙娅嗛柣鎾存礃閵囧嫰骞囬崜浣瑰仹缂備胶濮佃摫闁靛洤瀚伴弫鍌炲传閸曨偒娼庢繝娈垮枛閿曘儱顪冮挊澹╂盯宕橀…瀣秺婵″爼宕卞▎宥佸亾閹烘嚚褰掓偑閸涱垳鏆ら梺鐟扮－閸嬨倖淇婇悜钘壩ㄩ柕蹇曞С婢规洖鈹戦悙鏉戠仧闁搞劍妞介崺娑㈠箳濡や胶鍘遍柣蹇曞仦瀹曟ɑ绔熷鈧弻宥堫檨闁告挻宀搁獮鍐磼濮樿鲸娈鹃梺鍦濠㈡绮婚悷鎳婂綊鏁愰崨顔藉枑闂佹寧绋掗悷鈺呭箖濡ゅ懏鍋￠柡澶嬵儥娴犻箖姊洪棃鈺冩偧妞ゃ儲鍔欐俊鐢稿箛閺夎法顔婇梺鐟邦嚟婵挳鍩€椤掑倸浠滄い顏勫暣婵″爼宕卞Δ鈧鎴︽⒑缁嬫鍎愰柟姝岊嚙椤洨鎷犲ù瀣杸闁诲函缍嗛崑鈧柟閿嬫そ濮婄粯绗熼崶褌绨介梺绋款儐閻╊垶骞婇悢纰辨晬婵炴垶鐟﹂悵鐑芥⒑閸︻叀妾搁柛鐘愁殜閹€斥槈閵忊€斥偓鍫曟煟閹邦厼绲婚柍閿嬫閺屾洟宕卞Ο鐑樿癁闂佸搫鑻粔鐑铰ㄦ笟鈧弻娑㈠箻閸楃偛顬嬬紓浣戒含閸嬨倕鐣烽崡鐐╂婵☆垳銆嬬槐閬嶆⒒娴ｅ憡鍟炲〒姘殜瀹曘垺銈ｉ崘銊﹁緢闂佹寧妫冮弫顕€宕戦幘璇茬濠㈣泛锕ｆ竟鏇㈡⒒娴ｅ憡鍟炴繛璇х畵瀹曟粌鈽夐姀鐘插亶闂傚倸鐗婃笟妤€銆掓繝姘厪闁割偅绻冮ˉ鐐烘煃闁垮濮堥柕鍥у楠炲鎮欓崹顐㈡珣婵＄偑鍊ら崢鐓幟洪銏㈠祦闁搞儺鍓氶崑瀣煕椤愮姴鐏╅悽顖炵畺濮婄粯鎷呯粙娆炬闂佺顑嗙敮鈥崇暦濠婂啠妲堥柕蹇娾偓鍏呮偅闂備礁澹婇悡鍫ュ磻閹烘垟鏋斿ù鐘差儐閻撶喖鏌熼柇锕€骞楃紓宥嗗灥閳规垿顢欓懖鈺佲叺闂佸搫鐬奸崰鏍€佸☉妯锋婵炲棙蓱椤ュ牊淇婇悙顏勨偓鎴﹀垂濞差亝鍋＄憸鏃堢嵁韫囨稒鍋愰悹鍥皺閻撴垶绻濋姀锝嗙【妞ゆ垵鎳樺铏緞閹邦厸鎷婚梺绋挎湰閼归箖鍩€椤掍焦鍊愮€规洘鍔欓獮鏍ㄦ媴閸濄儻绱┑锛勫仜椤戝懎霉閻戣姤鍎楅柛鈩冦仠閳ь剚甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愭亽鈧啴宕ㄧ划鍏夊亾閿曞倸惟闁宠桨绶氶崬璺衡攽閻樼粯娑ч柣妤€绻愰悾鐑藉醇閺囩啿鎷绘繛杈剧悼閻℃柨顭囬幇顒夌唵闁荤喓澧楅ˉ鐐烘煛閸涚増纭鹃摶鏍煕濞戝崬骞橀柨娑欑洴濮婅櫣绮欑捄銊т紘闂佺顑囬崑銈夊箖閿熺姴唯闁冲搫鍊婚崢浠嬫⒑閸濆嫬鈧湱鈧瑳鍥х畾闁割偀鎳囬崑鎾斥槈濞嗘垹鐤勫┑顔硷攻濡炰粙骞愭繝鍐ㄧ窞濠电姴鍟宥夋⒒娴ｅ憡鎲稿┑顔炬暬閹囨偐瀹割喖娈ㄦ繝鐢靛У閼圭偓鍎梻渚€娼чˇ顓㈠垂濞差亜妫橀柍褜鍓熷缁樻媴閾忓箍鈧﹥淇婇悪娆忔搐閻ょ偓绻濇繝鍌涘櫧闁瑰啿鎳樺濠氬磼濞嗘劗銈板銈嗘礃閻楃姴鐣疯ぐ鎺戠闁芥ê顦遍悰銉╂⒑閸濆嫯鐧侀悘鐐插⒔缁嬩焦绻濋悽闈涗粶婵☆垰锕ョ粋宥呪攽鐎ｅ骸顦靛畷濂告偄閾忚鍟庨梻浣侯攰閹活亞绱炴笟鈧畷顐⒚洪鍛異闂佸搫绋侀崢浠嬪煕閹烘嚚褰掓晲閸曨噮鍔呴梺缁樺笧閸嬫挾鎹㈠☉姘ｅ亾閻㈡鐒鹃柛妯侯嚟閳ь剝顫夊ú妯好洪悢闀愮箚闁割偅娲栭悙濠囨煃閸濆嫬鏆熼柛鏂跨秺濮婄粯鎷呴崨濠呯闂佺绨洪崐婵嬬嵁閹邦厹鍋呴柛鎰ㄦ杹閹稿啴姊洪崨濠冨闁搞劑浜堕幃锟犲即閻旇櫣顔曢梺鐟邦嚟閸嬫劕危閸儲鐓曟い鎰Т閸旀氨绱掗悪鈧崹鍫曞蓟濞戞ǚ鏀介柛鈩冾殢娴犻亶姊虹悰鈥充壕婵炲濮撮鍡涙偂閻斿吋鐓欓梺顓ㄧ畱閻忥紕鐥銏㈢暫闁哄矉绠撳畷鐔碱敊闂傚瓨鐫忛梻渚€鈧偛鑻晶鍙夈亜椤愩埄妲搁悡銈嗙節婵犲倻澧曢柡瀣╃窔閹綊宕堕鍕闂佸搫妫寸粻鎾诲蓟閺囷紕鐤€闁哄洨鍊☉娆庣箚闁圭粯甯炴晶锕傛煛鐏炵偓绀夌紒鐘崇洴婵＄柉顦撮柨娑氬枛濮婃椽宕ㄦ繝蹇氣偓鍨瑰鍡樼【妞ゎ偄绻橀幖鍦喆閸曨偅鐎梻浣告啞濞诧箓宕戦崱娴板洭濡搁妷銏℃杸闂佺粯鍔曞Ο濠偽ｈぐ鎺撶厽闁冲搫锕ら悘鐘炽亜閺囶亞绉€规洏鍔嶇换婵嬪礃閵娿儱韦濠碉紕鍋戦崐銈夊磻閹烘绀傛繛鎴炰亢婵娊鎮归崶褎鈻曟繛鎾愁煼閺屾洟宕煎┑鍥舵婵犳鍠栭崐鍧楀蓟濞戙垹惟闁靛鍎遍幆鐐电磽娓氬洤鏋涙い顓犲厴楠炲﹪鎮╁ú缁樻櫌闂佺鏈划锝囨閼碱剛纾介柛灞捐壘閳ь剛鍏橀幃鐐烘晝閸屾せ鍋撻敃鍌氱倞闁冲搫鍟╃粭澶愭⒑閸︻厼浜鹃柣锝庝簼缁傚秴顭ㄩ崟鈺€绨婚梺瑙勬緲婢у酣骞冮懖鈺冪＜闁绘﹢娼ф禒褔鏌嶈閸撴繈锝炴径濞掑搫顫滈埀顒勫Υ閸愨晝绡€闁稿本绮嶅▓鎯р攽鎺抽崐鏇㈠箠鎼达絿鐭嗛柛宀€鍋為悡鐘崇箾閺夋埈鍎愭繛鍛噽缁辨挸顓奸崨顕呮＆濠殿喖锕ら…宄扮暦閹烘埈娼╂い鎴ｆ娴滈箖鏌熼梻瀵割槮缁炬儳缍婇弻锝夊箣閿濆憛鎾绘煕閵堝懎顏柡灞剧洴楠炴﹢鎳犻澶嬓滈梻浣规偠閸斿秶鎹㈤崘顔嘉﹂柛鏇ㄥ灠閸愨偓濡炪倖鍔﹀鈧慨瑙勵殜濮婃椽鏌呴悙鑼跺濠⒀冨⒔缁辨帡鎮╅搹顐㈢闂佷紮缍侀弨杈╃紦娴犲顥堥柍鍝勫暟閳笺倖淇婇悙顏勨偓鏍箰閻愵剚鍙忛悗娑櫳戝▍鐘绘煟閹伴潧澧扮紒鈾€鍋撻梻浣圭湽閸ㄨ棄顭囪缁傛帒顭ㄩ崟顏嗙畾濡炪倖鍔х徊鍧楀箠閸ヮ煈娈介柣鎰綑婵牏绱掔紒妯肩畵妞ゎ偅绻堥、妤呭磼閿旀儳鑰?",
            "task": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡▎鎴犫敍闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼宕滆绾惧ジ鏌ｅΟ鎸庣彧閻忓浚鍙冮弻锝夋晲婢跺鏆犵紓浣芥閺咁偆鍒掑▎蹇婃瀻闁绘劦鍓涚粔閬嶆⒒閸屾瑨鍏岄柛瀣ㄥ姂瀹曟洟鏌嗗鍛焾闁荤姵浜介崝蹇旀叏閹惰姤鐓忓璺烘濞呭棝鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡樺窛闁硅棄鍊圭换娑㈠礂閻撳骸顫屽銈庡幖濞硷繝骞冮悜鑺ュ亱闁割偒鍋呴敍渚€姊绘担鍛婃儓闁硅櫕鎸搁埢鏂库槈濠婂懍绨烽梻鍌欑閹测剝绗熷Δ鍛偍濡わ絽鍟弲顒佺箾閹存瑥鐏柣鎾跺枛楠炴牠骞栭鐐典化缂備礁顦遍弫濠氬蓟濞戙垺鍋愰柟棰佺劍閻や線姊虹拠鈥虫珯缂佺粯绻傞锝夊箻椤旂⒈娼婇梺鎸庣☉鐎氼剛鏁Δ鍛拻濞达絽鎽滈弸鍐╀繆濡炵厧濡跨紒顔肩墛缁楃喖鍩€椤掆偓椤曪綁骞庨懞銉ヤ簻闂佺绻楅崑鎰板储閹炬剚娓婚柕鍫濇婢ь剛绱掔€ｎ偄绗х紒顔肩墢閳ь剨缍嗛崰妤呮偂濞戙垺鍊堕柣鎰絻閳锋棃鏌曢崱妯烘诞闁哄苯绉烽¨渚€鏌涢幘鍗炲妤犵偐鍋撻梺闈涱槴閺呮稓绮堢€ｎ偁浜滈柟鐑樺灥閳ь剙鎽滃濠冦偅閸愨斁鎷婚梺绋挎湰閻熝呯玻閺冣偓缁绘稒鎷呴崘鎻掑箻婵炲樊浜滃洿闂佹悶鍎荤徊鑺ョ閻愵剚鍙忔慨妤€妫楁禍婊呪偓瑙勬尭濡繈寮婚敐鍛闁告鍋為悵婵單旈悩闈涗沪閻㈩垱甯熼悘鍐⒑闁偛鑻晶鎵磼椤旂⒈鐓奸柡浣瑰姍瀹曞崬鈻庨幋鐘愁潓闂傚倷绀佹竟濠囨偂閸儱纾婚柛鏇ㄥ墯閸欏繘鏌涢幇闈涙灍闁绘挻鐟﹂妵鍕即閻愭惌妫ら梺璇″枦閸嬫劗妲愰幒鎾寸秶闁靛绠戠壕鎶芥倵鐟欏嫭绀冮悽顖涘浮閸┿垺鎯旈妸銉ь唺闂佺懓鐡ㄧ换鍌炴嚈閹邦厾绡€闁汇垽娼ф牎濡炪倖姊归悧鐘茬暦鐟欏嫬顕遍柟纰卞幗閺咁亜顪冮妶鍡樺暗濠殿喚鏁婚敐鐐哄即閵忥紕鍘介梺褰掑亰閸擄箓宕甸悢鍏肩厽闁绘棃顥撶粔娲煛鐏炵晫啸妞ぱ傜窔閺屾盯骞樼€靛憡鍣板銈冨灪瀹€鎼佸极閹版澘骞㈡繛鍡樺灩濡插洦绻濆▓鍨灍闁挎洍鏅犲畷銏ゅ礂閼测晩娲稿┑鐘诧工閻楀﹪鍩涢幋鐘电＜閻庯綆鍘界涵鍓佺磼閻樿櫕銇濋柡灞剧〒閳ь剨缍嗛崑鍕叏瀹ュ洠鍋撶憴鍕缂佽鐗撻獮鍐煥閸喎娈熼梺闈涱槶閸ㄨ櫣鈧艾銈稿缁樻媴閸涘﹨纭€濡炪値鍘奸悧蹇涘焵椤掍胶鈻撻柡鍛箖缁旂喖寮撮姀鈥充缓闂佸憡绋戦敃锕傚储闁秵鐓熼幖鎼灣缁夌敻鏌涚€ｎ亝鍣藉ù婊勬倐閹囧醇濞戞鐩庨梻渚€娼ч…顓犲緤娴犲绀夐柨鏇炲€归悡娆愩亜閺冨倹娅曢柟鍐叉处椤ㄣ儵鎮欑€电鈷屽銈冨灪閿曘垽骞冮姀銈嗗€绘俊顖涙た閸熷秹姊婚崒姘偓鎼佸磹閹间礁纾圭紒瀣紩濞差亜围濠㈢櫢绠戝ú顓㈠箖閻ｅ瞼鐭欓柤鎰佸灡閹蹭即姊绘担鐟邦嚋缂佽鍊块獮澶婎潨閳ь剟骞冮姀銈呬紶闁告洦鍓涢埀顒佸▕濮婃椽宕ㄦ繝搴㈢暭闂佺顑嗛惄顖炴晲閻愬樊娼╅柤鍝ヮ暯閹风粯绻涙潏鍓ф偧妞ゎ厼鐗撻獮鍐箣閻愮數鐦堥梺闈涚箚閸╂顢旈崼姘ｅ亾閿曞倸鐐婃い鎺嶇劍濞呫垽姊虹紒姗嗙劸閻忓浚浜獮妤呭即閵忊檧鎷洪梺缁樺姌濡嫰宕濆杈╂／缂備降鍨瑰顔锯偓娈垮枟婵炲﹤鐣烽崡鐐╂婵炲棗绻嗛崑鎾绘偨閸涘﹦鍙嗗┑鐘绘涧濡繈顢撳Δ鈧…鑳槺闁告濞婂濠氭晸閻樻彃鑰块梺褰掑亰閸忔﹢宕戦幘鏂ユ斀閻庯綆浜為悾鍝勨攽鎺抽崐鎰板磻閹剧粯鐓冪紓浣股戝畷宀€鈧娲栫紞濠囥€佸▎鎾村仼閻忕偛銈搁崑妤呮⒒閸屾艾鈧娆㈠璺虹劦妞ゆ帒鍊告禒婊堟煠濞茶鐏￠柡鍛板煐鐎佃偐鈧稒顭囬崢閬嶆⒑閹稿海绠撻柛鐕佸亰瀹曟繂顫濈捄铏诡攨闂備緡鍓欑粔鐢稿磻閿濆鐓曢柕澶嬪灥鐎氀囧几濞嗗繆鏀介柣鎰摠鐏忣厽銇勯鐘插幋鐎殿喖顭峰鎾閻樿鏁规繝鐢靛█濞佳兠洪妶鍛瀺闁靛牆娲ㄧ壕钘壝归敐鍥剁劸闁逞屽墯閹倿銆侀弽銊ョ窞闁归偊鍓濋幗鏇炩攽閻愭潙鐏﹂柛鈺佸暣瀹曟垿骞樼紒妯绘珳闁圭厧鐡ㄧ换鍕礄瑜版帗鈷戦梻鍫氭櫇鐎佃偐绱掗鐣屾噰鐎殿喖顭烽幃銏ゆ嚃閳轰胶銈﹂梻浣稿閻撳牓宕板顓狀浄濠靛倸鎲￠埛鎴︽倵閸︻厼校妞ゃ儱顦伴妵鍕晝閳ь剟鎮樺璺虹疄闁靛ň鏅涢悞鍨亜閹烘垵顏柣鎾跺枑娣囧﹪顢涘☉鍗炲妼闂佹悶鍊栭悷鈺呭蓟閳╁啯濯撮柛婵勫劤妤旀繝娈垮枛閿曪妇鍒掗鐐茬闁告稑鐡ㄩ幆鐐烘煟閻旂顥嬫い鎰悑缁绘繄鍠婂Ο娲绘綉闂佺顑呯€氭澘鐣烽婊冾棜閻庯綆鍋撶槐鎾绘⒒閸屾瑦绁版い顐㈩樀瀹曟洟骞庣粵瀣櫔濡炪倖鎼╁鍧楀焵椤掆偓閹虫﹢骞冨鍫熷殟闁靛／鍐ㄧ疄濠电姷鏁告繛鈧繛浣冲應鍋撳鐓庡⒋鐎规洘绻堟俊鍫曞炊閳哄偊绱￠梻浣侯攰椤宕濋弽顓勫寰勯幇顓ф⒖婵犮垼鍩栭崝鏍偂閵夛妇绡€闂傚牊绋掗ˉ鐐烘煕閿濆牜娼愰柕鍥у婵＄兘濡疯椤旀帡姊洪崫鍕拱缂佸甯￠獮鍡涘籍閸喐娅栭梺鍛婃处閸欏酣宕ぐ鎺撯拻濞撴埃鍋撴繛浣冲厾娲Χ閸ワ絽浜炬慨姗嗗亜瀹撳棛鈧鍣崑濠傜暦閹烘鍊烽柡澶嬪灍閸嬫捇鏌ㄧ€ｃ劋绨婚梺鐟版惈缁夊爼宕濆澶嬬厽闁挎棁濮ゅ畷宀勬煛瀹€瀣ɑ闁诡垱妫冩俊鑸垫償閵忋垻啸濠电姷鏁搁崑娑橆嚕閸洘鏅俊鐐€ゆ禍婊堝疮椤栨粎鐭夐柟鐑樻煛閸嬫捇鏁愭惔婵堝嚬濠碘€虫▕閸撶喎顫忓ú顏呯劵闁绘劘灏€氭澘顭胯閸ㄥ爼寮婚弴銏犵倞鐟滃秹顢旈鐕佹闁绘劖娼欑粭鎺撱亜閹惧啿鎮戠€垫澘瀚埀顒婄悼椤ｄ粙宕戦幘璇插唨闁靛ě鍜佸晭闂佽瀛╃粙鎺椻€﹂崶顒佸剹閻庯綆鍓涚壕鍏笺亜閺冨洤袚鐎规洖鐬奸埀顒侇問閸犳牠鈥﹂悜钘夌畺闁靛繈鍊曠粈鍌炴煟閹惧磭宀搁柛瀣尵缁辨帒螣閸︻厾鐣炬俊鐐€栭悧妤冩崲閸愵噮鏁傞柣妯款梿瑜版帗鍋愰柧蹇ｅ亜閸炲鈹戦纭锋敾婵＄偘绮欏濠氬川鐎涙ê鈧兘鏌ら懝鐗堢【妞ゅ浚鍘界换婵嬪煕閳ь剛浠﹂懞銉у綆闂備礁鎼張顒勬儎椤栨稒鍙忛柍褜鍓熼弻銊モ槈濡警浠奸悗娈垮枔閸旀垵顫忛搹鐟板闁哄洨鍠愬鎾绘⒑閹肩偛濮€婵炲拑绲块崚鎺斺偓锝庡枛缁犳娊鏌￠崒姘儓濞存粓绠栭弻銊モ攽閸℃ê娅ф繛瀵稿У閻╊垶寮婚敓鐘插窛妞ゆ柨澧介悡澶娾攽椤旂》鏀绘俊鐐舵閻ｅ嘲顭ㄩ崼婵堫唽闂佺懓鎼粔鍫曞极閺嶎厽鈷掑ù锝呮啞閹茬鈹戦鐐毈妤犵偞鍨垮畷鎯邦槾闁哄棴绠撻弻鏇＄疀鐎ｎ亖鍋撻弽顓熷€块柤娴嬫杹閸嬫捇鐛崹顔煎濠碘槅鍋呴惄顖氱暦閵忥紕顩烽悗锝庡亽濡懎顪冮妶鍡楀闁搞劎鍎ゅ鍕礋椤掑倻顔曢梺鍛婄懃椤﹁鲸鏅堕鍌滅＜闁稿本绋戠粭鈺傘亜閿曗偓缂嶅﹪寮婚敍鍕勃闁告挆浣插亾閹烘鐓冪憸婊堝礈閵娧呯闁糕剝绋戠壕濠氭煕濞戝崬骞橀柡鍡閳ь剙鍘滈崑鎾绘煕閺囥劌澧伴柛姗€娼ч—鍐Χ閸℃瑥顫ч梺鐓庣秺缁犳牕顕ｉ幎鑺ユ櫜闁糕檧鏅滈鏃堟⒑缂佹ê濮囨俊顖氾躬瀹曟洟寮崼鐔哄幐婵炶揪绲块…鍫ュ焵椤掆偓濞硷繝鐛崘顔肩鐟滃苯鈻介鍫熺參婵☆垯璀﹀Σ鐑樸亜閺傛寧鎼愰柍瑙勫灴閹晠宕归锝嗙槑濠电姵顔栭崰鏇㈠础閸愯尙鏆︾憸鐗堝笚閸嬪倿骞栫€涙〞鎴︽倶閸愩劉鏀介柣鎰綑閻忓秹鏌熷畷鍥т槐鐎规洖鐖奸、妤佹媴閸濆嫬笑闂佽楠哥粻宥夊磿閸楃倣娑樜旈崨顓狀槶闂佽崵鍠愭竟瀣绩娴犲鐓熼柟閭﹀墮缁狙勩亜閵壯冧槐闁哄瞼鍠撶划娆忊枎閸撗冩倯闂備浇顕栭崰鎺楀焵椤掍焦鐏辨俊鎻掔墛閹便劌顫滈崼銏犲煂婵炲瓨绮撶粻鏍蓟濞戞粎鐤€闁瑰灝鍟瑧濠电偛鐡ㄧ划鎾剁不閺嶎厼钃熼柨婵嗘閸庣喐銇勯弽銊х煂閺嶏繝姊绘担鍛婂暈闁圭顭烽幃鐑藉煛娴ｇ儤娈鹃梺鎯х箻閳ь剚绋掗崟鍐磽娴ｅ湱鈽夋い鎴濇閳ь剟娼ч惌鍌氼潖濞差亝顥堟繛鎴炶壘椤ｇ儤淇婇妶鍥ｉ柟顔煎€块幃浼搭敋閳ь剟鐛€ｎ喗鏅滈柣锝呰嫰楠炲牓姊绘担鍛婃儓闁哥喓濞€瀹曟垿骞樼紒妯煎幈闂侀潧臎閸曨剚鐦撻梻浣筋嚃閸犳宕曢幎鑺ュ仼闁跨喓濮甸悞浠嬫煥閺冨洦顥夌紓鍌涙崌濮婄粯绗熼埀顒勫焵椤掑倸浠滈柤娲诲灡閺呭爼顢涘В鎻掗叄瀹曟儼顧傜€规悶鍎查妵鍕敃閻樿尙浠奸梺浼欑稻缁诲啰鎹㈠┑瀣闁告劖鍎虫晶顖滅磼缂佹绠為柟顔荤矙濡啫鈽夊Δ鍐╁礋濠碉紕鍋戦崐褏绮婚幋锕€鐤柛褎顨呴悡婵嬫煛閸愩劎澧曢柛妤佸▕閺岋絽螣鐠囨彃顫┑鐐跺亹閸犳牕顫忛搹瑙勫枂闁告洦鍋嗛ˇ銊ヮ渻閵堝棙鑲犻柛娑卞弾濡粓姊虹粙璺ㄧ闁稿鍔楃划缁樸偅閸愨晝鍘遍梺鏂ユ櫅閸橀箖顢旈崨顔煎伎婵犮垼鍩栭崝鏍偂韫囨稒鐓曟い鎰Т閻忊晜銇勯敐鍥у付閼挎劙鏌涢妷鎴濈Х閸氼偊姊虹拠鈥虫灍闁荤啙鍥х劦妞ゆ帊鑳堕埊鏇熴亜椤撶偞宸濈紒顔界懇瀹曞爼顢楁担鍙夊缂備胶铏庨崢濂稿箠鎼淬値鏆辩紓鍌氬€风欢锟犲窗濡ゅ懎绠查柛銉墯閸嬫ɑ銇勯弴妤€浜惧Δ鐘靛仜椤戝寮崘顔肩劦妞ゆ帒瀚哥紞鏍煕濞戞鎽犻柣鎾崇箻閺屾盯顢曢敐鍥╃暫闂佹悶鍊曞ú顓㈠蓟濞戙垺鍊烽柤鍝ユ暩閵嗘劙姊虹€圭媭娼愰柛銊ユ健楠炲啴鍩￠崘顏嗭紲濠碘槅鍨伴…鐑藉极椤忓牊鈷掑ù锝堟鐢稒銇勯妸銉﹀殗闁轰礁鍟存俊鑸靛緞婵犲嫬骞掗梻浣筋潐瀹曟﹢顢氳缁顫濇潏銊ユ瀾婵犮垼鍩栭崝鏇犵磼閳轰急褰掓偐瀹割喖鍓遍梺缁樻尭閸熸挳寮婚敃鈧灒濞撴凹鍨辨晥婵＄偑鍊戦崕鑼垝閹捐钃熼柨婵嗙墢閻も偓闂佸搫娲ㄩ崑鐐烘倶閸儲鈷戦悹鍥ｂ偓铏亪缂傚倸绉撮敃顏勭暦濞差亜鐒垫い鎺嶉檷娴滄粓鏌熼悜妯虹仴妞ゅ浚浜弻锟犲川椤斿墽鐤勯梺鍝勬湰缁嬫挻绂掗敃鍌氱煑闁靛鍊曢銏ゆ煟閻愬顣茬紒璇茬墕椤繘鎼圭憴鍕彴闂佸湱绮敮鎺懶掗幇顔剧＝闁稿本姘ㄥ瓭濠碘槅鍋呴悷褏鍒掔€ｎ亶鍚嬪璺猴躬閸炲爼姊洪崫鍕窛闁哥姴瀛╃粋宥咁煥閸啿鎷虹紓渚囧灡濞叉牗鏅堕懠顒傜＜閻庯綆鍋勫ù顔锯偓瑙勬礃閸ㄥ潡寮幇顓炵窞閻庯綆鍓欏浼存⒒婵犲骸浜滄繛璇х畱鐓ゆ慨妞诲亾鐎规洜鏁婚崺鈧い鎺戝閳锋垿鏌涘☉姗堟敾闁绘挶鍎查妵鍕箣濠靛浂妫︽繝纰夌磿閺佽鐣烽悢纰辨晬婵絿顑曢崝搴ㄥ箟缁嬫鍚嬮柛鈩冪懐濞村嫰姊绘笟鍥у缂佸鏁婚幃鈥斥槈閵忊€斥偓鍫曟煟閹邦収鍟忛柣鎺撳劤椤儻顦抽柣鎿勭節瀵鎮㈡搴㈡疂闂佺粯顨呴悧鍡椻枔濡ゅ懏鍊甸悷娆忓缁岃法绱掗崣澶婂姢妞ゆ洏鍎靛畷鐔碱敇濞戞ü澹曢梺鎸庣箓妤犲憡鏅堕鍓х＜闁圭粯甯掗埛鏃傜磼鏉堛劍宕岀€规洘甯掗～婵嬵敄閽樺澹曢梺缁樺灱婵倝宕甸崟顖涚厱闁规崘灏欓ˇ锕傛煕閵婏妇绠栭柕鍥у瀵粙顢曢～顓熷媰闂備胶顭堟鍝モ偓娑掓櫊婵＄敻宕熼姘敤濡炪倖鍔﹀鈧柟瀵稿厴閹鎲撮崟顒€鐭紓浣藉煐瀹€鎼佺嵁閸愩剮鏃堝川椤旇姤鐝抽梺纭呭亹鐞涖儵宕滃┑瀣€剁€广儱顦伴埛鎴犵磼鐎ｎ亜鐨￠柛鏃傚枛閺屾稖绠涢弮鎾光偓璺ㄢ偓娈垮枛椤兘宕洪崟顖氱闁靛ě鍛祦闂備浇顕ч崙鐣岀礊閸℃顩查柣鎰嚟椤╃兘鏌ｉ幘鍐茬槰婵炴挸顭烽弻鏇㈠醇濠靛牏顔婄紓浣割儏椤兘寮婚敐澶婄妞ゆ牗顨呮禍楣冩煙妫颁胶鍔嶇紓宥呮捣缁辨捇宕掑▎鎴濆闁藉啫宕埞鎴︻敍濞戞瑥鍞夐梺鍝勭焿缂嶄線骞冮姀銈嗗亗閹煎瓨绻傞弸鍫ユ⒒娴ｈ鍋犻柛濠冩礋椤㈡牠宕ㄩ弶鎴犲幋闂佺鎻梽鍕磹瀹勬嫈娑㈡偋閸垻鐣靛┑鐐茬墛缁诲牆顫忔繝姘＜婵﹩鍓︽禒濂告煟鎼淬垹鍤柛鐘冲哺瀹曟岸骞掗弬鍝勪壕闁挎繂绨奸幉楣冩煕濮橆剦鍎忔い顓炴健閹虫粓鎯夐鍛伌鐎殿喗褰冮…銊╁醇閻斿弶瀚奸梻浣告啞閹告槒銇愰崘鈺冾洸婵犻潧鐗忕壕濂告偣閸ャ劌绲绘い蹇ｅ弮閺岀喖顢欓挊澶婂Б闁绘挶鍊栭妵鍕疀閹炬潙娅濋梺褰掓敱濡炶棄顫忓ú顏勫窛濠电姴瀚悾鐢告煟鎼淬垼澹橀柛銏″絻瀹撳嫰姊洪崨濠勭細闁稿骸纾竟鏇熺附閸涘﹦鍘繝鐢靛仧閸嬫挸鈻嶉崘顔界厵闁圭粯甯掗埛鏃堟煃瑜滈崜姘额敊閺嶎厼绐楅柡宥庡幖缁犵喖鏌ㄩ悢鍝勑㈢紒鐘冲哺閺岋繝宕橀妸褍顣洪柟顖滃枛濮婃椽骞愭惔鈶╂嫻闂佺瀛╂繛濠囨偘椤旂⒈鍚嬪璺侯儌閹锋椽鏌ｉ悩鍙夋悙鐎殿喖鐖奸獮鎴︽晲婢跺鍘告繛杈剧秬椤宕愰幇鐗堢厓闁靛鍨抽悾鐢碘偓瑙勬礀閵堟悂骞冮姀锛勭懝妞ゆ牗绋撻妶顐⑩攽閻樺灚鏆╁┑顔芥尦閺佸啴濡舵径瀣罕婵犵數濮村ú锕傚磻閸岀偞鐓熼柡鍌涘閹插摜绱掗埦鈧崑鎾绘⒒閸屾艾鈧悂鎮ф繝鍕煓闁规儳鐡ㄥ▍鐘绘煛閸モ晛鏋傚ù婊勭矒閺屻劌鈹戦崱娆忣暫婵炲瓨绮屽﹢杈╂閹烘挻缍囬柕濞垮劤椤戝倻绱撴担浠嬪摵閻㈩垱甯熼悘鎺楁煟韫囨挾绠查柣妤佹礋閿濈偟浠﹂崜褏鐦堥梺姹囧灲濞佳勭瑜旈弻娑樜熼悩鍙夊櫤鐎规洖寮舵穱濠囶敍濠靛浂浠╅梺鍝勬４闂勫嫮鎹㈠┑鍥╃瘈闁稿本鍐荤槐鐐测攽閳╁啰鍙€缂佺姵鐗犻獮鍐崉娓氼垱鍍甸梺鍛婃寙閸氶攱鍨剁换娑㈡晲閸涱喗鎮欓梺鎸庢处娴滎亪鐛崘銊㈡瀻闁瑰灝鍟弲婊堟⒑閸涘﹥纾搁柛鏂挎湰缁傚秵銈ｉ崘鈺冨帾闂佸壊鍋呯换宥呂ｉ崫銉ф／闁诡垎宀€鍚嬮梺鍝勬湰閻╊垰顕ｉ幘顔嘉╅柕澹偓閸嬫捇顢楅崟顒傚幈闂侀潧顦介崰鏍ㄦ櫠椤栫偞鐓熼柟鐑樻礀娴滃綊鏌嶈閸撴瑧绮诲澶婄？闁告鍊ｅ☉妯滄梹鎷呮笟顖涚カ婵＄偑鍊栭幐鍫曞垂濞差亜纾婚柍鈺佸暟缁♀偓婵犵數濮撮崐鎼侇敂椤忓牊鐓熼柟鎯у船閸旀粓鏌曢崶褍顏い銏℃礋婵偓闁靛繈鍩勯崬铏圭磽閸屾瑦绁板鏉戞憸閺侇噣骞掗弴鐘辫埅闂備浇宕垫慨鏉懨洪妶鍛傜喐绻濋崶褏鍔﹀銈嗗笂閻掞箑鐣风仦鐐弿濠电姴鍟妵婵堚偓瑙勬磸閸斿秶鎹㈠┑瀣闁靛瀵屽鏃堟⒒閸屾瑧鍔嶉悗绗涘厾楦跨疀濞戞锛欏┑鐘绘涧濡參宕甸弴銏＄厵闁诡垳澧楅ˉ澶愭⒑閸楃偞鍠橀柡灞炬礃瀵板嫬鈽夊鍐╁€曢梻浣告贡閺屽鈻嶉敐鍥潟闁规崘顕х壕鍏肩箾閸℃ê鐏ュ┑鈥茬矙閺岋箓宕橀銏犳懙闂侀潧娲ょ€氱増淇婇悜鑺ユ櫆缂佹稑顑嗛ˉ鍫ユ⒒娴ｅ憡鎯堥柡鍫墴閹嫰顢涢悙闈涚ウ濠碘槅鍨伴惃鐑藉磻閹剧粯顥堟繛鎴烇供濡矂姊洪崫鍕紨缂佽鲸娲滃Σ鎰板箻鐎涙ê顎撻梺鍛婄缚閸庢娊宕濋鎴掔箚闁绘劕鐡ㄧ紞鎴︽煙閼恒儳鐭掓鐐村灴婵偓闁绘﹩鍋呴弬鈧梺璇插嚱缂嶅棙绂嶉悙鍝勭９闁绘劗鍎ら崑鈩冪節婵犲倸鏆熺紒鐘哄吹閳ь剝顫夊ú姗€宕濆▎鎾崇畺婵炲棙鎸婚崐缁樹繆椤栨繃銆冮柣銏㈢帛缁绘繈鎮介棃娴躲垽鏌ㄩ弴妯衡偓妤呭焵椤掍礁鍤柛鐘虫皑閸掓帗绻濆顓炩偓鐑芥煟閹寸儐鐒介柛妯兼暬濮婃椽骞嗚缁傚鏌涚€ｎ亝鍣归柣锝呭槻閻ｆ繈鍩€椤掑嫬鐒垫い鎺戝枤濞兼劖绻涢崣澶岀煉闁炽儻绠撳畷濂告晲閸ワ妇鑳哄┑鐘垫暩閸嬬娀骞撻鍡楃筏濞寸姴顑呯粻瑙勩亜閹扳晛鐒洪柛銈嗘礋閺岀喖骞嗛弶鍟冩捇鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡欏妞ゅ繒濞€閹粙顢涘☉姘垱闂佸搫鐭夌槐鏇熺閿旂偓瀚氶柟缁樺俯濞煎孩淇婇妶鍥ラ柛瀣仱閹囨偐濮瑰洠鍋撴笟鈧鎾閳╁啯鐝抽梻浣规偠閸庢粓鍩€椤掑嫬鐭楅柣鎰劋閳锋帡鏌涚仦鎹愬闁逞屽墯閹倸鐣烽幇鐗堝€婚柤鎭掑劚濞堟垿姊洪崜鎻掍簼婵炴彃绉归崺鈧い鎺戯功閻ｇ數鈧娲栭妶鎼佸箖閵堝棙濯撮悹鍥ｂ偓铏珫闂傚倸鍊风粈渚€骞夐敍鍕处闁秆勵殔绾惧潡鏌熼幆鏉啃撻柛搴㈩殜閺岀喖骞戦幇顒傚帿闂佸摜濮甸崝娆撳蓟閿濆憘鏃堝焵椤掑嫭鍋嬮柛鈩冪懅缁犳棃鏌熼悜姗嗘畷闁绘挶鍨介弻娑㈠箛閸忓摜鐩庨梺鍝勵儐閸ㄥ湱妲愰幒鏃傜＜婵☆垰鍚嬮崚娑樜旈悩闈涗粶妞ゆ垵鎳橀崺銏℃償閵堝洨鏉搁梺鍝勬处绾板秹宕戦崨瀛樷拻闁稿本鐟чˇ锕傛煙鐠囇呯瘈闁靛棗鍟村畷鍗炍熼懖鈺婂晭濠电姷鏁告慨鏉懨洪妶澶嬪珔闁绘柨鍚嬮悡娑㈡煕閵夈垺娅呴柡瀣⒒缁辨帡鎮╅懡銈囨毇闂佸搫鏈惄顖炲灳閿曞倸绠ｆ繝闈涙川娴滎亜鈹戦悩鎰佸晱闁哥姵顨呯叅闁绘柨顨庡鏍煣韫囨凹娼愰悗姘哺閺屻倗鍠婇崡鐐差潾濡炪倖鏌ㄩˇ闈涱潖濞差亝鍋￠柣妤€鐗嗛弳鍫ユ⒑鐠団€虫灈闁稿﹤鐏濋悾宄懊洪鍛偓鐑芥煕濠靛棗顏い鎾存そ濮婃椽骞愭惔銏紩闂佺顑嗛幑鍥蓟閿濆绠抽柟鐐暘娴犮垽姊洪崫鍕拱闁烩晩鍨堕悰顕€宕堕鈧悡娑樏归敐鍛棌闁诲酣顥撶槐鎾诲磼濞嗘劦妯傞梺鐓庡暱閻栫厧鐣峰Δ鈧灒濞撴凹鍨辩紞搴ㄦ⒑閹呯婵犫偓鏉堚晛顥氶柛蹇撳悑閸欏繑淇婇妶鍌氫壕濠碘槅鍋呴悷鈺呭箖妤ｅ啯鍊婚柤鎭掑劗閹锋椽姊洪棃鈺佺槣闁告ü绮欏畷鐢稿焵椤掆偓閳规垿鎮欓懠顒佸嬀闂佺锕ョ换鍫ュΥ娴ｅ壊娼╅柤绋跨仛濞呮粓姊虹化鏇炲⒉闁荤啙鍥ㄥ剨闁割偅绺鹃弨鑺ャ亜閺冣偓閺嬬粯绗熷☉銏＄厱婵☆垱瀵чˉ澶愭煃鐠囪尙效濠殿喒鍋撻梺闈涚墕濡矂骞忛搹鍦＝闁稿本鐟ч崝宥夋煥閺囨娅婇柟顔惧仦閵堬綁宕橀埡浣插亾閸洜鍙撻柛銉ｅ妽閳锋帡鏌熼崘鍙夊枠闁圭锕ら埞鎴犫偓锝庡亞閸樺憡绻濋姀锝嗙【妞ゆ垶鍔欏畷鏇㈠Ψ閿斿墽顔曢梺鍦亾閸撴岸鎮℃總鍛婄厸閻忕偟鍋撶粈瀣偓瑙勬礈閸樠囧煘閹达箑鐐婇柤鍛婎問濡勭節閻㈤潧校妞ゆ梹鐗犲畷浼村冀椤撶偟锛欓梺绉嗗嫷娈旈柦鍐枑缁绘盯骞嬮悙鍨櫘缂備讲妾ч崑鎾绘⒒娴ｅ憡鍟為柛鏂跨箻瀵彃鈹戠€ｅ骸娲︾€佃偐鈧稒锚閳ь剛鏁婚幃宄扳枎韫囨搩浠剧紓浣插亾闁割偁鍎查悡娑樏归敐鍛棌闁绘挸銈搁弻鏇㈠幢閺囩媭妲柧缁樼墵閺屾稑鈽夐崡鐐茬闂佹寧绋掔划宀勫煘閹达附鍋愰悹鍥囧啩绱ｉ梻浣哥秺閺€閬嶅垂閻熸嫈锝夊箛閺夎法顦ㄥ┑鐐存綑椤戝棝寮埀顒勬⒒娴ｈ櫣甯涢柛鏃€娲熼幃娲Ω瑜岄悞濠偯归悡搴ｆ憼闁绘挾濞€閹嘲鈻庤箛鎿冧患闂佸憡鏌ｉ崐婵嬪箖閿熺姴围濠㈣泛顑囬崢顏呯節閻㈤潧浠ч柛瀣尭閳诲秹宕ㄧ€涙鍘遍柣蹇曞仩椤曆勪繆閻ｅ瞼纾肩紓浣诡焽缁犳牜绱掔紒妯肩疄鐎规洘甯掗埥澶娢熷ú璁虫缂傚倸鍊烽懗鍫曞磻閹惧磭鏆︽慨妞诲亾鐎规洘鍨块獮鍥敊缁涘缍楅梻浣筋潐閸庢娊鎮洪妸锕€鍨旈柟缁㈠枟閸嬶綁鏌涢妷鈺婃缁炬儳娼￠弻娑㈠籍閸偅顥栫紓浣介哺閹稿骞忛崨鏉戜紶闁告洘鍨崕鐢稿蓟濞戞埃鍋撻敐鍐ㄥ闁逞屽墯缁诲倿顢氶敐鍡欑瘈婵﹩鍘藉▍婊堟⒑閸涘﹣绶卞ù婊勭箞閿濈偛顓兼径瀣ф嫼闂佸憡绋戦…顒€鈻撳鈧弻娑氣偓锝庡墮娴犻亶鏌熼鈧褔鍩為幋鐘亾閿濆骸浜愰柟鐤缁辨挻绗熼崶褏浠┑鐐插级閿曘垹顕ｉ幆鑸汗闁圭儤鎸鹃崢閬嶆煟鎼搭垳绉甸柛瀣噽娴滄悂顢橀悢缈犵盎濡炪倕绻愮€氼剟寮抽敐鍛斀闁炽儱纾崺锝団偓瑙勬礀瀹曨剝鐏冮梺鍛婂姦娴滄繈宕导瀛樷拻闁稿本鐟ㄩ崗宀勬煕濡姴娲ら悿顕€鏌熺粙鍨劉婵炲懐濞€楠炴牜鍒掔憴鍕垫綉闂佹悶鍊栧ú婊堝箟閹间礁绫嶉柛顐ｇ箖濡差剟姊洪柅鐐茶嫰婢ь垶鏌曢崶褍顏鐐村浮楠炲鈹戦幇顏嗘／闂傚倷鐒︽繛濠囧绩鏉堚晜鏆滈柨鐔哄Т閽冪喐绻涢幋鐐电叝婵炲矈浜弻锝夊箛闂堟稑顫┑鐐茬墑閸婃牜鎹㈠┑瀣厱闁逞屽墴瀹曠喖顢橀悢宄扮仭闂傚倷绀侀幖顐﹀嫉椤掑嫭鍎庢い鏍仧瀹撲線鏌涢妷顔煎⒒闁轰礁妫楅…璺ㄦ崉妤﹀灝顏梺璇″枟閸ㄥ潡寮婚敐鍡樺劅闁靛牆瀛╃紞鍫濃攽閻愭彃绾фい顓炴喘楠炴垿濮€閵堝懘鍞堕梺闈涱槶閸庢娊鎮惧ú顏呪拺闂傚牊绋撶粻鐐烘煕婵犲啯绀堢紒顔肩墦瀹曟帡鎮欑€电骞樻繝鐢靛仦濞兼瑩顢栭崱妞绘瀺闁告侗鍣▓?",
            "next_task": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡▎鎴犫敍闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼宕滆绾惧ジ鏌ｅΟ鎸庣彧閻忓浚鍙冮弻锝夋晲婢跺鏆犵紓浣芥閺咁偆鍒掑▎蹇婃瀻闁绘劦鍓涚粔閬嶆⒒閸屾瑨鍏岄柛瀣ㄥ姂瀹曟洟鏌嗗鍛焾闁荤姵浜介崝蹇旀叏閹惰姤鐓忓璺烘濞呭棝鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡樺窛闁硅棄鍊圭换娑㈠礂閻撳骸顫屽銈庡幖濞硷繝骞冮悜鑺ュ亱闁割偒鍋呴敍渚€姊绘担鍛婃儓闁硅櫕鎸搁埢鏂库槈濠婂懍绨烽梻鍌欑閹测剝绗熷Δ鍛偍濡わ絽鍟弲顒佺箾閹存瑥鐏柣鎾跺枛楠炴牠骞栭鐐典化缂備礁顦遍弫濠氬蓟濞戙垺鍋愰柛鎰絻閹界敻鎮楃憴鍕┛缂傚秳绶氶悰顔嘉熼懖鈺冿紲濠碘槅鍨抽崢褔鐛崼銉︹拻濞撴埃鍋撴繛浣冲毝銊╁焵椤掑倻纾奸柤鑹版硾琚氭繛锝呮搐閿曨亜鐣风粙璇炬梹鎷呴崫鍕瑲闂傚倷娴囨慨銈夋晪濡炪倧绠掑Λ鍕亽闂侀€炲苯澧存慨濠冩そ瀹曨偊宕熼鐘插Ы缂傚倸鍊哥粔顕€宕戦幘鍓佺＝濞达絽鎼牎缂備礁顑嗛崹鍧楁晲閻愭祴鏀介悗锝呯仛閺咃綁姊虹紒妯忣亜顕ｉ崼鏇熺叆妞ゆ挾鍠撶弧鈧梺姹囧灲濞佳囧礈瀹曞洨纾奸柤鑹板煐椤ュ鎮￠妶澶嬬厪闁割偅绻嶅Σ褰掓煛閸涱喚绠栭柕鍥у缁犳盯骞樼捄渚殽闂備線鈧偛鑻崢鍝ョ磼閳ь剚绗熼埀顒勫春閵夛箑绶炲┑鐘插瀵ゆ椽姊虹化鏇炲⒉闁挎岸鏌涜箛鎿勬敾濞ｅ洤锕幃娆擃敂閸曘劌浜鹃柡宥庡亝閺嗘粌鈹戦悩鎻掝伀闁活厼妫楅妴鎺戭潩閿濆懍澹曢梻浣虹《閺備線宕戦幘鎰佹富闁靛牆妫楃粭鎺撱亜閿旇鐏﹂柟顔斤耿閺佸秹宕熼鐙呯床缂傚倸鍊烽悞锕傗€﹂崶鈺冧笉闁瑰墽绮悡鍐磽娴ｈ偂鎴濈暦瀹€鈧埀顒冾潐濞叉牜绱炴繝鍥モ偓浣糕枎閹惧磭鐓戦梺闈涱槶閸庢煡骞夐姀銈嗏拻闁稿本鑹鹃埀顒勵棑濞嗐垹顫濋澶屽姺閻熸粍妫冮獮鍐槼缂佺粯绻堝畷鎯邦槾闁伙絾妞藉铏圭矙閹稿孩鎷遍梺鍛婂灥缂嶅﹤鐣烽悽绋垮嵆闁绘劏鏅滈弬鈧梻浣虹帛閿氶柣銈呮处缁旂喎顫滈埀顒勫蓟濞戞鏃€鎷呯化鏇熺亞闂備礁鎼張顒€煤濠靛牏涓嶆繛鎴欏灩閸楁娊鏌ｉ幇銊︽珕闁诲簼鍗冲缁樻媴閸涘﹥鍠愰梺绋款儑婵挳鍩㈤弬搴撴闁靛繒濮烽崢鎾⒑绾懏褰ч梻鍕瀹曟垿骞囬鍓э紳婵炶揪缍€閸嬪倿骞嬮敂鐣屽弳濡炪倖鎸鹃崑鎰板绩娴犲鐓冮柦妯侯槹椤ユ粌霉濠娾偓缁瑩寮诲☉妯滅喖宕楅崗鑲╁涧闂備線鈧偛鑻晶瀛樼箾娴ｅ啿娲ゅ洿闂佸綊妫跨粈渚€寮伴妷鈺傜厓鐟滄粓宕滃璺何﹂柛鏇ㄥ灠缁犳娊鏌熺€涙绠ュù鐘荤畺濮婃椽骞庨懞銉︽殸闁汇埄鍨辩敮鈥筹耿娓氣偓濮婃椽骞愭惔锝囩暤闂佺粯顨呴敃顏囨＂婵犮垼鍩栭崝鏍偂閺囩喐鍙忔慨妤€妫楁晶鎵磼婢跺銇濋柡宀嬬磿娴狅箓宕滆閸掓盯姊虹拠鈥虫灀闁哄懐濮撮悾宄邦潨閳ь剟鐛幘璇茬婵犻潧娲ㄧ粙鍫熺節瀵伴攱婢橀埀顒侇殕閹便劑鎮滈挊澶岋紱闂佺粯鍔曢幖顐ょ矆婢跺绠鹃柛鈩兩戠亸鐢碘偓瑙勬尫缁舵岸寮婚垾鎰佸悑闁告劑鍔岄‖澶嬬節濞堝灝鐏￠柟鍛婂▕瀵鈽夊Ο閿嬫杸闂佸憡娲﹂崑鍕叏鎼淬劍鍊垫繛鍫濈仢閺嬫棃鏌涢弬璺ㄧ劯闁糕晝鍋ら獮瀣晜閽樺姹楁俊鐐€栧Λ渚€宕戦幇顓烆嚤闁搞儺鍓氶埛鎴犵磼椤栨稒绀冩繛鍛閺岋絽螖閸愩剱銏ゆ煟閿濆懎妲婚柍瑙勫灩閳ь剨缍嗘禍婊冪暤閸℃稒鈷戠紓浣光棨椤忓牆瑙﹂柍褜鍓涚槐鎺懳旈埀顒勊囨潏鈺傤潟闁规崘顕х壕鍏肩箾閸℃ê鐏ュ┑鈥茬矙閺屻倝宕归敃鈧崢楣冩偡闁妇鍙嗛梺鍛婃处閸橀箖鎮℃径鎰拺闁告繂瀚ˇ顒勬煃瑜滈崜姘跺礈濮樿泛瑙﹂悗锝庡枟閻撴洟鏌熼幍铏珔濠碘€冲悑閵囧嫰顢楅埀顒勵敄婢跺娼栭柧蹇撴贡绾惧吋淇婇婊呭笡闁稿骸閰ｅ娲箹閻愭彃顬嗛梺鍛婎殕婵炲﹪宕规ィ鍐╂櫆闁绘劦鍓欑壕顖炴⒑闂堟侗鐓紒鐘冲灴瀵悂宕掗悙绮规嫼闂佸憡绋戦敃銉﹀緞閸曨垱鐓曢柟鎯ь嚟濞叉挳鎸婂┑瀣厪濠㈣泛妫欏▍鍡涙煃闁垮鐏撮柟顔筋殜瀹曠兘顢橀悜鍡忓亾鐏炲墽绠鹃柛蹇曞帶婵秹鏌＄仦鍓ф创濠碘剝鎮傛俊鐑芥晝閳ь剚绂掗幘顔藉€甸悷娆忓缁€鍐╀繆閻愯泛袚濞ｅ洤锕幃婊堟寠婢跺苯骞愬┑鐐舵彧缁查箖鎮洪弴銏犵劦妞ゆ巻鍋撻柣蹇旂箞閸╃偤骞嬮敂鑺ユ珫闂佸憡娲﹂崑鍌滃垝閼哥數绡€闁冲皝鍋撻柛灞剧矌閻撴捇鎮楀▓鍨珮闁稿锕ら锝夊磹閻曚焦啸闂備浇銆€閸嬫挸霉閻樺樊鍎愰柣鎾跺枑閹便劌螖閳ь剙螞濡や胶顩叉繝闈涙閺€鑺ャ亜閺嶃劎鎳冪€规挸妫濋弻锛勪沪閸撗勫垱閻庢鍠楅幐鎶藉箖濞嗘挸绀傞柛婵勫劦閳瑰繘姊婚崒娆愵樂缂侀硸鍠氬濠囨嚃閳轰礁鐏婂┑鐐叉濞存艾顭囬弽銊х鐎瑰壊鍠曠花濠氭煙绾懎鐓愰柕鍥у楠炴鎹勯惄鎺炵秮閺岀喖宕ｆ径娑溾偓鎸庢叏婵犲懏顏犵紒顔界懃閳诲酣骞嗚婢瑰牓姊虹拠鎻掝劉闁活収鍣ｅ畷锟犲礃閼碱剚娈惧┑鐐叉▕娴滄繈宕愰悜鑺ョ厱婵犻潧妫楅顐ｃ亜閹惧瓨銇濇慨濠冩そ楠炴劖鎯旈姀鈺傗挅婵犵妲呴崑鍕偓姘嵆瀹曟椽鍩€椤掍降浜滈柟鐑樺灥閳ь剚鎮傚畷銏ゅ箻椤旂晫鍘靛銈嗘⒒閻℃柨鈻撻弮鍫熺厓闁芥ê顦藉Σ鎼佹煃鐠囪尙效妞ゃ垺顭堥ˇ杈╃磼閵娿倗鐭欓柡灞剧洴閹晝鎷犺娴兼劕顪冮妶鍡樺碍闁告艾顑呴銉╁礋椤撴稑浜鹃柨娑樺船鐎氼剟顢旈崷顓犵＝闁稿本鑹鹃埀顒佹倐瀹曟劙鎮滈懞銉モ偓鍧楁煥閺囩偛鈧敻鍩€椤掑﹦鐣电€规洖鐖兼俊鎼佹晜閻ｅ苯濞囬梻鍌氬€风欢锟犲礈濞嗘垹鐭撻柣銏犳啞閸嬪倿鏌￠崶鈺佹瀺缂佽妫欓妵鍕冀閵娧呯厐閻庢稒绻傞埞鎴︽倷妫版繂娈濈紓浣哄У閹告悂鎮鹃悜钘夌闁挎洍鍋撻柣鎾寸洴閺屾盯骞囬崜浣稿煂婵炲瓨绮撶粻鏍蓟閿濆鍋勯柛娑橈功閸戔€愁渻閵堝懏绂嬪ù婊庝邯楠炲啫螖閳ь剟锝炲┑瀣垫晢闁稿本鍩冮崣娲煟鎼淬埄鍟忛柛锝庡櫍瀹曟娊鏁愰崨顖涙闂佺粯鎸哥花鍫曞绩娴犲鐓曢柍鈺佸暟閹冲懐鈧娲栭幖顐﹀煘閹达附鏅柛鏇ㄥ亗閺夘參姊虹粙鍖℃敾闁绘濞€閻涱噣骞囬弶鍧楀敹闂佸搫娲ㄩ崑娑㈡倵椤撱垺鍋℃繝濠傛噹椤ｅジ鎮介娑樻诞鐎殿喖鎲￠幏鍛存倻濡儤鐎鹃梻浣虹帛椤ㄥ懘鎮ч崱娆戠當婵鍩栭悡鍐⒑閸噮鍎忕紒妤佸浮閺屾洟宕卞Ο铏圭懆濡炪値鍋呯换鍫ュ极閹版澘宸濇い鎺嗗亾妞ゃ儲鑹鹃埞鎴︽偐閸偅姣勯梺绋款儐閿曘垹鐣烽悩缁樺亹閻犲洦褰冪粣娑橆渻閵堝棙鈷掗柛妯犲懓濮抽柕澶嗘櫆閳锋帒霉閿濆浂鐒炬い銉ョ箻閺屾稓鈧絺鏅濈粣鏃傗偓瑙勬礃濞茬喖寮婚崱妤婂悑闁告侗鍘鹃埀顒夊弮濮婅櫣绮欓幐搴㈡嫳闂佺硶鏅涢崯鏉戭嚕閵婏妇顩烽悗锝庡亞閸樿棄鈹戦埥鍡楃仴婵炲拑缍侀弫宥咁吋閸℃劒绨婚梺鎸庣箓濡盯宕ｉ埀顒勬⒑閸濆嫭婀扮紒瀣崌閸┾偓妞ゆ帒锕︾粔闈浢瑰鍕煉闁糕斁鍋撳銈嗗坊閸嬫挻绻涚亸鏍ゅ亾閹颁礁娈ㄩ柣鐘叉搐濡﹪宕ョ€ｎ喗鐓曟い鎰靛亜娴滄繃銇勬惔鈩冨枠婵﹦绮幏鍛村川婵犲倹娈橀梻浣筋潐閹倻绮婚弽褏鏆﹂柣妤€鐗婇崕鐔搞亜椤撶喎绗х紒瀣箻濡懘顢曢姀鈥愁槱濠电偛寮剁划搴㈢珶閺囥垹绀傞梻鍌氼嚟缁犳艾顪冮妶鍡欏缂佽绉瑰畷闈涒枎閹扳晙绨婚柟鍏肩暘閸ㄥ搫鐣风仦鐐弿濠电姴鍟妵婵囦繆椤愩垹鏆ｉ柛鈹惧墲閹峰懘鎮滃Ο鐐村浮濮婄粯鎷呴崨濠傛殘闁活亜顦辩槐鎺楊敊閻ｅ本鍣板Δ鐘靛仜閿曨亪寮幇顓炵窞濠电姴瀚埀顒傚仜椤啴濡堕崱妤冪憪闁荤姳鐒﹂悡锟犵嵁韫囨拋娲敂閸涱亝瀚奸梻浣告啞缁嬫垿鏁冮敃鍌氱叀濠㈣埖鍔栭悡銉╂煛閸ヮ煁顏堝礉閿曞倹鐓欐い鏇炴缁♀偓婵犵绱曢崗姗€宕洪敓鐘茬＜婵犲﹤鍟粻鍝勨攽閿涘嫬浜奸柛濠冪墪椤斿繑绻濆顒傦紱闂佺懓澧界划顖炴偂韫囨稒鐓曟い鎰╁€曢弸鎴︽煕婵犲啫濮夐柍褜鍓濋～澶娒哄Ο渚富濞寸姴顑呴弰銉╂煃瑜滈崜姘跺Φ閸曨垰绠崇€广儱顦伴鏍ㄧ箾鐎涙鐭嬬紒顔芥崌瀵鎮㈤悡搴濈炊闂佸憡娲﹂崢婊堝Χ閸℃劒绨婚梺鎸庢閸嬫劙鎮鹃悽鍛婄厸閻忕偛澧藉ú鏉戔攽闄囬崺鏍箚閺冨牆鐏抽柡鍌樺劜鐎氼剟姊婚崒娆戭槮闁圭⒈鍋婂鐢割敆閸曨剙鍓銈嗙墬缁嬫劗鎹㈤崱娑欑厵闂傚倸顕ˇ锕傚箚閻斿吋鈷戦柟绋垮閻擄綁鏌涢弴鐕傝€块柛鈹惧亾濡炪倖甯婄粈浣规叏瀹ュ棙鍙忓┑鐘插閸斿鎮楅悽闈涘付闁宠閰ｉ獮瀣攽閸℃瑥甯撻梻鍌氬€烽悞锕傚箖閸洖鍨傞柤娴嬫櫃閻掑﹥銇勮箛鎾跺闁稿﹤鐖奸弻娑㈠箛闂堟稒鐏嶉梺鎶芥敱閸ㄥ灝顫忓ú顏嶆晝闁靛牆鎳嶇划鍫曟⒑閸忓吋銇熼柛銊╀憾瀵煡宕奸弴鐐殿啋濡炪倖姊婚弲顐﹀矗閸℃せ鏀介柣妯肩帛濞懷囨煟濡も偓濡瑧绮嬮幒鎴叆闁告洍鏅欑花璇差渻閵堝棙灏扮紒顔兼湰閹便劑宕掑┃鎯т壕閻熸瑥瀚粈鍫ユ煕濡姴娲ら悡姗€鏌熸潏鍓х暠闂佸崬娲︾换婵嬫濞戞瑧鍘愰梺鍝勬川閸嬫劙寮ㄦ禒瀣叆婵炴垶锚椤忊晛霉濠婂啨鍋㈤柡灞剧⊕缁绘繈宕橀鍕ㄥ悅婵＄偑鍊栭弻銊ф崲閹寸姵宕叉繝闈涙－濞尖晜銇勯幒鎴濅喊缂侀亶浜跺缁樻媴閻戞ê娈屾繝鈷€鍛珪闁告帗甯￠、娑㈡倷閺夋垳绨甸梻浣虹帛閺屻劑宕ョ€ｎ喗鍋傞柕澶涘缁♀偓闂傚倸鐗婄粙鎺椝夐悙鐑樼厱闁挎繂鐗滃鎰庨崶褝韬鐐存崌楠炴帒鈹戦崼婵囧€梻鍌欑閹碱偊鎳熼婊呯煋闁割偅娲栫粻鐔兼煙缂併垹鏋涚紒鈧€ｎ偁浜滈柟鎵虫櫅閳ь剚鎸惧Σ鎰攽鐎ｎ偆鍘介柟鍏肩暘閸娿倕顭囬幇顓犵闁告瑥顦辩粻姗€鏌涢幒鎾虫诞鐎规洘绮忛ˇ鏉戔槈閹惧磭校缂佺粯鐩獮瀣枎韫囨洑鎮ｇ紓鍌欑贰閸嬪嫮绮旇ぐ鎺戣摕闁绘棁銆€閸嬫捇鎮藉▓璺ㄥ姼婵炲濮嶉崨顖滐紲婵犮垼娉涢懟顖涚閸撗呯＜缂備焦顭囩粻鐐烘煙椤旇崵鐭欐俊顐㈠暙闇夐悹浣告贡缁嬪鏌曢崶褍顏€殿噮鍣ｉ崺鈧い鎺戝閸嬪鏌ｅΟ鍨毢闁哄棴绠撻弻鈩冨緞鎼搭喖娈鹃梺鍝勫暙閻楀棗顔忓┑鍥ヤ簻闁哄啫娲よ闂佺粯绻冮悧鐘差潖缂佹ɑ濯寸紒瀣濮ｆ劙姊洪崷顓涙嫛闁稿锕悰顔界節閸愨晛鍔呴梺鎸庣箓濞层劑鎮炴總鍛娾拺缂佸瀵у﹢鎵磼鐎ｎ偅灏电紒顔剧帛閵堬綁宕橀埡鍐ㄥ箥闂佽瀛╃粙鎺椻€﹂崶顒€绠犻柛鎰靛枟閻撶喖鐓崶褝鏀绘繛鍛川缁辨帗娼忛妸銉﹁癁闂佺硶鏂侀崑鎾愁渻閵堝棗鍧婇柛瀣崌閺岋綁鏁愰崱娆戠杽閻庤娲滈崰鏍€佸Δ鍛＜婵﹩鍓涢鍥⒒娴ｇ瓔鍤欏Δ鐘叉憸缁顓兼径濠勶紵闁哄鐗滈悡鍫濃枔娴犲鐓欓梻鍌滎棎閸忓瞼鈧鎸烽悞锔界┍婵犲洤围闁告侗鍠栧▍銈夋⒑缂佹ɑ灏柛鐔告綑椤繐煤椤忓嫬鐎銈嗘礀閹冲酣宕滄导瀛樷拺閻犲洩灏欑粻鏌ユ煙閸涘﹤鈻曠€殿喖顭烽崹鎯х暦閸ャ劍鐣烽梻渚€鈧偛鑻晶瀵糕偓瑙勬磻閸楁娊鐛Ο鍏煎磯闁告繂瀚禍鐗堢節閻㈤潧浠滄俊顐ｇ懇楠炴劙宕妷褌绗夋繛鏉戝悑濞兼瑧绮荤憴鍕闁挎繂楠告晶顕€鏌ｈ箛濠冩珚婵﹤顭峰畷鎺楀Χ閸涱垯妗撴繝娈垮枛閿曪妇鍒掗鐐茬闁告稒娼欐导鐘绘煏婢舵稑顩柍褜鍓﹂崰鏍煘閹达箑鐓￠柛鈩冦仦缁ㄥ鏌ｆ惔銏㈩暡濠殿垵妫勮灋闁绘柨鍚嬮埛鎴炴叏閻熺増鎼愰柣蹇ｅ枟閵囧嫰顢橀悙闈涒叺闂佸綊鏀遍崹鍧楀箖閵忋倕绀傞柤娴嬫櫅鐢箖姊绘担绋款棌闁稿鎳愰幑銏ゅ礃椤旇偐锛涘銈呯箰閻楀﹪鎮￠敐澶屽彄闁搞儯鍔岄崵顒佺箾閸忕厧濮嶉柟顔筋殔椤繈顢橀悙鍙夋嚈闂備礁鎼悮顐﹀磹濡ゅ懎绐楀┑鐘叉搐绾偓闂佺粯鍔栬ぐ鍐不閻楀牏绡€缁剧増锚婢у弶銇勯妸銉︻棦妤犵偞鍨垮畷鍫曨敆閳ь剟鎷戦悢鍏肩叆婵犻潧妫欓ˉ鐐烘煕鎼达絽鏋涢柡灞炬礋瀹曠厧鈹戦崱鈺佸Ψ缂傚倸鍊哥粔鎾偋閸℃稑鐓橀柟杈鹃檮閸婂嘲螞閻楀牏绠撴繛鍫熺箘缁辨挻鎷呴崫鍕戯綁鏌熼崨濠冨€愰柟顕€绠栭幃鍧楊敍濡鐫忛梻浣告贡閸庛倝宕归崸妤€鑸归柛顐ｆ礃閳锋垿鏌涘┑鍡楊仾鐎瑰憡绻堥弻娑氣偓锝庡墮娴犳粓宕℃潏銊ｄ簻闁圭儤鍨甸顏堟煃闁垮鐏存慨濠冩そ椤㈡洟濡堕崨顒傛崟闂備礁鍚嬪鍧楀垂闁秴鐤鹃柛顐ｆ处閺佸秹鏌ｉ幇顒夊殶闁告﹩浜娲箹閻愭彃濡ч梺鍛婂姇瑜扮偟妲愰弮鈧穱濠囧Χ閸ヮ灝銉╂煕鐎ｎ剙浠ч柡渚囧櫍閺佹捇鎮╅棃娑氥偊闂佽鍑界紞鍡樼閺嶎厼缁╁ù鐘差儐閻撴瑩姊洪銊х窗缂併劏濮ゆ穱濠囶敃椤愩垻浠稿┑顔硷工椤嘲鐣烽幒鎴旀瀻闁圭儤鍨电敮顖滅磽閸屾瑧璐伴柛锝庡櫍瀹曞綊宕奸弴鐘茬ウ闂佸綊鍋婇崰妤冣偓姘哺閹攱鎷呮搴М闂佸湱鈷堥崑澶愭倶閹烘鈷戠紒瀣硶缁犳娊鏌涘Ο鐘插閸庣喎鈹戦悩鎻掆偓鐢稿绩娴犲鐓熼柟閭﹀幗缂嶆垿鏌ｈ箛鏇炴灈闁哄本鐩俊鎼佸Ψ瑜忔闂備胶绮笟妤呭闯閿濆棙鍙忛柍褜鍓熼弻宥夊Ψ閵娿儳姣㈢紓浣哄У閼归箖鈥旈崘顔嘉ч柛鈩冪懃椤冣攽椤旇婊堝礉鎼达絽鍨濋悹鍥梿濞差亶鏁傞柛娑卞灠楠炲牓姊虹拠鎻掑毐缂傚秴妫濆畷鎴﹀礋椤掍礁寮块悗骞垮劚椤︿即鎮″▎鎴斿亾鐟欏嫭绀€婵炲眰鍊栫粋鎺楁晜閻ｅ瞼顔曢梺缁樻尭濞撮绮绘繝姘厱闁冲搫顑囩弧鈧悗瑙勬礃鐢帡锝炲┑瀣闁绘劕鎼ぐ娆撴⒒閸屾艾鈧嘲霉閸パ呮殾闁汇垻顭堢粣妤冣偓骞垮劚閹峰銆掓繝姘厵闁绘垶蓱閳锋帡鏌ｉ鐐搭棞闂囧鏌ㄥ┑鍡欏妞ゅ繒濮风槐鎺楀焵椤掍胶绡€闁稿本顨嗛弬鈧梻浣虹帛閿氱€殿喖鐖奸獮鏍箛椤斿墽锛滈梺缁樏壕顓熸櫠閻㈠憡鐓涢悘鐐垫櫕鏍″┑鐐碘拡娴滎亪鐛箛鏇氭勃闁芥ê顦懙鎰版⒒閸屾瑧顦﹂柟纰卞亜铻為悗闈涙憸娑撳秹鏌熼幑鎰靛殭闁藉啰鍠愮换娑㈠箣濞嗗繒浠奸柛鐑嗗灦濮婃椽骞愭惔锝囩暤闂佺懓鍟跨€涒晠骞堥妸锕€绶為柟閭﹀幐閹疯櫣绱撴担鍓插剱妞ゆ垶鐟╁畷鏇㈠箛閻楀牏鍘甸梺鑽ゅ枔婢ф宕板鈧弻锝呪槈閸楃偞鐝濆Δ鐘靛仦鐢帟鐏冮梺閫炲苯澧伴柣姘劤椤撳吋寰勭€ｎ剙骞堥梺璇茬箳閸嬫稒鏅舵禒瀣仢闁煎鍊楃壕濂告煕濡ゅ啫浠滅紒鐙欏叇搴ㄥ炊瑜濋煬顒勬煙椤旂晫鎳囨い銏℃瀹曠喖濡搁妷銈咁棜闂備礁鎼粙渚€鎮橀幇顑炴椽顢旈崟顐㈡暏婵＄偑鍊栭幐楣冨磻閻斿吋鍋柛銉墯閻撴瑩鏌ゅù瀣珗閽樼喎鈹戦埄鍐ㄧ祷闁硅櫕锚閻ｇ兘鎮界粙鍨祮闂佺粯姊荤换婵堣姳婵犳碍鈷戦柛婵嗗閳ь剙缍婇、鏍р枎韫囷絿鍔烽梺缁樻椤旀牠鎮烽柇锔惧弳闂佸憡娲﹂崢楣冩偂婢舵劖鈷戦柛婵嗗濠€鐗堢箾閸欏绠樼紒顔款嚙閳藉濮€閻樻牓鍔庨幉姝岀疀濞戞瑦娅栭梺缁樻煥閹芥粎寮ч埀顒勬⒑閸愯尙娈遍柛瀣崌閺屾盯濡烽鐐搭€嶉梺鍝ュУ瀹€绋款潖濞差亜浼犻柛鏇ㄥ幘娴煎洭姊洪崫銉バｉ柣妤冨█閻涱噣宕橀钘夆偓濠氭煢濡警妲哄Δ鐘叉搐閳规垿鎮欓崣澶樻閻熸粍澹嗛崑鐔肺ｉ幇鏉跨睄闁割偆鍟块幏缁樼箾鏉堝墽鍒伴柟纰卞亝缁傛帒煤椤忓懐鍘遍柟鍏肩暘閸婃洟宕ラ崷顓犵＜妞ゆ梻鈷堥悡鍏碱殽閻愯揪鑰块柟绛圭節婵″爼宕ㄩ妯轰喊闂傚倷娴囬褔宕欓悾宀€绀婇柛鈩冾焽椤╂煡鏌涢锝嗙闁稿鍊块弻鏇熷緞閸℃ɑ鐝曢梺缁樻尰濞叉鎹㈠☉銏犵婵犻潧妫滈崺鐐烘⒑鐠囪尙绠哄鏉戞啞缁岃鲸绻濋崶鈺佸絼濡炪倖鎸鹃崑娑氱矈椤斿皷鏀芥い鏃傘€嬪銉︺亜椤撶偛妲婚柣锝囧厴楠炴帡骞嬮鐔峰厞婵＄偑鍊栭崹鐓幬涢崟顒傤洸闁告挆鈧崑鎾绘偡閺夋浠鹃梺闈╃悼椤ユ劙濡甸幇鏉跨闁瑰濮撮埀顒傚仜椤啴濡堕崱妤冪懆濡炪倧缂氶崡鍐差嚕閺屻儺鏁傞柛顐ゅ枎娴狀厼鈹戦悩璇у伐闁哥喐澹嗙划鑽ょ磼濮楀棙顔旈梺缁樺姈濞兼瑩鎮橀弶鎴旀斀妞ゆ梻鎳撴禍楣冩⒒娓氣偓濞佳囨偋閸℃稑绠犻柟浼村亰閺佸﹤鈹戦悩鎻掆偓鐢稿绩娴犲绠抽柟鎯版绾惧綊鏌熼悧鍫熺凡缁炬儳顭烽弻鐔煎箚瑜嶉。铏繆椤愵偄鐏﹂柡灞剧洴楠炴ê螖閳ь剟骞婃惔锝囩當闁挎稑瀚壕钘壝归敐鍫燁仩閻㈩垱鐩弻锝夊煛婵犲倻浠搁梺缁樹緱閸犳岸鍩€椤掑﹦绉靛ù婊勭墵瀵憡鎯旈妸褍褰勯梺鎼炲劘閸斿秶澹曟繝姘厵妞ゆ洖妫涢幃鑲╃磼鏉堛劍灏伴柟宄版嚇瀹曨偊宕熼鍕垫闂佽姘﹂～澶娒哄鈧弫鍐閵堝棙娅滈梺缁樺姈濞兼瑧娆㈤悙鐑樼厵闂侇叏绠戞晶浼存煟閵堝懎顏慨濠冩そ濡啫鈽夋潏鈺佸Ъ闂備胶顭堢€垫帡宕抽敐鍜佸殨闁靛濡囬々鐑芥倵閿濆骸浜為柛姗€浜跺娲棘閵夛附鐝旈梺鍝ュ櫏閸嬪﹤鐣烽悽鍓叉晢濞达綀娅ｉ鏇㈡⒑閼归偊娼愭繝銏★耿閹繝骞囬鍓э紲缂傚倷鐒﹂…鍥Υ閹烘鐓冪憸婊堝礈濮樿京鐭欓柟鐑樸仜閳ь剨绠撳畷鍫曨敆娴ｇ澹掑┑鐘垫暩婵鈧凹鍠氭竟鏇㈡偩鐏炵浜炬鐐茬仢閸旀岸鏌熼柨瀣伌闁绘搩鍓熼、妤呭磼濡も偓娴滅偓绻涢崼婵堜虎闁哄闄勯妵鍕即閸℃鎼愰柣鎾偓鎰佺唵閻犲搫銈介敓鐘冲亜闁稿繗鍋愰崣鍡涙煟鎼搭垳绉甸柛蹇旓耿瀹曟垿骞樼€靛摜鐦堝┑顔斤供閸欏骸螞閸涱収娓婚柕鍫濇婵倿鏌涢妸銊︻仩缂侇喖锕、鏇㈠Χ閸モ晪绱查梻浣告惈鐞氼偊宕曢幎鑺ュ仼婵炲樊浜濋悡鏇㈡煃閻熸壆浠㈤柣蹇撳级椤ㄣ儵鎮欐潏鎹愨偓璺ㄢ偓娈垮櫘閸撶喐淇婇悜鑺ユ櫆闁兼亽鍎茬欢顐︽⒒閸屾艾鈧兘鎳楅崜浣稿灊妞ゆ牜鍋涚粈澶嬩繆椤栫偞锛熼柣鎺戯攻缁绘盯宕卞Ο鍝勵潔濠电偛鎳愭繛鈧柡灞炬礉缁犳稓鈧綆浜栭崑鎾诲冀椤撶喎浜楀┑鐐村灟閸ㄦ椽鎮￠弴鐔虹瘈濠电偞鍎虫禍鍓х磽娴ｆ彃浜炬繛杈剧到濠€閬嶃€呴幓鎹楀綊鎮℃惔锝嗘喖闂佺粯鎸诲ú鐔煎蓟瀹ュ洦鍠嗛柛鏇ㄥ亜婵垺绻涚€涙鐭岄柛瀣尰缁岃鲸绻濋崶銊モ偓閿嬨亜韫囨挸顏ら柛瀣崌瀵€燁檨闁哥喎鎳庨埞鎴︽偐鐎圭姴顥濈紒鐐劤椤兘寮婚悢鐓庣鐟滃繒鏁☉銏＄厽闁规儳鐡ㄧ粈鍐ㄇ庨崶褝韬い銏＄☉閳规垿宕卞Δ浣稿姃闂傚倷鐒﹀鍧楀储閻ｅ本鏆滈柣鎰惈閻掑灚銇勯幒鎴濇灓婵炲吋鍔栫换娑㈠矗婢舵稖鈧法鈧娲栫紞濠傜暦缁嬭鏃堝礃閵娧佸亰濠电姷顣藉Σ鍛村垂閻㈢纾婚柟閭﹀枛椤ユ岸鏌涜箛娑欙紵缂佽妫欓妵鍕冀閵娧呯厐闁汇埄鍨甸崺鏍€冮妷鈺傚€烽柤纰卞墮閳潧鈹戦纭峰姛缂侇噮鍨堕獮蹇涘川椤栨粓鈹忛柣搴秵閸嬪棛绮旈柨瀣瘈闁汇垽娼цⅷ闂佹悶鍔嶅浠嬪极閸愵喖顫呴柣妯虹仛濞堥箖姊洪棃娑辨Т闁哄懏鐩幃鐐哄垂椤愮姳绨婚梺鍦劋閸ㄧ敻鍩€椤掑啫鍚瑰瑙勬礃缁轰粙宕ㄦ繝鍕妇濠电姷鏁搁崑娑㈡倶濠靛绀夋慨妯垮煐閻撴瑦銇勯弮鍥棄闁诲繑鎸抽弻锛勪沪閻愵剛顦伴悗瑙勬礃閸庡ジ藝閸欏浜滈煫鍥风到楠炴鏌曢崶褍顏┑顔瑰亾闂佹枼鏅涢崯浼此囬悧鍫㈢瘈婵炲牆鐏濋弸鎾绘煕鐎ｎ偅宕屾慨濠呮閳ь剙婀辨慨鐢垫兜妤ｅ啯鐓熼煫鍥ㄦ⒐缁€瀣偓瑙勬礈閸犳牠銆佸Δ鍛劦妞ゆ巻鍋撴い鏇秮楠炴劖鎯旈敐鍥╂闂備焦鐪归崹钘夘焽瑜嶉悺顓㈡⒒娴ｅ憡鎲搁柛锝冨劦瀹曞綊鎳滈崗鍝ョ畾闂傚倸鐗婄粙鍫ュ绩娴犲鐓曟い鎰剁秬婢规ê霉濠婂牏鐣洪柟顔煎槻閳诲氦绠涢幙鍐х棯缂備礁澧介崑鎾诲箖閸岀偛钃熸繛鎴欏灩濡﹢鎮归幁鎺戝闁靛牆顦伴悡娆愵殽閻愯尙浠㈤柣蹇婃櫊閺屽秶鎲撮崟顐や患闂侀€炲苯澧剧紓宥呮缁傚秹鎮欓弽绋挎喘婵℃悂濡烽钘夌槣闂備線娼ч悧鍡涘箠閹邦喚涓嶅ù鐓庣摠閸婂灚鎱ㄥΟ鐓庡付濠⒀勫缁辨帡顢欏▎鎯ф闁绘挶鍊栭妵鍕疀閹炬潙娅濋梺鐟板槻椤嘲顫忛搹鍦煓闁圭瀛╅幏閬嶆⒑閼姐倕鏆€闁搞儰绀佸ú顓㈠极閸愵喖纾兼繛鎴炶壘楠炲秹姊洪懡銈呅㈡繛澹洤宸濇い鏍ㄧ矋椤矂姊虹拠鎻掝劉妞ゆ梹鐗犲畷浼村冀椤撴稈鍋撻敃鍌涚叆閻庯絺鏅濈粻姘舵⒑瑜版帗锛熺紒鈧笟鈧幃鈥斥槈濡攱鏂€闂佺粯蓱瑜板啴寮抽悙瀵哥闁告侗鍘炬晶锔芥叏婵犲嫮甯涢柟宄版噽閹叉挳宕熼鈥虫憢闂傚倷鑳堕…鍫⑩偓鍨浮瀹曟娊鏁愰崪浣告闂佸湱绮敮鈺呮偂閵夆晜鐓曟い鎰靛亜婢ф壆绱?",
        }
        base = mapping.get(scenario, "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡▎鎴犫敍闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼宕滆绾惧ジ鏌ｅΟ鎸庣彧閻忓浚鍙冮弻锝夋晲婢跺鏆犵紓浣芥閺咁偆鍒掑▎蹇婃瀻闁绘劦鍓涚粔閬嶆⒒閸屾瑨鍏岄柛瀣ㄥ姂瀹曟洟鏌嗗鍛焾闁荤姵浜介崝蹇旀叏閹惰姤鐓忓璺烘濞呭棝鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡樺窛闁硅棄鍊圭换娑㈠礂閻撳骸顫屽銈庡幖濞硷繝骞冮悜鑺ュ亱闁割偒鍋呴敍渚€姊绘担鍛婃儓闁硅櫕鎸搁埢鏂库槈濠婂懍绨烽梻鍌欑閹测剝绗熷Δ鍛偍濡わ絽鍟弲顒佺箾閹存瑥鐏柣鎾跺枛楠炴牠骞栭鐐典化缂備礁顦靛褔婀佸┑鐘诧工鐎氼喗鏅堕悽纰樺亾濞堝灝鏋旈柛鏂跨Ф缁骞掗弬鍝勪壕闁挎繂楠告禍鐐烘煕濡寧顥夐柍瑙勫灴閸┿儵宕卞Δ鍐ф樊婵＄偑鍊栧▔锕傚川椤撶姷鐡樺┑鐘垫暩婵數鍠婂澶嬪亗婵炴垯鍨洪悡鏇㈡煃閳轰礁褰侀柟瀵稿Х閻棝鏌涢鐘茬伄缁炬儳銈稿鍫曞醇濞戞ê顬堢紓浣广亞閸ャ劎鍘垫俊鐐差儏妤犳悂鍩㈤崼鈶╁亾鐟欏嫭绌跨紒鍙夊劤椤曘儵宕熼瀣枑鐎电厧鈻庨幋鐙€妲梻鍌氬€搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偞鐗犻、鏇㈡晜閽樺澹庡┑鐘绘涧閸婂鈥﹂崼銏㈢幓婵°倕鎳忛悡娑氣偓瑙勬惄閸犳牠寮甸鍌滅閹兼番鍔嶉埛鎴︽煟閹惧啿鐦ㄦ繛鑲╁枛閺屾稒绻濋崘銊ヮ潚閻庤娲橀崹鍧楃嵁濡偐纾兼俊顖濇〃缂傛挻绻濋悽闈涗粶闁绘鍔曢埢鏃堝即閵忕姷顦梺鍛婄☉閿曪妇寮ч埀顒傜磼閸撗冾暭閼裤倝鏌涚€ｎ偅宕岄柟宕囧█椤㈡宕掑鍐ㄧ畾婵犵數濮甸鏍窗閺嶎厽鏅濋柕澶堝労濞撹霉閻樺樊鍎戠€规挷绶氶獮鏍庨鈧俊浠嬫煕閵堝懐效闁哄本娲樺鍕槈閵忊槅鈧秴鈹戦悙鑼闁诡喖鍊搁～蹇涘传閸曟嚪鍥х倞鐟滃繘宕濋幘顔解拺闁硅偐鍋涙慨鍌毭瑰鍐煟濠碘剝鎸冲畷姗€鍩￠崘顏嗘闂備礁鎲￠崜顒勫川椤栨粍姣庨梻鍌氬€烽悞锕傛儑瑜版帒鍨傚┑鐘冲焹閳ь剨绠撳畷濂稿閵忋垻鍔堕梺璇插嚱缂嶅棝宕戞担鍦洸婵犲﹤鐗婇悡娑氣偓骞垮劚閸燁偅鎱ㄩ埀顒佺節閵忥綆娼愭い顓炴喘閸┾偓妞ゆ帒鍠氬鎰版煙閸濄儺鐒鹃摶鐐翠繆閵堝懏鍣归柣鎾达耿閺岀喓鈧數顭堟禒婊呯磼閻橀潧鈻堟慨濠呮缁瑩宕犻埄鍐╂毎闂備礁鎲″褰掓偡閵夆晜鍋╅柣鎴ｆ缁狅綁鏌ㄩ弴妤€浜剧紓浣哄Т椤兘骞冨ú顏勭鐎广儱鐗嗛崢锟犳⒑绾懏鐝柟鐟版喘閸ㄩ箖鏁冮崒姣尖晠鏌嶆潪鎷屽厡妞わ附婢橀—鍐Χ閸℃顫囬梺鎼炲妿椤㈠﹪銆傞懞銉х瘈缁炬澘顦辩壕鍧楁煕鐎ｎ偄鐏寸€规洘鍔欐俊鍫曞幢濞嗘ɑ閿ゆ繝鐢靛Т閿曘倝鎮ч崱娑欏仾妞ゆ洍鍋撻柟顔筋殔閳藉鈻嶉鈥充汗闁瑰箍鍨藉畷鍗炩槈濞嗘垵骞嶆俊鐐€栭悧妤冪矙閹次诲鈧綆鍠楅悡鐔兼煏閸繂鈧憡绂嶆ィ鍐┾拻闁稿本鐟чˇ锕傛煙绾板崬浜滈悡銈夋煏婵炵偓娅呯紒鎰殜楠炴牕菐椤掆偓閻忣喗銇勯埡鍜佹闁瑰弶鎮傞幃褔宕煎┑鍫㈡嚃闂備焦濞婇弨杈╂暜閹烘绠掗梻浣瑰缁诲倿骞婅箛娑樼柈闁绘劗鍎ら悡娆愩亜閺嶃劍鐨戝褝绠撻弻鈥崇暆閳ь剟宕版惔銊﹀仼闁跨喓濮甸悞浠嬫煥閺囨浜鹃梺鍛婃尭閻栧ジ骞冨Δ鍐╁枂闁告洦鍓涢ˇ銊╂⒑閹肩偛濡奸柣蹇旂箞閹箖鎮滈挊澶岊攨闂佺粯鍨靛Λ娆戔偓闈涜嫰椤啴濡舵惔鈥茶埅闂佸摜濮靛銊у垝閺冨牜鏁婄紒娑橆儐椤旀棃姊虹紒妯哄鐎殿喖鐖煎畷鏉课熺亸鏍т壕婵炲牆鐏濋弸娑橆熆瑜嶉柊锝夌嵁閹达箑绀嬫い鏍ㄣ仜閸嬫捇鏁冮崒姘鳖吅濠电娀娼уú锕傛偟閵娾晜鈷掗柛灞捐壘閳ь剙鍢查湁闁搞儜鍛闂佸壊鐓堥崑鍛村矗韫囨稒鐓涘璺侯儏濞堫喗绻涘顔荤盎闁绘挻鐩弻娑㈠箛鐏炶姤鍣瑰褏鍋撶换婵嬫偨闂堟稐绮跺┑鈽嗗亝閻熲晠鐛幇鏉跨濞达絽鎽滈敍婊堟⒑闂堟单鍫ュ疾濠婂牊鍋傛繛鍡樻尰閳锋帡鏌涚仦鎯у毈闁搞倗鍠栭弻娑㈠棘鐠恒剱褔鏌＄仦鐣屝ч柡灞诲妿閳ь剨缍嗘禍鐐寸閼测晝纾藉ù锝勭矙閸濇椽鎮介婊冧槐闁糕斁鍋撳銈嗗笒閿曪妇绮旈悽鍛婄厱閻庯綆浜滈顓熴亜閵徛ゅ妞ゎ厹鍔戝畷鐔碱敇閻樺灚顫岄梻鍌欑窔閳ь剛鍋涢懟顖涙櫠閹绢喗鐓欐い鏂诲妼濞层倝鏌嬮崶顒佺厽闁哄倸鐏濆Σ璇裁归悡搴☆劉缂佺粯绻勯崰濠偽熷ú缁樼秹闂備焦鎮堕崝宥嗙箾婵犲洤鐏抽柨鏇炲€搁柋鍥煟閺傚灝顣崇紒鐘冲哺濮婄儤瀵煎▎鎴濆煂闂佹椿鍓濋崑鎰珶閺囩喓闄勯柛娑橈功閸橀亶鏌ｈ箛鏇炰户闁稿鎹囬幆鍐箣閿曗偓閺嬩線鏌涢鐘插姕闁抽攱鍨垮鍫曟倷閺夋埈妫嗛梺鍛婃煥缁夊綊寮诲☉銏犵睄闁逞屽墴閹兘濡烽埡鍌氫患闂佺粯鍨煎Λ鍕兜閳ь剟姊虹紒妯哄闁哄懏绮撻幃妤佺節濮橆厸鎷洪柣鐔哥懃鐎氼參宕曞Δ鍛厱婵☆垱浜介崑銏⑩偓娈垮枟閻擄繝銆佸鈧慨鈧柍閿亾闁瑰嘲顭峰铏圭矙閹稿孩鎷遍梺鑽ゅ枂閸旀垵鐣峰Δ鈧悾婵嬪礋椤掑倸骞嶉梻浣瑰劤濞存岸宕戦崨顓犳殾閻忕偘鍕樻禍婊堟煏韫囧ň鍋撻崘鍙夋嚈婵＄偑鍊戦崹娲晝閵忊剝鍙忛柍褜鍓熼弻锝呂熺喊杈ㄦ缂備線浜舵禍璺侯潖缂佹ɑ濯撮柧蹇曟嚀缁楋繝姊洪崨濠冣拹婵炶尙鍠庨悾鐑藉Ψ閳轰胶鍔﹀銈嗗笒鐎氼參鎮￠悢鍏肩厵闁绘垶锚閻撯偓闂傚鍓﹂崜鐔煎蓟閿涘嫪娌柣鎰靛墰椤︺劎绱撴担铏瑰笡闁烩晩鍨堕獮鍐ㄢ枎閹垮啯鏅㈡繛杈剧到閹碱偆寰婃ィ鍐┾拻闁稿本鐟ㄩ崗宀€绱掗鍛仸妤犵偞鍔楅幏鐘垫啑娴ｈ銇濋柟顔哄灲閹剝鎯旈敐鍥ㄦ瘒濠电姴鐥夐弶搴撳亾閺囥垹绠犻煫鍥ㄧ☉閻ら箖鏌＄仦璇插姎缂佺姴婀辩槐鎺楊敊閻撳骸杈呴梺绋款儐閹瑰洭骞婇悩娲绘晢闁逞屽墴瀹曠敻顢楅崟顑芥嫽婵炶揪绲块悺鏃堝吹濞嗘垹纾肩紓浣姑慨鍥婢跺鍙忔俊顖涘绾箖鏌ｉ鐕佹疁闁哄本鐩獮鍥濞戞瑧浜梻浣芥閸熶即宕伴幘璇茬劦妞ゆ巻鍋撶紒鐘茬Ч瀹曟洟鏌嗗畵銉ユ喘楠炲秹顢欓悷棰佸闂佹眹鍨藉褍鐡俊鐐€ら崢鐓庮焽閿熺姴绠犳繝濠傜墛閸庢梹銇勮箛鎾村櫣闁诲繑鎸抽弻娑㈠煘閸喚浼堥悗瑙勬礈閸樠団€﹂崸妤婃晜闁告侗鍣Λ鍐⒑鐠団€虫灀闁哄懐濮磋灋闁告劑鍔夊Σ鍫熶繆閵堝嫮顦﹀┑顖欏嵆濮婂宕掑▎鎰偘閻庤娲滈弫璇茬暦椤栫偛閿ゆ俊銈傚亾闁汇倗鍋撶换娑㈠箣濞嗗繒浠鹃梺绋款儌閺呮繈鍩€椤掑倹鍤€閻庢凹鍘鹃埀顒佽壘閻楁捇骞冮姀顫剨濞达絽婀遍埀顒€顭峰铏圭磼濡搫袝闂佺娴烽崗姗€銆佸Δ鍛妞ゆ垼濮ょ€氳棄鈹戦悙鑸靛涧缂佽弓绮欓獮澶愭晸閻樿尙鏌堥梺缁樺姉閸庛倝鎮￠弴銏＄厪濠电偛鐏濋崝銈囩磼婢跺苯鍔嬫い銊ｅ劦閹瑧鎷犺閸氼偄螖閻橀潧浠︽い顓炴喘楠炲繘鎮╃紒妯烘濡炪倖宸婚崑鎾搭殽閻愬樊鍎旀慨濠勭帛閹峰懏绗熼娑欐殲闂備浇顫夊鎸庣椤忓嫷娼栧ù鐘差儏缁€瀣亜閺嶃劍鐨戦柨娑欑懇濮婅櫣绱掑Ο铏逛紘婵犳鍠撻崐婵嗙暦閹版澘鍨傛い鎰╁€楅鏇㈡⒑閻熼偊鍤熼柛搴㈠姈缁傛帡鎮欓鍙ョ盎闂婎偄娲﹂幐濠毸夊鍫熺厸閻庯綆浜炴晶銏ゆ煃瑜滈崜娆戠不瀹ュ纾块柛妤冨€ｅ☉妯锋婵﹩鍓欒ⅲ闂備線鈧偛鑻晶瀛樻叏婵犲啯銇濈€规洘锕㈤幊鐘活敆娓氬洤鏁婚梻鍌欒兌椤牓顢栭崱娑樼闁搞儺鍓欓拑鐔哥箾閹存瑥鐏╃紒鐘崇洴閺岋綁濮€閵堝棙閿柣銏╁灛閸庨潧顫忓ú顏勫窛濠电姴鍟伴崣鍡楊渻閵堝繒鐣冲ù婊庡墮鍗遍柟鐗堟緲缁犲鎮楀☉娅亪顢撻幘鍓佺＝濞达絽澹婇崕蹇曠磼閵娾晙鎲剧€规洘鍨块獮妯兼嫚闊厾鐐婇梻渚€娼ч敍蹇涘川椤栨艾鑴梻鍌氬€风粈浣革耿闁秵鎯為幖娣妼闂傤垱銇勯弽銊х煂缂佲偓婵犲洦鐓涚€广儱楠搁獮妤呮煟閹惧磭绠婚柣鎿冨亰瀹曞爼濡搁敂缁㈡К闂佸摜鍠愰幃鍌氼潖濞差亜浼犻柛鏇ㄥ墻濡偛鈹戦埥鍡椾簼缂佽鐗嗛锝囨嫚瀹割喖鎮戦梺鍓插亽閸嬪懘顢撻崶顒佲拻濞达絽鎲￠崯鐐烘煙閹间胶鐣虹€规洑鍗冲浠嬵敇閻樿尙銈﹂梻浣告啞閸旓箓宕伴弽顓熺叆闁靛牆妫旂换鍡涙煏閸繂鈧憡绂嶆ィ鍐┾拺缂備焦锚缁楁帡鏌ｈ箛鏂垮摵濠碉紕鏁诲畷鐔碱敍濮橀硸鍞洪梻浣烘嚀閻°劎鎹㈠鍡欘浄濡わ絽鍟埛鎴︽煙閹澘袚闁轰線浜堕弻娑㈠Ω閵夛箑浠村Δ鐘靛仜閸燁偊鎮鹃敓鐘茬闁惧浚鍋嗛埀顒€顭峰Λ鍛搭敃閵忊€愁槱闂佺懓鐨烽弲婊呯矉閹烘挾闄勯柛娑樑堥幏娲⒑閸涘﹦鈽夐柨鏇樺劦閹繝鎮㈤崗鑲╁幈婵犵數濮撮崯鎵不閻愮鍋撳▓鍨灈妞ゎ厾鍏樺顐﹀箛椤撶偟绐炴繝鐢靛亹閹峰啴宕堕妸褍骞堟繝鐢靛仦閸ㄩ潧鐣烽鍕嚑婵炴垯鍨洪悡娑㈡倵閿濆骸澧€涙繂顪冮妶搴濈盎闁哥喎鐡ㄦ穱濠囧醇閺囩偟顦ㄩ梺闈浤涢崒婊勶紡闂傚倸鍊峰ù鍥х暦閻㈢闂柨鏂垮⒔娑撳秹鏌熸潏鎯х槣闁轰礁顑夐弻鏇熷緞閸℃ɑ鐝旂紓浣插亾閻庯綆鍋佹禍婊堟煙閹屽殶闁宠棄顦湁婵犲﹤鐗忛悾娲煛鐏炶濡奸柍瑙勫灴瀹曞崬顪冪拠韫闂佽崵鍠愭竟瀣几瀹ュ鐓曢柕澶堝灪濞呭洨鐥幆褋鍋㈤柡宀嬬到铻ｉ柛婵嗗濮ｆ劙姊洪崨濠勭畼闁稿簺鍊濋獮鍫ュΩ閿斿墽鐦堥梺鍛婂姀閺傚倹绂掗姀鐘斀闁宠棄妫楁禍婊堟煕閻曚礁浜伴柛鈹垮劜瀵板嫭绻濇惔銏犲厞婵＄偑鍊栫敮鎺椝囬弶鍟冩帡宕惰閺€浠嬫煟濡櫣浠涢柡鍡忔櫊閺屾稓鈧綆鍋嗗ú鎾煙椤栨碍澶勯悗闈涖偢瀵爼骞嬮悪鍛覆闂傚倷绀侀幖顐⒚洪姀銈呭瀭婵炲樊浜滅壕濠氭煏閸繃顥撳ù婊勭矒閺岀喖骞嗚閼稿綊鏌ｈ箛锝勯偗闁哄苯绉归弻銊р偓锝庝簽閻熴劑姊婚崶褜妯€闁哄被鍔岄埞鎴﹀幢濞嗗繆鎷℃繝鐢靛仜閸氬宕濆▎鎾宠摕闁哄洢鍨归悙濠囨煃鏉炴壆鍔嶉柣蹇撶墦濮婃椽宕崟顒佹嫳缂備礁顑嗛崹濂告倶閹烘鈷戦柛锔诲弾閻掗箖鎮楅崹顐㈢瑲缂佸倹甯￠崺鈩冩媴閸欏鏉搁梻浣虹帛閸旀洖顕ｉ崼鏇€澶愬箻缂佹鍘遍梺闈涱焾閸庡磭绮斿ú顏呯叆婵犻潧鐗嗘禒婊堟煃鐟欏嫬鐏寸€规洖銈搁幃銏☆槹鎼搭垳纭€闂傚倸鍊烽悞锕傚磿瀹曞洦宕查柟閭﹀墾閼板潡姊洪鈧粔鏉懶ч弻銉︾厸濠㈣泛锕﹀銊╂煛閳ь剚绂掔€ｎ偆鍘介梺褰掑亰閸ㄤ即鎮￠幇顔藉枑闁硅泛锕ら幊鎰婵傚憡鐓欑紓浣姑粭姘舵煕鐎ｃ劌鍔滄い銊ｅ劦閹瑧鎷犺閸氼偄螖閻橀潧浠﹂柨鏇樺灲楠炲﹤顭ㄩ崘锝嗙亖闂佸壊鐓堥崰鏇犵磽閹剧粯鈷掗柛灞剧懆閸忓瞼绱掗鍛仸鐎规洘绻傝灃闁告侗鍘鹃敍鐔兼⒑闂堟稓澧曟い锔垮嵆瀹曟垿宕掑☉姘鳖啎闂佺硶鍓濊摫閻忓繋鍗抽弻宥夋煥鐎ｎ亞浠搁梺闈涙搐鐎氫即鐛鈧畷锟犳倷瀹割喚鈧兘姊绘担椋庝覆缂佽尪妫勯悾鐑筋敆閸曘劉鍋撻敃鍌涘殑妞ゆ牭绲鹃瀷婵犵數濮幏鍐礋閸偆鏉瑰┑鐘殿暜缁辨洟寮拠鑼殾闁绘梻鈷堥弫宥嗙箾閹寸偟鎳勯柣婵囨礋濮婃椽鎳￠妶鍛呫垺绻涚仦鍌氣偓鏇㈩敋閿濆閱囬柡鍥╁枎娴犙冣攽閻樼粯娑ф俊顐㈢焸瀵劑鎳為妷锝勭盎闂佸搫鍟崐鍫曞焵椤掆偓椤戝顕ｉ妸褏纾兼俊顖氭贡缁犳岸姊虹紒妯哄闁糕晜鐗犺棢濠㈣埖鍔栭幊姘舵煟閹邦喖鍔嬮柣鎾存礋閺岀喖骞嶉搹顐ｇ彅婵犵绻濋弨杈ㄧ┍婵犲洤绠甸柟鐑樻煥閳敻鎮楀▓鍨灈闁绘牜鍘ч悾鐑芥偂鎼搭喗鍍靛銈嗘尵閸犳捁銇愰崨顓涙斀闁绘ɑ鍓氶崯蹇涙煕閻樺磭澧靛┑鈥冲缁瑥鈻庨悙顒傜▉缂傚倸鍊烽悞锕佹懌婵犳鍨卞娆撳Υ閹烘埈娼╅柣鎾虫捣娴狀垶姊洪崨濠冣拹闁诡喖鍊搁～蹇撁洪鍕唶闁瑰吋鐣崹濠氭晬濮椻偓濮婅櫣绮欓幐搴㈠闯闂佽桨鑳剁划顖涚┍婵犲洤绠绘い鏃囧亹椤︺劌顪冮妶鍡樼叆闁靛牊鎮傚畷顒勫醇閺囩啿鎷洪梻鍌氱墛缁嬫挾绮婚崘娴嬫斀妞ゆ棁濮ょ亸锕傛煙?")
        if repeated_gap:
            if localized_repeated_gap:
                base += ""
            else:
                base += "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘辨繝鐢靛Т閸婂綊宕戦妷鈺傜厸閻忕偠顕ф慨鍌溾偓娈垮櫘閸ｏ絽鐣锋總鍛婂亜闁告稑顭崬鍫曟⒒閸屾瑨鍏屾い顓炵墦椤㈡牠宕卞☉妯碱唶闂佸憡鎸嗛崘銊т喊婵＄偑鍊栭幐楣冨磻閹邦儵锝夊醇閻斿墎绠氬銈嗙墬缁诲秹宕靛▎鎰闁告稑娲ゅú锕傚煕閹寸偟绠鹃柤濂割杺閸ゆ瑦顨ラ悙鎼疁闁哄矉缍侀幃銏ゅ矗婢跺褰嬮柣搴㈩問閸犳牠鈥﹂悜钘夌畺闁靛繈鍊曞婵嗏攽閻樻彃顏懖鏍ㄧ節瀵伴攱婢橀埀顑懎绶ゅù鐘差儏閻ゎ喗銇勯弽顐㈠壉闁轰椒鑳堕埀顒€绠嶉崕閬嵥囨导鏉戠厱闁硅揪闄勯悡娆撴煠濞村娅呭ù鐘崇矒閺屽秷顧侀柛鎾村哺閹囨偐閼碱剚娈惧┑鐘绘涧椤戝懘宕橀埀顒€顪冮妶鍡樺暗闁稿缍侀弫鍐磼濞戞艾骞堥梻浣告惈濞层垽宕濆畝鍕€堕柣妯肩帛閻撴洟鏌熼懜顒€濡煎ù婊勫劤閳规垿鏁嶉崟顐℃澀闂佺锕ラ悧鐘茬暦濠靛鏅濋柍褜鍓熼垾锕傚锤濡も偓閻掑灚銇勯幒鎴濃偓鑽ゅ閸忕浜滈柡鍐ㄥ€哥敮鑸点亜閿濆懐锛嶇紒杈ㄥ笚濞煎繘濡搁敃鈧棄宥夋⒑閻熸澘妲婚柟铏悾鐑筋敃閿曗偓缁€瀣煙閹碱厼鐏ｇ紒澶樺櫍閺屸€崇暆鐎ｎ剙鍩岄柧缁樼墵閺屾盯骞囬埡浣肝ㄩ梺鍝勵儏閹虫﹢骞冨Δ鈧埢鎾诲垂椤旂晫浜俊鐐€ら崢楣冨礂濮椻偓閻涱噣宕橀纰辨綂闂侀潧鐗嗗Λ妤佺濡ゅ懏鐓欓柤鍦瑜把呯磽瀹ュ懏顥㈢€规洦鍓濋妵鎰板箳閹绢垱瀚藉┑鐐存尰閸╁啴宕戦幘缁樼厓鐟滄粓宕滃杈╃煓闁瑰瓨绻勯弳銈夋煕閳╁喚鐒界紒鐘冲劤闇夐柨婵嗘噹閺嗛亶鏌涢悢鍝勨枅鐎殿喗鎮傚顕€鍩€椤掑嫬桅闁告洦鍨扮粻濠氭偣閾忚纾柕澹懏锛忛梺纭咁潐閸旀牠藟婢舵劖鐓忛柛鈩兠粭鎺撱亜椤愶絿绠炴い銏☆殕閹峰懐鎲撮崟顐熷亾瀹勬壋鏀介柣鎰皺閹界姷绱掗鑲┬ら柛鎺撳笚閹棃鏁愰崱鈺傜稐闂備礁婀遍崕銈夊箰閸濄儲顐介柣鎰ゴ閺€浠嬫煟濡绲绘い蹇ｅ亜铻栭柡鍐ｅ亾濞ｅ洤锕俊鍫曞炊椤喓鍎甸弻娑氣偓锝庡亞濞插鈧娲﹂崹鍫曠嵁鎼淬劍瀵犲鍏夋櫔缁犳捇寮婚悢鍏煎亱闁割偆鍠撻崙锛勭磽娴ｅ搫校濠电偛锕濠氭偄鐞涒€充壕婵炴垶鐟悞浠嬫煟椤撶偟鐒搁柡宀嬬秮楠炲洭顢楁繝鍛儓婵犳鍠栭敃锔惧垝椤栫偛绠柛娑欐綑瀹告繂鈹戦悩鎻掆偓鐟扳枔濡崵绡€闁汇垽娼ф禒鈺傘亜閺囩喓鐭岀紒顔碱煼楠炴ê鐣烽崶銊︻啎婵犵數濮撮敃銈夊窗濮橆剦鐒介柍鍝勬噺閸嬶絽螖閿旇棄顕滄い蹇曞█閺屻劌鈽夊顒佺亪濠殿喖锕ュ浠嬪箖閻戣棄绾ч幖瀛樻尰鐎垫牜绱撻崒娆戣窗闁革綆鍣ｅ畷褰掑醇閺囩偞妲┑鐐村灟閸ㄥ湱绮婚敐澶嬬厽婵☆垰鍚嬮弳鈺呮煥濞戞瑧绠栫紒缁樼⊕濞煎繘宕滆琚ｉ梻浣侯焾椤戝懘宕愰崸妤冨祦閻庯綆鍠楅崑鎰板级閸碍娅呭褔绠栧缁樻媴缁涘缍堝銈嗘⒐閻楃姴鐣烽弶娆炬僵闁告鍎愬Λ婊勭節闂堟稑鈧悂骞夐敓鐘茬；闁挎繂顦伴悡鏇㈡煏婢舵ê鏋欑紒銊ヮ煼閺岋綁濡搁妷锔藉創濡炪値鍙€閸庡篓閸屾埃鏀介柍銉ㄦ珪閸犳﹢鏌涢埞鎯т壕婵＄偑鍊栫敮濠勬閿熺姴鐤煫鍥ㄧ⊕閻撴洟鏌ｅΟ铏癸紞濠⒀呮暬閺屽秹濡烽婊呮殼闂佽鍠楃划鎾诲箰婵犲啫绶炵€光偓閳ь剟寮抽锔解拻濞撴埃鍋撴繛浣冲懏宕查柛顐犲劚绾惧綊鏌″搴″箹缁炬儳顭烽弻娑樼暆閳ь剟宕戝☉姘变笉鐟滅増甯掔痪褔鏌涢锝囩畵闁抽攱姊荤槐鎺撳緞濡儤鐝濋梺鍝勭焿缁蹭粙鍩ユ径濞炬瀻闁归偊鍓涢敍鎾寸節濞堝灝鏋涢柨鏇樺劚椤啯绂掔€ｎ亞鐤囬梺璺ㄥ枔婵潙娲块梻浣告啞缁嬫垿骞忛幋鐘茬筏濞寸姴顑嗙粻鎺撶節閻㈤潧孝閼瑰矂鏌涚€ｎ偅灏电紒杈ㄥ浮椤㈡瑩鎮剧仦鎯ф珣闂備椒绱徊浠嬪床閺屻儱鐓橀柟杈剧畱閻愬﹪鏌曟繛鍨姎濠德ゆ珪娣囧﹪鎮欓鍕ㄥ亾閵堝鍌ㄥù鐘差儏閸ㄥ倿鏌涢锝嗙闁汇倝绠栭弻宥夊传閸曨剙娅ら梺鎶芥敱閸ㄥ潡寮诲☉銏℃櫆閻犲洦褰冪粻褰掓⒑閸涘﹥鐓ユい鎴濐樀瀵鎮㈤搹鍦厯闂佸壊鐓堥崰鎺楀箰閸愵亞纾藉〒姘搐閺嬨倗绱掗鍛仸濠碘€崇埣閺佹劖寰勬繝鍕垫О闂備礁鍟块幖顐﹀疮椤愶妇宓侀柟閭﹀厴閺€浠嬫煟濮楀棗鏋涢柣蹇氶哺缁绘稒寰勭€ｎ剚鍒涘銈冨灪閻楃姴鐣烽妸褉鍋撳☉娅亪鍩€椤掆偓閻栧ジ寮诲澶婁紶闁告洦鍋€閸嬫捁銇愰幒鎴犵厬闂婎偄娲︾粙鎺楁偂閵夛妇绡€闂傚牊绋掗ˉ鐐烘煙閸忕厧濮囬棁澶愭煟濡鍞洪柟鏌ョ畺閺岋紕浠︾化鏇炰壕鐎规洖娲﹀▓鏇㈡煟鎼搭垳绉甸柛鎾寸洴閹線宕奸妷锕€鈧敻鎮峰▎蹇擃仾缁剧偓鎮傞弻娑㈠籍閳ь剟宕归崸妤€违濞达絿纭堕弸搴ㄦ煙閻愵剚缍戦柍褜鍓熼弨閬嶅Φ閸曨垰绠抽柛鈩冦仦婢规洟姊绘担瑙勫仩闁告柨绻戦妵鏃堝川婵犲嫧鏀虫繝鐢靛Т濞诧箓宕愰柨瀣ㄤ簻闊洦鎸搁銈夋煕鐎ｎ偅宕屾鐐差儔閺佸啴鍩€椤掑嫬鍨傞柛宀€鍋為悡鏇熺節闂堟稒顥滄い蹇ｅ亰閺岋繝宕卞Δ渚囨＆闂佸搫鐬奸崰鏍ь潖閼姐倐鍋撻棃娑橆棌婵″樊鍣ｅ娲传閸曢潧鍓紓浣藉煐瀹€绋款嚕婵犳碍鍋勯柛蹇氬亹閸旂兘姊洪幐搴㈢５闁稿鎸婚〃銉╂倷鐎电鈷堢紓浣介哺鐢€崇暦濠婂嫭濯撮梻鈧幇顔藉礋闂傚倷绀侀悿鍥綖婢舵劕鍨傞柛褎顨呯粻鏍煃閸濆嫭鍣圭紒鐘垫暬閺岀喖鎮滃Ο鑲╃暠闂佽鍣徊浠嬪煘閹达附鍋愰柟棰佺閺呴亶姊洪棃鈺冪У闁搞劏娉涢～蹇旂鐎ｎ亞顦板銈嗗笒閸婄敻寮ㄩ搹顐ょ瘈闁汇垽娼у瓭濠电偠顕滅粻鎾崇暦閹扮増鐓ラ悗锝冨妺缁ㄥ妫呴銏″闁瑰憡鎮傞、鏃堝Χ婢跺鍘遍柣搴秵閸嬪懎鐣峰畝鈧埀顒侇問閸犳洜鍒掑▎鎾扁偓渚€寮撮姀鈩冩珳闂佺硶鍓濋敃鈺呭船閼哥數绡€闁汇垽娼у暩闂佽桨绀侀幉锟犲箞閵娾晛绾ч柟鐐藉妽濡炰粙寮崘顔肩＜婵ɑ鍞荤槐顕€姊绘担渚綊闁告洖鐏氶悾鐑芥⒑缂佹ɑ灏柛搴ｆ暬瀵鏁撻悩鑼槰闂侀潧顭粻鎴λ囬埡渚囨富闁靛牆鍟崝姘亜閿旂偓鏆€殿喛顕ч埥澶愬閻樻牑鏅犻弻銊╁籍閸屾粍鎲樺┑鈽嗗亜閸熸潙顫忓ú顏勪紶闁告洦鍘炬导鍥⒑閸濄儱校闁瑰憡鍎冲嵄闁圭増婢樼粻铏繆閵堝倸浜惧銈庡亜閹虫﹢寮婚敐鍛傜喖鎼归惂鍝ョ濠电偛鐡ㄧ划宀勬偉閻撳寒娼栫紓浣股戞刊鎾煣韫囨洘鍤€缂佹绻濆铏规喆閸曨剙鈧劗绱掗悩宕囧ⅹ闁伙綁鏀辩€靛ジ寮堕幋鐘垫澑婵＄偑鍊栭幐鐐叏椤撱垹缁╅柧蹇ｅ亞缁♀偓闂佹眹鍨藉褍鐡繝鐢靛仦濞兼瑩宕愰崹顕呭殨妞ゆ劑鍩勯崥瀣煕閳╁啰鎳呮い鏃€娲熷娲偡闁箑娈堕梺绋垮閸ㄥ墎绮悢灏佹闁靛骏绱曢崢閬嶆⒑闂堟稓澧曢柟宄邦儔瀹曟洟寮埀顒勫箞閵婏妇绡€闁告侗鍣禒鈺冪磽娴ｄ粙鍝洪悽顖涘笩閻忔帡姊洪崗鑲┿偞闁哄應鏅犲畷銉р偓锝庝簴閺€浠嬫煟閹邦垰鐨洪柟鐣屽Х缁辨帡顢欓懖鈹倝鏌涢幒鎾虫诞妤犵偞顭囩划鐢垫兜閸涱亜浜鹃柛顭戝枔閳ь剚甯掗～婵嬫晲閸涱剙顥氬┑鐘愁問閸犳牠鏁冮妸銉㈡瀺闁挎繂娲﹂～鏇㈡煙閻戞ê鐒炬繛绗哄姂閺屾盯鍩勯崘顏呭櫑婵犳鍠氶崕銈嗙┍婵犲洦鍊锋い蹇撳閸嬫捇寮介锝嗘濠德板€曢幊蹇涘磻閸岀偞鐓ラ柣鏂挎惈瀛濈紓浣哄Х婵炩偓闁哄瞼鍠栭獮鎴﹀箛椤掑倸甯块柣搴ゎ潐濞叉牠藝閻㈢钃熼柡鍥╁枔缁犻箖鏌涢…鎴濇灓濞寸姴鍚嬬换娑氣偓娑欘焽閻矂鏌涚€ｎ偅灏甸柟骞垮灩閳藉濮€閻樿鏁规繝鐢靛█濞佳囨偋閸涘瓨鎯為幖娣妽閳锋垿鏌涘┑鍡楊伌闁稿孩鍔欓弻锝夊煛婵犲倻浠搁悗娈垮枛椤兘寮幇顓炵窞濠电姴鍊搁弫銈夋煟閻斿摜鐭婃い鎴濐槸閻ｇ兘骞嬮敃鈧～鍛存煃閸ㄦ稒娅呭ù婊堢畺閹嘲鈻庤箛鎿冧痪缂備讲鍋撻柛鎰ㄦ櫃缁诲棝鏌ｉ幇顓烆棆闁活厽鐟ч埀顒侇問閸ｎ噣宕戞繝鍥╁祦婵☆垵鍋愮壕鍏间繆椤栨繃銆冩慨瑙勵殜濮婄粯鎷呴挊澶夋睏闂佸啿鍢查悧鎾崇暦濠婂牆惟鐟滃酣锝為弴銏＄厱婵炲棗娴氬Σ铏圭磼閳锯偓閸嬫挻绻濋悽闈涗粶闁绘妫濋幃妯衡攽鐎ｎ亜鍤戦梺缁樻煥閸氬鎮￠妷锔藉弿婵☆垰娼￠崫娲煕閻樺啿濮嶉柡灞稿墲瀵板嫮鈧綁娼ч崝灞解攽閳ュ啿绾ч柟顔煎€块獮濠囨晲婢跺﹦鐤€濡炪倖鎸荤划鍫㈣姳婵犳碍鈷戦柛婵嗗婢跺嫭銇勯妸銉﹀櫤缂佸倸绉甸妶锝夊礃閳圭偓瀚奸梻浣告啞缁诲倻鈧凹鍣ｉ幃鐐垫崉閵娧咃紲闂佸搫琚崕鎶芥偩閻戞﹩娈介柣鎰级椤ャ垻鈧鍣崳锝呯暦閻撳簶鏀介柟閭﹀幘缁夐亶姊婚崒娆戭槮闁汇倕娲ら々濂稿Ω閳哄倸鈧潡鏌ㄩ弴妤€浜鹃梺瀹狀嚙缁夋挳鍩ユ径鎰潊闁抽敮鍋撻柟椋庣帛缁绘稒娼忛崜褍鍩岄梺纭咁嚋缁绘繈鐛径宀€鐭欓幖瀛樻尰閺傗偓婵＄偑鍊栧濠氬磻閹捐姹查柍鍝勫暟绾惧吋銇勯弮鍌涙珪闁瑰啿娲﹂〃銉╂倷閺夋垹鐟ㄩ柧缁樼墵閺屽秷顧侀柛鎾寸〒閸掓帗绻濆顓炩偓鐑芥煟閹寸儐鐒介柛姗嗕簼缁绘繈鎮介棃娑楁埛闂佺顑嗛幐鎼佸煝瀹ュ宸濋柡澶嬪灩閸婄偤姊洪崷顓℃闁哥姵顨婇崺娑㈠箣閿旂晫鍘卞┑鐐村灦閿曨偊宕濋悢鍏肩厽妞ゆ挾鍋為ˉ鐘电磼鏉堛劌娴柛鈹惧亾濡炪倖甯婇悞锔藉垔鐎靛摜纾兼い鏍ㄧ⊕缁€鍐煟韫囧海顦︽い顏勫暣婵″爼宕卞Δ鈧〖闂傚倸鍊哥€氼剛鈧矮鍗冲畷鍝勨槈閵忕姷顓洪梺鎸庢⒒閺咁偊宕㈤崡鐐╂斀闁绘劖娼欓悘锕傛煥閺囥劌浜扮€殿喓鍔庨幏鐘差啅椤旀儳鏁搁梺鑽ゅТ閹碱偊骞栭锔绘晜妞ゆ挶鍨洪悡娑㈡倶閻愭彃鈷旈柕鍡樺浮閺屽秷顧侀柛鎾卞妿缁辩偤宕卞☉妯硷紱闂佸憡娲﹂崐瀣亹閹烘繃鏅╅梻浣诡儥閸ㄧ増绂嶆ィ鍐╁仭婵炲棗绻愰顏嗙棯閻愵剚鍊愰柡灞剧⊕閹棃濮€閻橆偅鐏嗛梻浣虹《閺備線宕戦幘鎰佹富闁靛牆妫楃粭鎺楁煥閺囶亜顩紒顔芥閹粙宕ㄦ繝鍕箞闂備胶绮摫闁告挻鑹鹃埢鎾愁煥閸喓鍘靛銈嗘礀濡稓寮ч埀顒勬倵濞堝灝鏋熼柟鍛婂▕楠炲啴濮€閵堝棙鍎柣鐘叉礌閳ь剝娅曞▍妤呮⒒閸屾艾鈧兘鎳楅崼鏇炵疇闁瑰墽绮崑銈夋煏婵炑冨鎼村﹪姊虹粙璺ㄧ伇闁稿鍋ゅ畷鐢碘偓锝庡枟閸嬧剝绻涢崱妤冪妞ゅ繐鐡ㄧ换娑㈠醇濠婂懐鐓撻梺鍝勭焿缂嶄線鐛崶顒夋晣闁绘柨鍢叉竟鎺撶節閻㈤潧浠滈柣妤€锕﹂崚鎺楀箻鐠囪尪鎽曢梺鐐藉劚绾绢參寮抽崱娑欏€甸柨婵嗛婢ф壆鎮敃鍌涒拻濞达綀濮ら妴鍐磼閳ь剚绗熼埀顒€鐣烽幇鏉块敜婵°倐鍋撶紒鐘靛█閺岋綁骞囬浣瑰創闁哥儐鍨伴—鍐Χ閸℃ǚ鎷婚梺鐑╁墲閺屻劏鐏嬮梺鍛婂姂閸斿寮ㄦ禒瀣厽婵☆垵顕ф晶顖炴煕閻旈绠婚柡灞剧洴閹晛鐣烽崶褉鎷伴梻浣芥〃缁€渚€宕€涙ü绻嗛柟闂寸鍞梺闈涢獜缁辨洟鍩€椤掍焦銇濇慨濠冩そ楠炴劖鎯旈敐鍥╂殼婵犵數鍋犻婊呯不閹剧粯鏅查柣鎰惈閸楁娊鏌曡箛銉х？闁告鏁诲铏圭磼濡櫣浠搁梺鎸庣缁绘盯宕奸妷褏鏆梺鍝勭焿缂嶄礁顕ｉ鍕瀭妞ゆ棁妫勯埀顒夊灦濮婃椽骞栭悙娴嬪亾閺囥垹鐤柟缁㈠枛閽冪喓鈧箍鍎遍ˇ顖涘閻樼粯鐓曢柡鍥ュ妼娴滄繃绻涢崼顐㈠籍闁哄矉缍佹慨鈧柍杞拌兌娴狀參鏌ｉ姀鈺佺仭妞ゃ劌鐗撻獮鎴﹀閻橆偅鏂€闁诲函缍嗛崑鍕濞差亝鈷掗柛灞炬皑婢ф盯鏌涢幒鍡椾壕闂備胶绮崝妤呭磿閵堝鍋傞柡鍥ュ灪閻撳繐鈹戦悙鑼虎闁告梹鎸抽弻锝夊箻閸愬弶鍊銈冨妸閸庣敻骞冨▎鎴炲珰鐟滄垿宕ラ鈶芥棃鎮╅棃娑楁勃闂佹寧纰嶉妵鍕敇閻愭潙浠撮悗瑙勬礈閸犳牠銆佸Δ鍛＜婵°倓绶″鏃堟⒒娴ｇ鈷旂紒顕呭灦閹囨偐鐠囪尪鎽曞┑鐐村灦鑿ゆ俊鎻掔墦閺屾稑螖閸愩劋绮剁紓浣哄Т椤嘲顫忓ú顏勫窛濠电偞纰嶉崹鐢糕€旈崘顔藉癄濠㈣埖蓱缂嶅酣姊洪幆褏绠烘い顐㈩樀瀹曚即宕卞☉娆戝幈闂佸搫娲㈤崝灞剧閻愭番浜滈柨鏂挎惈婵″吋銇勯鍕殻濠碘€崇埣瀹曞崬螣閸喕绨撮梻鍌欑閹测剝绗熷Δ鍛瀭妞ゆ牗绮庣粻鏂款熆閼搁潧濮堥柍閿嬪灴閺岀喓绮欓幐搴㈠闯缂備胶濮甸幐濠氬Φ閸曨垱鏅滈柛顭戝枛缁侇噣姊虹拠鈥虫珯缂佺粯绻冩穱濠囨倻閽樺鍘搁梺绋挎湰缁矂鐛幇鐗堚拻濞达綀顫夐崑鐘绘煕鎼淬垺銇濋柟顕嗙節瀹曠厧鈹戦崘鈺冧簴闂備礁鎼崐褰掓晬閺囥垺鍋￠梺顓ㄥ閸欏棝姊洪崨濠傚闁告柨顦甸獮鎰板礃椤忓棛锛濇繛杈剧导缁瑩宕ú顏呯厵缂佸顑欓悡鍏碱殽閻愯尙绠荤€规洏鍔戝鍫曞箣閻欌偓閸炰粙姊绘担鐑樺殌闁圭⒈鍋嗙划鏃堝箻椤斻垹顦～婵嬫嚋绾版ɑ瀚介梻浣侯焾閺堫剟鎮烽妸鈺佺鐎光偓閳ь剟鎯€椤忓牜鏁囬柣鎰版涧閻撶喖鎮楃憴鍕缂侇喖鐭傞崺鐐哄箣閿曗偓闁卞洭鏌曡箛瀣伄闁告﹩鍨跺缁樻媴閸涘﹨纭€闂佺绨洪崐婵嬪Υ閸愵喖骞㈡繛鎴烆焽閿涙盯姊虹粙璺ㄧ伇闁稿鍠栧畷锝夊箻缂佹鍘遍梺闈涱檧缁茶姤淇婇崸妤佺厓妞ゆ牗绋掔粈瀣煛瀹€瀣М妤犵偞顭囬埀顒佺⊕椤洭藝閵娾晜鈷戦梻鍫熺⊕閹兼劙鎮楀顐㈠祮闁绘侗鍣ｅ畷鍫曨敆閳ь剛绮堥崼婢濆綊鏁愰崶銊ユ畬婵炲濮村﹢杈╂閹捐纾兼繛鍡樺笒閸樷剝绻濆▓鍨灓闁轰礁顭烽獮鍐槻閾绘牠鏌涘☉鍗炲福闁挎洖鍊归悡鏇㈡煛閸ャ儱濡奸柣蹇曞█瀹曨剟顢涢悙鏉戜画濠电姴锕ら崯鐗堢墡缂傚倷绀侀崐鍦暜閿熺姴钃熼柛鈩冾殢閸氬鏌涢埄鍐噧妤犵偞鍔欓弻锝嗘償閳ュ啿杈呴梺绋款儐閹瑰洭骞冨Δ鍛櫜閹肩补鈧剚娼鹃柣鐐寸啲闂勫嫭绌辨繝鍥ч柛銉仢閵夆晜鐓曢悗锝庡墮娴犙囨煛娓氬洤娅嶆鐐村笒铻栧┑鐘插暞濞呭秴鈹戦悩缁樻锭闁稿﹤顭烽垾锕傚醇閵夛箑鈧嘲鈹戦悩鍙夊闁绘挸鍟撮弻娑樷攽閸℃浠奸梺鍝勬閻燂箓銆冮妷鈺傚€烽柛娆忣樈濡箑鈹戦纭峰伐妞ゎ厼鍢查悾鐑藉箳閹存梹鐎婚梺瑙勬儗閸樺€熲叺闂傚倸鍊风粈浣革耿闁秴鐓曢柛顐犲劚绾捐鈹戦悩鎻掍簽闁搞倖娲熼弻锝夊閻樺樊妫岄梺杞扮濡繈寮诲☉姘勃闁告挆鍛帓闂備胶绮幐濠氬箲閸パ屾綎闁惧繗顫夐崰鍡涙煕閺囥劌浜炴い锔哄妼椤啴濡堕崱妯垮亖闂佹悶鍎崝宀勫焵椤掆偓濞硷繝寮诲☉鈶┾偓锕傚箣濠靛懐鎸夊┑鐐茬摠缁秶鍒掗幘璇茶摕闁绘柨鍚嬮崐缁樹繆椤栨繃顏犻柛妯诲姍濮婃椽宕ㄦ繝鍐ｆ嫽闂佸摜濮甸幐鎯ｉ幇鏉跨闁规儳纾粣鐐烘⒑瑜版帒浜伴柛妯圭矙閺屻劑顢橀姀鈾€鎷婚梺鎼炲劀鐏炴嫎褏绱撴担铏瑰笡缂佽鍟伴幑銏犫攽鐎ｎ亞锛滃┑鐐村灦钃辨い蹇曞Т閳规垿鎮欏顔兼婵犳鍠栫粔鐟扮暦閵娾晩鏁嶆繝濠冨姉鎼村﹤鈹戦敍鍕杭闁稿﹥鐗曢～蹇旂節濮橆剛鍘遍梺鍓插亖閸庢煡宕戦崒姘ｆ斀闁稿本纰嶉崯鐐烘煟閹惧鎳勯柕鍥у瀵剛鎷犻幓鎺濈€虫繝鐢靛仜閻即宕愬┑瀣摕閻庯綆鍠栭悙濠囨煏婵炑冩噽濡插洤鈹戦悩鍨毄濠殿喗鎸冲畷鎰亹閹烘垿妫锋繛瀵稿Т椤戝棝鎮?"
        return base

    mapping = {
        "idea_implementation": (
            f"compress the idea into the thinnest verifiable slice and define the first acceptance signal{_file_suffix(file_path)}"
        ),
        "remote_workspace": "name the real workspace boundary first, then prove which machine owns the files and where credentials should safely live",
        "debug_loop": "reproduce once, pause at the first meaningful state change, and inspect one value or branch before widening the debug story",
        "function_guidance": "anchor the function contract to one live call site, then name what the function expects and what evidence proves that reading",
        "engineering_challenge": "anchor the challenge in one real code boundary from the current project, then land the first thin implementation slice and verify it immediately",
        "project_idea": "extract one practice task from the current project that genuinely improves engineering judgment, then define what done looks like",
        "project_adaptation": "separate what stays stable from what must change, then validate only the first critical modification",
        "principle": f"locate the mechanism in the current code{_file_suffix(file_path)} and explain the concrete problem it solves",
        "concept_teaching": f"tie the concept to one live code boundary or one failure path{_file_suffix(file_path)}, then explain why that framing is safer",
        "review": f"fix the single issue that most affects correctness or the feedback loop{_file_suffix(file_path)}, then verify immediately",
        "plan": "lock the one goal for the current stage, then compress today's work into a small loop you can finish",
        "task": "finish the thinnest implementation slice first, then verify whether it actually proves the idea",
        "next_task": "confirm the exact skill the next task should train, then complete only the first verifiable slice",
    }
    base = mapping.get(scenario, "reduce the problem to one smallest verifiable move")
    if repeated_gap:
        base += f", while watching for a repeated gap: {repeated_gap}"
    return base


def _scaffold_teaching_note(
    *,
    scenario: str,
    mode: str,
    recent_wins: list[str],
    weak_spots: list[str],
    due_reviews: list[object],
    review_rhythm: str,
    coach_defaults: dict[str, object],
    tone_name: str,
    verbosity_bias: str,
    chinese: bool,
) -> str:
    localized_recent_win = _surface_context_text(recent_wins[0] if recent_wins else "", chinese=chinese)
    localized_weak_spot = _surface_context_text(weak_spots[0] if weak_spots else "", chinese=chinese)
    review_cadence = str(coach_defaults.get("review_cadence") or "").strip()
    working_set_mode = str(coach_defaults.get("working_set_mode") or "").strip()
    if chinese:
        lines: list[str] = []
        if scenario == "principle":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欑粣娑㈡⒑閸濄儱校闁圭澧介崚鎺旂磼濡浜濋梺鍛婂姀閺呮繈宕㈡禒瀣拺闂侇偅绋戝畵鍡樼箾娴ｅ啿瀚▍鐘炽亜閺嶎偄浠﹂柣鎾跺枑缁绘繈妫冨☉娆忣槱缂備讲鍋撻悗锝庡亝閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濮风槐鎺楊敊閻ｅ本鍣ч梺瀹狀嚙闁帮綁鐛崱姘兼Щ婵犮垼顫夐敋闁宠鍨块幃娆撴嚑椤掍焦鍠栫紓鍌欑贰閸犳碍鎱ㄩ悽鐢电焿鐎广儱顦介弫鍌炴煕閺囥垺娑ф繛鍫涘姂閺岋綁鎮╅崣澶婎槱缂備椒鐒﹀娆忓祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔告倐濮婃椽宕ㄦ繝鍐ｆ嫻闂佸湱顭堥崯鍧楋綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愬宀婃澓濠电姷鏁搁崑娑㈡偤閵娧冨灊鐎广儱顦伴崑瀣繆閵堝懏鍣圭紒鐘靛仱閺屾洘绻涢悙顒佺彅闂佺粯鍔曢敃銉╁Φ閸曨垰绠崇€广儱鐗滈崬褰掓⒑閸︻厽鐒挎繛鍜冪悼濡叉劙骞樼拠鑼紲濠电偛妫欓崹鍨繆娴犲鐓㈤柛鎰靛枙閹查箖鏌熼绛嬬劸缂佺姵鐩弫鎰板川椤撶姷娼夐梻鍌欑閹碱偊寮甸鍌滅煓闁圭儤姊瑰畷鍙夌節闂堟侗鍎忕痪鎯с偢閺屾洟宕煎┑鍥ㄦ倷闂佽鍠楅崹鍨潖缂佹ɑ濯撮柧蹇撶畭閳ь剙锕弻锟犲磼濞嗘垹鐛㈤悗瑙勬礃閸ㄥ潡鐛鈧獮鍥ㄦ媴閻熸壆妲ｉ梻鍌欑窔濞佳囨偋閸℃あ娑樜旈崨顓㈡暅婵犵數濮村ú锕傛偂閺囥垺鍊甸柨婵嗛娴滄繈鎮樿箛鏇熸毄缂佽鲸甯楀蹇涘Ω閵夛箒鐧侀梻浣筋嚃閸犳帡寮查悩璇茬疇闁绘ɑ妞块弫鍕亜閹邦剟顎楅柟鍐差樀瀹曟垿骞橀懜闈涙瀭闂佸憡娲﹂崜娑⑺囬妸銉㈡斀闁绘劘娉涢惃娲煕閻樻煡鍙勯柟顕€绠栭幃婊堟嚍閵夛附顏熼梻浣虹帛閿氶柛鐔锋健閸┾偓妞ゆ巻鍋撳褍娴峰Σ鎰板箻鐎涙ê顎撻梺鍏肩ゴ閸撴繈宕归幐搴濈箚闂傚牊绋堥弨浠嬫煕閳ュ磭绠查柡鍌楀亾闂傚倷鑳堕崑銊╁磿鏉堚晛顥氭い鎾卞灩閺勩儵鏌ㄥ┑鍡樼闁稿鎸鹃幉鎾礋椤掑偆妲柣搴ゎ潐濞诧箓宕滈悢鐓庢槬闁靛繆鍓濋崕鐔兼煃椤撴粌鍔ら柛鐘崇墵楠炲﹪鏁撻悩鍙傃囨煕閹扳晛濡洪柤鍓蹭簼缁绘繈鎮介棃娴躲儲銇勯敐搴℃灓婵″弶鍔欏鎾閻樼绱遍梻浣侯攰閹活亞绮婚幋鐘差棜鐟滅増甯楅悡娑氣偓骞垮劚妤犳悂鐛Δ鍛厱閻庯綆浜堕崕鎰庨崶褝韬┑鈥崇埣瀹曘劑顢欓崗纰变哗闂傚倷绀侀幖顐も偓姘ュ姂瀹曟洟鎮界粙鑳憰濠电偞鍨崹鍦不濞戙垺鐓冮弶鐐村椤︼附銇勯妷銉剶婵﹥妞介獮鎰償閿濆洨鏆ゆ俊鐐€х€靛矂宕归崼鏇炶摕閻庯綆鍠栭悙濠冦亜閹哄秷鍏岄柛姗嗕簼缁绘繈濮€閿濆懐鍘紓浣割儐閸ㄥ潡濡撮崨鎼晢闁告洦鍓涢崢鍗炩攽閳藉棗鐏犻柛姘儔瀵娊顢楁担鐟板伎婵犵數濮撮幊蹇涱敂閻樼粯鐓欏瀣閳诲牓鏌涢妸锕€鍔ら柣锝囧厴瀹曞爼鏁愰崨顒€顥氬┑鐘垫暩婵數鍠婂澶嬪亗闁哄洨鍠撶弧鈧繝鐢靛Т閸婃悂寮冲▎鎾寸厸闁糕剝鐟ラ弸鏃傜磼鏉堛劌娴柛鈹惧亾濡炪倖甯婇懗鍓佸姬閳ь剟姊洪幖鐐插姌闁告柨顦甸獮蹇撁洪鍛嫼闂佸憡绋戦敃锔剧不閹剧粯鍊垫慨妯煎帶閺嬶箓鏌嶉鍡樻毈婵﹦绮粭鐔煎焵椤掑嫬鐒垫い鎺戝€告禒婊堟煠濞茶鐏￠柡鍛埣椤㈡盯鎮欑€电骞愰梺璇插嚱缂嶅棙绂嶅Δ鍛；闁靛繆鎳囬崑鎾斥枔閸喗鐏侀梺鍛婃煥缁夊墎鍒掔€ｎ喖绠抽柡鍌氭惈娴滈箖鏌ㄥ┑鍡涱€楀ù婊呭仱閺屾稑螣缂佹ê纾冲┑顔硷攻濡炶棄螞閸愩劉妲堥弶鍫涘壉閵堝鈷戠紒瀣健閸欏嫬霉濠婂棙纭炬い鏇秮閹煎綊顢曢敐鍥┬ら梻浣稿暱閹碱偊宕导瀛樻櫖婵犲﹤鐗婇埛鎴犵磽娴ｈ鐒介柟鍐插閺岋綁鎮㈤弶鎴濆闁绘挶鍊濋弻銊╁即閻愭祴鍋撹ぐ鎺戠；闁稿本绋撶粻楣冩煕閳╁厾顏呮叏閸屾鐟邦煥閸曨厾鐓夐梺鍝勭焿缁绘繂鐣峰鈧俊鎼佸Ψ閵忕姳澹曢梺鍛婄缚閸庢煡寮冲鍫熺厱妞ゆ劧绲剧粈鍐煟閹惧啿鏆熼柟鑼焾椤劑宕煎┑鍫Ф婵犵數鍋涘Λ妤€霉濮樿埖鍊垮ù鐘差儐閻撱儵鏌ｉ弬鎸庢儓鐎涙繄绱撴担鍝勑ｉ柣妤佹礋濠€渚€姊虹粙璺ㄧ闁告艾顑夊畷鏇炍旈崨顔惧幐婵炶揪缍佸濠氱叕椤掑嫭鐓涢悘鐐额嚙閳ь剚绻堥悰顔界瑹閳ь剟鐛幒妤€绠ｆ繝闈涙－濞兼盯姊婚崒娆戭槮闁硅绻濆濠氬Ω閳轰胶鐤囧┑鈽嗗灟鐠€锕€顭囬弽銊х鐎瑰壊鍠曠花鍏笺亜閵夈儳澧涚紒缁樼洴楠炲鎮欑€靛憡顓婚梻浣圭湽閸婃洜鈧碍婢橀～蹇撁洪鍕啇闂佺粯鍔栬ぐ鍐€栭崼婵愭富闁靛牆楠搁獮姗€鏌涜箛鏃撹€块柣娑卞櫍瀹曞崬螣閼测晜鍤岄梻渚€鈧偛鑻晶顕€鏌ｉ敐澶嬫暠缂佽櫣鏅划娆戞嫚娣囧崬濮傞柡灞诲姂瀵噣宕堕懜鐢电Х闂佽瀛╂穱娲磻閹邦喗顫曢柟鎹愵嚙绾惧吋绻涢崱妯虹劸婵″樊鍠栭—鍐Χ閸℃浠村┑鈽嗗亝閻╊垶宕洪埀顒併亜閹烘垵鈧骞婂Δ鍛厱闁归偊鍨伴崝鐢告煃瑜滈崜娆忣焽閿熺姴钃熼柣鏂跨殱閺嬫棃鏌涢…鎴濇灍闁诲繑鎸搁埞鎴﹀煡閸℃ぞ鑸梺鎼炲妼閻栫厧顕ｆ繝姘労闁告劑鍔庣粣鐐烘煙閸忚偐鏆橀柛銊ヮ煼婵″瓨绻濋崶銊у幐婵炶揪绲介幗婊勬櫠閿曞倹鐓欐い鏃傜摂濞堟棃鏌嶇紒妯诲磳鐎规洖缍婇、娆撴偩鐏炲ジ鍋楅梻鍌氬€烽懗鍫曘€佹繝鍥舵晪婵犲﹤鎳忓畷鍙夌節闂堟稒鐭楃紒璇叉閺屾盯顢曢敐鍡欘槰闂佸搫鎳忚ぐ鍐€︾捄銊﹀磯闁绘碍娼欐慨娑橆渻閵堝繗绀嬮柛鏃€鍨甸～蹇撁洪鍕槰闂佸憡鐟ラˇ宕囨兜閳ь剟姊绘担渚劸妞ゆ垵妫濋獮鎰偅閸愩劎鍔﹀銈嗗笂濞村洦绔熷鈧弻鏇㈠醇閵忊晝鍔稿銈庡亜缁绘帞妲愰幒鎳崇喓鎷犲顔瑰亾閹剧粯鈷戦柛娑橈功缁犳捇鎮楀鐓庡缂佸倹甯掕灒濞撴凹鍨辩€靛矂姊洪棃娑氬濡ょ姴鎲＄粋宥呪攽閸モ晝顔曢梺鑲┾拡閸撴瑩寮告惔銊︾厽闁挎繂娲ら崢瀛橆殽閻愬弶鍠樼€殿喖鐖煎畷褰掝敊閼测斂鍋栭梻鍌氬€烽懗鍓佸垝椤栫偛钃熺憸蹇涘箯閸愵喗鏅濋柍褜鍓熷﹢渚€姊洪崨濠冨闁稿鍋撻梺琛″亾濞寸姴顑嗛悡鐔镐繆椤栨侗鍎ラ柛銈咁儑閳ь剝顫夐幃鍫曞磿閻㈢绠栨俊銈傚亾妞ゎ偅绻堝鑽も偓闈涙啞閺呭ジ姊绘担鐑樺殌缂佺姴绉瑰畷褰掓寠婢跺本娈鹃梺鍛婎殘閸婏綁鎮㈤崗灏栨嫻闂佸綊鍋婇崰姘枖閸ф鈷掗柛灞剧懄缁佺増銇勯銏╂Ц妞ゎ厼鐏濊灒缂備焦蓱閻濈兘鏌熼崗鑲╂殬闁告柨鐬肩划濠氬冀瑜夐弨浠嬫煕鐏炲墽顣查柛鐔哄仱閺岋綁骞樼捄鐑樼€鹃梺闈涙搐鐎氫即鐛Ο鍏煎磯闁绘垶顭囬埀顒冨吹缁辨挻鎷呯拠鈩冪暦閻庡厜鍋撻柟闂寸閽冪喖鏌￠崶銉ョ仼闁绘劕锕﹂幉绋款吋婢舵ɑ鏅滃銈嗘尵閸嬫劙寮ㄩ懞銉ｄ簻闁哄啫鍊归崵鈧繛瀛樼矒缁犳牕顫忕紒妯诲闁告繂瀚紓鎾绘⒑缁嬪潡鍙勫ù婊嗘硾閻ｇ兘顢涢悙鏌ユ暅濠德板€愰崑鎾剁磼閻樿櫕銇濋柡宀嬬秮婵偓闁绘ê鍟块弳鍫ユ⒑閹惰姤鏁遍柛銊ユ贡濡叉劙骞掑Δ濠冩櫖濠电偞鍨堕悷褔藝閵娾晜鈷戦柛婵嗗濡插摜绱撳鍜冭含鐎殿喛顕ч埥澶愬閻樻鍟嬮梺璇查叄濞佳囧箺濠婂牊鍋╅柤娴嬫櫇绾捐棄銆掑顒佹悙婵炲懏锕㈤弻娑樷枎韫囨挻娈诲Δ鐘靛仜閸熷瓨鎱ㄩ埀顒勬煏閸繃顥滃ù婊勵殜閺岀喖鎳濋悧鍫濇锭缂備浇寮撶划娆撳春閳ь剚銇勯幒鎴濃偓鍛婄鏉堛劍鍙忓┑鐘叉噺椤忕娀鏌嶈閸撴瑥锕㈡潏銊﹀弿闁汇垻顭堣繚闂佸憡鍔︽禍鐐靛婵傚憡鐓冪憸婊堝礈濮樿泛绠柛娑樼摠閸婄粯鎱ㄥΔ鈧Λ妤佺閻戞ü绻嗛柣鎰典簻閳ь剚鐗犻獮鎰板醇閺囩偛鐎┑鐐叉▕娴滄粓鎮￠弴銏＄厵闁绘垶锕╁▓鏇㈡煟閹惧瓨绀嬮柟顔斤耿閹瑩骞撻幒鍡樺瘱闂備胶鎳撻崯鍨涘┑瀣摕婵炴垶绮庨悿鈧梺瑙勫劤閻°劑骞忛柆宥嗏拺闂傚牊绋掗幖鎰版倵濮橆偄宓嗛柕鍡曠椤粓鍩€椤掑嫬绠栨繛鍡樻尰椤ュ牊绻涢幋鐐茬瑨鐎垫澘绉瑰铏规嫚閹绘帩鍔夊銈嗘⒐閻楃姴鐣烽弶娆炬僵閻犺櫣鍎ら悗顒佺節閻㈤潧校闁告繂閰ｉ崺鈧い鎴ｆ硶椤︼箓鎽堕弽顓熺厱婵炴垵宕獮妯汇亜閿旇姤绶叉い顏勫暣婵″爼宕卞Δ鈧鎴︽⒑缁嬫鍎愰柟鍛婃倐濠€渚€姊虹紒妯兼喛闁稿鎹囬弻娑樷枎韫囨挻娈銈庡亜缁绘劗鍙呭銈呯箰閹峰螞閸愩劉鏀介柣鎰綑閻忓崬顪冪€靛壊鐒鹃柣鈽嗗弮濮婂宕掑▎鎴М闂佸湱鈷堥崑濠囩嵁婵犲懐鐤€闁哄洨鍋涢悘濠囨⒑鐟欏嫬鍔ょ痪缁㈠弮瀵娊鏁冮崒娑氬幐闂佹悶鍎弲娑㈠几閺冨倻纾奸柍閿亾闁稿鎹囧缁樻媴鐟欏嫬浠╅梺绋垮瘨閸ㄨ泛鐣峰┑鍥ㄥ劅闁靛鍎遍崑宥咁渻閵堝懐绠伴柟铏姉瀵囧焵椤掑嫭鈷戞慨鐟版搐閻忓弶绻涙担鍐插椤╅鎲搁弮鍫濊摕婵炴垶鍩冮崑鎾绘晲鎼粹€茬凹闁诲繐娴氶崣鍐蓟瀹ュ洦瀚氶柤纰卞劮瑜忛埀顒冾潐濞叉牕鐣烽鍕叀濠㈣泛艌閺嬪酣鏌熺€涙绠撶紒鐘虫そ濮婂宕掑▎鎰偘濡炪値鍋勯ˇ闈涚暦閺囥垹绀冮柤纰卞墯濞堟儳顪冮妶鍡楃瑨閻庢凹鍓涚划鍫熷緞鐎ｎ剛鐦堟繝鐢靛Т閸婂綊宕抽悾宀€妫柟瑙勫姇娴滃湱绱掓潏銊﹀鞍闁瑰嘲鎳愰幏鐘绘晬閸曨偄楔濠电姷鏁搁崑鐐躲亹閸愵喗鍋ら柕濞炬杺閳ь剙鍟存俊鐑藉煛閸屾埃鍋撴搴樺亾閻熸澘顥忛柛鐘崇墵瀹曟粓宕奸弴鐔叉嫼闁荤姴娲犻埀顒冩珪閻忓秶绱撴笟鍥ф灍闁瑰憡鎮傞幃楣冩倻閽樺顢呴梺缁樺姀閺呮粓鎮楁繝姘棅妞ゆ劑鍨烘径鍕煙缁嬪灝鏆ｅ┑鈩冩倐閸╋繝宕掑Δ浣割伜闂傚倷鑳堕…鍫ュ嫉椤掑嫭鍋￠柕濞炬櫅缁€鍌溾偓鍏夊亾闁逞屽墰濡叉劙骞掑Δ濠冩櫔闂佸憡渚楅崢鐐椤栫偞鈷戦弶鐐村鐠愪即鏌涢敐蹇曠М妤犵偛鍟埢搴ㄥ箻閸忓懐鐐婇梻浣告啞濞诧箓宕ｆ惔鈭ワ綁顢涘☉姘辩槇濠电偛鐗嗛悘婵嬪几閻斿吋鐓忛柛銉ｅ妿濞插鈧娲橀崹鍧楃嵁濮椻偓瀹曠懓鈽夊Ο鐟邦棜婵犵數鍋涢悧鍡涙倶濠靛鍑犻柨鏂款潟娴滄粓鏌￠崶褎顥滄繛鏉戝€垮顐﹀炊瑜夐弨浠嬫煕鐏炲墽鐭ら柣鎺楃畺濮婃椽宕￠悙鏉戭槱闂侀潧娲ょ€氫即鐛崶顒€绀堝ù锝囨磪閿濆鈷戦梺顐ゅ仜閼活垱鏅堕鐣岀鐎瑰壊鍠栭獮鏍ㄣ亜椤愩垻绠崇紒杈ㄥ笒铻ｉ悹鍥ф▕閳ь剚鎹囧娲川婵犲嫧妲堥梺鎸庢磸閸婃繂顕ｉ幎钘夐唶闁靛鑵归幏娲⒑闂堚晛鐦滈柛娆忛叄閹偤鎮欓鍙ョ盎濡炪倖鎸炬慨鎾储鐎涙﹩娈介柣鎰絻閺嗭綁鏌熼鐣岀煉闁圭锕ュ鍕沪閽樺顔囧┑鐘垫暩閸嬬偤骞愭繝姘殞闁诡垼鐏愬ú顏勎ч柛娑变簼閻忎線姊洪棃娴ュ牓寮插鍫濈厱闁瑰鍋為崣蹇涙煟閻斿搫顣奸柟鍏煎姍閺岋綀绠涙繝鍐╃彅濡炪値鍘煎锟犲箖妞嬪孩鏆滄い鏂跨仢閹牓鏌ｆ惔銏╁晱闁革綆鍣ｅ畷鎴炵節閸屾粍娈鹃梺鍛婎殘閸嬫劕危閸喓绠鹃柛鈩兠悘銉╂偨椤栨侗娈滈柡宀嬬秮閹垽宕妷褏鍘戠紓鍌欑贰閸犳骞愰幖浣瑰仼鐎瑰嫰鍋婇悡銉╂煕閹板墎绋婚柣搴☆煼濡懘顢曢姀鈥愁槱濠电偛寮堕敋闁崇粯鎸荤缓浠嬪川婵炵偓瀚奸梻浣告啞缁嬫垿鏁冮妷锕€绶為柛鏇ㄥ灡閻撴洟鏌曟繛鐐珒闁规煡绠栭弻娑㈠煛閸屾粍鍒涘Δ鐘靛仜椤戝寮崒鐐村仼閻忕偠妫勭粻鐐测攽閻樺灚鏆╅柛瀣仱瀹曞綊宕奸弴鐔告珖濡炪倖鍔х粻鎴犵矆婢舵劖鐓熼柡鍐ㄦ处椤忕姷鐥崣銉х煓闁哄本绋撴禒锕傚礈瑜夊Σ鍫ユ⒑閸涘﹦绠栨俊鐐扮矙瀵鏁嶉崟顏呭媰闂佸憡鎸嗛埀顒佹叏閸ヮ剚鈷戦悹鍥ｂ偓宕囦画濠碘槅鍋勯崯鏉戠暦瑜版帒绠氱憸蹇涘汲閿曞倹鐓曢柕澶樺枛婢ф壆鈧娲樼划鎾愁潖婵犳艾纾兼繛鍡樺焾濡差噣姊虹涵鍜佸殝缂佽鲸娲熷顐︻敋閳ь剟鐛幒鎳虫梹鎷呯憴鍕絿闂傚倷绶氬褔鏁嶈箛娑樺窛妞ゆ牗鍑瑰Σ杈ㄧ節閻㈤潧浠滄い鏇ㄥ幗閹便劑骞橀鍛櫈闂佸憡渚楅崣搴ㄥ疮閸涱喚绡€闂傚牊绋掗ˉ鎴︽煛閳ь剚绂掔€ｎ偆鍘藉┑鈽嗗灥椤曆呭緤缂佹ǜ浜滈煫鍥э攻濞呭﹪鏌熼鑽ょ煓妞ゃ垺绋戦埥澶嬫綇閵娧勬緬濠电姵顔栭崰鏍晝閵夈儺娓诲ù鐘差儏缁犵娀鏌ㄩ悢鍝勑㈤崶鎾⒑閸涘﹣绶遍柛鎾村哺瀹曠喖宕橀鍡欙紳闂佺鏈悷褔藝閿斿浜滈柟瀛樼箖閸ゅ洭鏌熼銊ユ搐缁犲鎮归崶褍绾ф俊宸墴濮婃椽鏌呴悙鑼跺濠⒀屽灦閺屾洟宕惰椤忣厽顨ラ悙鏉戞诞鐎规洖宕—鍐箚瑜滃Λ婊堟⒒閸屾艾鈧绮堟笟鈧獮澶愭闁圭瓔鍋婂铏圭磼濮楀棙鐣峰銈冨妼閻楀繘宕氶幒妤€鐓涢柛娑卞枛娴滄粓姊虹紒妯诲碍濡ょ姷顭堥悾鐢稿幢濞戞瑢鎷虹紓鍌欑劍閿曗晠鎮炴禒瀣厸濞达綀顫夐崐鎰版煛娴ｅ摜孝闁宠鍨归埀顒婄秵閸嬧偓闁圭柉娅ｇ槐鎾存媴閸撴彃鍓遍柣搴ｇ懗閸愯儻鈧灝霉閻撳海鎽犻柣鎾跺Х閹叉悂鎮ч崼婵堫儌闂佷紮绲惧浠嬪蓟濞戙垹鐓橀柟顖嗗倸顥氭繝纰夌磿閸嬫垿宕愰弽褜鍟呭┑鐘宠壘绾惧鏌熼崜褏甯涢柣鎾寸懇閺屻倝骞侀幒鎴濆Б闂佹椿鍘奸惌鍌炲蓟濞戙垹绠抽柟鎹愭珪鐠囩偤鎮楀▓鍨珮闁革綇绲介悾閿嬬附閸涘﹤浜滈梺鐐壘閸婅崵妲愰敃鍌涒拻闁稿本鐟чˇ锕傛煙鐠囇呯？缂侇喗鐟╅獮瀣晜閼恒儲鐝栭梻渚€娼чˇ顓㈠磿椤曗偓瀵顓兼径瀣幈闂侀潧顦介崰鏍ㄦ櫠椤栫偞鐓冮梺鍨儏閻忓瓨鎱ㄦ繝鍌ょ吋鐎规洖銈搁幃銏ゅ箒閹哄棗浜鹃柟鐑樻⒒绾惧ジ鏌ｅ鈧褎绂掗柆宥嗙厸閻忕偛澧介埊鏇犵磼缂佹绠炵€规洘锕㈤崺锟犲礃閻愵儷銈囩磽閸屾艾鈧娆㈤敓鐘茬獥闁哄稁鍘搁埀顒婄畵閹粓鎸婃径宀€鏆梻浣稿暱閹碱偊骞婃惔锝囩焼闁稿瞼鍋為悡鏇熺箾閹存繂鑸归柣蹇ョ秮閺岋綁鏁愭径宀€鏆┑顔硷功缁垳绮悢鐓庣劦妞ゆ巻鍋撴い顓炴穿椤﹀綊鏌熼銊ユ搐楠炪垺绻涢幋鐑嗙劷闁汇倕娲Λ鍛搭敃閵忊€愁槱缂備礁顑嗛崹鍨潖婵犳凹鏁嶆繛鎴炴皑椤旀洟鎮楅悷鏉款棌闁哥姵娲滈懞杈ㄧ附閸涘﹦鍘介梺瑙勫劤閻°劎绮堢€ｎ喗鐓涢悘鐐靛亾缁€瀣偓瑙勬礈閸樠囧煘閹达箑鐐婄憸搴敂閵堝鈷戦弶鐐村椤︼箓鏌ｅΔ浣瑰碍妞ゎ偄绻愮叅妞ゅ繐瀚槐鍫曟⒑閸涘﹥澶勯柛鎾村哺楠炲繘宕￠悙鈺傛杸闂佺粯鍔栬ぐ鍐棯瑜旈弻銊ヮ潩椤撴粈绨婚梺鍝勬处閿氶柛鏃撳閳ь剝顫夊ú婊堝窗閺嶎厹鈧礁鈽夊鍡樺兊闁荤姾娅ｉ崕銈夊汲椤忓嫧鏀介柣妯虹仛閺嗏晛鈹戦悙鈺佷壕婵犵數鍋橀崠鐘诲礂閻愵剛鈽夐摶鏍煕濮樿櫕顥夋い锔诲灦閸┿垺鎯旈妸銉ь啋缂備緡鍠涢～澶屸偓姘虫閳规垿鎮欓懜闈涙锭缂備焦褰冨锟犲灳閿曞倸閱囬柕澶堝劜鏉堝牓姊绘笟鍥у缂佸鏁婚幃鈥斥枎閹寸姵锛忛梺鍝勵槸閻忔繈鎳滈悷鎳婄懓顭ㄩ崨顓ф毉濡炪們鍔婇崕鐢稿箖濞嗘垶瀚氱憸鏃傛鐎靛摜纾藉ù锝呮惈鏍＄紓浣割儐閸ㄥ潡宕洪妷锕€绶炲┑鐐灮閸犳挸鈽夐崹顐Ч閹肩话銈傚亾閸ф鈷掗柛灞捐壘閳ь剛鍏橀幃鐐烘晝閸屾艾鍤戞繝闈涘€婚…鍫ユ偪閻愵剛绠鹃柟瀛樼懃閻忊晠鏌ｉ妶搴℃珝闁哄瞼鍠庨埢鎾诲垂椤旂晫浜惧┑鐐村灦閹稿摜绮旂壕瀣簷闂備焦瀵х换鍌炲箠鎼淬劌姹查柣鎰劋閻撶喖鏌熼幆褏鎽犵紒鈧€ｎ喗鐓涢悘鐐垫櫕鏁堥梺绯曟杹閸撴繈骞忛崨鏉戝窛濠电姴瀚竟鏇炩攽閻樺灚鏆╅柛瀣洴閹勭節閸ワ絺鍋撻敃鍌氱倞闁冲搫鍋嗗鐔兼⒑閸︻厼鍔嬫い銊ユ瀹曟垿骞囬悧鍫氭嫽闂佸壊鍋嗛崰宥囨闁秵鐓涢柛鈾€鏅涘顔芥叏婵犲啯銇濇俊顐㈠暙閳藉鈻庨幇顓炩偓鐑芥⒑鐠囨彃顒㈤柛鎴濈秺瀹曠懓鐣烽崶褍鐏婇柣鐘叉处缁佹潙危閸喓绠鹃柛鈩兠悘鈺呮煟閿曗偓閻楁挸顫忓ú顏勫窛濠电姴鍊搁～鍛存⒑閸濆嫭鍣虹紒璇叉婵＄敻骞囬鐟颁壕闁挎繂楠搁弸鐔兼煃闁垮绗掗棁澶愭煥濠靛棙鍣洪柛鐔哄仱閺岀喖顢涘鍗炩叺闂佸搫鐭夌换婵嗙暦婵傚壊鏁冮柕蹇曞Л閹奉偊姊绘担绛嬪殐闁搞劍澹嗛埀顒佺煯閸楁娊濡存担绯曟闁靛繆鈧枼鍋撻悜鑺ョ厾缁炬澘宕崢鍝ョ磼鏉堛劎鐭掓慨濠勭帛閹峰懘鎮烽柇锕€娈濇繝鐢靛仜瀵爼鎮ч悩鑼殾闁圭増婢樻导鐘绘煏婢诡垰鍊婚悷婵嬫⒒娴ｇ懓顕滅紒璇插€歌灋婵炴垶鑹炬慨顒勬煃瑜滈崜鐔奉潖婵犳艾纾兼慨妯哄船椤も偓缂傚倷绀侀鍡涘箰婵犳艾鐤鹃柛顐ｆ礀缁秹鏌嶈閸撴氨绮氭潏銊х瘈闁稿濮ゅ褰掑箯閸涘瓨鍋￠柟娈垮櫘閺嗭繝姊婚崒娆戭槮闁汇倕娲敐鐐村緞閹邦剙鐎梺绉嗗嫷娈旂紒鐘崇墵閺屽秵娼幏宀婂敼闂佸搫顑嗗Λ鍐蓟閻旇櫣鐭欓柛顭戝櫘閸斿姊烘导娆撴缂侇喗鎸搁～蹇曠磼濡偐鎳濋梺閫炲苯澧撮柛鈹惧亾濡炪倖甯掗崐鍛婄濠婂牊鐓犳繛鑼额嚙閻忥繝鏌￠崨顓犲煟妞ゃ垺鐟╁畷婊嗩槼闁挎稑绻掔槐鎾诲磼濞嗘挻顎栭梺鎼炲妿閹虫捇顢氶敐澶樻晩缂佹稑顑嗛鏃堟⒑缂佹ê濮堥柟顖氳嫰閳绘挸顭ㄩ崼鐔哄幍濡炪倖妫侀～澶娾枍閸モ晝纾奸弶鍫涘妼缁楁帡鎽堕敐澶嬬厽闁圭偓濞婇妤冪磼閻橆喖鍔︽慨濠呮閹风娀宕ｆ径瀣棷闂備胶顢婂▍鏇㈠箰妤ｅ啫鐒垫い鎺嶇閸ゎ剟鏌涢悩鎰佹疁鐎殿喛灏欓幑鍕媴閺囩喐顥堢€规洏鍔戦、姗€濮€閳藉懐鑸归梻浣藉吹閸犳劗鍒掓惔銏℃珷婵°倕鍟弳婊勪繆閵堝懏鍣洪柛瀣€块弻锝夊棘閸喗鍊梺缁樻尪閸庤尙鎹㈠┑瀣棃婵炴垶鐟Λ銈囩磽娴ｅ搫孝缁剧虎鍘惧Σ鎰板箳濡も偓閻撱垽鏌嶈閸撶喎鐣烽幋锕€绠荤紓浣骨氶幏缁樼箾鏉堝墽鎮奸柣鈩冩瀹曠敻宕橀鐣屽幈闂佺粯娲戠粈浣圭閹殿喒鍋撶憴鍕闁稿骸銈歌棟鐟滅増甯楅悡鏇㈡煟閹邦垰鐨洪柛鈺嬬稻閹便劍绻濋崨顕呬哗缂備浇椴哥敮鎺曠亽闂佺厧顫曢崐鏇烆嚕閸愭祴鏀介柣姗嗗枛閻忣噣鏌熼搹顐ｅ磳闁轰礁鍟撮、鏃堝礋椤撶喐顔曢梻渚€娼чˇ顓㈠磿椤曗偓瀵憡鎯旈妸锔惧幍闂佸憡鎸嗛崰顐㈩樀閺岀喎鐣￠柇锔惧悑濠殿喖锕ㄥ▍锝囧垝濞嗘挸绠伴幖娣灪鐎氭娊姊绘担鍝勫付缂傚秴锕︾划濠氬冀椤撶偞妲梺閫炲苯澧柕鍥у楠炴帡骞嬪┑鍐ㄤ壕闁归棿绀侀崒銊╂煙缂併垹鏋熼柣鎾寸懄閵囧嫰寮埀顒勫磿閾忣偆顩烽梺顒€绉甸悡娑樏归敐鍥剁劸闁哄棴缍侀弻娑㈠煘閹傚濠碉紕鍋戦崐鏍暜閹烘柡鍋撳鈧崶褏鍔﹀銈嗗笂閻掞箓藟閸懇鍋撶憴鍕闁挎洏鍨介妴浣糕枎閹邦噣妾梺鍛婄☉閿曘儱鈻撻弬搴撴斀闁绘灏欏Λ鍕煛婢跺﹦姘ㄩ柛瀣崌楠炲洭寮剁捄顭掔幢闂備浇顫夐崕铏櫠鎼达絽顥氬┑鍌氭啞閻撴瑩姊洪銊х暠鐎殿喚鍋撶换娑㈠醇閻旇櫣鐓夐梺鍝勫閳ь剙纾弳鍡涙倵閿濆骸澧伴柣锕€鐗撻幃妤冩喆閸曨剛顦ラ梺缁樼墪閵堢鐣峰ú顏呮櫢闁绘灏欓崝锕€顪冮妶鍡楃瑨闁稿﹤缍婇敐鐐哄即閻橆偄浜鹃悷娆忓缁€鈧┑鐐额嚋缁犳挸鐣锋导鏉戠疀闁绘鐗忛崢钘夆攽鎺抽崐鎰板磻閹剧粯鐓熸俊銈傚亾婵☆偅绋撻崚鎺楊敇閵忕姷顔婂┑掳鍊撻懗鍫曞储娴犲鈷戠憸鐗堝笒娴滀即鏌涢幘鍗炲闁绘搩鍓熼、妤呭礋椤掑倸骞愰梺璇茬箳閸嬬喖寮查锝嗘珡闂佽姘﹂～澶娒洪敃鍌氱；濠电姴鍊婚弳锕傛煟閺冨倵鎷￠柡浣稿暣閺屻劌鈹戦崱姗堢礊闂佸摜鍋為悡鈥愁潖閾忚瀚氶柛娆忣槸閺€顓烆渻閵堝骸浜滄い锔诲灣閸欏懘妫呴銏″缂佸鍨规竟鏇㈠锤濡や讲鎷婚梺鍓插亞閸犲秶娆㈡潏銊х闁稿繗鍋愭晶鐢告煛鐏炵喎妫涢悿鈧梺鐟板⒔椤ユ劗娑甸埀顒傜磽娴ｅ搫浜鹃柛搴㈠▕瀹曘儳鈧綆鍋嗛埞宥呪攽閻樺弶绁╅柡浣哥У缁绘繈妫冨☉娆樻闂佽鍨抽崑銈咁潖濞差亜宸濆┑鐘插閸Ｑ冣攽閳藉棗浜濈紒璇插€块敐鐐剁疀閹句焦妞介、鏃堝礋椤愩倗宕烘繝鐢靛Х閺佸憡鎱ㄩ幘顔肩疇閹兼番鍓径濞炬斀闁糕檧鏅滅€靛矂姊洪棃娑氬婵☆偅顨婇幃姗€濡烽敂杞扮盎闂佹寧妫侀褔鎮橀敃鍌涚厵妞ゆ洍鍋撶紒鐘崇墵楠炲啫顭ㄩ崼鐔风檮婵犮垼娉涢惌鍫ュ触閸涘瓨鈷掑ù锝囨嚀椤曟粍绻涢幓鎺斝х€规洘鍨块獮妯肩磼濡厧骞楅梻浣筋潐閸庢娊顢氶鐏绘椽骞橀鐣屽幐闁诲繒鍋涙晶浠嬪煡婢舵劖鐓冮柦妯侯樈濡偓閻庤娲╃换婵嬪箖濞嗘垟鍋撻悽鍛婃珳闂侇収鍨跺濠氬磼濞嗘垹鐛㈤梺閫炲苯澧伴柛瀣洴閹崇喖顢涘☉娆愮彿濡炪倖娲嶉崑鎾绘煛瀹€瀣М鐎殿喖鈧噥妲归梺绋款儍閸ㄥ鍩€椤掍緡鍟忛柛鐘崇墵閳ワ箓鎮滈挊澶嬬€梺褰掑亰閸樿偐娆㈤悙娴嬫斀闁绘ɑ褰冮顐︽煛婢跺﹥鍟炲ǎ鍥э躬閹瑩顢旈崟銊ヤ壕闁哄稁鍘介崑瀣繆閵堝懎鏆熼柣顓熺懇閺岀喖骞戦幇闈涙閺夆晜绻堝铏规喆閸曨偒妫嗘繝鈷€鍕垫疁鐎规洘鍨块幃鈺呮惞椤愩垹浼庢繝娈垮枟椤ㄥ懎螞濡ゅ懐宓侀柡宥庡幗閻撴洘绻濋棃娑欏闁靛洦绻堥弻锛勪沪缁洖浜剧€规洖娲﹀▓鏇㈡煟鎼搭垳绉甸柛鎾寸閹筋偊姊婚崒娆愮グ妞ゆ洘鐗犲畷褰掑础閻愬秵鐩畷姗€鍩￠崒姘紟闂備線鈧偛鑻晶鎾煛鐏炵偓绀夌紒鐘崇⊕缁绘繈宕橀埡鍐ㄧ稻濠电姷鏁搁崑娑㈡偋閸℃瑧绀婂┑鐘叉搐閽冪喖鏌ㄥ┑鍡╂Ч闁稿瀚伴弻娑樷攽閸曨偄濮㈤梺缁樻尫缁€渚€鍩為幋锔藉亹妞ゆ棁鍋愭禒楣冩⒑閹稿孩纾搁柛銊ョ秺閹箖鎮滅粵瀣櫖闂佺粯鍔樼亸娆擃敊閹烘埈娓婚柕鍫濇椤ュ棝鏌涚€ｎ偄濮堥悗浣冨亹閳ь剨缍嗛崰妤呭煕閹达附鐓欑紒瀣仢椤掋垻绱掗埀顒勫焵椤掑嫭鈷戠紒瀣皡閺€濠氭煙椤旂厧鈧灝顕ｆ繝姘╅柍杞扮导瑜旈弻娑㈠焺閸愨晝顦紓浣哄У瀹€绋款潖濞差亝顥堟繛鎴炶壘椤ｆ椽姊虹粙鍖″伐闁硅绱曠划瀣吋婢跺﹦顦悷婊冪箳婢规洟鎸婃竟婵嗙秺閺佹劙宕ㄩ钘夊壍闂佸搫绋勭换婵嬪箖濡ゅ懎绀傚璺猴梗婢规洟姊绘担鍝ョШ婵☆偉娉曠划鍫熺瑹閳ь剟骞忛幋锔藉亜闁稿繗鍋愰崢浠嬫⒑閸濆嫬鈧棄鈻旈弴鐐╂灁闂侇剙绉甸悡娑㈡倵閿濆骸浜濇い銉ョ墦閺岋紕浠﹂崜褎鍒涢梺鐐藉劵缁犳捇鐛€ｎ亖鏀介柛銉㈡櫃閹查箖姊婚崒娆愮グ妞ゆ泦鍛床闁硅揪绠戠粻浼存煕閹炬瀚峰鐔兼⒑鐟欏嫬绀冩い鏇嗗懎顥氶柛蹇撳悑閸欏繑淇婇姘儓闁肩缍婇弻宥夘敂閸曨厺绮电紓浣虹帛缁嬫捇鍩€椤掍胶鈯曟い顓炴喘閹本绻濋崶銊у幗闂佸搫绋侀崑鍕暜閼哥偣浜滈柡鍥朵簽缁嬭崵绱掔紒妯肩畵妞ゎ偅绻堥、姗€鎮㈤崫銉ョ濠电姷鏁告慨浼村垂閻撳簶鏋栨繛鎴欏焺閺佸嫰鏌涘☉鍗炴灓妞も晛寮剁换婵囩節閸屾粌顤€闂佹娊鏀遍崹鍧楀蓟濞戞ǚ妲堟慨妤€鐗嗘慨娑氱磽閸屾艾鈧懓鐣濋幖浣歌摕婵炴垶鐟﹂崕鐔兼煏韫囧鐏╃€殿喓鍔戦幃妤冩喆閸曨剛顦梺杞版祰椤曆囨偩閻戣棄绠抽柟鎼幘閸欏棝姊洪崨濠佺繁闁搞劎鏅Σ鎰板礃濞村鏂€闂佺粯鍔橀崺鏍亹瑜忕槐鎺楃叓椤撶姷鐓撳Δ鐘靛仦閻楃娀銆侀弴銏℃櫜闁搞儜鈧崣鐐烘⒒閸屾艾鈧悂宕愰悜鑺ュ殑闁割偅娲栫粻鐘绘煙閹规劦鍤欑紒鐘靛枛閺屻劑鎮㈤崫鍕戙垻绱掗悩宕囧⒌闁哄本绋戦悾婵嬪焵椤掑嫬纾绘繛鎴炴皑娑撳秹鏌″搴ｄ粶闁哄啫鐗婇弲鏌ユ煕濞戝崬骞楁繛鍫熺叀濮婅櫣绮欓崠鈥充紣濡炪値鍘鹃崗妯侯嚕婵犳碍鏅濋柍褜鍓濋悘鎺楁⒑缂佹澹樻い鏇ㄥ幘缁牓宕卞☉娆屾嫼闂傚倸鐗婇崡鏇㈠醇閵夈儳鏌у┑鐘诧工閻楀﹪宕戦崒鐐寸厪濠㈣泛妫欏▍鍡涙煟閹惧娲撮柡灞剧洴楠炲洭鍩℃担鍓茬€村┑鐘灱濞夋稓鈧凹鍙冩俊鐢稿礋椤栨銊╂煏婢舵ê鏋熼柍璇茬墦濮婃椽宕崟顒佹嫳闂佺儵鏅╅崹浼搭敋閿濆鏁嗛柛鏇ㄥ亞椤斿洭鏌熼懖鈺勊夐柛鎾寸箞閹墽绱掑Ο鑲╃槇濠电偛鐗嗛悘婵嬪几濞戙垺鐓ラ柡鍥崝姘亜椤忓嫬鏆ｉ柟绋匡攻缁旂喖鍩￠崒婊勫垱閻庤娲橀敃銏′繆閹间礁顫呴柍钘夋缂嶅苯鈹戦悩鍨毄闁稿绋戣灋婵炲棙鎸搁弰銉╂煕椤愶絿璐╂繛宸簼閸ゅ鏌ｉ姀銏℃毄闁伙箑鐗撳鍝勑ч崶褏浼堝┑鐐板尃閸″繐褰洪梻鍌氬€烽懗鍫曞箠閹捐鐤柛顭戝晹濞差亶鏁囬柣鎰仛濞堥箖姊虹涵鍛涧缂佺姵鍨圭划濠氭嚒閵堝洨锛濇繛杈剧秮椤庡洤顫濈捄铏诡唵濠电偛妯婃禍婵嬪煕閹达附鐓曟繛鎴烇公閸旂喖鏌嶉挊澶樻█闁哄被鍔戝鏉懳熺悰鈥充壕婵犻潧顑呯粻鏍ㄦ叏濡炶浜鹃梺杞扮劍閸旀瑥鐣烽崼鏇炵厸闁告劘娉曟惔濠傗攽閿涘嫬浜奸柛濠冪墪椤繑绻濆顒傛煣濡炪倖鍔х粻鎴犵不閻樼粯鐓曢柟鑸妽閺夊搫霉濠婂嫮鐭嬮柕鍥у楠炲洭鍩℃担杞扮磿缂傚倷鑳舵慨鎯х暦閻㈢鐒垫い鎺戝枤濞兼劖绻涚拠褏鐣电€规洘鍨剁换婵嬪磼濠婂嫭顔曟繝鐢靛█濞佳囶敄閸涱垰顥氱憸鐗堝笚閻撶喖鏌￠崒姘变虎妞ゃ儱绻愰湁闁绘﹩鍋呭▍濠冩叏婵犲啯銇濋柟顔惧厴瀵爼骞愰獮顔规櫅椤啴濡堕崱妤冧淮闂佺娅曢敃銏ょ嵁閸愨斂鍋呴柛鎰ㄦ櫅閳ь剙顭烽弻锕€螣娓氼垱楔闂佺锕﹂崑銈咁潖濞差亝顥堟繛鎴ｄ含閸欐岸姊婚崒姘仼閻庢矮鍗抽妴渚€寮崼鐔告珳婵犮垼娉涢鍌炲箯婵犳碍鈷戠紒瀣濠€浼存煠瑜版帞鐣洪柛鈹惧亾濡炪倖甯掔€氬嘲螞閹寸姷纾兼い鏃囧亹婢ф稓绱掑Δ鍐ㄦ灈闁糕斁鍋撳銈嗗笒鐎氼喖鐣垫担閫涚箚闁靛牆鍊告禍鎯ь渻閵堝骸骞戦柛鏃€鍨甸悾鐑芥偄绾拌鲸鏅㈤梺閫炲苯澧い鏇秮瀹曠螖娴ｅ弶瀚兼繝娈垮枤閹虫挸煤閵堝鍊舵い鏂款潟娴滄粍銇勯幘璺轰户濠⒀佸灮缁辨帡顢欓懖鈺侇杸閻庡灚婢樼€氼噣鍩€椤掑﹦绉甸柛鎾寸洴椤㈡瑩寮撮姀鈾€鎷虹紓渚囧灡濞叉牗鏅堕弻銉﹀珔闂侇剙绉甸崐鍫曠叓閸ラ瀵奸梺顓у灦閺岋紕浠﹂悾灞濄儲銇勮缁舵岸寮诲☉婊呯杸闁哄啫鍊堕埀顒佸笧缁辨帡顢欓懖鈺侇杸闂佺懓鍢查幊姗€骞冮崜褌娌柤娴嬫櫈閸忔帡姊婚崒姘偓鎼佸磹妞嬪孩顐芥慨妯挎硾閻掑灚銇勯幒鎴濃偓鍛婄濠婂牊鐓犳繛鑼额嚙閻忥繝鏌￠崨顓犲煟妤犵偞锕㈤、娆撴偩鐏炶棄绗氶梻鍌欑窔濞佳囁囨禒瀣瀭闁规儼濮ら崑鈺呮⒒閸喓鈻撻柡鈧禒瀣厓闁宠桨绀侀弳鐐烘煕婵犲啫濮嶉柡灞剧洴閸╃偤骞嗚閳峰姊洪悷鏉挎Щ闁瑰啿绻掔划顓㈡偄绾拌鲸鏅┑鐐存綑閻栥垽宕橀敐鍡樻澑闂備焦瀵х粙鎴犫偓姘煎墯缁傚秵绺介崨濠勫幈婵犵數濮撮崯鐗堟櫠閻㈢鍋撶憴鍕缂傚秴锕ら悾宄邦煥閸曨剙顎撻梺鍦帛鐢﹥绔熼弴鐘电＝濞达綀顕栧▓鏇犵磼鐎ｎ偄鐏ラ悡銈夋煏閸繍妲归柛銈咁儔閺岋綁鎮㈤悡搴濆枈闂佺粯鏌ㄥΛ婵嬪蓟閵堝绠瑰ù锝堫潐闁款厽绻濆▓鍨灈闁绘鎹囧璇差吋婢跺鍙嗛柣搴秵娴滅偤鎮烽妸鈺傗拻闁搞儜灞锯枅闂佸搫琚崝宀勫煘閹达箑骞㈡繛鍡楁禋閺夊憡淇婇悙顏勨偓鏇犳崲閹烘挾绠鹃柍褜鍓熼弻鐔碱敊閼姐倗鐓撳銈冨灪缁嬫垿鍩ユ径濠庢僵妞ゆ挾鍋涢悘锟犳⒒閸屾瑧顦﹂柟纰卞亰瀵敻顢楅崟顒€鍓銈嗙墬閸戝綊宕甸弴鐔翠簻闁哄洦顨呮禍楣冩⒑缁洘鏉归柛瀣尭椤啴濡堕崱妤冪懆闁诲孩鍑归崣鍐嚕閹绘巻鏀介悗锝庡亞閸橆亪妫呴銏″婵炲弶鐗曢弳鈺呮⒒娴ｅ憡鎯堟俊顐ｆ尦濮婁粙宕熼鐔峰簥濠电偞鍨堕敃鈺呭疮閸涱喓浜滈柡鍐ㄦ搐閸氬綊鏌ｉ埡渚€鍙勬慨濠冩そ瀹曘劍绻濋崒姘兼綂闂備胶顭堥鍡涘箲閸ヮ剙钃熼柨婵嗩槹閸嬪嫰鏌涘┑鍕姢闁绘挴鍋撶紓鍌氬€烽懗鍓佸垝椤栫偞鏅俊鐐€栧ú鈺冪礊娓氣偓閻涱喗鎯旈妸锕€娈熼梺闈涱檧闂勫嫰鎮甸弽顓熲拻濞达絼璀﹂悞楣冩煛閸偄澧扮紒顔界懇楠炴鎷犻幓鎺戜憾闂備焦鐪归崹褰掑箟閿熺姴鐓曢柟杈鹃檮閸嬶綁鏌涢妷顖滃矝闁稿鎸搁悾鐑藉炊閿旂偓鏆版繝鐢靛Х閺佸憡鎱ㄦ导鏉戝瀭婵炲樊浜栭埀顒婄畵瀹曞ジ濡烽敐鍌氫壕闁稿瞼鍋涢柨銈嗕繆閵堝嫯顔夐柟椋庣帛缁绘稒娼忛崜褏袣濠电偛鎷戠徊鍧楀极椤斿皷妲堥柕蹇ョ磿閸橀潧鈹戦鐣岀畵闁兼椿鍨跺畷銉╁捶椤撶姷锛滃銈嗘⒒閺咁偊骞婇崶顭戞闁绘劕妯婇崕鏃堟煛娴ｇ鈧灝鐣峰Δ浣哥窞濠电姳绀侀ˉ姘舵⒒娴ｇ懓顕滄慨濠傤煼瀹曟垿骞樺畷鍥ㄦ婵犮垼鍩栭崝鏍偂韫囨挴鏀介柣妯垮皺缁犳娊鏌ｉ敐鍫滃惈闁汇儺浜炵槐鎺楀閻樺吀妗撴繝娈垮枛閿曘儱顪冩禒瀣祦闁糕剝鍑瑰Σ鍓х磽娴ｅ搫校濠电偛锕濠氭偄閸忓吋鍎銈嗗姧缁茬晫澹曢幎鑺モ拺闂傚牊绋掗ˉ婊堟煕婵犲倹鎲搁柛娆忔噹椤啴濡堕崨顖滎唶闂佺懓鍟块ˇ鐢哥嵁韫囨拋娲敂閸涱亝瀚奸梻浣告啞缁嬫垿鏁冮敃鍌氱叀濠㈣埖鍔栭悡銉╂煛閸ヮ煁顏堝礉閿曞倹鐓曢柍鍝勫€诲ú瀛橆殽閻愬弶鍠橀柟顔ㄥ洤閱囬柕蹇曞Т濮规煡姊婚崒娆戭槮闁圭⒈鍋勭叅闁挎洖鍊归弲顏堟⒒娴ｇ瓔鍤欑紒缁橆殘娴滅鈻庨幘宕囧姦?")
        elif scenario == "concept_teaching":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欑粣娑㈡⒑閸濄儱校闁圭澧介崚鎺旂磼濡浜濋梺鍛婂姀閺呮繈宕㈡禒瀣拺闂侇偅绋戝畵鍡樼箾娴ｅ啿瀚▍鐘炽亜閺嶎偄浠﹂柣鎾跺枑缁绘繈妫冨☉娆忣槱缂備讲鍋撻悗锝庡亝閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濮风槐鎺楊敊閻ｅ本鍣ч梺瀹狀嚙闁帮綁鐛崱姘兼Щ婵犮垼顫夐敋闁宠鍨块幃娆撴嚑椤掍焦鍠栫紓鍌欑贰閸犳碍鎱ㄩ悽鐢电焿鐎广儱顦介弫鍌炴煕閺囥垺娑ф繛鍫涘姂閺岋綁鎮╅崣澶婎槱缂備椒鐒﹀娆忓祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔告倐濮婃椽宕ㄦ繝鍐ｆ嫻闂佸湱顭堥崯鍧楋綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愬宀婃澓濠电姷鏁搁崑娑㈡偤閵娧冨灊鐎广儱顦伴崑瀣繆閵堝懏鍣圭紒鐘靛仱閺屾洘绻涢悙顒佺彅闂佺粯鍔曢敃銉╁Φ閸曨垰绠崇€广儱鐗滈崬褰掓⒑閸︻厽鐒挎繛鍜冪悼濡叉劙骞樼拠鑼紲濠电偛妫欓崹鍨繆娴犲鐓㈤柛鎰靛枙閹查箖鏌熼绛嬬劸缂佺姵鐩弫鎰板川椤撶姷娼夐梻鍌欑閹碱偊寮甸鍌滅煓闁圭儤姊瑰畷鍙夌節闂堟侗鍎忕痪鎯с偢閺屾洟宕煎┑鍥ㄦ倷闂佽鍠楅崹鍨潖缂佹ɑ濯撮柧蹇撶畭閳ь剙锕弻锟犲磼濞嗘垹鐛㈤悗瑙勬礃閸ㄥ潡鐛鈧獮鍥ㄦ媴閻熸壆妲ｉ梻鍌欑窔濞佳囨偋閸℃あ娑樜旈崨顓㈡暅婵犵數濮村ú锕傛偂閺囥垺鍊甸柨婵嗛娴滄繈鎮樿箛鏇熸毄缂佽鲸甯楀蹇涘Ω閵夛箒鐧侀梻浣筋嚃閸犳帡寮查悩璇茬疇闁绘ɑ妞块弫鍕亜閹邦剟顎楅柟鍐差樀瀹曟垿骞橀懜闈涙瀭闂佸憡娲﹂崜娑⑺囬妸銉㈡斀闁绘劘娉涢惃娲煕閻樻煡鍙勯柟顕€绠栭幃婊堟嚍閵夛附顏熼梻浣虹帛閿氶柛鐔锋健閸┾偓妞ゆ巻鍋撳褍娴峰Σ鎰板箻鐎涙ê顎撻梺鍏肩ゴ閸撴繈宕归幐搴濈箚闂傚牊绋堥弨浠嬫煕閳ュ磭绠查柡鍌楀亾闂傚倷鑳堕崑銊╁磿鏉堚晛顥氭い鎾卞灩閺勩儵鏌ㄥ┑鍡樼闁稿鎸鹃幉鎾礋椤掑偆妲柣搴ゎ潐濞诧箓宕滈悢鐓庢槬闁靛繆鍓濋崕鐔兼煃椤撴粌鍔ら柛鐘崇墵楠炲﹪鏁撻悩鍙傃囨煕閹扳晛濡洪柤鍓蹭簼缁绘繈鎮介棃娴躲儲銇勯敐搴℃灓婵″弶鍔欏鎾閻樼绱遍梻浣侯攰閹活亞绮婚幋鐘差棜鐟滅増甯楅悡娑氣偓骞垮劚妤犳悂鐛Δ鍛厱閻庯綆浜堕崕鎰庨崶褝韬┑鈥崇埣瀹曘劑顢欓崗纰变哗闂傚倷绀侀幖顐も偓姘ュ姂瀹曟洟鎮界粙鑳憰濠电偞鍨崹鍦不濞戙垺鐓冮弶鐐村椤︼附銇勯妷銉剶婵﹥妞介獮鎰償閿濆洨鏆ゆ俊鐐€х€靛矂宕归崼鏇炶摕閻庯綆鍠栭悙濠冦亜閹哄秷鍏岄柛姗嗕簼缁绘繈濮€閿濆懐鍘紓浣割儐閸ㄥ潡濡撮崨鎼晢闁告洦鍓涢崢鍗炩攽閳藉棗鐏犻柛姘儔瀵娊顢楁担鐟板伎婵犵數濮撮幊蹇涱敂閻樼粯鐓欏瀣閳诲牓鏌涢妸锕€鍔ら柣锝囧厴瀹曞爼鏁愰崨顒€顥氬┑鐘垫暩婵數鍠婂澶嬪亗闁哄洨鍠撶弧鈧繝鐢靛Т閸婃悂寮冲▎鎾寸厸闁糕剝鐟ラ弸鏃傜磼鏉堛劌娴柛鈹惧亾濡炪倖甯婇懗鍓佸姬閳ь剟姊洪幖鐐插姌闁告柨顦甸獮蹇撁洪鍛嫼闂佸憡绋戦敃锔剧不閹剧粯鍊垫慨妯煎帶閺嬶箓鏌嶉鍡樻毈婵﹦绮粭鐔煎焵椤掑嫬鐒垫い鎺戝€告禒婊堟煠濞茶鐏￠柡鍛埣椤㈡盯鎮欑€电骞愰梺璇插嚱缂嶅棙绂嶅Δ鍛；闁靛繆鎳囬崑鎾斥枔閸喗鐏侀梺鍛婃煥缁夊墎鍒掔€ｎ喖绠抽柡鍌氭惈娴滈箖鏌ㄥ┑鍡涱€楀ù婊呭仱閺屾稑螣缂佹ê纾冲┑顔硷攻濡炶棄螞閸愩劉妲堥弶鍫涘壉閵堝鈷戠紒瀣健閸欏嫬霉濠婂棙纭炬い鏇秮閹煎綊顢曢敐鍥┬ら梻浣稿暱閹碱偊宕导瀛樻櫖婵犲﹤鐗婇埛鎴犵磽娴ｈ鐒介柟鍐插閺岋綁鎮㈤弶鎴濆闁绘挶鍊濋弻銊╁即閻愭祴鍋撹ぐ鎺戠；闁稿本绋撶粻楣冩煕閳╁厾顏呮叏閸屾鐟邦煥閸曨厾鐓夐梺鍝勭焿缁绘繂鐣峰鈧俊鎼佸Ψ閵忕姳澹曢梺鍛婄缚閸庢煡寮冲鍫熺厱妞ゆ劧绲剧粈鍐煟閹惧啿鏆熼柟鑼焾椤劑宕煎┑鍫Ф婵犵數鍋涘Λ妤€霉濮樿埖鍊垮ù鐘差儐閻撱儵鏌ｉ弬鎸庢儓閺嶏繝姊虹粙娆惧剱閽冮亶鏌曢崶褍顏€殿噮鍣ｅ畷鎺戔槈濞嗘垵娑х紓鍌氬€风拋鎻掝瀶瑜斿畷鎴﹀箻缂佹ǚ鎷绘繛杈剧导鐠€锕傛倿閻愵兙浜滈柟瀛樼箘婢ф盯鏌熸笟鍨濠碘€崇埣瀹曘劑宕掑☉姘垱閻庤娲橀敃銏′繆濮濆矈妲煎┑鐐茬墛閸庢娊鍩為幋锕€鐓￠柛鈩冾殘娴狀厼顪冮妶鍡楃仸闁荤喆鍎卞畵鍕節闂堟稑鈧悂骞夐敓鐘茬厱闁硅揪闄勯悡鏇熺箾閹寸儑鍏柡鈧懡銈囩＜闁逞屽墴閸┾偓妞ゆ帒瀚埛鎴︽煕濠靛嫬鍔氶柡瀣灥椤潡鎮烽悧鍫闁告浜堕弻鐔兼偋閸喓鍑＄紓浣哄Т椤兘骞冭ぐ鎺戠倞妞ゅ繐瀚В銏ゆ⒑閹稿海鈯曠紒顔肩焸閸╃偤骞嬮敂钘夆偓鐑芥煕濞嗗浚妯堟俊顐節濮婃椽宕烽褏鍔稿銈庡幘閸忔﹢濡存笟鈧獮妯兼嫚閹绘帒鏁ゆ俊鐐€栭幐楣冨疮閸ф绠繛宸簼閳锋垹鐥鐐村櫣濞存粌缍婇弻娑氣偓锝庡亞閳洖菐閸パ嶈含闁瑰磭鍋ゆ俊鐑藉Χ閸モ晝鏆伴梻鍌欒兌缁垶宕濋弽銊х彾闁糕剝绋掗崕妤佺箾閸℃ɑ灏伴柣鎾跺枑缁绘盯骞嬪┑鍡氬煘濠电偛鎳庣粔鍫曞焵椤掍緡鍟忛柛鐘虫礈閸掓帒鈻庨幘鎵佸亾娴ｅ壊娼ㄩ柍褜鍓熼獮鍐ㄢ枎閹炬潙浠洪梺鍓茬厛閸嬪懐娆㈤锔解拻闁稿本鑹鹃埀顒傚厴閹虫宕滄担绋跨亰濡炪倖鐗滈崑鎴﹀焵椤掆偓閸熸潙鐣烽妸褉鍋撳☉娅亝绂嶉崡鐐╂斀闁绘顕滃銉╂煕濮橆劶顏堝煡婢舵劕顫呴柣妯垮皺閻涒晜淇婇悙顏勨偓鏍箰閸℃稑绀嬫い鎰╁€栬闂傚倸鍊搁崐椋庢濮橆剦鐒界憸鏃堝箖瑜斿畷鍗烆渻閵忥紕鈽夐摶鏍归敐鍥ㄥ殌鐎殿喖娼″铏圭矙鐠恒劎浼囬梺绋款儑閸嬨倝骞冮敓鐘插嵆闁靛骏绱曢崢顏呯節閻㈤潧孝缂佺粯锚椤﹪顢氶埀顒勫蓟閺囥垹鐐婇柕濞у懐鏆梻渚€鈧偛鑻晶鍙夈亜椤愩埄妲搁悡銈嗕繆椤栨瑨顒熼柣鏂挎娣囧﹪顢涘┑鍥┿€婃繛瀛樼矆缁瑥顫忕紒妯诲闁告繂瀚禒妯侯渻閵堝骸浜濇繛鑼枎閻ｇ兘骞囬鈺傛瀹曨亝鎷呯憴鍕彟闂傚倷绀侀幖顐⒚洪妸鈺佺獥闁规儳澧庢稉宥呂旈敐鍛殭缂佺嫏鍥ㄧ厱妞ゆ劧绲跨粻鎾绘煃闁垮顥堥柡灞剧洴楠炴帒顓奸崨顓犮偖闂備礁鎼張顒勬儎椤栫偛绠栭柕蹇婃濡插綊骞栫€涙绠氭俊鐐倐濮婅櫣绱掑Ο璇茶敿闂佺锕ョ换鍫濐嚕婵犳艾惟闁宠桨绀佸畵鍡涙⒑缂佹ê濮堢紒浣规尦瀹曟垿骞樼拠韫炊闂侀潧顦崕鍝勎涘鍕瘈闁汇垽娼ф牎缂佺偓婢樼粔褰掑箖閿熺姴绀冩い鏃傛櫕閸樺崬鈹戦悩缁樻锭婵☆偅顨婇、鏃堫敂閸喓鍘遍梺鎸庣箓濡瑩濡靛┑瀣厸鐎光偓鐎ｎ剛袦濡ょ姷鍋為…鍥箲閸曨垱鍊绘俊顖炴？闁垶姊婚崒娆戭槮闁圭⒈鍋婇幆澶嬬附缁嬭法鐛ラ梺褰掑亰閸犳帡宕戦幘瀛樺闁告劑鍔嬪Ч妤呮⒑闁偛鑻晶顖滅磼鐎ｎ偄绗╅柟绛嬪亰濮婄粯鎷呯拠鈥冲妼闂佸憡顭囬弲顐﹀箲閵忕姭鏀介悗锝庝簽閸橀亶姊洪柅鐐茶嫰婢у鈧娲樼敮鎺楋綖濠靛鏁嗛柛灞久禒蹇涙⒒閸屾艾鈧绮堟笟鈧獮鏍敃閿旇棄娈ｅ銈嗙墬缁酣鎯岄幘缁樼厱闁规崘灏欓崝宥嗐亜椤愶絾绀嬮柡宀€鍠栭幃婊兾熼悜姗嗗晭闂備胶绮弻銊╁触鐎ｎ喖鍚归柟鐑橆殕閻撳繘鏌涢锝囩畵妞ゆ帇鍨婚幃顕€鏁愰崱娆戠槇缂佺偓婢橀ˇ杈╁閸ф鐓曢悗锝庡亜閻忓鈧娲橀崝娆愪繆閼搁潧绶炲┑鐘插€告禍鍫曟⒒娴ｈ櫣甯涢柟绋挎憸閳ь剙鐏氱敮锟犲箖閻愬顩烽悗锝庡亞閸欏棝姊虹紒妯荤叆闁圭⒈鍋勯悺顓犵磽閸屾瑨鍏屽┑顕€鏀遍幈銊╂偨閸偄搴婂┑鐘绘涧濞层劎寮ч埀顒勬⒑缁嬫寧婀扮紒顔肩焸璺柍褜鍓熷缁樻媴娓氼垳鍔稿銈嗗灥閸熸潙鐣峰┑瀣闁挎洍鍋撻柦鍐枛閺屻劌鈹戦崱鈺傂︾紓浣哄У缁嬫帡濡甸崟顖氱闁糕剝銇炴竟鏇㈡⒑濮瑰洤鐒洪柛顭戝墴瀹曟繈骞嬮敃鈧拑鐔哥箾閹寸偛鐒归柛瀣崌閺佹劖鎯旈垾鑼嚬闁诲氦顫夊ú鏍嫉椤掑嫨鈧啴濡烽埡鍌氣偓鐑芥煛婢跺鐏﹂悹鍥╁仱閹鈻撻崹顔界彯闂侀潻缍囩徊浠嬫偩閻戣棄绠抽柟鎼幘閸欏棝姊鸿ぐ鎺戜喊闁哥姵鐗滈懞閬嶅Ψ閳哄倵鎷婚梺绋挎湰閼归箖鍩€椤掑嫷妫戞繛鍡愬灩椤繄鎹勯搹鐟板Е婵＄偑鍊栫敮鎺楀磹閸涘﹦顩锋繝濠傜墛閻撶姵绻涢懠棰濆殭闁诲骏绻濋弻锟犲川椤撶姴鐓熷銈冨灪缁嬫垿鍩為崘顔肩畾鐟滃本绔熼弴銏♀拺闁告捁灏欓崢娑㈡煕鐎ｎ亝鍣芥繛鍡愬灲瀵濡烽敃鈧埀顒€鐏氶幈銊ヮ潨閸℃ぞ绨婚悗瑙勬尭濡繈寮婚敐鍛闁告鍋為悵婵嬫倵鐟欏嫭绀€闁绘牕銈搁妴浣肝旀担鍝ョ獮闁诲函缍嗛崑鍛存偟濠靛鈷掗柛灞剧懆閸忓瞼绱掗鍛仴闁圭瓔鍋婇幃宄邦煥閸曨剛鍑￠梺鍝ュ枑婢瑰棝宕氶幒鏃傜＜婵☆垵鍋愰惁鍫濃攽椤旀枻渚涢柛妯绘倐楠炲繑绻濆顓涙嫼缂備礁顑嗙€笛冿耿娴煎瓨鐓熼柣鏃€绻傚▔姘跺炊椤掍焦娅囬梺绋挎湰缁嬫捇宕㈤悽鐢电＜闁绘劦鍓氱欢鑼偓瑙勬处閸撴氨绮嬪鍡楊嚤閻庢稒锚閻у嫬鈹戦悩缁樻锭妞ゆ垵妫濋幃鈥斥枎閹邦喚顔曢梺鍓插亝缁诲嫭绂掗姀銈嗙厸閻庯綆鍋呭畷宀勬煛鐏炲墽銆掗柍褜鍓ㄧ紞鍡涘磻閸涱垯鐒婇柣銏㈡暩绾惧吋銇勯弴鐐村櫣妤犵偞鐗犻弻宥夋寠婢舵ɑ笑闁句紮缍侀弻锝夊箣閻戝棛鍔锋繛瀵稿Т閻倸顫忕紒妯诲缂佸瀵ч崐顖氣攽閻橆喖鐏柨姘亜椤撶偞鍠橀柡浣规崌閹晠鎳犻懜鍨暫闂傚倷鐒︾€笛呮崲閸岀偛绠熸慨妞诲亾鐎殿噮鍣ｅ畷鐓庘攽閸繂袝濠碉紕鍋戦崐鏍暜閹烘柡鍋撳鐓庡籍鐎规洘鍨归埀顒婄秵閸犳鎮￠弴鐔虹闁瑰瓨绻傞懜褰掓煟韫囥儳纾块柍褜鍓濋～澶娒哄鈧幃锟犳晸閻樿尪鎽曞┑鐐村灟閸ㄥ綊鎮炲ú顏呯厱闁规澘鍚€缁ㄦ潙鈹戦鍏煎枠婵﹨娅ｇ槐鎺懳熺拠鏌ョ€烘繝鐢靛仜瀵爼鈥﹂崶顒€绠查柕蹇曞Л濡插牓鏌曡箛鏇炐㈤柤鏉跨仢閳规垶骞婇柛濠冩崌閹虫宕奸弴妯峰亾閸涙潙绾ч幖瀛樻尰閺傗偓闂備焦鏋奸弲娑㈠疮椤愩倕绶ら柤濮愬€楃壕鐣屸偓骞垮劚閹锋垿鐓鍌楀亾濞堝灝鏋︽い鏇嗗洤鐓″璺号堥弸搴ㄦ煙鐎电啸婵℃彃娲缁樻媴閸涘﹤鏆堥梺鍛婃⒐閸ㄥ灝鐣峰┑鍡欐殕闁告洖澧庣粙蹇涙倵楠炲灝鍔氶柟宄邦儏閵嗘帗绻濆顓犲帾闂佸壊鍋呯换鍌炲汲濞嗗繆鏀介柍鈺佸暞閸婃劙鏌＄仦鍓р姇闁诡垱妫冮弫鎰板幢濡崵妲楀┑掳鍊楁慨鐑藉磻濞戙垹鐤い鎰剁畱閻撴繈骞栧ǎ顒€濡肩紒鐘哄吹閳ь剝顫夊ú鏍归崒鐐茶埞濞寸姴顑嗛埛鎺懨归敐鍛暈閻犳劧绻濋弻娑欐償濞戞ǚ鍋撳Δ鍛闁靛繈鍊曠壕鍏肩箾閹寸儐娈樼紒鐘崇娣囧﹪鎮欏顔煎壈濠电偞鎸抽ˉ鎾寸珶閺囩喓顩烽悗锝庡亞閸橀亶鏌ｈ箛鏇炰粶濠⒀傜矙楠炲﹪宕卞☉娆戝幈闂婎偄娲﹂幐楣冩倶鏉堚晝纾奸弶鍫涘妼濞搭喗銇勯姀鈥冲摵鐎规洏鍔戦、姗€鎮╅崡鐐差嚙闂傚倸鍊烽懗鍫曞箠閹惧墎涓嶇€广儱顦崹鍌炴煢濡警妲洪柡鍡畵閺岋綁骞樺畷鍥у摵闂佽　鍋撳ù鐘差儐閻撴洘銇勯幇鈺佲偓鏇㈠几閹寸偑浜滈柡鍐ｅ亾婵炲弶顭囬幑銏犫攽閸″繑鐏侀梺鍓茬厛閸犳鎮樺澶嬧拺闂傚牊绋掓径鍕煟閳哄﹤鐏犻柣锝囧厴楠炲鏁冮埀顒傜不閼姐倗纾藉ù锝堫嚃閻掍粙鏌涘鈧褔鈥旈崘顔嘉ч柛鈩兦氶幏濠氭⒑閸濆嫭濯奸柛瀣躬閻涱喗绻濋崶褏鍊為梺闈涱煭缁茶偐鑺辨繝姘拺闂傚牊绋撶粻姘繆閹绘帗鍣归柍缁樻崌瀵挳濮€閿涘嫬骞嶉柣搴ｆ嚀鐎氼喗鏅跺Δ鍛惞闁搞儺鍓氶悡娆愩亜閺冣偓閸庢娊宕㈢€涙﹩娈介柣鎰皺鏁堥悗瑙勬礃閿曘垽鎮￠锔绘晣闁绘垵妫欓ˉ锟犳⒒閸屾艾鈧兘鎳楅崜浣稿灊妞ゆ牜鍋涢崹鍌炴煕韫囨挸鎮戦柛娆忕箻閺屾洟宕煎┑鎰﹂梺缁樻尰濞茬喖寮婚悢鍏煎€绘慨妤€妫欓悾鐑芥⒑缂佹ɑ灏版繛鑼枛楠炲啫顫滈埀顒勫箖濞嗘挸绾ч柟瀛樼箓琚橀梻鍌欑劍閹爼宕愰妶澶婄闁绘梻鍘ч拑鐔兼煥濠靛棭妲哥紒鐘层偢閺屾盯骞囬埡浣割瀳闂佸啿鍢查澶婎潖濞差亜浼犻柛鏇ㄥ墯閹疯京绱撴担鍓插剱闁圭懓娲畷娲焵椤掍降浜滈柟鐑樺煀閸旂喓绱掓径鎰锭闂囧绻濇繝鍌氼伀闁活厽甯楅妵鍕閳╁喚妫冮梺绯曟櫔缁绘繂鐣烽妸鈺婃晩闂傚倸顕弳妤呮⒒閸屾瑧绐旀繛浣冲洦鍋嬮柛鈩冦亗濞戞瑦鍎熼柕蹇嬪焺濞茬鈹戦悩璇у伐闁绘锕幃鈥斥枎閹惧鍘甸柣鐔哥懃鐎氼剚鎱ㄩ崼銏㈡／妞ゆ挶鍨婚悾娲煛鐏炲墽娲存鐐搭焽閹峰鎼归銏＄亾闂傚倷绀侀幖顐︽儗婢跺瞼绀婂〒姘ｅ亾闁绘侗鍣ｉ獮鎺懳旈埀顒傜尵瀹ュ鐓冪憸婊堝礈濞嗘挸鐓濈€广儱顦崡鎶芥煏韫囥儳纾块柛妯兼暬濮婃椽宕ㄦ繝鍕櫑濡炪倧缂氶崡鍐茬暦閹版澘绠涙い鏃傛嚀娴滅偓绻涢崼婵堜虎婵炲懏锕㈤弻娑㈡晲韫囨洖鍩岄梺浼欑秮閺€杈╃紦閻ｅ瞼鐭欐繛鍡欏亾缂嶅倿姊绘担铏瑰笡妞ゎ厼娲畷鎴︽晲婢跺﹦锛涙繝鐢靛Т濞诧箓鍩涢幒妤佺厱閻忕偞鍎抽崵顒勬煟閹垮啫澧撮柡灞剧〒閳ь剨缍嗘禍婊堫敂閳哄懏鍋傞柕鍫濐槹閻撱儵鏌￠崒姘变虎闁抽攱妫冮弻锝夘敇閻旂儤鍣伴梺鍝勭灱閸犳捇鍩€椤掑倹鏆╂い顓炵墕閺嗏晛鈹戦悙鏉戠仸闁圭鎽滅划鏃堟偨缁嬭锕傛煕閺囥劌鐏犻柛鎰ㄥ亾婵＄偑鍊栭崝锕€顭块埀顒佺箾瀹€濠侀偗婵﹨娅ｇ划娆撳礌閳ュ厖绱ｉ梻浣虹帛閻楁洟濡剁粙娆惧殨濠电姵纰嶉弲鎻掝熆鐠虹尨鍔熼柣銈傚亾闂傚倸鍊风欢锟犲矗韫囨稒鈷旈柛鏇ㄥ亽閻斿棝鏌熼崜褏甯涢柍閿嬪灴閺屾稑鈹戦崟顐㈠婵炲濮嶉崶銊у幈闁圭厧鐡ㄧ粙鎴﹀焵椤掍胶绠為柣娑卞櫍瀹曞ジ濡烽妷搴樻櫇閹插憡鎯旈妸銉х崶闂佺硶鍓濈粙鎺楁偂閺囥垺鐓涢柛銉㈡櫅娴犙兠归悩宕囨创闁哄矉缍佹俊鍫曞礋椤撗勑滈梻浣哥枃椤宕归崸妞尖偓浣糕枎閹寸偛鍘归梺缁樺灩閺咁偊宕ｅ鍡欑瘈闁汇垽娼ф禒婊堟煙闁垮鐏╃紒杈╁仦缁楃喖鍩€椤掑嫭鍋樻い鏃囨缁剁偤鏌熼柇锕€澧版い鏃€甯掗—鍐Χ閸℃﹩姊块梺绋款儐閸旀瑨妫熼梺鍝勵槹椤戞瑥銆掓繝姘厪闁割偅绻冮ˉ婊冣攽椤旂厧鈧潡寮诲☉銏犖╃憸婊堝绩閻楀牄浜滈柨婵嗗閻瑦鎱ㄦ繝鍌ょ吋鐎规洘甯掗～婵嬵敄閽樺澹曟俊鐐差儏濞寸兘鎯岄崱妞尖偓鎺戭潩閿濆懍澹曟俊銈囧Х閸嬬偤銆冮崨绮光偓锕傚Ω閳轰線鍞跺┑鐘绘涧閻楀繐鐣烽崼鏇熲拺缁绢厼鎳庢禍褰掓偠濞戞牕鍔氶崡閬嶆煕濞戞鎽犻柛濠傜仢闇夐柣妯烘▕閸庢劙鏌嶉柨瀣棃闁哄本鐩俊鐑筋敊閻撳寒娼介梻浣侯焾鐎涒晠銆冮崨鎵簷闂備焦瀵х换鍌炲箠鎼淬劌姹查柣鎰劋閻撳啴姊洪崹顕呭剰闁诲繑鎸抽弻锛勪沪閸撗€妲堥梺瀹犳椤︻垶锝炲鍫濋唶闁绘洑鐒﹀В澶岀磽閸屾艾鈧绮堟笟鈧幃銉╁礂閼测晩娲搁梺鍓插亝濞叉牠鎷戦悢鍝ョ闁瑰瓨鐟ラ悘鈺冪磼椤愩垻效闁哄苯绉烽¨渚€鏌涢幘璺烘瀻闁伙絿鍏樺鎾偄濞差亝顎嶇紓鍌欑椤戝牓顢氶幎鑺ユ櫇闁稿本绋撻崢鐢告⒑缂佹﹩娈旈柣妤€锕﹀▎銏ゆ嚑椤掑倻锛滈梺缁樏崯鍧楀煝閺囥垺鐓涚€光偓閳ь剟宕伴弽顓犲祦闁糕剝鍑瑰Σ濠氭煟閵忊晛鐏ｅ┑鐐╁亾闂佸搫澶囬崜婵嗩嚗閸曨倠鐔煎传閸曨厾娼夊┑鐘愁問閸犳牠鏁冮敂鎯у灊妞ゆ牜鍋涚粻顖炴煕濞戞瑦缍戠€瑰憡绻傞埞鎴︽偐閹绘巻鍋撻悷鎵虫灁婵☆垵銆€閺€浠嬫煟閹邦剛鎽犻悘蹇斿閻ヮ亪寮剁捄銊愌囨煏閸℃鏆炵紒缁樼箞瀹曟帒顭ㄩ崟顒夊晭闂佽崵鍠愮划搴㈡櫠濡ゅ啯鏆滄俊銈呮噺閸婂潡鏌ゅù瀣澒闁稿鎹囬悰顕€宕归鐓庮潛闂備胶顢婂▍鏇㈠礉濞嗘挸鏋佺€广儱鎳夊Σ鍫ユ煏韫囧ň鍋撻崗鍛暰濠电姷鏁告慨鎾晝閵堝洠鍋撳鐓庡籍闁诡噯绻濇俊鐑芥晜鏉炴壆鐩庢俊鐐€栭崝鎴﹀垂閼姐倗涓嶅┑鐘崇閻撴瑩鏌ｉ幘铏崳缂佸娅ｉ埀顒冾潐濞叉粓宕楀鈧妴浣割潨閳ь剟骞冮鍫濆窛妞ゆ牗姘ㄩ崫搴♀攽閻樺灚鏆╁┑顔惧厴閵嗗倿鎸婃竟鈺嬬秮瀹曘劑寮堕幋婵堚偓顓㈡⒑鐟欏嫬鍔舵俊顐㈠瀹曟帡濡歌閸犳劙鏌￠崘銊у闁哄懏鐓￠弻锝夊箛闁附婢撳┑鈩冨絻婢х晫妲愰幘瀛樺濞寸姴顑呴幗鐢告⒑鐟欏嫮鎽冪€规洜鏁搁崚鎺楊敇閵忊€充簻闂佺粯鎸稿ù鐑藉磹閻愮儤鍋℃繝濠傚暣閸欏嫰鏌熼鐭亪顢橀崗鐓庣窞閻庯急鍕伖闂傚倷绶氬鑽も偓闈涚焸瀹曘垺绂掔€ｎ亜鎯為梺閫炲苯澧柍瑙勫灴閹瑩鎳犻浣稿瑎闂備胶顭堥敃銉ф崲閸儱违濞达絽澹婂鈺呮煠缁嬭法浠涙繛鍛矋缁绘繈濮€閿濆棛銆愬銈嗗灥閹冲酣鍩㈤幘璇参ㄩ柍鍝勫€甸幏娲⒒閸屾氨澧涚紒瀣尰閺呭爼寮撮姀鈥斥偓鍨叏濡厧甯剁€殿噮鍠氶埀顒冾潐濞叉粓宕伴弽褏鏆︽慨妞诲亾妞ゃ垺鐟ч幉鎾晲閸℃浼栧┑鐘垫暩閸嬬偛顭囧▎鎾宠Е閻庯綆鍠楅崑锛勬喐閺傝法鏆︽慨姗嗗幖椤曢亶鎮楀☉娆樼劷闁告ɑ鎮傚娲礈閹绘帊鑸梺绋款儏鐎氼參寮查崼鏇ㄦ晪闁逞屽墴瀵顓奸崶鈺冿紲濠碘槅鍨甸褏澹曢幎鑺ュ€垫繛鍫濈仢閺嬬喖鏌熷灞剧彧闁逛究鍔戦崺鈧い鎺戝閻撳啴姊哄▎鎯х仩濞存粓绠栧楦裤亹閹烘挻鏆犲┑锛勫仩濡嫰锝炶箛鏇犵＜婵☆垵鍋愰幊婵嬫⒑閹肩偛鍔€闁稿本绮嶉弲濂告⒒閸屾瑨鍏屾い顓炵墦椤㈡牠宕卞☉娆忓壆濡炪倖鐗滈崑娑氱不閻樼粯鐓熼柡鍐ㄥ€甸幏锟犳煛娴ｅ摜校缂佺粯鐩獮瀣倷閸偄娅楅梻浣虹帛缁诲倿宕查弻銉⑩偓鏃堝礃椤斿槈褔鏌涢埄鍐剧劷闁挎稒娲熷铏圭矙濞嗘儳鍓遍梺鍦嚀濞差厼顕ｆ繝姘櫖闁告洦浜濋崟鍐⒑娴兼瑧鍒伴柣顐ｎ殜婵″爼宕堕埡鍐跨床闂佸搫顦悧鍕礉瀹€鈧划顓㈠箳濡や焦鍤夐梺鎸庣箓椤︿即宕戦敐澶嬬厱闁靛鍠曠花濠氭煟閵婏附銇濋柡灞诲妼閳藉鈻庨幇顒勭€哄┑鐑囩到濞层倝鏁冮鍛箚闁割偅娲栭悙濠冦亜椤掑鏋旈柛搴ｆ暬瀵鈽夊锝呬壕闁挎繂楠告禍鐐寸箾閹绘帞鎽犻柕鍥у婵偓闁挎稑瀚～褔鎮楅崹顐ｇ凡閻庢矮鍗抽悰顕€宕堕澶嬫櫌闂佺鏈划宥呅掗崶褉鏀介柣妯虹仛閺嗏晠鏌涚€ｎ偆鈽夐摶鐐寸箾閸℃ɑ灏柛銊ュ€块弻锝夊籍閸屾艾浠樼紒鐐劤椤兘寮婚悢鐓庣鐟滃繒鏁☉娆嶄簻闁靛鍎虫晶娑氱磼缂佹娲存鐐差儔閹瑩宕归銏＄彫闂傚倷绀侀幗婊勬叏閻㈢绀夋繛鍡樻尭閽冪喖鏌曢崼婵愭Ц闁活厽顨呴…璺ㄦ崉妤﹀灝顏梺鍐插槻閼活垶鍩為幋锔绘晩缁绢厼鍢叉导鎰渻閵堝骸骞栭柛銏＄叀閹箖鎮滈挊澶岊唺闂佺懓鐡ㄥ褰掓倵婵犳碍鈷戦柣鐔煎亰閸ょ喎鈹戦鐓庢Щ闁伙絿鍏樺畷锝嗗緞瀹€鈧惁鍫ユ⒑濮瑰洤鐏叉繛浣冲嫮顩烽柍杞扮贰閻斿棝鏌ｉ悢绋款棆濠⒀勬礋閺岋綁鏁愰崶褍骞嬮梺璇″枤閺咁偆鍒掑▎鎴炲磯闁靛鍎辫婵犵绱曢崑鎴﹀磹閺嶎偅鏆滈柟鐑樻煛閸嬫挸顫濋悡搴＄闂佸疇妫勯ˇ鎶剿囪ぐ鎺撶厸鐎光偓鐎ｎ剛袦濡炪們鍨洪敃銏ゅ箖濞嗗緷鍦偓锝庝簷婢规洟姊鸿ぐ鎺擄紵闁绘帪绠撳畷鎴﹀煛閸涱喚鍘介梺纭呮彧缁查箖藟婢跺浜滄い鎰╁灪閸ゅ洭鏌＄仦鐐鐎规洜鍘ч埞鎴﹀炊閼告妫ч梻鍌欐祰閻偊宕橀…鎴滅棯缂傚倷鑳剁划顖滄崲閸喐鍙忛柍褜鍓熼弻銊モ攽閸℃﹩妫ら梺闈涙閸旀洟鍩為幋锕€鐓￠柛鈩冦仦缁ㄥジ姊洪懡銈呮毐闁哄懐濞€閻涱噣宕橀妸搴㈡閸┾偓妞ゆ帒鍊稿鍙変繆閻愵亜鈧洜鎹㈤幇鏉跨疇濠㈣埖鍔曠粻顖涚箾瀹割喕绨奸柍閿嬪灴閺屾稑鈽夊鍫濆缂備胶濮甸幑鍥箖濡も偓椤繈鎮℃惔锛勭潉闁诲氦顫夊ú妯兼暜閳╁啩绻嗛柟闂寸閻撴盯鏌涚仦鍓х煀妤犵偛鐗撳缁樼瑹閳ь剙顭囪閳ワ箓顢橀姀鈾€鎸冮梺鍛婃处閸ㄧ増顢婃繝鐢靛█濞佳囶敄閸℃稒鍋傛繛鍡樺姂娴滄粓鏌￠崘锝呬壕闂佽崵鍣︾紞浣哥暦閹邦儵鏃堝川椤旈棿鐥梻渚€鈧偛鑻晶顕€鏌嶇憴鍕伌闁诡喗鐟╁鍫曞箣閻樿鲸顢橀梻鍌欐祰瀹曠敻宕▎鎾崇倞鐟滃秹宕戝澶嬧拻濞撴艾娲ゆ晶顔剧磼婢跺本鏆柛鈺傜洴楠炲鏁傞悾灞藉箰闂備胶顭堥張顒勬晪闂佸憡姊圭划宥囨崲濞戙垹宸濇い鎾跺枎濞堟姊洪崫鍕拱闁烩晩鍨堕獮鍐Χ閸℃ê顎撻梺鍛婄缚閸庝即宕犻弽顐ょ＝闁稿本鐟х拹浼存煕閻樺磭澧甸柟顔ㄥ洤绠荤€规洖娲﹀▓鐐節闂堟稑鈧悂骞夐敓鐘茬；闁告洦鍘剧壕浠嬫煕椤愮姴鐏╅崯鎼佹⒑閻戔晜娅呴梺甯到椤繒绱掑Ο璇差€撻梺鑽ゅ枛閸嬪﹪宕电€ｎ亖鏀介柍钘夋娴滄绱掗懜浣冨闁伙絿鍏橀獮瀣晝閳ь剛绮诲☉銏＄厽婵°倐鍋撻柣妤€妫欑粋鎺撶附閸涘ň鎷哄┑顔炬嚀濞层倝鎮橀埡鍛厵閻犲泧鍛槇闂佽鍠掗埀顒佹灱濡插牓鏌曡箛濞惧亾閺傘儱浜鹃柛顐ｆ礃閻撶喖鏌熼幍顔碱暭婵炴嚪鍏犵懓顭ㄩ崘銊㈡寖缂備浇椴哥敮锟犲春閳ь剚銇勯幒鎴濃偓鐢稿磻閹剧粯鏅查幖绮光偓鍐茬闂備胶顭堥鍡涘箰妤ｅ啫绠熼柟缁㈠枛缁€瀣亜閹烘垵浜炴俊宸墴濮婄粯鎷呴搹鐟扮闂佺粯顨嗗ú鐔风暦閵壯€鍋撻敐搴′簽闁崇懓绉撮埞鎴︽偐閸欏鎮欑紓浣哄Х閹虫捇婀侀梺鎸庣箓閻楀棝鍩€椤戣法鐭欏┑鈩冪摃椤︽娊鏌涢悩鍐插闁逞屽墮閸樻粓宕戦幘缁樼厱闁哄洢鍔屾禍鐐烘煟閿濆棙銇濇慨濠冩そ楠炴劖鎯旈敐鍥╂殼婵＄偑鍊х紓姘跺础閹惰棄鏄ユ繛鎴欏灩缁犳娊鏌熼悙钘夊缂傚秴锕顐﹀箛閺夎法鍊為悷婊冪У娣囧﹤煤椤忓應鎷洪梺纭呭亹閸嬫盯鍩€椤掍礁濮嶇€规洘鍨块獮妯肩磼濡攱瀚藉┑鐐舵彧缂嶁偓妞ゎ偄顦靛畷鎴︽偐缂佹鍘遍梺闈涱焾閸斿本绂嶉悷鎳婄懓顭ㄩ崪浣哄姼闂佸疇顕ч柊锝夌嵁鐎ｎ喗鍊婚柛鈩冾焽缁嬫劙姊婚崒娆掑厡缂侇噮鍨跺畷婵嬪即閵忊晜鏅銈嗘尵婵瓨鎱ㄩ鍕厓鐟滄粓宕滈悢濂夋綎婵炲樊浜滃婵嗏攽閻樻彃鈧悂藟閸儲鈷戦柛娑橈梗缁堕亶鏌涢妸锕€鈻曠€殿喛娅曠€佃偐鈧稒菤閹峰姊虹粙鎸庢拱闁煎綊绠栭崺鈧い鎺戝濡垹绱掗鑲╁缂佹鍠栭崺鈧い鎺戝缁犳牗淇婇婵勨偓鈧柡鈧禒瀣€甸柨婵嗘噽娴犳盯鏌￠崨顖氫槐婵﹨娅ｉ崠鏍即閻愭祴鎷ゆ俊鐐€戦崝宀€鎹㈠Ο铏规殾闁汇垻顭堥崡鎶芥煏韫囥儳纾块柛妯兼暬濮婅櫣鎷犻垾宕団偓濠氭倶閻愯泛袚妞ゆ柨绉剁槐鎾诲磼濞嗘帒鍘℃繝鐢靛亹閸嬫挾绱撴担鍝勑ｉ柣妤佹礋椤㈡岸鏁愭径濠囧敹闂佸搫娲ㄩ崑銈夊船鐠鸿　鏀介柣妯肩帛濞懷勪繆椤愩垻鐒告鐐村姍瀹曟﹢顢欑憴锝嗗闂備礁鎲＄粙鎴︽晝閵堝洨绠旀慨姗嗗幘缁♀偓闂侀潧绻嗗Σ鍕嚀閸ф鐓冮柕澶樺灣閻ｇ數鈧娲滈…鍫ｇ亙婵炶揪缍侀弲鏌ユ偨婵犳碍鈷戞慨鐟版搐閻掓椽鏌涢妸銉ｅ仮鐎规洘婢橀埥澶愬閻樼洅鏇烆渻閵堝棗濮ч梻鍕瀹曟劙鎮介崨濠備画濠电偛妫楃换鎰邦敂椤忓棛纾奸柍褜鍓熷畷濂稿Ψ閿旀儳骞愬┑鐐舵彧缁插潡鎮洪弮鍫濆惞婵炲棙鍔戞禍婊堟煛閸ユ湹绨界紒澶樺枟椤ㄣ儵鎮欐潏鎹愨偓鎸庛亜閵忥紕鎳呴柛鐘诧攻濞煎繘濡歌琚╅梻鍌氬€搁崐椋庢濮橆剦鐒界憸蹇涘箲閵忋倕绠抽柟鐐綑瀵潡鏌ｆ惔锝嗘毄妞ゎ厼鐗忓▎銏ゅΧ閸涱亝鏂€闂佺鏈喊宥夊疮閻愮儤鐓冮梺鍨儏缁楁帡妫佹径鎰叆婵犻潧妫涙晶杈ㄧ箾閸忕厧濮嶉柡灞剧〒閳ь剨缍嗛崜娆撳煝閸儲鐓涢悘鐐插⒔閳洟鏌熼娑欘棃濠殿喒鍋撻梺闈涚箞閸ㄥ宕㈤幒鎴旀斀闁绘劕妯婇崵鐔封攽椤栨凹鍤熺紒顔碱煼楠炴鎷犻懠顒夊敹濠电姷鏁告慨鎾疮椤愩倖顐介柣鎰ゴ閺€浠嬫煟濡绲绘い鎺嬪灪閵囧嫰濡烽妷褍鈪靛┑顔硷工椤嘲鐣烽幒鎴僵妞ゆ垼妫勬禍楣冩煙闂傚顦︾痪鎯х秺閺岋綁骞嬮敐鍛呮捇鏌涢妶鍛伃闁哄本鐩、鏇㈡晲閸℃瑱绱╅梻渚€鈧偛鑻晶鍓х磼閻樿櫕灏柣锝夋敱缁虹晫绮欑拠淇卞妽閵囧嫰寮崶顬挻绻涢崨顓犲ⅵ婵﹦绮幏鍛存惞楠炲簱鍋撴繝鍥ㄧ厱闁规儳顕粻妯肩磼椤旂晫鎳囨鐐差儔閹晠宕楅崫銉ф喒婵犵數鍋涢顓㈠储瑜旈幃娲Ω閳哄倸浜楅梺缁樕戠粊鎾绩閼恒儯浜滈柡鍐ㄦ处椤ュ鈹戦鍏煎枠闁哄苯绉烽¨渚€鏌涢幘鏉戝摵闁靛棗鍟村畷濂稿閻樿尙浜板┑鐘垫暩婵敻鎳濋崜褏灏电€广儱顦伴悡鏇熴亜閹扳晛鈧洟寮搁弮鍫熺厱婵☆垰婀遍惌娆愭叏婵犲啯銇濈€规洦鍋婂畷鐔碱敃閿濆棭鍞查梻鍌欒兌椤牓鏁冮妶澶婄婵犲﹤鐗嗛弸浣广亜閺囨浜鹃悗瑙勬礀閵堢顕ｉ幘顔藉亜闁告繂瀚粻娲⒒閸屾瑧顦︽繝鈧柆宥呯？闁靛牆顦崹鍌炴偡濞嗗繐顏い鈺呮敱缁绘盯骞嬪▎蹇曚痪闂佺粯鎸哥换姗€寮诲☉銏犖ㄩ柟瀛樼箓閺嬨倕霉閻撳骸鏆欓摶鏍煟濮椻偓濞佳勭閿曞倹鍋ㄦい鏍ュ€楃弧鈧梺缁樹緱閸犳岸鍩€椤掑﹦绉靛ù婊勭墵瀵劍绂掔€ｎ偆鍘甸梻渚囧弿缂傛氨鑺遍懞銉ょ箚妞ゆ劦鍋勯悘锔芥叏婵犲偆鐓肩€规洘甯掗埢搴ㄥ箳閹存繂鑵愬┑锛勫亼閸娿倝宕㈡總鍛婂亱闁圭偓鐪归埀顑跨窔瀵粙顢橀悙鑼垛偓鍨攽椤旀枻渚涢柛妯圭矙瀹曡櫕顦版惔锝囷紳闂佺鏈懝楣冨焵椤掑倸鍘撮柟铏殜瀹曟粍鎷呯粙璺ㄤ喊婵＄偑鍊栭悧婊堝磻閻愬搫纾块幖鎼娇娴滄粓鏌″鍐ㄥ闁汇劍鍨块弻锟犲幢椤撶姷鏆ら梺鍝勬湰缁嬫垼鐏冮梺鍛婂姂閸斿宕戦幘缁樻櫜濠㈣泛顑呮禍婊堟⒑缁嬭法绠伴柛姘儔瀹曟洟顢旈崼鐔叉嫽婵炴挻鑹惧ú銈嗙濠靛牏纾奸悗锝庡亜濞搭噣鏌曢崱鏇狀槮妞ゎ偅绮撻崺鈧い鎺嗗亾妞ゎ偄绻掔槐鎺懳熺拠宸偓鎾剁磽娴ｅ湱鈽夋い鎴濇噹閳绘捇顢橀姀锛勫幗闁瑰吋鐣崹濠氬煝閹剧粯鐓涢柛娑卞枤缁犵偟鈧娲滄晶妤冩崲濠靛纾奸柕鍫濇噺閸婎垰鈹戦悩顔肩伇婵炲鐩、鏍川椤撴稒鐏侀梺缁樺姉缁绘繄鎹㈤崱娑欑厪闁割偅绻勭粻鎶芥煕閹哄秴宓嗛柡灞剧洴閹倖鎷呴崫銉ゅ寲缂傚倷绶￠崰鏍€﹂悜鐣屽祦闁圭儤鍤﹂弮鈧幏鍛村矗婢跺浼滃┑鐘垫暩閸嬬娀骞撻鍡楃筏闁秆勵殔缁犵娀鏌熼悙顒併仧闁轰礁顑嗙换婵囩節閸屾稑娅х紒鐐劤閵堟悂骞冭ぐ鎺戠倞闁靛鍎崇粊鐑芥⒑闁偛鑻晶顖炴煙椤旂厧鈧悂鏁冮姀锛勭懝闁逞屽墮椤繘鎼归崷顓犵厯闁荤姵浜介崝搴㈠閸ヮ剚鈷戠紒瀣儥閸庢垿鏌涚€ｃ劌鈧洟鎮鹃悜钘夌疀闁哄娼￠弫婊冣攽鎺抽崐鎾绘嚄閸洖鍌ㄩ梺顒€绉甸埛鎴︽煕閿旇骞栧ù婊呭亾閵囧嫰濡搁妷锕€娅ч梺閫炲苯澧柛鎴濈秺瀹曟粌顫濇潏鈺冪効闂佸湱鍎ゅú婊堟偪閳ь剙鈹戦悙鏉戠仸闁荤喆鍨介獮蹇涙惞閸︻厾锛濋梺绋挎湰閻熝囧礉瀹ュ瀚呴梺顒€绉甸悡鐔兼煙閹冭埞闁告棑绠撻弻鈥崇暆閳ь剟宕伴弽顓炵疇闁绘劕鎼敮閻熸粌绻橀幃锟犲磼濠婂懐锛濇繛鎾磋壘濞层倝寮搁妶鍥╃＜妞ゆ洖鎳庨悘锕€鈹戦垾宕囧煟闁轰焦鍔栧鍕節閸曞灚袨闂傚倷绶氬褑鍣归梺鎼炲劗閺呮稓绮堥崼銉︹拻闁稿本鑹鹃埀顒勵棑缁牊鎷呴崷顓犲骄婵犵數濮村ú銈囧婵犳碍鐓曟繛鎴濆船閻忥紕鈧娲橀悡锟犲蓟濞戞鏆嗛柍褜鍓熷畷鎴濃槈閵忊€充簵闂佸搫娲㈤崹娲偂濞戙垺鐓曢柟鎵虫櫅婵″ジ鏌嶈閸撴繂鐣烽崹顐ょ彾闁哄洨鍠撻梽鍕煕濞戞﹫宸ラ柍褜鍓涢弫濠氬蓟閵娿儮鏀介柛鈩冧緱閳ь剚顨嗛〃銉╂倷鐎电鈷岄梺鍝勬湰缁嬫垿锝炲┑瀣垫晢濞达絿鏅、鍛磽閸屾瑦绁板鏉戞憸閺侇喖螖閳ь剟鈥﹂崶顏嗙杸婵炴垶顭傞埡鍛厪濠㈣埖绋撻悾鎶芥煟瑜岄悞锔界┍婵犲洦鍊锋い蹇撳閸嬫捇骞嬮敃鈧崹鍌涚箾瀹割喕绨奸柛瀣剁節閺屻劑寮崹顔规寖缂備焦鍞荤粻鎴︽箒闂佺粯锚濡﹪宕曡箛鏇犵＜闁逞屽墴瀹曞ジ鎮㈤搹璇″晭闂備礁鎼ˇ浼村春閸儱纾块煫鍥ㄦ媼閻熼偊鐓ラ柛娑卞幒婢规洘绻涢敐鍛悙闁挎洦浜濇穱濠囧醇閺囩偛绐涘銈嗘煥閸氬顢旈敓鐘斥拻濞达綀娅ｇ敮娑㈡煙缁嬭法鍩ｇ€规洘娲熼幃鐣岀矙閼愁垱鎲伴梻浣芥硶閸犳挻鎱ㄩ幘顔藉€峰┑鐘插暔娴滄粍銇勯幘璺哄壉闁稿孩绋戦湁婵犲﹤绨奸柇顖涱殽閻愭彃鏆欐い顐ｇ矒閸┾偓妞ゆ巻鍋撴い鏇稻缁绘繂顫濋鈹垮姂閺屻劑寮埀顒勫磿閹剁晫宓侀柛顐犲劜閳锋帒銆掑锝呬壕濠电偘鍖犻崱妤婃澓闂傚倷绀侀幖顐﹀箠韫囨洘宕查柛顐犲劚缁犳牕螖閿濆懎鏆為柛濠勭帛閹便劌螖閳ь剙螞濞嗘搩鏁婇柡鍐ㄧ墛閳锋垹绱撴担濮戭亝鎱ㄩ崶鈹惧亾濞堝灝鏋﹂柛鈺傜墪椤曘儵宕熼姘鳖槹濡炪倖鐗楃粙鎾诲储閻㈠憡鍊甸柣鐔告緲椤忣偄顭胯椤ㄥ﹤鐣烽搹顐ゎ浄閻庯綆鍋嗛崢鐢告⒑閸涘﹦鎳冩い锔藉娴滄悂鏁傞柨顖氫壕閻熸瑥瀚粈鍫ユ煕閻樺磭澧电€规洘妞介幃娆撳传閸曨厾鏆伴柣鐔哥矊閺堫剛绮╅悢鐓庡嵆闁靛繆妾ч幏娲⒑閸涘﹦鈽夐柨鏇樺€栭幈銊╂晝閸屾稓鍘遍梺缁樕戦崜姘枔濠婂牊鐓曢柍鍝勫€诲ú瀛橆殽閻愭潙娴鐐诧躬婵℃悂濡疯妤旈梻浣芥〃閻掞箓宕濆▎蹇曟殾闁割偅娲栨儫闂侀潧顧€婵″洭寮冲顑芥斀闁挎稑瀚禍濂告煕婵犲啰澧悡銈嗕繆椤栨粌甯堕柛銊︾箞楠炴牗娼忛崜褏蓱濡炪値鍋呭ú鐔煎蓟閻斿吋鍊绘俊顖滃劦閹峰綊鏌ｆ惔銏㈩暡鐎光偓閹间礁钃熼柣鏃囨绾惧吋淇婇姘儓婵炲吋鍨垮铏圭矙濞嗘儳鍓遍梺鍦嚀濞层倝鎮炬搴ｇ煓閻犲洨鍋撳Λ鍐春閳ь剚銇勯幒鎴濃偓缁樼▔瀹ュ鐓涚€广儱楠告禍婵嬫煕閻樺啿濮嶉柡宀€鍠撻埀顒傛暩椤牆鏆╁┑鐐村灦閹稿摜绮旈悽鍨床婵炴垯鍨圭粻锝嗙箾閸℃绠冲ù鐘层偢濮婃椽宕ㄦ繝搴㈢暦婵犵數鍋涢敃顏勵嚕婵犳碍鏅查柛娑樺€婚崰鎰嚗閸曨厾鐭欓柟绋块閸撶敻姊婚崒娆愮グ鐎规洜鏁诲畷浼村箛椤旇棄搴婇梺绋跨灱閸嬫盯鎮″鈧弻鐔衡偓鐢殿焾娴犳粎绱掗悩闈涒枅婵﹨娅ｇ划娆戝閺囩喓娲寸€规洏鍔戦、姗€鎮╅悽鍨啠濠电姷鏁搁崑娑㈩敋椤撶喐鍙忛柟缁㈠櫘閺佸嫰鏌涘☉妯兼憼闁稿浜濋妵鍕棘濞嗙偓缍楁繛瀛樼矋缁捇寮婚垾鎰佸悑閹肩补鈧尙鐩庡┑鐐差嚟婵數鍒掓惔銊﹀剦妞ゅ繐鐗嗙粻姘辨喐濠婂牊鍋傚┑鍌氭啞閻撴盯鎮橀悙棰濆殭濠碘€炽偢閺屽秶鎲撮崟顐や紝閻庤娲栧畷顒冪亽婵炴挻鍑归崹杈吀闂傚倸鍊搁崐椋庣矆娓氣偓楠炴顭ㄩ崟顒€寮块梺姹囧灮椤牏绮堟径瀣闁糕剝蓱鐏忣參鏌﹂崘顏勬灈闁哄被鍔戦幃銏ゅ传閸曟垯鍨荤槐鎺楀焵椤掑嫬绀冩い鏃傛櫕閸橆亝绻濋悽闈涒偓顖炲礃閵婏妇浜鹃梻浣告惈濡參宕戦崱娆愵潟闁规崘顕х壕鍏兼叏濮楀棗鍘撮柛瀣尰椤︾増鎯旈姀鐙€鈧盯姊洪崫鍕潶闁稿酣浜堕幃鎸庛偅閸愨晝鍘藉┑鈽嗗灡椤戞瑩宕靛▎鎾寸參闁告劦浜滈弸鎴犵磼缂佹娲存鐐差儔閹粓宕卞▎蹇撔熼梻鍌欑閹碱偊宕锔藉亱闁糕剝鐟ч惌鍡涙煕閹伴潧鏋熼柣鎾崇箰閳规垿鎮欓懠顑胯檸闂佸憡姊圭喊宥夊Φ閸曨垰唯闁靛鏅涘鏉库攽椤旂》鍔熺紒顕呭灦楠炲繘宕ㄧ€涙ɑ鍎梺鑽ゅ枑婢瑰棝顢曟總鍛娾拺婵懓娲ら悞娲煕閵娿倕宓嗛柡浣稿暣閺佸啴宕掑槌栨Т闂備礁婀遍崕銈夊垂閻旂厧鍑犻幖娣妽閻撴瑩鏌熼鍡楁噺閻庮噣姊虹涵鍛撴繛鑼枎椤繐煤椤忓嫮顔囬柟鑹版彧缁插潡鎮鹃棃娑辨富闁靛牆绻愰惁婊堟煕閵娿儳鍩ｉ柡浣瑰姍閹瑩宕崟顐ょ崺闂佽瀛╃粙鎺椻€﹂崶顒€鍌ㄦい蹇撶墛椤ュ﹥銇勯幇鈺佺仾闁瑰吋鍔欓弻銊╁即濡搫濮庨梺瀹狀嚙缁夌懓鐣烽崼鏇ㄦ晢濞达絽鎼獮鍫ユ⒒娴ｅ憡鎯堥柛鐔哄█瀹曟垿骞樼紒妯煎幍濡炪倖姊婚崢褔鍩€椤掍焦鍊愭い?")
        elif scenario == "idea_implementation":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欑粣娑㈡⒑閸濄儱校闁圭澧介崚鎺旂磼濡浜濋梺鍛婂姀閺呮繈宕㈡禒瀣拺闂侇偅绋戝畵鍡樼箾娴ｅ啿瀚▍鐘炽亜閺嶎偄浠﹂柣鎾跺枑缁绘繈妫冨☉娆忣槱缂備讲鍋撻悗锝庡亝閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濮风槐鎺楊敊閻ｅ本鍣ч梺瀹狀嚙闁帮綁鐛崱姘兼Щ婵犮垼顫夐敋闁宠鍨块幃娆撴嚑椤掍焦鍠栫紓鍌欑贰閸犳碍鎱ㄩ悽鐢电焿鐎广儱顦介弫鍌炴煕閺囥垺娑ф繛鍫涘姂閺岋綁鎮╅崣澶婎槱缂備椒鐒﹀娆忓祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔告倐濮婃椽宕ㄦ繝鍐ｆ嫻闂佸湱顭堥崯鍧楋綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愬宀婃澓濠电姷鏁搁崑娑㈡偤閵娧冨灊鐎广儱顦伴崑瀣煛閸モ晛浠滅紒渚囧亰濮婄粯鎷呯粙娆炬闂佺顑勭欢姘暦瑜版帗鍤掗柕鍫濇媼濡粓姊洪懞銉冾亪藟閵忥絻浜归柟鐑樻尰濞呮粓姊虹化鏇炲⒉妞ゃ劌鐗忕划濠囨煥鐎ｎ剛顔曢柣搴㈢⊕椤洭鎯岄幒鏃傜＜闁绘ê纾晶顏呫亜椤愩垻绠婚柟鐓庣秺瀹曠兘顢橀悩闈涘箚闂備浇宕垫慨鍨娴犲绀夐幖娣灩椤曢亶鏌涢妷顔煎闁抽攱鍨圭槐鎺斺偓锝庡亽閸庛儵鏌涙惔銏犵伌闁哄本绋撻埀顒婄祷閸斿矂鍩€椤掍胶绠為柣娑卞櫍瀹曟﹢顢欓懞銉︻仧闂備胶绮摫鐟滄澘鍟悾鐢稿幢濞戞瑢鎷虹紓鍌欑劍钃遍柍閿嬪笧缁辨帞绱掑Ο鑲╃暭闂佸ジ缂氭ご鍝ユ崲濠靛棭娼╂い鎾寸⊕鐎氬ジ姊洪懡銈呮瀾闁荤喆鍎抽埀顒佸嚬閸樻儳鈻庨姀銈呯闁圭儤绻勯崬鐢告偡濠婂啰效闁哄苯锕弫鎰緞鐏炵晫銈﹂梻浣告啞閸旓箓宕板Δ鍛惞闁告劦鍠楅悡鍐煕濠靛棗顏╅柡鍡欏枛閺屻劌鈽夊▎鎴犵厜濠殿喖锕ㄥ▍锝囨閹烘埈娼ㄩ柛鈩冪懃婵吋绻濋悽闈涗粶闁瑰啿绻愮叅闁哄稁鍘介崑鈺冣偓鐟板婢瑰棝寮抽崱娑欑厱闁哄洢鍔屾晶浼存煕濡粯鍊愰柟顔筋殜瀹曟寰勬繝浣割棜闂備浇顕ч崙鐣岀礊閸℃稑绀堟繛鎴炲閸欑儤绻濆閿嬫緲閳ь剚顨嗛幈銊╂倻閽樺锛涢梺缁樺姇閻忔岸寮冲鍫熺叆闁绘柨鎼暩閻庤鎸风欢姘跺箖濡ゅ懏鏅查幖瀛樼箘閹稿姊洪崫鍕靛剰闂佸府缍侀幃锟狀敃閿曗偓閻愬﹦鎲搁弮鍫晛婵°倕鎳忛悡鏇㈡煏婵犲繐顩紒鐘靛仦閹便劍绻濋崨顕呬哗闂佸綊顥撴繛鈧鐐存崌楠炴帒鈹戦崱妞劌鈹戦敍鍕杭闁稿﹥鐗曢～蹇氥亹閹烘挸浜遍梺缁橆焾鐏忔瑩寮抽敃鈧湁闁稿繐鍚嬬紞鎴︽煕閹般劌浜惧┑锛勫亼閸婃牠骞愭ィ鍐ㄧ獥閹兼番鍨婚々鍙夈亜閺嶃劎銆掔紒鈾€鍋撻梻鍌氬€搁悧濠勭矙閹达箑鐒垫い鎺嗗亾妞ゎ厾鍏橀崹楣冩晝閸屾岸鍞堕梺闈涱槶閸庡崬顕ｉ悜鑺モ拺闂傚牊渚楀Σ鎾煛閸涱喚鐭掗柟顕嗙節婵＄兘鍩￠崒婊冨箺闂備礁鎼崐鍦偓绗涘洤绠氶柛顐熸噰閸嬫挸鈽夊▎鎴犵暭缂備浇椴搁幐濠氬箯閸涙潙绠甸柟鍝勭Т椤ユ岸姊绘担绛嬪殭闁告垹鏅槐鐐哄幢濞戞锛涙繛杈剧到濠€閬嶃€呴崣澶岀瘈濠电姴鍊绘晶娑㈡煟閹惧鎳囬柡宀嬬秮楠炲鎮樺ú璁抽偗闁诡喚鍋ら幃娆擃敄鐠恒劎鐣鹃梻浣哄帶閵堟悂路閸屾凹鐒介柟鎵閻撳繘鏌涢妷鎴濆枤娴煎啯绻濈喊澶岀？闁稿繑蓱娣囧﹪鎮滅粵瀣櫓闁荤喐鐟辩徊楣冩倵閺夊簱鏀介柣妯诲墯閸熷繘鏌涢悩宕囧⒌闁轰礁鍟撮弫鍌炲箚瑜嶉悘濠傤渻閵堝棛澧遍柛瀣〒缁顢涢悙瀵稿幈濠电偞鍨靛畷顒€鈻嶅Ο璁崇箚闁圭粯甯炵粔鐑橆殽閻愬澧遍柍褜鍓氱粙鎺椻€﹂崶鈺冧笉婵﹩鍘规禍婊堟煃閸濆嫸宸ュù婊呭仧缁辨帗娼忛妸锕€纾抽悗瑙勬礃鐢帡锝炲┑瀣垫晞闁芥ê顦竟鏇㈡⒑閸涘﹦缂氶柛搴㈠▕閹矂骞樼紒妯煎幐婵犮垼娉涢鍛枔閻愵剛绠鹃柟瀵稿€戝璺虹哗濞寸姴顑嗛悡鏇㈡煃閳轰礁鏆熼柟鍐插缁绘盯宕奸悢宄板Б闂佸疇顫夐崹鍧楀箖閳哄啯瀚氱憸宥嗗閹扮増鈷戠紓浣癸供濞堟棃鏌ㄩ弴銊ょ盎闁伙絿鍏橀獮瀣晝閳ь剛绮堢€ｎ偁浜滈柟閭﹀枛閺嬫垿鏌￠崒妤€浜鹃梻鍌氬€烽懗鍫曗€﹂崼銉ュ珘妞ゆ帒瀚粈鍕煟閻旂鐝楅柨婵嗩槸瀹告繂鈹戦悩鎻掝伀妞ゆ梹娲熷娲礈閹绘帊绨肩紓浣割儐閸ㄨ埖绌辨繝鍥х缂佹妗ㄧ花璇差渻閵堝懐绠伴悗姘煎墴瀵娊鏁愰崨顏呮杸闂佺偨鍎辩壕顓㈠春閿濆洠鍋撶憴鍕鐎规洦鍓濋悘鍐⒑闁偛鑻晶鎾煥濠靛牆浠辩€规洖鐖奸、妤佹媴閸欏顏圭紓鍌氬€风粈渚€顢栭崨顖欑剨闁告稒娼欑紒鈺佲攽閻樺磭顣查柣鎾存礋閺岋繝宕橀敐鍛闂備浇宕甸崰鍡涘磿閻㈢绠栧Δ锝呭暞閸婂鏌﹀Ο渚Ш妞ゆ挻妞藉娲箰鎼淬垻锛曢梺绋款儐閹稿墽妲愰幒妤佸亹鐎瑰壊鍠氶崥瀣⒑閸濆嫮鐒跨紒缁樼箓閻ｇ兘骞掗幊宕囧枛瀹曨偊宕熼顐ｆ笎婵犵绱曢崑鎴﹀磹閵堝纾婚柛鏇ㄥ幘閻捇鏌熺紒銏犳灈闁绘挻锕㈤弻鐔告綇妤ｅ啯顎嶉梺绋匡功閸忔﹢寮诲☉妯锋瀻闊浄绲剧瑧婵犵數鍋涢悧鍡涙嚐椤栫偛鐓橀柟杈鹃檮閸婄兘鏌涘▎蹇ｆЦ婵炲懌鍊曢埞鎴︽倷鐠鸿櫣姣㈤梺鍝ュТ闁帮綁骞冩ィ鍐╁仾妞ゆ牗眉濮规姊洪崷顓炲妺闁搞劌娼″顐㈩煥閸愶絾鏂€闁圭儤濞婂畷鎰板箛閺夎法锛涢梺瑙勫劤婢у海澹曟總鍛婄厽婵☆垵娅ｉ敍宥咁熆瑜忛弫濠氬蓟閿涘嫪娌柣锝呯潡瑜嶉埞鎴︽晬閸曨偄骞嬮梺杞扮閸婂潡骞冮崜褌娌柤娴嬫櫇椤︺劑姊婚崒姘偓椋庣矆娓氣偓楠炴牠顢曢敂缁樻櫈闂佸憡绋戦悺銊╂偂閳ь剟姊洪幐搴ｇ畵妞わ富鍨堕幏鎴︽偄閸忚偐鍘介梺鍝勫€搁悘婵嬪箖閹达附鐓熼柟鍝勭Ф閻瑩鏌＄仦璇插鐎殿噮鍣ｅ畷鍫曞Ω瑜嬮埀顒€锕鐑樻姜閹殿喖濡介梺缁橆殕缁骸危閹版澘绠婚悗娑櫭鎾绘⒑閸涘﹦绠撻悗姘嚇閺佹劖寰勭€ｎ剙骞橀柣鐔哥矌婢ф鏁悙鐑樺仼婵炲樊浜濋悡鏇㈡煃閸濆嫬鏆欏ù鐘洪哺椤ㄣ儵鎮欏顔煎壎闂佽鍠楅悷鈺呭箠閻樻椿鏁嗛柛灞剧〒閳ь剦鍣ｅ濠氬磼濮橆兘鍋撻悜鑺ュ殑闁割偅娲嶉埀顒婄畵瀹曞ジ濡烽敂鑺ョ彇闂備線娼чˇ顐﹀疾濞戞氨鐭嗗璺侯儑缁犻箖鏌涢埄鍐炬畼缂佺姵濞婇弻锟犲幢椤撶姷鏆ら梺鍝勭灱閸犳劕顭囪箛娑樼鐟滃繘寮抽悩鐢电＝濞达絽鎼瀷閻庤娲滈弫绋课ｉ幇鏉跨閻庢稒锚椤庢捇鏌ｉ悩鍙夌カ缂佽鲸娲熷畷婵嬫倻閼恒儮鎷洪梺鍛婄☉椤剟鎮為悙顑跨箚妞ゆ劑鍨归顓㈡煕閳哄啫浠辨鐐差儔閹瑩鎳犻鍌涚€梻鍌氬€烽懗鍫曗€﹂崼銉︽櫇闁靛鍎嶅ú顏呭亜濡炲瀛╁▓鎯ь渻閵堝棛澧遍柛搴㈠姍瀵偊宕橀鐣屽弳濠电娀娼уΛ娆戠矈閳哄倻绠鹃柡澶嬪灥椤忣參鏌熼鐓庢Щ妞ゎ厹鍔戝畷姗€鈥﹂幋婵單ㄧ紓鍌氬€风粈渚€鎯屾担骞夸粓闁告縿鍎插畷鍙夌節闂堟侗鍎忛柣鎰功閹叉瓕绠涘☉娆忎簵闂佺懓顕崑鐔哄姬閳ь剟姊洪棃娑㈢崪缂佹彃澧藉☉鍨偅閸愨晝鍙嗛梺鍝勬处閿氶柍褜鍓氱换鍫ュ极閹扮増鍊烽柤纰卞墯濞堟洟姊洪崨濠冨闁稿繑锕㈤獮蹇撁洪鍛幗闁硅偐琛ラ崜婵堟嫻閳ユ枼鏀芥い鏍电到楠炴牗銇勯鐐村枠妤犵偛娲幃褔宕奸姀鐘茬疄闂傚倷绶氬褔鈥﹂崼銉ョ？鐎规洖娲ㄩ惌鎾寸箾瀹割喕绨奸柣鎾存礋閺屽秶鎲撮崟顐㈠Б婵炲瓨绮庨崑鎾寸┍婵犲洦鍊锋い蹇撳閸嬫捇寮介锝嗘闂佸湱鍎ら〃鍡涘疾濠靛鐓ラ柡鍌氱仢閳锋棃鏌ｉ鐔稿磳婵﹤顭峰畷濂告偄閻戔晛浜惧ù鐘差儐閸嬶繝姊洪銊ヮ洭闁告瑥妫濆娲川婵犱胶绻侀梺鍛娒幖顐㈠祫闂佽澹嗘晶妤呮偂閵忊€茬箚妞ゆ牗绻傞崥鍦磼閻樼鑰块柡宀€鍠栧畷锝嗗緞鐎ｎ亖鍋撻幇顔瑰亾濞堝灝娅橀柛鎾寸懇閸┿垺鎯旈妸锕€鈧攱銇勯幒鎴濃偓濠氬煝婢跺ň鏀介柣妯虹仛閺嗏晠鏌涚€ｎ偆鈽夐摶锝呪攽閻樻彃鏆熸い鈺佸级缁绘繃绻濋崒娑樻闂佹椿鍘煎Λ婵嬪蓟濞戙埄鏁冮柣妯诲絻婵洟姊虹紒妯诲鞍闁荤啙鍛潟闁规儳鐡ㄦ刊鏉戔攽椤旇棄鐒惧ù婊呭仧閸掓帡顢橀姀鐘碉紲濠电姴锕ら幊鎰版晬濠婂牊鈷戦梻鍫熶緱閻掗箖鏌涙繝鍐炬疁闁诡垰鑻埢搴ㄥ箛椤撶偛浼庡┑鐘垫暩婵挳宕鐐参︽繝闈涚墐閸嬫挾鎲撮崟顒€顦╅梺绋款儏閿曘儲绌辨繝鍥ㄥ€婚柦妯猴級閵娾晜鐓欓柟浣冩珪濞呭懘鏌ｈ箛鏃傚弨闁哄瞼鍠栭、娆戠驳鐎ｎ偆鏆ラ梻浣哥枃濡嫰藝閻㈠摜宓侀柟鐑橆殔缁犲鎮楅悽娈跨劸缂傚秴鍟村铏规嫚閸欏鏀銈庡亜椤︻垳鍙呭┑鈽嗗灠閵堣棄煤椤忓懎浜滅紓浣诡殙閵嗏偓闁稿鎸荤粭鐔煎焵椤掆偓椤曪綁骞橀纰辨綂闂佺粯蓱閻栫娀宕堕妸褍骞堥梻渚€娼чˇ顓㈠垂閸濆嫧鏋嶉柡鍐ㄥ€荤壕濂稿级閸稑濡奸柍缁樻礃閹便劍绻濋崟顓炵闂佺懓鍢查幊蹇曠箔閻旂⒈鏁嶆繝濠傚暙姝囬梻鍌氬€风粈渚€骞栭锔藉亱婵犲﹤鐗嗙粈鍫ユ煟閺冨倸甯剁紒鐘崇墵閺岋綁濡舵惔锛勪紘濠碘槅鍨扮€氫即骞冨Δ鍐╁枂闁告洦鍓涢ˇ銊х磽娴ｇ瓔鍤欓柛濠傛健閵嗕礁螣閼姐倝妾紓浣割儏閻忔繈鎳撻崸妤佲拺鐟滅増甯掓禍鏉棵瑰鍛槐闁诡垰瀚幆鏃堝Ω閿旇瀚藉┑鐐存尰閸╁啴宕戦幘瀵哥濞达絽鍟垮ú鐘诲焵椤掑﹦鐣电€规洖銈告俊鐑藉Ψ瑜濈槐鐢告煟鎼淬値娼愭繛鍙夌墪鐓ら柕濠忓閳绘梻鈧箍鍎遍ˇ浼存偂閻樻祴鏀芥い鏃囨婵洭鏌嶈閸撴岸宕濆▎蹇曟殾闁硅揪绠戠粻濠氭煠閹间焦娑ч柡瀣€垮娲川婵犲啫顦╅梺鍛婃尰閻╊垵妫熼梺闈涱焾閸庡搫銆掓繝姘厪闁割偅绻傞弳娆忊攽閳ョ偨鍋㈤柡宀€鍠栭幖褰掝敃椤掑啠鍋撶捄銊㈠亾鐟欏嫭绀冩俊鐐跺Г娣囧﹪鎮滈懞銉︽珖闂侀€炲苯澧版繛鍡愬灲閹瑥霉鐎ｎ偅鏉搁梻浣虹帛钃辩憸鏉垮暣椤㈡濮€閵堝棛鍘遍悗骞垮劚濞诧箓寮抽浣瑰弿濠电姴鍟妵婵堚偓瑙勬磸閸斿秶鎹㈠┑鍥ㄥ劅闁靛繈鍨哄В澶愭⒒閸屾瑨鍏屾い顓炵墦椤㈡牠宕卞▎鎴犵厯闂佽宕橀褏绮婚悢鍏肩厵缂備降鍨归弸鐔兼煛閸涱喚绠為柡灞剧〒娴狅箓宕滆閺嬫棃姊鸿ぐ鎺濇缂侇噮鍨抽幑銏犫槈濞嗘劗绉堕梺鍛婃寙閸愩劎鍘掗梻鍌欒兌椤㈠﹪顢氬鍛潟闁哄洢鍨圭粻顖滄喐閻楀牆绗氶柡鍛倐閺岋絽螣閾忕櫢绱為梺鍛婄懃鐎氭澘螞閸涙惌鏁冮柕蹇娾偓鎰佹П闂備礁婀遍幊鎾趁洪鐐垫殾闁挎繂顦粈瀣亜閹惧鈽夊ù婊堢畺閹嘲鈻庤箛鎿冧痪缂佺偓鍎抽…鐑藉蓟濞戞鏃堝焵椤掑嫬鐤柛褎顨忛弫瀣煥濠靛棙顥犳い鈺冨厴閹鏁愰崨顖欑驳闂佸搫鎳忕换鍫濐潖濞差亝顥堟繛鎴炶壘椤ｅ搫鈹戦悙鑼勾闁告梹鍨甸悾宄扳攽鐎ｎ亪鍞堕梺鍝勬川閸熷潡骞忕紒妯肩閺夊牆澧界粔顒佺箾閸滃啰绉┑鈥崇摠缁绘繈宕堕妸褍骞堥梻浣筋潐閸庢娊顢氶鐘典笉婵☆垵鍋愮壕鍏笺亜閺冨倹娅曢柟鍐叉处椤ㄣ儵鎮欓弶鎴犵懆闁剧粯鐗曢湁闁挎繂顦板▍婊呯磼閵娧勬毈婵﹦绮幏鍛村川婵犲倹娈橀梻浣告啞濡垿姊介崟顓犵焿鐎广儱鎳夐弨浠嬫倵閿濆簼绨介柣娑栧劦濮婇缚銇愰幒鎴滃枈闂佸憡锚婢ц棄顕ｈ閸┾偓妞ゆ帊鑳剁弧鈧梺姹囧灲濞佳冪摥闂備胶顭堥敃锔惧垝椤栫偛鐤鹃柛顐ｆ礀閸楁娊鏌ｅΟ鍏兼毄闁挎稒绮撳娲焻閻愯尪瀚板褍顕埀顒冾潐濞叉牠濡堕崨濠佺箚闁绘垼濮ら弲婊堟煙椤栧棗鍟伴鎴︽⒒閸屾艾鈧绮堟笟鈧獮鏍敃閿曗偓閻ゎ喗銇勯幇鍫曟闁稿顑嗙换婵囩節閸屾碍鍋愬┑鐐村灟閸ㄥ湱绮婚敐澶嬬叆闁哄啫鍊瑰▍鏇㈡煕濡粯鍊愭慨濠呮閸栨牠寮撮悤浣圭秹闂備礁鎲￠敃銏㈢不閺嶎厼绠栧Δ锝呭暞閸嬨劑鏌涘☉姗堝姛闁告ɑ鎮傞幃妤呭礂婢跺﹣澹曢梻渚€鈧偛鑻晶瀵糕偓瑙勬磻閸楁娊鐛Ο鍏煎珰闁肩⒈鍓欐慨锔戒繆閻愵亜鈧牜鏁繝鍥ㄥ殑闁割偅娲栭悡鈧梺鍝勬川閸犲棙绂嶅鍕╀簻闁规崘娉涙禒锔锯偓鐟版啞缁诲嫮妲愰幒妤婃晩缁炬媽浜崥瀣節绾板纾块柛蹇旓耿瀵偊宕掗悙鑼槶閻熸粍绮撳畷顖涙償閵婏腹鎷洪柣鐘叉穿鐏忔瑧绮婚幍顔剧＜缂備焦锚閻忔挳鏌熼銊ュ悩閺冨牆鐒垫い鎺戝閻撴繄鈧箍鍎遍ˇ顖炵嵁閵忥紕绠鹃柟瀵稿仧閹冲懘鏌涘鍡曢偗婵﹥妞介獮鏍倷閹绘帒螚闂備礁鎲￠崝鏇°亹閻愬灚顫曢柡鍐ｅ亾濞ｅ洤锕俊鍫曞炊椤喓鍎甸弻娑氣偓锝庡墮娴犻亶鏌嶉妷顖滅暤鐎规洖鐖奸、妤呭焵椤掑倻涓嶉柡灞诲劜閻撴洟鏌￠崶銉ュ濠⒀屽灠閳规垿顢欓悾宀€鐓夐梺鍝勭焿缁插€熺亙闂侀€炲苯澧撮柟顔ㄥ洤骞㈡繛鎴炵懃娴滄姊洪崫鍕窛闁哥姵鎸惧褔鍩€椤掑嫭鈷戞慨鐟版搐閻忓弶绻涙担鍐插椤╅攱绻濇繝鍌滃闁绘挾鍠栭獮鎺楀箮閽樺顦柟鍏肩暘閸斿瞼绮堥崱娑欑厵闁绘垶锕╁▓鏇㈡煛閸涱喚鍙€闁哄本鐩俊鐑藉箣濠靛洤娅ч梺鐑╁墲閿曘垹顫忕紒妯诲闁告稑锕ら弳鍫ユ⒑閸︻収鐒炬俊顐ｇ箓閻ｇ兘鎮㈢喊杈ㄦ櫇闂侀潧绻堥崹褰掑箹閸涘﹦绡€闁汇垽娼у暩闂佽桨鐒﹂幃鍌氱暦閹达附鍊烽柛婵嗗閻庮厼顪冮妶鍡欏⒈闁稿鐩畷褰掑磼閻愬鍘遍梺鎸庢椤曆囩嵁濡　妲堥柟鎯х－鏁堥梺鍝勮閸斿矂鍩為幋锕€骞㈤柍鍝勫€愯濮婅櫣绱掑Ο璇叉殫闂佸摜濮甸悧鐘差嚕婵犳碍鍋勯柛蹇氬亹閸旂兘姊洪幐搴㈢５闁稿鎸婚〃銉╂倷閹碱厽鐣肩紓浣介哺閹告悂顢樻總绋垮耿婵°倕鍟╃槐婵嬫⒒娴ｅ憡鎯堥柣顓烆槺缁辩偞鎷呴柅娑氱畾闂佸綊妫块悞锕傚疾濠靛鐓冪憸婊堝礈閻旂厧绠栨俊顖氱毞閸嬫挸鈽夊▍铏灴瀹曪綀绠涢幘顖涙杸闂佺粯锚瀵爼宕抽悜妯镐簻闊洦娲栧暩缂備浇椴哥敮锟犮€佸▎鎾村仼閻忕偞鍎冲▍鎴︽⒒娴ｅ摜鏋冩い鏇嗗洦鐓€闁挎繂顦卞畵渚€鏌涢埄鍐ㄥ毈婵¤尙绮换婵嬪閵忊€虫畬濡炪倧绠撳褔锝炶箛鏇犵＜婵☆垵顕ч鎾绘⒑缂佹ê鐏﹂柨姘箾閸繄鐒告慨濠呮濞戠敻宕担鍛婄杺缂傚倷鑳剁划顖滄崲閸儲鍋樻い鏇楀亾鐎规洘锕㈤、娆撴嚃閳哄搴婇梻鍌欒兌缁垶宕濋弴鐑嗗殨閻犺桨缍嶉敐澶樻晢闁告洦鍏橀幏娲⒒閸屾氨澧涘〒姘殔椤﹨顦寸紒杈ㄥ浮閹晠宕橀懠顑挎偅婵犵數鍋涘Λ搴ㄥ垂娴犲绠栨繛鍡樻尰閸婄粯淇婇婊冨付妤犵偛绉瑰濠氬磼濞嗘垼绐楅梺鍛婄懃缁绘帞鍒掓繝姘闁绘劕鐡ㄩ悵鐑芥⒑缂佹﹩娈旈柣妤€瀚粋宥咁煥閸喓鍘搁梺鍛婂姧缁茶姤绂嶆ィ鍐┾拺闁革富鍘介崵鈧┑鐐茬湴閸婃繈鏁愰悙鍓佺杸闁瑰彞鐒﹀浠嬨€侀弮鍫濈妞ゆ劑鍊楀畷鐑樼節閻㈤潧啸闁轰礁鎲￠幈銊╁箻椤旇偐锛欓梺褰掓？缁插憡寰勯幇顒勫敹闂侀潧顧€閼靛綊骞忓ú顏呪拺缁绢厼鎳庢禍褰掓煕鐎ｎ偆娲寸€规洘绻堥崺鈧い鎺戝閳锋垹绱掔€ｎ偄顕滄繝鈧幍顔剧＜妞ゆ柨銈搁崣鍕煟濞戝崬娅嶆鐐搭焽缁辨帒螣闁垮顏洪梻鍌欒兌椤牓寮甸鍕殞濡わ絽鍟悞鍨亜閹哄秶鍔嶉柛濠冨姉閳ь剝顫夊ú姗€宕濋弽顓勫洭鎮ч崼鐔峰妳闂佹寧绻傚ú銊╁礉鐠鸿　鏀介柣鎰煐瑜把呯磼闊厾鐭欐鐐寸墵椤㈡洑缍呭璺侯煬濞尖晜銇勯幘瀵哥焼缂併劌顭峰铏规喆閸曨偄濮㈤悗瑙勬处閸撶喖骞冨鈧崺锟犲礃椤忓棴绱查梻浣虹帛閿曘垹顭囪閸┿垽宕奸妷锔惧幐閻庡厜鍋撻柍褜鍓熷畷浼村冀瑜忛弳锔界節婵犲倹锛嶆俊鏌ョ畺閺岋綁濮€閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棛鍑归柟鏌ョ畺閺屾稒鎯旈敍鍕啋闂佸搫鑻粔鍫曞箟閹绢喖绀嬫い鎰╁€撶槐婵嬫⒒娴ｇ瓔鍤冮柛鐘冲浮瀵煡鎮╅懡銈呯ウ闂佽宕橀褏绮婚搹顐ょ瘈闂傚牊绋掗崳鐣岀棯閹岀吋婵﹤顭峰畷鎺戔枎閹存繂顬夋繝纰夌磿閸嬫稑顭囬垾宕囨殾闁靛骏绱曢々鐑芥倵閿濆骸浜滃ù鐙€鍙冨娲濞戣鲸孝闂佸搫鍊风欢姘跺春閳ь剚銇勯幒鎴伐妞も晩鍓熼弻鐔兼偡閺夋浼冩繝纰樺墲閹倿寮崘顔肩劦妞ゆ帒鍊搁ˉ姘亜閺嶃劎銆掔紒鐘荤畺閺岀喖鎮欓浣虹▏闂佹悶鍊ら崜鐔煎蓟濞戙垹惟闁靛牆鎳庣粊顕€鎮楃憴鍕缂侇喖鐭傞幃楣冩倻閽樺鍊為梺鍐叉惈閸犳稓妲愰崘娴嬫斀闁绘劘鍩栬ぐ褏绱掗懠鑸殿棄妞ゆ洩缍佸畷濂稿即閵婏附娅呴梻浣虹《閸撴繄绮欓幒妤佸亗闁哄洢鍨洪崐鐢告煥濠靛棝顎楀ù婊勭箘閳ь剝顫夊ú鏍嫉椤掑嫬绠為柕濠忓缁♀偓闂佸憡娲﹂崢鑲╃箔閿熺姵鈷戦柣鐔告緲濡插鏌熼搹顐€顏堟偩閻戣棄惟闁挎柨澧介惁鍫ユ⒑缁嬫寧婀扮紒瀣浮閹箖宕楅懖鈺冪槇闂佹眹鍨藉褎绂掗敃鍌涚厵婵繂鑻崥褰掓煕閻樿宸ユい鎾冲悑瀵板嫰宕煎顑垮闂佸憡鍔忛弲婵堝姬閳ь剟姊虹粙鎸庢拱缂侇喖绉撮埢鎾淬偅閸愨斁鎷洪梻鍌氱墛閻╊垶鎮板鍛＜閺夊牄鍔嶇粈瀣叏婵犱胶鐭欑€规洜鍠栭、娑樷槈濮橆剙绠炲┑鐘垫暩婵炩偓婵炰匠鍛亾濮樼厧澧寸€规洘绻傞～婵囨綇閳哄喛绱插┑鐐存尰閼归箖鏁冮敃鍌涘仼闁汇垹鎲￠悡娑氣偓鍏夊亾閻庯綆鍓涜摫闂備浇顕栭崹鍗炍涢崘顔衡偓浣糕槈濮楀棛鍙嗛梺鍛婄☉閹锋垹绱炴担鍓叉綎闁惧繐婀遍惌娆愮箾閸℃ê鍔ら柛鎾插嵆濮婅櫣绮欓崠鈥充紣濡炪値鍘鹃崗姗€鎮伴鈧獮瀣晝閳ь剟锝為崨瀛樼厪闁割偅绻冮崳褰掓煠閺夎法浠㈤柍瑙勫灴閹瑩寮堕幋鐘辨闂備浇宕甸崯娆撳炊瑜嶉崑宥咁渻閵堝懐绠伴柣妤€锕崺娑㈠箣閿旂晫鍘遍梺鍦亾濞兼瑧寰婄拠瑁佺懓顭ㄩ崟顓犵暭缂備浇椴哥敮鐐哄箯閻樿绠甸柟鐑樻尰椤旀帗淇婇妶鍥ラ柛瀣仱閹囨偐閼姐倕绁﹂梺鎼炲労閸擄箓寮繝鍥ㄧ厽闁绘梻鈷堥弳鎺戭熆鐟欏嫭绀€闁宠鍨块幃娆撳级閹寸姳妗撻梻浣藉吹閸熸瑩宕ㄩ娆戠憹闂備胶绮崝鏇㈡偤閵娾晛鐭楅煫鍥ㄦ尨閺€浠嬫煟濡绲婚柍褜鍓欑紞濠囩嵁閸℃稑閱囬柕澶涚畱娴滄姊洪棃娑氬妞わ缚鍗冲畷鎴︽晲婢跺鍘遍梺闈涱檧缁茶姤淇婇懖鈺冪＜闁艰壈娉涢崥鍦磼鏉堛劌娴柟顔规櫊閹崇娀顢楁繝鍕槸缂傚倸鍊峰ù鍥ㄣ仈閹间礁绠板┑鐘宠壘缁狀垶鏌涘☉妯兼憼閻庣數濮撮…璺ㄦ崉妤﹀灝顏柣銏╁灠濞硷繝寮婚敐鍡樺劅闁炽儱鍟挎潏鍛存⒑缁嬫鍎愰柟鐟版喘瀵鎮㈤崗灏栨嫽缂佺偓鍎抽鍛村储閿熺姵鍊甸悷娆忓鐏忣偆绱掗懜闈涘摵鐎殿喛顕ч埥澶愬閻橀潧濮堕梻浣侯焾缁诲棝寮插鍫濆瀭闁割偅娲栫粈鍡椻攽閻樺弶鎼愮紒鐘电帛閵囧嫰寮崒娑欑彧闂佸憡眉缁瑥顫忛搹鍦＜婵☆垳鍎甸幏璇差渻閵堝骸骞栭柣妤佹崄濡垽鏌ｆ惔顖滅У闁告挻绋撴竟鏇熺附閸涘﹦鍘甸梻渚囧弿缁犳垿寮稿☉妯忓綊鎮╁ú顏勬懙闂侀€涚┒閸斿秶鎹㈠┑瀣倞闁冲搫鍟伴悰銉╂⒒娓氣偓濞佳兠洪敃鍌氱婵炲棙鎸惧畵渚€鏌熼悜姗嗘當缂佺媴绲剧换婵囩節閸屾碍娈查梺璇插婵炲﹤顫忔繝姘＜婵炲棙鍩堝Σ顕€姊虹涵鍜佸殝缂佺粯绻堝顐も偓锝庡枟閳锋垿姊婚崼鐔恒€掑褋鍨洪妵鍕敇閻愰潧鈪甸梺璇″枟閸庢娊鎮鹃敓鐘崇劷闁挎梹鍎冲鎶芥⒒娴ｇ顥忛柛瀣浮瀹曟垿宕ㄩ弶鎴犳煣闂佹寧绻傞ˇ浼村煕閹达附鈷掗柛顐ゅ枔閵嗘帞绱掗悩宕囶暡濞ｅ洤锕幃顏勨枎韫囨梹鎮欑紓浣哄閸ㄨ京鎹㈠☉姗嗗晠妞ゆ棁宕甸崙褰掓⒑閹惰姤鏁遍柛銊ユ健瀵鈽夊Ο閿嬵潔濠殿喗顨呴悧鍡樻叏濞戙垺鈷戦悗鍦У椤ュ銇勯敂鐐毈鐎殿喖顭锋俊鎼佸煛娴ｇ绁繝纰樻閸ㄤ即骞栭锝嗗弿闁哄洢鍨洪崐鐢告煕椤垵浜濈紒鑸电叀閹顫濋鐔哄嚒闂佷紮绲块崗姗€骞冮姀銏犳瀳閺夊牄鍔嶅▍鏍ㄧ節閻㈤潧浠﹂柛銊ョ埣閹虫繃銈ｉ崘顏勭ウ闂佸壊鍋侀崕鏌ュ煕閹达附鍋ｉ柛銉ｅ妼缁插鏌涢妶鍫滃惈缂佽鲸鎸搁濂稿川椤曞懏锛佺紓鍌欑閸婂摜绮旈幘顔肩厴闁瑰濮崑鎾绘晲閸涙惌鈧銇勯敂璇茬仸闁炽儻绠撴俊鎼佸煛娴ｅ摜鐛╂俊鐐€栧Λ鍐ㄎ涚捄銊ュ灊闁斥晛鍟扮弧鈧梺姹囧灲濞佳勭濠婂嫪绻嗘い鎰剁悼閹冲洦顨ラ悙鏉戝缂佺粯绻傞～婵嬵敇閻愭壆鏆楅梻鍌欑閹碱偄煤閵娾晛绐楅柛鈩冾焽椤╁弶绻濇繝鍌滃闁绘挻鐟╁娲敇閵娧呮殸闂佸搫顑嗙粙鎾诲焵椤掍胶鈯曠紒璇茬墕椤繐煤椤忓嫬绐涙繝鐢靛Т閸熺娀骞忛崷顓犵＝濞撴艾娲ら弸鐔兼煙閻熺増鎼愭い鏇悼閹风姴顔忛鍏煎€┑鐘灱濞夋盯顢栭崶顒€鐭楅柛鈩冪⊕閻撶喖骞栭幖顓炵仯缂佸娼ч湁婵犲﹤瀚粻姗€鏌熸搴♀枅闁诡喗鐟╅幃婊兾熼柨瀣伖闂傚倷绀侀幉锛勬崲閸屾壕鍋撳鐓庡箹闁挎洏鍨介獮宥夘敊閸撗嶇床闂佽鍑界紞鍡涘磻閸涱垯鐒婇柟娈垮枤绾惧ジ鏌涚仦鍓р槈婵炴惌鍣ｉ弻鈩冩媴缁嬪簱鍋撻崸妤€绠栨繛鍡樻惄閺佸棝鏌嶈閸撶喖骞冮悽绋跨骇閹煎瓨鎸婚弬鈧梻浣虹帛閸旀洟鎮洪妸褏绀婇柟瀵稿亼娴滄粓鏌熺€涙绠栭柛锝堟缁辨帡宕掑姣欙綁鏌曢崼顒傜М鐎规洘锕㈤崺锟犲礃閵娿儳顔囬梻鍌氬€烽悞锕傚箖閸洖纾挎い鏍仜绾惧潡姊洪鈧粔鐢稿磹閼哥偣浜滈柡鍐ㄧ墛閺嗘粓鏌涚€ｎ偅灏甸柟鍙夋尦瀹曠喖顢楅埀顒勬儗椤曗偓濮婅櫣绱掑Ο娲殝闂傚倸瀚€氼喚鍒掑顓熺秶闁靛ě鍛闂備焦鎮堕崕鎾春閺嶎厼鐤炬い鎺嗗亾闁宠鍨块幃娆撳级閹寸姳妗撻梻浣藉吹閸ｏ妇寰婇崜褏鐭夐柟鐑樻处濡插姊虹€圭媭娼愰柛銊ユ健楠炲啫鈻庨幘鏉戞濡炪倖宸婚崑鎾淬亜閿濆懏璐＄紒杈ㄦ尰缁楃喖宕惰閻忓秹姊洪懡銈呮毐闁哄懏鐩、姘舵晲閸℃瑧鐦堝┑顔斤供閸樿棄鈻嶅鍕瘈闁靛骏绲剧涵楣冩煥閺囶亞鐣甸柟顔兼健閸┾偓妞ゆ帊妞掔换鍡涙煟閹板吀绨婚柍褜鍓氶悧鏇㈩敊韫囨梻绡€婵﹩鍓涢敍娑㈡⒑鐟欏嫬鍔ゅ褍娴锋竟鏇熺附閸涘﹦鍘藉┑鐐叉閸旀骞婇崘顔藉€垫慨妯稿劚婵＄晫绱掗崒姘毙㈡い顓滃姂瀹曞ジ鎮㈤崫鍕婵犵數濮伴崹濂稿春閺嶎偆鐭欓柟鎹愵嚙缁€鍡椕归悡搴ｆ憼闁绘挾鍠栭悡顐﹀炊瑜濋弨缁樼箾閸涱叏韬柡?")
        elif scenario == "engineering_challenge":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欑粣娑㈡⒑閸濄儱校闁圭澧介崚鎺旂磼濡浜濋梺鍛婂姀閺呮繈宕㈡禒瀣拺闂侇偅绋戝畵鍡樼箾娴ｅ啿瀚▍鐘炽亜閺嶎偄浠﹂柣鎾跺枑缁绘繈妫冨☉娆忣槱缂備讲鍋撻悗锝庡亝閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濮风槐鎺楊敊閻ｅ本鍣ч梺瀹狀嚙闁帮綁鐛崱姘兼Щ婵犮垼顫夐敋闁宠鍨块幃娆撴嚑椤掍焦鍠栫紓鍌欑贰閸犳碍鎱ㄩ悽鐢电焿鐎广儱顦介弫鍌炴煕閺囥垺娑ф繛鍫涘姂閺岋綁鎮╅崣澶婎槱缂備椒鐒﹀娆忓祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔告倐濮婃椽宕ㄦ繝鍐ｆ嫻闂佸湱顭堥崯鍧楋綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愬宀婃澓濠电姷鏁搁崑娑㈡偤閵娧冨灊鐎广儱顦伴崑瀣繆閵堝懏鍣圭紒鐘靛仱閺屾洘绻涢悙顒佺彅闂佺粯鍔曢敃銉╁Φ閸曨垰绠崇€广儱鐗滈崬褰掓⒑閸︻厽鐒挎繛鍜冪悼濡叉劙骞樼拠鑼紲濠电偛妫欓崹鍨繆娴犲鐓㈤柛鎰靛枙閹查箖鏌熼绛嬬劸缂佺姵鐩弫鎰板川椤撶姷娼夐梻鍌欑閹碱偊寮甸鍌滅煓闁圭儤姊瑰畷鍙夌節闂堟侗鍎忕痪鎯с偢閺屾洟宕煎┑鍥ㄦ倷闂佽鍠楅崹鍨潖缂佹ɑ濯撮柧蹇撶畭閳ь剙锕弻锟犲磼濞嗘垹鐛㈤悗瑙勬礃閸ㄥ潡鐛鈧獮鍥ㄦ媴閻熸壆妲ｉ梻鍌欑窔濞佳囨偋閸℃あ娑樜旈崨顓㈡暅婵犵數濮村ú锕傛偂閺囥垺鍊甸柨婵嗛娴滄繈鎮樿箛鏇熸毄缂佽鲸甯楀蹇涘Ω閵夛箒鐧侀梻浣筋嚃閸犳帡寮查悩璇茬疇闁绘ɑ妞块弫鍕亜閹邦剟顎楅柟鍐差樀瀹曟垿骞橀懜闈涙瀭闂佸憡娲﹂崜娑⑺囬妸銉㈡斀闁绘劘娉涢惃娲煕閻樻煡鍙勯柟顕€绠栭幃婊堟嚍閵夛附顏熼梻浣虹帛閿氶柛鐔锋健閸┾偓妞ゆ巻鍋撳褍娴峰Σ鎰板箻鐎涙ê顎撻梺鍏肩ゴ閸撴繈宕归幐搴濈箚闂傚牊绋堥弨浠嬫煕閳ュ磭绠查柡鍌楀亾闂傚倷鑳堕崑銊╁磿鏉堚晛顥氭い鎾卞灩閺勩儵鏌ㄥ┑鍡樼闁稿鎸鹃幉鎾礋椤掑偆妲柣搴ゎ潐濞诧箓宕滈悢鐓庢槬闁靛繆鍓濋崕鐔兼煃椤撴粌鍔ら柛鐘崇墵楠炲﹪鏁撻悩鍙傃囨煕閹扳晛濡洪柤鍓蹭簼缁绘繈鎮介棃娴躲儲銇勯敐搴℃灓婵″弶鍔欏鎾閻樼绱遍梻浣侯攰閹活亞绮婚幋鐘差棜鐟滅増甯楅悡娑氣偓骞垮劚妤犳悂鐛Δ鍛厱閻庯綆浜堕崕鎰庨崶褝韬┑鈥崇埣瀹曘劑顢欓崗纰变哗闂傚倷绀侀幖顐も偓姘ュ姂瀹曟洟鎮界粙鑳憰濠电偞鍨崹鍦不濞戙垺鐓冮弶鐐村椤︼附銇勯妷銉剶婵﹥妞介獮鎰償閿濆洨鏆ゆ俊鐐€х€靛矂宕归崼鏇炶摕閻庯綆鍠栭悙濠冦亜閹哄秷鍏岄柛姗嗕簼缁绘繈濮€閿濆懐鍘紓浣割儐閸ㄥ潡濡撮崨鎼晢闁告洦鍓涢崢鍗炩攽閳藉棗鐏犻柛姘儔瀵娊顢楁担鐟板伎婵犵數濮撮幊蹇涱敂閻樼粯鐓欏瀣閳诲牓鏌涢妸锕€鍔ら柣锝囧厴瀹曞爼鏁愰崨顒€顥氬┑鐘垫暩婵數鍠婂澶嬪亗闁哄洨鍠撶弧鈧繝鐢靛Т閸婃悂寮冲▎鎾寸厸闁糕剝鐟ラ弸鏃傜磼鏉堛劌娴柛鈹惧亾濡炪倖甯婇懗鍓佸姬閳ь剟姊洪幖鐐插姌闁告柨顦甸獮蹇撁洪鍛嫼闂佸憡绋戦敃锔剧不閹剧粯鍊垫慨妯煎帶閺嬶箓鏌嶉鍡樻毈婵﹦绮粭鐔煎焵椤掑嫬鐒垫い鎺戝€告禒婊堟煠濞茶鐏￠柡鍛埣椤㈡盯鎮欑€电骞愰梺璇插嚱缂嶅棙绂嶅Δ鍛；闁靛繆鎳囬崑鎾斥枔閸喗鐏侀梺鍛婃煥缁夊墎鍒掔€ｎ喖绠抽柡鍌氭惈娴滈箖鏌ㄥ┑鍡涱€楀ù婊呭仱閺屾稑螣缂佹ê纾冲┑顔硷攻濡炶棄螞閸愩劉妲堥弶鍫涘壉閵堝鈷戠紒瀣健閸欏嫬霉濠婂棙纭炬い鏇秮閹煎綊顢曢敐鍥┬ら梻浣稿暱閹碱偊宕导瀛樻櫖婵犲﹤鐗婇埛鎴犵磽娴ｈ鐒介柟鍐插閺岋綁鎮㈤弶鎴濆闁绘挶鍊濋弻銊╁即閻愭祴鍋撹ぐ鎺戠；闁稿本绋撶粻楣冩煕閳╁厾顏呮叏閸屾鐟邦煥閸曨厾鐓夐梺鍝勭焿缁绘繂鐣峰鈧俊鎼佸Ψ閵忕姳澹曢梺鍛婄缚閸庢煡寮冲鍫熺厱妞ゆ劧绲剧粈鍐煟閹惧啿鏆熼柟鑼焾椤劑宕煎┑鍫Ф婵犳鍠楅…鍫濃枖濞戞氨涓嶉柡宥庡幗閻撴洜鈧厜鍋撻柍褜鍓熷畷鎴濃槈濮樺彉绗夐梺鍝勭▉閻忔盯寮崼鐔告珳闂佸憡渚楅崢钘夆枔閺屻儲鈷戠紒瀣皡瀹搞儲銇勯鐘插幋鐎殿喖顭烽弫鍐焵椤掑啰浜藉┑鐐存尰閸戝綊宕规潏顭戞婵犵绱曢崑鎴﹀磹閺嶎厼绠伴柟闂寸缁犺銇勯幇鍓佺暠闁绘挻锕㈤弻鐔告綇妤ｅ啯顎嶉梺绋款儐閸旀瑩寮婚妶鍥ф瀳闁告鍋涢獮鎰磽娓氬洤鏋ら柡浣筋嚙椤繐煤椤忓嫬绐涙繝鐢靛Т閸熺娀骞忚ぐ鎺撯拺缂備焦锕╁▓妯衡攽椤旇姤灏﹂柟顕€绠栭幃婊堟寠婢跺矈鍟嬬紓鍌氬€烽悞锕傛晝閳轰絼娑㈠礃閵娿垺鏂€闂佺粯鍔栧娆撴倶閸楃儐娓婚柡澶嬪灦閹叉悂鏌嶈閸撶喎顭囪閹矂宕掑鍏肩稁濠电偛妯婃禍婵嬎夐崼鐔虹闁瑰鍋犳竟妯汇亜閿濆懏鎯堥柍瑙勫灴閸┿儵宕卞鍓у嚬闂備浇宕甸崯娆撳礋椤撗勯敜闂備礁缍婂Λ鍧楁倿閿曞倸纾婚柕濞炬櫆閻撴洘绻涢幋鐑囧叕闁告梻鍠栭弻娑橆潨閳ь剚绂嶉崼鏇炶摕闁挎繂妫欓崕鐔搞亜閺嶃劎鐭岄弽锟犳⒒娴ｄ警鐒炬い鎴濇噽閳ь剚鍑归崣鍐嵁閸儱惟闁靛鍠栭幃鎴︽⒑閹肩偛鍔电紒鑼跺Г缁傚秹鎮欓鍌滎啎闂佸壊鍋呯换鍕閵忋倖鐓涢悗锝冨妼閳ь剚鐗犳俊鐢稿礋椤栵絾鏅ｉ梺缁樺姍濞佳囧焻閻㈠憡鈷戠紒顖涙礃閺夋椽鏌涢妸锔姐仢妤犵偛妫濆顕€宕煎顏佹櫊閺屾洘绔熼姘冲闁哄拋浜缁樻媴缁涘娈┑鐐差嚟閸忔ê顕ｉ锕€绠瑰ù锝嗙ゴ閸嬫捇鏁冮崒姘跺敹闂侀潧锛忛崘顏傚亰濠电姴鐥夐弶搴撳亾閺囥垹绠犻煫鍥ㄧ☉閻撴洟鏌熼悜妯烘鐟滅増甯楅弲鏌ユ煕椤愩倕娅忓ù鐘櫊閺岋綁濮€閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｆ繝姘╅柍杞扮瀹撳棗鈹戦埥鍡楃仴婵炲拑绲剧粋鎺楁偂鎼搭喗瀵岄梺闈涚墕妤犳悂鐛弽銊х婵炴潙顑嗗▍濠囨寠濠靛鐓曢柨鏃囶嚙楠炴劙鏌涚€ｎ偅灏甸柟鍙夋尦瀹曠喖顢楅崒銈喰炵紓鍌氬€风欢锟犲窗閺嶎厽鍎楅柛宀€鍋涚粻鏍旈敐鍛殲闁稿﹤顭烽弻锕€螣娓氼垱楔闂佺锕﹂崑銈咁潖濞差亜绀冮柛娆忣槹閸庢捇姊洪崫銉バｇ紒瀣尭鍗遍柟鐗堟緲閽冪喖鏌曟径娑滃悅闁归攱妞藉娲川婵犲嫮鐣甸柣搴㈣壘閸㈡彃宓勯梺褰掓？閻掞箓鎮￠悢闀愮箚闁靛牆鍊告禍楣冩煟鎼淬垻顣叉繝銏★耿閹儳鐣￠幍铏杸闂佺硶妾ч弲娑㈠箖閹达附鈷戦柟鑲╁仜閸旀鏌￠崨顔剧疄闁诡喚鍋炵缓浠嬪川婵炵偓瀚奸梻浣告啞閹告槒銇愰崘鈺冾洸闁哄稁鍘介悡鏇㈠箹濞ｎ剙鐏柛娆屽亾闂備浇顕栭崳顖滄崲濠靛棭鍤曢柟缁㈠枛椤懘鏌ㄥ☉妯侯仼妤犵偛绉瑰缁樻媴閾忕懓绗￠梺鎼炲妽閸庡ジ骞楅锔界厽闊洦鎸荤粋瀣煕濡搫鈷旀俊鍙夊姍楠炴帡骞嬮鐔风槣闂備焦瀵уú宥夊磻閹剧粯鐓曟俊顖濐嚙缁€鍐煏閸ャ劌濮嶆鐐村浮楠炴﹢宕楅崨顔界窔闂傚倸鍊风粈渚€骞夐埄鍐懝婵°倕鎳庨崹鍌炴煙閹増顥夋慨瑙勭叀閺屾洟宕煎┑鎰ч梺绋匡功閺佸骞冨畡鎵虫瀻闊洦鎼╂禒鍓х磽娴ｆ彃浜鹃梺鍛婂姦娴滅偟澹曢崗绗轰簻闁哄啫娲ゆ禍鍦磼閻樺樊鐓奸柟绋匡工閳规垿宕堕妷銈囩泿闂備礁鎼ú锕傘€冮崨顔绢洸濡わ絽鍟埛鎴︽煕濠靛棗顏柣鎺曟硶缁辨帗娼忛妸锔绢槹闂佺硶鏂侀崑鎾愁渻閵堝棗绗掗柨鏇缁棃鎮介崨濠勫幈闁诲函缍嗘禍婵嬎夐姀鈽嗘闁绘劘顕滈煬顒傗偓瑙勬礀閻栧吋淇婇幖浣规櫇闁逞屽墮椤曪綁骞愭惔锝囩槇闂佹眹鍨藉褍鐡梻浣烘嚀閸熻法鎹㈠鈧妴渚€寮崼鐔蜂汗闂佹眹鍨婚弫鎼佹晬濠婂牊鐓涘璺猴功婢ф垿鏌涢弬璺ㄧ伇缂侇噮鍙冮獮鎺懳旀担鐟版畽闂備焦瀵х换鍌炈囨导瀛樺亗闁哄洢鍨婚崣鎾绘煕閵夛絽濡界紒鈧埀顒勬煟閵忊晛鐏ラ柛鈺傜墱閹广垹鈽夐姀鐘茬獩濡炪倖妫侀崑鎰鐏炶В鏀芥い鏃傘€嬮崝鐔虹磼椤曞懎鐏︽鐐茬箻瀹曘劑顢欓崜褎鍤屾俊鐐€栭悧妤冪矙閹烘姹查柣鎰嚟缁♀偓闂佹眹鍨藉褎绂掑鍫熺厵闁告劘灏欑粻浼存偂閵堝鐓熼柡鍐ㄧ墱濡垿鏌￠崱顓㈡缂佺粯绻堝Λ鍐ㄢ槈濞嗘垵濮奸梻浣告惈閸燁偊鎮ч崱娆戠焼闁告劦鍠楅悡蹇撯攽閻愯尙浠㈤柛鏂诲€曢湁婵犲ň鍋撻柛妤€鍟块～蹇曠磼濡顎撶紓浣割儐椤戞瑥螞瀹€鍕拺缂佸顑欓崕蹇斾繆椤愶絿绠撻柣锝囧厴閹囧醇閻斿嘲濡抽梻浣瑰缁诲倸螞椤撱垹纾婚柕濞炬櫆閳锋垹绱撴担濮戭亝鎱ㄦ径鎰厱閹煎瓨绋戦埀顒佺箞楠炲啴鍨鹃弬銉︾€婚梺鐟板⒔鐞涖儵骞忛崫鍕垫富闁靛牆妫欑亸顏堟煕閺傚潡鍙勯柟顔惧亾濞煎繘鈥﹂幋鐑嗗晬闂備胶绮崝姗€骞撻鍫熷殌闁秆勵殕閻撴盯鎮橀悙鎻掆挃闁宠棄顦伴妵鍕敃閿濆洨鐓夐梺绯曟杹閸嬫挸顪冮妶鍡楃瑨闁稿﹦绮粙澶婎吋婢跺鍘搁悗瑙勬惄閸犳牠寮甸鍌滅閹肩补妾ч弨浠嬫煟閹邦剙绾ч柍缁樻礀闇夋繝濠傚閻鎮楅棃娑栧仮闁诡喒鏅濈槐鎺懳熼悡搴＄疄闂傚倷绀侀幖顐⒚洪妸鈺佺；闁绘柨鎽滈々閿嬬箾閹存瑥鐏╅柡瀣╃窔閺屾盯顢曢悩鎻掑闂佹娊鏀遍崹鍧楀箖瑜版帒鐐婄憸宥囩棯瑜旈弻鐔兼儌閸濄儳袦闂佸搫鐭夌紞渚€骞冮姀銏㈢煓閹煎瓨鎸婚悘鍡涙煟鎼淬値娼愭繛鍙夛耿閺佸啴濮€閵堝懐鐤囧┑掳鍊曢幏瀣极瀹ュ棔绻嗛柕鍫濆€告禍鐐箾鐎涙鐭掔紒鐘崇墵瀵鈽夊搴⑿俊鐐€戦崝灞轿涘┑瀣畺闁跨喓濮甸崑鍕⒒閳ь剟骞囬鍓ф毎闂傚倷绶氬褔鎮ч崱娑樼９闁告稑锕﹂々鎻捨旈敐鍛殲闁抽攱鍨圭槐鎾存媴閻ч晲绶靛┑鐐茬墛濡啴寮婚悢鍏兼優妞ゆ劑鍨归～鎺懳旈悩闈涗沪闁搞劍瀵ч幈銊╁焵椤掑嫭鐓忛柛顐ｇ箖閸ｅ綊鏌ら弶璺ㄤ虎闁宠鍨块幃娆撳级閹寸姳妗撻梻浣藉吹閸熸瑩宕惰閸嬪秹姊洪崨濠庢畼闁稿鍔欏銊︾鐎ｎ偆鍘介梺褰掑亰閸撴瑧鐥閵囧嫰濡烽敂鍓х厑缂備胶绮粙鎾诲焵椤掍胶鈯曟い顓炵墛缁旂喎顫滈埀顒€鐣烽埄鍐╃秶闁冲搫鍊搁弸鎴︽⒑缂佹﹩娈旈柣妤€妫涚划顓烆潩閼哥數鍘介梺瑙勫劤閻°劎绮堥埀顒勬⒑鐎圭媭娼愰柛銊ユ健楠炲啴鍩￠崨顓狀唽闂佸湱鍎ら幐濠氼敊閸曨偀鏀介柣妯诲墯閸熷繘鏌涢悩宕囧⒌闁诡啫鍕瘈闁搞儺鐏涢敃鍌涚厱闁哄洢鍔岄悘鐘诲箚閻斿吋鈷戦柟绋挎捣缁犳捇鏌熼崘鎻掝劉闁逛究鍔戦弫鍐磼濞戞帗瀚奸梺鑽ゅТ濞茬娀鍩€椤掑啯鐝柣蹇撶Ч濮婃椽鎳￠妶鍛瘣闂佸搫鎳愭繛鈧柟顔诲嵆椤㈡岸鍩€椤掑嫮宓佹俊顖氬悑鐎氭岸鏌ょ喊鍗炲⒒闁哥偟鍎ょ换婵嬫偨闂堟稈鏋呭┑鐐板尃閸忕偓绋戣灃闁逞屽墴瀵偊顢欓崜褏锛濋梺绋挎湰閼归箖鍩€椤掍焦鍊愮€规洘鍔欓獮鏍ㄦ媴閸濄儻绱梻浣虹帛閸ㄥ吋鎱ㄩ妶澶婂惞闁告洦鍨遍悡鏇㈡煙閹规劕鐨烘い锔肩畵閺屾盯濡搁敂鍓х暫闂侀潧娲ょ€氭澘顕ｆ禒瀣╃憸蹇涙偂娓氣偓閹鎲撮崟顒傤槰闂佺粯鎼换婵嗩嚕鐠囨祴妲堥柕蹇婃櫆閺呮繈姊洪幐搴ｇ畵婵炲眰鍔戦幃鐐附閸涘ň鎷洪梺鍛婄箓鐎氼參鏁嶉弮鍫熲拻闁告洦鍋勯顓炩攽閿涘嫭鏆€规洜鍠栭、娆撳礈瑜庡鎴︽⒒娴ｅ憡璐￠柛瀣尭椤洤鈻庤箛濠冪€洪梺闈涚墕濡稓寮ч埀顒€鈹戦悙鑼闁诲繑绻堥幃姗€鏁撻悩宕囧幍闂佸憡绋戦敃銈夊煝閺囩姭鍋撳▓鍨灕妞ゆ泦鍥х叀濠㈣泛谩閻斿吋鐓ラ悗锝呯仛缂嶅苯鈹戦悩鎰佸晱闁哥姵顨婇妴鍐川鐎涙ê浜辨繝鐢靛Т濞层倝寮告笟鈧弻鐔碱敍閸″繐浜鹃梺琛″亾濞寸姴顑嗛悡鐔兼煙闁箑鐏犻柣銊ユ惈椤儻顧傜紒鎻掑⒔閹广垹鈽夐姀鐘炽仢闂佸憡鍔︽禍婵嬪磻瑜嶉埞鎴﹀灳閸愯尙楠囬梺鍛婃⒐閻熲晠鎮伴鍢夌喖宕楅悡搴ｅ酱闂備浇鍋愰埛鍫ュ礈閵娧勵潟闁告瑥顦辩弧鈧┑鐐茬墕閻忔繈寮搁悢鍏肩叆闁哄洦顨嗗▍濠勨偓瑙勬礃椤ㄥ懘锝炲鍫濈劦妞ゆ巻鍋撻柣锝囧厴楠炲鏁冮埀顒傜不婵犳碍鍋ｉ柛銉簻閻ㄧ儤銇勯弮鈧崝鏍崲濞戞瑦缍囬柛鎾楀啫鐓傞梻浣侯攰婵倗鍒掗幘璇叉瀬鐎广儱鎳夐弸搴ㄦ煙闁缚绨界紒鐘冲哺濮婅櫣绱掑Ο鍝勵潓濠碘槅鍨伴敃顏勭暦閺囷紕鐤€闁哄啫鍊婚鏇㈡煟鎼达絾鏆╂い顓炵墦瀹曘垽骞橀鐣屽幍濡炪倖鐗楀銊╂倿閸濄儮鍋撶憴鍕鐎规洦鍓熼垾鏃堝礃椤忓啰鍓ㄩ梺鍝勮癁閸屾凹妫滈梻鍌欑濠€閬嶅磿閵堝鏄ラ柛顐ｇ箥閻掍粙鏌嶉崫鍕櫤闁绘挶鍎茬换婵嬫濞戞瑯妫￠梺闈╃悼椤牓鈥︾捄銊﹀枂闁告洦鍓涢ˇ浼存⒑閸濆嫮鐒跨紒鏌ョ畺楠炲棝寮崼婢囧箹濞ｎ剙鐏紒澶愭敱缁绘繈鎮介棃娑楀摋濡炪倖娲樼划搴ｅ垝婵犳艾绠荤€规洖娲﹀▓楣冩偡濠婂懎顣奸悽顖涘浮閺屽宕堕浣哄幐闂佹悶鍎弲娑樼摥缂傚倷妞掔欢銈囩不閹达箑鐓橀柟杈惧瘜閺佸﹤鈹戦钘夊缂侇喖鐖煎铏圭矙濞嗘儳鍓遍梺鍦焾椤攱淇婇悽绋跨妞ゆ牗鍑瑰濠囨⒑閹稿海鈽夐悗姘煎弮瀹曟娊顢氶埀顒€顫忛搹瑙勫珰闁炽儴娅曢悘鍡涙⒑閸涘娈曞┑鐐诧工閻ｉ鎲撮崟鈺佷簼闂佸憡鍔戦崝搴ㄋ囪濮婃椽宕ㄦ繝浣虹箒闂佸憡鐟ユ姝岀亱濠电姴锕ら悧濠囧煕閹烘鐓曢悘鐐插⒔閹冲棝鏌涜箛鎾存拱闁靛洤瀚伴、姗€鎮欓棃娑掑徍闁诲孩顔栭崰姘跺极婵犳哎鈧礁螖閸涱厾锛滃┑鐘诧工閹虫劙宕㈤鐐粹拻濞达絽鎲＄拹锟犳煕鐎ｎ偅宕岄柟顖氭穿閵囨劙骞掗幋鐘插Е婵＄偑鍊栧濠氬磻閹剧粯鐓欓柧蹇ｅ亾閼版寧顨ラ悙鎻掓殭妞ゎ厹鍔戝畷濂告偄闁垮鏋€闂傚倷绶氬褔藝椤撱垹纾挎い鏇楀亾鐎规洘鍨块獮妯肩磼濡桨缂撻梻浣告啞缁嬫垿鏁冮敃鍌氱煑闁糕剝銇涢弨浠嬫煟濡偐甯涙繛鎳峰嫪绻嗘い鎰剁悼濞插鈧娲橀悷鈺佺暦閻戠瓔鏁囬柣妯碱暜缁辨煡姊绘笟鈧褔鈥﹂崼銉ョ？婵炲樊浜濋崑鍌氣攽閸屾碍鍟為柣鎾寸洴閹﹢鎮欓幓鎺嗘寖闂侀潧妫欑敮锟犲蓟瀹ュ牜妾ㄩ梺鍛婃尪閸斿海妲愰悙鍝勫耿婵☆垳鈷堝ú鎼佹⒑缂佹ê濮囬柣掳鍔岄埢宥堢疀濞戞瑢鎷婚梺绋挎湰閻熝囁囬敃鍌涚厵缁炬澘宕禍浼存煙椤栨碍婀扮€垫澘瀚禒锕傛偩瀹€鈧悺妯衡攽鎺抽崐褏寰婃禒瀣柈妞ゆ劑鍊楁稉宥嗘叏濡灝鐓愰柣鎾寸洴閺屾盯骞囬埡浣割瀷婵犫拃鍥︽喚闁哄备鍓濋幏鍛村传閵夋劧绲跨槐鎺旂磼濡偐鐣虹紓浣虹帛缁诲牆鐣烽幒鎴旀婵☆垳绮銈夋⒒閸屾瑧鍔嶉悗绗涘懏宕查柛灞绢嚤濞戞ǚ妲堟慨妯哄綁缁楀淇婇妶蹇曞埌闁哥噥鍨跺畷鎰板垂椤愩倗顔曢梺鐟邦嚟閸嬬喖骞婇幇鐗堢厽闁瑰搫绉堕惌娆撴煛瀹€瀣М妞ゃ垺锕㈤幃婊堝幢濡も偓婢瑰绱撻崒娆愮グ濡炴潙鎽滈弫顕€鎮欓崫鍕唵闂佺粯顭囩划顖炲吹閹寸偑浜滈柟鍝勬娴滈箖姊洪幇浣风敖闁轰浇顕ч～蹇涙惞鐟欏嫬鐝伴梺鐐藉劥濞呮洟鎮甸婊呯＝濞达綀娅ｇ敮娑氱磼鐠囪尙澧﹀┑鈥崇摠閹峰懘鎳栧┑鍥棃鐎规洏鍔戦、姗€鎮埀顒€危瑜版帗鈷掑ù锝囶焾椤ュ繘鏌ｉ幘宕囧ⅵ鐎规洘鍨垮畷銊╊敇濞戞瑧鈧椽鎮楅崗澶婁壕闂佸憡娲﹂崗姗€骞忕紒妯肩閺夊牆澧界€靛ジ鎮归埀顒勬晝閸屾稑鈧灝螖閿濆懎鏆為柣鎾寸洴閺屾盯顢曢顫盎婵犫拃鍕棆缂佽鲸甯￠、娆撴偩鐏炴儳娅氭俊銈囧Х閸嬫盯顢栨径鎰瀬闁告劦鍠栭悞鍨亜閹烘垵顏╃紒鈧崟顖涚厽婵☆垵鍋愮敮娑㈡煟閹惧鎳囩€殿喖鐖煎畷濂稿Ψ瑜忛弳顐⑩攽閿涘嫯妾搁柛锝忕秮瀵顓兼径瀣弳闁诲函缍嗘禍鐐寸閼测晝纾藉ù锝勭矙閸濇椽鏌熺粙娆剧吋妤犵偛绻樺畷銊р偓娑櫭崜顒勬⒒閸屾浜鹃梺褰掑亰閸犳稓鎹㈤幋婵冩斀闁绘ê鐏氶弳鈺呮煕鐎ｎ偆娲撮柟顔ㄥ嫮绡€闁稿濮ら惄顖氱暦濮椻偓椤㈡瑩鎳濋悧鍫熷暫闂傚倷鐒︾€笛呮崲閸岀偛绠熸慨妞诲亾鐎殿噮鍣ｅ畷鐓庘攽閸繂袝濠碉紕鍋戦崐鏍暜閹烘柡鍋撳鐓庡籍鐎殿喗褰冮埞鎴犫偓锝庡亞閸欏棝姊洪崫鍕殭闁稿﹦鎳撻埢宥夊即閻旂繝绨婚梺鍐叉惈閸婂宕ｉ埀顒勬⒑閸濆嫮鐏遍柛鐘崇墪椤繘鎳￠妶鍌氫壕闁割煈鍋嗛幗鍐磼閹邦収娈滄慨濠勫劋濞碱亪骞嶉鍛滄繝鐢靛仜濡﹪宕ｉ崘顭戝殨濠电姵纰嶉弲鎻掝熆鐠虹尨鍔熸い鎾虫惈閳规垿鎮╃紒妯婚敪濠电偞娼欓崐姝岀亱闂侀潧鐗嗛ˇ浼村煕閹达附鐓曟繝闈涘閸旀艾霉閻樻瑥娲﹂悡娑樏归敐鍛棌闁绘挸鍚嬮〃銉╂倷閹绘帗娈梺浼欑秶缁绘繈寮婚崶顒佹櫆闁诡垎鍐╄緢闂傚倸鍊风粈渚€骞夐敓鐘茬闁挎梻鏅々鏌ユ煟閹邦亣顒熼柡浣革工椤潡鎳滈棃娑橆潔闂佹娊鏀遍崹鍨潖濞差亶鏁冮柨婵嗘储閳ь剚甯￠弻宥囨喆閸曨偅璇為梺鍝勬湰閻╊垰顕ｉ鈧崺鈧い鎺戝閸ㄥ倿鏌涜椤ㄥ牆鐣垫笟鈧弻娑㈠箛闂堟稒鐏嶉梺绋款儌閺呮繈鍩€椤掆偓閸樻粓宕戦幘缁樼厓鐟滄粓宕滈悢鐓庣畾閻忕偠袙閺嬪酣鏌熼悙顒佺稇濞寸媭鍨跺娲箹閻愭彃濮岄梺鍛婃煥缁夊爼鍩€椤掍胶顣叉繛鍙夌矌濡叉劙骞掑Δ浣镐汗闂佹儳娴氶崑鍕閹惰姤鍊垫繛鍫濈仢閺嬶附銇勯弴鍡楁搐閻撯€愁熆閼搁潧濮囨い顐㈡嚇閺岋絽螣鐠囪尙绁风紓浣风贰閸ｏ絽顫忕紒妯肩懝闁逞屽墮椤洩顦归柍銉畵瀹曞ジ濡烽妷褝绱甸梻浣瑰劤濞存岸宕戦崱娑栤偓鍛存倻閼恒儳鍘撻梺鍛婄箓鐎氼參宕冲ú顏呯厓闂佸灝顑呴悘鎾煛鐏炲墽娲撮柡浣稿€婚幏鐘诲箵閹烘埈鍔€闂傚倷娴囬妴鈧柛瀣尭闇夐柣鎾虫捣閹界娀鏌ｉ幘瀛樼闁哄苯绉瑰畷顐﹀礋椤愮喎浜剧紓浣股戝▍鐘绘⒒閸喓鈻撻柡鈧禒瀣叆婵炴垶锚椤忣亪鏌￠崱鈺佸闁逞屽墲椤煤濠婂牆绐楅柡宥庡幑閳ь兛绀侀埥澶婎潨閸℃ê鍏婂┑鈩冨絻閺堫剟鎮ч弴銏犵柧妞ゅ繐鐗婇埛鎺懨归敐鍫燁棄闁告氨鎳撻埞鎴︻敊閽樺濮㈤梺瀹狀嚙缁夊綊寮幇顓炵窞濠电姴瀚哥槐鐢告⒒娓氣偓濞佳囨偋閸℃蛋鍥ㄥ閺夋垹锛欓柣鐘靛劋娴滀粙鍩€椤掍礁绗掓い顐ｇ箞閺佹劙宕ㄩ鈧ˉ姘攽閻樻剚鍟忛柛鐘崇墵閺佸啴濡搁妷銏＄€洪梺鎸庣箓濞诧箓锝為弴銏＄厵闁绘垶锚濞堥箖鏌ｉ弮鍥ㄣ€冮柣鎺戯躬閺屸€愁吋鎼达絽甯ㄧ紓浣介哺閻熲晛顫忔繝姘＜婵炲棙甯掗崢鈥愁渻閵堝骸骞栭柣妤佹崌瀵粯绻濋崶銊︽珳闂佸憡绮堥懗鍫曞礉閻戣姤鍋℃繝濠傚椤ュ牓鏌℃担鐟板闁诡喗鐟╁畷婊勬媴閻戞ɑ绶梻鍌欑閹碱偄煤閵婏附鍙忛柣鎴ｅГ閺咁剚绻濇繝鍌氭殜闁衡偓娴犲鐓冮柦妯侯槹椤ユ粓鏌ｈ箛瀣姕闁靛洤瀚板鎾幢濡や胶銈╅梺杞版缁舵岸寮婚悢鐓庣鐟滃繒鏁☉銏＄厓闂佸灝顑呴悘鎾煛鐏炶鈧牠骞堥妸鈺佺疀妞ゆ垼妫勬禍楣冩煛閸ャ儱鐏╅柛鎴犲█閺岀喓鈧稒顭囩粻銉╂煟閺傛寧顥㈤柡宀嬬秮閹垽宕崟鍨瘔婵＄偑鍊戦崕铏叏妞嬪孩顫曢柟鐑橆殢閺佸﹦鐥鐘崇効闁告凹鍋婂娲传閸曨噮娼堕梺鍛婃煥闁帮綁宕洪埀顒併亜閹烘埊鍔熺紒澶屾暬閺屾盯骞樼€靛憡鍒涢梺璇″灟缁舵艾鐣锋總绋课ㄩ柨鏃囶潐鐎氫粙姊绘担渚劸闁哄牜鍓欓～婵嬪Ω閿旇姤鐝峰┑鐐村灦濮樸劎澹曟總鍛婂€甸柨婵嗛娴滄粓鏌ｈ箛鏃€灏﹂柡灞剧洴閸╃偤骞嗚婢规洖鈹戦敍鍕杭闁稿﹥鐗滈弫顕€骞掑Δ鈧壕鍦喐閻楀牆绗掗柛姘秺閺屽秷顧侀柛鎾寸懇閳ユ棃宕橀鍢壯囧箹缁厜鍋撻懠顒傛晨缂傚倸鍊烽懗鍓佸垝椤栫偞鏅濋柕蹇嬪€楀畵浣糕攽閻樺弶澶勯柡鍛倐閺岋絽螣閸濆嫭顥濋悷婊勬瀵鈽夊Ο閿嬵潔闂佸憡顨堥崑娑氱不缂佹绠鹃悗娑欘焽閻棝鏌涘Δ鈧崯鍧楋綖韫囨洜纾兼俊顖濐嚙椤庢挾绱撴担鍓插剱閻庣瑳鍐冩帡骞囬悧鍫氭嫼闂侀潻瀵岄崢鎼佸箯閿熺姵鐓曢悗锝庝悍瀹搞儵鏌ｉ敐鍥у幋妞ゃ垺鐩幃娆撳级閹存粍鐫忛梻浣藉吹婵潙煤閳哄啩鐒婃繛鍡樻尰閺咁剚绻涢幋娆忕仾闁抽攱鍨块弻娑㈡晜鐠囨彃绠规繛瀛樼矒缁犳牠寮婚敍鍕ㄥ亾閿濆骸澧悽顖氱埣瀹曪繝鏌嗗鍡欏幈濡炪倖鍔戦崐鏇㈠几閺冨倻纾奸柣妯垮吹閻ｆ椽鏌＄仦鍓р槈妞ゎ厹鍔戦崺鈧い鎺戝€婚惌鍡椕归敐鍛棌闁搞倖娲熼弻鐔碱敍閿濆洣姹楅梺鑽ゅ枛閸嬪﹪鎮￠妷鈺傜厱婵炴垵宕獮鎺旂磼椤旇偐鍩ｆ慨濠呮閳ь剙婀辨刊顓㈠吹濞嗘挻鈷戦悽顖ｅ枤缁嬪鏌熸笟鍨闁糕斁鍋撳銈嗗笒鐎氼參鎮¤箛娑欑厱妞ゆ劧绲跨粻鏍ㄣ亜閵夛妇鐭掗柡灞界Х椤т線鏌涢幘瀵告创鐎规洘顨呴～婊堝焵椤掆偓椤曪絾绻濆顓熸珳婵犮垼娉涢敃锕傤敇濞差亝鈷戠紓浣姑悘銉︿繆椤愶絿娲寸€规洘绻堥幃婊堟嚍閵夈垺瀚奸梻浣告啞缁嬫垿鈥﹂銏″殌闁割煈鍟旈悷閭︾叆闁糕剝顭囬妴鎰渻閵堝骸浜滅紒缁樺姉閸欏懎顪冮妶鍛閻庢凹浜炲Σ鎰板醇閺囩啿鎷洪梺鍛婄☉閿曘儲寰勯崟顖涚厱闁规儳顕幊鍥┾偓瑙勬礃閸ㄧ敻顢橀崗鐓庣窞閻庯急鍕伖闂傚倷绀侀幉锛勭矙閹达附鏅濋柕澶嗘櫆閸嬪倿鏌曟径鍡樻珕闁绘挾鍠愰妵鍕箻鐠鸿桨绮堕梺閫炲苯澧繛纭风節閻涱噣宕橀埡渚囧殼闂佸湱鈷堥崢浠嬪疾閳哄懏鈷戦柟鑲╁仜閻忊晜銇勯敂鑺ョ凡閾荤偤鏌涢幇鈺佸闁哄棴绠撻弻鏇熺箾閻愵剚鐝﹂梺杞扮閿曨亪寮婚悢纰辨晬闁糕剝顨呴弳鐔兼煟閵堝懎顏慨濠傤煼瀹曟帒顫濋钘変壕濡炲娴烽惌鍡椼€掑锝呬壕闂佽鍠栧鈥崇暦閹偊妾ㄥ┑鐐茬摠閻楃娀寮婚弴鐔虹鐟滃秹骞婇幇鐗堝€块柛蹇氬亹缁犻箖鏌熼悙顒佺稇闁绘帒缍婇弻娑氣偓锝庡亝瀹曞矂鏌＄仦鍓ф创闁糕晝鍋ら獮鍡氼槺濠㈣娲栭埞鎴︽晬閸曨偂鏉梺绋匡攻閻楁洟顢欒箛鏃傜瘈婵﹩鍓涢敍娑㈡⒑鐟欏嫬鍔ゆい鏇ㄥ幘缁宕滆濡垱銇勯幘鍗炵労婵☆偅鍨圭槐鎺楀煢閳ь剟宕戦幘缁樷拻濞达綀娅ｇ敮娑樸€掑顓ф疁鐎规洘濞婇弫鎰板川椤栨稒顔曟繝娈垮枟閵囨盯宕戦幘鏂ユ斀闁炽儴娅曢崯鐐烘煙椤栨稒顥堝┑顔瑰亾闂佸疇妫勫Λ娆撍夐崼銉︾厽閹兼番鍊ゅ鎰箾閹绘帞绠荤€规洘绻堥獮瀣晜鐞涒€充壕濞达絽澹婂銊╂煃瑜滈崜鐔肩嵁閸愵喖顫呴柍钘夋鏁堥梺鍦帶閻°劎绮欓幋鐐殿浄闁宠桨璁查弨浠嬫煟濡椿鍟忛柡鍡樼矌缁辨帗娼忛妸锔绢槹閻庤娲橀崹鍧楃嵁鐎ｎ喗鏅濋柍褜鍓涙竟鏇°亹閹烘挾鍘搁悗骞垮劚妤犳悂鐛弽顐ょ＜闁绘娅曠欢鏌ユ懚閺嶎厽鐓ユ繝闈涙閸ｅ綊鏌￠崱妯兼噮闁汇儺浜畷婊嗩槾閻㈩垱绋戣彁闁搞儜宥堝惈濡炪們鍨虹粙鎴︹€﹂妸鈺佺闁靛鍊楃敮娑㈡⒒閸屾瑧鍔嶉柟顔肩埣瀹曟繂顓奸崶銊ュ簥闂佸憡娲﹂崹鎵不閻斿吋鐓欓梻鍌氼嚟椤︼附淇婇锛╂垹鎹㈠☉銏犲耿婵炲棗绻嬫竟鏇犵磽閸屾氨孝濡ょ姵鎮傞崺鐐哄箣閿旇棄鈧兘鏌涘▎蹇ｆТ闁哄鐟︾换娑氣偓娑欘焽閻绱掗鑲┬ら柍褜鍓熷褔濡堕幖浣哥畺闁冲搫鍟扮壕鍏间繆椤栨粌甯堕悽顖涘劤閳规垿鎮╅鑲╀紘濠电偛顦伴惄顖炲箖瑜斿畷鍗炩槈濡⒈妲锋繝娈垮枟閿曗晠宕滈敃鍌涘亜闁糕剝绋掗悡鐔兼煟閺冨倸甯跺ù婊呭娣囧﹪顢涘Δ鈧禍鎯р攽閻樻剚鍟忛柛鐘崇墵閺佸啴濡烽妷顔藉瘜闂佽姤锚椤﹂亶寮抽敃鍌涚厪濠电姴绻愰々顒傜磼閳锯偓閸嬫捇姊绘担鍛婂暈闁告梹鍨垮畷婵嗩吋閸涱亝鐏佸銈嗗姧闂勫嫰鍩涢幒鎳ㄥ綊鏁愰崨顔兼殘闂佺灏欓…鍫ュ煘閹达富鏁婇柣鎰靛墯濮ｅ牓姊虹拠鈥虫殭闁搞儯鍔屾禍鍦磽閸屾瑧鍔嶉柨姘归悩鍐茬瑨妞ゎ亜鍟存俊鍫曞幢濡》绱╅梻浣侯焾椤戝棝骞愭ィ鍐ㄧ劦妞ゆ帒鍠氬鎰箾閸欏澧柣锝囧厴椤㈡宕橀鍐兒濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柟缁㈠枛绾惧湱鎲搁悧鍫濈瑨缁炬崘顫夐妵鍕冀椤愵澀娌梺鎶芥敱鐢帡婀侀梺鎸庣箓閻楀﹪顢旈悩缁樼厪闁糕剝顨愰煬顒勬煛鐏炲墽娲存鐐搭焽閳ь剟娼ч幗婊堟偪閸曨垱鈷戦弶鐐村椤︼附銇勯幋婵囧殗闁炽儲妫冨畷姗€顢欓崲澹洦鐓曟繛鎴濆船瀵箖鏌涢弬娆炬█婵﹥妞藉畷鐑筋敇閻旈攱鐣繝鐢靛仜閻即宕愬┑瀣櫜闁绘劕澧庨悿鈧┑鐐村灦閻熴儵鍩€椤掑倻甯涘ǎ鍥э躬椤㈡稑鈻庨幒婵嗗Τ闂備焦鎮堕崐鎴﹀磹閺囥垹鐓橀柟杈鹃檮閸婄兘鏌涘▎蹇ｆ▓婵☆偓绻濆娲箹閻愭彃顬嬮梺杞版祰椤曆囨偩閻戣棄浼犻柛鏇ㄥ幗濞堟洟姊洪崨濠冨闁稿繑锕㈤獮蹇涘传閸曘劍鏂€闂佺粯鍔樺▔娑㈡嫊閸忕浜滈柡鍥ф鐎氼厼鈻嶉悩缁樼厵缂備焦锚娣囶垶鏌ｉ弬鎸庮棦闁哄矉缍侀幃銏㈢矙濞嗙偓顥嬪┑鐘媰瀹ュ洨鏆犻梺瀹狀潐閸ㄥ潡寮澶婄妞ゆ帊鐒﹂惁鎾翠繆閵堝洤啸闁稿绋戠叅妞ゆ搩娼块埀顑跨铻ｅ〒姘煎灣閸欏棝姊洪崨濠傚闁告侗鍘煎В鍫ユ⒒閸屾艾鈧悂宕愭搴ｇ焼濞撴埃鍋撴鐐差樀閺佹捇鎮╅懠顒夋Х闂傚鍋勫ú锔剧矙閹存惊娑樜熼幁鎺嗗亾閹烘埈娼╅柨婵嗘噸婢规洘淇婇妶鍥ラ柛瀣〒閹广垹顫滈埀顒勭嵁閸愵煈鐓ラ柛蹇撳⒔閸犳牠骞婇弽顓炵厸濠电姴鍊瑰▍妤呮⒒閸屾艾鈧绮堟笟鈧獮鏍敃浣嶉崶銊ヮ嚤闁哄鍨甸悗顓㈡⒑濮瑰洤鐏い顓炵墢缁寮介鐔哄幍闁哄鐗撶粻鏍ь瀶椤曗偓閺岋綁骞樼捄鐑樼亪闂佸搫鐭夌紞浣割嚕椤曗偓閸┾偓妞ゆ帒鍊瑰畷鏌ユ煕鐏炵虎鍤旀繛宸簻鍥撮梺鎼炲劗閺呮繈鎮炴總鍛娾拺缂侇垱娲栨晶鑼磼鐎ｎ偄娴柟顔光偓鏂ユ婵妫涢崬鐢告煟閻樼儤顏犻悘蹇嬪姂瀹曟繈鎮㈤崨濠傚伎濠碘槅鍨抽…鍫熸叏閸岀偞鐓涚€光偓鐎ｎ剛鐦堥梺绯曟杹閸嬫挸顪冮妶鍡楃瑐闁煎啿鐖奸妴鍛存倻閼恒儱鈧敻鏌ㄥ┑鍡涱€楀ù婊呭仱閺屾稑顫滈埀顒佺閸洖钃熼柨婵嗙墢閻も偓闂佸搫娲ㄩ崑妯煎垝閼哥數绡€闁冲皝鍋撻柛灞剧矌閻撴捇姊虹化鏇熸珔闁挎洦浜滈锝夊箻椤旂⒈娼婇梺鎸庣☉鐎氼剛鏁Δ鍛拻闁稿本鐟чˇ锕傛煟韫囨梻绠炴い銏＄墵瀹曘劑顢涘鍛殽闁荤喐绮岀换鎺懳ｉ幇鏉跨闁规儳顕粔鍫曟⒑闂堟侗鐒鹃柛搴ゅ皺閹风娀鎮欏顔藉瘜闂侀潧鐗嗛崯顐︽倶椤忓棌鍋撻崗澶婁壕缂備礁顑堝▔鏇㈠汲閿曞倹鐓忓┑鐐靛亾濞呮捇鏌℃担鍛婂枠闁哄矉缍侀獮鍥敊閼恒儲鐦庢繝鐢靛仧閸樠囁囬棃娑辨綎闁惧繗顫夌€氭岸鏌涘▎蹇ｆЦ闁衡偓椤撶儐娓婚柕鍫濋娴滄粍銇勯敂璇茬仯闁告瑥鎳庨埞鎴﹀煡閸℃浠╅梺鍛婅壘椤戝顕ｉ崘宸叆闁割偆鍠撻崣鍡涙⒑缂佹ɑ鐓ラ柟纰卞亜閻☆厾绱撻崒娆掑厡濠殿喚鏁婚幃褍螖閸愨晛搴婂┑鐐村灟閸ㄥ綊鐛姀鈥茬箚妞ゆ牗绻嶉崵娆戠棯閺夎法效婵?")
        if recent_wins:
            if localized_recent_win:
                lines.append("")
            else:
                lines.append("婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽弫鎰板川閸屾粌鏋庨柍璇查叄楠炲棜顦虫い鏂垮缁辨捇宕掑▎鎺戝帯婵犳鍠楅幐鎶藉箖濡警娼╅悹杞扮秿閿曞倹鐓曢柡鍥ュ妼閺嬨倝鏌ｉ妶鍌氫壕闂傚倷绀佸﹢閬嶅磻閹捐绠氶悘鐐跺▏濞戙垺鍊烽柣銏㈡暩閿涙繃绻涙潏鍓ф偧闁哄拋鍋婂畷濂割敂閸喓鍘辨繝鐢靛Т閸熸壆绮婚悙纰樺亾濞堝灝鏋涙い顓犲厴楠炲啴濮€閵堝棙鍎梺闈╁瘜閸橀箖宕㈤鐐粹拻濞达絿顭堥ˉ蹇涙煟閹惧磭澧︾€规洘濞婇、姘跺焵椤掆偓閻ｅ嘲鈹戦崶褏绐為梺褰掑亰閸樻悂骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囶亞鐣垫鐐诧躬瀹曟﹢顢旈崱娆欑床缂傚倸鍊烽悞锕傚煟閵堝鏁傞柛顐墰缁嬪繘妫呴銏″婵﹨宕靛褔鍩€椤掆偓閳规垿顢欓弬銈勭返闂佸憡鎸鹃崰鏍х暦椤掑嫬閱囬柡鍥╁暱閹疯櫣绱撻崒娆戝妽閽冭鲸銇勯妷銉︻棦闁哄本娲熷畷杈疀閹炬彃顥氭繝鐢靛Х椤ｈ棄危閸涙潙纾诲〒姘ｅ亾鐎规洘绻堥獮瀣攽閹邦厾绋佹繝鐢靛仜濡﹥绂嶅┑瀣€垮┑鐘崇閻撶喖鏌熼柇锕€鐏犻柦鍕偢閹顫濋鐔哄嚒濡炪値鍙€閸庡篓娓氣偓閺屾盯濡搁妷褍鐓熷Δ鐘靛仜閸燁垳绮嬮幒鏂哄亾閿濆懐浠涢柡鍜佸墴濮婃椽妫冨☉姘暫濠电偛鐪伴崝鎴﹀箚娓氣偓瀹曠厧顭块鍛棃闁诡喒鏅犲Λ鍐ㄢ槈濡ゅ啯宕熼梻鍌欑劍鐎笛兠鸿箛娑樼９婵犻潧顑呴悘鎶芥煥閺囩偛鈧憡鍎梻浣哥枃濡椼劎娆㈠璺鸿埞閻犻缚銆€閺€浠嬫煟濡偐甯涙繛鎳峰嫪绻嗘い鎰剁悼濞叉挳鏌涢埞鎯т壕婵＄偑鍊栫敮鎺椝囬鐐靛祦闁哄秲鍔婃禍婊勩亜韫囨挸顏╅柡鍡到閳规垿鍨惧畷鍥х厽閻庤娲栧畷顒冪亙闂侀€炲苯澧撮柨婵堝仱瀹曘劎鈧稒菤閹锋椽姊洪崨濠勨槈闁挎洏鍎虫禍鎼佸箥椤斿墽锛滈柣鐘叉穿鐏忔瑦鏅堕弴銏＄厽闁挎繂娲ら崢瀛樸亜閵忊槅娈曢柟宄版嚇瀹曨偊濡疯瀹撲線姊婚崒娆戭槮缂傚秴锕畷鎴炵節閸パ冨亶闂佸綊妫跨粈浣虹不椤栨粎纾藉ù锝堫嚃閻掔晫绱掗悩鑽ょ暫鐎殿喖鐖煎畷鐓庘攽閸″繑瀵栭梻浣筋嚃閸犳牠濡堕幖浣歌摕婵炴垶鐟﹂崕鐔哥箾閹寸們姘跺磻閹炬枼鏀介柛鈩冪懄濞堥箖姊哄Ч鍥х伄妞ゎ厼鐗撻幃鐐哄垂椤愮姳绨婚梺鍦劋閸ㄧ敻顢旈鍫熺厓闂佸灝顑呴悘鎾煙椤旂瓔娈滈柟顖氬€块獮鏍ㄦ媴鐠団檧鍋撳鍛斀闁绘﹩鍠栭悘顏堟嫅閸楃們搴ㄥ炊瑜濋煬顒傗偓瑙勬礈椤牐鐏冩繛杈剧到閹碱偊鐛鍡曠箚闁靛牆娲ゅ暩闂佺顑嗛惄顖炲箖濡　鏀介悗锝庡亜閳ь剙鐖奸弻銈囧枈閸楃偛骞嬮梺绋款儐閹搁箖骞夐幘顔肩妞ゆ帒鍋嗗Σ浼存⒑濮瑰洤鐒洪柛銊ф櫕閹广垹鈹戠€ｎ剙绁﹂梺鍛婂姂閸斿寮告惔銊︾厵闁诡垎鍜冪礊濡炪倖鏌ㄩ惌鍌氼潖濞差亜鎹舵い鎾跺仜婵℃椽姊洪悷鐗堝暈闁诡喖鍊搁悾宄扳攽鐎ｎ亞顔婂┑掳鍊撶拋鏌ュ箯婵犳碍鈷戠紒瀣濠€浼存煟閻旀繂娉氶崶顒佹櫆闁伙絽鐬奸惁鍫ユ⒑闁偛鑻晶鎾煛鐏炶姤顥滄い鎾炽偢瀹曘劑顢涢妶鍥ф優闂傚倸鍊风欢姘焽瑜旈幃褔宕卞☉妯碱唵闁诲函缍嗘禍鍫曟倿娴犲鐓涚€广儱楠搁獮妤呮煟閹捐泛孝闁宠鍨块、娆撴寠婢跺娼撻梻渚€鈧偛鑻晶顖涚箾閼碱剙鏋欐俊顐犲灩閳规垿顢欑粵瀣姼闂佺硶鏅滈悧鐘诲箖閿熺姴顫呴柍銉ㄥ皺缁犳艾顪冮妶鍡欏闁荤喆鍔戦、妤呮偄闂€鎰畾濡炪倖鍔﹂崜娆撱€呴鍕厵闁告瑥顦伴崐鎰版煙椤斻劌娲ら柋鍥ㄧ節闂堟稓澧㈤柟铏墵濮婄粯鎷呴崨濠冨創闂佺懓鍟跨换姗€骞冮敓鐘虫櫢闁绘灏幗鏇炩攽閻愭潙鐏﹂懣銈嗕繆閹绘帞澧﹂柡灞剧☉铻栭柛鎰╁妺濞岊亪姊虹拠鑼缂佸鎳撻～蹇撁洪鍕炊闂侀潧顦崕娑㈡晲婢跺鍘遍梺鍝勫暊閸嬫挻銇勯妸銉у閸楅亶鏌熼悧鍫熺凡缂佺姴顭烽幃妤€鈽夊▍顓т邯椤㈡捇骞樼紒妯锋嫼闂佸憡绋戦敃锔剧不閹剧粯鍊垫慨姗嗗墯閸ゅ洭鏌℃担鐟板鐎规洦浜濋幏鍛村传閸曨剚姣勯梻鍌氬€峰ù鍥х暦閻㈢绐楅柟鎯х摠濞呯姵淇婇妶鍛劙濠㈣埖鍔栭崑鎰版煕韫囨挻鍣界紒鐘冲哺濮婃椽宕ㄦ繝鍕櫑濡炪倧瀵岄崹閬嶅箞閵娿儺鍚嬮柛鈾€鏅滈鏃堟⒑缂佹ê濮堟繛鍏肩懃闇夋い鏃傜摂濞堜粙鏌ｉ幇顓熷剹闁绘帊绮欓弻宥堫檨闁告挾鍠庨…鍥樄妤犵偞顨呴…銊╁幢濡炶浜鹃柟缁㈠枟閳锋帡鏌涚仦鎹愬闁逞屽墴椤ユ挸鈻庨姀鐙€娼╂い鎺戭槺閸旂兘鎮峰鍕棃闁搞劑绠栭弫鍐磼濮樿泛鏁归梻渚€娼чˇ顓㈠磿閹惰姤鏅柣鏂垮悑閳锋垿鏌熼鍡楀椤╀即姊虹粙娆惧剰婵☆偅绻堟俊鎾川鐎涙ê鈧鏌ら幁鎺戝姢闁告鏁诲濠氬磼濮橆兘鍋撻幖渚囨晪妞ゆ挶鍨圭粈澶屸偓骞垮劚椤︿即鎮￠崘顔解拺闁割煈鍣崕蹇涙煟韫囨挾鎽犻柟渚垮妽缁绘繈宕橀埞澶歌檸婵＄偑鍊戦崹鍝劽洪悢鐓庢瀬闁圭増婢橀悙濠囨煏婢跺牆鐏╁ù婊堢畺閺岀喖鎮滃鍡樼暦闂佺粯鎸搁崯鎾箖瀹勬壋鏋庨煫鍥ㄦ惄娴犵厧鈹戦悙瀛樺剹闁革綇缍佸濠氭晬閸曨亝鍕冮梺鍛婃寙閸曨偄鐏￠梺璇插椤旀牠宕抽鈧畷婊堟偄妞嬪孩娈剧紓浣割儓椤曟娊寮崼婵堝姦濡炪倖宸婚崑鎾淬亜閺囶亞绋婚悗浣冨亹閳ь剚绋掕彜闁圭柉娅ｇ槐鎾寸瑹閸パ呬画濠电偛寮堕敃銏狀嚕閹埇浜归柟鐑樻尵閸橀亶鏌ｆ惔顖滅У闁稿鎳愭禍鎼侇敇閻旂繝绨诲銈呯箰鐎氼剟寮抽敐鍛斀闁炽儱纾崺锝団偓瑙勬礀瀹曨剝鐏冮梺鍛婂姦娴滄繈宕抽鐐粹拻闁稿本鐟ч崝宥夋倵缁楁稑鍘惧ú顏勭厸闁稿本鐟х粻姘舵⒑閹肩偛鍔楅柡鍛洴瀹曠懓鈹戠€ｎ偆鍘搁梺鍛婂姂閸斿孩鏅跺☉娆嶄簻闁靛鍎虫晶娑氱磼缂佹鈽夐懣鎰亜閹哄棗浜鹃梺璇叉禋閸ｏ綁寮婚悢鍏兼優妞ゆ劧绲界壕鎶芥⒑閻愯棄鍔电紒鐘虫尰娣囧﹪骞栨担鍝ュ幐婵炶揪绲肩拃锕€危鐟欏嫪绻嗛柣鎰典簻閳ь剚鐗犻獮鎰版倷椤掍礁寮块梺缁樺灱濡嫰宕掗妸鈺傜厵闁绘垶锕╁▓鏇㈡煃闁垮绗掗棁澶愭煥濠靛棛澧曠悮姘舵⒑闂堟稒顥滈柛鐔稿濡叉劙骞掗弮鈧刊濂告煕閿旇骞橀柣锕€鐗撻幃妤冩喆閸曨剛顦ㄦ繝鐢靛仜閿曨亜顕ｉ锕€绠涢柡澶婄仢閼板潡姊洪崫鍕窛濠殿喚鍏橀幃鐐偅閸愨斁鎷绘繛杈剧秬濞咃絿鏁☉銏＄厱闁靛ě鍐ㄤ粯闁捐崵鍋ら弻娑㈠即閵娿儳浠梺绋款儏閸婂湱鎹㈠☉銏犵婵炲棗绻掓禒楣冩⒑缂佹ɑ灏版繛鑼枛楠炲啫顫滈埀顒勫箖濞嗘挸绠甸柟鍝勬鐎垫牠姊绘担瑙勩仧闁告ê銈搁弫鍐Ψ閳瑰簱鍋撻崘顔嘉ㄩ柍鍝勫€搁埀顒傚厴閺屻倗鍠婇崡鐐插О閻熸粌閰ｉ獮鍫ュΩ閿斿墽鐦堥梺鍛婃处閸樿偐绮敓鐘斥拺闁荤喐婢樺Σ濠氭煙閾忣偄濮夐柛鎺撳笒閳诲氦绠涙繝鍐偓濠氭⒑缂佹ê濮﹂柛鎿勭畱铻為煫鍥ㄧ⊕閳锋帡鏌涚仦鍓ф噯闁稿繐鐬肩槐鎺楊敋閸涱厾浠稿Δ鐘靛仦閸旀瑩鐛弽銊﹀闁荤喖顣︾純鏇㈡⒒娴ｇ瓔娼愰柛搴＄－婢规洟顢橀姀鐘宠緢闂佹寧娲栭崐褰掓偂濞嗘挸绾ч柛顐ｇ箓閳锋棃鏌ｉ敐鍫滃惈缂佽鲸甯￠崺鈧い鎺戝€甸崑鎾绘晲鎼粹€茬按婵炲瓨绮嶇划鎾诲蓟閳ユ剚鍚嬮柛鎰╁妼椤姊哄Ч鍥у闁搞劌鐖兼俊鐢稿礋椤栨稒娅嗛柣鐘叉搐瀵爼鎮靛┑鍡忔斀妞ゆ梻銆嬮弨缁樹繆閻愯埖顥夐摶鐐烘煕閹扳晛濡锋俊鎻掔墛閹便劌顫滈崱妤€鈷掗梺鍝勬－閸嬪懐鎹㈠┑鍫濇瀳婵☆垱妞垮鎴︽⒑缁嬫鍎忛悗姘煎櫍閸┾偓妞ゆ帊鑳堕埢鎾绘煛閸涱喚绠橀柛鎺撳笧閳ь剨缍嗘禍鍫曞触鐎ｎ喗鐓曟繝濞惧亾闁煎啿鐖煎畷锝夊幢濞戞瑢鎷洪梺鍛婃尰瑜板啯绂嶉悙鐑樼厱闁绘娅曞畷宀€鈧娲忛崹浠嬬嵁閺嶃劍濯撮柛蹇擃槹鐎氬ジ姊绘担渚敯闁稿鍔欏畷鎴濃槈閵忕姷顦┑顔姐仜閸嬫捇鏌＄仦鍓р姇闁诡垱妫冩俊鑸靛緞婵犲啯鍤堟繝鐢靛剳缁茶棄煤閵堝鏅濇い蹇撳閺嗭附淇婇妶鍛櫤闁搞倕鍟撮弻宥夊传閸曨偅鐏撻梺鍝ュ枎闁帮絽顫忕紒妯诲闁告稑锕ら弳鍫熺箾閹惧顣叉い銊ワ工閻ｇ兘濮€閵堝懐顔夐梺褰掑亰閸忔﹢宕戦幘璇茬妞ゆ棁袙閹风粯绻涢幘鏉戠劰闁稿鎹囬弻宥堫檨闁告挻鐩畷鎴濃槈閵忊€虫濡炪倖鐗楃粙鎺戔枍閻樼偨浜滈柡宥冨妿閳笺倕霉濠婂嫮鐭掗柡宀嬬節瀹曟﹢鏁愰崨顒€顥氶梻鍌欒兌缁垶銆冮崼鐔稿弿闁圭虎鍠楅崑鈺呮煟閹达絾顥夌紒鐙€鍠氱槐鎺戔槈濮楀棗鍓遍梺鍝勬媼娴滎亜顫忓ú顏呯劵闁绘劘灏€氭澘顭胯閸ｏ綁寮婚敐澶嬫櫜闁告侗鍘戒簺婵＄偑鍊ら崢褰掑礉閹存繄鏆﹀┑鍌氭啞閸嬪嫰鏌у顒€鈧鎯勬惔銏㈢瘈缁炬澘顦辩壕鍧楁煕鐎ｎ偆娲存い銏＄墵瀹曘劑顢涘Δ鈧禍鐐箾閹寸偛绗氭繛鍛嚇閺屽秶绱掑Ο璇查瀺闂侀潧鐗炵紞浣哥暦濮椻偓閸╃偤鎮欓鈧褰掓⒒閸屾瑧顦﹂柟璇х節楠炴劙寮拌箛瀣╂睏闂佸憡鍔忛弲婵嬨€呴崣澶岀瘈闂傚牊绋掑婵堢磼閻樿崵鐣洪柡灞剧☉閳诲氦绠涢敐鍡┾偓鍡涙⒑閸忕厧顎滄繛澶嬫礋閸┾偓妞ゆ帊绶￠崯蹇涙煕閻樻剚娈欓柕鍥ㄥ姍瀹曟﹢顢欓崗澶婁壕闁挎洖鍊告儫闂佸疇妗ㄧ粈浣虹玻濞戞﹩娓婚柕鍫濇婢ь剛绱掗鍡欐偧婵″弶鍔欏畷锝嗗緞瀹€鈧惁鍫ユ⒑濮瑰洤鐏叉繛浣冲嫮顩烽柨鏇炲€归悡鏇㈡煏婵炲灝鍔ら柛鈺嬬秮閺屸剝鎷呯粙鎸庢闂佺硶鏅换婵嗙暦閵娾晩鏁囬柣娆忔噽閸氬綊姊婚崒姘肩叕闁稿瀚叅闁挎洖鍊哥粻顖炴倵閿濆骸骞戝ù婊冪秺閺岀喖鎮滃Ο璇茬婵炲瓨绮岀紞濠傤潖濞差亜绠氱憸搴ｇ矉鐎ｎ喗鐓曢悗锝傛櫇閸斿秶绱掗崒娑樻诞濠殿喒鍋撻梺缁橈供閸嬪懘寮埀顒佷繆閻愵亜鈧牕顫忔繝姘ラ悗锝庡枛缁€澶愭煟閺冨洦顏犵痪鎯у悑閵囧嫰寮撮悙鏉戞闂佽楠忛梽鍕€冮妷鈺傚€烽柤纰卞墰椤旀帡鎮楃憴鍕８闁告梹鍨甸锝夊醇閺囩偟顓哄┑鐘绘涧閻楀繐鐣烽悜妯肩瘈闁汇垽娼у暩闂佽桨绀侀幉锟犲箞閵娾晛绠绘い鏃囧亹閿涙瑩姊洪懡銈呮瀾濠㈢懓顑夊鎼佸籍閳ь剚绌辨繝鍥舵晬婵犻潧妫斿Ч妤冪磼閹冪稏缂侇喗鐟╁璇测槈濮橆偅鍕冮梺鍛婃寙閸曨偅鐝梻浣藉吹婵敻宕濋幒妤€纭€闁规儼妫勯拑鐔哥箾閹存瑥鐏柛瀣姉閳ь剝顫夊ú鏍洪妶澶婄厱鐎光偓閸曨兘鎷洪柣鐘叉礌閳ь剙纾禒鈺呮⒑濞茶骞栭柛濠冩倐閹箖鎮滈挊澶岊唺濠德板€撶粈渚€鍩€椤掑倸鍘撮柡灞诲€楅崰濠囧础閻愬樊娼鹃梻浣告惈濡棃宕￠幎钘夎摕闁挎繂妫欓崕鐔兼煃閵夈儱鏆遍弶鍫濇嚇濮婅櫣绮欏▎鎯у壉闂佸湱鎳撳ú顓烆嚕鐠囨祴妲堥柕蹇曞Т瀹撳棝姊洪棃娑辩劸闁稿孩澹嗛懞杈ㄧ鐎ｎ偀鎷洪梺鍦焾濞寸兘鍩婇弴鐘电＜妞ゆ棁濮ょ亸顓熴亜椤愩垻绠婚柟鐓庣秺瀹曠兘顢橀悪鍛簥濠电姷顣藉Σ鍛村垂娴兼潙绠规い鎰惰缂嶆牠鏌熸潏楣冩闁绘挾鍠栭悡顐﹀炊閵婏箑鏆楃紓浣哄У閻擄繝寮婚敐澶嬪亜闁告瑥顦伴悵姘舵⒑闂堟稒顥欑紒鈧笟鈧崺銏℃償閵娿儳顔掗悗瑙勬礀濞村倿宕ラ崨瀛樷拻濞达絿鎳撻婊勪繆椤愨剝绁版い锝夌畺濮婇缚銇愰幒鎾存殸濠碉紕鍋犲Λ鍕綖韫囨稒鎯為柛锔诲幘閻撴捇鏌ｉ悩鍏呰埅闁告柨閰ｉ、娆撳箣閿旇В鎷虹紓浣割儐椤戞瑩宕曢幇鐗堢厱闁哄啠鍋撻柣鐕傞檮缁岃鲸绻濋崶褔鍞堕梺鍝勬川閸嬬喖顢欓幒鎴富闁靛牆妫欓埛鎺楁煛閸滀礁浜扮€规洏鍨介獮鏍ㄦ媴閸忓瀚奸梻浣告啞缁嬫垿鏁冮敐鍥偨闂侇剙绉甸悡鏇㈡煟濡搫鏆遍柛婵囨そ閺岀喖顢涘顓熸嫳缂備胶绮换鍫濈暦閸洖惟鐟滃秹鐛Δ鍛拻濞达絿鎳撻婊呯磼鐠囨彃鈧儻妫熸繛鏉戝悑濞兼瑩寮告笟鈧鍫曞醇濮橆厽婢掗梺绋款儐閹瑰洤鐣疯ぐ鎺濇晝闁挎繂娲ら崵鎺楁⒑鐠囨彃顒㈤柛鎴濈秺瀹曟娊鏁愭径濠冩К闂侀€炲苯澧柕鍥у楠炴帡骞嬮姘潬缂傚倷妞掗懗鍫曞礂濮椻偓瀵鈽夐姀鐘愁棟濠电偛妫欓崕鎶藉礈閹惰姤鈷戝┑鍌氭憸缁辨澘顪冮弶鎴炴喐闁瑰箍鍨归埞鎴﹀幢閳哄倸鍏婃俊鐐€栭幐鑽ょ矙閹烘柡鍋撳顑惧仮婵﹦绮幏鍛村川婵犲倹娈樼紓鍌欐祰椤曆囧磹婵犳艾鐒垫い鎺嶇閸ゎ剟鏌涢悩宕囨创闁糕晛鎳撻妵鎰板箳閹绢垱瀚藉┑鐐舵彧缁蹭粙骞夐敓鐘茬柈闁绘劗鍎ら悡娑㈡倶閻愰鍤欏┑鈥虫健閺岀喖鐛崹顔句紙濡ょ姷鍋涢澶愬箖閳哄懏顥堟繛鎴烆焾琚濋梻鍌氬€烽懗鍓佸垝椤栫偛钃熼柕濞炬杺閳ь剙鍟幆鏃堝煡閸℃瑥濮洪梻渚€娼ц墝闁哄懏绮撻幃锟犲礃椤忓懎鏋戝┑鐘诧工閻楀棛绮堥崼銉︾厽闁哄倹顑欏▓鐘绘煕閵堝棙绀€闁宠鍨块幃鈺佺暦閸ヨ埖娈归梻浣告惈閹冲繘骞冮崒鐐茶摕闁挎繂鎲橀悢鐑樺珰闁肩⒈鍓涢妶椋庣磽閸屾瑧鍔嶉柛鏃€鐗滅划娆撳箣閿斿厜鍋撻弮鍫濈妞ゆ柨妲堣閺屾盯鍩勯崗锔藉哺楠炲繑绻濆顓涙嫼缂備礁顑嗛娆撳磿閹扮増鐓欓柣鐔哄閹兼劙鏌ｉ敐鍥у幋闁圭厧缍婇、鏇㈠閳轰焦顔撻梻浣筋嚙鐎涒晝绮欓幒鏇炵稊闂備礁缍婇弨鍗烆渻閽樺娼栨繛宸簻瀹告繂鈹戦悩鎻掝伀闁伙絿鏁婚弻锝嗘償閵忕姴姣堥梺鍛娒妶鎼佸极閸愵喖顫呴柍銉﹀墯閸ゃ倝鏌ｆ惔銏⑩姇妞ゎ厼娲畷銏＄鐎ｎ偀鎷洪梺鍛婂姇瀵爼骞嗛崼銉︾叆闁哄洦锚閳ь剚绻堥獮鍐潨閳ь剟骞冮埡鍛€烽柟瀛樺笧閻╁酣姊绘担鍛婃儓婵炴潙鍊圭粋宥夋倷閻㈢數鐓嬪銈嗘煥椤洘绂嶅鍫熺厪闊洤锕ラ～濠冪箾閸喓鐭岄柍褜鍓濋～澶娒哄Ο鍏兼殰闁圭儤顨呴悡鈥愁熆鐠哄ソ锟犳偄閸忕厧浜楅柟鍏肩暘閸斿矁銇愬▎鎾粹拻闁稿本鑹鹃埀顒佹倐瀹曟劖顦版惔锝囩劶婵炶揪缍佸濠氭嚀閸ф绾ч柛顐ｇ濞呭懘鏌涢妸锔剧畺闁靛洤瀚板浠嬪Ω瑜忛悡渚€姊洪崫鍕棡缂侇喗鎹囧璇差吋婢跺﹣绱堕梺鍛婃处閸撴瑥鈻嶉妶澶嬧拺缂佸灏呴崝鐔兼煛娴ｅ壊鐓肩€殿喖顭烽崺鍕礃閵娧呯嵁闂佽鍑界紞鍡樼閻愬顩查柛顐ｆ礃閳锋垿鎮跺☉鎺嗗亾閸忓懎顥氭繝鐢靛仜椤曨厽鎱ㄩ幘顕呮晞闁糕剝绋掗崑鍌炴煟閺傛寧鍟為柛娆忕箲娣囧﹪濡堕崒姘婵犵妲呴崑鍛淬€冮崱娆戠焿鐎广儱鎳夐弨浠嬫煕閳ュ磭绠查柡鍌楀亾濠碉紕鍋戦崐鏍偋濡ゅ懏鍋￠柕澶堝劤閺嗐倝鏌涢埄鍐姇闁绘挻鐩幃姗€鎮欓幓鎺嗘寖濠电偞褰冮顓㈠焵椤掍緡鍟忛柛鐘愁殜楠炴劙鎼归锛勭畾闂佸綊妫跨粈浣告暜闂備線娼ч敍蹇曚沪閼恒儲鐝ㄩ梻鍌氬€搁崐鎼佸磹閻戣姤鍤勯柛鎾茬閸ㄦ繃銇勯弽顐粶缂佺姳鍗抽弻鐔兼⒒鐎垫瓕绠為梺鎼炲労閸撴岸藟閸喓绠鹃柟杈剧秮閸濊櫣绱撳鍛村弰婵﹨娅ｇ槐鎺懳熼搹閫涙闂佽棄鍟畷顒勫煘閹达富鏁婇柣锝呯灱閻撳姊洪崫鍕伇闁哥姴閰ｉ崺銏ゅ箻鐠囨彃鐎銈嗘⒒閺咁偉銇愰娑氱瘈缁剧増菤閸嬫捇鎼归鐔哥亞闂備礁鎽滄慨闈涱潩閵娿儙锝夊箛閺夎法顔掗柣搴㈢⊕閿氭い搴㈡崌濮婃椽宕ㄦ繝鍐ㄧ閻庢鍠涢崺鏍疾閵夆晜鈷掗柛灞剧懆閸忓矂鏌熼搹顐ｅ磳妤犵偛顦甸崺鍕礃椤忓棭鍟庡┑鐘垫暩婵潙煤閵娿儳鏆ゅ〒姘ｅ亾闁哄本鐩獮鍥濞戞瑧浜紓鍌欒兌婵潧顫濋妸鈺佺疅闁告稑锕ょ欢鐐烘煙闁箑澧伴柛婵囶殕缁绘稓鈧數顭堝瓭濡炪倖鍨靛Λ婵嗙暦閹扮増鍋ㄩ柛娑橈功閸欏棗鈹戦悩缁樻锭婵☆偅鐩畷娆撳捶椤撶姷锛滈梺闈涱焾閸斿矁顣块梻渚€娼уú銈団偓姘嵆瀵偊宕掗悙韫炊闂佸憡娲﹂崑鎺楁倵閾忣偂绻嗛柣鎰典簻閳ь兙鍊栫粋宥咁煥閸繄鏌堥柣搴㈢⊕鐪夌紒璇叉閺屾盯顢曢敐鍡欘槬閻庣懓鎲＄换鍐Φ閸曨垰鍐€闁靛ě鍛幘闂備礁鎽滈崑鐘诲春閺嶎偅宕叉繝闈涚墕閺嬪牊淇婇娑欍仧婵炲吋鍨垮铏圭矙濞嗘儳鍓遍柣銏╁灙閳ь剙纾弳锕傛煥濠靛棭妲哥紒鈧崘顔界厪濠电倯鍐仾妞ゆ梹娲樻穱濠囨倷椤忓嫧鍋撻弽顓熷亱婵犲﹤鐗嗙壕缁樼箾閹存瑥鐏柛濠傚槻閳规垿鎮╅幓鎺撴婵炲瓨绮嶇划鎾诲蓟閻旂厧浼犻柛鏇ㄥ帨閵夛负浜滈柡鍌涱儥濡偓闂佸搫鐬奸崰鏍蓟閵娧€鍋撻敐搴′簴濞寸姰鍨归埞鎴︻敊绾攱鏁惧┑锛勫仒缁瑩鐛崘顔肩労闁告劏鏅涢崝鍛渻閵堝棙鈷掗柡鍜佸亞缁瑩骞囬悧鍫氭嫽婵炶揪绲肩拃锕傛倿妤ｅ啯鐓ラ柡鍥崝姘舵偂閵堝鐓涚€广儱楠搁獮妤呮煕鐎ｃ劌鈧牠濡甸崟顖氱閻犺櫣鍎ら悘浣虹磽娴ｅ弶顎嗛柛瀣崌濮婄粯鎷呴崷顓熻弴闂佹悶鍔忓Λ鍕€﹂崶顏嶆Ъ缂備礁鍊圭敮鎺椻€﹂妸鈺侀唶闁绘柨鎼獮妤佷繆閻愵亜鈧洜鎹㈤幇鏉跨柈妞ゆ劑鍨婚弳銈夋煕閳╁啰鎲块柛瀣尵閹叉挳宕熼鍌ゆО闂備礁鎲″鐟懊洪悢鐓庢槬闁绘劕鎼粻锝夋煟濮楀棗浜滃ù婊堢畺閺屻劌鈹戦崱娆忓毈缂備降鍔嬬划娆撳蓟閿濆鏅查柛娑卞枟閸庢捇姊虹€圭媭娼愰柛銊ユ健楠炲啫鈻庨幘宕囩厬婵犮垼娉涘Λ娆撴倶閸℃せ鏀介柣鎰皺閹界姷绱掗鑲┬ら柛鎺撳笒椤撳吋寰勬繝鍕剁吹婵＄偑鍊栭崝褔姊介崟顖氱厱闁圭儤鍨埀顒佸笒椤繈鏁愰崨顒€顥氬┑鐘垫暩閸嬫﹢宕犻悩璇茬倞濞达絽鎲￠崰妯汇亜閵忥紕娲撮柟顔界懇閹崇娀顢楁径瀣撶喖姊婚崒娆愵樂缂侀硸鍠氬濠冪鐎ｎ偄鍓堕梺鍏肩ゴ閺呮繈鎯岄崱妞绘斀闁绘ɑ褰冮埀顒€鐖奸崺鈧い鎺嶇缁楁帗銇勯锝囩疄闁轰焦鍔欏畷銊╊敆閳ь剟藟濮樿埖鈷掗柛灞剧懆閸忓瞼绱掗鍛仭缂佹鍠庤灃闁告侗鍘鹃悰銉モ攽椤旂瓔鐒炬繛澶嬬洴閹偤宕归鐘辩盎闂佸湱鍎ら崺濠囧礉閻旇櫣纾煎璺烘湰閺嗩剟鏌＄仦鍓ф创闁诡喒鏅犻獮鍥ㄦ媴閸︻厽婢掗梺璇叉唉椤煤濮椻偓瀹曟繂鈻庨幘宕囩暫濠电姴锕ら悧濠囧吹瀹ュ鐓忓璇″灠閸燁偆绮婚悧鍫㈢瘈闁汇垽娼цⅷ闂佹悶鍔庨崢褔鍩㈤弬搴撴闁靛繆鏅滈弲鐐烘⒑閸涘﹦鈽夐柣掳鍔戝畷鎰板垂椤斻儲妫冮弫鎰板川椤撶喐顔夐梻浣虹帛閹告悂宕导鏉戠疅缂佸顑欓悡銉╂煕椤愶絿绠樻い锔诲幖閳规垿顢欑粵瀣姼濠电偛顦扮粙鎾跺垝婵犳艾钃熼柕澶涘閸橀亶姊洪棃娑辨Ч闁搞劎鏁诲鐢割敆閸屾粎顦柟鍏肩暘閸斿秹鍩涢幋锔界厵妞ゆ牕妫楅幊鎰邦敊閸パ€鏀介柣姗嗗亜娴滈箖鏌℃径濠勫闁哄懏鐩棢婵鍩栭悡鏇㈢叓閸ャ劎鈯曢柨娑氬枔缁辨帞鎷犻崣澶樻！闂侀潧娲ょ€氭澘顕ｆ禒瀣╃憸婊堝汲閿涘嫮纾藉ù锝囶焾閳ь剚鎮傞、鏍川鐎涙鐣冲┑鐘垫暩婵挳鏁冮妶鍥С濠靛倸鎲￠悞鑺ャ亜閺嶃劋绶辨繛鍫滅矙閺岋綁骞囬鐐电シ闂佸搫妫欓悷鈺呭箺閸洘鏅查柛娑卞亐閸嬫捇骞掗幋顓熷兊闂佺粯鎸稿ù閿嬬椤撱垺鈷戠紒瀣硶鑲栭梺杞版祰椤曆囷綖韫囨拋娲敂閸曨収妲梻浣侯焾缁绘帡宕㈣閸┾偓妞ゆ帊绀佹慨鍫㈢磼缂佹鈯曢柟宄版嚇瀹曟﹢骞撻幒婵呯磻婵＄偑鍊愰弲娑㈠床閺屻儱鐓橀柟杈剧畱绾惧吋鎱ㄥ鍡楀箹闁哄棗鐗撳铏圭磼濡闉嶇紓浣割儐閸ㄥ潡鍨鹃敂鐐磯闁靛绠戠壕顖炴⒑缂佹顣叉繛鍏肩懄閹便劌鈽夊▎鎴犵槇闂佸啿鐨濋崑鎾绘煕閺囥劌浜滄い顐ｅ浮濮婃椽宕崟顓犲姽缂備胶绮换鍌炴偩閻戣棄绠抽柟瀛樻⒐閻庡姊洪悷閭﹀殶濠殿喖鍢查悾鐑藉蓟閵夛妇鍘介柟鍏肩暘閸娿倕顭囬幇顓犵闁告瑥顧€閼拌法鈧娲栫紞濠傜暦缁嬭鏃堝礃閵娧佸亰濠电姵顔栭崰妤呭Φ濞戙垹纾婚柟鍓х帛閻撴瑩鏌ц箛锝呬簽闁活厽甯楁穱濠囶敃閵忕姵娈梺瀹犳椤︻垶鍩㈡惔銊ョ闁哄倸銇樻竟鏇烆渻閵堝棙灏柛銊︽そ閸╂盯骞掗幊銊ョ秺閺佹劙宕ㄩ鍏兼畼闂備礁鎽滈崰鎾诲磻閻愬灚宕叉繛鎴炵鐎氭氨鎲歌箛娑欏仼闁汇垻顣介崑鎾舵喆閸曨剛顦ㄧ紓渚囧枛閻倿宕洪姀鈩冨劅闁靛鍎抽悿鈧俊鐐€栧ú鏍箠韫囨洜鐭堟い鎰堕檮閳锋帒霉閿濆浂鐒鹃柡鍡涗憾閺岀喓鍠婇崡鐐板枈濡ょ姷鍋涢敃銊х不濞戞ǚ妲堟俊顖滃帶楠炲牓姊绘担鐑樺殌妞ゆ洦鍘介幈銊︻槹鎼粹槅妫滄繝闈涘€搁幉锟犲磹閻㈠憡鐓ユ繝闈涙閸戝湱绱掗妸銊︻棄闂囧鏌ｅ鍡楁灈闁诲浚浜弻鏇㈠炊瑜嶉顓燁殽閻愭潙绗ч柍褜鍓ㄧ紞鍡樼閻愬顩峰┑鍌氭啞閳锋垿鎮楅崷顓烆€屾繛鍏煎姍閺屾盯濡搁妷锕€浠村Δ鐘靛仜閸燁偊鍩㈡惔銊ョ闁绘劘灏欒ぐ鎾煟閻斿摜鐭嬮柛銊ョ仢閻ｇ兘濡烽埡濠冩櫇闂佹寧妫佸Λ鍕焵椤掑倹鏆柟顔煎槻閳诲氦绠涢幙鍐х棯缂傚倷璁查崑鎾绘煕閹般劍娅冪紒璇叉閺岋綁骞囬娑氥€愰悶姘哺濮婃椽鏌呭☉姘ｆ晙闂佸憡姊归崹鍨暦濞差亜鐒垫い鎺嶉檷娴滄粓鏌熼悜妯虹仴妞ゅ浚浜弻锝夊箻閸楃偛濮曠紓浣虹帛閻╊垶鐛€ｎ喗鍊舵繛鑼额唺闁垱銇勯姀鈩冾棃妞ゃ垺锕㈤幃銏ゅ礈娴ｈ櫣鏆扮紓鍌氬€搁崐鐑芥⒔瀹ュ鍨傜憸鐗堝笒閸戠娀鏌曢崼婵囧窛缁炬儳銈稿鍫曞醇濞戞ê顬夐柣蹇撶箣閸楁娊寮婚悢椋庢殝闁绘鐗嗗▓妤呮倵鐟欏嫭绀冪紒顔芥崌閻涱噣骞樼拠鑼唺闂佺懓鐡ㄧ换宥呂涢幇顓犵瘈闁汇垽娼у暩闂佽桨鐒﹂幃鍌氱暦閹存績妲堥柍璺烘惈濞差厼顕ｇ捄浣曟盯宕归锝冧虎闂佽鍠撻崹鑽ゆ閹烘埈娼ㄩ柛鈩冿公缁辨瑥鈹戦悩娈挎殰缂佽鲸娲熷畷鎴﹀箣閿曗偓绾惧綊鏌″搴″箹缂佲偓婢跺本鍠愰柡鍌涱儥濞兼牕霉閻樺樊鍎忕紒鈧€ｎ偁浜滈柡宥冨妽閻ㄦ垿鏌涘鈧禍璺侯潖閾忚鍏滈柛娑卞枛濞懷囨⒒閸屾艾顏╅悗姘嵆瀹曞搫鈽夐姀鐘殿唺濠德板€撻懗鍫曞储閸楃儐娓婚柕鍫濇婵倿鏌涙繝鍐╃鐎殿喗鎮傚顕€宕奸悢鍝勫妇闂備胶纭堕崜婵嬫晪缂備焦顨嗙敮妤呭Φ閸曨垼鏁囬柍銉ュ暱婵嘲顪冮妶蹇曠暢婵炲懏娲滈幑銏犫槈閵忕姷鐓戞繝銏㈡缁查箖宕归崷顓炲灊婵﹩鍘界紞鍥煏婵炑冩噽濡插洭姊绘担瑙勫仩闁稿孩鎸冲畷娲冀椤撶偟鏌у┑鐘绘涧椤戝棝鍩涢幋锔界厵缂佸瀵ч幑锝囩磼閻樿櫕灏扮紒缁樼〒閹风姾顦撮柣锝囨暩閳ь剝顫夊ú婵嗏枍閺囩姭鍋撴担鍐ㄤ汗闁逞屽墯缁嬫帟褰滈梺褰掓敱濡炰粙寮婚敐澶嬪亹闁告瑥顦遍ˇ閬嶆⒑闁偛鑻晶鍙夌箾閸涱喗绀嬮柟顔斤耿楠炴绱掑Ο閿嬪缂傚倷绀侀鍡涱敄濞嗘挸纾块柟杈鹃檮閻撴洟鎮楅敐搴″闁哄妫冮弻娑㈠箳閹惧磭顑傞梺閫炲苯澧剧紓宥呮瀹曚即寮介銈勭瑝闂佽鍎兼慨銈夋偂濞戙垺鐓曢悘鐐插⒔椤ｆ煡鏌熼姘卞闂囧绻濇繝鍌滃ⅱ闁伙絾妞介弻锛勪沪鐠囨彃顬堥梺瀹狀潐閸ㄥ灝鐣烽崡鐐╂闁瑰吀绀佹禍鐐繆閵堝倸浜鹃梻鍥ь槹缁绘繃绻濋崒娑樻婵炲濞€娴滃爼寮婚敍鍕勃闁告挆鈧Σ鍫濐渻閵堝骸浜濈紒顔芥崌瀹曟椽鍩€椤掍降浜滈柟鍝勭Х閸忓本銇勯埡鍌滃弨闁诡喛顫夊顏堝箯瀹€濠傚Τ婵犵數鍋涢崥瀣偋濡ゅ啯宕叉繛鎴烇供閸熷懏銇勯弮鍥у惞闁烩晛娴风槐鎾存媴閸濆嫅锟犳煕濡や礁鈻曢柣娑卞櫍瀵粙鈥栭妷銉╁弰妞ゃ垺顨婇崺鈧い鎺戝閸婅埖銇勯弴妤€浜鹃梺鍝勬湰缁嬫垿鍩㈡惔銈囩杸闁哄啯鍨堕敍鍡樼節濞堝灝鏋涢柨鏇樺劚椤啴鎸婃径灞炬闂佺粯鍨归悺鏃堝极閸ャ劎绠鹃柟瀵稿仧閹冲啴鏌ｅ┑瀣╂喚婵﹦绮幏鍛瑹椤栨粌濮兼俊鐐€栭崹鐢稿箠濮椻偓閻涱喗绻濋崨顖滄澑闂佸搫娲ㄦ慨鐑芥偂閺冨牊鐓涘璺猴功婢ф垿鏌涢弬鎸庢崳鐎殿啫鍥х劦妞ゆ帒瀚埛鎴︽煙閼测晛浠滈柛鏃€锕㈤弻娑㈠棘閼愁垰顏梺宕囩帛閹瑰洭鐛崶顒佸亱闁割偅纰嶇€氬ジ姊绘担鍛婂暈闁告梹娲栭锝夊醇閺囩偟鐣鹃梺鍓插亖閸庢煡鎮￠弴鐐╂斀闁绘ɑ褰冮弳鐐烘煕婵犲啫濮夐柍褜鍓氶鏍窗濡ゅ懎绠栭柛宀€鍋熷畵渚€鎮楅敐搴℃灍闁哄懏绮撻幃宄扳枎濞嗘垹蓱闁诲孩鑹鹃妶绋款潖缂佹ɑ濯撮柛娑橈工閺嗗牏绱撴担绛嬪殭闁稿﹤顭烽崺鈧い鎺嶆祰婢规﹢鏌涢姀鈥崇祷鐎规挸瀚伴弻锝夋偄閸濄儲鍣ч柣搴㈠搸閸斿秶绮嬪鍜佺叆闁割偆鍠撻崢鐢告煟鎼达絾鏆╂い顓炵墛缁傛帟顦归柡宀€鍠栧畷姗€骞撻幒鎾搭啋闁诲氦顫夊ú鈺冩崲濠靛钃熼柛鈩冾殢閸氬鏌涢埄鍐噧鐎殿喕鍗冲缁樼節鎼粹€茬盎濠电偠顕滅粻鎾荤嵁閹扮増鍤掗柕鍫濇椤忔悂姊洪幐搴ｂ槈閻庢凹鍠栬灋妞ゆ牜鍋為悡娆愩亜閺嵮勵棞闁哥噥鍨跺畷鎰邦敍閻愮补鎷洪梻鍌氱墛缁嬫帡骞栭幇鐗堝€垫慨姗嗗幗缁跺弶銇勯弴顏嗙М妞ゃ垺宀搁崺鈧い鎺嗗亾闁伙絿鍏橀獮鎺楀箣閺冣偓椤秴鈹戦悙鍙夘棡闁搞劑娼ч埥澶庮樄婵﹤顭峰畷鎺戔枎閹烘垵甯梻浣侯攰濞呮洟骞戦崶褏鏆︽い鏍仜閸ㄥ倹銇勯弮鈧喊宥咁渻娴犲鈧礁顫滈埀顒佹叏閳ь剟鏌ｅΟ鐓庡妺闁硅弓鍗冲缁樻媴閾忕懓绗″┑顔硷工椤兘宕哄☉銏犻唶闁靛鍎查悗顒佺節閻㈤潧孝婵炶绠撻幃锟犳偄閸忚偐鍙嗗┑鐘绘涧濡瑩宕抽悜妯肩瘈闁逞屽墯鐎佃偐鈧稒顭囬崢閬嶆⒑閹稿海绠撳Δ鐘殿焾閳诲秴顓奸崱妯哄伎婵犵數濮撮崯顖炲Φ濠靛鐓欐い鏃€鍎抽崢瀵糕偓娈垮枛婢у酣骞戦崟顖毼╅柍鍝勫暙缁€鍫ユ⒒閸屾艾鈧兘鎳楅崼鏇炵疇闁规崘顕х粻鐔兼煃閳轰礁鏆熺紒鐘冲劤閳规垿鎮╅幓鎺嶇敖闂佹悶鍊栧ú姗€濡甸崟顖氱疀闁告挷鑳堕弳鐘电磽娴ｅ搫校闁烩晩鍨跺濠氬焺閸愩劎绐炴繝鐢靛Т鐎氼亪鎼规惔锝囩＝濞达絿鎳撴慨鍫㈢磼鐎ｎ偄鐏撮柍銉︽瀹曟﹢顢欓崲澹洦鐓曢柍鈺佸枤濞堟梹绻涢崗鐓庣伌婵﹨娅ｇ划娆忊枎閹冨闂備礁婀遍…鍫モ€﹂柨瀣╃箚?")
        if weak_spots:
            if localized_weak_spot:
                lines.append("")
            else:
                lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欑粣娑㈡⒑閸濄儱校闁圭澧介崚鎺旂磼濡浜濋梺鍛婂姀閺呮繈宕㈡禒瀣拺闂侇偅绋戝畵鍡樼箾娴ｅ啿瀚▍鐘炽亜閺嶎偄浠﹂柣鎾跺枑缁绘繈妫冨☉娆忣槱缂備讲鍋撻悗锝庡亝閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濮风槐鎺楊敊閻ｅ本鍣ч梺瀹狀嚙闁帮綁鐛崱姘兼Щ婵犮垼顫夐敋闁宠鍨块幃娆撴嚑椤掍焦鍠栫紓鍌欑贰閸犳碍鎱ㄩ悽鐢电焿鐎广儱顦介弫鍌炴煕閺囥垺娑ф繛鍫涘姂閺岋綁鎮╅崣澶婎槱缂備椒鐒﹀娆忓祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔告倐濮婃椽宕ㄦ繝鍐ｆ嫻闂佸湱顭堥崯鍧楋綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愬宀婃澓濠电姷鏁搁崑娑㈡偤閵娧冨灊鐎广儱娲﹀畷鏌ユ煕椤愶絿绠橀柡鍡畵閺岀喖骞嗛悧鍫闁哥儐鍨跺娲礃閸欏鍎撻梺绋匡功閺佸鐛箛娑欐優闁革富鍘鹃敍婵嬫⒑缁嬫寧婀伴柣鐔濆洤绀夌€广儱顦伴悡銉︽叏濡じ鍚痪鎯у悑娣囧﹪濡堕崟顓фМ濠电偞鎯岄崳锝夊蓟閿涘嫪娌悹鍥ㄥ絻椤洭鎮楀▓鍨灍闁规瓕娅曟穱濠囧箹娴ｈ倽褍顭跨捄鐚存缂侇噯缍佸铏规嫚閹绘帩鍔夊銈嗘⒐閻楃姴鐣锋导鏉戝唨妞ゆ挻绋堥崑鎾绘晝閳ь剟鎮鹃敓鐘崇劷闁挎洍鍋撴繛鍫涘姂濮婃椽宕烽鈩冾€楅梺鍝ュУ閻楃娀鏁愰悙鍝勫窛閻庢稒顭囬崢钘夆攽閳藉棗鐏℃い鎴炵懇瀹曢潧鈻庨幘瀵稿幐婵炶揪绲块悺鏂款焽閹邦喚纾肩紓浣诡焽缁犵偤鏌熼鑽ょ煓婵☆偄鍟埥澶愬箳閹惧灈鍋撻悧鍫㈢瘈闁汇垽娼ф禒鎺楁煕閺嶎偄鈻堢€规洘顨婇幃鈺呮惞椤愮姳铏庡┑鐘殿暯閳ь剙纾崺锝団偓瑙勬磸閸旀垿銆侀弮鍫濆窛妞ゆ牗顨呮禍鐐箾瀹割喕绨奸柍閿嬪灴閺岀喓绮欓幐搴㈠闯缂備胶濮甸幐濠氬Φ閸曨垱鏅滈柛顭戝枛缁侇噣鎮楃憴鍕闁告梹鐟╅獮鍐╃鐎ｎ亜绐涙繝鐢靛Т鐎氼剟鐛Δ鍛拻濞撴埃鍋撴繛浣冲懏宕查柛顐犲劚绾惧綊鏌″畵顔瑰亾婵℃彃鐗忛幉鍛婃償閵娿儙锕傛煕閺囥劌鐏￠柡鍛叀閺屾稑鈽夐崡鐐扮盎婵炲濯崳锝咁潖濞差亜浼犻柛鏇ㄥ幘娴煎洭姊洪崫銉バｉ柣妤冨█閻涱噣宕橀钘夆偓濠氭煠閹帒鍔氬ù婊堜憾濮婃椽宕滈幓鎺嶇凹缂備浇顕ч崯鎾箖濡粯鍎熼柕濠忓閸樹粙鏌熼崗鑲╂殬闁糕晛瀚板畷顖濈疀濞戞瑧鍘遍梺缁樏壕顓灻虹€涙ǜ浜滈柕蹇娾偓韫濡炪倧绠戠紞濠囧蓟濞戙垹鐓橀柛顭戝枛婵洟鎮楅崹顐ｇ凡閻庢矮鍗抽悰顕€宕堕澶嬫櫌婵犮垼娉涢鍥╃矓闁秵鈷掗柛灞剧懆閸忓瞼绱掗鍛仴闁圭瓔鍋勯—鍐Χ閸℃ǚ鎷归梺缁橆殘婵挳鎮鹃悜绛嬫晢闁告洦鍓欓埀顒傜帛娣囧﹪顢涘┑鍡曟睏闂佷紮绠戦悧鎾愁潖閸濆嫅褔宕惰娴煎牆鈹戦悙鏉垮皟闁搞儜鍛箳闂備礁澹婇崑鍡涘窗閹惧墎涓嶉柟顖ｇ亹瑜版帗鏅查柛娑卞幗濮ｆ劙姊洪崨濠勵暡闁挎岸鏌嶉挊澶樻█濠殿喒鍋撻梺缁橆焽閺佺顭囨径鎰拻濞达絼璀﹂悞楣冩煛閸偄澧伴柟骞垮灲瀹曟帒顫濇潏銊ф濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊閵堝棙閿梺鍝勵儏閻楀繘鍩€椤掆偓缁犲秹宕曢柆宓ュ洭顢涢悙鏉戜簵闂佸搫娲㈤崹娲偂濞嗘挸绾ч柛顐犲劤閻ｇ儤淇婄紒銏犳珝闁哄矉缍侀獮妯尖偓娑欘焽椤︺劎绱撴担铏瑰笡缂佽鐗嗚灋闁告劑鍔夊Σ鍫熸叏濡も偓濡棃骞冮敐澶嬧拻濞达絽鎲￠崯鐐存叏婵犲嫭鍤€闁伙絾绻堥獮鏍ㄦ媴濮濆本鎲伴梻浣芥硶閸犳挻鎱ㄩ幘顔惧祦闁靛骏绱曠粻楣冩煙鐎电鍓辨繛鍫熸礋閺屾盯鎮╅崘鎻掓懙濠殿喖锕ュ钘夌暦椤愶箑绀嬫い鎺嶇劍鐎氬磭绱撻崒娆戭槮妞ゆ垵妫濋獮鎴﹀炊椤掆偓閺勩儵鏌嶈閸撴岸濡甸崟顖氱闁规惌鍨版慨娑氱磽娴ｅ壊妲洪柡浣割煼瀵鈽夊锝呬壕闁挎繂绨肩花濂告煕閿濆懐绉洪柡宀嬬秮閺佹劖寰勫Ο娲绘濠电偛顕刊瀵哥不閹捐绠栨繛鍡樻惄閺佸棝鏌嶈閸撴瑩顢氶敐澶婄閹艰揪绲块惁鍫ユ⒑濮瑰洤鐏叉繛浣冲啰鎽ラ梻鍌欑閹芥粓宕抽妷鈺佸瀭闁肩鍚€缁诲棝姊婚崼鐔衡枔闁衡偓娴犲鐓曢柕澶堝妼閻撴劖銇勯弮鈧Λ鍐潖閾忓湱纾兼俊顖氭惈椤苯顪冮妶鍡樺闁告ü绮欏鏌ュ醇閺囩喎浠洪梺鍛婄☉閿曪箓宕㈤棃娑辨富闁靛牆妫欓埛鎺楁煛閸滀礁浜版鐐诧躬瀹曞爼鈥﹂幋鐑嗗晬闂備胶绮崝鏇㈡偤閵娿儳鏆﹂悘鐐佃檸濞堜粙鏌ｉ幇顓熺稇婵炴惌鍠楅〃銉╂倷鐠囇嗗惈闂佺娅曠划鎾澄涢崘銊㈡婵﹩鍋嗙粈澶娾攽閻樻剚鍟忛柛鐘崇墵閺佸啴鏁傞幆褍鐏婂銈嗙墱閸嬫稓绮婚鐐寸厱婵炴垵宕弸銈夋煟閻旀椿娼愰柕鍥у瀵粙濡歌閻撯偓濠电姵顔栭崰鏍触鐎ｎ偆鈹嶅┑鐘叉处閸婇攱銇勮箛鎾愁仱闁稿鎹囧浠嬵敇閻愯尙鈧參姊婚崒姘卞闁稿繑鑹鹃埥澶娢熼柨瀣澑闂佽鍑界紞鍡樼閻愮儤鍋╁Δ锝呭暞閳锋垿鏌涘☉姗堟敾濠㈣泛瀚伴弻娑㈠Ω閵夛絽浠悗娈垮櫘閸嬪嫰顢樻總绋垮耿婵☆垰鎼导搴㈢節绾版ɑ顫婇柛銊︽緲椤洭鏁撻悩韫炊闂佺粯鍨堕…鍥╃不妤ｅ啯鐓曟い鎰Т閸斻倝鏌ｉ敐鍥у妺闁逛究鍔嶇换婵嬪礃閳瑰じ铏庨柣搴ゎ潐濞插繘宕濆鍥ㄥ床婵犻潧顑呯粈瀣亜閹捐泛校婵炲牆銈稿缁樻媴缁涘娈柣搴㈢▓閺呯姴鐣峰▎鎺嬩汗闁圭儤鍨垮Λ鐑芥⒑閹稿海绠撻柟宄邦儔瀹曠敻寮撮姀锛勫幍闂佽鍨虫晶妤吽夋径瀣垫闁绘劦浜滈悘顏嗙磼缂佹娲存鐐差儔閹瑩宕归銏＄彯闂傚倷绀侀幉锟犳晝閵忥紕顩查悹杞拌濞兼牗绻涘顔荤盎濞磋偐濞€閺屾盯寮撮妸銉ヮ潻闂佺顑呯粔鐟邦潖濞差亜宸濆┑鐘插暟閸欏棝姊洪崫鍕⒈闁告挻绋撻崚鎺斺偓锝庝憾閸氬顭跨捄渚剰闁逞屽墰閸忔﹢骞冮柨瀣濡炲瀵掑Σ顔剧磽閸屾氨孝闁挎洦浜悰顕€宕橀鑲╁姶闂佸憡鍔忛弲娑㈠礉閸涱収娓婚柕鍫濇閳锋帡鏌涘Ο鐘插閻濆爼鏌涢鐘插姕闁抽攱甯掗湁闁挎繂鎳忛幉鎼佹煛鐎ｎ亜鏆為柕鍥у椤㈡洟濮€閳哄倵鏋呴柣搴ゎ潐濞叉牜绱炴繝鍌滄殾缂佸顕抽弮鍫濈劦妞ゆ帒鍊绘稉宥夋煛瀹ュ骸骞楅柣鎾冲暣閺屾稑鈹戦崱妤婁患闂佸搫妫涢崑銈夊箖濡も偓椤繈顢橀悢鐑橆吇闂備胶顢婄亸娆撯€﹂崼銉晣濠靛倻顭堥獮銏′繆閵堝拑宸ユ繛鍫濄偢濮婄粯鎷呴崫銉ㄩ梺绋款儏閿曨亜鐣峰Δ鈧～婊堝焵椤掆偓椤曪綁濡搁敂缁㈡祫闁诲函缍嗛崑鍡涘储閹剧粯鈷戦柤鎭掑剭椤忓煻鍥ㄥ濮濄倕顦…銊╁礂閻樺灚鍤€妞ゎ厹鍔戝畷鐔碱敇閻樺灚姣夌紓鍌氬€峰ù鍥ㄣ仈閸濄儲鏆滈柣鎰惈閻掑灚銇勯幒鎴姛缂佸鏁婚弻娑氣偓锝庝簼閸ｈ棄霉濠婂嫭鍊愰柟顔荤矙瀹曘劍绻濋崟顐㈢疄闂傚倷绀佸﹢閬嶅磿閵堝绠伴柛婵勫劤缁犳梹鎱ㄥΟ澶稿惈缁炬崘鍋愮槐鎾存媴鐠囷紕鍔风紓浣哄У閹稿濡甸崟顖ｆ晝闁挎繂娲ㄩ悿鍕渻閵堝啫鐏柨鏇樺灲楠炲啴鍩￠崨顓狀唽闂佸湱鍎ら幑浣烘閵忋倖鈷掗柛灞捐壘閳ь剙鍢查湁闁搞儺鍓﹂弫瀣喐閺傝法鏆︽繛鍡樻尰閸嬧晝鈧厜鍋撻柍褜鍓涚划鍫熺節閸ャ劎鍘遍梺鏂ユ櫅閸熶即鍩ユ径宀€纾奸柍褜鍓熷畷濂告偄閾忚鍟庨梻浣烘嚀閻°劑鎮烽妷鈺傚€挎繛宸簼閻撴稑霉閿濆浜ら棅顒夊墴閺屸€崇暆鐎ｎ剛鐦堥悗瑙勬礀閻栧吋淇婇悜钘壩ㄧ憸宀勬儉椤忓牊鈷掑ù锝堟鐢盯鏌熼幖浣虹暫鐎规洑鍗冲浠嬵敇閻旇渹绨垫俊鐐€栭崝褏绮婚幋锔藉€峰┑鐘叉处閻撳繐鈹戦悩鑼妞も晩鍓氶妵鍕晜閸濆嫬濮曠紓浣虹帛缁嬫捇鍩€椤掑倹鏆╂い顓炵墛閻楀海绱撻崒娆戣窗闁哥姵顨婇獮鎴﹀炊椤掑倸绁﹂梺鍛婂姂閸擃噣寮崼婵堝姦濡炪倖甯掔€氬摜绱為弽銊х瘈闂傚牊渚楅崕蹇涘船椤栫偞鈷戦梻鍫熶緱濡插爼鏌涙惔鈩冩儓妞ゎ厼娲﹂幆鏃堝Ω閿旀儳骞楅梺鐟板悑閻ｎ亪宕愰妶鍜佺劷闁归偊鍘剧粻楣冩煕濞嗗浚妾ч柤鎷屾硶閳ь剝顫夊ú妯兼崲閸岀偛鐓濋幖娣妼缁犳稒銇勮箛鎾搭棤闁伙綁绠栧缁樻媴缁嬫寧鍊梺璇″枛閸婃悂鈥﹂崶顏嶆Ь濠电偛妫庨崹浠嬪箖濞嗗緷鍦偓锝庡亝閺夋悂姊绘担铏瑰笡闁挎氨鈧鍠栭悥鐓庣暦鐎圭姰浜归柟鐑樻尵閸樹粙姊虹憴鍕闁规椿浜幊鎾诲箰鎼淬垹寮挎繝鐢靛Т閸燁垶濡靛┑瀣厵缂佹稑婀辩弧鈧繝纰樷偓宕囧煟鐎规洏鍔戦、娆撴煥椤栨矮澹曟俊銈忕到閸燁垶鍩涢幋锔界厾濠殿喗鍔曢埀顒佹礋瀵悂宕掗悙瀵稿幈闁瑰吋鐣崹褰掑煝閺囥垺鐓曢柍瑙勫劤娴滅偓淇婇悙顏勨偓鏍暜婵犲嫮鐭嗗〒姘ｅ亾鐎规洜鏁婚、妤呭礋椤掑倸骞堥梻浣虹帛椤牆鈻嶉弴銏″剭闁硅揪闄勯悡鏇㈡煙閻戞ɑ灏紒妞﹀懐纾奸弶鍫涘妼缁楁帡鎽堕敐鍥╃＜閻庯綆浜楁禒鎺旂磼閵娿儯鍋㈡慨濠勭帛閹峰懘宕ㄦ繝鍌涙畼闂備礁鎲￠弻銊ф崲濡警鍤曢柟缁樺坊閺€浠嬫倵閿濆簼绨婚柛瀣Ч濮婂搫效閸パ呬患闂佺顕滅换婵嬪春濞戙垹绠ｉ柣妯虹仛閿涘繐顪冮妶鍡樺暗闁稿鍋為崚濠囧礂閼测晝顔曢梺绋跨箳閸樠勬叏瀹ュ鐓涢悘鐐插⒔濞插鈧鍣崳锝夊春閳ь剚銇勯幒鎴濐仾闁稿顑夐弻锝呂熷▎鎯ф缂備胶濮甸悧鐘诲蓟閿濆顫呴柣妯烘▕濡矂姊烘潪鎵槮闁稿﹤娼″璇测槈閵忊晜鏅濋梺闈涚墕閹冲繘鎮樻笟鈧娲川婵犲繗鈧灝霉濠婂棙纭炬い顐㈢箰鐓ゆい蹇撳椤斿洭鏌熼懝鐗堝涧缂佹彃娼￠幃楣冩偨閸涘ň鎷虹紓鍌欑劍閿曗晛鈻撻弮鈧穱濠囶敃閿濆洨鐓夐梺闈涙閸婂骞戦崟顖毼╃憸蹇涙晬濠靛鈷戠紒瀣濠€浼存煟閻旀潙濮傜€规洘顨呴悾婵嬪焵椤掑倹顫曢柟鐑橆殢閺佸鏌涘☉鍗炲箻濞寸姵鎮傚铏规嫚閳ュ磭浠╅柣搴㈢煯閸楁娊濡存担绯曟闁靛繆鈧枼鍋撻悜鑺ョ厸濠㈣泛顑呴悘锝囩磼閵娿儳浠涘ǎ鍥э躬閹瑩顢旈崟銊ヤ壕闁哄稁鍘肩粈澶屾喐韫囨稑鐒垫い鎺戝濞懷囨煟椤撶偛鈧悂顢氶敐澶樻晝闁挎洍鍋撻柣鎰攻閵囧嫰骞掑鍫濆帯闂佸憡眉缁瑥顫忔ウ瑁や汗闁圭儤鍨抽崰濠囨⒑閹肩偛濡洪柛妤佸▕楠炲棝宕橀…瀣そ椤㈡棃宕ㄩ姘闂傚倷绀佹竟濠囧磻閹烘纾婚柛鏇ㄥ亐閺嬪秶鈧箍鍎遍ˇ浼存偂濞戞埃鍋撻崗澶婁壕闁诲函缍嗛崜娑滄懌闂傚倷娴囬鏍垂閸楃倣娑㈠礃閳哄倸寮块梺閫炲苯澧撮柡灞界У濞碱亪骞嶉鐓庮瀴婵犵數鍋涢幊蹇涙儎椤栨凹娼栫紓浣股戞刊鎾煕濞戞﹫鏀婚柛鐘冲姈缁绘繂鈻撻崹顔界彎濠电偘鍖犻崨顓炵柧濠电姷鏁告慨鎾晝閵堝鍋嬮柛鈩冪懅閻棝鏌涢埄鍐姇闁绘挻鐟╅弻锝夊箣閻忔椿浜幃妯侯吋婢跺鍘搁柣搴秵娴滎亪宕ｉ崟顖涚厽闁瑰灝鍟禍鎵偓瑙勬礀閻栧吋淇婇幖浣规櫆缂備降鍨鸿ⅷ婵犵數濮烽弫鎼佸磻濞戙垺鍋嬮柟鎯у娑撳秹鏌″畵顔兼湰缂嶅酣姊洪幆褏绠烘い顐㈩槺閳ь剚纰嶅畝鎼佸蓟瀹ュ唯闁靛／宥囩濠电偛顕慨鐢稿箖閸屾凹娼栭柧蹇撴贡閻瑦绻涢崱妯哄姢闁告挷鍗冲娲箰鎼淬垻锛橀梺绋匡攻濞叉牠鎮鹃悽绋跨妞ゆ帒鍊婚惁鍫ユ⒒閸屾氨澧涚紒瀣灴閸┾偓妞ゆ帊鐒﹂崐鎰殽閻愬樊妯€闁轰焦鎹囬幃鈺呮嚑椤掆偓楠炲牓姊绘担鐑樺殌妞ゆ洦鍙冨畷鎴︽倷閸濆嫮鐓戦棅顐㈡处缁嬫帡鎮￠悢鍏肩厽闁哄倹瀵ч幆鍫熴亜閿濆懌鍋㈤柡宀€鍠栧畷妤呮偂鎼粹槅娼撻梻浣哥枃椤宕归崸妤€鍨傚Δ锝呭暞閸ゆ垶銇勯幒鎴濃偓濠氬储椤栫偞鈷掑ù锝呮啞閹牓鏌￠崼顐㈠⒋闁诡垰瀚伴、娑樷槈濡ゅ啰鐣鹃梻浣哥秺濡法绮堟担鍛婃殰闂傚倷鐒︾€笛兠哄澶婄；闁规崘绉ぐ鎺撳亹闁惧浚鍋勯崬澶愭⒑鐠団€虫灍妞ゃ劌鎳橀崺銏ゅ箻鐠囨彃鐎銈嗘⒒閺咁偅绂嶉鍛箚闁绘劦浜滈埀顑惧€濆畷銏°偅閸愩劎顦у┑顔姐仜閸嬫捇鏌ｅ☉鍗炴珝鐎规洘锕㈤、娆戝枈鏉堛劎绉遍梻鍌欑窔濞佳呮崲閹烘挻鍙忛柣銏犳啞閸婄敻鏌熼幆鏉啃撻柣鎾寸☉椤法鎹勯悮鏉戝婵犫拃鍕伌闁哄本鐩顒傛崉閵婃劑鍨介弻宥囨嫚閼碱儷褏鈧娲栭妶鍛婁繆閻戣姤鏅滈悷娆忓椤忕儤绻濋悽闈涗哗闁规椿浜炲濠囧锤濡や礁浠遍梺鍝勫暙閻楀棝宕ヨぐ鎺撶厱闁逛即娼ч弸鐔兼煟閹惧瓨绀嬮柡灞炬礃缁绘盯宕归鐓幮曢梻浣告啞閻熴儳鈧凹鍣ｉ崺鈧い鎺戝枤濞兼劖绻涢崣澶涜€块柡浣稿暣婵偓闁炽儴灏欑粻姘舵⒑瑜版帗锛熺紒鈧担铏逛笉婵炴垶鐟ｆ禍婊堟煙閹规劖纭惧ù鐘欏厾褰掓偐閸欏鍠愮紓浣介哺閹稿骞忛崨瀛樻優闁荤喐澹嗛鑲╃磽閸屾瑦绁版い鏇嗗洦鍋嬮柟鎹愬吹瀹撲線鏌涢幇銊︽珖妞も晝鍏橀幃妤呮晲鎼粹€茶埅濠碘槅鍋勯崯顐﹀煘閹达附鍊烽柡澶嬪灩娴犵顪冮妶鍐ㄥ婵☆偅绻傞悾鐑藉传閸曘劍顫嶉梺闈涚箚濡狙囧箯缂佹绠鹃弶鍫濆⒔閸掍即鏌熺拠褏绡€鐎规洦鍨堕幃娆徢庨璺ㄧ泿婵＄偑鍊栭幐楣冨磻閻愭牳澶愬閳垛晛浜鹃悷娆忓缁€鍐煕鎼绰板仮閽樻繈鏌熺紒銏犳灍闁绘挻鐩幃姗€鎮欓崹顐ｇ彧婵犫拃宥夋闁逛究鍔嶇换婵嬪礃閳瑰じ铏庨柣搴ゎ潐濞诧箓宕戞繝鍌滄殾闁绘梻鍘ч崹鍌涖亜閹邦剝鐧侀柛銉ｅ妷閹疯櫣绱撴笟鍥х仭婵炲弶锚閳诲秹宕ㄧ€涙鍘藉┑掳鍊撻悞锔句焊椤撱垺鐓熼柨婵嗘搐閸樻挳鏌熼鐐珪缂侇喗鐟╁畷褰掝敊閼测斂鍋栭梻鍌氬€风欢姘焽瑜庨〃銉ㄧ疀閺囩噥娼熼梺鍝勬储閸ㄥ綊宕掗妸锔轰簻闊洦鎸婚崳鐣岀磼閳锯偓閸嬫捇姊绘担鍦菇闁搞劏妫勯…鍥槼缂佸倹甯熼ˇ褰掓煛鐏炲墽銆掗柍褜鍓ㄧ紞鍡涘磻閸涱垯鐒婃い鎾卞灪閻撳啴鎮归崶顏勭毢閺佸牓鎮楃憴鍕鐎规洦鍓熼崺銉﹀緞婵炵偓鐎婚梺鐟扮摠缁诲倻绮诲ú顏呪拻闁稿本鐟чˇ锔界節閳ь剟鏌嗗鍛紵闂侀潧鐗嗛幏瀣焽閺嶎厽鐓犲┑顔藉姇閳ь剚鐗犲鍐差煥閸曨厾顔曢梺鐟邦嚟閸嬬偤鎯冮幋鐘垫／闁硅鍔曟禍鍦磼鏉堛劍灏伴柟宄版噽閹风娀鏁嶉崟顐⑿ㄥ┑鐘垫暩閸嬬偠銇愰崘顔藉仱闁靛ň鏂傞埀顒€鍟存俊鐑藉煛閸屾埃鍋撴搴樺亾閻熸澘顥忛柛鐘崇墵瀹曟粓宕奸弴鐔叉嫼闁荤姴娲犻埀顒冩珪閻忓秹姊洪懡銈呮毐闁哄懏鐩幃楣冩倻閽樺顢呴梺缁樺姇缁夊爼宕伴弽顓炵鐟滅増甯楅悞缁樼箾閹寸偞鐨戞い锔诲櫍濮婄粯鎷呯粵瀣闁诲孩绋堥弲鐘汇€佸▎鎾冲唨妞ゆ挾鍋熼悰銉モ攽鎺抽崐鎾绘嚄閸撲胶涓嶉柟顖嗏偓閺€浠嬫煟濡绲诲ù婊呭仱閺屾盯濡堕崱妯碱槹闂佸搫鐬奸崰鎾舵閹烘顫呴柣妯虹－娴滎亝淇婇悙顏勨偓銈夊磻閸曨垰绠犳慨妞诲亾鐎殿喛顕ч鍏煎緞鐎ｎ剙寮虫俊鐐€栭悧妤呮儗椤旂晫鐝堕柡鍥ュ灪閳锋帒霉閿濆洤鍔嬮柛銈傚亾闂備焦鎮堕崹娲偂閿熺姷宓侀柡宥庡弾閺佸啴鏌ㄩ弴妤€浜鹃梺缁樻尰閿曘垽寮婚悢鍛婄秶濡わ絽鍟宥夋⒑缁嬪尅鍔熼柛蹇旓耿楠炲啴鎮烽幊濠冩そ椤㈡棃宕卞▎鎴犲炊闂傚倷娴囧銊х矆娓氣偓閹ê鈹戠€Ｑ€鍋撻弮鍫濈妞ゆ柨妲堣閺屾盯鍩勯崘鍓у姼闂佺顑勭欢姘潖濞差亜绠归柣鎰絻婵⊙囨⒑閸涘﹤濮傞柛鏂跨Ч椤㈡鎷犲ù瀣杸闂佺粯锚閻忔岸寮抽埡鍛厱閻庯綆鍋嗛埥澶愭懚閻愬绠鹃柛鈩兩戠亸顓犵磼閻樿櫕绶查柍瑙勫灴閹晝鈧湱濮撮ˉ婵堢磼閻愵剙鍔ゆい顓犲厴瀵濡搁妷銏℃杸闂佺硶鍓濋敋濞寸娀绠栭幃宄邦煥閸涱収鏆柣銏╁灡椤ㄥ﹤顕ｉ弻銉ヨ摕闁靛濡囬崢鍗炩攽閻愭潙鐏ョ€规洦鍓熷鎼佹晜閸撗勶紡濡炪倖鎸荤粙鎴炵妤ｅ啯鈷掗柛灞捐壘閳ь剟顥撶划鍫熺瑹閳ь剟鐛径鎰櫢闁绘ê鍟挎禒顓㈡⒑闂堟稓绠為柛濠冩礈婢规洘绻濆顓犲幍闂佸憡鎸嗛崨顓狀偧闂備焦濞婇弨杈╂暜閹烘绠掗梻浣瑰缁诲倿鎮ф繝鍥舵晜闁绘绮悡蹇涙煕閳╁喚娈ｉ棅顒夊墴閺屸€崇暆鐎ｎ剛鐦堥悗瑙勬礃鐢帡鍩㈡惔銊ョ闁绘﹢娼ф惔濠囨⒑鐠囧弶鍞夋い顐㈩槸鐓ゆ慨妞诲亾鐎规洖缍婂畷绋课旈崘銊с偊婵犳鍠楅妵娑㈠磻閹炬惌娈介柣鎰级婢跺嫰鏌熷畡鐗堝殗闁诡喚鍏橀獮宥夘敊閸欘偅甯″濠氬磼濮橆兘鍋撴搴㈩偨婵﹩鍓﹂悞鐣屾喐閺冨牆绠栫憸鏂跨暦閸楃儐娓婚柕蹇ョ磿閳藉鎽堕弽顓熺厱闁规澘鍚€缁ㄤ粙鏌ｉ敐鍛煟婵﹨娅ｇ划娆戞崉閵娧傜礃闂備胶顭堥鍥磻閵堝绠栭柨鐔哄У閸嬫劗绱撴担璇＄劷闁告﹢浜跺楦裤亹閹烘垳鍠婇梺鍛婎焾閸嬫劕顕ユ繝鍕＜婵☆垶鏅茬花濠氭⒑閹稿海绠撻柟铏姍閺佸秴顓奸崶鈺冿紲闁哄鐗勯崝灞矫归濮愪簻闁靛骏绱曢幊鍐煃鐠囨煡鍙勬鐐叉椤﹁櫕銇勯弬鍨伃婵﹥妞藉畷锝夊Ψ瑜岀憰鍡欑磽閸屾氨小缂佽埖鑹鹃锝嗙節濮橆儵褔鏌涢埄鍏狀亜顕ｉ崸妤佲拺鐟滅増甯掓禍浼存煕韫囨棑鑰跨€规洘鍨块獮妯侯熆閸曨剚顥堢€规洦浜濋幏鍛喆閸曨剛褰熼梻鍌氬€风粈渚€骞栭鈷氭椽濮€閵堝懎鐎┑鐐叉▕娴滄粓鎮￠弴銏＄厵閺夊牓绠栧顕€鏌ｉ幘瀛樼闁哄瞼鍠栭幃娆擃敆娴ｈ櫣鈻忕紓鍌欐祰鐏忣亪顢氳濠€浣糕攽閻樿宸ラ柟鍐插缁傛帡鏌嗗鍡欏幐闁诲繒鍋涙晶钘壝洪幘顔界厵妞ゆ棁顫夊▍濠勨偓娈垮枛椤攱淇婇悜钘壩ㄩ柕澶堝劚閹搞倝姊婚崒姘偓宄懊归崶顒夋晪闁哄稁鍘肩粣妤佷繆閵堝懏鍣洪柡鍛箞閺屾洝绠涚€ｎ亖鍋撳Δ鈧悾鍨媴鐟欏嫬寮垮┑锛勫仩椤曆勭閹屾富闁靛牆鍟悘顏堟煟閻斿弶娅婃鐐插暣瀹曟粏顦辨繛宀婁邯閺岋箑螣娓氼垱楔濡炪倖鎸搁妶绋款潖婵犳艾纾兼慨姗嗗厴閸嬫捇鎮滈懞銉モ偓鍧楁煥閺囩偛鈧摜澹曢崸妤佺厱闁归偊鍨煎鍧楁煟閻旂厧浜版繛灏栨櫊閹銈﹂幐搴哗闂佹寧绋掗惄顖氼潖濞差亜宸濆┑鐘辫兌缁讳線姊洪崜鑼帥闁搞劌鐖奸獮鍐倷鐎靛摜鐦堥梺绋款儛閸ㄦ壆绱炴繝鍥х畺闁斥晛鍟崕鐔兼煥濠靛棙顥為柛鐘崇墵濮婄粯鎷呴搹鐟扮闂佸湱顭堥…鐑藉箖閻ゎ垼妯勯梺绯曟杹閸嬫挸顪冮妶鍡楃瑨闁稿﹤缍婂畷鐢稿焵椤掑嫭鐓熼幖娣灩閸ゎ剟鏌涢悩鎰佹疁鐎殿喛灏欓幑鍕媴閺囩喐顥堢€规洏鍔戦、姗€鎮欓弶鎴濆闂傚倸鍊烽悞锕傚箖閸洖纾挎い鏇楀亾鐎殿噮鍓氱粭鐔煎焵椤掆偓閻ｇ兘骞嬮敃鈧粻濠氭煠閹间焦娑ч柡瀣€垮娲川婵犲啫顦╅梺鍛婃尰閻╊垶寮鍜佹建闁逞屽墮椤繐煤椤忓嫬绐涙繝鐢靛Т閸熶即宕ｉ崱娆戠＝濞达絽澹婂Σ鎼佹煟閺嵮佸仮闁绘侗鍣ｉ獮瀣晝閳ь剟锝為崨瀛樼厽婵妫楁禍婵嬫煛閸屾浜鹃梻鍌欐祰椤曆囧礄閻ｅ瞼绀婇柛鈩冾焽椤╂煡鏌ｉ幇顓犲闁搞儺鍓欑痪褎绻涢崱娆忎壕閻庨潧鐭傚娲濞戞艾顣哄┑鈽嗗亝閻熝勭閹间礁绠ユい鏂垮⒔閿涙粓鏌ｆ惔顖滅У闁稿瀚湁妞ゆ洍鍋撻柡宀€鍠栭、娆戠驳鐎ｎ偆鏆︾紓鍌欐祰濡椼劎鍒掑▎蹇曟殾闁靛濡囩粻楣冩煟閹伴潧澧い蹇旀そ濮婂宕掑▎鎺戝帯濡炪値鍘奸悧鎾愁嚕閻㈠壊鏁嗛柛鏇ㄥ墮濞堢偞淇婇妶蹇曞埌闁哥噥鍋婇幃鐐哄垂椤愮姳绨婚梺鐟版惈缁夊爼宕濆澶嬬厱濠电姴鍟慨澶愭煃瑜滈崜婵嬶綖婢跺⊕鍝勵潨閳ь剙鐣峰┑鍡忔瀻闁规儳纾悾鍝勨攽閻樿宸ラ柣妤€锕畷闈涱吋婢跺鍘繝銏ｆ硾閻楀棝宕濆Δ鍛厱閻庯綆鍋呭畷宀€鈧娲滈…鍫ｇ亙婵炶揪绲介幖顐㈩嚕閹惰姤鈷掑ù锝呮啞閹牊绻涚拠褏鐣遍柣锝嗙箘缁瑥鈻庨崜褉鍋撻崜浣插亾閻熸澘顏柛锝嗘尦閹兘鏌囬敂鎯у汲闂備礁鎲￠崝锔界閻愭惌娈梻鍌氬€风粈渚€骞栭锕€瀚夋い鎺戝閸庡孩銇勯弽顐户鐎规挷绶氶弻娑㈠Ψ椤旂厧顫╃紓浣插亾闁稿瞼鍋為悡鏇熺節闂堟稑顏╅柛鏃€宀搁弻娑㈠Χ鎼粹€斥拫濠殿喖锕︾划顖炲箯閸涱喚鐟规い鏍ㄧ矊婵吋淇婇悙顏勨偓鏍垂闂堟党娑樷攽鐎ｎ亞鐣洪悷婊冪Х閻忓啴姊洪崨濠佺繁闁告ɑ鐟╅弫鍐磼濞戞艾骞堥梻浣告惈濞层垽宕濆畝鍕€堕柣妯兼暩绾惧ジ鏌ｅΟ铏癸紞婵炲弶鎸抽弻锛勪沪閸撗勫垱濡ょ姷鍋為敃銏ゅ箠閻樺灚宕夐柛婵嗗閼垫劙姊婚崒娆戭槮闁圭⒈鍋勮灋婵炴垶鐟х粻楣冩煃瑜滈崜姘跺箞?")
        if scenario in {"review", "plan", "task", "next_task"} and review_rhythm:
            lines.append("")
        elif due_reviews:
            lines.append(f"闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴氨绮悢鑲烘棃鍩€椤掑啰浜遍梻浣芥硶閸犳挻鎱ㄩ悽绋跨厱闁硅揪闄勯悡鐔兼煟閺傛寧鍟炵紒鑸电叀閺岋繝宕卞☉妤佸枤闂佸搫鐭夌换婵嗙暦婵傚壊鏁冮柕蹇曞濞奸箖姊绘担鐑樺殌缂佺姴绉瑰畷纭呫亹閹烘垹鍘撮梺鐟邦嚟婵參宕戦幘缁樻櫜閹肩补鈧尙鐩庡┑鐐差嚟婵潧顪冮挊澶樻綎濠电姵鑹剧壕鍏兼叏濡搫鑸规い銈傚亾闂傚倷绀侀幉鈥愁啅婵犳艾纾婚柟鐐灱閺€浠嬫煟閹邦厽缍戦柣蹇曞枛閺屾盯濡搁敂濮愪虎闂?{len(due_reviews)} 婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽弫鎰緞婵犲嫮鏉告俊鐐€栫敮濠囨倿閿曞倸纾块柟鍓х帛閳锋垿鏌熼懖鈺佷粶濠碘€炽偢閺屾稒绻濋崒娑樹淮閻庢鍠涢褔鍩ユ径鎰潊闁冲搫鍊瑰▍鍥⒒娴ｇ懓顕滅紒璇插€歌灋婵炴垟鎳為崶顒€唯鐟滃繒澹曢挊澹濆綊鏁愰崨顔藉創閻庢稒绻勭槐鎾诲磼濮樻瘷銏ゆ煥閺囥劋绨绘い鏇悼閹风姴顔忛鍏煎€┑鐘灱濞夋盯鏁冮敐鍥潟闁割偅娲橀埛鎴︽煕濞戞﹫鏀诲璺哄閺屾稓鈧急鍐у闂傚倷鑳堕…鍫ヮ敄閸℃稑绠伴柤濮愬€栧畷鍙夌節闂堟稒锛嶆繛灏栨櫊閺屾洘寰勯崼婵堜患婵炲瓨绮撶粻鏍蓟濞戞ǚ妲堟繛鍡樺姉缁嬪洭姊哄ú璇插箺妞ゃ劌鎳橀垾锔炬崉閵婏箑纾梺鎯х箰濠€杈ㄥ閸ヮ剚鈷戝ù鍏肩懅閻ｉ亶鏌ｅΔ鈧敃锕傚箲閵忕姭鏀介悗锝庡亜娴犳椽姊婚崒姘卞闁告巻鍋撻梺闈涚箞閸婃牠鎮￠弴鐐╂斀闁绘ɑ褰冩禍鐐烘煟閹剧懓浜归柍褜鍓濋～澶娒鸿箛娑樼？闂傚牊绋撻弳锕傛煕椤愶絾澶勯柡浣告闇夐柨婵嗘噺閹牊顨ラ悙鑼ⅵ婵﹦绮粭鐔煎焵椤掆偓椤洩顦归挊婵喢归悩宸剰缂佹劖顨婇弻鈥愁吋閸愩劌顬夊┑鐐叉噽婵敻濡甸崟顖氬嵆婵°倐鍋撳ù婊堢畺濮婃椽宕崟顓犲姽缂傚倸绉崇欢姘跺Υ娴ｅ壊娼ㄩ柍褜鍓熼獮鍐Χ閸℃ê顎撻梺闈╁瘜閸樿棄鈻撻挊澶嗘斀闁挎稑瀚禍濂告煕婵炲灝鈧繂鐣烽敐澶婄劦妞ゆ帊鑳剁粻鎯ь熆鐠轰警鍎愮紒鈧€ｎ偒娈介柣鎰綑閻忓鈧娲滈崰鏍€佸☉姗嗘僵妞ゆ劑鍊楅崐鐐烘⒒閸屾瑧顦﹂柟娴嬧偓瓒佹椽寮介鐔封偓鑸垫叏濮楀棗骞樺褝绻濆濠氬磼濮橆兘鍋撻幖浣哥９濡炲娴烽惌鍡椼€掑锝呬壕濡ょ姷鍋為悧鐘汇€侀弴銏℃櫆缂備焦蓱濞呭牓姊绘担铏广€婇柛鎾寸箘缁瑩骞掑Δ鈧壕濠氭煥閻斿搫校闁绘挸鍟村鍫曟倷閺夋埈妫嗛柣鐘冲姉婢ф鎹㈠☉銏犵闁兼祴鏅涢埛宀勬⒑閸濆嫮娼ら柛鈩冪懅閺夋悂姊洪悷鏉库挃妞ゃ儲鍔楀☉鐢稿焵椤掑倻纾藉ù锝呮惈娴滈箖鏌涙惔銏犫枙鐎规洏鍎抽埀顒婄秵閸犳牜绮婚悙鐑樼厪濠电偛鐏濋崜濠氭煛閸愩劎澧曢柣鎺戠仛閵囧嫰骞掗幋婵愪痪闂佺顑呴澶愬蓟閻斿吋鍋嬮柛顐ゅ枔閸戯繝姊虹紒妯虹瑨闁诲繑宀告俊鐢稿礋椤栨氨顔婇悗骞垮劚濞村倸危椤旂⒈娓婚柕鍫濇缁€鍐磼椤斿吋鎹ｆ俊鍙夊姍楠炴帡寮崒婊愮床婵犵妲呴崹浼存儍闁垮鍙忛柛銉墯閳锋垿鏌ｉ悢鍛婄凡婵℃彃顭烽弻鐔兼惞椤愨偓椤忓牊鍋╃€瑰嫰鍋婂銊╂煃瑜滈崜鐔兼偘椤曗偓楠炴鎷犻懠顒夊敽婵犵數濞€濞佳囧箠閹邦喖顥氶悹鍥ㄧゴ閺€浠嬫煥濞戞ê顏╁ù婊冦偢閺屾稒绻濋崘銊ヮ潚閻庢鍠楅悡锟犲箖閳哄啯瀚氶柤纰卞墮閹藉姊婚崒娆戣窗闁告挻鐟х划鏃傗偓娑欙供閺€浼存⒒閸屾瑧顦﹂柟娴嬧偓瓒佹椽鏁冮崒姘€繛鏉戝悑濞兼瑧绮堥崘顔界厓鐟滄粓宕滃▎鎾偓鏃堝礃椤斿槈褔鏌涢埄鍐炬當鐞氭繃绻濋悽闈浶涢柟鍐叉喘瀹曟垿骞橀弬銉︽杸闂佺粯鍔樼亸娆撴倿閹灐鐟邦煥鎼存繄鐩庡銈庡亜缁绘﹢骞栬ぐ鎺戞嵍妞ゆ挾濯寸槐鍙夌節绾版ɑ顫婇柛銊ф暬椤㈡俺顦规俊顐㈠椤撳ジ宕ㄩ鍛澑闂備胶绮崝鏍亹閸愵亞妫憸鏃堝蓟閿濆憘鏃堝礃閵娿垺鐎伴柣搴ゎ潐濞叉ê顪冩禒瀣畺婵炲棙鎸告导鐘绘煕閺囥劌寮鹃柛姘嚇濮婄粯鎷呴悷閭﹀殝濠碘槅鍋傜粈浣界亱闂佸憡娲﹂崜娑€呴懠顒佸枑闁绘鐗嗙粭姘舵煃闁垮鐏撮柡灞剧洴閺佸倻鎷犻幓鎺旑啋闂佹眹鍩勯崹閬嶆儎椤栫偛绠栧ù鐘差儛閺佸秵淇婇妶鍕妽闁绘繃娲滅槐鎾存媴缁嬪簱鍋撻崷顓熸殰婵°倕鍟扮槐锕€霉閻樺樊鍎忕€瑰憡绻傞埞鎴︽偐閹绘帩浠煎Δ鐘靛仦椤ㄥ﹤顫忕紒妯肩懝闁逞屽墮椤洩顦撮柟骞垮灲瀹曞崬鈽夊Ο鍏肩叄婵犵數鍋為崹顖炲垂濞差亜纾归柛顐ｆ礃閻撶喐淇婇婊冨妺闁崇粯娲熼弻锝夊棘閹稿寒妫ら梺纭呭皺椤牓顢樻總绋胯Е闁靛牆娲﹂崵鈧梺浼欑秶缁绘繈鐛箛娑樼睄闁规儳澧庤ⅵ婵°倗濮烽崑娑樏洪鐑嗗殨闁告挷鐒﹀畷澶嬨亜椤撶喎鐏ラ柡浣芥閳规垿鎮╅懠顒侇棄闂佸搫顦花閬嶅磻閹捐绠涢柡澶庢硶閿涙盯姊洪悷鏉库挃缂侇噮鍨堕崺娑㈠箣閿旂晫鍘卞┑掳鍊曢崯顐ｇ閿曞倹鐓曢柣妯碱劜閼板潡鏌＄仦绯曞亾瀹曞洦娈曢柣搴秵閸撴盯鎯侀崼銉﹀€甸悷娆忓缁€鈧梺缁樼墪閸氬绌辨繝鍌ゆ桨鐎光偓婵犲喚鈧洭姊绘担鍛婃儓婵☆偄顕幑銏犫攽閸♀晜缍庡┑鐐叉▕娴滄粍瀵奸悩缁樼厪濠㈣泛鐗嗛崜楣冩煥濠靛棙绀岄柛瀣崌瀹曟寰勬繝浣割棜闂傚倷绀佺紞濠偽涚捄銊х焼濞达綀娅ｆ稉宥夋煛瀹ュ啫濡虹紒璇叉閺屾洟宕煎┑鍥ф闂佸搫妫涢崑銈夊蓟濞戙垺鍋愰柛娆忣樈濡箓姊洪崫鍕拱闁烩晩鍨伴锝夊箻椤斿槈鈺呮煏婢跺牆鍔存繛濂哥畺濮婄粯鎷呴悷閭﹀殝缂備礁顑嗙敮锟犲极閸愵喖顫呴柣娆屽亾婵炲吋鐗犻弻褑绠涢幘纾嬬闂佹椿鍘介悷鈺呭蓟濞戔懇鈧箓骞嬪┑鍥╁蒋闂備礁鎲￠弻銊┧囬棃娑辨綎闁惧繐婀辩壕鍏间繆椤栨粎甯涢柛搴㈡尵缁辨挻鎷呴搹鐟扮缂備浇顕ч悧鎾荤嵁閸愨晛顕遍柟纰卞幗閺咁亪姊洪柅鐐茶嫰婢ь噣鏌ｉ敐鍥у幋鐎规洩绻濋幃娆撳煛閸屻倖缍屽┑鐘殿暯濡插懘宕归悽绋跨；闁归偊鍓﹂悞钘夘熆閼搁潧濮堥柍閿嬪笒闇夐柨婵嗘祩閻掔偓銇勯妷銉х闁哄本绋撻埀顒婄秵娴滄繈藟閵忊懇鍋撶憴鍕；闁告濞婇悰顕€宕堕澶嬫櫈闂佸吋浜介崕鎶藉焵椤掆偓閹碱偊鍩為幋锔藉亹閻犲泧鍐х矗闂備胶绮〃鍛存晝椤忓牆鏄ユ繛鎴欏灩缁狅綁鏌ㄩ弮鍌涙珪闁告鏁诲娲礂閼测斂鍋為梺鍝勬噺缁嬫帞绮嬮幒鎴叆闁割偆鍠撻崢閬嶆⒑閸濆嫬鏆婇柛瀣崌閺屻劑寮村Ο铏逛紙閻庢鍠涢褔鍩ユ径鎰潊闁绘ɑ鍓氬Λ鐔兼⒑閼姐倕校濞存粈绮欏畷婊堟焼瀹ュ拋娼婇梺闈涚箚閳ь剙鍘栫划鈩冪節閻㈤潧浠滄俊顐ｇ懇楠炴劙宕妷褌绗夐柣鐔哥懃鐎氼喚绮绘ィ鍐╃叆婵犻潧妫濋妤€顭胯閸犳牠鍩為幋锕€鐏抽柤纰卞墰閻撴捇姊洪崫鍕缂佸缍婂濠氬Ω瑜夐崑鎾绘晲鎼存繄鏁栭梺鑽ゅ枂閸旀垵顫忔繝姘倞鐟滄粌螣閳ь剟姊洪崫鍕潶闁告柨鐭傞崺鐐哄箣閿曗偓楠炪垺绻涢崱妤冪畾闁瑰皝鍓濈换婵嬫偨闂堟稐绮堕梺鍛婅壘椤戝鐣峰┑鍡忔瀻闁规儳鐤囬幗鏇炩攽閻愭潙鐏﹂柛鈺佸暣瀹曟垿骞樼紒妯绘珳闁硅偐琛ラ埀顒佸墯濞煎姊绘担鍝ユ瀮妞ゆ泦鍥ㄥ亱闁规崘顕ч拑鐔兼煥濞戞ê顏ф繛宀婁邯閺屾盯骞樺璇蹭壕婵犳鍠栧ú顓烆潖閾忚瀚氶柍銉ョ－娴狀厼鈹戦埥鍡椾簻闁哥噥鍨堕獮鍫ュΩ閳轰胶鍔﹀銈嗗笒鐎氼參鎮￠悢鍛婂弿婵°倐鍋撴俊顐ｎ殕缁傚秴鈹戠€ｎ偆鍘介棅顐㈡处閹稿藟閵忋倖鐓涚€光偓鐎ｎ剛蓱闂佽鍨卞Λ鍐╀繆閼稿灚鍎熼柕蹇嬪灮鍟告繝鐢靛Х閺佹悂宕戝☉姗嗗殨闁割偅娲橀弲婵嬫煏韫囨洖啸闁哄棴濡囬幉鎼佹偋閸繄鐟ㄩ梻浣斤骏閸婃牗绌辨繝鍥ч柛灞剧煯婢规洜绱撻崒娆掑厡濠殿喚鏁婚幃褔鎮╃拠鑼舵憰闂佸搫娴勭槐鏇㈡偪閳ь剟鏌ｆ惔顖滅У濞存粍鐗犲畷鎴﹀箻鐠囨彃宓嗛梺缁橆焽閺佹悂鎮炴總鍛娾拺闁告稑锕ユ径鍕煕閵娾晙鎲鹃柟顔欍倗鐤€婵炴垶鐟ч崢鍗烆渻閵堝棗濮х紒鑼舵硶缁螣娓氼垳鍞甸悷婊冮叄瀹曟繂鈻庨幘瀹犳憰濠电偞鍨堕崺鍐磻閹剧粯鏅查幖绮光偓鑼嚬闁诲氦顫夊ú鏍儔婵傜鐒垫い鎺戝枤濞兼劖绻涢崣澶岀煉闁炽儻绠撳畷濂告晲閸ワ妇鑳哄┑鐘垫暩閸嬬娀骞撻鍡楃筏濞寸姴顑呯粻瑙勩亜閹拌泛顩€规挷绶氶弻娑㈩敃閵堝懏鐏佺紓浣叉閸嬫捇姊绘担鍦菇闁搞劏妫勯…鍥槼缂佸倹甯￠弫鍐磼濞戞艾骞堥梻渚€娼ч…鍫ュ磿閹惰棄鏄ラ柨婵嗩槹閻撳啴鏌曟径妯虹仯闁伙絿鏁搁埀顒冾潐濞叉牠鎮ユ總鎼炩偓浣肝旈崨顓犲姦濡炪倖甯掗崐缁樼▔瀹ュ棛绠剧€瑰壊鍠曠花濂告煟閹捐泛鏋戝ǎ鍥э躬椤㈡稑鈹戦崱鏇熺潖闂佹眹鍩勯崹閬嶆儎椤栫偛钃熼柨婵嗩槸缁犲鎮楅棃娑欏暈闁告帗鐩娲传閸曨剚鎷辩紓浣割儐閸ㄥ潡鍨鹃敃鍌毼╅柍杞拌兌閸旓箑顪冮妶鍡楃瑨闁稿﹤顭烽幆宀勫幢濡炴洖缍婇弫鎰板醇椤愶絿绉锋繝鐢靛仜閹虫劖绻涢埀顒勬煛瀹€鈧崰鎾舵閹烘顫呴柣妯虹－娴滃爼姊绘担铏瑰笡闁圭顭烽幃鐑芥晝閸屾锕傛煕閺囥劌鐏犵紒顐㈢Ч閺屽秷顧侀柛鎾跺枎椤曪綁宕ㄦ繝鍕槇濠殿喗锕╅崢鐓庘枔瀹€鍕拺缂佸妫楃€氬嘲鈻撻弴銏＄厽闁规儳顕幊鍕煏閸パ冾伃鐎殿噮鍣ｅ畷鎺戔槈濞嗘垵娑ч梻鍌欒兌閹虫捇宕崸妤€绠犳慨妞诲亾鐎殿喖顭烽幃銏ゅ礂閻撳簼鐢婚梻浣告惈椤︿即顢栧▎鎰浄闁诡垎鈧弨浠嬫煟閹邦噮鏆柟灏佲偓瓒佺懓顭ㄦ惔婵嬪仐濡ょ姷鍋涢崯鎶剿囬崷顓涘亾鐟欏嫭绀€闁靛牆鎲￠幈銊╁焵椤掑嫭鐓ユ繛鎴灻顐︽煃鐠囧樊妲虹紒杈ㄦ崌瀹曟帒顫濋钘変壕闁归棿绀佺壕褰掓煙闂傚顦︾痪鎯х秺閺岀喖姊荤€靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戦敍鍕杭闁稿﹥鍨垮畷鐟懊洪鍛罕闂佺粯顭堢亸娆撳汲閿曞倹鐓忓┑鐐戝啫鏆欓柣蹇擄躬濮婅櫣绮欑捄銊ь唶濡炪倧瀵岄崹杈╃矉瀹ュ棎鍋呴柛鎰ㄦ櫇閸欏棝姊洪崫鍕窛闁稿鐩崺鈧い鎺嗗亾缂傚秴锕ら悾鐑藉箛椤撶姷鐦堝┑顔斤供閸橀箖宕ｉ崘銊㈡斀闁宠棄妫楅悘鐔兼偣閳ь剟鏁冮埀顒€宓勬繝闈涘€搁幉锟犳偂濞嗘挻鐓犻柟顓熷笒閸旀粎绱掗埀顒傗偓锝庡亝閸欏繐鈹戦悩鎻掓殲闁靛洦绻冮〃銉╂倷閺夋垵顫嶉梺璇″灡濡啴寮幇鏉跨倞闁冲搫鍊归鎾绘⒒閸屾艾鈧兘鎳楅崼鏇炵疇闁规崘顕ф惔濠囨煛鐏炶鍔撮柡浣稿椤潡鎳滈棃娑橆潓缂備胶濮甸悧鐘诲蓟閵娾晜鍋勯柛婵嗗珔閵忋倕鑸规い鏍仦閳锋垿鏌涢幇顒€绾ч柟顖氱墦閺屾稒绻濋崒銈囧悑閻庤娲忛崹浠嬪蓟閸℃鍚嬮柛鈥崇箲鐎氬ジ姊绘担鍛婂暈缂佽鍊婚埀顒佸嚬閸欏啫鐣烽幒妤€惟闁冲搫鍊婚崢閬嶆⒑閸濆嫬鈧湱鈧瑳鍐胯€垮ù鐓庣摠閻撴盯鏌涘☉娆愮凡闁绘挻鍔欓幃妤佹媴閸愩劋姹楅梺閫炲苯澧紒瀣浮閳ワ箓宕堕鈧崒銊╂⒑椤掆偓缁夌敻鍩涢幋锔界厽闁绘梻顭堥ˉ瀣煙閻ｅ苯鈻堥柡灞糕偓宕囨殕閻庯綆鍓涢惁鍫ユ倵鐟欏嫭绀冮柛銊ユ健閻涱喖螣閸忕厧鐝伴梺鍛婄懃椤﹁棄螞閻斿吋鈷掑〒姘ｅ亾婵炰匠鍤躲劑鍩€椤掑嫭鈷掗柛鏇ㄥ亜椤忣厾鈧鍠栭悥濂哥嵁閺嶃劍濯撮柛蹇擃槹鐎氳棄鈹戦悙鑸靛涧缂傚秮鍋撳┑鐐叉嫅缁插潡寮灏栨闁靛骏绱曢崣鍡涙⒑閸濆嫭澶勬い銊ユ閳诲秵绻濋崟銊ヤ壕閻熸瑥瀚粈鍐煕閵娿儳浠㈤柣锝囧厴閹垻鍠婃潏銊︽珜闂備胶顭堢悮顐﹀磹閺嶎厽鐓ラ柕鍫濐槹閳锋帒霉閿濆洨鎽傞柛銈呭暣閺屾盯濡搁妷锔藉闯婵炲濯寸粻鎾荤嵁閸℃凹妲惧┑陇顕滅紞浣割潖婵犳艾纾兼繛鍡樺灩閻涖垹鈹戦悙鏉垮皟闁搞儯鍔屾禍閬嶆⒑缁洖澧茬紒瀣灩缁鎮╃紒妯煎幍闂備緡鍙忕粻鎴﹀几閵堝應妲堥柟鎯х－瀛濋梻鍥ь樀閺岋綁骞橀搹顐ｅ闯闂佸湱鏅繛鈧柡宀嬬秮楠炴鎹勯悜妯尖偓鐐箾閿濆懏鎼愰柨鏇ㄤ簼娣囧﹪宕奸弴鐐碉紲濠殿喗锕╅崑鍕夊顑芥斀闁绘ɑ顔栭弳顖涗繆閹绘帗鍤囩€规洘鍨垮畷銊╊敍濠婂懐鍘梻浣筋潐瀹曟﹢顢氳缁牓宕卞☉娆戝幍闂佺粯鍨堕敃鈺佲枔閺冨牊鈷戦柛妤冨仦閸犳﹢鏌＄仦鐐鐎垫澘瀚板畷鐓庘攽閸℃ぅ鎴︽⒒娴ｇ懓顕滅紒瀣笧閸掓帡骞橀幇浣圭稁闂佹儳绻愬﹢杈╁閸忛棿绻嗘い鏍ㄧ閹牊銇勯銏ｅ妞ゎ亜鍟存俊鍫曞幢濡警妲遍梻浣告啞閻熴儵宕锔藉仼闁绘垼妫勯～鍛存煏閸繃鍣芥い銏犳嚇濮婅櫣绱掑Ο铏逛淮濠碘槅鍋呴悷褔鍩€椤掑嫭娑ч柣顓炲€搁～蹇撁洪鍜佹濠电偞鍨堕懝楣冦€傞崫鍕ㄦ斀闁宠棄妫楁禍婵囥亜閵娿儲顥㈡鐐茬墦婵℃悂鈥﹂幋鐐愵剛绱撻崒娆愮グ濡炴潙鎽滈弫顕€鏁撻悩鑼枃闂佺粯顭囩划顖炲吹鐎ｎ喗鐓熼柕蹇嬪灩娴狀垶鏌嶈閸撴瑩鏁冮敂鐐潟闁规儳顕悷褰掓煕閵夋垵瀚禍顏呬繆閻愵亜鈧倝宕㈡ィ鍐ㄧ婵せ鍋撻柟顔诲嵆椤㈡瑩宕叉径灞芥灈闁硅櫕鐗犻崺锟犲礃鐠恒劌绨ユ繝鐢靛Х椤ｈ棄危閸涙潙鍨傞柟鎯版閸屻劎鎲搁弮鍫熷仒妞ゆ柨妲堥弮鍫濆窛妞ゆ棁顫夌€氳棄鈹戦悙鑸靛涧缂佽弓绮欓獮澶愭晬閸曨剙顏搁梺璺ㄥ枔婵敻鎮￠弴銏犵閻庢稒顭囬埥澶愭煃瑜滈崜姘辨崲閸岀偞鍋╅柣銈庡灛娴滃綊鏌熼悜妯肩畺闁哄拋鍓熷铏圭磼濡搫顫戦柣蹇撶箲閻熲晠寮鍛闁靛繆妾ч幏娲⒒閸屾氨澧涚紒瀣尵缁鎮欓悜妯煎幈婵犵數濮撮崯鐗堟櫠閻㈠憡鐓欐い鏂垮帨閸嬫捇寮妷锔绘綌闂備線娼х换鍡涘焵椤掍焦鐏遍柛瀣崌瀹曞ジ寮撮悢鍝勫箺闂備礁缍婇崑濠囧储閼测晛绶ゅ┑鐘崇閻撳啴姊洪崹顕呭剱闁抽攱鍔楃槐鎺旂磼濡吋鍒涘Δ鐘靛仦閹瑰洭鐛幒妤€绫嶉柍褜鍓熼獮澶愭偂鎼搭喗瀵岄梺闈涚墕閸燁偅淇婇幖浣圭厱閹艰揪绲鹃弳顒侇殽閻愭彃鏆欓柍璇查叄楠炴ê鐣烽崶顒傚礈闂傚倷鑳堕幊鎾活敋椤撱垹纾婚柣妯肩帛閸庡苯霉閿濆鍋撳☉姘辩暰闂備線娼ч悧鍡椕洪妶鍛瘎闂傚倷鑳堕…鍫ヮ敄閸℃稒鍎庢い鏍亼閳ь兛绶氬浠嬪Ω閵壯呯嵁闂備礁缍婇崑濠囧礈濞戙垺鍋╅柛婵嗗閺€浠嬫煟濡鍤嬬€规悶鍎甸弻锝呂旈埀顒€螞濠靛鍋樻い鏇楀亾濠殿喒鍋撻梺鏂ユ櫅閸燁偄顕ｉ崹顔规斀閹烘娊宕愰幇鏉跨；闁瑰墽绻濈换鍡樸亜閹板墎鎮奸柟鍐叉喘閺屸剝鎷呴崫銉愌呪偓瑙勬礀閻栧ジ宕洪敓鐘茬妞ゅ繐娴烽梻顖炴⒒閸屾瑨鍏屾い顓炵墦瀵敻顢楅崟顒€娈炴俊銈忕到閸燁偊鎮為崹顐犱簻闁瑰搫绉堕崝宥夋煕婵犲啫濮夐柍褜鍓濋～澶娒哄鈧畷婵嗏枎閹惧磭鐣哄┑鐘诧工閻楀﹪宕靛澶嬬厪濠㈣泛鐗嗛崝妤呮煕鐎ｎ偅宕岀€规洜顭堣灃濞达絽鎼鎶芥⒒娴ｅ憡鎯堟繛璇х畵閵嗗啴宕ㄩ缁㈡锤闂佽鍨庣仦鎯х槣闂備線娼ч悧鍡欒姳閼测晞濮冲┑鐘崇閻撴洟鏌ｉ弬鎸庡暈閻忓骏闄勯〃銉╂倷閹绘帗娈诲Δ鐘靛仜濡粓藝閹绢喗鐓涢柛鈩冾殕椤ャ垽鏌＄仦鐣屝ユい褌绶氶弻娑㈠箻鐎涙娈ょ紓渚囧枟閻燂箑顕ラ崟顒傜瘈閹肩补鍓濋崐顖氣攽閻橆喖鐏辨繛澶嬬洴椤㈡牠宕堕鈧崒銊╂煙闂傚鍔嶉柛濠傜仛椤ㄣ儵鎮欓懠顑胯檸闂佸憡姊瑰畝鎼佸蓟濞戙垺鍋嗗ù锝夋櫜缁ㄥ吋绻涢敐鍛悙闁挎洦浜獮鏍亹閹烘垶宓嶅銈嗘尵婵妲?")
        if working_set_mode == "focused":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欓崑宥夋⒑閹肩偛濡肩紓宥咃躬瀵崵鈧綆鍠栭悙濠囨煏婵炑冩噽濡插洭姊婚崒姘偓鎼佹偋婵犲嫮鐭欓柟鐑橆殔缁犲綊鏌熼柇锕€鏋ょ痪鎯с偢閺岀喖鏌囬敃鈧獮妯荤箾閹绘帞鎽犻柟渚垮妽缁绘繈宕橀埞澶歌檸闁诲氦顫夊ú蹇涘礉瀹ュ洦宕叉繝闈涙处閸庣喖鏌曡箛瀣仾婵炲牓绠栧铏规嫚閺屻儺鈧鏌涘Ο鑽ょ煉鐎规洘鍨块獮妯肩磼濡厧骞嶉梻鍌氬€搁崐鎼侇敋椤撯懞鍥晜閸撗咃紲闂佺粯锚绾绢厽鏅堕鈧彁闁搞儜宥堝惈婵犵鈧磭鍩ｇ€规洘甯掗～婵嬵敃閵忊晜顥￠梻鍌氬€搁崐椋庣矆娓氣偓閹潡宕堕‖顒佺洴瀹曠喖顢涢埀顒勫炊椤掑鏅梺缁樺姌鐏忔瑩宕㈠ú顏呭€垫鐐茬仢閸旀碍銇勯敂鍨祮妤犵偛妫濋幃娆徢庨璺ㄧ泿闂備浇顫夋竟瀣疾濞戙垺鍊舵い鏃€绁硅ぐ鎺撳亹闁惧浚鍋勯埀顒佸姈閹便劍绻濋崘鈹夸虎闂佸搫鑻幊搴ㄥ煡婢跺娼╅柨婵嗘濞呭啴姊婚崒娆戭槮闁硅绻濆濠氬Ω閳哄倸鍓归梺绋跨灱閸嬫盯鎮橀幎鑺ョ叆闁哄洨鍋涢埀顒€鎲￠崕顐︽⒒娴ｅ摜鏋冩俊妞煎姂閹虫宕奸弴鈧崶銊ヮ嚤閻庢稒菤閹锋椽鏌ｆ惔鈩冭础濠殿喕鍗抽崺鈧い鎴ｆ娴滈箖姊绘担渚劸妞ゆ垵妫濋獮鎰板礈瑜庨～鏇㈡煙閻戞﹩娈旈幆鐔兼⒑闂堟侗妯堥柛鐘冲哺瀹曘儳鈧綆浜栭弨鑺ャ亜閺冨倶鈧寮ㄧ紒妯圭箚闁绘劘鍩栭ˉ澶愭煟閿濆洤鍘存い銏℃礋閺佸啴鍩€椤掑倻鐭嗛悗锝庡亖娴滄粓鏌熼柇锕€鏋涢柡瀣闇夋繝濠傜墢閻ｆ椽鏌″畝鈧崰鏍ь潖閼姐倐鍋撻悽娈跨劸濠碘€茬矙濮婅櫣绮欓崠锟犵反闂佺硶鏅滈悧婊堝箲閵忕姭鏀介悗锝庡亽濡啫鈹戦悙鏉戠仴鐎规洦鍓熷畷婊堝箥椤斿墽锛濇繛杈剧到閹碱偅鐗庨梻浣虹帛椤ㄥ牊绻涢埀顒傗偓娈垮枛椤兘骞冮姀銈呭窛濠电姴瀚倴婵犲痉鏉库偓褏寰婃禒瀣柈妞ゆ牜鍎愰弫浣衡偓骞垮劚椤︿即鍩涢幋鐘电＝濞达綀鍋傞幋鐘辩剨濞寸厧鐡ㄩ悡鐔兼煃閸濆嫸宸ラ柣蹇ュ閳ь剚顔栭崰娑㈩敋瑜旈崺銉﹀緞婵炪垻鍠栭弻銊р偓锝呯仛缂嶅矂姊婚崒娆戭槮闁硅绻濋妴鍐醇閵夈儳锛涘┑鐐村灦濮樸劍绋夊澶嬬厸閻忕偠顕ч崝婊堟煃闁垮鐏╃紒杈ㄥ笧閳ь剨缍嗛崑鎺楀磿閵夆晜鐓曢幖杈剧磿鏁堥梺鍝勬湰閻╊垱淇婇幖浣规櫆濠殿喗鍔掗搹搴繆閵堝洤啸闁稿鐩幃褔骞樼紙鐘电畾闂佸綊妫块悞锕傚疾濠婂牊鐓曢柟鐐殔閹冲繘锝炲畝鍕拻闁稿本鐟чˇ锕傛煙鐠囇呯瘈鐎规洘绻嗙粻娑樷槈濡椿妫熼梻浣侯焾閺堫剛绮欓幘姹団偓鍛存倻閼恒儳鍘棅顐㈡处濞叉牠锝炲澶嬬厸闁告劑鍔庢晶娑㈡煕鐎ｎ偄濮嶆慨濠傤煼瀹曞ジ鎮㈢悰鈩冿級婵犵數鍋涢惌鍫熺椤忓嫷娼栨繛宸簻閹硅埖銇勯幘璺烘瀻婵炲牆鑻埞鎴︽倷閸欏鏋欓梺鍛婄懃閸熸挳鐛崘鈺侇嚤闁圭⒈鍘介弲顏堟⒑闁偛鑻晶鎾煟濞戝崬娅嶆鐐村浮楠炲﹪鎼归锝庢闂佺硶鏂侀崑鎾愁渻閵堝棗绗掗柛濠呭吹娴滄悂鎮界喊妯轰壕妤犵偛鐏濋崝姘亜閿斿灝宓嗛柟顕嗙節瀵挳濮€閳ユ枼鍋撻崼鏇熺厽闁逛即鍋婇弶娲煕閵堝棛鎳囬柡灞界Х椤т線鏌涢幘纾嬪閻撱倝鏌ｉ弬娆炬疇闁搞倖娲橀妵鍕箛閳轰礁濮屾繛瀛樼矊缂嶅﹪寮婚悢鍏煎€绘俊顖濐嚙閻ㄦ垿姊鸿ぐ鎺撴暠婵＄偠妫勯～蹇撁洪鍛簵闁瑰吋鎯岄崰妤冪礊濡ゅ懏鈷戠紒瀣皡閺€缁樼箾閼碱剙鏋庢い鏇秮楠炴牗鎷呴崫銉悈闂備胶绮…鍥极閹间焦鏅繝濠傚枤濞撳鏌曢崼婵囶棡妞ゃ儱妫濋弻娑氣偓锝庡亜婵牓鏌ｅΔ鈧鎼佸煘閹达附鍊婚柛銉㈡櫅閸╁苯鈹戦悙鑼勾闁稿﹥绻堝顐﹀礃椤曞懏鏅滈梺鍓插亖閸ㄥ湱绮婇敃鍌涒拺闁告繂瀚ⅹ闂佸憡鏌ㄧ粔鐢稿礆婵犲嫧鍋撻棃娑欐喐缁炬儳銈搁幃妤呮晲鎼粹€崇缂佺虎鍘奸悥濂稿蓟閿濆應妲堥柟鐑樻尰閻濇洘绻涢敐鍛悙闁挎洦浜獮鍐ㄢ枎閹垮啯鏅滈梺鍛婃磸閸斿本绂嶆ィ鍐╃厸鐎规搩鍠栭張顒傜礊鎼淬垻绡€闁汇垽娼ф牎闂佺厧缍婄粻鏍箖閿熺姴鍗抽柕蹇ョ磿閸樺崬顪冮妶鍡楀闁稿﹥娲熷鍛婃償椤兛绨婚梺鍝勬祩濠⑩偓闁规煡绠栭弻鈥崇暆鐎ｎ剛鐦堥悗瑙勬礀閻栧吋淇婇悜钘壩ㄧ憸宀勬儉椤忓牊鈷掑ù锝囨嚀閳绘洟鏌￠埀顒勬焼瀹ュ懎鐎梺绉嗗嫷娈旂紒鐘崇墱閹叉悂鎮ч崼婵堢懆闂佺粯鍔曢敃顏堝蓟閺囩喓绠剧憸宥夊疮椤愩倗纾奸柍鍝勬噺閳锋帒霉閿濆懏鍟為柛鐔哄仱閺岋綁鎮㈤弶鎴濆Б闂侀€炲苯澧柛鎴濈秺瀹曘垺銈ｉ崘銊ь唹闂侀潧绻掓慨顓炍ｉ崼鐔虹闁糕剝锚婵洦銇勬惔銏″磳婵﹥妞藉畷銊︾節閸屾凹娼撻柣搴㈩問閸犳牠鎮ユ總鍝ュ祦闁哄稁鍘肩粻娑欍亜閺傚灝鈷旈柨娑欑矒濮婅櫣绱掑鍫ｂ偓鎸庣箾娴ｅ啿娲ら崙鐘崇箾閹存瑥鐏柣鎾寸洴閹﹢鎮欐０婵嗘婵犵鈧偨鍋㈤柡灞界Ч閹稿﹥寰勫Ο鎭嶏箓鏌ф导娆戝埌闁靛棙甯掗～婵嬫偂鎼达絼鎴烽梻浣筋嚃閸ｎ垳寰婄捄銊︻潟闁规崘顕х壕鍏肩箾閸℃ê濮夐柕鍫熷缁辨捇宕掑鍗烆暪闂佸憡顨呴崯鍧楁偩閻戣棄绠涙い鎴ｅГ閺傗偓闂佽鍑界紞鍡樼閿濆绠洪柡鍥ュ灪閳锋垿姊婚崼鐔恒€掑褎娲樻穱濠囶敃閿濆洦鍣伴悗瑙勬穿缂嶁偓缂佺姵绋戦埥澶娾枎閹存繂绠ラ梻鍌氬€风欢锟犲矗韫囨洜涓嶉柟杈剧畱閸屻劑鏌熺紒銏犳灍闁绘挻娲熼幃妤呮晲鎼粹€茬凹閻庤娲栭惉濂稿焵椤掍緡鍟忛柛鐘虫礈閸掓帒鈻庨幘鎵佸亾娴ｅ壊娼ㄩ柍褜鍓熼獮鍐ㄢ枎閹炬潙浠洪梻鍌氱墛缁嬫捇宕愰悙鐑樷拻闁稿本鑹鹃埀顒€鍢查湁闁搞儺鍓ㄧ紞鏍ь熆鐠轰警鍎戦柣婵嗙埣閺屾盯鍩勯崗鈺傚灥閳诲秹鎮╅崗鍛畾闂侀潧鐗嗛幊蹇涘闯濞差亝鐓曢悗锝庝簻閳ь剙娼″濠氭晲婢跺﹦鐫勯梺鍓插亞閸犳劙鎮靛畷鍥╃＝濞达絿鐡旈崵娆愪繆椤愶絿绠炵€殿喖顭峰鎾閻樿鏁规繝鐢靛█濞佳兾涘畝鍕；闁规崘顕у婵嗏攽閻樻彃顏存繛鎻掓啞娣囧﹪濡惰箛鏇炲煂闂佸摜鍣ラ崹鍫曞春濞戙垹绠ｉ柣妯兼暩閿涙繃绻涙潏鍓ф偧婵炲懌鍨虹粭鐔封槈濞嗘垹顔曢梺鍓插亞閸犳劙藟閸儲鐓涢悘鐐额嚙婵倻鈧鍠楅幐鎶姐€侀弮鍫濋唶闁绘洑璁查崑鎾愁吋閸モ晝锛濇繛杈剧悼椤牓鍩€椤掆偓閹芥粎鍒掗弮鍥ヤ汗闁圭儤鏌ㄧ粊锕傛⒑閸濆嫮袪闁告柨閰ｉ幃鐤亹閹烘挾鍘遍梺闈涱檧缁茶姤淇婇懞銉х闁告侗鍘炬晥濠殿喖锕︾划顖炲箯閸涘瓨鎯為柣鐔稿椤愬ジ姊绘担瑙勫仩闁告梹鍨甸…鍥樁闁诲繐顑呴埞鎴︽倷閺夋垹浠ч梺鎼炲妼缂嶅﹪骞婂鍡愪汗闁圭儤鎸鹃崢浠嬫⒑闂堟稓绠冲┑顔炬暬瀹曨垶鎮欓悜妯煎幈闁诲函鎬ラ崘銊㈡嫟缂傚倷鑳剁划顖滄崲閸愵亝宕叉繝闈涱儏绾惧吋鎱ㄥ鍡楀箺妞ゆ柨绉剁槐鎾诲磼濞嗘帒鍘℃繝娈垮枤閺佸骞冮敓鐘虫櫢闁绘灏幗鏇㈡⒑缂佹ɑ鐓ラ柟鑺ョ矒閹柉銇愰幒鎾跺幈濡炪値鍘介崹鐢稿几濞戞瑣浜滄い鎰╁灪閸犳ɑ鎱ㄦ繝鍛仩闁归濞€閸ㄩ箖鎼归銈勭敖缂傚倸鍊风欢锟犲窗濡ゅ懏鍋￠柍鍝勬噽瀹撲線鏌涢幇銊︽珖妞も晝鍏橀幃妤呮晲鎼粹€茬盎婵炲濮靛钘夘潖閸濆嫅褔宕惰娴煎牆鈹戦悙鏉垮皟闁告洦鍓欏鎸庣箾鐎电孝妞ゆ垵妫濋崺娑㈠箳濡や胶鍘遍柣蹇曞仜婢т粙骞婇崨顔轰簻闁挎柨銈稿顔剧磼缂佹绠為柛鈹惧亾濡炪倖甯掔€氼參鎮為懖鈹惧亾楠炲灝鍔氶柟铏姍閺佸秹鎮㈤崗灏栨嫼闂傚倸鐗婄粙鎾存櫠閺囥垺鐓欑€瑰嫰鍋婇崕蹇斻亜椤撶偞鍠樼€殿喕绮欓、姗€鎮㈤崫鍕疄闂傚倷鐒︾€笛兾涙笟鈧、姘愁樄闁绘侗鍣ｉ獮鍥偋閸垹骞堥梺璇插嚱缂嶅棝宕戦崨顖欑剨妞ゆ挾鍠嗘禍婊勩亜閹板墎鎮肩紒鐘靛仦閵囧嫰濮€閳藉懓鈧潡鏌熼鐣屾噰鐎规洩绲惧鍕偓锝庝簼閻ｅジ姊婚崒姘偓鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偞鐗犻、鏇㈡晜閽樺澹庡┑鐘绘涧閸婂鈥﹂崼銏㈢幓婵°倕鎳忛悡娆撴煙鐟欏嫬濮囬柣鎾村姈閵囧嫰顢曢敐鍡欘槹闂佸搫鐬奸崰鏍箖濠婂吘鐔兼倻濮楀棗鏅梻鍌欒兌缁垶寮婚妸鈺佺疅闁斥晛鍟崣蹇旂節婵犲倻澧涢柣鎾寸☉椤法鎹勯悮鏉戝婵炲濮伴崹浠嬪蓟閿濆牏鐤€閹艰揪缍嗗Σ顕€姊虹€圭媭娼愰柛銊ユ健楠炲啴鍩￠崨顓炵€銈嗗姧缁查箖鎯佹惔銊︹拻濞达絼璀﹂悞鐐亜閹存繃顥㈤柟顖氬椤㈡稑顫濇潏銊︻啎闂備線娼ч敍蹇涘焵椤掑嫬纾婚柟鍓х帛閺呮煡骞栫划鍏夊亾閼碱剚鏅肩紓鍌氬€烽懗鑸垫叏閻㈢纾块柟鎯版閻撴﹢鏌熸潏楣冩闁稿鍔欓弻鐔虹磼濡櫣鐟愮紓浣靛姀濡嫰鍩為幋锔藉€烽柟缁樺笚閸婎垶姊虹紒姗嗘畷妞ゃ劌鐗撻獮鎴﹀閻橆偅顫嶅┑顔筋殔濡寮查悩宸富闁靛牆妫欓ˉ鍡欌偓瑙勬礈閺佸骞嗛崟顒佸劅闁靛绠戦埀顒傛暬閺岋綁鎮㈤崫鍕垫毉闂佸摜鍠撻崑鐔烘閹烘梹瀚氶柟缁樺坊閸嬫捇宕稿Δ鈧弰銉╂煟閹邦剚鎯堢紒鐙呯秮閺屻劑寮崶顭戞婵炲瓨绮岀紞濠傤潖濞差亜鎹舵い鎾跺Т缁楋繝鏌ｉ姀鈺佺仚闁哄懏绮庨埀顒勬涧閵堟悂宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗙墛椤忕娀鎮介娑氭创闁哄瞼鍠栧畷銊︾節閸愩劌鏀柣搴ゎ潐濞叉﹢宕归崸妤冨祦婵☆垵鍋愮壕鍏间繆椤栫偞鏁遍悗姘矙濮婄粯鎷呮笟顖滃姼闂佸搫鐗滈崜鐔煎箖閻ゎ垼妯勯悗瑙勬礃缁诲倿顢樻總绋垮耿闁哄洨濮烽悾楣冩⒒娴ｈ櫣甯涢柛鏃€娲栭锝夊醇閺囩偟锛涢梺闈涳紡閳ь剟宕戦幘鑸靛枂闁告洦鍓涢ˇ銊х磽娓氬洤鏋涢柣顓炲€垮畷娲Ψ閿曗偓缁剁偤鏌熼柇锕€澧绘繛鐓庯躬濮婅櫣绱掑Ο鏇熷灱閵囨劙宕橀埡鍐炬锤闂佸壊鍋呭ú姗€鎮￠悢鍏肩厽闁哄倹瀵ч幉鎼佹煟椤撶儑鍔熺紒杈ㄥ笧缁辨帒螣韫囷絼閭柟顕€绠栭幃婊堟嚍閵夛附鐝冲┑鐘灱濞夋盯鏁冮妶鍥╃幓婵炴垯鍨洪悡鐔煎箹濞ｎ剙鐏柍顖涙礋閹筹綁濡舵径瀣幍闂佹眹鍊ら崹閬嶎敂閻樼數纾奸弶鍫涘妽鐏忎即鏌熷畡鐗堝殗鐎规洘绮撳畷锝嗙珶椤撱劎鐣遍柍瑙勫灴閸┿儵宕卞鍓у嚬婵＄偑鍊戦崝宀勬偋閹捐鏄ラ柍褜鍓氶妵鍕箳瀹ュ棛銈版繝銏ｎ潐閿曘垽寮诲☉銏狀潊闁挎稑瀚銊╂⒑缁洘鏉洪柛銊ょ矙閻涱喖螣閸忕厧鐝伴梺鑲┾拡閸撴稑顭囨径鎰拻濞达絼璀﹂悞楣冩煛閸偄澧伴柛鎺撳笚閹棃濡搁敂鑺ョ彨婵犵數濮撮敃銈夋偋婵犲洤鐓曢柟瀵稿Х绾捐棄霉閿濆懎甯ㄦ俊顐犲妽閵囧嫯绠涢幘璺侯暫闂佹眹鍊ら崳锝夊蓟濞戞粠妲煎銈冨妼閹虫﹢骞冮垾鏂ユ斀閻庯綆鍋嗛崢鎼佹⒑閹肩偛鍔橀柛搴ㄤ憾閹﹢顢旈崼鐔哄幗闂佽鍎抽顓灻洪幘顔界厵妞ゆ梹鏋婚懓鍧楁煙椤旂晫鎳囨俊顐㈠暙閳藉螖閳ь剟藟濮樿京纾介柛灞剧懆椤斿鏌涚€ｎ偅宕岄柡灞剧洴楠炲洭宕楅崫銉︽櫦缂備胶鍋撻崕鎶藉Χ閹间礁钃熼柨鐔哄Т缁€鍐煏婵炲灝鍔楅柛瀣崌楠炴牗鎷呯粙鍨婵犵數鍋為崹鍫曟偡閿濆棛顩叉繝濠傜墛閻撳繘鐓崶銉ュ姢缁炬儳娼￠弻宥夋寠婢舵ɑ效闂侀潧娲ょ€氫即銆侀弴銏℃櫜闁搞儮鏅濋弶鑺ヤ繆閻愵亜鈧垿宕瑰ú顏傗偓鍐幢濡ゅ﹤娈梺鍛婃处閸撴瑧娆㈤悙纰樺亾閸忓浜鹃梺閫炲苯澧撮柡浣哥Т閳藉濮€閳锯偓閹峰姊虹粙鎸庢拱闁煎綊绠栭崺鈧い鎺戝濡垶绻涢崱鎰仼妞ゎ偅绻堥、妤佸緞鐏炶棄楔闂佽崵鍠愮划宥呂涢崘顔惧祦闁告劦鍙庡Σ鑲╃磽娴ｈ櫣甯涚紒璇茬墕閻ｇ兘宕奸弴鐐嶁晠鏌曟径鍫濃偓妤呭汲濡ゅ懏鈷掗柛灞剧懆閸忓矂鏌涚€ｃ劌濮傜€规洘娲熷濠氬Ψ閵壯屾Ф婵犳鍠楅敃鈺呭礈閿曞倹鍊垮ù鐘差儐閻撴稓鈧箍鍎辨鎼佺嵁濡ゅ懏鐓熼柟鍨缁夘噣鏌ｉ幙鍐ㄤ喊鐎规洖鐖兼俊鎼佹晝閳ь剟妫勫澶嬬厽闁绘ê鍟挎慨褏绱掔紒妯肩疄鐎殿喖顭烽弫鎰緞濡粯娅嶉梻浣虹帛濮婂宕曢妶澶婇棷濞寸厧鐡ㄩ埛鎴︽偣閸ワ絺鍋撻搹顐や邯缂傚倸鍊哥粔鎾晝椤忓牊鍋樻い鏃傛櫕閻熷綊鏌嶈閸撶喖鎮伴鈧獮鎺懳旈埀顒傜不閿濆棛绡€闁割煈鍋勬慨澶愭煃瑜滈崜鐔煎绩鏉堛劎鈹嶅┑鐘叉处閸婇攱銇勮箛鎾愁仱闁稿鎹囧鍊燁檨婵炲吋鐗滈幉鎼佹偋閸繄鐟ㄩ梺鎼炲妼閸婂潡寮婚敐澶婎潊闁靛繆鏅濋崝鎼佹⒑缂佹ɑ灏伴柨鏇樺灲瀵鎮㈤崨濠勭Ф婵°倧绲介崯顖烆敁瀹ュ鈷戠紒瀣皡閸旂喖鏌涜箛鏃撹€跨€殿喛顕ч埥澶娢熼柨瀣偓濠氭椤愩垺绁紒鎻掑⒔閻熝冣攽閻樺灚鏆╅柛瀣洴楠炲﹤鐣濋崟顐わ紮闂佸搫娲㈤崹褰掓偂濮椻偓閺岀喐娼忔ィ鍐╊€嶉梺绋匡功閸忔﹢骞冪憴鍕╁亰闁圭瀵掓禒鈺佲攽椤曞棛绁烽柛銊ㄦ椤繐煤椤忓嫪绱堕梺闈涱槶閸庢盯濮€閵堝棌鎷洪柣銏╁灱閸犳氨绮旈鈧弻鏇㈠幢閺囩媭妲銈庡亝缁诲牓骞婂鍫濆瀭妞ゆ劧绲胯ぐ鍛婄節閻㈤潧袨闁搞劎鍘ч埢鏂库槈閵忊剝娅囬梺鎸庢礀閸嬪棝寮繝鍥ㄧ厵闂侇叏绠戦獮妯肩磼閻樿崵鐣虹€殿喖鐖煎畷鐓庘攽閸″繑瀵栭梻浣告啞鐢﹪宕￠幎钘夎摕闁绘柨鍚嬮崵宥夋煏婢诡垰鎳愰崢婊堟⒑閼恒儔鎴犳崲閸儱钃熼柡鍥╁枔缁犻箖鏌ｉ幇闈涘闁绘繃娲熷娲箮閼恒儲鏆犻梺鎼炲妼濞尖€愁嚕鐠囨祴妲堥柕蹇曞Х閻も偓婵＄偑鍊栧濠氬磻閹惧墎纾奸柣娆愮懃濞诧箓鎮″▎鎰╀簻闁哄秲鍔嶉惃鎴濐熆瑜濈粻鎾诲蓟閿涘嫪娌柛鎾楀嫬鍨遍梻浣筋嚃閸犳帡寮插┑瀣劦妞ゆ巻鍋撴繝鈧潏銊﹀弿闁圭虎鍟熸径濞炬斀閻庯綆鍋€閹峰姊洪幖鐐插妧閻忕偤鏁弸鍛存⒒娴ｅ憡鎯堥柡鍫墴閹嫰顢涘鐓庢闂佸湱铏庨崰鏍ㄥ劔闂備線娼ч敍蹇涘磼濠婂嫭姣庨梻鍌氬€搁崐鐑芥嚄閸撲礁鍨濇い鏍仜缁犳澘螖閿濆懎鏆欑紒鎰殜閺屸€愁吋鎼粹€崇闂佽棄鍟伴崰鏍蓟閵娿儮鏀介柛鈩兠弲鐢告⒑缂佹ɑ鈷掓い顓炵墢濞嗐垽鎮欓悽鐢碉紲闁诲函缍嗛崑鍕敋濠婂牊鐓曢幖娣灪鐏忔澘菐閸パ嶈含闁诡喗鐟╅、鏃堝礋閵娿儰澹曢悷婊冪箻楠炲繒鈧綆鍠楅弲鎻掝熆鐠轰警鍎岄柟绋垮暣濮婃椽宕ㄦ繝鍐槱闂佸憡顭堝Λ鍕偩閻戣棄鐭楀璺虹灱閻﹀牓姊婚崒姘卞濞撴碍顨婂畷鏇＄疀濞戞瑧鍘介梺鍦劋閸ㄨ绂掑☉銏＄厪闁搞儜鍐句純濡ょ姷鍋炵敮鎺楊敇婵傜鐐婄憸宥夆€栨径宀€纾介柛灞捐壘閳ь剙鎽滅划鏃堝级閹炽劍妞介、姗€濮€閻樼儤鎲伴柣搴＄畭閸庨亶藝椤栨稑顕遍柣妯肩帛閻撴洟鏌￠崶銉ュ濞存粍绻冪换娑㈠醇濠靛牆鐓熷┑顔硷龚濞咃絿妲愰幒鎳崇喖鎼归崷顓熷櫙闂傚倷绀侀幉锟犳嚌妤ｅ喚鏁勯柛銉墮缁犳煡鏌曡箛鏇炐涢柡鈧禒瀣€甸柨婵嗙凹閹茬偓绻涢悡搴含婵﹥妞介獮鎰償閿濆洨鏆ゆ繝纰樻閸嬪懘鎯勯娑楃箚闁圭虎鍠栫粻娑㈡煟濡も偓閻楀繘宕㈡ィ鍐┾拺闁煎鍊曢弸鏂款熆瑜庨〃鍛存晝閵忋倕绾у鐟板暱闁帮絽鐣烽幆閭︽闂傚鍓﹂崜姘躲€冮妷鈺傚€烽悗娑櫭壕鍐参旈悩闈涗沪閻㈩垪鈧剚鍤曟い鎺嶇劍閸庣喖鏌熼幆褍鏆辩紒鍫嗗洦鈷掗柛灞捐壘閳ь剟顥撶划鍫熺瑹閳ь剟鐛弽顓ф晝闁挎棁妫勯崜鑸电節闂堟稑鈧鈥﹂崼銏㈢幓婵°倕鎳忛悡娑氣偓骞垮劚妤犳悂鐛Ο灏栧亾鐟欏嫭灏紒鑸靛哺瀵鈽夐姀鐘靛姶闂佸憡鍔戦崝灞叫掗崼婵冩斀闁斥晛鍟伴崣鈧紓浣哄У閻楁洟锝炶箛鎾佹椽顢旈崟顓у敹闂佺澹堥幓顏嗗緤閸濆嫀锝夊醇閵忋垻锛濇繛杈剧到婢瑰﹤危濞差亝鐓欓柧蹇ｅ亝瀹曞矂鏌熼鈧粻鏍箖濠婂懐椹抽悗锝庡亝濞呮牗绻濋悽闈浶㈤柨鏇樺€濋獮濠囧箛閻楀牆浜楅梺鍦亾閺嬪ジ寮ㄦ禒瀣厽闁归偊鍓欑痪褎銇勯妷褍鈻堥柡灞剧〒閳ь剨缍嗛崑鍛焊閻㈠憡鐓冪憸婊堝礈閻斿鐒界憸鏃堝箚瀹€鍕＜婵ê鍚嬬紞搴♀攽閻愬弶鈻曞ù婊勭箞钘熼柛顐ゅ枔缁犻箖鏌熺€电浠╁瑙勆戦妵鍕晲閸℃ǜ浠㈠┑顔硷龚濞咃絿鍒掑▎鎾崇闁炽儱鍟块～鐘绘⒒娴ｄ警鏀版繛鍛礋楠炴垿宕堕鈧弰銉╂煏韫囨洖顎岄柛姘儏椤法鎹勯悮鏉戝闂佹椿鍋勭€氭澘顫忛搹鍦煓闁圭瀛╅幏杈╃磽娓氬洤鏋涢梺甯秮瀵偄顓奸崪浣哄弳闂佸壊鍋嗛崯鍧楀箯閾忓湱纾介柛灞剧懅閸斿秹鏌ㄩ弴妤佹珚闁诡喚鍋ら幃娆擃敆閸屾粠鍟庨梻浣告啞娓氭宕板Δ鍐焼闁逞屽墴濮婄儤瀵煎▎鎴濆煂闂佹悶鍨洪悡锟犲箖閹€鏀介悗锝庝簽椤︽澘顪冮妶鍡楃瑨闁稿﹥鎮傞悰顔嘉旀担铏圭槇闂佹眹鍨藉褎绂掗敃鍌涚厱闁靛ň鏅滃☉褔鏌ｉ敐鍥у幋妞ゃ垺顨婂畷鐔碱敃閵忕姵顓婚梻鍌欒兌缁垶寮婚妸鈺佽Е閻庯綆鍠楅崑鍌涚箾閸℃ê濮傚ù婊勭矒閺屸€愁吋閸愩劌顬嬮梺鎰佸灡濞叉﹢濡甸崟顖毼ㄩ柕澹喚鏆梻浣哥枃椤宕归崸妞尖偓浣糕枎閹炬潙浠俊顐︻暒缁€渚€藟濮樿埖鈷掗柛灞捐壘閳ь剟顥撳▎銏狀潩椤掑鍔烽悷婊冪箻楠炴垿濮€閵堝懘鍞堕梺闈涱槶閸庨亶鎮楅銏＄厽闁绘ê寮堕幖鎰偓娈垮櫘閸撶喖寮幇顓炵窞濠电姴瀚埀顒傚仜椤啴濡堕崱妤冪憪闁荤姳鐒﹂悡锟犵嵁韫囨洜纾兼俊顖濆亹椤旀洟鏌℃径濠勫濠⒀傜矙瀹曟碍瀵肩€涙鍘甸柣鐘叉厂閸涱垳妲囬柣搴ゎ潐濞诧箓宕归崼鏇炵畺婵炲棙鍨冲▽顏堟煕鐏炵虎娈斿ù婊堢畺閺岀喖鎮滃Ο铏瑰姼濠电偛鐨烽弲婊堝Φ閸曨垰绠绘俊銈傚亾閻庢凹鍣ｅ鎯般亹閹烘挾鍘介柟鍏肩暘閸娿倕顭囬幇顓犵闁圭粯甯炵粻鑽も偓瑙勬礉椤绮嬮幒鏂哄亾閿濆骸澧紒渚婄畵濮婅櫣鍖栭弴鐐测拤缂備礁顑呴悧鎾诲春閳ь剚銇勯幒宥堝厡濠⒀冪仛閵囧嫰濮€閳藉棙鐣风紓浣虹帛缁诲牆鐣烽悢纰辨晝闁靛繈鍨圭敮鎾绘⒒閸屾瑨鍏岀紒顕呭灦楠炴劙宕奸弴鐐碉紮闂佸搫绋侀崢鍏碱攰闂備礁鎲″ú锕傚窗濮樿埖鍋柍褜鍓熷娲捶椤撶偘澹曞┑鐐插悑閻熴儵鍩㈠鍛斀閻庯綆鍋€閹锋椽鎮峰鍛暭閻㈩垱顨婂顐ｆ綇閵娿倗绠氶梺缁樺姌閸╂牠藟婢跺浜滄い鎰╁灮缁犲鏌熼悡搴㈣础闁瑰弶鎸冲畷鐔碱敃閵忕姷顔夐梻鍌氬€风粈渚€骞夐埄鍐懝婵°倕鎳庨崒銊╂煕濠靛棗鐝旂憸宥堢亙闂佸憡渚楅崰鎺楀箯閾忓湱纾藉ù锝呭閸庢劖銇勯幋鐐垫噰鐎规洘娲熼獮鍥偋閸垹骞楅梻浣稿暱閹碱偊鏁冮妶澶嬪€堕柣妯肩帛閻撶喖鏌ㄥ┑鍡樺櫣婵℃彃顭烽弻宥囨喆閸曨偆浼岄悗瑙勬礋娴滃爼宕洪敓鐘茬＜婵﹩鍓欑敮顏堟⒒閸屾艾鈧兘鎳楅崼鏇炲偍鐟滄棃鐛Δ鈧…銊╁醇濠靛洨鈧剟姊鸿ぐ鎺擄紵缂佲偓娓氣偓瀹曟帡濡搁妷鍐ㄧ秺閹晛顔忛鐓庡闂備胶绮幐濠氭偡閳哄懎钃熼柨婵嗩槸缁狅綁鏌ｈ箛鏃€銇熷ù婊庝邯瀹曟椽濮€閵堝懎宓嗛梺缁橈供閸嬪嫭绂嶆ィ鍐╁仭婵炲棗绻愰顏嗙磼閳ь剟宕橀鍡欙紲闁荤姴娲﹁ぐ鍐焵椤掆偓濞硷繝濡存担鍓叉建闁逞屽墮閻ｅ嘲螖閸涱喖浜楅柟鑹版彧缁插潡鎮伴灏栨斀闁绘ê鐏氶弳鈺佲攽椤旂⒈鍤熼柍褜鍓氶懝楣冨床閹绘帒绁梻浣告惈椤︿即宕归悢鐓庣哗濞寸姴顑嗛悡鐔镐繆椤栨繃顏犲ù鐘崇洴閺岋繝宕辫箛鏃€鐝旈梺瀹狀潐閸ㄥ潡銆佸▎鎾村殟闁靛／鍛瀼闂備胶绮幐鍫曞磹濠靛钃熼柕濞炬櫅閸楁娊鏌ｉ幇顓犮偞闁稿鎹囧畷顐﹀Ψ瑜岀粭澶娾攽椤旂瓔鐒鹃柛鈺傜墵閹繝鎮㈤崗鑲╁幍闂備緡鍙忕粻鎴﹀几濞戙垺鐓曢柡鍌涱儥閸庢棃鏌″畝瀣М妤犵偞顭囬埀顒佺⊕椤洭藝娴煎瓨鈷戠紓浣股戦幆鍕煕鐎ｎ亷宸ラ柣锝囧厴瀹曞ジ寮撮悙宥佹櫊閺屻劑寮崶顭戞闂佸憡鎼╅崰妤冩崲濠靛棭鍤楅柡瀣靛亜閳ь剚娲熼幆鍐倻濡晲绨诲銈嗘尵閸嬬喐鏅堕敂鐣岀瘈闁逞屽墯閹峰懐鍖栭弴鐔告澑闂備胶绮…鍫ヮ敋濠婂喚鍟呴柕澶嗘櫆閻撶喐淇婇妶鍌氫壕缂備胶绮敃銏ょ嵁閸愵喖绠氭い顑藉墲濡炰粙銆侀弮鍫濆窛妞ゆ牗鑹剧粻浼存⒑鐠囨煡顎楅柛妯荤矒瀹曟垿骞樼紒妯衡偓鐢告煥濠靛棝顎楀褎澹嗛幃顕€鏁冮崒娑掓嫽婵炶揪绲块悺鏃堝吹閸愵喗鐓曢柣妯挎珪瀹曞瞼鈧娲濋～澶岀矉閹烘柡鍋撻敐搴濈敖闁伙絾妞藉娲棘閵夛附鐝旈梺鍝ュ櫏閸ㄨ泛鐣烽弴銏″亜闁告縿鍎抽惁鍫ユ⒒閸屾氨澧涚紒瀣浮钘熼柣鎰劋閻撶喖骞栫划鍏夊亾閾忣偅鐦ｉ梻浣哥枃椤宕归崸妤€绠栭柍鍝勬噹閸ㄥ倹銇勯幇鍓佺ɑ闁伙箑閰ｅ缁樻媴娓氼垳鍔稿銈嗗灥濞诧妇鎹㈠☉銏犵劦妞ゆ帒鍊甸崑鎾舵喆閸曨剛顦ㄩ梺鎼炲妼濞硷繝鎮伴鈧畷鍫曨敆閳ь剛鐥閹綊骞侀幒鎴濐瀷閻庤娲栭悥鐓庮潖缂佹ɑ濯撮柛娑橈攻閸庢挾绱撴担鍓插剮缂佽埖鑹鹃悾鐑藉閿涘嫰妾梺鍛婄☉閿曘倝鎮?")
        elif working_set_mode == "broad":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欑粣娑㈡⒑閸濄儱校闁圭澧介崚鎺旂磼濡浜濋梺鍛婂姀閺呮繈宕㈡禒瀣拺闂侇偅绋戝畵鍡樼箾娴ｅ啿瀚▍鐘炽亜閺嶎偄浠﹂柣鎾跺枑缁绘繈妫冨☉娆忣槱缂備讲鍋撻悗锝庡亝閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濮风槐鎺楊敊閻ｅ本鍣ч梺瀹狀嚙闁帮綁鐛崱姘兼Щ婵犮垼顫夐敋闁宠鍨块幃娆撴嚑椤掍焦鍠栫紓鍌欑贰閸犳碍鎱ㄩ悽鐢电焿鐎广儱顦介弫鍌炴煕閺囥垺娑ф繛鍫涘姂閺岋綁鎮╅崣澶婎槱缂備椒鐒﹀娆忓祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔告倐濮婃椽宕ㄦ繝鍐ｆ嫻闂佸湱顭堥崯鍧楋綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愬宀婃澓濠电姷鏁搁崑娑㈡偤閵娧冨灊鐎广儱顦伴崑瀣煛閸モ晛浠滅紒渚囧亰濮婄粯鎷呯粙娆炬闂佺顑勭欢姘暦瑜版帗鍤掗柕鍫濇媼濡粓姊洪懞銉冾亪藟閵忥絻浜归柟鐑樻尰濞呮粓姊虹化鏇炲⒉妞ゃ劌鐗忕划濠囨煥鐎ｎ剛顔曢柣搴㈢⊕椤洭鎯岄幒鏃傜＜闁绘ê纾晶顏呫亜椤愩垻绠婚柟鐓庣秺瀹曠兘顢橀悩闈涘箚闂傚倷绀佸﹢閬嶁€﹂崼鈶╁亾濞戞帗娅婃鐐茬箻瀹曪繝鎮滈崱妯虹槣闂備線娼ч悧鍡椢涘▎鎴濐棜闁归棿鐒﹂悡鏇㈡煏婵炲灝鍔橀柛瀣ㄥ灩閳规垿鏁嶉崟顒佹瘓濡ょ姷鍋涘ú顓烆嚕閸撲焦宕夋い顓熷灥閺佷粙姊婚崒娆愮グ妞ゎ偄顦靛畷鏇㈠箮閼恒儱浠遍梺闈浥堥弲婊堝磻閻斿吋鐓欓柟顖涙緲琚氶梺鎶芥敱鐢帡婀侀梺鎸庣箓閻楁粌顭囬幇鐗堢厱閻庯綆鍓欓埢鍫ユ煛鐏炲墽鈯曢柟顖涙椤㈡瑩宕楅懖鈺佺秵闂佽瀛╅鏍窗濡ゅ嫨浜归柛鎰靛枓閳ь剨绠撴俊鎼佸煛娓氣偓閸炶泛鈹戦悩缁樻锭闁绘绻樺鎼佸焵椤掆偓閳规垿鎮╅幇浣告櫛闂佸摜濮甸〃濠冧繆闂堟稈妲堥柕蹇曞Х閿涙盯姊虹憴鍕姢闁宦板姂瀹曪綀绠涢幘顖涙杸闂佺粯蓱瑜板啴寮抽悙鐑樼厪闁搞儯鍔庣粻姗€鏌嶈閸撴繈锝炴径濞掓椽鏁冮崒姘憋紱婵犵數濮撮崯鈺冩崲閸℃稒鐓熼柟杈剧稻椤ュ宕鐐粹拺闁圭瀛╅ˉ鍫ユ煛娓氬洤娅嶇€规洘鍨块獮妯尖偓闈涙憸閻﹀牆鈹戦鏂や緵闁告ɑ鎮傞獮蹇撁洪鍛嫼闂佺厧顫曢崐鏇㈠几閹寸偟绡€闁靛繆妲勯懓璺ㄢ偓娈垮枟婵炲﹪寮婚崱妤婂悑闁糕€崇箲鐎氬ジ姊哄Ч鍥х労闁搞劌銈稿畷鏉款潩鐠鸿櫣顦繛瀵稿帶閻°劑鎮￠妷鈺傜厸闁搞儺鐓侀鍫熷€舵い蹇撴绾惧吋淇婇妶鍛殭闁哄鐩弻娑㈠煘閹傚濠碉紕鍋戦崐鏍ь啅婵犳艾纾婚柟鐐暘娴滄粍銇勯幇鈺佺伄缂佺姳鍗抽幃锟犲Χ閸℃劒绨婚棅顐㈡处閹告悂顢旈锝冧簻闁哄倹瀵ч崰姗€鏌″畝鈧崰鏍箠濠靛鍋嬮柛顐ｇ箖闁款厾绱撻崒娆戝妽鐟滄澘鍟…鍥晸閻樿尙鐣烘俊銈忕到閸燁垶藟閸喓绠鹃柟瀵稿仜缁楁岸鏌￠崒妤€浜鹃梻鍌氬€烽懗鍓佸垝椤栫偛绀夋俊顖炴？閻掑﹥绻涢崱妤呯崪闁兼澘娼￠弻鐔虹磼閵忕姵鐏嶉梺缁樻尰濞叉牠鍩為幋锔藉亹闁圭粯甯楀▓鍓佺磽娴ｅ搫啸闁稿鍠栭崺鈧い鎺戝枤濞兼劖绻涢崣澹濐亪鈥旈崘顔藉殟闁靛绠戝鍧楁⒑闁偛鑻晶鎾煛鐏炵偓绀嬬€规洜鍘ч埞鎴﹀炊瑜庨悾濠氭⒒娴ｅ憡鎲搁柛瀣洴閹儵鎮℃惔顔界稁濠电偛妯婃禍婵嬎夐崼鐔虹闁硅揪缍侀崫鐑樸亜鎼粹剝顥炵紒缁樼箘閸犲﹤螣瀹勯澹曢梺鎯ф禋閸嬪嫰寮搁悩缁樺€甸悷娆忓绾炬悂鏌涢妸銈囩煓闁绘侗鍠栬灒闁兼祴鏅濋敍婊冣攽閳藉棗鐏ユ俊妞煎姂閹晫绱掑Ο鑲╃槇闂佹眹鍨藉褍鐡梻浣瑰濞插繘宕愬Δ鍛劦妞ゆ帊绀侀崵顒勬煕閿濆繒绉鐐叉閻ｆ繈宕熼銈庡敽闂備礁鎼崐鎼佸箹椤愶絿顩插Δ锝呭暞閸嬧剝绻涢崱妤冪妞ゅ浚浜炵槐鎺楀焵椤掑嫬绀冩い蹇撴閿涙粌顪冮妶鍡橆梿闁稿鍔欓幃鐐哄箹娴ｅ湱鍘遍梺宕囨嚀閻忔繈鎮橀鍫熺厵妞ゆ牗绋掗ˉ鍫濃攽閳╁啯鍊愬┑锛勬焿椤т線鏌涢悢濂夊剶闁哄矉绲鹃幆鏃堝Χ鎼淬垻绉锋繝鐢靛仜瀵爼鎮ч弴銏＄畳闂備礁鎲″ú锕傚储娴犲缍栭柡鍥╁枂娴滄粓鏌￠崶顭戞當濞存粍鍎抽埞鎴︻敊绾嘲濮涚紓渚囧櫘閸ㄥ爼鐛箛娑樺窛闁哄鍨电粣娑欑節閻㈤潧孝闁稿﹦鎳撻埢鎾澄熼懖鈺冿紳闂佺鏈悷褔藝閿曞倹鐓欑痪鏉垮船娴滄粍銇勯鐐村枠闁搞劍鍎抽悾鐑藉炊閵婏富鍟庨梻鍌欑閹碱偄煤閵忋倕鏄ラ柛鏇ㄥ灠閺嬩線鎮楅敐搴℃灍闁绘挸鍟伴幉绋款煥閸繄顦┑鐐叉閹稿宕戦埡鍛厽闁硅揪绲鹃ˉ澶岀磼閻欏懐绉柡灞诲姂瀵潙螖閳ь剚绂嶉崜褏纾藉ù锝呮惈瀛濆銈庡幘閸忔ê顕ｆ繝姘у璺猴功椤旀劖绻涙潏鍓хК妞ゎ偄顦甸弻銊╊敇閵忊檧鎷洪梺鍛婄箓鐎氱兘宕曡箛娑欑厱濠电姴鍊绘禒銏°亜椤愩垻绠伴悡銈嗐亜韫囨挸顏╃紒鎰⊕缁绘繈鎮介棃娴躲垽鏌涢悤浣镐喊閽樻繈鏌嶉崫鍕櫤闁抽攱鍨圭槐鎺斺偓锝庡亽閸庛儵鏌涙惔锛勭劯闁哄本绋撻埀顒婄秵閸嬪懎鐣风仦鐐弿濠电姴鍟妵婵堚偓瑙勬处閸嬪﹤鐣烽悢鍏碱棃婵炴垶锚椤ュ酣姊婚崒娆愮グ鐎规洜鏁诲畷顖炲锤濡も偓閻ょ偓绻涢幋顓熺窙缂傚秵鐗犻悡顐﹀炊閵娧€濮囬梺璇″灣閸嬨倝骞冨畡鎵虫瀻闊洦鎼╂禒濂告⒑閸涘⊕顏嗙礊婵犲偆娼栨繛宸簻瀹告繂鈹戦悩杈厡缂佽绶氬娲传閵夈儛锝吳庨崶銊︺仢濠碉紕鏁婚獮鍥敍閿濆柊鈺呮⒒娴ｅ摜鏋冩い顐㈩樀瀹曞綊宕稿Δ鈧粻鏍ㄧ箾閸℃ê鐏︾€规洖顦甸弻褑绠涘鍏肩秷濡炪倖娲橀〃濠傤潖缂佹ɑ濯撮柛娑橈攻閸犳劖绻濆▓鍨灍闁瑰憡濞婂缁樼節閸ャ劍娅滄繝銏ｆ硾閻楀啴宕戦幘瀛樺闁告挸寮堕崓鐢告⒑閼测晩鐒鹃柣蹇旇壘閳诲秴顭ㄩ崟顓犵槇闂侀潧楠忕徊浠嬫偂閹扮増瀚呴梺顒€绉甸悡娑㈡煕濞戝崬浜滈柣蹇撳级閹便劍绻濋崘鈹夸虎閻庤娲忛崝宥囨崲濠靛绀冩い顓熷灦琚╅梻鍌氬€烽懗鍫曗€﹂崼銉晞闁告侗鍨崑鎾愁潩椤愩垹绁Δ鐘靛仜閸燁偉鐏冮梺鍛婄矆閻掞箓寮查敐澶嬧拺缂備焦锚閻忋儲淇婇锝囨噮闁逞屽墴濞佳囨儗閸屾凹娼栨繛宸簼椤ュ牊绻涢幋鐐跺妞わ絽鎼埞鎴﹀煡閸℃ぞ绨奸梺鑽ゅ暱閺呯娀鐛崘銊庣喓鎮伴埄鍐╂澑闂佽鍑界紞鍡涘磻閸℃稑鍌ㄩ梺顒€绉甸埛鎴︽煕濠靛棗顏€瑰憡绻堥弻娑氣偓锝庡墮閺嬫垹绱掗崒娑樼瑨闁宠棄顦垫慨鈧柨娑樺楠炴姊绘笟鈧褔鎮ч崱娆屽亾濮樼厧鏋ょ紒顕嗙秮瀵噣鍩€椤掑嫬绠為柕濠忓缁♀偓闂佸憡鍔忛弬鍌涚閵忋倖鍊甸悷娆忓婢跺嫰鏌涚€ｎ亷宸ラ柣锝囧厴閹垻鍠婃潏銊︽珝闂備胶绮摫鐟滄澘鍟冲鏇犵磽閸屾艾鈧悂宕愰幖浣哥９闁绘垼濮ら崵鍕煕閹捐尙顦﹂柛銊︾箖閵囧嫰寮介妸褏鐓侀悗瑙勬礃閻擄繝寮诲☉妯兼殕闁逞屽墴瀹曟垿鎮欓崫鍕紱闂佸啿鎼幊蹇涙偂閻斿吋鐓欓弶鍫濆⒔缁嬬粯銇勯妷銉█婵﹥妞藉畷锟犳倷閺夋垶鐏庨梻浣告惈閻鎹㈠┑鍡欐殾闁割偅娲栭悡娑樏归敐鍡楃祷濞存粓绠栭弻銊モ攽閸♀晜笑闂佺粯鎸婚惄顖炲蓟濞戞ǚ妲堥柛妤冨仦閻忔捇姊洪崨濠勬噧婵☆偅绻傞～蹇撁洪鍕炊闂佸憡娲﹂崑鈧柛瀣崌楠炴牗鎷呴悷鎵冲亾閼哥數绡€闂傚牊渚楅崕蹇涙煟閹惧瓨绀嬮柡宀嬬節瀹曟﹢濡歌椤も偓闂備胶绮幐鎼佸疮閹绢喖绠栫憸鐗堝笒閻愬﹥銇勮箛鎾愁伀婵絻鍨荤槐鎾存媴閸濆嫅锝囨喐閺夊灝鏆㈢憸棰佺窔濮婃椽骞栭悙鎻掑Η閻庡箍鍎遍悧鍡涘箚閸儲鈷掑ù锝囩摂閸ゅ啴鏌涢悩鎰佹疁闁诡喚鍏橀崺锟犲川椤愮喎浜惧〒姘ｅ亾鐎殿噮鍣ｅ畷鐓庘攽閸偅效闂傚倷绶氬褔鈥﹂崼銉ョ？闁绘鐗忛悵鍫曟煛閸ャ儱鐏柍閿嬪灴閺屾稑鈹戦崱妤婁紓闂佽皫鍌滅獢闁诡喗锕㈤幃娆撳箵閹哄棙瀵栫紓鍌欑椤戝嫮娆㈠顒夋綎缂備焦蓱婵挳鏌﹀Ο渚Ц闁诡垳鍋ゅ娲传閵夈儛锝夋煕閺冣偓椤ㄥ﹪宕洪埀顒併亜閹哄秵绁板瑙勶耿閺岋絽螖閳ь剙螞濠靛鏄ラ柕澶涚畱缁剁偤鏌熼柇锕€澧绘繛鐓庯躬濮婅櫣绱掑Ο鏇熷灴椤㈡瑩寮介‖顒婄秮閹囧醇濠婂懐鐣鹃梻浣虹帛閸旓附绂嶅鍫濈劦妞ゆ帊鑳舵晶顏堟懚閻愬眰鈧帒顫濋敐鍛闁诲氦顫夊ú姗€宕归崸妤冨祦闁搞儺鍓氶崑瀣煕椤愶絿绠戦柟顕嗙到閳规垶骞婇柛濞у懎绶ゅù鐘差儏閻ゎ喗銇勯弽顐粶闁绘挻娲熼弻鐔告綇妤ｅ啯顎嶉梺缁樻尰濞叉鎹㈠☉銏犵闁绘垵娲ら崣鏇㈡倵鐟欏嫭鍋犻柛搴ㄤ憾閸╃偤骞嬮敂缁樻櫔闂佺硶鍓濋悷褔寮抽妶澶嬧拺闁告繂瀚﹢浼存煟閳哄﹤鐏︽鐐插暣閸┾剝鎷呴悜妯活啎闂備焦鎮堕崕婊堝焵椤掑嫬绠柨娑樺绾句粙鏌涚仦鍓ф噮閻犳劒鍗抽弻娑㈡偐瀹曞洤鈷岄梺璇″暙閸℃瑧鏉稿┑鐐村灦椤洭宕濋敃鈧—鍐Χ閸℃鐟ㄩ梺鎸庢穿婵″洨鍒掗弮鍫熷仺闁告稑锕﹂崢閬嶆煟鎼搭垳宀涢柡鍛箞瀹曟繂顓奸崶鈺冿紲闂佺鏈銊ョ摥婵＄偑鍊ら崢褰掑礉閹存繄鏆﹀┑鍌滎焾椤懘鏌ｅΟ鍨毢閻庨潧銈稿濠氬磼濞嗘垵濡介梺璇″枛閻栫厧鐣烽弴銏╂晬闁绘劘灏欓ˇ顕€鎮楅獮鍨姎婵炶缍侀幃鐐寸節閸愶缚绨婚梺瑙勫礃濞夋盯寮搁崒姣懓顭ㄩ崟顓犵厜闂佺粯鎼╅崑濠傜暦閼告妲归幖绮规閸ゃ倝姊婚崒娆戣窗闁告瑥閰ｅ畷褰掑醇閺囩偠鎽曢梺鐐藉劚绾绢參寮抽崱娑欏€甸柨婵嗛婢т即鏌ｉ敃鈧悧鎾诲箖濡ゅ啯鍠嗛柛鏇ㄥ墰椤︺儵鎮楃憴鍕闁告挻绻堥幃姗€骞掑Δ浣叉嫼闂佺粯鎸哥€垫帒顭囬悢鍏肩厱濠电偛鐏濋埀顒佹礀瀹撳嫰鏌ｉ悢鍝ユ噧閻庢凹鍠氬褔鍩€椤掆偓閳规垿鎮欓懠顒€顣洪梺璇茬箲缁诲牆顕ｇ粙搴撴闁靛骏绱曢崣鍡涙⒑閸濆嫭澶勯柨姘舵煃瑜滈崜姘辨崲閸儲鍋樻い鏇楀亾鐎殿喕绮欓、妯款槼闁哄懏绻堝娲濞戞艾顣洪梺鐟板暱闁帮綁骞冮幐搴涘亝闁告劏鏂侀幏缁樼箾鏉堝墽绉俊顐㈠瀹曘儵鎮烽幍铏杸濡炪倖妫佹慨銈囩礊閹达附鍋傞柕鍫濐槹閻撳繘鏌涢锝囩畺濠殿垰銈搁弻娑㈠Χ閸℃顦伴梺鍝勬湰閻╊垶銆侀弴銏℃櫜闁糕剝鐟Σ浼存⒒娴ｄ警鐒鹃柨鏇樺€濋幃銉︾附缁嬭儻鎽曞┑鐐村灟閸ㄥ綊鎮炲ú顏呯厱闁规澘澧庣槐鎵磼椤旇偐鍩ｆ慨濠呮閹即鍨鹃崗鍛棜婵犵數鍋涢顓熸叏閹绢噮鏁勯柛鈩冪⊕閸嬪倿鏌ｉ弬鍨倯闁绘挻鐟╁娲敇閵娧呮殸婵犫拃鍌氬祮闁哄瞼鍠栭幃鍓т沪閸欘偁鍎崇槐鎺撴綇閵婏箑纰嶅銈嗘尭閵堢鐣烽崡鐐嶆棃宕樿椤㈡绱撻崒姘偓鐑芥嚄閸撲礁鍨濇い鏍ㄧ矌閻瑩鏌熼幆褜鍤熸い鈺冨厴閺屻劑寮撮悙娴嬪亾閸濄儱顥氶柛蹇撳悑閸欏繑鎱ㄥΔ鈧Λ妤佹櫠婵犳碍鐓熼幖杈剧到閸樺瓨鎱ㄦ繝鍕笡闁瑰嘲鎳樺畷銊︾節閸屾稒鐣奸梻浣圭湽閸╁嫰宕归柆宥冣偓鍐醇閵夈儲鐎銈嗘磵閸嬫捇鏌℃担瑙勫磳闁诡喒鏅犲畷锝嗗緞鐎ｆ挻宀稿缁樻媴閼恒儳銆婇梺鍝ュУ閹稿骞堥妸鈺佺骇闁规惌鍘奸弲鐘测攽閻樼粯娑ф繛灞傚灪缁傚秴顭ㄩ崼鐔哄幐闂佸憡鍔戦崝搴㈡櫠濞戙垺鐓ユ繛鎴炶壘閺嬫梻绱掓潏銊ユ诞濠碘剝鎮傛俊鐑筋敊閹勫€┑鐘愁問閸犳牠鏁冮敂鎯у灊妞ゆ牜鍋涚粻顖炴煕濞戝崬鏋ら柣鐔活潐閵囧嫰寮介妸褏鐓€婵犳鍠涢崑鎰閹捐纾兼繛鍡樺笒閸橈紕绱撴笟鍥ф珮闁搞劍濞婂顐︻敋閳ь剟宕归幆褏鏆﹂柛銉ｅ妽椤旀洟姊绘笟鈧褎顨ヨ箛鏇犵闁糕剝銇傞敐澶嬪殐闁冲搫鍟伴敍婵囩箾鏉堝墽鎮兼い顓炵墦閸┾偓妞ゆ巻鍋撴繝鈧柆宥呮瀬妞ゆ柨妲堥弮鍫濈妞ゅ繐妫楅ˇ鈺佲攽閻愬樊鍤熷┑顔芥尦椤㈡牠宕ㄩ褍鏅犲┑鐘绘涧濡矂寮ㄦ禒瀣厽婵☆垵顕х徊濠氭煃瑜滈崜娑㈠极鐠囪尙鏆﹂柟杈剧畱缁犺崵绱撴担濮戭亝绂掑ú顏呪拺闁告稑锕﹂埥澶愭煥閺囶亞鐣电€规洏鍨介弻鍡楊吋閸♀晜顥婃俊鐐€栭崝鎴﹀垂閻戞ê绶為柛鏇ㄥ灡閻撴瑩鎮樿箛鏃傚婵炲懎鎳樺畷鈩冩綇閳哄啰锛滈柣搴秵閸嬫挾妲愰埡鍛厽闁绘梻鍘ф禍浼存煟閹惧崬鍔﹂柡灞剧洴椤㈡洟鎮╅懠顑跨磿闂備礁鎼Λ顓㈠磻婵犲偆娼栨繛宸簻娴肩娀鏌涢弴銊ュ箻闁告柨婀辩槐鎾存媴閸︻厼寮ㄧ紓浣哄У閻楃娀鎮伴鈧畷鍗炩槈濡偐娼夐梻浣稿閸嬫帡宕戦崨鏉戠柧妞ゆ巻鍋撻柍瑙勫灴閹晝鎷犺娴兼劙姊洪悷鏉跨骇闁烩晩鍨跺顐﹀箛椤撶偟绐為柣搴€ラ崟顐紪闂傚倸鍊风粈渚€骞夐敍鍕煓闁硅揪闄勯弲婵嬫煏婢诡垰鍊婚崜銊︾箾鐎电甯堕柣掳鍔戦幃锟犳偄閸忚偐鍘撻梺鍛婄箓鐎氱顔忛妷鈺傜厽闊洤顑呴崝婊兦庨崶褝韬い銏℃礋婵″爼宕ㄩ閿亾鐠囧樊娓婚柕鍫濈凹缁ㄥ鏌涢悢椋庢憼濞ｅ洤锕畷濂稿即閻愯尪鈧灝鈹戦埥鍡楃仸闁衡偓鏉堚斁鍋撳顐ょ煓婵﹦绮幏鍛村川婵犲啫鍓甸梻浣烘嚀閸㈡煡顢栨径濠勬殾闁硅揪绠戦獮銏＄箾閸℃绠伴柣蹇擄功缁辨捇宕掑▎鎴濆闁煎灕鍥ㄧ厱閻庯綆浜濋崵鍥煛鐏炲墽娲存鐐叉喘閸┾剝鎷呴崜鑼偓宄扳攽鎺抽崐妤佹叏閺夋嚚娲敇閻戝棙缍庡┑鐐叉▕娴滄粎绮堥崼銉︾厵缂備焦锚缁楀倻绱掗妸銊ヤ汗缂佽鲸鎸婚幏鍛驳鐎ｎ亝顔勯梻浣侯焾閿曘倕顭囬垾宕囨殾闁告繂瀚уΣ鍫ユ煏韫囨洖啸闁活偄瀚板娲礈閹绘帊绨介梺鍝ュУ閹瑰洤鐣烽姀銈嗙劶鐎广儱妫岄幏娲⒑闂堚晛鐦滈柛妯恒偢瀹曟繄鈧綆鍠楅悡娑㈡倶閻愰鍤欏┑顔煎€块弻鏇㈠幢濡も偓閳ь剙娼￠獮鍐晸閻橀潧绁﹂梺闈涱槶閸庣敻宕ｉ崟顓涘亾鐟欏嫭绀冮柛搴°偢绡撻柛宀€鍋為ˉ濠冦亜閹烘埈妲稿褜鍨堕弻鏇㈠炊瑜嶉顓炩攽椤旂懓浜鹃梻浣规灱閺呮盯宕导姝ゅ洦瀵肩€涙ǚ鎷洪柡澶屽仦婢瑰棝宕濆澶嬬厱闁哄啠鍋撻柣鐔村劦閹箖鎮滈挊澶愬敹闂佸搫娲ㄩ崐锝夊煛閸涱喚鍘繝銏ｅ煐缁嬫垿銆呴鍌涘枑闁绘鐗婄亸锔芥叏婵犲偆鐓肩€规洘甯掗～婵嬵敄閽樺澹曢悗鐟板閸ｇ銇愰幒鎴犲€炲銈嗗笒椤︿即寮查鍫熲拺闁告繂瀚埢澶愭煕濡亽鍋㈢€规洖缍婂畷鎺戔槈閺嶏妇鐩庨梻浣告惈缁夋煡宕濇惔銊﹀剹閻庯綆鍋佹禍婊堟煙闁箑鐏犵悮姘舵⒑闁稓鈹掗柛鏂跨焷閻忔帡姊洪崷顓х劸婵炲鍏樻俊鎾箛閻楀牃鎷洪梺鍛婄箓鐎氼剟顢旈妷鈺傜厱閹艰揪绲鹃弳顒傗偓娈垮枦椤曆囧煡婢舵劕顫呴柣妯诲絻缁侇噣姊绘笟鈧褔鈥﹂崼銉ョ？闁惧浚鍋嗛々鐑芥煃閸濆嫬鏆熺痪鎹愭闇夐柨婵嗘缁茶霉濠婂牏鐣烘慨濠冩そ瀹曘劍绻濋崒姘兼綂闂備礁鎼崐鎼佸磹閸︻厾鐭夌€广儱鎷嬮悡銉╂煕椤愮姴鐏╃憸鏉垮濮婃椽骞栭悙鎻掑Η闂佸憡娲﹂崜娆撴⒒椤栫偞鈷掑ù锝呮啞閸熺偤鏌＄仦璇插缂侇喗妫侀妵鎰板箳閹达絾鎲伴梻浣瑰缁诲倿鎮ц箛娑欏仾闁逞屽墴濮婅櫣鎲撮崟顐ゎ槰濠电偛鎳忓ú鏍煝閹捐埖瀚氭繛鏉戭儐閺傗偓婵＄偑鍊栧濠氬Υ鐎ｎ喖绀夐柣鏃囨绾惧吋銇勯弴鐐村櫣闁诲骏绲跨槐鎺楊敋閸涱厼绫嶉梺璇″枔閸ㄤ粙骞冮埄鍐╁劅闁挎繂鎳庤婵犵绱曢崑鎴﹀磹閺嶎偅鏆滈柟鐑樻煛閸嬫挸顫濋悡搴♀拫闂佽鍠氶崑銈呯暦瑜版帩鏁冮柣妯夸含閻╁酣姊绘担鍛婅础闁稿簺鍊濆畷褰掓偨缁嬭法鍔﹀銈嗗坊閸嬫捇鏌熺拠褏纾跨紒顔碱儔楠炴帡骞嬮鐘插汲闂備礁澹婇崑鍡涘窗閹捐鍌ㄩ柟顖嗏偓閺€浠嬫煟閹邦垱纭鹃柦鍕悑閵囧嫰寮撮崱妤佸闁稿﹤鐖奸弻銊╂偄閸濆嫅锝夋煟閹惧娲撮柡灞剧☉閳藉宕￠悙鑼啋闂備胶纭堕弲顏嗗緤妤ｅ啫桅闁告洦鍨伴～鍛存煥濞戞ê顏柛锝庡弮濮婃椽鏌呭☉姘ｆ晙闂佸憡姊归崹鍧楁偘椤曗偓瀹曞爼顢楁径瀣珕闂備胶纭堕崜婵嬫偡閿曞倸鐤鹃柕濠忓缁♀偓缂佺偓婢橀ˇ杈╁閸ф鐓曢悗锝庡亜閻忓鈧娲橀崝娆忣嚕娴犲鏁囬柣鎰問濡查攱绻濆閿嬫緲閳ь剚鎹囬幃鐐烘晝閸屾氨鐓戦棅顐㈡处缁嬫帡鎮″▎鎴犵＝濞达綁娼ч悘鈺呮煛鐎ｎ剙鏋涢柡灞剧⊕缁绘繈宕掑鍐幗闂備礁鎼惉濂稿窗閹捐埖顫曢柟鐑樺殾閻旂厧浼犻柛鏇ㄥ墰缁夊綊姊婚崒娆愮グ闁靛棌鍋撻梺绋款儐閹告悂婀侀梺缁樏Ο濠囧磿閹扮増鐓熼柟鎯у船閸旀粎绱掔紒妯兼创妤犵偛顑夐幃妯好虹拋鎶藉仐濡炪們鍨哄Λ鍐春閿熺姴宸濇い鏃€鍎抽獮鍫熺節绾版ɑ顫婇柛銊ョ－閸掓帡顢涘鍛槸闂佺鎻梽鍕偂閸愵喗鍋℃繛鍡楃箰椤忊晠鏌ｈ箛鏃€灏﹂柡灞剧洴閸┾剝鎷呴崜韫磾闁诲氦顫夊ú姗€鏁冮姀銈冣偓渚€寮崼婵嗙獩濡炪倖鏌ㄩ崥瀣枍閵忥紕绡€缁炬澘顦辩壕鍧楁煕鐎ｎ偄鐏寸€规洘鍔橀ˇ瀵哥磼椤旂⒈鐓兼鐐差儔閺佸倿鎸婃径澶嬵潟闂傚倷绶氬褑澧濋梺鍝勬噺缁嬫帡銆佹繝鍥ㄢ拻濞达絽鎲￠崯鐐寸箾鐠囇呯暤鐎规洖缍婂鍓佹嫚閻愵剛鈽夋い顐ｇ矒閸┾偓妞ゆ帒瀚拑鐔哥箾閹寸偟鐭ゆ俊鑼帶椤啴濡堕崘銊ヮ瀳闂佺懓鍟块柊锝夈€佸鑸垫櫜濠㈣泛锕︽鍥煙閻撳海鎽犻柟绋款煼瀵剟鍩€椤掍椒绻嗛柣鎰典簻閳ь剚鐗曢～蹇旂節濮橆儵銉╂倵閿濆骸鏋涚紓浣叉櫇缁辨挻鎷呮慨鎴ｅ亹閹广垽宕卞☉娆戝幗闂佸綊鍋婇崹浼存偂閹邦厹浜滈柕澶堝労濡偓闂佸搫鐭夌紞渚€寮幇鏉跨倞鐟滃秹鐛€ｎ亶娓婚柕鍫濆暙閻忣亝绻涢懠顒€鏋涚€殿噮鍋婂畷姗€顢欓懖鈺佸Е婵＄偑鍊栫敮鎺楀磹婵犳碍鍎楅柛鈩冪⊕閸婄敻鏌ㄥ┑鍡涱€楀ù婊勭墪闇夋繝濠傚閻帡鏌″畝鈧崰鎰偓浣冨亹閳ь剚绋掕摫闂佹鍘界换娑氣偓娑欘焽閻銇勯妸銉уⅱ婵″弶鍔欓獮鎺楀箻鐎靛摜肖闂備線娼ц噹闁告侗鍨卞鏍р攽閻樻剚鍟忛柛鐘崇墵閺佸啴鏁傞幆褍鐏婂銈嗙墱閸嬫稓绮婚鐐寸厱婵炴垵宕悘锟犳煕閻樺弶顥㈤柡灞剧洴瀵挳濡搁妷銈囨殫闂備礁鎲＄换鍐€冩繝鍌ゆ綎缂備焦蓱婵挳鏌涘☉姗堝伐闁哄棗鐗撳娲传閸曨噮娼堕梺鍛婃⒐閸ㄥ灝顕ｇ紒妯肩瘈闁搞儯鍔嶅▍婊堟⒑閸涘﹦鐭嗙紒鈧担绯曟灁闁靛鍎哄〒濠氭煏閸繃顥滃┑顔ㄥ懐纾奸柤鑹板煐绾墎鈧鍟崶褏鍔﹀銈嗗坊閸嬫捇鏌嶇憴鍕伌妞ゃ垺鐟╁顒勫Χ閸曨叀绻戦梻鍌欒兌椤牆霉閻戣棄鏋佺紓浣姑肩换鍡涙煟閹达絾顥夐柣鎾寸洴閺屾稓浠﹂崜褏鐓€濡ょ姷鍋涢悧濠勬崲濠靛鍋ㄩ梻鍫熺◥濞岊亪姊洪幖鐐插闁绘牕銈搁崹楣冩晝閸屾氨鍊炲銈嗗坊閸嬫挾绱掗悩铏仢闁哄矉绲借灒闁兼祴鏅涚粭锟犳⒑缂佹ɑ灏伴柣鈺婂灦瀵鈽夊Ο閿嬵潔闂佸憡顨堥崑鐐烘倶閹惧墎纾藉ù锝呮惈鍟搁梺绋款儍閸婃繂顕ｆ繝姘櫖闁告洦浜濋崟鍐⒑閸涘﹥瀵欏ù锝嗗絻娴滈箖鏌熼悜妯烘鐟滅増甯楅崑鎴︽煕濞戝崬鐏ｉ柡鍡愬€濆铏规嫚閳ヨ櫕鐏嶉梺鑽ゅ暱閺呯娀濡存担鑲濇棃宕ㄩ鐙呯床婵犵數鍋為崹闈涚暦椤掑嫬绠栭悗锝庡枟閳锋帡鏌涚仦鎹愬闁逞屽墰閸忔﹢骞婂Δ鍛唶闁哄洦銇涢崑鎾绘晝閸屾岸鍞堕梺闈涱檧闂勫嫬鈻嶉崶顒佲拺闁圭瀛╃粈鈧梺绋匡工閹芥粍绔熼弴鐔虹瘈婵﹩鍘鹃崢顏堟⒑閸撴彃浜濈紒璇插暞閸掑﹪宕楅懖鈺冾啎闂佺绻楅崑鎰櫠閻㈠憡鐓涢悘鐐靛枎濡盯鎮块埀顒勬⒑閻熸澘鈷旀い銉﹀姉濞戠敻鍩€椤掑倻纾藉ù锝呮惈娴滈箖鏌涙惔銏犫枙鐎规洏鍎抽埀顒婄秵閸嬪棝鍩炲鍛斀闁绘ê寮剁粊鈺呮煛娴ｅ摜校闁逛究鍔岄～婊堝幢濡も偓缁犳椽姊虹粙鍨劉闁瑰憡鎮傞垾鏃堝礃椤斿槈褔骞栫划鍏夊亾閼碱剛娉跨紓鍌氬€风粈渚€藝椤栨粎绀婂┑鐘叉川瀹撲線鏌涢幇鈺佸闁哄棗顑夊娲敇閵娿儺娲梺鍛婄懃濡繂顫忓ú顏勫窛濠电姴鍟ˇ鈺呮⒑閸涘﹥灏伴柣鈺婂灠閻ｅ嘲鈻庨幘瀛樻闂佺粯蓱閺嬪ジ骞忓ú顏呪拺闁告稑锕︾紓姘舵煕鎼淬劋鎲剧€殿喗鎮傞獮瀣晜閻ｅ苯骞嶉梻浣告啞缁嬫垿鏁冮妶澶婄厺闁哄洢鍨洪悡鐔哥箾閹存繂鑸规繛鍛Ф閳ь剝顫夊ú姗€鏁冮姀銈冣偓浣糕枎閹炬潙娈熼梺闈涱檧鐎靛本绂掕濮婂宕掑▎鎺戝帯缂備緡鍣崹鍫曞灳閿曞倸閱囨い顐幘閸撱劌鈹戦悙鍙夘棡闁圭顭峰鏌ヮ敆娴ｈ櫣鐦堟繝鐢靛Т閸婄粯鏅跺☉銏＄厓闂佸灝顑呴悘鈺冪磼鏉堛劍灏伴柟宄版噺閹便劑骞嬮婵堝嚬闂侀€涚┒閸旀垵鐣烽崼鏇炍╅柨婵嗗閻╁酣姊绘担鍛婃儓婵炲眰鍨藉畷婵堜沪缁涘娈ㄥ銈嗘閺侇噣宕戦幘鑸靛枂闁告洦鍓涢敍姗€姊洪幖鐐插婵☆偄瀚伴幃楣冩倻閼恒儲娅㈤梺缁樏崯鍧楀焵椤掑倸鍘撮柡灞界Ч瀹曨偊宕熼鐔蜂壕鐟滅増甯掔痪褔鏌熼梻瀵稿妽闁抽攱甯掗湁闁挎繂鐗婇鐘绘偨椤栨稓娲撮柡灞剧洴瀵噣鍩€椤掆偓鐓ら柡宥庡弾閺佸鏌ㄥ┑鍡╂Ц闂佸崬娲弻锟犲炊閿濆懍澹曞┑鐘灱閸╂牠宕濋弽顓炵９闁绘垼濮ら悡鐔兼煙鐎电鍓遍柣鎺嶇矙閺屾稑鈻庤箛鏃戞闂佸疇顫夐崹鍧椼€佸▎鎴犻┏閻庯綆鍓欐慨濂告⒒娴ｈ櫣銆婇柡鍛矒閹囨偐鐠囪尙鐣洪梺璺ㄥ枔婵敻宕戦崟顖涚厾婵炴潙顑嗗▍鍛喐閺夊灝顏慨濠冩そ楠炴牠鎮欓幓鎺戭潙闂備胶顭堥柊锝嗙鐠鸿櫣鏆︽繝闈涱儏鍥存繝銏ｆ硾椤戝洭宕㈡禒瀣拺闁圭娴风粻鎾寸箾鐠囇呯暤鐎殿喗濞婇、妤呭礋椤掑倸骞愰梺璇茬箳閸嬬喓娑甸崼鏇炵；闁规儳纾弳锕傛煕閵夛絽濡介柣锝囧厴濮婅櫣鎷犻幓鎺戞瘣缂傚倸绉村Λ婵嗙暦濠婂啠鏋庨柟鎹愭珪濡差剟鎮楅崗澶婁壕闂佸憡娲﹂崗姗€骞忓ú顏呯厽閹肩补鍓濈拹鈥斥攽椤旂偓鏆挊鐔奉熆鐠轰警鍎嶅ù婊勭矒閺屻劑寮崶璺烘闂佽楠忕粻鎾诲蓟濞戙垹鐓橀柛顭戝枤娴犻箖姊虹拠鈥崇仭婵☆偄鍟穱濠囧箹娴ｈ倽銊ф喐濠婂牆瑙﹂柛娑樼摠閳锋帒霉閿濆牊顏犻悽顖涚洴閺屾盯寮埀顒€煤閺嶎収鏁嬮柨婵嗩槸闁卞洭鏌￠崶鈺佹瀻濞寸姍鍐炬富闁靛牆妫欑壕鐢告煕鐎ｎ偅灏伴柟渚垮妽缁绘繈宕掗妶鍥ф倯闁诲氦顫夊ú妯兼暜閹烘鐓濋幖娣妼缁狅絾銇勯幘璺烘櫩婵犲﹤鎳愮壕浠嬫煕鐏炴崘澹橀柍褜鍓欓幗婊呭垝閺冨牆绠绘い鏃囧Г濞呭洤顪冮妶鍛婵炶绠撻弫宥夊磼閻愮补鎷绘繛杈剧悼閻℃柨顭囬幇鐗堢厱閹兼番鍨归埢鏇㈡煙椤旇姤銇濆┑鈩冩倐閸┾剝鎷呴搹鐟板箑闂傚倸顭崑鍕洪敂鍓х煓闁圭儤顨嗛崑鍌炴煟閺傚灝鎮戦柣鎾崇箻閻擃偊宕惰閸庡繘鏌ｉ幒鎾淬仢闁哄矉缍侀獮鎺楀箣濠靛啯瀵栫紓鍌欐祰妞村摜鏁敓鐘茬畺妞ゅ繐鐗嗛悞鍨亜閹烘垵顏╅柛銊ュ€块弻娑㈩敃閿濆棛顦ラ梺钘夊暟閸犳劗鎹㈠☉銏犵闁绘劕鍟懝鎯у祫闂佸壊鍋嗛崰鎾剁不妤ｅ啯鐓曢柍鈺佸幘椤忓懏鍙忓璺虹灱绾惧ジ鎮楅敐搴濈凹鐎瑰憡绻勭槐鎺撴綇閵婏箑闉嶉梺鐟板槻閹虫﹢鐛幘璇茬鐎广儱鎷嬪Λ婊堟⒒閸屾艾鈧绮堟担鍦彾濠电姴娲ょ壕璇层€掑锝呬壕閻庤娲樺ú鐔奉嚕婵犳艾唯闁挎洍鍋撳ù婊勵殜濮婃椽宕崟顒€绐涢梺鍝ュТ濡瑧绮嬪鍜佺叆闁告洍鏅欑花濠氭⒑鐟欏嫬绀冩繛澶嬬洴瀵憡鎯旈妸锔惧幗闂婎偄娲ら鍛村礉濠婂懐纾肩紓浣诡焽濞插鈧娲忛崝鎴︺€佸▎鎾村亹闁告劘灏欐禒鍝ョ磽娴ｅ摜鐒峰鏉戞憸閹广垹鈹戠€ｎ亞鍊為悷婊冪箻椤㈡瑥鐣濋崟顑芥嫼闂侀潻瀵岄崢濂稿礉鐎ｎ喗鐓欓梺顐ｇ閸忓本绻涢幋鐘虫毈闁糕斁鍋撳銈嗗笒閸婅崵澹曟禒瀣厱閻忕偛澧介幊鍕磼娴ｈ绶叉い顏勫暣瀵爼骞嬮悙鏉戞瀾闂備浇妗ㄧ欢锟犲闯閿濆绠栨繛鍡樻尭娴肩娀鏌涢弴銊ュ箹濠殿噯闄勬穱濠囨倷椤忓嫧鍋撻弽顐ｆ殰闁圭儤顨嗛弲婵嬫煥閺傚灝鈷旈柣顓熸崌濮婂宕奸悢鐑╁亾娴犲鍋￠梺顓ㄥ閸欏棝姊虹化鏇炲⒉妞ゎ厼娲俊鎾箛閻楀牏鍘卞┑掳鍊曠€氼亪宕ラ锔界厵闁告瑥顦伴崐鎰版煙椤斻劌娲ら柋鍥ㄧ節闂堟稓澧㈤柟铏墵濮婄粯鎷呴搹鐟扮闂佸湱顭堥…鐑藉箖閻ゎ垼妯勯梺绯曟杹閸嬫挸顪冮妶鍡楃瑨闁稿﹤缍婂畷鐢稿焵椤掑嫭鐓熼幖娣灩閸ゎ剟鏌涢悩鎰佹疁鐎殿喛灏欓幑鍕媴閺囩喐顥堢€规洏鍔戦、姗€濮€閳藉懐鑸瑰┑鐘垫暩閸嬫盯顢氶鐔稿弿闁圭虎鍣弫鍕煕閳╁啰鈯曢柛瀣€块弻锟犲炊閵夈儳浠鹃梺缁樻尵閸犳劖绌辨繝鍥舵晬婵炴垵宕崝宀勬⒑閹肩偛鈧洟顢栭崶顒€鐒垫い鎺戝枤濞兼劙鏌熼鑲╁煟鐎规洘娲熼幃鐣岀矙鐠侯煈鍟堥梻浣稿閸嬪懎煤濮椻偓瀵煡骞撻幒婵堝數闁荤姾娅ｇ亸銊╁礉閻旇偤鏃堟偐閸欏鏋犲┑顔硷龚濞咃絿妲愰幒鎳崇喖宕崟鍨秼闂傚倷绀侀浠嬪级閸噮鐎锋繝鐢靛仜濡酣宕归挊澶屾殾闁挎繂妫楃欢鐐烘煕椤愶絿鐭岄柣?")
        if mode == "direct":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃闁硅櫕鎹囬垾鏃堝礃椤忎礁浜鹃柨婵嗙凹缁ㄥジ鏌熼惂鍝ョМ闁哄矉缍侀、姗€鎮欓幖顓燁棧闂備線娼уΛ娆戞暜閹烘缍栨繝闈涱儐閺呮煡鏌涘☉鍗炲妞ゃ儲鑹鹃埞鎴炲箠闁稿﹥顨嗛幈銊╂倻閽樺锛涘┑鐐村灍閹崇偤宕堕浣镐缓缂備礁顑嗙€笛囨倵椤掑嫭鈷戦柣鐔告緲閳锋梻绱掗鍛仸鐎规洘鍨块獮鍥敇濠娾偓缁ㄥ姊洪崫鍕殭闁稿﹤缍婂畷鐢稿焵椤掍胶绠鹃悗娑欘焽閻帞绱掗悩宕囧⒌鐎殿喛顕ч埥澶愬閻樼數鏉搁梻鍌氬€搁悧濠勭矙閹烘鍊堕柛顐犲劜閸婄敻鏌ｉ悢鍝勵暭闁哥喓鍋熺槐鎺旀嫚閼碱剙鈪甸悗娈垮枛椤兘宕洪崟顖氱闁靛ě鍛祦闂備浇顕ч崙鐣岀礊閸℃顩查柣鎰嚟椤╃兘鏌熺紒銏犳灍闁抽攱鍨圭槐鎺斺偓锝庡亽閸庛儵鏌涙惔锛勭缂佽鲸甯楀鍕沪閹勭暚婵＄偑鍊ら崑鍕崲閹邦喖寮叉俊鐐€曠换鎰偓姘间簽濡叉劙宕奸弴鐔叉嫼闂佸憡绋戦敃銉﹀緞閸曨垱鐓曟俊顖濆吹閻帡鏌熼瑙勬珖缂佽鲸甯掕灒闁绘挸楠哥粻鐐烘⒒閸屾瑧顦﹂柟纰卞亰瀹曟劙宕烽娑樹壕缂佹绋戝ú銈囩不閺屻儲鐓ユ繝闈涙瀹告繄鐥幆褍鎮戦柕鍥у瀵剟宕归瑙勫瘱闂佹眹鍩勯崹閬嶆儎椤栫偛钃熼柡鍥ュ灩闁卞洦銇勯幒鎴濃偓鏄忊叺闂佽姘﹂～澶娒哄鈧弫鍐閵堝懏妲梺璺ㄥ枔婵绮堥崘顔界厪濠电偛鐏濋崝銈夋煟閵堝懎顏慨濠傤煼瀹曟帒顫濋钘変壕濡炲瀛╅鑺ユ叏濮楀棗澧婚柣鎺旀櫕閹叉悂寮崶顭戞（婵犵數鍋涢顓熸叏閹绢噮鏁勯柛娑卞灣閻滅粯淇婇妶鍛櫤闁绘挻绋撻埀顒€绠嶉崕閬嶅疮椤愶絼绻嗛柤鎭掑劤缁犻箖鏌涘☉鍗炵仩閺嶏繝姊洪棃娑欐悙閻庢碍婢橀锝夘敆閸曨偄鐎銈嗘椤鈧灚鐗滅槐鎾存媴閸濆嫪澹曢梺绋垮婵炲﹥淇婇崼鏇炵濞达絾鐡曢幗鏇㈡⒑閹稿海绠撻柟鍐差樀瀵憡鎯旈妸褍褰勯梺鎼炲劘閸斿秹鎮￠妷锔剧闁告稑娲ら幊鎰閽樺褰掓晲閸涱収妫屽┑鈽嗗灠閻楁捇寮诲☉銏℃櫜闊洦娲滆ⅵ闁诲孩顔栭崰鏍€﹂悜钘夊瀭闁诡垎鍛闂佹悶鍎崝宥夋偩閻戣姤鈷掑〒姘ｅ亾闁逞屽墰閸嬫盯鎳熼娑欐珷閻庣數纭堕崑鎾舵喆閸曨剛锛涢梺鍛婎殕婵炲﹪鎮伴鍢夌喖宕楅悡搴ｅ酱闂備浇鍋愰埛鍫ュ礈濞嗘劖鍙忛柨鏃€鍨濈换鍡涙煟閹板吀绨婚柍褜鍓氶悧婊堝极椤曗偓楠炴帒螖閳ь剛澹曢崷顓熷枑闁绘鐗嗙粭鎺撴叏鐟欏嫮鍙€闁哄苯绉瑰畷顐﹀礋椤愮喎浜鹃柤鍝ユ暩椤╁弶绻濇繝鍌氼仴濞存粍绮撻弻鐔煎箲閹邦厾銆愭繛瀵稿閸愬墽鍞甸悷婊冮鐓ら柣鏃傚帶閽冪喖鏌ㄩ悢鍝勑㈡鐐灲閻擃偊宕堕妸锔规嫻闂佺粯绻冮懝楣冨煘閹达富鏁婄痪顓炲槻婵稓绱撴笟鍥ф珮闁搞劌鐖奸悰顔跨疀濞戞ê绐涢柣搴㈢⊕閿氶柣褍瀚换婵嬪閿濆棛銆愬銈忕細閸楁娊骞嗛崼锝囩杸闁哄倸澧界粻姘舵⒑缂佹ê濮﹀ù婊勭矒閸┾偓妞ゆ垶鍎抽埀顒佺箓閻ｇ兘濮€閿涘嫰妾梺鍛婄☉閿曘倖绂嶆潏銊х瘈闁汇垽娼у瓭濠电偛鐪伴崐婵嬪箖閹稿簺鍋呴柛鎰ㄦ櫇閸樺墽绱撴担鍓插創婵炲娲樼粋鎺戔槈閵忥紕鍘遍柟鑹版彧缁蹭粙寮稿☉銏＄厸閻忕偟鍋撶粈鍐磼缂佹娲寸€规洖缍婇、娆撴偂楠烆喗鍨垮缁樻媴閸涘﹤鏆堝┑鈽嗗亝閸ㄥ湱鍒掓繝姘闁挎柨鍘滈崑鎾诲籍閸繄顦ㄥ銈嗘煥濡插牐顦归柡灞剧洴閸╁嫰宕橀悙顒傛毉闂備浇宕甸崰鍡涘礉閹存繍娼栭柧蹇撴贡閻瑩鏌涢弽銈傚亾閸忓懐鐭楃紓鍌氬€搁崐鍝ョ矓閹绢喗鏅濋柕鍫濐樈閺佸鏌ㄥ┑鍡╂Ц缂佺媭鍣ｉ弻锕€螣娓氼垱楔闂佸憡锚閹诧紕鎹㈠☉銏犵缁炬儳顑呴ˉ婵嗏攽閻愯尙婀撮柛鏃€鍨甸悾鐑筋敆閸曨剙浠洪梺鍛婄☉閿曘倖绂掗鐐╂斀闁绘顕滃銉╂煕閻斿憡灏︾€规洩缍佸畷鐔碱敍濞戞艾甯鹃梻浣虹《閸撴繈銆冮崨鏉戞辈闁绘劗鏁哥壕鑲╃磽娴ｈ鐒界紒鐘靛仧閳ь剝顫夊ú鏍偉婵傜鐏抽柡宥庡弾閺佸嫰鏌熼鍡楀暙琚濋梻鍌欑閹碱偊寮甸鍕剮妞ゆ牜鍋熷畵渚€鏌涢妷顔煎妞ゃ儱鐗婄换娑㈠箣閻愬灚鍣繛瀛樼矤娴滄繃绌辨繝鍥ч柛銉仢閵夆晜鐓曢悗锝庡亜閻忓鈧娲栫紞濠囧箖濠婂吘鐔轰焊閺嶃劍鏆ゆ繝鐢靛Х閺佸憡鎱ㄩ弶鎳ㄦ椽鏁冮崒姘憋紮闂佺粯鍨兼慨銈夊磹閸偆绠鹃柟瀵稿仧閹虫劙鏌ｉ幒鏇炐撻柕鍥у閺佸倿宕崟顐€抽梻浣哥枃椤宕归崸妤€鏋佺€广儱顦粈瀣亜閹般劉鍋撻搹顐ｅ暉婵犵數濮烽。钘壩ｉ崨鏉戠；闁告洦鍘搁崑鎾愁潩椤愩垹绁Δ鐘靛仜閸熸挳骞冨▎鎿冩晢濠㈣泛鐟╄閺岀喖鎳濋悧鍫濇锭缂備焦褰冨锟犲箖閿熺姴绠荤紓浣诡焽閸樹粙姊虹紒妯忣亜顕ｇ捄渚晠婵犻潧顑嗛悡鏇㈡倵閿濆骸浜濋悘蹇ｅ幗閵囧嫰顢曢姀銏㈩啈闂侀潧娲﹂崝娆撶嵁閹烘绠ｉ柣娆屽亾闁哥偟鏁诲缁樻媴閸涘﹤鏆堟繛鎾寸椤ㄥ﹤鐣疯ぐ鎺戠闁兼亽鍎遍崜鐟扳攽閻愬弶顥為柟绋款煼閹繝寮撮悢缈犵盎濡炪倖鎸鹃崰搴ㄦ倶閵夛妇绠鹃柛娑卞暆閹寸偟鈹嶅┑鐘叉祩閺佸啴鏌曡箛濠冾潑婵☆偓绠戦埞鎴︻敊绾嘲浼愬銈庡幖閸㈡煡鎮鹃悜钘夌闁瑰瓨姊归悗濠氭⒑瑜版帒浜伴柛鐘虫崌瀹曟垵螣鐠佸磭绠氶梺缁樺姦娴滄粓鍩€椤掍胶澧柍缁樻閺佸啴宕掑顒傜崺婵＄偑鍊曠换鎰偓姘间簼缁旂喖寮撮悙鈺傛杸闂佺粯鍔栧娆撴倶閿曞倹鍋ㄦい鏍ㄤ緱濞堟棃鏌嶇拠鑼х€规洖鐖奸崺锟犲礃椤忓海搴婂┑锛勫亼閸婃牕顫忔繝姘柧妞ゆ劧绠戠粻鐘绘煕閵夘喚鍘涙繛鍫滅矙閺岋綁骞囬鐔虹▏缂備焦顨嗙敮锟犲箺閸洖鍐€妞ゎ兘鈧磭绉洪柡浣瑰姍瀹曞ジ顢曢敐鍥┬ラ梻鍌欒兌缁垳缂撻崸妤€绀夌€光偓閸曨偆鍘撮梺纭呮彧闂勫嫰宕戦幇鐗堢厱妞ゎ厽鍨垫禍婵囨叏閿濆懎顏紒缁樼箓閳绘捇宕归鐣屼簽闂備礁鎲￠〃鍛村疮閸ф鍋╅柣銈庡灛娴滃綊鏌熼悜妯诲碍濞存粍顨婇弻鐔兼偂鎼达絾鎲奸柦鍐憾閺岋綀绠涢幘铏闂佸疇顫夐崹鍧楀箖濞嗘挸绾ч柟瀵稿С濡楁挻绻濆▓鍨灍閼垦囨煕閺冣偓閸ㄥ潡鐛崱妤冩殕闁告洦鍋嗛鎺楁⒑閸忓吋鍊愭繛浣冲洤鍑犻柟杈鹃檮閳锋垹绱撴担鐧镐緵婵炲牊妫冮弻锝呂旈埀顒€螞濞戞艾鍨濇い鎾卞灩缁犺櫕淇婇妶鍕厡闁告瑥鍟村娲川婵犲倸袝婵炲瓨绮嶇划鎾愁嚕缁嬪簱妲堥柕蹇ョ磿閸樻悂鏌ｈ箛鏇炰户闁稿鎸剧划鍫ュ礃椤忓棛锛滅紓鍌欑劍椤洤煤鐎电硶鍋撶憴鍕缂傚秴锕妴浣糕枎閹炬潙浜楅柟鍏兼儗閸犳绱炲鍡欑瘈闁汇垽娼у暩濡炪倧绲肩划娆忕暦濠婂啠鏀藉┑鐐层仒濮规姊洪崨濠傚Е闁哥姵顨婂畷鎴犫偓锝庝簴閺€浠嬫煟濡绲婚柡鍡欏枛閺屽秹鎮烽幍顔с垽鏌嶇憴鍕伌闁诡喒鏅犲畷锝嗗緞鐏炶浜归梻鍌欐祰濡椼劎绮堟担铏圭煋闁汇垹鐏氬畷鍙夌箾閹存瑥鐏╂鐐灪娣囧﹪顢涘┑鍥モ偓鍐煕閹烘埊韬慨濠冩そ瀹曘劍绻濋崘顏勫汲闂備胶鎳撻崯鍧楁煀閿濆鏄ラ柣鎰惈缁狅綁鏌ㄩ弮鍥棄闁逞屽墰閸忔﹢寮婚妶鍥ф瀳闁告鍋涢～鈺呮⒑閸愭彃妲婚柣妤佹尭椤繐煤椤忓嫬绐涙繝鐢靛仦鐢晜绂嶅┑瀣柧闁割偅娲樼€电姴顭块崗澶嬫珨缂傚秳绶氶悰顕€宕堕鈧痪褔鎮规笟顖滃帥闁哥喎顑夊娲嚒閵堝憛銏＄箾濞村娅囧ù婊咁焾閳诲酣骞樼€涙ɑ鐝繝鐢靛Т閿曘倝宕悩璇茬哗闁兼亽鍎禍婊堟煛閸愩劌鈧鐣甸崱娑欑厵閺夊牓绠栧顕€鏌涙惔鈽呰含闁哄矉缍侀獮瀣晲閸涘懏鎹囬弻锟犲川椤旇偐绁峰銈庡弨濞夋洟骞戦崟顒傜懝妞ゆ牗鑹炬竟鍫ユ⒒娴ｈ櫣甯涚紒璇插暙铻為柛鎰靛枛閽冪喖鏌嶉埡浣告殭缂佸墎鍋涢埞鎴︽偐閹绘帩浠煎銈忕悼閺佽顫忓ú顏勪紶闁告洦鍓欏▍銈囩磽娴ｇ瓔鍤欓悗姘煎幘缁晠鎮㈤悡搴″祮闂佺粯姊瑰钘夘瀶椤曗偓濮婃椽宕ㄦ繝鍕ㄦ闂佹寧娲忛崐婵嬪春閳ь剚銇勯幒鎴濃偓褰掑汲椤掑嫭鐓涢悘鐐额嚙婵″ジ鏌嶇憴鍕伌鐎规洖宕埢搴ょ疀閹惧妲楅梻鍌氬€峰ù鍥敋閺嶎厼绐楅柡宥庡亞閻捇鏌ｉ悢绋跨彈婵炴垯鍨瑰婵嬫煙绾板崬骞楅柡鍛灪缁绘繈濮€閿濆棛銆愰梺鎸庢磸閸婃繈宕哄☉姘ｅ亾閿濆骸鏋熼柍閿嬪灴閺屾稑鈹戦崱妤婁紑闂佽绻樻禍鍫曞蓟濞戙垺鍋愮€规洖娲ら埛宀勬⒑闂堟稒顥欑紒鈧笟鈧崺銏℃償閵娿儳顔掗梺绋跨箰閹虫劙鎮欐繝鍥ㄢ拻濞达絽鎲￠崯鐐寸箾鐠囇呯暤鐎规洏鍨介幖鍦喆閸曞灚缍楁繝鐢靛仜濡瑩骞愭繝姘亗闁绘梻鍘х粻瑙勭箾閿濆骸澧柍褜鍏欓崐鏇⑩€﹂崶顒€绠涙い鎾跺Х椤旀洟姊洪崷顓犲笡閻㈩垳鍋熺划濠氭嚒閵堝倸浜鹃悷娆忓缁€鍐磼鐠囨彃鈧潡銆佸Ο鑽ら檮缂佸娉曢崐鐐烘⒑闂堟侗鐒鹃柛搴や含閼洪亶濡烽敂鍓х槇闂佹眹鍨藉褔鍩㈤崼鐔虹濞达絽鍟块崢鎯洪鍛珕闂佽姤锚椤︻垶鎮樻笟鈧娲捶椤撯剝顎楅梺鍝ュУ椤ㄥ﹪骞冮敓鐘插嵆闁绘棁娅ｉ惁鍫ユ⒒閸屾氨澧涚紒瀣浮钘熸繝濠傚娴滄粓鐓崶椋庡埌濞存粍绻堥弻鏇㈠炊瑜嶉顓燁殽閻愬弶鍠樻い銏＄懇閹剝鎯斿┑鍫濈闂傚倸鍊风粈渚€鎮块崶顒婄稏濠㈣埖鍔曢崹鍌炴煕瑜庨〃鍛不閺嶎厽鐓冮柛婵嗗閸ｅ綊鏌涢妸銉モ偓褰掑Φ閸曨垰绠涢柛鎾茶兌钃遍梻浣风串缁犳垶顨ラ幖浣哥厴闁硅揪闄勯崑鎰版煕椤垵浜濇慨锝呭濮婅櫣绮欏▎鎯у壉闂佸憡姊归悷銉╂偩閻戣棄绠ｉ柨鏇楀亾缂佺姴顭烽弻锟犲磼濡搫濮曢梺鍝勫€甸崑鎾绘⒒閸屾瑨鍏岀紒顕呭灦瀹曟繈寮借閻斿棙淇婇鐐达紵闁绘帒锕弻娑㈠箛闂堟稒鐏嶉梺缁樻尰濞茬喖寮婚弴鐔风窞閻庯綆浜炴禒鎾⒑瑜版帗鏁遍柛銊ф嚀鍗遍柟浼村亰閺佸鏌嶈閸撴瑩锝炶箛鏇犵＜婵☆垵顕ч鎾绘⒑閼恒儍顏堟晬瀹ュ绠荤紓浣诡焽閸欏棗鈹戦绛嬬劸闁糕晜鐗犻幃锟犲Ψ閿斿墽顔曢梺鐟邦嚟閸庢垶绗熷☉娆庣箚闁告瑥顦伴崐鎰版煛鐏炵晫效闁圭锕ュ鍕熼悜鈺傜€版繝鐢靛У椤旀牠宕伴幒妤€纾婚柟鍓х帛閳锋垹绱撴担骞库偓鐐哄箣閿旂粯鏅╅梺鍝勭▉閻忔盯鏁愰崶銊ユ瀭闂佸憡娲︽禍鐐电不濮樿埖鈷戠紓浣姑慨锕€霉濠婂嫮鐭掗柛鈹惧亾濡炪倖甯婇懗鑸垫櫠閻㈢鍋撶憴鍕缂佽鐗撳顐﹀礃椤旇偐锛滃┑顔斤耿绾危閼哥數绡€闁汇垽娼ч埢鍫熺箾娴ｅ啿娴傞弫鍕煕濞戞鎽犻柛濠傛健閺屾盯鈥﹂幋婵呯按婵炲瓨绮嶇划鎾诲蓟閻旂厧浼犻柛鏇ㄥ帨閵堝棎浜滈柨鏂裤偢濡绢噣鏌曢崶褍顏€殿喗鎸抽幃銏ゆ惞閸︻厼甯ㄩ梻鍌欑閹碱偊寮甸鈧叅闁绘棃顥撻弳锕傛煙椤栫偛浜版俊鑼额嚙椤啴濡堕崨顔绢洶闂佸憡鎸荤粙鎾澄ｉ幇鏉跨婵°倓绀佹禍褰掓倵鐟欏嫭绀€婵炶绠撳畷姘槈濡粍妫冮幃鈺呮濞戞鍕冩俊鐐€ら崢鐓幟洪銏㈠祦闁硅揪绠戠粈瀣亜閹烘垵鈧骞婂┑鍡╂富闁靛牆妫涙晶顒傜磼鐎ｎ偄娴柟顖欑窔楠炴帡寮崒婊愮闯闂備胶顭堥張顒勬嚌妤ｅ啫鐒垫い鎺嶇劍閸婃劗鈧娲橀崝鏍囬悧鍫熷劅闁靛繒濯埀顒佺洴濮婃椽宕崟顕呮蕉闂佺姘︽禍顒佺珶閺囩喓绡€婵﹩鍘鹃崢鐢告⒑缂佹ê濮﹂柛鎾寸懄閺呭爼顢涢悙瀵稿幗闂佸搫鍊圭€笛囁夐姀銈嗙厸閻忕偠顕ч埀顒佺箞閻涱噣寮介妸锕€顎撻柣鐔哥懃鐎氫即寮鍕ㄦ斀闁绘ɑ鍓氶崯蹇涙煕閻樺磭澧甸柟顔ㄥ洤绠婚悹鍥蔼閹芥洟姊洪幐搴ｇ畵妞わ富鍨崇划濠氭嚒閵堝倸浜鹃悷娆忓缁€鈧┑鐐茬湴閸旀垿銆佸▎鎾崇倞妞ゆ帊璁查幏娲煟鎼粹剝璐″┑顖ｅ幖椤洭骞囬悧鍫㈠幈闂侀潧顭堥崕鏌ュ磻閵夛富娈介柣鎰絻閺嗭綁鏌涢埡瀣瘈鐎规洏鍔戦、娆撳礂绾板崬鎮嬫繝纰夌磿閸嬫垿宕愰弽顐ｆ殰闁圭儤顨呯壕濠氭煕閳╁啰鈽夐柤姝岊潐缁绘稑顔忛鑽ゅ嚬闂佹娊鏀辩敮鎺楁箒闂佹寧绻傞ˇ钘壩涢幋婵冩闁瑰墽鎳撻惃铏圭磼鏉堛劍灏い鎾冲悑閹峰懘姊归幇顒夋婵犵數濮烽。顔炬閺囥垹纾绘繛鎴欏灪閸嬨倝鏌曟繛鐐珔缂佺姵鐗犻弻娑氫沪閸撗€妫╃紓浣筋嚙濡繈寮婚敐澶婎潊闁靛繆鏅濋崝鍝ョ磽娴ｆ彃浜鹃柣搴秵閸嬩焦绂嶅鍫熺厸鐎广儱娴烽崢娑㈡煕閵堝啫鈧骞夐幖浣哥睄闁割偅绻嗛幗鏇炩攽閻愭潙鐏熼柛銊ョ秺瀹曪繝骞庨懞銉у帾婵犵數鍋涢悘婵嬪礉濮樿京纾奸柣妯烘▕閻撳吋鎱ㄦ繝鍛仩缂佽鲸甯掕灒閻忓繑鐗楅敍鍫ユ⒒娴ｈ鍋犻柛鏂跨箰铻為柛鏇ㄥ灲缂嶆牠鐓崶銊﹀婵炲樊浜堕弫鍌炴煕閺囥劋绨介柣鎰躬濮婄粯鎷呴崨濠傛殘濠电偠顕滅粻鎾崇暦濠婂喚娼╅悹楦挎椤斿棝姊绘笟鍥у缂佸鏁婚崺娑㈠箣閿旂晫鍘介梺鐟扮摠濮婄懓鈻嶉崱妯肩闁告侗鍠楀畷宀勬煛鐏炲墽娲村┑鈩冩倐婵＄柉顦查柣鎾跺枛濮婅櫣鎷犻垾铏亞闂佸憡顨嗘繛濠囧Υ娴ｇ硶鏋庨柟鎯у暱缁ㄣ儲绻濋姀锝嗙【闁兼椿鍨跺绋库槈閵忥紕鍘甸梺缁樻尭鐎涒晝鎷归敓鐘崇厵闁告瑥顦扮亸锔锯偓瑙勬礈閸犳牠銆佸Δ浣哥窞濠电姴鍟悵顒勬⒒閸屾艾鈧悂宕愰幖浣哥９闁绘垼濮ら崐鍧楁煥閺囩偛鈧摜绮婚弽顓熺厱妞ゆ劧绲剧粈鈧紒鐐劤濞硷繝寮诲☉妯滄棃宕橀妸銏犱壕闁挎繂鎳夊Σ鍫熺箾閸℃ê濮囬柛鏂挎嚇濮婃椽妫冨☉杈╁姼闂佺閰ｆ禍鍫曞箖濡ゅ拋鏁囬柣鏃囨椤旀洟鏌ｆ惔锝嗘毄妞ゎ厼鐗嗛悺顓熶繆閻愵亜鈧牠宕归悽绋跨疇婵せ鍋撴鐐茬箻楠炲鏁傞挊澶夌盎闂備礁鎲＄缓鍧楀磿閹剁瓔鏁婇柡鍥ュ灪閳锋垿鏌ｉ悢鐓庝喊闁搞倗鍠栭弻娑欐償閵忕姴顫掗梺璇″枤閸嬨倝鐛弽銊﹀闁革富鍘奸獮妤呮⒒娴ｅ憡鎯堥柛濠冩倐閹ê鈹戠€ｎ亞鐣洪梺纭呮彧闂勫嫰鎮￠弴銏＄厪闁割偅绻冮ˉ婊勭箾閹碱厼娅嶉柡宀嬬磿娴狅箓鎮欓鍌ゆЧ闁诲氦顫夊ú婊堝储瑜旈崺鐐哄箣閿曗偓楠炪垺淇婇婵嗗惞闁哄缍婂濠氬磼濞嗘帒鍘″銈庡幖閻楁捇銆侀弽顓炲耿婵炴垶顭囬澶愭⒑閹肩偛鍔撮柛鎾寸☉閻ｅ灚绗熼埀顒勫蓟閻斿吋鍊绘俊顖滃劋椤旀洟姊洪崫鍕殜闁稿鎹囬弻鐔风暋閻楀牆娈楅悗瑙勬处閸嬪﹤鐣烽悢纰辨晝闁靛牆楠搁幃鎴濃攽閻樺灚鏆╁┑顔惧厴閵嗗倿顢欓悙顒夋綗闂佸搫娲㈤崹鍦缂佹绠鹃柟瀛樼懃閻掓椽鏌℃担绋款伃闁哄本绋戦埥澶愬础閻愬褰繝鐢靛仜閻楀懐鍒掑▎鎾宠摕闁绘柨鍚嬮埛鎺楁倵闂堟稑顥忔俊宸櫍濮婅櫣绱掑Ο璇查瀺缂備浇顕ч悧鎾愁嚕鐠囨祴妲堥柕蹇婃櫆閺呮繈姊虹紒妯烩拻妞ゎ厼鐗嗛埢宥咁潩閼哥鎷虹紓浣割儐椤戞瑩宕曢幇鐗堢厵闁告稑锕ラ崐鎰版煕閳瑰灝鐏叉鐐搭焽閹风娀骞撻幒鏂哄亾椤撶儐娓婚柕鍫濇閳锋帡鏌￠崪浣镐簼缂佸倸绉归、鏃堝醇閻斿弶瀚藉┑鐐舵彧缂嶁偓婵炲拑绲块弫顔尖槈閵忥紕鍘藉┑掳鍊撻悞锔剧矆鐎ｎ亖鏀介柍銉ョ－閸╋絾顨ラ悙瀵稿闁瑰嘲鎳橀幃閿嬶紣娴ｆ椽鎸兼繝纰夌磿閸嬫垿宕愰弽顬盯宕橀鍏肩€銈嗘磵閸嬫挾鈧娲橀崹鍧楃嵁濡偐纾兼俊顖滅帛閻濇娊姊洪崷顓炲付闁宦板妿閹广垽宕熼姘鳖唶婵犮垼鍩栭崝鏍煕閹达附鍋犳繛鎴炲坊閸嬫捇宕楅崨顓ф濠电姷鏁搁崑娑㈩敋椤撶喐鍙忛柟缁㈠櫘閺佸嫰鏌涢埄鍐姇闁稿鍊块弻锟犲炊閵夈儳浠鹃梺缁樻尭缁绘劙鈥︾捄銊﹀磯闁惧繒鎳撻。娲⒑鐠囧弶绂嬪ù婊勭箘閹广垹鈽夐姀鐘茬獩濡炪倖鎸鹃崳銉ノ涢敓鐘斥拺闂傚牊绋掗幖鎰版倵濮橆偄宓嗛柕鍡曠窔瀵挳濮€閳╁啯鐝抽梻浣规偠閸庮噣寮插┑瀣辈妞ゆ劑鍊楃壕浠嬫煕鐏炲墽鎳嗛柛蹇撶灱缁辨帡顢氶崨顓犱化闂佺懓绠嶉崹钘夌暦婵傜唯闁靛／鍛瘒婵犵數鍋涢顓熸叏閹绢噮鏁勯柛鈩冭泲婢舵劕閱囬柣鏃囨椤旀洟姊洪悷閭﹀殶闁稿孩鍔曢埢鎾诲籍閸喓鍘甸梺鑺ッˇ浠嬪磿閺冣偓閹便劍绻濋崟顓炵闂佺懓鍢查幊鎰垝閻㈢鍋撻敐搴′簽缂佸鏀辩换婵堝枈婢跺瞼锛熼梺绋款儑閸嬬喖鍩€椤掑倻鎳楅柛娑卞灣閻掑潡鎮楅獮鍨姎妞わ缚鍗冲畷鎰槹鎼存ê浜鹃柣鐔告緲椤ュ繘鏌涢悩宕囧ⅹ闁崇粯鎹囬、鏇㈡晲閸モ晝妲囬梻浣圭湽閸ㄨ棄顭囪閻☆厽绻濋悽闈涗粶闁活亙鍗冲畷鎰旈崘銊ョ亰缂傚倷鐒﹂敋妞ゆ洟浜堕弻鈩冨緞鐎ｎ亞浠煎銈嗘⒐閸旀洟鍩為幋锔藉€婚柛銉㈡櫇鏍￠梻浣告啞閹稿鎮烽埡鍛畺婵せ鍋撻柛鈺嬬節瀹曟﹢鏁愰崨顒€顥氭繝鐢靛仜閻楀棝鎮樺┑瀣嚑婵炴垶鐟х粻楣冩倶韫囨梻澧ら柛瀣崌楠炲洦鎷呴崷顓犫枆濠电姷鏁搁崑娑樜熸繝鍐洸婵犲﹤鐗嗙粻鏌ユ煠閸濄儱浠ù婊勭矒閺岀喓绱掗姀鐘典哗婵犫拃鍐ㄧ骇闁靛洤瀚幆鏃堝閳哄倻鏉规繝娈垮枛閿曘儱顪冮挊澶屾殾妞ゆ劧绠戝敮闂侀潧顦伴崝褏绱炴笟鈧濠氭晲閸涘倹妫冨畷姗€濡搁幇鈺佺仾闁靛洤瀚伴、鏇㈠閵忋埄鍞圭紓鍌欒兌缁垳鎹㈤崒鐑囩稏婵犻潧顑呯粈鍌炴煕韫囨挸鎮戦柣婵愬亜閳规垿鎮╅崹顐ｆ瘎闂佺顑囬崑銈呯暦瑜版帒閱囬柡鍥╁枎娴滈亶姊洪崫鍕殭闁稿﹨濮ら幈銊╁礃濞村鏂€闂佺粯锚绾绢參銆傞弻銉︾厓闂佸灝顑呴悘鎾煛鐏炲墽鈽夐柍瑙勫灴瀹曞崬螖婵犱胶纾婚梺鑽ゅ仦閸戣绂嶉鍕垫綎婵炲樊浜滃婵嗏攽閻樻彃鏆熼柛娆忔濮婄粯鎷呯粙璺ㄧ泿缂傚倸绉崇粈渚€鎮惧畡鎳婃椽顢旈崟搴涘姂閺屻劑寮村Δ鈧禍鍓х磽娴ｇ顣抽柛瀣枛閸┾偓妞ゆ巻鍋撻柛妯荤矒瀹曟垿骞樼紒妯煎帗閻熸粍绮撳畷婊冣槈濞嗘垹褰鹃梺鍝勬川閸犳捇姊介崟顖涚厱婵炴垶锕崝鐔兼煕濮椻偓娴滆泛顫忛搹瑙勫枂闁告洦鍋嗛ˇ銊╂煟韫囨挾绠查柣鐔叉櫈濡喖姊洪幐搴㈢５闁稿鎹囧Λ浣瑰緞閹邦厾鍘藉┑鈽嗗灡椤戞瑩宕ú顏呯厵闁哄被鍎抽悾娲煛鐏炵硶鍋撳畷鍥ㄦ畷闁诲函缍嗛崜娑㈡晬閻斿摜绠鹃悗鐢殿焾椤庢挾绱掗悩铏碍闁伙絽鍢查…銊╁幢閳哄倐顏堟⒒娴ｅ憡鍟為悽顖涱殘缁瑩骞掗弮鈧畷鍙夌節闂堟稓澧曢柡瀣墕椤法鎹勯搹鍦紘闂佹寧绋撻崰鏍ь潖閾忓湱鐭欓悹鎭掑妿椤斿姊洪幐搴㈢８闁搞劏濮ゆ穱濠勨偓娑櫳戞刊瀵哥磼椤栨稒绀冮柣搴☆煼濮婃椽宕烽鐐板濠电偛鍚嬮悷锔剧矉瀹ュ憘鏃堝川椤旀儳骞嶉梻浣侯焾缁绘劙宕ョ€ｎ喖纾挎俊銈呮噺閻撴洟鏌ｅΟ璇插婵炲牊娲橀妵鍕Ω閿濆懎濮﹂悗瑙勬礈閸犳牠銆佸☉妯锋闁圭儤鎸搁褰掓⒒娴ｈ棄鍚瑰┑顔芥綑鐓ら柕鍫濇媼閸ゆ洟鏌涢锝嗙闁煎摜鎳撻…璺ㄦ崉娓氼垰鍓繛瀛樼矋缁秹濡甸崟顖氱疀闁宠桨鑳堕崝鏉戔攽閳ュ啿绾ч柟顔煎€块獮鍐晸閻樺弬褍顭跨捄渚剳闁告ɑ鎹囧娲川婵犲嫮鐣甸柣搴㈠嚬閸撶喎顕ｉ幎鑺ュ亜闁惧繐婀遍敍婊堟⒑闁偛鑻晶顖滅磼缂佹绠炵€规洘甯掕灒鐎瑰嫰顣︽竟鏇㈡⒑閸︻厼鍔嬮柛鈺佺墕椤洭鍩￠崨顔惧弳濠电娀娼уΛ娆撳闯缁嬫鐔嗛悷娆忓缁€鍐ㄇ庨崶褝韬┑鈥崇埣瀹曞爼鈥栭鍝勫姦闁哄本绋撻埀顒婄秵閸嬪棗煤鐎电硶鍋撶憴鍕闁搞劌鐖奸悰顔芥償閵婏箑鐧勬繝銏犲帨閺咁亞绮婚幘璇茶摕闁绘柨鍚嬮崑瀣煕椤愩倕鏋旈柛鎴磿缁辨挻鎷呴崫鍕戯絽鈹戦悙璇ц含鐎殿喖顭烽幃銏㈡偘閳ュ厖澹曢梺姹囧灪椤旀牠鎮為崜褉鍋撳☉娆戠疄婵﹥妞介弻鍛存倷閼艰泛顏繝鈷€鍌氬祮闁哄本绋撻埀顒婄祷閸斿矂鍩€椤掍焦绀嬮柨婵堝仩缁犳盯骞樻担瑙勩仢妞ゃ垺妫冨畷鐔碱敇瑜嶉弫褰掓⒒娴ｇ儤鍤€闁告艾顑夐幃楣冾敂閸繂鐎繝鐢靛У绾板秹寮查浣虹闁瑰鍋為惃鎴犵棯閹规劖顥夐棁澶愭煥濠靛棙顥滅紒鑼额嚙闇夋繝濠傛噹娴滃墽绱掔紒妯兼创妤犵偞锕㈠鍫曞箣閻樻彃袪闂傚倷鑳堕…鍫ヮ敄閸℃稑绠板Δ锝呭暙閻掑灚銇勯幒鎴濇灓婵炲吋鍔栫换娑㈠箵閹烘梻顔掗悗瑙勬礉椤绮嬮幒鏂哄亾閿濆簼绨婚柣搴幗娣囧﹪濡惰箛鏇炲煂闂佸摜鍣ラ崑鍕亱濠殿喗銇涢崑鎾绘煛鐏炵偓绀冪€垫澘瀚埥澶愬閳藉棌鍋撳澶嬧拺闁告繂瀚峰Σ褰掓煙椤旂厧鈧悂锝炶箛鏇犵＜婵☆垵顕ч鎾绘⒑閹呯闁硅櫕鎸剧划顓㈡晸閻樻枼鎷洪梺鍛婄☉閿曘儵鍩涢幇顓滀簻妞ゆ挾鍋炴径鍕磼閸屾氨肖缂侇喗鐟﹂幆鏃堝箻鐎电硶鍋撴繝姘拺鐟滅増甯掓禍浼存煕濡湱鐭欓柟顕€娼ч悾锟犲箥閾忣偅鏉搁梻浣虹帛閸旀牕顭囧▎鎾村€堕柣鏂垮悑閻撴洟鏌曟繝蹇涙闁靛洦绻堥弻鐔碱敋閸℃瑧鐦堥悗娈垮枟閹歌櫕鎱ㄩ埀顒勬煥濞戞ê顏╅悽顖涘劤閳规垿鎮╅崹顐ｆ瘎闂佺顑嗛惄顖炲箖濡　鏀介悗锝庝簽椤︻喖鈹戦悩璇у伐闁绘锕幃锟犲即閵忊€斥偓鐢告煥濠靛棗鏆欏┑鈥炽偢閺屾盯寮拠娴嬪亾濠靛钃熺€广儱鐗滃銊╂⒑閸涘﹥灏扮€光偓閹间降鈧礁鈻庨幘鍐插敤濡炪倖鎸鹃崑鐔兼偘閵夆晜鈷戦柛婵嗗閳诲鏌涘Ο缁樺€愰柛鈹惧亾濡炪倖甯掗敃锕傛偩闁秵鐓熼柨婵嗙箳缁♀偓濡ょ姷鍋涚粔褰掋€佸▎鎾村殟闁靛鍠栭弲顓㈡⒒閸屾艾鈧绮堟担鍦彾濠电姴娲ょ壕濠氭煕濞戝崬濮告繛宸簼閺呮繈鏌涚仦鍓ь暡闁诲寒鍓熷铏瑰寲閺囩偛鈷夊銈忕畵缂傛岸濡甸幇鏉跨闁规儳鐡ㄩ悵鎶芥⒒娴ｇ顥忛柛瀣浮瀹曟垿宕ㄩ婊咁槸闂佸壊鍋侀崕鏌ュ煕閹寸姷纾藉ù锝堫嚃閻掔晫绱掗悩宕囧ⅹ闁宠鍨块幃娆戞嫚瑜嶆导鎰渻閵堝骸浜滅紒缁樺笧濡叉劙骞掗幊宕囧枔閹风姴顔忛鐟颁壕闁瑰墽绮埛鎴︽煕濞戞﹫鍔熼柍钘夘樀閺屻劑寮村Ο琛″亾濠靛棭鍤曢柟鎯版闁卞洦绻濋棃娑樻殲闁哄倵鍋撻梻鍌欒兌缁垶宕濆▎鎾€鐑藉磼閻愭彃鎯為柣搴秵閸撴稓澹曟總鍛婄厽婵☆垱瀵ч悵顏堟倶韫囷絽寮柡宀嬬秮閺佹劙宕惰楠炲姊烘潪鎵妽闁告梹鐟ラ悾鐑藉础閻愬秶鍠栧畷顐﹀礋椤愬鍊濆濠氬磼濞嗘垹鐛㈠┑鐐板尃閸涱喖搴婇梺鍦劋閹告悂宕归弮鈧妵鍕箻閸楃偟浠奸梺鍛婅壘缂嶅﹪寮婚弴銏犻唶婵犲灚鍔栨晥闂備焦濞婇弨閬嶅垂閸ф钃熼柣鏂垮悑閸ゅ啴鏌嶆潪鐗堫樂缂侇喖鐖煎娲川婵犲啠鎷归梺鎸庢磸閸ㄨ棄顕ｇ拠娴嬫闁靛繒濮甸ˉ婵嬫⒑閸︻収鐒鹃悗娑掓櫅閻ｅ嘲鐣烽崶鈺冿紳婵炴挻鑹惧ú銈夊几閵堝洨纾兼い鏇炴噹閻忥箑鈹戦垾宕囧煟闁轰焦鍔栧鍕節閸曞灚袨闂傚倷绀侀崯鍧楀箹椤愶箑鐤い鎰跺瀹撲胶鈧箍鍎遍ˇ浼村煕閹达附鍋ｉ柛銉戝啰楠囬梺鍦缂嶄線寮婚埄鍐╁閻熸瑥瀚埀顒佸姍閺屽秹濡烽婊呮殼閻庤娲栭妶鎼佸箖閵忥紕鐟规い鏍ㄧ〒閵堫偊姊婚崒娆戝妽閻庣瑳鍏犳椽寮介鐐碉紮閻熸粎澧楃敮妤呭磻閸屾稓绠鹃柛鈩兠慨鍌毭瑰鍕煉闁哄备鈧剚鍚嬮柛鎰╁妼椤懏绻濋姀锝庢綈閽冮亶鏌曢崶褍顏紒鐘崇⊕缁绘繈宕橀埡鍐ㄧ秲濠电姷顣藉Σ鍛村磻閸岀偞鍊块柨鏇楀亾妞ゆ洏鍎靛畷鐔碱敇濞戞ü澹曢梺鎸庣箓妤犲憡鏅舵导瀛樼厽闁挎洍鍋撻柣妤€锕﹂幑銏犫攽鐎ｎ偄浠洪梻鍌氱墛閸掆偓闁靛繈鍊栭悡鏇炩攽閻樻彃鈧崵绮旈搹鍏夊亾鐟欏嫭绀冨┑鐐诧躬楠炲啴鎮滈挊澶岀枃婵犵數濮撮崐鑽ょ矓濞差亝鐓欐い鏃囶潐濞呭懘鏌嶇拠鍙夊攭缂佺姵鐩顒€鈻庨悙顑喖姊婚崒娆掑厡缂侇噮鍨堕獮鎰嫚鐟佷焦妞介幃銏ゆ偂鎼淬倖鎲伴梻浣虹帛閺屻劑宕ョ€ｎ喖纾圭紓浣姑肩换鍡樸亜閺嶃劎绠ラ柛銈嗙懅閻ヮ亪寮剁捄銊愩垽鏌嶇憴鍕伌闁诡喗鐟ч埀顒佺⊕閿氶柛鎾崇秺濮婃椽宕妷銉愶綁鏌ｅΔ鍐ㄢ枅鐎规洘妞介幃娆撳传閸曨収鍚呴梻浣瑰濞插秹宕戦幘缁樼厽闁圭儤鎸婚妵婵嬫煛鐏炲墽娲存鐐叉喘婵℃悂鏁傞悾灞界到闂傚倷绶氶埀顒傚仜閼活垱鏅堕鐐寸厱闁哄啠鍋撻柣鐔叉櫅椤曪絿鎷犲ù瀣潔闂侀潧绻掓慨鐑藉储閹绢喗鈷戦悹鍥ｂ偓宕団偓濠氭煕閹板墎绋婚悗姘卞枛濮婂宕掑▎鎺戝帯闂佺娅曢幑鍥х暦閺屻儱钃熼柕澶堝劤閻ゅ洭姊鸿ぐ鎺戜喊闁哥姵鐗犲畷鐟扳攽閸モ晝顔曢梺绯曞墲钃遍悘蹇ｅ幘缁辨帡鎮╅崡鐐茬ギ濡ょ姷鍋為悧鐘荤嵁閺嶎収鏁囬柣鎰嚟娴滎亪姊绘担绛嬪殐闁哥姵鐗犻、鏍川閺夋垹鍘撮梺纭呮彧闂勫嫰宕戦幇鐗堢厱妞ゎ厽鍨垫禍婵囨叏閿濆懎顏紒缁樼箓閳绘捇宕归鐣屼壕闂備胶顭堢换鎴︽晪濡炪倖娲╃紞渚€銆侀弴銏℃櫇闁逞屽墮椤斿繐鈹戦崱蹇旀杸闂佺粯蓱瑜板啴寮冲▎鎴斿亾濞堝灝鏋涙繛纭风節楠炲啫螖閸涱垰绁﹂梺鍓茬厛閸犳牗鎱ㄦ惔鈽嗘富闁靛牆绻愰惁婊堟煕閵娿儳锛嶉柛鎺撳浮瀹曞ジ濡烽妷褜妲伴梻浣哥－閹虫捇濡靛Ο鑹板С濠电姵纰嶉ˉ濠冦亜閹扳晛鐏璺哄閺岀喓绮欏▎鍓у悑閻庤娲樻繛濠囧箠閻愬搫唯鐟滃繘顢欓弴銏♀拺闁告挻褰冩禍婵堢磼鐎ｎ偄鐏撮柛鈹惧亾濡炪倖甯婇懗鍓佺不閹炬番浜?")
        elif mode == "guided":
            lines.append("婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽弫鎰板川閸屾粌鏋庨柍璇查叄楠炲棜顦虫い鏂垮缁辨捇宕掑▎鎺戝帯婵犳鍠楅幐鎶藉箖濡警娼╅悹杞扮秿閿曞倹鐓曢柡鍥ュ妼閺嬨倝鏌ｉ妶鍌氫壕闂傚倷绀佸﹢閬嶅磻閹捐绠氶悘鐐跺▏濞戙垺鍊烽柣銏㈡暩閿涙繃绻涙潏鍓ф偧闁哄拋鍋婂畷濂割敂閸喓鍘辨繝鐢靛Т閸熸壆绮婚悙纰樺亾濞堝灝鏋涙い顓犲厴楠炲啴濮€閵堝棙鍎梺闈╁瘜閸橀箖宕㈤鐐粹拻濞达絿顭堥ˉ蹇涙煟閹惧磭澧︾€规洘濞婇、姘跺焵椤掆偓閻ｅ嘲鈹戦崶褏绐為梺褰掑亰閸樻悂骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囶亞鐣垫鐐诧躬瀹曟﹢顢旈崱娆欑床缂傚倸鍊烽悞锕傛晪濠电偞鎯岄崳锝夊蓟濞戙垹鐓橀柟顖嗗倸顥氭繝纰夌磿閸嬫垿宕愰弽顐ｆ殰闁圭儤顨呯粣妤佹叏濮楀棗澧婚柣鎺嶇矙閺岀喖鏌囬敃鈧獮妯肩磼閻樿崵鐣洪柡灞剧☉閳诲氦绠涢敐鍠般劍绻濋埛鈧仦濂稿仐闂佽鍣换婵囦繆閼搁潧绶為悗锝庡墮鐢儳鈹戦悩鍨毄闁稿鍨跺畷姗€鍩℃担璇′户缂傚倸鍊烽悞锕傘€冮崨姝ゅ洭妫冨☉杈ㄧ稁濠电偛妯婃禍婊勫閻樼粯鐓曢柡鍥ュ妼娴滄劙鏌涚€ｎ偅宕勯柕鍥ㄥ姍楠炴帒鈹戦崶銊︾彈濠电姷鏁搁崑娑樜涘▎鎾崇濠电姵鑹剧壕濠氭煕閺囥劌鐏￠柣鎾存礋閺屽秹鍩℃担鍛婃闂佹剚鍨卞ú鐔煎蓟閿濆绠婚悹楦裤€€閺嬪懘姊洪崫鍕伇闁哥姵鐗曢～蹇涙嚒閵堝倸浜鹃柣銏☆問閻掓儳鈹戦檱濡嫰鍩為幋锔藉€烽柡澶嬪灦閻︽垿姊洪崨濠傚Ё缂佹煡绠栧顒勫焵椤掍椒绻嗛柣鎰典簻閳ь剚鐗曡灋濞撴埃鍋撶€规洘鍨块獮鍥敇閻斿摜褰块梻浣瑰濞叉牠宕愯ぐ鎺撳亗婵炴垯鍨洪崐鍫曟煟閹邦厼绲婚柍閿嬫閺屾洟宕卞Ο鐑樿癁闂佸搫鑻粔鐑铰ㄦ笟鈧弻娑㈠箻閸楃偛顬嬮悗鍨緲閿曘儳鎹㈠┑鍡╂僵妞ゆ帒鍋嗗Σ鐑芥⒑鐠囪尙绠抽柛瀣枛瀹曟垿骞樼拠鑼厬闂婎偄娲︾粙鎺楁偂閺囩姭鍋撻崗澶婁壕闂侀€炲苯澧寸€规洘鍨块幃娆撴倻濡桨绨垫繝鐢靛仦閸垶宕瑰ú顏勭９闁割偅娲橀悡鐔兼煙閹殿喖顣兼繛鎳峰厾鐟邦煥閸愩劉鎸冪紓浣介哺鐢繝宕洪埀顒併亜閹烘垵顏╃紒鈧崘鈹夸簻闊洦鎸婚ˉ鐘绘煥濞戞瑧鐭岀紒杈ㄦ崌瀹曟帒鈻庨幋婵嗩瀴婵＄偑鍊ら崢鐓幟洪妸褍鍨濋悹鍥ф▕濞尖晠寮堕崼姘珖闁挎稒绮撳铏圭磼濡浚浜炴竟鏇㈩敇閵忕姷鍙€婵犮垼娉涢鍐╃濠婂嫨浜滈柟鏉垮閹偐绱掗悩闈涗沪闁靛洤瀚版慨鈧柍钘夋閻ｇ兘姊洪悷鏉挎Щ闁硅櫕鍔欏畷鐘诲冀椤撶偛宓嗛梺缁樺姈濠㈡﹢藟濮樿埖鈷掑ù锝呮啞閹牊绻涚仦鍌氱伈鐎规洜鎳撶叅妞ゅ繐瀚崢閬嶆⒑閸︻厼鍔嬮柛銈嗕亢閵囨劙骞掗幘瀛樼彸闂備礁鎲″ú锕傚闯椤曗偓瀹曟繈宕ㄧ€涙ǚ鎷虹紓鍌欑劍閿氱紒妞﹀洦鐓曢悗锝庡亝瀹曞苯鈹戦敍鍕毈鐎规洜鍠栭、娑橆潩妲屾牕鎮堝┑鐘垫暩婵炩偓婵炰匠鍏犲綊宕掑В鍏肩洴閺佸啴鍩€椤掑啰浜欓梻浣虹帛閿曘垹顭囪缁傛帡鏁冮崒娑氬幈闂侀潧顭堥崕铏閵忋倖鐓熼柨婵嗘搐閸樺鈧娲栭妶绋款嚕閹绢喗鍊风€广儰鐒﹀▍濠囨煛鐏炵偓绀嬬€规洜鍘ч埞鎴﹀炊瑜忛悰鈺呮⒒娴ｉ涓茬紓宥勮兌缁寮借濞兼牜绱撴担鑲℃垶鍒婇幘顔界厱闁挎棁顕ч獮妤呮煠閸喗鍠樻慨濠呮缁瑥鈻庨崜褍濮奸梻浣侯焾閿曘儳鎹㈤崒鐐村仼闁汇値鍨禍褰掓煙閻戞ɑ灏ù婊勵殔铻栭柣姗€娼ч崜閬嶆煕閹惧崬濡跨紒杈╁仦缁楃喖鍩€椤掑嫮宓佸┑鐘叉搐閸愨偓濡炪倖鎸鹃崑鐔煎储閹间焦鈷戦柛娑橈工婵箑霉濠婂牜妫戞俊鍙夊姍瀹曟ê霉鐎ｎ偅鏉搁梻浣虹帛閸旀﹢宕洪弽顑句汗鐟滃繒妲愰幒妤€绠甸柟鐑樻尭娴犳潙螖閻橀潧浠滈柨鏇ㄤ邯閻涱喖螣閸忕厧纾梺鎯х箰濠€閬嶆偤濡偐纾介柛灞捐壘閳ь剛鍏橀幃鐐烘晝娴ｅ摜绋戞繝鐢靛仜閻°劎鍒掑鍥у灊鐎广儱顦闂佸憡娲﹂崹鎵不婵犳碍鍋ｉ柧蹇氼潐绾绢亪鏌曡箛瀣偓鏍偂閺囩喍绻嗘い鏍ㄧ箖椤忕娀鏌熼悾灞叫ｉ柕鍥у婵℃悂鏁愰崨顓炐曢梻浣筋嚃閸犳鎮烽埡鍛祦闁规崘顕х粻鎶芥煙閻愵剚鍎楅柛鐔奉儔濮婂宕掑▎鎰偘濡炪倖娲橀悧鐘茬暦閺夎鏃堝礃閵娿儳浜伴梻浣筋潐瀹曟﹢顢氳缁寮舵惔鎾存杸闂佺粯蓱瑜板啴寮冲▎鎴犵＜闁告挷绀佹禒婊堟煃鐟欏嫬鐏撮柟顔规櫊楠炴捇骞掗崱妞惧婵犵數濮甸懝鎯ф纯婵＄偑鍊栭弻銊╂儍閻戣棄缁╁ù鐘差儐閻撶喐淇婇婵愬殭濠⒀屽灦閺屾盯鎮㈡搴ｎ啋闂佸搫鏈惄顖炲箖閳哄懎绠涘ù锝呮贡閺夊綊姊绘担鑺ャ€冪紒鈧笟鈧畷顖溾偓娑櫳戦崣蹇涙煃瑜滈崜鐔煎蓟閺囷紕鐤€濠电偞鍎虫禍楣冩煕閹邦厼绲荤紒鐘哄皺缁辨捇宕掑顑藉亾妞嬪海鐭嗗〒姘ｅ亾妞ゃ垺鐗犲畷濂稿Ψ椤旇姤娅旈梻浣筋潐閸庡吋鎱ㄩ妶澶婄柧闁圭粯甯╅悢鍡涙煠閸濄儳浠氶柟杈剧畱閻ょ偓銇勮箛鎾跺闁抽攱鍨垮娲敃閵堝懍绮堕梺鍏兼た閸ㄩ亶寮查崼鏇ㄦ晩濠殿喗鍔掔花璇差渻閵堝棗濮傞柛銊ㄥ吹缁粯绻濆顓犲幍濡炪倖姊婚弲顐︽儗婵犲洦鎳氶柨婵嗘噷閳ь剚甯掗～婵嬫偂鎼达絼鍝楁繝鐢靛仜閻楀棝宕ョ€ｎ剚宕叉繝闈涱儐閸嬨劑姊婚崼鐔衡棩缂侇喛娉涢埞鎴﹀煡閸℃ぞ绨奸梺鑽ゅ暱閺呮盯鎮鹃悜钘夋嵍妞ゆ挾鍠庨弸鍌炴⒑閸涘﹥澶勯柛妯恒偢閸╁懏瀵肩€涙ǚ鎷婚梺绋挎湰閼归箖鍩€椤掍焦鍊愮€规洘鍔栭ˇ鐗堟償閿濆洨鍔跺┑鐐存尰閸╁啴宕戦幘鎼闁绘劕妯婂Ο鈧梺杞扮劍閹瑰洭骞冮埡鍛殤妞ゆ帒顦弫瑙勭節瀵伴攱婢橀埀顑懎绶ゅù鐘差儏閻ゎ喗銇勯幇鈺佲偓妤呮偝缂佹ü绻嗛柕鍫濇噺閸ｅ湱绱掗悩鑼Ш闁哄瞼鍠撻崰濠囧础閻愯尙顔掗梻浣告啞钃遍柣鈺婂灦瀵鍩勯崘鈺侇€撻梺鍛婃尰瑜板啴宕滈崼鏇熲拺闁告繂瀚～锕傛煕閺傝法鐒搁柛鈺冨仱楠炲鏁冮埀顒勭嵁閵忋倖鐓冮柛婵嗗閳ь剛鏁诲鎼佸籍閸啿鎷绘繛杈剧秬婵倝濡撮崘顏嗙＜闁逞屽墯缁楃喖鍩€椤掆偓閻ｇ兘顢涢悙鑼啋濡炪倖妫佹竟鍫ュ箺閺囥垺鈷戦柛婵嗗閸屻劑鏌涢妸銉хШ闁哄苯顑夊畷鍫曞Ω瑜忛惁鍫ユ⒒閸屾氨澧涚紒瀣浮钘熼柟杈鹃檮閻撴洟鎮楅敐搴′簼鐎规洖鐬奸埀顒冾潐濞插繘宕濆鍥ㄥ床婵犻潧顑呯粈瀣煕椤垵浜伴柡浣圭矋缁绘繂顕ラ柨瀣凡闁逞屽劯閸涱厾绛忔繛瀵稿Т椤戝懘鎮块濮愪簻闁哄稁鍋勬禒婊堟煟閹惧瓨绀嬮柡宀€鍠栭幃婊冾潨閸℃鏆﹂梻浣虹帛閹歌煤濮椻偓婵＄敻宕熼姘辩杸闂佸疇妗ㄧ拋鏌ュ磻閹捐鍗抽柕蹇曞Т閸ゆ垿姊洪崫鍕殭闁绘锕幃锟犲礃閳瑰じ绨婚梺鍝勭Р閸斿酣鍩婇弴鐘电＜闁逞屽墰閳ь剨缍嗛崰妤呮偂濞戞埃鍋撻崗澶婁壕闂侀€炲苯澧寸€规洑鍗冲鍊燁槾闁哄棴绠撻弻銊モ攽閸℃﹩妫炵紓浣稿閸嬨倝骞冨Δ鍛櫜閹煎瓨绻勯幐澶愭⒑缁嬫鍎愰柟鐟版喘閻涱噣宕堕浣镐罕闂佸壊鍋侀崹褰掔嵁閹扮増鐓熼幖绮光偓鍐茶緟闂佺顑嗛幑鍥蓟瀹ュ牜妾ㄩ梺鍛婃尵閸犲酣鎮鹃柨瀣嚤闁哄鍨甸崬銊ヮ渻閵堝棙灏甸柛瀣枛閹潡宕堕浣叉嫼缂傚倷鐒﹂敋濠殿喖娲弻鐔哄枈閸楃偘绨婚梺杞扮贰閸ｏ絽顫忕紒妯诲闁荤喖鍋婇崵瀣攽椤旂》宸ユい顓犲厴楠炴牜鎲撮崟顒€鍔呴梺鎰佸幑閸庤崵绱炴担鍓插殨闁肩鐏氶崕鐔兼煙閹呮憼闁哄鎮傚缁樻媴閾忕懓绗￠梺鎼炲姂濞佳呭弲闂侀潧艌閺呮稓绮堥崱娑欑厽婵°倐鍋撻柣妤€绻掔划缁樸偅閸愨晛鈧爼鏌ｉ幇顓炵祷闁逞屽墯閹倿宕洪埀顒併亜閹哄秷鍏岀紒鐘靛仧閳ь剚顔栭崳顕€宕戞繝鍌滄殾婵せ鍋撴い銏＄懇瀹曞弶绔熼姘闁绘挻娲橀妵鍕箛闂堟稐绨肩紓浣藉煐濮樸劎妲愰幒妤€惟鐟滃秹宕㈢€涙ɑ鍙忓┑鐘插亞閻撹偐鈧娲樼敮鎺楀煝鎼淬劌绠ｉ柣姗€娼ф惔濠囨⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栨稒娅犲ù鐓庣摠閻撴洟鎮楅敐搴′簽婵炲弶鎸抽弻鐔风暦閸パ勭亪濡炪們鍨虹粙鎴﹀煡婢跺ň鏋庨柟閭﹀枛婵炲洭姊婚崒娆戭槮婵犫偓闁秵鎯為幖娣妼缁愭淇婇妶鍛櫤闁稿鍊圭换娑㈠幢濡搫顫囨繛瀛樼矋缁捇寮婚敓鐘茬＜婵犲灚鍔曞▓顓熺節绾版ǚ鍋撻崘鍙夊€紓浣虹帛缁嬫捇骞忛悩渚Ь闂佷紮绲块弫鎼佸焵椤掑喚娼愭繛鍙夛耿瀹曟繂鈻庨幘宕囩暫濠电姴锕ら悧濠囧吹瀹ュ鐓忓璇″灠閸燁偆绮婚悙娴嬫斀闁挎稑瀚禍濂告煕婵炲灝鈧繂鐣烽姀锛勵浄閻庯綆浜滈悗顓㈡⒑閸撹尙鍘涢柛瀣閵嗗懘寮婚妷锔惧幘闂佽鍘界敮鎺楀礉閵堝洨纾奸柣妯垮吹閻ｆ椽鏌＄仦璇测偓鏇㈡箒闁诲函缍嗛崑鍛存偟閺冨牊鈷戦柛婵嗗閸庡繘姊虹敮顔剧М鐎殿喛顕ч濂稿炊閵娿儲鐎梻浣告啞濞诧箓宕戦崱妯侯嚤鐎光偓閸曨兘鎷洪柣鐘叉礌閳ь剝娅曢悘鈧梻浣告惈閹冲繒鎹㈤崟顐嬶綁骞囬弶璺唺闂佺懓鍟跨壕顓㈠窗閹邦喗宕叉繝闈涙－濞尖晜銇勯幘璺烘瀾妞ゆ柨鍟埞鎴︽偐濞堟寧娈扮紓浣介哺濞茬喎鐣烽幋锕€绠ｉ柨鏇楀亾缁炬儳缍婇弻鈥愁吋鎼粹€崇闂佹悶鍔岄崐鍧楀蓟閿濆顫呴柕蹇婃櫇閸斿摜绱撴担鍝勑ュ┑鐐╁亾闂佸搫鐬奸崰鏍蓟閸ヮ剚鏅濋柍褜鍓熷绋库槈閵忥紕鍘遍梺闈涱煭婵″洨绮婚悙鐑樼厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柟顔规櫊楠炴捇骞掗幋顓熺稉缂傚倸鍊烽懗鍫曞磻閹捐纾块柟鎯版鍥撮梺褰掓？缁€渚€鎷戦悢鍏肩叆婵犻潧妫Σ鍝ョ磼閻樺磭鈯曢柕鍥у楠炴帡骞嬮鐔滐箑鈹戦悙鑼闁绘牜鍘ч～蹇撁洪鍕獩婵犵數鍋炵敮鈺傜濠婂牊鍋╅柣鎴犵摂閺佸棝鏌涢弴妯哄Ψ闁稿鎹囧顕€宕煎┑鍫О婵＄偑鍊栭弻銊ノｉ崼锝庢▌闂佸搫鏈惄顖炲春閸曨垰绀冮柣鎰靛墰閺嗐儲淇婇悙顏勨偓銈夊磻閸曨個娲敇閻戝棙缍庨梺鎯х箰濠€閬嶆儗濞嗘挻鐓曢柡宥冨€曟晶鏌ユ煛娴ｇ懓鍔ら柍瑙勫灴閹瑧鎹勯搹瑙勵嚄闂備礁鎽滄慨鎾煀閿濆鈧礁顫濋懜鍨珳婵犮垼娉涢敃銈囩玻濞戞瑧绡€闁汇垽娼у瓭闂佸摜鍣ラ崑濠傜暦濠靛宸濋悗娑櫱氶幏娲⒒閸屾氨澧涘〒姘殜閹偞銈ｉ崘鈺冨幈闁瑰吋鐣崹褰掑煝閺囥垺鐓欐い鏃€鍎虫禍楣冩煏閸剛绉€规洘锕㈤崺鐐烘倷椤掆偓椤忓湱绱撻崒姘偓鎼佸磹閻戣姤鍊块柨鏇氱劍閹冲本淇婇悙顏勨偓鎴﹀磿閸楃倣娑樷枎閹寸偛搴婂┑鐐村灟閸ㄧ懓顪冩禒瀣厱闁规澘鍚€缁ㄥジ鏌涚€ｆ柨瀚弧鈧梺闈涢獜缂嶅棗顭囬幇顓犵闁肩⒈鍓欓弸娑欘殽閻愭潙濮堢紒缁樼箞瀹曟﹢顢旈崱妤呯崕濠电姷鏁告繛鈧繛浣冲吘娑樷槈濮樿京鐓嬪┑鐐叉▕娴滄繈鎮″☉妯忓綊鏁愰崶銊ユ畬婵犳鍠栫粔鍫曞焵椤掑喚娼愭繛鍙夌墵婵″爼骞栨担纰樺亾娓氣偓瀵挳濮€閻欌偓濞煎﹪姊洪幐搴ｂ槈閻庢凹鍘奸埢鎾绘嚋閻㈢數鐦堥梺姹囧灲濞佳冩毄闂備浇妗ㄩ悞锕傚箖閸屾氨鏆﹂柟瀛樼妇濡插牓鏌曡箛濞惧亾閸忓懐缍嶉梻鍌欑閹测€趁洪敃鍌氬瀭濞村吋娼欓崹鍌炴煕鐏炵虎鍤旂憸鐗堝笚閸嬫劗鈧懓澹婇崰鏍礈娴煎瓨鈷戦柦妯侯槸閺嗙喖鏌涢悩鍐插闁瑰箍鍨归埥澶愬閻樻鍚呴梻浣虹帛閸旀寮幖浣瑰亗闁稿瞼鍋為埛鎴炴叏閻熺増鎼愰柍褜鍓氶崝娆忕暦閹达箑绠荤紓浣骨氶幏缁樼箾鏉堝墽鍒伴柟璇х節楠炲棝宕奸妷锔惧幈闂佺粯娲戠粈浣圭閹殿喒鍋撶憴鍕闁告梹鐟ラ悾閿嬬附缁嬪灝宓嗛梺缁樺姍濞佳勬叏閿旀垝绻嗛柣鎰典簻閳ь剚鐗滈弫顔界節閸曨厾鐒兼繛杈剧秬濞咃絿绮婚弮鍌涘枑闊洦娲橀～鏇㈡煙閻戞ɑ灏扮紓宥呮喘閺屾洘绻涢崹顔煎闁荤姴娲ㄩ崑娑⑩€旈崘顔嘉ч柛鎰╁妿娴犻箖姊洪懡銈呮殌闁搞儜鍛瀫闂備礁婀遍搹搴ㄥ窗閺嶎偆鐭嗛悗锝庡亖娴滄粓鏌熼悜妯虹仴闁逞屽墮閹芥粎妲愰悙鍝勭妞ゆ棁袙閹锋椽鏌ｉ悩鍙夊鐟滄澘鍟撮、妤呭鎺虫禍婊堟煛閸愶絽浜鹃梺缁橆殘婵挳鎮鹃柨瀣嚤闁哄鍨甸崬銊ヮ渻閵堝棙灏甸柛鐘插缁傚秹顢涘☉姘辩槇闂傚倸鐗婄粙鎴﹀焵椤掍焦鍊愭鐐搭殔椤劑宕橀鍛啌濠电偞鎸婚崺鍐磻閹剧粯鐓欐い鏃傜摂濞堟粓鏌℃担鐟板闁诡垱妫冮崺鍕礃椤忓嫯鎷梻鍌氬€峰ù鍥ь浖閵娧呯焼濞达綀顕氬ú顏嶆晣闁靛繒濮鹃幗鏇㈡⒑閹稿海绠撴い锔诲灣閻氭儳顓兼径瀣帗閻熸粍绮撳畷婊堟偄閼测晛绁﹂梺鍛婂姦閸犳牠鏌嬮崶顒佺厸闁搞儮鏅涙禒褔鏌涢弮鎾剁暠妞ゎ亜鍟存俊鍫曞幢濡も偓濞兼垿姊虹粙娆惧剱闁圭懓娲璇测槈閵忊€充簻闂佸憡绋戦敃锔剧矙閸パ屾富闁靛牆楠告禍婊呯磼缂佹ê绗ф俊鍙夊姍楠炴帡骞婂畷鍥ф灈闁硅櫕鐗犻崺锟犲磼濮橆厾鏉介梻鍌氬€搁崐椋庢濮樿泛鐒垫い鎺戝€告禒婊堟煠濞茶鐏￠柡鍛埣椤㈡瑦鎱ㄩ幇顏嗙泿婵＄偑鍊栭幐楣冨磻閻愮數鐭氶柟绋跨昂娴滄粓鏌ㄩ弴妤€浜剧紓鍌氱Т閿曨亪鐛幇顓犵瘈闁稿本顨嗛弬鈧梻浣规偠閸庮垶宕曢幍顔垮С濠电姵纰嶉埛鎴︽偡濞嗗繐顏╅柛鏂诲€楅埀顒冾潐濞诧箓宕滈悢鐓庣畺婵せ鍋撻柛鈺嬬節瀹曟﹢顢旈崪鍐闂傚倷娴囬鏍垂鎼淬劌绀嬫い鎰ㄥ墲濡﹪姊婚崒娆戭槮闁圭⒈鍋婇幆澶嬬附缁嬭法鐛ラ柟鍏肩暘閸斿矂鎮″┑瀣厵闁硅鍔﹂崵娆撴煕閵娿儱鈧綊濡甸崟顖氱睄闁稿本绋掗悵顏呯箾鐎涙鐭ゅù婊庝簻椤繒绱掑Ο璇差€撻柣鐔哥懃鐎氼剚绂掗埡鍛拺闁告稑锕ラ悡銉х磼婢跺﹦鍩ｆ鐐村灴婵偓闁靛牆鎳橀崬鍫曟⒑闂堟侗妲堕柛搴㈡尦楠炴寮撮姀鈾€鎷洪梺鍦焾濞撮绮婚幘娣簻闁挎棁顕ч悘锕傛煥濠靛牆浠辩€规洏鍔庨埀顒佺⊕椤洭宕㈤挊澶嗘斀闁宠棄妫楅悘鐘绘煙绾板崬浜扮€殿喗濞婇弻鍡楊吋閸℃瑥骞愰梻浣虹《閸撴繈銆冮崼鐔告珷闁挎棁濮ら崣蹇撯攽閻樺弶鍣烘い蹇曞Х缁辨帡顢欓悾灞惧櫚閻庤娲滄繛鈧柛銊╃畺瀹曟ê顔忛鑺ョギ闂傚倸鍊搁崐宄懊归崶褜娴栭柕濞у懐鐒兼繛鎾村焹閸嬫捇鏌嶉妷顖滅暠闁伙綇绻濋弻鍥晝閳ь剙鈻撻妸锔剧瘈闁汇垽娼ф牎缂佺偓婢樼粔鐟邦嚕閺屻儱绠甸柟鐑樼箘閸炵敻鏌ｉ悩鐑樸€冮悹鈧敃鍌涘亗妞ゆ帊鑳剁粻楣冩煟閹惧啿鍤遍棅顒夊墯閹便劍绻濋崨顕呬哗缂備浇椴哥敮鎺曠亽闂婎偄娴勭徊濂告焽椤栨壕鍋撶憴鍕８闁稿海鏁诲畷娲焵椤掍降浜滈柟鐑樺灥閳ь剝宕垫竟鏇㈠礂缁楄桨绨婚梺鍝勬处椤ㄥ懏绂嶉幆褉鏀介柣鎰緲鐏忓啴鏌涢妷顖滃矝闁稿鎹囧顕€宕煎┑鍫О婵＄偑鍊栭弻銊ノｉ崼锝庢▌闂佸搫鏈粙鎴﹀煡婢舵劕纭€闁绘劕鍚€閸栨牗淇婇悙顏勨偓鏍蓟閵娾晜鏅濇い蹇撳濞兼牗绻涘顔荤盎濞磋偐濞€閺屾洘寰勯崼婵嗗闂佹寧绻傞ˇ浼存偂濞嗘挻鐓曟繛鎴烇公瀹搞儵鏌涢弬璇测偓婵嗙暦閿熺姵鐒肩€广儱妫涢崢鐢告⒑缂佹﹩娈旈柣妤€锕﹀▎銏ゆ嚑椤掑倻锛滈梺缁樏崯鍧楀煝閺囥垺鐓涚€光偓閳ь剟宕伴弽顓犲祦闁糕剝鍑瑰銊╂⒑閹肩偛鈧宕伴幘鑸殿潟闁圭儤鎸哥欢鐐测攽閻樻彃顏╅柣鎾跺枎閳规垿顢欑涵閿嬫暰濠碉紕鍋犲Λ鍕亱闂佸憡鍔﹂悡浣姐亹閹烘嚦褔鏌涢埄鍐噭闁告帗鐩幃妤冩喆閸曨剛锛橀梺鍛婃⒐閸ㄥ潡濡存担绯曟婵☆垶鏀遍～宥呪攽閻愬弶顥為柛銊ョ埣閿濈偛鈹戠€ｎ偀鎷婚梺绋挎湰閼归箖鍩€椤掍焦鍊愮€规洘鍔欓獮鏍ㄦ媴閸濄儻绱梻浣虹帛閸ㄥ吋鎱ㄩ妶澶婂惞闁告洦鍨遍悡鏇熴亜閹板墎绋荤紒鈧埀顒傜磽娴ｅ搫啸濠电偐鍋撻梺鍝勭灱閸犳牠鐛幋锕€绠涢梻鍫熺⊕椤斿嫰姊洪悷鏉挎倯婵炲吋鐟╅弫鍐敂閸繆鎽曢梺鎸庣☉鐎氼亜鈻介鍫熷仯闁搞儯鍔岀徊璇测攽椤旇偐鍩ｆ慨濠勫劋濞碱亪骞嶉鍛滈梺璇插閸戝綊宕滈悢鐓庣伋闁挎洖鍊搁柨銈嗕繆閵堝嫮顦︽繛鍫熺箞濮婂宕掑鍗烆杸缂備礁顑嗛崹鍧楁晲閻愬搫鐐婃い鎺嶈閹锋椽姊绘笟鍥т簽闁稿鐩幊鐔碱敍閻愭彃鍋嶉梺鍛婄缚閸庡磭澹曟總鍛婄厓鐟滄粓宕滃杈╃當闁绘梻鍘ч悞鍨亜閹烘垵顏柡鍛叀閺岋綁骞囬浣叉灆闂佺粯鎸堕崕鐢稿蓟濞戙埄鏁冮柨婵嗘川閻ｅジ姊洪崨濠冾棖缂佺姵鍨块垾鏃堝礃椤斿槈褔鏌涢埄鍐炬畼闁荤喆鍔戦弻锝嗘償閵忕姴姣堥梺鍛婃尰缁嬫捇宕氶幒鎾剁瘈婵﹩鍓欓崬銊ヮ渻閵堝棙灏甸柛鐘虫崌瀹曘垽骞樼紒妯锋嫼闂佸憡绋戦敃锔剧不閹剧粯鍊垫慨妯煎帶瀵喚鈧娲栭崯璺ㄥ弲濡炪倕绻愰幊鎰板储闁秵鐓熼幖鎼灣缁佺兘鏌涢弬鎸庢拱闁逛究鍔戝畷鎺楁倷鐎电骞愰柣搴″帨閸嬫捇鎮楅敐搴″鐞氾箑鈹戦悩鎰佸晱闁哥姵甯″畷鎴﹀箻缂佹ǚ鎷洪梻鍌氱墛缁嬫挻鏅堕弴鐔剁箚妞ゆ劧绲块幊鍥煛鐏炶濮傛い銏★耿婵偓闁挎稑瀚獮妤呮⒒娓氣偓濞佳呮崲閸℃稑鐤炬繛鎴欏灪閸婂爼鏌ｅΟ鑲╁笡闁稿﹤鐏氱换娑㈠箣閻愯尙鐟插┑鐐叉噹濞差參寮婚悢鑲╁祦闁割煈鍠氭禒濂告⒑鐎圭媭娼愰柛銊ョ秺閸┾偓妞ゆ帒锕︾粔鐢告煕鐎ｎ亜顏紒鍌涘笒鐓ゆい蹇撴噳閹峰姊虹粙鎸庢拱婵ǜ鍔嶉弲璺衡槈濮樿京锛滈柣搴秵閸嬪嫭鎱ㄦ径鎰厱闁圭儤鎸哥粭褔鏌熼悷鏉款仾缂佹鍠栭、娑樷槈濡吋袙闂傚倸鍊风欢姘焽瑜旈幃褔宕卞銏＄☉閳诲酣骞囬鍌滅嵁闂備礁鎲″ú锕傚垂闁秵鍋傞柡鍥╁枍缁诲棙銇勯弽銊ь暡閻犳劧绻濋弻锝夘敇閻旂儤鍣銈冨妸閸庣敻骞冨▎鎾村殤妞ゆ巻鍋撻柍顏勭仛缁绘繄鍠婂Ο鍝勨拤闂佽鍠栭崐鍨暦濞差亜鐒洪柛鎰ㄦ櫅椤庢挻绻涢幘鏉戝毈闁搞劋鍗冲鏌ヮ敂閸曘劍鏂€闂佹寧绋戠€氼剚绂嶆總鍛婄厱濠电姴鍟版晶顏呫亜椤愩垻绠茬紒缁樼箓椤繈顢楅埀顒勫磻瀹ュ鍋℃繝濠傚暟缁犲鏌熷畷鍥т槐闁哄苯妫楅濂稿川閸屾ê濮傞柡灞界Ч瀹曨偊宕熼鐔蜂壕闁汇垻顭堢粻顖涚箾瀹割喕绨奸柍閿嬪灴閺屾稑鈽夊鍫濆缂備胶濮甸幑鍥箖濡も偓椤繈鎮℃惔锝勬闂備焦瀵х换鍕磻閵堝鏋侀柛鎰靛枛绾惧吋绻涢幋鐐跺妤犵偛鐗撳娲偡閺夋寧鍊梺浼欑秵娴滎亜鐣峰┑鍫氬亾閿濆骸鏋涚紒鐘靛枎铻栭柨婵嗘噹閺嗙偤鏌ｉ幘瀵告噭闁靛洤瀚板顕€鍩€椤掑嫬纾块柧蹇ｅ亞椤╃兘寮堕崼姘澒闁稿鎸鹃幉鎾礋椤掑偆妲紓鍌氬€哥粔鎾晝椤忓牆违濞撴埃鍋撶€殿喗鎸虫慨鈧柍銉ュ帠濮规姊洪崫鍕垫Ц闁绘鍟村鎻掆攽閸″繑鐏冮梺绉嗗嫷娈曢柍閿嬪浮閺屾稓浠﹂崜褎鍣銈忚闂勫嫮鎹㈠┑瀣劦妞ゆ帒瀚悞鑲┾偓骞垮劚閹虫劙鏁嶉悢鍏尖拺闂傚牊绋撴晶鏇熴亜閿旇鐏︾€规洖缍婂畷鎺楁倷鐎电骞楅梻渚€娼х换鍫ュ春閸曨垱鍊垮Δ锝呭暞閻撶喖鏌熼悜妯虹仼濞寸姵鐩弻鏇㈠炊瑜嶉顓燁殽閻愭潙娴€规洖宕—鍐箚瑜滃Λ婊堟⒒閸屾艾鈧兘鎳楅崼鏇樷偓浣圭節閸愨晛寮块梺闈涚墕濞层倝宕瑰┑瀣厵闁绘劦鍓欐晶顖炴煕閵堝棙绀冮柕鍥у楠炲洨鎹勯搹瑙勑掗梻浣芥〃缁€渚€顢栨径鎰摕鐎广儱鐗滃銊╂⒑閸涘﹥灏伴柣鐔叉櫊楠炲啴骞嗚閺嗗姊洪銊ヮ洭闁告瑥妫濆娲川婵犲啫顦╅梺鍛婃尰閻熲晠銆侀幘璇茬缂備焦菤閹锋椽姊洪棃鈺佺槣闁告ê澧介弫顔尖槈閵忊€充缓濡炪倖鐗楅悢顒勫绩閼姐倗纾奸柡鍐ㄥ€搁弸娑氣偓娈垮枟閹告娊骞冨▎鎾崇厸闁稿本绋掑鎴︽⒒閸屾瑨鍏岀紒顕呭灦瀹曟繂螣闂傚鍓ㄥ┑鐐叉閸旀牕鈻嶉悩缁樼厸闁搞儯鍎遍悘顏堟煟閹捐泛鏋涢柣鎿冨亰瀹曞爼濡搁敂瑙勫缂傚倷鑳舵慨鐑藉磻閻旂厧鐒垫い鎺嶇贰閸熷繘鏌涢悩鍐插摵闁炽儻绠撳畷濂稿Ψ閵壯冨箳闂佺懓鍚嬮悾顏堝礉瀹€鈧划濠氭晲婢跺鍘藉┑鈽嗗灣閳峰牓寮冲鍛＜闁告鍋涚痪褍菐閸パ嶈含闁诡喗鐟╅、鏃堝礋閵娿儰澹曢梺鍝勮癁鐏炲墽绋佸┑鐘垫暩婵敻鎳濇ィ鍐╁仾闁绘劦鍏欐禍婊堟煙閺夊灝顣抽柣锝堜含缁辨帡鎮╅棃娑掓瀰闂佸搫鏈惄顖涗繆閻戠瓔鏁婇柟顖嗗啫绱┑鐘垫暩閸嬫盯鎮ч崨顖氬灊婵炲棙鎸搁拑鐔兼煥濠靛棭妲哥紒鐘崇⊕閵囧嫰寮介悽闈涘煂濠电偛鐗婄换鍫濐潖缂佹绡€閹肩补鈧枼鎷婚梻浣告啞閹歌鐣濋幖浣肝ラ柛鎰靛枛鍞梺鍐叉惈閸婃悂鍩€椤掑倸鍘寸€殿喖鐖煎畷濂告偄妞嬪寒妲伴梻渚€鈧偛鑻晶鍙夌箾婢跺绀嬮柛鈹惧亾濡炪倖甯婄欢锟犲疮韫囨稒鐓曢柣妯哄暱閸濊櫣鈧鍣崑鍡涘箯閻樼粯鍤戞い鎺嶇劍椤旀洟鏌ｉ悢鍝ョ煂濠⒀勵殘閺侇噣鍩￠崨顓熺€梺鍛婂姦閸犳鎮¤箛娑氬彄闁搞儯鍔嶇粈鈧銈呴閻倿寮诲鍫闂佸憡鎸婚悷褔骞戦姀鐘栫喐绗熼娑氱▉濠电姷鏁告慨鐢告嚌閸撗冾棜闁稿繗鍋愮粻楣冩煕閳╁厾顏嗙箔閹烘鐓曟慨妤€鐗忕壕璺ㄧ磼鏉堛劍灏扮紒妤冨枛瀹曟儼顦抽柣婵愬櫍濮婃椽骞栭悙鎻掝潊濠电偛顦伴惄顖炲箖閹呮殝闁逛絻娅曢弬鈧梺璇插嚱缂嶅棝宕戦崨顓涙瀺闁搞儺鍓氶埛鎴犵磼鐎ｎ偄顕滄繝鈧悧鍫熷弿婵☆垳顭堟慨鍌炴寠濠靛洢浜滈柟鎹愭硾娴滃綊鏌￠埀顒佺鐎ｎ偆鍘介梺褰掑亰閸樼晫绱為幋锔界厽闊洦娲栭弸娑㈡煛鐏炲墽娲村┑鈩冩倐婵＄兘鏁冩担渚敤缂傚倸鍊风欢锟犲窗閺嶎厽鍋嬮柟鎯х－閺嗭箓鏌ｉ弮鍌楁嫛闁轰礁绉电换娑㈠箣閻愯泛顥濆Δ鐘靛仦閿曘垹顫忕紒妯诲缂佹稑顑呭▓鎰版⒑閸涘鐒介柡鍜佸亰瀵偊顢氶埀顒勭嵁閹烘嚦鏃堝焵椤掑倻鐭嗗璺侯儑缁犻箖鏌涢埄鍏狀亪鎮橀埡鍐／闁诡垎浣镐划闂佽鍠栫紞濠傜暦閹偊妲荤紓浣哄珡閸曗晙绨婚梺闈涱檧缁蹭粙鎮橀弻銉︾厸鐎光偓鐎ｎ剛锛熸繛瀵稿缁犳捇骞冨▎鎿冩晢闁稿被鍊栨晥闂備浇顕у锕傦綖婢跺⊕鍝勵煥閸繂鍋嶉悷婊勬瀹曟椽鎮欓崫鍕吅闂佹寧娲嶉崑鎾绘煟閹邦剨鍔熼柟鎻掓啞閹棃鈥﹂幋鐐存珕闂備胶绮…鍥╁垝椤栫偛鐓曢柟鐑樺灟閳ь剚甯掗～婵嬫晲閸涱剙顥氶梻鍌欑窔閳ь剛鍋涢懟顖涙櫠娴煎瓨鐓曢悗锝庡亞濞叉挳鏌熷畷鍥ф灈妞ゃ垺绋戦埥澶娾枎閹邦喖濞囬梻鍌欒兌缁垶銆冮崨瀛樺亱闁告洦鍓涢々鍙夌節婵犲倻澧涢柣鎾崇箻閻擃偊宕堕妸锔绢槬濡炪倕瀛╅幐鎼侊綖濡ゅ拋鏁冮柨婵嗘噹閹界敻姊洪崫鍕拱婵炶尙鍠庨悾鐑藉醇閺囩倣鈺呮煏婢跺牆鍔存繛鍏煎哺濮婄粯鎷呯粵瀣異闂佸摜濮电敮鈥愁嚕閹绘巻鏀介柛顐ゅ櫏濞肩喖姊洪崷顓炲妺闁搞倧绠撻幃銏ゅ礂閼测晛寮抽梺璇插嚱缂嶅棙绂嶉懜闈涱嚤?")
        else:
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欑粣娑㈡⒑閸濄儱校闁圭澧介崚鎺旂磼濡浜濋梺鍛婂姀閺呮繈宕㈡禒瀣拺闂侇偅绋戝畵鍡樼箾娴ｅ啿瀚▍鐘炽亜閺嶎偄浠﹂柣鎾跺枑缁绘繈妫冨☉娆忣槱缂備讲鍋撻悗锝庡亝閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濮风槐鎺楊敊閻ｅ本鍣ч梺瀹狀嚙闁帮綁鐛崱姘兼Щ婵犮垼顫夐敋闁宠鍨块幃娆撴嚑椤掍焦鍠栫紓鍌欑贰閸犳碍鎱ㄩ悽鐢电焿鐎广儱顦介弫鍌炴煕閺囥垺娑ф繛鍫涘姂閺岋綁鎮╅崣澶婎槱缂備椒鐒﹀娆忓祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔告倐濮婃椽宕ㄦ繝鍐ｆ嫻闂佸湱顭堥崯鍧楋綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愬宀婃澓濠电姷鏁搁崑娑㈡偤閵娧冨灊鐎广儱顦伴崑瀣煛閸モ晛浠滅紒渚囧亰濮婄粯鎷呯粙娆炬闂佺顑勭欢姘暦瑜版帗鍤掗柕鍫濇媼濡粓姊洪懞銉冾亪藟閵忥絻浜归柟鐑樻尰濞呮粓姊虹化鏇炲⒉妞ゃ劌鐗忕划濠囨煥鐎ｎ剛顔曢柣搴㈢⊕椤洭鎯岄幒鏃傜＜闁绘ê纾晶顏呫亜椤愩垻绠婚柟鐓庣秺瀹曠兘顢橀悩闈涘箚闂備浇宕垫慨鍨娴犲绀夐幖娣灩椤曢亶鏌涢妷顔煎闁抽攱鍨圭槐鎺斺偓锝庡亽閸庛儵鏌涙惔銏犵伌闁哄本绋撻埀顒婄祷閸斿矂鍩€椤掍胶绠為柣娑卞櫍瀹曟﹢顢欓懞銉︻仧闂備胶绮摫鐟滄澘鍟悾鐢稿幢濞戞瑢鎷虹紓鍌欑劍钃遍柍閿嬪笧缁辨帞绱掑Ο鑲╃暭闂佸ジ缂氭ご鍝ユ崲濠靛棭娼╂い鎾寸⊕鐎氬ジ姊洪懡銈呮瀾闁荤喆鍎抽埀顒佸嚬閸樻儳鈻庨姀銈呯闁圭儤绻勯崬鐢告偡濠婂啰效闁哄苯锕弫鎰緞鐏炵晫銈﹂梻浣告啞閸旓箓宕板Δ鍛惞闁告劦鍠楅悡鍐煕濠靛棗顏╅柡鍡欏枛閺屻劌鈽夊▎鎴犵厜濠殿喖锕ㄥ▍锝囨閹烘嚦鐔荤疀閿濆嫮鏁栨繝銏ｎ潐濞茬喖銆佸鈧幃銏ゅ川婵犲嫬濞囬梻鍌欑劍閻綊宕硅ぐ鎺戠疅闁跨喓濮甸崑鍌涚箾閹存瑥鐏柛濠傜埣閺岋綁骞囬鐐电シ闂佹娊鏀卞Λ鍐蓟瀹ュ鏁嶆繛鎴炵懅椤︻厾绱撴担浠嬪摵閻㈩垳鍋熷Σ鎰板箳閹冲磭鍠栭幊鏍煛閸愨晜绶伴梻浣筋嚙濮橈箓锝炴径濞掑搫顫滈埀顒勫极閸愵喖顫呴柕鍫濆暊閸嬫挻绗熼埀顒€顕ｉ鈧畷鐓庘攽閸偅效闂傚倷绶氬褔鈥﹂鐘典笉闁硅揪瀵岄弫鍌涖亜閺嶃劎銆掔紒鈾€鍋撻梻浣圭湽閸ㄨ棄顭囪閻楀孩淇婇悙顏勨偓鏍ь潖瑜版帗鍋嬮柣妯垮皺閺嗭箑霉閸忓吋缍戦柛鎰ㄥ亾婵＄偑鍊栭幐楣冨窗閹邦兘鏋嶉柛銉墯閳锋垿姊婚崼鐔剁繁婵℃彃鐖奸弻娑欐償閳╁啯鍎撻梺闈涙鐢偤骞忛悩鍨晳濞达絽鎽滅粔娲煙椤旇娅呮い鏂跨箻椤㈡瑩鎮℃惔鈽嗘闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灦瀹曘垽宕妷褏锛滈梺濂告櫜缁茬粯绔熷Ο姹囦簻闁哄浂浜炵粔顔筋殽閻愯揪鑰挎い銏＄懅閸犲﹥娼忛妸褏袩闂傚倸鍊烽懗鍓佸垝椤栫偞鍋￠柕蹇嬪€曠壕濠氭煙閹屽殶缂佺娀绠栭弻锝夊箻閸愭彃姣愰梻濠庡墻閸撴岸骞堥妸锔剧瘈闁告劏鏂傛禒銏犫攽閳藉棗浜滈柛鐕佸亰閸┿儲寰勬繝搴㈠兊闁哄鐗冮弲婊冾熆閺嶎厽鈷掗柛灞剧懆閸忓瞼鐥鐐靛煟鐎殿喗褰冮埥澶婎潩閿濆懍澹曞┑顔斤供閸樼晫娆㈤弻銉︾厽闁挎繂娲ら崢瀛樸亜閵忊槅娈滅€规洘锕㈤弫鍌炲箰鎼达絾缍庨梻鍌氬€风粈浣革耿闁秴纾块柕鍫濐槸缁犱即鏌熺紒銏犳灈缂佺媭鍨崇槐鎾存媴鐠囷紕鍔风紓浣哄█缁犳牕顕ｉ崼鏇為唶婵犻潧妫岄幐鍐⒑閸涘﹤绗傞柛妤佸▕瀵鎮㈤悜妯虹彴閻熸粌绻掑褔鍩€椤掆偓铻栭柣姗€娼ф禒婊勪繆椤愶絿绠撻柣锝夋敱缁虹晫绮欑拠淇卞姂閺屻劑寮埀顒勫磿閹剁晫宓佹俊銈勬缁诲棝鏌ｉ幇鍏哥盎闁逞屽墯閻楁洟顢欒箛鏃傜瘈婵﹩鍓涢敍娑㈡⒑閻熸澘鈷旂紒顕呭灦閹ょ疀濞戞瑧鍘卞銈嗗姉婵挳鎮炲ú顏呯厽闁圭儤顨堥悾娲煛瀹€瀣М闁轰焦鍔栧鍕偓锝庡亝濞堟悂姊虹拠鏌ュ弰婵炰匠鍥х紒瀣儥閸ゆ洟鏌涢锝嗙缂佺媴绲剧换婵嬫濞戞瑯妫￠梺鍝勬缁绘ê顫忓ú顏呭殥闁靛牆鎳忛悗鍓х磽娓氬洤鏋涢柣顒€銈搁獮鎴﹀閻樻牜鍠愮粭鐔碱敍濮橆収鍚欓梻鍌欐祰椤宕曢崗鍏煎弿闁靛牆顦悿鐐節闂堟侗鍎愰柣鎾存礋閹﹢鎮欓幓鎺嗘寖闂侀潧妫欑敮锟犲蓟濞戞﹩娼ㄩ柛鈩冩礈閸戝湱绱撴担铏瑰笡缂佽鐗婇幈銊╁焵椤掑嫭鐓ユ繝闈涙椤ョ娀鏌曢崱妯哄闁宠鍨块崺銉╁幢濡炲墽鍑归梻浣藉吹閸犲棝宕曢悽绋挎槬闁靛繒濯崥瀣熆鐠虹尨宸ョ紒鎰☉椤啴濡堕崱娆忣潷缂備緡鍠栭柊锝夊极瀹ュ拋鐓ラ柛顐ゅ暱閹疯櫣绱撻崒娆戝妽妞ゎ厼娲獮濠囧礃椤旂晫鍘甸梺鎯ф禋閸嬪嫭鎱ㄦ径宀€纾兼い鏃傛櫕閹冲洭鏌熺粵鍦瘈濠碘€崇埣瀹曞爼鍩＄€ｎ剙绨ョ紓鍌氬€搁崐鎼佸磹閻戣姤鍊块柨鏇炲€甸埀顒婄畵瀹曞爼鍩￠崘褏鐟濋梻浣虹帛閸旀鎹㈠┑鍫熷床闁糕剝菧娴滄粓鏌熼幍铏珔闁诲繆鏅犻弻锟犲幢濡吋鍣伴梺鍝勮嫰缁夊綊骞愭繝鍐ㄧ窞婵☆垱浜堕敃鍌涒拺閻庡湱濯崵娆撴⒑鐢喚绉柣娑卞櫍瀹曞爼顢楁径瀣珝闂備胶绮崝蹇涘疾濞戞瑧顩插Δ锝呭暞閳锋垿鏌涢…鎴濇珮闁稿骸娴风槐鎺旀嫚閸欏妫﹂梺鍝勭焿缂嶄線鐛崶顒€绀傞柛婵勫劤濞夊潡姊绘笟鈧埀顒傚仜閼活垱鏅堕娑氱闁告瑥顦辨晶鍨節閳ь剚鎷呯化鏇熸杸濡炪倖姊婚悺鏃堟倿閻愵剛绠惧璺侯儑濞插鈧娲栫紞濠傜暦閹烘鍊烽柡澶嬪灣閸栨牠姊洪崫鍕垫Ш闁稿鍋為崚濠冪鐎ｅ灚鏅㈤梺缁樻煥閹芥粎绮绘ィ鍐╃厱闊洦鑹炬禍鐟邦熆瑜滈崜娑氭閹烘梻纾兼俊顖氱毞濡插牆顪冮妶鍡樼叆缂佺粯锕㈤妴浣糕枎閹炬潙娈ラ梺闈涚墕濞诧箓寮查妸鈺傗拺閻犲洤寮堕幑锝夋煙閾忣偅宕屾鐐差樀閺佸秹宕熼鈧惔濠囨⒑缁嬭法鐏遍柛瀣洴閹€愁潨閳ь剟寮婚悢鍛婄秶濡わ絽鍟宥夋⒑缁嬫鍎愰柛鏃€鐟╁濠氭偄閾忓湱锛滃┑鈽嗗灠閹碱偄顭囬幋锔解拺缂佸顑欓崕鎰版煙濮濆苯鍚归柟骞垮灩閳规垿宕遍埡鍌氬厞闂備胶顭堢换鎰板触鐎ｎ亖鏋嶉柛鈩冦仜閺€浠嬫煟濡櫣浠涢柡鍡忔櫅閳规垿顢欓悙顒佹瘎闂佸摜濮撮敃銈夘敇閸忕厧绶炲┑鐘插楠炲牓姊绘担鐑樺殌妞ゆ洦鍘介幈銊︻槹鎼粹槅妫滄繝闈涘€搁幉锟犲磹閻㈠憡鐓ユ繝闈涙閸戝湱绱掗妸銉吋闁哄矉缍侀垾锕傚箳閺冨倻妲囬梻浣告惈閻鎹㈠┑瀣槬闁逞屽墯閵囧嫰骞掑鍫濆帯缂備讲妾ч崑鎾寸節濞堝灝鏋熼柨鏇楁櫊瀹曘垺銈ｉ崘銊ュ亶闂佽姤锚椤︻偊寮ㄦ禒瀣闁规儼妫勭壕褰掓煛閸ャ儱鐏╅柣銈庡枟閵囧嫰骞囬埡浣轰紕闂佺懓顫曢崕閬嶅煘閹达附鏅柛鏇ㄥ亗閺夘參姊虹粙鍖℃敾闁绘娲滈崣鍛存⒑閸愬弶鎯堥柛鐕佸亞濞嗐垽濡舵径瀣幈闂佸湱鍋撻〃鍛偓姘煎墯閹梹绻濋崒妤佹杸闂佺粯顭囩划顖氣槈瑜庢穱濠囶敃椤愩垹绠瑰銈庡幖濞差參宕洪敓鐘茬＜婵☆垰婀遍惄搴ㄦ⒒娴ｅ憡璐￠柛搴涘€濆畷褰掓偨缁嬭法鍔﹀銈嗗笂閻掞箓宕愰幇鐗堢厱闁宠鍎虫禍鐐繆閻愵亜鈧牜鏁幒妤€纾归柛娑橈功椤╅攱绻濇繝鍌氼仴濞存粍绮嶉妵鍕疀閹炬剚浠奸梺鍝勬４缁蹭粙鍩為幋锕€鐏崇€规洖娲ら悡鐔兼倵鐟欏嫭绀€鐎规洦鍓濋悘鍐⒑闁偛鑻晶顔姐亜椤撶偞鍠樻鐐差儔閺佸倻鎲撮敐鍡楊伖缂傚倸鍊风粈渚€顢栭崱娑辨晞婵炲棙鎸哥壕鍧楁煙閹殿喖顣奸柣鎾寸懇閺岋綁鎮㈤崫鍕垫毉闂佸摜濮甸…鍥焵椤掍緡鍟忛柛鐘崇洴椤㈡俺顦归柛鈹垮劜瀵板嫰骞囬澶嬬秱闂備胶绮…鍥极閹间礁绾ч柟闂寸劍閳锋帒銆掑锝呬壕濠电偘鍖犻崶锝傚亾閿曞倸閱囬柕澶堝劤閿涚喖姊虹紒姗嗘當闁绘绻橀幃鐢稿醇閺囩喓鍘搁梺鎼炲劘閸庨亶鎮橀鍫熺厓闂佸灝顑呭ù顕€鏌＄仦鍓с€掑ù鐙呯畵楠炴垿骞囬澶嬵棨闂傚倷绶氶埀顒傚仜閼活垱鏅舵导瀛樼厱闊洦妫戦懓鎸庮殽閻愭彃鏆ｉ柟顔界懇閹粌螣缂佹褰囬梻鍌欒兌椤牓寮甸鈧～婵嬪Ω閳哄倸浠煎┑鐐叉▕娴滄繈鍩涢幋锔界厱闁圭偓娼欑徊璇裁瑰鍕畺缂佺粯鐩畷锝嗗緞鐏炶В鎷″┑鐘灱椤煤閻旇偐宓侀柟閭﹀幗閸庣喖鏌ㄥ┑鍡樺窛婵℃彃娲ら埞鎴︽偐閸偅姣勬繝娈垮枟閹稿啿鐣烽幇顔剧＜婵☆垳绮悵鐑芥⒑閸濆嫭宸濆┑顕€顥撴竟鏇熺附閸涘﹦鍘撻悷婊勭矒瀹曟粓鎮㈡搴㈡濠殿喗銇涢崑鎾淬亜閵忥紕鎳囬柟顔煎⒔娴狅箓鎸婃径宀€鎳栭梻鍌氬€搁崐椋庣矆娓氣偓楠炲鏁嶉崟顒€搴婇梺绋挎湰婢规洟宕戦幘鎰佹僵闁绘挸楠搁埛瀣倵濞堝灝鏋涢柛鐔锋健閸┿垺鎯旈妸銉ь啋闂佸搫顦伴崹鎶藉礌閺嵮€鏀介柣鎰煐瑜把呯磼閼艰埖顥夐柨鏇樺灲閺屽棗顓奸崨顖滃幀闂備線鈧偛鑻晶顕€鏌嶇憴鍕伌妞ゃ垺鐟у☉闈涚暋妫颁胶鐭楀┑锛勫亼閸娿倝宕㈡總绋垮簥闁哄被鍎查崑鈺呮煟閹达絾顥夌紒鐘冲▕閺岀喓鈧稒蓱閳锋劙鏌ｆ惔鈽嗙吋婵﹥妞介幃鐑藉箥椤旇姤鍠栫紓鍌欐祰椤曆囧磹閸ф鐏抽柡宥冨妼缁剁偤鏌熼柇锕€骞愰柟閿嬫そ閺岋綁鎮╅崣澶嬫倷閻庢鍠栭悥濂哥嵁閹达附鏅插璺侯儑閸樹粙姊虹紒妯烩拻妞ゎ厼鐗撻崺銏ゅ即閻橆偄浜鹃悷娆忓绾炬悂鏌涢弮鈧崹鍧楀Υ娴ｇ硶妲堟慨妤€妫涢崣鍡涙⒑閸涘﹣绶遍柛妯垮亹缁顫濋懜纰樻嫽闂佺鏈懝楣冨焵椤掑倸鍘撮柟铏殜瀹曞ジ寮村Ο宄颁壕濞达絽婀辩弧鈧梺鎼炲劀閸滀礁鏂€濠碉紕鍋戦崐鏇犳崲閹扮増鍋嬪┑鐘叉搐閻撴洟鏌￠崘銊у闁绘挻娲熼弻锟犲炊閵夈儱顬堥梺璇茬箳婵兘鎯€椤忓牊鍊锋い鎺嗗亾妞ゆ洘绮岃彁闁搞儜宥堝惈婵犵鈧磭鍩ｇ€规洏鍔戦、娆撳礂绾板彉鐢婚梻鍌氬€烽懗鍓佸垝椤栫偛绠伴悹鍥梿濞差亝鍋勯柣鎾虫捣閻ｅ搫鈹戦濮愪粶闁稿鎹囬弻鐔碱敊閻ｅ本鍣伴悗娈垮枛閻栧ジ鐛€ｎ亖鏀介柛鐘靛閸ㄥ灝顫忕紒妯诲闁绘垶锚濞堝矂姊洪崨濠呭妞ゆ垵顦甸悰顕€宕橀鑲╋紲闂佺粯鍔樼亸顏堝箺閺囥垺鍊垫鐐茬仢閸旀岸鏌ｅΔ浣虹煀妞ゎ剙锕俊鎼佸煛閸屾瀚奸梻浣告啞缁嬫垿鏁冮妷褌鐒婇柣妤€鐗婇崣蹇斾繆椤栨粠鐒惧┑顔煎€婚埀顒侇問閸ｎ噣宕戞繝鍥モ偓浣割潩鐠鸿櫣鍔﹀銈嗗笒鐎氼剟宕归崒鐐寸厵妞ゆ牕妫楅幊蹇撯枔妤ｅ啯鈷戦柟鑲╁仜閸旀﹢鏌涢弬璺ㄐфい銏＄懇瀵挳鎮㈤搹鍦闂備焦鐪归崹钘夘焽瑜嶉悺顓㈡⒒娴ｇ懓顕滄繛鎻掔箻瀹曟劕螖閸涱厾鍔﹀銈嗗笂缁€渚€宕甸鍕厱婵☆垰婀遍惌娆戔偓瑙勬礃绾板秶鎹㈠┑瀣倞鐟滃繘顢欓幒鎴富闁靛牆妫欓埛鎺楁煛閸滀礁浜扮€规洏鍨虹粋鎺斺偓锝庡亐閹疯櫣绱撻崒娆戝妽閽冮亶鏌ｉ幘鍗炲姦闁哄瞼鍠撻崰濠囧础閻愭澘鏋堥梻渚€娼уΛ妤呭磹閸喚鏆︽俊銈呮噹缁€鍌炴煟閹炬娊顎楀ù鐓庨叄濮婄粯鎷呴悷閭﹀殝缂備浇顕ч崐鍧楃嵁婵犲懐鐤€婵炴垶顭囬鎰版⒑鐟欏嫬顥嬪褎顨婇幃锟犲礃椤旇棄浠┑鐐叉缁绘劙顢旈埡鍛厽闊洦姊圭亸锕傛煛瀹€鈧崰鏍€佸▎鎾村仼閻忕偞鍎冲▍姘舵⒒娴ｄ警鏀版繛鍛礈閸掓帡骞樺鍕洴瀹曟﹢濡搁姀鈽嗘綌婵犵數鍋涘Λ娆撳箰婵犳艾姹叉俊顖濆亹绾句粙鏌涚仦鎹愬闁逞屽墯閹倸鐣烽幇鏉跨濞达絽鎽滈敍娆撴⒑閸涘﹦缂氶柛搴㈠▕閹矂骞樺ǎ顑跨盎闂佸搫娲﹂〃鍛妤ｅ啯鍊甸悷娆忓缁€鍐煕閵娿儲鍋ラ柣娑卞枛椤粓鍩€椤掑嫮宓侀柛銉ｅ妽婵挳鏌ｉ悢绋款棆婵¤缍佸濠氬磼濞嗘垹鐛㈠┑鐐板尃閸ャ劌浜遍梺绯曞墲閿曗晛鈻撴禒瀣厱婵炴垶锕崝鐔搞亜閳轰礁绾х紒缁樼箖缁绘繈宕掑闂存樊濠电偛鐡ㄧ划宥囧垝閹捐钃熼柕濞炬櫅缁秹鏌涢妷锝呭闁靛棗锕︾槐鎾存媴妞嬪海鐛㈤梺琛″亾閺夊牄鍔庨埞宥呪攽閻樺弶绁╅柡浣稿暣閺屾洟宕煎┑鍥ф闂佽绻愰悧鎾愁潖閾忚瀚氶柍銉ㄦ珪閻忓牓姊洪幖鐐茬仾闁绘搫绻濋崹楣冩晝閸屾鈺呮煃鏉炴媽鍏屾い锔芥緲椤啴濡堕崱妤冪懆濡炪倧缂氶崡瀹犳＂闂佸壊鍋侀崕鏌ユ偂閻旂厧绠规繛锝庡墮閻掓椽鏌涢悢椋庣闁哄本鐩幃鈺佺暦閸パ€鎷伴梻浣哄仺閸庤崵绮婚幘璇茬畺婵犲﹤鐗婄€电姴顭跨捄铏圭伇闁哄棭鍋婂缁樼瑹閳ь剙顭囪閹广垽宕奸妷銉ョ€┑鐐叉▕娴滄粎澹曠紒妯诲弿婵＄偠顕ф禍楣冩⒑閸濆嫯瀚扮紒澶庮潐娣囧﹪鎮滈挊澹┿劑鏌曟径鍫濆姢妞ゆ垵鐗嗛埞鎴︽偐椤旇偐浼囧銈庡亜椤︻垳鍙呴梺鍝勭▉閸樺ジ鎮″鈧弻鐔告綇妤ｅ啯顎嶉梺绋匡功閸忔﹢寮婚埄鍐ㄧ窞閻庯綆浜炴禒鍏肩箾鐎电啸妞ゎ厼鐗撻垾鏃堝礃椤斿槈褔鏌涘☉鍗炴灓妞も晝澧楃换娑氣偓娑欘焽閻倕霉濠婂簼閭┑鈥崇摠缁楃喖鍩€椤掆偓椤曪綁顢氶埀顒€鐣烽悡搴樻斀閻庯綆浜濋弳顏堟⒒閸屾瑨鍏岀紒顕呭灦瀵濡搁埡鍌氬壄濠电娀娼ч鍛婵犳碍鐓欓柟瑙勫姦閸ゆ瑩姊洪崡鐐村枠闁哄矉绻濆畷鍫曞煛娴ｅ湱浜栭梻浣告啞閿曗晜绂嶅┑鍫熷床婵犻潧顑呴～鍛存煥濠靛棙顥犻柕鍡樺姇閳规垿鍩ラ崱妞剧凹闂佽崵鍠嗛崕鐢稿春閵忕媭鍚嬪璺猴工閼板灝鈹戦悙鏉戠仸闁荤啙鍥у偍濞寸姴顑嗛埛鎴︽偡濞嗗繐顏╅柛鏂诲€濋弻锝嗗箠闁告柨娴烽崚鎺楀醇閳垛晛浜鹃柨婵嗛閺嬬喖鏌ｉ幘瀵搞€掗柍褜鍓欓崢婊堝磻閹剧粯鍊甸柨婵嗛婢ф壆鎮敃鍌涚厽閹兼番鍩勯崯蹇涙煕閿濆骸娅嶇€规洘濞婇弫鎰緞婵犲啯袣闂備線鈧偛鑻晶顖炴煏閸パ冾伃妤犵偞甯￠獮瀣攽閸ヮ煈鍚樻繝鐢靛仜閻°劎鍒掑畝鈧槐鐐寸節閸パ嗘憰濠电偞鍨崹鍦不濞戙垺鐓忓┑鐘茬箻濡绢噣鏌ｅ┑鍥╁ⅹ妞ゎ亜鍟存俊鍫曞磼濞戞瑧褰嗛梻浣虹帛閹碱偆鎹㈠┑鍡╁殨閻犲洦绁村Σ鍫ユ煏韫囨洖啸妞ゆ梹甯掗埞鎴炲箠闁稿﹥鍔欏畷鎴﹀箻缂佹鍘甸梺鎯ф禋閸嬪嫭鎱ㄥ澶嬬厸濞达絽鎽滃瓭闂佸疇顫夐崹褰掑焵椤掑﹦绉甸柛瀣у亾闂佸湱鏌夊▍锝囨閹惧瓨濯撮柛鎾村絻閸撻亶鏌ｆ惔锝囨嚄闁告劘鍎婚埀顒€鐏濋湁闁绘挸娴烽幗鐘绘煟閹捐泛啸闁瑰弶鎮傞幃褔宕煎┑鍫剬闂備椒绱徊鎯ь渻娴犲钃熸繛鎴欏灩閻撴﹢鏌熼鍡楀€搁ˉ姘節绾板纾块柛瀣灴瀹曟劙寮介锝嗘闂佸湱鍎ら弻锟犲磻閹炬剚娼╂い鎺嗗亾婵℃彃顭烽幗鍫曟倷閻戞鍘甸柣搴ｆ暩椤牆鏆╃紓浣哄亾閸庢娊濡剁粙娆惧殨闁割偅娲栭柋鍥ㄦ叏濮楀棗骞楅柣婵囨⒐缁绘稓鈧數顭堥埢鍫澝瑰鍐煟鐎殿喛顕ч埥澶愬閻橀潧骞嬮梻浣筋嚃閸ㄥ酣宕掑鍏碱棥婵犵數濮烽。顔炬閺囥垹纾婚柟杈剧畱绾惧綊鏌″搴′簼闁哄棙绮撻弻鐔兼倻濡崵鍘搁梺绋款儐閹告悂锝炲┑瀣亗閹艰揪绱曢惈鍕⒒娴ｇ瓔鍤冮柛锝庡灣閹广垹鈹戦崱鈺佹闂佸湱铏庨崰妤呭磻閸曨垱鐓ｉ煫鍥ㄥ嚬閸ゅ啴鏌涢悢鐑藉弰婵﹦绮幏鍛存倻濡儤鐣梻浣割吔閺夊灝顬嬮梺鐟扮畭閸ㄨ棄鐣烽幒妤佸€烽柡澶嬪灦閻ゅ倿鏌ｉ悢鍝ョ煂濠⒀勵殘閺侇喖螖閸涱喖浜楅梺缁樻閸嬫劙宕ｉ幘缁樼厱闁靛绲介崝姘舵煕閺傝鈧妲愰幒妤€鐓㈤柍褜鍓熷畷鎴﹀箻缂佹ǚ鎷绘繛杈剧到閹诧繝骞嗛崼銉︾厽妞ゆ挾鍎愬Σ娲煙楠炲灝鐏╅柍瑙勫灴瀹曞崬鈻庨幇顓у晭闂傚倸鍊风欢锟犲礈濞嗘垹鐭撻柟缁㈠枛绾偓闂佽鍎兼慨銈夋偂閻斿吋鐓欓梺顓ㄧ畱閻忕娀鏌ｉ妸锔姐仢闁哄本娲熷畷濂割敃閵忥紕浜剁紓鍌欒兌缁垳鎹㈤崒鐐茬厺闁规崘顕ч崹鍌涖亜閺冨倹娅曞ù婊庝邯濮婄粯鎷呴悷閭﹀殝濠电偞褰冪换妯虹暦濠靛棛鏆嗛柛鏇ㄥ亞閸樻椽鎮楅獮鍨姎妞わ缚鍗冲鏌ュ蓟閵夛妇鍘卞┑鐐村灥瑜板鑺遍崗绗轰簻妞ゆ劑鍨绘晥濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈崨顒傜？濠碉紕鍋戦崐銈夊储婵傚憡鍋嬮柛鈩冧緱閺佸﹪鐓崶銊﹀皑闁衡偓娴犲鐓曢柕澶涚到閸旀瑧绱掗妸銉吋婵﹥妞藉畷顐﹀礋椤愮喎浜剧憸鐗堝笒绾捐法鈧娲栧ú鐘诲磻閹炬剚娼╂い鎺戝瀵即姊洪崫鍕缂佸鍏樼瘬濞撴埃鍋撻柡灞剧洴楠炴﹢寮堕幋婵囨嚈闁诲氦顫夊ú妯兼崲閸岀偛鐓濋幖娣€楅悿鈧梺鎸庣箓濡稓绮欐担鍦瘈闁汇垽娼ф禒婊勪繆椤栨熬鏀荤紒鍌氱Т椤劑宕ㄩ娆戠憹濠电偞娼欓崥瀣焽濞嗘垹涓嶉悷娆忓缁犻箖鏌ㄥ┑鍡涱€楀褜鍣ｉ弻锝堢疀閿濆懏鐝濋梺鍝勮閸斿矂鍩ユ径濞炬瀻婵炲棙宸婚崑鎾诲箰鎼淬垹寮挎繝鐢靛Т閹冲繘顢旈悩鐢电＜妞ゆ梻鏅幊鍥┾偓瑙勬礈婵炩偓闁糕晛瀚板畷姗€鍩￠崒娑氭Д缂傚倸鍊搁崐鎼佸磹瀹勬噴褰掑炊椤掑鏅悷婊勬楠炲啳顦规鐐搭焽缁辨帒螣鏉炴壆閽靛┑锛勫亼閸婃牕煤瀹ュ纾婚柟鎯х亪閸嬫挾鎲撮崟顒傤槰闂佹寧娲忛崹浠嬪Υ娴ｇ硶鏋庨柟閭﹀櫍濡绢噣姊洪崨濠勨槈闁挎洏鍎遍埢鎾诲棘鎼存挻鏂€闂佺粯顭堢亸娆徫涢崟顖涚厸濠㈣泛锕﹀銊╂煕鐎ｎ偅宕屾鐐叉喘瀵墎鎹勯…鎺斿耿闂傚倷娴囬～澶愬磿閾忣偅娅犻幖杈剧到椤ユ艾鈹戦崒姘暈闁绘挸鍟伴幉绋款煥閸繄顦┑鐐村灟閸ㄥ綊鎮為崹顐犱簻闁圭儤鍩婇崝鐔虹磼婢跺本鏆柡灞剧〒閳ь剨绲洪弲婵嬪礉瀹ュ洨纾奸柛灞炬皑瀛濆銈庡幑閸旀垵鐣锋總鍛婂亜闁告繂瀚粻浼存⒑鐠囨煡顎楃紒鐘茬Ч瀹曟洟鏌嗗鍛焾濡炪倖鍔х徊鑲╂崲閸℃稒鐓曠憸搴ㄣ€冮崱娑欏亗闁告劦鍠楅悡銏′繆椤栨瑨顒熸俊顖氱墛娣囧﹪宕ｆ径瀣偓鎰繆椤愶紕鍔嶇€垫澘瀚伴獮鍥敇閻樻彃绠哄┑鐘愁問閸犳銆冮崨顓囨稑螖閸涱厼鍤戝┑鐐村灟閸ㄦ椽鎮￠悢鑲╁彄闁搞儯鍔嶇亸顓犵磼閻欐瑥娲﹂悡娆忋€掑顒備虎濠碉紕鏅槐鎺旂磼濡偐鐤勯悗瑙勬礃閿曘垽宕洪悙鏉戠窞婵繂鏈妤呮⒒娴ｇ瓔鍤欐慨姗堢畵閿濈偞寰勬繛鎺撴そ閺佸啴宕掑鎲嬬幢濠电姷鏁告慨鎾磹婵犳艾姹查柨鏇炲€归悡鐔兼煛閸愩劌鈧摜鏁崼鏇熺厱闁靛鍎遍埀顒€缍婃俊鐢稿礋椤栨氨鐤€濡炪倖甯掗崐鐢稿几閸℃绠鹃悗娑欘焽閻绱掗鑺ュ磳鐎规洘妞介幃娆撳传閸曨収鍚呴梻浣瑰濡礁螞閸曨垰鐒垫い鎺戝濡垿鏌嶈閸撴盯骞婇幘瀵哥彾濠电姴娲ょ粣妤佷繆閵堝嫮鍔嶆繛鍛箲缁绘繈鎮介棃娴躲儵鏌℃担瑙勫€愮€规洘鍨甸埥澶婎潨閸℃顓块梻浣稿閸嬪懎煤濮椻偓瀹曟垹鈧綆鍠楅悡鐔镐繆椤栨侗鍎ラ柛銈嗙懇閺岋綀绠涢弬搴撴灆闂佸搫琚崝鎴濐嚕閹绢喗鍊锋繛鏉戭儏娴滈箖鏌熼梻瀵稿妽闁稿﹤鍢查埞鎴︽偐閹绘帗娈ф繛瀛樼矋缁捇寮婚悢鐓庝紶闁告洦鍓﹀Λ鐐寸箾鐎涙鐭婂褏鏅Σ鎰板箻鐎靛摜鎳濋梺鎼炲劀閸屾粎娉跨紓鍌氬€风粈渚€藝椤栨粎绀婂┑鐘插亞閸ゆ洟鎮归崶銊с偞婵℃彃鐗婇幈銊ヮ潨閸℃ぞ绨奸梺鍛婃礀閸熸壆妲愰幘璇茬＜婵炲棙鎸婚鏍⒑閹肩偛濡芥俊鐐扮矙楠炲啯銈ｉ崘鈺佹疂闂佹眹鍨婚弫鎼侇敊閺囥垺鐓熼幖娣灮閳洘銇勯鐐村枠闁诡垰鑻悾婵嬪礋椤掑倸骞堥梺璇插嚱缂嶅棝宕戦崨顖欑剨闁汇垹鎲￠悡娆愵殽閻愯尙浠㈤柣蹇婃櫊閺屽秹鎸婃径妯烩枅婵犳鍠掗崑鎾绘⒑缂佹﹩鐒炬い鏇嗗洤鏋侀悷娆忓缁♀偓闂佹眹鍨藉褔鍩㈤崼鐔虹濞达絽鍟垮ú锕傚磻鐎ｎ喗鐓曟繛鎴烆焽閹界娀鏌熼婊冧槐妤犵偞鐗曡彁妞ゆ巻鍋撳┑鈥茬矙閺屽秹鏌ㄧ€ｎ亞浼岄梺鍝勬湰缁嬫垿鍩為幋锕€骞㈡俊銈咃梗缁辨繈姊绘担渚劸閻庢稈鏅犲畷婵嗏枎閹惧疇鎽曢梺缁樻煥閸氬宕戦敓鐘崇厽婵°倐鍋撻柣妤€妫濆鎼佹偐缂佹ê鈧灚绻涢崼婵堜虎闁哄闄勯妵鍕即閸℃鎼愰柣鎾偓鎰佺唵閻犺桨璀﹂悡顒佺箾鐏忔牗娅婇柡灞诲妼閳规垿宕卞Ο鐑橆仧濠电姰鍨奸～澶娒洪悢濂夋綎婵炲樊浜滅粻浼村箹鏉堝墽鎮奸柣锝呯仛娣囧﹪濡堕崶顬垽鏌熺拠褏纾跨紒顔碱儏椤撳ジ宕ㄩ鍛澑闂備礁澹婇崑鍛存嚌閻愵剛顩插Δ锝呭暞閸嬧剝绻涢崱妤冪妞ゅ浚浜炵槐鎺楀焵椤掑嫬鐒垫い鎺戝閳锋垶绻涢懠棰濆殭妤犵偞鐗犻弻娑欑節閸屾粈铏庡?")
        if tone_name == "concise_rescue":
            lines.append("婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽弫鎰板川閸屾粌鏋庨柍璇查叄楠炲棜顦虫い鏂垮缁辨捇宕掑▎鎺戝帯婵犳鍠楅幐鎶藉箖濡警娼╅悹杞扮秿閿曞倹鐓曢柡鍥ュ妼閺嬨倝鏌ｉ妶鍌氫壕闂傚倷绀佸﹢閬嶅磻閹捐绠氶悘鐐跺▏濞戙垺鍊烽柣銏㈡暩閿涙繃绻涙潏鍓ф偧闁哄拋鍋婂畷濂割敂閸喓鍘辨繝鐢靛Т閸熸壆绮婚悙纰樺亾濞堝灝鏋涙い顓犲厴楠炲啴濮€閵堝棙鍎梺闈╁瘜閸橀箖宕㈤鐐粹拻濞达絿顭堥ˉ蹇涙煟閹惧磭澧︾€规洘濞婇、姘跺焵椤掆偓閻ｅ嘲鈹戦崶褏绐為梺褰掑亰閸樻悂骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囶亞鐣垫鐐诧躬瀹曟﹢顢旈崱娆欑床缂傚倸鍊烽悞锕傛晝椤愶附鍤€閻犳亽鍔夐崑鎾斥枔閸喗鐏堝銈庡幘閸忔ê顕ｉ锕€绠涙い鎾跺仧缁愮偞绻濋悽闈浶㈤悗姘卞厴瀹曘儵宕ㄧ€涙ǚ鎷绘繛杈剧秬濞咃絿鏁☉娆嶄簻妞ゆ挾鍋熸晶鏇㈡煃鐠囪尙效鐎殿喗鎸虫慨鈧柍銉ュ帠閹撮攱淇婇悙顏勨偓鏇犳崲閹扮増鍋嬪┑鐘叉搐绾惧綊鏌ｉ姀鐘冲暈闁稿鍓濈换娑㈠幢濡ゅ啰顔囧銈呮禋娴滎亪骞冨Ο璺ㄧ杸闁挎繂鎳嶇花鐣岀磽娴ｄ粙鍝洪悽顖ょ節楠炲﹤顭ㄩ崼鐕佹濠电偞鍨惰摫闁硅櫕鐟╅弻锝嗘償閵忊晛鏅遍梺鍝ュУ閻╊垶銆佸鎰佹▌闂佺硶鏂傞崕鎻掝嚗閸曨垰绠涙い鎺戭槹缂嶅倿姊绘担铏瑰笡閽冮亶鏌ｅΔ浣瑰磳鐎规洘绻傞鍏煎緞婵烆澁绠撻弻娑㈠即閵娿儳浠╃紓渚囧亜缁夊綊寮诲☉姘勃闁硅鍔曢ˉ婵囩箾鐎电校闁挎碍銇勯鍕殻濠德ゅ煐閹棃鍨鹃懠顒傚煃闂傚倷绀侀幖顐﹀箠閹邦厽鍙忛柟缁㈠櫙缂嶆牠鐓崶銊﹀婵炲樊浜堕弫鍌炴煕閺囥劌澧紒浣藉煐娣囧﹪鎮欓鍕ㄥ亾閺嶎厼绠板Δ锝呭暙缁愭骞栫划瑙勵€嗛柡瀣⒒閳ь剙鍘滈崑鎾绘煕閺囥劌鍘撮柟鐤缁辨捇宕掑▎鎴濆濡炪値鍘煎ú锕傚疾閸洦鏁傞柛顐ゅ枔閸橆亪姊洪崜鎻掍簴闁糕晛瀚伴幃鐐烘倷椤戝彞绨婚梺鍝勬祩娴滅偟绮欓懡銈囩＜缂備焦顭囩粻鎾淬亜椤愶絿绠炴い銏☆殜閸┾偓妞ゆ巻鍋撻柣锝囨暬瀹曞崬鈽夊▎灞惧缂傚倸鍊烽悞锕佹懌濡炪們鍎卞Λ娆戞崲濞戙垹妞介柛鎰典簽琚﹂梻浣筋嚃閸垳娆㈠顒傛殾濠靛倻顭堝敮闂佹寧姊荤划顖炈夋繝鍐х箚闁绘劦浜滈埀顒佺墵瀹曟繈骞嬮敃鈧崹鍌炴煟閹寸伝顏嗘閻愮儤鐓曢柡鍥ュ妼楠炴鐥幆褋鍋㈤柟顔筋殜閺佹劖鎯旈垾鑼泿婵犵數鍋為幆宀勫窗濡ゅ懎桅闁告洦鍨伴～鍛存煃閳轰礁鏆欑痪鏉跨Т椤啴濡堕崱妯虹闂侀潧鐗忛…鍫ユ偩閻戣棄纭€闁绘劏鏅滈悗濠氭⒑鐟欏嫭鍎楅柛妯恒偢瀵煡顢橀姀鈾€鎷绘繛杈剧悼閻℃棃宕靛▎鎰閻庣數顭堥崢瀵糕偓娈垮櫘閸嬪﹪鐛弽銊﹀婵炴潙顑呮禍楣冩煥閺囩偛鈧悂鏌嬮崶顒佺厽闁哄倹瀵ч幆鍫ユ煃椤忓啫宓嗘慨濠傤煼瀹曟帒顫濋钘変壕闁绘垼濮ら崐鍧楁煥閺冨牊鏆滈柛瀣尵缁厼鈽夊Ο鍝勭婵°倧绠掑▔鏇㈡偪閳ь剙鈹戦悙鏉戠仸闁挎岸鏌ｆ惔顔煎籍闁诡喖鍢查…銊╁川椤撗勬瘔闂佹眹鍩勯崹鍏肩閻愬灚顫曢柣鎰惈閸愨偓濡炪倖鎸炬慨纾嬨亹閸曨垱鈷戦柟鑲╁仜閸旀﹢鏌涢弬璺ㄐч柛鈺傜洴楠炴帡寮崒婊愮床闂備焦濞婇弫顕€宕戦幘缁樼厱閻庯綆鍋呯亸鎵磼缂佹绠撻柍缁樻崌瀹曞綊顢欓悾灞兼喚闂傚倷鐒︾€笛兠哄澶婄柧闁绘灏欓弳锔界節婵犲倸鏆婃俊鎻掔墦閺屾洝绠涢弴鐐愩儵鏌ㄥ☉娆戞噰婵﹨娅ｇ槐鎺懳熼崫鍕垫綍闂備胶顭堢花娲磹濠靛鏄ユ繛鎴欏灩缁狅綁鏌ㄩ弮鍌涙珪闁告鏁哥槐鎾存媴閸撴彃鍓遍柣搴ｇ懗閸パ咁唹闂佹寧绻傚ú銊у婵傚憡鐓熸俊顖涘閻濐亞鈧娲栭惌鍌炲蓟閳ュ磭鏆嗛柍褜鍓熷畷浼村冀瑜忛弳锔芥叏濡炶浜鹃梺鐟扮－婵炩偓妞ゃ垺鐗犻、鏇㈩敆閸屾稑浠圭紓鍌欐祰妞村摜鏁垾鎰佸殨妞ゆ洍鍋撶€规洘甯掗～婵嬵敇閻橀亶鍋楅梻浣筋嚙鐎涒晠顢欓弽顓炵獥婵°倕鎳庣粻浼存煣韫囷絽浜濋柛娆忕箻閺屽秷顧侀柛鎾跺枛瀵顓兼径瀣弳濡炪倖鐗楅惌顔界珶閺囥垺鈷掑ù锝呮憸缁夋椽鏌￠埀顒勫础閻戝棙瀵岄梺鑺ッˇ钘夘焽閺嶃劎绠剧€瑰壊鍠曠花濂告煕鐎ｎ亜鈧潡鐛弽顓炵妞ゆ挾鍋為悘宥囩磽閸屾氨校妞ゃ劌锕ら～蹇涙惞閸︻厾鐓撻梺鍛婄墤閸撴繈寮幆褉鏀介柣鎰硾閻ㄦ椽鏌涢悩鏌ュ弰妞ゃ垺宀搁弫鎰緞婵犲嫷鍟囧┑鐐舵彧缁蹭粙骞楀鍫晣婵炲樊浜濋埛鎴犵磽娴ｅ顏呮叏婢舵劖鐓涘ù锝堫潐閸婃劖銇勯姀锛勬噰鐎殿喗鎸虫慨鈧柍閿亾闁归攱妞藉娲川婵犲嫧妲堥梺鎸庢穿缁犳捇鐛繝鍥х闁崇懓銇樼花濠氭⒑閹稿孩顥嗘い鏇嗗洦鍊堕柨鏇炲€归悡娆愩亜閺冣偓閺嬪鎳撻幐搴闁绘劘鎻懓鎸庛亜閵忥紕鎳囬柟顔煎⒔娴狅箓鎸婃径宀婂悑闂傚倸鍊搁崐鐑芥倿閿曞倸纾块柛鎰梿閻熼偊娼╅悹楦挎閿涙盯姊洪崷顓炲妺闁搞劎鍠栧鎼佸籍閳ь剟骞堥妸銉富閻犲洩寮撴竟鏇㈡⒒娴ｅ憡鎯堥柣顒€銈稿畷浼村冀椤撶偟鐣洪梺缁樺灱濡嫮鐥缁绘盯宕卞Δ鈧紞鏍磼鏉堛劌鐏存慨濠勭帛閹峰懐绮电€ｎ亝鐣伴梻浣告憸婵潧煤閻旈鏆﹂柨鐔哄Т缁狀噣鏌﹀Ο渚Ч婵″樊鍓熷娲川婵犲啫顦╅梺鎼炲妽婢瑰棛鍒掗崼銉ョ闁崇懓銇樼花濠氭椤愩垺澶勯柟鍛婃倐瀵娊鎮㈤崗鑲╁幍缂備礁顑嗛娆徫熼埀顒€鈹戦纭峰伐妞ゎ厼鍢查悾鐑藉箳閹搭厽鍍靛銈嗗灱濡嫭绂嶆ィ鍐╃厽闁硅揪绲借闂佹悶鍊曠€氫即寮诲☉銏╂晝闁挎繂妫涢ˇ銉х磽娴ｅ搫啸濠电偐鍋撻梺鍝勭灱閸犳牠骞冨▎鎿冩晢濞达絽鍚€閹寸兘姊绘担鑺ャ€冪紒鈧笟鈧、鏍幢濞戞锕傛煕閺囥劌鐏犵紒鐘差煼閺屾稑螖閸愩劋鎴锋繛瀵稿Ь閸嬫劗妲愰幒妤佸€锋い鎺嗗亾闁告柣鍊栭妵鍕敇閻樻彃骞嬮悗娈垮枛椤兘寮幇顓炵窞濠电姴瀚澶愭⒒娴ｄ警鐒鹃柡鍫墴閹虫繈鎮欓鍌ゆ祫濠殿喗銇涢崑鎾存叏婵犲懏顏犵紒杈ㄥ笒铻ｉ悹鍥ㄧ叀閻庤櫣绱撻崒娆愮グ妞ゆ泦鍥ㄥ亱闁圭偓鍓氶崵鏇炩攽閻樺磭顣查柡鍛倐閺岋絽螣閸喚姣㈠銈忚礋閸旀垵顫忓ú顏咁棃婵炴垼浜崝鎼佹⒑缁嬪灝鐦ㄩ柛锝忕到閻ｇ兘骞嬮敃鈧粻鑽ょ磽娴ｅ顏呯閾忓湱纾藉ù锝呭閸庢挻绻涙径瀣闁轰礁绉撮埥澶愬閳锯偓閹锋椽鏌ｉ悢鍝ユ噧閻庢凹鍓涚划鍫ュ礃椤忎礁浜鹃悷娆忓缁€瀣箾娴ｅ啿娲﹂崑鈺呮煕椤垵浜為柣鐔风秺閺屽秷顧侀柛鎾跺枎椤曪絿鎷犲ù瀣潔闂佸啿鐏堥弬渚€宕戦幘缁樻櫇闁稿本姘ㄩ鍝勨攽閻樼粯娑ф繛灞傚妽缁傚秹顢旈崟銊︽杸闂佺粯蓱閸撴岸宕箛娑欑厱闁绘ê纾晶顒併亜閵婏絽鍔︽鐐寸墬閹峰懘宕妷銉ョ闂傚倷鑳堕、濠囧箵椤忓棛涓嶉柟杈鹃檮閸嬪倿鏌ㄩ悢鍝勑ｉ柣鎾存礋閺屽秹鍩℃担鍛婃婵炲濯存俊鍥╂閹烘惟闁靛绲芥禒顔尖攽椤旂》鏀绘俊鐐扮矙楠炲﹪鏁撻悩鍙傃囨煕濞戝崬鏋熼柣锝庡墴濮婄粯鎷呯憴鍕哗闂佺瀵掗崹璺虹暦濠靛牅娌柛鎾楀本绁俊鐐€栭幐鍫曞垂濞差亜纾婚柍鈺佸暟缁♀偓婵犵數濮撮崐鎼侇敂椤忓牊鐓熼柟鎯у船閸旀粓鏌曢崶褍顏い銏℃礋婵偓闁靛繈鍩勯崬铏圭磽閸屾瑦绁板鏉戞憸閺侇噣骞掗弴鐘辫埅闂備浇宕垫慨鏉懨洪妶鍛傜喐绻濋崶褏鍔﹀銈嗗笂閻掞箑鐣风仦鐐弿濠电姴鍟妵婵堚偓瑙勬磸閸斿秶鎹㈠┑瀣闁靛瀵屽鏃堟⒒閸屾瑧鍔嶉悗绗涘厾楦跨疀濞戞锛熼梻鍌氱墛缁嬫捇寮抽敃鍌涚厸闁搞儯鍎遍悘鈺冪磼閻樺樊鐓奸柡宀嬬節瀹曟帒螣閸濆嫬顫氶梻浣告惈閸婄敻宕戦幘缁樷拻闁稿本鐟ㄩ崗宀€绱掗鍛仸鐎规洘绻傞埢搴ㄥ箻閳ь剟鎮滈挊澶岋紲闂佺粯鍔栬ぐ鍐箚閻愮儤鐓熼幖鎼灣缁夌敻鏌涢幘瀵搞€掑瑙勬礃缁轰粙宕ㄦ繝鍕箺婵犵妲呴崹浼村箹椤愶箑姹查梺顒€绉甸悡鐔肩叓閸ャ劍鈷愰悘蹇ョ畵閺岋紕浠﹂悾灞澭冣攽閿涘嫬鍘存い銏＄☉椤劑宕ㄩ绛嬪晫闂備浇顕у锕傦綖婢跺⊕鍝勵潨閳ь剙鐣烽弴鐔洪檮闁哄妫楀ú顓€佸璺虹劦妞ゆ帒瀚拑鐔兼煥濞戞ê顏ら柛瀣崌閺佹劖鎯斿┑瀣粣闂備礁鎲￠悷銉р偓姘嵆瀵鍨惧畷鍥ㄦ畷闂侀€炲苯澧寸€规洑鍗冲浠嬵敇閻樿尙銈﹂梻浣虹《閸撴繈宕欓悷鎷旓絾銈ｉ崘鈺佲偓鍨箾閹寸偟鎳呯紒鐘虫崌閺屽秶鎲撮崟顐や紝闂佽鍠楅悷鈺佺暦閿濆棗绶為柛鈩冾焽娴滅偤姊婚崒娆戭槮闁硅绻濋幃鐑藉Ψ閳轰胶鏌堥梺鍦檸閸犳牜绮婚弽顬″綊宕楅崗鐓庡壒闂佽桨绀侀澶愬蓟瀹ュ牜妾ㄩ梺鍛婃尵閸犳牠骞冩导鎼晪闁逞屽墮閻ｇ兘宕奸弴銊︽櫌婵犮垼娉涢鍡椻枍瀹ュ鈷掑ù锝堟鐢盯鏌＄仦璇插鐎规洘鐓″畷锝嗗緞婢跺瞼鐣鹃梻浣筋潐閸庡吋鎱ㄩ妶澶婄厱闁圭儤鍤氳ぐ鎺撴櫜闁搞儯鍔屽▓灞筋渻閵堝棙绀冪紒顔兼捣濡叉劙骞掗弮鈧€氭岸鏌熺紒妯哄潑闁稿鎹囧畷褰掝敊閻愵剚顔曢梻浣哥秺閸嬪﹪宕归浣侯洸鐟滅増甯楅悡娆撴煟閹寸伝顏堟倶閿曞倹鐓熼幖鎼枛婢у瓨鎱ㄦ繝鍌涙儓閺佸牓鏌涢妷鎴濇噸閹綁姊绘担渚敯妞ゆ洘绮庨幑銏犫攽鐎ｎ亝妲┑鐐村灟閸ㄥ湱绮婚幎鑺ョ厵闁绘劘妫勬俊鑲╃磽瀹ュ拑韬€殿噮鍋婇獮鍥级閸ф鏁规俊鐐€栭崝褏寰婄捄銊х煋闁绘垼濮ら埛鎺懨归敐鍥╂憘闁搞倖鐟х槐鎺旂磼濡洘鍨圭划瀣吋婢跺﹪鍞堕梺鍝勬川閸嬬娀骞楅弴銏♀拺閻犳亽鍔岄弸鏂库攽椤旇姤缍戞い鏂跨箰閳规垿宕堕妷銈囩泿闂備礁鎼崯顐﹀磹閸涘﹦顩插Δ锝呭暞閻撴洟鏌熼悜妯诲暗婵炲弶鎸抽弻鐔碱敊缁涘鐣奸梺鐟板级閹稿啿鐣烽悢纰辨晢闁逞屽墴钘濋柍鍝勬噺閳锋垿鏌熼懖鈺佷粶濠碘€炽偢閺岋綁寮介銏犱粯闂佷紮绲介崲鑼弲濡炪倕绻愰幊蹇撯枍閵忋倖鈷戠紓浣癸供閻掗箖鎮樿箛鏃傛噰閽樻繈鏌曟繛鐐珕闁抽攱鍨块弻娑㈠箛椤掆偓缁狙囨煙椤栨氨澧﹂柡灞诲姂瀵潙螣閸濆嫬袘缂傚倷娴囨禍顒勫磻濞戞粎浜欓梻浣告啞娓氭宕伴幒妤€绠紓浣诡焽缁犻箖寮堕崼婵嗏挃闁告帊鍗抽弻鐔烘嫚瑜忕弧鈧Δ鐘靛仜濡繂鐣锋總绋款潊闁靛浚婢佺槐鏌ユ⒑鐠囨彃鍤辩紒鍙夋そ瀵彃鈹戦崼銏㈠箵闂佸搫鍟崐鐢稿磻閹捐埖鍠嗛柛鏇ㄥ墰閿涙﹢姊洪幖鐐插婵炲拑绲块崚鎺斺偓锝庡枛缁犳娊鏌￠崒姘儓濞存粓绠栭弻銊モ攽閸℃侗鈧霉濠婂嫮鐭婇棁澶嬬節婵犲倸顏存繛鍫熺矋閹便劍绻濋崘鈹夸虎濠碘槅鍋勯崯顐﹀煡婢跺缍囨い顓熷灍閸嬫捇宕卞Ο鑲╃槇缂佸墽澧楄彜闁稿鎹囬幖褰掝敃閵忋垻宕虹紓鍌氬€风欢锟犲窗濮樺崬鍨濇い鏍仜鍥撮梺鎸庣箓椤︻垳绮堥崘顔界厓闁告繂瀚弳娆愵殽閻愯尙效婵﹨娅ｉ幏鐘诲矗婢跺闂梻浣芥〃閻掞箓骞冮崒鐐茬伋闁挎洖鍊搁柋鍥煏婢跺牆鍔ゆい锔诲弮濮婄粯绗熼崶褍顫╃紓浣割槺閺佸骞冮敓鐘冲亜闁稿繗鍋愰崢鐢告⒑閸涘﹦绠撻悗姘煎枦閸婃挳姊绘担瑙勩仧闁告ü绮欓幃鐑藉煛閸涱叀鎽曢梺鐐藉劚绾绢參寮抽崱娑欏€甸柨婵嗛婢ф壆鎮敂鎴掔箚闁靛牆娲ゅ暩闂佺顑囬崑鐔煎极椤曗偓閸ㄩ箖骞囨担鍛婎吙婵＄偑鍊栫敮鎺斺偓姘煎墴瀹曞綊宕掑☉鏍︾盎闂佸搫鍟ú銈嗙鐟欏嫨浜滈柟鎯х摠閵囨繃鎱ㄦ繝鍌ょ吋鐎规洘甯掗埢搴ㄥ箣椤撶啘婊堟⒒娴ｅ憡璐￠柍宄扮墦瀹曟垶绻濋崶褏鐤囬梺缁樻⒒閳峰牓寮鍡欑瘈濠电姴鍊归崳浠嬫煟閹炬剚鍎旀慨濠呮缁辨帒螣閾忛€涚礉闂備礁婀遍悺鏃€绂嶉鍛箚闁归棿鐒﹂弲婊堟煕閹炬瀚▓鐐烘⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栨稒娅犻悗鐢电《閸嬫挸鈻撻崹顔界仌濡炪倖娉﹂崶褏鍙€婵犮垼鍩栭崝鏇綖閸涘瓨鐓熸俊顖涙た閸熷繘鏌涢悢濂夊剶婵﹨娅ｉ幏鐘诲蓟閵夈儱鍙婃繝鐢靛仒閸栫娀宕惰閻ゅ懘姊虹捄銊ユ灁濠殿喗鎸冲濠氼敍濮ｎ厼缍婇幃鈩冩償閿濆棙鍠栭梻浣侯焾閿曘倝鎮樺杈ㄥ床婵炴垯鍨归柋鍥ㄧ節闂堟稓澧旈柧蹇撻叄濮婃椽宕崟闈涘壄闂佺锕ョ换鍫濐嚕婵犳艾鐒洪柛鎰ㄦ櫅椤庢捇姊洪崨濠冨磩閻忓繑鐟╁畷銉р偓锝庡枟閳锋垿姊婚崼鐔衡姇妞ゃ儲鐟х槐鎺楀焵椤掍焦濯撮柣锝呭缁ㄧ兘姊婚崒娆戭槮闁规祴鍓濈粭鐔肺旈崨顓炲亶婵°倧绲介崯顐ょ矆婢舵劖鐓ラ柡鍥殔娴滄儳顪冮妶搴濈盎闁哥喎鐡ㄦ穱濠囧醇閺囩偛鑰垮┑掳鍊愰崑鎾寸箾閸忕厧鐏存慨濠呮缁瑥鈻庨幆褍澹夐梻浣筋潐閹倻绮婚弽顓炴槬闁逞屽墯閵囧嫰骞掗幋婵囩亾濠电偛鍚嬮崝娆撳蓟閻旇櫣鐭欓柟绋垮閸犳劙姊洪柅鐐茶嫰婢ь垳鐥弶璺ㄐ㈡い顓炵仢椤粓鍩€椤掑嫭鏅查柣鎰閻も偓闂佸搫鍊介褎绂嶆导瀛樼厽闁绘柨鐖煎鐑芥煕婵犲啯灏弫鍫熶繆閵堝懏鍣洪柍閿嬪灴閺屾盯鏁傜拠鎻掔闂佸憡鏌ㄩ澶愬蓟閻斿搫鏋堥柛妤冨仒缁ㄨ棄鈹戦垾鍐茬骇闁告梹鐟╅獮鍐╃鐎ｎ偄浠洪梺姹囧灮椤ｎ喚妲愰崘娴嬫斀闁绘劘鍩栬ぐ褏绱掗崣澶婄闁靛洦鍔欏畷姗€鍩￠崘鐐敜闂備胶绮崝锕傚礈濞戞氨涓嶅Δ锝呭暞閻撴瑩鏌ｉ幇闈涘缂傚秵鍨块弻锝夊箳閹寸姷楔闂佸搫鏈粙鎾诲焵椤掑﹦绉甸柛瀣噽娴滄悂鎮介崨濠勫帗閻熸粍绮撳畷婊冣攽鐎ｅ墎绋忔繝銏ｆ硾閳洖煤椤忓嫮鍘搁梺鍛婂姀閺呮稒鎯旀繝鍌楁斀闁绘绮☉褎銇勯幋婵囨悙闁伙絽鐏氱粭鐔煎焵椤掑嫮宓侀柡宥庣仈鎼搭煈鏁嗛柍褜鍓氭穱濠冪鐎ｎ偆鍘遍梺闈涚墕閹虫劖鏅ラ梻浣告惈閺堫剙煤濡偐鍗氶柣鏃傗拡閺佸秵鎱ㄥ鍡楀婵炲牜鍘剧槐鎾存媴閸濆嫅銉ヮ熆瑜庨〃鍫ュ箲閵忕姭鏀介悗锝庡亜娴犳椽姊婚崒姘卞闁告巻鍋撻梺缁樺姉閸庛倝鎮￠弴銏＄厪濠电倯鍐ㄦ殭濞寸姵锕㈠鍝勭暦閸モ晛绗￠梺鍝勮閸旀垿宕洪妷锕€绶為柟閭﹀墻濞煎﹪姊洪崘鍙夋儓闁稿﹦鎳撻埢宥夊醇閵夛腹鎷绘繛杈剧到閹诧繝宕悙鐢电＜閻庯綆鍋勯悘鎾煙椤旇姤銇濆┑鈩冩倐閸┾剝鎷呴悮瀵镐覆闂傚倷绀佹竟濠囧磻閸涱劶鍝勵潨閳ь剟骞冮敓鐘茬妞ゆ梻鏅崢鍗炩攽閻樼粯娑ф俊顐ｎ殜椤㈡棃鍩￠崨顔惧帗閻熸粍绮撳畷婊冣枎閹寸姷顦繝鐢靛Т閸婂寮抽敃鍌涚叆婵犻潧妫涙晶銏ゆ煟閵堝倸浜惧┑鐘垫暩閸嬬偤宕归崼鏇熷仭鐟滄柨鐣烽敐澶婂耿婵＄偟绮弬鈧梻浣虹帛椤洨鍒掗姘ｆ鐟滃孩绌辨繝鍥舵晝闁挎繂娲﹂崳浼存倵鐟欏嫭绀冨┑鐐诧躬楠炴劖绻濋崘銊х獮濠碘槅鍨抽崢褔寮幖浣圭厽闁绘柨鎽滈惌瀣磼鐠囨彃顏柛鎺撳笚缁绘繂顫濋鍌ゅ晪闂佽崵濮村ú鈺冧焊椤忓牆绠洪柡鍥ュ灪閳锋垿鏌熺粙鎸庢崳闁宠棄顦甸幃妤€顫濋梻瀵哥泿闂佸疇顔婄划娆撱€侀弮鍫濋唶闁绘柨鎼獮妤呮⒒娓氣偓閳ь剚绋戝畵鍡樼箾娴ｅ啿瀚▍鐘绘煟濡も偓閻楀嫭绂嶅鍫熺叆闁哄倽娉曟禒銏⑩偓瑙勬尭濡繈寮婚悢纰辨晩缂佹稑顑嗛悾濂告⒑閻熸澘绾ч柟绋垮暱閻ｇ兘鎮㈢喊杈ㄦ櫌闂佺琚崐鏍ㄦ櫏婵犵數濮烽弫鎼佸磻濞戙垺鍋ら柕濞у啫鐏婇棅顐㈡处閹告挳寮搁弽銊х闁瑰瓨鐟ラ悞娲煛娴ｅ壊鍎旈柡灞诲妼閳规垿宕遍埡鍌傦妇绱撴担鍝勑ョ紒顕呭灦婵＄敻宕熼姘辩潉闂佹悶鍎洪悡鍫澪涢崟顒傜閻庢稒顭囬惌濠勭磽瀹ュ拑宸ユい顐㈢箰鐓ゆい蹇撳瀹撳秴顪冮妶鍡樺暗濠殿喖顕划顓㈡晸閻樺磭鍘介梺闈涚箚閺呮盯鎮樺▎鎾寸厸闁告侗鍨伴埢鍫燁殽閻愭彃鏆欓摶鏍煕濞戝崬骞樺Δ鐘叉喘濮婃椽鎮烽幍顔芥喖濠殿喖锕ょ紞濠傤嚕椤掑嫬鐒垫い鎺戝閳锋帒霉閿濆牊顏犻悽顖涚洴閺屻劌顫濋懜鐢靛幗闂婎偄娲﹂弻銊╁传閾忓厜鍋撳▓鍨灍濠电偛锕畷娲晸閻樻彃绐涘銈嗘⒐閸庢娊鐛崼銉︹拺閻犲洦褰冮崵杈╃磽瀹ュ懏顥㈢€规洘绮岄埢搴ょ疀閺冣偓閻﹀骸鈹戦悩鍨毄闁稿鐩幃娲Ω瑜嶉崹婵堚偓骞垮劚椤︻垳绮婚弽顓熺厱鐎光偓閳ь剟宕戦幋锕€鐒垫い鎴ｆ硶缁愭梻鈧鍣崳锝呯暦閻撳簶鏀介柛顐亝鏁堥梻鍌氬€风欢姘焽瑜旈垾锕傤敇閻斿墎绠氶梺鎼炲劘閸斿酣銆呴崣澶岀闁糕剝蓱鐏忎即鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡樺櫤闁哥喓鍋ら弻鐔碱敍濮樺崬顤€缂備胶绮粙鎾寸閿曞倸纾兼慨姗嗗墻閻庢挳姊绘笟鈧埀顒佺〒閳规帡鏌涢弮鈧崹鍧楁偘椤旂⒈娼ㄩ柍褜鍓熼妴浣糕枎閹炬潙浜楅柟鑹版彧缁叉椽宕戦幘娲绘晣闁绘劏鏅滈弬鈧梻浣虹帛椤洨鍒掗姘ｆ鐟滃海鎹㈠☉姘勃闁稿本鑹鹃‖瀣磽娓氬洤鏋ょ紒顕呭灦婵″爼鏁愭径濠勵槰闂佸啿鎼崯顐︾嵁閸儲鈷掑ù锝堫潐閻忛亶鏌￠崨顔炬创鐎规洘婢橀～婵嬵敄閼恒儳浜栨繝纰樻閸ㄧ敻宕戦幇顔碱棜濠靛倸鎲￠悡鐔镐繆椤栨碍鎯堥柡鍡涗憾閺屽秶绱掑Ο鑽ゎ槹闂佸搫澶囬埀顒€纾弳鍡涙倵閿濆骸澧伴柣锕€鐗撻幃妤冩喆閸曨剛顦版繛瀛樼矊閻栧ジ濡存担鍓叉建闁逞屽墴楠炲啴鍩￠崨顓炵€銈嗗姧缂嶅棝宕畝鍕拻闁稿本鑹鹃埀顒勵棑缁牊绗熼埀顒勭嵁閺嶎収鏁冮柨鏇楀亾閻庢艾顦伴妵鍕箳閹存繍浠鹃梺绋块鐎涒晠濡甸崟顖氬唨闁靛ě鈧Λ鈺冪磽娴ｇ瓔鍤欐俊顐ｇ箞瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘搁梺鍛婁緱閸犳岸宕ｉ埀顒勬⒑閸濆嫭婀扮紒瀣灴閸┿儲寰勯幇顒傤攨闂佺粯鍔栬ぐ鍐敆濠婂牊鈷掑ù锝囩摂閸ゆ瑦绻涚€电鍘寸€规洘顨呰灒濞撴凹鍨辩紞搴ｇ磽閸屾瑧鍔嶉拑鍗炩攽椤栨稒灏﹂柡灞剧☉閳藉顫滈崼鐔告毎闂備胶顭堢€涒晠骞愰幖浣哥厴闁硅揪绠戦悡锟犳煕閳╁啨浠︾紒銊ㄥ亹缁辨挻鎷呴崜鎻掑壉闁汇埄鍨界换婵嬫偘椤曗偓瀹曞ジ濡烽妷搴樻櫊閺屽秹宕崟顐熷亾閸涘﹦顩锋繛宸簼閳锋垿鏌涢幘鐟扮毢闁告ɑ鐩弻娑氣偓锝庝簻椤忣亪鏌熼娑欌拹缂佺粯绻堝畷鎺懳旀担瑙勬緫闂傚倷鑳剁划顖炲礉閺嵮岀劷婵炲棙鎸婚崐鍫曟煟閺傚灝鎮戦柣鎾存礋閺屾洘绻涢崹顔煎闁荤姵鍔х槐鏇犳閹烘鏁婄痪鎷屼含閸氬姊烘潪鎵妽闁告梹鐗曢銉╁礋椤撴稑浜鹃柨婵嗛婢ь喗顨ラ悙鎼疁婵﹦绮幏鍛村传閵夘灝銊╂⒑缁嬫鍎忛柨鏇ㄤ簻閻ｇ兘濮€閵堝棗浠奸悗鍏夊亾闁逞屽墰缁牊绻濋崶銊у幍闁哄鐗撶粻鏍ь瀶椤曗偓閺岋綁骞樼捄鐑樼亪闂佸搫鏈ú妯兼崲濠靛﹦鐤€闁哄洨濮靛▓鎼佹⒒娴ｇ瓔鍤欑紒缁樺姍閹椽濡搁埡浣虹杽闂侀潧顭俊鍥╁姬閳ь剟姊洪崨濠佺繁闁革綆鍠楃粋鎺楀煛閸愵亞锛濇繛鎾磋壘濞层倝寮搁悢鍏肩厽闁绘梹娼欓崝锕傛煕閳瑰灝鐏柟顖涙婵℃悂濡疯閺嗕即鏌ｉ悢鍝ョ煀缂佸鏁哥划鈺呮偄缁嬭法绐為梺褰掑亰閸樻悂骞忕紒妯肩閺夊牆澧介崚浼存煙鐠囇呯？闁瑰嘲缍婇崺鍕礃閿旇法鐩庢俊鐐€栭幐楣冨磻閻斿憡娅犻柨鏇炲€归悡鍐煏婢舵ê鐏ｉ柣锝囨暬閺岀喖顢欓悾宀€鐓夐梺璇″枛婢ц姤绂掗敃鍌涘仼閻忕偠顕ф禍浼存⒒閸屾艾鈧绮堟担鍦彾濠电姴娲ょ壕璇层€掑锝呬壕閻庤娲樺ú妯侯焽韫囨稑惟闁靛鍎遍～濠囨⒒閸屾艾鈧悂宕愭搴㈩偨婵﹩鍓﹂悞鐣屾喐閺冨洦顥ゆ俊鐐€栭幐鍫曞垂瑜版帒鍨傞柛灞剧〒缁犲墽鈧懓澹婇崰鏇犺姳缂佹ü绻嗘い鎰剁秶閼板潡鏌＄仦鐣屝ユい褌绶氶弻娑㈠箻鐠虹儤鐎诲銈庡亜缁绘帞妲愰幒鎳崇喓鎷犲顔瑰亾閹剧粯鈷戦柛娑橈功閳藉鏌ㄩ弴妯衡偓婵嗩嚕閹惰棄閱囨繝闈涘暞閺傗偓闂備胶绮崝娆撀烽崒鐐插惞閻庯綆鍓涚壕濂告煟濡寧鐝悘蹇ｅ弮閺岋綁鏁愰崶褍骞嬪Δ鐘靛仜椤戝寮崘顔肩劦妞ゆ帒鍊婚惌鍡涙倵閿濆骸浜栧ù婊勭矒閺岀喖宕崟顓夈倖銇勯敂鐓庮洭闁逞屽墯椤旀牠宕伴弽褜鐒介柨鐔哄Т缁犳牗淇婇妶鍛櫣缂佲偓閸屾凹鐔嗛悹铏瑰皑濮婃顭跨憴鍕婵﹦绮幏鍛村川婵犲倹娈樻繝鐢靛仩椤曟粎绮婚幘宕囨殾婵°倐鍋撴い顐ｇ矒閸┾偓妞ゆ帒瀚畵?")
        elif verbosity_bias == "expanded":
            lines.append("缂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈囩磽瀹ュ拑韬€殿喖顭烽弫鎰緞婵犲嫷鍚呴梻浣瑰缁诲倿骞夊☉銏犵缂備焦顭囬崢杈ㄧ節閻㈤潧孝闁稿﹤缍婂畷鎴﹀Ψ閳哄倻鍘搁柣蹇曞仩椤曆勬叏閸屾壕鍋撳▓鍨珮闁告挾鍠庨悾鐤亹閹烘繃鏅╅柣鐔哥懃鐎氼剟鎯侀柆宥嗏拻闁稿本鐟ч崝宥嗕繆閻愬弶鍋ョ€规洏鍨虹粋鎺斺偓锝庡亜娴狀參姊洪崘鍙夋儓闁瑰啿閰ｉ幏鎴︽偄閸忚偐鍘介梺鍝勫€藉▔鏇炩枔闁秵鐓涢悗锝庝邯閸欏嫭鎱ㄦ繝浣虹煓鐎规洖鐖奸、妤佸緞鐎ｎ偅鐝ㄩ梺鑽ゅ枑缁瞼绮旈崼鏇炵煑闁告侗鍙庡〒濠氭煏閸繃顥為柟顖氬缁绘盯鎮℃惔銏犱淮闂佺硶鏂侀崑鎾愁渻閵堝棗鐏辨繛澶嬫礋钘濋柨鏇炲€归悡鍐偣閸ャ劎鍙€闁告瑥瀚〃銉╂倷閻ゆ浜幃楣冩倻閽樺鍊為梺鐓庢啞閺咁偊濡舵径瀣ф嫼闂佺厧顫曢崐鏇㈠几閹寸姷纾兼い鏃囧亹閻忛亶鏌熼獮鍨仼閾伙綁鏌熺粙鍨槰婵☆偁鍔岄埞鎴︽晬閸曨偂鏉梺绋匡攻閻楃娀骞冭铻栭柛娑卞幗濡差剟姊洪崨濠傚Е闁哥姵鐗滅槐鎺楀煛閸涱喚鍘鹃梺璇″幗鐢帡宕濆Ο濂界懓顭ㄩ崟顓犵厜闂佸搫鐭夌换婵嗙暦閹烘垟妲堥柛妤冨仜婵″吋绻濋悽闈涗哗闁稿鍔欏畷鐗堟償閵婏妇鐣抽梻鍌欒兌缁垶鏁嬬紒鍓ц檸閸欏啴骞嗗畝鍕婵°倓鑳堕崢鎼佹煟韫囨洖浠滃褌绮欐俊鎾箳濡や胶鍘撻悷婊勭矒瀹曟粓濡歌缁€濠囨煕閳╁啰鈽夌痪鎯ь煼閺屾稑鈽夐崡鐐典户闂佺粯甯掗敃顏堝蓟閿濆憘鏃堝焵椤掑嫭鍋嬮柛鏇ㄥ墰椤╁弶绻濇繝鍌滃闁绘挸绻愰埞鎴︽偐閼碱剛顔婇梺鍛婂笂閸楁娊寮诲☉銏犵睄闁规儳澧庨弳銈夋⒑閸濆嫮鐏遍柛鐘崇墵閵嗕礁鈻庨幘鏉戜患闁诲繒鍋為崕鍐测枍濮橆厺绻嗛柕鍫濇搐鍟搁梺绋款儑閸嬨倝鐛幋锕€鐐婃い鎺戝€哥粊锕傛⒑閸︻厼鍔嬮柛銊у枛瀵劍绂掔€ｎ偆鍘遍梺鏂ユ櫅閸熴劍绂嶅Δ鍛厪濠电倯鍐╁櫧闁挎稒绻堝铏圭矙閹稿孩鎷遍梺鐓庣秺缁犳牠宕洪埀顒併亜閹烘垵鈧悂宕㈤幘顔界厵闁惧浚鍋掑▓婊呪偓瑙勬礃缁秹骞忛崨顖滅煓閻犳亽鍔嬮崰濠傗攽閿涘嫬浜奸柛濠冪墵閹兾旈崘銊ョ亰閻庡箍鍎遍幊鎰板汲閿曞倹鐓涢悘鐐额嚙閸旀粓鏌ｉ幘瀛樼闁靛洤瀚伴獮鍥礈娴ｇ懓浠圭紓鍌欒兌婵敻鏁冮姀銈呰摕闁跨喓濮撮獮銏°亜閹捐泛啸闁哄棎鍊濆娲传閸曨剚鎷卞┑鐐插级椤洭骞戦姀鐘闁靛繆鈧枼鍋撻柨瀣ㄤ簻闁瑰搫绉烽崗宀€鎲搁幍顔兼灈婵﹦绮幏鍛存嚍閵夛絺鍋撻崘顏嗙＜闁逞屽墯閹峰懘鎼归崷顓犲帬闂備焦鐪归崹褰掓倶濮橆剛鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺娲诲墮閵堢鐣烽弴銏犵疀闁哄娉曢崝锕€顪冮妶鍡楃瑐缂佸灈鈧枼鏋旀繝濠傜墛閻撴稓鈧厜鍋撻悗锝庡墰閻﹀牓鎮楃憴鍕濞存粠浜滈悾宄邦潨閳ь剟銆侀弮鍫濈獥闁冲搫鍊搁悘鈺冪磼鏉堛劍灏伴柟宄版嚇閹煎綊鎮烽幍顕呭仹缂傚倸鍊峰ù鍥敋瑜旈幃褔骞橀懡銈呯ウ闂佸憡鍔忛弲婵嬨€呴悜鑺ュ€甸柨婵嗛娴滆姤淇婇銏犳殭闁宠鍨块幃娆撳级閹寸姳妗撴俊鐐€戦崝灞轿涘┑鍡欐殾闁绘梻鍘х粈鍐┿亜閺冨泦鎺楀箯缂佹绠鹃弶鍫濆⒔缁夘剚銇勯銏╂█鐎规洘鍨块幃鈺冪磼濡厧骞堥梻浣告惈閸婅棄鈻旈弴銏″€块柟闂寸劍閻撴瑦銇勯弬鎸庢儓闁告梹绮庣槐鎺撴姜閹殿喚鐓撻悗瑙勬处閸嬪﹥淇婇悜钘壩ㄧ憸瀣磻婵犲洦鈷掗柛灞剧懅椤︼附绻濋埀顒佹綇閵婏附鐝峰┑掳鍊愰崑鎾淬亜椤撶偟浠㈤摶锝夋煠濞村娅冪紒妤€顦辩槐鎾诲磼濞嗘垵濡介柤鍨﹀厾鐟邦煥閸曨厾鐓夐梺鍝勭焿缁绘繂鐣峰鈧俊鎼佹晜閼恒儱鈧嘲鈹戦悙鑼憼缂侇喖鐬肩槐鐐寸節閸パ嗘憰闂侀潧顭堥崕顔嘉ｉ崼鐔虹闁糕剝锚閻忥箓鏌涢幒鎾垛槈闁宠鍨块、娆戞兜闁垮鏆版繝纰夌磿閸嬫鍒掑▎鎾跺祦闁告劦鍠楅崐濠氭煢濡警妲哄Δ鐘叉喘閺岀喖鎮℃惔锝嗘喖闂佽鐡曞畷鐢稿焵椤掆偓閻忔岸鎮у鍛潟闁规崘顕х壕鍏肩箾閸℃ê鐏辩紒鎰殜濮婃椽妫冮埡鍐ｉ梺闈╃秶缁蹭粙鎮鹃悜钘夋嵍妞ゆ挾鍠庣壕顖炴⒑閹呯妞ゎ偄顦埢鎾淬偅閸愨斁鎷洪梺闈╁瘜閸樺ジ銆傞崗鑲╃瘈闁靛繆妲勯懓鍧楁煛鐏炵瓔鍎旂€规洖鐖奸、妤佹媴閸濆嫬绠伴梻鍌欑劍閹爼宕曢鈧鎻掆槈濡吋鎳冮梻浣藉吹閸犳劗鍒掑鍜佺唵婵☆垰鐨烽崑鎾愁潩椤撶喓鍑″銈庡亜缁绘劗鍙呭銈呯箰鐎氼噣顢欓幇鐗堚拺缂備焦锚婵牏鎲搁弶鍨殲闁逛究鍔岄悾婵嬪礋椤戣姤瀚奸梻浣告啞缁嬫垿鏁冮妷鈺傚亗闁靛／鍛紲婵犮垼娉涙鎼佹偂閹邦喚纾奸柛灞炬皑鏁堝Δ鐘靛仦閻楁骞忛崨瀛樺仭濡鑳剁槐锕傛⒒閸屾瑧鍔嶉柣顏勭秺瀹曡绻濆顒佺€梺褰掓？閻掞箓寮查浣虹瘈濠电姴鍊绘晶娑㈡煃闁垮鐏╃紒杈ㄦ尰閹峰懘鐛惔鎾充壕闁绘劕鎼粻锝夋煥濠靛棗鏆曟慨瑙勵殜濮婃椽宕ㄦ繝鍌毿曟繛瀛樼矌閸嬫稖鐏嬪銈嗙墬缁秹宕伴幇鐗堢厸闁告劑鍔庢晶鏇㈡煢閸愵亜鏋涢柡宀嬬節瀹曞爼濡烽妷褌鎮ｉ梻浣虹帛閸旀洟鏁冮敃鍌氱疅缂佸顑欓崥瀣熆閼哥灙鎴﹀疾濠婂喚娓婚柕鍫濇鐏忕敻鏌涢敐鍐ㄥ姎闁崇粯鎸荤粋鎺斺偓锝庡亞閸樹粙姊鸿ぐ鎺戜喊闁告鏅槐鐐哄箣閻愮數顔曢梺鍦拡閸樺ジ寮搁妶澶嬬厓鐟滄粓宕滃棰濇晩闁哄稁鍘奸梻顖涖亜閺囨浜鹃悗瑙勬礃缁矂锝炲┑瀣垫晢濠㈣泛锕ラ鍌炴⒒娴ｅ憡鍟炴繛璇х畵瀹曞綊寮跺▎鎯ф櫊濠电娀娼уΛ宀勫绩娴犲鐓熸俊顖濐嚙缁茬粯銇勯幒瀣伄缂佽鲸鎸搁濂稿幢閳哄倻鏉规繝娈垮枛閿曘倝鈥﹀畡鎵殾闁圭儤鍩堝鈺傘亜閹达絾顥夊ù婊堢畺閺岋綁骞嬮敐鍛呮捇鏌涢妶鍛伃闁哄本鐩、鏇㈡晲閸℃瑯妲紓鍌欒兌婵攱绻涢埀顒勬煛瀹€鈧崰鏍嵁閹达箑绠涢梻鍫熺⊕椤斿嫰姊洪悷鏉挎倯婵炲吋鐟╅弫鍐敂閸繆鎽曢梺鎸庣☉鐎氼亜鈻介鍫熷仯闁搞儯鍔岀徊璇测攽椤斿ジ鍙勬慨濠傛惈鏁堥柛銉戔偓閸嬫捇濡舵径濠囨７闂佹寧绻傞ˇ顖炴嫅閻斿吋鐓熼柡鍐ㄦ处椤忕姷鐥幆褋鍋㈤柡灞炬礉缁犳盯寮撮悙鎰剁秮閺岋綀绠涢幘璺衡叡缂備浇椴搁幐濠氬箯閸涙潙浼犻柛鏇熷煀缁插墽鎹㈠┑瀣潊闁宠棄鎳撻埀顒€娼￠弻娑㈠煛閸愩劋妲愬Δ鐘靛仜椤戝寮崒鐐村癄濠㈣泛顦伴惈蹇涙⒒閸屾瑧顦︽繝鈧潏鈺佸灊妞ゆ牗绮嶉弳婊勪繆閵堝倸浜鹃梺宕囩帛閹瑰洭銆佸鈧幃鈺呮偨绾板闂繝鐢靛仩閹活亞寰婇崸妞烩偓锕傚醇閵夛絺鍋撻崒鐐茬闁兼亽鍎抽崢閬嶆煟鎼搭垳绁烽柛鏂跨焸閸┾偓妞ゆ帊鑳剁粻鐐烘煟濞戝崬娅嶇€规洘锕㈡俊鍛婃償閵忊槅妫冮悗瑙勬磸閸旀垿銆佸▎鎾村殟闁靛／鍐槮闂傚倸鍊风粈浣革耿闁秴鍌ㄧ憸鏃堝箖濞差亜惟鐟滃骸鐣烽弻銉︾厱闁哄洢鍔岄悘锟犳煕鎼达繝鍙勬鐐寸墪鑿愭い鎺嗗亾濠碘€茬矙閺屽秹鏌ㄧ€ｎ亞浼岄梺鍝勮閸婃牠骞堥妸鈺佺疀妞ゆ垼妫勬禍楣冩煛閸ャ儱鐏╅柛鎴犲█楠炴牕菐椤掆偓婵′粙鏌嶉柨瀣伌闁诡喕绮欓、娑㈡晲閸涱喚浜鹃梻浣告啞鐢偞鏅跺Δ鍛﹂柛鏇ㄥ灱閺佸啴鏌曡箛瀣伄妞ゆ柨锕︾槐鎾存媴娴犲鎽甸柣銏╁灡鐢喖鎮橀幒妤佺厽闁绘ê寮堕幖鎰繆椤栨熬韬柛鈹惧亾濡炪倖甯婇悞锕€鐣风仦鐐弿濠电姴鍟妵婵嬫煙缁涘湱绡€濠碘€崇埣瀹曘劑顢欓崣銉╁仐闂傚倸鍊烽懗鍫曗€﹂崼銉晞闁告稑鐡ㄩ弲婵囥亜韫囨挸顏柡鍡畵閺岋綁濮€閵忊晜姣岄梺绋款儐閹瑰洭寮幇顓熷劅闁炽儲鍓氬鍓х磽娴ｅ搫浜剧€规洘锚铻為柛鏇ㄥ灡缁犳帡姊绘担鐟邦嚋缂佽鍊块獮濠冩償閵婂顦崇粻娑樷槈濞嗘垵骞堥梺鐟板悑閻ｎ亪宕圭憴鍕弿鐎广儱顦伴悡娑㈡倶閻愭彃鈷旀繛鍙夋綑閳规垿鍩勯崘鈺佲偓鎰攽閿涘嫭鐒挎い锕備憾閺屟嗙疀閹炬椿鈧銇勯鍕殻濠碘€崇埣瀹曞崬螣鐏忔牗鏅紓鍌氬€搁崐鍝ョ矓瀹曞洦顐芥慨妯哄瀹撲線鏌涢幇銊︽珖妞も晝鍏橀幃妤呮晲鎼存繄鏁栧銈忓瘜閸欏啫顫忓ú顏勫窛濠电姴瀚崳褍顪冮妶蹇涙婵犮垺锕㈤崺銏狀吋閸涱垱娈曢梺鍛婃处閸忔﹢骞忕紒妯肩閺夊牆澧介崚浼存煙鐠囇呯瘈鐎规洦鍨堕幃娆戔偓闈涙憸椤旀洟鏌ｉ悩鍙夊巶闁告侗鍨卞▓濂告煟鎼淬値娼愭繛鍙夛耿瀹曞綊宕归鐐闂佺粯姊婚埛鍫ュ极瀹ュ棛绠鹃柟瀵稿€戝璺虹；闁规崘顕ч崹鍌涖亜閹邦喖小缂併劌顭峰铏规喆閸曨偆顦ㄥ┑鐐差槹缁嬫帞绮嬪鍫涗汗闁圭儤鎸鹃崢鎼佹⒑闁偛鑻晶顖滅磼閸屾稑绗ч柍褜鍓ㄧ紞鍡涘磻閸℃稑鍌ㄩ柦妯侯槴閺€浠嬫煃閽樺顥滈柣蹇婂墲閵囧嫰骞嬮悙鍨櫚閻庤娲滈弫鎼佸焵椤掑﹦绉甸柛蹇旓耿瀹曟垿骞橀懜闈涙瀭闂佸憡娲﹂崜娆愮閳哄懏鈷戠紒瀣閹癸綁鏌℃担鍓茬吋闁绘侗鍣ｅ畷姗€濡告惔銏☆棃闁糕斁鍋撳銈嗗笒鐎氬摜绱為弽銊х瘈闂傚牊渚楅崕鎰版煕鐎ｎ亜鈧潡鐛弽顬ュ酣顢楅埀顒勬倶椤旂偓鍠愰柡澶婃健閸欏嫭鎱ㄦ繝鍕笡缂佹鍠栭崺鈧い鎺嗗亾妞ゎ厼娲╅ˇ鏌ユ懚閻愮繝绻嗛柕鍫濇噺閸ｅ湱绱掗悩闈浶ｉ柟渚垮妼椤啰鎷犻煫顓烆棜闂佽瀛╅鏍窗閺嶎厸鈧箓鏌ㄧ€ｂ晝绠氬┑顔界箓閻牆危閻戣姤鈷戠紒瀣儥閸庢劙鏌熼悷鐗堝枠鐎殿噮鍋婇獮鍥级鐠侯煈妲伴梻渚€娼ч…鍫ュ磿濞差亝鍊甸弶鍫氭櫇绾句粙鏌涚仦鍓ф噰婵″墽鍏橀弻娑㈠棘鐠恒劎鍔梺鐐藉劵缁犳垿鎮鹃敓鐘崇劷闁挎梻鏅粙浣圭節閻㈤潧浠滄俊顖氾攻缁傚秴鈹戠€ｎ亞锛涢梺璺ㄥ枔婵敻鎮￠悢闀愮箚闁靛牆鍊告禍楣冩⒑缂佹﹩娈旈柨鏇ㄤ簻閻ｇ兘寮撮姀鐘殿啋闂佸搫鍊堕崕鏌ュ棘閳ь剟姊绘担鍝ユ瀮婵☆偄瀚灋婵°倓鑳堕々鍙夌節闂堟稒鍌ㄥù婊勭矒閺屾洘绻涢崹顔煎濡炪們鍎虫慨椋庢閹烘鏁婄痪鏉垮船閸撴澘顪冮妶鍡樺碍闁靛牏顭堥悾鐑芥焼瀹ュ懐鐤€濡炪倖鍨煎▔鏇㈠礄瑜版帗鈷掗柛灞剧懅椤︼箓鏌熺拠褏绡€鐎规洘绻嗙粻娑樷槈濡椿妫熷┑鐐存尰閸╁啴宕戦幘鎼闁绘劘灏欑粻浼存偂閵堝棎浜滈煫鍥ㄦ尰閸ｆ娊鏌熼柨瀣仢婵﹥妞藉畷銊︾節閸曘劍顫嶉梻浣瑰濞测晜淇婇崶鈺傤潟闁圭偓鍓氬鈺呮煠閸濄儲鏆╅柛姗€浜堕弻鐔煎礂閼测晜娈梺鍛婃煥椤戝鐛径鎰鐟滃宕戦幘鏂ユ灁闁割煈鍠楅悘宥嗙節閻㈤潧浠滈柨鏇ㄤ簻椤曪絾绻濆顒€鑰垮┑掳鍊曢敃銈夊箖閹达附鈷戠紒顖涙礀婢ф煡鏌ｉ悢鏉戝姦闁绘侗鍣ｅ畷濂稿Ψ閿旇瀚奸梺鑽ゅТ濞诧箒銇愰崘顔煎惞閺夊牃鏅濈壕鐣屸偓骞垮劚閹冲繘藟閵忊懇鍋撶憴鍕闁搞劌鐏濋悾鐑藉Ω閳哄﹥鏅┑鐐叉閸ㄥ灚鏅舵ィ鍐┾拻濞达絽婀卞﹢浠嬫煕閵娿儺鐓肩€殿噮鍋婂畷顐﹀Ψ閵夘喗顥″┑鐘绘涧閸婂鈥﹂崼銏㈡／鐟滄棃寮诲☉銏╂晝闁挎繂娲犲Σ鍫熺節绾板纾块柡鍜佸亰閸┾偓妞ゆ帒鍠氬鎰箾閸欏澧甸柟顖氼槹缁虹晫绮欑捄銊ュЕ婵＄偑鍊栫敮鎺楀窗濮橆剦鐒介柟閭﹀幘缁犻箖鏌涘▎蹇ｆ▓闁绘帊绮欓弻鈩冪瑹閸パ勭彎濡ょ姷鍋炵敮鎺曠亙闂侀€炲苯澧撮柟顔光偓鏂ユ斀閻庯綆浜為鎰攽閻戝洨绉甸柛鎾寸懄娣囧﹪鎳栭埡鍐紲闂佺粯鐟ラ幊鎰矓椤曗偓閺屸€崇暆鐎ｎ剙鍩岄柧浼欑悼缁辨帡濡搁幋婵嗩仼闁诲繈鍎甸弻锝夋晲閸℃瑧鐣肩紓渚囧枟閻熴儵鍩㈡惔銊﹀€锋い鎺戝€婚埢澶娾攽閻樺灚鏆╅柛瀣☉铻ｅ┑鐘插暟椤╁弶绻濇繝鍌氭灓闁哥喎鎳忕换婵嬫濞戞瑯妫忛梺琛″亾濞寸姴顑嗛悡鐔镐繆椤栨繃纭剁紒銊ユ健閺屾稖绠涢幘鍓佷紘缂備浇椴哥敮鐐哄箯鐎ｎ亞鏆﹂柛銉㈡櫇瀹曞弶绻濆▓鍨灈闁挎洏鍎遍—鍐╃鐎ｎ剙绁﹂梺鍝勭▉閸樹粙宕愰悜鑺ョ厵缂備焦锚娣囶垱绻涢悡搴€楅柍瑙勫灴閹瑩鎳犻浣瑰枛缂傚倷绶￠崰鏍崲閹版澘鐓濋柡鍌氱氨濡插牓鏌曡箛濠冩珕闁哄拋浜娲箰鎼达絿鐣靛銈忕細閸楁娊鐛崱娑欏€锋繛锝庡厸缁ㄥ姊虹憴鍕棎闁哄懏鐩幃鐐裁洪鍛幈闂侀潧鐗嗛崯顐﹀焵椤掍胶绠炵€殿喖顭烽弫鎰板幢濡搫濡抽梻渚€娼х换鍡涘箠閸ャ劍鍙忛柛銉墯閻撶娀鎮锋担闈涒偓鏇㈠焵椤掍胶绠炵€殿喖顭烽幃銏ゅ礂閻撳簼鐥俊鐐€栭悧妤佺瑹濡や胶顩烽柍鍝勫暟绾捐棄霉閿濆嫮鐭欓柛婵囨そ閹粙顢涘鍐ф埛濠碘€冲级閸旀瑩鐛幒鎳虫棃鍩€椤掑嫸缍栭柛娑樼摠閻撶喐淇婇姘变虎闁汇劎鍎ら妵鍕籍閳ь剟宕濆▎蹇ｆ綎缂備焦蓱婵挳鏌ｉ幋鐏活亜鈻撳畝鍕拺闁告縿鍎遍弸娆愮箾婢跺绀嬫鐐村灴婵偓闁靛牆鎳愰濠囨⒑閻熸壆鎽犳慨濠傜秺閿濈偛顓兼径瀣ф嫼闂佸憡鎹佺亸娆撳储濞戙垺鐓曢悗锝傛櫇缁愭梻鈧娲橀崹鍨暦閵娧€鍋撳☉娆樼劷闁告﹢浜跺铏规兜閸涱厾鍔烽梺鍛婃煥缁夋挳鍩㈠澶婄倞妞ゆ帊鑳堕崢鍗炩攽閻愬弶顥滅紒缁樺灴钘熼柕蹇婂墲閸欏繐鈹戦悩鎻掓殲闁靛洦绻勯埀顒冾潐濞诧箓宕戞繝鍌滄殾闁绘梻鈷堥弫鍡涙煃瑜滈崜鐔绘闂佸啿鎼幊蹇涘煕閹达附鐓欑紒瀣健椤庢鏌涘┑鍥ㄣ仢闁哄矉绱曟禒锕傛偩鐏炴縿鍎查妵鍕槺缂佽埖宀稿璇测槈閵忕姷顔掗梺鍝勵槹閸ㄧ敻骞楅悽鍛娾拺闂傚牊绋掗ˉ婊堟煕閻曚礁鐏ｉ柟骞垮灩閳规垹鈧綆浜為敍婊堟⒑闂堟稓澧曢柟鍐茬箻椤㈡﹢骞愭惔婵堢畾闂佺粯鍔︽禍婊堝焵椤掍胶澧电€规洘绻嗛ˇ鎾煃瑜滈崜鐔奉焽瑜旈幆宀勫磼濮樼厧娈ㄥ銈嗗姂閸婃劙宕戦幘缁樻櫜閹肩补鍓濋悘宥夋⒑缂佹ɑ灏柛鐔跺嵆楠炲绮欏▎鍓у弳闂佸壊鍋呯换鍕囬銏♀拺缂備焦蓱閳锋帡鏌涘Ο鐘叉缁犺姤绻濋悽闈涗沪闁圭顭峰畷娲礃椤旇偐锛涢梺瑙勫劤閻忓牓宕戦幘鏂ユ灁闁割煈鍠楅悘宥夋⒑鐟欏嫮鎽冩繛鍛礋楠炲牓濡搁埡浣哄姦濡炪倖甯掔€氼參鎮￠崘顔界厓閺夌偞澹嗛ˇ锕傛煛閸℃瑥浠遍柡宀嬬到閳规垿宕堕妸褜妲规繝娈垮枛閿曪妇鍒掗鐐茬闁告稑鐡ㄧ€电姴顭跨拠鈥冲箺闁圭懓娲濠氬Ω閵夘喗鍍靛銈嗘尰缁牏鑺辨繝姘拺闁圭瀛╅ˉ鍡樸亜閺囧棗鍟犻弸宥団偓骞垮劚濞茬娀宕戦幘鑸靛枂闁告洦鍓欓ˇ鈺呮⒑缁嬫鍎忛悗姘煎灦閹﹢宕橀瑙ｆ嫼闂佸憡绋戦敃锝囨闁秵鐓曢柣妯哄暱濞搭喗顨ラ悙鑼缂佽鲸甯掕灒闁兼祴鏅╅崯搴ㄦ⒑閸濆嫷妲搁柣妤€妫欓弲鍫曟偩瀹€鈧惌鎾淬亜閹哄秷鍏岀紒鐘荤畺閺屾稑顭ㄩ崘銊︽缂備礁顦介崰鏍煘閹达箑鐏崇€规洖娲﹂幉鑲╃磽娴ｈ櫣甯涚紒璇茬墕閻ｇ兘宕奸弴鐐嶁晝鎲稿澶屽祦闁割偁鍎查埛鎺懨归敐鍥╂憘婵炲吋鍔欓弻娑欐償閵忕姭鏋欏銈冨灪瀹€鎼併€佸鈧幃鈺呭礂閸濄儳鎲归梻鍌欒兌缁垶宕濆Δ鍛？闁靛牆顦伴崑鍌炵叓閸ャ劎鈯曢柣鎾存礋閺屽秹鍩℃担鍛婄亾濠电偛鐗婂Λ鍐蓟閿熺姴骞㈡い鎾跺У閸嬔囨⒑闁偛鑻晶鍙夈亜椤愩埄妲搁悡銈夋煛瀹擃喖鎳忓▓鎯ь渻閵堝棗绗掗悗姘煎墴閹€斥攽鐎ｎ亞顔愰柡澶婄墕婢х晫鈧潧鍚嬬换娑樼暆婵犱線鍋楅梺鍝勭灱閸犳捇鍩€椤掍胶鈯曢柨姘辩磼濡や礁绗氶柕鍥у婵＄兘鏁傜紒銏℃缂傚倷鑳剁划顖滄崲閸岀偛鐓濋柟鎹愵嚙閸ㄥ倹銇勯弮鍌涙珪濞存粌鐖煎缁樻媴閻熼偊鍤嬪┑鐐村絻缁夌懓顕ｉ弻銉﹀亹闁肩⒈鍓氬▓楣冩⒑闂堟稓杩旈柡澶娿仒缁ㄥジ姊绘担鍛婂暈闁告梹鍨垮畷婵囨償閵婏箑浜楅梺纭呮彧闂勫嫰鍩涢幋锔解拺妞ゆ劑鍊曟禒婊堟煠濞茶鐏￠柡鍛閳ь剚绋掕摫闁告瑥绻愰埞鎴︽偐閹绘帗娈查梺闈涙处缁诲嫰鍩€椤掑喚娼愭繛璇х畵瀹曟垶绻濋崒婊勬闂佺粯姊婚埛鍫ュ极閸愨斂浜滈柟鎷屾硾瀵兘鏌ㄥ┑鍡╂Ч闁抽攱甯掗湁闁挎繂鎳忛崯鐐烘煕閻斿搫浠遍柡宀€鍠庨～銏沪閽樺鍎梻浣烘嚀缁犲秹宕归挊澶屾殾闁圭儤顨嗛崐濠氭煕閳╁叐鎴濃枍閺冨牊鈷掑〒姘ｅ亾婵炰匠鍥佸洭顢曢敃鈧悿鐐箾閹寸偞鐨戦柣顓炴閹鏁愭惔鈥茬按婵炲瓨绮嶇划鎾诲蓟閻斿吋鍊绘俊顖濇娴犳挳姊洪柅鐐茶嫰婢ь喗銇勯鐘插幋妤犵偛妫欑粭鐔煎焵椤掆偓閻ｉ攱绺界粙璇俱劑鏌ㄩ弮鍥舵綈閻庢俺鍋愮槐鎾诲磼濞嗘埈妲銈嗗灥濡盯鍩€椤掑倻鎳楅柛鎰劵閳ь剙娼￠弻鐔封枔閸喗鐏撶紒鐐劤閵堟悂骞冨Δ鍛櫜閹肩补鈧尙鐩庢繝鐢靛仦閹矂宕板Δ鍛﹂柛鏇ㄥ灠椤懘鏌ㄥ☉妯侯仾闁革絾婢樿灃闁绘﹢娼ф禒婊勩亜閹存繍妯€鐎殿噮鍋婂畷鎺戭煥閸曨偅鐎梻浣瑰缁诲倸螞濡ゅ拋鏁傞柣鎴烆焽缁♀偓闂佹眹鍨藉褎绂掗敃鍌涚厵缂佸顑欓悡鑲┾偓瑙勬礃濡炶棄鐣峰鈧、娆撴嚃閳哄骞㈤梻鍌欐祰椤宕曢幎绛嬫晪妞ゆ挾濮锋稉宥夋煙椤栵絿浜圭憸鐗堝笚閺呮煡鏌涘☉鍗炲箺婵絾鍔欏娲川婵犲嫷鏆￠梺鎸庡哺閺屽秹鎸婃径妯恍﹂柧浼欑秮閺屾稖绠涢幘铏€梺浼欑悼閸忔ê顫忕紒妯诲闁告稑锕ら弳鍫濃攽閻愰鍤嬬紒鐘虫尭閻ｇ兘骞嬮敃鈧獮銏＄箾閹寸偟鎳勬繛鍛墪閳规垿鎮欓弶鎴犱户闂佹悶鍔嶅浠嬪春濞戙垹绠ｉ柨鏃傛櫕閸樹粙姊虹紒妯荤叆闁硅绱曞▎銏ゅ蓟閵夛妇鍘撻梻浣哥仢椤戝棝鍩涢幒鏃傜＜閺夊牄鍔屽ù顔姐亜閵忊€冲摵鐎规洏鍔戦、姗€鎮╂潏顭戞晣闂傚倸鍊峰ù鍥敋閺嶎厼闂い鏍ㄧ矋瀹曞弶绻濋棃娑卞剰缂佺姵鐗犻弻鏇＄疀鐎ｎ亖鍋撻弴鐘电焼闁稿瞼鍋為悡鐘崇箾閺夋埈鍎愭繛鍛噺椤ㄣ儵鎮欓幖顓熺暦缂備胶绮换鍕窗婵犲伣鐔访虹紒妯肩Ч闂傚倷鐒﹂幃鍫曞礉鐎ｎ喖纭€闁惧浚鍋傜换鍡涙⒒閸喍绶辨繛绗哄姂閺屽秷顧侀柛鎾寸懇閹箖鎮滈挊澹┿劑鏌嶉崫鍕舵敾闁哄懏绻堝娲箰鎼粹懇鎷婚梺鍝勬媼閸嬪﹤鐣烽姀銈嗙劶鐎广儱妫岄幏娲⒑閸涘﹦绠撻悗姘煎墴閸┾偓妞ゆ帒鍟ˉ澶愭煃缂佹ɑ顥堢€殿喗鎸抽幃銏ゅ川婵犲嫬缍戦梻鍌氬€搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偞鐗犻、鏇㈡晜閽樺澹掑┑鐘灱濞夋盯鎯夐懖鈺冪焼濠电姴鍊堕埀顒佸笒椤繈鏁愰崨顒€顥氶梻鍌欒兌缁垱绗熷Δ鍛獥闁哄稁鍘奸悡婵嬪箹濞ｎ剙濡肩紒鐘哄吹閳ь剝顫夊ú鏍归崒姣硷絿鎲撮崟顏嗙畾闂佺粯鍔︽禍婊堝焵椤掍胶澧垫鐐村姍閹瑩顢楁担绋夸紟闁诲海鎳撶€氼厾鈧艾鐗撻弫鎰緞婵犲嫬鈧偛顪冮妶鍡楃瑐閻犱焦鐓￠獮蹇曠磼濡偐顔曢柡澶婄墕婢х晫绮旈浣虹闁告粌鍟扮粔顔尖攽閳ュ磭鎽犵紒缁樼箞瀹曞爼濡歌楠炴劙姊绘担渚劸闁哄牜鍓熼幃鐤槾缂侇噯缍佸顕€宕掑Δ鈧禍楣冩偡濞嗗繐顏紒鈧崘顔界厱闁靛鍎查崑銉╂煟濞戝崬鏋涙い顐ｇ矒閸┾偓妞ゆ帒瀚畵渚€鏌涢妷锝呭濠殿垱鎸抽弻锝夋偄缁嬫妫嗗┑陇顕滅紞浣割潖婵犳艾纾兼繛鍡樺灩閻涖垹鈹戦悙鏉垮皟闁搞儯鍔屾禍閬嶆⒑缁洖澧查柕鍥у€搁埥澶娢熷鍕棃鐎规洏鍔戦、姗€濮€閳╁啯鐣跺┑鐘垫暩婵兘寮崨濠冨弿闁哄鍤氬ú顏呮櫇闁稿本绋戞禍妤呮⒑閸濆嫭鍌ㄩ柛銊︽そ瀹曟劙鎮介崨濠勫弳濠电娀娼уΛ婵嬵敁濡も偓闇夋繝濠傚缁犵偤鏌熼绛嬬劸缂佺姵鐩鎾偄閸涘﹦妲戠紓鍌氬€峰ù鍥ㄣ仈閸濄儲鏆滄俊銈傚亾妞ゎ厼娲╃粻娑樷槈濡壕鏅犻弻鏇熺珶椤栨俺瀚伴柛鎿冨墴濮婂宕掑▎鎴М缂傚倸绉撮敃顏囨＂闂佽鍎抽顓犵不妤ｅ啯鐓冪憸婊堝礈閻旂厧钃熼柣鏃堫棑閺嗭箓鏌涢妷鎴斿亾闁哄鎳庨—鍐Χ閸愩劎浠惧銈冨妼閿曨亜鐣峰ú顏勭劦妞ゆ帊闄嶆禍婊堟煙閻戞ê鐏ユい蹇婃櫊閺岋綁骞掗幋顓犲悑闂佸搫鐭夌紞浣规叏閳ь剟鏌ｅΟ鍝勬毐闁哄棗鐗撳娲箮閼恒儲鏆犻梺鎼炲妼濠€鍗炍ｉ幇鏉跨婵°倕锕ラ弲顒€鈹戦悙鏉戠仸闁荤啙鍥佸洭濡搁埡鍌楁嫼闂佸憡绻傜€氬嘲危閸濄儳纾界€广儱鎷戦煬顒傗偓?")
        if review_cadence == "light":
            lines.append("婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鈽夊Ο閿嬵潔濠殿喗顨呴悧濠囧极妤ｅ啯鈷戦柛娑橈功閹冲啰绱掔紒妯哄婵犫偓娓氣偓濮婅櫣绮欑捄銊ь唶闂佸憡鑹鹃鍥╂閻愬搫绠ｉ柨鏃傛櫕閸橀亶姊洪棃娑辩劸闁稿酣浜堕崺鈧い鎺嗗亾婵炲皷鈧剚鍤曞┑鐘崇閺呮彃顭跨捄鐚村姛妞ゆ梹甯￠幃妤冩喆閸曨剛顦ュ┑鐐茬湴閸婃繂鐣烽鈷氭椽顢旈崨顏呭闂備礁鎲＄换鍌溾偓姘卞厴瀹曟洟骞囬悧鍫㈠幗濠德板€撶欢鈥斥枔濮椻偓閺岀喖鐛崹顔句患闂佸疇妫勯ˇ鍨叏閳ь剟鏌ｅΟ娲诲晱闁告艾鎳樺缁樻媴閾忕懓绗￠梺鍛婃⒐濞茬喖銆佸棰濇晣闁绘劏鏅滈悘渚€姊洪棃娑氬妞わ缚鍗抽崺娑㈠箣閻愮數顔曢梺鐓庛偢椤ゅ倿宕靛▎鎰垫闁绘劖鎯屽▓婊堟煛瀹€鈧崰鏍嵁閺嶃劍濯撮柧蹇氼潐濮ｅ洭姊绘担铏广€婇柡鍌欑窔瀹曟垿骞橀幇浣瑰瘜闂侀潧鐗嗗Λ妤冪箔閹烘鐓曢柣妯虹枃婢规ɑ銇勯鐐村枠妤犵偛娲、姗€鎮╁▓鍨櫗闂傚倷绀侀幉锟犳偡閵夆敡鍥ㄦ綇閵婏附鐝峰銈呯箰閻楀﹪宕戦崒鐐寸厪闁割偅绻嶅Σ褰掓煟閹惧磭绠婚柡灞剧洴椤㈡洟鏁愰崶鈺冩毇婵＄偑鍊戦崕鎶藉磻閵堝钃熸繛鎴炃氶弸搴ㄧ叓閸ャ劍绀堟い鏂款樀濮婃椽妫冨☉娆愭倷闁诲孩鐭崡鎶芥偘椤曗偓楠炴帒螖閳ь剛绮婚敐鍡欑瘈闁割煈鍋勬慨鍐煟閵夘喕閭慨濠勭帛閹峰懘鎼归悷鎵偧闂備浇顫夐悺鏇㈩敋瑜忛崣鍛存⒑缂佹ɑ鈷掗柛妯犲洦瀚呴柣鏂垮悑閻撱儵鏌ｉ弬鎸庢儓鐎涙繈姊虹紒妯哄闁挎洦浜濠氬即閻旈绐為梺鍓插亝缁诲倹鎱ㄦ惔鈽嗘富闁靛牆楠告晶顕€鏌ｅΔ浣瑰碍妞ゎ偄绻橀幖鍦喆閸曨偆褰撮梻浣藉亹閳峰牓宕滃☉銏╂晩濠电姴鍟扮弧鈧┑鐐茬墕閻忔繂鈻嶅鍡愪簻闁靛闄勭亸顓㈠础闁秵鐓欓柣妤€鐗婄欢鑼磼閻樼儤鐝ǎ鍥э躬婵″爼宕熼褎袦濠电偛鐡ㄧ划宀€绱炴繝鍌ゆ綎婵炲樊浜滅粈鍫ユ煠绾板崬澧悽顖樺劦濮婅櫣绮欏▎鎯у壈闂佺懓鍟垮锕傘€傛ィ鍐┾拺闁告挻褰冩禍鏍煕鎼淬垻鍙€闁糕晜鐩獮瀣晜閻ｅ苯骞堟繝鐢靛█濞佳兾涘Δ鍜佹晜妞ゆ劧闄勯悡鐔肩叓閸ャ劎鈼ラ柟鏌ョ畺閺岋紕浠﹂崜褎鍒涢梺璇″枓閺呮盯鎮鹃悜钘夌倞鐟滃骞忛悧鍫滅箚闁靛牆娲ゅ暩闂佺顑嗛惄顖氱暦椤栫偛绠柛鎾崇仢濞差厼鐣烽悜绛嬫晣婵炴垶眉婢规洟鏌ｉ悢鍝ユ噧閻庢凹鍘剧划鍫ュ焵椤掑嫭鈷戦梻鍫熺〒婢ф盯鏌熼鐓庘偓鍧楁偘椤曗偓瀹曟﹢顢欑喊杈ㄧ秱闂備線娼ч悧鍡涘箠瀹ュ洦顫曢柛顐ｆ礃閳锋垿鏌涘☉姗堟敾濠㈣泛瀚伴弻娑氣偓锝庝簼閸ゅ洦銇勯姀鈭╂垹缂撴禒瀣窛濠电偟鍋撶€氫粙姊绘担渚劸闁哄牜鍓熼幊婵囥偅閸愩劎鍔﹀銈嗗笒鐎氬嘲螞閹寸姷纾兼い鏃囧亹婢ф稓绱掑Δ鍐ㄦ灈闁糕斁鍋撳銈嗗笒鐎氼喖鐣垫笟鈧弻鈥愁吋鎼粹€冲闂佽桨绀侀崯鎾蓟閵娾晛鍗虫俊銈傚亾濞存粌澧界槐鎾存媴閸濆嫷鈧矂鏌涢妸銉у煟妤犵偛鍟灃闁告侗鍠楀▍婊堟煙閼测晞藟闁逞屽墲鐏忔瑩寮弽銊ょ箚闁绘劦浜滈埀顒佸姍瀵彃鈽夊鍡楁闂佸憡鎸烽悞锕€鐣烽崣澶岀瘈闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝€荤壕浠嬫煕鐏炲墽鎳嗛柛蹇撹嫰閳规垿顢欓悙顒佹瘎闂佽桨绶￠崳锝夊垂妤ｅ啫绠涘ù锝呮贡缁嬩胶绱撻崒姘偓鐑芥倿閿曚焦鎳屽┑鐘愁問閸ㄥ崬顭囧▎鎾澄ラ柟鐑樺焾濞尖晠鏌ｉ幘铏崳濞寸媭鍨跺娲川婵犲啰鍙嗛梺纭呭Г缁骸危閹版澘绠婚悗娑櫭鎾绘⒑閹呯闁硅櫕鎸剧划顓㈠灳閹颁焦瀵岄梺闈涚墕閸燁偅淇婃總鍛婄叆闁哄洦锚閳ь剚绻堥獮鍐┿偅閸愨晛鈧鏌﹀Ο渚Ш妞ゆ挻妞藉娲箰鎼淬垻锛曢梺绋款儐閹稿墽妲愰幒妤佸亹鐎规洖娲﹂崚娑㈡⒑閸濆嫯顫﹂柛濠冪箓閻ｅ嘲顭ㄩ崼婵堫唽闂佸湱鍎ら崹鐢电不閿濆鈷掑ù锝勮閻掔偓銇勯幋婵囶棦妤犵偞鍨垮畷鎯邦槾闁哄棴绠撻弻鐔兼倻濮楀棙鐣烽梺绋匡功閸忔﹢寮婚妶鍥ф瀳闁告鍋涢～顐︽⒑閸涘渚涢柛鎾寸懇閸╃偤骞嬮敂钘変汗濡炪倖妫侀崑鎰閸パ€鏀介柣鎰▕濡插綊鏌ｉ埡濠傜仸妤犵偛妫欏鍕偓锝庡墴濡绢噣姊洪崨濠冨碍鐎殿喖鐖煎鏌ュ煛閸涱喒鎷洪梺鍛婄箓鐎氼參宕掗妸鈺傜厱闁靛闄勯妵婵嬫煕閳哄倻娲存鐐差儔閺佸倿鎮剧仦钘夌疄闂傚倷鐒︾€笛兾涙笟鈧、姘愁樄闁绘侗鍠栭～婊堝焵椤掑嫬绠栧ù鐘差儛閺佸秵绻涢幋鐐殿暡闁告帗鐩铏规嫚閳ヨ櫕鐏嗙紓渚囧枟閻熲晠濡存担绯曟婵☆垶鏀遍～宥夋煛婢跺﹦澧戦柛鏂块叄瀵儼銇愰幒鎾跺幗闁瑰吋鐣崐銈咁焽閹邦厾绠鹃柛娆忣檧閼拌法鈧娲栫紞濠囩嵁閹邦厽鍎熸繝闈涚墢閻ｉ箖姊绘担鍦菇闁稿鍊濆畷褰掓偂楠烆剨缍侀幃婊堟嚍閵夈垺瀚肩紓鍌欑椤戝棝顢栧▎鎾崇？闁规壆澧楅悡娆撴煙闂傜鍏岄柣锝囧劋椤ㄣ儵鎮欏顔解枅濡ょ姷鍋為敃銏ゃ€佸▎鎾村殐闁冲搫锕ユ晥婵犵绱曢崑鎴﹀磹閺嶎偅鏆滈柟鐑橆殔绾惧鏌涢埄鍐︿簵闁挎繂顦伴崑瀣煕椤愶絿鐭岀紒鐘冲哺濮婅櫣绱掑Ο鍝勑曟繛瀛樼矋缁捇宕洪埀顒併亜閹哄秶顦﹂柣蹇擃嚟閳ь剝顫夊ú妯兼崲閸岀偞鍋╂繝闈涱儏缁€瀣亜閹哄棗浜炬繛瀛樼矒娴滆泛顫忛搹瑙勫枂闁告洦鍋嗛ˇ銊ヮ渻閵堝棙鑲犻柛銉戝啫鎸ら梻渚€娼чˇ顐﹀疾濠婂牊鍋傞柛鎰典簼閸犳劖绻濇繝鍌滃缂佲偓閸喐鍙忔俊顖涘绾儳顩奸崨瀛樷拺闁告稑锕ユ径鍕煕閵婏箑顥嬬紒顔碱煼楠炲酣鎳為妷褍骞嶉梻浣告贡閳峰牓宕㈡總鍛婂€堕柣妯荤ゴ閺€鑺ャ亜閺冨倹娅曢柕鍡樺笧缁辨帗娼忛妸锕€闉嶉梺鐟板槻閹虫ê鐣峰鍫濈煑濠㈣泛妫欓悗鏉库攽閻樺灚鏆╅柛瀣耿瀹曠娀鎮╃拠鑼€為梺闈浤涢崨顔筋啈婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌熺紒銏犳灍闁哄懏绻堥弻鏇㈠醇濠靛洨顦遍梺绋款儐閹告悂锝炲┑瀣亗閹兼番鍨昏ぐ搴ㄦ⒒娴ｇ瓔鍤冮柛銊ゅ嵆閹矂宕掗悙闈涚ウ闂佸湱鍎ら崵锕傚籍閳ь剟骞忛崨鏉戜紶闁告洦鍋嗛鍏肩節绾板纾块柛瀣灴瀹曟劙寮介‖鈩冩そ瀵粙鈥栭浣衡槈闁宠棄顦～婵嬵敆閳ь剝鈪查梻鍌欑窔閳ь剛鍋涢懟顖涙櫠椤曗偓閹藉爼寮介鐔哄幗濠殿喗銇涢崑鎾寸箾娴ｅ啿瀚々閿嬬節婵犲倸顏ュù婊勭矒閺岀喓鈧稒顭囩粻銉︿繆椤栨浜鹃梺璇插椤旀牠宕抽鈧畷鎴炵節閸屾粍娈鹃梺鍦劋椤ㄥ棝宕愰悜鑺ョ厸濠㈣泛顑呴悘锝夋煙椤曞棛绉慨濠呮閹风娀鎳犻鍌ゅ敽闂備胶顭堥鍥ㄦ叏绾惧浜遍梻浣告啞濞诧箓宕愰敐鍫▌濡ょ姷鍋為幑鍥嵁閹烘骞㈡俊顖滅帛濠㈡垿姊婚崒娆掑厡缂侇噮鍨堕弫瀣⒑鐠囪尙绠茬€光偓缁嬫鍤曢柟鎯版閻撴盯鏌涘☉鍗炴灓闁告﹢浜堕弻锝嗘償椤栨粎校闂佸憡鎸婚悷锔剧矉閹烘挻缍囬柍瑙勫劤娴滈箖鎮峰▎蹇擃仾缂佲偓閳ь剛绱撻崒姘毙㈤柨鏇樺€濋幃楣冩煥鐎ｎ剟妾紓浣割儏閻忔繂鐣甸崱妞绘斀闁挎稑瀚禒鈺傘亜閺囧棗瀚々鎻捨旈敐鍛殲闁绘挶鍎甸弻锟犲炊閳轰椒绮堕梺閫炲苯澧柟顔煎€垮鑽も偓锝庡枛閻愬﹥銇勯幒宥堝厡闁告ɑ鎹囧娲箹閻愭彃顬夌紓浣割儐鐢帡鍩㈠澶婂窛妞ゆ帟鍋愰幊鎾烩€﹂妸鈺佸窛妞ゆ挻绻傞ˉ姘舵⒒娓氣偓閳ь剚绋撻埞鎺楁煕閺傝法鐒搁柨婵堝仜椤劑宕煎┑鍡氣偓鍨攽閿涘嫬浠滃褌绮欓幆鍕償閵婏妇鍘介柟鍏肩暘閸娿倕顭囬幇鐗堢厵闁告縿鍎洪悞楣冩懚閻愬绡€闂傚牊渚楅崕蹇涙煢閸愵亜鏋涢柡灞诲妼閳藉螣娓氼垯杩樻繝鐢靛仜閻牊绂嶉鍫濊摕婵炴垯鍨圭粻缁樹繆閻愰鍤欏ù婊勫劤閳规垿鍩勯崘銊хシ闂佺粯顨嗛幑鍥ь嚕閺勫浚妲奸柣搴ｆ暩閸樠囧煝鎼淬劌绠ｉ柣妯簧戠划鎾愁潖濞差亜浼犻柛鏇ㄥ櫘濞煎爼姊虹粙鍖℃敾闁绘濞€閻涱噣宕奸妷銉庘晠鏌嶆潪鎷屽厡闁汇倐鍋撳┑锛勫亼閸婃牠宕归悡骞盯宕熼鍌ゆ锤婵°倧绲介崯顖炴偂濞戞埃鍋撻獮鍨姎濡ょ姵鎮傞悰顕€寮介銈囷紲闂侀€炲苯澧寸€规洖宕灒闁兼祴鏅╅崯搴ㄦ⒒娴ｇ儤鍤€闁宦板姂閹兘濡烽埡鍌氣偓鑸点亜韫囨挾澧涢柣鎾存礀閳规垿鎮╅幓鎺濅痪闂佸搫妫崜鐔煎蓟閻旂⒈鏁婇柣鎾冲浜涢梻浣哥枃椤曆冾潩閿斿墽涓嶆繛鎴欏灩缁犲ジ鏌涢幇灞芥噺閿涘繒绱撻崒姘偓鎼佸磹妞嬪孩濯奸柡灞诲劚绾惧鏌熼崜褏甯涢柣鎾存礋閺岀喖寮堕崹顔藉€庣紓浣靛妽閹告娊寮诲☉姘ｅ亾閿濆骸浜濈€规洖鐬奸埀顒冾潐濞叉﹢銆冮崱妤婂殫闁告洦鍓涚弧鈧繛杈剧到婢瑰﹤螞濠婂牊鈷掗柛灞捐壘閳ь剟顥撶划鍫熸媴閾忓湱顦繝鐢靛Т娴硷絽鈽夐姀鐘绘暅濠德板€撶拋鏌ュ箰閸愵喗鍊垫鐐茬仢閸旀碍銇勯敂璇茬仸闁诡喚鍋ゅ畷褰掝敃閻樿京鐩庨梻浣侯攰閹活亞寰婇崜褎鍏滈柛鎾茶兌绾惧ジ鏌熼柇锕€骞楅柍閿嬪浮閺屽秷顧侀柛鎾村哺椤㈡瑩寮介鐐电崶濠德板€曢幊搴ｇ不娴煎瓨鐓ｉ煫鍥风到娴滄繈鏌涘▎蹇曠闁哄苯绉烽¨渚€鏌涢幘璺烘灈鐎殿喖顭烽弫鎰板川閸屾粌鏋涢柟绛圭節婵″爼宕ㄩ鍕阀闂傚倸鍊风粈渚€骞夐敓鐘茶摕闁靛ě鍛厠闁荤喐鐟ョ€氼亞鎹㈤崱娑欑厽闁靛繈鍩勯悞鍓х磼閳ь剛鈧綆鍋佹禍婊堟煛瀹ュ啫濡挎い锝呭级閵囧嫰濡烽敂鍓х杽闂佸搫鐬奸崰鏍箖閳╁啯鍎熼柨婵嗘閸犳牠姊绘担鍛婅础妞ゎ厼鐗撻獮澶愭晬閸曨厾鐒块悗骞垮劚濡酣宕戦崨瀛樼厱闁硅埇鍔嶅▍鍥煕濡湱鐭欐慨濠冩そ瀹曨偊宕熼鐔蜂壕闁革富鍘搁崑鎾剁箔濞戞ɑ鎼愰柣銈庡櫍閺岋綁骞囬鐓庡闂佺粯鎸鹃崰鎰崲濠靛鍨傛い鎰剁到閺嗘姊洪崨濠傜瑐闁告濞婂璇差吋閸ャ劌鏋傞梺鍛婃处閸嬪棙瀵煎畝鍕拺閻犲洠鈧櫕鐏€闂佸搫鎳愭慨鎾偩閻ゎ垬浜归柟鐑樼箖閺呮繈姊洪幐搴ｇ畵婵☆偅绋戝嵄闁瑰鍋熺弧鈧梺姹囧灲濞佳勭墡婵＄偑鍊栧褰掓偋閻樿尙鏆﹀ù鍏兼綑閸楁娊鏌曡箛鏇炐ユい銏犳嚇濮婃椽宕ㄦ繝鍌氼潙闁诲繐绻戦悷鈺侇嚕閹惰姤鏅濋柛灞剧☉娴狀厼鈹戦悙鍙夘棞缂佺粯鍔欓、鏃堫敃閿濆啩绨婚梺鍐叉惈閸燁偊宕㈤幘顔界厵妞ゆ梻鐡斿▓婊堟煛娴ｇ懓濮嶇€规洏鍔戦、妯款槺缂佽鲸鍨垮缁樻媴娓氼垳鍔哥紓浣虹帛閸ㄥ潡寮€ｎ喗鈷戝ù鍏肩懅閹ジ鏌涜箛鏃撹€块柣娑卞櫍楠炴帒螖閳ь剛绮婚敐澶嬬厸闁告劧绲芥禍鎯ь渻閵堝骸浜滅紒澶嬫尦閸╃偤骞嬮敂缁樻櫓闂佹椿鍙庨崑鎺撶椤忓嫮鏆﹂柕澹偓閸嬫捇鏁愭惔鈩冪亶闂佺粯鎸堕崕鐢稿蓟閺囥垹閱囨繝闈涙祩濡倗绱撴担鍙夘€嗛柛瀣崌濮婄粯鎷呴崷顓熻弴闂佹悶鍔忓Λ鍕€﹂崶顏嶆Щ闂佺儵妲呴崣鍐潖缂佹ɑ濯撮柣鐔煎亰閸ゅ鈹戦悙鏉戠祷缂佺粯锚閻ｇ兘骞囬鑺ユ杸闁诲函缍嗘禍鐐烘偩濞差亝鈷戦柡鍌樺劜濞呭懘鏌涢悢绋款棆鐎殿啫鍥х劦妞ゆ巻鍋撻柍瑙勫灴椤㈡瑩寮妶鍕繑闂備礁鎲￠幐濠氭儎椤栨氨鏆﹂柟鎵閸婇鈧懓澹婇崰妤冣偓闈涚焸濮婃椽妫冨☉姘暫濠碘槅鍋呴〃濠傜暦閸涘﹦绡€闁搞儯鍔庨崢閬嶆煟鎼搭垳绉甸柛瀣噹閻ｉ浠﹂悙顒€寮挎繝鐢靛Т閹冲繘顢旈悩缁樼厵闁告瑥顦藉▓婊冣攽閳ュ磭鍩ｇ€规洏鍔戦、鏃堝礋椤忓嫷妫滈梻鍌欑閹碱偆绮旈弻銉ョ閹兼番鍔岄悡妯尖偓骞垮劚閹冲寮ㄦ禒瀣厽婵☆垰鎼痪褔鏌熼崗鐓庡鐎规洖鐖奸獮姗€顢欑憴锝嗗缂傚倷绀侀鍡欌偓绗涘喛鑰垮ù鐓庣摠閻撶喐銇勯幘妤€鍟悘宥囩磽娴ｈ鈷掗柛鐘崇墪椤曪綁骞橀纰辨綂闂佹娊鏁崑鎾绘煙妞嬪海甯涚紒缁樼⊕濞煎繘宕滆琚ｆ繝鐢靛仜閹锋垹寰婇崸妤€鏋佹い鏂跨毞濡插牓鏌曡箛銉х？闁告﹢浜跺娲传閸曨偅娈滈梺绋款儐閹歌崵鎹㈠☉銏″殤妞ゆ巻鍋撻柡瀣〒閳ь剚顔栭崳顕€宕戞繝鍌滄殾婵せ鍋撴い銏″哺瀹曘劑顢欓懞銉у絾闂傚倸鍊风粈浣圭珶婵犲洤纾婚柛娑卞灡瀹曟煡鏌涢埄鍐槈缂佺姵妞介弻锟犲炊閵夈儳浠鹃梺鎶芥敱閸ㄥ潡寮婚悢铏圭煓闁圭瀛╁畷宕囩磽娴ｅ搫校闁圭顭锋俊鐢稿礋椤栨稒娅嗛柣鐘叉穿鐏忔瑦绂掗婊呯＝濞撴艾娲ら弸锔姐亜閺囧棗娲ら悡鈥愁熆鐠哄彿鍫ュ几鎼达絺鍋撻獮鍨姎閻庢凹鍣ｉ幆鍕償閵婏腹鎷绘繛杈剧到閹诧紕鎷归敓鐘崇厱閹煎瓨绋戦埀顒佺箓閻ｇ柉銇愰幒鎾充缓缂備礁顑堝▔鏇㈠礉閿曗偓椤啴濡堕崱妤冪懆闁诲孩鑹鹃崲鑼剁亱闂佺鎻梽鍕偂閺囥垺鐓欓柣鎴炆戠亸顓熺箾閹碱厼娅嶉柡宀€鍠栭、娆撴嚒閵堝洨鍘梻浣筋嚃閸犳洜鍒掑▎鎾崇畺闁伙絽鑻弸鍫濐熆鐠鸿櫣鐒告俊顐㈠槻閳规垿鎮╅崹顐ｆ瘎闂佺顑囨繛鈧鐐存崌椤㈡棃宕卞Δ鍐摌濠电偛顕慨鎾敄閸涱垳涓嶉悷娆忓娴滄粓鏌熼弶鍨暢闁诡喚鍘ч…鑳檪缂佺粯绻傞～蹇旂節濮橆剛锛滃┑鐐叉閸旀濡舵导瀛樺€甸悷娆忓缁€鍫ユ煛娴ｇ瓔鍤欓柣锝囧厴椤㈡盯鎮欓弻銉︽殔婵犲痉鏉库偓鎰板磻閹剧粯鐓熼柕鍫濐槺閻ｆ椽鏌″畝瀣埌閾伙綁鏌ｉ幋鐐冩岸寮稿▎鎾粹拺闁硅偐鍋涢埀顒佺墪鐓ら柡宥庡幖閻撴﹢鏌熸潏楣冩闁稿鍔楅埀顒冾潐濞叉牕霉閸岀偛姹查柨鐔哄У閳锋垿鏌涘┑鍡楊仾闁革綀娅ｉ幉鎼佸级閸喗娈婚梺鐐藉劵婵″洭骞戦崟顖毼╅柨鏇楀亾缁剧虎鍨跺铏圭磼濡⒈鏆″┑鐐插悑閻燂箓骞堥妸銉㈡闁靛繆妾ч幏鍝勨攽椤旂偓鍤€婵炲眰鍊濋崺鈧い鎺嶇婵秶鈧娲橀崹鍧楃嵁濮椻偓瀵剟濡烽敂鑺ユ緫闂傚倷鐒︾€笛呯矙閹寸姭鍋撳鐓庡缂佸倸绉电缓浠嬪川婵犲嫬骞堝┑鐘垫暩婵挳宕悧鍫熸珷闁汇垹鎲￠悡娆愩亜閺傝濡兼繛鏉戝€垮顐﹀炊椤掍胶鍘藉┑鈽嗗灠閻忔繈鎯冮搹鍦＜婵炴垶顭囩粻缁樻叏婵犲啯銇濈€规洏鍔嶇换婵嬪礃閵娧勨枈闂傚倷绀侀幉鈩冪瑹濡ゅ懎鍨傞柣鎾冲閿濆绠瑰ù锝呭帨閹风粯绻涙潏鍓ф偧妞ゎ厼鐗撹棢闊洦绋掗悡鏇㈡倵閿濆簼绨兼い銉ｅ灮閳ь剝顫夊ú鎴﹀础閹剁晫宓佹俊顖氬悑瀹曞鏌涘┑鍡楃彅婵鍩栭埛鎴︽⒑椤愩倕浠滈柤娲诲灡閺呭墎鈧稒蓱閸欏繐鈹戦悩鎻掓殲闁靛洦绻勯埀顒冾潐濞叉﹢鏁冮姀銈呯疇闁绘ɑ妞块弫鍡椼€掑顒佹悙闁轰礁顭峰濠氬磼濞嗘帒鍘″銈庡幖閻楁捇銆侀弽顓炲耿婵炴垶顭囬鍥ㄤ繆閵堝繒鍒伴柛鐕佸亰閹偤宕归鐘辩盎闂佺懓鎼Λ妤佺閸撗呯＝濞达絽鎼瓭缂備礁顦遍幊鎾绘偩閻戣棄鍗抽柕蹇曞Х椤㈠懘姊虹拠鑼缂侇噮鍨伴—鍐嚍閵夈倗绠氶梺褰掓？缁€渚€鎮″☉妯忓綊鏁愰崶鑸垫暞缂備浇缈伴崹钘夘潖缂佹鐟归柍褜鍓欓…鍥樄闁诡啫鍥у耿婵炲瓨婢樺ú锔锯偓闈涖偢瀵爼骞嬮悪鍛覆闂傚倷绀佹竟濠囨偂閸儱纾婚柛鈩冪懅娑撳秴螖閿濆懎鏆為柣鎾存礃閵囧嫰骞囬崜浣瑰仹缂備胶濮甸敋闂囧鏌ｅ鍡楁灈闁诲浚浜炵槐鎺旂磼濡吋鍒涢悗瑙勬磸閸旀垿銆佸璺哄耿婵﹫绲芥禍楣冩煕瑜庨〃鍡涙偂濞戙垺鍊堕柣鎰絻閳锋梹绻涢幓鎺旀憼妞ゃ劊鍎甸幃娆撳箹椤撶姴濮洪梻浣告贡閹虫挾鈧矮鍗抽獮鍐煥閸忓墽鍠栧濠氬箻椤旈棿绮ｉ梻鍌氬€搁崐鎼佸磹妞嬪孩顐芥慨姗嗗墻閻掔晫鎲稿鍫罕闂備礁鎼崯顐﹀磹婵犳碍鍎楅柛鈩冾樅瑜版帗鏅查柛銉ｅ妽閻濐亝绻涚€涙鐭嗙紒顔界懃椤繐煤椤忓懎娈ラ梺闈涚墕閹冲秴鈻介鍡欑＝濞达絽澹婇崕蹇涙煟濡や焦灏柣锝呭槻椤劑宕橀敐鍡樻澑闂佽鍑界紞鍡樼濠靛鍊垫い鎺戝閳锋垹绱撴担鐧镐緵闁绘帞鏅槐鎺楊敋閸涱厾浠搁梺绯曟櫆閻╊垶鐛€ｎ喗鏅滈柦妯侯槷閸栨牠姊绘担瑙勫仩闁稿氦宕靛濠偯洪鍕紱闂佽鍎崇壕顓㈠汲閿曞倹鐓曢柕澶樺灣閸掓澘霉濠婂嫬鍔ら柍瑙勫灴閹晛鐣烽崶鑸垫闂備胶绮幐璇裁洪悢鐓庣畺婵せ鍋撻柟顔界懇瀵爼骞嬪┑鍠版垿姊绘担瑙勫仩闁稿鍊濆畷婊冾潩椤撶姭鏀?")
        elif review_cadence == "active":
            lines.append("婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鈽夊Ο閿嬵潔濠殿喗顨呴悧濠囧极妤ｅ啯鈷戦柛娑橈功閹冲啰绱掔紒妯哄婵犫偓娓氣偓濮婅櫣绮欑捄銊ь唶闂佸憡鑹鹃鍥╂閻愬搫绠ｉ柨鏃傛櫕閸橀亶姊洪棃娑辩劸闁稿酣浜堕崺鈧い鎺嗗亾婵炲皷鈧剚鍤曞┑鐘崇閺呮彃顭跨捄鐚村姛妞ゆ梹甯￠幃妤冩喆閸曨剛顦ュ┑鐐茬湴閸婃繂鐣烽鈷氭椽顢旈崨顏呭闂備礁鎲＄换鍌溾偓姘卞厴瀹曟洟骞囬悧鍫㈠幗濠德板€撶欢鈥斥枔濮椻偓閺岀喖鐛崹顔句患闂佸疇妫勯ˇ鍨叏閳ь剟鏌ｅΟ娲诲晱闁告艾鎳樺缁樻媴閾忕懓绗￠梺鍛婃⒐濞茬喖銆佸棰濇晣闁绘劏鏅滈悘渚€姊洪棃娑氬妞わ缚鍗抽崺娑㈠箣閻愮數顔曢梺鐓庛偢椤ゅ倿宕靛▎鎰垫闁绘劖鎯屽▓婊堟煛瀹€鈧崰鏍嵁閺嶃劍濯撮柧蹇氼潐濮ｅ洭姊绘担铏广€婇柡鍌欑窔瀹曟垿骞橀幇浣瑰瘜闂侀潧鐗嗗Λ妤冪箔閹烘鐓曢柣妯虹枃婢规ɑ銇勯鐐村枠妤犵偛娲、姗€鎮╁▓鍨櫗闂傚倷绀侀幉锟犳偡閵夆敡鍥ㄦ綇閵婏附鐝峰銈呯箰閻楀﹪宕戦崒鐐寸厪闁割偅绻嶅Σ褰掓煟閹惧磭绠婚柡灞剧洴椤㈡洟鏁愰崶鈺冩毇婵＄偑鍊戦崕鎶藉磻閵堝钃熸繛鎴炃氶弸搴ㄧ叓閸ャ劍绀堟い鏂款樀濮婃椽妫冨☉娆愭倷闁诲孩鐭崡鎶芥偘椤曗偓楠炴帒螖閳ь剛绮婚敐鍡欑瘈闁割煈鍋勬慨鍐煟閵夘喕閭慨濠勭帛閹峰懘鎼归悷鎵偧闂備浇顫夐悺鏇㈩敋瑜忛崣鍛存⒑缂佹ɑ鈷掗柛妯犲洦瀚呴柣鏂垮悑閻撱儵鏌ｉ弬鎸庢儓鐎涙繈姊虹紒妯哄闁挎洦浜濠氬即閻旈绐為梺鍓插亝缁诲倹鎱ㄦ惔鈽嗘富闁靛牆楠告晶顕€鏌ｅΔ浣瑰碍妞ゎ偄绻橀幖鍦喆閸曨偆褰撮梻浣告惈鐞氼偊宕曢崘鑼殾妞ゅ繐妫涚壕钘壝归敐鍫燁仩閻㈩垱绋撶槐鎺旀嫚閼碱剙顣哄銈嗘穿缁插潡骞忛悩瑁佸湱鈧綆鍋掑鏃堟⒒娓氣偓濞佳呮崲閹烘挻鍙忛柛顐秵濡嫰姊洪崫鍕拱缂佸鍨块崺銉﹀緞閹邦剛顢呴梺缁樺姉椤ｄ粙宕戦幘缁樻優閻熸瑥瀚弸鎴︽⒑閸濆嫬鏆欓柣妤€妫濋幏鎴︽偄閸忚偐鍙嗗┑鐐村灦閿氭い寰板嫮绠剧€光偓婵犱線鍋楅梺鍝勬湰閻╊垶鐛Ο渚富闁硅鍔﹂崬褰掓⒑缁嬫鍎愰柟鐟版喘閻涱噣骞掑Δ鈧粻鐘绘煏婵炲灝鍔ょ紒澶嬫そ閺岀喖顢氶崨顒勫仐閻庤娲忛崝鎴︺€佸☉姗嗙叆闁告洦鍓﹂崯灞剧節瀵伴攱婢橀埀顒侇殕閹便劑鎮滈挊澶岋紱濠电偞鍨堕…鍌氣槈濮楀棛鍙嗛梺绯曟櫈濞夋稑煤椤撶偟鏆﹂柨婵嗘缁剁偤鎮楅敐搴濈盎濞寸厧閰ｅ缁樻媴閻熼偊鍤嬬紓浣筋嚙閸婂潡鐛繝鍥х疀妞ゆ挾鍠愰悵鐑芥⒑閸濆嫭鍌ㄩ柛銊︽そ閹繝宕橀钘変画濠电偛妫楃换鎰邦敂閳哄懏鐓熼煫鍥ㄦ⒐鐏忥箓鏌″畝鈧崰鏍€佸▎鎾村仼閻忕偞鍎冲▍姘舵⒒娴ｇ儤鍤€缁剧虎鍘界换娑㈠焵椤掍降浜滈柕蹇婃濞堟粓鏌涢埞鎯т壕婵＄偑鍊栫敮鎺斺偓姘煎弮瀹曟劙宕奸弴鐔哄弳濠电娀娼уΛ顓炍ｈぐ鎺撶厓闂佸灝顑呴悘鈺冪磼鏉堛劌绗ч柍褜鍓ㄧ紞鍡涘储閻ｅ本鍏滈柛鎾茶兌绾惧ジ鏌ｅΟ璇茬祷闁哄棝浜堕弻宥囨喆閸曨偆浼屽銈冨灪閻熝囧窗婵犲洤纭€闁绘劖鎯岄崯鈧紓鍌氬€搁崐宄懊归崶銊ь洸妞ゆ帒瀚壕濠氭煟閹邦剛浠涚€规洖寮剁换婵嬫濞戝崬鍓扮紒鐐劤閸氬鎹㈠┑鍥╃瘈闁稿本鍑规禒鎯ь渻閵堝棙鈷愭繛鍙夘焽閹广垹鈹戦崱鈺佹闂備礁鐏濋鍡欐閺屻儲鐓冪憸婊堝礈濮橆優娲偄閼测晛绁︽繝鐢靛Т閹虫劙鎮块埀顒€鈹戦悙鏉戠仸闁挎岸鏌熼婊冧槐婵﹥妞藉畷銊︾節閸屾鏇㈡⒑閸濄儱校妞ゃ劌锕獮鍐晸閻樿尙顦ㄥ銈嗘⒒閺咁偊宕㈤崡鐐╂斀闁绘绮☉褎淇婇锝庢疁妞ゃ垺妫冮幃浠嬪川婵犲嫬骞愰梻渚€鈧偛鑻晶鎵磼鏉堛劌绗掗摶锝夋煠濞村娅撻柛鐔烽叄濮婄粯鎷呯粙娆炬闂佺顑嗛幐鍓ф閻愬搫骞㈡俊銈咃功閸旂兘姊鸿ぐ鎺戜喊闁哥姵姘ㄦ竟鏇㈡嚃閳哄啰锛濇繛杈剧秬椤曟牠鎮為悾宀€纾奸柣姗€娼ф禒閬嶆煛瀹€鈧崰鏍€佸▎鎾村殥闁靛牆娲ㄩ崢顖涚節绾版ɑ顫婇柛瀣瀹曨垶顢曢敃鈧悡鈥愁熆鐠哄ソ锟犲籍閸繄鍔﹀銈嗗笒鐎氼剛绮诲ú顏呭€甸柨婵嗛閺嬬喖鏌嶉柨瀣伌闁诡喖缍婂畷鍫曨敂閸曨厽顕楃紓鍌欒兌婵攱鏅跺Δ鍐╁床婵炴垶鍩冮崑鎾斥槈濞嗘鍔峰銈忕秬鐏忔瑧妲愰幒妤€纾兼慨妯荤樂閵徛颁簻妞ゆ挻绮屾慨鍌溾偓瑙勬礈閸樠囧煘閹达箑閱囨繝闈涙椤斿﹪姊婚崒姘偓椋庣矆娓氣偓楠炴牠顢曢敃鈧悿顔姐亜閹板爼妾柛瀣儔閺屾盯鍩勯崘顏佹缂佺虎鍘搁崑鎾绘⒒娴ｇ瓔娼愰柛搴″悑閹便劑濡舵径瀣簵闂佺粯鏌ㄩ崥瀣偂濞嗘挻鈷戞い鎾卞妿閻ｅ崬顭胯閸楁娊寮诲鍥ㄥ珰闁肩⒈鍓涙导鍥╃磽娴ｄ粙鍝洪柟鍛婃倐椤㈡ɑ绺界粙璺槹濡炪倖鎸炬慨宄扮暦閺屻儲鈷掑ù锝堟鐢稑銆掑顓ф疁鐎规洘濞婇弫鎰板川椤栨稒顔曢梻浣稿閸嬪懎煤閿曞倸鏋侀柛鈩冾殢閻斿棝鎮规潪鎷岊劅闁稿孩鍔栫换娑㈠川椤旀儳鈷屽┑顔硷功缁垶骞忛崨瀛樺仭闂侇叏绠戝▓婵堢磽閸屾瑦绁版い鏇嗗洤纾规慨婵嗙灱娴滆鲸淇婇悙顏勨偓鏍箰閸洖鍨傜憸鐗堝笚閸婂潡鏌涢…鎴濅簴濞存粍绮撻弻鐔煎传閸曨剦妫炴繛瀛樼矋閸庢娊鈥旈崘顔嘉ч煫鍥ㄦ礈閺嗐垺绻涚€涙鐭ら柛鎾寸懃瀹撳嫰姊洪崷顓烆暭婵犮垺顭囩划缁樼節濮橆厼浠梺鎼炲労娴滄粓鎯冨ú顏呯叆婵炴垶鐟ч惌濠囨煃鐟欏嫬鐏撮柟顔界懇瀹曪絾寰勫Ο浼欑磼闂傚倷绀侀幉鈥愁潖瑜版帇鈧啯绻濋崘褏绠氶梺鍓插亝濞叉﹢宕戠€ｎ喗鐓曟い鎰剁悼閻瞼绱掗悩鍐插摵婵﹨娅ｇ槐鎺懳熼崫鍕垫綋闂備礁顓介弶鍨瀷缂備浇浜崑銈夌嵁鐎ｎ喗鏅滈柣锝呰嫰楠炲秹姊绘担绋挎倯濞存粈绮欏畷鏇㈠箮閼恒儱鍓归梺鍦劋閹尖晛鈻撴禒瀣厽闁归偊鍘界紞鎴︽煟韫囨梹缍戦柍瑙勫灴椤㈡瑩鎮锋０浣割棜闂傚倸鍊风欢姘焽瑜旈幃褔宕卞☉妯肩枃濠殿喗銇涢崑鎾垛偓瑙勬处閸撴盯骞戦崟顓熷仒闁斥晛鍟弶鎼佹⒒娴ｈ櫣甯涙い顓炵墢娴滅鈻庨幇顕呮祫濠电偞鍨崹娲偂閺囥垺鐓涢柛鎰剁到娴滄儳鈹戦悙鎻掔骇闁绘濞€瀹曟椽濮€閵堝懐顔掗柣鐘叉搐瀵剟鍩￠崨顔惧帗闂佸憡绻傜€氼剟鍩€椤掑倹鏆鐐茬箻瀹曨偊宕熼妸锔芥澑婵＄偑鍊栧濠氬磻閹捐鍚归柍褜鍓欓埞鎴︽倷閼碱剚鍕鹃梺绋匡攻缁诲牓鐛崘顭戞建闁逞屽墴閵嗕礁鈻庨幇顓炲伎闂佸綊鍋婃禍鐐烘儎鎼搭澀绻嗛柣鎰典簻閳ь剚鐗犻獮鎰偅閸愩劎锛涢梺缁樻煥閹测€斥枍閻樼粯鐓ラ柡鍥╁仜閳ь剙缍婇幃鈥斥枎閹扳晙绨婚梺鍝勫暊閸嬫捇鏌涙惔銈嗙彧缂佸倹甯楀蹇涘煘閹傚闁荤喐鐟ョ€氼厾绮堥埀顒傜磽閸屾氨孝闁挎洦浜俊瀛樼瑹閳ь剙顕ｉ幘顔碱潊闁炽儱鍘栧Ч妤呮⒑閸濆嫷妲搁柣妤€鍟村鎻掆攽閸″繑鐏冮梺绉嗗嫷娈曢柍閿嬪浮閺屾稓浠﹂崜褎鍣梺绋跨箰閻倿寮婚悢鍏兼優妞ゆ劧绲界壕鍐参旈悩闈涗沪闁绘濞€閵嗕線寮撮姀鐘栄囨煕閵夈垺娅囬柛妯煎█濮婄粯鎷呴搹鐟扮闂佹悶鍔庨崢褑鐏嬮梺鍛婃处閸橀箖鎯岄崱娑欑厱閻忕偞鍎抽ˉ姘舵煕鐎ｎ偅宕岀€规洘顨嗗鍕節娴ｅ壊妫滈梻鍌氬€风粈渚€骞夐垾瓒佹椽鏁冮崒姘鳖槯濠殿喗銇涢崑鎾搭殽閻愯尙绠茬紒缁樼箓椤繈顢樺☉娆忣伖闂傚倷绀侀幉锛勭矙閹达附鏅濋柕澶涚畱缁剁偤鏌涢弴銊ョ仭闁绘挻娲熼幃妤呮晲鎼存繄鐩庡銈呮禋閸樹粙濡甸崟顖氼潊闁斥晛鍠氬Λ鍐渻閵堝啫鐏柨鏇樺灪閹便劑鍩€椤掑嫭鐓ユ繛鎴灻鈺傤殽閻愭潙濮嶉柡宀嬬稻閹棃鍨鹃崘鑼剁窡闂備胶顭堥鍡涘箲閸ヮ剙绠栨俊銈呮噺閺呮煡骞栫划鍏夊亾閹颁焦楠勯梻鍌欑閹碱偄螞濞戞瑧绠鹃柍褜鍓熼弻锛勪沪閻斿嘲顏╂い鏇￠哺缁绘盯宕卞Ο铏逛淮闂佺硶鏅涢惌鍌氼潖濞差亝顥堟繛鎴炵懐濡繝鏌ｉ姀鈺佺仭閻㈩垽绻濋弫鎰版倷濞村鏂€闁诲函缍嗛崑鍕濡ゅ懏鐓欓柤鍦瑜把呯磼閹绘帇鍋㈤柟顔垮Г缁绘繂顫濋娑欏闂佸搫顦遍崑鐐寸珶閸℃蛋鍥晝閸屾稓鍘藉┑掳鍊撻悞锔句焊椤撶喆浜滄い鎰╁灮缁犺尙绱掔紒妯肩畵妞ゎ偅绻堥、妤呭磼閿旀儳绨ユ繝鐢靛У椤旀牠宕板Δ鍛偓锕傚醇閵夈儳锛涢梺鍦濠㈡﹢鎯屽Δ鍛厸闁搞儯鍎遍悘顏堟煃闁垮鐏撮柡灞剧☉閳藉顫滈崼鐔告毎闂備浇顕栭崹浼存偋韫囨洘顫曢柟鐑橆殕閸嬫劙鏌ц箛锝呬簻缁炬澘绉瑰鐑樺濞嗘垵鍩岄梺鎼炲灪閻擄繝鍨鹃敃鍌毼╅柍杞扮窔閸炲爼姊虹紒妯活梿婵炴挸婀遍懞杈╂嫚濞村鏂€闂佺粯顭囩划顖氣槈瑜旈弻娑欑節閸愨晛鈧劙鎸婂┑鍥ヤ簻闁哄秲鍔岄悞褰掓煛鐎ｎ偅顥堥柡灞炬礃缁绘盯鎮欓浣哄絾闂備焦濞婇弨閬嶅垂閸ф钃熸繛鎴欏灩缁犲鏌℃径瀣仼缂佷線鏀辩换娑氣偓娑欘焽閻绱掔拠鎻掓殶闁瑰箍鍨归埥澶愬閻樼數鍘┑鐘灱濞夋盯鎳熼鐐茬厱鐎光偓閸曨兘鎷洪柣鐘叉礌閳ь剝娅曢悘鈧梻渚€鈧偛鑻晶顖炴煛鐎ｎ剙甯堕崡閬嶆煕椤愮姴鍔滈柣鎾崇箻閻擃偊宕堕妷銉ュБ缂佺偓鍎冲锟犲蓟濞戞﹩娼ㄩ柍褜鍓氱粋宥夊醇閺囩偠鎽曢梺鎸庣箓閻楀繘鎮块埀顒勬⒑閸濆嫭宸濋柛瀣焽閸掓帡鎳滈悽鐢电槇闂佸啿鐨濋崑鎾绘煕鐏炲墽鐭岄柣鎾存崌濮婅櫣鎷犻垾宕囦哗闂佹椿鍓欓妶鎼佸春閳ь剚銇勯幒鎴姛缂佸鏁婚弻娑㈡偐閹颁焦鐤侀梺璇″櫙缁绘繂顕ｉ幘顔碱潊闁挎稑瀚铏節閻㈤潧鈻堟繛浣冲吘娑樜旈崨顓熻緢濠电偛妫欓幐濠氭偂閺囥垺鐓涢柛灞剧箥閸ゆ瑩鏌嶈閸撴岸銆冮崼婢綁骞囬弶璺唺闂佽鍎抽顓犵矓閸洘鈷戦梻鍫熶緱閻擃厾绱掗悩鍐茬伌婵☆偄瀚鍏煎緞鐎Ｑ勫闂備浇宕甸崰鎰熆濡綍锝嗙節濮橆厾鍘甸梺鎯ф禋閸嬪嫭鎱ㄥ鍡╂闁绘劕妯婂Ο鈧Δ鐘靛仦閿曘垽銆佸▎鎾村殐闁冲搫锕ユ晥闂傚倸鍊风欢姘焽瑜旈垾锕傤敇閻樺吀绗夐梺纭呮彧鐎靛矂寮崒鐐寸厵闂傚倸顕崝宥夋煃闁垮娴柡灞剧〒娴狅箓宕滆閸ｎ喖顪冮妶蹇氼吅闂傚嫬瀚幑銏犫攽鐎ｎ亞鍔﹀銈嗗笒鐎氼參鎮為懖鈹惧亾楠炲灝鍔欓悹浣圭叀瀹曟垿骞樼紒妯绘珖闂佺鏈畝鎼佸船閸洘鈷戦梻鍫熶緱濡插爼鏌涙惔銏犫枙鐎殿喖顭峰畷濂稿Ψ閿旇瀚肩紓鍌欑椤︻垰螞濡ゅ啠鍋撳顒€妲婚柍缁樻崌瀵挳濮€閿涘嫬骞堥梺璇插嚱閹儵宕熼鍌氱悼闂傚倷绶氶埀顒傚仜閼活垱鏅舵导瀛樼厵闁惧浚鍋呯亸鐢告煃瑜滈崜姘舵儗椤曗偓瀹曪繝宕橀懠顒佹闂佺懓顕崑鐔哄姬閳ь剟姊虹粙鑳潶闁稿﹥顨婂畷婵嬫倻閼恒儮鎷洪梺鍛婂姇瀵爼骞嗛崼銉︾厵闁告劘灏欑粻鑽も偓瑙勬礃閸ㄥ潡寮幇鏉垮窛闁稿本绋掗ˉ鍫ユ煛娴ｇ鈧潡骞愭繝鍐ㄧ窞婵☆垳鍎ら悿鍌氣攽閿涘嫬浜奸柛濠冩礈閹广垽骞掗幘鍓侇啎闂侀€炲苯澧撮柡宀嬬磿娴狅箓宕滆閸掓盯鎮楀▓鍨珮闁革綇缍侀悰顔碱潨閳ь剙鐣峰鍕閻熸瑥瀚烽崯鍛節绾板纾块柛瀣灴瀹曟劙濡堕崱娆樻锤濠电姴锕ら悧鍡涙偪椤曗偓閹鈽夊▍顓″亹閹广垽宕卞☉娆戝幈濡炪倖鍔х徊鍓х矆閳ь剙螖閻橀潧浜奸柛銊у劋缁岃鲸绻濋崶顬囨煕濞戝崬骞楁繛鍫濈埣濮婃椽鎮烽弶鎸庢瘣濠碘槅鍋呯换鍌烇綖韫囨稒鎯為悷娆忓閻濅即姊洪崷顓犲笡閻㈩垪鏅犲畷婵囧緞閹邦厸鎷洪梺鍛婄☉閿曘倝鎮橀妷褏纾界€广儱鎷戝銉╂煟閿濆懎妲绘い顓滃姂瀹曟﹢鏁愰崱鈺傜秾濠电姵顔栭崰妤呮晝閳哄懎绀堟繛鍡樻尰閸婅泛鈹戦悩鍙夊闁抽攱鍨块弻娑㈠箻閺夋垹绁锋繛瀛樼矋閻楃娀寮诲☉娆愬劅闁靛鍊栭崰姘舵⒑缂佹ü绶遍柛锝忕稻閹便劑鍩€椤掑嫭鐓冮柕澶堝妼閻ㄨ櫣绱掗悩瀹犲妞ゎ亜鍟存俊鍫曞幢濞嗗浚娼风紓鍌欐祰椤曆呯矓閻熸壆鏆﹂梻鍫熺▓閺嬪酣鏌熺€涙ɑ鐓ュù婊呭亾缁绘盯宕煎┑鍫滆檸闂佸搫顑嗛惄顖炲蓟閿濆牏鐤€闁哄啫鍊婚悿鍕⒑缁洘娅囬柛瀣ㄥ€濋悰顔锯偓锝庡枟閺呮繈鏌嶈閸撶喖骞冮敓鐘虫櫢闁绘ê纾崢閬嶆⒑閺傘儲娅呴柛鐘宠壘閳绘挸螣婵傝棄缍婇幃鈺咁敃閿濆棛褰嬫繝娈垮枛閿曘儱顪冮挊澶屾殾闁绘垹鐡旈弫鍥ㄧ箾閹寸偟鎳冮柣婵嬩憾濮婄粯鎷呮笟顖滃姼濡炪倖鍨甸幊姗€寮崘顕呮晜闁告侗鍓涚粻姘舵⒑閸︻叀妾搁柛鐘崇墱婢规洟宕楅崗鐓庡伎濠碘槅鍨板锟犲传閻戞绠鹃柛顐犲劤閻ｇ儤鎱ㄦ繝鍐┿仢妤犵偞鐗犻幃娆撳箵閹烘嚩銉х磽閸屾瑦绁伴悘蹇ｄ簼閹便劑濡堕崶鈺冪効閻庡箍鍎卞Λ搴ㄥ磻閸涘瓨鐓曢柟鑸妽濞呭懎霉閻欌偓閸樺ジ鍩為幋锔藉€烽柛娆忣樈濡偟绱撴担铏瑰笡闁告梹鐟╅妴渚€寮崼顐ｆ櫆闂佺硶鍓濋悷褔鏁嶅鍫熷€甸柛蹇擃槸娴滈箖姊洪崨濠傚闁哄懏绻堟俊瀛樼節閸曨厾锛濇繛杈剧导缁瑩宕ú顏呯厵闁告稑锕ラ崐鎰亜閵忊埄鎴犵紦閻ｅ瞼鐭欓悹渚厛濡茶淇婇悙顏勨偓鏍箰閻愵剚鍙忕€瑰嫭澹嗛弳锕傛煕濞嗗浚妲风紒璇叉閺屾洟宕煎┑鍥ㄦ倷闁哥喐鎮傚铏圭矙濞嗘儳鍓遍梺鐑╂櫓閸ㄤ即鎮鹃悜绛嬫晬闁绘劘灏欓鍛存⒑閼恒儍顏堟晬婢舵劖鏅濋柛灞剧〒閸樼敻姊虹紒姗嗘當闁绘锕﹀▎銏ゆ嚑椤掑倻锛滈梺缁樏崯鍧楀煝閺囥垺鐓涚€光偓閳ь剟宕伴幘璇茬劦妞ゆ帒鍊归弳鈺傘亜椤撶偟澧曢柣鈽嗗弮濮婄粯绗熼埀顒勫焵椤掑倸浠滈柤娲诲灡閺呰埖瀵肩€涙鍘遍柣搴祷閸斿矂鍩€椤掍焦绀嬮柨婵堝仩缁犳盯骞樻担瑙勩仢妞ゃ垺妫冨畷鐔碱敇瑜嶉弫褰掓⒒娴ｄ警鏀伴柛瀣姉閹即濡烽埡浣虹枃闂佹悶鍎洪崜娆戠不椤栨埃鏀介柣妯虹－椤ｆ煡鏌嶉柨瀣伌闁哄瞼鍠栭、娑㈠幢濡や礁娅у銈嗘煥濞诧附绌辨繝鍥ч柛銉仢閵夛负浜滄い鎾跺仧婢ф洟鏌ｉ敐鍥ㄦ毈鐎规洜鍠栭、鏇㈩敃閿濆懐妲ｉ梻鍌欑窔濞佳囨偋閸℃あ娑樷枎閹存繍妫滈梺姹囧灩閹诧繝鎮￠弴銏″€甸柨婵嗛娴滄繈鎮樿箛搴″祮闁哄瞼鍠愮粭鐔煎垂椤旂⒈鐎寸紓鍌欒兌缁垳鎹㈤崼婵堟殾闁绘梻鈷堥弫鍐煏韫囨洖顎岄柣搴ㄤ憾濮婄粯鎷呯粵瀣濠电偛顕崗妯侯嚕椤愶箑绠瑰ù锝囶焾閸嬪秹鎮峰鍕棃鐎规洘妞芥慨鈧柍鈺佸暙閸斿懘姊洪棃娑辩劸闁稿孩濞婇、妯好洪鍛嫼缂傚倷鐒﹂妴鐐哄箣閿旇姤娅囧銈嗗姂閸婃绮堟繝鍋綊鏁愰崨顓ф濠电偛鍚嬮悧妤冩崲濞戞﹩鍟呮い鏃囧吹閻╁酣鎮楅悷鐗堝暈缂佽鍊块崺鐐哄箣閿旇棄浜归梺鍦帛鐢鈻撻銏♀拻闁稿本鍑瑰Σ鍝ョ磼婢跺﹤顣虫俊鍙夊姍楠炴鈧稒锚椤庢捇姊洪崨濠冨鞍鐟滄澘鍟村畷婊堟焼瀹ュ棛鍘介梺闈涚箚閺呮盯鎮橀敐澶嬬厱閻庯綆鍓欓弸娑氣偓瑙勬礃瀹€鎼佺嵁閹烘妫橀柛婵嗗婢规洟姊洪幐搴ｇ畵缂併劌銈搁獮澶嬨偅閸愨晝鍘卞┑顔斤供閸擄箓宕曡箛鏂讳簻妞ゆ挴鍓濈涵鍫曟煙閻熸澘顏柟顕呭櫍瀵爼骞嬪鍛厬缂傚倸鍊搁崐鐑芥倿閿曞倸绀夐柡宥庡亞閻瑩鏌熼悜妯烩拹鐎规洖寮剁换婵嬫濞戝崬鍓遍梺绋款儍閸旀垵顫忔繝姘唶闁绘柨鍢查悗顒勬⒑闂堟稓绠為柛濠冪墵閹繝寮撮姀锛勫幗闂佸搫鍟崑鍡涙倿閻愵兙浜滈柕澶堝労閸庢垹绱掓潏銊ユ诞妞ゃ垺鐟╅幊鐐哄Ψ椤旂瓔妫冮梺璇叉唉椤煤閺嶎厼围缂佸顑欓崵鏇㈡煙缂併垹鏋熼柛瀣閺屾稑鈻庤箛锝喰﹀銈呯箰缂嶅﹤顫忔繝姘＜婵炲棙鍩堝Σ顕€姊虹涵鍜佸殝缂佺粯绻傞悾宄扳攽鐎ｎ亜宓嗛梺缁樺灥濡鈻撻妸鈺傗拺闁告挻褰冩禍婵囩箾閸欏澧辩紒顔款嚙椤繈鎳滈悽闈涘箞婵＄偑鍊栭崝妤佹叏閹绢喖绀夋繝濠傜墛閻撶喖鏌熼幆褏鎽犵紒鈧埀顒勬⒑鐎圭媭娼愰柛銊ユ健楠炲啴鍩￠崨顓狀唽闂佸湱鍎ら幐濠氼敊婢舵劖鈷掑ù锝勮閻掗箖鏌ㄩ弴妯哄姦鐎规洘绻傞埢搴ㄥ箻鐎圭姵鎲伴梻浣虹帛濮婂鍩涢崼銉ユ瀬閻庯綆鍠楅悡鏇㈡煃閳轰礁鏆熼柟鍐叉嚇閺岋綁鏁冮埀顒勬偋閹捐绠栨俊銈傚亾闁崇粯鎹囧畷褰掝敊閻ｅ奔鎲鹃梻鍌欒兌閹虫捇骞夐埄鍐濠电姴娲ㄥ畵渚€鏌涢幇闈涙灈闁绘挻鐩弻娑樷槈閸楃偞鐏堟繛瀵稿Ь濞咃絿妲愰幒妤佸€锋い鎺嶈兌閸戔€愁渻閵堝繒鐣靛ù婊嗘硾椤繑绻濆鍏兼櫖闂佺粯鍔楃悰銉╁箯婵犳碍鈷戠紒瀣濠€浼存煟閻旀潙濮傜€规洘顨堟禒锔界┍閸欐鐩庢俊鐐€栭幐楣冨磻閻斿憡娅犻柨鏃堟暜閸嬫挸鈻撻崹顔界亾闂佽桨绀侀…鐑藉Υ娴ｈ倽鏃堝川椤撶媭妲规俊鐐€栧濠氬磻閹捐秮褰掓偑閳ь剟宕ｉ崘顔肩畺鐎瑰嫰鍋婇悡銉╂煕閹板吀绨芥い鏃€甯掕灃闁绘﹢娼ф禒婊呯磼缂佹ê娴鐐差樀楠炴﹢顢欓懖鈺婃Ч婵＄偑鍊栭崝锕傚磻閸曨偀鏋斿┑鍌氭啞閳锋垿鎮归崶銊ョ祷妞ゆ帇鍨荤槐鎺斺偓锝庡亜濞搭噣鏌嶉妷顖滅暤鐎规洖鐖奸、妤呭焵椤掑嫬纾奸柕濞炬櫆閻撴洘淇婇妶鍛殭濞存粌缍婇弻锟犲焵椤掍胶顩烽悗锝庡亞閸樹粙姊鸿ぐ鎺戜喊闁告挻鐟ч惀顏囶槼闁靛洤瀚版俊鐑芥晜閸撗呭帓缂傚倷娴囨ご鍝ユ暜閻愬灚顫曢柟鐑樺殾閻旂厧浼犻柛鏇炵仛缂嶆帡姊虹拠鎻掝劉妞ゆ梹鐗犲畷浼村冀椤撶偟鏌堥梺绉嗗嫷娈旈柣鎾寸箞楠炴牕菐椤掆偓婵¤偐绱掗悩宸吋闁诡喗顨呴埥澶娾枍椤撗傜盎闁崇粯鎸搁埢搴ㄥ箻缁瀚藉┑鐐舵彧缂嶁偓婵炲拑绲块弫顔尖槈閵忥紕鍘遍梺鍝勫暊閸嬫挻銇勯妸銉伐闁伙絿鍏樺鎾閻樻爠鍐剧唵閻犺桨璀﹂崕蹇撁瑰鍕垫當闁宠鍨块幃娆撳矗婢舵ɑ锛侀梻浣规偠閸斿苯锕㈡潏銊х彾闁哄洢鍨虹€电姴顭跨憴鍕畵缂傚秴锕顐﹀箛椤撶偟绐為柣搴秵閸嬪﹪寮鍫熲拻濞达絿鐡旈崵娆戠磼鐠囧弶顥㈢€殿喗鐓￠幃鈺冩嫚閼艰埖鎲伴梻浣瑰缁嬫垹鈧皜鍥х；闁瑰墽绮弲鏌ュ箹缁厜鍋撻幇浣逛氦闂傚倷绀侀幖顐︻敄閸℃稒鍎庢い鏍仜閽冪喖鏌ㄥ☉妯侯仹婵炲矈浜弻娑㈠箻濡炴崘顔夐柛瀣崌楠炴帒螖娴ｅ搫甯楅柣鐔哥矋缁挸鐣峰鍫澪╃憸蹇曠矆婵犲洦鐓曢柍鈺佸暟閳藉鐥幆褜鐓奸柡灞剧洴閸╁嫰宕橀鍛珮濠电偞鍨堕幐鍝ョ矓瑜版帒钃熼柍銉﹀墯閸氬骞栫划鍏夊亾瀹曞浂鍟堥梻鍌欒兌缁垶骞愰崫銉﹀床婵せ鍋撶€殿喛顕ч埥澶愬閻樻牓鍔戦弻鐔衡偓娑欘焽缁犳捇鏌＄€ｃ劌鈧洟婀侀梺缁樻尭妤犳悂寮抽敐澶嬬厵妞ゆ梻鐡斿▓鏃堟煃缂佹ɑ宕岀€规洖缍婇、娆撴偩鐏炶偐鏁栫紓鍌氬€搁崐椋庢閿熺姴绐楁俊銈呮噺閸嬶繝鏌ㄩ弮鍌涙珪闁崇懓绉撮埞鎴︽偐閸欏鎮欑紓浣哄Х閹虫捇婀侀梺鎸庣箓閹冲繘骞夐幖浣圭厱濠电姴瀚禒杈ㄦ叏婵犲啯銇濇俊顐㈠暙閳藉娼忛埡浣感梻鍌欒兌椤牓鏌婇敐鍡欘洸闁割偅娲滃畵浣逛繆閵堝懏鍣洪柛瀣ㄥ姂閺屾稑鈽夊鍫濅紣闂?")
        if not lines:
            return ""
        if len(lines) <= 2:
            return "".join(lines)
        return " ".join(lines)

    lines = []
    if scenario == "principle":
        lines.append("This turn is not about sounding clever; it is about tying the rule to one code boundary and one failure mode.")
    elif scenario == "concept_teaching":
        lines.append("This turn is not about reciting the concept; it is about attaching it to one live code boundary, one failure mode, and one verification move.")
    elif scenario == "idea_implementation":
        lines.append("Do not chase completeness yet; turn the first move into a tiny loop you can verify immediately.")
    elif scenario == "engineering_challenge":
        lines.append("This turn should stay grounded in the current project, not drift into a detached toy exercise.")
    if recent_wins:
        lines.append(f"A real strength from recent work is: {recent_wins[0]}. That matters because you are not starting from zero.")
    if weak_spots:
        lines.append(f"The thing I most want you to avoid repeating this turn is: {weak_spots[0]}.")
    if scenario in {"review", "plan", "task", "next_task"} and review_rhythm:
        lines.append(f"Keep the review rhythm alive as well: {review_rhythm}")
    elif due_reviews:
        lines.append(f"There are also {len(due_reviews)} follow-up reviews worth revisiting later, but they should not distract this turn.")
    if working_set_mode == "focused":
        lines.append("Stay close to the current task and its nearest files instead of widening the surface area.")
    elif working_set_mode == "broad":
        lines.append("You may reference a broader code boundary this turn, but each step still needs to collapse back into a verifiable patch.")
    if mode == "direct":
        lines.append("Even in direct mode, name the one result you intend to verify before you start typing.")
    elif mode == "guided":
        lines.append("You do not need the full answer yet; getting the first step right is more valuable here.")
    else:
        lines.append("This turn should focus on direction and decision quality first, then we can expand the implementation.")
    if tone_name == "concise_rescue":
        lines.append("Right now the learner needs less surface area, not more theory.")
    elif verbosity_bias == "expanded":
        lines.append("Once this slice lands, we can widen into the principle and tradeoff discussion.")
    if review_cadence == "light":
        lines.append("Review reminders should stay quiet unless the thread begins to drift.")
    elif review_cadence == "active":
        lines.append("Revisit quickly after the slice lands so the loop stays hot.")
    return " ".join(lines)


def _scaffold_close(
    *,
    learner_signal: str,
    mode: str,
    verbosity_bias: str,
    chinese: bool,
) -> str:
    if chinese:
        if learner_signal == "blocked":
            return "婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鈽夊Ο閿嬵潔濠殿喗顨呴悧濠囧极妤ｅ啯鈷戦柛娑橈功閹冲啰绱掔紒姗堣€跨€殿喖顭烽弫鎰緞婵犲嫷鍚呮繝鐢靛Т閻忔岸宕濋弽顐ょ婵°倕鎳忛埛鎴︽⒑椤愩倕浠滈柤娲诲灡閺呭爼顢氶埀顒勫蓟濞戞瑧绡€闁稿本绋栫涵鈧紓鍌欑贰閸犳牠顢栨径鎰祦闁圭儤顨呭Λ姗€鏌涘┑鍡楊仹濠㈣娲熷娲箰鎼达絿鐣电紓浣靛姀閸嬫劙鎳炴潏銊ь浄閻庯綆鍋嗛崢閬嶆⒑閸濆嫬鏆為柟鎼佺畺閹偓娼忛妸锝勭盎濡炪倕绻愮€氼剟寮抽敐鍛斀闁炽儱纾崺锝団偓瑙勬礀瀹曨剝鐏冮梺閫炲苯澧い顓炴喘楠炲鏁傜憴锝嗗缂傚倷绀侀鍡涱敄濞嗘挸纾块柟鎵閻撴瑩鏌ｉ悢鍝勵暭闁哥姵顭囬埀顒侇問閸犳盯顢氳閸┿儲寰勯幇顒夋綂闂佺偨鍎遍崢鏍姳婵犳碍鈷掗柛灞剧懅椤︼箓鏌ｈ箛鏃傜疄妞ゃ垺鐗犲畷銊╊敊缂併垺绁梻浣告贡閾忓酣宕板Δ鍛厱闁瑰濮风壕鍏笺亜閺嶃劎鈯曠紒鈧崘顔界厸濠㈣泛锕︾粔娲煛鐏炲墽銆掗柍褜鍓ㄧ紞鍡涘磻閸涱垯鐒婃い鎾跺枂娴滄粍銇勮箛鎾愁仼闁哄棴绲介埞鎴﹀灳瀹曞洤鐓熼悗瑙勬礀瀹曨剝鐏冮梺閫炲苯澧い顓炴喘楠炲鏁傜憴锝嗗缂傚倷绀侀鍡涱敄濞嗘挸纾块柟鎵閻撴瑧绱掔€ｎ亞浠㈤柍閿嬫⒐娣囧﹪宕ｆ径濠傤潚濡ょ姷鍋為敃銏ょ嵁閸ャ劍濯撮柛娑橈工閳ь剦鍨跺缁樻媴閸涘﹤鏆堢紓渚囧枛閻倸鐣烽鐐茬闁芥ê顦宠婵＄偑鍊栭崝蹇涘箠閿熺姴绫嶉柛顐ゅ枎娴滃綊姊婚崒姘卞缂佸鍔楅崚鎺楀醇閺囩啿鎷洪梺鍛婄缚閸庡崬鈻嶈箛娑欑厱閻庯綆浜跺Ο鈧梺璇″枟閿曘垽鐛幒鎳虫梹鎷呴崫鍕闂傚倷鑳剁划顖炴晪閻庢鍠栨晶搴ｅ垝濮樿泛閿ゆ俊銈勭閳ь剙鐖奸悡顐﹀炊閵婏腹鎷婚梺鐟板暱閹虫劗妲愰幒妤婃晪闁糕剝鐟цⅵ闂備浇顕栭崰妤呮偡閳哄懎绠栨繝濠傚悩閻斿吋鍋傞幖杈剧磿椤旀垿姊婚崒娆掑厡闁硅櫕鎹囧畷銉р偓锝庡枛缁犳氨鈧厜鍋撻柛鏇ㄥ亜閻庮參鎮楃憴鍕婵炲眰鍔戦幆宀勫箻缂佹鍘介梺闈涚箳婵敻宕悙鐑樼厽闁规儳鐡ㄧ粈瀣煙椤旂瓔娈滈柡浣瑰姈閹柨鈹戦崼銏℃櫒濠碉紕鍋戦崐鏇灻瑰璺哄偍濞寸姴顑呮闂佸憡娲﹂崹浼达綖閸涘瓨鐓冮柍杞扮閺嗘瑧鐥幆褍鏆遍摶鏍煟濮椻偓濞佳勭閿斿浜滄い鎾跺仦瀹告繃淇婇崣澶婂妤犵偞甯￠獮濠傜暦閸パ勭亪闂佸搫琚崝搴ㄥ焵椤掑﹦绉靛ù婊嗗煐鐎靛ジ寮介銈囷紳闂佺鏈懝楣冨焵椤掍焦鍊愮€规洘鍔欓獮鏍ㄦ媴閸濄儻绱梻浣虹帛閸ㄥ吋鎱ㄩ妶澶婄９闁秆勵殕閻撱儵鏌￠崶鈺佷粶闁逞屽墮缂嶅﹤顕ｉ幓鎺嗘斀閻庯綆鍋嗛崢鎾绘⒑閸涘﹦绠撻悗姘煎弮瀹曞啿煤椤忓懐鍘辨繝鐢靛Т閸婂綊宕戦妷鈺傜厸鐎光偓閳ь剟宕伴弽顓溾偓浣糕槈閵忊剝娅滈梺鎼炲劵闂勫嫰鎯堣箛娑欌拻濞达綀妫勯崥褰掓煕閻樺磭澧电€规洘鍨剁换婵嬪炊閵娿儰绨甸梻渚€娼чˇ顐﹀疾濞戞氨涓嶉柛锔诲幘绾惧吋銇勯弮鍌氬付閻㈩垬鍔戦弻娑氣偓锝庡亝瀹曞瞼鈧鍣崜鐔镐繆閻戣姤鏅濋柍褜鍓熼、鏃堝煛閸屾粎鐦堢紒鐐緲椤﹁京澹曢崸妤佺厱閻庯綆鍋勯悘瀵糕偓瑙勬礃閸旀瑩鐛€ｎ喗鏅濋柍褜鍓熷畷褰掑磼閻愬鍘卞┑鐘绘涧濡鎮电€ｎ偆绠鹃柟瀛樼懃閻忊晝绱掗埀顒勫礃閳瑰じ绨婚梺鍝勫暙濞层倝藟瀹ュ鐓欓柤鎭掑劜缁€瀣叏婵犲懏顏犻柛鏍ㄧ墵瀵挳鎮欏ù瀣珶濠碉紕鍋戦崐鎴﹀礉瀹€鈧幑銏犖熼搹瑙勬闂侀潧锛忛埀顒勫磻閹剧粯鏅查幖绮瑰墲閻忓秹姊虹紒妯诲鞍婵炶尙鍠栧璇差吋婢跺﹦鍘告繛杈剧到閹测€斥枔閸洘鈷戦柣鐔告緲閺嗛亶鏌涢悤浣哥仸闁靛棗鍟存俊鐑藉煛閸屾埃鍋撻悜鑺ョ厾缁炬澘宕晶顕€鏌嶉鍫熸锭闁宠鍨块、娆戞兜瀹勬澘顫犵紓鍌欑贰閸ｎ噣宕归崼鏇犲祦闊洦绋戝婵嬫煛婢跺鐏ョ紒鎰⊕缁绘繈鎮介棃娴躲垽鏌涢悤浣镐喊鐎规洘绮撻幃浠嬪川婵炵偓瀚藉┑鐐舵彧缁茶偐鎷冮敃鍌涘€垮Δ锝呭暞閻撱儵鏌￠崶鏈电敖闁诡喖銈搁弻娑㈠箳閹惧磭鐟ㄩ梺瀹狀嚙闁帮綁鐛鈧獮宥嗘媴闂€鎰棜濠电偠鎻徊鑺ョ珶婵犲偆鐒介柍鍝勬噺閻撴瑥螞妫颁浇鍏岄柛鏂跨Т椤垽宕堕妸褏鐦堥梺姹囧灲濞佳囧礈瀹曞洨纾奸柤鑹板煐椤ュ鎮￠妶澶嬬厪闁割偅绻嶅Σ褰掓煛閸涱喚绠栭柕鍥у缁犳盯骞樼捄渚毇缂傚倷鑳舵慨闈涱熆濮椻偓閸╃偤骞嬮敂钘変汗闂佸湱绮敮妤€鈻撻鐘电＝濞达絿顭堥。鎶芥煕鐎ｎ剙浠︾紒宀冮哺缁绘繈宕堕懜鍨珫婵犵數濮撮敃銈夊疮椤愶絿顩锋慨妞诲亾婵﹦鍎ゅ顏堝箥椤旂厧顬夐梻浣筋嚃閸犳牠宕愰崹顕呭殨濠电姵纰嶉弲鎻掝熆鐠轰警鍎忓ù婊勭矒濮婃椽宕ㄦ繝鍕窗闂佺瀛╂繛濠囧箖閿熺姴鐒垫い鎺嶈兌缁♀偓闂佹眹鍨藉褎绂掑鍕╀簻闁哄洢鍔屽顔锯偓瑙勬礃椤ㄥ懓鐏掗梺鎯х箺椤鈻撻幆褉鏀芥い鏃傜摂閻掔偓绻涙径瀣€掔紒顔碱煼閹煎綊顢曢敍鍕暰闂備線娼ч悧鍡涘磹閸涘﹦顩查柛鎾楀懐锛濇繛杈剧到閹碱偊鐎烽柣搴ゎ潐濞叉粓寮繝姘槬闁逞屽墯閵囧嫰骞掗幋婵囩亾濠电偛鍚嬮崝鏍崲濞戙垹鐭楀璺鸿嫰閳綊鏌ｉ幘鍗炩偓婵嬪蓟閵娾晛鍗虫俊銈傚亾濞存粓绠栧鍝勭暦閸モ晛绗￠梺鍦焾椤攱淇婇崼鏇熸櫜濠㈣泛锕﹂ˇ銊╂⒑閸愬弶璐￠柛瀣尵閳ь剚鑹鹃妶绋款潖缂佹ɑ濯撮柛娑橈龚绾偓婵＄偑鍊ら崢濂告偋閸℃稒绠掑┑锛勫仜椤戝懎霉闁垮鈻旂€广儱顦伴悡娆撴煟閹伴潧澧伴柡鍡樏湁婵犲﹤瀚惌鎺楁煛鐏炶濮傜€殿噮鍣ｅ畷鍓佹崉閻戞﹩鍞查梻鍌欐祰椤曆勵殽韫囨洜涓嶉柟鎹愵嚙閽冪喖鏌ㄥ☉妯侯仹婵炲矈浜炵槐鎺戔槈濮楀棗鍓伴梺鍛婃尭閻栧ジ骞冨Δ鍐╁枂闁告洦鍓涢ˇ銉╂⒑缂佹澧柛姘儐缁岃鲸绻濋崒銈嗘〃閻庡厜鍋撳┑鐘插敪椤掑嫭鈷掑ù锝夘棑娑撹尙绱掗悩鍐茬伌闁诡啫鍥х闁归鐒︾紞搴㈢節閻㈤潧校闁肩懓澧芥竟鏇㈠礂閸忕厧寮垮┑鈽嗗灠閹碱偊鎳滅憴鍕╀簻闁靛牆鍊告禍鍓х磽閸屾艾鈧悂宕愭搴ｇ焼濞撴埃鍋撴い銏＄墵瀹曞崬鈻庨幇顓燁唶闂傚倸瀚ú銈堢亱闂侀潧绻掓慨顓㈠绩娴犲鐓熸俊顖涱儥閸ゅ鈧鎮堕崕鐢稿蓟閿濆憘鏃堝焵椤掑嫭鏅濇い蹇撶墕缁犳牠鏌ㄩ悢鍝勑ｉ柛瀣姉缁辨挻鎷呯拠锛勫姺闂佸憡顭堝Λ鍕煘閹寸偛绠犻梺绋匡攻閸旀瑥鐣烽幋锕€绠荤紓浣诡焽閸樿棄鈹戞幊閸婃劙宕戦幘缈犵箚妞ゆ劧绲跨粻鐐烘煏閸℃洜顦︽い顐ｇ箞椤㈡寰勭仦钘夋辈闂傚倷绀侀幉鈩冪瑹濡ゅ懎鍨傞柟鎯板Г閺咁剚绻濇繝鍌涘櫧缁惧彞绮欓弻娑氫沪閸撗勫櫘闂佸憡鏌ㄧ粔鐢稿Φ閸曨垼鏁囬柣鎰綑閺嬬娀姊虹化鏇熸珔闁挎洦浜滈锝夊箻椤旇棄浜滈梺鎯х箺椤曟牠宕惔銊︹拻濞达綀娅ｇ敮娑㈡煙閸濄儺鐒鹃棁澶婎渻鐎ｎ亝鎹ｅ☉鎾崇Ч閺屻倖鎱ㄩ幇顑藉亾閹版澘纾婚柟鎹愬煐閸犲棝鏌涢弴銊ュ妞わ负鍔庣槐鎾寸瑹閸パ勭亪缂備胶绮…鍫澪涢悢鍏尖拺闁告繂瀚～锕傛煕鎼淬垻鍙€闁诡噯绻濆鎾閿涘嫬甯楅梺鍝勵槺閸嬬偞绔熼崱娑樼鐎广儱妫涚弧鈧梺閫炲苯澧寸€殿喛鍩栫粩鐔煎礃閺屻儱寮伴悗瑙勬礃閸庡ジ篓閸岀偞顥婃い鎺戭槸婢ь噣鏌嶇憴鍕伌闁搞劍鍎抽悾鐑藉炊瑜忛崢浠嬫煟鎼淬値娼愭繛鍙夌墵閹儲绺界粙璺ㄤ紜闂佸搫绋侀崣搴ㄥ极婵犲洦鐓曟繝闈涙椤忣偄霉閻撳骸顏紒杈ㄦ尰閹峰懏绂掔€ｎ亝鎳欓梺姹囧焺閸ㄦ娊宕戦悢鑲猴綁骞囬弶璺唺闂佺懓鍟跨壕顓㈠窗閺嶎厼绠圭憸鐗堝笒閹硅埖銇勯幘璺烘瀻婵炲懏鐟╁濠氬磼濞嗘埈妲梺纭咁嚋缁绘繈濡撮崘鈺冪瘈闁告劦浜跺ú鎼佹⒑閸撴彃浜濇繛鍙夌墵閹锋垿鎮㈤崗鑲╁幗闂佸搫鍊搁悘婵嬪箖閹达附鐓熼柟鍝勭Ф閻瑩鏌＄仦璇插鐎殿喗娼欒灃闁逞屽墯缁傚秵銈ｉ崘鈹炬嫼闂佸憡绋戦…鈧柟杈剧畱缁犱即鏌熼幆鐗堫棄闁藉啰鍠栭弻銊╂偄閸濆嫅銏ゆ煟閹烘垹浠涢柕鍥у楠炴帒顓奸崼婵嗗腐婵＄偑鍊愰弲婵嬪礂濮椻偓楠炲啫螖閸涱喗娅滈柟鑲╄ˉ閳ь剝灏欓弫鏍⒒娴ｅ憡鍟為柨姘扁偓瑙勬处閸撶喖鍨鹃弮鍫濈妞ゆ柨妲堣閺屾盯鍩勯崘鐐暥閻炴稖鍋愮槐鎾诲磼濞嗘垵濡介悷婊勬緲閸燁偊鈥﹂崶顒佹櫢闁绘灏欓悾楣冩煟韫囨洖浠ч柡鍜佸亰瀵娊宕卞☉娆戝幈闂佸搫娲㈤崝灞炬櫠娴煎瓨鐓曟慨妞诲亾濞存粏娉涢～蹇涙惞鐟欏嫬鏋傞梺鍛婃处閸嬪嫭鎱ㄩ姀銈嗗€甸悷娆忓婢跺嫰鏌涢幘鏉戝摵妤犵偛鐗撴俊鎼佸煛娴ｇ尨绱查梻浣虹帛閸旀洟顢氶銏犲偍闁归棿鐒﹂悡鐔肩叓閸ャ劍绀€濞寸姍鍕╀簻妞ゆ挾鍋熸晶娑㈡煛閸涱厾鍩ｉ柟宕囧█椤㈡牠鎸婃径澶婎棜闂備礁澹婇悡鍫ュ磻閸涱垱顐介柡灞诲劜閸婂灚鎱ㄥΟ鐓庡付妤犵偞锕㈤弻鐔肩嵁閸喚浠奸梺瀹狀潐閸ㄥ綊鍩€椤掑﹦绉靛ù婊呭仱钘濋柡澶嬵儥濞撳鏌曢崼婵囶棞濠殿噯绠撻弻娑氣偓锝庝簼閸ｅ綊鏌嶇紒妯诲鞍缂佽桨绮欏畷銊︾箾閻愵剙顏洪梻鍌欒兌椤牓寮甸鍕仭鐟滄棁妫熼梺鎸庢礀閸婂綊鎮″▎鎴犳／闁哄鐏濋懜鐟懊瑰鍛暭妞ゃ劊鍎甸幃娆戞嫚瑜旂欢瀵哥磽娴ｅ搫校闁烩晩鍨伴锝夊箻椤旇棄鈧兘鏌ょ喊鍗炲幐闁哥姴锕缁樻媴閻戞ê娈岄梺鍛婅壘椤戝骞冩ィ鍐炬晜闁割偅绻勯ˇ顕€鎮楅獮鍨姎妞わ富鍨虫竟鏇㈠垂椤曞懐鍞甸柣鐘烘〃鐠€锕傚磿瀹ュ悿鐟邦煥閸曨厾鐓夐梺缁樻惄閸嬪﹤鐣烽崼鏇炍╅柨鏇楀亾闁哄棙顨嗙换婵嬪煕閳ь剟宕堕敂钘夋灓闂備礁鎼径鍥礈濠靛绠柛娑欐綑娴肩娀鏌曟径瀣闁搞儯鍔庨崢鎼佹倵閸忓浜鹃柣搴秵閸撴稖鈪靛┑掳鍊楁慨鐑藉磻濞戞◤娲敇椤兘鍋撴担鑲濇梹鎷呴崫銉х嵁濠电姷鏁告慨鎾窗濮樿泛鐤柍褜鍓熷濠氬磼濮橆兘鍋撴搴ｇ焼濞撴埃鍋撴鐐差樀閺佹捇鎮╅鐔蜂壕闁挎洖鍊搁悙濠冦亜閹哄棗浜鹃梺鍝勵儎缁舵岸骞冭ぐ鎺戠倞鐟滃酣鍩㈤弴鐔虹闁稿繗鍋愭晶鐢告煛鐏炵喎妫涢悿鈧┑顔矫崥瀣礊閸儲鐓熼幖娣灮椤ｈ尙鈧厜鍋撻柟闂寸閽冪喓鈧箍鍎遍ˇ顖氭暜闂備線娼чˇ顓㈠磿閹绘崼鎺楀箛椤斿墽锛濇繛杈剧到閹碱偅鐗庢繝纰夌磿閸嬫鍒掑▎蹇ｅ殨濠电姵纰嶉弲鎻掝熆鐠轰警鐓繛鐓庯躬濮婅櫣鈧湱濮甸妴鍐煠鐎圭姴鐓愮紒鍌涘浮椤㈡﹢濮€閿涘嫬骞楅梻渚€娼х换鍡涘疾濞戙垺鍊舵繛鍡樻尰閻撳啰鎲稿鍫濈婵炲棙鍨甸ˉ姘亜閹惧崬鐏╂慨瑙勭叀閺屻劑寮崒娑欑彧缂備讲妾ч崑鎾绘⒒閸屾艾鈧悂鎮ф繝鍕煓闁圭儤顨嗛弲顒傗偓骞垮劚椤︿即鎮￠悢鍏肩厵闁诡垎鍐煘闂佸憡妫戠粻鎾诲蓟閿涘嫪娌柛鎾楀嫬鍨辨俊銈囧Х閸嬫稑煤椤撶偟鏆︽繝濠傚婵挳鏌ゆ禒瀣暠闁搞劌鐏濋～蹇撁洪鍕炊闂佸憡娲﹂崑鈧柛瀣崌閹晫绮欑捄顭掔幢闂備胶鎳撴晶鐣屽垝椤栫偛鐓曢柟鐑橆殕閻撴洟鎮橀悙鎻掆挃闁瑰啿妫濋弻娑滅疀閹惧墎鍔梺鍝勬湰缁嬫捇鍩€椤掑﹦绁烽柛鏂挎湰閹便劑宕掑┃鎯т壕閻熸瑥瀚粈鍐╃箾閼碱剙鏋庢い鏇秮瀹曞ジ寮撮悙娈垮悈闂備礁鎼崯鐘诲磻閹剧粯鐓熼幖娣灪閵囨繃鎱ㄦ繝鍐┿仢鐎规洦鍋婂畷鐔碱敆閳ь剟宕戝澶嬧拺闁硅偐鍋涙俊鑲╃磽瀹ュ拑韬鐐插暣瀹曠螖婵犲啯娅旈梻渚€鈧偛鑻晶瀵糕偓娈垮枛椤兘寮幇顓炵窞濠电姴瀚弶鍛婁繆閻愵亜鈧牕顫忔繝姘偍鐟滃孩绌辨繝鍋椽顢旈崨顏呭缂傚倸鍊烽悞锕佹懌闁诲繐绻嬮崡鎶藉蓟閿濆鍋勬繝闈涙閹兼劙鏌ｉ幒鎴犱粵闁靛洤瀚伴獮鎺楀箣濠靛啫浜剧憸鐗堝笒閸氬綊鏌嶈閸撶喖寮婚敐鍡樺劅闁靛繒濮村В鍫ユ⒑閸濄儱校妞ゃ劌锕ら锝夋嚑椤掍礁纾繛杈剧稻濞叉ê螞閸愩劎鏆﹂柕濞炬櫓閺佸洭鏌ｉ幇顓熺稇闁告梹甯″濠氬磼濞嗘垵濡介梺璇″枛閻栫厧鐣烽弴鐏绘椽顢旈崟顓фФ婵犳鍠楅…鍫ュ春閺嶎厼纾婚柛灞剧〒缁犻箖鏌涢埄鍏狀亝鎱ㄩ崒姣懓顭ㄩ崟顓犵厜闂佸搫鐭夌换婵嗙暦濮椻偓婵℃悂鏁傛穱鍗炰汗濠电姷鏁搁崑娑㈠触鐎ｎ喖绀夐柡宥庡亝瀹曞弶绻涢幋娆忕仼鐎瑰憡绻冮妵鍕箻閸楃偛顬夐梺杞扮劍閸庢娊鈥旈崘顔嘉ч柛鎰╁妼鎯熼梻浣侯焾濞寸兘寮繝姘卞祦闁告劑鍔夐弸搴ㄦ煙鐎涙ɑ鐓ュù婊呭亾缁绘盯骞嬮悜鍡曠棯濡炪倕绻愬Λ妤吽夊鑸电厱闁归偊鍓欏Λ姗€鏌￠崘銊у闁稿鍔欏濠氬醇閻旇　妫╁┑鐐茬焾娴滎亪寮婚敐澶婎潊闁宠桨鑳舵导鍫㈢磽娴ｈ櫣甯涚紒璇茬墦楠炲啯瀵奸幖顓熸櫓闂佹悶鍨归ˇ閬嶅窗閺嵮呮殾婵°倕鎳忛崑鍌炲箹鏉堝墽绉剁紒鎵佸墲缁绘繂顕ラ柨瀣凡闁逞屽劯閸ャ劉鎸冮梺鍛婃处閸ㄥジ寮崟顒傜闁糕剝蓱鐏忣參鏌ょ粙璺ㄧШ闁诡喖鍢查埢搴ょ疀閹垮啩绱戠紓鍌欒濡狙囧磻閹剧粯鈷掑ù锝呮贡濠€浠嬫煕閵娿劍顥夋い顓炴穿椤︽煡鏌￠崱蹇旀珚婵﹦绮幏鍛存嚍閵夛絺鍋撻崘顏嗙＜闁逞屽墯缁楃喖鍩€椤掑嫮宓佸鑸靛姈閺呮悂鏌ｅΟ鍨毢闁汇倕瀚板娲濞戣京鍙氱紓浣哄У閸ㄥ潡銆佸鑸电劶鐎广儱妫涢崢鍛婄節閵忥絾纭炬い鎴濇嚇閹﹢濡烽埡鍌滃幗闁瑰吋鎯岄崰鏍ь嚕椤旇姤鍙忓┑鐘叉噺椤忕姷绱掓潏銊ョ瑨閾伙綁鎮归崶顏勭毢妞わ綀灏欑槐鎾诲磼濞嗘挻顎栭梺鍛婃煥閻倿骞冮妷鈺傚亗閹兼惌鍠栧▓銊╂⒑瑜版帗锛熺紒鈧笟鈧畷姗€鍩€椤掑嫭鈷戦梻鍫熶腹濞戙垹妞藉ù锝呮啞濞呮姊婚崒姘偓鐑芥嚄閸洖绠犻柟鐐た閺佸銇勯幘鍗炵仼缁炬儳顭烽弻鐔兼焽閿曗偓閸旓附绻涢幋娆忕仼閹喖姊洪幐搴㈢叆濠⒀傜矙椤㈡瑩寮撮姀鈥斥偓鐢告煟閻斿憡绶叉い銉ョ箻閺屾盯鎮╅搹顐ゎ槶闂佸ジ缂氭ご鍝ョ紦娴犲宸濆┑鐘插楠炴劙姊绘担鍛婂暈濞撴碍顨婂畷鏉款潩鏉堚晙绗夐梺缁樺姉閸庛倝鎮″☉銏″€堕柣鎰絻閳锋棃鏌曢崱妯虹瑨闂囧鏌ｅ▎蹇斿櫧闁伙絿鏁搁埀顒冾潐濞叉鍒掕箛娴°劍绗熼埀顒勫蓟閿熺姴骞㈡い鎾跺Х閻﹀牆鈹戦纭烽練婵炲拑缍侀獮蹇涙偐鐠囪尙顔岄梺鍦劋濮婄鈪烽梻鍌氬€风粈渚€骞夐敓鐘茬閻犲洤妯婂鈺呮煏婵炵偓娅呯紒鐘崇叀閺屾洝绠涢弴鐐愭盯鏌￠埀顒佺鐎ｎ偄鈧敻鏌ㄥ┑鍡涱€楀ù婊嗗Г娣囧﹪顢曢姀鐘虫闂佸疇顫夐崹鍧楀箖濞嗘挸绾ч柟瀵稿С濡楁捇姊洪懝甯獜闁稿﹥绻堝璇测槈濮橈絽浜鹃柨婵嗛娴滄繄鈧娲栭張顒勩€冮妷鈺傚€烽悗鐢殿焾椤囨⒑閻熸澘妲婚柟铏悾鐑筋敃閿曗偓鍞悷婊冮叄閹顢曢敂瑙ｆ嫽闂佺鏈悷锔剧矈閻楀牏绠惧璺侯儐缁€瀣偓瑙勬磻閸楁娊鐛Ο灏栧亾濞戞顏勵嚕閸ф鐓熼幖杈剧稻閺嗏晜銇勯鐐靛ⅵ閽樼喐鎱ㄥΟ鍨厫闁稿缍侀弻鐔碱敇閻旈鐟ㄦ繝纰夌磿閸忔﹢寮诲☉姘ｅ亾閿濆骸浜濈€规洖鐭傞弻锝呪槈閸楃偞鐝濋悗瑙勬礀缂嶅﹪銆佸▎鎾村亗閹兼惌鍠楃紞鎾寸節绾板纾块柛瀣灴瀹曟劘顦寸紒杈ㄦ尭椤繄鎹勯搹璇℃敤闂備浇顫夐崕鐓幬涢崟顓犱笉闁哄稁鍘介悡銉╂煟閺傛寧鎯堢€涙繈姊洪崨濠庢畷濠电偛锕濠氬即閿涘嫮鏉搁梺闈涳紡閸滃啰鍚归梻鍌欑閹猜ゆ懌闂佽鍠栭崐鎼侊綖韫囨拋娲敂閸曨収鍟囬梻浣虹帛閸旀牞銇愰崘鈺傚弿鐎光偓閸曨兘鎷虹紓浣割儐鐎笛囧船婢跺娓婚柡澶嬪灦閸熺偟绱掑畝鍐摵缂佺粯绻堝畷姗€顢旈崼鐕佲偓宥夋⒒娴ｅ憡鍟炵紒瀣灴閺佸啴鏁冮崒姘亶婵炲濮撮鍡浰夋繝鍐︿簻闁规壋鏅涢悘顏勵熆鐠哄搫顏紒缁樼洴瀹曪絾寰勭仦瑙ｅ悅闂備胶鍎靛Σ鍛村矗閸愵煈娼栧┑鐘宠壘绾惧吋鎱ㄥ鍡楀箺闁诡喗鐟ラ—鍐Χ韫囨稒顎嶆繝銏㈡嚀濡繈鐛幋锕€顫呴柣姗嗗亝閺傗偓闂備焦鎮堕崕顕€寮插┑瀣剨闁割偁鍎查埛鎴犵磼鐎ｎ偄顕滄繝鈧导瀛樼厱闁硅揪缍嗗鎰版倵闂堟稏鍋㈤柛鈹惧亾濡炪倖甯掗崐鑽ゅ娴犲鐓曢悘鐐插⒔閹冲棝鏌涜箛鎾瑰闁宠鍨块、娆撴倷椤掍焦鐦撴俊銈囧Х閸嬬偤宕归崹顔炬殾闁割偅娲﹂弫鍡涙煃瑜滈崜鐔煎箯閹达附鍋勯悶娑掆偓鍏呭濡ょ姷鍋涢悘婵嬪礉濮橆厹浜滈柨鏃囨椤ュ鏌嶈閸撴盯寮崨濠冨弿闁圭虎鍠掗埀顒婄畵瀹曠螖娴ｅ憡鐤傞梻浣规た閸擄附绂嶅┑瀣瀭闁秆勵殔閺勩儵鏌曡箛瀣偓鏇㈡煁閸ャ劎绡€闁靛繆鏅欑花鍏间繆椤愩垹鏆ｆ鐐插暣閸╋繝宕ㄩ鍛棃婵犵數鍋為崹鍫曘€冮崱娑樼闁告劦鍠楅埛鎺懨归敐鍥ㄥ殌妞ゆ洘绮嶇换娑㈠箵閹烘梻顔掗悗瑙勬礉椤绮嬮幒鏂哄亾閿濆簶鍋撻婊冨姎闂囧鏌ㄥ┑鍡樺窛闁靛棗锕ユ穱濠囧箵閹烘柨顤€闂侀€涚┒閸斿矁鐏冮梺閫炲苯澧摶鐐寸箾閸℃ɑ灏痪鍙ョ矙濮婂宕奸悢鍓佺箒濠电偞鎸搁…鐑藉蓟閺囥垹閱囨繝闈涙祩濡偞绻濆▓鍨灈闁稿﹤娼″璇测槈閵忕姷鍘告繛杈剧到婢瑰﹥绂掓總鍛婄叄闁煎鍊曟禒锔剧磼缂佹绠栫紒缁樼箞瀹曟帒顭ㄩ崘鐐緫闂傚倷鐒︽繛濠囧绩鏉堚晜鏆滈柨鐔哄Т閽冪喐绻涢幋鐐电叝婵炲矈浜弻娑㈠箻濡も偓鐎氼剙鈻嶅Δ鍐＝闁稿本鐟﹂ˇ鐑芥煠鐎圭姴鐓愰柡鍛版硾铻栭柛娑卞帣閿曞倹鐓曢柡鍥ュ妼閻忕娀鏌涘Δ浣糕枙闁哄本鐩崺鍕礃閻愵剛鏆﹂梻渚€娼荤紞鈧繛鍜冪秮閸┾偓妞ゆ帒鍠氬鎰箾閸欏鑰块柟顕嗙節閺佹捇鎮╅懠鑸垫啺闂備胶绮弻銊╁触鐎ｎ喗鍊垮ù鐘差儐閻撱儵鏌￠崶顭戞當濞存粓绠栧娲传閸曢潧鍓抽梺鍝ュУ閹瑰洭宕洪埀顒併亜閹烘垵鏋ゆ繛鍏煎姈缁绘盯宕ｆ径娑溾偓鍧楁煙椤曞棛绡€闁轰焦鎹囬幃鈺呮嚑閼稿灚鍟洪梻鍌欒兌缁垶寮婚妸鈺佽Е閻庯綆鍠楅崐鍨归悩宸剱闁绘挶鍎甸弻锟犲炊椤垶鐣舵繛瀛樼矒缁犳牕顫忓ú顏勪紶闁告洟娼ч崜鎶芥⒑閸濄儱校闁圭懓娲畷娲焵椤掍降浜滈柟鐑樺灥閺嬨倖绻涢崗鐓庡缂佺粯鐩畷锝嗗緞濞戞壕鍋撻崸妤佺厵妞ゆ洖妫涚弧鈧梺杞扮劍閹瑰洭骞冮埡鍛殤闁肩鐏氶崯娲⒒閸屾瑨鍏岀紒顕呭灦瀵濡搁埡浣虹枀闂佹寧绋戠€氼喚绮堟繝鍥ㄧ厱闁靛鍠栨晶顖炴煟閹惧鎳勯柕鍥у瀵€燁槼妞ゃ儲绮撻弻鐔煎礃閼碱剛顔戝銈忕秮缁犳牕顫忔繝姘＜婵﹩鍏橀崑鎾崇暋閹冲﹤缍婂畷鎯邦檨婵炲瓨鐗犻弻鏇熺箾瑜嶉幊鎰版倿閸忚偐绠鹃柟鐐綑閻掑綊鏌涚€ｎ偅宕岄柡灞稿墲閹峰懐绮欓幐搴㈩啋闂備浇妗ㄧ粈渚€宕弶鎴犳殾闁圭儤鍩堝鈺呮煕濡ゅ啫浠滅悮婵囩節绾板纾块柛瀣灴瀹曟劙寮借閸熷懎鈹戦悩瀹犲缁炬儳顭烽弻鐔煎礈瑜忕敮娑㈡煟閹惧瓨绀冨ǎ鍥э躬椤㈡稑鈹戦崱妤佸劒闂備焦妞块崢鐣屾暜閻愬搫鐒垫い鎺戝枤濞兼劖绻涢崣澶涜€跨€规洖缍婂畷绋课旈崘銊с偊婵犵妲呴崹鐢稿磻閹邦喖顥氶柛蹇涙？缁诲棙銇勯弽銊х煀閻㈩垰鐖奸幃浠嬵敍濞戣鲸鐤侀梺鍝勭焿缂嶄線骞冮姀銈呬紶闁靛／鍛笒缂傚倸鍊风欢锟犲窗濡ゅ懎绠伴柟闂寸劍閸嬧晝鈧懓瀚伴崑濠囨偂閵夆晜鐓曟い鎰╁€曢弸搴∶瑰鍕煉婵﹥妞藉畷妤呮嚃閳瑰灝浠﹂梻浣告惈閹冲繒绮欓幘璺哄灊濠电姴娲﹂弲婵嬫煕鐏炲彞绶辨俊顐㈡噹椤啴濡堕崱妤€顫囬梺鎼炲妿閸庛倕顕ラ崟顖氱妞ゆ挾濮烽敍婊堟煟鎼搭垳绉甸柛瀣閹鈧稒锕╁▓浠嬫煟閹邦厽缍戦柣蹇旀尦閺岀喖鎼归銈囩厜闂佽鍠楅悷鈺呭蓟閸涱厸妲堟慨妯块哺閺呫劑姊婚崒姘偓宄懊归崶顒婄稏濠㈣埖鍔曠壕鍧楁煙閸撲胶鎽傞柡浣割儐閵囧嫰骞橀崡鐐典患闂佺粯鎸撮埀顒佸墯閻斿棝鎮规ウ瑁も偓鈧┑顔兼喘閺岋綁鎮㈤悡搴濆枈闂佺粯鎸堕崕鐢稿蓟濞戙埄鏁冮柣妯垮皺娴煎嫰姊洪崫鍕紞闁稿瀚伴崺鐐哄箣閿旂粯鏅╃紒缁㈠幖閸㈠弶瀵奸幇顒夋富闁靛牆楠搁獮鏍煕閵忥紕鍙€闁诡噣绠栭弻銊р偓锝庡墴濡绢噣姊洪崨濠勨槈闁挎洏鍊栫粋宥咁煥閸喓鍘介梺缁樺姇椤曨參鍩㈤幘缁樼厓鐟滄粓宕滃璺虹婵﹩鍓﹂悞浠嬫煙閸撗呭笡闁抽攱甯￠弻娑氫沪閸撗勫櫙闂佺绻愰惌鍌炲蓟閻斿吋鎯炴い鎰剁到绾板秴顪冮妶鍡樼┛缂傚秳绀侀悾閿嬬附缁嬪灝宓嗛梺缁樺姉閺佹悂寮抽锔解拻濞达絼璀﹂悞楣冩煟椤掆偓閵堢鐣烽幋婵冩闁靛繆鈧磭褰呴梻浣虹帛閺屻劑宕ョ€ｎ喗鍋傞煫鍥ㄧ⊕閻撴洘銇勯幇鍓佹偧缂佺姵鐗滈埀顒傛嚀閹诧紕鎹㈤崼銉ヨ摕闁挎繂顦介弫鍥煟閺冨倸鍔嬮柛锝勫嵆濮婅櫣鎷犻垾铏亪缂傚倸绉撮敃顏堟偘椤旂晫鐟归柍褜鍓熼悰顕€骞掑Δ鈧粻锝嗙節閸偄濮夐柍褜鍓氭繛濠傤潖缂佹ɑ濯撮柧蹇曟嚀缁楋繝姊虹憴鍕€愮紒鐘崇墪閻ｉ攱瀵奸弶鎴濆敤閻熸粍绮岄…鍥冀閵娧咁啎閻庣懓澹婇崰鏇犺姳鐠囪褰掓嚃閳轰讲鏋呴梺鍝勬湰閻╊垰顕ｉ幘顔嘉╅柕澶堝劤椤旀帒鈹戦悙宸殶闁告鍏犳椽顢橀悜鍡樼稁濠电偛妯婃禍婊勫閻樼粯鐓忓璺虹墕閸撻箖鏌ㄥ┑鍡╂Ч闁绘挻鐟╅弻锝夋偄閸濆嫷鏆梺鍝ュУ椤洭鍩€椤掑喚娼愭繛鍙壝—鍐╃鐎ｎ亝妲梺閫炲苯澧柕鍥у楠炴帒顓兼径瀣碘偓鏍ㄧ箾鐎涙鐭嬬紒顔芥崌瀵鎮㈤悡搴濈炊闂佸憡娲﹂崢婊堝Ψ閳哄倻鍘遍棅顐㈡处閹搁箖鎮為幖浣圭厸閻忕偟鏅晥濡炪們鍨虹粙鎴﹀煡婢跺ň鏋庨柟鎼幗鏁堥梻鍌氬€风粈渚€骞栭銈嗗仏妞ゆ劧绠戠粈澶屸偓鍏夊亾闁告洖澧庣粙蹇撯攽閻樼粯娑фい鎴濇瀹曠數鈧綆鍠楅悡鐔兼煏韫囧鈧牕鈽夎椤ㄣ儵鎮欓幖顓熺杹濠殿喖锕︾划顖炲箯閸涙潙宸濆┑鐘叉噽椤㈠懘姊绘担鐟板姢缂佺粯鍔欓弻濠囨晲閸涱垱娈鹃悷婊呭鐢宕戠€ｎ喗鐓曟い鎰Т閻掔儤绻涢崣澶嬪€愭慨濠冩そ瀹曘劍绻濋崘銊ф▊闂備礁鎲℃笟妤呭垂閻ｅ本顫曢柟鎯板Г閳锋帒霉閿濆嫯顒熼柣鎺楃畺閺岋繝宕奸銏犫拫闂佺娅曠换鍐Χ閿濆绀冮柕濞у啫袝濠碉紕鍋戦崐鏍ь啅婵犳艾纾婚柟鍓х帛閻撴洟鏌曡箛銉х？闁告瑢鍋撴繝鐢靛Л閸嬫挸銆掑锝呬壕濠殿喖锕ュ浠嬬嵁閺嶎厽鍊烽柟缁樺笒椤垿姊绘担鍛婂暈闁哄被鍔戦弫鍐Ψ瑜忛惌澶愭煙閻戞﹩娈旈梺鍗炴喘閺屾洘寰勫☉姗嗘喘闂佸憡锚瀹曨剟鍩為幋锔藉亹缂備焦蓱闁款參鏌ｆ惔銏犲毈闁告挾鍠庨悾宄扳攽閸♀晝鍙嗛梺鍛婁緱娴滄粍绂嶆ィ鍐╁仭婵炲棗绻愰顏嗙磼閳ь剟宕橀鐣屽幗闂佺懓鐏濈€氼喚寮ч埀顒勬倵濞堝灝鏋︽い鏇嗗洤鐓″鑸靛姇椤懘鏌嶉崫鍕偓鐟扳枍閸ヮ剚鈷掑ù锝堟鐢盯鎷戞潏鈺傚枑闁哄鐏濋弳鐐烘煙娓氬灝濮傚┑顔瑰亾闂侀潧鐗嗗Λ妤呭焵椤掑倹鏆柟顔煎槻閳诲氦绠涢幙鍐х棯闂佽绻愬ù姘跺磻閸℃瑦顫曢柟鐑橆殕閸ゅ姊婚崼鐔衡槈闁逛粙娼ц灃闁绘﹢娼ф禒婊堟煕閻曚礁浜柣蹇撳暣濮婃椽宕ㄦ繝浣虹箒闂佸摜濮甸〃鍛村煝瀹ュ拋鐓ラ柛顐ゅ枔閸樼敻姊洪崗鑲┿偞闁哄懐鍋犲Λ銏ゆ⒒娴ｅ憡鍟為柟姝屽吹閹广垽宕奸妷銉х暫濠殿喗銇涢崑鎾垛偓瑙勬礀閵堝憡鎱ㄩ埀顒勬煏韫囷絾绶涚紒鍗炲暱閳规垿鎮欓懜闈涙锭缂備浇寮撶划娆撶嵁閺嶎収鏁冮柨鏃傜帛閺呮盯姊虹憴鍕姢濠⒀冩捣婢规洟鎮剧仦绋夸壕妤犵偛鐏濋崝姘舵倵濮樼厧鏋ょ紒顕嗙秮瀵噣宕掑Δ鈧禍鐐箾閸繄浠㈤柡瀣⊕閵囧嫰顢橀悩鎻掑箣閻庢鍣崑濠囩嵁閸ヮ剙绾ч柛顭戝枤閻涒晠姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸曨偄鍤戝┑鐐村灦閸╁啴宕戦幘鑸靛枂闁告洦鍓欓ˇ鈺呮⒑缁嬫鍎忛柨鏇樺€濋幃楣冩倻閼恒儱浜滅紒鐐妞存悂寮查姀锛勭閺夊牆澧介幃濂告煕鎼存稑鈧盯路閸涘瓨鈷掗柛灞捐壘閳ь剚鎮傚畷鎰板箹娴ｅ摜锛欓梺缁樺灱婵倝宕甸崟顖涚厱闁规崘灏欓ˇ锕傛煕閵婏妇绠栭柕鍥у瀵粙顢曢～顓犳崟缂傚倷鑳舵慨鎶藉础閹惰棄绠栫憸鐗堝笒閻愬﹥銇勮箛鎾缎ｉ柍閿嬬墵濮婃椽宕ㄦ繝鍕暤闁诲孩姘ㄩ崗姗€骞冮敓鐘参ㄩ柍鍝勫€婚崢鍗炩攽閻愭潙鐏ョ€规洦鍓欓埢宥呂熼懡銈囶啎闂佸吋绁撮弲娑㈠几濞戞瑦鍙忓┑鐘叉噺椤忕娀鏌熼崣澶嬪唉鐎规洜鍠栭、鏇㈠Χ鎼粹懣鐐测攽閿涘嫬浜奸柛濠冪墪閳绘棃鏁冮崒姘獩濡炪倖鎸嗛崟鍨紖闂傚倸鍊烽懗鍫曗€﹂崼銏″床婵°倕鎳庣壕濠氭煙闁箑鏋ゅ☉鎾崇Т铻栭柨婵嗘噹閺嗙偤鏌ｉ幘瀛樼闁哄苯绉归崺鈩冩媴缁嬭法顔掓俊鐐€曠换鎰版偋婵犲洤纾归柛顐ｆ礀缁狙囨煕椤愶絿顣叉繛鍛川閻ヮ亪骞嗚閸嬨垽鏌″畝鈧崰鏍蓟閸ヮ剚鏅濋柍褜鍓欓锝夋倷椤掑倻顔曢梺鍓插亞閸犳捇鎯岀€ｎ喗鐓欏〒姘仢婵＄晫绱掔紒妯肩疄鐎规洘锕㈤崺鐐村緞濮濆本顎楅梻浣筋嚙濮橈箓锝炴径濞掗缚绠涘☉妯碱槷閻庡箍鍎卞ú锕€鐣烽崣澶岀瘈闂傚牊绋掓径鍕煕鎼达絽鏋涢柡灞诲妼閳规垿宕卞Ο鐑橆仩濠殿喗绻傚ú銈夊煘閹达附鍋愰柛顭戝亝濮ｅ嫭绻濆▓鍨灆闁告鍟块悾椋庢喆閸曨厾鐦堝┑顔斤供閸撴盯鎮块崶顒佲拺闁荤喐婢橀埛鏃傜磼椤曞懎鐏︾€规洘鍨归埀顒婄秵閸犳鎮″▎鎾寸厱闁圭偓顨呴幊鎰版儊閸垻纾藉ù锝囩摂閸ゆ瑦淇婇锝囩疄鐎殿喖顭烽弫鎰緞婵犲孩缍傞梻渚€娼х换鍡涘疾濠靛绀夐柛婵勫劤绾捐棄霉閿濆懏鎯堥弽锛勭磽娴ｅ壊鍎愰悽顖楀墲娣囧﹪鎮界粙璺槹濡炪倖鐗楅懝楣冨船閵娾晜鈷戞慨鐟版搐閻忣噣鏌℃担鍦憙闁圭瓔鍋婂濠氬磼濮橆兘鍋撻幖浣€鍥敍閻戝棙鏅炴繝銏ｆ硾椤剙顭囬弽褉鏀介柣妯虹枃婢规鐥幆褍鎮戠紒缁樼洴瀹曞崬螣閸濆嫷娼曢梻渚€娼ч悧濠傤熆濮椻偓閸╃偤骞嬮敃鈧悞娲煕閹板墎绱扮紒顔碱煼濮婃椽宕ㄦ繝鍐弳婵°倗濮甸幃鍌炲春閵忊剝鍎熼柕濞垮労濞煎﹪姊洪棃娑氬婵☆偅鐟ラ埢宥夊閵堝棌鎷虹紓鍌欑劍閵嗙偤骞嬮敂钘変簵闂佺偨鍎茬欢鐐测槈閵忊€斥偓濠氭煠閹帒鍔楅柟閿嬫そ濮婃椽宕烽褏鍔稿┑鐐存尦椤ユ挾鍒掓繝姘婵烇綆鍏涚花濠氭⒑閹稿孩顥嗘い鏇嗗洦鍊堕柨鏃堟暜閸嬫挸鈻撻崹顔界亪闂佺顕滅槐鏇犲垝椤撱垺鍋勯柣鎾虫捣閸旓箑顪冮妶鍡楃瑨閻庢凹鍓熼幏鎴︽偄閸濄儳顔曢梺鐟邦嚟閸嬬喖鎮￠娑氱鐎光偓婵犱線鍋楅梺鍝勬湰閻╊垶鐛Ο浣曟棃鍩€椤掑嫬绠犻柟鐗堟緲閸屻劑鏌熸潏楣冩闁绘挾鍠栭獮鏍庨鈧埀顑惧€曢…鍥箛椤撶姷顔曢梺鍛婄懃椤﹁鲸鏅堕悽鍛婂癄婵犻潧顑嗛悡鐔兼煏韫囧鐒洪柣鎺楃畺閺岋箓宕橀鍕亪闂佸搫鐭夌换婵嗙暦閸洖鐓涘ù锝呮贡娴滄牜绱撻崒娆掑厡濠殿喖鐡ㄩ弲鑸电鐎ｎ亞鐤呴梺鍛婄☉閿曘倗娆㈤悙鐑樼厵闂侇叏绠戞晶浼存煥濞戞瑧娲存慨濠冩そ閹兘寮舵惔鎾村瘱缂傚倷鑳剁划顖滄崲閸曨垰绠查柕蹇嬪€曢獮銏＄箾閹寸偟鎳呴柛妯兼暩缁辨捇宕掑▎鎴濆闂佹寧姘ㄧ槐鎺戭渻閿曗偓閸犳岸鎮㈤崱娆愬枑婵犻潧顑嗛埛鏃堟煕閺囥劌鐏犵紒鐘靛仱閺屾洘绻濊箛鎿冩喘缂備讲妾ч崑鎾绘⒒娴ｅ憡鍟炴繛璇х畵瀹曘垽鎳栭埡鍐暥闂佽法鍠撴慨鐢稿煕閹达附鐓熼柣鏂挎啞缁跺弶淇婇幓鎺濈吋闁哄瞼鍠栭幖褰掝敃閵忕媭娼曢梻浣告啞鐢鏁敓鐘茬畺闁伙絽鑻弸鍫熶繆椤栨繃銆冨瑙勬礋濮婃椽骞愭惔锝囩暤婵°倗濮撮幉锛勭矉瀹ュ鍊烽柣銏㈡暩閿涙粍绻濋姀锝嗙【闁挎洏鍊曞嵄濠电姵纰嶉悡鍐偡濞嗗繐顏╅柣蹇旀尦閺岀喖顢欓悾灞惧櫚闂佺懓纾繛鈧い銏☆殕閹峰懘鎮烽悧鍫邯缂傚倸鍊搁崐鎼佸磹妞嬪孩顐介柨鐔哄Т缁愭鏌″搴″箺闁稿顑夐悡顐﹀炊閵娧€妲堢紓浣插亾闁糕剝绋掗悡娆撴煟閹寸伝顏堟倶瀹ュ鐓涢悗锝庝邯閸欏嫰鏌ｉ幙鍐ㄤ喊鐎规洖鐖兼俊鎼佹晜缂併垺袨濠电姷鏁搁崑娑㈡偋婵犲洤纾块柟鎯版閻撴﹢鏌熸潏楣冩闁稿鍔楃槐鎾存媴閼测剝鍨块弻銊╊敇閵忊檧鎷洪梺鍦焾鐎涒晝绮氱捄銊х＜闁绘娅曞畷灞绢殽閻愭彃鏆ｇ€规洜顭堣灃闁逞屽墴閹偤宕归鐘辩盎闂佸湱鍎ら崹鐢割敂椤忓牊鐓冮梺鍨儏閻忔挳鏌＄仦鍓р槈闁宠鍨垮畷鍗炍旀繝浣烘／闂佽娴烽幊鎾诲箟閿涘嫭宕查柛顐犲劚閽冪喐绻涢幋娆忕仾闁稿鍔欓弻鐔虹磼濡桨鍒婇梺鍛婃煥椤﹂潧顫忛搹瑙勫珰闁炽儱纾禒顓炩攽椤旂》宸ユ繝鈧柆宥呯闁靛繒濮弨浠嬫倵閿濆簼绨介柨娑欑矊閳规垶骞婇柛濠冩崌閹偤鏁冮崒姘遍獓闂佸綊妫块悞锕傚煕閹烘嚚褰掓晲閸涱喗鍠愰梺鍝勵儏閸燁垱绌辨繝鍥舵晝闁靛繒濯禒濂告煣閼姐倕浠﹀ǎ鍥э躬婵″爼宕ㄩ鍏碱仭闂備胶顭堥敃銈夋偉婵傜钃熼柡鍥╁枔閻濊埖銇勯弽顭戞當濞存粓绠栧铏圭矙濞嗘儳鍓遍梺瑙勬倐缁犳牠鐛径鎰妞ゆ棁鍋愰ˇ鏉款渻閵堝棗绗掗柛瀣鍗遍柛顐ｆ礃閳锋帒霉閿濆牆袚闁靛棗鍟扮槐鎺楀焵椤掍胶鐟归柍褜鍓熼崹楣冩晝閳ь剟鎮鹃敓鐘茬妞ゆ棁濮ら鏇熺節閻㈤潧浠滄俊顖氾攻缁傚秴顭ㄩ崼顒傜◤闂佸憡绋戦悺銊╂偂韫囨稒鐓曟い鎰剁悼缁犳牠鏌涢敐鍕煓闁哄矉缍侀、鏇㈠閻欌偓娴煎啫鈹戦纭锋敾婵＄偠妫勯悾宄邦煥閸繄顔岄梺鐟版惈缁夊爼寮弽顓熲拻濞达絽鎲￠幉绋库攽椤旇姤灏﹂柡灞斤躬閺佹劖寰勬繝鍐┬氶梻渚€鈧偛鑻晶顖炴煏閸パ冾伃妤犵偞甯￠獮瀣攽閸愩劋澹曢悷婊呭鐢帒效閸欏浜滈柟鐑樺灥椤忣亪鏌ｉ幘瀵告创闁诡喗锕㈤幃娆愶紣濠靛棙顔勫┑鐘殿暯閳ь剛鍋ㄩ崑銏ゆ煛鐏炵晫肖闁瑰弶鎸冲畷鐔碱敃閵堝嫮绀夐梺璇叉唉椤煤閺嵮呮殾妞ゆ帒瀚ч埀顒佹瀹曟﹢顢旈崨顓犲酱闂傚倸顭崑鎺楀储婵傛潌澶婎潩閼哥鎷绘繛杈剧秬濡嫰宕ヨぐ鎺撶厱闁绘ê鍟挎慨鍫㈢磼閺冨倸鏋旈柍褜鍓ㄧ紞鍡涘窗閺嶎厼绀勯柣妯碱暯閸嬫捇鐛崹顔煎濡炪倧缂氶崡鎶藉箖閿熺姴鍗抽柕蹇ョ磿閸橆亝绻濋姀锝呯厫缂佸鎹囧畷姘跺级鎼存挻鏂€闂佹寧绋戠€氱兘鎮炴ィ鍐╊梿濠㈣泛顑囩弧鈧繝鐢靛Т閸婃悂顢旈锔界厽妞ゆ挾鍠庡ù顕€鏌″畝瀣М妤犵偞鐟╁畷姗€濡搁妶鍛€抽梺璇叉唉椤煤閺嶎厽鍋夐柛蹇涙？缁诲棙鎱ㄥ┑鍡欑劸婵℃彃鍢查埞鎴﹀煡閸℃ぞ绨梺鍝勬噽婵挳锝炶箛娑欐優閻熸瑥瀚弸鍌炴⒑閸涘﹥澶勯柛妯煎帶椤曪綁濡歌绾捐棄霉閿濆懏鎯堥弽锟犳⒑缂佹﹩娈樺┑顔芥尦椤㈡岸鏁愰崱娆戠槇濠殿喗锕╅崢鍏肩濠婂懐纾奸柣鎰靛墮椤庢粌顪冪€涙ɑ鍊愮€殿喗鐓￠崺锟犲礃椤忓棴绱冲┑鐐舵彧缁茶棄锕㈤柆宥呯叀濠㈣泛顑冩禍婊堟煙鐎涙绠栭柛鐘愁焽閳ь剝顫夊ú妯兼崲閸繄鏆︽い鎰剁畱鍞悷婊冪箻閺佸秴鈹戦崶鈺冾啎闁哄鐗嗘晶浠嬪礆娴煎瓨鐓欑痪鏉垮船娴滄繈鏌ｅΔ鈧柊锝咁潖缂佹ɑ濯撮柛婵嗗婵箓姊洪崫鍕櫝闁哄懐濮撮悾鐤亹閹烘垿鍞堕梺鍝勬川閸犲孩绂掗幒鎴富闁靛牆妫欓埛鎺楁煃瀹勬壆澧曟い顓炴喘婵℃悂鍩￠崒婊冨笚闁荤喐绮嶇划鎾崇暦濠婂啠鏋庨柟鐐綑娴犲ジ鎮楅悷鏉款伃闁稿锕幃锟犲Ψ閳哄倻鍘遍梺鍝勬储閸斿矂鐛鈧弻鐔兼惞椤愩倗鐤勫┑顔硷攻濡炰粙鐛弽顓熷€烽柟缁樺笒铻氶梻鍌欑閹测€趁洪敃鍌氱婵鍩栭崕濠囨煛閸愶絽浜剧紓浣虹帛缁诲牓骞冩禒瀣棃婵炵缈伴崕鏌ュΦ閸曨垱鏅查幖绮瑰墲閻忔挸鈹戦垾鍐茬骇闁告梹鐟ラ锝夊箻椤旂⒈娼婇梺缁橆焽椤ｎ喚妲愰柆宥嗏拻濞达絼璀﹂弨浼存煙濞茶绨界紒顔碱煼楠炲鎮╁顔筋棥闁荤喐绮庢晶妤冩暜濡ゅ懏鍋傛繛鎴炲焹閸嬫捇鐛崹顔煎婵°倗濮撮幉锛勭矉瀹ュ應鏀介悗锝庡亞閸樻悂姊虹化鏇炲⒉妞ゎ厼娲幆宀勫箳濡や胶鍘搁悗鍏夊亾閻庯綆鍓涜ⅵ婵°倗濮烽崑娑樏洪顫偓浣肝旀担鐟邦€撻梺鑽ゅ枑濠㈡ɑ绔熷鍥╃＝闁稿本鐟ㄩ崗宀勬煕鐎ｎ偅宕岀€规洘娲熼獮搴ｆ喆閿濆倸浜鹃柨鏇炲€归崐濠氭煢濡警妲奸柟鑺ユ礋濮婃椽宕崟顒€鍋嶉梺鎼炲妼缂嶅﹪寮荤€ｎ喖鐐婇柕濞у懐妲囬梻鍌氬€搁悧濠勭矙閹烘梻鐭堥柍鍝勫€风换鍡樸亜閹板墎鎮奸柕鍡樺笧缁?"
        if mode == "direct":
            return "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡▎鎴犫敍闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼宕滆绾惧ジ鏌ｅΟ鎸庣彧閻忓浚鍙冮弻锝夋晲婢跺鏆犵紓浣芥閺咁偆鍒掑▎鎴炲珰濞ｅ洤宕俊浠嬫煏閸パ冾伃鐎殿噮鍣ｅ畷鍫曗€栭鑺ュ鞍缂佺粯鐩畷銊╊敇閻樻祴鍙烘繝娈垮枛閿曪妇鍒掗鐐茬闁告稑鐡ㄩ幆鐐搭殽閻愯尙姘ㄩ柛瀣尰缁绘繈宕堕妸褍骞堥梻浣筋潐閸庢娊顢氶鐘典笉婵☆垵鍋愮壕鍏笺亜閺冨倹娅曢柟鍐叉处椤ㄣ儵鎮欓弶鎴犵懆闁剧粯鐗犻弻宥堫檨闁告挾鍠庨悾鐑藉Ψ閵婏絼姹楅梺鍦劋閹告悂鍩€椤掆偓閻栧ジ寮婚敐澶婄疀妞ゆ牗绋撻妴鎰版⒑鐎圭媭鍤欑紒缁橈耿瀵鏁撻悩鑼槰闂侀潧臎閸愮偓婢戦梻鍌欑閹碱偊骞婅箛娑欏亗闁跨喓濮撮拑鐔哥箾閹寸們姘ｉ崼銉︾厱婵°倕鍟禒婊呯磼閻樺弶鎯堥柍瑙勫灴閹瑩鎳犻鈧·鈧梻浣虹帛閹告挳鍩€椤掍礁澧繛鍏肩墵閺屟嗙疀閹剧纭€闂佹椿鍘介悷锔炬崲濞戙垹骞㈡俊顖氭惈婵垽姊洪崨濠冩儎闁告挾鍠庨～蹇撁洪鍕炊闂佸憡娲﹂崜娆忊枍閵堝洨纾藉〒姘搐閺嬬喖鏌熼崫銉у笡缂佸矁椴哥换婵嬪炊閵娿儰缂撶紓鍌欑椤戝牆鈻旈弴鈶哄洭寮跺▎鐐瘜闂侀潧鐗嗗Λ娑欐櫠椤掍焦鍙忔俊顖滎焾婵倹銇勯姀锛勬噭缂佺粯绻堝畷鍫曞Ω閵夈垹浜鹃柛顭戝亽濞堜粙鏌ｉ幇顖氱毢濞寸姰鍨介弻娑㈠籍閳ь剙鐣濋幖浣歌摕闁挎繂鎲橀弮鍫濈劦妞ゆ巻鍋撻摶鐐寸節闂堟稒顥犻柡鍡畵閺屾洝绠涚€ｎ亖鍋撻弴銏″€堕柟鎯板Г閻撴瑥螞妫颁浇鍏岄柛鏂跨Ч閹妫冨☉姘卞姱濠殿喖锕ュ钘壩涢崘銊㈡婵﹩鍓﹂弳顐︽⒒娴ｄ警鐒鹃柨鏇畵楠炲﹪骞樼拠鑼幒閻庡箍鍎遍ˇ顖炴倷婵犲啨浜滈柟鍝勭Х閸忓矂鏌涘鈧禍璺何涢崨鎼晝闁靛繆鈧剚妲辨繝纰樻閸嬪懘宕归崸妤€绠犻柟鎹愬煐瀹曞鏌曟繛鍨仼濞存粎鍋撶换娑㈠醇濠靛牅铏庨梺鍝勵儐缁嬫帡濡甸崟顖ｆ晣闁绘劕寮朵簺婵＄偑鍊栧ú鈺冪礊娓氣偓閻涱喖顫滈埀顒勩€佸▎鎾村癄濠㈣泛顦遍惄搴㈢節绾板纾块柛瀣洴椤㈡牠宕ㄩ鐓庣秺閹粓鎳為妷銉ょ钵婵＄偑鍊栧ú宥夊磻閹惧瓨鍙忓┑鐘插鐢盯鏌熷畡鐗堝櫧缂侇喗鐟ラ埢搴ㄦ倷椤掑顥旈梻鍌氬€烽懗鍫曗€﹂崼銉晞闁告稒娼欑粻鐘绘煙閻楀牊绶茬紒鐘崇叀閺屾洝绠涚€ｎ亖鍋撻弴鐘差棜闁稿繗鍋愮粻楣冩煙鐎电浠ч柟鍐插暟閳ь剚顔栭崰鏍ь焽閳ユ剚娼栨繛宸簻娴肩娀鏌涢弴銊ュ闁稿绉瑰娲箹閻愭彃顬夊┑锛勫仒缁瑥鐣烽崫鍕ㄦ闁靛繒濮烽娲⒑缂佹﹩鐒介柡浣规倐閺佸秴顭ㄩ崼鐔哄幗闁瑰吋鎯岄崹宕囩矓闂堟耽鐟邦煥閸曨厾鐓夐梺璇″灠閸熸挳寮幘缁樺亹鐎规洖娲ら獮鍫ユ⒒娴ｅ憡鎯堥柛鐕佸亰瀹曟劙骞栨担绋垮殤濠电偞鍨崹娲偂濞戙垺鍊堕柣鎰問閻掓儳顭胯閻擄繝寮婚悢椋庢殝闁绘鐗嗗▓妤呮倵鐟欏嫭绀冪紒顔芥崌楠炲﹪鎮╁ú缁樻櫌闂侀€炲苯澧存鐐插暣楠炲鏁傞悾灞藉箺闂佺懓鍚嬮悾顏堝春閸曨垰鐤煫鍥ㄧ⊕閻撴洟鏌ｅΟ铏癸紞婵炴彃鐡ㄩ妵鍕閳ヨ弓瀛╁銈忕畱缂嶅﹪寮诲☉銏犵厴闁割煈鍠栨慨鏇㈡倵閸偅绶查悗姘嵆閻涱噣宕堕澶嬫櫌婵犮垼娉涢鍥╃矓闁秵鈷掗柛灞剧懆閸忓瞼绱掗鍛仴闁圭瓔鍋勯—鍐Χ閸℃ǚ鎷归梺缁橆殘婵挳鎮鹃悜绛嬫晢闁告洦鍓欓埀顒傜帛娣囧﹪顢涘┑鍡曟睏闂佷紮绠戦悧鎾愁潖閸濆嫅褔宕惰娴煎牆鈹戦悙鏉垮皟闁搞儜鍛箳闂備礁澹婇崑鍡涘窗閹惧墎涓嶉柟顖ｇ亹瑜版帗鏅查柛娑卞幗濮ｆ劙姊洪崨濠勵暡闁挎岸鏌嶉挊澶樻█濠殿喒鍋撻梺缁橆焽閺佺顭囨径鎰拻濞达絼璀﹂悞楣冩煛閸偄澧伴柟骞垮灲瀹曟帒顫濇潏銊ф濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊閵堝棙閿梺鍝勵儏閻楀繘鍩€椤掆偓缁犲秹宕曢柆宓ュ洭顢涘鍐炬婵犵數濮电喊宥夋偂閸愵喗鐓冮弶鐐村椤︼箓鏌￠崱娆忔灁缂佽鲸甯￠崺锕傚焵椤掑嫬纾婚柟鐐灱閺€浠嬫煟濡櫣浠涢柡鍡忔櫅閳规垿顢欓懞銉ュ攭閻庤娲橀崝娆撶嵁閺嶃劎鐟归柛銉ｅ妽濞呭棝姊绘担绋挎毐闁圭⒈鍋婇獮濠冩償閿濆洣绗夊┑顔筋焾閸╂牠鎮￠悢鍏肩厸闁稿本姘ㄦ禒銏ゆ煙椤旇棄鐏撮柡灞界Ч閺屻劎鈧綆浜炴导宀勬⒑閸濆嫭婀扮紒瀣灴閸┿儲寰勬繝搴㈠缓闂佸壊鍋嗛崳銉╁汲椤撶姷纾介柛灞剧懅椤︼箓鏌ｉ弽褍鎮戠紒鍌氱Ч瀹曞ジ寮撮悙鑸垫啺婵犵數鍋為崹顖炲垂濞差亜纾婚柟閭﹀枓閸嬫挾鎲撮崟顒傤槬濠电偛鐪伴崐婵嬪春濞戞鏆嗛柛鏇ㄥ厴閹锋椽鏌ｉ悩鍙夌闁逞屽墲濞呮洟鎮橀幘缁樷拺閺夌偞澹嗛ˇ锔姐亜椤撶姴鍘撮柟顔诲嵆椤㈡瑧鍠婇崡鐐村€┑鐘灱閸╂牞鎽梺鍝勬噳閺呯姴顫忓ú顏勫窛濠电姴鍟惁鐑芥倵楠炲灝鍔氭繛宸幖铻炵€瑰嫭澹嬮弨浠嬫煟濡櫣浠涢柡鍡忔櫊閺屾稓鈧綆鍓欐禒杈殽閻愭潙濮堢紒缁樼箓椤繈顢橀悙瀵告澖闂傚倷娴囬鏍垂婵傚憡鍊堕柟閭﹀劒濞差亶鏁傞柛鏇炴睘閸愬墽鍞甸柣鐘烘鐏忋劌顔忛妷鈺傜厱闁靛牆妫楅悘銉╂煃鐟欏嫬鐏撮柟顔界懇瀵爼骞嬮悩杈ㄥ煕闂傚倷鐒﹂幃鍫曞礉瀹ュ拋娓诲ù鐘差儏缁犳牠鏌ㄩ悢鍝勑㈤柛妤佸▕閺岋綁寮崹顕呮殺缂備胶濮甸懝楣冣€旈崘顔嘉ч柛鈩冪懃椤呯磽娴ｇ瓔鍤欓柛濠傜仢閻ｇ兘濡烽妸锝勬睏闂佸湱鍎ら幐楣冨储閽樺娓婚柕鍫濇鐏忕敻鏌涢悩鍙夋崳缂侇噮鍙€椤﹀綊鏌＄仦鐣屝ユい褌绶氶弻娑㈠箻鐎靛摜鐤勯梺鎸庣箘閸嬬偛顕ラ崟顒傜闁圭儤鍨堕幆鍫熴亜椤愶絿鐭掗柛鈹惧亾濡炪倖宸婚崑鎾绘煟閿濆洦鐒块柕鍥ㄥ姍楠炴帡骞嬮敂鑺ユ當濠电姴鐥夐弶搴撳亾閺囥垹鐤い鎰╁€楅惌鍫ユ煥閺囨浜鹃梺瀹狀潐閸ㄥ潡銆佸▎鎰弿闁归偊浜為幑鏇㈡⒒娴ｄ警鐒炬い鎴濇楠炴劖绻濆銉㈠亾閸愵喖唯闁冲搫鍊搁埀顒傚厴閺屾稑鈻庤箛锝喰﹀銈忚吂閺呯姴顫忓ú顏呭仭闁哄瀵т簺闂備胶顢婂▍鏇㈡晪闂佷紮绲块崗姗€銆侀弴銏℃櫇闁逞屽墰缁牏鈧綆鍋佹禍婊堟煙閺夊灝顣崇紒澶樺墰缁辨帡鐓幓鎺斾紙濠殿喖锕ら…宄扮暦閹烘埈娼╂い鎴ｆ娴滈箖鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻濞戔懞鍥偨缁嬪灝鐎梺鍛婃寙閸曨剙鍔氬┑鐐舵彧缂嶁偓妞ゎ偄顦垫俊闈涒攽鐎ｎ偆鍘告繛杈剧悼椤牓寮抽敐鍥ｅ亾鐟欏嫭绀冮悽顖涘浮閿濈偛鈹戦崶鑸电稇闂佸搫绉查崜閬嶅Χ閸涱亝鏂€闂佺粯蓱閸撴岸宕箛娑欑厱闁绘ɑ鍓氬▓婊堟煛娴ｇ鏆ｉ柛鈺嬬節瀹曘劑顢橀悪鍛惞闂傚倷鑳剁划顖炲垂閻撳宫娑㈠礋椤撶姳绗夐梺瑙勫劶婵倝鎮″▎鎾寸厵妞ゆ牕妫楅幏鎴犳閻愮數纾藉ù锝囨嚀婵鏌涚€ｃ劌鈧繂顕ｆ繝姘櫜闁糕剝锚閸斿懎顪冮妶鍡欏缂侇喖瀛╅悧搴ㄦ⒒閸屾瑧顦﹂柟璇х節楠炴劖绻濆顓炲壆濡炪倖鐗滈崑娑氱不濮橆兙鈧帒顫濋敐鍛闁诲氦顫夊ú鏍Χ閸涘﹣绻嗛柣鎴ｅГ閺呮粓鎮峰▎蹇擃仼妞ゅ繑妞藉濠氬磼濞嗘帒鍘″銈庡幖閻楁挸顕ｉ悽鍓叉晢闁逞屽墴閿濈偛鈹戠€ｎ€晠鏌ㄩ弮鍥撻柣婵嗗槻閳规垿鎮欓弶鎴犱桓濠殿喗菧閸斿孩绔熼弴鐔洪檮闁告稑锕ら埀顒傛暬閺屻劌鈹戦崱娑扁偓妤€霉濠婂嫮鐭掗柡宀嬬秬缁犳盯寮埀顒備焊閿曞倹鐓涢悘鐐插⒔濞叉挳鏌涢埡鍐ㄤ槐妤犵偛妫滈ˇ鍗烆熆鐟欏嫭绀€闁宠鍨块弫宥夊礋椤愨剝婢€闂備胶顭堥敃銉╂偋閺囥埄鏁婇煫鍥ㄦ⒒缁♀偓濠殿喗锕╅崜娑㈡晬濞戙垺鈷戦悷娆忓閸斻倕顭胯濞撮攱绔熼弴銏″仼閻忕偟顭堟禍鐐殽閻愯尙浠㈤柛鏃€宀搁弻鐔兼煥鐎ｎ亞浠村銈嗘煥缁绘ɑ淇婇悜钘夌厸闁稿本绮岄獮妤呮⒒娴ｇ懓顕滅紒璇插€哥叅闁靛牆顦崒銊╂煙缂併垹鏋熼柣鎾寸懄閵囧嫰寮埀顒勫磿閹惰棄鍌ㄩ悗娑欙供濞堜粙鏌ｉ幇顖氱毢閺佸牓姊洪崷顓炲付缂傚秴锕妴渚€寮撮姀鈩冩珳闂佺硶鍓濋…鍥╂暜閸℃稒鈷掗柛灞捐壘閳ь剚鎮傚畷鎰槹鎼达絿鐒兼繛杈剧到濠€閬嶆偟鐠鸿　鏀介柣妯哄级閹兼劗鐥幆褜鐓奸柡宀€鍠栭獮鎴﹀箛椤撶姰鈧劗绱撴担鐣屽牚闁稿﹥绻堝濠氭晝閳ь剝鐏掓繛鎾村嚬閸ㄨ鲸顨欏┑鐘愁問閸ｎ垳寰婃禒瀣亱闁圭偓鍓氬鏍р攽閻樺疇澹樼痪鎯у悑閹便劌顫滈崱妤€骞嬮梺绋款儐閹告悂鎮鹃敓鐘茬疇濠电姴鍊荤粔铏光偓瑙勬礃閸庡ジ藝椤曗偓閺岋紕鈧綆鍋嗘晶鐢告煛瀹€瀣瘈鐎规洖鐖兼俊鐑藉Ψ瑜岄幃锝囩磽閸屾瑧鍔嶉柛鏃€鐗犻妴鍐╃節閸パ嗘憰闂佺粯姊婚崢褏绮诲杈ㄥ枑闊洦绋戠粻娲煟濡偐甯涢柣鎾存礃缁绘盯宕卞Δ鍐唺缂備胶濮撮…鐑藉蓟閳ュ磭鏆嗛柍褜鍓熷畷浼村箻閼告娼熼梺鍦劋椤ㄥ懘锝為崨瀛樼厽婵☆垵娅ｉ敍宥吤瑰鍐煟婵﹦绮幏鍛瑹椤栨粌濮奸梻浣瑰濞插繘宕愬┑瀣畺闁靛濡囬梽鍕磼鐎ｎ厼鍔甸柟鑺ユ礋閹嘲顭ㄩ崟顐や患缂備緡鍠涢褔鍩ユ径鎰潊闁斥晛鍟悵鎶芥⒒娴ｅ憡鍟炲〒姘殜瀹曟粌鈽夐姀鐘崇€梺鍝勭▉閸嬪棛澹曟禒瀣厱閻忕偛澧介幊鍡樸亜閺傛妲瑰ǎ鍥э躬閹亜鈻庤箛鏃€鎮欑紒鐐劤椤兘寮婚悢鐓庣鐟滃繒鏁☉銏＄厓闂佸灝顑呯粭鎺楁婢舵劖鐓ユ繝闈涙缁佲晠鏌ｉ幒鏂夸壕闁靛洤瀚版俊鐑藉Ψ瑜忛鎺楁⒑閸濆嫮鐒跨紓宥勭窔閻涱喖螣閾忚娈鹃梺鎼炲劀閳ь剟宕ｅú顏呯厽閹兼番鍊ゅ鎰箾閸欏鑰跨€规洖缍婂畷褰掝敊閻愵剚顔曢梻渚€娼ц墝闁哄應鏅犲顐㈩吋閸℃瑧顔曢梺绯曞墲閿氶柣蹇嬪劚椤儻顦圭紒鐘崇墪椤繒绱掑Ο璇差€撻梺闈╁瘜閸樹粙鎳ｉ崶顒佲拺闁硅偐鍋涙俊鍏笺亜椤撶偛妲绘い鏇秮椤㈡洟鏁冮埀顒佸閻樼粯鐓忓璺虹墕閸斿瓨淇婇锝囩煁缂佺粯绻堝Λ鍐ㄢ槈濡嘲浜鹃柟闂寸缁犵喖鏌ㄩ悢鍝勑ｉ柛瀣€块弻娑㈠箛閸忓摜鍑归梺鍝ュУ閸旀牜鎹㈠┑鍥╃瘈闁稿本绮岄。铏圭磽娴ｆ彃浜鹃梺鍓插亞閸犳劙宕ｈ箛鏃€鍙忔俊銈傚亾婵☆偅顨嗛弲鑸电節濮橆厾鍘遍梺闈涚墕濡厼鈻撳鍫熺厸閻忕偛澧藉ú瀵糕偓娈垮枟閹歌櫕淇婇幖浣肝ㄧ憸宀勫传濡ゅ啰纾介柛灞剧懆閸忓苯鈹戦鐐毄缂侇喗鐟╅獮鎺懳旈埀顒侇攰闂備礁鎲″ú锕傚垂閹殿喚涓嶅┑鐘崇閸嬶綁鏌ц箛姘兼綈缁剧虎浜弻鏇＄疀婵犲喚娼戝┑鐐茬墔缁瑩寮婚敐澶婄疀妞ゆ挾鍠庨崜鐟扳攽閻愯尙澧涚紒顔肩Ч楠炲牓濡搁敂鍓х槇闂佸憡娲﹂崢鑲╃箔閿熺姵鈷戦柣鐔告緲濡插鏌熼搹顐€顏堟偩閻戠瓔鏁冮柨鏇楀亾閸烆垶姊洪幐搴㈩棃闁轰緡鍣ｅ畷鎴﹀箻濞茬粯鏅╅柣蹇撶箲閻楁寮埀顒勬⒒娴ｈ鐏遍柡鍛洴瀹曨垶濡搁敂缁㈡祫闂佺粯顭囩划顖炴偂閺囥垺鐓涢柛鎰剁到娴滈箖姊洪幖鐐插婵炵》绻濋幃浼搭敊閻ｅ瞼鐦堥梺绋款儓婵倕螞閸愩劎鏆﹂柕濞炬櫓閺佸洭鏌曡箛鏇炐ｉ柡鍡╀邯濮婂宕掑▎鎴М闂佸湱鈷堥崑鍕弲闂侀潧艌閺呮稓澹曟繝姘厽闁哄啫鍊甸幏锟犳煛娴ｉ潻韬柡宀€鍠愬蹇斻偅閸愨晩鈧秹姊洪幎鑺ユ暠闁搞劌婀卞Σ鎰板箻鐎涙ê顎撻梺璋庡洦娅滅紒鍓佹暬濮婅櫣绱掑Ο铏诡儌闂佸搫鎷嬮崑鍡椢ｉ幇鏉跨婵°倕锕ラ弲顏堟⒑閸涘﹣绶遍柛妯煎亾缁傛帡骞栨担鐟扳偓鐢告偡濞嗗繐顏紒鈧崘顔界厱闁靛绠戦婊兦庨崶褝韬鐐寸墬閹峰懐鎲撮崟顒傚絾闂備礁鎼ˇ閬嶅磻閻愬鐝堕柛鈩冪⊕閸庡酣骞栧ǎ顒€濡介柍閿嬪笒闇夐柨婵嗘噺閸熺偤鏌熼姘卞ⅱ缂佽鲸甯楀鍕偓锝庡墮瀵劑鎮楃憴鍕缂佽鍟撮獮鍡涘籍閸惊鈺呮煏婢诡垰鍟粭宀勬⒒閸屾瑧顦﹂柟纰卞亜鐓ら柕蹇嬪€曢崹鍌涚箾瀹割喕绨荤痪鎯х秺閺屾盯顢曢敐鍡欘槶闂佸憡鐟﹂幑鍥蓟濞戙垹唯闁挎繂鎳庢慨搴ㄦ⒑閸涘﹥鈷愮痪鏉跨Ч婵＄敻宕熼姘卞幐婵犵數濮撮崐鎼佸煕鐎ｎ喗鈷戦柛婵嗗鐎氭壆绱掓径灞藉幋缁℃挸銆掑锝呬壕闂佸搫鏈惄顖炵嵁濡皷鍋撻棃娑欐喐闁汇倕瀚板娲箰鎼达絿鐣奸梺绋款儑閸嬫盯顢氶妷鈺佺妞ゆ帒鍊婚鏇㈡⒑閸︻厼鍔嬫い銊ョ墢濡叉劙骞嶉鍓э紲闂佺粯锚绾绢參鍩ユ径鎰厓闁芥ê顦藉Σ鎼佹懚閿濆洨妫柟宄扮焸閸濇椽宕幖浣光拻濞达絿鐡旈崵娆徫旈悩鍙夋喐缂侇喛顕ч鍏煎緞婵犲嫸绱甸梻浣告啞椤ㄥ牊瀵煎┑鍠㈡椽顢旈崨顔界彇闂備線鈧偛鑻晶鎾煙椤曗偓缁犳牠骞冨鍫熷癄濠㈣泛鐬奸崢顒€鈹戦悩顔肩伇婵炲鐩幆澶嬬附閸涘﹤鍓ㄩ梺鍓插亖閸庢煡鍩涢幒妤佺厱閻忕偟鍋撻惃鎴濐熆瑜庣粙鎴﹀Υ閹烘埈娼╂い鎾楀嫮鏉归柣搴ゎ潐濞叉ê煤濠靛牏涓嶆繛鎴欏灩閸楄櫕淇婇妶鍌氫壕婵炲瓨绮撶粻鏍蓟閿濆鍋勯柛婵嗗閺嗩參姊洪崫銉ユ灁闁稿鍠撳Σ鎰板箳閺冣偓鐎氭岸鏌熺紒妯虹瑲婵炲牏绮换婵堝枈婢跺瞼锛熼梺杞版祰椤曆囨偩閻戣姤鍋勭痪鎷岄哺閺咁剙鈹戦鏂や緵闁告挻鐟╁顐﹀Χ婢跺鎷绘繛鎾村焹閸嬫挻绻涙担鍐叉礌閳ь剨绠撳畷濂稿Ψ閵壯嶇串婵犲痉鏉库偓鏇㈠疮椤栨氨鏆﹂柟缁樺础瑜版帗鏅查柛銉㈡杺閳ь剙锕弻锟犲焵椤掍胶顩烽悗锝庡亞閸樹粙姊鸿ぐ鎺戜喊闁搞劋鍗抽幆鍐倻濡寮块梺鎸庣箓濞层倖绂掗柆宥嗙厸鐎光偓鐎ｎ剛鐦堥悗瑙勬磸閸旀垿銆佸☉妯炴帞鎲楅妶鍛痪闂侀潧娲ょ€氫即銆侀弴銏狀潊闁靛繈鍩勯崬铏圭磽閸屾瑦绁板鏉戞憸閺侇噣骞掗弴鐘辫埅闂備浇宕垫慨鏉懨洪妶鍛傜喐绻濋崶褏鍔﹀銈嗗笂閻掞箑鐣风仦鐐弿濠电姴鎳忛鐘电磼鏉堛劌绗掗摶锝夋煣韫囨稈鍋撳☉娆樻晣闂傚倸鍊烽悞锔锯偓绗涘懎鏋堢€广儱娲﹀畷鍙夌箾閹存瑥鐏╅梺鍗炴处缁绘繈妫冨☉姘叡闂佸憡妫忛崹浼村煘閹达富鏁婄痪顓犲厴缁舵潙鈹戦悙鍙夊珔缂傚秳绶氬畷娲焵椤掍降浜滈柟鐑樺灥閳ь剙缍婇、鏃堟偄閸忓皷鎷婚梺鍛婃处閸嬪嫰顢旈埡鍌樹簻妞ゆ挾鍋熸禒銏ゆ懚閿濆洨纾藉ù锝咁潠椤忓嫷鍤曢柛褎顨嗛埛鎴犵磼鐎ｎ偄顕滄繝鈧弶娆剧唵閻熸瑥瀚粈瀣偓瑙勬礃閸ㄥ潡鐛鈧幊婊堟濞戞瑧鈧參姊绘担鍛婂暈婵炶绠撳畷婊冣槈閳跺搫娲、姗€濮€閳锯偓閹疯櫣绱掔紒銏犲箹闁瑰啿绻橀幃鐢割敂閸喓鍘甸梺鑽ゅ枔婢ф宕板Ο娲绘闁绘劖褰冮弳鐐烘煏閸剛绉€规洘锕㈤崺鈩冩媴閹绘帊澹曟繝鐢靛У绾板秹鎮￠姀鈥茬箚妞ゆ牗鐟ㄩ鐔镐繆閸欏銇濋柡灞剧⊕缁绘繈宕熼鈩冾潟婵犳鍠栭敃銉ヮ渻閽樺鏆︽慨妞诲亾鐎规洩绲惧鍕偓锝庝簻婢瑰秹姊婚崒娆戭槮闁硅姤绮嶉幈銊╂偨閸涘﹤娈為梺璇″瀻閸愵亗鍋掗梻鍌氬€风粈渚€骞夐敍鍕煓闁硅揪闄勯弲婵嬫煥閺冣偓閸庤櫕鎱ㄩ鍕厓鐟滄粓宕滃☉姘潟闁圭儤顨呯粈鍫㈡喐瀹ュ鈧倹绺介崨濠傜彅闁哄鐗勯崝濠冪濠婂嫨浜滈柟鏉跨仛缁舵盯妫呴澶婂⒋闁哄矉绱曟禒锕傚礈瑜庨崚娑欑節绾版ê澧查柟顔煎€规穱濠囨倻閽樺）銊╂煏婵炲灝鍔ら柛妯绘綑閳规垿鏁嶉崟顐℃澀闂佺顭堥崐鏍矉瀹ュ拋鐓ラ柛顐ｇ箘閺屽牓姊洪崫鍕垫Ч闁搞劌缍婂鎶芥晜閻愵剙鏋戦梺缁橆殔閻楀棙绌遍鐐寸厸濞达綁娼婚煬顒勬煙椤旂厧妲婚柍璇叉唉缁犳盯骞欓崘褏纾绘繝鐢靛仜閻°劎鍒掑澶嬪亱闁绘ê妯婂鏍磽娴ｈ偂鎴炲垔閺夋埈娓婚悗锝庝簽閸戝綊鎮烽弴鐐搭棤缂佽鲸鎸婚幏鍛存寠婢跺孩鏆卞┑鐘愁問閸犳捇宕愰弴銏╂晪闁靛鏅涚粈瀣亜閺嶃劍鐨戦柛濠勫仜椤啴濡堕崱妤€娼戦梺绋款儐閹搁箖鎯€椤忓牆绠氱憸婊堟偂婵傚憡鐓涚€光偓閳ь剟宕伴弽顓犲祦闁硅揪绠戠粻娑㈡⒒閸喓鈯曟い鏂垮缁辨捇宕掑▎鎺濆敼闂佺顑嗛幑鍥蓟濞戞矮娌柟顖嗗啯鐦撻梻浣虹帛閺屻劌螞濠靛绠栫憸鐗堝笚閹偤鏌ｉ悢绋款棆婵炲牄鍊曢埞鎴︻敊绾攱鏁惧銈冨妼閹虫﹢鍨鹃敂鐐磯闁靛绠戦弸鍌炴⒑閸涘﹥澶勯柛鎾寸洴钘濋柡澶婄氨閺€鑺ャ亜閺冨倶鈧宕濋悢铏圭＜妞ゆ洖鎳庨悘锔筋殽閻愯尙绠荤€规洏鍔戝鍫曞箣濠靛牏宕烘繝鐢靛Х閺佸憡鎱ㄩ幘顔肩９闁荤喐澹嬮弸鏃€鎱ㄥ璇蹭壕濠殿喖锕︾划顖炲箯閸涙潙宸濆┑鐘插€瑰▓妯荤節绾版ɑ顫婇柛瀣嚇瀹曞綊宕归鍛稁婵炲濮撮鍛矆鐎ｎ偁浜滈柟鎹愭硾鍟搁梺缁樺笒濞硷繝骞冨Δ鍛祦闁割煈鍠栨慨搴ㄦ⒑閻熸澘鏆辨い锕傛涧椤曪綁濡搁敂缁㈡祫闁诲函缍嗛崑鍕焵椤掑倹鏆柡灞诲妼閳规垿宕卞Ο鐑橆仩婵＄偑鍊х徊鐣屽椤撶姵顫曢柟鐑樻煛閸嬫捇鏁愭惔婵堟晼缂備胶濮撮…鐑藉蓟閻旂⒈鏁婄紒娑橆儐閻や線姊虹紒妯圭繁闁革綇绲介悾鐤亹閹烘繃鏅╅梺缁樻尭鐎垫帒顭囧☉妯锋斀闁绘ɑ顔栭弳顖涗繆閹绘帗鍤囩€规洘鍨垮畷銊╊敍濠婂懐鍘梻浣筋潐瀹曟ê鈻斿☉銏犲瀭婵犻潧鐗忕壕钘壝归敐澶樷偓鍥ь煥閸繄锛涢梺鍛婄☉閻°劑鎮￠弴銏＄厵闁煎壊鍓欐俊鑺ョ箾閸涱厽鍤囬柡灞界Х椤т線鏌涢幘瀵告噰闁诡喗锚椤繃娼忛妸銉ョ哎婵犵數鍋為崹顖炲垂閸︻厾涓嶉柨婵嗩槹閻撶喖鏌熼柇锕€澧板ù鐘崇洴閺屾盯鏁愰崟顓犵厯濠殿喖锕ㄥ▍锝囨閹烘嚦鐔兼惞閸︻厽鍟扮紓鍌氬€风欢锟犲窗濡ゅ懏鍋￠柍杞扮贰閸ゆ洖鈹戦悩宕囶暡闁哄懏褰冮…鍧楁嚋閻亝鍨垮鏌ユ晲婢跺鎷虹紓鍌欑劍閿氶柣蹇嬪劜缁绘稓鎷犺閻ｇ數鈧鍣崑濠囧箖濞嗘搩鏁嗛柛灞剧矤閸熷酣姊绘担鐟邦嚋缂佽鍊块獮濠呯疀濞戞顔愰梺瑙勫婢ф鎮￠妷鈺傜厸闁搞儯鍎辨俊娲⒑椤撗冪仸闁哄本娲熷畷閬嶅即閻樼數宕查柣搴㈩問閸犳骞愰搹顐ｅ弿闁逞屽墴閺屽秹鍩℃担鍛婃闂佺粯绻冩繛濠傤潖缂佹ɑ濯撮柧蹇撶畭閳ь剙锕弻宥堫檨闁告挻鐟ф竟鏇㈩敇閻樺吀绗夐梺鍝勮閸庢煡宕愰崹顐ｅ弿婵妫楁禍鐐烘煟椤撶喓鎳勯柟渚垮妽缁绘繈宕熼鐐殿偧闂備胶鎳撻崲鏌ュ箠濡櫣鏆﹂柕濠忓缁♀偓闂佺鏈粙鎺楁偩婵傚憡鈷掑ù锝呮贡濠€浠嬫煕閳轰礁顏€规洖缍婇弻鍡楊吋閸愶絽浜鹃柛鎰靛枛闁卞洭鏌曟径鍫濆姕闁诲寒鍓欓—鍐Χ閸℃锛曢梺绋款儐閹瑰洭寮诲☉銏犖╅柨鏇楀亾闁告柣鍊濋弻锝夋晲閸パ冨箣閻庤娲栭悥鍏间繆閹间焦鏅滈悹鍥у级濞呮绻濋悽闈浶ラ柡浣告啞缁绘盯鍩€椤掍胶绠惧ù锝呭暱濞层倗澹曡ぐ鎺撶厵闂傚倸顕ˇ锔剧磼閻橀潧鏋涢柡灞诲姂閹垽宕崟鎴欏灮閻ヮ亪骞嗚閻撳ジ鏌＄仦鍓ф创鐎殿喗鎸虫俊鎼佸Ψ瑜岄悽濠氭⒒娴ｄ警鐒炬い鎴濇处閹便劑鎮介崹顐㈠簥濠电偞鍨崹鍦不閿濆鐓熼柟閭﹀灠閻ㄦ椽鏌ｉ悢鏉戝缂佺粯绻堥崺娑㈠焵椤掑嫬绀嬫い鎾跺仜缂佲晠姊绘担鍛婃儓闁活厼顦辩槐鐐哄焵椤掑倻纾奸柣妯虹－濞插瓨顨ラ悙杈捐€挎鐐寸墵椤㈡﹢鎮ら崒婊咁槯濠电姷鏁告慨鐢割敊閺嶎厼绐楅柡宥庡幗閺呮繈鏌ㄩ弮鈧崕鎶藉垂濠靛洢浜滈柡宥庡亜娴犳粎绱掗悪鈧崹鍫曞蓟濞戞ǚ妲堥柛妤冨仧娴狀垶姊哄ú璇插箺闁荤噦濡囬幑銏犫槈閵忕姴鑰垮┑鐐叉缁诲绔熼弴鐑嗘富闁靛牆鍟崝婊堟煕閵娿儳浠㈡い顐㈢箳缁辨帒螣鐠囧樊鈧挻绻涢幘鏉戝毈闁搞劍濞婂畷婵堢矙濞嗙偓瀵岄梺闈涚墕濡鎮橀妷鈺傚€垫慨妯煎帶閺嬫盯鏌嶇拠鏌ュ弰濠殿喒鍋撻梺缁樼憿閸嬫挻绻涚亸鏍ㄦ珕闁靛洤瀚伴獮鎺楀箣濠靛啫浜鹃柣鐔稿閺嬫柨螖閿濆懎鏆為柍閿嬪灴濮婂宕煎顓熺彅闂佷紮闄勭划鎾诲蓟濞戞鐔煎礂閸忚偐褰ч梻渚€鈧偛鑻晶顖滅棯閺夎法肖闁哥姴锕ら濂稿炊閵娿儱绨ユ繝鐢靛仦閸垶宕归崷顓犳／鐟滄棃寮婚悢鐓庣妞ゆ挾鍋涚粻褰掓⒑閸涘﹥宕屽ù婊嗘硾椤繘鎼圭憴鍕彴闂佽偐鈷堥崜娑㈩敊閸ヮ剚鈷戦柛婵勫劚閺嬫垶绻涢崗鑲╂噰闁挎繄鍋犵粻娑㈠箻娴ｈ銇濇い銏℃瀹曨亝鎷呯拠鈩冾棃婵犵數濮烽弫鎼佸磻閻愬搫鍨傞悹杞拌濞尖晠鏌曟繛鐐珕闁稿浜弻娑㈠即閵娿儳浠梺鎶芥敱閸ㄥ湱妲愰幒鏂哄亾閿濆簼绨婚柣顭掔節閺岋繝鍩€椤掍胶绡€婵﹩鍘鹃崢钘夆攽鎺抽崐鏇㈠疮椤愶箑鐓濋柛顐ゅ櫏濞堜粙鏌ｉ幇顓炵祷闁哄棴缍侀弻娑㈠Ω閳哄啰鏆悗娈垮櫘閸撶喐淇婇悜鑺ユ櫆缂備焦顭囩粔楣冩⒒閸屾艾鈧娆㈠顒夌劷鐟滃繘骞戦姀銈呭耿婵炴垶顭囬崝锕€顪冮妶鍡楃瑐闁绘帪绠撻幃姗€鏌嗗鍡欏幈闁诲函缍嗛崑鍛暦瀹€鍕厵妞ゆ棁宕甸惌娆戔偓瑙勬磸閸斿秶鎹㈠┑瀣妞ゆ劑鍨烘潏鍫熺節閻㈤潧啸闁轰礁鎲＄换娑㈠焵椤掍胶绠惧ù锝呭暱閸氭ê鈽夊Ο閿嬫杸闁诲函绲介悘姘跺疾濞戞ǚ鏀介幒鎶藉磹閹版澘纾婚柟鍓х帛椤ュ棗顭跨捄渚剳缂佲檧鍋撳┑鐘垫暩婵挳宕愯ぐ鎺戦棷闁荤喐鍣磋ぐ鎺撳亹閻犱浇娅曢崰姘舵⒑閸濆嫬顦柍褜鍓欑壕顓㈠汲閸℃稒鍊甸柨婵嗛婢ь噣鏌涢埡浣藉妞ゎ亜鍟存俊鑸垫償閳ュ磭顔夐梻浣告啞濮婂綊宕归悽鍛婂仼闁绘垼妫勭涵鈧梺缁樺姇缁夐潧螞閸愵喖鏄ラ柍褜鍓氶妵鍕箳閹存繍浠肩紓浣哄У瀹€鎼佸蓟閿濆绠涙い鏃囧Г濮ｅ嫮绱掗悙顒€绀冩俊顐㈠濠€渚€姊洪幐搴ｇ畵閻庢凹鍣ｉ幆灞解枎閹惧鍘卞┑鐘绘涧濞诧箓濡靛┑瀣厵妞ゆ棁宕甸惌娆愩亜閵忥紕鈽夐柍钘夘槹濞煎繘濡歌濞堣棄鈹戦敍鍕杭闁稿鍊濆畷銏ゆ偂楠炵喐妞介崺锟犲礃椤忓啰鐟濇繝鐢靛仦閸ㄦ儼褰滃┑鈩冨絻閻楀﹥绌辨繝鍥舵晬婵炴垶锕╁Λ婊堟⒑閸濆嫭鍣虹紒璇茬墦閻涱喗寰勬繝搴㈡〃閻庡厜鍋撻柍褜鍓熼幃鍧楀焵椤掆偓閳规垿鎮欓弶鎴犱桓闂佽崵鍠嗛崕鑼矉閹烘挶鍋呴柛鎰ㄦ杹閹锋椽姊洪崨濠勨槈闁挎洏鍎插鍕礋椤栨稓鍘辨繝鐢靛Т鐎氼剟鍩㈤崼鈶╁亾濞堝灝娅橀柛锝忕到閻ｉ攱绺介崨濠備簻闂佺偓鑹鹃崐褰掓儓韫囨稒鈷掗柛灞捐壘閳ь剚鎮傚畷鎰板箹娴ｇ懓浜辨繝鐢靛Т鐎氼噣鎯屽▎鎾寸厵闂侇叏绠戦弸娑㈡煕閵婏妇绠為柟顔款潐濞碱亪骞忓畝濠傚Τ婵犵數鍋為幐鎼佲€﹂悜钘夎摕闁哄洢鍨归柋鍥ㄧ節闂堟稒绁╂俊顐ゅ仱濮婅櫣鎷犻懠顒傜杽闂佺瀛╅悡鈩冧繆閻㈢绀嬫い鏍ㄧ⊕濞呭棝姊虹紒妯哄Е闁告挻鑹捐闁割偁鍎查埛鎴︽偣閸ワ絺鍋撻搹顐や簽闂備礁鎲￠〃鍡樼箾婵犲洤违濞达絿纭堕弸搴ㄦ煙閹屽殶闁告瑥妫楅—鍐Χ閸℃瑥顫ч梺娲诲弾閸犳绮╅悢鐓庡嵆闁靛繆妾ч幏娲⒑閸︻収鐒炬繛鎾棑缁骞橀崜浣猴紲闂侀潧顭堥崝灞剧瑜版帗鐓犳繛宸簷閹茬偓顨ラ悙杈捐€挎い銏＄懇閹墽浠﹂挊澶岊唶闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼顢涘鍛紲闂佺鏈粙鎴犵箔瑜旈弻宥堫檨闁告挶鍔庣槐鐐哄幢濞戞锛涢梺绯曞墲缁嬫垿宕掗妸鈺傗拺妞ゆ巻鍋撶紒澶屾暬閸╂盯骞嬮敂鐣屽幐闂佺鏈敋闁告梹绮嶇换娑㈠川椤撶喎娈楅梺鍝勬湰缁嬫垿鍩㈡惔銊ョ疀妞ゆ巻鍋撴い顐ｅ笒铻栭柣姗€娼ф禒婊勩亜閹存繍妯€鐎殿噮鍋婂畷鎺楁倷閺夋垹妾┑鐘灱濞夋盯藝娴兼潙鏄ユ繛鎴欏灪閳锋帡鏌涚仦鍓ф噮妞わ讣闄勭换婵嬪焵椤掑嫭鐒肩€广儱鎳愰敍鐔兼⒑闂堟稓澧曟い锔诲弮閸┾偓妞ゆ巻鍋撻柛鐔告綑閻ｇ兘宕￠悙鈺傤潔濠碘槅鍨抽崢褔鐛崼銉︹拻濞达絿鍎ら崵鈧銈嗘处閸欏啫鐣烽幋锔藉€烽柛婵嗗閻撴垿妫呴銏″缂佸甯￠幃锟犳偄閸忚偐鍘介梺鍝勫€圭€笛囧箚閸喆浜滈柨婵嗘噷閸嬨垽鏌″畝鈧崰鏍х暦濡ゅ懏鍋傞幖绮规濞兼岸姊绘担鍛婃儓闁活厼顦辩槐鐐寸瑹閳ь剟鎮伴鈧獮鎺懳旈埀顒傜不缂佹绠鹃柨婵嗛閸樻悂鏌ц箛鎾诲弰婵﹦绮幏鍛村川婵犲啫鍓甸梻浣告惈閻楁粓宕滈悢鐓庣畾闁告洦鍨奸弫宥嗙箾閹寸儐娈樼紒鐘冲哺濮婇缚銇愰幒鎿勭吹缂備讲鍋撳ù锝呮啞閺嗘粓姊婚崒娆戝妽閻庣瑳鍛床闁稿瞼鍋涚粻鐘碘偓骞垮劚椤︻垳绮堥崱娑欑厵闁绘垶锕╁▓鏇㈡煟閹捐泛鏋涙鐐寸墪鑿愭い鎺嗗亾闁逞屽厵閸婃洟鈥﹂崶顒€绠涙い鎾跺Х椤旀洟姊洪崨濠勬噧妞わ富鍨堕幃妯尖偓鐢电《閸嬫挾鎲撮崟顒傗敍缂備胶绮换鍌炴偩瀹勬嫈鐔哥瑹椤栨碍娅婃俊鐐€栭弻銊╁触鐎ｎ噮鏁囬柛褎顨嗛埛鎺懨归敐鍛暈閻犳劧绻濋弻褑绠涢幘璇插及閻庤娲樺妯跨亙闂佸憡渚楅崢楣冩晬濞戙垺鈷戦悷娆忓椤ュ顭胯椤ㄥ﹪骞冮敓鐘冲亜闁稿繗鍋愰崢顏堟椤愩垺鎼愰柨鏇樺劦閿濈偞绻濋崶銊у幈闂佺粯妫冮ˉ鎾剁不閹绘崨搴ㄥ炊瑜濋煬顒侇殽閻愬瓨宕屾鐐村浮楠炴﹢鎼归锝囨毉缂傚倸鍊搁崐鐑芥嚄閸撲礁鍨濇い鏍ㄧ矋瀹曟煡鏌涘畝鈧崑娑㈡偂濠靛鐓欓柟瑙勫姦閸ゆ瑩鏌涢妸銉モ偓褰掑Φ閸曨垰绫嶉柛灞剧⊕閻濐亝绻涚€涙鐭婇柣鏍帶椤繒绱掑Ο鑲╂嚌闂侀€炲苯澧い顓炴穿椤︽煡鎮￠妶澶嬬叆闁哄洨鍋涢埀顒€缍婂畷鏇熸償椤兛绨婚梺鍝勭Р閸斿秹鎯冮幋锔界厸闁糕槅鍘鹃悾鐢告煛瀹€鈧崰鎰焽韫囨稑绀堢憸蹇涘汲閻樼數纾藉ù锝呮惈瀛濆銈庡幘閸忔ê顕ｇ拠娴嬫闁靛繒濮堥埡鍛叆闁哄啫鐗婇弳婊勪繆閹绘帞澧涚紒缁樼〒閳ь剚绋掗…鍥儗閹烘梻纾奸柣妯虹－婢у灚顨ラ悙鎻掓殭闁伙綇绻濋獮宥夋惞椤愩倐鍋撴繝姘棅妞ゆ劑鍨烘径鍕煙鐏忔牗娅嗙紒鍌涘浮瀹曟粏顦寸痪鎹愭闇夐柨婵嗘缁茶霉濠婂牏鐣烘慨濠冩そ瀹曘劍绻濋崒姣挎洘绻涚€涙鐭嬮柣妤冨Т閻ｇ兘骞嬮敃鈧粻濠氭偣閸ヮ亜鐨烘い蟻鍕瘈闁靛骏绲剧涵楣冩煥閺囶亞绋荤紒鏃傚枛瀵挳濮€閳锯偓閹风粯绻涙潏鍓у埌闁硅绻濆畷顖炴倷閻㈢數锛滈柣搴秵閸嬪嫰鎮橀幘顔界厸濞达絿顭堥弳锝夋煛娴ｇ懓濮嶇€规洖鐖兼俊鎼佸Ψ閵壯冩惛闂傚倸鍊烽懗鍓佹兜閸洖绀堟繝闈涚墢閻瑩鏌熼悜姗嗘畷闁稿鍊块弻锟犲炊閳轰焦鐎繛瀛樼矋缁捇寮婚悢鐓庣骇闁割煈鍣弳銏㈢磽娴ｅ壊鍎撶€规洜鏁稿Σ鎰板箳濡も偓閻掑灚銇勯幒鎴濐仼闁绘帒鐏氶妵鍕箳閸℃ぞ澹曢梺鍓х帛閻楃娀寮婚敐鍜佹建闁逞屽墮椤洩顦崇紒鍌氱У缁轰粙宕ㄦ繝鍕箞闂備線娼ц噹闁告劑鍔岄‖鍡欑磽閸屾瑧顦﹂柣顓濈劍閵囨棃宕妷锕€搴婂┑鐘绘涧椤戝懘鎮欐繝鍥ㄧ厾缂佸娉曟禒娑欑箾閸涱喚澧紒缁樼箞閹粙妫冨ù韬插灲閺屻劑寮村Ο琛″亾濠靛棛鏆︽い鏍剱閺佸啴鏌ㄥ┑鍡樼ォ婵炴潙瀚埞鎴﹀煡閸℃浠撮悗瑙勬礈閺佺顕ｈ閸┾偓妞ゆ巻鍋撻柍瑙勫灴閹瑩鎳犻鈧。娲⒑鐠囪尙绠茬紒璇茬墕椤曪絿绮欐惔鎾搭潔闂侀潧楠忕槐鏇㈠储閻㈢數纾奸柣鎰靛墯缁惰尙鈧娲﹂崜姘辩矉瀹ュ棗顕遍悗娑欘焽閸橀亶姊洪崘鍙夋儓闁哥噥鍋呯粋鎺撴綇椤垶顔旈梺缁樺姇濡﹪宕曢弮鍫熺厸濞达絿顭堥埀顒€娼￠獮鎰節閸愩劎绐為梺绯曞墲閵囩偞绔熼弴銏♀拺缂備焦锚閻忓崬鈹戦鍝勨偓婵嬪箖閳ユ枼妲堟慨妤€妫涢崬鐢告煟閻樼儤銆冮悹鈧敃鍌氱？闊洦绋掗悡鐔肩叓閸パ嶆敾婵炲懎鎳樺Λ浣瑰緞閹邦厾鍘藉┑鈽嗗灡鐎笛囨偟椤忓牊鐓曞┑鐘插暙婵牓鏌熸笟鍨缂佺粯绻堝畷姗€鍩炴径姝屾闂傚倷娴囬鏍窗濮樿泛绀傛慨妞诲亾妤犵偛鍟抽ˇ鍦偓瑙勬礈閸樠囧煘閹达箑鐐婇柕濞у嫭鐦旈梻鍌氬€搁崐鎼佸磹瀹勬噴褰掑炊椤掑鏅梺鍝勭▉閸樿偐绮ｅΔ鍛厸鐎广儱楠搁獮鏍棯閹呯Ш闁哄本绋栭ˇ铏亜閵娿儲鍤€缂佺粯鑹鹃埞鎴︽倷鐎涙ê闉嶉梺绯曟櫅閸熸潙鐣烽幋锕€绠婚柛銊︾☉娴滅偓绻涢崼婵堜虎闁哄鐟х槐鎺楊敊閻ｅ本鍣伴梺闈涙缁€渚€锝炲鍫濈劦妞ゆ帒瀚粻鏍ㄧ箾閸℃绠氶柡瀣閺岀喓绮欓崹顔惧絹閻熸粌绉归崺鐐哄箣閿旇姤娅栭梺鍛婃处閸嬪倿寮堕銏♀拺缂佸灏呴弨濠氭煟濡ゅ啫鈻堥柣娑卞櫍楠炲洭鎮ч崼婵冨亾闁垮浜滈柟鍝勭Ф椤︼妇鈧鍠栧鈥愁潖濞差亜浼犻柛鏇炵仛鏁堥梻浣规偠閸斿瞼绱炴繝鍌ゅ殨闁规儼濮ら弲婵嬫煕鐏炲墽銆掗柛姗嗕簼缁绘繈濮€閿濆棛銆愬┑鈽嗗亝閻熴儵鍩㈠澶婂耿婵炴垶鐟ч崢鎾绘⒒娴ｅ摜浠㈡い鎴濇嚇閹﹢骞橀鐣屽幐闁诲繒鍋涙晶浠嬪煡婢舵劖鐓冮悷娆忓閻忓鈧娲栧畷顒冪亙婵犵數濮抽懗鍓佺矆婢跺ň鏀介柣妯活問閺嗩垶鏌涢幘瀵哥畾闁靛洦鍔欏畷姗€顢旈崱娆樻Ц濠电姷鏁告慨鏉懨洪妶澶嬪珔闁绘柨鎽滅粻楣冩煙鐎涙鎳冮柣蹇婃櫊閺岋綁骞樼€电硶妲堥梻鍥ь樀閺屻劌鈹戦崱妯烘闂佽鍨伴悧濠囧Φ閸曨垱鏅查柛娑卞枟閸庢挸顪冮妶搴濈盎闁哥喎鐡ㄦ穱濠囨嚋閸偄鍔呴梺鐐藉劚绾绢參顢欓幇顓犵瘈闁汇垽娼ф禒鈺傘亜閺囩喓鐭嬪ǎ鍥э躬瀹曞爼顢楅埀顒勬倿閸偁浜滈柟杈剧稻绾墎绱掓担鍝勫幋闁哄本绋撻埀顒婄秵閸嬪嫭鎱ㄥ澶嬬厱闁宠鍎虫禍鐐繆閻愵亜鈧牜鏁繝鍥ㄥ殑闁割偅娲栭悡鈧梺鍝勬川閸犲棙绂嶅鍕╀簻闁规崘娉涙禒锕傛煕閻樻剚鐒介柍褜鍓濋～澶娒鸿箛娑樺瀭濞寸姴顑冮埀顑跨窔瀵噣宕煎┑鍡欑崺婵＄偑鍊栭悧妤冨垝鎼粹垾锝夊炊椤掍讲鎷绘繛鎾村焹閸嬫挻绻涙担鍐插濞堜粙鐓崶銊︾缂佽翰鍊曢湁闁绘ê妯婇崕鎰版煕鐎ｎ亜鈧潡寮婚悢鍏肩劷闁挎洍鍋撻柡瀣ㄥ€楅惀顏堝箚瑜嬮崑銏ゆ煙椤旂瓔娈滈柡浣瑰姈閹棃鍨鹃懠顒€鍤梻浣筋嚙缁绘劕霉濮樿泛鐭楅柛鎰靛枛閽冪喖鏌ㄥ┑鍡╂Ч闁哄懏鐓￠弻娑㈠焺閸愵亝鍣梺浼欑悼閺佽顫忛搹鍏夊亾閸︻厼校妞ゃ儱顦伴妵鍕晝閳ь剟鎮樺璺虹疄闁靛ň鏅涢悞鍨亜閹烘垵顏柣鎾卞劜缁绘盯骞嬮悘娲讳邯椤㈡棃鍩￠崒銈嗩啍?"
        if verbosity_bias == "short":
            return "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡▎鎴犫敍闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼宕滆绾惧ジ鏌ｅΟ鎸庣彧閻忓浚鍙冮弻锝夋晲婢跺鏆犵紓浣芥閺咁偆鍒掑▎蹇婃瀻闁绘劦鍓涚粔閬嶆⒒閸屾瑨鍏岄柛瀣ㄥ姂瀹曟洟鏌嗗鍛焾闁荤姵浜介崝蹇旀叏閹惰姤鐓忓璺烘濞呭棝鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡樺窛闁硅棄鍊圭换娑㈠礂閻撳骸顫屽銈庡幖濞硷繝骞冮悜鑺ュ亱闁割偒鍋呴敍渚€姊绘担鍛婃儓闁硅櫕鎸搁埢鏂库槈濠婂懍绨烽梻鍌欑閹测剝绗熷Δ鍛偍濡わ絽鍟弲顒佺箾閹存瑥鐏柣鎾跺枛楠炴牠骞栭鐐典化缂備礁顦遍弫濠氬蓟濞戙垺鍋愰柟棰佺劍閻や線姊虹拠鈥虫珯缂佺粯绻傞锝夊箻椤旂⒈娼婇梺鎸庣☉鐎氼剛鏁Δ鍛拻濞达絽鎽滈弸鍐╀繆濡炵厧濡跨紒顔肩墛缁楃喖鍩€椤掆偓椤曪綁骞栨担鑲澭冾熆鐠轰警鍎戦柛妯圭矙濮婃椽宕烽鐐插濠电偛寮堕悧鐐恒€傞崸妤佲拻濞撴埃鍋撴繛浣冲厾娲Χ閸ワ絽浜炬慨姗嗗亜瀹撳棛鈧娲樺浠嬪极閹剧粯鍋愰柟缁樺笧閻涒晜淇婇悙顏勨偓鏍涙担瑙勫弿闁靛牆鎳夐弸鏃堟煕濠靛嫬鍔ょ痪鍙ョ矙閺屾稓浠﹂崜褎鍣梺绋跨箰閻偐妲愰幒妤婃晪闁告侗鍘炬禒鎼佹⒑鐠団€崇仩閻庢矮鍗抽妴浣糕槈閵忊€斥偓鐑芥⒒閸喓銆掗柕鍫畵濮婅櫣鎷犻幓鎺戞瘣缂傚倸绉村Λ婵嗙暦閺夎鏃堝川椤撶媴绱梻浣虹帛閸ㄥ吋鎱ㄩ妶澶嬪亗闁哄洨鍠嗘禍婊勩亜閹捐泛鏋庨柣蹇嬪劚闇夋繝濠傚閻绱掔紒妯兼创鐎规洏鍔戦、姘跺川椤旂偓娈介梻鍌欑閻ゅ洭锝炴径鎰瀭闁秆勵殔缁犳牗绻涢崱妯诲鞍闁搞倖鍨堕妵鍕箳瀹ュ洤濡介梺鍝ュУ閻楃姴顫忕紒妯诲閻熸瑥瀚禒鈺呮⒑缁嬪尅鏀绘繛鑼枛瀵粯绻濋崶銊︽珳闂佸憡渚楅崹鍗炩枔妤ｅ啯鈷戦柛锔诲幖椤ｅ吋绻濋姀鈽呰€跨€规洘锕㈤崺鈧い鎺嗗亾妞ゎ亜鍟存俊鍫曞幢濡も偓琛肩紓鍌欐祰鐏忣亝鎱ㄩ妶澶婄畾闁哄啠鍋撶紒缁樼箞瀹曟帒螖娴ｈ婢戦梻鍌欒兌缁垶宕濋弽褜鐒芥繛鍡樻尰閸婂爼鏌ｉ弬鍨倯闁绘挻娲熼弻鏇熺箾閸喖濮㈢紓浣割槹濡炰粙寮婚敐鍛闁告鍋為悵婵囩節濞堝灝鏋撻柛瀣崌濮婃椽鎮欓挊澶婂Г闁诲繐绻戦悷褏鍒掔拠宸僵闁煎摜顣介幏娲⒒閸屾氨澧涚紒瀣尰閺呭爼寮撮姀鈥斥偓鍨叏濡厧甯舵繛鍛Ф閳ь剝顫夊ú妯兼崲閸岀儐鏁囧┑鍌滎焾閻愬﹪鏌ㄥ┑鍡樺櫢濠㈣娲熼弻锝夋偄閸濄儲鍣ч柣搴㈠嚬閸樺墽鍒掗崼銉ョ劦妞ゆ帒瀚埛鎴︽煕濠靛嫬鍔氶柡瀣缁绘稓娑垫搴ｇ槇闂佹悶鍔戠粻鏍ь嚕椤曗偓瀹曠厧鈹戦崼顐Ｐ炲┑锛勫亼閸婃牠寮婚妸銉庯綁宕奸敐搴⑩枌闂備礁鎼張顒傜矙閹达箑鐓″鑸靛姇绾偓闂佺粯鍔曢崥鈧柛鏍ㄧ墬娣囧﹪鎮欓鍕ㄥ亾閺嵮屾綎闁革富鍘介弳婊勪繆閵堝懎鏆炵€规洖寮剁换娑㈠箣閻愯尙鍔伴梺绋款儐閹告悂鍩ユ径濞炬瀻婵☆垳鍘ф慨娲⒒娴ｈ銇熼柛妯恒偢閺佸啴顢旈崼婵婃憰闂佹寧绻傞ˇ顖炲礃閳ь剟鎮峰鍐惧剶鐎规洘鍨挎慨鈧柕鍫濇閸樿棄鈹戦悙鏉戠仴鐎规洦鍓欓埢宥咁吋閸ワ絽浜鹃悷娆忓缁€鍐煥閺囨ê鐏ǎ鍥э躬瀹曘劍绻濋崘銊ュΤ闂備焦瀵х换鍌炲箠韫囨稒鍊跺〒姘ｅ亾婵﹥妞藉畷鐑筋敇閻旈攱鐣梺璇插濮樸劍鏅跺Δ浣衡攳濠电姴鍋嗗鎵偓鍏夊亾濠电姴鍞鍛瘈闁汇垽娼цⅷ闂佹悶鍔嶅钘夌暦瑜版帒鍨傛い鏇炴噺缂嶅海绱撻崒娆戝妽閽冨崬鈹戦姘煎殶缂佽鲸甯掗埥澶婎潨閸℃澹夌紓鍌氬€哥粔鎾偋閹炬剚娼栭柧蹇撴贡閻瑩鏌熺粙鍧楊€楅柡鈧鐐╂斀闁绘劕寮堕崳鐑樼箾閼碱剙鏋庢い鏇秮瀵濡烽敃鈧▓婵嬫⒑閸撹尙鍘涢柛瀣瀹曟繈宕ㄩ褎瀵岄梺闈涚墕妤犳悂鐛Δ鍛厱闁靛鍎抽崺锝団偓娈垮枟閻擄繝宕洪敓鐘茬＜婵犲﹤鎳愬Σ鍥⒒娓氣偓濞佳勵殽韫囨洖绶ら柛鎾楀嫬鍘归梺缁樺姦閸忔瑦绂嶅鍕╀簻闁圭偓顨呴崯顐︼綖閳哄懏鈷戦梻鍫熺⊕椤ョ偤鎮介娑辨畼闁瑰箍鍨归埞鎴﹀幢閳哄倸鍏婃俊鐐€栭幐鐐叏鐎靛憡鏆滃Δ锝呭暞閳锋帒霉閿濆浂鐒炬い銉ョ箻閺屾稓鈧綆浜濋崳浠嬫煙楠炲灝鐏茬€规洘锕㈤、娆撳閻欌偓濡插憡銇勯婊冨鐎规洏鍔戦、娑橆煥閹邦喖绨ユ繝鐢靛Х椤ｎ喚妲愰弴銏犵？闁瑰濮锋稉宥夋煙鐎涙璐╂繛宸簼閺呮繈鏌涚仦鍓р槈濞存粍顨婂娲传閸曨剙鍋嶉梺鎼炲妽濡炶棄鐣烽幇鐗堝仺闁告稑锕﹂崣鍡椻攽閻樼粯娑ф俊顐ｎ殜瀵啿鈻庤箛濠冩杸闂佺偨鍎抽崑銊╁磻閵忋倖鐓涢悘鐐垫櫕鍟稿銇卞倻绐旈柡灞剧洴楠炴鈧稒顭囧▓銈夋⒑閻熸壆鐣柛銊ㄦ閻ｇ兘骞掑Δ浣糕偓濠氭煕閳╁叐鎴濃枍閺冨牊鈷掑ù锝囨嚀椤曟粎绱掔拠鎻掆偓鑳婵炲濮撮鍛村几娓氣偓閺屾盯骞囬棃娑欑亶闂佺粯鎸哥换姗€鎮￠锕€鐐婄憸婵嬪绩缂佹绠鹃柛娑卞幗閸ゅ洭鏌″畝鈧崰鏍€佸▎鎾村癄濠㈣泛濂旂槐婵囩節濞堝灝鏋涢柨鏇樺劚椤啯绂掔€ｎ剙绁﹂梺鍝勭▉閸樹粙宕愰悜鑺ョ厵缂備焦锚缁楁帡宕幖浣光拻闁稿本鑹鹃埀顒佹倐瀹曟劙宕妷銏犱壕婵鍘ф晶浼存煃瑜滈崜姘卞枈瀹ュ拋鐔嗘慨妞诲亾闁诡噣绠栭幃婊堟嚍閵夈儰绨婚梻浣虹帛閹哥霉閻戝壙鍥Ω閵夘喗瀵岄梺闈涚墕濡瑩藟閸℃瑦鍋栨繛鍡樻尰閻撴瑥顪冪€ｎ亪顎楅柛鏂款儑缁辨帞绱掑Ο鍏煎垱閻庢鍠栭悥濂哥嵁鐎ｎ亖鏀介柛銉戔偓閸嬫捇顢涢悙绮规嫼闂佺厧顫曢崐鏇㈠汲閳ь剟姊洪幖鐐插妧闁告粈鐒﹀瓭濠电姷鏁搁崑娑㈩敋椤撱垹鍌ㄧ憸鏃堝箖濞差亜惟闁冲搫鍊告禍妤€鈹戦悙鏉戠仧闁搞劍妞介幃锟犲即閻旂繝绨婚梺閫涘嵆濞佳勭濠婂厾鐟邦煥閸曨厾鐓€濡炪値鍙€閸庡藝閸欏浜滈柡鍥ュ妼瀵噣鏌涢埞鎯т壕婵＄偑鍊栫敮濠勬閿熺姴鐤煫鍥ㄧ⊕閻撴洟鏌ｅΟ璇插婵炲牊娲滅槐鎺旂磼濡皷濮囩紓浣虹帛缁诲牆鐣烽幒妤€围闁告侗鍣崥娆忊攽閿涘嫬浜奸柛濠冪墪鐓ょ€广儱顦壕濠氭煙閹呬邯闁稿鎸鹃幉鎾礋椤掑偆妲伴梺姹囧焺閸ㄨ京鏁敓鐘茬伋闁挎洖鍊告儫闂佸疇妗ㄩ悞锕傚Φ濠靛鈷戦柛娑橈工婵箑霉濠婂簼绨婚摶鐐烘煟閹达絽袚闁抽攱甯￠弻娑氫沪閹规劕顥濋梺閫炲苯澧伴柛蹇旓耿楠炲﹤螖閸涱參鍞堕梺鍝勬处閵囨盯宕戦幘缁樻櫇闁稿本宀搁崬鍫曟⒑闂堟侗妲堕柛搴ㄤ憾閹潧螣娓氼垱瀵岄梺闈涚墕濡绮幒妤佸€垫慨妯煎帶瀵喚鈧娲橀崹鍧楀极瀹ュ绀嬫い鎺嗗亾闁哄鍨垮娲传閸曨偀鍋撻挊澶嗘灃闁哄洢鍨瑰Ч鏌ユ煥閺冨倹娅曠紒鈾€鍋撻梻鍌氬€搁悧濠勭矙閹烘鏅€广儱顦伴悡鏇熸叏濮楀棗澧婚柛搴＄箲閵囧嫰顢橀埄鍐€婇梺鍦嚀鐎氼厾绮悢纰辨晬婵﹩鍓欓ˉ鎰版⒒閸屾瑧顦﹂柟璇х節閳ワ箓宕堕鈧弸渚€鏌涘┑鍕姕妞ゎ偅娲熼弻鐔煎箚瑜忛幗鐘测攽椤栨稒灏﹂柡灞剧洴楠炴﹢寮堕幋鐘点偡闂備礁鎲￠幐绋跨暦椤掑嫧鈧棃宕橀鍢壯囨煕閳╁喚娈樺ù鐘虫倐濮婃椽鎳￠妶鍛瘣闂佸搫鎳愭繛鈧柣娑卞櫍瀹曟﹢顢欓懖鈺佸Ф闂備礁鎲￠崝锔界椤忓嫷鐎舵い鏇楀亾婵﹥妞藉畷銊︾節閸曘劍顫嶉梻浣瑰濞测晝绮婚幘宕囨殾闁靛繈鍊栭ˉ鍫熺箾閹达綁鍝洪悗闈涚焸濮婃椽妫冨☉姘暫濠碘槅鍋呴悷鈺呭春濞戙垹绠虫俊銈勮兌閸樺崬鈹戞幊閸婃挾绮堟笟鈧崺銏ゅ即閻曚焦顔旈梺缁樺姇濡﹪宕曡箛娑欑厓閻熸瑥瀚悘瀛橆殽閻愬弶鍠樻い銏☆殕缁楃喖宕惰閺嗘棃姊婚崒姘偓鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偛顦甸崹鍓ф惥娴ｈ銇濋柡浣稿暣瀹曟帒顫濋鍌楀亾椤撱垺鈷戦悷娆忓閸熷繘鏌涢悩宕囶暡缂佸顦濂稿幢濞嗘埈鍟庨梻浣烘嚀椤曨參宕戦悢鐓庣疇闁逞屽墯缁绘稓鈧稒顭囬惌瀣磼椤旇姤宕岀€殿喖顭烽幃銏ゅ礂閻撳簶鍋撶紒妯圭箚妞ゆ牗绻冮鐘裁归悩铏唉婵﹥妞介弻鍛存倷閼艰泛顏繝鈷€灞界仸闁哄瞼鍠栭、娆撴偂鎼存ê浜鹃柛顭戝枤閺嗭附绻涘顔荤盎闁绘帒鐏氶妵鍕箳瀹ュ顎栨繛瀛樼矋缁捇寮婚悢鍏煎€绘俊顖濇娴犳挳姊洪柅鐐茶嫰婢ь噣鏌熺拠褏纾跨紒顔碱儔楠炴帡骞樼€靛摜肖闂備線娼ч…顓犵不閹存繍鍤曢柟绋挎捣缁♀偓闂佹眹鍨藉褍鐡梻浣烘嚀閸熻法鎹㈠鈧妴渚€寮崼鐔蜂汗闂佹眹鍨婚弫鎼佹晬濠婂牊鐓涘璺猴功婢ф垿鏌涢弬璺ㄧ伇缂侇噮鍙冮獮鎺懳旀担鐟版畽闂備焦瀵х换鍌炈囨导瀛樺亗闁哄洨鍠撶弧鈧梻鍌氱墛缁嬫帡藟濠婂嫨浜滈煫鍥ㄦ尵閹界姷绱掔紒妯兼创鐎规洘顨婂畷妤呮偂鎼达綇绱﹀┑鐘愁問閸犳牠鏁冮敂鎯у灊妞ゆ牜鍋涚粻顖炴煕濞戞瑦缍戠紒鈧崼銉︾厵缂備焦锚缁楁岸鏌涚€ｎ亜顏慨濠勭帛閹峰懘宕ㄦ繝鍐ㄥ壍婵＄偑鍊х€靛矂宕归崼鏇炵畺婵☆垵銆€閺€浠嬫倵閿濆懎顣崇紒瀣箻濮婃椽骞栭悙鎻掑Η闂侀€炲苯澧寸€殿喓鍔戦幊鐐哄Ψ閿濆嫮鐩庨梻浣告惈閸燁偊宕愰崼鏇炵劦妞ゆ巻鍋撴い鎴濇閻忓鈹戦鏂や緵闁告娅ｉ幑銏ゅ幢濡晲绨婚梺瑙勫閺呮盯鎮橀埡鍌樹簻闊浄绲介獮妤呮煏閸パ冾伃濠殿喒鍋撻梺瀹犳閹虫捇鍩€椤掑啯纭堕柍褜鍓濋～澶娒哄鈧妴鍐╃節閸パ呯暫闂佹枼鏅涢崯顖炲磿閻斿吋鐓ユ繝闈涙瀹告繄鈧鎸风欢姘潖缂佹ɑ濯寸紒娑橆儏濞堫參姊洪崨濠傜仼闁哄拋鍋嗗Σ鎰版倷閸濆嫬鑰垮┑鐐村灦椤洭藝椤撶偐鏀介柣鎰级椤ョ偤鏌涢妸銉у煟鐎?"
        return "婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽弫鎰板川閸屾粌鏋庨柍璇查叄楠炲棜顦虫い鏂垮缁辨捇宕掑▎鎺戝帯婵犳鍠楅幐鎶藉箖濡警娼╅悹杞扮秿閿曞倹鐓曢柡鍥ュ妼閺嬨倝鏌ｉ妶鍌氫壕闂傚倷绀佸﹢閬嶅磻閹捐绠氶悘鐐跺▏濞戙垺鍊烽柣銏㈡暩閿涙繃绻涙潏鍓ф偧闁哄拋鍋婂畷濂割敂閸喓鍘辨繝鐢靛Т閸熸壆绮婚悙纰樺亾濞堝灝鏋涙い顓犲厴楠炲啴濮€閵堝棙鍎梺闈╁瘜閸橀箖宕㈤鐐粹拻濞达絿顭堥ˉ蹇涙煟閹惧磭澧︾€规洘濞婇、姘跺焵椤掆偓閻ｅ嘲鈹戦崶褏绐為梺褰掑亰閸樻悂骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囶亞鐣垫鐐诧躬瀹曟﹢顢旈崱娆欑床缂傚倸鍊烽悞锕傛晝椤愶附鍤€閻犳亽鍔夐崑鎾斥枔閸喗鐏堝銈庡幘閸忔﹢鐛崘顔碱潊闁靛牆妫欓崕顏堟⒑闂堚晛鐦滈柛娆忕箳濡叉劙寮婚妷锔规嫽婵炴挻鍩冮崑鎾寸箾娴ｅ啿鎳忓畷鏌ユ煙閻戞ɑ灏伴柛娆忕箻閺岋綁濮€閻樺啿鏆堥梺绋匡工閻栧ジ寮诲☉銏╂晝闁绘ɑ褰冩慨鏇㈡⒑閹惰姤鏁遍柛銊ユ贡濡叉劙骞掗弬鍝勪壕闁挎繂楠搁獮鏍煕閺傝法浠涢柕鍥у椤㈡洟顢楅崒婊勬闂備礁鎼張顒勬儎椤栨凹鍤曟い鎺戝€瑰畷澶愭煏婵犲啫濮傞柛濠冪箞瀵鎮㈤懖鈺佺ウ闂佸壊鐓堥崰姘婵傚憡鈷戦悗鍦У椤ュ銇勯敃鈧悘姘跺箞閵娾晛鐒垫い鎺戝閻撶喐淇婇娑欍仧闁哥喎绻橀弻娑橆潩椤掍礁娅ょ紓浣虹帛缁诲牓骞冩禒瀣棃婵炴垶顨堥幑鏇熺節绾版ɑ顫婇柛瀣嚇閵嗗啴宕奸妷銉ь唹闂侀潧绻堥崐鏇犵不閹惰姤鐓欏Δ锝呭枤閺夌儤绻涢弶鎴濐伃婵﹥妞藉畷妤呮嚃閳瑰灝浠﹂梻浣告惈閹冲繒鎹㈤崟顒傜彾闁哄洨鍠撻梽鍕煕濞戞﹫鍔熼柛姗€娼ч—鍐Χ閸℃瑥鈪瑰┑鈽嗗亝椤ㄥ﹤鐣烽鐐村亹閻犲洩灏欓鍥⒑閸涘﹤濮﹀ù婊呭仧婢规洟鎸婃径鍫氬亾閹烘埈娼╂い鎺嶇劍閹瑥鈹戦悙鍙夊櫤闁挎洏鍨藉璇测槈閵忕姈鈺呮煏婢诡垰鍟伴崢浠嬫⒒娴ｈ櫣甯涘〒姘殜瀹曟娊鏁愰崨顖涙婵犻潧鍊婚…鍫濇暜闂備線娼чˇ顖滆姳閸洖鐤鹃柣妯款嚙閽冪喖鏌￠崶鈺佹瀻缂佸墎鍋炴穱濠囶敍濠婂啫濡洪梺璇茬箰缁夊綊骞冨Δ鍛€烽柣鐔稿閸嬫捇寮借濞撳鏌﹀Ο渚▓婵炲吋鐗犻弻褑绠涢弴鐔锋畬闁诲骸鐏氶悡锟犲蓟閿熺姴鐐婇柍杞版缁爼姊洪崘鎻掓Щ妞わ富鍨堕垾鏃堝礃椤斿槈褔鏌涢幇鈺佸妞ゎ剙鐗撳铏规兜閸涱喚褰ч梺鎸庢磸閸ㄨ棄顕ｉ锕€绠涢柣妤€鐗嗛埀顒€鍢查妴鎺戭潩閻撳海浠梺鍝勬噺缁诲牆顫忓ú顏勭閹兼番鍩勫鍧楁偠濮橆厾鎳囬柡宀€鍠栭弻銊р偓锝庡亖娴犮垹鈹戦纭锋敾婵＄偠妫勯悾鐑藉Ω閿斿墽鐦堥梺鍛婃处閸橀箖寮抽妶澶嬧拺閻犲洦褰冮銏ゆ煕閹存繄绉虹€规洩缍佸畷姗€顢橀悤鍌滅＝闂傚倸鍊烽懗鍓佸垝椤栫偛绀夋俊銈呮噷閳ь剙鍊圭粋鎺斺偓锝庝簽閿涙盯姊虹憴鍕妞ゆ泦鍛焼闁稿本鍑归悢鍡涙偣閾忕懓鐨戞慨濠冾殔椤法鎲撮崟顒傤槶缂備浇椴搁幑鍥х暦閹烘垟鏋庨柟鎼幗琚﹀┑锛勫亼閸婃牠宕归棃娴虫稑鈹戠€ｃ劉鍋撴笟鈧鍊燁槷闁哄閰ｉ弻鐔煎箚瑜嶉弳閬嶆煙椤栨粌浠辨慨濠冩そ瀹曨偊宕熼鈧崑宥夋⒑閹肩偛濡芥俊鐐扮矙楠炲啴鏁撻悩鎻掑祮闂佺粯姊荤换婵堣姳婵犳碍鈷戦悷娆忓缁舵彃顭胯濞撮鍒掑▎鎾村殥闁靛牆娲ㄩ敍婊堟⒑闁偛鑻晶鎾煕閳规儳浜炬俊鐐€栫敮鎺斺偓姘煎弮閸╂盯骞嬮悩鐢碉紳婵炶揪缍€閸嬪倿骞嬮悩杈╁墾婵炲鍘ч悺銊╂偂閻斿吋鐓冮柛婵嗗瀹搞儵鏌ｈ箛銉ヮ洭闁逞屽墯椤旀牠宕板☉銏╂晪鐟滄棃宕洪妷锕€绶炲┑鐘插閸嶉潧顪冮妶鍡楀Ё缂佽尪濮ら崚濠冨鐎涙ǚ鎷绘繛杈剧到閹诧繝宕悙鐑樼厵缂佸瀵чˉ銏⑩偓瑙勬磸閸旀垿銆佸☉姗嗘僵妞ゆ帒鍊婚幊鍡涙⒒閸屾艾鈧悂宕愰幖浣哥９濡炲瀛╅鑺ユ叏濮楀棗澧婚柣鎺嶇矙閺屻倖鎱ㄩ幇顑藉亾閺囩姵顐介柕鍫濇噳閺€浠嬫煟濡櫣鏋冨瑙勵焽閻ヮ亪骞戦幇顓犮€婇梺閫炲苯澧叉い顐㈩槸鐓ら柡宥庣亹濞差亝鏅濋柛宀嬪缁嬪繘姊洪崫鍕偍闁搞劍妞介幃鈥斥枎閹惧鍘靛銈嗙墪濡骞婅箛娑樼疅闁稿繗鍋愮弧鈧┑鐐茬墕閻忔繈鎮橀敓鐘崇厵闁告稑锕ら埢鏇燁殽閻愭彃鏆欓柣锝忕節楠炲秹鎼归銈傚亾婵犳碍顥婃い鎰╁灪婢跺嫰鏌熺亸鏍ㄦ珕閻庨潧銈搁崺鈧い鎺戝閳锋帒霉閿濆懏鍟為柛鐔哄仱閺岋綁鎮㈤弶鎴濆闁捐崵鍋炴穱濠囧Χ閸涱喖娅濋梺閫炲苯澧俊顐㈠暙閻ｅ嘲顫滈埀顒勩€佸▎鎾冲簥濠㈣鍨板ú锕傛偂閺囥垺鐓冮柍杞扮楠炴ɑ銇勮箛鎾跺悋闁搞儺鍓欓悡娑㈡煕濞戝崬鏋撻柟閿嬫そ濮婃椽宕ㄦ繝鍕ㄦ濡炪値鍙庨崜鐔煎箖閻愬顩烽悗锝庡亞閸樻悂姊洪崨濠勭焼缂佲偓娴ｅ湱顩查柣鎰劋閻撴洟鏌熼悜妯诲碍缂佹う鍥ㄧ厓鐟滄粓宕滈妸褏绀婇柛鈩冾焽椤╂煡鏌涢锝嗙閻熸瑱绠撻幃妤呮晲鎼粹剝鐏嶉梺缁樻尰濞叉鎹㈠┑鍥╃闁诡垎鍌氼棜闂傚倷鑳剁划顖滄暜椤忓棛涓嶉柟杈捐礋閳ь剙鎳忕缓鐣岀矙鐠囬敮鏅犻弻宥夊传閸曨偀鍋撻幖浣哥劦妞ゆ帒鍊归弳顒勬煛鐏炲墽顬肩紒鐘崇洴楠炴瑩宕橀埞顒婇檮缁绘稓鈧稒顭囬惌鎺旂磼閻樺磭澧い顐㈢箰鐓ゆい蹇撴噽閸旂敻姊虹紒妯哄閻忓浚浜為埀顒佺濠㈡﹢鈥﹂懗顖ｆЪ闂佺懓鎲℃繛濠傤嚕婵犳碍鍋勭痪鎷岄哺閺呪晠姊虹粙璺ㄧ闁告鍕浄闁圭虎鍠楅埛鎴犵磼椤栨稒绀冮柡澶婄秺閺屾稓鈧綆鍋呯亸顓熴亜椤忓嫬鏆ｅ┑鈥崇埣瀹曞崬螖閸愵亝鍣梻浣筋嚙鐎涒晠宕欒ぐ鎺戠煑闁告劦鍠栭弰銉︾箾閹存瑥鐏╃紒鐙呯秮閺屻劑寮崒娑欑彧闂佸憡锚瀹曨剟鍩為幋锔藉亹缂備焦蓱闁款厼鈹戦埥鍡椾簼妞ゃ劌锕妴渚€寮崼婵堝幐闂佸憡渚楅崰姘跺储閹间焦鈷戠紒顖涙礀婢ф煡鏌ｉ悢鏉戝姕缂佸倹甯￠弻鍡楊吋閸℃瑥骞愰梺璇茬箳閸嬫稒鏅堕挊澹濇椽寮堕幋鏃€鏂€闂佹枼鏅涢崯顖炲磹閹邦兘鏀介柨娑樺閻掓寧銇勯敃浣峰惈缂佽鲸甯￠、娆撴嚃閳衡偓缁數绱撴担铏瑰笡闁烩晩鍨跺顐﹀箛閺夊灝绐涘銈嗘婵倝宕愰悜鑺モ拻濞达絿鎳撻婊勭箾鐠囇囨缂佸倸绉归、鏃堝礋闂堟稒顓垮┑鐘垫暩婵敻鎳濇ィ鍐祦闁靛繆鈧尙绠氶梺闈涚墕閹锋垵顔忛妷鈺傜厵妞ゆ棁妫勯悘瀛樻叏婵犲懏顏犻柛鏍ㄧ墵瀵潙螖閳ь剚绂嶉崜褉鍋撶憴鍕婵炲眰鍔戦、娆愬緞閹邦厾鍘介柟鍏肩暘閸ㄥ吋绔熷鈧弻鏇㈠醇閵忊晝鍔稿銈庡亜缁绘帞妲愰幒鎳崇喓鎷犲顔瑰亾閹剧粯鈷戦柛娑橈功閳藉鏌ㄩ弴妯哄婵炴垹鏁婚崺鈧い鎺嶆缁诲棝鏌ｉ幇鍏哥盎闁逞屽厵閸婃繂鐣烽姀锛勯檮闁告稑锕ゆ禍閬嶆⒑缁洖澧茬紒瀣笧缁骞掑Δ浣叉嫽婵炶揪缍€濞咃絿鏁☉銏＄厱闁靛ě鍐ㄤ粯闁捐崵鍋ら弻娑㈠即閵娿儳浠梺绋款儏閸婂潡寮诲澶娢ㄩ柨鏇楀亾濠⒀屽灦閺岋綁寮幐搴＆闂佸搫琚崐婵嬬嵁閺嶃劍濯撮悷娆忓閺侇亜鈹戦悩鎰佸晱闁哥姵鐗犻幃褔骞樼拠鑼舵憰闂佹寧绻傞ˇ顖滅不婵犳碍鍋ｉ柧蹇氼潐绾绢亪鏌ㄥ┑鍡樺窛缁炬崘鍋愮槐鎾存媴鐠囷紕鍔峰┑鐐插级閹告娊寮婚悢椋庢殾闁搞儺鐏濋敐澶嬬叆婵炴垶鐟ユ慨鍥煃鐟欏嫬鐏寸€规洖宕～婊堝幢濡や焦娈洪梻鍌氬€搁崐鎼佸磹瀹勬噴褰掑炊椤掑鏅悷婊冮叄閵嗗啴濡烽妸褏鏉搁梺鍝勬川婵磭绮径鎰拺閻熸瑥瀚粈鍐┿亜閺囧棗娲︾€氬懘鏌ｉ弬鍨倯闁绘挾鍠栭弻锟犲礃閵娿儮鍋撻悽绋跨闁跨喓濮甸悡娑樏归敐澶嬩氦闂婎剦鍓熼弻锛勪沪鐠囨祴鍋撻弽顓炵疄闁靛ň鏅涚粻娑欍亜閹达絾顥夊ù婊呭亾娣囧﹪濡堕崨顔兼闂佺顑呴崐鍧楀蓟閻斿吋鍊锋い鎺嗗亾濠⒀屽灡缁绘盯骞橀幇浣哄悑闂佸搫鏈ú鐔风暦閻撳簶鏀介柛鈩兩戦鍕⒒娴ｇ瓔鍤欐繛瀛樼缁傚秴鈹戦崼鐔峰簥濠电偞鍨崹娲吹閹寸偑浜滈柟鍝勬娴滈箖姊洪崫鍕靛剱缂佸鎹囬崺鈧い鎺嶇贰閸熷繘鏌涢敐搴℃珝鐎规洘鍨剁换婵嬪磼濠婂嫭顔曢梻浣告贡閸庛倝銆冮崱娑樼９闁绘垼濮ら悡娑橆熆鐠轰警鍎忛柣蹇婃櫆娣囧﹦绱掗姀鐘崇亪闂佸疇顫夐崹鍧楀箖閳哄拋鏁婇柤娴嬫櫃缁辨ɑ绻濋悽闈涗粶妞わ缚鍗抽幆鍕敍閻愬弶鐎梺鍛婂姦閸犳牕娲垮┑鐘灮濞呫垻绮婚幋位鍥偨閸濄儱绁﹂梺鍦劋閸わ箓寮埀顒勫箯閸涙潙鐭楀璺侯煬娴兼粓姊婚崒姘偓鐑芥嚄閸洍鈧箓宕奸妷銉ョ彉濡炪倖甯掔€氼參宕戦敍鍕枑闊洦娲栭崹婵嬫煥濠靛棭妲哥紒顐㈢Ч閺屾盯顢曢妶鍛亖闂佸憡蓱閹瑰洭骞冨畡閭︾叆闁告洦鍘鹃悡澶愭倵鐟欏嫭绀冪紒顔肩焸閸┿儲寰勯幇顒夋綂闂佺粯顭囬。顔炬鏉堛劎绡€闁汇垽娼ф禒锕傛煕椤垵鐏︾€规洜鎳撶叅妞ゅ繐瀚幆鐐烘⒑瑜版帒浜伴柛妯款潐缁傚秴顭ㄩ崼鐔哄幐閻庡箍鍎遍崯顐ｄ繆閸ф鐓冩い鏍ㄧ⊕缁€鍐磼缂佹娲寸€规洏鍔戦、娑橆潩閿濆棛鈧即姊绘担鍛婃儓闁活剙銈稿畷鐗堟償閵娿儳鍘洪梺瑙勫礃椤曆囧垂閸屾稏浜滈柡鍐ㄥ€瑰▍鏇灻瑰鍐ㄢ挃缂佽鲸鎸婚幏鍛村传閸曨亜顥氶梻浣侯焾鐎涒晜绻涙繝鍐х箚闁告挷鑳堕惌娆愮箾閸℃ê鍔ゆ繛鍫涘姂濮婃椽宕滈幓鎺嶇凹濠电偛寮堕悧鐘诲蓟鐎ｎ喖鐐婇柕濞у拋鍟庨梻浣烘嚀椤曨厽瀵煎┑瀣垫晜闁割偅鍩冮崑鎾诲冀椤撶偤鍞跺┑鐘绘涧閸燁垶寮埀顒勬⒒娴ｈ櫣甯涢柛鏃€娲熼幃娲Ω閳轰胶锛熷┑掳鍊曢幊蹇涙偂閺囥垺鐓熸俊顖濐嚙婢ь垱绻涢崼鐔虹煉闁哄本娲熷畷鍗炍旈埀顒勫汲閿濆應鏀介柨娑樺閸樻挳鏌涢埡瀣瘈鐎规洘甯掗～婵嬫晲閸涱剙顥氶梻浣虹帛閸ㄥ吋鎱ㄩ妶澶嬪亗婵炲棙鍨瑰Λ顖炴煛婢跺﹦浠㈤柤姝岊潐椤ㄣ儵鎮欐潏鎹愨偓鍧楁煛鐏炲墽娲寸€殿噮鍣ｅ畷鎺戭潩椤掆偓缁狅絾绻濆▓鍨灈闁挎洏鍎遍—鍐╃鐎ｎ亣鎽曢梺鍛婄☉閻°劑宕愰悜鑺ョ厾闁煎湱澧楃涵鐐亜韫囷絽骞楃紒缁樼箞閸╂盯鍩€椤掑嫬纾兼慨姗嗗墰閵堫噣姊绘担鍛婃儓濠㈣泛娲畷婊冣攽鐎ｎ亞顔嗛梺鍛婄⊕濞兼瑧绮堥崼銉︾厾缁炬澘宕晶顕€鏌熼钘夌伌闁哄矉绲鹃幆鏃堝閳轰焦娅涢梻浣告憸婵敻銆冩繝鍥х畺闁跨喓濮撮悘鎶芥煙妫颁胶顦︽繛鍫涘妽缁绘繈鎮介棃娴讹綁鏌ょ憴鍕姢闁轰緡鍣ｅ缁樼瑹閳ь剙顭囪閺佸秷绠涢弴姘媰闂佸綊鏀遍…鍥窗閹邦喗宕叉繝闈涱儐閸嬨劑姊婚崼鐔衡棩缂侇喛娉涢—鍐Χ閸℃ê顦╅梺鍛娒肩划娆撶嵁閸儱惟闁宠桨鑳堕鎺戭渻閵堝棙绀€闁瑰啿绻樺鏌ユ倷閻戞ǚ鎷虹紓渚囧灡濞叉牗鏅堕懠顒傜＜閻庯綆鍋勯悘鎾煙椤曞棛绡€鐎殿喗鎸虫慨鈧柨娑樺楠炲秹姊洪崫鍕垫Ц闁绘鎸剧划濠氬冀瑜滈悗鑸点亜閺囨浜鹃梺鍝勭焿缂嶄線鐛Ο灏栧亾闂堟稒鍟為柛锝勫嵆濮婃椽宕崟顕呮蕉闂佺锕ュú鐔凤耿娓氣偓閺岋絾鎯旈婊呅ｉ梺绋款儏閹虫﹢骞冮悽绋跨睄闁逞屽墰閹广垹鈽夊锝呬壕闁汇垺顔栭悞楣冨冀閿涘嫮纾藉〒姘搐閺嬬喖鏌熼悷鐗堟悙妞ゆ洩绲块幏鐘裁圭€ｎ偒娼旈梻渚€娼х换鎺撴叏閻㈡潌澶娾攽鐎ｎ偆鍘介梺缁樏鑸靛緞閸曨厾纾煎ù锝堫潐鐏忥妇鈧娲橀崹鍧楃嵁濮椻偓瀵剟濡烽敂鑺ユ緫闂備浇顕ч崙鐣岀礊閸℃顩查柨婵嗩槸缁犳椽鏌￠崶鈺佷汗闁衡偓娴犲鐓熼柟閭﹀幗缂嶆垿鏌ｈ箛銉х暤闁哄本鐩崺鈩冩媴閸涘﹥顔掗柣搴ゎ潐濞叉﹢宕归崸妤冨祦婵☆垵鍋愮壕鍏间繆椤栨粎甯涢柣婵囧▕濮婅櫣娑甸崨顓濇睏闁荤偞绋忛崕鐢稿春閳ь剚銇勯幒宥囶槮濠⒀屽灡缁绘盯鎳濋柇锕€娈梺瀹狀潐閸ㄥ潡骞冨▎蹇ｅ晠妞ゆ柨鍚嬮宥呪攽閻樻剚鍟忛柛鐘冲哺瀵偊骞栨担鍝ヮ槴闂佸湱鍎ら崺鍫ュ触鐎ｎ亶鐔嗛悹鍝勩偨閿熺姵鏅濋柛灞剧〒閸橀亶姊洪崫鍕偍闁告柨鐭傞幃姗€鏌嗗鍡欏幐婵炶揪绲介幉锟犲窗濮椻偓閺屸€崇暆鐎ｎ剛袦濡ょ姷鍋涘ú顓€佸鈧幃銏ゆ惞閸忓鐎奸梻鍌氬€风粈渚€骞栭锔绘晞闁搞儯鍔庣粻楣冩煃瑜滈崜姘跺箞閵婏妇绡€闁告侗鍣禒鈺呮⒑瑜版帩妫戝┑鐐╁亾闂佹悶鍔戠粻鏍箹瑜版帩鏁冮柕鍫濆閺佹牜绱撻崒姘偓鎼佸磹妞嬪孩顐介柨鐔哄Т缁愭淇婇妶鍛櫤闁稿绻濋弻鏇熷緞閸℃ɑ鐝曢梺绋款儌閺呯娀寮婚敐澶婄闁挎繂妫Λ鍕煙椤栨粌鏋涙慨濠冩そ楠炴劖鎯旈姀銏犲汲濠电姭鎷冮崒婊呯厯闂佽鍨欢姘暦婵傜唯闁挎棁顫夌€氬ジ姊绘担鍛婂暈缂佸鍨块弫鍐Χ閸℃ê寮块梺閫炲苯澧存慨濠冩そ瀹曨偊宕熼鈧▍銈囩磽娴ｇ瓔鍤欐俊顐ｇ箖娣囧﹪鎮界粙璺ㄧ杸闂佸搫顦抽鎶藉煛閸涱喚鍘撻梺鍛婄箓鐎氼剟鍩€椤掑倹鏆鐐茬箳缁辨帒螣閼测晩鍟庨梺鍝勵槸閻楀棙鏅舵禒瀣畺濠靛倸鎲￠悡鐔兼煃閳轰礁鏆炴い銉ョ墢閳ь剝顫夊ú鐔奉焽瑜旈崺銏℃償閵娿儳顓洪梺缁橆焽椤ｎ喚妲愰懠顒傜＝闁稿本鑹鹃埀顒傚厴閹偤鏁冮崒娑欐珨濠电姷鏁搁崑鐐哄箚瀹€鍕獥婵娉涢悞鍨亜閹烘垵鏋ゆ繛鍏煎姈缁绘盯宕ｆ径娑溾偓璺ㄢ偓瑙勬礀缂嶅﹤鐣风粙璇炬棃鍩€椤掑倻涓嶉柡宥冨妿缁犻箖鏌涢埄鍏╂垹浜搁鐏诲綊鎳栭埡浣叉瀰闂佸搫鏈惄顖氼嚕閹绢喖惟闁靛鍎扮槐鐔虹磽閸屾瑦绁板ù婊庡墴瀵偆鎷犲顔界稁缂傚倷鐒﹁摫濠殿垰顕槐鎺戔槈濮楀棗鍓辩紓鍌氱Т閻楁挸顫忛搹鍦煓闁秆勵殢閳ь剚顨婇弻娑橆潩椤掑鍓跺Δ鐘靛仜閻楁挻淇婇幖浣哥厸濞达絽瀚囬崘鍓у數闁荤姾娅ｇ亸銊╁礉閻斿吋鐓ユ繛鎴炵懅閹冲洭鏌″畝瀣М闁诡喒鏅犻幃婊兾熺化鏇炰壕闁告劦鍠楅崑锝夋煃瑜滈崜鐔煎极閸愵喖纾兼繛鎴灻肩花濠氭⒒娴ｈ櫣銆婇柛鎾寸箘缁瑩骞掑Δ鈧壕濠氭煥濠靛棙鍟掗柡鍐ㄧ墛閺呮繂銆掑顒婅含闁绘稒绮撳娲焻閻愯尪瀚伴柛妯绘尦閺屾稓鈧綆鍋呯亸鎵磼缂佹绠撻柍缁樻崌瀹曞綊顢欓悾灞奸偗濠电姷鏁搁崑娑㈡儑娴兼潙绀夐柟杈惧瀹撲礁顭块懜闈涘缂佺姷鎳撻湁闁挎繂娲﹂崵鈧繛瀛樼矒娴滆泛顫忓ú顏勭闁圭粯甯婄花鑲╃磽娴ｇ瓔鍤欓悗姘嵆楠炲啴鎮滈挊澶庢憰闂侀潧顧€閼靛綊骞忛搹鍦＝濞达絽澹婇崕鎰亜閹寸偟鎳囩€规洘娲熼獮鍥偋閸垹骞堥梻渚€娼ч…鍫ュ磿閺屻儱纾婚柕澹偓閸嬫挸鈻撻崹顔界仌濡炪倖娉﹂崶鑸垫櫍婵犻潧鍊婚…鍫ユ煁閸ャ劊浜滈柟鏉垮缁夌敻鏌嶈閸撴瑥煤椤撶儐娼栫紓浣股戞刊鎾煕濞戞﹫宸ラ柡鍡楃墦濮婅櫣鎲撮崟顒€鈧劗绱掗悩宕囧ⅹ闁伙絿鍏橀幃褔宕奸悢宄板Τ闂備線娼ч…顓犵不閹寸偟顩峰┑鍌氭啞閸婄敻鏌ｉ悢鍛婄凡妞ゅ浚鍙冮弻娑氣偓锝庝悍闊剟鏌熼鍡欑瘈濠碉紕鍏橀崺锟犲磼濠婂啫绠為梻鍌欐祰椤顭垮Ο缁樻珷閹艰揪绲块惌娆忊攽閻樺磭顣查柣鎾跺枛楠炴牜鍒掔憴鍕垫綉闂佺粯鎸搁崥瀣箞閵婏妇绡€闁告侗鍣禒鈺呮⒑閻熸澘绾ч柟绋垮暱閻ｇ兘鎮㈢喊杈ㄦ櫇闂侀潧绻掓慨宀勫箣閻樼數锛濇繛杈剧悼椤牓鍩涢弮鍫熺叄闊洦鎹囬崣鍕偓瑙勬穿缂嶄礁鐣峰鈧垾锕傚箣濠靛浂鍚欐繝鐢靛Х閺佸憡鎱ㄩ悽鍛婂殞濡わ絽鍟悡渚€鏌涢妷顔煎闁绘挸绻愰…鍧楁嚋閻㈡鐏遍梺鍛婅壘閸婂潡寮婚悢鍏肩叆閻庯綆鍋佹禒銏犫攽椤旂》鍔熺紒顕呭灣缁參鎮㈤悡搴ｅ€為悷婊冪灱閼鸿鲸绂掔€ｎ偀鎷虹紓浣割儐椤戞瑩宕曢幇鐗堢厽闁冲搫锕ら悘锔筋殽閻愯韬柟顔哄灮閸犲﹥娼忛妸锔界彨濠电姷鏁搁崑鐐哄垂閸洘鍋￠柨鏇炲€归崑鐔兼煟閹达絽袚闁抽攱鍨块弻娑㈡晜鐠囨彃缁╁┑锛勫亾閹倿寮诲☉銏″亹闁归鐒﹂悿渚€姊虹拠鈥虫灀闁逞屽墯閺嬬厧危閸儲鐓忛煫鍥堥崑鎾诲棘閵夈儰澹曢梺鍓插亝濞叉﹢鎮￠悢鍏肩厵闂侇叏绠戦獮鏍磼閹绘帩鐓奸柡灞界Ч閺屻劎鈧綆鍋€閹峰湱绱撴担铏瑰笡闁烩晩鍨堕悰顕€骞樼拠鑼唺闂佸搫鍟犻崑鎾绘煙閼碱剙甯舵い顏勫暣婵″爼宕橀妸銉庘晠姊虹粙鎸庢崳闁轰礁顭烽悰顕€宕橀妸銏＄€婚梺瑙勫劤绾绢參鎮￠幋鐐电瘈闁靛骏绲剧涵楣冩煥閺囨ê鍔﹂柟顔缴戦幆鏃堬綖椤撶姷鐣鹃梻浣虹帛閸旓附绂嶅鍫濈劦妞ゆ帊绀侀悘瀵糕偓瑙勬礈閹虫挾鍙呭銈呯箰閸婄敻宕戦幘璇茬闁冲搫鍟伴惁鍫ユ⒑閹肩偛鍔€闁告洦鍎峰鑸碘拻濞撴埃鍋撻柍褜鍓涢崑娑㈡嚐椤栨稒娅犳い鏍仦閻撳繘鏌涢妷鎴濆枤娴煎啫螖閻橀潧浠﹂悽顖ょ節閻涱喚鈧綆浜栭弨浠嬫煙闁缚绨奸柛瀣噹閳规垿鎮╅幇浣告櫛闂佸摜濮甸惄顖炴晲閻愭潙绶為柟閭﹀幖娴滄姊洪悙钘夊姕闁告挻鑹鹃…鍥冀閵娧咁啎閻庣懓澹婇崰鏇㈠箟妤ｅ啯鐓涘ù锝呮啞椤ャ垽鏌＄仦鐣屝ユい褌绶氶弻娑㈠箻鐎垫悶鈧帡鏌涢幒鎾虫诞鐎殿噮鍣ｅ畷濂告偄閾氬倻绱﹂梻鍌欑閹诧紕绮欓幋锔芥櫇闁靛牆妫涢々鍙変繆閵堝懏鍣洪柍閿嬪灩缁辨挻鎷呴懖鈩冨灴閹繝濡烽埡鍌滃幈濠殿喗锕╅崜锕傚磿閺冨牊鐓欐い鏇炴缁♀偓婵犵绱曢崗姗€寮崒鐐茬鐟滃繐危閸ヮ剚鈷掗柛灞捐壘閳ь剚鎮傞幃褎绻濋崟顓犵厯闂佸湱鍎ら〃鍡涘疾椤掑倵鍋撻獮鍨姎婵☆偅姊婚幑銏ゅ幢濞戞瑧鍘卞┑鐐叉濞存艾危瑜版帗鐓忛柛銉ｅ妿缁犵偤鏌＄仦绯曞亾瀹曞洦娈曢柣搴秵閸撴稖鈪甸梻鍌欐祰濡椼劑鎮為敃鍌氱婵炲棗绻掗弳锕€鈹戦崒姘暈闁稿妫楅湁闁挎繂鎳庡Σ濠氭煙閽樺鍎旀慨濠傤煼瀹曟帒鈻庨幋鐘靛床闂備線鈧偛鑻晶浼存煕鐎ｎ偆娲撮柟宕囧枛椤㈡稑鈽夊▎鎰娇婵＄偑鍊栭悧妤冪矙韫囨梻顩叉繝濠傜墛閻撴盯鏌涢幇鍓佸埌濞存粓绠栧铏圭磼濮楀棙鐣兼繝娈垮枟閹告娊骞冩ィ鍐╃叆閻庯綆浜堕崵銈夋⒑閸濆嫷妲归柛銊╂涧閻ｇ敻宕卞☉娆屾嫼闂傚倸鐗婄粙鎾剁不閸愭祴鏀芥い鏃€鍎抽崢鎾煏閸℃洜绐旂€规洏鍔庨埀顒佺⊕鑿ら柟鐤缁辨帞绱掗姀鐘茬闂佺懓鍟跨换鎺戔槈閻㈠憡鍊锋い鎴濆綖缁ㄨ顪冮妶鍡楀Ё缂佹彃澧界划鍫⑩偓锝庡枟閻撴洟鏌嶇憴鍕姢濞存粎鍋撴穱濠囨倷椤忓嫧鍋撻弽顓炲瀭闁绘挸绨堕弸鏍煛閸ワ絾鍤嶉柛銉墯閺呮繈鏌涚仦鍓с€掗柛妯绘崌濮婃椽鎳為妷鍐句邯钘濋柦妯猴級閿濆宸濆┑鐐层仒缁ㄨ顪冮妶鍡楀Ё缂佹彃娼￠幆宀勫箳閺傚搫浜鹃悷娆忓缁€鈧悗瑙勬处閸撶喖宕洪姀鈩冨劅闁靛牆娲ㄩ弶鎼佹⒑閻熸澘鈷旀い銉﹀姉濞嗐垽濮€閵堝棌鎷婚梺绋挎湰閼归箖鍩€椤掍焦鍊愮€规洘鍔栭ˇ鐗堟償閿濆洨鍔跺┑鐐存尰閸╁啴宕戦幘鎼闁绘劕妯婂Ο鈧梺鎼炲妼婢т粙骞栭悙顒佸閻熸瑥瀚ㄦ禒銏ゆ⒑鏉炴壆顦﹂柛鐔告綑閻ｇ兘骞掗幋顓熷兊闂佽褰冮鍥嵁閵忋倖鈷掗柛灞剧懆閸忓瞼鐥鐐靛煟鐎规洘绮岄埞鎴﹀醇閵忋垻鍘梻浣侯攰閹活亞绮婚幋鐘差棜濠靛倸鎲￠悡蹇撯攽閻愰潧浜炬繛鍛噽缁辨帡鎮▎蹇斿闁绘挻娲橀妵鍕箛閸撲焦鍋у銈忕到瀵墎鎹㈠☉銏犲窛妞ゆ挾鍠庣粣娑㈡⒑濮瑰洤鍔村ù婊庝簻閻ｇ兘鏁愭径濞劎鎲歌箛娑欏亗闁瑰墽绮埛鎴︽煕濠靛棗顏繝鈧幍顔剧＜閻庯綆鍋呯亸鎵磼閸屾稑娴柡浣稿暣瀹曟帒顫濇鏍ф暭闂傚倷绀佺紞濠囧磻婵犲洤绀堥柨鏇楀亾閾荤偤鏌ｉ弬鍨倯闁抽攱甯掗妴鎺戭潩閿濆懍澹曢梻渚€鈧偛鑻晶浼存煕鐎ｎ偆娲撮柟宕囧枛椤㈡稑鈽夊▎鎰娇闂佽瀛╃粙鎺曞綘婵炲瓨绮嶇划鎾诲蓟閺囩喎绶炴繛鎴欏灪椤庡秹鏌ｈ箛鎾寸闁告瑥鍟村璇差吋閸ャ劌鐝伴梺鍝勮閸庡崬顕ｉ悧鍫㈢瘈婵炲牆鐏濋弸鎾绘煕鐎ｎ偅宕屾慨濠冩そ濡啫鈽夊顒夋毇婵犵妲呴崑鍛存偡閵夆晛鐓濈€广儱顦～鍛存煏閸繃顥戦柟鐤缁辨捇宕掑▎鎴濆闂侀潧妫涢崑銈夌嵁鐎ｎ喗鏅查柛鎰屽嫮娼栭梻鍌欑閹诧繝宕濋敃鍌氱獥闁哄稁鍋勯ˉ姘舵煠婵劕鈧劙宕戦幘鑽ゅ祦闁割煈鍠栨慨搴♀攽閳藉棗浜濈紒瀣尭椤曪綀顦归柛鈹惧亾濡炪倖甯掔€氼參鍩涢幒妤佺厱閻忕偟鍋撻惃鎴濐熆瑜庣粙鎾舵閹烘柡鍋撻敐搴′簻闁诲繑鎸抽弻娑㈠煘閹傚濠碉紕鍋戦崐鏍暜婵犲洦鍊块柨鏇炲€哥壕褰掓煙闁箑寮炬繛鍫滅矙閺岋綁骞囬浣叉灆濠碘槅鍨崑鎾绘⒒娴ｈ姤銆冮柣鎺炵畵楠炴垿宕堕鈧粻鏍煃閸濆嫭鍣洪柛銈嗗灦閵囧嫰骞掗幋顖氬闂佸憡鑹剧紞濠傤潖婵犳艾纾兼繛鍡樺姉閵堟澘顪冮妶搴′簻妞わ箓娼ч悾鐑藉即閵忕姷顔呴梺鍏间航閸庨亶鍩€椤掆偓閻栧ジ寮诲☉銏╂晝闁绘ɑ褰冩慨搴ｇ磼閻愵剙鍔ゆい顓犲厴瀵鎮㈤悡搴ｎ唹闂佸綊鍋婇崜娆撳箚閻愮儤鍊甸悷娆忓鐏忣偆绱掗懜闈涘摵鐎殿喛顕ч埥澶愬煑閳规儳浜鹃柨鏇炲€哥粻锝嗙節闂堟稒宸濆ù婊庝簻閳规垿鎮╅幇浣告櫛闂佸摜濮甸悧鐘诲蓟婵犲洦鏅查柛婊€鐒︾紞搴♀攽閻愬弶鈻曞ù婊勭箞瀹曟垿鏁撻悩宕囧幐婵犮垼娉涢鍛搭敋濠婂嫮顩叉繛鎴炵懁缁诲棝鏌ｉ幇鍏哥盎闁逞屽墯閻楃姴鐣疯ぐ鎺撳仺闁哄妫楀ú顓€佸☉銏″€烽柡澶嬪灣閹綁姊绘担铏瑰笡闁搞劌鍚嬮幈銊╁Χ婢跺﹦锛涢梺闈浤涢崨顖ょ床闂佽鍑界紞鍡樼閻愬顩烽柕蹇婃噰閸嬫挾鎲撮崟顒€纰嶅┑鈽嗗亝缁诲倿锝炶箛鎾佹椽顢旈崪浣诡棃婵犵數鍋為崹顖炲垂鐠囪尙鏆︽い蹇撴绾捐棄霉閿濆嫮鐭欓柛婵堝劋缁绘盯鎳犻鈧弸搴ㄦ煟閿濆洤鍘村┑顔瑰亾闂侀潧鐗嗛幊鎰邦敊閹烘梻纾介柛灞剧懅閸斿秹鏌ㄥ顑炲綊鎮埀顒勫储婵傜鐓橀柟杈鹃檮閸嬫劙鎮归崶鍥у暕缁憋綁姊虹拠鎻掝劉闁告垵缍婂畷鎶芥晲婢跺﹦鐣鹃悗鍏夊亾闁告洦鍋嗛濠囨⒑閸濆嫬鈧悂骞栭锝囶洸濡わ絽鍟崑鈩冪箾閸℃绠版い蹇ｄ簽缁辨帡鍩€椤掑嫬绀冩い蹇撴閿涙粌顪冮妶鍡橆梿濠殿喓鍊曢悾椋庝沪缂併垺顔旈梺缁樺姈瑜板啴寮抽敐鍛斀妞ゆ梻鎳撴禍楣冩⒒娓氣偓濞佳囨偋閸℃あ娑樜旀担渚锤濠德板€曢幊蹇涙偂濞嗘挻鐓曢煫鍥ㄨ壘娴滃綊鏌￠崱姗堣€块柡灞剧洴婵℃悂濡烽鎯ф倯闂備胶纭堕弬渚€宕戦幘鎰佹富闁靛牆妫楃粭鎺撱亜閿旇鐏￠柡鍛埣楠炴﹢顢欓悾灞藉箥婵＄偑鍊栧濠氭偤閺傚簱鏋旀繝濠傜墛閻撶喐绻涢幋婵嗚埞婵炲懎绉堕埀顒冾潐濞叉牜绱炴繝鍥モ偓浣糕枎閹炬潙浜楅柟鍏兼儗閸犳绱為幘缁樷拻闁稿本鑹鹃埀顒傚厴閹虫宕奸弴妯峰亾娴ｅ湱绡€闁稿本顨嗛悗娲⒑閸濆嫭鍌ㄩ柛銊ユ贡缁牊寰勭€ｎ剛顔曢梺绯曞墲椤ㄥ棛绮嬬€ｎ喗鐓曢柕鍫濇缁€瀣煛瀹€鈧崰鏍嵁閸℃稒鍋嬮柛顐亝椤ュ淇婇妶鍥ラ柛瀣灴瀹曞綊鎼圭憴鍕簥濠电偞鍨崹鍦不閿濆鐓熼柟閭﹀墰娴犳盯鏌涢敐搴℃珝婵﹥妞藉畷銊︾節韫囨埃鍋撻崹顔氱懓顭ㄩ崱妯笺€愬銈庡亜缁绘﹢骞栭崷顓熷枂闁告洦鍋呴悗顓㈡⒒娴ｅ憡鍟炴繛璇х畵瀹曟粌鈽夐姀鐘殿槱闂佽法鍠撴慨鐢稿煕閹达附鐓曟繛鎴烇公瀹搞儵鏌ｉ幒鎴犵Ш闁哄本绋撻埀顒婄秵閸嬪懐浜搁悽鐢电＜閺夊牄鍔嶇亸浼存煙瀹勭増鍤囨俊顐㈠暙閳藉顫滈崱妯肩П濠电姷鏁告慨鐢割敊閺嶎厼绐楅柟鎹愵嚙绾捐绻濋棃娑欑煑缂佽妫濋弻锝夊閵忊晝鍔哥紓浣插亾閻庯綆鍋佹禍婊堟煛瀹ュ啫濡挎い锝呭级閵囧嫰濡烽敂鍓х杽濠殿喖锕ㄥ▍锝囧垝閺冨牆骞㈡俊銈傚亾妞ゅ繐鐡ㄧ换娑㈠醇閻旂硶鎷婚梺閫炲苯澧い鏃€鐗犲畷鏉课旈埀顒勨€﹂崹顕呮建闁逞屽墴瀹曟椽鎮欓崫鍕吅闂佹寧姊荤划顖炲疾閳哄啰纾肩紓浣靛灩瀵噣鏌￠埀顒勬焼瀹ュ懏鐎梺璇″瀻閳ь剟寮ㄦ禒瀣叆婵炴垶锚椤忊晛霉閻橆偅娅嗗ǎ鍥э躬椤㈡洟濮€閻欌偓娴煎啴姊虹拠鈥虫珝缂佺姵鐗犻獮鍐煥閸涱垶鈹忛柣搴秵閸嬪懎鈻嶉崶顒佲拻濞达絿鎳撻婊勭箾閹绘帞效鐎规洘鍨块獮姗€宕滄担鐚寸床闂備線鈧偛鑻晶浼存煃瑜滈崜銊х礊閸℃稑纾诲ù锝呮贡椤╁弶绻濇繝鍌滃闁绘挻鐟ラ湁闁绘挸娴烽幗鐘崇箾閹冲嘲鍘鹃悷閭︾叆闁告洖鐏氶悾鑲╃磽娴ｄ粙鍝洪悽顖涱殔椤洩绠涘☉妯溾晝鎲歌箛娑欏仾闁告洦鍋€閺€鑺ャ亜閺冨倶鈧宕濋悢铏圭＜妞ゆ洖鎳庨悘锔筋殽閻愯尙绠荤€规洏鍔戦、娑樷槈濡崵鈧參姊绘担鍛婂暈婵炶绠撳畷鎴﹀磼閻愯弓绱跺┑掳鍊曢幊蹇涘煕閹烘嚚褰掓晲閸涱喖鏆堥梺鍝ュ枔閸嬨倝寮婚敍鍕勃閻犲洦褰冮～鍥ь渻閵堝啫鐏柣妤侇殔椤曘儵宕熼鍌滅槇闂佸憡娲﹂崜姘额敊閺囥垺鈷掑ù锝堝Г绾爼鏌涢悩铏鞍闁逛究鍔庨埀顒勬涧閹芥粓鎯岄崱娑欑厱闁逛即娼ч弸鐔兼煟閹捐泛啸闁汇儺浜鍫曞垂椤斿灝鐓樺┑鐘媰鐏炵晫浠紓浣虹帛閻╊垰鐣锋總绋课ㄧ憸蹇涘汲椤愨懇鏀芥い鏃傘€嬮弨缁樹繆閻愯埖顥夐摶鐐烘煕閹扳晛濡锋俊鎻掔墛閹便劌顫滈埀顒傛兜閹间礁鑸归柛婵嗗閺€浠嬫煟濡澧柛鐔风箻閺屾盯鏁愭惔鈩冪彎閻庤娲忛崹浠嬪箖閳╁啯鍎熼柨娑樺閸嬫帡姊婚崒姘偓椋庣矆娴ｅ湱鐝跺┑鐘叉搐绾捐銆掑锝呬壕閻庤娲樺ú鐔奉嚕婵犳艾唯闁挎洍鍋撳ù婊勵殜濡懘顢曢姀鈥愁槱缂備礁顑嗛幑鍥х暦閿濆绠荤紓浣诡焽閸橀亶姊洪棃娑辨缂佽尪濮ゆ穱濠囨偩瀹€鈧壕濂告煃瑜滈崜鐔煎春閳ь剚銇勯幒鎴濐仾闁绘挻娲熼弻锝夊棘閹稿骸鏆堥梺绋匡攻閸旀牠骞堥妸锔剧瘈闁告劏鏂傛禒銏犖旈悩闈涗沪闁告梹鐗犻獮鍡涘籍閸喐娅滈梺绋挎湰閸戠懓顭囬幘鍓佺＝闁稿本鑹鹃埀顒勵棑缁牊绗熼埀顒勩€侀弽顓炲耿婵炴垶锚閻庮參姊虹粔鍡楀濞堟棃鏌￠崟鈺佸姦闁哄矉缍侀獮鍥敆娴ｇ懓鍓电紓鍌欒兌婵绱炴笟鈧濠氬Ω閳轰胶鐫勯梺绋挎湰缁瞼绮敓鐘斥拺闁告繂瀚崳鎶芥煛閸涱垰孝妞ゎ偄绻愮叅妞ゅ繐瀚槐鍫曟⒑閸涘﹥澶勯柛瀣у亾闂佺顑嗛幑鍥х暦婵傜鍗抽柣鎰暜缁鳖噣姊绘担绛嬫綈鐎规洘锕㈠畷娲冀椤撗勬櫇婵炲濮撮鍡涙偂閻斿吋鐓忛煫鍥ㄦ礀鏍￠梺鍝ュ枔閸嬨倝寮诲澶嬬叆閻庯綆浜炴禒鑲╃磽娴ｄ粙鍝洪悽顖滃仱閸┾偓妞ゆ帒锕︾粔鐢告煕鐎ｎ偄娴€规洘娲熸俊鐑藉煛閸屾粌骞堥梺纭呭閹活亞妲愰弴鐘典笉闁圭粯宕ㄦ惔銊ョ倞鐟滄繈鐓浣典簻闁靛繆鍓濈粈瀣煛娴ｇ懓濮嶇€规洖鐖奸崺锟犲礃閳哄倻閽掗梻鍌氬€搁崐椋庢濮橆剦鐒界憸宥堢亱闂佸搫鍟崐褰掝敃閼恒儲鍙忔慨妤€妫楁晶濠氭煕閵堝棙绀冮柕鍥у瀵潙螖閳ь剚绂嶆ィ鍐┾拺缂侇垱娲橀弶褰掓煕鐎ｎ偅灏い顏勫暣婵″爼宕卞Δ鈧鎴︽⒑缁嬫鍎愰柟绋款煼婵＄敻宕熼锝嗘櫍闂佺粯鍔曢顓㈠煘濞戞氨纾藉ù锝呮惈鏍＄紓浣割儐閸ㄥ潡宕洪妷锕€绶炲┑鐐灮閸犲酣鍩為崘顔藉€锋い鎺嶈兌瑜板洭姊绘担鐑樺殌鐎殿喖鐖奸幃娲即閻樺吀绗夊┑鐐村灦鑿ゆ俊鎻掔墦瀵爼宕煎☉妯侯瀴濠电偛鎳忛幑鍥ь潖缂佹ɑ濯撮柛娑橈攻閸庢挸鈹戦悙鑼勾闁搞劏妫勯悾鐑芥偡閹冲﹥妞介、鏃堝礋椤撶偛绠為梻鍌欒兌閹虫捇顢氶鐔稿弿濡炲楠搁ˉ姘舵煕韫囨洦鍎犲ù婊勭矒閺屸€愁吋閸愩劌顬嬮梺鎰佸灡濞叉粎妲愰幒妤€鐒垫い鎺戝缁€鍐煃閻熻埇浠掔紒銊嚙椤啴濡堕崱妤€袝濠电媭婢€缁舵岸鎮￠鍕垫晢闁告洦鍓涢崢鎼佹煟韫囨洖浠滃褌绮欓崺銉﹀緞閹邦厽鍤夐梺鎸庣箓椤︿即鎮￠弴鐔虹瘈闂傚牊绋掗ˉ婊勩亜韫囧鈧繈寮婚悢铏圭煓闁割煈鍠楀▓濠氭⒑鐠団€虫灍妞ゃ劌鎳橀崺銏ゅ箻鐠囨彃鐎銈嗘婵倝顢欓崟顖涒拻濞达綀顫夐崑鐘绘煕鎼淬垻鐭掔€规洏鍔戦、姗€鎮欓幇顓熺闁宠鍨块弫宥夊礋椤愨剝婢€闂備胶顭堥敃銉╂偋濠婂牆鏋佹い鏇楀亾妤犵偞甯″顒勫传閸曨亜顥氭繝娈垮枟椤洭宕㈣椤曪綁顢氶埀顒勫蓟濞戙垹鐓涢柛灞剧矋閸掓稑螖閻橀潧浠滄い鎴濐樀瀵偊宕掗悙鏉戜患闁诲繒鍋犲Λ鍕不濞差亝鈷掗柛灞剧懆閸忓瞼绱掗鍛仸鐎殿喖顭锋俊鎼佸煛娴ｈ櫣鏋€闂備焦瀵х粙鎴犫偓姘煎弮椤㈡洘绂掔€ｎ偆鍘卞┑鐐叉濞存艾危閾忓湱纾奸柣妯垮吹閻ｆ椽鏌＄仦鍓ф创妞ゃ垺娲熼弫鎰板炊閼稿灚顔愬┑鐘垫暩閸嬫盯骞婃惔鈭舵椽濡歌椤洟鏌熼悜妯诲鞍缂傚秴娲弻鏇熺箾閸喖濮㈤梺鑽ゅ枑瑜板啴鍩為幋锔藉€烽梻鍫熺☉娴犳绱撴担铏瑰笡閽冨崬菐閸パ嶈含妤犵偞鐗楅幏鍛喆閸曨剛褰嗙紓鍌氬€搁崐鐑芥⒔瀹ュ鍨傞柣鎴炆戝▍蹇涙⒒閸屾艾鈧悂宕愰幖浣哥９闁绘垼濮ら崵鍕煕閹捐尙鍔嶉柛蹇旂矒閺屾盯顢曢敐鍡欘槬濠碘槅鍋呴敋闁靛棙甯掗～婵嬫晲閸涱剙顥氶梺璇叉唉椤煤濮椻偓瀹曞綊宕稿Δ鍐ㄧウ濠殿喗銇涢崑鎾搭殽閻愬弶澶勯柟宄版嚇閹兘骞嶉鍙帡姊婚崒姘偓椋庢濮橆剦鐒界憸鏃堝箖瑜斿畷鍗烆渻閵忥紕鈽夐摶鏍煕濞戝崬鏋涢柍褜鍓欓悥鐓庮嚕閸洖閱囨繛鎴灻‖瀣磽娴ｅ搫校闁稿孩濞婇垾锔炬崉閵婏箑纾繛鎾村嚬閸ㄤ即宕滄潏鈺冪＝濞达絾褰冩禍楣冩⒑閸撴彃浜栭柛銊ㄥ吹婢规洟宕楃粭杞扮盎闂佸搫鍟崐鍫曞焵椤掆偓椤戝鎮￠鍕垫晢闁告洦鍓涢崢鎼佹煟韫囨洖浠╂い鏇嗗嫪绻嗛柛褎顨嗛悡鍐喐濠婂牆绀堥柕濞у啰绛忔繝鐢靛У閼瑰墽绮堟径鎰€甸柨婵嗛婢ф彃鈹戦钘夆枙闁诡喖缍婂畷鎯邦槼闁崇粯娲樼换娑㈠箻閹颁胶鍚嬮梺鍝勬湰濞茬喎鐣烽悡搴樻斀闁搞儴鍩栭ˉ锝呪攽閻樻剚鍟忛柛鐘崇墵瀹曟劙宕稿Δ鈧拑鐔哥箾閹存瑥鐏╅柣鎾寸☉闇夐柨婵嗘噹椤ュ繐霉閻樺眰鍋㈤柡灞熷嫬顕辨繛鍡樺灩琚﹂梻浣告惈閼活垳绮旈悜閾般劍绗熼埀顒勫蓟濞戙垹绠婚悹铏瑰劋閻庤顪冮妶搴′簻缂佺粯锕㈤獮鏍亹閹烘挸浠梺鍝勵槹椤戞瑩宕靛▎鎾粹拻濞达絽鎲￠幆鍫熺箾鐏炲倸濮傜€规洑鍗抽獮鍥敆婢跺苯鏁搁梻浣告贡閸庛倝銆冮崱娑樼厱闁瑰濮风壕濂告倵閿濆骸浜介柛搴涘劦閺屾稒鎯旈姀鐘差潚闂佸搫鐬奸崰鏍х暦閵婏妇绡€闁告劑鍔夐崑鎾诲箛閻楀牏鍘撻梺闈涱檧闂勫嫰藟閸懇鍋撶憴鍕闁挎洏鍨介妴浣糕枎閹惧啿绨ユ繝銏ｎ嚃閸ㄦ澘煤閿曞倹鍋傞柡鍥ュ灪閻撳啴鏌嶆潪鎵槮闁哄鍊栫换娑㈠醇閻曞倽鈧潡鏌＄仦鍓ф创鐎殿噮鍣ｉ崺鈧い鎺戝缁犳牠鏌涚仦鎯у毈婵炲吋鐗楃换娑橆啅椤旇崵鐩庨悗鐟版啞缁诲倿鍩為幋锔藉亹闁圭粯甯楀▓顓㈡⒒閸屾凹妲哥紒澶屾嚀椤繐煤椤忓懎娈ラ梺闈涚墕閹冲繐袙閹扮増鈷戦柛婵嗗閸ｆ椽鏌ｉ埡濠傜仸妤犵偛鍟妶锝夊礃閳轰讲鍋撴繝姘參婵☆垯璀﹀Σ鍝勎旈悩鍙夋悙闁宠鍨块幃娆撳矗婢舵ɑ锟ラ梻浣侯焾椤戝棝骞戦崶褏鏆﹂柟鍓х帛椤ュ牊绻涢幋锝夊摵閻庨潧鐭傚娲濞戞艾顣哄┑鈽嗗亝椤ㄥ﹪骞冨Ο渚悑濠㈣泛顑囬崢鎼佹⒑閸涘﹦鐭嗘俊鐐村笧閼洪亶鎮剧仦绋夸壕闁割煈鍋呯欢鏌ユ煥閺囥劋绨婚柣锝呭槻椤劑宕遍埡鍌傤亪鏌ｆ惔銈庢綈婵炲弶鐗曢锝夊礈娴ｇ懓搴婂┑鐘绘涧椤戝棝藟閸喓绠鹃柟瀵稿仧閹虫洜绱掓潏鈺佷粶闁宠鍨块幃娆撴嚑椤掍胶妾ㄩ梻浣告惈閹冲繒鍒掗幘缈犵箚闁汇垻顭堢粈瀣亜閺嶃劍鐨戞い鏃€甯￠弻锝夋偐閻戞﹩浠╁┑鐐村絻閹虫ɑ鎱ㄩ埀顒勬煃閽樺顥炴い鏃€妫冨铏圭磼濡搫顫嶉梺璇″灠閼活垶鍩㈤幘鎰佺叆闁告洦鍓欏鎸庣節閻㈤潧孝閻庢凹鍠氶弫顔尖槈閵忥紕鍘甸悗鐟板婢ф宕抽悾宀€纾兼い鏃傛櫕閹冲洦顨ラ悙鏉戝闁诡垱妫冩慨鈧柕蹇婂濮椻偓濮婂宕掑顑藉亾妞嬪海鐭嗗ù锝夋交閼板潡姊洪鈧粔鎾偂閺囥垺鐓曟い鎰Т閸旀氨鐥幆褜鐓奸柡灞剧☉閳藉宕￠悙鍏哥泊闂備胶顭堥鍡涘箰婵犳艾绠柛娑欐綑缁€鍐煏婵炲灝鈧牠鎯堣箛娑欌拻濞撴埃鍋撻柍褜鍓涢崑娑㈡嚐椤栨稒娅犻柛鎾楀懐锛濋悗骞垮劚閹冲繘藟閻愮數纾奸柛灞炬皑鏁堥悗瑙勬礀閵堢顕ｉ幘顔藉亜闁炬艾鍊婚弳妤呮⒒閸屾瑧绐旀繛浣冲泚鍥敃閿曗偓閻ょ偓绻濇繝鍌滃闁稿鍊块弻锟犲炊閳轰焦鐎繛瀛樼矋缁捇寮婚悢鐓庣骇闁割煈鍣弳銏ゆ⒑鐠団€虫灕闁稿鍔楀Σ鎰板箳濡や礁浜圭紓浣圭〒椤㈠﹪鍩€椤掆偓濞硷繝寮?"
    if learner_signal == "blocked":
        return "If you get stuck again as soon as you start, show me the exact small section you were about to change and I will help you reduce it one step further."
    if mode == "direct":
        return "When you finish, do not just say 'done'; tell me what result you verified and I will help you choose the next move."
    if verbosity_bias == "short":
        return "Take that one step first, then bring back the result."
    return "Take that one step first, then bring back the result and we can decide whether to expand, review, or tighten the loop."


def _prefer_structured_next_step(
    *,
    scenario: str,
    next_step_hint: str,
    implementation_guide: dict[str, object],
    adaptation_guide: dict[str, object],
    principle_note: dict[str, object],
    project_ideas: list[dict[str, object]],
    exercise_prompt: dict[str, object],
) -> str:
    if next_step_hint:
        return next_step_hint
    value = exercise_prompt.get("prompt")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if scenario == "idea_implementation":
        value = implementation_guide.get("current_step")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if scenario == "project_adaptation":
        value = adaptation_guide.get("first_migration_step")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if scenario == "principle":
        value = principle_note.get("follow_up_exercise") or principle_note.get("apply_now")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if scenario == "project_idea" and project_ideas:
        value = project_ideas[0].get("first_step")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_next_step_hint_text(value: object | None) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("title", "label", "next_step", "nextStep", "summary"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


def _file_suffix(file_path: str | None, chinese: bool = False) -> str:
    if not file_path:
        return ""
    if chinese:
        return f"闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘辨繝鐢靛Т閸婂綊宕戦妷鈺傜厸閻忕偠顕ф慨鍌溾偓娈垮櫘閸ｏ絽鐣锋總鍛婂亜闁告稑顭崬鍫曟⒒閸屾瑨鍏屾い顓炵墦椤㈡牠宕卞☉妯碱唶闂佸憡鎸嗛崘銊т喊婵＄偑鍊栭幐楣冨磻閹邦儵锝夊醇閻斿墎绠氬銈嗙墬缁诲秹宕靛▎鎰闁告稑娲ゅú锕傚煕閹寸偟绠鹃柤濂割杺閸ゆ瑦顨ラ悙鎼疁闁哄矉缍侀幃銏ゅ矗婢跺褰嬮柣搴㈩問閸犳牠鈥﹂悜钘夌畺闁靛繈鍊曞婵嗏攽閻樻彃顏懖鏍ㄧ節瀵伴攱婢橀埀顑懎绶ゅù鐘差儏閻ゎ喗銇勯弽顐㈠壉闁轰椒鑳堕埀顒€绠嶉崕閬嵥囨导鏉戠厱闁瑰濮风壕濂告倵閿濆骸浜介柛搴涘劦閺屾稒鎯旈敍鍕唹闂侀潧娲ょ€氫即鐛€ｎ亖鏀介柟閭﹀幐閺嬪懘鏌ｆ惔銏╁晱闁哥姵鐩、姘愁樄闁糕斂鍎插鍕箛椤掑缍傞梻浣虹帛閿曘垹顭囪閹便劑宕奸弴鐔叉嫽婵炶揪绲介幉锟犲疮閻愮儤鐓曢柡鍐╂崌濡绢喚绱掗崒姘毙х€殿喕绮欓垾鏍敆婵犲嫮袦閻庤娲栭妶鍛婁繆閻戣姤鏅滈悷娆忓椤忓湱绱撻崒姘偓椋庣矆娓氣偓椤㈡牠宕奸妷銉э紵婵犵數濮甸悢顒傜礊閺嶎厽鐓ラ柡鍥╁仜閳ь剙缍婇幃锟犲即閵忥紕鍘搁梺绋挎湰缁诲啰娑甸崼鏇熷殐闁哄稁鍘介埛鎴︽煟閻旂顥嬮柣锝庡弮閺屾盯濡搁妷褏楔闂佺硶鏂傞崕鎻掝嚗閸曨垰绠涙い鎺戭槹缂嶅倿姊绘担铏瑰笡閽冭鲸銇勯弮鈧悧鐘茬暦閵夆晛宸濇い鏂垮⒔閻﹀牓姊哄Ч鍥х伈婵炰匠鍕浄婵犲﹤瀚换鍡樸亜閹板墎绉垫繛鍫燂耿閺岀喖鐛崹顔句紙濡ょ姷鍋炵敮锟犵嵁濡紮绱ｆ繝闈涙川閵堫偊姊婚崒娆掑厡缂侇噮鍨跺畷婵嬫晝閸屾氨顦┑鐐村灦閼圭偓鎱ㄩ鍕厓鐟滄粓宕滃▎鎾崇厴闁硅揪闄勯崐鐑芥煠绾板崬澧い锝嗘そ濮婅櫣鎷犻懠顒傤唹缂備浇顕ч悧鎾荤嵁閸愵煈娼ㄩ柍褜鍓熼獮鍐閵堝懐顦ч梺鍏肩ゴ閺呮盯鐛崼鐔虹瘈鐎典即鏀卞姗€鍩€椤掍焦灏电紒顔肩墛缁楃喖鍩€椤掑嫬鏄ラ柕蹇嬪€曢崡鎶芥煟濮楀棗浜滃ù婊呭亾缁绘盯宕煎┑鍫滆檸闂佸搫顑嗙粙鎺楀Φ閸曨垼鏁囬柣妯诲絻楠炲鎮楀▓鍨珮闁稿锕ら悾宄邦潨閳ь剟銆佸▎鎾村殐闁宠桨绀佽婵犵绱曢崑鎴﹀磹閺嶎偅鏆滈柟鐑橆殔閻ゎ噣鏌ｅΔ鈧悧蹇涖€呴弻銉︾參婵☆垯璀﹀Σ鎾煛閳ь剚绂掔€ｎ偆鍘介梺褰掑亰閸撴盯骞楅悩缁樺€堕煫鍥ч瀹撳棝鏌＄仦鍓ф创妤犵偛顑呴埞鎴﹀醇閳惰￥鍔戦幃妤冩喆閸曨剛顦銈庡亜椤︻垶鈥﹂崶顏嗙杸婵炴垶顭傞埡鍛叆闁哄啫鍊瑰▍鏇犳喐閻楀牏鎳囨慨?`{file_path}` 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欓崑宥夋⒑閹肩偛濡肩紓宥咃躬瀵崵鈧綆鍠栭悙濠囨煏婵炑冩噽濡插洭姊婚崒姘偓鎼佹偋婵犲嫮鐭欓柟鐑橆殔缁犲綊鏌熼柇锕€鏋ょ痪鎯с偢閺岀喖鏌囬敃鈧獮妯荤箾閹绘帞鎽犻柟渚垮妽缁绘繈宕橀埞澶歌檸闁诲氦顫夊ú蹇涘礉瀹ュ洦宕叉繝闈涙处閸庣喖鏌曡箛瀣仾婵炲牓绠栧铏规嫚閺屻儺鈧鏌涘Ο鑽ょ煉鐎规洘鍨块獮妯肩磼濡厧骞嶉梻鍌氬€搁崐鎼侇敋椤撯懞鍥晜閸撗咃紲闂佺粯锚绾绢厽鏅堕鈧彁闁搞儜宥堝惈婵犵鈧磭鍩ｇ€规洘甯掗～婵嬵敃閵忊晜顥￠梻鍌氬€搁崐椋庣矆娓氣偓閹潡宕堕‖顒佺洴瀹曠喖顢涢埀顒勫炊椤掑鏅梺缁樺姌鐏忔瑩宕㈠ú顏呭€垫鐐茬仢閸旀碍銇勯敂璺ㄧ煓鐎殿噮鍋婂畷鍫曞煛閸屾碍鐎鹃柣搴″帨閸嬫捇鏌嶈閸撶喖骞婇悙鐑樼劶鐎广儱妫楀▓鐔兼⒑闂堟冻绱￠柛婊€绀侀弲顓㈡⒒閸屾瑨鍏岀痪顓炵埣瀹曟粌鈹戠€ｎ亞顦梺鍝勬储閸ㄦ椽宕愰崼鏇熺厸閻忕偠顕ч崝婊堟煟閹惧鎳勯柕鍥у瀵噣宕掑☉娆戝涧闂備胶鎳撻崯鍨洪銏犺摕闁绘梻鈷堥弫濠囨煟閿濆懐鐏遍柣鎾亾闂備礁褰炵槐顔剧礊娓氣偓瀵鏁愭径濠勵啋闂佺懓澧庨悺鏃堝焵椤掍緡娈樼紒杈ㄥ浮閹晠妫冨☉妤侇潟婵犳鍠栭敃銈夆€﹀畡鎵殾闁圭儤鍨熼弸搴ㄦ煙閹碱厼骞楃悮锕傛⒒閸屾瑧顦︽繝鈧柆宥呯厱闁割偁鍎辩壕濠氭煕閺囥劌骞栫€殿喗鐓″缁樼瑹閳ь剙顭囪婢ф繈姊洪崫鍕櫤缂佸鎸荤粩鐔煎即閻樼數锛滃┑鈽嗗灥閸嬫劙顢欓弴銏♀拺閻熸瑥瀚崕妤呮煕濡灝袚缂佺粯鐩畷鍫曨敆娴ｅ搫甯楅柣鐔哥矋缁挸鐣峰鍐ｆ瀻闁规儳纾敍娆撴⒑瑜版帗锛熼柣鎺炵畵瀹曟垿鍩￠崨顔惧幗闂佺鎻徊楣兯夋径鎰厽闁归偊鍓ㄩ煬顒勬煛鐏炵晫效鐎规洦鍋婂畷鐔碱敃閿濆洣绮氱紓鍌氬€峰ù鍥ㄣ仈閹间焦鍋傞柍銉﹀墯濞?"
    return f" in `{file_path}`"


def _surface_context_text(text: str, *, chinese: bool) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    if not chinese:
        return cleaned
    if _looks_english_heavy(cleaned):
        return None
    return cleaned


def _looks_english_heavy(text: str) -> bool:
    alpha_count = sum(1 for char in text if char.isalpha() and char.isascii())
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return alpha_count > 8 and cjk_count == 0


def _append_unique_paragraphs(reply: str, additions: list[str]) -> str:
    resolved: list[str] = []
    for item in additions:
        cleaned = item.strip()
        if not cleaned:
            continue
        if _reply_mentions_excerpt(reply, cleaned):
            continue
        if any(_reply_mentions_excerpt(existing, cleaned) for existing in resolved):
            continue
        resolved.append(cleaned)
    if not resolved:
        return reply
    return f"{reply}\n\n" + "\n\n".join(resolved)


def _trim_sentence(text: str, limit: int) -> str:
    normalized = " ".join(text.split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _first_turn_guided_lane(scenario: str | None, learner_message: str) -> str:
    normalized = str(scenario or "").strip().lower()
    if normalized in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return normalized
    inferred_scenario = infer_coaching_scenario(
        learner_message,
        current_file=None,
        coach_context=None,
        default=normalized or "general",
    )
    if inferred_scenario in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return inferred_scenario
    inferred = _infer_guided_coaching_domain(
        learner_message,
        current_file=None,
        coach_context=None,
    )
    if inferred in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return inferred
    return normalized


def _resolve_first_turn_guided_lane(
    *,
    scenario: str | None,
    learner_message: str,
    reply: str,
) -> str:
    guided_lane = _first_turn_guided_lane(scenario, learner_message)
    if guided_lane in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return guided_lane
    inferred_from_reply = _infer_guided_coaching_domain(
        f"{learner_message}\n{reply}".strip(),
        current_file=None,
        coach_context=None,
    )
    if inferred_from_reply in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return inferred_from_reply
    return guided_lane


def _first_turn_lane_continuity_note(scenario: str, *, chinese: bool) -> str:
    if scenario == "remote_workspace":
        if chinese:
            return "鎴戜細缁х画鎶婅繖涓€杞暀鍦?VS Code remote 杩欐潯绾夸笂锛氬厛纭宸ヤ綔鍖鸿竟鐣屽拰鏂囦欢瀹為檯鍦ㄥ摢鍙版満鍣ㄤ笂锛屽啀鍐冲畾 credential move銆?
        return (
            "I will keep this in the VS Code remote lane: first prove the workspace boundary "
            "and where the files actually live, then decide the credential move."
        )
    if scenario == "debug_loop":
        if chinese:
            return "鎴戜細鍏堟妸杩欎竴杞敹鏉熸垚涓€涓彲淇＄殑 debug loop锛氬厛澶嶇幇涓€娆★紝鍦ㄧ涓€涓湁鎰忎箟鐨?state change 鍋滀笅锛屽啀妫€鏌ヤ竴涓€笺€?
        return (
            "I will keep this as one trustworthy debug loop: reproduce once, pause at the first "
            "meaningful state change, and inspect one value before we widen anything."
        )
    if scenario == "function_guidance":
        if chinese:
            return "鎴戜細鍏堟妸鍑芥暟鐞嗚В閿氬畾鍦ㄤ竴涓?live call site 涓婏紝鍐嶇敤 hover銆乻ignature help 鍜?definition 鎶?contract 璇荤ǔ銆?
        return (
            "I will keep this anchored to one live call site, then use hover, signature help, "
            "and definition until the function contract stops moving."
        )
    if scenario == "project_adaptation":
        if chinese:
            return "鎴戜細鍏堝垎娓呯幇鏈夐」鐩噷鍝簺蹇呴』绋冲畾銆佸摢浜涘繀椤绘敼鍙橈紝鍐嶈惤涓€涓獎鑼冨洿 adaptation銆?
        return (
            "I will keep this in the existing-project lane: first separate what must stay stable "
            "from what must change, then land one narrow adaptation before we widen scope."
        )
    return ""

def _first_turn_lane_next_step(scenario: str, *, chinese: bool) -> str:
    if scenario == "remote_workspace":
        if chinese:
            return "涓嬩竴姝ワ細鍛婅瘔鎴戝綋鍓嶅伐浣滃尯鏄?SSH銆乼unnels銆乨ev container銆乄SL 杩樻槸 local锛屽啀缁欐垜涓€涓綘鑳界湅鍒扮殑鐪熷疄璺緞鎴栦富鏈烘爣绛俱€?
        return (
            "Next step: tell me whether this workspace is SSH, tunnels, dev container, WSL, "
            "or local, and give me one real path or host label you can see."
        )
    if scenario == "debug_loop":
        if chinese:
            return "涓嬩竴姝ワ細鍛婅瘔鎴戜綘鍑嗗鍏堝仠鍦ㄥ摢閲岋紝浠ュ強浣犲噯澶囧厛妫€鏌ュ摢涓€涓€笺€佸垎鏀垨 stack frame銆?
        return (
            "Next step: tell me where you will pause first and which single value, branch, "
            "or stack frame you expect to inspect there."
        )
    if scenario == "function_guidance":
        if chinese:
            return "涓嬩竴姝ワ細缁欐垜鍑芥暟鍚嶅拰涓€涓綘鐜板湪灏辫兘鎵撳紑鐨?call site锛屾垜浠啀浠庨偅閲岃鍙傛暟銆佽繑鍥炲€煎拰涓婁笅鏂囥€?
        return (
            "Next step: give me the function name and one call site you can open right now, "
            "and we will read the parameters, return value, and context from there."
        )
    if scenario == "project_adaptation":
        if chinese:
            return "涓嬩竴姝ワ細鍛婅瘔鎴戝摢涓幇鏈夋ā鍧楁垨琛屼负蹇呴』绋冲畾銆佸摢涓€閮ㄥ垎蹇呴』鏀瑰彉锛屼互鍙婁綘鎯冲厛閫傞厤鐨勭涓€閬撹竟鐣屻€?
        return (
            "Next step: tell me which existing module or behavior must stay stable, which part "
            "must change, and the first boundary you want to adapt."
        )
    return ""

def _compact_first_turn_reply(
    reply: str,
    *,
    chinese: bool,
    scenario: str | None = None,
    learner_message: str = "",
) -> str:
    paragraphs = [part.strip() for part in reply.split("\n\n") if part.strip()]
    if not paragraphs:
        return ""

    kept: list[str] = []
    for paragraph in paragraphs:
        lowered = paragraph.lower()
        if lowered.startswith("##") or lowered.startswith("###"):
            continue
        if lowered.startswith("- ") or lowered.startswith("* "):
            continue
        kept.append(paragraph)
        if len(kept) >= 2:
            break

    if not kept:
        kept = paragraphs[:2]

    trimmed = [_trim_sentence(item, 112 if chinese else 142) for item in kept[:2]]
    first = trimmed[0] if trimmed else ""
    guided_lane = _resolve_first_turn_guided_lane(
        scenario=scenario,
        learner_message=learner_message,
        reply=reply,
    )
    guided_note = _first_turn_lane_continuity_note(guided_lane, chinese=chinese)
    guided_close = _first_turn_lane_next_step(guided_lane, chinese=chinese)
    if guided_note and guided_close:
        second = guided_note
        close = guided_close
        return "\n\n".join([part for part in (first, second, close) if part.strip()])
    second = (
        trimmed[1]
        if len(trimmed) > 1
        else (
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棗鏆欏┑鈥炽偢閺屽秷顧侀柛鎾存皑閹广垽宕煎┑鎰婵犵數濮甸懝楣冨础閹惰姤鐓熼柡鍐ㄦ处椤忕姵銇勯弮鈧ú鐔奉潖閾忓湱纾兼俊顖氭惈琚濋梻浣告啞閹歌鐣濋幖浣哥畺闁汇垻顭堢猾宥夋煕椤愩倕鏆遍柟閿嬫そ濮婅櫣娑甸崨顓濇睏闂佺顑嗙粙鎺撶┍婵犲啰闄勯柛娑橈功閸樿鲸绻濋悽闈浶㈤柛瀣閹剝绺介崨濠勫幈闂佸疇顫夐崕铏閻愵兛绻嗛柣鎰典簻閳ь剚鐗滈弫顕€骞掑Δ鈧粣妤佹叏濮楀棗澧婚柣鎺嶇矙閺岀喖鏌囬敃鈧獮妯肩磼閻樿崵鐣洪柡灞剧☉閳诲氦绠涢敐鍠般劍绻濋埛鈧仦濂稿仐闂佽鍣换婵囦繆閼搁潧绶為悗锝庡墮瀵娊姊绘担鍛婃儓婵炲眰鍔戝畷鎴濃槈濞嗘埈娲搁梺瑙勵問閸犳氨澹曢悾灞稿亾楠炲灝鍔氭俊顐ｇ⊕閺呭爼鎮介崨濠勫幐閻庡厜鍋撻悗锝庡墰閻﹀牓鎮楃憴鍕闁绘牕銈稿畷娲晸閻樿尙鍔﹀銈嗗笒閸婂綊锝為弴鐘亾鐟欏嫭绀€婵炶绠撳畷浼村箛閻楀牏鍘藉┑掳鍊愰崑鎾绘煟濡も偓濡稓鍒掗銏犵闁哄啫鍊婚敍婊堟⒑闁偛鑻晶瀵糕偓瑙勬礃鐢繝骞冨▎鎴斿亾閻㈡鐒炬鐐茬墦濮婄粯绻濇惔鈥茬盎濠电偠顕滅粻鎾诲箠濠靛鍊锋い鎺戝亞濞叉悂姊洪棃鈺佺槣闁告ê澧芥竟鏇熺附閸涘﹤鈧敻鏌ㄥ┑鍡欏嚬缂併劏鍋愰埀顒傛嚀閹诧紕鎹㈤崟顓燁潟闁圭儤鎸荤紞鍥煏婵犲繒鐣遍梻澶婄Ч濮婃椽鎮烽弶鎸幮╅梺纭呮珪閿曘垽鎮伴鈧獮妯兼嫚閼碱剦鍞洪柣搴＄畭閸庨亶骞忕€ｎ€稑顭ㄩ崼鐔叉嫽闂佺鏈懝楣冨焵椤掑倸鍘撮柟铏殜瀹曞ジ寮村璇蹭壕闁挎洖鍊搁柋鍥煏婢舵稓鐣遍柛鎾瑰煐缁绘繈妫冨☉妯峰亾婵犳埃鈧箓宕奸姀鐙€妫滄繝鐢靛У绾板秹鎮￠悢鍏肩厵闂侇叏绠戦弸娑㈡煕閺傛鍎旈柡灞剧〒閳ь剨缍嗘禍婊堝焵椤掆偓濞尖€愁嚕婵犳碍鏅搁柣妯垮皺閸婄偤姊虹€圭姵銆冮柣鎺炵畵閹顢橀悢铏诡啎闁诲孩绋掗…鍥儗鐎ｎ剛纾兼い鏃囧Г瀹曞瞼鈧鍠栭…鐑藉箖閵忋倕绀傞柤娴嬫櫅婵椽姊绘担鐟邦嚋婵炴彃绉瑰畷鎴﹀箻缂佹鍘搁柣搴秵閸嬪棝濡撮幒妤佺厓鐟滄粓宕滃杈╃煓闁圭儤姊瑰畷鏌ユ煕椤愶絿绠ユ繛鍏肩墵閺屟嗙疀濮樺吋缍堥柣搴㈢瀹€鎼佸蓟濞戞ǚ鏋庨煫鍥风稻妤旀俊鐐€愰弲婵囨櫠濡ゅ啯宕叉繛鎴炲焹閸嬫挸鈽夊▎妯煎姺闂佹椿鍘归崐鏇㈡箒濠电姴锕ょ花鑲╄姳缂佹ǜ浜滈柡鍥朵簽閹ジ鏌熸搴⌒㈤棁澶愭倵閿濆骸浜芥繛鍏兼⒐缁绘繈鎮介棃娑楃捕濠碘槅鍋呴悷鈺佺暦绾懌浜归柟鐑樻尭閸撱劑姊洪崜鎻掍簴闁稿孩鐓￠崺娑㈠箣閿旂晫鍘卞┑鐐村灦閿曨偊寮ㄧ拠宸唵閻犲搫鎼顓㈡煛鐏炲墽銆掗柍褜鍓ㄧ紞鍡樼濠婂牆鐒垫い鎺戝亞閻掑墽鈧鎸哥€氭澘顫忛搹瑙勫枂闁告洦鍋掑Λ鍡樼節閳封偓閸曞灚鐤侀梺绯曟櫆閻╊垶鐛€ｎ喗鏅滈柦妯侯槷閸栨牠姊绘担瑙勫仩闁稿氦宕靛濠偯洪鍕紱闂佺懓澧界划顖炲箚閻愭番浜滈柟鎵虫櫅閳ь剚鎹囬弻鍥敍閻愮补鎷婚梺绋挎湰閻熝囧礉瀹ュ鐓欐い鏃囧亹閸╋絿鈧娲滈幊鎾跺弲濡炪倕绻愰幊搴㈢濡ゅ懏鈷戦悹鎭掑妼閺嬫柨鈹戦鑺ュ唉鐎殿喕鍗虫俊鐑藉煛閸屾粌甯鹃梻濠庡亜濞层倝鏁冮妶鍡樻珷闁哄被鍎查悡鏇㈠箹鏉堝墽鍒伴柡瀣洴閺岋紕浠﹂悾灞澭囨煛鐏炶濮傛い銏＄☉椤繈顢曢姀鈺傤棥闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敂缁樻櫈闂佸憡绋戦悺銊╂偂閳ь剟姊洪幐搴ｇ畵妞わ富鍨堕幏鎴︽偄閸忚偐鍘介梺鍝勫暙濞层垽鍩€椤戣棄浜鹃梻浣侯焾椤戝棝骞愰幖浣哥叀濠㈣泛艌閺嬪孩淇婇婊冨付濠殿喛娅ｇ槐鎾诲磼濞嗘帒鍘℃繝娈垮枙閸楀啿鐣烽弴銏″仺缂佸鍎婚幗鏇炩攽閻愭潙鐏熼柛銊ф嚀濞插潡姊绘担鍛婂暈闁告梹鍨垮畷婵囧緞閹邦剛锛涢梺鍦亾缁剁偤寮崼婵堫槰闂佸啿鎼敃銉х礊濡ゅ懏鈷掑ù锝囩摂濞兼劗鈧娲橀敃銏ゃ€佸鎰佹Ь婵犮垼顫夊ú鐔风暦濡ゅ懎绀傞柣鎾抽娴煎孩绻濆▓鍨灍妞ゃ劌鎳庤灋婵°倕鎳庨崒銊╂煙缂併垹鏋熼柣鎾存礋閹鏁愭惔鈥茬凹閻庤娲栭惉濂稿焵椤掑喚娼愭繛璇х畵瀹曟垶绻濋崘褏绠氶梺姹囧€ら崹鐓幬ｆィ鍐┾拺缂備焦蓱鐏忣厽銇勯幋婵愭Ц妞ゎ偄绻樺畷顐﹀礋閹冲嘲娲ら悙濠勬喐韫囨梻顩峰┑鍌氭啞閳锋垹鐥鐐村闁搞倕顑囩槐鎺旂磼濡偐鐣靛銈嗘穿缂嶄線鐛幘璇茬闁糕剝蓱閺夋悂姊虹拠鎻掑毐缂傚秴妫濆畷鎴﹀幢濞戞ê鍋嶅銈呯箰閻楀﹪藟婵犲啨浜滈柟鎵虫櫅閻忣亪鏌熼崗鐓庡闁靛洤瀚伴獮瀣攽閸パ勭暬闂備胶纭堕弬渚€宕戦幘鎰佹富闁靛牆妫楃粭鍌炴煟閹虹偛顩紒顔肩墦瀹曞ジ濮€閵忣澁绱叉俊鐐€栧褰掝敄濞嗘挸鍚规繛鍡樺姂娴滄粍銇勯幇鍓佹偧缂佺姷鍋ら弻鐔兼惞椤愩倗鐓夐梺璇″枙缁瑥螞閸愩劉妲堟俊顖濆亹閺変粙姊婚崒姘偓鎼佸磹妞嬪孩顐芥慨妯挎硾閻掑灚銇勯幒宥堝厡闁宠棄顦遍埀顒冾潐閹哥螞濞嗘垶宕叉繛鎴炵懄婵挳鏌涢幇顒€绾ч柟鍏煎姍閺屾盯骞嬮悩娈嬶絿绱掔紒妯兼创妤犵偛顑夐幃娆戔偓闈涙啞椤撹崵绱撴担鍝勪壕闁稿孩濞婃俊鍫曞箹娴ｆ瓕鎽曢悗骞垮劚閻楁粌顬婇妸鈺傗拺闁告稑锕ョ亸浼存煟閳哄﹤鐏︾€规洘妞介崺鈧い鎺嶉檷娴滄粓鏌熼悜妯虹厐闁告梻鍠撶槐鎺撳緞鐏炵偓姣堥梺鍝勬湰缁嬫捇鍩€椤掑﹦宀涢柡鍛箞瀹曟繂顓奸崶鈺冿紲闂佺鏈銊ョ摥婵＄偑鍊ら崢褰掑礉閹存繄鏆﹀┑鍌氭啞閸嬪嫰鏌涘┑鍡楊仼缂佺姰鍎靛濠氬磼濞嗘帒鍘″銈冨灩閿曨亪鏁愰悙鏉戠窞闁归偊鍓涢ˇ顕€姊洪崫鍕枆闁稿鎳樺畷妤€顭ㄩ崗鐐閺佹劙宕ㄩ鐔割唹闂備胶绮幐濠氭儎椤栫偛绠栨俊銈呮噺閺呮煡骞栫划鍏夊亾閼碱剙鍤┑锛勫亼閸婃垿宕曢柆宥嗗亱闁规崘顕ч拑鐔兼煃閵夈儳锛嶉柡鍡楁閹鏁愭惔鈥愁潻闂佺硶鏅涢惌鍌氼潖閾忓厜鍋撻崷顓炐ｆい銉ヮ槹閵囧嫰鏁冮崒娑欓敪濡炪倖娲╃紞浣哥暦閹扮増鍋嗗ù锝呭ⅲ閳轰讲鏀介柣妯诲墯閸熷繘鏌涢敐搴＄仯缂侇喖顭烽獮瀣晝閳ь剟鎮″鈧弻鐔告綇閹呮В闂佽桨绀侀敃锕傛儉椤忓牜鏁囬柕蹇婂墲閺嗙娀姊烘潪鎵妽闁稿孩濞婇崺鐐哄箣閿旇姤娅栭梺鍛婃处閸嬪倿宕Δ鈧埞鎴﹀煡閸℃ぞ绨婚柣搴㈢煯閸楁娊鐛崘鈹垮亝闁告劏鏅涢埀顒冨吹缁辨帒鈽夊鍡楀壉闂佸搫鎳忕换鍫濐潖濞差亜绠伴幖娣灮閿涙洟姊虹粙娆惧剱闁圭澧藉Σ鎰板箳濡も偓閻掑灚銇勯幒鎴濃偓鐢稿磻閹剧粯鏅查幖绮光偓鑼寜濠电偛鐡ㄧ划宥囧垝閹捐钃熼柣鏂垮悑閸婇攱銇勯幒鍡椾壕婵犫拃灞界仭濞ｅ洤锕獮鎾诲箳閺傝法鍘介梻浣告惈閺堫剟鎯勯娑楃箚闁归棿绀佹儫闂佹寧妫侀濠囧传濡ゅ懏鈷掑ù锝囧劋閸も偓缂備胶濮寸粔鐟扮暦绾懌浜归柟鐑樺灩閸欌偓濠电姰鍨煎▔娑⑩€﹂鈧…鍥煛閸屾ü绨婚梺瑙勬緲婢у酣宕氶弶搴撴斀妞ゆ牗鐟ュ畵鍡樻叏婵犲嫮甯涢柟宄版噺缁楃喖顢涘鍐ㄐ梻鍌欑閹碱偊鎮у鍫濈婵炲棙鎼紞鏍ㄧ節闂堟侗鍎忛幆鐔兼⒑閹稿孩纾甸柛瀣尰閵囧嫰寮撮～顓熷枤闂佸搫鏈惄顖炪€侀弴銏″亹闁圭粯甯掗～姘舵⒒娴ｇ懓鈻曢柡鈧柆宥呭瀭闁革富鍘介～鏇㈡煙閻戞﹩娈㈤柡浣哥У缁绘盯骞嬮悙鍨櫘濡炪倧璐熼崝鎴濐潖濞差亜浼犻柛鏇炵仛绗戠紓鍌氬€哥粔鎾晝椤忓嫷鍤曢悹鍥ㄧゴ濡插牊鎱ㄥ鍫㈠埌濞存粓绠栭弻銊モ攽閸℃侗鈧霉濠婂嫮绠為柟顔筋焾缁犳盯鏁愰崨顓狀啈闂備線娼уú銈団偓姘嵆閵嗕線寮崼婵堫槹濡炪倖鍔х徊楣冾敊閹烘垟鏀介柣妯活問閺嗩垶鏌嶈閸撴瑧澹曢銏犳槬闁挎繂娲犻崑鎾舵喆閸曨剛顦ラ悗瑙勬处閸撴繈鎮橀崘顔解拺闁告稑锕ゆ竟鍐煕濞戝崬鐏辨俊鍙夋緲閳规垿鎮╅崹顐ｆ瘎婵犳鍠氶崗妯侯嚕椤愶箑绠瑰ù锝呮憸閿涙稑鈹戦悙鏉戠亶闁瑰磭鍋ゅ畷鍫曨敆閳ь剛鐥娣囧﹪顢曢敂鑺ラ敪闂佸湱鈷堥崑濠囧灳閿曞倸惟闁宠桨绀佺粣娑橆渻閵堝棙灏甸柛瀣枑缁傚秵瀵肩€涙ǚ鎷绘繛杈剧悼閹虫捇顢氬鍛＜閻犲洦褰冮埀顒冨劵濡喎顪冮妶鍡欏缂侇喖娴锋禍鎼佹偨绾版ê浜炬鐐茬仢閸旀碍銇勯敂鍨祮闁诡噯绻濆鎾偄缂堢姷鐩庨梻浣筋潐婢瑰寮插☉銏犵劦妞ゆ帊鐒︾粈瀣偓娈垮枟閹倸顕ｉ鈧畷濂告偄閸濆嫬绠炲┑鐘愁問閸犳銆冮崨顓囨盯寮崼鐔哄姺濡炪倖鐗楃粙鎺楀矗韫囨挴鏀介柣妯哄级閸ｇ儤銇勮箛鏇炩枅闁哄本鐩浠嬪Ω瑜嶉埛宀勬倵濞堝灝鏋熼柟鍛婂▕楠炲啫鈻庡婵嗘贡閳ь剨缍嗛崑鍕偟閼哥數绡€缁炬澘顦辩壕鍧楁煕鐎ｎ偄鐏寸€规洘鍔欓獮瀣晝閳ь剛绮堟径灞稿亾閸忓浜鹃梺鍛婃处閸撴瑦绂嶆潏銊х瘈闁汇垽娼у瓭濠电偛鐪伴崐婵嬪箖閹稿簺鍋呴柛鎰ㄦ櫇閸橆亝绻濋姀锝嗙【婵☆偅鐟ラ埢宥夊幢濞戞瑧鍘撻梻浣哥仢椤戝懐绮幒妤侇梿濠㈣埖鍔栭悡銉︾節闂堟稒顥炵€瑰憡绻堥弻鐔兼寠婢跺ň鍋撻崸妤€钃熸繛鎴欏灩鍥撮梺鍛婁緱閸樿棄鈻撴繝姘拺闁告繂瀚﹢浼存煟閳哄﹤鐏″ǎ鍥э躬楠炴牗鎷呯憴鍕彇闂備線鈧偛鑻晶鎾寠閻斿吋鍊甸柨婵嗛閺嬬喖鏌ｉ幘鍐叉殶闁硅尙顭堥…銊╁醇濠靛牜妲舵繝娈垮枟椤牓宕洪弽顓炵？婵°倓闄嶆禍婊堟煛閸ヮ煈娈斿ù婊堢畺閹鎲撮崟顒傗敍缂備胶绮换鍫ユ偘椤旇姤鍎熼柕濠忕畱閻у嫭绻濋姀鐘插辅闁哄倸鍊垮畷鏇㈡焼瀹ュ棛鐣抽梻鍌欑劍鐎笛呮崲閸屾娲Ω閳轰絼銉モ攽閻樺弶澶勯柣鎾寸洴閹鏁愭惔婵嬪仐闂佸憡鐟ョ€氫即寮婚垾宕囨殕闁逞屽墴瀹曚即寮介鐘茬ウ闂佺硶鍓濋崙鐟拔ｆィ鍐┾拺闁圭娴烽埥澶岀磼婢跺本鏆┑锛勬暬瀹曠喖顢欓幆褎鏆愰梻鍌欑劍閹爼宕曢鐐茬濠㈣埖鍔曠粻顖炴煣韫囨挻璐＄痪鍙ョ矙閺屾稓浠﹂崜褎鍣梺鍛婃煥缁夊綊骞忛幋锔界劶鐎广儱妫楅埀顒€鐖奸悡顐﹀炊妞嬪骸鍩岄悗娈垮櫘閸ｏ綁寮婚悢纰辨晩缂佹稑顑嗛悿渚€鎮楃憴鍕缂傚秴锕妴渚€寮撮姀鐙€娼婇梺闈涚箞閸ㄦ椽宕甸崘顔解拻濞达絿鐡旈崵娆撴⒑鐢喚鍒版い顓炴穿椤︾懓鈹戦垾鍐差暢缂侇喗鐟ч幑鍕Ω閿旂瓔鍟庨梻鍌欑窔濞佳嗗櫣闂侀€炲苯澧寸€规洘鍨块獮姗€寮妷锔绘綌婵犵數鍋涢幊鎾淬仈缁嬭法鏆嗛柟闂磋兌瀹撲線鐓崶銊︾缁炬儳鍚嬫穱濠囶敍濠靛棔姹楀銈嗘⒐濞茬喖寮婚埄鍐ㄧ窞濠电姴瀚。鐑樼節閳封偓閸屾粎鐓撻悗瑙勬礃绾板秶鈧絻鍋愰埀顒佺⊕椤洭宕㈤悽鍛婄厽闁绘ê寮堕崢鍌炴煕濞戝崬鐏ｆ俊鎻掓喘閺岋絾鎯旈妶搴㈢秷濠电偠顕滅粻鎾崇暦瑜版帒閱囬柡鍥╁仧閻ｅ搫鈹戦悙鍙夘棞闁告柨寮堕幆鏃堚€﹂幋鐐存珗闂佽崵濮垫禍浠嬪礉鎼粹檧鏋栭柛褎顨嗛埛鎺楁煕鐏炲墽鎳呯紒鎰⒐缁绘稒鎷呴崘鍙夌闁逞屽墾缁犳捇銆佸鈧幃鈺呭礂閸濄儳鎲归梻鍌欒兌閹虫捇顢氶銏犵；闁绘劕鎼惌妤呯叓閸ャ劍鎯勯柣鏂挎閹娼幏宀婂妳闂佺楠稿ù椋庢閹烘梹瀚氶柛娆忣樈濡箓姊洪崫鍕拱缂佸鍨块崺銏℃償閵堝洨鏉搁梺鎸庣箓閺屽﹪鏁傞悾宀€鐦堝┑鐐茬墕閻忔繈寮稿☉姘辩＜濠㈣泛锕﹂崺锝夋煕閳规儳浜炬俊鐐€栫敮濠勬閿熺姴鐤煫鍥ㄧ⊕閻撴洟鏌ｅΟ璇插婵炲牊绮嶉〃銉╂倷閺夋垵顫掗梺鍦帶缂嶅﹪銆侀弴銏℃櫜闁告侗鍘虹槐鐔兼⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栨稒娅犻柟缁㈠枟閻撴稓鈧厜鍋撻悗锝庡墮閸╁矂鏌ф导娆戞偧闁汇儺浜獮蹇撶暆閸曨偅鎳欐繝鐢靛仜閻楀﹥绔熼崱娆愵潟闁规儳顕悷褰掓煃瑜滈崜姘辩矉瀹ュ鍤嬮柣銏☆問濞叉悂鏌ｉ悩鐑樸€冮悹鈧敃鈧…鍥冀椤愩倗锛濇繛杈剧秬閸嬪倿骞嬮悙鎻掔亖闂佸湱铏庨崰妤呮偂閻斿吋鐓熼柡鍐ㄥ€哥敮璺好瑰鈧崡鎶藉蓟濞戙垹围闁告粈绀侀崜宕囩磽娴ｄ粙鍝洪柟绋款煼楠炲繘宕ㄩ婊堚攺闁诲函缍嗘禍婵嬵敊閸曨垱鈷掑ù锝勮閻掗箖鏌ㄩ弴妯哄鐎规洘娲滈幏鐘诲矗閸屾稓娲撮柟顔哄灲瀹曨偊濡疯閸熷酣姊绘担鍛婃儓妞わ缚鍗冲畷褰掓偨缁嬭法鐣洪梺鐟邦嚟閸嬬喓绮绘ィ鍐╃厱闊洦鑹炬禍褰掓煙閸愬弶鍠橀柡宀€鍠栭、娆撳礂閻撳簼娣梻浣筋嚃閸犳鎮烽埡鍛偓渚€寮介鐐电厬闂侀潧锛忛崨顔芥珤闂傚倸鍊搁崐椋庣矆娴ｉ潻鑰块梺顒€绉寸壕鍧楁煏閸繍妲搁柛銊ュ€块弻锝夊閻樺樊妫岄梺杞扮閸婂綊濡甸崟顔剧杸闁规崘娉涢·鈧梻浣虹帛閹歌煤閺嶎厼鐓橀柟杈鹃檮閸嬫劙鏌熺紒妯哄潑闁稿鎸荤换婵嗩潩椤掍焦袣闂備焦瀵х换鍌炈囨导瀛樺亗婵炴垶鍩冮崑鎾诲礂婢跺﹣澹曢梺璇插嚱缂嶅棝宕滃☉婧惧徍婵犲痉鏉库偓妤佹叏閻戣棄纾绘繛鎴炩棨濞差亶鏁囨い顐厴閸嬫挻鎷呴崜鍙夊缓闂侀€炲苯澧存鐐插暣婵偓闁靛牆妫欓崕顏堟⒑缁嬭法绠版い锔垮嵆閹绺介崨濞炬嫽闂佺鏈懝楣冨焵椤掑嫷妫戠紒顔肩墛缁楃喖鍩€椤掑嫮宓佸鑸靛姈閺呮悂鏌ｅΟ鍨敿闁硅姤娲熷娲箰鎼达絿鐣靛銈忓瘜閸ㄨ櫕绔熼弴鐘冲枂闁告洦鍘鹃惁鍫ユ⒒閸屾氨澧涘〒姘殜瀹曟洟骞嬮悩顐壕閻熸瑥瀚亸顐ょ磼閼搁潧鍝虹€殿喛顕ч埥澶愬閻橀潧濮堕梻浣告啞閸旓附绂嶉弽銊﹀弿闁搞儺鍓氶埛鎴犵磼鐎ｎ偒鍎ラ柛搴＄箻閹顫濋銏犵ギ閻庢鍠涢褔鍩ユ径濠庣叆闁告侗鍨卞鎴炵節濞堝灝鏋熼柨鏇楁櫊瀹曟鈽夊Ο鐐戝吘鏃堝川椤旇瀚奸梻浣告啞缁嬫垿鍩婇弴銏╂晜闁割偅绻勯悿鍛存⒑閹稿海鈽夐悗姘煎幖閻ｇ兘宕ｆ径宀€鐦堥梻鍌氱墛娓氭宕曡箛鏂讳簻妞ゆ劑鍨洪崵鍥煛鐏炶濡奸柍瑙勫灴瀹曞崬顫滈崱姗堥獜闂傚倷绶氬褍螞濞嗘挸绀夐柡鍥ュ灩閻撴﹢鏌熸潏鍓х暠闁绘搫绻濋弻娑㈠焺閸愶缚娌紓浣靛妼閵堢顫忓ú顏呭殥闁靛牆鎳忛悗顓㈡⒑缁嬫寧鎹ｉ柡浣筋嚙閻ｅ嘲煤椤忓嫷娼婇梺缁樼憿閸嬫捇鏌涘顒夊剰妞ゎ叀娉曢幑鍕偖閺夋垳绱ｉ梻浣稿悑濠㈡﹢鎮樺┑瀣厴闁硅揪闄勯崐鐑芥煛婢跺鐏╁ù鐘虫倐濮婃椽鎳￠妶鍛畬闂佹悶鍎滈崘銊ゆ喚婵犵數鍋涢顓熸叏閹绢噮鏁勯柛鈩冪☉閻撴洟鏌熺€电啸缁炬崘妫勯湁闁挎繂鐗嗘禍妤呮煙鏉堝墽鐣遍柣鎾存礋閺岀喖鏌囬敃鈧獮妯肩磼閻樿崵鐣洪柡灞剧缁犳稑顫濋鎸庣潖闂備胶鎳撻崯鍨洪銏犺摕婵炴垯鍨归悡姗€鏌熼鍡楀€搁ˉ姘節绾板纾块柛瀣灴瀹曟劙寮介锝嗘婵犵數濮寸€氼參顢曟禒瀣厓闁靛闄勯悘閬嶆煛鐎ｎ偅鈷愮紒缁樼箖缁绘繈宕掑鍐炬澑闂備胶绮幐濠氭偡瑜旈崺鈧い鎺戝枤濞兼劖绻涢崣澶屽ⅹ閻撱倝鏌曢崼婵囶棤妞も晝鍏樺鍫曞醇濮橆厽婢掗梺绋款儐閹搁箖骞夐幘顔肩妞ゆ帒鍊甸弫宥囩磽閸屾瑨鍏岀紒顕呭灣閹广垽宕奸妷褍绁﹂梺鍛婂姂閸擃噣鎮㈤崗鐓庢異闂佸啿鎼崰娑氭閸欏绡€缁剧増蓱椤﹪鏌涢妸鈺€鎲鹃柟顖氭川閹叉挳宕熼褎绁梻渚€娼х换鎺撳垔椤撶偑鈧帗绻濆顓犲帾闂佸壊鍋呯换鍌炲汲濞嗘挻鐓熼煫鍥风导缁ㄧ厧菐閸パ嶈含妞ゃ垺娲熸慨鈧柣妯挎珪椤斿嫰姊绘担椋庝覆缂佹彃娼″畷妤€顫滈埀顒勭嵁閸愵喖顫呴柕蹇曞У閻庢娊鏌℃径濠勫闁告柨绉撮埢宥咁吋婢跺鍘介梺缁樻煥閹芥粓鎯屾繝鍐╁弿婵鐗忛悾鐢告煕閳轰焦鍤囩€规洖銈稿鎾偄閸欏顏洪梻鍌欒兌椤牓寮甸鍕殞濡わ絽鍟悞鍨亜閹哄秶鍔嶉柛濠冨姉閳ь剝顫夊ú姗€宕濋弴銏″仼闁跨喓濮寸粻鐘测攽閻樻彃鈧崵绮旈搹鍏夊亾鐟欏嫭绀€闁绘牕銈搁妴浣肝旀担铏圭槇闂佸憡娲﹂崢绋课涢妸锔剧瘈闁汇垽娼цⅷ闂佹悶鍔岄妶绋跨暦濞差亜鍐€妞ゆ挾鍋熼ˇ顕€姊洪崫鍕窛濠殿喗鎸宠棢婵鍩栭悡鏇犳喐鎼淬劊鈧啴宕卞☉娆忎簵闂佸搫娲㈤崹濠氬矗閹剧粯鐓曢柕澶涚到婵′粙鎮樿箛锝呭籍闁哄瞼鍠栭、娆撴寠婢跺奔绱濋梻浣告惈閺堫剛绮欓幋锕€鐓濋幖娣€楅悿鈧梺鍝勬川婵參宕€ｎ喗鈷掑ù锝呮啞閹牓鏌￠崼顐㈠閻撱倝鏌ｉ弮鍫闁哄棴绠撻弻锝夊箻瀹曞洤鍝洪梺琛″亾濞寸姴顑嗛悡娆撴⒑椤撱劎鐣遍悽顖樺姂閺屻劑寮村Δ鈧禍楣冩⒑鐎圭媭娼愰柛銊ユ健閵嗕礁鈻庨幘鏉戔偓閿嬨亜閹哄棗浜惧┑鐐茬墕閻倿骞冨Δ鈧埢鎾诲垂椤旂晫浜┑鐘媰閸愵喖寮板Δ鐘靛仦閸ㄦ寧鎱ㄩ埀顒勬煟濮楀棗浜濇い顐㈢Ч濮婃椽妫冨☉姘鳖唺婵犳鍠氶崗姗€銆佸Ο濂芥椽顢旈崨顏呭缂傚倸鍊烽悞锕傛晪婵犳鍣粻鎴︽箒濠电姴锕ょ€氼喗鏅堕悽纰樺亾鐟欏嫭绀冮柛銊ユ健閻涱喖螣閸忕厧鐝伴梺鑲┾拡閸擄箓宕ú顏呪拻濞达絽鎲＄拹锟犳煕鐎ｎ偅灏い顓炴搐閳诲酣骞樺畷鍥舵Х闂備礁鎲＄粙鎴︽偤閵娾晛鐓曢柟杈鹃檮閳锋帡鏌涢銈呮瀺缂佸爼浜堕弻锝夊箳濡ゅ啰鏆梺鍝勬湰缁嬫帡骞嗛弮鍫濐潊闁绘﹩鍋呴悘鍡涙煟鎼淬値娼愭繛鍙夛耿瀹曟繂鈻庨幘宕囩暫濠电偛妫欓幐濠氬磹缂佹ü绻嗘い鏍仦閺侀亶鎮楀顑惧仮婵﹦绮幏鍛村川婵犲懐顢呮俊鐐€ら崢濂告偋閸℃稒绠掑┑锛勫仜椤戝懎霉闁垮鈻旂€广儱顦伴悡娆撴煕閹炬鎳庣粭锟犳⒑缂佹ɑ灏伴柣鐔叉櫊瀵鈽夐姀鐘电杸濡炪倖鎸炬慨鏉戭嚕閵娾晜鈷戦柛娑橈功閹冲啴鎮楀顐㈠祮鐎殿喛顕ч埥澶愬閻橀潧骞愰梻浣侯焾閺堫剚绔熼弴鐔稿弿闁搞儺鍓氶崐鐢告煕椤垵浜濈紒鑸电叀閹顫濋悡搴㈢彎闂佺硶鏂侀崑鎾愁渻閵堝棗绗掗柨鏇缁棃鎮介崨濠勫幈闂佽鍎抽顓灻虹€涙ǜ浜滈柕蹇ョ磿閹冲洨鈧鍠楅幐铏叏閳ь剟鏌ㄥ☉妯侯仼妤犵偞顨婂铏规兜閸涱収妫堥梺瑙勬た娴滅偛顕ユ繝鍐﹀亝闁告劑鍔嶆潏鍫ユ⒑閸愬弶鎯堥柛濠呭煐缁傚秴顭ㄩ崟鈺€绨婚梺瑙勫礃濞夋稒绂掕椤儻顦伴柛銊ょ矙瀵鍩勯崘顏嗘嚌闂佹悶鍎滈崟顓炵秵闂佽姘﹂～澶娒洪弽顓炍х紒瀣儥閸ゆ洟鏌熺紒銏犳灍闁稿瀚伴弻娑樷攽閸℃浠肩紓浣哄О閸庨潧顫忔繝姘＜婵炲棙鍨垫俊浠嬫⒑缁嬪潡顎楅柛鐔锋健濠€浣糕攽椤旂瓔鐒炬繛澶嬬〒婢规洘绻濆顓犲幈闂佸搫娲㈤崝灞炬櫠椤栫偞鐓曟繛鍡楃箳缁犳娊鏌嶈閸撴瑧绮诲澶婄？闁告鍊ｅ☉銏╂晣闁绘劏鏅滈悘浣圭箾鐎电孝妞ゆ垵妫濋幃锟犳偄閸忚偐鍘甸梻渚囧弿缁犳垿鎮橀悩缁樼厽闁靛鍔嶉鐘电磼鏉堛劌娴柟顔规櫊瀹曟ê霉鐎ｎ偆浜為梻鍌欑閹碱偊鎳熼婊呯煋闁绘垿鎽妸锔剧懝闁逞屽墴瀵鈽夐姀鐘殿啋闂佸憡顨堥崑娑⑩€栫€ｎ剛纾藉ù锝嗗灊閸氼偊鏌涚€ｃ劌鈧洟鎮鹃悜钘夌闁绘劏鏅滈～宥呪攽閳藉棗鐏ｉ柕鍡楊儑濡叉劙鏌嗗鍡忔嫽婵炶揪绲块悺鏂款焽閹邦喒鍋撶憴鍕闁挎洏鍨归悾宄懊洪鍕敤濡炪倖鎸堕崝搴ｇ矙韫囨稒鈷戦柛婵嗗閸屻劑鏌涢妸锔姐仢闁诡噯绻濇俊鐑芥晜閸撗呮闂傚倸鍊搁悧濠勭矙閹烘澶愭倷閻戞鍘遍柣搴到閸氣偓缂併劋绮欓弻鐔煎矗婢跺鈧劙鏌熼銊ユ搐闁卞洦绻濋棃娑氬ⅱ闁硅櫕鐗犲缁樻媴閸涘﹥鍎撻梺鐟板暱缁绘﹢骞冮敓鐘虫櫢闁绘灏幗鏇炩攽閻愭潙鐏熼柛鈺佸瀵偊宕橀鐣屽帾闂佸壊鍋呯换鍐闯濞差亝鐓熸繝闈涘暙婢ц尙绱掔紒妯笺€掗柍褜鍓涢弫鎼佲€﹂崼锝傚彺闂傚倷绀侀幖顐﹀箠閹邦厾绠鹃柍褜鍓涢埀顒侇問閸犳牠鈥﹂柨瀣╃箚闁兼悂娼х欢鐐测攽閻樻彃顏柛姗嗗墮閳规垿鎮╅鑲╀紘濠电偛顦伴惄顖炲箠閻旂⒈鏁嶉柣鎰皺閸橀亶鏌ｈ箛鏇炰哗鐞氭瑩鏌￠埀顒勬嚍閵夛絼绨婚梺鍝勫暙閸婂爼鍩€椤掆偓椤戝鐣峰┑瀣亜闁惧繐婀遍敍婊冾渻閵堝棙绀€闁瑰啿閰ｉ幃姗€鏁傜粵瀣啍闂佺粯鍔樼亸娆戠不閼姐倐鍋撶憴鍕８闁告柨閰ｉ崺鈧い鎺嶈兌閳洟鏌ㄥ顑炲綊鎮埀顒勫矗閸愵煈娼栫紓浣诡焽閻熷綊鏌涢妷鎴濆暕缁辩喓绱撻崒娆掑厡濠殿喚鏁诲畷褰掓偨缁嬭法鍘洪梺鍦亾閺嬪ジ寮ㄦ禒瀣厱妞ゆ劗濮撮悘顕€鏌ㄥ☉娆戠疄婵﹨娅ｇ划娆撳箰鎼淬垺瀚抽梻浣藉吹閸熸瑩宕舵担鍛婂枠闁轰礁鍊归幈銊╁箛椤忓棛娉块梻鍌欒兌閹虫捇鎮洪妸褎宕查柛鎰靛暉婢舵劕顫呴柍鍨涙櫅娴滈箖鎮峰▎蹇擃仾缂佲偓閳ь剛绱撻崒姘毙㈤柨鏇樺€濋幃鐐槹鎼达絿鐓撻柣鐘叉川閸嬫挸螞閸愵喖鏄ラ柍褜鍓氶妵鍕箳閹存績鍋撶紒妯尖枖鐎广儱顦伴悡鐔镐繆椤栨繂浜归悽顖涚洴閺岋綁骞樼捄鐑樼亪闂佸搫鐭夌换婵嗙暦濮椻偓婵℃悂濡烽姀鐘卞闂佹眹鍨婚…鍫㈢不椤栫偞鐓ラ柣鏂挎惈鏍￠梺缁樻尰缁嬫垿婀侀梺鎸庣箓閹冲繘骞夐幖浣告瀬闁割偁鍎查埛鎴︽煕濠靛棗顏柣鎺曟硶缁辨挸顓奸崟顓犵崲闂佺粯渚楅崳锝呯暦閸洦鏁嗗璺侯儐濞呮牗绻濆▓鍨灍妞ゎ厼鐗婇妵鏃堝箹娓氬洦鏅┑掳鍊曢幊蹇涘煕閹烘嚚褰掓晲閸涱喖鏆堥梺璇″灠閻楁捇寮婚妶鍚よ櫣鎷犻懠顑挎闂備浇顕栭崯顐﹀炊瑜忛鎺楁⒑瑜版帩鏆掗柣鎺炲缁辩偞鎯旈埦鈧弨浠嬫煟閹邦剙绾ч柍缁樻礀闇夋繝濠傚缁犵偤鏌熼鎯т沪缂佺粯绻傞～婵嬵敇閻樻彃绠洪梻鍌欑缂嶅﹪宕戞繝鍥у瀭濞寸厧鐡ㄧ€氬﹤鈹戦崒姘暈闁稿﹤鐏氶幈銊ヮ潨閸℃绠虹紓浣芥硾瀵爼濡甸崟顖ｆ晣闁炽儱鍟挎慨宄邦渻閵堝繘妾┑鐐诧躬瀵鎮㈤悡搴＄獩婵犵數濮撮崐鐢稿几濞嗘挻鍊垫繛鍫濈仢閺嬫稒銇勯鐘插幋鐎殿噮鍋勯鍏煎緞婵犲嫷妲规俊鐐€曠换鎰板箠鎼淬垹鍨斿ù鐓庣摠閳锋帒霉閿濆懏鍟為柛鐔哄仱閺岀喓绮欓幐搴＆閻庤娲滈崰鏍€侀弴銏狀潊妞ゎ偒鍘鹃弫鐐節閻㈤潧孝闁汇儱顦靛鑸垫償閹惧厖澹曞┑掳鍊撻悞锕傚矗韫囨稒鐓熼柟杈剧稻椤ュ鐥崜褏甯涚紒缁樼洴楠炲鎮欓埡鍌︾礄婵犵數鍋涘Ο濠冪閸洖鏋侀柛銉ｅ妸娴滄粍銇勯幇闈涗簻闁告ɑ鎸抽弻娑氣偓锝庡亝鐏忎即鏌熷畡鐗堝殗闁硅櫕鐗曢埞鎴﹀炊椤垶顥堥柣搴ゎ潐濞插繘宕濋幋锔衡偓浣割潨閳ь剟骞冮埡鍛闁硅鍋呭ú鏍煘閹达附鏅柛鏇ㄥ亗閺夘參姊虹粙鍖℃敾闁绘绮撳顐︻敋閳ь剟鐛幒妤€妫橀柛婵嗗婢规洖鈹戦绛嬬劷闁告鍕珷妞ゆ洍鍋撶€殿噮鍋婂畷濂稿Ψ閿旀儳骞愰梺璇茬箳閸嬬娀顢氳瀹曟繂顭ㄩ崼鐔哄帗闂備礁鐏濋鍛存倶閿曞倹鐓忛柛銉戝喚浼冨Δ鐘靛仦鐢€崇暦閸楃儐娓婚柟顖嗗本顥＄紓鍌氬€搁崐鎼佸磹妞嬪海鐭嗗〒姘ｅ亾閽樻繈姊洪鈧粔鎾几娴ｇ硶鏀介柣妯虹枃婢规绱掗悩宕囧⒌闁哄被鍔戦幃銏ゅ传閸曟埊缍侀弻娑氣偓锝庝簻椤忣參鏌＄仦鍓ь灱缂佺姵绋戦～婵嬵敄閹稿海娼栭梻鍌欑閹诧繝鎮烽妷銉庢稑螖閸涱厾鍘撮梺纭呮彧闂勫嫰宕戦幇顔剧＝濞达綀鍋傞幋锔界叆妞ゆ挾鍋愰弨浠嬫煃閽樺顥滃ù婊€绮欓弻娑樜熼悡搴′粯閻庤鎸哥€氼剟鍩為幋锔藉€烽柛娆忣槴閺嬫瑦绻涚€涙鐭嬬紒璇茬墦楠炲啴鏁撻悩鍐蹭簻闂佺绻楅崑鎰板矗閸℃せ鏀介柣妯肩帛濞懷勪繆椤愶絿鈯曢柡鍛版硾閳藉鈻庡鍕泿闂傚鍋勫ú锕€煤閺嶎厼鐓濋柛顐犲劜閻撴盯鎮橀悙鍨珪閸熺顪冮妵鍗炲€荤粣鏃堟煛鐏炲墽娲存鐐达耿瀵爼骞嬪┑鍥ㄥ殘濠碉紕鍋戦崐鎴﹀垂濞差亝鍋￠柍杞扮贰閸ゆ洖霉閻樺樊鍎涢柡浣告喘閺岋綁骞囬鑺ユ瘎閻庤娲栭悥鐓庮潖缂佹ɑ濯撮柛娑橈攻閸庢挸鈹戦悙鑼勾闁搞劏妫勯悾鐤亹閹烘垶宓嶅銈嗘尵閸犲酣宕㈣ぐ鎺撯拺闂侇偆鍋涢懟顖涙櫠鐎涙ɑ鍙忓┑鐘叉噺椤忕姵绻涢幋鐘虫毈鐎规洏鍔戦、娆愮┍閹典礁浜鹃柟閭﹀墻濞撳鏌曢崼婵嬵€楀ù婊勭箖缁绘盯鎳犻鈧弸娑氣偓瑙勬礃濡炰粙宕洪埀顒併亜閹哄秹妾峰ù婊勭矒閺岀喐娼忛崜褏蓱缂佺虎鍙€閸╂牠濡甸崟顖涙櫆闁兼祴鏅濋弳銈夋⒑閸濆嫯瀚扮紒澶婄秺楠炴劖绻濋崘銊х獮濠碘槅鍨辨禍鍫曟晝閸屾稓鍙勬繛鏉戝悑閻熝呯矓椤旇姤鍙忓┑鐘插暞閵囨繄鈧娲栫紞濠囥€佸璺哄窛妞ゆ挾鍋涢ˉ鎰版⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栨稒娅犳い鏂款潟娴滄粍銇勯幘璺轰粶婵¤尙绮妵鍕敃閵忋垻顔掗梺鍦帶濠€閬嶅箟閹绢喖绀嬫い鎰剁悼閳ь剦鍙冨缁樻媴閸涘﹤鏆堝┑鐐额嚋缁犳挸鐣峰鍐ｆ瀻闁规儳纾ˇ顓㈡偡濠婂懎顣奸悽顖涱殜閸╂盯骞嬮敂鐣屽幈濠电偞鍨堕敃鈺呮偂椤掑嫭鐓熼柟鐑樻煥娴滃墽绱掔紒妯兼创鐎规洦浜畷姗€顢旈崟顐ゅ帓闂備礁鎲￠〃濠冪閸洖钃熼柣鏂垮悑閻掍粙鏌ㄩ弴妤€浜炬繝鈷€鍛笡缂佺粯绋撶划顓㈠传閸曨偒娼庨梻浣告惈閼活垳绮旈悜閾般劍绗熼埀顒勫蓟濞戙垹绠婚悗闈涙啞閸ｄ即姊洪幐搴ｇ畼闁稿濮风划璇测槈閵忕姷顔掓繛杈剧秬椤濡靛┑鍥ヤ簻闁靛繆鍓濋ˉ鍫⑩偓瑙勬磸閸旀垿銆佸鈧幃銈嗘媴閸涘﹤鈧垶姊婚崒姘偓鎼佸磹妞嬪孩顐芥慨姗嗗墻閻掔晫鎲搁弮鍫濈畺鐟滄柨鐣烽崡鐐╂婵☆垳鈷堥崬鐢告⒑鐠囨彃鍤辩紓宥呮缁傚秹宕奸弴鐔封偓鍧楁煠閹帒鍔滈柛娆忕箲娣囧﹪顢涘鍙樿檸闂佺粯鎸婚崝娆撳蓟瀹ュ鐓ラ悗锝庝簽娴煎矂姊洪崫鍕伇闁哥姵鐗犻獮濠囧冀椤撶偟鍘告繛杈剧秮椤ユ捇骞戦弴銏♀拻濞达絽鎲￠崯鐐存叏婵犲倻绉洪柡浣稿暣婵偓闁靛牆鎳撻幗鏇炩攽閻愭潙鐏熼柛銊ф嚀铻炴慨妞诲亾闁诡喖缍婇獮渚€骞掗幋婵愭闁荤喐绮岀换姗€宕洪埀顒併亜閹哄秶璐伴柛鐔风箻閺屾盯鎮╅幇浣圭暦缂備胶绮粙鎺旀崲濠靛鐐婄憸蹇涙偩濞差亝鈷戦柛鎰级閹牓鏌涢悢绋款棆濠㈣娲熷畷妤呮⒒鐎靛摜鐣炬俊鐐€栭悧婊堝磻閻愬搫鏋侀梺顒€绉甸崐鍨叏濮楀棗鍘甸柛瀣ㄥ灪閹便劍绻濋崘鈹夸虎閻庤娲﹂崑濠傜暦閻旂厧鍨傛い鎰Р閸旀垵顫忛搹鍦煓婵炲棙鍎抽崜鎶芥⒑缁嬫鍎戦柛瀣枔閸掓帡鍩￠崨顔间簻闂佺粯鎸告鎼佹嚀閸喒鏀介柣鎰皺閹界姵绻濋姀鈭额亞鍙呭銈嗘尪閸ㄥ綊寮告笟鈧弻娑㈠箛闂堟稒鐏堢紒鐐劤閸氬鎹㈠☉銏犵闁绘劘娉涢ˉ婵單旈悩闈涗粶闁绘锕﹂幑銏犫攽閸″繑鐏侀梺鍓茬厛閸犳鎮樺澶嬧拺闁圭瀛╃壕鐢告煛閸涱垰孝闁伙絽鍢查…銊╁醇閻斿憡鐝栭梻浣侯焾閺堫剙顫濋妸鈺傛櫖闁绘柨鍚嬮埛鎴︽煟閻旂厧浜伴柛銈囧枎閳规垿顢氶埀顒勊夐幘瀵哥彾闁哄洢鍨圭粈鍌滅磼濡ゅ嫭銆冪紒銊ヮ煼濮婃椽宕崟顐ｆ闂佺锕﹂弫濠氱嵁韫囨稒鏅搁柣妯虹－閸橀亶鏌熼崗鑲╂殬闁搞劍妞介崺娑㈠箛椤撴粈绨婚梺闈涱煭缁蹭粙宕濋敃鍌涚厵妞ゆ梻鏅幊鍥┾偓娈垮枛閻栧ジ鐛€ｎ喗鍋愰柛顭戝亜濞呮瑩姊婚崒娆戭槮濠⒀呮櫕閸掓帡顢涢悙鏉戜罕闂佸搫娲㈤崹铏圭不閹烘鈷掑ù锝囨嚀椤曟粎绱掔拠鎻掆偓鍧楀箖瑜嶉…銊╁礃閸撗冨Ш闂備浇顫夋竟鍡樻櫠濡ゅ懏鍋傞柣鏂挎憸缁♀偓闂傚倸鐗婄粙鎺楀箹閹扮増鐓冪紓浣股戠粈鍐煙娓氬灝濡界紒缁樼箞瀹曠喖顢橀悙娈垮仹闂傚倷鑳堕幊鎾诲床閺屻儱绠犻柟鐗堟緲缁犵喖鏌熺紒銏犳灈缂佲偓鐎ｎ偁浜滈柟鑸妷閸嬫捇鎼归锝呮殙闂傚倸鍊搁崐鎼佸磹閻戣姤鍤勯柛顐ｆ磵閳ь剨绠撳畷濂稿煑閳轰椒澹曢梺鍓茬厛閸嬪嫬霉椤旈敮鍋撶憴鍕濠电偛锕顐﹀箛閺夋寧銇濇繛杈剧到閹诧繝顢橀崸妤佲拻濞达絽鎲＄拹锛勭磼椤曞懎鐏犳い鏂跨箳閹风娀宕ｉ崒锔剧М鐎规洖銈告俊鐑芥晜閹冨闂傚倸顭崑鍕洪妶鍫濐杺闂備胶顭堥鍡涘箲閸パ屽殨妞ゆ帒瀚敮闂侀潧顦崐鏇⑺夊鑸碘拻濞达絿顭堥ˉ蹇涙煕鐎ｎ亝鍣归悡銈嗘叏濡炶浜鹃梺璇″櫙缁绘繃淇婇悜鑺ユ櫆闁告挆鍛潓闂傚倸鍊搁崐鎼佹偋婵犲嫮鐭欓柟鐑橆殕閺咁剛鈧箍鍎卞Λ鏃傛崲閸℃稒鐓欑紓浣姑粭褏绱掓径瀣仢闁哄矉绱曟禒锕傛偩鐏炴经鍥ㄧ厸閻忕偠顕ф俊鍧楁煃瑜滈崜銊х礊閸℃顩查柣鎰綑椤曢亶鎮橀悙缂庢帡寮ㄩ懞銉ｄ簻闁哄啫鍊堕埀顒€顑呴蹇涘Ψ閿旇桨绨诲銈嗘尵閸嬫稑危婵犳碍鐓熼柨婵嗩槹閺佽京绱掓潪鎵煓鐎规洏鍔嶇换婵嬪磼濞嗘垹娉块梻鍌欐祰瀹曠敻宕戦悙鐢电煓闁割偁鍎遍悞鍨亜閹哄秶顦﹀褜鍨辩换娑㈠礂閸忕厧纰嶉梺瀹狀潐閸ㄥ潡寮澶婄妞ゆ劏鍓濆鈧梻鍌欒兌椤牓鏁冮妷鈺佸瀭闁割煈鍠氶弳锕傛煛閸ャ儱鐏╅柦鍐枛閺屾洘寰勫☉姘辨殸婵炲濯崣鍐潖濞差亜绠伴幖绮规噰閹峰姊虹粙娆惧剱闁瑰憡鎮傞幃楣冩倻閽樺鐓戞繝銏ｆ硾閻ジ顢欓弴銏♀拺闁荤喐澹嗛幗鐘绘煟閻旀潙鍔﹂柟顔斤耿閸╋繝宕橀鍡床闂備胶绮悷锕傛偡閵夈儍娲晝閸屾稑浜楀┑鐐叉閹稿宕愰悽鍛婄厽闁靛繆妲呴崯蹇涙煟閹烘挸鍔ら棁澶愭煟濡櫣锛嶉柣顓熷浮閺屸€崇暆鐎ｎ剛锛熼梺閫炲苯澧剧紓宥呮瀹曟粌鈻庤箛鏇熸噧婵犵绱曢崑鎴﹀磹閵堝棛顩叉繝濠傜墕閻ゎ噣鎮楀☉娅偐鎹㈤崱娑欑厱妞ゆ劧绲剧粈鈧紓浣插亾闁告劦鍠楅悡蹇撯攽閻愭垵鍟埀顒冾嚙铻炴い鏍仦閳锋帡鏌涚仦鍓ф噭缂佷焦澹嗛埀顒冾潐濞叉粓寮拠鑼殾闁规儼濮ら弲婊堟煕閹炬鍊婚悷婵嬫⒒娴ｄ警鏀伴柟娲讳簽閳ь剟娼ч惌鍌氼嚕椤愩倐鍋撻敐搴℃灍闁绘挸绻愰…璺ㄦ崉閻戞﹩妫″┑鐐叉噹閹虫劗妲愰幒妤€鐒垫い鎺戝€甸崑鎾绘晲鎼粹€茬按婵炲瓨绮嶇划鎾诲蓟閳ユ剚鍚嬮柛鎰╁妼椤姊哄Ч鍥у闁搞劌娼″濠氭晲婢跺á褔鏌涚仦鍓х叝濠㈣娲栭埞鎴︽偐濞堟寧娈扮紓浣介哺濞茬喎鐣烽幋锕€绠ｉ柨鏇楀亾缁炬儳缍婇弻鈥崇暤椤旇壈瀚伴柡鍛У缁绘繈鎮介棃娴讹綁鏌ら悷鏉库挃濠㈣娲樼换婵嗩潩椤撶姴骞嶉梻浣告啞閹稿棝宕ㄩ鐙€鍋ч梻鍌欒兌缁垶骞愮拠瑁佹椽鎮㈤悡搴ｇ暫濠德板€曢幊蹇涘疾閺屻儱绠归悗娑欘焽缁犳﹢鏌℃担鍦⒌闁哄备鍓濋幏鍛村传閵夈儺鏆梻浣哥枃椤宕归崸妞尖偓浣糕枎閹寸偛鍘归梺缁樺灩閺咁偊宕ｅ鍡欑瘈闁汇垽娼ф禒婊堟煙闁垮鐏╃€垫澘锕畷褰掝敊閵夘垳绉鐐叉喘瀵墎鎹勯…鎴濇暯闂傚倷鑳堕幊鎾诲疮鐠恒劌顥氭い鎾卞灩缁愭鏌″搴″箹缂佺姵鐗楃换婵囩節閸屾粌顣洪梺缁樻尰閻╊垶寮诲☉姘勃闁诡垎鍐╃槗濠电偞娼欓崥瀣垝閹炬剚娼栧┑鐘宠壘绾惧吋鎱ㄥ鍡楀幋闁稿鎹囬幃婊堟嚍閵夈儲鐣遍梻浣稿閸嬪懎煤瀹ュ鐒垫い鎺戯功閻ｇ數鈧娲栭妶鍛婃叏閳ь剟鏌ㄥ┑鍡樺晽闁炽儲鏋奸弨浠嬫煟閹邦剙绾ч柍缁樻礀闇夋繝濠傚閻苯顭跨憴鍕闁瑰弶鎸冲畷鐔碱敇閻樺灚顫岄梻鍌氬€搁崐鎼佹偋婵犲嫮鐭欓柟鐑橆檪婢舵劖鍋愮紓浣诡焽閸樻悂姊虹化鏇燁潑闁告﹢绠栭幃楣冩偨閸涘﹦鍘搁悗鍏夊亾闁逞屽墴瀹曚即寮介鐘茬ウ閻庡箍鍎遍ˇ浠嬪极婵犲嫮妫柟宄扮焸閸濈儤鎱ㄩ敐鍜佹█婵﹦绮幏鍛瑹椤栨粌濮奸梻浣瑰濞测晝绮婚幘宕囨殾婵°倐鍋撴い顐ｇ矒閸┾偓妞ゆ巻鍋撴い鏇稻缁绘繂顫濋鐔哥彸濠电姰鍨煎▔娑㈡晝閿曞偆鏁囨繛宸簼閳锋垹绱撴担濮戭亪鎮橀妷锔跨箚妞ゆ劧绲垮ú瀵糕偓瑙勬礃缁诲牓骞冨鍫熷殟闁靛鍨虹€氬ジ姊绘担鍛婂暈缂佸鍨块弫鍐晝閸屾氨鐤囬梺鍛婂姀閺呮瑧鎹㈤崱妯镐簻闁规澘澧庣粔鍨箾閸喓鐭掗柡灞剧洴閸╋繝宕橀妸銈嗩潟婵°倗濮烽崑娑㈩敄婢舵劕鏋侀柛宀€鍋炵€电姴顭跨捄鐑橆棞濞存粓绠栭弻锝夊箣閿濆憛鎾绘煟閹惧鈽夋い顓℃硶閹瑰嫭绗熼姘闂備浇顕х换鍡涘疾濞戙垺绠掗梻浣虹帛钃辨い鏃€鐗犻幃鐐烘倷椤戝彞绨诲銈呯箰鐎氼剟寮抽敐鍛斀闂勫洭宕洪弽顓炵畾闁哄啫鐗嗛悘宕団偓瑙勬礀濞村倿宕崶褉鏀介柣妯虹仛閺嗏晠鏌涚€ｎ偆鈽夐摶锝呪攽閻樺弶鎼愰柣顓燁殜閺屾盯骞囬棃娑欑亾閻庤鎸风欢姘跺蓟濞戙垹绠涢梻鍫熺⊕閻忓秹姊虹粙鍖″姛闁稿繑锕㈠濠氭偄閸濆嫭鐎抽梺鍛婎殘閸嬫稓绮诲ú顏呯厸濞达絽鎽滄晶锔芥叏婵犲懏顏犳繛鎴犳暬瀹曘劑顢樿椤ュ秹姊绘担绛嬫綈婵＄偞瀵х粋宥夋倷瀹割喖娈繝鐢靛Т濞层倝鏌ㄩ妶鍡曠箚闁靛牆瀚崝宥嗙箾閸涱喚澧柍瑙勫灴閹晝鎷犺娴兼劙姊虹涵鍛彧闁告梹顨嗙粩鐔煎即閻斾警娴勯柣搴秵閸嬪棝宕㈤柆宥嗙厽闊洦娲栨禒婊冾熆瑜岀划娆撶嵁婵犲洤宸濋悗娑欘焽閸橀亶姊洪崫鍕偓钘夆枖閺囩喐娅忛梻鍌欑缂嶅﹪寮ㄩ柆宥呭瀭閻犺桨璀﹂悞浠嬬叓閸ャ劎鈽夐柣鎾寸洴閺屾盯骞囬崗鍛婂€ｇ紓浣介哺閻撯€愁潖缂佹鐟归柍褜鍓熼崺鈧い鎺戝€告禒婊堟煠濞茶鐏￠柡鍛板煐鐎佃偐鈧稒顭囬崢鎾绘偡濠婂嫮鐭掔€规洘绮撴俊姝岊槾缂佲偓婵犲洦鐓曢柍鈺佸暟閳藉绱掗埀顒勫磼濞戞瑥寮垮┑锛勫仩椤曆勭妤ｅ啯鍊甸悷娆忓缁€鍐煕閵娿儲鍋ラ柣娑卞枛椤粓鍩€椤掆偓椤曪綁顢楅崟顐嬨劑鏌ㄩ弬鍨稏缂併劍鎸冲濠氬磼濞嗘埈妲繝銏㈡嚀閿曨亪骞冮敓鐘查唶闁靛鍎抽悰銉モ攽鎺抽崐鏇㈠箠韫囨稑纾归柛顐ｆ礃閻撴洟鏌嶉埡浣告殶闁愁垱娲熼弻宥夋煥鐎ｎ亞浼岄梺鍝勬湰缁嬫垿鍩ユ径濠庢建闁糕剝鐟ヨぐ鍡樼節閻㈤潧浠滈柣妤€锕ょ叅闁哄稁鍘奸悡姗€鏌熸潏楣冩闁稿﹦鍏橀幃褰掑炊閸パ勵棞闁诡垰鐗嗛埞鎴︽偐濞堟寧姣岄梺閫炲苯澧痪缁㈠弮楠炴鎮╃紒妯煎幍閻庣懓瀚晶妤呭闯娴犲鐓曢柡宥冨妿婢х數鈧鍠楅幐鎶藉箖閵堝棙濯撮柛锔诲幘闉嬫繝鐢靛Х閺佸憡鎱ㄩ悽鍓叉晩闁哄稁鍘肩粣妤佷繆閵堝懏鍣烽柍褜鍓欓崯鏉戠暦閵娾晩鏁囬柛銉ｅ妿閳藉鏌嶇拠鏌ュ弰妤犵偞锚閻ｇ兘宕舵搴ㄦ７闂傚倸鍊搁崐鎼佸磹閹间焦鍋嬪┑鐘插暟閻熻淇婇妶鍌氫壕闂侀潧妫欑敮妤冩崲濠靛棭娼╂い鎾跺Т鐢箖姊绘担绋款棌闁稿鎳愰幑銏ゅ礃椤斻垹顦…銊╁醇閻斿搫骞堥柣鐔哥矊缁夊綊寮崘顕呮晜闁割偅绻嗛幗鏇炩攽閻愭潙鐏﹂柛鈺佸暣瀹曟垿骞樼紒妯绘珳闁硅偐琛ラ埀顒冨皺閸戝綊姊虹拠鑼缂佺粯甯″顐ｇ節濮橆剝鎽曢悗骞垮劚閻楁粌顬婇妸鈺傗拺闁告稑锕ョ亸鎵偓鍏夊亾闁归棿闄嶉埀顑跨閳诲酣骞橀崘鎻掓暏婵＄偑鍊栭幐楣冨磻閻斿吋鍋橀柕澶堝劗閺€浠嬪箳閹惰棄纾归柡鍥ュ灩缁犵姷鈧厜鍋撻柛鏇ㄥ亞閸旓箑顪冮妶鍡楀潑闁稿鎹囬弻娑㈡偆娴ｅ摜浠梺鐟扮畭閸ㄥ綊鍩為幋鐘亾閿濆簼绨介柨娑欑矒濮婃椽妫冨☉姘暫濠碘槅鍋呯粙鎾跺垝濞嗘劗鐟归柍褜鍓欓～蹇曠磼濡顎撻梺鑽ゅ枑濠㈡ɑ鎱ㄩ姀銏㈢＝濞达綀娅ｇ敮娑欍亜閵娿儻韬柡浣瑰姍閹瑩寮堕幋鐘电嵁闂備礁缍婇崑濠囧礈濞戔懞鍥槻闁宠鍨块幃鈺冩嫚瑜嶆导鎰版⒑缂佹﹩娈旈柨鏇ㄤ邯楠炲啴鏁撻悩鎻掑祮闂佺粯妫佸▍锝夘敊閺囥垺鈷戦柣鐔稿閹界姷绱掔拠鎻掆偓鍧楀箠濠婂棎浜归柟鐑樻尵閸樻悂鏌ｆ惔顖滅シ闁告柨鐭傞崺鈧い鎺嶈兌缁犵偟鈧鍠栭…宄邦嚕閹绢喖顫呴柣妯垮蔼閳ь剙鐏濋埞鎴﹀煡閸℃浠╅梺鍦拡閸嬪﹪鏁愰悙鍝勭闁瑰瓨姊归弬鈧俊鐐€栧濠氬Υ鐎ｎ喖缁╃紓浣姑肩换鍡涙煟閹邦厼顥嬮柣顓熺懇閺岋絽鈽夐崡鐐寸彎濡ょ姷鍋涘ú顓€佸鈧幃銏犵暋閺夎銈夋⒒閸屾瑧绐旀繛浣冲厾鐟邦潩椤掑鍞垫繛杈剧悼閸庛倝锝為弴鐔翠簻闁规儳宕悘顏堟煃闁垮绗掗棁澶愭煥濠靛棙鍣洪柛鐔哄仱閺屾盯鎮㈤崫鍕勃闂侀€涚┒閸斿秶鎹㈠┑瀣＜婵犲﹤鎲涢妸鈺傚€甸悷娆忓缁€鈧紓鍌氱Т閿曘倝鎮炬搴ｇ煓閻犲洨鍋撳Λ鍐春閳ь剚銇勯幒鎴濇殶缂佺姾濮ょ换婵嬫偨闂堟稐鍝楅梺瑙勬た娴滅偛顕ユ繝鍕磯闁靛绠戦崢褰掓⒑閸撴彃浜濇繛鍙夌墵瀹曟瑩鎮╃拠鑼啇濠电儑缍嗛崜娆愪繆娴犲鐓熼柟鎯ь嚟閹冲洭鏌″畝鈧崰鏍€佸☉銏犲耿婵°倓绀侀悵鏃傜磽娴ｆ垝鍚柛瀣洴閳ユ棃宕橀鍢壯囩叓閸ャ劎鈯曟い搴＄Т閳规垿鎮╅鑲╀痪闂佹寧娲忛崹浠嬪垂妤ｅ啫绫嶉柛顐ｇ箘椤︺劌顪冮妶鍡樼叆婵℃彃鐗愰ˇ褰掓煛鐏炲墽娲撮柛鈺佸瀹曟鎮埀顒佺椤忓嫷鍤曢柛鎰棘閺冣偓閹峰懘鎼归崷顓燁潓濠电姷鏁搁崑娑㈡偋閸℃稒鍊舵繝闈涱儏閸戠娀鏌曢崼婵愭Ч闁绘挻娲熼悡顐﹀炊閵婏富妫栭梺鍏煎濞夋洟鍩€椤掍緡鍟忛柛锝庡櫍瀹曟垿宕熼锝嗘櫍婵犻潧鍊婚…鍫濐渻閽樺褰掓晲閸涱喗鍎撻悗娈垮枟婵炲﹤顫忕紒妯诲缂佸顑欏Λ宀勬⒑缁嬫鍎忔俊顐ｇ箓閻ｇ兘顢涢悙鏌ユ暅濠德板€愰崑鎾剁磼閻欌偓閸ㄨ京鎹㈠☉姗嗗晠妞ゆ棁宕甸崙褰掓⒑閹惰姤鏁遍柛銊ユ健瀵鈽夊Ο閿嬵潔濠殿喗顨呴悧鍡樻叏濞戙垺鈷戦悗鍦У椤ュ銇勯敂鐐毈鐎殿喖顭锋俊鎼佸煛娴ｇ绁繝纰樻閸ㄧ敻濡撮埀顒勬煕鐎ｎ偅宕岀€殿喕绮欓、鏇㈠Χ閸涱叀袝闂傚倷鑳剁划顖氼潖婵犳艾鍌ㄧ憸蹇曞垝閸儱绀冮柍鐟般仒缁ㄥ姊洪崫鍕殭闁稿﹦鎳撻埢宥夊即閵忥紕鍘卞┑顔姐仜閸嬫挸霉濠婂棙纭炬い顐㈢箻閹煎湱鎲撮崟顐ｇ€梻浣告啞濞诧箓宕滃☉銏犵闁跨喓濮甸埛鎴︽煕濞戞﹫宸ラ柣鎺戠秺閺屾稓鈧綆鍋呯亸鐢电磼鏉堛劍灏伴柟宄版嚇濡啫鈽夊鍡樼秱闂傚倷鑳堕…鍫ヮ敄閸℃稑绀夋繛鍡樻尵瀹撲線鏌涢幇闈涙珮闁轰礁锕幃妯跨疀閺冨倸顫ч梺璇查椤嘲顫忓ú顏呭仭闂侇叏绠戝▓鑸电節濞堝灝鏋ら柛蹇旓耿瀵偄顓奸崨顏呮杸闁诲函缍嗛崑鈧柟鐤缁辨挻鎷呴崜鎻掑壉闁诲海鐟抽崘鑳偓鍨归悡搴ｆ憼闁绘挾濮烽幉鎼佹偋閸繄顑傞梺浼欑稻濡炰粙寮诲☉銏犵厴闁诡垎鍌氼棜婵犵绱曢崑鎴﹀磹閺嶎偅鏆滈柟鐑橆殔绾惧綊鏌熼梻瀵割槮闁稿被鍔戦弻鐔虹磼閵忕姵鐏嶉梺缁樻尰閻燂箓濡甸崟顖氱睄闁逞屽墴瀹曟洟鎼归銈庢祫闂備緡鍓欑粔鐢告偂濞戞◤褰掓晲閸ュ墎鍔搁梺鍝勬４缁插潡鍩€椤掑喚娼愭繛鍙夘焽閺侇噣骞掑Δ瀣◤濠电娀娼ч鍛不閻斿吋鍊甸柨婵嗛婢ь噣鏌熼婊冧槐婵﹤顭峰畷鎺戭潩椤戣棄浜剧€瑰嫭鍣磋ぐ鎺戠倞妞ゆ帒锕︾粙蹇旂節閵忥絽鐓愰柛鏃€娲滄竟鏇㈠锤濡や胶鍘遍棅顐㈡处閹告悂骞冮幋锔界厱婵炲棗绻掔粻濠氭煛鐏炵偓绀嬬€规洜鍘ч埞鎴﹀箛椤撳濡囩槐鎺楁倷椤掆偓閸斻倗绱撳鍜冭含鐎殿喖顭锋俊鑸靛緞婵犱胶鐐婇梻渚€娼ч¨鈧梻鍕琚欓柛鏇ㄥ幘绾捐棄霉閿濆懎绾фい搴℃閺屾稓鈧綆鍋呭畷灞炬叏婵犲偆鐓肩€规洘甯掗～婵嬵敄閽樺澹曢梺褰掓？閻掞箓宕戠€ｎ亖鏀介柣妯诲絻閺嗙喖鏌ｉ悢娲绘綈濞ｅ洤锕俊鍫曞川椤斿吋顏犵紓浣哄亾閸庡啿顭囬敓鐘茶摕闁绘梻鍘х粻銉︺亜閺冨倵鎷￠柡鍡╁弮濮婅櫣绱掑Ο璇查瀺濠电偠灏欓崰鏍嵁閸愩剮鏃堝川椤旇姤鐝梻浣告啞椤ㄥ牓宕戝☉銏╂晜妞ゅ繐鐗婇悡鐔哥節闂堟稒鎼愰柛婵堝劋閹便劍绻濋崘鈹夸虎閻庤娲﹂崑濠傜暦閻旂⒈鏁囬柣妯诲絻铦庣紓鍌氬€搁崐鎼佸磹閸濄儳鐭撶€规洖娲﹂鑺ユ叏濡灝鐓愰柛瀣戦妵鍕即濡も偓娴滈箖鎮楃憴鍕闁绘牕銈搁妴浣肝旀担铏规嚌闂佹悶鍎洪悡鍫澪涢崘銊㈡斀闁绘ê鐏氶弳鈺呮煕鐎ｎ剙浠辩€规洖缍婂畷濂稿即閻斿憡鐝栭梻浣哥枃濡椼劎娆㈤敓鐘冲€块柦妯猴級閺冨牊鏅查柛娑卞幗濞堟煡姊洪幎鑺ユ暠閻㈩垱甯″﹢渚€姊洪幐搴ｇ畵闁瑰啿绻橀獮澶愬箹娴ｅ湱鍙嗗┑鐐村灦椤洩鍊寸紓鍌欐祰妞村摜鏁敓鐘偓浣割潩鐠哄搫绐涘銈嗘尵婵娊宕Δ鍛拺闁硅鍔曢崥褰掓煕鐎ｃ劌鈧繂顕ｇ拠娴嬫闁靛繒濮烽悿鈧梻鍌氬€搁悧濠勭矙閹烘鍊堕柛顐犲灮绾捐棄霉閿濆懏鎯堥弽锟犳⒑缂佹﹩娈曟い銊ユ缁碍娼忛妸褏鐦堥梺鎼炲労閻忔稖顦归柡灞剧☉閳藉宕￠悙瀵镐邯婵犵數鍋涢幊宀勫磹濠靛棭娼栨繛宸簻娴肩娀鏌涢弴銊ュ婵炲懌鍊濆铏圭磼濡粯鍎撶紓浣虹帛缁诲牓骞冩导鎼晪闁逞屽墮椤曪絾绂掔€ｅ灚鏅濋梺闈涚箳婵攱绂嶆导瀛樷拻濞达絼璀﹂悞鍓х磼缂佹ê濮嶉挊婵囥亜閺嶃劎銆掓い鈺傚絻铻栭柨婵嗘噹閺嗙偤鏌ｉ幘璺盒ラ柣銉邯瀵爼宕归鍨厴濠电姭鎷冪仦鑺ョ彎闂佸搫鏈惄顖涗繆閼稿灚鍎熼柍銉︽灱閹奉偅绻濆▓鍨灈闁挎洏鍊濋垾锕€鐣￠幍顔芥闂佸湱鍎ら崺鍫濐焽閳哄倶浜滈柟杈剧稻椤ュ霉濠婂牏鐣洪柡宀€鍠栧鑽も偓闈涘濡差喚绱掗悙顒€鍔ょ紓宥咃躬瀵鈽夊Ο閿嬫杸闂佸憡娲﹂崑鍕叏婢舵劖鈷戠紒瀣儥閸庢劙鏌熼崨濠冨€愰柨婵堝仜閳规垹鈧綆鍋勬禍妤呮煙閼测晞藟婵℃彃鎳庨…鍥礈瑜忕壕浠嬫煕鐏炲墽鎳呴悹鎰嵆閺屾盯鎮╅幇浣圭暥闁捐崵鍋涢妴鎺戭潩閿濆懍澹曞┑鐘殿暜缁辨洟寮繝姘卞祦闁搞儺鍓欑痪褔鎮规笟顖滃帥闁哥偞妞藉缁樻媴娓氼垱鏁梺瑙勬た娴滅偛顕ユ繝鍐﹀亝闁告劑鍔庨悿?"
            if chinese
            else "I will first understand your goal, project, and blocker, remember that context for the next turn, then decide whether to guide the code, explain the principle, or shape the training thread first."
        )
    )
    if chinese:
        close = "婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄闁挎繂妫Λ鍕⒑閸濆嫷鍎庣紒鑸靛哺瀵鎮㈤崗灏栨嫽闁诲酣娼ф竟濠偽ｉ鍓х＜闁绘劦鍓欓崝銈嗐亜椤撶姴鍘寸€殿喖顭烽弫鎰板川閸屾粌鏋庨柍璇查叄楠炲棜顦虫い鏂垮缁辨捇宕掑▎鎺戝帯婵犳鍠楅幐鎶藉箖濡警娼╅悹杞扮秿閿曞倹鐓曢柡鍥ュ妼閺嬨倝鏌ｉ妶鍌氫壕闂傚倷绀佸﹢閬嶅磻閹捐绠氶悘鐐跺▏濞戙垺鍊烽柣銏㈡暩閿涙繃绻涙潏鍓ф偧闁哄拋鍋婂畷濂割敂閸喓鍘辨繝鐢靛Т閸熸壆绮婚悙纰樺亾濞堝灝鏋涙い顓犲厴楠炲啴濮€閵堝棙鍎梺闈╁瘜閸橀箖宕㈤鐐粹拻濞达絿顭堥ˉ蹇涙煟閹惧磭澧︾€规洘濞婇、姘跺焵椤掆偓閻ｅ嘲鈹戦崶褏绐為梺褰掑亰閸樻悂骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囶亞鐣垫鐐诧躬瀹曟﹢顢旈崱娆欑床缂傚倸鍊烽悞锕傛晝椤愶附鍤€閻犳亽鍔夐崑鎾斥枔閸喗鐏堝銈庡幘閸忔﹢鐛崘顔碱潊闁靛牆妫欓崕顏堟⒑闂堚晛鐦滈柛娆忕箳濡叉劙寮婚妷锔规嫽婵炴挻鍩冮崑鎾寸箾娴ｅ啿鎳忓畷鏌ユ煙閻戞ɑ灏伴柛娆忕箻閺岋綁濮€閻樺啿鏆堥梺绋匡工閻栧ジ寮诲☉銏╂晝闁绘ɑ褰冩慨鏇㈡⒑閹惰姤鏁遍柛銊ユ贡濡叉劙骞掗弬鍝勪壕闁挎繂楠搁獮鏍煕閺傝法浠涢柕鍥у椤㈡洟顢楅崒婊勬闂備礁鎼張顒勬儎椤栨凹鍤曟い鎺戝€瑰畷澶愭煏婵犲啫濮傞柛濠冪箞瀵鎮㈤懖鈺佺ウ闂佸壊鐓堥崰姘婵傚憡鈷戦悗鍦У椤ュ銇勯敃鈧悘姘跺箞閵娾晛鐒垫い鎺戝閻撶喐淇婇娑欍仧闁哥喎绻橀弻娑橆潩椤掍礁娅ょ紓浣虹帛缁诲牓骞冩禒瀣棃婵炴垶顨堥幑鏇熺節绾版ɑ顫婇柛瀣嚇閵嗗啴宕奸妷銉ь唹闂侀潧绻堥崐鏇犵不閹惰姤鐓欏Δ锝呭枤閺夌儤绻涢弶鎴濐仾缂佺粯绻堝Λ鍐ㄢ槈濡嘲浜鹃柟闂寸缁犵喖鏌ㄩ悢鍝勑㈢痪鎯х秺閺岋綁濮€閻樺啿鏆堥梺缁樻尵閸犳牠寮婚敐澶婃闁圭瀛╅崕鎾愁渻閵堝繒鍒伴柕鍫熸倐瀵鈽夐姀鈥充簻闂佸憡绻傜€氼亪骞嬫搴ｇ＝濞达絼绮欓崫娲偨椤栨粌浠辨鐐茬箻閹晝鎷犻懠顒夊斀闂備胶鎳撻幖顐⑽涘Δ浣侯洸濡わ絽鍟悡鏇犳喐鎼淬劊鈧啴宕ㄩ弶鎴濆挤闂侀潧顦弲婊堟偂閻斿吋鐓欓梺顓ㄧ畱婢ь垶鏌熼姘卞ⅱ缂佽鲸甯￠幃顏堝川椤栨簽婊堟⒑閸濆嫯顫﹂柛鏃€鍨甸锝夘敋閳ь剙鐣烽崼鏇椻偓锕傚箣閻戝棙顥夊┑鐘垫暩閸嬫盯鎮洪妸褍鍨濈€光偓閳ь剛妲愰悙瀵哥瘈闁稿被鍊栫紞搴♀攽閻愬弶鈻曞ù婊勭矊椤斿繐鈹戦崱蹇旀杸闂佺粯蓱瑜板啴顢旈鍫熺厱闁挎稑宕崰姘€掓繝姘厪闁割偅绻勭粻浼存煟閿旂晫鐭掗柡灞剧洴婵℃悂濡堕崨顓犮偖闂備胶纭堕弬鍌炲垂瑜版帩鏁囧┑鍌滎焾闁卞洦銇勯幇璺哄挤闁冲搫鎳忛埛鎺懨归敐鍛喐闁哄鍟妵鍕敃閵忊晜鈻堥悗瑙勬礀缂嶅﹤鐣风粙璇炬棃鍩€椤掑嫬鍨傞柛灞绢嚤閺冨牊鏅查柛娑卞幗濞堫厾绱撴担鎻掍壕闂佸憡鍔﹂崰妤呮偂閻樼數妫柡澶婄仢閼哥懓顭胯閹告娊寮婚敐鍛婵炲棙鍔曠壕鍐测攽椤旂》鍔熺紒顕呭灦楠炲繘宕ㄧ€涙ê浠梻渚囧弿缁犳垵鈻撳┑鍥╃瘈闁汇垽娼ф禒锔炬喐閺夊灝鏆熼柟骞垮灩铻ｉ柧蹇氼潐濞堥箖鎮峰鍛暭閻㈩垱顨堥埀顒傛暩婵挳鈥﹂崸妤佸殝鐎电増顨忔禍婊堝煝閹捐惟闁挎柨澧介惁鍫ユ⒑濮瑰洤鐏叉繛浣冲嫮澧＄紓鍌欒兌閸嬫挸顭垮Ο鑲╃煋闁荤喐澹嗛弳锕傛煙鏉堝墽鐣辩紒鈧€ｎ偁浜滈柡宥冨妿閳藉霉閻橆偅娅呴柍瑙勫灴閹瑩寮堕幋鐘辨闁诲骸婀遍…鍫モ€﹀畡鎵殾闁硅揪绠戠粻濠氭偣閸ヮ亜鐨烘い蟻鍥ㄢ拺闁告稑锕ｇ欢閬嶆煕濞嗗繘顎楅摶鐐寸節婵犲倸鏆婇柡鈧禒瀣厽婵☆垵娅ｆ禒娑㈡煛閸″繑娅婇柡灞剧〒閳ь剨缍嗛崜娆愮鏉堚斁鍋撶憴鍕缂傚秴锕ら悾閿嬬附缁嬪灝宓嗛梺闈涱煭闂勫嫬鈻嶉崱妯圭箚闁绘劦浜滈埀顒佹礈閹广垽骞囬悧鍫濅罕濠电姴锕ら悧鍡涘几娓氣偓閺屾稑鐣濋埀顒勫磻閻愮儤鍋傞柡鍥╁枂娴滄粓鏌熼幍铏珔闁逞屽墯濞茬喎顕ｉ崨濠冨劅闁愁厼澧庨幊鎾烩€﹂妸鈺佺闁割煈鍋嗛弶瑙勭節濞堝灝鏋涢柨鏇樺劚椤啯绂掔€ｎ亣鎽曢梺鍛婄☉閻°劑宕愰悜鑺ョ厾闁煎湱澧楃涵鐐亜韫囷絽骞楃紒缁樼箞閸╂盯鍩€椤掑嫬绀嬫い鎰靛亝椤ュ绱撻崒娆愮グ濡炴潙鎽滈弫顔嘉旈埀顒勨€﹂崶顏嗙杸婵炴垶顭傞埡鍛叆闁哄洦顨呮禍楣冩⒒閸屾凹妲哥紒澶屾嚀椤繐煤椤忓懎浠梺鍝勵槹鐎笛傜昂闂傚倷鑳堕幊鎾诲疮鐠恒劍宕查柟鐑樻煥閸ㄦ繈鎮楅敐搴℃灈缂佺姵濞婇弻锟犲磼濮橆厽鍎撴繛瀛樼矒缁犳牠寮婚妸銉㈡斀闁糕剝鐟ラ崵顒傜磽娴ｉ潧濡奸柕鍫熸倐瀵鎮㈤崗鍏煎劒濡炪倖鍔戦崐鏍闯椤斿墽纾藉ù锝勭矙閸濇椽鏌熼悷鐗堟悙闁伙絿鍏橀獮鎺楀箣閺冣偓閻庡姊鸿ぐ鎺戜喊闁哥姵鎹囧畷鎴澪熺拋宕囩畾闂佺粯鍔︽禍婊堝焵椤掍胶澧柍缁樻閺佸啴宕掑鍗炩偓鐐烘偡濠婂啰绠荤€殿喖顭峰畷濂稿Ψ閿旇瀚奸梻渚€娼荤€靛矂宕ｉ埀顒佷繆閻愵剚鍊愰柡灞剧洴閹晝鈧湱濮撮ˉ婵嬫⒑娴兼瑧鍒伴柣蹇旀皑缁參鎮㈤悡搴ｅ姦濡炪倖甯掔€氼參宕戦崒娑栦簻闁规澘澧庨悾閬嶆煟閹邦剨韬柡灞炬礃缁绘稖顦柛瀣尰娣囧﹪骞撻幒鏂库叺闂佽鍠楅〃濠囧箖閻戣姤鍋嬮柛顐ｇ箖濞堟绱撻崒娆愮グ妞ゆ泦鍥ㄥ亱闁规崘宕靛畵渚€鏌涢幇鈺佸闁哄啫鐗嗛悞鍨亜閹烘垵顏╅柣鎾偓鎰佺唵閻犲搫褰块崼銉ュ嚑鐎广儱妫庢禍婊堟煙閻愵剦娈旈柛濠傤煼瀹曟瑩宕烽鐘碉紳婵炶揪绲块…鍫ュ焵椤掆偓閹芥粎鍒掗弮鍫熷€婚柦妯猴級閿曞倹鐓欓柣妤€鐗婄欢鑼磼閻樺啿鈻曢柡宀€鍠撶槐鎺楀閻樺吀鐢婚梺璇插閻喚鍒掑▎蹇ｆ綎缂備焦蓱婵潙銆掑鐓庣仯闁告梹鎮傚娲传閸曨厼鈷堥梺鍛婃尰閻熲晠鏁愰悙娴嬫斀閻庯綆鈧厸鏅犻弻銊╁籍閸ヮ灝鎾绘煟濠靛棗妲婚柍瑙勫灴閹瑩寮堕幋鐘辨婵犳鍠楄彠闁告柨瀛╃粩鐔煎即閻旀椽妾梺鍛婄☉閿曘倝鍩€椤掑倹鏆柡灞诲妼閳规垿宕卞☉鎵佸亾濡も偓闇夋繝濠傚缁犳﹢鏌嶈閸撴繈锝炴径濞掓椽寮介鐔峰壒闂佺鐬奸崑娑㈡嫅閻斿吋鐓熼柡鍐ㄥ€甸幏锟犳煛娴ｉ潻韬柡灞剧缁犳盯寮撮悙韫帛濠电偛顕慨鐢稿箰閸愬樊娼栭柧蹇曟嚀鐎垫煡鏌￠崶鈺佹瀾婵犮垺甯″铏圭矙濞嗘儳鍓遍梺鐟版啞閹倿鍨鹃弮鍫濈妞ゆ柨妲堣閺屾盯鍩勯崘鐐暭闂佽崵鍠嗛崝鎴﹀蓟閿濆棙鍎熼柕蹇曞Т濮ｅ牓姊洪崨濠勬噧闁哥喐娼欓悾鐑藉传閸曘劍顫嶉梺闈涚箳婵兘顢欐繝鍥ㄢ拺闁荤喐澹嗛幗鐘绘煟閻旀潙鐏茬€规洘鍨块獮妯兼嫚閼碱剦鍞洪梻浣筋潐閹矂宕㈡禒瀣＝闁汇垹鎲￠埛鎴︽煙缁嬫寧鎹ｇ紒鐘虫崌閺岀喖宕橀懠顑絿绱掗弮鍌氭灈鐎殿喗鎸抽幃銏ゆ惞閸︻厽顫岄梻鍌欑劍閻綊宕归挊澶樼劷鐟滃海绮嬮幒妤€鐓涘〒姘川閸炵敻姊洪懡銈呮瀾濠㈢懓妫欓弲鍫曞即閵忥紕鍘介梺鎸庣箓濞层倝宕㈤幘顔界厵妞ゆ梻鍋撳▍鏇犵磼椤旂晫鎳呴柟鐟板閳ワ箓骞嬪┑鍥ㄦ瘎闂傚倷娴囧畷鐢稿窗閹邦喖鍨濋幖娣灪濞呯姵淇婇妶鍛殲闁哄棙绮嶆穱濠囧Χ閸涱喖娅ｇ紒鐐劤椤兘寮诲☉銏犲嵆闁靛鍎虫禒顓㈡⒑缂佹ɑ灏甸柛鐘崇墵瀵鎮㈤悡搴ｎ唹闂佸綊鍋婇崢鎹愩亹瑜斿娲捶椤撶噥浠х紓浣圭叀缁犳牗淇婇悽绋跨妞ゆ牗绋掑▍鍡涙煟閻樺弶鎼愮€殿喖鐖奸幃闈涒攽鐎ｎ偀鎷洪柣鐘叉礌閳ь剝娅曢悘宥咁渻閵堝啫濡奸柨鏇ㄤ邯楠炲啯瀵奸幖顓熸櫔闂侀€炲苯澧柣锝囨焿閵囨劙骞掑┑鍥ㄦ珦闂備胶绮幐鍝モ偓鍨笒椤洤鈽夐姀鈾€鎷婚梺绋挎湰閻燂妇绮婇悧鍫涗簻闁哄洨鍠撴晶鐢碘偓瑙勬磻閸楀啿顕ｆ禒瀣垫晣闁绘柨鐨濋崑鎾绘嚋閻㈢數鐦堥梻鍌氱墛缁嬫挻鏅堕弴鐘亾濞堝灝鏋涚€殿喛鍩栫粚杈ㄧ節閸ャ劌鈧攱銇勮箛鎾愁仱闁稿鎹囧鎾偐閸愭彃绨ラ梻浣哥秺閸嬪﹪宕伴幒妤€纾婚柟鐐墯濞尖晜銇勯幇鈺佺仼缂佷緡鍣ｉ幃妤€鈻撻崹顔界彯闂佺顑呯€氫即鍨鹃敃鍌毼╅柍杞拌兌椤︺劑姊洪幐搴ｇ畵婵☆偅鐟╁鍫曞箹娴ｅ厜鎷洪梺闈╁瘜閸樺ジ宕濈€ｎ亖鏀介柣鎰嚋瀹搞儵鏌ｉ敐鍥у幋妤犵偛娲鍓佹崉閵娧勬緫闂傚倷绀侀幖顐λ囬崘娴嬫灃闁哄洢鍨洪弲顒佺箾閹存瑥鐏柍閿嬪灴閹嘲鈻庤箛鎿冧患闂佸憡鏌ｉ崐鏇⑩€﹂懗顖ｆЩ濠电偞鎸抽弨杈╃博閻旂厧鍗抽柣鏃€妞藉顕€姊洪崨濠勨槈闁挎洩绠撳畷銏ゆ寠婢跺棙鏂€闂佸疇妫勫Λ妤呮倶閻樼粯鐓欑痪鏉垮船娴滄壆鈧鍠楁繛濠囧蓟閸℃鍚嬮柛鈩冪懃鐢绱撻崒姘偓鐑芥倿閿曚焦鎳岀紓鍌欒閸嬫捇鎮楅敐搴℃灍闁绘挻绋撻埀顒€鍘滈崑鎾绘倵閿濆骸澧伴柨娑氬枑缁绘稓鈧數顭堥鎾剁磼閻樿櫕宕屾鐐插暙閳诲酣骞欓崘鈺傛珜闂備胶顭堢悮顐﹀磹閺嶎兘鍙块梻鍌氬€峰ù鍥敋瑜庨〃銉╁箹娴ｇ懓鈧埖鎱ㄥ鍡楀⒒闁绘柨妫欐穱濠囶敍濮樿鲸鐧侀梺绋款儐閹告悂锝炲┑瀣垫晣闁绘柨鎼崵鎺楁⒒娴ｉ涓茬紒鎻掓健瀹曟顫滈埀顒勭嵁閸愵喖鐒洪柛鎰ㄦ櫅閸斿懎鈹戦埥鍡楃仯缂侇噮鍨跺鍫曞箹娴ｅ厜鎷绘繛杈剧秬濞咃綁濡存繝鍐х箚闁绘瑦鐟ュú銈夋偪閻愵剛绡€闂傚牊渚楅崕蹇涙煟閹烘垹浠涢柕鍥у楠炴帡骞嬪┑鎰礉婵犵妲呴崑鍛村垂閸︻厽顫曢柟鐑樻尰缂嶅洭鏌曟繝蹇曠暠缁剧偓濞婇幃妤冩喆閸曨剛顦ㄩ柣銏╁灡鐢繝宕洪姀鈩冨劅闁靛鍎抽濠囨⒑閻熸壆鎽犵紒璇插€块幊娆撳箛椤撶姷鐦堥梺姹囧灲濞佳勭墡婵＄偑鍊栧褰掓偋閻樿尙鏆﹂悷娆忓闂勫嫮绱掔€ｎ厽纭堕柣鎾村灴濮婃椽宕ㄦ繝鍌氼潎闂佸憡鏌ㄩ柊锝咁嚕閹惰姤鏅濋柛灞剧〒閸樼敻姊虹拠鈥崇仭婵犮垺顭堥。鍧楁⒒娴ｅ憡鎯堥柟鍐茬箺閵囨劙宕橀鍏夊亾閿旂偓宕夐柕濠忕畱绾绢垶姊虹紒妯碱暡闁圭纾▎銏ゅ箻椤旇В鎷虹紒缁㈠幖閹冲氦顣挎繝鐢靛仜瀵爼鎮ч悩璇叉槬闁绘劕鎼粻锝夋煥閺冨洦顥夐柍褜鍓涢崗姗€寮婚埄鍐ㄧ窞閻庯綆浜炴禒鍏肩箾鐎电校闁诡喖鍊垮濠氬Χ閸ャ劌鏅抽梺闈涚墕閹冲宕戦幘鏂ユ斀閻庯綆浜ｉ幗鏇㈡⒑鐠恒劌鏋斿┑顔芥尦閹偤宕归鐘辩盎闂佺懓鎼粔鐑藉礂鐏炰勘浜滈柍鍝勫暙閸樻挳鏌熼绛嬫疁闁轰焦鍔栭幆鏃堝灳閼碱剚鏅奸梻鍌欑閹诧繝鈥﹂崶顒€鏋侀悹鍥ф▕濞兼牜绱撴担璇＄劷闁荤喎缍婇弻娑㈠Ψ閹存繂鏆曠紒杈╁枔缁辨捇宕掑顑藉亾閹间礁纾归柣鐔煎亰濞尖晠鏌曟繛鐐珕闁搞倕绉瑰鍫曞醇濞戞ê顬嬪銈傛櫇閸忔﹢骞冨Δ鍛櫜閹肩补鈧尙鏁栭梻浣告啞閿曘垻绮婚弽顓炶摕闁挎繂妫欓崕鐔兼煃閳轰礁鏆㈢痪顓涘亾婵犵數濮甸鏍窗濮樿泛鏋佸┑鐘冲搸閳ь兛绶氬顕€宕奸悢铚傛睏闂備焦鐪归崹濠氬极閹间焦鏅繝濠傜墛閻撴稑顭跨捄鐚村姛濠⒀勫灴閺屾盯寮捄銊愩倕霉濠婂啯鍟為悗浣冨亹閳ь剚绋掗…鍥储閻㈠憡鍊甸柣鐔告緲椤忣偄顭胯椤ㄥ﹤鐣烽搹顐ゎ浄閻庯綆鍋嗛崢鐢告⒑閸涘﹦鎳冩い锔藉娴滄悂鏁傞柨顖氫壕閻熸瑥瀚粈鍫ユ煕閻樺磭澧甸柕鍡曠椤粓鍩€椤掑嫬绠栨繛鍡樻尭閻顭跨捄鐑樻崳闁告瑦鍨剁换婵嬫偨闂堟刀銉︺亜閿濆骸鏋ゆ俊鍙夊姍瀵挳濮€閻樼绱遍梻浣侯攰閹活亞绮婚幋鐘差棜鐟滅増甯楅悡娑氣偓骞垮劚濞撮攱绂嶇憴鍕鐎瑰壊鍠曠花濂告煛閸涱喚绠為柡灞剧〒娴狅箓骞戦幇顒夋闂備胶顭堥鍛矓閸偆鈹嶅┑鐘叉搐鍥撮棅顐㈡处濞叉牠宕哄畝鍕拺闁告縿鍎卞▍蹇涙煕鐎ｎ亝顥犻柛鎺撳浮瀹曞ジ濡烽妷銉ㄢ偓鍨攽閻愭潙鐏﹂柣鐔濆洤鍌ㄩ柣銏犳啞閳锋垹绱撴担濮戭亪鎮橀敃鍌涚叆闁哄洦顨嗗▍鍛存煃缂佹ɑ宕岀€殿噮鍣ｉ崺鈧い鎺嶈兌閳瑰秴鈹戦悩鍙夌ォ闁轰礁鍟撮弻銊モ槈閹烘挻鐝曢梺鎼炲妼缂嶅﹪鐛幋锕€顫呴柣姗嗗亝椤秹姊洪棃娑氱濠殿喗鎸抽幊鎾诲垂椤旇鏂€闂佸疇妫勫Λ妤呮倶閻樼粯鐓欑痪鏉垮船娴滄繈鏌熸笟鍨濠殿喒鍋撻梺闈涚墕濡矂骞忓ú顏呯厽闁绘ê寮剁粈宀勬煃瑜滈崜婵嗏枍閺囥垺鍊剁€广儱顦伴埛鎴︽煙閼测晛浠滃┑鈥炽偢閺岋綀绠涢弮鍌滅暰闂佽绻愰澶婎潖濞差亜宸濆┑鐘插婵洭姊虹拠鈥崇仩闁活厼鍊搁锝夘敃閿曗偓缁€鍐┿亜閺冨倹娅曢柛姗嗕邯濡懘顢曢姀鈩冩倷闁肩懓鐭傞弻娑氣偓锝庡亝瀹曞本顨ラ悙鍙夊闁瑰嘲鎳樺畷婊堝箛椤斿吋鐎婚梺瀹狀潐閸ㄥ潡骞冮埡鍛瀭妞ゆ劧绲鹃惁搴ㄦ⒒娴ｄ警鐒炬い鎴濇缁瑩骞嬮敂缁樻櫔闂佹寧绻傞ˇ顖滅矆閸緷褰掓晲閸ュ墎鍔搁梺璇茬箰閿曨亜顫忛搹瑙勫枂闁告洦鍋嗛ˇ銊ヮ渻閵堝棙鑲犻柛娑卞灟缁楀姊洪崫鍕枆闁诲繑鍔橀妵鎰板箳閹寸媭妲梻浣侯焾缁绘宕戦幇顔剧煓闁搞儺鍓氶悡鏇㈡煟閹存繃顥滈柣蹇ラ檮閹便劍绻濋崘鈹夸虎閻庤娲橀敃銏犵暦閿濆棗绶為悗锝庝簻婢瑰秹姊婚崒娆掑厡妞ゎ厼鐗撻弫鍐Χ婢跺棌鍋撻敃鈧悾锟犲箥椤旇姤顔曢梻渚€娼ф蹇曟閺囶潿鈧懘鎮滈懞銉モ偓鐢告煥濠靛棝顎楀ù婊呭仱閺屾稑螣閸忓吋姣堝┑顔硷攻濡炶棄鐣峰Δ鍛殐闁崇懓鐏濇禒锕傛⒒娴ｅ憡鎯堥柟铏姍瀹曟垿鎮╅崣鍌涚洴婵偓闁靛牆妫岄幏缁樼箾鏉堝墽鍒伴柟璇х節瀹曨垶鎮欓悜妯煎幍濠殿喗绻傞懟顖炲触瑜版帗鐓欐鐐茬仢閻忚尙鈧娲滈崰鏍€佸☉姗嗘僵濡插本鐗曢弫鎼佹⒑閼姐倕鏋戠紒顔煎閺呰泛螖閸愨晜娈板┑掳鍊曢幊搴ㄦ偪妤ｅ啯鐓欓梻鍌氼嚟閸斿秹鏌ｉ幘璺烘瀾濞ｅ洤锕、娑樷攽閸ユ湹鍝楅梻浣瑰缁嬫垹绮旇ぐ鎺戣摕婵炴垶锕╁銊╂煃瑜滈崜姘辩矉瀹ュ閱囬柡鍥╁仩閹芥洟姊洪幐搴ｇ畵婵☆偅鐟╁畷鏇㈡偄閹肩偘绨婚梺鍝勭Р閸斿酣鎯屽畝鍕唨闁跨喓濮甸埛鎺懨归敐鍛暈闁哥喓鍋ら弻鐔虹矙濞嗗墽鍚嬮梺璇″枤閸忔﹢宕洪埄鍐懝闁搞儜鍕靛悪缂傚倸鍊风粈渚€顢栭崨顖濆С闁告鍊ｉ敐澶婇唶闁靛濡囬崢顏堟椤愩垺鍌ㄩ柛搴＄－婢规洟宕稿Δ浣哄幈?idea闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃闁硅櫕鎹囬垾鏃堝礃椤忎礁浜鹃柨婵嗙凹缁ㄧ粯銇勯幒瀣仾闁靛洤瀚伴獮鍥敍濮ｆ寧鎹囬弻鐔哥瑹閸喖顬堝銈庡亝缁挸鐣烽崡鐐嶆棃鍩€椤掑嫬鐓曢柟鐑橆殕閳锋垹绱撴担濮戭亞绮閺岋繝宕担闀愬枈濡ょ姷鍋涢ˇ杈╁垝濞嗗繆鏋庨柟顖嗗嫬鈧垶姊绘担绋款棌闁稿甯掗…鍧楀焵椤掑倻纾介柛鎰ㄦ櫆缁€瀣叏婵犲偆鐓肩€规洘甯掗埢搴ㄥ箣椤撶啘婊堟⒒娴ｅ憡璐￠柍宄扮墦瀹曟垶绻濋崒婊勬濡炪倖鐗滈崕鎰板极閸愵喗鐓ラ柡鍐ㄦ处椤ュ霉濠婂棝鍝虹紒缁樼箞閹粙妫冨ù韬插灪缁绘稓浠﹂崒姘ｅ亾濡や胶鐝堕柡鍤堕姹楅梺鍦劋閹搁箖宕㈤柆宥嗗仭婵犲﹤鍟撮崣鍕煏閸℃鏆ｇ€规洖宕埥澶娾枎韫囧海鏆楅梻鍌欑窔濞佳囁囬锕€鐤炬繝濠傜墛閸嬪倹绻涢幋娆忕仾闁绘挻娲熼弻鏇熷緞閸繄浠惧┑鐐叉噹閹冲酣婀侀梺缁樏壕顓㈡儗閹烘鐓涢悘鐐垫櫕鍟稿銇卞倻绐旈柡灞剧洴楠炴﹢寮堕幋婵囨嚈婵°倗濮烽崑娑㈠疮閺夋垹鏆﹂柟鐑樺焾濞尖晠鏌ｉ幘鍐差劉妞ゆ挸娼″缁樻媴閸涘﹤鏆堢紓浣割儐閸ㄥ潡寮崘顔嘉ㄩ柨鏇楀亾闁搞劍妫冮幃妤呮濞戞瑦鍠愮紒鐐劤閸氬濡甸崟顖氬唨闁靛ě鈧慨鍥╃磽娴ｆ彃浜鹃梺鍛婂姦閸犳鎮″☉銏＄厱閻忕偟铏庡▓鏂棵瑰鍫㈢暫婵﹤顭峰畷鎺戭潩椤戣棄浜鹃柣鎴ｅГ閸ゅ嫰鏌涢锝嗙５闁逞屽墾缁犳挸鐣锋總绋课ㄩ柕澶堝劤瑜板淇婇悙顏勨偓鏍暜閹烘纾归柟闂寸閸戠娀鏌涢鐔稿櫚闁稿鎹囬悰顕€宕归鐓庮潛婵＄偑鍊х€靛矂宕归崼鏇炵畺闁秆勵殢閺佸鏌嶈閸撶喎顕ｆ繝姘櫜濠㈣泛锕﹂悿鈧俊鐐€栧濠氬储瑜庢穱濠偯洪鍛嫼缂傚倷鐒﹁摫閻忓繒鏁婚弻娑㈡偐瀹曞洤鈷岄悗娈垮枛椤兘骞冮姀銈呯闁绘挸绨堕崑鎾剁磼濡湱绠氬銈嗙墬缁诲啴顢旈悩缁樼厱闁哄啠鍋撻柟顔煎€搁～蹇涙惞閸︻厾锛滃┑鈽嗗灥椤曆呭枈瀹ュ鈷戦梻鍫熺〒婢ф盯鏌熼鐓庘偓鎼侇敋閿濆棛绡€婵﹩鍓涙导瀣倵鐟欏嫭绀€婵炶绠戦埢鎾诲即閵忥紕鍘介柟鍏兼儗閸ㄥ磭绮旈悽鍛婄厱闁规儳顕幊鍥┾偓瑙勬礀閹碱偊鎮惧┑瀣妞ゆ帒鍊稿鏉库攽閻愬瓨缍戦柛姘儔閹柉顦寸紒顔芥椤㈡岸鍩€椤掑嫬钃熼柨娑樺濞岊亪鎮归崶銊с偞闁稿鎹囧浠嬵敇閻愮數鏉介梻渚€娼ц墝闁哄懏绋撶划璇测槈濞嗗秳绨婚梺纭呮彧缁查箖藟婢跺⊕鐟邦煥閸垻鏆梺鍝勫閳ь剚鍓氶崥瀣箹缁厜鍋撳畷鍥跺晥闂傚倷鐒﹂幃鍫曞磹閺嶎灐娲偄閻撳氦鎽曞┑鐐村灟閸ㄧ懓鏁俊鐐€栧濠氬储瑜旈敐鐐侯敂閸啿鎷洪梺瑙勫劶婵倝寮柆宥嗙厱闁靛鍎虫禒銏°亜椤愩垻绠伴悡銈嗐亜韫囨挾校闁哄懏绻堝娲濞戞艾顣洪梺鐟板暱缁夊爼宕氶幒妤€閱囬柡鍥╁暱閹锋椽姊虹粙璺ㄧ闁告艾顑夋俊鐢告偄閸忚偐鍘遍梺闈浥堥弲娆撳箟閸撗€鍋撳▓鍨灍闁绘挴鈧磭鏆﹀┑鍌滎焾閸楁娊鏌曟繝蹇涙婵炲懏鎹囧缁樻媴閸涘﹤鏆堥梺鍦焾濡繂鐣烽鍫濈妞ゅ繐瀚崫搴㈢節閻㈤潧啸闁轰礁鎲￠幈銊﹀閺夋垵鐎梺缁樻尭缁ㄥ爼寮搁弽銊х闁瑰瓨鐟ラ悘顏堟煛閸涱喚绠為柡灞诲姂瀵剟宕归瑙勫瘱闂備焦妞块崢浠嬪箲閸ヮ剙钃熼柨婵嗩槸缁狅綁鏌ｉ幋婵囩煑缂佸爼娼ч埞鎴︽倷閼碱剙顣圭紓渚囧枟閻熲晛顕ｆ繝姘櫜濠㈣泛锕﹂悿鈧俊鐐€栧濠氬磻閹惧墎纾奸柣娆愮懃鐎氥劍绂嶅鍫熺厪濠㈣埖绋撻崚浼存煟韫囷絽娅嶉柡灞界Х椤т線鏌涢幘瀵哥疄闁挎繄鍋炲鍕箾閹烘垶鎯堟い顓滃姂瀹曠厧鈹戦崼銏犵倞闂傚倷绀侀幖顐ょ矙娓氣偓瀹曘垼銇愰幒鎴犲姦濡炪倖鍨煎▔鏇⑺囬敃鍌涚厓闁芥ê顦藉Ο鈧繝娈垮枓閸嬫捇姊洪弬銉︽珔闁哥噥鍨堕幃鐢稿箮閼恒儮鎷绘繛杈剧秬濞咃綁濡存繝鍥ㄧ厱闁规儳顕粻姘舵煙缁涘浜版慨濠呮缁辨帒螣閼测晝绐楅梻浣告啞濮婂綊宕归悽闈╃稏闊洦姊荤弧鈧┑顔斤供閸撴盯鏁嶅鍐ｆ斀闁绘劕寮堕ˉ鐐烘偨椤栨稑娴€规洏鍨介弫宥夊礋椤撶媴绱茬紓鍌氬€烽梽宥夊垂瑜版帞宓侀柡宥庡幗閻撶喖鏌″搴′簻閻㈩垰鐖奸弻锝夋晲閸涱厽些濡炪値鍘归崝鎴濈暦濮椻偓閺佹劙宕卞Ο缁樼帆闂傚倷娴囬褔宕欓悾宀€绀婇柛鈩冪☉绾惧鏌涢弴銊ュ妞も晠鏀遍妵鍕箻閸楃偟浠鹃梺绋款儌閸撴繄鎹㈠┑鍥╃瘈闁稿本鍑规禒鎯ь渻閵堝啫鍔氭俊顐ｇ懄缁岃鲸绻濋崶鑸垫櫇闂侀潧鐗嗛幊蹇涙倵鐠囧樊娓婚柕鍫濈凹缁ㄥ鏌涢悢椋庢憼濞ｅ洤锕畷濂稿即閻愯尪鈧灝鈹戦埥鍡楃仯闁靛棗顑囧Σ鎰板煛閸涱喒鎷绘繛杈剧导鐠€锕傛倿閻愵兙浜滈柟瀛樼箖椤ャ垺顨ラ悙鏉戠伌鐎规洖鐖奸、妤呭焵椤掑嫭瀚呴柣鏂垮悑閻撱儲绻涢幋鐏活亪顢旇缁绘稑鐣濇繝浣烘晼缂備浇椴哥敮鐐哄焵椤掑﹦绉靛ù婊呭仦缁傛帡濮€閵堝棛鍘撻悗鐟板閸嬪﹤螣閳ь剟姊虹拠鈥虫灍妞ゃ劌锕ら悾鐤亹閹烘繃鏅濋梺鎸庣箓濞层倝宕甸幒妤佲拺閻犲洦褰冮銏㈢棯閺夎法孝妞ゎ厼鐏濋～婊堝焵椤掑嫬绠栧Δ锝呭暞閸婂鏌﹀Ο渚Ш妞ゃ垹鎳樺铏圭磼濡搫顫岀紓浣割槸閻栫厧鐣锋导鏉戝唨妞ゆ挾鍋熼悿鍥⒑鐠恒劌鏋斿┑顔芥綑濞插潡姊绘担鍛婂暈濞撴碍顨婂畷鍦偓鍦У閹冲矂姊婚崒姘偓鎼佸磹閹间礁纾归柟闂寸绾惧湱鈧懓瀚崳纾嬨亹閹烘垹鍊炲銈庡墻閸撴岸鎯勯姘辨殾闁绘梻鈷堥弫宥嗘叏濡潡鍝洪柣鎺楃畺濮婄粯鎷呴悷鏉垮Б濠电偛鐡ㄥ畝绋跨暦閹寸偞濯撮柛锔诲弾濞村嫰姊洪崜鎻掍簴闁稿孩鐓￠幃锟犲即閻旇櫣顔曢梺鐟邦嚟閸庢垿宕楅鍕厱闁哄啫鍊搁弸娑㈡煛鐏炵晫效闁诡喚鍏橀獮宥夘敊瑜嬮崹浠嬪蓟瀹ュ洦鍠嗛柛鏇ㄥ亞娴煎矂姊虹拠鈥虫灀闁哄懐濮撮悾鐑芥晲閸℃绐為柣搴秵閸嬪嫰鍩€椤掑倸鍘存慨濠勭帛閹峰懐鎲撮崟鈺€鎴烽梻浣告啞鐪夌紒顔界懇婵℃挳宕橀鐓庣獩缂備緡鍠栭崢婊堝磻閹剧粯鏅滈柣鎰靛墮绾绢垶姊洪棃娑辩叚缂佺姵鍨规竟鏇㈩敍濞戞氨顔曢梺鍦亾濞兼瑩宕甸鍕厱闁靛鍊曞畵鍡欌偓瑙勬礃缁秶鈧絻鍋愰埀顒佺⊕鑿ら柟閿嬫そ濮婄粯绗熼崶褌绨介梺绋款儐閻╊垶骞婇悢纰辨晬婵炴垶鐟﹂悵宄邦渻閵堝棛澧遍柛瀣仱閹繝寮撮姀锛勫幐闂佸憡鍔х徊鑺ョ閹屾富闁靛牆鍟俊濂告煥閺囥劋绨婚柣锝呭槻鐓ゆい蹇撳閸旓箑顪冮妶鍡楃瑐闂傚嫬绉电粋宥咁煥閸喓鍘甸梺缁樺灦閿氶柣蹇嬪劦閺岋紕鈧絻鍔岄埀顒佺墱閹广垹鈽夐姀鐘殿槯闂佺粯鎸告鎼侊綖瀹ュ洨纾藉ù锝堟鐢盯鏌ｉ埡濠傜仩闁伙絿鍏橀弫鎰板幢濡ゅ啰鐛繝鐢靛仦閸ㄨ埖绔熼弴銏犵；闁规崘顕ч柨銈嗕繆閵堝嫯鍏岄柛姗嗕邯濮婅櫣鍖栭弴鐐测拤濡炪們鍔岄幊妯侯嚕閹惰姤鍊烽柣銏㈡暩閿涙粎绱撻崒娆戝妽妞ゎ厼娲ㄧ划濠氭倷绾版ê浜鹃悷娆忓缁€鍐偨椤栨稑娴柍銉畵婵℃悂鍩℃担渚Ч婵＄偑鍊栫敮鎺椝囬鐐茬柧妞ゆ挶鍨洪埛鎺楁煕鐏炴崘澹橀柍褜鍓涢崗姗€骞婂Δ鍛濞达絿顭堥悘濠傤渻閵堝棛澧遍柛瀣〒缁粯瀵肩€涙鍘卞┑鐘绘涧鐎氼剟宕濋妷銉㈡斀妞ゆ棁妫勯埢鏇㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎妯恍氱紓鍌氬€搁崐椋庢媼閺屻儱鐤炬繛鎴欏灪缁犳帡姊绘担铏瑰笡闁挎碍淇婇姘捐含鐎规洘娲熼獮鍥偋閸垹骞楅梻浣筋潐閸庢娊鎮洪妸褏鐭嗛柛鎰靛枟閻撳繘鏌涢妷鎴濆枤娴煎啫螖閻橀潧浠滄繛宸弮瀹曟椽鍩勯崘鈺侇€撻梺鍦帛鐢﹥绔熼弴銏♀拺闁告繂瀚崒銊╂煕閵娿儳绉虹€规洘鐟╅幃鈺冪磼濡厧骞嶉梺鍝勵槸閻楁挾绮婚弽褜鐎舵い鏇楀亾闁哄矉缍侀獮妯兼崉閻戞浜梻浣告惈鐞氼偊宕濋幋婵愬殨妞ゆ洍鍋撻柛鈹惧亾濡炪倖甯掔€氼剛澹曢崸妤佺叄闊浄绲芥禍鐐淬亜閳哄啫鍘寸€殿喖鐖煎畷鐓庘槈濡警鐎撮梻浣告啞閻熴儳鎹㈤幇鏉跨厴闁硅揪闄勯崑鎰版煙缂佹ê绗氭繛鍫熺叀濮婃椽妫冨☉娆忣槱缂備浇顕ч悧鎾愁嚕婵犳碍鍋勯柧蹇撶秺閳瑰繘姊洪棃鈺佺槣闁告﹢绠栭幆渚€宕奸悢铏圭槇缂佸墽澧楄彜闁稿鎸搁悾鐑藉炊瑜忛崢浠嬫煟鎼淬値娼愭繛鎻掔箻瀹曟繈骞嬪┑鍫熸濡炪倕绻愰悧鍡欑矆閸愨斂浜滈煫鍥ㄦ尰閿涙梻绱掓潏鈺傛毄缂佽鲸鎹囧畷鎺戔枎閹邦喓鍋樺┑锛勫仦濞兼瑩骞楀鍫濇瀬妞ゆ洍鍋撻柟顔界懇瀹曨偊宕熼褍鏁搁梻浣筋嚙閸戠晫绱為崱娑樼獥闁哄稁鍘肩粻鏌ユ煠閸濄儱浠ù婊勭矒閺岀喖骞戦幇顓犮€愰柛鐔侯焾閳规垿鍩勯崘銊хシ濠电偛妯婇崣鍐嚕婵犳碍鏅查柛鈩兠崝鍛存⒑闂堟稓澧曢悗娑掓櫇缁辩偤宕煎┑鍐╂杸闂佺粯鍔栧娆戝緤閼姐倗纾肩紓浣光棨椤忓牊鍋╅柣銈庡灛娴滃綊鏌熼悜妯诲碍闁谎冨缁绘繈濮€閿濆棛銆愰梺鍝勭墱閸撴瑩鍩㈤幘璇茬畾鐟滃寮ㄦ禒瀣厽婵☆垱顑欓崵瀣偓瑙勬偠閸庡弶绌辨繝鍥舵晝妞ゆ劑鍨圭粻褰掓煕濡も偓瀹曨剟鍩為幋锔藉亹鐎规洖娴傞弳锟犳⒑閹惰姤鏁遍柛銊ユ健瀵鎮㈤崗鐓庢異闂佸疇妗ㄥ鎺斿垝閼哥數绡€缁炬澘顦辩壕鍧楁煛閸滀礁浜炴俊鍙夊姍楠炴帡寮埀顒傗偓姘哺閺屻倗鍠婇崡鐐差潻闂佹剚浜褑鐏冮梺缁橈耿濞佳勭濠婂牊鐓曢柣鏇氱娴滀即鏌ㄥ┑鍫濅粶妞ゎ厹鍔戝畷鐓庘攽閸繂袝濠碉紕鍋戦崐鏍暜閹烘柡鍋撳鐓庡缂侇喖顭峰浠嬪Ω瑜忛鏇㈡⒑缁洖澧查拑閬嶆倶韫囷絽骞樼紒杈ㄥ浮閹晠宕归锝嗙槗闂備礁鎼惉濂稿窗閺嵮呮殾妞ゆ劧绠戠粈瀣亜閹烘埈妲归柨娑楃窔濮婅櫣鎷犻弻銉偓妤呮煟韫囨柨鍝洪柟顔ㄥ洦鍋愮€瑰壊鍠楃紞搴ｇ磽閸屾瑧鍔嶉拑鍗炩攽椤栨稒灏﹂柡灞剧☉閳规垿宕熼銏犘ョ紓鍌欐祰娴滎剟宕戦悢鐑橆潟闁规儳顕悷褰掓煕閵夋垵瀚ぐ顖炴⒒娴ｈ鍋犻柛鏂跨У閸掑﹥绂掔€ｎ偄鈧爼鎮楅敐搴℃灍闁抽攱鍨块弻娑樷槈濮楀牆浼愭繝娈垮櫙缁犳捇寮诲☉銏″亹鐎规洖娲ら埛宀勬⒑瑜版帗鏁遍柛銊ユ健楠炲啴濮€閵堝懐顦ч梺鍏肩ゴ閺呮稓鏁ィ鍐┾拻濞达絿顭堥ˉ蹇涙煕鐎ｎ亝鍣介柟骞垮灲瀹曟﹢顢欓姀鐙€妯€闁诡喗鐟╅幃婊兾熼悡搴＄疄濠电姷鏁搁崑娑樜涘Δ鍐╁床闁圭儤姊绘稉宥呪攽閻樺磭顣查柣鎾寸〒閳ь剙鍘滈崑鎾绘煃瑜滈崜鐔风暦娴兼潙鍐€妞ゆ挾鍋犻幗鏇㈡⒑閹肩偛鍔撮柛鎾村哺瀵彃鈹戠€ｎ偆鍘撻悷婊勭矒瀹曟粓鎮㈡搴㈡闂侀潧绻堥崐鏇犵不缂佹ǜ浜滈柡鍐ㄥ€瑰▍鏇㈡煕濮椻偓娴滃爼寮婚敐鍡樺劅妞ゆ牗绮庢牎闂備胶顭堥鍛村箠鎼淬劍鍋╃€瑰嫭澹嗛弳鍡涙煃瑜滈崜鐔煎春閳ь剚銇勯幒宥囪窗闁哥喎绻橀弻娑㈡偐閹颁焦鐤佸Δ鐘靛仦閸旀瑩鐛惔銊﹀癄濠㈣泛鐬奸弳顐ｇ節閻㈤潧浠滄俊顐ｇ懇楠炴劙骞栨担鐟颁簵濠电偞鍨崹娲偂閺囥垺鍊堕柣鎰絻閳锋棃鏌ｉ鐐搭棤缂佽鲸甯℃俊鎼佹晜閽樺鏀繝娈垮枛閿曘倝鈥﹀畡鎵殾闁圭儤鍨熼弸搴ㄦ煙閻戞ê鐏ラ悽顖ｅ灣缁辨捇宕掑▎鎴ｇ獥闂侀潻缍嗛崳锝呯暦瑜版帒閱囬柡鍥╁仧娴煎姊洪幐搴㈢闁稿﹥鎮傞幃娆愮節閸ャ劎鍘撻柡澶屽仦婢瑰棝藝閿曞倹鐓熼煫鍥ㄦ惈瀹搞儲銇勯鍕殻濠碘€崇埣瀹曞崬鈻庤箛濠冨珱闂傚倷鑳堕…鍫ヮ敄閸ヮ剙纾婚柕鍫濇噽閺?"
    else:
        close = "Tell me which lane is closest right now: implementing an idea, adapting a project, or shaping the training thread first."
    return "\n\n".join([part for part in (first, second, close) if part.strip()])


def _reply_needs_first_turn_reframe(reply: str) -> bool:
    stripped = reply.strip()
    if not stripped:
        return False

    paragraphs = [part.strip() for part in stripped.split("\n\n") if part.strip()]
    if len(paragraphs) >= 3:
        return True
    if len(stripped) >= 260:
        return True

    lowered = stripped.lower()
    structural_signals = ("```", "## ", "### ", "\n- ", "\n* ", "\n1. ", "\n2. ")
    if any(signal in lowered for signal in structural_signals):
        return True

    return False


def _compose_principle_followthrough_patch(
    *,
    reply: str,
    principle_note: dict[str, object],
    chinese: bool,
) -> str:
    if not principle_note:
        return ""

    why_it_matters = str(principle_note.get("why_it_matters") or "").strip()
    apply_now = str(principle_note.get("apply_now") or principle_note.get("follow_up_exercise") or "").strip()

    needs_reason = bool(why_it_matters) and not (
        _reply_mentions_excerpt(reply, why_it_matters) or _reply_has_reason_signal(reply, chinese)
    )
    needs_apply = bool(apply_now) and not (
        _reply_mentions_excerpt(reply, apply_now) or _reply_has_action_signal(reply, chinese)
    )
    parts: list[str] = []
    if chinese:
        if needs_reason:
            parts.append(f"\u5b83\u5728\u8fd9\u91cc\u91cd\u8981\uff0c\u662f\u56e0\u4e3a{why_it_matters}\u3002")
        if needs_apply:
            parts.append(f"\u4f60\u73b0\u5728\u5148{apply_now}\u3002")
    else:
        if needs_reason:
            parts.append(f"It matters here because {why_it_matters}.")
        if needs_apply:
            parts.append(f"Apply it now by {apply_now}.")
    return " ".join(parts).strip()


def _compose_missing_next_step_patch(
    *,
    reply: str,
    scenario: str,
    next_step_hint: str,
    file_path: str | None,
    project_entry_points: list[str],
    learner_signal: str,
    mode: str,
    chinese: bool,
) -> str:
    step = next_step_hint.strip()
    if not step:
        return ""
    if _is_meta_step_hint(step):
        return ""

    if _reply_mentions_excerpt(reply, step):
        return ""
    if _reply_has_action_signal(reply, chinese) and len(reply) > 120:
        return ""

    anchored_step = _anchor_step_to_workspace(step, file_path=file_path, project_entry_points=project_entry_points, chinese=chinese)
    if chinese:
        if scenario in {"project_idea", "engineering_challenge"}:
            return ""
        if scenario == "principle":
            return ""
        if learner_signal == "blocked":
            return ""
        if mode == "direct":
            return ""
        return ""

    if scenario in {"project_idea", "engineering_challenge"}:
        return f"Do not widen this into a larger plan yet. Take this first cut: {anchored_step}"
    if scenario == "principle":
        return f"Turn the principle into action with this move: {anchored_step}"
    if learner_signal == "blocked":
        return f"For this turn, do only this next move: {anchored_step}"
    if mode == "direct":
        return f"Start directly with this step: {anchored_step}"
    return f"The next move is this: {anchored_step}"


def _compose_guided_lane_continuity_patch(
    *,
    reply: str,
    scenario: str,
    chinese: bool,
) -> str:
    guided_lane = _first_turn_guided_lane(scenario, "")
    if guided_lane not in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return ""
    if _reply_has_guided_lane_signal(reply, guided_lane, chinese):
        return ""
    return _first_turn_lane_continuity_note(guided_lane, chinese=chinese)


def _compose_review_tightening_patch(
    *,
    reply: str,
    scenario: str,
    failing_checks: list[str],
    learning_outcomes: list[dict[str, object]],
    pace_signal: str,
    learner_signal: str,
    chinese: bool,
) -> str:
    repeated_failure = _has_repeated_failure_signal(learning_outcomes, pace_signal, learner_signal)
    review_pressure = scenario in {"review", "task", "next_task", "plan", "project_adaptation"} or bool(
        failing_checks or repeated_failure
    )
    if not review_pressure:
        return ""
    if _reply_has_scope_tightening_signal(reply, chinese) and _reply_has_verification_signal(reply, chinese):
        return ""

    check = failing_checks[0] if failing_checks else ""
    if chinese:
        if check:
            return f"闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欑粣娑㈡⒑閸濄儱校闁圭澧介崚鎺旂磼濡浜濋梺鍛婂姀閺呮繈宕㈡禒瀣拺闂侇偅绋戝畵鍡樼箾娴ｅ啿瀚▍鐘炽亜閺嶎偄浠﹂柣鎾跺枑缁绘繈妫冨☉娆忣槱缂備讲鍋撻悗锝庡亝閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濮风槐鎺楊敊閻ｅ本鍣ч梺瀹狀嚙闁帮綁鐛崱姘兼Щ婵犮垼顫夐敋闁宠鍨块幃娆撴嚑椤掍焦鍠栫紓鍌欑贰閸犳碍鎱ㄩ悽鐢电焿鐎广儱顦介弫鍌炴煕閺囥垺娑ф繛鍫涘姂閺岋綁鎮╅崣澶婎槱缂備椒鐒﹀娆忓祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔告倐濮婃椽宕ㄦ繝鍐ｆ嫻闂佸湱顭堥崯鍧楋綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愬宀婃澓濠电姷鏁搁崑娑㈡偤閵娧冨灊鐎广儱顦伴崑瀣煛閸モ晛浠滅紒渚囧亰濮婄粯鎷呯粙娆炬闂佺顑勭欢姘暦瑜版帗鍤掗柕鍫濇媼濡粓姊洪懞銉冾亪藟閵忥絻浜归柟鐑樻尰濞呮粓姊虹化鏇炲⒉妞ゃ劌鐗忕划濠囨煥鐎ｎ剛顔曢柣搴㈢⊕椤洭鎯岄幒鏃傜＜闁绘ê纾晶顏呫亜椤愩垻绠婚柟鐓庣秺瀹曠兘顢橀悩闈涘箚闂備浇宕垫慨鍨娴犲绀夐幖娣灩椤曢亶鏌涢妷顔煎闁抽攱鍨圭槐鎺斺偓锝庡亽閸庛儵鏌涙惔銏犵伌闁哄本绋撻埀顒婄祷閸斿矂鍩€椤掍胶绠為柣娑卞櫍瀹曟﹢顢欓懞銉︻仧闂備胶绮摫鐟滄澘鍟悾鐢稿幢濞戞瑢鎷虹紓鍌欑劍钃遍柍閿嬪笧缁辨帞绱掑Ο鑲╃暭闂佸ジ缂氭ご鍝ユ崲濠靛棭娼╂い鎾寸⊕鐎氬ジ姊洪懡銈呮瀾闁荤喆鍎抽埀顒佸嚬閸樻儳鈻庨姀銈呯闁圭儤绻勯崬鐢告偡濠婂啰效闁哄苯锕弫鎰緞鐏炵晫銈﹂梻浣告啞閸旓箓宕板Δ鍛惞闁告劦鍠楅悡鍐煕濠靛棗顏╅柡鍡欏枛閺屻劌鈽夊▎鎴犵厜濠殿喖锕ㄥ▍锝囨閹烘埈娼ㄩ柛鈩冪懃婵吋绻濋悽闈涗粶闁瑰啿绻愮叅闁哄稁鍘介崑鈺冣偓鐟板婢瑰棝寮抽崱娑欑厱闁哄洢鍔屾晶浼存煕濡粯鍊愰柟顔筋殜瀹曟寰勬繝浣割棜闂備浇顕ч崙鐣岀礊閸℃稑绀堟繛鎴炲閸欑儤绻濆閿嬫緲閳ь剚顨嗛幈銊╂倻閽樺锛涢梺缁樺姇閻忔岸寮冲鍫熺叆闁绘柨鎼暩閻庤鎸风欢姘跺箖濡ゅ懏鏅查幖瀛樼箘閹稿姊洪崫鍕靛剰闂佸府缍侀幃锟狀敃閿曗偓閻愬﹦鎲搁弮鍫晛婵°倕鎳忛悡鏇㈡煏婵犲繐顩紒鐘靛仦閹便劍绻濋崒銈囧悑閻庤娲樼敮鎺楀煝鎼淬劌绠ｆい鎾跺晿濠婂牊鈷掑ù锝呮啞鐠愶繝鏌嶅畡鎵ⅵ鐎规洘鍨剁换婵嬪炊瑜忛悾鐐節閵忥絾纭炬い鎴濇喘濮婁粙宕熼鐘碉紲闁诲函缍嗛崢鐣屾兜閸洘鐓熸繛鎴炵墪閸旓附鎱ㄦ繝鍛仩闁瑰弶鎸冲畷鐔碱敃閵堝孩袨濠碉紕鍋戦崐鏍р枖閿曞倸宸濇い鏍ㄧ矊缁犲灚绻濆閿嬫緲閳ь剚鍔欏畷鎴﹀箻缂佹鍘撻柣鐔哥懃鐎氼剟鎮橀幘顔界厵妞ゆ棁顫夊▍濠囨煟閹垮啫浜版い銏★耿閸╁嫰宕橀…鎴炵秿闂傚倸鍊搁崐鐑芥嚄閸撲礁鍨濇い鏍嚤濞戞瑦濯寸紒顖涙礃閻庢椽姊洪幐搴ｇ畵婵炲眰鍊濊棢婵鍩栭悡鏇㈢叓閸ャ劎鈯曢柨娑氬枔缁辨帞鎷犻崣澶樻！闂侀潧娲ょ€氭澘顕ｆ禒瀣╃憸蹇涙偂閳ь剟姊哄Ч鍥х労闁搞劎澧楅弲鑸垫償閿濆棭娼熼梺鍦亾閸撴岸宕ョ€ｎ€㈠綊鏁愭径瀣彸婵犮垼顫夊ú鐔奉潖婵犳艾纾兼慨姗嗗厴閸嬫捇骞栨担鍝ワ紮闂佸綊妫跨粈浣哄閸︻厸鍋撻悷鏉款仾闁革絿顥愰妵鎰板箳閹寸姴鈧偛顪冮妶鍡楃瑨妞わ缚鍗冲鏌ヮ敂閸喎浠┑鐘诧工閸熸挳宕ｉ崟顖涚厪闁糕剝顨呴弳锝呪攽閿涘嫬鍘撮柛鈹惧墲閹峰懏绗熼姘珝濠电姷鏁搁崑鐘诲箵椤忓棗绶ら柛褎顨呯粻鐘绘煙閹规劦鍤欓柣鎺戠仛閵囧嫰骞掗幋婵囨闂佺粯鎸婚崝娆撳蓟閻斿摜鐟归柛顭戝枛椤牓鏌ф导娆戠М闁哄本鐩垾锕傚箣濠靛洨浜鹃梻浣告啞閿曗晠宕戞繝鍌ゆ綎闁惧繐婀遍惌娆愮箾閸℃ê鍔ら柛鎾存緲椤啴濡堕崱妤冧淮濡炪倧绠撳褔顢氶敐鍡欑瘈婵﹩鍘藉▍婊堟⒑閸涘﹦鈽夐柛濠傤煼瀹曚即寮借閺嗭妇鎲搁悧鍫濅刊闁轰礁锕弻锝夊箛闂堟稑鈷掗梺鎼炲€曠€氭澘顫忔繝姘＜婵炲棙鍩堝Σ顕€姊洪崷顓涙嫛闁稿瀚悘瀣煟鎼淬劍娑ч柟鑺ョ矋缁嬪顓兼径瀣幍闂佺顫夐崝锕傚吹濞嗘挻鐓㈤柛鎰典簻閺嬫盯鏌＄仦鐐鐎规洜鍘ч埞鎴﹀炊瑜忛悰鈺呮⒒娴ｈ銇熼柛妯圭矙閹兘鍩￠崨顓犵暫閻熸粎澧楃敮鎺旂不閹烘鐓欓柣鎴灻悘銉︺亜椤掆偓濡稓妲愰幘瀵哥懝闁搞儜鍕壕闂備浇妗ㄧ粈渚€骞楀鍏撅綁骞囬弶璺啋闁荤姴娲╃亸娆撴晬濠婂啠鏀芥い鏃傚嵆閹达附鍎婇柣鎴ｆ椤懘鏌ㄥ☉妯侯伀妞ゆ梹娲熼幃妤呮偡閺夋妫岄梺鍝ュУ閻楁洟顢氶敐澶樻晩闂佹鍨版禍鐐箾閸繄浠㈤柡瀣堕檮閵囧嫰寮撮崱妤佹悙闁绘挴鈧剚鐔嗛柤鎼佹涧婵洦銇勯銏″殗闁哄矉绲借灒婵炶尪顕ч弲閬嶆⒑閸濄儱鏋庢い鎴濇閹广垹鈹戦崱鈺佹闂備礁鐏濋鍡欐閺屻儲鐓冪憸婊堝礈濮樿泛绀夋繛鍡楃箳閺嗭箓鏌熸潏鍓х暠缂佺姾宕电槐鎾存媴鐠囷紕鍔烽梺鍛婎焽閺佸骞冨Δ鍛仭闁哄顑欐导鍐⒑缁嬫鍎忛柨鏇ㄤ簻閻ｇ兘寮撮敍鍕澑濠电偞鍨堕…鍥€侀崨瀛樷拻濞撴艾娲ゆ晶顔剧磼婢跺本鏆柟顕嗙節閹垽宕楅懖鈺佸箥闂佸搫顦悧鍡樻櫠娴犲绀嗛柟娈垮枟閸嬫牗鎱ㄥΟ鍨厫闁抽攱鍨块弻鐔煎箚閺夊晝鎾绘煛娓氣偓娴滃爼骞冩禒瀣垫晬婵炴垶蓱鐠囩偛鈹戦悩顐壕婵炴挻鍩冮崑鎾存叏婵犲啯銇濇鐐村姈閹棃鏁愰崶鈺傛闂備浇顕х€涒晠宕欒ぐ鎺戝瀭闁割偅娲忛埀顑跨铻栭柛娑卞枛娴滄粓姊虹粙璺ㄧ闁稿鍔欏畷銏＄鐎ｎ偀鎷洪梺闈╁瘜閸樺ジ宕濈€ｎ喗鐓曢柕濞у嫭姣堥梺绯曟櫆閻╊垰顕ｉ鈧畷鎺戭煥閸滃啰搴婇梻浣告惈椤︻垶鎮ч崟顖氱鐎光偓閳ь剛鍒掗鈽嗘Ь缂備浇椴哥敮妤€顭囪箛娑樜╅柕澹懏鍣梻浣稿綖缁鳖喚绱炴笟鈧璇测槈濡攱鏂€闂佺硶鍓濋〃蹇斿鐏炶В鏀介柣鎰絻閹垹鈧厜鍋撶紒瀣儥濞兼牜绱撴担鑲℃垶鍒婄€靛摜纾兼繛鎴烇供閸庡繑绻涢崼鐔峰婵﹥妞藉畷顐﹀Ψ閵夛妇褰欓梻浣侯焾椤戝懘鏁冮妶澶嬪仼闁绘垼妫勭粻姘舵⒑椤撱劑妾禍娑㈡⒒閸屾瑧顦﹂柛姘儏椤灝顫滈埀顒勫箖濡　鏀介悗锝庝簽閸樻挳姊虹涵鍛涧闂傚嫬瀚板鏌ヮ敆閸曨剛鍘遍梺鍝勬储閸斿本绂嶅Δ浣虹鐎光偓婵犱胶鐩庨梺瀹狀潐閸ㄥ潡骞冨▎鎾崇闁圭儤妫冮悰鎾剁磽閸屾瑦绁版い鏇嗗洤纾归柛褎顨呴弰銉╂煏韫囨洖顎岄柛姘儏椤法鎹勬笟顖氬壉濠电偛鎳忕划宥囨崲濠靛顫呴柨婵嗘閵嗘劙姊洪幐搴㈢┛缂佺姵鎹囬妴浣糕枎閹邦剛绐為梺褰掑亰閸樻悂骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囨ê鍔滅€垫澘瀚板畷鐔碱敍濞戞艾骞堥梻渚€娼ц噹闁告劗鍋撳В澶愭⒒娴ｄ警鐒鹃悗鍨浮瀹曟垶绻濋崶褑鎽曢梺鎸庣箓椤︿即宕戦崟顖涚厱婵犻潧瀚崝銈夋煟閹绢垰浜剧紓鍌氬€搁崐鐑芥嚄閸撲礁鍨濇い鏍仦閺呮繈鏌曡箛鏇烆€岄柛?`{check}` 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘遍梺闈涚墕閹冲酣顢旈銏＄厸閻忕偛澧藉ú瀛樸亜閵忊剝绀嬮柡浣瑰姍瀹曞崬鈻庡Ο鎭嶆氨绱撻崒姘偓鐑芥嚄閼稿灚鍙忛梺鍨儑缁犻箖鏌嶈閸撶喖寮婚垾宕囨殕闁逞屽墴瀹曚即寮借閺嗭附绻濇繝鍌涳紞婵℃煡绠栭弻锝夊閳轰胶浠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫婵炲棙鍨归惁鍫ユ⒑閸涘﹣绶遍柛姗€绠栧畷銏ゎ敃閿旇В鎷洪梻渚囧亝缁嬫捇鍩為幒妤佺厱闁哄倽娉曢悞鐑芥煟韫囨柨娴慨濠冩そ瀹曠兘顢樿閸旂鈹戦悙宸殶闁稿繑蓱娣囧﹪骞橀鑲╃杸濡炪倖鏌ㄦ晶浠嬫晬濠靛洨绠鹃弶鍫濆⒔閸掍即鏌熺喊鍗炰簼闁绘閰ｅ缁樻媴閾忕懓绗￠梺鍦拡閸嬪棝骞戦姀鐘斀闁糕檧鏅涘▓銊╂煟閻樺弶澶勭紒浣规綑鍗遍柛顐犲劜閻撳繘鐓崶銊︾妞ゎ偄绉归弻鏇熺節韫囨氨顦版繛瀛樼矋缁捇寮婚敓鐘茬闁靛鍎崑鎾诲传閵夛附娈伴梺鐓庢憸閸嬶絾绂嶅鍕╀簻闁归偊鍠栭弸鎴炵箾閸涱叏鏀婚柟渚垮妽缁绘繈宕ㄩ鍛摋缂傚倷娴囨ご鍝ユ暜閹烘洜浜介梻浣瑰劤缁绘劕锕㈤柆宥呯疇闁糕剝绋掗埛鎺懨归敐鍥╂憘闁搞倖鐟х槐鎺旂磼濡櫣浠撮梺浼欑稻缁诲牆鐣烽妸锔剧瘈濞达綀娅ｉ悾楣冩⒒娴ｅ湱婀介柛銊ヮ煼閳ワ箓宕奸姀銏㈢劶闁诲函缍嗛崑浣圭濠婂牊鐓涚€广儱鍟俊浠嬫煟閵婏箑鐏﹂柕鍥у瀵剟宕犻檱閸氼偊姊虹拠鈥虫灍妞ゃ劌锕幃浼搭敋閳ь剙鐣疯ぐ鎺濇晩闁绘挸瀵掑娑㈡⒒閸屾瑨鍏岀紒顕呭灦閵嗗啴宕ㄩ鍥ㄧ☉閳规垿宕卞▎鎰啎闂備線娼х换鍫ュ磹閺嶎厼鐤鹃柟闂寸劍閻撶喐淇婇婊呭笡闁诲繘浜堕弻鐔兼偪椤栨侗浠╃紓浣介哺閹瑰洤鐣烽幒鎴旀瀻闁瑰瓨绻傞‖澶愭⒑閽樺鏆ｅù婊冪埣瀵鎮㈢喊杈ㄦ櫖濠殿喗锕╅崜锔藉閸愵喗鈷戦柛婵嗗濠€浼存煟閳哄﹤鐏″ǎ鍥э躬楠炴牗鎷呴懖婵勫妿閹茬鈹戦崼鐕佹綗闂佺粯鍔栫粊鎾绩娴犲鐓冮柕澶堝劚閺嗚京绱掗悪娆忔处閻撴洟鏌￠崘锝呬壕闂佽崵鍟块弲鐘诲箖娴兼惌鏁嬮柍褜鍓熼悰顕€骞掑Δ鈧粻鐘绘煣韫囷絽浜濇い銉ョ墦閺屾盯鍩為幆褌澹曞┑锛勫亼閸婃牕顔忔繝姘；闁瑰墽绮幊姘舵煟閹邦剛鎽犻柛娆忕箲娣囧﹪鎮欐０婵嗘婵炲瓨绮撶粻鏍ь潖閾忚瀚氶柍銉ㄦ珪閻忓牏绱撻崒姘毙㈤柨鏇ㄤ邯閹即顢欓悾宀€鎳濋梺閫炲苯澧撮柣娑卞櫍楠炴帒螖閳ь剛绮婚敐鍡欑瘈闁割煈鍋勬慨澶愭煃瑜滈崜姘跺箰閸愬樊娼栫紓浣股戞刊鏉戙€掑鐓庣仭闁轰緡鍨堕弻锝堢疀閹惧顩版繛瀛樼矤娴滄粓鎮鹃悜钘夌闁挎洍鍋撶紒鐘崇⊕閵囧嫰寮崒婊勬啒濠电偠鍋愰崰鏍ь潖閾忚鍠嗛柛鏇ㄥ亜婵垽姊虹€癸附婢樻俊浠嬫煕閹烘埊韬鐐达耿椤㈡瑩鎮剧仦钘夌疄闂傚倷绀佸﹢閬嶅磻閹炬剚鐒芥繛鍡樺灥缁躲倕鈹戦悩宕囶暡闁绘挻娲熼弻鐔煎箚瑜忛幗鐘电磼鐠哄搫绾ч柕鍥у椤㈡棃宕熼锝嗩啋濠电姷顣介崜婵嬪磿閼测晝涓嶆繛鎴欏灩缁犲ジ鏌涢幇銊︽珔闁哄濞€濮婂宕掑▎鎰偘濠碘剝銇滈崝搴ｅ垝閸喓鐟归柍褜鍓熼崹楣冩晝閸屾稓鍙嗛柣搴岛閺呮繄绮诲鑸电厽閹兼番鍨婚埊鏇熴亜椤撶偞鍠橀柟顔炬焿閵囨劙骞掗幘璺哄笚闁荤喐绮嶇划鎾崇暦濠婂啠鏋庨柟鍨暞閺咁亪姊洪幐搴ｇ畵妞わ缚绮欏顐も偓锝庡枟閻撳啰鎲稿鍫濈婵炲棙鎸婚崑鈺呮煟閹达絽袚闁稿鍊块獮鏍偓娑欍€為幋锕€妫橀柍褜鍓熷缁樻媴閾忓箍鈧﹪鏌涢幘瀵哥疄闁诡喚鏌夐ˇ鏌ユ煟閿濆洤鍘寸€规洦鍋婂畷鐔煎Ω閿旇姤婢戦梻鍌欑劍鐎笛呯矙閹寸姭鍋撳鐓庡缂佸倸绉电缓浠嬪川婵犲嫬骞堝┑鐘垫暩婵挳宕悧鍫熸珷妞ゅ繐鐗婇幊姘舵煟閹邦垼姊跨憸鐗堝笚閺呮煡鏌涘☉鍗炴灍闁哥姵鍔欏娲传閸曨剨绱ㄧ紓浣哄У閹瑰洤顕ｆ繝姘櫜濠㈣泛顭濠囨⒑缂佹◤顏堝触閳ь剛绱掗鐐毈婵﹥妞藉畷顐﹀礋椤掑锛佺紓鍌欑贰閸犳牜绮旈崼鏇炵闁靛繒濮Σ鍫ユ煏韫囨洖啸妞ゆ挸鎼埞鎴︽倷閸欏妫炵紓浣虹帛鐢绮嬮幒鎾卞亝闁告劏鏂侀幏娲⒑鐟欏嫬鍔跺┑顔哄€濆顐︽焼瀹ュ棛鍘遍梺闈涱焾閸庢煡宕戦妷锔绘闁绘劖褰冮弳銏ゆ煏閸ャ劌濮嶆鐐村浮楠炲鎮╁ù瀣壕闁绘劕妯婂〒濠氭煏閸繃鍣界紒鐘卞嵆閹顫濋悡搴㈢亪閻炴碍鐟╅弻鏇＄疀鐎ｎ亞浼勭紒鐐礃濡嫰婀侀梺鎸庣箓閹冲繘骞嗛崼銉ュ唨闁斥晛鍟扮弧鈧梺闈涚箞閸ㄦ椽宕甸埀顒€鈹戦埥鍡椾簼缂佸鍨靛畵鍕⒑閸︻厼顣兼繝銏☆焽缁骞庨懞銉у幐闂佸憡鍔戦崝宀勫焵椤掆偓椤兘寮鍜佺叆闁告劧绲鹃弬鈧梻浣哥枃濡嫬螞濡ゅ懏鍊堕柣妯肩帛閻撴瑧鐥弶鍨埞濞存粈鍗抽弻銊モ攽閸繀娌梺璇″灡濡啯淇婇幖浣规櫆閻熸瑥瀚褰掓⒒閸屾瑦绁扮€规洜鏁诲畷浼村箛椤撶姷褰鹃梺绯曞墲缁嬫帡宕戦埡鍌樹簻闁规儳宕悘顏堟煟閹惧瓨绀嬮柡灞炬礃缁绘盯宕归鐟颁壕婵°倕鎳忛崕妤佺箾閸℃ɑ灏伴柣鎾跺枑缁绘盯骞嬪┑鍡氬煘濠电偛鎳庣粔鍫曞焵椤掑喚娼愭繛鍙夌墵閹儲绺介幖鐐╁亾娴ｈ倽鏃€鎷呴崫銉х嵁闂佽鍑界紞鍡涘磻閸涘瓨鍋熸繝濠傚缁♀偓闂佹眹鍨藉褑鈪烽梻浣规偠閸斿酣宕㈣閸┿垽寮惔鎾搭潔闂侀潧绻嗛崜婵嗏枍閸ヮ剚鈷戦梻鍫熶緱濡叉挳鏌￠崨顏呮珚鐎殿噮鍋婂畷鍫曨敆娴ｅ搫骞堥柣鐔哥矊闁帮綁濡撮崘顔煎耿婵炴垶顭囬崢閬嶆⒑閸︻厼鍔嬮柛銈嗕亢閵囨劙骞掗幘瀛樼彸闂備焦鎮堕崕杈ㄦ櫠鎼淬劌绀夐柟闂寸劍閳锋垿鎮归崶锝傚亾閾忣偆浜堕梻浣规偠閸斿酣寮拠璇ц€垮ù锝囩《閺€浠嬫煟濡顤呴柛顐犲劚绾惧鏌熼幆褍顣崇痪鎯у悑閵囧嫰寮崒娑欑彧闂佺懓鍟块崯鎾蓟閿濆鏅查柛銉戝啫绠ｉ柣搴㈩問閸犳骞愰搹顐ｅ弿闁逞屽墴閺屽秹濡烽妸锔惧涧濡炪倖鎸搁妶绋款潖缂佹鐟归柍褜鍓欓…鍥樄闁诡啫鍥у耿婵＄偑鍨洪惄顖炪€佸鈧幃婊堝幢濞嗗繐楔闂傚倷鑳剁划顖炲蓟閵娾晛瑙﹂悗锝庡枛閻撴洟鏌熸潏楣冩闁绘挻娲樼换婵嬫濞戞瑯妫炲銈呯箚閺呯娀寮婚敓鐘插耿婵☆垰鍚嬮崳浼存⒑閸濆嫮鐒跨紒鎻掆偓鐔轰簷闂備線鈧偛鑻晶鎾煛娴ｇ鏆ｆい銏℃瀹曠厧鈹戦崼銏℃瘒闂傚倷娴囧▔鏇㈠窗閹惧瓨鍙忛柟缁㈠枛绾偓闂佽鍎兼慨銈夋偂閻斿吋鐓涢柛鎰╁妼閳ь剝宕靛褔鍩€椤掑倻纾藉ù锝夋涧婵″吋銇勯鐐叉Щ妞ゎ偄绻戦妶锔炬啑閵堝嫭鐫忛梻浣告贡閸庛倝宕归幎钘夌獥濠电姴娲﹂埛鎴︽煕濠靛嫬鍔氶弽锟犳⒑缂佹﹩娈曟繛鑼枛楠炲啫煤椤忓秵鏅ｉ梺闈涚箚濡狙囧箯缂佹绠鹃弶鍫濆⒔閸掍即鏌熺拠褏绡€鐎规洦鍨堕幃娆戔偓娑櫭鎸庣節閻㈤潧孝闁稿﹤婀遍幏褰掓晸閻樺磭鍘遍梺鍦劋閹哥霉椤旂瓔娈介柣鎰儗閻掍粙鏌熸搴♀枅闁瑰磭濞€閹虫粓宕归銏℃瘒闂傚倸鍊搁崐鐑芥嚄閸撲礁鍨濇い鏍嚤濞戙垹绀冩い鏂诲灩椤︾敻鐛Ο鍏煎珰闁告瑥顦崇欢銏ゆ⒒娴ｇ懓顕滄繛鍙夌墵瀹曟劘銇愰幒鎾充簵闂佸搫娲㈤崹娲偂韫囨搩鐔嗛悹杞拌閸庡繘鏌ｈ箛鎾缎ч柡灞剧〒閳ь剨缍嗛崑鍛暦瀹€鍕厸鐎光偓鐎ｎ剛锛熼梺閫炲苯澧剧紓宥呮缁傚秴鈹戠€ｎ亜鎯為梺鎼炲劘閸斿秹宕ｈ箛鎾斀闁绘ɑ褰冮弳鐐烘煏閸ャ劎绠橀柍褜鍓濋～澶娒洪敃鍌氱；濠电姴鍊婚弳锕傛煟閺冨倵鎷￠柡浣割儔閺屾稑鈽夐崡鐐寸仌闂佸搫鎲為崶銊㈡嫽闂佺鏈悷褔藝閿曞倹鐓欓悹鍥囧懐鐦堥悗娈垮枛椤攱淇婇幖浣哥厸闁稿本鑹炬竟鎺楁⒒娴ｄ警鐒鹃柣顒€銈稿畷鎴濃槈閵忕姴寮烽梺闈涱槴閺呮粓鎮¤箛鎿冪唵闁煎摜鏁搁妴鎺楁煟閿濆牅鍚紒杈ㄥ浮瀹曟粍鎷呴梹鎰崟闂備礁鐤囬～澶愬垂閸ф绠栨繛鍡樻惄閺佸倿鏌涢弴銊ュ箳缂佽鲸娲熷缁樻媴閸涘﹥鍠愭繝娈垮枤閺佸骞冭閹晠鎳￠妶鍛偊濠电姷鏁告慨鏉懨洪妶澶婄闁逞屽墮椤啴濡堕崱妯烘殫闂佺顑囬崰鏍х暦閵忋倕绠瑰ù锝呭帨閹锋椽姊绘笟鍥т簽闁稿鐩幊鐔碱敍濞戞瑦鐝烽梺缁橆殔閻楀懐鎹㈤崱娑欑厱婵炲棗娴氬Σ绋库攽椤斿吋澶勯柕鍥у椤㈡洟鏁愰崶鈺冨帨闂備胶纭堕弬渚€宕戦幘鎰佹富闁靛牆妫楅崸濠囨煕鐎ｎ偅灏伴柕鍥у椤㈡洟濮€閵忋埄鍞虹紓鍌欐祰妞村摜鏁幒鏇犱航闂佽崵濮村ú銈呂熸繝鍥х劦妞ゆ帊鐒﹀畷灞炬叏婵犲啯銇濈€规洏鍔嶇换婵嬪礋椤撶姵娈奸梻浣筋嚙鐎涒晠宕欑憴鍕洸闁绘劕鐏氶～鏇㈡煙閹规劦鍤欑紒鐘哄吹缁辨挻鎷呮銊﹀哺楠炲繘鎼归崷顓狅紳婵炶揪绲芥竟濠囧磿韫囨稒鐓熼煫鍥ㄦ⒒缁犵偞銇勯姀鈽嗘疁濠殿喒鍋撻梺闈涚墕濡盯宕㈡禒瀣拺闁荤喐澹嗘禒銏ゆ倵濮樼厧鏋ょ€殿啫鍥х劦妞ゆ帒瀚埛鎴︽煙閼测晛浠滃┑顔煎€荤槐鎺楁偐瀹曞洤鈷岄悗娈垮櫘閸嬪﹤鐣峰鈧、娆撴嚃閳哄搴婂┑鐘愁問閸犳鏁嬮悗瑙勬处閸撶喖宕洪埀顒併亜閹烘垵鈧憡绂掑鍕╀簻妞ゅ繐瀚弳锝呪攽閳ュ磭鍩ｇ€规洖宕灃闁逞屽墮椤洭骞嬮敂瑙ｆ嫼缂備礁顑嗛娆撳磿閹扮増鐓欑紒瀣仢閳锋梹淇婇崣澶婂妤犵偞甯掕灃濞达綁鏅查弶顓㈡⒒娓氣偓閳ь剛鍋涢懟顖涙櫠鐎电硶鍋撶憴鍕缂傚秴锕ら悾閿嬬附缁嬪灝宓嗛梺缁樺姉閺佹悂寮抽锝囩瘈鐎典即鏀卞姗€鍩€椤掍焦绀嬫鐐诧龚缁犳稑鈽夊Ο鍏肩叄闂備礁鎼悮顐﹀磿鏉堚晝涓嶉柛锔诲幘绾惧吋銇勯弮鍌氫壕闁搞倐鍋撳┑鐘媰閸曨厼寮ㄩ梺鍝勭焿缂嶁偓缂佺姵鐩獮妯兼崉鐞涒€冲緧闂傚倷绀侀幖顐﹀嫉椤掑嫭鍎庢い鏍ㄧ◥缁诲棝鏌ｉ幋锝呅撻柡鍛矒閺岋箑螣娓氼垱笑闂佽　鍋撴い鎾跺枔缁♀偓濠电偛鐗嗛悘婵嬪几濞戙垺鐓ラ柡鍥崝姘亜椤忓嫬鏆ｉ柟绋匡攻瀵板嫮浠﹂悙顒夊晭闂傚倷绶氬褔鈥﹂鐔剁箚闁搞儮鏅涙慨顒勬煃瑜滈崜姘辨崲濞戞瑦缍囬柛鎾楀憛姘攽閻愬弶瀚呯紒鑼舵硶閸掓帗绻濆顒傤唺濠德板€撶拋鏌ュ箯缂佹绠鹃弶鍫濆⒔缁夘剚銇勯銏╂█鐎规洘鍨块幃鈺冪磼濡厧骞堥梻浣告惈閸婁粙宕曢懡銈傚亾濮橆偄宓嗛柡宀嬬秮閺佹劙宕惰楠炲顪冮妶鍐ㄧ仾妞ゃ劌锕ら悾鐑芥偄绾拌鲸鏅濋梺闈涚墕閹冲海绮婚幎鑺モ拻闁稿本鐟чˇ锔界節閳ь剟鏌嗗鍛紱闂佽宕橀褏绮堥崼鐔稿弿婵☆垰鐏濋悡鎰版煕鐎ｎ亜鈧潡寮婚弴鐔风窞闁糕剝蓱閻濇洟姊虹紒妯诲鞍婵炲弶锕㈡俊鐢稿礋椤栨氨鐤€闂佸疇妗ㄧ拋鏌ュ磻閹捐鍗抽柕蹇曞Т閸ゆ垿姊洪崫鍕殭闁绘锕幃锟犲即閻斿墎绠氬銈嗙墬缁矂宕濈€ｎ喗鐓曢柣鏂挎惈娴犙呯磼鏉堛劌绗х紒杈ㄥ笒铻ｉ柤娴嬫櫇閺夎棄鈹戦悩鎰佸晱闁哥姵甯″畷鎴﹀箻缂佹ǚ鎷洪梺鍦焾濞撮绮婚幘缈犵箚妞ゆ劧绲垮ú鏉戔攽閳╁啯灏︽鐐叉喘椤㈡牠鎳為妷锔芥緫闂傚倷绀侀悿鍥涢崟顐嬫稑螖娴ｄ警娲稿┑鐘绘涧椤戝棝鎮￠悢鍏肩厽闁哄啠鍋撴繛鍏肩懇瀹曟繈鏁冮崒娑氬幈闂佸磭鎳撻悘婵嬫倶閳哄倶浜滈柟鎯у暱閹垹鈧灚婢樼€氼厾鎹㈠┑瀣＜婵犲﹤鎳庨弰銉︾節绾板纾块柛瀣灴瀹曟劙寮介鐐舵憰闂侀潧顭梽鍕枍閻樿褰掓偐瀹割喖鍓鹃梺杞扮閿曨亪寮婚敓鐘茬倞闁靛鍎虫禒楣冩⒑缂佹ɑ灏甸柛鐘崇墵瀵鏁愰崨鍌滃枛瀹曨偊宕熼銏㈠礈闂傚倷绀侀幉锟犳晪闂佺锕ゅ鈥愁嚕鐠囨祴妲堟俊顖炴敱椤秹姊洪崨濠庢畼闁稿鍋ら幃姗€宕奸悢铏诡啎闁诲海鏁搁…鍫濈摥缂傚倸鍊哥粔鎾晝閵堝缍栭煫鍥ㄦ礈绾惧吋淇婇婵愬殭妞ゅ孩鎸剧槐鎾存媴閸撴彃鍓遍柣搴ｇ懗閸パ咃紮濡炪倖鐗楅崺鍐绩娴犲鐓ユ繛鎴灻鈺伱归悩顐ｆ珔闁宠鍨块、娆撳传閸曘劌浜炬俊銈呭暙閸ㄦ繈鎮楅敐搴濇喚闁告艾顑呴…璺ㄦ崉閻氱鍚梺鍝ュ仜閻栫厧顫忓ú顏勪紶闁告洦鍓欑粣娑㈡⒑缁嬫鍎戦柛瀣ㄥ€濋獮鍐ㄎ旈崪浣规櫌闂佸憡娲﹂崗姗€骞忓ú顏呪拺闁煎鍊曢弸鎴炵節閵忊槄鑰块柛鈺傜洴瀵噣宕掑鍜冪床婵＄偑鍊栧ú鏍箠鎼淬劍鍊堕柨鏃堟暜閸嬫挾鎲撮崟顒傤槰闂佹悶鍔屽锟犳偘椤曗偓瀹曞爼顢楁担闀愮綍闂備礁澹婇崑渚€宕归悷閭﹀殨濞寸厧鐡ㄩ埛鎺戔攽閻樻煡顎楀ù婊勭矋缁绘盯寮堕幋婵愪紑閻庡灚婢橀敃顏堝箠閻愬搫唯鐟滄粌煤缁嬪簱鏀介柣妯肩帛濞懷勩亜閹存繃顥㈤柟顕嗙節閹垽宕妷褏妲囬梻浣稿閻撳牓宕戦崟顒佸弿闁搞儺鐏愰悷閭︾叆闁告侗鍙庨弳顓㈡⒑闁稓鈹掗柛鏂跨Ф閹广垹鈹戠€ｎ亜绐涘銈嗘礀閹冲秹宕Δ鍛拻濞达絽鎽滅粔鐑樸亜閵夛附灏扮紒缁樼洴閸┾偓妞ゆ帒瀚悡娆戔偓瑙勬礀濞层倝鍩㈤崼鐔翠簻闁靛繆妲呭▓婊呪偓瑙勬礃鐢剝淇婇崼鏇炲窛妞ゆ棁濮ら惁婊堟⒒閸屾艾鈧悂宕愰幖浣哥９闁绘垼濮ら崵鍕煕椤愶絾纾甸柍褜鍓ㄧ粻鎾崇暦婵傜唯妞ゆ棁濮ゅ▍鍫ユ⒒娴ｈ鍋犻柛搴灦瀹曟繂顓兼径濠勭厬闂婎偄娲﹀ú婊兾涢鐐寸厵妞ゆ牕妫楅懟顖炲礈閾忣偆绠鹃悗娑欘焽閻帒霉濠婂棙纭炬い顐㈢箳缁辨帒螣鐠囧樊鈧捇姊洪崨濠勨槈闁挎洏鍊濆鎶藉醇濠靛啯鏂€闂佺粯鍔欓·鍌炲吹鐎ｎ剛纾奸柣妯挎珪鐏忣參鏌ｉ敐澶樻闁瑰弶鎸冲畷鐔碱敃椤愩垺顔撻梻浣筋嚙鐎涒晝绮欓幒妤佹櫔濠电偛顕繛鈧紒鐘崇墪椤繘鎼归崷顓狅紲濠碘槅鍨伴幖顐ヮ杺闂傚倷绀侀幉锟犲箰閼姐倗鐭欓柟鎹愭硾閸ㄦ繄绱撴担楠ㄦ粓宕戦崨瀛樼厱闁硅埇鍔嶅▍鍥煕濮椻偓娴滆泛顫忓ú顏勬闁靛闄勯悵鏃堟⒑閸涘﹦鎳勯柛鏃€鐟╅悰顔锯偓锝庡枟閸嬫劙寮堕崼姘珔濠⒀勫劤閳规垿鎮欏顔兼闂佸憡顭嗛崶銊ヤ槐闂侀潧艌閺呮粓宕戦崒鐐寸厽闁哄倸鐏濋幃鎴︽煟閹惧鎳囬柡宀€鍠栭、娑㈠幢濡や礁娅ら梺纭呭蔼閸嬫劗妲愰幘瀛樺闁圭粯甯婃竟鏇㈡⒑鐠囨彃鍤辩紓宥呮瀹曟澘螖閸涱喖浜楀┑鐐村灦閸╁啴宕戦幘璇茬濠㈣泛锕ｆ竟鏇㈡⒒娓氣偓閳ь剛鍋涢懟顖涙櫠鐎电硶鍋撶憴鍕；闁告鍟块锝嗙鐎ｅ灚鏅ｉ梺缁樺姌閸╂牠骞夋导瀛樷拻濞达綀顫夐崑鐘绘煕鎼淬垺銇濈€规洘绮岄～婵堟崉閾忚鐓ｆ繝鐢靛█濞佳囶敄閸℃稒鍋傞柛鎰典簼閸犳劖绻濇繝鍌滃缂佲偓閸喐鍙忔俊顖涘绾箖鏌ｉ妶澶岀暫闁哄本鐩、鏇㈡晲閸℃妲遍梻浣芥〃缁€渚€顢栨径鎰摕鐎广儱鐗滃銊╂⒑閸涘﹥灏甸柛鐘查叄椤㈡岸鏁愰崱娆戠槇濠殿喗锕╅崢钘夆枍閵忋倖鈷戠紓浣广€為幋锝冧汗闁告劦鍠楅崵鈧梺鍓茬厛閸犳帡寮ㄦ禒瀣厽闁归偊鍘界紞鎴︽煟韫囥儵妾柕鍥у婵℃悂濡烽敂缁橈紗闁诲氦顫夊ú妯侯熆濮椻偓閿濈偛鈹戠€ｎ偄娈濈紒鍓у钃遍悗姘偢濮婄粯鎷呴崨濠傛殘缂備浇顕ч崐濠氬焵椤掍礁鍤柛锝忕秮楠炲啴鎮欓崹顐㈢／闂侀潧臎閸滃啰闂梺璇查缁犲秹宕曟潏鈹惧亾濮樼厧鏋ょ紒顕嗙秮瀵噣宕掑Δ鈧禍鐐箾閸繄浠㈡繛鍛耿閺屾稓鈧綆浜烽煬顒勬煟濞戝崬娅嶇€规洖鐖奸、妤呭焵椤掑倻妫憸鏃堝蓟濞戔懇鈧箓骞嬪┑鍥╀壕闂備胶绮粙鍫ュ疾濠婂嫮鈹嶅┑鐘叉处閸婇攱銇勮箛鎾愁仱闁稿鎹囧浠嬵敇閻愭鍞堕梻浣哄帶椤洟宕愬Δ鍛剹婵炲棙鎸婚悡娆撴煟閹寸倖鎴︽偂濞戙垺鐓曢悗锝庡亝瀹曞瞼鈧娲栫紞濠囥€侀弴銏犖ч柛娑变簼鐎氭彃鈹戦悩鎰佸晱闁哥姵鐗犻弫鍐晜閹冪亰濡炪倖鐗滈崑娑氱不椤栫偞鐓曟繛鎴濆船閺嬨倝鏌ｉ悢娲绘綈闁靛洤瀚板浠嬪Ω瑜夋慨鍥⒑閸濆嫭顥犻柛瀣ㄥ€曢～蹇涙惞鐟欏嫬鐝伴梺鑲┾拡閸撴盯顢欓崶鈺冪＝濞达綀娅ｇ敮娑㈡煕閵娿儲鍋ユ鐐插暣閹粓鎳為妷锔界彇闂備胶顭堥張顒€顫濋妸鈺佽摕鐟滄棃寮婚敐澶嬪亹闁绘垶菧閳ь剙鍟扮槐鎾愁吋閸涱垍褏鈧鍣崳锝呯暦閻撳簶鏀介柛鈩冪懅瀹曞搫鈹戦敍鍕杭闁稿﹥鐗犻獮鎰版倷椤掆偓閸ㄦ梹銇勯幘鍗炵仼闁肩缍婇弻锝夊閻樺啿鏆堥梺鎶芥敱鐢帡婀侀梺鎸庣箓閹冲繘宕悙鐑樼厱闁绘柨鎼禒婊堟煏閸℃ê绗掓い顐ｇ箞椤㈡顦抽柣銈勭窔閹鎲撮崟顒傤槰婵犵數鍋涢敃顏堝Υ娴ｇ硶鏋庨柟鎯у暱缁ㄣ儲绻濋姀锝呯厫缂佸鎸剧划鏃堫敆閸曨剛鍘梺鎼炲劘閸斿本鎱ㄥ鍡╂闁绘劖娼欏ù顔筋殽閻愬樊鍎旈柟顕呬邯閸┾偓妞ゆ帒瀚悿顕€鏌涢妷顔煎闁抽攱鍨块弻娑樷攽閸℃浼屽┑鈥冲级閹倿寮婚敐鍛傛棃鍩€椤掆偓铻炴繛鍡樻尭閻ら箖鏌涢锝嗙闁稿鏅濋埀顒€鍘滈崑鎾绘煃瑜滈崜鐔煎箚鐏炶В鏋庨煫鍥э攻閺傗偓闂備胶绮敋缁剧虎鍙冮妴鍌炲蓟閵夛妇鍘介梺瑙勫劤閻°劎绮堢€ｎ喗鐓涚€光偓鐎ｎ剙鍩岄柧浼欑秮閺屾稑鈹戦崱妤婁痪濠殿噯绲鹃崝鏇㈠煘閹达附鍊烽悗娑櫭崜褰掓⒑閸濄儱校妞ゃ劌锕悰顕€宕奸妷銉庘晠鏌ㄩ弬鍨挃闁伙箑鐗撳娲川婵犲倸顫呴梺鍝勫€搁崐鍦矉閹烘顫呴柕鍫濇閹锋椽姊洪棃鈺佺槣闁告瑥閰ｅ畷婵嗩煥閸涱垳锛滅紓鍌欑劍椤洨绮婚弽顬ュ酣宕惰闊剛鈧娲栭妶绋款嚕閹绢喗鍊烽柤纰卞墰瀹曞搫鈹戦敍鍕杭闁稿﹥鐗曡灋闁告劦鍠栭弸浣广亜閺囨浜鹃悗瑙勬礃閸ㄥ潡鐛Ο鍏煎珰闁肩⒈鍓涢弳浼存煟閻斿摜鐭婃い锕傛涧椤曪綁濡搁敂缁㈡祫闁诲函缍嗛崑鍡涘储娴犲鈷戠憸鐗堝笒娴滀即鏌涘Ο鍨汗鐎垫澘锕幊锟犲Χ閸モ晪绱查梻浣虹帛閻燂箓鎮烽妷銉冩椽鏁冮崒娑樹簵闂佸搫娲㈤崹娲偂韫囨挴鏀介柣鎰皺娴犮垽鏌涢弮鈧划鎾诲箖瑜版帒绠涢柛鎾茶兌閻﹀牓姊洪崫鍕拱闁烩晩鍨堕悰顕€骞掑Δ鈧粻濠氭煣韫囷絽浜柣褌绶氶弻锝嗘償閵堝孩缍堝┑鐐插级閻楃姵淇婇崼鏇炵濞达絽鎽滈悾娲⒑闂堟稓绠為柛濠冪墵楠炲棝鎮欓悜妯轰画濠电偛妫楃换鎰邦敂閳哄倻绠鹃柛顐犲灩娴犺鲸鎱ㄦ繝鍌ょ吋鐎规洘甯掗埢搴ㄥ箣閻橀潧搴婇梻鍌欑窔閳ь剛鍋涢懟顖涙櫠娴煎瓨鐓曢悗锝庡亞濞叉挳鏌熷畷鍥ф灈妞ゃ垺绋戦埥澶娾枎閹邦喖濞囬梻浣筋嚙鐎涒晝绮欓幒妤佹櫇闁宠桨璁查弸鏂棵归悩宸剱闁绘挾鍠栭弻鐔兼焽閿曗偓婢ь喚绱掗悪娆忓娴滄粓鏌曟径娑氬埌闁诲浚鍣ｉ弻宥堫檨闁告挻绻堥敐鐐村緞婵炴帒鎼…銊╁醇濠靛棗浜堕柣鐔哥矋濡啫鐣峰ú顏呭€烽柛婵嗗椤撴椽姊洪幐搴㈢５闁稿鎸剧槐鎺楁偐瀹曞洠濮囬梺闈涙搐鐎氫即鐛幒鎴悑闁搞儴鍩栬ⅵ闂傚倷绶氶埀顒傚仜閼活垱鏅舵繝姘厱闁靛鍔嶇涵鐐亜椤愩垻绠崇紒杈ㄥ笒铻ｉ悹鍥ф▕閳ь剚鎹囧娲川婵犲嫧妲堥梺鎸庢磸閸婃繂顕ｉ幎钘夐唶闁靛繈鍨婚敍婵囩箾閹剧澹樻繛灞傚€濆绋库槈閵忥紕鍘藉┑掳鍊愰崑鎾剁磼缂佹ê娴€规洘宀搁獮鎺懳旈埀顒勬煁閸ヮ剚鐓熼柡鍐ㄥ亞閻掔偓銇勬惔銏″暗缂佽鲸鎸荤粭鐔煎炊瑜忔禒顓炩攽閻愭彃绾ч柨鏇樺灲楠炲啫螣閼姐倗鎳濋梺閫炲苯澧い顐㈢箰鐓ゆい蹇撴媼濡啫鈹戦悙瀵告殬闁稿酣浜堕幃褔骞橀幇浣告闂佸湱绮敮鈺呮偂閵夆晜鐓曟い鎰剁悼缁犳﹢鏌涘鈧禍璺侯潖閾忚鍏滈柛娑卞枛濞懷囨⒒閸屾艾顏╅悗姘嵆瀹曞搫鈽夐姀鐘殿吅闂佺粯鍔︽禍娆戣姳婵犳碍鈷戦悷娆忓椤ユ劙鏌￠崨顔炬创闁糕斁鍋撳銈嗗笂閻掞妇绮堥崘顏嗙＜闁稿本绋戠粭鎺撱亜椤撴粌濮傜€规洖銈搁幃銏ゅ传閸曨偆顔掓繝鐢靛Х閺佹悂宕戦悩鍏哥剨妞ゅ繐鐗滈弫瀣喐閺冨牆绠栨慨妞诲亾闁轰焦鎹囬幃鈺佺暦閸パ冪闂傚倷绀侀幉鈩冪瑹濡ゅ懎鍌ㄥΔ锝呭暙閺勩儵鏌ㄥ┑鍡樼闁稿鎸搁埢鎾诲垂椤旂晫浜梻浣虹帛閻楁洟濡堕幖浣瑰仒妞ゆ棃鏁崑鎾绘晲鎼粹剝鐏堢紓渚囧亜缁夊綊寮诲鍫闂佸憡鎸鹃崰搴敋閿濆鏁嗛柛鏇ㄥ亞閸?"
        return "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欑粣娑㈡⒑閸濄儱校闁圭澧介崚鎺旂磼濡浜濋梺鍛婂姀閺呮繈宕㈡禒瀣拺闂侇偅绋戝畵鍡樼箾娴ｅ啿瀚▍鐘炽亜閺嶎偄浠﹂柣鎾跺枑缁绘繈妫冨☉娆忣槱缂備讲鍋撻悗锝庡亝閸欏繐鈹戦悩鍙夊櫤妞ゅ繒濮风槐鎺楊敊閻ｅ本鍣ч梺瀹狀嚙闁帮綁鐛崱姘兼Щ婵犮垼顫夐敋闁宠鍨块幃娆撴嚑椤掍焦鍠栫紓鍌欑贰閸犳碍鎱ㄩ悽鐢电焿鐎广儱顦介弫鍌炴煕閺囥垺娑ф繛鍫涘姂閺岋綁鎮╅崣澶婎槱缂備椒鐒﹀娆忓祫闂佸壊鍋侀崕鏌ユ偂韫囨稓鍙撻柛銉ｅ妽缁€鈧柛鐔告倐濮婃椽宕ㄦ繝鍐ｆ嫻闂佸湱顭堥崯鍧楋綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愬宀婃澓濠电姷鏁搁崑娑㈡偤閵娧冨灊鐎广儱顦伴崑瀣煛閸モ晛浠滅紒渚囧亰濮婄粯鎷呯粙娆炬闂佺顑勭欢姘暦瑜版帗鍤掗柕鍫濇媼濡粓姊洪懞銉冾亪藟閵忥絻浜归柟鐑樻尰濞呮粓姊虹化鏇炲⒉妞ゃ劌鐗忕划濠囨煥鐎ｎ剛顔曢柣搴㈢⊕椤洭鎯岄幒鏃傜＜闁绘ê纾晶顏呫亜椤愩垻绠婚柟鐓庣秺瀹曠兘顢橀悩闈涘箚闂備浇宕垫慨鍨娴犲绀夐幖娣灩椤曢亶鏌涢妷顔煎闁抽攱鍨圭槐鎺斺偓锝庡亽閸庛儵鏌涙惔銏犵伌闁哄本绋撻埀顒婄祷閸斿矂鍩€椤掍胶绠為柣娑卞櫍瀹曟﹢顢欓懞銉︻仧闂備胶绮摫鐟滄澘鍟悾鐢稿幢濞戞瑢鎷虹紓鍌欑劍钃遍柍閿嬪笧缁辨帞绱掑Ο鑲╃暭闂佸ジ缂氭ご鍝ユ崲濠靛棭娼╂い鎾寸⊕鐎氬ジ姊洪懡銈呮瀾闁荤喆鍎抽埀顒佸嚬閸樻儳鈻庨姀銈呯闁圭儤绻勯崬鐢告偡濠婂啰效闁哄苯锕弫鎰緞鐏炵晫銈﹂梻浣告啞閸旓箓宕板Δ鍛惞闁告劦鍠楅悡鍐煕濠靛棗顏╅柡鍡欏枛閺屻劌鈽夊▎鎴犵厜濠殿喖锕ㄥ▍锝囨閹烘埈娼ㄩ柛鈩冪懃婵吋绻濋悽闈涗粶闁瑰啿绻愮叅闁哄稁鍘介崑鈺冣偓鐟板婢瑰棝寮抽崱娑欑厱闁哄洢鍔屾晶浼存煕濡粯鍊愰柟顔筋殜瀹曟寰勬繝浣割棜闂備浇顕ч崙鐣岀礊閸℃稑绀堟繛鎴炲閸欑儤绻濆閿嬫緲閳ь剚顨嗛幈銊╂倻閽樺锛涢梺缁樺姇閻忔岸寮冲鍫熺叆闁绘柨鎼暩閻庤鎸风欢姘跺箖濡ゅ懏鏅查幖瀛樼箘閹稿姊洪崫鍕靛剰闂佸府缍侀幃锟狀敃閿曗偓閻愬﹦鎲搁弮鍫晛婵°倕鎳忛悡鏇㈡煏婵犲繐顩紒鐘靛仦閹便劍绻濋崒銈囧悑閻庤娲樼敮鎺楀煝鎼淬劌绠ｆい鎾跺晿濠婂牊鈷掑ù锝呮啞鐠愶繝鏌嶅畡鎵ⅵ鐎规洘鍨剁换婵嬪炊瑜忛悾鐐節閵忥絾纭炬い鎴濇喘濮婁粙宕熼鐘碉紲闁诲函缍嗛崢鐣屾兜閸洘鐓熸繛鎴炵墪閸旓附鎱ㄦ繝鍛仩闁瑰弶鎸冲畷鐔碱敃閵堝孩袨濠碉紕鍋戦崐鏍р枖閿曞倸宸濇い鏍ㄧ矊缁犲灚绻濆閿嬫緲閳ь剚鍔欏畷鎴﹀箻缂佹鍘撻柣鐔哥懃鐎氼剟鎮橀幘顔界厵妞ゆ棁顫夊▍濠囨煟閹垮啫浜版い銏★耿閸╁嫰宕橀…鎴炵秿闂傚倸鍊搁崐鐑芥嚄閸撲礁鍨濇い鏍嚤濞戞瑦濯寸紒顖涙礃閻庢椽姊洪幐搴ｇ畵婵炲眰鍊濊棢婵鍩栭悡鏇㈢叓閸ャ劎鈯曢柨娑氬枔缁辨帞鎷犻崣澶樻！闂侀潧娲ょ€氭澘顕ｆ禒瀣╃憸蹇涙偂閳ь剟姊哄Ч鍥х労闁搞劎澧楅弲鑸垫償閿濆棭娼熼梺鍦亾閸撴岸宕ョ€ｎ€㈠綊鏁愭径瀣彸婵犮垼顫夊ú鐔奉潖婵犳艾纾兼慨姗嗗厴閸嬫捇骞栨担鍝ワ紮闂佸綊妫跨粈浣哄閸︻厸鍋撻悷鏉款仾闁革絿顥愰妵鎰板箳閹寸姴鈧偛顪冮妶鍡楃瑨妞わ缚鍗冲鏌ヮ敂閸喎浠┑鐘诧工閸熸挳宕ｉ崟顖涚厪闁糕剝顨呴弳锝呪攽閿涘嫬鍘撮柛鈹惧墲閹峰懏绗熼姘珝濠电姷鏁搁崑鐘诲箵椤忓棗绶ら柛褎顨呯粻鐘绘煙閹规劦鍤欓柣鎺戠仛閵囧嫰骞掗幋婵囨闂佺粯鎸婚崝娆撳蓟閻斿摜鐟归柛顭戝枛椤牓鏌ф导娆戠М闁哄本鐩垾锕傚箣濠靛洨浜鹃梻浣告啞閿曗晠宕戞繝鍌ゆ綎闁惧繐婀遍惌娆愮箾閸℃ê鍔ら柛鎾存緲椤啴濡堕崱妤冧淮濡炪倧绠撳褔顢氶敐鍡欑瘈婵﹩鍘藉▍婊堟⒑閸涘﹦鈽夐柛濠傤煼瀹曚即寮借閺嗭妇鎲搁悧鍫濅刊闁轰礁锕弻锝夊箛闂堟稑鈷掗梺鎼炲€曠€氭澘顫忔繝姘＜婵炲棙鍩堝Σ顕€姊洪崷顓涙嫛闁稿瀚悘瀣煟鎼淬劍娑ч柟鑺ョ矋缁嬪顓兼径瀣幍闂佺顫夐崝锕傚吹濞嗘挻鐓㈤柛鎰典簻閺嬫盯鏌＄仦鐐鐎规洜鍘ч埞鎴﹀炊瑜忛悰鈺呮⒒娴ｈ銇熼柛妯圭矙閹兘鍩￠崨顓犵暫閻熸粎澧楃敮鎺旂不閹烘鐓欓柣鎴灻悘銉︺亜椤掆偓濡稓妲愰幘瀵哥懝闁搞儜鍕壕闂備浇妗ㄧ粈渚€骞楀鍏撅綁骞囬弶璺啋闁荤姴娲╃亸娆撴晬濠婂啠鏀芥い鏃傚嵆閹达附鍎婇柣鎴ｆ椤懘鏌ㄥ☉妯侯伀妞ゆ梹娲熼幃妤呮偡閺夋妫岄梺鍝ュУ閻楁洟顢氶敐澶樻晩闂佹鍨版禍鐐箾閸繄浠㈤柡瀣堕檮閵囧嫰寮撮崱妤佹悙闁绘挴鈧剚鐔嗛柤鎼佹涧婵洦銇勯銏″殗闁哄矉绲借灒婵炶尪顕ч弲閬嶆⒑閸濄儱鏋庢い鎴濇閹广垹鈹戦崱鈺佹闂備礁鐏濋鍡欐閺屻儲鐓冪憸婊堝礈濮樿泛绀夋繛鍡楃箳閺嗭箓鏌熸潏鍓х暠缂佺姾宕电槐鎾存媴鐠囷紕鍔烽梺鍛婎焽閺佸骞冨Δ鍛仭闁哄顑欐导鍐⒑缁嬫鍎忛柨鏇ㄤ簻閻ｇ兘寮撮敍鍕澑濠电偞鍨堕…鍥€侀崨瀛樷拻濞撴艾娲ゆ晶顔剧磼婢跺本鏆柟顕嗙節閹垽宕楅懖鈺佸箥闂佸搫顦悧鍡樻櫠娴犲绀嗛柟娈垮枟閸嬫牗鎱ㄥΟ鍨厫闁抽攱鍨块弻鐔煎箚閺夊晝鎾绘煛娓氣偓娴滃爼骞冩禒瀣垫晬婵炴垶蓱鐠囩偛鈹戦悩顐壕婵炴挻鍩冮崑鎾存叏婵犲啯銇濇鐐村姈閹棃鏁愰崶鈺傛闂備浇顕х€涒晠宕欒ぐ鎺戝瀭闁割偅娲忛埀顑跨铻栭柛娑卞枛娴滄粓姊虹粙璺ㄧ闁稿鍔欏畷銏＄鐎ｎ偀鎷洪梺闈╁瘜閸樺ジ宕濈€ｎ喗鐓曢柕濞у嫭姣堥梺绯曟櫆閻╊垰顕ｉ鈧畷鎺戭煥閸滃啰搴婇梻浣告惈椤︻垶鎮ч崟顖氱鐎光偓閳ь剛鍒掗鈽嗘Ь缂備浇椴哥敮妤€顭囪箛娑樜╅柕澹懏鍣梻浣稿綖缁鳖喚绱炴笟鈧璇测槈濡攱鏂€闂佺硶鍓濋〃蹇斿鐏炶В鏀介柣鎰絻閹垹鈧厜鍋撶紒瀣儥濞兼牜绱撴担鑲℃垶鍒婄€靛摜纾兼繛鎴烇供閸庡繑绻涢崼鐔峰婵﹥妞藉畷顐﹀Ψ閵夛妇褰欓梻浣侯焾椤戝懘鏁冮妶澶嬪仼闁绘垼濮ら崑鍕棯閹峰矂鍝洪柡鍜冪秮濮婅櫣绱掑Ο蹇ｄ邯閹ê顫濈拋鍦◤閻庡厜鍋撻柛鏇ㄥ厴閹峰姊虹粙鎸庢拱闁荤啙鍥佸洭鏁冮崒娑氬幍闁荤姴娉ч崨顖滄闁诲氦顫夊ú妯兼崲閸℃瑧涓嶆繛鎴炃氬Σ鍫熶繆椤栨艾鎮戦柣鎿勭稻缁绘繈鎮介棃娴躲垽鏌ㄩ弴妯衡偓婵嬪箖瑜庣换婵嬪炊瑜忛敍娑㈡⒑缂佹ɑ鐓ラ柛姘儔閹繝鎮㈤崗鑲╁幍闁哄鐗嗘晶浠嬪礆閹殿喗鍋栨慨妯垮煐閳锋垿鏌熼幆鏉啃撻柡渚€浜堕弻娑㈠Ω閵夛箑浠撮悗娈垮枛椤兘骞冮姀銈嗘優闁革富鍘鹃崢顖炴⒒娴ｇ顥忛柣鎾崇墦瀹曟娊顢氶埀顒€鐣峰┑鍥х窞鐎光偓閳ь剛澹曢挊澹濆綊鏁愰崱妤冪シ婵炲瓨绮撶粻鏍ь潖濞差亝鐒婚柣鎰蔼鐎氭澘顭胯閻°劑骞堥妸锔剧瘈闁告侗鍣禒鈺冪磽娓氬洤鏋熼柣鐔叉櫅閻ｇ兘鎮╃拠鑼紜闂佺绻愰幊鎰版儗濡ゅ啰纾介柛灞捐壘閳ь剚鎮傚畷鎰板传閵壯呯厠闂佸湱铏庨崰妤呭疾濠靛洢浜滈煫鍥ㄦ尵婢с垻鈧鎸风欢姘跺蓟濞戙垹绠涢梻鍫熺⊕閻忓秹姊虹粙鍖″姛闁稿繑锕㈠濠氭晲婢跺娼婇梺闈涚箚閸撴繂袙閸曨垱鈷戦柟绋挎捣閳洜绱掗鑲╃劯闁糕晝鍋ら獮瀣晝閳ь剟鎮￠敓鐘崇厱闁斥晛鍠氬▓妯好归悩铏稇妞ゎ亜鍟存俊鍫曞幢濡灝浜栭梻浣告啞閸旀牠宕曢崘娴嬫灁闁靛ň鏅滈埛鎴︽煕閹剧懓鐨洪柛妯荤洴閺屾盯鎮╅崘鍙夎癁閻庢鍠撻崝鎴﹀箠閻愬搫唯闁挎繂瀚惄搴ㄦ⒒娴ｅ憡鎯堥柛鐕佸亰瀹曟劖绻濆顒傤啈闂佺鏈粙鎾剁不妤ｅ啯鐓曟い鎰╁€曢弸鎴︽煃闁垮濮囬懣鎰版煕閵夋垵绉烽崥顐㈩渻閵堝啫鐏繛鑼枛瀵偊骞囬鐔峰妳闂侀潧绻堥崹鍝勨枔閸撗呯＝闁稿本鑹鹃埀顒勵棑缁牊绗熼埀顒€鐣烽幇鏉夸紶闁靛／鍛帬闁荤喐绮庢晶妤冩暜閹烘梻涓嶉柡宥冨妿缁犻箖鏌涢埄鍐炬當濠殿喗鎸抽獮鏍箹椤撶姴甯ラ梺杞扮鐎氫即骞冭ぐ鎺戠畳闁圭儤鍨甸‖瀣攽閻愬樊妲告繛灏栤偓鎰佹綎濠电姵鑹剧壕鍏兼叏濡灝浜归柛娆愭礋濮婅櫣绮欏▎鎯у壈闁诲孩鍑归崜娑㈠矗閸涘瓨鈷戦柟绋垮缁€鈧梺绋匡工閹芥粎鍒掔紒妯侯嚤閻庢稒顭囬崢鐢告⒒閸屾艾鈧悂顢氶銏犵鐎广儱顦伴悡鏇㈡煏閸繃濯奸柛搴㈠灴閺岀喖宕ｆ径瀣偓鎰版煙椤斻劌娲ら柋鍥ㄧ節闂堟稓澧㈤柟铏墵濮婄粯鎷呴搹鐟扮闂佺懓鎲￠幃鍌氱暦椤栫偛绠绘い鏃囧閹芥洟姊洪幐搴㈢５闁稿鎹囬幗鍫曟晲閸涱偀鍋撻幒鎴僵闁绘挸娴锋禒顓㈡⒑瀹曞洨甯涢柟鍛婃倐閸╃偤骞嬮敃鈧悡锟犳煕閳╁喚娈樺ù鐘冲哺濮婅櫣绮欏▎鎯у壉闂佺懓鎽滅划顖滅矚鏉堛劎绡€闁搞儺鐏涜閺屾盯濡烽鍙ヨ檸闂侀潧顦弲婊堟偂閺囥垺鍊甸柨婵嗛婢ь喖霉閻樿鎲鹃柡宀€鍠栭、娆撳箚瑜嶉獮瀣⒑缁洘鏉归柛鎾寸箞楠炲繘宕ㄧ€涙ê鈧粯淇婇娑欍仧闁哥喎楠搁埞鎴︽偐濞堟寧姣屽┑鈩冨絻閹虫ê鐣疯ぐ鎺撶劶鐎广儱瀛╅弲鐐测攽閻愬弶顥滅紒顕€绠栭弫鎰板幢閹邦兛绨奸梻浣告啞閸斿繘寮笟鈧獮蹇撁洪鍛嫼闂佸憡绋戦敃锕傚煡婢舵劖鐓ラ柡鍥埀顒佺箞楠炲啫顫滈埀顒勫春閿熺姴宸濇い鏃€鍎抽獮宥夋⒒娴ｇ懓鍔ゆ繛瀛樺哺瀹曟垿宕ㄩ鐘虫閻庡厜鍋撻柛鏇ㄥ墰閸橀亶姊洪崘鍙夋儓闁哥噥鍋呯粋鎺撴綇椤垶顔旈梺缁樺姇濡﹪宕曢弮鍫熺厸濞达絿顭堥埀顒€娼￠獮鎰節閸愩劎绐為梺绯曞墲閵囩偞绔熼弴銏♀拺缂備焦锚閻忓崬鈹戦鍝勨偓婵嗙暦閹版澘鍨傛い鎰╁€楅鏇㈡⒑閻熼偊鍤熼柛搴㈠姈缁傛帡鎮欓鍙ョ盎闂婎偄娲﹂幐濠毸夊鍫熺厸閻庯綆浜炴晶銏ゆ煃瑜滈崜娆戠不瀹ュ纾块柛妤冨€ｅ☉妯锋婵﹩鍓欒ⅲ闂備線鈧偛鑻晶瀛樻叏婵犲啯銇濈€规洘锕㈤幊鐘活敆娓氬洤鏁婚梻鍌欒兌椤牓顢栭崱娑樼闁搞儺鍓欓拑鐔哥箾閹存瑥鐏╃紒鐘崇洴閺岋綁濮€閵堝棙閿柣銏╁灛閸庨潧顫忓ú顏勫窛濠电姴鍟伴崣鍡楊渻閵堝繒鐣冲ù婊庡墮鍗遍柟鐗堟緲缁犲鎮楀☉娅亪顢撻幘鍓佺＝濞达絽澹婇崕蹇曠磼閵娾晙鎲剧€规洘鍨块獮妯兼嫚闊厾鐐婇梻渚€娼ч敍蹇涘川椤栨艾鑴梻鍌氬€风粈浣革耿闁秵鎯為幖娣妼闂傤垱銇勯弽銊х煂缂佲偓婵犲洦鐓涚€广儱楠搁獮妤呮煟閹惧磭绠婚柣鎿冨亰瀹曞爼濡搁敂缁㈡К闂佸摜鍠愰幃鍌氼潖濞差亜浼犻柛鏇ㄥ墻濡偛鈹戦埥鍡椾簼缂佽鐗嗛锝囨嫚瀹割喖鎮戦梺鍓插亽閸嬪懘顢撻崶顒佲拻濞达絽鎲￠崯鐐烘煙閹间胶鐣虹€规洑鍗冲浠嬵敇閻樿尙銈﹂梻浣告啞閸旓箓宕伴弽顓熺叆闁靛牆妫旂换鍡涙煏閸繂鈧憡绂嶆ィ鍐┾拺缂備焦锚缁楁帡鏌ｈ箛鏂垮摵濠碉紕鏁诲畷鐔碱敍濮橀硸鍞洪梻浣烘嚀閻°劎鎹㈠鍡欘浄濡わ絽鍟埛鎴︽煙閹澘袚闁轰線浜堕弻娑㈠Ω閵夛箑浠村Δ鐘靛仜閸燁偊鎮鹃敓鐘茬闁惧浚鍋嗛埀顒€顭峰Λ鍛搭敃閵忊€愁槱闂佺懓鐨烽弲婊呯矉閹烘挾闄勯柛娑樑堥幏娲⒑閸涘﹦鈽夐柨鏇樺劦閹繝鎮㈤崗鑲╁幈婵犵數濮撮崯鎵不閻愮鍋撳▓鍨灕妞ゆ泦鍥х叀濠㈣埖鍔曢～鍛存煃閵夈儱甯犵紒銊ヮ煼濮婂宕掑▎鎴М闂佽绻戠换鍫ャ€侀弽顓炲窛妞ゆ梻铏庡ù鍕⒑閸︻叀妾搁柛鐘愁殜瀹曟劙鎮介崨濠備画濠电偛妫楃换鎰邦敂椤忓嫷鐔嗛悹鍝勬惈椤忣參鏌＄仦鍓ф创妤犵偞顭囬幑鍕倻濡皷鍋撻悙顒傜闁挎繂鎳忛幖鎰版煥閺囥劋閭柣娑卞櫍瀵粙濡搁敃鈧鎾绘煟閻斿摜鎳冮悗姘煎弮閹敻寮撮姀鈾€鎷洪梺鐓庮潟閸婃洘鐗庡┑鐐茬摠缁牏鍒掑▎蹇曟殾婵犻潧娲﹂崕鐔兼煏婵犲繒鐣卞ù鐘层偢濮婅櫣绱掑Ο鍝勑曢梺绋跨箲缁嬫捇骞戦姀銈呭耿婵炴垶鐟ч崢浠嬫⒑鐟欏嫭绶查柛姘ｅ亾缂備降鍔岄…鐑藉蓟瀹ュ牜妾ㄩ梺鍛婃尰瀹€鎼佸箖瑜旈幃鈺呮嚑椤掍焦顔曟繝鐢靛█濞佳囶敄閸℃稑鐤炬繝闈涱儐閻撴洟鎮橀悙闈涗壕闁汇劍鍨堕妵鍕晜鐠囨彃绠归梺瀹狀潐閸ㄥ潡骞冨▎鎾崇骇闁瑰濮抽幋鐑芥⒒娴ｈ鍋犻柛鏂胯嫰閿曘垺娼忛埡浣哥亰闂佸壊鍋侀崕閬嶇嵁閵忊€茬箚闁绘劕鐡ㄧ粈鈧紓鍌氱Т閿曨亪鐛崘顔肩労闁告劏鏅涢崝鍛存⒑閹稿海绠撴俊顐ｇ懇瀹曚即寮介鐔叉嫽婵炶揪缍€濞咃絿鏁☉銏＄厵闁归棿鑳堕悾铏光偓瑙勬磻閸楁娊鐛崶顒夋晣闁绘﹩鍋呴弫闈涒攽閻樺灚鏆╁┑顔芥綑鐓ら柕鍫濇噺缁绢垶姊婚崒娆戭槮闁规祴鈧秮娲晝閸屾艾鍋嶉梺绋跨箻濡法鎹㈤崱妞曞綊鎮╁顔煎壉闂佺锕﹂弫濠氬箖瀹勬壋鏋庨煫鍥ㄦ惄娴犲墽绱撴担鎻掍壕闂侀€炲苯澧存慨濠冩そ瀹曨偊宕熼鐐╂嫛闂備礁鎲￠幐楣冨窗閺嶃劋绻嗛柟缁㈠枛缁€鍐┿亜閺傛寧顫嶉柕濞炬櫆閻撳啴鏌涘┑鍡楊仼闁逞屽墯閹倿宕洪埀顒併亜閹烘垵鈧悂宕㈤幘顔界厸鐎光偓閳ь剟宕伴幘璇茬獥濠电姴娲ょ涵鈧梺缁樺姌鐏忔瑩顢欓幋锔解拻濞达綁顥撴稉鑼磽瀹ュ嫮绐旈挊鐔兼煙閹规劕鐓愭い顐ｆ礋閺岀喖骞嗚閹界姴鈹戦娑欏唉闁哄被鍊濋獮渚€骞掗幋婵嗩潙闂備線鈧偛鑻晶顕€鏌涢悢绋款棆婵″弶鍔欓獮鎺懳旀繝鍐╂珦闂備椒绱徊浠嬪嫉椤掑嫬闂憸鏂款潖閻戞ê顕辨繛鍡樺灦閸嬔囨⒑缁嬭法绠查拑鍗炃庨崶褝韬鐐寸墬閹峰懐鎲撮崟顒傚絾闂傚倷绀侀幉锟犲箰閸℃稑宸濇い鏇炴噺缂嶅姊婚崒姘偓鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偛顦甸弫鎾绘偐閼碱剦妲烽梻濠庡亜濞诧妇绮欓幋锔藉仾闁绘劦鍓涚弧鈧梻鍌氱墛娓氭鎮為幆顬＄懓顭ㄩ崘顏喰ㄩ梺鍝勬湰濞叉鎹㈠☉銏″€锋い鎺嶈兌瑜板棝姊绘担鐟扳枙闁衡偓闁秴鍨傞柛褎顨呯粻鏍喐閻楀牆绗掗柣鎰躬閺屾洘绻涜閸燁偆绱掗埡鍌欑箚闁绘劦浜滈埀顒佹礈閳ь剚绋堥弲鐘诲Υ閸愨晝绡€闁搞儜鍡樻啺婵犵數鍋為崹鍫曗€﹂崒鐐村亜闁稿繒鍘у▓銉╂⒑闂堟稓澧曟繛灞傚姂瀹曘垹顭ㄩ崼鐔哄幗闁瑰吋鐣崐銈咁焽閹邦厾绠鹃柛娆忣檧閼拌法鈧娲栫紞濠傜暦缁嬭鏃堝礃閵娧佸亰濠电姷顣藉Σ鍛村垂閻㈢纾婚柟閭﹀枛椤ユ岸鏌涜箛娑欙紵缂佽妫欓妵鍕冀閵娧呯厐闁汇埄鍨伴悥濂稿箖娴犲鏁嶆繛鎴ｉ哺閻や線姊洪崫鍕効缂傚秳绶氶獮鍐閵堝懍绱堕梺闈涳紡閸涱厼绗掔紓鍌氬€搁崐椋庢閿熺姴绐楁俊銈呮噹缁犱即鏌熼梻瀵稿妽闁稿鏅濋埀顒傛嚀鐎氫即宕戞繝鍥ㄥ亗闁靛鏅滈悡鏇熴亜閹扳晛鈧洟寮告惔鈭剁懓顭ㄩ崟顓犵厜濠殿喖锕ㄥ▍锝囨閹烘嚦鐔烘嫚閼碱剦鏆℃繝寰锋澘鈧鎱ㄩ悽绋跨畺闁稿瞼鍋涚粻鏍ㄤ繆閵堝懏濯奸柡浣告喘閺屾洝绠涙繝鍐锯偓鍡涙煙闁垮銇濋柡宀嬬秮閹晠宕ｆ径宀婃Ш闂備線鈧偛鑻晶顔剧棯缂併垹骞楅悗闈涖偢瀹曞爼顢楁担鍙夊闂佽崵濮村ú鈺冧焊濞嗘垹涓嶉柡灞诲劜閻撶喖鏌嶉崫鍕跺伐闁诲骏闄勯〃銉╂倷閹绘帗娈绘繝娈垮枓閸嬫捇姊洪棃娑氬婵☆偅顨嗙粋宥呂旈崨顔惧幍闂佺厧婀辨晶妤勩亹瑜忕槐鎾愁吋閸涱噮妫為柛妤勯哺閵囧嫰寮介顫勃闂佹娊鏀辩敮鎺楁箒闂佹寧绻傞悧濠囶敂閻樼粯鍋ㄦい鏍ㄧ〒濞叉挳鏌″畝鈧崰鎾跺垝濞嗘挸绠伴幖娣灩閺嬫垿姊绘笟鈧埀顒傚仜閼活垱鏅堕鈧弻锝堢疀閺冣偓閻ㄦ垿鏌℃笟鍥ф珝闁轰焦鎹囬幃鈺呭矗婢跺瑩姘舵⒒娓氣偓閳ь剛鍋涢懟顖涙櫠椤栫偞鐓忛柛銉戝喚浼冨Δ鐘靛仦鐢帡顢樻總绋块唶婵犻潧妫楅懙鎰攽閻樺灚鏆╅柛瀣仩閵囨劙宕橀钘変槐闂侀潧艌閺呮稓绮婚悙鐑樼厪濠电姴绻愰々顒傜磼閳锯偓閸嬫捇姊绘担鍛婂暈闁告柨绻樺顒勫磼濞戞凹娴勯梺闈涚箳婵參寮ㄦ禒瀣厓闁芥ê顦伴ˉ婊兠瑰鍕煉闁哄本鐩幃銈嗘媴闂€鎰瀳闂備胶纭堕弬鍌炲磿閹绘帩鍤楅柛鏇ㄥ墰缁♀偓闁瑰吋鐣崹褰掑礂婵犲啩绻嗛柣鎰典簻閳ь剚鐗滈弫顕€骞掑婵嗘喘瀵爼宕崘鈺佹诞鐎规洖鐖奸、妤佹媴閸欏顏洪梻鍌欒兌椤牓寮甸鍕仭闁靛ň鏅涚粈鍌溾偓鍏夊亾闁逞屽墰濡叉劙骞掑Δ濠冩櫔闂佸憡渚楅崢鐐閹间焦鈷戦梻鍫熺⊕椤ユ粓鏌涢悢鍛婄稇闁伙絿鍏樻俊鎼佸煛婵犲啯娅栨繝鐢靛仦閸ㄥ爼鏁嬬紓浣靛妸閸庨潧顫忕紒妯诲闁告稑锕ㄧ涵鈧梻浣侯焾缁ㄦ椽宕愬┑鍡╁殨濠电姵鑹炬儫闂佸疇妗ㄧ粈渚€鎮楅鐐╂斀闁绘绮☉褎淇婇銏㈢劯鐎殿喓鍔嶇粋鎺斺偓锝庡亞閸樿棄鈹戦埥鍡楃仴婵炲拑缍侀弫宥咁吋閸℃劒绨婚梺鎸庣箓濡盯宕ｉ埀顒勬⒑閸濆嫭婀扮紒瀣崌閸┾偓妞ゆ帒锕﹂崚鏉款熆瑜嶅ù宄邦嚕瑜旈崺鈧い鎺戝閳锋垿鏌涘┑鍡楊伀闁诲繘浜堕弻娑㈡偐閸愭彃顫掑Δ鐘靛仜缁绘ê鐣烽妸鈺佺骇闁瑰濯Σ浼存⒒娴ｇ鏆遍柟纰卞亰瀹曨垶顢曢埗鈺傤潔閻熸粌瀛╃粚杈ㄧ節閸ャ劌鈧攱銇勮箛鎾愁仱闁稿鎹囨俊鑸靛緞婵犲嫸绱遍梻浣告啞濞诧箓宕㈡ィ鍐╁剹闁瑰墽绮悡鐔兼煟閺冨倸甯跺ù婊呭缁绘盯宕楅懖鈺侇潷缂備胶绮粙鎴︻敊韫囨侗鏁婇柤濮愬€楀▔鍧楁⒒娴ｅ憡璐℃い銏狅躬瀹曟椽寮介鐐嶏箓鏌涢弴銊ョ仩缂佺姷绮妵鍕冀閵娿劌顥濋梺鍐插槻椤︻垶鈥旈崘顔嘉ч柛娑卞弾閸斿顪冮妶鍐ㄥ闁挎洏鍊濋敐鐐剁疀閹句焦妞介、鏃堝礋椤撗冩櫍闂傚倷鑳剁划顖炲礉閺嶎兙浜归柛鎰靛枓閳ь剚鐗滈埀顒婄秵閸嬪棛寮ч埀顒勬⒑閸愯尙娈遍柛瀣崌閺屾盯寮撮悙鍏哥驳闂佷紮缍€閸嬫劗妲愰幘瀵哥懝闁搞儜鍕邯婵＄偑鍊栭崹鐢稿箠濮椻偓閵嗕礁顫滈埀顒€鐣峰Δ鍛亗閹艰揪绲块悰顔尖攽閻樺灚鏆╁┑顔碱嚟閳ь剚鍑归崳锝咁嚕閾忣偄顕遍悗娑欘焽閸樹粙姊虹紒妯荤叆闁硅姤绮撻幆灞剧節閸愶缚绨婚梺鎸庢礀閸婄懓鈽夎閵囧嫰寮撮鍡櫺滄繝纰樺墲閹倿宕洪敓鐘茬＜婵﹩鍘鹃弸鈧梻鍌氬€风欢姘焽瑜旂瘬闁逞屽墰缁辨帡鎳犵捄杞版睏闂佸ジ缂氭ご鍝ユ崲濠靛棭娼╂い鎾寸⊕鐎氬ジ姊绘担鍛婂暈缂佽鍊婚埀顒佸嚬閸撶喎顕ｉ崘娴嬫瀻闁规儳顕崢杈ㄧ節閻㈤潧孝閻庢凹鍙冨畷鐢稿焵椤掑嫭鈷戦悗鍦閸ゆ瑧绱掓径灞惧殌妞ゆ洩缍侀獮姗€顢欓挊澶夋睏闂備焦鐪归崹濠氥€傞鐐潟闁规儼濮ら埛鎺懨归敐鍕劅闁绘帡绠栭弻锟犲醇椤愩垹顫紓渚囧枟閻熲晠鐛€ｎ喗鏅濋柍褜鍓氱€靛ジ鎮╁畷鍥╊啎閻庣懓澹婇崰鏇犺姳婵傚憡鐓熼柟鎯ь嚟濞叉挳鏌熼鏂よ€块柟顔界懇楠炴捇骞掗崱妯虹槺闂傚倷鐒﹂崜姘跺垂閸楃伝娲偄閻撳氦鎽曢梺缁樻⒒閳峰牓寮鍡欑闁瑰鍋熼幊鎰繆椤愩垹鏆ｆ慨濠冩そ楠炴牠鎮欓幓鎺濇綆缂傚倷鑳舵慨鐢告偋閻樿崵宓侀柡宥庡厵娴滃綊鏌熼悜妯肩畺闁哄懏绻堝娲箰鎼达絿鐣靛┑鐐额嚋缁犳帡路閸涘瓨鈷掗柛灞捐壘閳ь剚鎮傚畷鎰板箹娴ｅ摜锛欓梺缁樺灱婵倝宕愰崸妤佺叆闁哄啫鐗婇弳婊堟煕鐎ｎ偅灏电紒顕呭幖閳藉螣閸濆嫮顔掑┑掳鍊х粻鎺戔枖閺囥垺鍋柍褜鍓欓埞鎴︽倷閺夋垹浠搁梺鎸庡哺閺岋絾鎯旈鐓庣缂備胶绮粙鎾诲焵椤掑倹鏆╂い顓炵墕閻☆厽淇婇悙顏勨偓鏍垂閻㈢绠犳俊顖欒閸ゆ洟鏌涘☉姗堝姛闁荤喎缍婇弻宥堫檨闁告挾鍠庨锝嗙節濮橆厼浜滈梺缁樻尭濞寸兘藝椤撱垺鍋℃繝濠傚暟缁犳娊鏌℃笟鍥ф灈闁宠棄顦垫慨鈧柨娑樺楠炲牓姊虹拠鎻掑毐缂傚秴妫濆畷鎴﹀礋椤掍礁寮块悗骞垮劚椤︿即鎮″☉銏″€堕柣鎰絻閳锋梹绻涢幓鎺旀憼妞ゃ劊鍎甸幃娆撳矗婢跺﹥鐏庢俊鐐€戦崹娲晝閵忋倕绠栨繛鍡樻尰閸嬨劑鏌ｉ幇顔藉殌濞寸媭鍘奸埞鎴︽偐閸偅姣勬繝娈垮枙閸楀啿鐣风憴鍕瘈婵﹩鍓涢悿鍥⒑鐟欏嫬鍔ら柣蹇撶墦瀹曟垿骞橀幇浣瑰兊濡炪倖鎸鹃崰鎾诲礄閳ユ剚娓婚柕鍫濋娴滄粎绱掔紒妯虹婵″弶鍔欓獮鎺楀箠瀹曞洤鏋旈柟椋庡Т椤斿繘顢欓悷棰佸闂佺懓澧界划顖炲煕閹达附鐓曟繛鎴烇公閸旂喖鏌嶉挊澶樻█闁哄被鍔戝鏉懳熺悰鈥充壕婵犻潧妫崵鏇㈡煙閹増顥夐梺鍗炴处缁绘繈妫冨☉妯绘闂佸搫鍊甸崑鎾绘⒒閸屾瑨鍏岀紒顕呭灦瀹曟繂鈻庨幘鈧悜钘夌＜闁绘劖褰冮幆鐐烘煟鎼搭垳绉甸柛鎾寸〒婢规洘绺介崨濠勫幗濠碘槅鍨辩€笛囨偟椤忓牊鍊堕煫鍥风到瀵噣鏌″畝瀣М闁轰焦鍔欏畷鎯邦槻妤犵偛顑夐幃妤€鈻撻崹顔界仌濠电偛顦伴惄顖炲春閵忊剝鍎熼柕濠忕畱閳ь剟鏀遍妵鍕箳閸℃ぞ澹曢梻浣侯焾缁绘劙鏁冮鍕垫綎婵炲樊浜滄导鐘绘煕閺囩偟浠涚粭鎴︽⒒娴ｈ櫣甯涙い銊ユ嚇瀹曨垶寮堕幋顓炴闂佸湱绮濠氬几鎼淬劍鐓欓悗鐢殿焾鍟搁梺浼欑秬閸╂牜鎹㈠┑瀣潊闁挎繂鎳愰崢顐︽⒑閸涘﹥鈷愰柣妤冨█瀹曞搫鈽夐姀鐘殿吅闂佹寧姊婚弲顐﹀储閸楃偐鏀介柣妯肩帛濞懷勪繆椤愶綆娈滄い銏℃椤㈡洟鏁傞悾灞藉笚闂佽崵濮村ú銈呂熸繝鍋界喖鍩€椤掑嫭鈷戦柛婵嗗閻掕法绱撳浣镐壕缂傚倷鑳舵慨鐢告儎椤栨凹鍤曟い鎺戝閸ㄥ倹銇勯弴鐐村櫤缂傚秵甯″濠氬磼濞嗘劗銈板銈嗘礃閻楃姴鐣烽弶娆炬僵閻犻缚娅ｉˇ褍鈹戦濮愪粶闁稿鎸鹃埀顒侇問閸犳牠鈥﹀畡鎵殾闁割偅娲﹂弫鍡椕归敐鍫綈闁绘繃娲熷缁樻媴缁涘娈愰梺鎼炲妼闁帮絽鐣峰鈧崺锟犲礋椤撶偛绲洪梻鍌氬€搁崐鎼佸磹閹间礁纾归柟闂寸绾剧懓顪冪€ｎ亝鎹ｉ柣顓炴閵嗘帒顫濋敐鍛婵°倗濮烽崑娑⑺囬悽绋挎瀬闁瑰墽绮崑鎰版煠绾板崬澧绘俊鑼厴濮婄粯绻濇惔鈥茬盎濠电偠顕滄俊鍥╁垝濞嗘挸绠ｉ柨鏃囨娴犻箖姊虹紒妯哄Е闁稿繑鐟︾粋宥咁煥閸垹褰勯梺鎼炲劘閸斿秶浜搁悧鍫涗簻闁靛／鍐ф勃闂侀潧娲ょ€氫即銆侀弴銏℃櫜闁糕剝鐟Σ褰掓⒒娴ｅ憡鎯堥柡鍫墮鐓ゆ俊顖氬悑瀹曞弶绻涢幋鐐电煠婵℃彃顭峰铏规兜閸涱喚褰ч梺鍛婃⒐閻熲晛顕ｉ銏╁悑闁告侗浜濋弬鈧梻浣规偠閸庮噣寮插┑瀣垫晩闁哄洢鍨洪悡娑橆熆鐠虹尨鍔熷褎娲栭…鑳槾闁哄拋鍋婇崺鈧い鎴ｆ硶缁佺兘鏌涚€ｎ偄濮夋俊鍙夊姍楠炴帒螖婵犲啯娅撻梻浣风串缁蹭粙寮甸鍕棷濞寸厧鐡ㄩ崐鐢告偡濞嗗繐顏璺哄閺屾稓鈧綆浜烽煬顒侇殽閻愬澧抽柕鍥ㄥ姍楠炴帡骞嬮悙鑼偠濠碉紕鍋戦崐鏍箰閻愵剙鍨旈悗闈涙啞椤洟鏌＄仦璇插姕闁抽攱鍨块弻銈嗘叏閹邦兘鍋撻弴鐐垫懃濠电姷鏁搁崑鐐电矈閹绢喖鐤炬繝闈涙川椤╄尙绱掔€ｎ亞姘ㄩ柡瀣叄閺岀喖鏌囬敃鈧獮妤呮煟濠靛牆鍘存慨濠冩そ瀹曨偊宕熼鈧崑宥夋⒑閹肩偛濡芥俊鐐扮矙楠炲啴鏁撻悩鍐蹭簻闂佺绻楅崑鎰板矗閸℃せ鏀介柣妯肩帛濞懷勪繆椤愶絿鎳囩€规洖纾幉鎾礋椤忓棛鐣鹃梻浣告贡缁垳鏁埡鍛亗濠靛倸鎲￠悡娆撴煢濡警妲洪柛鈺嬬秮閺屸剝鎷呴悷鏉款潚閻庤娲忛崝鎴︺€侀弴銏″亜闁炬艾鍊搁ˉ姘舵⒒娴ｅ憡璐￠柛搴涘€濆畷娲醇濠垫劗鍔烽梺鍐叉惈閹冲繘鎮￠悢鍏肩厵闁硅鍔栭悵顏堟煙閻у摜鍒伴棁澶愭煟濮楀棗浜濇繛鍛攻閹便劍绻濋崨顕呬哗闂佸綊顥撴繛鈧柛銊╃畺閹煎綊顢曢妶鍕枤闂傚倸鍊烽悞锕傚箖閸洖绀夌€光偓閸曨剙鈧埖绻濋棃娑卞劀缂傚秵鐗犻悡顐﹀炊閵婏箑顎涘┑鐐叉▕娴滃爼寮崒鐐寸厱闁哄洢鍔屾禍鐐烘煟濞戞帗娅呴柍瑙勫灴閹晠宕归锝嗙槑濠电姵顔栭崰妤佺箾婵犲洤绠犳俊銈呮噹缁€鍫澝归敐鍥ㄥ殌閹兼潙锕ョ换娑㈠箻閺夋垹鍔伴梺绋款儐閹稿骞堥妸锔剧瘈闁告劏鏂傛禒銏ゆ倵鐟欏嫭纾搁柛鏂跨Ф閹广垹鈽夐姀鐘殿唺闂佸搫娲ㄩ崑妯盒уΔ鍛拺闁告稑锕ょ粭姘舵偨椤栨稑娴柛鈹垮灪閹棃濡搁妷褜鍟嬮柣搴ゎ潐濞叉牕煤閵娾晛姹叉い鎰剁悼缁♀偓閻庡吀鍗抽弨鍗烆熆濮椻偓閸┾偓妞ゆ帊鐒︾粈瀣殽閻愯尙绠抽柍褜鍓ㄧ紞鍡涘窗閺嶎厼鍑犲〒姘ｅ亾闁哄本鐩獮鍥濞戞瑧浜堕梻浣虹帛閹稿爼宕曢悽绋胯摕闁跨喓濮寸粈鍐煏婵炲灝鍔楅柛瀣崌閹兘骞嶉搹顐も偓娲⒑閸濆嫭鍌ㄩ柛銊︽そ閹繝寮撮悢鍓佺畾濡炪倖鐗楃喊宥囨嫻閿熺姵鐓熸い鎾跺枔閹冲洭鏌＄仦绯曞亾瀹曞洦娈曢梺閫炲苯澧寸€规洑鍗冲鍊燁槾闁哄棴闄勬穱濠囧Χ閸涱喖娅ら梺鎼炲€曢崯鎾蓟瀹ュ浼犻柛鏇ㄥ亐閸嬫捁銇愰幒婵囨櫓闂佸憡鍔﹂崰妤呭煕閹烘嚚褰掓晲閸曨噮鍔呴梺缁樺笧閸嬫捇濡甸崟顖ｆ晣闁绘劙娼ч埅鐢告倵鐟欏嫭绀冮柛鏃€鐟ラ锝夊箻椤旇偐鍘梺瀹狀潐閸庤櫕绂嶆ィ鍐╃叆闁哄洨鍋涢埀顒佹倐閹瑦绻濋崘锔跨盎闂佺懓鎼Λ妤佺閸撗呯＝濞达絽鎼牎缂備礁顑嗙敮鈩冧繆閻㈢绀嬫い鏍ㄦ皑椤撳搫鈹戦悙鍙夘棞缂佺粯甯楃粋鎺撶附閸涘ň鎷绘繛杈剧悼椤牏鑺遍懡銈囩＜闂婎偒鍘鹃惌娆撴煙椤曗偓缁犳牠骞冨鍫熷癄濠㈣埖鍔曢弫褰掓⒒娴ｅ憡鎯堟繛灞傚姂瀹曟劙鏁愭径濠勫幐闂佸憡渚楅崰姘跺矗閸℃稒鈷戦柛婵嗗閺嗘瑦绻涚拠褏鐣靛┑鈩冩尦瀹曟﹢顢欓悾灞藉及闂傚鍋勫ú锕傚箲閸ヮ剙鐭楅柛鏇ㄥ墯閸欏繐鈹戦悩鎻掝伀閻㈩垱绋撶槐鎺懳旈崘銊︾亪闂佺硶鏂侀崑鎾愁渻閵堝棗鍧婇柛瀣尰閵囧嫰顢橀悙瀵糕敍濡炪倧闄勯悡锟犲箺閸洘鍊风紓鍫㈠Х缁犳岸姊洪棃娑氬闁瑰啿绻樺畷鎶藉捶椤撶姷锛滈梺缁橈耿濞佳勭墡闂備線鈧稓鈹掗柛鏂跨焸閳ユ棃宕橀鍛彴闂傚鍋掗崢濂杆夊鑸碘拺閻犲洦褰冮銏°亜閺冣偓閻楃姴鐣烽幎绛嬫晪闁逞屽墮閻ｇ兘骞嬮悙鐢电槇闂佺鏈划宥呪枔妤ｅ啯鈷戦柛锔诲幖閸斿銇勯妸銉︻棦鐎规洘鍔欓幃婊堟嚍閵壯冨箰濠电姰鍨煎▔娑㈩敄閸涘瓨鍊堕柨婵嗩槹閻撴瑦銇勯弴鐐搭棤缂佸鍠楅幈銊︾節閸涱噮浠╅梺褰掝棑婵炩偓闁瑰磭濞€椤㈡宕掗妶鍛毌闂傚倸鍊烽懗鍫曗€﹂崼銉晞闁糕剝绋掗崕搴亜閺嶎偄浠х€规挷绀侀…鍧楁嚋闂堟稑顫嶉梺鍝勬噺閹倿寮婚敐鍛傜喖宕崟顒佺槪闂備線鈧偛鑻晶顕€鏌ｉ弽褋鍋㈢€殿喛顕ч埥澶愬閻樼數鏉搁梻鍌氬€搁悧濠勭矙閹烘鍊剁€广儱顦伴埛鎴犵磽娴ｈ偂鎴犱焊閻㈠憡鐓曢柣妯虹－婢х敻鏌ｅ☉鍗炴珝鐎殿喕绮欐俊鎼佹晜閸擃灝銈夋⒒娴ｅ憡鍟為柟绋挎瀹曨亪宕橀鍕劒闂傚倸鍊搁崐宄邦渻閹烘梹顫曟い鏂垮⒔缁€濠囨煕閳╁啰鈽夐柣顓燁殜閺屾盯骞囬棃娑欑亪闂佽棄鍟伴崰鎰崲濞戙垹绠ｉ柣鎰仛閸ｎ參姊虹粙鎸庢崳闁哥姵鐗犲濠氬即閻旇櫣顔曢梺鍓茬厛閸犳帡宕戦幘璇插唨妞ゆ挾鍋熼悰銉モ攽椤旂瓔鐒鹃柛鈺傜墵閸╂盯骞嬮敂钘変化闂佹悶鍎荤徊娲磻閹剧粯鎯炴い鎰剁秵閸炴煡姊婚崒娆戭槮闁硅绻濆畷婵嬪即閻斿憡鐝锋繛瀵稿Т椤戝懘鎯屽Δ鍛厱闁斥晛鍟伴埊鏇㈡煃闁垮鐏╃紒杈ㄥ笧閳ь剨缍嗛崢鐣屾兜閸撲胶纾奸柣妯诲絻閺嗛亶鏌嶇憴鍕伌妞ゃ垺宀搁崺鈧い鎺嗗亾妞ゎ厼娲╅ˇ褰掓煃閵夛附顥堢€规洘锕㈤崺锟犲礃閻愵剛銈梻浣筋嚙閸戠晫绱為崱妯碱洸婵犻潧顑嗛崐鍨亜閹烘垵顏柍閿嬪灩閹叉悂鎮ч崼婵堢懆婵炲瓨绮堥崡鎶藉蓟濞戞鐔煎垂椤旂粯鐫忔繝鐢靛仜濡酣宕规禒瀣畺婵炲棙鎸婚崐缁樹繆椤栨縿鈧偓闁稿鎹囬幃浠嬪川婵犲嫬寮虫繝鐢靛█濞佳兾涘☉銏犵闁革富鍘剧壕濂告煏婵犲繘妾悘蹇ョ畵閺岋紕浠﹂崜褋鈧帡鏌嶈閸撱劎绱為崱娑樼；闁告侗鍘鹃弳锔锯偓鍏夊亾闁逞屽墴閸┾偓妞ゆ帒鍠氬鎰箾閸欏澧靛┑鈥冲缁瑥鈻庨幆褎顓块梻浣告贡閾忓酣宕板Δ鍛；闁告洦鍨遍悡鏇熺節闂堟稒顥滄い蹇婃櫇缁辨帡鎮╅搹顐犱虎濠殿喖锕ら…宄扮暦閹烘垟鏋庨柟鎼幗琚︾紓鍌氬€搁崐鍝ョ矓閹绢喗鏅濇い蹇撳閺嗭箓鏌熺€电浠х紒鈾€鍋撻梻浣规偠閸庢粓宕担鍓愩倕鈹戦悩鍨毄闁稿鍋ゅ畷褰掝敍閻愭彃鐎梺闈╁瘜閸樼偓绋夊鍡欑鐎瑰壊鍠曠花濂告煟閹捐泛鏋戝ǎ鍥э躬椤㈡稑顫濋浣糕偓顖炴⒑閸濆嫭顥戦柡鍛箞閹偓妞ゅ繐鐗嗙粻姘辨喐鐎ｎ喖纾婚柕蹇嬪€栭悡娑㈡倶閻愬灚娅曢崯绋款渻閵囧崬鍊荤粣鏃堟煛鐏炲墽娲存鐐搭焽閹瑰嫰鎮滃Ο闂撮偗闂佽姘﹂～澶娒哄Ο渚富濞寸姴顑呴弰銉╂煃瑜滈崜姘跺Φ閸曨垰绠崇€广儱顦伴鏍ㄧ箾鐎涙鐭嬬紒顔芥崌瀵鎮㈤崗鐓庘偓缁樹繆椤栨繃顏犲ù鐘虫尦濮婃椽鏌呴悙鑼跺濠⒀嗗皺閳ь剝顫夊ú鏍倶濮樿京鍗氶柣鏃傚帶閸楁娊鏌曡箛濞惧亾瀹曞洦顎嶆繝鐢靛О閸ㄥジ锝炴径灞惧床闁稿本绮庣粈濠傗攽閻樺弶鎼愰柡瀣╃窔閺岀喖鎮ч崼鐔哄嚒缂備讲鍋撻悗锝庡亖娴滄粓鏌熼幑鎰【閸熸悂姊洪崨濠忎緵闁搞劏娉涢～蹇曠磼濡顎撻梺鍛婄☉閿曘倝寮抽崼銏㈢＝濞达絿鐡旈崵娆撴煕閻曚礁浜伴柍銉︽瀹曟﹢鍩￠崘鐐カ闂佽鍑界紞鍡樼閿濆绠洪柡鍥╁亹閺€浠嬫煟閹邦厽缍戦柣蹇曞枛閺屾盯濡搁…鎴炵秷闂佺瀵掗崑濠傤潖缂佹ɑ濯撮柣鐔煎亰閸ゅ鈹戦悙鏉戠祷缂佸鎳撻悾鐑藉箣閿曗偓缁犵粯绻涢敐搴″幐缂併劌顭峰娲传閸曨剙绐涢梺鍝ュУ閹瑰洭骞嗙仦鍓х瘈闁搞儯鍔屽▓?"

    if check:
        return f"Do not widen scope on this turn. First restore one minimal feedback loop around `{check}`, confirm it passes, then decide whether to expand."
    return "Do not widen scope on this turn. First restore one minimal feedback loop, confirm this step passes, then decide whether to expand."


def _compose_success_signal_patch(
    *,
    reply: str,
    exercise_prompt: dict[str, object],
    chinese: bool,
) -> str:
    if not exercise_prompt:
        return ""
    success_signal = str(exercise_prompt.get("success_signal") or "").strip()
    if not success_signal:
        return ""
    if _contains_meta_coach_context(success_signal):
        return ""
    if _reply_mentions_excerpt(reply, success_signal):
        return ""
    if _reply_has_verification_signal(reply, chinese) and len(reply) > 180:
        return ""
    if chinese:
        return ""
    return f"You can count this slice as done when: {success_signal}."


def _compose_recalled_memory_patch(
    *,
    reply: str,
    recalled_coaching_memories: list[dict[str, object]],
    chinese: bool,
) -> str:
    if not recalled_coaching_memories:
        return ""
    if _reply_has_recall_signal(reply, chinese):
        return ""

    first = recalled_coaching_memories[0]
    lesson = str(first.get("lesson") or first.get("summary") or "").strip()
    title = str(first.get("title") or "").strip()
    if not lesson:
        return ""
    if _reply_mentions_excerpt(reply, lesson) or (title and _reply_mentions_excerpt(reply, title)):
        return ""
    if (
        len(reply) > 220
        and _reply_has_action_signal(reply, chinese)
        and _reply_has_verification_signal(reply, chinese)
    ):
        return ""
    if chinese:
        return ""
    return f"Stay on the line that already worked before: {lesson}."


def _anchor_step_to_workspace(
    step: str,
    *,
    file_path: str | None,
    project_entry_points: list[str],
    chinese: bool,
) -> str:
    anchor = file_path or (project_entry_points[0] if project_entry_points else "")
    if not anchor or _reply_mentions_excerpt(step, anchor):
        return step
    if chinese:
        return f"{step}闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘辨繝鐢靛Т閸婂綊宕戦妷鈺傜厸閻忕偠顕ф慨鍌溾偓娈垮櫘閸ｏ絽鐣锋總鍛婂亜闁告稑顭崬鍫曟⒒閸屾瑨鍏屾い顓炵墦椤㈡牠宕卞☉妯碱唶闂佸憡鎸嗛崘銊т喊婵＄偑鍊栭幐楣冨磻閹邦儵锝夊醇閻斿墎绠氬銈嗙墬缁诲秹宕靛▎鎰闁告稑娲ゅú锕傚煕閹寸偟绠鹃柤濂割杺閸ゆ瑦顨ラ悙鎼疁闁哄矉缍侀幃銏ゅ矗婢跺褰嬮柣搴㈩問閸犳牠鈥﹂悜钘夌畺闁靛繈鍊曞婵嗏攽閻樻彃顏懖鏍ㄧ節瀵伴攱婢橀埀顑懎绶ゅù鐘差儏閻ゎ喗銇勯弽顐㈠壉闁轰椒鑳堕埀顒€绠嶉崕閬嵥囨导鏉戠厱闁硅揪闄勯悡娆撴煠濞村娅呭ù鐘崇矒閺屽秷顧侀柛鎾村哺閹囨偐閼碱剚娈惧┑鐘绘涧椤戝懘宕橀埀顒€顪冮妶鍡樺暗闁稿缍侀弫鍐磼濞戞艾骞堥梻浣告惈濞层垽宕濆畝鍕€堕柣妯肩帛閻撴洟鏌熼懜顒€濡煎ù婊勫劤閳规垿鏁嶉崟顐℃澀闂佺锕ラ悧鐘茬暦濠靛鏅濋柍褜鍓熼垾锕傚锤濡も偓閻掑灚銇勯幒鎴濃偓鑽ゅ閸忕浜滈柡鍐ㄦ搐娴滃綊鏌涢埡瀣ɑ闁逛究鍔嶇换婵嬪川椤曞懍鍝楃紓鍌欑贰閸犳鎮烽埡鍛疇婵°倕鎷嬮弫宥夋煥濠靛棙顥￠柡鍛囧洦鈷掗柛灞剧懅椤︼箓鏌熺拠褏绡€鐎殿喖顭锋俊姝岊槾闁活厽鎹囬弻娑㈩敃閿濆棛顦ョ紓浣哄У閻擄繝寮婚弴锛勭杸闁哄洨鍊☉娆庣箚闁圭粯甯炴晶锕傛煛鐏炵偓绀夌紒鐘崇洴瀵挳鎮欓幇鈺佸姕闁靛洤瀚伴獮姗€鎼归锝呭壍闂備礁鐤囬～澶愬垂閸ф绠栨繛鍡樻尭閻顭块懜鐬垿藟閿濆洨纾介柛灞剧懆閸忓瞼绱掗鍛仯闁轰緡鍠栬灃闁告劦浜為悞鍧楁⒑閸︻厼鍔嬫い銊ユ瀹曟劙鏌ㄧ€ｃ劋绨婚梺鍦劋閸ㄧ敻鍩€椤掆偓椤兘骞嗘笟鈧畷鐓庘攽閸愨晜鏉搁梻浣虹帛閸旀浜稿▎鎰珷闁哄洢鍨洪悡鐔肩叓閸ャ劍鈷掔紒鐘靛仱閺岀喖顢欓弬銈堚偓鍧楁煙椤斿搫鐏茬€规洘顨婇幊鏍煛娴ｅ摜鐤勬繝鐢靛Т閻ュ寮舵惔鎾充壕闁规儳澧庨惌鍡椼€掑锝呬壕闂佺硶鏂傞崹钘夘嚕閹绢喗鍋愭い鎰垫線婢规洖鈹戦悙鑼闁诲繑绻堝绋库槈濞嗗秳绨诲銈嗘尵婵挳宕㈢€电硶鍋撳▓鍨珮闁稿锕ら悾宄邦潨閳ь剟銆佸▎鎾村殐闁宠桨绀佽婵犵绱曢崑鎴﹀磹閺嶎偅鏆滈柟鐑橆殔閻ゎ噣鏌ｅΔ鈧悧蹇涖€呴弻銉︾參婵☆垯璀﹀Σ鎾煛閳ь剚绂掔€ｎ偆鍘介梺褰掑亰閸撴盯骞楅悩缁樺€堕煫鍥ч瀹撳棝鏌＄仦鍓ф创妤犵偛顑呴埞鎴﹀醇閳惰￥鍔戦幃妤冩喆閸曨剛顦銈庡亜椤︻垶鈥﹂崶顏嗙杸婵炴垶顭傞埡鍛叆闁哄啫鍊瑰▍鏇犳喐閻楀牏鎳囨慨?`{anchor}` 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忋倖鈷掑ù锝堫潐閸嬬娀鏌涙惔銏°仢鐎规洘绮撻弫鍐磼濮橆厾鈧剟姊洪崨濠傚Е闁哥姵顨婇幃锟犲Ψ閳哄倻鍘搁梺鎼炲労閻撳牆鈻撻弬妫电懓顭ㄩ崼銏㈡毇濠殿喖锕ら幖顐ｆ櫏闂佹悶鍎滈埀顒勫磻閹炬緞鏃堝川椤撶媴绱遍梻浣筋潐瀹曟﹢宕洪弽褏鏆﹂柛娆忣槺缁♀偓闂傚倸鐗婄粙鎺戭啅濠靛牏纾奸柍閿亾闁稿鎹囧缁樻媴娓氼垳鍔搁梺鍝勭墱閸撴盯宕氶幒鎴犳殕闁告棁鍋愰崗姗€宕洪埀顒併亜閹烘垵顏柍閿嬪笒闇夐柨婵嗗椤掔喖鏌ｉ幒鏂夸壕闁靛洤瀚伴獮瀣倷閼碱兛鎮ｉ梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繃鎹ｉ梺纭呭Г濞茬喎顫忓ú顏勪紶闁告洦鍓欓崑宥夋⒑閹肩偛濡肩紓宥咃躬瀵崵鈧綆鍠栭悙濠囨煏婵炑冩噽濡插洭姊婚崒姘偓鎼佹偋婵犲嫮鐭欓柟鐑橆殔缁犲綊鏌熼柇锕€鏋ょ痪鎯с偢閺岀喖鏌囬敃鈧獮妯荤箾閹绘帞鎽犻柟渚垮妽缁绘繈宕橀埞澶歌檸闁诲氦顫夊ú蹇涘礉瀹ュ洦宕叉繝闈涙处閸庣喖鏌曡箛瀣仾婵炲牓绠栧铏规嫚閺屻儺鈧鏌涘Ο鑽ょ煉鐎规洘鍨块獮妯肩磼濡厧骞嶉梻鍌氬€搁崐鎼侇敋椤撯懞鍥晜閸撗咃紲闂佺粯锚绾绢厽鏅堕鈧彁闁搞儜宥堝惈婵犵鈧磭鍩ｇ€规洘甯掗～婵嬵敃閵忊晜顥￠梻鍌氬€搁崐椋庣矆娓氣偓閹潡宕堕‖顒佺洴瀹曠喖顢涢埀顒勫炊椤掑鏅梺缁樺姌鐏忔瑩宕㈠ú顏呭€垫鐐茬仢閸旀碍銇勯敂璺ㄧ煓鐎殿噮鍋婂畷鍫曞煛閸屾碍鐎鹃柣搴″帨閸嬫捇鏌嶈閸撶喖骞婇悙鐑樼劶鐎广儱妫楀▓鐔兼⒑闂堟冻绱￠柛婊€绀侀弲?"
    return f"{step} Start in `{anchor}`."


def _has_repeated_failure_signal(
    learning_outcomes: list[dict[str, object]],
    pace_signal: str,
    learner_signal: str,
) -> bool:
    if pace_signal in {"fragile", "stalled", "recovery"}:
        return True
    if learner_signal == "blocked":
        return True
    repeated_markers = {
        "repeated_error",
        "repeated_failure",
        "regression",
        "forgotten",
        "failed_review",
        "retry",
    }
    for item in learning_outcomes:
        outcome = str(item.get("outcome") or "").strip().lower()
        summary = str(item.get("summary") or "").strip().lower()
        if outcome in repeated_markers:
            return True
        if "failed twice" in summary or "repeated" in summary or "again" in summary:
            return True
    return False


def _reply_has_reason_signal(reply: str, chinese: bool) -> bool:
    markers = [
        "because",
        "this matters",
        "the reason",
        "so that",
        "which helps",
        "why this matters",
    ]
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)

def _reply_has_action_signal(reply: str, chinese: bool) -> bool:
    markers = [
        "next step",
        "start by",
        "start with",
        "begin with",
        "the next move",
        "apply it now",
        "try ",
        "run ",
        "verify",
        "check ",
        "implement ",
        "patch ",
    ]
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)

def _reply_has_verification_signal(reply: str, chinese: bool) -> bool:
    markers = ["verify", "check", "run", "test", "confirm", "passes", "feedback loop"]
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)

def _reply_has_scope_tightening_signal(reply: str, chinese: bool) -> bool:
    markers = ["do not widen", "reduce scope", "tighten", "smallest", "minimal", "one branch", "one patch"]
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)

def _reply_has_recall_signal(reply: str, chinese: bool) -> bool:
    markers = ["previous", "earlier", "already worked", "reuse", "stay on the line", "keep this lane"]
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _strip_generic_lane_prompt_artifacts(
    reply: str,
    scenario: str,
    learner_message: str,
    chinese: bool,
) -> str:
    resolved_scenario = _resolve_first_turn_guided_lane(
        scenario=scenario,
        learner_message=learner_message,
        reply=reply,
    )
    if resolved_scenario not in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return reply

    generic_paragraphs = {
        "I will first understand your goal, project, and blocker, remember that context for the next turn, then decide whether to guide the code, explain the principle, or shape the training thread first.",
        "Tell me which lane is closest right now: implementing an idea, adapting a project, or shaping the training thread first.",
        "Tell me which lane is closest right now: implementing an idea, adapting an existing project, or shaping the training thread first.",
    }
    if chinese:
        generic_paragraphs.update(
            {
                "鎴戜細鍏堢悊瑙ｄ綘鐨勭洰鏍囥€侀」鐩拰闃诲鐐癸紝璁颁綇杩欎簺涓婁笅鏂囷紝鍐嶅喅瀹氬厛甯︿綘鏀逛唬鐮併€佽鍘熺悊锛岃繕鏄厛鏁寸悊璁粌绾跨▼銆?,
                "璇峰憡璇夋垜鐜板湪鏈€鎺ヨ繎鍝潯绾匡細瀹炵幇涓€涓兂娉曘€侀€傞厤涓€涓」鐩紝杩樻槸鍏堟暣鐞嗚缁冪嚎绋嬨€?,
                "璇峰憡璇夋垜鐜板湪鏈€鎺ヨ繎鍝潯绾匡細瀹炵幇涓€涓兂娉曘€侀€傞厤鐜版湁椤圭洰锛岃繕鏄厛鏁寸悊璁粌绾跨▼銆?,
            }
        )

    paragraphs = [part.strip() for part in reply.split("\n\n") if part.strip()]
    filtered = [part for part in paragraphs if part not in generic_paragraphs]
    if len(filtered) == len(paragraphs):
        return reply
    return "\n\n".join(filtered).strip()


def _fresh_lane_comparison_requested(learner_message: str) -> bool:
    lowered = learner_message.casefold()
    markers = (
        "compare",
        "comparison",
        "difference",
        "different",
        "versus",
        "compared to",
        "瀵规瘮",
        "鍖哄埆",
        "鐩告瘮",
    )
    return any(marker.casefold() in lowered for marker in markers)


def _strip_fresh_lane_cross_lane_carryover(
    reply: str,
    *,
    scenario: str,
    learner_message: str,
    chinese: bool,
) -> str:
    if not reply.strip() or _fresh_lane_comparison_requested(learner_message):
        return reply

    lane_markers: dict[str, tuple[str, ...]] = {
        "remote_workspace": (
            "remote lane",
            "remote workspace",
            "ssh",
            "dev container",
            "wsl",
            "credential mode",
        ),
        "debug_loop": (
            "debug loop",
            "breakpoint",
            "launch.json",
            "call stack",
            "stack frame",
        ),
        "function_guidance": (
            "function-guidance lane",
            "function contract",
            "live call site",
            "signature help",
            "go to definition",
        ),
        "project_adaptation": (
            "existing-project lane",
            "adaptation lane",
            "must stay stable",
            "must change",
        ),
    }
    if chinese:
        lane_markers["remote_workspace"] += ("杩滅▼", "杩滅▼宸ヤ綔鍖?, "杩滅▼杈圭晫", "涓绘満", "瀹瑰櫒")
        lane_markers["debug_loop"] += ("璋冭瘯", "鏂偣", "璋冪敤鏍?)
        lane_markers["function_guidance"] += ("鍑芥暟", "璋冪敤鐐?)
        lane_markers["project_adaptation"] += ("鏀归€?, "鐜版湁椤圭洰")

    bridge_markers = (
        "already were",
        "previous",
        "earlier",
        "same lane",
        "same line",
        "we were with",
        "coming out of",
        "fits where we already were",
        "keep circling",
        "keep circling back",
        "circling back",
        "keep coming back to",
        "from the debug loop",
        "from the remote lane",
        "娌跨潃涓婁竴鏉?,
        "涓婁竴鏉?,
        "鍓嶄竴鏉?,
        "鍒氭墠閭ｆ潯",
    )
    other_lane_markers = [
        marker
        for lane, markers in lane_markers.items()
        if lane != scenario
        for marker in markers
    ]
    if not other_lane_markers:
        return reply

    def _mentions_other_lane(text: str) -> bool:
        lowered = text.casefold()
        return any(marker.casefold() in lowered for marker in other_lane_markers)

    def _split_visible_chunks(text: str) -> list[str]:
        chunks = re.split(r"(?<=[銆傦紒锛??锛?])|(?<=\.)\s+|\n+", text)
        return [chunk.strip() for chunk in chunks if chunk and chunk.strip()]

    paragraphs = [part.strip() for part in reply.split("\n\n") if part.strip()]
    filtered: list[str] = []
    removed = False
    for part in paragraphs:
        lowered = part.casefold()
        mentions_other_lane = _mentions_other_lane(part)
        has_bridge_cue = any(marker.casefold() in lowered for marker in bridge_markers)
        if mentions_other_lane and has_bridge_cue:
            removed = True
            continue
        filtered.append(part)

    if removed and filtered:
        return "\n\n".join(filtered).strip()

    sentence_filtered: list[str] = []
    sentence_removed = False
    for part in paragraphs:
        chunks = _split_visible_chunks(part)
        kept_chunks = [chunk for chunk in chunks if not _mentions_other_lane(chunk)]
        if len(kept_chunks) != len(chunks):
            sentence_removed = True
        if kept_chunks:
            sentence_filtered.append(" ".join(kept_chunks))

    if sentence_removed and sentence_filtered:
        return "\n\n".join(sentence_filtered).strip()
    return reply

def _reply_has_guided_lane_signal(reply: str, scenario: str, chinese: bool) -> bool:
    if not reply.strip():
        return False

    lowered = reply.casefold()
    english_markers: dict[str, tuple[str, ...]] = {
        "remote_workspace": (
            "vs code remote lane",
            "workspace boundary",
            "credential mode",
            "files actually live",
            "credential move",
        ),
        "debug_loop": (
            "trustworthy debug loop",
            "breakpoint",
            "state change",
            "pause at the first",
            "single value",
        ),
        "function_guidance": (
            "live call site",
            "signature help",
            "function contract",
            "hover",
            "go to definition",
        ),
        "project_adaptation": (
            "existing-project lane",
            "must stay stable",
            "must change",
            "narrow adaptation",
        ),
    }
    chinese_markers: dict[str, tuple[str, ...]] = {
        "remote_workspace": (
            "VS Code remote",
            "宸ヤ綔鍖鸿竟鐣?,
            "credential mode",
            "API key",
            "鏂囦欢瀹為檯鍦ㄥ摢鍙版満鍣?,
        ),
        "debug_loop": (
            "debug loop",
            "鏂偣",
            "state change",
            "璋冪敤鏍?,
            "stack frame",
        ),
        "function_guidance": (
            "live call site",
            "signature help",
            "function contract",
            "hover",
            "definition",
        ),
        "project_adaptation": (
            "project adaptation",
            "蹇呴』绋冲畾",
            "蹇呴』鏀瑰彉",
            "閫傞厤",
            "杈圭晫",
        ),
    }
    markers = english_markers.get(scenario, ())
    if chinese:
        markers = markers + chinese_markers.get(scenario, ())
    return any(marker.casefold() in lowered for marker in markers)

def _reply_mentions_excerpt(reply: str, source: str) -> bool:
    excerpt = _search_excerpt(source)
    if not excerpt:
        return False
    return _normalize_search_text(excerpt) in _normalize_search_text(reply)


def _search_excerpt(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return ""
    if any("\u4e00" <= char <= "\u9fff" for char in cleaned):
        compact = "".join(
            char for char in cleaned if ("\u4e00" <= char <= "\u9fff") or char.isascii() and char.isalnum()
        )
        return compact[:12]
    words = cleaned.split(" ")
    return " ".join(words[:6])[:48]


def _normalize_search_text(text: str) -> str:
    return "".join(
        char.casefold()
        for char in text
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    )


def _is_meta_step_hint(text: str) -> bool:
    normalized = _normalize_coach_meta_candidate(text)
    if not normalized:
        return False
    lowered = normalized.casefold()
    return (
        lowered.startswith("review rhythm:")
        or lowered.startswith("current coaching focus:")
        or lowered.startswith("\u590d\u4e60\u8282\u594f\uff1a")
        or lowered.startswith("\u5f53\u524d\u805a\u7126\uff1a")
        or _looks_like_internal_coach_meta(normalized)
    )


def _contains_meta_coach_context(text: str) -> bool:
    return _looks_like_internal_coach_meta(text)


def _provider_service_onboarding_reply(self, response_language: str | None = None) -> str:
    if _prefers_chinese(response_language):
        return (
            "鍏堝埆鎬ョ潃鐩存帴涓婃柟妗堛€傜涓€杞垜鏇存兂鍏堟妸浣犵殑鐩爣銆侀」鐩澧冨拰浣犳洿閫傚悎鐨勫甫娉曞榻愯捣鏉ャ€俓n\n"
            "浣犲彲浠ョ洿鎺ュ憡璇夋垜浣犵幇鍦ㄦ墜涓婄殑椤圭洰銆佹兂瀛﹀埌鍝竴姝ャ€佸崱鍦ㄥ摢閲岋紝鎴戜細鎶婅繖浜涘垽鏂浣忥紝鍚庨潰缁х画娌跨潃鍚屼竴鏉＄嚎甯︿綘锛屼笉浼氭瘡涓€杞兘閲嶅紑銆俓n\n"
            "浣犵幇鍦ㄦ洿闇€瑕佹垜甯︿綘鍋氬摢涓€绫伙細瀹炵幇涓€涓?idea銆佹敼閫犵幇鏈夐」鐩紝杩樻槸鍏堟妸璁粌涓荤嚎鍜岃妭濂忓畾涓嬫潵锛?
        )
    return (
        "Let's not jump straight into a solution. On the first turn I want to line up the few things that matter most: "
        "your goal, the project context, and how you prefer to be coached.\n\n"
        "Tell me what you are working on, where you want to get to, and where the thread feels unstable right now. "
        "I will remember that context so the next turn can continue the same lane instead of restarting.\n\n"
        "Which lane is closest right now: implement an idea, adapt a project, or shape the training thread first?"
    )


def _provider_service_error_reply(self, exc: Exception, response_language: str | None = None) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    if _prefers_chinese(response_language):
        return (
            "杩炴帴鏁欑粌鏈嶅姟鏃堕亣鍒颁簡涓€鐐归棶棰橈紝鎵€浠ヨ繖涓€杞垜鍏堢敤鏈湴鏁欑粌閫昏緫鎶婁綘鎺ヤ綇銆?
            f" 杩欐鐨勯敊璇槸锛歿detail}銆?
        )
    return (
        "I hit an issue connecting to the coach service, so I am keeping this turn moving locally. "
        f"The error was: {detail}."
    )


def _provider_service_missing_api_key_reply(
    self,
    response_language: str | None = None,
) -> str:
    if _prefers_chinese(response_language):
        return (
            "Trainer 鐜板湪杩樹笉鑳芥寮忓紑濮嬶紝鍥犱负杩樻病鏈夊彲鐢ㄧ殑 API key銆?
            " 璇峰厛鍘?Settings 淇濆瓨 provider銆乵odel 鍜?API key锛岀劧鍚庢垜灏辫兘缁х画甯︿綘銆?
        )
    return (
        "Trainer cannot start working yet because there is no usable API key. "
        "Open Settings, save a provider, model, and API key, and I can continue from there."
    )


async def _provider_service_coaching_reply_stream(
    self,
    profile: UserProfile | None,
    message: str,
    current_file: dict[str, object] | None = None,
    response_language: str | None = None,
    answer_mode: str | None = None,
    coach_context: dict[str, Any] | None = None,
    history: list[dict[str, str]] | None = None,
):
    self.clear_last_reply_state()
    if not self.has_api_key:
        if not profile:
            yield self._missing_api_key_reply(response_language)
            return
        yield self._missing_api_key_reply_with_scaffold(
            profile,
            message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        return
    if not profile:
        yield self._onboarding_reply(response_language)
        return

    messages = build_coaching_messages(
        profile,
        message,
        current_file,
        response_language=response_language,
        answer_mode=answer_mode,
        coach_context=coach_context,
        history=history,
    )
    model = self._resolve_model()
    try:
        if self._plain_completion_uses_agent_binding():
            raw_content = ""
            pending_visible = ""
            yielded_visible = False
            holdback_chars = 256 if _prefers_chinese(response_language) else 32
            async for chunk in self._completion_stream_via_agent_binding(
                messages,
                temperature=0.7,
                max_tokens=1024,
            ):
                raw_content += chunk
                pending_visible += chunk
                reply_corruption_detail = _mixed_script_reply_corruption_detail(
                    raw_content,
                    message=message,
                    response_language=response_language,
                )
                if reply_corruption_detail:
                    self._record_reply_language_corruption(reply_corruption_detail)
                    if not yielded_visible:
                        recovery_override = _build_language_corruption_recovery_override(
                            message,
                            current_file=current_file,
                            coach_context=coach_context,
                            response_language=response_language,
                        )
                        if isinstance(recovery_override, dict):
                            reply_override = str(recovery_override.get("reply") or "").strip()
                            if reply_override:
                                yield reply_override
                    return
                if len(pending_visible) > holdback_chars:
                    safe_prefix = pending_visible[:-holdback_chars]
                    pending_visible = pending_visible[-holdback_chars:]
                    if safe_prefix:
                        yielded_visible = True
                        yield safe_prefix
            reply_corruption_detail = _mixed_script_reply_corruption_detail(
                raw_content,
                message=message,
                response_language=response_language,
            )
            if reply_corruption_detail:
                self._record_reply_language_corruption(reply_corruption_detail)
                if not yielded_visible:
                    recovery_override = _build_language_corruption_recovery_override(
                        message,
                        current_file=current_file,
                        coach_context=coach_context,
                        response_language=response_language,
                    )
                    if isinstance(recovery_override, dict):
                        reply_override = str(recovery_override.get("reply") or "").strip()
                        if reply_override:
                            yield reply_override
                return
            if pending_visible:
                yielded_visible = True
                yield pending_visible
            final_content = self.finalize_coaching_reply(
                raw_content,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
            if not raw_content and final_content:
                yield final_content
                return
            if final_content.startswith(raw_content) and final_content != raw_content:
                yield final_content[len(raw_content) :]
            return
        client = self._get_client()
        stream, _ = await self._create_chat_completion(
            client=client,
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
            stream=True,
        )
        reasoning_filter = _ReasoningBlockFilter()
        emitted_visible = False
        yielded_visible = False

        def _normalize_stream_chunk(text: str) -> str:
            nonlocal emitted_visible
            if emitted_visible:
                return text
            trimmed = text.lstrip()
            if not trimmed:
                return ""
            emitted_visible = True
            return trimmed

        raw_content = ""
        pending_visible = ""
        holdback_chars = 256 if _prefers_chinese(response_language) else 32
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text = _normalize_stream_chunk(reasoning_filter.push(chunk.choices[0].delta.content))
                if not text:
                    continue
                raw_content += text
                pending_visible += text
                reply_corruption_detail = _mixed_script_reply_corruption_detail(
                    raw_content,
                    message=message,
                    response_language=response_language,
                )
                if reply_corruption_detail:
                    self._record_reply_language_corruption(reply_corruption_detail)
                    if not yielded_visible:
                        recovery_override = _build_language_corruption_recovery_override(
                            message,
                            current_file=current_file,
                            coach_context=coach_context,
                            response_language=response_language,
                        )
                        if isinstance(recovery_override, dict):
                            reply_override = str(recovery_override.get("reply") or "").strip()
                            if reply_override:
                                yield reply_override
                    return
                if len(pending_visible) > holdback_chars:
                    safe_prefix = pending_visible[:-holdback_chars]
                    pending_visible = pending_visible[-holdback_chars:]
                    if safe_prefix:
                        yielded_visible = True
                        yield safe_prefix
        tail = _normalize_stream_chunk(reasoning_filter.flush())
        if tail:
            raw_content += tail
            pending_visible += tail
        reply_corruption_detail = _mixed_script_reply_corruption_detail(
            raw_content,
            message=message,
            response_language=response_language,
        )
        if reply_corruption_detail:
            self._record_reply_language_corruption(reply_corruption_detail)
            if not yielded_visible:
                recovery_override = _build_language_corruption_recovery_override(
                    message,
                    current_file=current_file,
                    coach_context=coach_context,
                    response_language=response_language,
                )
                if isinstance(recovery_override, dict):
                    reply_override = str(recovery_override.get("reply") or "").strip()
                    if reply_override:
                        yield reply_override
            return
        if pending_visible:
            yielded_visible = True
            yield pending_visible
        final_content = self.finalize_coaching_reply(
            raw_content,
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        if not raw_content and final_content:
            yield final_content
            return
        if final_content.startswith(raw_content) and final_content != raw_content:
            yield final_content[len(raw_content) :]
    except Exception as exc:
        category, retryable, status_code, provider_reachable, model_supported = self._classify_error(exc)
        provider_config = self._config or ProviderConfig(
            name="unspecified-provider",
            base_url="",
            api_key_ref="trainer.unspecified",
            model=self._resolve_model(),
        )
        detail = self._detail_from_category(
            category,
            provider=provider_config,
            error=exc,
        )
        self._record_last_reply_failure(
            category=category,
            detail=detail,
            retryable=retryable,
            status_code=status_code,
            provider_reachable=provider_reachable,
            model_supported=model_supported,
            error=exc,
        )
        yield self._error_reply_with_scaffold(
            exc=exc,
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )


def _clean_guided_domain_empty_reply(
    domain: str | None,
    *,
    response_language: str | None,
) -> str:
    if domain == "remote_workspace":
        return _localized_text(
            (
                "Remote work gets easier once the workspace boundary stops moving. "
                "Stay in the VS Code remote lane for one more turn: identify whether this workspace is SSH, "
                "tunnels, dev container, WSL, or local, then verify which machine owns the files and whether "
                "the API key should stay local or remote. Return in 2 short lines: one real workspace label or "
                "path, and one sentence about the safe credential mode."
            ),
            (
                "鍏堟妸宸ヤ綔鍖鸿竟鐣岃娓呮锛宺emote 鎵嶄細鍙樼畝鍗曘€傜户缁暀鍦?VS Code remote 杩欐潯绾夸笂锛?
                "鍏堢‘璁ゅ綋鍓嶆槸 SSH銆乼unnels銆乨ev container銆乄SL 杩樻槸 local锛屽啀纭鏂囦欢瀹為檯鍦ㄥ摢鍙版満鍣ㄤ笂锛?
                "浠ュ強 API key 搴旇鐣欏湪 local 杩樻槸 remote銆傝鐢?2 琛屽洖澶嶏細绗竴琛岀粰涓€涓湡瀹炵殑宸ヤ綔鍖烘爣绛炬垨璺緞锛?
                "绗簩琛岀粰涓€涓畨鍏?credential mode 鐨勫垽鏂€?
            ),
            response_language,
        )
    if domain == "debug_loop":
        return _localized_text(
            (
                "Keep this in one trustworthy VS Code debug loop. Reproduce once, pause at the first meaningful "
                "state change, and inspect one value, branch, or stack frame before widening the story. Return in "
                "2 short lines: where you will pause first, and what single thing you expect to inspect there."
            ),
            (
                "鍏堟妸杩欎竴杞敹鏉熸垚涓€涓彲淇＄殑 VS Code debug loop銆傚厛澶嶇幇涓€娆★紝鍦ㄧ涓€涓湁鎰忎箟鐨?state change 鍋滀笅锛?
                "鍐嶆鏌ヤ竴涓?value銆乥ranch 鎴?stack frame锛屼笉瑕佸厛鎶婂彊杩伴摵寮€銆傝鐢?2 琛屽洖澶嶏細绗竴琛屽啓浣犲噯澶囧仠鍦ㄥ摢閲岋紝"
                "绗簩琛屽啓浣犲噯澶囧厛妫€鏌ュ摢涓€涓偣銆?
            ),
            response_language,
        )
    if domain == "function_guidance":
        return _localized_text(
            (
                "Keep this in the function-guidance lane. Start from one live call site, then use hover, "
                "signature help, and definition in that order until the contract stops moving. Return in 2 short "
                "lines: the function name, and the call site or evidence that proves what the function expects."
            ),
            (
                "鍏堟妸杩欎竴杞暀鍦?function guidance 杩欐潯绾夸笂銆傚厛浠庝竴涓?live call site 寮€濮嬶紝鍐嶆寜椤哄簭鐢?hover銆?
                "signature help銆乨efinition 鎶?contract 璇荤ǔ銆傝鐢?3 琛屽洖澶嶏細绗竴琛屽啓鍑芥暟鍚嶏紝绗簩琛屽啓浣犵湅鐨?"
                "call site锛岀涓夎鍐欒兘璇佹槑瀹冩湡鏈涗粈涔堢殑 contract 璇佹嵁銆?
            ),
            response_language,
        )
    if domain == "project_adaptation":
        return _localized_text(
            (
                "Keep this in the existing-project adaptation lane. First separate what must stay stable from what "
                "must change, then land one narrow adaptation before widening scope. Return in 3 short lines: one "
                "stable behavior you must keep, one thing that must change, and the first boundary you want to adapt."
            ),
            (
                "鍏堟妸杩欎竴杞暀鍦ㄧ幇鏈夐」鐩?adaptation 杩欐潯绾夸笂銆傚厛鍒嗘竻鍝簺蹇呴』淇濇寔涓嶅彉銆佸摢浜涘繀椤绘敼鍙橈紝"
                "鍐嶅厛钀戒竴涓獎鑼冨洿 adaptation锛屼笉瑕佷竴寮€濮嬪氨閾哄ぇ銆傝鐢?3 琛屽洖澶嶏細绗竴琛屽啓蹇呴』淇濇寔涓嶅彉鐨勮涓猴紝"
                "绗簩琛屽啓蹇呴』鏀瑰彉鐨勭洰鏍囷紝绗笁琛屽啓浣犳兂鍏堥€傞厤鐨勭涓€鏉¤竟鐣屻€?
            ),
            response_language,
        )
    return ""


def _clean_guided_domain_empty_reply_override(
    domain: str | None,
    *,
    response_language: str | None,
) -> dict[str, str] | None:
    if domain == "remote_workspace":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the VS Code remote lane.",
                "provider 娌℃湁杩斿洖鍙鍐呭锛屾墍浠ユ垜鍏堟妸杩欎竴杞户缁暀鍦?VS Code remote 杩欐潯绾夸笂銆?,
                response_language,
            ),
            "next_step": _localized_text(
                "Return one real workspace label or path and one sentence about the safe credential mode.",
                "璇疯繑鍥炰竴涓湡瀹炵殑宸ヤ綔鍖烘爣绛炬垨璺緞锛屽啀琛ヤ竴鍙ュ畨鍏?credential mode 鐨勫垽鏂€?,
                response_language,
            ),
            "teaching_note": _localized_text(
                "Keep the lesson grounded in the real workspace boundary before widening the remote story.",
                "鍏堟妸鐪熷疄宸ヤ綔鍖鸿竟鐣岃绋筹紝鍐嶅睍寮€ remote 缁嗚妭銆?,
                response_language,
            ),
        }
    if domain == "debug_loop":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the VS Code debug lane.",
                "provider 娌℃湁杩斿洖鍙鍐呭锛屾墍浠ユ垜鍏堟妸杩欎竴杞敹鏉熷湪 VS Code debug 杩欐潯绾夸笂銆?,
                response_language,
            ),
            "next_step": _localized_text(
                "Tell me where you will pause first and which single value, branch, or stack frame you expect to inspect there.",
                "璇峰憡璇夋垜浣犲噯澶囧厛鍋滃湪鍝噷锛屼互鍙婁綘鍑嗗鍏堟鏌ュ摢涓€涓?value銆乥ranch 鎴?stack frame銆?,
                response_language,
            ),
            "teaching_note": _localized_text(
                "Pause at one meaningful state change before widening the debug story.",
                "鍏堝湪涓€涓湁鎰忎箟鐨?state change 鍋滀笅锛屽啀灞曞紑 debug 鍙欒堪銆?,
                response_language,
            ),
        }
    if domain == "function_guidance":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the function-guidance lane.",
                "provider 娌℃湁杩斿洖鍙鍐呭锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦?function guidance 杩欐潯绾夸笂銆?,
                response_language,
            ),
            "next_step": _localized_text(
                "Return the function name and one call site that proves what the function expects.",
                "璇疯繑鍥炲嚱鏁板悕銆佷竴涓?call site锛屼互鍙婅兘璇佹槑瀹冩湡鏈涗粈涔堢殑 contract 璇佹嵁銆?,
                response_language,
            ),
            "teaching_note": _localized_text(
                "Keep the contract anchored to one live call site before widening the explanation.",
                "鍏堟妸 contract 閿氬畾鍦ㄤ竴涓?live call site 涓婏紝鍐嶅睍寮€瑙ｉ噴銆?,
                response_language,
            ),
        }
    if domain == "project_adaptation":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the existing-project adaptation lane.",
                "provider 娌℃湁杩斿洖鍙鍐呭锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦ㄧ幇鏈夐」鐩?adaptation 杩欐潯绾夸笂銆?,
                response_language,
            ),
            "next_step": _localized_text(
                "Tell me what must stay stable, what must change, and the first boundary you want to adapt.",
                "璇峰憡璇夋垜浠€涔堝繀椤讳繚鎸佷笉鍙樸€佷粈涔堝繀椤绘敼鍙橈紝浠ュ強浣犳兂鍏堥€傞厤鐨勭涓€鏉¤竟鐣屻€?,
                response_language,
            ),
            "teaching_note": _localized_text(
                "Separate stable behavior from change scope before widening the adaptation plan.",
                "鍏堝垎娓呯ǔ瀹氶潰鍜屽彉鏇撮潰锛屽啀鎵╁ぇ adaptation 璁″垝銆?,
                response_language,
            ),
        }
    return None


def _build_empty_reply_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, object]:
    domain_override = _guided_domain_empty_reply_override(
        message,
        current_file=current_file,
        coach_context=coach_context,
        response_language=response_language,
    )
    summary = str(domain_override.get("summary") or "").strip() if isinstance(domain_override, dict) else ""
    next_step = str(domain_override.get("next_step") or "").strip() if isinstance(domain_override, dict) else ""
    teaching_note = (
        str(domain_override.get("teaching_note") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    if not summary:
        summary = _localized_text(
            "The provider returned an empty visible answer.",
            "provider 娌℃湁杩斿洖鍙鍐呭銆?,
            response_language,
        )
    if not next_step:
        next_step = _localized_text(
            "Retry with a visible conclusion.",
            "鍏堣繑鍥炰竴涓彲瑙佺粨璁猴細鐩爣琛屼负銆佸綋鍓嶅垽鏂紝浠ュ強涓嬩竴姝ユ渶灏忓彲楠岃瘉鍔ㄤ綔銆?,
            response_language,
        )
    if not teaching_note:
        teaching_note = _localized_text(
            "Keep the same lane and ask for one visible, verifiable conclusion on the next turn.",
            "缁х画娌跨潃鍚屼竴鏉℃暀瀛︾嚎璧帮紝涓嬩竴杞厛鎷垮洖涓€涓彲瑙佷笖鍙獙璇佺殑缁撹銆?,
            response_language,
        )
    resume_thread = _agentic_resume_thread_text(
        summary,
        next_step,
        response_language=response_language,
    )
    return {
        "summary": summary,
        "next_step": next_step,
        "blocker": summary,
        "teaching_note": teaching_note,
        "resume_thread": resume_thread,
        "stop_reason": "empty_response",
        "fell_back": True,
    }


def _build_language_corruption_recovery_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, object] | None:
    if not _prefers_chinese(response_language):
        return None
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    guided_reply = _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
    ).strip()
    domain_override = _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
    )
    if not guided_reply and not isinstance(domain_override, dict):
        return None

    summary = _localized_text(
        "The provider reply came back degraded, so I kept this lesson moving with a local recovery scaffold.",
        "杩欐 provider 鐨勫洖澶嶄笉澶熷共鍑€锛屾墍浠ユ垜鍏堢敤鏈湴鎭㈠鑴氭墜鏋舵妸杩欒疆鏁欏鎺ヤ綇銆?,
        response_language,
    )
    next_step = (
        str(domain_override.get("next_step") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    teaching_note = (
        str(domain_override.get("teaching_note") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    if not next_step:
        next_step = _localized_text(
            "Keep going with the next small verifiable move on this same lane.",
            "缁х画娌跨潃鍚屼竴鏉′富绾垮仛涓嬩竴涓彲楠岃瘉鐨勫皬鍔ㄤ綔銆?,
            response_language,
        )
    if not teaching_note:
        teaching_note = _localized_text(
            "Keep the lesson narrow, visible, and verifiable until the provider path is stable again.",
            "鍏堟妸杩欒疆鏁欏鏀剁獎鎴愬彲瑙併€佸彲楠岃瘉鐨勫皬鍔ㄤ綔锛岀瓑 provider 閾捐矾绋冲畾鍚庡啀鎵╁ぇ銆?,
            response_language,
        )
    if not guided_reply:
        guided_reply = summary
    reply = guided_reply if guided_reply.startswith(summary) else f"{summary}\n\n{guided_reply}"
    resume_thread = _agentic_resume_thread_text(
        summary,
        next_step,
        response_language=response_language,
    )
    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
        "resume_thread": resume_thread,
        "stop_reason": "language_corruption_recovered",
        "fell_back": True,
        "scenario": domain,
    }


def _mode_style_label(mode: str, chinese: bool) -> str:
    if chinese:
        return {
            "guided": "鎴戝厛甯︿綘鎶?,
            "balanced": "鎴戜滑鍏堟妸",
            "direct": "鍏堢洿鎺ユ妸",
        }.get(mode, "鎴戜滑鍏堟妸")
    return {
        "guided": "In guided mode,",
        "balanced": "In balanced mode,",
        "direct": "In direct mode,",
    }.get(mode, "In guided mode,")


def _scaffold_anchor(
    *,
    scenario: str,
    goal: str,
    file_path: str | None,
    current_focus: str,
    chinese: bool,
) -> str:
    visible_focus = _surface_context_text(current_focus, chinese=chinese)
    if visible_focus:
        return (
            f"鎴戜滑鍏堟部鐫€杩欐潯绾跨户缁細{visible_focus}銆?
            if chinese
            else f"I will keep working along this live thread: {visible_focus}."
        )

    if scenario == "remote_workspace":
        base = "鎴戜滑鍏堟妸杩欎竴杞暀鍦?VS Code remote 杩欐潯绾夸笂銆? if chinese else (
            "I will keep this turn in the VS Code remote lane."
        )
    elif scenario == "debug_loop":
        base = "鎴戜滑鍏堟妸杩欎竴杞敹鏉熸垚涓€涓彲淇＄殑 debug loop銆? if chinese else (
            "I will keep this turn inside one trustworthy debug loop."
        )
    elif scenario == "function_guidance":
        base = "鎴戜滑鍏堟妸杩欎竴杞暀鍦?function guidance 杩欐潯绾夸笂銆? if chinese else (
            "I will keep this turn in the function-guidance lane."
        )
    elif scenario == "project_adaptation":
        base = "鎴戜滑鍏堟部鐫€鐜版湁椤圭洰 adaptation 杩欐潯绾跨户缁€? if chinese else (
            "I will keep this turn in the existing-project adaptation lane."
        )
    elif scenario == "principle":
        base = "鎴戜滑鍏堟妸杩欎竴杞敋瀹氬湪褰撳墠鍘熺悊鍜屼唬鐮佽竟鐣屼笂銆? if chinese else (
            "I will anchor this turn in the current principle and code boundary first."
        )
    else:
        base = (
            f"鎴戜滑鍏堝洖鍒?`{file_path}` 杩欎竴姝ャ€?
            if chinese and file_path
            else f"I will re-anchor on `{file_path}` first."
            if file_path
            else "鎴戜滑鍏堝榻愯繖涓€姝ョ湡姝ｈ瀹屾垚鐨勭洰鏍囥€?
            if chinese
            else "I want to re-anchor on the real goal of this step first."
        )

    if goal and scenario not in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        goal_text = _trim_sentence(goal, 42 if chinese else 96)
        if chinese:
            return f"{base} 杩欎竴杞厛鏈嶅姟杩欎釜鐩爣锛歿goal_text}銆?
        return f"{base} The immediate goal for this round is: {goal_text}."
    return base


def _scaffold_diagnosis(
    *,
    scenario: str,
    learner_signal: str,
    diagnostics_count: int,
    weak_spots: list[str],
    teaching_observations: list[str],
    summary: str,
    teaching_decision_reason: str,
    chinese: bool,
) -> str:
    visible_summary = _surface_context_text(summary, chinese=chinese)
    if visible_summary:
        return visible_summary if visible_summary.endswith(("銆?, ".", "!", "锛?, "?", "锛?)) else (
            f"{visible_summary}銆?
            if chinese
            else f"{visible_summary}."
        )

    visible_reason = _surface_context_text(teaching_decision_reason, chinese=chinese)
    if visible_reason:
        return (
            f"杩欎竴杞厛杩欐牱鏀舵潫锛屾槸鍥犱负{visible_reason}銆?
            if chinese
            else f"I am narrowing this turn this way because {visible_reason}."
        )

    if diagnostics_count > 0:
        return (
            f"褰撳墠鏂囦欢閲岃繕鏈?{diagnostics_count} 鏉?diagnostics锛屽厛涓嶈閾哄紑锛屽厛鎭㈠涓€鏉℃渶灏忓弽棣堥摼銆?
            if chinese
            else f"There are still {diagnostics_count} diagnostics in the current file, so I want one minimal feedback loop before we widen anything."
        )

    if weak_spots:
        weak_spot = _trim_sentence(weak_spots[0], 28 if chinese else 72)
        return (
            f"杩欎竴杞厛鐩綇鏈€瀹规槗鍙嶅鍗′綇鐨勭偣锛歿weak_spot}銆?
            if chinese
            else f"The riskiest recurring weak spot on this turn is: {weak_spot}."
        )

    if teaching_observations:
        observation = _surface_context_text(teaching_observations[0], chinese=chinese)
        if observation:
            return observation if observation.endswith(("銆?, ".", "!", "锛?, "?", "锛?)) else (
                f"{observation}銆?
                if chinese
                else f"{observation}."
            )

    if learner_signal == "blocked":
        return (
            "浣犵幇鍦ㄦ洿闇€瑕佺殑鏄厛鎶婅寖鍥村帇灏忥紝鑰屼笉鏄啀鍔犳洿澶氳В閲娿€?
            if chinese
            else "Right now you need a smaller scope more than a larger explanation."
        )

    scenario_map = {
        "remote_workspace": (
            "鍏堟妸宸ヤ綔鍖鸿竟鐣岃绋筹紝鍐嶅喅瀹?remote 閲岀殑涓嬩竴姝ャ€?,
            "The next useful move depends on proving the real workspace boundary first.",
        ),
        "debug_loop": (
            "鍏堟妸 debug 鏀舵潫鍒颁竴涓?pause point銆佷竴涓?value 鍜屼竴涓獙璇佸姩浣滀笂銆?,
            "The next useful move is to keep debugging inside one pause point, one observed value, and one verification move.",
        ),
        "function_guidance": (
            "鍏堟妸鍑芥暟 contract 閿氬畾鍦ㄤ竴涓?live call site 涓婏紝鍐嶆墿瑙ｉ噴銆?,
            "The next useful move is to anchor the function contract to one live call site before the explanation widens.",
        ),
        "project_adaptation": (
            "鍏堝垎娓呯ǔ瀹氶潰鍜屽彉鏇撮潰锛屽啀鍔ㄧ涓€鏉?adaptation 杈圭晫銆?,
            "The next useful move is to separate the stable surface from the change surface before the first adaptation.",
        ),
        "principle": (
            "鍏堟妸鍘熺悊鍘嬪洖褰撳墠浠ｇ爜杈圭晫锛屽啀鍋氫竴涓渶灏忛獙璇併€?,
            "The next useful move is to pin the principle back to the live code boundary and test it once.",
        ),
    }
    zh, en = scenario_map.get(
        scenario,
        (
            "杩欎竴杞厛钀戒竴涓渶灏忓彲楠岃瘉鍔ㄤ綔锛屾妸绾跨▼缁х画鎺ョǔ銆?,
            "The next useful move is one small verifiable action that keeps the thread continuous.",
        ),
    )
    return zh if chinese else en


def _scaffold_next_step(
    *,
    scenario: str,
    mode: str,
    learner_signal: str,
    file_path: str | None,
    weak_spots: list[str],
    next_step_hint: str,
    chinese: bool,
) -> str:
    localized_hint = _surface_context_text(next_step_hint, chinese=chinese)
    if next_step_hint and (localized_hint or not chinese):
        visible_hint = localized_hint or next_step_hint
        if chinese:
            if scenario in {"project_idea", "engineering_challenge"}:
                return f"鍏堝埆鎶婂畠璁叉垚鏇村ぇ鐨勮鍒掞紝鍏堝仛杩欎竴姝ワ細{visible_hint}"
            if scenario == "principle":
                return f"鍏堟妸杩欎釜鍘熺悊钀芥垚鍔ㄤ綔锛歿visible_hint}"
            if learner_signal == "blocked":
                return f"杩欎竴杞厛鍙仛杩欎竴涓姩浣滐細{visible_hint}"
            if mode == "direct":
                return f"鍏堢洿鎺ヤ粠杩欎竴姝ュ紑濮嬶細{visible_hint}"
            return f"涓嬩竴姝ュ厛鍋氳繖涓細{visible_hint}"
        return f"The next move I recommend is this: {next_step_hint}"

    scenario_step = _scenario_step_text(
        scenario=scenario,
        file_path=file_path,
        weak_spots=weak_spots,
        chinese=chinese,
    )
    mode_prefix = _mode_style_label(mode, chinese)
    if chinese:
        if learner_signal == "blocked":
            return f"鍏堝埆鍚屾椂鍋氬お澶氾紝鍙仛杩欎竴姝ワ細{scenario_step}"
        if mode == "direct":
            return f"鍏堢洿鎺ヤ粠杩欎竴姝ュ紑濮嬶細{scenario_step}"
        return f"{mode_prefix}{scenario_step}銆?
    if learner_signal == "blocked":
        return f"{mode_prefix} do not do too much at once; start by {scenario_step}"
    return f"{mode_prefix} the highest-value next move is to {scenario_step}"


def _scenario_step_text(
    scenario: str,
    *,
    file_path: str | None,
    weak_spots: list[str],
    chinese: bool,
) -> str:
    file_suffix = _file_suffix(file_path, chinese=chinese)
    weak_spot = _trim_sentence(weak_spots[0], 24 if chinese else 56) if weak_spots else ""

    if scenario == "remote_workspace":
        return (
            "鍒ゆ柇褰撳墠宸ヤ綔鍖烘槸 SSH銆乼unnels銆乨ev container銆乄SL 杩樻槸 local锛屽啀纭鏂囦欢瀹為檯鍦ㄥ摢鍙版満鍣ㄤ笂"
            if chinese
            else "identify whether the workspace is SSH, tunnels, dev container, WSL, or local, then prove which machine actually owns the files"
        )
    if scenario == "debug_loop":
        return (
            "鍙鐜颁竴娆★紝鍦ㄧ涓€涓湁鎰忎箟鐨?breakpoint 鍋滀笅锛屾鏌ヤ竴涓?value銆乥ranch 鎴?stack frame"
            if chinese
            else "reproduce once, pause at the first meaningful breakpoint, and inspect one value, branch, or stack frame"
        )
    if scenario == "function_guidance":
        return (
            "鍏堜粠涓€涓?live call site 璇昏繖涓嚱鏁帮紝鍐嶇敤 hover銆乻ignature help銆乨efinition 鎶?contract 璇荤ǔ"
            if chinese
            else "start from one live call site, then use hover, signature help, and definition until the contract stops moving"
        )
    if scenario == "project_adaptation":
        return (
            "鍐欏嚭蹇呴』淇濇寔涓嶅彉鐨勮涓恒€佸繀椤绘敼鍙樼殑鐩爣锛屼互鍙婅鍏堢鐨勭涓€鏉¤竟鐣?
            if chinese
            else "write down what must stay stable, what must change, and the first boundary you want to adapt"
        )
    if scenario == "principle":
        return (
            f"鎶婂綋鍓嶅師鐞嗛拤鍦ㄤ竴澶?live code boundary 涓婏紝鍐嶅仛涓€涓渶灏忛獙璇亄file_suffix}"
            if chinese
            else f"pin the current principle to one live code boundary and run one small verification{file_suffix}"
        )
    if scenario in {"review", "task", "next_task"}:
        return (
            f"鍏堟仮澶嶄竴鏉℃渶灏忓弽棣堥摼{file_suffix}"
            if chinese
            else f"restore one minimal feedback loop{file_suffix}"
        )
    if scenario == "plan":
        return (
            "鍙繚鐣欎竴涓渶杩戠殑閲岀▼纰戝拰涓€涓獙璇佺偣"
            if chinese
            else "keep only the nearest milestone and one verification point"
        )
    if weak_spot:
        return (
            f"鍏堟妸 {weak_spot} 杩欎竴澶勫帇绋硔file_suffix}"
            if chinese
            else f"stabilize {weak_spot} first{file_suffix}"
        )
    return (
        f"鍏堣惤涓€涓渶灏忓彲楠岃瘉鍒囩墖{file_suffix}"
        if chinese
        else f"land one smallest verifiable slice{file_suffix}"
    )


def _scaffold_teaching_note(
    *,
    scenario: str,
    mode: str,
    recent_wins: list[str],
    weak_spots: list[str],
    due_reviews: list[dict[str, str]],
    review_rhythm: str,
    coach_defaults: dict[str, object],
    tone_name: str,
    verbosity_bias: str,
    chinese: bool,
) -> str:
    if recent_wins:
        recent_win = _surface_context_text(recent_wins[0], chinese=chinese) or recent_wins[0]
        return (
            f"浣犲墠闈㈠凡缁忔妸杩欐潯绾跨殑涓€閮ㄥ垎璧伴€氫簡锛歿recent_win}銆傝繖涓€杞户缁部鐫€鍙獙璇佺殑鑺傚璧般€?
            if chinese
            else f"You already proved part of this lane earlier: {recent_win}. I want to keep the same verifiable rhythm."
        )
    if weak_spots:
        weak_spot = _surface_context_text(weak_spots[0], chinese=chinese) or weak_spots[0]
        return (
            f"鎴戜細缁х画鐩綇 {weak_spot} 杩欎釜鏄撻敊鐐癸紝涓嶈瀹冨湪杩欎竴杞噸鏂版墿鏁ｃ€?
            if chinese
            else f"I will keep watching the recurring weak spot around {weak_spot} so it does not spread again on this turn."
        )
    if due_reviews:
        reason = _format_due_review_item(due_reviews[0])
        return (
            f"鍋氬畬杩欎竴姝ュ悗锛屾垜浠啀鍐冲畾瑕佷笉瑕佹妸澶嶄範闃熷垪閲岀殑杩欐潯涔熸敹鍥炴潵锛歿reason}銆?
            if chinese
            else f"After this move, we can decide whether to pull this review thread back in: {reason}."
        )
    if review_rhythm and scenario == "plan":
        visible_rhythm = _surface_context_text(review_rhythm, chinese=chinese)
        if visible_rhythm:
            return (
                f"杩欎竴姝ュ畬鎴愬悗锛屽啀鎸夌幇鍦ㄧ殑 review rhythm 鎺ョ潃璧帮細{visible_rhythm}銆?
                if chinese
                else f"After this move, continue with the current review rhythm: {visible_rhythm}."
            )
    if mode == "direct":
        return (
            "鎴戜細鎶婅В閲婂帇鐭竴鐐癸紝浣嗕細鎶婁负浠€涔堣繖涓€姝ラ噸瑕佸拰鎬庝箞楠岃瘉璇存竻妤氥€?
            if chinese
            else "I will keep the explanation short, but I will still make the reason and verification signal explicit."
        )
    if verbosity_bias == "short":
        return (
            "杩欎竴杞厛淇濇寔鐭竴鐐癸紝鍙洿缁曞綋鍓嶈繖涓€鏉＄嚎璇存竻妤氥€?
            if chinese
            else "I will keep this turn compact and stay on one line of coaching."
        )
    if tone_name:
        return (
            f"杩欎竴杞垜浼氫繚鎸?{tone_name} 杩欑被璇皵锛屼絾浼樺厛淇濊瘉鍔ㄤ綔鍙獙璇併€?
            if chinese
            else f"I will keep the {tone_name} tone, but I still want the move to stay verifiable."
        )
    if coach_defaults:
        return (
            "鎴戜細缁х画娌跨潃浣犲凡缁忚瀹氬ソ鐨勬暀缁冨亸濂芥潵甯︼紝涓嶉澶栨墦寮€鏂扮殑闈€?
            if chinese
            else "I will keep following your saved coaching defaults instead of opening a new lane."
        )
    return (
        "杩欎竴姝ョ殑閲嶇偣涓嶆槸璁叉洿澶氾紝鑰屾槸鎶婄嚎绋嬬户缁帴绋炽€?
        if chinese
        else "The point of this turn is not more breadth; it is keeping the thread stable."
    )


def _scaffold_close(
    *,
    learner_signal: str,
    mode: str,
    verbosity_bias: str,
    chinese: bool,
) -> str:
    if chinese:
        if learner_signal == "blocked":
            return "濡傛灉浣犱竴鍔ㄦ墜鍙堝崱浣忥紝灏辨妸閭ｄ竴灏忔鍘熸牱甯﹀洖鏉ワ紝鎴戝府浣犲啀缂╀竴灞傘€?
        if mode == "direct":
            return "鍋氬畬鍒彧璇粹€滃ソ浜嗏€濓紝鍛婅瘔鎴戜綘楠岃瘉鍒颁簡浠€涔堬紝鎴戝啀甯綘閫変笅涓€姝ャ€?
        if verbosity_bias == "short":
            return "鍏堝仛杩欎竴姝ワ紝鍐嶆妸缁撴灉甯﹀洖鏉ャ€?
        return "鍏堝仛杩欎竴姝ワ紝鍐嶆妸缁撴灉甯﹀洖鏉ワ紝鎴戜滑鍐嶅喅瀹氭槸鎵╁睍銆佸鐩橈紝杩樻槸缁х画鏀剁揣銆?
    if learner_signal == "blocked":
        return "If you get stuck again as soon as you start, show me the exact small section you were about to change and I will help you reduce it one step further."
    if mode == "direct":
        return "When you finish, do not just say 'done'; tell me what result you verified and I will help you choose the next move."
    if verbosity_bias == "short":
        return "Take that one step first, then bring back the result."
    return "Take that one step first, then bring back the result and we can decide whether to expand, review, or tighten the loop."


def _file_suffix(file_path: str | None, chinese: bool = False) -> str:
    if not file_path:
        return ""
    if chinese:
        return f"锛屽厛浠?`{file_path}` 寮€濮?
    return f" in `{file_path}`"


_FIRST_TURN_EXPLICIT_SCENARIOS = {
    "concept_teaching",
    "debug_loop",
    "engineering_challenge",
    "function_guidance",
    "idea_implementation",
    "next_task",
    "principle",
    "project_adaptation",
    "project_idea",
    "project_sourcing",
    "remote_workspace",
    "review",
    "review_reflection",
}


def _first_turn_concrete_followthrough(*, chinese: bool) -> str:
    if chinese:
        return "\u4e0b\u4e00\u6b65\uff1a\u6cbf\u7740\u4f60\u521a\u624d\u8fd9\u4e2a\u5177\u4f53\u4efb\u52a1\u7ee7\u7eed\uff0c\u7ed9\u6211\u4e00\u4e2a\u4f60\u73b0\u5728\u5c31\u80fd\u5c55\u5f00\u7684\u771f\u5b9e\u4f8b\u5b50\u3001\u7247\u6bb5\u6216\u8f93\u5165\uff0c\u6211\u4f1a\u5728\u540c\u4e00\u6761\u7ebf\u91cc\u7ee7\u7eed\u5e26\u4f60\u505a\u3002"
    return (
        "Next step: stay on the exact task you just named and give me one real example, "
        "snippet, or input you can open right now so we can keep the same thread moving."
    )


def _first_turn_has_concrete_focus(
    *,
    scenario: str | None,
    learner_message: str,
    reply: str,
) -> bool:
    normalized = str(scenario or "").strip().lower()
    if normalized and normalized in _FIRST_TURN_EXPLICIT_SCENARIOS:
        return True

    source = f"{learner_message}\n{reply}".strip()
    if not source:
        return False

    if _infer_guided_coaching_domain(
        source,
        current_file=None,
        coach_context=None,
    ):
        return True

    lowered = source.casefold()
    concrete_markers = (
        "`",
        "/",
        "\\",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".java",
        ".go",
        ".rs",
        ".md",
        "http://",
        "https://",
        "api",
        "bug",
        "class",
        "code",
        "dataset",
        "debug",
        "endpoint",
        "error",
        "essay",
        "file",
        "function",
        "grammar",
        "implement",
        "implementation",
        "library",
        "method",
        "module",
        "outline",
        "paragraph",
        "project",
        "python",
        "react",
        "refactor",
        "remote",
        "review",
        "sentence",
        "snippet",
        "sql",
        "ssh",
        "stack frame",
        "stack trace",
        "test",
        "traceback",
        "translation",
        "typescript",
        "vocabulary",
        "word",
        "writing",
        "\u4ee3\u7801",
        "\u5199\u4f5c",
        "\u51fd\u6570",
        "\u5355\u8bcd",
        "\u53e5\u5b50",
        "\u6bb5\u843d",
        "\u65b9\u6cd5",
        "\u62a5\u9519",
        "\u63a5\u53e3",
        "\u7ffb\u8bd1",
        "\u8bed\u6cd5",
        "\u8bcd\u6c47",
        "\u8c03\u8bd5",
        "\u8fdc\u7a0b",
        "\u9879\u76ee",
    )
    if any(marker in lowered for marker in concrete_markers):
        return True

    meta_markers = (
        "coach me",
        "help me learn",
        "how should we start",
        "how should we work",
        "learning plan",
        "study plan",
        "training plan",
        "training rhythm",
        "what should we focus on first",
        "where should we start",
        "\u4ece\u54ea\u5f00\u59cb",
        "\u5148\u5b66\u4ec0\u4e48",
        "\u5b66\u4e60\u8ba1\u5212",
        "\u5b66\u4e60\u8282\u594f",
        "\u600e\u4e48\u5f00\u59cb",
        "\u600e\u4e48\u5b66",
        "\u8bad\u7ec3\u4e3b\u7ebf",
        "\u8bad\u7ec3\u8ba1\u5212",
        "\u8bad\u7ec3\u8282\u594f",
        "\u5e26\u6211\u5b66",
    )
    if any(marker in lowered for marker in meta_markers):
        return False

    words = [part for part in re.split(r"\s+", lowered) if part]
    return len(words) >= 12


def _should_offer_generic_first_turn_lane_prompt(
    *,
    scenario: str | None,
    learner_message: str,
    reply: str,
) -> bool:
    if _fresh_lane_comparison_requested(learner_message):
        return False
    return not _first_turn_has_concrete_focus(
        scenario=scenario,
        learner_message=learner_message,
        reply=reply,
    )


def _compact_first_turn_reply(
    reply: str,
    *,
    chinese: bool,
    scenario: str | None = None,
    learner_message: str = "",
) -> str:
    paragraphs = [part.strip() for part in reply.split("\n\n") if part.strip()]
    if not paragraphs:
        return ""

    kept: list[str] = []
    for paragraph in paragraphs:
        lowered = paragraph.lower()
        if lowered.startswith("##") or lowered.startswith("###"):
            continue
        if lowered.startswith("- ") or lowered.startswith("* "):
            continue
        kept.append(paragraph)
        if len(kept) >= 2:
            break

    if not kept:
        kept = paragraphs[:2]

    trimmed = [_trim_sentence(item, 112 if chinese else 142) for item in kept[:2]]
    first = trimmed[0] if trimmed else ""
    guided_lane = _resolve_first_turn_guided_lane(
        scenario=scenario,
        learner_message=learner_message,
        reply=reply,
    )
    guided_note = _first_turn_lane_continuity_note(guided_lane, chinese=chinese)
    guided_close = _first_turn_lane_next_step(guided_lane, chinese=chinese)
    if guided_note and guided_close:
        second = guided_note
        close = guided_close
        return "\n\n".join([part for part in (first, second, close) if part.strip()])

    if not _should_offer_generic_first_turn_lane_prompt(
        scenario=scenario,
        learner_message=learner_message,
        reply=reply,
    ):
        second = trimmed[1] if len(trimmed) > 1 else _first_turn_concrete_followthrough(chinese=chinese)
        return "\n\n".join([part for part in (first, second) if part.strip()])

    second = (
        trimmed[1]
        if len(trimmed) > 1
        else (
            "鎴戜細鍏堢悊瑙ｄ綘鐨勭洰鏍囥€侀」鐩澧冨拰褰撳墠闃诲鐐癸紝鍐嶆妸杩欎竴杞敹鏉熷埌鏈€鍚堥€傜殑鏁欏绾块噷銆?
            if chinese
            else "I will first understand your goal, project, and blocker, remember that context for the next turn, then decide whether to guide the code, explain the principle, or shape the training thread first."
        )
    )
    if chinese:
        close = "鍛婅瘔鎴戠幇鍦ㄦ洿鎺ヨ繎鍝竴绫伙細瀹炵幇涓€涓?idea銆佹敼閫犵幇鏈夐」鐩紝杩樻槸鍏堟妸璁粌涓荤嚎鍜岃妭濂忓畾涓嬫潵銆?
    else:
        close = "Tell me which lane is closest right now: implementing an idea, adapting a project, or shaping the training thread first."
    return "\n\n".join([part for part in (first, second, close) if part.strip()])


def _compose_principle_followthrough_patch(
    *,
    reply: str,
    principle_note: dict[str, object],
    chinese: bool,
) -> str:
    if not principle_note:
        return ""

    why_it_matters = str(principle_note.get("why_it_matters") or "").strip()
    apply_now = str(principle_note.get("apply_now") or principle_note.get("follow_up_exercise") or "").strip()
    source_asset_title = str(principle_note.get("source_asset_title") or "").strip()

    needs_reason = bool(why_it_matters) and not (
        _reply_mentions_excerpt(reply, why_it_matters) or _reply_has_reason_signal(reply, chinese)
    )
    needs_apply = bool(apply_now) and not (
        _reply_mentions_excerpt(reply, apply_now) or _reply_has_action_signal(reply, chinese)
    )
    needs_source = bool(source_asset_title) and not (
        _reply_mentions_excerpt(reply, source_asset_title)
    )

    parts: list[str] = []
    if chinese:
        if needs_reason:
            parts.append(f"瀹冨湪杩欓噷閲嶈锛屾槸鍥犱负{why_it_matters}銆?)
        if needs_apply:
            prefix = "浣犵幇鍦? if apply_now.startswith("鍏?) else "浣犵幇鍦ㄥ厛"
            parts.append(f"{prefix}{apply_now}銆?)
        if needs_source:
            parts.append(f"缁х画娌跨潃 `{source_asset_title}` 杩欐潯瑙ｉ噴绾裤€?)
    else:
        if needs_reason:
            parts.append(f"It matters here because {why_it_matters}.")
        if needs_apply:
            parts.append(f"Apply it now by {apply_now}.")
        if needs_source:
            parts.append(f"Stay on `{source_asset_title}` for the next explanation move.")
    return " ".join(parts).strip()


def _compose_missing_next_step_patch(
    *,
    reply: str,
    scenario: str,
    next_step_hint: str,
    file_path: str | None,
    project_entry_points: list[str],
    learner_signal: str,
    mode: str,
    chinese: bool,
) -> str:
    step = next_step_hint.strip()
    if not step:
        return ""
    if _is_meta_step_hint(step):
        return ""

    if _reply_mentions_excerpt(reply, step):
        return ""
    if _reply_has_action_signal(reply, chinese) and len(reply) > 120:
        return ""

    anchored_step = _anchor_step_to_workspace(
        step,
        file_path=file_path,
        project_entry_points=project_entry_points,
        chinese=chinese,
    )
    if chinese:
        if scenario in {"project_idea", "engineering_challenge"}:
            return f"鍏堝埆鎶婂畠璁叉垚鏇村ぇ鐨勮鍒掞紝鍏堝仛杩欎竴姝ワ細{anchored_step}"
        if scenario == "principle":
            return f"鍏堟妸杩欎釜鍘熺悊钀芥垚鍔ㄤ綔锛歿anchored_step}"
        if learner_signal == "blocked":
            return f"杩欎竴杞厛鍙仛杩欎竴涓姩浣滐細{anchored_step}"
        if mode == "direct":
            return f"鍏堢洿鎺ヤ粠杩欎竴姝ュ紑濮嬶細{anchored_step}"
        return f"涓嬩竴姝ュ厛鍋氳繖涓細{anchored_step}"

    if scenario in {"project_idea", "engineering_challenge"}:
        return f"Do not widen this into a larger plan yet. Take this first cut: {anchored_step}"
    if scenario == "principle":
        return f"Turn the principle into action with this move: {anchored_step}"
    if learner_signal == "blocked":
        return f"For this turn, do only this next move: {anchored_step}"
    if mode == "direct":
        return f"Start directly with this step: {anchored_step}"
    return f"The next move is this: {anchored_step}"


def _compose_review_tightening_patch(
    *,
    reply: str,
    scenario: str,
    failing_checks: list[str],
    learning_outcomes: list[dict[str, object]],
    pace_signal: str,
    learner_signal: str,
    chinese: bool,
) -> str:
    repeated_failure = _has_repeated_failure_signal(learning_outcomes, pace_signal, learner_signal)
    review_pressure = scenario in {"review", "task", "next_task", "plan", "project_adaptation"} or bool(
        failing_checks or repeated_failure
    )
    if not review_pressure:
        return ""
    if _reply_has_scope_tightening_signal(reply, chinese) and _reply_has_verification_signal(reply, chinese):
        return ""

    check = failing_checks[0] if failing_checks else ""
    if chinese:
        if check:
            return f"鍏堝埆鎵╄寖鍥淬€傚厛鎶?`{check}` 杩欎竴鏉℃渶灏忓弽棣堥摼鎭㈠鍑烘潵锛岀‘璁ゅ畠閫氳繃锛屽啀鍐冲畾瑕佷笉瑕佹墿銆?
        return "鍏堝埆鎵╄寖鍥淬€傚厛鎭㈠涓€鏉℃渶灏忓弽棣堥摼锛岀‘璁よ繖涓€姝ラ€氳繃锛屽啀鍐冲畾瑕佷笉瑕佹墿銆?

    if check:
        return f"Do not widen scope on this turn. First restore one minimal feedback loop around `{check}`, confirm it passes, then decide whether to expand."
    return "Do not widen scope on this turn. First restore one minimal feedback loop, confirm this step passes, then decide whether to expand."


def _compose_success_signal_patch(
    *,
    reply: str,
    exercise_prompt: dict[str, object],
    chinese: bool,
) -> str:
    if not exercise_prompt:
        return ""
    success_signal = str(exercise_prompt.get("success_signal") or "").strip()
    if not success_signal:
        return ""
    if _contains_meta_coach_context(success_signal):
        return ""
    if _reply_mentions_excerpt(reply, success_signal):
        return ""
    if _reply_has_verification_signal(reply, chinese) and len(reply) > 180:
        return ""
    if chinese:
        return f"杩欎竴姝ョ畻杩囩殑淇″彿鏄細{success_signal}銆?
    return f"You can count this slice as done when: {success_signal}."


def _compose_recalled_memory_patch(
    *,
    reply: str,
    recalled_coaching_memories: list[dict[str, object]],
    chinese: bool,
) -> str:
    if not recalled_coaching_memories:
        return ""
    if _reply_has_recall_signal(reply, chinese):
        return ""

    first = recalled_coaching_memories[0]
    lesson = str(first.get("lesson") or first.get("summary") or "").strip()
    title = str(first.get("title") or "").strip()
    if not lesson:
        return ""
    if _reply_mentions_excerpt(reply, lesson) or (title and _reply_mentions_excerpt(reply, title)):
        return ""
    if (
        len(reply) > 220
        and _reply_has_action_signal(reply, chinese)
        and _reply_has_verification_signal(reply, chinese)
    ):
        return ""
    if chinese:
        return f"鍏堟部鐫€涔嬪墠宸茬粡楠岃瘉杩囩殑鍋氭硶璧帮細{lesson}銆?
    return f"Stay on the line that already worked before: {lesson}."


def _anchor_step_to_workspace(
    step: str,
    *,
    file_path: str | None,
    project_entry_points: list[str],
    chinese: bool,
) -> str:
    anchor = file_path or (project_entry_points[0] if project_entry_points else "")
    if not anchor or _reply_mentions_excerpt(step, anchor):
        return step
    if chinese:
        return f"{step}锛屽厛浠?`{anchor}` 寮€濮嬨€?
    return f"{step} Start in `{anchor}`."


def _reply_has_reason_signal(reply: str, chinese: bool) -> bool:
    markers = ["because", "this matters", "the reason", "so that", "which helps", "why this matters"]
    if chinese:
        markers.extend(["鍥犱负", "杩欏緢閲嶈", "鍘熷洜", "杩欐牱灏辫兘", "涓轰粈涔堣繖涓€姝ラ噸瑕?, "瀹冨湪杩欓噷閲嶈"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_action_signal(reply: str, chinese: bool) -> bool:
    markers = [
        "next step",
        "start by",
        "start with",
        "begin with",
        "the next move",
        "apply it now",
        "try ",
        "run ",
        "verify",
        "check ",
        "implement ",
        "patch ",
    ]
    if chinese:
        markers.extend(["涓嬩竴姝?, "鐜板湪鍏?, "鍏堝仛", "鍏堣窇", "鍏堟敼", "鍏堣ˉ", "鍏堥獙璇?, "鍏堟鏌?, "鍏堟寚鍑?, "鍏堢‘璁?, "鐩存帴浠庤繖涓€姝?])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_verification_signal(reply: str, chinese: bool) -> bool:
    markers = ["verify", "check", "run", "test", "confirm", "passes", "feedback loop"]
    if chinese:
        markers.extend(["楠岃瘉", "妫€鏌?, "纭", "璺戜竴娆?, "閫氳繃", "鍙嶉閾?, "楠屾敹淇″彿", "鍙獙璇?])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_scope_tightening_signal(reply: str, chinese: bool) -> bool:
    markers = ["do not widen", "reduce scope", "tighten", "smallest", "minimal", "one branch", "one patch"]
    if chinese:
        markers.extend(["鍏堝埆鎵╄寖鍥?, "涓嶈鎵╄寖鍥?, "鏀剁揣", "鏈€灏忓弽棣堥摼", "鏈€灏忓彲楠岃瘉", "缂╁皬鑼冨洿"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_recall_signal(reply: str, chinese: bool) -> bool:
    markers = ["previous", "earlier", "already worked", "reuse", "stay on the line", "keep this lane"]
    if chinese:
        markers.extend(["涔嬪墠", "鍓嶉潰", "宸茬粡楠岃瘉杩?, "澶嶇敤", "娌跨潃杩欐潯绾?, "缁х画杩欐潯绾?])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


setattr(ProviderService, "_onboarding_reply", _provider_service_onboarding_reply)
setattr(ProviderService, "_error_reply", _provider_service_error_reply)
setattr(ProviderService, "_missing_api_key_reply", _provider_service_missing_api_key_reply)
setattr(ProviderService, "coaching_reply_stream", _provider_service_coaching_reply_stream)


def _clean_provider_service_onboarding_reply(
    self,
    response_language: str | None = None,
) -> str:
    if _prefers_chinese(response_language):
        return (
            "鍏堝埆鎬ョ潃鐩存帴涓婃柟妗堛€傜涓€杞垜鎯冲厛鎶婁綘鐨勭洰鏍囥€侀」鐩澧冦€?
            "浠ュ強鏇撮€傚悎浣犵殑甯︽硶瀵归綈璧锋潵銆俓n\n"
            "浣犲彲浠ョ洿鎺ュ憡璇夋垜鐜板湪鎵嬩笂鐨勯」鐩€佹兂瀛﹀埌鍝竴姝ャ€佸崱鍦ㄥ摢閲屻€?
            "鎴戜細璁颁綇杩欎簺鍒ゆ柇锛屽悗闈㈢户缁部鐫€鍚屼竴鏉＄嚎甯︿綘锛屼笉浼氭瘡涓€杞兘閲嶅紑銆俓n\n"
            "浣犵幇鍦ㄦ洿闇€瑕佹垜甯︿綘鍋氬摢涓€绫伙細瀹炵幇涓€涓?idea銆佹敼閫犵幇鏈夐」鐩紝"
            "杩樻槸鍏堟妸璁粌涓荤嚎鍜岃妭濂忓畾涓嬫潵锛?
        )
    return (
        "Let's not jump straight into a solution. On the first turn I want to line up the few things that matter most: "
        "your goal, the project context, and how you prefer to be coached.\n\n"
        "Tell me what you are working on, where you want to get to, and where the thread feels unstable right now. "
        "I will remember that context so the next turn can continue the same lane instead of restarting.\n\n"
        "Which lane is closest right now: implement an idea, adapt a project, or shape the training thread first?"
    )


def _clean_provider_service_error_reply(
    self,
    exc: Exception,
    response_language: str | None = None,
) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    if _prefers_chinese(response_language):
        return (
            "杩炴帴鏁欑粌鏈嶅姟鏃堕亣鍒伴棶棰橈紝鎵€浠ヨ繖杞垜鍏堢敤鏈湴鎭㈠閫昏緫鎺ヤ綇浣犮€?
            f"杩欐閿欒鏄細{detail}銆?
        )
    return (
        "I hit an issue connecting to the coach service, so I am keeping this turn moving locally. "
        f"The error was: {detail}."
    )


def _clean_provider_service_missing_api_key_reply(
    self,
    response_language: str | None = None,
) -> str:
    if _prefers_chinese(response_language):
        return (
            "Trainer 鐜板湪杩樹笉鑳芥寮忓紑濮嬶紝鍥犱负杩樻病鏈夊彲鐢ㄧ殑 API key銆?
            "璇峰厛鍒?Settings 淇濆瓨 provider銆乵odel 鍜?API key锛岀劧鍚庢垜灏辫兘缁х画甯︿綘銆?
        )
    return (
        "Trainer cannot start working yet because there is no usable API key. "
        "Open Settings, save a provider, model, and API key, and I can continue from there."
    )


def _clean_provider_failure_summary(
    self,
    category: str,
    response_language: str | None,
) -> str:
    summary_map: dict[str, tuple[str, str]] = {
        "invalid_key_or_permission": (
            "The provider rejected this turn's API key or permissions.",
            "杩欎釜 provider 鎷掔粷浜嗚繖涓€杞娇鐢ㄧ殑 API key 鎴?permission銆?,
        ),
        "model_unsupported": (
            "The provider reached the endpoint, but this model name is not accepted there.",
            "杩欎釜 provider 鍙互杩為€氾紝浣嗗綋鍓?model name 涓嶈杩欎釜 endpoint 鎺ュ彈銆?,
        ),
        "model_not_found": (
            "The provider reached the gateway, but no available channel matched this model.",
            "杩欎釜 provider 鍙互杩為€氾紝浣?gateway 閲屾病鏈夊彲鐢?channel 鍖归厤褰撳墠 model銆?,
        ),
        "language_corruption": (
            "The provider returned a visibly corrupted coaching reply on this turn.",
            "杩欎釜 provider 鍙揪锛屼絾杩欎竴杞繑鍥炰簡鑲夌溂鍙鐨勪贡鐮佸洖澶嶃€?,
        ),
        "language_probe_inconclusive": (
            "The provider reached the endpoint, but Trainer could not fully verify zh-CN input integrity yet.",
            "杩欎釜 provider 鍙揪锛屼絾 Trainer 杩樹笉鑳藉畬鏁撮獙璇佽繖鏉￠摼璺殑 zh-CN 杈撳叆淇濈湡搴︺€?,
        ),
        "empty_response": (
            "The provider reached the endpoint, but returned no usable visible reply.",
            "杩欎釜 provider 鍙揪锛屼絾娌℃湁杩斿洖鍙敤鐨勫彲瑙佸洖澶嶃€?,
        ),
        "malformed_response": (
            "The endpoint responded, but the payload did not match the configured protocol.",
            "杩欎釜 endpoint 鏈夊搷搴旓紝浣?payload 涓嶇鍚堝綋鍓嶉厤缃殑 protocol銆?,
        ),
        "rate_limit": (
            "The provider rate-limited this turn before Trainer could continue.",
            "杩欎釜 provider 瀵硅繖涓€杞姹傝Е鍙戜簡 rate limit锛孴rainer 鏆傛椂涓嶈兘缁х画銆?,
        ),
        "timeout": (
            "Trainer could not get a response from the provider before the timeout.",
            "Trainer 鍦?timeout 鍓嶆病鏈変粠 provider 鏀跺埌鍝嶅簲銆?,
        ),
        "network": (
            "Trainer could not reach the provider over the network.",
            "Trainer 鐩墠鏃犳硶閫氳繃 network 杩炲埌杩欎釜 provider銆?,
        ),
    }
    english, chinese = summary_map.get(
        category,
        (
            "Trainer is blocked on the provider path for this turn.",
            "Trainer 杩欎竴杞 provider path 鍗′綇浜嗐€?,
        ),
    )
    return _localized_text(english, chinese, response_language)


def _clean_provider_failure_next_step(
    self,
    category: str,
    response_language: str | None,
) -> str:
    next_step_map: dict[str, tuple[str, str]] = {
        "invalid_key_or_permission": (
            "Check the API key or provider permissions, retest the connection, and resend this exact turn.",
            "鍏堟鏌?API key 鎴?provider permission锛岄噸鏂版祴璇曡繛鎺ュ悗鍐嶉噸鍙戣繖涓€杞€?,
        ),
        "model_unsupported": (
            "Switch to a model name that this provider actually supports, retest, and resend this exact turn.",
            "鍏堟崲鎴愯繖涓?provider 鐪熸鏀寔鐨?model name锛岄噸鏂版祴璇曞悗鍐嶉噸鍙戣繖涓€杞€?,
        ),
        "model_not_found": (
            "Pick a channel-backed model at this gateway, retest, and resend this exact turn.",
            "鍏堟崲鎴愯繖涓?gateway 閲岀湡瀹炲彲鐢ㄧ殑 model锛岄噸鏂版祴璇曞悗鍐嶉噸鍙戣繖涓€杞€?,
        ),
        "language_corruption": (
            "Switch provider or gateway first, then resend this same turn after the visible corruption disappears.",
            "鍏堝垏鎹?provider 鎴?gateway锛岀‘璁や贡鐮佹秷澶卞悗鍐嶉噸鍙戣繖涓€杞€?,
        ),
        "language_probe_inconclusive": (
            "Retest with a zh-CN probe before trusting this provider for Chinese coaching turns.",
            "鍏堢敤 zh-CN probe 閲嶆柊娴嬭瘯锛屽啀鎶婅繖涓?provider 鐢ㄤ簬涓枃 coaching銆?,
        ),
        "empty_response": (
            "Retest with a visible-text probe or switch to a model that returns visible text.",
            "鍏堢敤 visible-text probe 閲嶆柊娴嬭瘯锛屾垨鍒囨崲鍒颁細杩斿洖鍙鏂囨湰鐨?model銆?,
        ),
        "malformed_response": (
            "Check that the endpoint really speaks the configured protocol, then retest and resend this exact turn.",
            "鍏堢‘璁よ繖涓?endpoint 鐪熺殑鏀寔褰撳墠閰嶇疆鐨?protocol锛屽啀娴嬭瘯骞堕噸鍙戣繖涓€杞€?,
        ),
        "rate_limit": (
            "Wait briefly, then retry this same turn once the rate limit clears.",
            "鍏堢瓑涓€浼氬効锛岀瓑 rate limit 杩囧幓鍚庡啀閲嶈瘯杩欎竴杞€?,
        ),
        "timeout": (
            "Retry once after checking provider latency or gateway load.",
            "鍏堟鏌?provider 寤惰繜鎴?gateway 璐熻浇锛屽啀閲嶈瘯杩欎竴杞€?,
        ),
        "network": (
            "Check the network path or proxy settings, then resend this exact turn.",
            "鍏堟鏌?network 璺緞鎴?proxy 璁剧疆锛屽啀閲嶅彂杩欎竴杞€?,
        ),
    }
    english, chinese = next_step_map.get(
        category,
        (
            "Repair the provider path, then resend this exact coaching turn.",
            "鍏堜慨濂?provider path锛屽啀閲嶅彂杩欎竴杞?coaching銆?,
        ),
    )
    return _localized_text(english, chinese, response_language)


def _clean_provider_failure_reply(
    self,
    category: str,
    detail: str | None,
    response_language: str | None,
) -> str:
    detail_text = _compact_text(detail)
    summary = self.provider_failure_summary(category, response_language)
    next_step = self.provider_failure_next_step(category, response_language)
    if _prefers_chinese(response_language):
        lines = [
            "Trainer 褰撳墠鍗″湪 provider path锛屾墍浠ヨ繖杞?coaching 杩樹笉鑳界户缁€?,
            "",
            summary,
        ]
        if detail_text:
            lines.append(f"璇︽儏锛歿detail_text}")
        lines.append(f"涓嬩竴姝ワ細{next_step}")
        return "\n".join(lines)
    if detail_text:
        return (
            "Trainer is blocked on the provider path, so I cannot continue this coaching turn yet.\n\n"
            f"{summary}\nDetail: {detail_text}\nNext: {next_step}"
        )
    return (
        "Trainer is blocked on the provider path, so I cannot continue this coaching turn yet.\n\n"
        f"{summary}\nNext: {next_step}"
    )


setattr(ProviderService, "_onboarding_reply", _clean_provider_service_onboarding_reply)
setattr(ProviderService, "_error_reply", _clean_provider_service_error_reply)
setattr(ProviderService, "_missing_api_key_reply", _clean_provider_service_missing_api_key_reply)
setattr(ProviderService, "provider_failure_summary", _clean_provider_failure_summary)
setattr(ProviderService, "provider_failure_next_step", _clean_provider_failure_next_step)
setattr(ProviderService, "provider_failure_reply", _clean_provider_failure_reply)
