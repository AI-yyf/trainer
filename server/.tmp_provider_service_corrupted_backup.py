from __future__ import annotations

import json
import re
import socket
from contextvars import ContextVar
from importlib import import_module
from time import monotonic
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from ..core.models import (
    ProviderConfig,
    ProviderModelTokenLimit,
    ProviderModelsResponse,
    ProviderTestResponse,
    UserProfile,
)
from ..training.subject_taxonomy import classify_learning_subject
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

DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS = 45.0
DEFAULT_OPENAI_CLIENT_MAX_RETRIES = 0
MIN_OPENAI_CLIENT_TIMEOUT_SECONDS = 5.0


def _compact_text(value: object | None, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 1)].rstrip()}..."


def _as_mapping(value: object | None) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    if value is None:
        return None

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
        except TypeError:
            dumped = model_dump(mode="python")
        if isinstance(dumped, dict):
            return dumped

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        dumped = to_dict()
        if isinstance(dumped, dict):
            return dumped

    model_extra = getattr(value, "model_extra", None)
    if isinstance(model_extra, dict):
        mapped = dict(model_extra)
        for field_name in ("id", "name"):
            field_value = getattr(value, field_name, None)
            if field_value is not None and field_name not in mapped:
                mapped[field_name] = field_value
        return mapped

    if hasattr(value, "__dict__"):
        mapped = {
            key: field_value
            for key, field_value in vars(value).items()
            if not key.startswith("_")
        }
        return mapped or None

    return None


def _positive_int(value: object | None) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else None
    if isinstance(value, str):
        normalized = value.strip().replace("_", "")
        if normalized.isdigit():
            parsed = int(normalized)
            return parsed if parsed > 0 else None
    return None


def _extract_model_token_limit(value: object | None) -> ProviderModelTokenLimit | None:
    record = _as_mapping(value)
    if not record:
        return None

    context_window_tokens = next(
        (
            parsed
            for parsed in (
                _positive_int(record.get("context_window_tokens")),
                _positive_int(record.get("contextWindowTokens")),
                _positive_int(record.get("context_length")),
                _positive_int(record.get("contextLength")),
                _positive_int(record.get("input_token_limit")),
                _positive_int(record.get("inputTokenLimit")),
                _positive_int(record.get("input_tokens")),
            )
            if parsed is not None
        ),
        None,
    )
    max_output_tokens = next(
        (
            parsed
            for parsed in (
                _positive_int(record.get("max_output_tokens")),
                _positive_int(record.get("maxOutputTokens")),
                _positive_int(record.get("output_token_limit")),
                _positive_int(record.get("outputTokenLimit")),
                _positive_int(record.get("max_completion_tokens")),
                _positive_int(record.get("maxCompletionTokens")),
            )
            if parsed is not None
        ),
        None,
    )
    if context_window_tokens is None and max_output_tokens is None:
        return None

    return ProviderModelTokenLimit(
        context_window_tokens=context_window_tokens,
        max_output_tokens=max_output_tokens,
    )


_MOJIBAKE_FALLBACK_MARKERS = (
    "\ufffd",
    "\ue000",
    "\ue1ec",
    "锟",
    "闂",
    "濠",
    "閻",
    "缂",
    "鈧",
    "鐢",
    "鍙",
    "鏂",
    "瀹",
    "涓",
    "浣",
    "璇",
    "骞",
    "搴",
    "绠",
    "鎴",
    "灏",
    "鏄",
    "杩",
    "鍏",
    "鐩",
    "閸",
    "鐠",
    "娑",
)
_LATIN1_MOJIBAKE_PATTERN = re.compile(
    r"(?:[\u00C2\u00C3\u00C4\u00C5\u00C6\u00C7\u00C8\u00C9\u00CF\u00D0\u00E2\u00E3\u00E4\u00E5\u00E6\u00E7\u00E8\u00E9\u00EF\u00F0][\u0080-\u00BF]{1,2}){2,}"
)


def _looks_like_mojibake_text(value: object) -> bool:
    text = str(value or "")
    return any(marker in text for marker in _MOJIBAKE_FALLBACK_MARKERS) or bool(
        _LATIN1_MOJIBAKE_PATTERN.search(text)
    )


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
    "只用简体中文回答一句话，并完整保留“先学再测”和“VS Code”。不要解释，不要加引号。"
)
_NATURAL_LANGUAGE_PROBE_FRAGMENTS = ("先学再测", "VS Code")
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


_LEADING_HTML_SHELL_PATTERN = re.compile(
    r"^\s*(?:<!doctype\s+html\b[\s\S]*?</html>|<html\b[\s\S]*?</html>)\s*",
    re.IGNORECASE,
)
_PROVIDER_HTML_SHELL_MARKERS = (
    '<div id="root"></div>',
    "<div id='root'></div>",
    '<div id="app"></div>',
    "<div id='app'></div>",
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
    return marker_hits >= 1 or ("<head" in lowered and "<body" in lowered)


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


def _malformed_provider_html_shell_detail() -> str:
    return (
        "Provider returned an HTML app shell instead of a chat payload. "
        "Check the base URL and protocol."
    )


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


def _agentic_has_grounded_resource_evidence(tool_events: list[dict[str, Any]]) -> bool:
    grounded_tool_names = {"search_resources", "read_workspace_file"}
    for event in tool_events:
        if not isinstance(event, dict):
            continue
        name = str(event.get("name") or "").strip()
        if name in grounded_tool_names:
            return True
    return False


def _agentic_recoverable_grounded_stop_reason(stop_reason: object) -> str:
    normalized = str(stop_reason or "").strip()
    return normalized if normalized in {"max_steps", "no_progress"} else ""


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
        or "\u95ee\u53f7" in visible
        or "\u4e71\u7801" in visible
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


def _wrong_language_cjk_reply_detail(
    reply: str,
    *,
    response_language: str | None = None,
) -> str | None:
    if _prefers_chinese(response_language):
        return None
    visible = _compact_visible_text(reply, limit=480)
    if not visible or not _contains_cjk(visible):
        return None
    cjk_count = sum(1 for char in visible if "\u3400" <= char <= "\u9fff")
    latin_count = sum(1 for char in visible if char.isascii() and char.isalpha())
    if cjk_count < 12:
        return None
    if latin_count > 0 and cjk_count < latin_count * 2:
        return None
    return (
        "The provider returned a coaching reply in the wrong language. Trainer cannot "
        "trust this text as a clean coaching turn."
    )


def _mixed_script_reply_corruption_detail(
    reply: str,
    *,
    message: str | None = None,
    response_language: str | None = None,
) -> str | None:
    visible = _compact_visible_text(reply, limit=480)
    if _looks_like_mojibake_text(visible):
        return (
            "The provider returned mojibake-corrupted text in the visible coaching reply. "
            "Trainer cannot trust this text as a clean coaching turn."
        )
    fragments = _mixed_script_corruption_fragments(reply, message=message)
    if fragments:
        return (
            "The provider returned suspicious mixed-script fragments in an otherwise readable "
            "coaching reply. Trainer cannot trust this text as a clean coaching turn."
        )
    wrong_language_detail = _wrong_language_cjk_reply_detail(
        reply,
        response_language=response_language,
    )
    if wrong_language_detail:
        return wrong_language_detail
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
                "这个 provider 拒绝了这轮请求使用的 API key 或 permission。",
            ),
            "model_unsupported": (
                "The provider reached the endpoint, but this model name is not accepted there.",
                "这个 provider 可以连通，但当前 model name 不被这个 endpoint 接受。",
            ),
            "model_not_found": (
                "The provider reached the gateway, but no available channel matched this model.",
                "这个 provider 可以连通，但 gateway 里没有可用 channel 能匹配当前 model。",
            ),
            "language_corruption": (
                "The provider returned a visibly corrupted coaching reply on this turn.",
                "这个 provider 可达，但这一轮返回了肉眼可见的乱码回复。",
            ),
            "malformed_response": (
                "The endpoint responded, but the payload was not a valid OpenAI-compatible response.",
                "这个 endpoint 有响应，但返回 payload 不是有效的 OpenAI-compatible response。",
            ),
            "rate_limit": (
                "The provider rate-limited this turn before Trainer could continue.",
                "这个 provider 对这轮请求触发了 rate limit，Trainer 暂时无法继续。",
            ),
            "timeout": (
                "Trainer could not get a response from the provider before the timeout.",
                "Trainer 在超时前没有从 provider 收到响应。",
            ),
            "network": (
                "Trainer could not reach the provider over the network.",
                "Trainer 目前无法通过 network 连到这个 provider。",
            ),
        }
        english, chinese = summary_map.get(
            category,
            (
                "Trainer is blocked on the provider path for this turn.",
                "Trainer 这轮被 provider path 卡住了。",
            ),
        )
        return _localized_text(english, chinese, response_language)

    def provider_failure_next_step(self, category: str, response_language: str | None) -> str:
        next_step_map: dict[str, tuple[str, str]] = {
            "invalid_key_or_permission": (
                "Check the API key or provider permissions, retest the connection, and resend this exact turn.",
                "先检查 API key 或 provider permission，重新测试连接后再重发这一轮。",
            ),
            "model_unsupported": (
                "Switch to a model name that this provider actually supports, retest, and resend this exact turn.",
                "先换成这个 provider 真的支持的 model name，重新测试后再重发这一轮。",
            ),
            "model_not_found": (
                "Pick a channel-backed model at this gateway, retest, and resend this exact turn.",
                "先换成这个 gateway 里真的有 channel 的 model，重新测试后再重发这一轮。",
            ),
            "language_corruption": (
                "Switch provider or gateway first, then resend this same turn after the visible corruption disappears.",
                "先切换 provider 或 gateway，确认乱码消失后再重发这一轮。",
            ),
            "malformed_response": (
                "Check that the endpoint really speaks the OpenAI-compatible protocol, then retest and resend this exact turn.",
                "先确认这个 endpoint 真的返回 OpenAI-compatible protocol，再测试并重发这一轮。",
            ),
            "rate_limit": (
                "Wait briefly, then retry this same turn once the rate limit clears.",
                "先等一会儿，等 rate limit 过去后再重试这一轮。",
            ),
            "timeout": (
                "Retry once after checking provider latency or gateway load.",
                "先检查 provider 延迟或 gateway 负载，再重试这一轮。",
            ),
            "network": (
                "Check the network path or proxy settings, then resend this exact turn.",
                "先检查 network 路径或 proxy 设置，再重发这一轮。",
            ),
        }
        english, chinese = next_step_map.get(
            category,
            (
                "Repair the provider path, then resend this exact coaching turn.",
                "先修好 provider path，再重发这一轮 coaching。",
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
                "invalid_key_or_permission": "先检查 API key / permission 是否有效。",
                "malformed_response": "先确认 endpoint 真正返回的是 OpenAI-compatible protocol。",
                "rate_limit": "先等一会儿，再重试同一轮。",
                "model_unsupported": "先换一个这个 provider 支持的 model name。",
            }.get(category, "先修复 provider path，再重试同一轮。")
            lines = [
                "Trainer 目前卡在 provider path，暂时无法继续这轮 coaching。",
                "",
                category_hint,
            ]
            if detail_text:
                lines.append(f"详情: {detail_text}")
            lines.append("下一步：先把 provider 恢复到可用状态，再重新发送这轮。")
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
            self._client = async_openai_cls(
                api_key=self._api_key,
                base_url=base_url,
                timeout=self._provider_client_timeout_seconds(),
                max_retries=self._provider_client_max_retries(),
            )
        return self._client

    def _create_sync_client(self, provider: ProviderConfig, api_key: str) -> Any:
        openai_cls = self._get_sync_openai_class()
        return openai_cls(
            api_key=api_key,
            base_url=self._normalized_openai_compatible_base_url(provider),
            timeout=self._provider_client_timeout_seconds(provider),
            max_retries=self._provider_client_max_retries(provider),
        )

    def _provider_request_defaults(self, provider: ProviderConfig | None = None) -> dict[str, Any]:
        config = provider or self._config
        if config is None:
            return {}
        defaults = getattr(config, "request_defaults", None)
        if not isinstance(defaults, dict):
            return {}
        return dict(defaults)

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

    def _provider_client_timeout_seconds(self, provider: ProviderConfig | None = None) -> float:
        defaults = self._provider_request_defaults(provider)
        for key in (
            "clientTimeoutSeconds",
            "client_timeout_seconds",
            "timeoutSeconds",
            "timeout_seconds",
            "timeout",
        ):
            resolved = self._request_default_number(defaults.get(key))
            if resolved is not None:
                return max(MIN_OPENAI_CLIENT_TIMEOUT_SECONDS, resolved)
        return DEFAULT_OPENAI_CLIENT_TIMEOUT_SECONDS

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
        model_token_limits: dict[str, ProviderModelTokenLimit] | None = None,
    ) -> ProviderModelsResponse:
        unique_models = sorted({model for model in models if model}, key=str.lower)
        resolved = self._resolve_model_from_list(provider.model, unique_models)
        resolved_from_input = bool(resolved and resolved != provider.model)
        normalized_model_token_limits = {
            model_name: limit
            for model_name, limit in (model_token_limits or {}).items()
            if model_name in unique_models
        }
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
            model_token_limits=normalized_model_token_limits,
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
        model_token_limits: dict[str, ProviderModelTokenLimit] = {}
        for item in body.get("data") or []:
            if not isinstance(item, dict):
                continue
            model_id = self._normalize_model_id(item.get("id"))
            if model_id:
                models.append(model_id)
                token_limit = _extract_model_token_limit(item)
                if token_limit is not None:
                    model_token_limits[model_id] = token_limit
        return self._models_response_from_ids(
            provider,
            models,
            diagnostics=diagnostics,
            model_token_limits=model_token_limits,
        )

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
        model_token_limits: dict[str, ProviderModelTokenLimit] = {}
        for item in body.get("models") or []:
            if not isinstance(item, dict):
                continue
            raw_name = self._normalize_model_id(item.get("name"))
            if not raw_name:
                continue
            model_id = raw_name.removeprefix("models/")
            models.append(model_id)
            token_limit = _extract_model_token_limit(item)
            if token_limit is not None:
                model_token_limits[model_id] = token_limit
        return self._models_response_from_ids(
            provider,
            models,
            diagnostics=diagnostics,
            model_token_limits=model_token_limits,
        )

    def _openai_list_models(self, provider: ProviderConfig, api_key: str) -> ProviderModelsResponse:
        client = self._create_sync_client(provider, api_key)
        response = client.models.list()
        models: list[str] = []
        model_token_limits: dict[str, ProviderModelTokenLimit] = {}

        for item in response:
            model_id = self._normalize_model_id(getattr(item, "id", None))
            if model_id:
                models.append(model_id)
                token_limit = _extract_model_token_limit(item)
                if token_limit is not None:
                    model_token_limits[model_id] = token_limit

        return self._models_response_from_ids(
            provider,
            models,
            diagnostics=[f"Using OpenAI-compatible model listing for provider {provider.name}."],
            model_token_limits=model_token_limits,
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
                    "自然中文探测通过了：虽然严格回显探测不稳定，但这条连接仍能输出可用的中文教学句子。",
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
                            f"语言完整性探测在连通性成功后没能完成。后续检查失败：{exc}",
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
                                "语言完整性探测在连通性成功后没有拿到可见内容。"
                                "Trainer 现在还不能验证这条链路上的非 English 输入。"
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
                            "这个 provider 可达，但在模型看到之前就把当前这条混合语言教学消息变成了一串问号。",
                            response_language,
                        )
                    else:
                        detail = _localized_text(
                            (
                                "Provider reachable, but it corrupted Chinese input into question marks "
                                "before the model saw it."
                            ),
                            "这个 provider 可达，但在模型看到消息之前把中文输入变成了一串问号。",
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
                        "语言完整性探测没有通过。provider 虽然回复了，"
                        "但没有把基于当前消息生成的探测文本完整保留下来，Trainer 还不能信任这条链路。"
                        if probe_kind == "message"
                        else (
                            "语言完整性探测没有通过。provider 虽然回复了，"
                            "但没有把混合语言探测文本完整保留下来，Trainer 还不能信任这条链路。"
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
                "语言完整性探测通过了：基于当前消息生成的探测文本和 mixed CJK/ASCII 探测文本都被完整保留下来了。"
                if message_probe is not None or _prefers_chinese(response_language)
                else "语言完整性探测通过了：mixed CJK/ASCII 探测文本在所有检查里都被完整保留下来了。"
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
        if _looks_like_mojibake_text(reply):
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
                "当前这轮我仍然保留在 VS Code remote 这条主线里。",
                response_language,
            )
        if normalized == "debug_loop":
            return _localized_text(
                "I am still keeping this turn in the VS Code debug lane.",
                "当前这轮我仍然保留在 VS Code debug 这条主线里。",
                response_language,
            )
        if normalized == "function_guidance":
            return _localized_text(
                "I am still keeping this turn in the function-guidance lane.",
                "当前这轮我仍然保留在 function-guidance 这条主线里。",
                response_language,
            )
        if normalized == "project_adaptation":
            return _localized_text(
                "I am still keeping this turn in the existing-project adaptation lane.",
                "当前这轮我仍然保留在 existing-project adaptation 这条主线里。",
                response_language,
            )
        return ""

    def language_corruption_summary(
        self,
        response_language: str | None,
        scenario: str | None = None,
    ) -> str:
        if reason == "reanchor":
        summary = _localized_text(
            f"I kept this turn inside {spec['lane_en']}.",
            f"这一轮我继续留在{spec['lane_zh']}里。",
            response_language,
        )
    else:
        summary = _localized_text(
            f"{summary_prefix[0]}, so I kept this turn inside {spec['lane_en']}.",
            f"{summary_prefix[1]}锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦ㄤ簡{spec['lane_zh']}銆?",
            response_language,
        )
    next_step = _localized_text(spec["next_en"], spec["next_zh"], response_language)
    teaching_note = _localized_text(spec["note_en"], spec["note_zh"], response_language)
    if reason == "reanchor":
        reply = _localized_text(
            f"I will keep this turn inside one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"这一轮我先用一个更小的{spec['unit_zh']}把它接住。\n\n下一步：{next_step}",
            response_language,
        )
    else:
        reply = _localized_text(
            f"{reply_prefix[0]}, so I will keep the work alive with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"{reply_prefix[1]}锛屾墍浠ユ垜鍏堢敤涓€涓洿灏忕殑{spec['unit_zh']}鎶婅繖涓€杞帴浣忋€俓n\n涓嬩竴姝ワ細{next_step}",
            response_language,
        )
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
        grounded_resource_evidence = _agentic_has_grounded_resource_evidence(tool_events)
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
        recoverable_grounded_stop_reason = (
            _agentic_recoverable_grounded_stop_reason(result.stop_reason)
            if grounded_resource_evidence
            else ""
        )
        if recoverable_grounded_stop_reason:
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
                and plain_stop_reason not in {"empty_response", "max_steps", "no_progress"}
            ):
                final_text = plain_reply
                result.stop_reason = "completed"
                result.summary = None
                result.next_step = None
                result.resume_thread = None
                recovered_stop_reason = recoverable_grounded_stop_reason
                fell_back = True
        if str(result.stop_reason or "").strip() == "timeout":
            timeout_recovery = _build_timeout_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(timeout_recovery, dict):
                result.summary = timeout_recovery.get("summary") or result.summary
                result.next_step = timeout_recovery.get("next_step") or result.next_step
                result.teaching_note = (
                    timeout_recovery.get("teaching_note")
                    or getattr(result, "teaching_note", None)
                )
                result.resume_thread = timeout_recovery.get("resume_thread") or _agentic_resume_thread_text(
                    result.summary,
                    result.next_step,
                    response_language=response_language,
                )
                timeout_reply = str(timeout_recovery.get("reply") or "").strip()
                if timeout_reply:
                    final_text = timeout_reply
                fell_back = True
        if str(result.stop_reason or "").strip() == "provider_error":
            provider_error_recovery = _build_provider_error_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
                error_detail=getattr(result, "error", None),
            )
            result.summary = provider_error_recovery.get("summary") or result.summary
            result.next_step = provider_error_recovery.get("next_step") or result.next_step
            result.teaching_note = (
                provider_error_recovery.get("teaching_note")
                or getattr(result, "teaching_note", None)
            )
            result.resume_thread = provider_error_recovery.get("resume_thread") or _agentic_resume_thread_text(
                result.summary,
                result.next_step,
                response_language=response_language,
            )
            provider_error_reply = str(provider_error_recovery.get("reply") or "").strip()
            if provider_error_reply:
                final_text = provider_error_reply
            fell_back = True
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
        final_text = self._sanitize_agentic_visible_reply(
            final_text,
            profile=profile,
            message=message,
            current_file=current_file,
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
        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario") or "").strip()
        history_mode = str(context.get("history_mode") or "").strip().lower()
        chinese = _prefers_chinese(response_language)
        summary_before_visible = str(result.summary or "").strip()
        next_step_before_visible = str(result.next_step or "").strip()
        if str(result.summary or "").strip():
            result.summary = _sanitize_agentic_continuity_text(
                str(result.summary or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="summary",
                response_language=response_language,
                coach_context=context,
            )
        if str(result.next_step or "").strip():
            result.next_step = _sanitize_agentic_continuity_text(
                str(result.next_step or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="next_step",
                response_language=response_language,
                coach_context=context,
            )
        summary_changed_for_visible = str(result.summary or "").strip() != summary_before_visible
        next_step_changed_for_visible = str(result.next_step or "").strip() != next_step_before_visible
        if (
            not str(getattr(result, "resume_thread", "") or "").strip()
            or summary_changed_for_visible
            or next_step_changed_for_visible
        ):
            result.resume_thread = _agentic_resume_thread_text(
                result.summary,
                result.next_step,
                response_language=response_language,
            )
        if str(getattr(result, "resume_thread", "") or "").strip():
            sanitized_resume_thread = _sanitize_agentic_continuity_text(
                str(getattr(result, "resume_thread", "") or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="resume_thread",
                response_language=response_language,
                coach_context=context,
            )
            if summary_changed_for_visible or next_step_changed_for_visible:
                result.resume_thread = _normalize_visible_resume_thread_text(
                    sanitized_resume_thread,
                    chinese=chinese,
                )
            else:
                result.resume_thread = sanitized_resume_thread
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
        stop_reason = str(final_event.get("stop_reason") or "").strip()
        grounded_resource_evidence = _agentic_has_grounded_resource_evidence(tool_events)
        needs_empty_response_recovery = not content.strip() and stop_reason == "empty_response"
        needs_timeout_recovery = stop_reason == "timeout"
        needs_provider_error_recovery = stop_reason == "provider_error"
        recoverable_grounded_stop_reason = (
            _agentic_recoverable_grounded_stop_reason(stop_reason)
            if grounded_resource_evidence
            else ""
        )
        needs_grounded_stop_recovery = bool(recoverable_grounded_stop_reason)
        if (
            not needs_empty_response_recovery
            and not needs_grounded_stop_recovery
            and not needs_timeout_recovery
            and not needs_provider_error_recovery
        ):
            return final_event
        if needs_timeout_recovery:
            timeout_recovery = _build_timeout_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(timeout_recovery, dict):
                final_event["content"] = str(timeout_recovery.get("reply") or content).strip()
                final_event["summary"] = timeout_recovery.get("summary")
                final_event["next_step"] = timeout_recovery.get("next_step")
                final_event["teaching_note"] = timeout_recovery.get("teaching_note")
                final_event["resume_thread"] = timeout_recovery.get("resume_thread")
                final_event["fell_back"] = True
            return final_event
        if needs_provider_error_recovery:
            provider_error_recovery = _build_provider_error_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
                error_detail=str(final_event.get("error") or "").strip() or None,
            )
            final_event["content"] = str(provider_error_recovery.get("reply") or content).strip()
            final_event["summary"] = provider_error_recovery.get("summary")
            final_event["next_step"] = provider_error_recovery.get("next_step")
            final_event["teaching_note"] = provider_error_recovery.get("teaching_note")
            final_event["resume_thread"] = provider_error_recovery.get("resume_thread")
            final_event["fell_back"] = True
            return final_event
        if needs_empty_response_recovery and tool_events:
            return final_event

        if needs_empty_response_recovery and loop is not None and messages is not None:
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
            and plain_stop_reason not in {"empty_response", "max_steps", "no_progress"}
        ):
            final_event["content"] = plain_reply
            final_event["stop_reason"] = "completed"
            final_event["summary"] = None
            final_event["next_step"] = None
            final_event["resume_thread"] = None
            if needs_grounded_stop_recovery:
                final_event["recovered_stop_reason"] = recoverable_grounded_stop_reason
                final_event["fell_back"] = True
            return final_event
        if needs_grounded_stop_recovery:
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
        content = self._sanitize_agentic_visible_reply(
            str(final_event.get("content") or ""),
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        final_event["content"] = content
        if str(final_event.get("summary") or "").strip():
            final_event["summary"] = _strip_internal_coach_meta(str(final_event.get("summary") or ""))
        if str(final_event.get("next_step") or "").strip():
            final_event["next_step"] = _strip_internal_coach_meta(str(final_event.get("next_step") or ""))
        if str(final_event.get("resume_thread") or "").strip():
            final_event["resume_thread"] = _visible_model_text(
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
        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario") or "").strip()
        history_mode = str(context.get("history_mode") or "").strip().lower()
        chinese = _prefers_chinese(response_language)
        summary_before_visible = str(final_event.get("summary") or "").strip()
        next_step_before_visible = str(final_event.get("next_step") or "").strip()
        if str(final_event.get("summary") or "").strip():
            final_event["summary"] = _sanitize_agentic_continuity_text(
                str(final_event.get("summary") or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="summary",
                response_language=response_language,
                coach_context=context,
            )
        if str(final_event.get("next_step") or "").strip():
            final_event["next_step"] = _sanitize_agentic_continuity_text(
                str(final_event.get("next_step") or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="next_step",
                response_language=response_language,
                coach_context=context,
            )
        summary_changed_for_visible = (
            str(final_event.get("summary") or "").strip() != summary_before_visible
        )
        next_step_changed_for_visible = (
            str(final_event.get("next_step") or "").strip() != next_step_before_visible
        )
        if (
            not str(final_event.get("resume_thread") or "").strip()
            or summary_changed_for_visible
            or next_step_changed_for_visible
        ):
            final_event["resume_thread"] = _agentic_resume_thread_text(
                final_event.get("summary"),
                final_event.get("next_step"),
                response_language=response_language,
            )
        if str(final_event.get("resume_thread") or "").strip():
            sanitized_resume_thread = _sanitize_agentic_continuity_text(
                str(final_event.get("resume_thread") or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="resume_thread",
                response_language=response_language,
                coach_context=context,
            )
            if summary_changed_for_visible or next_step_changed_for_visible:
                final_event["resume_thread"] = _normalize_visible_resume_thread_text(
                    sanitized_resume_thread,
                    chinese=chinese,
                )
            else:
                final_event["resume_thread"] = sanitized_resume_thread

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
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎妯恍氱紓鍌氬€烽懗鑸垫叏闁垮绠鹃柍褜鍓熼弻鈥崇暆閳ь剟宕伴弽褏鏆︽繝濠傛－濡查箖鏌ｉ姀鈺佺仭闁烩晩鍨跺璇测槈濮橈絽浜鹃柨婵嗗暙婵″ジ鏌嶈閸撴氨鎹㈤崼婵愬殨濠电姵鑹鹃崡鎶芥煟閺冨洦顏犳い鏃€娲熷铏圭磼濡搫袝闂佸憡鎸诲畝鎼佸箖閻㈢绫嶉柛顐ゅ暱閹锋椽姊虹涵鍛汗闁稿绋掓穱濠冪附閸涘﹦鍘辨繝鐢靛Т閸婂綊宕戦妷褉鍋撳▓鍨灕妞ゆ泦鍥х叀濠㈣埖鍔曢悡鎴︽煃鐟欏嫬鍔ゅù婊堢畺閺屻劑寮撮悙娴嬪亾閸濄儳涓嶉柨婵嗘缁♀偓闂傚倸鐗婄粙鎺楀闯娴犲鐓涘ù锝呮贡婢ь剙菐閸パ嶈含闁诡喗鐟╅、鏃堝礋閵娿儰澹曢梺鍦濠㈡﹢鎮挎ィ鍐╃厽婵☆垱顑欓崵娆戠磽娴ｅ弶娅婄€殿喖鐖煎畷鐓庮潩椤撶喓褰嗛柣搴ゎ潐濞叉牕顕ｉ崜浣瑰床婵炴垯鍨圭粻锝嗙箾閸℃绠冲ù鐘哄亹缁辨挻鎷呴崫鍕碘偓鎾剁磽瀹ュ嫮绐旂€殿喖顭烽弫鎰緞婵犲嫮鏉告俊鐐€栭悧妤€顫濋妸銉愭帡濮€閵堝棌鎷洪梺鍛婄☉閿曘儵鎮￠敐澶嬬厱婵°倐鍋撻柛鐔锋健閿?",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎娆戠┛闂傚倷绶氶埀顒傚仜閼活垱鏅堕崜褏纾奸柣妯挎珪鐏忣參鏌ｉ敐澶嬫暠缂佽櫣鏅划娆戞嫚娣囧崬濡介柕鍥у瀵噣宕堕‖顔芥尰缁绘盯宕ㄩ鐘测叺濠殿喖锕︾划顖炲箯閸涘瓨鎯炴鐐茬氨閸嬫挻绻濋崶銊у幈闂佽鍎抽顓犵不濡偐纾兼い鏃傛櫕閹冲洦顨ラ悙鏉戠瑨閾绘牠鏌嶈閸撶喎鐣烽妷銊ｄ汗闁圭儤鎸搁埀顒€鐖奸弻锝夊箛椤栨稓銆愰梺瀹狀嚙缁绘﹢寮婚敓鐘茬闁靛ě鍐炬澑闂備礁鎼幊蹇涙偂閿熺姴钃熸繛鎴炃氬Σ鍫ユ煕濡ゅ啫浠滅紒鐘叉惈閳规垿鎮欓懠顒€顤€闂佺粯鎸撮埀顒佸墯濞兼牠鏌ц箛鎾磋础闁活厽鐟︾换娑㈠幢濡搫濮㈤梺鍛婃惄閸撶喎顫忓ú顏勪紶闁告洦鍓欏▍銈囩磽娓氬洤鏋熼柟鍝ョ帛缁岃鲸绻濋崶銊ヤ缓缂備礁顑堝▔鏇⑺囬弶娆炬富闁靛牆妫涙晶顒佹叏濡濮傛い銏＄懄缁绘繈宕堕妸銉㈠亾閸偒娈介柣鎰皺娴犮垽鏌涢弮鈧畝鎼佸蓟閿濆憘鏃堝焵椤掆偓铻炴繝闈涙閺嗭箓鏌曡箛瀣偓鏇㈡倶閹惰姤鐓欏Λ棰佽兌閸斿秹鎮?",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎妯恍氶梻鍌欒兌椤牏鎮锕€绀夐幖娣妼缁犵喖鏌熼梻瀵割槮缂侇偄绉归弻娑㈩敃閿濆洨鐣奸梺浼欑稻濡炶棄顫忛搹鍦煋闁糕剝顨呴瀛樼箾閸喐顥堥柡宀嬬秮楠炲洭顢楁繝鍛儓闂備礁鎼張顒€煤濡吋宕叉繝闈涳功閻も偓闂佸搫娲ㄦ慨闈涒枔閹间焦鐓熼幖娣焺閸熷繘鏌涢悩宕囧ⅹ妞ゎ厼娲崹楣冨箛娴ｅ湱绋佹繝鐢靛仜濡﹥绂嶅┑瀣庡宕奸悢铏诡啎闂佺懓顕崑鐘崇珶濡眹浜滈柨婵嗘噺閹牊銇勯鍕殻濠碘剝鍎肩粻娑㈠即閻樼數宕堕梻鍌欑閹诧繝銆冮崨鏉戠柈闁秆勵殕閸嬧晠鏌ｉ幋锝嗩棄缂佺媴缍侀弻锝夊箛椤栨氨姣㈢紓浣瑰姉閸嬨倕顫忔ウ瑁や汗闁圭儤鍨抽崰濠囨⒑閸涘鑰跨紒鐘崇墪閻ｇ兘鏁愭径濠傝€垮┑锛勫仧缁垶寮埀顒勬⒒娴ｈ櫣甯涙い顓炴川閸掓帡顢涘锝嗩潔閻熸粌瀛╃粚杈ㄧ節閸ヨ埖鏅濋梺鎸庣箓濞诧箓宕抽銏″€甸柛顭戝亝缁舵煡鎮楀顓熺凡闁伙絿鍏橀幃銏㈠枈鏉堛劍娅囬梻浣虹帛閺屻劑骞夐敓鐘茬骇?",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；婵炴垟鎳為崶顒佸仺缂佸瀵ч悗顒勬⒑閻熸澘鈷旂紒顕呭灦瀹曟垿骞囬悧鍫㈠幈闂佸綊鍋婇崹鎵閿曞倹鐓熼柕蹇嬪灮鐢稑菐閸パ嶈含闁诡喗鐟╅、鏃堝礋閵娿儰澹曢梺鍝勭▉閸樹粙宕戠€ｎ偆绡€濠电姴鍊绘晶鏇犵棯閸撗呭笡缂佺粯鐩獮瀣枎韫囨洑鎮ｉ梻浣规偠閸斿矂宕愰崸妤€钃熸繛鎴炵煯濞岊亪鏌涢幘妞诲亾婵☆偁鍔嶇换娑氣偓娑欘焽閻绱掗鑺ュ磳鐎殿喖顭烽崹楣冨箛娴ｅ憡鍊梻浣告啞閸旀垿宕濆畝鍕ㄢ偓鏍偓锝庡枟閳锋垿姊婚崼鐔衡姇妞ゃ儳鍋ら幃浠嬵敍濞戣鲸鐤佹繝纰夌磿閺佽鐣烽悢纰辨晬婵ê宕獮鎰版⒒娴ｄ警鐒鹃柡鍫墰閸掓帞浠︾粵瀣闂侀潧艌閺呮粓鍩涢幋锔界厱婵犻潧妫楅顐︽煟韫囨稐鎲鹃柡灞剧洴閹晛鐣烽崶褉鎷版俊銈囧Х閸嬫盯宕锔光偓锕傚Ω閳轰胶顦ㄩ梺缁樺姦閸撴瑧绱撻幘缁樷拻濞达綀娅ｉ妴濠囨煕閹惧绠為柍銉畵瀹曞爼顢楅埀顒€效閺屻儲鐓忓璺烘濞呭棝鏌嶉柨瀣瑨闂囧鏌ㄥ┑鍡樺櫤闁哥喓鍋ら弻娑㈡偄閸濆嫪妲愰梺鍝勬湰閻╊垰顕ｉ鍌涘磯闁靛ě灞芥櫔闂佽姘﹂～澶娒哄鈧畷褰掑锤濡ゅ啫绁﹀┑鈽嗗灥閸嬫劗澹曢崗闂寸箚妞ゆ牜鍋為弫閬嶆倵濮樿櫕顥夐柍瑙勫灴閹瑩鎳滈棃娑欓敪缂傚倸鍊哥粔顕€宕戦幘鎰佹富闁靛牆楠告禍婊勩亜閿曞倹娑ч柣锝囧厴楠炲鏁傞挊澶夋睏缂傚倸鍊烽悞锕傗€﹂崶顒€鍌ㄩ梺顒€绉甸悡娆撴煠閸︻厼顣肩憸鎶婂懐纾奸棅顐幘閻瑧鈧娲樼换鍕焵椤掑﹦绉甸柛鎾寸〒婢规洘绺介崨濠勫幈闁诲繒鍋熼崑鎾绘儍閹达箑鏋侀柛顐犲劜閸婄敻鎮峰▎蹇擃仾缂佲偓閳ь剟姊洪棃娑氬ⅱ妞ゎ厼鐗撻、姘舵晲婢跺﹦顔掑銈嗘濡嫰鍩€椤掑倸鍘撮柟顔款潐閵堬箓骞愭惔顔诲摋闂?",
            "濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻鐔虹磼閵忕姵鐏嶉梺绋块椤︻垶鈥﹂崸妤佸殝闂傚牊绋戦～宀€绱撴担鍝勭彙闁搞儜鍜佸晣闂佽瀛╃粙鎺曟懌闁诲繐娴氶崢濂告箒濠电姴锕ら幊搴㈢閹灔搴ㄥ炊瑜濋煬顒€鈹戦垾宕囧煟鐎规洜鍠栭、姗€鎮欏顔锯偓鎾⒒閸屾瑧顦﹂柟璇х節閹兘濡疯瀹曞弶鎱ㄥ璇蹭壕閻庢鍠栭…鐑藉箖閵忋倖鎯為柛锔诲弿缁辨煡姊绘笟鈧褏鎹㈤幒鎾村弿闁汇垹鎲￠崐鍓佲偓骞垮劚椤︿即鍩涢幋鐘电＜閻庯綆浜炴禒銏°亜閹哄鐏柕鍥у婵℃悂濡烽敃鈧▓妤佺節绾版ê澧查柟鍛婂▕閻涱噣骞掑Δ鈧粻锝嗐亜閹捐泛鏋庨柛蹇擄躬濮婄粯鎷呴悷閭﹀殝缂備浇顕ч崐鍧楃嵁婵犲偆鍚嬮柛鈩冪懅瑜伴箖姊洪崫鍕偍闁搞劍妞介崺娑㈠箳閹炽劌缍婇弫鎰板炊閳哄倹鍟掗梻浣规偠閸婃洟宕幘顔艰摕婵炴垟鎳囬埀顒婄畵楠炲鈹戦崼婊勵敇闂傚倷娴囬鏍窗濮樿泛纾婚柕鍫濐槸閺嬩線鏌涢幇闈涙灈闁绘帒鐏氶妵鍕箳閹存繍浼岄梺杞扮椤戝寮婚弴鐔风窞闁糕剝蓱閻濇梻绱撴担鎻掍壕闁诲函缍嗛崑浣圭濠婂牊鐓欓柟顖嗗苯娈堕梺瀹犳椤︻垶婀佸┑鐘诧工閻楀繘鎮惧ú顏呯厸閻忕偠顕ф俊濂告煃鐟欏嫬鐏寸€规洖宕埥澶愬箥娴ｉ晲澹曞┑掳鍊曢幊蹇涙偂閺囩喍绻嗘い鏍ㄧ矌鐢盯鎮樿箛銉х暤闁哄备鈧磭鏆嗛悗锝庡墰閿涚喖姊洪柅鐐茶嫰婢у墽绱撳鍛棦鐎规洘鍨垮畷鍗炍熺紒妯煎娇闂備礁澹婇悡鍫ュ磻閸涙潙鐭楅煫鍥ㄦ尨閺€浠嬫煟濡绲婚柡鍡欏仱閺屾洟宕堕妸褏鐤勯梺鍝勭焿缁辨洘绂掗敃鍌涘殟闁靛鍎查悾濠氭⒒娴ｇ瓔鍤冮柛鐘愁殜閹兘鍩￠崨顓犵枃闂佺粯锚閻忔艾鐣锋径濞库偓鎺戭潩閻撳海浠х紓浣介哺濮婂湱鎹㈠┑瀣仺闂傚牊鍒€濞戙垺鐓欑€瑰嫭婢橀弳鐔访归悪鍛暤闁诡喖澧芥禒锕傛偂鎼粹槅鍤欑紓?",
            "婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ幋锝嗩棄闁哄绶氶弻娑樷槈濮楀牊鏁鹃梺鍛婄懃缁绘﹢寮婚敐澶婄婵犲灚鍔栫紞妤呮⒑闁偛鑻晶顕€鏌涙繝鍌涘仴妤犵偞鍔栫换婵嬪礃椤忓棗楠勯梻浣稿暱閹碱偊顢栭崶鈺冪煋妞ゆ棃鏁崑鎾舵喆閸曨剛锛橀梺鍛婃⒐閸ㄧ敻顢氶敐澶婇唶闁哄洨鍋熼娲⒑缂佹鎳冮柟铏姍閻涱噣濮€閵堝棌鎷婚梺绋挎湰閻熝呯玻閺冨牊鐓冪憸婊堝礈濞戙垹纾绘繛鎴欏灪閸ゆ劖銇勯弽銊р姇婵炲懐濞€閺岀喓绱掗姀鐘崇亶闂佺粯鎸婚惄顖炲箖濮椻偓閹瑩骞撻幒鍡樺瘱闂備線娼уΛ娆戞暜閿熺姴钃熺€广儱鐗滃銊╂⒑閸涘﹥灏柛鏂挎捣濡叉劙鎮欓崫鍕€垮┑鐐村灦椤洭鏁嶅☉銏♀拺闁告稑锕ｇ欢閬嶆煕濮椻偓缁犳牕顕ｉ幎鑺ユ櫆闂佹鍨版禍楣冩煕韫囨搩妲稿ù婊堢畺濮婃椽宕ㄦ繝鍐槱闂佸憡鎸婚惄顖氱暦閵忋倕绠瑰ù锝囨嚀閳ь剛鏁婚弻娑滅疀閹垮啯笑婵炲瓨绮撶粻鏍蓟閿濆棙鍎熸い鏍ㄧ矌鏍￠梻浣告啞閹稿鎯勯鐐叉瀬鐎广儱顦伴崑鍕煕濠靛嫬鍔ゆい鏃€娲熼弻锝嗘償閿濆棙姣勫銈庡幖閻楁捇銆侀幘璇茬闁哄倶鍎查弬鈧梻浣哄仺閸庢潙鈻嶉弴銏犵獥婵☆垱妞垮▓浠嬫煟閹邦垰鐨虹紒鐘差煼閺岀喖顢欑憴鍕彇闂佸綊顥撴繛鈧柟宕囧█椤㈡寰勬繝鍐╂緫闂傚倸鍊搁崐椋庣矆娴ｉ潻鑰块梺顒€绉寸壕鍧楁煏閸繍妲搁柡鍕╁劦閺屾盯顢曢敐鍥╊吋闂佺粯甯熸慨銈夊箞閵娿儙鐔稿緞缁嬫寧鍎撶紓浣瑰劤瑜扮偟鍒掑▎鎾宠摕婵炴垶鐭▽顏堟煙鐟欏嫬濮囨い銉︾箞濮婃椽鏌呴悙鑼跺濠⒀傚嵆閺屾稖绠涢弮鎾光偓鎸庮殽閻愭彃鏆ｉ柟顔界懇閹粌螣缂佹褰囬梻鍌欒兌椤牓寮甸浣衡攳婵炲樊浜滅粻娲煛閸ャ儱鐏柍閿嬪灴濮婂宕奸悢宄扮闂佸壊鍋侀崕閬嶆偪閻愵剛绡€濠电姴鍊绘晶鏇犵棯閹岀吋闁哄本娲熷畷鐓庘攽閹邦厜褔姊虹紒妯诲碍缂佺粯鍔欓崺鐐哄箣閿旇棄鈧兘鏌熺€涙绠撻柡鍡欏仱閺屾盯鏁愰崟顓犵厯闂?",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃闁硅櫕鎹囬垾鏃堝礃椤忎礁浜鹃柨婵嗙凹缁ㄧ粯銇勯幒瀣仾闁靛洤瀚伴獮鍥敂閸℃瑧鍘梻浣告惈鐞氼偊宕濋幋锕€绠栭柕蹇嬪€曟导鐘绘煕閺囩喎鐏熼柛銊ヮ煼閹偓妞ゅ繐鐗嗙粻姘辨喐濠婂牊鍋傚┑鍌氭啞閻撴盯鎮橀悙鎻掆挃闁宠棄顦甸弻宥夋寠婢舵ɑ鈻堥悗瑙勬穿缁绘繈骞冨▎鎴斿亾閻㈠憡娅滃瑙勬礋濮婂宕掑▎鎴М缂佸墽铏庨崣鍐嵁婵犲洤绠婚柛鎾茶兌閻撳鎮峰鍛暭閻㈩垱甯￠幏鎴︽偄閻戞ê鏋戦梺鐟邦嚟婵攱绋夊鍡欑闁瑰鍎戞笟娑欑箾鐏忔牗娅婇柡灞剧缁犳稑顫濋鎸庣潖缂傚倷绀侀ˇ閬嶅礂濮椻偓瀵鏁愰崱妯哄妳闂侀潧鐗嗙€涒晝绱為崼婵冩斀闁绘劖褰冪痪褔鏌ㄩ弴妯虹伈妤犵偛鍟撮弫鎾绘偐閾忣偅顏熼梻浣虹帛椤牏浜搁鍫濈闁哄洨鍋愰弨浠嬫煟閹邦厽缍戦柣蹇曞枛閺屾盯濡搁妷锕佺缂備緡鍠涢褔鍩ユ径鎰潊闁挎稑瀚敮鎯р攽閻樺灚鏆╁┑顔碱嚟閹广垹螣娓氼垳鈧埖銇勯弴妤€浜鹃梺鍝勭焿缁蹭粙鍩為幋锕€鐐婇柍杞拌閸氬倹淇婇悙顏勨偓銈嗙濠婂牆鐤悗娑櫭肩换鍡涙煕椤愶絾绀€缁炬儳鍚嬬换娑㈠箣閻愬灚鍣悷婊勬緲濡繂顫忕紒妯诲闁惧繒鎳撶粭锟犳⒑閸︻厸鎷￠柛瀣楠炴垿濮€閻橆偅鏂€闂佺硶妾ч弲娑樷枔閵娾晜鐓熼柣妯哄级婢跺嫮绱掓担瑙勭稇閸楅亶鏌涢鐘插姕闁绘挸绻橀悡顐﹀炊閵婏妇顦ラ柛鐔告倐濮婃椽宕ㄦ繝鍐ｆ嫻闂佸湱顭堥崯鍧楋綖韫囨拋娲敂閸曨偆鐛╁┑鐘垫暩婵挳宕愰幖渚婄稏閹兼番鍔嶉埛鎴犵磼鐎ｎ偒鍎ラ柛搴㈠姍閺岀喖鎮烽悧鍫濇灎濡ょ姷鍋涢崯顖炲Χ閿濆绀冮柍杞拌閸嬫挻绻濆顓犲幘闂佽鍘界敮鎺楀礉濡ゅ懏鐓?",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳婀遍埀顒傛嚀鐎氼參宕崇壕瀣ㄤ汗闁圭儤鍨归崐鐐差渻閵堝棗绗掓い锔垮嵆瀵煡顢旈崼鐔蜂画濠电姴锕ら崯鐗堟櫏婵犵數濮崑鎾炽€掑锝呬壕濠殿喖锕ㄥ▍锝囨閹烘嚦鐔兼惞闁稓绀冨┑鐘殿暯濡插懘宕戦崟顓涘亾濮樼厧鏋ら柛鎺撳笚缁绘繂顫濋鐐版睏缂傚倸鍊烽悞锕傗€﹂崶顒€鍌ㄩ柣銏犳啞閳锋垹鐥鐐村婵炲吋鍔欓弻娑㈠籍閹惧墎鏆ら悗瑙勬礋濞佳囧煝鎼淬劌绠婚柡澶嬪灍閸嬫捇宕归锝呭伎濠殿喗顨呭Λ妤佹櫠缂佹ü绻嗛柟缁樺笧缁夋椽鏌＄仦鐐鐎规洘鍎奸ˇ鍙夈亜韫囷絽骞楁い銊ｅ劦閹瑩寮堕幋鐐剁檨婵°倗濮烽崑娑㈩敄閸涙潙鐓橀柟杈剧畱缁犳稒銇勮箛鎾村櫣濞存粍绻堝濠氬磼濮橆兘鍋撻悜鑺ュ€块柨鏇炲€哥粻鏍煕椤愶絾绀€缂佲偓婢跺备鍋撻崗澶婁壕闂佸憡娲﹂崑鍡涙晬濞嗘挻鍋℃繝濠傛噹椤ｅジ鎮介娑樼缂侇喖顭烽幃娆撴倻濡厧甯惧┑鐘垫暩閸嬫盯鎮樺┑瀣閻庢稒顭囩粻鍓х磼濡も偓閹碱偅鎱ㄩ崒鐐寸厸閻忕偛澧藉ú鎾煕閳轰礁顏€规洘锕㈤幃娆擃敆閸屾稒顔旂紓鍌氬€搁崐鐑芥嚄閼稿灚鍙忓Δ锝呭枤閺佸鎲搁弮鍫濈伋闁哄啫鐗嗙粈鍐┿亜閺傛寧顫嶇憸鏃堝蓟濞戞矮娌柛鎾椻偓婵洭姊虹紒妯肩畺婵炶尙鍠庨～蹇涙惞閸︻厾锛滃┑鈽嗗灣缁垶宕曢幘鍓佺＝濞达綀娅ｇ敮娑氱磼鐠囨彃鈧潡銆佸鑸垫櫜闁搞儯鍔岄悵鏉库攽閻愬瓨缍戞い鎴濇閿濈偛顓兼径瀣ф嫼闂傚倸鐗婄粙鎾剁不閸愭祴鏀芥い鏃€鍎抽崢瀵糕偓瑙勬礃缁诲牓鐛鈧、娆戞喆閿濆棗顏归梻鍌欑閹诧紕绮欓幋锔芥櫇闁靛牆妫欓崣蹇擃熆閼搁潧濮堥柣鎾存礋閹鏁愭惔鈥茬凹閻庤娲栭惌鍌炲蓟閻旂⒈鏁嬮柍褜鍓涚划濠氬冀椤撶偟鐣哄┑鐘诧工閻楀﹪宕靛澶嬬厪濠㈣泛鐗嗛悘顏堟倵?",
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


def _training_record_has_verification_clues(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    list_keys = (
        "acceptance_criteria",
        "acceptanceCriteria",
        "learner_deliverables",
        "learnerDeliverables",
        "verification_steps",
        "verificationSteps",
        "self_check",
        "selfCheck",
        "expected_symbols",
        "expectedSymbols",
        "api_hints",
        "apiHints",
    )
    for key in list_keys:
        value = record.get(key)
        if isinstance(value, list) and any(str(item or "").strip() for item in value):
            return True
    scalar_keys = (
        "training_card_id",
        "trainingCardId",
        "selected_card_id",
        "selectedCardId",
        "success_signal",
        "successSignal",
        "deliverable",
        "problem_statement",
        "problemStatement",
        "suggested_workspace_action",
        "suggestedWorkspaceAction",
    )
    for key in scalar_keys:
        if str(record.get(key) or "").strip():
            return True
    target_skill = str(record.get("target_skill") or record.get("targetSkill") or "").strip().lower()
    return bool(target_skill) and any(
        token in target_skill for token in ("practice", "current-file", "verification")
    )


def _coach_context_has_active_training_card(coach_context: dict[str, Any] | None) -> bool:
    if not isinstance(coach_context, dict):
        return False
    routing_candidates: list[Any] = [
        coach_context.get("active_training_card_routing"),
        coach_context.get("activeTrainingCardRouting"),
    ]
    memory = coach_context.get("memory")
    if isinstance(memory, dict):
        routing_candidates.extend(
            [
                memory.get("active_training_card_routing"),
                memory.get("activeTrainingCardRouting"),
            ]
        )
    for routing in routing_candidates:
        if not isinstance(routing, dict):
            continue
        selected_card = routing.get("selected_card") or routing.get("selectedCard")
        if _training_record_has_verification_clues(selected_card):
            return True
        if str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip():
            return True
    return False


def _current_file_has_training_context(current_file: dict[str, object] | None) -> bool:
    if not isinstance(current_file, dict):
        return False
    if _training_record_has_verification_clues(current_file):
        return True
    return any(
        str(current_file.get(key) or "").strip().lower() == "training"
        for key in ("evaluation_source", "source", "mode")
    )


def _current_file_has_visible_content(current_file: dict[str, object] | None) -> bool:
    if not isinstance(current_file, dict):
        return False
    return any(
        str(current_file.get(key) or "").strip()
        for key in ("path", "content", "content_excerpt")
    )


def _agentic_practice_verification_context_active(
    *,
    message: str,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> bool:
    context = extract_coaching_context(message, current_file, coach_context)
    if isinstance(context.get("exercise_prompt"), dict):
        return True

    coaching_state = context.get("coaching_state")
    if isinstance(coaching_state, dict):
        teaching_mode = str(coaching_state.get("teaching_mode") or "").strip().lower()
        if teaching_mode == "practice":
            return True

    if _current_file_has_training_context(current_file):
        return True

    practice_focus_text = " ".join(
        str(value or "")
        for value in (
            message,
            context.get("summary"),
            context.get("current_focus"),
            context.get("next_step_hint"),
        )
    )
    practice_terms_present = _text_has_practice_verification_terms(practice_focus_text)
    if not practice_terms_present:
        return False

    if _current_file_has_visible_content(current_file):
        return True
    if _coach_context_has_active_training_card(coach_context):
        return True
    return False


def _text_has_practice_verification_terms(text: str) -> bool:
    lowered = text.lower()
    return any(
        term in lowered
        for term in (
            "practice",
            "training card",
            "hands-on",
            "acceptance",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳婀遍埀顒傛嚀鐎氼參宕崇壕瀣ㄤ汗闁圭儤鍨归崐鐐差渻閵堝棗绗掓い锔垮嵆瀵煡顢旈崼鐔蜂画濠电姴锕ら崯鎾矗閸曨垱鐓忛柛鈩冾殔閺嗭絽鈹戦敍鍕効妞わ附鎸抽弻锝夘敇閻旂儤鍣伴梺鍝勬湰閻╊垰顕ｆ繝姘兼晣婵犲﹤鍟犻崑鎾诲箛閺夎法锛涢梺瑙勫礃椤曆囨煥閵堝棔绻嗛柕鍫濆椤斿鏌熷畡鐗堟儓妞ゎ亜鍟存俊鍫曞幢濡も偓濞兼垿姊虹粙娆惧剱闁圭澧藉Σ鎰板箳閹惧磭绐炴繝鐢靛Т妤犵鈻撻懜鐢电瘈闁靛骏缍嗗鎰箾閸欏鐒介柟骞垮灩閳规垿宕遍埡鍌氬厞婵＄偑鍊栭幐鐐叏閹绢喚宓佹俊銈呮噺閳锋帒霉閿濆懏鎲哥紒澶嬫そ閺屾稓鈧綆浜烽煬顒傗偓瑙勬礃缁矂锝炲┑鍫熷磯闁惧繐婀遍弳浼存⒒娴ｇ顥忛柛瀣╃窔瀹曟洟寮婚妷锕€浜?",
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳婀遍埀顒傛嚀鐎氼參宕崇壕瀣ㄤ汗闁圭儤鍨归崐鐐烘偡濠婂啰绠荤€殿喗濞婇弫鍐磼濞戞艾骞堟俊鐐€ら崢浠嬪垂閸偆顩叉繝闈涱儐閻撴洘绻涢崱妤冪缂佺姵濞婇弻宥堫檨闁告挻绻堥敐鐐村緞婵炴帗妞藉浠嬧€栭埄鍐┿仢闁轰礁鍟村畷鎺楀Χ閸℃ɑ鐝栨繝鐢靛仜椤曨厽鎱ㄩ幘顕呮晞闁糕剝绋掗崑鍌炴煏婢跺棙娅嗛柣鎾跺枛閺岋繝宕掑☉姗嗗殝闂佽鍨伴悧蹇涘焵椤掍胶鈯曠紒璇茬墕椤繘鎼归崷顓犵厯闂佸吋鍓氶崹鐓庮焽閸洘鈷戦柛娑橈攻閳锋劙鏌涢妸銉т虎妞ゆ洩绲块幏鐘裁圭€ｎ偒娼旈梻渚€娼х换鎺撴叏閻戠瓔鏁婇柟鐑樺灍閺€浠嬪箳閹惰棄纾归柟鐗堟緲绾惧鏌熼崜褏甯涢柣鎾存礋閺岋綁寮村槌栨М婵炲瓨绮堥崡鎶藉蓟閻旂⒈鏁婄紓鍌氱摠閸ㄥ綊骞戦姀鐘斀閻庯綆浜為崐鐐烘⒑闂堟侗鐒鹃柛搴櫍瀹曟垿骞樼紒妯轰缓闂佸憡绋戦敃锕傚储闁秵顥婃い鎰╁灪婢跺嫰鏌熺亸鏍ㄦ珔閸楄京绱掔€ｎ偓绱╅柣鐔煎亰閻撱儵鏌涢鐘茬伄闁哄棭鍋勯埞鎴︻敊绾攱鏁惧┑锛勫仩濡嫰鎮鹃悜钘壩╅柨鏂垮⒔閻﹀牓姊洪崨濠傚Е闁绘挸鐗嗗嵄闂侇剙绉甸埛鎺懨归敐鍕劅闁绘帞鍋撻妵鍕箣濠靛洤娅ｉ柧鑽ゅ仦缁绘繈妫冨☉鍗炲壈閺?",
            "濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻鐔虹磼閵忕姵鐏嶉梺绋块椤︻垶鈥﹂崸妤佸殝闂傚牊绋戦～宀€绱撴担鍝勭彙闁搞儜鍜佸晣闂佽瀛╃粙鎺曟懌闁诲繐娴氶崢濂告箒濠电姴锕ら幊搴㈢閹灔搴ㄥ炊瑜濋煬顒€鈹戦垾宕囧煟鐎规洜鍠栭、姗€鎮欏顔锯偓鎾⒒閸屾瑧顦﹂柟璇х節閹兘濡疯瀹曞弶鎱ㄥ璇蹭壕閻庢鍠栭…鐑藉箖閵忋倖鎯為柛锔诲弿缁辨煡姊绘笟鈧褏鎹㈤幒鎾村弿闁汇垹鎲￠崐鍫曟煕椤愮姴鍔滈柣鎾跺枛楠炴牕菐椤掆偓閻忓崬顭跨憴鍕嗘垿濡甸崟顖涙櫆闁割煈鍠栫粊顔界節绾板纾块柡浣筋嚙閻ｇ兘鎮㈢喊杈ㄦ櫖濠殿喗锕㈢涵鎼佸船濞差亝鈷掑ù锝囧劋閸も偓闂佸鏉垮闁瑰箍鍨归濂稿幢濞嗘ɑ绁┑鐘绘涧閸婃悂骞夐敓鐘茬厱?",
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
            "practice is verified",
            "verified from the current file",
            "verified by current-file evidence",
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
            else "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃闁硅櫕鎹囬垾鏃堝礃椤忎礁浜鹃柨婵嗙凹缁ㄧ粯銇勯幒瀣仾闁靛洤瀚伴獮鍥敂閸℃瑧鍘梻浣告惈鐞氼偊宕濋幋锕€绠栭柕蹇嬪€曟导鐘绘煕閺囩喎鐏熼柛銊ヮ煼閹偓妞ゅ繐鐗嗙粻姘辨喐濠婂牊鍋傚┑鍌氭啞閻撴盯鎮橀悙鎻掆挃闁宠棄顦甸弻宥夋寠婢舵ɑ笑闁句紮缍侀弻娑滅疀閹捐櫕鍊梺鍝ュУ閻楃姴顫忕紒妯诲濞撴凹鍨抽崝绋款渻閵堝棗鐏﹂柛銊ョ秺楠炴垿濮€閻橆偅鏂€闁诲函缍嗘禍锝夊箺閺囥垺鈷戦柛婵嗗閸屻劑鏌涢妸銉хШ闁哄苯顑夊畷鍫曞Ω瑜忛惁鍫ユ⒒閸屾氨澧涚紒瀣浮楠炴牠骞囬鍓э紲闂佸綊鍋婇崢鎯虹€涙ɑ鍙忓┑鐘插暞閵囨繄鈧娲忛崝宥囨崲濠靛洦鍎熼柕蹇嬪灪濞堥箖姊虹拠鏌ヮ€楅柛妯荤矒瀹曟垿骞樼紒妯煎幍闂傚倸鍊搁顓⑺囬敂鍓х＜闁绘ê纾晶顒€菐閸パ嶈含濠碘€崇埣瀹曟帒顫濋銏╂闂傚倸鍊风粈渚€鎮块崶顬盯宕熼鈧崶顒夋晬闁绘劘灏欓崢娲倵楠炲灝鍔氭い锔垮嵆楠炲棝鎮欏ǎ顑跨盎闂佽澹嬮弲娑㈡倶椤旀祹褰掓偐閸濆嫪姹楃紓浣介哺閹稿骞忛崨鏉戠闁圭儤鍨堕崕鎾绘⒒娴ｄ警鐒炬い鎴濆暣瀹曟劕鈹戠€ｎ偄浠掑銈嗘煥濡插牓鎮㈤悡搴＄獩闂傚倸鐗婇惄顖炲矗閸曨兙浜滈柕蹇ョ磿婢ч亶鏌熼悷鏉款伃濠碘剝鐡曢ˇ鎶芥煛閸涱偄濮傛慨濠傤煼瀹曟帒顫濋钘変壕闁归棿璁查埀顒婄畵椤㈡宕熼銈忕幢闂備礁鎲″ú锕傚磹鐎ｎ€㈡椽顢旈崨顔界彇闂備胶顭堥張顒€顫濋妸鈺婃晩闁搞儺鍓氶埛鎴犵磽娴ｅ顏呮叏閿曞倹鐓曢柟鍓ь棎婢规﹢鏌嶇拠鑼ч柟顔规櫅閻ｇ兘宕堕埡濠傛櫗闂傚倷鑳堕幊鎾活敋椤撱垹纾婚柟閭﹀劦濞戙垹惟鐟滃酣宕伴幇鐗堢厽婵°倐鍋撻柣妤€妫涚划顓烆潩閼哥數鍘遍柣搴秵閸嬪嫭鎱ㄦ径宀€纾奸弶鍫涘妼缁楁帡鏌嶉挊澶樻Ц妞ゎ偅绻堝畷妤呭礂閸忓吋顔夐梻鍌氬€风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼顢欓悾宀€顔曠紒缁㈠弮椤ユ挾寮ч埀顒勬倵濞堝灝鏋涙い顓犲厴楠炲啴濮€閵忕姵鐎抽柡澶婄墑閸斿秴鈻嶉幘缁樷拻濞达絿鐡旈崵鍐煕閵娿儵鍙勭€规洘锕㈡俊姝岊檨闁告艾鎳樺缁樻媴缁涘娈柣搴㈢▓閺呯娀銆佸▎鎾冲唨妞ゆ挾鍋熼悰銉モ攽鎺抽崐鎰板磻閹炬番浜滄い鎾跺仦閹兼劙鏌嶇拠鏌ュ弰妤犵偞鐟╁畷鐔碱敇閻橆偅锛堟繝鐢靛Х閺佸憡绻涢埀顒佺箾娴ｅ啿鍘惧ú顏呮櫆闁告挆鍜佹Ц闂備焦鎮堕崕娲礈濮樿埖鍋傞柛鎰靛枟閻撴洘绻濋棃娑欘棞妞ゅ繆鏅犻弻锟犲幢濡吋鍣板Δ鐘靛仦閻楃姴顕ｉ崼鏇炵妞ゆ牗绻傞幆鍫熺節濞堝灝鏋涢柨鏇樺€濋垾锕€鐣￠幍顔芥闂佸湱鍎ら崹鐔煎几鎼淬劍鐓欓悗鐢殿焾鍟搁悗瑙勬礀瀵墎鎹㈠┑瀣仺闂傚牊绋愰崫妤佺節閵忋垺鍤€闁绘妫濋幃楣冩倻閼恒儺妫冨┑鐐村灥瀹曨剙鈻撻锝囩瘈闁汇垽娼у瓭闂佸摜鍠嗛崝鎴濈暦閹达箑宸濋悗娑欘焽閸橀亶姊虹憴鍕棎闁哄懏绋掓穱濠囧锤濡や胶鍘介梺鎸庣箓濡瑩濡靛┑鍥ㄥ弿濠电姴鎳忛鐘电磼椤旂晫鎳囨鐐村姈閹棃濮€閳ユ剚浼嗛梻鍌氬€风粈渚€骞夐敓鐘插瀭闁汇垻鏁哥粈濠傗攽閻樻彃鈧寮抽敃鍌涚厽闁靛繈鍩勯悞楣冩煕濡や礁鈻曢柡宀嬬秮瀵噣宕掑鍛缂傚倷闄嶉崝宀勨€﹀畡閭︽綎婵炲樊浜滈幑鑸点亜閹捐泛浠滃┑鈩冩そ濮婃椽骞栭悙鎻掝瀷闂佽桨绀侀…鐑藉Υ娓氣偓瀵噣宕煎┑鍫濆箰闂備礁鎲￠崝锔界閻愮儤鏅繝濠傜墛閳锋垹绱撴担璇＄劷闁规彃娼￠弻娑氣偓锝庡亝瀹曞矂鏌＄仦鍓ф创濠碘剝鎮傞弫鍐焵椤掑嫬鐓濋柡鍥ュ灪閻撴洟鏌嶇憴鍕姢濞存粎鍋撴穱濠囨倷椤忓嫧鍋撻弽褜鍟呭┑鐘宠壘绾惧鏌熼崜褏甯涢柣鎾存礃娣囧﹪顢涘┑鍡楁優闂佹椿鍘界敮鐐哄焵椤掑喚娼愭繛鍙夛耿瀹曞綊宕稿Δ鍐ㄧウ濠碘槅鍨甸崑鎰閸忛棿绻嗘い鏍ㄧ矊鐢埖顨ラ悙鑼ⅵ婵﹦绮幏鍛瑹椤栨稒鏆為梻浣虹《閺呮稑煤椤撶偟鏆︽繝闈涙－閸氬鏌涘☉鍙樼凹闁诲孩妞藉娲川婵犲嫧妲堥梺瀹︽澘濮傞柟?provider闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱濠电姴鍊归崑銉╂煛鐏炶濮傜€殿噮鍣ｅ畷濂告偄閸涘鍞堕梻鍌欒兌椤牓顢栭崱娑樼闁告挆鍐ㄧ亰濡炪倖鎸鹃崑鎰ｉ崼鐔剁箚妞ゆ牗绻嶉崵娆愮箾閸涘洤娲﹂埛鎴炵箾閼奸鍤欐鐐搭殜閺岋綁鎮㈤崣澶嬬彋閻庢鍠栭…鐑藉箖閵忋垺鍋橀柍銉ュ帠婢规洟姊哄Ч鍥х仾妞ゆ梹鐗犻幃鐐哄箚椤€崇秺閹晛鈻庤箛鏂款槱闂佹娊鏀辩敮锟犲蓟濞戙垹鍗抽柕濞垮劙缁ㄨ顪冮妶鍛闁告瑥鍟村濠氬灳瀹曞洦娈曢柣搴秵閸撴盯鎯侀崼銉﹀€甸悷娆忓缁€鍐煥閺囨ê鐏ǎ鍥э躬楠炴牗鎷呴懖婵勫姂閺屾洝绠涢弴鐐愨€愁熆鐟欏嫭绀嬫慨濠冩そ瀹曘劍绻濋崟顓犵獥闂備胶顭堢€涒晠鎮￠敓鐘偓渚€寮撮悢渚祫闁诲函缍嗛崑鍡涘储椤忓牊鈷戦柛鎾村絻娴滄繄绱掔拠鎻掓殻鐎规洦鍨堕獮鎺懳旀担鍝勫箰闂備礁鎲￠崝鎴﹀礉鎼淬垺娅犳繛鎴欏灪閻撴盯鏌涘☉鍗炴灓闁告瑢鍋撻梻浣告惈閺堫剛绮欓幋锕€鐓″鑸靛姇绾偓闂佺粯鍔樼亸娆擃敊閹寸偟绡€闁汇垽娼ф禒婊堟煟濡や胶鐭掔€规洩缍佸畷姗€顢欓懝鐗堟啺闂備焦瀵х换鍌炈囨导鏉戠；闁告洦鍨遍悡鏇熺節闂堟稑顏╅柛鏃€绮撻弻娑㈠Χ閸涱厸鍋撻懡銈嗩潟闁规儳鐡ㄦ刊鎾煕濠靛棗鐝旈柨婵嗩槹閻撴瑩鏌ｉ悢鍝勵暭闁哥姵锕㈤弻锝呪槈閸楃偞鐝濋悗瑙勬礃閿曘垽鍨鹃敃鍌氱闁绘劘灏欑槐锕傛⒒閸屾瑧绐旈柍褜鍓涢崑娑㈡嚐椤栨稒娅犻悗娑欙供濞堜粙鏌ｉ幇顓炵祷闁哄棙鐟╅弻宥囨嫚閺屻儱寮板Δ鐘靛仜椤戝骞冨▎鎾村殤妞ゆ帒锕︾涵鈧梻鍌氬€风粈渚€骞栭位鍥焼瀹ュ懐锛涢梺缁樻煥閹测€斥枍閻樺厖绻嗛柕鍫濇噺閸ｆ椽鏌涙惔銏″磳闁绘搩鍋婂畷鍫曞Ω閿旀儳寮扮紓鍌欐祰椤曆兾涘┑瀣摕闁挎繂顦粻娑㈡煕韫囨挻鎲搁柣鈺侀叄濮婃椽鏌呴悙鑼跺濠⒀屽灡缁绘盯宕ｆ径宀€鐓夊Δ鐘靛仦閸ㄦ寧鎱ㄩ埀顒勬煟濡崵澧慨濠傜秺楠炲繘宕ㄩ弶鎴狀槯闂佸憡绺块崕鎶芥偂婢舵劖鈷掗柛灞剧懅椤︼妇绱撳鍜冨伐閾荤偤鎮归幁鎺戝闁活厼妫楅湁闁挎繂鐗婇鐘测槈閹惧磭效闁哄矉缍侀獮鍥敊閻撳骸顬嗛梻浣虹帛閹稿摜鎹㈤幇鏉跨厴闁硅揪闄勯崑鎰版煠绾板崬澧版い鏂挎搐椤啴濡堕崒娑欑彟闂佸憡鎸荤粙鎾澄ｉ幇鏉跨婵°倐鍋撻柣鎾卞灲閺屽秷顧侀柛鎾跺枎閻ｇ兘骞嬮敃鈧粻鑽ょ磽娴ｉ姘跺箯缂佹绠鹃弶鍫濆⒔閸掍即鏌熺拠褏绡€鐎规洦鍨堕幃娆撴倻濡厧骞堥梻浣告惈閸燁垶骞戦崶褜鐎舵い鏂垮⒔绾惧ジ鏌涚仦鐐殤閺佸牓姊虹拠鈥虫灍闁荤啿鏅犻獮鍐煥閸忓墽鍠愬顏堟偋閸繀绨奸梻鍌氬€搁崐鎼佸磹妞嬪孩顐介柨鐔哄Т缁€鍫熺箾閸℃ê鐏╅柣顓熸崌閺岋綁濮€閻樺啿鏆堥梺绋款儏閸婂潡寮婚敐澶婄睄闁稿本鑹炬禒妯肩磽娴ｅ搫鞋妞ゎ偄顦遍幑銏犫槈閵忊剝娅滈柟鑲╄ˉ閳ь剚鍓氬璇测攽閻樿尙妫勯柕鍫濇啗閹惧墎纾肩紓浣诡焽濞插瓨顨ラ悙璇у伐闁伙綇绻濋幃褔宕煎┑鎰熼梻鍌欒兌缁垶骞愭ィ鍐ㄧ獥闁圭増婢樻闂佸憡娲﹂崹鎵不閹惰姤鐓欓悗娑欘焽婵″洭鏌涚€ｎ偅宕岀€规洦鍋婃俊鐑芥晜閼恒儺鍞堕梻鍌欑婢瑰﹪宕戦崨顒煎搫顫滈埀顒勫箖閿熺姴绀冩い鏃囨娴狀垶姊洪幖鐐插姌闁告柨閰ｅ畷锝夊焵椤掑嫭鈷戦柛娑橈功閹冲啴鎮楀鐓庡⒋闁糕晝鍋ら獮瀣晜缂佹ɑ娅撻梻浣藉吹閸犳牠銆傞敂鐣岀彾闁哄洢鍨洪埛鎺楁煕鐏炲墽鎳嗛柛蹇撶灱缁辨帡顢氶崨顓犱桓闂佽鍠氶崗妯绘叏閳ь剟鏌曢崼婵囧櫧闁挎稒鐩铏规喆閸曨偄濮㈠銈嗘处閸樺墽鍒掔紒妯稿亝闁告劏鏅涢埀顒€鐖奸悡顐﹀炊閵婏腹鎷绘繝鈷€灞藉缂佺粯鐩畷銊╊敇閵娿劌鎯堥梻浣告惈閻ジ宕伴弽顓溾偓浣糕枎韫囧﹥鐎婚梺缁樺姦閸撴稓绮旈悜鑺モ拻濞撴埃鍋撴繛浣冲洦鍋嬮柣鎰節缁诲棝鏌涢妷顔煎缂佺姷鍠愭穱濠囧Χ閸涱喖娅ｉ柛銉︽尦濮婅櫣绮欓幐搴㈡嫳闂佹椿鍙庨崰妤冪博閻旂厧鍗抽柕蹇婃閹锋椽姊绘笟鍥т簽闁稿鐩幊鐔碱敍濞戞瑦鐝烽梺鍦檸閸犳鎮″☉銏″€堕柣鎰絻閳锋棃鏌曢崱妯烘诞闁哄苯绉烽¨渚€鏌涢幘鍗炲缂佽京鍋ゅ畷鍗炩槈濡》绱遍梻浣告啞娓氭宕㈡ィ鍐ㄦ辈闁挎洖鍊归崐鍫曟煟閹邦亞绁锋俊鎯ф啞缁绘盯宕煎鍛厯闂佸搫鐭夌紞渚€鐛崶顒夋晣闁绘柨鍢叉竟鎺楁⒒娴ｈ櫣甯涢悽顖滃仱瀵煡顢曢妶鍡╂綗闂佸湱鍎ら幐鑽ょ礊閸ヮ剚鐓忓┑鐐茬仢閸斻倝鏌ｉ悢鏉戝闁哄睙鍕嚤婵炲棙鍨硅ⅵ闂備礁鎼惌澶岀礊娓氣偓閻涱喚鈧綆鍠楅崐濠氭煕閳╁啰鎳冨┑顔芥そ濮婄粯鎷呴崨濠冨創濠碘槅鍋呯粙鎺旀崲濞戙垹鐒垫い鎺嶇劍閸欏繐鈹戦悩鎻掍簽闁绘捁鍋愰埀顒冾潐濞叉鏁幒妤€鐓濋幖娣妼缁狅絾銇勯幘璺烘櫩婵犲﹤鐗婇埛鎺懨归敐鍛暈闁哥喓鍋ら弻銈堛亹閹烘梻鏆銈冨灪閻楃姴鐣烽崡鐐╂瀻闁瑰濮烽崝褰掓煟鎼达紕鐣柛搴″船铻炴繛鎴娇閳ь剙鎳橀幃婊堟嚍閵夈儮鍋撻悽鍛婄叆婵犻潧妫涢崙鍦磼閵娿倗鐭欓柡灞诲妼閳藉顫濋浣轰邯闂備礁鎼径鍥礈濠靛棭鍤楅柛鏇ㄥ墰缁♀偓闂佸憡娲﹂崑鎺楀汲閵夆晜鈷掑ù锝呮啞閸熺偤鏌＄仦璇插闁诡垰顦甸幃鈩冩償濡崵鈧姊洪棃娑氱疄闁稿﹥鐗犲畷鎰槹鎼达絾锛忛梺缁橆殔閻擃偊顢旈崨顖ｆ锤闂佺粯鍔﹂崜锕€鈻撴禒瀣厽闁归偊鍨伴惃鍝劽归悩顔肩伈闁哄本鐩顕€鍩€椤掑倸鏋堢€广儱顦闂佸憡娲﹂崹閬嶅疾濠婂牊鐓曟い顓熷灥閺嬫稓绱掓笟鍥ф珝婵﹨娅ｉ幏鐘诲灳閾忣偆褰茬紓鍌欒兌缁垳鎹㈤崘顔肩疄闁靛ň鏅涢悞鍨亜閹烘垵顏柣鎾跺枑娣囧﹪顢涘鍐ㄥ濡炪們鍎茬划搴ｆ閹炬剚鍚嬮柛婊冨暢閸氼偊鎮楀▓鍨珮闁稿锕悰顕€宕堕鈧痪褔鏌涜椤ㄥ懘寮憴鍕箚闁绘劦浜滈埀顒佺墵瀹曟繈骞嬮敃鈧崹鍌涚箾瀹割喕绨奸柛瀣ф櫊閺岋絽螖閳ь剟鎮ц箛鏇炲К闁逞屽墴濮婂搫效閸パ呬紙濠电偘鍖犻崟顓ф祫濠电姴锕ら悧濠囨偂閻旈晲绻嗛柕鍫濆€告禍楣冩⒑閹稿孩纾搁柛濠冪箞閺佹劙鎮欓崜浣烘澑濠电偞鍨堕悷銉モ枔閵夆晜鈷戦梻鍫熺〒婢ф洘淇婇顐㈠箹妞ゎ厼娲幃銏ゅ礂鐏忔牗瀚奸梻渚€娼荤€靛矂宕㈡總绋跨閻庯綆鍋佹禍婊堟煏婵炲灝鍔滄い銉ｅ灮閳ь剝顫夊ú婊堝极閹间礁鐒垫い鎺戯功缁夌敻鏌涢悩鎰佹疁闁诡噯绻濋幃銏ゅ礂閼测晛甯鹃梻濠庡亜濞层倝鏁冮妷鈺嬬稏濠电姴娲﹂悡鏇㈡煟閺冨牜妫戠紒鐘差煼閺屸€崇暆鐎ｎ剛鐦堥悗瑙勬礋娴滃爼銆佸鈧幃鈺冨枈婢跺苯鎯炵紓鍌氬€搁崐宄懊归崶銊ｄ粓闁归棿绀佺粻鏉库攽閻樺疇澹樼紒鐙€鍨堕弻娑樷槈濞嗘劗绋囩紓浣插亾闁割偁鍎查悡娆戠磽娴ｅ顏嗙箔閹烘埈鐔嗛柣鐔稿婢ф稑菐閸パ嶈含闁诡喗鐟╅、鏃堝礋閵娿儰澹曢悷婊冪箳閸掓帗绻濆顒傤啋闁诲酣娼ф竟濠偯洪幖浣光拺闁告挻褰冩禍婵囩箾閸欏澧电€殿喕鍗虫俊鐑藉煛閸屾粌甯楅柣鐔哥矋缁挸鐣峰鍐炬僵閻犺桨缍嶉敃鍌涚厱闁哄洢鍔岄悘鐘电磼閻樺啿鈻曢柡宀€鍠栭獮鏍敇閻愬吀鍝楀┑鐘愁問閸犳绮欓幘鑸殿潟闁规儳鐡ㄦ刊鎾煟閵堝骸鐏犻柛姗堢節濮婅櫣绮欑捄銊ь唹闂佹寧娲忛崹褰掝敋閿濆洦瀚氭繛鏉戭儐椤秹姊洪棃娑氱濠殿喚鏁昏棢婵犻潧妫岄弨浠嬫煟閹邦剙绾фい銉у█閺屾稓鈧綆鍋呭畷宀勬煕閳瑰灝鐏茬€规洖銈告俊鐑芥晝閳ь剟鍩€?"
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
            else "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎娆戠┛闂傚倷绶氶埀顒傚仜閼活垱鏅堕崜褏纾奸柣妯挎珪鐏忣參鏌ｉ敐澶嬫暠缂佽櫣鏅划娆忊枎閻愵剛绉遍梻鍌欒兌閸嬨劑宕曢柆宥呯柈閻犳亽鍔忔慨鎶芥煏婢跺棙娅嗛柍閿嬪笒闇夐柨婵嗘川閹藉倹绻涢崗鐓庡妞ゎ厼娼￠幃鐑芥偋閸偅锛侀梻浣告惈閹虫挸鈻斿☉婊呬簷闂備礁鎲℃笟妤呭储妤ｅ啯鏅繛鎴欏灪閻撶喖骞栭幖顓炵仯缂佸娼ч湁婵犲﹤瀚晶鐢碘偓娈垮枔閸斿秶绮嬮幒鏂哄亾閿濆骸浜為柛妯挎閳规垿鍩ラ崱妤冧哗闂佸湱鈷堥崑鍡涙儉椤忓浂妲鹃梺姹囧労娴滎亪銆佸鈧崺鍕礃閻愵剦妫勫┑锛勫亼閸娿倝宕㈤悡搴劷闁跨喓濮寸粻鐘崇節婵犲倻澧涙い銉ョ墛缁绘盯骞嬮悜鍥︾返濠电偛鍚嬮幑鍥蓟閿濆棙鍎熼柨婵嗘濞堝矂姊虹涵鍜佸殝缂佽鲸娲熼獮鎴﹀閵堝懘鍞堕梺闈涱槶閸庢挳骞楅弴銏♀拺闁哄倶鍎插▍鍛存煕閻曚礁浜炴繛鍡愬灲閹瑩鎮滃Ο琛″亾閻㈠憡鐓ユ繝闈涙閸戝湱绱掗妸銊︻棄闂囧鏌ｉ幘鍐差劉闁哥姵蓱閹?provider 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊渚楅崕鎰亜閵夈儳澧涚紒缁樼洴楠炲鈹戦崱姘厴闂備礁鎲￠幐缁樼珶閸℃瑦顫曢柟鐑橆殕閸婇攱銇勯幒鍡椾壕闂佸憡鏌ｉ崐鏍Φ閸曨垼鏁囬柣妯诲絻楠炲鎮楀▓鍨灈妞ゎ厾鍏樺顐﹀箛椤撶偟绐炴繝鐢靛Т鐎氼噣寮堕崨濠佺箚闁绘劦浜滈埀顒佺墱閺侇噣骞掑Δ鈧壕鐟邦渻鐎ｎ亪顎楅柛銊︾箞閺岋綁濮€閻樺啿鏆堥梺鎶芥敱閸ㄥ潡寮诲☉妯锋斀闁糕剝顨忔禒鎯ь渻閵堝啫鍔ら柛瀣枔濡叉劙骞掑Δ濠冩櫓闂佸吋浜介崕杈╁閹惰姤鍊垫繛鍫濈仢閺嬫稒銇勯鐘插幋妤犵偛鍟存慨鈧柕鍫濇閸庮亪姊洪棃鈺佺槣闁告瑥绻掑Σ鎰板蓟閵夛腹鎷绘繛鎾村焹閸嬫挻绻涙担鍐叉噺瀹曟煡鏌熼悜妯诲鞍闁告瑥绻橀弻锝夊閻樺啿鏆堥梺绋匡工婢у酣鍩€椤掆偓缁犲秹宕曢柆宓ュ洦瀵奸弶鎴犲幈闂佺鎻梽鍕偂閺囩喓绡€闂傚牊绋掗ˉ婊勩亜韫囷絼绨婚柍瑙勫灴椤㈡稑顫濋妷銉ゅ垝闂備礁鎼張顒勬儎椤栫偟宓佹俊顖氬悑瀹曞鏌ｉ幋鐑嗙劷濞存粠浜濇穱濠囧Χ閸ヮ灝銉╂煕鐎ｎ偆娲寸€规洦鍨堕、鏇㈡晜閼测晝鈼ゆ繝鐢靛Т閿曘倝鎮ч崱娑欏€块柛顭戝亖娴滄粓鏌熼悜妯虹仴妞ゅ繆鏅濈槐鎺楁偐瀹曞洤顫х紓浣虹帛閻╊垰鐣烽崡鐐嶇喓鎷犻弻銉р偓娲⒒娴ｈ鍋犻柛濠冩礋椤㈡牠宕卞▎鎰簥濠电偞鍨崹褰掓煁閸ヮ剚鐓熼柡鍌涱儥濞堢娀鏌涢妶鍜佸剰妞ゎ亜鍟存俊鍫曞礃閵娿儱顫撴俊鐐€х粻鎾愁焽瑜旈敐鐐剁疀閺囩姷锛滃┑鈽嗗灥椤曆囶敁閹剧粯鈷戦柛娑橈功閳藉鏌ㄩ弴妯哄姦鐎规洘娲熼獮妯肩磼濡攱瀚奸梻浣藉吹閸犳劕顭垮鈧铏綇閳哄啰锛滅紓鍌欑劍閿曨偊鎳撻幐搴闁绘劖褰冮弳锝夋煙椤旂晫鐭掗柟绋匡攻缁旂喖鍩為崹顔碱潎闂佸搫鑻粔鐟扮暦椤愶箑绀嬫い鎰枎娴滄儳鈹戦悩宕囶暡闁稿鏅犻弻鐔煎箚閺夊晝鎾绘煃闁垮娴柡灞剧〒娴狅箓宕滆閸ｎ垶姊虹粙璺ㄧ闁活剝鍋愬Σ鎰板箳濡ゅ﹥鏅梺鍛婁緱閸樼偓绂掗幘顔解拺闁革富鍘鹃幗鍌炴煕鐎ｎ亷韬鐐插暙閻ｏ繝鏌囬敂鎯у汲闂備礁鎲″ú锕傚礈濞戙垹绀勯柨鐔哄У閳锋垿鏌涘┑鍕姎闁哄鍨块弻鐔煎川婵犲倵鏋欐繝纰樷偓宕囨憼闁瑰嘲鎳橀幊鏍р攽閸ヮ煈妫冮悗瑙勬磸閸旀垿銆佸Ο娆炬Ъ缂傚倸绉撮崐鍨潖缂佹ɑ濯撮柣鐔煎亰閸ゅ绱撴担鍓插剱闁搞劌缍婇崺鈧い鎺嶇閸ゎ剟鏌涢敐蹇曠М闁靛棔绀侀埢搴ㄥ箻閸愭彃绁梻渚€娼х换鍡楊瀶瑜旈獮蹇撁洪鍛幗闂佺粯鏌ㄩ幗婊堝箠閸愵喗鍊垫慨妯煎帶婢у鈧娲樼换鍫熶繆閼搁潧绶為悗锝庡墮楠炲牓姊绘担铏瑰笡婵☆偄鍟村銊╂焼瀹ュ懐锛涢梺闈涱槴閺呮粓鎮¤箛娑欑厱闁斥晛鍠氬▓鏃堟煃瑜滈崜娆撴倶濠靛鍋╃€瑰嫭瀚堥悢鐓庣闁绘挸瀛╁▍婵嗏攽閻愯埖褰х紒鎻掓健瀹曟洟濡舵径濠傛優闂侀€炲苯澧い顏勫暣婵¤埖鎯旈垾宕囶唹闂備礁鎲″褰掑垂閻㈠憡鍋╅柣鎴ｅГ閸嬪嫮鐥幏宀勫摵闁哄拑缍佸铏圭磼濡儵鎷诲銈庡幖閻楁挸顕ｉ弻銉ヤ紶闁靛／鍜冪闯闂備胶顭堥張顒勬嚌妤ｅ啫鐒垫い鎺戝€搁崢鎾煙閾忣偒娈滈柟铏矒瀹曞綊顢曢姀鐘辩礋闂傚倷鐒﹂惇褰掑垂瑜版帒绠熼柨鐔哄Т绾惧潡骞栭幖顓熷▏濞存粍绮撻弻鈥愁吋鎼粹€茬盎婵炲濮嶉崨顏勪壕閻熸瑥瀚亸顐︽煟閹虹偤妾紒宀冮哺缁绘繈宕堕懜鍨珫婵犳鍠楅…鍫熴仈閹间焦鍎屽〒姘ｅ亾婵﹨娅ｇ划娆忊枎閹冨闂備礁婀遍幊鎾趁洪妶澶嬪仼闁绘垼濮ら崐鑽ょ磼濞戞﹩鍎愰柡鍜冪秮濮婅櫣绱掑Ο铏逛淮濠碘槅鍋勯惌鍌氱暦閹达箑绠荤€规洖娲﹀▓鏇㈡⒑閸涘﹥澶勯柛鎾寸洴瀹曘垽鏌嗗鍡忔嫼缂傚倷鐒﹂敋濠殿喖娲弻锝堢疀閺傚灝鎽甸悗瑙勬礈閺佸宕洪埀顒併亜閹烘垵顏柍閿嬪灴閹宕烽鐑嗏偓灞剧箾閸忕厧濮嶉柡灞剧洴婵℃悂濡疯閻撶喖姊虹紒妯圭繁闁哥姵顨堥幑銏犫攽鐎ｎ亞鍊為梺闈浤涢崘銊х杽濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柟缁㈠枛缁愭鎱ㄥ鍡楀幋闁哄妫冮弻锟犲炊閵夈儳浠鹃梺缁樻尰閻熴儵濡撮幒鎴僵妞ゆ帒鍊烽搹搴㈢節濞堝灝鏋涢柛濠傜秺閵嗗啴濡烽埡鍌氣偓鐑藉级閸喎绀冮柍褜鍓氱€笛囧Φ閸曨垰顫呴柨娑樺閸ｄ即姊洪崷顓х劸闁挎洏鍎遍銉╁礋椤掑倻鐦堥梺绋胯閸婃牠藟濠婂嫮绡€闁汇垽娼у暩闂佽桨鐒﹂幃鍌氱暦閹达附鍊烽柛婵嗗椤斿洦绻濋悽闈浶ｉ柤褰掔畺瀵即濡烽埡鍌滃幈闂侀€涘嵆濞佳囧几濞戞氨妫柟顖嗗瞼鍚嬮梺鍝勭灱閸犳牕鐣峰鍡╂Ь闁汇埄鍨遍惄顖炲蓟閿濆绠婚悗闈涙啞閸ｎ參姊洪棃娑欐悙閻庢碍婢橀锝嗙鐎ｎ€晝鎲告惔銊ラ棷妞ゆ洍鍋撴慨濠冩そ瀹曘劍绻濋崘顏勫汲缂傚倷绀侀ˇ顖炴偉婵傜鏄ラ柍褜鍓氶妵鍕箳閸℃ぞ澹曢梻浣筋嚙缁绘垿鎳濇ィ鍐ｂ偓锕傚垂椤斻儳鍠撴禍鎼佸冀瑜屾竟鏇炩攽椤旀枻渚涢柛瀣閻ｇ敻宕卞☉娆戝幗濠电偞鍨靛畷顒€鈻嶅鍥ｅ亾鐟欏嫭绀€闁绘牕銈搁妴浣肝旀担鍝ョ獮闁诲函缍嗛崑鍛存偟濠靛鈷掗柛灞剧懆閸忓瞼绱掗鍛仸鐎规洘绻堝浠嬵敄閸欍儲鐫忛梻浣告啞閸旓箓宕悢绋跨窞閻庯綆浜炵粣鐐烘⒑瑜版帒浜伴柛妯绘倐楠炲繑绻濆顓涙嫼缂備礁顑嗙€笛冿耿娴煎瓨鐓熼柣鏃€绻傚▔姘跺炊椤掍焦娅囬梺绋挎湰缁嬫捇宕㈤棃娑掓斀闁绘劕鐡ㄧ紞鎴炪亜閹存繂鈧灝鐣烽幋锕€绠婚柤绋跨仛閸庤鲸绻涙潏鍓хК妞ゎ偄顦垫俊闈涒攽鐎ｎ偆鍘告繛杈剧悼椤牓鍩€椤掆偓濞硷繝鐛崘顔肩畾鐟滃繘寮抽崱妞绘斀闁绘ɑ褰冮弳锝夋煛娴ｅ湱鐭掓慨濠傤煼瀹曟帒鈻庨幒鎴濆腐缂傚倷绶￠崳顕€宕圭捄铏规殾婵犻潧顑呯粻鎶芥煛閸愶絽浜炬繝娈垮灟閸楁娊寮婚妸鈺佸嵆闁绘劖绁撮崑鎾诲箹娴ｇ鍤戞繛鎾村焹閸嬫捇鏌＄仦鍓р槈闁伙絾绻堥崺鈧い鎺戝绾剧粯绻涢幋鐐寸殤婵☆偒鍨抽幉鎼佸籍閸繆鎽曞┑鐐村灟閸╁嫰寮崘顔界叆婵犻潧妫欑粈灞句繆閹绘帞澧涚紒缁樼箘閸犲﹤螣瀹勯澹曢梺鑲┾拡閸撴盯鎮￠幘缁樷拺闁告繂瀚﹢鎵磼鐎ｎ偄鐏撮柛鈹垮灪閹棃濡堕崶鈺傛緫闂備礁鎼ú銊﹀垔椤撱垹鑸归柛锔诲幘绾句粙鏌涚仦鍓ф噯闁稿繐鐬肩槐鎺楊敋閸涱厾浠梺鐟扮畭閸ㄨ棄鐣烽悡搴唵妞ゅ繐鎳愬ú瀵糕偓瑙勬礃閿曘垺淇婇幖浣割潊闁宠棄妫欑紞灞解攽閻樻剚鍟忛柛鐘愁殜閵嗗啴宕ㄩ鍥ㄧ洴瀵噣宕煎┑鍫㈡毇闂備焦瀵х换鍌炈囨导鏉戠厱闁圭儤鍤氳ぐ鎺撴櫜闁告侗鍠栭弳鍫ユ⒑閸濄儱鏋旈柛瀣仦缁岃鲸绻濋崶鑸垫櫇闂佹寧绻傞幊鎰閼测晝纾藉〒姘搐閺嬫稒銇勯鐘插幋闁绘侗鍠栬灒闁稿繒鍘ч悵浼存⒑閼规澘顥嶉柛鈺傜墵楠炲鎮ч崼銏㈢槇闂佹眹鍨藉褎绂掗敃鍌涚厱妞ゎ厽鍨甸悘锔锯偓瑙勬礈閹虫挾鍙呭銈呯箰鐎氼噣寮昏濮婃椽宕崟顕呮蕉闂佺瀛╅悡锟犲箖閿熺姴鍗抽柕蹇ョ磿閸樻捇姊虹€圭姵銆冪紒鈧笟鈧悰顔嘉熷Ч鍥︾盎闂婎偄娲﹂幐鐐櫠閺囥垺鐓熼柟鐑樺灩娴犳盯鏌曢崶褍顏鐐村笒椤撳ジ宕堕懜鏁屾粌鈹戦悩鎰佸晱闁哥姵鐗犺棟闁汇垻顭堥拑鐔衡偓骞垮劚閻楁粌顬婇妸鈺傗拺闁告稑锕ョ亸鎵偓鍏夊亾闁归棿闄嶉埀顑跨閳诲酣骞橀崘鎻掓暏婵＄偑鍊栭幐楣冨磻閵堝憘娑樼暋闁附瀵岄梺闈涚墕濡瑧澹曢悽鍛婄厱閻庯綆鍋呯亸鐢告煃瑜滈崜婵嬶綖婢跺⊕鍝勎熼悡搴＄亰闂佽宕橀褏绮婚弽顓熺厪闊洢鍎崇壕鍧楁⒒閸曨偄顏╂い顓℃硶閹瑰嫰鎮€涙ɑ鏆版俊鐐€栭幐绋款焽閳ユ剚娼栫紓浣股戞刊鎾煕濞戞﹫宸ラ柡鍡楃墦濮婃椽鎮烽悧鍫熷枑闂佺绻戦敃銏ょ嵁閸愵喗鍊烽柣鎴炆戝▍鍥⒑闁偛鑻晶鎾煙椤曗偓缁犳牠寮婚妸褉鍋撻敐搴濈敖缂佹劗鍋ゅ楦裤亹閹烘垳鍠婇梺鍛婏耿缁犳牕鐣烽姀銈庢晜闁告侗鍨抽惁鍫ユ⒑濮瑰洤鐏叉繛浣冲洤鐒垫い鎺戭槸閻忥妇鈧娲橀敃銏ゃ€侀幘娲绘晬婵☆垵銆€閸嬫捇寮介婧惧亾閸愵喖唯闁冲搫鍊搁埀顒勬敱閵囧嫯绠涢幘鎰佷紑婵炲濮存晶鐣屾閹惧瓨濯撮柧蹇曟嚀缁楋紕绱撴担绛嬪殭闁绘鎹囬悰顕€宕橀埡鍐炬祫闁诲函缍嗛崑鎺懳涢崘銊㈡斀闁绘劖顔栧Λ搴亜閺冣偓閸旀顕ユ繝鍐﹀亝闁告劑鍓敃鍌涚厱闁哄洢鍔岄悘鐘电磼椤愩垻效闁哄苯绉烽¨渚€鏌涢幘璺烘灈妤犵偛鍟抽ˇ褰掓煙椤旇娅婇柟宕囧█椤㈡鎷呯拠鈥虫櫗濠电姷鏁搁崑鐐差焽濞嗘挸瑙﹂悗锝庝憾閻掕姤绻涢崱妯诲碍缂佲偓閸愵喗鐓冪憸婊堝礈濞嗘挴鈧棃宕橀鍢壯囨煕閳╁厾顏堟儊閻戣姤鈷戦柛娑橈攻婢跺嫰鏌涢幘鏉戝摵闁诡噣娼ц灃闁告侗鍠掗幏濠氭⒑缁嬫寧婀伴柣鐔濆泚鍥晝閸屾稓鍘甸柣鐘叉厂閸涱垳妲囬柣搴ゎ潐濞叉鎹㈤崼銉ユ瀬闁告劦鍠栫壕鍏兼叏濡じ鍚€规洖鐖煎缁樻媴閸涘﹥鍎撶紓浣割儎缁舵艾鐣烽姀锛勵浄閻庯綆浜為敍?"
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

    resolved_scenario = _resolve_first_turn_guided_lane(
        scenario=str(context.get("scenario") or "").strip(),
        learner_message=message,
        reply=content,
    )
    if resolved_scenario in _GUIDED_DOMAIN_SCENARIOS:
        if _looks_like_generic_guided_review_fallback(summary):
            repaired_summary = _first_turn_lane_continuity_note(
                resolved_scenario,
                chinese=chinese,
                coach_context=context,
            )
            if repaired_summary:
                summary = repaired_summary
        if _looks_like_generic_guided_review_fallback(next_step):
            repaired_next_step = _first_turn_lane_next_step(
                resolved_scenario,
                chinese=chinese,
                coach_context=context,
            )
            if repaired_next_step:
                next_step = repaired_next_step

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
    if next_step_text:
        if chinese:
            for prefix in ("\u4e0b\u4e00\u6b65\uff1a", "\u4e0b\u4e00\u6b65:"):
                if next_step_text.startswith(prefix):
                    next_step_text = next_step_text[len(prefix) :].strip()
                    break
        else:
            lowered_next_step = next_step_text.casefold()
            for prefix in ("next step:", "next:"):
                if lowered_next_step.startswith(prefix):
                    next_step_text = next_step_text[len(prefix) :].strip()
                    break
    if not summary_text and not next_step_text:
        return ""
    if summary_text and summary_text[-1] not in ".!?。！？":
        summary_text = f"{summary_text}{'。' if chinese else '.'}"
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


_GUIDED_DOMAIN_SCENARIOS = {
    "remote_workspace",
    "debug_loop",
    "function_guidance",
    "project_adaptation",
}


def _guided_domain_inference_coach_context(coach_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(coach_context, dict):
        return []
    scenario = str(coach_context.get("scenario") or "").strip().lower()
    history_mode = str(coach_context.get("history_mode") or "").strip().lower()
    parts: list[str] = []
    if scenario:
        parts.append(scenario)
    if history_mode == "fresh_lane":
        return parts
    if scenario not in _GUIDED_DOMAIN_SCENARIOS:
        return parts
    for key in ("current_focus", "summary", "thread_summary", "thread_next_step"):
        value = coach_context.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return parts


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
    parts.extend(_guided_domain_inference_coach_context(coach_context))
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
        "远程",
        "远程开发",
        "远程工作区",
        "远程连接",
        "隧道",
        "容器",
        "凭据模式",
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
        "调试",
        "断点",
        "调用栈",
        "堆栈",
        "单步",
        "启动配置",
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
        "函数提示",
        "函数签名",
        "参数提示",
        "悬停",
        "查看定义",
        "转到定义",
        "引用",
        "补全",
    )
    if any(token in blob for token in function_tokens):
        return "function_guidance"

    project_tokens = (
        "existing project",
        "project adaptation",
        "adaptation",
        "migration",
        "migrate",
        "改造",
        "适配",
        "迁移",
        "接入现有项目",
    )
    if any(token in blob for token in project_tokens):
        return "project_adaptation"
    return None

def _clean_guided_domain_empty_reply(
    domain: str | None,
    *,
    response_language: str | None,
    coach_context: dict[str, Any] | None = None,
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
                "先把工作区边界说清楚，remote 才会变简单。继续停在 VS Code remote 这条线上："
                "先确认当前是 SSH、tunnels、dev container、WSL 还是 local，再确认文件实际在哪台机器上，"
                "以及 API key 应该留在 local 还是 remote。请只回 2 行：一行真实的工作区标签或路径，"
                "一行安全 credential mode 的判断。"
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
                "先把这一轮收束成一个可信的 VS Code debug loop。先复现一次，在第一个有意义的 "
                "state change 停下，再检查一个值、分支或 stack frame，不要先把叙述铺开。"
                "请只回 2 行：第一行写你准备停在哪里，第二行写你准备先检查哪一个点。"
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
                "先把这一轮留在 function guidance 这条线上。先从一个 live call site 开始，再按顺序用 "
                "hover、signature help、definition 把 contract 读稳。请只回 2 行：第一行写函数名，"
                "第二行写能证明它期望什么的 call site 或证据。"
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
                "先把这一轮留在 project adaptation 这条线上。先分清哪些必须稳定、哪些必须改变，"
                "再先落一个窄范围 adaptation，不要一开始就铺大。请只回 2 行：一行写必须保持稳定的行为，"
                "一行写你想先适配的第一道边界。"
            ),
            response_language,
        )
    return ""

def _clean_guided_domain_empty_reply_override(
    domain: str | None,
    *,
    response_language: str | None,
    coach_context: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    if domain == "remote_workspace":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so I kept this turn in the VS Code remote lane.",
                "provider 没有返回可见内容，所以我先把这一轮留在 VS Code remote 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Return one real workspace label or path and one sentence about the safe credential mode.",
                "请返回一个真实的工作区标签或路径，再补一句安全 credential mode 的判断。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Keep the lesson grounded in the real workspace boundary before widening the remote story.",
                "先把真实工作区边界说稳，再展开 remote 细节。",
                response_language,
            ),
        }
    if domain == "debug_loop":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so I kept this turn in one trustworthy debug loop.",
                "provider 没有返回可见内容，所以我先把这一轮收束成一个可信的 debug loop。",
                response_language,
            ),
            "next_step": _localized_text(
                "Tell me where you will pause first and which single value, branch, or stack frame you expect to inspect there.",
                "请告诉我你准备先停在哪里，以及你准备先检查哪一个值、分支或 stack frame。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Pause at one meaningful state change before widening the debug story.",
                "先在一个有意义的 state change 停下，再展开 debug 叙述。",
                response_language,
            ),
        }
    if domain == "function_guidance":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so I kept this turn in the function-guidance lane.",
                "provider 没有返回可见内容，所以我先把这一轮留在 function guidance 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Return the function name, what it expects, and which call site proves that reading.",
                "请返回函数名、它期望什么，以及哪个 call site 能证明这个判断。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Keep the contract anchored to one live call site before widening the explanation.",
                "先把 contract 锚定在一个 live call site 上，再展开解释。",
                response_language,
            ),
        }
    if domain == "project_adaptation":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so I kept this turn in the project-adaptation lane.",
                "provider 没有返回可见内容，所以我先把这一轮留在 project adaptation 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Tell me which existing behavior must stay stable, what must change, and the first boundary you want to adapt.",
                "请告诉我哪个现有行为必须稳定、哪一部分必须改变，以及你想先适配的第一道边界。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Separate stable behavior from change scope before widening the adaptation plan.",
                "先分清稳定面和变更面，再扩大 adaptation 计划。",
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
    if isinstance(general_override, dict):
        summary = str(general_override.get("summary") or "").strip() or summary
    next_step = (
        str(domain_override.get("next_step") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    if not next_step and isinstance(general_override, dict):
        next_step = str(general_override.get("next_step") or "").strip()
    teaching_note = (
        str(domain_override.get("teaching_note") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    if not teaching_note and isinstance(general_override, dict):
        teaching_note = str(general_override.get("teaching_note") or "").strip()
    if not summary:
        if reason == "reanchor":
        summary = _localized_text(
            f"I kept this turn inside {spec['lane_en']}.",
            f"这一轮我继续留在{spec['lane_zh']}里。",
            response_language,
        )
    else:
        summary = _localized_text(
            f"{summary_prefix[0]}, so I kept this turn inside {spec['lane_en']}.",
            f"{summary_prefix[1]}锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦ㄤ簡{spec['lane_zh']}銆?",
            response_language,
        )
    next_step = _localized_text(spec["next_en"], spec["next_zh"], response_language)
    teaching_note = _localized_text(spec["note_en"], spec["note_zh"], response_language)
    if reason == "reanchor":
        reply = _localized_text(
            f"I will keep this turn inside one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"这一轮我先用一个更小的{spec['unit_zh']}把它接住。\n\n下一步：{next_step}",
            response_language,
        )
    else:
        reply = _localized_text(
            f"{reply_prefix[0]}, so I will keep the work alive with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"{reply_prefix[1]}锛屾墍浠ユ垜鍏堢敤涓€涓洿灏忕殑{spec['unit_zh']}鎶婅繖涓€杞帴浣忋€俓n\n涓嬩竴姝ワ細{next_step}",
            response_language,
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
            "guided": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎妯恍氱紓鍌氬€烽懗鑸垫叏闁垮绠鹃柍褜鍓熼弻鈥崇暆閳ь剟宕伴弽褏鏆︽繝濠傛－濡查箖鏌ｉ姀鈺佺仭闁烩晩鍨跺璇测槈濮橈絽浜鹃柨婵嗗暙婵″ジ鏌嶈閸撴氨鎹㈤崼婵愬殨濠电姵鑹鹃崡鎶芥煟閺冨洦顏犳い鏃€娲熷铏圭磼濡搫袝闂佸憡鎸诲畝鎼佸箖閻㈢绫嶉柛顐ゅ暱閹锋椽姊虹涵鍛汗闁稿绋掓穱濠冪附閸涘﹦鍘辨繝鐢靛Т閸嬪棝鎮℃總鍛婄厱闁宠鍎虫禍鐐繆閻愵亜鈧牜鏁幒妤€绐楁慨姗嗗墻閻掍粙鏌熼柇锕€骞樼紒鐘荤畺閺屾稑鈻庤箛锝喰ㄦ繝鈷€灞奸偗闁诡噯绻濇俊鑸靛緞鐎ｎ剙寮抽梻浣告惈濞层劑宕戝☉娆戭洸闁规鍠氱壕鐣屸偓骞垮劚濡稒鏅堕悽鍛婄厸鐎光偓鐎ｎ剛鐦堥悗瑙勬礀閻栧ジ宕洪敓鐘茬劦妞ゆ帒鍊归～鏇犫偓瑙勬礀濞诧箓宕伴幇鐗堢厽婵°倐鍋撻柣妤€妫涚划顓㈠箳閺冨倻锛滈梺閫炲苯澧寸€规洘甯￠幃娆戔偓鐢殿焾楠炲牓姊绘繝搴′簻婵炶绠撻幊婵嬫倷椤掑偆娲搁梺闈╁瘜閸樺墽澹曟總鍛婂€甸柨婵嗙凹缁ㄨ偐鈧懓鎲＄换鍕閹烘挻缍囬柕濠忕畱闂夊秹姊洪悷鏉挎Щ闁硅櫕锕㈤悰顕€骞樼拠鑼唺閻庡箍鍎遍幏瀣涘鍫熲拻闁稿本鑹鹃埀顒傚厴閹虫宕奸弴妞诲亾閿曞倸閱囬柕澶涚畱閸撹埖绻濋棃娑樷偓濠氣€﹂崼銏狀棜濠电姵纰嶉悡鐔兼煙闁箑鏋涢柛鏂款儔閺屾稓鈧綆浜滈埀顒€娼″濠氭晸閻樿尙鍊為梺瀹犳〃閻掞箓鎮楅鐔虹閻庢稒顭囬惌瀣磼椤旇姤宕岀€殿喖顭烽幃銏ゆ偂鎼达綁鐛撻梻浣稿閻撳牓宕抽鈧鎶藉閵堝棌鎷洪柣鐘叉礌閳ь剝娅曢悘鏇㈡⒑缁嬫鍎愰柛鏃€顨呭嵄闁圭増婢樼粻铏繆閵堝嫮顦﹀ù婊冪秺濮婃椽骞嗚缁傚鏌涚€ｎ亜顏€殿喖鍟胯灃闁告劦浜為敍婵囩箾鏉堝墽瀵肩紒顔界懇瀹曨偄煤椤忓懎浠哄銈嗙墬椤ㄥ懏鏅堕幓鎹涘酣宕惰闊剚顨ラ悙瀵稿闁瑰嘲鎳庨湁閻庯綆浜欐竟鏇㈡⒑閹稿孩绀€闁稿﹤鎽滅划濠氭晲閸℃瑧鐦堥梻鍌氱墛缁嬫帞绮婇埡鍛厱闁绘劕顕崣鈧┑顔硷工椤嘲鐣烽幒鎴僵妞ゆ垼妫勬禍鍓х磼鐎ｎ偓绱╂繛宸簻鍥存繝銏㈡缁犳垵煤椤撱垹绠栭柣锝呯灱閻瑩鏌ら幇浣哥仭闁硅弓鍗冲缁樼瑹閳ь剙顭囪閳ワ箓宕奸妷銉э紵濡炪倖娲嶉崑鎾垛偓娈垮枔閸斿秶绮嬮幒鏂哄亾閿濆骸浜為柛姗€浜跺娲棘閵夛附鐝旈梺鍛婄懄閸旀瑩鐛€ｎ喗鏅濋柍褜鍓涚划濠氬冀閵娧咁啎闂佺硶鍓濊摫閻忓繋鍗抽弻锝夊箻鐎涙顦伴梺鍝勭焿缂嶄礁顕ｉ鍕閹肩补鍓濆▓姗€姊绘担渚劸闁挎洏鍎靛畷婵嗏枎閹惧疇鎽曢梺鎸庣☉鐎氼亜鈻介鍫熷仯闁搞儯鍔庨妶鎾煕鐎ｎ偅灏柍瑙勫灩閳ь剨缍嗛崜娆戠矈閿曞倹鈷戠憸鐗堝笒娴滀即鏌涘Ο鍦煓鐎规洘娲熼幃銏ゅ礂閼测晛寮虫繝鐢靛█濞佳兾涘▎鎾嶅顭ㄩ崟顓狀啎闂佸憡渚楅崰鏍倶鐎涙ɑ鍙忓┑鐘插亞閻撹偐鈧娲樼敮鎺楋綖濠靛鏁囬柣鏃傤焾閳ь剟鏀辨穱濠囨倷椤忓嫧鍋撹娣囧﹪宕堕鈧弸渚€鎮归崶褎鈻曢柛銈嗘礀閳规垿鎮╃€圭姴顥濋柟顖滃枛濮婃椽妫冨☉杈ㄐら梺鎼炲妽濡炶棄顕ｉ鍕劦妞ゆ帒瀚埛鎺懨归敐鍫燁仩闁靛棗锕弻娑㈠箻鐎靛摜鐤勯梺杞扮椤戝懘鍩為幋锔藉€烽柛娆忣槸閺嗕線姊洪崨濠佺繁闁搞劍濞婇弫宥呪攽閸モ晝顔曢柡澶婄墕婢т粙宕氭导瀛樼厵缁炬澘宕禍浼存煟鎼淬劍鏁辩紒缁樼箞閹粙妫冨☉妤冩崟闂備胶鎳撻崯璺ㄦ崲閹邦喖寮叉繝鐢靛Т閿曘倝鎮ч崱娆戜笉闁哄被鍎查悡蹇涚叓閸ャ劍绀€鐞氥儱鈹戦埄鍐ㄧ祷闁绘鎹囧濠氬即閿涘嫮鏉搁柣搴秵娴滅偞绂掓總鍛婂仭婵犲﹤瀚欢鏌ユ倵濮樼厧澧撮柍銉︽瀹曟﹢顢欓崲澹洦鐓曢柍鈺佸幘椤忓牆姹叉俊銈呮噺閳锋垹绱掔€ｎ偒鍎ラ柛搴㈠姉缁辨帞鈧綆鍋呯亸鐢告煕閹烘挸绗氱紒缁樼箞瀹曞爼鎳滈崹顐ｇ彣闂傚倷绶氶埀顒傚仜閼活垱鏅剁€涙﹩娈介柣鎰絻閺嗘瑩鎽堕弽顓熺厓鐟滄粓宕滈悢鐓庢槬闁靛繈鍊曠粻濠氭偣閸ャ劌绲婚柣搴幖椤啴濡堕崱妯锋嫽闂佸搫鎷嬮崑鍛矉瀹ュ鍊烽柣銏㈡暩閿涙繈姊虹粙鎸庢拱闁荤啙鍛濞寸厧鐡ㄩ悡鏇㈡煟濡澧繛鍫熺矒閺岀喖顢欓幆褍骞嬫繝纰夌磿閸忔﹢宕洪敓鐘茬＜婵﹩鍋呴崑鍛存⒒閸屾瑨鍏岀紒顕呭灦瀹曞綊鎮￠獮顒佺洴瀹曠喖顢橀悩杈╃憹婵犳鍠楅…鍫ュ春閺嶎厼鐓曢柟瀵稿亼娴滄粓鏌熼幆褍鑸瑰┑顔煎€规穱濠勭磼閵忕姵鐏堝銈庡亖閸ㄨ棄鐣烽崼鏇ㄦ晢濞达絽寮剁€氳棄鈹戦悙鑸靛涧缂佹彃娼￠幃娲籍閸繂鎯炲┑鐐叉閹稿宕愰崹顐ょ闁瑰鍋涚粭姘箾閸涱厽顥犵紒杈ㄥ笒閻ｆ繈宕熼鍛灓闂備礁婀遍崢褏绱炴繝鍥ц摕闁告侗鍘稿Σ鍫熸叏濮楀棗澧柍閿嬫礀閳规垿鎮╅崹顐ｆ瘎闂佺顑嗙粙鎴ｇ亱濠电偛妫欓幐鎼佸垂閸岀偞鐓曟い鎰剁稻缁岃法绱撳鍡欏⒌闁哄矉绻濆畷鍫曞Ψ閵壯傜棯闂備胶绮幐濠氭偡閳哄懎钃熼柣鏃傚劋閸犲棝鏌涢弴銊ヤ簻鐞氭繈姊绘担瑙勫仩闁稿﹥鐗犻幃鐤樄闁诡垪鍋撳銈呯箰閻楀棛绮诲杈ㄥ枑鐎广儱顦粻鏍煙鏉堥箖妾柣鎾寸懃閵嗘帒顫濋鍌欒檸婵犵鈧啿鎮戦柕鍥у椤㈡洟鏁愰崶鈺冨帨闁诲氦顫夊ú鏍х暦椤掑啰浜欓梻渚€鈧偛鑻晶鎵磼椤旀鍤欓悡銈嗐亜韫囨挻鍣抽柟鐤缁辨挻鎷呴崜鎻掑壈闂佽绻戠换鍫ャ€佸Δ鍛潊闁靛牆妫涢崢鐢告⒑閼姐倕鏋斿褎顨婂畷鏉课熷ú缁橆啍闂佺粯鍔栬ぐ鍐汲濞嗘挻鐓熼柨婵嗙箳缁♀偓闂佸搫鑻ú顓㈠极閸岀偛绠氱憸宥呅ч弻銉︹拻闁稿本鐟чˇ锕傛煙濞村澧茬紒妤冨枎铻栭柛娑卞幘閻撴垿鏌熼崗鑲╂殬闁告柨鑻晥闁告瑥顦禍婊堟煙閹冭埞闁诲浚浜弻宥夋煥鐎ｎ亞浼岄梺鍝勭焿缂嶄線鐛€ｎ喖绫嶉柍褜鍓欓埢宥夊幢濡偐顔曢梺鍛婁緱閸犳鐣峰畝鍕厸閻忕偛澧藉ú鏉戔攽閳╁啯鍊愬┑鈩冩倐閺佸倹绌遍幍浣镐壕闁归偊鍓﹀〒濠氭煏閸繃顥炵紒宀冩硶缁辨挸顓奸崟顓犵崲闂侀潧妫旂欢姘嚕閹绢喖顫呴柣娆屽亾婵炵厧锕铏光偓鍦У閵嗗啴鏌ｉ幒鐐电暤鐎规洘鍔欓、娑㈡倷缁瀚藉┑鐐舵彧缂嶁偓妞ゎ偄顦靛畷鎴︽偐缂佹鍘遍柟鑲╄ˉ濡插懘鎮￠崗鍏煎弿濠电姳鑳堕惌娆戔偓瑙勬礈閸犳牠銆佸☉姗嗘僵濡插本鐗楁晥闂傚倸鍊风粈渚€骞夐敓鐘茬闁挎洖鍊哥粣妤佷繆閵堝懏鍣归柣鎾存礋閺岀喐娼忔ィ鍐╊€嶉梺缁樻尵婵炩偓闁哄瞼鍠栭、姗€鎮㈡搴ｆ噯闂備礁鎲￠幖鈺呭储娴犲桅闁告洦鍠氶悿鈧梺瑙勫礃濞夋盯骞冪€ｎ喗鈷戦柟鑲╁仜閸旀挳鏌涢幘瀵告噮闁汇儺浜ｉˇ瑙勵殽閻愬澧遍柍褜鍓氱粙鎺曟懌闁诲繐绻嬮崡鎶藉蓟閿濆棙鍎熼柕寰涢铏庢繝娈垮枛閿曘儱顪冮挊澶屾殾闁靛濡囩弧鈧梺绋挎湰椤曟挳寮撮姀鈾€鎷洪梺鍛婄缚閸庤鲸鐗庢俊鐐€戦崝宀勬晝椤忓嫮鏆﹂柛婵嗗濡插牓鏌曡箛鏇炐ユい鎾存そ濮婅櫣绱掑Ο蹇ｄ邯閹ê顫濋懜鍨珫闂婎偄娲﹂幖鈺併€掓繝姘厪闁割偅绻冮ˉ鐐烘倶韫囨洘鏆柡灞剧〒閳ь剨缍嗛崜娆愮鏉堚斁鍋撶憴鍕濠电偛锕獮鏍亹閹烘垶宓嶅銈嗘尵閸ｏ妇妲愰埄鍐х箚闁绘劦浜滈埀顒佺墵楠炴劙宕奸弴鐐茬€繝鐢靛У绾板秹宕戦埡鍌滅鐎瑰壊鍠曠花濂告煟閹惧娲撮柟顔斤耿閹瑦锛愬┑鍡橆唲濠电姵顔栭崰鏍磹婵犳艾鐒垫い鎺嶇贰閸熷繘鏌涢悩鎰佹當妞ゎ厼娲ら埢搴ㄥ箳閺傛崘鍩呴梻鍌欐祰瀹曠敻宕戦悙鐢电煓闁割偁鍎遍悞鍨亜閹哄棗浜鹃梺鍛娚戦悧妤冪博閻旂厧鍗抽柕蹇婃閹锋椽姊洪崨濠勭畵閻庢凹鍣ｉ崺銏″緞閹邦厾鍘卞┑鈽嗗灠閻忔繃绂嶉崷顓犵＜妞ゆ梻鈷堥悡濂告煙椤旂晫鎳囬柟顔界矊铻ｉ柣鎾抽婵″洦绻濋悽闈浶ラ柡浣规倐瀹曟垿鎮㈤悡搴ｏ紱闂佸湱鍋撻弸濂稿几瀹ュ鐓曟繛鎴烆焽閹界娀鏌ｉ幘璺烘灈闁哄瞼鍠栭獮鍡氼檨闁搞倗鍠愮换娑㈠矗婢跺鍞夐梺鍝勭焿缁辨洘绂掗敃鍌氱鐟滃鍩€椤掍礁绗掗棁澶愭煟濞嗗繑鍣介柣锝囨暩閳ь剝顫夊ú妯煎垝韫囨蛋鍥敊閹存帞绠氶梺鍦帛鐢偞鏅堕弴鐔翠簻妞ゅ繐瀚弳锝呪攽閳ュ磭鍩ｇ€规洏鍔戦、妯款槻濠碉紕鍏樺缁樻媴閻戞ê娈岄梺纭咁嚋缁绘繈鐛崘顔肩＜闁绘劕寮跺Σ顒勬⒑缂佹ê濮囬柟纰卞亞缁鏁愭径瀣弳闂佸搫鍟ú锕偹夋径濞掔懓顭ㄩ崘顏喰ㄩ梺鍝勭焿缂嶄線骞冮埡鍛煑濠㈣泛锕ら懠鍐⒒娴ｅ憡鍟為柛鎿冨墴瀹曘劑顢涘鍐ㄧ畱闂傚倸鍊搁崐鎼佸磹閹间礁纾归柣鎴ｅГ閸ゅ嫰鏌涢锝嗙８闁逞屽厸閻掞妇鎹㈠┑瀣＜婵°倓鑳堕埀顒佹そ濮婃椽宕崟顒€鍋嶉梺鎼炲妼濠€杈╁垝閸喎绶為悗锝傛櫇缁犳岸姊洪棃娑氬闁稿﹤鎲＄粋宥嗐偅閸愨晝鍘卞┑掳鍊曢幊宥夊箟妤ｅ啯鐓涚€光偓閳ь剟宕伴弽顓炶摕闁搞儺鍓氶弲婵嬫煃瑜滈崜姘跺疾閸撲胶纾兼俊顖濆亹椤旀洟鏌ｈ箛鎾剁闁绘顨呴埢宥嗙節閸ャ劎鍘搁柣蹇曞仩椤曆囧焵椤掍胶绠撻柣锝囧厴椤㈡洟鏁冮埀顒€鏁梻浣瑰濡焦鎱ㄩ妶澶嬪剨閹兼番鍔嶉埛鎺懨归敐鍛暈闁哥喓鍋ら弻銊╁即濡櫣浠剧紓浣稿€哥粔鍫曞箲閸曨剛鐟规い鏍ㄧ〒缁嬩焦绻濋悽闈涗粶婵☆垰锕ョ粋宥咁煥閸繄顔夐梺鐓庢憸閸嬶絾绂嶅鍫熺厵闁硅鍔栫涵鎯归悩宕囩煀闁宠鍨块崺鍕礃閳瑰じ铏庢繝娈垮枛閿曘儱顪冮挊澶屾殾妞ゆ劧绠戠粈瀣亜閺囩偞鍣洪柦鎴濐樀濮婄粯鎷呴崨濠傛殘濠殿喖锕ょ紞濠傜暦瑜版帒绠伴幖瀛樼箘缁犳岸姊洪崷顓℃闁哥姵鐗滄竟鏇熺附閸涘﹦鍘介梺褰掑亰閸ㄤ即鎯冮悜妯镐簻閿滃宕堕妸銏″闂備胶顭堢换妤呭磻閹版澘围闁圭虎鍠楅悡娑㈡煕濞戝崬鏋ょ紒鐘靛仦閵囧嫰濮€閿涘嫭鍣伴悗娈垮枟閹歌櫕鎱ㄩ埀顒勬煃闁款垰浜鹃梺褰掓敱濡炰粙寮婚敐澶嬪亜闁告縿鍎查崳褔鏌ｆ惔銏犲毈闁告挾鍠庨悾宄扳攽鐎ｎ€冾熆鐠轰警鍎戦柛姗€浜跺铏圭磼濡椿妫冮梺琛″亾闂侇剙绉寸壕濠氭煏婢跺棙娅嗛柣鎾崇箻閺屾盯鍩勯崘鐐暥闂侀€炲苯澧柣蹇旂箞閹儳鐣￠幏鏃傚枛瀹曟鎮℃惔銏＄彺婵犵數鍋犻幓顏嗗緤閸ф纾块柕鍫濐槸閸氬綊鏌嶈閸撴瑩鈥旈崘顔嘉ч幖绮光偓宕囶唹闂備礁鎲″褰掑垂閻㈠憡鍋╅柣鎴ｅГ閸嬪嫮鐥幏宀勫摵闁哄拑缍佸铏圭磼濡儵鎷诲銈庡幖閻楁挸顕ｉ弻銉ヤ紶闁靛／鍜冪闯闂備胶顭堥張顒勬嚌妤ｅ啫鐒垫い鎺戝€搁崢鎾煙閾忣偒娈滈柟铏矒瀹曞綊顢曢姀鐘辩礋闂傚倷鐒﹂惇褰掑垂婵犳艾鏋侀柟闂寸劍閸庢绻涢崱妯诲鞍闁绘挻鐟╅弻鐔烘喆閸曨偄袝闂佹悶鍊栭悷鈺呭蓟閿濆绠抽柟瀵稿С缁敻姊洪棃娑欐悙閻庢矮鍗抽悰顕€骞掑Δ鈧粻锝嗐亜閺嶃劎鈯曢柡鍡曞嵆濮婄粯绗熼埀顒勫焵椤掑倸浠滈柤娲诲灦瀹曘垽鎮介崨濠勫幈闁瑰吋鐣崝宥呪槈瑜旈弻锝夋晲閸涱厽些闁句紮绲剧换娑㈠幢濞嗗繋澹曞ù婊勭☉閳?",
            "balanced": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎妯恍氱紓鍌氬€烽懗鑸垫叏闁垮绠鹃柍褜鍓熼弻鈥崇暆閳ь剟宕伴弽褏鏆︽繝濠傛－濡查箖鏌ｉ姀鈺佺仭闁烩晩鍨跺璇测槈濮橈絽浜鹃柨婵嗗暙婵″ジ鏌嶈閸撴氨鎹㈤崼婵愬殨濠电姵鑹鹃崡鎶芥煟閺冨洦顏犳い鏃€娲熷铏圭磼濡搫袝闂佸憡鎸诲畝鎼佸箖閻㈢绫嶉柛顐ゅ暱閹锋椽姊虹涵鍛汗闁稿绋掓穱濠冪附閸涘﹦鍘辨繝鐢靛Т閸嬪棝鎮℃總鍛婄厱闁宠鍎虫禍鐐繆閻愵亜鈧牜鏁幒妤€绐楁慨姗嗗墻閻掍粙鏌熼柇锕€骞樼紒鐘荤畺閺屾稑鈻庤箛锝喰ㄦ繝鈷€灞奸偗闁诡噯绻濇俊鑸靛緞鐎ｎ剙寮抽梻浣告惈濞层劑宕戝☉娆戭洸闁规鍠氱壕鐣屸偓骞垮劚濡稒鏅堕悽鍛婄厸鐎光偓鐎ｎ剛鐦堥悗瑙勬礀閻栧ジ宕洪敓鐘茬劦妞ゆ帒鍊归～鏇犫偓瑙勬礀濞诧箓宕伴幇鐗堢厽婵°倐鍋撻柣妤€妫涚划顓㈠箳閺冨倻锛滈梺閫炲苯澧寸€规洘甯￠幃娆戔偓鐢殿焾楠炲牓姊绘繝搴′簻婵炶绠撻幊婵嬫倷椤掑偆娲搁梺闈╁瘜閸樺墽澹曟總鍛婂€甸柨婵嗙凹缁ㄨ偐鈧懓鎲＄换鍕閹烘挻缍囬柕濠忕畱闂夊秹姊洪悷鏉挎Щ闁硅櫕锕㈤悰顕€骞樼拠鑼唺閻庡箍鍎遍幏瀣涘鍫熲拻闁稿本鑹鹃埀顒傚厴閹虫宕奸弴妞诲亾閿曞倸閱囬柕澶涚畱閸撹埖绻濋棃娑樷偓濠氣€﹂崼銏狀棜濠电姵纰嶉悡鐔兼煙闁箑鏋涢柛鏂款儔閺屾稓鈧綆浜滈埀顒€娼″濠氭晸閻樿尙鍊為梺瀹犳〃閻掞箓鎮楅鐔虹閻庢稒顭囬惌瀣磼椤旇姤宕岀€殿喖顭烽幃銏ゅ礂閼测晛濮洪梻浣瑰濞插秹宕戦幘缁樼厸閻庯綆鍋嗛妴鎺楁煃瑜滈崜姘辩矙閹烘梹宕查柛顐ｇ箥濞兼牠鏌ц箛姘兼綈閻庢碍宀搁弻娑樷枎韫囷絾楔濡炪倐鏅欓崡鍐差潖濞差亝顥堥柍鍝勫暟鑲栫紓鍌氬€哥粔宕囩矆娓氣偓椤㈡岸鏁愰崱娆戠槇濠殿喗锕╅崕浣冾樄闁哄本鐩俊鐑藉閳╁啰褰囬梻浣虹帛閹稿骞戦崶顒€钃熼柨婵嗩槹閸嬫劙鏌涜箛鎾村殌闁糕晛鎳樺娲川婵犲啰鍙嗛梺娲诲幖閸婂潡鐛崘顔芥櫢闁绘ê鍟挎禍婊堟⒑缁嬭法绠伴柣銊у厴楠炲繐煤椤忓應鎷洪梺鍛婄☉閿曪妇绮婚幘缁樺€垫慨妯煎帶濞呭秹鏌熼鎯т户闁圭懓瀚版俊姝岊槾闁挎稒绮庣槐鎾诲磼濞嗘垵濡藉銈庡幖濞层劎鍒掓繝姘缂備焦顭囬崢浠嬫⒑閹稿海绠撴繛灞傚€濆畷銏⑩偓娑欙供濞堜粙鏌ｉ幇顓熺稇婵炴惌鍠楅〃銉╂倷瀹割喖鍓跺銈冨灪閿曘垽骞冮埡鍛闁圭儤鎹佺欢銏ゆ⒒閸屾艾鈧悂宕愭搴ｇ焼濞撴埃鍋撴鐐差樀閸ㄥ墽鎼炬担瑙勩仢闁轰礁鍟村畷鎺戭潩閹插骞㈤梻鍌欑閹诧紕绮欓幋锔藉仱闁靛ň鏅涚壕濠氭煃閸濆嫬鈧埖绂嶅鍫熺厵闁绘垶锚閻忋儲銇勮箛锝勯偗闁哄苯绉归弻銊р偓锝庝簽閻熴劑姊婚崶褜妯€闁哄被鍔岄埞鎴﹀幢濡櫣鐛╅梻浣侯攰濡嫰宕愰崸妤€钃熸繛鎴欏灩鍥撮梺鍛婁緱閸樿棄鈻撴繝姘拺闁告繂瀚﹢浼存煟閳哄﹤鐏︽鐐插暣閸╋繝宕ㄩ鐘垫澑濠电偠鎻徊钘夛耿闁秴姹叉い鎾卞灪閳锋帒霉閿濆懏鍟為柛鐔哄仱閹粙顢涘☉杈ㄧ暭闂佽桨绶￠崳锝夊极閹剧粯鍋愰梻鍫熺〒閵堬附绻濈喊妯活潑闁搞劑娼ч埢宥夋晲婢跺﹥杈堥梺鎸庢礀閸婂綊鎮￠弴銏＄厪濠㈣埖绋撻崚鏉库攽闄囨慨銈夊Φ閸曨垰绫嶉柍褜鍓欑叅婵☆垵宕甸埞宥呪攽閻樺弶澶勯柛濠囨敱閵囧嫯绠涢幘鎰佷槐闂佺顑嗛幑鍥ь嚕閹绢喗鍋愰柛鎰絻缁ㄣ儵姊绘担鍝ョШ闁稿锕畷鏇㈡濞戞帗顫嶉梺闈涚箳婵敻藟濠靛鐓欓柣鎾虫捣閹界娀鏌熺粙娆剧吋闁诡噯绻濇慨鈧柣娆屽亾婵炴挸顭烽弻鏇㈠醇濠靛洤娅х紓浣哄С閸楁娊寮婚敐鍛傛棃鍩€椤掑嫭鏅濇い蹇撶墕缁犳牠鏌ㄩ悢鍝勑ｉ柛瀣閺屾稖绠涘顑挎睏闂佸憡鐟ュΛ妤呭煘閹达附鍋愮紓浣股戦柨顓炩攽閳藉棗浜濋柣鐔叉櫅閻ｇ兘骞庨懞銉モ偓缁樹繆椤栨繂浜归柣锕€鐗撳娲焻閻愯尪瀚板褎鎸抽弻鐔碱敊閵娿儲鎼愰梺鍗炴喘閺屾洝绠涚€ｎ亞浼勫┑鈩冨絻濞差厼顫忕紒妯肩懝闁逞屽墮椤洩顦虫い銊ｅ劥缁犳盯寮撮悤浣圭稐闂備礁鎼ú銊╁窗閹邦兘鏋嶉柣妯肩帛閻撴洘銇勯鐔风仴濞存粍绻堥弻娑樷枎韫囨洜顔囬梺瀹狀潐閸ㄥ潡骞冮埡鍛煑濠㈣泛锕ラ鈩冧繆閻愵亜鈧洜鎹㈤幒鎾村弿濡炲瀛╅～鏇㈡煙閻戞ɑ灏扮紓宥呮喘閺屾洘绻涢崹顔煎Б闂佽崵鍠嗛崝鎴﹀蓟瑜庣€电厧鈻庨幋鐘樻粓姊洪崫鍕潶闁稿﹥娲熷﹢渚€鏌ｆ惔顖滅У闁稿鎳橀幃鐢稿冀椤撶啿鎷洪梺鍛婄☉椤偓闁瑰濮甸弳婊堟煙閻戞﹩娈旈柣鎾达耿閺岀喐娼忔ィ鍐╊€嶉梺绋款儐閸旀牠濡甸崟顖氱疀闁告挷绀侀崺灞筋渻閵堝懘顎楃紒缁樏～蹇撁洪鍕獩婵犵數濮撮崯浼此囬妷鈺傗拺閻犲洩灏欑粻鑼偓鍏夊亾闁归棿绀佺粻鏍旈敐鍛殲闁稿﹤顭烽弻銈夊箒閹烘垵濮夐梺褰掓敱濡炶棄顫忕紒妯肩懝闁搞儜鍌滃嚬缂傚倷绀侀鍡涘箲閸ヮ剙鏄ラ柣鎰惈缁犺櫕淇婇妶鍕厡闁告﹢浜跺娲传閸曨偅娈滈梺绋款儐閹瑰洭寮诲☉銏犖╃憸搴ㄥ汲椤掑嫭鐓欐い鏇楀亾缂佺姵鐗犻獮鍐煥閸喎娈熼梺闈涱槶閸庢壆鑺遍懡銈囩＝濞达絽鎼禍鎯р攽椤栨繂袚闁靛洦妫冮獮鏍ㄦ媴閸濄儲鐓ｆ俊鐐€栧濠氬磻閹剧粯鐓冮悷娆忓閻忓瓨銇勯姀锛勬噰鐎殿噮鍓熸俊鍫曞醇濮橆兛澹曢柣鐘充航閸斿骸螞椤栨稏浜滈柟鎹愭硾閺嬫垿鏌涙繝鍐ㄥ闁逞屽墲椤煤韫囨稑纾块柟鎯版閻掑灚銇勯幒鎴姛缂佸鏁婚弻娑㈡偐閹颁焦鐤侀梺绯曟櫆閻╊垶鐛€ｎ喗鏅滈柦妯侯槷閸栨牠姊绘担瑙勫仩闁稿寒鍨跺畷婵嗙暆閳ь剙顕ユ繝鍐瘈婵﹩鍘鹃崢閬嶆⒑闂堟稓澧曢柣妤€鎳樺畷銉╊敃閵堝洨锛滈柡澶婄墑閸斿苯霉椤曗偓閺岀喎鐣烽崶顬儵鏌熼悷鏉款伃闁诡垰瀚伴獮鎺楀箻閺夋垹锛撻梻浣告惈閻鎹㈠┑鍡欐殾闁靛ň鏅涚痪褔鎮归幁鎺戝閻㈩垰娼″缁樻媴缁涘娈愰梺鎼炲妼瀹曨剝鐏嬮梺鍛婂姦閸犳牠寮告笟鈧弻鐔兼偋閸喓鍑￠梺缁樺姇閿曨亪寮诲澶婁紶闁告洦鍋呭▓顓熺節濞堝灝鏋涢柟璇х磿閹广垹鈹戠€ｎ偄浠洪梻鍌氱墛閸掆偓闁绘劗鍎ら悡鏇㈡煏婵炲灝鍔橀柛瀣ㄥ灮閳ь剝顫夊ú妯侯渻閽樺鍤曞ù鐘差儛閺佸洭鏌ｉ幇顓у晱婵¤尙鍏樺缁樻媴閸涘﹥鍎撶紓浣割儎缁舵艾鐣烽姀锛勵浄閻庯綆浜為敍娑㈡⒑缁嬭法鐏遍柛瀣仱閹€斥槈閵忥紕鍘遍梺闈涱檧缁蹭粙宕濆鑸电厽闊浄绲奸柇顖炴煛瀹€瀣М妤犵偞顭囬埀顒勬涧閹诧繝宕抽弶搴撴斀妞ゆ梻銆嬮弨缁樹繆閻愭壆鐭欓柕鍡曠椤粓鍩€椤掍椒绻嗘慨婵嗙焾濡查箖姊洪崫鍕棤濠殿喚鏁搁幑銏犫攽鐎ｎ亞鍘遍梺閫炲苯澧寸€规洜鍠栭、鏇㈩敃閿濆孩顥嬮梻鍌氬€风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼顢涘鍛紲闁诲函缍嗛崑鍕箔瑜旈弻鐔肩嵁閸喚浼堥悗瑙勬礈閸樠囧煘閹达箑绠涙い鎾跺Х閳诲鈹戦悩鍨毄闁稿绋戣灒濠电姴鍟伴々鍙夌節婵犲倸顏╂い鏇憾閺岋絽螣閼测晛绗￠梺缁樻尭缁绘劙鈥︾捄銊﹀磯闁惧繒鎳撻。娲⒑閸涘﹥宕岀紒鐘崇墵瀵寮撮敍鍕澑闁诲函缍嗘禍鏍磻閹捐鍐€妞ゆ挾鍠庢禍妤€鈹戦悙鍙夘棡闁圭顭烽幃锟犳晲婢跺苯褰勯梺鎼炲劦椤ユ捇宕氶弶妫电懓顭ㄩ崟顓犵厐闂佸疇顫夐崹鍧椼€佸▎鎾村殐闁宠鍎搁崶銊у幐闁诲繒鍋涙晶钘壝洪幘顔界厱闁冲搫鍟禒杈殽閻愬弶顥℃い锕€宕…璺ㄦ喆閸曨剛顦ラ梺瀹狀潐閸ㄥ潡寮澶婄妞ゆ劏鍓濆鈧梻鍌欒兌椤牓鏁冮妷鈺傚亱婵犲﹤鐗嗛弸浣广亜閺囨浜惧Δ鐘靛仦鐢帟鐏冮梺閫炲苯澧扮紒顕嗙到铻栧ù锝囨嚀瀵灝鈹戦绛嬫當婵☆偅顨嗛弲鑸电節濮橆厾鍘介梺鐟版惈缁夊爼鎯屽▎鎾寸厸鐎光偓閳ь剟宕伴弽顓炶摕闁搞儺鍓氶弲婵嬫煃瑜滈崜鐔风暦濠靛柈鏃堝川椤撶媭鍟囨繝鐢靛剳缂嶅棝宕滃▎鎰箚濠靛倸鎲￠悡鐔兼煙闁箑澧鹃棅顒夊墴閺岋紕浠﹂悙顒傤槰缂備胶绮换鍡欑不濞戞﹩娼╁Σ灞剧墬鏁堝┑鐘垫暩閸嬫盯顢氶鐔稿弿濞村吋娼欓崹鍌炴煢濡警妯堟繛鍏肩墬缁绘稑顔忛鑽ゅ嚬濡炪們鍎遍悧濠勬崲濞戙垹绠ｉ柣鎰仛閸ｈ棄鈹戦埥鍡椾簽闁稿鍊曢～蹇涙惞鐟欏嫬鍘归梺鍛婁緱閸犳俺銇愯濮婃椽骞愭惔銏紭闂佹悶鍔岀紞濠囥€佸鑸垫櫜濠㈣埖蓱閺呮繈姊洪幐搴㈢５闁稿鎸鹃惀顏堝箚瑜嬮崑銏ゆ煛瀹€瀣М妤犵偛娲、姗€鎮㈤搹鍏夋瀼婵犵數鍋涢顓熸叏閹绢喖围闁归棿绀侀拑鐔兼煥濠靛棛澧㈤柣銈傚亾闂備礁鎼ú銊╁磻濡厧鍨濋柛顐ｆ礃閳锋垹鐥鐐村闁搞倕顑囩槐鎺旂磼濡偐鐤勫Δ鐘靛仜閸燁偊锝炲鍫濈劦妞ゆ巻鍋撻柣锝呭槻椤粓鍩€椤掑嫨鈧礁鈻庨幘鏉戜患闁诲繒鍋犲Λ鍕不濞差亝鈷掑ù锝勮閺€鏉款熆閻熸壆澧︽鐐存崌椤㈡棃宕卞鍡樼稐闂備礁鎼ú銏ゅ垂濞差亜纾婚柍鍝勫€舵禍婊堟煙閹冭埞闁诲浚浜弻锝夊箻鐎涙顦板Δ鐘靛仦閻楁洝褰佸銈嗗坊閸嬫挸鈹戦埄鍐┿仢闁哄瞼鍠栧濠氬Ψ瑜忛弳顐︽⒑閸濆嫮鐏遍柛鐘崇墵閵嗕礁鈻庨幘婢勨晠鏌曟径鍫濆姕闁诲繑鎹囧铏圭磼濡钄奸梺绋挎捣閺佽顕ｇ拠娴嬫婵犲﹤鎳愰弶鎼佹⒑閸濆嫭宸濋柛濠庡亰閺佹劙宕遍弴鐘电暰闂備胶绮崝鏍ㄧ珶閸℃稒鍎楁繛鍡樺灍閸嬫挸鈻撻崹顔界彯闂佺顑呴敃顏堟偘椤曗偓瀹曞爼顢楅埀顒傜棯瑜旈幃褰掑箒閹烘垵顬堥梺閫炲苯澧伴柛瀣ㄥ€曢～蹇撁洪鍕槰闂佸憡鐟ラˇ浼村磿閹剧粯鈷戦柛婵勫劚鏍＄紓浣割儐閹哥宓勯梺鍦濠㈡绮堥崘鈺冪闁哄鍩堥崕鎰版煛閸屾浜鹃梻鍌氬€烽懗鍓佸垝椤栫偛绀夋慨妞诲亾鐎规洘妞藉浠嬵敄閸欍儲鐫忛柣鐔哥矊缁绘帒危閹版澘绠虫俊銈呭暙瑜板嫬顪冮妶鍡樺暗濠殿喚鍏橀幃锟犲箻缂佹ǚ鎷洪柣鐘叉礌閳ь剝娅曞▓顓㈡⒑閹肩偛鍔€闁告劦鍘搁崑鎾诲垂椤旇鏂€闂佺粯鍔栧娆撴倶閿斿浜滄い鎾跺仦閸犳﹢鏌熼鍏煎仴鐎规洖鐖奸、妤佹媴閸欏顏归梻鍌欑窔濞艰崵鈧潧鐭傚畷銏＄附閹肩偐鍋撻崒鐐茬闁兼祴鏅濋惁鍫ユ⒑闂堟稓绠氭俊鎻掑閹虫挾鎹勯妸銏犱壕婵炲牆鐏濋弸娑㈡煙鐠囇呯瘈妤犵偛绻樺畷銊р偓娑櫭▓鎰攽閻樼粯娑ф繛璇х畵钘熼柛顐犲劜閻撴稑霉閿濆洦鍤€濠殿喖绉堕埀顒冾潐濞插繘宕濋幋锔衡偓浣割潨閳ь剟骞冮姀銈呯闁圭粯甯楅弳顓㈡⒒閸屾艾鈧悂宕愰悜鑺ュ殑闁割偅娲嶉埀顒婄畵瀹曞ジ濡烽敂鑺ョ彇闂備線娼ч悧鍡浰囨导鏉戠；濠㈣泛艌閺€浠嬫煕鐏炲墽鐭ら柣鎺楃畺閺岋箓宕橀鍕亪闂佸搫琚崝宀勫煘閹达箑骞㈤柍鍝勫€愰敂鍓х＝濞达絽鎼牎缂備礁顑嗙敮鈩冧繆閻㈢绀嬫い鏍ㄦ皑椤斿﹪姊洪悷鎵憼缂佹椽绠栧畷鎴﹀箻楠炲じ姹楅梺鍦劋閸ㄥ綊鎮块崨瀛樷拺闁稿繗鍋愰妶鎾煛閸涱喚绠樺瑙勬礋閹稿﹥绔熷┑鍡欑Ш闁轰焦鍔欏畷鍗炍旈崘顏傚仭婵犵數鍋涢悺銊у垝閹惧墎涓嶉柡宓本缍庡┑鐐叉▕娴滄繈鎮炴繝姘厽闁归偊鍨伴拕濂告倵濮橆厽绶叉い顓″劵椤﹀啿顭块悷鐗堫棤婵″弶鍔欓獮鎺楀箻鐎靛摜肖闂備線娼ч…顓犵不閹达附顥夌€广儱顦伴埛鎴︽煟閻斿憡绶叉俊鎻掝煼閺岀喖宕橀懠顒傤唺缂備緡鍠栭澶愮嵁閹烘妫橀柛婵嗗婢规洟姊洪幐搴ｇ畵缂併劏鍋愰懞杈ㄧ附閸涘﹦鍘甸梺鎯ф禋閸嬪棝骞婇崶銊﹀弿濠电姴瀚敮娑㈡煙瀹勭増鍣介柟鍙夋尦瀹曠喖顢曢垾铏啟闂傚倸鍊风粈渚€骞夐敓鐘茶摕闁靛ě鍛厠闂佸壊鍋呭ú鏍倿閸偁浜滈柟鐑樺灥閳ь剙顭烽獮濠偽旈崨顔惧幈闂佸搫娲㈤崝宀勭嵁閹扮増鐓涢柍?",
            "direct": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎妯恍氱紓鍌氬€烽懗鑸垫叏闁垮绠鹃柍褜鍓熼弻鈥崇暆閳ь剟宕伴弽褏鏆︽繝濠傛－濡查箖鏌ｉ姀鈺佺仭闁烩晩鍨跺璇测槈濮橈絽浜鹃柨婵嗗暙婵″ジ鏌嶈閸撴氨鎹㈤崼婵愬殨濠电姵鑹鹃崡鎶芥煟閺冨洦顏犳い鏃€娲熷铏圭磼濡搫袝闂佸憡鎸诲畝鎼佸箖閻㈢绫嶉柛顐ゅ暱閹锋椽姊虹涵鍛汗闁稿绋掓穱濠冪附閸涘﹦鍘辨繝鐢靛Т閸嬪棝鎮℃總鍛婄厱闁宠鍎虫禍鐐繆閻愵亜鈧牜鏁幒妤€绐楁慨姗嗗墻閻掍粙鏌熼柇锕€骞樼紒鐘荤畺閺屾稑鈻庤箛锝喰ㄦ繝鈷€灞奸偗闁诡噯绻濇俊鑸靛緞鐎ｎ剙寮抽梻浣告惈濞层劑宕戝☉娆戭洸闁规鍠氱壕鐣屸偓骞垮劚濡稒鏅堕悽鍛婄厸鐎光偓鐎ｎ剛鐦堥悗瑙勬礀閻栧ジ宕洪敓鐘茬劦妞ゆ帒鍊归～鏇犫偓瑙勬礀濞诧箓宕伴幇鐗堢厽婵°倐鍋撻柣妤€妫涚划顓㈠箳閺冨倻锛滈梺閫炲苯澧寸€规洘甯￠幃娆戔偓鐢殿焾楠炲牓姊绘繝搴′簻婵炶绠撻幊婵嬫倷椤掑偆娲搁梺闈╁瘜閸樺墽澹曟總鍛婂€甸柨婵嗙凹缁ㄨ偐鈧懓鎲＄换鍕閹烘挻缍囬柕濠忕畱闂夊秹姊洪悷鏉挎Щ闁硅櫕锚閻ｇ兘顢曢敃鈧粈瀣棯閻楀煫顏呯閸撗€鍋撻崗澶婁壕闂佸憡娲﹂崜娑㈠储闁秵鈷戠紓浣光棨椤忓棗顥氭い鎾跺枑濞呯娀鏌ｉ姀鐘冲暈闁绘挻娲熼弻宥夊传閸曨偅娈繛瀵稿Ь妞存悂銆冮妷鈺傚€风€瑰壊鍠栭崜鍫曟⒑鏉炴壆顦﹂柛濠傛健楠炴劖绻濋崘銊х獮婵犮垼娉涢鍥ь焽閺嶎厽鈷掗柛灞捐壘閳ь剟顥撶划鍫熸媴闂堚晞鈧潡寮堕崼姘珔闁搞劍绻冮妵鍕冀閵娿儱姣堥梺鍝ュ枎閹冲酣鍩為幋锔藉亹閻庡湱濮撮ˉ婵堢磼閻愵剙鍔ゆい顓犲厴瀵鎮㈤悡搴ｇ暰閻熸粍绮撳畷鐢告偄閾忓湱锛滈梺鎶芥暜閸嬫捇鏌涚€ｎ偅灏扮紒缁樼箓閳绘捇宕归鐣屼憾闂備焦瀵уú宥夊疾閻樿尙鏆︽繝濠傚暊濡插牊绻涢崱妯曟垿顢欓弮鍫熲拺闁硅偐鍋涢崝姗€鏌涢弬鎸庢崳缂侇喚绮妶锝夊礃閳轰讲鍋撻悽鍛婄厽闁靛繆妲呴崯蹇涙煟閹烘垵鈷旈柍褜鍓氱粙鎺旀崲閸岀偐鈧棃宕橀鍢壯囨煕閳╁喚娈樺ù鐘虫綑閳规垿鍩ラ崱妞剧凹缂備浇顕ч悧鎾绘偘椤曗偓瀹曟﹢顢欓懞銉︻仧闂備胶绮敋闁哥喐瀵х粋宥咁煥閸啿鎷洪梺鍛婄☉閿曪妇绱撳鑸电厱閹兼番鍨归埢鏇㈡煙椤栨瑧绐旂€规洖銈搁幃銏ゆ惞閸︻厽顫岄梻鍌欑劍閻綊宕归挊澶樼劷鐟滃秹鎮洪銏♀拻濞达絼璀﹂悞楣冩煥閺囨ê鍔︽鐐插暣瀹曟帡鎮欓浣镐壕濞撴埃鍋撶€殿噮鍣ｅ畷鐓庘攽閸繂绠伴梻鍌欒兌椤牓寮甸鍌涚畳缂傚倷闄嶉崝宀勨€﹂悜钘夎摕闁绘梻鍘х粈鍌炴煠濞村娅嗘繛鍫墴濮婃椽骞栭悙鎻掝瀳濡炪値鍘鹃崗姗€鐛崱妤冩殕闁告洦鍋嗛濠傗攽鎺抽崐鎾绘嚄閸洖鍌ㄩ柟闂寸劍閸婄敻鏌涜箛鎿冩Ц濞存粓绠栭弻锝嗘償椤栨粎校闂佸憡鎸荤粙鏍焻闂堟稈鏀介柨娑樺娴滃ジ鏌涙繝鍐ㄧ伌鐎规洜鎳撶叅妞ゅ繐鎳忓▍鍥⒑闂堟稓绠為柛濠冩礈缁寮介鐔哄帾闂婎偄娲﹀ú鏍ф毄闂備礁鎼Λ妤咁敄婢舵劕钃熼柍鈺佸暙缁剁偛鈹戦悩鎻掓殲闁绘繃鐗犲娲偡闁箑娈堕梺绋款儐椤洭骞戦姀銈呭耿婵炴垶鐟ч崢浠嬫⒑鐟欏嫭绶查柛姘ｅ亾缂備降鍔岄…鐑藉蓟瀹ュ牜妾ㄩ梺鍛婃尰瀹€鎼佸箖瑜斿鎾偐閹绘帞鏌ч梻鍌氬€搁…顒勫磻閸曨個娲晜閸撗呯厯闂佺懓顕慨鎾夊鑸电厱鐟滃酣銆冮崱娑樼厱闁圭儤顨嗛悡鏇熴亜閹扳晛鈧洟寮搁弮鍫熺厪闁糕剝锚濞搭噣鏌″畝瀣瘈鐎规洟浜堕、姗€鎮╅崹顐ｎ啌闂傚倷绀侀幖顐︽儗婢跺瞼绀婂ù锝呭閸ゆ洘銇勯弴妤€浜鹃悗瑙勬礃鐢帟鐏冩繛杈剧到閹芥粏銇愰悽鍛娾拻闁稿本鐟︾粊鐗堜繆濡炵厧濡跨紒顔肩墛缁楃喖鍩€椤掑嫨鈧線寮介妸銉х獮闂佸綊鍋婇崜婵嬪箺閺囩偐鏀介柣鎰綑閻忥箓鎳ｉ妶鍡曠箚闁圭粯甯炴晶锕傛煛鐏炲墽鈽夐摶鏍煕閹扳晛濡虹紒顔煎缁辨挻鎷呴崫鍕戯絾淇婇悙鑸殿棄妞ゎ偄绻愮叅妞ゅ繐瀚槐鍫曟⒑閸涘﹥澶勯柛鎾卞妿濡叉劙鎮欓悜妯锋嫼闂佸憡绋戦…顒勬倿娴犲鐓涢柛婊€绀佹禍鐗堫殽閻愭潙鐏村┑顔瑰亾闂佺粯锕╅崑鍛村棘閳ь剟姊虹拠鎻掑毐缂傚秴妫濆畷鎴﹀礋椤掑偆娴勫┑鐐叉▕娴滄繈鍩涢幒妤佺厱閻忕偟鍋撻惃鎴濐熆瑜庣粙鎾舵閹烘柡鍋撻敐搴′簻濠殿喖娲弻宥囨媼瀹曞洨鐓撳銈冨灪濡啫鐣锋總鍛婂亜闁告瑥顦褰掓⒒閸屾瑦绁扮€规洜鏁诲畷浼村箻鐎涙ɑ鐝峰┑掳鍊曢幊搴ㄦ偪椤曗偓閺岋綁骞囬鐓庡闂佺粯鎸婚悷锕傚Φ閸曨垰绫嶉柛灞捐壘娴犳﹢姊洪柅鐐茶嫰婢ь喗绻涚涵椋庣瘈妤犵偛鍟€靛ジ骞栭鐔告珦闂備椒绱徊浠嬫儔婵傚憡鍎婇柛顐犲劜閳锋垿鏌涘☉姗堟缂佸爼浜堕弻娑㈠Ω閿曗偓閳绘洜鈧鍠栨晶搴ｅ垝濞嗘劖鍎熼柟鎯х摠閺夋悂姊绘担铏瑰笡闁告梹鐗曢…鍥р枎閹炬潙鈧爼鏌ㄩ弴鐐测偓褰掓偂閻旈晲绻嗛柕鍫濆椤︼箓鏌ｈ箛鎿冨殶闁逞屽墲椤煤濮椻偓瀹曞綊宕稿Δ鍐ㄧウ濠碘槅鍨伴崥瀣偓姘哺閺屻倗鍠婇崡鐐测拻濠德ゅ皺婢ф绌辨繝鍥ㄥ€锋い蹇撳閸嬫捇寮介‖顒佺⊕閹峰懘鎳栧┑鍥╂创鐎规洜鍠栭、妤呭磼閵堝棝鏁滃┑鐘垫暩婵挳鏁冮妶澶嬪亱濠电姴娲ら悡鏇㈡煙鐎电啸缁炬儳銈搁幃妤呮晲鎼粹€崇缂佺虎鍘兼晶搴ｆ閹烘鍋愰柛妤冨仜缁侇噣姊洪崫鍕拱缂佸鍨块敐鐐测攽鐎ｅ灚鏅㈡繝銏ｆ硾閿曘倖绔熼崼銉︹拻濞达絽鎽滈弸鍐┿亜閺囧棗鎳愰惌鎾绘煟閻旂厧浜伴柛銈嗘礀闇夐柣妯烘▕閸庢盯鏌℃担鍛婂枠闁哄矉缍佸顒勫箰鎼淬垹鍓垫俊銈囧Х閸嬬偤銆冩繝鍌ゆ綎缂備焦顭囩弧鈧柟鑲╄ˉ閳ь剝灏欓惄搴㈢節閻㈤潧浠╂い鏇熺矌缁骞嬮悩鎻掔柧闂傚倷绀侀幖顐ょ矓閺屻儱绀夐幖娣妸閳ь剙鎳橀幃婊堟嚍閵壯冨笚闂備礁鎲＄换鍌溾偓姘煎弮瀹曞啿煤椤忓懐鍘介梺瑙勫劤閻°劎绮堢€ｎ喗鐓欐い鏃傜摂濞堟粓鏌℃担鐟板闁诡垱妫冮崹楣冩嚑椤掑倹鏅ㄥ┑鐘垫暩婵敻顢欓弽顓炵獥闁哄稁鍘旈崶銊︾秶闁冲搫鍋嗗鐔兼⒑閸︻厼鍔嬫い銊ョ箻瀵偅绻濋崶銊у幗闂佹寧绻傞幊蹇擄耿娴煎瓨鐓曢柨婵嗛楠炴绱掓潏銊﹀鞍闁瑰嘲鎳橀幖褰掓偡閹殿噮鍋х紓鍌氬€峰ù鍥敋瑜斿畷鎰板锤濡や焦娅滈梺缁樺姈缁佹挳寮ㄦ禒瀣€甸柨婵嗘噽娴犳盯鏌￠崨顐㈢伈婵﹨娅ｇ划娆戞崉閵娧傜礃闂備胶顭堥鍥窗鎼淬劍鍋╃€瑰嫰鍋婇悡銉╂煕椤愩倕鏆遍柟宄邦煼濮婅櫣绮欓幐搴㈡嫳闂佽崵鍟欓崶浣告喘閺佸啴宕掑☉姘箞闂備胶绮Λ鍐绩闁秴纾婚柕澶涘瘜濞堜粙鏌ｉ幇顒夊殶濠⒀冪仛閵囧嫰濮€閳╁啰顦伴梺杞扮劍閸旀瑥鐣烽鍛闁告稑顭崯宀勬⒒閸屾艾鈧绮堟担闈╄€块梺顒€绉寸壕鍧楁煏閸繍妲堕柍褜鍓欓崯鏉戠暦閵娾晩鏁嶆繝濞惧亾缂佹顦靛娲箰鎼达絿鐣靛┑鈽嗗亝缁嬫挸顕ｈ閸┾偓妞ゆ帒瀚埛鎴︽⒒閸喓銆掔紒鐘冲哺閺岋繝宕ㄩ鐐櫚濡ょ姷鍋涢崯顐︻敇婵傜鐐婇柍鍝勫枦缁辨娊鏌ｆ惔锛勭暛闁稿氦浜埀顒佸嚬閸ｏ綀妫熼梺鎸庢礀閸婂綊鎮￠悢鍏肩叆婵犻潧妫欓幖鎰版煕濡粯缍戦柍瑙勫灴閸╁嫰宕橀埡浣插亾閹扮増鐓涘ù锝囶焾閳ь剙鐏濋悾宄邦煥閸♀晜鞋婵犵鍓濊ぐ鍐洪鐑嗘綎缂備焦蓱婵潙銆掑鐓庣仯闁告梹鎮傞弻锝夋倷閺夋垵姣堥梺绋款儏閿曘倝鎮鹃悜钘夌疀闁哄鐏濆畵鍡涙⒑缂佹ê濮€闁哄懏绮撻幃妯荤瑹閳ь剙顫忛搹鍦煓閻犳亽鍔庨鎴︽⒑缁嬫鍎愰柛鏃€顨呴锝堫樄闁糕斁鍋撳銈嗗坊閸嬫捇鏌嶇憴鍕伌闁诡喗鐟╅幊鐘活敆閳ь剟銆傚ú顏呪拺閻犲洩灏欑粻鑼磼鐠囪尙澧曟い鏇秮楠炴牗鎷呴悷棰佺盎闂備胶顭堢换妤呭磻閹版澘鐭楅柛鈩冪⊕閳锋垿鏌涘┑鍡楊仾濠㈣泛瀚妵鍕Ω閵夛富妫為梺瀹狀嚙缁夌數鎹㈠┑瀣闁靛鍎版竟鏇㈡煟閻斿摜鎳冮悗姘煎幘缁牓宕橀鍡欙紲濡炪倖妫侀崑鎰版倿閹间焦鐓ユ繝闈涚墕娴犳粓鏌嶇憴鍕伌鐎规洖銈搁幃銏☆槹鎼搭垳纭€闂傚倸鍊烽悞锕傚磿瀹曞洦宕叉俊銈呮嫅缂嶆牕顭块懜闈涘闁稿﹤鐏濊灃闁挎繂鎳庨弳鐐烘煃闁垮绗掗棁澶愭煥濠靛棛澧涙い蹇曞█閹粙顢涘☉姘垱闂佸搫鏈惄顖氼嚕椤曗偓閸┾偓妞ゆ帒瀚ㄩ埀顒€鍟换婵嬪磼濠婂嫭顔曢梻浣告惈濞层垽宕归悷鐗堢函婵犵數濮伴崹鐓庘枖濞戙垺鏅濋柨鏇炲€归弲顒佺箾閹存瑥鐏柍閿嬪灴閺岀喓绮欓幐搴㈠闯缂備胶濮甸幐濠氬Φ閸曨垱鏅滈柛顭戝枛缁侇噣姊虹拠鈥虫珯缂佺粯绻傞锝夊箻椤旂⒈娼婇梺鎸庣☉鐎氼剛鏁幆褉鏀介柣姗嗗枛閻忚鲸绻涙径瀣创妞ゃ垺鐗犲畷銊р偓娑櫭埀顒€鐖奸弻鏇熷緞閸℃ɑ鐝曢梺缁樻尰閻╊垶寮诲☉銏╂晝妞ゆ劦婢€缁ㄧ粯绻濋埛鈧仦鑺ョ彎闂佸搫鐭夌换婵嗙暦鏉堫偆鐤€闁哄啠鍋撻柣婵囩墱缁辨挻鎷呮禒瀣懙闂佸湱鎳撳ú銈夋偩閻戣棄绠抽柟鎼幗閸嶉潧顪冮妶鍡楃伇婵☆偄瀚粋宥嗐偅閸愨晝鍘甸梻鍌氬€搁顓⑺囬敂鍓ф／闁诡垎鍛ㄩ梺鍝勬湰缁嬫垿鍩為幋锕€绀嬫い鎰╁灩琚橀梻鍌欑劍濡炲潡宕㈡禒瀣闁归棿鐒︾粻鎺楁⒒娴ｇ懓顕滅紒璇插€块獮濠冩償閵娿儲杈堥梺缁樺姉閸庛倝鎮″▎鎾寸厱闁归偊鍨伴惃娲煟韫囨矮鍚紒杈ㄥ笚濞煎繘濡搁敃鈧壕鎶芥倵鐟欏嫭绀冮悽顖涘浮閸┿垺鎯旈妸銉ь吅濡炪倖鎸鹃崯妯侯煥閸曨亞绠氶梺缁樺姦娴滄粓鍩€椤掍胶澧电€规洖缍婇幃鐣岀矙鐠恒劎鏋冩繝纰樻閸ㄨ京鈧瑳鍥佸濡舵径瀣ф嫽婵炶揪绲介幉锟犲箚閸喆浜滈柨鏂跨仢瀹撳棙銇勯姀锛勫ⅹ闁宠閰ｉ獮姗€寮堕幋鏂夸壕闁秆勵殕閻撶娀鏌熼鐔风瑨闁告梹锚闇夋繝濠傚閻帡鏌ｉ幙鍐ㄤ喊鐎规洖鐖兼俊鎼佹晝閳ь剟寮冲Δ浣虹瘈闁冲皝鍋撻柛鏇ㄥ墰椤︻厾绱撴担浠嬪摵閻㈩垽绻濋獮鍐煛閸滀焦鏅╅梺缁樻尭妤犳悂锝炲鑸碘拻濞撴埃鍋撴繛浣冲厾娲Χ閸ワ絽浜炬慨姗嗗幗缁跺弶銇勯弴顏嗙М妞ゃ垺顨婂畷鐔碱敃閵忊懇鍋撻鐑嗘富闁靛牆妫欓ˉ鍡樸亜椤愩埄妲洪柍褜鍓欓悘姘舵偋閻樺樊娼栫紓浣股戞刊鎾煕濞戞﹫宸ラ柡鍡楃墕閳规垿鍩ラ崱妞剧暗缂備讲鍋撳〒姘ｅ亾闁糕斂鍨藉顒佹償閹炬惌娼旈梻渚€娼х换鎺撴叏閻戣棄鍌ㄩ柟缁㈠枟閳锋垹鐥鐐村櫤鐟滄妸鍥ㄢ拻闁告洦鍋勯顓犫偓瑙勬礃閸旀瑩骞冨鍫熷殟闁靛／鍐ㄧ婵犵數濮伴崹鐓庘枖濞戙埄鏁勯柛娑樼摠閸婂爼鏌嶆潪鐗堚偓銉ㄣ亹閹烘挸浜归梺鎯ф禋閸嬪嫰鍩€椤掍礁濮堥柟渚垮妽缁绘繈宕橀埞澶歌檸闁诲氦顫夊ú锕傚磻婵犲倻鏆﹂柣鏃傗拡閺佸鏌涘☉鍗炴灕闁哄憞鍥ㄢ拻闁稿本鐟чˇ锕傛煙濞村鍋撻幇浣圭稁閻熸粎澧楃敮鎺楀垂閸岀偞鐓曠憸搴ㄣ€冮崼婵堟殼濞撴埃鍋撻柡灞剧洴楠炲洭妫冨☉妯侯劀婵犵妲呴崹鎵偓姘煎墲閻忓啴姊虹紒姗堣€挎繛浣冲嫮顩锋繝濠傚缁犲墽鈧懓澹婇崰鏍ь嚕椤曗偓閺屾洟宕遍弴鐙€妲梺瀹狀嚙闁帮綁鐛鈧鍫曞箣閻樻剚鈧秵绻濋悽闈浶為柛銊у帶閳绘柨鈽夐姀鈩冩珖闂佹寧娲栭崐鍛婂閻樿绠规繛锝庡墮婵′粙鏌嶉柨瀣诞闁哄本绋撴禒锕傚礈瑜庨崳顔碱渻閵堝繗顓虹紒鐘虫崌瀵鎮㈤崫鍕€抽梺鍛婎殘閸嬫鑺遍悾宀€纾藉〒姘搐閺嬬喖鏌ｉ悤鍌氼洭缂侇噮鍙冮幃銏ゆ偂鎼达絽濮︽俊鐐€栧濠氬磻閹剧粯鐓熼柨婵嗘搐閸樻潙鈹戦鐟颁壕闂備焦瀵х粙鎴犫偓姘緲椤﹪顢欓崜褏锛濇繛杈剧到婢瑰﹪宕曢幘瀵哥濠㈣泛顑嗙粈瀣寠濠靛鐓忓┑鐐靛亾濞呭棝鏌嶉柨瀣伌婵﹥妞介、鏇㈠Χ閸涱剛鎹曢梻浣稿悑濡炲潡宕归柆宥呯柧闁割偅娲栫粻缁樸亜閺冨倹娅曢柛姗€娼ч—鍐Χ閸℃ǚ鎷婚梺鐑╁墲閺屻劑鍩㈤幘鎰佺叆闁割偆鍠撻崢闈涱渻閵堝棙鈷愰柛搴㈠▕瀹曘垻鈧數纭堕崑鎾斥枔閸喗鐏曞┑鐐差槹閻╊垶宕洪姀鈩冨劅闁靛鍎抽悡鎴︽⒑闂堟冻绱￠柛婊冨暟閸掓稒绻濋悽闈浶ユい锝庡枤濡叉劙寮撮姀鐘碉紱闂佺鎻粻鎴犲閸︻厽鍠愰煫鍥ㄦ礃椤洟鏌ｉ幇顒佹儓闁绘劕锕弻鏇熺箾閸喒鍋撳Δ鍐笉婵鍩栭埛鎴︽煙閼测晛浠滈柛鏃€鎸抽弻娑㈠箻鐎靛憡鍣紓渚囧枛閻楁挸鐣烽崡鐐╂婵炲棙鍨甸獮宥夋⒒娴ｈ櫣甯涢柛銊ョ埣閺佸啴鍩℃担鍙夌亖闂佸搫娲㈤崹娲偂閺囥垺鍊甸柨婵嗗暙婵＄厧鈹戦鐓庘偓鍧楀蓟閿涘嫪娌柛鎾椻偓濡插牓姊虹€圭姵顥夋い锔诲灦閿濈偛顭ㄩ崼婵嬪敹濠电娀娼уΛ顓烆焽椤掑嫭鈷?",
        }.get(mode, "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎妯恍氱紓鍌氬€烽懗鑸垫叏闁垮绠鹃柍褜鍓熼弻鈥崇暆閳ь剟宕伴弽褏鏆︽繝濠傛－濡查箖鏌ｉ姀鈺佺仭闁烩晩鍨跺璇测槈濮橈絽浜鹃柨婵嗗暙婵″ジ鏌嶈閸撴氨鎹㈤崼婵愬殨濠电姵鑹鹃崡鎶芥煟閺冨洦顏犳い鏃€娲熷铏圭磼濡搫袝闂佸憡鎸诲畝鎼佸箖閻㈢绫嶉柛顐ゅ暱閹锋椽姊虹涵鍛汗闁稿绋掓穱濠冪附閸涘﹦鍘辨繝鐢靛Т閸嬪棝鎮℃總鍛婄厱闁宠鍎虫禍鐐繆閻愵亜鈧牜鏁幒妤€绐楁慨姗嗗墻閻掍粙鏌熼柇锕€骞樼紒鐘荤畺閺屾稑鈻庤箛锝喰ㄦ繝鈷€灞奸偗闁诡噯绻濇俊鑸靛緞鐎ｎ剙寮抽梻浣告惈濞层劑宕戝☉娆戭洸闁规鍠氱壕鐣屸偓骞垮劚濡稒鏅堕悽鍛婄厸鐎光偓鐎ｎ剛鐦堥悗瑙勬礀閻栧ジ宕洪敓鐘茬劦妞ゆ帒鍊归～鏇犫偓瑙勬礀濞诧箓宕伴幇鐗堢厽婵°倐鍋撻柣妤€妫涚划顓㈠箳閺冨倻锛滈梺閫炲苯澧寸€规洘甯￠幃娆戔偓鐢殿焾楠炲牓姊绘繝搴′簻婵炶绠撻幊婵嬫倷椤掑偆娲搁梺闈╁瘜閸樺墽澹曟總鍛婂€甸柨婵嗙凹缁ㄨ偐鈧懓鎲＄换鍕閹烘挻缍囬柕濠忕畱闂夊秹姊洪悷鏉挎Щ闁硅櫕锕㈤悰顕€骞樼拠鑼唺閻庡箍鍎遍幏瀣涘鍫熲拻闁稿本鑹鹃埀顒傚厴閹虫宕奸弴妞诲亾閿曞倸閱囬柕澶涚畱閸撹埖绻濋棃娑樷偓濠氣€﹂崼銏狀棜濠电姵纰嶉悡鐔兼煙闁箑鏋涢柛鏂款儔閺屾稓鈧綆浜滈埀顒€娼″濠氭晸閻樿尙鍊為梺瀹犳〃閻掞箓鎮楅鐔虹閻庢稒顭囬惌瀣磼椤旇姤宕岀€殿喖顭烽幃銏ゆ偂鎼达綁鐛撻梻浣稿閻撳牓宕抽鈧鎶藉閵堝棌鎷洪柣鐘叉礌閳ь剝娅曢悘鏇㈡⒑缁嬫鍎愰柛鏃€顨呭嵄闁圭増婢樼粻铏繆閵堝嫮顦﹀ù婊冪秺濮婃椽骞嗚缁傚鏌涚€ｎ亜顏€殿喖鍟胯灃闁告劦浜為敍婵囩箾鏉堝墽瀵肩紒顔界懇瀹曨偄煤椤忓懎浠哄銈嗙墬椤ㄥ懏鏅堕幓鎹涘酣宕惰闊剚顨ラ悙瀵稿闁瑰嘲鎳庨湁閻庯綆浜欐竟鏇㈡⒑閹稿孩绀€闁稿﹤鎽滅划濠氭晲閸℃瑧鐦堥梻鍌氱墛缁嬫帞绮婇埡鍛厱闁绘劕顕崣鈧┑顔硷工椤嘲鐣烽幒鎴僵妞ゆ垼妫勬禍鍓х磼鐎ｎ偓绱╂繛宸簻鍥存繝銏㈡缁犳垵煤椤撱垹绠栭柣锝呯灱閻瑩鏌ら幇浣哥仭闁硅弓鍗冲缁樼瑹閳ь剙顭囪閳ワ箓宕奸妷銉э紵濡炪倖娲嶉崑鎾垛偓娈垮枔閸斿秶绮嬮幒鏂哄亾閿濆骸浜為柛姗€浜跺娲棘閵夛附鐝旈梺鍛婄懄閸旀瑩鐛€ｎ喗鏅濋柍褜鍓涚划濠氬冀閵娧咁啎闂佺硶鍓濊摫閻忓繋鍗抽弻锝夊箻鐎涙顦伴梺鍝勭焿缂嶄礁顕ｉ鍕閹肩补鍓濆▓姗€姊绘担渚劸闁挎洏鍎靛畷婵嗏枎閹惧疇鎽曢梺鎸庣☉鐎氼亜鈻介鍫熷仯闁搞儯鍔庨妶鎾煕鐎ｎ偅灏柍瑙勫灩閳ь剨缍嗛崜娆戠矈閿曞倹鈷戠憸鐗堝笒娴滀即鏌涘Ο鍦煓鐎规洘娲熼幃銏ゅ礂閼测晛寮虫繝鐢靛█濞佳兾涘▎鎾嶅顭ㄩ崟顓狀啎闂佸憡渚楅崰鏍倶鐎涙ɑ鍙忓┑鐘插亞閻撹偐鈧娲樼敮鎺楋綖濠靛鏁囬柣鏃傤焾閳ь剟鏀辨穱濠囨倷椤忓嫧鍋撹娣囧﹪宕堕鈧弸渚€鎮归崶褎鈻曢柛銈嗘礀閳规垿鎮╃€圭姴顥濋柟顖滃枛濮婃椽妫冨☉杈ㄐら梺鎼炲妽濡炶棄顕ｉ鍕劦妞ゆ帒瀚埛鎺懨归敐鍫燁仩闁靛棗锕弻娑㈠箻鐎靛摜鐤勯梺杞扮椤戝懘鍩為幋锔藉€烽柛娆忣槸閺嗕線姊洪崨濠佺繁闁搞劍濞婇弫宥呪攽閸モ晝顔曢柡澶婄墕婢т粙宕氭导瀛樼厵缁炬澘宕禍浼存煟鎼淬劍鏁辩紒缁樼箞閹粙妫冨☉妤冩崟闂備胶鎳撻崯璺ㄦ崲閹邦喖寮叉繝鐢靛Т閿曘倝鎮ч崱娆戜笉闁哄被鍎查悡蹇涚叓閸ャ劍绀€鐞氥儱鈹戦埄鍐ㄧ祷闁绘鎹囧濠氬即閿涘嫮鏉搁柣搴秵娴滅偞绂掓總鍛婂仭婵犲﹤瀚欢鏌ユ倵濮樼厧澧撮柍銉︽瀹曟﹢顢欓崲澹洦鐓曢柍鈺佸幘椤忓牆姹叉俊銈呮噺閳锋垹绱掔€ｎ偒鍎ラ柛搴㈠姉缁辨帞鈧綆鍋呯亸鐢告煕閹烘挸绗氱紒缁樼箞瀹曞爼鎳滈崹顐ｇ彣闂傚倷绶氶埀顒傚仜閼活垱鏅剁€涙﹩娈介柣鎰絻閺嗘瑩鎽堕弽顓熺厓鐟滄粓宕滈悢鐓庢槬闁靛繈鍊曠粻濠氭偣閸ャ劌绲婚柣搴幖椤啴濡堕崱妯锋嫽闂佸搫鎷嬮崑鍛矉瀹ュ鍊烽柣銏㈡暩閿涙繈姊虹粙鎸庢拱闁荤啙鍛濞寸厧鐡ㄩ悡鏇㈡煟濡澧繛鍫熺矒閺岀喖顢欓幆褍骞嬫繝纰夌磿閸忔﹢宕洪敓鐘茬＜婵﹩鍋呴崑鍛存⒒閸屾瑨鍏岀紒顕呭灦瀹曞綊鎮￠獮顒佺洴瀹曠喖顢橀悩杈╃憹婵犳鍠楅…鍫ュ春閺嶎厼鐓曢柟瀵稿亼娴滄粓鏌熼幆褍鑸瑰┑顔煎€规穱濠勭磼閵忕姵鐏堝銈庡亖閸ㄨ棄鐣烽崼鏇ㄦ晢濞达絽寮剁€氳棄鈹戦悙鑸靛涧缂佹彃娼￠幃娲籍閸繂鎯炲┑鐐叉閹稿宕愰崹顐ょ闁瑰鍋涚粭姘箾閸涱厽顥犵紒杈ㄥ笒閻ｆ繈宕熼鍛灓闂備礁婀遍崢褏绱炴繝鍥ц摕闁告侗鍘稿Σ鍫熸叏濮楀棗澧柍閿嬫礀閳规垿鎮╅崹顐ｆ瘎闂佺顑嗙粙鎴ｇ亱濠电偛妫欓幐鎼佸垂閸岀偞鐓曟い鎰剁稻缁岃法绱撳鍡欏⒌闁哄矉绻濆畷鍫曞Ψ閵壯傜棯闂備胶绮幐濠氭偡閳哄懎钃熼柣鏃傚劋閸犲棝鏌涢弴銊ヤ簻鐞氭繈姊绘担瑙勫仩闁稿﹥鐗犻幃鐤樄闁诡垪鍋撳銈呯箰閻楀棛绮诲杈ㄥ枑鐎广儱顦粻鏍煙鏉堥箖妾柣鎾寸懃閵嗘帒顫濋鍌欒檸婵犵鈧啿鎮戦柕鍥у椤㈡洟鏁愰崶鈺冨帨闁诲氦顫夊ú鏍х暦椤掑啰浜欓梻渚€鈧偛鑻晶鎵磼椤旀鍤欓悡銈嗐亜韫囨挻鍣抽柟鐤缁辨挻鎷呴崜鎻掑壈闂佽绻戠换鍫ャ€佸Δ鍛潊闁靛牆妫涢崢鐢告⒑閼姐倕鏋斿褎顨婂畷鏉课熷ú缁橆啍闂佺粯鍔栬ぐ鍐汲濞嗘挻鐓熼柨婵嗙箳缁♀偓闂佸搫鑻ú顓㈠极閸岀偛绠氱憸宥呅ч弻銉︹拻闁稿本鐟чˇ锕傛煙濞村澧茬紒妤冨枎铻栭柛娑卞幘閻撴垿鏌熼崗鑲╂殬闁告柨鑻晥闁告瑥顦禍婊堟煙閹冭埞闁诲浚浜弻宥夋煥鐎ｎ亞浼岄梺鍝勭焿缂嶄線鐛€ｎ喖绫嶉柍褜鍓欓埢宥夊幢濡偐顔曢梺鍛婁緱閸犳鐣峰畝鍕厸閻忕偛澧藉ú鏉戔攽閳╁啯鍊愬┑鈩冩倐閺佸倹绌遍幍浣镐壕闁归偊鍓﹀〒濠氭煏閸繃顥炵紒宀冩硶缁辨挸顓奸崟顓犵崲闂侀潧妫旂欢姘嚕閹绢喖顫呴柣娆屽亾婵炵厧锕铏光偓鍦У閵嗗啴鏌ｉ幒鐐电暤鐎规洘鍔欓、娑㈡倷缁瀚藉┑鐐舵彧缂嶁偓妞ゎ偄顦靛畷鎴︽偐缂佹鍘遍柟鑲╄ˉ濡插懘鎮￠崗鍏煎弿濠电姳鑳堕惌娆戔偓瑙勬礈閸犳牠銆佸☉姗嗘僵濡插本鐗楁晥闂傚倸鍊风粈渚€骞夐敓鐘茬闁挎洖鍊哥粣妤佷繆閵堝懏鍣归柣鎾存礋閺岀喐娼忔ィ鍐╊€嶉梺缁樻尵婵炩偓闁哄瞼鍠栭、姗€鎮㈡搴ｆ噯闂備礁鎲￠幖鈺呭储娴犲桅闁告洦鍠氶悿鈧梺瑙勫礃濞夋盯骞冪€ｎ喗鈷戦柟鑲╁仜閸旀挳鏌涢幘瀵告噮闁汇儺浜ｉˇ瑙勵殽閻愬澧遍柍褜鍓氱粙鎺曟懌闁诲繐绻嬮崡鎶藉蓟閿濆棙鍎熼柕寰涢铏庢繝娈垮枛閿曘儱顪冮挊澶屾殾闁靛濡囩弧鈧梺绋挎湰椤曟挳寮撮姀鈾€鎷洪梺鍛婄缚閸庤鲸鐗庢俊鐐€戦崝宀勬晝椤忓嫮鏆﹂柛婵嗗濡插牓鏌曡箛鏇炐ユい鎾存そ濮婅櫣绱掑Ο蹇ｄ邯閹ê顫濋懜鍨珫闂婎偄娲﹂幖鈺併€掓繝姘厪闁割偅绻冮ˉ鐐烘倶韫囨洘鏆柡灞剧〒閳ь剨缍嗛崜娆愮鏉堚斁鍋撶憴鍕濠电偛锕獮鏍亹閹烘垶宓嶅銈嗘尵閸ｏ妇妲愰埄鍐х箚闁绘劦浜滈埀顒佺墵楠炴劙宕奸弴鐐茬€繝鐢靛У绾板秹宕戦埡鍌滅鐎瑰壊鍠曠花濂告煟閹惧娲撮柟顔斤耿閹瑦锛愬┑鍡橆唲濠电姵顔栭崰鏍磹婵犳艾鐒垫い鎺嶇贰閸熷繘鏌涢悩鎰佹當妞ゎ厼娲ら埢搴ㄥ箳閺傛崘鍩呴梻鍌欐祰瀹曠敻宕戦悙鐢电煓闁割偁鍎遍悞鍨亜閹哄棗浜鹃梺鍛娚戦悧妤冪博閻旂厧鍗抽柕蹇婃閹锋椽姊洪崨濠勭畵閻庢凹鍣ｉ崺銏″緞閹邦厾鍘卞┑鈽嗗灠閻忔繃绂嶉崷顓犵＜妞ゆ梻鈷堥悡濂告煙椤旂晫鎳囬柟顔界矊铻ｉ柣鎾抽婵″洦绻濋悽闈浶ラ柡浣规倐瀹曟垿鎮㈤悡搴ｏ紱闂佸湱鍋撻弸濂稿几瀹ュ鐓曟繛鎴烆焽閹界娀鏌ｉ幘璺烘灈闁哄瞼鍠栭獮鍡氼檨闁搞倗鍠愮换娑㈠矗婢跺鍞夐梺鍝勭焿缁辨洘绂掗敃鍌氱鐟滃鍩€椤掍礁绗掗棁澶愭煟濞嗗繑鍣介柣锝囨暩閳ь剝顫夊ú妯煎垝韫囨蛋鍥敊閹存帞绠氶梺鍦帛鐢偞鏅堕弴鐔翠簻妞ゅ繐瀚弳锝呪攽閳ュ磭鍩ｇ€规洏鍔戦、妯款槻濠碉紕鍏樺缁樻媴閻戞ê娈岄梺纭咁嚋缁绘繈鐛崘顔肩＜闁绘劕寮跺Σ顒勬⒑缂佹ê濮囬柟纰卞亞缁鏁愭径瀣弳闂佸搫鍟ú锕偹夋径濞掔懓顭ㄩ崘顏喰ㄩ梺鍝勭焿缂嶄線骞冮埡鍛煑濠㈣泛锕ら懠鍐⒒娴ｅ憡鍟為柛鎿冨墴瀹曘劑顢涘鍐ㄧ畱闂傚倸鍊搁崐鎼佸磹閹间礁纾归柣鎴ｅГ閸ゅ嫰鏌涢锝嗙８闁逞屽厸閻掞妇鎹㈠┑瀣＜婵°倓鑳堕埀顒佹そ濮婃椽宕崟顒€鍋嶉梺鎼炲妼濠€杈╁垝閸喎绶為悗锝傛櫇缁犳岸姊洪棃娑氬闁稿﹤鎲＄粋宥嗐偅閸愨晝鍘卞┑掳鍊曢幊宥夊箟妤ｅ啯鐓涚€光偓閳ь剟宕伴弽顓炶摕闁搞儺鍓氶弲婵嬫煃瑜滈崜姘跺疾閸撲胶纾兼俊顖濆亹椤旀洟鏌ｈ箛鎾剁闁绘顨呴埢宥嗙節閸ャ劎鍘搁柣蹇曞仩椤曆囧焵椤掍胶绠撻柣锝囧厴椤㈡洟鏁冮埀顒€鏁梻浣瑰濡焦鎱ㄩ妶澶嬪剨閹兼番鍔嶉埛鎺懨归敐鍛暈闁哥喓鍋ら弻銊╁即濡櫣浠剧紓浣稿€哥粔鍫曞箲閸曨剛鐟规い鏍ㄧ〒缁嬩焦绻濋悽闈涗粶婵☆垰锕ョ粋宥咁煥閸繄顔夐梺鐓庢憸閸嬶絾绂嶅鍫熺厵闁硅鍔栫涵鎯归悩宕囩煀闁宠鍨块崺鍕礃閳瑰じ铏庢繝娈垮枛閿曘儱顪冮挊澶屾殾妞ゆ劧绠戠粈瀣亜閺囩偞鍣洪柦鎴濐樀濮婄粯鎷呴崨濠傛殘濠殿喖锕ょ紞濠傜暦瑜版帒绠伴幖瀛樼箘缁犳岸姊洪崷顓℃闁哥姵鐗滄竟鏇熺附閸涘﹦鍘介梺褰掑亰閸ㄤ即鎯冮悜妯镐簻閿滃宕堕妸銏″闂備胶顭堢换妤呭磻閹版澘围闁圭虎鍠楅悡娑㈡煕濞戝崬鏋ょ紒鐘靛仦閵囧嫰濮€閿涘嫭鍣伴悗娈垮枟閹歌櫕鎱ㄩ埀顒勬煃闁款垰浜鹃梺褰掓敱濡炰粙寮婚敐澶嬪亜闁告縿鍎查崳褔鏌ｆ惔銏犲毈闁告挾鍠庨悾宄扳攽鐎ｎ€冾熆鐠轰警鍎戦柛姗€浜跺铏圭磼濡椿妫冮梺琛″亾闂侇剙绉寸壕濠氭煏婢跺棙娅嗛柣鎾崇箻閺屾盯鍩勯崘鐐暥闂侀€炲苯澧柣蹇旂箞閹儳鐣￠幏鏃傚枛瀹曟鎮℃惔銏＄彺婵犵數鍋犻幓顏嗗緤閸ф纾块柕鍫濐槸閸氬綊鏌嶈閸撴瑩鈥旈崘顔嘉ч幖绮光偓宕囶唹闂備礁鎲″褰掑垂閻㈠憡鍋╅柣鎴ｅГ閸嬪嫮鐥幏宀勫摵闁哄拑缍佸铏圭磼濡儵鎷诲銈庡幖閻楁挸顕ｉ弻銉ヤ紶闁靛／鍜冪闯闂備胶顭堥張顒勬嚌妤ｅ啫鐒垫い鎺戝€搁崢鎾煙閾忣偒娈滈柟铏矒瀹曞綊顢曢姀鐘辩礋闂傚倷鐒﹂惇褰掑垂婵犳艾鏋侀柟闂寸劍閸庢绻涢崱妯诲鞍闁绘挻鐟╅弻鐔烘喆閸曨偄袝闂佹悶鍊栭悷鈺呭蓟閿濆绠抽柟瀵稿С缁敻姊洪棃娑欐悙閻庢矮鍗抽悰顕€骞掑Δ鈧粻锝嗐亜閺嶃劎鈯曢柡鍡曞嵆濮婄粯绗熼埀顒勫焵椤掑倸浠滈柤娲诲灦瀹曘垽鎮介崨濠勫幈闁瑰吋鐣崝宥呪槈瑜旈弻锝夋晲閸涱厽些闁句紮绲剧换娑㈠幢濞嗗繋澹曞ù婊勭☉閳?")
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
        anchor = "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎妯恍氱紓鍌氬€烽懗鑸垫叏闁垮绠鹃柍褜鍓熼弻鈥崇暆閳ь剟宕伴弽褏鏆︽繝濠傛－濡查箖鏌ｉ姀鈺佺仭闁烩晩鍨跺璇测槈濮橈絽浜鹃柨婵嗗暙婵″ジ鏌嶈閸撴氨鎹㈤崼婵愬殨濠电姵鑹鹃崡鎶芥煟閺冨洦顏犳い鏃€娲熷铏圭磼濡搫袝闂佸憡鎸诲畝鎼佸箖閻㈢绫嶉柛顐ゅ暱閹锋椽姊虹涵鍛汗闁稿绋掓穱濠冪附閸涘﹦鍘辨繝鐢靛Т閸婂綊宕戦妷褉鍋撳▓鍨灕妞ゆ泦鍥х叀濠㈣埖鍔曢～鍛存煟濡吋鏆╅柡澶婃啞娣囧﹪鎮欓鍕ㄥ亾閺嶎偅鏆滃┑鐘插婵ジ鏌＄仦璇插姎闁告垹濮电换娑㈠幢濡闉嶉梺鎶芥敱閸ㄥ湱妲愰幘瀛樺闁兼祴鍓濋崹瑙勭閹间緡鏁傞柛顐ゅ枔閸橀亶鏌熼懝鐗堝涧缂佹煡绠栧鎶筋敆閸屾浜炬繛鍫濈仢閺嬫稒銇勯鐘插幋妤犵偛鍟存慨鈧柕鍫濇噹缁愭稒绻濋悽闈浶㈤悗姘煎枦閸婃挳姊婚崒姘偓椋庣矆娓氣偓楠炲鏁撻悩鑼唶闂佺硶鍓濈粙鎴濐啅濠靛洢浜滈柡鍐ㄥ€婚幗鍌炴煕閻旈攱鍣界紒杈ㄦ崌瀹曟帒顫濋钘変壕闁归棿绀佺壕鐟邦渻鐎ｎ亜顒㈠┑顖氥偢閺岋紕浠︾拠鎻掑缂佺偓鍎抽…鐑藉蓟閻旂厧绀堢憸蹇曟暜濞戙垺鐓熼柟鎯х摠缁€鍫ユ煃瑜滈崜娆撳储濠婂牆纾婚柟鍓х帛閻撳啰鎲稿鍫濈闁绘棃顥撻弳锕傛煙鏉堥箖妾柛濠勫厴閺岋綁骞嬮悘娲讳簼缁傚秴螖閸涱喒鎷洪梺鍛婄箓鐎氼厼顔忓┑瀣厱闁绘ê寮堕ˉ鐐电磼閸屾氨孝妞ゎ厹鍔戝畷濂告偄閸濆嫬绠ラ梻鍌欑窔閳ь剚绋撶粊閿嬬箾閸涱喗绀€闁宠绉瑰畷銊р偓娑欘焽閸樻捇鎮峰鍕煉鐎规洘绮岄～婵嬵敄閻愬瓨銇濋柟顔哄灪缁鸿姤寰勬繝鍐惧悪闂傚倷绀侀幉锛勭矙閹达附鏅濋柕澶嗘櫅绾惧潡鏌ｉ弬鍨倯闁绘挸绻愰埞鎴︽倷閼碱兛铏庨梺鍛婃煟閸婃繈寮婚敐澶嬫櫜濠㈣泛鐬奸弳顐⑩攽椤旂》榫氭繛鍜冪悼濡叉劙骞掗幊宕囧枛閹筹繝濡堕崨顓熻緢闂傚倸鍊风粈渚€骞夐敓鐘冲殞濡わ絽鍠氶弫鍕熆閼搁潧濮囩紒鐘崇墵閺屽秹濡烽敂鐣屼紘濠碘剝褰冮悧濠囧箞閵娿儙鏃堝焵椤掆偓铻炴繛鎴欏灩閼稿綊鏌ｉ姀鐘冲暈闁绘挾鍠栭弻锝呂熼悡搴″濡炪倕绻掓繛鈧柡灞剧⊕閹柨鈽夊Ο宄颁壕婵犻潧锕ラ敍鍌炴⒒娴ｈ櫣甯涢柛鏃€娲熼、姘额敇閻樺吀绗夋俊銈忕到閸燁垶鎮￠弴鐔虹闁瑰瓨绻傞懜瑙勵殽閻愭惌娈曢柕鍥у婵＄兘鏁愰崨顖欑礄闂備礁鎼径鍥焵椤掆偓绾绢參寮抽崱娑欏€甸柨婵嗛婢ф壆鎮敃鍌涒拻濞达絿鐡旈崵鍐煕閻樿櫕宕岀€规洖缍婇幐濠冨緞濡儤顓块梻浣稿閸嬪懎煤閺嶎偆涓嶉柨婵嗩槹閻撴盯鏌涚仦鎯ф惛濞寸姵甯掗…璺ㄦ喆閸曨剛顦ラ梺瀹狀潐閸ㄥ爼鐛繝鍥ㄧ厱濠电姴鍟粈瀣偓瑙勬处閸ㄥ爼銆侀弴銏℃櫇闁逞屽墴瀹曞綊宕掑☉姘辩槇闂傚倸鐗婃笟妤呭磿閹扮増鐓熼柟鎯у暱閺嗭綁鏌＄仦鍓р槈闁宠鍨垮畷鍗炍旀繝浣烘／闂傚倷绶氬鑽ゅ緤閽樺鑰块弶鍫氭櫆椤洟鏌熼悜姗嗘畷闁稿鍨剁换娑㈠幢濡ゅ啰顔夋繝銏ｆ硾鐎氫即寮婚敐澶婄閻庨潧鎲￠崳浼存⒑閸濆嫮鐏遍柛鐘虫崌瀹曠増绻濋崶褏顢呴梺缁樺姌鐏忔瑩顢欓幇顓濈箚闁靛牆娲ゅ暩闂佺顑囬崑銈夊Υ閸愵喖骞㈡俊顖氱毞閺€铏節閻㈤潧孝闁稿妫楅妴鎺撶節濮橆厾鍘介梺鍦亾婵炲﹪顢撳Δ浣典簻妞ゆ劑鍨洪幖鎰版煃鐟欏嫬鐏存い銏＄懅濞戠敻鏌ㄧ€ｎ偅姣庡┑鐘殿暜缁辨洟宕戦悩鍙傛盯宕熼鍙ョ綍闂傚倷绀侀幉锟犲礉閹达箑绀夊璺好￠敐澶婇唶闁冲灈鏅涙禍楣冩偡濞嗗繐顏紒鈧埀顒€鈹戦悙鑼勾闁告梹鍨挎俊瀛樼瑹閳ь剙鐣烽妸褉鍋撳☉娅辨岸骞忕紒妯肩閺夊牆澧介崚浼存煙鐠囇呯瘈鐎规洦鍨堕幃娆戔偓闈涙憸椤旀洟鏌ｉ悩鍙夊巶闁告侗鍨卞▓濂告煟鎼淬値娼愭繛鎻掔箻瀹曡绂掔€ｎ亞顔囨繝鐢靛Т閸燁偆娆㈤悙鐑樼厱闁斥晛鍠氶悞钘壝瑰鍕⒌婵﹦绮幏鍛村传閵夘灝銊モ攽閳藉棗浜滄繛纭风節楠炲啴鎮欓悜妯绘珖闂佺鏈銊╁储闁秵鈷戦柛锔诲幖閸斿鏌涢妶鍡曚孩闁靛洦鍔欓獮鎺楀箻鐎涙褰搁梻鍌欑閹测剝绗熷Δ鍛獥婵°倕鎳庣壕鍧楁煙閸撗呭笡闁抽攱鍨块弻娑樷槈濮楀牊鏁惧銈冨劜閻楁粎妲愰幒妤佸亹闁惧浚鍋勭壕鎶芥倵濞堝灝鏋涙い顓犲厴瀵偊骞樼紒妯轰汗闂佸湱绮敮鐐烘偘閳哄倷绻嗛柣鎰典簻閳ь剚娲滈幑銏ゅ箛閺夎法鐤囬棅顐㈡处缁嬫帡宕戦悢鍛婂弿婵☆垰鐏濋悡鎰版煕婵犲嫭鏆柟顔煎槻閳诲氦绠涢幙鍐х棯缂傚倷璁查崑鎾绘煕閹般劍娅囩紒鈾€鍋撻梻渚€娼х换鍡椢ｉ崨瀛樺€垮Δ锝呭暞閻撶喖鐓崶銊﹀碍闁哄棴绲鹃幈銊︾節閸愨斂浠㈤悗瑙勬磸閸斿秶鎹㈠┑鍥ㄥ闁惧繐婀遍悾鎶芥⒒閸屾瑧顦﹂柟鑺ョ矋閹便劑鎮介崨濠備罕濠德板€曢崯浼存儗婢跺备鍋撻獮鍨姎妞わ缚绮欏顐㈩吋婢跺鍘介梺褰掑亰閸犳稖妫㈤梻浣哥秺閺€鍗烆渻閽樺娼栨繛宸簻閹硅埖銇勯幘妤€鎳庢慨鍏肩節閻㈤潧浠﹂柟鍛婂▕钘熼柟鎹愭硾閸ㄦ繂鈹戦悩瀹犲缂佺姷绮换娑㈡晲鎼粹€冲箰缂備降鍔岄…宄邦潖濞差亜绠伴幖娣灮閸欏棝姊虹拠鑼缂佽鍊块幃楣冩偨缁嬪灝鑰垮┑鐐村灦閻熝囧储闂堟侗娓婚柕鍫濇缁€鈧┑鈽嗗亝缁嬫挸顕ｈ閸┾偓妞ゆ帒瀚崐鐢告偡濞嗗繐顏紒鈧崘顔藉仺妞ゆ牗绋戝ù顕€鏌涢埡鍐ㄤ槐鐎规洘锕㈤、娆撴嚃閳哄啯姣庨梺鑽ゅ枑缁矂寮甸鍌滃崥闁绘梻鍘ч崡鎶芥煟閹邦剛校婵☆偄鍟撮獮鍐煛閸涱噮妫冨┑鐐村灦椤ㄥ牓骞戦弴銏♀拻濞达絿鐡旈崵娆戠磼缂佹ê鐏╅柟骞垮灲瀹曠厧鈹戦崼鐔割啎婵犵數濞€濞佳兾涢鐑嗙劷闁冲搫鍊舵禍婊堟煙閹屽殶缂佺姵顭囩槐鎺楁偐鐎圭姴顥濆銈庝簻閸熷瓨淇婇崼鏇炲耿婵°倐鍋撶悰鑲╃磽閸屾瑧鍔嶇憸鏉垮暙椤洭鏁撻悩闈涚ウ婵犵數濮村ú銈夋倷婵犲啨浜滈柟鍝勭Х閸忓矂鏌涘鈧褔鈥旈崘顔嘉ч柛鈩冾焽椤︺儱鈹戦埥鍡椾簼缂佸鎸搁锝堫樄闁糕斁鍋撳銈嗗笒鐎氼參鍩涢幋鐘电＜妞ゆ牗绋掔粈鍐煛婢跺﹦绉洪柡灞剧〒閳ь剨缍嗛崑鍛焊椤撶喆浜滄い蹇撳閺嗭絽鈹戦垾宕囧煟鐎规洖宕灃闁告劦浜濋崳顖炴⒒娴ｇ瓔鍤欓悗娑掓櫊瀹曟瑨銇愰幒鎴犵厬闂佸憡鍔﹂崰鏍及閵夛妇绠鹃柟瀛樼懃閻忊晝绱掗悪鍛М闁哄被鍔戝顕€宕掑☉娆戝涧闂備礁鎲￠敋鐎规洦鍓熼崺鐐哄箣閿旇棄鈧兘鏌℃径瀣仼濞寸姵鎮傞弻銈囨啑閵堝應鍋撻弴銏犵厴闁硅揪瀵岄弫濠囨煕韫囨洖甯舵い锔规櫊濮婃椽妫冨☉娆愭倷闁诲孩鍑归崹宕囧垝鐠囨祴妲堥柕蹇曞Х椤旀帡鏌ｉ悩鑽ょ窗闁靛棌鍋撻梺鐟板殩缁绘繂顫忕紒妯诲闁兼亽鍎埀顒€鍟扮槐鎺楀焵椤掍焦濯撮悶娑掆偓鍏呭濠殿喗锕╅崑鍕暤閸℃瑢鍋撳▓鍨灕妞ゆ泦鍥х叀濠㈣泛谩閻斿吋鐓ラ悗锝呯仛缂嶅苯鈹戦悩娈挎毌婵℃彃鎳樺畷瑙勫閺夋垼袝闁诲函缍嗛崰鏍不閻斿皝鏀介柛灞剧閸熺偤鏌嶉柨瀣仼缂佽鲸甯為埀顒婄秵閸嬫帡宕曢妷鈺傜厱閹兼番鍨婚埥澶愭婢跺绡€濠电姴鍊婚崙褰掓⒑椤撗冪仯闁逞屽墯椤旀牠宕板☉銏╂晪鐟滄棃宕洪妷锕€绶為柟閭﹀墻濞煎﹪姊虹紒妯曟垼銇愰崘顏嗙焾妞ゆ洍鍋撴慨濠勭帛缁楃喖鍩€椤掆偓椤洩顦归柍銉畵瀹曞ジ濡烽妷褝绱甸梻浣瑰劤濞存岸宕戦崱娑栤偓鍛存倻閼恒儳鍘撻梺鍛婄箓鐎氼參宕抽崷顓犵＜?"
        if goal:
            anchor += ""
        if localized_focus:
            anchor += ""
        elif current_focus:
            anchor += "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧湱鈧懓瀚崳纾嬨亹閹烘垹鍊為悷婊冪箻瀵娊鏁冮崒娑氬幗闂侀潧绻堥崺鍕倿閸撗呯＜闁归偊鍙庡▓婊堟煛瀹€鈧崰鏍蓟閸ヮ剚鏅濋柍褜鍓熷绋库槈閵忥紕鍘遍梺闈涱煭婵″洨绮婚悙鎼闁绘劕顕晶顏堟嚕閹邦厹浜滈柟鍝勬娴滈箖姊虹拠鍙夌濞存粍绻勯幑銏犫槈閵忕姴绐涘銈嗙墬椤曟挳鏁愰崥鍐查叄瀹曟儼顧傞棅顒夊墮閳规垿鍨惧畷鍥х厽閻庤娲忛崝鎴︺€佸▎鎾崇缁炬澘褰夐崫妤冪磽閸屾艾鈧悂宕愰悜鑺ュ殑闁肩鐏氶崣蹇涙煙閹増顥夌痪顓涘亾闂備浇顫夐崕鐓幬涢崟顖涘珔闁绘柨鎽滅粻楣冩煙鐎电鈧垵顫濋鈺嬬秮瀹曞ジ鎮㈢粙鍨紟婵犲痉鏉库偓鎰板磻閹剧粯鐓熸俊銈傚亾闁挎洦浜滈锝夘敃閿曗偓缁犳氨鎲告径鎰哗濞寸姴顑嗛悡鐔兼煙闁箑澧紒鐙欏洦鐓曢柨婵嗙墛椤ュ鏌嶇憴鍕伌闁诡喗鐟╅崺鈩冩媴瀹勯偊妫滈梻鍌氬€搁崐椋庣矆娓氣偓楠炴牠顢曢敂钘夊壒婵犮垼娉涢懟顖滄閵堝鐓曞┑鐘插閺嬫柨霉濠婂棗袚缂佺粯绻堥幃浠嬫濞戞鎹曟繝纰樻閸嬪懘鎮烽埡浣烘殾闁哄洢鍨圭粈鍐╃箾閺夋埈鍎愰柣蹇庣椤啴濡堕崱妯鸿敿闂佹悶鍔嶅浠嬪箖閿熺姵鍋勯柣鎾虫捣椤旀劕鈹戦悜鍥╃У闁告挻鐟╅幃姗€宕￠悜鍡欏數闁荤喐鐟ユ刊鍫曞箣閿曗偓妗呴梺鍛婃处閸ㄩ亶寮插鍫熺厽闁逛即娼ф晶顖涙叏閿濆懐澧﹂柟顔筋殔閳绘捇宕归鐣屼粚婵＄偑鍊栧▔锕傚炊閼稿灚娅嶅┑鐘绘涧閸婂鈥﹂崼銉︾厑闁搞儯鍔婃禍婊堟煙閺夊灝顣崇紒澶屾暬閺屽秷顧侀柛鎾寸懃鐓ゆい鎾跺剱濞兼牜绱撴担鑲℃垶鍒婇幘顔界厱婵炴垶锕銉╂煛閸℃澧︽慨濠冩そ瀹曠兘顢樿閸旂顪冮妶搴″箻闁稿繑锕㈤悰顕€宕卞☉妯碱槹濡炪倖鐗徊楣冨疾椤掑嫭鈷戠紓浣姑慨宥嗙箾娴ｅ啿鎳愰惌鍫ユ煥閺囩偛鈧綊藟婵犲啨浜滈柟鎵虫櫅閻忣亜顭跨捄鍝勵伀缂佽鲸甯為埀顒婄秵閸嬪嫬霉椤旈敮鍋撶憴鍕闁搞劌娼￠悰顕€宕堕浣镐罕闂佸壊鍋呯换鈧柛鏍ㄧ墵濮婄粯鎷呯憴鍕哗闂佺瀛╃划鎾崇暦濮椻偓閸┾剝绻濋崘鐐紙闂傚倸鍊搁崐椋庢濮橆剦鐒界憸鎴炴櫠濠靛鈷戦柛婵嗗閸ｈ櫣绱掗鑺ュ磳妤犵偛鍟村杈╃磼閻樺磭娲存鐐寸懇瀹曟﹢顢旈崟顒佹瘎闂傚倷娴囧畷鍨叏閺夋嚚娲偐鐠囪尙鍔﹀銈嗗坊閸嬫挾鐥紒銏犲箺缂佸倹甯￠崺锟犲川椤旀儳骞楅梺鐟板悑閻ｎ亪宕硅ぐ鎺戝惞妞ゆ帒瀚悡鏇熺箾閸℃绠伴柡鍡秮閺屾洟宕遍弴鐙€妲銈庡亝缁捇宕洪埀顒併亜閹烘垵顏╃紒鐘虫緲閳规垿鎮╅幓鎺撴缂備礁澧庨崑銈夊蓟濞戙垹鐒洪柛蹇婃櫆閸ㄥ灝顕ｉ崼鏇炵濞达絽鍘滈幏缁樼箾鏉堝墽绉繛鍜冪悼閺侇喖鈽夐姀锛勫幈闂佸搫鍟犻崑鎾绘煥閺囨ê鐏╅柣锝呭槻鐓ゆい蹇撳閸炪劌顪冮妶鍡楃仴鐟滄壆鍋涙晥婵°倕鎳忛崑鈩冪節婵犲倸鏆熺紒鐘烘珪娣囧﹪宕ｆ径濠傤潚濡ょ姷鍋炵敮鎺曠亙婵炶揪绲介幉锟狀敇缂佹ü绻嗛柣鎰典簻閳ь剚鐗滈弫顔界節閸ャ劌鈧潡鏌ㄩ弴鐐测偓褰掑磻閻旀悶浜滈煫鍥ㄦ尵婢ф盯鏌嶉柨瀣伌闁哄矉缍侀幃銏㈢矙濞嗙偓顥嬮梻浣风串缂嶅棝宕ｉ崘顔艰摕婵炴垯鍨规儫闂侀潧鐗嗗ú銊╂偂閹剧粯鈷戠紓浣姑肩欢閬嶆煕閿濆繒绉柣娑卞櫍楠炴帡骞婇搹顐ｎ棃闁糕斁鍋撳銈嗗笒閸婄粯绋夊澶嬬叆婵犻潧妫Σ褰掓煟閹惧娲撮柡灞剧洴楠炲洭宕滄担绋跨厒濠电偛鐡ㄧ划鎾剁不閺嵮屾綎闁惧繗顫夌€氭岸鏌ょ喊鍗炲妞ゆ捁娅ｇ槐鎾存媴閽樺鍘梺鐓庣秺缁犳牠鏁愰悙鍓佺杸婵炴垶鐟﹂崕顏堟煟閻斿摜鎳冮悗姘煎墴瀹曘垼銇愰幒鎾嫼闂佸憡绋戦敃锝囨闁秵鐓曢柣妯虹－婢ь亪鏌嶉挊澶樻Ъ妞わ箑顕槐鎺撴綇閵婏箑闉嶉梺鐟板槻閹虫ê鐣烽锕€绀嬮柟鎼灣缁夘噣鏌＄仦鍓ф创濠碘剝鎮傛俊鐤槺闁惧繐閰ｅ鐑樺濞嗘垶鍋ч梺绋跨箲閿曘垹顕ｉ锕€绠涢柡澶婄仢閼板灝鈹戦悙鍙夘棡闁搞劎鎳撳嵄闁搞儺鍓氶埛鎺懨归敐鍛暈闁哥喓鍋ら弻娑㈠棘閻愬弶鍣界痪鎹愬Г閹便劌螣鐠恒劎缈辨繝娈垮枛閸熷潡鍩為幋锔藉亹鐎规洖娴傞弳锟犳⒑閹惰姤鏁遍柛銊ユ健瀵鈽夊Ο閿嬫杸闂佺硶鍓濋〃蹇斿閳ь剟鏌ｉ悙鏉戝毈濞存粠浜滈～蹇撁洪鍕獩婵犵數濮撮崯浼村矗閸℃稒鈷掑ù锝囶焾缁ㄨ崵绱撳鍕獢闁绘侗鍣ｅ畷鍗炍旈崘鈺傜暦闂備線鈧偛鑻晶鎾煕閳规儳浜炬俊鐐€栫敮鎺楁晝閿斿墽鐭撻柣銏犳啞閻撴洟鏌熼幆褜鍤熼柕鍡樺笒椤法鎲撮崟顒傤槰缂備浇妗ㄧ划娆忕暦閵婏妇绡€闁告洦鍋勬俊鍥ㄧ節閻㈤潧啸闁轰礁鎲￠幈銊р偓闈涙啞瀹曟煡鏌熼幏灞界劷闁逞屽墮閹虫﹢銆佸Δ鍛妞ゆ帒鍊搁獮妤佷繆閻愵亜鈧牠骞愭ィ鍐ㄧ獥閹肩补鍩楄ぐ鎺濇晪闁逞屽墴瀵鍨惧畷鍥ㄦ畷闁诲函缍嗛崜娑㈡晬閻斿摜绠鹃悗鐢殿焾椤庢挾绱掗悩铏碍闁伙絽鍢查…銊╁幢閳哄倐顏堟⒒娴ｅ憡鍟為悽顖涱殘缁瑩骞嬮敐鍥︾胺闂傚倷鑳剁划顖炴晝閵忕媭鐒界憸搴ｇ矉閹烘鏅濋柛灞剧〒閸欏棗鈹戦绛嬬劸闁糕晜鐗犻幃锟犳偄閸忚偐鍙嗗┑鐘绘涧濡瑩骞栭幇鐗堢厱婵☆垯璀﹂崵鐔兼煃瑜滈崜婵嬶綖婢跺⊕娲冀椤撶喎浜梺缁樻尭濞寸兘寮抽敃鍌涒拺妞ゆ巻鍋撶紒澶婎嚟缁鈽夊▎宥勭盎闂佺懓鎼Λ妤佺閻愵剛绡€婵炲牆鐏濋弸鏃堟煕閵娿劌鍚规俊鍙夊姍楠炴鈧稒锚椤庢挻绻涚€电孝妞ゆ垵鎳橀獮妤呮偨閸涘﹦鍘介梺闈涚箚閺呮盯鎮橀敐澶嬬厱閻庯綆鍓欓弸搴ㄥ础闁秵鐓欓柣妤€鐗婄欢鑼磼閻樺啿鈻曢柡宀€鍠栧畷姗€鎳犻濠勭闂備礁鎽滄慨鐢告偋閻樿崵宓侀柛鎰靛枛閻掓椽鏌涢幇銊︽珔闁告柨鎳庨埞鎴﹀煡閸℃浠村銈嗘肠閸ヨ埖鏅滃銈嗙墱閸嬬偤鍩涢幒鎳ㄥ綊鏁愰崶鈺傛啒闂佹悶鍊栭悷鈺呭箖濡も偓閳藉骞掗幘瀵稿綃婵＄偑鍊戦崹娲偡閳轰緡鍤曞ù鐘差儛閺佸洭鏌ｉ幇顔芥毄鐎规洖鐖煎缁樻媴閸涘﹥鍎撶紓浣割儎缁舵艾鐣烽姀锛勵浄閻庯綆浜為敍娑欑節閵忥絾纭鹃懝宀勬煛閳ь剚绂掔€ｎ偆鍘遍柣蹇曞仜婢т粙鎯岄妶澶嬬厽闁圭儤顨堥悾娲煛鐏炲墽娲村┑鈩冩倐婵＄兘濡烽姀鐘卞濠殿喗绻傞惉鍏肩濞嗘挻鈷掑ù锝囨嚀椤曟粎绱掔拠鎻掆偓鍧楃嵁婵犲啯鍎熼柕濞垮劜鏉堝牆鈹戦悙鍙夘棡闁搞劌婀辨竟鏇熺附閸涘﹦鍘藉┑鈽嗗灥濞咃絾绂掑☉銏＄厸闁糕檧鏅涙晶鎾煛鐏炵硶鍋撳畷鍥ㄦ畷闂侀€炲苯澧寸€规洑鍗冲浠嬵敇閻愮數鏆繝鐢靛Т閿曘倝宕ュ鈧幃銏ゅ礂閻撳簶鍋撴繝姘厓闁告繂瀚埀顒佹倐椤㈡棃骞栨担鍏夋嫼闂佺厧顫曢崐鏇熺閿斿墽妫柡澶庢硶鏁堥梺璇″枤閸忔﹢宕洪埄鍐懝闁搞儯鍔庣粙浣糕攽閻樺灚鏆╁┑顔炬暬閹虫繈宕滆椤ユ岸鏌涜箛姘汗缂佺娀绠栭弻娑㈠焺閸忕媭浜幃鐐烘倷椤戣法绠氶悗鐟板閸犳牕鈻嶅鍡樺弿濠电姴鎳忛鐘崇箾閹寸姵鏆€规洦浜濋幏鍛村川婵犲嫭婢撶紓鍌氬€搁崐鐑芥嚄閸撲礁鍨濇い鏍ㄧ矋瀹曟煡鏌涢鐘插姢鐎规挷绶氶弻娑㈠箛闂堟稒鐏嶉梺绋匡工椤兘寮婚敃鈧灒闁绘艾顕粈鍡涙⒑闂堟丹娑㈠礋椤愶絿鈧箖姊绘繝搴′簻婵炶濡囩划娆撳箳濡も偓绾炬寧淇婇妶鍛櫤闁绘挻鐟╅弻鐔烘喆閸曨偄顫岄梺缁樻尰閸旀瑩寮诲☉銏″亹闁告劖褰冮～鎺楁⒑閸濆嫮鐒跨紒鎻掆偓鐔轰簷闂備線鈧偛鑻晶鎾煙椤斻劌娲ら獮銏＄箾閸℃ê鐏ョ€规洏鍎叉穱濠囧Χ韫囨洖鍩岄梺鍝ュ櫏閸ㄥ爼骞冮敓鐘茬妞ゅ繐鎳庨弸鎴濃攽閻樿宸ラ柣妤€妫涚划鍫ュ醇閻旇櫣顔曢梺绯曞墲钃遍悘蹇ｅ幘缁辨帡鎮╅棃娴讹綁鏌熸笟鍨妞ゎ亜鍟伴幏鐘荤叓椤撶儐妫滈梻鍌氬€风欢姘焽瑜嶈灋闁哄啫鍊婚惌鍡椼€掑锝呬壕闂佹寧绻勯崑娑⑩€﹂妸鈺侀唶婵犻潧鐗嗘慨锔戒繆閻愵亜鈧牜鏁繝鍥ㄥ€块柨鏇炲€搁惌妤呯叓閸ャ劎鈯曢柣鎾冲暟閹茬顭ㄩ崼婵堫槶闂佺粯姊婚崢褔鎷戦悢鍏肩厪濠电偛鐏濋崝妤佷繆閹绘帞澧涘ǎ鍥э躬椤㈡稑鈻庨幒婵嗗Τ濠电偛顕慨鎾Χ閹间礁绠栨俊銈傚亾闁崇粯鎹囧畷褰掝敊閻ｅ奔绨介梻鍌欑閹诧繝銆冮崨鏉戠柈闁秆勵殣缂嶆牠鐓崶銊︾缁炬儳鍚嬫穱濠囶敍濠垫劕娈銈呭閹歌崵鎹㈠☉銏犵闁哄鍨靛В鍫ユ⒑閹肩偛濮傚ù婊嗘硾椤曪綁顢曢敂缁樻櫖濠殿喗锚閸氬鈧潧鐭傚娲濞戞艾顣烘俊銈囧Т閹诧紕绮嬪鍜佺叆闁告洍鏅欑花濠氭⒑閹稿孩绀€闁稿﹦鎳撻埥澶庮樄闁哄矉缍侀弫鎰板川椤撶啘鈺呮⒑鐎圭媭娼愰柛銊ョ仢閻ｉ攱瀵奸幖顓熸櫓闂佸吋浜介崕鍝勎涢崘顔藉€甸悷娆忓绾炬悂鏌涢弮鈧崹鍧楀Υ娴ｇ硶鏋庨柟鍓цˉ閹峰鏌ｆ惔銊︽锭闁硅姤绮岄埢鏃堝锤濡や讲鎷婚梺绋挎湰閼归箖鍩€椤掑嫷妫戠紒顔肩墛缁楃喖鍩€椤掑嫮宓佸鑸靛姈閺咁剟鏌涢弴銊ュ箻闁绘挻鎹囧铏规兜閸涱喖娑ч梻鍌氬鐎氭澘鐣烽幋锕€围濠㈣泛顑囬崢顏呯節閻㈤潧浠ч柛瀣尭閳诲秹宕卞☉娆戝幈闁诲函缍嗘禍婊堝焵椤掆偓濞尖€愁嚕婵犳艾鍗抽柣鏃堫棑缁愮偛鈹戦悙鏉戠仸闁挎洍鏅涚叅妞ゆ挾濮风壕钘壝归敐鍛儓闁宠鐗忕槐鎺楁偐瀹曞洤鈷岄悗娈垮枛椤兘骞冮姀銏″仒闁炽儱鍘栨竟鏇㈡⒑濮瑰洤鐏╅柟娴嬧偓鏂ユ瀺婵犲﹤鎳愮壕濂稿级閸偄浜濋柣婵愪邯閺屾洟宕惰椤忣剛绱掗悩宕囨创妤犵偞顭囬幑鍕瑹椤栨稒顔旈梻鍌氬€风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼顢氶埀顒勫蓟濞戙垺鍋嗗ù锝夋櫜閸犲﹪姊虹化鏇熸澓闁搞劍妞介獮鍡涘籍閸惊鈺呮煏婢诡垰鑻幃鍫ユ⒒閸屾瑨鍏岀紒顕呭灦閳ワ箓宕堕閿亾閸岀儐鏁婇柣鎰靛墻濞肩喖姊洪崨濠勬噧妞わ箒浜褔鍩€椤掑嫭鍊甸柛蹇曨焾瀹撳棝鏌￠埀顒勫础閻戝棛鍞靛┑顔姐仜閸嬫捇鏌涢埞鎯т壕婵＄偑鍊栫敮濠勭矆娴ｈ鍙忕€广儱娲犻崑鎾舵喆閸曨剛顦ㄩ梺鎼炲妼濞硷繝鎮伴鍢夌喖宕ㄩ棃娑㈠弰妞ゃ垺鐗滈幑鍕Ω瑜庨弲銊╂⒒閸屾艾鈧兘鎮為敂閿亾缁楁稑鍘惧ú顏勫唨妞ゆ挾鍋熼敍娆撴⒑缂佹ê鐏辨俊顐㈠缁鎮㈤崗鑲╁幗闂侀€涘嵆濞佳勬櫠缂佹绠鹃柛顐ｇ矌閻瑩鏌″畝瀣М妤犵偛娲、妤佹媴閸欏浜炲┑鐘殿暯濡插懘宕归鍫濈；闁瑰墽绮埛鎺懨归敐鍥╂憘闁搞倕鍟撮弻娑㈡偆娴ｉ晲鍠婇悗瑙勬礃閸庡ジ藝瑜版帗鐓曢柣鎰皺閸╋絾鎱ㄦ繝鍛仩缂佽鲸甯掕灒闁煎鍊曞铏繆閻愵亜鈧垿宕濆畝鍕厐闁挎繂顦弰銉╂煃瑜滈崜姘跺Φ閸曨垰绠崇€广儱娲ゆ俊浠嬫煟韫囨挾绠叉繝銏☆焾瑜颁線姊洪幖鐐插妧鐎广儱鐗嗛幆鍫ユ⒒娴ｇ瓔鍤冮柛鐘愁殜閹兘濡烽埡濠冩櫓闂婎偄娲︽笟妤呭极婵犲洦鐓熼柟鐐▕椤庢銇勯妷銉ф慨濠勭帛閹峰懐绮电€ｎ亝顔勫┑掳鍊楁慨鐢稿箖閸岀偛绠栨俊顖欒濞尖晠寮堕崼娑樺婵炲牊婢橀埞鎴炲箠闁稿﹥娲熷畷顖炴偐鐠囪尙锛涢梺鐟板⒔缁垶藟閸喓绠鹃柟瀵稿仧婢ь亜霉閻欌偓閸ｏ綁骞冨Δ鍐╁枂闁告洦鍓涢ˇ銉╂⒑缂佹澧柛姘儐缁岃鲸绻濋崒銈嗘〃閻庡厜鍋撳┑鐘插敪椤掍椒绻嗛柣鎰典簻閳ь剚鐗曢～蹇涙偡閹冲﹥妞介幃銏＄附婢跺绋佹繝鐢靛仜濡﹥绂嶅┑瀣；闁跨喓濮甸埛鎴炪亜閹惧崬濡块柣锝堥哺缁绘盯宕煎┑鍫濈厽濠殿喖锕ㄥ▍锝囧垝濞嗗繆鏋庨柟顖嗗啫顥愰梻鍌欒兌椤牓顢栭崶顒€绐楅柟閭﹀枤閻鈧箍鍎遍ˇ顖滅不閻熻埇鈧帒顫濋浣割槱闂佸搫鎷戠紞浣割潖濞差亝顥堟繛鎴欏灮瀹曨亞绱撴担浠嬪摵婵炶尙鍠庨悾鐑芥晲婢跺﹤鑰垮┑鐐村灦閻熴垽骞忓ú顏呪拺闁告稑锕︾粻鎾绘倵濮樼厧骞楃€垫澘瀚板畷鐔碱敍濞戞艾寮虫繝娈垮枟椤牓宕洪弽顓熷亗闁哄洢鍨洪悡娑㈡煕閹板墎鍒板ù婊冨⒔缁辨帡鎮欓浣哄嚒缂備礁顦抽～澶嬬┍婵犲洦鍋ㄧ紒瀣硶椤︽澘顪冮妶鍡欏缂佹煡绠栧鏌ユ晲婢跺鎷虹紓鍌欑劍閿氬┑顔肩墛缁绘盯宕楅懖鈺傚櫚閻庢鍠楅幃鍌炲箖閳哄啰纾兼俊顖炴敱鐎氬ジ姊洪懡銈呅㈡繛鑼█閸┾偓妞ゆ帒鍟悵顏堟煟韫囨挻顥犵紒杈ㄦ尰缁楃喖宕惰閻忓秹姊洪懡銈呮瀭闁稿海鏁婚獮鍐箚瑜忛弳瀣煙闁垮鈷愭俊顐㈠暙閻ｇ兘濡搁埡濠冩櫍濠电娀娼ч悧蹇涘磹閻愮儤鈷掗柛灞剧懅缁愭梹绻涙担鍐叉硽閸ヮ剦鏁囬柕蹇曞Х閿涚喖姊绘笟鍥у缂佸鎸抽幃锟犲即閵忥紕鍘搁梺鎼炲劘閸庨亶鎮橀鍫熺厓闂佸灝顑呯粭鎺楁婢舵劖鐓ユ繝闈涙閸ｆ椽鏌涢悢鍝勪槐闁哄瞼鍠栭、娑橆潩閸楃儐鏉搁梻渚€娼уú銈団偓姘嵆瀵偊宕掑鍕彴闂佽偐鈷堥崗娑橆浖閹剧粯鈷掑ù锝囩摂閸ゅ啴鏌涢悤浣镐喊鐎规洘鍎奸ˇ瀛樸亜閿旇姤绶叉い顏勫暣婵″爼宕卞▎蹇ｆ椒婵犳鍠楄彠闁告梹鍨煎Λ鐔奉渻閵堝棙纾甸柛瀣崌閺屸€崇暆鐎ｎ剛袣缂備胶濮甸惄顖氼嚕閹绢喗鍊烽柣妤€鐗嗘刊浼存⒒閸屾瑨鍏屾い顓炵墢閳ь剚绋堥弲婊呮崲濞戞瑧绡€闁稿本绮嶅▓鎯р攽閻樼粯娑фい鎴濇噽閻氭儳顓兼径瀣幈濡炪倖鍔戦崐鏇㈠汲闁秵鐓欑€瑰嫰鍋婇悡鍏兼叏婵犲懏顏犵紒顔界懇楠炴劖鎯旈姀鈥愁伆闂傚倷娴囧畷鐢稿闯閿旀垝绻嗛柛銉㈡櫅閸ㄦ繂鈹戦悩鎻掓殭妞ゆ洟浜堕幃妤€鈽夊▎妯煎姺闂佸憡锕㈡禍鍫曞蓟閿濆棙鍎熸い鏍ㄧ矌鏍￠梻浣侯焾椤戝懐鈧凹鍙冮獮鍫ュΩ閵夘喖鎮戦梺鎼炲劵缁茶姤绂嶆ィ鍐╁仭婵炲棗绻愰顏嗙棯閻愵剚鍊愰柡灞剧洴婵℃悂濡烽敐鍛垝闂佽姤蓱缁诲牓寮诲☉銏℃櫆閻犲洦褰冪粻浼存⒑缁嬫鍎愰柟鎼佺畺楠炲骞橀鑲╊槹濡炪倖宸婚崑鎾淬亜閿旇娅婃慨濠冩そ楠炴牠鎮欓幓鎺濈€抽梻浣虹帛閻楁洟濡堕崨濠佺箚閻庢稒顭囬悷褰掓煃瑜滈崜娆擃敋閿濆绠绘い鏃傗拡濞煎﹪姊虹紒姗堣€挎繛浣冲洨宓侀柛顐ゅ枔缁♀偓濠电偛鐗嗛悘婵嬪几閻斿吋鐓ラ柡鍥殕濞呭﹦鈧娲忛崹铏圭矉閹烘柡鍋撻敐搴樺亾椤撱劑妾紒缁樼箞濡啫鈽夊顒夋殼闂備胶顭堥鍡涘箰妤ｅ啫绠熼柟缁㈠枛缁€瀣亜閹烘垵浜炴俊鑼跺煐娣囧﹪鎮欓鍕ㄥ亾閵堝鍌ㄥ┑鍌氭啞閸嬪鏌熼幍顔碱暭闁稿﹤鐖奸弻娑㈠箛闂堟稒鐏嶉梺鎶芥敱閸ㄥ灝顫忓ú顏嶆晝闁靛牆鎳嶇划鍫曟⒑閸忓吋銇熼柛銊╀憾瀵煡宕奸弴鐐殿吋濡炪倖鏌ㄦ晶浠嬫晬濠婂牊鐓涘璺猴功婢ф垿鏌涢弬鑳闂囧銇勯弴妤€浜鹃梺鍝勬湰閻╊垶宕洪敍鍕ㄥ亾閿濆骸澧伴柣锕€鐗撻幃妤冩喆閸曨剛锛橀梺鍛婃⒐閸ㄥ潡濡存担绯曟瀻闁规儳纾悾楣冩偡濠婂啰肖缂侇喖顭锋俊鐑藉Ψ閵忊剝鏉搁梻浣瑰缁嬫垹鈧凹鍓氱粋宥嗙附閸涘﹦鍘辨繝鐢靛Т閸熺増鏅堕悽鍛婄厵妞ゆ柣鍔屽ú銈夊础閹惰姤鐓熼柟閭﹀墰鏍￠梺鐑╂櫓閸ㄤ即顢氶敐澶樻晢闁逞屽墴閸┿垺鎯旈妸锕€鈧攱銇勯幒鍡椾壕闂佷紮闄勭划鎾愁潖缂佹ɑ濯撮柛娑橈龚绾偓闂備胶顭堢花娲磹濠靛棛鏆﹂梻鍫熶緱濞尖晠鏌ｉ幇顓炵亰婵顨婂娲捶椤撶偛濡洪梺鐟版啞閹倿宕洪埀顒併亜閹哄棗浜惧銈庡幘閸忔ê顕ｆ繝姘у璺猴功閻ｆ娊姊洪崷顓炲妺闁搞劌鐏氶幈銊﹀緞閹邦厸鎷?"
        elif file_path:
            anchor += f"闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙绐涢梺鍝ュУ閹稿墽鍒掔紒妯稿亝闁告劏鏅濋崢浠嬫⒑闁稑宓嗘繛浣冲嫭娅犳い鏍仦閻撶喐绻濋棃娑欏缂佲偓鐎ｎ偅鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噧闁宠閰ｉ獮鍡氼槻濠㈣锚閳规垿鎮欓懠顒佹喖缂備緡鍠氭慨鐢电矉瀹ュ鏁傞柛鏇㈡涧濞堛劑鏌ｉ悩鍙夊缂佷焦娼欏嵄闁割偁鍎查悡蹇涚叓閸ャ劍绀€閸熸悂姊洪崨濠冣拹闁圭鍟块～蹇撁洪鍕獩婵犵數濮撮崐姝岊杺婵犵數鍋涢悺銊у垝瀹ュ鍋嬮柡鍥╁仜缁侇偊姊绘担绋款棌闁稿绶氬畷褰掓嚒閵堝拋妫滈梺鑺ッˉ銏ｃ亹閹烘挻娅滈梺绯曞墲椤ㄥ牏绮婇柨瀣閻庢稒顭囬惌鎺旂磼閻樺磭澧い顐㈢箻閹煎綊宕烽鐘靛幆闂佽崵濮垫禍浠嬪礉鎼淬垹顕遍柛銉墯閳锋垹绱掔€ｎ偒鍎ラ柛搴㈠灴閺屾稓鈧絻鍔岄埀顒佺箞閻涱噣宕橀鑺ユ闂佺粯蓱瑜板啫鐣甸崱娑欌拺缂備焦蓱閳锋帞绱掔紒妯肩畼闁奸缚椴哥换婵嗩潩椤撴稒瀚奸梺鑽ゅ枑閻熴儳鈧凹鍘惧▎銏ゅ箵閹烘繄鍞甸悷婊冪Ч閺屽﹪鏁愭径灞界ウ闂佸憡鍔﹂崰妤呭吹閸愵喗鐓冮柛婵嗗閺嗙喖鏌ㄥ☉娆戠煉婵﹨娅ｇ槐鎺懳熻箛锝勭敖濠㈣娲熼、姗€鎮㈤崨濠勫娇闂佸搫顦悧鍐疾濠靛牆顥氬┑鍌滎焾缁狙囨煕椤愶絿鈽夊┑陇鍋愮槐鎺戭渻閿曗偓閹虫劗澹曟總绋跨骇闁割偅绋戞俊鍏肩箾閹碱厼鏋涢柍瑙勫灴椤㈡瑩鎮锋０浣割棜闂傚倸鍊烽懗鍓佸垝椤栫偞鏅梻浣告啞閸╁啴宕戦幘缁樷拺闁告稑锕︽晶顒勬煟濡や胶鐭屾俊?`{file_path}` 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲濞淬儱鐗撳鎻掆槈閵忕姷顢呴梺鎯ф禋閸嬪倻鎹㈤崱娑欑厪闁割偅绻傞埀顒€鎲＄粋宥夋倷椤掑倻顔曢柣搴㈢⊕椤洭鎯岀€ｎ喗鐓曢幖娣灩閳绘洟鏌嶉妷锔筋棃鐎规洘锕㈤、娆撳床婢诡垰娲ょ粻鍦磼椤旂厧甯ㄩ柛瀣尭閻ｇ兘宕剁捄鐑樻珝濠电姷鏁告慨鐑藉极閹间礁纾绘繛鎴烆焸閻斿摜绡€闁搞儜鍛幀闂備礁鎲￠崝锕傚窗閺嶎剛绠芥繝鐢靛仩閹活亞寰婄捄銊﹀厹閻犺桨缍嶉敐澶婇唶闁靛濡囬崢顏堟椤愩垺鎼愰懝宀勬煕鐎ｎ偅宕岀€殿噮鍓熸俊鐑藉Ψ閵堝拋妫滈梻鍌欒兌缁垶宕归崗鍏煎弿闁靛牆顦壕褰掓煟閵忕姵鍟為柣鎾跺枛閺屾洝绠涙繝鍐炬綉闂佸摜鍠庣换姗€寮婚敐澶婄闁瑰瓨绺鹃幐鍐⒑闁偛鑻晶顖涖亜閺冣偓閻楃姴鐣锋导鏉戝嵆闁靛繒濮烽、鍛存⒑閸涘﹤濮囨俊顖氾工椤洭寮介銈囷紳婵炶揪缍€閸嬪倿骞嬮悙鎻掔亖闂佸搫顦伴崹顖炲焵椤掍礁绗掓い顐ｇ箞閹剝鎯旈敐鍕暰闂傚倷娴囧銊ф閿熺姴鍨傚ù鑲╄ˉ閳ь剚妫冨畷姗€顢欓崲澹洤绠圭紒顔煎帨閸嬫捇鎳犻鍌涙櫒婵犵绱曢崑鎴﹀磹瑜忕划濠氬箻閹颁胶鍔烽悷婊勬楠炲啴骞嗚閺嗗鏌熸担鍐╃彧闁哄倵鍋撻梻鍌欑閹芥粍鍒婇銏犵獥婵°倐鍋撻摶鐐烘煕閹扳晛濡块柡鍡畵閺屾洘绻涢悙顒佺彟闂佽桨绀侀敃顏勵潖婵犳艾纾兼慨妯煎帶濞堝爼姊洪悜鈺傛珔闂佸府绲介～蹇旂節濮橆剛锛滃┑鐐叉閸╁牆危椤曗偓濮婅櫣娑甸崪浣告疂缂備浇椴稿ú婊堝礆閹烘垟鏋庨柟鎯х－椤撴椽姊洪幐搴㈩梿婵☆偄瀚粋鎺楁焼瀹ュ棌鎷洪梻鍌氱墛閸楁洟宕奸妷銉ф煣濠电姴锕ら悧鍡欏婵犳碍鐓曢悘鐐插⒔閵嗘帞绱掗悩鑽ょ暫闁哄本鐩崺鍕礂閳哄倸鐏╁ù婊冩啞鐎佃偐鈧稒顭囬崢浠嬫⒑鐟欏嫬鍔ゆい鏇ㄥ弮楠炲﹪宕熼娑氬帾闂佹悶鍎滈崘鍙ョ磾婵°倗濮烽崑鐐衡€﹂崶顒€绠查柛鏇ㄥ灡閸婄粯淇婇姘辨癁闁稿鎹囬幊锟犲Χ閸モ晪绱冲┑鐐舵彧缂嶁偓妞ゆ洘鐗曢埢鎾诲即閵忊€充缓濡炪倖鐗楃粙鎴澝归鈧弻娑㈠煛閸愩劋妲愬Δ鐘靛仜椤戝寮崒婊呯＜婵☆垳绮悵锕傛⒒閸屾瑦绁扮€规洜鏁诲畷浼村冀椤撴壕鍋撻崒鐐存櫆闁伙絽鐬艰ぐ楣冩⒑閸濆嫭宸濆┑顕€顥撴竟鏇熺鐎ｎ偆鍘遍柣蹇曞仦瀹曟ɑ绔熷鈧弻宥堫檨闁告挻宀搁獮鍐磼濮樿鲸娈鹃梺瑙勫婢ф宕愭繝姘厾闁诡厽甯掗崝姘箾閸喎鐏存慨濠冩そ瀹曘劍绻濋崘銊х叝缂傚倷璁查崑鎾炽€掑锝呬壕閻庤娲滈幊鎾诲煘閹达箑鐐婇柕澶堝€楅惄搴ㄦ⒒娴ｅ憡鎯堢紒瀣╃窔瀹曟垿宕熼鍌ゆ祫闂佹寧娲栭崐褰掓偂濞戙垺鐓曟繛鎴濆船閺嬨倗绱掗悩闈涗槐闁哄矉绱曟禒锕傛倷椤掑偆妲风紓鍌欒兌婵數绮欓幒鏃€宕叉繛鎴欏灩缁犳氨鎲哥仦鍓х彾闁哄洢鍨洪埛鎴︽煠濞村鏉归柟鍑ょ節閺屾盯骞樼€靛憡鍒涢梺?"
        else:
            anchor += "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙绐涢梺鍝ュУ閹稿墽鍒掔紒妯稿亝闁告劏鏅濋崢浠嬫⒑闁稑宓嗘繛浣冲嫭娅犳い鏍仦閻撶喐绻濋棃娑欏缂佲偓鐎ｎ偅鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噧闁宠閰ｉ獮鍡氼槻濠㈣锚閳规垿鎮欓懠顒佹喖缂備緡鍠氭慨鐢电矉瀹ュ鏁傞柛鏇㈡涧濞堛劑鏌ｉ悩鍙夊缂佷焦娼欏嵄闁割偁鍎查悡蹇涚叓閸ャ劍绀€閸熸悂姊洪崨濠冣拹闁圭鍟块～蹇撁洪鍕獩婵犵數濮撮崐姝岊杺婵犵數鍋涢悺銊у垝瀹ュ鍋嬮柡鍥╁仜缁侇偊姊绘担绋款棌闁稿绶氬畷褰掓嚒閵堝拋妫滈梺鑺ッˉ銏ｃ亹閹烘挻娅滈梺绯曞墲椤ㄥ牏绮婇柨瀣閻庢稒顭囬惌鎺旂磼閻樺磭澧い顐㈢箻閹煎綊宕烽鐘靛幆闂佽崵濮垫禍浠嬪礉鎼淬垹顕遍柛銉墯閳锋垹绱掔€ｎ偒鍎ラ柛搴㈠灴閺屾稓鈧絻鍔岄埀顒佺箞閻涱噣宕橀鑺ユ闂佺粯蓱瑜板啫鐣甸崱娑欌拺缂備焦蓱閳锋帞绱掔紒妯肩畼闁奸缚椴哥换婵嗩潩椤撴稒瀚奸梺鑽ゅ枑閻熴儳鈧凹鍘惧▎銏ゅ箵閹烘繄鍞甸悷婊冪Ч閺屽﹪鏁愭径灞界ウ闂佸憡鍔﹂崰妤呭吹閸愵喗鐓冮柛婵嗗閺嗙喖鏌ㄥ☉娆戠煉婵﹨娅ｇ槐鎺戭潨閸℃瑥濮兼繝鐢靛仜閹冲繐煤濠婂嫮顩查柟闂寸缁犮儲銇勯弬鍨挃闁挎稒绮庣槐鎾诲磼濞嗘垵濡藉銈庡幖濞层倗鍙呴柣搴㈢⊕閿曗晛鈻撴禒瀣厽闁归偊鍨奸崵瀣偓瑙勬偠閸庣敻寮婚敐澶嬫櫜闊洦娲滈惁鍫ユ倵濞堝灝鏋涢柣鏍с偢閻涱噣骞囬鐔峰妳闂佹寧绻傜€氼剟藟濮樿埖鈷掗柛灞捐壘閳ь剛鍏橀幊妤呭礈娴ｇ鐏婂銈嗙墱閸嬫盯鎷戦悢鍏肩厪濠电偛鐏濋崜缁樼箾閹寸們姘跺绩娴犲鍊甸柨婵嗙凹缁ㄤ粙鏌ｉ敐鍡樸仢闁诡喖鍢查…銊╁川椤撗勬瘔闂佹眹鍩勯崹杈╂暜濡ゅ啠鍋撻棃娑栧仮闁诡喒鏅濈槐鎺懳熼悡搴＄疄闂傚倷绀侀幖顐⒚洪姀銈呯閻忕偟鍋撳▍鐘炽亜閺嶎偄浠﹂柣鎾存礋楠炴牕菐椤掆偓閻忣亪鎮樿箛锝呭箺闁靛洤瀚伴、鏃堝礋椤愶絾顔掑┑鐘殿暯閳ь剙纾崺锝団偓瑙勬磸閸旀垿銆佸▎鎴犵＜闁靛骏绱曢崐鐐烘⒒閸屾艾鈧兘鎳楅崼鏇椻偓锕傚醇閵夘喗鏅為梺鍛婄☉閻°劑寮插┑鍥ヤ簻闊洦鎸搁鎾煕閵堝棙绀€闁宠鍨块幃鈺佺暦閸ヨ埖娈归梻浣侯焾椤戝懐鈧凹鍣ｉ幆鈧い蹇撶墕缁狀垳鈧厜鍋撻柛鏇ㄥ亝閹虫瑩姊绘担鍛婃儓闁瑰啿顦靛鎻掆攽閸噥娼熼梺鍦劋濮婅崵澹曟總鍛婄厪闊洦娲栧瓭缂備胶濮撮…宄邦潖濞差亜浼犻柛鏇ㄥ枛椤忣厼顪冮妶蹇曠暤婵炰匠鍥ㄥ仼闁绘垼妫勫敮闂佸啿鎼敃銉╁疾濠靛鈷戦柟绋垮椤ュ棛鎮▎鎾寸厵闂佸灝顑嗛妵婵嬫煛瀹€瀣М闁诡喒鏅犲畷锝嗗緞瀹€濠冃ㄩ梻鍌欑窔閳ь剛鍋涢懟顖涙櫠椤斿墽妫紓浣靛灩楠炴绱掗崒娑樻诞闁糕斁鍓濋幏鍛村矗婢跺婢戦梻鍌欒兌缁垶宕濋弴鐑嗗殨闁割偅娲栭悡婵嬫煛閸ャ儱鐏柣鎾存礃缁绘盯宕卞Δ鍐唶闂佸搫妫寸紞渚€寮婚敐鍛闁告鍋為悵婵嬫倵鐟欏嫭绀冮柨鏇樺灲閵嗕礁鈻庨幘鏉戞異闂佸疇妗ㄧ粈浣藉€撮梻鍌氬€搁崐椋庣矆娓氣偓楠炲鏁撻悩鑼槷闂婎偄娲︾粙鎴︽偪閻愵剛绠鹃柟瀛樼懃閻忊晝绱掗埀顒佸緞閹邦厾鍘卞┑鐐村灦椤洭骞楅悩缁樼厓闂佸灝顑呴悘鎾煙椤旂瓔娈滅€规洜鍏橀、姗€鎮欓幇鍓佺ɑ闁靛洤瀚版俊鐑藉Ψ椤斿彨褎绻涢敐鍛悙闁挎洦浜妴渚€寮撮姀鈩冩珳闂佹悶鍎崝灞解枍濮樿埖鈷掑ù锝囩摂閸ゅ啴鏌涢悩鎰佹疁闁靛棗鍟换婵嬪炊閵夈垹浜惧〒姘ｅ亾鐎殿喗鎸虫慨鈧柍鈺佸暞閻濇洟姊洪懡銈呮瀾闁荤喕浜濠囧礈瑜夐崑鎾愁潩椤戞儳浠┑顔硷功缁垶骞忛崨鏉戝窛濠电姴鍊瑰▓妯肩磽閸屾瑦绁版い鏇嗗洤纾瑰┑鐘宠壘閻掑灚銇勯幒宥嗙グ濠㈣锕㈤弻娑㈠閳ュ磭绁烽悗瑙勬尭鐎氭澘顫忓ú顏勬嵍妞ゆ挴鍓濋妤呮⒑閸濄儱校妞ゃ劌锕獮鍐灳閺傘儲顫嶉梺闈涢獜缁辨洟宕㈤崡鐐╂斀闁绘劖娼欓悘銉р偓瑙勬处閸撶喎顕ｉ幖浣肝у璺侯儑閸樿棄顪冮妶鍡樺暗闁哥姴楠搁湁妞ゆ洍鍋撻柡灞糕偓宕囨殕闁逞屽墴瀹曚即寮介婧惧亾娴ｇ硶鏋庨柟鎯х－閻ｉ箖鎮峰鍐ч柣娑卞枤閳ь剨缍嗛崑鍡欏姬閳ь剛绱掗崜褍顣奸懣銈夋煕鐎ｎ偅灏柣锝囧厴瀹曟儼顦撮柛妯圭矙閺岋絾鎯旈妶搴㈢秷濠电偛寮堕悧鐘诲箖閵夛妇闄勭紒瀣濡差剟姊洪弬銉︽珔闁哥噥鍨遍崚濠勨偓娑櫳戦崣蹇旂節闂堟稒顥犳繛纭风節閺岋繝宕堕妷銉т痪闂佹娊鏀辩敮鎺楁箒闂佹寧绻傚ú銊╁箺閸岀偞鐓曢柕鍫濇閹冲洭鏌熼绛嬫當闁宠棄顦甸獮鎺楀箻鐎电绲跨紓鍌氬€风欢锟犲窗濡ゅ懏鍋￠柍鍝勬噽瀹撲線鏌熼悜妯虹劸婵炴挸顭烽弻锝夊箣閺冣偓濞呭懎霉濠婂牏鐣洪柡灞诲姂瀵挳鎮欏ù瀣壕闁归棿鐒﹂崐宄扳攽閻樻彃鏆斿ù婊勭矒閺岀喖宕崟顒夋婵炲瓨绮撶粻鏍ь潖閾忓湱纾兼俊顖濐嚙闂夊秶绱撴担绛嬪殭闁绘鎸搁锝嗙節濮橆厽娅㈤梺缁橆焾鐏忔瑩藝閵娾晜鈷戦柟绋挎捣缁犳捇鏌熼崘鑼ｇ紒鏃傚枛瀵挳濮€閳锯偓閹风粯绻涢幘鏉戠劰闁稿鎸荤换娑欐媴閸愭彃骞樻繛宸簻鍥撮梺鎼炲劵缁茶姤绂嶉悙顒佸弿婵☆垳鍘х敮鍫曟煟韫囥儳鎮肩紒杈ㄥ浮椤㈡瑥鈻庨幆褎顔勯梻浣哥枃濡嫰藝閸偅鍙忛柍褜鍓熼弻锝呂熷ú璇叉櫛闂佸摜鍠庨澶婎潖缂佹ɑ濯撮柛娑橈攻閸庢挸顪冮妶蹇曠窗闁告鍟块悾鐤亹閹烘垿鍞堕梺鍝勬储閸斿秹寮插鍫熲拺闁绘劘妫勯崝婊堟煛鐎ｎ亗鍋㈢€殿喓鍔嶇粋鎺斺偓锝庡亞閸樹粙姊鸿ぐ鎺戜喊闁告挻宀搁崺銏ゅ即閵忥紕鍘遍梺闈涚墕濞层倝寮告惔銊︾厓閻熸瑥瀚悘瀛樸亜閵忥紕鎳囬柟顔界懇椤㈡鎷呴崷顓燁潨闂傚倸鍊峰ù鍥ь浖閵娧呯焼濞撴埃鍋撶€规洦鍨抽埀顒佺⊕钃遍柛娆忕箻閺屽秷顧侀柛鎾跺枛瀵寮撮姀鐘诲敹濠电娀娼уú銈呪枔瀹€鍕拺缁绢厼鎳庤濠电偛寮堕悧鐘诲春閻愬搫绠ｉ柨鏃囨閳ь剛鍏橀弻鈩冨緞鐎ｎ亞浠兼繛瀵稿У閹倸顫忓ú顏呭殥闁靛牆鎳忓▓宀勬⒑閸涘﹣绶遍柛妯垮閳煡姊婚崒娆戠獢闁逞屽墰閸嬫盯鎳熼娑欐珷閻庢稒蓱閸欏繐鈹戦悩鎻掓殲闁靛洦绻勯埀顒冾潐濞插繘宕濆鍥ㄥ床婵犻潧顑呯粈鍐┿亜椤撶喎鐏︾悮鈺呮⒒閸屾艾鈧兘鎳楅崼鏇椻偓锕傚醇閵夘喗鏅為梺鍛婁緱閸亪宕戦幘鎰佹僵闁绘挸楠哥粻鑽ょ磽娓氬洤鏋涙い鎴濐樀閻涱噣骞掑Δ鈧粻鐘碘偓瑙勬礀濞层倝寮稿☉銏＄厵闁惧浚鍋嗘晶鐢告煕閳哄绡€鐎规洘顭囬幑鍕Ω閳哄偊绱┑鐘垫暩婵兘寮幖浣哥；闁绘顕х粻鍨亜韫囨挻顥滅紒韬插€曢湁闁绘ê妯婇崕蹇曠磼閻橀潧鍔嬬紒缁樼箖缁绘繈宕掑鍐炬毇闂備礁鎼€氥劑宕曢悽绋胯摕闁靛鍎弨浠嬫煕閳╁厾顏呯妤ｅ啯鈷戦柤濮愬€曢弸娑㈡煕鐎ｎ亷韬柟顕嗙節婵＄兘鍩￠崒婊冨箞闂備浇顫夊姗€宕ラ埀顒傜磼閵娿儺鐓奸柡宀嬬秮楠炴鎹勯悜妯间邯婵犳鍠栭敃銊モ枍閿濆洦顫曢柟鐑樺殾閻旂厧鎹舵い鎾跺Х閻ｆ娊姊婚崒娆戠獢婵炶壈宕电槐鐐哄炊閳哄啰顦繛鎾村焹閸嬫捇鏌熼璇插祮妞ゃ垺宀搁崺鈧い鎺戝瀹撲線鏌熼悜姗嗘當缂佺姷濞€閺屟嗙疀閿濆懍绨煎銈冨劚閻楁捇寮诲☉銏犵厴闁诡垎鍌氼棜婵犵绱曢崑鎴﹀磹閺嶎偅鏆滃┑鐘插閻棗銆掑锝呬壕閻庤娲樼换鍫濐嚕椤曗偓瀹曞ジ鎮㈤崣澶婎伜闂傚倷鑳堕…鍫ュ嫉椤掑嫭鍋＄憸蹇曞垝閿濆绫嶉柍褜鍓涢幑銏犫槈濞嗘劕顎撻梺鍛婂姇瀵爼藟濠婂嫮绠鹃柛婊冨暟缁夘喗鎱ㄦ繝鍕笡闁瑰嘲鎳樺畷銊︾節閸屾稒鐣肩紓鍌氬€风欢锟犲窗閺嶎厽鍋嬮煫鍥ㄦ礀閸ㄦ繈鏌涢銈呮灁闁荤喎缍婇弻宥堫檨闁告挻鐟╅、姘舵晲婢跺﹨鎽曢梺闈涱樈閸犳寮插鍫熲拺闁告挻褰冩禍鐐烘煕閻旈攱鍋ユ鐐茬箲缁绘繂顫濋娑欏缂傚倷绀侀鍡欌偓绗涘喛鑰垮ù鐓庣摠閻撶喖鏌ｉ弮鈧换鍌毭洪妶鍥╃焼濠㈣泛澶囬崑鎾荤嵁閸喖濮庡銈忕細閸楁娊骞冮敓鐘冲亜闁硅偐鍋樼花濠氭椤愩垺澶勯柟鍛婃倐椤㈡棃顢曢妶鍥╋紲婵犮垼娉涚€涒晠顢旈悩缁樼厓鐟滄粓宕滃┑瀣剁稏濠㈣泛鈯曢崫鍕庣喖宕楅悡搴＄哎闂備胶顭堥惉濂稿磻閻愬搫纾婚柍鍝勫€荤弧鈧梻鍌氱墛娓氭宕曡箛娑欑厽闁圭儤鍨规禒娑㈡煏閸パ冾伃妤犵偞甯￠獮瀣攽閹邦亝鍋呴梻鍌欒兌缁垳鏁幒妤佸€舵慨妯挎硾妗呴梺鍛婃处閸ㄦ壆绮诲畷鍥ｅ亾楠炲灝鍔氶柣妤€妫濆畷銏ゅ灳閹颁焦瀵岄梺闈涚墕缁绘帡宕氶幍顔瑰亾濞堝灝鏋涘褍閰ｉ獮鎴﹀閻橆偅鏂€闁诲函缍嗘禍璺侯焽婵犲洦鈷戦悗鍦У椤ュ淇婇锝囨创鐎规洘绻堥獮鏍ㄦ媴閸忓瀚奸梺鑽ゅТ濞测晝浜稿▎鎴犱笉闁绘鐗勬禍婊堟煙鐎涙绠ユ俊鎻掓啞閵囧嫰顢曢姀銏㈩唶闁绘挶鍊栭妵鍕疀閹炬潙娅ｆ繛瀛樼矋椤ㄥ﹪寮婚悢鐓庣闁兼祴鏅滃▓顒勬⒑閹肩偛濡芥俊鐐舵閻ｉ攱瀵奸弶鎴犵杸濡炪倖甯掗ˇ鎵偓闈涚焸濮婃椽妫冨☉姘暫缂備胶绮敮鐐靛垝閺冨牊鍋ㄩ柛娑橈功閸橀亶姊虹紒妯忣亪鎮块崶銊х彾婵せ鍋撶€规洩绻濋弻鍡楊吋閸℃瑥骞嶉梻浣筋潐椤旀牠宕伴弽顓溾偓鍌涚附閸涘﹦鍘搁梺鍛婁緱閸犳岸宕ｉ埀顒勬⒑閸濆嫭婀伴柣鈺婂灦瀹曟椽宕熼姘鳖槰闂佸啿鎼崰姘ｉ崜浣虹＝闁稿本鐟ㄩ崗灞解攽椤旂偓鏆柟铏箖閵堬綁宕橀敐鍌氫壕闁哄啫鐗嗙粈鍐┿亜閺傛寧顫嶇憸鏃堝蓟濞戙垹鐒洪柛鎰典簼閸Ｑ冾渻閵堝骸鈧倝宕ㄩ婊愮闯濠电偞鎸婚懝鎯洪妶澶婂嚑婵炴垯鍨洪埛鎴︽偨椤栵絽鏋ょ紒瀣嚙鑿愰柛銉戝秴濮涢梺閫炲苯澧紒瀣浮閳ワ箓宕堕埡浣感氶梺閫炲苯澧存慨濠冩そ楠炴牠鎮欓幓鎺戭潙闂備礁鎲￠弻銊╂煀閿濆懐鏆?"
        if scenario == "principle":
            anchor += " 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲濞淬儱鐗撳鎻掆槈閵忕姷顢呴梺瑙勫劶婵倝鎮￠悢鍏肩厵闂侇叏绠戦悘鐘电磼閹插顩紒杈ㄥ浮婵℃悂濡堕崶鈺冨幆婵犳鍠栭敃锕傚磿閵堝拋鐒芥い蹇撶墕缁犮儲銇勯弴鐐村櫤鐞氾箓姊婚崒娆戭槮闁硅姤绮撳畷鎶藉Ψ閳轰胶锛涙繝鐢靛Т濞层倝寮伴妷鈺傜厽闁归偊鍓氶幆鍫㈢磼閻欏懐绉柡灞诲姂瀵潙螖閳ь剚绂嶉崜褏纾奸柣鎰靛墮閸斻倝鏌涘顒夊剶妤犵偛鐗撴俊鎼佸Ψ椤旇棄缂撻梻浣虹《閸撴繈銆冮崨顖滀笉鐟滅増甯楅埛鎴︽煕濠靛棗顏い銉︾矒閺岋絽螖娴ｇ懓纰嶅銈庡亜缁绘﹢骞栬ぐ鎺戞嵍妞ゆ挾濯寸槐鍙夌節绾版ɑ顫婇柛銊ф暬椤㈡俺顦撮柛鐘诧工椤撳吋寰勭€Ｑ勫缂傚倷绀侀鍛焊閸涱収鍟呴柕澶涜礋娴滄粍銇勯幘璺盒㈤柛妯侯嚟閳ь剝顫夊ú妯侯渻娴犲鏄ラ柍褜鍓氶妵鍕箳瀹ュ顎栨繛瀛樼矋缁捇寮婚悢鐓庝紶闁告洦鍓﹀Λ鐐寸箾鐎涙鐭婂褏鏅Σ鎰板箻鐎涙ê顎撻梺鍛婄箓鐎氬懘濮€閵忋垻锛滄繝銏ｆ硾閺堫剟宕甸埀顒勬⒑娴兼瑧鎮奸柛蹇斆锝夊箻椤旂⒈娼婇梺缁樕戦鏍绩閵娾晜鈷掑ù锝囩摂閸ゆ瑧绱掔紒妯虹闁告帗甯￠、娑橆潩閸忕厧鐦滈梻浣稿悑娴滀粙宕曢幍顔藉床闁糕剝绋掗悡鏇熴亜閹板墎绋荤紒鈧埀顒€螖閻橀潧浜奸柛銊ㄦ閹广垹鈽夐姀鐘茶€垮┑鈽嗗灡濞叉﹢宕归崷顓炲灊濠电姴娴傞弫鍐煥濠靛棗顏紒鐘冲哺濮婅櫣绱掑Ο鍝勑曟繛瀛樼矋缁捇宕洪埀顒併亜閹哄秷鍏屽褏鏁婚弻鐔碱敊閵娿儱鎮╅柡鍐ㄧ墕瀹告繃銇勯幘璺烘瀾鐞氾綁姊婚崒娆戭槮闁硅绻濆畷婵嬪箣閿曗偓缁€鍫熴亜閺囨浜鹃梺杞扮劍閸旀牕顕ラ崟顒傜瘈闁搞儜鍕瘑闂傚倸鍊风欢姘焽瑜旂瘬闁逞屽墮閳规垿鍨鹃搹顐㈡灎閻庤娲忛崹浠嬪箖娴犲宸濆┑鐐靛亾鐎氬ジ姊洪懡銈呅㈡繛鑼█閸┾偓妞ゆ巻鍋撶痪缁㈠弮閸┾偓妞ゆ巻鍋撴い顓犲厴瀵鈽夊鍡欏弳闂佸憡鍔戦崝宥呪枔閸撲胶纾藉ù锝嗗絻娴滅偓绻濋悽闈浶㈡繛璇х畵閸╂盯骞嬮敂鐣屽幈濠电娀娼уΛ妤咁敂椤愩倖鍋栭柨鏇炲€归埛鎴︽⒑椤愩倕浠滈柤娲诲灡閺呭爼顢涢悙瀵稿幐闁诲函缍嗘禍妤呭磻閵忊懇鍋撳▓鍨灁闁告柨绉剁划瀣箳閺傚搫浜鹃柨婵嗛娴滅偤鏌涘Ο缁樺磳婵﹨娅ｉ埀顒€婀辨慨鐢稿Υ閸愵亞纾奸柍褜鍓氱粭鐔煎焵椤掆偓椤曪綁宕樺ù瀣€婚梺鐟邦嚟婵兘鏁嶅鍫熲拺闁革富鍘剧敮娑㈡偨椤栨娅婇柟顔瑰墲缁轰粙宕ㄦ繝鍕箰闁诲骸鍘滈崑鎾绘煃瑜滈崜鐔风暦閻楀牊鍎熼柕濠忓閻ｆ娊姊绘担绛嬪殭闁告垳绮欓獮鈧柕澶嗘櫅缁€鍐喐瀹ュ＆澶婎潩閼哥鎷绘繛杈剧到閹芥粎绮旈悜妯镐簻闁挎繂绻愰々顒傜磼椤旇偐澧涢柟宄版噽閸栨牠寮撮悢杞扮按濠碉紕鍋戦崐鏍礉瑜斿浠嬪礋椤栨氨鍘遍梺纭呮彧闂勫嫰鎮￠弴鐔虹闁瑰鍎戦崗顒勬煛閳ь剛鎷犲顔惧數闁荤姴鎼幖顐︻敂椤撱垺鐓涢悘鐐插⒔閵嗘帡鏌嶈閸撱劎绱為崱娑樼；闁告洦鍘剧粻鏃堟煙閻戞ɑ灏ù婊勭矋閵囧嫰骞樼捄杞版勃闂佸摜濮甸敃銏ゅ蓟濞戙垹鐓涢悗锝庡墰閻﹀牓鎮楃憴鍕閻㈩垱甯熼悘鎺楁⒑闂堚晛鐦滈柛妯诲劤閳绘棃宕稿Δ浣叉嫽闂佺鏈悷銊╁礂瀹€鍕厵闁惧浚鍋呭畷灞绢殽閻愬澧垫い銏℃礋閸╂鎳為妷褉妲堥柧缁樼墪闇夐柨婵嗗椤掔喐绻涢幓鎺撳暈濞ｅ洤锕俊鎯扮疀閺囩偛鐓傞梻浣告憸閸ｃ儵宕归崼鏇炴槬婵炴垯鍨圭粻锝夋煥閺冨倹娅曢柛妯哄船閳规垿鎮╃紒妯婚敪濠碘槅鍋呴〃濠囥€侀弮鍫晜闁割偆鍠撻崢閬嶆⒑閹稿海绠撻柣妤€妫滈。鍧楁⒒娓氣偓濞佳兠洪妶鍥ｅ亾濮橆偄宓嗛柕鍡曠椤粓鍩€椤掑嫬绠栨繛鍡樻尰椤ュ牊绻涢幋鐐茬瑨鐎垫澘绉撮埞鎴︽偐閸偅姣勬繝娈垮櫘閸欏啫鐣烽幋锕€绠婚柣鎰掗崑鎾诲箳閹搭厽鍍甸梺鎸庣箓閹冲秵绔熼弴鐔虹瘈婵炲牆鐏濋弸娑㈡煥閺囨ê濡奸柍璇茬Ч閺佹劙宕堕…鎴炵稐闂備礁婀遍崕銈夊吹閿曞倹鍋勯柣鎾虫捣椤ρ囨⒑缂佹ɑ灏悗娑掓櫊閹敻鏁愭径瀣ф嫽闂佺鏈悷銊╁礂鐏炰勘浜滈柕蹇曞瀹搞儵鏌嶇拠鑼х€殿喗鎸虫慨鈧柣妯活問濡查攱绻濋悽闈涗粶婵☆偅鐟╅獮鎰板箚瑜忛弳銈呫€掑锝呬壕闂佸搫鏈惄顖炵嵁閸ヮ剙惟闁挎梻鏅ぐ鍥⒒閸屾艾鈧摜鈧凹鍓涢埀顒佺煯閸楀啿顕ｇ拠娴嬫婵☆垶鏀遍～宥呪攽椤旂瓔娈旈柣妤€妫欓幈銊モ槈閵忊檧鎷洪梺鍛婄☉閳洟鎳栭埡浣哥亰濠电偛妫楀ù姘焽閺嶃劎绠剧€瑰壊鍠曠花璇裁归懖鈺佲枅闁哄本鐩鎾Ω閵夈儴绶熼梻浣虹帛椤洨鍒掗鐐村亗闁哄洢鍨洪悡娑㈡煕鐏炲墽顣查柛瀣ㄥ劦閺屾稑鈻庤箛鎿冧純闂佸搫鐬奸崰鏍€佸☉姗嗘僵閺夊牃鏅涙慨杈ㄤ繆閵堝洤啸闁稿鍋熼弫顕€骞掗弴鐘辩胺婵犵數鍋犻幓顏嗗緤娴犲绠规い鎰跺瀹撲線鏌熼柇锕€鍘撮柡鈧禒瀣厽闁归偊鍨伴悡鎰喐閹跺﹤鎳愮壕濂告椤愵偄骞橀柣顓熺懄椤ㄣ儵鎮欓幖顓熺暥濡炪値鍘归崝鎴濈暦濮椻偓椤㈡棃宕ㄩ鍏肩彛闂傚倸鍊搁崐鎼佸磹閹间礁纾圭€瑰嫰鍋婂〒濠氭煙閻戞ɑ鈷愭い顐ｆ礃閵囧嫰寮埀顒勫磿瀹曞洦顐介柕鍫濐槹閻撴洟鏌熼悙顒夋當閻庢凹鍓氶幆鏃€绻濋崶銊㈡嫼闂佸憡鎸昏ぐ鍐╃濠靛牏纾奸悹鍥ㄥ絻椤忣厾鈧鍠楁繛濠囧极閸岀偞鍤嶉柕澶堝劚娴煎孩绻濈喊澶岀？闁稿濞€椤㈡俺顦崇紒鍌氱У閵堬綁宕橀埞鐐闂佸搫顦遍崑鐐寸珶閸℃稑绀夌€广儱顦伴悡鏇㈡煛閸愶絽浜鹃梺鑽ゅ枂閸庣敻骞冩ィ鍐╁€婚柦妯猴級閳哄懏鐓冮柛婵嗗閺€濠氭煛閸涱偄鐏叉慨濠冩そ閺屽懘鎮欓懠璺侯伃婵犫拃鍕唉闁圭锕幃銏ゅ川婵犲倸浼庢繝纰樻閸ㄤ即鎮樺┑瀣亗闁规壆澧楅悡鍐⒑閸噮鍎忛柣蹇旀尦閺岀喖顢欓懖鈺冃ㄩ悗瑙勬礀閻栧ジ銆侀弮鍫濈妞ゆ挾鍣ラ崵鍕磽閸屾艾鈧兘鎳楅懜鍨弿闁割煈鍋嗙粻鎯р攽閻樺弶鎼愰柦鍐枑缁绘盯骞嬮悙鑼姲闂佺顑嗛幑鍥极閹邦厽鍎熼柍銉﹀墯濞煎姊绘担鍛婃儓妞ゆ垵妫涚划娆撳箻鐠囪尙鍔﹀銈嗗笒閸犳艾顭囬幇顓犵闁告瑥顧€閼拌法鈧娲栫紞濠傜暦缁嬭鏃堝礃閵娧佸亰濠电姵顔栭崰妤呭Φ濞戙垹纾婚柟鎯х亪閸嬫挾鎲撮崟顒傤槰缂備緡鍠栫粔褰掔嵁韫囨稑宸濋悗娑櫭禒顓㈡⒑缂佹﹩娈旈柣妤€绻楅妵鎰邦敍閻愮补鎷婚梺绋挎湰閼归箖鍩€椤掍焦鍊愮€规洘鍔欓獮鏍ㄦ媴閸濄儻绱梻浣哥秺濡法绮堟担鍝勵棜鐟滅増甯楅悡鐔兼煙鏉堝墽鍒扮悮姘舵⒑閹肩偛鈧洜鈧矮鍗冲璇测槈閵忊晜鏅濋梺鎸庣箓濡盯鏁嶅鈧娲焻閻愯尪瀚伴柛妯绘倐閺岋綁骞掗悙宸喘闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濈敖闁挎稒绮岄埞鎴炲箠闁稿﹥鎹囬幊妤呮嚋閻㈡娲稿┑鐐叉閸旀寮ч埀顒勬⒑濮瑰洤鐏叉繛浣冲嫮顩烽柨鏇炲€归悡鏇熴亜椤撶喎鐏ラ柣蹇ュ閳ь剝顫夊ú婊堝箠閹捐泛寮叉俊鐐€曠换鎰偓姘煎櫍瀵槒顦查柍瑙勫灴閹晝绱掑Ο濠氭暘婵＄偑鍊栭崹闈浳涘┑瀣畺闂勫洨绮诲☉銏犵闁告劦浜滈弫鎼佹⒑閼姐倕鈻堢紓鍌涜壘閳诲秹鏁愰崱妯荤彿闂佸搫娲㈤崹娲偂閺囥垺鐓涢柛鎰剁到娴滄儳顪冮妶鍐ㄥ闁挎洦浜滈锝嗙節濮橆厽娅㈤梺缁橆焾鐏忔瑩宕濋敃鈧—鍐Χ閸℃鐟ㄩ柣搴㈠嚬閸欏啫顕ｉ幓鎺嗘斀閻庯綆鍋嗛崢閬嶆煟韫囨洖浠滃褌绮欐俊鎾箳濡や胶鍘卞┑鈽嗗灣缁垰鐣峰畝鍕厵妞ゆ梻鍘уΣ缁樸亜椤撴粌濮傜€规洜鍠栭、姗€鎮╅棃娑樿緟闂備浇顕у锕傦綖婢跺⊕鍝勎熼悡搴＄亰闂佽宕橀褏绮婚弽顓熺厪闊洤顑呴埀顒佺墵瀹曟垿宕掗悙鑼啇濠电儑缍嗛崜娆撳焵椤掍胶澧垫鐐差樀閹囧醇閵忋垻妲囬梻浣圭湽閸ㄨ棄顭囪缁傛帡鏁冮崒娑氬幈濡炪値鍘介崹鐢告倶閿旈敮鍋撶憴鍕缂傚秴锕ら悾鐑芥倻缁涘鏅ｉ梺缁橆焾娴滎剟鎮峰┑瀣拻濞达絿鐡斿鎰版煕鎼粹€虫倯闁逛究鍔戞俊鑸靛緞鐎ｎ亙绨垫繝鐢靛仜濡瑩骞愭繝姘９闁割煈鍋嗙粻楣冩煙鐎电浠ч柟铏姍閺岋綁骞掗弮鈧▍鏇犵磼鏉堛劌娴柟顔规櫊椤㈡瑩鎮℃惔鈱掓洟姊绘担鍛婃儓闁活厼顦遍幑銏犫攽閸℃瑦娈鹃梻渚囧墮缁夊绮诲☉娆嶄簻闁圭儤鍨甸埀顒傚厴楠炲啴鏁愭径瀣ф嫽婵炶揪绲介幗婊堝几閸愨斂浜滄い鎰╁焺濡偓閻庤娲栫紞濠傜暦缁嬭鏃堝焵椤掑倻涓嶉柡宥庡幗閻撳啴鏌涘┑鍡楊仾濠殿垰銈搁弻鈩冩媴缁嬫寧娈查梺闈涙搐鐎氫即銆侀弴銏╂晝闁靛繒濮烽鎰繆閻愵亜鈧垿宕曢幓鎺旀殕缂佸顑欏鏍р攽閻樺疇澹樼痪鎯у悑缁绘盯宕卞Ο铏圭懆闂佸憡锕换婵嗩潖閾忓湱鐭欐繛鍡樺劤閸擃參姊洪崨濠冣拹闁搞劎鏁婚幃楣冩倻閽樺宓嗛梺闈涚箳婵箖骞楅弴銏♀拺闂傚牊渚楀Σ鍫曟煕鎼淬垹鈻曢挊婵囥亜閹捐泛浜归柡鈧懞銉ｄ簻闁哄啠鍋撻柡瀣帛缁楃喎鈽夐姀锛勫幈闂佺懓鐏濈€氼噣鎮鹃悽鍛婄厵妞ゆ梹鍎虫禒閬嶆煙缁嬪尅鏀荤紒鏃傚枎閳规垿宕卞▎鎳躲劑姊虹拠鈥虫灀闁告挻绻堥獮鍡涘籍閸喐娅滈梺绯曞墲閿氶柡瀣洴濮婂宕掑▎鎺戝帯缂備緡鍣崹鍫曠嵁閹版澘閱囬柡鍥╁仧閿涚喖姊洪懖鈹炬嫛闁告挻鑹鹃悾鐑藉矗婢跺瞼鐦堥梻鍌氱墛娓氭宕曢幇顓滀簻闁靛鍎虫晶娑氱磼缂佹娲存鐐差儔閹瑩宕归銏☆仱濠电姷顣藉Σ鍛村磻娓氣偓瀹曟劙寮介锝呭簥濠电娀娼ч鍛存偂閺囥垺鐓冪憸婊堝礈閻旈鏆﹂柛顐ｆ礃閺呮粓鏌﹀Ο渚Ч闁诲繑鎹囧濠氬磼濞嗘埈妲梺鍦拡閸嬪﹤顕ｉ悽鍓叉晢闁告洦鍓欓崜顔碱渻閵堝棛澧遍柛瀣〒缁寮介妸褏顔曢梺绯曞墲钃遍悘蹇庡嵆閺屾盯濡堕崱妤冧桓闂侀潧娲ょ€氫即鐛幒妤€绠ｆ繝闈涘暙娴滈箖鏌熼悧鍫熺凡閹喖姊洪棃娑辨Ф闁搞劍妞藉顒勫焵椤掍椒绻嗛柣鎰典簻閳ь剚鐗曢～蹇旂節濮橆儵銉╂倵閿濆骸鏋涚紓浣叉櫇缁辨挻鎷呮慨鎴ｅ亹閹广垽宕卞☉娆戝幗闂佸綊鍋婇崢濂杆夌€ｎ喗鐓熸い鎾跺枔閹冲洭鏌＄仦鐐鐎规洟浜跺鎾偐閻㈤潧搴婇梺璇插椤旀牠宕板Δ鍛闁惧浚鍋呴崣蹇涙煃瑜滈崜鐔煎蓟閿濆應鏋庨悘鐐村灊婢规洘绻濋悽闈涗户闁告鍥ㄦ櫇妞ゅ繐瀚峰鏍ㄧ箾瀹割喕绨兼い銉ョ墛缁绘盯骞嬮悙瀵告闂佹眹鍊曠€氭澘顫忓ú顏勭闁绘劖褰冮‖鍫濐渻閵堝骸骞栭柛銏＄叀椤㈡岸鏁愭径瀣疂闂佹眹鍨洪鏍归崟顖涚厽閹兼惌鍨崇粔鐢告煕鐎Ｑ冧壕闂?"
        elif scenario == "concept_teaching":
            anchor += " 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲濞淬儱鐗撳鎻掆槈閵忕姷顢呴梺瑙勫劶婵倝鎮￠悢鍏肩厵闂侇叏绠戦悘鐘电磼閹插顩紒杈ㄥ浮婵℃悂濡堕崶鈺冨幆婵犳鍠栭敃锕傚磿閵堝拋鐒芥い蹇撶墕缁犮儲銇勯弴鐐村櫤鐞氾箓姊婚崒娆戭槮闁硅姤绮撳畷鎶藉Ψ閳轰胶锛涙繝鐢靛Т濞层倝寮伴妷鈺傜厽闁归偊鍓氶幆鍫㈢磼閻欏懐绉柡灞诲姂瀵潙螖閳ь剚绂嶉崜褏纾奸柣鎰靛墮閸斻倝鏌涘顒夊剶妤犵偛鐗撴俊鎼佸Ψ椤旇棄缂撻梻浣虹《閸撴繈銆冮崨顖滀笉鐟滅増甯楅埛鎴︽煕濠靛棗顏い銉︾矒閺岋絽螖娴ｇ懓纰嶅銈庡亜缁绘﹢骞栬ぐ鎺戞嵍妞ゆ挾濯寸槐鍙夌節绾版ɑ顫婇柛銊ф暬椤㈡俺顦撮柛鐘诧工椤撳吋寰勭€Ｑ勫缂傚倷绀侀鍛焊閸涱収鍟呴柕澶涜礋娴滄粍銇勯幘璺盒㈤柛妯侯嚟閳ь剝顫夊ú妯侯渻娴犲鏄ラ柍褜鍓氶妵鍕箳瀹ュ顎栨繛瀛樼矋缁捇寮婚悢鐓庝紶闁告洦鍓﹀Λ鐐寸箾鐎涙鐭婂褏鏅Σ鎰板箻鐎涙ê顎撻梺鍛婄箓鐎氬懘濮€閵忋垻锛滄繝銏ｆ硾閺堫剟宕甸埀顒勬⒑娴兼瑧鎮奸柛蹇斆锝夊箻椤旂⒈娼婇梺缁樕戦鏍绩閵娾晜鈷掑ù锝囩摂閸ゆ瑧绱掔紒妯虹闁告帗甯￠、娑橆潩閸忕厧鐦滈梻浣稿悑娴滀粙宕曢幍顔藉床闁糕剝绋掗悡鏇熴亜閹板墎绋荤紒鈧埀顒€螖閻橀潧浜奸柛銊ㄦ閹广垹鈽夐姀鐘茶€垮┑鈽嗗灡濞叉﹢宕归崷顓炲灊濠电姴娴傞弫鍐煥濠靛棗顏紒鐘冲哺濮婅櫣绱掑Ο鍝勑曟繛瀛樼矋缁捇宕洪埀顒併亜閹哄秷鍏屽褏鏁婚弻鐔碱敊閵娿儱鏋ら柣鎾卞劦閺屾盯顢曢敐鍥╃暭闂佹寧绋掗惄顖氼潖閾忓湱纾兼俊顖氭惈椤酣姊虹粙璺ㄦ槀闁稿﹥绻傞悾鐑藉箣閿曗偓绾惧吋绻涢幋鐐寸殤妞ゆ梹娲熷娲偡閹殿喗鎲奸梺鑽ゅ枂閸庣敻骞冨鈧、鏃堝醇閻斿搫骞楅梻浣筋潐閸庢娊鎮洪妸褏鐭嗛悗锝庡枟閻撴稓鈧厜鍋撻悗锝庡墰閻﹀牓鎮楃憴鍕闁绘牕鍚嬫穱濠囨倻閽樺）銊ф喐瀹€鍕剦妞ゅ繐鎳愮弧鈧梺姹囧灲濞佳勭閿曞倹鐓曢柕鍫濈凹闁垳鈧娲栭悥鍏间繆濮濆矈妲诲Δ鐘靛仦椤ㄥ﹤顫忕紒妯肩瘈閹肩补鈧尙鐩庢繝鐢靛仜閻即宕愬☉娆愭珷婵犻潧顑嗛埛鎴犵磼鐎ｎ偒鍎ラ柛搴㈠姍閺岀喖鎮烽悧鍫熸倷濡炪倖娲╃紞渚€銆佸Δ鍛妞ゆ劕顑冮崝鎴﹀蓟閵娾晛绫嶉柛銉仢閹惧绡€闁靛繆鈧磭浼屽┑顔硷工椤嘲鐣烽幒鎴旀瀻闁瑰瓨绻傞‖澶愭⒑鐠囧弶鎹ｉ柣鐔稿▕瀹曘劑顢涘鍛箚闂傚倷鑳堕幊鎾活敋椤撶喐鍙忔い鎾卞灩绾惧鏌熼悙顒€澧繛灏栨櫊閺屾稑螖閸愩劋绮跺Δ鐘靛仜椤戝顫忛搹瑙勫珰闁炽儴娅曢悘鎾绘⒑缁嬫鍎嶉柛濠冪箞閻涱噣宕橀妸銏＄€婚梺鐟扮仢閸燁垶寮查悙鐑樷拺闁告稑锕﹂幊鈧梺绋垮婵炲﹪骞嗛崟顒佸劅妞ゎ偒鍘剧粻姘舵⒑缂佹ê濮﹀ù婊勭矒閸┾偓妞ゆ帊鑳舵晶鐢碘偓瑙勬礃缁诲棝藝鐎靛摜纾奸弶鍫氭櫅娴犺京鈧娲栧畷顒勨€旈崘顏嗙＜婵☆垶妫跨花鏉戔攽閻樺灚鏆╁┑顔芥尦閺佸啴濡舵径濠勭枃婵犮垼鍩栭崝鏇犲婵犳碍鐓欓柟瑙勫姇閻撴劙鏌涢悩鍙夘棦闁哄本鐩鎾Ω閵夈儺娼炬俊鐐€х拹鐔煎礉閹达箑钃熼柨婵嗩槸椤懘鏌嶆潪鎷屽厡濞寸媭鍙冮弻锝夊閳轰胶浼堢紓浣虹帛缁诲牆顕ｉ锕€绠涢柣妤€鐗嗛埀顒勬敱缁绘盯寮堕幋顓炲壉闂佸搫鍊甸崑鎾绘⒒娴ｇ瓔鍤欓柛鎴犳櫕瀵板﹥绂掔€ｎ偄鈧埖鎱ㄥΟ鎸庣【闁汇倝绠栭弻鏇＄疀閵壯咃紵缂備胶濞€缁犳牕顕ｉ崼鏇為唶婵犻潧妫岄幐鍐⒑鐠団€虫灕闁稿鍔欓幆鈧い蹇撶墱閺佸洭鏌ｉ幇鐗堟锭闁绘挾鍠栭幃妤冩喆閸曨剛顦ㄩ梺鎼炲妼濞硷繝鎮伴鍢夌喖鎳栭埡鍐跨床婵犵妲呴崹宕囧垝椤栫偞鍋熼柛鎰ゴ閺€浠嬫煟濮楀棗鏋涢柣蹇氶哺缁绘稒寰勭€ｎ剚鍒涘銈冨灪閻楃姴鐣烽幒妤佸€烽柤纰卞墻閸炵數绱撻崒姘偓鐑芥倿閿曞倵鈧箓宕堕埡鍐х瑝婵°倧绲介崯顐ょ棯瑜旈弻娑㈩敃閿濆洨鐣甸梺鎶芥敱濮婅崵妲愰幒鎾崇窞婵☆垰鎼～鈺呮⒑鐎圭媭娼愰柛銊ユ健閵嗕礁鈻庨幘鍏呯炊闂佸憡娲忛崝灞剧閻愵剛绡€闂傚牊鍐婚弨濠氭煥濞戞ê鈧悂鍩為幋锔藉亹妞ゆ棁鍋愭导鍥р攽閻愬樊妲归柣鈺婂灦閵嗕線寮介鐐殿槰闂佸啿鎼崰姘虹粙搴撴斀闁绘顕滃銉╂煟濡も偓閿曨亪骞冮敓鐘参ㄩ柍鍝勫€婚崢鎼佹⒑閸涘﹤濮傞柛鏂跨Ф缁﹪鍩￠崨顔惧幈闂侀潧鐗嗗Λ娑㈠箠閸ヮ剚鐓涚€光偓鐎ｎ剛袣缂備胶濮甸惄顖氼嚕閹绢喗鍊烽柍鍝勫€婚埀顑垮嵆濮婄粯鎷呴崨濠冨創闁荤偞鍑归崑濠傜暦濠靛绠ｆ繝鍨姇濞堛劑姊洪崫鍕垫Ч闁搞倧绠撻幃銏ゅ礂閸忕厧鍔掗梻鍌欑贰閸嬪懐绮欓幘鍓佺焼闁告洦鍋€閺€浠嬫煥濞戞ê顏╁ù婊冦偢閺屾稒绻濋崘銊т紝閻庤娲栫紞濠傜暦椤愶箑绀嬮幖娣灮濞插鈧娲橀敃銏′繆濮濆矈妲煎┑鐐茬墦缁犳牕顫忓ú顏勭闁圭粯甯婄花鐓庘攽閻愭彃绾ч柣妤佹礋瀵偊顢氶埀顒€顫忕紒妯肩懝闁逞屽墮椤洩顦归柟顔ㄥ洤骞㈡俊鐐灪缁嬫垿鍩ユ径濠庢建闁糕剝鐟ユ慨娲⒒娴ｅ憡鎯堢紒瀣╃窔瀹曘垺绂掔€ｎ亞鍘遍梺鍦劋椤ㄥ棝鎮￠弴銏″€堕柣鎰絻閳锋棃鏌熼崘鎻掝伀缂佽鲸甯楅幏鍛村传閸曞灚姣夐梻渚€娼уú銈団偓姘嵆閵嗕線寮撮姀鐙€娼婇梺鍐叉惈閸婄敻寮搁崨瀛樼厽閹兼番鍊ゅ鎰箾閸欏顏嗗弲闂佺粯妫侀崑鎰暤娓氣偓楠炴牕菐椤掆偓婵′粙鎮楅悽闈浶㈡い顓℃硶閹瑰嫰鎮滃Ο缁樺闂備胶绮敮锛勭不閺嵮屾綎缂備焦蓱婵潙銆掑鐓庣仭缂傚秴锕娲川婵犲啰顦ラ梺璇茬箲瀹€鎼佸春閵忕姷鏆嗛柛鏇ㄥ厴閹疯櫣绱撻崒娆戝妽闁挎岸鏌ｈ箛姘跺摵濞ｅ洤锕、鏇㈠閻欌偓娴犵厧顪冮妶鍡樼叆缂佺粯鍔欓崺鐐哄箣閿曗偓閻愬﹪鏌曟径鍫濃偓妤呮儎鎼淬劍鈷掑ù锝呮啞鐠愶繝鏌涙惔娑樷偓婵嗩嚕婵犳艾惟鐟滃酣寮冲鍫熺厱闁规崘灏崗宀€鐥崜褎娅曢柍褜鍓欑粻宥夊磿闁秴绠柟杈惧閸欐洘銇勯幒宥囪窗婵炲牅绮欓弻锝夊箛椤撶偟绁烽梺鍝勬４缁查箖濡甸崟顖氼潊闁斥晛鍠氬Λ鍐倵鐟欏嫭绀堥柛妯犲洤鐓橀柟杈剧畱楠炪垺绻涢崱妯虹仴闁哄嫨鍎茬换婵堝枈婢跺瞼锛熼梺绋款儐閸ㄥ灝鐣烽幇鏉垮唨妞ゆ挾鍠庢禍鍗炩攽鎺抽崐鏇㈠疮娴煎瓨鍎楁繛鍡樻尰閻撴瑩鎮楅悽娈跨劸濞寸姍鍕╀簻闁冲搫鎷嬪Λ鎴︽煙閸欏鍊愰柟顔ㄥ洤閱囨繝闈涚墢閹虫牠姊绘担鐟扳枙闁衡偓鏉堚晜鏆滈柟鐑橆殕缁犳帡姊绘担鐟邦嚋缂佽鍊块幃褎绻濋崶鑸垫櫆闂佺粯顭囩划顖炲磻閵婏负浜滈柡宥冨妿閵嗘帗绻涢崣澶嬪唉闁哄备鈧磭鏆嗛悗锝庡墮閸╁矂鏌х紒妯煎ⅹ闁靛棙甯掗～婵嬵敆娴ｅ壊妲遍梻浣风串缁蹭粙濡剁粙娆炬綎婵炲樊浜滃婵嗏攽閻樻彃鈧鎮烽弻銉︾厽闁靛繆鏅涢悘鑼磼缂佹绠為柟顔诲嵆椤㈡瑩宕叉径灞芥灈闁圭厧婀遍幉鎾礋椤掑鏅梻鍌氬€烽悞锕傚箖閸洖纾挎い鏍仜缁€澶屸偓骞垮劚椤︿粙寮繝鍥ㄧ厸闁搞儮鏅涢弸宥囩磼鐠囧弶顥㈤柡宀嬬秮楠炲洭宕楅崫銉ф晨闂備線鈧偛鑻晶顖涚箾閸欏鐭掓鐐村灴婵偓闁靛牆鎳愰悿鈧俊鐐€栧濠氬箠閹惧顩查柣鎰靛墯閸欏繑淇婇婊冨付閻㈩垵鍩栫换娑㈠川椤撶姌銈夋煃瑜滈崜姘额敊閺嶎厼绐楁俊銈勮兌缁犳儳鈹戦悩鎻掆偓濠氬汲閿曞倹鐓曟俊銈呭暙娴滆淇婇幓鎺斿缂佺粯鐩畷鍗炍熼搹閫涙樊婵°倗濮烽崑娑㈡偋閹炬剚娼栫紓浣股戞刊鎾煕濞戞﹫鏀婚柛搴㈡尭閳规垿鎮欓懠顒佸嬀闂佹悶鍔忓Λ鍕偩瀹勬壋鏀介柛顐ｇ矋閸曞啴姊虹紒妯哄Е闁告挻宀搁幃闈涚暋闁附瀵岄梺闈涚墕濡稒鏅堕鍌滅＜閻庯綆鍋呯亸鐢电磼椤斿墽甯涢柕鍫秮瀹曟﹢鍩￠崘銊ョ疄濠电姷鏁搁崑鐐哄垂闂堟稓鏆︽い鎺戝閸戠娀鏌ｉ弮鍥モ偓鈧柛瀣尵閹叉挳宕熼鍌ゆК闂備焦妞块崢濂稿磹閸噮鍤曞┑鐘宠壘閻忓磭鈧娲栧ú锕€鈻撻弴銏＄厽閹兼惌鍨崇粔鐢告煕閹惧顬奸柍顏嗘暬濮婂宕掑▎鎰偘濡炪倖娲橀悧鐘茬暦娴兼潙绠虫俊銈傚亾闁汇倝绠栭弻锝呂熼崹顔炬闂佸搫妫寸粻鎾诲蓟閵娿儮鏀介柛鈩冿供濡偟绱撴担绋款暢闁稿鍊濋獮鍐潨閳ь剟骞冨▎鎰剁矗婵犻潧妫欓鍕攽閻愯尙鎽犵紒顔肩灱缁辩偞绻濋崒銈嗙稁婵犵數濮甸懝鍓у閸忚偐绠鹃柛鈩兠悘銉モ攽閳ヨ尙鐭欐慨濠呮閹风娀鍨鹃搹顐や邯闂備胶绮悧婊堝储瑜旈幃鎯х暋閹佃櫕鏂€婵犵數濮寸€氼噣寮堕幖浣光拺闁告繂瀚婵嬫煕鐎ｎ偆娲撮柟顔缴戠换婵嬪礃瑜忕粻姘舵⒑闂堟稓澧曠紒缁樺浮瀹曟碍瀵肩€涙鍘遍梺缁樻磻缁€浣圭娴煎瓨鐓欐い鏂垮悑閸嬨儲銇勯姀锛勬噭闁逛究鍔戦獮鍥敂閸℃瑦鏅ㄩ梻鍌氬€风粈渚€骞栭銈囩煓濞撴埃鍋撶€规洘鍨垮畷鐔碱敆閸屻倖绁梻浣瑰濞叉牠宕愯ぐ鎺撳亗闁哄洨鍋愰弨浠嬫煟濡绲婚柍褜鍓涚划顖滅矉閹烘垟妲堟慨妯夸含閿涙粎绱撻崒娆戝妽妞ゎ厼娲ょ叅閻庣數纭堕崑鎾舵喆閸曨剛顦梺鍛婎焼閸パ呭幋闂佺鎻粻鎴︽煁閸ャ劎绡€濠电姴鍊归ˉ鐐淬亜鎼淬埄娈滄慨濠傤煼瀹曟帒鈻庨幋顓熜滈梻浣告贡閳峰牓宕戞繝鍥モ偓渚€寮介鐐茶€垮┑鐐叉閸ㄥ綊鎮￠幘缁樷拺閻熸瑥瀚粈鍐煕閳哄倻澧甸柨婵堝仱瀵挳濮€閿涘嫬骞嶉梻浣虹帛閸ㄦ儼鎽梺鎶芥敱閸旀瑩骞冨Δ鈧～婵嬵敇閻旂儤顓婚梻渚€鈧偛鑻晶浼存煙閾忣偅灏扮紒鏃傚枑缁绘繈宕惰閻涖儵姊洪崫鍕枆闁告鍋愮划鍫ュ醇閳垛晛浜鹃悷娆忓缁€鈧┑鐐茬湴閸斿孩绔熼弴銏″癄濠㈣泛鐗冮崑鎾诲箳閹搭厽鍍靛銈嗗笂閻掞箓骞冨▎蹇婃斀闁绘劕寮堕崳娲煥閺囨ê鐏茬€殿喛顕ч埥澶娢熼柨瀣偓濠氭椤愩垺澶勯柟姝岊嚙閳绘捇顢橀姀鈾€鎷烘繛鏉戝悑閻熝囧箖婵傚憡鐓曢煫鍥ㄦ閼板潡鏌ｅ☉鍗炴珝妤犵偞甯￠獮濠囨惞椤愶絺鎷归梺鐟板槻閹虫劙宕犻弽顓炲嵆闁绘劖婢橀ˉ姘舵⒒娴ｈ櫣甯涢柛銊ュ悑閹便劑濡舵径濠勶紮闂佸壊鐓堥崑鍡欑不妤ｅ啯鐓欓悗鐢殿焾閸撳崬霉閻撳孩顥㈤柡宀€鍠愬蹇斻偅閸愨晩鈧秹姊虹粙娆惧剳闁哥姵鍔欐俊鐢稿礋椤栨氨鐤€闂佸壊鍋呭ú姗€顢撳澶嬧拺缂備焦蓱鐏忕敻鏌涢悩宕囧⒌闁绘侗鍣ｅ浠嬵敃閵忕姷浜伴梻浣侯焾缁绘劙藝椤栨稓顩插Δ锝呭暞閻撴洟鏌熼柇锕€鐏犻柦鍕亹缁辨帡宕滄担鍛婄亪濠殿喖锕︾划顖炲箯閸涱喚鐟规い鏍ㄧ矊婵吋淇婇悙顏勨偓鏍垂闂堟党娑樷攽鐎ｎ剙绁﹂梺纭呮彧缁犳垿鎮欐繝鍐︿簻闁瑰搫妫楁禍楣冩⒑閽樺鏆熼柛鐘冲姉閹广垹鈽夐姀鐘殿吅濠电偛妫楃换鎺撶閼测晝纾藉ù锝呮惈鏍￠梺鐑╂櫓閸ㄨ泛顕ｇ拠娴嬫闁靛繒濮烽鎺楁⒑閼测斁鎷￠柛鎿勭畱鍗辨い鏇楀亾婵﹨娅ｉ崠鏍即閻斿摜褰呴梻浣告惈閻楁粓宕滃☉銏犵闁靛繒濮Σ鍫熸叏濮楀牏鍒板ù婊呭亾缁绘盯骞嬮悙鍨櫧闂佺粯甯婄划娆撳蓟閿濆鏁囬柣鏃堫棑椤戝倻绱撴担浠嬪摵閻㈩垽绻濋獮鍐煛娴ｇ儤娈鹃梺鎼炲劀閳ь剟骞忛悧鍫滅箚闁靛牆娲ゅ暩闂佺顑嗛惄顖氱暦椤栫儐鏁冮柨鏃囧亹缁嬪繐鈹戦悩璇у伐闁绘妫濋幃鐐哄垂椤愮姳绨婚梺鍦劋閸ㄧ敻顢旈埡鍐＜闁绘ê纾晶顒傜磼缂佹娲寸€规洖宕灒闁惧繘鈧稒顢橀梺璇叉唉椤煤閺嶎厔鍥濞戝崬娈ㄩ梺鍓插亝濞叉﹢宕愰悜鑺モ拻闁割偆鍠嶇欢閬嶆煛閸♀晛寮慨濠傛惈鐓ら悹鍥紦缁ㄨ崵绱撴担铏瑰笡闁挎碍銇勯銏㈢缂佽鲸甯掕灒閻犲洤妯婇埀顒佹崌濮婃椽鎳為妷鍐句邯钘濇い鏍仜缁犳岸鏌ｉ幇顔煎妺闁抽攱鍨块弻娑樷攽閸曨偄濮庨柡宥忕節濮婃椽宕ㄦ繝鍐ｆ嫻濡炪們鍔岄敃顏堟偘椤曗偓楠炲鏁冮埀顒勶綖閸涘瓨鐓忛柛顐ｇ箖閸ゅ洭鏌涢悙鑼煟婵﹥妞藉Λ鍐ㄢ槈鏉堛剱銈夋⒑缁嬪灝顒㈤柟鍛婂▕閻涱喖螖閸涱厼宓嗛梺闈涚箚濡狙囧箯濞差亝鐓熼柣妯哄帠閼割亪鏌涢弬璺ㄧ劯鐎殿喗鎮傚顒佹償閹惧瓨鏉告俊鐐€栧濠氬煕閸儱鍚归柣鏃囨绾惧吋銇勯弮鍥т汗濠⒀佸灲閺屽秷顧侀柛鎾卞妿缁辩偤宕卞☉妯肩崶濠德板€曢幊搴ㄦ偂閺囥垺鐓欓柣鎴烇供濞堟洟鏌ｉ幘瀛樼闁靛洤瀚伴獮鍥煛娴ｆ彃浜鹃柡鍥ュ灩閸戠娀鏌￠崘銊у闁绘挸绻橀弻娑㈠焺閸忕媭浜炵划顓㈠箳濡や緡姊挎繝銏ｅ煐閸旀牠鎮￠悢鍝ョ闁糕剝顨夌€氭澘霉濠婂牏鐣烘慨濠冩そ楠炴牠鎮欓幓鎺濇綂婵犵數鍋涢ˇ浼存儎椤栫偞鏅查柣鎰閻も偓濠电偞鍨堕悷锕傚磿椤忓牊鈷戠紒瀣硶缁犵増銇勯敂璇茬仭缂佸倸绉甸妶锝夊礃閳哄啫骞堥梻浣瑰濡線顢氳閻涱噣寮介妸锝勭盎闁硅偐琛ラ崜婵嗭耿閹殿喚纾肩紓浣诡焽濞插鈧娲橀〃濠囧箖閳╁啯鍎熼柍钘夋缂嶆帡姊婚崒娆戭槮闁圭⒈鍋婇幆灞惧緞鐏炵晫绛忛梺绋匡功閸犳挻绂嶅▎蹇婃斀闁绘劘鍩栬ぐ褏绱撳浣镐壕婵犵數鍋涢幏鎴犵礊娓氣偓楠炲啴鍩勯崘銊х獮婵犵數鍋戦崹鍝勎涢崘顔肩畺闁冲搫鎳忛ˉ鍫熺箾閹寸儐娈橀柟瑙勬礈缁辨捇宕掑▎鎺戝帯缂備緡鍣崹鎶藉极椤曗偓閺佹捇鎮╅崣澶嬓氶梻渚€鈧偛鑻晶顖炴煏閸パ冾伃妤犵偞甯￠獮瀣敍濮橆剦娼紓鍌氬€风粈渚€藝闁秴鏋佸┑鐘宠壘閽冪喐绻涢幋娆忕仾闁稿鍔楅埀顒冾潐濞叉牕煤閵堝鐓曢柛顐犲灮绾捐棄銆掑顒佹悙闁哄绋掗妵鍕敇閻樻彃骞嬪Δ鐘靛仜閸燁垳绮嬮幒鏂哄亾閿濆簼绨荤紒鎰⊕缁绘繈鎮介棃娴躲垽鎮楀鐓庡⒋闁绘侗鍠栭鍏煎緞鐎Ｑ勫濠电偠鎻紞鈧繛鍜冪悼閺侇喖鈽夐姀锛勫幈闂侀潧顭粻鎴﹀礉閸洘鐓欑紒娑橆儏娴滅増鎱ㄦ繝鍐┿仢妤犵偛閰ｉ幊鐐哄Ψ閿旇姤顔忛梻鍌欑閹测€愁潖瑜版帗鍋嬮柣妯垮吹瀹撲線鏌涢鐘插姎閹喖姊洪崘鍙夋儓闁稿﹦鎳撻埢宥咁煥閸啿鎷洪梺鍛婄☉閿曪絿娆㈤柆宥嗙厱婵炲棗绻橀崣鍕偓瑙勬礃缁诲啫顕ラ崟顐ゆ殕闁逞屽墰婢规洟鎸婃竟婵嗙秺閺佹劙宕奸悤浣峰摋闂佹眹鍩勯崹閬嶆儎椤栫偛钃熼柨婵嗩槸閻撴稑鈹戦悩鎻掆偓缁樼閹间焦鈷戠紓浣姑肩欢閬嶆煕閻樺啿鍝洪柛鈹惧亾濡炪倖甯掗敃锔剧矓閻㈠憡鐓曢柣妯诲墯濞堟粎鈧娲橀崝娆撳箖濠婂牊鍤嶉柕澶堝劗閸嬫捇鎮介崨濠勫幗闂侀潧绻嗗Σ鍛村疮韫囨稒鐓熼柟鐑樺灥閳锋棃鏌嶈閸撴岸顢欓弽顓炵獥婵炴垶菤閺嬪秹鏌￠崶鈺佹灁闁崇懓绉撮埞鎴︽偐閸欏顦╅梺绋匡躬閺€閬嶅Φ閸曨喚鐤€闁圭偓鍓氭禒閬嶆⒑缁嬫鍎愰柟閫涚窔钘濋柟缁㈠枟閻撳啰鎲稿鍫濈闁绘柨顨庨悞鐣屾喐閺冨牆绠氱€光偓閸曨偆锛滃┑顔筋焾妞寸鈻撴ィ鍐┾拺闁圭娴风粻鎾淬亜閿旇鐏ｇ紒顔肩墦瀹曟﹢鍩炴径鍝ョ泿闂備礁鎼崐鎼佹倶濠靛绠栭柟瀵稿仒缁诲棛鈧懓澹婇崰鏍ㄦ櫠鐎涙ɑ鍙?"
        elif scenario == "engineering_challenge":
            anchor += " 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲濞淬儱鐗撳鎻掆槈閵忕姷顢呴梺瑙勫劶婵倝鎮￠悢鍏肩厵闂侇叏绠戦悘鐘电磼閹插顩紒杈ㄥ浮婵℃悂濡堕崶鈺冨幆婵犳鍠栭敃锕傚磿閵堝拋鐒芥い蹇撶墕缁犮儲銇勯弴鐐村櫤鐞氾箓姊婚崒娆戭槮闁硅姤绮撳畷鎶藉Ψ閳轰胶锛涙繝鐢靛Т濞层倝寮伴妷鈺傜厽闁归偊鍓氶幆鍫㈢磼閻欏懐绉柡灞诲姂瀵潙螖閳ь剚绂嶉崜褏纾奸柣鎰靛墮閸斻倝鏌涘顒夊剶妤犵偛鐗撴俊鎼佸Ψ椤旇棄缂撻梻浣虹《閸撴繈銆冮崨顖滀笉鐟滅増甯楅埛鎴︽煕濠靛棗顏い銉︾矒閺岋絽螖娴ｇ懓纰嶅銈庡亜缁绘﹢骞栬ぐ鎺戞嵍妞ゆ挾濯寸槐鍙夌節绾版ɑ顫婇柛銊ф暬椤㈡俺顦撮柛鐘诧工椤撳吋寰勭€Ｑ勫缂傚倷绀侀鍛焊閸涱収鍟呴柕澶涜礋娴滄粍銇勯幘璺盒㈤柛妯侯嚟閳ь剝顫夊ú妯侯渻娴犲鏄ラ柍褜鍓氶妵鍕箳瀹ュ顎栨繛瀛樼矋缁捇寮婚悢鐓庝紶闁告洦鍓﹀Λ鐐寸箾鐎涙鐭婂褏鏅Σ鎰板箻鐎涙ê顎撻梺鍛婄箓鐎氬懘濮€閵忋垻锛滄繝銏ｆ硾閺堫剟宕甸埀顒勬⒑娴兼瑧鎮奸柛蹇斆锝夊箻椤旂⒈娼婇梺缁樕戦鏍绩閵娾晜鈷掑ù锝囩摂閸ゆ瑧绱掔紒妯虹闁告帗甯￠、娑橆潩閸忕厧鐦滈梻浣稿悑娴滀粙宕曢幍顔藉床闁糕剝绋掗悡鏇熴亜閹板墎绋荤紒鈧埀顒€螖閻橀潧浜奸柛銊ㄦ閹广垹鈽夐姀鐘茶€垮┑鈽嗗灡濞叉﹢宕归崷顓炲灊濠电姴娴傞弫鍐煥濠靛棗顏紒鐘冲哺濮婅櫣绱掑Ο鍝勑曟繛瀛樼矋缁捇宕洪埀顒併亜閹哄秷鍏屽褏鏁婚弻鐔碱敊閵娿儱鏋ら柣鎾卞劦閺屾盯顢曢敐鍥╃暭闂佹寧绋掗惄顖氼潖閾忓湱纾兼俊顖氭惈椤酣姊虹粙璺ㄦ槀闁稿﹥绻傞悾鐑藉箣閿曗偓绾惧吋绻涢幋鐐寸殤妞ゆ梹娲熷娲偡閹殿喗鎲奸梺鑽ゅ枂閸庣敻骞冨鈧、鏃堝醇閻斿搫骞楅梻浣筋潐閸庢娊鎮洪妸褏鐭嗛悗锝庡枟閻撴稓鈧厜鍋撻悗锝庡墰閻﹀牓鎮楃憴鍕闁绘牕鍚嬫穱濠囨倻閽樺）銊ф喐瀹€鍕剦妞ゅ繐鎳愮弧鈧梺姹囧灲濞佳勭閿曞倹鐓曢柕鍫濈凹闁垳鈧娲栭悥鍏间繆濮濆矈妲诲Δ鐘靛仦椤ㄥ﹤顫忕紒妯肩瘈閹肩补鈧尙鐩庢繝鐢靛仜閻即宕愬☉娆愭珷婵犻潧顑嗛埛鎴犵磼鐎ｎ偒鍎ラ柛搴㈠姍閺岀喖鎮烽悧鍫熸倷濡炪倖娲╃紞渚€銆佸Δ鍛妞ゆ劕顑冮崝鎴﹀蓟閵娾晛绫嶉柛銉仢閹惧绡€闁靛繆鈧磭浼屽┑顔硷工椤嘲鐣烽幒鎴旀瀻闁圭儤鍨电敮顖炴⒒娴ｄ警鐒炬い鎴濆暣瀹曟繈骞嬪┑鍫熸闂佸搫娲㈤崹鍦棯瑜旈弻鐔衡偓娑櫳戦埛鎰版煟鎼淬垺銇濇慨濠冩そ瀹曨偊宕熼鈧崑宥夋⒑閹肩偛濡兼繝鈧潏鈺佸灊濠电姵纰嶉崑鍕煕韫囨艾浜归柛妯兼暬濮婂宕掑顑藉亾閹间緡鏁嬫い鎾卞灩缁€澶屸偓骞垮劚椤︿即鎮￠悢鍏肩厵闁诡垎灞芥闂佺懓鍟块幊姗€寮诲鍫闂佸憡鎸婚惄顖炵嵁婵犲洤绠婚柛銊︾☉娴滅偓鎱ㄥ鍡椾簻鐎规挸妫涢埀顒冾潐濞叉﹢宕归崜浣瑰床婵犻潧顑呴悙濠勬喐韫囨稒鏅柣鏂垮悑閳锋垿鏌涘┑鍡楊仼闁哄棗锕弻娑氣偓锝庡亝瀹曞矂鏌＄仦鐐鐎规洘鍎奸ˇ鍙夈亜韫囷絽骞栭柍瑙勫灴椤㈡瑩鎮锋０浣割棜闂傚倸鍊风粈渚€鎮块崶顬盯宕熼姘辩枃闂佽宕橀褔鎮為崹顐犱簻闁瑰搫妫楁禍鎯р攽閻愮偣鈧鎹㈠┑鍡╁殨濠电姵纰嶉崑鍕棯閹峰矂鍝洪柡鍛櫊閺岋綁鎮㈤崫銉﹀櫑闁诲孩鍑归崣鍐箖闂堟侗娼╅柤鍝ヮ暯閹锋椽鏌ｉ悩鍙夌闁逞屽墲濞呮洟鎮橀崱娆戠＝濞撴艾娲ら弸鐔兼煟閻斿弶娅婇柣娑卞櫍瀹曟﹢鍩￠崘鐐カ闂佽鍑界紞鍡涘磻閹烘嚦娑㈠礃閵娿垺鏂€闂佺粯鍔栧娆撴倶閿斿浜滄い鎾跺仦閸犳﹢鏌熼鎯у幋濠殿喒鍋撻梺鎸庣☉鐎氼噣鎯侀崼銉︹拺婵懓娲ら悘鍙夌箾娴ｅ啿鍟В鍕攽閿涘嫬浜奸柛濞у懐绀婇柍褜鍓氭穱濠囶敃閵忕媭浠奸悗瑙勬尭鐎氭澘顫忓ú顏勫窛濠电姴瀚ф慨鍥р攽閻愭彃鎮戦柣鐔濆嫮鐝堕柡鍥╁枔缁♀偓濠殿喗锕╅崢楣冨储闁秵鈷戦柡鍌樺劜濞呭懘鏌涘▎鎰妤犵偛顑呴埞鎴﹀礃閳哄啠鍋撳ú顏呪拺缂備焦鈼ら鍫濆偍闁哄稁鍋呭畷鏌ユ煕閳╁啰鈯曢柣鎾崇箻閺屾盯顢曢敐鍥╃暫闂侀潻缍€椤濡甸崟顔剧杸闁挎繂瀚伴崑妤呮⒑閸濆嫮鐏遍柛鐘崇墪閻ｅ嘲顫滈埀顒勫箠閻樺灚宕夊〒姘煎灟缁辨棃姊婚崒娆戭槮闁汇倕娲敐鐐村緞閹邦剙鐎梺绉嗗嫷娈旂紒鐘崇墵閺屽秹宕崟顒€顎涢梺杞扮閸熸挳寮婚妸銉㈡斀闁糕剝锚椤庢盯姊洪柅鐐茶嫰婢ь喚绱掔紒姗堣€挎鐐插暙铻栭柛娑卞灠缁侊箓姊洪崜鑼帥闁哥姵鐗楅幈銊︽償閳锯偓閺€浠嬫煟閹邦垰鐨烘繝鈧幘顔界厱闁哄啠鍋撻柛銊ユ健閻涱噣宕卞Ο鑲╂嚌闂侀€炲苯澧柣锝夋敱缁虹晫绮欑拠淇卞姂閺屻劑寮村Δ鈧禍楣冩⒑闁偛鑻晶浼存煛娴ｅ壊鐓兼鐐插暙閻ｏ繝骞嶉搹顐も偓濠氭椤愩垺澶勯柟灏栨櫆缁傛帡宕滆绾捐棄霉閿濆棗绲诲ù婊堢畺濮婃椽宕滈幓鎺嶇按闂佺瀛╅悡锟犲箖閿熺姴鍗抽柕蹇嬪灩瑜板嫰姊洪幖鐐插姌闁告柨绉归幃妤佺附閸涘﹦鍘甸柣搴ｆ暩椤牊绂掕閺屽秹鎮烽幍顔с垽鏌嶇憴鍕伌闁诡喒鏅犲畷锝嗗緞鐎ｎ偄鈧绱撻崒娆掑厡濠殿喚鍏橀獮濠囧箻缂佹鐣抽梻鍌欑劍鐎笛呮崲閸岀偞鍋嬮柛鈩冪☉閻掑灚銇勯幋锝嗙《闁活厽鐟ラ埞鎴﹀焺閸愵亝鎲欏銈忛檮婵炲﹪寮诲☉銏″亹闁告劖褰冮～鎺楁⒑缂佹ɑ鎯勯柛瀣工閻ｇ兘宕奸弴鐐嶁晠鏌ㄩ弮鍥舵綈閻庢矮绮欏缁樻媴閸涘﹨纭€闂佸憡顭嗛崨顖滎槸婵犵數濮撮崑鍡楊焽閺嵮€鏀介柣妯虹枃婢规鐥幆褍鎮戦柟渚垮妼椤粓宕卞Δ鈧獮瀣⒑缁嬫鍎愰柟绋款煼钘濋柣妤€鐗婇崕鐔兼煥濠靛棙宸濋柛鏃囨硾閳规垿鎮欑€涙ê闉嶉梺绯曟櫅閸熸潙鐣烽幋锕€绠婚柟纰卞幗椤旀棃姊虹紒妯哄婵☆垰锕よ灒闁逞屽墴濮婄儤娼幍顔煎闂佸湱鎳撳ú顓㈢嵁閸愵喖鐓涢柛娑卞枛濞堛倕顪冮妶鍡楃瑨妞わ富鍨跺顐ャ亹閹烘挴鎷婚梺绋挎湰閻熝囁囬敃鍌涚厵閻犲泧鍛紵缂傚倸鍊归幑鍥х暦缁嬭鏃堝焵椤掑倸顥氶柛褎顨嗛悡娆撴煙椤栨稒绶茬悮姘舵⒑缁嬪灝顒㈡い銊ワ躬瀵鎮㈤悡搴ｎ唹闂佸綊鍋婇崜娑㈠储椤愶附鈷戦柛婵勫劚鏍￠梺鍛婃⒐閻熲晛顕ｆ繝姘櫜闁告稑鍊瑰Λ鍐春閳ь剚銇勯幒鎴濐仾闁稿顑夐弻娑㈠焺閸愵亝鍣紓浣哄У濡啴寮婚悢鍏煎€绘俊顖濐嚙闂夊秵绻涚€涙ê娈犻柛濠冪墱閹广垹鈹戠€ｎ偒妫冨┑鐐村灥瀹曨剟宕滈柆宥嗏拺缂佸灏呭銉╂煟韫囨柨鍝洪柕鍡楀暣婵＄兘鍩￠崒姘ｅ亾閻戣姤鐓犵痪鏉垮船閸樻悂鏌ц箛鎾诲弰婵﹥妞藉畷銊︾節閸愶絾瀚荤紓浣哄亾濠㈡绮旂憴鍕箚闁汇垻顭堢粈瀣亜閺嶃劎鈯曟繛鍛濮婃椽宕滈懠顒€甯ラ梺鍝ュУ閻楁粎鍒掓繝鍥舵晪闁逞屽墴楠炲啫螖閸愨晛鏋傞梺鍛婃处閸撴盯藝閵娿儮鏀介柣鎰絻缁狙囨煥閺囨ê鐏查柣娑卞櫍瀹曞崬鈽夊Ο鑲╂綁闂備礁澹婇崑鎺楀礈濞戞氨鐭欓煫鍥ㄦ惄濞撳鏌曢崼婵囶棞闁诲繗椴哥换娑欏緞鐎ｎ偆顦伴梺璇″灠鐎氼參骞嗛弮鍫澪╅柨鏃囶潐鐎氳棄鈹戦悙鑸靛涧缂佽弓绮欓獮澶愭晸閻樿尙鐣鹃梺鍓插亞閸犳挾绮绘ィ鍐╁仯闁搞儱娲ら幊鎰板汲閵堝鈷戦梻鍫熺⊕椤ユ粓鏌涢悢鍛婄稇闁伙絿鍏樻俊鎼佸煛婵犲啯娅撶紓鍌氬€烽梽宥夊垂濞差亝鐓ラ柕鍫濇噳閺€浠嬪箳閹惰棄纾圭憸蹇擃嚗婵犲啰顩烽悗锝庝簽閺屽牆顪冮妶鍡欏⒈闁稿鐩幃锟犲即閵忥紕鍘甸柡澶婄墦缁犳牕顬婇鈧弻宥夋煥鐎ｎ亝璇為梺鍝勬湰閻╊垶銆侀弴銏℃櫜闁搞儴鍩栧▓瑙勭節閻㈤潧浠滈柟鍐查鐓ゆい鎾卞灩閽冪喖鏌ｉ弮鍌楁嫛闁轰礁锕︾槐鎺懳旈埀顒勫箹椤愶絿顩锋い鏇楀亾婵﹥妞藉畷顐﹀礋椤掍焦瀚崇紓鍌欑椤戝棝鎮у鍛灊閻犲洦绁村Σ鍫ユ煏韫囨洖啸闁活偄瀚板铏规喆閸曨偄濮㈤梺鍛娚戠划鎾崇暦閹达箑绠婚柤鎼佹涧绾绢垶姊洪棃娑辩劸闁搞劏顫夌粋宥夋倷椤掑倻顔曢梺鍓插亝缁诲嫭绂掗姀锛勭闁告侗鍣懓鍧楁煛鐏炲墽銆掗柍褜鍓ㄧ紞鍡樼濠婂牜鏁傛い鎾跺枂娴滄粓鏌曡箛濠傜労闁瑰濮风槐锕傛煟閿濆懐鐏遍柣顓熺懇閺屾盯鈥﹂幋婵囩亾闂佺粯绋堥弲婊勭┍婵犲洦鍊锋い蹇撳閸嬫捇寮介鐔蜂罕濠德板€曢崯浼存儗濞嗘挻鐓欓柣鎴烇供濞堟洟鏌涚€Ｑ勬珚闁哄矉缍侀獮瀣晲閸涘懏鎹囬弻宥夋煥鐎ｎ亞鐟ㄩ梻鍥ь樀閺屻劌鈹戦崱妯烘闂佸摜鍠撻崑銈夊蓟濞戙垺鍋勯柛婵嗗濡叉劙姊洪崫鍕拱闁烩晩鍨伴锝夘敆閸曨剙鈧兘鏌涘▎蹇ｆЦ婵炲拑绲跨槐鎾存媴閻ｅ苯鐗氶梺绋匡攻缁诲牆顕ｆ繝姘у璺猴功閻ｆ娊姊洪崷顓炲妺闁搞劌鐏氶幈銊╁閻欌偓濞撳鏌曢崼婵嗏偓鐟扳枍閸℃瑦鍠愰柡澶婄仢閺嗐垽鏌ｈ箛鎾虫殻婵﹥妞介獮鎰償閿濆洨鏆ら梻浣烘嚀閸熷潡鏌婇敐鍜佸殨闁规儼濮ら崐鐑芥煟閹寸儐鐒介柛妯块哺缁绘繈鎮介棃娴躲垽鏌涙繝鍌ょ吋鐎规洘妞介弫鎰緞鐎ｎ剙骞愰柣搴″帨閸嬫捇鎮楅敐搴″鐞氾附淇婇妶鍥ラ柛瀣☉鐓ゆい鎿冩娇閳ь兛绀侀埥澶娢熼柨瀣垫綌婵犳鍠楄彠闁稿寒鍣ｅ畷鎴﹀箻鐠囪尙鐤€濡炪倖鎸炬慨鐑筋敊閺囥垺鐓熼幖娣灮閳洘銇勯鐐村枠闁诡垰鏈换婵嬪礋椤撶媴绱抽柣搴＄畭閸庨亶骞忛幋锔惧彆妞ゆ帒鍊甸崑鎾斥枔閸喗鐏堝銈庡幘閸忔ê顕ｉ锕€绠涙い鎾跺仧缁愮偤鏌ｆ惔顖滅У濞存粍鐟ч懞杈ㄧ節濮橆厸鎷绘繛杈剧到閹诧繝宕悙鐢电＜闁告繂瀚崑銉р偓瑙勬礃濞茬喖鐛惔銊﹀殟闁靛鍎伴惀顏堟⒒娴ｅ憡鍟炴繛璇х畵瀹曞綊鏌嗗鍛幈闂佺鎻梽鍕偂閺囩喓绡€闂傚牊绋掗ˉ婊勩亜韫囷絽浜伴柡宀嬬秮楠炴帡寮撮悢鎭掆偓濠勭磽娴ｄ粙鍝洪悽顖滃仧濡叉劙骞掗幊宕囧枛閹虫牠鍩￠崘鈺傤啌闂傚倸鍊峰鎺旀椤旀儳绶ら柛褎顨呯粈鍌涙叏濡炶浜惧Δ鐘靛仜閸熷瓨鎱ㄩ埀顒勬煏閸繃鍣芥い蟻鍛＜闁绘劦鍓欓婊冾渻鐎涙ɑ鍊愰挊鐔兼煕椤愩倕鏋旂紒鈾€鍋撻梻浣圭湽閸ㄨ棄顭囪缁傛帡鏁冮崒娑氬幈闂侀潧顭堥崕鎶藉春閿濆鐓欐い鏍ㄦ皑閻掑憡銇勯姀鈥冲摵闁糕斁鍋撳銈嗗坊閸嬫捇鏌ｉ敐鍥у幋妞ゃ垺娲熼崺妤呮嚍閵夛富妫冮梺绯曟杹閸嬫挸顪冮妶鍡楃瑨閻庢凹鍓熼幃鈥愁潨閳ь剟寮婚悢鍛婄秶濡わ絽鍟宥夋⒑缁嬪尅韬い銉︽崌閸┾偓妞ゆ帒鍊归崵鈧繝銏㈡嚀閿曨亜鐣锋导鏉戝唨鐟滃寮搁弮鍫熺厾闁告縿鍎查弳鈺冪磼閳锯偓閸嬫挻绻濋悽闈涗粶闁绘妫濋幃妯衡攽鐎ｎ亜鍤戦梺闈涚墕椤︿即鎮″☉妯忓綊鏁愰崨顔兼殘闂佺懓寮堕幃鍌炲蓟濞戙垹绠抽柟鎯х－閻熴劑姊虹€圭媭鍤欓梺甯秮閻涱喖螣閾忚娈鹃梺鎼炲劥濞夋盯寮禒瀣拻闁稿本鐟чˇ锕傛煙绾板崬浜扮€规洦鍨堕、鏇㈡晝閳ь剛澹曢悷鎵虫斀闁绘ê纾。鏌ユ煕鐎ｎ亜鈧潡寮婚悢鐓庣畾鐟滄粓宕甸悢铏圭＜闁抽敮鍋撻柛瀣崌濮婄粯绗熼埀顒€顭囪椤ㄣ儴绠涢弴鐐电瓘婵炲濮撮鍡涘磻閸岀偞鐓欓柟娈垮枛椤ｅジ鏌ｉ幘瀛樼闁哄矉绻濆畷姗€鏁愰崨顒€顥氬┑鐘垫暩閸嬬姷浜稿▎鎾崇獥闁哄稁鍘惧畵渚€鏌涢幇闈涙灍闁稿﹦鍏橀弻娑樷攽閸℃浠奸梺璇插瘨閸樺ジ鈥旈崘顔嘉ч柛鈩冾殔椤孩绻濆▓鍨灈缁剧虎鍙冮幊鐐存綇閵娧呯槇濠殿喗锕╅崢鎼佸箯濞差亝鈷戦柤濮愬€曢弸鏂款熆瑜庨〃濠囩嵁閸℃稑閱囬柕蹇嬪灮閿涙粍绻濋姀锝嗙【闁挎洏鍊濋妴鍌氱暦閸モ晝锛滃銈嗘瀹曠數绮婃搴ｇ＜闁绘ê纾ú瀵糕偓娈垮枟閹告娊骞冮埡鍐ㄦ瀳濠㈣泛鑻花銉╂⒒閸屾艾鈧嘲霉閸ヮ剨缍栧璺虹昂娴滃綊鏌涢幇闈涙珮闁轰礁瀚伴弻娑㈠Ψ閵忊剝鐝栭梺娲诲幗閻熲晠骞冭ぐ鎺戠倞闁冲搫鍊搁埢蹇涙煙閸忚偐鏆橀柛鏂跨焸閹瑦绻濋崟顒€鏋戝┑鐘绘涧椤戝洭宕ｉ弴鐔翠簻闁瑰搫绉瑰宄懊瑰鍕煉闁哄本娲濈粻娑㈠Ψ瑜忛敍鐔兼⒑鐎圭姵顥夋い锔垮嵆婵＄敻宕熼锝嗘櫇闂佹寧绻傚ú銊╂偪閸曨垱鍊甸悷娆忓缁岃法绱掗幓鎺嗗亾閻旇桨鑸梻鍌欑濠€閬嶁€﹂崼鈶╁亾閸偄娴柛鈹惧亾濡炪倖甯婄欢鈥斥枔閺囩姷纾肩紓浣诡焽缁犵偤鏌熼鑽ょ煓婵☆偄鍟湁閻犱礁婀辩粙濠氭煏閸パ冾伃鐎殿噮鍣ｉ崺鈧い鎺戝閸嬪鏌ｅΟ鍨毢闁哄棴绠戦湁闁稿繐鍚嬬紞鎴︽煕閹般劌浜惧┑锛勫亼閸娿倝宕曢埡鍛ч幖娣灮缁夐攱淇婇悙顏勨偓褎淇婇崶銊︽珷婵°倕鎳庣粻姘舵煛閸愩劎澧曟い顐㈡嚇閺屽秹宕崟顐熷亾閼姐倗鐭欓柟鎵閳锋帡鏌涚仦鍓ф噮妞わ讣闄勭换婵嬪焵椤掑嫭鐒肩€广儱鎳愰敍鐔兼⒑闂堟稓澧曟い锔诲弮閸┾偓妞ゆ巻鍋撻柛鐔告綑閻ｇ兘濡搁埡濠冩櫖濠殿喗锚閸氬藟閿熺姵鈷掑ù锝勮閻掑墽绱掔紒姗嗘疁鐎规洘鍨块獮鍥敊閻撳巩姘舵⒑闁偛鑻晶瀛樻叏婵犲啯銇濈€规洘绮撻幊鐘活敆閳ь剛鏁妷鈺傗拺缂佸顑欓崕蹇涙倵濮樼厧寮鐐茬墦婵℃悂鍩℃担鍝勨偓鐐差渻閵堝棗绗傞柤鍐茬埣瀹曘垽宕ㄦ繝鍕啎闁哄鐗嗘晶鐣岀矓椤斿浜滈柕澶涢檮瀹曞矂鏌熼姘冲闁宠閰ｉ獮鍥敇閻愯弓绱熸繝鐢靛Х閺佸憡鎱ㄩ幘顔肩柈妞ゆ牜鍋涙濠电娀娼ч悧鍐磻閹捐埖鍠嗛柛鏇ㄥ墮椤︹晠姊虹粙娆惧剰闁挎洏鍎茬粚杈ㄧ節閸ャ劌鈧鏌﹀Ο鐚寸礆闁靛ň鏅滈悡蹇擃熆鐠鸿櫣澧曢柛鏂跨摠娣囧﹪顢曢～顔垮惈濠殿喖锕ら…宄扮暦閹烘垟鏋庨柟鎼幗琚﹂梻鍌欒兌椤㈠﹪顢氬鍛床婵犻潧顑囧畵渚€鏌熼柇锕€骞戦柛瀣嚇閺屾盯骞囬埡浣割瀷闂佺粯绋忛崕闈涱潖濞差亜浼犻柛鏇ㄥ幐閺嬪棝姊洪崨濞氭垿宕曢幎鑺ュ仼闁割煈鍋嗛悷褰掓煃瑜滈崜鐔奉嚕鐠囨祴妲堥柕蹇曞Х閸旀挳姊洪崨濠傚闁稿鎹囬、妯裤亹閹烘挴鎷洪梺鍛婄☉閿曘劍绔熷Ο姹囦簻闁瑰瓨绻嶅Ο鈧悗娈垮枦椤曆囧煡婢舵劕顫呴柣姗€娼ф慨鍫曟⒒娴ｄ警鐒剧紒缁樺笚閸掑﹪顢橀悢渚锤濡炪倕绻愰悧鍕焵椤戣法绐旀鐐搭焽閹风娀鎳犻澶婃櫔缂傚倸鍊搁崐鐑芥倿閿曚礁缍旈梻浣哥秺閺€鍗烆渻閽樺娼栨繛宸簻瀹告繂鈹戦悩鎻掝仱婵℃彃鐗撳娲箰鎼淬垻鈹涙繝纰樷偓铏窛婵″弶鍔欓獮姗€骞囨担鐟板厞闂備胶鍘ч幗婊堝极閹间礁鍌ㄩ梺顒€绉甸悡娆撴煕韫囨艾浜归柡鍡橈耿閺屾盯濡搁妷顔惧悑閻庤娲╃紞渚€宕洪埀顒併亜閹烘垵顏柍閿嬪灴閹綊宕堕敐鍌氫壕鐎规洖娲ｉ崫妤呮⒒娴ｅ憡鎲搁柛鐘冲姍楠炴劙骞庨懞銉ヤ粧濡炪倖妫冮弫顕€宕戦幘缁樻櫜閹肩补鍓濋悘宥夋⒑閸濆嫭鍣虹紒顔芥崌楠炲啫鐣￠幍铏€诲┑鐐叉閸ㄧ鎽梻浣筋嚙鐎涒晠鎳濇ィ鍐ㄨЕ閻庯綆鍓氬畷鍙夌節闂堟稒顥戦柡瀣閺屾盯鈥﹂幋婵囩亶闂佽绻戦幑鍥ь潖閾忚鍏滈柛娑卞枤瑜把囨⒑閸︻収鐒鹃柟鑺ョ矒瀹曪綁宕ㄧ€涙ǚ鎷洪梻鍌氱墛缁嬫挻鏅堕弴鐔剁箚妞ゆ劧绲鹃埛鎺楁煙楠炲灝鐏茬€规洖宕—鍐磼濡粯婢戦梻鍌欒兌椤牓寮甸鍌氭瀳鐎广儱顦悿顕€鏌ｉ幇顔煎妺闁绘挻娲栭埞鎴︽偐閹绘巻鍋撶紒妯碱浄婵炴垯鍨洪悡娆忋€掑顒備虎濠碘€炽偢閹藉爼鏁愭径瀣幗闂佸湱鍋撴繛濠囶敁濡も偓闇夐柣妯碱劜閼版寧鎱ㄦ繝鍐┿仢鐎规洦鍋婂畷鐔兼濞戞ê顥夐梻鍌欒兌椤牓鏁冮妷褎宕查柛顐ｇ箥閸ゆ洖鈹戦悩瀹犲闁绘帗妞介弻娑㈠箛閸忓摜鏁栭梺纭呮珪缁诲牆顫忓ú顏勭闁绘劖褰冩俊褔姊洪崨濠冨闁告ɑ妞介弻鍥敍閻愮补鎷绘繛杈剧秬濞咃絿鏁☉銏＄厵缂佸娉曢崺锝団偓瑙勬礃閸旀瑥顕ｆ禒瀣垫晣闁绘劕绋勭粻鎾诲蓟濞戙垹鍗抽柕濞垮劜閻忔捇姊哄Ч鍥р偓鎰板磻閹剧粯鈷掑ù锝呮啞鐠愶繝鏌涚€ｎ偅宕岀€规洘绮岄～婵嬵敇閻戝棗娈奸梻渚€鈧偛鑻晶顖毲庨崶褝韬柟顔界懇椤㈡棃宕橀鍡╂К婵犵數鍋犻幓顏嗗緤娴犲绠熼柍鈺佸暙缁剁偤鏌涢弴銊ョ仭闁绘挸鍟村娲垂椤曞懎鍓伴梺璇茬箚閺呮繄妲愰幒鎾寸秶闁靛绠戦棄宥夋⒑閻熸澘妲婚柟鍐茬箻楠炲牓濡搁埡浣侯吅濡炪倖鎸荤换鍫ュ磻濡ゅ懏鈷戦悹鍥ｂ偓铏亶闂佹寧娲忛崹钘夌暦濞差亝鏅搁柣妯诲絻缁愭稑顪冮妶鍡樷拹闁稿孩濞婇悰顔嘉旈崨顔规嫽婵炶揪缍€椤鎮橀柆宥嗙厸闁告侗鍠氬ú瀵糕偓瑙勬处閸ㄥ爼銆佸☉銏″€烽柛顐ｇ箥濡偓閻庤娲栭妶鎼佸春濡ゅ懎鐓涘ù锝呭槻椤ユ碍绻濋悽闈涗粶闁绘妫濋幃妯衡攽鐎ｎ亜鍤戦梺缁樻煥閻ㄦ繈寮ㄦ禒瀣厽闁归偊鍨奸崵瀣椤掑澧撮柡灞炬礋瀹曢亶寮撮悪鈧Σ顕€姊虹€圭姵顥夋い锕€鐏氶幈銊╁焵椤掑嫭鐓冮柕澶涢檮閻忛亶鏌涚€ｎ偅宕岄柟顔界矒閹崇偤濡烽妷銏犱壕闁汇垹鎲￠悡鐔兼煏韫囧﹥顫婇柛鐔风箻閺岋綁骞掑Δ鍐毇闂?"
        elif scenario == "plan":
            anchor += " 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲濞淬儱鐗撳鎻掆槈閵忕姷顢呴梺瑙勫劶婵倝鎮￠悢鍏肩厵闂侇叏绠戦悘鐘电磼閹插顩紒杈ㄥ浮婵℃悂濡堕崶鈺冨幆婵犳鍠栭敃锕傚磿閵堝拋鐒芥い蹇撶墕缁犮儲銇勯弴鐐村櫤鐞氾箓姊婚崒娆戭槮闁硅姤绮撳畷鎶藉Ψ閳轰胶锛涙繝鐢靛Т濞层倝寮伴妷鈺傜厽闁归偊鍓氶幆鍫㈢磼閻欏懐绉柡灞诲姂瀵潙螖閳ь剚绂嶉崜褏纾奸柣鎰靛墮閸斻倝鏌涘顒夊剶妤犵偛鐗撴俊鎼佸Ψ椤旇棄缂撻梻浣虹《閸撴繈銆冮崨顖滀笉鐟滅増甯楅埛鎴︽煕濠靛棗顏い銉︾矒閺岋絽螖娴ｇ懓纰嶅銈庡亜缁绘﹢骞栬ぐ鎺戞嵍妞ゆ挾濯寸槐鍙夌節绾版ɑ顫婇柛銊ф暬椤㈡俺顦撮柛鐘诧工椤撳吋寰勭€Ｑ勫缂傚倷绀侀鍛焊閸涱収鍟呴柕澶涜礋娴滄粍銇勯幘璺盒㈤柛妯侯嚟閳ь剝顫夊ú妯侯渻娴犲鏄ラ柍褜鍓氶妵鍕箳瀹ュ顎栨繛瀛樼矋缁捇寮婚悢鐓庝紶闁告洦鍓﹀Λ鐐寸箾鐎涙鐭婂褏鏅Σ鎰板箻鐎涙ê顎撻梺鍛婄箓鐎氬懘濮€閵忋垻锛滄繝銏ｆ硾閺堫剟宕甸埀顒勬⒑娴兼瑧鎮奸柛蹇斆锝夊箻椤旂⒈娼婇梺缁樕戦鏍绩閵娾晜鈷掑ù锝囩摂閸ゆ瑧绱掔紒妯虹闁告帗甯￠、娑橆潩閸忕厧鐦滈梻浣稿悑娴滀粙宕曢幍顔藉床闁糕剝绋掗悡鏇熴亜閹板墎绋荤紒鈧埀顒€螖閻橀潧浜奸柛銊ㄦ閹广垹鈽夐姀鐘茶€垮┑鈽嗗灡濞叉﹢宕归崷顓炲灊濠电姴娴傞弫鍐煥濠靛棗顏紒鐘冲哺濮婅櫣绱掑Ο鍝勑曟繛瀛樼矋缁捇宕洪埀顒併亜閹哄秷鍏屽褏鏁婚弻鐔碱敊閵娿儱鏋ら柣鎾卞劦閺屾盯顢曢敐鍥╃暭闂佹寧绋掗惄顖氼潖閾忓湱纾兼俊顖氭惈椤酣姊虹粙璺ㄦ槀闁稿﹥绻傞悾鐑藉箣閿曗偓绾惧吋绻涢幋鐐寸殤妞ゆ梹娲熷娲偡閹殿喗鎲奸梺鑽ゅ枂閸庣敻骞冨鈧、鏃堝醇閻斿搫骞楅梻浣筋潐閸庢娊鎮洪妸褏鐭嗛悗锝庡枟閻撴稓鈧厜鍋撻悗锝庡墰閻﹀牓鎮楃憴鍕闁绘牕鍚嬫穱濠囨倻閽樺）銊ф喐瀹€鍕剦妞ゅ繐鎳愮弧鈧梺姹囧灲濞佳勭閿曞倹鐓曢柕鍫濈凹闁垳鈧娲栭悥鍏间繆濮濆矈妲诲Δ鐘靛仦椤ㄥ﹤顫忕紒妯肩瘈閹肩补鈧尙鐩庢繝鐢靛仜閻即宕愬☉娆愭珷婵犻潧顑嗛埛鎴犵磼鐎ｎ偒鍎ラ柛搴㈠姍閺岀喖鎮烽悧鍫熸倷濡炪倖娲╃紞渚€銆佸Δ鍛妞ゆ劕顑冮崝鎴﹀蓟閵娾晛绫嶉柛銉仢閹惧绡€闁靛繆鈧磭浼屽┑顔硷工椤嘲鐣烽幒鎴旀瀻闁瑰瓨绻傞‖澶愭⒒娴ｅ憡鎯堟い鎴濇嚇婵″墎绮欏▎鎯ф闂佸湱绮璇参ｉ崼銉︾厪闊洦娲栧暩闂佸搫鑻悧鍡涒€旈崘顔嘉ч柛鈩冪懃閳峰牓姊虹粙娆惧剱缂佸鎸荤粩鐔煎即鎺虫禍褰掓煙閻戞ɑ灏甸柛妯兼暬濮婅櫣鎲撮崟闈涙櫛闂佸摜濮甸悧鐘诲Υ閸屾稓闄勯柛娑橈功閸樹粙姊虹憴鍕姢妞ゆ洦鍙冮獮濠囧川鐎涙鍘撻悷婊勭矒瀹曟粌鈹戠€ｅ墎绋忔繝銏ｆ硾閳洖煤椤忓嫬鍞ㄥ銈庡厴閸撴繂顪冮懞銉ょ箚闁割偅娲栭獮銏＄箾閸℃〞鎴犵矈椤愶附鈷戦柛婵嗗濡叉悂鏌ｅΔ鈧崯鏉戭嚕椤掍胶鐟归柍褜鍓欓悾鐑藉箣閿曗偓缁犲鏌ら幖浣规锭闁哄鍊垮娲川婵犲啫顦╅梺鍛婃尰閻╊垵妫熼梺闈浥堥弲婊堟偂閻斿吋鐓忛煫鍥э攻濞呭懘鏌ｈ箛銉х瘈闁诡喕绮欓、娑㈠Χ閸モ晝妲囬梻浣芥〃閻掞箓宕濆▎鎾崇畺婵炲棗绶烽崷顓涘亾閿濆骸浜濋柡澶嬫倐濮婅櫣鎷犻幓鎺戞瘣缂傚倸绉村Λ娆戠矉瀹ュ鍊烽柡宥囶焾濞测晠藝鐎靛摜纾奸弶鍫涘妼濞搭噣鏌熼鐣屾噰妞ゃ垺顨嗛幏鍛村传閸曨偅顓奸梻浣筋嚙濮橈箓锝炴径濞掓椽鏁冮崒姘鳖槶闂佺粯妫侀崑鎰暤娓氣偓閺屾盯骞囬棃娑欑亪闂佺粯鎸婚惄顖炲蓟濞戞ǚ妲堥柛妤冨仦閻忊偓闂備胶鎳撻崲鏌モ€﹀畡閭︽綎闁惧繐婀遍惌娆撴煙缁嬪灝顒㈤柟鐑戒憾濮婃椽鎳￠妶鍛畬闂佹悶鍎扮粈浣该洪銏犳瀬闁告劦鍠栫壕鍏肩箾閹寸偠澹樻鐐茬Ч濮婃椽鎳￠妶鍛呫垺绻涙竟顖氭搐瀹告繃銇勯弽銉モ偓妤呭触瑜版帗鈷掗柛灞剧懅椤︼箓鏌熺拠褏纾块柡渚囧枛铻栭柛鎰ㄦ櫆濞堜即姊虹紒妯哄妞ゆ洦鍙冮妴鍛存倻閼恒儳鍙嗛梺鍝勬川閸嬫盯鍩€椤掆偓閹芥粎鍒掗崼銉ラ唶闁靛繆鈧櫕鐎鹃梻浣告惈閸婂綊顢栧▎鎾村€甸柤鍝ュ仯娴滄粓鏌￠崶顭戞當濞存粍鍎抽埞鎴︻敊绾攱鏁惧┑锛勫仩濡嫰鎮鹃悜绛嬫晝闁挎洍鍋撶紒鈧€ｎ偁浜滈柟鏉垮缁嬬粯銇勯弬鍨伃婵﹦绮幏鍛瑹椤栨粌濮奸梻浣瑰濞插繘宕愬Δ鍐╊潟闁绘劕顕弧鈧梺鎼炲劘閸斿秴鈻嶅鍫熲拺缂備焦锚婵洭鏌熺喊鍗炰喊鐎规洩绻濋獮搴ㄦ嚍閵壯冨箺闂備礁鎼崯顐﹀磹閼姐倕濮柍褜鍓涚槐鎾存媴闂堟稑顬堝銈庡幖閸㈡煡锝炶箛娑欐優閻熸瑥瀚弸鍌炴⒑閸涘﹥澶勯柛瀣閹便劑濮€閵堝棗鈧敻鎮峰▎蹇擃仾濠㈣泛瀚伴弻娑㈠箻鐠虹儤鐏堝Δ鐘靛仜閸燁偊锝炲鍫濈劦妞ゆ帒瀚弰銉╂煥閻斿搫孝缂佲偓閸愨斂浜滈煫鍥ㄦ尰閿涙梻绱掓潏銊у弨婵﹦绮粭鐔煎焵椤掑嫬鐒垫い鎺戝€告禒婊堟煠濞茶鐏￠柡鍛閳ь剛鏁哥涵鍫曞磻閹捐埖鍠嗛柛鏇ㄥ墰椤︺劑鏌ｉ姀鈺佺伈缂佺粯绻堥悰顕€宕橀妸銏＄€婚梺鐟扮摠閺屻劍绂嶆ィ鍐╃厽闁靛繆妲呴崯蹇涙煟閹烘柨浜炬い銊ｅ劦閹瑩鎳犻鈧·鈧┑鐑囩到濞层倝鏁冮鍫濈畺婵炲棙鎼╅弫鍌炴煕閺囨ê濡煎ù婊堢畺閺屸€愁吋鎼粹€崇缂備讲鍋撳璺侯儎缁诲棝鏌曢崼婵嗩伀闁告柨绉归弻娑樷枎韫囨洜顔掗梺鍝勭灱閸犳挾妲愰幒妤€顫呴柣妯虹－娴滃爼姊绘担渚劸闁挎洏鍊濋幃銉︾附缁嬭儻鎽曢梺鎸庣☉鐎氼亜鈻介鍫熷仯闁搞儯鍔岀徊璇测攽椤旇姤绀嬫慨濠呮缁辨帒螣鐠囧弶娈梻浣告憸婵敻宕濆Δ鍛闁靛繒濮Σ鍫ユ煏韫囨洖啸妞ゆ挻妞藉铏圭磼濡搫顫岄梺璇茬箲瀹€绋跨暦閹剁瓔鏁囬柕蹇娾偓鏂ュ亾閻㈠憡鍋℃繛鍡楃箰椤忣亞绱掗埀顒勫焵椤掑嫭鈷戞繛鑼额嚙楠炴牠鏌涙繝鍌滀虎妞ゆ洩绲剧换婵嗩潩椤掑倷绱滈柣搴ゎ潐濞叉牕煤閿曗偓閳绘捇寮撮姀锛勫幗闁瑰吋鎯岄崹宕囩矓閻㈠憡鐓曢柟鎯ь嚟濞叉挳鏌熼娆戠獢鐎规洖銈告俊鐑芥晜鐟欏嫬顏圭紓鍌氬€风欢锟犲垂閸楃伝鍝勵潨閳ь剙顕ｉ幆鑸汗闁圭儤鎸鹃崢閬嶆煟鎼搭垳绉甸柛瀣噽娴滄悂顢橀悢缈犵盎濡炪倕绻愮€氼剟寮抽敐鍛斀闁炽儱纾崺锝団偓瑙勬礀瀹曨剝鐏冮梺鍛婂姦娴滄繈宕抽鐐粹拻濞达絿鐡旈崵娆撴倵濞戞帗娅婄€规洘鐟ㄩ妵鎰板箳閹寸姷鍘梻浣告啞閸旀垿宕濇惔銊ユ辈闁挎洖鍊归悡鐔兼煏韫囧鐒洪柡鍡╁灦閺屾稓鈧綆鍋呭畷宀勬煛娴ｇ懓濮堥柟顖涙閸╁嫰宕橀鍐╁枤闂傚倸鍊烽悞锔界箾婵犲洤缁╅弶鍫氭櫆閺嗘粓鏌ㄩ悢鍝勑㈤柦鍐枑缁绘盯骞嬪▎蹇曞姶闂佽桨绀侀崯鎾蓟閺囥垹閱囨繝闈涙搐濞呫倝姊虹拠鑼缂佽埖鑹鹃～蹇撁洪鍜佹濠电偞鍨堕悷顖毼涢敓鐘崇厽闁靛繆鏅涢悘锝夋煕鐎ｃ劌鈧繈鎮伴钘夌窞闁归偊鍓涢鎰箾鏉堝墽鍒伴柟鑺ョ矋椤ㄣ儵宕堕浣叉嫼闂侀潻瀵岄崣搴ㄦ倿妤ｅ啯鍊垫繛鎴炲笚濞呭﹦鈧娲樺ú鐔肩嵁濡偐纾兼俊顖炴敱鐎氬ジ姊虹拠鏌ヮ€楁繝鈧潏銊ュ灁妞ゆ挾鍎愰悞浠嬫煙閹殿喖顣奸柣鎾存礋閺屾洘绻涢崹顔煎闂佺顑冮崕鏌ャ€冮妷鈺傚€烽柟缁樺笚濞堫參姊虹€圭媭鍤欓梺甯秮閻涱喚鈧綆鍠栧Λ妯侯熆閸撲緡鐒炬い銉︾缁绘繈鎮介棃娑楁勃闂佹悶鍔岄悥濂搞€侀弮鍫晜闁割偒鍋呴弲婊堟⒑缁洖澧叉い銊ユ閹骞庨懞銉モ偓鍨殽閻愯尙浠㈤柛鏃€纰嶉妵鍕晜閸喖绁梺绯曟櫆閻╊垶鐛€ｎ喗鏅滈柣锝呰嫰楠炴姊绘担铏瑰笡闁哄被鍔戦獮澶愭晬閸曨剦鍋ㄩ梺鍝勮閸庢煡鎮″☉銏＄厱闁斥晛鍟伴悡顖炴煕濮樼厧浜炵紒杈ㄥ笚濞煎繘濡搁妷褜鍎岀紓鍌欐祰妞村摜鏁幒妤嬬稏婵犲﹤鐗嗛柋鍥煥濠靛棗鈧憡绂嶆ィ鍐╃厱妞ゎ厽鍨甸弸鎾绘煛閳ь剚绂掔€ｎ偆鍘撻梺瀹犳〃缁€渚€寮抽悙鐑樺€堕煫鍥ュ劚椤╊剟鏌嶈閸撴繈锝炴径濞掑搫顫滈埀顒勫极閸愵喖顫呴柕鍫濆暊閸嬫挻鎷呯化鏇熺€婚梺鍦亾濞兼瑩鎯傞崟顒傜瘈闁靛骏绲剧涵鐐亜閿曞倷鎲鹃柟顖氬閹棃濡搁敂瑙勫闂備胶顭堥張顒勬偡閵娾晛绀傜€光偓閳ь剛妲愰幒妤婃晪闁告侗鍘炬禒绋课旈悩闈涗沪闁告梹鐟ラ悾鐑筋敃閿曗偓鍞梺闈涚箳婵櫕绔?"
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
            parts.append("濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ゆい顓犲厴瀵鏁愰崨鍌滃枎閳诲酣骞嗚椤斿嫮绱撻崒娆掑厡濠殿喗鎸抽幃妯侯潩鐠轰綍锕傛煕閺囥劌鏋ら柣銈傚亾闂備礁婀遍崑鎾诲箚鐏炶娇娑㈡倷閻㈢數锛濇繛杈剧悼閺咁偊宕奸鍫熺厱濠电姴鍟扮粻鐐碘偓娈垮枛椤兘骞冮姀銈嗘優闁革富鍘鹃崢顖炴⒒娴ｇ顥忛柣鎾崇墦瀹曟娊顢氶埀顒€鐣峰┑鍥х窞闁归偊鍘搁幏娲⒑閸涘﹦鈽夐柨鏇畵楠炲﹪宕橀鍡欙紲缂傚倷鐒﹂敃顐︽嚀鐠恒劉鍋撳▓鍨灈妞ゎ厾鍏樺顐﹀箛椤撶偟绐炴繝鐢靛Т鐎氱兘宕ラ崨瀛樷拻濞达綀娅ｇ敮娑欍亜椤撶偟澧曢柍璇茬Ч瀵挳濮€閳ュ厖鎴锋俊鐐€曠换鎰版偋婵犲洤纾归柣銏犳啞閸嬧剝绻涢崱妤冪妞ゅ浚浜幃妯跨疀閿濆懍绨界紓浣介哺鐢繝骞婂鍫燁棃婵炴垶蓱閹虫瑩鏌ｆ惔銏╁晱闁哥姵鐩、姘愁樄闁糕斂鍎插鍕箛椤掑缍傞梻浣虹帛钃遍柣妤佹崌瀹曟繂顓兼径濞箓鏌涢弴銊ョ仩缂侇偄绉归弻娑氫沪閹规劕顥濇繛瀵稿У閿氭い顏勫暣婵¤埖鎯旈垾鑼埍闂備礁鎼幊鎰叏閹绢噯缍栭煫鍥ㄦ媼濞差亶鏁傞柛鏇ㄥ墮缁佽埖淇婇悙顏勨偓鏍箰妤ｅ啫绐楅幖绮规閺嬫梻鈧厜鍋撻柛鏇ㄥ厴閹疯櫣绱撻崒娆戝妽妞ゎ厼娲﹂弲鍫曨敂閸喓鍘梺鍓插亖閸╁嫰鎮為悙顑句簻闁哄浂浜炵粙鑽ょ磼缂佹绠撴い顐ｇ箞椤㈡鍩€椤掆偓閻ｇ敻宕卞☉娆屾嫼缂傚倷鐒﹁摫妞ゃ儱妫欑换娑㈠椽閸愵亞袦闂佽鍨欢姘暦婵傜唯闁挎梻绮ˉ濠冧繆閻愵亜鈧牠宕濋幋锕€鍨傞柣鎴灻欢鐐烘煕閺囥劌骞樼痪鎯с偢閹鏁愭惔鈥茬盎濠电偞鎯岄崰妤呭Φ閸曨垰顫呴柍鈺佸暙绾板秴顪冮妶鍡樺碍闁靛牏顭堥悾鐑藉醇閺囩偟鍘搁梺鍛婂姌濞夋洟姊婚娑氱瘈闁汇垽娼ф禒鈺呮煙濞茶绨界紒杈╁仦閹峰懘鎼归崷顓ㄧ闯婵犳鍠楅敃鈺呭礈閿曞倹鍊甸柛顐ｆ礃閻撴瑩姊婚崒姘煎殶闁告柨绉归弻锝夊箻鐎涙顦伴梺鍝勬湰濞叉鎹㈠☉銏犲瀭妞ゆ梻鍘ц闂傚倷鑳剁涵鍫曞疾椤忓棗绶ら柛褎顨呴悞鍨亜閹哄秶璐伴柛鐔风箻閺屾盯鎮╁畷鍥ㄥ垱濡炪們鍨烘穱娲囪ぐ鎺撶厱闁崇懓鐏濋崝婊呪偓鍨緲鐎氼厾鎹㈠┑鍥ㄥ劅闁靛繒濮风槐锕傛⒒閸屾瑨鍏岀痪顓炵埣瀹曟粌鈹戠€ｃ劉鍋撻崘顔煎耿婵炴垶顭囬敍娆忣渻閵堝棛澧遍柛瀣仱閸╂盯骞掗幊銊ョ秺閺佹劙宕ㄩ鍏兼畼闂備礁鎽滈崰鎾诲磻濞戙垹违闁圭儤鍩堝鈺傘亜閹炬瀚弶褰掓煟鎼淬値娼愭繛鍙夌墱缁辩偞绻濋崶鈺佺ウ闁硅壈鎻徊鎸庛仚閹惰姤鍊甸柨婵嗛娴滄繃绻涢崨顔藉碍闁宠鍨块幃鈺咁敊閼测晙绱樻繝鐢靛仜椤︽壆绮欓弽銊︽珷婵犻潧顑嗛埛鎴︽偠濞戞巻鍋撻崗鍛棜婵犵數鍋涢顓熸叏閹绢噮鏁勯柛鈩冪⊕閸嬪倿鏌涢幇闈涙灍闁绘挸鍟村鍫曟倷閺夋埈妫嗗銈忚缁犳捇寮婚敓鐘插耿婵☆垰鍚嬮崳顔剧磽娴ｄ粙鍝洪悽顖ょ節閻涱噣骞樼拠鑼唺濠电娀娼ч悧鍡涘箖閹达附鈷掑ù锝呮啞閹牓鏌ｉ鈧妶绋跨暦娴兼潙鍐€妞ゆ挾鍋熼悿鍥⒑缂佹ê濮囬柟纰卞亜閺侇噣鏌ｉ悢鍝ョ煀缂佺粯锕㈤獮鍐焺閸愩劎绐炴繝鐢靛亼閸ㄥ搫螞閸愵喖绠栭柍鍝勬噺椤ュ牊绻涢幋鐑嗘畼闁硅娲熷缁樻媴閸涘﹥鍠愰梺鍝ュУ閸旀瑩鐛幇鏉跨闁芥ê锛夐妷銉冨綊鏁愰崨顓ф濠电偛鐨烽弲鐘诲箖鐟欏嫨鍋婇柟绋垮瘨娴犫晠姊洪崨濠冾棖缂佺姵鍨块垾鏃堝礃椤斿槈褔鏌涢埄鍐炬畼闁荤喆鍔戦弻锝嗘償閵忕姵鎯涢梺鍛婃⒐閸ㄥ灝鐣峰ú顏勭劦妞ゆ帊闄嶆禍婊堟煙鏉堝墽绋荤痪顓炲缁辨帡骞囬鐔叉嫽闂侀€炲苯澧い鏃€鐗犲畷鏉课旈崨顓狀唶闂佹儳娴氶崑鍛村矗韫囨稒鐓冪憸婊堝礈閻旂厧钃熺€广儱顦悡娑樏归敐鍛暈婵炲牊鐓″铏圭磼濡偐鐣烘繝鐢靛仜閿曘倝锝炶箛鏇犵＜婵☆垵顕ч鎾绘煟閻斿摜鎳冮悗姘煎墯缁傛帡鍩￠崨顔规嫼缂備礁顑呴悘婵嬵敆閵忋垻纾兼い鏃囧Г鐏忣參鏌ｉ敐鍛Щ妞ゎ偅绮撻崺鈧い鎺戝閳ь兛绶氬顒€鈻庨幆褎鍊梻浣虹《閸撴繈鎮烽妷鈺佸惞閺夊牄鍔庣弧鈧梺姹囧灲濞佳冩毄闂備浇妗ㄧ粈渚€骞夐敓鐘茬疄闁靛ň鏅滈崐濠氭煢濡警妲归柣搴墴濮婇缚銇愰幒鎿勭吹缂備讲鍋撳ù锝呮惈椤ユ艾鈹戦悩宕囶暡闁绘挾鍠栭弻鐔兼焽閿曗偓婢ь垶鏌熼姘卞ⅵ闁哄本鐩俊鎼佸Ψ閵夈垹浜鹃柛褎顨呴拑鐔哥箾閹存瑥鐒洪柡浣稿暣閺屻劌鈹戦崱姗嗘￥濡炪倧璐熼崕宕囨閹惧瓨濯撮柛婵嗗珔閵忋垻纾界€广儱鎷戦煬顒傗偓娈垮枦椤曆囶敇閸忕厧绶炲┑鐘辫兌閻愬﹪姊绘担鍛婂暈婵炶绠撳畷鎴﹀焵椤掑嫭鐓曢悗锝庡亝鐏忔壆绱掔紒妯肩畵妞ゎ偅绻堟俊鐑藉閻樺崬顥氶梻浣告啞缁嬫帒顭囧▎鎾村剹婵°倐鍋撴い顓℃硶閹瑰嫰鎼归崷顓濈礃闂備椒绱粻鎴︽偋婵犲嫭宕叉繝闈涱儐閸嬨劑姊婚崼鐔峰瀬闁靛繈鍊栭悡鏇炩攽閻樻彃顏悽顖涚洴閺岋繝宕ㄩ鐘茬厽閻庢鍠楅幐铏叏閳ь剟鏌ㄥ☉妯侯仼妤犵偛鐗撳缁樼瑹閳ь剙顭囪閳ワ箓宕奸妷銉э紵闂備緡鍓欑粔鎾倿閸偁浜滈柟鍝勭Ф閸斿秹鏌涙繝鍐ㄥ缂佺粯绻堥崺鈧い鎺嶈兌閻熷綊鏌嶈閸撴瑩锝炶箛娑欐優闁革富鍘鹃敍婊冣攽閳藉棗鐏犳繛瀛樼缁傚秴顭ㄩ崱娆庤埅婵犵數濮烽弫鍛婃叏閺夋嚚娲Χ閸パ屾闂佺鍕垫畼闁告瑦鎹囬弻娑㈠Ψ閿濆懎顬夐梺缁樻惈缁茶法妲愰幒鏃€瀚氶柛娆忣樈濡繝姊洪棃娑欐悙閻庢矮鍗抽悰顕€宕堕鈧粈鍫澝归敐鍫燁仩妞わ富鍋婂缁樻媴娓氼垱鏁梺瑙勬た娴滅偟鍒掓繝姘闁绘垵妫欓弫顖炴⒒閸屾艾鈧绮堟笟鈧獮澶愬灳鐡掍焦妞介弫鍐磼濮橆剛鈧參姊虹憴鍕靛晱闁哥姵纰嶇粙澶婎吋閸涱亝鏂€闂佺粯锚绾绢參銆傞弻銉︾厱閻庯絽澧庣粔顕€鏌＄仦鐔锋閻も偓濠殿喗锚閸氬绱為崼銏㈢＜闁告挆鍡橆€楁繛瀛樼矤娴滎亜顕ｆ繝姘嵆闁挎稑瀚弶鎼佹⒑閸濆嫭宸濋柛濠忕秮婵＄柉顦抽柛鐘冲姍閺岋絽螖閳ь剟鎮ч崱娆戠當婵鍩栭悡鏇㈡倵閿濆骸浜滈柣蹇旀尦閺岋紕浠﹂悾灞濄儲銇勮缁舵岸寮诲☉銏犵閻犺櫣鍎ら悗濠氭⒑娴兼瑧鎮奸柡灞筋樀婵＄敻骞囬弶璺唺闂佺鎻粻鎴﹀极瑜版帗鈷掑ù锝呮啞閹牊绻涚仦鍌氬鐎规洘鍨块幃鈺冩嫚閼碱剦鍟堥梻浣告惈濞层劑宕戦幇鏉跨哗濞寸姴顑嗛悡鐔兼煙闁箑骞楃紓宥嗗灴閺岋綀绠涢妷褏鏆ら梺鍝勮閸旀垵顕ｉ弶鎳虫梹鎷呴崷顓炵到闂傚倷绶氬褍螞濞嗘垶鏆滄俊銈呭暞瀹曞弶绻濋棃娑欙紞婵炲皷鏅滈妵鍕箻鐠虹洅銏☆殽閻愭惌娈滄慨濠勭帛閹峰懘鎮滃Ο鐑樼暚闂備礁顓介弶鍨瀳濡炪値鍋勭换姗€骞冮悜钘夌闁惧浚鍋嗛埀顒佹そ濮婃椽宕ㄦ繝浣虹箒闂佸憡鏌ㄩ悥濂稿箖閻戣姤鐒介柨鏃€鍎冲鎶芥⒒娴ｇ顥忛柛瀣╃窔瀹曡绻濆顒佽緢濡炪倖鍔ч梽鍕煕閹达附鐓曟繝闈涙椤忣剚銇勯顒傜暤闁哄本绋掔换婵嬪礃閻愵剛鏉归柣搴ゎ潐濞叉粍鏅跺Δ鍐╁床婵犻潧顑呴悙濠勬喐韫囨稏鈧線宕ㄧ€涙ǚ鎷虹紓鍌欑劍閿氬┑顔兼处娣囧﹪顢涘鎯т紣濡炪値鍘煎ú锕傚Χ閿濆绀冮柍鍦亾鐎氬ジ姊绘担铏瑰笡闁圭鎲￠〃銉╁传閵壯勶紡閻熸粍妫冨濠氭晲閸涘倹姊归幏鍛村捶椤撗勑ч梻鍌欒兌绾爼寮插┑瀣；闁靛牆顦卞畵渚€鎮楅敐搴℃灍闁哄懏绮撻弻锕€螣娓氼垱孝闂佺顑嗛幑鍥箖濠婂牊鍤嶉柕澹啫绠荤紓鍌欒兌閸嬫挸顭垮Ο铏规殾妞ゆ帊鐒﹀▍鐘炽亜閺嶎偄浠﹂柣鎾寸懇閺屻倝鎳濋悧鍫€愭繛瀛樼矊濠€杈╂閹烘挻缍囬柕濠忕畱闂夊秶绱撴担璇℃畼闁哥姵鐗曢悾鐑藉箚闁附歇闂備浇顕х换鎰版偋閹炬剚娼栨繛宸簻缁€鍌炴煕韫囨洦鍎犲ù鐘欏洦鈷戦柟鑲╁仜婵″潡鏌℃担鍓茬吋妤犵偛鍟灒閻忓繑鐗曟禍楣冩煥濠靛棝顎楅柡瀣枛閺岋綁骞樼捄鐑樼亪濡ょ姷鍋為悧鏇″絹濡炪倖宸婚崑鎾斥攽闄囨慨銈囨崲濞戙垹绠犵€瑰嫮澧楁径鍕煟閹惧鎳囬柟顔肩秺瀹曞爼宕惰閸ｄ粙鏌ｉ敃鈧悧鎾愁潖濞差亜绠伴幖杈剧悼閻ｅジ姊虹粙娆惧剭闁稿﹥娲熼、姘舵晲婢跺﹦顔掑銈嗘濡嫭绂嶅鍫熲拺闁诡垎鍛唶濠电姭鍋撻柛妤冨€ｉ敐澶婄倞妞ゆ帊璁查幏濠氭⒑缁嬫寧婀伴柤褰掔畺閸┾偓妞ゆ帊鐒﹂崐鎰版煙椤斻劌瀚弧鈧梺鍛婂姦娴滅偤骞婂┑鍡忔斀閹烘娊宕愰弴銏犵疇閹艰揪绲介ˉ姘舵煕瑜庨〃鍫ュ矗閹剧粯鐓曢柕澶涚到婵＄晫绱掗埀顒勫醇閵忋垺锛忛梺璇″瀻娴ｉ晲鍒掗梻浣告惈閻寰婃禒瀣剁稏婵犲﹤鐗嗛獮銏′繆閵堝嫯鍏屽ù婊庝邯濮婄粯鎷呴崨濠傛殘濠碘槅鍋呴崹鍦垝婵犳艾绠婚悹鍥蔼閹芥洟姊洪幐搴ｂ槈閻庢凹浜滈埢浠嬵敂閸喓鍘介梺鎸庣箓閹虫劕顭囬敓鐘崇厪濠㈣埖绋栫粈瀣瑰鍕煂闁硅尙顭堥悾婵嬪焵椤掆偓閳诲酣濮€閻欌偓濞尖晠鎮瑰ú顏嗙窗闁硅姤娲栭埞鎴︽倷閺夋垹浠ч梺鎼炲妼濠€杈╁垝缂佹绡€婵﹩鍘奸埀顒€鐏氱换娑㈠箣閻愬灚鍣介梺缁樺笩婵倗鎹㈠☉銏犻唶婵炴垶菤閸嬫挸螖閸愨晩娼熼梺瑙勫劤椤曨參鎮疯ぐ鎺撶厱闁靛鍨电€氼喗绂嶉鍛箚闁绘劦浜滈埀顒佺墵瀹曞綊鎮介弶鍡楁喘閹粙宕ㄦ繝鍌欑钵婵＄偑鍊栧ú宥夊磻閹炬惌娈介柣鎰綑濞搭喗顨ラ悙璇ц含闁圭厧缍婇、鏇㈡晲鎼淬埄妫冮梻鍌欒兌绾爼寮笟鈧畷鎴﹀箻閹颁焦瀵岄梺闈涚墕濡宕告繝鍥ㄧ厱閻庯綆鍋呭畷宀勬煛鐏炵澧茬紒妤冨枛瀹曟儼顦抽柣婵囩箓閳规垿顢欑涵宄板缂備緡鍣崹宕囧垝椤撱垺鍋勯柣鎾虫捣閸旓箑顪冮妶鍡楀潑闁稿鎸婚妵鍕敇閻愬鈹涘銈忕畱缂嶅﹪寮婚悢纰辨晩闁靛鍎查幖鎰殽閻愵亜鐏ǎ鍥э躬閹瑧鈧稒顭囬ˇ銊モ攽閿涘嫬浠╁┑顔哄€栫粚杈ㄧ節閸パ咁啇婵炶揪绲介幗婊堝储閸涘﹦绠鹃弶鍫濆⒔缁夘剚绻涢崪鍐М鐎殿喗鎮傞崺鈧い鎺戝閳锋垿鏌ゆ慨鎰偓鏇㈠几閹寸姷纾兼い鏃傚帶椤掋垽鏌￠崨鐗堢【閾绘牠鏌涢幇銊︽珕婵炲牊婢橀埞鎴炲箠闁稿﹥娲熼獮濠呯疀濞戞锛涢梺绋跨灱閸嬬偤鎮￠悢鍏肩厸闁稿本姘ㄦ禒銏ゆ煙椤旇棄鐏撮柡宀嬬秮楠炴鎹勯悜妯尖偓鐐箾閿濆懏鎼愰柨鏇ㄤ邯閵嗕礁鈽夊鍡樺兊濡炪倖鎸鹃崰搴ㄥ礈閻㈢數纾介柛灞剧懆閸忓矂鎮楀顒傜鐎规洖鐖兼俊姝岊槻妤犵偛鐗撳铏规嫚閼碱剛顔婇梺绋款儑婵炩偓妞ゃ垺淇洪ˇ鎶芥煙娓氬灝濮傜€规洘甯￠幃娆戔偓鐢殿焾楠炴劙姊虹拠鑼闁稿绋掗弲鑸电鐎ｎ亞鍘愰梺鍝勬储閸ㄦ椽鎮″▎鎰╀簻闁哄秲鍔庨埊鏇熴亜閵夈儳澧曢柍瑙勫灴閸╁嫰宕橀埡浣插亾閹邦兘鏀介柍銉ョ－閸╋絿鈧娲栧畷顒冪亙婵炶揪缍€濡椼劍绔熼弴銏♀拻闁稿本鐟︾粊鐗堛亜閺囧棗鍠氬鈺呮煥閺囩偛浜扮紓宥嗙墪椤法鎹勭悰鈥愁潓濠电偛妯婃禍婵嬪疾濠靛鐓曢悘鐐村礃婢规﹢鏌ｆ惔顔煎籍婵﹥妞藉畷婊堝箵閹哄秶鍑规繝鐢靛仜瀵爼鎮ч悩宸殨濞村吋娼欏敮闂佸啿鎼崐濠氬储閹剧粯鍋℃繝濠傚閻帞鈧娲樼划宀勶綖濠靛牊宕夊ù锝嗘穿缁犳捇寮诲☉銏犲嵆闁靛鍎虫禒鈺冪磽娴ｅ搫校濠电偛锕濠氭偄鐞涒€充壕婵炴垶鐟悞钘夆攽閳ヨ櫕鍠橀柡灞剧〒閳ь剨缍嗛崑鍛暦瀹€鍕厵缂佹稑婀辩弧鈧繝纰樷偓宕囧煟鐎规洦浜濋幏鍛嫚閳╁喛绱栭梻鍌氬€搁崐宄懊归崶銊﹀弿闁靛牆顦伴弲顏呬繆閻愵亜鈧垿宕曢鐐插瀭濠靛倻顭堟闂佸湱澧楀妯肩不閹惰姤鐓欓柟顖嗗懏鎲奸梺缁樼箖婵炲﹤顫忕紒妯诲闁告稑锕ら弳鍫熺箾閹惧顣叉い銊ワ工閻ｉ鎲撮崟顐殼濠电儑缍嗛崗姗€宕戦幘璇茬＜婵綆鍘藉浠嬨€侀弮鍫濆窛妞ゅ繐鎳庨鍦磽閸屾瑨鍏岄柧蹇撻叄瀹曘垺绺界粙璺ㄧ枃闂婎偄娲︾粙鎺楀磻閻旀悶浜滈煫鍥ㄦ尵婢ф盯鏌ｉ幘瀛樼闁哄矉绻濆畷姗€鏁愰崨顒€顥氶梻鍌欐祰瀹曠敻宕伴崱娑樼？闁汇垺鎮堕埀顑跨椤繈鎳滈崹顐ｇ彸濠电姰鍨奸崺鏍懌闂佸搫鎳忕换鍫濐潖濞差亜绠伴幖杈剧悼閻ｇ敻姊洪崫銉ユ珡闁稿鎳愮划瀣吋閸涱亝鏂€闁诲函缍嗛崑鈧柟閿嬫そ濮婃椽宕ㄦ繝鍕ㄦ闂佹寧娲忛崐鏍箞閵娾晛鐒垫い鎺戝閳锋垿鏌涘┑鍡楊仼闁逞屽墴椤ユ挸鈻庨姀鐙€娼╅柛鎾茬缁侊箓妫呴銏″闁瑰嘲顑呯叅妞ゅ繐绉甸弲婊堟⒑閸涘﹣绶卞ù婊勭箘閳ь剚鑹鹃妶绋款潖濞差亝鍤掗柕鍫濇啗閵忥紕绠鹃柤纰卞墮閳诲牓鏌涢埞鎯т壕婵＄偑鍊栧濠氬磻閹惧墎妫紓浣靛灩瀵噣鏌涢埞鎯т壕婵＄偑鍊栧濠氬磻閹炬番浜滄い鎾跺Т閸樺鈧鍠涢褔鍩ユ径鎰潊闁绘ɑ褰冪粊顕€姊绘笟鈧褔鈥﹂崼銉ョ？闂侇剙绋勭紞鏍煃閸濆嫭鍣洪柍閿嬪灴閺屾稑鈽夊鍫熸暰闁诲繐绻掗弫濠氬蓟閳╁啯濯寸紒娑橆儏濞堫厼顪冮妶搴′簻缂佺粯甯炲Σ鎰板箳閹冲磭鍠栭幊鏍煛閸屾碍鐤勯梻鍌氬€风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼顢欐慨鎰盎濡炪倖鎸鹃崑鐐电矚閹稿簺浜滈柨鏃傛櫕閸欌偓闂佽鍣换婵囦繆閼搁潧绶為悗锝庡墮鐢箖姊绘担绋款棌闁稿鎳愰幑銏ゅ礃椤旇偐锛涘銈呯箰閹虫劗绮婚崜褉鍋撻悷鏉款棌闁哥姵娲熼獮澶嬨偅閸愨晝鍘告繛杈剧到閹诧繝宕板鈧弻鈥崇暆鐎ｎ剛袦濡ょ姷鍋涘ú顓€佸Δ鍛＜闁稿矉濡囩粔顕€鏌″畝瀣М闁糕斁鍓濈换婵嬪磼濠娾偓閸濇姊绘担椋庝覆缂佽弓绮欏畷鏌ュ蓟閵夘垳绋忓┑鐘诧工閻楀棝鎮為崹顐犱簻闁圭儤鍨甸銉╂煃瑜滈崗娑氱矆娓氣偓閿濈偛鈹戦崼鐔风／闂佸憡绻傜€氼垶鍩€椤掆偓閻忔繈鍩為幋锔藉€烽柛娆忣樈濡繝姊洪幖鐐插闁哥姴姘﹂悘瀣⒑闂堟侗鐒鹃柛搴櫍瀵劍绂掔€ｎ偆鍙嗗┑鐐村灦閿氭い蹇婃櫅闇夋繝濠傚暔閸嬨垽鏌＄仦鍓р姇缂佺粯绻堝畷姗€顢旈崟銊﹀闂佽姘﹂～澶娒洪弽顐ょ濠电姴娲ょ粻鏍煥閻斿搫啸鐎规挷鐒﹂妵鍕箳瀹ュ牆鍘″┑鐐村絻椤曨參鍩€椤掑喚娼愭繛鍙夌矒瀹曚即寮介婧惧亾娴ｈ倽鏃堝川椤撶媴绱查梻渚€娼ч悧鍡椢涘┑瀣瀬?")
        elif learner_signal == "uncertain":
            parts.append("濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ゆい顓犲厴瀵鏁愰崨鍌滃枎閳诲酣骞嗚椤斿嫮绱撻崒娆掑厡濠殿喗鎸抽幃妯侯潩鐠轰綍锕傛煕閺囥劌鏋ら柣銈傚亾闂備礁婀遍崑鎾诲箚鐏炶娇娑㈡倷閻㈢數锛濇繛杈剧悼閺咁偊宕奸鍫熺厱濠电姴鍟扮粻鐐碘偓娈垮枛椤兘骞冮姀銈嗘優闁革富鍘鹃崢顖炴⒒娴ｇ顥忛柣鎾崇墦瀹曟娊顢氶埀顒€鐣峰┑鍥х窞闁归偊鍘搁幏娲⒑閸涘﹦鈽夐柨鏇畵楠炲﹪宕橀鍡欙紲缂傚倷鐒﹂敃顐︽嚀鐠恒劉鍋撳▓鍨灈妞ゎ厾鍏樺顐﹀箛椤撶偟绐炴繝鐢靛Т鐎氱兘宕ラ崨瀛樷拻濞达綀娅ｇ敮娑欍亜椤撶偟澧曢柍璇茬Ч瀵挳濮€閳ュ厖鎴锋俊鐐€曠换鎰版偋婵犲洤纾归柣銏犳啞閸嬧剝绻涢崱妤冪妞ゅ浚浜幃妯跨疀閿濆懍绨界紓浣介哺鐢繝骞婂鍫燁棃婵炴垶蓱閹虫瑩鏌ｆ惔銏╁晱闁哥姵鐩、姘愁樄闁糕斂鍎插鍕箛椤掑缍傞梻浣虹帛钃遍柣妤佹崌瀹曟繂顓兼径濞箓鏌涢弴銊ョ仩缂侇偄绉归弻娑氫沪閹规劕顥濇繛瀵稿У閿氭い顏勫暣婵¤埖鎯旈垾鑼埍闂備礁鎼幊鎰叏閹绢噯缍栭煫鍥ㄦ媼濞差亶鏁傞柛鏇ㄥ墮缁佽埖淇婇悙顏勨偓鏍箰妤ｅ啫绐楅幖绮规閺嬫梻鈧厜鍋撻柛鏇ㄥ厴閹疯櫣绱撻崒娆戝妽妞ゎ厼娲﹂弲鍫曨敂閸喓鍘梺鍓插亖閸╁嫰鎮為悙顑句簻闁哄浂浜炵粙鑽ょ磼缂佹绠撴い顐ｇ箞椤㈡鍩€椤掆偓閻ｇ敻宕卞☉娆屾嫼缂傚倷鐒﹁摫妞ゃ儱妫欑换娑㈠椽閸愵亞袦濡炪們鍨洪悷鈺侇嚕閹绢喖顫呴柍閿亾闁归攱妞藉娲川婵犲啫纾╅柣蹇撶箲閻熲晛鐣烽姀鐘闁靛骏绱曢崢閬嶆⒑缂佹◤顏堝疮閸啔褰掝敊闁款垰浜鹃悷娆忓缁€鍐煕閵娿儲鍋ラ柣娑卞枛铻ｅ〒姘煎灣閸炵敻姊洪崨濠冨闁告挻宀歌棢闁割偀鎳囬崑鎾舵喆閸曨剛锛橀梺鍛婃⒐閸ㄥ潡濡存担绯曟瀻闁瑰墽琛ラ幏濠氭煟鎼淬劍娑ч柟璇х節瀵娊鎮ч崼銏㈢槇闂佹眹鍨藉褍鏆╅梻浣芥〃缁€渚€骞夐敍鍕床婵炴垯鍨归悞鍨亜閹哄秷鍏岀紒鐘冲劤闇夐柨婵嗘噹閺嗚鲸绻涢弶鎴濃偓鍨嚕椤愶箑绀嬫い鏍ㄧ〒閸橀亶姊洪弬銉︽珔闁哥喍鍗抽崺濠囧即閵忥紕鍘遍柣搴秵娴滄粓鍩€椤掆偓濠€閬嶅箲閵忕姭妲堥柕蹇曞Х椤撳搫鈹戦悙鍙夘棞缂佺粯甯楃粋鎺撱偅閸愨斁鎷虹紓鍌欑劍钃遍悘蹇曞缁绘盯鎳犻鈧弸娑氣偓娈垮枛椤兘寮幘缁樺亹闁肩⒈鍓欓埀顒傚仱濮婃椽妫冨☉杈ㄐら梺绋挎唉濞呮洜绮嬮幒妤€绠氱憸澶愬绩娴犲鐓熼柟閭﹀幗缂嶆垶鎱ㄩ敐鍛棦闁哄本鐩俊鐑芥晲閸涱収鐎烽梻浣告啞鐪夌紒顔界懃铻為柛娑欐儗閺佸啴鏌曡箛濞惧亾閸愯弓鎲鹃梻鍌欒兌椤牏鈧稈鏅滅换娑欑節閸モ晛绁﹂梺鍛婂姀閺呮繈姊介崟顖涚厱婵炴垶锕崝鐔兼煕濡粯宕岄柟顔煎槻椤劑宕熼鐘靛帨闁诲氦顫夊ú妯煎垝瀹€鍕厴闁瑰濮崑鎾绘晲閸涱収鏆㈢紓浣割儏缁绘垹鎹㈠┑瀣潊闁挎繂鎳愰崢顐︽⒑閸涘﹥鈷愭繛鍙夌矌閸掓帗绻濆顒€鍞ㄥ銈嗘尵閸犳捇宕㈤柆宥嗙厽闊洦娲栨禒婊冾熆瑜岀划娆愪繆閹绢喖绠抽柟鎯у綁缁ㄥ姊洪崘鍙夋儓闁稿﹤顭峰畷锝夊焵椤掑嫭鈷戦悹鍥ｂ偓铏仌濡炪値鍋勯ˇ鍨繆閸洘鏅濋柛灞炬皑椤斿洭鏌熼崗鍏煎剹闁哥姵娲熷畷顐⑽旈崨顔规嫽婵炶揪绲介幉锟犲箚閸喍绻嗘い鎰剁稻鐏忥附鎱ㄦ繝浣虹煓鐎规洜鍠栭、姗€鎮㈠畡鎵搸濠电姷鏁告繛鈧繛浣冲浂鏁勯柛鈩冭泲婢舵劕閱囬柣鏃囨椤旀洟姊洪悷鎵憼缂佽鍊块幊婊嗐亹閹烘挾鍘遍梺瑙勫礃瀹曠敻鎮鹃悜妯诲弿濠电姴瀚崝瀣箾绾板彉閭鐐茬Ч椤㈡岸宕ㄩ褎绮撳缁樻媴娓氼垳鍔搁梺鎸庢磸閸婃洟鈥﹂崶顒€鐏抽柟棰佺濞堛劑鏌ｉ悩鍙夊缂佷焦娼欏嵄闁割偁鍎查悡蹇涚叓閸ャ劍绀€鐎涙繈鎮楃憴鍕碍婵☆偅绻傞～蹇撁洪鍜佹濠电偞鍨兼禍顒勫礉閹间焦鈷戠紒瀣硶閸戝綊鏌涘Δ浣糕枙妤犵偛锕ら…銊╁醇椤愶絾娅嗛梻浣告啞濞插繘宕濆澶婃闁逞屽墴濮婄粯鎷呴搹鐟扮闂佸憡姊归悧鐐哄Φ閹版澘绀冩い鏃囧亹閻ｆ椽姊洪悷閭﹀殶濠殿噣顥撴竟鏇熺附閸涘﹤浠梺鎼炲労娴滄粓鎯冮崫鍕电唵鐟滃骸煤濮椻偓婵＄敻宕熼锝嗘櫇闂侀潧绻堥崹濠氼敊閸ヮ剚鐓熼柟鎯у船閳ь剚鐗犳俊鐢稿礋椤斿墽鏉搁梺鍦亾閸撴碍瀵奸埀顒佷繆閻愵亜鈧牠寮婚妸銉冩椽顢橀姀鐘烘憰闂佺粯鏌ㄩ崥瀣吹瀹€鍕厽婵°倐鍋撻柣妤€妫楅埥澶庮槾缂佽鲸鎸婚幏鍛存偡閹殿喚銈烽梻浣告贡閳峰牓宕戦崟顐ゆ殼闁告洦鍨遍埛鎴︽煕閹炬潙绲诲ù婊勭墵閺屾稒鎯旈姀銏犲绩闂佺硶鏅滈惄顖炵嵁鐎ｎ喗鍊烽柣銏☆問閸熷酣姊绘担鍝勫付闁靛牊鎮傝矾闁稿瞼鍋涢崥瑙勭箾閸℃ê濮︽繛鍫滅矙閺岋綁骞囬鐔虹▏缂備焦銇嗛崨顖滐紲闁哄鐗勯崝灞矫归鈧弻鐔兼惞椤愩倗鐓夊┑鈽嗗亜閸燁偊鍩ユ径濞㈢喓绱掑Ο鐑樼暭闂傚倷娴囬褍顫濋敃鍌︾稏濠㈣泛鈯曢崫鍕庣喐绗熼娑樼槣濠电偛顕慨鎾敄閸涙潙鍙婇柕澶嗘櫆閻撳啰鎲稿鍫濈婵娉涙闂佸憡娲﹂崹鎵不瀹曞洠鍋撻獮鍨姎妞わ缚鍗抽、鎾诲冀閵娧咁啎闁诲孩绋掗…鍥儗鐎ｎ剛纾兼い鏃囧Г瀹曞瞼鈧鍠栭…鐑藉箖閵忋倖鍋傞幖瀛樼箘閻愬﹪姊绘担鍛婂暈婵炶绠撳畷婊堟晝閳ь剝鐏嬮梺缁樺姇椤曨厾绮绘ィ鍐╁€垫繛鎴炵懐閻掍粙鏌ｉ鐔风缂佽鲸甯￠幃鈺佺暦閸パ€鍚傛俊鐐€ら崑鍕崲閹邦喖寮叉俊鐐€曠换鎰偓姘间簽濡叉劙宕奸弴鐔叉嫼闂佸憡绋戦敃銉﹀緞閸曨垱鐓曟俊顖涗航閸嬨垽鏌涢埡鍌滄创鐎规洖銈告俊鐑芥晜鐟欏嫬顏归梻鍌欑閹诧紕绮欓幋锔芥櫇闁靛／鍌滃墾婵炲鍘ч悺銊╂偂閻斿吋鐓熼柡鍐ｅ亾婵炲吋鐟╁畷婵嗩潩閼哥數鍘介梺鎸庣箓濞诧箓寮抽鍌楀亾鐟欏嫭绀堥柛鐘崇墵閵嗕礁鈽夊Ο閿嬵潔闂佸湱鍎ら幐鎼侇敂瑜版帗鈷掗柛灞剧懅椤︼箓鏌熺拠褏纾跨紒顔界懇楠炲鏁傞懞銉︾彇闂備焦瀵ч弻銊︽櫠閻ｅ苯顥氶柤鎭掑劜閸欏繑淇婇姘变虎闁绘挻鍔欓弻锝夊箻鐎涙顦板Δ鐘靛仦閻楁顭囪箛娑樼鐟滃繘鏁嶉悢鍏尖拺闁圭娴烽埥澶岀磼婢跺灏﹂柍銉閹瑰嫰濡搁敃鈧弸鍌炴⒑閸涘﹥澶勯柛鎾寸洴钘濋柕濞у懐锛濇繛杈剧悼椤牓鍩€椤掆偓濠€閬嶅极椤曗偓閹瑩宕崟顓炲Е婵＄偑鍊栫敮鎺楁晝閿斿墽鐭撻梻鍫熻€介悷閭︾叆闁告侗鍘哄▽顏勵渻閵堝啫濡搁柛搴ㄦ涧閻ｇ兘宕奸弴銊︽櫌婵炶揪绲藉鍓佲偓姘冲亹缁辨捇宕掑顑藉亾閻戣姤鍊块柨鏇炲€归弲顏勨攽閻樻剚鍟忛柛鐘崇墵閹勭節閸曨剙搴婂┑鐐村灟閸ㄥ湱绮堥崒鐐寸厾婵炴潙顑嗗▍鍡涙煕閿濆嫬宓嗛柡宀嬬畱铻ｉ柣鎾冲閻忓牓姊虹拠鈥虫灍妞ゃ劌锕顐﹀箛椤撶喎鍔呴梺鐐藉劥鐏忔瑩骞愭径濞炬斀闁绘劘灏欓幗鐘电磼椤旇偐肖闁告帗甯￠獮妯肩磼濡桨绨垫俊鐐€栭崝褏绮婚幋锔藉€峰┑鐘叉处閻撳繐鈹戦悩鑼闁伙綀浜惀顏堝级鐠恒剱褎鎱ㄦ繝鍐┿仢闁硅櫕鐗犻崺鈩冪節閸曨偄歇缂傚倸鍊搁崐鍝ョ矓閹绢喗鏅濇い蹇撳閸ゆ洟鎮归崶褎鈻曢柛姘儏椤法鎹勬笟顖氬壈闂佽皫鍐仾缂佺粯绻堟慨鈧柨婵嗘噽閸橆偊鏌﹂崘顔绘喚闁哄苯绉堕幏鐘绘嚑椤掆偓椤ｆ椽鏌х紒妯煎⒌闁哄矉绲介～婊堝焵椤掆偓椤洩顦崇紒鍌涘浮閺佸啴宕掑☉姘箺闂備胶绮弻銊ヮ嚕鐠鸿　鏋嶉柛娑樼摠閻撶喖鏌ㄥ┑鍡樺櫣婵℃彃顭烽幗鍫曟晲閸℃瑧顔曢梺绯曞墲閻熴儲绂嶆ィ鍐╊棄閻庯綆鍠楅埛鎺楁煕鐏炲墽鎳呮い锔肩畵閺岀喓鎷犺缁♀偓閻庤娲滈、濠囧Φ閹版澘绠抽柟瀵稿Х閺嬪啴姊绘担绛嬫綈鐎规洘锕㈤、姘愁樄闁诡喒鈧剚娼ㄩ柍褜鍓熷濠氭偄閸涘﹦绉舵俊銈忕到閸燁垶顢撳澶嬧拺缂佸灏呴崝鐔兼煕韫囨棑鑰挎鐐插暣閹兘骞婃繝鍐┿仢妞ゃ垺妫冨畷鍗炩枎閹寸姴鐐婇梻鍌氬€峰ù鍥ь浖閵娧呯焼濞撴埃鍋撻柟顔矫埞鎴犫偓锝庝簽閸樻挳姊虹涵鍛涧闂傚嫬瀚板畷鎰槹鎼存ê浜鹃柣鐔告緲椤ュ繘鏌涢悩鎰佹畷闁哄懌鍎遍埞鎴︽偐閸偅姣勯梺绋款儐缁嬫垿顢氶敐澶婄濞达絿顭堥悘濠囨⒑鐟欏嫬鍔ょ痪缁㈠弮瀵娊鏁傞懞銉ュ伎濠碘槅鍨辩€笛呮兜閸撗呯＜闁绘ê鍟块埢鏇㈡煛瀹€鈧崰鎾诲焵椤掍胶鈯曢拑閬嶆煃闁垮濮嶉柡宀嬬稻閹棃鍩ラ崱娆忔倯婵犳鍠栭敃銊モ枍閿濆绠熼柟缁㈠枛缁€瀣亜閹扳晛鐏╃悮妯肩磽閸屾瑧顦﹀褌绮欓幖瑙勬償閵娿儳鐓戦梺鍛婂姦閸樹粙藟閵堝鈷掑〒姘ｅ亾婵炰匠鍡楊杺闂備礁鎼幊蹇曞垝閹捐鏄ユ繛鎴欏灩缁狅綁鏌ㄩ弮鍌涙珪闁告ɑ鍎抽埞鎴︽倷鐎涙绋囧銈嗗灥濡繂顕ｉ幆鑸汗闁圭儤鎸鹃崢鐢告⒑閸涘﹤鐏熼柛濠冾殘瀵囧焵椤掑嫭鈷戦柛婵嗗濠€浼存煟閳哄﹤鐏﹂柣娑卞枛铻ｉ柣鎾冲瘨濡粓鏌ｆ惔顖滅У濞存粏娉涜灋闁绘柨鍚嬮悡鐔兼煟閹邦剦鍤熸い锝嗙叀閺岋綁鎮㈤崣澶嬬彋闂佺粯渚楅崳锝咁嚕娴犲鈧牠濡烽妷鈺佸及濡炪們鍨洪〃濠囧春閳ь剚銇勯幒宥嗩樂缂佽妫楅湁闁绘ê妯婇崕鎰版煟閹惧啿鏆ｆ慨濠冩そ瀹曞綊顢氶崨顓炲闂備浇顕ф蹇曠不閹捐钃熼柣鏂挎憸閻熷綊鏌涢…鎴濇灈妞ゎ偄娲铏规嫚閳ヨ櫕鐏撻梺绋跨箲閿曘垽鐛崘顓ф▌閻庤娲栭妶鎼佸箖閵忋垻鐭欓幖瀛樻尭娴滃墽鈧懓瀚竟瀣绩娴犲鐓熸俊顖涙た閸熷繘鏌￠崱鈺佺仸闁哄苯绉烽¨渚€鏌涢幘瀵告创鐎规洘鍨挎俊鎼佸煛娴ｇ尨绱遍梻渚€娼х换鍫ュ磹閺嶎厽鍋傛繛鍡樺姂娴滄粓鏌￠崘銊モ偓濠氬箺閸屾稓绠鹃柛顐ゅ枑閳锋劙鏌曢崶褍顏い銏℃礋閺佹劙宕堕埡鍐╂緰闂傚倷娴囬鏍窗閹烘绀堟繝闈涱儏缁犳岸鏌￠崘銊у闁绘挶鍨介弻宥堫檨闁告挾鍠栭悰顔跨疀濞戣鲸鏅濋梺鎸庢⒒閺咁偊宕㈡禒瀣厵闁稿繗鍋愰弳姗€鏌涙繛鍨偓鏇⑩€﹂崶顒€绠涙い鎾跺Х椤旀洟姊洪崨濠勬噧妞わ箒浜划濠氭倷閻戞鍙嗗┑鐘绘涧閻楀棙绂掗敂閿亾閸偅绶查悗姘煎墴閹儳鈹戠€ｎ亞鍔﹀銈嗗笒鐎氼參宕曞Δ鈧…鍧楁嚋闂堟稑顫嶉梺缁樻尰閻熲晠寮婚敐澶婄闁绘劕妫欓崹鍧楀箖閳ユ枼妲堥柕蹇ョ磿閸橀亶鏌ｆ惔顖滅У闁稿鎳庨悾宄扮暆閸曨剛鍘告繛杈剧悼閹虫挻鎱ㄩ崼銉︾厵妞ゆ牗绋掗悡銉╂煃鐟欏嫬鐏寸€规洜鍘ч埞鎴﹀幢濡吋顫滄繝鐢靛Х椤ｎ喚妲愰弴銏犵；闁硅揪绠戠壕褰掓煙鏉堝墽鐣辩痪鎯ф健閺屻倗鍠婇崡鐐差潽閻庤娲橀悡锟犲蓟濞戞鏆嗛柍褜鍓熷畷鎴﹀箛閺夎法鍔﹀銈嗗笂閻掞箓藟閸懇鍋撶憴鍕闁挎洏鍨介妴浣糕枎閹惧啿绨ユ繝銏ｎ嚃閸ㄦ澘煤閿曞倹鍋傞柡鍥ュ灪閻撳啴鏌嶆潪鎵槮鐟滈绶氶弻鐔告綇閸撗呮殸缂佺偓鍎冲锟犵嵁閺嶎偄鍨濋悷娆忓閳ь剙妫濋弻锟犲焵椤掍胶顩烽悗锝庡亞閸樹粙姊虹憴鍕棆濠⒀勵殔閳藉顦归柟顔荤矙椤㈡稑鈹戦崱娆忓缚缂傚倷鑳剁划顖滅矙閹炬枼妲堥柛顭戝亽濡插綊骞栨潏鍓ф偧婵℃彃娲弻锝嗘償閵堝孩缍堝┑鐐插级閿氭い顏勫暞缁傛帞鈧綆浜濆Σ顒勬⒑闁偛鑻晶顖炴煏閸パ冾伃妤犵偞甯掗鍏煎緞鐎ｇ鍋撻弽銊х閻庢稒顭囬惌瀣磼椤旇姤宕岀€殿喖顭烽幃銏ゆ偂鎼存繄鐐婇梻浣告啞濞诧箓宕滈敃鈧灋闁绘劕顕粻楣冩倵濞戞瑯鐒介柣顓熷笧缁辨帡鎮╁畷鍥р拰閻庢鍠栭…鐑藉极閹版澘骞㈡俊顖氭惈婵℃娊姊绘笟鈧褏鎹㈤崱娑樼疇闁搞儺鍓欓崙鐘绘煛閸愩劎澧涢柍閿嬪灴閺屾稑鈹戦崱妤婁痪闂侀潻缍€濡嫰鍩為幋锔藉€烽柍杞版婢规洟姊婚崒娆掑厡缂侇噮鍨辩粭鐔肺旈崨顓㈡７闂佹寧绻傞幊鎰板汲閿曞倹鐓曟俊銈呭暙娴滆淇婇幓鎺斿濞ｅ洤锕、娑樷攽閸℃洘鐫忔繝鐢靛仧閸樠囁囬棃娑辨綎缂備焦蓱婵挳鎮峰▎蹇擃仼濞寸姭鏅犲铏圭矙閸喚妲伴梺闈╃秶缁蹭粙顢氶敐澶婄闁瑰搫妫欓弬鈧梺璇插嚱缂嶅棙绂嶉悙鎼闁搞儺鍓氶埛鎴犳喐閻楀牆绗氶柨娑氬枛閺岋綁骞掗悙鐢垫殼闂佽鍣换婵嬪箖閵忋倖鍋傞幖杈剧秵閸熷洭姊绘担鍛婅础闁冲嘲鐗撳畷銏＄附閸涘﹤鈧爼鏌ㄩ悢鍝勑ｉ柣鎾冲暟閹茬顭ㄩ崼婵堫槯濠电偛妫欓幐鍝ュ閸ф鈷掗柛顐ゅ枔閵嗘帡鏌￠崱顓㈡濞ｅ洤锕、娑樷槈閸楃偛濡兼繝寰枫倕钄兼い鏇嗗洠鈧?")
        elif learner_signal == "curious":
            parts.append("濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ゆい顓犲厴瀵鏁愰崨鍌滃枎閳诲酣骞嗚椤斿嫮绱撻崒娆掑厡濠殿喗鎸抽幃妯侯潩鐠轰綍锕傛煕閺囥劌鏋ら柣銈傚亾闂備礁婀遍崑鎾诲箚鐏炶娇娑㈡倷閻㈢數锛濇繛杈剧悼閺咁偊宕奸鍫熺厱濠电姴鍟扮粻鐐碘偓娈垮枛椤兘骞冮姀銈嗘優闁革富鍘鹃崢顖炴⒒娴ｇ顥忛柣鎾崇墦瀹曟娊顢氶埀顒€鐣峰┑鍥х窞闁归偊鍘搁幏娲⒑閸涘﹦鈽夐柨鏇畵楠炲﹪宕橀鍡欙紲缂傚倷鐒﹂敃顐︽嚀鐠恒劉鍋撳▓鍨灈妞ゎ厾鍏樺顐﹀箛椤撶偟绐炴繝鐢靛Т鐎氱兘宕ラ崨瀛樷拻濞达綀娅ｇ敮娑欍亜椤撶偟澧曢柍璇茬Ч瀵挳濮€閳ュ厖鎴锋俊鐐€曠换鎰版偋婵犲洤纾归柣銏犳啞閸嬧剝绻涢崱妤冪妞ゅ浚浜幃妯跨疀閿濆懍绨界紓浣介哺鐢繝骞婂鍫燁棃婵炴垶蓱閹虫瑩鏌ｆ惔銏╁晱闁哥姵鐩、姘愁樄闁糕斂鍎插鍕箛椤掑缍傞梻浣虹帛钃遍柣妤佹崌瀹曟繂顓兼径濞箓鏌涢弴銊ョ仩缂侇偄绉归弻娑氫沪閹规劕顥濇繛瀵稿У閿氭い顏勫暣婵¤埖鎯旈垾鑼埍闂備礁鎼幊鎰叏閹绢噯缍栭煫鍥ㄦ媼濞差亶鏁傞柛鏇ㄥ墮缁佽埖淇婇悙顏勨偓鏍箰妤ｅ啫绐楅幖绮规閺嬫梻鈧厜鍋撻柛鏇ㄥ厴閹疯櫣绱撻崒娆戝妽妞ゎ厼娲﹂弲鍫曨敂閸喓鍘梺鍓插亖閸╁嫰鎮為悙顑句簻闁哄浂浜炵粙鑽ょ磼缂佹绠撴い顐ｇ箞椤㈡鍩€椤掆偓閻ｇ敻宕卞☉娆屾嫼缂傚倷鐒﹁摫妞ゃ儱妫欑换娑㈠椽閸愵亞袦闂佽鍨欢姘暦婵傜唯闁挎梻绮ˉ濠冧繆閻愵亜鈧牠宕濋幋锕€鍨傞柣鎴灻欢鐐烘煕閺囥劌骞樼痪鎯с偢閹鏁愭惔鈥茬盎濠电偞鎯岄崰妤呭Φ閸曨垰顫呴柍鈺佸暙绾板秴顪冮妶鍡樺碍闁靛牏顭堥悾鐑藉醇閺囩偟鍘搁梺鍛婂姌濞夋洟姊婚娑氱瘈闁汇垽娼ф禒鈺呮煙濞茶绨界紒杈╁仦閹峰懘鎼归崷顓ㄧ闯婵犳鍠楅敃鈺呭礈閿曞倹鍊甸柛顐ｆ礃閻撴瑩姊婚崒姘煎殶闁告柨绉归弻锝夊箻鐎涙顦伴梺鍝勬湰濞叉鎹㈠☉銏犲瀭妞ゆ梻鍘ц闂傚倷鑳剁涵鍫曞疾椤忓棗绶ら柛褎顨呴悞鍨亜閹哄秶璐伴柛鐔风箻閺屾盯鎮╁畷鍥ㄥ垱濡炪們鍨烘穱娲囪ぐ鎺撶厱闁崇懓鐏濋崝婊呪偓鍨緲鐎氼厾鎹㈠┑鍥ㄥ劅闁靛繒濮风槐锕傛⒒閸屾瑨鍏岀痪顓炵埣瀹曟粌鈹戠€ｃ劉鍋撻崘顔煎耿婵炴垶顭囬敍娆忣渻閵堝棛澧遍柛瀣仱閸╂盯骞掗幊銊ョ秺閺佹劙宕ㄩ鍏兼畼闂備礁鎽滈崰鎾诲磻濞戙垹违闁圭儤鍩堝鈺傘亜閹炬瀚弶褰掓煟鎼淬値娼愭繛鍙夌墱缁辩偞绻濋崶鈺佺ウ闁硅壈鎻徊鎸庛仚閹惰姤鍊甸柨婵嗛娴滄繃绻涢崨顔藉碍闁宠鍨块幃鈺咁敊閼测晙绱樻繝鐢靛仜椤︽壆绮欓弽銊︽珷婵犻潧顑嗛埛鎴︽偠濞戞巻鍋撻崗鍛棜婵犵數鍋涢顓熸叏閹绢噮鏁勯柛鈩冪⊕閸嬪倿鏌涢幇闈涙灍闁绘挸绻愰…璺ㄦ崉閾忕懓顣洪梺鍛婃⒐瀹€鎼佸蓟閿熺姴骞㈡慨姗嗗亜閹牏绱撴担浠嬪摵閻㈩垽绻濋獮鍐敂閸曘劍鐎婚棅顐㈡处閺屻劑藝閳哄懏鈷戠紓浣股戠亸浼存煟閻曞倻鐣靛┑锛勬暬瀹曠喖顢涘杈╂綁闂備胶顭堥張顒勬嚌閻愵剛顩锋慨妞诲亾婵﹥妞介弻鍛存倷閼艰泛顏繝鈷€灞界仸闁哄瞼鍠栭、娆撴偂鎼存ê浜鹃柛褎顨堝畵渚€鏌涢幇銊︽澓闁稿鎳橀弻娑㈠箛閵婏附鐝旈梺閫炲苯澧い顓犲厴瀵濡舵径濠勭暢闂佸湱鍎ら崹鍨叏鎼淬劍鈷戦梺顐ゅ仜閼活垱鏅堕濮愪簻妞ゆ挾濮撮崢瀵糕偓娈垮枛椤兘寮崘顔肩劦妞ゆ帒鍟版禍浠嬫⒒娴ｈ櫣甯涢柤褰掔畺椤㈡岸顢橀悩鐢电劶闂佺硶鍓濈粙鎺楀煕閹达附鐓曢柟閭﹀墮缁狙囨煙椤栨氨澧﹂柡宀€鍠栧畷姗€鎳犻鍌ゅ晪闂備浇顕栭崯鎾诲Χ閸モ晜婢戦梻浣告贡閾忓酣宕归柆宥呮闁逞屽墴濮婄粯鎷呴搹鐟扮濡炪値鍘奸悧蹇旂缁嬪簱鏋庨柟瀵稿С缁楀姊虹憴鍕姸濠殿喓鍊濋幃锟犳偄閸忚偐鍙嗗┑鐘绘涧濡稒鏅堕敃鍌涚厱婵犻潧娲﹂妵婵嬫煛鐏炵偓绀嬬€规洘鍎奸ˇ鍙夈亜韫囷絽澧扮紒杈ㄥ浮閹晛鐣烽崶銊ュ灡婵°倗濮烽崑鐐衡€﹂崶顒€绠查柛鏇ㄥ灡閹偤鏌ｉ悢鍛婄凡缂佺姷鍎ょ换婵嬫偨闂堟刀锝嗐亜閺冣偓閻楃姴鐣锋导鏉戝唨妞ゆ挾鍠愬▍鍥⒑闂堟侗妲堕柛搴℃惈閵嗘帗绻濆顓犲弮濠碘槅鍨拃锕€危濞差亝鐓涢柛鈽嗗弮濡绢噣鏌曢崶褍顏鐐叉喘瀹曟粍鎷呴悜妯活啅缂傚倸鍊风拋鏌ュ磻閹剧粯鍊甸柨婵嗛娴滄牕霉濠婂嫮鐭掗柡宀€鍠栭獮鎴﹀箛椤撶姰鈧劙姊洪崨濠冨磳濞存粌鐖煎濠氭晸閻樻彃鑰块梺瀹犳〃濡炴帡宕版繝鍌楁斀妞ゆ梻銆嬮崝鐔虹磼椤曞懎鐏︽鐐茬箻瀹曘劑寮堕幋婵堢崺濠电姷鏁告慨鎾箠閹拌埇鈧線宕ㄧ€涙ǚ鎷绘繛杈剧悼椤牓寮抽柆宥嗙厱闁靛骏绱曢崣鈧梺璇″暙閸パ咁啋閻庤娲栧ú锕€鈻撴ィ鍐┾拺闁荤喖鍋婇崵鐔兼煕鐎ｎ剙鏋旂€殿啫鍥х劦妞ゆ帒瀚埛鎴犵磼鐎ｎ偄顕滄繝鈧幍顔剧＜妞ゆ棁鍋愬瓭闂佸磭绮幐濠氬Χ閿濆绀冮柍鍦亾鐎氬ジ姊绘担鍛婂暈缂佸鍨块弫鍐晜閸撗傜瑝闂佺懓澧界划顖炲磹閸偅鍙忔慨妤€鐗忛崚鏉棵瑰鍫㈢暫婵﹦绮幏鍛村川婵犲啫鍓甸梻浣告憸閸ｃ儵宕戞繝鍥х畺鐟滄柨鐣烽崡鐐嶆梹绻濋崒娑欑彋濠电姷鏁告繛鈧繛浣冲厾娲閿涘嫷娲稿┑鐘诧工閻楀﹪鎮″☉銏＄厱闁规壋鏅涙俊浠嬫煙閸忕厧濮夐柟顕呭枛椤繈鎳滅喊妯诲缂傚倸鍊烽悞锕傗€﹂崶鈺冧笉闁靛鏅滈悡鏇㈡倵閿濆簼鎮嶉棅顒夊墰閳ь剚顔栭崰鏍€﹂悜钘夋瀬闁圭増婢橀獮銏′繆椤栨碍鎯堝┑鈩冨▕濮婄粯鎷呴崫鍕紦闂佺閰ｆ禍璺虹暦椤栫偛绠伴幖娣灮缁夊爼姊洪崨濠勨槈闁宦板姂閸╂盯骞嬮悩鐢碉紲闁诲函缍嗛崑鎺楀磿閵夆晜鐓曢幖娣灩婵秹鏌″畝鈧崰鏍箖閻戣姤鍋嬮柛顐ｇ箖閻忓酣鏌ｆ惔銏╁晱闁哥姵鐩、姘愁樄闁糕斂鍎插鍕箛椤掑缍傞梻浣虹帛椤洭寮幖浣哥骇闁归棿鐒﹂埛鎺懨归敐鍕劅闁绘帒澧界槐鎺旂磼濡搫顫掑Δ鐘靛仦椤ㄥ懘鈥﹂妸鈺侀唶婵犻潧娲ㄩ埀顒夊墴濮婃椽宕崟顔炬闁诲繒鍋為崕鎶芥儊濠婂牊鈷掑〒姘ｅ亾婵炰匠鍥ㄥ亱闁糕剝銇傚☉妯锋瀻闁规儳纾崢閬嶆⒑鐟欏嫬顥嬪褎顨婇幃锟犲即閵忥紕鍘搁梺鍛婂姧缁茶姤绂嶆ィ鍐┾拺闁煎鍊曢弳閬嶆煛閸涱垰鈻堥柟顔诲嵆椤㈡岸鍩€椤掆偓閻ｅ嘲顫滈埀顒佷繆閸涘﹥鍎熼柕蹇婃濡啴鎮楃憴鍕８闁告梹鍨块妴浣割潨閳ь剟骞冨▎鎴濇瀳婵☆垵妗ㄦ竟鏇烆渻閵堝棙灏甸柛搴㈠姇閵嗘帗绻濆顓犲帾闂佸壊鍋呯换鍐夊鍐ｆ斀妞ゆ柣鍔岄幊鎰婵傚憡鐓欑紓浣姑粭姘舵煕鐎ｃ劌鍔ら柍褜鍓濋～澶娒哄鈧幃鐑藉煛閸涱厽鐎梺鐟板⒔缁垶宕戦幇鐗堢厸闁稿本锚閸旀粓鎮楀鍐蹭汗缂佽鲸鎹囧畷鎺戭潩椤戣棄浜鹃柣鎴ｅГ閸婂潡鏌ㄩ弴鐐测偓褰掑疾濠靛鐓冮弶鐐村椤斿鏌＄€ｎ偅顥堥柡宀嬬節瀹曟﹢鏁愰崨顒€顥氭繝鐢靛剳缁茶棄煤閵堝鏅濇い蹇撶墑閳ь兛绶氬鎾閳╁啯鐝抽梻浣规偠閸庮噣寮插┑瀣辈妞ゆ劏鎳囬弨浠嬫煟閹存繃宸濋柛鎺斿缁绘稓浠﹂崒姘ｅ亾濠靛鏋侀柛鎰靛櫘閺佸倿鏌涢锝囩畼闁汇倕娲ら埞鎴︽偐鐠囇冧紣闂佺粯顨呴敃顏勭暦閹达箑惟闁挎柨澧介鏇㈡⒑閸撴彃浜為柛鐘查叄椤㈡艾顭ㄩ崨顖滐紲婵炴挻鑹惧ú銈嗙閻楀牊鍙忓┑鐘叉噺椤忕娀鏌熸搴♀枅妤犵偞鎹囬獮鎺楀箣閻愬灚袠缂傚倸鍊搁崐鎼佸磹閸濄儳鐭撻柡澶嬪殾濞戞ǚ鏀介柛鈩冪懄濞堥箖姊虹涵鍛涧缂佺姵鍨甸蹇撯攽閸ャ儰绨婚梺瑙勫劤椤曨參鍩婇弴銏＄厽閹兼番鍨洪妵婵囨叏婵犲啯銇濈€规洦鍋婂畷鐔碱敇濞戞瑧鈧亶姊绘担鍛婂暈閻绱掗鐣屾噰妤犵偛鍟撮弫鎾绘偐閸愯弓绨婚梻浣稿悑缁佹挳寮插☉婧夸汗闁告洦鍨遍埛鎴︽煙閼测晛浠滈柛鏃€锕㈤弻娑㈠棘鐠恒剱銈囩磼椤旇偐澧﹂柛鈹惧亾濡炪倖甯婇懗鍓佺不妤ｅ啯鍊甸柣銏☆問閻掑墽鎮妷鈺傗拺闁告繂瀚崳钘夆攽閻愨晛浜鹃柣搴㈩問閸犳盯顢氳閸┿儲寰勬繝搴㈠兊闂佹寧绻傞幊宥嗙珶閺囥垺鈷戦柟绋挎捣缁犳挸螖閻樺弶鍟炵紒鍌氱Т椤劑宕橀敐鍡樻澑婵＄偑鍊栧濠氬煕閸惊锝夋惞閸︻厾锛滈柡澶婄墑閸斿苯霉椤斿浜滈柕蹇ョ磿閹冲洭鏌熼鐓庘挃濞寸媴绠撻獮鍡氼槼闁绘繍鍣ｅ濠氬磼濞嗘埈妲紓鍌氱Т閿曨亣妫㈤梺瑙勫劤閻°劑宕ｈ箛娑欑厵缂備降鍨归弸鐔虹磼閻樺啿娴慨濠呮閹风娀骞撻幒鎴炵槪缂傚倸鍊哥粔鏉懳涘┑鍡欐殾闁硅揪绠戠粻鎶芥煙閹碱厼骞橀柛鏃傚厴濮婃椽宕崟顐ｆ闂佺粯顨呴敃顏堝春濞戙垹绠抽柟鐐藉妼缂嶅﹪寮幇鏉垮窛妞ゆ柨鍚嬪▓姗€姊绘担绛嬪殐闁搞劋鍗抽幃褔骞樼拠鑼舵憰濠电偞鍨崹娲磻閸℃褰掓晲婢跺鐝抽梺鍝ュТ閿曨亪骞冨Δ鍐╁枂闁告洦鍓涢ˇ銊╂⒑閸涘﹥鈷愰柣鐔叉櫊閹即顢氶埀顒€顕ｆ禒瀣╅柨鏇楀亾妞ゅ孩鎸剧槐鎾存媴閸撴彃鍓伴梺璇茬箲缁诲倿鍩㈤幘璇参ч柛鈩冪懅閻﹀牓姊哄Ч鍥х伈婵炰匠鍕浄婵犲﹤瀚换鍡樸亜閹板墎鎮奸柟鍐叉川閳ь剝顫夊ú妯兼崲閸儳宓侀悗锝庡枟閸婇攱绻涢崼鐔奉嚋闂佽￥鍊栫换婵嬫偨闂堟刀銏ゆ煥閺囨ê鈧繈骞冭缁绘繈宕堕妸銉ょ暗闂備礁鎲￠崝锕傚窗濡ゅ懏鍋傞柡鍥╁枔缁♀偓闂傚倸鐗婄粙鎺椝夊鍕╀簻闊洦姊圭亸锕傛煛鐏炲墽鈯曢柟顖涙婵偓闁绘ê鍚€缁辨繈姊绘担鍛婃儓闁活厼顦辩槐鐐寸瑹閳ь剙顕ｉ锕€绠涢柡澶婄仢缁愭稑顪冮妶鍡欏闁荤啙鍕╀粴闁规儼濮ら埛鎺戙€掑锝呬壕闂侀€炲苯澧紒瀣崌閸╃偤骞掑Δ浣哄幈闂佸搫鍊藉▔鏇″€撮梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼存繄鏁栭梺鎸庣⊕缁矂鍩為幋锕€鐓￠柛鈩冾殘娴犳潙鈹戦埄鍐︿粻闁告梹鍨甸悾宄邦潩鐠鸿櫣顔婂┑掳鍊撻懗鍫曞储娴犲鐓欓柛蹇氬亹閺嗘﹢鏌涙繛鍨偓鏇⑩€﹂崶顒€绠涙い鎾跺Х椤旀洖鈹戦悙瀛樼稇妞ゆ垵妫楅埢宥夊炊閳规儳浜鹃柛顭戝亝缁舵煡鏌ㄩ弴銊ら偗闁绘侗鍣ｅ畷鍗烆潩閸忕⒈鈧洭姊绘担瑙勫仩闁稿﹥鐗犻妴鍐╃節閸パ嗘憰濠电偞鍨崹褰掑础閹惰姤鐓忓┑鐐茬仢閸旀鏌涚€ｎ偅宕岄柟顔规櫇缁辨帒螣鏉炴壆鐩庨梻鍌欒兌缁垶骞愰崫銉ㄥС闁兼祴鏅滈～鏇㈡煕椤愶絾绀冮柍閿嬪灴閺屾稑鈽夊鍫熸暰缂備讲鍋撻柍褜鍓熷铏规嫚閼碱剛顔夐悗鍏夊亾婵繂鏈敍鍌炴⒒娓氣偓濞佳囨偋閸℃蛋鍥ㄥ閺夋垹鍘遍梺鍦劋椤ㄥ棝鎮￠弴銏″€堕柣鎰綑缁€鍐熆鐟欏嫸鑰块柡灞界Х椤т線鏌涢幘瀵告噰鐎规洘鐓″濠氬Ψ閿斿墽鏆㈤梻鍌氬€烽悞锕傚箖閸洖纾挎繝濠傜墕瀹告繃銇勯弮鍌滄憘闁哥喎閰ｅ濠氬磼濞嗘垵濡介梺娲讳簻缂嶅﹤鐣风憴鍕瘈婵﹫绲洪崑鎾绘晝閸屾岸鍞堕梺闈涚箳婵厼螞濠婂懐纾介柛灞剧懅閸斿秵銇勯鐐村窛缂侇喚绮妶锝夊礃閳哄啫骞嶉梺璇叉捣閺佹悂鈥﹂崼銉ョ闂侇剙绉甸悡鐔兼煙閻戞ê鐏﹂柛鐔哄仧缁辨帞绱掑Ο鍏煎垱濡ょ姷鍋涢澶愬箖濠婂牆鐐婇柨鏃€宕樼换鎴︽⒒閸屾瑨鍏岀紒顕呭灦楠炴劙宕奸弴鐐碉紵闂佹眹鍨婚…鍫ユ嫅閻斿摜绠鹃柟瀛樼懃閻忊晠鏌ｉ幘鍗炵伈闁哄苯绉烽¨渚€鏌涢幘璺烘瀻妞ゆ洩缍侀獮鎾诲箳濠靛牆寮抽梻浣告啞閸旀洟宕婊勬殰婵°倕鎳庣粻姘舵煛閸愩劎澧曢幆鐔兼⒑閹稿孩顥嗘い顐㈩槺閳ь剚鐭划娆忣潖缂佹ɑ濯村〒姘煎灣閸旀悂姊洪崫鍕⒈闁告挾鍠栭獮鍐偪椤栵絾鈻岄梺鑺ド戠换鍫ュ蓟閵娾晛鍗抽柣鎰ゴ閸嬫捁銇愰幒鎾充簵濠电偛妫欓幐濠氬磻閿濆鐓曢柕澶堝劜閹兼劙鏌熼搹顐㈠闁诡垯绶氬畷濂稿Ψ閿旇瀚奸梺鑽ゅТ濞茬娀鍩€椤掑啯鐝柣蹇旀崌濮婅櫣绮欑捄銊ь唹闂佹寧娲忛崹褰掝敋閿濆鏁冮柨鏇楀亾缂佲偓閸愨斂浜滈柡鍐ㄦ搐娴滃綊鏌ㄥ☉娆戠煀闁宠鍨块、娆撳棘閵堝嫮杩旈梻浣告啞閹稿鎯勯鐐叉槬闁逞屽墯閵囧嫰骞掗幋顓熜﹂悗娈垮櫘閸犳骞堥妸锔剧瘈闁告劏鏂傛禒銏ゆ倵鐟欏嫭绀冪紒顔芥崌閻涱噣骞樼拠鑼唺閻庡箍鍎卞ú銈夊吹椤掆偓閳规垿鎮╅崹顐ｆ瘎闂佺顑嗙粙鎴︻敋閿濆閱囬柡鍥╁枎娴滈亶姊洪崫鍕窛闁哥姵鍔曢埢宥堢疀濞戞瑢鎷绘繛杈剧到閹诧繝骞嗛崼銉﹀仩婵鍘ф禍鎵偓瑙勬礃濞叉ê顭囪箛娑樼厸闁告剬鍛喒闂備浇宕甸崰鎰版偡閵壯€鍋撳鐓庢灓缂侇喚绮妶锝夊礃閳哄啫寮虫繝鐢靛█濞佳兾涘┑瀣垫晛婵°倐鍋撴い顓″劵椤т線鏌涢悩宕囧⒌闁糕晝鍋ら獮瀣晝閳ь剟鎮橀幎鑺ョ厱闁归偊鍓欑痪褔鏌涙繝搴＄仩闁?")
        else:
            parts.append("濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ゆい顓犲厴瀵鏁愰崨鍌滃枎閳诲酣骞嗚椤斿嫮绱撻崒娆掑厡濠殿喗鎸抽幃妯侯潩鐠轰綍锕傛煕閺囥劌鏋ら柣銈傚亾闂備礁婀遍崑鎾诲箚鐏炶娇娑㈡倷閻㈢數锛濇繛杈剧悼閺咁偊宕奸鍫熺厱濠电姴鍟扮粻鐐碘偓娈垮枛椤兘骞冮姀銈嗘優闁革富鍘鹃崢顖炴⒒娴ｇ顥忛柣鎾崇墦瀹曟娊顢氶埀顒€鐣峰┑鍥х窞闁归偊鍘搁幏娲⒑閸涘﹦鈽夐柨鏇畵楠炲﹪宕橀鍡欙紲缂傚倷鐒﹂敃顐︽嚀閹稿寒娈介柣鎰絻閺嗘瑩鎽堕弽顓熺厱婵炴垵宕▍妯讳繆椤愩垹鏆欓柍瑙勫灴閹瑩寮堕幋鐘辨闂備浇宕甸崳锔剧不閹惧磭鏆﹀ù鍏兼綑缁犳稒銇勯弬鍨挃闁挎稒绻冪换娑欐綇閸撗吷戦悷婊勬緲閸燁垳绮嬪澶嬪€锋い鎺戝€婚惁鍫ユ⒑濮瑰洤鐏叉繛浣冲啰鎽ュ┑鐘垫暩閸嬬娀顢氬鍛笉闁规儳纾弳锕傛煙閹殿喖顣奸柛瀣ㄥ姂閺屾稑鈽夊鍫濆闂佸憡鐟ュΛ妤呭煘閹达附鍋愮紓浣股戦柨顓炩攽閳藉棗浜濈紒璇茬墦閵嗕線骞樺鍕瀹曘劑顢欓幆褍绠伴梻浣筋嚙閸戠晫绱為崱娑樼；闁糕剝绋戣繚闂佸湱鍎ゅ鑽ゅ婵傜绾ч柛顐ｇ☉婵″吋绻涢幖顓炴珝闁哄本鐩崺鐐哄箚瑜屾竟鏇炩攽閿涘嫬浜奸柛濠冪墱閺侇噣骞掗弬鍝勪壕婵鍘ф晶鎾煛鐏炵瓔鍎旂€规洖鐖奸、妤佹媴閸濆嫬绗氶梻鍌欑劍閹爼宕濆鍥╃煓闁圭儤鍨熼弸宥夋煕濞戝崬濮搁柣鐔煎亰閻撱儵鏌涘☉鍗炲箳濠㈣娲栭—鍐Χ閸愩劌惟闂佺娴烽弫濠氱嵁閸愩劉鏋庨柟鐐綑濞堛倕顪冮妶鍡楃伇闁稿氦顕ч‖濠囧箹娴ｅ厜鎷绘繛杈剧到閹诧繝宕悙瀛樺弿濠电姴鍊圭拹锟犳煕閻樿宸ユい鎾炽偢瀹曞爼濡搁妷銉у搸濠电姷鏁搁崑鐐哄垂閸撲礁鏋堢€广儱娲犻崑鎾愁潩椤撶喓娈ら梺鐟板级閻℃洜绮诲☉妯锋婵炲棗绻嬮幃锝夋⒒娴ｅ湱婀介柛銊ョ秺楠炲鏁撻悩鍐蹭簵濠电偛妫欓崝鎴炵濠婂牊鐓涢柛銉厛濞堟柨霉濠婂啫鈷旂紒杈ㄦ尰閹峰懘宕崟鎴秮閺岋絽螖閸愩剱銏°亜閺囶亞绋荤紒缁樼箓椤繈顢楅埀顒勬嚀閸喒鏀介幒鎶藉磹閺囥垺鏅濋柕鍫濐槸缁犳牠鏌熸潏楣冩闁抽攱鍨圭槐鎺楊敍濞戞瑧顦ユ繝鈷€鍕弨闁哄矉缍侀幃銏ゅ级閹存繂袝闂備胶绮笟妤呭窗閺嶎収鏁囬柛蹇曞帶缁剁偤鎮楅敍鍗炲椤忕儤绻濋悽闈涗哗闁规椿浜炲濠囧锤濡や礁浠遍梺鍝勫暙閻楀棝宕ヨぐ鎺撶厱闁逛即娼ч弸鐔兼煟閹惧瓨绀冨ǎ鍥э躬椤㈡稑顫濋浣糕偓顖氣攽閻愬弶鍣烘繛鑼枛瀵鍩勯崘顏嗘嚌闂佹悶鍎滈崟顓炵秵濠德板€楁慨鐑藉磻閻愬灚鏆滈柨鐔哄Х瀹撲焦鎱ㄥ璇蹭壕閻庢鍠栭悥濂哥嵁鐎ｎ亖鏀介柛娑卞灣椤︿即姊婚崒姘偓鎼佸磹妞嬪孩顐芥慨妯挎硾閻掑灚銇勯幒鎴濃偓鍛婄濠婂牊鐓犳繛鑼额嚙閻忥繝鏌￠崨顓犲煟妤犵偛绉归、娆撳礈瑜濈槐鏌ユ⒑閸濆嫷妲搁柣妤€瀚板畷婵嗩吋閸ワ妇鍓ㄦ繛瀵稿帶閻°劑鎮″▎鎴斿亾閻熸澘顏褎顨婂畷鐢稿炊椤掍胶鍘甸梺缁樻尭濞撮绮斿ú顏呯厵妞ゆ梹鍎抽崢瀛橆殽閻愯尙效妞ゃ垺宀稿畷銊╊敇濠靛﹦绠烽梻鍌氬€搁崐鎼佸磹閹间礁纾归柣鎴ｅГ閸婂潡鏌ㄩ弮鍫熸殰闁稿鎸剧划顓炩槈濡搫绠绘俊銈忕畳濞夋洟鎮块埀顒€鈹戦悙鏉戠仸闁挎岸鏌ｆ惔顔煎箺缂佺粯绋撻埀顒傛暩椤牆鐡俊鐐€栭崹闈浢洪妶澶嬪仼闁割煈鍋呮刊瀵哥磼椤栨稒绀冮柡鍌楀亾闂傚倷鑳剁划顖炴晪閻庢鍠涢崺鏍ь嚗閸曨垰绀嬫い鏍ㄧ〒閸樿鲸绻濋悽闈浶㈤悗姘煎墴瀹曘垽骞橀鐣屽幐闁诲繒鍋涙晶浠嬪煡婢舵劖鐓冮悷娆忓閻忓鈧娲栧畷顒冪亙婵犵數濮抽懗鍓佸婵犳碍鈷掗柛灞剧懅閸斿秹鎮楃粭娑樻噽閻瑩鏌熼悜妯荤叆闁搞劍绻勯埀顒€鍘滈崑鎾绘煕閺囥劌浜為柛妯绘尦濮婅櫣娑甸崨顔兼锭闁诲酣娼ч惌鍌氼嚕椤愶絿绡€闁搞儯鍔庨崢钘夘渻閵堝棙瀵欓柛鎰屽棗鐒绘繝鐢靛仜閻°劎鍒掗悩宕囶洸婵犲﹤鐗婇崑鈺呮煟閹达絾顥夐崬顖炴偡濠婂喚妯€鐎规洘鍨块獮妯肩磼濡粯鐝抽梺纭呭亹鐞涖儵宕滃┑瀣仧妞ゆ洍鍋撴慨濠勫劋濞碱亪骞嶉鍛滄繝鐢靛仜閻即宕愬☉銏″€堕柛鎰靛枟閳锋垿鏌熺粙鎸庢崳缂佺姵鎹囬弻鐔煎礃閺屻儱寮伴悗娈垮枟婵炲﹪骞冨▎鎾村€绘俊顖滃帶鐢姊婚崒娆戭槮闁诲繑绻堥、鏍川鐎涙ê鈧爼鏌熺紒銏犳灍闁绘挻鐩幃姗€鎮欓幓鎺嗘寖闂佸疇妫勯ˇ鐢稿蓟瀹ュ洦鍠嗛柛鏇ㄥ亞娴煎矂鎮楃憴鍕鐎规洦鍓濋悘鍐╃節閻㈤潧小闁绘帪绠撳畷鎴﹀川椤撴稒鏂€闂佹寧绋戠€氼剚绂嶆總鍛婄厱濠电姴鍟粈鍫ユ煙楠炲灝鐏叉鐐差儔閺佸啴鍩€椤掑倻涓嶅ù鐓庣摠閻撴瑩鏌熼婊冾暭妞ゃ儱顦甸弻锕傚礃椤忓嫭鐎剧紓浣虹帛閻╊垶鐛€ｎ亖鏋庨煫鍥ㄦ磻閹綁姊虹拠鈥崇仯闁哥姵鐗曢～蹇撁洪鍜佹濠电偞鍨电壕顓犳兜閳ь剟姊绘担鍛婂暈婵炶绠撳畷銏ゅ箹娴ｅ摜锛涢梺鍦亾濡炲潡寮€ｎ喗鐓冪憸婊堝礈閻旇偐宓侀柛鎰╁妿閺嗗姊洪銊ヮ洭闁告瑥妫濆娲川婵犲啫顦╅梺鍛婃尰閻╊垰鐣峰▎鎾存櫢闁绘ɑ鏋奸幏娲⒑閸︻収鐒鹃悗娑掓櫆瀵板嫰宕熼鈧悷閭︾叆闁告洦鍘鹃悡澶愭⒑閹稿海绠橀柛瀣Х缁鈽夊Ο閿嬵潔濠碘槅鍨板﹢閬嶆倷婵犲洦鈷掑ù锝呮啞閸熺偞绻涢崣澶涜€跨€规洜鏁婚、鏃堝醇濠靛牆鈧偤鎮峰鍐鐎规洘鍔欓幃娆撴倻濡桨鐢绘繝鐢靛Т閿曘倝宕悧鍫熸珡闂傚倷鑳堕崑銊╁磿閺屻儲鍋嬮柣妯垮皺閺嗭箑鈹戦崒婊庣劸閸烆垶姊洪幐搴⑩拹闁稿孩濞婇悰顔嘉旈崨顔规嫼闂佽崵鍠愬姗€骞冮幋锔界厽闁挎繂绨奸柇顖溾偓瑙勬礀缂嶅﹤鐣峰Δ鍛殐闁冲搫鍟鍕節濞堝灝鏋熼柕鍥ㄧ洴瀹曟垿骞樼紒妯煎幐閻庡厜鍋撻柍褜鍓熷畷浼村冀椤撶偟鐤囬梺缁樺姇閹碱偄鏁柣鐔哥矊缁绘﹢骞冮敓鐘茬劦妞ゆ帒瀚埛鎴︽煕濞戞﹩鐓繛鍫熺矊闇夋繝濠傚暟閸╋絿鈧鍠栭…鐑藉箖閵忋倕绀傞柤娴嬫櫅婵椽姊绘担鐟邦嚋婵炴彃绉瑰畷鎴﹀箻缂佹鍘卞┑鈽嗗灣缁垳浜搁敃鍌涚厸鐎光偓鐎ｎ剛鐦堥梺绯曟杹閸嬫挸顪冮妶鍡楃瑐闁煎啿鐖奸妴鍛存倻閼恒儱鈧敻鏌ㄥ┑鍡涱€楀ù婊勭矒閺屽秷顧侀柛鎾寸洴瀵偅绻濆顒冩憰闂侀潧顭堥崕顕€寮ㄦ禒瀣厱闁斥晛鍟伴幊鍐煕閵堝骸澧扮紒杈ㄦ尰閹峰懘妫冨☉姗嗙€辩紓鍌欑贰閸犳鎮烽埡渚囧殨濠电姵纰嶉弲鎻掝熆鐠虹尨鍔熸い鏃€甯″娲传閸曞灚效闂佹悶鍔忛～澶岀矉閹烘绾ч柟鎼幗鐎靛矂姊洪棃娑氬缂併劏鍋愰懞杈ㄧ節濮橆厾鍘遍梺缁樻椤ユ捇骞楅悩鐫酣宕惰闊剛鈧娲栭妶绋款嚕閹绢喗鍊烽柤鐓庣亪閸嬫捇宕归瑙勬杸闂佺粯鍔曞鍫曀夊鍕閻庢稒顭堟竟妯汇亜椤撶偞鍠橀柟顔界矒閹崇偤濡烽姀鈥愁伜婵犵數鍋犻幓顏嗙礊閳ь剚淇婇銏狀伃鐎规洏鍎撮妵鎰板箳閹捐泛骞堥梻浣虹帛閿氱€殿喖鐖艰棢闁靛繆鎳囬崑鎾舵喆閸曨剛顦ㄩ梺鍛婃⒐濞叉繈鎮橀崘顔解拺闁告稑锕ｇ欢閬嶆煕閻樺磭澧柍缁樻崌閹垽宕楃亸鏍ㄥ濠电偞鎸婚懝鎯洪妶鍡樻珷妞ゆ柨澧界壕鐓庮熆鐠轰警鐓柛銈囧枔缁辨帡顢欑喊杈╁悑婵犵绱曢崗姗€寮崒娑欏闁规鍠氬▔鍧楁⒒閸屾瑧顦﹂柟纰卞亰瀹曟劙骞栨担鐟扳偓鑸电節闂堟侗鍎忛柣鎾存礋閺岋繝宕橀妸褍顤€闂佺粯鎸堕崕鑼崲濞戙垹绠ｉ柣鎰仛閸ｎ喚绱撴担鍝勑ｉ柣妤佺矌濡叉劙骞掗弮鍌滐紲濠碘槅鍨伴惃閿嬫叏閸パ€鏀介柣鎰版涧鐢墎绱掔紒妯忣亪鎮惧畡閭︾叆闁糕檧鏅滀簺闂傚倷鑳剁涵鍫曞疾濞戙垺鍎楅柛灞惧嚬濞兼牠鏌ц箛鎾磋础缁炬儳鍚嬮幈銊ノ旈埀顒€螞濞嗘挻鍋╅悹楦裤€€閺€浠嬫煃閽樺顥滃ù婊勭箘缁辨帞鎷犻懠顒€鈪甸梺璇″枙閸楁娊銆佸▎鎾村仼鐎光偓閳ь剟鎯侀崼銉︹拺闁硅偐鍋涢崝鈧梺鍛婁緱閸ㄥ崬顭块幋锔解拻闁稿本鐟чˇ锕傛煙绾板崬浜伴挊婵嬫煙濞堝灝鏋撻柛瀣尵缁厼鈽夊Ο璇差槱闂佺锕ら悘姘跺Φ閸曨垰绠崇€广儱妫Ο鍌滅磽娴ｇ瓔鍤欐俊顐ｇ箞瀵寮撮姀鐘诲敹濠电娀娼ч悧蹇涱敊婵犲洦鈷戦柛娑橈工缁楀倿鏌涘Δ浣糕枙鐎殿喛顕ч埥澶愬閳ュ厖绨藉┑鐐舵彧缁蹭粙骞楀鍕浄闁归棿鐒﹂埛鎴︽偣閸ワ絺鍋撻搹顐ゅ讲缂傚倷鑳剁划顖滄崲閸岀儐鏁嬮柨婵嗩槸缁犵粯銇勯弮鍥棄濞存粍绮撳娲川婵犲啫鐭梺鐓庡暱閻栧ジ骞冩ィ鍐╁€锋い鎴ｆ硶缁犳岸姊虹紒妯哄Е濞存粍绮撻崺鈧い鎺嶈兌婢х敻鏌熼銊ュ悩閺冨牆宸濇い鏃堟？閻㈠姊绘笟鈧褑澧濋梺鍝勬噳閺呯姴顕ｉ锕€骞㈡繛鎴炵懅閸樹粙姊洪崫鍕偓鎼佹倶濠靛绠栭柟杈鹃檮閻撶喖鏌熼幆褏鎽犵紒鈧€ｎ偒娈介柣鎰嚟婢ь亪鎳ｉ幇顓滀簻闁瑰搫妫楁禍楣冩⒑鐠囪尙绠氶柡鍛█瀵鏁愰崼銏㈡澑婵犵數濮撮崯顖炴偟閺嶎偆纾藉ù锝勭矙閸濇椽鎮介娑辨當妞ゎ厼娲╃粻娑樷槈濡壕鏅犻弻銊╁即濡も偓娴滃墽绱掗崜褍浜惧┑鐐诧躬楠炲啫螖閸愨晛鏋傞梺鍛婃处閸撴盯藝閵娾晜鐓熼柕蹇婃櫅閻忥繝鎮介銈囩瘈闁轰焦鍔欓幃娆徝圭€ｎ偅鏉搁梺璇插嚱缂嶅棙绂嶉悙鏍稿洩顦归柡宀嬬秬缁犳盯骞橀崜渚囧敼闂備胶绮〃鍡涖€冩繝鍥х畺婵°倕鎳庣痪褔骞栫€涙ɑ灏伴柡鍌楀亾闂傚倷鑳剁划顖濇懌闂佸憡鎸诲畝绋跨暦椤栨繄鐤€婵炴垶鐟ч崢閬嶆⒑缂佹◤顏嗗椤撶喐娅犻柣銏犳啞閻撴稑霉閿濆浂鐒鹃柡鍡到閳规垿妾遍柛鈺傜墪椤曘儵宕熼姘€块棅顐㈡处閹搁攱绔熼弴銏♀拺闁圭瀛╃粈鈧梺绋匡工缂嶅﹤鐣烽幇顔藉珰婵炴潙顑嗛弬鈧俊鐐€栧Λ浣肝涢崟顒佸弿闁逞屽墴濮婅櫣绮欏▎鎯у壉闂佸湱顭堥…鐑界嵁韫囨稑宸濋柡澶嬪灩椤︻參姊洪崨濠勬噧妞わ富鍨跺畷妤佺節閸ャ劉鎷洪梺鐓庮潟閸婃洟鍩㈤崼銏㈢＝闁稿本绋栨竟姗€鏌嶇拠鑼ч柡浣瑰姈瀵板嫭绻濋崟鍨ラ梻鍌欑劍鐎笛兠哄澶婄；闁圭偓鐣禍婊勩亜韫囨挸顏╅柡鍡到閳规垿鍨惧畷鍥х厽閻庤娲栧畷顒冪亙闂佸憡鍔︽禍婵嬪闯椤栫偞鈷掑ù锝囩摂閸ゆ瑩鎮楀☉鎺撴珚鐎规洦鍋呴幆鏃堝Ω閵壯屾Х闂備胶顢婇幓顏嗙不閹达箑鍙婇柕澶嗘櫆閻撳啰鎲稿鍫濈婵娉涙闂佸憡娲﹂崹鎵不閹惰姤鐓曢柍鈺佸暔娴狅箑顭跨憴鍕婵﹦绮幏鍛瑹椤栨粌濮奸梻浣瑰濞插繘宕愰弴鈶┾偓锕傚炊椤掍焦娅㈤梺缁橈耿濞佳呯矈閿旂晫绡€闁汇垽娼у瓭濠电偠顕滅粻鎾崇暦閹扮増鍊婚柤鎭掑劤閸樺崬鈹戦悩缁樻锭婵☆偅顨婇幃鐢碘偓锝庡枟閻撳繐鈹戦悙闈涗壕婵炲懎妫濋弻锝夊箻閸楃偛濮﹂梺鍝勭焿缁绘繂鐣烽幒鎴僵闁告瑦顭堝鎼佹⒒娴ｇ懓鈻曢柡鈧崡鐐嶆盯宕橀鑲╃枃闂佸搫绋侀崢濂稿礃閳ь剙顪冮妶鍡樺暗闁哥喎娼￠獮蹇旂節濮橆厸鎷虹紓浣割儐鐎笛冿耿娴煎瓨鐓熼柣鏃€绻傞幊鎰版偝婵犳碍鐓涢柛鎰剁到娴滃墽绱撴担铏瑰笡闁烩晩鍨堕獮濠傗攽鐎ｎ亞楠囬梺鍓茬厛閸犳宕曢鍫熲拻濞撴埃鍋撻柍褜鍓涢崑娑㈡嚐椤栨稒娅犻悗娑欘焽缁犳儳霉閿濆懎鏆辨繛璇х畵瀹曟洖螖閸涱喚鍘遍柣蹇曞仧閸嬫捇鎯冮幋锔界厸闁糕槅鍘鹃悾鐢告煛鐏炵偓绀夌紒鐘崇〒閳ь剨缍嗘禍鏍磻閹捐鍐€妞ゆ劗鍠庢禍楣冩煟閵忋倖娑х€涙繂顪冮妶搴″绩婵炲娲熼獮鎴﹀礋椤栨稑鈧粯鎱ㄥΔ鈧Λ娆撴晬娓氣偓濮婄粯鎷呯粵瀣闁诲孩绋堥弲娑⑩€旈崘顔藉癄濠㈣埖蓱缂嶅骸鈹戦悙鍙夆枙濞存粍绮嶇€靛ジ鎮╃紒妯煎幈闂佸搫娲㈤崝灞炬櫠椤曗偓閺屾稓鈧綆浜炴晥濠殿喖锕ュ浠嬬嵁閺嶎厽鍊烽柟缁樺俯閻庡瓨绻濈喊澶岀？闁稿顭囬崚鎺戔枎閹捐泛绁?")
        if diagnostics_count:
            parts.append(f"闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧湱鈧懓瀚崳纾嬨亹閹烘垹鍊為悷婊冪箻瀵娊鏁冮崒娑氬幗闂侀潧绻堥崺鍕倿閸撗呯＜闁归偊鍙庡▓婊堟煛瀹€鈧崰鏍蓟閸ヮ剚鏅濋柍褜鍓熷绋库槈閵忥紕鍘遍梺闈涱煭婵″洨绮婚悙鎼闁绘劕顕晶顏堟嚕閹邦厹浜滈柟鍝勬娴滈箖姊虹拠鍙夌濞存粍绻勯幑銏犫槈閵忕姴绐涘銈嗙墬椤曟挳鏁愰崥鍐查叄瀹曟儼顧傞棅顒夊墮閳规垿鍨惧畷鍥х厽閻庤娲忛崝鎴︺€佸▎鎾崇缁炬澘褰夐崫妤冪磽閸屾艾鈧悂宕愰悜鑺ュ殑闁肩鐏氶崣蹇涙煙閹増顥夌痪顓涘亾闂備浇顫夐崕鐓幬涢崟顖涘珔闁绘柨鎽滅粻楣冩煙鐎电鈧垵顫濋鈺嬬秮瀹曞ジ鎮㈢粙鍨紟婵犲痉鏉库偓鎰板磻閹剧粯鐓熸俊銈傚亾闁挎洦浜滈锝夘敃閿曗偓缁犳氨鎲告径鎰哗濞寸姴顑嗛悡鐔兼煙闁箑澧紒鐙欏洦鐓曢柨婵嗙墛椤ュ鏌嶇憴鍕伌闁诡喗鐟╅崺鈩冩媴瀹勯偊妫滈梻鍌氬€搁崐椋庣矆娓氣偓楠炴牠顢曢敂钘夊壒婵犮垼娉涢懟顖滄閵堝鐓曞┑鐘插閺嬫柨霉濠娾偓缁瑥顫忕紒妯诲闁告稑锕ㄧ涵鈧俊鐐€ら崢濂告偋閸℃稒绠掗梻浣圭湽閸娿倝宕归浣侯洸闁革富鍘介崰鎰板箹鏉堝墽绋荤€规洖寮剁换娑㈠箣閻愯尙鍔伴梺绋款儐閹告悂鍩ユ径濞炬瀺妞ゆ挆鍌滅泿闂佸磭绮幑鍥箖閳哄啰纾兼俊顖滃帶楠炲牆鈹戦悩鍨毄濠殿喗鎸冲畷顖炴偋閸喐鐝峰銈嗗笒閸婅崵澹曢懖鈹惧亾閸忓浜鹃梺鍛婂姦閸犳牠骞楅悽鐢电＝濞达綀娅ｇ敮娑氱磼鐠囪尙澧曢柣锝囧厴瀹曞ジ寮撮悢閿嬬杺闂備礁澹婇悡鍫ュ磻閸涘瓨鍋熸い鎰ㄦ噰閺€浠嬫煟濡櫣浠涢柡鍡忔櫅閳规垿鎮欓埡浣峰濠电姷鏁搁崑姗€宕犻悩璇茬闁绘灏欑粔铏光偓瑙勬礃鐢帡鍩ユ径濠庢僵闁稿繗鍋愰妶顐︽⒒閸屾瑧顦﹂柛鐔锋健楠炴牠顢曢敃鈧粻鐘荤叓閸ャ劎鈽夐柣鎾存礋閺岀喐娼忛崜褏鏆犵紓浣哄珡閸ャ劎鍘介梺褰掑亰閸樼晫娆㈤懠顑藉亾鐟欏嫭灏俊顐ｇ懄缁岃鲸绻濋崶褏顦悷婊冪Ч瀹曘垽骞橀鐣屽幐闁诲繒鍋涙晶钘壝虹€电硶鍋撳▓鍨珮闁革綇缍佸畷娲焵椤掍降浜滈柟鐑樺灥椤忊晠鏌涢妸銉モ偓鍧楀蓟濞戔懇鈧箓骞嬪┑鍥╁蒋闂備焦鎮堕崐鏍洪弽顓炵厴闁硅揪闄勯崑鎰偓瑙勬礀濞村倿寮抽敓鐘斥拺闁告繂瀚崳铏规喐閺夊灝鏆ｉ柍銉畵瀹曠螖娴ｅ憡鐤傞梻浣规た閸擄附绂嶅┑瀣瀭闁割煈鍣崵鏇㈡煙缂佹ê鍧婇柡鈧禒瀣€甸柨婵嗛娴滄劙鏌熼悿顖涱仩缂佽鲸鎹囧畷鎺戔枎閹存繂顬夐梺钘夊暢妞存悂濡甸崟顖毼ㄩ柕澶涘瘜濡紕绱撴担铏瑰笡闁烩晩鍨堕悰顔嘉熼崗鐓庣彴闂佹枼鏅涢崯鎵矓妞嬪海纾?{diagnostics_count} 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閺夋埈娼╅弶鍫氭暕閵忕姭鏀介柣姗嗗枛閻忛亶鏌涢埡鍌滃⒌鐎规洘绻堝浠嬵敇閻愬灚鐓ｉ梻浣哥秺濡潡鎮為敃鍌涘亗闁绘棃鏅茬换鍡樸亜閺嶃劎顣查柟顖氱墛娣囧﹪顢曢敐搴ｅ姺闂佺懓寮堕幃鍌氼嚕椤曗偓瀹曠厧鈹戞繝鍐╁暫濠电姷鏁搁崑鐐哄垂椤栫偛鍨傞柣鐔哄閺嗘粌鈹戦敍鍕杭闁稿﹥鐗曢～蹇氥亹閹烘垹锛熼悗瑙勬礀濞诧箓寮冲鍫熺厪濠㈣泛鐗嗛崝妤呮煛閳ь剚绂掔€ｎ偆鍘介梺褰掑亰閸ｎ噣寮抽鐐寸厵闁告垯鍊楃弧鈧梺鍝勬湰缁嬫捇鍩€椤掑﹦绉靛ù婊冨槻椤斿繘濡烽敂杞扮盎濡炪倖鍔戦崹鑽ょ不瀹曞洨纾奸弶鍫涘妼缁楁帡鎽堕敐澶嬪仯闁搞儜鍕ㄦ灆闂侀€炲苯澧柟鐟版搐椤繐煤椤忓嫬绐涙繝鐢靛Т鐎氀兾ｉ崼銉︹拺闁圭瀛╃壕鎼佹煕鎼淬劍娑ч柣锝囧厴瀵挳濮€閻樻鍟嬬紓鍌氬€烽悞锕佸綔闂佸湱鏌夊▍锝囨閹惧瓨濯撮柛鎾村絻閸撳崬顪冮妶鍡楃仸闁荤啿鏅涢悾鐑藉即閿涘嫮鏉搁梺鍝勫€告晶鐣岀不濮橆剦娓婚柕鍫濇婵呯磼閼艰埖纭剁紒顔碱煼楠炴绱掑Ο鐓庡箺闂備焦瀵х换鍌毭洪妶澶婂偍闁哄鍨熼弨鑺ャ亜閺冨倹鍤€濞存粓绠栧缁樼瑹閳ь剙顭囪閹囧幢濡炪垺绋戣灃闁告侗鍘鹃崝锕€顪冮妶鍡楃瑨闁稿﹨宕甸弫顔尖槈濡挸閰ｅ畷鎯邦檪闂婎剦鍓氶妵鍕閿涘嫧妲堝銈庡亝缁诲啫顭囪箛娑樜╃憸搴敁閸ヮ剚鈷掗柛灞剧懄缁佷即鏌曢崱蹇撲壕闂備胶顭堥鍡涘箲閸ヮ剙钃熺憸鎴犵不濞戙垺鏅查柛娑卞墰閺佹牜绱撻崒娆掝唹婵＄嫏鍥х；闁瑰墽绮埛鎺懨归敐鍛础婵犫偓娴犲鐓曢柕濞垮妽椤ュ銇勯鐐寸┛妞わ附鐓￠弻锝夊煡閸℃绠虹紓浣虹帛缁诲牓骞冩禒瀣棃婵炴垶顨堥幑鏇㈡⒒娴ｈ銇熷ù婊勭懇瀹曪繝宕橀懠顒佹闂佸綊鍋婇崗姗€寮ㄦ禒瀣€甸柨婵嗙凹缁ㄤ粙鏌ｉ敐澶岀暫闁哄矉缍€缁犳盯寮撮悙鏉挎憢濠电姷鏁搁崑娑樏洪鐑嗗殨妞ゆ洍鍋撶€规洜鍘ч埞鎴﹀幢濞嗘垵鏄ユ繝纰夌磿閸嬫垿宕愰弽褜娼栫憸鐗堝笒绾惧潡鏌熼崜浣规珪鐎规挷绶氶弻娑㈩敃閻樻彃濮曢梺鎶芥敱鐢帡婀侀梺鎸庣箓濞层倝宕濈€ｎ喗鐓曢柕鍫濆€告禍楣冩⒒閸屾瑧顦︽い鎾茬矙瀵爼宕归鍛秵闂傚倷娴囬鏍窗濮樿泛绀傛俊顖濐唺缁诲棝鏌ｉ幋锝嗩棄闁绘挻绋戦湁闁挎繂鎳忛幆鍫濃攽椤曞棝妾ǎ鍥э躬閹瑩顢旈崟銊ヤ壕闁哄稁鍋呴弳婊冣攽閻樻彃顏い鎰矙閺屽秹濡烽敂鐣屼紘闂佸搫顑嗗瑙勭┍婵犲浂鏁嶆繝闈涙濮规绱掗悙顒€鍔ら柛姘儔婵＄敻宕熼姘辩潉闂佹悶鍎滈崒娑氭綎婵犵數濮幏鍐礋椤撴壕鍋撻幒妤佺厓鐟滄粓宕滃▎鎾村€舵慨姗嗗墻閻斿棙淇婇姘辨癁闁稿鎸搁～婵嬵敃閵忕姷銈梻浣虹帛娓氭宕抽敐鍛殾闁割偅娲﹂弫鍡楊熆鐠轰警鍎愭繛鍛Ч濮婄粯鎷呴搹鐟扮闂佸憡姊归悧鏇⑩€﹂崹顔ョ喓浜搁弽褌澹曢梺鍓茬厛閸嬪棝宕ｉ埀顒€鈹戦纭峰伐妞ゎ厼鍢查悾鐑藉箳閹存梹鐎婚梺鐟扮摠缁诲倿鈥栨径鎰拻濞达絿鐡旈崵鍐煕閻樺磭澧甸柟顔哄劦閹剝鎯旈敐鍡橆啎闂備礁鎼ú銊╁磿閹扮増鍋傞柕澶嗘櫆閻撴洘銇勯幇鍓佹偧缂佺姵鎸剧槐鎺楀箛椤撶姭妲堝銈庝簻閸熷瓨淇婇崼鏇炲耿婵妫欓埛鏍ㄧ節绾版ɑ顫婇柛瀣閳ь剚纰嶅姗€顢氶敐鍥╃煓閹煎瓨鎸婚～宥呪攽閳藉棗鐏﹂柡鈧柆宥呮闁逞屽墴濮婄粯鎷呴搹鐟扮闁藉啳椴搁妵鍕籍閳ь剟鎮ч悩宸殨闁瑰墎鐡旈弫宥夋煟閹邦剦鍤熼柛妯绘崌閹嘲顭ㄩ崟顓犵厜閻庤娲樼划宀勫煝鎼淬劌绠荤€规洖娲﹂悞楣冩⒑閼姐倕校濞存粈绮欏畷婵囨償閳儲鐩、娑橆煥閸曨偅鐎鹃梻浣告惈閸燁偊鎮ч崱娑欏珔闁绘柨鎽滅粻楣冩煙鐎涙鎳冮柣蹇婃櫊楠炲棝鎮㈤崗灏栨嫼闂傚倸鐗婃笟妤呮偂椤撶偐鏀介柍銉ㄦ珪閸犳ê鈹戦埄鍐╁唉妤犵偛娲、妤佸緞鐎ｎ亞妲ｉ梻鍌欑窔濞佳囨偋閸℃﹩娈介柟闂磋兌瀹撲線鏌″鍐ㄥ缂佺娀绠栭幃姗€鎮欓幓鎺嗗亾閸涘﹥鍙忛柛灞句緱濞堜粙鏌ｉ幇顖氱毢缂佺姴顭烽弻鐔碱敊鐟欏嫭鐝栭梺鐟板级椤ㄥ棝骞忛崨鏉戝窛濠电姴鎳愰、鍛存⒒娓氣偓閳ь剛鍋涢懟顖涙櫠閸撗呯＝鐎广儱鎳忛ˉ銏⑩偓瑙勬礃閸ㄥ灝鐣烽崡鐐╂婵☆垳鍘ф慨锔戒繆閻愵亜鈧牕顔忔繝姘；闁圭偓鐣禍婊勩亜閹捐泛浠滄俊鑼帛閵囧嫰顢曢姀銏㈩唶闁绘挶鍊栭妵鍕疀閹炬剚浠鹃悗瑙勬尭缁夋挳鈥旈崘顔嘉ч柛鈩兠弳妤呮⒑缁嬫鍎愮紒瀣笚缁岃鲸绻濋崶褌绱堕梺鍛婃磸閸斿秹寮埀顒佷繆閻愵亜鈧牕顫忔繝姘ラ悗锝庝憾閸熷懘鏌曟竟顖氭噽閿涙繈鎮楅獮鍨姎闁归攱鍨块悡顒勵敆娓氬洦顔旈梺缁樺姈瑜板啴寮冲▎鎾存嚉闁哄稁鍘介悡鏇熺節婵炴儳浜鹃梺缁樺釜缁犳挸顕ｉ弻銉︽櫜濠㈣泛顑傞幏娲⒒閸屾氨澧涚紒瀣尵缁顫濋婵堢畾闂佺粯鐟﹂悷銉ッ洪妶鍥╀笉妞ゆ牗绋撶粻鍓р偓鐟板閸犳洜鑺辨總鍛婄厓闂佸灝顑呴悘鎾煛鐏炲墽鈽夐柍钘夘槸椤粓宕煎┑鍡╂浆缂傚倸鍊烽懗鑸垫叏閻㈢绠查柛銉墮缁犳牗淇婇妶鍌氫壕濡炪値鍋呯换鍫ュ箖閳╁啯鍎熼柕蹇ｆ線閹查箖姊婚崒娆戭槮闁圭⒈鍋婇獮濠冩償閵婏箑浜繝闈涘€搁幗婊冪暤娓氣偓閺屾盯濡烽鐓庮潽闂佺顑呴澶愬蓟濞戙埄鏁冮柣妯垮皺娴犵厧螖閻橀潧浠滈柣妤佹尭椤繘鎼圭憴鍕彴闂佸湱绮敮鎺懶掗幇顔剧＝闁稿本姘ㄥ瓭濠碘槅鍋呯换鍌炴偩閻戣棄绠ｉ柨鏇楀亾鐎瑰憡绻冮妵鍕冀閵娧勫櫘闂佸憡鎸堕崝宀勨€旈崘顔嘉ч柛鈩兠拕濂告⒑閹肩偛濡芥俊鐐扮矙楠炲啴鏁撻悩鑼槰濡炪倖妫佸Λ鍕椤撶偐鏀介柣鎰级椤ユ粎绱掔紒妯哄妞ゃ垺妫冮崺锟犲川椤旀儳骞楅梻濠庡亜濞诧箓骞栭埡鍛惞闁绘柨鍚嬮悡鍐喐濠婂牆绀堟繝闈涱儜缂嶆牕顭跨捄琛″闁告繂瀚€閻旂厧绀傞柛蹇撳悑椤斿洭姊绘担鍛婅础闁稿簺鍊濋妴鍐川鐎涙ê浜楀┑顔姐仜閸嬫捇鏌″畝鈧崰鎰焽韫囨稑绀堢憸蹇涘汲閻樼粯鈷戠紓浣姑慨鍥煥閺囥劋閭€殿喖顭锋俊鑸靛緞婵犲倻鐛╁┑鐘垫暩婵瓨顨ラ幖浣哥柧闁告鍋愰弨浠嬫煃閽樺顥滃ù婊勭矒閹顫濋鐔哄嚒濡炪値鍋勭换鎴犳崲濠靛棭娼╂い鎺戝亰缁卞弶绻濋悽闈涗粶婵☆偅鐟╁畷娲醇濠㈩亷缍侀、姘跺焵椤掆偓椤繐煤椤忓嫭宓嶅銈嗘尵閸庢劙宕甸妷鈺傗拺闂傚牊绋撴晶鏇熶繆椤愶絿鎳囩€规洘濞婇幃婊堟嚍閵夈垺瀚介梻浣侯焾閺堫剟鎮烽妸鈺佺鐎光偓閸曨剛鍘遍柟鑹版彧缁查箖寮抽鍌楀亾濞堝灝鏋熼柣鎿勭節瀹曟椽鏁撻悩鎻掔獩濡炪倖鎸鹃崑鐔煎焵椤掑寮慨濠冩そ瀹曟粓骞撻幒宥囧嚬婵犵數鍋涘鍫曟晝閵忕姷鏆﹂柟瀛樻儕閻旀哺褔宕堕敂鍓ф晨闂傚倷绀侀幖顐﹀疮椤愨挌娲Χ閸偅姣愰梻鍌氬€烽懗鍫曗€﹂崼婢濆綊鎮滈挊澶岀崶闂佸搫绋侀崢濂告嫅閻斿吋鐓涢柛銉╊棑绾惧潡鏌ｉ妶鍌氫壕闂備浇顕ч崙鐣岀礊閸℃顩查柣鎰綑椤曢亶鏌涢弴銊ョ仭闁抽攱鍨甸湁闁稿繗鍋愰幊鍛存煟閿濆鎲鹃柡宀嬬到铻栧ù锝囨嚀绾板秴顪冮妶搴′簻缂佺粯锕㈤獮鏍亹閹烘垶宓嶅銈嗘尵婵兘宕㈤鐐粹拻濞达絽鎲＄拹鈩冦亜椤撶偟澧㈤柍褜鍓氱粙鍫ュ疾閻樿崵宓侀煫鍥ㄧ⊕閻掕偐鈧箍鍎卞Λ宀勫箯濞差亝鈷戠紓浣股戠亸顓熺箾閹绢噮妫戠紒顔芥閹煎綊宕烽鐙呯床闂備胶绮敋缁剧虎鍘介弲鍫曨敂閸喓鍘介梺鎸庣箓濞层倝宕㈢€涙ǜ浜滈柕蹇婃濞堟粎鈧娲滈崰鏍€侀弴鐘亾閿涘崬瀚悵姘舵⒑閸濆嫯顫﹂柛鏃€鍨甸锝夘敋閳ь剙鐣烽崼鏇炍╃憸瀣焵椤掆偓閿曪妇妲愰幘瀛樺闁告繂瀚呴敐澶嬬厾鐟滅増甯為悾娲煃閵夛附顥堢€规洘锕㈤、娆撳床婢诡垰娲﹂悡鏇㈡煃閳轰礁鏋ゆ繛鍫熸⒒閹喖鈹戠€ｎ偀鎷绘繛杈剧到閹诧繝宕悙鐑樼厵缂佸顑欓悡濂告煙椤栨艾顏い銏＄☉椤繃娼忛妸锔诲晭濠电姵顔栭崰妤呮晝閳哄懎鍌ㄥ┑鍌氬閺佸姊洪鈧粔鐢稿磹閸偆绠鹃柟瀵稿仧閹虫劙鏌ｉ幒宥囩煓闁哄本绋戣灒闁圭瀵掑Λ鍕⒑鐎圭媭娼愰柛銊ョ埣閻涱喗绻濋崶銊у幈婵犵數濮撮崯顖氱暦瀹€鍕厵妞ゆ梹鍎虫禒閬嶆煛娴ｇ鏆ｉ柛鈹惧亾濡炪倖甯掔€氼參宕戦埡渚囨富閻庯綆浜為崙瑙勭箾瀹€濠佺敖缂佽鲸鎸婚幏鍛存濞戞矮鐥俊鐐€栧鐟拔涢崘顭戞綎闁惧繐婀辩壕鍏间繆椤栨碍鎯堟い顐㈢Ч濮婅櫣鎷犻垾宕囦哗闂佸吋妞块崹鍫曞春閵忋倕绠婚悹鍥ㄥ絻瀹撳棝姊虹紒姗嗙劷闁轰焦鎮傞弫宥咁煥閸啿鎷洪梺璇″瀻閸涱垼鍟堟俊鐐€ら崑鍕囬鐐茬厺鐎广儱顦崡鎶芥煟濡吋鏆╅柨娑欑矊椤啴濡堕崱妯锋嫽闂佸搫鎷嬮崑濠囩嵁婵犲洤宸濋悗娑欘焽閸樼敻姊洪懡銈呮瀾婵犮垺锕㈤、鏃堫敇閵忥紕鍘撻梺闈涱樈閸ㄦ娊鎮鹃崹顐闁绘劕妯婇崕蹇涙煃鐟欏嫬鐏寸€规洘鍎奸ˇ顕€鏌涚€ｎ偅宕屾い銏＄洴閹瑧鍒掔憴鍕伜闂傚倷鑳堕…鍫ュ嫉椤掑嫭鍤屽Δ锝呭暙閻掑灚銇勯幒鎴濃偓鎼佸储閹绢喗鐓欓柧蹇ｅ亽濞堟粎鈧娲栭妶绋款嚕閹绢喗鍊烽柣銏犵仛閻庮噣姊婚崒娆愮グ妞ゎ偄顦靛畷鏇㈠箮閼恒儱浠遍梺闈涱焾閸庮噣寮稿澶嬬厽婵☆垱顑欏璺ㄦ喐閻楀牆绗氶柛瀣姉閳ь剛鎳撴竟濠囧窗閺嶎厼绀堥柟娈垮枤绾惧ジ鏌ｉ幇闈涘闁告柣鍊栫换娑氭兜妞嬪海鐦堥悗娈垮枛椤兘寮幇顓炵窞濠电姴瀛╃紞鍌炴⒒娓氣偓濞佳呮崲閸℃稑鐤炬繝闈涱儏缁€澶愭煕濠靛嫬鍔ょ痪鎯с偢閺岋綁骞囬棃娑橆潻闂佸憡鏌ｉ崐鏍Φ閸曨垼鏁囬柣妯诲絻楠炲鎮楀▓鍨灈妞ゎ厾鍏橀獮鍐閵堝懐顦ч梺缁樻尭缁ㄥ爼宕戦幘缁樼叆閻庯絻鍔嬬花濠氭⒑閻熺増鎯堟俊顐ｎ殕缁傚秹鎮欓鍌滅槇闂佸啿鐨濋崑鎾绘倶閻愬灚娅曞ù鐙€鍘剧槐鎾存媴閾忕懓绗＄紓浣割儐閹歌崵绮嬪澶婄濞达絿顭堥崬銊╂⒑闂堟侗鐓┑鈥虫穿閵囨劗鈧綆鍠楅埛鎺懨归敐鍛暈闁诡垰鐗撻弻锟犲醇椤愩垹顫╅柣鎾卞€栨穱濠囶敍濞嗘帩鍔呴梺鎼炲€栭〃濠囧蓟濞戙垹鍗抽柕濞垮劤娴犫晠姊绘担绋胯埞婵炶濡囬幑銏犫攽鐎ｎ偒妫冨┑鐐村灦閼归箖銆傝ぐ鎺撯拺閻犲洠鈧櫕鐝紓浣藉紦缁瑩宕?")
        if weak_spots:
            if localized_weak_spot:
                parts.append("")
            else:
                parts.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎妯恍氱紓鍌氬€烽懗鑸垫叏闁垮绠鹃柍褜鍓熼弻鈥崇暆閳ь剟宕伴弽褏鏆︽繝濠傛－濡查箖鏌ｉ姀鈺佺仭闁烩晩鍨跺璇测槈濮橈絽浜鹃柨婵嗗暙婵″ジ鏌嶈閸撴氨鎹㈤崼婵愬殨濠电姵鑹鹃崡鎶芥煟閺冨洦顏犳い鏃€娲熷铏圭磼濡搫袝闂佸憡鎸诲畝鎼佸箖閻㈢绫嶉柛顐ゅ暱閹锋椽姊虹涵鍛汗闁稿绋掓穱濠冪附閸涘﹦鍘辨繝鐢靛Т閸嬪棝鎮℃總鍛婄厱闁宠鍎虫禍鐐繆閻愵亜鈧牜鏁幒妤€绐楁慨姗嗗墻閻掍粙鏌熼柇锕€骞樼紒鐘荤畺閺屾稑鈻庤箛锝喰ㄦ繝鈷€灞奸偗闁诡噯绻濇俊鑸靛緞鐎ｎ剙寮抽梻浣告惈濞层劑宕戝☉娆戭洸闁规鍠氱壕鐣屸偓骞垮劚濡稒鏅堕悽鍛婄厸鐎光偓鐎ｎ剛鐦堥悗瑙勬礀閻栧ジ宕洪敓鐘茬劦妞ゆ帒鍊归～鏇犫偓瑙勬礀濞诧箓宕伴幇鐗堢厽婵°倐鍋撻柣妤€妫涚划顓烆潩閼哥數鍘遍柣搴秵娴滄粓鍩€椤掆偓濞硷繝鎮伴鈧浠嬪Ω閿斿墽肖闂備礁鎲￠幐鍡涘触闁垮鐏存慨濠呮閹叉挳宕熼銈囥偡闂備線娼ч悧蹇涒€﹂崼銉稏闊洦绋掗幆鐐烘煕閿旇骞橀柣鎾存尭閳规垿鎮欓崣澶樻！闂佺瀛╂繛濠傜暦濠婂牆绾ф繛鍡欏亾鐎靛矂姊洪棃娑氬婵☆偅顨婇幃姗€濡烽敂杞扮盎闂佹寧娲栭崐鐟扳槈瑜庨妵鍕即椤忓棛蓱缂備胶绮换鍌烇綖濠靛鏁囬柣鏂挎憸瑜板憡绻濋悽闈浶為柛銊у帶閳绘柨鈽夐姀鈺傛櫈闂佸憡渚楅崰姘躲€呴崣澶岀瘈濠电姴鍊绘晶娑㈡煃闁垮鐏撮柡灞剧☉閳藉顫滈崼婵嗩潬闂備礁鐤囧Λ鍕囬悽绋胯摕闁靛ň鏅涢崡铏亜韫囨挻顥犻柡鍡愬€濋幃妤冩喆閸曨剛顦ㄩ梺鑽ゅ暱閺呯姴顕ｉ锕€绠荤紓浣姑禍褰掓⒑閸濆嫬鈧爼宕曢懠顑藉亾濮樺啿浜圭紒杈ㄦ崌瀹曟帒顫濋钘変壕闁绘垼濮ら崐鍧楁煥閺囩偛鈧綊寮查鍡欑＝闁稿本鐟ч崝宥嗐亜閵娿儲顥犻柡渚囧櫍閺佹捇鎮╅懠鑸垫啺闂備礁鎼ú銏ゅ垂瑜版帗鐓侀柛銉墯閻撶喖鏌￠崘銊ヤ簽闁绘帡绠栭弻宥堫檨闁告挻宀稿畷婵單旈崨顓犲姦濡炪倖甯婄欢锟犲疮韫囨稒鐓曢柣妯虹－婢х敻鏌嶉妷顖滅暤闁诡喗绮撻幐濠冨緞鐎ｎ兘鍋撻鍕拺鐟滅増甯掓禍浼存煕濡灝浜规繛鍡愬灲閹瑥霉鐎ｎ偅鏉搁梻浣虹帛钃辩憸鏉垮暣椤㈡棃鍩￠崒銈嗩啍闂佺粯鍔栧娆愭叏閸ヮ剚鐓冮悷娆忓閻忔挳鏌熼瑙勬珚鐎规洖缍婇、鏇㈡晲閸℃瑦顫栧┑鐘垫暩婵敻顢欓弽顓炵獥婵°倕鎳庣粻浼存煕閹邦垰鐨洪柡鍡畵閺岀喖鏌囬敃鈧弸銈囩棯閹冩倯濞ｅ洤锕、娑樷攦閻愵剙鐝辨繝鐢靛仦濞兼瑧鈧矮鍗抽獮鍐ㄧ暋闁妇鍙嗛梺鍛婂姦娴滅偤顢欐繝鍌楁斀闁炽儱鍟跨痪褔鏌涢弮鈧悷鈺呮偘椤斿槈鐔煎礂閻撳海褰撮梻浣藉亹閳峰牓宕滈妸褎顫曢柛娆忣槺缁♀偓濠电偛鐗嗛悘婵嬪几閻斿吋瀚呴梺顒€绉甸悡鐔兼煥閺冣偓閸庢娊宕㈤弶鎴旀斀妞ゆ梻鎳撴禍楣冩⒒娴ｇ懓顕滅紒瀣灩閳ь剚鍑归崳锝夈€佸▎鎾冲嵆闁靛骏绱曢崢浠嬫⒑缂佹◤顏勵嚕閸洖鍌ㄩ柛宀€鍋為悡鏇熺箾閹存繂鑸归柣蹇婂墲缁绘盯宕煎┑鍡樺€繛锝呮搐閿曨亝淇婇崼鏇炵倞妞ゎ剦鍠撻崕鐢稿蓟濞戞埃鍋撻敐搴′簽闁靛棙甯￠弻鐔肩嵁閸喚浠奸柧浼欑秮閺屟嗙疀濮樺吋缍堝┑鐐茬墦缁犳牕顫忓ú顏咁棃婵炴番鍊栭惄顖炲春閳ь剚銇勯幒鎴濐仼缁炬儳顭烽弻鐔兼倷椤掍胶浼囧┑鈩冨絻閻楀﹦鎹㈠☉銏犳そ濞达絿顭堢€涳絾绻涚€涙鐭嬬紒璇插閸掓帞鈧綆浜堕崥瀣煕椤愶絿鈼ユ慨瑙勵殜濮婃椽宕烽鐐插闂佺懓鎲￠幐鎶界嵁韫囨拋娲敂閸涱亝瀚奸梺鑽ゅТ濞茬娀鍩€椤掆偓绾绢參鍩€椤掆偓椤兘寮诲☉銏犲嵆闁靛鍎辩€涳絽鈹戦悙鏉戠祷闁绘牜鍘ч～蹇曠磼濡顎撴繛鎾村嚬閸ㄦ娊宕濈粙娆炬富闁靛牆妫楅悘銉╂煙閾忣個顏堟偩閻戣棄绠涙い鎾跺Х閻﹀牆鈹戦鏂や緵闁告挻鐩棟妞ゆ劧闄勯埛鎴︽煕閿旇骞栭柛鏂款儐閵囧嫰濡搁妷褏顔掗悗娈垮櫘閸嬪嫰顢橀崗鐓庣窞閻庯綆鍓欓獮妤呮⒒娴ｅ摜绉洪柛瀣躬瀹曟粓鏁冮崒姘優闂佺粯鏌ㄩ崥瀣偂閺囩喍绻嗘い鏍ㄧ矊閸斿鏌涢悢鍝勪户缂佽鲸甯炵槐鎺懳熼懖鈺冩澖濠电姵顔栭崰鎺楀磻閹剧粯鈷戦柟绋挎捣缁犳挻淇婇锝囨创濠碘剝鎸抽獮鍥敄閼恒儲鏉搁梻浣哥枃濡嫬螞濡や胶顩叉繝闈涱儐閻撶喖鏌ｉ弮鈧娆撳礉閿曞倹鐓曢柍鐟扮仢閻忊晜銇勯幘鍐叉倯鐎垫澘瀚换婵嬪磼濠靛啫浜鹃柛顭戝枓閺€浠嬫煟閹邦厽缍戦柣蹇ョ畵閺岋綁鎮㈠┑鍡樻悙闁稿被鍔戝娲敆閳ь剛绮旈悽绋跨厱闁硅揪闄勯埛鎺楁煕椤愩倕鏋庣€规洜鍠栭弻娑㈩敃閻樻彃濮庨梺姹囧€楅崑鎾舵崲濠靛洨绡€闁稿本纰嶅▓婊冣攽閳╁啫绲婚柣妤€绻橀獮澶愬川婵犲啫鍔呴梺闈涱焾閸庢瑩鏁冮崒娑氬幈闂佸搫娲㈤崝宀勬倶閻樼粯鐓曟俊銈呭閻濐亪鏌曢崶褍顏紒鐘崇洴楠炴﹢骞栭鐕傞獜闂佽崵鍋為悢顒傜不閹炬剚娼栫紓浣股戞刊鎾煟閹寸伝顏勨枔瀹€鈧槐鎺楀礈瑜戝鎼佹煕濞嗗繐鏆欓柣锝囧厴楠炲鏁冮埀顒€娲块梻浣虹《閸撴繂煤濠婂懐涓嶆慨妯垮煐閳锋垹绱撴担濮戭亪鎮樻潏銊ょ箚妞ゆ劑鍨归鈺呮煛娓氬洤娅嶉柡宀嬬秮閹垽宕妷褏鍘愮紓鍌欒兌缁垶鏁冮姀銈囧祦闁告劏鏅涢閬嶆煙绾板崬骞楅柡鍜佷邯濮婃椽鏌呴悙鑼跺濠⒀冾嚟閳ь剚顔栭崰鏍€﹂悜钘夋瀬闁圭増婢橀獮銏′繆椤栨碍鎯堝┑鈩冨▕濮婄粯鎷呴悷閭﹀殝缂備礁顑嗛崹褰掑焵椤掍礁鍤柛锝忕到椤曪綁宕樺ù瀣潔闂侀潧绻嗗褔骞忛搹鍦＝濞达絽澹婇崕蹇旂箾绾绡€鐎规洩缍佸畷鐔碱敃閳ь剟鎮烽柇锔惧弳闂佸憡鍔︽禍婊堟偂閻斿吋鈷戠紓浣姑肩欢閬嶆煕閻樻剚娈橀柟骞垮灩閳规垹鈧綆浜為ˇ銊╂⒑鐎圭姵銆冪紒鈧担閫涚箚闁规儼濮ら埛鎺懨归敐鍛喐闁哄鍟—鍐级閹寸偞鍠愰梺杞扮贰閸犳牞鐏冮梺鍛婂姀閺呮粌鈻撻弶搴撴斀閹烘娊宕愰幇鏉跨；闁圭偓鐣禍婊堟煛閸ヮ煁顏堝礉閿旈敮鍋撶憴鍕闁哥姵鐗犻妴浣糕槈濮楀棙鍍甸柡澶婄墐閺呮粌顭块幋婵冩斀闁挎稑瀚禍濂告煕婵犲啰澧垫鐐村姍閹瑩顢楁担绋夸紟闂備礁婀遍搹搴ㄥ窗濮橆剛鏆ゅù锝夆偓娑氱畾闂侀潧鐗嗙€氼垶宕楀畝鈧槐鎺楀煢閳ь剟宕戦幘缁樷拻濞达絽婀卞﹢浠嬫煕閵娿劍顥夋い顓炴穿椤︽煡鏌ｉ埥鍡楀籍婵﹦绮幏鍛存偡闁箑娈濇繝鐢靛仦瑜板啰鎹㈠Ο铏规殾闁归偊鍎甸弮鍫濆窛妞ゆ挾濮存慨锔戒繆閻愵亜鈧牜鏁繝鍕焼濞撴埃鍋撶€规洜鏁婚、妤呭礋椤掑倸骞堥梻浣筋潐瀹曟ê鈻斿☉銏犲嚑婵炲棙鍔掔换鍡樸亜閹邦喖孝闁诲繑鐓￠弻鈥崇暆鐎ｎ剛蓱闂佽鍨卞Λ鍐€佸☉姗嗙叆闁告稑鎷戠紞浣割潖閾忓湱鐭欐繛鍡樺劤閸撴澘鈹戦埥鍡椾簼缂佸鎹囧畷姘跺箳閺冨倻锛滃┑鈽嗗灣椤牊绂嶅┑瀣拺闁告稑锕ゆ慨鈧梺鍝勬噺缁诲牆鐣烽姀銈呯闁绘垵妫欑€靛矂姊洪棃娑氬婵☆偅顨嗛幈銊╁磼閻愬鍘辨繝鐢靛Т閸燁垳绮堢€ｎ兘鍋撳▓鍨灈闁硅绻濋獮鍡涘籍閸惊鈺呮煥閺冣偓閸庢娊鐛Δ鍛拻濠电姴楠告禍婊勭箾鐠囇呯暠妞ゎ偄绻樺畷鐑筋敇濠靛牆澧鹃梻浣瑰濞叉牠宕愯ぐ鎺撳亗婵炴垶鍩冮崑鎾诲礂婢跺﹣澹曢梻渚€鈧偛鑻晶瀵糕偓瑙勬磻閸楀啿顕ｆ禒瀣垫晣闁绘劖顔栭崯鍥煟閻斿摜鐭屽褎顨堥弫顕€鍩￠崨顓熺€梺鍛婂姦閸犳鎮￠妷锔剧瘈闂傚牊绋掗ˉ鐐烘煕閵堝懏鍠橀柡宀嬬稻閹棃濡堕崱鈺€鍝楃紓鍌欐祰妞存悂骞戦崶褏鏆﹂柟鐑樺灍閺嬪酣鏌熺€涙绠撴い顒€顦版穱濠囨倷椤忓嫧鍋撻幋锕€绀夌€光偓閸曨剙浜遍梺瑙勫劤绾绢參寮抽敃鈧湁闁稿繐鍚嬬紞鎴︽煕閹般劌浜惧┑锛勫亼閸婃牠骞愭ィ鍐ㄧ；闁绘劕寮敐澶樻晢闁告洦鍏橀幏娲⒒娓氬洤浜為柛瀣洴閹崇喖顢涘☉娆愮彿濡炪倖鐗滈崑鐐烘偂韫囨稒鐓曢柕澶嬪灥閸犳碍瀵奸崘銊庢棃鎮╅棃娑楁勃闁汇埄鍨埀顒€纾弳锕傛煕濡ゅ啫鍓辨繛鎾愁煼閺岀喖顢涢崱妤佹拱妞ゃ儻绻濆濠氬磼濮橆兘鍋撻悜鑺ュ€块柨鏇楀亾闁伙絽鍢茶灒闁惧繗顫夊▓楣冩⒑濮瑰洤鐏い顓炵墢婢规洘绻濆顓犲帾闂佸壊鍋呯换宥呂ｉ幖浣圭參闁告劦浜滈弸娑㈡煛鐏炵偓绀嬬€规洜鍘ч埞鎴﹀箛椤撳闄勭换娑氬鐎ｎ亙姹楁繝鐢靛亹閸嬫捇姊洪崫鍕拱婵炲弶锚椤曘儵宕熼瀣枛閹粌螣闂傚瓨鍠氭繝鐢靛Х閺佹悂宕戝☉銏″亱濠电姴鍟伴悵鍫曟煕閳╁啰鎳勬い顐ｆ礋閺岀喖骞嗚閹界姴鈹戦娑欏唉闁哄矉缍侀幃銏ゅ传閸曞灚姣夐梻浣告惈濡瑦绔熼崱娆愵潟闁规儳鐡ㄦ刊鎾煕閿旇骞栫€殿喓鍔庣槐鎾存媴閸濆嫅锝夋煟濡ゅ啫鈻堥柟顔诲嵆椤㈡岸鍩€椤掆偓閻ｉ攱绺界粙璇俱劑鏌曟径濠勫哺闁哄懐濞€瀵寮撮悢椋庣獮婵犵數濮撮崑鍡涘礉婢跺ň鏀介柍钘夋娴滄粓鏌涢悢鍛婄稇闁伙絽鍢茬叅妞ゅ繐瀚崝锕€顪冮妶鍡楃瑐闂傚嫬绉电粋宥咁煥閸喓鍘甸梺缁樺灦閿氶柣蹇嬪劜閵囧嫯绠涢敐鍕仐闂佸搫鏈粙鎾诲焵椤掑﹦绉靛ù婊冪埣瀹曟洟寮崼鐔哄幗闂佺懓鐏濋崯顐ｇ閹殿喒鍋撶憴鍕闁绘牕鍚嬫穱濠囧箹娴ｈ娅嗙紓鍌欓檷閸ㄩ缚鍊撮梻鍌氬€搁崐鐑芥倿閿曗偓椤啴宕稿Δ鈧崒銊╂煟閹惧啿顔傛繛鎴烆焸閺冨牆宸濇い蹇庣娴滈箖鏌ㄩ弴鐐测偓鎼佹煥閵堝棔绻嗛柕鍫濆椤︼附绻涢崼鐔虹疄婵﹤顭峰畷鎺戭潩閸楃儐鏉哥紓鍌欑椤戝棝宕归崸妤佹櫜闁绘劕妯婇崥瀣熆鐠轰警鍎岄柟閿嬫そ濮婅櫣鎲撮崟顐㈠Ц婵犳鍠撻崐婵嗩嚕椤愶附鐒肩€广儱妫涢崢閬嶆⒑闂堟侗鐒鹃柛搴㈠▕瀹曟椽鏁愰崨顏呮杸闂佹寧绋戠€氼參寮抽鍌楀亾鐟欏嫭绀堥柛鐘崇墵閵嗕礁鈽夊鍡樺兊婵℃彃鏈悧鏇㈠极娴犲鈷掗柛灞剧懆閸忓瞼鐥鐐靛煟鐎规洘绮岄埞鎴犫偓锝庘偓顓ㄧ畵閺岋綁骞囬澶婃闂佺粯绻傞悥濂稿蓟閿熺姴鐐婇柕澶堝劤娴犻箖姊洪幎鑺ユ暠閻㈩垱甯″﹢渚€姊洪幐搴ｇ畵婵炲眰鍔戦獮妤呭磼閻愬鍘遍梺闈涚墕濡盯骞婇崨顖滅＜閺夊牄鍔岀粭褏绱掓潏銊ョ瑨閾伙綁鏌ц箛娑掑亾濞戞瑥浜濋梻鍌氬€烽懗鍫曞箠閹惧墎涓嶇€广儱顦崹鍌炴煢濡警妲洪柡鍡畵閺岋綁骞樺畷鍥у摵闂佽　鍋撳ù鐘差儐閻撴洘銇勯幇鈺佲偓鏇㈠几閹寸偑浜滈柡鍐ｅ亾婵炶尙鍠庨～蹇曠磼濡偐鎳濋梺閫炲苯澧い顓炴穿椤︽挳鏌熼獮鍨伈鐎规洖銈告俊鐑藉Ψ瑜濈槐顕€姊绘担鍛婃儓婵炲眰鍔戝畷鎴︽倷閻㈠灚锛忓銈嗙墱閸嬬偤鍩涢幒妤佺厱閻忕偛澧介幊鍡涙煕韫囨挾鐏遍柣銉邯椤㈡﹢鎮欓棃娑氬幗闁诲氦顫夊ú妯煎垝瀹€鍕厴闁瑰濮崑鎾绘晲鎼粹€茬盎婵炲濯崣鍐潖濞差亝顥堟繛鎴炴皑閻ゅ嫰姊虹粙鍖℃敾婵炶尙鍠庨悾宄扳枎閹炬潙浜圭紓鍌欑劍椤洭宕㈤幖浣瑰€垫鐐茬仢閸旀艾螖閻樿櫕鍊愰柣娑卞枛铻栭柛娑卞枤閸樻捇姊绘担鍝ヤ虎妞ゆ垵鎳橀幃妯尖偓娑櫳戦崣蹇撯攽閻樻彃鏆為柕鍥ㄧ箖閵囧嫰濮€閳╁啰顦版繝纰樷偓宕囧煟鐎规洏鍔戦、妤呭磼濞戞顦伴梻鍌氬€搁崐椋庣矆娓氣偓瀹曘儳鈧綆浜跺〒濠氭煕瑜庨〃鍛村垂閸岀偞鈷戞い鎺嗗亾缂佸鎸抽幃鎸庛偅閸愨晝鍘卞銈嗗姧缁插墽绮堥崘顔界厱閻庯綆浜堕崕鏃堟煛鐏炲墽娲存い銏℃礋閺佹劙宕堕埡鍐ㄥ笓缂傚倸鍊烽懗鑸垫叏闂堟稓鏆嗙紒瀣儥濞兼牗绻涘顔荤盎鐎瑰憡绻傞埞鎴︽偐閹绘帩浠鹃梺闈╂€ラ崘鐐瘜闂侀潧鐗嗙换鎰版儊濠婂牊鐓曢柕濞炬櫃閹茬偓顨ラ悙鑼ⅵ濠碘剝鐡曢ˇ杈ㄧ箾瀹€濠佺盎閼挎劙鏌涢妷鎴濆暟缁夘喚绱撴担闈涘妞ゎ厼鍢查～蹇撁洪鍕唶闁瑰吋鐣崹濠氭晬濞戞氨纾藉ù锝嗗絻娴滅偓绻涢幘鏉戠劰闁稿鎹囬弻鐔碱敍濮橆剚娈婚梺鍦帶缂嶅﹤鐣烽悜绛嬫晣闁绘瑥鎳愭惔濠囨⒒娴ｅ憡鎯堟い锔诲灦閹囧礋椤栨氨顦柣蹇曞仧閻擃偉銇愰幒婵囨櫓闂備焦顑欓崹鐗堢妤ｅ啯鍋℃繛鍡楃箰椤忣亞绱掑畝鍐╃《缂佽鲸甯炵槐鎺懳熼懖鈺冩澖婵°倗濮烽崑娑㈠疮椤愶箑鐓濋幖娣€楅悿鈧梺鎸庣箓閹冲繐鈻嶆繝鍐х箚闁绘劦浜滈埀顒佺墪铻炲ù锝堫潐閸欏繘鏌曢崼婵愭▓闁轰礁锕弻鐔衡偓鐢殿焾娴犙呯磼閳锯偓閸嬫捇姊绘担鍦菇闁搞劏妫勯…鍥槼缂佸倹甯掗…銊╁醇閻斿搫骞楅梺鍦劋婵炲﹤鐣峰┑鍥ㄥ劅闁靛鍎抽ˇ顐︽⒑閸︻厼鍔嬮柛銊ョ秺瀵娊宕卞☉娆戝幈闂佸搫娲㈤崝灞剧閻愮儤鐓熼柕鍫濇噺閸ゅ洦鎱ㄦ繝鍐┿仢闁诡喗鐟╅幐濠冨緞婵犲偆娼ラ梻鍌欑閹诧繝骞愮拠鑼殕闁归棿绀佺粻鏍煟閹邦剦鍤熸い鈺冨厴閹鏁愭惔鈥愁潻閻熸粍婢樼€氭澘顫忓ú顏勭闁绘劖褰冩慨宀勬⒑閸涘﹥鐓ユい鎴濇搐閳诲酣濮€閵堝棛鍔堕悗骞垮劚濡盯宕㈤崨濠勭閺夊牆澧介幃鍏笺亜椤撶偟澧︾€殿喗濞婇弫鎰緞鐎ｎ剙骞愰梺璇茬箳閸嬬喖宕戦幘鍓佺焼閻庯綆鍏橀崑鎾舵喆閸曨剛顦梺鍛婎焼閸パ呭幋闂佺鎻粻鎴︽倷婵犲嫭鍠愰幖鎼厛閺佸倿鏌ｅΟ鑽ゃ偞闁衡偓娴犲鐓熸俊顖濐嚙婢ь垶鏌涢悢椋庣闁哄本鐩幃鈺呭箛娴ｅ湱鏆ラ梺缁樻尪閸婃繈寮婚敐澶婃婵炲棛鍋撻悿鍥р攽閻愭彃鎮戦柣妤侇殘閹广垹鈽夊鍡楁櫊濡炪倖妫佸畷鐢告儎鎼淬垻绠剧痪鎯ь儏娴滅懓鈹戦悙鈺佷壕闂備礁鎼張顒勬儎椤栨凹鍤曢柟缁㈠枟閸婄兘鏌涜箛鎾存喐濡炶濞婇弻锝嗘償閵忊懇濮囩紓浣筋嚙閻楀棝锝炶箛鏇犵＜婵☆垵顕ч鎾绘⒑閸涘﹦鈽夐柨鏇樺劦瀹曟洟骞樼紒妯锋嫼闂佽崵鍠愬姗€寮虫潏鈺冪＜缂備焦锚缁椦囨煕閹烘挸绗掗柍璇查叄楠炴ê鐣烽崶璺烘倛闂傚倷鑳剁划顖濇懌閻熸粍婢橀崯鎾箖閹稿簺鍋呴柛鎰ㄦ杹閹峰姊虹粙鎸庢拱闁荤啙鍛幓闁哄啠鍋撶紒缁樼⊕閹峰懘宕橀崣澶岊槺闂侀€炲苯澧剧紒鐘虫尭閻ｉ攱绺界粙璇俱劑鏌曟竟顖氱Ф閸氬綊姊虹拠鏌ヮ€楃紒鐘茬Ч瀹曟洟鏌嗗畵銉ユ处鐎靛ジ寮堕幋鐙呯串缂傚倸鍊烽悞锔炬箒缂備浇顕уΛ娆撳Φ閸曨垰鍐€闁靛ě鍕珯婵＄偑鍊栫敮鐐哄窗閺嶎厼钃熸繛鎴欏灩鍥撮梺鍛婂姂閸斿宕戦幘鏂ユ斀闁糕檧鏅滅紞搴♀攽閻愬弶鈻曞ù婊勭矋鐎靛ジ鎮╃紒妯煎幈闂佸搫娲ㄩ崑鐔哥濞戙垹鏋侀柛顐犲劜閳锋帒霉閿濆牜娼愰柛瀣█閺屾盯寮崸妤€寮伴悗娈垮櫘閸嬪棝骞忛悩缁樺殤妞ゆ帊鐒﹂鏇熶繆閻愵亜鈧牜鏁幒鏂哄亾濮樼厧澧柛搴亰濮婄粯鎷呯粙鎸庢瘣闂佸湱鈷堥崑濠傜暦閹扮増鍋ㄧ紒瀣硶椤斿棗鈹戦悙鍙夆枙濞存粍绻堥崺娑㈠箣閻樺灚锛忓銈嗘尵閸嬬偤宕抽悷鎳婄懓顭ㄩ崘顏喰ㄩ梺鍝勬湰缁嬫捇鍩€椤掑﹦绉甸柛瀣鐓ら悗鐢电《閸嬫挾鎲撮崟顒傤槰缂備浇顕ч崐鍧楁晲閻愬樊鐓ラ柛顐ｇ箘閸旓箑顪冮妶鍡楃瑨閻庢凹鍓熼幏鎴︽偄閸濄儳顔曢梺鐟扮摠閻熴儵鎮橀埡鍌欑箚妞ゆ劧缍囬懓鍧楁煛瀹€鈧崰鎾跺垝濞嗘挸鍨傛い鏇炴噹婵＄兘鏌ｆ惔銈庢綈婵炲弶鐗滄竟鏇㈩敇閻樻剚娼熼梺瑙勫劤椤曨參鎮疯ぐ鎺撶厱闁靛鍨电€氼喛銇愰懠顒傜＝闁稿本鑹鹃埀顒€鎽滅划鏂跨暦閸ヮ煈鍋ㄥ┑顔矫晶搴＄暤娓氣偓閺屾盯骞囬埡浣肝ㄩ梺鍝勵儏闁帮綁寮婚悢琛″亾濞戞鎴︽偂閵夈儍鐟邦煥閸垻鏆┑顔硷工椤嘲鐣锋總鍛婂亜閻炴稈鈧剚娼撻梻鍌欐祰椤銇愰崘顔肩疅闁跨喓濮存闂佸憡娲﹂崹鎵尵瀹ュ鐓冪憸婊堝礈濞嗘垵寮查梻浣虹帛閺屻劑銆冩惔鈽嗙劷闁哄稁鍘介悡锝夌叓閸ャ劌鍤繛鍏煎姍閺屾盯鎮╅崣澶樻＆闂佸搫鏈惄顖氼嚕閹绢喖惟闁靛鍊楅弫鏍ㄤ繆閻愵亜鈧呮嫻閻旂厧绀夌€光偓閸曨偆鍘撮梺纭呮彧闂勫嫰宕愰悜鑺ョ厱婵炲棗娴氬Σ鍛婄箾閸涱偄鈧洟鍩為幋锔藉€烽悹楦挎濮ｃ垽姊洪崫銉バ㈤梺甯秮楠炲啯銈ｉ崘鈺佲偓濠氭煢濡警妲烘い鏂挎嚇濮婃椽宕楅梻纾嬪焻闂佺閰ｆ禍鍫曞春閳ь剚銇勯幒鍡椾壕濡炪値鍘鹃崗妯侯嚕婵犳艾围濠㈣泛锕﹂悾鎶芥⒑閸︻厼鍔嬮柛銊ョ仛閹便劑濮€閵堝棌鎷?")
        elif teaching_observations:
            if localized_observation:
                parts.append("")
            else:
                parts.append("濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閹冣挃缂侇噮鍨抽幑銏犫槈閵忕姷顓哄┑鐐叉缁绘帡宕濋幘顔解拺閺夌偞澹嗛ˇ锔姐亜閹存繃顥㈠┑锛勬暬瀹曠喖顢涘槌栧晪闂佽崵濮惧▍锝夊磿閵堝鍊靛Δ锝呭暞閳锋垿鏌涘☉姗堝姛闁瑰啿鍟扮槐鎺旂磼濮楀牐鈧寧顨ラ悙鎻掓殭閾绘牠鏌涘☉鍗炴灈濞寸姵妞藉鍝勑ч崶褏浼勯梺绋款儜缂嶄線宕洪埀顒併亜閹哄棗浜鹃梺鎸庢处娴滎亜顕ｇ拠娴嬫婵﹫绲芥禍楣冩煥濠靛棝顎楀ù婊勭箞閹绠涢敐鍛睄闂佸搫鑻粔褰掑箰婵犲啫绶炴俊顖滃劦閺嬪懏淇婇妶鍥ラ柛瀣仧閺侇噣鏁撻悩闈涚ウ濠碘槅鍨伴惃鐑藉磻閹剧粯鍋ㄦ繛鍫ｆ硶閸斿摜绱撴担钘夌处缂侇喗鐟ラ～蹇旂節濮橆剛锛滃┑鐐叉閸ㄥ綊鎮伴姀鐘斀闁绘劖婢樼亸鍐煕韫囨洖浜剧紒瀣灴閸┿垺鎯旈妸銉ь吅闂佺粯鍔曢悺銊╊敊閸ヮ剚鈷掑ù锝堝Г绾爼鏌涢悩铏鞍闁逛究鍔庨埀顒勬涧閹芥粍绋夊澶嬬厽婵☆垵娅ｉ敍宥囩磼閳锯偓閸嬫挸鈹戦悩鍨毄濠殿喗鎸冲畷鎰磼濡粯鐝烽梺鍝勬储閸ㄦ椽鎮￠弴銏＄厪濠电偛鐏濋崝姘舵煃瑜滈崜娆戠礊婵犲啩绻嗛柣銏㈩焾缁€瀣亜閺嶃劍鐨戦柣銈傚亾闂傚倷绶氬褔鈥﹂崼銉ョ？闂侇剙绉撮悡鏇烆熆閼搁潧濮堥柍閿嬪灴閺屾稑鈹戦崟顐㈠婵炲濮电划宥夊Φ閸曨垱鏅濋柛灞剧⊕闁款厼顪冮妶搴′簻缂佺粯甯炲Σ鎰板箳閹冲磭鍠撻幏鐘差啅椤旂懓浜鹃柟鍓х帛閳锋垹绱撴担濮戭亪鎮橀敃鍌涚叆婵﹩鍘剧粻楣冩煕椤愶絿绠氶悗姘卞閵囧嫰顢旈崟顐ｆ婵犵鈧磭鍩ｇ€规洖宕灒濞撴凹鍨辫ⅸ闂傚倸鍊风粈渚€骞夐敍鍕畳缂傚倷绶￠崰妤呮偡閳哄懏鍋樻い鏇楀亾鐎规洖銈告俊鐑藉Ψ鎼存ɑ娅婇柡灞界Ч瀹曨偊宕熼鐔蜂壕闁告稑锕﹂々閿嬬箾瀹割喕绨奸柍閿嬪灴閺屾稑鈽夊鍫濆闂佸疇妫勯ˇ鐢稿蓟閵娾晛鍗虫俊顖濄€€閸嬫捇寮介銈囩効闂佸湱鍎ら幐楣冩⒔閸曨垱鐓曟繛鎴炩槈閸儱绠紓浣诡焽缁犻箖鏌熼崜褜妫庡瑙勆戠换娑氫沪閸屾埃鍋撻弽顓炵柧闁割偅娲﹂弫濠囨煕閹炬鎷戠槐鎻掆攽閻橆喖鐏辨繛澶嬬洴瀵敻顢楅崟顐ｈ緢濡炪倖甯掗崐鐢稿磻閹捐埖鍠嗛柛鏇ㄥ墰椤︺劑姊洪幖鐐插婵炲皷鈧剚鍤曟い鎰剁畱缁犳盯鏌℃径濠勪虎缂佹劖绋戦—鍐Χ閸℃顫庨梺鍝ュТ鐎涒晝绮嬪鍡愬亝闁告劏鏅濋崢鐢告⒑缂佹ê鐏﹂柨姘舵煟閹烘柨浜剧紒缁樼〒娴滄悂寮介妸锔惧絾闂備線娼уú銈団偓姘嵆閻涱噣骞掗幋顓炴倯闂佹悶鍎滈崘鍓р偓鎾⒒閸屾瑦绁版い鏇熺墵瀹曟澘螖閸涱喖浠梺闈涱槶閸斿孩绂嶅▎鎾粹拻濞达綀娅ｇ敮娑㈡煥閺囨ê鐏╂い顓炴穿椤﹀磭绱掗崒娑樻诞闁轰礁鍊归幈銊╁箛椤忓棛娉垮┑锛勫亼閸婃牠骞愭ィ鍐ㄧ；闁绘劕妯婇崯鍛節闂堟稒鐭楃紒璇叉閺屾稑鈻庤箛锝喰︽繝娈垮枛缁夌敻銆冮妷鈺傚€烽柡澶嬪灩閻熴劑鏌х紒妯煎ⅹ闁宠鍨块幃鈺呭箵閹烘挻顔夋繝鐢靛仜閹冲繘骞戦崶褜娼栫紓浣股戞刊瀵哥磼鐎ｎ偄顕滈柛濠庡灣缁辨挻鎷呮搴″闂佸湱顭堥崯鍧楊敋閿濆绠甸柟鍝勬閺傗偓闂佽鍑界紞鍡樼閻愭牳鍥敊绾拌鲸瀵岄梺闈涚墕濡稒鏅堕柆宥嗙厱閻庯綆鍓欐禒閬嶆煕閳哄倻娲存鐐差儔閺佸倿鎸婃径澶婂闂傚倷鐒﹂幃鍫曞磿閼姐倕绶ゆ繛宸簻绾惧鏌熼幆褏锛嶉柡鍡畵閺屾盯濡烽婊呮殸闂佺妫勯鍛村煘閹达附鍋愰柛顭戝亝濮ｅ嫰姊虹粙娆惧剱闁烩晩鍨堕獮鍡涘炊閵娿儺鍤ら梺鍝勵槹閸ㄥ綊藝椤曗偓濮婅櫣娑甸崨顔兼锭缂備胶濮甸崹鍨嚕娴兼潙唯闁冲搫鍊婚崢鎾绘偡濠婂嫮鐭掔€规洘绮岄～婵堟崉娴ｆ洩绠撻弻娑㈠即閵娿儳浠╃紓浣哄У婵炲﹪寮婚悢鐓庣妞ゆ挾鍋熸禒鈺傜節濞堝灝鏋熼柣鈺婂灠椤繐煤椤忓嫬绐涙繝鐢靛Т閸婂鎮烽幓鎺嗘斀闁绘﹩鍠栭悘顏堟煥閺囨ê鐏查柛銊╃畺閺佸啴宕掑☉妯荤暠婵＄偑鍊栭悧顓犲緤閸欍儳鏄傚┑鐘垫暩婵兘寮幖浣哥；闁绘劕鎼粻浼存煙鐠哄搫顥炲鑸靛姇缁犲鎮归崶顏勭毢妞わ富鍋婂娲捶椤撶偛濡哄銈冨妼閹虫﹢寮荤€ｎ喖鐐婃い鎺嶈兌閸樹粙姊洪崫鍕殭闁绘绮岃灋闁瑰濮风壕濂告煙闁箑鏋涘ù鐙呭缁辨帞绱掑Ο鑲╃杽闂佽鍠曠划娆徫涢崘銊㈡婵°倓绀佹刊浼存⒒娴ｅ湱婀介柛鈺佸瀹曡娼忛埡鍌涙闂佺粯鍔曢悘姘讹綖閺囥垺鐓熼柟閭﹀墻閸ょ喓绱掗埦鈧崑鎾绘⒒娴ｈ鍋犻柛搴㈢矒瀹曠喖顢樺☉妯瑰濡炪倖甯掔€氼參鍩涢幋锔界厱闁挎棁顕ч獮鏍ㄣ亜閿濆懎鎮戠紒缁樼箞婵偓闁宠棄鎳撻埀顒€娼￠弻鐔碱敊閻ｅ本鍣紓浣虹帛缁诲牆鐣峰鈧弫鍌滄崉閵娧勬櫒婵犵绱曢崑鎴﹀磹閺嶎偅鏆滈柟鐑橆檪閸ヮ剦鏁嶆慨姗堢稻閻庡搫鈹戦悙鍙夘棡闁搞劌婀辨竟鏇熺附缁嬭法楠囬梺鍓插亝缁嬫垶淇婇悾宀€纾奸柍褜鍓熷畷濂告偄閸撲胶鐣鹃梻浣告啞閻熴儵藝椤栨稒鍙忕€广儱妫▓浠嬫煟閹邦厽缍戠紒妤佸浮閹藉爼寮介鐔哄帗閻熸粍绮撳畷婊冣槈閵忊€充粡闂佽鍨庣仦鑺ュ€┑鐘灱濞夋盯顢栭崶顒€鍌ㄩ柟鍓х帛閸嬧剝绻濇繝鍌氼伀闁活厽甯為埀顒冾潐濞叉鍒掗幘璇茬畺闁靛繈鍊栭崵鍐煃鏉炴媽鍏岄柕鍫畵濮婄粯鎷呴崨濠呯婵犫拃鍕垫當妞ゎ厼鐏濊灒闁兼祴鏅濋悞濂告⒑閸涘﹤濮﹀ù婊勭墵瀹曟垿骞樼紒妯轰画闂佸搫顦伴娆徫涘畝鍕拺闁告縿鍎辨牎闂佺粯顨嗗ú鐔煎春閵忋倕绠婚悹鍥у棘閳哄懏鐓忓鑸得弸鐔兼倵闂堟稓鐒告慨濠冩そ濡啫鈽夊顒夋毇婵犵妲呴崑鍛存偡瑜庣粩鐔煎即閵忊€充缓闂佸憡绋戦敃锕傚储闁秵鐓熼幖鎼灣缁夌敻鏌涚€ｎ亝鍣归柣锝呭槻閻ｆ繈宕熼鍌氬箰闂佽绻掗崑鐔尖€﹂崼鐔告珷闁哄被鍎查悡娆戔偓鐟板婢ф宕抽悾宀€纾兼い鏃傛櫕閹冲嫰鏌熼娑欘棃妤犵偞锕㈠畷妤呭川椤撗勵棥闂傚倸鍊烽懗鍫曪綖鐎ｎ喖绀嬮柛顭戝亞閺嗐儳绱撻崒娆掑厡濠殿噣娼ч…鍨潨閳ь剟宕洪悙鍝勭闁挎棁妫勬禍褰掓⒑閸︻厾甯涢悽顖涱殔閳绘捇宕奸弴鐔叉嫼缂傚倷鐒﹂…鍥╃不閹剧粯鐓熼柡宓礁浠悗娈垮枦椤曆囶敇閸忕厧绶炲┑鐘插暙缁佽埖淇婇悙顏勨偓鏍箰妤ｅ啫纾绘俊顖濆吹閻濆爼鏌￠崶鈺佷汗闁衡偓娴犲鐓熼柟閭﹀墮缁狙囨煕閿濆懐绉洪柡宀€鍠栭幖褰掝敃椤掑啠鍋撶捄銊㈠亾濞堝灝鏋︽い鏇嗗浂鏁囬柛蹇曞帶缁剁偤鎮楅敐搴濈敖婵＄虎鍠栭埞鎴︽偐椤旇偐浼囬梺绯曟櫆閻楃偤骞楅锔解拺閻庡湱濯崵娆撴煟濡も偓濡粓鎮橀崘顔解拺缂備焦锕懓鎸庣箾娴ｅ啿瀚々鐑芥煥閺囩偛鈧綊鎮￠妷鈺傜厸闁搞儺鐓侀鍫熷€堕柡灞诲劜閻撶喐绻涢幋婵嗚埞婵炲懎绉堕埀顒冾潐濞叉牠鎮ラ崗闂寸箚闁归棿鐒﹂弲婵嬫煃瑜滈崜鐔笺€侀幘璇茬闁告挷鑳堕敍婵囩箾鏉堝墽鍒板鐟帮躬瀹曟洝绠涘☉娆戝幗闂婎偄娲﹀鑽ょ不閻愮儤瀵犻柣鏂垮悑閸婄敻鏌ㄥ┑鍡涱€楀褎澹嗛惀顏堝矗閵壯呯厯闂佸搫鏈粙鎾寸閿曞倸绠查柟閭﹀墻濡喖姊绘笟鈧埀顒傚仜閼活垱鏅舵导瀛樼厱闊洦妫戦懓鎸庮殽閻愭彃鏆ｉ柟顔界懇閹粌螣缂佹褰囬梻鍌欑窔閳ь剛鍋涢懟顖涙櫠閹绢喗鐓ユ繝闈涚墕娴犫晝绱掗悩宕団槈闁宠棄顦埢搴ょ疀鎼达絾鏆伴梻鍌氬€搁崐椋庢閿熺姴鐭楅煫鍥ㄦ煣缁诲棝鏌涢妷顔煎缂佲偓婢跺备鍋撻悷鏉款仾濠㈢懓顑夊銊︾鐎ｎ偆鍘介梺褰掑亰閸撴瑧鐥閵囧嫰濡疯娴犻亶鏌″畝鈧崰鎾诲窗婵犲洤纭€闁绘劖澹嗛弫鏍磽閸屾瑦绁板ù婊庡墴瀹曟垿濡堕崪浣告婵炲濮撮鎰板极閸ヮ剚鐓熼柡鍌涘閹牓鎮介鐐电暫婵﹦绮换婵囨償閳ヨ尙鐩庢繝鐢靛仜閻即宕愬┑瀣ㄢ偓渚€寮介鐐茬獩闂佸搫顦伴崹褰掑礉閿曗偓椤啴濡堕崱妤冪憪闂佺粯甯俊鍥╁垝閸儱鐒垫い鎺戝閳锋垿寮堕悙鏉戭棆閻犳劒鍗抽弻娑㈡晲韫囨洖鍩屽銈庡亜缁绘帞妲愰幒鎳崇喖鎳栭埡鍌氭疄闂傚倷绶氶埀顒傚仜閼活垱鏅堕濮愪簻妞ゆ挾鍋炵粚鎸庛亜閿曗偓缂嶅﹪骞愭繝鍌楁斀闁搞儯鍎扮花濠氭⒑鐟欏嫬鍔ょ€规洦鍓熼幃姗€鍩￠崘顏咃紡闂佽鍨庨崟顐℃樊闂備礁鎼惉濂稿窗閺嵮呮殾婵犲﹤瀚刊鎾煟閹寸倖鎴﹀疮閹烘鈷掑ù锝堝Г閵嗗啰绱掗埀顒佺瑹閳ь剙鐣烽幇鏉块敜婵°倐鍋撻柦鍐枛閺屾洟宕煎┑鍥舵！闂佸憡鐟ョ换姗€寮婚悢鍏肩劷闁挎洍鍋撻柛妯绘尦閺屾稓鈧綆鍋呯亸顓㈡懚閺嶎厽鐓曢柟鎵暩閸樻稒淇婇锝囩煁缂佺粯绋撻埀顒傛暩椤牆鐡俊鐐€栭崹闈浳涘┑瀣畺闁跨喓濮撮崡鎶芥煏韫囧ň鍋撻弬銉ヤ壕闁割偅娲橀悡鐔兼煙闁箑骞楃紓宥嗗灩缁辨帡鍩€椤掑嫬绀冩い顓熷灩閸炵敻鏌ｉ悢鍝ユ噧閻庢碍鎮傞幊鎾诲锤濡や胶鍘搁柣蹇曞仧閺咁偄鏆╂俊鐐紘閸屾粎鐛㈤梺鍝勬湰閻╊垶鐛Ο灏栧亾闂堟稒鍟為柛鎺撶洴閹鈻撻崹顔界彯闂佺顑呭Λ婵嬬嵁韫囨稒鍋愮€瑰壊鍠栭弲鐘差渻閵堝棙鐓ラ柛姘儔椤㈡﹢宕稿Δ浣叉嫽婵炶揪绲介幉锛勬嫻閿涘嫮纾兼い鏇炴噹閻忥綁鏌℃笟鍥ф珝闁糕晪绻濆畷銊╊敊闂傚鏆楅梻鍌欑窔濞佳囁囬锕€鐤炬繝濠傜墛閸嬪倿鏌￠崶鈺佹瀭濞存粍绮撻弻鐔煎级閸噮鏆㈤梺璇″枦閸嬫劗妲愰幒妤佸亹闁惧浚鍋勭壕鎶芥⒑閸濆嫮鐒跨紒鏌ョ畺楠炲棝寮崼顐ｆ櫓闂佺粯鎸稿ù鐑筋敊閹扮増鈷掑ù锝呮憸閺嬪啯銇勯銏╂█鐎规洖缍婂畷绋款渻鐏忔牕浜惧ù锝囩《閺嬪酣鏌熼幑鎰彧妞ゃ儲绻堝娲濞戞艾顣洪柣搴㈠嚬閸犳顭囨繝姘睄闁割偆鍟块幏缁樼箾鏉堝墽鍒伴柟璇х節瀹曨垶鎮欓悜妯煎弳闂佸搫娲﹂敋闁诲浚鍠氱槐鎺楊敊绾拌京鍚嬮悗娈垮枙缁瑩銆佸鈧幃娆戔偓娑欘焺濮樿埖鈷掑〒姘ｅ亾婵炰匠鍛床闁割偁鍎辩壕褰掓煛閸モ晛啸閻忓繒鏁搁埀顒€绠嶉崕閬嵥囨导瀛樺亗闁哄洨鍠嗘禍婊堟煙閹佃櫕娅呴柍褜鍓氬ú鐔奉嚕閹间礁绫嶉柛顐ゅ枔閸樺崬鈹戦埥鍡楃仯缂侇噮鍨伴悾宄扮暆閸曨剛鍘靛銈嗘⒒閸樠兾ｇ紒妯镐簻妞ゆ挻绮屾慨鍌溾偓瑙勬礈閸犳牠銆佸鈧幃鈺呮濞戞绶熼梻鍌欐祰椤曆冾潩閿曞偊缍栧璺衡姇閸濆嫀鐔兼偂鎼达紕浜伴柣搴″帨閸嬫捇鏌涢弴鐐差暢缂佸绻愰埞鎴︽偐缂佹ɑ閿┑鐐额嚋婵″洨妲愰悙鍝勭倞妞ゆ帊鑳堕崢鎾绘⒑閸涘﹦绠撻悗姘煎墴瀵娊鎮㈤崗鑲╁幈濠殿喗顨呭Λ妤呮倶閻樼粯鐓冮悷娆忓閻忔挳鏌熼瑙勬珚妞ゃ垺鐟╅幊鏍煛閳ь剛妲愬鈧缁樻媴閾忓箍鈧﹪鏌￠崨顔剧煉闁诡啫鍥ㄥ亹闁肩⒈鍓氬▓鎯р攽閻樼粯娑фい鎴濇瀵彃鈹戠€ｎ偆鍘遍柣蹇曞仜婢т粙銆傞弻銉︾厽閹兼惌鍠栨晶瀛樻叏婵犲懏顏犵紒顔界懅閹瑰嫰濡歌缁辨﹢姊绘担渚劸妞ゆ垵娲畷鎴﹀Χ婢跺﹦鐣洪梺璺ㄥ枔婵挳宕￠幎鑺ョ厽闁哄啫娲﹂鐘炽亜閺冣偓濞茬喎顫忓ú顏呭仭闁规鍠楅幉鑲╃磽娴ｇ瓔鍤欓柛濠傛健楠炲﹤顭ㄩ崱鎰睏闂佸湱鍎ら幐楣冨储娴犲顥婃い鎰╁灪婢跺嫰鏌熼崨濠冨€愰柟铏矎閵囨劙骞掗幙鍐┾挅濠电姰鍨奸崺鏍礉閺嶎厽鍋傞柡鍥ュ灮閸欐捇鏌涢妷锝呭閻忓浚鍙冮弻鐔碱敊閽樺浠肩紓浣介哺鐢繝宕洪埀顒併亜閹烘垵顏╅柣鎺戠仛閵囧嫰骞掗幋婵愪痪闂佹娊鏀遍崹鍧楀箖濡ゅ懎鎹舵い鎾跺剱閳ь剙鏈换娑㈠礂閻撳骸顫掗梺鍝勬湰閻╊垱淇婇幖浣肝ㄧ憸宥夋偂閻斿吋鈷戠紓浣姑肩欢閬嶆煕閻樻剚娈橀柟骞垮灩閳规垹鈧綆浜為崐鐐烘⒑闂堟丹娑㈠礃閵娧呮澖婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌熺紒銏犳灈闁汇値鍣ｉ弻锝呂旈埀顒勬偋婵犲倵鏋嶉柣妯煎仺娴滄粓鐓崶銊﹀鞍闁革絽鍢查湁婵犲﹤瀚惌瀣煏閸パ冾伃妤犵偛娲畷婊勬媴閻熼杩樼紓鍌氬€烽懗鑸垫叏閻戣棄纾绘繛鎴欏灩閻撴﹢鏌熸潏鍓х暠闁绘帗妞介弻娑㈠箛閵婏附鐝旈梺閫炲苯澧柛鏃€娲熼崺鐐哄箣閿旇姤娅栭梺鍛婃处閸嬪嫰鐛€ｎ偆绡€婵炲牆鐏濋弸鎾绘煕鐎ｎ偅宕屾慨濠冩そ楠炴劖鎯旈敐鍌涱潔闂佽瀛╅崙瑙勭閻愮儤鍤嶉梺顒€绉寸粻缁樸亜閺冨泦鎺楀箯婵犳碍鈷戠紒瀣濠€浼存煟閻旀潙濮傜€规洘顨呴悾婵嬪礋椤掑倸骞嶉梻浣瑰劤濞存岸宕戦崨顓犳殾閻忕偘鍕樻禍婊堟煏韫囧ň鍋撻崘鍙夋嚈婵＄偑鍊戦崹娲晝閵忋倕绠栭柕蹇嬪灮閻瑩鏌涢…鎴濇灆缂佽京鍠栧濠氬磼濞嗘劗銈板銈庡亜椤﹂潧鐣烽弴銏犵闁稿繒鍘у鍧楁⒑闂堟稓澧曟い锔诲灣婢规洝銇愰幒鎾跺幈濡炪値鍘介崹鐢稿几閹剧粯鐓涢柍褜鍓氱粋鎺斺偓锝庡亞閸樿棄鈹戦埥鍡楃仩闁圭⒈鍋嗛惀顏囶槾闁逞屽墰閹虫捇骞夐敍鍕床闁割偁鍎遍拑鐔哥箾閹寸們姘跺几鎼淬劍鐓欓梺顓ㄧ畱楠炴牜鐥悙顒€鈻曟慨濠冩そ瀹曨偊宕熼浣瑰闂備胶鍎甸弲鈺呭垂鏉堛劎鈹嶅┑鐘叉处閸婅崵绱掑☉姗嗗剱闁哄應鏅犲铏规嫚閳ュ磭鈧鏌涢幇鈺佸闁肩缍婂濠氬磼濮橆兘鍋撻悜鑺ュ€块柨鏇炲€哥粻鏍煕椤愶絾绀€缁炬崘顫夋穱濠囧Χ閸涱喖娅ｇ紓浣瑰姈椤ㄥ﹪鐛弽顬ュ酣顢楅埀顒佷繆閻戣姤鐓冪憸婊堝礈閵婏缚绻嗛柛銉墮缁犳煡鏌涢弴銊ョ仩閹喖姊洪幐搴㈢５闁稿鎸鹃惀顏嗙磼閵忕姷浠紓浣虹帛閻╊垶鐛鈧鍫曞箣濠靛洨妲楅梻鍌欑劍閹爼宕濈€ｎ喖纭€闁告劘灏欓弳锔界節婵犲倻澧曠紒鐙€鍣ｉ弻銈夊箒閹烘垵濮夐梺褰掓敱濡炰粙骞冨Δ鍐╁枂闁告洦鍓涢ˇ銉モ攽閻愯尙婀撮柛鏂块叄瀵偊顢欑亸鏍潔闂侀潧楠忕槐鏇㈠储閹间焦鐓熼煫鍥ㄦ礀娴犫晜銇勯弴鍡楀閸欏繘鏌涚仦鎯х劰闁衡偓娴犲鐓冮柍杞扮閺嗙偤鎮樿箛銉╂妞ゃ劊鍎甸幃娆撳级閹寸偠鐧佹俊銈囧Х閸嬫盯顢栨径鎰┾偓浣割潨閳ь剟骞冮姀鐘垫殝闁哄鐏濋柌婊冣攽閻樻鏆滅紒杈ㄦ礋瀹曟垿骞嬮敃鈧壕褰掓煛瀹ュ骸浜濋柡鍡樼矒閺岀喖鎮滃鍡樼暦闂佸搫鎳忕换鍫ュ蓟閺囥垹閱囨繝闈涙祩濡繝姊洪崨濠勬噧缂佺粯鍨归幑銏犫槈閵忕姷顓洪梺缁樺姇椤曨厼鈻撻妶鍥╃＜闁绘劦鍓欑粈鍐╀繆椤愩垹顏繝鈧笟鈧娲箰鎼达絿鐣靛┑鈽嗗亝椤ㄥ牆顕ユ繝鍕珰閻熶椒鑳堕幊鎾烩€﹂妸鈺佸窛妞ゆ挻绻傞ˉ姘辩磽閸屾瑨鍏岀紒顕呭灣閹广垽宕奸悢绋垮伎闂侀€炲苯澧撮柡灞诲妼閳规垿宕卞Ο鐑橆仱闂備礁鎲￠敃鈺呭磻婵犲偆娼栨繛宸簻瀹告繂鈹戦悩鎻掓殜闁瑰嘲缍婂铏圭磼濮楀棙鐣兼繝鐢靛亹閸嬫挸螖閻橀潧浠滈柛鐔告尦瀹曡銈ｉ崘銊︻棟闂侀潧顧€婵″洭鍩€椤掆偓椤嘲顫忛搹瑙勫枂闁告洦鍋勬慨銏狀渻閵堝棙澶勯柛娆忓暙閻ｇ兘濮€閵堝棭妫冨┑鐐村灱妞村摜鈧潧鐭傚娲濞戞艾顣哄┑鈽嗗亝閻熝勭閹间焦鍋ㄩ柛娑橈功閸橀亶姊虹紒妯忣亜顕ｉ崼鏇炵闁挎繂娲ㄧ壕鍏笺亜閺囩偞鍣圭€殿噮鍠楅〃銉╂倷閺夋垶璇炲Δ鐘靛仜椤戝顕ｉ鈧崺鈧い鎺戝濡﹢鏌嶈閸撴碍绌辨繝鍥ㄥ€锋い蹇撳閸嬫捇寮借濞兼牕鈹戦悩瀹犲缂佺姷濞€閺岀喖骞嗚閸ょ喐銇勯埡鍌滃弨闁哄本鐩獮妯何旈埀顒勫箠閹扮増鏅繝闈涱儐閳锋垹绱掔€ｎ偄顕滄繝鈧导瀛樼厾鐟滅増甯為悾娲煕閳规儳浜炬俊鐐€栫敮鎺楀磹閹间礁鍌ㄩ柟缁㈠枟閻撴瑩鏌ц箛锝呬航婵炲牊绮庨埀顒冾潐濞叉鍒掑澶婄闁告侗鍨抽惌娆撴偣閹帒濡洪柛鐘诧工閳规垿鏁嶉崟顐℃澀闂佺锕ラ悧鐘诲箖瑜嶉…銊╁醇濠靛牞绱遍梻浣虹帛閸旀洟骞栭锔藉仾闁绘劦鍓涚弧鈧梻鍌氱墛娓氭宕曢幇鐗堢厽闁规儳纾粻濠氭煟閹垮啫浜扮€规洘鍎奸¨渚€鏌涙惔锛勭闁哄苯绉烽¨渚€鏌涢幘纾嬪閻撱倝鏌ｉ弮鍌氬付缂佺媭鍨堕弻鐔告綇妤ｅ啯顎嶉梺绋款儏鐎氫即寮诲☉婊呯杸婵﹩鍏涘Ч妤呮⒑閸涘⊕顏勭暦椤掑嫬鐓橀柟杈鹃檮閸婄兘鏌℃径瀣仼濞寸姷顭堥—鍐Χ鎼粹€崇濠电偛妯婇崣鍐偘椤斿槈鏃堝川椤旈棿姹楃紓鍌氬€烽悞锕傗€﹂崶顒€鍌ㄩ梺顒€绉甸悡鐔煎箹閹碱厼鐏ｇ紒澶愭涧闇夋繝濠傚閻帗銇勯姀鈩冾棃妞ゃ垺娲熼弫鍌炴偩鐏炶棄绗氶梺鑽ゅ枑缁秶鍒掗幘宕囨殾婵犲﹤鍟犲Σ鍫ユ煏韫囨洖啸闁汇倕娲铏规喆閸曨偄濮㈤梺璇茬箰閻楁挸鐣烽幋锕€绠婚柟棰佺劍閸嶉潧顪冮妶鍡楀闁搞劌婀辩划濠囶敋閳ь剟骞冨Δ鍐╁枂闁告洦鍓涢ˇ銊╂⒑閹肩偛濡煎褍閰ｉ獮鎴﹀閻橆偅鏂€闁诲函缍嗘禍鐐哄磹閻愮儤鍋℃繝濠傚閻忓鈧娲樺浠嬪箖濞嗘挻鍊绘俊顖炴敱鐎氳偐绱撻崒姘偓鐑芥倿閿曞倹鏅梻浣筋嚙妤犲繘姊介崟顖毼﹂柛鏇ㄥ灱閺佸洭鏌ｉ幇顓熺稇缂佹劖绋撶槐鎾寸瑹閸パ勭亾缂備緡鍣崹鑸典繆閸洘鏅插璺猴功椤︺劑姊洪崘鍙夋儓闁哥噥鍋婇悰顕€骞囬鑺ユ杸闂佺粯锕╅崰鏍倶鏉堛劎绠惧璺侯儑濞插瓨銇勯姀锛勫⒌鐎规洏鍔庨埀顒佺⊕閿氶柍褜鍓欓悥濂稿蓟閺囩喎绶為柛鈩兩戦悵鏇㈡⒑缂佹ɑ灏伴柣鐕傜畵婵＄敻宕熼姘辩潉闂佹悶鍎洪悡鍫澪涢崟顖涒拺閻犲洩灏欑粻姘舵煛閸涱垰鈻堢€殿喖顭烽弫鎰緞婵烆潿鍔嶉妵鍕棘濞嗗墽鍚嬮梺绋款儐椤ㄥ﹪骞冨Δ鈧埢鎾诲垂椤旂晫浜┑鐘媰閸愵喖寮板Δ鐘靛仦閸ㄥ灝鐣烽悢纰辨晬婵絽鐨烽弲鐘诲蓟閻旂厧绠ラ柧蹇ｅ亝閻濇棃姊虹拠鑼閻忓繑鐟╅崺鈧い鎺戝枤濞兼劖绻涘ù瀣珖闁瑰箍鍨归埞鎴犫偓锝庝海閹芥洟姊虹化鏇炲⒉妞ゃ劌绻樺畷銉р偓锝庡枟閻撴洟鏌嶉埡浣告殶闁瑰啿鍟〃銉╂倷閼碱儷褎鎱ㄦ繝鍐┿仢鐎规洦鍋婂畷鐔煎垂椤愬稄绠撳铏圭磼濮楀棙鐣跺┑鈽嗗亝閻熲晛顕ｉ弻銉﹀殝闁汇垺顔栧ù鍕煟鎼搭垳绉甸柛瀣缁傛帗绺介崨濞炬嫽婵炴挻鑹惧ú銈嗘櫠椤斿墽纾煎璺烘湰閺嗩剟鏌熼鍡欑瘈鐎殿喗鎸抽幃銏ゆ惞鐠団€虫櫗闂傚倷鑳剁涵鍫曞礈濠靛鈧啯绻濋崶銊ヤ粧濠电姴锕ら悧濠囁夋繝鍐︿簻闁圭儤鍩堝Σ绋款熆瑜庨幐鎶藉蓟閿涘嫪娌紒顖涙礀娴滃墽鈧娲栧ú锕€鈻撻弴銏＄厽閹兼惌鍨崇粔鐢告煕閹惧顬奸柍顏堟涧閳规垶骞婇柛濠冾殕閹便劑鎮滈挊澶岋紱濠电偞鍨堕埣銈吤洪宥嗘櫍闂佺粯鍔曠粔鐢告儎椤栨氨鏆︽慨妞诲亾濠碘剝鎮傛慨鈧柍钘夋缂嶅苯鈹戦悩鎰佸晱闁哥姵顨婇妴鍐川椤撳洦绋戦埢搴☆嚗濠靛棛绉虹€规洖鐖奸崺锟犲礃椤忓海闂梻鍌欒兌椤牓寮甸鍕殞濡わ絽鍟悞鍨亜閹烘垵鈧悂宕㈤幘顔界厵闁惧浚鍋掑▓婊呪偓瑙勬礀閵堢顕ｉ幘顔藉亜缂佸鐏濇慨鍐⒒娴ｇ儤鍤€闁告艾顑夐幃楣冾敂閸繄顦悗鍏夊亾闁告洦鍋勯悗顓㈡⒑缁嬫寧婀板瑙勬礋瀹曟垿骞橀懜闈涙瀭闂佸憡娲﹂崜娑⑺囬妷銉㈡斀闁绘劙顤傞崵瀣磼閻樿櫕宕岄柡浣瑰姍閹瑩宕崟顐㈢ギ闂備線娼ф蹇曟閺囥垹鍌ㄩ柣銏犳啞閳锋垹绱撴担濮戭亪鎮橀敃鍌涘珔闂侇剙绉甸悡鐔兼煙閹屽殶婵炲弶鎸抽弻锛勪沪閸撗佲偓鎺楁煃瑜滈崜銊х礊閸℃稑纾婚柛娑卞幘閺嗭妇鈧厜鍋撻柛鏇ㄥ墰閸樺憡绻涙潏鍓ф偧闁硅櫕鎸婚幈銊╁醇閵夛妇鍘靛銈嗙墬缁嬫帡藟閸儲鐓曢柕濞炬櫇閻ｇ儤顨ラ悙鍙夊闁瑰嘲鎳橀弻鍛槈濞嗗繑鏁繝鐢靛Х閺佸憡鎱ㄩ悜钘夋瀬闁归棿绀佺壕缁樼箾閹存瑥鐒洪柡浣割儐閵囧嫰骞樼捄鐑樼€鹃梺鍛婄懃缁绘ê顫忔繝姘唶闁绘柨澧庣换浣糕攽閻愬瓨宕勬い鏇嗗洦绠掗梻浣虹帛閿氭俊顖氾躬瀹曟洝绠涘☉娆戝弮?")
        elif summary:
            parts.append(localized_summary or "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；闁绘劗鍎ら崑瀣煟濡崵婀介柍褜鍏涚欢姘嚕閹绢喖顫呴柍鈺佸暞閻濇洟姊绘担钘壭撻柨姘亜閿旇鏋ょ紒杈ㄦ瀵挳濮€閳锯偓閹风粯绻涙潏鍓у埌闁硅绻濆畷顖炴倷閻戞鍘遍梺鍝勫暞閹搁箖鎮鹃悽纰樺亾鐟欏嫭纾婚柛妤€鍟块锝嗙鐎ｅ灚鏅濋梺闈涚箚閺呮粓藟閳ユ枼鏀介柣妯虹仛閺嗏晛鈹戦鐐毄闁哥姴锕ら鍏煎緞鐎ｎ亙绨垫繝鐢靛仜濡瑩骞愭繝姘亗婵炲棙鎸婚崑鈩冪箾閸℃绠版い蹇婃櫅閳规垿顢氶崱娆戞殼闂佸搫鏈惄顖涗繆閸洖骞㈡繛鍡樺姇濞呮绱撻崒娆愮グ濡炴潙鎽滈弫顕€鏁撻悩鑼暫濡炪倕绻愮€氀囧几鎼淬劎鍙撻柛銉ｅ妽閻撱儲銇勯敂瑙勬珚婵﹨娅ｇ槐鎺懳熺拠鑼暡闂備礁鎽滈崰鎰板箰閸愬樊鍤曢悹鍥ㄧゴ濡插牊淇婇鐐存暠闁哄倵鍋撻梻鍌欒兌绾爼宕滃┑瀣ㄢ偓鍐疀閺冨偆娴勬繝闈涘€搁幉锟犲煕閹达附鈷戞い鎰╁€曟禒婊堟煠濞茶鐏￠柡鍛埣椤㈡盯鎮欑€电骞嶆俊鐐€栧濠氬储瑜旈崺鈧い鎺嗗亾婵炵》绻濋幃浼搭敋閳ь剙鐣峰鈧俊鍛婃償閿濆懏鐏佺紓浣介哺鐢帟鐏掗梺鍏肩ゴ閺佲晠濡舵径瀣ф嫽婵炶揪绲块…鍫ュ汲闁秵鐓欑痪鏉垮船娴滄壆鈧娲﹂崹杈┾偓浣冨亹閳ь剚绋掕摫婵炲懏鐗曢埞鎴︽偐鐠囇冧紣闂佺娅曢崝妤佺珶閺囩喓顩烽悗锝庡亞閸橀亶鏌ｈ箛鏇炰粶濠⒀傜矙楠炲﹪宕ㄧ€涙鍘遍梺鍝勫€藉▔鏇熺墡闂備線娼уú銈団偓姘嵆閵嗕礁顫滈埀顒勫箖濞嗘挸绾ч柟鎼幗琚╅梻鍌氬€风粈渚€骞栭锕€绠犻幖娣妽閸嬪鈹戦崒婊庣劸缂佺姵鐗犻弻锝夋晲閸涙澘顏梺鍝勵儏閻楀﹥绌辨繝鍥舵晬婵犻潧娲㈤埀顒€鍟…璺ㄦ喆閸曨剛顦ラ梺瀹狀潐閸ㄥ潡骞冨▎鎾村殤妞ゆ巻鍋撴い锝嗘そ濮婅櫣鎷犻懠顒傤唹缂備浇顕ч悧鍡涱敋閿濆洨鐭欓幖瀛樻尰椤秹姊洪棃娑㈢崪缂佽鲸娲熷畷銏＄鐎ｎ偀鎷洪梺鍛婄箓鐎氼噣鍩㈡径鎰厱閻庯綆浜滈顐︽煛娓氬洤娅嶉柟铏矒閹瑩鏌呭☉姘辨晨濠碉紕鍋戦崐鏍ь啅婵犳艾纾婚柟鍓х帛閻撱儵鏌￠崶顭嬵亪宕濆顓滀簻妞ゆ挾鍋炵粚璺ㄧ磼閻樺磭鈽夐柍钘夘槸铻ｆ繝褏鍋撳▍濠囨煛鐏炶濡奸柍瑙勫灴瀹曞崬螖婵犱胶纾婚梻鍌欒兌閸庣敻寮插☉銏＄厐闁挎繂鎷嬪鏍磽娴ｈ偂鎴炲垔閹绢喗鐓曟繛鎴烇公閺€濠氭煕鎼淬垺宕屾慨濠呮缁瑩宕犻埄鍐╂毎闂備浇顕栭崰鏍磹閸ф宓侀柛鎰╁壆閻旂儤鍋橀柍鈺佸暞閺夋悂姊虹拠鎻掑毐缂佽弓绮欓幃妯侯潩鐠鸿櫣鏌у┑鐘诧工閸犳艾銆掓繝姘厪闁割偅绻冮ˉ婊冣攽椤旂厧鈧潡寮诲☉娆戠瘈闁告劗鍋撻悾鍏肩節閵忥綆娼愭繛鍙夘焽缂傛捇鎮惧畝鈧惌娆撴偣閹帒濮傞柣娑欐崌濮婄粯鎷呯粙娆炬闂佺顑呴幊鎰垝濞嗘挸绠ｉ柣鎰缁犳岸姊虹粙璺ㄧ闁稿鍔楃划缁樸偅閸愨晝鍘电紒鐐緲瀹曨剟鐛弽顓熺厸閻庯絻鍔岄埀顒佺箞瀵顓奸崼顐ｎ€囬梻浣告啞閹歌崵鎹㈤崼銉︽櫜闁绘劖娼欑欢鐐测攽閻愭潙绗掗柟纰卞亰閿濈偛顭ㄩ崼婵堝姦濡炪倖甯掔€氼剟寮告笟鈧弻娑㈠箛闂堟稒鐏堝銈庡亜閹虫﹢寮婚弴銏犻唶婵犻潧妫欏▓婊堟⒑缁嬫鍎愰柟姝屽吹缁參鎮㈤悡搴ｅ姦濡炪倖宸婚崑鎾淬亜閺囶亞绉い銏″哺閸┾偓妞ゆ巻鍋撻柣锝囧厴閹剝鎯斿Ο缁樻澑闂備礁澹婇崑鎺楀磻閸涱喗娅忔繝鐢靛Х椤ｎ喚妲愰弴銏犵；闁硅揪绠戠壕褰掓煛瀹ュ骸浜濋柡鍡樼矒閺岀喖鎮滃鍡樼暥缂佺偓鍎冲﹢閬嶅箟閹间焦鍋嬮柛顐ｇ箘閻熸煡姊虹粙鍖″伐闁诲繑宀告俊鐢稿礋椤栨艾宓嗗┑掳鍊愰崑鎾趁瑰鍕姢闁宠鍨块、娆戞兜瀹勬澘顫犵紓鍌欑贰閸ｎ噣宕归崼鏇犲祦闊洦绋戝婵嬫倵濞戞顏堟儌閸曨剛绡€闁靛骏绲剧涵楣冩煥閺囨ê鍔︾€规洘娲熼、鏃堝礋閵婏附鏉搁梻浣虹帛钃遍柛鎾村哺瀹曨垵绠涘☉娆戝幈闂佺粯蓱閸撴艾鈻撻弮鈧妵鍕敇閻愬瓨鎮欓梺瀹狀嚙闁帮綁鐛€ｎ亖鏀介柛鈩冪懄閻擄綁姊婚崒姘偓鎼佸磹妞嬪孩顐芥慨姗嗗墻閻掔晫鎲搁弮鍫濈畺鐟滄柨鐣烽崡鐏诲綊寮堕幐搴☆槱闁诲酣娼ч妶绋款嚕閸洖绠ｉ柣娆忔噽楠炪垽姊婚崒娆戠獢婵炰匠鍥ㄥ亱闁糕剝铔嬮崶銊ヮ嚤閻庢稒锚娴滄妫呴銏″闁瑰憡鎸冲銊︾鐎ｎ偆鍘介梺褰掑亰閸ㄤ即鎯冮崫鍔藉綊鎮╅鑲╀紙闂佸搫鏈惄顖炵嵁濮椻偓楠炲洦鎷呴崫鍕€梻鍌欑閹碱偆鎮锕€绀夌€光偓閸曨偆鍘撮梺纭呮彧缁犳垿鐛姀銈嗙厓闁告繂瀚埀顒佸姍閺佸倿宕滆閿涙繃绻涙潏鍓у埌闁圭⒈鍋婇、鎾诲箻閸撲胶锛濋悗骞垮劚鐎氼喚绮ｉ弮鍌楀亾濞堝灝鏋涙い顓㈡敱娣囧﹪骞栨担鍝ュ幐婵炶揪缍€濞咃絽顭囨径鎰拻濞达綀顫夐崑鐘绘煕鎼淬垺銇濋柟顔矫埞鎴犫偓锝庝簽椤旀帡鏌ｆ惔銊︽锭闁硅姤绮撻、娆撳即閵忊檧鎷洪梺鍛婄☉閿曪絿娆㈤柆宥嗙厱闁绘ê纾。鏌ユ煛閸涱厾鍩ｉ柟顔荤矙瀹曘劍绻濋崟顐㈢闂佽楠搁崢婊堝磻閹剧粯鍊甸柨婵嗛婢ф壆鎮敐鍥╃＝闁稿本鐟ㄩ崗灞解攽椤旂偓鏆柟顖氬椤㈡稑顫濋悡搴㈩吙闂備礁婀遍搹搴ㄥ窗濡ゅ懎纾归柣鎴ｅГ閻撴稑顭跨捄渚剰妞ゆ洘绮撻弻鐔轰沪閸屾氨浠奸梺瀹狀潐閸ㄥ潡骞冮埡浣叉灁闁圭瀛╅惁婊勭節绾版ê澧茬憸鏉垮暣楠炲﹤螣閾忚娈鹃梺纭呮彧缁犳垹绮堢€ｎ偁浜滈柟鎯ь嚟閳藉霉濠婂懎浜鹃柟渚垮妼铻ｉ柣鎾抽娴犳ɑ绻濋埛鈧崟顒€鍞夐梺鍝勬湰閻╊垶宕洪悙鍝勫瀭妞ゆ梻鍘ч～姘舵煟鎼达紕浠涙繝銏☆焽閳ь剚鍑归崣鍐嵁閸℃稑绫嶉柛顐亝閺呪晠鏌ｉ悢鍝ユ嚂缂佹煡绠栭幃妤呭箹娴ｅ厜鎷婚梺绋挎湰閼归箖鍩€椤掆偓閸㈡煡婀侀梺鎼炲労閸擄箓寮€ｎ喗鐓涚€广儱楠搁獮鏍磼閹邦収娈曢柟渚垮妼铻ｉ柟绋挎捣閵嗘劗绱撴担鎻掍壕闂佺鏈粙鎰崲閸℃ǜ浜滈柡宥冨妿閹冲棙銇勯幒鏂挎灈闁哄本鐩俊鍫曞幢濡⒈妲归梻浣告惈婢跺洭宕滃┑鍡╁殫闁告洦鍘搁崑鎾绘晲鎼存繄鏁栭梺鍛婃⒒椤牓鍩為幋锔藉€烽柤纰卞墯閻т線姊洪崫鍕櫤缂佸鍨甸悾鐢稿礋椤栨稓鍘介棅顐㈡处濞叉牗绂掑鍐剧唵鐟滄垶鎱ㄩ妶澶婄柧闁割偅娲﹂弫鍡涙煕鐏炲墽鈽夊ù鐘茬箻濮婃椽骞愭惔銏㈩槬闂佺锕ょ紞濠囧春濞戙垹绠ｉ柨鏃囨娴狀垶姊洪幖鐐插姌闁告柨鐬煎濠勭磼濡晲绨婚梺鐟版惈椤戝懘鎮橀鍫熺厪闁搞儜鍐句純閻庢鍣崳锝夊春閳ь剚銇勯幒鎴濐仾闁稿顑夐弻锝呂熼崹顔炬闂佸搫妫寸粻鎾诲蓟閳╁啫绶炲┑鐘插閻ㄦ垵鈹戦埄鍐ㄧ祷闁绘锕﹂幑銏犫槈閵忕姴鑰垮┑鈽嗗灠閹碱偊锝炲畝鍕€垫繛鍫濈仢閺嬫稒绻涚亸鏍ゅ亾閹颁焦缍庡┑鐐叉▕娴滄繈藟閸喓绠鹃柟瀵稿仩婢规ɑ銇勯敐鍛儓妞ゎ亜鍟存俊鎯扮疀閺囩姷鐛ラ梻浣告啞椤ㄥ懘宕崸妤婃晪闁挎繂顦拑鐔兼煏婢舵ê鏋熼柡鍛灲濮婃椽宕ㄦ繝鍐槱闂佸憡鎸婚惄顖氱暦閵忋倖鐒肩€广儱妫岄幏娲⒒娓氬洤浜濈紒瀣灥閻ｇ敻宕卞Ο鑲╊啎婵炶揪绲介崯鍨洪妶澶婄闁绘ê纾粻楣冩煙鐎涙鎳冮柣蹇ｄ邯閺屽秹鏌ㄧ€ｎ亞浼岄梺鍝勬湰缁嬫垼鐏冮梺鍛婂姂閸斿鈻介鍛瘈闁靛骏绲剧涵楣冩倵濮樼厧鏋ゆ俊鍙夊姍楠炴帡寮崒婊愮床婵犵妲呴崹鐢稿磻閹扮増鍋柛鏇ㄥ亐閺€浠嬫煃閽樺顥滃ù婊勭矒閺屾盯鎮ゆ担闀愬枈闂佺硶鏂傞崕鎻掝嚗閸曨剛绠鹃柣鎰靛墰閳ь剙顭峰Λ鍛搭敃閵忊€愁槱濠电偛寮剁划宀勬偩閻戣棄浼犻柛鏇樺妽閺傗偓闂備焦瀵х粙鎴犫偓姘煎墯缁傚秵绺介崨濠勫幈婵犵數鍊崘鈺佹闁诲孩鑹鹃…鐑藉蓟閿濆绫嶉柛灞捐壘娴犳绱掗悙顒€鍔ゆ繛纭风節瀵鏁愭径濠庢綂闂侀潧绻嗛弲婵嬪礉閹间焦鈷戦柦妯侯槸閺嗙喖鏌涢悩宕囧⒌鐎殿喖顭锋俊鎼佸Ψ閵忊剝鏉搁梻浣虹《濡狙囧疾濠婂嫭娅忛梻鍌氬€烽懗鍫曗€﹂崼銉晞闁糕剝绋戠粈澶嬬箾閸℃绂嬮柛銈嗘礋閺屾盯顢曢敐鍡欘槬闂備礁宕ú锕傚Φ閸曨垰绠涢柛顭戝亞缁愭棃姊洪悡搴☆棌濞存粠浜滈～蹇撁洪鍕獩婵犵數濮撮崯浼村矗閸℃稒鈷戠痪顓炴噺閻濐亪鏌ㄥ顓滀簻妞ゆ劑鍨荤粻浼存偂閵堝棎浜滈煫鍥ㄦ尭椤忣偅銇勯弮鈧崝娆忣潖閾忓湱纾兼俊顖氭惈椤秹鎮峰鍕凡闁哥喐鎸抽崹楣冨冀椤撶偛鑰垮┑鐐村灦閻熴垽骞忓ú顏呪拺闁告稑锕﹂埥澶嬨亜椤撗冨闁崇粯鎹囧顕€宕掑鍕剁础缂傚倸鍊烽梽宥夊垂閻熼偊鍤曟い鏇楀亾闁哄瞼鍠栭、娑樷枎閹寸姷宕叉俊鐐€戦崹娲€冩繝鍌滄殾闁绘梻鈷堥弫鍕煠閹帒鍔氭い蹇撶秺濮婂宕掑▎鎴М闂佺顕滅槐鏇犲垝濞嗘挸绠ｉ柨鏃囧Г濞呭洭姊洪棃娑辨缂佺姵鍨瑰▎銏ゆ倷閻戞鍘遍梺鍝勬储閸斿矂鎮橀敓鐘崇厽闁规儳鐡ㄧ粈瀣煛鐏炵偓绀冪紒缁樼洴閹瑩顢楁担鍝勭祷闂傚倷娴囬～澶庛亹閸愨晜娅犲ù鐘差儏閻掑灚銇勯幒鎴濇灓婵炲吋鍔栫换娑㈠矗婢规繍浜為崣鍛存⒑閸濆嫮鈻夐柛鎾寸⊕缁傚秴鈻庤箛濠冩杸闂佺粯鍔橀崺鏍亹瑜忕槐鎺楃叓椤撶姷鐓撻悗瑙勬磸閸庣敻宕洪埀顒併亜閹烘垵鈧崵澹曟總鍛婄厪濠电偛鐏濋崝鎾煟閹惧啿鎮戦柟渚垮妽缁绘繈宕ㄩ鍛摋闂備胶鎳撳鍫曞箰閸愯尙鏆﹂柣鏃傗拡閺佸啴鏌曡箛鏇烆潙闁硅揪闄勯悡鐔煎箹濞ｎ剙鈧倕顭囬幇顓犵閻犲泧鍛殼閻庤娲樼划宀勶綖濠靛鏁囬柣姗嗗亝閺侀潧鈹戦悩鍨毄濠殿喖顕埀顒佸嚬閸樺ジ鎮鹃柨瀣窞闁归偊鍘鹃崢顏呯節閻㈤潧鈧垶宕橀埡浣哄絽缂傚倷娴囨ご鎼佹偂閳ユ剚娼栫紓浣诡焽閻熷綊鏌嶈閸撶喖宕洪埀顒併亜閹烘垵鈧憡绂掑鍫熺厾婵炶尪顕ч悘锟犳煛閸涱厾鍩ｆい銏＄☉閳瑰啴骞嗚婢规洟姊洪崜鑼帥闁稿鎳愬▎銏ゅ蓟閵夛箑鈧灚鎱ㄥΟ鐓庡付妤犵偞锕㈤弻鐔肩嵁閸喚浠奸梺瀹犳椤﹀灚鎱ㄩ埀顒勬煟濡椿鍟忛柛鐐存そ濮婄粯鎷呴悜妯烘畬濡炪倖娲﹂崢浠嬪箞閵娾晜鐓ラ悗锝呯仛椤斿嫰姊婚崒姘偓鎼佸磹瀹勬噴褰掑炊瑜滃ù鏍煏婵炵偓娅嗛柛濠傛健閺屻劑寮撮悙娴嬪亾閸濄儳鐭嗗璺侯儑缁犻箖鏌涢埄鍐炬畼缂佺姵濞婇弻锟犲幢椤撶姷鏆ら梺鍝勬湰閻╊垶銆侀弴銏℃櫜闁糕剝鐟辩槐鈺呮⒒娓氣偓閳ь剛鍋涢懟顖涙櫠椤栫偞鐓熸俊銈呭暙閳诲牓鏌曢崱鏇狀槮闁宠閰ｉ獮姗€宕楅崨顖滃€為梻鍌欑閹测€趁洪敃鍌氱；闁告洦鍨界紞鏍ㄦ叏濡じ鍚痪鍙ョ矙閺屾稓浠﹂崜褎鍣梺绋跨箰閻偐妲愰幒妤婃晪闁告侗鍘炬禒鎼佹⒑鐠団€崇仩閻庢矮鍗抽妴浣糕槈濮楀棙鍍甸柡澶婄墑閸斿秹顢欓弴鐐╂斀闁绘绮☉褔鏌涙繝鍐╁€愭鐐差樀閺佹捇鎮╅懠顒婄幢闂備礁鎲″ú锕傚磻閹烘垯鈧帗绻濆顓炩偓鐢告煥濠靛棛鍑圭紒銊ょ矙閺屾盯骞嬪┑鍥缂備浇椴哥敮妤€顭囪箛娑樜╃憸蹇涙偩閻戞绠鹃柨婵嗘噺閹兼劙鏌ㄩ弴銊ょ凹濞ｅ洤锕畷濂稿即閻愰潧鈧偛顪冮妶搴″⒒闁哥姵鎹囧畷鏇㈡偨缁嬭儻鎽曞┑鐐村灦閸╁啴宕戦幘缁樻櫜閹肩补鈧剚娼诲┑鐐差嚟婵秹宕堕妸褍骞愬┑鐐存尰閼规儳煤閵堝應鏋嶇€广儱顦伴悡鏇㈡煃鏉炴壆顦︽い蹇ｅ幘閳ь剝顫夊ú姗€鈥﹂崼銉嬪洨鈧潧鎽滅壕濂告煟濡搫鏆遍柛婵堝劋閹便劍绻濋崶鈺冪獥闂侀潧娲﹂崝娆撶嵁閹烘绠奸柛鏇ㄥ幖閹偟绱撻崒姘偓椋庢媼閺屻儱纾婚柟鎹愮М瑜版帗鏅查柛銉ｅ妼濞堝矂姊洪崨濠冣拹婵☆偄鍟～蹇撁洪鍛闂侀潧鐗嗛幊蹇涙倵閸撗呯＝濞撴艾娲ら弸娑㈡煟椤掆偓閵堟悂鐛幋锕€顫呴柣娆屽亾婵炵鍔戦弻宥堫檨闁告挾鍠愭穱濠勨偓娑櫳戞刊瀵哥磼椤栨稒绀冮柣搴☆煼濮婅櫣鎲撮崟顐㈠Б缂佸墽铏庨崣鍐€佸▎鎰瘈闁稿本顨嗛弬鈧梺鍦劋婵炲﹤鐣烽幇鏉跨缂備焦锚濞堟垿姊洪崜鎻掍簼婵炲弶鐗犲畷鎺楀Ω閵夊啫缍婇幃鈺侇啅椤旂厧澹夐梻浣瑰▕閺€閬嶅垂閸︻厽顫曢柟鎯х摠婵挳鏌涜箛鎿冩Ч闁挎稑鐗嗛—鍐Χ閸涱垳顔囬梺缁橆殔濡繈骞冮崸妤婃晪闁逞屽墴瀵鎮㈤搹鍦厯闂佸壊鐓堥崳顕€宕濇径鎰拺闁告稑锕﹂幊鍐磼缂佹﹫鑰跨€殿喛顕ч埥澶娢熼崗鍏肩暦闂備線鈧偛鑻晶瀵糕偓瑙勬礃閸ㄥ潡骞冨▎鎾村€绘俊顖濇〃缁ㄧ敻姊绘担鍛婃儓婵炲眰鍨藉畷鐟懊洪鍛簵濠电偞鍨崹娲偂閺囥垺鐓欓柡澶婄仢椤ｆ娊鏌涢幒鎾寸凡闂囧绻濇繝鍌滃ⅱ闁伙絿鍎ら幈銊︾節閸愨斂浠㈠Δ鐘靛仦閻楃娀骞冨▎鎾崇闁圭儤绻勯埀顒佸▕濮婄粯鎷呯粵瀣缂備胶绮崹褰掑箲閵忋倕閱囬柕澶堝劤閻ｇ儤淇婇妶蹇曞埌闁哥噥鍨跺畷鎰節濮橆厾鍙冨┑鈽嗗灟鐠€锕€危閻戞ǜ浜滈柡鍌涘閸ゅ洦鎱ㄦ繝鍐┿仢鐎规洘顨婂鑽ゅ鐎ｎ亞鍔甸梻鍌欒兌椤牏鈧稈鏅犻幃锟犲灳瀹曞洦娈鹃梺鍝勬储閸╁嫰寮崒鐐寸厱妞ゆ劑鍊曢弳閬嶆煙妞嬪海甯涚紒缁樼洴楠炴澹曠€ｎ亶妫熸繝鐢靛仜閻即宕愰弽顐ょ焿鐎广儱鎳夐弨浠嬫煕椤愮姴鐏柨娑欑矒閺岋絾鎯旈婊呅ｉ梺绋款儏閹冲酣鎮惧畡鎵殕闁逞屽墴閸┾偓妞ゆ帒鍠氬鎰箾閸欏鐒介柛鎺撳浮楠炴绱欓悩鐢电暰闂備礁缍婂Λ璺ㄧ矆娓氣偓閹€斥槈閵忥紕鍘遍柣蹇曞仧閾忓骸鈻撻弴銏″€垫慨姗嗗厵閸嬨垺鎱ㄦ繝鍕笡闁瑰嘲鎳樺畷銊︾節閸屾稒鐣肩紓鍌氬€风粈渚€顢栭崱娑樺瀭闁秆勵殔閺嬩線鏌涢幇闈涙灍闁哄懏绻堥弻娑氫沪閻愵剛娈ら梺姹囧€曞ú顓烆潖濞差亜宸濆┑鐘插暙椤︹晠姊虹粙璺ㄧ闁荤噦濡囩划瀣吋閸滀胶鍙嗛梺鍛婃磵閺呮瑧鑺辨繝姘拺閻熸瑥瀚粈鍐╃箾婢跺鈯曠紒鍌涘浮閺佸倿鏌ㄩ姘闂佽崵鍠撴晶妤呭疮閻愮數纾奸悹鍥ㄥ絻椤忣偅淇婇崣澶婂妤犵偞甯掕灃濠电姴鍟▍鏃堟⒒娴ｈ櫣銆婇柛鎾寸箞閹兘濡烽埡浣规К閻庡厜鍋撻柛鏇ㄥ墰閸欏嫮绱撻崒娆戝妽妞ゎ厼娲﹂弲鍫曟偨閸涘﹦鍘搁柣蹇曞仜婢т粙鍩ユ径鎰厓闁芥ê顦藉Ο鈧悗瑙勬穿缁绘繈骞冨▎鎴斿亾閻㈠憡娅滃瑙勬礋濮婂宕掑▎鎴М闂佸湱瀵介妶鍡樺櫡闂傚倷娴囬鏍窗閺嶎厼纾归柟闂寸筏缂嶆牠鐓崶銊﹀婵炲樊浜堕弫鍌炴煕閺囥劌浜為柣娑掓櫅閳规垿鎮╅崹顐ｆ瘎婵犳鍠楅幐鍐茬暦椤栫儐鏁冩担宥夊炊椤掆偓閻撴盯鏌涘☉鍗炴灀闁圭柉娅ｇ槐鎾存媴閸撴彃鍓卞銈嗗灦閻熲晛鐣烽弴锛勭杸婵炴垶鐟ラ埀顒€鐏氶幈銊ヮ潨閸℃ぞ绨婚悗瑙勬尭濡繈寮婚弴銏犲耿闁哄洨濯Σ顕€鏌х紒妯煎⒌闁哄本绋戦埥澶愬础閻愭彃顒滄繝鐢靛仧閸樠囨晝椤忓嫷娼栨繛宸簼閸婄兘鏌﹀Ο渚Ц濠殿喓鍊濋弻锝堢疀閹惧墎顔夐梺鑽ゅ暀閸涱厼鐏婇柣鐘叉搐濡﹤顭囬埡鍌樹簻闁圭儤鍩堝Σ褰掓倵闂堟稓鐒告慨濠冩そ濡啫鈽夊顒夋毇婵犵妲呴崑鍛矙閹烘鐤鹃柛顐ｆ处閺佸棝鏌涢弴銊ュ闁告﹢浜跺娲偡闁箑娈舵繝娈垮枤閺佽鐣烽悽绋跨劦妞ゆ帒瀚悡锝吤归崗鑲╂噮缂佸鍣ｉ弻锛勪沪閻ｅ睗銉︺亜瑜岀欢姘跺蓟濞戙垹绠婚悹铏瑰劋閻忓牆螖閻橀潧浠滈柛鐕佸亯閻忓啴姊洪崨濠傚闁哄懏鐩鎼佸磼閻愮补鎷洪梺鍛婄☉閿曘儲寰勯崟顖涚厱闁规儳顕ú鎾煕閳哄啫浠滈柍钘夘槸椤繃娼忛埡瀣棷婵犵數鍋犻幓顏嗗緤閸ф绠犻柟鎹愭硾缁躲倕鈹戦悩宕囶暡闁绘挸鍟伴幉绋款煥閸繄顦┑鐐村灟閸ㄥ湱绮ｅΔ鍛厵闁诡垎灞芥濡炪倐鏅滆ぐ鍐箒闂佺粯锚濡﹪宕曢幇鐗堢厓闂佸灝顑呯粭鎺楁婢舵劖鐓ユ繝闈涙瀹告繈鏌熼挊澶娾偓鍧楀蓟濞戙垹围闁告侗鍘藉▓濠氭⒑閸濆嫭婀扮紒瀣灱閻忔帡姊虹粙璺ㄧ闁告艾顑夐幃鐢割敂閸啿鎷洪柡澶屽仦婢瑰棛鎷规导瀛樼厱闁挎繂绻掔粔顕€鏌ｅ☉鍗炴珝妤犵偞甯掕灃闁逞屽墰缁崵鎷犻崣鍌涚洴閹囧醇閵忋垻鏆紓鍌欐缁讹繝宕戦崨顖涘床婵犻潧顑嗛崑銊╂⒒閸喓鈼ョ紒顔挎硾閳规垿鍩ラ崱妤冧哗闂佹寧娲忛崕宕囧垝鐎ｎ亶鍚嬮柛娑变簼閺傗偓闂佽鍑界紞鍡樼閻愬搫鍌?")
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
            "engineering_challenge": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎娆戠┛闂傚倷绶氶埀顒傚仜閼活垱鏅堕崜褏纾奸柣妯挎珪鐏忣參鏌ｉ敐澶嬫暠缂佽櫣鏅划娆忊枎閻愵剛绉遍梻鍌欒兌閸嬨劑宕曢柆宥呯柈閻犳亽鍔忔慨鎶芥煏婢跺棙娅嗛柍閿嬪笒闇夐柨婵嗘川閹藉倹绻涢崗鐓庡妞ゎ厼娼￠幃鐑芥偋閸偅锛侀梻浣告惈閹虫挸鈻斿☉婊呬簷闂備礁鎲℃笟妤呭储妤ｅ啯鏅繛鎴欏灪閻撶喖骞栭幖顓炵仯缂佸娼ч湁婵犲﹤瀚晶鐢碘偓娈垮枔閸斿秶绮嬮幒鏂哄亾閿濆骸浜為柛妯挎閳规垿鍩ラ崱妤冧淮濡炪倖娉﹂崨顓犵瓘婵犵數濮电喊宥夋偂濞戙垺鐓曢柍鈺佸彁閹寸姷鐭嗛柛顐犲灮绾惧ジ寮堕崼娑樺缂佹う鍥ㄧ厵濡炲楠搁埢鍫⑩偓瑙勬穿缁叉儳顕ラ崟顐嬬喐瀵煎▎鎴狀槯闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敃鈧€氬銇勯幒鎴濃偓濠氭儗濞嗘挻鐓欓弶鍫濆⒔閻ｉ亶鏌ｉ幘杈捐€块柡宀€鍠愬蹇涘礈瑜忛弳鐘电磽娴ｆ彃浜鹃柣搴秵閸嬩焦绂嶅鍫熺厵闁逛絻娅曞▍鍛存煟韫囧﹥娅嗛柕鍥у椤㈡洟鏁愰崼婵愭闂備礁鐤囬～澶愬垂閸ф绠栭柍鍝勬噹缁犳稑霉閿濆懏鍟炴繛鍛洴濮婄粯鎷呯憴鍕哗闂佸憡鏌ㄩ澶婄暦閿熺姴绀冮柤纰卞墯濞堥箖姊洪棃娑崇础闁逞屽墴瀹曟垿骞樼紒妯绘珳闁硅偐琛ラ崜婵嬫倶閸喍绻嗘俊銈傚亾闁硅櫕锚椤繐煤椤忓嫬绐涙繝鐢靛Т閸燁偊藝閳哄懏鈷戦柟鑲╁仜婵¤棄顭块悷鐗堫棤闁告帗甯炵槐鎺懳熼懖鈺冩婵犳鍠楅敃鈺呭储閸忚偐顩锋い鏍仦閳锋垿鏌熼鍡楁噽椤旀垵顪冮妶搴′簻妞わ箒椴哥粩鐔煎即閵忊晜鏅滈梺鍓插亞閸犳捇宕㈤鍛瘈闁靛骏绲剧涵鐐繆椤愶絿鎳冮柍璇茬Ч瀹曞崬鈽夊▎鎴濆箺闂備浇顫夊畷妯衡枖濞戙垹鍑犻柟杈鹃檮閻撳繘鏌涢妷鎴濆枤娴煎啫螖閻橀潧浠︽い顓炴喘楠炴垿宕熼姘炊闂佸憡娲﹂崑鎺懳涙惔銊︹拺閻犲洤寮堕崬澶嬨亜椤愩埄妯€妤犵偛鍟村畷濂稿即閻愮绱甸梻浣圭湽閸ㄥ鈥﹂崼銏笉婵炲樊浜濋悡鏇熴亜閹板墎绋荤紒鈧崘顔界厱濠电姴瀚崢鎾煛瀹€瀣М妤犵偛顑夐幃婊堝幢濞嗗繐楔闂傚倷绀侀幉锟犫€﹂崼婢盯宕熼姘卞幋闂佺懓顕崑娑氱不閻樼粯鈷戠紒瀣皡閺€濠氭煕閺冣偓閻熴儵鎮鹃悜钘夌闁挎洍鍋撶紒鐘哄吹缁辨挻鎷呯拠锛勫姺闂佸憡顭堝Λ鍕煘閹寸偛绠犻梺绋匡攻濞茬喎鐣烽鐑嗘晝闁挎繂娴傚ù鍕⒒娓氬洤澧紒澶屾暬閹€斥枎閹惧鍙勯棅顐㈡祫缁茶姤绂嶅┑鍫氬亾鐟欏嫭绀€闁活剙銈搁崺鈧い鎺戝枤濞兼劖绻涢崣澶岀煉闁炽儻绠撳畷濂告晲閸ワ妇鑳哄┑鐘垫暩閸嬬娀骞撻鍡楃筏濞寸姴顑呯粻瑙勩亜閹拌泛顩€规挷鑳堕埀顒€绠嶉崕閬嵥囨导鏉戠厱闁圭儤鍤氳ぐ鎺撴櫜闁告侗鍠栭弳鍫ユ⒑鐠団€崇仩闁绘锕俊鐢稿礋椤栨氨顓洪梺缁樺姈瑜板啴锝為幒妤佸€甸悷娆忓缁€鍐煕閵娿儳浠㈤柣锝囧厴閹垻鍠婃潏銊︽珫婵犳鍠楅敋鐎规洦鍓氶幈銊╂晜閹存帞绠氶梺缁樺姦娴滄粓鍩€椤掍胶澧遍柡渚囧枟缁绘繈宕堕妸銉︾暠闂備礁鎲￠幐鐑芥嚄閼哥數鈻旂€广儱顦伴悡娆撴煕閹炬鎳庣粭锟犳⒑缂佹ɑ灏甸柛鐘崇墵瀵濡搁妷銏℃杸闂佺硶鍓濊摫闁诡喗鐟╁娲川婵炴碍鍨块獮鎰板箮閽樺鎽曢梺缁樻⒒閳峰牓寮繝鍥ㄧ厽闁挎繂鎳愰悘閬嶆煟閹炬剚妯€婵﹥妞藉畷鐑筋敇瑜忛崝鎼佹⒑閹稿孩纾搁柛搴＄－閸掓帡鍩￠崨顔间簻闂佺粯鎸稿ù鐑藉储閹绢喗鈷戠紓浣姑慨锕傛煕閹炬潙鍝洪柟顕€娼ч～婵嬫嚋绾版ɑ瀚奸梻浣告啞缁诲倻鈧凹鍘奸敃銏ゆ偋閸垻顔曢梺鍛婄懃椤︿粙鎮為悾宀€纾兼い鏃囶潐濞呭﹪鏌熼鍝勭伄闁哥姴锕ュ蹇涘Ω閿旂晫褰ㄦ繝鐢靛У椤旀牠宕板Δ鍛櫇闁冲搫鎳庨崒銊モ攽閸屾粠鐒鹃柣銈夌畺閺岋箑螣娓氼垱鈻撳┑鐐存尭椤兘寮婚弴銏犻唶婵犻潧娲ゅ▍褏绱撴担鍝勑￠柛妤佸▕瀵鏁愰崨鍌涙閸┾偓妞ゆ帒瀚弲婵囥亜韫囨挾澧曢柡鍕╁劜缁绘盯骞嬪▎蹇曚患缂備胶濯寸紞渚€寮婚妸鈺佺睄闁稿本绋掗悵顏堟⒑閸涘⊕顏勭暦椤掑嫬鐓橀柟杈鹃檮閸婄兘鏌℃径瀣仼濞寸姵鎮傚娲箰鎼淬垹顦╅梺绋款儏閿曘倝顢氶敐澶娢╅柨鏂垮⒔閻﹀牆鈹戦鏂や緵闁告ê銈搁崺鈧い鎺嗗亾闁绘牕銈搁幃锟狀敃閿曗偓閻愬﹤顪冪€ｎ亪顎楅柛鈺佽嫰铻栭柣姗€娼ф禒锔姐亜椤撶偞宸濇俊鍙夊姍楠炴帡骞樼€靛摜肖闂備線娼ч…鍫ュ磿閹惰姤鍋￠柡灞诲劜閸婄敻鏌涢…鎴濅簼缂佽埖鐓￠幃妤€顫濋悡搴＄闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濈敖妞わ附婢橀—鍐Χ閸℃ê纰嶅銈忓瘜閸欏啫鐣峰┑鍡╁悑闁搞儯鍔屾惔濠傗攽閻樼粯娑ч柣妤€妫濆鎼佸醇閻斿墎绠氬銈嗙墬绾板秹骞嗛崼銉︾厓鐎瑰嫰鍋婂Σ鎼佹煃鐟欏嫬鐏撮柟顔界懇楠炴捇骞掗幘鏂ュ亾椤栫偞鈷戦柤濮愬€曢弳閬嶆煛閸涱垰鈻堝┑鈥崇摠閹峰懘宕滈崣澶婄紦闂備線鈧偛鑻晶顕€鏌ｉ敐鍛Щ閾绘牠鏌涘☉鍗炴灈濞存粍顨婇弻鐔兼嚌閻楀牆娑х紓浣瑰絻濞硷繝骞冩导鎼晪闁逞屽墮椤繘鎼圭憴鍕彴闂佸湱绮敮鎺懶掗幇顔剧＝闁稿本姘ㄥ瓭濠碘槅鍋呴悷褏鍒掔€ｎ亶鍚嬮柛婊€鑳堕崣鍡涙⒑閸涘﹥澶勯柛妯诲礃閵囨劖銈ｉ崘鈹炬嫼缂備緡鍨卞ú鏍ㄦ櫠閺屻儲鍎戝璺虹灱绾惧ジ鎮归崶褍绾фい銉ｅ灲閺屸€崇暆鐎ｎ剛袦濡ょ姷鍋涘ú顓炵暦濡ゅ懎浼犻柕澹嫭娅掗梻鍌氬€风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼顢涢悙瀵稿幗濠德板€撻悞锔剧矆鐎ｎ喗鐓ユ繝闈涚墕娴犫晝绱掗悩宕囨创鐎殿噮鍣ｅ畷鎺戭煥閸涱噮娼撴繝鐢靛У椤旀牠宕板Δ鍛櫇闁冲搫鎳庣粈鍫熺箾閹存瑥鐏柡鍜佸墯缁绘盯骞嬪▎蹇曚痪闂佹娊鏀遍崹鍧楀蓟閿濆鍋勯柛娑橈功閸戯繝姊洪幎鑺ユ暠婵﹨宕靛Σ鎰板箳濡ゅ﹥鏅梺鍛婁緱閸樼偓绂掗幖浣瑰€甸悷娆忓缁€鍐煕閵娿儲鍋ョ€规洘妞介弫鎾绘偐閹绘帞鐛╂俊鐐€栧褰掑磿閹剁晫宓侀柛顐ゅ枔缁♀偓閻庡吀鍗抽弨鍗烆熆濮椻偓閸┾偓妞ゆ帊鐒︾粈瀣偓瑙勬处閸ㄥ爼銆侀弴銏℃櫜闁搞儴鍩栭柨銈夋⒑閼姐倕鏋戦柣鐔村劤閳ь剚鍑规禍鐐哄箲閵忋倕骞㈡繛鎴炵懅閸樼數绱撻崒娆戝妽闁挎氨绱掑锕€鍠氶悢鍡欐喐濠靛牏涓嶉柟鎹愵嚙閽冪喖鏌嶉妷銉э紞闁哄棗妫濋弻宥堫檨闁告挾鍠庨悾閿嬪閺夋垹顔掗梺鐓庢啞椤旀牕顭囬悢鍏尖拺闁革富鍘奸崝瀣亜閵娿儲鍤囬柨婵堝仱瀹曘劎鈧稒顭囬崢钘夆攽閳藉棗鐏犻柟纰卞亰楠炲啯绗熼埀顒勫蓟濞戞ǚ鏀介柛銉ㄥ煐閻ｅ爼姊虹€圭媭娼愰柛銊ユ健楠炲啫鈻庨幘鏉戞濡炪倖甯婇悞锕傚窗閺嶎偆纾介柛灞剧懅鐠愪即鏌涢悩宕囧⒌闁哄苯锕弫鎰板川椤栨稒顔曢梻浣侯攰閹活亞绮婚幋鐘典笉濠电姵纰嶉悡鐘绘煙闂傚鍔嶆繛鎳峰洤绠归柡澶嬪煀瀹搞儵鏌嶇憴鍕伌闁诡喒鏅濈槐鎺懳熸繝姘殬濠碉紕鍋戦崐鏍垂閻㈢绠犳慨妞诲亾闁轰焦鍔欓幃娆撳传閸曨偆鐛╅梺璇插缁嬫帡鈥﹂崶顒€鐭楅柛鈩冦仜閺€浠嬫煟濡偐甯涙繛鎳峰嫪绻嗘い鎰剁悼閹冲洭鎸婇悢鍏肩厽婵☆垵鍋愮敮娑㈡煟閹惧磭绠婚柡灞剧洴閸╁嫰宕楅悪鈧禍婵嬪箞閵娿儺鍚嬪璺侯儑閸樻悂鎮楅崗澶婁壕闁诲函缍嗛崜娑滄懌闂傚倷娴囬鏍垂閸楃倣娑㈠礃閳哄倸寮块梺閫炲苯澧撮柡宀嬬到铻ｉ柛婵嗗妤犲洭姊烘导娆撴闁圭懓娲ら～蹇曠磼濡顎撻梺鍛婄☉閿曘儵宕伴幇顓犵瘈婵炲牆鐏濋弸銈夋煛娴ｅ壊鐓兼鐐插暢椤﹀綊鏌熼瑙勬珖闁归濞€瀹曪絾寰勭仦绋夸壕妞ゆ帒瀚埛鎴︽煕濞戞﹫宸ュ┑顕嗙畵閺屾盯鎮╁畷鍥р拰闂佹寧绻勯崑銈呯暦閵娧€鍋撳☉娆樼劷闁告﹩浜娲礈閹绘帊绨肩紓浣筋嚙閸熺妫㈤梺缁樺姇椤曨厾绮绘ィ鍐╃厱婵炴垵宕弸銈咁熆瑜嶉悘姘跺箞閵婏妇绡€闁告劏鏂傛禒銏ゆ倵鐟欏嫭纾搁柛鏂跨Ф閹广垹鈹戠€ｎ亞顦ㄥ銈呯箰濞寸兘宕板鈧濠氬磼濞嗘埈妲梺纭咁嚋缁绘繂顕ｆ繝姘╅柍杞扮閻濇ê顪冮妶鍡楃瑨闁稿﹤顭烽幆灞惧緞鐏炵浜炬鐐茬仢閸旀碍淇婇銏ゅ弰鐎规洘鍨垮畷銊р偓娑欘焽閸橀亶姊虹涵鍛劷闁告柨绉撮埢宥夊炊椤掍胶鍘卞┑顔姐仜閸嬫挸霉濠婂棙纭炬い顐㈢箰鐓ゆい蹇撳椤斿洭鏌熼崗鑲╂殬闁糕晛瀚～蹇涘垂椤曞懏瀵岄梺闈涚墕濡瑩鎳栭悩缁樼厱闁靛鍨哄▍鍛磼娓氬﹦鐣垫慨濠冩そ瀹曨偊宕熼娑欑€遍梻浣筋嚙缁绘垿宕濆鈧俊鐢稿箛閺夎法顔婇梺瑙勫劤閸樻牕效濡ゅ懏鈷掑ù锝呮啞閸熺偤鏌涢弮鈧ú鏍敋閿濆绀堝ù锝囨嚀閻濅即姊虹紒妯哄闁稿簺鍊濋崺娑㈠箣閿旂晫鍘卞┑鐘绘涧濡顢旈鍛瘈闁逞屽墯鐎佃偐鈧稒顭囬崢浠嬫⒑閸愬弶鎯堥柨鏇樺€濋幃姗€鏁傜粵瀣啍闂佺粯鍔栬ぐ鍐汲濞嗘劑浜滄い鎾寸矊婵倻鈧娲滈崢褔鍩為幋锕€骞㈡慨姗堢到娴滈箖鏌涢…鎴濇灀闁衡偓娴犲绠抽柟鎯版绾惧綊鏌熼悧鍫熺凡缁炬儳顭烽弻鐔煎礈瑜忕敮娑㈡煟閹惧啿鏆熼柍褜鍓涢幊鎾垛偓姘嵆瀹曟垶绻濋崶褏锛熼梺鍝勫暊閸嬫捇鏌熸笟鍨缂佺粯绻堝畷銊╊敋閸涱剙鎽嬮梻鍌欑缂嶅﹪藟閹惧绠鹃柍褜鍓熼弻娑㈠Ω閿曗偓閸斻倝鏌ｉ敐鍥у幋鐎规洖鐖奸弫鍐焵椤掑嫬绠洪悗锝庡墰绾句粙鏌涚仦鎹愬闁逞屽墴椤ユ挾鍒掗崼鐔虹懝闁逞屽墲濡喖姊绘笟鍥у缂佸鎸冲鍛婃媴缁洘鏂€闂佺粯顭堝▍鏇㈡儍閹寸姭鍋撶憴鍕矮缂佽埖宀搁幃锟狀敃閿曗偓閻愬﹪鏌曟繛褉鍋撴俊鎻掔墦閹鎮烽悧鍫濇殘缂備浇顕ч悧鎾荤嵁閸愩剮鏃堝焵椤掑嫬鐓″璺号堥弸宥嗐亜閹炬鍊婚崙鍦磽娴ｇ鈧湱鏁Δ鍐处濞寸姴顑呭婵嗏攽閻樻彃鈧敻宕戦幘缁樺仺闁告稑锕﹂崢閬嶆椤愩垺澶勯柟灏栨櫅鍗辩紒瀣紩閻熼偊鐓ラ柛顐犲灮閺嗩偄鈹戦纭锋敾婵＄偘绮欏濠氬川鐎涙ê鈧兘鏌ら懝鐗堢【妞ゅ浚鍘界换婵嬪煕閳ь剟宕熼鐐茬哗闂備礁鎼張顒€煤閻旈鏆﹂柛顐ｆ礀鎯熼梺闈涱槶閸庡搫顭囬弮鍫熲拻濞撴埃鍋撴繛浣冲洦鍋嬮柣鎰暩缁€濠偯归敐鍛喐闁哄棴闄勯幈銊ヮ渻鐠囪弓澹曢梻浣虹《閺呮繈宕戦妶澶婄畺婵炲棙鎼╅弫鍡涙煃瑜滈崜鐔笺€侀弮鍌涘枂闁告洦鍘鹃惁鍫ユ⒑濮瑰洤鐏叉繛浣冲嫮顩烽柨鏃傛櫕缁犻箖鏌涜箛姘汗闁瑰啿娲ㄩ埀顒冾潐濞插繘宕曢幎钘夌劦妞ゆ帒锕︾粔鐢告煕閻樻剚娈滅€规洘鍨块弫宥夊礋椤掆偓閺嬫垿姊洪崫鍕偓钘夆枖閺囥垹姹查柨鏃囧Г閸欏繑淇婇娑橆嚋缁绢厼澧界槐鎺楁偑濞嗗繑鎼愮紒鐘茬秺閹鈽夊▍铏灩娴滃憡瀵肩€涙鍘搁梺绋挎湰椤ㄥ懏绂嶆ィ鍐┾拻闁稿本鑹鹃埀顒傚厴閹虫宕奸弴妞诲亾閿曞倸閱囬柕澶堝劚閻濇ê顪冮妶鍡楃瑨闁稿﹤顭烽幆灞解枎閹惧鍘甸梺缁樺灦閿曗晛鈻撻弮鍫熺厽闁规儳鐡ㄧ粈瀣煛瀹€鈧崰鏍箖濠婂吘鐔兼倻閳哄倸顏虹紓鍌欒兌閸嬫捇宕曢幎钘夎Е閻庯綆鍠栨闂佸憡娲﹂崹浼村础閹惰姤鐓熼柟閭﹀幗缂嶆垶绻涢崪鍐М闁诡喗顨呴埢鎾诲垂椤旂晫褰梻浣告憸婵潧鐣濋幖浣告槬闁逞屽墯閵囧嫰骞掗幋婵囩亾濠电偛鍚嬮崝鏍崲濞戙垹鐭楀鑸殿焽閸旂兘姊烘潪鎵窗闁革綇缍佸顐﹀箻缂佹ê浜归梺鑲┾拡閸撴盯寮抽锝囩瘈闁汇垽娼ф禒婊勪繆椤愶絿鎳囩€规洖缍婇幃銏ゆ偂鎼达綇绱遍梻浣告贡閸嬫捇寮搁悡骞綁宕奸悢铏诡啎闂佸憡绋撴晶妤呮偟椤忓牊鐓曢柕濞垮劜閸嬨儲顨ラ悙鎻掓殻闁诡喕绮欏畷婊堝矗婢跺鐝栭梻鍌欑劍鐎笛兾涙担绛嬫毎闂備礁缍婇弨鍗烆渻娴犲钃熼柨婵嗩槹閸嬫劙鏌涘▎蹇ｆШ闁宠鐩弻锝堢疀閹惧墎顔夐梺鑽ゅ暀閸涱厼鐏婃繝鐢靛У閼瑰墽绮婚鈧弻銈夊箒閹烘垵濮㈤梺鍛婏耿娴滃爼寮婚敐鍡樺劅妞ゆ牗绮庢牎闂備礁鎲￠幐濠氭偡閵夆晜鍋ゆい鎾卞灪閳锋垿鏌熺憴鍕闁告艾缍婇弻娑氣偓锝冨妼閳ь剚绻傞锝囨嫚濞村顫嶉梺闈涚箳婵潙鐣甸崱娑欌拺闂傚牊渚楅悞楣冩煕鎼淬倖鐝紒鍌涘浮閸╋繝宕ㄩ瑙勫婵犳鍠氶幊鎾趁洪妶澶婄劦妞ゆ帊绶″▓婊呪偓瑙勬礃閸ㄥ潡鐛鈧幊婊堟濞戞鍝庡┑鐘垫暩閸嬬偤宕归鐐插瀭鐟滅増甯炲畵渚€鏌曡箛濞惧亾閼碱剛鐣炬俊鐐€栭悧妤冩崲瀹ュ鍚规繛鍡樻尰閳锋帒顭跨捄鐚村姛閺佸牆鈹戦纭烽練婵炲拑绲垮Σ鎰板箳閹冲磭鍠撻幏鐘诲蓟閵壯€鍋撻悜妯肩瘈闁汇垽娼ф禒婊呪偓娈垮枛閻栧ジ鍨鹃敃鍌氱倞妞ゆ巻鍋撶紒鐘崇叀閺屾洝绠涢弴鐐愭稒淇婇幓鎺斿ⅵ闁哄本娲濈粻娑㈠即閻愭劑鍨介弻銈夊级鐠恒劋铏庨梺瀹狀潐閸ㄥ潡宕洪妷鈺佸耿婵°倕鍟╅崫妤冪磽閸屾瑨鍏岀紒顕呭灦閵嗗啯绻濋崒婊勬闂佺鎻粻鎴犵不濞戙垺鐓熸俊銈傚亾闁绘妫楅埢鎾绘偄閸忚偐鍘告繝銏ｆ硾閿曪附鏅堕幇鐗堢厸闁告侗鍠氶惌宀勬煃瑜滈崜姘卞枈瀹ュ懐鏆嗛柟闂寸缁犳牠姊洪崹顕呭剱濠殿垱娼欓—鍐偓锝庝簻閻︺劍淇婂顔兼灓缂佽鲸鎹囧畷鎺戭潩濮ｆ瑣鍨介弻銊╁即閵娿倝鍋楅梺缁樹緱閸ｏ絽鐣峰鈧、娆撴嚃閳轰礁绠版繝鐢靛仩閹活亞寰婇崸妤€纾块柕鍫濇噳閺嬫柨螖閿濆懎鏆為柍閿嬪灴閺岀喖鎳栭埡浣风捕闂佸憡姊归敃銏ゅ蓟濞戞瑦鍎熸い鏂垮悑閻濇繈鎮楃憴鍕闁搞劌娼￠悰顔嘉熼崗鐓庣彴闂佽偐鈷堥崜锕傚船濞差亝鈷掑ù锝呮啞閹牓鏌涢悤浣镐喊鐎规洘鍔栫换婵嗩潩椤撶喐鐝繝鐢靛Т閿曘倝宕板顑锯偓鎺撶節濮橆厾鍘梺鍓插亝缁诲啴藟閻愮數纾奸柍褜鍓熼崺鈧い鎺戝閳锋垿鏌ｉ悢鍛婄凡闁哄棗宕灃闁绘娅曢崐鎰亜閵忊€冲摵闁轰焦鍔栧鍕熺紒妯荤彟婵犵數濮甸鏍窗濡ゅ懎绀夐柟鐑樻婵啿鈹戦悩宕囶暡闁抽攱鍨垮濠氬醇閻旂儤鍒涢梺缁樼⊕缁海妲愰幒鎾寸秶闁靛濡囬ˇ銊╂⒑閸濆嫭鍣归柣鏍с偢瀵宕卞Δ濠傛倯闂佺硶鍓濋悷銉╃嵁瀹ュ鈷掑ù锝堟閸氬綊鏌涢悩鍐插妞ゎ厼鐏濋～婊堝焵椤掑嫨鈧線寮崼顐ｆ櫍闂侀潧楠忕槐鏇㈠储閹剧粯鈷戦梻鍫熶緱濡牓鏌涢妸锕€鈻曢柟顕€绠栧畷褰掝敃椤愶綆鍟嶉梻浣虹帛閸旀洖螣婵犲洤纾块煫鍥ㄦ煟娴滄粍銇勯幘瀵哥煀濠殿喖鍊婚埀顒冾潐濞插繘宕濋幋锔衡偓浣糕槈閵忊剝娅滈梺鍝ュУ婢瑰棝宕戦妶鍜佹綎濠电姵鑹剧壕鍏兼叏濮楀棗鍘撮柛瀣崌楠炴牗鎷呴崫銉串闂備礁缍婂Λ璺ㄧ矆娴ｅ搫顥氶柣鐔煎亰濞撳鎮楅敐搴濈凹闁圭櫢缍侀弻锝夘敇閻愭惌妫為梺闈涙鐢帡锝炲┑瀣櫜闁告侗鍓欓ˉ姘攽鎺抽崐妤佹叏閻戣棄纾绘繛鎴旀嚍閸ヮ剚鍋ㄧ紒瀣仢閻庮厽淇婇妶蹇曞埌闁哥噥鍋嗙划璇测槈濡繐缍婇弫鎰板川椤斿吋娈樻繝鐢靛仜閹冲酣鏁冮妶澶婄厴闁硅揪闄勯崑鎰版煕椤垵浜濇慨锝呭缁绘繂鈻撻崹顔界亾闂佽桨绀侀…鐑界嵁婵犲倵鏀介悗锝庝簽椤︻參鎮峰鍐ч挊鐔告叏濮楀棗鍘撮柡鈧禒瀣厽婵☆垵娅ｉ敍宥嗐亜閿濆棛鍙€闁哄矉缍侀獮妯尖偓闈涙啞閸ｄ即姊洪崫鍕拱闁烩晩鍨堕悰顔嘉熸担鏇熸閸┾偓妞ゆ帒瀚粻鐘诲箹鏉堝墽鎮肩紒鐘虫閺屻劑鎮㈤崫鍕戯綁鏌嶉柨瀣仼缂佽鲸鎸婚幏鍛存嚃閳╁啫鐏╁ù婊冩啞鐎佃偐鈧稒顭囬崢浠嬫⒑閸愬弶鎯堥柨鏇樺€濋幃姗€鏁傞柨顖氫壕婵炲牆鐏濋弸锔姐亜閺囧棗娲ら悡鈥愁熆閼搁潧濮囨い顐㈡嚇閺屽秹宕崟顐熷亾閻熸壋鏋嶉柛銉墯閳锋帒霉閿濆洦鍤€妞ゆ洘绮庣槐鎺旀嫚閹绘巻鍋撻崸妤€绠栫憸鏂跨暦閸楃伝褰掑级濞嗙偓笑闂佸疇顫夐崹鍨暦閸洖鐓涢柛鎰劤閺咁參姊绘担绛嬪殭閻庢稈鏅濈划娆撳箳濡炵儵鍋撻敃鍌氱倞妞ゆ帊绀侀崜褰掓⒑閸︻厼鍔嬫慨濠呭吹婢规洘绺介崨濠勫幗濠碘槅鍨靛▍锝夋晬瀹ュ拋鐔嗙憸蹇涘极閹间礁鐒垫い鎺嶇贰閸熷繘鏌涢悩宕囧⒌闁炽儻绠撻幃婊堟寠婢跺鈧剟姊洪崷顓烆暭婵犮垺锕㈤弻瀣炊椤掍胶鍘棅顐㈡搐椤戝懘鎮橀鍛瘈闁靛繆鈧磭浼屽┑顔硷功缁垶骞忛崨顖滈┏閻庯綆鍋嗙粔鐑芥⒒娴ｄ警鐒炬慨姗堢畱閳诲秹寮撮姀鐘垫煣闂佽偐顭堥悘姘跺磿閻旀悶浜滄い鎾跺枎閻忥箓鏌￠崨顏呮珚婵﹥妞介獮鏍倷閹绘帒顫庨梻浣告惈閹冲繒鎹㈤崟顒傜彾闁哄洢鍨虹€电姴顭跨憴鍕畵缂傚秴锕顐﹀箛閺夊潡鍞堕梺缁樻磻濡炴帡宕Δ鍛拺婵懓娲ら悞娲煕閵娾晙鎲鹃柟顖氬椤㈡盯鎮欓懠鑸垫啺婵犵數鍋為崹顖炲垂閸︻厾灏电€广儱顦伴悡鍐喐濠婂牆绀堥柣鏃傚帶缁犳牠鏌ｉ幋锝嗩棄闁绘挻鐩弻娑樷槈閸楃偟浠╃紓浣风筏缁犳挸顫忓ú顏勫窛濠电姴鍊歌闂備礁鎽滄慨鐢告偋閻樿钃熼柕濞炬櫅鍥撮梺绯曞墲濞叉粎绮诲鑸碘拺闂傚牊绋撴晶鏇㈡煕婵犲倹鍟炵紒鍌氱Ч瀹曟粏顦寸痪鎹愭闇夐柨婵嗘缁茶霉濠婂牏鐣洪柡宀嬬稻閹棃顢涘鍛咃綁姊虹粙娆惧剮闁绘帪濡囩划瀣吋閸滀胶鍙嗛梺鍓插亞閸犳捇宕㈤幖浣瑰€垫鐐茬仢閸旀岸鏌涢悤浣镐簼濞ｅ洤锕畷绋课旀担鍝勫笚闂備浇濮ら敋妞わ箒妫勫嵄闁归棿鐒﹂ˉ鍡楊熆閼搁潧濮堥柣鎾跺枑閹便劌螖閳ь剙螞濡ゅ懎鍑犳繛鎴欏灪閻撶喖鐓崶銊﹀碍缂佺嫏鍥ㄧ厵濞撴艾鐏濇俊鐣岀磼缂佹绠炵€规洘锕㈤崺鐐村緞濮濆本顎楅梻浣筋嚙濮橈箓锝炴径濞掓椽鏁冮崒姘憋紱婵犵數濮撮崐濠氬汲閿曞倹鐓熼柡鍐ㄥ€哥敮鍫曟煕閵娿儱鈧綊濡甸崟顖氱疀妞ゆ帒鍊甸弸鍡樼箾鐎涙鐭ゅù婊勭矒閿濈偠绠涘☉娆愬劒闂侀潻瀵岄崢楣冩偂閹剧粯鈷戦柛锔诲弾閻掓儳螖閻樿櫕鍊愮€殿喓鍔戦、姗€濮€閳ユ枼鍋撻悽鍛婂仭婵炲棗绻愰顏嗙磼閳ь剟宕奸妷锔惧幐婵炶揪绲芥竟濠囨偂閼测斁鍋撶憴鍕婵＄偘绮欏畷娲焵椤掍降浜滈柟鍝勭Ч濡惧嘲霉濠婂嫮鐭掗柡宀€鍠栧畷顐﹀礋椤撳鍎甸弻娑滅疀閹惧瓨鎷遍梺闈涙搐鐎氫即寮幇鏉垮耿婵炲棗绻愮紒鈺呮⒒娴ｅ憡鎯堥柣顓烆槺缁辩偞绗熼埀顒勭嵁閸愵喖顫呴柣姗嗗亝閺傗偓闂備胶纭堕崜婵嬫晪濠电偛鎳岄崐鏇⑩€旈崘顔嘉ч幖绮光偓鑼嚬婵犵數鍋犵亸娆撳窗閺嵮屽殨濠电姵纰嶉崑鍕煕韫囨洖甯堕柍褜鍓涚划顖炲箞閵娿儙鏃堝焵椤掆偓铻炴繛鍡樻尰閸嬧晠鎮规ウ瑁も偓鈧柡鈧禒瀣厓闁芥ê顦伴ˉ婊兠瑰鍕疄闁归攱鍨跺蹇涘煛閸愵亷绱茬紓鍌氬€烽悞锕傗€﹂崶顬¤櫣鈧數纭堕崑鎾舵喆閸曨剛顦ラ悗瑙勬处閸撴繈鎮橀幒妤佲拺闁告稑锕︾粻鎾绘倵濮樼厧澧叉い锝勭矙濮婂宕掑顑藉亾妞嬪海鐭嗗〒姘ｅ亾妤犵偛顦甸弫鎾绘偐閼碱剦鍞堕梻浣虹帛閸ㄧ厧螞閸曨厽鍏滈柍褜鍓熷铏规喆閸曨偄濮稿┑鈽嗗亜鐎氼喚鍒掓繝姘唨闁靛鍊楃粻姘舵⒑闂堟稓澧曢柟鍐查叄瀵娊鎮欓悜妯煎幈闂佺粯锚瀵爼藟閵忋倖鐓涢悘鐐插⒔濞插鈧鍠楅幐铏繆閹间礁唯闁靛鍠楁禍銈囩磽閸屾瑨鍏岄柛瀣尭椤灝螣閼测晝鐓嬮梺鍦檸閸犳牠鎮″鈧弻鐔告綇閸撗呮殸闂佺粯鎼换婵嬪蓟濞戙垹鐒洪柛鎰剁細濞岊亞绱撴担闈涘闁靛牏顭堥～蹇撁洪鍛闂侀潧鐗嗛幊蹇撔掗幇鐗堚拺闁告繂瀚崳钘夆攽椤旇偐浠涚紒宀冮哺缁绘繈宕惰椤旀帒顪冮妶鍡橆梿闁稿鍔欒棟闁靛鍎哄〒濠氭煏閸繃顥為柣鎾卞劜娣囧﹪骞撻幒鏂库叺婵犵鍓濋幃鍌炲春閿熺姴纾兼繝濠傚暙婵″洦绻濋悽闈浶為柛銊ャ偢椤㈡岸寮介鐐茬€梺瑙勵問閸犳帡宕戦幘鎰佹僵闁绘挸楠哥猾宥夋⒑鐠団€虫珝缂佺姵鐗犻獮鍐煥閸喎娈熼梺闈涱槶閸ㄨ櫣鈧俺妫勯埞鎴︽倷閼搁潧娑х紓浣藉紦缁瑩鐛径鎰櫢闁绘灏欓弻鍫ユ⒑缂佹ê濮夐柛搴涘€濋幃锟犲即閵忥紕鍘搁梺鍛婂姀閺呮粌鐣风仦鍙ョ箚缂備降鍨归弸銈囩磼鏉堛劌娴€规洘甯掗～婵喰掑▎宥呯伈闁哄苯绉堕幉鎾礋椤愩倓鎮ｉ梻渚€鈧偛鑻晶鍓х磼閼艰泛袚闁哄懓鍩栭幆鏃堟晲閸モ晝鍘?",
            "project_idea": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎娆戠┛闂傚倷绶氶埀顒傚仜閼活垱鏅堕崜褏纾奸柣妯挎珪鐏忣參鏌ｉ敐澶嬫暠缂佽櫣鏅划娆忊枎閻愵剛绉遍梻鍌欒兌閸嬨劑宕曢柆宥呯柈閻犳亽鍔忔慨鎶芥煏婢跺棙娅嗛柍閿嬪笒闇夐柨婵嗘川閹藉倹绻涢崗鐓庡妞ゎ厼娼￠幃鐑芥偋閸偅锛侀梻浣告惈閹虫挸鈻斿☉婊呬簷闂備礁鎲℃笟妤呭储妤ｅ啯鏅繛鎴欏灪閻撶喖骞栭幖顓炵仯缂佸鏁婚弻娑㈡偐閹颁焦鐤侀梺璇″櫙缁绘繂顕ｉ幘顔藉亜闁惧繗顕栭崯搴ㄦ⒒娴ｇ儤鍤€闁宦板妿閹广垽宕掗悙鏉戞疂閻熸粎澧楃敮妤呮偂閻旇偐鍙撻柛銉ｅ妽缁€鈧梺瀹狀嚙閻楁捇寮婚敍鍕勃闁告挆鍕灡濠电姷顣介崜婵嬪箖閸岀偛鏋侀柛宀€鍋涚粈鍫㈡喐韫囨稑绾уù鐘差儐閳锋帒霉閿濆懏鍟為柟顖氱墦閺岋綁顢橀悜鍡樞ㄩ悗鍨緲閿曨亜鐣烽幇鐗堝亜閺夌偞濯介崺鍛存⒒閸屾瑦绁扮€规洖鐏氶幈銊ョ暦閸モ晝鐒兼繛鎾村焹閸嬫捇鏌熼鍏煎仴鐎规洖鐖奸、妤呭焵椤掑嫬鍙婇柕澶嗘櫆閻撴洘绻涢幋婵嗚埞闁哄鍊楃槐鎺楁偐閼姐倗鏆梺璇″枟椤ㄥ懘鍩ユ径濞炬瀻婵☆垳鍘ф慨娲⒒娴ｈ銇熼柛妯恒偢閺佸啴鏁傞悙顒夋綗闂佸湱鍋撻崜姘跺触鐎ｎ喗鐓曟繝濠傚暙閺嗐垽鏌涘鐓庝喊闁诡喗顨呴埢鎾诲垂椤旂晫浜俊鐐€ら崢楣冨礂濮椻偓閻涱噣宕橀纰辨綂闂侀潧鐗嗗Λ妤佺濡ゅ懏鐓欓柤鍦瑜把呯磼閹绘帗鍋ョ€殿喛娅曠€佃偐鈧稒顭囬崢浠嬫⒑缂佹ɑ鐓ラ柟鑺ョ矒閹本绻濋崟顓狅紲婵犮垼娉涢張顒勫吹閳ь剙顪冮妶鍡樼┛缂傚秳绶氶獮鏍亹閹烘繃鏅濋梺鎸庣箓濞层劏鍊撮梻鍌氬€风欢姘焽瑜旈垾锕傤敇閻樿尙绛忛梺鍏肩ゴ閺呯偞鎱ㄩ崘娴嬫斀闁绘ê纾。鏌ユ煃闁垮鐏存慨濠傤煼瀹曞ジ鎮㈤幁鎺嗗亾閹烘埈鐔嗙憸搴∶洪悢鐓庤摕闁绘梻鍘х粈鍐煠绾板崬澧版い鏃€甯￠幃妤冩喆閸曨剛顦ョ紒鍓ц檸閸欏啴鐛径鎰妞ゆ棁鍋愰ˇ浼存⒑鐎圭姰鈧偓闁稿鎸剧槐鎺楀Ω椤垵娈銈庝簻閸熷瓨淇婇崼鏇炲窛妞ゆ牗绮犻崬鍫曟⒑鐠囨彃顒㈤柛鎴濈秺瀹曟粓鎮㈡總澶婃闂佽鍎兼慨銈夊疾閺屻儲鐓曟繛鎴濆綁缁ㄥジ鏌￠崒妤€浜鹃梻鍌氬€烽懗鍫曞磻閵娾晛纾块弶鍫氭櫅椤ユ碍銇勯幘鍗炵仼闁哄嫨鍎甸弻銊モ攽閸℃顦遍梺绋款儐閹搁箖骞夐幘顔肩妞ゆ帒鍋婄槐顓㈡⒒娴ｅ憡鍟炴慨濠傜秺瀹曞綊宕稿Δ鈧繚婵炶揪绲跨涵鍫曞几鎼淬劍鐓欓悗鐢殿焾娴犳粎鐥紒銏犵仩妞ゎ亜鍟存俊鑸垫償閳ュ磭顔戦梻浣规偠閸斿矂鎮ラ悡搴殨妞ゆ劧绠戝洿闂佺硶鍓濋悷褔鎯侀崼銉︹拺婵懓娲ら悘鍙夌箾娴ｅ啿鍟В鍕⒒閸屾瑦绁版俊妞煎姂閹偤鏁冮崒姘辩暫闂佺鏈銊╁汲閿曞倹鐓欓弶鍫ョ畺濡绢噣鏌涚€ｎ偄濮夐柍褜鍓涢幊鎾寸珶婵犲洤绐楅柡宓偓閺嬫棃鏌曟繛鐐珕闁抽攱鍨块幃宄扳枎韫囨搩浠肩紓浣插亾闁告劏鏂傛禍婊堟煛閸パ勵棞闁瑰啿绻樺畷妤€顭ㄩ崼鐔哄帗閻熸粍绮撳畷婊堟偄婵傚缍庨梺鎯х箺椤宕伴崱娑欑厱闁哄洢鍔屾禍婊冣攽椤旂虎鐒鹃柍瑙勫灴閸┿儵宕卞鍓х泿闂佽瀛╅惌顕€宕￠幎鐣屽祦闊洦绋戠粻锝夋煥閺冨洦顥夊ù婊勭矒閺岋綁鎮欑€电硶鏋旈梺閫炲苯澧柛妯荤墬缁旂喖寮撮姀鈾€鎷虹紓浣割儓濞夋洜绮婚悧鍫涗簻闁挎棁顕ч悘锛勭磼閸屾氨校闁靛牞缍佸畷姗€鍩為悙顒€顏归梻鍌氬€风欢锟犲磻閸℃稑纾绘繛鎴欏灪閸ゆ劖銇勯弽銊р姇婵炲懐濮甸妵鍕冀閵娧呯厒缂佺偓鍎抽妶鎼佸蓟濞戞矮娌柛鎾椻偓濡插牆鈹戦悙瀛樺剹闁革綇缍佸濠氬焺閸愨晛顎撶紓浣割儐鐎笛冣枔婵犳碍鍊甸悷娆忓缁€鍐偨椤栨稑娴柨婵堝仜閳规垿宕堕妸褏肖闂備礁鍟块幖顐﹀磹瑜版帗鍎婇柣鎰劋閳锋帒霉閿濆牊顥夐柛姘秺閺屾盯鎮╅崘鎻掝潕闂佸憡甯楃敮鎺楁偩濠靛鐒垫い鎺戝缁犳煡鏌曡箛鏇烆潔闁绘柨鍚嬮幆鐐烘偡濞嗗繐顏い鏃€娲熷缁樻媴閸涘﹨纭€婵犫拃鍕垫當妞ゎ厼鐏濊灒闁兼祴鏅欑粭澶愭⒑閹勭闁稿鍊婚幑銏ゅ幢濞戞瑧鍘梺鍓插亝缁诲倿顢旈浣典簻闁哄倹顑欏Ο鈧梺鍝勭灱閸犳牠骞冮崸妤婃晬婵炴垵褰夐崫妤冪磽閸屾瑦绁板瀛樻倐楠炴垿宕惰閺嗭箓鏌熼悜妯虹亶闁哄閰ｉ弻鐔衡偓娑欘焽缁犳挻銇勯鈧ˇ闈涱潖缂佹ɑ濯撮柣鐔煎亰閸ゅ姊洪悡搴ｇШ缂佺姵鐗犲畷娲倷閸濆嫮顓洪梺鎸庢⒒缁垶寮查埡鍛拺闁稿繗鍋愰妶鎾煛娴ｅ弶娅婇柡浣瑰姍瀹曘儵宕橀弻銉ュ及閻庤娲橀崕濂嘎ㄩ崒鐐搭棅妞ゆ帒顦晶顖炴煏閸パ冾伃濠殿喒鍋撻梺鏂ユ櫅閸熶即藝閻楀牏绡€缁炬澘顦辩壕鍧楁煕韫囨棑鑰跨€殿噮鍋婂畷鎺戔槈濮橈絾鏁甸梻浣烘嚀閸氣偓缂佲偓娴ｅ湱顩查柟顖嗏偓閺€浠嬫煟濡绲绘い蹇ｅ亞閻ヮ亪骞戦幇顓ф闂侀潧妫欑敮鎺楋綖濠靛鏁嗗ù锝堫潐閸婄兘姊绘担鍛婃儓妞ゆ垵妫濋獮鎴﹀炊椤掆偓閽冪喖鏌ㄩ悢鍝勑㈢€瑰憡绻冮妵鍕棘閸喒鎸冮梺姹囧€曠€氭澘顫忛搹鐟板闁哄洨鍠愬鎺楁⒑缁嬫鍎愰柟鍛婃倐閳ユ棃宕橀鍢壯囨煕閳╁喚娈橀柣鐔稿姍濮婃椽鎮℃惔鈩冩瘣闂佺粯鐗曢妶绋跨暦閻戞绡€闁搞儜鍐ㄧギ闂備胶绮鑽ゆ崲濠靛牐濮抽悹鍥ф▕濞撳鏌曢崼婵囶棡閻忓繒鏁婚弻娑氣偓锝庡墮娴犺京鈧娲樺姗€锝炲鍫濈劦妞ゆ帒瀚拑鐔哥箾閹存瑥鐏╅柣鎾达耿閺屾盯鈥﹂幋婵囩亾婵炲鍘ч悧鎾诲箖濡も偓閳绘捇宕归鐣屽蒋闂備線娼荤紞鍥╃礊娴ｅ摜鏆︽繛宸簻閻掑灚銇勯幒宥夋濞存粍绮撻弻鐔兼倻濡櫣浠村銈呯箚閺呮盯銆呮總绋垮窛閻庢稒菤閹锋椽姊洪崨濠勨槈闁挎洏鍎插鍕礋椤栨稓鍘遍梺缁樏崯鍧楀传濞差亝鐓欐い鏂垮悑閸嬨儵鏌涢埞鎯т壕婵＄偑鍊栫敮鎺斺偓姘煎弮閸╂盯骞嬮敂鐣屽幈闂佹寧妫侀褔鐛弽顬＄懓顭ㄩ崼銏㈡毇闂佸搫鐬奸崰鏍€佸☉姗嗘僵闁告劕妯婃导鍐⒑閹规劕鍚归柛瀣ㄥ€濆濠氬Ω閳哄倸浜滈梺鍛婄箓鐎氬懘鏁愭径瀣帗闂備礁鐏濋鍛存倶閳哄啰纾奸弶鍫涘妼濞搭喗銇勯姀锛勨槈闁宠棄顦埢搴ㄥ箣椤撶啘鐐测攽閻樺灚鏆╅柛瀣洴楠炲﹥鎯旈妸銉х枃濠殿喗銇涢崑鎾垛偓娈垮枦椤曆囧煡婢跺ň鏋庨柟瀵稿Х濡插洭姊绘担渚劸闁哄牜鍓涢崚鎺撴償閵忊晜顔勫┑鐘茬棄閺夊簱鍋撳Δ浣瑰弿闁绘垼妫勭壕缁樼箾閹存瑥鐏柛瀣儔閺岀喖宕滆缁♀偓缂備浇顕уΛ婵嬪蓟閻斿吋鈷掗悗闈涘濡差噣鏌涢悜鍡楃仸婵﹥妞藉Λ鍐ㄢ槈濮樿京鏆伴梻浣告啞閹歌崵鎹㈤崼婵愬殨闁割偅娲栫粻鐟懊归敐鍛辅闁归绮换娑欐綇閸撗勫仹闂佺儵鍓濋弻銊┾€﹂崶顒€绠涢柣妤€鐗忛崢閬嶆煙閸忚偐鏆橀柛濠冪墵閹敻顢旈崼鐔哄幐闂佸憡绋掑姗€鎮￠幇鐗堢厵妞ゆ牗绋掗ˉ鍫濃攽閳ュ磭鍩ｇ€规洘甯掗～婵嬵敆閸屾壕鏋旈梻鍌氬€搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻锝夊箣閿濆憛鎾绘煕閵堝懎顏柡灞剧洴椤㈡洟鏁愰崱娆欑穿闂備線鈧偛鑻晶鍓х磼閻樿櫕灏柣锝夋敱缁虹晫绮欏▎鐐秱闂備胶鍋ㄩ崕閬嶅疮鐠恒劏濮抽柕澶嗘櫆閳锋帒霉閿濆嫯顒熼柡鈧导瀛樼厵婵炶尪顔婇柇顖涙叏婵犱胶鐭欑€规洜鍠栭、娑橆潩鏉堛劎鍙勫┑鐘垫暩婵炩偓婵炰匠鍥舵晞闁糕剝绋掗崑鍌炵叓閸ャ劎銆掗柛娆愭崌閺屾盯濡烽幋婵婂闁告挷鍗冲娲焻閻愯尪瀚板褜鍨遍妵鍕Ω閵夛箑娈楅梺璇″櫍缁犳牕鐣疯ぐ鎺濇晝闁靛牆娲﹂崵宀勬⒒娓氣偓閳ь剛鍋涢懟顖涙櫠鐎电硶鍋撳▓鍨灈妞ゎ厾鍏橀獮鍐閵堝棗浜楅柟鑹版彧缂嶅棝宕ぐ鎺撯拻濞撴埃鍋撻柍褜鍓氱粙鎴濈暤閸℃绠惧ù锝呭暱閸熺娀寮搁弮鈧妵鍕箻鐠虹洅銉х棯閹规劖顥夐棁澶愭煥濠靛棙鍣洪柟顖氱墦瀵粙鏁嶉崟顓狅紳婵炶揪绲芥竟濠囧磿閹扮増鍋ㄦい鏍殔婢ф彃菐閸パ嶈含闁诡喚鏅划娆戞崉椤垶效濠碉紕鍋戦崐鏍偋濡も偓椤繈濡搁埡濠冩櫓婵犵數濮村ú锕傚煕閹寸姷纾兼い鏍ㄧ⊕缁€鈧繝鈷€鍕弨闁哄本娲熷畷鍫曞煛娴ｉ攱鍕冪紓鍌欑劍濮婂宕伴弽褜鍤曢柟缁㈠枟閸嬫劙鏌ｉ姀銏╂殰缂佸崬鍟块埞鎴︽倷閼搁潧娑х紓浣藉紦缁瑩鐛弽顓ф晝闁挎繂娴傚ú鍛婁繆閵堝繒鍒伴柛鐕佸灦閹繝寮撮姀鐘殿啇闁哄鐗嗘晶鐣屽閸ф鐓ユ繛鎴烆焽瀛濆銈庡弨濞夋洟骞夐幘顔肩妞ゆ帒鍋嗗Σ瑙勪繆閻愵亜鈧垿宕瑰ú顏呮櫇闁靛繆鍓濋崣蹇涙煃瑜滈崜鐔煎蓟閿濆拋娼ㄩ柍褜鍓欓…鍥槼闁逛究鍔戦弫鍌炲箣閹烘梻鐣鹃梻浣虹帛閸旓附绂嶅鍫濈劦妞ゆ帊鑳舵晶閬嶆煛娓氬洤娅嶆鐐村笒铻栭柍褜鍓涚划锝呂旀担鐟板伎濠殿喗顨呭Λ妤佹櫠婵犳碍鐓熼柟鍝勭Ф閻瑩鏌″畝鈧崰鏍嵁瀹ュ鏁婄痪鎷岄哺濮ｅ姊绘担铏瑰笡闁圭顭烽幃鐑芥晝閸屾锕傛煕閺囥劌鐏犵紒顐㈢Ч閺屾盯濡烽幋婵嗏偓褰掓儓韫囨稒鈷掑ù锝堟閵嗗﹪鏌￠崪浣风敖鐎垫澘锕畷绋课旈埀顒勬倿閸偁浜滈柟鐑樺灥閺嬨倖绻涢崗鐓庡缂佺粯鐩畷锝嗙珶濠垫劒绨介柛娆忔嚇濮婅櫣绱掑Ο娲绘⒖闂佺顑嗛崝鏇㈡偩閸偆鐟归柍褜鍓熼悰顕€寮介‖銉ラ叄椤㈡鍩€椤掍椒绻嗗ù鐘差儐閸婄敻鏌ｉ姀銈嗘锭鐎涙繂顪冮妶搴″绩婵炲娲熼獮鎴﹀礋椤戞儳浜伴梺鍓茬厛閸ｎ喗瀵奸崘鈺€绻嗛柕鍫濇搐鍟搁梺绋款儑閸嬬喖寮鈧獮鎺懳旈埀顒勬偂濮椻偓閺岀喐娼忔ィ鍐╊€嶉梺绋款儐閸旀妲愰幘瀛樺闁兼祴鍓濋崹鍧楀蓟閵娾晩鏁囬柕蹇婃閹疯櫣绱撴担鍓插剰閻忓繐鎳庨蹇涘Ψ閿旇桨绨诲銈嗘尵婵挳宕㈤幘顔界厱闁靛ň鏅濋悾娲煛娴ｇ鏆ｇ€规洘甯掗～婵堟崉閻戞ɑ姣嗛梻鍌氬€风欢姘焽瑜忛幑銏ゅ醇閵夈儱鐎繝鐢靛У绾板秹宕愰崹顔规斀闁稿本纰嶉崯鐐烘煃闁垮鐏╃紒杈ㄥ浮椤㈡稑鈽夊▎鎴К濠电姭鎷冮崱妤冩缂備浇椴哥敮鐐哄焵椤掑﹦绉甸柛瀣闇夋い鏇楀亾闁哄瞼鍠栭、娆忊枎瀹ュ應鍋撳Δ鍛仾闁逞屽墮閳规垿鎮欓弶鎴犱桓闂佽崵鍟欓崶褍鍋嶉梺鍛婎殘閸庢劕銆掓繝姘厪闁割偅绻冮ˉ婊冣攽椤斻劌鎳愮壕濂告煠閼规澘鐓愮痪顓炲缁辨帡顢欑喊杈╁悑閻庢鍠曠划娆愪繆閹间焦鏅查柛鏇ㄥ幘濞夊潡姊婚崒娆戠獢婵炰匠鍥ㄦ櫖闊洦绋戠粈鍐喐鎼搭煉缍栭柡鍥ュ灪閳锋帒霉閿濆懏鍟為柟顖氱墦閺岋綁顢橀悜鍡樞ㄧ紓浣戒含閸嬬偟绮悢鐓庣劦妞ゆ帒瀚崑妯汇亜閺囨浜惧Δ鐘靛仦鐢繝鐛€ｎ噮鏁囬柣鎰綑閳ь剦鍨跺缁樻媴鐟欏嫬浠╅梺绋垮瘨閸ｏ絽顕ｉ幓鎺嗘斀閻庯綆浜滈崑宥咁渻閵堝棛澧遍柛瀣仱閸╂盯骞掗幊銊ョ秺閺佹劙宕ㄩ鍏兼畼闂備浇顕栭崹浼存偋閹捐钃熼柨鐔哄Т闁卞洦銇勯幇鈺佺仼闁冲嘲顑夊铏规嫚閳ュ磭浠╅柣搴㈢煯閸楁娊濡存担绯曟婵妫欓崓鐢告⒑缂佹ɑ灏悗娑掓櫊椤㈡﹢骞愭惔婵堢畾闂佺粯鍔︽禍婊堝焵椤掍胶澧悡銈団偓骞垮劚椤︻垳澹曟繝姘厵闁告挆鍛闂佺粯鎸诲ú鐔煎蓟瀹ュ洦鍠嗛柛鏇ㄥ亜婵垺绻涚€涙鐭岄柛瀣尰缁岃鲸绻濋崶銊モ偓閿嬨亜韫囨挸顏ら柛瀣崌瀵粙顢曢敐鍡橆唶闂備礁婀遍崕銈夈€冮崨顖氼棜闁荤喐澹嬮弨浠嬫煟濡櫣锛嶆い锝嗙叀閺屾稒鎯旈姀鈺傜暦缂備胶绮惄顖氱暦閸楃倣鐔烘嫚閺屻儳鈧椽姊绘担铏瑰笡闁圭顭烽幃鐑藉煛閸涱叀鎽曢梺鎸庣箓椤︻垳绮诲☉銏♀拻闁割偆鍠撻埥澶嬨亜椤愵偂閭慨濠呮閹风娀鎳犻鍌ゅ晪濠电偛鐡ㄧ划宀勬偉閻撳寒鍤曞┑鐘崇閺咁剟鏌涢弴妯哄濞存粓绠栭弻銊モ攽閸℃侗鈧霉濠婂嫮绠栭柕鍥у婵＄兘濡疯閳敻姊洪崫鍕槵闁逞屽墮绾绢參寮抽崱娑欑厓鐟滄粓宕滈悢椋庢殾濞村吋娼欑粻濠氭偣閸ヮ亜鐨洪柛鏃撶畱椤啴濡堕崱妤冪懆闂佺锕ょ紞濠傤嚕閹惰棄鐓涢柛灞久肩花璇差渻閵堝棙灏甸柛瀣枑閺呭爼寮撮姀锛勫幗濡炪値鍘介崹鍨櫠鐎涙ɑ鍙忓┑鐘插鐢盯鏌熷畡鐗堝殗闁圭厧缍婇幃鐑藉箥椤曞懎浠归梻鍌欑劍閻綊宕洪崟顖氬瀭閺夊牃鏅滈弳婊堟煥閻斿搫孝闁哄绶氶弻娑㈠箛闂堟稒鐝梺杞扮閸婂潡寮诲☉銏╂晝闁靛牆鎳忛悗缁樼箾鐎涙鐭嬫い銊ユ嚇閳ユ棃宕橀鍢壯囨煕閳╁喚娈旂悰鑲╃磽閸屾瑨鍏屽┑顔炬暬瀹曞綊宕稿Δ鈧粻鏍ㄧ箾閸℃ê濮夌紒鈾€鍋撻梻浣规偠閸庮垶宕濇惔銊ュ偍妞ゅ繐鎳愮弧鈧梺姹囧灲濞佳勭濠婂牊鐓熼煫鍥ㄦ⒒缁犵偟鈧娲樼换鍌烇綖濠靛鏁囬柣鏂垮槻娴煎酣姊绘担鐟邦嚋缂佽鍊块獮濠囧箛椤撶喐鐝烽梺鎸庢婵倝宕ｈ箛鎾斀闁绘ɑ褰冮弳鐐烘煏閸ャ劎绠橀柍褜鍓濋～澶娒洪敃鍌氱；濠电姴鍟╃换鍡涙煟閹达絾顥夐崬顖炴⒑闂堟稓澧曢柟鍐茬箻楠炲濮€閵堝棌鎷绘繛杈剧悼閻℃棃宕靛▎鎴犵＜缂備焦锚婵鏌熼獮鍨伈妤犵偛顑夐弫鍌炴寠婢跺鏁鹃梺鑽ゅ枑缁瞼绮旈弶鎴犳殼闁告洦鍨遍埛鎴︽煕閿旇骞栨い锝呭悑缁绘繈濮€閳藉棛鍔风紓渚囧枤缁垳鎹㈠┑鍡╂僵妞ゆ挾鍋愰崑鎾诲垂椤愩倗顔曢梺鐟邦嚟閸庢劖绂掗悙顑句簻闊洦鎸炬晶閬嶆煛娴ｉ绐旈柡宀€鍠栭獮鍡氼槻妞わ絽纾惀顏堝箲閹邦収妫勯梻鍥ь樀閺屻劌鈹戦崱妯烘濡炪們鍎辩换姗€寮诲☉娆愬劅闁靛繒濮撮～鎺楁⒑鐠団€虫灍妞ゃ劌鐗忛崚鎺楊敇閻愨晜顫嶅┑鈽嗗灣閸庛倕鈻撳鍫熲拺闁告繂瀚烽崕鎰繆椤愩垹鏆ｆ鐐插暢閵囨劙骞掗幋鐘测偓鐐烘偡濠婂啴鍙勯柛鈹垮灲瀵挳鎮㈤搹璇″晭闂備礁婀遍崑鎾诲礈濮樿埖鍋傚┑鍌氭啞閻撴盯鎮橀悙闈涗壕缂佲偓鐎ｎ兘鍋撶憴鍕闁告鍥х厴闁硅揪绠戦柋鍥煏韫囧﹥娅呴柡浣风矙濮婄粯鎷呯粵瀣缂備降鍔忛崑鎰嚗婵犲啰绡€婵﹩鍓涢敍娑㈡⒑瑜版帒浜伴柛鐘愁殜閿濈偤寮撮姀锛勫幍闂佺粯鍨堕敃鈺佲枔閵忋倖鐓涘ù锝夋交闊剟鏌″畝瀣М闁轰焦鍔欏畷銊╊敊閼恒儱顏伴梻鍌欑窔濞艰崵寰婃總绋跨闁规儼妫勭粻鏍ㄤ繆閵堝倸浜鹃梺宕囩帛閹瑰洤鐣疯ぐ鎺濇晩闁伙絽鑻拏瀣⒒閸屾瑨鍏屾い顓炵墦椤㈡牠宕ㄩ妤€浜炬慨姗嗗亜瀹撳棝鏌曢崱鏇狀槮閾伙綁鏌ゆ慨鎰偓婵嗩瀶椤斿墽纾藉ù锝呭閸庢挻绻涙径瀣鐎规洘鍔欓幃娆撴倻濡攱瀚奸梻浣告贡椤牏鈧稈鏅犺棢闁糕剝眉缁诲棙銇勯幇鈺佺仼妞ゅ浚浜弻娑㈠箳閹搭垱鏁鹃柣搴濈祷閸嬫劙鍩€椤掍胶鈯曢懣銈夋煙妞嬪海甯涚紒缁樼⊕濞煎繘宕滆琚ｆ繝纰樻閸嬪嫮鈧凹鍨堕妴鍌炲锤濡や讲鎷绘繛杈剧悼閹虫捇顢氬鍛／闁哄娉曟晥婵犵绱曢弫璇茬暦閻旂⒈鏁嶆繛鎴炵懄閻濇洟姊绘担绋挎倯濞存粈绮欏畷鏇㈠箮閽樺顦╅梺璺ㄥ枔婵敻鍩涢幋锔藉€甸柛锔诲幖椤庡矂鏌涢妶鍡欐噮缂佽鲸甯楀鍕沪閹勭暚闂備椒绱徊浠嬪床閺屻儻缍栨繝濠傜墕閻掑灚銇勯幒鎴濐仴闁逞屽厸缁€渚€鍩㈡惔銊ョ闁哄鍨抽幃锝夋⒑鐠囪尙绠抽柛瀣Т铻為柛鏇ㄥ幘娑撳秵绻涘顔荤凹闁抽攱甯掗湁闁挎繂娲ら崝瀣煕閵堝倸浜鹃梻鍌欑閹诧繝鎳濇ィ鍐炬晞濠㈣埖鍔曠粻鏍旈敐鍛灓闁轰礁鍊块弻娑㈩敃閿濆洨鐣奸梺鎸庣⊕閻熲晛顫忓ú顏咁棃婵炴垶鑹鹃。娲⒑閻熸澘妲绘い鎴濐樀楠炲啴鎮欑€靛壊娴勯柣搴秵閸嬪棝宕㈤悽鍛娾拺閻熸瑥瀚烽崯蹇涙煕閻樺磭澧甸柕鍡楀€圭缓浠嬪川婵犲嫬骞楅梻浣筋潐瀹曟ê鈻斿☉銏犲嚑闁硅揪闄勯悡蹇涙煕閵夋垵鍠氭导鍐ㄎ旈悩闈涗沪闁挎岸鎽堕弽顓熺厓鐟滄粓宕滈悢椋庢殾妞ゆ牜鍎愰弫宥夋煟閹邦厽缍戦柍褜鍓欓悥濂稿蓟閻旂厧绠氱憸宥夈€傚畷鍥╂／闁硅鍔栭ˉ澶愭煏閸℃ê绗掓い顐ｇ箞椤㈡鎷呯憴鍕偓鐑芥⒒娴ｅ憡鎯堟い鎴濇缁瑩骞掑Δ鈧闂佸憡娲﹂崹濂稿极閸ヮ剚鐓熸俊顖濐嚙缁茬粯顨ラ悙宸剰閾绘牠鏌ｅ鈧褎绂掑鍫熺厱闁绘棃顥撻幗鐘绘煙娓氬灝濮傞柛鈹惧亾濡炪倖甯掔€氼參鎮¤箛娑氬彄闁搞儺鐏掗崼銉ョ；闁规崘顕х粈鍌炴煕濞戝崬鐏﹂柟绋裤偢濮婂宕掑顑藉亾閻戣姤鍤勯柛顐ｆ礀绾惧鏌曟繛鐐珔缁炬儳娼″娲敆閳ь剛绮旈幘顔肩＜闁靛ň鏅滈悡娑氣偓骞垮劚閸燁偅淇婇崸妤佺厽婵犻潧妫涢崺锝夋煛瀹€瀣瘈鐎规洖鐖兼俊鐑藉Ψ瑜岄惀顏堟⒒娴ｇ懓鈻曢柡鈧柆宥呭瀭闁秆勵殔閽冪喖鏌曢崼婵囶棡闁告瑥绻橀弻鐔兼焽閿曗偓閸樻挳鏌涚€ｎ偅宕岀€殿喗鎸虫慨鈧柣妯诲絻濞堛倝姊绘担鍛婃儓闁稿﹤缍婇、鏍р枎閹炬潙浜滈梺绯曞墲閻燂箓宕伴幇鏉跨婵烇綆鍓欐俊鎼佹煃瑜滈崜娆撳疮閺夋垹鏆﹂柕濞р偓閸嬫挸鈽夊▍铏灥閳诲秹宕堕浣叉嫼闂傚倸鐗婄粙鎾剁不濮樿埖鐓冪憸婊堝礈濮樿泛绀堟慨妯挎硾閸氬綊鏌曢崼婵愭Ч闁绘挾鍠栭獮鏍庨鈧悘顕€鏌嶉娑欑闁靛洤瀚伴、姗€鎮欓弶鎴炵亷闁诲氦顫夊ú蹇涘垂娴犲钃熼柛鈩冾殢閸氬鏌涢垾宕囩閻庢艾銈稿濠氬磼濮橆兘鍋撻幖浣瑰亱濠电姴鍟伴悷瑙勪繆閵堝懏鍣洪柛瀣€归妵鍕箻鐠虹洅銉х棯閹佸仮闁哄矉绲借灒闁告繂瀚В鎰版⒑鐠囪尙绠版い鏇ㄥ弮閸┾偓妞ゆ帒鍠氬鎰箾鐠囇呯暤鐎规洘鍨剁换婵嬪炊瑜忛鎰版偡濠婂懎顣奸悽顖涘笧缁牓宕掑鑲╁數闁荤姾娅ｇ亸銊ヮ潖濡も偓椤法鎲撮崟顒傤槬闂佸疇顫夐崹鍧楀箖濞嗘挻鍤戞い鎺嗗亾妞わ絾妞藉铏规嫚閼碱剛顔夌紓浣筋嚙閻楀棝顢氶敐鍥╃煓閹煎瓨鎸婚悗濠氭⒑閻熼偊鍤熷┑顔惧厴閺佸秴顭ㄩ崘鐐瘜闂侀潧鐗嗗Λ娆撳煕閹烘鐓涢柛婊€绀佹禍鐗堫殽閻愯韬€规洘锕㈤、娆撴偩鐏炶棄绠洪梻鍌欑劍鐎笛呮崲閸屾娲Χ婢跺﹤鍋嶉柣搴㈢⊕閿曗晛鈻撴禒瀣厽闁归偊鍓欑痪褎銇勯妷锝呯伈闁哄矉绱曟禒锕傛嚍閵夈儲鐏庨梻浣芥〃缁€渚€宕愰崹顔炬殾闁挎繂顦介弫鍐煟閺傛寧鍟為柣婵囨礈缁?",
            "project_adaptation": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎娆戠┛闂傚倷绶氶埀顒傚仜閼活垱鏅堕崜褏纾奸柣妯挎珪鐏忣參鏌ｉ敐澶嬫暠缂佽櫣鏅划娆忊枎閻愵剛绉遍梻鍌欒兌閸嬨劑宕曢柆宥呯柈閻犳亽鍔忔慨鎶芥煏婢跺棙娅嗛柍閿嬪笒闇夐柨婵嗘川閹藉倹绻涢崗鐓庡妞ゎ厼娼￠幃鐑芥偋閸偅锛侀梻浣告惈閹虫挸鈻斿☉婊呬簷闂備礁鎲℃笟妤呭储妤ｅ啯鏅繛鎴欏灪閻撶喖骞栭幖顓炵仯缂佸鏁婚弻娑㈡偐閹颁焦鐤侀梺璇″櫙缁绘繂顕ｉ幘顔碱潊闁挎稑瀚敮妤呮⒒娴ｅ摜鏋冩俊妞煎妿缁牊绗熼埀顒€顕ｉ幎鑺ュ亜闁稿繗鍋愰崢鎾绘⒑閼恒儍顏埶囬挊澹╃喖鍩€椤掑嫭鈷戦柛婵嗗濠€浼存煟閳哄﹤鐏″ǎ鍥э躬楠炴牗鎷呴懖婵勫姂閺屾洘寰勯崼婵堜患婵炲瓨绮撶粻鏍蓟濞戞粠妲煎銈冨妼閻楀棝鎮鹃崹顐ょ懝闁逞屽墴瀵鍨鹃幇浣告倯闁硅偐琛ラ埀顒冨皺閺佹牜绱撴担鍝勪壕闁稿孩濞婃俊鍫曞箹娴ｆ瓕鎽曢梺鎸庣箓閹叉﹢寮崼婵堝姦濡炪倖甯掔€氼參宕戠€ｎ喗鐓曢柍鈺佸暢濞夋彃顭块懜闈涘缂佺姵鐩弻锝呂旈埀顒勬偋韫囨稑鍌ㄩ梺顒€绉甸悡鐔煎箹閹碱厼鐏ｇ紒澶屾暬閺屾稓鈧綆浜濋崳褰掓煟閿濆妫戝ù鐙呭缁辨帡濮€閳藉棗鏅梻鍌欒兌缁垶宕濋弽褜鐒芥繛鍡樺灩缁犳棃鏌熼悜姗嗘畷闁硅櫕宀搁弻鈥愁吋鎼粹€崇闂佺粯鎸搁崯浼村箟缁嬫鐓ラ柛顐ｇ箘椤︻厼鈹戦悙鍙夘棡闁瑰皷鏅犲顐ｇ節閸モ晛褰勯梺鎼炲劘閸斿秶浜搁妸鈺傜厸闁逞屽墯缁傛帞鈧綆鍋嗛崢閬嶆⒑闂堟侗妾х紒韫矙瀹曟繂鈻庨幋鐘碉紲闂侀潧顭堥崕娲偂閸忓吋鍙忓┑鐘叉噺椤忕娀鏌熼崣澶嬪唉鐎规洜鍠栭、鏇㈠Χ鎼粹懣鐐测攽閻樺灚鏆╅柛瀣洴钘濆ù鐓庣摠閸庡孩銇勯弽銊ュ毈闁搞倖娲熼弻鐔兼⒒鐎靛壊妲紓浣哄缂嶄線寮婚妸鈺佺睄闁稿本绋掗悵顏堟⒑閸涘鑰垮ù婊嗘硾椤繘鎼归崷顓狅紲濠碘槅鍨板ù姘閻愬鐝堕柡鍥ュ焺閺佸洭鏌曡箛鏇炐ラ柛妯诲姍濮婃椽宕崟顒€绐涙繝娈垮櫍椤ユ挻绔熼弴銏″殐闁冲搫鍟伴敍婵囩箾鏉堝墽绉い鏇熺墵閹偞绂掔€ｎ偆鍘梺绯曞墲閿氭繛鎼櫍閺岋紕浠﹂悾灞濄儲銇勮缁舵岸寮诲☉銏犵閻庢稒顭囧▓銈囩磽娓氬洤鏋熼柣鐔叉櫊閻涱噣骞掗幋顓熷瘜闂佺粯鍨熼弲娑欑妤ｅ啯鐓ラ柡鍥╁仜閳ь剚鎮傞幃娆愮節閸愶缚绨婚梺鐟版惈缁夊爼藝閿曞倹鐓曢柟鎯х－缁夋椽鏌″畝瀣ɑ闁诡垱妫冮、娑橆煥閸涘拑缍佸娲川婵犲啫闉嶇紓浣割儐閹歌崵绮╅悢鐓庡嵆闁绘梹妞藉顕€姊洪崨濠勨槈闁挎洏鍊濋崺鈧い鎺戝€归弳顒勬煛鐏炶濡奸柍瑙勫灴瀹曞崬鈽夐幍浣镐壕婵°倐鍋撻棁澶嬬節婵犲倸顏紒鐘靛仱閺岀喖顢欑粵瀣姼缂備胶濮甸惄顖氼嚕閹绢喗鍋勯柛娑橈功濡叉姊婚崒娆戭槮闁圭⒈鍋婂鐢割敆閸曨剙鍓銈嗙墱閸嬬喎鐣垫笟鈧弻鐔兼倻濮楀棙鐣剁紓浣哄Т椤兘寮昏缁犳盯鏁愰崨顒€鍤遍梻浣界毇閸屾粠妲梺瀹狀潐閸ㄥ潡骞冮埡浣叉灁闁圭瀛╅惁婊堟⒒娴ｅ憡鍟為柟姝屽吹閹广垽宕奸妷褍绁﹂梺鍛婂姦閸犳牜澹曟總鍛婄厽闁归偊鍓欑痪褎淇婂顔煎⒋婵﹥妞藉顒勫Ψ閿旂晫褰呴梻浣告憸閸ｃ儵宕归柆宥呯濠电姴瀚ч崑鎾绘濞戞瑦鍠愮紒鐐劤閵堟悂骞冨Δ鍛櫜閹肩补鈧尙鐩庢俊鐐€栧ú妯煎垝瀹ュ桅闁告洦鍨扮粻濠氭煙妫颁浇鍏岄柛姘儏閳规垿顢欑涵宄颁紣濡炪値鍘奸崲鏌ユ偩閻戣棄绠抽柟瀛樻⒐閻庡姊虹憴鍕剹闁告ê鈧啿鍙洪梻鍌氬€搁崐宄懊归崶顒婄稏濠㈣泛鐬奸惌鍫ユ煙缂併垹鏋涢柣鎺戠仛閵囧嫰骞掗幋婵囨閻炴熬绠戦埞鎴︽倷閸欏鏋欐繛瀛樼矋缁诲牆顕ｉ幓鎺濈叆闁割偆鍠撻崢浠嬫⒑閹稿海绠撻柟铏姍閹偤鎮欓鍌滎啎闂佸憡鐟ラˇ浼村磹閹邦厽鍙忓┑鐘叉噺椤忕姷绱掓潏銊ョ瑨閾伙綁鏌涘┑鍡楊伌婵炲吋娲熷缁樻媴閼恒儯鈧啰绱掗埀顒佺瑹閳ь剟鐛径鎰櫖闁告洦鍘鹃悡鎾寸節閵忥絾纭炬い顓у墴瀹曘儳鈧綆鍠楅悡鏇熸叏濡鍔氶柍褜鍓氬ú婊呮閻愬绡€闁搞儜鍛毇闂備礁鐤囧銊ф閿熺姴鐤柛娑卞枔娴滄粓鏌￠崘銊モ偓鍝ユ暜鐠轰警鐔嗛柣鐔煎亰濡偓濠殿喖锕︾划顖炲箯閸涘瓨鎯為柣鐔稿椤愬ジ姊绘担鍛婅础妞ゎ厼鐗撻垾锕傛倻閽樺鐣洪梺缁樺灱濡嫰鎮″☉妯糕偓鎺戭潩椤掍礁顦╃紓鍌氱Т鐎涒晝鎹㈠┑瀣仺闂傚牊鍒€閿濆鐓犵憸鐗堝笧閻ｆ椽鏌熼鎯т槐鐎规洖缍婇、鏇㈡偐鏉堚晝娉块梻鍌欑濠€閬嶅磿閵堝鍨傞柣銏犲閺佸倿鏌嶉崫鍕殶缁炬儳銈搁弻锝呂熼搹鐧哥礊闂佹剚鍨卞ú鐔煎蓟閺囥垹鐐婄憸宥夘敂椤撶噥娈介柣鎰煏椤忓洨浜欓梻渚€鈧偛鑻晶浼存煃瑜滈崜姘舵儍濠婂牆鐐婄憸宥夊吹閹达附鈷戦柛鎾村絻娴滄牠鏌涢妸銊ュ惞濠㈣娲樼粋鎺斺偓锝庡亞閸橀亶鏌ｈ箛鏇炰沪鐎规洘蓱缁旂喎顫滈埀顒勫蓟瀹ュ牜妾ㄩ梺鍛婃尰閻╊垰鐣峰Δ鈧～婊堝焵椤掑嫮宓侀柛鎰靛枟閸婄兘鏌ｉ幋鐐嗘垵鈻嶉崶顒佲拺缂佸瀵у﹢浼存嚕閵堝鐓曢悗锝庡亝瀹曞瞼鈧娲橀敃銏ゃ€佸▎鎾村亗閹艰揪绲垮畷鍝勨攽閻樻剚鍟忛柛鐘愁殘缂傛捇宕稿Δ鈧壕褰掓煛閸モ晙绱虫繛宸憾閺佸洭鏌ｉ幇顒傂ｉ柣鈺婂灠閻ｅ嘲顫滈埀顒佷繆閹间礁顫呴柍钘夋缂嶅苯鈹戦悩鎰佸晱闁哥姵顨婇弫鍐煛閸涱厼鍋嶆繛瀵稿Т椤戞劙寮繝鍥ㄧ厸闁搞儮鏅涢弸鏃傜磼閳锯偓閸嬫捇姊绘担鍦菇闁搞劏妫勯…鍥樄闁糕斂鍨藉畷濂告偄閾忚鍟庡┑鐐舵彧缁蹭粙宕崹顔氬綊宕掗悙鍙夌€梺鍛婃处閸ㄩ亶鎮￠弴鐘亾閸忓浜鹃梺閫炲苯澧寸€规洘鍨甸埥澶愬閳ユ枼鍋撻崸妤佺厱妞ゎ厽鍨垫禍鏍瑰鍕煉闁哄瞼鍠栭幃婊兾熼搹鐟板笌闂備礁鎲″濠氬窗閺嶎厼钃熼柨婵嗩槹閺呮煡鏌涘☉鍗炵仧缂侇噣娼ч—鍐Χ閸愩劌惟闂佺娴烽弫濠氱嵁閸愩劉鏋庨柟鎯х－妤犲洭姊洪悷閭﹀殶闁稿濞€閹倹绗熼埀顒勫蓟閿濆棙鍎熼柕蹇婃櫅閺呴亶姊洪棃鈺冪У闁革綇绲介悾鐑藉箮閼恒儲娅滈梺鍛婁緱閸ㄥ崬鈻撴ィ鍐┾拺闁革富鍘奸崝瀣亜閵娿儲鍣规繛鎻掓健濮婄粯鎷呴崨濠冨枑婵犳鍣ｇ粻鏍х暦濞差亜鐐婃い鎺嗗亾缁炬儳娼″濠氬醇閻斿墎绻佸┑鐐插悑閻楁洟鍩為幋锔藉亹閻庡湱濮撮ˉ婵堢磼閻愵剙鍔ら柛姘儑閹广垹鈽夐姀鐘茶€垮┑鈽嗗灥濞咃綁宕濈粙搴撴斀闁炽儴娅曢埢鏇㈡煕閿濆繒鍒版い顐㈢箻閹煎湱鎲撮崟顐㈠箲闂備礁鎲＄划鍫㈢矆娴ｇ硶鏋旀繝闈涚墢绾捐棄霉閿濆嫮鐭欓柛婵堝劋缁绘盯鎳犻鈧弸娑㈡煟濞戝崬娅嶆鐐差儔閺佸啴鍩€椤掑嫸缍栭柛娑樼摠閻撶喐绻涢崱妤勫濞存粓绠栧娲川婵犲懎顥濆銈嗗灥椤﹂潧顕ｇ拠娴嬫闁靛繒濮烽崝鎾⒑閸涘﹤濮﹀ù婊勭箞瀹曟娊鎸婃径鍡樻杸闂佺粯鍔樺▔娑㈡儍閻戞ǜ浜滄い鎾跺仧婢э箓鏌涢埡鍐ㄤ槐妤犵偛顑夐弫鍌炴寠婢跺棗浜鹃柣鎴ｅГ閻撴洘绻涢崱妤佺婵☆垰鐗婃穱濠囶敃椤掑倻鐦堝┑顔硷攻濡炰粙鐛弽顓熷€烽柟缁樺俯閻庢娊姊绘担鍛婂暈闁煎綊绠栭、鏍ㄥ緞閹邦喖绁﹂梺鍓插亖閸庤鲸鍎梻浣稿暱閹碱偊宕愯ぐ鎺戠？妞ゅ繐瀚峰〒濠氭煏閸繃顥滃┑顔煎€块弻娑欑節閸愮偓鐤佸銈冨灪閻熲晛顕ｉ幘顔碱潊闁炽儲鏋奸崑鎾绘偨閸涘﹦鍘介梺缁樻煥閹诧紕娆㈤崣澶堜簻闁靛鍎崇粻濠氭煛鐏炲墽娲撮柟顔规櫊閹煎綊顢曢妶搴⑿ら梻鍌欑閸氬顪冮懞銉ь洸闁割偅娲栫粻鐘绘煥閻斿搫孝閸ユ挳姊洪幖鐐插姉闁哄拋浜炲Σ鎰板蓟閵夛腹鎷绘繛杈剧秬濞咃絿鏁☉銏＄叆婵鍩栭悡鏇㈡煟閺冨牊鏁遍柛瀣ㄥ劦閺屾盯鍩為崹顔句紙閻庢鍠楅幐铏叏閳ь剟鏌ㄥ☉妯侯仼妤犵偞鍔欏铏规嫚閼碱剛顔婇梺绋款儑閸犳牕鐣烽幋锕€绠婚柛鎾茶兌閻掑ジ姊洪崨濠傚Е濞存粍鐗犲畷鎴﹀箻鐠囨彃鐎銈嗗姧缁插潡宕欓敓鐘崇厽閹兼番鍨婚。鍙夌節閵忊槄鑰块柟顕€绠栭幃婊堟嚍閵夈儰绨甸梺鍦帶閻°劏鎽梺鍝勫€甸崑鎾绘⒒閸屾瑨鍏岀痪顓炵埣瀹曟粌鈹戠€ｃ劉鍋撻崘顓犵杸闁瑰灝鍟伴崝宄扳攽閻愭潙鐏︽慨妯稿妿婢规洘绂掔€ｎ偆鍘遍柣蹇曞仦瀹曟ɑ绔熷鈧弻宥堫檨闁告挻宀搁獮鍐磼濮樿鲸娈鹃梺鍦濠㈡ɑ瀵奸悩缁樼厪濠㈣鍨伴幊鎰板储閻樼粯鈷掑ù锝呮贡濠€浠嬫煕閵娿儺鐓奸柍銉畵瀹曞ジ濮€椤厾鐟濋梻浣告惈鐞氼偊宕曢弻銉﹀亗闁哄洢鍨洪悡蹇擃熆閼稿緱顏堝几濞戞﹩鐔嗙憸婊堝垂閸洖钃熸繛鎴炲焹閸嬫捇鏁愭惔婵堢泿闂侀€炲苯澧紓宥咃攻娣囧﹪鎮界粙璺槹濡炪倖鐗楀銊╂偪閳ь剟姊绘担鍛婂暈闁瑰摜鍏橀幊妤呭醇閺囩偞杈堥梺缁橆焽缁垶鍩涢幋鐘电＝濞达絽顫栭鍛弿闁搞儺鍓氶悡銉╂煛閸ユ湹绨介柣锝呯仛椤ㄣ儵鎮欏顔解枅閻庤娲忛崝宥囨崲濠靛绀冮柕濞垮劚闊﹂梻鍌氬€风欢姘焽瑜旈垾锕傚醇閵夈儳锛熼梻渚囧墮缁夊绮诲鑸电厽闁归偊鍠栭崝瀣煃闁垮鐏撮柡宀€鍠栭幊鏍煛娴ｉ鎹曢梻浣告啞濮婂綊骞愰幎钘夎摕婵炴垯鍨圭粻濠氭煛婢跺鐏ラ柟鐣屾暬濮婅櫣鎷犻垾铏闂侀潧鐗嗗ú銊╁级缁嬪簱鏀介柣鎰綑閻忥箓鏌ｉ悢婵嗘搐閸屻劑姊洪鈧粔鐢稿煕閹达附鐓涢柛灞久崝婊勭箾閸涱厽鍤囬柡灞剧洴閹晝鈧湱濮撮ˉ婵嬫⒑瀹曞洨甯涢柟鍛婄摃閻忔帡姊洪崗鑲┿偞闁哄懏绻堥弫宥咁煥閸啿鎷虹紓鍌欑劍閳笺倝顢旈崼婵堫啇濡炪倖鍔х粻鎴犳喆閿旂偓鍠愰柣妤€鐗嗙粭姘舵煟閹惧啿鏆熼柟鑼焾椤劑宕煎┑鍫Ф婵犳鍠楅敃銏ぢ烽崒鐐叉瀬濠电姴娲﹂悡娑氣偓骞垮劚妤犳悂鐛弽顐ょ＜闁归偊鍙庡▓婊堟煛瀹€鈧崰鏍嵁閹达箑绠涢梻鍫熺⊕椤斿嫮绱撻崒娆掝唹闁稿鎸搁…鍧楁嚋闂堟稑顫嶉梺缁樻尰閻熲晛顕ｉ崼鏇為唶婵犻潧妫岄幐鍐⒑娴兼瑧绉ù婊庡墰濡叉劙骞掑Δ浣镐汗闂佸憡鍔栬ぐ鍐箺閻㈠憡鈷戦柛婵嗗濠€鎵磼鐎ｎ偄鐏撮柟顔藉劤閳规垹鈧綆浜為崝锕€顪冮妶鍡楃瑨閻庢凹鍓涙竟鏇犵磼濡偐顔曢梺鐟邦嚟閸嬬喖骞婇崘鈹夸簻闁哄浂婢€閹查箖鏌″畝瀣埌閾伙綁鏌ゅù瀣珔缂佹绻濆铏圭磼濡纰嶇紓浣虹帛閸旀瑩鍨鹃敂鐐磯闁靛绠戦悵浼存⒑閻愯棄鍔氱痪缁㈠幗缁傛帡鍩￠崨顔规嫼闂佸憡绻傜€氼喗鏅堕柆宥嗙厱闁规儳顕幊鍥┾偓娈垮枟婵炲﹪宕洪敓鐘插窛妞ゆ棁顫夌€氫粙姊绘担渚劸闁哄牜鍓熼幊婵囥偅閸愩劎鍔﹀銈嗗笂閻掞箓宕愰幇顔瑰亾鐟欏嫭绀冮柛鏃€鐗犺棟闁绘鐗婇崕鐔兼煥濠靛棙宸濋柛鏃囨硾閳规垿鎮欑€涙ê闉嶉梺绯曟櫅閸熸潙鐣烽幋锕€绠婚柟纰卞幗椤旀棃姊虹紒妯哄婵☆垰锕よ灒闁逞屽墴濮婄儤娼幍顔煎闂佸湱鎳撳ú顓㈢嵁閸愵喖鐓涢柛娑卞枛濞堛倕顪冮妶鍡楃瑨妞わ附婢橀弳鈺呮⒒閸屾艾鈧悂宕愭搴ｇ焼濞撴埃鍋撴鐐寸墵椤㈡洟鍩涘顓熴仢濠碘剝鎮傞弫鍌炴寠婢跺﹣绱熼梻鍌欒兌缁垶宕归崗鍏煎弿闁靛牆顦壕鎸庝繆閵堝懏鍣洪柣鎾寸懇閺岀喖顢涢崱妤€鏋ら柡鍡愬灩閳规垿鍩ラ崱妞捐埅闂佹悶鍔岄悥鐓庮嚕婵犳碍鍋勭痪鎷岄哺閺咁剟姊虹化鏇炲⒉妞ゃ劌顦遍埀顒佺煯閸楁娊寮诲☉銏犵闁告劑鍔岀粻铏圭磽娴ｈ櫣甯涚紒瀣崌閸┾偓妞ゆ帊鑳堕埊鏇熴亜椤撶偞鍠橀柟顖氭湰缁绘繈宕橀鍡欐闂備線鈧偛鑻晶鎾煛鐏炶姤顥滄い鎾炽偢瀹曘劑顢涘鍕偓顐︽⒒閸屾瑧顦﹂柟璇х磿缁瑩骞嬮敂鑺ユ珖闂侀潧顦弲娑氬閸ф鐓熼柡鍌氱仢閹垿鏌ｉ幘宕囩闁宠鍨块幃鈺呮嚑椤掑偆鍞洪柣搴″帨閸嬫挻绻涢幋娆忕仾闁绘挻娲熼幃妤呮晲鎼粹€茬凹閻庤娲栭惉濂稿焵椤掑喚娼愭繛鍙夛耿閺佸啴濮€閵堝啠鍋撴担绯曟瀻闁规儳鍟跨花銉︾節閵忥絾纭鹃柣妤€妫欓幈銊╁磼閻愬鍘搁柣蹇曞仧閸嬫挾绮堥崘顏嗙＜闁哄啫鍊搁弸娑欍亜閵忥紕鈽夋い顐ｇ箞椤㈡寰勬径灞撅紡闂傚倸鍊峰鎺旀椤旀儳绶ら柛褎顨呯粈鍌涗繆椤栨瑨顒熸繛鍏肩墱缁辨挻鎷呴懖鈩冨灦閸掑﹪骞橀鐣屽幈濠电偞鍨堕敃顐㈩啅閵夆晜鐓涢柛鈩冾殘婢э附鎱ㄦ繝鍐┿仢鐎规洏鍔嶇换婵嬪礃閻愵剦妫濋梻鍌氬€搁崐鍝モ偓姘煎墰閳ь剚鍑归崰姘跺礆閹烘柡鍋撻敐搴濇喚闁告艾顑夐弻娑樷槈閸欐鍑归梺鍝勫€甸崑鎾绘⒒娴ｇ瓔鍤欓柛鎴犳櫕瀵板﹪鎳為妷锔界彿闁硅壈鎻徊鍧楁儗濞嗘挾鍙撻柛銉ｅ妿閳洟鏌涙繝鍌滀粵妞ゃ劊鍎甸幃娆撴嚑椤戣儻妾搁梻浣告啞濮婂湱鍠婂鍥ㄥ床婵炴垶鐭▽顏堟煕鐏炴崘澹樻い顒€顑嗙换婵嬪閿濆孩缍堝┑鐐跺皺閸犳牠鐛幇顓犵瘈闁告劦浜炶ぐ鎯р攽閻樼粯娑ф俊顐ｇ〒缁柨煤椤忓懐鍘告繛杈剧悼閹虫挻鎱ㄥ鍥ｅ亾鐟欏嫭绀€闁靛牊鎮傞妴渚€寮撮姀鐙€娼婇梺鎸庣☉鐎氼厼鈻撻懜鐢电瘈闁汇垽娼у暩闂佽桨鐒﹂幃鍌氱暦閹存績妲堥柕蹇娾偓鍏呯綍闂備礁鎲″ú锕傚垂娴兼潙鍨傞柛灞绢嚔瑜版帗鍋愮€瑰壊鍠栭崜浼存⒑閽樺鏆熼柛鐘冲姉閹广垹鈽夐姀鐘殿吅闂佺粯鍔楅弫鎼佹偂閸岀偞鈷戞慨鐟版搐閳ь剚鍔欏畷鎴﹀箻缂佹ǚ鎷绘繛杈剧到閹诧繝骞嗛崼銉︾厱闁绘洑绀佹禍鎵偓瑙勬礃閸旀瑥鐣锋總绋垮嵆闁绘劙娼ф慨锔戒繆閻愵亜鈧牜鏁繝鍕焼濞达綀娅ｇ粻鏃傛喐韫囨洘顫曢柟鐑樻尰缂嶅洭鏌曟繛鍨姕閻犲洨鍋涢—鍐Χ閸愩劎浠鹃梺鑽ゅ暀閸パ呯枀闂佸湱铏庨崰鏍矆鐎ｎ偁浜滈柟鐑樺灥閳ь剙鎽滃濠囧锤濡や讲鎷婚梺绋挎湰閻熝呯玻閺冨牊鐓冪憸婊堝礈濞戙垹纾绘繛鎴欏灪閸ゆ劖銇勯弽銊р姇婵炲懐濮甸妵鍕冀閵娧呯厒缂佺偓鍎抽妶鎼佸箖濡ゅ懏鏅查幖绮光偓鑼泿婵犵數鍋為幆宀勫闯閿濆钃熼柍鈺佸暞婵挳鏌涢幘鏉戠祷闁告挸纾槐鎾存媴娴犲鎽甸梺鍦焾椤兘鐛箛娑樺窛妞ゆ牗绮庨悡鎾斥攽閻愬弶顥犻柛瀣尭閳绘挸煤椤忓應鎷绘繛杈剧导鐠€锕傛倿閻愵兙浜滈柟瀛樼箓閺嗭絿鈧娲橀崝鏇㈠煘閹达箑骞㈤柍杞扮劍椤撳潡姊洪懡銈呅㈡繛璇у缁﹪寮堕幊绛圭秮瀹曞ジ濡烽敂鎯у妇闂傚鍋勫ú锕€煤閺嵮呮懃闂佽姘﹂～澶愬箰缁嬭娑樷攽閸♀晜缍庡┑鐐叉▕娴滄繈藟閸喓绠鹃柟杈剧导閸氼偊鏌涢弮鈧幃鍌氼潖閾忓湱鐭欓柛顭戝櫘閸斿绻濋姀銏″殌婵☆偅绻堥獮濠囨倷鐎涙绉堕梺闈浤涢崨顖涱潓濠电姵顔栭崰妤呮晝閳哄懎鍌ㄩ柛蹇氬亹椤╅攱銇勯幘璺轰汗闁衡偓娴犲鐓熸俊顖涱儥閸ゅ鈧鎮堕崕鐢稿箖濡も偓椤繈鎮℃惔鈾€鎷梺鑺ヮ焽閸犳牠骞冨Δ鍛櫜閹煎瓨绻勯幐澶愭⒑鐞涒€充壕婵炲濮撮鍡涙偂閻斿吋鐓欓柤鍓插墮婵¤姤绻涢崨顓熷櫣闂囧绻濇繝鍌涘櫣濞存粌澧界槐鎺旂磼濡偐鐣甸梺宕囩帛閹瑰洤鐣疯ぐ鎺濇晩闁伙絽濂旈柇顖炴⒒閸屾瑧鍔嶉悗绗涘厾楦跨疀濞戞锛欏┑鐘绘涧椤戝洤鐣垫笟鈧弻鈥愁吋鎼粹€冲闂佽桨绀侀崯鎾蓟閵娾晛鍗虫俊銈傚亾濞存粓绠栧铏圭磼濡闉嶇紓浣筋嚙閻楁捇鎮伴鈧浠嬧€栭妷銉╁弰妞ゃ垺顨婇崺鈧い鎺嶆缁诲棝鏌ゅù瀣珖缁炬儳銈搁弻锝呂熼幐搴ｅ涧闂佹眹鍔嶉崹鍧楀蓟閻旂厧绠甸柟鐑樻尭閺嗗牓姊虹拠鈥崇仭婵☆偄鍟穱濠囧箹娴ｈ娅囬梺閫炲苯澧撮柛鈹惧亾濡炪倖宸婚崑鎾愁熆瑜嶉柊锝夊春閳ь剚銇勯幒鍡椾壕缂備胶濮寸粔鐟扮暦閺囥垺鐒肩€规挶鍎卞ú锔锯偓闈涖偢瀵爼骞嬮悩鎻掔疄闂傚倷鑳堕、濠囧箵椤忓棛涓嶉柟瀵稿Х濡垳鎲搁弮鍫濊摕闁挎繂顦粻娑欍亜閹捐泛鏋旂紒瀣搐椤啴濡堕崘銊ュ濡炪倖鍨靛Λ婵囦繆閻㈢绀嬫い鏍ㄧ⊕濞呭棝姊洪崗鑲┿偞闁哄懏绻堝鎶藉Χ婢跺鎷洪梺鍛婄箓鐎氼厼锕㈤悧鍫㈢闁肩⒈鍓欓弸搴ㄦ煟閿濆鏁辩紒铏规櫕缁瑥鈻庨悙顒傜П闂傚倷绀侀崯鍧楀箹椤愶箑鐤い鎰剁稻閸欏繐鈹戦崒姘暈闁?",
            "principle": "",
            "concept_teaching": "",
            "review": "",
            "plan": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎娆戠┛闂傚倷绶氶埀顒傚仜閼活垱鏅堕崜褏纾奸柣妯挎珪鐏忣參鏌ｉ敐澶嬫暠缂佽櫣鏅划娆忊枎閻愵剛绉遍梻鍌欒兌閸嬨劑宕曢柆宥呯柈閻犳亽鍔忔慨鎶芥煏婢跺棙娅嗛柍閿嬪笒闇夐柨婵嗘川閹藉倹绻涢崗鐓庡妞ゎ厼娼￠幃鐑芥偋閸偅锛侀梻浣告惈閹虫挸鈻斿☉婊呬簷闂備礁鎲℃笟妤呭储妤ｅ啯鏅繛鎴欏灪閻撶喖骞栭幖顓炵仯缂佸鏁婚弻娑㈡偐閹颁焦鐤侀梺璇″枓閳ь剚鏋奸弸搴ㄦ煙閹屽殶闁告鏁婚弻锝夋偄閸濄儲鍣ч柣搴㈠嚬閸撴岸骞堥妸鈺傛櫇闁稿本绋撻崢閬嶆⒑闂堟稓澧曟俊顐ｇ洴楠炲﹪宕ㄩ婊咃紲闁哄鐗勯崝宥囦焊娴煎瓨鐓欑€瑰嫮澧楅崵鍥┾偓瑙勬穿缁叉儳顕ラ崟顓涘亾閿濆骸澧紓宥呭暣濮婂宕掑▎鎴М闂佸湱鈷堥崑鍡涘箖椤曗偓椤㈡洟鏁冮埀顒傜矆婢跺备鍋撻崗澶婁壕闂佸憡娲﹂崑鍡涘储閹绢喗鈷戠痪顓炴噺瑜把呯磼閻樺啿鐏撮柣娑卞櫍婵偓闁炽儴灏欑粻姘渻閵堝棛澧瑙勬礋楠炲繘鍩勯崘褏绠氶梺鍛婄懃椤︿即濡靛┑鍥ㄥ弿濠电姴瀚敮娑㈡煙瀹勭増鍣虹紒妤冨枛椤㈡稑顭ㄩ崘銊愵亜鈹戦敍鍕杭闁稿﹥鐗犲畷褰掓濞磋櫕绋戦埞鎴犫偓锝庡墮缁侊箓姊鸿ぐ鎺戜喊闁告ê缍婂畷鎴﹀川鐎涙鍘遍梺瑙勫閺呮稒淇婇崸妤佺厽闁靛牆鎳忛崵鍥ㄦ叏婵犲啯銇濈€规洜鍏橀、姗€鍩勯崘閿亾濡ゅ懏鈷戦柛婵勫劚鏍￠梺缁橆殕缁酣宕氶幒妤€閱囬柍鍨涙櫅娴滈箖鏌ㄥ┑鍡涱€楀ù婊勭墪闇夋繝濠傚閻帡鏌″畝瀣瘈鐎规洘锕㈡俊鎼佸Ψ閵忕姳澹曢梺姹囧灮椤牏绮婚鐐寸厓闁宠桨绀侀弳鏇犵磼鐠囧弶顥為柕鍥у楠炲洭鍩℃担鎻掍壕闁哄洢鍨归崙鐘绘煛閸愩劌鈧崵澹曟總绋跨骇闁割偅绋戞俊鐣屸偓瑙勬礀閻ジ鍩€椤掑喚娼愭繛鍙夘焽閺侇噣骞掑Δ瀣◤濠电娀娼ч鎰板极閸曨垱鐓㈡俊顖欒濡插嘲顭跨憴鍕婵﹥妞藉畷銊︾節閸曨厾绐楅梻浣侯焾鐎涒晜绻涙繝鍥х畾鐎光偓閸曨偆顔掔紓鍌欑劍椤洭宕㈤悽鐢电＝闁稿本鐟╁鐑芥煕閵娧勫殌闁宠绉撮～婊堝焵椤掑嫬钃熼柍鈺佸暞婵绱掔€ｎ偒鍎ュù鐘靛帶椤啴濡舵惔鈥崇哗濠电偛顦板ú鐔肩嵁閹达箑绀嬫い鏍ㄧ☉娴犲繘姊洪崫鍕垫Ч闁搞劎鏁婚敐鐐烘偐缂佹ǚ鎷绘繛杈剧到閹诧繝骞嗛崼鐔剁箚妞ゆ劧绲剧亸锔芥叏婵犱胶鐭欑€规洜鍠栭、姗€鎮㈠畡鎵搸濠电姷鏁告繛鈧繛浣冲厾娲Ω瑜嶆慨顒勬煃瑜滈崜鐔奉潖閾忓湱鐭欓柟绋垮閹疯京绱掗悙顒佺凡缂佸缍婇獮鍐潨閳ь剟鐛Ο鑲╃＜婵☆垶鏀辩€氬ジ姊绘担鍛婂暈缂佸鍨块弫鍐Ω閿斿墽褰惧┑鈽嗗灡閻绂嶅鍫熺厵閻庢稒顭囩粻鏍煕閵堝懏鍠橀柡灞界Ч婵＄兘顢涘鍏煎枠闂備礁婀遍幊鎾垛偓姘卞娣囧﹪骞栨担瑙勬珖闂侀€炲苯澧板瑙勬礋椤㈡稑鈽夊槌栧晭闂備礁婀遍崑鎾愁焽濞嗘挸鍚规い鎺戝閻撴洟鏌曟繛鍨偓鏇炵暤閸℃瑢鍋撶憴鍕缂侇喗鎹囬妴浣肝旈崨顓狀槹濡炪倖鍨兼慨銈団偓姘偢濮婄粯鎷呴崨濠傛殘缂備浇顕ч崐濠氬焵椤掍焦鐨戦柛蹇斆悾鐑藉即閿涘嫮鏉搁梺鍝勫€告晶鐣岀不濮橆剦娓婚柕鍫濇婵呯磽瀹ュ懏顥滈柍缁樻尭椤劑宕奸悢鍝勫箞闂備礁鍟块幖顐﹀疮椤愶絿顩烽弶鍫厛濞堜粙鏌ｉ幇顒佲枙闁稿孩妫冮弻鈩冩媴缁嬪簱鍋撻崸妤€绠板┑鐘插暙缁剁偤鏌涢埄鍐︿沪濠㈣娲熷铏圭磼濡櫣浼囨繝娈垮枔閸婃繈骞冮敓鐘冲亹闁汇垹鐏氶敍蹇涙⒑閸濆嫷妲搁柣蹇旂箞閹虫粓鎮烽柇锔惧數閻熸粍绮撳畷鎶芥晲婢跺﹨鎽曢悗骞垮劚椤︿粙寮崒鐐寸厱妞ゆ劑鍊曢弸鎴︽⒑濞嗘儳寮慨濠呮閳ь剙婀辨刊顓烆焽閹扮増鐓曢柕濞垮劜閸嬨儲顨ラ悙鎻掓殭闁宠閰ｉ獮妯虹暦閸ヮ剛宕滈梻鍌欑婢瑰﹪鎮￠崼銉ョ獥婵﹩鍏橀弸鏃堟煕椤愶絾绀冮柍閿嬪笒闇夐柨婵嗙墱濞兼劙鏌涚€ｎ剙鈻堥柡灞剧⊕閹棃濮€閵忋垻鍘滈柣搴ゎ潐濞叉粓宕伴弽顓溾偓浣肝熺悰鈩冾潔濠碘槅鍨抽幊鎾凰夊顓濈箚闁绘劦浜滈埀顒佺墪椤斿繑绻濆顒傦紱闂佸湱鍋撻悾顏呯濠婂嫨浜滈煫鍥ㄦ尭椤忊晠鏌￠崱顓犲埌闁宠鍨块崹鎯х暦閸パ呭幗闁诲氦顫夊ú鏍х暦椤掑啰浜介梻鍌欑閻忔繈顢栭崨鎼晜婵炲樊浜濋埛鎺楁煕鐏炲墽鎳呮い锔肩畵閺岀喓鍠婇崡鐐板枈濡ょ姷鍋涚换鎺楀焵椤掑﹦绉甸柛鐘崇墱婢规洜鎷犲ù瀣杸闂佺粯锚瀵爼骞栭幇鐗堢厸闁告洍鏅涢崝锕傛煛鐏炵偓绀夌紒鐘崇〒閳ь剨缍嗘禍鏍磻閹捐鍗抽柣姗€娼ч弳妤呮倵楠炲灝鍔氭い锔垮嵆閹繝寮撮悢缈犵盎闂佽澹嬮弲娑㈠焵椤掍焦绀嬬€殿喗鎮傚顕€宕奸悢鍝勫箞婵犵妲呴崹宕囧垝椤栨氨鏆︾€光偓閸曨剛鍘靛銈嗘⒒閸樠兾ｇ紒妯镐簻妞ゆ挻绮屾慨鍌溾偓瑙勬礈閸犳牠銆佸鈧幃鈺呮濞戞绶熼梻鍌欐祰椤曆冾潩閿曞偊缍栧璺衡姇閸濆嫀鐔兼偂鎼达紕浜伴梻浣筋潐瀹曟﹢顢氳缁寮介鐔哄帾闂婎偄娲ら鍛村焵椤掍胶澧电€规洘鍨垮畷鎺楁倷閼碱剦鍟囬梺鍝勵槸閻楀棙鏅舵禒瀣畺濠靛倸鎲￠悡娑㈡煕閳╁啯绀€鐎规挸妫欓幈銊︾節閸曨厼绗￠梺鐟板槻閹虫ê鐣烽妸锔剧瘈闁稿本绋掗悾鐓庘攽閻樺灚鏆╅柛瀣█椤㈡艾顭ㄩ崨顖欑瑝闂佽鍎崇壕顓㈠汲閿曞倹鍋℃繛鍡楃箰椤忣偊姊婚崟顐㈩伀缂佽鲸甯為埀顒婄秵閸嬪嫰顢氬鍫熺厽閹兼惌鍠栨晶顖滅磼缂佹绠為柟顔荤矙濡啫霉闊彃鐏紒缁樼〒閹风姾顦撮柣锝囨暬閺岀喖顢氶崱娆戠槇闂佽鍠撻崹钘夌暦濡ゅ懏鍤冮柍杞扮濮规彃鈹戦悩鍨毄濠电偐鍋撳┑鐐板尃閸忕偓绋戦埢搴ㄥ箻閸愬弶鍎梻渚€鈧偛鑻晶鎾煛瀹€瀣ɑ闁诡垱妫冩慨鈧柕蹇嬪灩瑜板酣姊绘担鍛婂暈妞ゃ劌妫欑换娑欑節閸屻倕娈ㄦ繝鐢靛У绾板秹寮查弻銉︾厱妞ゆ劗濮撮悘顕€鏌℃径宀婄劸闁宠鍨块幃娆撳级閹寸姳妗撴俊鐐€戦崝灞轿涘┑鍡欐殾闁哄顑欏鈺傘亜閹达絽袚闁哄倵鍋撳┑锛勫亼閸婃牕顫忔繝姘ラ悗锝庡枛缂佲晝绱撴担濮戣偐鎹㈤崱娑欑厽闁归偊鍘奸ˉ瀣煟椤撶喓鎳囬柡宀嬬到閳藉宕￠悙瀵稿綆婵°倗濮烽崑娑樏洪顫偓浣割潨閳ь剟骞冮姀鐘垫殝闁哄顕抽妶澶嬧拻闁稿本鐟ч崝宥夋倵缁楁稑鎳忓畷鏌ユ煕瀹€鈧崑娑氬閸︻厽鍠愰柣妤€鐗嗛柌婊呯磽瀹ュ棛澧遍柍褜鍓欑粻宥夊磿闁单鍥ㄥ閺夋垹鍘遍梺鍦劋閸ゆ俺銇愰幒鎾存珳闂佹悶鍎辨晶搴ㄥ礉閹间焦鈷戦悹鍥ｂ偓铏亶闂佹悶鍔忛崺鏍矚鏉堛劎绡€闁搞儯鍔岄埀顒傚厴閺屾稑鈻庤箛锝喰︽繛瀵稿У閹告娊骞冨Δ鍐╁枂闁告洦鍓涢ˇ銉モ攽閻橆偄浜鹃梻渚囧墮缁夊绮婚弻銉︾厱闁哄洢鍔岄悘锟犳煙椤栨粌浠遍柟顔煎槻閳诲氦绠涢幙鍐х棯婵＄偑鍊栧鐟懊哄Ο鑽も攳濠电姴娲﹂崐閿嬨亜韫囨挸顏ら柛瀣崌瀵粙顢橀悢铚傜綍婵犵數濮撮敃銈夋偋閸℃瑥顥氱紓浣诡焽缁犻箖鏌熺€涙鎳冮柣蹇ｄ邯閺屾稒绻濋崒娑樹淮闂佸搫鏈惄顖炲灳閿曞倸绠ｆ繝闈涙噽閹稿鈹戦悙鑼憼缂侇喖绉堕崚鎺楀箻鐠囪尪鎽曢梺缁樻煥閸氬宕愮紒妯圭箚妞ゆ牗绻冮鐘裁归悩铏稇妞ゎ亜鍟存俊鍫曞川椤旂虎娲跺┑鐐茬摠缁姵绂嶉鍕靛殨濠电姵纰嶉弲鎻掝熆鐠虹尨鍔熸い鏃€甯￠弻锝嗘償閵婏附閿梺纭咁嚋缁绘繂鐣烽搹顐㈩嚤閻庢稒菤閹锋椽鏌ｉ悩鍙夌闁逞屽墲濞呮洟鎮橀崼銏㈢＝闁稿本姘ㄥ瓭闂佹寧娲︽禍顏堟偘椤曗偓瀵粙顢栭崣銉︾潖闂備礁婀遍崕銈夊箰閸涘﹦顩锋い鎾卞灪閳锋垿鎮峰▎蹇擃伌闁哥喎绻橀弻娑㈡偐閹颁焦鐤佸銈冨灪椤洨妲愰幒鎳崇喖鎳栭埡鍐╊潓濠电姷鏁搁崑娑㈡偋閸℃稒鍊舵繝闈涱儏閸戠姵绻涢幋娆忕仾闁绘挶鍎甸弻锟犲炊椤浜畷婵嬫晝閸屾稓鍘梺绯曞墲椤ㄥ懘寮抽敐鍥ｅ亾鐟欏嫭绀€闁靛牆鎲￠幈銊╁焵椤掑嫭鐓冮柦妯侯槹椤ョ偟绱撳鍡╂疁婵﹦绮幏鍛村川婵犲懐顢呴梻浣侯焾缁ㄦ椽宕愬┑瀣ラ柛鎰靛幘閻も偓濠电偞鍨惰摫闁诲寒鍓氱换婵嬫偨闂堟刀銏＄箾鐠囇呯暤闁诡噯绻濋幃銏ゅ礂閼测晛寮虫繝鐢靛█濞佳兾涘▎鎾冲惞闁逞屽墴閺岋絾鎯旈姀锛勬婵犫拃鍕垫疁濠碉紕鏁诲畷鐔碱敍閿濆棙娅囬梺纭呭亹鐞涖儵宕滃┑鍥х窞闁告洦鍨遍悡鏇炩攽閻樻彃顏柡鍡╁墴閺岋紕浠﹂崜褎鍒涢梺鐐藉劵缁犳捇鐛€ｎ亖鏀介柛娑卞灠閸ゎ剛绱撻崒姘偓宄懊归崶顒€鏄ラ柡宥庡幗閸嬪倿鏌ㄩ悢鍝勑㈢紒鐘崇墬娣囧﹪濡堕崒姘婵＄偑鍊ら崑鍛崲閸儯鈧線寮撮姀鐙€娼婇梺缁橆焽閸嬶綁宕戦弽顓熲拺閻犲洤寮堕崬澶嬨亜椤愩埄妲搁悡銈嗕繆椤栨瑨顒熸繛鎾诡嚙闇夐柣妯烘▕閸庡繘鏌＄€ｂ晝绐旈柡宀€鍠栧畷婊嗩槾閻㈩垱鐩弻娑氣偓锝庡亜婵秹鏌＄仦璇测偓妤呭窗婵犲洤纭€闁绘劖绁撮幏缁樼節瀵版灚鍊曠槐锕傛煕濡も偓閸熷潡锝炶箛鏇犵＜婵☆垵顕ч鎾剁磽娴ｅ壊鍎愰悗绗涘唭鎺楀箛閻楀牃鎷洪梺闈╁瘜閸樻悂骞忛敓鐘崇厱閻庯綆浜峰銉╂煟閿濆洤鍘存い銏＄洴閹粓宕卞Ο缁樼彨濠电姵顔栭崰妤呮晝椤愩倕绶ゅΔ锝呭暞閸婅泛銆掑锝呬壕濠殿喖锕紓姘跺Φ閹版澘绠抽柟鍨閸氬綊姊绘担铏瑰笡閻㈩垼浜炵划濠氬箻鐠囧弶妲┑鐐村灟閸ㄥ湱绮婚幎鑺ョ厵闁绘劘妫勬俊鑲╃磽瀹ュ拑韬€殿噮鍋婇獮鍥级閸喚鐛╂俊鐐€栭弻銊╁触鐎ｎ亖鏋旀慨妞诲亾婵﹦绮幏鍛村川婵犲啫鏋戦梻浣告憸婵敻骞戦崶褏鏆﹂柟杈剧畱鍥存繝銏ｆ硾閿曘劑骞楅弴銏♀拺闁绘劘妫勯崝姘辩棯缂併垹寮€殿喗濞婂畷鍗炩槈濞嗗繆鍋撻悽鍛婄叆婵犻潧妫濋妤€顭胯婢瑰棝骞冮鈧弫鍐磼濞戞艾骞楅梺鐟板悑閻ｎ亪宕愰妶鍜佺劷闁归偊鍘剧粻楣冩煕濞嗗浚妯堥柣鎺嶇矙閺岀喖鐛崹顔句紙閻庤娲滈崰鏍€佸☉姗嗘僵闁告鍋涜婵犵绱曢崑鎴﹀磹閺嶎偅鏆滈柟鐑橆殕閺呮繈鏌ㄩ弬鍨挃闁活厽鎹囬弻锝夊閻樺啿鏆堥梺缁樻尰濞茬喖寮婚悢鐓庣畾鐟滄粓宕甸悢鍏肩厪闁糕剝锚缁椦呯磼鏉堛劌娴い銏＄懇閹虫牠鍩℃笟鍥ㄦ緫缂傚倸鍊烽懗鍓佸垝椤栨粍宕查柛顐ｇ箘閺嗭箓鏌涢锝嗙閹喖鎮峰鍐ч柣娑卞櫍楠炲洭鎮ч崼姘濠电偠鎻徊浠嬪箟閿熺姴鐤柣鎰劋閻撴洟鏌￠崘锝呬壕闂佹悶鍔岄悘婵嬫偩瀹勬壋鏀介柛銉ｅ妼閸斿懘姊洪棃娑氱畾闁告挻绻堥幃鐢告倻閼恒儮鎷洪梺鍛婄箓鐎氼參宕掗妸鈺傜厱闁靛闄勯妵婵嬫煙椤曞棛绡€鐎殿喗鎸虫慨鈧柍銉︽灱閸嬫捇宕奸弴鐔哄幗闂侀€涘嵆閸嬪﹪寮跺ú顏呯厱闁靛牆妫涢幊鍐煃鐟欏嫬鐏存い銏＄懇閹剝鎯斿Ο杞板闂佺鍕垫當闁藉啰鍠栭弻锝夊籍閸屾瀚涢梺杞扮閿曪妇妲愰幒鎴旀婵妫楅崜閬嶆⒑濮瑰洤鈧挾娆㈠顒夋綎闁绘垶蓱婵粓鏌熷▓鍨灈濠碘€茬矙濮婃椽宕ㄦ繝鍐ｆ嫻闂佺粯顨堟繛鈧柣娑卞櫍瀹曞崬鈽夊Ο鑲╂綁闂備礁澹婇崑鍛崲閸曨剙顕遍悗锝庡枟閳锋垹鎲搁悧鍫濅刊闁哄棙甯￠弻锝夊箳閻愮儤顎嶅銈冨妸閸庨潧鐣烽悢纰辨晣闁绘顣槐鎶芥⒒娴ｄ警鐒鹃柡鍫墴閹虫繃銈ｉ崘銊у姦濡炪倖宸婚崑鎾绘煕閵忥紕鍙€婵犫偓娓氣偓濮婃椽骞栭悙鎻掑闂佸憡鏌ㄩ敃銉х矉閹烘閱囬柕蹇嬪灮閿涙粓鏌ｆ惔顖滅У闁告鏅☉鐢稿醇閺囩喓鍘搁梺绯曞墲椤ㄥ棝藟閵忋倖鐓涚€光偓閳ь剟宕伴弽褜娼栭柤濮愬€愰崑鎾绘濞戞﹩妫屽┑鈥虫▕閸ｏ絽顫忓ú顏呭癄濠㈣泛锕ュ▓鍫曟⒑閸濄儱校闁告梹顨婇獮鎴﹀閻橆偅顫嶉梺闈涚箳婵兘顢橀崫鍕ㄦ斀闁绘劕寮堕ˉ婊呯磼缂佹ê绗氱紒鍌涘浮閹虫牠鍩￠崘顏庣闯濠电偠鎻徊浠嬪箹椤愶妇鈧攱绻濋悽闈涗粶闁瑰啿绻愮叅婵☆垵鍋愰惌姘跺级閸稑濡跨紒鈾€鍋撻梻浣规偠閸庢椽鎮樺☉婊庢▌闂佸搫鏈粙鎴︹€﹂妸鈺佺闁靛闄勯澶愭⒒娴ｈ姤銆冮柣鎺炵畵瀹曟洟骞庨挊澶屽幋闂佺鎻梽鍕磹閻戣姤鐓犵痪鏉垮船婢ь喗銇勯敐鍛煟婵﹨娅ｇ划娆撳锤濡ゅň鍋撳Δ鍐／缂備降鍨归獮鏍础闁秵鐓欓柣妤€鐗婄欢鑼磼閻樺樊鐓奸柟顔筋殔閳藉鈻嶉褌閭い銏℃崌楠炴绱掑Ο鐓庡箺闂備胶绮弻銊╁箺濠婂牆绠犻柛鎰靛枟閸婂灚鎱ㄥΟ鐓庡付婵炲懎绉堕埀顒冾潐濞测晝绱炴担鍝ユ殾闁告鍋愬Σ鍫熺箾閸℃婀伴悗姘偢濮婅櫣鎷犻崣澶嬪闯濠电偛鎳岄崹钘夘潖娴犲绀嬫い鎰靛亞閸為潧鈹戦埥鍡楃仴妞ゆ柨锕﹂幑銏ゅ幢濞戞瑥浠梺璇″幗鐢帗淇婄捄銊ф／闁诡垎鍐╁€梺闈涙搐鐎氭澘顕ｉ鈧畷鎺戔槈濞嗘垵娑ч梻鍌欒兌閹虫捇宕捄銊㈠亾濮樼厧娅嶉柛鈹惧亾濡炪倖宸婚崑鎾绘煟韫囨棁澹樻い顓炵仢铻ｉ悘蹇旂墪娴滅偓鎱ㄥ鍡椾簻鐎规挸妫濋弻锝呪槈閸楃偞鐝濋悗瑙勬礀閻栧ジ銆佸Δ鍛劦妞ゆ帒瀚崹鍌炴煕鐏炲墽鈼ゅù婊勭矒閺岀喖寮堕崹顕呮殺缂備礁顑呴…鐑藉蓟閿濆應鏀介柛銉ｅ妿椤︽澘鈹戦纭峰伐妞ゎ厼鍢查悾鐑藉箳閹存梹鐎婚梺鐟扮摠缁诲倿鈥栨径鎰拻濞达絿鐡旈崵鍐煕閻樺磭澧甸柟顔哄劦閹剝鎯旈敐鍡橆啎闂備礁鎼ú銊╁磿閹扮増鍋傞柕澶嗘櫆閻撴洘銇勯幇鍓佹偧缂佺姵蓱閵囧嫰鏁傞崫鍕潎濠殿喖锕ュ钘壩涢崘顭嬪綊濡堕崱娆嶁偓鎺懨归悪鍛暤闁瑰磭鍋ゆ俊鐑藉Ψ閵忕姳澹曞┑鐐村灟閸ㄦ椽鍩涢幒妤佺厱閻忕偞宕樻竟姗€鏌嶈閸撴岸骞冮崒姘辨殾闁圭増婢樼粻鐟懊归敐鍛喐闁挎稒鐟╅幃妤呮偡閺夋浠鹃梺闈╃悼椤ユ劙濡甸幇鏉跨闁瑰濮撮埀顒傚仜椤啴濡堕崱妤€娼戦梺绋款儐閹歌顭囩拠娴嬫斀閻庯綆鍋€閹锋椽姊绘笟鍥т簽闁稿鐩幊鐔碱敍濞戞瑦鐝烽梺鍦檸閸犳鎮″☉銏″€堕柣鎰絻閳锋棃鏌曢崱妯烘诞闁哄苯绉烽¨渚€鏌涢幘鍗炲缂佽京鍋ゅ畷鍗炩槈濡》绱遍梻浣告啞娓氭宕㈡ィ鍐ㄦ辈闁挎棃鏁崑鎾诲礂婢跺﹣澹曢梻浣告啞濞诧箓宕滃☉銏犲偍闂傚牊渚楀〒濠氭煏閸繃顥為柍閿嬪姈閵囧嫰骞嬮悙鍨櫑濡炪値鍘煎ú顓㈢嵁閸ヮ剚鍋嬮柛顐犲灩鐢箖姊绘担绋款棌闁稿甯″畷婊冣槈閵忊€充患闂佸壊鐓堥崑鎺戔枔娴犲鐓熼柟閭﹀幗缂嶆垵鈹戦鑲╁ⅵ闁哄瞼鍠栭、娑樷槈濞嗘ɑ顥堟俊鐐€戦崹娲偡瑜旈獮蹇涙偐鐠囪尙鐓戞繝銏ｆ硾椤戝懘寮虫径鎰拻闁稿本鑹鹃埀顒佹倐瀹曟劙骞栨担鍝ワ紮婵＄偛顑呭ù鐑芥儗閸℃ぜ鈧帒顫濋敐鍛婵°倗濮烽崑鐐恒€冮崨绮光偓锕傚Ω閳轰線鍞跺┑鐘绘涧閻楀繐鐣烽崼鏇熲拻濞达絿鐡斿鎰熆閻熺増顥為柡鍛版硾铻栭柛娑卞幘閿涙盯姊虹粙璺ㄧ伇闁稿鍋ら幃锟犲Ψ閳哄倻鍘介梺鍝勫€圭€笛囧箚閸懇鍋撳☉娆戠疄婵﹥妞介幐濠冨緞婵犲啯顔嶉梻浣告憸婵敻鎮ч悩宸殨濠电姵鑹炬儫闂侀潧顦崹娲棘閳ь剟姊绘担铏广€婃俊鐙欏洤鐤炬繝濠傛噽閹冲懘姊婚崒娆愮グ妞ゆ洘鐗犲畷褰掑箮閽樺鐛ラ梺鍝勮癁鐏炲墽绋佹繝鐢靛仜濡﹥绂嶅┑瀣庡宕奸悢铏诡啎闂佺鎻紞渚€宕ú顏呭殐闁哄稁鍘介埛鎺懨归敐鍕劅闁绘帞鍋撶换娑氣偓鐢殿焾閸樺鈧娲樺ú鐔镐繆閸洖鐐婇柍鍝勫暟閸斿綊姊绘担鍛婅础闁稿簺鍊濋獮鎰偅閸愨斁鎸冮梺鍛婃处閸ㄩ亶鎮￠弴鐔虹闁瑰鍋愬Σ鍫ユ煕椤愮姴鍔氱紒鐙€鍨堕弻娑樷攽閸℃浠遍梺琛″亾濞寸姴顑嗛悡鐔兼煙闁箑鐏＄痪顓㈢畺閺岋箓宕熼闂存睏闂侀€炲苯澧叉い顐㈩槸鐓ゆ繝濠傜墕閺嬩線鎮归崶顏勭毢闁哄棴绠撻弻鏇＄疀閺囩倫娑欎繆閹绘帞澧﹂柡灞炬礉缁犳盯濡疯閿涚喖姊洪崨濠忚€垮ù婊嗘硾椤繘鎼圭憴鍕瀭闂佸憡娲﹂崑鍡浰囬妸銉㈡斀闁绘劕妯婂Σ褰掓煟閳哄﹤鐏犳い鏇秮瀹曘劍绻濋崘銊ュΤ婵＄偑鍊ら崑鎺楀礂濞戞俺濮抽悹鍥ф▕濞撳鏌曢崼婵囶棞濠殿喖鍊块弻娑㈠Ω閵娿儱鎯炵紓渚囧枛椤兘骞婇悩娲绘晢闁稿本绮ｇ槐鑼磽閸屾艾鈧兘鎮為敃鍌椻偓锕傚炊閳哄啩绗夐梺鍦亾閻ｎ亝绂嶅鍕╀簻闁规澘澧庨幃鑲╃磼閻橀潧浠ч柍褜鍓濋～澶娒哄鈧妴鍐╃節閸屾粍娈惧┑掳鍊曢幊搴ｇ矆閸岀偞鐓犳繛鏉戭儐濞呭懐绱撳鍛棦婵﹤顭峰畷鎺戭潩椤戣棄浜鹃柟闂寸绾惧綊鏌ｉ幋锝呅撻柛銈呭閺屾盯骞橀懠顒夋М闂佹悶鍔嶇换鍐Φ閸曨垰鍐€妞ゆ劦婢€濮规姊洪柅鐐茶嫰婢у墽绱掗悩铏碍闁伙綁鏀辩缓浠嬫閳哄啰鈼ゆ俊鐐€栭幐鐐叏鐎涙ɑ娅犻柣鎰靛墰缁♀偓闂佹眹鍨藉褎绂掑鍕箚妞ゆ劧绲块幊鍥殽閻愭潙濮堢紒缁樼箓椤繈顢楅崒锔惧耿?",
            "task": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎娆戠┛闂傚倷绶氶埀顒傚仜閼活垱鏅堕崜褏纾奸柣妯挎珪鐏忣參鏌ｉ敐澶嬫暠缂佽櫣鏅划娆忊枎閻愵剛绉遍梻鍌欒兌閸嬨劑宕曢柆宥呯柈閻犳亽鍔忔慨鎶芥煏婢跺棙娅嗛柍閿嬪笒闇夐柨婵嗘川閹藉倹绻涢崗鐓庡妞ゎ厼娼￠幃鐑芥偋閸偅锛侀梻浣告惈閹虫挸鈻斿☉婊呬簷闂備礁鎲℃笟妤呭储妤ｅ啯鏅繛鎴欏灪閻撶喖骞栭幖顓炵仯缂佸鏁婚弻娑㈡偐閹颁焦鐤侀梺璇″櫙缁绘繂顕ｉ幘顔碱潊闁挎稑瀚敮妤呮⒒娴ｅ摜鏋冩俊妞煎妿缁牊绗熼埀顒€顕ｉ幎鑺ュ亜闁稿繗鍋愰崢鎾愁渻閵堝棛澧紒瀣笧缁牏鈧綆鍠楅悡娑㈡倶閻愭彃鈷旈柕鍡樺浮閺屽秷顧侀柛鎾卞姂楠炩偓闁靛鏅涚粈瀣亜閹烘垵鈧摜寰婃ィ鍐┾拻闁稿本鐟х粣鏃€绻涙担鍐插幘濞差亜围闁搞儻绲芥禍鐐叏濮楀棗浜滅€规挸妫濋弻锝呪槈閸楃偞鐝濆Δ鐘靛仦鐢帟鐏冮梺閫炲苯澧扮紒顔碱煼閺佹劙宕卞▎鎴犳闂備礁澹婇悡鍫ュ磻閸曨剚鍙忛柛鎰靛枟閻撴瑦銇勯弴鐐搭棤闁诡喛鍋愮槐鎺撴綇閵婏箑纾抽悗瑙勬礃鐢帡鍩㈡惔銊ョ闁瑰瓨绻傞懙鎰節閻㈤潧校妞ゆ梹鐗犲畷瑙勫閹碱厽鏅銈嗘尵婵敻锝為弴銏＄厽闁归偊鍓﹂崵鐔兼煟閻旈绉洪柡灞界Х椤т線鏌涢幘瀵告噰妞ゃ垺宀搁弫鎰板幢濞嗘垹妲囨繝娈垮枟閿曗晠宕㈤崗鑲╊洸婵犲﹤鐗婇埛鎴犵磼鐎ｎ厽纭剁紒鐘虫そ閺屾稓鈧綆鍋勬慨宥団偓瑙勬礃缁诲牓骞冨鍫熷殟闁靛鍨虹€氬ジ姊绘担鍛婅础妞ゎ厼鐗忛埀顒佺▓閺呮繃绔熼弴銏″仺闁告稑锕﹂崢閬嶆煟鎼搭垳绉甸柛瀣噽娴滄悂鎮ч崼娑楃盎闂侀潧顭徊浠嬪礉閿曞倹鐓欐い鏃傛櫕閹冲洦顨ラ悙瀵稿⒌妞ゃ垺锕㈤幃銏ゆ倻濡椿鍟嶉梻鍌氬€搁崐鎼佸磹缁嬫５娲Χ婢癸箑娲幃鐣岀矙閼愁垱鎲伴梻浣瑰缁诲倿骞夊鈧幃銏ゅ传閸曨剛鈧娊姊洪崨濠庢畼闁稿鐩敐鐐差潩閼哥鎷绘繛杈剧悼椤牓骞冮幋鐐电瘈闁靛繆鍩楅鍫氣偓锕傚炊椤掍焦娅㈤梺缁橆焾鐏忣亪骞楅弴銏♀拺闁绘劘妫勯崝姘辩棯缂併垹寮€殿喗濞婂畷鍗炩槈濞嗗繆鍋撻悽鍛婄叆婵犻潧妫濋妤€顭胯閸楁娊寮婚敓鐘插耿闁归偊鍏橀崑鎾斥攽鐎ｎ亞鐣哄┑掳鍊愰崑鎾绘煃缂佹ɑ宕岀€规洖缍婇、娆撴偩鐏炲ジ鍋楅梻鍌氬€风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呰埖瀵肩€涙鍘遍梺鎸庣箓閸燁偊宕濆璺虹闂侇剙绉甸崑锝夋煕閵夋垵瀚ч弸娆忊攽閻愬瓨灏い顓犲厴瀵寮撮姀鐘诲敹濠电娀娼уú銈呪枍閵堝洨纾藉ù锝囶焾閳ь剚鎮傞、鏍ㄥ緞閹邦剝鎽曞┑鐐村灦閸╁啴宕戦幘缁樻櫜閹煎瓨绻勯崙褰掓⒑闂堚晝瀵肩紒顔界懇瀵鎮㈤懖鈺佺ウ闂佸壊鐓堥崰姘婵傚憡鈷戦悗鍦У椤ュ銇勯敃鈧悘姘跺箞閵娾晛鐒垫い鎺戝閻撶喐淇婇娑卞劌闁搞倖鐟╅弻鈩冩媴閸濄儳楔濠殿喖锕︾划顖炲箯閸涘瓨鎯為柣鐔稿椤愬吋绻濈喊妯活潑闁稿瀚板畷顖滃鐎ｎ偓绱撻梻鍌欐祰椤宕曢幎绛嬫晪妞ゆ搩娼块埀顒€鎳橀幃婊堟嚍閵壯冨箞婵犵數濞€濞佳呪偓姘煎墴瀹曟繈濡堕崶鈺傦紡闂佺顫夐崝鏍夋径鎰梿濠㈣埖鍔栭悡銉︾節闂堟稒顥為柛锝堫潐閵囧嫰濡烽妷褏顔掗梺鍝勬湰缁嬫帡骞嗛弮鍫熸櫖闁告洦鍙庨崬褰掓⒒娓氣偓濞佳兠洪妶鍥ｅ亾濮橆偄宓嗙€殿噮鍋婂畷鎺楁倷閺夋垟鍋撻柨瀣ㄤ簻闁瑰搫绉堕崝宥夋煟閿旇姤宕岄柡宀嬬稻閹棃濡舵惔銏㈢Х婵犵數鍋涘鍫曟晪濡炪値浜滈崯顖滅矉閹烘柡鍋撻敐搴濈凹婵″樊鍓熷娲焻閻愯尪瀚板褜鍨堕弻鏇㈠炊瑜嶉顓燁殽閻愭潙绗掓い鎾冲悑瀵板嫮鈧絿顣介崑鎾诲冀閵娧咁啎闁诲孩绋掗…鍥儗鐎ｎ剛纾兼い鏃囧Г瀹曞瞼鈧鍠栭…鐑藉箖閵忋倕绀傞柣鎾崇岸閸嬫挾绱掑Ο鍦畾濡炪倖鐗楃换鍐敂閻樿褰掓偐閾忣偄鍞夊┑顔硷攻濡炰粙寮婚崨瀛樺€烽柤鑹版硾椤忣厽绻濋埛鈧仦鑺ョ彎闂佸搫鏈惄顖涙叏閳ь剟鏌ㄥ☉妯侯仼鐎殿喓鍔戝铏瑰寲閺囩喐婢撻梺鎼炲姀濞咃絿鍒掔€ｎ喖绠抽柡鍌氭惈娴滈箖鏌ㄥ┑鍡樺櫧濞寸姵鐩弻锟犲川椤斿墽鐓夊┑顔硷攻濡炶棄鐣峰鍫濈闁瑰搫绉堕弫鏍⒒娴ｅ憡鎲稿┑顔炬暬楠炴垿宕惰閺嗭箓鏌曡箛瀣偓鏍倿閼测斁鍋撻獮鍨姎婵☆偅鐩畷銏＄鐎ｎ偒妫呭銈嗗姂閸ㄧ儤寰勯崟顒傜闁告瑥顦辨晶顒傜磼閸屾稑绗╂い锕€缍婇弻锛勪沪閸撗佲偓鎺楁煃瑜滈崜銊х礊閸℃稑纾婚柛娑卞幘閺嗭妇鈧厜鍋撻柛鏇ㄥ墰閸橀潧顪冮妶鍡欏闁煎綊绠栧鎶芥晲閸♀晜顔旈梺缁樺姇濡﹪宕曢弮鍫熺厸濞达絿顭堥埀顒€娼￠獮鍐礈瑜屽▽顏堟煢濡警妲烘い鏂挎搐閳规垿鎮╅崹顐ｆ瘎婵犳鍠曢崡鍐茬暦瑜版帗鍋傞幖瀛樕戦悘鍐ㄢ攽閻愭潙鐏嶉柟宕囧仱瀹曞爼顢楁担鍝勫Ц闁诲骸绠嶉崕鍗炍涘Δ鍛闁荤喐澹嬮弨浠嬫煟閹邦剙绾фい銉у仱閺岀喓绮欏▎鍓у悑闂佽鍠掗埀顒佹灱濡插牊鎱ㄥ鍫㈠埌濞存粓绠栭弻娑滅疀閹垮啯笑婵炲瓨绮撶粻鏍蓟閿濆棙鍎熸い鏍ㄧ矌鏍￠梻浣告啞閹稿鎮烽埡浣烘殾闁惧繘鈧稒鍕冪紓浣圭☉椤戝棛鈧潧鐭傚娲濞戞艾顣烘俊銈囧У閹倿鎮伴鈧獮瀣晜閻ｅ苯骞堥梻浣告惈閸熺娀宕戦幘缁樼厱闁靛ě鍕瘓闂佽鍠楅崕鎶芥偩閿熺姵鐒介柨鏃囨缂傛捇姊绘笟鈧埀顒傚仜閼活垱鏅堕姣插酣宕惰瀹搞儲銇勯鐘茬仼闁伙絾绻冪换婵嬪礃閸愭儳澧紒缁樼箞閹粙妫冨☉妤冩崟婵＄偑鍊х粻鎴﹀疮閸ф鐓濋柡鍐ㄧ墕閸楁娊鏌ｅΟ璇插婵炶偐鍠栧铏规喆閸曨偆顦ㄥ銈嗘肠閸涱収妫滈梺绋跨箺閸嬫劗绮绘ィ鍐╃厱闁斥晛鍘鹃鍛弿濠㈣埖鍔栭悡蹇涙煕椤愮姴鐏╂い锝囧帶鑿愰柛銉戝秷鍚梺璇″枟閻熝囧焵椤掍胶鈯曟い顓炴川缁瑩宕堕浣叉嫼缂佺虎鍘奸幊搴ゎ暱缂傚倷绶￠崰妤呭箲閸ヮ剚鍋樻い鏇楀亾妤犵偛顑夐弫鍐焵椤掑嫸缍栭柛娑樼摠閻撳繘鏌涢锝囩畺闁搞倕娲弻娑㈡倷閼哥數銆愰梺瀹狀潐閸ㄥ潡骞冮埡鍐＜婵☆垰顭烽弫顏堟⒒娴ｈ櫣甯涙い銊ユ嚇閺佸啴濡舵径濠勫幒闂佽宕橀褏绮诲杈ㄥ枑濠㈣埖鍔曠紒鈺伱归悩宸剱闁绘挸鍟撮弻锕€螣娓氼垱效濡炪們鍎茬划鎾诲蓟閿濆牏鐤€闁哄洨鍋為悘鍫ユ⒑鐠団€虫灈缂傚秴锕畷娲焵椤掍降浜滈柟鐑樺灥椤忣亪鏌￠崨顔剧疄闁哄本绋撴禒锕傚矗閵夈倕顒㈤柣鐐寸缁诲牆顫忛搹瑙勫珰闁圭粯甯掑В鎰磽閸屾氨孝婵☆偅鐟х划瀣吋婢跺﹪鍞堕梺鍝勬川閸犲孩绂嶅鍫熲拺缂侇垱娲栨晶鑼磼鐎ｎ偄娴€规洘鍨块弫鎰緞鐎ｎ剙寮伴梻濠庡亜濞诧箑煤濮椻偓瀹曠敻鍩€椤掑嫭鈷戦柛娑橈攻閻撱儲銇勯幋婵囶棦濠碉紕鏁诲畷鐔碱敍濮ｇ鍔庨幉绋款吋閸℃瑯娴勯梻渚囧墮缁夌敻鎮″☉銏″€堕柣鎰問閻掓儳顭胯閻擄繝寮婚悢椋庢殝闁绘鐗嗗▓妤呮倵鐟欏嫭绌跨紒鍙夊劤椤曘儵宕熼娑樹壕闁挎繂楠告晶顔剧磼閹绘帒鈷旂紒杈ㄦ崌瀹曟帒顫濋钘変壕闁绘垼濮ら崵鍕煕閹捐尙顦﹂柛銊︾箖閵囧嫰寮介顫勃闂佺楠哥€涒晠濡甸崟顖氬唨妞ゆ劦婢€閹寸兘鎮楃憴鍕矮缂佽埖宀搁獮鍐ㄎ旈崨顔芥珳闁硅偐琛ラ崜婵嬫倶瀹ュ鈷戠紒瀣皡閸旂喖鏌涜箛鏃撹€跨€殿喖顭烽崺鍕礃閵娧呯嵁闂佽鍑界紞鍡樼閻愬顩烽柣鎾冲瘨濞撳鏌曢崼婵堢缂佸顭烽弻锝夊箻椤栨浜鹃柟棰佺劍缂嶅海绱撻崒娆戝妽閽冨崬鈹戦娑欏唉闁哄矉缍侀幃銏ゆ偂鎼存繂鏋堥梻浣规偠閸婃洟顢栭崨鏉戠厴闁硅揪闄勯崐宄拔涢悧鍫㈢畵婵炲牊绻堝濠氬磼濮橆剦浠奸柣搴㈠嚬閸犳岸宕氶幒鏂哄亾閿濆簼鎲鹃柛姘儏椤潡鎳滈惉顏呭灴瀵彃顭ㄩ崼鐔叉嫼闂佸憡鎸昏ぐ鍐╃濠靛牏纾奸悹鍥ㄥ絻椤忣參鏌熼钘夊姢閻撱倖銇勮箛鎾村櫝闁归攱妞藉娲川婵犲嫮鐣甸柣搴㈣壘閸㈡彃宓勯梺鍛婄缚閸庡磭澹曟總鍛婄厪濠电偟鍋撳▍鍐煙閹绘帒鈷旈柍褜鍓氶鏍窗閺嶎厼绠熼柨鐔哄Т缁犳岸鏌￠崘銊у閹喖姊洪幐搴⑩拹闁稿孩濞婇悰顔碱吋婢跺鎷洪柣鐘叉搐瀵爼骞戦敐澶嬬厸濞达綀顫夐崐鎰版煃閵夘垳鐣电€规洖銈搁幃銏＄瑹椤栨稓銈┑鐘垫暩婵挳鏁冮妶澶嬪亱濠电姴娲﹂崑鍌炴煟閺傛寧鎲哥紒鈾€鍋撻梻鍌氬€搁悧濠勭矙閹惧瓨娅犻柡鍥╁枂娴滄粓鏌ㄥ┑鍡欏濞存粌婀辩槐鎺撴綇閵娿儳顑傜紓浣介哺鐢帟鐏掗柣蹇撶箲閻楁洟锝炵仦鍓х瘈闁汇垽娼ф禒褔鏌涘Ο鐘叉噺瀹曞弶淇婇婵囶仩闁哄棴闄勭换婵囩節閸屾冻绱炲┑鈩冪叀缁犳牠骞冪捄渚僵闁告挆鍚锋垶绻涢敐鍛悙闁挎洦浜獮鍐ㄢ枎閹垮啯鏅滈梺鍛婃磸閸斿本绂嶆ィ鍐╃厪闁割偅绻嶅Σ鍝ョ棯閹岀吋闁哄本鐩鎾Ω閵壯€鍋撻鍕厱闁靛鍠栨晶顖炴煟閹烘洖浜归柍褜鍓欑粻宥夊磿閸楃倣娑樜旀担渚祫濡炪倖鎸堕崹娲磻閳╁啰绡€濠电姴鍊搁顏堟煟閹惧崬鍔滈柕鍥у椤㈡洟濮€閵忋埄鍞虹紓鍌欐祰妞村摜鏁幒鏇犱航闂佽崵濮村ú銈呂熸繝鍥х劦妞ゆ帊鐒﹀畷灞炬叏婵犲啯銇濈€规洏鍔嶇换婵嬪礋閵婏富娼旈梻鍌欑劍鐎笛兠鸿箛娑樼９婵犻潧妫崵鏇㈡煙閹増顥夐梺鍗炴喘閺屾洘寰勫☉婊冩倕闂佸湱鏌夊▍锝囨閹捐纾兼繛鍡樺灥婵′粙鏌﹂崘顓㈠摵闁靛洤瀚版俊鐑芥晜缁涘顥堥梻浣告惈閺堫剟鎯勯鐐靛祦婵☆垰鐨烽崑鎾绘濞戞﹩妫岄梺鍝勬４缁辨洜妲愰幘瀛樺闁告縿鍎抽崝顔戒繆閻愬瓨缍戦柟鑺ョ矒楠炴垿濮€閻橆偅鏂€闁诲函缍嗘禍鐐哄磹閻愮儤鍋℃繝濠傚暟缁犺崵鈧娲橀崝娆撳箖濞嗘挻鍊绘俊顖濇〃閻㈢粯绻濋悽闈浶㈤柨鏇樺€楅埀顒佸嚬閸犳氨鍒掓繝姘€烽柣鎴烆焽閸樼敻姊洪幆褎绂嬮柛瀣噹閻ｅ嘲鐣濋埀顒勫焵椤掑喚娼愭繛鍙夌矒閳ワ箓宕奸敐鍥︾胺婵犵數鍋犻幓顏嗗緤娴犲绠规い鎰╁焺閸ゆ洟鏌熼幆鏉啃撻柍閿嬪笒闇夐柨婵嗙墛椤忕娀鎮介娑氭创闁哄矉绱曟禒锔炬嫚閹绘帩娼庢俊銈囧Х閸嬬偤鎮ч悩姹団偓渚€寮撮姀鈩冩珳闂佹悶鍎滈埀顒勫矗閻愮儤鈷掗柛灞捐壘閳ь剚鎮傚畷鎰版倻閼恒儱娈戦梺鍓插亝濞插秹鍩€椤掑﹦鐣电€规洖銈搁幃銈嗘媴鐠団€虫櫖闂傚倷绀侀幉锛勭紦閸ф纾块柟鎯板Г閸庢鏌熼幑鎰厫闁哥姵鍔欓弻锝呂旈埀顒勬偋閸℃瑧绠旈柟鐑橆殕閻撱垽鏌涢幇鍏哥盎闁哄鍨圭槐鎺旂磼濡吋鍒涘Δ鐘靛仜椤戝懘鍩㈡惔銈囩杸闁哄洦纰嶉崑鍛存⒒閸屾瑧顦﹂柟璇х節閵嗗啴宕卞Ο鑲╊啎婵犵數濮村ú銈夋嫅閻斿吋鐓涢柛銉㈡櫅閺嬫梻绱掗悩鑽ょ暫闁哄本鐩垾锕傚箣濠靛洨浜┑鐘愁問閸犳煤閻斿娼栭柧蹇氼潐鐎氭岸鏌ょ喊鍗炲妞ゆ柨顦靛娲偡閻楀牆鏆堥梺璇″枛閸婂灝鐣峰ú顏呭€烽柛婵嗗椤撴椽姊洪幐搴㈢５闁稿鎹囬弻锝夊箳閹炬番浠㈤梺鍝勬湰閻╊垶鐛崶顒€鐓涘ù锝呭閻庨绱撻崒娆愵樂闁煎啿鐖煎畷妤€螣娓氼垱缍庨梺鎯х箰濠€杈╁閸忓吋鍙忔俊銈傚亾婵☆偅鐟╅幃楣冩倻閼恒儮鎷洪梺闈╁瘜閸樹粙宕甸埀顒€鈹戦悙鑼勾闁稿﹥绻堥妴浣割潩閼稿灚娅滈梺绯曞墲閻熝囨儊閸績鏀芥い鏃€鏋绘笟娑㈡煕濡寧顥夐柍璇茬Ч婵偓闁靛牆妫岄幏铏圭磽閸屾瑧鍔嶉柨鏇楁櫊閹偞銈ｉ崘鈺佲偓鍫曠叓閸ャ劍鈷掗柟鍐叉喘閹稿﹤鈹戠€ｎ偆鍘告繝銏ｆ硾椤戞劙宕曢妷锔剧闁圭偓鍓氶悡濂告煛鐏炵偓绀嬬€规洜鍘ч埞鎴﹀炊閼告妫ф繝鐢靛У椤旀牠宕伴弽顓炵９闁秆勵殔閽冪喐绻涢幋鐐垫噮缂佲檧鍋撻梻浣告啞閸斿繘寮插┑瀣庡洦瀵肩€涙ê鈧敻鎮峰▎蹇擃仾缂佲偓閸儲鐓涘ù锝呭閻撳ジ鏌曢崱鏇狀槮閾绘牠鏌涘☉鍗炲箻闁挎稒绮岄埞鎴︽偐鐠囇冧紣闂佸綊鏀遍崹鐟拔ｉ幇鏉跨婵炴潙顑嗛弬鈧梻浣虹帛閸旀洟鎮洪妸褌鐒婂ù鐓庣摠閻撶娀鎮峰▎蹇擃仼闁告柣鍊濋幃锟犲Χ婢跺鍘繝鐢靛仧閸嬫挸鈻嶉崨瀛樼厱閻忕偠顕ф俊鐣岀磼缂佹绠栫紒缁樼箞瀹曟帒鈽夊Ο娲讳槐缂傚倷鑳堕崑鎾崇暦濮椻偓瀹曟垿骞囬绛嬫綗闂佽鍎抽悺銊﹀垔閹绢喗鍋ｉ柛銉╊棑绾惧潡鏌涢弮鍫缂佽鲸鎸婚幏鍛村传閸曟垯鍎甸弻娑氣偓锝冨妼閳ь剚绻傞锝嗙節濮橆厽娅滈梺鍛婁緱娴滄繈锝炲澶嬧拺闁告稑顭▓姗€鏌涚€ｎ剙浠遍柟顕€娼ч埞鎴犫偓锝庡亐閹疯櫣绱撴笟鍥х仭婵炲弶锕㈠鎯般亹閹烘挾鍘遍柣搴秵閸嬪懐浜搁鐔翠簻妞ゅ繐瀚弳锝呪攽閳ュ磭鍩ｇ€规洖宕灃闁告劦浜濋崯浼存⒒閸屾瑨鍏岄柛妯犲洤鐤柟绋垮濞呯娀骞栫划瑙勵潑闁搞倖娲滈幉鎼佸籍閸繃妲梺閫炲苯澧柕鍥у楠炴帡骞嬪┑鎰棯闂備焦濞婇弨杈╂暜閿熺姴钃熸繛鎴炵煯濞岊亪鏌ｉ幇闈涘婵炲牄鍊栫换婵嬪煕閳ь剟宕熼鐔峰灡闂備礁鎼張顒勬儎椤栫偟宓侀柛銉墻閺佸棗顭跨捄楦垮闁诡喗鍨块弻锝嗘償閵堝孩缍堝┑鐐插级椤洭骞戦姀銈呴唶闁靛鍎抽悾娲⒑闂堟稓绠為柛濠冩礈缁牓宕掗悙瀵稿幘濠电偞娼欓鍡椻枍閸涱噮娈?",
            "next_task": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎娆戠┛闂傚倷绶氶埀顒傚仜閼活垱鏅堕崜褏纾奸柣妯挎珪鐏忣參鏌ｉ敐澶嬫暠缂佽櫣鏅划娆忊枎閻愵剛绉遍梻鍌欒兌閸嬨劑宕曢柆宥呯柈閻犳亽鍔忔慨鎶芥煏婢跺棙娅嗛柍閿嬪笒闇夐柨婵嗘川閹藉倹绻涢崗鐓庡妞ゎ厼娼￠幃鐑芥偋閸偅锛侀梻浣告惈閹虫挸鈻斿☉婊呬簷闂備礁鎲℃笟妤呭储妤ｅ啯鏅繛鎴欏灪閻撶喖骞栭幖顓炵仯缂佸鏁婚弻娑㈡偐閸愭彃鎽甸悗瑙勬穿缂嶄線鐛Ο鑲╃＜婵☆垳鍘ч獮鍫ユ⒒娓氣偓濞佳嚶ㄩ埀顒傜磼閼艰泛袚濞ｅ洤锕畷绋课旀担鍝勫笚闂備浇濮ら敋妞わ箒妫勮灒闁逞屽墴濮婃椽宕崟顓犲姽缂傚倸绉崑鎾剁磽娴ｅ搫校缂佸鍨块敐鐐测攽鐎ｅ灚鏅ｉ梺缁樏鍫曟煥椤撶喓绡€闁汇垽娼ч崜宕囩磼閼艰埖顥夐悡銈夋煏閸繍妲归柡鍛箖閵囧嫯绠涢幘璺侯暥闂侀€炲苯鍘哥紒鈧笟鈧崺銉﹀緞婵犲孩寤洪梺绯曞墲閿氶柛蹇擄攻娣囧﹪鎮欓鍕ㄥ亾閺嶎偅鏆滃┑鐘插閻棗銆掑锝呬壕闂佺硶鏂侀崑鎾愁渻閵堝棗绗掓い锔诲灦閹﹢鏁嶉崟顓狅紲缂傚倷鐒﹂…鍥╃不閹剧粯鐓冪紓浣股戝畷宀€鈧娲栫紞濠囥€佸▎鎾崇煑闁靛鍎查幉銏ゆ⒒閸屾艾鈧娆㈠顒夌劷鐟滄棃骞冭缁绘繈宕惰閻ｆ椽姊虹粙鎸庢拱闁告垵缍婂畷鐢稿即閻愨晜鏂€闂佺粯锚閻ゅ洦绔熷鈧弻娑樜旀担绯曟灆闂佸搫鏈ú婵堢不濞戙垹鍗抽柣鎰ㄦ櫆閻庝即姊绘担鍛婃喐闁稿濮撮埢鏂库槈閵忕姷鍘撮梺纭呮彧闂勫嫰宕戦幇顔剧＝濞达綀鍋傞幋锔界叆妞ゆ挾鍋愰弨浠嬫煃閽樺顥滃ù婊€绮欓弻娑樜熼崗鍏肩彧闂侀€炲苯澧存繛浣冲洤围闁归棿绀侀弰銉╂煃瑜滈崜姘跺Φ閸曨垰绠抽柟瀛樼箥娴犻箖姊洪幎鑺ユ暠閻㈩垱甯″﹢渚€姊洪幐搴ｇ畵闁绘锕棢濠㈣埖鍔栭悡鏇熸叏濮楀棗澧扮紒澶嬫そ閺岋紕浠﹂崜褎鍒涢梺璇″枓閺呯姴鐣峰鈧獮鎾诲箳濠靛洨绋堟繝寰锋澘鈧鎱ㄩ悜钘夌；闁绘劕鎼粈澶嬬箾閸℃ɑ灏电€规挷绶氶弻鈥愁吋閸愩劌顬夋繝娈垮灡閹告娊寮诲☉妯锋斀闁告洦鍋勬慨搴ㄦ倵濞堝灝鏋旈柛鏂跨焸閸╃偤骞嬮敂钘変汗濡炪倖妫侀崑鎰閸ヮ剚鈷戠紒顖涙礃濞呭棝鏌ｅΔ鍐ㄐ㈤柣锝呭槻閳规垹鈧綆浜滃畵鍡涙⒑缂佹◤顏堝触閳ь剛绱掑Δ鈧ˇ杈╂閹捐纾兼繛鍡樺灥婵′粙鏌ら崹锕€鍘鹃悷閭︾叆闁告洦鍘鹃悡澶愭⒑閸濆嫬顦柍褜鍓氶崜姘跺触鐎ｎ喗鐓曢柟鎵虫櫅婵″吋銇勯鈧澶婎潖閾忓湱纾兼俊顖滅帛閸庡酣姊洪幖鐐插闁告濞婇崹楣冩晜閻愵剙纾梺闈涱煭缁犳垿寮搁崒鐐粹拺闁告稑锕ユ径鍕煕閹惧娲撮挊婵嬫煏婢跺棙娅嗛柍閿嬪灴閹宕烽鐑嗏偓灞剧箾閸忕厧濮嶉柡灞剧洴婵℃悂濡烽敃鈧禒鎾倵鐟欏嫭绀冩俊鐐跺Г娣囧﹪鎮滈挊澶屽幐婵炶揪绲鹃悺鏇㈠焵椤掆偓閻忔繈鍩為幋锔芥櫖闁告洦鍋傜划鑸电節閳封偓閸屾粎鐓撻悗娈垮櫘閸嬪﹤顕ｉ崐鐕佹Х闂佽　鍋撳ù鐘差儐閻撶喐鎱ㄥΔ鈧Λ妤佺濠靛棌鏀芥い鏍ㄧ懃瀹撳棝鏌＄仦鍓ф创鐎殿喗鎸抽幃娆撳礂閸濄儵鈹忛梻鍌欐缁鳖喚寰婇懖鈺佸灊婵炲棗娴氬鏍ㄧ箾瀹割喕绨婚柟纭呭煐閵囧嫰骞樼捄鐩掞綁鏌熼崣澶涜€挎慨濠呮缁瑥鈻庨幆褍澹堥梺璇插閻噣宕￠崘鑼殾婵炲樊浜濋崐鐑芥煕濠靛棗顏い鎾存そ濮婃椽骞愭惔銏╂⒖濠碘槅鍋勭€氫即宕洪埀顒併亜閹烘垵鈧悂宕㈤幘顔界厵妞ゆ梻鐡斿▓鏃堟煃閽樺妲搁柍璇茬Ч椤㈡顦辩紒銊ょ矙閺屾盯鎮╃拠褍浼愬銈嗘尭閸氬顕ラ崟顓涘亾閿涘崬瀚鍦磽閸屾艾鈧悂宕愰悜鑺ュ€块柨鏇炲€甸埀顒婄畵瀹曞爼濡搁敂鐣屽娇闂傚倷绶￠崜娆戠矓閻㈠憡鍋傞柡鍥╁枍缁诲棙銇勯弽銊х煀鐎涙繂鈹戦悙棰濆殝缂佺姵鎸搁悾鐑藉箣閿曗偓閻撴盯鏌涢幇鍓佸埌濞存粓绠栭弻锝夋偄閸涘﹦鍑″銈呮禋娴滎亪骞冨Δ鈧～婵嬵敆閸屾埃鍙洪柣搴㈩問閸ｎ噣宕抽敐鍛殾闁绘挸绨堕弨浠嬫煕閳╁啰鎳呯€规洖鎼埞鎴︽晬閸曨偂鏉梺绋匡攻閻楃娀鐛幇鏉块唶闁哄洨鍋涢悗顓㈡偡濠婂懎顣奸悽顖涘浮瀵憡鎷呴悜妯烘瀾闂佺粯顨呴悧鍡欑箔濮樿埖鐓冮梺鍨儏缁楁帡鏌曢崱妯虹瑨妞ゎ偅绻堥弫鎰板川椤掆偓椤ユ艾鈹戦悩鍨毄闁稿锕㈠畷鐘绘偐鐠囨彃绐涘銈嗘⒒閸樠呰姳閵夆晜鈷掑ù锝囶焾椤ュ繘鏌涚€ｂ晝绐旂€规洘娲熼弻鍡楊吋閸涱厾鈧參姊虹粙鎸庢拱闁糕晛鍟村銊︾鐎ｎ偆鍘藉┑鈽嗗灥濞咃綁鏁嶅鍡愪簻闁挎繂妫涢崣鈧梺鍝勬湰缁嬫捇鍩€椤掑﹦绉靛ù婊勭矒閸┾偓妞ゆ巻鍋撴繛灏栤偓鎰佸殨閻犲洤妯婇崥瀣煕椤愵偄浜濇い搴℃喘濮婄粯鎷呴崨濠傛殘闂佽鎮傜粻鏍х暦閻楀牊鍎熸い顓熷笧缁嬪繘妫呴銏″婵炲弶绮庢竟鏇㈠礂闂傚绠氬銈嗙墬缁诲秹宕靛▎鎰╀簻閹兼番鍨哄畷灞炬叏婵犲啯銇濇俊顐㈠暣閸┾剝鎷呴悜妯炴帡姊绘担鍛婂暈閻绱掗鐣屾噰妤犵偛锕弫鎰緞婵犲嫬鈧偛顪冮妶鍡楃瑐閻犱焦鐓￠獮蹇撁洪鍛嫼闂佸憡绋戦敃锕傚煡婢舵劖鐓ラ柡鍥崝锕傛煙椤曞棛绡€濠碉紕鍏橀崺锟犲磼濠婂啫绠哄┑锛勫亼閸婃牕顔忔繝姘；闁瑰墽绮悡蹇涙煕椤愩倕鏋戦柛濠冨姉閳ь剝顫夊ú妯侯渻娴犲鏄ラ柍褜鍓氶妵鍕箳瀹ュ顎栨繛瀛樼矋缁捇寮婚悢鐓庝紶闁告洦鍘滈妶鍡愪簻闁挎棁鍋愰悾鐢告煛鐏炲墽娲村┑陇鍩栭幆鏃堝灳閺傘儲瀚梻鍌欑閹碱偊寮甸鍕剮妞ゆ牗绋愮换鍡涙煙闂傚顦﹂幆鐔兼⒑閹稿孩鐓ｉ柛鏇燂耿閸┾偓妞ゆ帊绀佹慨宥嗘叏婵犲嫬鍔嬮悗鐢靛帶閳诲酣骞嬪┑鍡欏帓闂傚倷鐒﹂幃鍫曞垂閼测晙鐒婃い蹇撶墛閸婂爼鏌涢幇闈涙灍闁抽攱鍨垮娲敃閵堝懍绮堕梺鍏兼た閸ㄩ亶寮查崼鏇炵妞ゆ梻鏅崣鍡椻攽閻樼粯娑ч柣妤€妫欑粋鎺戭煥閸曗晙绨诲銈嗘尰缁本鎱ㄩ崒婧惧亾鐟欏嫭绀堥柛妯犲洤鐓橀柟杈剧畱闁卞洦绻濋棃娑欑厐闁哄洨鍋愰弨浠嬫煥濞戞ê顏╁ù婊冦偢閺屾稒绻濋崘顏勨吂濡炪倖鏌ㄧ换鎴犳崲濠靛棭娼╂い鎺戝亰缁遍亶姊绘担鐑樺殌濠⒀呮櫕閸掓帡顢涢悙鏉戜簵闂佺粯鏌ㄩ崥瀣偂閵夛妇绡€闂傚牊绋掗ˉ鐐烘煕閿濆牜娼愬ǎ鍥э躬楠炴捇骞掑┑鍫濇倯闂備礁鎼懟顖滅矓閸洖绠熼柟缁㈠枛缁€瀣亜閹扳晛鈧挾妲愬┑瀣厽閹兼番鍊ゅ鎰箾閸欏绠橀柛鎺撳浮瀹曟粏顦村☉鎾崇У缁绘盯骞嬪▎蹇曚患缂備緡鍋勭粔褰掑蓟閻旇　鍋撻悽娈跨劸濞寸姍鍛＜濠㈣泛鑻禍鍓х磼缂佹绠為柟顔荤矙濡啫霉鐠佸湱绋婚柕鍥у瀵噣鍩€椤掑嫭鍋嬮柣妯垮皺閺嗭箓鏌℃径搴殾闁哄啫鐗嗗婵囥亜閺冨洤袚闁绘繃鐗犲缁樻媴缁嬫寧姣愰梺鍦拡閸嬪﹪鐛繝鍐╁劅闁挎繂娲ㄩ悞濂告⒑缁嬫寧婀扮紒瀣尵缁粯銈ｉ崘鈺冨幍闁诲孩绋掗…鍥箠閸愵喗鐓熼煫鍥э攻濞呭洨绱掓潏銊ユ诞闁糕斁鍋撳銈嗗坊閸嬫捇鏌ｉ敐鍡欑疄鐎规洜鍠栭、妤呭磼濮橆剛顔囬梻浣筋嚙妤犲摜绮诲澶婄？閺夊牜鐓堝▓浠嬫煙闂傜鍏岀€规挷鐒︽穱濠囧Χ閸涱喖娅ら梺缁樻尭閸熸潙顫忓ú顏勫瀭妞ゆ洖鎳庨崜浼存⒑鐠囪尙绠查柟鍛婂▕瀵鍨惧畷鍥ㄦ畷闂侀€炲苯澧寸€规洑鍗抽獮妯兼崉閸濆嫮浜版繝鐢靛仜濡瑩骞愰崫銉т笉濞村吋娼欑粻瑙勭箾閿濆骸澧柣蹇婃櫊濮婂宕掗妶鍛桓濠殿喖锕︾划顖炲箯閸涙潙浼犻柕澶涘閳ь剦鍠栭埞鎴﹀煡閸℃ぞ绨婚柣搴㈢婵棄螞閻斿吋鈷戞慨鐟版搐閻忣喗銇勯鐐靛ⅵ闁归攱鍨块幃銏ゅ礂閼测晛甯鹃梻浣稿閸嬪懐鎹㈤崘顔肩；妞ゅ繐鐗婇悡锝夌叓閸ャ劌鍤繛鍏煎姍閹顫濋鐐叉懙闂佸搫琚崐妤呭窗婵犲洤纭€闁绘劖褰冪粻鐗堢節绾版ê澧叉い銊ユ楠炴垿宕堕鈧拑鐔兼煥濠靛棙顥為柛搴ｅ枛閺屾洟宕煎┑鍡╁妷缂傚倸绉撮悧鍡涘煘閹达附鍊峰Λ鐗堢箓濞堟繄绱撴担鍝勑ｉ柟鍛婃倐閹箖鎮块妯规睏闂佸湱鍎ら崹鍧楀船閸洘鈷戦柛婵嗗瀹告繈鏌涚€ｎ剙浠滈崡杈ㄣ亜閹烘垵顏柍閿嬪灴濮婃椽顢曢妶鍛捕闂佸吋妞块崹閬嶅疾閸洦鏁嶉柣鎰嚟閸橆亪姊洪幖鐐插妧闁告劕褰炵槐鏃€淇婇妶鍥ラ柛瀣仧閺侇噣鏁撻悩闈涚ウ闁诲函缍嗘禍鏍绩娴犲鐓欓梺顓ㄧ細缁ㄨ姤淇婇顐㈢仸婵﹤顭峰畷鎺戔枎閹烘垵甯紓鍌欑贰閸ｎ噣宕归崼鏇犲祦闁归偊鍠楃€氭岸鎮锋担椋庮槮闁圭⒈鍋夐悘鎺楁⒑缁嬭法绠抽柛妯犲嫭鍎熷┑鐘插€甸弨浠嬫煟閹邦厽缍戦柣蹇曞枛閺屾盯濡搁妷褏楔闂佺粯渚楅崳锝嗘叏閳ь剟鏌嶉妷銊ョ毢缂佺姵鑹鹃—鍐Χ閸℃瑥顫у┑顔角滈崝搴ｅ垝鐠囪娲敂閸涱垰骞堥梺璇插嚱缂嶅棝宕戦崟顒佸弿鐎广儱顦伴悡娆戔偓瑙勬礀濞层倖绂掗敂鐣岀闁绘挸娴风粻濠氭煕閳哄绡€鐎规洘甯掗～婵嬪础閻愬搫褰欓梻鍌氬€峰ù鍥х暦閻㈢绐楃€广儱鎷嬪〒濠氭煙閻戞ɑ鈷掗柣顓炴闇夐柨婵嗙墛椤忕姷绱掗埀顒佺節閸屾鏂€闂佺粯锚瀵爼骞栭幇顔剧＜闁绘ê纾晶鐢告煛鐏炵晫校婵炵⒈浜獮蹇曚沪閽樺鑵愰梻鍌欑閹碱偄螞鐎靛摜涓嶉柟鎹愵嚙閽冪喐绻涢幋娆忕仼閸烆垶姊洪幐搴ｇ畵闁瑰啿瀛╅幈銊﹀緞閹邦厸鎷虹紓浣割儐椤戞瑩宕曢幇鐗堢厵闁荤喓澧楅崰姗€鏌ｅ☉鍗炴珝妤犵偞甯掕灃闁逞屽墰閻氭儳顓兼径瀣幈闁诲繒鍋涙晶浠嬫偝閼姐倗纾奸柛妤冨仜缁狙兦庨崶褝韬柟顔界懇椤㈡棃宕熼妸銉ゅ闂佸搫绋侀悘鎰洪鍕敤濡炪倖鎸鹃崑鐔兼偪閸ヮ剚鐓欓柤娴嬫櫈钘熷┑鈩冨絻閹虫ê鐣烽悽绋垮嵆闁绘梻绻濈花濠氭⒑閸濆嫬鈧綊顢栧▎蹇ｇ劷闁绘棁顔栭悷閭︾叆闁告洦鍘鹃悡澶愭⒑閸濆嫭婀版繛鍙夌箘缁鈽夐姀鐘栥劎鎲歌箛娑欐櫖闁绘柨鎽滅弧鈧梺鍐茬殱閸嬫捇鏌涢妷顖炴闁哥姵宀稿娲传閸曨厾浼囬梺鍝ュУ閻楃娀鐛崘顔藉€婚柦妯侯槺妤犲洤鈹戦悙鍙夘棞鐟滄壆鍋熷Σ鎰板籍閸啿鎷绘繛杈剧到閹碱偅绂掑ú顏呯厱閹兼番鍊曢崥鍦磼椤旂⒈鐓兼鐐达耿閹筹繝濡堕崨顖樺亰闂備浇顕ч崙鐣岀礊閸℃顩查柛顐ｆ礃閸嬪倿鏌曟径鍡樻珕闁绘挻娲樼换娑㈠箣濠靛棜鍩為梺璇茬箺妞村憡绌辨繝鍥╁彄妞ゆ挾鍋涚粊顔尖攽椤旂》宸ユい顓炲槻閻ｇ兘骞掗幋顓熷兊濡炪倖鍨煎Λ鍕閸撗€鍋撻悷鏉款仾闁革絿顥愰妵鎰板箳閹寸姴鈧偛顪冮妶鍡楃瑨妞わ缚鍗冲鏌ヮ敂閸喎浠┑鐘诧工閸熸壆绮荤紒姗嗘闁绘劖娼欓悘鏉戔攽椤旂懓浜鹃梻渚€娼ч悧鍡涘箠閹伴偊鏁婂┑鐘插€甸弨浠嬪箳閹惰棄纾归柟鐗堟緲绾惧鏌熼幆褍顣虫俊顐灦閺屾盯骞樺Δ鈧幊搴ｇ箔閿涘嫮纾藉ù锝堟鐢盯鏌ｉ埡濠傜仸闁绘侗鍠氶埀顒婄秵娴滄牠寮告惔銊у彄闁搞儯鍔嶇壕濠氭煙椤曞棛鎮肩紒杈ㄦ尰閹峰懘宕崟顏勵棜闁诲氦顫夊ú姗€鏁冮姀銈嗘櫜闁绘劖娼欑欢鐐烘煙闁箑澧伴柣銈呭濮婃椽妫冨☉杈╁姼闂佺瀵掗崳锝咁嚕閵婏妇顩烽悗锝庡亞閸橀亶姊洪弬銉︽珔闁哥噥鍋婂畷鐢割敆娴ｈ櫣顔曢梺鑹邦潐濠㈡﹢鎮￠幇顔剧＜缂備焦顭囬妴鎺楁煃瑜滈崜姘辩矙閹烘せ鈧箓宕堕浣稿壒婵犵數濮寸€氼喚澹曢悾灞稿亾楠炲灝鍔氶柟閿嬪灴閻擃剟顢楅崒妤€浜炬繛鍫濈仢閺嬶附銇勯弴鍡楁搐閻撯€愁熆鐠哄ソ锟犳偄閸忚偐鍙嗛柣搴秵閸忔﹢宕戦幘瀵哥瘈婵﹩鍙庡Λ鍛渻閵堝棗濮傞柛銊ㄦ缁﹪顢曢妶鍥╋紲闂佸搫琚崕鎶芥偩濞差亝鐓曢柍鐟扮仢閻忓弶顨ラ悙杈捐€跨€殿噮鍓熸俊鐑芥晜閼恒儲绶梻鍌氬€烽懗鍓佸垝椤栫偛绀夋俊顖炴？閻掑﹥绻涢崱妯哄婵炲懐濞€閺屾洝绠涚€ｎ亖鍋撻弽顓熷亗婵炴垯鍨洪悡鏇熺節婵炴儳浜剧紓浣插亾濞达絽婀遍々鎻捗归悡搴ｆ憼闁绘挻娲熼弻宥囨喆閸曨偄濮㈡繛瀛樼矌閸嬫挻绌辨繝鍥ㄥ€锋い蹇撳閸嬫捇寮借閸熷懎鈹戦悩瀹犲缁炬儳顭烽弻鐔煎礈瑜忕敮娑㈡煟閹惧瓨绀冨ǎ鍥э躬椤㈡稑鈹戦崱妤佸劒闂備焦妞块崢鐣屾暜閻愬搫鐒垫い鎺戝枤濞兼劖绻涢崣澶涜€跨€规洖缍婂畷绋课旈崘銊с偊婵犵妲呴崹鐢稿磻閹邦喖顥氶柛蹇涙？缁诲棙銇勯弽銊х煀閻㈩垵鍩栭〃銉╂倷閼碱剙鈪靛┑顔硷功缁垶骞忛崨顖滈┏閻庯綆鍋嗙粔閿嬬節閻㈤潧袨闁搞劍妞介弫鍐閻樺灚娈鹃梺闈涱槴閺呮盯鎮為崹顐犱簻闁圭儤鍨甸埀顒冨吹婢规洘绺介崨濠勫帾婵犵數鍋涢悘婵嬪礉濮樿埖鐓欐い鏃囨閻忔挳鏌＄仦鐐鐎规洘鍎奸ˇ鍙夈亜韫囷絽骞楅柕鍥у婵偓闁斥晛鍟伴ˇ鐗堢節濞堝灝鏋撻柛瀣崌濮婅櫣鈧湱濮电涵楣冩煟韫囨梹绀嬬€规洜鍠栭、妤呭焵椤掆偓椤曪綁骞愭惔锝囩槇闂佹眹鍨藉褍鐡梻浣告憸閸ｃ儵宕归懜鍏哥箚闂傚牊绋堥弨浠嬫煕椤愶綀澹樺ù婊堢畺閹嘲鈻庤箛鎿冧痪缂佸墽鍋撻幃鍌炲蓟濞戙垹妫橀悹鎭掑壉閵堝鐓欐鐐茬仢閻忊晠鏌嶇憴鍕仼闁逞屽墾缂嶅棙绂嶉悙鏍稿洭濡搁妷顔藉瘜闂侀潧鐗嗛幊鎰不娴煎瓨鍊垫慨妯煎帶婢ф壆绱掗娆惧殭閻撱倖銇勮箛鎾村櫝闁瑰嘲顭峰铏圭矙閹稿孩鎷遍梺鑽ゅ暀閸ヤ礁娲弫鍐磼濞戞艾骞嶉梺鑽ゅТ濞壯囧川椤栨粍顫岄梺璇插椤旀牠宕伴弽顓涒偓锕傛煥鐎ｂ晝绠氶梺褰掓？缁€渚€鎮″☉妯锋斀闁绘ɑ褰冮弳鐐寸箾閸涱厾澧︽慨濠勭帛閹峰懐鎲撮崟顐″摋闂備胶顭堢€垫帡宕抽敐鍜佸殨闁圭粯甯╅悡銉╂煕椤愵偄澧扮紒?",
        }
        base = mapping.get(scenario, "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎娆戠┛闂傚倷绶氶埀顒傚仜閼活垱鏅堕崜褏纾奸柣妯挎珪鐏忣參鏌ｉ敐澶嬫暠缂佽櫣鏅划娆忊枎閻愵剛绉遍梻鍌欒兌閸嬨劑宕曢柆宥呯柈閻犳亽鍔忔慨鎶芥煏婢跺棙娅嗛柍閿嬪笒闇夐柨婵嗘川閹藉倹绻涢崗鐓庡妞ゎ厼娼￠幃鐑芥偋閸偅锛侀梻浣告惈閹虫挸鈻斿☉婊呬簷闂備礁鎲℃笟妤呭储妤ｅ啯鏅繛鎴欏灪閻撶喖骞栭幖顓炵仯缂佸娼ч湁婵犲﹤瀚晶鐢碘偓娈垮枔閸斿秶绮嬮幒鏂哄亾閿濆骸浜為柛妯挎閳规垿鍩ラ崱妤冧淮濡炪倖娉﹂崨顓犵瓘婵犵數濮电喊宥夋偂濞戙垺鐓曢柍鈺佸彁閹寸姷鐭嗛柛顐犲灮绾惧ジ寮堕崼娑樺缂佹う鍥ㄧ厵濡炲楠搁埢鍫⑩偓瑙勬穿缁叉儳顕ラ崟顐嬬喐瀵煎▎鎴狀槯闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敂钘夊壎婵犻潧鍊婚…鍫㈢玻濡ゅ懏鐓涚€规搩鍠栭張顒傜礊鎼淬劍鈷戦柣鎾冲瘨濞肩喖鏌涙繝鍐ㄥ鐎规洘鍨块獮妯肩磼濡桨缂撴繝鐢靛仜閻楁劕鈻旈弴銏犵闁告稑锕︾弧鈧紒鍓у鑿ら柛瀣崌閹崇娀顢楅崒婊冨箚濠电姵顔栭崰鏍晝閵夈儺娓诲ù鐘差儑瀹撲線骞栧ǎ顒€濡介柛銈呯Ч閺屾洘寰勫☉銏☆€嶅┑鐐茬墛閹倸顫忛崫鍕懷囧炊瑜忛崝鎾⒑閹肩偛濮傚ù婊冪埣婵℃挳宕橀埡鍐槇闂佸憡鍓崨顖滄毎闂傚倷鐒﹂惇褰掑垂婵犳埃鈧箓宕奸姀銏㈢劶闁诲函缍嗛崑浣圭濠婂牊鐓涚€广儱鍟慨鈧繝銏ｎ潐椤洭鍩€椤掑喚娼愰柟鍝ヮ焾铻炴俊銈呮噹閻撴﹢鏌熺€电浠滅紒鐘靛█濮婅櫣绮欓崠鈩冩暰闂佸憡姊归悷銉╂偩閻戣棄绠ｉ柨鏇楀亾缂佺姴顭烽幃娲箳瀹ュ牆鍘￠梺纭呮珪閹瑰洭鍨鹃敃鍌毼╅柍杞拌兌椤︽澘顪冮妶鍡楀闁搞劎顢婇。鑺ョ節绾板纾块柛瀣灴瀹曟劙濡堕崱娆樻锤濠电姴锕ら悧鍡涙偪椤曗偓閹鈽夊▍顓″亹閹广垽宕卞☉娆戝幍濡炪倖鐗楃粙鎴λ夌€ｎ喗鐓熼柕鍫濆€告禍楣冩⒒閸屾瑧顦﹂柟纰卞亜鐓ら柕濞炬櫅缁愭骞栧ǎ顒€鐏い鈺咁棑閹叉悂鎮ч崼婵堢懖闂佹娊鏀辩敮鎺楁箒闂佹寧绻傞幊蹇涘疮閻愮儤鐓欐い鏍ㄦ皑婢э箓鏌″畝鈧崰搴ㄦ偩閿熺姵鐒介柨鏇楀亾闁告挸鐖奸幃妤冩喆閸曨剛顦ㄩ梺鎼炲妼閻忔繈鎮鹃悜钘夌闁绘垵妫欑€靛苯顪冮妶搴′航闁哥姵姘ㄧ划鏃堫敊缁涘顔旈梺缁樺姇瀵爼宕板Ο灏栧亾濞堝灝鏋涘褍閰ｉ獮鎴﹀礋椤栨せ鍋撻敃鍌氱婵犻潧娲﹂悵銊╂⒒閸屾艾鈧嘲霉閸パ呮殾闁割煈鍋呴崣蹇涙煛婢跺娈繛宸簻閻撴盯鏌涢幇灞芥噹婢х偓绻濋悽闈涗粶婵☆偅鐟╅獮鎰板箹娴ｅ摜锛滈梺闈浥堥弲婊堟偂濞嗘挻鈷掗柛灞惧嚬閸ょ喖鏌涢弬璺ㄐч柡灞界Ч閺屻劎鈧綆浜炴禒鑲╃磽娴ｄ粙鍝洪悽顖滃仱閸┾偓妞ゆ帒锕︾粔鐢告煕鐎ｎ亜顏い銏¤壘椤劑宕熼鐘垫闂備線鈧偛鑻晶鎾煙椤斻劌娲ら柋鍥煟閺傚灝妲诲ù鐓庡缁绘繄鍠婂Ο娲绘綉闂佹悶鍔嶆繛濠囧灳閿曞倸閱囬柣鏂垮缁犳岸姊烘导娆戝埌闁活剝鍋愭竟鏇熺附閸涘﹦鍘遍柣蹇曞仧閸嬫捇鎯冮幋锕€鏋侀柛顐犲劜閳锋垿寮堕悙鏉戭棆闁告柨绉归弻娑㈠籍閳ь剟鎮烽妷鈺傚仼闁绘垼妫勭涵鈧梺缁樺姀閺呮粓鎮楁繝姘拺閻熸瑥瀚崕妤呮煕濡亽鍋㈢€殿喗鐓￠、姗€濮€閳锯偓閹峰姊虹粙鎸庢拱闁荤喆鍔戝畷妤€鐣濋崟顒傚幍闂佹儳娴氶崑鍛暦鐏炰勘浜滈柕蹇娾偓鍐叉懙濡炪們鍨洪敃銏℃叏閳ь剟鏌ｅΟ纰辨殰缂侀亶浜跺缁樻媴閾忕懓绗￠梺鍛婃⒐濞茬喎鐣烽妷鈺佺劦妞ゆ帒瀚悡鐔兼煙閻戞ê鐓€闂婎剦鍓熼弻锛勪沪閻愵剛顦ㄧ紓浣虹帛閻╊垶骞冨▎鎿冩晢濞达絽鎼徊楣冩⒒閸屾瑨鍏岀紒顕呭灦楠炴劗鎷犵憗浣规そ閹垽鎮℃惔锝囨毇婵犲痉鏉库偓鏇㈠箠韫囨稑鐤鹃柡灞诲劚缁犲湱绱掗鐓庡辅闁稿鎹囬幊鐘活敆閳ь剟宕甸鍕拻濞达絿鐡旈崵娆戠磼缂佹ê濮囬棁澶嬫叏濡寧纭鹃柣顓燁殜閺屾盯骞囬棃娑欑亪闂佽棄鍟伴崰鎾诲焵椤掆偓缁犲秹宕曢柆宓ュ洭骞嶉鐟颁壕闁汇垽娼у瓭濡炪値鍘煎锟犲箠濠婂牊鍎旀い蹇撴噹閻忔挳鏌涢埞鍨伈鐎规洜鍘ч…鍧楊敂閸涱噮妫冮梺璇″枓閺呯姴螞閸愩劉妲堟俊銈勭婵即姊婚崒娆愮グ鐎规洜鏁诲畷顖炲锤濡も偓閻ょ偓绻涢幋娆忕仾闁稿鏅濋埀顒傛嚀鐎氼厾鈧艾鐗撻幃銏焊娴ｅ湱鈧姊虹紒妯哄Е闁稿海鍏橀、妤呭礋椤戣姤瀚藉┑鐐舵彧缁蹭粙骞夐敓鐘茬柈闁绘劗鍎ら悡鏇㈡煏婵炲灝鍔ょ紒澶屽劋椤ㄣ儵鎮欑拠褑鍚Δ鐘靛仦椤洭骞忛悩缁樺殤妞ゆ巻鍋撴鐐差儔濮婄粯鎷呮笟顖涙暞闂佽妞挎禍顏勵潖娴犲绀嬫い鏍ㄦ皑閿涙瑩姊虹紒妯虹伇濠殿喓鍊濆畷鎰板垂椤愩倗顔曢梺鐟邦嚟閸庢劖绂掗悙顑句簻闊洦鎸婚ˉ婊堟煛鐎ｎ亞澧㈤柍褜鍓欑粻宥夊磿閸楃倣娑樷槈濮橆剙袣闂侀€炲苯澧存慨濠冩そ瀹曟﹢鎳犻渚囧敻闂備胶顭堥鍡涘箲閸ヮ剙钃熸繛鎴欏灩缁犳盯鏌ｉ姀銈嗘锭閻㈩垬鍎靛娲川婵犲啰鍙嗗銈忕畳娴滎剙危閹版澘绠婚悗娑櫭鎾剁磽娴ｅ壊鍎忕紒銊╀憾瀹曟垿骞樼拠韫炊闂侀潧锛忛崨顖氬脯闂傚倷绀佸﹢閬嶆惞鎼淬劌闂い鏍ㄧ矌缁€濠囨煛瀹ュ骸骞楅柣鎾崇箻閻擃偊宕堕妸锔绢槬闁哥喐鎮傚娲传閸曨剦妫炲┑鈽嗗亝缁诲牆顕ｇ拠宸悑闁割偒鍋呴鍥⒒娴ｅ憡鍟為柟鎼佺畺瀹曚即寮介鐘茬ウ闂佸憡鍔﹂崰鏍煥閵堝棔绻嗛柕鍫濆€告禍楣冩⒑缂佹ê绗掗柣蹇斿哺婵＄敻宕熼姘鳖唺闂佺懓鐡ㄧ换宥嗙妤ｅ啯鈷戦柟鎯板Г閺侀亶鏌涢妸銉﹀仴妤犵偛鍟悾锟犲箥閾忣偆鈧妫呴銏″闁瑰皷鏅滅粋鎺撶附閸涘ň鎷洪梺鍛婄☉閿曘儵鎮￠悢鍏肩厱濠电姴鍟扮粻鐐碘偓娈垮枛椤兘寮幇顓炵窞濠电偐鎷冮崶銊у幈濠电偞鍨靛畷顒勫几濞戙垺鐓涢悗锝庡墮瀛濆銈庝簻閸熷瓨淇婇崼鏇炵闁靛ě鍌滄／闂傚倷娴囧畷鐢稿闯閿斿墽涓嶉柟杈惧瘜閺佸鏌曟径鍡樻珔缂佲偓鐎ｎ偁浜滈柟鎯ь嚟閳藉霉濠婂牏鐣洪柡灞诲妼閳规垿宕卞璇蹭壕闁荤喐澹嬮弸宥夋煕閵夈垺娅囩痪鎯с偢閺岋絽螣閸濆嫭姣愰梺鍛婄箘閸庛倝骞堥妸锔剧瘈闁告劏鏂傛禒銏犫攽閳藉棗浜滈柛鐕佸亰閸┿儲寰勬繝搴㈠兊濡炪倖甯掗ˇ鏉啃掗崶褉鏀介柣妯虹仛閺嗏晠鏌涚€ｎ偆娲撮柟顖氭处鐎靛ジ寮堕幋鐙呯串闂備礁鎼ú銏ゅ垂濞差亜纾婚柕鍫濇娴滄粓鏌熼幆褍鑸归柣蹇ｄ邯閺屽秹鏌ㄧ€ｎ亞鐟ㄩ梻鍥ь樀閺屻劌鈹戦崱娆忊拡濠电偛鍚嬮崝娆撳蓟閺囥垹鐐婇柍杞扮劍閻忓牓姊洪崫鍕拱缂佸鍨奸悘鎺楁⒑閸︻収鐒鹃悗鍨笚缁傛帡鍩℃担鍙夋杸闂佺粯鍔曞鍫曀夐幘缁樼厱闁靛鍎崇粔娲煥濠靛牆浠滈柍瑙勫灴瀹曞ジ鎮㈡搴础闂傚倷鐒﹂崕宕囨崲閹邦剨鑰块梺顒€绉村Ч鏌ユ煛婢跺﹦姘ㄩ柡鈧禒瀣厽闁归偊鍨伴悡鎰喐閹跺﹤鎳愮壕濂告煙缂佹ê绗氶柛瀣ㄥ劜椤ㄣ儵鎮欑拠褑鍚Δ鐘靛仦閿曘垽骞婂鍐ｆ灁闁割煈鍠曠紓鎾绘⒒閸屾瑨鍏岀紒顕呭灦瀹曟繂螖閸涱厾锛熼梺闈涚墕椤︿即宕戦崒娑氱闁糕剝蓱鐏忎即鏌嶉柨瀣仸闁靛洤瀚伴獮姗€宕￠悙宸€烽梻浣风串缁茶棄鐣烽鍕ㄢ偓锕傛嚄椤栵絾鞋濠电姭鎷冮崟鍨杹婵犵绱曢弫璇茬暦閻旂⒈鏁嶆繛鎴炵懄閻濇洟姊洪懡銈呅㈡繛灞傚€曢锝夊醇閺囩喎浠у┑鐘绘涧濡矂寮ㄩ懞銉ｄ簻闁哄啫鍊堕埀顒€顑夊銊х磼濡湱绠氶梺缁樺姌閸╂牠藟婢舵劖鎳氶柣鎰劋閻撴洟鏌熼幍铏珔濠碉繝鏀辨穱濠囧箵閹烘柨鈪甸悗娈垮枛閻栫厧鐣烽悡搴僵妞ゆ挾鍠撹ぐ鍛攽閻樻剚鍟忛柛鐘崇墵婵″墎绮欏▎鐐稁缂傚倷鐒﹁摫濠殿垱娼欓妴鎺戭潩閻撳海浠梺鍛婃⒐閹倸顫忓ú顏勭閹兼番鍨婚敍姗€姊虹粙鎸庢崳闁轰胶绮穱濠囧箻椤旇偐顦ㄥ銈嗘煥閵堟悂宕崼鏇熲拺闂傚牊绋撶粻鍐测攽椤旇姤灏﹂柟?")
        if repeated_gap:
            if localized_repeated_gap:
                base += ""
            else:
                base += "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱濠电姴鍊归崑銉╂煛鐏炶濮傜€殿噮鍣ｅ畷濂告偄閸涘鍞堕梻鍌欒兌椤牓顢栭崱娑樼闁告挆鍐ㄧ亰濡炪倖鎸鹃崑鎰ｉ崼鐔剁箚妞ゆ牗绻嶉崵娆愮箾閸涘洤娲﹂埛鎴炵箾閼奸鍤欐鐐搭殜閺岋綁鎮㈤崣澶嬬彋閻庢鍠栭…鐑藉箖閵忋倕宸濆┑鐘插鑲栨繝寰锋澘鈧呭緤娴犲鐤い鏍剱閺佷胶鈧箍鍎遍ˇ浼村煕閹达附鐓欓柤娴嬫櫅娴犳粓鏌嶈閸撴岸鎮ч悩鑼殾婵犻潧顑呴崘鈧銈嗘尵閸婏綁鏁冮崒娑氬幈闂佸搫娲㈤崝宀勬倶閻樼粯鐓曢柟鑸妼娴滄儳鈹戦敍鍕杭闁稿﹥鐗犲畷婵嬫晝閳ь剟鈥﹂崸妤€鐒垫い鎺戝€荤壕鍏笺亜閺冨倸甯舵い锝呯－缁辨帗娼忛妸锕€闉嶉梺鐟板槻閹虫ê鐣烽锕€绀嬮柟鎼灣缁夘噣鏌″畝瀣埌閾绘牠鏌涢幇鈺佸Ψ闁哄鎳橀幃妤€鈻撻崹顔界亪濡炪値鍘鹃崗姗€鐛崘顔碱潊闁靛牆妫楁禍妤呮煙閼圭増褰х紓宥呮瀹曨剝銇愰幒鎾嫽婵炴挻鍩冮崑鎾绘煃瑜滈崜姘辩矙閹存繄鏆ら柛鈩冾焽缁犳儳霉閿濆懎鏆遍柛鐔哄█瀵悂寮埀顒勫Φ閸曨垰绠婚悹铏规磪閵壯呮／闁硅鍔栭ˉ澶愭煏閸℃ê绗掓い顐ｇ箞椤㈡鎷呯憴鍕偓宄扳攽閻愯尙鎽犵紒顔肩Ф閸掓帗鎯旈敐鍡╂綗闂佸湱鍎ら幐鍝ユ閻愭祴鏀介柣妯诲絻椤忣偄螖閺冣偓娣囧﹪濡堕崶顬儵鏌涚€ｎ偆娲寸€规洦鍨堕獮搴ㄦ寠婢光晪绠撻弻鐔兼偋閸喓鍑＄紓浣哄У婵炲﹪寮婚悢琛″亾濞戞瑯鐒介柣顓炵焸閺岋綁骞囬濠呭惈濠殿喖锕︾划顖炲箯閸涙潙宸濆┑鐘插€瑰▓妯荤節閻㈤潧浠╂い鏇熺矌缁骞樺畷鍥ㄦ濠电姴锕ら崰姘焽閳哄懏鍋ｅΔ锔藉椤忕娀鏌ㄥ☉姘灈婵﹥妞介幃鐑藉级鎼存挻瀵栫紓鍌欑贰閸ｎ噣宕归崼鏇炴槬婵炴垯鍨圭粻锝夋煟濡吋鏆╅柨娑欑箖缁绘稒娼忛崜褏袣闂佺顑呴崐鍧楃嵁鐎ｎ喗鍋愰弶鍫氭櫅婢ч箖姊绘担绛嬫綈妞ゆ梹鐗犲畷鏉款潩閸楃儐妫滄繝闈涘€搁幉锟犲磻閿濆鐓曢柕澶樺枙缁ㄥ鏌ｉ妸銉︽儓妞ゎ叀鍎婚¨鍌氣攽閳ヨ櫕鍠橀柛鈹惧亾濡炪倖甯婄欢锟犲疮韫囨稒鐓曢柣妯虹－婢х敻鏌嶉妷顖滅暤闁诡喗绮撻幐濠冨緞瀹€鈧弳顐︽⒒娓氣偓濞佳呮崲閸儱纾归柡宥庡幖绾惧鏌涘畝鈧崑娑氱不瑜版帒绾ч柛顐ｇ箓閳锋梻绱掓径妯烘珝闁哄矉绲介埥澶娾枎閹邦剛锛撴繝娈垮枛閿曘儱顪冩禒瀣疇闁跨喓濮村洿闂佸憡绋戦幏鎴犲緤娴犲绠掓繝鐢靛Т鑹岄柛瀣尵缁辨帡顢欓悾灞惧櫑闂佷紮绲介崲鏌ュ煘閹达箑鐐婇柕濞垮劚婵¤櫕淇婇悙顏勨偓銈夊储娴犲鍨傞柛顐ｆ礀閻ら箖鏌嶉崫鍕櫤闁抽攱鍨块弻娑㈡晜鐠囨彃绠归梺鍛婃煥椤戝寮婚悢铏圭煓闁割煈鍠掗幐鍐磽娓氬洤鏋ょ紒顕呭灦婵″爼鏁愭径濠勵槰闂佸啿鎼崯顐︾嵁閹邦兘鏀介柣姗嗗枛閻忚鲸绻涙径瀣创妞ゃ垺鐗犲畷銊р偓娑櫭埀顒€鐖奸弻宥夊传閸曨偀鍋撹ぐ鎺戠煑闊洦绋掗悡銉︾節闂堟稒顥為柟鍏煎姇闇夐柣妯款唺閹查箖鏌＄仦绯曞亾瀹曞洦娈曢柣搴秵閸撴盯鎯侀崼銉﹀€甸悷娆忓绾炬悂鏌涢弮鈧崹鍧楀Υ娴ｇ硶鏋庨柟鐐綑閳ь剟鏀遍妵鍕箳閸℃ぞ澹曢梻浣规偠閸斿繑銇旈崨濠勨攳濠电姴娲﹂崐閿嬨亜韫囨挸顏ら柛瀣崌楠炲鏁冮埀顒勫垂閸岀偞鐓曟繝闈涙椤忣偊鏌￠崱妤侇棦闁哄瞼鍠栧鑽も偓闈涘濡差噣姊洪崫鍕靛剮缂佽埖宀稿濠氭偄閸忚偐鍔烽梺鎸庢磵閸嬫挻顨ラ悙瀵稿⒈缂佽鲸甯″畷婊勬媴闂€鎰崟闂備礁鐤囬～澶愬垂閸ф绠栭柍鍝勬噹缁犵敻鏌熼悜妯肩畱闁诡噯绲介埞鎴︽偐閹颁礁鏅遍梺闈╃秵閸ㄨ泛顫忔禒瀣妞ゆ帒鍊甸弨铏節閻㈤潧孝婵炶绠撳畷鎰版煥鐎ｃ劋绨婚棅顐㈡处閹告悂顢旈妶澶嬬厱閻庯綆鍋呭畷宀€鈧鍠曠划娆撱€侀弴銏℃櫜闁糕剝锕╅崬鑸电節閻㈤潧啸闁轰礁鎲￠幈銊╁级閹炽劍妞介弫鍐磼濮樻唻绱梻浣侯潒閸曞灚鐣烽梺缁樻尪閸庣敻寮婚敓鐘茬闁靛绠戦ˇ鈺侇渻閵堝啫鍔氭い锔炬暬瀵鈽夐姀鐘栤晠鏌ㄩ弮鍌滄憘婵☆偄鍟村娲传閸曨厾浼囬梺鍝ュУ閹告儳危閹版澘绠虫俊銈傚亾妞ゎ偄鎳橀弻锝呂熼搹鐧哥礊婵炲瓨绮岄悥鐓庮潖缂佹ɑ濯撮柧蹇曟嚀缁楋繝姊虹憴鍕€愮紒鐘崇墪閻ｉ攱瀵奸弶鎴犵杸濡炪倖鎸炬慨顓㈠绩閾忣偆绡€闁汇垽娼у瓭濠电偞娼欓崐鍨嚕椤愩埄鍚嬮柛鈩冪懅椤旀洟姊洪悷閭﹀殶闁稿孩鍨剁粭鐔封槈閵忥紕鍘遍梺闈涚墕閹峰宕曢弮鈧幈銊︾節閸涱噮浠╃紓浣介哺鐢帟鐏掗梺鍏肩ゴ閺呪晠宕ョ€ｎ亖鏀介柣鎰皺閹界姷绱掗鑲┬ら柛鎺撳浮楠炴绮电涵鍛亾閸喓鈧帒顫濋敐鍛婵犳鍠栭敃銊モ枍閿濆洦顫曢柟鐑樺焾濞笺劑鏌涢埄鍐噧濠殿喚鍎ゆ穱濠囨倷椤忓嫧鍋撻弽顐ｆ殰婵°倕鎳忛崑鍌炴煥閻斿搫孝缂佺姷濞€閺岀喖骞戦幇顒傚帿閻庤娲栭ˇ鐢稿蓟閺囩喓绠鹃柛顭戝枤娴犲吋绻涚€涙鐭岄柛瀣尵閹广垹鈽夐姀鐘诲敹濠电娀娼ч悧鍛存惞鎼淬劍鈷戦柛婵嗗閸庢劙鏌ｉ埡濠傜仸鐎殿喖顭烽弫鎰緞婵犲倸鏁ら柣鐔哥矊椤戝鐣烽幋锕€顫呴柍鍨涙櫅娴滈箖鎮峰▎蹇擃仾缂佲偓閸愨晙绻嗛柣鎰閻瑧鈧鍣崑濠囩嵁濡偐纾兼俊顖濇〃濮规姊绘担钘変汗闁冲嘲鐗撳畷婊堝Ω瑜庨～鏇㈡煕濞嗗浚妲虹紒鈾€鍋撴繝鐢靛仜閻楀棝鎮樺┑瀣嚑闁绘柨鍚嬮悡銉︽叏濡潡鍝洪柛鐘冲姍閺屸剝寰勭€ｉ潧鍔屽┑鈥冲级閹倿骞婇敐澶婄疀妞ゆ挻绮堢花濠氭⒑閸濆嫭澶勬い銊ユ噺缁傚秵銈ｉ崘鈹炬嫼闂佸憡绻傜€氼噣鎮炵捄銊х＜闁哄被鍎抽悾鐑橆殽閻愬弶顥㈢€殿噮鍣ｅ畷鐓庘攽閹邦厾绉遍梻鍌欑閻ゅ洤顩奸妸鈺傚€块柨鏇楀亾闁宠绉撮埥澶愬閳锯偓閹风粯绻涙潏鍓у埌闁硅绻濋獮澶岀矙鎼存挻鏂€濡炪倖姊婚崑鎾诲汲閳哄啰纾兼い鏃傛櫕閹冲洦顨ラ悙鏉戠瑨閾绘牠鏌嶈閸撴稓鍒掓繝姘€烽柣鎴烆焽閸橆亝绻濋悽闈涗户闁稿鎸搁埢宥夊川閺夋垹鍊為梺鍦檸閸犳鍩涢幋锔界厱婵炴垶锕崝鐔兼煟椤撶偞顥犵紒杈ㄥ浮閸┾偓妞ゆ帊鐒︽刊瀵哥磼椤栨稒绀冮柣蹇庣椤啴濡堕崱妤€衼闂傚倸瀚€氫即宕哄☉銏犵闁挎梻鏅崢鍗炩攽閻愭潙鐏﹂柨鏇ㄥ亰瀵劎鎷犲顔惧數闁荤姴鎼幖顐︻敂椤撱垺鐓涢悘鐐插⒔閵嗘帡鏌嶈閸撱劎绱為崱娑樼；闁告洦鍊嬭ぐ鎺濇晩闂佹鍨版禍楣冩偡濞嗗繐顏痪鐐倐閺屾稒鎯旈姀鐘灆闂佺硶鏂侀崑鎾愁渻閵堝棗绗掗柨鏇缁棃鎮介崨濠勫幈闂佺粯蓱閸撴艾鈻撳鍫熺厵妞ゆ洖妫涚弧鈧悗娈垮枟閹告娊骞冮姀銈嗘優閻犲洠鈧櫕娅楅梻鍌氬€烽懗鍫曞箠閹剧粯鍋ら柕濞у嫬搴婇梺绋跨灱閸嬬偤宕电€ｎ喗鍋℃繛鍡楃箰椤忓瓨绻涢崼婊呯煓闁哄矉缍侀獮鍥敇閻斿嘲澹掓繝鐢靛仜閻楀﹦鍒掗幘璇茶摕闁炽儱纾弳鍡涙倵閿濆骸澧扮悮锕傛⒒娴ｈ姤銆冪紒鈧笟鈧畷鎰板锤濡も偓缁犵娀鏌ｉ幇顒佹儓閸烆垰顪冮妶鍡樷拻闁烩剝鏌ㄨ灋闁告劑鍔夐弨浠嬫煟濡澧柛鐔风箻閺屾盯鎮╁畷鍥р拰闂佽桨绀侀崯瀛樹繆閹间礁唯闁靛骏绱曢埀顒佹そ濮婃椽骞愭惔锝囩暤濠电偠顕滅粻鎾绘晲閻愬搫鍗抽柕蹇ョ磿閸樼敻姊虹紒妯虹仸闁挎碍绻涢崼銉х暫闁哄矉缍佸顒勫垂椤旇棄鈧垶姊洪幖鐐测偓鏇㈠疮閹绢喖钃熺€广儱顦导鐘绘煕閺囥劌浜濇繛鍫弮閺岋綁濮€閳轰胶浠柣銏╁灡椤ㄥ牓骞戦姀鐘斀閻庯綆鍋勬禒娲⒒閸屾氨澧涢柛鎺嗗亾闂佺粯鍔楅崕銈夋偂閺囥垺鐓忓┑鐐茬仢閸旀挳鏌ｉ幘鍐叉倯妞ゃ劊鍎甸幃娆戞嫚瑜戦崥顐⑽旈悩闈涗沪闁挎碍銇勯鐐村仴鐎规洜鍠栭、妤呭磼濡や緡娼旈梻浣稿⒔缁垶鎮ч悩璇茶摕婵炴垶菤濡插牓鏌涘Δ鍐ㄤ粶缂佺姴顭峰娲川婵炴碍鍨甸—鍐寠婢舵ɑ缍庨梺鎯х箺椤宕伴崱娑欑厱闁哄洢鍔屾禍鐐淬亜閿斿搫濡兼い顏勫暣婵″爼宕卞Ο鍨簴闂備礁鎲℃笟妤呭垂椤栨粎绠斿鑸靛姈閳锋垿鏌熺粙鎸庢崳缂佺姵鎸婚妵鍕晜閸喖绁梺璇″櫙缁绘繃淇婇悜钘夌厸闁稿本绮岄獮鎰版⒒娴ｈ鍋犻柛搴㈡そ閹繝宕煎┑鍐╃亖闂佸搫鍊归敍鏇㈡偡闁妇鍙嗛梺鍛婂姂閸斿骞愰崘顏嗙＝濞达絼绮欓崫娲煙缁嬫鐓兼鐐茬箻瀹曘劑寮堕幋鐙€鍞介梻浣烘嚀閹碱偆绮旈幘顔㈠顫濋懜纰樻嫽闂佺鏈悷銊╁礂瀹€鈧惀顏堫敇閻愰潧鐓熼悗瑙勬礃缁矂鍩為幋锕€閱囬柕蹇嬪灮閸橆垶姊绘担鍛婅础闁稿簺鍊濋妴鍐幢濞戞锛涢梺绋跨灱閸嬬喖宕ｉ幘缁樼厱闁靛绲芥俊鍧楁煃椤栨稒绀嬮柡宀嬬秮楠炴鈧稒顭囬ˇ銊╂⒑闂堟稒鎼愰悗姘嵆閻涱噣宕堕鈧粈鍫澝归敐鍥ㄥ殌濞寸姴婀辩槐鎾诲磼濞嗘帒鍘℃繝娈垮枤閺佸骞冭铻栭柛娑卞帣閿曞倹鐓曢柡鍥ュ妼閻忕娀宕鐐村仭婵犲﹤鍟版牎缂備礁鍊圭敮锟犲蓟閸℃鍚嬮柛鈩冪懃楠炴劙鏌ｆ惔鈥冲辅闁稿鎹囬幃妤呮晲鎼粹€愁潾閻炴熬闄勬穱濠囧Χ閸ヮ灝銉╂煕鐎ｎ剙浠ч柡渚囧櫍楠炴帒螖婵犲啯娅嶅┑鐘绘涧閸婂鈥﹂崼銉﹀€峰┑鐘叉处閻撳啴鏌涘┑鍡楊仼闁哄棙鐟﹂〃銉╂倷閸欏妫﹀┑顔硷工椤嘲鐣烽幒鎴旀瀻闁规惌鍘借ⅵ闂傚倷绀佸﹢閬嶅煕閸儱纾诲┑鐘插亞閸ゆ洟鏌ｉ姀鐘差棌闁轰礁妫濋弻娑氫沪閸撗呯厒闂佺粯鎸婚幑鍥ь潖閾忚鍠嗛柛鏇ㄥ亞椤︺劌顪冮妶鍡樿偁闁搞儯鍔岄埀顒€娼￠弻娑⑩€﹂幋婵呯按婵炲瓨绮嶇划鎾诲蓟閻斿吋鍊绘俊顖濇閸樻劙姊洪崨濠冣拻闁哥姵鎸惧Σ鎰板箳閹惧磭绐為梺褰掑亰閸樹粙鏌ㄩ銏♀拻闁搞儜灞拘х紓浣虹帛缁诲啰鎹㈠┑瀣＜婵炴垶蓱椤忕姴鈹戦悙宸殶濠殿喖绉瑰畷銊╊敍濠婃劗搴婂┑锛勫亼閸婃牕顫忔繝姘厱闁割偁鍎查崑鍌氣攽閸屾碍鍟為柣鎾寸懄閵囧嫰寮拠鎻掝瀳濠电偛鐪伴崐婵嬪蓟鐎ｎ喖鐐婇柕濞у懐妲囧┑鐘垫暩婵挳宕愯ぐ鎺戦棷濞寸姴顑嗛悡?"
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
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙绐涢梺鍝ュУ閹稿墽鍒掔紒妯稿亝闁告劏鏅濋崢浠嬫⒑闁稑宓嗘繛浣冲嫭娅犳い鏍仦閻撶喐绻濋棃娑欏缂佲偓鐎ｎ偅鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噧闁宠閰ｉ獮鍡氼槻濠㈣锚閳规垿鎮欓懠顒佹喖缂備緡鍠氭慨鐢电矉瀹ュ鏁傞柛鏇㈡涧濞堛劑鏌ｉ悩鍙夊缂佷焦娼欏嵄闁割偁鍎查悡蹇涚叓閸ャ劍绀€閸熸悂姊洪崨濠冣拹闁圭鍟块～蹇撁洪鍕獩婵犵數濮撮崐姝岊杺婵犵數鍋涢悺銊у垝瀹ュ鍋嬫俊銈呮噹缁犵偤鏌曟繛鐐珔闁绘劕锕ラ妵鍕箳瀹ュ牜鍞归梺鍦焿濞咃絿妲愰幘璇茬＜婵炲棙鍨垫俊浠嬫煢閸愵喕鎲鹃柟顔筋焾缁犳盯鏁愰崨顓犵潉闂備礁鎼張顒傜矙閹烘梹宕叉繝闈涱儏绾惧ジ鏌曢崼婵囨悙闁诡喗鍨垮缁樻媴閾忓箍鈧﹪鏌￠崒娆戠獢鐎规洘鍨块獮姗€骞囨担鐟扮槣闂備線娼ч悧鍡椢涘Δ鍛敜濠电姴娲﹂悡鏇㈡倵閿濆骸浜濋悘蹇曟暩缁辨帗娼忛妸銉﹁癁闂佽鍠掗弲鐘诲箠閻樻椿鏁勬い鎰閹冲宕戦幘鑸靛枂闁告洦鍓涢ˇ銊モ攽閻愯泛鐨洪柛鐘查叄閹箖鎮滈懞銉︽闂佺粯锚閸熷潡鍩€椤掆偓婢у海妲愰幘瀛樺闁兼祴鍓濋崹鎸庝繆闂堟稈鏀介柛鈥崇箲閺傗偓闂備胶鍋ㄩ崕杈╁椤撱垹鏄ラ柨婵嗘礌閸嬫挾鎲撮崟顒傤槬閻庤娲﹂崜鐔煎春閵忊剝鍎熼柍顓滃劤閸犳牠骞婇敓鐘参ч柛鎰╁妺閼割亝绻濋悽闈浶ユい锝庡枤濡叉劙寮撮姀鐘碉紱闂佺鎻粻鎴犲瑜版帗鐓涚€广儱楠搁獮妤呮煕鐎ｎ亶鍎愬ǎ鍥э躬婵″爼宕ㄩ鍏碱仩闂備礁鎼€氥劑宕曢悽绋胯摕婵炴垯鍨圭粻娑㈡煃鏉炴壆顦︽い銉ヮ儔濮婃椽骞愭惔锝囩暤濡炪倧瀵岄崹鍫曞蓟鐎ｎ喖鐐婃い鎺嶈兌閸橆亝绻濋姀锝呯厫缂佸鍨块妴鍛搭敆閸曨剛鍘卞┑鈽嗗灠閸氬寮抽浣瑰弿濠电姴鎳忛鐘绘煙妞嬪骸鈻堥柛銊﹀劤閻ｇ兘宕堕敐鍛婵犵數濮电喊宥夋偂閺囩喓绡€濠电姴鍊搁弳娆撴煛閸℃瑥鏋旂紒杈ㄥ浮閸┾偓妞ゆ帊鑳剁弧鈧梺鎼炲劘閸斿骞忓ú顏呪拺闁告稑锕︾粻鎾绘倵濮樼厧鏋﹂柍顏嗘暬濮婄粯绗熼埀顒勫焵椤掑倸浠滈柤娲诲灡閺呭爼顢涢悙瀵稿幐闁诲函缍嗘禍妤呭磻閵忊懇鍋撳▓鍨灁闁告柨绉剁划瀣箳閺傚搫浜鹃柨婵嗛娴滅偤鏌涘Ο缁樺磳婵﹥妞藉Λ鍐ㄢ槈鏉堛剱銈夋⒑缁嬪潡鍙勫ù婊嗘硾椤曪綁鎼归锝囩Ф闂佸啿鎼崯浼存晬濠婂牊鈷戠紓浣诡焽閹冲嫰鏌ｉ悢鏉戝姎閻撱倝鏌ㄩ弴鐐测偓褰掑磻閸屾稓绠鹃柛鈩兠慨鍌毭瑰鍕煉闁哄矉绻濆畷姗€濡搁妷銏犱壕闁告縿鍎查弳婊堟煕椤愶絾绀冮柣鎾冲暟閹茬顭ㄩ崼婵堫槶濠电偛妫楀ù姘舵倿娴犲鐓ラ柣鏂挎惈瀛濈紓浣哄У閻楁洟婀侀梺绋跨箰閸氬宕曞Δ鍛厸濞达綁娼婚煬顒勬煛鐏炶鈧繈鐛笟鈧獮鎺楀箣濠靛棭娼涢梻鍌欑閹诧繝寮婚妸鈺佺疇婵☆垯璀﹀鏍ㄧ箾瀹割喕绨兼い銉ョ墛缁绘盯骞嬮悙瀵告闂佹眹鍊曠€氭澘顫忓ú顏勭闁绘劖褰冮‖鍫濐渻閵堝骸骞橀柛蹇旓耿閻涱噣宕卞Ο鑲╂嚌闂侀€炲苯澧柣锝夋敱缁虹晫绮欑拠淇卞姂閺屻劑寮崶鑸电秷闁诲孩淇洪崑鎰閹捐纾兼繛鍡樺焾濡差喖顪冮妶鍡楃仴婵☆偅鐩崺鈧い鎺戝€婚幊妤呮煕閹邦垰鍔甸柍褜鍓欏锟犲蓟閻斿皝鏋旈柛顭戝枟閻忔挸鈹戦埥鍡椾航闁搞劌鐖煎濠氬焺閸愩劎绐為柟鍏肩暘閸ㄥ濡存繝鍥ㄧ厸濞达絽鎽滄晶锕傛煙椤旂瓔娈旈柍缁樻崌瀹曞綊顢欓悾灞奸偗闂傚倷鑳堕、濠囶敋濠婂懏宕叉繝闈涙矗缁诲棝鏌涢锝嗙闁哄懏褰冮…璺ㄦ崉閻氭潙濮涘銈忚礋閸旀垵顫忓ú顏勭闁告瑥顦崇涵鈧梻浣侯焾椤戝棝骞愭ィ鍐ㄧ劦妞ゆ帊娴囨竟姗€鏌曢崼銏╃劸妞ゎ偄绻掔槐鎺懳熺拠宸偓鎾绘⒑閸涘﹦绠撻悗姘煎墯缁傛帒螣娓氼垱瀵岄梺闈涚墕妤犲憡绂嶅┑鍥╃闁肩⒈鍓欓弸搴ㄦ煟閿濆洤鍘存鐐叉喘瀵爼宕归鑲┿偖闂傚倷鑳剁划顖炲蓟瑜忛幏鍐晝閳ь剟婀侀梺鍛婃处閸嬧偓闁衡偓娴犲鐓熸俊顖涱儥閸ゅ鈧鎮堕崕鐢稿箖濡も偓椤繈姊荤€靛憡鏅奸梻浣烘嚀缁犲秹宕归挊澶屾殾闁告鍊ｉ悢鍏尖拹闁归偊鍠氬▔鍧楁⒒閸屾瑦绁版い顐㈩槸椤灝螣缂佹ɑ鐝烽柟鍏肩暘閸斿瞼绮婚弽褉鏀介柛灞剧閸熺偤鏌ｉ幘璺烘瀾闁靛洤瀚伴獮妯兼崉閻戞鈧崵绱撴担璇℃畷鐎光偓閹间礁钃熼柡鍥ュ灩閻愬﹦鎲稿澶樻晜妞ゆ挾鍋愰弨鑺ャ亜閺冨倹鍤€濞存粓绠栧缁樻媴閸濆嫪缂撻梺绋块叄娴滆泛鐣烽鐐查敜婵°倐鍋撶紒鐘虫そ閺岋綁濮€閻樺啿鏆堥梺鎶芥敱閸ㄥ湱妲愰幒妤婃晬婵炴垶鐟чˇ銊╂⒑閸濆嫷妲哥紓宥咃躬瀵鈽夐姀鐘殿啋闁诲酣娼ч幗婊堟偩閼测晝纾藉〒姘搐濞呮﹢鏌涘▎蹇撴殻妤犵偛鍟存慨鈧柕鍫濇娴滄鏌熼懝鐗堝涧缂佽弓绮欓崺鈧い鎺戝€告禒杈ㄦ叏婵犲懏顏犻柍褜鍓欏﹢杈ㄦ叏閻㈢违闁告劦浜炵壕濂告煃瑜滈崜姘跺箯閸涘瓨鍊绘慨妤€妫楁禒鐑樹繆閻愵亜鈧牠骞愰崼鏇炲瀭婵炲樊浜滈悡鏇㈡煙閻戞﹩娈曢柣鎾存礋閹﹢鎮欓幓鎺嗘寖闂佺懓鍟垮Λ婵嬪蓟濞戞粎鐤€闁规儳鐡ㄩ幏閬嶆⒑闂堟稒鎼愰悗姘嵆閵嗕礁顫滈埀顒勫箖濞嗘挻顥堟繛鎴炲笒瀵板秹姊虹拠鎻掝劉妞ゆ梹鐗犲畷鏉款潩鐠虹儤鐎繝鐢靛У閸濆酣鍩€椤戣法顦﹂摶鏍煕濞戝崬骞樻い锔芥緲椤啴濡堕崱妤€娼戦梺绋款儐閹告悂婀侀梺缁樼憿閸嬫捇鏌涘▎蹇撴殭妞ゎ偄绻愮叅妞ゅ繐鎷嬪Λ鍐ㄢ攽閻愭潙鐏卞瀵割焾閻☆參姊婚崒娆戭槮闁圭⒈鍋婇獮濠呯疀閺囩偛鐏婇梺瑙勫劤绾绢參寮抽敃鍌涚厸闁搞儮鏅涢弸鏃傜磼閳锯偓閸嬫捇姊绘担瑙勫仩闁稿寒鍨跺畷婵囨償閵娿儱鍋嶅銈呯箰閹虫劗寮ч埀顒勬⒑濮瑰洤鐏叉繛浣冲嫮顩风憸鏃堝蓟濞戞埃鍋撻敐搴′簼閻忓浚鍙冮弻宥囨嫚閼碱儷褏鈧娲栧畷顒勫煡婢跺ň鏋庨柟瀛樼箓缁犳椽姊婚崒娆愮グ妞ゎ偄顦靛畷鏇㈠礃閼碱剚娈惧銈嗗笒鐎氼剛绮堟径瀣瘈濠电姴鍊归崳鐣岀棯閹规劕浜圭紒杈ㄦ尰閹峰懐鎷犻敍鍕Ш婵犵數鍋炶ぐ鍐偤閵娾斂鈧啴濡烽埡鍌氣偓椋庘偓鐟板閸犳牠宕滈崼鏇熲拺閻犲洠鈧櫕鐏嶇紓渚囧枟閹告悂鎮鹃悜钘夌闁绘劏鏅滈悗濠氭椤愩垺澶勯柟绋垮暣婵℃悂鍩￠崒妤佸闂備胶顭堥張顒勬偡閵娾晛绀傜€光偓閳ь剛妲愰幒妤婃晪闁告侗鍘炬禒顖炴⒑鏉炴壆璐伴柛锝忕秮楠炲啫鈻庨幘鍏呯炊闂佸憡娲﹂崣搴∥ｉ娑氱瘈婵炲牆鐏濋弸鐔兼煏閸ャ劎娲寸€规洘鍨块獮姗€宕瑰☉妯瑰濠电偛鐗嗛悘婵嬪几閿斿浜滈柡鍥ф濞村倿寮崶褉鏀介柛灞剧矤閻掗箖姊洪崡鐐村闁靛洤瀚伴獮鍥礈娴ｇ洅锝夋⒑闁偛鑻晶顔界箾瀹割喖骞栨い顐㈢箳缁辨帒螣鐠囧樊鈧捇姊洪崨濠勨槈闁挎洏鍊濆鎶藉醇閵夛腹鎷洪梺闈╁瘜閸欏酣鎮為悙顑句簻妞ゆ挾濮撮崢瀛橆殽閻愭彃鏆ｉ柟顔界矒閹稿﹥寰勭仦钘夌婵犵數鍋為幐濠氭嚌閹灐娲Χ閸涱亝鐏侀梺闈浥堥弲婊堝煕閹寸偞鍙忛柣鐔哄閹兼劙鏌ｈ箛濠冩珔妞ゎ厼娼￠幃椋庢暜椤斿灝鎯堥柣搴㈩問閸ｎ噣宕戞繝鍌滄殾闁告鍋愬Σ鍫熺箾閸℃ê鐏ラ悽顖涱殜閺岋綁鎮㈤崫銉х厑缂備緡鍠楅幐鎼佹偩瀹勯偊鐓ラ柛鎰剁稻閻庡妫呴銏″婵炲弶锚閳绘挻绺介崨濞炬嫼闂佸憡绋戦敃銉﹀緞閸曨垱鐓曢柕濞炬櫃閹查箖鏌涢埡鍌滄创妤犵偛顑夐弫鍌炴偩鐏炶棄绠炲┑鐘垫暩閸嬬偤宕归崼鏇熸櫇妞ゆ劧绠戠粈澶愭煟閺冨洦顏犵痪鍙ョ矙閺屾稓浠﹂崜褉妲堥梺鍛婄箖濡炰粙寮婚敍鍕勃闁告挆鈧慨鍥⒑鐠団€崇仭婵☆偄鍟村畷褰掑箚瑜忛弳锕傛煕閵夘喖澧扮€规洘绮撳濠氬磼濞嗘埈妲梺纭咁嚋缁辨洟寮鈧獮鎺懳旀担瑙勭彇闂備線娼ч敍蹇涘川椤栨凹妲辨繝鐢靛仜椤曨厽鎱ㄩ幘顕呮晞闁告侗鍙庨崯鍛節闂堟稒顥戦柡鈧禒瀣厽婵☆垵顕х徊缁樸亜韫囧﹥娅婇柟顔荤矙椤㈡稑鈽夋潏銊ф澒婵犳鍠栭敃銉ヮ渻娴犲绠犻柨鐔哄Т鍥撮梺鍛婁緱閸撴岸宕熼崘顏嗙＝闁稿本鐟чˇ锔姐亜閹存繃鍤囬柟顔ㄥ洤绠婚悹鍥у级濡差剟姊洪柅鐐茶嫰婢ь垶鏌曢崶褍顏鐐村浮瀹曞崬顪冮幆褜妫滈梻鍌氬€风粈渚€骞夐檱閹筋偊姊虹紒姗嗘畷妞ゃ劌鐗忛崚鎺楀煛閸涱喖浜滈梺缁樻尭妤犵鐣甸崱娑欌拺缂備焦锕╅悞浠嬫煛娴ｈ鍊愰柡浣哥Т閳规垹鈧綆鍋€閹疯櫣绱撴担鍓插剱閻庣瑳鍐胯€垮ù鐓庣摠閻撶姷鎲搁悧鍫濈闁伙絾妞介弻娑㈠煘閹傚濠碉紕鍋戦崐鏍ь啅婵犳艾纾婚柟鍓х帛閻撴瑩鏌ら幁鎺戝姢闁活厼鐭傞弻娑㈠箳閹捐櫕璇為悗娈垮櫘閸ｏ絽鐣锋總鍛婂亜闁炬艾鍊荤槐锕傛⒒閸屾瑧顦﹂柟璇х磿缁瑩骞嬮敂鑺ユ珖闂侀潧顦崕顕€寮稿澶嬬厱闁靛鍠栨晶顖炴煃闁垮鐏存慨濠傤煼瀹曞ジ鎮㈤幁鎺嗗亾閹烘梻纾奸柣姗€娼ф禒閬嶆煛鐏炲墽鈯曠紒缁樼箞瀹曟﹢鍩￠崘鐐ょ紓鍌氬€风欢锟犲窗閺嶎厸鈧箓鎮滈挊澶岀暫闂佸啿鎼幊搴ｇ矆閸岀偞鐓曟繛鎴濆船閻忥綁鏌ｉ敐澶岀暫婵﹦绮粭鐔煎焵椤掆偓椤洩顦归柟顔ㄥ洤骞㈡繛鎴烆焽閻ゅ洭妫呴銏″缂佸鍨垮濠氼敍濞戞氨顔曢悗鐟板閸犳洜鑺辨總鍛婄厽闁规儳鐡ㄧ粈瀣煛鐏炵偓绀嬬€规洜鍘ч埞鎴﹀炊瑜庨銈夋⒑鏉炴壆顦﹂柣妤佹尭椤繐煤椤忓嫪绱堕梺鍛婃处閸撴岸骞忛崡鐐╂斀闁绘劖褰冪痪褔鏌ㄥ顓滀簻闁哄洦锚閸旓妇鈧娲滈崰鏍€佸☉姗嗘僵閻犺櫣鍎ら弳顏勨攽閻樺灚鏆╁┑鐐╁亾濠电偘鍖犻崗鐐☉铻栭柛姘虫椤︻垶鍩㈡惔銊ョ缂侇喛顫夌€氳棄鈹戦悙鑸靛涧缂佹彃娼￠垾锕傚醇閵夈儲杈堥梻渚囧墮缁夌敻鎮″▎鎴犳／闁哄鐏濋懜鐟懊瑰鍛暭妞ゃ劊鍎甸幃娆戞嫚瑜旂欢瀵哥磽娴ｅ搫校缂佸鍨块崺銉﹀緞婵炪垻鍠撳☉鍨槹鎼绰も偓鍧楁⒒閸屾艾鈧兘鎮為敃鍌氬嚑濠靛倻顭堥悿鐐箾閹存瑥鐏╅柣銈庡櫍閺岀喎鈻撻崹顔界亾婵炴垶鎸哥粔纾嬬亙闂佹寧绻傞幊搴ㄥ汲閻愮儤鐓熼柟鎯х摠缁€瀣煛鐏炵晫效闁糕斁鍓濋幏鍛村川婵犲嫪澹曞┑鐘垫暩閸嬫盯鎮ф繝鍥ｂ偓锕傚炊閳哄偆娼熼梺鍦劋椤ㄥ棝宕戦幇鐗堚拻闁割偆鍠嶇欢閬嶆煛閸♀晛寮慨濠冩そ濡啫鈽夊▎鎰€烽梺璇插閸戝綊宕瑰畷鍥у灊閻犲洦绁村Σ鍫熺箾閸℃ê鐏╅柣锕€鐗撳娲川婵犲倸顫呴梺鍝勬噺缁诲棝濡甸幇顔瑰亾閿濆骸鏋熼柍閿嬪笒闇夐柨婵嗘噺閸熺偤鏌熼姘卞ⅵ闁哄矉绻濆畷濂割敃閵忕姭鎷梻浣筋嚃閸ㄦ壆鈧矮鍗抽妴浣糕槈閵忊€斥偓鐑芥煠绾板崬鍘哥紒杈ㄧ矒濮婄粯鎷呴悷閭﹀殝濠电偛寮堕悧鐘茬暦閹版澘浼犻柕澹倻鐟濋梻浣瑰缁诲倸螞濞戞艾濮柍褜鍓熷濠氬磼濮樺崬顤€缂備礁顑嗛幐濠氬疾閸洖绫嶉柍褜鍓氱粚杈ㄧ節閸嬭姤姊归幏鍛存偡閹殿噮鏆￠梻鍌欑閻ゅ洭锝炴径鎰瀭闁秆勵殔缁犳牠鏌嶆潪鎷岊唹闁哄妫冮弻鐔虹矙閸噮鍔夐梺浼欓檮缁挸顫忕紒妯肩懝闁逞屽墴閸┾偓妞ゆ帒鍊告禒婊堟煠濞茶鐏￠柡鍛埣椤㈡瑩宕滆閿涘繒绱撻崒娆撴闁搞劎鎳撻锝夘敊缁涘顔旈梺缁樺姈閹苯鈻撳鍫熺厵妞ゆ棁顫夊▍鍥╃磼鏉堛劌绗掗摶锝夋煟閹炬娊顎楃紒鐘劦濮婅櫣鎷犻崣澶嬪闯闂佺娅曢幐楣冨焵椤掍礁鍤柛鐘愁殜瀵尙鎹勬担鏇熸瀹曘劑顢橀姀鈽呯船闂佽崵鍠愮划搴㈡櫠濡ゅ啯鏆滄俊銈呮噺閸嬪倿鏌ｉ弬鍨倯闁绘挶鍎茬换婵嬫濞戞瑯妫ょ紓浣哄Т绾绢厾妲愰幒妤€鐓㈤柍褜鍓熷畷鎴﹀箻缂佹ǚ鎷绘繛杈剧悼閻℃棃宕甸崘顔界厱闁绘洑绀佹禍鎵偓瑙勬礃閸庡ジ藝瑜版帗鐓曢柣鎰皺閸╋絾鎱ㄦ繝鍛仩缂佽鲸甯掕灒闁煎鍊曞鍐测攽閻橆喖鐏柟铏崌閺佸啴顢旈崟顓熸闂侀潧顦崕顕€寮告惔銊︾厵闁告挆鍠鏌熷畡閭︾吋婵﹨娅ｇ划娆撳箰鎼淬垺瀚抽梻浣哄帶缂嶅﹦绮婚弽顓炴槬闁逞屽墯閵囧嫰骞掗幋婵冨亾閹间礁鍌ㄩ柟缁㈠枟閻撴瑦銇勯弮鈧崕铏闁秵鐓涘ù锝囶焾閺嗭綁鏌涢埞鎯т壕婵＄偑鍊栫敮鎺斺偓姘€鍥х劦妞ゆ帊鐒﹂ˉ鍫⑩偓瑙勬礃閿曘垽銆佸▎鎰檮闁告稑锕ュ▓鏂库攽閻樿尙妫勯柡澶婄氨閸嬫捇骞囬弶璺紱闂佽鍎虫晶搴ｅ婵傚憡鐓欓梺顓ㄧ畱瀵偓绻涢崼鐔虹煉闁哄备鈧磭鏆嗛悗锝庡墰閻﹀牓鎮楃憴鍕闁绘牕銈稿畷娲晸閻樿尙鍔﹀銈嗗笒閸婂綊锝為弴鐘亾鐟欏嫭绀€婵炶绠撳畷浼村箛閻楀牏鍘藉┑掳鍊愰崑鎾绘煟濡も偓濡稓鍒掗銏犵婵°倓鑳堕崢浠嬫⒑瑜版帒浜伴柛鎾卞姂閻擃剟顢楅崟顒傚幐闁诲繒鍋熼弲顐ｆ櫏闁诲氦顫夊ú锕傚磻婵犲倻鏆﹂柣鏃傗拡閺佸啴鏌ㄥ┑鍡橈紞闁哥偞鐓″铏规嫚閸欏鏀銈庡亜椤︻垳鍙呴棅顐㈡处缁嬫垹澹曢崸妤佲拻闁割偆鍠嶇欢杈ㄧ箾閸忚偐澧甸柡灞熷棛鐤€闁瑰墽顥愮涵鈧紓浣哄亾閸庢娊宕ョ€ｎ偆鈹嶅┑鐘叉祩閺佸秵绻濋棃娑欘棞闁诡垳鍋ゅ娲川婵犲嫭鍣у┑鈽嗗亝缁诲倿锝炶箛鎾佹椽顢旈崟顐ょ崺濠电姷鏁告慨鎾箠鎼淬剫澶娾攽閸♀晜瀵岄梺闈涚墕濡鎮橀妷锔轰簻闁挎棁顕ч悘锕傛煙椤曗偓缁犳牠骞冨鍫熷癄濠㈣泛鐭堥崥鍛存⒒娴ｇ懓顕滄繛鎻掔Ч瀹曟垿骞樼紒妯煎幗闂佽鍎抽顓灻洪幘顔界厸閻忕偛澧介埥澶愭煃閽樺妯€鐎规洩绻濋幃娆戔偓鐢告櫜闁垶姊婚崒娆戠獢闁逞屽墰閸嬫盯鎳熼娑欐珷妞ゆ洍鍋撻柡宀嬬秮瀵€燁槹闁稿鍨婚埀顒侇問閸犳牠鈥﹂悜钘夋瀬闁归偊鍘肩欢鐐测攽閻樻彃顏柡澶婃啞娣囧﹪鎮欓鍕ㄥ亾閺嶎厽鍋嬫俊銈呭暟閻瑩鏌熼幑鎰靛殭鏉╂繈姊虹憴鍕棆濠⒀勵殜瀹曟垿鎮╅搹顐㈠伎濠殿喗顨呭Λ妤呯嵁閺嶎厽鐓曟繝闈涙处閵囨繈鏌＄仦绯曞亾瀹曞洦娈曢柣搴秵閸撴稖鎽梻鍌欐祰椤曟牠宕归崡鐐嶆盯宕橀埡鍌氬伎闂侀€炲苯澧撮柡灞炬礉缁犳稒绻濋崘鈺冨絾婵犵數鍋涢悧鍡欑礊婵犲洤钃熼柨婵嗩槹閸嬪嫰鏌涘┑鍕姢闁绘挷绀侀埞鎴︽偐椤旇偐浠鹃梺鎸庢磸閸ㄥ綊鎮鹃悜绛嬫晬闁绘劘灏欓鎺戭渻閵堝棙顥嗛柛瀣姈鐎佃偐鈧綆鍠楅埛鎴︽煙缁嬪灝顒㈢紒鈧埀顒勬⒑缁嬪尅鏀婚柟顔煎€垮濠氬Ω閳轰絼褔鏌涢埄鍐╃缂佺姵宀稿娲濞戞艾顣洪梺绋匡工閹诧紕绮嬪澶婄鐟滃繒澹曢挊澹濆綊鏁愰崨顔藉創闁哄稄绻濋幃妤呭礂婢跺﹣澹曢梻浣哥秺濡法绮堟笟鈧幏鎴︽偄閸忚偐鍘介梺鍝勫€藉▔鏇炩枔闁秵鐓涢悗锝庡亝椤ュ牓鏌＄仦鍓ф创闁炽儻绠撻獮瀣攽閸モ晙鎲鹃梻鍌欐祰椤曆呮崲閹达箑绠伴柛鎾楀嫷娼熼梺瑙勫礃椤曆呭閸忓吋鍙忔俊顖氭惈閼稿綊鏌嶉鍕粵缂佺粯绋撻埀顒佺⊕椤洭鎯屾繝鍥ㄧ厽闁哄稁鍋勭敮鑸点亜閺囶亞绋荤紒缁樼箓椤繈顢橀悢鍝ュ礁婵犵數濮伴崹鐓庘枖濞戙埄鏁勯柛娑卞枤椤╁弶绻濇繝鍌滃闁抽攱鍨块弻娑樷槈濮楀牆濮涚紓鍌氬€瑰畝鎼佸蓟濞戞瑦鍎熼柕蹇嬪灩瀵劑鎮楃憴鍕闁轰浇顕ч悾鐑藉箳閹搭厾鍙嗛梺鍛婁緱閸ㄧ晫妲愰崘娴嬫斀闁绘劘鍩栬ぐ褏绱掗煫顓犵煓妤犵偞鐗犻、鏇㈡晲閸パ€鍙為梻鍌氬€搁崐鐑芥嚄閸洖绠犻柟鎹愵嚙缁犵喖鏌ㄩ悢鍝勑㈢紒鐘崇墵閺屾稑鐣濋埀顒勫磻濞戞氨涓嶉柡宥庣仜閺冨牊鏅查柛娑卞幗濞堟煡姊虹粙鍖″伐妞ゎ厾鍏樺濠氭晝閳ь剝鐏掗梺缁樿壘椤曨厾绮堥崱娑欌拺闂傚牊鍗曢崼銉ョ柧婵犲﹤鐗婇崑鍌炴煏婢跺棙娅嗛柣鎾寸洴閺屾盯骞囬埡浣割瀴婵犮垼娉涚€氼參濡甸崟顖毼ㄩ柕澶樺枟閳诲牓姊洪崫鍕拱闁烩晩鍨伴锝夘敆閸曨偆顔囬柟鑲╄ˉ閸撴繈鎮剧紒妯肩瘈婵炲牆鐏濋弸娑㈡煥閺囨ê鍔氭い顏勫暣閹稿﹥绔熼埡鍌滄创鐎规洘锕㈡俊鎼佸閳藉棙缍屽┑鐘垫暩閸嬫稑螞濞嗘挸鏄ラ柛顐ｇ贩濞差亝鍤嬮柣銏㈡暩閻﹀牓姊哄Ч鍥х伈婵炰匠鍡忓彺闂傚倷鑳堕幊鎾诲疮閸啔娲敇閻愬灚娈鹃梺纭呮彧缁犳垹绮婚懡銈囩＝濞达綁顎囧璺虹婵炲樊浜濋埛鎴︽煕濞戞﹫鍔熼柍钘夘樀閺屻劑寮村Ο琛″亾濠靛绠栨慨妞诲亾闁轰焦鍔欏畷鍫曞煛閸愯法搴婂┑锛勫亼閸婃牕顫忔繝姘柧妞ゆ劧绠戠粻鐘绘煕閹般劍鏉哄ù婊勭矋閵囧嫰骞囬埡浣轰紕缂備胶濮惧畷鐢稿焵椤掑喚娼愭繛璇х畵瀹曟垶绻濋崒婊勬濠电娀娼ч鍛瑜版帗鐓熼柡鍌氱仢椤ュ繐霉閻橆偅娅婃慨濠冩そ閹兘寮堕幐骞晛顪冮妶鍡楃仴闁硅櫕锕㈤獮鍐┿偅閸愨晛鈧鏌﹀Ο渚Ш闁稿﹦鍋ゅ娲濞戣京鍙氶梻鍌氬鐎氫即銆侀弮鍫熸櫜濠㈣泛顑傞幏濠氭⒑缁嬫寧婀伴柤褰掔畺閸┾偓妞ゆ帒瀚峰Λ鎴犵磼椤旇偐澧涚紒妤冨枛閸┾偓妞ゆ帒瀚畵浣逛繆閵堝倸浜惧銈庡幑閸旀垵鐣烽悢纰辨晢闁逞屽墮椤曪綁宕稿Δ浣叉嫼濠殿喚鎳撳ú銈夋倶椤斿浜滄い鎾跺仧婢с垻绱掗鑲╁鐎垫澘瀚埀顒婄秵閸撴盯顢欓弴銏♀拺缂侇垱娲栨晶鏌ユ嫅闁秵鍊堕煫鍥风导闁垶鏌＄仦鐣屝ユい褌绶氶弻娑滅疀閺冨倶鈧帞绱掗鑲╁闁瑰嘲鎳橀幃鍓т沪閼测晞鍏掗梻鍌氬€搁崐椋庢濮樿泛鐒垫い鎺戝€告禒婊堟煠濞茶鐏￠柡鍛埣楠炴﹢顢欓悾灞藉笚闂備線娼чˇ浠嬪垂閹惰姤鍋╅梻鍫熺▓閺€浠嬫煃閳轰礁鏆為柛濠冨姍閺屾盯鍩為幆褍鈷夐梺鐟板槻閹冲繒绮悢纰辨晬婵炴潙鐖㈤崘锝嗘杸闂佹寧绋戠€氼剚绂嶆總鍛婄厱濠电姴鍟版晶鐢碘偓瑙勬礀缂嶅﹤鐣峰鍕闁圭粯甯婃竟鏇犵磽娴ｈ娈曠紒瀣灥鐓ら柕鍫濐槹閸ゅ鏌ｉ悢鐓庝喊闁绘柨妫濋弻銈夊箹娴ｈ閿繝娈垮枛閻楁捇寮诲澶嬬叆閻庯綆浜為悷銊╂⒒閸パ屾█闁哄被鍔岄埞鎴﹀幢濞嗗浚鏉告俊鐐€曠换鎺撶箾閳ь剟鏌熼鑽ょ煓妞ゃ垺绋戦埥澶婎潩椤撶偛鐏￠梻鍌欑閹碱偊寮甸鍕剮妞ゆ牗鍑归崵鏇熴亜閺囨浜鹃梺绯曟杹閸嬫挸顪冮妶鍡楃瑨閻庢凹鍙冨鎻掆攽鐎ｎ偆鍘棅顐㈡处濞叉牕鏆╅梻浣告惈濡挳姊介崟顓熷床婵炴垶锕╅崯鍛亜閺冨洤鍚归柣鈺侀叄濮婃椽宕ㄦ繝鍌氼潊闂佺顑嗛幑鍥蓟閿濆鍋勯柛婵勫劤閻撯偓缂傚倷鑳剁划顖炴晪濡炪倖娲╃紞渚€鐛惔銊﹀殟闁靛闄勯悵鏍⒒娴ｄ警鐒鹃柡鍫墰缁瑩骞樼拠鎻掑亶闂佹眹鍨归幉锟犲煕閹达附鍋ｉ柛銉岛閸嬫挸鐣烽崶锔炬暰濠电姷鏁告慨浼村垂濞差亖鈧箓宕奸妷锝傚亾閸岀偛閿ゆ俊銈勮閹风粯绻涙潏鍓хК婵炲拑绲块弫顔尖槈閵忥紕鍘靛┑顔界箓閼活垶宕ラ崷顓犵＜妞ゆ梻鏅幊鍥殽閻愬樊鍎旈柡浣稿€垮畷妤佸緞婵犱礁顥氶梻浣瑰濮婂宕戦幘宕囨殾濠㈣埖鍔栭悡蹇撯攽閻樿尙绠抽柣锝堜含閻ヮ亞绱掗姀鐘典桓濠殿喖锕ュ浠嬬嵁閸℃凹妲剧紓浣哄У婵炲﹪寮婚悢鍏兼優妞ゆ劧绲界壕鎶芥⒑闂堟稒顥滈柛濠傛憸閸欏懎顪冮妶鍛闁瑰啿顦甸獮蹇撁洪鍛嫼闂佸憡绋戦敃锕傚煡婢舵劖鐓ラ柡鍥崝锕傛煕閳哄倻娲存鐐叉喘閹囧醇閵忕姴姹查梻鍌欑閹碱偄煤閿曞倹鏅梻浣筋嚙缁绘浜稿▎鎾崇劦?")
        elif scenario == "concept_teaching":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙绐涢梺鍝ュУ閹稿墽鍒掔紒妯稿亝闁告劏鏅濋崢浠嬫⒑闁稑宓嗘繛浣冲嫭娅犳い鏍仦閻撶喐绻濋棃娑欏缂佲偓鐎ｎ偅鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噧闁宠閰ｉ獮鍡氼槻濠㈣锚閳规垿鎮欓懠顒佹喖缂備緡鍠氭慨鐢电矉瀹ュ鏁傞柛鏇㈡涧濞堛劑鏌ｉ悩鍙夊缂佷焦娼欏嵄闁割偁鍎查悡蹇涚叓閸ャ劍绀€閸熸悂姊洪崨濠冣拹闁圭鍟块～蹇撁洪鍕獩婵犵數濮撮崐姝岊杺婵犵數鍋涢悺銊у垝瀹ュ鍋嬫俊銈呮噹缁犵偤鏌曟繛鐐珔闁绘劕锕ラ妵鍕箳瀹ュ牜鍞归梺鍦焿濞咃絿妲愰幘璇茬＜婵炲棙鍨垫俊浠嬫煢閸愵喕鎲鹃柟顔筋焾缁犳盯鏁愰崨顓犵潉闂備礁鎼張顒傜矙閹烘梹宕叉繝闈涱儏绾惧ジ鏌曢崼婵囨悙闁诡喗鍨垮缁樻媴閾忓箍鈧﹪鏌￠崒娆戠獢鐎规洘鍨块獮姗€骞囨担鐟扮槣闂備線娼ч悧鍡椢涘Δ鍛敜濠电姴娲﹂悡鏇㈡倵閿濆骸浜濋悘蹇曟暩缁辨帗娼忛妸銉﹁癁闂佽鍠掗弲鐘诲箠閻樻椿鏁勬い鎰閹冲宕戦幘鑸靛枂闁告洦鍓涢ˇ銊モ攽閻愯泛鐨洪柛鐘查叄閹箖鎮滈懞銉︽闂佺粯锚閸熷潡鍩€椤掆偓婢у海妲愰幘瀛樺闁兼祴鍓濋崹鎸庝繆闂堟稈鏀介柛鈥崇箲閺傗偓闂備胶鍋ㄩ崕杈╁椤撱垹鏄ラ柨婵嗘礌閸嬫挾鎲撮崟顒傤槬閻庤娲﹂崜鐔煎春閵忊剝鍎熼柍顓滃劤閸犳牠骞婇敓鐘参ч柛鎰╁妺閼割亝绻濋悽闈浶ユい锝庡枤濡叉劙寮撮姀鐘碉紱闂佺鎻粻鎴犲瑜版帗鐓涚€广儱楠搁獮妤呮煕鐎ｎ亶鍎愬ǎ鍥э躬婵″爼宕ㄩ鍏碱仩闂備礁鎼€氥劑宕曢悽绋胯摕婵炴垯鍨圭粻娑㈡煃鏉炴壆顦︽い銉ヮ儔濮婃椽骞愭惔锝囩暤濡炪倧瀵岄崹鍫曞蓟鐎ｎ喖鐐婃い鎺嶈兌閸橆亝绻濋姀锝呯厫缂佸鍨块妴鍛搭敆閸曨剛鍘卞┑鈽嗗灠閸氬寮抽浣瑰弿濠电姴鎳忛鐘绘煙妞嬪骸鈻堥柛銊﹀劤閻ｇ兘宕堕敐鍛婵犵數濮电喊宥夋偂閺囩喓绡€濠电姴鍊搁弳娆撴煛閸℃瑥鏋旂紒杈ㄥ浮閸┾偓妞ゆ帊鑳剁弧鈧梺鎼炲劘閸斿骞忓ú顏呪拺闁告稑锕︾粻鎾绘倵濮樼厧鏋﹂柍顏嗘暬濮婄粯绗熼埀顒勫焵椤掑倸浠滈柤娲诲灡閺呭爼顢涢悙瀵稿幐闁诲函缍嗘禍妤呭磻閵忊懇鍋撳▓鍨灁闁告柨绉剁划瀣箳閺傚搫浜鹃柨婵嗛娴滅偤鏌涘Ο缁樺磳婵﹥妞藉Λ鍐ㄢ槈鏉堛剱銈夋⒑缁嬪潡鍙勫ù婊嗘硾椤曪綁鎼归锝囩Ф闂佸啿鎼崯浼存晬濠婂牊鈷戠紓浣诡焽閹冲嫰鏌ｉ悢鏉戝姎閻撱倝鏌ㄩ弴鐐测偓褰掑磻閸屾稓绠鹃柛鈩兠慨鍌毭瑰鍕煉闁哄矉绻濆畷姗€濡搁妷銏犱壕闁告縿鍎查弳婊堟煕椤愶絾绀冮柣鎾冲暟閹茬顭ㄩ崼婵堫槶濠电偛妫楀ù姘舵倿娴犲鐓ラ柣鏂挎惈鏍￠梺绋款儐钃遍柕鍥у瀵噣宕掑☉娆戝涧缂傚倷璁插褔宕戦幘缁樷拻濞达絼璀﹂悞鐐亜閹存繄澧涢柟渚垮姂婵″爼宕ㄩ崒娑氭创鐎规洘锕㈡俊姝岊槼婵炲牊鍎抽埞鎴﹀煡閸℃浠銈嗗灦閻熴儱宓勬繝闈涘€搁幉锟犲煕閹达附鐓曟繛鎴烇公閺€鑽ょ磼閳ь剟鍩€椤掑嫭鈷戦柛婵勫劚閺嬫垵顭块悷鐗堫棞閸楅亶鏌熼悧鍫熺凡缂佺姴顭烽幃褰掑炊椤忓嫮姣㈤梺鎸庣⊕缁矂鍩為幋锔藉€烽柛娆忣樈濡繝姊洪崷顓х劸妞ゎ厾鍏橀妴渚€骞樼拠鎻掑敤濡炪倖鎸鹃崯鍧楀箯濞差亝鈷戠痪顓炴噹娴滃綊鏌涚€ｎ偆鈯曞ǎ鍥э躬閹崇偤濡烽妶鍥╃暰闂備胶绮崝鏍ㄧ珶閸℃稒鍎楁繛鍡樻尰閻撶喐绻涢幋婵嗚埞婵炲懎绉堕埀顒侇問閸犳洜鍒掑▎鎾扁偓浣割潨閳ь剟骞冨▎鎾村仺闁割煈鍋呯欢顐︽⒒閸屾艾鈧兘鎳楅崜浣稿灊妞ゆ牜鍋戦埀顒€鍟村畷銊р偓娑櫭禍鍗炩攽閻樿宸ラ柛姘埥澶愬閻樿尙鐛╂俊鐐€栭幐鍡涘礋椤愩倖袙闂傚倸鍊风欢姘焽瑜旈幃褔宕卞銏＄☉铻栧ù锝囨嚀瀵潡姊虹粙璺ㄧ伇闁稿鍋ら幃锟犲即閵忥紕鍘繝鐢靛Т缁绘ê顬婇鈧弻鏇㈠炊閵娧呯暭闂侀€炲苯澧叉い顐㈩槸鐓ゆ俊顖欒閻斿棙淇婇婵囩《濞存粈绮欏缁樻媴閸濆嫬浠樺銈庡亝濞茬喎鐣烽幇顑╂棃宕担瑙勬珦闂備礁鎼ú銊╁窗閹惧墎涓嶅Δ锝呭暙缁狙囨煕椤愶絿绠撻柍閿嬫閺屾盯骞掑鍛ギ闂佸搫鏈惄顖炲箖閵忊槅妲归幖瀛樼箚濡炬悂姊虹紒妯诲蔼闁稿﹥绻堝濠氬Ω閳轰礁宓嗛梺缁樺姈缁佹挳宕戦幘璇蹭紶闁靛鍎哄Λ婊勭節閻㈤潧校缁炬澘绉归幃锟犲礃椤旂晫鍘卞┑鐘绘涧濡顢旈鍫熺厱闁挎繂妫欓妵婵嬫煛瀹€瀣М妤犵偞顭囬幑鍕倻濡棿閭梻鍌欑閹碱偊鎯夋總绋跨獥闁归偊鍠掗崑鎾存媴閸愩劋姹楅梺閫炲苯澧紒瀣笩閹筋偊姊绘担璇″劌闁告鏅幑銏犫攽鐎ｎ亞鍘遍梺閫炲苯澧寸€规洘甯掗～婵嬵敆閸屾ê浠忛梻鍌氬€风粈渚€骞栭锔藉殣妞ゆ牗绮庨惌鎾绘煕閹捐尙鍔嶆い顐ｆ礋閺岀喖鎮滃Ο鐑橆啎闂佺粯鏌ㄩ崥瀣吹閹烘鐓忛柛顐ｇ箓椤掋垻鎮敐鍡欑瘈缁炬澘顦辩壕鍧楁煕鐎ｎ偄鐏寸€规洘鍔欐俊鑸靛緞婵犲倸浜堕梻浣虹帛閹稿摜鈧灚甯￠幃鐐寸鐎ｎ偆鍙嗛梺缁樻煥閹碱偄鐡紓鍌欒兌婵攱鎱ㄩ悽鍨床婵犻潧娲ㄧ弧鈧梺绋挎湰缁矂路閳ь剟姊绘担渚劸妞ゆ垵鍟村畷婵嬪箣閿曗偓閽冪喖鏌ㄥ┑鍡╂Ц缂佺姵绋掗妵鍕箳閸℃ぞ澹曢梺姹囧焺閸剟宕濋幋锕€钃熸繛鎴炲焹閸嬫捇鏁愭惔鈥茬凹閻庤娲栭張顒勩€冮妷鈺傚€烽柡澶嬪灦鐠囩偤鎮楀▓鍨珮闁革綇绲介悾鐑藉箳閹搭厾鍙嗛梺褰掑亰閸犳牜鑺遍妷鈺傗拻闁稿本鑹鹃埀顒勵棑濞嗐垹顫濈捄铏瑰姦濡炪倖甯掗崐鍛婄濠婂牊鐓犳繛鑼额嚙閻忥繝鏌￠崨顓犲煟妞ゃ垺绋戦埞鍐箚瑜屾竟鏇㈡⒑閸撹尙鍘涢柛瀣噽濞嗐垽寮婚妷锕€鈧灚鎱ㄥ鍡椾簻鐎规挸妫濋弻锝呪槈閸楃偞鐝濋悗瑙勬礀閻栧ジ銆佸Δ浣哥窞閻庯綆鍋呴悵婵嬫⒒閸屾瑨鍏岀紒顕呭灥閹筋偊鎮峰鍕凡闁哥喐澹嗛崚鎺旂磼濡偐鐦堝┑顔斤供閸樻悂骞忔繝姘拺缂佸瀵у﹢浼存煟閻旀繂娉氶崶顒佹櫇闁稿本绋撻崢鐢电磼閻愵剚绶茬€规洦鍓氱粋宥嗗鐎涙ê鐧勫┑鐘绘涧椤戝棝鎮″▎鎰闁割偅绻勬禒銏ゆ煛鐎ｎ偅宕岄柡灞剧〒閳ь剨缍嗛崑鍛焊閻㈢數纾兼い鏇炴噹楠炴牠鏌嶉挊澶樻Ц閾伙綁鏌ｉ幋鐑嗙劷濞寸姴鐭傚缁樻媴缁嬫寧鍊┑鐘灪閿氭い顓炴喘閺佹捇鎮╅懠鑸垫啺闂備焦瀵х换鍌炲箟濮椻偓瀵噣宕煎┑鍫濆Е婵＄偑鍊栫敮鎺斺偓姘煎弮瀹曟垹鈧綆鍠楅悡鏇熺箾閹存繂鑸归柣蹇ョ磿閳ь剝顫夊ú姗€鎮￠敓鐘茶摕婵炴垯鍨归悞娲煕閹板吀绨村┑顔兼喘濮婅櫣绱掑Ο璇查瀺濠电偛寮堕…鍥箲閵忕姭妲堥柕蹇曞Т閼板灝鈹戞幊閸婃捇鎳楅崼鏇樷偓鍛村级鎼存挻鏂€闂佹枼鏅涢崯顐ゅ緤閼姐倗纾界€广儱鎷戦煬顒傗偓娈垮枦椤曆囧煡婢跺ň鏋庨柟瀵稿Х濡插洭姊绘担鍛婂暈闁告梹鍨垮畷婵嗙暆閸曞墎绋忛悗骞垮劚閹峰銆掓繝姘厪闁割偅绻傞弳娆忊攽閳╁啯鍊愰柡灞剧⊕閹棃鏁愰崱妯荤槗婵°倗濮烽崑娑㈠疮椤愶箑鐓濋幖娣妼缁犺崵鈧娲栧ù鍌炲船娴犲鈷掑ù锝呮啞鐠愶繝鏌涙惔娑樷偓妤呭箲閵忋倕纾兼繛鎴烆殘缁犳碍淇婇悙宸剰婵炴挳顥撴竟鏇熺鐎ｎ偆鍘遍柣蹇曞仜婢т粙骞婇崱娑欑厱闊洦鎸鹃悘杈╃磼鏉堛劌娴い銏″哺瀹曘劑顢橀悩鍗炲闂傚倷鑳堕幊鎾剁不瀹ュ鍨傞柦妯侯槺閺嗭箓鏌ｉ幘宕囧哺闁衡偓娴犲鐓曟い鎰╁€曢弸鎴炪亜閺冣偓濞叉鎹㈠┑鍡忔灁闁割煈鍠楅悘宥夋⒑闂堟稒澶勯柣鈺婂灠閻ｇ兘骞嬮敃鈧粻鑽ょ磽娴ｈ鐒介柛姗€娼ч—鍐Χ閸℃ǚ鎷婚梺鍝勬媼閸嬪﹪鐛繝鍥х倞闁靛绲肩花濠氭⒑闂堟稓绠氭俊鎻掓噹閳绘捇寮撮姀锛勫幍閻庣懓瀚晶妤呭吹閸ヮ剚鐓欐い鏃€鍎抽崢瀛橆殽閻愯尙效鐎规洘锕㈤悡顐︻敇閻戝棙顥￠梻鍌氬€烽懗鍓佸垝椤栫偛鍨傞柛蹇撳悑閸欏繘鏌曢崼婵愭Ц闁绘挻娲熼弻鐔兼倻濮楀棙鐣烽梺缁樻尰濞茬喖骞冨鈧幃娆撳级閹存繂袘闂備焦鎮堕崐銈夊礈閻旂厧钃熼柨婵嗩槸缁犲ジ鏌涢幇鈺佸闁冲嘲顑夊娲传閸曨剚鎷辩紓浣割儐閹瑰洭宕洪埀顒併亜閹烘埊鍔熺紒澶愭涧闇夋繝濠傚閻帗銇勯姀鈩冾棃闁糕晪绻濆畷銊╊敊闂傚鏆楅梻鍌欑窔濞佳囨偋閸℃あ娑欐償閵忋埄娲稿┑鐘诧工閻楀﹪鎮″▎鎾寸厵閻熸瑥瀚慨鍫㈢棯椤撱垻鐣洪柡灞剧洴楠炴鎷嬮搹顐㈡灓闂備礁鎼惌澶岀礊娓氣偓閻涱噣骞掑Δ鈧猾宥夋煃瑜滈崜娆撳煝瀹ュ鍗抽柕蹇ョ磿閸樼敻姊洪崨濠勬噧妞わ缚鍗冲畷鎰板箛椤旂懓浜炬繛鍫濈仢濞呮﹢鏌涢敐蹇曞埌闁伙綁鏀辩缓鐣岀矙濞嗙偓缍傞梻浣虹帛椤洭宕戦敐澶婄；濠电姴娲﹂埛鎺楁煕鐏炴儳鍤柣鎿冨墴閺屾稓鈧綆浜滈鈺呮偂閵堝鐓ラ柡鍌氱仢閳锋棃鏌ｉ鐔烘噰闁哄瞼鍠撻埀顒傛暩椤牆鏆╁┑鐐村灦閹稿摜绮旈悽绋课﹂柛鏇ㄥ灠閸愨偓濡炪倖鍔﹀鈧繛宀婁邯濮婅櫣绮欓崠鈥充紣闂佺粯鐗曢妶绋款嚕婵犳碍鏅插璺猴功閻も偓闂傚倷绶￠崣蹇涙⒔閸曨偒鐔嗛柟鍓х帛閳锋垿鏌涘┑鍕姎濞寸姍鍥ㄧ厱閹煎瓨绋戦埀顒佺箞閻涱噣宕奸妷銉庘晝鎲告惔銊ョ獥闁糕剝绋掗悡鏇㈡煛閸モ晛浠уù鐘崇洴閺岋綁濡堕崟顓фМ闂佸疇顫夐崹鍧椼€佸▎鎴炲厹闁绘垹鏅崣宥嗙節閻㈤潧浠滈柟閿嬪灩缁辩偞绗熼埀顒勬偘椤旇棄绶為柟閭﹀墰椤旀帒顪冮妶鍡橆梿闁稿鍔欒棟闁哄顑欏〒濠氭煏閸繃顥滃┑顔煎€块弻娑㈠Ω瑜滈弨鐗堛亜閿濆嫮鐭欐慨濠傤煼瀹曟帒顫濋钘変壕濡炲娴烽惌鍡椼€掑锝呬壕濡ょ姷鍋為〃鍛粹€﹂妸鈺侀唶婵犻潧鐗忓畷鍫曟⒑绾懎浜归悶娑栧劚鍗遍柛娑樼摠閸婂灝霉閻樺樊鍎愰柍閿嬫閺屾盯濡烽鐓庮潽闂佺瀛╅〃鍛扮亙闂佹寧绻傞幊搴ㄥ汲閻愮儤鐓冮梺鍨儏閻忔挳鏌＄仦鍓р槈闁宠棄顦～婊堝醇閻曚焦姣夌紓鍌氬€风粈渚€鎮ラ崗鑲╊洸闁割偅娲栭拑鐔哥箾閹存瑥鐏╃紒顐㈢Ч閺屽秷顧侀柛鎾跺枎閻ｇ兘寮撮悢娲缂備礁顑堥鎶芥晝閸屾稓鍘甸梺缁橆殔閻楀﹦娆㈤懠顒傜＜闁绘ê鍟块埢鏇㈡煛瀹€鈧崰鏍嵁閸℃凹妲婚柣銏╁灣婵炩偓闁哄备鍓濆鍕熼崫鍕潉婵犳鍠栭敃锔惧垝椤栫偛绠柛娑欐綑瀹告繂鈹戦悩鎻掆偓鐟扳枔濡　鏀介柣鎰摠鐏忔壆鐥弶璺ㄐч柕鍡楀暞缁绘繈宕掑鍕啎闁荤喐绮庢晶妤冩暜濡ゅ懏鍊块柤娴嬫杹閸嬫捇鐛崹顔煎闂佺娅曢崝娆撳极瀹ュ應妲堥柕蹇娾偓鍏呯敾婵犵數濮撮敃銈団偓姘煎弮閹繝濡烽敂杞扮盎濡炪倖鍔戦崹鑽ょ不婵犳碍鐓欓柣鎾虫捣缁夎櫣鈧娲滈崗姗€銆佸鈧幃顏堝川椤栨氨鍝庡┑鐘垫暩婵兘銆傞挊澹╋綁宕ㄩ弶鎴濈€梺瑙勫劶濡嫰宕掗妸褎鍠愰柡鍐ㄧ墛閺呮煡鏌ｉ幇閭︽澓婵℃彃澧界槐鎾存媴娴犲鎽甸梺瑙勭摃瀹曠數鍒掗銏″亜闁绘挸娴烽崐鐐烘偡濠婂啴鍙勯柟顔矫鍏煎緞鐎Ｑ勫闂備線娼荤€靛矂宕㈡禒瀣惞闁逞屽墮閳规垿鎮欓懠顒佸嬀闂佺锕ョ换鍫ュΥ娴ｅ壊娼╅柤绋跨仛濞呮粍绻濋姀锝嗙【妞ゆ垵鎳庨埢鎾诲Ψ閳哄倵鎷洪梻鍌氱墛缁嬫挻鏅堕弴銏″€垫慨妯煎帶瀵喚鈧娲滈崰鏍х暦濮椻偓椤㈡瑧鎲撮敐鍡楊伖婵犵數鍋炲娆撳触鐎ｎ喗鍋＄憸鏂跨暦濮橆厼顕遍悗娑欘焽閸樻悂姊洪崜鎻掍航闁稿瀚弲鍫曨敋閳ь剟寮诲鍥╃＜婵☆垵顕х壕鎶芥倵濞堝灝鏋熼柟姝屾珪閹便劑鍩€椤掑嫭鐓冮梺娆惧灠娴滈箖姊鸿ぐ鎺撴暠婵＄偠妫勯～蹇曠磼濡偐鎳濋梺鎼炲劀閸屾粍鏅奸梻鍌欒兌椤牓顢栭崱娑欏剮妞ゆ牜鍋涚粻鐘绘煟閺冨倵鎷￠柡浣哥У缁绘盯骞嬮悙鍨櫗闂佺粯绻傞崲鏌モ€旈崘顔嘉ч柛鈩冾焽閿涙洟姊虹粙娆惧剱闁圭懓娲濠氭晬閸曨亝鍕冮梺浼欑到閻濡堕崶鈺冿紲闁哄鐗勯崝宀€绮幒妤佹嚉闁挎繂顦伴崑锝夋煕閵夘喕绨婚柣銊︽そ閺屻劌鈽夊▎鎰瀺婵烇絽娲ら敃顏呬繆閸洖鐐婃い顒夊枔閸庣敻寮诲☉姘ｅ亾閿濆骸浜炴繛鎻掔摠閵囧嫰濮€閿涘嫬顫ч悗鍨緲鐎氫即鐛崶顒夋晢闁稿本绮嶅В鍥р攽閻樺灚鏆╅柛瀣☉铻炴繛鍡樻尭閸ㄥ倿鏌ｉ弮鍌氬付缁炬儳顭烽弻鐔煎礈瑜忕敮娑欍亜閵夈儳澧涚紒缁樼洴楠炲鎮欓崹顐㈡珬闂備礁鎽滄慨鐢稿礉濞嗘挸钃熼柕鍫濐槸閻顭跨捄楦垮闁冲嘲鑻埞鎴︻敊绾嘲浼愬銈庡幖閸㈡煡鎮鹃悜钘夌闁瑰瓨姊归悗濠氭⒑閻熼偊鍤熷┑顔煎槻閻ｇ兘宕ｆ径宀€鐦堥梺姹囧灲濞佳勭閳轰緡鐔嗛柣鐔稿婢ф洟鏌ｉ敐鍥у幋闁诡喚鏅划娆戞崉閵娿儱袝濠碉紕鍋戦崐鏍暜閹烘柡鍋撳鐓庡箹闁宠棄顦抽ˇ褰掓煛瀹€瀣М妞ゃ垺锕㈤幃娆徝圭€ｎ亙澹曢梺褰掓？閻掞箓宕戦埡鍛厽闁硅揪绲鹃ˉ澶嬨亜椤愩垺鍤囬柡灞炬礋瀹曠厧鈹戦崶鑸殿棧闂備浇鐨崘顭戜痪缂備胶绮换鍫熸叏閳ь剟鏌ㄥ┑鍡橆棤闁靛棙鍔曢埞鎴﹀煡閸℃ぞ绨奸梺鑽ゅ暱閺呯娀鐛崘銊庢棃鍩€椤掑倸寮叉俊鐐€曠换鎰板箠婢舵劕绠繛宸簼閳锋垿鏌涘☉姗堝姛缂佺姵鎹囬幃妤€顫濋悡搴＄睄閻庤娲樼敮鈩冧繆閹间礁鐓涢柛灞剧矊楠炲牓姊绘笟鈧褔鈥﹂銏♀挃闁告洦鍨版濠电娀娼ч鍡涙偂濞嗘劑浜滈柡鍐ｅ亾闁荤噦缍佸畷鎰旈崨顔间痪闂侀€炲苯澧柍瑙勫灴閹瑩寮堕幋鐘辨闂備浇宕甸崯娆撳炊瑜嶉崑宥夋⒒娓氬洤澧紒澶屾暬閸╂盯骞嬮敂鐣屽幐闂佺鏈敋闁告梹绮嶇换娑㈠川椤撶喎娈楅梺鍝勬湰閻╊垶骞冮妶鍡樺闁告縿鍎伴崠鏍磽閸屾瑧璐伴柛鐘崇墵閹囧箻瀹曞洦娈炬繝闈涘€搁幉锟犲磻閸曨厾纾介柛顐犲灩鍟搁梺鐑╂櫅闁帮絽顫忕紒妯诲闁荤喖鍋婇崵瀣攽閳藉棗浜楃紒鑸佃壘閻ｇ兘骞嬮敃鈧粻娑㈡煟濡も偓閻楀棙绂掓總鍛娾拺婵懓娲ら悘鈺呮煙鐠囇呯瘈闁诡喒鈧枼妲堥柕蹇娾偓鏂ュ亾閸洘鐓熼柟鎵濞懷兠瑰鍐ㄢ挃缂佽鲸甯￠崺鈧い鎺戝€甸崑鎾绘晲鎼粹€冲箣闂佺顑嗛幐楣冨箟閹绢喖绀嬫い鎺戝亞濡差剟姊绘担铏瑰笡闁绘娲熷畷銉р偓锝庡亞閳瑰秴鈹戦悩鍙夋悙缂佺姷鎳撻湁闁挎繂鐗嗛埀顑跨矙婵℃瓕顦抽柛鐘冲姉閳ь剙鍘滈崑鎾绘煕閺囥劌浜為柣锝嗘そ濮婃椽骞愭惔锝囩暤濡炪倧缂氶崡鎶藉春濞戙垹绠抽柟鐐藉妼缂嶅﹪寮幇鏉跨倞鐟滃秵淇婂ú顏呪拺闁硅偐鍋涢埀顒佸姍瀹曟垿骞樼紒妯锋嫽婵炶揪缍€椤宕戦悩缁樼厱闁靛鍔屾禍鐟懊瑰鍜佺劸闁宠閰ｉ獮瀣倻閸℃绋愰梻鍌欒兌缁垶宕濋弴銏╂晪妞ゆ挾濮存慨顒勬煃瑜滈崜鐔奉潖濞差亜宸濆┑鐘插€搁ˉ鍫ユ⒑閸涘﹣绶遍柛銊﹀▕瀵櫕瀵肩€涙ǚ鎷婚梺绋挎湰閼归箖鍩€椤掑嫷妫戠紒顔肩墛缁楃喖鍩€椤掑嫬绠栨俊顖濄€€閺€浠嬫倵閿濆懐浠涢柡鍛仱濮婅櫣鍖栭弴鐐测拤濡炪們鍔岀换妯虹暦閻㈢鍗抽柕蹇ョ磿閸樼敻姊虹拠鈥崇€婚悘鐐跺Г椤斿秶绱撻崒娆掑厡濠电偐鍋撶紓浣哄У閻楁洟顢氶敐澶婇唶闁哄洨鍋ら崬璺衡攽閻樼粯娑ф俊顐㈢焸楠炴劙宕橀瑙ｆ嫼闂佸憡绋戦敃銈囩箔濮橆厾绡€闁靛繆妲勯懓鍧楁煃閵夘垳鐣电€规洜顭堣灃濞达綁鏅查悽濠氭⒑濮瑰洤鐒洪柛銊ャ偢瀹曟澘鈽夐姀鐘盒曞銈嗗姧闂勫嫰宕愰悽鍛婂仭婵炲棗绻愰顏嗙磼閳ь剟宕奸妷锔惧幐婵炶揪绲块悺鏃堝吹濞嗘劑浜滈柡鍥朵簽缁夘喗顨ラ悙杈捐€挎い銏＄懅閸犲﹥娼忛妸褏袩闂傚倸鍊风欢姘焽瑜忛幑銏ゅ箳閹炬潙寮块柣搴ｆ暩椤牏娆㈤妶鍛斀闁稿本纰嶉崯鐐烘煃闁垮绗掗棁澶愭煥濠靛棛澧辨繛鍏煎姍閺屾稓鈧綆鍓欓埢鍫ユ煛鐏炲墽鈯曢柟顖涙婵偓闁靛繈鍨婚崢鎺戔攽閻愬樊鍤熷┑顖氼嚟缁骞樼拠鑼唶婵犵數濮撮崯顐ゆ閻愭祴鏀介柣妯诲絻椤掋垺銇勯妷銉уⅵ婵﹤顭峰畷鎺戭潩椤戣棄浜鹃柟闂寸绾惧綊鏌ｉ幋锝呅撻柛銈呭閺屾盯顢曢敐鍡欙紩闂侀€炲苯澧剧紒鐘虫尭閻ｉ攱绺界粙璇俱劍銇勯弮鍥撴繛鍛墦濮婄粯鎷呴搹骞库偓濠囨煕閹惧绠樼紒顔界懇楠炲鎮╅崗鍝ョ憹濠电偛顕崢褔鎮洪妸鈺傚亗闁绘ɑ绁撮弨鑺ャ亜閺冨洦顥夊┑顔兼喘閺屽秷顧侀柛鎾村哺閵嗗啴宕奸姀鐘茬亰婵犵數濮甸懝鍓х尵瀹ュ鐓曟い鎰╁€曢弸鏃堟煕濡湱鐭欐慨濠冩そ瀹曨偊宕熼锝嗩唲闂備胶顭堥敃銈夊箺濠婂牆鏋佹い鏇楀亾鐎规洖銈稿鎾偄閸濆嫬绠洪梻鍌欑濠€閬嶅磿閵堝鍨傞悷娆忓椤╅攱绻涢幋娆忕仾闁绘挸绻橀弻娑㈠Ψ閹存繂鏋ゅù鐓庡暙铻栭柣姗€娼ф禒锕傛偨椤栥倗绡€闁绘侗鍠氶埀顒婄秵娴滄牠寮ㄦ禒瀣厵闂侇叏缂氱花鑺ヤ繆椤愵偄鐏︽慨濠傤煼瀹曟帒鈻庨幒鎴濆腐婵＄偑鍊ら崢濂告偋閹炬眹鈧線寮介鐐茶€垮┑顔斤供閸樹粙宕虫搴ｇ＝闁稿本鑹鹃埀顒傚厴閹虫宕滄担绋跨亰濡炪倖鐗滈崑鐐哄磿鎼搭潿浜滈柡宥冨妽閻ㄦ垿鏌￠崱顓犵暤闁哄本绋戣灃闁告劑鍔夐崑鎾绘晲婢跺浜滈梺绋跨箰閸氬宕曢鍫熲拻濞撴艾娲ゆ禍婵堢磼鐎ｎ偄娴柕鍡曠椤粓鍩€椤掆偓椤繒绱掑Ο璇差€撶紓浣圭☉椤戝懎鈻撻銏＄厽閹兼番鍨婚埢鎾绘煛閸涱喚绠炵€规洜澧楃换婵嬪磼閵堝懏鍊┑鐘灱濞夋盯顢栭崨顓涙灁闁绘劗绻濈换鍡涙煏閸繄绠抽柛鎺嶅嵆閺屾盯鎮ゆ担鍝ヤ化缂備緡鍠栭…鐑界嵁閹烘嚦鏃€鎷呴崣澶婎伜婵犵數鍋犻幓顏嗗緤閸ф绠犻柟鐐た閺佸绻濇繝鍌涘櫧缁炬儳銈搁幃褰掑炊閵娿儳绁烽梺閫炲苯澧柟顔煎€搁敃銏＄瑹閳ь剙顫忛搹鍦煓閻犳亽鍔庢导鍥⒑缁嬫鍎戦柛瀣ㄥ€曢悾鐑藉箛閺夊潡鏁滃┑掳鍊撻懗鍫曞储闁秵鈷戦柛锔诲幖娴滅偓銇勯妸銉﹀櫧闁逞屽墯閸戝綊宕滃杈╃焿闁圭儤娲滈悿鈧┑鐐村灦閻熴垽骞忛搹鍦＝闁稿本鐟ч崝宥夋嫅闁秵鐓熼柟鎯у船閸旓箓鏌″畝鈧崰鏍箠閻愬搫唯鐟滃繘鎮￠崒婊呯＝濞撴艾娲ら弸銈囩磼椤曞懎鐏﹀┑鈥崇埣閺佹劖寰勬繝鍕垫О闂備線娼ц噹闁搞儮鏅涚粈鍫ユ⒒閸屾艾鈧绮堟担鍦彾濠电姴娲ょ壕濠氭煕濞戝崬鐏＄€规洘鐓￠弻娑樼暆閳ь剟宕戝☉銏″亗闁哄洢鍨洪悡娑㈡煕閹扳晛濡奸柍褜鍓濆畷鍨珶閺囩喓闄勯柛娑橈工閳ь剛鏁婚弻銊モ攽閸℃侗鈧顨ラ悙瀵稿⒌闁哄本绋戦～婵嬵敆娴ｇ晫顢呯紓鍌欐祰妞村摜鏁Δ鈧…鍥疀濞戞鈺呮煏婢舵稓鐣抽柣褌鐒︽穱濠囨倷椤忓嫧鍋撻幋锕€鍨傛繛宸簼閸嬶繝鏌ㄩ弬鍨挃缂佹唻绠戦湁闁绘ê妯婇崕蹇曠磼閳ь剟宕奸悢铏诡啎闂佸搫顦伴崺鍫ュ磿韫囨拋鐟邦煥閸涱厺澹曟繛锝呮搐閿曨亝淇婇崼鏇炲窛妞ゆ柨鍚嬮锟犳⒒娴ｈ櫣甯涢柟绋跨埣瀹曟洟鎮界粙鑳憰闂佽法鍠撴慨鎾倷婵犲啨浜滄い鎾跺剱閸庢稑霉濠婂簼閭鐐插暙椤粓鍩€椤掆偓椤曪絾绻濆顑┿劑鏌ㄩ弮鈧崕鎶界嵁閸儲鈷掑〒姘ｅ亾婵炰匠鍡楊杺闂備礁鎼幊蹇曟崲閸儱绠栧Δ锝呭暞閸婄粯鎱ㄥΔ鈧Λ娆擃敊閺冨牊鈷戠紓浣姑慨鍥┾偓娈垮枦閸╂牕顕ラ崟顖氱妞ゆ牗绋撻崢鐢告倵閻熸澘顏褎顨婂畷铏鐎ｎ偆鍘甸梺鍛婄懃椤︽壆浜搁敂閿亾鐟欏嫭绀堥柛鐘崇墵瀹曟椽鎮欓崫鍕暰閻熸粌鏈粩鐔煎即閵忊檧鎷洪梺鍛婄☉閿曘倖鎱ㄩ敃鍌涚厱闁绘ɑ鍓氬▓婊堟煕閳哄倻娲存鐐村浮楠炲﹪濡搁妷褏楔闂佽桨鐒﹂崝娆忕暦閸洖惟闁靛濡囬弳姘攽閿涘嫬浜奸柛濠冪墪鐓ゆ俊顖滃帶閸ㄦ繈骞栨潏鍓хɑ妞ゎ偅娲熼弻鐔兼倻濡儵鎷归柣搴㈢瀹€鎼佸蓟閻旇櫣纾兼俊顖氭惈濞兼垿姊虹粙娆惧剱闁圭懓娲ら悾椋庣矙鐠囩偓妫冮崺鈧い鎺戝€绘稉宥夋煛瀹ュ骸浜濋柛鐘冲姍閺岀喓鈧數顭堝暩婵炴垶鎸哥粔鐢垫崲濞戙垹绠ｆ繛鍡楃箳娴犲ジ姊洪崨濠庢畷濠电偛锕濠氭晲閸涘倻鍠愬鍕矙閹稿骸鍓甸梻鍌欐祰瀹曠敻宕伴幇顔藉床闁稿瞼鍋涢悡姗€鏌熺€电浠滅紒鐘靛█濮婅櫣绮欑壕鏇熺洴瀹曘劑顢橀悩鐢垫憣婵犵數鍋涢顓熸叏閹绢噮鏁勯柛娑樼摠閸嬵亝銇勯弬娆炬綗濞存粍绮撻弻鈥愁吋鎼粹€茬盎婵炲濮电划搴ㄦ儉椤忓牆绠氱憸婊堟偂婵傚憡鐓涢悘鐐额嚙婵″ジ鏌嶇憴鍕伌鐎规洖宕灒濞撴凹鍨辫ⅸ闂傚倸鍊风粈渚€骞楀鍕弿闁汇垻顭堢粈澶嬬箾閸℃ɑ灏柦鍐枛閺屻劑鎮㈤崫鍕戙垻绱掗埀顒勫礃椤旂晫鍘繝鐢靛€崘銊︾亾闂佸搫妫崑鍡欐閹捐纾兼慨姗嗗厴閸嬫挻顦版惔銏狀€涢梺鍝勮閸庨亶鎮挎ィ鍐╃厽婵☆垱顑欓崵娆撴煢閸愵亜鏋戠紒缁樼洴楠炲鎮滈崱娆忓П闂備礁鎼崯顐︽偋閸℃瑧鐭嗛柛鎰靛枟閻撳繐鈹戦悙鑼虎闁告梹纰嶉妵鍕Ψ閵夆晛寮板┑顔硷功缁垶骞忛崨瀛樻優闁荤喐澹嗛濂告⒑濮瑰洤鐒洪柛銊ゅ嵆閺佸啴鏁冮崒姘鳖槴闂佸湱鍎ら崹鐔煎几鎼淬劍鐓欓柟顖嗗懏鐎梺纭呭Г濞茬喎顫忓ú顏勭閹艰揪绲块悾闈涱渻閵堝繐鐦滈柛銊ョ埣閺佹劙鎮欓崫鍕獩闁诲孩绋掗…鍥储椤忓牊顥婃い鎰╁灪閹兼劙鏌ㄩ弴妯哄姎闁宠绉瑰畷鍫曨敆娴ｅ搫骞堥梻浣告惈閸熺娀宕戦幘缁樼厵妞ゆ梻鍘ч埀顒佹倐椤?")
        elif scenario == "idea_implementation":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙绐涢梺鍝ュУ閹稿墽鍒掔紒妯稿亝闁告劏鏅濋崢浠嬫⒑闁稑宓嗘繛浣冲嫭娅犳い鏍仦閻撶喐绻濋棃娑欏缂佲偓鐎ｎ偅鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噧闁宠閰ｉ獮鍡氼槻濠㈣锚閳规垿鎮欓懠顒佹喖缂備緡鍠氭慨鐢电矉瀹ュ鏁傞柛鏇㈡涧濞堛劑鏌ｉ悩鍙夊缂佷焦娼欏嵄闁割偁鍎查悡蹇涚叓閸ャ劍绀€閸熸悂姊洪崨濠冣拹闁圭鍟块～蹇撁洪鍕獩婵犵數濮撮崐姝岊杺婵犵數鍋涢悺銊у垝瀹ュ鍋嬮柡鍥╁仜缁侇偊姊绘担绋款棌闁稿绶氬畷褰掓嚒閵堝拋妫滈梺鑺ッˉ銏ｃ亹閹烘挻娅滈梺绯曞墲椤ㄥ牏绮婇柨瀣閻庢稒顭囬惌鎺旂磼閻樺磭澧い顐㈢箻閹煎綊宕烽鐘靛幆闂佽崵濮垫禍浠嬪礉鎼淬垹顕遍柛銉墯閳锋垹绱掔€ｎ偒鍎ラ柛搴㈠灴閺屾稓鈧絻鍔岄埀顒佺箞閻涱噣宕橀鑺ユ闂佺粯蓱瑜板啫鐣甸崱娑欌拺缂備焦蓱閳锋帞绱掔紒妯肩畼闁奸缚椴哥换婵嗩潩椤撴稒瀚奸梺鑽ゅ枑閻熴儳鈧凹鍘惧▎銏ゅ箵閹烘繄鍞甸悷婊冪Ч閺屽﹪鏁愭径灞界ウ闂佸憡鍔﹂崰妤呭吹閸愵喗鐓冮柛婵嗗閺嗙喖鏌ㄥ☉娆戠煉婵﹨娅ｇ槐鎺戭潨閸℃瑥濮兼繝鐢靛仜閹冲繐煤閺嶎厽鍋╃€瑰嫭澹嗛弳鍡涙煕閺囥劌澧伴柛妯绘倐閹宕楁径濠佸闂佽鍑界紞鍡涘礈濞戞壕鍙烘繝寰锋澘鈧鎱ㄩ悜钘夌；闁绘劕鐏氶弳婊堟煥閻斿搫啸鐎规挷绶氶幃妤呮晲鎼存繄鎸夐梺鍝勵儏闁帮綁鎮￠锕€鐐婄憸鏃堫敁濡ゅ懏鐓曢柕濠忓缁犵偞鎱ㄦ繝鍛仩闁归濞€楠炴捇骞掑┑鍡椢ㄥ┑锛勫亼閸婃牕顫忚ぐ鎺撳亱闁绘灏欓弳锕€霉閸忓吋缍戦柛鎰ㄥ亾婵＄偑鍊栭幐楣冨窗鎼淬垻顩叉い鏍ㄧ〒缁♀偓闂傚倸鐗婄粙鎴﹀焵椤掆偓椤兘鍨鹃敃鍌氶唶闁靛鍎卞鐑芥⒑闂堟侗妲撮柡鍛矒閹繝濡烽埡鍌滃幗闂佸搫鍊圭€笛囧箚閸懇鍋撳☉娆戠畼缂佽鲸鎸婚幏鍛村箵閹哄秴顥氶梻浣筋嚙閸戠晫绱為崱娑樼；濞达絽婀遍々鍙夌節婵犲倻澧涢柣鎾寸懇閺岋綁骞嬮悘娲讳邯閹偤鎮欓璺ㄧ畾闂佺厧銈搁·鍌氼焽閹扮増鐓忛柛銉戝喚浼冩繝纰夌磿閸忔ɑ淇婇悜绛嬫晩閻熸瑱绲鹃悗鏉库攽閻樻剚鍟忛柛鐘崇墵閺佸啴鏁傞幆褍鐏婂銈嗙墱閸嬫稓绮婚鐐寸厱婵炴垵宕▍妯讳繆閹绘帞绉烘鐐寸墱閳ь剚绋掗…鍥╃不濮橆厹浜滈柍鍝勶工娴滅偟绱掓潏銊﹀磳鐎规洘甯掗～婵嬵敄閽樺澹曢梺鍛婄缚閸庢娊鎯岄幘缁樼厸濠㈣泛顑呭▓鐐箾閹寸們姘跺绩娴犲鐓曢柍鈺佸暟閹冲嫭绻涢崼鐔峰姢闁宠鍨块幃鈺冩嫚瑜嶆导鎰版⒑缂佹﹩娈旈柨鏇ㄤ簻閻ｇ兘骞嬮敃鈧粈瀣亜閹邦喖鏋戦柡鍌楀亾闂傚倷鑳堕…鍫ュ嫉椤掑嫬绀勯柣鐔稿珗閿濆宸濆┑鐘插椤旀洟姊洪崜鎻掍簼缂佸鍨舵穱濠囧礂缁楄桨绨诲銈呯箰鐎氼剟寮抽敐鍛斀闁炽儱纾崺锝団偓瑙勬礀瀹曨剝鐏冮梺閫炲苯澧撮柨婵堝仱瀹曞爼顢楁担鍙夊缂傚倷绀侀鍛焊閸涙潙缁╁┑鐘崇閻撴洟鏌￠崘锝呬壕闂佽崵鍠嗛崕鐢稿箖妤ｅ啯鍊婚柦妯侯槺椤撴椽姊洪幐搴㈢５闁稿鎸剧槐鎺楁偐瀹割喚鍚嬮梺鍝勭焿缁绘繂鐣烽幒鎳崇喖宕崟顐渐濠碉紕鍋戦崐銈夊磻閸曨厾鐭撻柟缁㈠枛閻撴﹢鏌熸潏楣冩闁稿﹦鍏橀弻娑樷枎韫囷絾笑濠电偛鐗嗛懟顖炲煘閹达附鍊烽柛娆忣槸濞呫倕鈹戦悙璺虹毢闁哥姴閰ｉ幃楣冩偪椤栨ü姹楅梺鍦劋閸ㄥ潡寮鍐ｆ斀閹烘娊宕愰幇鏉跨；闁规儳澧庣壕濂告煟濡櫣锛嶅褏鏁婚弻锛勪沪閻ｅ睗褍鈹戦敍鍕幋闁轰礁鍊块幃鍓т沪閼测晝顦ㄩ梻鍌氬€风粈渚€骞栭锔绘晞闁告稑鐡ㄩ悡鈧梺鎸庣箓椤︻垶鎷戦悢鍏肩厽闁哄倸鐏濋幃鎴︽煟閹哄秶鐭欓柡灞诲姂瀵噣宕堕妸褋鈧﹪姊烘潪鎵妽闁绘绮庡Σ鎰板箻鐎涙ê顎撻梺鍛婄箓鐎氬懘鏁愭径瀣幘閻熸粎澧楃敮鐐烘偩濞差亝鐓曢柍鍝勫暙娴犺鲸顨ラ悙宸剶闁诡喗鐟╅幊鐘活敆閸屾稓鈧噣姊婚崒姘偓鐑芥嚄閸洍鈧箓宕奸妷锔芥珖闂侀潧顦弲娑氱矆婢跺绠鹃柛鈩冾殘缁犳娊鏌￠崱顓犵暤闁哄瞼鍠愬蹇涘礈瑜忛弳鐘电磽娴ｅ搫鞋鐎规洜鏁稿Σ鎰板箻鐎涙ê顎撻柣鐘叉祫缁辨洟宕濋悜鑺モ拺闁告稑顭悞鐐繆椤愩垹顏柛鈺冨仱楠炲鎮欓懠顒傛瀮闂傚倷鑳堕…鍫ユ晝閵夈儍娲偄妞嬪孩娈惧銈嗙墱閸庢劙寮崘顔界叆婵犻潧妫欑粊鈺傜箾閺夋垵顏柟顔煎槻椤劑宕橀…鎴濆Ψ缂傚倷绀侀惌浣广仈閸濄儲宕叉繝闈涱儏閻愬﹦鎲歌箛娑欏亗闁瑰鍋熺弧鈧梺闈涢獜缁插墽娑垫ィ鍐╃叆闁哄洦锚閳ь剚绻堥弫鎰版倷閼碱剚娈曢梺鍛婃处閸忔﹢骞忓ú顏呯厽閹肩补鍓濈拹鈥斥攽椤栵絽骞栨い顓炴喘楠炲洭鎮ч崼銏犲箞闂備線娼ч…鍫ュ磿瀹曞洨鐭撴繛宸簼閻撴洟鏌嶇憴鍕姢濞存粎鍋撴穱濠囨倷椤忓嫧鍋撻弽顐ｆ殰闁圭儤顨嗛弲婵嬫煥閺傚灝鈷旈柣顓熸崌濮婂宕奸悢鐑╁亾娴犲鍋￠梺顓ㄥ閸欏棝姊洪崨濠佺繁闁告ê鎼嵄闁规壆澧楅悡銏′繆椤栨繂鍚圭紒鐘筹耿閺岀喖宕ｆ径瀣偓鎰偓娈垮櫘閸撴瑩鍩㈡惔銊﹀€锋い鎺戝€婚埢澶娾攽閻樺灚鏆╅柛瀣☉铻ｅ┑鐘插暟椤╁弶绻濇繝鍌涘櫧闁活厼妫濋弻娑㈩敃閻樻彃濮曢梺缁樻尰閻熝呮閹惧瓨濯村┑顔藉焾娴滅偟鍒掗銏犵＜婵犲﹤鎳愰敍婊堟⒑闂堟侗鐒鹃柛濠冾殜閹苯鈻庨幇顓炲伎婵犵數濮撮崯顖炲Φ濠靛牃鍋撶憴鍕闁稿锕ユ穱濠囨倻閽樺）銊╂煙閹佃櫕娅呴柣蹇旂叀閺岀喖顢欑粵瀣暥闂佸疇妫勯ˇ鐢哥嵁閹烘绠婚悗鐢殿焾缂嶅啴姊虹拠鍙夊攭妞ゎ偄顦叅婵☆垰銈藉ú顏呭亜缂佹銆€閸嬫挻绗熼埀顒€顕ｉ幘顔碱潊闁绘ɑ鐖犻崶銊у幈闂侀潧顦崹鍝勨枍閺冨倻纾奸弶鍫涘妼閳绘洘鎱ㄦ繝鍕笡闁瑰嘲鎳忕粭鐔碱敍濠婂啫歇闂傚倷绀侀幖顐︽偋濠婂牆绀堥柣鏃傚帶缁犳牠鏌ｉ妶搴＄伇婵☆垰瀚伴幃妤冩喆閸曨剛顦ㄧ紓浣筋嚙閸婂潡銆佸Ο鑽ら檮缂佸鐏濋懓鍧楁⒑瑜版帒浜板ù婊呭仱閹嫭鎯旈妸锔规嫽婵炴挻鍩冮崑鎾寸箾娴ｅ啿娲犻埀顒婄畵瀹曞ジ濡烽妷褝绱甸柣搴ゎ潐濞叉牕煤閵婏妇鈻旂€广儱顦伴悡鐘测攽椤旇棄濮囬柍褜鍓氶崝娆忕暦閹达箑绠婚柤鎼佹涧閺嬪倿姊洪崨濠冨闁告挻鐩棟闁靛鍎哄〒濠氭煏閸繂鏆欏┑鈥炽偢閺岀喖鎼归顒冣偓璺ㄢ偓瑙勬礃濡炶姤淇婇悜鑺ユ櫇闁逞屽墰濞嗐垽鎮欏ù瀣杸闂佺粯蓱瑜板啴顢楅姀銈嗙厱鐎广儱娲﹂弳顒佹叏婵犲啯銇濈€规洏鍔嶇换婵囨償閵忋垺姣夐梻鍌欒兌椤牓顢栭崱娆戠煓闁规崘顕х粻鐔兼煙缂併垹鏋熼柡鍛箞閺屾稓浠﹂崜褉鏋旈梺褰掝棑缁垳鎹㈠☉娆愮秶闁告挆鍐ㄧ厒闂備胶顢婇婊呮閺囥垹绠憸鐗堝笚閺呮悂鏌ｅΟ铏癸紞闁告瑥瀚板Λ鍛搭敃閵忊€愁槱闂佸湱鎳撳ú顓炵暦閿濆绀嬫い鎾寸☉娴滈箖鎮峰▎蹇擃仾缁炬儳顭烽弻娑樜旈埀顒勫疮閸ф鏁嬮柨婵嗘椤╃兘鎮楅敐鍛粵闁哄懏绻堝娲濞戞艾顣哄┑鐐茬湴閸旀垵鐣峰┑瀣唶闁哄洨鍟块幏缁樼箾鏉堝墽绉繛鍜冪秮婵″瓨绻濋崶銊у幈闂佽鍎抽顓犵不濡偐纾兼い鏃傛櫕閹冲洦顨ラ悙鏉戠瑨閾绘牕霉閿濆娅滅紒銊ф暬濮婄粯鎷呴崨濠傛殘闂佸憡妫戦梽鍕矉瀹ュ應鏀介悗锝庝簽閻涖儵姊鸿ぐ鎺戜喊闁告ê澧藉褔鍩€椤掍胶绡€闁汇垽娼у瓭闂佺锕︾划顖炲疾閸洖鍗抽柣妯兼暩閿涙粓姊洪柅鐐茶嫰婢у鈧娲栭妶鍛婁繆閻戣姤鏅滈柟顖嗗啰顔戦梻鍌氬€风粈渚€骞栭锕€鐤い鎰堕檮閸嬪绻濇繝鍌氭偐婵炴垯鍨圭粻锝夋煥閺冨倹娅曢柛妯绘倐濮婅櫣鍖栭弴鐕佹綉闂佸憡锕㈢粻鏍箖妤ｅ啯鍋ㄩ柛娑橈功閸樻悂鎮楅崗澶婁壕闂侀€炲苯澧寸€规洑鍗抽獮妯兼嫚閼碱剙濮︽俊鐐€栫敮濠囨嚄閸洖鐓€闁哄洨鍠嗘禍婊勩亜閹捐泛浠︾€瑰憡绻勭槐鎺楊敊绾拌京鍚嬫繝纰夌磿閸忔﹢寮崒鐐茬鐟滄粓宕惔銊︹拺閻犲洩灏欑粻鎵磼缂佹ê鐏撮柟顔ㄥ吘鏃堝焵椤掑嫬鐓濈€广儱顦獮銏＄箾閹寸偟鎳呴柛姗嗕邯濮婃椽骞栭悙鎻掑Η闂佸憡鍔曡ぐ鐐垫閺冣偓娣囧﹪濡堕崶顬儵鏌涚€ｎ剙浠遍柍銉畵瀹曞爼顢楅埀顒傜不閺屻儲鐓曢柡鍥ュ妼婢ь垰鈹戦鐣岀煉闁哄矉绲借灃闁逞屽墴閹囧幢濞戞瑥浜楅梺鍝勬川閸犳挾寮ч埀顒勬⒑濮瑰洤鐏叉繛浣冲嫮顩锋繝濠傜墛閻撶喖骞掗幎钘夌閹兼番鍔岀粈鍡涙煙閻戞﹩娈曢柡鍛叀閺屾盯濡烽幋婵囧櫧闁烩剝锕㈠缁樻媴閸涘﹤鏆堥梺鍦焾濡繂鐣烽悢纰辨晝闁靛繈鍨归幖鍛婄節閻㈤潧啸闁轰焦鎮傚畷鎴︽倷閸濆嫬鐎銈嗙墱閸嬫盯宕归崒鐐寸厱闁挎棁顕ч獮妯衡槈閹惧磭效闁哄被鍔岄埞鎴﹀幢閳哄倐褔姊虹紒妯诲暗闁哥姵鐗犲濠氭偄閸忚偐鍔烽梺鎸庢磵閸嬫挻顨ラ悙鎼畼缂佽鲸鎸搁濂稿幢濡ゅ啩绱濋梻浣告惈閻绱炴担閫涚箚闁归棿鐒﹂弲婵嬫煃瑜滈崜鐔煎箖濡皷鍋撳☉娅虫垿宕ｈ箛鎾斀闁绘ê寮堕崳鐑樸亜韫囨洖啸缂佽鲸甯￠、娆撴偩鐏炴儳娅戦梻浣哥枃椤曆囨煀閿濆宓侀柛鈩冨嚬濡茬粯绻濋姀銏″殌妞わ箓娼ч～蹇曠磼濡顎撻梺缁樺灦閿氭繛鍫濈焸濮婅櫣娑甸崪浣告疂缂備胶绮换鍫ユ偘椤曗偓瀹曟﹢顢欓懖鈺嬬床闂備胶绮崝鏇烆嚕鐠轰綍锝夘敆閸曨兘鎷洪梻鍌氱墛娓氭顬婅缁辨帡鎮╅崘鑼患濠电偛妫庨崹浠嬪箖濞嗘挻鍊绘俊顖滃帶楠炲秹姊婚崒娆戣窗闁告瑥绻掔划濠氬箣閻愬瓨鐝烽梺缁橆殔閻楀嫭绂嶅鍫熺厸闁告劧绲芥禍楣冩⒑閸︻厽鍤€婵炲眰鍊濋敐鐐剁疀閹句焦妞介、鏃堝礋椤愩倗宕烘繝鐢靛Х閺佸憡鎱ㄩ幘顔肩９闁归棿绲告径鎰唶闁靛鑵归幏娲⒑绾懎浜归柛瀣洴瀹曟繈鍩€椤掑嫭鈷戠紒瀣濠€鎵磼椤斿ジ鍙勯柣娑卞櫍楠炴绱掑Ο閿嬪闂備胶顭堥張顒勬嚌妤ｅ啫鐒垫い鎺嶇劍閸婃劗鈧娲橀崝鏍囬悧鍫熷劅闁挎繂娲ㄩ崝璺衡攽閻愯埖褰х紒韫矙楠炴牠顢曚綅婢跺娼╂い鎾寸矆缁ㄥ姊虹憴鍕姢鐎规洦鍓熼幃姗€鍩￠崘顏嗭紲闂佺粯锕㈠褔鍩㈤崼銉︾厸鐎光偓閳ь剟宕伴弽褏鏆︽繝濠傛－濡查箖鏌ｉ姀鈺佺仭闁烩晩鍨跺璇测槈濮橈絽浜鹃柨婵嗙凹閹查箖鏌涙惔锛勭闁哄苯绉堕幉鎾礋椤愩倓绱濋梻浣筋嚃閸犳帡寮查悩鑽ゅ祦闁规崘顕х粻铏節闂堟稒鍣界痪鎯ь煼濮婂宕掑▎鎴濆濠碉紕鍋涘鈥崇暦閵忥紕顩烽悗锝庡亜娴狀參姊洪棃娑辨Т闁哄倷绶氶崺鈧い鎺戯工椤╊剟鏌熼悷鏉款伃濠碘剝鎮傞弫鍐焵椤掑倸顥氭い鏍ㄧ〒缁犻箖鏌熼悙顒佺稇闁搞値鍓熼弻娑㈠Ω閵堝懎绁悗瑙勬礃缁矂鎮鹃悜钘夌倞闁冲搫鍠涚槐鍐测攽閻愯埖褰х紒鑼舵椤曪綁宕奸弴銊︽櫅闂佺硶鍓濈粙鎺楁偂閺囥垺鍊甸柨婵嗛娴滄繄鈧娲栭張顒勫箞閵婏妇绡€闁告洦鍘肩粭锟犳⒑閻熸澘妲婚柟铏悾鐑藉Ω閿斿墽鐦堥梺绋挎湰缁嬫帡鎮鹃崗鑲╃瘈闁汇垽娼ф禒锕傛煙濮濆苯鍚归柛鐘诧工椤撳吋寰勯崼姘壕闁告劏鏅濈弧鈧梺绋挎湰缁秴鈻撴ィ鍐┾拺闂傚牊鐩悰婊呯磼鏉堛劍绀嬫慨濠佺矙瀹曠喖顢涘☉姘箞婵犵數濞€濞佳呪偓姘煎墴瀹曟繂顫濇潏鈺冿紲婵炴挻鑹鹃敃锕傛偩閻㈠憡鐓涚€光偓鐎ｎ剛蓱闂佽鍨卞Λ鍐€佸☉姗嗙叆闁告稑鎷戠紞浣割潖閾忓湱鐭欐繛鍡樺劤閸撲即姊虹粙鍖″伐妞ゎ厾鍏橀悰顕€骞嬮敃鈧～鍛存煏閸繃鍣归柤鏉跨仢閳规垿鎮欓弶鎴犱桓闂佽崵鍟欓崶褍鍋嶅銈呯箰閻楀﹪鍩涢幋锔界厱闁圭偓娼欑徊璇裁瑰鍕畼缂佽鲸甯為幏鐘诲箵閹烘挻顔掓俊銈囧Х閸嬬偤鎮ч悩鑽ゅ祦闁搞儺鍓﹂弫濠囨煟閻旂⒈鏆掑瑙勬礀閳规垿鎮欓弶鎴犱桓闂佽崵鍟欓崨顖欑瑝闂佺粯鍔曢悺銊╁矗韫囨挴鏀介柣妯诲絻閳ь剙缍婇獮鍡涘醇閵夛箑浜楅梺闈涚墕椤︿即宕戦敐澶嬬厱闁靛绲芥俊鑲╃磼閼艰泛鍚圭紒杈ㄥ浮閹晠鎳犻濠勭缂傚倷娴囨ご鎼佸箰婵犳艾绠柛娑樼摠鐎电姴顭跨捄楦垮閻㈩垰娼￠弻锝嗘償閳ュ啿杈呴梺绋款儐閹瑰洭寮婚悢鍏尖拻缁炬儳顑呴崢锟犳倵鐟欏嫭灏紒鑸靛哺瀵鈽夐姀鐘靛姶闂佺绻嗛弲婊堝垂閸洖绀嗗┑鐘叉搐缁犵粯銇勯弮鍌涙珪闁告ü绮欏铏圭磼濡儵鎷诲銈庡幖閻楁捁妫㈤柣搴秵閸撴稓澹曟總鍛婄厵闂侇叏绠戦弸娑樏归悩娲摵闁逛究鍔嶇换婵嬪炊閳哄啰鐛ラ梻渚€娼уú锕傚礉濞嗘挾宓侀柟鐑橆殔缁狅絾绻濇繝鍌氭殲闁诲孩濞婂濠氬磼濞嗘埈妲梺纭咁嚋缁绘繈寮€ｎ喗鈷戦梻鍫熺〒婢с垺銇勯鐐靛ⅵ闁诡喗鍎抽悾锟犳焽閿旀儳寮抽梻浣稿閸嬫帡宕戦崨鏉戠柧闁挎繂顦伴埛鎴︽⒒閸喓銆掔紒鐘崇娣囧﹪鎮▎蹇旀悙缂佺媭鍨辩换娑橆啅椤旇崵鍑归梺鎶芥敱閸ㄥ潡寮诲☉妯锋婵鐗嗘慨娑㈡⒑鐎圭姵顥夋い锔炬暬瀵濡搁埡浣稿祮濠碘槅鍨伴幖顐ｆ叏閺囥垺鍊甸柛顭戝亝缁舵煡鎮楀顓熺凡闁伙絿鍏橀幃銏㈠枈鏉堛劍娅栨繝鐢靛仦閸ㄥ爼鎳濇ィ鍐祦闁割偁鍎查埛鎴︽偣閸ャ劌绲婚柛銈堜含缁辨挸顓奸崨顕呮！缂備礁鍊哥粔鎾煘閹寸姭鍋撻敐鍛搭€楁い锔诲灦閳ワ箓濡搁埡浣哥獩濡炪倖妫冨Λ璺ㄥ垝閳╁啰绡€闁汇垽娼ф禒婊勪繆椤愶絿鎳囨鐐村姈缁绘繂顫濋鐐扮暗闂備礁鎼ú銊╁窗閸℃顩叉繝濠傜墛閻撴瑩姊洪銊х暠闁哄绋撻埀顒佺⊕缁诲牆顫忓ú顏勫窛濠电姴鍟犻幏鍦磽娓氬洤鏋熼柟鐟版搐椤曪絿鎷犲顔兼倯婵犮垼娉涢鍥矗閸℃稒鐓熼幖鎼灣缁夐潧霉濠婂嫮绠橀柟椋庡█閹瑩鎮滃Ο閿嬪闂備礁鎲＄换鍌溾偓姘煎幖閿曘垽骞嶉鍓э紲闁诲函缍嗛崑鍛焊閹殿喚纾奸柛灞剧☉濞搭噣鏌℃担绋库偓鍧楀箖濞嗘搩鏁嗛柍褜鍓熼幃鐢稿级鎼存挻鏂€闂佺粯鍔曢悺銊х礊閹寸偑浜滈柟瀛樼箖閸ｈ櫣绱掗崒姘毙ｉ柕鍫秮瀹曟﹢鍩￠崘銊ョ闂傚倷鐒﹂幃鍫曞磿椤栫偛纾块梺顒€绉甸崐鑸点亜閺冨牊鏆滈柛瀣尵閹叉挳宕熼鈧惌顕€姊虹紒妯洪嚋闂傚嫬瀚划姘綇閵娧呯槇闂佹悶鍎撮崺鏍疾椤掆偓閳规垿鎮欓弶鎴犱桓闂佽崵鍣︾徊鍓х矉閹烘洦妲婚梺瀹狀潐閸ㄥ潡骞冨▎鎾村殤妞ゆ巻鍋撴い锝呮贡缁辨挻绗熼崶褎鐏嶉梺鑽ゅ暱閺呮盯顢氶敐鍡欑瘈婵﹩鍘藉▍婊勭節閵忥絾纭鹃柨鏇畵閹潡鍩€椤掍椒绻嗛柣鎰典簻閳ь剚鐗曢蹇旂節濮橆剛锛涢梺瑙勫劤婢у海澹曟總鍛婄厽婵炲棙鍔楅幊鍐倵濮樸儱濡界紒鍌氱Т椤劑宕奸悢鍝勫妇濠电姰鍨奸崺鏍矙閹捐绀嗗ù鐓庣摠閻撶喖鐓崶褝鏀绘繛鍛躬閺?")
        elif scenario == "engineering_challenge":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙绐涢梺鍝ュУ閹稿墽鍒掔紒妯稿亝闁告劏鏅濋崢浠嬫⒑闁稑宓嗘繛浣冲嫭娅犳い鏍仦閻撶喐绻濋棃娑欏缂佲偓鐎ｎ偅鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噧闁宠閰ｉ獮鍡氼槻濠㈣锚閳规垿鎮欓懠顒佹喖缂備緡鍠氭慨鐢电矉瀹ュ鏁傞柛鏇㈡涧濞堛劑鏌ｉ悩鍙夊缂佷焦娼欏嵄闁割偁鍎查悡蹇涚叓閸ャ劍绀€閸熸悂姊洪崨濠冣拹闁圭鍟块～蹇撁洪鍕獩婵犵數濮撮崐姝岊杺婵犵數鍋涢悺銊у垝瀹ュ鍋嬫俊銈呮噹缁犵偤鏌曟繛鐐珔闁绘劕锕ラ妵鍕箳瀹ュ牜鍞归梺鍦焿濞咃絿妲愰幘璇茬＜婵炲棙鍨垫俊浠嬫煢閸愵喕鎲鹃柟顔筋焾缁犳盯鏁愰崨顓犵潉闂備礁鎼張顒傜矙閹烘梹宕叉繝闈涱儏绾惧ジ鏌曢崼婵囨悙闁诡喗鍨垮缁樻媴閾忓箍鈧﹪鏌￠崒娆戠獢鐎规洘鍨块獮姗€骞囨担鐟扮槣闂備線娼ч悧鍡椢涘Δ鍛敜濠电姴娲﹂悡鏇㈡倵閿濆骸浜濋悘蹇曟暩缁辨帗娼忛妸銉﹁癁闂佽鍠掗弲鐘诲箠閻樻椿鏁勬い鎰閹冲宕戦幘鑸靛枂闁告洦鍓涢ˇ銊モ攽閻愯泛鐨洪柛鐘查叄閹箖鎮滈懞銉︽闂佺粯锚閸熷潡鍩€椤掆偓婢у海妲愰幘瀛樺闁兼祴鍓濋崹鎸庝繆闂堟稈鏀介柛鈥崇箲閺傗偓闂備胶鍋ㄩ崕杈╁椤撱垹鏄ラ柨婵嗘礌閸嬫挾鎲撮崟顒傤槬閻庤娲﹂崜鐔煎春閵忊剝鍎熼柍顓滃劤閸犳牠骞婇敓鐘参ч柛鎰╁妺閼割亝绻濋悽闈浶ユい锝庡枤濡叉劙寮撮姀鐘碉紱闂佺鎻粻鎴犲瑜版帗鐓涚€广儱楠搁獮妤呮煕鐎ｎ亶鍎愬ǎ鍥э躬婵″爼宕ㄩ鍏碱仩闂備礁鎼€氥劑宕曢悽绋胯摕婵炴垯鍨圭粻娑㈡煃鏉炴壆顦︽い銉ヮ儔濮婃椽骞愭惔锝囩暤濡炪倧瀵岄崹鍫曞蓟鐎ｎ喖鐐婃い鎺嶈兌閸橆亝绻濋姀锝呯厫缂佸鍨块妴鍛搭敆閸曨剛鍘卞┑鈽嗗灠閸氬寮抽浣瑰弿濠电姴鎳忛鐘绘煙妞嬪骸鈻堥柛銊﹀劤閻ｇ兘宕堕敐鍛婵犵數濮电喊宥夋偂閺囩喓绡€濠电姴鍊搁弳娆撴煛閸℃瑥鏋旂紒杈ㄥ浮閸┾偓妞ゆ帊鑳剁弧鈧梺鎼炲劘閸斿骞忓ú顏呪拺闁告稑锕︾粻鎾绘倵濮樼厧鏋﹂柍顏嗘暬濮婄粯绗熼埀顒勫焵椤掑倸浠滈柤娲诲灡閺呭爼顢涢悙瀵稿幐闁诲函缍嗘禍妤呭磻閵忊懇鍋撳▓鍨灁闁告柨绉剁划瀣箳閺傚搫浜鹃柨婵嗛娴滅偤鏌涘Ο缁樺磳婵﹥妞藉Λ鍐ㄢ槈鏉堛剱銈夋⒑缁嬪潡鍙勫ù婊嗘硾椤曪綁鎼归锝囩Ф闂佸啿鎼崯浼存晬濠婂牊鈷戠紓浣诡焽閹冲嫰鏌ｉ悢鏉戝姎閻撱倝鏌ㄩ弴鐐测偓褰掑磻閸屾稓绠鹃柛鈩兠慨鍌毭瑰鍕煉闁哄矉绻濆畷姗€濡搁妷銏犱壕闁告縿鍎查弳婊堟煕椤愶絾绀冮柣鎾冲暟閹茬顭ㄩ崼婵堫槶濠殿喗顭堝▔娑氱不閺嶎厽鐓曠€光偓閳ь剟宕戝☉姘变笉闁哄稁鐏涢弮鍫熸櫜闁告侗鍘藉▓鏌ユ⒑缁嬪尅宸ユい顓犲厴瀵鏁冮埀顒冪亽婵炴挻鍑归崹杈殭濠碉紕鍋戦崐鏍箰閹间礁绠规い鎰剁畱閻撴﹢鏌熸潏楣冩闁稿鍔欓弻銈囧枈閸楃偛骞愮紓渚囧枤閺佽顫忓ú顏勫窛濠电姴鍟犻幏褰掓⒑缂佹﹩娈樺┑顔芥尦閹箖鎮滈挊澶岊啋缂傚倷鐒﹂敃鈺佄涢崘銊㈡斀闁绘劖娼欓悘鍗烆渻閺夋垶鎲搁柍褜鍓熷褔鎯岄崒姘兼綎婵炲樊浜濋ˉ鍫熺箾閹寸偠澹樻い锝呮惈閳规垿鍩ラ崱妞剧凹闂佽崵鍟欓崟顓ф锤闂佸綊妫块悞锕傚磻閵娾晜鐓曟繛鎴烇公閸旂喖鏌涘鈧禍鍫曞蓟閿濆棙鍎熸い鏍ㄧ矌鏍￠梻浣侯焾椤戝懐鈧凹鍙冮獮鍫ュΩ閵夘喖鎮戦梺鎼炲劵缁茶姤绂嶉悙顒傜闁割偅绻勬禒銏ゆ煛鐎ｃ劌鈧牠濡甸崟顖ｆ晣闁绘劙娼ч埅鐢告⒑缁洘鏉洪柛銊︽そ楠炲棝寮崼婢晠鏌曟竟顖氳嫰閺咁亪姊绘担绛嬪殭婵炲鍏樺顐﹀箹娴ｆ祴鍋撻敃鍌氶唶闁靛／鍐偊婵犲痉鏉库偓鏇㈠箠韫囨稑鐓曢柟鐑樺殮瑜版帗鏅查柛顐ゅ櫏娴犫晠鏌ｉ姀鈺佺仭闁烩晩鍨跺濠氬Ω閳轰礁宓嗗┑鈽嗗灥濞咃絾绂掗悡搴富闁靛牆楠搁獮鏍ㄧ箾濞村娅婇挊婵嬫煕閿旇骞愰柛瀣尵閹叉挳宕熼鍌ゆО缂傚倷绶￠崰鏍儗閸岀偛绠栧Δ锝呭暞閸婂鏌﹀Ο渚Ш闁稿﹦鍋ゅ娲礃閸欏鍎撻梺鍝ュУ缁嬫挸危閹版澘钃熼柕澶涜吂閹锋椽姊洪崨濠勭畵閻庢艾鍢插嵄闁归棿鐒﹂悡鐔镐繆閵堝倸浜鹃柣搴㈢濠㈡﹢鎮惧畡鎵虫斀闁糕檧鏅涢幃鎴︽⒑閹肩偛鍔楅柡鍛箞閹偞绺介崨濞炬嫼闂佸憡鎸昏ぐ鍐╃閺嶎厽鐓曢幖娣灮閸欌偓闂佽鍣换婵嗩嚕閹绢喖顫呴柨娑樺楠炲秹姊绘担铏瑰笡闁搞劍鍎奸幗顐︽煟韫囨挻绂嬮柛妯哄⒔濡叉劙骞掗幋顓熷瘜闂佹寧娲嶉崑鎾绘煕濡绀冮柕鍥ㄥ姍楠炴帡骞橀崗鍛線闂傚倷绀侀幉鈩冪瑹濡ゅ懎鍨傞柟鎯版濮规煡鏌曢崼婵愭Ч闁稿﹦鏁婚幃宄扳枎韫囨搩浠剧紓浣插亾闁告劦浜炵壕鍏笺亜閺冨洤浜圭紒鐘差煼閹稿﹤鈹戦崶銉ょ盎闂佸搫娲﹂〃鍛妤ｅ啯鈷戦柛婵嗗閻掕法绱掓潏銊︾闁糕斁鍋撳銈嗗笒閿曪妇绮旈悽鍛婄厱閻庯綆浜濋ˉ銏☆殽閻愯韬€规洖鐖兼俊鎼佹晝閳ь剙顕ｉ幐搴ｇ瘈闁汇垽娼у瓭闂佺懓鍟跨换姗€銆侀弮鍫熷亹闁汇垻鏁搁敍婊堟煛婢跺﹦澧戦柛鏂跨灱缁參骞掑Δ浣瑰殙闂佹寧绻傞ˇ浼存偂閺囥垻鍙撻柛銉ｅ妽缁€鈧柣銏╁灥閸╂牜鎹㈠☉銏犲窛妞ゆ棁鍋愭导灞解攽椤旂》鍔熺紒顕呭灦楠炲繘宕ㄩ鍓ф嚌濡炪倖鐗楃粙鎺楀汲閻愬绡€闁汇垽娼ф禒婊堟煙閸愯尙绠伴悡銈夋煟閺冨牜妫戦柡鍡檮缁绘繈妫冨☉娆戝姼闂佸搫鍟悧鍡欑矆閸愵喗鐓忓┑鐐茬仢閸斻倕霉濠娾偓閸楀啿顫忕紒妯诲缂佸顑欏Λ宀勬⒑缁嬫鍎忔俊顐ｇ箓閻ｇ兘鎮ч崼鐔峰妳闂佹寧绻傚Λ顓㈠磻閵娾晜鈷戠紓浣姑慨澶愭煕鎼存稑鈧繈骞冮垾鏂ユ瀻闁瑰墽琛ラ幏鍝勵渻閵堝棙灏柛鏂块叄閹偓娼忛…鎴烆啍闂佺粯鍔橀幓顏堟嚀閸ф鐓涢悘鐐插⒔閳藉銇勯锝囩煉闁糕斁鍋撳銈嗗笒閸婄粯绋夊澶嬬厸鐎规搩鍠栭張顒傜礊鎼粹檧鏀介柣鎰级閳绘洖霉濠婂嫮鐭嬮悗闈涖偢閹晝绱掑Ο鐓庡箞闂備礁鎼ú銊╁磻閻斿摜顩锋繛鎴欏灩閺嬩線鏌涢鐘插姕闁抽攱鍨块幃褰掑炊瑜嶇痪褔鏌熼惂鍝ョМ闁哄矉缍侀幃銏㈢矙鎼存挻鐏嗛柣搴ゎ潐濞叉﹢鏁冮姀銈呯疇婵°倕鎷嬮弫宥嗕繆閵堝倸浜炬繛瀛樼矒缁犳牠寮诲☉婊庢Ъ濡炪們鍔屽Λ婵嬪箖閿熺姵鍋勯梻鈧幇顔剧暰闂備線娼ч悧鍡涘磹閸涘﹦顩插Δ锝呭暞閳锋垹绱撴担鐧镐緵婵炲牊妫冮弻鐔兼惞椤愩垹顫掑Δ鐘靛仦閸ㄦ寧鎱ㄩ埀顒勬煏閸繃鍣归柤鏉跨仢閳规垿鎮欓弶鎴犱桓闂佽崵鍟欓崶褍鍋嶉梺鍛婎殘閸嬫劙寮ㄦ禒瀣厽闁归偊鍓欑痪褎銇勯妷锔剧煁缂佺粯绋撻埀顒佺⊕椤牊绔熷鈧畷鈩冩綇閳哄倸鏋戦梺缁橆殔閻楀棛绮鑸电厽闁规儳鐡ㄧ粈鈧梺瀹狀潐閸ㄥ潡骞冮埡鍛闁圭儤鎸婚鍕攽閻樻剚鍟忛柛鐘崇墵閹勭節閸ヮ灛锕傛煕閺囥劌鐏犻幆鐔兼⒑閹稿海绠撻柟鍐插閹便劑鏁冮崒娑掓嫼闁荤姴娲犻埀顒冩珪閻忓秹姊洪懡銈呮毐闁哄懐濞€閹即顢氶埀顒勭嵁濡吋瀚氶柤纰卞墻閸炵儤绻濋悽闈涒枅婵炰匠鍏炬稑螖閳ь剟寮鍓х＝闁稿本鑹鹃埀顒佹倐瀹曟劙骞栨担鍝ワ紮闂佺粯鍨兼慨銈夊吹閸曨垱鐓曢柟鎹愬皺椤︼箓鏌涢妸锔剧畺闁靛洤瀚板浠嬪Ω瑜忛悡渚€鎮楃憴鍕闁绘搫绻濆璇测槈閵忊晜鏅濋梺鎸庣箓濞层劑鎮炬總鍛娾拺闁告繂瀚敍鏃堟⒒閸曨偄顏┑锛勬暬瀹曠喖顢欓崜褎婢戦梻浣告贡閸嬫挸顭囧▎蹇婃瀺闁靛牆妫涚弧鈧┑鐐茬墕閻忔繈鎮橀敓鐘崇厵闁告稑锕ら埢鏇犫偓娈垮枦椤曆囧煡婢跺á鐔兼煥鐎ｅ灚缍屽┑鐘愁問閸犳銆冮崨瀛樺亱濠电姴娲ら弸渚€鏌熼鍡忓亾闁衡偓娴犲鐓熼柟閭﹀灠閻ㄥ搫顭胯缁插墽鎹㈠☉銏犳そ闁告劦浜濋崑褍鈹戦垾鍐茬骇闁告梹鐟╅悰顔嘉熼崗鐓庣彴闂佽偐鈷堥崜銊ф閸欏绡€婵炲牆鐏濋弸鐔兼煥閺囨娅婄€规洘顨呴～婊堝焵椤掆偓閻ｇ兘骞嬮敃鈧粻濠氭偣閸ヮ亜鐨烘い鏃€鍔栫换娑欐綇閸撗冨煂闂佺濮ょ划鎾诲极瀹ュ應鏋庨柟閭︿簽缁犳岸姊虹紒妯哄婵☆垰锕畷鏇＄疀閺冨倻顔曢柣搴ｆ暩椤牓宕㈤幘顔界厵妞ゆ牗姘ㄩ悞鍝モ偓瑙勬礀瀹曨剟鈥旈崘顏冪剨闁哄诞鍌氼棜闂備礁婀遍崕銈夊春閸繍鐒介柍鍝勬噺閻撱儲绻濋棃娑欘棡闁革絿顭堥…璺ㄦ喆閸曨剛顦伴梺鍝勭焿缁查箖骞嗛弮鍫澪ч幖娣灮缁夐攱绻濋悽闈涗哗妞ゆ洘绮庣划濠氬箻瀹曞洦娈鹃悷婊呭鐢帡鏌嬮崶顒佺厸闁搞儮鏅涘瓭缂備椒绶ょ粻鎴﹀煘閹达富鏁婂┑顔藉姃缁爼姊虹粙娆惧剱闁圭顭锋俊鐢稿礋椤栨凹娼婇梺鎸庣☉鐎氼參宕抽鈧铏规嫚閳ヨ櫕鐏嗛梺鍛婎殕婵炲﹤鐣风憴鍕╁亝闁告劑鍔庨ˇ褔姊洪崨濠佺繁闁告瑥楠歌灋婵犲﹤鐗婇埛鎺楁煕鐏炲墽鎳嗛柛蹇撴湰閵囧嫰顢橀悙闈涒叺閻庢鍠氶弫濠氥€佸Δ鍛＜婵犲﹤鎳愰崢顖炴⒒娴ｅ憡璐￠柛瀣崌閹洩銇愰幒鎴犲姦濡炪倖宸婚崑鎾绘煙閾忣偓鑰挎鐐插暙椤劑宕奸悢閿嬬枀闂備線娼чˇ顓㈠磿椤曗偓瀹曟垿骞樼紒妯轰缓闂佸憡绋戦敃锕傚矗閸℃せ鏀介柣妯肩帛濞懷勪繆椤愶絿娲寸€规洘鐟╁畷鐑筋敇閻樼绱查梻渚€娼ч…鍫ュ磿濞差亝鍋傚┑鍌氭啞閻撴盯鎮橀悙鎻掆挃闁靛棙甯￠弻宥堫檨闁告挶鍔庣槐鐐哄幢濡⒈娲搁梺缁樺姇閻°劌鈻嶈箛娑欌拻闁稿本鐟чˇ锕傛煙绾板崬浜伴柟顖氭湰瀵板嫮浠﹂悾宀€鐡樺┑掳鍊х徊浠嬪疮椤愩倗涓嶆慨妯垮煐閻撴盯鏌涢幇鈺佸濠⒀囦憾閺屸剝鎷呴崫銉愶絿绱掔紒妯肩畺缂佺粯绻堝畷鎺戔槈濡粯顏ら梻鍌欑劍鐎笛呮崲閸屾娑樷槈濮樺彉绗夋俊銈忕到閸燁垶宕愰崹顐ょ闁瑰鍋熼幊鎰版煟閹哄秶鐭欓柡宀嬬秮椤㈡﹢鎮滈崱妤€澹嬬紓鍌欐祰妞村摜鏁悙鍝勭闁绘绮崵鎴炪亜閹哄棗浜鹃梺鎰佷簽閺佽顫忛搹瑙勫珰闁炽儴娅曢悵顖滅磽娴ｈ櫣甯涚紒璇茬墦婵″瓨鎷呴懖婵囨瀹曘劑顢橀悪鈧Σ褰掓⒒娴ｇ顥忛柣鎾崇墦瀹曟垿宕ㄩ娑欑€洪悗鍏夊亾闁告洦鍏橀幏缁樼箾鏉堝墽瀵奸悹鈧敃鍌涘€垮Δ锝呭暞閻撴盯鏌涢顐簻濠⒀勫缁辨帡顢欓悾灞惧櫚濡ょ姷鍋涢澶愬极閸愵喖鐒垫い鎺戝缁€鍕煟濡偐甯涢柣鎾寸懇瀵爼宕奸妷褏鏆┑锛勮檸閸ｏ綁寮诲澶嬬叆閻庯綆浜炴禒鑲╃磽娴ｄ粙鍝洪柟绋款煼楠炲繘宕ㄧ€涙ê鍓梻鍌楀亾闁归偊鍠涚换鎴濃攽閻樺灚鏆╅柛瀣洴閹勭節閸嬭姤鐩畷姗€顢欓懝鐗堟啺闂備焦瀵х换鍌炲箟濮椻偓瀵噣宕煎┑鍫濆Е婵＄偑鍊栫敮鎺斺偓姘煎弮瀵彃鈹戠€ｎ偆鍙嗛梺鍝勫暙閸婄懓鈻嶉弴鐔翠簻闁冲搫鍊婚崣鈧梺鍝勭灱閸犳牕顫忛懡銈傚亾閸偆鎽冪紒鎰殜濮婄儤娼幍顕呮М濠电偛妯婇崣鍐嚕婵犳碍鏅插璺猴功椤撳搫鈹戦悩缁樻锭婵炴潙鍊歌灋闁靛牆顦伴埛鎴︽煕濠靛嫬鍔氬ù鐘欏洦鐓涘ù锝呭閻撳吋顨ラ悙鎻掓殭闁伙綇绻濋弻鍥晜閹冩辈闂傚倷绀侀幉锟犲礉閿旂晫顩查柣鎰閺佸﹤顭块懜闈涘闁抽攱鍨垮娲敃閿濆洢鈧帡鏌嶇憴鍕诞闁哄本鐩顕€鍩€椤掑嫬鍨傞柛褎顨堝畵渚€鏌涢幇闈涙灍闁稿鏅濋埀顒€鍘滈崑鎾绘煃瑜滈崜鐔煎箚鐏炶В鏋庨柟鐐綑娴狀垶姊洪幖鐐插姌闁告柨绉堕埀顒佺濞叉粎妲愰幒妤佸亹闁惧浚鍋勭壕鎶芥倵濞堝灝鏋︽い鏇嗗洤鐓″鑸靛姇椤懘鏌ｅΟ璇茬祷缂佷緡鍣ｅ缁樼瑹閳ь剙顭囪閳ワ箓宕奸妷銉э紵闂佹儳娴氶崑鍡涖€呴悜鑺ョ厓闁告繂瀚崳娲煃闁垮鐏撮柡灞剧洴閺佸倻鎷犻幓鎺戭劀闂備浇銆€閸嬫挸霉閻撳海鎽犻柣鎾存礋閺屽秹宕崟顐熷亾缂佹ɑ娅犻梻鍫熺▓閺€浠嬫煥濞戞ê顏柡鍡╁墰閳ь剝顫夊ú婊堝窗閺嶎厹鈧礁鈽夊鍡樺兊婵℃彃鏈悧鏇㈠疾椤忓牊鈷掑ù锝堟閸氱懓鈹戦钘夊姢闁宠绉归弫鎰緞婵犲嫸绱甸梻渚€娼ч悧鍡浰囨导鏉戠９閻犵儤浜介埀顒佸笒椤繈鏁愰崨顒€顥氬┑鐘愁問閸犳牠鏁冮妸銉㈡瀺闁挎繂娲﹂～鏇㈡煙閻戞ê娈鹃柣鏃囨〃閻掑﹪鏌″搴ｅ帨缂佽鲸鐟╁濠氬磼濞嗘帒鍘″銈庡幖閻楁捇寮绘繝鍥ㄦ櫜闁告粈鑳堕崝鐑芥偡濠婂嫭顥堥柡浣瑰姍閹瑩宕滄担鐑樻緫闂備礁鎼ú銊︽叏閻戣姤鏅繝濠傚暊閺€浠嬫煃閽樺顥滈柣蹇嬪劜閵囧嫰寮撮崱妤佺ォ闁轰椒绶氶弻鐔煎礈瑜忕敮娑㈡煃闁垮鐏撮柡灞诲€栭幈銊╁箛椤戣棄浜鹃柡鍥ュ灩閸戠娀鏌熺€涙绠ラ柣鏂挎閺岋綁鎮㈤崫鍕垫毉濡炪們鍎虫慨椋庢閹烘鏁婄痪顓犳焿閸氼偊姊洪崫鍕潶闁告柨閰ｉ崺鈧い鎺戯功缁夌敻鏌涢幘瀵告创闁诡垯绶氬畷濂稿Ψ閿旇瀚介梻浣侯焾閺堫剙顫濋妸锔芥珷婵炴垶姘ㄧ壕濂告倵閿濆骸浜滈柣蹇旀尦閺屾盯鍩為幆褌澹曞┑锛勫亼閸婃牜鏁幒妤€纾圭憸鐗堝笒閸氬綊鏌嶈閸撴瑩鈥旈崘顔嘉ч幖绮光偓鑼泿缂傚倷鑳剁划顖炴晝閵忋倗宓佸┑鐘叉处閺呮悂鏌ｅΟ鍝勬鐟滄棃寮诲☉妯锋闁告鍋涚粻缁樼箾鐎涙鐭嗛柛妤€鍟块～蹇曠磼濡顎撶紓浣割儐鐎笛冃掗幇鐗堚拺闁革富鍘搁幏锟犳煕鐎ｎ亷宸ラ柣锝囧厴椤㈡盯鎮欓弶鎴滄睏闂佽崵濮村ú鈺冧焊濞嗘挻鏅繛鎴欏灪閳锋垿鏌涢敂璇插箹濞存粓绠栭弻锛勨偓锝庡墮鐢爼宕￠柆宥嗙厱妞ゆ劑鍊曢弸鏃傜磼閻樿崵鐣洪柡灞剧☉椤劑鍩€椤掑倻鐭嗗ù锝呭閸ゆ洟鏌熼锝囦汗闁荤喖鍋婇悡銉╂煕濞戝崬骞掔紒顔肩埣濮婅櫣鈧湱濯崵娆撴⒑鐢喚绋婚柟渚垮姂閸┾偓妞ゆ帒瀚悡蹇涙煕椤愶絿绠栨い銉︾矒閺屽秷顧侀柛鎾寸洴瀹曟顫滈埀顒€顕ｆ繝姘櫜濠㈣泛锕﹂娲⒑缂佹ê鐏ユ俊顐ｇ洴瀹曟繈鎮滈懞銉㈡嫼闂佸憡绋戦…顓㈡嚀閸啔鐟邦煥閸℃銆愬銈庡亜缁绘劗鍙呭銈呯箰鐎氼亞妲愰崼鏇熲拺闁告稑锕ユ径鍕煕閹惧鎳囩€规洘鍨甸鍏煎緞鐎Ｑ勫闂備礁鎲＄粙鎴︽晝閵夆晜鍋傞柕澶嗘櫆閻撶喐銇勯幘璺轰粶闁逞屽墮濞硷繝鐛崘鈺侇嚤闁圭⒈鍘介弲鈺呮⒑閹肩偛鐏╂い锔芥緲铻為柛鎰╁妿閺嗭箓鏌曟繛鐐珦闁轰礁锕弻鐔碱敍閸℃鏆熼柣銈呭濮婂宕掑顑藉亾妞嬪海鐭嗗〒姘ｅ亾闁诡喖娼″畷鎯邦檨婵炲瓨鐗犻弻鏇熺箾瑜嶉幊鎰版倿閸忚偐绠鹃柟鐐綑閻掑綊鏌涚€ｎ偅宕岄柡灞剧洴閸╃偤骞嗚婢规洖鈹戦敍鍕杭闁稿﹥鐗曢蹇旂節濮橆剛锛涢梺瑙勫劤椤曨厾绮婚崜褏妫い鎾卞焺濡垹绱掗埦鈧崑鎾绘⒒娴ｈ櫣甯涘〒姘殜瀹曟娊鏁愰崨顖涙濠殿喗銇涢崑鎾斥攽閳ヨ櫕鍟為柟顖涙婵偓闁宠棄妫欓ˉ鍫ユ煟鎼淬値娼愭繛鎻掔箻瀹曟繈骞嬮敂琛″亾娴ｅ壊娼ㄩ柍褜鍓熼獮鍐閳藉棙效闁圭厧鐡ㄧ粙鎴炵閳轰讲鏀介柣妯活問閺嗘粎绱掓潏銊︾鐎规洘鍨块獮瀣晝閳ь剛澹曡ぐ鎺撶厸鐎广儱楠搁獮鏍磼閻樿櫕绶查摶鏍煥濠靛棙鍣归柡鍡樼懅閻ヮ亪宕滆鐢稑菐閸パ嶈含妞ゃ垺绋戦…銊╁礃閵娿倗甯涢梻鍌欑劍閹爼宕濆鍥ㄥ床闁告洦鍨扮粻鐔兼煙闂傚顦︽俊顐Ｉ戠换娑㈠幢濞嗗繋澹曠紓鍌氱Т妤犳悂鍩為幋锔藉€烽柛娆忣槴閺嬫瑦绻涚€涙鐭嬬紒顔肩Ф閳ь剟娼ч妶鎼佸箖閳哄啰纾兼俊顖滃帶鐢儳鈹戦悩顔肩伇婵炲鐩幃褔宕卞☉妯碱槷濠殿喗锕╅崜锕傛偄閸℃稒鐓熼柣鏃傚帶娴滅増淇婇妤€浜惧┑鐘愁問閸犳牠鏁冮妷銉富闁芥ê顦遍弳锕傛煏婵犲繐顩紒鈾€鍋撻梻浣告啞閸旀垿宕濆鍛灁妞ゆ劧闄勯埛鎺懨归敐鍛暈闁硅尙顭堥埞鎴︻敊閻愵剚姣堥梺璇″暙閸ャ劌浜圭紓鍌欑劍閿氬ù鐘冲笒椤啴濡堕崱妯硷紩闂佺顑嗛幐楣冨焵椤掑喚娼愭繛鍙夌墪閻ｇ兘顢楅崘顏冪胺婵犵數濮烽弫鍛婃叏閹绢喖纾圭憸鐗堝笒绾捐銇勯弽顐沪闁抽攱甯掗湁闁挎繂鐗婇鐘绘煏閸℃韬柡灞剧洴楠炴鈧潧鎽滈悿鍕⒑鏉炴壆顦︽い鎴濇嚇閳ユ棃宕橀鍢壯囨煕濞戝崬寮鹃柛鏂款樀濮婃椽宕烽鐔锋畬濠电偛鐪伴崐婵嬫晲閻愬墎鐤€婵炴垶鐟ラ埀顒傜帛娣囧﹪顢涘▎鎺濆妳闂佹悶鍊戦崐鏇㈠煘閹达附鍊烽柛娆忣樈濡繝姊洪幖鐐插闁轰浇顕ч悾鐑藉传閸曨厽娈曢梺鍛婃处閸忔﹢骞忛崫鍕ㄦ斀闁绘劘娉涢拕鍏笺亜閺囧棗瀚▍鐘绘煙缂佹ê淇柣鏂挎閺岋綁鎮㈢粙娆炬婵犫拃宥囩暠闁宠鍨块弫宥夊礋椤掍焦鐦撴俊銈囧Х閸嬫稑煤椤擃潿鈧礁螣娓氼垳鍙嗛梺鍛婂壃閸涱厼姣堥梻鍌氬€搁崐椋庣矆娓氣偓楠炲鏁撻悩鑼槷闂婎偄娲︾粙鎴澪涘Ο鎭掆偓鎺戭潩閿濆懍澹曟俊銈囧Х閸嬫稓鎹㈠鈧獮鍐煥閸忓墽鍠栭幊鏍煛婵犲倹娅楅梻鍌氬€风粈渚€骞栭位鍥ㄥ閺夋垵鐎梺姹囧灮椤牏绮婚弽顓熺厵閺夊牓绠栧顕€鏌ｉ幘璺烘灈闁哄矉缍佸顕€鍩€椤掑倹宕查柛灞绢嚔濞差亜围闁搞儮鏅濋悞濂告⒑缁洖澧茬紒瀣浮閹€斥槈濮楀棛鍞甸柣鐘烘鐏忋劑宕濋悢鍛婂弿婵☆垳顭堟慨鍌炴煛瀹€瀣瘈闁糕斁鍋撳銈嗗笂閼冲爼銆呴悜鑺ュ€甸柨婵嗛娴滅偤鏌涘鈧禍鍫曞蓟閿濆牏鐤€闁哄洨鍋樼划鑸电節閳封偓閸屾粎鐓撻梺绯曟櫅閿曨亜顕ｉ幘顔碱潊闁挎稑瀚敮妤呮⒒閸屾瑧顦﹂柣蹇旂箞椤㈡牠宕ㄩ婊呯暥閻熸粌绻掑Σ鎰板箳閹惧绉堕梺闈涱焾閸庤尙鎷犻悙宸富闁靛牆鍟悘顏嗏偓鍏夊亾缂佸娉曢弳锕傛煏婵炵偓娅撻柡浣告喘閺岋綁骞囬鑺ユ瘎濠电偟鍘чˇ闈涱潖閾忚瀚氶柛娆忣槸閺€顓烆渻閵堝骸浜滄い锔诲灣閸欏懎鈹戦埥鍡楃仩闁告艾顑夊鍐差煥閸喓鍙嗛梺缁樻煥閹碱偄鐡紓鍌欒兌婵敻鎮уΔ鍐╁床婵炴垯鍨归獮銏′繆椤栨繍鍤欑痪鏉跨Ч濮?")
        if recent_wins:
            if localized_recent_win:
                lines.append("")
            else:
                lines.append("濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ゆい顓犲厴瀵鏁愰崨鍌滃枎閳诲酣骞嗚椤斿嫮绱撻崒娆掑厡濠殿喗鎸抽幃妯侯潩鐠轰綍锕傛煕閺囥劌鏋ら柣銈傚亾闂備礁婀遍崑鎾诲箚鐏炶娇娑㈡倷閻㈢數锛濇繛杈剧悼閺咁偊宕奸鍫熺厱濠电姴鍟扮粻鐐碘偓娈垮枛椤兘骞冮姀銈嗘優闁革富鍘鹃崢顖炴⒒娴ｇ顥忛柣鎾崇墦瀹曟娊顢氶埀顒€鐣峰┑鍥х窞闁归偊鍘搁幏娲⒑閸涘﹦鈽夐柨鏇畵楠炲﹪宕橀鍡欙紲缂傚倷鐒﹂埣銈夘敂閸剛绋忛棅顐㈡处濮婅崵寮ч埀顒€鈹戦鏂や緵闁告挾鍠栧畷顒勫醇閺囩啿鎷虹紓鍌欑劍钃辨い銉ユ閺屾洟宕辫箛鎾插濠电姷顣藉Σ鍛村磻娓氣偓瀹曟繈骞嬪┑鎰稁濠电偛妯婃禍婵嬫倿婵犳碍鐓熼柟閭﹀灠閽勫ジ鎮楀顓熺凡妞ゎ叀鍎婚¨渚€鏌涢妸銉у煟妤犵偛鍟粋鎺斺偓锝呯仛閺咁剟姊洪棃娑氬婵炲眰鍔戦幆渚€宕煎顏呮閹晠妫冨☉妤冩崟闂備焦瀵уú蹇涘磹濠靛鐏抽柨鏇炲€告儫闂佸疇妗ㄧ欢姘跺船鐠鸿　鏀介柣妯肩帛濞懷勪繆椤愶絿娲撮柛鈹惧亾濡炪倖甯掗ˇ顖炵嵁閺嶃劊浜滄い蹇撳閺嗭絽鈹戦垾宕囧煟鐎规洖宕灃闁逞屽墴閿濈偤宕ㄧ€涙ǚ鎷洪梺鍛婄☉閿曘儳浜搁幍顔剧＜閻犲洩灏欐晶鏇㈡煟閿濆洤鍘存い銏☆殕閹峰懘宕妷褏宓侀梻鍌欑缂嶅﹪宕戞繝鍥у偍闁归棿绀佺粻顖滅磽娴ｈ鐒界紒鐘荤畺瀵爼宕煎┑鍡忔寖闂佽鍠栭妶鎼佸蓟濞戞瑦鍎熸繛鎴炃氶崑鎾斥攽閸℃瑦娈鹃梺姹囧灮椤牓鎮為崹顐犱簻闁圭儤鍨甸顏堟煃闁垮鐏撮柟顔筋殜閹倿骞栨担璇♀偓宥呪攽閻橆喖鐏拑鍗炃庨崶褝韬€规洜顭堣灃濞达絽鎼獮宥嗕繆閵堝洤啸闁稿鐩幃妯衡攽鐎ｎ偄鈧爼鏌ょ喊鍗炲幋闁稿鎸鹃幉鎾礋椤掑偆妲伴梺姹囧焺閸ㄧ晫鎹㈠┑瀣祦闁告劑鍔夐弸搴ㄦ煙閹咃紞妞ゆ柨鐭傚娲捶椤撶偛濡洪梺鐟版啞閹倸鐣峰┑瀣婵°倓璁查幏濠氭⒑缁嬫寧婀伴柣鐔濆泚鍥晜閻ｅ瞼鐦堥梺閫炲苯澧撮柡灞芥椤撳ジ宕ㄩ銈囧惞闂傚倷绶氬褔鎮ч崱娑樼閻庯綆浜堕悞浠嬫煛瀹ュ骸骞楅柣鎾跺Т閳规垿顢欓挊澶婎潓闂侀€炲苯澧繛鑼枙濡垹鈹戦绛嬬劸闁糕晜鐗犻幃锟犲閳ヨ尙绠氬銈嗙墬閻熴劑顢楅悢闀愮箚妞ゆ劦鍓欓々顒勬煙閸欏鍊愰柟顔ㄥ洤閱囨繝闈涚墢閹虫牠姊绘担鍛婃儓闁瑰啿绻橀幃锟犳晸閻樿尪鎽曞┑鐐村灦鑿ゆ俊鎻掔墦閺屾稑螖閸愩劋娌梺璇茬箰缁夌懓顫忓ú顏勪紶闁靛鍎涢敐澶嬬厱闁哄啠鍋撴い銊ョ墕鍗遍柟鐗堟緲缁犲鎮楀☉娅亪顢撻幘缁樷拺闁告稑锕︾粻鎾绘倵濮橆剚鍤囬柡浣瑰姍瀹曨亝鎷呴崫鍕毄闂傚倷娴囧畷鐢稿窗閹惧瓨娅犳俊銈呮儰婢舵劖鍋愰柛蹇撴噽缁犳岸姊洪崨濠勬噧妞わ富鍨遍幈銊ヮ吋閸♀晜顔旈梺缁樺姈濞兼瑥霉椤旂瓔娈介柣鎰儗閻掍粙鏌嶈閸撶喎顭囪楠炴顭ㄩ崱妞诲亾閹绢喗鈷掗柛灞捐壘閳ь剟顥撳▎銏狀潩椤掑鍔烽悷婊勬閸ㄩ箖鏁冮崒姘跺敹闂侀潧顦崕鎶芥晬閻斿吋鈷戦柟顖嗗嫮顩伴梺绋款儏濡繈濡撮崨瀛樺€婚柤鎭掑劤閸樼敻姊婚崒姘偓鎼侇敋椤撱垹绀夌€广儱顦伴悡鍐⒑閸噮鍎忛柣蹇撶摠閹便劍绻濋崘鈹夸虎濡炪們鍨哄ú鐔煎极閹版澘鐐婇柕澶堝灩娴滈箖鏌熼悜姗嗘畷闁绘挸鍟撮幃宄扳枎韫囨搩浠煎┑鐐存儗閸ｏ綁寮婚敍鍕勃闁告挆鍕灡闁诲孩顔栭崳顕€宕滈悢椋庢殾缂佸顕抽弮鍫濈劦妞ゆ巻鍋撴い鏇稻鐎佃偐鈧稒菤閹疯櫣绱撴笟鍥х仭婵炲弶锕㈠鎯般亹閹烘挾鍘遍柣搴秵閸嬪懐浜搁鐔翠簻妞ゅ繐瀚弳锝呪攽閳ュ磭鍩ｇ€规洖宕灃闁告劦浜濋崳顖炴⒒閸屾瑧鍔嶉悗绗涘厾娲煛閸屾瑧绠氶梺鎼炲劗閺呮盯宕瑰┑瀣厸闁告劑鍔庢晶娑欍亜閵夈儳澧涚紒缁樼☉鑿愭い鎺嗗亾闁诲浚鍣ｉ弻鐔兼惞椤愶絽纾抽梺鐐藉劵缁犳挻淇婇幖浣哥厸濞达絼璀﹀Σ瑙勪繆閻愵亜鈧牠骞愰悙顒佸弿闁绘垼妫勯崒銊╂煙閻戞﹩娈曢柍閿嬪笒闇夐柨婵嗙墕琚氶梺闈涙閸熸壆妲愰幒鏃€濯奸柛锔诲幘閻﹀牓鎮楃憴鍕濠电偛锕顐﹀箛閺夊灝鑰块梺鍝勬川婵兘鎮炬ィ鍐┾拻濞达綀娅ｇ敮娑㈡煕閵娧冨付閾荤偤鏌涢弴銊ョ仭闁稿鍊圭换娑㈠箣濞嗗繒浠鹃梺缁樻尰濞茬喖骞冨鈧幃娆撳箵閹哄棙瀵栭梻浣规た閸樺ジ鏁冮妷鈹库偓鍐Ψ閳哄倸鈧兘鏌ょ喊鍗炲姰鐟滃酣骞堥妸锔剧瘈闁告洦鍘肩粭锟犳⒑閻熸澘妲婚柟铏姉閸掓帒鈻庤箛濠冪€婚梺缁樺姦閸擄箑螞韫囨稒鈷掗柛灞剧懆閸忓瞼绱掗鍛仸妤犵偞鍔欓獮鏍ㄦ媴閻熼缃曢梻浣筋潐閸庡磭澹曢銏犳辈闁挎洖鍊归悡娆撳级閸繂鈷旈柣锝堜含缁辨帡鍩€椤掑倵鍋撻敐搴′簴濞存粍绮撻弻鈥愁吋閸愩劌顬夐梺姹囧妽閸ㄥ爼濡甸崟顖涙櫆閻犲洤寮堕悵婵嗏攽椤旂》鏀绘俊鐐舵铻為柛鎰╁妷濡插牊鎱ㄥ鍡楀⒒闁哄棭鍋呯换婵堝枈濡椿娼戦梺绋款儏鐎氼噣鍩€椤掍胶鈻撻柡鍛箘閸掓帞鈧綆浜堕崥瀣煕濠娾偓閼冲爼宕ｉ崱娑欌拺闁告挻褰冩禍鐐烘煕閻樿櫕宕岀€规洏鍨介獮鏍ㄦ媴閸忓瀚奸梻浣侯攰閸嬫劙宕戝☉銏犵婵せ鍋撻柡灞剧⊕閹棃濡舵径濠冩嚈濠电儑绲藉ú銈夋晝椤忓嫮鏆︽俊銈呮噺閸ゅ啴鏌嶉崫鍕灓闁哥喎閰ｅ缁樻媴閸涘﹤鏆堟繛鎾寸椤ㄥ﹤鐣烽姀銈呯闁归偊鍏橀崑鎾诲箻椤旇В鎷绘繛鎾村焹閸嬫捇鏌嶈閸撴盯宕戝☉銏″殣妞ゆ牗绋掑▍鐘炽亜閺嶃劎鈼ゅù婊勭矒閺岋繝宕橀敐鍛闂備胶绮〃鍫熸叏閹绢喗鍋╅柣鎴ｆ缁狀喚绱掑☉姗嗗剱闁哄拋浜娲焻閻愯尪瀚板褜鍣ｉ弻锝夋晲閸涱厽些濡炪値鍘归崝鎴濈暦婵傚憡鍋勯柧姘€婚惄搴㈢節绾板纾块柛瀣洴椤㈡牠宕ㄩ妤€浜炬繛鎴炲笚濞呭懘鏌嶇紒妯诲鞍闁靛牞缍佸畷姗€鍩為悙顒€顏归梻鍌欑閹诧繝骞愰弰蹇嬩汗闁告劏鏅濋々鍙夌節闂堟稒宸濈紒鐘荤畺閺屾稑鈻庤箛锝嗩€嗛梺鍏煎濞夋洟鍩€椤掍緡鍟忛柛鐘愁殙閵囨劙宕橀鍏夊亾閿曞倸惟闁宠桨绀佺粣娑橆渻閵堝棛澧紒顕嗙悼濡叉劙宕ｆ径宀€鐦堥梺姹囧灲濞佳勭閿曞倹鐓曢柕濞垮劤閸╋綁鏌℃担绋挎殻闁糕晪绻濆畷銊╊敇閻欏懐鍚归梻鍌氼煬閸嬪嫬煤閿曞倸绠悗锝庡幑娴滃綊鏌熼悜妯诲碍濞存粌缍婂娲箚瑜庣粋瀣煕鐎ｂ晝鍔嶇紒鍌涘浮婵偓闁绘﹩鍋呴弬鈧俊鐐€栧濠氬Υ鐎ｎ喖绀夐柣鏃囨绾惧吋銇勯弴鐐村櫣闁诲骏闄勯〃銉╂倷閼碱剛顔掗悗瑙勬磸閸旀垵顕ｉ崼鏇炵婵犻潧鐗忓畷鐑樼節閻㈤潧啸闁轰礁鎲￠幈銊╁箻椤旇偐锛欓梺鑽ゅ枑婢瑰寮搁弮鈧穱濠囶敍濠靛棔姹楃紒鎯у綖缁瑩寮诲☉姘勃闁告挆鍕珮闂佽崵濮甸崝鎺楀础閹惰棄钃熸繛鎴欏灪閸嬫劗鈧娲栧ú銈夊煕瀹€鍕拺閻犲洠鈧磭浠╅梺娲诲幖閸婃悂鎮鹃悜钘夌婵°倓绀侀埀顒傚厴閺屻倗鍠婇崡鐐差潾闂佸搫妫旈崡鎶藉蓟閿濆棙鍎熼柍銉ュ暱鏉堝懘姊虹粙娆惧剱闁圭懓娲璇测槈閵忕姴宓嗛梺闈涱焾閸庢壆鑺辨禒瀣拺闁圭娴烽埊鏇犵磼椤旇姤灏い顐㈢箻閹煎綊宕烽鐙呯床婵犵妲呴崹浼村箹椤愶讣缍栭柟杈鹃檮閻撶喖鐓崶銊﹀暗缂佺姵鐓￠弻锝夋偄閸欏鐝氶梺闈涙缁€渚€鍩㈡惔銊ョ鐎规洖娴傞崥鍛存⒒娴ｇ懓顕滄俊顐℃祰椤ｉ箖姊鸿ぐ鎺撴暠婵＄偠妫勯～蹇涙惞閸︻厾鐓撻柣鐘充航閸斿酣顢欓幋锔解拺缂佸顑欓崕鎰版煕閺冣偓閻燂附绌辨繝鍥ч唶闁哄洨鍋熼鎺戭渻閵堝棙鈷掗柡鍜佸亰瀹曘垽骞栨担鍏夋嫼闂佸憡绋戦敃锝囨闁秵鐓曢柣妯哄暱閸濇椽鏌熼姘拱缂佺粯绻堝畷鍫曞Ω瑜嶉獮妤呮⒒娴ｇ懓顕滅紒璇插€胯棟濞村吋娼欓弸渚€寮堕崼姘澒闁稿鎹囧畷褰掝敃閿濆洤鍤掗梺璇插閸戝綊宕抽敐澶婃槬闁逞屽墯閵囧嫰骞掗幋顖氬缂備椒鑳堕崗姗€寮诲☉銏犳婵炲棙鍎抽崜鎶芥⒑婵傚摜绱板鏉戞憸閹广垹鈹戦崱鈺傚兊濡炪倖鎸荤粙鎺斺偓姘偢濮婄粯鎷呴崨濠傛殘缂備浇顕ч崐濠氬焵椤掍礁鍤柛鐘崇洴閸╁懓銇愰幒鎾嫽婵炶揪绲介幉锟犲疮閻愮儤鐓涢悘鐐额嚙婵″潡鏌熼獮鍨伈妤犵偛顑夐幃鈺呮濞戞袝闂傚倷鑳剁划顖炲蓟閵娾斂鈧啯鎯旈埥鍡欏姺闂侀潧艌閺呮粓鎮￠崘顏呭枑婵犲﹤鐗嗙粈鍫ユ煟閺傛娈犻柛銈嗘礀閳规垿鎮╁畷鍥舵殹闂佸搫鎳忛幃鍌炲蓟閿濆憘鐔烘嫚閼碱剛銈风紓鍌欑劍閸旀牜绮欓幋锔光偓鏃堝礃椤斿槈褔鏌涢埄鍏︽岸骞忔繝姘拺缂佸顑欓崕鎰版煙閻熺増鎼愰柣锝囧厴閹煎綊顢曢姀鈺佹闂佽瀛╃粙鎺曞綔闂佸綊鏀卞钘夘潖濞差亜宸濆┑鐘插閻ｇ敻鏌ｆ惔銏犲毈闁告ê銈搁弫鍐閳ユ剚鍤ら柣搴㈢⊕椤洭宕㈡禒瀣拺闁告劕寮堕幆鍫ユ煥閺囨ê鈧繈骞冨鈧幃鈺呮倷閹存帞鐩庨梻浣告惈濞村倹绂嶉悙鐢电煋妞ゆ柨顫曟禍婊堟煏韫囧﹥顫婃繛鍫熺矌閳ь剝顫夊ú妯兼暜閹烘鐓″璺好￠悢鍏煎亗閹兼番鍔岃ぐ娆撴⒒閸屾艾鈧悂宕愭搴ｇ焼濞达綁娼婚懓鍧楀级閸碍娅呴柛銊︾箖閵囧嫰寮介妸褏鐓侀梺鍝勬缁捇寮诲澶婁紶闁告洦鍓欏▍銈夋⒑缁嬪尅鍔熼柡浣割煼瀵鍩勯崘銊х獮闁诲函缍嗘禍鐐寸閸洘鈷戦悶娑掆偓鍏呭濠电偛顕慨鎾敄閸℃稒鍋傞柣鏂挎啞閸欏繑淇婇妶鍌氫壕濠碘槅鍋呴〃鍡欑矉瀹ュ應鏀介柛鈥崇箲閺傗偓婵＄偑鍊栭悧妤呮偡閵夈儳鏆ら柛鈩冪⊕閻撴盯鎮橀悙鎻掆挃婵炴彃顕埀顒侇問閸犳骞愰搹顐＄箚闁归棿绀佸敮闂侀潧锛忕仦鑺ユ珨闂傚倸鍊搁崐鐑芥嚄閸撲礁鍨濇い鏍仜缁犱即鏌熼梻瀵歌箞闁搞儺鍓氶ˉ鍫熺箾閹达綁鍝虹紓宥呴叄濮婅櫣绱掑Ο铏逛桓闁藉啫宕埞鎴︻敊閻ｅ瞼鐓夐梺鍝勭灱閸犲酣鍩㈤幘璇插瀭妞ゆ梻鏅ぐ顖涚節绾版ǚ鍋撻搹顐熸灆闂佸摜濮靛銊ノｉ幇鏉跨閻庢稒锚椤庢捇姊洪崨濠冨碍鐎殿喛鍩栭弲銉╂⒒閸屾瑨鍏岄柟铏崌楠炲鍩勯崘顏嗩啎婵犵數濮村ú銊ョ暤娓氣偓閺屾盯骞囬棃娑欑亪缂備胶濮靛銊╁箟閸涘﹤绶為柟閭﹀墰閸濇绻涚€电孝妞ゆ垵妫濆畷鎰版偨閸涘﹦鍙嗗┑鐘绘涧濡盯宕欓崷顓犵＜闁靛鍔岃闂侀潧娲ょ€氫即寮崒鐐蹭紶闁告洦鍋掗悗铏繆閻愵亜鈧倖绂嶅鍫濈柈閻庢稒眉缁诲棝鏌涢锝嗙鐎瑰憡绻冮妵鍕冀閵娧呯厾闂佸摜鍋犻崺鏍崲濠靛牆鏋堟俊顖涙た濞兼垿姊虹粙娆惧剱閻㈩垪鈧磭鏆﹂柨婵嗩槸缁€鍐煏婵炑冨椤旀洘淇婇悙顏勨偓鏍偋濠婂牆纾绘繛鎴欏灪閸婂嘲鈹戦悩鎻掓殧濞存粍绮撻弻鐔煎传閸曨厜銉︺亜閺傛妯€闁哄瞼鍠栭弻銊р偓锝庡亖娴犮垹鈹戦纭锋敾婵＄偘绮欓獮鍐焺閸愨晛鍔呭銈嗘⒒閺咁偆绮欓幇鐗堚拻濞达絼璀﹂悞楣冩煥閺囨ê鍔氶悡銈夋煛瀹ュ骸骞楅柛瀣ㄥ€栭妵鍕箻鐠虹儤鐏佺紓浣叉閸嬫捇姊绘担鍦菇闁搞劏妫勯…鍥槼缂佸倹甯掗…銊╁醇閻斿搫骞楁俊鐐€曠换鎰板疮椤愩垻鏆ら柛鈩冪憿閸嬫挾鎲撮崟顒傤槰闂佸憡姊瑰ú鐔煎春閻愬搫绠ｉ柣姗嗗亜娴滈箖鏌ㄥ┑鍡欏嚬缂併劋绮欓弻锝夋晲閸涱喗鍎撻梺瀹狀潐閸ㄥ潡骞冨▎鎾崇煑濠㈣泛妫欓悘鍡椻攽閻愯尙鎽犵紒顔肩Ф閸掓帒顓兼径濠勶紵濡炪倖鍔ч梽鍕煕閹烘垯鈧帒顫濋敐鍛婵犵數鍋橀崠鐘诲炊娴ｅ憡鍠樻い銏＄洴閹瑩鎳犻澶嬓熼梻鍌欐缁鳖喚寰婃禒瀣剶闁兼祴鏅濋惌鍡椻攽閻樻彃鈧爼鍩€椤掍礁绗掓い顐ｇ箞閺佹劙宕ㄩ鈧ˉ姘舵⒒閸屾瑨鍏岀紒顕呭灡缁楃喎螖閸涱厾鐛ュ┑顔筋焾濞夋盯鎮為崹顐犱簻闁圭儤鍩婇崝鐔虹磼婢跺本鏆柡灞剧洴閹晠骞囨担鍦澒闁诲氦顫夊ú姗€宕濆▎鎾崇畺婵犲﹤鐗婇崵宥夋煏婢诡垰鍟粻鐗堢節閻㈤潧袨闁搞劎鍘ч埢鏂库槈閵忊晜鏅為梺鍛婄☉閻°劑宕愰崹顔ユ棃鏁愰崨顓熸闂佺粯鎸搁崯浼村箟缁嬫鐓ラ柛顐ｇ箘椤︻厼鈹戦绛嬬劸婵炲绋撶划濠氬蓟閵夛妇鍘遍梺闈涱槹閸ㄧ敻寮甸鍌滅閹兼番鍔嶉埛鎴︽煙椤栧棗鎳愰鍥р攽閻橆偄浜鹃柡澶婄墐閺呮盯藟濮樿埖鐓曢煫鍥ㄧ⊕閿涚喓绱掔拠鍙夘棡闁靛洤瀚板浠嬪Ω瑜滈弳锛勭磽娴ｇ鈧悂顢栭崨瀛樼畳婵犵數濮撮敃銈囪姳婵傚憡鐒芥い鏍ㄤ緱濞堜粙鏌ｉ幇顓炵祷闁哄棙鐟╅幗鍫曟晲閸涱偀鍋撻幒鎴僵闁绘挸娴锋禒顓㈡⒑缁嬭法肖闁轰浇顕ч～蹇撁洪鍕槯闂佺绻掗崢褔鍩€椤掍礁濮堢紒缁樼⊕閹峰懘宕橀幓鎺濅紑濡炪倐鏅涢崲鏌ュ煘閹达箑纾兼慨姗嗗幖閺嗗牓姊虹紒妯诲鞍缂佸鍨块垾锔炬崉閵婏箑纾梺缁樼濞兼瑦鎱ㄥ☉娆戠瘈闁冲皝鍋撻柛鏇ㄥ亜椤帡姊洪崫鍕効缂佺粯绻傞悾鐑藉箳閹存梹鐎婚梺鐟邦嚟婵嘲鐣烽弻銉︾厽閹兼番鍊ゅ鎰箾閸欏鑰跨€规洖缍婂畷绋课旈崘銊с偊婵犳鍠楅妵娑㈠磻閹剧粯鐓欓柧蹇ｅ亞閻帗淇婇銏犳殭闁宠棄顦埢搴ㄥ箣閺傚じ澹曞銈嗘尪閸ㄦ椽鍩涢幒鎳ㄥ綊鏁愰崨顔兼殘闂佸摜鍠撻崑鐐垫崲濞戞碍瀚氱憸蹇涙偩閻㈢鍋撶憴鍕缂侇喖鐭傞崺銏℃償閵娿儳鐤€濡炪倖娲栭幊蹇曠矈椤愶附鈷掑ù锝囶焾閺嗛亶鏌熺喊鍗炰喊妤犵偛锕ㄧ粻娑樷槈濡厧骞堥梻浣烘嚀椤曨厽鎱ㄦ搴☆棜濠靛倸鎲￠崐鐢告煥濠靛棛鍑圭紒銊ㄦ闇夐柣姗嗗枛閻忣亪鏌曢崶褍顏鐐村笧閳ь剨缍嗘禍鐐寸婵傚憡鈷戦悗鍦濞兼劙鏌涢妸銉﹀仴妤犵偛鍟埢搴ㄥ箣閻愯尙褰撮柣鐔哥矋閸ㄥ灝鐣烽妷鈺婃晝闁挎棁妫勯埀顒傛暬閹嘲鈻庤箛鎿冧痪缂備讲鍋撻柛鎰ㄦ櫃缁诲棝鏌ｉ幇顖涚【鐞氭岸姊洪柅娑氣敀闁告梹鍨垮畷娲焵椤掍降浜滈柟鐑樺灥椤忣亪鏌ｉ幘鍗炲姕缂佺粯鐩獮瀣倶濞茶閭い銏℃椤㈡﹢鎮㈤崜浣虹暰缂傚倸鍊烽梽宥夊垂瑜版帒鍑犻柕鍫濇川绾惧ジ寮堕崼娑樺閻忓繋鍗抽弻鐔风暋閻楀牆娈楅悗瑙勬礃缁捇鐛幘璇茬闁瑰瓨绻嶅Λ鎰節閻㈤潧啸闁轰焦鎮傚畷鎴濃槈閳跺搫娲璺何涢崹顐ｃ仢闁诡喓鍨荤槐鎺戭潨閸℃﹫绱欏┑鐘殿暜缁辨洟宕戦幋锕€纾归柡宥庡幖缁€澶屾喐閺傛娼栧ù鐘差儏缁€瀣亜閺嶃劍鐨戦柛姗€浜跺铏规兜閸涱喖娑ч梻鍌氬鐎氫即宕哄☉銏犵婵°倓鑳堕崢鍗烆渻閵堝棗濮傞柛濠冩礋瀵悂寮崼鐔哄帾闂佺硶鍓濋敋缂佹甯楅妵鍕敇閳ュ啿濮峰銈忕畳濞呮洜鎹㈠☉銏犵煑濠㈢櫢绲鹃崹鍦垝濮橆厽缍囬柕濞у懐妲囬梻浣规偠閸庢挳宕洪弽顓炵柧婵犻潧顑嗛埛鎴︽煙缁嬫寧鎹ｇ紒鐘虫尰缁绘稓鎷犺閻ｇ數鈧娲濆▍鏇犫偓浣冨亹閳ь剚绋掕彜闁归攱妞介弻锝夋偐閸欏顦遍梺閫炲苯澧叉繛鍛礋閹﹢骞樼紒妯锋嫼缂備礁顑嗛娆撳磿閹达附鐓曢悗锝庡墮閺嬫棃鏌涢幒鎾崇闁逞屽墾缂嶅棝宕伴弽顐や笉闁规儼濮ら悡娑㈡煕鐏炲墽顣查柟顖氱墕闇夋繝濠傜墢閻ｆ椽鏌＄仦璇插闁宠鍨垮畷鍗炩槈閹典礁浜炬俊銈傚亾闂囧绻濇繝鍌涘櫣濞寸娀浜堕弻锛勪沪閸撗€妲堝銈庡亝缁捇宕洪埀顒併亜閹哄秷鍏屾い鈺傜叀閹娼幏宀婂妳濠电偛鍚嬮悧妤冩崲濞戞﹩鍟呮い鏃囧吹閻╁海绱撴担鍝勑￠柛妤佸▕閻涱噣寮介‖銉ラ叄椤㈡鍩€椤掑嫭鍊舵い鏇楀亾闁哄本绋戦埢搴ょ疀閺冩垶锛嗘繝娈垮枛閿曘儱顪冮挊澶屾殾闁绘垹鐡旈弫鍥ㄧ箾閹寸偟鎳冮柣婵嬩憾濮婄粯鎷呮笟顖滃姼濡炪倖鍨甸幊姗€鐛繝鍛杸闁哄洨濮烽悡鏃堟煛婢跺﹦澧戦柛鏂挎捣瀵囧焵椤掑嫭鈷戦柟鑲╁仜閸旀﹢鏌涢弬鑳闁崇粯鎹囬獮鍥偋閸碍瀚奸梻浣告啞閸旀洖顕ｉ崼鏇炵畾闁割偁鍎查悡鏇炩攽閻樻彃鏆為柛濠冨姉閳ь剚顔栭崰妤呭箖閸岀偟宓侀悗锝庡枟閺呮粓鎮峰▎娆戠ɑ閻庢艾銈稿缁樻媴閸涘﹤鏆堢紓浣筋嚙閸婂鍩€椤掍浇澹橀柛銏″絻瀹撳嫰鏌ｉ悢鍝ユ噧閻庢哎鍔嶇粋宥咁煥閸喓鍘甸柣搴ｆ暩椤牊绂掕閺岀喖宕橀幓鎺撴閻庤娲╃换婵嬪蓟閸℃鍚嬮柛鈩冪懃瀵即姊绘繝搴′簻婵炶绠撻獮鎰版嚒閵堝棗顏搁梺鎸庣☉鐎氼喖螞椤栫偞鐓欐い鏍ф閸燁垶宕愰鐐粹拺闂傚牊绋掗幖鎰版倵濮橆厽绶叉い鏇秮椤㈡岸鍩€椤掆偓閻ｇ兘骞掗幋鏃€顫嶅┑鐐叉閸ㄩ潧鈽夎濮婂宕掑▎鎺戝帯闂佺娅曢幑鍥х暦椤栫偛鍨傛い鏃€纰嶅浠嬨€佸鈧慨鈧柣妯煎劋閹蹭即姊绘担铏瑰笡婵﹤顭烽崺娑㈠醇閵夈儲鐎繝鐢靛Т濞诧箓鎮￠悢鍏肩叆婵犻潧妫欓崳鐑樼節閳ь剚瀵肩€涙鍘遍梺鎸庣箓妤犵鈻嶅鍡樺弿濠电姴鍟妵婵嬫煙椤旀儳鍘寸€殿喖澧庨幑鍕Ω閳哄啫绀堥梻鍌氬€烽懗鍫曞箠閹捐绠熼柍鈺佸暟缁犳儳鈹戦悩鎻掍簽闁搞倖娲橀妵鍕箛閸撲胶鏆犵紓浣哄У閻╊垶寮婚埄鍐ㄧ窞濠电姴瀚搹搴ｇ磽娴ｇ懓濮堢紒瀣灴閳ユ棃宕橀鍢壯囨煕閳╁喚娈旀繛鍏煎灴濮婅櫣绮欏▎鎯у壉闂佸湱顭堥…閿嬩繆?")
        if weak_spots:
            if localized_weak_spot:
                lines.append("")
            else:
                lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙绐涢梺鍝ュУ閹稿墽鍒掔紒妯稿亝闁告劏鏅濋崢浠嬫⒑闁稑宓嗘繛浣冲嫭娅犳い鏍仦閻撶喐绻濋棃娑欏缂佲偓鐎ｎ偅鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噧闁宠閰ｉ獮鍡氼槻濠㈣锚閳规垿鎮欓懠顒佹喖缂備緡鍠氭慨鐢电矉瀹ュ鏁傞柛鏇㈡涧濞堛劑鏌ｉ悩鍙夊缂佷焦娼欏嵄闁割偁鍎查悡蹇涚叓閸ャ劍绀€閸熸悂姊洪崨濠冣拹闁圭鍟块～蹇撁洪鍕獩婵犵數濮撮崐姝岊杺婵犵數鍋涢悺銊у垝瀹ュ洦宕查柛顐ｇ箘閺嗭箓鏌熼幆鐗堫棄閸烆垶姊洪崘鍙夋儓闁稿﹦鏁婚獮蹇涙惞閸︻厾锛濋梺绋挎湰閻熝囧礉瀹ュ鐓ユ慨妯夸含绾惧吋淇婇妶鍕槮婵炴惌鍣ｉ弻锛勪沪鐠囨彃顫囬悗娈垮枟閹歌櫕淇婇幖浣肝у璺猴梗缁綁姊虹拠鎻掝劉妞ゆ梹鐗犲畷浼村冀椤撴稈鍋撻敃鈧悾锟犳焽閿曗偓濞堛劑姊洪崷顓℃闁哥姵鐗犻敐鐐哄川鐎涙鍘藉┑鈽嗗灡椤戞瑩宕靛▎鎾寸厸濞达絿鐡斿鎰磼缂佹绠為柟顔荤矙濡啫鈽夐幒鎾垛偓鐗堢節閻㈤潧浠掗柛鏍█瀹曟鎮╅搹顐犱虎婵犵鈧磭鍩ｇ€规洏鍔戦、鏃堝川椤栨浜炬繛宸簼閳锋垿鏌熺粙鎸庢崳缂佺姵鎸婚妵鍕晜閸喖绁悗瑙勬礃閸旀瑩骞冩禒瀣窛濠电姴瀚獮妤呮⒒娓氣偓濞佳呮崲閸儱纾归柡宓偓濡插牏鎲告惔銊ノ﹂柛鏇ㄥ灡閺呮煡鏌涘☉鍗炰簻濞寸媭鍣ｅ娲传閸曨厾浼囬梺鍝ュУ閻楃娀鐛崘顔藉€婚柤鎭掑劚娴滈亶姊洪崜鎻掍簼缂佽鍟撮幃妯绘償閵婏妇鍘介柟鍏肩暘閸╁嫰宕箛娑欑厱闁绘ê纾ú瀛樸亜閵忊€蹭孩妞わ箑缍婇弻娑㈠煘閸喖濮曢悗鍨緲鐎氫即鐛崶顒夋晢濠㈣泛顑囩粔閬嶆⒒閸屾瑨鍏岀紒顕呭灥閹筋偄顪冮妶鍡樷拹闁绘濮撮悾鐑筋敆閸曨剙鈧粯淇婇婵嗕汗闁伙箑鐗撳鍝勑ч崶褏浼堝┑鐐板尃閸パ呭幒闂佸壊鍋嗛崰鎾剁不閹灐褰掓晲閸涱厽姣愰梺鍛婄閿氶柍钘夘樀婵偓闁绘鏁稿澶愭⒒娴ｄ警鐒鹃柡鍫墰閹广垽宕掑杈ㄧ槗婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ姀銈嗘锭闁哄鐗忛埀顒€绠嶉崕閬嵥囬鐐村亗闁哄洢鍨洪悡娆撳级閸儳鐣烘俊缁㈠櫍閺岋綁骞樼€涙顦ㄧ紓浣虹帛缁诲牆螞閸愩劉妲堟慨妤€妫旈幃锝夋⒒娴ｅ憡鍟炴慨濠勬嚀閻ｆ繈骞栨担姝屾憰闂佽法鍠撴慨鎾嵁閵忥紕绠鹃柟瀵稿剱濞堟洟鏌涢悩鍐插摵婵﹥妞藉畷顐﹀礋椤掍焦瀚崇紓鍌欑椤戝棝骞戦崶顒€鏄ラ柍褜鍓氶妵鍕箳閹搭垰濮涚紓浣割槺閺佸寮诲☉姘ｅ亾閿濆簼绨奸柛锝呯秺閺岋綁鏁愭径妯活棖婵炲濯寸粻鎾诲箖濞嗘搩鏁嗛柍褜鍓欓锝夊箰鎼达絿鐦堥梺姹囧灲濞佳冪摥闂備礁鎽滈崳銉╁垂閼稿吀绻嗛梻鍫熺▓閺€浠嬫煕閵夈劌鐓愭い鏃€妫冨铏圭磼濡搫顫屽銈嗘处閸樹粙寮查崼鏇熷仺闁告稑锕﹂崢闈涱渻閵堝棙鈷掗柡鍜佸亰楠炲﹪宕堕…鎴烆啍闂佺粯鍔曢悺銊ョ暦鐏炵虎娈介柣鎰綑濞搭喗顨ラ悙璇ц含闁硅櫕绮撳Λ鍐ㄢ槈濮橆偆绀夊┑鐘愁問閸犳牠鏁冮敂鎯у灊妞ゆ牜鍋涚粻顖炴煕濞戝崬鏋ら柣鐔活潐閵囧嫰寮介妸褏鐓€婵犳鍠栭崥瀣┍婵犲洦鍊锋い蹇撳閸嬫捇寮介鐐茬€梻鍌氱墛閸忔艾鈽夊Ο閿嬫杸闁诲函缍嗘禍鐐烘偩妤ｅ啯鈷戦柛娑橈攻婢跺嫰鏌涢妸銉ｅ仮鐎殿噮鍋勯濂稿幢濡搫浼庢繝纰樻閸ㄦ澘顭囬敓鐘蹭紶闁绘垶顭囩粻楣冩煕椤愮姴鍔ら柣锝囧劋閹便劍绻濋崘鈹夸虎閻庤娲忛崝宥囨崲濠靛绀嬫い鎾跺У濞堝ジ姊绘担绛嬪殭閻庢稈鏅犲畷娆掋亹閹烘垿妫烽梺鎸庣箓閹峰宕甸弴銏＄厵闁诡垳澧楅ˉ澶嬵殽閻愵亜鐏紒缁樼洴楠炲鎮欓崹顐㈡珮闂備礁鎲￠敃銏＄鐠轰警娼栨繛宸簻娴肩娀鏌涢弴銊ュ闁稿绉瑰娲川婵犲啰鍙嗛梺鍝勭墱閸撴稓鍒掔€ｎ亶鍚嬪璺侯儏閳ь剛鍏橀幃閿嬫媴妞嬪寒妲紓鍌氱Т閿曨亪鐛崘顔肩労闁告劏鏅涢崝鍛渻閵堝棙鈷掗柛妯犲嫮鐝堕柛顐犲劜閳锋帒霉閿濆懏鎲搁柡瀣暞閵囧嫰顢曢姀鈺傗枅閻庤娲栫紞濠傜暦缁嬭鏃堝焵椤掑倻涓嶉柡宥庡幗閻撳啴鏌涘┑鍡楊仼闁哄棛鍋ら幃妤€顫濋鐔烘闂佺灏欓…鍫ヮ敇婵傜骞㈡俊銈咃工濞堝ジ姊绘担鍝ョШ闁稿锕畷妤€顫滈埀顒€顕ｉ妸锔绢浄閻庯綆鍋嗛崢鎾绘⒑閼恒儍顏埶囨导姝ゅ顭ㄩ崗鐘垫嚀椤劑宕熼鐘垫毉缂傚倷娴囨ご鍝ユ暜閻愬搫鐒垫い鎺戯功缁夌敻鏌涚€ｎ亝鍣藉ù婊勬倐閹粙宕ㄦ繝鍕箞闂備礁婀遍崕銈夊箰閸濄儳绠旀慨妯夸含绾捐偐绱撴担璇＄劷缂佺姵鎸婚妵鍕敃閿濆洨鐤勫銈冨灪閿曘垽骞冮埡鍛闁圭儤鎹佺欢銏ゆ⒒閸屾艾鈧嘲霉閸ヮ剦鏁嬬憸鏂跨暦濞嗘挻鍋╃€光偓閳ь剛绮堟繝鍥ㄧ厱闁斥晛鍟伴埥澶岀磼閳ь剟宕奸悢铏诡啎闂佺懓鐡ㄩ悷銉╂倿濞差亝鐓涘ù锝夋交闊剟鏌″畝瀣瘈鐎规洖鐖兼俊鐑藉Ψ瑜岄惀顏堟⒒娴ｈ櫣甯涢柟鎼佺畺瀹曚即寮介鐔蜂簵濡炪倖鍔х粻鎴︽倷婵犲洦鐓忓┑鐘茬箰椤╊剚銇勯敂鍝勫姕缂佺粯绋撻埀顒傛暩椤牊鐗庣紓鍌欑贰閸犳骞戦崶顒傚祦闁告劑鍓弮鍫濈劦妞ゆ帒瀚哥紞鏍ㄧ節闂堟侗鍎忛崬顖炴⒑闂堟侗妲堕柛搴℃惈椤洦鎯旈妸锔惧幗闁瑰吋鐣崐銈咁焽閹邦厾绠鹃柛娆忣檧閼拌法鈧娲樼换鍌炲煝鎼淬劌绠涙い蹇撴閻ｉ箖姊绘担绋挎倯闁诡喖鍊搁…鍥槾婵炲棎鍨介幃娆徝圭€ｎ偅鏉搁梻浣虹帛閿氱€殿喖鐖煎畷瀹犮亹閹烘挾鍘介梺瑙勫礃閹活亪鎳撻幐搴㈠弿濠电姴鍟妵婵嬫煙缁涘湱绡€濠碘€崇埣瀹曘劑顢欓柨顖氫壕濡わ絽鍟埛鎴︽煠婵劕鈧洟寮搁崒鐐寸厱閹兼番鍨归埢鏇㈡煕閳规儳浜炬俊鐐€栫敮濠勭矆娓氣偓瀹曠敻顢楅崟顒傚幈闂佺粯顭堝▍鏇㈡儍閹达附鐓曢柟鐑樻尭缁椦呯磼鏉堛劌绗掗摶锝囩磼鐎ｎ亗浠掔紒銊ャ偢濮婄粯鎷呴崨濠傛殘闂佸憡鏌ㄧ换妯侯嚕閹绘巻鏀介悗锝庝簻閸嬪秹姊哄Ч鍥х仼闁硅绻濋崺娑㈠箣閻樺灚锛忓銈嗘尵閸嬬偞鍒婇崗鑲╃闁稿繒鍘ф慨宥夋煛鐏炲墽娲寸€殿噮鍣ｉ崺鈧い鎺戝閸嬪鏌ｅΟ娆惧殭缂佺姵鐗犻弻锝夊閻樺樊妫岄梺杞扮閸婂潡寮诲☉銏╂晝闁靛牆鎳忛悘渚€姊洪崨濠忚€垮ù婊嗘硾椤繐煤椤忓嫮顔囬柟鑹版彧缁插潡鎮鹃悽鍛娾拺缂備焦锕╁▓鏃€淇婇锝囩煉闁靛棗鍊婚幑鍕Ω瑜忛敍婵嬫⒑缁嬫寧婀伴柣鐔村姂瀹曟鐣濋埀顒傛閹烘鏁嬮柛娑卞幘娴犳悂姊虹拠鈥崇仩閻庢矮鍗抽妴浣糕槈閵忊€斥偓鐑芥煛婢跺鐏ｇ紒銊ョ仛娣囧﹪鎮欓鍕ㄥ亾閺嶎厼绀夌憸蹇涘焵椤掑嫭娑ч柣顓炲€搁锝夘敃閿曗偓閻愬﹥銇勯幒宥堝厡闁告ü绮欏楦裤亹閹烘垳鍠婇梺鎼炲妺閸楁娊骞嗛崘顭嬫椽顢旈崨顖氬妇闂備礁澹婇崑鎺楀磻閸曨偀鏋嶇€广儱顦伴悡娑氣偓鍏夊亾閻庯綆鍓涜摫闂備浇顕栭崹鍗炍涢崘鈺傚弿闁逞屽墴閺屽秵娼幍顔煎濠电偛鎳忛惄顖氼潖缂佹ɑ濯撮柛娑橈攻閸犳劖绻濆▓鍨珝婵炰匠鍛疾婵犵數濮撮敃銈夋偋閸℃瑧鐭嗛柛鈩冪⊕閻撴瑩鏌ｉ幋鐏活亪鎮樺澶嬬厸閻庯綆浜崣鍕煟閹垮啫浜扮€规洖鐖兼俊鎼佹晜缂併垺袨濠电姷鏁搁崑娑㈡偋閹惧墎涓嶉柡宓本缍庨梺鎯х箺椤鈧碍宀搁弻宥夊Ψ閵壯嶇礊婵炲濮甸幃鍌氼潖閾忓湱鐭欐繛鍡樺劤閸撲即姊洪幐搴㈢８闁稿﹥娲栭悾鐢稿礋椤掑倻鐦堥梻鍌氱墛缁嬫垿鍩€椤掍焦鍊愭鐐差樀閺佹捇鎮╅懠顒€骞堥梻浣烘嚀椤曨參宕戦悙鍝勭煑闊洦绋掗悡鐔兼煟閺傛寧鎯堟い锝呫偢閺岀喖宕楅悡搴☆潓闂佸疇顫夐崹鍧楀垂妤ｅ啯鍤戞い鎺戝€婚崢顖炴⒒娴ｅ憡鎯堥柡鍫墴閹嫰顢涘☉妤冪畾闂佸綊妫跨粈浣告暜闂備焦瀵уú宥夊磻閹捐秮褰掓偐閾忣偄鍞夐梺璇″枟椤ㄥ懘鍩㈤幘璇插瀭妞ゆ梻鏅禍顏呬繆閻愵亜鈧倝宕㈡ィ鍐ㄧ婵せ鍋撻柣娑卞櫍瀹曟﹢顢欑喊杈ㄧ秱闂備線娼х换鎺撴叏閻㈠憡鍊甸柟鎯板Г閻撴稑顭跨捄鐚村姛濠⒀勫灴閺屾盯寮捄銊愩垽鏌嶇拠鑼х€规洖銈告俊鐑芥晜鐟欏嫬顏烘繝鐢靛仩閹活亞寰婇崸妤佸仱闁哄啫鐗嗛崥褰掓煕閹伴潧鏋熼柣鎾存礋閺屾洘绻涢崹顔煎Е闂佸憡鐟ョ€氼噣鍩€椤掑喚娼愭繛鍙夛耿閺佸啴濮€閳ヨ尙绠氶梺褰掓？缁€浣虹不濞戞瑣浜滈柟鎹愭硾娴犙兠归悩鍙夋喐缂佽鲸鎸婚幏鍛存惞閻熸壆顐肩紓鍌欐祰椤曆囨偋閹捐崵宓侀柛鎰ㄦ櫇椤╃兘鎮楅敐搴′航婵☆偄鍟埞鎴︽倷閺夋垹浠稿銈冨妼濡繂鐣烽崫鍕ㄦ闁靛繆妾ч幏缁樼箾鏉堝墽鍒伴柟璇х節瀹曨垶鎮欏ǎ顑跨盎濡炪倖鎸鹃崑鐐核夐姀鈶╁亾鐟欏嫭绀冮柛搴°偢钘濋柟缁㈠枟閻撴盯鎮橀悙鍨珪濠⒀嶉檮閹便劍绻濋崘鈹夸虎閻庤娲﹂崑濠傜暦閻旂厧鍨傛い鎰癁閸ャ劉鎷虹紓渚囧灡濞叉ê鈻嶉崨瀛樼厽婵°倓鐒︾亸顓㈡煟閿濆洤鍘撮柟顔炬櫕缁瑩宕归鑲┿偖闂傚倷绶氬褎顨ヨ箛鏇燁潟闁哄洢鍨归崒銊︺亜韫囨挻鍣界紒鈾€鍋撻梻浣圭湽閸ㄨ棄顭囪缁傛帟顦归柡灞剧〒閳ь剨缍嗛崑鍛焊椤撱垺鐓冮悹鍥皺鏁堥悗瑙勬礀瀹曨剟鍩ユ径濞炬瀻闁瑰瓨绻傜粻娲⒒閸屾瑧顦︽繝鈧柆宥呯？闁靛牆鎷嬪鏍煠婵劕鈧牠寮冲鍕闁瑰鍋為惃鎴犵棯閹规劕浜圭紒杈ㄦ尰閹峰懐鎷犻敍鍕Ш婵犵數鍋炶ぐ鍐偤閵娾斂鈧啴濡烽埡鍌氣偓椋庘偓鐟板閸犳牠宕滈崼鏇熲拺閻犲洠鈧櫕鐏嶉梺鑽ゅ暱閺呮盯鎮鹃悜钘夌闁绘劕绉堕崰鏍箹瑜版帗鐒绘繛鎴炴皑椤︻噣姊绘担绛嬪殭閻庢稈鏅犻、娆撳冀椤撶偟鐛ュ┑掳鍊撻懗鍓佺不閹€鏀介柣妯诲絻娴滅偤鏌涢妶鍡樼闁哄瞼鍠撶槐鎺楀閻樺磭浜俊鐐€ら崑鍕箠濮椻偓瀵顓兼径瀣弳濡炪倖鐗楅惌顔界珶閺囥垺鈷掑ù锝囧劋閸も偓闂佹悶鍨洪悡锟犵嵁閺嶎収鏁冮柨鏇楀亾闁绘挻锕㈤弻鐔告綇妤ｅ啯顎嶉梺绋匡功閸忔﹢骞冮悷鎳婃椽顢旈崱娆戠崶闂備浇妗ㄧ粈渚€鎮樺┑瀣р偓鏃堝礃椤斿槈褔鏌涢埄鍐剧劸闁稿绶氬娲箹閻愭彃濡ч梺鍛婂姂閸斿秹顢樼拠娴嬫斀闁绘ê鐏氶弳鈺呮煕鐎ｎ偆鈽夐摶鐐寸箾閸℃ɑ灏紒鐘虫緲閳规垿鎮╃€圭姴顥濈紒鐐劤椤兘寮婚妸銉㈡斀闁糕剝锚娴犻箖鎮峰鍛暭閻㈩垱顨婂鏌ュ蓟閵夛妇鍘卞┑鐐村灥瀹曨剟寮搁敂鍓ф／妞ゆ挻绋戞禍楣冩⒒閸屾艾鈧绮堟笟鈧獮澶愭晸閻樺啿浠梺闈涚箞閸婃洜澹曟繝姘厵闁告挆鍛闂佹娊鏀辩敮鎺楁箒闂佹寧绻傞悧濠囶敂閻樼粯鐓忛柛鈩冾殣闊剟鏌″畝瀣瘈鐎规洘甯掗埢搴ㄥ箣閻橀潧搴婇梺璇叉唉椤煤濮椻偓瀹曞綊宕稿Δ鍐ㄧウ濠殿喗銇涢崑鎾搭殽閻愬弶澶勯柟宄版嚇閹兘骞嶉鍙帡姊婚崒姘偓椋庢濮橆剦鐒界憸鏃堝箖瑜斿畷鍗烆渻閵忥紕鈽夐摶鏍煕閹板吀绨介柣锝呯埣濮婅櫣绮欑捄銊т紘闂佺顑囬崑銈夊箖閿熺姵鍋愮紓浣诡焽閸橀亶姊鸿ぐ鎺戜喊闁告鍋愬濠勭磼濡晲绨婚梺鎸庣箓閹虫劙鏁嶅鍥╃＜閺夊牄鍔屽ù顔姐亜閵忥紕鎳冮柍璇查叄楠炲棜顦虫い鏂垮濮婃椽宕ｉ妷褌瑕嗙紓鍌氱С缁舵艾顕ｆ繝姘ч柛鈩兠鍧楁⒑瑜版帒浜伴柛蹇旓耿瀹曟垿骞樺鍕瀹曨亝鎷呯憴鍕彟闂傚倷绀侀幖顐⒚洪姀銈呭瀭婵炲樊浜滈悡鏇㈡煙鏉堥箖妾柣鎾存礋閺岀喖鎮欓浣虹▏缂備浇灏褔婀佸┑鐘诧工閹冲孩绂掗柆宥嗙厸閻忕偛澧藉ú鎾煙椤旇娅婄€殿喖顭锋俊鐑藉Ψ閵夈儱鎸ら梻鍌氬€峰ù鍥敋閺嶎厼绐楁俊銈呮噺閺呮繈鏌曡箛瀣偓妤€鐣垫担瑙勫弿婵＄偠顕ф禍鎯ь渻閵堝啫鐏柣鐔叉櫊楠炲啴宕滆濞岊亪鏌﹀Ο渚Ш妞ゆ挸銈稿濠氬磼濮橆兘鍋撻悜鑺ュ€块柨鏇炲€哥壕鍧楁煕閹邦垼姊块柣鐔煎亰濞尖晠鎮规ウ鎸庮仩闁挎稒鐩娲川婵犱胶绻侀梺鍓茬厛閸ㄥ爼骞冮悙瀵哥瘈闁稿鍨扮紞濠囧箖閳╁啯鍎熼柨婵嗘閸犳牠姊绘担铏瑰笡闁圭顭烽幃鐤樄闁糕斁鍋撳銈嗗笒閸婂綊宕甸埀顒勬煟鎼淬垹鍤柛鐘愁殜瀵尙鎹勬担鏇熸瀹曘劑顢橀悙鏉戝姃闂傚倷鐒﹂幃鍫曞磿椤曗偓瀵剚绗熼埀顒€鐣烽幋锕€绠婚柤鎼佹涧閺嬪倿姊洪崨濠冨闁告挻鐩弫宥咁潨閳ь剙顫忓ú顏勫窛濠电姴鍟伴崣鍡欑磽娴ｅ壊妲搁柣鏍с偢閻涱噣骞嬮敃鈧～鍛存煟濮楀棗浜濋柡鍌楀亾闂備浇顕ч崙鐣岀礊閸℃顩查柣鎰壋閸ヮ剙绾ф繛鍡欏亾鐎靛矂姊洪棃娑氬婵☆偅鐟ф禍鎼佸箥椤斿墽锛滈柣搴秵閸嬪嫬霉椤曗偓閺岀喖顢欑粵瀣暦缂備浇妗ㄧ划娆忕暦閵婏妇绠鹃柣鎰靛墮椤忔椽姊婚崒娆掑厡妞ゎ厼鐗撳鐢割敆閸曨剙娈炴俊銈忕到閸燁偊鎮為崹顐犱簻闁瑰搫绉堕崝宥夋煕婵犲啫濮夐柍褜鍓濋～澶娒哄鈧畷婵嗏枎閹惧磭鐣哄┑鐘诧工閻楀﹪宕靛澶嬬厪濠㈣泛鐗嗛崝妤呮煕鐎ｎ偅宕岀€规洜顭堣灃濞达絽鎼鎶芥⒒娴ｅ憡鎯堟繛璇х畱閻ｆ繄绮欏▎鍓р偓鍓佲偓鐟板閸ｆ挳鎮烽柇锔惧弳闂佸憡鍔︽禍鐐搭殭闂傚倷绀侀幖顐﹀嫉椤掑嫭鍎庢い鏍仧瀹撲線鏌涢妷顔煎缂佲偓閸岀偞鐓曟繝闈涘閸旀岸鏌涢妶搴″⒋婵﹦绮幏鍛瑹椤栨粌濮兼俊鐐€栭崹闈浳涘┑瀣畺鐟滃秷鐏冮梺鍛婁緱閸樻瑩鏁冮崒娑氬幈闂佸搫娲㈤崝宀勬倶閻樼數纾奸柣妯虹－濞叉挳鏌＄仦鍓ф创妤犵偞锕㈤幊鐘垫崉閸濆嫬鑵愰梻鍌欑閹碱偄螞濞戞瑧绠鹃柍褜鍓氶幈?")
        if scenario in {"review", "plan", "task", "next_task"} and review_rhythm:
            lines.append("")
        elif due_reviews:
            lines.append(f"闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓氱粭鐔肺旈埀顒冪亱闂佽法鍠撴慨鐢稿煕閹达附鐓熼柣鏂挎啞缁舵煡鏌￠崱娑楁喚闁哄矉绻濆畷濂割敃閵忕媭娼鹃梻浣烘嚀缁犲秹宕硅ぐ鎺戠厴闁瑰濮崑鎾绘晲鎼粹€茬盎婵炲濮靛钘夘潖婵犳艾纾兼慨妯哄船椤も偓闂備礁鎲″濠氬磻閹炬枼鏀介柣鎰綑閻忕喖鏌涢妸锔姐仢闁?{len(due_reviews)} 濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ゆい顓犲厴瀵鏁愭径濠勭杸濡炪倖甯婇悞锕傚磿閹剧粯鈷戦柟鑲╁仜婵″ジ鏌涙繝鍌涘仴鐎殿喛顕ч埥澶愬閳哄倹娅囬梻浣瑰缁诲倸螞濞戔懞鍥Ψ瑜忕壕钘壝归敐鍛儓鐎涙繄绱撻崒姘毙㈤柨鏇ㄤ簻椤曪絿鎷犲顔兼倯婵犮垼娉涢敃锝囨閸洘鈷戦柛娑橈攻婢跺嫰鏌涚€Ｑ冧壕闂備胶顭堥鍡涘箰閼姐倖宕叉繝闈涙－濞尖晠鏌曟径鍫濈仼濞存粓绠栭弻娑樷槈濞嗘劗绋囬梺娲诲幗椤ㄥ懘鈥︾捄銊﹀磯闁惧繐婀辨导鍥⒑娴兼瑧鐣遍柣妤€锕﹂幑銏犫攽鐎ｎ偄浠洪梻鍌氱墛閸掆偓闁靛繈鍊栭悡鏇炩攽閻樻彃浜為柣鎾瑰亹閳ь剝顫夊ú蹇涘磿闂堟稓鏆﹂柛顐ｆ处閺佸棗霉閿濆懏鎯堟鐐茬墦濮婄粯绗熼埀顒€顭囪钘濆ù鐘差儏缁愭鏌″鍐ㄥ婵炲懐濮甸妵鍕即濡も偓娴滈箖姊洪崫鍕効缂傚秳绶氶妴浣割潨閳ь剟骞冮妶鍡樺闁革富鍘藉▓钘夆攽閿涘嫬浜奸柛濞垮€濆畷锝夊焵椤掍胶绠惧璺侯儐缁€瀣殽閻愭潙鐏寸€规洜鍠栭、娑橆潩椤愩倗鍊為梻鍌欑閹测€趁洪弽顓熷€舵慨姗嗗幘婢э繝姊婚崒姘偓鎼佸磹妞嬪海鐭嗗〒姘ｅ亾妤犵偞鐗犻、鏇㈡晜缂佹ɑ娅堥梻浣虹《閸撴繄绮欓幒妤€纾婚柨鐔哄У閻撳啴寮堕悙鏉戭棆閻犳劗澧楃换娑㈠礂閼测晛鈷岄梺鍝勭潤閸℃瑧鏉搁梺鐟板⒔椤ユ劗娑甸埀顒傜磽娴ｅ搫浜鹃柛搴㈠▕瀹曘儳鈧綆鍠栫粻鐐烘煏婵炲灝鍓婚柡鍐ㄧ墕閻掑灚銇勯幒鎴濐仾闁稿顑夐弻鐔兼偋閸喓鍑￠梺缁樺笒閻忔岸濡甸崟顖氱鐎广儱娴傚Σ顔碱渻閵堝棙绀冪紒顔兼捣濡叉劙骞掗弮鍌滐紲濠碘槅鍨伴惃閿嬫叏閸ヮ剚鈷戦柣鐔告緲濡插鏌熼搹顐€顏堟偩瀹勯偊娼ㄩ柍褜鍓熼悰顕€骞樼拠鑼唺濠电娀娼ч幊鎰鐠囨祴鏀介柨娑樺娴滃ジ鏌涙繝鍐ㄥ鐎殿喗鐓￠幃鈺冩嫚閼碱剙鎽嬮梻鍌欑贰閸撴瑧绮旂€涙﹩鏀伴梻鍌欑閹测€趁洪敃鍌氬瀭濞村吋娼欑粈鍐煃瑜滈崜娆撯€旈崘顔嘉ч柛鈩冾殔琚濇繝鐢靛Л閹冲洭宕戦幘鏂ユ斀闁绘劘灏欓悞鎯瑰搴濈盎妞ゎ偄绻橀幖褰掑捶椤撶媴绱叉繝纰樻閸ㄧ敻顢氳濡嫬顓奸崨顏呮杸闂佺粯鍔栬ぐ鍐棯瑜旈弻锝呂旈崘銊㈡瀰閻庤娲樺浠嬪箖濞嗘挸浼犻柛鏇ㄥ弾閸氬懘姊绘担鐟邦嚋婵☆偂绀佽灋闁告洦鍓涢々鑼喐閻楀牆绗氶柍閿嬪灴閺屾盯鏁傜拠鎻掔闁汇埄鍨遍惄顖炲箖娴犲鏁嶆俊銈勭劍閻濇洜绱撴担绋库偓鍦暜濡ゅ啰绱﹀ù鐘差儏瀹告繂鈹戦悩鎻掝仼妤犵偞顨婂缁樼瑹閳ь剙顭囪閹广垽宕卞☉妯兼煣濠电偞鍨崹娲磹閸洘鐓熸俊顖滃劋閳绘洟鏌ｉ弬鎸庮棤闁硅尙顭堥濂稿触閵堝洦鍤€闁伙綇绻濋獮蹇涘籍閹惧墎袦濡ょ姷鍋涘ú顓烆嚕閸撲焦宕夋い顓熷灥閺佽棄鈹戦悩鑼闁哄绨遍崑鎾诲箛閺夎法锛涢梺鐟板⒔缁垶鍩涢幋锔界厱婵°倕鍟禒锕傛煕閻樼鑰块柡灞糕偓宕囨殕閻庯綆鍓涢惁鍫ユ倵鐟欏嫭绀€闁绘牕鍚嬫穱濠傤潰瀹€濠冾€囬梻浣告惈濡鎹㈠┑鍡╂綎婵炲樊浜滄导鐘绘煏婢跺牆鍓鹃柨婵嗘礌閸嬫捇宕楁径濠佸闂備礁缍婂Λ璺ㄧ矆娴ｈ櫣涓嶉柡宥冨妺缁诲棝鏌曢崼婵囧櫣闁哄棛鍋ら弻娑㈡偐閸欏妫﹂梺鍝勬湰閻╊垰顕ｉ幘顔嘉╅柕澶堝労濞奸箖姊绘担鐟邦嚋缂佸甯￠弫鍐閻欌偓濞兼牠鏌ц箛鎾磋础闁活厽鐟╅弻娑⑩€﹂幋婵囩彯闂佸憡鏌ㄩˇ闈涱潖閾忓湱纾兼俊顖滅帛閸庢挾绱撴担铏瑰笡缂佽鐗撻獮鍐╁閹碱厽鏅梺閫炲苯澧柣锝囧厴瀹曪繝鎮欓埡鍌ゆ綌婵犵妲呴崹鐢稿磻閹邦剦鐒藉鑸靛姈閳锋帒霉閿濆浂鐒炬い銉ョ箻閺屾稓鈧綆浜濋ˉ銏⑩偓瑙勬磻閸楁娊鐛崶顒夋晞闁兼亽鍎抽埀顒€鎼埞鎴︽偐鐠囇冧紣闂佺粯顨呴敃顏堝春濞戙垹绠ｉ柨鏃傛櫕閸樼敻姊洪崗鑲┿偞闁哄懏绋掔粋鎺戭煥閸喓鍘遍梺鍝勫暊閸嬫捇鏌ㄩ弴妯虹伈鐎殿喛顕ч埥澶愬閻樻剚妫熼梺鑽ゅУ娴滀粙宕滈柆宥咁潊闁靛繆鈧厖绮℃繝鐢靛仜濡瑩骞愰崫銉т笉閻熸瑥瀚粻楣冩煥濠靛棝顎楀褜鍠栭埞鎴﹀灳閼碱剛鐓撻梺鍝勮嫰缁夊綊寮婚妸褉鍋撻敐搴濈敖闁荤喆鍔戝濠氬炊瑜滃Ο鈧梺鍝勮閸斿矂鍩為幋锕€骞㈡繛鍡楃箚閹封剝绻濋悽闈涗粶闁告艾顑夊畷婵嗏枎閹惧疇鎽曞┑鐐村灦閸╁啴宕戦幘缁樻櫜閹肩补鈧剚娼婚梻浣哥枃椤曆囨偋閹捐钃熼柨娑樺濞岊亪鏌涢幘妞诲亾濠殿喖娲铏规嫚閳ュ磭浠┑鈽嗗亜閸燁垶骞堥妸鈺佺劦妞ゆ帒瀚悡鐔告叏濡も偓濡绂嶅┑瀣厽闊洦鎸婚ˉ銏ゆ煛瀹€瀣ɑ闁诡垱妫冩俊鑸垫償閵忋垻啸濠电姷鏁搁崑娑橆嚕閸洘鏅濋柕蹇曞Х閺嗭妇鎲搁悧鍫濈瑨闂佽￥鍊栨穱濠囧Χ閸屾矮澹曠紓鍌欒兌婵敻鎮ч悩璇茶摕闁哄浄绱曢悿鈧柣搴秵娴滄牠宕戦幘璇插嵆闁绘鏁搁悞濂告⒑閸涘﹥澶勯柛銊╀憾閹ょ疀濞戞瑧鍘卞銈嗗姧缁茶法绮诲Ο渚唵鐟滃酣宕濆▎鎾宠摕婵炴垶鍩冮崑鎾绘晲鎼粹€茬凹閻庤娲栭惉濂稿焵椤掑喚娼愭繛鍙夌矒閳ワ箓宕奸敐鍥︾胺婵犵數鍋犻幓顏嗗緤娴犲绠规い鎰跺瀹撲線鏌涢銈呮灁缂佲檧鍋撻梻浣圭湽閸ㄨ棄顭囪缁傛帡鏁冮崒娑氬幈闂侀潧顭堥崕鎶藉春閿濆鐓冮柕澶樺灣閻ｇ數鈧娲栭悥濂搞€佸Δ鍛劦妞ゆ帒鍊绘稉宥嗙箾瀹割喕绨奸柣鎾跺枑娣囧﹪顢涘┑鍡曟睏闁汇埄鍨遍惄顖炲蓟閿濆绠婚悗闈涙啞閸掓盯姊洪崫鍕拱缂佸鍨块垾锕傚Ω閳轰胶鍔﹀銈嗗笒閸婂鎯岄崱妞曞綊鏁愰崼顐ｇ秷濠电偛鎳愭繛鈧柡宀€鍠撶槐鎺楀閻樺磭浜堕梻浣虹帛閹稿鎮烽敃鍌毼﹂柛鏇ㄥ灠缁秹鏌嶈閸撶喎顕ｉ崨濠勭瘈婵﹩鍘煎▓宀勬⒑缁夊棗瀚峰▓鏇㈡煟閹惧鎳勯柕鍥у瀵噣宕掑☉娆戝涧闂備胶鎳撻崯鍧楀箠濮椻偓瀵鎮㈤崗鐓庝画闂佸搫顦伴娆愮閹€鏀介柣鎰暯閹封€趁瑰搴濋偗妤犵偛鍟抽ˇ鍦偓瑙勬礀閵堝憡鎱ㄩ埀顒勬煥濞戞ê顏柍璇差槺缁辨捇宕掑顑藉亾閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑锛勫亼閸婃垿宕瑰ú顏呭亱闁绘灏欓弳锕傛煏婵炑冨暙閻忓﹪姊虹粙璺ㄧ妞わ富鍨辩粋宥嗐偅閸愨晝鍙嗛梺鍝勬川閸嬫盯鍩€椤掆偓缂嶅﹤鐣烽幇顓犵瘈婵﹩鍘鹃崣鍐ㄢ攽閳藉棗鐏熼悹鈧敃鈧嵄濠靛倸鎲￠悡娆撴煠閹帒鍔滅紒鈧€ｎ偅鍙忓┑鐘插暞閵囨繃顨ラ悙鏉戝闁诡垱妫冮弫鎰板炊閳哄倹顔撻梻鍌氬€烽懗鍫曞箠閹捐搴婇柡灞诲労閺佸嫬顭块懜闈涘缂佺姵鐗犻弻銊╂偄閸濆嫅銏ゅ船椤栫偞鈷戦柛鎰级閹牓鏌涙繝鍌ょ吋鐎规洏鍨介弻鍡楊吋閸″繑瀚奸梻浣告啞缁诲倻鈧凹鍙冨畷鎺楀Ω閳哄倻鍘遍梺鍝勫€圭€笛冿耿娴煎瓨鐓涢柛娑欐緲閻撴劙鎮楁担鍐ㄤ汗闁逞屽墯缁嬫帡鈥﹂崶顒€鍌ㄩ梺顒€绉甸埛鎴︽煟閻旂顥嬮柟鐣屽█閺屸€崇暆鐎ｎ剛鐦堥悗瑙勬礃閸ㄥ潡鐛Ο鍏煎珰闁告瑥顦藉Λ鐔兼⒒娓氣偓濞佳嚶ㄩ埀顒勬⒒閸曨偄顏€殿喖鐖奸獮鏍ㄦ媴閸忓瀚藉┑鐐舵彧缂嶁偓婵炲拑绲块弫顔尖槈閵忥紕鍙嗛梺鍝勬处椤ㄥ棗鈻嶆繝鍕ㄥ亾鐟欏嫭绀冮柛銊ョ仢閻ｇ兘鎮㈢喊杈ㄦ櫌闂佺琚崐鏍煥閵堝鈷掑ù锝囩摂閸ゅ啴鏌涢妸銉︽崳濞寸媴绠撻獮鍡氼槾婵¤缍佸濠氬磼濞嗘垹鐛㈠┑鐐板尃閸ャ劌浜遍梺绯曞墲缁嬫垹绮婚悩缁樼厵闂侇叏绠戦弸銈呪槈閹惧磭孝闂囧鏌ｉ幘铏崳闁圭晫濞€閺岋綁骞樼捄鐑樼€炬繛锝呮搐閿曨亝淇婇崼鏇炵＜婵﹩鍋勯ˉ姘攽閻樻鏆俊鎻掓嚇瀹曟垿宕ㄩ婊呯厯闂佽宕橀褏绮堥崱娑欑厵闁绘垶锕╁▓鏃堟⒑閸楃偞鍠橀柡灞炬礃瀵板嫰宕煎┑鍡椥戦梻浣瑰缁嬫帞鍒掗幘鎰佹綎闁惧繐婀辩壕鍏间繆椤栨碍鎯堟い顐㈣嫰椤啴濡堕崱妯侯槱闂佸憡鐟ラ崯顐︽偩閻戣棄顫呴柕鍫濇噽椤㈠懘姊虹紒妯虹仴婵☆偅鐟ч埀顒勬涧閻倸顫忓ú顏咁棃婵炴垶鑹鹃。鍝勨攽閳藉棗浜濇い銊ユ楠炲牓濡搁…鎴炐紓鍌欐祰妞村摜鏁敓鐘茬疇闁绘绮崵瀣煟閵忋垹浠柍褜鍓欓敃锔炬閹惧鐟归柛銉戝嫮浜俊鐐€ら崢楣冨礂濮椻偓閹即顢欓崲澶屽枛閹虫牠鍩￠崘璺ㄥ簥濠电姷顣藉Σ鍛村垂閹惰棄鍌ㄧ憸鏃堟偘椤斿槈鏃堝川椤旇瀚藉┑鐐舵彧缁蹭粙骞夐敍鍕闁跨喓濮甸悡鏇㈠箹鐎涙鈽夐柍褜鍓氱换鍌炴偩閻ゎ垬浜归柟鐑樼箖閺咁剟姊虹紒妯哄閻忓繑鐟╅弫宥呪槈閵忊檧鎷洪梻鍌氱墛缁嬫挾绮婚悙鐑樼厱濠电姴鍟版晶鐢告煙椤斿厜鍋撻弬銉︻潔闂侀潧绻嗛埀顒佹灱閸嬫捇宕奸弴鐔哄幗闂佸綊鍋婇崢鑲╁緤婵犳碍鐓冮梺鍨儐閳锋劗绱掔紒妯兼创妤犵偞鎹囬獮鎺楀籍閳ь剟骞夐悡搴富闁靛牆鍟俊鎼佹煕鎼达絾鏆鐐插暙閳诲酣骞樺畷鍥崜闂備胶鎳撻顓㈠磻閻樼粯鍎屽ù锝夆偓娑氱畾闂侀潧鐗嗗ú銈呮毄闂備胶顭堥鍡涙儎椤栫偑鈧線寮介妸銉х獮闂佸綊鍋婇崜娑㈡偩閸濆嫧鏀介柣妯款嚋瀹搞儵鏌ｅΔ鈧Λ婵嬫偘椤曗偓婵偓闁斥晛鍟鍨攽鎺抽崐鎰板磻閹剧繝绻嗘い鎰剁悼閹冲洭鏌℃担鍝バх€规洖鐖奸崺锟犲礃椤忓海闂梻鍌欒兌椤牓寮甸鍕殞濡わ絽鍟悞鍨亜閹哄秶鍔嶉柛濠冨姉閳ь剝顫夊ú姗€宕濆▎鎾崇畺婵犲﹤鐗婇崵宥夋煏婢跺牆鍔楅柛瀣崌瀹曠螖娴ｅ搫寮抽梻浣告惈濞诧箓銆冮崨顔绢洸闁诡垎灞惧瘜闂侀潧鐗嗙花鑲╄姳婵犳碍鐓曢柣鏂挎啞鐏忥附顨ラ悙鎻掓殻妤犵偛妫滈ˇ鎾煛閸℃顥㈤柡灞界Х椤т線鏌涢幘瀛樼殤缂侇喗鐟﹀鍕節鎼粹剝鍊┑鐘灱濞夋盯顢栭崶顒€鍌ㄩ柟闂寸劍閸婂灚顨ラ悙鑼虎闁告梹宀搁弻娑㈡偆娴ｉ晲绨兼繛锝呮搐閿曨亪骞栬ぐ鎺戞嵍妞ゆ挾濯寸槐?")
        if working_set_mode == "focused":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙鍋嶉梺鎼炲妼缂嶅﹪寮荤€ｎ喖鐐婇柕濞у懐妲囬梻鍌氬€搁悧濠勭矙閹烘绠归柟閭﹀枤绾惧ジ鏌熼柇锕€骞樻繛鎻掔摠閹便劍绻濋崘鈹夸虎閻庤娲忛崝宥囨崲濠靛洦鍎熼柕蹇嬪灪濞堥箖姊虹拠鏌ヮ€楅柛妯荤矒瀹曟垿骞樼紒妯煎幍闂傚倸鍊搁顓⑺囬敂鍓х＜闁绘ê纾晶顒€菐閸パ嶈含濠碘€崇埣瀹曟帒顫濋銏╂闂傚倸鍊风粈渚€鎮块崶顬盯宕熼鈧崶顒夋晬闁绘劘灏欓崢娲倵楠炲灝鍔氭い锔垮嵆楠炲棝鎮欏ǎ顑跨盎闂佽澹嬮弲娑㈡倶椤旀祹褰掓偐閾忣偄鈧劖鎱ㄦ繝鍐┿仢闁哄苯鎳庨埥澶婎潩閿濆棙娅冮梻鍌欑閹诧繝寮婚妸鈺傚剹闁稿瞼鍋涢悘鎶芥煥閺囩偛鈧憡鍎梻浣哥枃濡椼劑鎳楅崼鏇€鍥ㄥ鐎涙ǚ鎷洪柣搴℃贡婵即鍩€椤戣棄浜鹃梻浣侯焾椤戝棝骞愰崜褎顫曢柟鐑橆殔鎯熼梺闈涱樈閸犳岸宕ョ€ｎ亖鏀芥い鏃傘€嬮弨缁樹繆閻愯埖顥夐柣锝囧厴椤㈡洟鏁冮埀顒傜矆鐎ｎ偁浜滈柟閭﹀枛閺嬪骸霉濠婂牏鐣洪柡宀€鍠栧鑽も偓鐢殿焾婵′粙姊虹粙鍖￠練闁糕晜鐗滈幑銏犫攽鐎ｎ偒妫冨┑鐐村灥瀹曨剟宕滈幍顔剧＝濞达絽鎼牎闂佺粯顨堟繛鈧€殿喖顭烽幃銏ゅ川婵犲嫮肖濠德板€х徊浠嬪疮椤栫儐鏁佺€广儱顦伴埛鎴犵磽娴ｈ偂鎴犱焊娴煎瓨鐓熼柍鍝勶工閻忥妇鈧鍠涢褔鍩ユ径濞㈢喖鏌ㄧ€ｅ灚缍岄梻鍌欑閹诧繝銆冮崼銉ョ；婵炴垶姘ㄦ稉宥夋煛鐏炶鍔滈柍閿嬪灩缁辨帞鈧綆鍋掗崕銉╂煕鎼达紕效闁哄本鐩俊鎼佹晜婵劒铏庢俊銈囧Х閸嬫盯鎮ч幘缈犵箚闁归棿鐒﹂弲婊堟煕閹炬鎳忛～宀勬⒒閸屾瑧顦﹂柟璇х節瀹曟繆绠涘☉妯活棟闂佺鏈粙鎾汇€呴悜鑺ョ厪闊洦娲栭～宥夋煛閸愩劎澧涢柛瀣姍濮婂宕奸悢琛℃）濠电偛鐭堟禍顏勵潖濞差亜鎹舵い鎾跺枎濞堝苯鈹戦悙鍙夆枙闁告瑥鍟撮獮鍐╁閹碱厽鏅梺閫炲苯澧撮柣娑卞櫍楠炴帡骞婇搹顐ｎ棃闁糕斁鍋撳銈嗗笒閸婅崵浜搁悽纰樺亾楠炲灝鍔氭い锔垮嵆閹繝寮撮姀鈥斥偓鍫曟煟閹伴偊鏉洪柛銈嗙懇閺屽秷顧侀柛鎾磋壘鐓ら柣鏂款殠閸ゆ洘銇勯幇鈺佸姌濞存粌缍婇弻鐔兼倻濡鐨戦梺褰掓敱濡炶棄顫忓ú顏呭亗閹兼惌鍠楃紞妤呮⒑缁嬪尅鏀绘繛鑼枎椤曪綁骞栨担鍝ヮ吅闂佺粯顭囬弫鎼佹晬濠婂喚娓婚柕鍫濇椤ュ棝鏌涚€ｎ偄濮堥柣妤€楠搁埞鎴︽倻閸モ晛鍩屽┑鐐茬湴閸婃繈寮崘顕呮晜闁割偁鍨圭粊锕傛⒑閸濆嫮袪闁告柨绉甸崚濠勨偓闈涙憸绾惧ジ鎮楅敐搴″箺缁绢厼鐖奸弻锝呪槈閹烘挻鐝曟繛锝呮搐閿曨亪骞冨▎鎿冩晜闁告洏鍔屾禍楣冩煛瀹擃喖鏈紞搴㈢節閻㈤潧校闁煎綊绠栭幃锟犲即閵忥紕鍘卞銈嗗姂閸婃洟寮告惔顫簻闁哄浂婢€閹查箖鏌″畝瀣瘈鐎规洖鐖兼俊鐑藉Ψ瑜岄惀顏堟⒒娴ｇ懓鈻曢柡鈧柆宥呭瀭闁秆勵殔缁犳牜鎲搁悧鍫濈瑨闁绘劕锕弻鏇熺箾瑜嶉崯顐ょ磼閳哄懏鈷掑ù锝呮啞閸熺偤鏌ｉ悢鏉戝姢闁逞屽墯閸戝綊宕㈡ィ鍐ㄧ闁靛繒濮Σ鍫熺箾閸℃ê濮囨い搴㈡崌濮婃椽宕ㄦ繝鍌氼潓閻庢鍠栭悥濂哥嵁閺嶎厼绠涙い鏂垮⒔閿涙粓姊虹紒姗堣€挎繛浣冲洤鍑犳繛鎴欏灪閻撴盯鎮橀悙棰濆殭濠碘€炽偢閺屽秹鎸婃径妯恍﹂柧浼欑到閵嗘帒顫濋悡搴ｄ户闂佽鍣徊璺ㄦ閹捐纾兼繛鍡樺姉閵堟壆绱撻崒姘卞闁告鍟块悾鐑藉箛椤戣姤鏂€闁诲函缍嗘禍锝夊箺閺囥垺鈷戦梻鍫熺〒婢ф洘淇婇锝囨噰鐎规洩缍€缁犳稑鈽夊▎鎴濆箥闂傚倷绶￠崣蹇曠不閹达箑鍌ㄩ柟缁㈠枟閻撴洟鎮楅敐搴′簼鐎规洖鐬奸埀顒侇問閸犳洜鍒掑▎鎾扁偓浣割潨閳ь剟骞冨▎鎾村仺闂傚牊绋撻崐鐐烘⒒閸屾艾鈧嘲霉閸ヮ剨缍栧璺侯儑閻濆爼鏌涢埄鍏╂垵鈻嶉悩鍏呯箚闁靛牆鎳忛崳娲煕鐎ｎ亜鈧潡寮婚敐澶婄睄闁割偆鍠愰悵宕囩磽娴ｇ瓔鍤欐俊顐ｇ箞瀵寮撮姀鐘诲敹濠电娀娼уΛ宀勫磻閹捐宸濆┑鐘插濞插憡淇婇妶蹇曞埌闁哥噥鍨堕崺娑㈠箣閻樼數锛濇繛杈剧悼濞呫垺绗熷☉娆戠闁割偆鍠愰ˉ鍫ユ煛鐏炶濮傜€殿喗鎸抽、鏃堝醇閻曚讲鍋撳鍥╃＝濞达絿顭堥埀顒€鎽滅划鏃囥亹閹烘柨绁﹂梺鍝勭Р閸斿酣鎮疯ぐ鎺撶厱闁靛绲芥俊鑺ョ箾閸涱厾效婵﹦绮幏鍛存惞閻熸壆顐奸梻浣规偠閸旀垵顭囪閻忓鈹戦悙鏉戠仧闁搞劌缍婇幊婊嗐亹閹烘挾鍘介梺闈涚箳婵敻宕悙鐑樼厱閻庯急鍐ㄢ拤缂備胶绮换鍐崲濠靛纾兼慨姗嗗幗椤斿秶绱撻崒娆掑厡濠殿喚鏁婚幃锟犳晸閻樿尪鎽曢梺缁樻煥閹芥粓鎮疯ぐ鎺撶厱妞ゎ厽鍨甸弸娑欍亜椤愩垺鍠樻慨濠呮閹风娀鍨鹃搹顐や簽缂傚倷绶￠崰妤呮偡閳哄懐宓侀柛鎰ㄦ櫇椤╃兘鎮楅敐搴′簻濞寸姵妞藉鍝勑ч崶褏浼堝┑鐐板尃閸曨剙寮挎繛瀵稿Т椤戝棝鍩涢幒妤佺厱閻忕偛澧介幊鍛亜閿斿ジ妾紒缁樼箞閸┾偓妞ゆ帒瀚悞鑲┾偓骞垮劚閹虫劙鏁嶉悢鍏尖拺闂傚牊绋撴晶鏇㈡煙瀹勯偊鍎忔い顓炴喘瀵粙顢橀悢鍝勫箞闂備焦瀵уΛ渚€顢氳閻涱噣骞囬悧鍫㈠幈闁诲函缍嗛崑鍛焊椤撶喆浜滄い鎰剁悼缁犵偞銇勯姀鈽呰€块柟顔界懇瀹曪絾寰勭€ｎ亝鐣奸梻鍌氬€搁崐椋庣矆娓氣偓楠炴牠顢曢敂钘夊壎婵犻潧鍊婚…鍫㈢玻濡ゅ懏鐓欓柟瑙勫姇閻撴劖銇勯锝嗙闁哄瞼鍠栭幃婊兾熼悜姗嗗晭闂備胶绮弻銊╁箟閳╁啯鍙忔繝濠傜墛閻撴稑顭跨捄鐚村姛濞寸姰鍨介弻锝堢疀鎼达綆妲梺瀹狀潐閸ㄥ潡骞冮埡鍛瀭妞ゆ劧绲鹃惁搴ㄦ⒒娴ｄ警鐒炬い鎴濇閹嫰顢涘杈ㄦ闂侀潧锛忛埀顒勫磻閹剧粯鏅查幖绮光偓鑼晼缂傚倷鑳舵慨鐢稿磿閹惰棄鐓橀柟杈鹃檮閸嬫劙鏌熺紒妯虹瑐缂併劏妫勯埞鎴︽倷閹绘帗鍊梺缁橆殕椤ㄥ牓骞戦姀鐘婵妫楅弲鐘差渻閵堝棙顥嗙€规洜鏁婚幆鍕償閵婏箑鈧敻鏌ｉ悢鍝勵暭闁哥喓鍋熺槐鎺旀嫚閹绘巻鍋撻崸妤€鏄ラ柣鎰惈缁狅綁鏌ㄩ弮鍥棄濞存粌缍婂娲捶椤撶姴绗￠柣銏╁灙閺呮粎鈧潧銈搁崺鈧い鎺戝閳锋帒霉閿濆牊顏犻悽顖涚洴閺岀喖宕ㄦ繝鍐ㄥ攭閻庤娲橀崹鍧楃嵁濡偐纾兼俊顖炴敱鐎氫粙姊绘担渚劸闁哄牜鍓熼幃鐤樄鐎规洘绻傞濂稿幢閺囩姷鐣鹃梻浣虹帛閸旀洖顕ｉ崼鏇炵；闁靛／鈧崑鎾舵喆閸曨剛顦ㄧ紓渚囧枛閻倿宕洪妷锕€绶為柟閭﹀墻濞煎﹪姊虹紒妯曟垼銇愰崘鈺冾洸闁割偅娲橀悡鐔兼煟閺傛寧鎲搁柣顓烇功缁辨帞绱掑Ο蹇ｄ邯閹箖鎮滈懞銉︽珳婵犮垼娉涢敃銈囩玻濞戙垺鐓熼幖娣灮閳洟鎳ｉ妶澶嬬厵闁汇値鍨遍鐘电磼鏉堛劍灏伴柟宄版嚇瀹曟粓宕ｆ竟顓ㄧ畱閳规垿鍩ラ崱妞剧凹濡炪們鍔岄悧鎾诲春閳ь剚銇勯幒宥嗙グ濠㈣锕㈤弻娑㈠閿涘嫬寮ㄩ梺绯曟杺閸ㄤ粙鐛Ο鍏煎珰闁肩⒈鍓涘澶愭⒒娴ｄ警鐒鹃柡鍫墰閸掓帗鎯旈妸锔芥珫濠电姴锕ら悧濠囧煕閹寸姷纾藉ù锝呭帨濡劍銇勮箛鎾跺闁汇値鍣ｉ弻娑滎槼妞ゃ劌鎳橀幃鈥斥攽鐎ｎ偆鍘搁梺鎼炲劘閸庨亶鎮橀鍫熺厽闁规儳顕ú鎾煙椤旀枻鑰块柟顔界懇濡啫鈽夊Δ鈧ˉ姘辩磽閸屾瑨顔夐柛瀣崌閺屾盯骞囬崗鍝ユ晼缂佺偓鍎抽妶鎼佸蓟閿熺姴绀冮柕濞垮劗閸嬫捇骞栨担绋垮殤濠电偞鍨堕悷锝嗙濠婂牊鐓忛煫鍥ュ劤绾惧潡鏌嶉挊澶樻Ч闁靛洤瀚伴、鏇㈡晲閸モ晝鏉芥俊鐐€戦崹娲€冮崱妤婂殫闁告洦鍓欑欢鐐碘偓鍏夊亾闁逞屽墴閺佸秴鈽夐姀鈾€鎷婚梺绋挎湰閼归箖鍩€椤掑嫷妫戞繛鍡愬灩椤繈顢楁径灞藉Ш闁荤喐绮嶅Λ鍐嵁閸愵収妲肩紓浣虹帛缁诲牆鐣烽崼鏇炍╅柕澶堝€楅弳妤呮⒒閸屾瑨鍏岄柛瀣ㄥ姂瀹曟洟寮婚妷銉ь槶濠殿喗锕╅崜锕傛倿娴犲鐓涚€广儱楠搁獮妤呮煟閹垮嫮绉柣鎿冨亰瀹曞爼濡搁敃鈧棄宥夋煟閻樺啿濮х紒缁樼箞瀵鏁愭径妯绘櫍闂佺粯姊婚崕銈夊闯娴煎瓨鈷戦悹鍥ｂ偓铏亪缂傚倸绉撮敃顏堟偘椤旂晫鐟归柍褜鍓熼悰顕€骞掑Δ鈧粻锝嗙節閸偄濮夐柍褜鍓熼弨杈ㄧ┍婵犲洦鍊锋い蹇撳閸嬫捇寮借濞兼牜鎲搁悧鍫濈瑨闁搞劌鍊块弻锝夊閵忊晝鍔搁梺缁樻尰閿曘垽寮婚悢鍛婄秶濡わ絽鍟宥夋⒑缁嬪尅鍔熼柛蹇旓耿瀵鈽夊Ο閿嬬€婚棅顐㈡祫缁插墽鐟у┑鐘垫暩閸嬫盯骞婂畝鍕９闁哄洢鍨归悡姗€鏌熸潏楣冩闁稿﹦鍏橀幃瑙勩偊閹稿寒浠╁┑顕嗙祷閸ㄨ棄顫忓ú顏勪紶闁靛鍎涢姀銈嗏拺閻㈩垼鍠氱粔顕€鏌曢崱鏇狀槮妞ゎ偅绻堥幊婊堝垂椤愶絿褰告繝鐢靛О閸ㄧ厧鈻斿☉銏℃櫇闁挎洖鍋嗛弫濠囨煙闁箑骞樼紒鐘荤畺瀵爼宕煎┑鍡忔寖闂佸憡甯婇崡鎶藉蓟閻斿吋鍤嶉柕澹懐鍘滈梺鑺ド戠换鍫ュ蓟閺囩喓绠鹃柣鎰靛墯閻濇洟姊洪幎鑺ユ暠闁搞劌娼″璇测槈閵忕姷鐤€濡炪倖宸婚崑鎾剁磼閻欐瑥娲﹂悡娆愩亜閺嶃劍鐨戝褝绠撻弻锛勪沪閸撗勫垱闂佽鍠掗弲婵嬪焵椤掆偓濠€杈ㄦ叏閹绢啟澶娾攽鐎ｎ偀鎷婚梺鎼炲劀鐏為敮鏋呴梻浣告惈閺堫剟鎯勯姘煎殨闁圭虎鍠栨儫闂侀潧锛忛崒婊勬毎闂傚倸鍊烽懗鍓佸垝椤栫偛绠板Δ锝呭暙缁愭鏌″搴″箹闁藉啰鍠栭弻銊モ攽閸℃ê鏅甸梺缁樻⒒椤牏娆㈤悙鐢电＜閻庯綆鍋勯婊堟煕鎼淬垺灏板ǎ鍥э躬閹瑩顢旈崟銊ヤ壕鐟滃繘骞忕€ｎ喗鏅插璺侯儌閹稿啴姊洪崨濠冨闁告妫勯悾鐑藉矗婢跺瞼鐦堥梻鍌氱墛娓氭宕曡箛娑欑厽闁圭儤鍨规禒娑㈡煏閸パ冾伃妤犵偞甯掗濂稿炊瑜嶉‖澶岀磽閸屾艾鈧摜绮旈弶鎳ㄦ椽顢橀姀鐘烘憰閻庡箍鍎遍ˇ顖涘閻樼粯鐓曢柡鍥ュ妼娴滄繃绻涢崼婵堝煟婵﹨娅ｇ槐鎺懳熼搹鍦噯闂備礁鎲￠懝楣冾敄閸ヮ剙绠查柕蹇曞Л閺€浠嬫倵閿濆簼鎲炬繛鐓庯躬濮婃椽骞愭惔锝囩暤濠碘槅鍋呴惄顖涗繆閹绢喖绠涢柣妤€鐗忛崢楣冩⒑閼姐倕鏋斿褎顨呴敃銏ゅ级婢瑰啿閰ｅ畷鎯邦檪闂婎剦鍓氶〃銉╂倷鐎涙ê纾冲Δ鐘靛仦鐢€愁嚕椤掍焦鍎熼柟鎯у暱缁堆囨⒒閸屾艾鈧绮堟笟鈧獮鏍敃閿旇棄鍓舵繝闈涘€婚…鍫㈢玻濡ゅ懏鐓涚€广儱楠搁獮妯尖偓瑙勬尫缁舵岸寮诲☉銏犵労闁告劑鍔屽В鍫濃攽閳╁啰鍙€缂佺姵鐗曢～蹇撁洪鍕唶闁硅壈鎻徊鍝勎ｉ崼銏㈢＝濞达絽澹婂Σ娲煙閾忣偅宕岄柟顕€绠栭幃婊呯驳鐎ｎ偅娅栨繝鐢靛Т閿曘倝骞婇幇鐗堝亗闁圭偓鏋奸弨浠嬫煟閹邦剙绾фい銉у█閺屾稓鈧綆鍋呯亸鐢告煃瑜滈崜鐔奉焽瑜旈幆宀勫磼濮樺吋缍庡┑鐐叉▕娴滄繈藟閸喓绠鹃柟瀵稿仩婢规ɑ銇勯敐鍡樸仢婵﹨娅ｇ划娆撳礌閳ュ啿顫犻梻浣侯攰濞呮洟骞戦崶顒€鏄ラ柕蹇曞閸氬顭跨捄鐚村姛闁活偄瀚板铏圭矙閹稿孩鎷辩紓渚囧枛闁帮綁寮鍜佺叆闁割偆鍟块幏铏圭磽閸屾瑧鍔嶉柨鏇楁櫊閹偤鎮欓鍌滎啎闂佸憡渚楅崰妤冪矆閳ь剟姊烘导娆戝埌闁搞垺鐓￠幃鎯р攽鐎ｎ亞顦板銈嗗笒閸婃悂鐛Δ浣虹瘈闁汇垽娼ф禒锕傛煕閵娾晜娑ч柣锝囧厴椤㈡宕熼銏犳闂備胶绮弻銊╁触鐎ｎ喗鍋傛繛鍡樺姂娴滄粓鏌″鍐ㄥ闁愁垱娲橀妵鍕Ψ閵壯冾暫闂佸疇顫夐崹鍧椼€佸▎鎾村仭濡绀侀ˉ姘舵⒒閸屾艾鈧娆㈠顒夌劷鐟滃繘骞戦姀銈呴唶闁靛鍎遍悗顓㈡煟閻樺弶鎼愮€殿噮鍓熼弫鎰緞婵犲嫬鈧偛顪冮妶鍡楃瑐閻犱焦鐓￠獮蹇曠磼濡偐顔曢柡澶婄墕婢т粙宕氭导瀛樼厵閻犲泧鍛槇閻庤娲﹂崹鍫曞箖濞嗘垳娌柛灞绢殔娴滈箖鏌熼悜妯虹劸婵炲皷鏅滈妵鍕箻濡も偓鐎氼噣寮惰ぐ鎺撶厽閹兼番鍊ゅ鎰箾閹绘帞绠荤€规洝顫夌粋鎺斺偓锝庡墮缁侊箓姊虹化鏇炲⒉缂佸鐗撻崺鈧い鎺嶈兌婢у灚銇勯姀鈽嗘畷缂佺粯绻堝畷鐔碱敃閵忋垹甯撻梻鍌欒兌缁垶骞愰崼鏇炵９闁哄稁鍘兼闂佸憡娲﹂崰姘舵偪閳ь剟姊洪崷顓炰壕婵炲吋鐟ラ埢宥呪攽鐎ｎ偀鎷洪悷婊呭鐢寮潏銊ょ箚闁绘劘鍩栭ˉ澶嬨亜椤愩垻绠婚柟鐓庢贡閹叉挳宕熼銏犵闂傚倷绀侀幉鈩冪瑹濡ゅ懎鍌ㄩ柛婵嗗珔瑜嶈灃闁告侗鍠掗幏铏圭磽娴ｅ壊鍎愭い鎴炵懇瀹曟洟骞囬悧鍫㈠幗闂佸啿鎼敃銈夋倶閻樼粯鐓熼柨婵嗘噹濡插鏌嶇憴鍕伌鐎规洟浜堕崺锟犲磼濮橆剙甯梻鍌氬€烽懗鍫曞储瑜旈獮妤€顭ㄩ崼婵囩€梺褰掓？缁€渚€宕掗妸銉冨綊鎮╁顔煎壉闂佺粯鎸婚悷鈺呭蓟閿濆绠ｉ柣蹇旀た娴滎亪宕洪姀銈呭嵆闁绘﹩鍋勬禍楣冩偡濞嗗繐顏紒鈧崘顏嗙＜閻犲洦褰冮埀顒€娼￠妴浣割潨閳ь剙鐣峰Δ鍛亗閹艰揪绲块悰顔尖攽閻樺灚鏆╁┑顔碱嚟閳ь剚鑹鹃崲鎻掑祫闂佸搫顦伴崹鐔煎绩娴犲鐓熸俊顖濇娴犳盯鏌￠崱蹇旀珔闁宠鍨块、娆撴嚍閵壯呪枏闂佺粯鎸堕崐婵嬪蓟閵娾晛鍗抽柣鎰ゴ閸嬫捇宕妷褌绗夊┑顔筋焾閸╂牠鎮￠悢鍏肩厵闂侇叏绠戦弸娑㈡煕閺傛鍎旈柡宀嬬秮楠炴鈧稒顭囬ˇ浼存⒑缂佹ɑ鎯勯柛瀣工閻ｇ兘宕奸弴鐐嶁晠鏌ㄩ弮鍥棄闁告搩鍠楃换婵嗩嚗閺嬵偄鈧洟鎯冮悜妯镐簻妞ゆ挾鍋熸晶锔界節閳ь剚鎷呯化鏇熸杸闂佺粯顭堥婊冾啅閵夆晜鐓熸俊銈傚亾缂佺粯锕㈤獮鍐箚椤剝妞介、鏃堝川椤栨艾绠伴梺璇查閸樻粓宕戦幘缁樺€甸柨婵嗛婢ф壆鎮敃鍌涒拻濞达絿鐡旈崵鍐煕閻樿櫕宕岀€规洝顫夌粋鎺斺偓锝庝簽閻ｆ椽姊洪弬銉︽珔闁哥噥鍨跺畷鏇㈡偄閸濄儳鐦堥梻鍌氱墛缁嬫帡藟閻愮儤鐓熼幖绮光偓铏瘣闂佸疇顫夐崹鍧楀箖閳哄懎鍨傛い鎰剁稻閻﹀酣姊绘担渚劸妞ゆ垵娲︾换娑㈠焵椤掑倵鍋撶憴鍕闁搞劌娼￠悰顕€宕堕鈧痪褔鎮归幁鎺戝鐎规洖鐖煎缁樻媴閸涘﹥鍎撶紓浣割儎缁舵艾鐣烽姀锛勯檮闁告稑锕ら悵?")
        elif working_set_mode == "broad":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙绐涢梺鍝ュУ閹稿墽鍒掔紒妯稿亝闁告劏鏅濋崢浠嬫⒑闁稑宓嗘繛浣冲嫭娅犳い鏍仦閻撶喐绻濋棃娑欏缂佲偓鐎ｎ偅鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噧闁宠閰ｉ獮鍡氼槻濠㈣锚閳规垿鎮欓懠顒佹喖缂備緡鍠氭慨鐢电矉瀹ュ鏁傞柛鏇㈡涧濞堛劑鏌ｉ悩鍙夊缂佷焦娼欏嵄闁割偁鍎查悡蹇涚叓閸ャ劍绀€閸熸悂姊洪崨濠冣拹闁圭鍟块～蹇撁洪鍕獩婵犵數濮撮崐姝岊杺婵犵數鍋涢悺銊у垝瀹ュ鍋嬮柡鍥╁仜缁侇偊姊绘担绋款棌闁稿绶氬畷褰掓嚒閵堝拋妫滈梺鑺ッˉ銏ｃ亹閹烘挻娅滈梺绯曞墲椤ㄥ牏绮婇柨瀣閻庢稒顭囬惌鎺旂磼閻樺磭澧い顐㈢箻閹煎綊宕烽鐘靛幆闂備礁婀遍…鍫⑩偓娑掓櫊楠炲繘宕￠悜鍡樺瘜闂侀潧鐗嗗Λ娆戝閹间焦鐓曢柕濞垮劘閸嬨垹鈹戦敍鍕毈妤犵偛娲鍓佹崉椤垵鏁介梻鍌欐祰椤宕曢幎鑺ュ仱闁靛ň鏅滈崑鐔兼煙閹澘袚闁抽攱甯掗湁闁挎繂鐗滃鎰版煕鐎ｎ剙鈻堥柡灞剧⊕閹棃顢欓崗鑲╁綆闁诲孩顔栭崰妤勩亹閸愵喒鈧箓濡搁埡渚€鍞跺┑鐘绘涧閻楀繘寮搁埀顒€鈹戦悩鎰佸晱闁哥姵顨婃俊闈涒槈閵忕姷锛涢梺瑙勫劤閻°劑宕ｈ箛鎾斀闁绘ɑ褰冮弳鐐烘煏閸ャ劎绠橀柍褜鍓濋～澶娒洪敃鍌氱；濠电姴鍟╃换鍡涙煟閹达絾顥夐崬顖炴⒑閹稿孩顥堥柡渚囧櫍瀹曟垿骞樼€靛摜鐦堝┑顔斤供閸樻悂骞忓ú顏呪拺闁煎鍊曢弸鎴炵節閵忊槄鑰跨€殿喗濞婇弻鍡楊吋閸″繑瀚奸梺姹囧焺閸ㄥジ宕板璺虹濞寸厧鐡ㄩ悡銉╂煛閸ヮ煁顏堟倶椤忓棛纾兼俊銈呭暙閺嬫盯鏌涢埞鎯т壕婵＄偑鍊栧濠氬磻閹炬番浜滄い鎰╁灮缁犱即鎮￠妶鍡愪簻闊洦鎸搁顐ｃ亜閺傛寧鍠橀柡宀€鍠栭幊婵嬫偋閸繃閿紓鍌欑劍瑜板啫顭囬敓鐘茬畺濡わ絽鍟ˉ鍫熺箾閹寸偛绗氶柡鍌楀亾闂傚倷鑳剁划顖炲礉濡棿鐒婃繛鍡楅獜閼板潡鏌熺紒銏犳灍闁绘挻娲栭埞鎴︽偐閹绘帗娈剁紓浣哄Х閸嬬喖鍩€椤掑喚娼愭繛鍙壝—鍐嚍閵夛箑寮块梺閫炲苯澧撮柡灞炬礋瀹曠厧鈹戦崶褎鐣婚梻浣告憸閸嬫盯鎮ラ悡搴綎婵炲樊浜濋ˉ鍫熺箾閹达綁鍝烘い搴℃缁绘繄鍠婂Ο宄颁壕闁惧浚鍋勯弸鐘绘倵鐟欏嫭纾搁柛銊ょ矙閻涱喖螣閼测晝锛滃┑鈽嗗灥濡椼劑鎮界紒妯肩瘈闁汇垽娼у瓭闂佹寧娲忛崐妤呭焵椤掍礁鍤柛锝忕秮楠炲棗鐣濋崟顐ゎ唺闂佸搫鍊搁幖顐ｇ妤ｅ啯鍋℃繛鍡楃箰椤忣亞绱掗埀顒勫礃椤忓棛锛滃銈嗘閸嬫劙鎮為幖浣圭厱闁崇懓鐏濋悘顏堟煙椤栨稒顥堝┑鈩冩倐婵＄柉顧侀柛鐔奉儔閺岋絾鎯旈妶搴㈢秷濠电偛寮堕悧鏇㈡箒闂佸憡娲﹂崢浠嬶綖閺囩喆浜滈柡鍥殔娴滄儳鈹戦纭峰姛缂侇噮鍨堕獮蹇涘川閺夋垵绐涙繝鐢靛Т閸婄懓鈻撳Ο鑲╃＝闁稿本鐟чˇ锕傛煙绾板崬浜滄い顓炴喘閸ㄦ儳鐣烽崶銊︻啎闂備礁鎼ú銏ゅ春閸曨垰鏋侀悗锝庡枟閻撳啰鎲稿鍫濈婵炲棙鎸婚崑鈺呮煟閹达絾顥夌紒鐙呯秮閺屻劑寮村Δ鈧禍鍓х磽娴ｅ搫孝妞ゎ厾鍏樺濠氬Χ婢跺﹦顔愭繛杈剧秬椤鏌ㄩ銏♀拺闁告繂瀚烽崕蹇涙煕婵犲倻浠㈡い顐㈢箰鐓ゆい蹇撳缁愭稒绻濋悽闈浶㈤柛鐕佸亰钘濋柍鍝勬噺閳锋垹绱掔€ｎ偒鍎ラ柛搴＄焸閺屾稓鈧綆鍋呭畷灞炬叏婵犲啯銇濈€规洦鍋婂畷鐔兼濞戞ê顥庨梻鍌欐祰瀹曠敻宕崸妤€鐤炬繛鎴緛缂嶆牠鐓崶銊р姇闁诡垳鍋ら幃宄扳枎韫囨搩浠奸梺鍛娒紞濠傤潖濞差亜宸濆┑鐘辫兌缁讳線姊洪崫銉バｅǎ鍥ㄦそ婵＄敻骞囬锝喰╅梻浣哥枃椤宕归崸妤€绠栨繛鍡樺灦瀹曞鏌ц箛姘兼綈妞ゆ洘顨婂缁樻媴閸涘﹥鍠愭繝娈垮枟閹告娊寮绘繝鍥ㄦ櫜濠㈣泛鐗冮崑鎾存媴閸撳弶鍍甸梺鑲╊焾閻忔艾鈻嶅鍕瘈闁靛骏绲介悡鎰版嫅闁秵鐓涢柛娑卞亜閻忓弶鎱ㄦ繝鍐┿仢鐎规洏鍔嶇换婵嬪礃椤垶袩闂傚倷鑳堕…鍫ヮ敄閸涱垪鍋撳顐㈠祮妤犵偛鍟灃闁告粈鐒﹂弲锝夋⒑缂佹ê鐏ユ俊顐ｇ懅閳ь剟娼ч惌鍌氼潖濞差亝顥堟繛鎴炶壘椤ｅ搫鈹戦埥鍡椾簼闁荤啿鏅犻獮鍐ㄎ熺悰鈩冩杸闁诲函缍嗛崑鍡涘储闁秵鈷戦柛婵嗗瀹告繈鏌涚€ｎ剙鏋戠紒鍌涘笒閳藉濮€閿涘嫬骞楅梻渚€娼ч悧鍡欌偓姘煎枤缁綁寮埀顒勫箞閵婏妇绡€闁告劏鏂傛禒銏ゆ倵鐟欏嫭澶勯柛瀣工閻ｇ兘鎮㈢喊杈ㄦ櫍闂佺粯蓱瑜板啳娼曠紓鍌氬€搁崐鎼佸磹閻戣姤鍤勯柛鎾茬閸ㄦ繃銇勯弽銊х煁鐎规洘鐓￠弻娑樼暆閳ь剟宕戦悙鍝勭；闁冲搫鎳忛悡鐔兼煙鏉堝墽绋绘い銉ヮ樀濮婃椽宕￠悙鏉戞灎闂佸搫鐭夌换婵嗙暦閸洖鐓涘ù锝嗗絻娴滈箖鏌ㄥ┑鍡╂Ц闁绘挻鐩弻娑樷槈閸楃偞鐏撻梺鍛婄懃濡繂顫忓ú顏勪紶闁告洦鍋€閸嬫捇骞栨担鐟扳偓鑸电節闂堟侗鍎忛柣鎾存礋閺岋繝宕橀妸褍顤€闂佺粯鎸搁崯鎾箖瑜版帒鐐婃い蹇撳濮ｃ垻绱撴担鍝勑ｇ憸鏉垮暢瑜颁線姊洪幖鐐插妧鐎广儱鐗嗛幆鍫ユ⒒娴ｇ瓔鍤冮柛鐘愁殜閹兘鍩￠崨顐熷亾娓氣偓瀵噣宕煎┑鍫Ч闂備線娼ч…鍫ュ磿閻楀牏鐝堕柡鍥ュ灪閳锋垿鏌涘┑鍡楊伂闁谎傜窔閹﹢鎮欓幓鎺嗘寖缂備礁顑勭欢姘潖缂佹ɑ濯撮柦妯侯槸閹偤姊洪崫銉バｉ柛鏃€顨婇崺鈧い鎺嶆祰婢规﹢鏌ｅΔ鈧Λ婵嬪春閵夛箑绶為柟閭﹀墻濞煎﹪姊虹紒妯曟垿顢欓弽顬綁鎮ч崼婊呯畾闂佺粯鍔︽禍婊堝焵椤掍胶澧摶鐐层€掑锝呬壕閻庤娲橀崹鍧楃嵁閸ヮ剚鍋嬮柛顐ｇ箑閹絽鈹戞幊閸娧呭緤娴犲鐤い鏍仜閻撴洟鏌熸潏楣冩闁绘挻娲樼换娑㈠箣閻戝洤鍙曢悗瑙勬偠閸庨亶鍩為幋锔绘晪闁糕剝鐟ч弳銈夋⒑閸濆嫭婀伴柣鈺婂灦楠炲啴鍩℃担鐑樻闂佹悶鍎滈埀顒勫箯閿涘嫮纾介柛灞剧懅鐠愪即鏌涢悩宕囧⒌闁诡啫鍡欑杸婵炴垶顭囬崝锕€顪冮妶鍡楃瑨闁挎洩濡囩划鏃堟偨閸涘﹦鍘遍柣搴岛閺呮繈宕濆鍥╃＜闁稿本姘ㄥ瓭濡炪値鍘归崝鎴濈暦婵傜顫呴柣妯垮皺鐎靛ジ姊婚崒娆戝妽闁诡喖鐖煎畷鏇㈩敍閻愯尙顦悗骞垮劚濞诧綁鎮炴繝鍐︿簻闁规崘娉涢弸鍌毭瑰鍕煉闁绘搩鍋婂畷鑸殿槹鎼粹槅鍤ら梻鍌欑贰閸欏酣宕归崼鏇炶摕闁炽儱纾弳鍡涙倵閿濆骸澧伴柣锕€鐗撻幃妤冩喆閸曨剛顦ラ悗瑙勬处閸撴繈鎮橀幒妤佲拺闁绘挸瀵掑鐔兼煕婵炲灝鈧洖宓勯柣鐔哥懃鐎氼喚寮ч埀顒€鈹戦悙鑼闁诲繑绻堝绋库槈閵忥紕鍙嗛梺鍝勬处閿氶柍褜鍓氱换鍫ユ偘椤曗偓瀵粙顢樿閺呮繈姊洪棃娑氬闁瑰啿閰ｉ幃鎸庛偅閸愨斁鎷绘繛杈剧秬濡嫰宕ラ悷鎵虫斀妞ゆ棁濮ょ紞鎴︽偂閵堝鐓忛柛顐ｇ箖婵ジ鏌涢妶鍡樼闁哄本鐩、鏇㈡晲閸℃瑯妲伴梻浣侯焾閿曘倝鎮ユ總绋胯摕婵炴垯鍨归悞娲煕閹板墎绱扮紒顔肩埣濮婅櫣鎮伴垾鍏呭濠电偛顕慨鎾敄閸℃稒鍋傞柣鏂垮悑閻撴瑩姊洪銊х暠濠⒀傚嵆閺岀喖鎮剧仦鍙儳绱掓潏銊﹀碍妞ゆ挸銈稿畷鍗炍旈崘褎顢樼紓鍌氬€烽懗鍓佸垝椤栨粎鐭欓柟鎯ь嚟椤╃兘鏌ㄩ弴鐐测偓鍝ュ閸忓吋鍙忔慨妤€妫楁晶濠氭煟鎼达絽鍘存慨濠勭帛閹峰懘宕ㄦ繝鍌涙畼闂佹眹鍩勯崹閬嶃€冮崼銉ユ瀬妞ゆ洍鍋撻柡浣规崌閹晠宕ｆ径瀣撴岸姊绘担鑺ョ《闁哥姵鎸婚幈銊╁级閹搭厼鏅犲┑鐘绘涧濞层垺绂嶅鍫熺厸闁告劑鍔庢晶娑㈡煥濞戞艾鏋旂紒杈ㄥ浮婵℃悂濡烽鎯ф倯婵犳鍠栭敃锔惧垝椤栫偛绠柛娑卞枤閻熻銇勯弽銊х煀濠殿喛鍋愮槐鎾诲磼濞嗘帒鍘＄紓渚囧櫘閸ㄦ娊寮鈧崹鎯х暦閸ャ劍顔曢梻渚€娼ф蹇曠礊閸℃あ锝夋嚃閳哄啰锛濇繛杈剧悼椤牓鍩€椤掆偓濠€閬嶅极椤斿槈鏃堝礃椤忓棗顦╁┑鐐差嚟婵挳顢栭崨顓у晠婵犻潧妫岄弨浠嬫煟濡绲婚柍褜鍓涢弫璇茬暦閹达箑绠荤紓浣姑禒娲⒑閸涘﹦鈽夐柨鏇畵瀹曘垽鏌嗗鍡╂濡炪倖鍔戦崹鐑樺緞閸曨垱鐓欓悘蹇旂墬濞呭懘宕℃潏鈺冪＜閻庯綆鍋撶槐鈺呮煟閻旂厧浜伴柣鎾卞劦閺屾盯顢曢悩鑼紕闂佸搫妫崑濠傤潖濞差亜浼犻柛鏇ㄥ幘閸斿湱绱撴担鍦弨缂佺姵鐗犻悰顕€宕卞☉妯肩潉闂佸壊鍋掗崑鍛村疾椤掆偓閳规垿鎮╃拠褍浼愰梺鐟板级閻╊垶寮幇顓炵窞閻庯急鍕伖闂傚倷绀侀幉锛勭矙閹达附鏅濋柕澹倻鍓ㄦ繛瀵稿帶閻°劑鎮￠悢鍏肩厓闁告繂瀚稿銉╂煟韫囧鍔滃ǎ鍥э躬椤㈡洟濡堕崨顔锯偓璇差渻閵堝簼绨婚柛鐔风摠娣囧﹪宕奸弴鐐茶€垮┑鈽嗗灦閺€杈┾偓姘矙濮婄粯鎷呴崨濠冨創闂佺懓鍢查澶婄暦閹达箑骞㈡繛鍡楃箰閻忓﹦绱撻崒娆戝妽閼垦囨煕鐎ｎ亝鍤囬柡灞剧洴楠炲洭鍩℃担鍓茬€峰┑掳鍊楁慨鏉懨洪鐑嗘綎婵炲樊浜滅粈鍫ユ煙缂佹ê绗傜紒銊ㄥ亹缁辨挻鎷呯粵瀣闂佺锕ゅ鈥崇暦閸濆嫧妲堥柕蹇曞Х閻嫰姊洪崜鎻掍簽闁哥姵鎹囧畷銏ゆ焼瀹ュ棌鎷洪梺闈╁瘜閸樺ジ宕濈€ｎ喗鐓涢悘鐐额嚙婵倿鏌曢崱妤€鈧潡骞冮敓鐘靛祦闁靛鍎甸崣鍕偓瑙勬礃閸庡ジ篓閸岀偞顥婃い鎺戭槸婢ь垶鏌曢崶褍顏┑顔瑰亾闂佹枼鏅涢崯浼此囨导瀛樷拺閺夌偞澹嗛崝宥夋煕閺冣偓閻熴儵鎮鹃悜钘夐唶闁哄洨鍊ｉ埡鍛厪濠㈣埖绋戦々顒傛喐閻楀牊灏︽慨濠傤煼瀹曟帒顫濋钘変壕鐎瑰嫭鍣磋ぐ鎺戠倞妞ゆ帒顦伴弲顏堟⒑閸濆嫮鈻夐柛妯恒偢瀹曞綊宕掑☉鏍︾盎闂佸搫绉查崝搴ㄦ儗鐎ｎ偁浜滈柟閭﹀灠琚氶梺閫涚┒閸斿矁鐏掗梺鍦焾濞寸兘濡撮幇鐗堚拺闁告繂瀚銉╂煕鎼达絾鏆€殿喛顕ч埥澶愬閻樻彃绁梻渚€娼ч…鍫ュ磿閾忣偆顩烽柍鍝勫暟绾捐棄霉閿濆棗绲诲ù婊堢畺濮婃椽宕ㄦ繝鍌氼潊闂佸搫鍊搁崐鍦矉瀹ュ拋鐓ラ柛顐犲灩瑜板嫰姊洪幖鐐插妧闁告洦鍓欓梻顖炴⒒娴ｅ憡鍟為柡灞诲妿缁棁銇愰幒鎴ｆ憰闂佹寧绻傞悧蹇涙偪閳ь剟姊虹憴鍕婵炲懏娲栭埢鎾舵嫚濞村鏂€濡炪倖姊婚妴瀣礉閻旇櫣纾兼い鏇炴噹閻忥絿绱掗鍛籍闁诡喓鍨介幃鈩冩償閿濆懎袝濠碉紕鍋戦崐鏍暜閹烘柡鍋撳鐓庡⒋闁诡喚鍋ゅ畷褰掝敃閻樿京鐩庨梻浣告贡閸庛倝宕归悽绋跨劦妞ゆ巻鍋撻柟璇х磿缁骞掗幋顓犲弳闂佸壊鍋嗛崰鎾诲储閹€鏀介柣鎰硾閽勫吋銇勯弴鍡楁处閸婂爼鏌ㄩ悢鍝勑ｉ柣鎾寸洴閺屾稑鈽夐崡鐐茬闂佺硶鏅徊楣冨Φ閸曨垰顫呴柨娑樺閸ｎ參姊洪柅娑氣敀闁告梹鍨块悰顕€宕堕澶嬫櫆闂佺硶鍓濋悷锕傚疾閵婏妇绡€缁炬澘顦辩壕鍧楁煕鐎ｎ偄鐏寸€规洘鍔欏浠嬵敇閻愭妲锋繝寰锋澘鈧捇鎮為敃鍌氱煑闊洦绋掗悡娆戠磽娴ｉ潧鐏╅柡瀣枛閺屾稒绻濋崒婊冪厽闂佸搫鐬奸崰鎾舵閹烘嚦鐔煎传閸曨剛绉归梻鍌欐祰閵嗏偓闁稿鎸搁湁闁绘ê妯婇崕鎰版煟閹惧崬鍔滅紒缁樼洴楠炲鎮樺ú璁抽偗妞ゃ垺妫冮崺锟犲川椤旀儳骞堟繝纰樻閸ㄥ磭鍒掗婊呯闁硅揪闄勯悡鍐偡濞嗗繐顏╅柣蹇旀尦閺屾盯鍩℃担鍓蹭純閻庤娲橀敃銏ゃ€侀弮鍫濆窛妞ゆ柨鍚嬪▍銏＄節绾板纾块柛瀣灴瀹曟劘顦寸紒顔碱煼楠炲鏁傞挊澶夋闂備線娼ц墝闁哄懏绋掗、濠囨⒒娴ｅ憡鍟炴繛璇х畵瀹曞綊寮剁拠鐐☉椤粓鍩€椤掑嫬钃熸繛鎴炵矤濡茬厧顪冮妶鍐ㄥ闁瑰啿閰ｉ、姘舵晲婢跺﹦楠囬柟鐓庣摠閹稿寮埀顒佷繆閻愵亜鈧牕顫忔繝姘ラ悗锝庡枛缂佲晝绱撴担濮戣偐鎹㈤崱娑欑厽闁归偊鍨伴悡鎰亜閵夈儺妯€闁哄矉缍侀弫鎰板炊瑜嶉獮瀣渻閵堝啫鐏繛鑼枛瀵偊宕橀鑲╁姦濡炪倖甯掗崐濠氭儗閸℃稒鍊甸柨婵嗛娴滄牕霉濠婂嫮鐭掗柡宀€鍠愮€佃偐鈧稒蓱闁款厽绻涚€涙鐭嬫い銊ョ墢濡叉劙骞掗幘瀵哥Ф闂侀潧臎閸涱垱婢栧┑鐘愁問閸犳牠鏁冮敂鎯у灊妞ゆ牜鍋涚粻顖炴煕濞戝崬鐏￠柛鐘叉閺屾盯寮撮妸銉ょ暗闂佸憡绻冮〃濠傤潖缂佹ɑ濯撮柛娑橈工閺嗗牓姊洪崫鍕潶闁告梹鍨垮缁樼節閸ャ劍娅滈梺鍛婄矆缁€浣糕枔閵娿儺娓婚柕鍫濇婵呯磼閼艰埖纭剁€殿啫鍥х劦妞ゆ巻鍋撻柍瑙勫灴椤㈡瑩寮妶鍕繑闂備胶顭堝ù鐑藉极缂佹ü绻嗛柣鎴ｆ閻撴盯鏌涚仦鍓х煀妤犵偛鐗婄换婵嬫偨闂堟稐娌梺鎼炲妼閻栧ジ鍨鹃敃鍌氱倞妞ゆ巻鍋撶紒鐘虫そ閺岋絽螣閼测晛绗￠梺缁樻尰閻╊垶寮诲☉妯锋闁告鍋為悘鎾剁磽娴ｅ搫啸闁稿鍊濆濠氭晬閸曨亝鍕冮梺鍛婃寙娴ｆ彃浜鹃柟鐑樺殮瑜版帗鍋戦柛娑卞灣閺嗐倝姊虹拠鈥虫灍闁荤啿鏅犻妴浣肝旈崨顓狅紲濠电偞鍨靛畷顒勫箖鐎ｎ喗鈷掗柛灞捐壘閳ь剛鍏橀幊妤呭醇閺囨せ鍋撻敃鍌氶唶闁靛闄勫▍鍥⒑閹稿孩绀€闁稿﹤鎽滄竟鏇熺節濮橆厾鍘梺鍓插亝缁诲啯鍒婇崗鑲╃闁稿繗鍋愭晶鐢告煛鐏炵喎妫涢悿鈧梺鐟板⒔椤ユ劗娑甸埀顒傜磽娴ｅ搫浜鹃柛搴㈠▕瀹曘儳鈧綆鍋嗛埞宥呪攽閻樺弶绁╅柡浣哥У閹便劌顫滈崱妤€绠洪梺绋垮閹告悂鈥旈崘顔嘉ч幖绮光偓鑼泿缂傚倷绀侀ˇ顖滅礊婵犲洨宓侀柛鎰╁妿閺嗗姊洪銊ヮ洭闁告瑥妫濆娲川婵犲啫顦╅梺鍛婃尰閻╊垰鐣峰▎鎾存櫢闁绘ɑ鏋奸幏娲⒑閸涘﹦缂氶柛搴ㄤ憾瀵悂骞嬮敂鐣屽幍闂佸憡绋戦敃銈夊煝閺囥垺鐓熸繛鎴濆船濞呭秶鈧娲橀敃銏ゃ€佸▎鎾村殟闁靛瀵屾禒褔姊婚崒娆掑厡缂侇噮鍨堕垾锕傚醇椤厾鍓ㄥ┑鐐叉閹稿寮查浣虹瘈濠电姴鍊绘晶娑㈡煃闁垮鐏╃紒杈ㄦ尰閹峰懏鎱ㄩ幋顓濈凹闁逛究鍔戝畷鍫曞Ω閿濆嫮鐩庨梻浣告惈濞层垽宕濈仦绛嬪殨妞ゆ棃鏁崑鎾舵喆閸曨剛锛橀梺鎼炲姀濡嫰鎮鹃悜鑺ユ櫢闁绘ê鍟块埀顒傚厴閺屽秹宕崟顐熷亾瑜版帒绾ч柟闂寸劍閳锋帒霉閿濆牊顏犻悽顖涚洴閺屾盯寮埀顒€煤閺嶎収鏁嬮柨婵嗩槸闁卞洭鏌￠崶锝呬壕婵犮垼鍩栭崝鏍磹閻戣姤鐓熼柟瀵稿剱閻掍粙鏌涘▎蹇旑棞闁宠鍨块、娆戠驳鐎ｎ剙濮奸梻浣虹《閺呮粓鎮ч悩璇茬畺闁跨喓濮甸崑鍕煠濞村娅呯憸鏉垮濮婃椽骞栭悙鎻掑闂佺閰ｆ禍璺虹暦濠靛围濠㈣泛顑囬崢浠嬫⒑閹稿海绠撴繛璇х畵瀵娊顢楅崟顒傚幐闁诲繒鍋熺涵鍫曞磻閹惧磭鏆﹂柛銉ｅ妽閻ｇ兘姊虹拠鎻掑毐缂傚秴妫濆畷婊冣枎閹捐櫕妲悗鍏夊亾闁告洦鍏橀幏娲煟鎼粹剝璐″┑顔炬暬钘熷璺侯儍娴滄粓鏌ㄩ弮鍥跺殭闁诲骏绠撻弻娑㈠煘閸喚浠鹃梺璇″灡濡啯淇婇幖浣肝ㄧ憸婊堝触閸涘瓨鈷掑ù锝堟鐢盯鏌涢弮鈧ú鏍敋閿濆閱囬柡鍥╁枎娴犙冾渻閵堝棙纾甸柛瀣尰閹便劍绻濋崒銈囧悑閻庤娲樼敮鎺楀煝鎼淬劌绠ｆい鎾跺晿濠婂懐纾介柛灞捐壘閳ь剙鎽滅划鏃堝箻椤旇姤娅囧銈呯箰濞诧箓鏁嶉崒鐐粹拻濞达絿鐡斿鎰版煕鎼淬垹鈻曢柟顔芥そ婵℃悂鍩℃担铏瑰幀闂傚鍋勫ú锔剧矙閹烘鍋傞柣鏂垮悑閻撳繘鐓崶褜鍎忛柣鎺撴そ閺岋綁骞掗幋婵冩寖缂備浇椴哥敮锟犲箖椤忓牆鐒垫い鎺戝閸ㄥ倿鏌涢锝嗙闁藉啰鍠愮换娑㈠箣閻愬啯鑹惧嵄闁割偆鍠撶粻楣冩煕閳╁厾顏呮叏婢跺瞼纾奸悗锝庝簼瀹告繄绱掓潏銊﹀鞍闁瑰嘲鎳橀獮鎾诲箳瀹ュ拋妫滈梻鍌氬€风粈浣圭珶婵犲洤纾诲〒姘ｅ亾鐎规洘娲熷濠氬Ψ閿曗偓娴滄姊洪崫鍕窛闁哥姴妫欑粋宥咁煥閸曗晙绨婚梺瑙勫礃濞夋盯寮告惔銊︾厽闊洤顑呴崝婊呯磼缂佹娲寸€规洏鍔戦、娆撴偐閸愯尙浠哥紓浣哥焷妞村摜鎹㈠┑瀣倞鐟滃繘顢欏畝鍕拺闁革富鍘奸崝瀣煙闁稖鍏屾繛鎴犳暬閸┾偓妞ゆ帒鍊荤壕浠嬫煕鐏炲墽鎳勭紒浣规緲椤啴寮堕幋鐐村枑闂佽桨绶￠崳锝夊箖濞嗘挸浼犻柛鏇ㄥ幖婵附淇婇悙顏勨偓鏍暜閹烘鏅濋柨鏂垮⒔閻捇姊婚崼鐔烩偓浠嬫偡闁妇鍙嗛梺绯曞墲椤洭濡撮幇鐗堢厱婵°倕瀚崥顐︽煙閸欏鍊愰柟顔ㄥ洤閱囨繝闈涚墢閹虫牠姊绘担铏瑰笡闁圭顭烽幃鐤樄闁糕斁鍋撳銈嗗笒閸婂綊宕甸埀顒勬煟鎼淬垹鍤柛鐘愁殜瀵尙鎹勬担鏇熸瀹曘劑顢橀姀鈽呯船婵犵數鍋涢顓熸叏閹绢噮鏁勯柛鈩冪⊕閸嬪倿鏌￠崶銉ョ仾闁绘挾鍠愭穱濠囶敍濞戝崬鍔岄梺鎼炲€曢鍥焵椤掑喚娼愰柟顔肩埣瀹曟洟鎮界粙璺啈闂佸壊鍋呭ú姗€寮查幓鎺濈唵閻犺櫣灏ㄩ崝鐔肺旈悩鍙夊枠婵﹨娅ｇ槐鎺懳熼崫鍕垫綋闂備礁顓介弶鍨瀷濠电偛妫庨崹钘夌暦閿濆棗绶為柛顐ｇ矌閻?")
        if mode == "direct":
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨奸柟鐧哥秮閺岋綁顢橀悙鎼闂侀潧妫欑敮鎺楋綖濠靛鏅查柛娑卞墮椤ユ艾鈹戞幊閸婃鎱ㄩ悜钘夌；婵炴垟鎳為崶顒佸仺缂佸瀵ч悗顒勬⒑閻熸澘鈷旂紒顕呭灦瀹曟垿骞囬婊€绨婚梺鍝勫暙閸婂綊宕甸埀顒佺箾鐎涙鐭掔紒鐘崇墵瀵鈽夐姀鐘电杸闂傚倸鐗婄粙鎺楁倶閸儲鍊甸柣鐔哄閸熺偟绱掔拠鑼ⅵ鐎殿喖顭烽崺鍕礃閵娧呯嵁闂佽鍑界紞鍡樼閻愬顩烽柟缁㈠枟閳锋垹绱掔€ｎ偒鍎ラ柛搴＄箳缁辨帗寰勭仦鎯ф畬濡炪値鍋勭换鎰弲濡炪倕绻愮€氼亞妲愰崼鏇熲拺闁告稑锕ユ径鍕煕濡崵鐭掗柟顔规櫇缁辨帒螣閻撳骸绠為梻鍌欑閹碱偊宕愰崷顓涘亾缁楁稑娲ょ粻鏌ユ煥濠靛棙宸濈痪鎯у悑閵囧嫰寮崹顔规寖闁汇埄鍨遍惄顖炲蓟閺囥垹閱囨い鎺戝€昏ⅵ闁诲氦顫夊ú姗€鏁冮姀銈呮槬闁跨喓濮寸粈鍐煏婵炲灝鍔ら柣銈呭濮婂宕掑顑藉亾妞嬪孩顐芥慨姗嗗墻閻掔晫鎲搁弮鍥棨濠电偛顕慨鎾敄閸涱垳鐜绘俊銈呮噺閻撴稓鈧箍鍎遍崯顐ｄ繆閼恒儳绠鹃柛娑卞灠鏍￠梺闈涙搐鐎氭澘顕ｉ鍕瀭妞ゆ棁顫夌€垫牜绱撴担鍝勪壕闁稿孩濞婃俊鍫曞箹娴ｆ瓕鎽曢梺鎸庣箓閹冲寮告惔銊у彄闁搞儯鍔嶉悡銉︾箾閸涘洤鎳愮壕钘壝归敐鍛棌婵☆垰鐗撻弻娑㈡晲韫囨洜袦閻庢鍠栭…鐑藉垂閹呮殾闁搞儯鍔嶉悾鐑芥⒒娓氣偓閳ь剛鍋涢懟顖涙櫠鐎电硶鍋撶憴鍕；闁告濞婇悰顔嘉熼崗鐓庣彴闂佽偐鈷堥崜娆愭叏閿旀垝绻嗛柣鎰典簻閳ь剚鐗滈弫顕€骞掑Δ鈧壕鍦喐閻楀牆绗掓慨瑙勭叀閺屽秹宕崟顐熷亾閼哥數顩叉繝濠傚娴滄粓鏌熼幑鎰【濞寸姍鍐剧唵鐟滃骸煤閻旂厧钃熼柨鐔哄Т楠炪垽鐓崶銊︹拹闁绘繃鑹鹃埞鎴︻敊绾嘲濮涚紓渚囧櫘閸ㄥ爼鐛箛娑樺窛閻庢稒锚閻у嫭绻濋姀锝嗙【妞わ缚鍗抽幆鍫ｇ疀閺傚墽绠氶梺缁樺姦娴滄粓鍩€椤戞儳鈧繂鐣烽姀锛勯檮闁告稑锕ゆ禍杈ㄧ節閻㈤潧孝婵炲眰鍊濋幃鎸庛偅閸愨晝鍘剧紓浣割儓濞夋洘绂掑☉銏＄厱閹艰揪绲介弸娑㈡煛鐏炵偓绀冪紒缁樼洴瀹曞綊顢欓悡骞垿姊绘担鍛婂暈婵☆偅鍨圭划濠氬箣閿斿厜鍋撻弮鍫濈妞ゆ柨妲堣閺屾盯鍩勯崘鐐暭闂佽崵鍠嗛崝鎴濐潖閾忓湱鐭欓柛鏍も偓鍏呯矗缂傚倸鍊哥粔鎾晝閵堝鏁嬮柨婵嗩槸缁狀噣鏌﹀Ο渚Ш闁告ê鎲＄换娑㈠箻绾惧顥濆┑鐐茬湴閸旀垵鐣烽鍕仺闁告稑锕ゆ禒顓炩攽閻樿宸ラ柛鐔告尦瀹曪綁宕熼娑氬帾闂佺硶鍓濋〃鍛村汲閻愮數纾肩紓浣诡焽缁犵偟鈧娲栭悥濂稿灳閺嶎収鏁勯柟顖嗗啫袝闂備礁鎼張顒勬儎椤栫偟宓侀柛銉墯椤ュ牊绻涢幋鐐垫噮濞存粠浜濇穱濠囧Χ閸ヮ灝銉╂煕鐎ｎ偄鐏寸€规洖缍婇幃婊兾熺亸鏍ㄦ暤濠电姷鏁告慨鏉懨洪敃鍌氱９闁绘垼濮ら崐鍨箾閹寸偟鎳愰柣鎺曞Г閵囧嫰鏁傞崫鍕瀳闂佸疇顫夐崹鍧楀极瀹ュ绀嬫い鎰ㄢ偓铏啟濠电姷顣藉Σ鍛村磻閸曨厸鍋撳顐㈠祮妤犵偛鍟撮幃娆擃敆婢跺瑩褔鏌熼懝鐗堝涧缂佹彃娼￠幃锟犲箻缂佹鍘介梺缁樏璺侯啅濠靛鐓曢悗锝庡亝鐏忣厽銇勯銏㈢闁靛洦鍔欓獮鎺楀箣閻欌偓閸炵敻姊绘担鍛婂暈濞撴碍顨婂畷褰掑箮閼恒儱鍓瑰┑鐐叉閹稿鎮￠弴鐔翠簻妞ゆ挾鍠庨悘銉︾箾閸涱啝鎴炵┍婵犲浂鏁冮柕蹇婃濡箑鈹戦纭峰伐妞ゎ厼鍢查悾鐑藉箳閹存梹鐎婚梺褰掑亰閸犳捇宕戝Ο璁崇箚闁绘劦浜滈埀顒佺墪閳绘棃鏁冮崒姘獩濡炪倕绻愮€氼亝绔熼弴鐐╂斀闁绘劖娼欓悘锕傛偨椤栨侗娈旈柍璇茬Ч瀹曞爼鍩￠崘顏庣床婵＄偑鍊栧濠氬疾椤愶箑绠犻柛銉厛濞堜粙鏌ｉ幇顓熺稇缂佹甯￠幗鍫曞冀椤€崇秺閺佹劙宕奸锝囩Х闂備胶绮缓鍧楀礉瀹€鍕厴闁硅揪闄勯崑鎰版煕椤垵浜濇慨锝呭缁绘繂鈻撻崹顔界亞闂佸憡顨呴崯鍧楁偩閻ゎ垬浜归柟鐑樻尭娴滄鏌熼悡搴ｆ憼閽冮亶鏌ｈ箛鎾虫殭闁宠鍨块幃娆撳级閹寸姳妗撴繝娈垮枟鑿ч柛鏃€鍨块獮鍡楃暆閸曨偆顔掗梺鍏兼倐濞佳囧几閹达附鈷戠紓浣癸供濞堟棃鏌ｅΔ鈧Λ娑氬垝椤撱垹绠虫俊銈勮兌閸欏啴姊洪崨濠傚Е濞存粍绮撳绋库槈閵忥紕鍘搁柣蹇曞仧閸嬫挾绮堥崘顏嗙＜缂備焦顭囧ú瀵糕偓瑙勬礀缂嶅﹪銆佸▎鎾村亗閹兼惌鍠楃紞宥嗙節閻㈤潧啸妞わ絼绮欏畷婊冣攽婵炲じ姹楅梺鍛婂姦閸犳宕戠€ｎ亖鏀介柣妯诲絻閺嗙喖鏌嶉悷鎵㈤柍瑙勫灴閹晠宕ｆ径灞诲亹闂備浇妗ㄧ粈浣虹矓閻㈠灚宕叉繛鎴欏灩楠炪垺淇婇婵囥€冮柛鎺戯躬濮婃椽宕ㄦ繝鍐弳闂佺懓鍟块柊锝夊春閻愬搫绠ｉ柨鏃囨閳ь剛鍏橀弻銈囧枈閸楃偛顫╅梺鍐插槻閻楁挸顫忓ú顏勫窛濠电偞甯╂禍婵嬪疾閸洘瀵犲鍏夋櫔缂嶄線鐛崶顒€绾ч悹渚厛閸熷姊洪懡銈呅㈡繛娴嬫櫇娴滅鈻庨幘瀛樻珫濠电姴锕ら崯鐘诲绩閼恒儯浜滈柡鍐ㄥ€稿畵鍡涙煙鏉堥箖妾柛搴★躬閺岋綁骞嬮敐鍛呮捇鏌￠崨顔肩祷妞ゎ叀娉曢幑鍕瑹椤栨艾澹堥梻浣虹帛缁诲啫螞閸愵喖钃熼柍鈺佸暙缁剁偛鈹戦悩鎻掝仼妞わ絿鏁诲娲传閸曨剙娅ょ紓浣筋嚙鐎氼厾绮╅悢鐓庡嵆闁绘梹妞藉顕€姊洪崨濠勨槈闁挎洏鍊濋崺鈧い鎺戝€归弳顒勬煛鐏炶濡奸柍瑙勫灴瀹曞崬鈻庤箛鎾寸槗闂傚倷娴囬鏍窗閺嶎偆鐭撻柣鐔稿珗濞戙垹宸濋柟纰卞幗閺呫垺绻濋姀锝嗙【闁挎洏鍊濋崺娑氣偓锝庡枟閳锋垿鏌涘┑鍡楊伀闁诲繘浜堕弻娑㈡偐瀹曞洤鈷岄梺闈涙缁€渚€鍩㈡惔銊ョ闁稿繐鎳愰悙濠囨⒒娴ｅ憡鍟炴繛璇х畵瀹曘垽鎼圭憴鍕垫綗濠电偛妫欓幐濠氭偂閻旂厧绠规繛锝庡墮閳ь兙鍊曢…鍥箛椤撶姷顔曢梺鍦帛鐢偟绮婚懡銈傚亾鐟欏嫭绀冪紒璇插€块、妯荤附缁嬭法鍊為梺闈涱焾閸庤京鑺遍妷锔剧瘈闁汇垽娼ч埢鍫熺箾娴ｅ啿鍘惧ú顏呮櫆闁芥ê顦悘渚€姊洪崷顓℃闁哥姵顨婇幃锟犲即閻旇櫣鐦堥梻鍌氱墛缁嬫帡藟濠婂嫨浜滈煫鍥风到娴滄繈鏌曢崶褍顏鐐叉喘椤㈡瑩鎮℃惔婵堝笡闂傚倷绀侀悿鍥綖婢舵劕鍨傞柛褎顨呯粻鏍煃閸濆嫭鍣归柛銊ュ€归妵鍕箛閸撲胶蓱闂佷紮绠戞鎼佸煘閹达附鍋愰柛顭戝亝濮ｅ嫰姊虹粙娆惧剱闁告梹鐟ラ悾鐑藉箣閿曗偓缁犲鏌￠崒妯哄姕闁哄倵鍋撻梻鍌欒兌缁垶宕濋弽褜鐔嗘俊顖炴？閻掑﹪鏌涢幇闈涙灍闁绘挻娲熼弻鏇熷緞鐎ｎ亞浠撮梺褰掓敱閸ㄧ懓危閹伴偊鏁嬮柍褜鍓欓～蹇曠磼濡顎撻梺鑺ッ敍宥夊箻缂佹鍙嗗┑顔筋焾閸╂牠鎮￠妷锔剧闁瑰鍎戞笟娑欎繆閸欏鍊愰柡灞界Ч閹稿﹥寰勫Ο鐑╂瀰濠电姵顔栭崰鎺楀磻閹剧粯鈷戠紓浣广€為幋锔绘晩闁哄稁鐏涢敐鍥ㄥ枂闁告洦浜炵粻姘舵⒑缂佹ê濮﹀ù婊勭矒閸┾偓妞ゆ帊鑳舵晶鐢碘偓瑙勬礃缁诲牓寮崘顔肩＜婵﹢纭稿Σ鑸电節閻㈤潧鈻堟繛浣冲浂鏁勯柛娑樼摠閸婂潡鏌涢…鎴濅簴濞存粍绮撻弻鐔煎传閸曨厜銈嗐亜閿斿ジ妾柕鍥у瀵挳鎮㈤搹鍦帨闂備礁鎼張顒€煤閻旈鏆﹂柟顖炲亰濡茶顪冮妶鍛闁告挻绋撳Σ鎰板箳濡や礁浜归悗瑙勬礀濞诧箓宕氬☉妯滄棃鎮╅棃娑楁勃濡炪値鍘煎ú顓㈢嵁閹达箑绀嬫い鎺戝€婚幊婵嗩渻閵堝棛澧紒瀣浮閹線骞掗弮鍌滐紳闂佺鏈懝楣冨焵椤掍焦鍊愮€规洘鍔栭ˇ鐗堟償閵忕媭鈧盯姊洪崫鍕潶闁稿氦浜竟鏇熺節濮橆厾鍘甸梺缁樺姦閸撴瑦鏅堕鐐寸厽闁哄倹瀵чˉ銏ゆ煛鐏炶鈧繈鐛弽銊﹀閻熸瑥瀚伴弫顏勨攽閻樻剚鍟忛柛鐘崇墵閹囧箻鐠囪尪鎽曢梺鎸庣箓椤︻垳绮婚懡銈傚亾鐟欏嫭绀€婵炲眰鍔戦、娆撳炊椤掍讲鎷洪柣搴℃贡婵厼顭囬幇鐗堢厱闁靛鍎查崑銉︻殽閻愭彃鏆ｉ柛鈺嬬節瀹曘劑顢欓崗纰卞悋濠碉紕鍋戦崐鏍暜閹烘纾婚柛鈩冪☉閼歌绻涘顔荤凹闁抽攱甯掗湁闁挎繂顦藉Λ鎴濃槈閹剧懓鐨虹紒杈ㄦ尭椤撳吋鎷呴梹鎰棜濠电姷顣槐鏇㈠磻濞戙垺鍋ら柕濞炬櫅缁犳牠鏌涚仦鍓р棩缂佽妫濋弻锝夊閵忊晝鍔哥紓浣插亾閻庯綆鍋佹禍婊堟煛瀹ュ海鍘涢柛銈冨€楅幉鎼佸籍閸繆鎽曞┑鐐村灟閸ㄥ綊宕￠幎鑺ョ厪濠电偛鐏濋崝姘辩磼閻樺樊鐓兼慨濠呮缁辨帒螣鐏忔牗锛堥梻浣规偠閸斿繐螞閸曨垽缍栭煫鍥ㄦ媼濞差亶鏁傞柛鏇ㄤ簽閻愬﹪姊绘担鍛婂暈婵炶绠撳畷婊冾潩鐠鸿櫣顔嗛梻渚囧墮缁夌敻鍩涢幋锔界厽闁瑰瓨姊瑰▍鍡樼箾閸涱喗宕岄柡灞剧洴婵℃悂濡疯閻撶喖姊虹拠鈥虫灆闁告濞婇妴浣糕枎閹惧啿绨ユ繝銏ｆ硾閼活垶寮稿☉銏＄厵闁绘挸瀛╃拹锟犳煙閸欏灏︾€规洜鍠栭、妤佸緞婵犲啯鐝梻鍌氬€搁崐鎼佸磹閻戣姤鍊块柨鏇炲€哥粻鏍煕椤愶絾绀€缁炬儳娼￠弻娑樜旈崘銊㈠亾閿濆應妲堟繛鍡樺姇閸斿懘姊洪棃娑辩劸闁稿酣浜堕幃妤咁敇閻旇櫣顔曢柣搴ｆ暩椤牆鐡俊鐐€栭崹鐢稿箠濮椻偓楠炲繘骞嬮敂钘変簻闂佸憡绺块崕鎶筋敊閺囥垺鈷戦柣鐔煎亰閸ょ喖鏌涙惔銏犲闁诡喚鍋ら獮鏍ㄦ媴閸︻厼骞楅梻浣告惈閸婃悂鎮樺┑瀣畺闁硅揪闄勯悡鏇㈡煏閸繃顥滄繛鎼櫍閺岋紕浠﹂悙顒傤槹閻庤娲滈崢褔鍩為幋锕€骞㈡俊顖濆吹閺夊綊姊婚崒娆掑厡妞ゎ厼鐗撻、鏍幢濞戞顔夐梺鎼炲労閸撴稑鐣垫笟鈧弻鐔兼倻濡儤顔曢梺鍝勫暊閸嬫捇鏌熷畡鐗堝殗鐎规洦鍋婂畷鐔碱敃閵堝骸鎮戝┑鐘垫暩婵兘銆傞鐐潟闁哄洢鍨圭壕缁樼箾閹存瑥鐒洪柡浣稿閺屾稑鈽夐崡鐐寸彯濠电偛鐗呯划娆撳蓟閻斿吋鈷掗悗闈涘濡差噣姊虹紒妯诲鞍缂佽鐗撳璇测槈閵忊晜鏅濋梺缁樻⒒椤牆鈻嶅鑸碘拺缂佸顑欓崕鎰版煙閸涘﹥鍊愰柛鈹垮灲楠炴鎷犻幓鎺斺偓顓烆渻閵堝棙鈷掗柡鍜佸亝缁傚秹顢旈崼鐔叉嫽婵炶揪缍€濞咃絿鏁☉銏＄厽婵°倓鐒︾粈瀣攽閳ュ磭鍩ｆ鐐寸墬閹峰懘鎮锋０浣洪挼濠碉紕鍋戦崐鏍涢崘顔兼瀬妞ゆ洍鍋撶€规洘鍨块獮妯肩磼濡粯鐝抽梺鍦帶閻°劎鎹㈤崟顖氱濠㈣埖鍔栭埛鎴︽偠濞戞巻鍋撻崗鍛棜婵犵數鍋涢顓熸叏閹绢噮鏁勯柛鈩冪⊕閸嬪倿鏌￠崶銉ョ仾闁绘挸绻愰…璺ㄦ崉閾忕懓顣洪梺璇叉禋娴滄繄鎹㈠☉銏犲窛妞ゆ挾鍣ュΛ锟犳⒑闂堟稒鎼愰悗姘嵆閵嗕線寮撮姀鈩冩珳闂佹悶鍎弲婵嬪汲椤愩倗纾介柛灞剧懆閸忓瞼绱掗鍛仯闁瑰箍鍨藉畷濂稿Ψ閵壯呮毇濠电偛顕慨鎾敄閸℃蛋澶愬醇閻旇櫣顔曢梺鐟邦嚟閸庢劕鈻撻弮鍫熺厵闁芥ê顦介崕鏃€鎱ㄦ繝鍕笡闁瑰嘲鎳愮划鐢碘偓锝庡亞缁夐攱绻濈喊澶岀？闁稿鍋熼埀顒傜懗閸涱垳鐒块悗骞垮劚椤︿即宕愭搴樺亾閻熸澘顥忛柛鐘崇墪閳绘捇顢曢敐鍥╃槇闂佹眹鍨藉褍鐡繝鐢靛仜閻即宕愬Δ鍐ㄥ灊缂備焦锚椤曢亶鏌℃径瀣仼妞ゆ梹鍔曢埞鎴︽倻閸モ晝校闂佸憡鎸婚悷鈺呭箖濮椻偓閸╋繝宕橀敐鍛濠电偛鐗嗛悘婵嬪几濞戞瑧绠鹃悘蹇旂墤閸嬫捇骞囨担鍦▉婵犵數鍋涘Ο濠冪濠婂牆绠查柤鍝ュ仯娴滄粓鏌熺紒銏犵仩濠⒀冨级閵囧嫭鎯旈姀鈺傜杹濠殿喖锕ュ钘夌暦椤愶箑唯闁靛鍔х紞渚€寮婚敐鍛傛棃宕橀妸鎰╁灪閵囧嫰顢曢姀銏㈩唹缂備胶绮换鍌烇綖濠靛绀傞柛蹇撳悑閻濐偄鈹戦悩鍨毄闁稿鍋ゅ畷褰掑醇閺囩喎浜遍梺鍝勫暙閸婅姤鎱ㄩ崘娴嬫斀闁绘ê纾。鏌ユ煃闁垮鐏撮柡灞剧☉閳规垿宕卞Δ濠佺磻闁荤偞鍑规禍顏勵潖濞差亜宸濆┑鐘插暟閸欏棝姊绘担绋跨盎缂傚秳绀侀悾宄懊洪鍕庛劑鏌ㄩ弴妤€浜剧紓浣稿閸嬬喖鍩€椤掆偓閸樻粓宕戦幘缁樼厓鐟滄粓宕滃☉娆戠彾闁哄洨鍠撻梽鍕煕濞戞﹫鍔熼柛姗€浜跺铏规喆閸曨偆顦ㄩ柣蹇撶箲閻熲晞妫熼梺鎸庢磵閸嬫捇妫佹径鎰厽婵☆垱顑欓崬娲煙閺屻儳鐣洪柡灞糕偓宕囨殕閻庯綆鍓涢敍鐔哥箾鐎电顎撶紒鐘虫尭閻ｅ嘲顭ㄩ崱鈺傂梻浣告啞鐢绮欓幒鏃€宕叉繝闈涚墕閺嬪牆顭跨捄铏圭伇闁挎稓鍠栧铏圭矙鐠恒劎顔夐梺鎸庢磸閸ㄨ姤淇婄€涙ɑ濯寸紒顖涙礃閻庡姊洪崷顓炰壕婵炲吋鐟︾粋宥呂旈崨顔惧幍闂佺绻愰崥瀣磿濡ゅ懏鐓曢柣妯诲墯濞堟洘銇勯妸锝呭姦鐎规洜鍠栭、娑樷槈閹烘挸顏归梻浣藉吹婵潙煤閵堝拋鍤曢柛顐ｆ礀閼哥懓顭跨捄渚剭濞存粍绮嶉妵鍕箛閳轰胶鍔村┑鈥冲级閹倿骞冮敓鐘参у璺侯儑閸樻捇姊洪崨濠勭畵閻庢凹鍓熷鎶芥偄閾忓湱锛滈梺閫炲苯澧紒缁樼箞瀹曟帒螣瀹勯澹曢梺鍦劋閸╁牆顭囬埡鍛叆婵犻潧妫欓崳绋款熆鐟欏嫭绀冨ǎ鍥э躬婵″爼宕堕‖顔哄劦閺屾稓鈧綆鍋嗗ú瀵糕偓瑙勬处閸ㄥ爼鐛惔銊﹀癄濠㈠厜鏅粻鎾诲蓟閻斿吋鍋嬮柛顐ゅ枔閸戯紕绱撴担鍝勑ｅ┑鐐诧躬瀵鎮㈢悰鈥充壕闁汇垺顔栭悞鍓р偓娑欑箞濮婃椽鏌呴悙鑼跺濠⒀傚嵆閺屾稓鈧絻鍔岄埀顒佹礋閿濈偠绠涢幘浣规そ椤㈡棃宕熼褍鏁归梻浣烘嚀閸氬鎮鹃鍫濆瀭濠电姵纰嶉弲顒佺箾閹寸偞鐨戠痪鎹愭闇夐柨婵嗘缁茶霉濠婂懎浜剧紒缁樼洴楠炴﹢寮堕幋鐘插Р闂備胶顭堥鍡涘箰妤ｅ啫鐒垫い鎺戝枤濞兼劖绻涢幓鎺旂鐎规洝顫夌粋鎺斺偓锝庝簻閻庮厽淇婇妶蹇曞埌闁哥噥鍋勮灋婵せ鍋撻柡灞炬礃瀵板嫬鈽夐姀鈽嗏偓宥夋⒑閸濆嫷妲归柟顔煎€搁～蹇曠磼濡顎撻梺鎯х箳閹虫挾绮敓鐘斥拺闁告稑锕ラ埛鎰亜椤撶偞澶勭紒鍌氱Ф缁瑦鎯旈幘瀵糕偓濠氭⒑瑜版帒浜伴柛妯圭矙閹潧鐣￠幍铏杸闂佺粯鍔栧娆撴倶閻斿吋鐓曢柕濠忛檮閵囨繈鏌熼鍡欑瘈鐎殿喗鎸虫慨鈧柨娑樺鐢儳鈹戦悩鍨毄闁稿鐩幃妯衡攽鐎ｎ亞顦┑鐘诧工閻楀﹪鎮￠弴銏″€甸柨婵嗗暙婵″ジ鏌涢弬璇测偓婵嬪蓟瀹ュ牜妾ㄩ梺鍛婃尰瀹€鎼併€佸▎鎾冲唨妞ゆ挾鍋熼悰銉╂⒑閸濆嫮鈻夐柛妯绘倐閸┾偓妞ゆ帒锕﹂悾閬嶆煟閿濆繒绡€妤犵偛绉归、娆撴嚍閵夘喖鏅梻鍌氬€风粈浣圭珶婵犲洤纾婚柛娑卞姸濞差亝鏅濋柛灞剧閻庮剟姊虹化鏇炲⒉妞わ箓缂氶妵鎰板箳閹惧瓨鐝抽梻浣稿閸嬫帡宕戦崨顖滅闁割偁鍎查埛鎴犵磽娴ｈ鐒界紒鐘崇墪閳规垿鎮欑拠褍浼愬銈庡亜缁绘帞妲愰幒鎳崇喓鎷犲顔瑰亾閹剧粯鈷戦柛娑橈功閳藉鏌ㄩ弴妯衡偓婵嗩嚕閹惰棄閱囨繝闈涘暞閺傗偓闂備胶绮崝娆撀烽崒鐐插惞閻庯綆鍓涚壕濂告煟濡寧鐝悘蹇ｅ弮閺岋綁鏁愰崶褍骞嬮梺杞扮劍閸旀瑥鐣烽崡鐐嶇喖宕崟顐嬨倝姊婚崒娆戠獢婵炰匠鍛床闁圭儤鎸搁崹鏃€銇勯幘鍗炵仼闁告艾缍婇弻鏇㈠醇濠垫劖效闂佹娊鏀遍崹鍧楀蓟閻斿吋鍤冮柍杞版缁爼姊洪崨濠冣拹闁挎洏鍨藉璇测槈閵忕姵顥濋梺鍦焾鐎涒晛鐣峰畷鍥╃＝濞撴艾娲ら弸銈囩磼椤曞懎鐏﹀┑鈥崇埣閺佹劖寰勬繝鍕垫О闂備礁鍟块幖顐﹀疮椤愶妇宓佺€广儱顦伴埛鎴︽偣閸パ冪骇闁圭櫢缍侀弻鈩冩媴鐟欏嫬鈧劙鏌嶉妷顖滅暤鐎规洖銈搁幃銏＄瑹椤栨稓銈梻鍌欑劍鐎笛兠洪弽顓炵９鐟滅増甯楅崑鍌涚箾閸℃ê濮傚ù婊勭矒閺屸€愁吋閸愩劌顫呮繝銏ｎ潐钃遍柕鍥у缁犳稒绻濋崘鈺冨綃婵犵妲呴崑鍌炴倿閿曗偓椤曘儵宕熼娑樹壕闁挎繂楠告晶浼存煟閿曗偓閻楀﹦鎹㈠┑瀣仺闂傚牊鍒€閵忋倖鐓曞┑鐘插€荤粔铏光偓瑙勬礃婵炲﹪骞冮悜钘夌疇濠电姴鍊荤粔娲煙椤旇娅呴柍璇叉唉缁犳盯寮▎鐐熼梻鍌欒兌缁垶骞愮拠瑁佹椽鎮㈤悡搴ゆ憰闂佺粯鏌ㄩ崥瀣磹缂佹ü绻嗘い鏍ㄧ箥閸ゆ瑧鐥弶璺ㄐ㈤柍瑙勫灴閹瑧鈧稒锚閸撳綊姊洪崫銉バｉ柣妤冨█瀹曟椽鎮欓崫鍕吅闂佹寧娲嶉崑鎾绘煟閹烘挻銇濋柡灞剧洴楠炲洭濡搁敂鐣屽絽闂備線鈧偛鑻晶顖炴煕閺冣偓閻熲晛顕ｇ拠娴嬫闁靛繒濮烽崢鎾⒑鐠団€崇€婚柛鎰剁稻鐎氱喖姊婚崒娆掑厡闁硅櫕鎹囧畷鏌ュ蓟閵夈儳鐤囬梺褰掑亰閸犳牠宕瑰┑鍥╃闁糕剝蓱鐏忣厾绱掗悩鍗炲祮妤犵偞鐗犻獮鏍敇閻愬浜梻浣筋嚃閸犳牠顢栭崨鏉戠厴闁硅揪闄勯崑鎰版煕椤垵浜濇慨锝呭缁绘繂鈻撻崹顔界亾闂佺绻戦敋妞ゆ洩缍侀、鏇㈡晝閳ь剙顔忓┑鍡忔斀闁绘ɑ褰冮弳娆戔偓娈垮枛濞硷繝骞冨Δ鍛祦闁割煈鍠栨慨搴☆渻閵堝繐鐦滈柛銊ョ－閸掓帡宕奸妷銉ь槰闂佸磭鎳撻妵妯艰姳婵犳碍顥婃い鎰╁灪婢跺嫰鏌熺粙娆剧吋鐎规洘濞婇幊鐐哄Ψ瑜忛鏇㈡⒑閸撴彃浜濈紒瀣灴閸┾偓妞ゆ帊鑳剁粻鎾淬亜?")
        elif mode == "guided":
            lines.append("濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ゆい顓犲厴瀵鏁愰崨鍌滃枎閳诲酣骞嗚椤斿嫮绱撻崒娆掑厡濠殿喗鎸抽幃妯侯潩鐠轰綍锕傛煕閺囥劌鏋ら柣銈傚亾闂備礁婀遍崑鎾诲箚鐏炶娇娑㈡倷閻㈢數锛濇繛杈剧悼閺咁偊宕奸鍫熺厱濠电姴鍟扮粻鐐碘偓娈垮枛椤兘骞冮姀銈嗘優闁革富鍘鹃崢顖炴⒒娴ｇ顥忛柣鎾崇墦瀹曟娊顢氶埀顒€鐣峰┑鍥х窞闁归偊鍘搁幏娲⒑閸涘﹦鈽夐柨鏇畵楠炲﹪宕橀鍡欙紲缂傚倷鐒﹂敋婵炴惌鍣ｉ弻娑㈠煘閹傚濠碉紕鍋戦崐鏍暜閹烘绐楁慨姗嗗墻閻掍粙鏌熼柇锕€骞樼紒鐘荤畺閺屾稑鈻庤箛锝喰ㄦ繝鈷€灞奸偗闁诡噯绻濇俊鑸靛緞鐎ｎ剙甯惧┑鐘垫暩閸婎垶宕橀埡浣诡仧缂傚倷鐒﹂〃鍛此囬棃娑辨綎婵炲樊浜滄导鐘绘煕閺囥劌浜愰柛瀣崄閵囨劙骞掑┑鍥ㄦ珗婵犵數鍋涘Λ娆撳箰婵犳艾纾婚柛鏇ㄥ灡閻撴洟鏌嶉埡浣告殶闁愁垱娲熼弻锝夊箻鐠鸿　鏋呴梺鍝勭灱閸犳牕顫忛懡銈傚亾閻㈡鐒惧┑陇妫勯埞鎴︽倷閺夋垶鐦戦梺鍛婂姧缁查箖寮埀顒佷繆閻愵亜鈧牕螞娓氣偓瀹曟垿骞囬鐔哥彿闂佹寧娲栭崐褰掓偂濞戙垺鍊堕柣鎰絻閳锋棃鏌曢崱妯烘诞闁哄苯绉烽¨渚€鏌涢幘鍗炲鐎垫澘锕ョ换婵嗩潩椤掑偆妲烽梺璇茬箳閸嬬喖宕戦幘璇茬煑闊洦绋掗悡鏇犫偓鍏夊亾闁逞屽墴瀹曟垿鎮欓悜妯轰簵濠电偞鍨崹娲磹閸洘鐓熼柟鎵濞懷兠瑰鍐ㄢ挃缂佽鲸甯￠崺鈧い鎺戝缁€鍐┿亜韫囨挻顥犻柨娑欑矌缁辨捇宕掑▎鎴濆濡炪値鍘煎ú銊у垝鐠囧樊娼╅弶鍫氭櫇閿涙粓姊虹紒妯忣亞澹曢銏犵叀濠㈣泛顑冩禍婊勩亜閹板墎鎮肩紒鐘靛仦閵囧嫰濮€閳藉棙鐣烽梺鐟板槻閹虫劙宕犻弽顓炲嵆闁绘劖婢橀ˉ姘舵⒒娴ｅ憡鎯堟繛灞傚灲瀹曠懓煤椤忓嫮鍘遍梺鍦劋閸ゆ俺銇愰幒鎾存珳闂佸憡娲﹂崳顕€宕濋崨瀛樷拺缂備焦锚缁椦囨煕鐎ｎ偅宕屽┑锛勬暬瀹曠喖顢涘槌栧悈婵犵數濞€濞佳兠归崒姣兼盯鏁冮埀顒冪亙闂佺粯锕㈠褎绂掗敃鍌涚厱闁靛鍎虫禒銏ゆ煟閿濆洤鍘寸€规洖銈稿鎾倷瀹ヤ焦娅婇柡灞炬礋瀹曠厧鈹戦崶褏鐛╅梻浣风串缂嶄胶绮婚弽褜娼栫紓浣股戞刊鎾煕閿旇骞楅柤鍨喘濮婅櫣绮欏▎鍓у姼闂佺锕ョ换鍌炴偩閻ゎ垬浜归柟鐑樻尭娴滄螖閻橀潧鍓遍柛鎾卞妿缁辩偞绗熼埀顒勭嵁婵犲洤鍐€妞ゆ挾鍋熼崢鎼佹⒑閸涘﹤濮﹀ù婊堫棑濡叉劙宕樺ù瀣杸闂佺粯鍔橀崺鏍亹瑜忕槐鎺楀箵閹烘挸浠村Δ鐘靛仜閿曨亪鐛Ο鍏煎磯闁惧繐婀遍悺妯肩磽閸屾艾鈧兘鎮為敃浣哥稑濠电偛鐡ㄧ划宥囧垝瀹ュ桅闁告洦鍨扮粻濠氭偣閾忚纾柕蹇嬪€栭悡鏇熶繆椤栨繃顏犻柟鐣屽У閵囧嫰濡搁敐鍛Е闂佽鍠楅悷鈺呯嵁閹捐绠抽柟鐐儗閸熷姊婚崒娆愮グ妞ゆ洘鐗犲畷鏉课旈崘銊ョ亰闂佽宕橀褏绮婚弶搴撴斀闁绘ɑ褰冮弳娆戠磼閸撲礁浠滈柍瑙勫灴閹晠骞撻幒鍡椾壕濠电姵鑹惧洿濡炪倖鏌ㄩ惃鐑藉绩娴犲鐓熸俊顖濐嚙婢ь垶鏌涢悢椋庣闁哄本鐩幃鈺呭箛娴ｅ湱鏉归梻浣芥〃缁€渚€宕€涙ɑ鍙忛柍褜鍓熼弻鏇＄疀婵炴儳浜鹃柛鎰絻缁犺尙绱撻崒姘偓椋庣矆娓氣偓椤㈡牠宕奸妷顔芥櫔闂佽鍎兼慨銈夊疾閹绘帩鐔嗛柤鍝ョ仚閹达箑鐤炬い蹇撶墛閳锋垿姊洪銈呬粶闁兼椿鍨遍弲鍫曨敊婵劒绨诲銈嗗姂閸ㄨ崵绮绘繝姘厵妞ゆ梻鏅惌濠囨懚閿濆懌鈧帒顫濋悡搴ｄ哗濠电偛鐗嗛崥瀣崲濠靛鍋ㄩ梻鍫熺◥缁泛鈹戦埥鍡椾簼闁荤啿鏅涢悾鐑藉捶椤撶喎鏋傞梺鍛婃处閸樺ジ鍩呮导瀛樷拻闁稿本鑹鹃埀顒佹倐瀹曟劖顦版惔锝囩劶婵炴挻鍩冮崑鎾搭殽閻愬樊妯€闁轰焦鎹囬幃鈺呮嚑椤掑鏁规繝寰锋澘鈧呭緤娴犲鐤い鎰╁€楅悳缁樹繆閵堝懏鍣圭紒鐘茬秺閺岀喓鍠婇崡鐐茬闂佸憡蓱閻╊垶寮婚埄鍐╁闁告挻褰冮崜鍫曟⒑閸濆嫯顫﹂柛鏂跨焸閸╃偤骞嬮敃鈧獮銏ゆ煃閸濆嫬鈧敻寮搁弮鍫熲拻濞达綀濮ら妴鍐磼閳ь剚绗熼埀顒€鐣烽鐐茬妞ゆ棁澹堥幗鏇㈡⒑閸濆嫭鍌ㄩ柛銊ョ秺閺屽宕堕妸褏鐦堥梻鍌氱墛缁嬫帡藟閹达附鐓曢悗锝庡亝瀹曞瞼鈧娲忛崝宥囨崲濠靛绀嬮柛顭戝亰閺佹粍绻濆閿嬫緲閳ь儸鍛筏濞寸姴顑呴悿顔姐亜閺嶎偄浠滈柣鎾存礋閺岀喖鎮滃鍡樼暦闂佺粯鎸诲ú姗€濡甸崟顖氱疀闁宠桨璁查崑鎾诲即閵忕姴鍤戦梺鍝勫暙閻楀﹪鎮￠崘鈹夸簻闁哄秲鍔庨埊鏇犵磼閳ь剛鈧綆鍠楅悡娑氣偓鍏夊亾闁逞屽墴瀹曚即寮借閺嗭箓鏌ㄥ┑鍡橆棞缂佸墎鍋ら幃妤呮晲鎼存繄鎸夐梺绋款儐閹瑰洭鐛崶顒佸亱闁割偁鍨归獮鎰版煟鎼粹€冲辅闁稿鎹囬弻宥堫檨闁告挾鍠庨悾閿嬪閺夋垵鍞ㄥ銈嗘尵閸嬬喖鎮块崶顒佲拺缂備焦锚婵洭鏌熺喊鍗炰簻闁轰緡鍣ｅ缁樻媴閻熼偊鍤嬪┑顔硷工椤兘骞栫憴鍕劅闁愁厹鍎荤紞浣割嚕閼稿灚鍎熼柟鎯х摠閺夋悂姊绘担铏瑰笡闁搞劑娼х叅闁靛ň鏅涚粈鍡涙煟濡も偓閻楀繒绮绘ィ鍐╁€堕柣鎰絻閳ь剚鎮傞崺鈧い鎺嶈兌缁犵偟鈧鍣崑濠傜暦濮椻偓椤㈡瑩宕叉竟顖氭处閻撴洘銇勯幇闈涗簼缂佽埖姘ㄧ槐鎺楀Ω瑜嶉崢瀛樻叏婵犲偆鐓肩€规洘甯掗埢搴ㄥ箣閻橀潧搴婇梻鍌欑窔閳ь剛鍋涢懟顖涙櫠娴煎瓨鐓曢悗锝庡亞濞叉挳鏌熷畷鍥ф灈妞ゃ垺绋戦埥澶娾枎閹邦喖濞囬梻鍌欑濠€閬嶆惞鎼淬劌绐楁俊銈呮噺閸嬪倹绻涢崱妯哄濞存粍绮撻弻锟犲磼濠垫劕娈繝纰樷偓鍐叉倯缂佺粯绋撻幏鐘侯槾闁伙絿鏁搁埀顒冾潐濞叉﹢宕濆▎鎾崇畺婵犲﹤鐗婇崵宥夋煏婢诡垰鍟粻鐐测攽閿涘嫬浜奸柛濞垮€濆畷銏＄鐎ｎ亜鐎梺鍓茬厛閸嬪棝銆呴弻銉︾厾闁诡厽甯掗崝銈囩磼閻樿崵鐣洪柡灞诲€曢湁閻庯綆鍋呴悵鏃堟⒑閸濆嫷鍎忛梺甯秮瀵顓奸崶銊ユ瀭闂佸憡娲﹂崑鍡樺瀹€鍕拺閻犲洠鈧櫕鐏€闂佸搫鎳忕换鍕ｉ幇鏉跨闁瑰啿纾崰鎰崲濠靛棭娼╂い鎾跺枑椤斿啫鈹戦悩娈挎殰缂佽鲸娲熷畷鎴﹀箣閿曗偓绾惧綊鏌″搴″箹闁搞劌鍊块弻锝夊閵忊晝鍔哥紓浣哄Х婵炩偓闁哄瞼鍠栭弻鍥晝閳ь剟寮稿☉銏＄厱闁靛濡囩粻鐐烘煛鐏炲墽娲存い銏℃礋閹晠骞撻幒鎴經缂傚倷鑳堕崑鎾诲磿閹惰棄围闁归棿绀侀拑鐔兼煥濠靛棭妲哥紒鐘崇⊕閵囧嫰骞掗幋顓熜﹀┑鐐茬墕閻栫厧顫忓ú顏勫窛濠电偞甯╂禍婊堟偩閻戠瓔鏁嗛柛鏇樺妷閸嬫捇寮崼婵堫槰濡炪倖鏌ㄥΣ鍫ｎ樄闁哄本鐩崺鍕礃閻愵剛鏆ユ俊鐐€ら崑鍕洪鐑嗘綎闁惧繐婀遍惌娆撴煕閺嶃倕澧查柡浣瑰劤閳规垿鎮欑捄铏规闂佸摜濮撮柊锝夈€佸鑸垫櫜濠㈣泛锕ょ粣娑欑節閻㈤潧孝闁哥噥鍋婂畷婵嬪川鐎涙ǚ鎷洪梻鍌氱墛娓氭鎮炴ィ鍐╃厱閹兼番鍨归埢鏇㈡煙椤旀儳浜鹃柕鍫秮瀹曟﹢鍩為悙顒€顏圭紓鍌氬€搁崐鐑芥倿閿曚焦鎳屾俊鐐€戦崕鍗炍涘▎鎴炲床婵炴垯鍨瑰浠嬫煕閹板吀绨奸柛瀣斿嫮绡€闁靛骏缍嗗鎰箾閼碱剙鏋涙鐐村姈缁绘繈宕橀鍡楅獎婵犵數濞€濞佳兾涘☉姘辩煋婵炲樊浜濋悡娑樏归敐鍥ㄥ殌濠殿喖绉堕埀顒冾潐濞叉牠濡堕幖浣碘偓渚€寮撮姀鐙€娼婇梺鎸庣☉鐎氼厼鈻撻懜鐢电瘈闁汇垽娼у暩闂佽桨鐒﹂幃鍌氱暦閹存績妲堥柕蹇娾偓鍏呯綍闂備礁鎲″ú锕傚垂娴兼潙鍨傞柛灞绢嚔瑜版帗鍋愮€瑰壊鍠栭崜浼存⒑閽樺鏆熼柛鐘冲姉閹广垹鈽夐姀鐘殿吅闂佺粯鍔楅弫鎼佹偂閸岀偞鈷戞慨鐟版搐閳ь剚鍔欏畷鎴﹀箻缂佹ǚ鎷绘繛杈剧到閹诧繝骞嗛崼銉︾厱闁绘洑绀佹禍鎵偓瑙勬礃閸旀瑥鐣锋總绋垮嵆闁绘劙娼ф慨锔戒繆閻愵亜鈧牜鏁繝鍕焼濞达綀娅ｇ粻鏃傛喐韫囨洘顫曢柟鐑樻尰缂嶅洭鏌曟繛鍨姕閻犲洨鍋涢—鍐Χ閸愩劎浠鹃梺鑽ゅ暀閸パ呯枀闂佸湱铏庨崰鏍矆鐎ｎ偁浜滈柟鐑樺灥閳ь剙鎽滅槐鐐哄礃椤旇В鎷洪柣鐘叉处瑜板啴顢楅姀掳浜滈柡鍐ｅ亾闁绘濮撮悾閿嬪閺夋垵鍞ㄥ銈嗘尵閸犲孩绂嶉娑氱瘈闂傚牊绋戦埀顒佹倐楠炴顭ㄩ崘顏呮婵炴挻鍩冮崑鎾绘煙椤旂瓔娈滈柡浣瑰姈閹棃鍩勯崘顏勮拫闂傚倷娴囧銊х矆娴ｈ娲敇閵忕姾鎽曢梺鎸庣箓椤︻垳鐚惧澶嬬厓鐟滄粓宕滈悢鑲╁祦闁告劦鍠栭柋鍥煛閸モ晛浠ч柛鏃撶畱椤啴濡堕崱妤€娼戦梺绋款儐閹瑰洭寮诲☉銏″亜闁告稑锕︾粙鍥ь渻閵堝骸浜滅紒缁樺笧濡叉劙骞掗幊宕囧枛閹虫牠鍩￠崒姘杽闂傚倸鍊风欢姘跺焵椤掑倸浠滈柤娲诲灡閺呭爼顢欐慨鎰盎濡炪倖鎸鹃崑鐐电矚閹稿簺浜滈柨鏇楀亾缂傚秴锕獮鎰節閸屾鏂€闂佹悶鍎崕鎵姳婵犳碍鈷戦悷娆忓閸斻倗鈧娲﹂崜鐔煎箖濮椻偓閸╋繝宕橀鍜冪础闂備浇顕栭崹搴ㄥ礋椤愨剝妯婇梻鍌欑閹碱偊鎯夋總绋跨獥閹兼番鍔岄悡婵嬫煙閹规劦鍤欓柛銊ュ€归妵鍕籍閸屾稒鐝繛瀛樼矤娴滎亜顫忕紒妯诲閻熸瑥瀚禒鈺呮⒑閸涘﹥鐓ョ紒澶婄埣楠炴垿濮€閵堝懘鍞堕梺闈涱槶閸庢挳骞楅弴銏♀拺闁圭娴风粻鎾淬亜閿旇鐏﹂柨婵堝仱瀹曘劎鈧稒顭囬崢钘夆攽閳藉棗鐏犻柟纰卞亰瀵娊鏌嗗鍡欏幐闂佺硶鍓濋〃鍫熸櫠閿旇姤鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噰鐎规洜濞€閸ㄩ箖宕樺顔芥祮闂傚倸鍊峰ù鍥ь浖閵娧呯焼濞撴埃鍋撻柍銉畱閻ｏ繝鏌囬敃鈧▓銊︾節閻㈤潧校缁炬澘绉瑰鏌ュ箵閹烘繄鍞甸柣鐘烘〃鐠€锕傛偂椤掍胶绠鹃柣鎾冲嚱闊剚鎱ㄦ繝鍛仩缂佽鲸甯掕灒闊浄绲奸柇顖溾偓瑙勬磸閸庣敻宕洪埀顒併亜閹烘垵鈧崵澹曢崗绗轰簻闁哄洦顨呮禍鎯р攽閻愭澘灏冮柛銉岛閸嬫捇寮崼婵堫槰濡炪倖鏌ㄥΣ鍫ｎ樄闁哄本绋戦埥澶愬础閻愬吀鍖栨俊鐐€栭弻銊╂晝椤忓嫷娼栨繛宸簻娴肩娀鏌曟径鍫濆壘闁挎繂顦伴悡娆撴煕濞戞﹫宸ラ柛鏂诲€濆畷锟犳焼瀹ュ棛鍘甸梺缁橆殔閻楀﹦娆㈤懠顒傜＜闁绘ê鍟块埢鏇㈡煛瀹€鈧崰鏍嵁閸℃凹妾ㄩ梺鎼炲€楅崰鎾舵閹烘挸绶炲┑鐘插閻撶喎鈹戦纭锋敾婵＄偠妫勮灋闁告劦鐓佽ぐ鎺懳ч柛鈩冪懄閸掓盯鎮楃憴鍕８闁告梹鍨块妴浣糕槈濡攱顫嶅┑鐐叉閸ㄥ爼锝炲┑瀣拻闁稿本鑹鹃埀顒佹倐瀹曟劙骞栨担鍝ワ紮闂佺粯鍨兼慨銈夊吹閸曨垱鐓曟い鎰剁稻缁€鈧紓浣哄Х婵炩偓闁哄瞼鍠栭獮鎴﹀箛闂堟稒顔勯梺鐟板悑濞兼瑩鏁冮鍫濊摕闁挎稑瀚▽顏堟偣閸ャ劌绲诲┑顔肩埣濮婄儤娼幍顕呮М闁诲孩鍑归崜鐔煎灳閿曞倸閿ゆ俊銈勭濞堟繈姊婚崒姘卞缂佸鍨块敐鐐哄炊椤掍讲鎷洪梻渚囧亞閸嬫盯鎳熼鐐插偍闁告縿鍎崇壕濂告煃瑜滈崜姘辩箔閻旂厧鐒垫い鎺戝閺呮煡鏌ｉ幇顒佲枙闁绘挶鍎甸弻娑㈩敃閿濆洨鐣奸梺鍛婃缁犳垿鈥旈崘顔嘉ч柛鈩冾殘閻熴劑鏌ｆ惔銏犲毈闁告挻绋撻崚鎺撶節濮橆剙鍞ㄥ銈嗘尵閸犳捇宕㈤幘缁樷拺闁告稑锕︾粻鎾绘倵濮樼厧寮€规洖鍟跨叅妞ゅ繐鎳愰崢閬嶆煟鎼搭垳绁烽柛鏂挎湰閹便劑宕掗悙瀵稿幐閻庡厜鍋撻悗锝庡墰琚﹀┑鐘愁問閸犳帡宕戦幘缁樷拺闂傚牊绋撴晶鏇熶繆椤愶絿鎳囬柡灞诲姂椤㈡﹢濮€閿涘嫬骞楅梻渚€娼х换鍡涘疾濞戙垺鍊堕柣妯肩帛閸婂灚绻涢幋鐐茬瑲婵炲懎娲弻鐔肩嵁閸喚浠奸梺瀹狀潐閸ㄥ綊鍩€椤掑﹦绉甸柛瀣缁傛帒煤椤忓應鎷婚梺绋挎湰濮樸劍鏅跺☉姘辩＜閻庯綆鍋勬慨澶愭煕閹烘挸绗ч柟鐟板缁楃喖顢涘☉妯兼В闂傚倷绶氬褔鎮ч崱妞㈡稑鈻庨幇顒傜獮闂佸憡娲﹂崹閬嶆偂閺囩喍绻嗘い鏍ㄧ鐠愶繝鏌ｉ鐔烘噭妞ゃ劊鍎甸幃娆撴嚑椤掆偓閳灚绻濈喊妯哄⒉闁诡喖鍊垮畷娲焺閸愨晛顎撴繛鎾村嚬閸ㄤ即寮查鍕ㄦ斀闁挎稑瀚禍濂告煕婵犲啰澧い顐㈢箲缁绘繂顫濋鈧崑宥夋偡濠婂啰绠婚柟宕囧仱閺屽棗顓奸崨鍌樺姂閺屽秹宕崟顐熷亾閻㈢绠繛宸簼閳锋垿鏌涘☉姗堝姛缂佺姵鎹囬幃妤€顫濋悡搴ｄ桓闂佹寧绻勯崑銈夊极閸愵喖纾兼繛鎴炶壘楠炲牓姊洪悷鏉挎倯闁伙綆浜畷婵堚偓锝庡枛缁犵喎螖閿濆懎鏆為柣鎾寸懄閵囧嫰寮埀顒勫磿閾忣偆顩烽弶鍫氭杹閸嬫挾鎲撮崟顒傤槬缂傚倸绉撮敃顏堝Υ娓氣偓瀵挳濮€閳ュ厖姹楅梺鍝勵槸閻楀啴寮插┑鍡忔灃闁秆勵殕閳锋帡鏌涚仦鍓ф噮妞わ讣闄勭换婵嬪焵椤掑嫭鐒肩€广儱鎳愰敍鐔兼⒑闂堟稓澧曟い锔诲灦瀹曞綊宕掗悙瀵稿幗闂侀潧绻堥崺鍕倿妤ｅ啯鐓熼柟鐑樺灩娴犳盯鏌曢崶褍顏鐐村浮瀹曞崬顪冮幆褜妫滈梻鍌氬€烽懗鍫曘€佹繝鍐╁弿闁靛牆娲ら崹婵嬫煙閻愵剙澧柛銈嗘礃閵囧嫰骞囩捄铏规В闂佽桨绀侀澶愬蓟瀹ュ牜妾ㄩ梺鍛婃尰閻熲晠骞冮幆褏鏆嬮梺顓ㄥ閸欏棝姊洪崨濠冨闁告挻鐟╅、鎾诲箻缂佹ǚ鎷洪梺闈╁瘜閸樺墽鏁☉銏″仺妞ゆ牗鐔弨鑽ょ磼閺冨倸鏋涚€殿喗鎸抽幃娆撳煛閸屾稒婢戦梻鍌欒兌缁垶宕濆Ο闂寸剨婵炲棙鍔栧▍鐘绘煛閸ャ儱鐏柣鎾跺枛閻擃偊宕堕妸锔规嫽缂備胶濮烽崑鐔煎焵椤掍緡鍟忛柛鐘冲哺閳ワ箓宕奸妷銉у幒闁瑰吋鐣崝宀€绮婚敐澶嬬厽婵☆垳鈷堥弳婊呯磼閸楃偛绾уǎ鍥э躬閹瑩顢旈崟銊ヤ壕闁哄诞灞剧稁婵犵數濮甸懝楣冩偪閻愵兙浜滈柟鏉垮閻ｈ京绱掗悩闈涒枅闁哄本鐩俊鐑筋敊閹冨紬婵犵數鍋涢悧鍛垝濞嗘挸钃熼柨婵嗩槸缁犳稒銇勯弽鐢靛埌婵炲牊绻堝缁樼節鎼粹€斥拻闂佸憡鎸诲畝鎼佸Υ閸愵喖唯闁冲搫鍊搁埀顒傚厴瀵爼宕奸悢椋庮槰闂侀€炲苯澧叉繛澶嬫礋閸┾偓妞ゆ帊绶￠崯蹇涙煕閻樺啿鍝虹€殿噮鍋嗛幏鐘绘嚑椤掍焦顔曢柣鐔哥矌婢ф鏁埡鍛瀬闁告劦鍠楅悡蹇涚叓閸ャ劍绀€妞ゅ骸鐭傞弻宥堫檨闁告挻鐟ч幑銏犖熸笟顖涚稁婵犵數濮甸懝鍓у閸忚偐绠鹃柛鈩兠粭鎺楁煕濮楀牏纾跨紒杈ㄦ尰缁楃喖宕惰閻濐噣姊洪幖鐐插婵炲鐩幃鎯х暋閹佃櫕鏂€闁诲函缍嗛崑鍛枍閸ヮ剚鈷戠紒瀣濠€鐗堟叏濡濮傞挊婵囥亜閹捐泛浜归柡鈧禒瀣厽闁归偊鍘界紞鎴︽煟韫囨洖鏋涢柡灞剧洴婵℃悂濡烽敃浣侯攨缂傚倷绶￠崰鏍偋閹惧磭鏆﹂柣鏃傗拡閺佸秵绻涢幋鐐跺妤犵偞锕㈠缁樻媴缁涘娈愰梺鍛婎焽閺咁偊寮鈧獮鎺懳旈埀顒傜矆婢跺绠鹃柛鈩兠悘鈺冪棯閹佸仮闁诡喖缍婂畷鎯邦槻缂佺嫏鍕╀簻闁靛绲介悘鏌ユ煛瀹€瀣？濞寸媴绠撻幃娆擃敆閸屻倖效闂佽姘﹂～澶娒哄鍫濆偍鐟滄棃宕洪悙鍝勭闁挎洍鍋撻柣鎰功閹插憡鎯旈…鎴炴櫆闂佺粯顭囩划顖炲煕閹烘垯鈧帒顫濋敐鍛闂備線鈧偛鑻晶浼存煕鐎ｎ偆娲撮柟宕囧枛椤㈡稑鈽夊▎鎰娇闂備胶绮〃鍛存偋閸曨剛顩叉繝濠傜墛閻撳繘鐓崶銊︾妞ゅ孩鎸搁～妤咁敃閿濆懎鎽甸梺鍝勬湰濞茬喎鐣烽崼鏇炍╅柕澶堝労濞兼岸姊绘担绛嬪殐闁哥姵甯″鎻掆攽閸噥娼熼梺鍦劋閸わ箓鎮㈤崗鑲╁弳闁诲函缍嗘禍鑸靛?")
        else:
            lines.append("闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙绐涢梺鍝ュУ閹稿墽鍒掔紒妯稿亝闁告劏鏅濋崢浠嬫⒑闁稑宓嗘繛浣冲嫭娅犳い鏍仦閻撶喐绻濋棃娑欏缂佲偓鐎ｎ偅鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噧闁宠閰ｉ獮鍡氼槻濠㈣锚閳规垿鎮欓懠顒佹喖缂備緡鍠氭慨鐢电矉瀹ュ鏁傞柛鏇㈡涧濞堛劑鏌ｉ悩鍙夊缂佷焦娼欏嵄闁割偁鍎查悡蹇涚叓閸ャ劍绀€閸熸悂姊洪崨濠冣拹闁圭鍟块～蹇撁洪鍕獩婵犵數濮撮崐姝岊杺婵犵數鍋涢悺銊у垝瀹ュ鍋嬮柡鍥╁仜缁侇偊姊绘担绋款棌闁稿绶氬畷褰掓嚒閵堝拋妫滈梺鑺ッˉ銏ｃ亹閹烘挻娅滈梺绯曞墲椤ㄥ牏绮婇柨瀣閻庢稒顭囬惌鎺旂磼閻樺磭澧い顐㈢箻閹煎綊宕烽鐘靛幆闂佽崵濮垫禍浠嬪礉鎼淬垹顕遍柛銉墯閳锋垹绱掔€ｎ偒鍎ラ柛搴㈠灴閺屾稓鈧絻鍔岄埀顒佺箞閻涱噣宕橀鑺ユ闂佺粯蓱瑜板啫鐣甸崱娑欌拺缂備焦蓱閳锋帞绱掔紒妯肩畼闁奸缚椴哥换婵嗩潩椤撴稒瀚奸梺鑽ゅ枑閻熴儳鈧凹鍘惧▎銏ゅ箵閹烘繄鍞甸悷婊冪Ч閺屽﹪鏁愭径灞界ウ闂佸憡鍔﹂崰妤呭吹閸愵喗鐓冮柛婵嗗閺嗙喖鏌ㄥ☉娆戠煉婵﹨娅ｇ槐鎺懳熻箛锝勭敖濠㈣娲熼、姗€鎮㈤崨濠勫娇闂備焦鐪归崹褰掑箟閿熺姵鍋傛繛鎴欏灪閸婂爼鏌ｉ幇顓炵祷闁抽攱妫冮弻宥夘敍濞戞瑧顦紓浣介哺鐢偟妲愰幒鎳崇喖鎳栭埡鍐╂緰闂佽姘﹂～澶娒哄鈧弫鍐閵堝啠鍋撴笟鈧顕€宕煎┑鍫Ч闂備線娼ч…顓犵不閹达富鏁傛い鏍ㄧ〒缁♀偓闂佹眹鍨藉褎鐗庢俊鐐€栧褰掓偋閻樿尙鏆﹀ù鍏兼綑閸愨偓濡炪倖鎸鹃崰鎰枍閸ヮ剚鈷戦梻鍫熶緱濡插爼鏌涙惔鈩冩儓闁靛棙甯為幏鐘垫啑娴ｅ摜绉洪柟顔规櫅椤斿繘顢欓悡搴☆棄闂傚倷绶氶埀顒傚仜閼活垶宕㈤崫銉х＜闁奸晲绲绘竟妯汇亜閺囶亞绉鐐达耿椤㈡瑧鍠婃潏銊хП闂傚倷鑳剁划顖炴偡閵忋倕纾婚柟鎯ь嚟缁犻箖鏌ｉ幘鍐插毐闂婎剦鍓氶幈銊︾節閸愨斂浠㈠┑鈽嗗亜閸燁偊鍩ユ径濠庢僵閺夊牃鏅滃鏍⒒閸屾瑨鍏岀痪顓炵埣瀵彃鈽夊锝呬壕婵﹩鍘界欢鏌ユ煟閿濆洤鍘存い銏☆殜瀹曟﹢鏁傞幐搴ｆ綎闂傚倷绀佸﹢閬嶅磿閵堝绠伴柟缁㈠枛缁狀垳绱撴担璇＄劷缂佺娀绠栧鍫曞醇濠靛棌鎸冮梺鍛婂笂閸楁娊寮婚悢鐑樺珰鐟滃繒寮ч埀顒€螖閻橀潧浠滄俊顐ｇ箓閻ｉ攱绺界粙璇俱劑鏌ㄩ弮鈧崕鎶界嵁濡や椒绻嗛柣鎰典簻閳ь剚鐗曢蹇旂節濮橆剛锛涢梺鐟板⒔缁垶鎮¤箛娑欑厱妞ゆ劗濮撮悞娲煟閹烘鐣洪柡宀嬬秮閺佹劖寰勭€ｎ偅娈搁梺璇查叄濞佳囧Χ缁嬫鍤曢柛顐ｆ礀缁狅絾绻濋棃娑欘棡闁哄棗绻樺娲嚒閵堝懏鐎剧紓渚囧枛閻ジ骞戦姀鐘栫喐绗熼姘吙闂備浇顫夐崕鍏兼叏閵堝鐤炬繝闈涱儐閻撴洟鎮橀悙鎻掆挃闁靛棙甯￠弻娑橆潨閸℃洜鍑圭紓浣虹帛缁诲牊鎱ㄩ埀顒勬煥濠靛棙顥犻柕鍡樺姇閳规垿鍩ラ崱妞剧凹闂佽崵鍠嗛崕鐢稿春閵忕媭鍚嬪璺猴工缁愭稑顪冮妶鍡欏缂侇喖閰ｉ弫宥咁煥閸啿鎷虹紓鍌欑劍椤洭骞婇崘顔界厵闁惧浚鍋勬慨澶岀磼椤旂晫鎳囬柟绛圭節婵″爼宕堕埡瀣簥缂傚倸鍊搁崐鐑芥倿閿曞倵鈧箓宕堕埡鍐х瑝闂佺粯鍔楃换婵堟崲閸℃ǜ浜滈柟鎵虫櫅閻忊晠鏌￠崱妯兼噰闁哄苯绉归幐濠冨緞濡亶锕傛⒑鐎圭媭鍤欓梺甯秮閻涱噣宕堕澶嬫櫍闂佺粯鍔忛弲娑欑妤ｅ啯鈷戦柛顭戝櫘閸庡海绱掔拠鍙夘棦闁哄矉缍侀獮鍥礂閸濄儳娉块梻渚€鈧偛鑻晶顖涚箾閸欏澧垫繝鈧担绯曟斀妞ゆ梻鐡旈悞鐐箾婢跺娲寸€规洖缍婂畷鎺楁倷閺夋垳鍖栭梺鍝勵槺閸嬬偞鍒婃禒瀣垫晢闁绘柨鎽滅粻楣冩煕韫囨艾浜瑰褜鍓涚槐鎺旂磼濡皷妲堝銈嗘煥缁绘﹢銆佸▎鎾村殥闁靛牆娲﹂弲銊╂⒑鐠囧弶鎹ｉ柟铏崌楠炲鏁嶉崟顒€搴婇梺绋跨灱閸嬫盯鎮″鈧弻鐔告綇妤ｅ啯顎嶉梺绋款儐閸旀瑩寮婚悢铏圭＜婵☆垰鎼鎴︽⒑缁嬫鍎愰柟姝屽吹閹广垹鈹戦崱鈺傚兊闂佺绻愰崥瀣枍閸℃せ鏀介柣妯虹仛閺嗏晛鈹戦鐐毄闁哥姴锕ら鍏煎緞婵犲嫬骞堥梻浣烘嚀椤曨厽鎱ㄦ搴☆棜濠靛倸鎲￠崐鐢告煥濠靛棛鍑圭紒銊ヮ煼閺岋綁鈥﹂幒鏃傜槇闂佸搫鐭夌换婵嬪春閳ь剚銇勯幒宥堝厡缂佲檧鍋撴繝娈垮枟閿曗晠宕㈡ィ鍐ㄥ偍闁芥ê顦弨浠嬪箳閹惰棄纾归柡鍥ュ灩閻ゎ喗銇勯幇鈺佺伄闁瑰鍎遍埞鎴︽晬閸曨偂鏉梺绋匡攻閻楁洜鍙呴梺鍐叉惈閸燁偆娆㈤妶澶嬬厱闁圭偓顨呯€氼剚鎯旀繝鍌楁斀闁绘绮☉褎淇婇顐㈠箹妞ゎ厼娲崺锟犲磼濡湱鐩庨梻浣告贡閸庛倝宕归悽绋跨劦妞ゆ帊鐒﹂崐鎰版煕閳规儳浜炬俊鐐€栫敮鎺楀磹閸涘﹦顩锋繝濠傚娴滄粍銇勮箛鎾愁仼闁哄棴绲介埞鎴﹀灳瀹曞洤鐓熼悗瑙勬礀瀹曨剝鐏冮梺閫炲苯澧い顓炴喘楠炲鏁傜憴锝嗗缂傚倷绀侀鍡涱敄濞嗘挸纾块柟鎵閻撴瑩鏌ｉ悢鍝勵暭闁哥姵顭囬埀顒侇問閸犳盯顢氳閸┿儲寰勯幇顒夋綂闂佺粯顭囬弫鎼佸级閹间焦鈷掑〒姘ｅ亾婵炰匠鍥ｂ偓锕傚醇閵夈儳锛熼梺缁橆殔閻楀繘鎮甸崼鏇熺厸闁搞儯鍎遍悘顏堟煃闁垮娴柡灞剧〒娴狅箓骞戦幇顒夋闂備線鈧偛鑻晶浼存煕韫囨棑鑰挎鐐插暣閹瑩鎮滃Ο缁樼彇闂備胶顭堥張顒€顫濋妸鈺傚仼婵炲樊浜濋埛鎴︽煕閹炬潙绲诲ù婊勭箖缁绘盯宕ｆ径灞解拡婵犮垼顫夊ú鐔肩嵁閹邦厽鍎熼柨婵嗘川濡插洤鈹戦悩鍨毄濠殿喗鎸冲畷鎰磼濡粯鐝烽梺鍝勬川婵澹曟總鍛婄厓鐟滄粓宕滈悢椋庢殾婵せ鍋撴い銏＄懇閹墽浠﹂挊澶岀懖闂傚倸鍊风粈渚€骞夐敍鍕床闁稿本澹曢崑鎾愁潩閻撳骸鈷嬮悗娈垮枛閸熷潡鍩㈡惔銊ョ闁哄鍨抽崠鏍р攽閻愯埖褰х紒鑼舵閿曘垽鏌嗗鍛厬闂侀€炲苯澧柍瑙勫灴椤㈡瑧娑靛畡棰佺矗婵＄偑鍊ら崢濂稿床閺屻儲鍋╅柣鎴ｆ缁犳娊鏌熺€涙ɑ鈷愰柣搴☆煼濮婃椽鎮烽幍顔芥喖缂備浇顕ч崐鍧楀灳閺嶃劌绶為柟閭﹀幐閹锋椽鏌ｉ悩鍙夋悙鐎殿喖鐖奸獮鎴︽晲婢跺鍘介梺缁樻⒒椤牓鍩㈤弴鐘亾鐟欏嫭纾搁柛鏃€鍨块妴浣糕槈濮楀棛鍙嗛梺鍛婁緱閸樿偐绮诲鑸碘拻闁稿本鑹鹃埀顒傚厴閹虫宕奸弴妯峰亾娴ｅ湱绡€闁搞儜鍜佸斀婵＄偑鍊曠换鎰版偋婵犲洤鐓曢柡鍐ㄧ墛閻撴洟鏌￠崶銉ュ闁诲繒濮烽惀顏堟倷椤掆偓椤曟粌菐閸パ嶈含濠碘€崇埣瀹曘劑顢欓崗纰变画闂傚倷鑳剁划顖炲箰鐠囪娲偄閻撳海鐣哄┑顔姐仜閸嬫捇鏌熼鐣屾噰鐎殿喖鐖奸獮瀣攽閸犵増鍨垮缁樻媴閻戞ê娈岄梺鍛婅壘椤戝鐛崘顔肩＜闁绘劘灏幗鏇㈡倵楠炲灝鍔氶柣妤佺矊椤﹪濡搁埡鍌楁嫼闂佸憡绋戦敃銉т焊閻楀牊鍙忔俊顖滎焾婵倻鈧鍣崑濠囥€佸璺虹劦妞ゆ帒瀚崹鍌炴煙椤栧棗鎳忓▓楣冩⒑閹肩偛鍔橀柛鏂跨Ч椤㈡瑩寮撮悢铏圭槇闂佹眹鍨藉褍鐡梻浣瑰濞插繘宕愬Δ鍛劦妞ゆ帊绀侀崵顒勬煕濡湱鐭欑€规洘纰嶇换婵嬪炊瑜忛鎺戭渻閵堝棙鈷掗柡鍜佸亰瀹曘垺绂掔€ｎ偀鎷虹紓鍌欑劍钃遍柣鎾卞劦閺岀喓鍠婇崡鐐板枈闂侀潧妫楅崐鍨暦濡ゅ懎绀傞柣鎾抽娴煎酣姊绘担鐟邦嚋缂佽鍊块獮濠呯疀濞戞顔愰梺瑙勫婢ф鎮￠崘顔藉仭婵炲棗绻愰鈺呮煟韫囨梹灏﹂柡宀€鍠栭、娆撴偩鐏炴儳娅氶梻浣侯攰濞呮洜鍒掗幘婢勬盯宕橀妸銏☆潔濠电偛妫欓幐濠氬汲濡偐纾介柛灞捐壘閳ь剚鎮傚畷鎰板箹娴ｅ摜锛欓梺鍛婄缚閸庢娊鎯岄幘娣簻闁哄洦顨呮禍楣冩倵鐟欏嫭绀冮柛銊ユ健閻涱喖顫滈埀顒勭嵁閸ャ劍濯撮柣鐔稿濡诧綁姊婚崒娆戠獢婵炰匠鍥ㄥ亱闁糕剝锕╁▓浠嬫煕濞戞﹫鍔熸い鈺佸级缁绘繃绻濋崒姘间淮婵炲瓨绮嶇划鎾诲蓟閵娾晛绫嶉柛銉ｅ妿閵嗗﹦绱撴担椋庣獢闁衡偓鏉堛劎鈹嶅┑鐘叉祩閺佸啴鏌曢崼婵囧櫤闁诲繐鐗撳铏规嫚閳ヨ櫕鐏堥梺鎼炲灪閻擄繝鍨鹃敃鍌毼╅柍杞拌兌椤︽澘顪冮妶鍡楃瑨妞わ缚鍗宠棢闁割偁鍎查悡鐔煎箹濞ｎ剙鐒洪柛鐔风箻閺屾盯鎮╁畷鍥р拰闂佺偨鍎荤粻鎾诲箖濠婂牊瀵犲璺虹灱閺嗩偊姊绘笟鈧褏鎹㈤崼銉ュ瀭婵炲樊浜滅壕缁樻叏濡炶浜鹃梺鍝勮嫰缁夎淇婇悜钘壩ㄩ柕澶堝劤椤戝牆鈹戦悩顔肩伇妞ゎ偄顦叅闁哄稁鍘奸悡姗€鏌熸潏楣冩闁稿﹦鍏橀弻鈩冨緞鐎ｎ亞浠兼繛瀵稿Х椤牓鈥旈崘顔嘉ч柛娑卞枤椤╃増绻涚€涙鐭ゅù婊庝邯婵″瓨绗熼埀顒€顕ｉ鈧畷鐓庘攽鐎ｎ亝鏆梻鍌欒兌缁垶寮婚妸鈺傚剭婵犻潧顑呯壕濠氭煙閹规劦鍤欓梺鍗炴喘閺岋繝宕堕埡浣圭亖闂佸憡锕╂禍婵堟崲濠靛顫呴柨婵嗘閵嗘劕鈹戦埥鍡椾簼闁荤喆鍎甸崺銏狀吋婢跺﹤鑰垮┑鐐村灦閻熝囧储娴犲鈷戦悷娆忓閸斻倝鏌ｆ幊閸斿海鍒掗崼鈶╁亾閿濆骸鏋熼柣鎾寸〒閳ь剙鍘滈崑鎾绘倵閿濆骸澧扮悮锕傛煟鎼淬埄鍟忛柛锝庡櫍瀹曟娊鏁愭径濠冩К闂侀€炲苯澧柕鍥у楠炴帡骞嬪┑鍥吘濠电偛鐡ㄧ划宀€绱炴繝鍥ц摕婵炴垯鍨圭粻娑㈡煏婵犲繘妾柣婵囩墪椤啴濡堕崒娑欑彆闂佺粯鎼换婵嗩嚕鐠囨祴妲堥柕蹇曞Х椤旀帒鈹戞幊閸婃劙宕戦幘缁樼厵闁惧浚鍋勬慨宥夋煛娴ｅ摜孝闁宠鍨归埀顒婄秵閸嬧偓闁圭柉娅ｇ槐鎾存媴閸撴彃鍓遍柣搴ｇ懗閸愯儻鈧灝霉閻撳海鎽犻柣鎾跺Х閹叉悂鎮ч崼婵堫儌闂佷紮绲惧浠嬪蓟濞戙垹鐓橀柟顖嗗倸顥氭繝纰夌磿閸嬫垿宕愰弽顐ｆ殰闁圭儤鏌￠崑鎾愁潩椤掆偓濡插鎽堕悙鐑樼厵閻庣數顭堝暩缂佺偓鍎抽妶绋款嚕閸洖閱囨慨姗嗗幗閻濇梹绻涚€电鈻堝ù婊冪埣瀵鈽夐姀鐘靛幋闂佽鍨庨崒姘兼濠电姷顣槐鏇㈠磻閹达箑纾归柡宥庡亝閺嗘粓鏌熼悜妯荤厸闁稿鎸搁～婵嬫偂鎼达紕鐫勯梻浣筋嚃閸ｎ垳鎹㈠┑鍡╁殨闁圭虎鍠楅崑鍕煣韫囨凹鍤冮柛鐔烽叄濮婄粯鎷呴悜妯烘畬闂佸鏉垮闁瑰箍鍨藉畷鎺楁倷閺夋垶鐤傞柣鐔哥矌婢ф鏁Δ鍛亗闁绘棁鍋愰崣鎾绘煕閵夛絽鍔氶柛鏂诲€楃槐鎺楀煢閳ь剟宕戦幘缁樷拻濞达絽鎲￠幆鍫ユ煟椤撶儐妲洪柟骞垮灩閳规垿宕卞▎鎰啎闂傚倷绶￠崜娆戠矓閹绢喖纭€闁规儼濮ら悡鐔兼煙闁箑鐏犻柣銊︽そ閺屾洟宕奸銏＄亶缂備胶绮换鍌炲煝閹捐鍨傛い鏃傛櫕娴滎亪姊绘担鐟邦嚋婵炴彃绻樺畷婵嗙暆閸曨偆鍘洪悗骞垮劚椤︿即寮查弻銉︾厱婵炴垵褰夌花鍏笺亜椤愩垻效婵﹤鎼晥闁搞儜鍛磿婵＄偑鍊ら崢濂告偋閸℃侗鏁婇煫鍥ㄦ尨閺€浠嬫煕閵夛絽鍔欑紒銊ヮ煼濮婃椽宕崟顐熷亾瑜版帒纾跨€规洖娲犻崑鎾愁潩椤掑嫬寮伴梺鍝勮嫰缁夌兘篓娓氣偓閺屾盯骞橀弶鎴濇懙閻庤娲樼换鍌炲煝鎼淬倗鐤€闁挎繂妫涚粙浣圭節閻㈤潧浠滄俊顖氾攻缁傚秴顭ㄩ崨顖欑瑝婵炴潙鍚嬪娆戠不鐟欏嫮绠鹃柨婵嗛婢ь噣鏌ｈ箛锝呮珝闁哄被鍔岄埥澶娾枎濞嗘巻鍋撻幐搴㈠弿濠电姴鎳忛鐘电磼椤旂晫鎳囩€规洜濞€閸╁嫰宕橀埡鍌涚槥缂傚倸鍊搁崐宄懊归崶顒夋晪鐟滄棃骞冭楠炴绱掑Ο杞扮钵婵＄偑鍊栧ú宥夊磻閹惧灈鍋撶憴鍕闁挎洏鍨介妴浣糕枎閹邦噣妾梺鍛婄☉閿曘儱鈻撻弬搴撴斀闁绘灏欏Λ鍕煛婢跺﹦姘ㄩ柛瀣崌楠炲洭寮剁捄顭掔幢闂備浇顫夐崕铏櫠鎼达絽顥氬┑鍌氭啞閻撳啰鎲稿鍫濈婵炴垯鍨归悞鍨亜閹烘埊鍔熺紒澶屾暬閺屾稓鈧絺鏅濋崝宥囩磼閸屾氨孝妞ゎ厹鍔戝畷濂告偄閸濆嫬绠伴梺璇查缁犲秹宕曢柆宥呯柈妞ゆ劧绲肩换鍡涙煕瑜庨〃鍡涙偂閸愵喗鐓㈡俊顖欒濡牊淇婇崣澶嬪€愭俊顐＄劍瀵板嫰骞囬鐘插箺婵犳鍠楅〃鍛涘Δ鍛嚑婵炴垯鍨洪悡鐔肩叓閸ャ劍灏紒鐙欏洦鐓欏〒姘仢婵＄晫绱掔紒妯肩疄鐎规洘锕㈤崺鐐村緞濮濆本顎楅梻浣筋嚙濮橈箓锝炴径濞掓椽鏁冮崒姘憋紱婵犵數濮撮崐濠氬汲閿曞倹鐓熼柡鍐ㄥ€哥敮鍫曟煕閵娿儱鈧綊濡甸崟顖氱疀妞ゆ帒鍊甸弸鍡樼箾鐎涙鐭嬬紒顔芥崌瀹曟椽鎮欓崫鍕吅闂佹寧妫佸Λ鍕焵椤掑嫷妫戦柍褜鍓涢幊鎾寸珶婵犲洤绐楁俊銈勭劍濞呭繑绻濋悽闈浶ラ柡浣规倐瀹曟垵鈽夊鍡楁闂佸壊鍋呭ú姗€宕戠€ｎ喗鐓熸俊顖涱儥閸ゆ瑩鏌ｈ箛鏂库枙闁哄被鍔戝鎾倷濞村浜鹃柟闂寸劍閸婂嘲鈹戦悩鎻掓殧濞存粍绮撻弻鐔煎传閸曨剦妫炴繛瀛樼矊婢х晫妲愰幘瀵哥懝闁搞儜鍌滅泿缂傚倷绀侀ˇ顖滅礊婵犲偆鍤曢悹鍥ㄧゴ濡插牊鎱ㄥ鍡椾簼闁告洖鍟扮槐鎾诲磼濞嗘挻顎栭梺鎼炲妽濡炰粙骞冩ィ鍐╁殝闁汇垻鏁搁鏇㈡煟鎼淬垻鈯曟い顓炴喘閹苯鐣濋崟顒傚幈闁诲函缍嗛崑鍛焊閻㈠憡鐓欐鐐茬仢閻忊晠鏌嶉挊澶樻█濠殿喒鍋撻梺缁橆焾椤曆囧极鐟欏嫮绡€闁汇垽娼ч埢鍫熺箾娴ｅ啿娲﹂崑瀣煕濞戞鎽犻柟顖滃仱楠炴牕菐椤掆偓婵′粙鏌嶉柨瀣伌闁哄本绋戦埞鎴﹀幢濡ゅ﹣绱濋梻浣侯焾鐎涒晠宕濆▎鎾宠摕闁绘柨鍚嬮崑锟犳煟濡も偓閻楀棝寮搁悩缁樺€垫繛鍫濈仢閺嬶附銇勯弴鍡楁搐閻撯€愁熆鐠轰警鐓繛灏栨櫊閺屻劌鈹戦崱妯烘婵犮垼顫夊ú鐔奉潖濞差亜绠伴幖杈剧悼閻ｅ灚淇婇妶鍥㈤柟璇х磿缁顓奸崨顏呮杸闂佸壊鍋呴懝鐐妤ｅ啯鍋℃繛鍡楃箰椤忣亞绱掗埀顒勫焵椤掑嫭鈷戞繛鑼额嚙楠炴牠鏌涙繝鍌滀虎妞?")
        if tone_name == "concise_rescue":
            lines.append("濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ゆい顓犲厴瀵鏁愰崨鍌滃枎閳诲酣骞嗚椤斿嫮绱撻崒娆掑厡濠殿喗鎸抽幃妯侯潩鐠轰綍锕傛煕閺囥劌鏋ら柣銈傚亾闂備礁婀遍崑鎾诲箚鐏炶娇娑㈡倷閻㈢數锛濇繛杈剧悼閺咁偊宕奸鍫熺厱濠电姴鍟扮粻鐐碘偓娈垮枛椤兘骞冮姀銈嗘優闁革富鍘鹃崢顖炴⒒娴ｇ顥忛柣鎾崇墦瀹曟娊顢氶埀顒€鐣峰┑鍥х窞闁归偊鍘搁幏娲⒑閸涘﹦鈽夐柨鏇畵楠炲﹪宕橀鍡欙紲缂傚倷鐒﹂敃顐︽嚀鐠恒劉鍋撳▓鍨灈妞ゎ厾鍏樺顐﹀箛椤撶偟绐炴繝鐢靛Т鐎氱兘宕ラ崨瀛樷拻濞达綀娅ｇ敮娑欍亜椤撶偟澧曢柍璇茬Ч瀵挳濮€閳ュ厖鎴锋俊鐐€曠换鎰版偋婵犲洤纾归柣銏犳啞閸嬧剝绻涢崱妤冪妞ゅ浚浜幃妯跨疀閿濆懍绨界紓浣介哺鐢繝骞婂鍫燁棃婵炴垶蓱閹虫瑩鏌ｆ惔銏╁晱闁哥姵鐩、姘愁樄闁糕斂鍎插鍕箛椤掑缍傞梻浣虹帛钃遍柣妤佹崌瀹曟繂顓兼径濞箓鏌涢弴銊ョ仩缂侇偄绉归弻娑氫沪閹规劕顥濇繛瀵稿У閿氭い顏勫暣婵¤埖鎯旈垾鑼埍闂備礁鎼幊鎰叏閹绢噯缍栭煫鍥ㄦ媼濞差亶鏁傞柛鏇ㄥ墮缁佽埖淇婇悙顏勨偓鏍箰妤ｅ啫绐楅幖绮规閺嬫梻鈧厜鍋撻柛鏇ㄥ厴閹疯櫣绱撻崒娆戝妽妞ゎ厼娲﹂弲鍫曨敂閸喓鍘梺鍓插亖閸╁嫰鎮為悙顑句簻闁哄浂浜炵粙鑽ょ磼缂佹绠撴い顐ｇ箞椤㈡鍩€椤掆偓閻ｇ敻宕卞☉娆屾嫼缂傚倷鐒﹁摫妞ゃ儱妫欑换娑㈠椽閸愵亞袦闂佽鍨欢姘暦婵傜唯闁挎梻绮ˉ濠冧繆閻愵亜鈧牠宕濋幋锕€鍨傞柣鎴灻欢鐐烘煕閺囥劌骞樼痪鎯с偢閹鏁愭惔鈥茬盎濠电偞鎯岄崰妤呭Φ閸曨垰顫呴柍鈺佸暙绾板秴顪冮妶鍡樺碍闁靛牏顭堥悾鐑藉础閻愨晜鐎婚梺瑙勬儗閸樺ジ寮查銏♀拻濞达絿鐡旈崵娆愮箾鐎电鍘寸€殿噮鍋婇獮鏍ㄦ媴濞村浜鹃柨鏇炲€搁柋鍥煟閺傛寧鎯堥柍顏冨嵆濮婂宕掑顑藉亾閻戣姤鍊块柨鏃堟暜閸嬫挾绮☉妯哄箻濡わ箒娉曢悿鈧┑鐐村灦閿氶柣搴弮閹嘲顭ㄩ崨顓ф毉闁汇埄鍨兼禍鐐垫閻愬搫鍐€妞ゆ挾濮磋ぐ鍕⒑閹肩偛鍔橀柛鏂跨Ч閸╂盯骞掗弮鍌滐紲闂佹娊鏁崑鎾绘煕鐎ｎ偅灏扮紒缁樼箓閳绘捇宕归鐣屼憾闂備焦瀵уú宥夊疾閻樿尙鏆︽繝濠傚暊濡插牓鏌曡箛鏇炐ラ柨娑欑懇濮婅櫣绱掑Ο鍝勵潕闂佺绨洪崐婵嬪春濞戙垹绠ｉ柨鏃傛櫕閸樼數绱撴担鍓插剱閻庣瑳鍥х闁挎繂娲ㄧ壕濂告煟濡寧鐝€规洖鐭傞弻鈥崇暆閳ь剟宕伴弽褏鏆︽慨妞诲亾闁瑰磭濞€椤㈡牠顢曢鍌涘仹缂備浇椴哥敮鈥愁嚕椤曗偓瀹曟帒顫濋鐘遍偗闂佽瀛╅鏍窗濡ゅ懎绠伴柧蹇ｅ亝閸欏繘鏌嶈閸撶喖寮诲澶嬬叆妞ゆ牗鐭竟鏇㈡⒒娴ｅ摜绉洪柡鈧崡鐑嗘富闁芥ê顦藉鏍ㄧ箾瀹割喕绨奸柛瀣€块獮鏍箹椤撶偞鐏嶇紓鍌氱У椤ㄥ﹤顫忛搹鍦煓闁告牑鍓濋弫鎯р攽閻愯泛鐨洪柛鐘查叄椤㈡岸鏁愭径濠勵啇婵炶揪绲介幗婊堫敇濞差亝鈷戠紓浣姑慨澶愭煛娴ｈ鍊愭い銏＄懇瀵挳濮€閳锯偓閹锋椽姊洪崨濠勨槈闁挎洩绠撻獮濠囧礃閳瑰じ绨婚梺鎸庢椤曆囨倶閿曞倹鐓欐い鏃€鏋婚懓鎸庮殽閻愯揪鑰挎い銏＄懇閹墽浠﹂挊澶岊吋闂傚倸鍊烽悞锕傚磿閸愯鐟邦潩鐠鸿櫣锛涢梺鍦劋閸ㄧ喖寮搁弮鈧幈銊ヮ渻鐠囪弓澹曢梻浣告惈閻ジ宕伴弽顓炵畺闁绘垼妫勭痪褎绻涢崱妤€缍栫紒杈ㄥ灴濮婄粯鎷呯粵瀣異闂佸摜濮靛ú鐔风暦閿熺姴绠柦妯侯槹濡差剟姊洪崨濠冨闁搞劍澹嗙划鍫ュ礃閳瑰じ绨婚棅顐㈡处閹告悂寮抽悢鍏肩厵缂佸顑欏Ο鈧┑顔硷工椤嘲鐣烽幒鎴僵妞ゆ垼妫勬禍楣冩煟閹达絽袚闁搞倕瀚伴弻娑㈩敃閿濆棛顦ョ紓浣哄Х婵炩偓闁哄瞼鍠栭幃娆擃敆娴ｅ吀鎴烽梻浣芥〃缁€渚€顢栭崱娑樜﹂柛鏇ㄥ灠缁犲鏌涘Δ鍐ㄤ户濞寸姾鍋愮槐鎺楁倷椤掆偓閸斻倖銇勯鐘插幋鐎殿喖顭烽弫鎰緞婵犲嫮娼夐梻浣侯焾閺堫剟鎳濋悙顒傤浄婵せ鍋撴慨濠呮缁辨帒螣鐠囨煡鐎虹紓鍌欐祰椤曆囨偋閹炬剚鍤曞┑鐘崇閺呮悂鏌ｅΟ鍨毢妞わ负鍔戝娲濞戣京鍔搁梺绋垮瘨閸ｏ絽鐣烽幋锕€绠荤紓浣姑禒铏圭磽娴ｅ壊鍎撴繛澶嬫礋閺佸秴鈽夐姀鈾€鎷洪柣鐔哥懃鐎氼剛绮堥崘顏佸亾鐟欏嫭绀嬫繛浣冲洦鍋╅柛顭戝亞閻熷綊鏌嶈閸撶喎顕ｇ拠娴嬫闁冲灈鏂侀崑鎾绘晝閸屾氨顓哄┑鐘绘涧濞层劍绂嶉鍕ㄦ斀闁绘ɑ鍓氶崯蹇涙煕閻樺磭澧い銊ｅ劦楠炴牗鎷呴崫銉ュ箣闂備胶顢婇幓顏嗙不閹达附鍋傞柨鐔哄У閻撴洟鏌嶉埡浣告殧濞寸媴濡囩槐鎺楀Ω閵夛絽浠┑顔硷攻濡炰粙骞婇敓鐘参ч柛娑卞枟閻ｎ剟姊绘担瑙勫仩闁稿寒鍨跺畷婵堜沪閸撗屾祫濡炪倖鎸堕崹娲磻閳╁啰绡€濠电姴鍊搁顏堟煟閹惧崬鍔滈柕鍥у椤㈡洟濮€閵忋埄鍞虹紓鍌欐祰妞村摜鏁幒鏇犱航闂佽崵濮村ú銈呂熸繝鍥х劦妞ゆ帊鐒﹀畷灞炬叏婵犲啯銇濈€规洏鍔嶇换婵嬪礋閵婏富娼旈梻鍌欑劍鐎笛兠鸿箛娑樼？闂傚牊绋撻弳锕傛煛閸ャ儱鐏╃紒鐘差煼閺岋繝宕掑Ο鍝勫闂佸搫鍊甸崑鎾绘⒒閸屾瑨鍏岀紒顕呭灦瀹曟繂鈻庨幘鈧悜钘夌＜闁绘劖褰冮幆鐐烘煟鎼搭垳绉甸柛鎾寸〒婢规洘绺介崨濠勫幗濠碘槅鍨伴幖顐﹀汲闁秵鐓熼煫鍥ㄦ⒐鐏忥箓鏌＄仦鐣屝у┑锛勫厴椤㈡稑顭ㄩ崨顔筋啌闂佽姘﹂～澶娒哄鈧畷鏇熺附閺夊棗娲、姘跺焵椤掑嫬钃熼柨娑樺閸嬫捇鏁愭惔婵嬪仐闂佸憡鐟ョ€氫即寮婚垾宕囨殕闁逞屽墴瀹曚即寮介鐘茬ウ闂佺硶鍓濋崙鐟拔ｆィ鍐╁€垫繛鎴炵懅缁犳捇鏌嶇憴鍕伌闁诡喗鐟╁畷锝嗗緞閸℃浜為梻鍌欑閹诧繝鎮烽妷鈺佺柈闁圭虎鍠栫粻鏍归崗鍏煎剹闁轰礁顑夐弻宥堫檨闁告挾鍠栭幃浼搭敋閳ь剙鐣烽崼鏇ㄦ晢濠㈣泛顑嗗▍宥夋⒒娴ｈ櫣甯涢柡灞诲姂瀹曟煡宕ｆ径澶岀畾闂佽鍎兼慨銈夊煕閹烘嚚褰掓晲閸ャ劌娈屽銈嗘礃缁海妲愰幒鏃€瀚氶柟缁樺坊閸嬫捇宕归鐐闂佸綊鍋婇崹顒佺瑜版帗鐓欓柣鎴灻悘锕傛煟鎼搭喖澧存慨濠傛惈鏁堥柛銉戝懍鎮ｉ梻浣侯攰椤曟粎鎹㈠┑瀣槬婵炴垯鍨圭粻鎶芥煙閻愯棄濡肩紓宥咃躬瀵偊骞囬弶鍧楀敹濡炪倖鍔х徊璺ㄧ矓閻戣姤鈷掑ù锝囩摂閸ゆ瑧绱掔紒妯曟垹绮嬪澶婇唶闁哄洨鍋犻幗鏇㈡⒑鐠恒劌鏋斿┑顔芥綑椤斿繐鈹戦崶銉ょ盎闂佸搫鍟崐鍛婄妤ｅ啯鐓曢柟鐑樻尵濞叉挳鏌熼绛嬫畼闁瑰弶鎸冲畷鐔碱敆閳ь剟藝閳哄懏鈷戦柟鑲╁仜婵″ジ鏌ｉ弽顐㈠付闁伙絽鍢茬叅妞ゅ繐鎳忓▍銏ゆ⒑缂佹﹩鐒鹃悘蹇旂懇钘濋柕濞炬櫆閳锋垿鏌涢幇顒€绾ч柟顖氱墦閺屻劑寮村Ο鍝勫Б缂備浇浜崑娑滅亙闂佸憡渚楅崰鎺楀箯缂佹绠鹃弶鍫濆⒔閸掍即鏌熺拠褏绡€妤犵偛妫濆畷濂稿閵忣澁绱查梺璇插嚱缁叉椽寮插┑鍫㈢幓闁哄啫鍊甸崑鎾舵喆閸曨剛锛橀梺鎼炲姀濞咃絿鍒掔€ｎ喖绠抽柡鍌氭惈娴滈箖鏌ㄥ┑鍡涱€楀ù婊勭矊闇夋繝濠傚濞堟粍鎱ㄦ繝鍐┿仢婵☆偄鍟埥澶嬫綇椤垟鍋撻崱妯肩瘈缁剧増菤閸嬫捇鎼归銏㈢崺缂傚倷绶￠崰姘卞垝椤栫偛围闁挎繂顦粈鍐煃閸濆嫬鏆欐鐐茬Ч濮婅櫣鎷犻崣澶嬪闯闂佽桨鐒﹂幃鍌炲灳閿曞倸閱囬柕澶堝劤椤︻參姊绘笟鍥у缂佸鏁婚幃锟犳偄閸忚偐鍘甸梺鍛婄箓鐎氼喛鍊撮梻浣规た閸樹粙鎮烽埡鍛摕闁炽儱纾弳鍡涙倵閿濆骸澧扮悮锔戒繆閵堝洤啸闁稿鍋熼弫顕€鍨鹃幇浣告濡炪倖甯掔€氼剟宕归崒娑栦簻闁哄啫娲ゆ禍瑙勩亜閹惧瓨銇濇慨濠傤煼瀹曟帒鈻庨幋顓熜滈梻浣告贡閳峰牓宕戞繝鍥х疇闁绘梻鈷堥弫宥嗙節婵犲倹鍣介柣鎾愁儔濮婅櫣绱掑Ο铏逛紝闂佸湱鐡旀禍顏呬繆閹间焦鏅滈柛鎾楀嫬娈為梻鍌欑窔閳ь剛鍋涢懟顖涙櫠鐎电硶鍋撳▓鍨灕妞ゆ泦鍥х叀濠㈣埖鍔曢～鍛存煟濡椿鍟忛柛鐔奉儔濮婅櫣鎷犻弻銉ュ及濠电偘鍖犻崶褏鐤呴梺璺ㄥ枔婵挳姊婚姣綊鎮℃惔锝嗘喖闂佺锕ら悘姘辨崲濞戙垹閱囨繝闈涚墔閾忓酣姊洪崫鍕靛剭闁稿﹥绻堝濠氬焺閸愨晛顎撻梺鍛婃崄鐏忔瑩宕ョ€ｎ喗鈷戦梻鍫熺⊕椤ユ瑧绱掗埀顒佹媴閻ｅ奔绨烽梻鍌欑閹测剝绗熷Δ鍛偍濡わ絽鍟粈澶愭煥閺囨浜惧銈庝簻閸熷瓨淇婇崼鏇炲耿婵°倐鍋撴繛鍏煎灴濮婅櫣绮欏▎鎯у壉闂佽鎮傜粻鏍春閳ь剚銇勯幒鎴濇灓婵炲吋鍔欓弻鐔虹矙閹稿孩鍠愰梺閫炲苯澧痪鏉跨Т椤灝顫滈埀顒勬晲閻愬墎鐤€闁哄倽顕ф禍浼存煟閻斿爼妾烽柛濠冩尭鏁堟俊銈呮噺閳锋垿鏌涢敂璇插箹闁告柨顑夐弻鐔哄枈閸楃偘绨藉┑鈥冲级閸旀瑩骞冩禒瀣仺闁汇垻顣槐鍐测攽閻愯埖褰х紒鍙夊礃閵囨劙宕橀埡鍐炬锤闂佺粯鍔﹂崜娑氱不妤ｅ啯鐓欓柣鎰靛墯缂嶆垿鏌ｉ幒鎴犵Ш闁哄本绋撻埀顒婄秵閸嬪懐浜搁悽鍛婄厓鐟滄粓宕滃┑瀣剁稏濠㈣泛鈯曞ú顏勭厸闁告劏鏅涙惔濠傗攽閻樼粯娑фい鎴濇搐閻ｅ灚绗熼埀顒勭嵁閺嶎灔搴敆閳ь剚淇婃禒瀣厱闁靛牆鎳愭晥闂佸搫鏈ú妯肩博閻旂⒈鏁嶆慨姗嗗墯濞堫厾绱撴担鍝勑ュ褎顨堥幑銏犫攽鐎ｎ偄浠洪梻鍌氱墛閸掆偓闁绘劗鍎ら悡鏇㈡煏婵炑冨暙娴犳﹢姊哄畷鍥╁笡闁哄被鍔戦崺銉﹀緞閹邦剦娼婇梺鍐叉惈閸婄懓鈻嶉崼銉︹拻濞达絽鎲￠崯鐐电磼鐎ｎ偄鐏撮柟顔芥そ婵℃悂鍩℃担鐚寸串闂備礁澹婇崑鍛哄鈧幃锟犲礃椤旂晫鍘卞┑鐘绘涧濡顢旈埡鍛厓鐟滄粓宕滃▎鎴犵濠电姴鍊婚弳锕傛煥濠靛棛澧㈤柣銈傚亾婵犵數鍋為崹鍫曟偡瑜斿畷锝夊幢濡炵粯鏂€闂佺粯顭囩划顖氣槈瑜庢穱濠囶敃閿濆洦鍣伴悗瑙勬礃婵炲﹪骞愭繝鍐ㄧ窞婵☆垳鍘ч弫鎼佹煟閻斿摜鐭嬬紒璇插閸掓帗绻濆顒傤啋闁荤姴娲╃亸顏堝箺閺囥垺鈷戦柟绋挎捣閳藉鎮楀闂寸盎闁宠绮欓、鏃堝醇閻斿搫骞楅梻渚€鈧稑宓嗘繛浣冲嫭娅犻柣妤€鐗勬禍婊堟煥閺傝法浠㈢€规挸妫濋弻鐔碱敊缁涘鐣奸梺鐟板级閹稿啿鐣烽悢纰辨晢闁稿被鍊栨晥濠电姷鏁搁崑娑㈡偤閵娧冨灊闊洦鎸撮弸鏍ㄧ箾閹存瑥鐒洪柡浣割儔閺屻劌鈹戦崱鈺傂︾紓浣哄Х缁垶濡甸崟顖氱睄闁搞儺鐓堝Λ鍕箾鐎涙鐭婄紓宥咃工椤繐煤椤忓嫭宓嶅銈嗘尵婵绮敓鐘崇厽闁靛繆鏅涢悘娆撴煛閸涱垰鈻堟鐐插暙铻栭柛娑卞幘妤犲洭姊洪悷鎵憼婵﹤缍婂顒勫焵椤掑嫭鈷掑ù锝堟鐢盯鏌ㄥ鑸电厽闊洦鏌ㄩ崫铏光偓娈垮枟婵炲﹪宕洪敓鐘插窛妞ゆ梹鍎抽獮鍫ユ⒑鐠囨彃鍤辩紓宥呮瀹曟粌鈻庤箛鏃€鐦庡┑鐘垫暩閸嬫盯鎮洪妸褍鍨濈€广儱顦粻鏍煕瀹€鈧崑鎴﹀焵椤戣法绐旂€殿噮鍣ｅ畷鐓庘攽閸偅效闂傚倷绶氬褔鈥﹂鐔剁箚闁搞儯鍔庨々鍙夌箾閸℃ɑ灏伴柍閿嬪笒闇夐柨婵嗘噺閸熺偤鏌熼姘卞缂佺粯绋撴禒锕傚磼濮橆剦鐎撮梻渚€鈧稓鈹掗柛鏃€鍨块悰顔碱潨閳ь剟銆佸▎鎾村亗閹艰揪绲洪崑鎾活敇閻愨晜鏂€闂佺粯顭囩划顖氣槈瑜庣换娑氫沪閸屾艾顬嬬紓渚囧枤缁垶濡堕敐澶婄闁冲搫鍟獮鍫ユ⒒娴ｈ鐏遍柡鍛洴瀹曟澘顫濋鑺ョ亖濠碘槅鍨甸崑鎰婵傚憡鐓熸俊顖氭惈閺嗛亶鏌嶇紒妯荤闁哄备鈧磭鏆嗛悗锝庡墰閻﹀牓鎮楃憴鍕濞存粌鐖奸妴浣割潨閳ь剟骞冮埡鍛瀭妞ゆ劧缍嗛崯宀勬⒒閸屾艾鈧绮堟笟鈧獮鏍敃閿曗偓鐎氬銇勯幒鎴濐仾闁稿骸瀛╅妵鍕冀閵娧€妫╃紓浣筋嚙濡繈寮婚敐澶婄闁挎繂鎲涢幘缁樼厸闁告侗鍠氶崣鈧梺鍝勬湰缁嬫垿鍩ユ径鎰闁绘劖褰冮婊堟⒒娴ｇ瓔鍤欐繛瀵稿厴瀹曟螣娓氼垱缍庣紓鍌欑劍钃卞┑顖涙尦閺屾稑鈽夊鍫熸暰闂佺瀛╅幐鎼佸煘閹达箑鐓￠柛鈩冦仦缁ㄨ偐绱撴担鍓插剱閻㈩垽绻濋悰顕€宕奸妷銉庘晠鏌嶉崫鍕偓鍛婄濞差亝鈷戦柛鎾瑰皺閸樻盯鏌涚€ｎ亜顏柟顖涙⒐缁绘繈宕掑Δ浣规澑闂備胶绮崝鏍ь焽濞嗘挻鍊堕柣鏂垮悑閻撴洟鏌曟繛鍨姕閻犳劧绱曠槐鎺楊敊绾拌京鍚嬮梺杞扮劍閸旀牕顕ラ崟顓涘亾閿濆骸澧鐐搭殜濮婄粯鎷呴崫銉ㄩ梺绋款儏閿曨亜鐣烽姀銈嗗仼鐎光偓閳ь剛绮堟繝鍥ㄧ厵閺夊牓绠栧顕€鏌ｉ幘璺烘灈闁哄本娲樼换婵婄疀閺囩姵娈搁梻浣筋嚙缁绘劙鎮洪妸鈺佺疄闁靛濡囩弧鈧梺鍛婁緱閸ｎ喗绂掗埡鍐＝濞撴艾娲ら弸鐔兼煟閻旀潙鍔﹂柛鈹垮灪閹棃濡搁妷褏鏆伴柣鐔哥矊缁夌數绮╅悢绋跨窞闁归偊鍘搁幏缁樼箾鏉堝墽鍒伴柟璇х磿閹峰綊鍩勯崘锔跨盎濡炪倖鎸鹃崑鐔告櫠閿曞倹鐓冮柕澶樺灣閻ｇ敻鏌熼鐣岀煉闁诡喖澧芥禒锕傛偩鐏炶浜伴梻鍌氬€风粈浣圭珶婵犲洤纾诲〒姘ｅ亾鐎规洘娲樺蹇涘Ω閵夈儱顫婇梻鍌氬€搁崐椋庢濮橆剦鐒界憸鏃囨濡炪倖鎸堕崹褰掑垂閸屾稓绠剧€瑰壊鍠曠花缁樹繆椤愶綇鑰块柡灞界Х椤т線鏌涢幘璺烘瀻妞ゎ偄绻掔槐鎺懳熺拠宸偓鎾绘⒑閸涘﹦鈽夐柨鏇樺€濆鎶藉醇濠靛啯鏂€闂佺粯鍔欓·鍌炲吹鐎ｎ剛纾奸柣妯挎珪鐏忣參鏌ｉ敐鍥у幋妤犵偛顑夐弫鍐焵椤掑倻鐭嗛悗锝庡亖娴滄粓鏌熼崫鍕ゆい锔煎閳ь剚顔栭崰鏍ь焽閿熺姴绠栨俊銈呮噹缁€鍌氼熆鐠虹尨姊楀瑙勬礋濮婄粯鎷呴崨濠傛殘濠电偠顕滅粻鎾崇暦濡も偓椤粓鍩€椤掑嫮宓?")
        elif verbosity_bias == "expanded":
            lines.append("缂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ょ紓宥咃躬瀵鏁愭径濠勵吅闂佹寧绻傞幉娑㈠箻缂佹鍘辨繝鐢靛Т閸婂綊宕戦妷鈺傜厸閻忕偠顕ф慨鍌溾偓娈垮櫘閸撶喎鐣疯ぐ鎺濇晩閻熸瑥瀚惁閬嶆⒒閸屾瑧鍔嶆俊鐐叉健瀹曘垺绂掔€ｎ偄浠梺鍐叉惈閹冲酣鎷戦悢鍏肩厽闁哄倽娉曞▓閬嶆煛鐎ｎ亪鍙勬慨濠佺矙瀹曞爼顢楁径瀣珨闁荤喐绮岀粔鍫曞矗閸涱収娓婚柕鍫濇閹嫭绻涢悡搴㈠仴闁糕斁鍋撳銈嗗灱濞夋洟藝閿曞倹鐓冮悹鍥ㄧ叀閸欏嫭顨ラ悙鐤殿亪鎮鹃悜钘夌倞闁煎憡鏅妶澶嬧拺闁煎鍊曢弸鎴犵磼椤旇偐鐏遍柟骞垮灩铻ｉ柟绋垮瘨濡劌鈹戦敍鍕杭闁稿﹥鐗犻幃褍螖閸涱厽妲梺鍛婂姦閸犳牜绱掗埡鍛厾闁诡厽甯掗崝妯好瑰鍕煉闁哄矉绻濆畷鎺戔槈閸楃偛濡兼繝鐢靛仩閸嬫劙宕版惔銊︾畳闂備胶绮敋缁剧虎鍙冮幆宀勫箳濡や胶鍘搁柣蹇曞仜婢т粙濡撮幒妤佺厓鐟滄粓宕滈妸褏绀婇柛鈩冪☉绾惧鏌涘☉鍗炵仧闁绘帒锕弻锝呂旈埀顒勬偋閸曨剛顩叉繝濠傜墛閻撳繐鈹戦悩鑼闁告帊鍗抽弻娑㈠籍閹惧墎鏆ら梺鍝勭灱閸犳牠銆佸▎鎾村仼閻忕偞鍎冲▍姘繆閵堝洤啸闁稿鍋ら獮鎴﹀炊椤掑倸绁﹂梺鍦劋閸ㄧ喖寮ㄦ禒瀣厱闁斥晛鍟ㄦ禍妤呮煏婵炑冩噽閿涙繈姊虹粙鎸庢拱闁煎綊绠栭崺鈧い鎺戝€搁崢鎾煙閾忣偒娈滅€规洘绮嶉幏鍛矙鐠恒劋鍠婂┑锛勫亼閸婃牠鎮уΔ鍐ㄥ灊鐎广儱鎳愰弳锕傛煛鐏炶鍔滈柣鎾存礃閵囧嫰骞囬崜浣瑰仹缂備胶濮甸敃銏ゅ蓟閿熺姴骞㈡い鎾跺Х閺嗐倝姊洪崫鍕拱婵炲弶顭囬幑銏犫槈閵忊€斥偓閿嬨亜閹哄秷鍏岀憸鎵枛濮婄粯鎷呴懞銉ｂ偓鍐磼閳ь剚鎷呴搹鍦厠闂佹眹鍨归悘姘暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁活剙銈稿畷鏇㈠箛閺夎法鍔﹀銈嗗笂缁垛€斥枔濠婂牊鐓涚€光偓鐎ｎ剛鐦堥悗瑙勬处娴滎亜鐣峰鈧、鏃堝窗閳哄倸鐏╃紒杈ㄦ尰閹峰懘鎼归悷鎵偧缂傚倷娴囬褔鎮ч幘鑽ゅ祦闁告劏鏅濋々鐑芥倵閿濆骸浜芥俊顐㈠暙閳规垿鎮欓弶鎴犱桓濡炪們鍔屽Λ婵嗙暦閻旂厧绀冩い鏃囆掗幏缁樼箾鏉堝墽绉い顐㈩樀瀹曟垿鎮╃紒妯煎幈闂佸搫鍊藉▔鏇㈡倿閹间焦鐓欐い鏂挎惈閸旀粎绱掓潪鎵煓鐎规洦鍋婃俊鐑藉Ψ瑜嬮崑濠囨⒒閸屾瑧顦︽繝鈧潏銊︽珷婵°倐鍋撴い顓炵仢铻ｉ柤娴嬫櫃缁楀绱撻崒娆戝妽閼垦兠瑰鍕煉闁哄矉绻濆畷姗€濡搁敂鑺ュ€峰┑鐐茬摠缁瞼绱炴繝鍥ц摕闁靛鍎Σ鍫熺箾閸℃ê鐏﹂柛鎺撶☉閳规垿顢欑涵閿嬫暰濠碉紕鍋樼划娆撶嵁閸愵喗鍊婚柦妯侯槺妤犲洭鏌熼悡搴ｆ憼闁规瓕宕甸埀顒€鐏氶悧婊呮閹捐纾兼繛鍡樺灱缁愭姊洪棃鈺冪У闁革綇绲介悾鐑藉捶椤撶喎纾梺鎯х箺椤鈻撴ィ鍐┾拺闁革富鍘奸。鍏肩節閵忊槄鑰块柡灞筋儔瀹曞爼顢楁担鍝勫箰闂備焦鎮堕崕顕€寮插☉妯兼懃闂佽崵鍠愮划宥咁熆濡皷鍋撳顓熺凡妞ゎ偄绻愮叅妞ゅ繐瀚鎰版⒑缂佹ê濮堢憸鏉垮暞閹便劌鐣濋崟顑芥嫼闂佸憡绋戦敃銉╂偂閵壯呯＜濠㈣泛楠搁悡鎰磼閸屾氨效妤犵偞鐗楅幏鍛存偡妫颁胶绱﹂梻鍌欑劍閻綊宕规繝姘瀬闁归棿鐒﹂弲顒佺節婵犲倻澧涢柍閿嬪灩缁辨挻鎷呴獮搴撳亾閻愬搫绠ｉ柨婵嗗暕濮规姊洪崨濠傚Е濞存粎鍋涜灋妞ゆ牗绮嶉崰鎰版煛閸愩劎澧曢柦鍐枛閺岋繝宕堕妷銉т患闂佺粯鍔曢敃锕傚箟缁嬫鍚嬪鑸瞪戦弲婊冾渻閵堝棙灏甸柛锝冨劚閳绘挻绂掔€ｎ偆鍘介梺褰掑亰閸樼晫绱為幋鐐电闁圭⒈鍘奸弸銈夋煃瑜滈崜姘额敊閺嶎厼闂い鏇楀亾鐎规洘绮岄～婵嬵敆婢跺﹥顔傞梻浣告啞濞诧箓宕归弶娆惧晠婵犻潧妫岄弨浠嬫煟濡绲绘い鎺嬪灮缁辨挸顓奸崱鈺傜杹濠殿喖锕ら…宄扮暦閹烘埈娼╂い鎴ｆ娴滈箖鏌ｉ幋锝呅撻柛銈呭閺屾盯顢曢敐鍡欘槬缂備胶濮锋繛鈧柡宀€鍠栭獮鎴﹀箛闂堟稒顔勯梺鐟板悑濞兼瑩鏁冮鍫濊摕闁挎稑瀚▽顏堟偣閸ャ劌绲诲┑顔奸叄濮婂搫效閸パ€鍋撻妶澶婇棷闁挎繂顦拑鐔兼煟閺冨洦顏犵痪鎯с偢閺屾洝绠涢弴鐐愶綁鏌ｈ箛鎾跺ⅱ缂佽鲸鎸婚幏鍛村传閸曟埊绲剧换婵嬪閳藉懓鈧潡鏌涢埡鍐ㄤ槐妤犵偛顑夐弫鍌炴寠婢跺鐫忛梻鍌欑濠€杈╁垝椤栨粍鏆滄俊銈傚亾闁崇粯鎹囬、姗€鎮╅悽纰夌闯濠电偠鎻徊鍧椻€﹂崼銉ｂ偓鍌炲箮閼恒儳鍘遍柣搴祷閸斿矂鍩€椤掍胶绠為柣娑卞櫍瀹曟﹢濡告惔銏☆棃鐎规洏鍔戦、娆撴嚍閵壯冪闂傚倷绀佸﹢閬嶅储瑜旈幃娲Ω瑜庡畷鏌ユ煕閺囥劌鐏￠柛搴￠叄楠炴牕菐椤掆偓婵′粙鏌嶉柨瀣伌闁哄被鍊栭幈銊╁箛椤戣棄浜鹃柡鍥ュ灩閸戠娀骞栧ǎ顒€濡介柍閿嬪灴閹粙顢涢敐鍛亾闂佸憡甯炴晶妤呭Φ閸曨垼鏁冮柕蹇嬪灮椤斿﹦绱撴担浠嬪摵閻㈩垱甯熼悘鎺楁煟閻樺弶鎼愭俊顖氾躬閸┾偓妞ゆ帊鐒﹀畷灞炬叏婵犲啯銇濋柟绛圭節婵″爼宕ㄩ鍙ラ偗闂傚倷鑳堕…鍫ヮ敄閸涘瓨鏅濇い蹇撳閺嗭箓鏌ｉ姀銏╂毌闁稿鎹囬弫鎰償閳ユ剚娼剧紓浣哄亾瀹曟ê螞閸曨垱绠掗梻浣瑰缁诲倿骞婃惔銊嬪绠涘☉娆戝幈闁瑰吋鐣崹瑙勬叏瀹ュ鐓涢悘鐐插⒔濞叉潙鈹戦埄鍐╁€愬┑锛勬焿椤﹂亶鏌ц箛鎾活€楁い顏勫暣婵″爼宕卞Ο灏栨晬缂傚倸鍊哥粔宕囨濮樺墎宓侀柛鎰ㄦ櫇椤╃兘鎮楅敐搴濈敖妞わ富鍙冨娲川婵犲嫭鍣у銈忛檮濠㈡﹢鍩㈠鍛殕闁告洦鍏橀幏缁樼箾鏉堝墽鍒伴柟璇х節瀹曨垶鎮欑€靛摜顔曢柣鐘叉厂閸涱垱娈奸柣搴ゎ潐濞叉﹢宕归崹顔炬殾闁绘梻鈷堥弫宥嗙箾閹寸們姘跺磻閹捐鍨傛い鎰С缁ㄥ姊虹憴鍕婵炲绋掔粋宥堛亹閹烘挾鍘搁梺閫炲苯澧紒鍌涘笧閳ь剨缍嗛崑鍡涘储閽樺鏀介柍钘夋閻忊剝銇勯幋鐐垫噰鐎规洜鏁搁埀顒婄秵閸忔﹢宕戦幘鑸靛枂闁告洦鍓欐禒鈺呮⒑缁嬫寧鎹ｉ柡浣割煼閻涱噣宕橀妸搴㈡閸┾偓妞ゆ帒瀚哥紞鏍ㄧ節闂堟侗鍎愰柛瀣€块獮鏍庨鈧悘顔炬喐閺夊潡鍙勬慨濠勭帛缁楃喖鍩€椤掆偓椤洩顦查摶鐐翠繆閵堝懏鍣圭紒鐘靛У閹便劌顪冪拠韫闁诲孩顔栭崰鏍€﹂柨瀣╃箚婵繂鐭堝Σ鐑芥⒑缁嬫鍎愰柟鐟版喘瀵偊骞囬弶璺槰闂侀潧顭堥崕娲倵鏉堚晝纾介柛灞剧懇濡剧兘鏌涢弬璺ㄧ劯闁炽儻绠戦悾锟犳焽閿旂晫绋佹繝鐢靛仜濡﹥绂嶅┑瀣；闁跨喓濮甸悡鐔镐繆閵堝倸浜鹃梺缁橆殔閿曨亜鐣烽弴銏犵闁哄倶鍎查弬鈧梻浣哥枃濡嫬螞濡や胶顩叉繝闈涙储娴滄粓鏌曟繛鍨姕妞ゃ儳濮风槐鎺楊敊绾板崬鍓板銈嗘尭閵堢鐣烽柆宥呯疀妞ゆ垼娉曢崙褰掓⒒閸屾瑧顦﹂柟璇х節瀹曟繆绠涘☉妯活棟婵炴挻鍩冮崑鎾搭殽閻愯尙绠伴悡銈嗐亜韫囨挻鍣抽柟閿嬫そ濮婃椽宕ㄦ繝鍕ㄦ闂佹寧娲╂俊鍥╂閹炬剚娼╅柤鍝ユ暩閸橀亶鏌熼崗鑲╂殬闁告柨顑夐獮澶愬礈瑜夐崑鎾斥枔閸喗鐏嶆繝鐢靛仜閿曨亜顕ｆ繝姘耿婵°倕锕ら幃鎴︽⒑缁洖澧查柣鐔村劦閻涱噣宕奸妷锔规嫼闁荤姴娲﹁ぐ鍐吹鏉堚晝纾界€广儱鎳忛ˉ銏⑩偓瑙勬礃閸ㄥ灝鐣烽妸鈺婃晬婵炲棙鍨垫晶楣冩⒒娴ｅ湱婀介柛銊ヮ煼瀵偊宕妷銉婵犻潧鍊婚…鍫㈢棯瑜旈弻娑㈩敃閿濆洠妲堟繝纰夌磿閺咁偊鍩€椤掑喚娼愭繛鍙夌墵閹绺界粙璺ㄥ姦濡炪倖甯掗崰姘焽閹邦厾绠鹃柛娆忣樈閻掍粙鏌℃笟鍥ф珝妤犵偞甯掕灃闁逞屽墴閹€斥攽鐎ｎ亞顔愬┑鐑囩秵閸撴瑦淇婇懖鈺冪＜闁绘瑥鎳愮粔顕€鏌″畝瀣埌閾伙絿绱掗妸鎴濆閻忋儵鏌ｉ敐鍡欑畼缂侇喗鐟ラ埢搴ㄦ倷椤掑倻鈻夊┑鐘垫暩閸嬫稑螣婵犲啰顩叉繝濠傚枤閸熷懏绻濋棃娑欘棏闁衡偓娴犲鐓熸俊顖濇硶缁ㄥ潡鏌涜箛鎾剁伇缂佽鲸甯為幏瀣暦閸モ晝宕叉繝娈垮枛閿曘儱顪冩禒瀣祦闁哄稁鍘介崐鐑芥煙缂佹ê淇繛鐓庨閳规垿鎮欓懠顒佹喖缂備緡鍠栫换鎰板煝閺傚簱妲堥柕蹇婃櫆閺咁亪姊洪幐搴ｇ畵妞わ缚鍗抽獮鍡涙倷濞ｎ兛绨婚梺瑙勫閺呮盯鎮炲ú顏呯厱闁靛牆鍟埀顒佺箞瀵鏁愰崱妯哄妳闂侀潧绻嗛幊鍥ㄦ叏閸ヮ剚鐓犻悷浣靛€曢埀顒佺箞瀵鎮㈤崗鐓庝痪濡炪倖鐗楁笟妤佺閳哄啰纾藉ù锝勭矙閸濇椽鎮介婊冧户婵″弶鍔欓獮鎺懳旈埀顒勶綖閸涘瓨鐓熸俊顖氱仢閻ㄧ儤銇勯弮鈧崝娆忣潖缂佹ɑ濯撮柣鎴灻▓宀勬⒑閸濄儱鏋欐繛澶嬫礋楠炴垿濮€閵堝懐顔婇梺鐟扮摠濮婂綊锝炲澶嬧拺闁告捁灏欓崢娑㈡煕鐎ｂ晝绐旂€规洘鍨垮畷銊р偓娑欘焽閸橀亶姊虹涵鍛劷闁告柨绉撮埢宥夊炊椤掍胶鍘卞┑鐐叉缁绘垿藟閵忊剝鍙忓┑鐘插暞閵囨繄鈧娲﹂崑濠傜暦閻旂⒈鏁嗛柍褜鍓熻棟闁冲搫鎳忛埛鎴︽煙缁嬪潡顎楅柛婵囨そ閺岋紕浠﹂悾灞濄儲銇勮缁舵岸寮诲☉銏犵闁哄鍨甸幗鐢告⒑闂堟稒顥滈柛鐕佸灣閹广垹鈹戠€ｎ亞锛滈梺闈涚墕閹冲繘顢橀幐搴濈箚闁绘劦浜滈埀顒佺墵瀹曟繆顦撮柍褜鍓熷褔鎯岄崒姘煎殨妞ゆ劑鍊愰崑鎾绘晲鎼粹剝鐏嶉梺缁樻尭閸熶即骞夌粙娆剧叆闁割偅绻勯ˇ顓㈡⒑缂佹ɑ鈷掗柛妯犲棛绠芥繝鐢靛仦閹稿宕洪崘顔肩；闁规儳鐏堥崑鎾斥枔閸喗鐏嶉梺瑙勭摃濞呮洟骞堥妸鈺佺劦妞ゆ帒瀚悡鍐煃鏉炴壆顦﹂柡鍡欏仱閺岋絽鈹戦崶銊ь槹濠殿喖锕︾划顖炲箯閸涘瓨瀵犲璇″幗閹瑰洭寮婚妸銉僵妞ゆ挻绮堢花濠氭⒑閹稿孩顥嗘い鏇嗗啠鏋嶇€广儱娲犻崑鎾舵喆閸曨剙顦╅梺绋款儏鐎氼垶鎮橀崘顔解拺闁告稑锕ｇ欢閬嶆煕閻樺啿娴鐐茬箳缁辨帒螣閼测晩鍟庨梺鍝勵槸閻楀棙鏅堕悾宀€鐭撴い鎺嶈兌缁犻箖鏌涘鍐ㄦ殶缂佸鍠栭埞鎴﹀灳瀹曞洦鎲肩紓浣虹帛缁诲牆鐣烽崼鏇炍╃憸宥夌嵁閸儲鈷掑ù锝囩摂濞兼劙鏌涙惔銏犫枙妞ゃ垺宀搁、姗€鎮╅崗鍝ョ憹闂備胶绮崝妤呭磿閵堝鍋傞煫鍥ㄧ⊕閻撴洟鏌嶉埡浣告灓婵炲牊妫冮弻锟犲幢椤撶姵鍋ч梺閫炲苯澧叉い顐㈩槸鐓ら柡宓懏娈惧銈嗗笒鐎氼剟鎮″┑瀣閺夊牆澧界€靛吋绻涘畝濠侀偗闁哄瞼鍠撻埀顒佺⊕閿氱紒妤佸笚閵囧嫰濡烽敂缁㈡殹缂備胶绮换鍌炲煝閹捐鍨傛い鏃傛櫕娴滃爼姊绘担鐟邦嚋婵炴彃绉瑰鏌ユ偐閼碱剚娈鹃梺闈涚返閺夊じ绨奸梻浣告啞閸旀垿宕濇惔銊﹀亗闁硅揪闄勯埛鎴︽⒑椤愩倕浠滈柤娲诲灡閺呭墎鈧稒蓱閸欏繐鈹戦悩鎻掓殲闁靛洦绻勯埀顒冾潐濞诧箓宕戞繝鍌滄殾闁绘梻鈷堥弫鍐┿亜閹拌泛寮烽柨婵嗩槹閳锋帒霉閿濆懏鍟為柛鐔哄仱閺岀喎顫㈢仦钘夋優闂佺懓绠嶉崹钘夌暦閹烘鍊婚柛鈩兩戝▍鏃堟⒒娓氣偓濞佳囁囬锕€鐤炬繛鎴炴皑閻棝鎮楅敐搴′簴濞存粍绮撻弻鐔兼倻濡櫣浠撮梺閫炲苯澧い顓犲厴楠炲棙绗熼埀顒€鐣锋總绋课ㄩ柨鏃囶潐鐎氳偐绱撻崒娆戭槮妞ゆ垵妫涢埀顒傜懗閸愯儻鈧潡鏌熷▓鍨灓缁炬儳銈搁幃妤呮晲鎼粹€茬盎濠电偞鎯岄崰妤呭Φ閸曨垰顫呴柨娑樺閸ｆ澘螖閻橀潧浠滄い鎴濐樀瀵偊宕掑鍕瀭闂佹寧绻傚Λ妤咁敂閻戞绡€闁汇垽娼ф禒锕傛煙缁嬫鐓肩€规洘妞藉畷姗€顢欓懖鈺嬬幢闂備浇顫夐崕鎶筋敋椤撶姷涓嶉柟顖ｇ亹瑜版帗鏅查柛娑卞幗濮ｆ劙姊洪崨濠勵暡闁挎岸鏌嶉挊澶樻Ц閾伙綁鏌涜箛鎾虫倯闁伙絿鍏樺缁樻媴閸涘﹤鏆堝┑鐐额嚋缁犳挸鐣烽幋锕€骞㈡繛鎴炵懄濞呮牕鈹戦悙鏉戠仧闁搞劍妞介崺娑㈠箣閿旂晫鍘介梺缁樻煥閹诧紕娆㈤弻銉︾厓闂佸灝顑嗛埛鎺旂磼鏉堛劌娴い銏″哺瀹曘劑顢橀悩杈敇闂傚倷娴囬鏍闯椤栨粍宕叉繝闈涱儏缁犳牠鏌曡箛瀣偓鏇犵矆閸岀偞鐓犳繛鏉戭儐濞呭懏顨ラ悙鎼畷缂佺粯绻勯崰濠偽熷ú缁樼秹闂備焦鎮堕崝瀣础閾忣偂绻嗛梻鍫熶緱濞笺劑鏌嶈閸撴瑩鎮鹃悜钘壩ㄩ柍鍝勶攻閺呮繈姊洪幐搴⑩拻闁哄拋鍋婂畷銏ゆ焼瀹ュ棌鎷洪梺鍛婄箓鐎氼剟鍩€椤掑啯顥夐柍缁樻瀵挳鎮㈤崨濠勫綑闂傚倸鍊搁崐椋庣矆娓氣偓楠炴牠顢曢敂钘夊壒婵犮垼娉涢惉鑲╃矆婵犲倶鈧帒顫濋敐鍛闂備胶绮笟妤呭窗閺嶎厼鐓濋幖娣妼缁犺崵鈧娲栧ù鍌毼ｇ憴鍕箚闁绘劦浜滈埀顒佺墵楠炴劙鎮欓浣稿伎閻庣懓瀚€氬牓鏁愭径濠勫€炲銈嗗笂鐠佹煡骞忕紒妯肩閺夊牆澧界粔顒佺箾閸滃啰绉┑鈥崇摠缁绘繈宕堕妸褍骞愰梻浣侯焾閺堫剟鎮疯缁綁寮崒妤€浜鹃悷娆忓缁€鍐煕閵娿儲鍋ラ柣娑卞枛椤粓鍩€椤掑嫮宓侀柛銉ｅ妽婵挳鏌ｉ悢绋款棆婵¤缍佸濠氬磼濞嗘垹鐛㈠┑鐐板尃閸ャ劌浜遍梺绯曞墲閵囧倸鈽夊Ο婊勬瀹曘劑顢橀姀鈩冩當婵犵數濮烽弫鍛婃叏閺夋嚚娲晝閸屾稑浜楅梺鍝勬储閸ㄦ椽宕愰悽鍛婄叆婵犻潧妫濋妤€霉濠婂嫮绠為柟顔筋焾缁犳盯寮撮悢鍛婄槑缂傚倷娴囨ご鍝ユ暜濡も偓椤洩绠涘☉妯溾晠鏌曟竟顖氳嫰閸擃剟姊婚崒娆戭槮缂傚秴锕棢闁规儳顕粻楣冩煃瑜滈崜鐔煎蓟閻旈鏆﹂柛銉戔偓閺嬪懎顪冮妶鍐ㄧ仾妞ゃ劌锕畷娲焵椤掍降浜滈柟鐑樺灥椤忊晠鏌ｉ幒鎴吋闁哄矉缍佹慨鈧柣妯哄暱閺嗗牓姊洪幎鑺ユ暠闁搞劌婀卞Σ鎰板箳濡ゅ﹥鏅┑鐐村灦閻熝囁囬妸鈺傗拺闁告繂瀚峰Σ鍝ョ磽瀹ュ拑韬€?")
        if review_cadence == "light":
            lines.append("濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮诲☉妯锋婵鐗婇弫楣冩⒑閸涘﹦鎳冪紒缁樺姍濠€渚€姊虹粙璺ㄧ闁告艾顑囩槐鐐哄箣閿旂晫鍘遍梺闈涱焾閸庨亶鍩€椤掆偓濞尖€愁嚕婵犳碍鏅插璺猴功椤旀帡鎮楃憴鍕婵炲眰鍊濆畷顐⒚洪鍛嫼闂佸憡绻傜€氱兘宕曢幇鐗堢厽婵°倓绶″▓姗€鏌熼獮鍨仼闁宠棄顦垫慨鈧柣妯活問閸氬懘姊绘担铏瑰笡闁告梹娲熼、姘额敇閻愨晜鐏侀梺闈涚墕椤︿即鍩涢幋鐐电闁煎ジ顤傞崵娆愵殽閻愭惌娈滈柡宀€鍠栭獮鏍ㄦ媴閾忚姣囬梻浣虹《閺備線宕戦幘鎰佹富闁靛牆妫楃粭鎺楁煕閻樺疇澹樻い顓炴喘楠炲洭顢橀悩娈垮晭闂備礁鎲￠悷銉┧囨潏銊︽珷妞ゅ繐鐗婇崑鍌炴煏閸繍妲归柣鎾崇箻閺屾盯顢曢敐鍥╃暫濡炪們鍎抽崑銈夊蓟濞戞ǚ鏋庨煫鍥ㄦ礈椤斿姊洪棃娑欐悙閻庢矮鍗抽悰顕€骞掑Δ鈧粻锝嗙節閸偄濮冮柣銉邯濮婄粯鎷呴搹鐟扮闂佽鐡曢褏鍙呴梺缁樻⒒閸樠囨嫅閻斿吋鐓ラ柣鏂挎惈瀛濋梺缁樺姇閿曨亪寮婚弴鐔风窞闁割偅绻傛慨搴☆渻閵堝骸澧柣妤佹尭椤繘鎼圭憴鍕彴闂佽偐鈷堥崜娑㈩敊婵犲啰绡€婵炲牆鐏濆▍宥嗐亜閵夛附灏崡閬嶆煙閻楀牊绶茬紒鐘烘珪娣囧﹪濡堕崟顓фМ婵炲瓨绮岀紞濠傤潖濞差亜绀堥柤纰卞墮鐢儵姊虹粙娆惧剰闁瑰啿姘﹂。楣冩⒑閸撴彃浜栭柛搴㈢叀閸╂盯骞嬮敂鐣屽幈濠电娀娼уΛ妤咁敂椤愶附鐓熼煫鍥ㄧ◥閹查箖鏌＄仦鍓ф创闁诡喒鏅涢悾鐑藉炊瑜夐幏鐗堜繆閵堝洤啸闁稿鐩畷顖炲箮閸撳灝娲畷鐑筋敇濞戞ü澹曢柣鐔哥懃鐎氼厾绮堥埀顒勬⒑闂堟稓澧涢柟顔煎€块悰顕€宕橀纰辨綂闂侀潧鐗嗛幊宥囨閸洘鈷戦柛娑橈攻婢跺嫰鏌涚€ｎ亝鍤囨い銏∩戠缓浠嬪川婵炵偓瀚介梻浣侯焾閺堫剟鎳濇ィ鍐ㄧ劦妞ゆ帒瀚峰Λ鎴犵磼椤旇偐澧涚紒妤冨枛閸┾偓妞ゆ帒瀚畵渚€鏌″搴″季闁轰礁鍟撮弻銊╁即濡も偓娴滃墽绱撴担鍝勵€岄柛銊ョ埣楠炲啫螖閸涱喗娅滈柟鑲╄ˉ閳ь剝灏欓弫鏍ㄤ繆閻愵亜鈧劙寮插☉姗嗗殨闁告挷鐒﹀畷鍙夌節闂堟稒宸濈紒鈾€鍋撻梻浣侯焾閺堫剛鍒掑畝鍔肩兘鍩€椤掑倻纾介柛灞剧懆閸忓苯鈹戦鐐毄闁轰緡鍣ｉ崹楣冨箛娴ｅ湱绋佺紓鍌氬€烽悞锕佹懌婵犳鍨卞娆撳Υ閹烘埈娼╅柣鎾虫捣娴狀垶姊洪崨濠冪叆闁硅姤绮庡Σ鎰板箻鐎涙ê顎撻梺鎯х箳閹虫挾绮垾鎰佹富闁靛牆鍟俊濂告煥閺囨ê鈧繈骞冩ィ鍐╁€婚柦妯侯槺椤撴椽姊洪幐搴㈢５闁稿鎸剧槐鎺楁偐瀹曞洦鍒涢梺鍝勮閸婃繂鐣峰鍫濈闁圭儤鍨电粻锝夋⒒娴ｄ警鐒炬い鎴濇楠炴垿宕惰閺嗭箓鏌熼悜姗嗘畷闁稿﹦鍏橀弻銈囧枈閸楃偛顫梺鍛婏供閸撴瑩鍩為幋锔藉亹妞ゆ棁鍋愭导鍥р攽閻愬樊妲归柣鈺婂灦楠炲棙寰勭€ｎ剟妾梺鍛婃尭瀵爼寮查埡鍛拺闁告繂瀚崒銊╂煕閵婏附銇濋柛鈺傜洴楠炲鏁傞悾灞藉箞闂備焦瀵уΛ渚€顢氳閻涱喖顫滈埀顒勫箖娴犲鏁嶆繛鎴炵閸掓盯姊虹拠鈥虫灆缂侇喗鐟╅妴浣糕槈濡攱顫嶉柡澶婄墑閸斿酣寮惰ぐ鎺撶厽閹兼番鍊ゅ鎰箾閸欏鑰跨€规洖缍婇獮鎰償濠靛牏鐣鹃梻浣圭湽閸娿倝宕归悡骞綁鎮滈懞銉㈡嫼缂備礁顑嗛娆撳磿閹扮増鐓欓柟闂磋兌閻ｇ儤顨ラ悙宸█妤犵偞锕㈤、娆撴嚃閳哄﹥效濠碉紕鍋戦崐鏍暜閹烘纾婚柛鈩冦亗閿濆鍋嬮柛顐ｇ矌缁犳岸姊虹紒妯哄Е濞存粍绮撻崺鈧い鎺嶇閻忓鈧娲樼换鍌炴偩濠靛绀嬫い鎺嗗亾濞存粓浜跺铏规喆閸曨偆顦ㄥ銈嗘肠閸パ冨挤闂侀潧顦弲婊堟偂閸愵亝鍠愭繝濠傜墕缁€鍫熸叏濡寧纭惧鍛存⒑閸涘﹥澶勯柛銊﹀缁骞庨懞銉у幍闂佸湱鈷堥崢濂告倶閻樻祴鏀芥い鏃傛櫕閵嗘帞绱掓潏銊﹀鞍闁瑰嘲鎳樺畷婊堝矗婢跺棙鐎板┑鐘垫暩閸嬫﹢宕犻悩璇茬倞闁靛ě鍛濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柟缁㈠枟閺呮繈鏌曢崼婵囩闁稿鎸搁～婵嬫偂鎼淬垻褰庨梻浣筋嚃閸ㄤ即鎯岄崒鐐靛祦闁圭儤鍤﹂弮鈧幏鍛村传閸曨偆顓兼繝纰夌磿閸嬫垿宕愰弽顬℃椽寮介‖顒佺☉閳藉顫濋鈧ⅲ闂備線鈧偛鑻晶顕€鎽堕弽顓熺厽婵せ鍋撴繛浣冲嫮顩锋繝濠傚娴滄粓鏌熺€涙绠ユ俊顖楀亾闁诲孩顔栭崳顕€宕戞繝鍌滄殾闁圭儤顨嗛崐鐑芥煛婢跺鐏ｉ柟顕嗙秮濮婅櫣鎷犻懠顒傤唺闂佺顑囨慨纾嬬亱闂佸憡娲﹂崐锝堫樄妤犵偞鎹囬獮鎺楀幢濡粯婢戦梻鍌欒兌缁垶鏁嬮梺璇茬箲瀹€绋款嚕閹惰棄鐓涢柛娑卞枤閸橀亶鏌ｆ惔顖滅У闁告挻鐟︾粋鎺撴綇閳规儳浜鹃悷娆忓缁€鈧紓鍌氱Т閿曘倝鎮鹃柨瀣檮缂佸鐏濆畵鍡椻攽閿涘嫬浠╂い鏇嗗嫮顩插Δ锝呭暞閻撱儵鏌￠崶鈺佷粶闁逞屽墯閹倿寮荤€ｎ喖鐐婃い鎺嶈兌閸樻捇姊洪幖鐐插缂佸甯掗埢宥夊川椤掕偐鎳撻…銊╁川椤撴繂顥氶梻渚€鈧稓鈹掗柛鏂跨焸閿濈偛顭ㄩ崼婵嗚€垮┑锛勫仜婢т粙鎯勬惔銊︾厽閹兼番鍊ゅ鎰版煙閸濄儺鐒鹃摶鐐寸節闂堟侗鍎忛柦鍐枛閺屻劌鈽夊Ο渚还濠电偛鐭堟禍顏堝蓟濞戙垹绠绘俊鐐额嚙娴滄儳鈹戦埄鍐ㄧ祷闁绘鎹囧鏄忣槼閻庣數鍘ч埢搴ㄥ箣閻樻ɑ绮撳娲传閸曨噮娼堕梺绋匡攻閻楃娀鐛崼銉ノ╅柍杞拌兌閻も偓婵＄偑鍊栭崹鐓幬涢崟顒傤洸濡わ絽鍟悡娑氣偓骞垮劚妤犳悂鐛弽顐ょ＜闁逞屽墴瀹曞崬螣閼测晩鍟庨梻浣烘嚀閻°劑鎮烽妷鈺傚€舵い蹇撶墛閻撴洖鈹戦悩鎻掝仾闁哄棭鍓熼弻鐔碱敊閻撳孩些闂佸疇顕у锔剧不濞戙垹绠奸柛鎰屽懏锛忕紓鍌氬€搁崐椋庢媼閺屻儱纾婚柟鍓х帛閻撴洟鏌熼弶鍨倎缂併劍鎸抽弻娑氣偓锝庡亝瀹曞瞼鈧娲橀〃鍡楊嚗閸曨剛绡€濞达絽澹婂Λ婊堟⒒閸屾艾鈧绮堟担铏圭濠电姴浼ｅ☉銏犻敜婵°倓璁查幐鍐倵楠炲灝鍔氭い锔诲灦閹偤宕归鐘辩盎闂佺鎻徊鍓ф兜閸撲胶纾奸柟閭﹀幗閳锋帡鏌嶈閸撴岸顢欓弽顓炵獥婵°倕鎳庣粻浼存煣韫囷絽浜濋柛娆忕箻閺屽秷顧侀柛鎾跺枛瀵鏁愰崨鍌滃枛閹筹繝濡堕崨顏勫緧闂傚倷绀侀幉锟犲蓟閵娧呯煋閻熸瑥瀚换鍡涙煟閵忋埄鐒剧紒鈧€ｎ偁浜滈柡宥冨妿椤ｅ弶銇勯妷锔剧疄闁哄瞼鍠栭幃鈩冩償閿濆棙鍠栭梻浣告贡椤牓骞夐敍鍕焿鐎广儱妫庨崑鍛存煕閹般劍娅囬柛妯圭矙濮婃椽宕崟顐熷亾閸︻厸鍋撶粭娑樻搐閻ゎ噣鏌ｉ幇顔煎妺闁绘挾鍠愮换婵嬪垂椤愶絽鏆楅梺鍛婂笂閸楁娊寮诲鍥ㄥ枂闁告洦鍋嗘导宀勬⒑鐠団€虫灀闁哄懐濮撮悾鐤亹閹烘繃鏅濋梺鎸庣箓濡稑危閹寸偟绡€闁汇垽娼ф牎濡炪倖姊归悧鐘茬暦娴兼潙鍗抽柕蹇曞Х椤㈠懘姊洪崨濠傚閻忓繑鐟╁鎶芥晝閸屾稑浠┑鐐叉缁绘劙顢旈锝冧簻闁冲搫鍟崢鎾煙椤旂瓔娈滈柡浣瑰姍瀹曘劑顢樿缁辨垿姊绘担渚劸缂佺粯鍨块弫瀣⒑娴兼瑧鎮奸柛蹇旓耿閻涱噣骞掑Δ鈧粻锝夋煛閸愶絽浜惧銈庡亜缁夋挳鍩為幋锔绘晩闁活収鍋掓禍顏勭暦閵壯€鍋撻敐搴℃灍闁绘挶鍎甸弻鏇㈠醇濠靛浂妫ょ紓浣叉閸嬫捇姊绘担鍦菇闁搞劏妫勯…鍥槻闁烩槅鍙冨缁樻媴閻熼偊鍤嬪┑鐐村絻缁绘ê鐣烽幇顑芥斀閻庯綆浜為悾娲⒑閺傘儲娅呴柛鐔稿瀵囧焵椤掆偓閳规垿顢欓弬銈勭返闂佸憡鎸婚惄顖氱暦閹扮増鍊风€瑰壊鍠楃€靛矂姊洪棃娑氬婵☆偅顨婂畷鍛婄節閸ャ劎鍘遍柣搴秵閸嬪懎鐣风仦鐐弿濠电姴鎳忛鐘绘煙閸欏娈滃┑鈥崇埣瀹曘劑顢旈崟顏勵棜闂備礁鎼粔鏌ュ礉鎼淬劌鐓樼€广儱鎳夐弨浠嬫煟濡搫绾ч柟鍏煎姍瀹曞爼骞橀瑙ｆ嫼缂備礁顑嗙€笛冿耿娴煎瓨鐓熸い鎾楀啯鐏嶇紓浣规⒒閸犳牕顕ｉ幘顔碱潊闁抽敮鍋撻柟椋庣帛缁绘稒娼忛崜褏袣濠电偛鎷戠徊鍧楀极椤斿皷妲堥柕蹇ョ磿閸橀亶姊洪崫鍕殜闁稿鎸荤换娑㈡嚑椤掆偓閺嬫稓鈧鍣崑濠傜暦濮椻偓椤㈡岸宕ㄩ鑺ョ彆闂傚倷绀佹竟濠囧磻閸涱垱宕查柛鈩冪☉缁犳椽鏌￠崶銉ョ仾闁抽攱鍨块弻鐔虹矙閹稿孩宕崇紓浣哄У閹稿濡甸崟顖涙櫆閻犲洩灏欐禒顖滅磽娓氬洤鏋︽い鏇嗗洤鐓″璺号堥弸搴ｂ偓骞垮劚鐎氼噣鎯勬惔銊︹拻濞达絽鎲＄拹锟犳煕鎼存稑鈧繂鐣疯ぐ鎺撳仺缂佸娉曢崝锕€顪冮妶鍡楃瑨閻庢艾鍢茶灋闁硅揪闄勯悡鏇㈡煙閻戞ɑ灏繛鎼櫍閺岀喖顢欓懡銈囩厯闂佽鍠曠划娆撳箖閻ｅ苯鏋堝璺虹焸濡嘲鈹戦悩鍨毄闁稿濞€楠炴捇顢旈崱妤冪瓘婵炲濮撮鍛不鐟欏嫨浜滈柟鏉垮閹厧顭胯缁绘繂顫忔繝姘＜婵炲棙鍔楅妶浼存倵鐟欏嫭绀堥柡浣筋嚙閻ｇ兘顢涢悙鏌ユ暅濠德板€愰崑鎾绘煟閵堝鐣洪柡宀嬬到铻ｉ柣鎴炃氶弸娆撴⒑閹肩偛鈧牕煤閺嶎厼鐓橀柟杈鹃檮閸嬫劗鈧娲栧ù鍌炲汲閿熺姵鈷戦柛婵嗗閸ｈ櫣鎲搁弶鍨殻闁炽儻濡囬幑鍕Ω閿曗偓绾绢垶姊虹紒妯碱暡婵炲吋鐟﹂幈銊モ槈閵忊檧鎷哄┑顔炬嚀濞层倝鍩€椤掍礁濮嶇€规洘鍨块獮姗€寮妷锔芥澑闂備焦瀵х粙鎴犫偓姘煎墯缁傚秵绺介崨濠勫幈婵犵數濮撮崯鐗堟櫠閻㈠憡鐓欐い鏂诲妼濞村倿寮崶顒佺厽婵☆垰鐏濋惃铏圭磼濞戞绠绘慨濠冩そ瀹曘劍绻濋崘銊ф▊闂備礁鎲℃笟妤呭垂閻撳宫锝夊箹娴ｅ厜鎷绘繛杈剧悼椤牓藟韫囨稒鐓曢悗锝庝簼椤ャ垻鈧娲戦崡鎶界嵁濡吋宕夐柛婵嗗珔濮樿埖鈷戦梺顐ゅ仜閼活垱鏅剁€涙ɑ鍙忓┑鐘插暞閵囨繄鈧娲橀敃銏ゅ箠閻樻椿鏁嗗〒姘搐閺佸姊婚崒娆掑厡妞ゎ厼鐗撻、鏍幢濞戞顔囨俊銈忕到閸燁偊鎮為崹顐犱簻闁瑰搫妫楁禍鍓х磽娴ｅ搫孝缂佸鎳撻悾鐑藉即閵忕姷顢呴梺璇茬箳缁垰顪冮懞銉ょ箚闁归棿绀侀悡娑樏归敐鍥舵敯缂佽翰鍨藉缁樼瑹閳ь剙顭囪閹囧幢濞存澘娲︾€靛ジ寮堕幋鐙呯串闂備礁澹婇悡鍫ュ磻閸℃瑧涓嶅Δ锝呭暞閻撴洘銇勯幇鍓佹偧缂佺姵锚闇夐柣姗嗗枛閻忣亞绱掔紒妯兼创鐎规洏鍔戦、姘跺幢濮橈絽浜鹃柛褎顨嗛悡娑㈡倶閻愭彃鈷旀繛鎻掔摠椤ㄣ儵鎮欓幖顓犲姺闂佸湱鎳撶€氫即骞冨鍏剧喖姊婚幘顔间粣闂傚倸鍊搁崐椋庢濮橆剦鐒界憸宥堢亱闂佸搫鍟崐濠氭儗閸℃褰掓晲閸ャ劍鐝繛瀛樼矆缁瑥顫忓ú顏呭殥闁靛牆鎳嶅▽顏嗙磽娴ｅ壊鍎忛柣妤佹尭閻ｅ嘲顭ㄩ崘锝嗘杸闁诲函缍嗘禍婵嬫倵椤掑嫭鈷戠紓浣癸供閻掔晫绱掗鍛仸闁糕晜鐩獮瀣晜閽樺鍖栭梻浣规偠閸庤崵寰婂ú顏勭；闁规儳纾弳锕傛煕閵夘垳鍒板ù婊勫劤閳规垿鎮╁畷鍥舵殹闂佺粯鎸诲ú鐔煎箖濮椻偓閹瑩寮堕幋婵喰戦梻浣规偠閸娿倝宕滃顓犫攳?")
        elif review_cadence == "active":
            lines.append("濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮诲☉妯锋婵鐗婇弫楣冩⒑閸涘﹦鎳冪紒缁樺姍濠€渚€姊虹粙璺ㄧ闁告艾顑囩槐鐐哄箣閿旂晫鍘遍梺闈涱焾閸庨亶鍩€椤掆偓濞尖€愁嚕婵犳碍鏅插璺猴功椤旀帡鎮楃憴鍕婵炲眰鍊濆畷顐⒚洪鍛嫼闂佸憡绻傜€氱兘宕曢幇鐗堢厽婵°倓绶″▓姗€鏌熼獮鍨仼闁宠棄顦垫慨鈧柣妯活問閸氬懘姊绘担铏瑰笡闁告梹娲熼、姘额敇閻愨晜鐏侀梺闈涚墕椤︿即鍩涢幋鐐电闁煎ジ顤傞崵娆愵殽閻愭惌娈滈柡宀€鍠栭獮鏍ㄦ媴閾忚姣囬梻浣虹《閺備線宕戦幘鎰佹富闁靛牆妫楃粭鎺楁煕閻樺疇澹樻い顓炴喘楠炲洭顢橀悩娈垮晭闂備礁鎲￠悷銉┧囨潏銊︽珷妞ゅ繐鐗婇崑鍌炴煏閸繍妲归柣鎾崇箻閺屾盯顢曢敐鍥╃暫濡炪們鍎抽崑銈夊蓟濞戞ǚ鏋庨煫鍥ㄦ礈椤斿姊洪棃娑欐悙閻庢矮鍗抽悰顕€骞掑Δ鈧粻锝嗙節閸偄濮冮柣銉邯濮婄粯鎷呴搹鐟扮闂佽鐡曢褏鍙呴梺缁樻⒒閸樠囨嫅閻斿吋鐓ラ柣鏂挎惈瀛濋梺缁樺姇閿曨亪寮婚弴鐔风窞闁割偅绻傛慨搴☆渻閵堝骸澧柣妤佹尭椤繘鎼圭憴鍕彴闂佸搫琚崕鍐茬暦椤忓棛纾藉ù锝堟鐢稓绱掔拠鑼妞ゆ洩绲块幏鐘裁圭€ｎ偒娼旈梻渚€娼х换鎺撴叏閸綆妯勯梺鍝勬湰缁嬫垿鍩ユ径鎰闁绘劗顣介崑鎾绘惞鐟欏嫬鏋戦梺鍝勫暙閻楀棝鎷戦悢鍏肩叆婵炴垶锚椤徰勭箾瀹€濠侀偗闁哄本鐩獮妯侯渻閹规劦鍞归梺绋款儐閹瑰洭鐛幒妤€绠犻柕濞垮劤缁夋椽鏌熼鍛偗鐎规洏鍔戦、娑橆煥閸曨剦鍟屾繝寰锋澘鈧鎱ㄩ悜钘夌；婵炴垶顭傚☉姗嗙叆闁糕晞娉涘ú顓炵暦閿濆棗绶為悗锝庝簻娴煎酣姊绘担鐟邦嚋缂佽鍊块獮濠囧箛椤撶喐鐝烽梺鍝勬储閸ㄦ椽鎮￠崘顔藉仭婵炲棗绻愰鈺呮煟韫囨梹灏﹂柡宀€鍠栭、娆撴偩鐏炴儳娅氶梻浣烘嚀绾绢厽绻涢埀顒併亜閵忊槅娈滈柛鈹惧亾濡炪倖甯掔€氼參宕愰崼鏇熺叆婵犻潧妫Σ褰掓煃闁垮鐏╃紒杈ㄥ笧閳ь剨缍嗛崢鐣屾兜閸撲胶纾奸柣妯诲絻閺嗛亶鏌嶇憴鍕伌妞ゃ垺鐟ч崰濠囧础閻愭惌鍟€缂傚倸鍊峰ù鍥ㄧ椤掑嫬纾婚柣鎰仛瀹曞弶绻濋棃娑卞剰缁炬儳鍚嬬换婵囩節閸屾凹浠惧銈嗘⒐濞叉鎹㈠┑鍡╁殫闂佸灝顑嗙欢鏌ユ煃瑜滈崜姘洪悢鑲╁祦濠电姴鎳愰悿鈧┑鐐村灦閿氶柟顖滃仱濮婃椽宕ㄦ繝鍌毿曢梺鍝ュУ椤ㄥ﹪骞冮敓鐘茬妞ゆ梻鏅崢鍗炩攽閻樼粯娑ф俊顐ｎ殜椤㈡棃鎮介崨濠勫幐闂侀€炲苯澧扮紒杈ㄥ笒铻ｉ柤娴嬫櫓閸熷酣姊绘担绋款棌闁稿鎸剧槐鐐哄幢濡ゅ﹦鍔烽梺褰掑亰閸犳氨澹曢懖鈺冪＝濞达綀顕栭悞鐣岀磼閻橀潧浠遍柡宀€鍠栭、娆撴嚒閵堝洨鍘繝纰樻閸嬪嫰宕锕€鐓″璺好￠弮鍫濈劦妞ゆ帒瀚粻娲倵閿濆骸鏋熼柍閿嬪灴閹綊宕堕鍕缂備胶濮锋晶妤冩崲濞戞埃鍋撳☉娆樼劷妞わ綀灏欑槐鎺楀磼濮樻瘷銏°亜椤撴粌濮傜€规洜鍘ч埞鎴﹀醇濠靛棛顔婇梻鍌氬€风粈渚€骞栭锕€鐤い鎰堕檮閸嬪鏌涢埄鍐槈缁绢厸鍋撻梻浣筋潐閸庡吋鎱ㄩ妶澶嬪亗闁绘柨鍚嬮悡娆撴⒑椤撱劎鐣卞褌鍗抽弻宥囨嫚閼碱剛浼囩紓浣介哺閹告悂顢樻總绋跨妞ゆ挾濮峰畷鏌ユ⒒娴ｈ櫣甯涘〒姘殜瀹曟娊鏁愰崨顖涙闂佸壊鍋呭ú锕傚极閸℃鐔嗛悹杞拌閸庢劖绻涢崨顔惧⒌婵﹦绮幏鍛存偡闁箑娈濈紓鍌欐祰椤曆囧磹濮濆瞼浜辨俊鐐€栭幐鍫曞垂瑜版帗鍊块柛顭戝亖娴滄粓鏌熼崫鍕棞濞存粍鍎抽—鍐Χ韫囨洜鏆㈡繛瀛樼矤閸撴瑥宓勯梺鍦濠㈡绮绘繝姘仯闁搞儺浜滈惃娲煥濞戞瑧鐭婇柍瑙勫灴閹瑩宕ｆ径妯伙紒闂備礁鎲″褰掋€冩繝鍐х箚闁割偅娲橀崑瀣煕椤愶絿鐭岀紒鐘冲哺濮婅櫣绱掑Ο鍝勵潓闂佸鏉垮缂佽京鍋ら獮瀣晜閻ｅ苯骞嶉梻浣稿悑娴滀粙宕曢幎鑺ュ剹闁圭儤鎼╁▓浠嬫煟閹邦厽缍戦柣蹇旀綑閳规垿顢欓悷棰佸闂傚倷绶氬褔鎮ч崱娑樼疇婵せ鍋撶€规洦鍓涢幑鍕偘閳╁啯鏉搁梻浣虹帛椤牏浜稿▎鎰浄婵炴垯鍨洪悡鏇㈡煛閸愶絽浜惧┑鐐插级閻楃娀宕洪姀銈呯閻犲洤寮埡鍛厓闁告繂瀚埀顒傛暬楠炲繘宕崟銊︽杸濡炪倖姊婚崑鎾诲吹閳ь剙鈹戦悙鑼勾闁稿﹥绻堥獮鍐潨閳ь剟銆佸▎鎰弿闁归偊浜為惄搴繆閻愵亜鈧牠骞愭ィ鍐ㄧ；闁绘柨鎲″▍鐘绘煥閺囩偛鈧綊鎮″▎鎰╀簻闁哄啠鍋撻柛搴ゆ珪缁傛帗娼忛埞鎯т壕閻熸瑥瀚粈鈧紓鍌氱Т閿曨亪濡存笟鈧鎾閳ュ厖姹楅梺鍝勵槸閻楀啴寮插┑鍡忔灃闁秆勵殕閳锋帡鏌涚仦鍓ф噯闁稿繐鐭傞弻鐔兼惞椤愶絽纾冲Δ鐘靛仦閻楃娀銆侀弴銏犖ч柛銉㈡櫇閸樼娀姊绘担铏瑰笡闁搞劎鍘ц灋闁告洦鍘鹃惌鍡涙煕鐏炴儳顥氶柛瀣崌瀹曟寰勬繝浣割棜闂傚倷绀侀幉鈥趁洪敃鍌氱婵せ鍋撴鐐茬箲缁绘繂顫濋娑欏闂備礁鎲＄粙鎴︽晝閵夛箑绶為柛鏇ㄥ灡閻撴洟鎮楅敐搴濈盎妞ゅ浚鍘介妵鍕閳╁喚妫冨銈冨灪閿曘垺鎱ㄩ埀顒勬煥濞戞ê顏╂鐐村姍閺岋絾鎯旈垾鍐茶緟闂佺顑嗛幑鍥箖濡ゅ懏鏅查幖绮光偓鎰佹骄闂備礁鎼Λ娑欑箾閳ь剟鏌＄仦鐔峰椤曡鲸绻涢崱妯虹仴闁糕晛鐭傚娲濞戞瑯妫￠柣銏╁灡鐢繝鏁愰悙娴嬫斀閻庯綆鍋勬禍妤呮煙閼圭増褰х紒鎻掋偢閹姤绻濆顓涙嫼闁哄鍋炴竟鍡浰囬敃鍌涚厽婵°倓鐒︾亸顓熴亜椤愩垻绠茬紒缁樼箓椤繈顢楅崒锔惧簥濠电姵顔栭崰妤呪€﹂崼銉ョ；闁圭増婢橀惌妤呮煛閸ャ儱鐏柍閿嬪灴閺屾稑鈽夊鍫熸暰闂佽鍨伴悧蹇曟閹烘鍋愰柧蹇ｅ亜绾板秹姊烘导娆戝埌闁搞垺鐓￠垾锕傚Ω閳轰線鍞堕梺缁樻濞撳湱鑺辩拠娴嬫斀闁绘绮☉褔鏌涙繝鍐╁€愰挊婵囥亜閺嶃劌鐒归柡瀣閺屾洘绻涢悙顒佺彆闂佹娊鏀遍崹鍧楀蓟濞戙垹绠婚柡澶嬪灩缁侀攱绻涚€涙鐭嬬紒璇插暟閹广垹鈽夐姀鐘电厬婵犮垼娉涢懟顖炲煕瀹€鍕拺閻犲洠鈧櫕鐏€闂侀€炲苯澧柡瀣帶鍗遍柛顐犲劜閻撳繘鐓崶銉ュ姢缁炬儳娼￠弻娑橆潨閳ь剚绂嶉崼鏇炶摕闁挎繂鐗忛悿鈧梺鍝勬川閸嬫鍒掗懜鐢电瘈闁冲皝鍋撻柛灞剧矌閻撴捇姊虹拠鈥崇仩闁活剙銈搁崺鈧い鎺戯功缁夌敻鏌涢悩鎰佹疁闁诡噯绻濆鎾閿涘嫬寮虫繝鐢靛█濞佳兾涘Δ鍛辈婵炲棙鎸婚悡鏇㈡煛閸屾繍鍤欓柍褜鍓氶〃鍫澪ｉ幇鏉跨闁规儳顕粔鍫曟⒑闂堟侗鐓紒鐘冲灴濡嫬顓兼径瀣ф嫼闂佽崵鍠愬妯何ｆ繝姘厵闁惧浚鍋勬慨宥嗩殽閻愬樊妯€妤犵偞锕㈤、娆撴嚃閳哄﹥效闂傚倷绶氬褔鈥﹂鐘典笉闁硅揪瀵岄弫鍌炴煙闂傚鍔嶉柍閿嬪浮閺屾稓浠﹂崜褎鍣銈忚闂勫嫮鎹㈠┑瀣劦妞ゆ帒瀚悞鑲┾偓骞垮劙鐠佹煡宕戦幘缁樻櫇闁稿本宀搁崬鍫曟⒑闂堟侗妲堕柛搴㈠▕瀵宕奸妷锔规嫼缂備礁顦Λ妤冣偓姘槻閳绘捇寮撮姀锛勫幈闁诲函鎬ラ崟顒傚絿闂備線鈧偛鑻晶浼存煙閾忣偅灏甸柍褜鍓氶惌顕€宕￠崘鑼殾闁瑰鍋熺弧鈧梺绋胯閸婃宕濋悜鑺モ拺闁告劕寮堕幆鍫ユ煙閸愯尙绠荤€规洘鍨块弫鎰板川閸屾稒顥堥柡浣稿€块幐濠冨緞濡儤鐤傚┑锛勫亼閸婃洜鎹㈤幒鎾剁闁逞屽墴閺岋紕浠﹂崜褎鍒涢悗娈垮櫘閸ｏ綁鐛鈧畷婊勬媴鐟欏嫷鍟呮繝纰夌磿閸嬫垿宕愰妶鍡欘洸婵犲﹤鐗嗛悿顕€鎮楀☉娅偐鎹㈤崱娑欑厱妞ゆ劧绲剧粈鈧Δ鐘靛亼閸ㄧ儤绌辨繝鍥ч柛娑卞幗濞堝爼姊洪悷鏉挎毐婵☆偅绻傞～蹇涙惞鐟欏嫬鐝伴梺鍦帛鐢晠宕濇径鎰拺闁告稑锕ら悘銉х磽瀹ュ拑宸ラ柣锝呭槻椤劑宕橀敐鍡╂綌婵犳鍠楅敃鈺呭礈濞嗘挻鍊跺┑鐘叉处閳锋垿鏌涢幘鏉戠祷濞存粍鐗犻弻娑欐償閵娿倖鍠氶梺缁樹緱閸ｏ絾鎱ㄩ埀顒勬煃閵夈劌鐨虹紒鐘宠壘椤啴濡堕崱娆忣潷缂備浇顕х粔鐟扮暦闂堟稈鏋庨柟瀛樻煥娴滅偓绻涢崼婵堜虎闁哄鐩弻锝堢疀閺冨倻鐤勯梺绯曟櫇閸嬨倝鐛€ｎ喗鏅濋柍褜鍓熼幃锟犳晸閻樺磭鍘遍梺鏂ユ櫅閸犳艾鈻撳Ο濂藉綊鎮╅锝嗙彋濠殿喖锕ュ钘夌暦閻戠瓔鏁囨繛鎴炵懃閻濋亶姊绘担渚劸妞ゆ垵鎳橀弫鍐敂閸涱剛绠氶梺鍦檸閸犳牜澹曢崗鍏煎弿婵☆垰娼￠崫鐑樼箾閸儳鐣烘慨濠冩そ楠炴牠鎮欓幓鎺懶ョ紓鍌欐祰鐏忣亝鎱ㄩ妶鍥╃焿鐎广儱妫庨崑鍛存煕閹般劍娅呭ù鐙€鍘奸埞鎴︽倷閸欏妫炵紓浣虹帛閸旀瑩銆侀弮鍫晜闁糕剝鐟ч敍婊堟倵閸忓浜鹃梺鍛婂姀閺呮繈濡存繝鍕＝濞达絼绮欓崫娲煙閸涘﹥鍊愭い銏∩戠缓鐣岀矙鐠侯煈妲规俊鐐€栭幐鐐叏瀹勬壆鏆﹂柛娆忣槷缁诲棝鏌曢崼婵囨悙閸熸悂姊虹粙娆惧剱闁烩晩鍨伴悾鐑筋敍閻愯尙顔呴梺鑺ッ敍澶愭晝閸屾稓鍘甸梺缁橆殔閻楀﹦娆㈤懠顒傜＜闁绘ê鍟块埢鏇㈡煛瀹€鈧崰鎾诲焵椤掑倹鏆╂い顓炵墕閻☆參姊绘笟鈧埀顒傚仜閼活垱鏅舵导瀛樼厱閻庯絻鍔岄埀顒佹礋閿濈偠绠涢幘浣规そ椤㈡棃宕熼褍鏁归梻浣侯攰閸嬫劗鎮伴妷鈺佺疇闁搞儺鍓欑粻顖氣攽閻樺磭顣查柍閿嬪灴閺岀喖顢涢崱妤佸櫧妞ゆ柨娲︽穱濠囧Χ閸ヮ灝銉︺亜椤撶偟澧曢柣锝囨暬瀹曠喖顢曢锝呯槣闂備線娼ч悧鍡椢涘▎鎴濐棜闁汇垹鎲￠悡鏇㈡倵閿濆骸浜濋悘蹇庡嵆閺岀喐绗熼崹顔碱瀴缂備胶绮换鍫濈暦閻旂⒈鏁冮柕蹇曞閻庨亶姊绘担绛嬪殭婵炲鍏樺顐﹀箹娴ｇ鍋嶉悷婊勬瀹曟椽濮€閳╁啫鍔呴梺闈涱焾閸庢娊顢樺ú顏呪拺缂備焦銆為幋锔芥櫇妞ゆ劑鍊楃粈濠偯归敐鍛棌婵炲吋鐗楃换娑橆啅椤旇崵鐩庨悗鐟版啞缁诲倿鍩為幋锔藉亹闁圭粯甯楀▓顓㈡⒒閸屾凹妲哥紒澶婂濡叉劙骞樼€涙ê顎撻梺鍛婃尰瑜板啴宕滈柆宥嗙厽闁靛繆鏅涢悘锝夋煕鐎ｎ剙鏋涚€规洘宀搁獮鎺楀棘閸濆嫪澹曢梺鎸庣箓缁ㄥジ骞夋ィ鍐╃厱婵﹩鍓﹂崕蹇斻亜椤撯剝纭堕柟鐟板閹噣寮堕幋婊呯煑缂傚倸鍊烽悞锕傚礉閺嶎偆鐭欓柟鐑樻⒐瀹曞弶绻濋棃娑卞剱闁稿鍔戝濠氬醇閻斿嘲鐎梺闈涚箞閸婃牠鎮￠弴銏＄厽闁哄啫鍋嗛悞鐐亜閵夈儺鍎戠紒杈ㄥ浮椤㈡瑩鎳為妷顔筋棃闁诲氦顫夊ú鏍Χ缁嬫鍤曢柟缁㈠枟閸嬪嫰鏌涘▎蹇ｆЦ妞ゅ繐缍婂濠氬磼濞嗘埈妲梺纭咁嚋缁绘繂鐣峰┑瀣嵆闁绘垵妫楀▓銊╂⒑閸撴彃浜濇繛鍙夌墱缁顫濋懜鐢靛幈濡炪倖鍔楁慨鎾礉濠婂牊鐓熼柟鎯х摠缁€鈧梺瀹狀潐閸ㄥ潡骞冮埡鍛闁圭儤鎸婚澶愭⒒娴ｄ警鐒鹃柨鏇樺劦瀹曟繂鈻庨幘瀹犳憰闂佺粯姊婚埛鍫ュ极鐎ｎ喗鐓曢柍鈺佸暟閹冲懘鏌ｉ敃鈧悧鎾诲箖濡も偓閳绘捇宕归鐣屼憾闂備胶鎳撻幉鈩冪箾婵犲洨宓侀柛鎰靛枛閻撴盯鏌涘☉鍗炴灈濞寸姾娅ｇ槐鎺楁倷椤掍胶鍑″銈忕畵娴滆泛顫忔繝姘兼晬闁绘劗琛ラ幏濠氭⒑缁嬫寧婀伴柣鐔村姂瀹曟浠︽穱鍙樼盎濡炪倖鎸鹃崑鐔告櫠閿旈敮鍋撳▓鍨灓闁轰礁顭烽妴浣肝旈崨顓狀槹濡炪倖宸婚崑鎾趁归悪鈧崣鍐箖瀹勯偊鐓ラ柛鎰典簽椤旀帒螖閻橀潧浠滅紒缁樺浮楠炲骞橀鑲╊槹濡炪倖鍔﹂崑鍕枔婵傚憡鈷戦悹鍥ㄥ絻椤掋垻绱掔€ｎ偄娴柍銉畵瀹曞爼顢楅埀顒勫磼閵娾晜鐓曟俊銈呭暙娴滃綊鏌￠埀顒佺鐎ｎ偆鍘介梺褰掑亰閸撴瑧鐥閵囧嫰濡烽敂鍓х厒缂備浇椴哥敮鐐垫閹烘嚦鐔煎传閸曞灚缍掗梺璇插椤旀牠宕伴弽顓炵柈闁秆勵殔閻撴繈骞栧ǎ顒€濡肩紒鐘差煼閹鈽夊▍顓т簻閳绘挸鈻庨幘绮规嫽婵炶揪缍€濞咃絿鏁☉銏＄厱闁哄啠鍋撴い銊ワ工閻ｇ兘寮撮姀鐘栄冾熆鐠轰警鍎忓ù婊勵殔閳规垿鎮欓崣澶樻！闂佹悶鍔屽﹢杈ㄧ珶閺囥垺瀵犲瑙勭箓缂嶅﹪寮幇顓炵窞閻庯綆鍋婇弫顏堟⒒娴ｇ瓔鍤欑紒璇叉瀵煡鎮╃拠鑼舵憰闂佹寧绋戠€氀囧磻閹剧粯鏅查幖绮光偓鎰佹交闂備礁鎼鍡涙儎椤栫偛钃熼柨娑樺濞岊亪鏌涢幘妞捐閸嬫捇骞掑Δ浣哄帗閻熸粍绮撳畷婊堝Ω瑜忕粈濠囨煕閳╁啰鈽夌痪鎯ь煼閺屾盯鍩勯崘顏呭櫘婵炴垶鎸哥粔褰掑蓟閳ユ剚鍚嬮幖绮光偓宕囶啈闂備胶绮幐鍝ユ崲濮椻偓瀵鈽夐姀鐘栥劑鏌熺€涙绠撻柡瀣ㄥ€曢湁闁绘挸楠搁弳锝夋煙椤旂瓔娈旈柍缁樻崌瀹曞綊顢欓悾灞肩敖缂傚倸鍊风欢锟犲窗濡ゅ懏鍋￠柨鏃傛櫕閳瑰秴鈹戦悩鍙夋悙缂佺姷鎳撻湁闁挎繂鎳忛幉鎼佹煕婵犲嫬浠辨慨濠冩そ濡啫鈽夋潏鈺佸Ъ闂備胶顭堥柊锝嗙閸洜宓佹俊銈呮噺閸嬨劑鏌涘☉姗堝伐闁?")
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
            return "濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮诲☉妯锋婵鐗婇弫楣冩⒑閸涘﹦鎳冪紒缁橈耿瀵鏁愭径濠勵吅濠电姴鐏氶崝鏍礊濡ゅ懏鈷戦梺顐ゅ仜閼活垱鏅堕鈧弻娑欑節閸屾稖纭€缂備緡鍠栭澶愮嵁閹烘妫橀柛婵嗗婢规洟姊洪幐搴ｇ畵缂併劏鍋愰懞杈ㄧ鐎ｎ偆鍘遍梺鍝勫暞閹搁箖鎮炬潏銊ｄ簻妞ゅ繐瀚弳锝呪攽閳ュ磭鍩ｇ€规洖宕灃闁逞屽墮椤洭骞嬮敂瑙ｆ嫼缂備礁顑嗛娆撳磿閹扮増鐓欓柣鐔哄閸犳鈧鍠涢褔鍩ユ径鎰潊闁炽儱鍘栫花濠氭⒒閸屾瑧顦﹂柣蹇旂箞椤㈡牠宕ㄩ缁㈡祫闂佸湱铏庨崰妤呭煕閹寸姷纾兼い鏍ㄧ⊕缁€鍐煛婢跺﹦绉洪柡灞剧〒閳ь剨缍嗛崑鍛焊椤撶喆浜滄い蹇撳閺嗭絽鈹戦垾宕囧煟鐎规洖宕灃闁逞屽墮椤洭骞嬮敂瑙ｆ嫼缂備礁顑嗛娆撳磿閹扮増鐓欑紒瀣仢閳锋梹淇婇崣澶婂妤犵偞锕㈤獮鍥ㄦ媴閸涘﹤鈧垶姊绘担鍛婂暈缂侇喖鐭傚畷顖炲箮閽樺袝濡炪倖鍔忛幊锟犲籍閸喎浜归梻鍌氱墛缁嬫劗鍒掗崼鏇熲拺闁告縿鍎卞▍蹇涙煕鐎ｎ亶妯€闁诡喗锕㈤獮鎺懳旀担鍝勫箺闂備胶绮敋鐎殿喖澧庣划姘跺锤濡や礁鈧爼鐓崶銊︹拻闁瑰啿鎳愮槐鎺楊敋閸℃瑧袦闂佽鍠楅悷鈺呭箖濠婂吘鐔兼偂鎼达紕顔戦梻鍌欒兌閹虫捇宕ョ€ｎ喖绠氱€光偓閸曨偄鐎悗瑙勬礀濞层劑鎯岄幘缁樼厽闁靛繒濮甸崯鐐烘煟閹惧瓨绀嬮柟顔筋殜閺佹劖鎯斿┑鍫㈡晨婵＄偑鍊曞ù姘跺储娴犲桅闁告洦鍨伴～鍛存煃閳轰礁鏆欑痪鎯у暱铻栭柣姗€娼ф禒锔姐亜椤撶偞宸濇俊鍙夊姍楠炴帡骞婂畷鍥ф灈闁哄被鍔庨埀顒婄秵娴滆埖瀵奸弽顐ょ＝闁稿本鑹鹃埀顒佹倐瀹曟劙骞栨担鍝ワ紮闂佺粯鍨兼慨銈夊磹閸ф鐓ラ柡鍥╁仜閳ь剙缍婂鎻掆攽鐎ｎ偆鍘撻梺鍛婄箓鐎氼參宕冲ú顏呯厱濠电姴鍊归崑銉╂煛瀹€鈧崰鏍€佸☉銏℃櫜闁搞儻闄勯惈蹇涙⒒娴ｈ棄鍚归柛鐘崇墵瀹曟垶绻濋崶銊ヤ簵闂侀潧顦弲娑氱不閸︻厾纾兼い鏃傚帶鐢劑鏌涚€ｎ偅宕岀€殿噮鍓熸俊鐑芥晝閳ь剟顢旈埡鍌滅瘈缁炬澘顦辩壕鍧楁煕鐎ｎ偄鐏寸€规洘鍔欓獮瀣晝閳ь剟宕归崒鐐寸厱婵犻潧妫楅悵瀣箾閹存瑥鐏╃紒鈧崘鈹夸簻闁哄啫娲らˉ宥夋煙閼恒儲绀嬫慨濠呮閸栨牠寮撮悙娴嬫嫟婵＄偑鍊戦崝宀€鎹㈠Ο铏规殾闁靛／鈧崑鎾绘晲鎼粹剝鐏嶉梺缁樻尰濞茬喖寮诲澶婄厸濞达絽鎲″▓鍫曟⒑閻熸澘鏆遍柛鐕佸灦閵嗗啴濡烽埡鍌氣偓鐑芥煠绾板崬澧柍顏堟涧閳规垿顢欑涵宄板缂備緡鍣崹鍫曠嵁韫囨稑宸濋柡澶嬪灥缁愭稒绻濋悽闈浶㈤柛鐕佸亰瀹曟粓鎮介崨濞炬嫽婵炶揪绲肩拃锕傛倿妤ｅ啯鐓ラ柡鍥朵簽閹ジ鏌涢幒鎾崇瑨闁宠閰ｉ獮姗€骞嶆担闀愬婵炶揪绲芥竟濠傤焽閳哄懏鐓欏Λ棰佽兌閸斿秴顫㈤崶銊х瘈闁汇垽娼ч崜宕囩磼閼艰埖顥夐悡銈夋煏閸繍妲归柡鍛箖閵囧嫯绠涢幘璺侯暫缂備胶濮靛姗€鍩為幋锔藉亹闁圭粯甯楀▓顓犵磽娴ｇ顣抽柛瀣仦缁岃鲸绻濋崶鑸垫櫖濠电姴锕ら崯顐ｇ濮椻偓濮婄儤娼幍顔煎闂佽鍠栭崐鍨嚕婵犳碍鏅插璺侯儏娴滄粓姊洪崨濠勭細闁稿孩濞婇幃锟犲焵椤掍胶绡€闁汇垽娼ф禒婊勩亜閺囥劌寮€规洘顨呰灒闁惧繗顫夊▓鎯р攽椤旂瓔鐒炬繛澶嬬〒缁鎼归锛勭畾闂侀潧鐗嗛崐鍛婄閸撗呯＝濞达絽鎼瀷閻庤娲滈弫濠氬春閳ь剚銇勯幒鎴濇灓婵炲吋鍔栫换娑㈠矗婢跺苯鈪归柣鎾卞€濋弻銊╁即濡も偓娴滈箖姊哄畷鍥╁笡闁圭顭锋俊鍫曟晲婢跺﹦顦ㄩ梺鍐叉贡閸嬫挾鈧艾銈稿缁樻媴閸涘﹨纭€濡炪値鍘奸悧鍡涙箒婵＄偛顑呭ù閿嬬▔瀹ュ鐓欓柣鎰靛墰閺嗘ê霉濠婂嫮鐭掗柡灞诲姂瀵噣宕剁捄鐑橆唲闂備浇顕ф蹇曠不閹捐钃熼柨娑樺濞岊亞绱掑☉姗嗗剰闁告挸鐖奸幃妤冩喆閸曨剛顦ラ梺缁樼墪閸氬绌辨繝鍌ゆ桨鐎光偓婵犲唭顒勬⒒娴ｉ涓茬紒鐘冲灴閹囧箻閹颁焦缍庢繝鐢靛У閼瑰墽澹曢崗鍏煎弿婵☆垰鎼懜瑙勩亜閵堝倸浜剧紓鍌氬€搁崐椋庣矆娓氣偓椤㈡牠宕卞▎鎰闂傚嫬娲よ灋闁靛繒濮弨浠嬫煟濡鍤嬬€规悶鍎甸弻锝呂旈埀顒勬晝椤忓牆绠栭柨鐔哄У閸嬫劗绱撴担璇＄劷闁告妫勯埞鎴炲箠闁稿﹥鍔欏畷鎴﹀箻缂佹鍘藉┑掳鍊愰崑鎾翠繆椤愶絿绠為柕鍡曠椤繈顢楁径灞藉汲闂備礁鎲℃笟妤呭垂閹惰姤鏅繝濠傛噽绾句粙鏌涚仦鍓ф噮闁告柨绉甸妵鍕敇閻愭潙鏋犻梺绯曟櫅閿曨亜顕ｉ幘顔藉亜闁惧繗顕栭崯搴ㄦ⒒娴ｈ櫣甯涢柟鍝ヮ焾闇夊瀣捣娑撳秹鏌ゆ慨鎰偓鎰板磻閹捐埖鍠嗛柛鏇ㄥ墰椤︺劎绱撴笟鍥ф灈缂佺粯顭堝Λ鐔兼⒑閸濆嫯顫﹂柛搴㈢叀閹繝寮撮姀锛勫帗闁哄鍋炴竟鍡涘礉瀹ュ棛绡€闁逞屽墴瀵埖绔熼崘鏌ュ弰鐎规洘鍎奸¨鍌炴椤掑澧柍瑙勫灴閸ㄦ儳鐣烽崶褏鍘介柣搴ゎ潐濞叉牠鎮ユ總绋跨伋闁哄稁鍙庨弫濠囨煕濠靛棗顏ù鐓庡缁辨挻鎷呮禒瀣懙闁汇埄鍨抽崑鐔肺ｉ幇鏉跨闁瑰啿纾崰鏍箹瑜版帒鎹舵い鎾跺枎濞呮瑩姊婚崒娆戭槮闁硅绻濋妴鍐╃節閸愵亶娲搁梺鍓插亝濞叉牠鎷戦悢鍏肩厽闁哄倸鐏濋幃鎴︽煟閹哄秶鐭欓柡灞诲姂瀵潙螖閳ь剚绂嶆ィ鍐┾拺闁告稑顭€閹达箑绠伴柟鎯版閽冪喖鏌ㄩ悢鍝勑㈤柣鎺戠仛閵囧嫰骞掑鍫濆帯濡炪倐鏅濋崗姗€骞冨Δ鍛櫜閹肩补鈧尙鏁栭梻浣告啞閿氱€规洦鍓熼垾鏃堝礃椤斿槈褔鏌涢埄鍐炬當鐞涜偐绱撻崒娆戝妽鐟滄澘鍟…鍥晸閻樿尙鐣鹃柣蹇曞仧閺咁偊寮抽崱娑欑厱闁哄洢鍔屾晶浼存煕濮椻偓娴滆泛顫忛搹瑙勫枂闁告洦鍋勬慨銏ゆ倵鐟欏嫭澶勯柛鎾村哺楠炲牓濡搁埡浣猴紲闂佺粯鍔曢顓㈠储閹间焦鐓熼煫鍥ㄦ礀娴犙勩亜椤撶偟澧涢柡鍛埣閹崇娀顢栭挊澶夊闂佸壊鐓堥崑鍛閺屻儲鍊垫慨妯煎帶楠炴﹢鏌熼獮鍨仼闁宠鍨归埀顒婄秵娴滅偤藝閺夋娓婚柕鍫濇婵箓鏌涚€ｎ亝鍣归柍缁樻尰缁轰粙宕ㄦ繛鐐闂備胶顭堥張顒勬偡瑜旇棟闁挎洖鍊归悡娆戠棯閺夊灝鑸瑰ù婊呭椤ㄣ儵鎮欑拠褔绶寸紓浣哄У閻╊垰顕ｉ幘顔藉€烽柤纰卞厸閸犲﹪姊绘担鐑樺殌闁告艾顑夐幃楣冾敂閸繄顦悗骞垮劚椤︻垳澹曢崹顕呯唵閻犺桨璀﹂崕宥吤瑰鍕煉闁绘搩鍋婂畷鍫曞Ω閿曗偓閺嗘绻濋埛鈧崶锔藉枤闂佸搫澶囬崜婵嬪箯閸涙潙浼犻柕澶嬪壃閸ャ劎鍘搁悗鍏夊亾閻庯綆鍓涜ⅵ婵°倗濮烽崑娑樏洪顫偓浣肝旀担鍝ョ獮婵犵數濮撮崰姘跺疮閳ь剟姊婚崒姘偓椋庣矆娓氣偓楠炲鏁撻悩顐熷亾閿曞倸鐐婃い鎺嗗亾闁哄绶氶幃褰掑炊瑜庨埢鏇熺箾閸忚偐澧甸柡灞熷棛鐤€婵ê鍚嬬紞鍫ユ煟鎼淬垻顣茬€光偓閹间礁钃熺€广儱顦敮闂侀潧顦崕鎻捫掗幇顔剧＝濞达絽鎼牎濠碉紕鍋樼划娆忣嚕婵犳碍鏅插璺侯煬濞煎﹪姊虹€圭姵銆冮柤瀹犲煐缁傛帡顢橀姀锛勫幗闂侀潧绻嗛弲娑㈡倶濞嗘挻鐓冪憸婊堝礈濞嗘垵顥氭い鎾卞灩濮规煡鏌ㄩ弮鍌涙珪缂佲檧鍋撻梻鍌氬€搁悧濠勭矙閹烘鏅€广儱顦伴悡鐔兼煙閹冭埞闁告棑绠撻弻锛勪沪閸撗勫垱濡ょ姷鍋涘ú顓炵暦濠婂嫭濯撮柤浠嬫敱閸ㄥ灝顫忓ú顏勪紶闁告洦鍋€閸嬫捇鎮界粙璺紱闂佺懓澧界划顖炲煕閹烘鐓曢悘鐐插⒔閹冲棝鏌涜箛鎾剁劯闁哄本绋撻埀顒婄祷閸斿本鎱ㄩ崒婧惧亾鐟欏嫭绀冩繛鑼枎椤曪綁宕奸弴鐐殿吅闂佸搫鍟犻崑鎾绘煟鎼淬垺銇濇慨濠冩そ瀹曨偊宕熼鈧崑宥夋⒑閹肩偛濡肩紓宥咃躬楠炲啴宕稿Δ濠冩櫔闂侀€炲苯澧寸€殿喖顭烽弫鎰緞婵犲嫮鏉告俊鐐€栧濠氬储瑜庢穱濠偯洪鍛嫼缂傚倷鐒﹁摫閻忓繋鍗抽弻锝夋偄濠靛棙鎼愰柣鎺戠仛閵囧嫰骞掗幋婵冨亾瑜版帒鍚归柍褜鍓熼弻锝嗘償閵忕姴姣堥梺鍝ュУ椤ㄥ﹤顕ｉ懠顒佸磯濞达絾娲樺Λ鍐ㄧ暦閵娾晩鏁囬柣鎰綑閸旀帡姊婚崒娆戝妽闁诡喖鐖煎畷鏇灻洪鍕槶濠殿喗顭堥崺鏍磻閸屾稓绠鹃柛鈩兠慨鍌毭瑰鍕煉闁哄矉绻濆畷姗€濡搁敂淇卞亹婵犵數鍋涢崥瀣礉閺嶎偅宕叉繛鎴欏灩瀹告繃銇勯幘鍗炲闁轰焦鍎抽—鍐Χ閸愩劌惟闂佺娴烽弫濠氱嵁閸愩劉鏋庨柟瀛樻煥娴滅偓绻涢幋鐑嗕痪妞ゅ繐妫楅ˉ姘舵煕閹邦剙妫橀柡鍐ㄧ墛閸嬫劙姊婚崼鐔衡棩婵炲矈浜弻锝夊閳轰胶浼堢紓浣虹帛缁诲牓骞冩导鎼晩闁搞垹顦遍崰鏍х暦濡ゅ懏鍋傞幖杈剧秶缁扁剝绻濆閿嬫緲閳ь儸鍥ㄢ挃闁告洦鍨奸弫鍕箾閸℃ɑ灏柤绋跨秺閹嘲鈻庤箛鎿冧紑缂備讲妾ч崑鎾绘⒒娴ｅ湱婀介柛銊ㄦ椤洩顦查柡鍡忔櫊濮婄粯鎷呴懞銉ｂ偓鍐磼閳ь剚绗熼埀顒勭嵁婢舵劖鏅搁柣妯垮皺閻ゅ嫰姊洪棃娑辩叚缂佺姵鍨块、姘舵焼瀹ュ棛鍘告繝銏ｆ硾椤戝懘鎮橀妷鈺傜厽閹兼惌鍠栧顔芥叏婵犲懏顏犵紒杈ㄥ笒铻ｉ悹鍥皺椤ｈ尙绱撻崒娆撴闁告柨鐭傞幃銉╂偂鎼搭喖娈ㄩ梺褰掓？缁€渚€宕橀埀顒勬⒑闂堟丹娑㈠椽娴ｅ憡娅楅梻鍌氬€烽懗鍫曞箠閹炬椿鏁嬫い鎾卞灩绾惧鏌熼柇锕€鍔︽繛鎴欏灩鎯熼梺鎸庢煥婢т粙顢欓弴銏″€甸柣鐔告緲椤ュ繘鏌涢悩铏闁奸缚椴哥缓浠嬪川婵犲嫬骞愰梻浣告啞娓氭宕板杈╀笉闁绘劗鍎ら悡娑㈡倶閻愭彃鈷旈柕鍡樺笒闇夐柣娆忔噽閻ｇ數鈧娲樼划蹇浡ㄦ笟鈧弻锟犲幢椤撶姷鐦堝┑顔硷龚濞咃綁骞忛悩璇茬闁圭儤姊硅ⅷ闂傚倷绀侀幉锟犲箰鐠囧樊娼╅柕濞炬櫅缁犳煡鏌曡箛鏇炐涢柡鈧禒瀣€甸柨婵嗛娴滆姤淇婇銏犳殭闁宠鍨块幃娆撳级閹寸姳妗撻梺鑹帮骏閸婃繈寮诲☉姘ｅ亾閿濆骸浜濈€规洖鏈〃銉╂倷鐎电顫ч梺鐟板槻閹虫ê鐣烽锕€唯鐟滃酣鎮楅锔解拻闁稿本鐟︾粊鐗堢箾婢跺绀嬬€规洑鍗抽獮妯尖偓娑櫭鍧楁煟鎼达絾鏆╂い顓炵墦钘熸慨妯垮煐閸嬶綁鏌熼鐔风瑨濠碉紕鍏橀弻娑氣偓锝庡亝瀹曞矂鏌ｅ☉鍗炴珝鐎规洖缍婇、娆撴偂鎼搭喗缍撴繝纰夌磿閸嬫垿宕愯缁辨挸顫濈捄铏诡攨闂佽鍎煎Λ鍕不閺嶎厽鐓ラ柣鏂挎惈瀛濋梺鍛婎殕婵炲﹪寮婚弴锛勭杸闁靛／鍜冪吹闂備礁鎲¤摫闁诡喖鍊搁～蹇撁洪鍕啇闂佺粯鍔栬ぐ鍐╂叏瀹€鍕拺缂佸瀵ч崬澶婎渻閺夋垶鍟炵紒宀冮哺缁绘繈宕橀鍫燁€嶉梻浣告啞缁嬫垿鏁冮敃鍌氬偍濞寸姴顑嗛ˉ濠冦亜閹扳晛鐏璺哄缁绘盯宕ｆ径灞解吂闂佺儵妲呴崣鍐潖婵犳艾纾兼慨姗嗗幗閹瑥顪冮妶蹇涙濠㈢懓妫濋獮鎴﹀閻橆偅鏂€闂佹悶鍎弲婵嬫儊閸儲鈷戠紒瀣濠€浼存煕閹达綆娼愰悗闈涖偢閸┾偓妞ゆ帒鍊荤壕浠嬫煕鐏炲墽鎳嗛柛蹇撹嫰閳规垿顢欓悙顒佹瘓濡ょ姷鍋為崹鍨暦閸洦鏁嗛柍褜鍓熼幏鎴︽偄鐞涒€充壕妤犵偛鐏濋崝姘亜閿旇棄顥嬮柍褜鍓涢弫鍛婃叏閹绢喒鈧箓宕稿Δ浣告疂闂佹椿鍓︽禍婵嬪垂閸ф鏄ラ柕蹇嬪€曢柋鍥ㄧ節閵忊晙绨兼俊顐㈠暣楠炲啴鍩￠崨顕呮濠电偞鍨堕〃鍡涘礋閸愵喗鈷掑ù锝囨嚀椤曟粍绻涢幓鎺旂鐎规洝顫夌粋鎺斺偓锝庘偓顓滃劚闇夐柨婵嗘川閵嗗﹥淇婇幓鎺斿闁逛究鍔岃灃闁逞屽墮铻炴繛鍡樻尭绾句粙姊婚崼鐔剁繁婵炴挸顭烽弻鏇㈠醇濠靛浂妫炴繝娈垮枛閸婂潡寮诲☉銏犵厸濞达絽澹婃禒濂告煣閼姐倕浠︾紒缁樼箖缁绘繈宕掑鍐炬澑闂備焦濞婇弨杈╂暜閿熺姴钃熸繛鎴炵煯濞岊亪鏌涢幘妤€瀚▍妤冪磽閸屾瑦顦烽柤瀹犲煐閺呰泛螖閸涱厙锕傛煕閺囥劌鐏犻柛妤佸▕閺屾盯鍩勯崘鐐暦闂侀潻缍€濞咃綁鍩€椤掑喚娼愭繛鍙夛耿閹繝鏁撻悩鑼舵憰闂佺粯鏌ㄩ崥瀣倿娴犲鐓ラ柡鍥殔娴滈箖姊洪崫鍕靛剳闁哥姵鎹囬崺鈧い鎺戝枤濞兼劖绻涢崣澶涜€块柟顕嗙節閺佹捇鎮╅懠鑸垫啺闂備胶绮弻銊╁触鐎ｎ喗鍊垮ù鐘差儐閻撱儵鏌￠崶顭戞當濞存粓绠栧娲传閸曢潧鍓抽梺鍝ュУ閹瑰洭宕洪埀顒併亜閹烘垵鏋ゆ繛鍏煎姈缁绘盯宕ｆ径娑溾偓鍧楁煙椤曞棛绡€闁轰焦鎹囬幃鈺呮嚑閼稿灚鍟洪梻鍌欒兌缁垶寮婚妸鈺佺疅闁挎稑瀚粈濠囨煕閵夘喖澧柣鎾寸懄閵囧嫰寮借椤ユ粓鏌熼崘鑼妞わ綁绠栧濠氬磼濮橆兘鍋撳畡鎳婂綊宕惰濞存牠鏌曟繛褍鎳愰悞鍏肩箾閹炬潙鐒归柛瀣崌閺屸剝鎷呯粙鎸庢闂佽桨绀侀崯鏉戠暦閹烘埈娼╅柛妤冨仜琚濇繝纰夌磿閸嬫垿宕愰弽褜鍟呭┑鐘宠壘绾惧鏌熼崜褏甯涢柣鎾存礃娣囧﹪顢涘┑鍡楁優闂佹椿鍘界敮鐐哄焵椤掑喚娼愭繛鍙夛耿瀹曞綊宕稿Δ鍐ㄧウ濠碘槅鍨甸崑鎰閸忛棿绻嗘い鏍ㄧ矊鐢爼鎮介娑辨疁闁哄矉缍侀幃銏ゅ传閵壯呭帒缂傚倷绶￠崰妤呭箰閹间焦鍋╃€瑰嫰鍋婇悡銉╂煕椤愩倕鏋庡ù婊勭矒濮婃椽宕楅懖鈹垮仦闂佸搫鎳忕粙鎾跺垝婵犲洦鏅濋柛灞句緱濡懎顪冮妶鍡楀闁搞劎鍎ゅ鍕礋椤撶姷锛滈柣搴秵閸嬪嫰鎮樼€涙﹩娈介柣鎰綑閻忔挳鏌熼搹顐ょ煉闁诡喗鐟╅弻鍛槈濮樿鲸鏅ㄩ梻鍌氬€峰ù鍥綖婢舵劕纾块柟鍓佺摂閺佸銇勯幘鍗炵仼闁绘挴鈧剚鐔嗛悹楦裤€€婵洭鏌ｉ悢鐓庝喊闁绘挶鍎甸弻娑㈩敃閻樿尙浼勯梺鍝勬－閸嬪嫰鍩為幋锔绘晩缁绢厼鍢叉导鎰渻閵堝骸骞栭柛銏＄叀閹箖鏌ㄧ€ｎ剟妾梺鍛婄☉閿曘倖绂嶅鍫熺厽闁绘劕顕埢鎾绘煃瑜滈崜姘跺礈濮橆剦鐒介柟鍓х帛閳锋帡鏌涚仦鍓ф噯闁稿繐鐭傞弻鐔兼惞椤愶絽纰嶅銈嗘穿缂嶄礁鐣锋總绋垮嵆闁绘劗鏁搁弳顐︽⒒娴ｄ警鐒鹃柣顒€銈稿畷鎴濃槈閵忊€崇彅闂佺粯鏌ㄩ崥瀣偂韫囨稒鐓曟い鎰剁悼缁犳牜鈧懓鎲＄换鍫ュ蓟閿濆鏁囬柣鏃傚劋閸ｄ即姊虹拠鈥虫灈缂傚秴锕悰顔界瑹閳ь剟鐛幒妤€绠ｆ繝鍨姉閳ь剚濞婂缁樻媴閾忕懓绗￠梺瑙勬倐缁犳牕鐣锋导鏉戝唨鐟滄粌顭囬弽銊х鐎瑰壊鍠曠花璇裁归懖鈺佲枅闁哄本鐩鎾Ω閵夈儳顔掑┑鐐差嚟閸樠兠洪鐑嗘綎婵炲樊浜滄导鐘绘煏婢跺牆鍓鹃柨婵嗩槹閻撴瑩鏌ｉ悢鍝勵暭闁哥姵顭囬埀顒冾潐濞叉ê顪冩禒瀣槬闁逞屽墯閵囧嫰骞掑澶嬵€栨繛瀛樼矋缁捇寮婚悢鐓庝紶闁告洦鍘滈妷鈺傜厱闊洦鎸鹃悞鎼佹煛鐏炵晫效妞ゃ垺绋戦埥澶娾枎閹搭厽效闂傚倷绀侀幖顐ゆ偖椤愶箑绀夌€光偓閸曞墎绋忓┑鐘绘涧椤戝棝宕电€ｎ喗鐓熼柕蹇嬪€栧☉褎顨ラ悙鎼疁婵﹦绮幏鍛村川婵犲懐顢呴梻浣瑰劤缁绘劙鏌婇敐鍛殾鐟滅増甯楅崑瀣煕椤愮姴鐒烘繛鍙夋倐濮婃椽宕ㄦ繝鍐ㄧ樂闂佸憡渚楅崹鐣屾閹惰姤鈷掑ù锝勮閻掗箖鏌￠崼顐㈠⒋闁硅櫕绻冮妶锝夊礃閵娧冨Е婵＄偑鍊栧濠氬磻閹剧粯鐓曢柕蹇ョ磿閸欌偓濠电姭鍋撳〒姘ｅ亾婵﹥妞介獮鏍倷閹绘帒顫戦梻浣告啞閺屻劑鏁冮妷褏鐭夐柟鐑橆殔闁卞洭鏌曟径娑橆洭闁告ê宕埞鎴︽偐缂佹ɑ閿柣搴㈠嚬閸撶喎鐣峰┑鍡╃叆闁告侗浜滄禍楣冩偡濞嗗繐顏紒鈧崘顔界厽闁瑰灝瀚弧鈧悗娈垮枦椤曆囧煡婢舵劕顫呴柍鍝勫€瑰▍鍥⒒娴ｈ櫣甯涢拑杈╂喐閺夊灝鏆為柟渚垮姂婵偓闁靛牆妫楅埀顒傛暬閹嘲鈻庤箛鎿冧痪闁诲繐娴氶崑鍡欐閹烘鍤嬮梻鍫熺☉閹介潧螖閻橀潧浠滈柛鐕佸亯閻忓啴姊洪崨濠佺繁闁哥姵顨呴埢宥咁煥閸喓鍘甸梺鍏肩ゴ閺呯偠妫㈤梻浣告啞閹歌崵鎹㈤崼銉ョ畺婵せ鍋撶€规洖銈告慨鈧柕蹇ｆ緛缁卞啿鈹戦悙鑸靛涧缂佽弓绮欓獮鏍敃閿旂粯鏅涢梺瑙勫劤婢у海澹曢悾灞稿亾楠炲灝鍔氶悗姘煎枤缁綁寮崒妤€浜炬繛鍫濈仢閺嬫稒銇勯鐘插幋鐎殿噮鍋婇獮鍥级閸喚鐛╅梻浣侯焾閺堫剛鍒掑畝鍕嚑婵炴垶鍩冮崑鎾舵喆閸曨剙顦╅梺绋款儏閿曘倝鎮鹃悜鑺ュ亜缁炬媽椴搁弲銏＄箾鏉堝墽鎮奸柛搴涘€涢·鍛存⒒閸屾艾鈧悂宕愰幖浣哥９闁绘垼濮ら崵鍕煕閹捐尙顦﹂柛銊︾箖閵囧嫰寮介顫捕缂備胶濮抽崡鎶藉箖瑜版帒鐐婃い蹇撶У閳锋牠姊洪崨濠勭畵閻庢氨鍏橀幃锟犲Ψ閳哄倻鍘卞┑鐐村灥瀹曨剙鈻嶅Ο鑽ょ闁兼祴鏅涢弸娑欐叏婵犲懏顏犻柟鍙夋尦瀹曠喖顢曢妶搴⑿炲┑锛勫亼閸婃牕鈻旈敃鍌氬窛妞ゆ挆鍕垫％闂傚倷鑳堕…鍫㈡崲濡ゅ懎纾婚柟閭﹀枤娑撳秴螖閿濆懎鏆為柣鎾存礋閺屽秹鍩℃担绋跨濡炪倕绻愰悧濠囧磹閸洖绾ч柛顐ｇ濞呭洨鐥幆褋鍋㈤柡宀€鍠栭弻鍥晝閳ь剙顕ｉ悙顒傜闁割偆鍠撻惌瀣煙娓氬灝濡界紒缁樼箞瀹曟﹢鍩炴径姝屾闂佽姘﹂～澶娒鸿箛娑樼鐎广儱娲﹀畷鍙夌節闂堟稒澶勯柛搴ｅ枛閺屻劌鈹戦崱妯烘婵繂娲ら埞鎴︽偐閸偅姣勬繝娈垮枙閸楀啿鐣风憴鍕瘈婵﹩鍓涢悿鍥⒑閻熸澘鈷旂紒顕呭灦瀹曟垹鈧綆鍠楅悡娆撴煕閹炬鎳愰惁鍫㈢磽娴ｇ瓔鍤欐俊顐ｇ箞瀵鏁愭径濠庢綂闂侀潧绻嗛弲婵嬪礉閸濄儳纾藉ù锝呮惈鏍＄紓浣割儐鐢剝淇婇悽绋跨妞ゆ牗鑹鹃崬銊╂⒑濮瑰洤鐏柡浣圭摃閹筋偊姊婚崒姘偓鎼佀囬鐑嗘晞濠㈣泛顭鏍р攽閻樺疇澹樼痪鎯у悑缁绘盯宕卞Ο鍝勵潕闂侀潧鐗婂姗€鍩為幋锕€鐒洪柛鎰剁細缁姊洪崨濠冪叆濡ょ姵鎮傞崺銏℃償閵娿儺娼婇梺闈涚墕濡瑥鈻嶉姀銈嗏拺缂備焦銆為幋锔藉亗闁炽儲绶炲☉銏″€婚柤鎭掑劗閹锋椽姊洪崷顓х劸婵炴挳顥撶划濠氬箻濞ｎ兛绨婚梺鎸庢椤曆囨倶閿旈敮鍋撳▓鍨灈闁硅绱曠划顓㈡偄閻撳海鍔﹀銈嗗笒鐎氼剟鎷戦悢鍝ョ闁瑰鍋熼悡顖涚箾瀹€濠侀偗闁哄本鐩獮妯何旈埀顒勫箠閹版澘鍌ㄩ柟杈鹃檮閻撶喖骞栧ǎ顒€鈧倕顭囬幇顓犵闁告瑥顦辨晶鐢告寠濠靛鐓熼柕蹇嬪焺閻掗箖鏌﹂崘顏勬灈闁哄矉绻濆畷鍫曞煛娴ｅ湱浜栫紓鍌欒兌婵瓨鏅舵禒瀣疅闁告稑锕ょ欢鐐烘煙闁箑澧伴柨娑欑洴濮婃椽鎮烽弶搴撴寖缂備胶绮换鍕箲閵忋倕骞㈡繛鎴炵懅閸樼數绱撻崒娆戝妽闁挎氨绱掑锕€鍠氶悢鍡欐喐濠靛鈷旈柛鏇ㄥ灠缁犵偤鏌曟繝蹇擃洭缂佲檧鍋撻梻浣告啞濞诧箓宕㈤懖鈺冪當闁跨喓濮甸埛鎴︽煟閻斿憡绶叉俊鎻掝煼閺岀喖鎼归銏狀潕闂佸憡甯楃敮锟犲箖閻ｅ苯鏋堟俊顖濇〃婢规洟姊洪幐搴ｇ畵濡ょ姴鎲＄粋宥夋倷閻㈢數锛滄繝銏ｆ硾閿曘倕危婵犳碍鐓冮悷娆忓閻忔挳鏌熼鐣屾噰闁瑰磭濞€椤㈡鎷呴悷鐗堢亪缂傚倸鍊搁崐椋庢閿熺姴绐楅柡宥庡幗閸嬪鐓崶銊р槈缂佲偓閸℃稒鐓欓柣鎴灻悘宥夋煛鐎ｎ亪鍙勯柣鎿冨亰瀹曞爼濡搁敂缁㈡О婵犵數鍋涢悧濠囧磿閹惰棄鐓橀柟杈鹃檮閸嬫劗绱撴担鑲℃垿鏌ㄩ銏♀拺闁圭瀛╃粚璺ㄧ磼閻樿櫕宕屾鐐插暣瀹曠螖閳ь剟鎮為崹顐犱簻闁圭儤鍨甸顏堟煃闁垮鐏撮柡灞剧☉閳规垿宕卞Δ濠佺棯闁诲海鎳撻幉锛勬崲閸儱钃熸繛鎴欏灪閸嬫劙鏌熺紒妯轰刊闁告柨顦靛铏规嫚閳ュ磭浠┑顔硷工濠€閬嶅箲閵忕姭鏀介悗锝庝簽閿涙粌鈹戞幊閸婃捇鎮為敃鍌氱骇闁归棿鐒﹂埛鎺懨归敐鍛喐闁哄鍟穱濠囶敃閵忕媭浠奸柧鑽ゅ仦娣囧﹪濡堕崨顔兼闂佺锕ら悥濂稿蓟閺囩喓鐝舵い鏍殔娴滈箖姊虹粙娆惧剱闁规悂绠栭獮澶愬箻椤旇偐顦板銈嗗笒閸嬪棗危閸洘鈷掑ù锝堝Г閵嗗啰绱掗埀顒佺瑹閳ь剟鍨鹃敃鈧悾锟犲箥椤旇姤顔曟繝鐢靛仜濡﹥绂嶅鍫稏闁告稑鐡ㄩ悡蹇涙煕椤愶絿绠栭柛锝勭矙閺岋綁顢曢姀鐙€浼冨┑顔硷攻濡炶棄鐣峰鍫濈闁瑰搫绉堕弫鏍⒒娴ｅ憡鎲稿┑顔芥尦閺屽﹪鏁愭径濠冩К闂侀€炲苯澧柕鍥у楠炴帡骞嬪┑鍐ㄤ壕鐟滅増甯掑Ч鍙夈亜閹烘垵顏柣鎾寸洴閹﹢鎮欐０婵嗘婵犵鈧偨鍋㈤柡灞界Ф閹叉挳宕熼銈勭礉闁诲氦顫夊ú鏍х暦椤掑嫧鈧棃宕橀鍛彴闂傚鍋掗崢濂杆夊鑸碘拻濞达綀妫勯崥褰掓煕閻樺啿濮堢紒鏃傚枔閳ь剨缍嗛崰鏍礄閻樼鍋撻獮鍨姎妞わ缚鍗抽幃锟犲即閵忥紕鍘繝銏ｅ煐缁嬫捇宕氶弶搴撴斀闁挎稑瀚烽悞楣冩婢跺绡€濠电姴鍊搁顐︽煟椤撶喎娴柡宀嬬秮楠炴瑩宕橀妸銈呮瀳闁诲氦顫夊ú鏍偉閸忛棿绻嗘慨婵嗙焾濡插嘲鈹戦埥鍡椾簮闁哄懐濮撮～蹇涙惞鐟欏嫬鏋傞梺鍛婃处閸樼厧顕ｉ妸褏纾藉ù锝呮惈鏍￠梺缁橆殘婵挳顢氶敐鍡欑瘈婵﹩鍘兼禍婊呯磼閻愵剙顎滃瀛樻倐瀵煡鍩￠崘顏嗭紳婵炶揪绲藉﹢閬嶅煡婢跺浜滈柟瀛樼箖閸犳鈧娲樼换鍫濈暦椤愶箑唯鐟滃繘鏁嶅┑鍥╃閺夊牆澧介崚浼存煙绾板崬浜濋柣妤€閰ｅ缁樻媴閸濆嫬濮﹂梺鍝勬噳閺呯姴鐣疯ぐ鎺戦唶闁哄洨鍠庢禒鎺戭渻閵堝棙鈷掗柍宄扮墕椤洭濡搁埡鍌滃帗閻熸粍绮撳畷婊冣枎閹炬潙浠奸悗鐟板閸嬪﹪鎮￠妷鈺傜厱闁哄洢鍔岄獮姗€鏌熼搹顐ょ疄婵﹥妞介獮鏍倷閹绘帒螚闂備礁鎲″ú锕傚礈濮樿埖鍎婇柡鍐ｅ亾缂佺粯绻堥幃浠嬫濞磋翰鍎查妵鍕晲鎼粹剝鐏撳┑鈥冲级閸旀瑥顕ｉ幘顔碱潊闁绘顣槐閬嶆⒒娴ｄ警鏀伴柟娲讳簽缁骞嬮悩宸閻熸粎澧楃敮妤呮偂濞戞埃鍋撻獮鍨姎濡ょ姴鎲＄粋宥呪攽鐎ｎ偆鍘搁梺绯曞墲椤洭鎯岄幒妤佺厸鐎光偓鐎ｎ剛袦濡ょ姷鍋涘ú顓€佸Δ浣瑰闁荤喐婢樻竟宥囩磽閸屾瑨鍏岄柛瀣崌瀹曟洟骞庣憴锝傚亾閿曞倹鍊婚柦妯侯槼閹芥洟姊洪崫鍕偍闁搞劌缍婇弻瀣炊閵娧呯槇闂傚倸鐗婄粙鎺旂矈閳哄倷绻嗘い鎰剁悼閵嗘帞绱?"
        if mode == "direct":
            return "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎娆戠┛闂傚倷绶氶埀顒傚仜閼活垱鏅堕崜褏纾奸柣妯挎珪鐏忣參鏌ｉ敐澶嬫暠缂佽櫣鏅划娆戞嫚娣囧崬濡介柕鍥у瀵噣宕堕‖顔芥尰缁绘盯宕ㄩ鐘测叺濠殿喖锕︾划顖炲箯閸涘瓨鎯炴鐐茬氨閸嬫挻绻濋崶銊у幈闂佽鍎抽顓犵不濡偐纾兼い鏃傛櫕閹冲洦顨ラ悙鏉戠瑨閾绘牠鏌嶈閸撶喎鐣烽妷銊ｄ汗闁圭儤鎸搁埀顒€鐖奸弻锝夊箛椤栨稓銆愰梺瀹狀嚙缁绘﹢寮婚敓鐘茬闁靛ě鍐炬澑闂備礁鎼幊蹇涙偂閿熺姴钃熸繛鎴炃氬Σ鍫ユ煕濡ゅ啫浠滅紒鐘叉惈閳规垿鎮欓懠顒€顤€闂佺粯鎸撮埀顒佸墯濞兼牠鏌ц箛鎾磋础闁活厽鐟︾换娑㈠幢濡搫濮㈤梺鍛婃惄閸撶喎顫忓ú顏勪紶闁告洦鍓欏▍銈囩磽娓氬洤鏋熼柟鍝ョ帛缁岃鲸绻濋崶銊ヤ缓缂備礁顑堝▔鏇⑺囬弶娆炬富闁靛牆妫涙晶顒佹叏濡濮傛い銏＄懄缁绘繈宕堕妸銉㈠亾閸偒娈介柣鎰皺娴犮垽鏌涢弮鈧畝鎼佸蓟閿濆憘鏃堝焵椤掆偓铻炴繝闈涙閺嗭箓鏌曡箛瀣偓鏇㈡倶閹惰姤鐓欏Λ棰佽兌閸斿秹鎮楅棃娑氱劯婵﹥妞藉Λ鍐ㄢ槈濮橆剦鏆梻浣侯焾閿曪箓骞婇幘璇茬厺鐎广儱顦悙濠冦亜閹哄秷鍏岄柛姗€浜跺Λ鍛搭敃閵忊€愁槱濠碘槅鍋呴崹鍧楀箠閹捐埖宕夐柕濞垮灩娴滅偓绻涢崼婵堜虎闁哄绋掗妵鍕敇閻愬弶些濡炪倖娲╃紞渚€鐛鈧、娆撴寠婢跺鐩庢繝纰夌磿閸嬫盯顢栭崨顒煎綊鎮滈懞銉ヤ粧濡炪倖娲嶉崑鎾存叏婵犲嫮甯涢柟宄版噽缁瑥鈻庨悙顒夋闂傚倷鑳堕…鍫ヮ敄閸涙潙绠犻柟鐗堟緲缁犳煡鏌曡箛瀣偓鏇犲閸忚偐绠鹃柟瀵稿仧閹冲啰鈧鍠栧鈥愁潖濞差亜浼犻柛鏇ㄥ墮閸嬪秹姊洪幖鐐插婵＄偘绮欏畷鍝勨槈閵忕姷顓洪梺缁橆焽閺佹悂鏁嶅鍫熺厽閹兼惌鍨崇粔闈浢瑰鍕煉闁诡垰鍟撮弫鎾绘偐瀹曞洤骞堥梻浣告惈閸燁偊宕愰幖浣稿嚑婵炴垯鍨洪悡娑㈡倶閻愭鐒惧褎鐓￠弻鐔风暋閻楀牆娈楅悗瑙勬礃缁捇骞婇悩娲绘晢闁逞屽墴楠炲啴骞嬮敂鐣屽幗闁瑰吋鐣崺鍕疮韫囨稒鐓曢柣妯虹－濞插瓨銇勯姀鈥蹭孩妞わ箑缍婇弻娑㈠煘閸喖濮曢悗鍨緲鐎氫即鐛崶顒夋晢濠㈣泛顑囩粔閬嶆⒒閸屾瑨鍏岀紒顕呭灥閹筋偄顪冮妶鍡樷拹闁绘濮撮悾鐑筋敆閸曨剙鈧粯淇婇婵嗕汗闁伙箑鐗撳鍝勑ч崶褏浼堝┑鐐板尃閸パ呭幒闂佸壊鍋嗛崰鎾剁不閹灐褰掓晲閸涱厽姣愰梺鍛婄閿氶柍钘夘樀婵偓闁绘鏁稿澶愭⒒娴ｄ警鐒鹃柡鍫墰閹广垽宕掑杈ㄧ槗婵犵數濮烽弫鍛婃叏閻戣棄鏋侀柛娑橈攻閸欏繘鏌ｉ姀銈嗘锭闁哄鐗忛埀顒€绠嶉崕閬嵥囬婊冾棜濠电姵纰嶉悡鍐煃鏉炴壆顦﹂柡鍡欏枔缁辨帡鍩﹂埀顒勫磻閹炬枼鏀介柣妯虹仛閺嗏晛鈹戦鑺ュ唉鐎规洘鍔欓獮鏍ㄧ瑹閸ャ劍娅嗛梻浣稿暱閹碱偊骞婃惔锝囦笉婵鍩栭悡鐔兼煛閸屾氨浠㈤柟顔藉灴閺屽秹鏌ㄧ€ｎ亞浼岄梺鍝勬湰缁嬫垿鍩ユ径濠庢建闁割偆鍣ラ弳顓犵磽閸屾瑧顦﹂柣鏍у悑缁傚秹宕奸弴鐐舵憰濠电偞鍨崹娲磻閹邦喒鍋撶憴鍕婵炲眰鍊濋崺娑樼暆閸曨兘鎷洪柣鐘叉礌閳ь剝娅曢悘鎾绘⒑鏉炴壆顦︽い顓犲厴閹即顢欑喊鍗炴倯婵犮垼鍩栬摫闁哄應鏅犲娲川婵犲啫鐦烽悗骞垮劚濞差厼螞瀹勬壋鏀介柣妯虹仛閺嗏晠鏌涚€ｎ剙浠辨鐐村姈缁绘繂顫濋鐐寸杽闂備浇顕栭崹濂告倶閹邦優娲敂閸曞汞鍐剧唵閻犺櫣灏ㄥ銉╂煕閵堝棗鐏ラ柍瑙勫灴閹瑩寮堕幋鐘辨埛闂備焦鎮堕崝宥咁渻娴犲绠栭柨鐔哄Т閸楁娊鏌ｉ弬鍨暢缂佺姵鑹鹃—鍐Χ閸℃瑥顫х紓浣筋嚙閸婂灝鐣烽妷銊ｄ汗闁圭儤鎸鹃崢钘夘渻閵堝棙灏甸柛鐘叉捣缁叀顦归柡灞界Х椤т線鏌涢幘瀵哥疄闁挎繄鍋炲鍕箾閹烘垶鎯堟い顐ｇ矒閸┾偓妞ゆ巻鍋撻柣锝囨焿閵囨劙骞掗幋锔芥殔婵犲痉鏉库偓鏇㈠疮椤愩倗鐭堥柨鏇楀亾闁宠鍨块、娆愭叏閹邦亞鎹曢梻浣侯焾椤戝棝骞愭繝姘モ偓鍐Ψ閳哄倸鈧兘鏌涘▎蹇ｆЦ妞わ腹鏅犲娲偡閺夋寧些闂佺娅曢敋闁伙絿鍏橀、鏇㈡晝閳ь剛绮堢€ｎ偁浜滈柟鏉垮缁夘剛绱掗煬鎻掔伈婵﹤顭峰畷鎺戭潩椤戣棄浜鹃柟闂寸绾剧懓顪冪€ｎ亝鎹ｉ柣顓炴閵嗘帒顫濋敐鍛婵°倗濮烽崑娑⑺囬悽绋垮瀭闁告挆鍕劚婵炶揪缍€椤濡靛┑瀣厸濞达絿顭堥弳锝団偓瑙勬礃鐢帡锝炲┑鍥舵綑闁哄秲鍓遍妶鍛斀闁绘ɑ鍓氶崯蹇涙煕閻樻剚娈滈柡浣稿暣閸╋繝宕ㄩ鐙呯吹闂備胶绮崹鐓幬涢崟顓犱笉闁规儼濮ら悡娆撴煙椤栧棗鎷戠槐鐐电磽娴ｇ懓濮夐柛瀣ㄥ€濆濠氭晲閸℃ê鍔呭銈嗙墬缁孩鐗庨梻鍌欑閹诧繝骞愭繝姘剮妞ゆ牜鍋涚粻姘€掑锝呬壕閻庤娲栭妶鍛婁繆閻戣姤鏅滈悷娆忓椤忔椽姊婚崒娆掑厡妞ゎ厼鐗撳鐢割敆閳ь剟锝炲┑瀣╅柨鏃囧Г閻濆嘲鈹戦悙鏉戠仸婵ǜ鍔庢竟鏇熺附閸涘﹤鈧敻鏌ㄥ┑鍡涱€楀ù婊勭矒閺岋綀绠涢弮鈧亸锕傛煛鐏炲墽娲撮柛鈺冨仱楠炲棜顦卞瑙勬礀閳规垿鏁嶉崟顐℃澀闂佺锕ラ悧鏇㈩敊韫囨梻绡€婵﹩鍓涢敍娑㈡⒑鐟欏嫬鍔ゅ褍娴锋竟鏇㈡偩鐏炵浜炬鐐茬仢閸旀岸鏌熼柨瀣仴妞ゆ柨绻樻俊鐑藉煛閸屾粌骞楅梻浣瑰缁诲倸煤閵堝鍌ㄩ柟缁㈠枟閻撴瑦銇勯弮鈧崕鎶藉储鐎涙﹩娈介柣鎰皺鏁堥梺鍦帶缂嶅﹪銆侀弴銏℃櫜闁糕剝顭囩敮鍡涙⒒閸屾艾鈧悂宕愭搴ｇ焼濞达絽婀遍悵璺衡攽閻樺弶鎼愮痪鎯ь煼閺岀喖骞戦幇顓犮€愮紓浣界堪閸婃繈寮婚敃鈧灒濞撴凹鍨辨婵犳鍣徊浠嬫偋閹炬剚娼栧┑鐘宠壘绾惧吋鎱ㄥ鍡楀幋闁稿鎸搁悾锟犲箠婵犲倻绉虹€规洘鍎奸ˇ顕€鏌＄€ｎ偆澧甸柡宀嬬節瀹曞爼濡烽妷褌鎮ｇ紓鍌欑劍閸旀牠銆冩繝鍥ц摕闁绘梻鍘х粻姘辨喐韫囨稑绠洪柣妯肩帛閻撴洘绻涢崱妤冪缂佺姴顭烽弻鈥崇暆閳ь剟宕伴幘鑸殿潟闁圭儤顨呴～鍛存煟濡櫣锛嶅ù婊冪埣濮婄粯鎷呮笟顖滃姼闂佹寧娲忛崐婵嬪箖閵夛妇闄勭紒瀣劵閹芥洟鎮峰鍕仼缂侇喛顕ч埥澶愬閳╁啯鐝抽梻浣告啞娓氭宕滃☉銏犳瀬闁哄稁鍋嗙壕浠嬫煕鐏炲墽鎳嗘い鏂款槹娣囧﹪鎮▎蹇旀悙缁炬儳顭烽弻鐔煎礈瑜忕敮娑㈡煃闁垮绗掗棁澶愭煥濠靛棙绁╅柣鎺斿亾閵囧嫰濡烽妷褏顔掗梺鍝勭焿缂嶄線鐛Ο铏规殾闁搞儜鈧崣娲煟鎼淬値娼愭繛鍙夛耿瀹曞綊宕归鐐闂侀潧艌閺呪晠寮鍡欑闁糕剝锚閻忋儱顭胯缁犳牕顫忕紒妯诲闁革富鍘介懣鍥⒑閹肩偛濡兼い顓炲槻椤曪綁顢曢敃鈧导鐘绘煏婢跺牆鍔存俊顐ｇ矋缁绘繈妫冨☉妯峰亾閹间礁绠熼柨鐔哄У閸嬪倿鏌涢幇鍏哥凹闁哥姵鍔栫换婵囩節閸屾粌顣虹紓浣插亾闁割偆鍠愰崣蹇旀叏濡も偓濡鏅舵繝姘厱闁靛牆妫▓婊堟煛鐏炲墽娲寸€殿喗鎸虫俊鎼佸Ψ瑜岄崫妤冪磽閸屾瑨鍏屽┑顔炬暩缁瑩骞掑Δ鈧闂佸憡娲﹂崹鎵不婵犳碍鍋ｉ柧蹇氼潐绾绢亪鏌曡箛濠冾潑婵炲牅绮欓弻锝夊箛椤撶喎鍓瑰┑鐐茬墛缁秹骞堥妸锔剧瘈闁告洦鍘肩粭锟犳⒑閻熸澘妲婚柟铏悾鐑筋敃閿曗偓鍞梺鎸庢閺侇噣宕戦幘娲绘晩閻忓繑鐗楅弬鈧梻浣规灱閺呮盯宕妸锔绢浄闁绘绮悡鏇㈡煛閸愶絽浜鹃梺鎼炲妼濞硷繝鎮伴鐣岀瘈闁稿濮ゅΛ鍐ㄧ暦閵娾晩鏁囬柕蹇曞У閺嗩亪姊婚崒娆戭槮闁圭⒈鍋勭叅闁靛ň鏅涚壕濠氭煟閺冨倵鎷￠柡浣革躬閺岀喐娼忔ィ鍐╊€嶉梺鎶芥敱閸ㄥ湱妲愰幘瀛樺闁谎囨櫜缁剁敻姊虹紒妯虹闁哄拋鍋嗗Σ鎰板箳濡ゅ﹥鏅梺鍛婁緱閸樼偓绂掗幖浣瑰€甸悷娆忓缁€鍐煕閵婏箑顕滃ǎ鍥э躬楠炴牗鎷呯憴鍕彆闂佸搫顦遍崑鐐寸珶閸℃稒鍎庨幖娣妽閳锋帒霉閿濆懏鍟為柟顖氱墢缁辨帗寰勭€ｎ剙寮ㄩ悗瑙勬礃缁诲啴骞嗛弮鍫澪╅柕澹啫绗岄梻鍌欑閹碱偄煤閵忋倕鍨傛繛宸簻绾惧綊鏌涢锝嗙闁告瑦鎹囬弻娑㈠Ψ閿濆懎濮庨梺鍛婃⒐绾板秹濡甸崟顖氱厸濠电姴鍊搁埛瀣⒑閸濆嫯瀚扮紒澶屽厴绡撳〒姘ｅ亾闁哄本鐩獮妯尖偓闈涙憸閻ゅ嫰姊洪幐搴ｇ畼闁稿鍋涢銉╁礋椤掑倻顔曢梺鍦劋椤ㄥ牏妲愰幍顔剧＜闁绘ê纾埥澶愭煃閽樺妲搁摶锝囩棯閹峰矂鍝洪崯鎼佹⒒娴ｇ瓔鍤欏Δ鐘叉憸缁顓兼径濠勶紵闂佸憡顨堟导婵喢洪鍛珖闂侀€炲苯澧撮柟顕€绠栭幃婊堟寠婢跺瞼鍘┑鐘灱濞夋盯鎯夋總鍛婂剨闁割偁鍎查埛鎺楁煕鐏炵偓鐨戝褎绋戦妴鎺戭潩椤撗勭杹閻庤娲樺ú婵堢不濞戙垹鍗虫俊銈傚亾濞存粓绠栭弻锝夋偄閸濆嫷鏆梺鍝ュ枔閸嬬喓妲愰幒鏃€瀚氶柟缁樺笚濞堢粯绻濈喊澶岀？闁轰浇顕ч悾鐑芥偄绾拌鲸鏅┑顔斤供閸撴瑩寮妶澶嬧拻濞撴埃鍋撴繛浣冲洠鈧箓宕奸妷銉э紮濠德板€曢崯顖氱暦閹绘崡褰掓晲閸モ斂鈧﹪鏌￠埀顒佺鐎ｎ偆鍘介梺褰掑亰閸ㄤ即鎯冮悜妯诲弿闁挎繂娲ゆ禒閬嶆煛瀹€瀣瘈鐎规洏鍔戦、娑樞掔憗銈呯仾闁靛洤瀚伴、鏇㈠閵忋埄鍞虹紓鍌欐祰妞村摜鏁幒鏇犱航闂佽崵濮村ú銈呂熸繝鍥х劦妞ゆ帊鐒﹀畷灞炬叏婵犲懏顏犵紒杈ㄥ笒铻ｉ柧蹇涒偓娑欘敇闂傚倷鐒︾€笛呭枈瀹ュ洦宕叉繛鎴欏灩闁卞洦绻濋棃娑氬ⅱ闁告棏鍨伴埞鎴︻敊绾兘绶村┑鐐叉嫅缂嶄線宕洪埀顒併亜閹烘垵鈧綊顢旈悢鍏尖拻闁告洦鍋勯鈺傘亜椤撶偟浠㈤摶锝囩磽娴ｅ顏勵嚕閸ф鈷戠紒瀣濠€鏉款熆鐟欏嫭绀嬬€规洘鍨块獮姗€鎳滈棃娑欑€梻浣告啞濞诧箓宕滃☉鈶哄洭顢橀姀鈾€鎷虹紒缁㈠幖閹冲繘鎮甸鍫熺厵闁荤喓澧楅崰妯活殽閻愭彃鏆為柕鍫秮瀹曟﹢鍩℃担鎻掍壕濠电姵纰嶉悡銏′繆椤栨瑨顒熸俊鍙夋そ閺屾稒绻濋崟顐℃濠殿喖锕ュ钘夌暦濮椻偓瀹曪絾寰勭€ｎ亜澹嶉梻鍌欑閹芥粍鎱ㄩ悽鍛婂殞闁诡垎鍐偒闂傚倷绀侀幉锛勭矙閹达附鏅濋柨鏃€鍎虫慨顒勬煃瑜滈崜娑氭閹烘绀堢憸宥夈€傛總鍛婂珔閺夊牄鍔婃禍婊勩亜閹板灚绶涢棅顒夊墴閺岋紕浠﹂崜褎鍒涙繝纰樺墲閹倹淇婇悜钘壩ㄩ柕濞垮劤閸樻潙鈹戦敍鍕杭闁稿鍊栫粋宥咁煥閸繄鏌堥梺鍝勵槹閸ㄥ綊寮抽敂鐐枑闁绘鐗嗘穱顖炴煛娴ｉ潻韬柟顔煎槻閳诲氦绠涢幙鍐х磻濠电偛鐡ㄧ划宥夋偋閻樺樊娼栫紓浣股戞刊鏉戭渻鐎ｎ亞鍑归悷鏇炴缁辨挻鎷呴挊澶庢暱婵犳鍠撻崐鏇㈩敋閵夆晛绀嬫い鏍ㄦ皑閸婄偛顪冮妶鍡楀潑闁稿鎸鹃惀顏堝箚瑜滈悡濂告煛瀹€鈧崰鏍嵁閹达箑绠涢梻鍫熺⊕椤斿嫮绱撻崒娆掝唹闁稿鎹囬弻娑氫沪閹冩瘓闂佺粯鏌ㄥΛ婵嬪箖瑜版帗鎯為柣鐔稿濞堛倕鈹戦纭锋敾妞ゃ劌鎳橀垾锔炬崉閵婏箑鏋傞梺鍛婃处閸撴盯藝閺夊簱鏀芥い鏃傘€嬮崝鐔虹磼椤曞懎鐏︽鐐茬箻瀹曘劑寮堕幋婵堢崺濠电姷鏁告慨鎾磹閻熸壋鏋旀慨妞诲亾婵﹦绮幏鍛村川婵犲倹娈樻繝纰樻閸嬪懘宕归崹顕呮綎濞寸姴顑呯粈瀣亜閹捐泛啸闁绘帒娼￠幃妤呯嵁閸喖濮庨梺鐟板暱椤﹂潧顕ｉ妸锔绢浄閻庯綆鍋勯埀顒傛暬閺屻劌鈹戦崱妯烘濡炪倧绲界壕顓犳閹烘柡鍋撻敐搴濈敖缂佺姴顭烽弻鐔碱敊缁涘鐤侀梺缁樹緱閸ｏ絽鐣疯ぐ鎺濇晩闁绘挸瀵掑娑樷攽閻樻鏆俊鎻掓嚇瀹曟垿宕ㄩ婊呯厯闂佽宕樺▔娑㈠垂濠靛牏纾藉ù锝夘€囧鍫濈；闁告稑鐡ㄩ悡鏇㈡煙閼割剙濡芥繛鍛嚇閺屽秷顧侀柛鎾寸懇閹ê顫濇潏銊ュ簥濠电偞鍨崹鍦不閿濆鐓熼柟閭﹀墰娴犳盯鏌涢敐鍕煓婵﹨娅ｇ槐鎺懳熼搹鍦啰缂傚倷绶￠崰妤呮偡閳轰緡鍤曞┑鐘崇閺呮彃顭块懜鐬垿寮查敐澶嬧拺缂備焦锚閻忋儲绻涚拠褏鐣电€殿噮鍋婇幃娆擃敆閸屾粠鍟庨梻浣瑰缁诲倿骞婅箛娑樼闁规壆澧楅悡銉╂煛閸ャ儱濡洪梺顓у灦閺屾洟宕遍弴鐘电崲閻庢鍠楅幐铏叏閳ь剟鏌嶉埡浣告殲闁绘繃濞婂缁樻媴閾忓箍鈧﹪鏌嶈閸撴瑧澹曢鐘典笉闁哄被鍎查崐鍨叏濮楀棗浜為柣顓熺懄閹便劍绻濋崟顓炵闂佺懓鍢查幊妯虹暦閵婏妇绡€闁稿本绋掗悾濂告⒒娴ｅ湱婀介柛鈺佸瀹曞綊鏌嗗鍐ｅ亾閸愵喖閱囬柕澶堝劜閻庮剙顪冮妶鍡樼５闁稿鎹囬弻娑㈠Ω閿曗偓閸斻倝鏌ｉ敐鍥у幋鐎规洖鐖兼俊鎼佹晜鐠囧弶娅楁繝鐢靛Х閺佸憡绻涢埀顒佺箾娴ｅ啿娲ょ壕褰掓煙闂傚顦︾紒鐘靛枛閺屻劑鎮㈤崫鍕戙垻鐥幆褜鐓奸柡灞剧洴瀵挳濡搁妷褌鐢婚梻浣侯焾椤戝洦鎱ㄩ悽鍨床婵炴垯鍨圭粻锝夋煟閹邦垰鐨洪柣鐔村妽缁绘繈鍩涢埀顒勫礋椤撶偛缁╅梻浣告惈閻绱為埀顒傜磼閻樺磭娲存鐐达耿楠炴牠顢橀悤鍌滅婵犵數濮甸鏍窗閺嶎厽鏅濋柨鏃€鍎抽崹婵囥亜閺嶎偄浠滅紒鐙€鍨堕弻娑樷槈閸楃偟浠梺娲诲幗閻燂妇鎹㈠☉銏犲耿婵炲棗绻嬫竟鏇烆渻閵堝啫鍔滈柛銊ョ仢椤繒绱掑Ο璇差€撴繛鎾村嚬閸ㄦ娊宕濈粙娆炬富闁靛牆妫楅悘銉╂倵濮樼厧鏋涢柍璇查叄婵偓闁绘瑢鍋撴繛灏栨櫆閵囧嫰骞掗幋婵冨亾閻熸壋鏋斿Δ锝呭暞閳锋垿姊婚崼姘珔闁伙附绮撻弻娑樜熼崗鍏肩彧闂侀€炲苯澧痪鏉跨Ф閸犲﹤顓奸崶銊ュ簥濠电偞鍨崹鍦棯瑜旈弻鐔煎箹椤撶偛绠归梺鍛婃崌娴滆泛顫忛搹瑙勫珰闁肩⒈鍓涢鍥⒑閸濄儱鏋戞繛鍏肩懇閿濈偠绠涢幘浣规そ椤㈡棃宕担璇℃濠电姷鏁搁崑鐐哄垂鐠轰警娼╅柕濞炬櫆閸嬵亪鏌涢弴銊ョ仭闁抽攱鍨圭槐鎺斺偓锝庝簻閻繝鏌￠埀顒佺節濮橆厾鍘藉┑掳鍊曢崯顐﹀煝閸噥娈介柣鎰絻閺嗭綁鏌涢妸鈺冪暫鐎殿噮鍓熸俊鐑芥晜缂佹绉鹃梻鍌氬€风欢姘焽瑜忛幑銏ゅ幢濞戞鍔﹀銈嗗笂閻掞箓鎮橀柆宥嗙厱閻庯綆鍋呭畷宀勬煙椤旇崵鐭欑€规洏鍔嶇换婵嬪礋椤愩垺杈堟繝鐢靛Х閺佸憡绻涢埀顒佺箾娴ｅ啿鍚樺☉妯锋斀閻庯絽鐏氶弲娑樷攽鎺抽崐鎰板磻閹剧粯顥嗗璺侯儑缁♀偓婵犵數濮撮崐褰掑闯閻熸噴褰掓偐鐠佽櫕鍠氶梺鍝勫閳ь剙纾弳鍡涙倵閿濆骸澧柛鈺佽嫰椤啴濡舵惔鈥崇闂佸憡姊归崹鐢告偩閻戣棄纭€闁绘劕绉靛Λ鍐春閳ь剚銇勯幒鎴濐仼缂佺姵宀搁弻锝夊箛椤旇姤姣勭紒鐐礃濡嫰婀侀梺鎸庣箓鐎氼噣鎯屽▎鎾寸厱婵犻潧娲﹂妵婵嬫煙椤旇崵鐭欐い銏＄☉閳藉娼忛妸褎娈藉┑锛勫亼閸娿倝宕㈤悡骞熸椽鍩￠崘顏冪瑝濠电偞鍨惰彜婵℃彃鐗婃穱濠囶敍濞戞﹩妫滈梺鍝勬噺缁诲牓鐛径濠庢桨鐎光偓閳ь剟鎮块埀顒€鈹戦悙鏉戠仸闁荤喆鍎茬粋鎺撱偅閸愨斁鎷洪梺鍛婄☉閿曘儲寰勯崟顖涚厱濠电姴瀚埢鍫⑩偓娈垮櫘閸ｏ絽鐣锋總鍛婂亜闁炬艾鍊归惈蹇涙⒒閸屾艾鈧悂宕愰幖浣瑰亱濠电姴瀚惌娆撴煙闁箑鏋涢柛銊︾箞閹娼幏宀婂妳濠电偞鎸搁…鐑藉蓟閺囥垹閱囨繝闈涙祩濡偤姊虹拠鑼疄闁稿孩鐓℃俊鐢稿礋椤栨稒娅嗛梺缁樺姦閸撴艾袙閸儲鈷戦悹鍥ｂ偓铏亞闂佸憡顨嗘繛濠囧Υ娴ｇ硶鏋庨柟鎯ь嚟閸欏棗顪冮妶鍡欏闁活収鍠楃粩鐔煎即閵忊檧鎷洪梺鍦焾濞撮绮婚幘鍓佺＜闁靛鍔屾禍褰掓煠濞差亙鎲炬鐐达耿椤㈡瑩鎮剧仦钘夌闂傚倷绶氶埀顒傚仜閼活垱鏅堕婊呯＜闁稿本绋戠粭褔鏌嶈閸撱劎绱為崱娑樼；闁糕剝绋戦崒銊╂⒑椤掆偓缁夌敻鍩涢幋锔界厸闁稿本锚閸旀粍绻涢崨顓熷殗闁哄本绋戦埢搴ㄥ箛椤掆偓椤帒螖閻橀潧浠滄い鎴濐樀瀵偊宕掗悙鏉戠檮婵犮垼娉涢ˇ浼村春濞戙垺鈷掗柛灞剧懅椤︼附绻濋埀顒勬焼瀹ュ懐锛熼梺闈涚墕椤︻參鍩€椤掆偓閸熸潙鐣烽崡鐐╂婵☆垳鍘ч獮鍫ユ⒒娴ｇ儤鍤€妞ゆ洦鍙冨畷鎴︽倷閸濆嫮鐓戦棅顐㈡处缁嬫帡鎮￠悢鍏肩厽闁哄倹瀵ч幆鍫熴亜閿濆懌鍋㈤柡宀€鍠栧畷妤呮偂鎼粹槅娼氶梻浣告惈閻绱炴笟鈧悰顕€骞掑Δ鈧粻缁樼箾閿濆骸鍘搁柧蹇撻叄濮婄粯鎷呴崨濠冨創闂佸搫鐗滈崜鐔煎箚閸曨垼鏁嶆繛鎴烆殘缁犳岸姊鸿ぐ鎺擄紵缂佲偓娴ｅ憡鏆滈梻鍌欑劍鐎笛呮崲閸岀偛绠犵€广儱顦粈鍡涙煙閻戞﹩娈曢柣鎾跺枛楠炴牕菐椤掆偓閳ь兙鍊曢…鍥箛椤撶姷顔曢梺鍛婄懃椤︻垶鎮樼€电硶鍋撶憴鍕┛缂佺粯绻傞悾宄拔熸笟顖氭櫊濡炪倖鏌ㄩ崥瀣敇閸ф鈷掑ù锝呮啞鐠愶繝鏌ц箛鎾诲弰鐎规洘婢樿灃闁告侗鍘鹃敍娑㈡⒑鐟欏嫬顥嬪褎顨婇幃锟犳偄閸忚偐鍘棅顐㈡搐閿曘儵锝炴繝鍥ㄧ厱闁绘棃顥撶粻鎻捛庨崶褝韬鐐存崌楠炴帡骞橀搹顐ｇ暭缂傚倸鍊烽懗鍓佸垝椤栨粍宕查柛宀€鍋涢悡婵嬫煙閹规劦鍤欓柛銊ュ€归妵鍕籍閸屾稒鐝繛瀛樼矊閻栫厧顫忕紒妯肩懝闁逞屽墮椤洩顦查悡銈夋煥閺囩偛鈧綊宕曟惔顫簻闁哄秲鍔嶉惃鎴︽煛閸☆厾鐣甸柡宀€鍠愬蹇涘礈瑜忛弳鐘电磽娴ｅ搫孝妞ゎ厾鍏樺璇测槈閵忕姈鈺呮煥閺冨牊鏆滄俊鎻掔墛缁绘稓鈧稒顭囬惌鎺旂磼閻樺磭澧垫鐐插暙閻ｏ繝骞嶉搹顐も偓濠氭椤愩垺澶勯柟灏栨櫆缁傛帡宕滆绾捐棄霉閿濆棗绲诲ù婊堢畺濮婃椽宕ㄦ繝鍌毿曟繛瀛樼矋閻楃姴鐣烽幋锕€绠婚悹鍥皺椤ρ勭節閵忥絾纭鹃柨鏇稻缁旂喖寮撮姀鈾€鎷绘繛杈剧到閹诧繝宕悙鐢电＜閻庯綆鍋勯悘鎾煛娴ｇ鏆ｉ柡浣瑰姍瀹曞爼濡搁妷銉у搸闂傚倷鑳剁涵鍫曞礈濠靛牏鐭欓柟鐑橆殕閸嬪倿鏌￠崶鈺佹瀭濞存粍绮撻弻鐔煎级閸噮鏆㈢紓浣割儓瀹曠數妲愰幒妤€鐒垫い鎺戝閻掑灚銇勯幒鍡椾壕闁剧粯鐗犻弻锝咁潨閳ь剙顭囪缁傚秵绺介崨濠勫幈闂侀潧臎閸愩劌顬嗙紓鍌欑閻焦銇旈崫銉﹀床婵犻潧顑呴悙濠囨煠缁嬭法浠涙繛鍛墬缁绘繈鎮介棃娴躲垽鏌ㄩ弴妯衡偓婵嗙暦椤栫儐鏁冮柨婵嗘祩濞村嫬鈹戦埥鍡楃仴鐎规洜鏁稿褔鍩€椤掆偓閳规垿鎮欓懠顒€顣洪梺璇茬箲缁诲牆顕ｇ粙搴撴闁靛骏绱曢崢鐢电磼閻愵剚绶茬€规洦鍓氱粋宥嗗鐎涙鍘遍梺鍐叉惈閸燁偅绂掓潏顭戞闁绘劕妯婇崕鏃堟煛娴ｇ鈧潡骞愭繝鍐ㄧ窞闁糕剝銇炴竟鏇㈡⒑缂佹ê鐏卞┑顔哄€濋幃鈥斥槈濮楀棛鍞甸柣鐘烘〃鐠€锕傚磿韫囨稒鐓熼煫鍥э攻濞呭懘妫佹径鎰厽婵☆垱瀵ч悵顏堟煕婵犲啫濮堥柟渚垮妽缁绘繈宕橀埞澶歌檸闂備浇顕栭崰姘跺礂濮椻偓楠炲啳顦圭€规洜鍘ч埞鎴﹀炊閵娧勬瘔闂傚倸鍊搁崐宄懊归崶顒夋晪闁哄稁鍘肩粣妤呮煛瀹ュ骸骞栫痪鎯х秺閺屾稖顦虫い銊ユ嚀缁绘艾鈹戦悙瀛樺鞍闁糕晛鍟村畷鎴﹀箻閸ㄦ稑浜炬繛鍫濈仢閺嬫瑧绱掗鐣屾噰闁靛棔绀侀～婊堝焵椤掑嫬绠栨繛鍡楃箚閺嬫棃鏌熺粙鍨彁鐟滃秹鍩為幋锔芥櫖闁告洦鍋傞弶顓㈡⒑缁嬪尅鏀婚柣妤冨█閻涱噣骞囬悧鍫濃偓閿嬨亜閹哄秶顦︾€殿喖娼″娲传閸曞灚效闂佹悶鍔岀紞濠傤嚕閹惰姤鏅濋柛灞剧〒閸橆亝绻濋姀锝嗙【婵☆偅鐟ラ埢宥夊幢濞戞瑧鍘撻梻浣哥仢椤戝懘鎮橀幘顔界厸閻忕偛澧介埥澶愭煃鐟欏嫬鐏寸€规洖宕灃濠电姳鑳剁粈澶娾攽閻樻鏆柛鎾寸箚閵囨劙宕橀鍡欘槸婵犵數濮村ú銈夋嫅閻斿摜绠鹃柟瀛樼懃閻忊晠鏌ｉ幘瀵糕槈闂囧鏌ㄥ┑鍡樺櫤闁诡垰鐗婇妵鍕晲閸涱喗鍎撳銈庝簻閸熷瓨淇婇懜鍨劅闁炽儱纾鎰節閻㈤潧浠╂い鏇熺矋娣囧﹪宕堕鈧悞鍨亜閹达絾纭剁紒浣哄厴閺屾稓鈧綆鍋勬慨宥夋煕閳规儳浜炬俊鐐€栫敮濠囨嚄閸洖鐓€闁哄洨鍠嗘禍婊勩亜閹捐泛浠﹂柛鐘愁焽閳ь剝顫夊ú蹇涘垂娴犲鈧線寮崼婵嗙獩濡炪倖鐗楃划搴∥ｉ崶顒佲拻濞撴埃鍋撴繛浣冲嫷娈介煫鍥ㄦ礀缁躲倕霉閻樺樊鍎愰柛瀣€块弻鐔兼焽閿曗偓閺嬨倗鐥幆褋鍋㈤柟顔筋殜閺佹劖鎯旈垾鑼嚬闂佽绻愬ù姘跺矗閸愵喖钃熼柨婵嗩槹閺呮煡鏌涢埄鍐噮闁伙絿鏁诲铏光偓鍦У椤ュ銇勯敃鈧悘姘跺箞閵娾晛鐒垫い鎺戝閻撱儲绻涢幋鐏活亪顢旈埡鍌ゆ?"
        if verbosity_bias == "short":
            return "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎娆戠┛闂傚倷绶氶埀顒傚仜閼活垱鏅堕崜褏纾奸柣妯挎珪鐏忣參鏌ｉ敐澶嬫暠缂佽櫣鏅划娆忊枎閻愵剛绉遍梻鍌欒兌閸嬨劑宕曢柆宥呯柈閻犳亽鍔忔慨鎶芥煏婢跺棙娅嗛柍閿嬪笒闇夐柨婵嗘川閹藉倹绻涢崗鐓庡妞ゎ厼娼￠幃鐑芥偋閸偅锛侀梻浣告惈閹虫挸鈻斿☉婊呬簷闂備礁鎲℃笟妤呭储妤ｅ啯鏅繛鎴欏灪閻撶喖骞栭幖顓炵仯缂佸鏁婚弻娑㈡偐閹颁焦鐤侀梺璇″櫙缁绘繂顕ｉ幘顔碱潊闁挎稑瀚敮妤呮⒒娴ｅ摜鏋冩俊妞煎妿缁牊绗熼埀顒€顕ｉ幖浣肝у璺侯儑閸樹粙姊洪崷顓炲妺婵炲弶鐗為。鍧楁⒒娓氣偓濞佳兠洪妶鍥ｅ亾濮橆偄宓嗙€规洘妞介弫鎾绘偐閹绘帞鐛╂俊鐐€栧Λ浣规叏閵堝應鏋旈柛婵勫劤绾句粙鏌涚仦鍓ф噯闁稿繐鐬肩槐鎺楊敋閸涱厾浠搁梺璇″灠鐎氫即銆佸☉銏″€烽梻鍫熺〒閵堬箓姊虹拠鎻掑毐缂傚秴妫濆畷鏉课旈崨顓狅紮闂佺粯鍨兼慨銈夋偂閺囩喆浜滄い鎾跺枎閻忋儱霉濠婂嫮鐭嬬紒缁樼洴瀹曘劑顢氶崨顔炬殽闂備礁鐤囬～澶愬垂閸ф绠栨繛鍡樻尰閸ゆ垶銇勯幒宥囧妽闁哥姵鐗犲缁樻媴鐟欏嫬浠╅梺绋匡攻濞茬喖寮绘繝鍥ㄦ櫜闁告侗鍨卞▓楣冩⒑閸︻厼顣兼繝銏★耿瀹曟﹢鍩€椤掆偓椤啴濡堕崱妤€衼缂備浇灏慨銈夊箚閺冣偓缁绘繈宕掑Δ浣规澑闂備胶绮崝鏍ь焽濞嗘挻鍊堕柣鏂垮悑閻撴洟鏌曟繛鍨姢缂佸妞介弻锝呪槈閸楃偞鐝濇繝娈垮枓閸嬫捇姊洪悙钘夊姤閻忓繑鐟х划璇差潩閼哥鎷洪梻鍌氱墛缁嬫挻鏅堕弴銏″€垫慨妯煎帶濞呭秶鈧娲樼换鍌烆敇婵傜鐐婇柨婵嗘噸婢规洟鏌ｉ悢鍝ユ噧閻庢凹鍘剧划鍫ュ焵椤掑嫭鈷戦柛婵勫劚閺嬪孩绻涚涵椋庣瘈闁搞劑绠栧顕€宕煎┑鍫О婵＄偑鍊栭弻銊ノｉ崼锝庢▌闂佸搫鏈粙鎴﹀煡婢舵劕纭€闁绘劕鍚€閸栨牗淇婇悙顏勨偓鏍ь潖閸︻厽鏆滄俊銈呭暞瀹曞弶绻涢幋鐐茬劰闁稿鎸搁埥澶娾枎濡厧濮洪梻浣规た閸樺ジ鏁冮鍫濊摕闁挎繂顦崘鈧悷婊冾儔瀹曟垿濮€閵堝棛鍘藉┑鐐村灥瀹曨剙鈻嶅鍥ｅ亾鐟欏嫭绀冮柨鏇樺灪娣囧﹪宕ㄦ繝鍐ㄥ妳闂佹寧绻傞幊蹇涙倶娓氣偓濮婃椽宕烽鐔锋畬闁诲孩姘ㄦ晶妤佺┍婵犲偆娼扮€光偓婵犲唭顏呯節閻㈤潧袨闁搞劍妞藉畷褰掑垂椤曞懏缍庣紓鍌欑劍钃卞┑顖氼嚟缁辨帒鈽夊鍡楀壉缂傚倸绉撮悧鎾愁潖閾忓湱鐭欓柟绋块閺€顓炩攽閻愬弶鍣烘繛鑼枎椤曪綁寮婚妷锕€娈濋梺鍓茬厛閸嬪嫰宕濋崨顓ф富闁靛牆楠搁獮妤呮煕閵娿儳鍩ｇ€殿喗鐓￠崺锟犲磼濠婂懐妲囬梻渚€娼ф蹇曞緤閸撗勫厹闁绘劦鍏欐禍婊勩亜閹炬鍟～鈺呮⒑闂堟稒顥為悽顖涱殘閹广垹鈹戦崱鈺傚兊濡炪倖鎸炬慨瀵告暜妤ｅ啯鈷掑ù锝囶焾椤ュ繘鏌涚€ｎ亝鍣介柟骞垮灲瀹曟﹢顢欓姀鐙€妲告い顓滃姂瀹曘劑顢涘鎰簥濠电姷顣槐鏇㈠磿閹寸姷涓嶉柟瀛樼贩濞差亝鏅濋柛灞剧☉娴滄姊洪崫鍕偍闁搞劍妞藉畷鎰版偨閸涘﹦鍙嗗┑鐘绘涧濡寮冲▎蹇婃斀闁炽儳鍋ㄩ崑銏ゆ煛鐏炵晫啸妞ぱ傜窔閺屾盯骞樼€涙娈ら梺鐟扮畭閸ㄨ棄鐣烽幒妤佸€婚柛鈩兩戝▍鏃堟⒒娴ｇ懓顕滅紒璇插€胯棟濞寸姴顑呴弸渚€鏌涢幇闈涙灍闁绘挸绻橀悡顐﹀炊瑜濋弨缁樼箾閸涱厽鍤囬柡宀€鍠栭、娆撴寠婢跺奔绱濇繝娈垮枛閿曘儱顪冩禒瀣祦闁哄稁鍘介崐鐑芥煙缂佹ê绗掗崯鎼佹⒒閸屾艾鈧悂宕愰崫銉㈠亾濮樼厧澧伴柍褜鍓氱喊宥咁熆濮椻偓閹箖鎮滈懞銉ヤ簻闂佺粯鎸稿ù鐑剿囬妸銉富闁靛牆妫欓ˉ鍡欐偖濞嗘挻鐓欏瀣閸斿绱掔紒妯兼创鐎殿喖鐖奸獮瀣攽閸パ€鍋撻鐐粹拺闁煎鍊曢弳鈧梺鎼炲劀閸滀焦孝婵犵數鍋涢顓㈠储瑜旈幃娲Ω閳哄倸浜楀┑鐐村灟閸ㄦ椽鎮￠弴鐔翠簻闁逛即娼ф禍婊兠瑰鍕煀妞ゎ叀鍎婚ˇ鍙夈亜閺囥劌寮柛鈹惧亾濡炪倖甯婄欢锟犲疮韫囨稒鐓曢柣妯诲墯濞堟洜绱掔紒妯尖姇缂佺粯绻堝畷鎺楀Χ閸涱噮鍚欏┑锛勫亼閸婃牕煤瀹ュ纾婚柟鎯х亪閸嬫挾鎲撮崟顒傤槰闁汇埄鍨辩敮锟犲灳閿曞倸惟闁宠桨鐒﹂妵婵嬫⒑閸涘﹤濮﹀ù婊庝簻铻為柣鎴ｅГ閳锋帡鏌涚仦鎹愬闁逞屽墰閸忔﹢骞婂Δ鍛唶闁哄洦銇涢崑鎾绘晝閸屾岸鍞堕梺闈涱槶閸庨亶鎮靛Ο渚富闁靛牆妫楃粭鎺楁倵濮樼厧寮€规洘鍨块弫宥夊礋椤掆偓閺嬫垿姊洪崫鍕偓钘夆枖閺囥垹姹查柨鏃傛櫕缁♀偓闂傚倸鐗婄粙鎺楁晬瀹ュ鐓曟慨姗嗗墻閸庡繑銇勯鈩冪《闁圭懓瀚粭鐔碱敍濮橆剙顥愰梻鍌欑閹诧繝鈥﹂崶顒€鏋侀柛婵勫劜椤洟鏌熼幆褏鎽犲┑顖涙尦閺屾盯骞橀弶鎴犵シ闂佸憡鎸稿畷顒勨€旈崘顔嘉ч柛鈩冾殘娴犳悂姊洪懡銈呮毐闁哄懐濞€閻涱噣宕橀鑲╁姶闂佸憡鍔︽禍顏勵瀶椤曗偓濮婃椽宕ㄦ繝鍕ㄦ闂佹寧娲╃粻鎾崇暦閵忋倖顥堟繛鎴ｉ哺鐎靛矂姊洪棃娑氬婵☆偅鐟╅崺娑㈠箳濡や胶鍘卞┑掳鍊撶粈渚€鍩㈤弴鐕佹闁绘劕妯婇崕蹇涙煃鐟欏嫬鐏存鐐叉喘椤㈡绗熼崶褎鏆旈梻鍌氬€搁崐椋庣矆娓氣偓楠炲鍨剧搾浣规そ閺佸啴宕掑顒傗偓顓㈡⒑鐟欏嫷鍟忛柛鐘崇缁嬪顓奸崱娆戭啎闂佺懓顕崑鐔煎箠閳ь剚绻涚€涙鐭嬬紒顔芥崌瀵鎮㈤崗鐓庘偓缁樹繆椤栨繃顏犲ù鐘虫尦濮婃椽鏌呴悙鑼跺濠⒀屽灦閺岀喖顢欓悡搴樺亾閸喚鏆︽繛宸簻閻掑灚銇勯幒宥夋濞存粍绮撻弻鐔兼倻濡櫣浠撮梺閫炲苯澧柟璇х磿缁骞掗幘瀵哥Ф闂侀潧顭粻鎴濐嚕閹稿海绡€闁汇垽娼у瓭闂佺懓鍟跨换姗€銆侀弮鍫熷亹闁汇垻鏁搁敍婊堟煛婢跺﹦澧戦柛鏂跨灱缁參骞掑Δ浣瑰殙闂佹寧绻傞ˇ浼存偂閺囩喓绡€闂傚牊绋掗ˉ婊勩亜韫囨挾鎽犵紒缁樼洴瀹曟宕楅悡搴ｏ紦婵犳鍠栭敃锔惧垝椤栫偛绠柛娑欐綑缁€鍫ユ煙缂佹ê绗氶柛瀣濮婄粯鎷呴崨濠冨創濡炪倧瀵岄崹鍫曞箖濡　鏀介悗锝呭缁嬪繘姊洪幖鐐插妧闁逞屽墴瀵劑鎳為妷锝勭盎闂佸搫鍟崐鍫曞焵椤掆偓椤戝棜鐏嬪┑顔斤供閸樿櫣鎹㈤崱妯镐簻闁规壋鏅涢悘鈺傘亜韫囷絽骞楅柕鍥у婵偓闁宠棄鎳撻埀顒冩硶閳ь剝顫夊ú姗€銆冩繝鍥х畺闁斥晛鍟崕鐔兼煥濠靛棙宸濈€规挷绶氬缁樻媴缁涘娈梺鍛婂灩閺咁偆妲愰悙鍝勫耿婵炴垶顭囬ˇ顓炩攽閻愬弶顥為柛銊ョ埣瀵?"
        return "濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ゆい顓犲厴瀵鏁愰崨鍌滃枎閳诲酣骞嗚椤斿嫮绱撻崒娆掑厡濠殿喗鎸抽幃妯侯潩鐠轰綍锕傛煕閺囥劌鏋ら柣銈傚亾闂備礁婀遍崑鎾诲箚鐏炶娇娑㈡倷閻㈢數锛濇繛杈剧悼閺咁偊宕奸鍫熺厱濠电姴鍟扮粻鐐碘偓娈垮枛椤兘骞冮姀銈嗘優闁革富鍘鹃崢顖炴⒒娴ｇ顥忛柣鎾崇墦瀹曟娊顢氶埀顒€鐣峰┑鍥х窞闁归偊鍘搁幏娲⒑閸涘﹦鈽夐柨鏇畵楠炲﹪宕橀鍡欙紲缂傚倷鐒﹂敃顐︽嚀鐠恒劉鍋撳▓鍨灈妞ゎ厾鍏橀獮鍐閵堝棙鍎梺闈╁瘜閸欏繒妲愰弻銉︹拻濞撴埃鍋撴繛浣冲懏宕查柟鐑樻尰閸欏繘鏌ｉ姀鐘冲暈闁稿﹤鐖奸弻娑㈩敃閻樻彃濮曢梺鎶芥敱閸ㄥ湱妲愰幒鏂哄亾閿濆骸骞栭柛鏂跨仛閵囧嫰顢曢鍌滄殼闂佸搫鏈惄顖氼嚕椤掑倹宕夐柕濠冨姂閸婃繈寮婚悢鑲╁祦闁割煈鍠氭禒濂告⒑鐎圭姵顥夋い锕€鐏氶幈銊╁焵椤掑嫭鐓熸俊顖涙た閸熷繘鏌涘顒佸櫤缂佺粯绻堥幃浠嬫濞戞鎹曟繝纰樻閸嬪懘銆冮崼銉ョ闁靛繈鍊曠粻鎶芥煙妤ｅ喚鏉烘繛鏉戝濮婃椽宕楅懖鈹垮仦闂佸搫鎳忕换鍕珶閺囩喓闄勯柛娑橈功閸橀潧顪冮妶鍡欏ⅹ婵☆偅顨婂畷顖炴偐鐠囪尙顔囬梺鍛婂姦娴滅偟澹曢挊澶堚偓鎺戭潩椤掍焦鎮欏┑鐐叉噺閿曘垽寮诲☉銏犖╅柕澹啰鍘介梻浣虹帛娓氭宕抽敐鍛殾濠靛倻顭堝敮闂侀潧顦花鍫曞疾閻樿钃熼柡鍥╁枎缁剁偞淇婇婊冨妺闁诲繐绉归幃妤呮倷閻熸壋鍋撻弽褜娓婚柦妯侯樈濞兼牠鏌ц箛鏇熷殌閻庡灚鐓￠弻锟犲炊閳轰椒绮堕梺鍐插槻椤︻垶鈥旈崘顔嘉ч柛鎰╁妼椤牓姊虹涵鍛彧闁挎洏鍨藉顐﹀箛閻楀牆鈧嘲銆掑鐓庣仭闁哄懏绻堝娲箰鎼淬埄姊块悶姘懇閺岀喖鏌ㄧ€ｎ偁浠㈠┑顔硷攻濡炶棄鐣烽妸锔剧瘈闁告洦鍘鹃弳銈夋⒑鐠囨彃顒㈤柛鎴濈秺瀹曪綁宕橀鐕傜磽闂傚倷鑳剁划顖炲礉濡ゅ懌鈧倹绂掔€ｎ亞锛涢梺瑙勫礃椤曆呯矆閸屾凹鐔嗛悹铏瑰皑濮婃顭跨憴鍕缂佽鲸鎹囧畷鎺戔枎閹搭厽袦婵＄偑鍊栭崹闈浳涘┑瀣ㄢ偓渚€寮借閺嬪酣鏌熼幆褍鏆遍柟顖滃仱濮婃椽宕崟顒€鍋嶉梺鎼炲妽濡炰粙骞冮敓鐘插嵆闁绘梻绻濈花濠氭⒑鐟欏嫭绶插褍娴风划娆撴嚒閵堝洨锛滈梺閫炲苯澧撮柛鈹惧亾濡炪倖甯掔€氼參鍩涢幋鐘电＝濞达綀鍋傞幋鐘辩剨濞寸厧鐡ㄩ悡鐔兼煃閸濆嫸宸ラ柣蹇ュ閳ь剚顔栭崰娑㈩敋瑜旈崺銉﹀緞婵犲孩鍍靛銈嗗姧缁茶姤鍒婃导瀛樷拻濞达絽鎲￠崯鐐烘煙缁嬫寧顥㈢€规洏鍔戦、娑橆潩椤掑倻鎳嗛梻鍌氬€搁崐鎼佸磹妞嬪孩顐芥慨姗嗗墻閻掍粙鏌ゆ慨鎰偓鏇犳閵堝應鏀介柣妯虹枃婢规鐥幑鎰《闁逞屽墲椤煤閺嶎灐娲晝閸岋妇绋忛梺鍝勬储閸ㄦ椽鎮″▎鎾寸厵妞ゆ牕妫楅幊蹇涘箟閸忚偐绡€婵炲牆鐏濋悘锟犳煙閸涘﹤鈻曟鐐插暙閻ｏ繝骞嶉搹顐も偓濠氭椤愩垺澶勯柟灏栨櫆鐎靛ジ鍩€椤掑嫭鈷掑ù锝呮啞閸熺偤鏌ｉ悢鏉戝姎閾荤偞淇婇妶鍛櫝闁逞屽墯濡啫鐣峰鈧、娆撳床婢诡垰娲﹂悡鏇㈡煃閳轰礁骞樻い蹇撶吇閸ヮ剙鐓涢柛娑卞枓閹锋椽姊洪崨濠勨槈妞ゎ収鍓熼幃鐐寸鐎ｎ偆鍘搁梺鍛婄矆缁€浣圭閻愮儤鐓曢柟鐑樻尭缁椦囨煃瑜滈崜銊х礊閸℃顩查柛顐ｆ礀鐟欙箓鎮楅敐搴℃灍闁绘挻娲樼换婵囩箾閹傚闂備胶绮敮顏嗙不閹达负鈧懏绺界粙璇锯晠鏌嶉崫鍕偓鎼佸焵椤掑倹鏆柡灞剧缁犳盯骞欓崘鈹附绻涚€涙鐭掔紒鐘崇墪椤繐煤椤忓懐鍔甸梺缁樺姌鐏忣亞鈧碍婢橀…鑳槼闁瑰憡濞婂濠氭偄绾拌鲸鏅╅梺绋跨箳閸樠勭閹绢喗鈷戠紒顖涙礃閺夊綊鏌涚€ｎ偅灏い顏勫暣婵″爼宕卞Δ鍐噯闂佽瀛╅崙褰掑矗閸愵喖鏄ユ繛鎴欏灩缁狅綁鏌ㄩ弮鍌涙珪闁告ê宕埞鎴︽偐缂佹ɑ閿┑鈽嗗亝椤ㄥ﹪銆侀弮鍫濈厸闁告侗鍠氶崢鎼佹⒑缁洖澧查柣鐔村劜缁傛帡鏌嗗鍡欏幐闁诲繒鍋涙晶钘壝洪弶鎴旀斀闁斥晛鍟崐鎰攽閿涘嫭鐒挎い锕佷含缁辨帡顢欓懖鈺€绮电紓浣虹帛閻╊垶寮幇鏉垮窛妞ゆ棁濮ら崐鐑芥⒒娴ｇ懓顕滄繛璇ч檮缁傚秹顢旈崟闈涙婵犵數濮甸懝楣冪嵁閵忊€茬箚闁靛牆鎷戝銉╂煙椤旇棄鐏存慨濠呮閸栨牠寮村Δ鈧禍鍓р偓瑙勬礀濞层劑顢欐径鎰厽閹兼番鍨兼竟姗€鏌曢崼銏╃劸妞ゎ偄绻掔槐鎺懳熺拠宸偓鎾绘⒑閸涘﹦鈽夐柨鏇樺妿濞戠敻鍩€椤掍椒绻嗛柣鎰典簻閳ь兙鍊濆畷銏＄附閸涘﹤浜遍梺绯曞墲缁嬫帞绮婚幒妤佲拻濞达綀娅ｇ敮娑㈡煕閵娧冨付閾荤偤鏌涢弴銊ョ仭闁稿鍊块弻宥夊Ψ閿曗偓婢ь垶鏌ｉ弬鎸庮棦闁哄被鍊濋獮鏍ㄦ媴鐟欏嫰鏁┑鐘愁問閸犳牠鎮ч幘璇茶摕闁挎繂顦粻濠氭偣閾忚纾柨婵嗘川绾捐偐绱撴担璇＄劷婵炲弶鎸抽弻鐔风暦閸ヮ灝锝夋煥濞戞瑥濮囬柍瑙勫灴瀹曞崬顫滈崱妤佹殺闂傚倸鍊搁崐宄懊归崶顒夋晪鐟滃酣銆冮妷銊х杸闁哄洨濮崇粭澶愭⒑鐟欏嫬绀冩い鏇嗗洦瀚呴柣鏂垮悑閻撶喖鏌￠崘銊モ偓鐢稿箯閿熺姵鐓涘ù锝夋交闊剟鏌＄仦璇测偓鏍箞閵娾晛绠涙い鎴ｆ娴滅偓淇婇妶鍛櫤闁稿鍊块弻鐔兼倷椤掆偓婢ь垱绻涢幘鎰佺吋闁哄本娲熷畷鐓庘攽閸℃ɑ顔勯梻浣筋嚙濞存碍绂嶅┑鍫熷床婵炴垯鍨洪崵鎴炪亜閹哄棗浜鹃梺鍝勵儐缁嬫捇鍩€椤掍緡鍟忛柛锝庡櫍瀹曟垶绻濋崒婊勬闂佸湱鍎ら〃鍡涘磹閻戣姤鐓涘璺侯儏閻忊晜淇婄紒銏犳灈闁宠鍨块幃鈺咁敊閼测晙绱樻繝鐢靛仜椤︿即鎯勯鐐叉瀬闁告劦鍠栧洿婵犮垻娅㈢粻鎴λ囬悽鍝ュ祦闁圭儤鍤﹂弮鈧幏鍛村矗婢跺浼滈梻鍌氬€烽懗鍫曗€﹂崼銉ュ珘妞ゆ帒瀚崑锛勬喐韫囨洖鍨濋柨婵嗩槸缁秹鏌涢銈呮灁闁告ɑ鎹囬幃宄邦煥閸曨厾鐓夐悗瑙勬礃缁矂鍩ユ径鎰潊闁绘顣槐杈ㄧ節閻㈤潧浠﹂柛顭戝灦瀹曠懓煤椤忓嫬鎯為梺褰掑亰閸樿绂嶅鍫熺厸鐎广儱鍟俊鍧楁煃椤栨稒绀冪紒缁樼洴瀹曘劑顢涘锝嗙€伴梻浣告惈閻ジ宕版惔銊ョ厺闁规崘顕ч崹鍌涖亜閺冨倹娅曞ù婊冨⒔缁辨挻鎷呴崫鍕闂佺瀛╂繛濠冧繆閸撲胶鐭欐繛鍡樺劤濞堛劑姊洪崜鎻掍簼婵炲弶鐗犻弻瀣炊閵娧咁啎闂佺懓顕导婵嬵敂閸埃鍋撻弽顓為唶婵犻潧鍟弬鈧梻浣虹帛閸旀洟鎮洪妸鈺佺？婵°倕鎳忛悡鏇㈡煟濡澧繛鍫熺矒閺屾洟宕卞Δ鈧弳锝呪攽閿涘嫬鍘撮柛鈺嬬節瀹曟帒顫濋敐鍛闂佺粯鍨兼慨銈夋偂濞嗘垹妫柡澶婄仢閼歌顨ラ悙杈捐€块柡灞剧洴瀵噣宕掑顒€绠ｆ繝娈垮枛閿曘儱顪冩禒瀣摕闁告稑鐡ㄩ崐鐑芥煠閼圭増纭炬い蹇ｅ幗缁绘繈鍩涢埀顒勫磼濮橆剛銈梻浣告惈婢跺洭宕滃┑瀣闁告稒娼欑粈鍫ユ煠绾板崬澧柟顔藉灴閺岋絾鎯旈姀鈺佹櫛闂佸摜濮甸〃濠囧箖閿熺姴鐏抽柟棰佺濞堛劍绻濋悽闈浶ｉ柤瑙勫劤閺侇噣姊绘笟鈧褔鏁嶈箛鏇氭勃闁归攱顭囬崰鎰崲濠靛鍋ㄩ梻鍫熺◥缁泛顪冮妶鍡樺闁告ü绮欓獮鍫ュΩ閳轰胶顔掑銈嗘礀閹冲繘寮查悙鐑樷拺缂侇垱娲栨晶鑼磼鐎ｎ偄鐏撮柟顕嗙節瀵挳濮€閿涘嫬骞嶉梺鍝勵槸閻楁挾绮婚弽褜鐎舵い鏇楀亾闁哄矉缍侀獮妯尖偓闈涙啞閸ｄ即姊洪崫鍕潶闁稿﹥娲熷﹢渚€鏌ｆ惔顖滅У闁稿鎳橀幃鐢稿籍閳ь剛鎹㈠☉姘ｅ亾閻㈡鐒鹃弽锛勭磽娓氬洤鏋熼柟鐟版搐椤曪絿鎷犲ù瀣潔闂侀潧绻掓慨鐢杆夊┑瀣厽闁绘ê寮舵径鍕磼娴ｈ灏︾€规洘鍨块獮姗€寮妷锔芥澑闂佽鍑界紞鍡樼閿濆绠洪柡鍥╁亹閺€浠嬫煟閹邦厽缍戦柣蹇ョ畵閺屾盯鍩℃担鍛婃閻庤娲橀崹鍧楃嵁濡偐纾兼俊顖滅帛閻濇娊姊虹涵鍛汗閻炴稏鍎甸崺鈧い鎺嶇婢ь垱绻涢懝閭﹀殭闁宠鍨块幃娆忣啅椤斿吋顔嶅┑鐘愁問閸犳岸寮幖浣哥闁圭儤鍩堥崥瀣熆鐠哄ソ锟犳晝閸屾稓鍘遍梺鍝勬储閸斿矂鎮橀柆宥嗙厸濞达絽鎲￠崰姗€鏌″畝瀣М妤犵偛娲、姗€鎮㈤搹鍏夋瀼闂傚倷绀侀幖顐︻敄閸ャ劎绠鹃柍褜鍓氶幈銊︾節閸涱噮浠╅梺褰掝棑婵炩偓闁搞劑绠栭幖褰掝敃閵堝嫮鏁栫紓鍌氬€搁崐椋庢閿熺姴绐楁俊銈呮噺閸嬶繝鏌曟径鍡樻珕闁稿鏅犻弻锝夊箣閿濆棭妫勯柟顖滃枛濮婃椽骞愭惔銏㈠弳婵犫拃鍌滅煓闁诡垯绶氬畷濂稿Ψ閿旇瀚奸梻浣告啞缁嬫垿鏁冮妶鍡樺弿闁逞屽墴濮婃椽宕崟顒€娅ょ紓浣筋嚙濡繃淇婇悽绋跨疀闁哄顕抽埡鍛厓闁告繂瀚埀顒傛暬楠炲繒绱掑Ο鑲╊啎闁哄鐗嗘晶浠嬪箖婵傚憡鐓熼柍鈺佸暞椤ュ牏鈧娲熷褔鍩㈡惔銊ョ闁绘顣槐鑼磽閸屾艾鈧兘鎮為敃鍌涙櫔婵犵數鍋為幆宀勫窗濮樿泛鐒垫い鎺戝枤濞兼劖绻涢崣澶涜€跨€规洖缍婂畷绋课旈埀顒傜不閺嶃劎绠鹃柛鈩兩戠亸顓灻归懖鈺佲枅闁哄本鐩鎾Ω閵夈儰绱熺紓鍌欐祰娴滎剟寮拠宸綎缂備焦蓱婵绱掑☉姗嗗剱缂傚秴鐗撳铏圭矙閸ф鈧鏌涘顒夊剶妤犵偛鐗撴俊鎼佸煛娴ｅ嫇鍐剧唵閻犺櫣灏ㄩ崝鐔兼煥濞戞瑧鎳囬柡宀嬬秮閹晠鎮滃Ο绯曞亾閸愵喗鍋ｉ柍褜鍓熼弫鍐磼濞戞ü绨婚梻浣虹《閸撴繄绮欓幒妤€纾婚柨婵嗘啒閺冨牊鏅濆〒姘躬閻涙粓姊洪柅鐐茶嫰閸樻挳鏌涚€ｎ偅灏扮紒缁樼箓閳绘捇宕归鐣屼邯婵犵數鍋涢惇浼村礉閹达妇宓佸鑸靛姇缁犵懓霉閿濆洦鍤€濞存粓浜跺娲礈閹绘帊绨肩紓浣筋嚙鐎氫即骞冮悜钘夎摕闁靛鑵归幏铏圭磽娴ｅ壊鍎愭い鎴炵懇瀹曟洟骞囬悧鍫㈠幈闂侀潧顭堥崕鏌ュ磻閵壯€鍋撳▓鍨灕妞ゆ泦鍥舵晣濠靛倻顭堥柋鍥ㄣ亜閹板墎绉甸柍褜鍓欏ú顓烆潖缂佹ɑ濯撮柛娑橈工閺嗗牓姊虹憴鍕€愮紒鐘崇墪閻ｇ兘鎮ч崼鐔峰妳闂侀潧顭粻鎴炵婵傚憡鍊甸柣鐔告緲椤忣參鏌涚€ｎ亷韬柟顕嗙節婵＄兘鍩￠崒婊冨箞闂備浇顫夊妯绘櫠鎼达絿鐭欏┑鐘崇閻撶喖骞栫划瑙勵潑闁绘挸鍚嬮幈銊︾節閸涱噮浠╅梺鐟板级閹稿啿鐣烽悢纰辨晝闁靛繒濮岄幋鐘电＝濞达絿顭堥埛鏃堟煣韫囨捇鍙勭€规洩缍佸畷姗€鈥﹂幋婵囶吙濠电姷鏁告慨鐢告嚌妤ｅ啯鐓侀柛銉墯閻撳繐顭块懜鐢殿灱闁告艾鍊块弻鐔兼煥鐎ｎ偁浠㈠┑顔硷功缁垳绮悢鐓庣倞鐟滃瞼鑺辨禒瀣拺缂佸顑欓崕鎰版煟閳哄﹤鐏︽鐐诧躬閹垻鍠婃潏銊︽珫婵犵數鍋為崹鍫曟偡閿曞倹鍋熼柣鎴ｅГ閳锋垿鏌涢敂璇插绩婵＄偓鎮傞弻娑㈡偐閹颁焦鐤侀梺璇″枓閳ь剚鏋煎Σ鍫ユ煏韫囧ň鍋撻弬銉ヤ壕闁割偅娲橀悡鐔兼煙闁箑骞栫紒鎻掝煼閺屽秹鏌ㄧ€ｎ偀鎷圭紓浣虹帛閻╊垶鐛幘璇茬闁哄啠鍋撻柟鑼帶椤啴濡堕崘銊ノ╅梺绋挎捣閺佸鐛崘銊㈡瀻闁规儳纾悡鎴炵節閵忥絾纭鹃柨鏇樺劦閹ɑ鎯旈～顓犵畾闂佺粯鍔︽禍婊堝焵椤掍礁鐏寸€规洜鎳撶叅妞ゅ繐鍊甸崑鎾诲礃閳哄啰鐦堥梺鎼炲劀閸曨儷姘舵⒒娓氣偓閳ь剛鍋涢懟顖涙櫠椤栫偞鐓忛柛銉戝喚浼冨Δ鐘靛仦鐢繝鐛€ｎ亖鏀介柟閭︿簼閸嬪懎鈹戦悩鎰佸晱闁哥姵鐩敐鐐村緞閹邦厼浜楅梺鐐藉劜閸撴艾顭囬弽銊х鐎瑰壊鍠曢幉楣冩煛娴ｅ憡顥㈤柡灞界Х椤т線鏌涢幘瀵搞€掗柛鎺撳浮瀵噣宕奸悢铚傜紦闂備礁鎲＄粙鎴︽晝閵堝棛顩叉俊銈呮噺閳锋垹绱撴担鑲℃垿鎮￠妷鈺傜厱婵﹩鍓﹂崕鏃堟煙椤曞棛绡€濠碉紕鍏橀弫鍌炲礈瑜忓Σ鍥⒒閸屾艾鈧悂鎮ф繝鍕煓闁圭儤顨嗛弲顒傗偓骞垮劚濡梻鎹㈤崱娑欑厱婵炲棗娴氬Σ褰掓煏閸ャ劎绠為柡灞糕偓宕囨殕閻庯綆鍓涜ⅵ闂備浇妗ㄩ悞锕傚礉濞嗗繒鏆﹀┑鍌氭啞閸嬪棗霉閿濆懎妲婚柟钘夘儔濮婂宕掑▎鎴犵崲闂侀€炲苯澧伴柛瀣洴閹崇喖顢涘☉娆愮彿濡炪倖鐗楃粙蹇旂濠婂牊鐓涢柛鎰剁到娴滈箖姊虹紒姗嗘畼濠殿喗鎸抽幃楣冩煥鐎ｎ亶鍤ら梺鍝勵槹閸ㄩ潧鐣甸崱娑欌拺闂傚牊绋撶粻鍐测攽椤旀儳鍘撮柕鍡曠窔瀹曘劎鈧稒菤閹疯櫣绱掔紒銏犲箹闁瑰啿绻掑☉鐢告倷椤戝彞绨诲銈嗗姧缁插墽绮堢€ｎ喗鐓曢柍瑙勫劤娴滅偓淇婇悙顏勨偓鏍垂閻撳簶鏋栭柡鍥ｆ嚍閸ヮ剚鏅濋柛灞剧〒閸樻捇姊洪懞銉冾亪藝閽樺）锝夊川婵炲じ绨诲銈嗗姧缁插潡鎯岄幒鏂哄亾鐟欏嫭绀€鐎规洦鍓熼崺銏℃償閵堝洨鏉搁梺鐟板⒔椤ユ劗娆㈤姀銈嗏拻闁稿本鑹鹃埀顒佹倐瀹曟劖顦版惔锝囩劶婵炴挻鍩冮崑鎾搭殽閻愬樊妯€闁搞劌澧介幖鐐媴鐟欏嫨浠㈤梺杞扮閸熸潙鐣烽幒鎴僵闁规彃顑囬獮銏ゆ⒒閸屾瑨鍏岀痪顓炵埣瀹曟粌鈹戦崼銏㈢厯闂佺鎻粻鎴犲婵傚憡鐓忓┑鐐靛亾濞呭懐绱掗悪娆忔处閻撴洘銇勯幇鍓佹偧妞わ絽寮剁换娑㈠川椤撶喎绐涢梺姹囧労娴滎亜鐣烽敐澶娢ㄧ憸蹇涙偂閹剧粯鈷戦柛婵嗗濠€鎵磼鐎ｎ偅灏扮紒鍌涘浮閺佸啴宕掑槌栧敼闂備礁缍婇崑濠囧礈閿曗偓铻為柣鏂垮悑閳锋帒銆掑锝呬壕闂侀€炲苯澧伴柛瀣洴閹崇喖顢涘☉娆愮彿闁诲孩绋掕彠濞存粍绮撻弻鏇熷緞濞戙垺顎嶉柣蹇撴禋閸欏啴寮诲鍥ㄥ珰闁哄被鍎卞鐗堢節濞堝灝鏋撻柛瀣崌濮婃椽妫冨☉姘暫濠碘槅鍋呴悷銉╁煝瀹ュ顫呴柕鍫濇閹疯櫣绱撻崒娆戝妽闁靛棛鍋ら獮瀣晲閸愌勭潖闂備礁鎲￠崝锕傚窗閺嶎偄顥氶柤濮愬€愰崑鎾荤嵁閸喖濮庡┑鈽嗗亝缁嬫挸顕ｈ閸┾偓妞ゆ帒瀚埛鎺楁煕鐏炵偓鐨戝褎绋撶槐鎺斺偓锝庡亜閻忔挳鏌涢埞鎯т壕婵＄偑鍊栫敮濠囨倿閿曞倸纾归柟閭﹀弾濞堜粙鏌ｉ幇顒佲枙婵☆垪鍋撻梻浣芥〃閻掞箓骞戦崶顒€绠栭柍鍝勬噺閸ゆ垶銇勯幒鎴姛闁告艾缍婂濠氬磼濞嗘劗銈板銈庡亜椤﹂潧鐣烽弴銏犵闁兼亽鍎遍埀顒€鐖奸弻娑㈩敃閻樻彃濮庣紒鐐劤椤兘寮婚悢鐓庣闁归偊鍓欓幆鐐烘倵鐟欏嫭灏紒鑸靛哺瀵鈽夐埗鈹惧亾閿曞倸绠ｆ繝闈涙川娴滎亜鈹戦悩鎰佸晱闁哥姵鐗犻弻濠囨晲閸滀焦缍庡┑鐐叉▕娴滄繈宕戦敓鐘崇厸濠㈣泛顑呴婊勭濞戞瑤绻嗛柣鎰典簻閳ь剚鐗犲畷褰掓偨閺夊棗娲、娑㈡倷閺夋垳鎮ｉ梻浣虹帛閸ㄥ吋鎱ㄩ妶澶婄；闁靛ě鍛紲闁诲函缍嗘禍鐐寸閵忊懇鍋撶憴鍕碍婵☆偅绻傞～蹇撁洪鍜佹濠电偞鍨崹璇茬暦椤忓棛纾藉ù锝勭矙閸濈儤绻涢懠顒€鏋庨柣锝囧厴婵偓闁靛牆鎳愰鎺旂磽閸屾瑧鍔嶉柨姘归悪鈧崢濂稿煘閹达附鍋愰悹鍥囧啩绱ｉ梺璇插閸戝綊宕抽敐澶婄畾鐎光偓閸曨偆顔婇梺鍝勫€搁幖顐ｇ妤ｅ啯鍋℃繛鍡楃箰椤忣亞绱掗埀顒勫礃椤忓棛锛滃銈嗘婵倕鐣风仦缁㈡闁绘劖褰冮弳锝呪攽椤旂懓浜鹃梻渚€娼ч悧鍡椢涘Δ浣侯洸婵°倕鎳忛悡娆撴煕韫囨艾浜归柡鍡橈耿閺屾盯濡搁妷顔惧悑闂佺硶鏂侀崑鎾愁渻閵堝棗绗掓い锔诲灡閺呭爼骞橀鐣屽幍濡炪倖姊婚悺鏂库枔濠婂牊鐓熸繛鎴濆船濞呭秶鈧娲栫紞濠囥€佸▎鎾村亗閹兼惌鍠楃紞鎾绘⒒閸屾艾鈧兘鎳楅崼鏇樷偓浣圭節閸屾鐎洪梺鍝勬储閸ㄥ湱绮堟径瀣闁糕剝顨嗙粋瀣煕閵堝棙绀嬮柡宀€鍠栭獮鍡涙偋閸偅顥夋俊銈囧Х閸嬫垿宕归搹瑙勫床婵炴垯鍨圭粻锝夋煟閹邦剛浠涢柛锝庡櫍濮婃椽宕ㄦ繝蹇氣偓鍨瑰鍡樼【妞ゎ偄绻橀幖鍦喆閸曨偅鐎梻浣告啞濞诧箓宕滃☉銏犵闁跨喓濮甸埛鎴︽煕濞戞﹫宸ラ柣鎺戠秺閺屾稓鈧綆鍋呯亸鐢电磼鏉堛劍灏伴柟宄版嚇濡啫鈽夊鍡樼秱婵犵數濮甸鏍窗閹捐纾规繝闈涙矗缁诲棝鏌ｉ姀銏╃劸缂佲偓鐎ｎ偁浜滈柡宥冨妿椤ｅ弶銇勯妷锔剧疄婵﹨娅ｇ划鏃堝幢濡も偓椤忓瓨绻涢崼鐔糕拻闁逞屽墯椤旀牠宕板Δ鈧…鍨潨閳ь剟宕洪悙鍝勭闁挎梻绮弲鈺冪磼缂併垹寮柡鈧柆宥呮瀬闁诡垎鈧弨浠嬫煥濞戞ê顏╁ù鐘櫆娣囧﹪顢曢姀鐙€浼冮梺璇″櫍缁犳牠骞冨鍛┏閻庯綆鍋呭▍鍥⒒娴ｇ懓顕滄繛鎻掔Ч瀹曟垿骞橀崜浣猴紲闂侀€炲苯澧伴柍褜鍓ㄧ紞鍡涘磻娴ｅ湱顩叉繝濠傜墛閻撴瑥霉閻撳海鎽犳繛鎳峰厾鐟邦煥閸曞灚鐣肩紓浣介哺鐢顭囪箛娑樜╃憸蹇涙偪閸曨偀鏀芥い鏃傘€嬮崝鐔虹磼椤曞懎鐏︽鐐茬箻瀹曘劑顢涘☉妯荤€梻浣告啞濞诧箓宕戦崒鐐蹭紶婵°倕鎳忛埛鎺懨归敐鍛暈闁哥喓鍋ら弻锛勪沪鐠囨彃顫囧銈冨灪閻楁顕ラ崟顒傜瘈闁告洦鍓氶鏇㈡⒒娴ｈ姤纭堕柛鐘虫尰閹便劎鈧潧鎽滈惌鍡涙煕閹伴潧鏋熼柣鎾跺Х閻ヮ亪寮堕崹顔垮煘婵犫拃灞界仭缂佺粯鐩畷濂稿Ψ瑜忛弳顐⑩攽椤旂》鏀绘俊鐐舵铻為柛鎰╁妷濡插牊鎱ㄥ鈧涵鎼佸船閸濆嫧鏀介柣妯诲墯閸熷繘鏌涢敐搴℃珝鐎规洏鍨介幃鈩冩償閿涘嫨鍋掗梻鍌氬€风粈浣圭珶婵犲洤纾诲〒姘ｅ亾鐎规洘娲熷濠氬Ψ閿曗偓娴滄妫呴銏″缂佸鎹囧畷锝夊箻缂佹鍘遍梺闈涱檧缁茶姤淇婇悾宀€纾奸柍褜鍓熼崺鈧い鎺戝閻撴洟鏌ｉ弬鎸庡暈闁稿﹥鍔栭幈銊︾節閸愨斂浠㈠Δ鐘靛仦閸旀牠骞嗛弮鍫熸櫜闁稿本鍑瑰鎾剁磽閸屾艾鈧绮堟笟鈧、鏍幢濞戞ê鐎梺绉嗗嫷娈旈柡鍕╁劦閺岋綁骞囬浣瑰創缂備胶濯寸紞渚€寮婚妸鈺佺睄闁稿本绮岀粭锟犳⒑閸濆嫭鍣抽柡鍛Т椤繐煤椤忓嫪绱堕梺鍛婃处閸嬧偓闁稿鎹囧畷濂稿即閻愮绱梻浣筋潐瀹曟﹢宕洪弽顓ф晝濞寸姴顑嗛悡鐔兼煏韫囨洖校闁哥喓鍋ら弻宥夋煥鐎ｎ亞浠肩紓浣介哺鐢偤鍩€椤掑﹦绉甸柛瀣浮瀹曟洟濡烽埡鍌滃幈闁硅壈鎻槐鏇犵不閹绘崨搴ㄥ炊瑜濋煬顒併亜閵忊剝绀嬮柡浣瑰姍瀹曞爼鍩￠崘鈺傜钒闂傚倸鍊风欢姘焽瑜嶈灋闁哄啫鍊归鑺ユ叏濮楀棗澧婚柛銈嗘礃閵囧嫰寮村Δ鈧禍楣冩⒑缁洘鏉归柛瀣尭椤啴濡堕崱妤€娼戦梺绋款儐閹稿濡甸崟顖ｆ晣闁绘劕顕埞娑氱磽娴ｅ搫校缂佸鍨块崺銉﹀緞婵炪垻鍠庨埞鍐倷椤掍胶褰囬梻浣烘嚀瀵爼鎮洪弴鐘典笉婵炴垶菤濡插牓寮堕崼娑樺婵炲懏鎹囧缁樻媴閸涘﹥鍎撳┑鐐茬湴閸ㄨ棄鐣烽悷鎳婃椽顢旈崟顓炲箞闂備胶鎳撻顓熸叏妞嬪骸顥氶柛蹇曨儠娴滄粓鏌″鍐ㄥ闁愁垱娲滅槐鎺楀焵椤掑嫬绀冮柍鐟般仒缁ㄨ顪冮妶鍡楀Е婵狀澀绶氶悡顒勵敆閸曨剛鍘搁柣蹇曞仜婢т粙鍩ユ径鎰嚉闁挎繂顦伴悡鏇熺節闂堟稒顥滄い蹇嬪€濋弻鐔虹矙閸喗娈婚梺璇″枟椤ㄥ懘鍩㈤幘璇插瀭妞ゆ棁濮ら鍕⒒娴ｈ鍋犻柛搴㈢矒瀹曘劑顢橀悙鎰礀閳规垿鏁嶉崟顐℃澀闂佺锕ラ悧婊堝极椤曗偓楠炴帡寮崫鍕濠殿喗顭囬崢褍顕ｉ鈧弻娑㈠煛閸屾粍鍒涘Δ鐘靛仜椤戝寮崒鐐村仼閻忕偠妫勭粻娲⒒閸屾瑨鍏岀紒顕呭灦瀵濡搁埡浣虹枀闂佹寧绋戠€氼參顢曟禒瀣厱婵炲棗娴氬Σ铏圭磼閻樿崵鐣洪柡灞剧洴椤㈡洟鏁愰崶鑸垫婵犵數鍋涢幊搴∶洪妸褎顫曢柟鐑樻尰缂嶅洭鏌曟繛鍨姢闁荤喐褰冮埞鎴︽倷闂堟稑浠樼紓浣虹帛钃卞ǎ鍥э躬楠炴牗鎷呯憴鍕彆缂傚倸鍊烽梽宥夊垂閻戞ɑ娅忛梻鍌氬€搁崐鎼佸磹閻戣姤鍤勯柛鎾茬劍閸忔粓鏌涢锝嗙婵☆偅锚閵嗘帒顫濋敐鍛闁诲氦顫夊ú姗€宕归崸妤冨祦婵せ鍋撴鐐叉处閹峰懘鎮烽幍顔叫掗梻鍌氬€风欢姘焽瑜旈幃褔宕卞銏＄☉铻栭柛娑卞枛閳ь剙鐖煎鍫曞醇濞戞ê顬嬬紓浣哄У閸庢娊鈥︾捄銊﹀磯濞撴凹鍨伴崜杈╃磽娴ｆ彃浜鹃梺鍓插亖閸ㄨ崵澹曢崗绗轰簻闁哄啫鍊堕埀顒€顑夐悡顒勵敆閸曨剛鍘搁柣蹇曞仩椤曆勪繆閸ф鐓冪憸婊堝礈閵娧冪筏濠电姵鑹剧粈澶愭倵閿濆骸澧插┑顔藉▕閹綊宕惰閳绘洘绻涢幘鎰佺吋闁哄本娲熷畷鐓庘攽閸ヨ埖顥ｅ┑鐘愁問閸犳牠宕愰崸妤€钃熸繛鎴欏灩閻撴稑霉閿濆懎顥忓ù鐘层偢閺屟勫濞嗘垹袦闂佸搫鑻粔鐑铰ㄦ笟鈧弻娑㈠箻鐠虹儤鐎诲銈庡亜缁绘﹢骞栬ぐ鎺撳仭闁哄顑欓崵娆撴⒒娴ｅ憡鎯堟繛灞傚姂瀹曚即骞囬澶屽數闂佸湱鍎ら〃鍡涘煕閹寸姷纾奸悗锝庡亽閸庛儵鏌涙惔銏犲闁哄瞼鍠栧畷銊︾節閸愩劉鍋撻幇鐗堢厓闁靛闄勯ˉ鍫⑩偓瑙勬礃閿曘垽銆佸▎鎾冲簥濠㈣鍨板ú锕傛偂閺囥垺鐓冮柍杞扮閺嬨倖绻涢崼鐕傝€块柡灞剧洴瀵噣鍩€椤掑嫬绠栭柛灞惧嚬濞兼牗绻涘顔荤盎鐎瑰憡绻傞埞鎴︽偐閹绘帗娈梻鍌氼槸缁夌懓顫忓ú顏呭殥闁靛牆鎳忓В鎰版⒑閸濆嫭鍣洪柣鈺婂灦楠炲啯銈ｉ崘鈺佲偓濠氭煢濡警妲哄Δ鐘叉搐閳规垿鎮欓崣澶樻￥闂佺顑嗛幑鍥х暦閹剧粯顥堟繛鎴ｉ哺鐎靛矂姊洪棃娑氬婵☆偅顨婇幃妯侯吋婢跺鍘搁梺鍛婄矆濡炴帞鑺遍悾灞稿亾閸偅绶查柨鏇ㄤ簻閻ｅ嘲顭ㄩ崱鈺傂柣搴ゎ潐濞叉牕顕ｉ崜浣瑰床婵犻潧顑嗛ˉ鍫熺箾閹寸偟鎳曠紒杈╁仜閳规垿鎮欓懠顒佺檨闂佸搫鎳忕划鎾翠繆閻㈢绀嬫い鏍ㄦ皑椤旀帡鏌ｉ悩鐑橆仩婵炴彃鎳樻慨鈧柍钘夋椤旀棃姊虹紒妯哄闁诡垰鑻埢鎾愁煥閸曨剙寮挎繝鐢靛Т鐎氼喚鏁☉銏＄厵鐎瑰嫮澧楅崳鐣岀磼椤旂晫鎳囨鐐村姈閹棃濮€閵忊寬姗€姊婚崒姘偓椋庣矆娴ｉ潻鑰块梺顒€绉撮悡鏇㈡煕椤愮姴鍔氱痪鎯ь煼閺屾稑鈽夐崡鐐典粴闂佺顑嗛幐濠氬箯閸涙潙绀冮柕濞垮€栭惈蹇涙⒒娓氣偓閳ь剛鍋涢懟顖涙櫠閸撗呯＝鐎广儱鎳忛ˉ鐐电磼閸屾氨效鐎规洖銈稿鎾偄閾氬倻鏆楅梻鍌欑窔濞佳囁囬锕€鐤炬繝濠傜墛閸嬪倿鏌￠崶鈺佹瀭濞存粍绮撻弻鐔煎级閸噮鏆㈤梺璇″枦閸嬫劗妲愰幒妤佸亹缂佹稓顢婇埀顒€娼￠弻?"
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
        return f"闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱濠电姴鍊归崑銉╂煛鐏炶濮傜€殿噮鍣ｅ畷濂告偄閸涘鍞堕梻鍌欒兌椤牓顢栭崱娑樼闁告挆鍐ㄧ亰濡炪倖鎸鹃崑鎰ｉ崼鐔剁箚妞ゆ牗绻嶉崵娆愮箾閸涘洤娲﹂埛鎴炵箾閼奸鍤欐鐐搭殜閺岋綁鎮㈤崣澶嬬彋閻庢鍠栭…鐑藉箖閵忋倕宸濆┑鐘插鑲栨繝寰锋澘鈧呭緤娴犲鐤い鏍剱閺佷胶鈧箍鍎遍ˇ浼村煕閹寸姷纾奸悗锝庡亽閸庛儵鏌涙惔锛勭闁靛洤瀚伴獮瀣攽閹邦厸鏋呴柣搴㈩問閸犳盯顢氳閸┿儲寰勯幇顒夋綂闂佺粯锕㈠褎鎱ㄩ崼鏇熲拻濞达絽鎲￠崯鐐烘煕閺冩捇妾紒鍌氱Ч瀵粙鈥栭濠勭М鐎规洖銈告俊鐑芥晜鐟欏嫬顏圭紓鍌氬€风粈渚€顢栭崼銉ョ？濠电姵鐔紞鏍煥閺囩偛鈧綊鎮￠弴銏＄厸闁稿本绻冪涵鍫曟嚃閺嶎厽鈷戦柣鐔稿閻ｎ參鏌涢妸銉хШ闁糕斂鍎插鍕箛椤掑缍傞梻浣虹帛钃辨い鏃€鐗犲畷銉╁川椤斿墽鐦堥梺姹囧灲濞佳勭濠婂嫪绻嗘い鎰剁秵濞堟﹢鏌熼獮鍨伈妤犵偞甯￠獮妯伙紣濠靛洨銈梻鍌欒兌缁垶宕濋敃鍌氱婵炴垶鑹炬慨顒勬煃瑜滈崜娆撳煘閹达附鍊烽柤纰卞墮椤ｆ椽姊虹拠鑼缂佽鐗撻獮鍐潨閳ь剟骞冮姀銈呯闁兼祴鏅涢獮鍫熺節瀵伴攱婢橀埀顒佹尵缁牊绗熼埀顒勫春閵忋倕鍗抽柣姗嗗亜娴滅偓绻涢崼婵堜虎闁哄绋掗妵鍕敇閻樻彃骞嬮悗娈垮櫘閸嬪﹤鐣峰鈧、娆撴嚃閳轰礁袝濠碉紕鍋戦崐鏍暜閹烘鐤柣妤€鐗忛々鏌ユ煢濡警妲撮柡鈧禒瀣厽闁归偊鍓涢幗鐘绘倶韫囧骸宓嗛柡灞剧洴楠炲鈹戦崼鈶裤劑鎮楃憴鍕妞ゎ偄顦…鍥疀濞戞鈺呮煥閺冨倹娅曠憸鐗堢懇濮?`{file_path}` 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙鍋嶉梺鎼炲妼缂嶅﹪寮荤€ｎ喖鐐婇柕濞у懐妲囬梻鍌氬€搁悧濠勭矙閹烘绠归柟閭﹀枤绾惧ジ鏌熼柇锕€骞樻繛鎻掔摠閹便劍绻濋崘鈹夸虎閻庤娲忛崝宥囨崲濠靛洦鍎熼柕蹇嬪灪濞堥箖姊虹拠鏌ヮ€楅柛妯荤矒瀹曟垿骞樼紒妯煎幍闂傚倸鍊搁顓⑺囬敂鍓х＜闁绘ê纾晶顒€菐閸パ嶈含濠碘€崇埣瀹曟帒顫濋銏╂闂傚倸鍊风粈渚€鎮块崶顬盯宕熼鈧崶顒夋晬闁绘劘灏欓崢娲倵楠炲灝鍔氭い锔跨矙瀵偊宕堕埡鍌氭瀾閻庡厜鍋撻柍褜鍓熼幊鐐烘焼瀹ュ棗娈熼梺闈涳紡閸滀礁鏅梻鍌欒兌绾爼宕滃┑瀣闁哄洢鍨洪崐鍫曟煛鐏炶鍔滈柣鎾寸懄閵囧嫰寮崒娑欑彧闂佺懓鍟垮ú顓㈠蓟閻旂⒈鏁婇柣锝呯灱閻撯偓闂佸彞绱紞渚€寮婚敐澶婄闁瑰墎鐡旈埀顒侇殘缁辨帡鎮╅棃娑楁濠殿喖锕ら…宄扮暦閹烘垟鏋庨柟鎼幗琚﹂梻鍌欑濠€閬嶅煕閸儱纾婚柛鏇ㄥ幖瀵煡姊绘笟鈧褑澧濋梺鍝勬噺缁嬫挻绔熼弴鐘电＜婵☆垵鍋愰鏇㈡⒑鐟欏嫭鍎楅柛妯垮Г缁绘盯宕堕浣哄帗閻熸粍绮撳畷婊冣枎閹惧磭锛欓梺褰掓？閻掞箓宕戦埡鍛厽闁硅揪绲鹃ˉ澶愭煟閹邦剨韬柡灞界Ч瀹曨偊宕熼锝囦粚缂傚倷娴囨ご鎼佹偂閳ユ剚娼?"
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


_FUNCTION_GUIDANCE_SYMBOL_PATTERNS = (
    re.compile(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?function\b"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\("),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?.*=>"),
)


def _function_guidance_symbol_hint(value: object | None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for pattern in _FUNCTION_GUIDANCE_SYMBOL_PATTERNS:
        match = pattern.search(text)
        if match:
            return _compact_text(match.group(1), 48)
    return None


def _function_guidance_current_file_reply_parts(
    coach_context: dict[str, Any] | None,
    *,
    chinese: bool,
) -> tuple[str, str]:
    if not isinstance(coach_context, dict):
        return "", ""
    file_path = _compact_text(coach_context.get("file_path"), 120)
    selection_range = _compact_text(coach_context.get("selection_range"), 48)
    selection_text = coach_context.get("selection_text")
    content_excerpt = coach_context.get("content_excerpt")
    symbol = (
        _function_guidance_symbol_hint(selection_text)
        or _function_guidance_symbol_hint(content_excerpt)
        or ("当前选中的函数" if chinese else "the selected function")
    )
    if not file_path and not selection_text and not content_excerpt:
        return "", ""

    anchor_label = f"`{file_path}`" if file_path else ("当前文件" if chinese else "the current file")
    if selection_range and file_path:
        anchor_label = f"{anchor_label} ({selection_range})"

    if chinese:
        return (
            (
                f"我会先把这一轮锚定在当前文件 {anchor_label} 里的 `{symbol}`，"
                "先直接从这段代码读 contract，再用 hover、signature help 和 definition 补齐边界。"
            ),
            (
                f"下一步：回到 {anchor_label}，先说清 `{symbol}` 的参数 contract 和 "
                "return contract；如果旁边就有最近的 call site，再用它验证你刚才的判断。"
            ),
        )
    return (
        (
            f"I will anchor this to `{symbol}` in the current file {anchor_label}, read the "
            "contract from that code first, then use hover, signature help, and definition "
            "to tighten the boundary."
        ),
        (
            f"Next step: go back to {anchor_label}, name `{symbol}`'s parameter contract and "
            "return contract, then verify that reading against the nearest call site you can see."
        ),
    )


def _function_guidance_starter_reply_parts(
    coach_context: dict[str, Any] | None,
    *,
    chinese: bool,
) -> tuple[str, str]:
    if not isinstance(coach_context, dict):
        return "", ""
    starter = coach_context.get("function_guidance_starter")
    if not isinstance(starter, dict) or str(starter.get("status") or "").strip() != "ready":
        return "", ""
    call_site_path = _compact_text(starter.get("call_site_path"), 120) or "the prepared call site"
    definition_path = _compact_text(starter.get("definition_path"), 120) or "the prepared definition"
    symbol = (
        _compact_text(starter.get("definition_symbol"), 48)
        or _compact_text(starter.get("call_site_symbol"), 48)
        or "the prepared function"
    )
    if chinese:
        return (
            f"我会先把这一轮锚定在准备好的 live call site `{call_site_path}`，再用 hover、signature help 和 definition 读稳 `{symbol}` 的 contract。",
            f"下一步：打开 `{call_site_path}`，把光标放到 `{symbol}` 上，先看 hover 和 signature help，再跳到 `{definition_path}` 说清参数 contract 和返回 contract。",
        )
    return (
        f"I will keep this anchored to the prepared live call site in `{call_site_path}`, then use hover, signature help, and definition to read `{symbol}` with a stable contract.",
        f"Next step: open `{call_site_path}`, place the cursor on `{symbol}`, check hover and signature help, then jump to `{definition_path}` and name the parameter and return contract.",
    )


def _first_turn_lane_continuity_note(
    scenario: str,
    *,
    chinese: bool,
    coach_context: dict[str, Any] | None = None,
) -> str:
    if scenario == "remote_workspace":
        if chinese:
            return (
                "\u6211\u4f1a\u5148\u628a\u8fd9\u4e00\u8f6e\u7559\u5728 VS Code remote \u8fd9\u6761\u7ebf\u4e0a\uff1a"
                "\u5148\u8bb2\u6e05\u5de5\u4f5c\u533a\u8fb9\u754c\u548c\u6587\u4ef6\u5230\u5e95\u843d\u5728\u54ea\u53f0\u673a\u5668\u4e0a\uff0c"
                "\u518d\u505a\u4e00\u4e2a\u6700\u5c0f\u9a8c\u8bc1\u52a8\u4f5c\uff0c"
                "\u786e\u8ba4 Trainer \u4e0d\u4f1a\u8d8a\u754c\u5199\u9519\u5730\u65b9\u3002"
            )
        if chinese:
            return "我会继续把这一轮留在 VS Code remote 这条线上：先确认工作区边界和文件实际在哪台机器上，再决定 credential move。"
        return (
            "I will keep this in the VS Code remote lane: first teach the workspace boundary "
            "and where the files actually live, then do one minimal verification move before "
            "any write or credential decision."
        )
    if scenario == "debug_loop":
        if chinese:
            return "我会先把这一轮收束成一个可信的 debug loop：先复现一次，在第一个有意义的 state change 停下，再检查一个值。"
        return (
            "I will keep this as one trustworthy debug loop: reproduce once, pause at the first "
            "meaningful state change, and inspect one value before we widen anything."
        )
    if scenario == "function_guidance":
        starter_note, _ = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=chinese,
        )
        if starter_note:
            return starter_note
        current_file_note, _ = _function_guidance_current_file_reply_parts(
            coach_context,
            chinese=chinese,
        )
        if current_file_note:
            return current_file_note
        if chinese:
            return "我会先把函数理解锚定在一个 live call site 上，再用 hover、signature help 和 definition 把 contract 读稳。"
        return (
            "I will keep this anchored to one live call site, then use hover, signature help, "
            "and definition until the function contract stops moving."
        )
    if scenario == "project_adaptation":
        if chinese:
            return "我会先分清现有项目里哪些必须稳定、哪些必须改变，再落一个窄范围 adaptation。"
        return (
            "I will keep this in the existing-project lane: first separate what must stay stable "
            "from what must change, then land one narrow adaptation before we widen scope."
        )
    return ""

def _first_turn_lane_next_step(
    scenario: str,
    *,
    chinese: bool,
    coach_context: dict[str, Any] | None = None,
) -> str:
    if scenario == "remote_workspace":
        if chinese:
            return (
                "\u4e0b\u4e00\u6b65\uff1a\u5728\u4f60\u5f53\u524d\u7684 VS Code \u7a97\u53e3\u91cc\uff0c"
                "\u7ed9\u6211\u4e00\u4e2a\u80fd\u8bc1\u660e\u5de5\u4f5c\u533a\u843d\u70b9\u7684\u771f\u5b9e\u4fe1\u53f7\uff0c"
                "\u6bd4\u5982 Explorer \u91cc\u7684\u8def\u5f84\u3001\u7ec8\u7aef\u91cc\u7684 `pwd`\uff0c"
                "\u6216\u8005\u5de6\u4e0b\u89d2\u7684 remote host \u6807\u7b7e\u3002"
            )
        if chinese:
            return "下一步：告诉我当前工作区是 SSH、tunnels、dev container、WSL 还是 local，再给我一个你能看到的真实路径或主机标签。"
        return (
            "Next step: in the current VS Code window, capture one real boundary signal - for "
            "example an Explorer path, `pwd` in the terminal, or the remote host label - so we "
            "can verify which machine owns this workspace."
        )
    if scenario == "debug_loop":
        if chinese:
            return "下一步：告诉我你准备先停在哪里，以及你准备先检查哪一个值、分支或 stack frame。"
        return (
            "Next step: tell me where you will pause first and which single value, branch, "
            "or stack frame you expect to inspect there."
        )
    if scenario == "function_guidance":
        _, starter_next_step = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=chinese,
        )
        if starter_next_step:
            return starter_next_step
        _, current_file_next_step = _function_guidance_current_file_reply_parts(
            coach_context,
            chinese=chinese,
        )
        if current_file_next_step:
            return current_file_next_step
        if chinese:
            return "下一步：给我函数名和一个你现在就能打开的 call site，我们再从那里读参数、返回值和上下文。"
        return (
            "Next step: give me the function name and one call site you can open right now, "
            "and we will read the parameters, return value, and context from there."
        )
    if scenario == "project_adaptation":
        if chinese:
            return "下一步：告诉我哪个现有模块或行为必须稳定、哪一部分必须改变，以及你想先适配的第一道边界。"
        return (
            "Next step: tell me which existing module or behavior must stay stable, which part "
            "must change, and the first boundary you want to adapt."
        )
    return ""


def _fresh_lane_reanchor_reply(
    scenario: str,
    *,
    response_language: str | None = None,
    coach_context: dict[str, Any] | None = None,
) -> str:
    chinese = _prefers_chinese(response_language)
    guided_note = _first_turn_lane_continuity_note(
        scenario,
        chinese=chinese,
        coach_context=coach_context,
    )
    guided_close = _first_turn_lane_next_step(
        scenario,
        chinese=chinese,
        coach_context=coach_context,
    )
    return "\n\n".join(part for part in (guided_note, guided_close) if part.strip())


def _compact_first_turn_reply(
    reply: str,
    *,
    chinese: bool,
    scenario: str | None = None,
    learner_message: str = "",
    coach_context: dict[str, Any] | None = None,
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
    guided_note = _first_turn_lane_continuity_note(
        guided_lane,
        chinese=chinese,
        coach_context=coach_context,
    )
    guided_close = _first_turn_lane_next_step(
        guided_lane,
        chinese=chinese,
        coach_context=coach_context,
    )
    if guided_lane == "function_guidance" and isinstance(coach_context, dict):
        starter = coach_context.get("function_guidance_starter")
        if isinstance(starter, dict) and str(starter.get("status") or "").strip() == "ready":
            starter_tokens = [
                _compact_text(starter.get("call_site_path"), 120),
                _compact_text(starter.get("definition_path"), 120),
                _compact_text(starter.get("definition_symbol"), 48),
                _compact_text(starter.get("call_site_symbol"), 48),
            ]
            reply_mentions_starter = any(token and token in reply for token in starter_tokens)
            if reply_mentions_starter:
                if starter_tokens[0] and starter_tokens[1] and starter_tokens[0] in reply and starter_tokens[1] in reply:
                    return first
                guided_note = ""
    if guided_note and guided_close:
        second = guided_note
        close = guided_close
        return "\n\n".join([part for part in (first, second, close) if part.strip()])
    second = (
        trimmed[1]
        if len(trimmed) > 1
        else (
            "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎妯恍氱紓鍌氬€烽懗鑸垫叏闁垮绠鹃柍褜鍓熼弻鈥崇暆閳ь剟宕伴弽褏鏆︽繝濠傛－濡查箖鏌ｉ姀鈺佺仭闁烩晩鍨跺璇测槈濮橈絽浜鹃柨婵嗗暙婵″ジ鏌嶈閸撴氨鎹㈤崼婵愬殨濠电姵鑹鹃崡鎶芥煟閺冨洦顏犳い鏃€娲熷铏圭磼濡搫袝闂佸憡鎸诲畝鎼佸箖閻㈢绫嶉柛顐ゅ暱閹锋椽姊虹涵鍛汗闁稿绋掓穱濠冪附閸涘﹦鍘辨繝鐢靛Т閸嬪棝鎮℃總鍛婄厱闁宠鍎虫禍鐐繆閻愵亜鈧牜鏁幒妤€绐楁慨姗嗗墻閻掍粙鏌熼柇锕€骞樼紒鐘荤畺閺屾稑鈻庤箛锝喰ㄦ繝鈷€灞奸偗闁诡噯绻濇俊鑸靛緞鐎ｎ剙寮抽梻浣告惈濞层劑宕戝☉娆戭洸闁规鍠氱壕鐣屸偓骞垮劚濡稒鏅堕悽鍛婄厸鐎光偓鐎ｎ剛鐦堥悗瑙勬礀閻栧ジ宕洪敓鐘茬劦妞ゆ帒鍊归～鏇犫偓瑙勬礀濞诧箓宕伴幇鐗堢厽婵°倐鍋撻柣妤€妫涚划顓㈠箳閺冨倻锛滈梺閫炲苯澧寸€规洘甯￠幃娆戔偓鐢殿焾楠炲牓姊绘繝搴′簻婵炶绠撻幊婵嬫倷椤掑偆娲搁梺闈╁瘜閸樺墽澹曟總鍛婂€甸柨婵嗙凹缁ㄨ偐鈧懓鎲＄换鍕閹烘挻缍囬柕濠忕畱闂夊秹姊洪悷鏉挎Щ闁硅櫕锕㈤悰顕€骞樼拠鑼唺閻庡箍鍎遍幏瀣涘鍫熲拻闁稿本鑹鹃埀顒傚厴閹虫宕奸弴妞诲亾閿曞倸閱囬柕澶涚畱閸撹埖绻濋棃娑樷偓濠氣€﹂崼銏狀棜濠电姵纰嶉悡鐔兼煙闁箑鏋涢柛鏂款儔閺屾稓鈧綆浜滈埀顒€娼″濠氭晸閻樿尙鍊為梺瀹犳〃閻掞箓鎮楅鐔虹閻庢稒顭囬惌瀣磼椤旇姤宕岀€殿喖顭烽幃銏ゅ礂閼测晛濮洪梻浣瑰濞插秹宕戦幘缁樼厸閻庯綆鍋嗛妴鎺楁煃瑜滈崜姘辩矙閹烘梹宕查柛顐ｇ箥濞兼牠鏌ц箛姘兼綈閻庢碍宀搁弻娑樷枎韫囷絾楔濡炪倐鏅濇晶妤冩崲濞戞埃鍋撳☉娆樼劷闁活厹鍊曢湁婵犲﹤绨肩花缁樸亜閺囶亞鎮奸柟椋庡Т闇夐悗锝庡亽濞兼梹绻濋悽闈涗粶婵☆偅鐟╁畷纭呫亹閹烘挸鍓ㄩ梺鍓插亖閸庢煡鍩涢幋锔界厱婵炴垶锕弨璇差熆鐠哄搫顏柡灞剧〒閳ь剨缍嗘禍婊堝焵椤掑偆鐒剧€规挸瀚板铏规喆閸曨偒妫嗘繝鈷€鍕垫疁闁糕晜鐩獮瀣晜閽樺鍖栭梻浣规偠閸庤崵寰婂ú顏勭；闁瑰墽绮幆鐐淬亜閹扳晛鈧捇鏌囬鐐粹拻闁稿本鐟ч崝宥夋煙椤旇偐鍩ｇ€规洜鎳撶叅妞ゅ繐鎳庢禍妤呮⒑鐠恒劌鏋斿┑顔芥尦瀵即濡烽埡鍌滃帾闂婎偄娲ら敃銈嗘櫠閺屻儲鐓曢幖杈剧到閺嬫盯鏌＄仦鐣屝ч柡灞诲姂椤㈡稑顫濋銏╂闂傚倸鍊风粈渚€骞栭锔绘晞闁告稑鐡ㄩ悡鈧梺鎸庣箓椤︻垶鎷戦悢鍏肩厽闁哄啫娲㈤埀顑藉亾闂佺顑嗛幐鎼佸煡婢跺ň鏋庢俊顖滃帶婵櫣绱撻崒娆掑厡濠殿喕鍗冲畷鏇㈡偨缁嬭儻鎽曞┑鐐村灟閸ㄧ懓娲块梻浣告啞閸旀垿宕濇径鎰；闁圭偓绶為弮鍫濈闁冲搫锕ョ紞妤呮⒒娴ｇ瓔娼愮€规洘锕㈤、姘愁槾濠㈣娲熷畷妤呭礂閻撳骸浼庢繝娈垮枟椤ㄥ懎螞濡ゅ懎鍌ㄩ柟缁㈠枟閻撴洟鎮楅敐搴′簼鐎规洖鐬奸埀顒冾潐濞诧箓宕戞繝鍐х箚闁汇値鍨煎Σ楣冩⒑缂佹ɑ灏い鎴濐槸椤繘宕崟鎳峰洤鐐婄憸蹇旂婵傚憡鈷戠痪顓炴媼閸ゅ绱掔紒妯肩畵妞ゆ洩缍侀獮鎾诲箳閸℃ɑ鏉搁梺璇插嚱缂嶅棝宕戦崱娑樺偍妞ゅ繐鐗婇ˉ濠冦亜閹扳晛鐏柟鍏煎姈閵囧嫰骞嬪┑鍥ф畻闂佺硶鏂侀崑鎾愁渻閵堝棗绗傞柣鎺炲缁牓宕奸姀銏紲濡炪倖姊归娆撳吹濞嗘劑浜滄い鎰剁悼缁犵偤鏌熼搹顐ょ煉闁诡喕绮欏Λ鍐ㄢ槈濡偐鏉介梻鍌氬€搁崐椋庢濮樿泛鐒垫い鎺嶈兌閳藉鈧鎸稿Λ娆戞崲濞戞瑦濯撮柛鎰级閹兼劙鏌涢幋鐘残ｇ紒缁樼洴楠炲鎮欑€靛憡顓荤紓浣哄亾閸庢娊濡堕幖浣歌摕鐎广儱鐗滃銊╂⒑閸涘﹥灏伴柣鈺婂灦瀹曟椽鍩€椤掍降浜滈柟鐑樺煀閸旂喓绱掓径灞炬毈闁哄本绋撻埀顒婄岛閺呮繈宕濆鍥╃＜闁稿本姘ㄥ瓭濡炪値鍘归崝鎴濈暦婵傚憡鍋勯柛婵嗗缁犮儵姊婚崒娆掑厡妞ゃ垹锕敐鐐村緞閹邦剛顦梺鍝勭▉閸嬪懘宕楀鍏炬棃鏁愰崨顓熸闂佺粯鎸婚惄顖炲箖濡ゅ懏鏅查幖绮光偓鑼嚬婵＄偑鍊戦崕閬嶆偋閹捐钃熼柍銉ョ－閺嗗棝鎮楅敐搴″闁糕晛鐭傚铏光偓鍦У椤ュ銇勯敃鍌涙锭妞ゆ洩缍佸畷鎰版偆娴ｅ墣鈺佲攽閻樻剚鍟忛柛锝庡灣缁骞嬮敃鈧悡姗€鏌熸潏鎯х槣闁轰礁锕﹂惀顏堫敇閵忊剝鏆犻梺杞扮劍閸庢娊鍩為幋锔芥櫖闁告洦鍋傞崫妤€鈹戦埥鍡椾簻閻庢矮鍗抽獮鍐┿偅閸愨晛鈧崵绱掑☉姗嗗剱闁哄懏绻堝娲箰鎼淬垻锛曢梺绋款儐閹稿墽妲愰幒妤€鐒垫い鎺戝€甸崑鎾绘晲鎼粹€茬按婵炲瓨绮嶇划鎾诲蓟閻斿吋鍊锋い鎺嗗亾濠⒀屽灡娣囧﹪骞撻幒鏂跨厽闂佸搫鏈惄顖涗繆閹间礁惟闁挎棁顔婇崫妤呮⒒娴ｇ儤鍤€缂佺姴绉瑰畷纭呫亹閹烘垹鍙€婵犮垼娉涢…顒€顭囬埡鍌樹簻闁规澘澧庨崚鏉库攽椤栨瑥宓嗘慨濠勭帛閹峰懏绗熼婊冨Ъ闂備礁鎼悧婊堝礈濞嗘搫缍栨繝闈涱儏鎯熼梺鎸庢磵閸嬫挻銇勯弴顫喚闁哄本鐩、鏇㈡偐閹绘帒顫氶梻浣瑰▕閺€閬嶅垂閸︻厽顫曢柟鐑橆殢閺佸秵绻涢幋鐐垫噮妞わ负鍔戝娲传閸曞灚笑缂傚倸绉撮敃顏勵嚕鐠囨祴妲堟慨姗堢到娴滈箖鏌ㄥ┑鍡涱€楀ù婊勭箞閹绠涢敐鍛闂侀潧娲ょ€氫即銆侀弮鍫濈妞ゆ劧绲鹃鎺戔攽閻樻鏆柍褜鍓欑壕顓㈠春閿濆洠鍋撶憴鍕鐎规洦鍓濋悘鍐⒑閸涘﹤澹冮柛娑卞灱濡叉澘鈹戦悩鍨毄濠殿喚鍏樺顐﹀箹娴ｅ摜锛涘┑鐐村灍閹崇偤宕堕鈧痪褎淇婇锔芥锭闁圭⒈鍋婇垾锕傚Ω閳轰礁绐涘銈嗘尵閸嬬喐绂嶆导瀛樷拻濞达絿鎳撻婊呯磼鐠囨彃鈧儻妫熷銈嗙墬缁海浜搁悽纰樺亾楠炲灝鍔氭い锔垮嵆閹繝寮撮悢缈犵盎闂佽澹嬮弲娑㈠焵椤掍焦绀嬬€殿喗鎮傚顕€宕奸悢鍝勫箞婵犳鍠楅〃鍛涢弮鍫熺劷妞ゆ牗绋掗崣蹇撯攽閻樺弶鍣烘い蹇曞█閺屾盯寮介妸褍鈷岄悗娈垮枟閹告娊骞冨▎寰濆湱鈧綆鍋勯悵鑸电節绾板纾块柛瀣灴瀹曟劙骞嬮敃鈧粈澶屸偓鍏夊亾闁告洦鍓欐禍杈ㄧ節閻㈤潧孝婵炲眰鍊濋幃鎸庛偅閸愨晝鍘繝銏ｆ硾濡瑥鈻嶉崱娑欑厓闂佸灝顑呯粭鎺楁婢舵劖鐓ユ繝闈涙瀹告繈鏌熼挊澶娾偓鍧楀蓟濞戙垹围闁告侗鍘藉▓濠氭⒑閸濆嫭婀伴柣鈺婂灡娣囧﹪骞栨担瑙勬珖闂侀€炲苯澧撮挊鐔兼倵閿濆骸鏋熼柣鎾冲暟閹茬顭ㄩ崼婵堫槶濠殿喗顭堥崺鏍磿濡や降浜滈柡鍥殔娴滈箖鎮楃憴鍕┛缂佺粯绻堥悰顔芥償閵婏箑鐧勬繝銏犲帨閺傚倿宕曢柆宥嗙畳闂備焦瀵х换鍌毭洪妸鈺佄ュ┑鐘叉处閻撴盯鎮楅敐搴濋偗闁告瑥瀚伴弻鈥崇暆閳ь剟宕伴弽顓犲祦闁糕剝鍑瑰Σ楣冩⒑閹稿海鈽夌紒澶屾暬婵＄敻宕熼鎯ф暐闂備焦鎮堕崕顖炲礉婢舵劕绠柧蹇撴贡绾句粙鏌涚仦鍓ф噮闁告柨绉归幏鎴︽焼瀹ュ棗鈧爼鐓崶椋庡埌鐎殿噮鍣ｉ弻鐔碱敊缁涘鐤侀悗瑙勬礀缂嶅﹪銆侀弴銏狀潊闁靛繈鍨洪崵鍐⒒娴ｇ瓔鍤欓梺甯到椤洩顦瑰┑鈥冲缁瑧鎹勯妸锔筋啎闂備線娼ц噹闁逞屽墴瀹曟垿骞橀弬銉︻潔濠电偛鎳撴ご绋跨暆閹间胶宓侀煫鍥ㄦ礈绾惧吋淇婇婵嗕汗妞ゆ梹娲熼弻鈩冨緞婵犲嫬顣烘繝鈷€鍌滅煓鐎规洘纰嶇€佃偐鈧稒顭囬崢鐢告煟閻樺弶鍘傞柛娑卞灣濡插洭鏌ｆ惔銈庢綈婵炶绠撳畷褰掑醇閺囩偟鐣哄┑鐐叉閸斿弶鎯旈…鎴炴櫈闁荤姵浜介崝搴♀枖閸ф鈷掗柛灞剧懅缁愭梹绻涙担鍐叉礌閳ь剨绠撻、姗€鎮╅崗鍝ョ憹闂備胶鎳撻顓㈠磻閻愬搫鐭楅煫鍥ㄦ惄閻斿棝鎮规潪鎷岊劅闁稿骸娴风槐鎺旀嫚閸欏妫﹂梺鍝勬湰缁嬫垿鍩㈡惔銈囩杸闁挎繂鏌婇敂鐣岀瘈婵炲牆鐏濋弸娑氱磼婢跺﹦鍩ｉ柛鈹惧亾濡炪倖甯婄欢锟犲疮韫囨稒鐓曢柣妯诲墯濞堟粍顨ラ悙鏉戝闁圭厧缍婇、鏇㈡晲閸涱厺绱熼梻鍌欑窔閳ь剛鍋涢懟顖涙櫠閹绢喗鐓涚€光偓鐎ｎ剙鍩岄柧浼欑悼閻ヮ亪骞忓畝鍕懙濠电偛鐗婃竟鍡欐閹惧鐟归柍褜鍓氱粋宥夋嚋閻㈡娲搁柣鐘烘〃鐠€锕€顭囬弽顐ょ＝濞达綀鍋傞幋鐐插灁闁圭虎鍠楅悡鐔兼煟閺冨倸甯跺ù婊€鍗抽弻娑㈠Χ閸滀礁鍓崇紓浣介哺閹稿骞忛崨顖滈┏閻庯綆浜濋鍕⒒娴ｄ警鐒鹃柨鏇樺姂瀹曟洜鎷犻崣鍌涚洴閹垽宕妷褜鍟庨梻浣告惈椤︿即宕归悽绋跨畺闁瑰鍋熺粻楣冩煕韫囨艾浜归柟鍐叉喘閺岀喖顢欓崗鐓庝淮闂佽鍠楅悷鈺呫€侀弽顓炵煑闁靛／鍛櫒闂傚倸鍊风粈浣革耿闁秴纾块柕鍫濐槸閸ㄥ倿鏌ｉ姀鐘差棌闁轰礁鍊归妵鍕疀閹捐泛顤€闂佺粯鎸诲ú鏍煘閹达附鍋愰柟缁樺坊閸嬫挻绻濆顒佹К闂佹寧绻傞ˇ浼存偂濞戞埃鍋撻崗澶婁壕闁诲函缍嗛崜娑溾叺濠德板€楁慨鐑藉磻濞戞◤娲敇椤兘鍋撴担鍓叉建闁逞屽墴楠炲啴濮€閵堝棙鍎梺绋跨箰椤︿即鎮楁總鍛娾拻闁稿本鑹鹃埀顒勵棑缁牊绗熼埀顒勭嵁婢舵劖鏅搁柣妯垮蔼閹芥洟姊洪幐搴ｇ畵妞わ富鍨虫竟鏇犳喆閸曨厾鐦堥梻鍌氱墛娓氭宕曢幋鐘亾鐟欏嫭灏紒鑸靛哺瀵鈽夐姀鐘靛姶闂佸憡鍔︽禍鏍ㄦ叏閸ヮ剚鈷戠紒瀣儥閸庡繘鎮楀顐㈠祮鐎殿喛顕ч埥澶婎煥閸涱垱婢戞繝娈垮枟閿曗晠宕楀☉妯炑兾旈崨顔规嫼闂佸憡绋戦埊鏇㈩敂閸繄鐤呴梺鎸庣☉鐎氼厼鐣烽崣澶岀瘈闂傚牊渚楅崕蹇斻亜椤愩垺鍤囬柡灞诲妼閳规垿宕卞鍡橈骏闂備線娼уΛ娆撳礉閺囥垹鐓橀柟杈剧畱閻擄繝鏌涢埄鍐︿沪缂併劌銈稿娲嚒閵堝懏鐎梺绋挎捣閺佽鐣峰ú顏勵潊闁绘瑢鍋撻柛姘儏椤法鎹勯悮鏉戜紣闂佸吋婢橀悘婵嬪煘閹达附鍊烽柡澶嬪灩娴犳悂姊洪懡銈呮殌闁搞儜鍐ㄤ憾濠电偛顕慨鎾敄閸℃稑鐓曢柟瀵稿Х绾捐棄霉閿濆牆浜楅柟杈剧畱閻撴洟鏌熼柇锕€骞樼紒鐘荤畺閺屾稖绠涘顑挎睏闂佺懓鍟垮ú顓㈠蓟濞戙垹鐓橀柟顖嗗倸顥氭繝纰夌磿閸嬫垿宕愰弽顐ｆ殰濠电姴瀚浠嬫煃閵夛附鐏遍柡瀣⒐缁绘繃绻濋崒婊冾杸闂佺粯鎸婚悷褔鍩€椤掑喚娼愭繛鍙夌墪鐓ら柕鍫濇椤╃兘寮堕崼姘澒闁稿鎸鹃幉鎾礋椤掑倵鏁嶇紓鍌欒兌缁垳鎹㈤崼銉у祦闁告劑鍓悢鍏煎殐闁冲搫鍠涚槐鍙夌節绾版ɑ顫婇柛銊╀憾閹洨鎲撮崟顓ф祫闂侀潧绻掓刊顓炪€掓繝姘厪闁割偅绻傞弳娆撴煟韫囷絼绨煎ǎ鍥э躬椤㈡洟濮€閻樿櫕顔勯梻浣风串缁插潡宕楀鈧獮鍐閵忕姵鐎抽柡澶婄墑閸斿秴鈻嶅澶嬬厽闁绘柨鎽滈惌濠冩叏濮楀牏鐣甸柛鈺佹嚇瀹曞ジ寮撮悢鍙夊闂備胶顭堥張顒勬嚌妤ｅ啫鐒垫い鎺嶇劍閸婃劗鈧娲橀崝鏇㈡偩閿熺姴绠犲┑鐘插€荤粔铏光偓瑙勬礀閻栧ジ銆佸Δ浣虹瘈闁告洦鍘稿Λ銊︾節閻㈤潧袨闁搞劌銈稿畷娲冀椤撶偟顦梺鍝勬川婵挳藟濮樿埖鐓曠憸搴ㄣ€冮崱娑欏亗闁哄洢鍨婚崣鎾绘煕閵夛絽濡介悘蹇ｅ弮閺岀喖顢欓挊澶屼紝闂佸搫鏈粙鎴﹀煝鎼淬倗鐤€闁哄洨濯崯瀣⒒娴ｅ憡鎯堥柡鍫墮鐓ら柣鏃堫棑閺嗭箓鏌ｉ幘宕囧哺闁衡偓娴犲鐓欓梺顓ㄧ畱鐢劑鏌ㄩ弴妤€浜鹃梺瀹狀潐閸ㄥ潡銆佸▎鎾村€锋い鎺嗗亾婵炲牆鐭傞幃妤€鈻撻崹顔界亪婵犫拃鍐弰妤犵偞鍨挎慨鈧柣姗嗗亝椤秹姊洪棃娑氱濠殿喚鍏橀、妯好洪鍛嫼缂傚倷鐒﹂敋濠殿噯绠戦湁婵犲﹤瀚晶鐢碘偓瑙勬礃閸ㄥ潡鐛Ο鍏煎珰闁肩⒈鍓﹂崬娲⒒娴ｅ憡璐￠柛瀣尭椤洤鈻庨幘宕囶槷闂佸憡绋戦悺銊╁煕閹达附鈷掗柛顐ゅ枍缁堕亶鏌ｉ幒妤冪暫闁哄本绋掗幆鏃堝閻橆偅鐏嗛柣搴ゎ潐濞叉﹢宕濆▎鎾崇畺婵炲棙鎸婚崐缁樹繆椤栫偞鏁遍悗姘偢濮婄粯鎷呴崨濠呯濡炪値鍘奸悧鍡涙箒婵＄偛顑呭ù閿嬬▔瀹ュ鐓欓柛鎾楀懎绗￠梺缁樻尰閻熲晠寮诲☉銏犵疀妞ゆ挾濮村銊╂⒑閸涘﹦鎳冮悗姘嵆瀵鈽夐姀鐘靛幐闂佺鏈竟鏇熸叏閸ヮ剚鍊甸柛顭戝亝缁舵煡鎮楀鐓庢珝闁糕斁鍋撳銈嗗笒閿曪妇绮旈悽鍛婄厱闁规儳顕ú瀛樸亜閵忥紕鎳囩€殿喗鎸虫慨鈧柨娑樺楠炴姊虹涵鍛棈闁规椿浜炲濠冦偅閸愩劍杈堥梺鍐叉惈閸婅埖绂嶅鍕╀簻闁规崘娉涙禒褍顭胯閸ㄤ粙寮婚埄鍐懝闁搞儜鍕綆闁诲氦顫夊ú鏍Χ缁嬫鍤曢柟缁㈠枟閸嬪嫰鏌涘┑鍡楊仼缂佺姰鍎靛濠氬磼濞嗘垵濡介梺绋块閸熷潡婀佸┑顔筋焾濞夋稓澹曟繝姘厱闁哄洢鍔屾晶顖炴煕濞嗗繒绠抽柍褜鍓欑粻宥夊磿閸楃倣娑㈩敇閻愨晜鐏佹繛瀵稿Т椤戝棝鎮￠悢鍏肩厵闂侇叏绠戦悘鐘绘煟閵娿劍顏犵紒杈ㄥ浮閹晠宕樺ù瀣亞闂備礁鎼懟顖滅矓閻戦摪銊︾瑹閳ь剟寮诲☉銏犵闁告鍋涢‖瀣磽娴ｆ垝鍚柛瀣ㄥ€曢悾鐑藉础閻愨晜顫嶅┑鈽嗗灣閵嗗妲愰柆宥嗏拻濞达絿鐡斿鎰偓瑙勬礃閿曘垹鐣峰ú顏勫唨妞ゆ挶鍔庣粙蹇涙⒑閸濆嫭鍌ㄩ柛銊︽そ閹繝濡烽敂鍓х槇闂傚倸鐗婄粙鎺椝夐悙鐑樼厱閻庯絽鍚€缁ㄤ粙鏌熼崣澶嬪€愰柟顔ㄥ洤閱囨繝闈涚墢閹虫牠姊绘担鍛婃儓闁瑰啿绻橀幃锟犳晸閻樿尪鎽曞┑鐐村灟閸╁嫰寮崘顔界厪闁割偅绻冮崳娲煟濠靛啫澧茬紒缁樼〒閳ь剛鏁搁…鍫ｂ叴闂備礁鎼幊鎰箾閳ь剛鈧鍠栭…閿嬩繆閼搁潧绶炲┑鐘插閸橆剙鈹戦悩顔肩伇婵炲鐩幊鐔碱敍閻愯尙鍘遍柣蹇曞仩琚欓柡鈧懞銉ｄ簻闁哄啫鍊堕埀顒€顑夊畷婵嬫偄閾忓湱锛滃銈嗘礀閹冲酣鎮橀敂绛嬫闁绘劘灏欑粻鑽も偓瑙勬磸閸斿酣鍩€椤掍胶鈯曢柨姘归悪鈧崣鍐潖缂佹鐟归柛銉戝啩绱熺紓鍌欒兌婵敻宕归悽绋跨厺闁圭偓鏋奸弨浠嬫煕椤愮姴鐏柨娑欑箞濮婅櫣绮欓幐搴㈡嫳闂佽崵鍟欓崶浣告喘閺佸倹鎱ㄩ幇顏嗙泿闂備胶鎳撻悺銊ф崲閸愵啟澶愬閳垛晛浜鹃悷娆忓缁€鈧紓鍌氱Т閿曘倝鎮炬搴ｇ煓閻犲洨鍋撳Λ鍐春閳ь剚銇勯幒鎴濃偓缁樼▔瀹ュ鐓熸俊顖濆亹鐢盯鏌ｉ幘璺烘灈闁哄矉绻濆畷姗€濡搁妷銏犱壕闁汇垻顭堢粻顖炴煥閻斿搫校闁绘挻绋戦湁闁挎繂鎳忛幉鎼佸极閸儲鈷戦柛婵嗗閻掕法绱撳鍕獢闁绘侗鍣ｅ畷鍫曨敆婢跺娅栨繝娈垮枟椤牊銇旈幖渚囨晪婵°倕鎳忛埛鎺懨归敐鍛暈闁诡垰鐗撻弻銈吤虹拠鑼桓闂佽鍟崶褏顔掗梺褰掝暒閻掞妇绱炴惔鈾€鏀介柣鎰级閳绘洖霉濠婂嫮绠為柟顔惧仦缁绘繂顫濋鐘插箺闂備礁缍婇崑濠囧垂娴煎瓨瀚婂┑鍌氭啞閸婂灚鎱ㄥ鍡楀箺缂佽泛寮堕妵鍕敇閳ュ啿濮峰銈忛檮婵炲﹪寮婚悢鐓庡窛濠电姴鍊甸弸娆撴倵濞堝灝鏋涙い顓犲厴瀵偄顓兼径濠勵槹濡炪倕绻愰幊搴㈠垔娴煎瓨鈷掑ù锝呮啞閸熺偤鏌熺粙鎸庮棦鐎规洜鍠栭、鏇㈠椤厾鏁炬繝鐢靛Т閻ュ寮舵惔鎾充壕婵°倓鐒﹂崣蹇涙煟閹达絾顥夌痪鍓х帛缁绘盯骞嬮悙鈺傦紙濠电偛妯婃禍鍫曞极閸ャ劊浜滄い鎰靛亜閸樻挳鏌涚€ｎ偅灏伴柟宄版嚇閹虫牕鈹戦崶顭戞閻庤娲忛崝鎴︺€佸鈧幃鈺呭箵閹诡偅娲栭埞鎴︽晬閸曨偂鏉梺绋匡攻閻楁粓寮鈧獮鎺楀棘閸濆嫪澹曞┑顔筋焽閸樠勬櫠椤曗偓瀵偊宕奸妷锔惧幐闁诲繒鍋犻褔宕濆鍫熺厓闂佸灝顑呴悘锕傛煏閸パ冾伃妤犵偞甯″畷鍗烆渻閹屾缂傚倸鍊搁崐椋庣矆娓氣偓钘濋梺顒€绉撮弸浣糕攽閻樺疇澹樼紒鐘崇墵閺屻劑鎮㈤崫鍕戯綁鏌涚€ｎ亜顏柡灞剧缁犳稑顫濋鎸庣潖闂備礁鎲￠悷銉ノ涘Δ鍛厴闁硅揪闄勯崑鎰磽娴ｈ偂鎴︽煥椤撶偐鏀介柍钘夋娴滀粙鏌涘Ο鐓庡付鐎规挸瀚埞鎴︽倷閸欏鏋欐繛瀛樼矋缁诲牓骞冮敓鐘冲亜闁稿繗鍋愰崣鍡椻攽閻樼粯娑ф俊顐ｇ⊕閺呰泛鈽夊▎宥勭盎闂婎偄娲﹀ú鏍煝閸儲鐓涢悘鐐垫櫕鍟稿銇卞倻绐旈柡灞剧洴楠炴﹢寮堕幋婵囨嚈婵＄偑鍊戦崹娲偡閳轰緡鍤曞ù鐘差儛閺佸洭鏌ｉ幇顔芥毄鐎规洖鐖煎缁樻媴閸涘﹥鍎撳┑鐐茬湴閸ㄨ棄鐣疯ぐ鎺戞嵍妞ゆ挾鍠庨崢褰掓⒑闁偛鑻晶瀛樻叏婵犲懏顏犳繛鎴犳暬瀹曘劑顢欐穱鎵佸亾閹邦剦娓婚柕鍫濋娴滄繃绻涢懠顒€鏋涚€规洘妞介崺鈧い鎺嶉檷娴滄粓鏌熸潏鍓хɑ缁绢叀鍩栭妵鍕晜閼测晝鏆ら梺鍝勮嫰缁夊綊骞愭繝鍐ㄧ窞婵☆垱浜堕敃鍌涚叄濞村吋鐟х粔顔芥叏婵犲啯銇濈€规洖缍婇、姘跺川椤撶偛顥愰梻鍌欑窔閳ь剛鍋涢懟顖涙櫠椤斿浜滄い鎾跺仜濡茬粯銇勯銏㈢闁圭厧婀遍幉鎾礋椤愶絿鈧參姊绘担鍛婂暈婵炶绠撳畷婊冣枎閹惧磭顦悷婊呭鐢鍩涢幋锔界厱婵炴垶锕╅悡顒勬煟閹烘柨浜剧紒缁樼洴瀹曨亪宕橀鍕厒闂佸憡顨婃禍鍫曞蓟閻斿吋鐒介柨鏇楀亾濠⒀呯帛缁绘稓绮崫鍕潎闂佸搫鑻粔鐑铰ㄦ笟鈧弻娑㈠箻鐎靛憡鍣伴梺鎸庣箘閸嬬姷绮诲☉銏犵濞达綀顫夐妵婵囥亜閵忊剝顥堢€规洏鍔戦、姗€鎮ゆ担鍛婂€梻鍌氬€搁崐椋庢濮橆剦鐒界憸鏃堝箖瑜斿畷鍗炩槈濡⒈鍞甸梺璇插嚱缂嶅棙绂嶉崼鏇熷€块柤鎭掑劜閸欏繑淇婇姘变虎闁绘挻鍔欓弻宥夋煥鐎ｎ亞浼岄梺鍝勭灱閸犳牠骞婇弽顓炵厸濞达綁顥撻幑鏇㈡⒒娴ｅ憡鍟炴慨濠傜秺閺佸啴濮€閵堝懓鎽曞┑鐐村灟閸ㄧ懓螞濮椻偓閹綊骞侀幒鎴濐棊閻熸粌绻橀崺鈧い鎺嶇贰閸熷繘鏌涢悩鎰佹畷缂佺粯绋掔换婵嬪炊瑜忛悾娲⒑閸愬弶鎯堥柛鐔稿婢规洟宕楅梻瀵哥畾濡炪倖鐗滈崑鐐哄极闁秵鍊垫慨姗嗗厵閸嬨垺鎱ㄦ繝鍐┿仢鐎规洦鍋婂畷鐔煎垂椤愬秲鍔戝铏圭矙濞嗘儳鍓抽梺绋款儑閸嬬喓鍒掗埡鍛亜闁绘挸楠搁懓鍨攽閻愯尙鎽犳繝銏∶叅妞ゆ挶鍨归弸渚€鏌涢幇闈涙灈缁炬儳鍚嬬换娑㈠箣閻愯泛顥濆Δ鐘靛仜閻楀﹦鎹㈠┑鍡忔灁闁割煈鍠楅悘宥夋⒑閹稿孩纾甸柡鍛Т閻ｅ嘲顭ㄩ崼鐔告珖闂佺鏈銊╂晬閻斿吋鈷戦柣鐔煎亰閸ょ喎鈹戦鈧ˉ鎾寸珶閺囥垹绀傜紒妤勬〃缁ㄥ姊洪崫鍕殭闁稿﹦鏁婚獮蹇涙晸閻樺磭鍘遍柟鍏肩暘閸ㄦ椽鍩涢幇顓滀簻闁靛绲介崝锕傛煙椤旂晫鎳囩€殿喖鐖奸獮瀣偐閸偄娅欓梻鍌欑婢х晫鍒掗鐐村亱闁哄洢鍨虹粻鎺楁⒒娴ｇ懓顕滅紒璇插€块幃褍顭ㄩ崘鍓у姺闂佽澹嗘晶妤呮偂閻斿摜绡€闂傚牊绋掗幖鎰版煃缂佹ɑ绀冮柟渚垮妽缁绘繈宕熼鐐殿偧闂備胶鎳撻崲鏌ュ箠閹版澘绠熼柟缁㈠枛缁€瀣亜閹般劉鍋撻搹顐ｅ暉闂傚倸鍊搁崐鐑芥嚄閸洍鈧箓宕奸埗鈺佷壕闁割煈鍋勫ù顔锯偓瑙勬礃婵炲﹪寮幇鏉挎そ濞达絽鎲￠鍧楁⒒娴ｅ憡璐＄紒顕呭灠椤斿繒鎷犻崣鍌︾秮瀹曞ジ濡烽敂鎯у妇闂傚鍋勫ú銈堝闂佺顑嗛幑鍥ь嚕椤掑嫬唯闁靛鍊曢ˉ姘舵⒒娴ｇ顥忛柛瀣噹鐓ゆ慨妞诲亾闁诡噯绻濇俊鐑芥晜閸撗呮闂傚倸鍊搁悧濠勭矙閹烘鏅€广儱妫旂换鍡涙煙缂佹ê绗х紒澶嬫そ閺岋紕浠﹂悾灞澭囨煛鐏炶濡块柍褜鍓ㄧ紞鍡樼閻愭潙顕遍悘鐐缎掗弨鑺ャ亜閺冨倶鈧顔忛妷锔轰簻妞ゆ挾鍋涘Σ濠氭煟閿濆鏁辩紒杞扮矙瀹曘劍绻濋崒娆戠泿闂備浇宕甸崑鐐电矙閸儱鐒垫い鎺嶇婢ь垱绻涢崗鍏煎碍闁宠鍨块弫宥夊礋椤愨剝婢€闂備胶顭堥敃銉╁垂閸喚鏆﹂柡鍥ュ灩閽冪喖鏌曟径娑氱暠濞寸媭鍙冨娲箰鎼粹懇鎷婚梺绋款儐閹告悂鎮鹃悜钘夌煑濠㈣泛鐬奸鏇㈡⒑閻熸壆鎽犻柣鐔村劦閹﹢鍩￠崘顏嗭紲闂佺粯鐟﹂悷銉ッ洪敃鍌涘亗婵炲棙鎸婚崐鐢告煟閵忊槅鍟忛柣鎺撳劤闇夐柣妯虹－閻帡鏌″畝瀣？闁逞屽墾缂嶅棝宕滃▎蹇曟懃濠碉紕鍋戦崐銈嗙濠婂牆鐤悗娑櫭肩换鍡涙煕椤愶絾绀€缂佲偓閸愵喗鐓忓┑鐐戝啫鈧螞椤栫偞鈷掗柛灞剧懄缁佹壆鈧娲滈弫璇茬暦閹惰姤鏅滈柛鎾楀倻鐟濋梻浣侯攰閹活亞鈧潧鐭傚顐も偓锝庡枟閻撳繐顭跨捄鐑橆棡婵炲懎鎳愮槐鎺楀焵椤掑倵鍋撻敐搴′簴濞存粍绮撻弻鈥愁吋閸愩劌顬夐梺姹囧妽閸ㄥ潡寮婚敐澶娢ч柛灞剧煯婢规洖鈹戦悩娈挎殰缂佽鲸娲熷畷鎴﹀箣閿曗偓绾惧綊鏌″畵顔艰嫰閺呯姵绻濋悽闈浶ｉ柤鐟板⒔婢规洘绻濆顓犲幍闂佸憡鎸嗛崨顓狀偧闂備胶绮幐璇裁洪悢鐓庣畺婵°倕鎳忛弲鏌ュ箹鐎涙绠橀柡浣圭墵閺屸剝鎷呴崫銉ヮ暫闂佸疇顫夐崹鍧椼€佸▎鎴炲厹闁绘垹鏅崣宥嗙節閻㈤潧浠滈柟閿嬪灩瀵板﹪宕归銉秮楠炲洭寮剁捄顭戝敽闂備胶鎳撻崯璺ㄥ椤撱垹绐楅柡宥庡幖缁犳牗绻濇繝鍌滃闁绘挻鐩弻娑氫沪閹冩瘓婵炴潙鍚嬬划鎾愁潖婵犳艾纾兼慨姗嗗厴閸嬫捇鎮滈懞銉ユ畱闂佸壊鍋呭ú宥夊焵椤掑﹦鐣电€规洖銈告慨鈧柨婵嗘啗閳ユ枼鏀介柣鎰级閳绘洖霉濠婂嫮鐭屽瑙勬礈閹叉挳宕熼鐘垫闂傚倸鍊搁悧濠勭矙閹烘澶愭偐缂佹鍘搁梺绯曟閸橀箖鎮鹃悽鍛婄厸鐎光偓閳ь剟宕伴弽顓犲祦鐎广儱顦介弫濠勭棯閹峰矂鍝烘慨锝咁樀濮婄粯鎷呮笟顖滃姼闂佹寧娲╃粻鎾崇暦濡も偓椤粓鍩€椤掆偓椤曪絾绻濆顓熸珳婵犮垼娉涢敃锕傤敇濞差亝鈷戠紓浣姑悘銉︿繆椤愶絿娲寸€规洘绻堥幃婊堟嚍閵夈垺瀚奸梻浣告啞缁嬫垿鏁冮敃鍌氱疇闁告劏鏅欑换鍡樸亜閹板墎绉垫繛鍫熺矒閺屾盯鍩￠崘銊ゆ濡ょ姷鍋涢澶愬极閸岀偞瀵犲璺烘娴滈箖鏌ｉ幋锝呅撻柣鎾寸☉椤法鎹勬笟顖氬壈闂佽绻嗛弲娑㈡箒闂佺粯蓱椤旀牠鎮為悙顑句簻妞ゅ繐瀚弳锝呪攽闄囬崺鏍箚閺冨牆鐏崇€规洖娴傞崯鍥р攽閻樺灚鏆╅柛瀣☉铻ｅ┑鐘叉搐閻鏌涢幇闈涙灓鐎规挷绶氶弻娑㈠箛闂堟稒鐏嶉梺绋匡功閸忔﹢寮婚悢鍝勬瀳闁告鍋涚粻娲煛娴ｅ摜澧︽慨濠呮濞戠敻宕ㄩ褎顥嶉梻浣筋潐濡炴寧绂嶉悙宸殫濠电姴娲ら柨銈嗕繆閵堝嫮鍔嶆繛鍛墪閳规垿鎮╃拠褍浼愰梺纭呮珪閸旀绔熼弴鐔侯浄閻庯綆鍋嗛崢閬嶆煟韫囨洖浠滃褌绮欓獮濠囧川鐎涙鍘遍梺鍝勫€藉▔鏇熸櫏闂備礁缍婇弨閬嶅垂鐠轰警鐒介煫鍥ㄧ☉閻撴盯鏌涢幇鍏告倣缂佽鲸鐓″缁樼瑹閳ь剟鍩€椤掑倸浠滈柤娲诲灡閺呰埖瀵肩€涙鍘撻悷婊勭矒瀹曟粓濡歌缁€濠囨煕閳╁啰鈽夌紒鈧崒娑欏弿婵＄偠顕ф禍楣冩倵鐟欏嫭绀冮柛銊ユ健閻涱喖顫滈埀顒€顕ｉ鍕ㄩ柨鏂垮綖缁ㄦ挳姊婚崒娆戭槮濠㈢懓锕幃锟犲醇閵夈儳鐛ュ┑掳鍊曢幊蹇涘磹閸洘鐓曢柍鈺佸暟閳洟鏌嶉柨瀣伌闁哄本绋戦埥澶婎潨閸℃瑥褰嗘繝鐢靛仜閻楀﹤煤閺嶎厼鐓橀柟杈鹃檮閸婄兘鎮归崶鍥ф閹牆鈹戦悩娈挎毌闁逞屽墮绾绢參骞楅悩缁樼厵鐎瑰嫮澧楅崳浠嬫煕閺嶃劎澧电€殿喗鎸抽幃銈嗘媴閸︻厾鞋濠电姷鏁告慨鐢割敊閺嶎厼绐楁俊銈呮噷閳ь剙鍟村畷銊╊敇閸ャ劎鈽夐柍璇查叄楠炴ê鐣烽崶椋庨棷闂傚倸鍊搁崐鎼佹偋婵犲啰鐟规俊銈傚亾闁靛棙甯楃换婵嗩潩椤撶姴甯鹃梻浣稿閸嬪懐鎹㈤崘顔㈠顭ㄩ崼鐔哄幈閻熸粌绉归弫鍐敂閸繆鎽曞┑鐐村灦閸╁啴宕戦幘缁樻櫜閹肩补鈧尙鍑归梺璇茬箰缁绘帡寮繝姘摕鐎广儱鐗滃銊╂⒑閸涘﹥灏扮€光偓閹间降鈧礁鈻庨幘鍐插敤濡炪倖鎸鹃崑鐔兼偘閵夈儮鏀介幒鎶藉磹閺囥垹绠犵€光偓閸曨偆鍔﹀銈嗗坊閸嬫捇鏌涢悤浣哥仯闁瑰箍鍨归埞鎴犫偓锝庝簽閿涙粓姊洪棃娑氬婵☆偅绋撶划娆愮瑹閳ь剙顫忕紒妯诲闁荤喐婢樻慨銏㈢磽娴ｈ櫣甯涙い銊ワ躬閺佹劙鎮欓弶鎴犵獮闂佸綊鍋婇崜娑⑺囪閳规垿鎮╃拠褍浼愰梺缁橆殔閿曨亪骞冮敓鐘插嵆闁绘棁娅ｉ鏇㈡⒑閻熸壆鎽犵紒璇插€块幊婊嗐亹閹烘挾鍘搁柣搴祷閸斿矂鍩€椤掍胶绠炵€殿喖顭峰鎾閻樿尪鈧灝鈹戦埥鍡楃仩闁圭⒈鍋婇敐鐐哄箳閹存梹鏂€濡炪倖姊婚妴瀣绩缂佹ü绻嗛柣鎰閻瑩鏌ｅ☉鍗炴珝妤犵偛娲、姗€鎮㈠畡鏉课ら梻鍌欑窔濞佳兠瑰顒夌唵濞达絿鍎ら～鏇熴亜閹惧崬鐏柍閿嬪笒闇夐柨婵嗘噺閸熺偤鏌涢悢鍝勪沪闁逛究鍔嶇换婵嬪磼濠婂憛銊╂倵鐟欏嫭绀€缂傚秴锕ら悾椋庣矙鐠囩偓妫冮崺鈧い鎺戝暟缁犺姤绻濋悽闈涗哗闁规椿浜炲濠勬崉閵婏箑鍘归梺鍓插亝濞叉牠宕欓悩璇茬婵烇綆鍓欐俊浠嬫煟閹惧鎳囬柡宀€鍠栭、娑㈠幢濡や礁鐝旂紓浣戒含閸嬫盯鈥旈崘顔嘉ч煫鍥ㄧ⊕椤庡秴鈹戦悩顔肩仾闁挎洏鍨介崹楣冨籍閸繄顦ㄥ銈嗘煥濡插牐顦归柡灞剧洴閸╁嫰宕楅悪鈧禍顏勵嚕閸愬弬鏃€鎷呴搹鍦婵犵數鍋涢悧鍡涙倶濠靛鍑犻柕鍫濐槹閻撴洟鐓崶銊︻棖闁兼媽娉曢埀顒侇問閸ｎ噣宕戦崟顖ｆ晣濠靛倻顭堝钘壝归敐鍛儓鐎殿喗濞婂缁樻媴缁嬫妫岄梺绋款儏濡繂鐣烽鐐查敜婵°倐鍋撶紒鐙€鍨辩换娑橆啅椤旇崵鍑归梺鎶芥敱閸ㄥ潡寮诲☉妯锋婵鐗嗘慨娑㈡⒑鐎圭姵顥夋い锔炬暬瀵濡搁埡浣稿祮濠碘槅鍨甸妴鈧柛瀣崌瀵粙顢曢妶鍛Е闂備胶绮濠氬储瑜忕划鍫ュ礃閳瑰じ绨婚梺鍝勫暙閸婄懓鈻嶉弴銏＄厱婵せ鍋撳ù婊嗘硾椤繘鎼圭憴鍕瀭闂佸憡娲﹂崜娑㈠礄閿熺姵鈷戦柛娑橈工閻掑綊鏌涚€ｎ偅灏电紒杈ㄦ尰閹峰懘妫冨☉姗嗘綂闂備胶顭堥鍡涘礉濞嗘挾宓侀柛鎰靛櫘閺佸﹪鎮樿箛鏃傚闁诲骸顭峰娲偡闁箑娈舵繝娈垮枤閸忔﹢寮鍛斀閻庯綆鍋€閹疯櫣绱撴担鍓插剱閻庣瑳鍐胯€垮ù鐓庣摠閻撶姷鎲搁悧鍫濈闁伙絾妞介弻娑㈠煘閹傚濠碉紕鍋戦崐鏍暜閹烘纾归柟闂寸閸屻劑鏌熺紒銏犳灍闁绘挻鐟﹂妵鍕籍閳ь剟宕曢搹顐ゎ浄闂侇剙绉甸悡娑樏归敐鍥剁劸闁哄棴绲块埀顒冾潐濞叉鏁幒妤嬬稏婵犻潧顑呯粻鐔兼倵閿濆骸澧柟顖滃仱濮婂宕掑顑藉亾瀹勬噴褰掑炊椤掑﹦绋忔繝銏ｅ煐閸旀洜澹曢崸妤佺厱闊洦鎸搁幃鎴︽煕濞嗗繒绠婚柡灞炬礋瀹曠厧鈹戦幇顓夛妇绱掗悙顒€鍔ょ紓宥咃躬瀵濡舵径濠佺炊闂侀潧顧€闂勫嫬袙閸曨厾纾藉ù锝呭级椤庡棝鏌涚€ｎ偅宕屾慨濠傤煼瀹曟帒顫濋钘変壕闁归棿鐒﹂崑瀣攽閻樻彃鏆熼柣鐔活潐娣囧﹪濡堕崨顔兼缂佺偓鍎冲锟犲蓟閻旂厧绠ユい鏃傗拡閺嗩參姊虹紒妯诲鞍婵炶尙鍠栭獮鍐ㄎ旈崨顔芥珫闂佸憡顨堥崑娑㈩敂椤忓牊鐓熸繝闈涙搐閸濈儤鎱ㄦ繝鍐┿仢鐎规洦鍋婂畷鐔碱敇閻樻彃蝎缂傚倸鍊搁崐鍝ョ矓瀹曞洦顐芥慨妯垮煐閸嬫ɑ銇勯弴妤€浜鹃悗瑙勬礀閻栧ジ銆佸Δ浣虹懝闁搞儺鐓堝Λ鍐ㄢ攽閻樺灚鏆╅柛瀣仱瀹曞綊宕奸弴鐔告珖闂佸疇妗ㄧ欢锟犳倿閽樺）鏃堟晲閸涱厽娈查梺鎶芥敱鐢帡婀侀梺鎸庣箓閹冲繘骞夐幖浣圭叆婵炴垶顭囪倴缂備浇椴哥敮锟犮€佸璺哄窛妞ゆ挾濮抽崫妤呮⒑閹规劕鍚归柛瀣ㄥ€濆璇测槈閵忕姷鐤€闂傚倸鐗婄粙鎺楁倶閸垻纾藉ù锝呮惈鏍￠梺缁橆殕椤ㄥ棛绮氭潏銊х瘈闁搞儺鐏涜閺屾稑鈽夐崡鐐寸亪濠电偛鎳岄崐婵嗩潖濞差亜浼犻柛鏇ㄥ墮濞呫倝姊虹紒妯绘儓缂佺粯绻堥幃浼搭敋閳ь剙顕ｆ禒瀣垫晝闁靛繒濮锋禍浼存⒒娴ｄ警鐒剧紒缁樺姍钘濇い鏍ㄧ〒椤╂彃螖閿濆懎鏆為柣鎾跺Х閻ヮ亪寮堕崹顔垮煘婵犫拃灞芥珝闁哄本鐩俊鑸垫償閳ユ枼鎷繝娈垮枛閿曘倝鈥﹀畡鎵殾闁圭儤鍩堝鈺傘亜閹达絾顥夊ù婊堢畺閺岀喖姊荤€靛壊妲紒鐐劤缂嶅﹪寮诲☉妯锋斀闁告洦鍋勬慨澶愭⒑缁嬫鍎愰柟鍛婃倐閿濈偛鈹戠€ｎ偄浜楅柟鑲╄ˉ濡插懎顭囬崜褏纾介柛灞剧懅鐠愪即鏌涢悩鎰佹當閾荤偛銆掑锝呬壕婵犵绱曢弫濠氱嵁閸ヮ剙绾ч悹渚厛閸炴椽姊绘担渚敯闁规椿浜炲濠冦偅閸愩劎鐤?"
            if chinese
            else "I will first understand your goal, project, and blocker, remember that context for the next turn, then decide whether to guide the code, explain the principle, or shape the training thread first."
        )
    )
    if chinese:
        close = "濠电姷鏁告慨鐑藉极閸涘﹥鍙忛柣鎴ｆ閺嬩線鏌涘☉姗堟敾闁告瑥绻橀弻锝夊箣閿濆棭妫勯梺鍝勵儎缁舵岸寮婚悢鍏尖拻閻庨潧澹婂Σ顔剧磼閻愵剙鍔ゆい顓犲厴瀵鏁愰崨鍌滃枎閳诲酣骞嗚椤斿嫮绱撻崒娆掑厡濠殿喗鎸抽幃妯侯潩鐠轰綍锕傛煕閺囥劌鏋ら柣銈傚亾闂備礁婀遍崑鎾诲箚鐏炶娇娑㈡倷閻㈢數锛濇繛杈剧悼閺咁偊宕奸鍫熺厱濠电姴鍟扮粻鐐碘偓娈垮枛椤兘骞冮姀銈嗘優闁革富鍘鹃崢顖炴⒒娴ｇ顥忛柣鎾崇墦瀹曟娊顢氶埀顒€鐣峰┑鍥х窞闁归偊鍘搁幏娲⒑閸涘﹦鈽夐柨鏇畵楠炲﹪宕橀鍡欙紲缂傚倷鐒﹂敃顐︽嚀鐠恒劉鍋撳▓鍨灈妞ゎ厾鍏橀獮鍐閵堝棙鍎梺闈╁瘜閸欏繒妲愰弻銉︹拻濞撴埃鍋撴繛浣冲懏宕查柟鐑樻尰閸欏繘鏌ｉ姀鐘冲暈闁稿﹤鐖奸弻娑㈩敃閻樻彃濮曢梺鎶芥敱閸ㄥ湱妲愰幒鏂哄亾閿濆骸骞栭柛鏂跨仛閵囧嫰顢曢鍌滄殼闂佸搫鏈惄顖氼嚕椤掑倹宕夐柕濠冨姂閸婃繈寮婚悢鑲╁祦闁割煈鍠氭禒濂告⒑鐎圭姵顥夋い锕€鐏氶幈銊╁焵椤掑嫭鐓熸俊顖涙た閸熷繘鏌涘顒佸櫤缂佺粯绻堥幃浠嬫濞戞鎹曟繝纰樻閸嬪懘銆冮崼銉ョ闁靛繈鍊曠粻鎶芥煙妤ｅ喚鏉烘繛鏉戝缁绘繈妫冨☉妯峰亾閹间礁绠熼柨鐔哄Т绾惧綊鏌ｉ姀鐘冲暈闁绘挾鍠栭弻锝夊棘閹稿孩鍎撳銈忕到閵堟悂寮诲☉銏″亜闁告繂瀚幋椋庣磽娴ｄ粙鍝洪悽顖滃仱楠炲繘鎮╃拠鑼唽闂佺懓鎼Λ妤佺妤ｅ啯鐓曠憸搴ㄣ€冮崨鏉戝強闁靛鏅滈悡鐔兼煙闁箑澧柟顖氱墢缁辨帡鎮崨顖溞滈梺鍝勮閸旀垵顕ｉ鈧畷鍫曗€﹂幋鐑嗘婵犵數鍋涢悺銊у垝瀹€鈧槐鐐寸節閸屻倖缍庡┑鐐叉▕娴滄粌顔忓┑鍡忔斀闁绘ɑ褰冮顏堟煕閿涘崬鍠氬〒濠氭煏閸繄绠伴柣锔界矒閺屾盯濡搁妶鍛ギ闂佺硶鏂傞崹褰掝敇婵傜閱囨い鎰跺強閳哄懏鈷掑ù锝呮憸閺嬪啯銇勯銏╂█鐎规洖缍婂畷绋课旈埀顒勫垂閸屾鏃堟晲閸涱厽娈紓浣插亾闁告劦鍠楅悡鐘电棯閺夊灝鑸瑰褎鎸抽弻锝呪槈濞嗘劕纾冲┑顔硷功缁垶骞忛崨瀛樺仭闂侇叏绠戝▓婵囩節閻㈤潧浠︾憸鏉垮暟閹广垹螣閾忚娈鹃悷婊呭鐢鈧數濮撮…鍧楁嚋瀵版浜滈埢鎾诲Ω閿斿墽鐦堥梺姹囧灲濞佳勭墡缂備胶鍋撳妯肩矓閻熸壆鏆﹂柟杈剧畱缁€瀣亜閺嶃劎鈽夊ù鐘櫅閳规垿鎮欓弶鎴犱桓閻庡湱顭堥…宄扮暦閹达箑绠婚悹鍥皺椤ρ囨⒑閸涘﹣绶遍柛娆忛铻炴繝濠傚暊閺€浠嬫煟濡櫣浠涢柡鍡忔櫊閺屾稓鈧綆鍓欐禒杈┾偓瑙勬礀缂嶅﹤鐣锋總绋垮嵆闁靛闄勫▍鍡樹繆閻愵亜鈧洜鎹㈤幇鐗堝亱婵犲﹤鐗嗛弸渚€鏌涘畝鈧崑鐐烘偂閺囩喆浜滈柟鎵虫櫅閳ь剚娲熷鍛婃償閳墎鎳撻…銊╁礋閸偆鏉规繝娈垮枛閿曘儱顪冩禒瀣摕闁告稑鐡ㄩ崐鐑芥煠閼圭増纭炬い蹇ｅ幗缁绘繈鍩涢埀顒勫礋椤愵偅顥嬬紓鍌欐祰妞村摜鏁Δ鈧…鍥疀濞戞鈺呮煥閺囨浜鹃梻鍌氼槸缁夌懓顫忓ú顏呭仭闁哄瀵т簺闂備胶鎳撻崯璺ㄦ崲閹烘柨鍨濋悗锝庡枛缁犳娊鏌￠崒姘儓濞存粓绠栭弻銊モ攽閸℃瑥鍤紓浣靛妼閵堟悂寮婚悢鍏兼優妞ゆ劑鍊栭崳顔剧磽娴ｄ粙鍝洪柟鐟版搐閻ｇ兘骞掗幋鏃€鐎婚梺褰掑亰閸犳捇宕戝Ο璁崇箚闁绘劦浜滈埀顒佺墪閳绘棃鏁冮崒姘卞€為悷婊冪箻瀵宕奸妷锔规嫼闂侀潻瀵岄崣鈧俊鐐倐閺屾盯鎮╃€圭姴顥濋梺浼欑到閻忔氨绮悢鐓庣劦妞ゆ帒瀚崑鍌涖亜閹板墎鐣遍柣鎰躬閺屾洘绻涜閸嬫挻淇婇幓鎺斿ⅵ闁诡喗顨婇幃鐑芥偋閸繃娈樼紓鍌欐祰椤曆囨偋閹捐崵宓侀柛鎰╁壆閺冨牆鐒垫い鎺戝閻撯€愁熆鐠哄彿鍫ュ几瀹ュ棎浜滈柟鐐殔閸婂宕欓崷顓犵＝濞达絿顭堥埀顒€鎽滅划鏃堟倻閽樺）锕傛煙閻楀牊绶茬紒鐘冲▕閺岀喓绱掗姀鐘典画闁诲孩鐭划娆忣潖缂佹ɑ濯村〒姘煎灣閸旀悂姊洪崫鍕⒈闁告挻鐟╅敐鐐测攽鐎ｎ€晠鏌ㄩ弮鍥撻柣婵嗗槻閳规垿鎮欓弶鎴犱桓濠殿喗菧閸斿孩绔熼弴鐔洪檮闁告稑锕ら埀顒傛暬閺屻劌鈹戦崱娑扁偓妤€霉濠婂嫮绠橀柍褜鍓濋～澶娒洪弽顓熷剹闁稿瞼鍋涢拑鐔兼煟閺冨倵鎷￠柡浣革躬閺屾稖绠涢弴鐐蹭粯婵炲濮甸幐鍐差潖閾忕懓瀵查柡鍥╁枑濠㈡帡姊虹粙娆惧剱闁瑰憡鎮傞垾鏃堝礃椤斿槈褔鏌涢埄鍐炬畼闁荤喆鍔戦弻锝嗘償閵忕姴姣堥梺鍛婄懃閸熸潙鐣烽崫鍕ㄦ闁靛繒濮烽濠囨⒑閻熸壆鎽犻柣鐔村灲瀹曟垿骞樼拠鑼唺闂佽鎯岄崢浠嬪磽閻㈠憡鈷戦柟绋挎捣缁犳捇鏌熼崘鑼ｇ紒鏃傚枛瀵挳鎮㈤搹鍦闂備焦鐪归崹钘夘焽瑜庣粋鎺楀煛娓氬洨鍞甸梺鑽ゅ枑婢瑰棙鏅堕弴銏＄厽闁挎繂娲ら崢鎾煙椤旂偓娅曠紒顔界懅閹瑰嫰鈥﹂幋婵囨毄闂備浇宕甸崰鎰垝鎼淬垺娅犳俊銈呭暞閺嗘粍淇婇妶鍛櫣缁炬儳顭烽弻娑㈠即閵娿儳浠梺缁樻尵閸犳牠寮婚悢鐓庣闁归偊鍘捐ぐ褔姊洪崷顓燁仧缂佹煡绠栨俊鐢稿礋椤栨稒娅嗛柣鐘叉搐瀵爼鎮靛┑瀣拺閻犲洠鈧櫕鐏嶅銈冨妼閿曨亪骞冩导鎼晪闁逞屽墮閻ｇ柉銇愰幒婵囨櫓闂佺粯鎸哥€垫帒顭囧☉銏♀拻闁稿本鐟︾粊鐗堛亜閺囩喓澧电€规洑鍗冲浠嬵敇閻斿皝鍋撻懜鐢电瘈闂傚牊绋撴晶鏇犫偓娈垮枛瀵埖绌辨繝鍥ㄥ€锋い蹇撳閸嬫捇寮撮悩鍐插簥闂佸綊鍋婇崰鎺楀磻閹炬剚娼╂い鎰╁灩缁侇噣鎮楀▓鍨珮闁稿瀚伴垾锕傚Ω閳轰胶顦ㄩ梺鎸庣箓濡瑩寮堕幖浣光拺闁革富鍘奸崝瀣攽閻愯宸ラ柣锝囧厴楠炲洭寮剁捄銊ф澑闂備礁鎼ˇ鍐测枖閺囥垺鏅繛鎴欏灪閳锋垿鎮峰▎蹇擃仼闁告柣鍊曢…鑳槻婵炴挳鏀辩粩鐔煎即閻旀椽妾梺鍛婄☉閿曪箓宕㈤挊澶嗘斀闁宠棄妫楅悘鐘绘煙绾板崬浜扮€殿喗濞婇弻鍡楊吋閸℃瑥甯楃紓鍌氬€烽悞锕佹懌缂備讲鍋撻悗锝庡枟閻撴稓鈧厜鍋撻悗锝庡墰閿涚喐绻涚€电顎撶紒鐘虫崌楠炲啫鈻庨幙鍐╂櫌闂佺琚崐鏍叿闂傚倷娴囬褎顨ラ幖浣瑰€舵慨姗嗗墻閻斿棙淇婇姘辨癁闁稿鎸搁～婵嬵敇閻斿搫鍤掗梻浣风串缁插潡宕楀鈧獮鍐焺閸愨晛鍔呭┑鈽嗗灣缁垶寮堕幖浣光拻濞达綀娅ｉ妴濠冧繆閻欐瑥娲ら悿鐐節闂堟侗鍎忛柣鎺戠仛閵囧嫰骞掗幋婵愪紝濠碘槅鍋呴崹鍦閹烘挻缍囬柕濠忕畱绾炬娊鎮楃憴鍕閻㈩垱甯￠崺銏℃償閵娿儳顔婇梺鐟扮摠缁诲倿鎳欓幇顓犵瘈闁汇垽娼ф牎濡炪倖姊归悧鐘茬暦鐟欏嫮闄勭紒瀣硶閻撴垿姊洪崨濠傚闁告柨閰ｅ鎶芥晝閸屾稓鍘甸梺璇″灡濠㈡顣块梻浣告惈閹冲繗銇愰崘顔光偓锔炬崉閵婏箑纾梺缁樼閹稿磭娆㈤幘顔解拺缁绢厼鎳庤濠电偛寮堕悧鐘诲春閻愬搫绠ｉ柨鏃囨閳ь剛鍏橀弻鈩冨緞鐎ｎ亞浠兼繛瀵稿У閹倿寮婚妶鍥ㄥ晳闁靛牆鎳夐崑鎾斥攽鐎ｎ亣鎽曢梺璺ㄥ枔婵挳鎮為崹顐犱簻闁瑰搫绉烽崗灞俱亜閳哄啫鍘撮柟顔筋殜閺佹劖鎯旈垾鑼晼闂備礁鎲￠…鍥极鐠囧樊娼栫紓浣诡焽閻熷綊鏌涢妷鎴濆暕缁辩喓绱撻崒姘偓鎼佸磹閻熼偊娼╅柕濞炬櫆閸ゅ秹寮堕崼娑樺妞も晝鍏橀幃妤呮晲鎼粹€茬敖闂佸憡锕㈢粻鏍蓟閿濆棙鍎熼柍鈺佸暢绾偓濠电姵顔栭崰姘跺极婵犳哎鈧線寮崼鐔蜂汗闂佹眹鍨婚弫鎼佹晬濠婂牊鐓涘璺猴功婢ф垿鏌涢弬璺ㄐゅù婊冩啞鐎佃偐鈧稒顭囬崢鐢告倵閻熸澘顏褎顨婂畷铏鐎ｎ偆鍘甸梺鍛婄懃椤︽壆浜搁敂閿亾鐟欏嫭绀堥柛鐘崇墵閵嗕礁顫滈埀顒勫箖濞嗘挸鐭楀璺烘捣閸欐垶绻濋悽闈浶ユい锝庡枤濡叉劙寮撮姀鐘碉紱闂佺鎻粻鎴犲瑜版帗鐓涚€广儱娴锋禍瑙勭箾瀹割喕绨奸柡鍛箞閺屾稓浠﹂幑鎰棟闂佺顑呯粔鍨┍婵犲洤围闊洦娲栭崺宀勬⒑閸濄儱娅忛柛瀣閸掓帡宕奸妷銉ヨ€垮┑鐐村灦閻熝囧储閻㈠憡鈷戠紓浣姑悘锕傛煥閺囨娅呴柍缁樻崌瀵噣鍩€椤掍胶鈹嶅┑鐘叉祩閺佸啴鏌ㄥ☉鎺撴珕闁搞劌缍婇獮鎴﹀閻橆偅顫嶉梺闈涚箳婵挳鎳撻崹顔规斀闁宠棄妫楅悘鐘绘煙绾板崬浜濋柟渚垮姂婵偓闁靛牆妫岄幏娲煟閻樺弶绀岄柍褜鍓濆▍鏇㈡倶瀹ュ鈷戦柟鑲╁仜婵″ジ鏌ｈ箛鏃傜畾闁诲繐顑夊娲川婵犲嫧濮囬梺璇″灠閻倸顕ｉ锕€绀冩い鏃傛櫕閸橆亪妫呴銏℃悙閼瑰矂鏌涚€ｎ偅宕屾鐐叉处閹峰懘宕滈幇顔兼瀻闁宠鍨块幃鈺呭垂椤愶絾鐦庨梻浣侯焾椤戝棛绮欓幋锔绘晪闁挎繂顦粈鍫澝归敐鍥剁劸闁诲繐锕铏规喆閸曨偆顦ㄥ銈嗘肠閸涱垯绗夐梺鍝勭▉閻忔劘銇愰幒鎴狀槯闂佺绻楅崑鎰矙閸ヮ剚鐓曢柣鎴濇閻忥附鎱ㄦ繝鍐┿仢鐎规洘锕㈠畷锝嗗緞鐎ｎ亜澹嶉梻鍌欒兌椤牓鏁冮妶澶嗏偓锕€鐣￠幍顔芥闂侀潧楠忕槐鏇€呴悜鑺ュ€甸柨婵嗛娴滅偤鏌涘Ο鍏兼毈婵﹥妞藉畷妤呮嚃閳瑰灝浠﹂梻浣告惈閹虫劙宕戦悩鍙傛盯濮€閵堝棌鎷绘繛杈剧到閹诧繝宕悙鐑樼厵婵繂鑻崥褰掓煙楠炲灝鐏茬€规洜鍠栭、娑橆潩妲屾牕鏁搁梺鑽ゅ枑缁孩鏅跺Δ鍐╂殰婵°倕鎳庨悿楣冩煙闂傚鍔嶉柣鎾跺枑娣囧﹪顢涘┑鍥朵哗闂佹寧绋戠粔褰掑蓟濞戞﹩娼ㄩ柍褜鍓氱粋宥夊醇閺囩偠鎽曢梺鎸庣箓濡瑩宕曢悢鎼炰簻闁哄秲鍔庨惌宀勫冀閿熺姵鈷掑ù锝呮啞閸熺偤鏌熺粙娆剧吋闁诡喚鍏橀崺鈩冪瑹閸パ勵吙缂傚倷绀侀鍛姳閸楃倣锝夊醇閵夛妇鍘棅顐㈡储閸庡磭澹曢崸妤佺厱?idea闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鎯у⒔閹虫捇鈥旈崘顏佸亾閿濆簼绨绘い鎺嬪灪閵囧嫰骞囬姣挎捇鏌熸笟鍨妞ゎ偅绮撳畷鍗炍旈埀顒勫煕閹烘鈷戠紓浣姑粭褔鏌￠崪浣镐喊妤犵偛顦辩划娆忊枎閹勫€梻浣稿閸嬫帒顭块埀顒傜磽閸愨晜绀嬫慨濠傤煼瀹曟帒鈻庨幋顓熜滈梻浣告贡閳峰牓宕戞繝鍌滄殾妞ゆ牜鍎愰弫鍐煥閺冨洦顥夊ù婊嗛哺缁绘繈鎮介棃娴躲垺绻涚仦鍌氣偓妤佺珶閺嚶颁汗闁圭儤鎸鹃崢閬嶆偡濠婂啴鍙勯柕鍡楀暣瀹曞崬鈽夊▎蹇庣暗闂備線娼чˇ顐﹀疾濠婂牊鍋傛繛鎴欏灪閻撴洟鏌曟径鍫濈仾婵炲懎鎳庨湁闁绘ê纾惌鎺楁煛鐏炵晫啸妞ぱ傜窔閺屾盯骞橀弶鎴濇懙濡ょ姷鍋涢崯鏉戠暦閹烘埈娼╅柣鎾冲椤撳潡姊绘担鍛婂暈缂佸鍨块弫鍐Ψ閿曗偓閸ㄦ棃鎮楅棃娑欐喐缁炬儳鍚嬮妵鍕冀閵娧€濮囩紓浣插亾闁告劦鍠楅悡娑㈡煕鐏炵虎娈斿ù婊堢畺濮婂宕掑顑藉亾閻戣姤鍤勯柛顐ｆ磵閳ь剨绠撳畷濂稿Ψ閵夈儳褰夋俊鐐€栫敮鎺楀磹閹间礁鍑犻柛顐熸噰閸嬫捇鐛崹顔煎濡炪倧瀵岄崹鍫曞箖閸ф鏁嬮柍褜鍓熷濠氭晲婢跺﹦鐤€濡炪倖姊婚崢褎淇婂ú顏呪拺缂備焦蓱鐏忕敻鏌涢悩宕囧⒌鐎殿喖顭烽幃銏ゅ礂閻撳簶鍋撶紒妯圭箚妞ゆ牗绻冮鐘绘煕閺冣偓閹倸顫忛搹鍦＜婵☆垵顕х喊宥夋⒑闂堟稓澧涢柟顔煎€搁锝嗙節濮橆剛浼嬮悗瑙勬礀濞诧箑鈻撻弴銏＄厽閹兼惌鍨崇粔鐢告煕閹惧鎳囩€规洖鎼悾婵嬪礋椤掑倸寮板┑鐐存綑閸氬鎮疯缁棃顢氶埀顒勫蓟閿涘嫪娌悹鍥ㄧゴ閸嬫捇寮介鐐电杽闂侀潧艌閺呮稓绮诲☉娆嶄簻闁硅揪绲鹃ˉ澶娒瑰鍫㈢暫闁哄备鈧剚鍚嬮幖绮光偓宕囶啈闂備焦鎮堕崐鏍洪悢鐓庤摕婵炴垯鍨瑰敮濡炪倖姊婚崢褔锝為鍫熲拺闁规儼濮ら弫閬嶆煕閵娿儳浠㈡い顐㈢箰鐓ゆい蹇撶У閺呮繈姊洪棃娑氬闁瑰啿绉堕崚鎺楀醇閺囩啿鎷洪梺绋跨箰閸氬濡甸悢鍏肩厱闁靛ň鏅欓幉鍓р偓娈垮枟閻撯€崇暦婵傜鍗抽柕濠忛檮濞呮捇姊绘担鍛婂暈闁圭妫濆畷顏堝礃椤忓嫮鍝庢繝鐢靛Х閺佸憡鎱ㄦ导鏉戝瀭闁绘挸绨堕弸鏍ㄧ箾閹存瑥鐏柡鍛箞閺屻劑寮崹顔规寖闂佹椿鍘介幑鍥蓟閿濆绠ｉ柣鎴濇矗缁堕潧鈹戦悙鑼缂侇喗鐟╁濠氭晲婢跺﹦鐤€濡炪倖宸婚崑鎾剁磼閻欐瑥瀚ㄦ禍婊堟煏婢舵稓鍒伴柣蹇ｅ櫍閺屽秷顧侀柛鎾寸箞閿濈偞寰勬繛鎺戞惈椤劑宕煎┑鍫㈠炊闂備礁鎼粙渚€宕㈣ぐ鎺戠劦妞ゆ垼娉曢ˇ锕傛煃閽樺妯€濠殿喒鍋撻梺鏂ユ櫅閸燁垶鎮甸幎鑺モ拻濞达綀娅ｉ妴濠囨煕閹惧绠氶柟绛嬪亰濮婅櫣绱掑Ο鑲╃窗闂佸憡姊归崹鐢革綖韫囨梻绡€婵﹩鍓涢敍婊冣攽閻愬弶顥為悽顖涘浮瀹曘垽鏁嶉崟顓狅紲缂傚倷闄嶉崹褰掔嵁閺嶎厽鐓熼柡宥庡亜鐢爼鏌ｉ敐鍛Щ妞ゎ厹鍔戝畷姗€鏁愰崱妯绘緫闂備浇顕ч崙鐣岀礊閸℃稑纾婚柛鏇ㄥ墰椤╅攱銇勯幘鍗炵仾闁稿鍓濈换婵囩節閸屾凹浠惧銈冨劚濡瑦绌辨繝鍥舵晝闁靛牆鎳忛悗璇差渻閵堝簼绨婚柛鐔风摠娣囧﹪宕奸弴鐐茶€垮┑鈽嗗灣閵嗗妲愰埡鍛拻濞达絼璀﹂悞鐐亜閹存繃顥㈡鐐村灴瀹曞爼顢楅埀顒勬嫅閻斿吋鐓ユ繛鎴灻褎绻涘畝濠佺敖缂佽鲸甯為埀顒婄秵娴滅偞绂掗姀銈嗙厓鐎瑰嫰鍋婂Ο鈧梺璇″枟椤ㄥ﹤鐣疯ぐ鎺濇晝闁挎繂娲ら崵鎺楁⒑鐠囨彃顒㈢痪鏉跨Т椤灝顫滈埀顒勫箖妤ｅ啯鍊婚柦妯侯槺椤㈠懘姊虹紒妯哄缂佸鐖煎畷浼村冀椤撶偟鐤囬梺璺ㄥ枔婵潙娲块梻浣告啞娓氭宕圭€圭姵鎳岄梻鍌氬€搁崐鎼佸磹閹间礁纾圭€瑰嫭鍣磋ぐ鎺戠倞妞ゎ剦鍓氶惄顖氱暦閻旂⒈鏁嶆慨妯块哺閻掗箖姊绘担鐟板姢婵炲瓨宀稿畷鎴炴媴閸︻収娴勯梺鍓插亖閸庢煡鎮￠弴鐔虹闁瑰鍎戦崗顒勬煕閺冨倸鏋涢柡灞界Ч閹兘骞嶉褋鍨介弻宥囨喆閸曨偆浼岄梺璇″枓閺呯姴鐣烽敐鍡楃窞閻庯綆鍋勯埀顒傚厴濮婄粯鎷呯憴鍕╀户闂佸憡眉缁瑩濡撮崘顔煎窛缂侇喖鍘滈崑鎾绘晜閻愵剙纾梺闈涱煭缁犳垹澹曢娑氱闁圭偓娼欓崵顒勬煕閵娿倕宓嗙€规洘绮嶇€佃偐鈧稒菤閹锋椽姊绘笟鍥т簽闁稿鐩幊鐔碱敍濞戞瑦鐝峰銈嗙墱閸嬬偤鎮￠弴銏＄厸闁告劧绲芥禍鎯ь渻閵堝啫濡奸柨鏇ㄤ簻閻ｅ嘲煤椤忓嫮鍔﹀銈嗗笂闂勫秵绂嶅鍫熺厵闁绘垶锚閻忋儵鏌＄€ｃ劌鈧牜鎹㈠☉銏犵闁绘挸楠搁～宥囩磽娴ｈ櫣甯涢柣鈺婂灠閻ｇ兘鏁愰崱妤冪獮濠电偞鍨舵竟鏇㈠磻閹捐閿ゆ俊銈勮兌閸橆亪姊虹化鏇炲⒉妞ゃ劌鎳樺鎶芥倷閻㈢數锛滅紓鍌欑劍椤洨绮婚悙纰樺亾鐟欏嫭绀冮悽顖涘浮閳ワ箓濡搁埡浣侯槹濡炪倖甯掗ˇ顖炲疾椤撱垺鈷掗柛灞捐壘閳ь剛鍏橀幊妤呭礈娴ｇ鐏婂銈嗙墱閸嬫稓绮绘导瀛樼厱婵犻潧瀚崝銉モ攽椤旇棄鈻曢柡灞剧洴椤㈡洟鏁愰崱娆樻К缂傚倸鍊风拋鏌ュ疾濞戙垺绠掗梻浣虹帛閿氭俊顖氾躬瀹曟洟骞囬悧鍫㈠幗闂佽鍎抽悺銊х矆閸愵喗鐓忛柛銉戝喚浼冨Δ鐘靛仜濞差參宕洪埄鍐╁闁圭粯甯婃竟鏇㈡⒑閸濆嫭鍌ㄩ柛銊ョ秺瀹曟瑩鎮╃紒妯煎幍闁哄鐗撶粻鏍ь瀶椤曗偓閺岋綁骞樼捄鐑樼亪闂佸搫琚崝鎴濐嚕椤曗偓閸┾偓妞ゆ帒瀚壕鍧楁煣韫囷絽浜炴い鈺冨厴瀵爼宕煎☉妯侯瀴闂佸憡鐟ョ换鎰板煘閹达附鍋愰柟缁樺笚濞堟煡姊洪棃娑欏缂佽鐗撳濠氭偄閾忓綊鈹忛梺闈╁瘜閸橀箖鎯侀崼鐔虹瘈缁剧増菤閸嬫挸鐣烽崶褏鍘介柣搴ゎ潐濞插繘宕濋幋婵堟殾妞ゅ繐鐗嗙粈鍐┿亜韫囨挻锛旂紒杈╂暩缁辨捇宕掑▎鎰偘婵＄偞娼欓幗婊堝极椤曗偓閹瑩宕崟顓у數闂佽鍑界紞鍡涘窗閺嶎厼绠查柤鍝ュ仯娴滄粓鏌熼幑鎰【閸熺鈹戦埄鍐ㄧ祷婵炲樊鍙冨濠氭晲閸℃ê鍔呴梺闈涚墕鐎涒晝绱為崼婵冩斀闁绘劖娼欑徊鑽ょ磼缂佹◤顏堟偩閻ゎ垬浜归柟鐑樻尭閻у嫭绻濋姀锝嗙【闁哄牜鍓欓埢鎾诲箚瑜夐弨浠嬫煟濡鍤嬬€规悶鍎叉穱濠囶敃椤愩垹绠归柛妤€宕埞鎴︽偐瀹曞浂鏆￠梺鎶芥敱閸ㄥ潡寮婚悢鍏煎殐闁宠桨妞掔划鑸电節绾板纾块柡鍜佸亞濡叉劙骞掗弮鈧€氭岸鏌ょ喊鍗炲闁愁亪娼ц灃闁绘﹢娼ф禒婊堟煕閻曚礁浜伴柨婵堝仜椤劑宕煎┑鍫濆Е婵＄偑鍊栫敮鎺斺偓姘煎墰缁寮介妸褏顔曢梺绯曞墲钃遍悘蹇ｅ幘缁辨帡鎮╅崹顐ｆ瘓闂佸搫鐬奸崰鏍х暦椤愶箑绀嬫い鎺戭槹閿涗線姊虹拠鏌ヮ€楅柣蹇斿哺閹囨偐瀹割喗缍庣紓鍌欑劍钃卞┑顖涙尦閺屾稑鈹戦崟顐㈠Х缂備浇浜崑鐔烘閹惧鐟归柛銉戝嫮褰梻浣规偠閸斿秵鍒婃禒瀣€堕悗锝庡枟閳锋垿鏌涘☉姗堝伐濠殿噯绠撻弻娑㈡偐瀹曞洤鈷岄梺褰掓敱閸ㄥ潡骞冮姀銈呯闁兼祴鏅涚敮楣冩⒒娴ｇ顥忛柛瀣噽閹广垽宕橀銏狀樀閹瑩鎮滃Ο鐓庡箞婵犵數鍋涘Λ妤冩崲閹烘梻涓嶅┑鐘崇閻撴稓鈧厜鍋撻柍褜鍓熷畷浼村冀椤撶偠鎽曢梺鎼炲労閸撴岸寮插┑瀣厓鐟滄粓宕滈悢椋庢殾闁靛繈鍊曠粻缁樸亜閺冨倹娅曢柛姗€浜堕弻锝嗘償椤栨粎校闂佺顑呴幊搴ㄦ偩瀹勬壆鏆嗛柍褜鍓熼崺鈧い鎺嶇贰閸熷繘鏌涢悩鎰佹疁妤犵偞鍔欓獮搴ㄦ寠婢跺瞼鏆繝鐢靛仜濡瑩骞愰幖浣瑰亗婵炴垯鍨洪悡鏇㈡倶閻愭彃鈷旈柣顓炴缁辨帡濡搁敂钘夊攭濠殿喖锕ら…宄扮暦閹烘垟鏋庨柟鐑樺灥鐢垳绱撻崒娆戣窗闁革綆鍣ｅ畷褰掑醇閺囩偟浼嬮梺鎸庢礀閸婃悂鎮欐繝鍥ㄧ厓閺夌偞澹嗛ˇ锕傛煟韫囨搫宸ユい顏勫暣婵″爼宕卞▎蹇婃嫛闂備胶顭堥鍥磻閵堝懐鏆?"
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
    coach_context: dict[str, Any] | None = None,
) -> str:
    step = next_step_hint.strip()
    if scenario == "function_guidance":
        starter_note, starter_next_step = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=chinese,
        )
        starter = coach_context.get("function_guidance_starter") if isinstance(coach_context, dict) else None
        starter_tokens = [
            _compact_text(starter.get("call_site_path"), 120) if isinstance(starter, dict) else None,
            _compact_text(starter.get("definition_path"), 120) if isinstance(starter, dict) else None,
            _compact_text(starter.get("definition_symbol"), 48) if isinstance(starter, dict) else None,
            _compact_text(starter.get("call_site_symbol"), 48) if isinstance(starter, dict) else None,
        ]
        if any(token and token in reply for token in starter_tokens):
            return ""
        if starter_note or starter_next_step:
            step = starter_next_step.strip()
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
    coach_context: dict[str, Any] | None = None,
) -> str:
    guided_lane = _first_turn_guided_lane(scenario, "")
    if guided_lane not in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return ""
    if _reply_has_guided_lane_signal(reply, guided_lane, chinese):
        return ""
    return _first_turn_lane_continuity_note(
        guided_lane,
        chinese=chinese,
        coach_context=coach_context,
    )


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
            return f"闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙绐涢梺鍝ュУ閹稿墽鍒掔紒妯稿亝闁告劏鏅濋崢浠嬫⒑闁稑宓嗘繛浣冲嫭娅犳い鏍仦閻撶喐绻濋棃娑欏缂佲偓鐎ｎ偅鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噧闁宠閰ｉ獮鍡氼槻濠㈣锚閳规垿鎮欓懠顒佹喖缂備緡鍠氭慨鐢电矉瀹ュ鏁傞柛鏇㈡涧濞堛劑鏌ｉ悩鍙夊缂佷焦娼欏嵄闁割偁鍎查悡蹇涚叓閸ャ劍绀€閸熸悂姊洪崨濠冣拹闁圭鍟块～蹇撁洪鍕獩婵犵數濮撮崐姝岊杺婵犵數鍋涢悺銊у垝瀹ュ鍋嬮柡鍥╁仜缁侇偊姊绘担绋款棌闁稿绶氬畷褰掓嚒閵堝拋妫滈梺鑺ッˉ銏ｃ亹閹烘挻娅滈梺绯曞墲椤ㄥ牏绮婇柨瀣閻庢稒顭囬惌鎺旂磼閻樺磭澧い顐㈢箻閹煎綊宕烽鐘靛幆闂佽崵濮垫禍浠嬪礉鎼淬垹顕遍柛銉墯閳锋垹绱掔€ｎ偒鍎ラ柛搴㈠灴閺屾稓鈧絻鍔岄埀顒佺箞閻涱噣宕橀鑺ユ闂佺粯蓱瑜板啫鐣甸崱娑欌拺缂備焦蓱閳锋帞绱掔紒妯肩畼闁奸缚椴哥换婵嗩潩椤撴稒瀚奸梺鑽ゅ枑閻熴儳鈧凹鍘惧▎銏ゅ箵閹烘繄鍞甸悷婊冪Ч閺屽﹪鏁愭径灞界ウ闂佸憡鍔﹂崰妤呭吹閸愵喗鐓冮柛婵嗗閺嗙喖鏌ㄥ☉娆戠煉婵﹨娅ｇ槐鎺戭潨閸℃瑥濮兼繝鐢靛仜閹冲繐煤閺嶎厽鍋╃€瑰嫭澹嗛弳鍡涙煕閺囥劌澧伴柛妯绘倐閹宕楁径濠佸闂佽鍑界紞鍡涘礈濞戞壕鍙烘繝寰锋澘鈧鎱ㄩ悜钘夌；闁绘劕鐏氶弳婊堟煥閻斿搫啸鐎规挷绶氶幃妤呮晲鎼存繄鎸夐梺鍝勵儏闁帮綁鎮￠锕€鐐婄憸鏃堫敁濡ゅ懏鐓曢柕濠忓缁犵偞鎱ㄦ繝鍌ょ吋鐎规洘甯掗埢搴ㄥ箣椤撶啘婊堟⒒娴ｅ憡璐￠柍宄扮墦瀹曟垶绻濋崶褏鐣炬繝銏ｆ硾椤戝洭姊介崟顓犵＜閻庯綆鍘界涵鍫曟煟濞戞牕鍔︽慨濠呮閹叉挳宕熼銈庢О婵＄偑鍊栧▔锕傚川椤栨粌绠垫繝寰锋澘鈧劙宕戦幘缁樼厓閻熸瑥瀚悘鎾煙椤旇娅婇柣鎿冨亰椤㈡﹢鍩勯崘顭戞綍闂傚倸鍊烽懗鍓佸垝椤栨娑欐媴缁洘鐎洪梺鎸庣箓濞层倝藟濮樿埖鐓曢煫鍥ㄧ⊕閿涚喓绱掔拠鍙夘棡闁靛洤瀚板浠嬪Ω瑜忛悡鈧梺姹囧焺閸ㄧ増鏅舵惔锝嗩潟闁圭偓鍓氶崥瀣归敐澶嬫珳濠㈣娲熷濠氬磼濮橆兘鍋撻幖浣哥９闁归棿绀佺壕鍦偓鐟板閸ｇ銇愰幒鎴犲€炲銈嗗笒椤︿即寮查鍫熷仭婵犲﹤鍟撮崣鍕煏閸℃鏆ｅ┑锛勫厴閸┾剝鎷呮笟顖氭櫍婵犵數鍋犻幓顏嗗緤閸ф绠犻柟鎹愵嚙閻掑灚銇勯幒鎴濇殭闁绘挻鍔欓弻鐔哥瑹閸喖顬堥柧浼欑秮閺屾盯鈥﹂幋婵囩亾闂佸憡锕╅崑濠傤潖閾忓湱鐭欐繛鍡樺劤閸撴澘顪冮妶鍡楃仴妞わ箓娼ч锝嗙節濮橆厽娅滈梺鍛婄☉閸婂宕伴弽褏鏆︾憸鐗堝俯閺佸﹪鏌ｉ幇闈涘⒒闁搞倕瀚板濠氬磼濞嗘埈妲梺鍦拡閸嬪嫯鐏嬮柣搴ㄦ涧閹芥粍绋夊澶嬬厵闁硅鍔﹂崵娆撴煢閸愵亜鏋涢柡灞炬礋瀹曠厧鈹戦崶褏鐛╅梻浣规た閸樹粙鎮烽埡鍛畺鐟滅増甯掔粻鎺楁煙閻戞ê鐏ユい顒€妫涚槐鎾寸瑹閸パ勭亾闂佽桨绀侀幗婊兾ｉ幇鏉跨閻犲洩灏欓敍婊冣攽椤旂即鎴︽儊閻戣棄顫呴柨娑樺椤旀洟鎮楅悷鏉款棌闁哥姵鐗曢锝夘敊闁款垰浜炬繛鍫濈仢閺嬶附銇勯弴鍡楁搐閻撯€愁熆閼搁潧濮囨い顐㈡嚇閺岋絽螣濞茶鏅遍梺鍝ュ枎椤戝棛鎹㈠┑鍡╁殫闂佸灝顑嗙欢鏌ユ煃瑜滈崜姘跺礉濞嗗繒鏆﹂柟杈剧畱缁犺崵绱撴担璇＄劷闁告鏁婚幃妤呮偡閺夋浼冮梺绋款儏閿曨亜鐣烽弴锛勭杸婵炴垶顭囬、鍛存⒒娓氬洤澧紒澶屾暬閹繝鎮㈤崗鑲╁幍闁哄鐗嗘晶浠嬪礆閹殿喗鍋栨慨妯垮煐閳锋垿鏌熼幆鏉啃撻柡渚€浜堕幃浠嬵敍濞戞ɑ璇炲┑鐘亾濞撴埃鍋撴慨濠冩そ楠炴劖鎯旈敐鍥╂殼闂佽瀛╅崙褰掑垂閸洏鈧礁螖閸涱喖浜滈梺绋跨箺閸嬫劙宕㈡禒瀣拺闁革富鍘奸崝瀣煕閵娧勬毈闁糕晜鐩顕€宕掑鍜冪床闂佸搫顦悧鍕礉瀹€鈧划顓☆槾缂佽鲸甯楀蹇涘Ω閵壯呮噯闂佸彞绱紞渚€寮诲☉妯锋斀闁糕剝顨忔导灞解攽閻愭彃鎮戠€光偓缁嬫娼栫紓浣股戞刊瀵哥磼濞戞﹩鍎忔繛鍫熷姍濮婃椽宕妷銉︾彙闂佺顑呴敃銈夋偩閻戣棄绠氶梺顓ㄩ檮浜涢梻鍌欑閸氬顭垮鈧幃妯衡攽鐎ｎ亞鍘撮梺纭呮彧闂勫嫰寮查鍕厱闁哄洢鍔屾禍妤佺箾瀹€濠佺盎闁宠鍨块幃娆撳箵閹烘棃鐛撶紓鍌欐祰椤曆囧磹閸ф鏄ラ柕蹇曞閸氬顭跨捄渚剱婵炲懏绮嶇换婵嬪閿濆棛銆愰梺鎸庢穿缁犳捇銆佸▎鎰窞闁归偊鍘搁幏娲⒑閸涘﹦鈽夐柨鏇樺劜瀵板嫰宕熼娑氬幈闂侀潧臎閸愮偓姣夐梻浣侯焾鐎垫帡宕戞繝鍥ц摕闁挎繂顦伴崑鍕煕濠靛嫬鍔ら柣鎾亾缂傚倸鍊烽懗鍓佸垝椤栫偞鏅濋柕蹇曞閸?`{check}` 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱闁靛牆鎳庨顓㈡煛鐏炲墽娲存い銏℃礋閺佹劙宕卞▎妯恍氱紓鍌氬€烽懗鑸垫叏闁垮绠鹃柍褜鍓熼弻鈥崇暆閳ь剟宕伴弽褏鏆︽繝濠傛－濡查箖鏌ｉ姀鈺佺仭闁烩晩鍨跺璇测槈濞嗘垹鐦堥梺鍛婁緱閸橀箖宕㈤锔解拺闂侇偅绋撻埞鎺楁煕閺傝法鐒烽柣蹇斿浮濮婃椽宕烽褏鍔稿┑鐐差嚟閸忔ɑ淇婇幘顔肩疀妞ゆ柨澧介敍婵囩箾鏉堝墽鍒伴柟纰卞亝閻楀酣姊绘担铏瑰笡闁圭⒈鍋嗛幑銏犫攽閸♀晛娈ㄩ柣鐘叉处缁佹潙危閸儲鐓忛煫鍥ㄦ礀椤秹鏌曟繝蹇氱濞存粍绮撻弻锟犲礃閵娿儮鍋撻崫銉︽殰闁煎摜鍋ｆ禍婊勩亜閹邦喖鏋戞繛鍛攻閹便劍绻濋崨顕呬哗缂備浇椴哥敮鎺曠亽闂佹儳绻愬﹢閬嶅箠閸℃稒鈷掑ù锝囩摂閸ゆ瑧绱掔紒妯虹仴闁伙絾绻堝畷銊︾節娴ｈ櫣鐣鹃梻浣圭湽閸ㄥ鈥﹂崼銏㈢焼閻庯綆鍋佹禍婊堟煛瀹ュ啫濡介柣銊﹀灦閵囧嫰寮崠陇鍚梺璇″枟椤ㄥ﹪鎮伴鈧畷褰掝敊閻撳寒娼涢梻鍌欒兌缁垶銆冮崨顓囨稑鈹戦崱娆愭闂侀潧绻堥崐鏍疾閹间焦鐓熸俊顖滅帛閻忛亶鏌熼悿顖涱仩缂佽鲸鎹囧畷鎺戔枎閹存繂顬夐梺钘夊暣娴滃爼寮婚悢纰辨晬婵﹩鍓︽导鍐⒑閸濆嫭婀伴柣鈺婂灡娣囧﹪骞栨担鑲濄劎鎲稿┑鍫燁潟闁绘劖绁撮弨浠嬫煃閵夈儱鏆辩紒鐙欏洦鐓曢柡鍐ｅ亾闁荤啿鏅犻幃浼搭敋閳ь剟鐛幒妤€绠犻柧蹇ｅ亝椤ュ牓鏌涢埞鎯т壕婵＄偑鍊栧濠氬磻閹剧粯鎳氶柣鎰摠閸欏繑淇婇悙棰濆殭濞存粓绠栧铏规嫚閳ヨ櫕鐏堢紓鍌氱Т閿曨亪鎮伴鐣岀懝闁逞屽墴閻涱噣骞掑Δ鈧粻锝嗙節閸偄濮夐柍褜鍓氶幐鍐差潖缂佹ɑ濯村〒姘煎灡閺侇垶鏌ｈ箛鎾寸濞存粠浜滈悾鐑藉箣閿曗偓缁犳稒銇勯弮鍌滄憘婵炶偐鍠栧铏规喆閸曨偄濮㈤梺瀹︽澘濡介柛鎺戯躬楠炴﹢顢欓悾灞藉箞闂備礁婀遍崑鎾愁焽濞嗘垵绶ゅ┑鐘崇閻撴洟鏌熼幆褏鎽犵紒璺哄级閵囧嫰顢旈崟顐ｆ婵犵鍓濋崕鑲╃不濞戙垹绠奸柛鎰ㄦ櫅閺嬬娀姊婚崒娆愮グ婵℃ぜ鍔庣划鍫熺瑹閳ь剟鍨鹃敃鍌涚叆閻庯絺鏅濈粻姘舵煟鎼淬垻鈯曟い顓炴喘閹柉銇愰幒鎾跺帗閻熸粍绮撳畷婊冣枎閹垮啯鏅梺鎸庣箓椤︿粙寮€ｎ喗鐓冪憸婊堝礈濞嗘挻鍋╅柣鎴ｅГ閸嬪倿骞栫€涙〞鎴﹀棘閳ь剟姊绘担铏广€婇柛鎾寸箞閹柉顦查柣锝囧厴瀹曨偊宕熼妸锔芥澑闂備焦瀵х粙鎴犫偓姘煎墯缁傚秵绺介崨濠勫幈婵犵數濮撮崯鐗堟櫠椤忓牊鎳氶柣鎰梿瑜版帗鏅查柛娑卞枟閸犳劙姊洪崫鍕紨缂佺姵鎹囧濠氭晲婢跺娼婇梺缁樏崥鈧紒顔炬暬濮婃椽宕崟顒夋！缂備緡鍠栫粔鍫曞箲閵忕姭妲堥柕蹇曞Х椤撳搫鈹戦悙鍙夘棞缂佺粯甯楃粋鎺撱偅閸愨斁鎷洪梺瑙勫劶婵倝寮柆宥嗙厱闁靛鍎查崑銉︻殽閻愭彃鏆㈤柕鍥ㄥ姍楠炴帡骞嬮悩娴嬪亾閻愬樊娓婚柕鍫濇噽缁犱即鎮楀鐓庢灈鐞氭瑩鏌曡箛瀣伄缁炬崘妫勯湁闁挎繂鎳忛幆鍫ュ冀閳╁啰绡€闁靛繈鍨洪崵鈧┑鈽嗗亝缁嬫垵宓勯梺鍦濠㈡绮婚幎鑺ョ厸闁告劑鍔岄埀顒€顭烽弫宥咁煥閸愶絾鏂€闂佸疇妫勫Λ妤呮倶閻樼粯鐓欑痪鏉垮船娴滀即鏌ㄥ┑鍫濅沪闁诡垱妫冩俊鎼佹晜鐟欏嫬顏归梻鍌欐祰瀹曠敻宕伴幇顓犵彾闁糕剝绋掗崑鈺傘亜閹惧崬鐏柣鎾存礋閺屾洘绻涢崹顔瑰亾濡ゅ懏鍎楁繛鍡樻尰閻撶喐绻涢幋婵嗚埞婵炲懎绉堕埀顒冾潐濞叉牠鎮ユ總鎼炩偓浣肝旀担鍝ョ獮闁诲函缍嗛崑鍛存偟濠婂嫮绡€闁汇垽娼цⅷ闂佹悶鍔庨崢褔鍩㈤弬搴撴闁靛繆鍓濆▍鍥⒑闂堟侗妲撮柡鍛櫊瀵偊宕堕浣哄幈閻熸粌閰ｉ妴鍐幢濞戞鍘遍梺鍦劋閸ゆ俺銇愰幒鎾存珳闂佹悶鍎辨晶搴ㄥ礉閹间焦鈷戦悹鍥ｂ偓铏亶闂佹悶鍔庨弫璇诧耿娴ｇ硶鏀介柣妯诲閸儱纾婚柟鎯у绾惧吋銇勯弮鍌涙珪闁瑰啿鍟撮弻锝夋晲閸パ冨箣閻庢鍠楅幐铏叏閳ь剟鏌嶉妷銊︾彧妞ゆ挸銈稿缁樼瑹閳ь剙顭囪閹囧幢濡炪垺鐩、姗€鎮滈崱娆忓Ш闂備胶绮弻銊╁触鐎ｎ喖鐓曢柟杈鹃檮閻撴洘绻濋棃娑欘棞妞ゅ繆鏅犻弻锟犲幢濡吋鍣伴梺鍝勭焿缁插€熺亙闂侀€炲苯澧撮柡浣稿暣椤㈡棃宕煎┑鍫㈡毇闂備浇娉曢崰鎾存叏閹绢喖纭€闁规儼濮ら悡鐔兼煛閸愩劌鈧崵寮ч埀顒傜磽娴ｉ潧濡兼い顓炲槻椤繑銈︾憗銈勬睏闂佸湱鍎ら崹鎶藉窗婵犲洦鈷戦柛婵勫劚鏍￠梺缁橆殕濞茬喖骞冨ú顏嶆晣闁靛繆妾ч幏缁樼箾鏉堝墽鍒伴柟璇х節瀹曨垶鎮欑€涙ê寮挎繝鐢靛Т閸婂湱鎷归敓鐘崇厱闁圭儤鎸稿ù顔筋殽閻愭惌鐒介柟椋庡█閹崇娀鎳滈崹顐㈡毇闂傚倸鍊烽懗鍓佸垝椤栨娑㈠礃椤斻垹顦甸獮妯兼嫚閸欏绶㈤梻浣瑰濞叉牠宕愯ぐ鎺撳亗闁哄洢鍨洪悡蹇擃熆鐠轰警鍎忛柣蹇撶Ч閺屾稓鈧綆鍋呭畷宀勬煛瀹€瀣？闁逞屽墾缂嶅棙绂嶅┑瀣惞闁搞儯鍔嶉崣蹇撯攽閻樻彃鏆為柕鍥ㄧ箘閳ь剝顫夊ú锕傚磻婵犲倻鏆﹂柣鏃傗拡閺佸鏌涘☉鍗炴灕闁哄憞鍥ㄢ拻闁稿本鐟чˇ锕傛煙鐠囇呯瘈鐎殿喖顭锋俊鎼佸煛閸屾艾澹掗梻浣侯焾閻ジ宕戝☉銏犲強闁靛鏅滈悡蹇擃熆閼哥數銆掗柣锝堜含缁辨帡宕滄担闀愮捕闂佸疇顫夐崹鍧楀箖濞嗘搩鏁傞柛鏇ㄥ幒缁辨洟姊绘担鍛婃喐濠殿喚鏁婚幃褔鎮╅懡銈呯ウ婵犵數濮村ú銈夊礃閳ь剙顪冮妶鍡樺暗闁稿鍠栧畷銏ゅ箹娴ｅ厜鎷洪梻渚囧亞閸嬫盯鎳熼娑欐珷闁绘鐗呯换鍡涙煕濞嗗浚妲稿┑顔兼处閵囧嫰顢曢敐鍥╃厜闂佺硶鏂侀崑鎾愁渻閵堝棗鍧婇柛瀣尰閵囧嫰顢曢姀銏㈩唺缂備浇椴哥敮鎺曠亽闁荤姴娲ゅΟ濠囧焵椤掍焦宕屾慨濠冩そ瀹曘劍绻濋崟顓犳殼闂佽瀛╅崙瑙勭閻愬灚顫曢柟鎹愵嚙缁犺崵绱撴担楠ㄦ岸骞忛搹鍦＝濞达絽澹婇崕蹇涙煟韫囨梻绠炴い銏☆殜婵偓闁靛牆妫涢崢浠嬫⒑閻熸壆浠㈤悗姘煎枤瀵囧焵椤掑嫭鈷戦柟鑲╁仜婵倻绱掗悩宕囧⒌鐎殿噮鍋婂畷姗€顢欓懖鈺嬬床婵犳鍠楅敋鐎规洦鍓熼崺鈧い鎺戝€告禒婊勩亜椤忓嫬鏆ｅ┑鈥崇埣瀹曞崬螖閳ь剙顭囬幋锔解拺缂佸顑欓崕鎰版煙缁嬪灝鈷旀俊鍙夊姍楠炴帒螖娴ｉ晲鏉梻渚€鈧偛鑻晶瀵糕偓瑙勬礀缂嶅﹤鐣锋總绋垮嵆闁绘劗鏁搁弳顐ｇ節瀵伴攱婢橀埀顒佹礋楠炲﹨绠涘☉妯兼煣闂佸搫琚崕杈╃不閸︻厾纾兼い鏃傚亾閸も偓婵犫拃鍕弨闁哄矉缍€缁犳盯骞樼捄琛″徍闂備礁鎼張顒勬儎椤栨稐绻嗛柣鎴ｅГ閺呮粓鏌﹀Ο渚Ц闁衡偓椤撶喓绡€婵炲牆鐏濋弸娑㈡煥閺囨ê鍔氭い顏勫暣閹稿﹥寰勭仦鐐啎闂備線娼ч…顓熶繆閸モ晛濮柍褜鍓氱换娑欐綇閸撗呅氬┑鐐叉嫅缁茶法鍒掓繝姘婵°倓璁查幏缁樼箾鏉堝墽绉い顐㈩樀瀹曟垿鎮╃紒妯煎幈闂佸搫鍊介崕鑽も偓姘嵆閺岋綁鏁愰崶褍骞嬪銈冨灪椤ㄥ﹤鐣烽悢纰辨晝闁靛牆鎳庣粻鎶芥⒒閸屾瑧顦︽繝鈧柆宥呯；闁规崘顕х粈鍫熸叏濡灝鐓愰柛瀣€块弻鏇熷緞閸℃ɑ鐝曢梺缁樻尰濞叉﹢濡甸崟顖氱疀闁宠桨璁查崑鎾诲即閵忕姴鍤戦梺鍝勫暙閻楀﹪鎮￠弴鐔剁箚妞ゆ牗绮岄崝瀣煕閻斿搫浠х紒杈ㄥ笧缁辨帒螣閼测晝鏉藉┑鐘愁問閸犳帡宕戦幘缁樷拺闁圭娴风粻鎾翠繆椤愶絿娲村┑鈩冩尦楠炲洭顢栭懞銉︽澑闂備礁鐤囧Λ鍕涘Δ浣侯洸婵犻潧顑嗛悡鐔兼煟閺冣偓濞兼瑩宕濋敃鍌涚厱闁崇懓鐏濋悘鈺傘亜閹惧啿鎮戠€垫澘瀚换婵嬪磼濠婂懎鏄ユ繝纰夌磿閸嬫垿宕愰弽顓炶摕闁靛闄勫▍鐘裁归悩宸剾闁轰礁锕弻锟犲炊閵夈儳浠鹃梺缁樻尵閸犳牠寮婚敐鍛傜喖宕崟顓㈢崜闂備礁鎲￠敋闁稿﹤娼″璇测槈濡攱顫嶉梺鍛婎殘閸嬬偤鎮橀崼鐔虹閻庣數顭堝瓭缂傚倸绉撮敃銈夛綖韫囨洜纾兼俊顖濐嚙椤庢挾绱撴担鍓插剱閻庣瑳鍥х９妞ゆ牗鍩冮弨浠嬫煥濞戞ê顏╁ù鐘櫅閳规垿顢欓崫鍕ㄥ亾濡ゅ啫鍨濋悗锝庝憾閸氬顭跨捄鐚磋含闁哥偛鐖煎娲传閸曨剙绐涢梺绋款儑閸嬨倝骞冨Δ鍜佹晢闁告洦鍏橀幏娲⒑閼姐倕鏋戞繝銏★耿閸╂盯寮崒婊咃紲濡炪倖娲栭幊搴ㄦ倶閿旈敮鍋撶憴鍕闁搞劌娼￠悰顕€宕堕浣镐罕闂佸壊鍋侀崹鐟邦嚕娴煎瓨鈷掑┑鐘查娴滄粍绻涢弶鎴濐伀鐎垫澘锕幊鐐哄Ψ瑜滃ú绋库攽閻樼粯娑фい鎴濇閹繝鎮㈤崫銉х槇闂佸壊鐓堥崑鍕叏閸ヮ灐鐟邦煥閸涱収鏆梺閫涚┒閸斿秶鎹㈠┑瀣窛妞ゆ洖鎳嶉崫妤呮⒒娴ｅ摜绉烘い銉︽尰缁绘盯鍩€椤掑嫭鐓欑€规洖娲ら埢鍫熴亜閵忊槅娈滅€规洘甯℃俊鍫曞川椤旇姤鐦滈梻鍌氬€搁崐鎼佸磹閻戣姤鍤勯柛顐ｆ磵閳ь剨绠撳畷濂稿Ψ椤旇姤娅堥梻浣规偠閸庮垶宕濆澶婄煑闊洦娲滃Λ顖炴煙椤栧棗鑻崜铏箾鐎涙鐭掑ù婊嗘硾椤繒绱掑Ο璇差€撻梺鍛婄☉閿曘倝寮抽崼婵冩斀闁绘劙顤傞崵瀣磼閻樿櫕灏柣锝夘棑閹叉挳宕熼顐㈡闂佽瀛╃粙鎺楁晪婵炲濞€缁犳牕顫忛搹鍦＜婵☆垰鎼闂備礁鎲￠幐鑽ょ矙閹捐泛鍨濈紓浣骨滈崑鍛存煕閹般劍娅囬柛姗€浜跺娲棘閵夛附鐝旈梺鍛婄懄閸旀瑩鐛€ｎ喗鍋愰弶鍫氭櫅婢ф儳鈹戦悙宸殶闁告鍥ㄥ仱闁靛ň鏅滈崑鍌炴煟閺傚灝鎮戦柣鎾寸懇閺岀喖顢涢崱妤佸櫤闁硅尪鍋愮槐鎾存媴閹绘帊澹曢梺璇插嚱缂嶅棝宕板Δ鍛亗婵炴垶鍩冮崑鎾诲礂婢跺﹣澹曢梻渚€鈧偛鑻晶瀵糕偓瑙勬磻閸楀啿顕ｆ禒瀣垫晣闁绘劘鍩栭幉浼存⒒娴ｈ鍋犻柛搴㈡そ瀹曟粌顫濈捄铏规煣濠电娀娼ч鍡涙偂閸愵亝鍠愭繝濠傜墕缁€鍫熸叏濡寧纭鹃柣銈夌畺閺屾盯顢曢敐鍡楊槱闂佽桨绀侀澶愬蓟瀹ュ牜妾ㄩ梺鍛婃尵閸犲酣顢氶敐鍡欑瘈婵﹩鍘藉▍銏ゆ⒑缂佹〞鎴ｃ亹閸愵喗鍤€闁割煈鍠掗弨浠嬫煟閹邦厽缍戦柣蹇ラ檮閵囧嫰濡搁妷锔绘＆閻庤娲樺姗€锝炲┑瀣殝缁剧増蓱鐎氬ジ姊绘担鍛婂暈缂佽鍊婚埀顒佸嚬閸ｏ綁骞冮悙鍨磯闁靛ě鍜冪闯闁诲骸绠嶉崕杈┾偓姘煎枤缁綁寮崒妤€浜炬繛鍫濈仢濞呮﹢鏌涚€ｎ亷韬柣娑卞櫍瀹曞爼顢楅埀顒傜棯瑜旈弻娑⑩€﹂幋婵囩亾闂佺粯绋堥弲婊勭┍婵犲洦鍊锋い蹇撳閸嬫捇寮介鐐殿唶闂佺厧顫曢崐妤呮儗濞嗘挻鐓欓柣鎴炆戦悡娑㈡煕鐎ｎ偅宕岀€规洖缍婇、鏇㈠Χ閸涱亝瀚插┑鐘愁問閸犳牠鏁冮敂鎯у灊妞ゆ牜鍋涚粻顖炴煕濞戝崬鏋ら柣鐔活潐閵囧嫰寮介妸褉濮囬梺鍝勬閸嬨倕顫忛搹瑙勫珰闁肩⒈鍓涢鍥╃磽娴ｈ櫣甯涢柛銊ユ健楠炲啴鎮滈懞銉︽珖闂佺鏈銊╁蓟瑜旈弻锝夋偐閻戞ǜ鈧啰绱撳鍛х€殿噮鍣ｅ畷鐓庘攽閸℃瑧宕哄┑锛勫亼閸婃牠骞愰悙顒€鍨旀い鎾卞灩閼稿綊鏌ｉ姀鐘冲暈闁抽攱甯掗湁闁挎繂鎳忛崯鐐烘煕閻斿搫浠滈柕鍡樺笒椤繈顢樿閻や線鎮楃憴鍕濠电偛锕妴浣糕枎閹惧啿绨ユ繝銏ｅ煐缁嬫挾绮旈鍕厪闁搞儯鍔屾慨宥嗩殽閻愭潙娴鐐差儔閹亪鍩€椤掑嫬鐤柛銉墯閳锋垿鏌涘┑鍡楊伌婵″弶鎮傞弻锝呂旈埀顒€螞濞嗘挸鐤鹃柛顐ｆ礃閸嬧晝鈧厜鍋撻柍褜鍓熼幆灞解枎韫囧﹥鏂€闂佺粯锚绾绢參銆傞弻銉︾厽闁规儳鐡ㄧ粈瀣煛瀹€瀣埌閾伙綁鏌涘┑鍡楊仾婵絾鍔曢埞鎴︽倷鐎涙ê鍓归梺鍝ュУ椤ㄥ﹪鐛崼銉ノ╅柨鏂垮⒔閻﹀牓姊洪崨濠傚闁哄倸鍊圭粋鎺楀閵堝棌鎷洪梺闈╁瘜閸欏酣宕濆鍛＜缂備焦顭囩粻鏍庨崶褝韬€规洖銈稿鎾倷閼碱剛宕哄┑锛勫亼閸婃牕螞閸愵喖鏋佹い鏇楀亾鐎规洘鍨块獮妯兼嫚閼碱剛鏆伴柣鐔哥矊椤﹂潧顕ｉ妸锔绢浄閻庯綆鍋嗛崢浠嬫⒑瑜版帒浜伴柛妯垮亹瀵板﹪鎳￠妶鍥╋紲闂佺粯鐟﹂悷銉ッ洪敃鍌涘亗闁哄洢鍨洪悡蹇撯攽閻愯尙浠㈤柛鏃€绮撻幃褰掑箛閸撲胶鐦堥梺鍝勬湰閻╊垶鐛幒妤€绠婚柧蹇ｅ亯閻т線鏌ｆ惔銈庢綈婵炲弶鐗犳俊鍫曞箹娴ｅ摜鐣洪梺闈涚箞閸婃牠骞嗛悙鐑樺仭婵炲棗绻愰鈺傜箾閸垹浠辨慨濠傤煼瀹曟帒鈻庨幋鐘靛床闂備線鈧偛鑻晶浼存煕鐎ｎ偆娲撮柟宕囧枛椤㈡稑鈽夊▎鎰娇闂佽瀛╃粙鎺楁晝閳轰讲鏋斿ù鐘差儐閻撶喖鏌熼柇锕€澧紒鐙欏嫨浜滈柕澶涚到閻忣噣鏌嶈閸撴繈锝炴径濞掑搫顭ㄩ崼婵嗗亶閻熸粍妫冨畷娲倷閸濆嫮顓洪梺鎸庢磵閸嬫挾绱掗悩宕団姇闁靛洤瀚伴獮鎺戭吋閸ヨ埖袦闂備線鈧偛鑻晶濠氭煕閵娿劍纭炬い顐㈢箳缁辨帒螣鐠囧樊鈧捇姊洪崨濠勨槈闁挎洏鍊濆鎶藉醇閵忋垻锛濇繛鎾磋壘濞层倝寮稿☉銏＄厽婵°倐鍋撶紒缁樺浮瀹曟岸骞掑Δ鈧柋鍥煟閺冨偆鐒炬い搴㈡尵缁辨挻绗熼崶褏浠┑鐐插级閿曘垽骞冨Ο鑽ょ懝闁逞屽墮椤繐煤椤忓拋妫冨┑鐐寸暘閸庨亶鎮ч幘鎰佸殨闁圭粯甯╅悡銉╂煕椤愶絿绠橀柛姗€浜跺铏规兜閸涱喖娑ч梻鍌氬鐎氫即宕哄☉銏犵闁绘劦浜欑花濠氭⒑鐟欏嫬顥愰柡鍛洴閸┾偓妞ゆ帊鐒︾粈鍐磼閸屾稑绗掓い顓滃姂瀹曞ジ鎮㈤崫鍕濠电姷鏁搁崑鐘典焊椤忓牜鏁嬬憸鏃堝箖濮椻偓閺佹捇鎮╁畷鍥у箰闂備礁鎲℃笟妤呭储妤ｅ啫鏄ラ柨婵嗘礌閸嬫挸鈻撻崹顔界亪闂佺粯鐗曢妶鎼佹偘椤旈敮鍋撻敐搴℃灈缂侇偄绉归弻宥堫檨闁告挾鍠庨锝夘敆閸曨偆鍔?"
        return "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙绐涢梺鍝ュУ閹稿墽鍒掔紒妯稿亝闁告劏鏅濋崢浠嬫⒑闁稑宓嗘繛浣冲嫭娅犳い鏍仦閻撶喐绻濋棃娑欏缂佲偓鐎ｎ偅鍙忓┑鐘叉噺椤忕姷绱掗鐣屾噧闁宠閰ｉ獮鍡氼槻濠㈣锚閳规垿鎮欓懠顒佹喖缂備緡鍠氭慨鐢电矉瀹ュ鏁傞柛鏇㈡涧濞堛劑鏌ｉ悩鍙夊缂佷焦娼欏嵄闁割偁鍎查悡蹇涚叓閸ャ劍绀€閸熸悂姊洪崨濠冣拹闁圭鍟块～蹇撁洪鍕獩婵犵數濮撮崐姝岊杺婵犵數鍋涢悺銊у垝瀹ュ鍋嬮柡鍥╁仜缁侇偊姊绘担绋款棌闁稿绶氬畷褰掓嚒閵堝拋妫滈梺鑺ッˉ銏ｃ亹閹烘挻娅滈梺绯曞墲椤ㄥ牏绮婇柨瀣閻庢稒顭囬惌鎺旂磼閻樺磭澧い顐㈢箻閹煎綊宕烽鐘靛幆闂佽崵濮垫禍浠嬪礉鎼淬垹顕遍柛銉墯閳锋垹绱掔€ｎ偒鍎ラ柛搴㈠灴閺屾稓鈧絻鍔岄埀顒佺箞閻涱噣宕橀鑺ユ闂佺粯蓱瑜板啫鐣甸崱娑欌拺缂備焦蓱閳锋帞绱掔紒妯肩畼闁奸缚椴哥换婵嗩潩椤撴稒瀚奸梺鑽ゅ枑閻熴儳鈧凹鍘惧▎銏ゅ箵閹烘繄鍞甸悷婊冪Ч閺屽﹪鏁愭径灞界ウ闂佸憡鍔﹂崰妤呭吹閸愵喗鐓冮柛婵嗗閺嗙喖鏌ㄥ☉娆戠煉婵﹨娅ｇ槐鎺戭潨閸℃瑥濮兼繝鐢靛仜閹冲繐煤閺嶎厽鍋╃€瑰嫭澹嗛弳鍡涙煕閺囥劌澧伴柛妯绘倐閹宕楁径濠佸闂佽鍑界紞鍡涘礈濞戞壕鍙烘繝寰锋澘鈧鎱ㄩ悜钘夌；闁绘劕鐏氶弳婊堟煥閻斿搫啸鐎规挷绶氶幃妤呮晲鎼存繄鎸夐梺鍝勵儏闁帮綁鎮￠锕€鐐婄憸鏃堫敁濡ゅ懏鐓曢柕濠忓缁犵偞鎱ㄦ繝鍌ょ吋鐎规洘甯掗埢搴ㄥ箣椤撶啘婊堟⒒娴ｅ憡璐￠柍宄扮墦瀹曟垶绻濋崶褏鐣炬繝銏ｆ硾椤戝洭姊介崟顓犵＜閻庯綆鍘界涵鍫曟煟濞戞牕鍔︽慨濠呮閹叉挳宕熼銈庢О婵＄偑鍊栧▔锕傚川椤栨粌绠垫繝寰锋澘鈧劙宕戦幘缁樼厓閻熸瑥瀚悘鎾煙椤旇娅婇柣鎿冨亰椤㈡﹢鍩勯崘顭戞綍闂傚倸鍊烽懗鍓佸垝椤栨娑欐媴缁洘鐎洪梺鎸庣箓濞层倝藟濮樿埖鐓曢煫鍥ㄧ⊕閿涚喓绱掔拠鍙夘棡闁靛洤瀚板浠嬪Ω瑜忛悡鈧梺姹囧焺閸ㄧ増鏅舵惔锝嗩潟闁圭偓鍓氶崥瀣归敐澶嬫珳濠㈣娲熷濠氬磼濮橆兘鍋撻幖浣哥９闁归棿绀佺壕鍦偓鐟板閸ｇ銇愰幒鎴犲€炲銈嗗笒椤︿即寮查鍫熷仭婵犲﹤鍟撮崣鍕煏閸℃鏆ｅ┑锛勫厴閸┾剝鎷呮笟顖氭櫍婵犵數鍋犻幓顏嗗緤閸ф绠犻柟鎹愵嚙閻掑灚銇勯幒鎴濇殭闁绘挻鍔欓弻鐔哥瑹閸喖顬堥柧浼欑秮閺屾盯鈥﹂幋婵囩亾闂佸憡锕╅崑濠傤潖閾忓湱鐭欐繛鍡樺劤閸撴澘顪冮妶鍡楃仴妞わ箓娼ч锝嗙節濮橆厽娅滈梺鍛婄☉閸婂宕伴弽褏鏆︾憸鐗堝俯閺佸﹪鏌ｉ幇闈涘⒒闁搞倕瀚板濠氬磼濞嗘埈妲梺鍦拡閸嬪嫯鐏嬮柣搴ㄦ涧閹芥粍绋夊澶嬬厵闁硅鍔﹂崵娆撴煢閸愵亜鏋涢柡灞炬礋瀹曠厧鈹戦崶褏鐛╅梻浣规た閸樹粙鎮烽埡鍛畺鐟滅増甯掔粻鎺楁煙閻戞ê鐏ユい顒€妫涚槐鎾寸瑹閸パ勭亾闂佽桨绀侀幗婊兾ｉ幇鏉跨閻犲洩灏欓敍婊冣攽椤旂即鎴︽儊閻戣棄顫呴柨娑樺椤旀洟鎮楅悷鏉款棌闁哥姵鐗曢锝夘敊闁款垰浜炬繛鍫濈仢閺嬶附銇勯弴鍡楁搐閻撯€愁熆閼搁潧濮囨い顐㈡嚇閺岋絽螣濞茶鏅遍梺鍝ュ枎椤戝棛鎹㈠┑鍡╁殫闂佸灝顑嗙欢鏌ユ煃瑜滈崜姘跺礉濞嗗繒鏆﹂柟杈剧畱缁犺崵绱撴担璇＄劷闁告鏁婚幃妤呮偡閺夋浼冮梺绋款儏閿曨亜鐣烽弴锛勭杸婵炴垶顭囬、鍛存⒒娓氬洤澧紒澶屾暬閹繝鎮㈤崗鑲╁幍闁哄鐗嗘晶浠嬪礆閹殿喗鍋栨慨妯垮煐閳锋垿鏌熼幆鏉啃撻柡渚€浜堕幃浠嬵敍濞戞ɑ璇炲┑鐘亾濞撴埃鍋撴慨濠冩そ楠炴劖鎯旈敐鍥╂殼闂佽瀛╅崙褰掑垂閸洏鈧礁螖閸涱喖浜滈梺绋跨箺閸嬫劙宕㈡禒瀣拺闁革富鍘奸崝瀣煕閵娧勬毈闁糕晜鐩顕€宕掑鍜冪床闂佸搫顦悧鍕礉瀹€鈧划顓☆槾缂佽鲸甯楀蹇涘Ω閵壯呮噯闂佸彞绱紞渚€寮诲☉妯锋斀闁糕剝顨忔导灞解攽閻愭彃鎮戠€光偓缁嬫娼栫紓浣股戞刊瀵哥磼濞戞﹩鍎忔繛鍫熷姍濮婃椽宕妷銉︾彙闂佺顑呴敃銈夋偩閻戣姤鍋勭痪鎷岄哺閺咃綁姊虹紒妯忣亪鎮樺璁圭稏鐎光偓閸曨兘鎷婚梺绋挎湰閻熝囁囬敃鍌涚厵閻犲泧鍛槇閻庤娲樼换鍡欑不濞戞ǚ妲堟俊顖氬悑閻擄絾绻濋悽闈浶㈤柨鏇樺€濋幃褎绻濋崶褏锛涢梺缁樻煥閸氬鎮￠悢鍏肩厵閺夊牆澧介崚鎵偖濮樿埖鈷戦柟鎯板Г閺侀亶鏌涢妸銉﹀仴鐎殿喖顭烽幃銏ゆ惞閸︻厾鍘梻浣稿閻撳牓宕抽鈧畷婵囧緞瀹€鈧壕钘壝归敐鍡楃祷濞存粓绠栧娲焻閻愯尪瀚板褍鐡ㄩ幈銊︾節閸涱噮浠╃紓渚囧枟閻熲晛鐣烽悩璇茬伋闁稿繐鎳愰惌妤冪磽閸屾艾鈧悂宕愰崫銉х煋闁圭虎鍠楅弲婵囥亜韫囨挾澧㈢€规挷绶氶弻娑㈠箛闂堟稒鐏嶉梺绋匡功閸忔﹢寮婚敐澶婎潊闁靛繆鍓濆В鍕⒑閹稿海鈯曠紒顔肩焸閸╃偤骞嬮敃鈧悡锟犳煕閳╁喚娈樺ù鐘虫綑椤啴濡堕崱妯垮亖闂佸憡鍔栭崕鍐测枔閵娾晜鈷戦柛鎾瑰皺閸樻盯鏌涢悩鍐叉诞鐎殿喓鍔戦幊鐐哄Ψ閿濆嫮鐩庨梻浣告惈閸燁偊宕愭繝姘闁稿本绋撶粻楣冩煕椤愩倕鏋戦柍閿嬪姇鑿愰柛銉戝秷鍚銈冨灪濞茬喖寮幇顓熷劅闁靛繈鍨哄▓鍓х磽閸屾艾鈧绮堟笟鈧畷鎰板传閵壯呯厠閻熸粎澧楃敮鎺旂不閺嶃劎绠鹃柛鈩冾殔婵挳骞栭幖顓犲帥闁轰礁瀚伴幃褰掑箒閹烘垵顬嬪┑鐐差槸濞尖€愁潖婵犳艾纾兼慨妯垮亹閸欐洟姊虹粙娆惧剰閻庢凹鍓涢崣鍛存⒑閹稿孩绀€闁稿﹤鎽滅划缁樺鐎涙鍘甸梻鍌氬€搁顓㈠礉瀹ュ鐓曢柕鍫濇媼閸庢垿鏌熼崣澶嬪€愰柟顔ㄥ洤閱囨繝闈涚墢閹虫牠姊绘担铏瑰笡闁瑰憡鎮傚畷顖炲箻椤旇壈鎽曢梺鎸庢磵閸嬫捇鎽堕敐鍛偓鎺戭潩閻撳海浠梺宕囩帛閹告悂鍩為幋锕€鐓￠柛鈩冾殘娴犳岸姊虹粙娆惧剱闁瑰摜绮粚杈ㄧ節閸ヮ灛褔鏌涢妷顔句虎闁靛鏅滈悡鏇㈡倵閿濆骸澧ù鐘讳憾閺岀喖顢欓幆褍骞嬮梺绯曟杹閸撴繈骞忛崨瀛樺€绘俊顖涙た閸熷骸鈹戦悩娈挎毌婵℃彃鎳樺畷褰掓焼瀹ュ孩鏅炲┑鐐叉缁箖鏁愰崱鎰簼闂佸憡鍔忛弬渚€骞忓ú顏呪拺闁告稑锕﹂埥澶愭煥閺囨ê鈧繈骞冨鈧崺锟犲川椤旀儳骞嶉梻浣瑰劤濞存岸宕戦崨顓犳殾鐎光偓閸曨剛鍘遍梺鍐叉惈閸燁偅绂掓潏顭戞闁绘劕妯婇崕鏃堟煛娴ｇ鈧潡骞愭繝鍐ㄧ窞闁糕剝銇炴竟鏇㈡⒑缂佹ê鐏卞┑顔哄€濆畷鎰板垂椤愩倗顔曢梺鐟邦嚟閸庢劖绂掗悙顑句簻闊洦鎸婚ˉ婊堟煛鐎ｎ亞澧㈤柍褜鍓欑粻宥夊磿閸楃倣娑樷槈濮橆剙袣闂侀€炲苯澧存慨濠冩そ瀹曟﹢鎳犻渚囧敻闂備胶顭堥鍡涘箲閸ヮ剙钃熸繛鎴欏灩缁犳盯鏌ｉ姀銈嗘锭閻㈩垬鍎靛娲川婵犲啰鍙嗗銈忕畳娴滎剙危閹版澘绠婚悗娑櫭鎾剁磽娴ｅ壊鍎忕紒銊╀憾瀹曟垿骞樼拠韫炊闂侀潧锛忛崨顖氬脯闂傚倷绀佸﹢閬嶆惞鎼淬劌闂い鏍ㄧ矌缁€濠囨煛瀹ュ骸骞楅柣鎾崇箻閻擃偊宕堕妸锔绢槬闁哥喐鎮傚娲传閸曨剦妫炲┑鈽嗗亝缁诲牆顕ｇ拠宸悑闁割偒鍋呴鍥⒒娴ｅ憡鍟為柟鎼佺畺瀹曚即寮介鐘茬ウ闂佸憡鍔﹂崰鏍煥閵堝棔绻嗛柕鍫濆€告禍楣冩⒑缂佹ê绗掗柣蹇斿哺婵＄敻宕熼姘鳖唺闂佺懓鐡ㄧ换宥嗙妤ｅ啯鈷戦柟鎯板Г閺侀亶鏌涢妸銉﹀仴妤犵偛鍟悾锟犲箥閾忣偆鈧妫呴銏″闁瑰皷鏅滅粋鎺撶附閸涘ň鎷洪梺鍛婄☉閿曘儵鎮￠悢鍏肩厱濠电姴鍟扮粻鐐碘偓娈垮枦椤曆囧煡婢舵劕顫呴柍銉ュ帠缁ㄥ姊婚崒娆戭槮闁诲繑绻堥、鏍川椤旂虎娴勯梺鍦檸閸犳宕愰悽鍛婂仭婵炲棗绻愰顏勵熆鐠哄搫顏柡灞剧洴楠炴鎹勯悜妯尖偓鐐箾閿濆懏鎼愰柨鏇ㄤ邯閻涱噣寮介妸锕€顎撻柣鐔哥懃鐎氼參鎮甸弴銏♀拺闁煎鍊曟牎婵炲瓨绮堢划娆忕暦濠靛洦鍎熼柕濠忕畱娴犲ジ姊虹紒妯哄Е闁稿繑绋撻幑銏ゅ幢濞戞瑧鍘介梺瑙勬緲閸氣偓缂併劌顭烽弻宥堫檨闁告挻宀搁幃褔鎮╅懠顒佹濠电娀娼ч鍡涘疾濠靛鐓曢悘鐐靛亾閻ㄦ垶銇勯敂璇插箹闁宠鍨块幃娆撳级閹寸姳鎴烽梻浣规偠閸斿苯锕㈡潏鈺佸灊闁割偁鍎遍獮銏′繆閻愬瓨绀€缂傚秴锕獮鍐焺閸愨晛鍔呴梺鎸庣箓濡瑩宕伴弽顓熲拻濞达綀娅ｇ敮娑㈡煙閹间胶鐣虹€规洑鍗抽獮鍥敇閻橆偅鏁靛┑鐘垫暩婵潙煤閵堝懏绾梻鍌欑閹测€趁洪敃鍌氬偍闁稿繘妫跨换鍡椕归悩宸剱闁稿﹦鏁婚幃宄扳枎韫囨搩浠剧紓浣插亾闁逞屽墴濮婃椽宕崟顓炩拡闂佸憡鎸鹃崰鏍ㄤ繆閹绢喖绀冩い鏂挎閵娾晜鐓冮柛婵嗗閳ь剚鎮傞崺鈧い鎺戝€搁崢鎾煛瀹€鈧崰鎾诲窗婵犲洤纭€闁绘劘灏欓鎴︽⒒娴ｉ涓茬紓宥勭窔钘熼柟鎹愬煐椤洟鏌熼幆褏鎽犲┑顖涙尦閺屻倝骞侀幒鎴濆闂侀€炲苯澧柛鐔稿濡叉劙骞掑Δ濠冩櫓闂佷紮绲介張顒勫闯瑜斿鐑樺濞嗘垶鍋ч梺绋跨箲钃卞ǎ鍥э躬楠炴牗鎷呯憴鍕彆闂備礁鎲￠幐鍡涘川椤曞懏缍嬮梻鍌氬€搁崐椋庣矆娓氣偓楠炲鏁撻悩鑼槷闂婎偄娲︾粙鎴︽偪閻愵剛绡€闂傚牊渚楅悞鎯瑰鍐Ш闁哄本娲樼换娑㈡倷椤掍胶褰嗛梻浣瑰▕閺€閬嶅垂閸ф绠栫憸鐗堝笒閻愬﹪鏌曟繛褍鍟紒鈺備繆閻愵亜鈧洜鈧稈鏅犻妴鍐╃節閸パ嗘憰濠电偞鍨堕…鍌炴偄閸忕厧娈ラ梺闈涚墕濞层劑宕㈠鍫熺厽閹兼番鍊ゅ鎰箾閸欏鑰跨€规洖缍婂畷绋课旈崘銊с偊婵犵妲呴崹鐢稿磻閹邦喖顥氶柛蹇涙？缁诲棙銇勯弽銊х煀閻㈩垰鐖奸幃浠嬵敍濞戣鲸鐤侀梺鍝勭焿缂嶄線骞冮姀銈呬紶闁靛／鍛笒缂傚倸鍊风欢锟犲窗濡ゅ懎绠伴柟闂寸劍閸嬧晝鈧懓瀚伴崑濠囨偂閵夆晜鐓曟い鎰╁€曢弸搴∶瑰鍕煉婵﹨娅ｇ槐鎺懳熺拠鑼暡濠德板€楁慨鐢稿箖閸岀偛绠栨俊銈呮媼閺佸洭鏌曡箛濠冾€嗛柟閿嬫そ閺岋綁鎮╅崣澶岊槺闂侀€炲苯澧痪缁㈠幗鐎靛ジ宕堕浣叉嫼闁荤姴娲╃亸娆戠不閺屻儲鐓熼柍鍝勶工閻忥附顨ラ悙鎻掓殻濠殿喒鍋撻梺闈涚墕濡绂嶅Δ鍛厵闁煎湱澧楄ぐ褏绱撳鍛棞閸楄鲸銇勯弽顐沪闁抽攱甯掗湁闁挎繂鐗婇鐘绘偨椤栨稓娲撮柡宀€鍠撶划娆撳箰鎼淬垹鏋戦梻渚€鈧偛鑻晶顕€鏌ｈ箛鏃€鐨戦柡渚囧櫍閺佹捇鎮╅崣澶嬓氶梻渚€鈧偛鑻晶顖炴煏閸パ冾伃妤犵偞甯掗濂稿醇濠靛棗鑵愬┑鐘垫暩閸嬬偠銇愰崘顔藉仱闁靛ň鏅涚粻鐐烘煏婵犲繐顩紒鈾€鍋撻梻浣告啞閸斿繘寮崒娑氼浄闁靛繒濮弨浠嬫煃閽樺顥滃ù婊勭矒閺屾盯鎮ゆ担闀愬枈闂佺硶鏂傞崕鎻掝嚗閸曨剛绡€閹兼番鍨归崗濠冧繆閻愵亜鈧牜鏁幒妞濆洭寮堕崯鍐╁浮瀹曞爼顢楁担鍙夊闂備胶顭堥張顒勬偡閵娾晛绀傜€光偓閳ь剛妲愰幒妤婃晪闁告侗鍘炬禒鎼佹⒑闂堟稒顥滈柛鐔告綑閻ｇ兘濡搁埡濠冩櫖濠电偞鍨堕敋缂併劊鍎靛缁樻媴閸涘﹨纭€闂佺绨洪崐婵嗩嚕婵犳艾惟闁宠桨绀侀悗顓炩攽閻樼粯娑ф俊顐㈢焸瀵劍绂掔€ｎ偆鍘藉┑鈽嗗灥濞咃綁鏁嶅鍡愪簻闁挎繂妫涢崣鈧梺鍝勬湰缁嬫捇鍩€椤掑﹦鍒板褍娴峰褔鍩€椤掑嫭鈷戦柛婵嗗閻忛亶鏌涢悩鍐插妤犵偛绻樺畷銊╁级閹寸媭妲伴梻浣稿暱閹碱偊宕鈶╂鐟滃孩绌辨繝鍥ㄥ€锋い蹇撳閸嬫捇濡舵径濠勶紱闂佸憡娲﹂崢楣冩儗閹剧粯鐓熼柣鏃傚帶娴滅増绻涢崗鑲╁缂佺粯绋戦蹇涱敊閼姐倗娉块梻浣告贡椤㈠﹪宕洪弽顓炍﹂柛鏇ㄥ灠缁犵粯銇勯弽銊ㄥ闁冲嘲顦—鍐Χ閸涱収鍔夊銈冨妼閿曘倝锝炶箛鎾佹椽顢旈崟顓у晣闂備胶绮崝鏍亹閸愵喒鈧牜鈧綆鍋嗙弧鈧梺鍐茬殱閸嬫捇鏌涢弴鐐典粵闁伙綀鍋愮槐鎾寸瑹閸パ勭亪濡炪倖鍨甸幊姗€銆佸鈧畷妤呮偂鎼达絿鐛┑鐘垫暩婵鈧凹鍣ｅ铏鐎涙鍘介梺缁樻煥閹芥粓鎯屾繝鍐︿簻闁挎洖鍊瑰☉褎銇勯弴顏嗙М濠碘剝鎮傞崺锟犲磼濮橆厾鏋€闂傚倷绶氬褔篓閳ь剛绱掗懠璺轰汗闁奸缚椴哥换婵嗩潩椤撴稒瀚奸梻浣告啞缁诲倻鈧凹鍓熷鍐测枎閹惧鍘辨繝鐢靛Т鐎氼參宕甸埀顒勬⒑鐎圭媭鍤欑紒澶屾嚀椤曪綁骞橀钘変汗闂佹眹鍨婚。顔炬閹惰姤鈷掑ù锝勮閻掗箖鏌￠崼顐㈠缂侇喗鐟╅獮瀣晝閳ь剚瀵奸悩宕囩鐎瑰壊鍠曠花濂告煟閹惧娲撮柟顔斤耿閹瑩骞撻幒鍡樺瘱闂備焦鍓氶崹鍗灻洪悢鐓庤摕闁绘梻鈷堥弫宥嗙箾閹寸偟鎳愭俊顐㈠暣濮婃椽骞栭悙鎻掝潎缂備胶濮甸悧鐘荤嵁閺嶎兙浜归柟鐑樼箖閺呮繈姊洪幐搴ｇ畵婵炶绠掗·鍛存⒒閸屾艾鈧悂宕愰幖浣哥９闁绘垼濮ら崐鍧楁煥閺冨牊鏆滈柛瀣尵缁厼鈽夊Ο鍝勭婵°倧绠掑▔鏇㈡偪閳ь剙鈹戦悙鏉戠仸闁挎岸鏌ｆ惔顔煎箺缂佺粯绋撻埀顒傛暩椤牆鐡俊鐐€栭崹鐢稿箠濡警鍤曢柛娑橈功閻熷綊鏌嶈閸撶喎顕ｆ繝姘亜闁绘挸娴烽ˇ顓㈡偡濠婂啰绠抽柡渚囧枛閳藉濮€閿涘嫬骞堥梺璇插嚱缂嶅棝宕戦崟顒佸弿鐎广儱顦伴悡娑㈡倶閻愭彃鈷旀繛鎻掔摠椤ㄣ儵鎮欓崣澶婃灎濡炪們鍨洪敃銏ゅ箖濞嗘挻鍋ㄩ柣鎰嚀娴狀厼鈹戦悩鍨毄濠殿喕鍗冲畷瑙勭節濮橆剛鐤囬梺瑙勫劤閻忓牓宕戦幘鎰佹僵妞ゆ挾鍠撻崙鈥愁渻閵堝骸浜滅紒缁樺笧濡叉劙骞掗幊宕囧枔閹风姴顔忛鐟颁壕闁瑰墽绮埛鎴︽煕濞戞﹫鍔熼柍钘夘樀閺屻劑寮村Ο琛″亾濠靛棭鍤曢柟鎯版闁卞洦绻濋棃娑樻殲闁哄倵鍋撻梻鍌欒兌缁垶宕濆▎鎾€鐑藉磼閻愭彃鎯為柣搴秵閸撴稓澹曟總鍛婄厽婵☆垱瀵ч悵顏堟倶韫囷絽寮柡宀嬬秮閺佹劙宕惰楠炲鎮楀▓鍨灕婵炲鐩崺銏℃償閵婏箑鈧攱銇勯幒鍡椾壕闂佺绻愰敃顏勵潖濞差亜浼犻柛鏇炵仛绗戦梻浣虹帛椤ㄥ懘宕弶鎴殨闁圭粯宸婚弸搴ㄦ煙鐎电啸闁伙綀鍩栫换婵嬪閿濆懐鍘梺鍛婃⒐閻楃娀宕哄☉銏犵闁挎梻鏅崢鍗炩攽閻樼粯娑ф俊顐ｎ殜椤㈡棃顢曢敂鐣屽帗闁荤姴娲ゅΟ濠偽熼埀顒勬⒑閸濆嫮鐒跨紓宥佸亾缂備胶濮甸惄顖氼嚕椤掑嫬鍨傛い鏇炴噺缂嶆帡姊婚崒娆愮グ妞ゆ洘鐗犲畷鏉款潩鐠鸿櫣顦у┑顔姐仜閸嬫挾鈧鍠栭…宄扮暦閸洦鏁嗗ù锝堫潐閻濇洟姊绘担绛嬪殐闁搞劌閰ｅ畷姗€鍩￠崟顓炲絺闂傚倸鍊搁崐鎼佸磹閹间礁纾瑰瀣捣閻棗銆掑锝呬壕濡ょ姷鍋涢ˇ鐢稿极閹剧粯鍋愰柤纰卞墻濡茬兘姊绘繝搴′簻婵炶濡囩划娆撳箣閿旇棄浠鹃梺缁樺姦閸忔瑦绂嶅鍫㈠彄闁搞儯鍔嶇亸鐗堛亜閵壯冧沪闁靛洤瀚伴、鏇㈡晲閸℃瑯妲归梻浣告惈閺堫剙煤濡吋宕叉繛鎴炵矤濡插姊虹涵鍛彧闁告梹鐟╁顐㈩吋閸涱亝鏂€闂佹悶鍎弲婵嬵敊閺囥垺鐓涘璺猴功婢ф洖顭胯閺咁偊鍩€椤戣法绁烽柛瀣姉濡叉劙骞掑Δ濠冩櫓闂佷紮绲介張顒勫闯娴煎瓨鍊甸悷娆忓婢跺嫰鏌涚€ｎ亷韬鐐寸墳閵囨劙骞掗幋鐐茬ザ婵＄偑鍊栭幐鐐垔鐎靛憡顫曢柡灞诲劜閳锋垿鏌ゆ慨鎰偓鏇炵摥婵犵數鍋炵粊鎾疾濠靛洨顩茬紒瀣氨閺嬪酣鏌熼柇锕€骞楅柣婵堝厴濮婃椽宕崟顒€鍋嶉梺鎼炲妽濡炰粙骞冮敓鐘冲亜闁稿繗鍋愰崣鍡椻攽閻樼粯娑ф俊顐ｇ懇瀹曞磭鎲撮崟顏嗙畾闂佸湱绮敮鈺呮偂婵傚憡鐓欓柦妯侯槺閸╋綁鏌℃担鐟板鐎规洏鍔戦、鏇㈡偄閾氬倸顥氶梻浣告贡閸庛倝宕洪崼婵愮劷闁冲搫鎳忛悡鐔兼煙閹规劖鐝柟鐧哥到闇夐柣姗嗗亝濞呭﹥鎱ㄦ繝鍛仩闁归濞€閸ㄩ箖鎼归銈勬喚闂傚倷鐒﹂幃鍫曞礉瀹€鍕€舵繝闈涱儜缂嶆牠鐓崶銊﹀婵炲樊浜堕弫鍌炴煕閺囥劌浜為柣娑掓櫅閳规垿鎮╅崹顐ｆ瘎婵犳鍠楁繛濠囧箠濡ゅ懎绀堝ù锝囨嚀鎼村﹥绻涢幘鏉戠劰闁稿鎸婚幈銊︾節閸愨斂浠㈤悗瑙勬磸閸斿秶鎹㈠☉銏犵闁哄洨鍋樺Ч妤呮⒑閸涘﹤绗氶悽顖涘浮閸┿垺鎯旈妸銉ь啋閻庤娲栧ú銊╁汲椤愶絿绡€鐎典即鏀卞姗€鍩€椤掍焦绀嬫鐐茬箳閳ь剨缍嗛崰鏍几娓氣偓閺屾盯骞囬棃娑欑亶闂佺粯鎸堕崕鐢稿蓟閿熺姴绀冮柕濞垮劗閸嬫捇鎮烽幍铏€洪梺鍝勬储閸ㄦ椽鎮￠弴鐔剁箚妞ゆ牗纰嶇拹锟犳煟椤撶喓鎳囬柡灞糕偓宕囨殕闁逞屽墴瀹曚即寮借閺嗭附淇婇妶鍛櫤闁搞倕鍟撮弻宥夊传閸曨偀鍋撹ぐ鎺濇晩闁告劦鍠楅埛鎺懨归敐鍕劅闁绘帞鍋撻妵鍕敇閻愰潧鈪甸悗瑙勬礃閸旀瑥顕ｉ幘顔肩厬闁宠鍎虫禍楣冩煥閺囩偛鈧悂鎮欐繝鍐︿簻闁瑰搫妫楁禍鍓х磽娴ｅ搫校缂佸甯℃俊鐢稿礋椤栨氨顓哄┑鐐叉缁绘帗绂掓總鍛娾拻濞达絿顭堢花鑽ょ磼闊厾鐭欓柟顕€绠栭幃婊堟寠婢舵劕鏁归梻浣告惈濞层劑宕愰敐澶婄厸闁告侗鍠氶崣鍡涙⒑閸濆嫬鏆欐繛璇х畵婵℃挳宕橀鐣屽弰闂婎偄娲﹂幑鍥矗閸曨剚鍙忓┑鐘插鐢稓绱掑Δ鍐ㄦ灈闁糕斁鍋撳銈嗗坊閸嬫挻銇勯鐐寸┛妞わ附鐓￠幗鍫曟倷缂堢姷绠氶梺闈涚墕閹冲繘宕抽崷顓犵＜闁绘﹢娼ф牎闂侀€涚┒閸斿矂鈥旈崘顏呭珰闂婎偒鍘奸ˉ姘舵⒑鐠囨彃顒㈡い鏃€鐗犲畷鎶筋敋閳ь剙鐣烽幋鐐电瘈闁稿本绮嶅▓楣冩⒑閸︻厼鍔嬫い銊ユ瀹曟劙鎮滈懞銉у幐婵犮垼娉涢鍛存倶閿濆鐓欐い鏇炴缁夘喗鎱ㄦ繝鍛仩闁归濞€閹崇娀顢楅崒銈呮暯闂傚倷鑳堕…鍫ヮ敄閸℃稒鍎庢い鏍仧瀹撲礁顭块懜闈涘闁哄懏鎮傞弻锝呂熼崫鍕瘣闂侀€炲苯澧柣鏍с偢瀵鈽夐姀鐘电杸闂傚倸鐗婄粙鎺楁倶瀹ュ鈷戠紓浣股戠亸鐢告煕閻樺磭澧甸柣娑卞櫍瀵粙濡搁敂鍓ら梻浣告啞閹稿棝宕崘顏勬優闂傚倸鍊峰鎺旀椤斿墽绀婇柛鈩冪☉閻鏌涢幇闈涙灈闁藉啰鍠愮换娑㈠箣閻愬灚鍣梺绋挎捣閸犳牠寮婚弴鐔虹闁割煈鍠掗崑鎾诲冀椤撶偟鐛ュ┑顔筋焾閸╂牠鍩涢幋锔藉仯闁搞儻绲洪崑鎾绘惞椤愶綆鍞查梻鍌欑閹诧繝宕濋弴鐔告珷濞寸姴顑呴惌妤呮煕閳╁啰鈯曢柍閿嬪灩缁辨帞鈧綆鍘界涵鍓佺磼閻樻彃鏆遍柍瑙勫灴椤㈡岸鍩€椤掆偓椤洩顦归柍銉︽瀹曟﹢鍩￠崘鐐カ闂佽鍑界紞鍡樼濠靛鍊垫い鎺戝閳锋垹鎲搁悧鍫濈瑨濞存粈鍗抽弻娑樜熼崹顔绘睏濠电偛妫庨崹浠嬪箖濞嗘挻鍊绘俊顖濄€€閸嬫捇鎮介崨濠勫弳濠电娀娼уΛ娑㈠礄閸︻厾纾奸柕濠忛檮鐏忥箓鏌＄仦鍓с€掗柍褜鍓ㄧ紞鍡涘磻閸涱厾鏆︾€光偓閳ь剟鍩€椤掑喚娼愭繛鍙夌墵婵″墎绮欏▎鎯ф闂佸湱铏庨崰妤呭磻閸曨垱鐓曟繝闈涙椤忊晝绱掗悩铏仢婵﹤顭峰畷鎺戔枎閹搭厽袦缂傚倸鍊哥粔鎾晝椤忓嫮鏆﹂柟瀵稿仧缁♀偓闂佹悶鍎滈崪浣剐ゅ┑鐘垫暩閸嬬偤宕归鐐插瀭闁革富鍘炬稉宥嗙箾瀹割喕绨奸柣鎾跺枑娣囧﹪顢涘顒佸€梺鍝勬閺呮繈鎯€椤忓牆绠氱憸瀣磻閵忋倖鐓涢悘鐐垫櫕鍟稿銇卞倻绐旈柡灞剧洴楠炴鎹勯悜妯间邯闁诲氦顫夊ú妯侯渻娴犲鏄ラ柍褜鍓氶妵鍕箳瀹ュ顎栨繛瀛樼矋缁捇寮婚悢鍏煎€绘俊顖濇娴犳挳姊洪柅鐐茶嫰婢ц尙鈧娲栭悘姘辩博閻旂厧鍗抽柕蹇娾偓宕囨濠电姰鍨奸～澶屾崲閸屾粎绀婂┑鐘叉搐閺嬩線鏌熼悧鍫熺凡缂佲偓鐎ｎ偁浜滈柟鎹愭硾鍟搁梺鍛婏供閸ㄨ泛顫忕紒妯诲闁告稑锕ら弳鍫㈢磽娴ｇ瓔鍤欓柛鐕佸亰閳ユ棃宕橀埡鍐炬祫闁诲函缍嗘禍锝夊箺閺囩偐鏀介柣鎰綑閻忕喖鏌涢妸顭戞綈闁稿寒鍋婂缁樻媴閻熼偊鍤嬪┑鐐村絻缁夌懓鐣烽幋锕€绠绘繛锝庡厸缁ㄥ姊洪崫鍕窛闁哥姵鎹囬幆灞剧節閸ャ劌娈?"

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
        return f"{step}闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁炬儳缍婇弻鐔兼⒒鐎靛壊妲紒鐐劤缂嶅﹪寮婚敐澶婄闁挎繂鎲涢幘缁樼厱濠电姴鍊归崑銉╂煛鐏炶濮傜€殿噮鍣ｅ畷濂告偄閸涘鍞堕梻鍌欒兌椤牓顢栭崱娑樼闁告挆鍐ㄧ亰濡炪倖鎸鹃崑鎰ｉ崼鐔剁箚妞ゆ牗绻嶉崵娆愮箾閸涘洤娲﹂埛鎴炵箾閼奸鍤欐鐐搭殜閺岋綁鎮㈤崣澶嬬彋閻庢鍠栭…鐑藉箖閵忋倕宸濆┑鐘插鑲栨繝寰锋澘鈧呭緤娴犲鐤い鏍剱閺佷胶鈧箍鍎遍ˇ浼村煕閹达附鐓欓柤娴嬫櫅娴犳粓鏌嶈閸撴岸鎮ч悩鑼殾婵犻潧顑呴崘鈧銈嗘尵閸婏綁鏁冮崒娑氬幈闂佸搫娲㈤崝宀勬倶閻樼粯鐓曢柟鑸妼娴滄儳鈹戦敍鍕杭闁稿﹥鐗犲畷婵嬫晝閳ь剟鈥﹂崸妤€鐒垫い鎺戝€荤壕鍏笺亜閺冨洤浜归柛鈺嬬稻閹便劍绻濋崨顕呬哗缂備緡鍠楅悷鈺呭箠濡ゅ拋鏁嶉柨婵嗘閺呇囨⒒閸屾瑧顦﹂柟璇х節瀵濡歌閻捇鏌涢锝嗙缂佺姵鐓￠弻鏇＄疀閺囩倫娑欎繆閹绘帞澧﹂柡灞炬礉缁犳盯寮撮悙鎰╁劜閵囧嫰骞橀搹顐ｅ創闂佸疇顫夐崹鍧楀箖濞嗘挸鐭楀鑸瞪戦ˉ锝囩磽閸屾瑨鍏岀紒顕呭灣閺侇喖螖閸愵亞鐒块梺鍦劋椤ㄥ棝宕愰柨瀣ㄤ簻闁圭儤鍨甸埀顒€顭烽幆渚€宕煎┑鍐╂杸闂佺粯鍔樼亸娆愭櫠閺囥垺鐓熼煫鍥ㄦ⒒缁犵偤鏌熼鏂よ€块柟顔哄灲瀹曟鎳栭埡浣哥疄濠电姴鐥夐弶搴撳亾閹惧墎鐭嗗〒姘ｅ亾闁糕斂鍨藉鎾偐椤愵澀澹曞┑鐐茬墕閻忔繈寮稿☉娆嶄簻妞ゆ挾濮撮崢瀵糕偓娈垮櫘閸嬪﹤鐣峰鈧、娆撴嚃閳轰礁袝濠碉紕鍋戦崐鏍暜閹烘鐤柣妤€鐗忛々鏌ユ煢濡警妲撮柡鈧禒瀣厽闁归偊鍓涢幗鐘绘倶韫囧骸宓嗛柡灞剧洴楠炲鈹戦崼鈶裤劑鎮楃憴鍕妞ゎ偄顦…鍥疀濞戞鈺呮煥閺冨倹娅曠憸鐗堢懇濮?`{anchor}` 闂傚倸鍊搁崐鎼佸磹閹间礁纾归柟闂寸绾惧綊鏌熼梻瀵割槮缁惧墽鎳撻—鍐偓锝庝簼閹癸綁鏌ｉ鐐搭棞闁靛棙甯掗～婵嬫晲閸涱剙顥氬┑掳鍊楁慨鐑藉磻閻愮儤鍋嬮柣妯荤湽閳ь兛绶氬鏉戭潩鏉堚敩銏ゆ⒒娴ｈ鍋犻柛搴㈡そ瀹曟粓鏁冮崒姘€梺鍛婂姦閸犳鎮￠妷鈺傜厸闁搞儺鐓堝▓鏂棵瑰鍫㈢暫婵﹤鎼晥闁搞儜鈧崑鎾澄旈崨顓狅紱闂佽宕橀崺鏍х暦閸欏绡€闂傚牊绋掑婵堢磼閳锯偓閸嬫捇姊绘担渚劸闁哄牜鍓涢崚鎺戠暆閸旇偐鍏橀崺鈧い鎺戝閳锋帒霉閿濆嫯顒熼柣鎺斿亾閵囧嫰骞嬮悙鑼患闂佺懓绠嶉崹褰掑煘閹寸姭鍋撻敐搴濇捣闁硅姤娲熷娲传閸曨剙鍋嶉梺鎼炲妼缂嶅﹪寮荤€ｎ喖鐐婇柕濞у懐妲囬梻鍌氬€搁悧濠勭矙閹烘绠归柟閭﹀枤绾惧ジ鏌熼柇锕€骞樻繛鎻掔摠閹便劍绻濋崘鈹夸虎閻庤娲忛崝宥囨崲濠靛洦鍎熼柕蹇嬪灪濞堥箖姊虹拠鏌ヮ€楅柛妯荤矒瀹曟垿骞樼紒妯煎幍闂傚倸鍊搁顓⑺囬敂鍓х＜闁绘ê纾晶顒€菐閸パ嶈含濠碘€崇埣瀹曟帒顫濋銏╂闂傚倸鍊风粈渚€鎮块崶顬盯宕熼鈧崶顒夋晬闁绘劘灏欓崢娲倵楠炲灝鍔氭い锔跨矙瀵偊宕堕埡鍌氭瀾閻庡厜鍋撻柍褜鍓熼幊鐐烘焼瀹ュ棗娈熼梺闈涳紡閸滀礁鏅?"
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
                "我会先理解你的目标、项目和阻塞点，记住这些上下文，再决定先带你改代码、讲原理，还是先整理训练线程。",
                "请告诉我现在最接近哪条线：实现一个想法、适配一个项目，还是先整理训练线程。",
                "请告诉我现在最接近哪条线：实现一个想法、适配现有项目，还是先整理训练线程。",
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
        "对比",
        "区别",
        "相比",
    )
    return any(marker.casefold() in lowered for marker in markers)


def _fresh_lane_marker_map(*, chinese: bool) -> dict[str, tuple[str, ...]]:
    lane_markers: dict[str, tuple[str, ...]] = {
        "remote_workspace": (
            "remote lane",
            "remote workspace",
            "remote workflow",
            "ssh",
            "tunnels",
            "devcontainer",
            "dev container",
            "container",
            "wsl",
            "credential mode",
        ),
        "debug_loop": (
            "debug loop",
            "breakpoint",
            "launch.json",
            "call stack",
            "stack frame",
            "watch value",
        ),
        "function_guidance": (
            "function-guidance lane",
            "function contract",
            "live call site",
            "call site",
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
        lane_markers["remote_workspace"] += (
            "\u8fdc\u7a0b",
            "\u8fdc\u7a0b\u5de5\u4f5c\u533a",
            "\u8fdc\u7a0b\u8fb9\u754c",
            "\u8fdc\u7a0b ssh",
            "\u5bb9\u5668",
            "\u5f00\u53d1\u5bb9\u5668",
            "\u96a7\u9053",
            "\u51ed\u636e\u6a21\u5f0f",
        )
        lane_markers["debug_loop"] += (
            "\u8c03\u8bd5",
            "\u8c03\u8bd5\u95ed\u73af",
            "\u65ad\u70b9",
            "\u8c03\u7528\u6808",
            "\u5355\u6b65",
            "\u53d8\u91cf\u503c",
        )
        lane_markers["function_guidance"] += (
            "\u51fd\u6570",
            "\u51fd\u6570\u5951\u7ea6",
            "\u8c03\u7528\u70b9",
            "\u8c03\u7528\u4f4d\u7f6e",
            "\u7b7e\u540d\u63d0\u793a",
            "\u67e5\u770b\u5b9a\u4e49",
        )
        lane_markers["project_adaptation"] += (
            "\u6539\u9020",
            "\u8fc1\u79fb",
            "\u9002\u914d",
        )
    return lane_markers


def _reply_mentions_other_guided_lane(reply: str, *, scenario: str, chinese: bool) -> bool:
    if not reply.strip() or scenario not in _GUIDED_DOMAIN_SCENARIOS:
        return False
    lowered = reply.casefold()
    lane_markers = _fresh_lane_marker_map(chinese=chinese)
    other_lane_markers = [
        marker
        for lane, markers in lane_markers.items()
        if lane != scenario
        for marker in markers
    ]
    return any(marker.casefold() in lowered for marker in other_lane_markers)


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
            "remote workflow",
            "ssh",
            "tunnels",
            "devcontainer",
            "dev container",
            "container",
            "wsl",
            "credential mode",
        ),
        "debug_loop": (
            "debug loop",
            "breakpoint",
            "launch.json",
            "call stack",
            "stack frame",
            "watch value",
        ),
        "function_guidance": (
            "function-guidance lane",
            "function contract",
            "live call site",
            "call site",
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
        lane_markers["remote_workspace"] += (
            "远程",
            "远程工作区",
            "远程边界",
            "远程 ssh",
            "容器",
            "开发容器",
            "隧道",
            "凭据模式",
        )
        lane_markers["debug_loop"] += (
            "调试",
            "断点",
            "调用栈",
            "单步",
            "变量值",
        )
        lane_markers["function_guidance"] += (
            "函数",
            "函数契约",
            "调用点",
            "调用位置",
            "签名提示",
            "查看定义",
        )
        lane_markers["project_adaptation"] += ("改造", "迁移", "适配")

    lane_markers = _fresh_lane_marker_map(chinese=chinese)

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
        "沿着上一条",
        "上一条",
        "前一条",
        "刚才那条",
    )
    other_lane_markers = [
        marker
        for lane, markers in lane_markers.items()
        if lane != scenario
        for marker in markers
    ]
    if not other_lane_markers:
        return reply

    paragraphs = [part.strip() for part in reply.split("\n\n") if part.strip()]
    filtered: list[str] = []
    removed = False
    for part in paragraphs:
        lowered = part.casefold()
        mentions_other_lane = any(marker.casefold() in lowered for marker in other_lane_markers)
        has_bridge_cue = any(marker.casefold() in lowered for marker in bridge_markers)
        if mentions_other_lane and has_bridge_cue:
            removed = True
            continue
        filtered.append(part)

    if removed and filtered:
        reply = "\n\n".join(filtered).strip()
    elif removed:
        return reply

    sentence_filtered: list[str] = []
    sentence_removed = False
    for part in filtered:
        if "```" in part:
            sentence_filtered.append(part)
            continue
        kept_sentences: list[str] = []
        sentences = re.split(r"(?<=[.!?。！？])(?:\s+|(?=[^\s]))", part)
        for sentence in sentences:
            normalized = sentence.strip()
            if not normalized:
                continue
            lowered = normalized.casefold()
            mentions_other_lane = any(marker.casefold() in lowered for marker in other_lane_markers)
            if mentions_other_lane:
                sentence_removed = True
                continue
            kept_sentences.append(normalized)
        if kept_sentences:
            joiner = "" if chinese else " "
            sentence_filtered.append(joiner.join(kept_sentences).strip())

    if sentence_removed and sentence_filtered:
        return "\n\n".join(sentence_filtered).strip()
    return reply


def _sanitize_agentic_continuity_text(
    value: str,
    *,
    scenario: str,
    learner_message: str,
    chinese: bool,
    history_mode: str,
    field_kind: str = "summary",
    response_language: str | None = None,
    coach_context: dict[str, Any] | None = None,
) -> str:
    if field_kind == "resume_thread":
        text = _visible_model_text(value).strip()
    else:
        text = _strip_internal_coach_meta(value).strip()
    if not text:
        return text
    if history_mode == "fresh_lane":
        text = _strip_fresh_lane_cross_lane_carryover(
            text,
            scenario=scenario,
            learner_message=learner_message,
            chinese=chinese,
        )
    resolved_scenario = _resolve_first_turn_guided_lane(
        scenario=scenario,
        learner_message=learner_message,
        reply=text,
    )
    active_view = (
        str(
            coach_context.get("active_view")
            or coach_context.get("activeView")
            or ""
        ).strip().lower()
        if isinstance(coach_context, dict)
        else ""
    )
    active_view_override = (
        _build_active_view_recovery_override(
            active_view=active_view,
            response_language=response_language,
            reason="reanchor",
        )
        if active_view in {"plan", "resources", "training", "settings"}
        else None
    )
    if isinstance(active_view_override, dict):
        if field_kind == "summary" and _structured_view_summary_needs_repair(
            text,
            active_view=active_view,
            chinese=chinese,
        ):
            text = str(active_view_override.get("summary") or "").strip() or text
        elif field_kind == "next_step" and _structured_view_next_step_needs_repair(
            text,
            active_view=active_view,
            chinese=chinese,
        ):
            text = str(active_view_override.get("next_step") or "").strip() or text
    if field_kind == "summary" and resolved_scenario in _GUIDED_DOMAIN_SCENARIOS:
        repaired_summary = _first_turn_lane_continuity_note(
            resolved_scenario,
            chinese=chinese,
            coach_context=coach_context,
        )
        if repaired_summary and _guided_lane_summary_needs_repair(
            text,
            scenario=resolved_scenario,
            chinese=chinese,
        ):
            text = repaired_summary
    if field_kind == "next_step" and resolved_scenario in _GUIDED_DOMAIN_SCENARIOS:
        repaired_next_step = _first_turn_lane_next_step(
            resolved_scenario,
            chinese=chinese,
            coach_context=coach_context,
        )
        if repaired_next_step and _guided_lane_next_step_needs_repair(
            text,
            scenario=resolved_scenario,
            chinese=chinese,
        ):
            text = repaired_next_step
    if _looks_like_generic_guided_review_fallback(text):
        if resolved_scenario in _GUIDED_DOMAIN_SCENARIOS:
            repaired_summary = _first_turn_lane_continuity_note(
                resolved_scenario,
                chinese=chinese,
                coach_context=coach_context,
            )
            repaired_next_step = _first_turn_lane_next_step(
                resolved_scenario,
                chinese=chinese,
                coach_context=coach_context,
            )
            if field_kind == "next_step" and repaired_next_step:
                text = repaired_next_step
            elif field_kind == "resume_thread" and (repaired_summary or repaired_next_step):
                text = _agentic_resume_thread_text(
                    repaired_summary,
                    repaired_next_step,
                    response_language=response_language or ("zh-CN" if chinese else "en-US"),
                )
            elif repaired_summary:
                text = repaired_summary
    return text


def _normalize_visible_resume_thread_text(text: str, *, chinese: bool) -> str:
    normalized = _strip_internal_coach_meta(text).strip()
    if not normalized:
        return ""
    if chinese:
        prefixes = (
            "回到同一条教练线程：",
            "沿着当前主线继续：",
            "继续当前主线。",
            "沿着同一条线继续。",
        )
        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                break
        normalized = re.sub(r"(下一步[:：]\s*){2,}", "下一步：", normalized)
        return normalized.strip()
    english_prefixes = (
        "Resume the live thread around ",
        "Resume the live thread. ",
        "Stay on that same thread: ",
    )
    lowered = normalized.casefold()
    for prefix in english_prefixes:
        if lowered.startswith(prefix.casefold()):
            normalized = normalized[len(prefix) :].strip()
            lowered = normalized.casefold()
            break
    normalized = re.sub(
        r"(?i)(next(?: step)?:\s*)(next(?: step)?:\s*)+",
        lambda match: match.group(1),
        normalized,
    )
    return normalized.strip()


def _looks_like_generic_guided_review_fallback(text: str) -> bool:
    normalized = " ".join(text.split()).strip().casefold()
    if not normalized:
        return False
    generic_fallbacks = (
        "ignore secondary issues and only name the first fix plus one verification.",
        "ignore secondary issues and only describe the first fix plus one verification.",
    )
    return any(fragment in normalized for fragment in generic_fallbacks)

def _reply_has_guided_lane_signal(reply: str, scenario: str, chinese: bool) -> bool:
    if not reply.strip():
        return False

    lowered = reply.casefold()
    if chinese:
        if scenario == "remote_workspace" and (
            "工作区边界" in reply
            or "Remote SSH" in reply
            or "Trainer 只该在" in reply
            or ("VS Code" in reply and "pwd" in reply)
        ):
            return True
        if scenario == "function_guidance" and (
            ("当前文件" in reply and "contract" in lowered)
            or ("参数 contract" in reply and "return contract" in reply)
            or ("hover" in lowered and "signature help" in lowered and "definition" in lowered)
        ):
            return True
        if scenario == "debug_loop" and (
            ("debug loop" in lowered and "breakpoint" in lowered)
            or ("断点" in reply and "state change" in lowered)
        ):
            return True
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
            "工作区边界",
            "credential mode",
            "API key",
            "文件实际在哪台机器",
        ),
        "debug_loop": (
            "debug loop",
            "断点",
            "state change",
            "调用栈",
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
            "必须稳定",
            "必须改变",
            "适配",
            "边界",
        ),
    }
    markers = english_markers.get(scenario, ())
    if chinese:
        markers = markers + chinese_markers.get(scenario, ())
    return any(marker.casefold() in lowered for marker in markers)


def _guided_lane_summary_needs_repair(text: str, *, scenario: str, chinese: bool) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    lowered = normalized.casefold()
    if lowered.startswith("next step:") or lowered.startswith("next:"):
        return True
    if normalized.startswith(("下一步：", "下一步:")):
        return True
    ascii_tokens = re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", normalized)
    if ascii_tokens and len(ascii_tokens) <= 5:
        return True
    if not _reply_has_guided_lane_signal(normalized, scenario, chinese):
        return True
    if ascii_tokens and len(ascii_tokens) <= 8 and not any(char in normalized for char in ".!?。！？"):
        return True
    return len(normalized) <= (8 if chinese else 14)


def _guided_lane_next_step_needs_repair(text: str, *, scenario: str, chinese: bool) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    normalized_search = _normalize_search_text(normalized)
    if scenario == "function_guidance":
        if "functionnameandonecallsiteyoucanopenrightnow" in normalized_search:
            return True
        if "给我函数名和一个你现在就能打开的callsite" in normalized_search:
            return True
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if chinese and not any("\u4e00" <= char <= "\u9fff" for char in normalized):
        return True
    if len(normalized) > 110:
        return True
    if normalized.count("。") + normalized.count(". ") + normalized.count("! ") + normalized.count("? ") >= 2:
        return True
    return False


def _structured_view_lane_markers(*, active_view: str, chinese: bool) -> tuple[str, ...]:
    english_markers: dict[str, tuple[str, ...]] = {
        "plan": (
            "planlane",
            "formalplan",
            "currentstage",
            "whynow",
            "verifymethod",
            "evidence",
            "blocker",
        ),
        "resources": (
            "resourceslane",
            "resourcelane",
            "resource",
            "sandbox",
            "library",
            "folder",
            "file",
            "sources",
            "knowledge",
            "cards",
            "download",
            "organize",
        ),
        "training": (
            "traininglane",
            "learn",
            "try",
            "verify",
            "reflect",
            "return",
            "currentcard",
            "card",
            "answer",
            "deliverable",
            "whynow",
        ),
        "settings": (
            "settingslane",
            "settings",
            "provider",
            "model",
            "protocol",
            "runtime",
            "apikey",
            "connection",
        ),
    }
    chinese_markers: dict[str, tuple[str, ...]] = {
        "plan": ("plan视图", "正式计划", "当前阶段", "whynow", "verifymethod", "证据", "阻塞"),
        "resources": ("resources视图", "资料库", "资源", "沙箱", "目录", "文件", "sources", "knowledge", "cards"),
        "training": ("training视图", "训练", "学习", "单卡", "作答", "验证", "复盘", "回流", "whynow"),
        "settings": ("settings视图", "设置", "provider", "model", "protocol", "runtime", "apikey"),
    }
    markers = english_markers.get(active_view, ())
    if chinese:
        markers = markers + chinese_markers.get(active_view, ())
    return markers


def _structured_view_has_lane_signal(text: str, *, active_view: str, chinese: bool) -> bool:
    normalized = _normalize_search_text(text)
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in _structured_view_lane_markers(active_view=active_view, chinese=chinese)
    )


def _structured_view_summary_needs_repair(text: str, *, active_view: str, chinese: bool) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    lowered = normalized.casefold()
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if lowered.startswith("next step:") or lowered.startswith("next:"):
        return True
    if normalized.startswith(("下一步：", "下一步:")):
        return True
    if not _structured_view_has_lane_signal(normalized, active_view=active_view, chinese=chinese):
        return True
    return len(normalized) <= (10 if chinese else 18)


def _structured_view_next_step_needs_repair(text: str, *, active_view: str, chinese: bool) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if not _structured_view_has_lane_signal(normalized, active_view=active_view, chinese=chinese):
        return True
    return len(normalized) <= (10 if chinese else 18)


def _structured_view_visible_reply_needs_repair(text: str, *, active_view: str, chinese: bool) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    if active_view == "training":
        return False
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if _structured_view_has_lane_signal(normalized, active_view=active_view, chinese=chinese):
        return False
    normalized_search = _normalize_search_text(normalized)
    stale_markers: dict[str, tuple[str, ...]] = {
        "plan": (
            "codemechanism",
            "patch",
            "branch",
            "breakage",
            "callsite",
            "signaturehelp",
            "hover",
            "debugloop",
        ),
        "resources": (
            "codemechanism",
            "patch",
            "branch",
            "breakage",
            "debugloop",
            "signaturehelp",
            "formalplan",
        ),
        "settings": (
            "patch",
            "branch",
            "breakage",
            "callsite",
            "debugloop",
            "formalplan",
        ),
    }
    if any(marker in normalized_search for marker in stale_markers.get(active_view, ())):
        return True
    return len(normalized) <= (36 if chinese else 96)


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
            "先别急着直接上方案。第一轮我更想先把你的目标、项目语境和你更适合的带法对齐起来。\n\n"
            "你可以直接告诉我你现在手上的项目、想学到哪一步、卡在哪里，我会把这些判断记住，后面继续沿着同一条线带你，不会每一轮都重开。\n\n"
            "你现在更需要我带你做哪一类：实现一个 idea、改造现有项目，还是先把训练主线和节奏定下来？"
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
            "连接教练服务时遇到了一点问题，所以这一轮我先用本地教练逻辑把你接住。"
            f" 这次的错误是：{detail}。"
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
            "Trainer 现在还不能正式开始，因为还没有可用的 API key。"
            " 请先去 Settings 保存 provider、model 和 API key，然后我就能继续带你。"
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
    coach_context: dict[str, Any] | None = None,
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
                "先把工作区边界说清楚，remote 才会变简单。继续留在 VS Code remote 这条线上："
                "先确认当前是 SSH、tunnels、dev container、WSL 还是 local，再确认文件实际在哪台机器上，"
                "以及 API key 应该留在 local 还是 remote。请用 2 行回复：第一行给一个真实的工作区标签或路径，"
                "第二行给一个安全 credential mode 的判断。"
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
                "先把这一轮收束成一个可信的 VS Code debug loop。先复现一次，在第一个有意义的 state change 停下，"
                "再检查一个 value、branch 或 stack frame，不要先把叙述铺开。请用 2 行回复：第一行写你准备停在哪里，"
                "第二行写你准备先检查哪一个点。"
            ),
            response_language,
        )
    if domain == "function_guidance":
        starter_note, starter_next_step = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=_prefers_chinese(response_language),
        )
        if starter_note or starter_next_step:
            return "\n\n".join(part for part in (starter_note, starter_next_step) if part.strip())
        return _localized_text(
            (
                "Keep this in the function-guidance lane. Start from one live call site, then use hover, "
                "signature help, and definition in that order until the contract stops moving. Return in 2 short "
                "lines: the function name, and the call site or evidence that proves what the function expects."
            ),
            (
                "先把这一轮留在 function guidance 这条线上。先从一个 live call site 开始，再按顺序用 hover、"
                "signature help、definition 把 contract 读稳。请用 3 行回复：第一行写函数名，第二行写你看的 "
                "call site，第三行写能证明它期望什么的 contract 证据。"
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
                "先把这一轮留在现有项目 adaptation 这条线上。先分清哪些必须保持不变、哪些必须改变，"
                "再先落一个窄范围 adaptation，不要一开始就铺大。请用 3 行回复：第一行写必须保持不变的行为，"
                "第二行写必须改变的目标，第三行写你想先适配的第一条边界。"
            ),
            response_language,
        )
    return ""


def _clean_guided_domain_empty_reply_override(
    domain: str | None,
    *,
    response_language: str | None,
    coach_context: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    if domain == "remote_workspace":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the VS Code remote lane.",
                "provider 没有返回可见内容，所以我先把这一轮继续留在 VS Code remote 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Return one real workspace label or path and one sentence about the safe credential mode.",
                "请返回一个真实的工作区标签或路径，再补一句安全 credential mode 的判断。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Keep the lesson grounded in the real workspace boundary before widening the remote story.",
                "先把真实工作区边界说稳，再展开 remote 细节。",
                response_language,
            ),
        }
    if domain == "debug_loop":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the VS Code debug lane.",
                "provider 没有返回可见内容，所以我先把这一轮收束在 VS Code debug 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Tell me where you will pause first and which single value, branch, or stack frame you expect to inspect there.",
                "请告诉我你准备先停在哪里，以及你准备先检查哪一个 value、branch 或 stack frame。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Pause at one meaningful state change before widening the debug story.",
                "先在一个有意义的 state change 停下，再展开 debug 叙述。",
                response_language,
            ),
        }
    if domain == "function_guidance":
        starter_note, starter_next_step = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=_prefers_chinese(response_language),
        )
        if starter_note or starter_next_step:
            return {
                "summary": starter_note or "",
                "next_step": starter_next_step or "",
                "teaching_note": starter_note or "",
            }
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the function-guidance lane.",
                "provider 没有返回可见内容，所以我先把这一轮留在 function guidance 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Return the function name and one call site that proves what the function expects.",
                "请返回函数名、一个 call site，以及能证明它期望什么的 contract 证据。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Keep the contract anchored to one live call site before widening the explanation.",
                "先把 contract 锚定在一个 live call site 上，再展开解释。",
                response_language,
            ),
        }
    if domain == "project_adaptation":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the existing-project adaptation lane.",
                "provider 没有返回可见内容，所以我先把这一轮留在现有项目 adaptation 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Tell me what must stay stable, what must change, and the first boundary you want to adapt.",
                "请告诉我什么必须保持不变、什么必须改变，以及你想先适配的第一条边界。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Separate stable behavior from change scope before widening the adaptation plan.",
                "先分清稳定面和变更面，再扩大 adaptation 计划。",
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
        if reason == "reanchor":
        summary = _localized_text(
            f"I kept this turn inside {spec['lane_en']}.",
            f"这一轮我继续留在{spec['lane_zh']}里。",
            response_language,
        )
    else:
        summary = _localized_text(
            f"{summary_prefix[0]}, so I kept this turn inside {spec['lane_en']}.",
            f"{summary_prefix[1]}锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦ㄤ簡{spec['lane_zh']}銆?",
            response_language,
        )
    next_step = _localized_text(spec["next_en"], spec["next_zh"], response_language)
    teaching_note = _localized_text(spec["note_en"], spec["note_zh"], response_language)
    if reason == "reanchor":
        reply = _localized_text(
            f"I will keep this turn inside one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"这一轮我先用一个更小的{spec['unit_zh']}把它接住。\n\n下一步：{next_step}",
            response_language,
        )
    else:
        reply = _localized_text(
            f"{reply_prefix[0]}, so I will keep the work alive with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"{reply_prefix[1]}锛屾墍浠ユ垜鍏堢敤涓€涓洿灏忕殑{spec['unit_zh']}鎶婅繖涓€杞帴浣忋€俓n\n涓嬩竴姝ワ細{next_step}",
            response_language,
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


_GENERAL_TIMEOUT_CODE_MARKERS = (
    "vs code",
    "vscode",
    "debug",
    "remote",
    "function",
    "call site",
    "stack trace",
    "traceback",
    "workspace",
    "repo",
    "repository",
    "api",
    "json",
    "typescript",
    "javascript",
    "python",
    "java",
    "rust",
    "golang",
    "sql",
    "git",
    "patch",
    "refactor",
    "bug",
    "launch.json",
    ".py",
    ".ts",
    ".js",
    ".tsx",
    ".jsx",
)


def _timeout_focus_seed(
    message: str,
    *,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> str:
    chinese = response_language == "zh-CN"
    candidates: list[object] = []
    if isinstance(coach_context, dict):
        scenario = str(coach_context.get("scenario") or "").strip().lower()
        history_mode = str(coach_context.get("history_mode") or "").strip().lower()
        prefer_message_first = history_mode == "fresh_lane" or scenario in {"", "general"}
        if prefer_message_first:
            candidates.append(message)
        candidates.extend(
            [
                coach_context.get("current_focus"),
                coach_context.get("currentFocus"),
                coach_context.get("thread_summary"),
                coach_context.get("threadSummary"),
                coach_context.get("summary"),
            ]
        )
        if not prefer_message_first:
            candidates.append(message)
    else:
        candidates.append(message)
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        cleaned = " ".join(candidate.strip().split())
        if not cleaned:
            continue
        return _trim_sentence(cleaned, 28 if chinese else 96)
    return ""


def _looks_code_or_tooling_focus(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    return classify_learning_subject(lowered).family == "code"


def _general_recovery_focus_and_subject(
    message: str,
    *,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
):
    focus = _timeout_focus_seed(
        message,
        coach_context=coach_context,
        response_language=response_language,
    )
    if not focus:
        return None, None
    subject = classify_learning_subject(
        focus,
        message,
    )
    return focus, subject


def _build_active_view_recovery_override(
    *,
    active_view: str | None,
    response_language: str | None,
    reason: str,
) -> dict[str, str] | None:
    normalized = str(active_view or "").strip().lower()
    if not normalized:
        return None

    if reason == "timeout":
        summary_prefix = (
            "The provider timed out before it could finish",
            "provider 鍦ㄥ畬鎴愬墠瓒呮椂浜嗭紝",
        )
        reply_prefix = (
            "The provider timed out before finishing",
            "provider 杩樻病璁插畬灏卞瓒呮椂浜嗭紝",
        )
    elif reason == "reanchor":
        summary_prefix = ("", "")
        reply_prefix = ("", "")
    else:
        summary_prefix = (
            "The provider became unstable on this turn",
            "杩欎竴杞殑 provider 閾捐矾涓嶇ǔ瀹氾紝",
        )
        reply_prefix = (
            "The provider became unstable before finishing",
            "provider 鍦ㄨ瀹屽墠鍙樺緱涓嶇ǔ瀹氫簡，",
        )

    view_copy: dict[str, dict[str, str]] = {
        "plan": {
            "lane_en": "the Plan lane",
            "lane_zh": "Plan 视图",
            "unit_en": "plan move",
            "unit_zh": "计划动作",
            "next_en": (
                "Stay inside the formal plan lane and compress the thread into four short items: "
                "current stage, why now, the smallest next step, and the verify method. "
                "Do not silently mutate the formal plan."
            ),
            "next_zh": (
                "先留在正式计划这条主线里，把这一轮压成四项：当前阶段、why now、最小 next step、"
                "verify method。普通聊天不要静默改正式计划。"
            ),
            "note_en": "Keep the plan truthful, compact, and evidence-first while the provider recovers.",
            "note_zh": "先保住计划的真实性、紧凑度和 evidence 导向，再等 provider 恢复。",
        },
        "resources": {
            "lane_en": "the Resources lane",
            "lane_zh": "Resources 视图",
            "unit_en": "resource move",
            "unit_zh": "资料动作",
            "next_en": (
                "Stay inside the resource lane and do one small library pass: locate the most relevant material, "
                "decide which sandbox folder should receive it, then describe how it should be organized into "
                "sources, knowledge, and cards."
            ),
            "next_zh": (
                "先留在资料库这条主线里，做一轮很小的整理：定位最相关资料、决定该放进资料库里的哪个分组目录，"
                "再说明如何整理成 sources、knowledge、cards。"
            ),
            "note_en": "Keep provenance, sandbox boundaries, and the next transformation path visible.",
            "note_zh": "先保住 provenance、沙箱边界和下一步转化路径的清晰度。",
        },
        "training": {
            "lane_en": "the Training lane",
            "lane_zh": "Training 视图",
            "unit_en": "Learn-first training move",
            "unit_zh": "Learn-first 训练动作",
            "next_en": (
                "Stay inside Learn -> Try -> Verify -> Reflect -> Return. "
                "Do not start with an exam. Land one single card that states why now, the problem, "
                "the learner deliverable, the verify method, and what to bring back."
            ),
            "next_zh": (
                "先留在 Learn -> Try -> Verify -> Reflect -> Return 这条训练闭环里，不要一上来考试。"
                "先落一张单卡，至少说清 why now、problem、deliverable、verify、return。"
            ),
            "note_en": "Keep one dominant card and preserve the learn-first loop while the provider recovers.",
            "note_zh": "先保住单卡优先和 learn-first 的训练闭环，再等 provider 恢复。",
        },
        "settings": {
            "lane_en": "the Settings lane",
            "lane_zh": "Settings 视图",
            "unit_en": "settings check",
            "unit_zh": "设置检查",
            "next_en": (
                "Stay inside the configuration lane and verify the current provider, model, protocol, and runtime truth "
                "before resuming the work."
            ),
            "next_zh": "先留在配置这条主线里，核对 provider、model、protocol 和 runtime 真相，再回来续上这一轮。",
            "note_en": "Keep capability truth explicit before resuming teaching work.",
            "note_zh": "先把能力真相说清楚，再恢复教学动作。",
        },
    }
    spec = view_copy.get(normalized)
    if spec is None:
        return None

    if reason == "reanchor":
        summary = _localized_text(
            f"I kept this turn inside {spec['lane_en']}.",
            f"这一轮我继续留在{spec['lane_zh']}里。",
            response_language,
        )
    else:
        summary = _localized_text(
            f"{summary_prefix[0]}, so I kept this turn inside {spec['lane_en']}.",
            f"{summary_prefix[1]}锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦ㄤ簡{spec['lane_zh']}銆?",
            response_language,
        )
    next_step = _localized_text(spec["next_en"], spec["next_zh"], response_language)
    teaching_note = _localized_text(spec["note_en"], spec["note_zh"], response_language)
    if reason == "reanchor":
        reply = _localized_text(
            f"I will keep this turn inside one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"这一轮我先用一个更小的{spec['unit_zh']}把它接住。\n\n下一步：{next_step}",
            response_language,
        )
    else:
        reply = _localized_text(
            f"{reply_prefix[0]}, so I will keep the work alive with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"{reply_prefix[1]}锛屾墍浠ユ垜鍏堢敤涓€涓洿灏忕殑{spec['unit_zh']}鎶婅繖涓€杞帴浣忋€俓n\n涓嬩竴姝ワ細{next_step}",
            response_language,
        )
    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
    }


def _general_theory_recovery_next_step(
    focus: str,
    *,
    subtype: str,
    response_language: str | None,
) -> str:
    if subtype == "derivation":
        return _localized_text(
            f"Write one tiny worked step or mini-derivation about {focus}, name the rule that justifies it, then bring back one check that proves it.",
            f"先围绕 {focus} 写出一个很小的步骤或小推导，说明支撑它的规则，再带回一个证明它成立的检查结果。",
            response_language,
        )
    if subtype == "writing":
        return _localized_text(
            f"Write or revise one sentence about {focus}, name one nearby alternative you rejected, then bring back the tone or meaning difference it proves.",
            f"先围绕 {focus} 写一句或改一句，说明你放弃了哪个相邻表达，再带回它证明了什么语气或含义差别。",
            response_language,
        )
    if subtype == "memorization":
        return _localized_text(
            f"Turn {focus} into one tiny fact cluster, do one closed-book recall, then bring back what you remembered versus missed.",
            f"先把 {focus} 收成一小组事实点，做一次闭卷回忆，再带回你记住了什么、漏了什么。",
            response_language,
        )
    if subtype == "reading":
        return _localized_text(
            f"Make one narrow claim about {focus}, support it with one real excerpt or detail, then bring back the evidence link.",
            f"先围绕 {focus} 提出一个很窄的判断，用一个真实片段或细节支撑它，再带回证据和判断之间的联系。",
            response_language,
        )
    return _localized_text(
        f"Explain {focus} in one short example, boundary, or contrast, then bring back one check that proves the explanation holds.",
        f"先用一个短例子、边界或对比把 {focus} 讲清楚，再带回一个能证明这段解释站得住的检查结果。",
        response_language,
    )


def _build_general_theory_recovery_override(
    message: str,
    *,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
    reason: str,
) -> dict[str, str] | None:
    focus, subject = _general_recovery_focus_and_subject(
        message,
        coach_context=coach_context,
        response_language=response_language,
    )
    if not focus or subject is None or subject.family == "code":
        return None

    next_step = _general_theory_recovery_next_step(
        focus,
        subtype=subject.subtype,
        response_language=response_language,
    )
    if reason == "timeout":
        if reason == "reanchor":
        summary = _localized_text(
            f"I kept this turn inside {spec['lane_en']}.",
            f"这一轮我继续留在{spec['lane_zh']}里。",
            response_language,
        )
    else:
        summary = _localized_text(
            f"{summary_prefix[0]}, so I kept this turn inside {spec['lane_en']}.",
            f"{summary_prefix[1]}锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦ㄤ簡{spec['lane_zh']}銆?",
            response_language,
        )
    next_step = _localized_text(spec["next_en"], spec["next_zh"], response_language)
    teaching_note = _localized_text(spec["note_en"], spec["note_zh"], response_language)
    if reason == "reanchor":
        reply = _localized_text(
            f"I will keep this turn inside one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"这一轮我先用一个更小的{spec['unit_zh']}把它接住。\n\n下一步：{next_step}",
            response_language,
        )
    else:
        reply = _localized_text(
            f"{reply_prefix[0]}, so I will keep the work alive with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"{reply_prefix[1]}锛屾墍浠ユ垜鍏堢敤涓€涓洿灏忕殑{spec['unit_zh']}鎶婅繖涓€杞帴浣忋€俓n\n涓嬩竴姝ワ細{next_step}",
            response_language,
        )
    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
    }


def _build_general_timeout_teaching_override(
    message: str,
    *,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, str] | None:
    return _build_general_theory_recovery_override(
        message,
        coach_context=coach_context,
        response_language=response_language,
        reason="timeout",
    )

    focus = _timeout_focus_seed(
        message,
        coach_context=coach_context,
        response_language=response_language,
    )
    if not focus or _looks_code_or_tooling_focus(focus):
        return None

    next_step = _localized_text(
        f"Write one tiny explanation, worked step, or example about {focus}, then bring back one check that proves it.",
        f"先围绕「{focus}」写出一小步解释、例题或推导，再带回一个最小验证结果。",
        response_language,
    )
    teaching_note = _localized_text(
        "When the provider is slow, keep the lesson alive with one Learn-first move and one tiny verification step.",
        "当 provider 较慢时，先用一个 Learn-first 动作和一个最小验证步骤把教学线程接住。",
        response_language,
    )
    if reason == "reanchor":
        summary = _localized_text(
            f"I kept this turn inside {spec['lane_en']}.",
            f"这一轮我继续留在{spec['lane_zh']}里。",
            response_language,
        )
    else:
        summary = _localized_text(
            f"{summary_prefix[0]}, so I kept this turn inside {spec['lane_en']}.",
            f"{summary_prefix[1]}锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦ㄤ簡{spec['lane_zh']}銆?",
            response_language,
        )
    next_step = _localized_text(spec["next_en"], spec["next_zh"], response_language)
    teaching_note = _localized_text(spec["note_en"], spec["note_zh"], response_language)
    if reason == "reanchor":
        reply = _localized_text(
            f"I will keep this turn inside one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"这一轮我先用一个更小的{spec['unit_zh']}把它接住。\n\n下一步：{next_step}",
            response_language,
        )
    else:
        reply = _localized_text(
            f"{reply_prefix[0]}, so I will keep the work alive with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"{reply_prefix[1]}锛屾墍浠ユ垜鍏堢敤涓€涓洿灏忕殑{spec['unit_zh']}鎶婅繖涓€杞帴浣忋€俓n\n涓嬩竴姝ワ細{next_step}",
            response_language,
        )
    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
    }


def _build_timeout_recovery_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, object]:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    guided_reply = _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    ).strip()
    domain_override = _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    )
    summary_map: dict[str | None, tuple[str, str]] = {
        "remote_workspace": (
            "The provider timed out before it could finish, so I kept this turn in the VS Code remote lane.",
            "provider 在完成前超时了，所以我先把这一轮继续留在 VS Code remote 这条主线上。",
        ),
        "debug_loop": (
            "The provider timed out before it could finish, so I kept this turn inside one trustworthy debug loop.",
            "provider 在完成前超时了，所以我先把这一轮继续收束在一个可信的 debug loop 里。",
        ),
        "function_guidance": (
            "The provider timed out before it could finish, so I kept this turn in the function-guidance lane.",
            "provider 在完成前超时了，所以我先把这一轮继续留在 function guidance 这条主线上。",
        ),
        "project_adaptation": (
            "The provider timed out before it could finish, so I kept this turn in the existing-project adaptation lane.",
            "provider 在完成前超时了，所以我先把这一轮继续留在 existing-project adaptation 这条主线上。",
        ),
    }
    active_view = (
        str(
            coach_context.get("active_view")
            or coach_context.get("activeView")
            or ""
        ).strip().lower()
        if isinstance(coach_context, dict)
        else ""
    )
    active_view_override = (
        _build_active_view_recovery_override(
            active_view=active_view,
            response_language=response_language,
            reason="timeout",
        )
        if active_view in {"plan", "resources", "training", "settings"}
        else None
    )
    default_summary = _localized_text(
        "The provider timed out before it could finish, so I kept this turn anchored to the same coaching lane.",
        "provider 在完成前超时了，所以我先把这一轮继续锚定在同一条教学主线上。",
        response_language,
    )
    if reason == "reanchor":
        summary = _localized_text(
            f"I kept this turn inside {spec['lane_en']}.",
            f"这一轮我继续留在{spec['lane_zh']}里。",
            response_language,
        )
    else:
        summary = _localized_text(
            f"{summary_prefix[0]}, so I kept this turn inside {spec['lane_en']}.",
            f"{summary_prefix[1]}锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦ㄤ簡{spec['lane_zh']}銆?",
            response_language,
        )
    next_step = _localized_text(spec["next_en"], spec["next_zh"], response_language)
    teaching_note = _localized_text(spec["note_en"], spec["note_zh"], response_language)
    if reason == "reanchor":
        reply = _localized_text(
            f"I will keep this turn inside one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"这一轮我先用一个更小的{spec['unit_zh']}把它接住。\n\n下一步：{next_step}",
            response_language,
        )
    else:
        reply = _localized_text(
            f"{reply_prefix[0]}, so I will keep the work alive with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"{reply_prefix[1]}锛屾墍浠ユ垜鍏堢敤涓€涓洿灏忕殑{spec['unit_zh']}鎶婅繖涓€杞帴浣忋€俓n\n涓嬩竴姝ワ細{next_step}",
            response_language,
        )
    return {
        "summary": summary,
        "next_step": next_step,
        "blocker": summary,
        "teaching_note": teaching_note,
        "resume_thread": resume_thread,
        "reply": reply,
        "stop_reason": "timeout",
        "fell_back": True,
    }


def _provider_error_recovery_kind(error_detail: str | None) -> str:
    normalized = str(error_detail or "").strip().lower()
    if not normalized:
        return "unstable"

    overloaded_markers = (
        "high load",
        "rate limit",
        "too many requests",
        "status 429",
        "status 529",
        "overloaded",
    )
    if any(marker in normalized for marker in overloaded_markers):
        return "overloaded"

    auth_markers = (
        "unauthorized",
        "forbidden",
        "permission",
        "access denied",
        "invalid api key",
        "missing api key",
        "status 401",
        "status 403",
    )
    if any(marker in normalized for marker in auth_markers):
        return "auth"

    config_markers = (
        "model not found",
        "unsupported model",
        "protocol",
        "malformed",
        "status 404",
        "status 400",
    )
    if any(marker in normalized for marker in config_markers):
        return "config"

    return "unstable"


def _build_provider_error_recovery_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
    error_detail: str | None = None,
) -> dict[str, object]:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    guided_reply = _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    ).strip()
    domain_override = _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    )
    active_view = (
        str(
            coach_context.get("active_view")
            or coach_context.get("activeView")
            or ""
        ).strip().lower()
        if isinstance(coach_context, dict)
        else ""
    )
    active_view_override = (
        _build_active_view_recovery_override(
            active_view=active_view,
            response_language=response_language,
            reason="provider_error",
        )
        if active_view in {"plan", "resources", "training", "settings"}
        else None
    )
    issue_kind = _provider_error_recovery_kind(error_detail)

    if issue_kind == "auth":
        if reason == "reanchor":
        summary = _localized_text(
            f"I kept this turn inside {spec['lane_en']}.",
            f"这一轮我继续留在{spec['lane_zh']}里。",
            response_language,
        )
    else:
        summary = _localized_text(
            f"{summary_prefix[0]}, so I kept this turn inside {spec['lane_en']}.",
            f"{summary_prefix[1]}锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦ㄤ簡{spec['lane_zh']}銆?",
            response_language,
        )
    next_step = _localized_text(spec["next_en"], spec["next_zh"], response_language)
    teaching_note = _localized_text(spec["note_en"], spec["note_zh"], response_language)
    if reason == "reanchor":
        reply = _localized_text(
            f"I will keep this turn inside one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"这一轮我先用一个更小的{spec['unit_zh']}把它接住。\n\n下一步：{next_step}",
            response_language,
        )
    else:
        reply = _localized_text(
            f"{reply_prefix[0]}, so I will keep the work alive with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"{reply_prefix[1]}锛屾墍浠ユ垜鍏堢敤涓€涓洿灏忕殑{spec['unit_zh']}鎶婅繖涓€杞帴浣忋€俓n\n涓嬩竴姝ワ細{next_step}",
            response_language,
        )
    return {
        "summary": summary,
        "next_step": next_step,
        "blocker": summary,
        "teaching_note": teaching_note,
        "resume_thread": resume_thread,
        "reply": reply,
        "stop_reason": "provider_error",
        "fell_back": True,
    }


def _build_language_corruption_recovery_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, object] | None:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    guided_reply = _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    ).strip()
    domain_override = _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    )
    general_override = _build_general_theory_recovery_override(
        message,
        coach_context=coach_context,
        response_language=response_language,
        reason="language_corruption",
    )
    if (
        not guided_reply
        and not isinstance(domain_override, dict)
        and not isinstance(general_override, dict)
    ):
        return None

    if reason == "reanchor":
        summary = _localized_text(
            f"I kept this turn inside {spec['lane_en']}.",
            f"这一轮我继续留在{spec['lane_zh']}里。",
            response_language,
        )
    else:
        summary = _localized_text(
            f"{summary_prefix[0]}, so I kept this turn inside {spec['lane_en']}.",
            f"{summary_prefix[1]}锛屾墍浠ユ垜鍏堟妸杩欎竴杞暀鍦ㄤ簡{spec['lane_zh']}銆?",
            response_language,
        )
    next_step = _localized_text(spec["next_en"], spec["next_zh"], response_language)
    teaching_note = _localized_text(spec["note_en"], spec["note_zh"], response_language)
    if reason == "reanchor":
        reply = _localized_text(
            f"I will keep this turn inside one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"这一轮我先用一个更小的{spec['unit_zh']}把它接住。\n\n下一步：{next_step}",
            response_language,
        )
    else:
        reply = _localized_text(
            f"{reply_prefix[0]}, so I will keep the work alive with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"{reply_prefix[1]}锛屾墍浠ユ垜鍏堢敤涓€涓洿灏忕殑{spec['unit_zh']}鎶婅繖涓€杞帴浣忋€俓n\n涓嬩竴姝ワ細{next_step}",
            response_language,
        )
    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
        "resume_thread": resume_thread,
        "stop_reason": "language_corruption_recovered",
        "fell_back": True,
        "scenario": resolved_scenario,
    }


def _mode_style_label(mode: str, chinese: bool) -> str:
    if chinese:
        return {
            "guided": "我先带你把",
            "balanced": "我们先把",
            "direct": "先直接把",
        }.get(mode, "我们先把")
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
            f"我们先沿着这条线继续：{visible_focus}。"
            if chinese
            else f"I will keep working along this live thread: {visible_focus}."
        )

    if scenario == "remote_workspace":
        base = "我们先把这一轮留在 VS Code remote 这条线上。" if chinese else (
            "I will keep this turn in the VS Code remote lane."
        )
    elif scenario == "debug_loop":
        base = "我们先把这一轮收束成一个可信的 debug loop。" if chinese else (
            "I will keep this turn inside one trustworthy debug loop."
        )
    elif scenario == "function_guidance":
        base = "我们先把这一轮留在 function guidance 这条线上。" if chinese else (
            "I will keep this turn in the function-guidance lane."
        )
    elif scenario == "project_adaptation":
        base = "我们先沿着现有项目 adaptation 这条线继续。" if chinese else (
            "I will keep this turn in the existing-project adaptation lane."
        )
    elif scenario == "principle":
        base = "我们先把这一轮锚定在当前原理和代码边界上。" if chinese else (
            "I will anchor this turn in the current principle and code boundary first."
        )
    else:
        base = (
            f"我们先回到 `{file_path}` 这一步。"
            if chinese and file_path
            else f"I will re-anchor on `{file_path}` first."
            if file_path
            else "我们先对齐这一步真正要完成的目标。"
            if chinese
            else "I want to re-anchor on the real goal of this step first."
        )

    if goal and scenario not in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        goal_text = _trim_sentence(goal, 42 if chinese else 96)
        if chinese:
            return f"{base} 这一轮先服务这个目标：{goal_text}。"
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
        return visible_summary if visible_summary.endswith(("。", ".", "!", "！", "?", "？")) else (
            f"{visible_summary}。"
            if chinese
            else f"{visible_summary}."
        )

    visible_reason = _surface_context_text(teaching_decision_reason, chinese=chinese)
    if visible_reason:
        return (
            f"这一轮先这样收束，是因为{visible_reason}。"
            if chinese
            else f"I am narrowing this turn this way because {visible_reason}."
        )

    if diagnostics_count > 0:
        return (
            f"当前文件里还有 {diagnostics_count} 条 diagnostics，先不要铺开，先恢复一条最小反馈链。"
            if chinese
            else f"There are still {diagnostics_count} diagnostics in the current file, so I want one minimal feedback loop before we widen anything."
        )

    if weak_spots:
        weak_spot = _trim_sentence(weak_spots[0], 28 if chinese else 72)
        return (
            f"这一轮先盯住最容易反复卡住的点：{weak_spot}。"
            if chinese
            else f"The riskiest recurring weak spot on this turn is: {weak_spot}."
        )

    if teaching_observations:
        observation = _surface_context_text(teaching_observations[0], chinese=chinese)
        if observation:
            return observation if observation.endswith(("。", ".", "!", "！", "?", "？")) else (
                f"{observation}。"
                if chinese
                else f"{observation}."
            )

    if learner_signal == "blocked":
        return (
            "你现在更需要的是先把范围压小，而不是再加更多解释。"
            if chinese
            else "Right now you need a smaller scope more than a larger explanation."
        )

    scenario_map = {
        "remote_workspace": (
            "先把工作区边界说稳，再决定 remote 里的下一步。",
            "The next useful move depends on proving the real workspace boundary first.",
        ),
        "debug_loop": (
            "先把 debug 收束到一个 pause point、一个 value 和一个验证动作上。",
            "The next useful move is to keep debugging inside one pause point, one observed value, and one verification move.",
        ),
        "function_guidance": (
            "先把函数 contract 锚定在一个 live call site 上，再扩解释。",
            "The next useful move is to anchor the function contract to one live call site before the explanation widens.",
        ),
        "project_adaptation": (
            "先分清稳定面和变更面，再动第一条 adaptation 边界。",
            "The next useful move is to separate the stable surface from the change surface before the first adaptation.",
        ),
        "principle": (
            "先把原理压回当前代码边界，再做一个最小验证。",
            "The next useful move is to pin the principle back to the live code boundary and test it once.",
        ),
    }
    zh, en = scenario_map.get(
        scenario,
        (
            "这一轮先落一个最小可验证动作，把线程继续接稳。",
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
                return f"先别把它讲成更大的计划，先做这一步：{visible_hint}"
            if scenario == "principle":
                return f"先把这个原理落成动作：{visible_hint}"
            if learner_signal == "blocked":
                return f"这一轮先只做这一个动作：{visible_hint}"
            if mode == "direct":
                return f"先直接从这一步开始：{visible_hint}"
            return f"下一步先做这个：{visible_hint}"
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
            return f"先别同时做太多，只做这一步：{scenario_step}"
        if mode == "direct":
            return f"先直接从这一步开始：{scenario_step}"
        return f"{mode_prefix}{scenario_step}。"
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
            "判断当前工作区是 SSH、tunnels、dev container、WSL 还是 local，再确认文件实际在哪台机器上"
            if chinese
            else "identify whether the workspace is SSH, tunnels, dev container, WSL, or local, then prove which machine actually owns the files"
        )
    if scenario == "debug_loop":
        return (
            "只复现一次，在第一个有意义的 breakpoint 停下，检查一个 value、branch 或 stack frame"
            if chinese
            else "reproduce once, pause at the first meaningful breakpoint, and inspect one value, branch, or stack frame"
        )
    if scenario == "function_guidance":
        return (
            "先从一个 live call site 读这个函数，再用 hover、signature help、definition 把 contract 读稳"
            if chinese
            else "start from one live call site, then use hover, signature help, and definition until the contract stops moving"
        )
    if scenario == "project_adaptation":
        return (
            "写出必须保持不变的行为、必须改变的目标，以及要先碰的第一条边界"
            if chinese
            else "write down what must stay stable, what must change, and the first boundary you want to adapt"
        )
    if scenario == "principle":
        return (
            f"把当前原理钉在一处 live code boundary 上，再做一个最小验证{file_suffix}"
            if chinese
            else f"pin the current principle to one live code boundary and run one small verification{file_suffix}"
        )
    if scenario in {"review", "task", "next_task"}:
        return (
            f"先恢复一条最小反馈链{file_suffix}"
            if chinese
            else f"restore one minimal feedback loop{file_suffix}"
        )
    if scenario == "plan":
        return (
            "只保留一个最近的里程碑和一个验证点"
            if chinese
            else "keep only the nearest milestone and one verification point"
        )
    if weak_spot:
        return (
            f"先把 {weak_spot} 这一处压稳{file_suffix}"
            if chinese
            else f"stabilize {weak_spot} first{file_suffix}"
        )
    return (
        f"先落一个最小可验证切片{file_suffix}"
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
            f"你前面已经把这条线的一部分走通了：{recent_win}。这一轮继续沿着可验证的节奏走。"
            if chinese
            else f"You already proved part of this lane earlier: {recent_win}. I want to keep the same verifiable rhythm."
        )
    if weak_spots:
        weak_spot = _surface_context_text(weak_spots[0], chinese=chinese) or weak_spots[0]
        return (
            f"我会继续盯住 {weak_spot} 这个易错点，不让它在这一轮重新扩散。"
            if chinese
            else f"I will keep watching the recurring weak spot around {weak_spot} so it does not spread again on this turn."
        )
    if due_reviews:
        reason = _format_due_review_item(due_reviews[0])
        return (
            f"做完这一步后，我们再决定要不要把复习队列里的这条也收回来：{reason}。"
            if chinese
            else f"After this move, we can decide whether to pull this review thread back in: {reason}."
        )
    if review_rhythm and scenario == "plan":
        visible_rhythm = _surface_context_text(review_rhythm, chinese=chinese)
        if visible_rhythm:
            return (
                f"这一步完成后，再按现在的 review rhythm 接着走：{visible_rhythm}。"
                if chinese
                else f"After this move, continue with the current review rhythm: {visible_rhythm}."
            )
    if mode == "direct":
        return (
            "我会把解释压短一点，但会把为什么这一步重要和怎么验证说清楚。"
            if chinese
            else "I will keep the explanation short, but I will still make the reason and verification signal explicit."
        )
    if verbosity_bias == "short":
        return (
            "这一轮先保持短一点，只围绕当前这一条线说清楚。"
            if chinese
            else "I will keep this turn compact and stay on one line of coaching."
        )
    if tone_name:
        return (
            f"这一轮我会保持 {tone_name} 这类语气，但优先保证动作可验证。"
            if chinese
            else f"I will keep the {tone_name} tone, but I still want the move to stay verifiable."
        )
    if coach_defaults:
        return (
            "我会继续沿着你已经设定好的教练偏好来带，不额外打开新的面。"
            if chinese
            else "I will keep following your saved coaching defaults instead of opening a new lane."
        )
    return (
        "这一步的重点不是讲更多，而是把线程继续接稳。"
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
            return "如果你一动手又卡住，就把那一小段原样带回来，我帮你再缩一层。"
        if mode == "direct":
            return "做完别只说“好了”，告诉我你验证到了什么，我再帮你选下一步。"
        if verbosity_bias == "short":
            return "先做这一步，再把结果带回来。"
        return "先做这一步，再把结果带回来，我们再决定是扩展、复盘，还是继续收紧。"
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
        return f"，先从 `{file_path}` 开始"
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
    coach_context: dict[str, Any] | None = None,
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
    guided_note = _first_turn_lane_continuity_note(
        guided_lane,
        chinese=chinese,
        coach_context=coach_context,
    )
    guided_close = _first_turn_lane_next_step(
        guided_lane,
        chinese=chinese,
        coach_context=coach_context,
    )
    if guided_lane == "function_guidance" and isinstance(coach_context, dict):
        starter = coach_context.get("function_guidance_starter")
        if isinstance(starter, dict) and str(starter.get("status") or "").strip() == "ready":
            starter_tokens = [
                _compact_text(starter.get("call_site_path"), 120),
                _compact_text(starter.get("definition_path"), 120),
                _compact_text(starter.get("definition_symbol"), 48),
                _compact_text(starter.get("call_site_symbol"), 48),
            ]
            reply_mentions_starter = any(token and token in reply for token in starter_tokens)
            if reply_mentions_starter:
                if starter_tokens[0] and starter_tokens[1] and starter_tokens[0] in reply and starter_tokens[1] in reply:
                    return first
                guided_note = ""
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
            "我会先理解你的目标、项目语境和当前阻塞点，再把这一轮收束到最合适的教学线里。"
            if chinese
            else "I will first understand your goal, project, and blocker, remember that context for the next turn, then decide whether to guide the code, explain the principle, or shape the training thread first."
        )
    )
    if chinese:
        close = "告诉我现在更接近哪一类：实现一个 idea、改造现有项目，还是先把训练主线和节奏定下来。"
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
            parts.append(f"它在这里重要，是因为{why_it_matters}。")
        if needs_apply:
            prefix = "你现在" if apply_now.startswith("先") else "你现在先"
            parts.append(f"{prefix}{apply_now}。")
        if needs_source:
            parts.append(f"继续沿着 `{source_asset_title}` 这条解释线。")
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
    coach_context: dict[str, Any] | None = None,
) -> str:
    step = next_step_hint.strip()
    if step:
        if chinese:
            for prefix in ("\u4e0b\u4e00\u6b65\uff1a", "\u4e0b\u4e00\u6b65:"):
                if step.startswith(prefix):
                    step = step[len(prefix) :].strip()
                    break
        else:
            lowered_step = step.casefold()
            for prefix in ("next step:", "next:"):
                if lowered_step.startswith(prefix):
                    step = step[len(prefix) :].strip()
                    break
    execution_ready = bool(coach_context.get("execution_ready")) if isinstance(coach_context, dict) else False
    if scenario == "remote_workspace" and execution_ready:
        step = _first_turn_lane_next_step(
            scenario,
            chinese=chinese,
            coach_context=coach_context,
        ).strip() or step
    if scenario == "function_guidance":
        starter_note, starter_next_step = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=chinese,
        )
        current_file_note, current_file_next_step = _function_guidance_current_file_reply_parts(
            coach_context,
            chinese=chinese,
        )
        starter = coach_context.get("function_guidance_starter") if isinstance(coach_context, dict) else None
        starter_tokens = [
            _compact_text(starter.get("call_site_path"), 120) if isinstance(starter, dict) else None,
            _compact_text(starter.get("definition_path"), 120) if isinstance(starter, dict) else None,
            _compact_text(starter.get("definition_symbol"), 48) if isinstance(starter, dict) else None,
            _compact_text(starter.get("call_site_symbol"), 48) if isinstance(starter, dict) else None,
        ]
        if any(token and token in reply for token in starter_tokens):
            return ""
        if current_file_note or current_file_next_step:
            step = current_file_next_step.strip() or step
        elif starter_note or starter_next_step:
            step = starter_next_step.strip() or step
    if step:
        if chinese:
            for prefix in ("\u4e0b\u4e00\u6b65\uff1a", "\u4e0b\u4e00\u6b65:"):
                if step.startswith(prefix):
                    step = step[len(prefix) :].strip()
                    break
        else:
            lowered_step = step.casefold()
            for prefix in ("next step:", "next:"):
                if lowered_step.startswith(prefix):
                    step = step[len(prefix) :].strip()
                    break
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
            return f"先别把它讲成更大的计划，先做这一步：{anchored_step}"
        if scenario == "principle":
            return f"先把这个原理落成动作：{anchored_step}"
        if learner_signal == "blocked":
            return f"这一轮先只做这一个动作：{anchored_step}"
        if mode == "direct":
            return f"先直接从这一步开始：{anchored_step}"
        return f"下一步先做这个：{anchored_step}"

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
            return f"先别扩范围。先把 `{check}` 这一条最小反馈链恢复出来，确认它通过，再决定要不要扩。"
        return "先别扩范围。先恢复一条最小反馈链，确认这一步通过，再决定要不要扩。"

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
        return f"这一步算过的信号是：{success_signal}。"
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
        return f"先沿着之前已经验证过的做法走：{lesson}。"
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
        return f"{step}，先从 `{anchor}` 开始。"
    return f"{step} Start in `{anchor}`."


def _reply_has_reason_signal(reply: str, chinese: bool) -> bool:
    markers = ["because", "this matters", "the reason", "so that", "which helps", "why this matters"]
    if chinese:
        markers.extend(["因为", "这很重要", "原因", "这样就能", "为什么这一步重要", "它在这里重要"])
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
        markers.extend(["下一步", "现在先", "先做", "先跑", "先改", "先补", "先验证", "先检查", "先指出", "先确认", "直接从这一步"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_verification_signal(reply: str, chinese: bool) -> bool:
    markers = ["verify", "check", "run", "test", "confirm", "passes", "feedback loop"]
    if chinese:
        markers.extend(["验证", "检查", "确认", "跑一次", "通过", "反馈链", "验收信号", "可验证"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_scope_tightening_signal(reply: str, chinese: bool) -> bool:
    markers = ["do not widen", "reduce scope", "tighten", "smallest", "minimal", "one branch", "one patch"]
    if chinese:
        markers.extend(["先别扩范围", "不要扩范围", "收紧", "最小反馈链", "最小可验证", "缩小范围"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_recall_signal(reply: str, chinese: bool) -> bool:
    markers = ["previous", "earlier", "already worked", "reuse", "stay on the line", "keep this lane"]
    if chinese:
        markers.extend(["之前", "前面", "已经验证过", "复用", "沿着这条线", "继续这条线"])
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
            "先别急着直接上方案。第一轮我想先把你的目标、项目语境、"
            "以及更适合你的带法对齐起来。\n\n"
            "你可以直接告诉我现在手上的项目、想学到哪一步、卡在哪里。"
            "我会记住这些判断，后面继续沿着同一条线带你，不会每一轮都重开。\n\n"
            "你现在更需要我带你做哪一类：实现一个 idea、改造现有项目，"
            "还是先把训练主线和节奏定下来？"
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
            "连接教练服务时遇到问题，所以这轮我先用本地恢复逻辑接住你。"
            f"这次错误是：{detail}。"
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
            "Trainer 现在还不能正式开始，因为还没有可用的 API key。"
            "请先到 Settings 保存 provider、model 和 API key，然后我就能继续带你。"
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
            "这个 provider 拒绝了这一轮使用的 API key 或 permission。",
        ),
        "model_unsupported": (
            "The provider reached the endpoint, but this model name is not accepted there.",
            "这个 provider 可以连通，但当前 model name 不被这个 endpoint 接受。",
        ),
        "model_not_found": (
            "The provider reached the gateway, but no available channel matched this model.",
            "这个 provider 可以连通，但 gateway 里没有可用 channel 匹配当前 model。",
        ),
        "language_corruption": (
            "The provider returned a visibly corrupted coaching reply on this turn.",
            "这个 provider 可达，但这一轮返回了肉眼可见的乱码回复。",
        ),
        "language_probe_inconclusive": (
            "The provider reached the endpoint, but Trainer could not fully verify zh-CN input integrity yet.",
            "这个 provider 可达，但 Trainer 还不能完整验证这条链路的 zh-CN 输入保真度。",
        ),
        "empty_response": (
            "The provider reached the endpoint, but returned no usable visible reply.",
            "这个 provider 可达，但没有返回可用的可见回复。",
        ),
        "malformed_response": (
            "The endpoint responded, but the payload did not match the configured protocol.",
            "这个 endpoint 有响应，但 payload 不符合当前配置的 protocol。",
        ),
        "rate_limit": (
            "The provider rate-limited this turn before Trainer could continue.",
            "这个 provider 对这一轮请求触发了 rate limit，Trainer 暂时不能继续。",
        ),
        "timeout": (
            "Trainer could not get a response from the provider before the timeout.",
            "Trainer 在 timeout 前没有从 provider 收到响应。",
        ),
        "network": (
            "Trainer could not reach the provider over the network.",
            "Trainer 目前无法通过 network 连到这个 provider。",
        ),
    }
    english, chinese = summary_map.get(
        category,
        (
            "Trainer is blocked on the provider path for this turn.",
            "Trainer 这一轮被 provider path 卡住了。",
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
            "先检查 API key 或 provider permission，重新测试连接后再重发这一轮。",
        ),
        "model_unsupported": (
            "Switch to a model name that this provider actually supports, retest, and resend this exact turn.",
            "先换成这个 provider 真正支持的 model name，重新测试后再重发这一轮。",
        ),
        "model_not_found": (
            "Pick a channel-backed model at this gateway, retest, and resend this exact turn.",
            "先换成这个 gateway 里真实可用的 model，重新测试后再重发这一轮。",
        ),
        "language_corruption": (
            "Switch provider or gateway first, then resend this same turn after the visible corruption disappears.",
            "先切换 provider 或 gateway，确认乱码消失后再重发这一轮。",
        ),
        "language_probe_inconclusive": (
            "Retest with a zh-CN probe before trusting this provider for Chinese coaching turns.",
            "先用 zh-CN probe 重新测试，再把这个 provider 用于中文 coaching。",
        ),
        "empty_response": (
            "Retest with a visible-text probe or switch to a model that returns visible text.",
            "先用 visible-text probe 重新测试，或切换到会返回可见文本的 model。",
        ),
        "malformed_response": (
            "Check that the endpoint really speaks the configured protocol, then retest and resend this exact turn.",
            "先确认这个 endpoint 真的支持当前配置的 protocol，再测试并重发这一轮。",
        ),
        "rate_limit": (
            "Wait briefly, then retry this same turn once the rate limit clears.",
            "先等一会儿，等 rate limit 过去后再重试这一轮。",
        ),
        "timeout": (
            "Retry once after checking provider latency or gateway load.",
            "先检查 provider 延迟或 gateway 负载，再重试这一轮。",
        ),
        "network": (
            "Check the network path or proxy settings, then resend this exact turn.",
            "先检查 network 路径或 proxy 设置，再重发这一轮。",
        ),
    }
    english, chinese = next_step_map.get(
        category,
        (
            "Repair the provider path, then resend this exact coaching turn.",
            "先修好 provider path，再重发这一轮 coaching。",
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
            "Trainer 当前卡在 provider path，所以这轮 coaching 还不能继续。",
            "",
            summary,
        ]
        if detail_text:
            lines.append(f"详情：{detail_text}")
        lines.append(f"下一步：{next_step}")
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
