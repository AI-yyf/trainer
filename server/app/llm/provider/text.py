"""Text sanitization for provider responses (§五十二).

Handles reasoning-block stripping, mojibake detection, provider control
marker removal, and visible-text normalization.
"""

from __future__ import annotations

import re

from .assessment import _as_mapping

_MOJIBAKE_FALLBACK_MARKERS = (
    "\ufffd", "\ue000", "\ue1ec",
    "锟", "闂", "濠", "閻", "缂", "鈧", "鐢", "鍙", "鏂",
    "瀹", "涓", "浣", "璇", "骞", "搴", "绠", "鎴", "灏",
    "鏄", "杩", "鍏", "鐩", "閸", "鐠", "娑",
)
_LATIN1_MOJIBAKE_PATTERN = re.compile(
    r"(?:[\u00C2\u00C3\u00C4\u00C5\u00C6\u00C7\u00C8\u00C9\u00CF\u00D0"
    r"\u00E2\u00E3\u00E4\u00E5\u00E6\u00E7\u00E8\u00E9\u00EF\u00F0]"
    r"[\u0080-\u00BF]{1,2}){2,}"
)
_THINK_BLOCK_PATTERN = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_THINK_TAG_PATTERN = re.compile(r"</?think\b[^>]*>", re.IGNORECASE | re.DOTALL)
_PROVIDER_CONTROL_MARKER_PATTERN = re.compile(
    r"\]\s*<\]\s*minimax\s*\[>\s*\[", re.IGNORECASE | re.DOTALL,
)
_PSEUDO_TOOL_CALL_BLOCK_PATTERN = re.compile(
    r"<tool_call\b[^>]*>.*?(?:</tool_call\s*>|$)", re.IGNORECASE | re.DOTALL,
)
_PSEUDO_TOOL_CALL_TAG_PATTERN = re.compile(r"</?tool_call\b[^>]*>", re.IGNORECASE | re.DOTALL)
_VISIBLE_MODEL_PUNCTUATION_MAP = str.maketrans({"…": "...", "\u2013": "-", "\u2014": "-"})

_CYRILLIC_CHAR_PATTERN = re.compile(r"[\u0400-\u04FF]")
_LATIN_CHAR_PATTERN = re.compile(r"[A-Za-z]")
_CJK_CHAR_PATTERN = re.compile(r"[\u3400-\u9fff]")


def _contains_cjk(text: str | None) -> bool:
    if not text:
        return False
    return bool(_CJK_CHAR_PATTERN.search(text))


def _contains_cyrillic(text: str | None) -> bool:
    if not text:
        return False
    return bool(_CYRILLIC_CHAR_PATTERN.search(text))


def _contains_latin(text: str | None) -> bool:
    if not text:
        return False
    return bool(_LATIN_CHAR_PATTERN.search(text))


def _looks_like_mojibake_text(value: object) -> bool:
    text = str(value or "")
    return any(marker in text for marker in _MOJIBAKE_FALLBACK_MARKERS) or bool(
        _LATIN1_MOJIBAKE_PATTERN.search(text)
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

# ---------------------------------------------------------------------------
# Script and corruption detection (§五十二 extension)
# ---------------------------------------------------------------------------


def _compact_visible_text(value: object | None, limit: int = 220) -> str:
    visible = _visible_model_text(value)
    normalized = " ".join(visible.split()).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 1)].rstrip()}..."


def _normalize_script_token(token: str) -> str:
    return re.sub(r"^[^A-Za-z\u0400-\u04FF]+|[^A-Za-z\u0400-\u04FF]+$", "", token)


_VISIBLE_TOKEN_PATTERN = re.compile(r"\S+")


_THINK_CLOSE_TAG_PATTERN = re.compile(r"</think\b[^>]*>", re.IGNORECASE | re.DOTALL)


_QUESTION_RUN_PATTERN = re.compile(r"\?{4,}")


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


def _has_hidden_reasoning(value: object | None) -> bool:
    if isinstance(value, str):
        return bool(value.strip()) and bool(_THINK_TAG_PATTERN.search(value)) and not _visible_model_text(value)
    if isinstance(value, list):
        return any(_has_hidden_reasoning(item) for item in value)

    record = _as_mapping(value) or {}

    for field_name in (
        "reasoning",
        "reasoning_content",
        "reasoningContent",
        "thinking",
        "thinking_content",
        "thinkingContent",
    ):
        field_value = record.get(field_name, getattr(value, field_name, None))
        if isinstance(field_value, str) and field_value.strip():
            return True
        if isinstance(field_value, (dict, list)) and field_value:
            return True

    if str(record.get("type", getattr(value, "type", "")) or "").strip().lower() in {
        "reasoning",
        "thinking",
    }:
        return True
    if record.get("thought", getattr(value, "thought", None)) is True and str(
        record.get("text", getattr(value, "text", "")) or ""
    ).strip():
        return True

    for field_name in ("content", "output", "parts", "text"):
        field_value = record.get(field_name, getattr(value, field_name, None))
        if isinstance(field_value, (dict, list)) and _has_hidden_reasoning(field_value):
            return True
        if isinstance(field_value, str) and _has_hidden_reasoning(field_value):
            return True
    return False


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
    message: str | None = None,
    response_language: str | None = None,
) -> str | None:
    if _prefers_chinese(response_language):
        return None
    if message and _contains_cjk(message):
        # A CJK learner message invites a mirrored CJK reply; that is language
        # alignment with the learner, not a wrong-language corruption signal.
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


def _wrong_language_zh_reply_detail(
    reply: str,
    *,
    response_language: str | None = None,
) -> str | None:
    """Reject prose-only English replies when the learner selected zh-CN.

    Code/API identifiers may remain English, so fenced and inline code are
    removed before deciding whether the remaining visible prose lacks CJK.
    """
    if not _prefers_chinese(response_language):
        return None
    visible = _compact_visible_text(reply, limit=480)
    if not visible or _contains_cjk(visible):
        return None
    prose = re.sub(r"```[\\s\\S]*?```", "", visible).strip()
    prose = re.sub(r"`[^`]*`", "", prose).strip()
    latin_words = re.findall(r"[A-Za-z]{3,}", prose)
    if len(latin_words) < 3:
        return None
    return (
        "The provider returned English-only visible prose while zh-CN is selected. "
        "Trainer cannot trust this text as a clean coaching turn."
    )


def _mixed_script_reply_corruption_detail(
    reply: str,
    *,
    message: str | None = None,
    response_language: str | None = None,
) -> str | None:
    visible = _compact_visible_text(reply, limit=480)
    wrong_language_zh_detail = _wrong_language_zh_reply_detail(
        reply,
        response_language=response_language,
    )
    if wrong_language_zh_detail:
        return wrong_language_zh_detail
    wrong_language_detail = _wrong_language_cjk_reply_detail(
        reply,
        message=message,
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


def _prefers_chinese(response_language: str | None) -> bool:
    return bool(response_language and response_language.lower().startswith("zh"))
