"""Text sanitization for provider responses (§五十二).

Handles reasoning-block stripping, mojibake detection, provider control
marker removal, and visible-text normalization.
"""

from __future__ import annotations

import re

from .assessment import _as_mapping

_HARD_MOJIBAKE_MARKERS = ("\ufffd", "\ue000", "\ue1ec", "\u951f\u65a4\u62f7")
_GBK_MOJIBAKE_MARKERS = (
    "锟", "闂", "濠", "閻", "缂", "鈧", "鐢", "鍙", "鏂",
    "瀹", "涓", "浣", "璇", "骞", "搴", "绠", "鎴", "灏",
    "鏄", "杩", "鍏", "鐩", "閸", "鐠", "娑",
)
_MOJIBAKE_FALLBACK_MARKERS = (*_HARD_MOJIBAKE_MARKERS, *_GBK_MOJIBAKE_MARKERS)
_LATIN1_MOJIBAKE_PATTERN = re.compile(
    r"(?:[\u00C2\u00C3\u00C4\u00C5\u00C6\u00C7\u00C8\u00C9\u00CF\u00D0"
    r"\u00E2\u00E3\u00E4\u00E5\u00E6\u00E7\u00E8\u00E9\u00EF\u00F0]"
    r"[\u0080-\u00BF]{1,2}){2,}"
)
#: ``<think>…</think>`` and MiniMax's spelling ``<mm:think>…</mm:think>`` are the same thing.
_THINK_TAG_NAME = r"(?:mm:)?think"
_THINK_BLOCK_PATTERN = re.compile(
    rf"<{_THINK_TAG_NAME}\b[^>]*>.*?</{_THINK_TAG_NAME}\s*>", re.IGNORECASE | re.DOTALL
)
# A stream cut mid-reasoning leaves the opening tag without its closing tag.
# Dropping only the tag would publish the raw chain-of-thought as coaching
# text, so an unclosed block consumes everything to the end of the reply.
_OPEN_THINK_BLOCK_PATTERN = re.compile(
    rf"<{_THINK_TAG_NAME}\b[^>]*>.*\Z", re.IGNORECASE | re.DOTALL
)
_THINK_TAG_PATTERN = re.compile(rf"</?{_THINK_TAG_NAME}\b[^>]*>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN_TAG_PATTERN = re.compile(rf"<{_THINK_TAG_NAME}\b[^>]*>", re.IGNORECASE | re.DOTALL)
_THINK_CLOSE_TAG_PATTERN = re.compile(rf"</{_THINK_TAG_NAME}\b[^>]*>", re.IGNORECASE | re.DOTALL)
# Provider-internal protocol that must never reach the learner. MiniMax models put
# ``]<]minimax[>[`` in front of special tokens; when they try to call a tool on a request that
# carries none, the attempt arrives as content (seen with a real model on 2026-11-28:
# ``]<]minimax[>[<tool_call><mm:think>Let me read payments.py…</mm:think>]<]minimax[>[…``).
_PROVIDER_CONTROL_MARKER_PATTERN = re.compile(
    r"\]\s*<\]\s*minimax\s*\[>\s*\[", re.IGNORECASE | re.DOTALL,
)
_PSEUDO_TOOL_CALL_BLOCK_PATTERN = re.compile(
    r"<tool_call\b[^>]*>.*?(?:</tool_call\s*>|$)", re.IGNORECASE | re.DOTALL,
)
_PSEUDO_TOOL_CALL_TAG_PATTERN = re.compile(r"</?tool_call\b[^>]*>", re.IGNORECASE | re.DOTALL)
_PSEUDO_TOOL_CALL_OPEN_PATTERN = re.compile(r"<tool_call\b[^>]*>", re.IGNORECASE | re.DOTALL)
_PSEUDO_TOOL_CALL_CLOSE_PATTERN = re.compile(r"</tool_call\s*>", re.IGNORECASE | re.DOTALL)
#: A gateway puts this sentence where a model message has no content of its own — a step that only
#: calls a tool. It is protocol, not text. Left alone it entered the history, and the next turn the
#: model echoed it as the last line of a reply (seen with a real model on 2026-11-28).
PROVIDER_EMPTY_CONTENT_SENTINEL = "[System: Empty message content sanitised to satisfy protocol]"
_PROVIDER_SENTINEL_PATTERN = re.compile(re.escape(PROVIDER_EMPTY_CONTENT_SENTINEL), re.IGNORECASE)
#: Canonical spellings whose beginning may be split across two stream chunks.
_PROTOCOL_TOKEN_PREFIXES = (
    "<think",
    "</think",
    "<mm:think",
    "</mm:think",
    "]<]minimax[>[",
    "<tool_call",
    "</tool_call",
    PROVIDER_EMPTY_CONTENT_SENTINEL,
)
_THINK_CLOSE_TAIL = len("</mm:think>") - 1
_TOOL_CALL_CLOSE_TAIL = len("</tool_call>") - 1
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
    if not text:
        return False
    if any(marker in text for marker in _HARD_MOJIBAKE_MARKERS):
        return True
    if _LATIN1_MOJIBAKE_PATTERN.search(text):
        return True
    # Single characters like "浣", "璇", "灏", "娑" appear in legitimate Chinese
    # text; require at least 2 distinct GBK-as-UTF-8 markers to flag mojibake.
    return sum(1 for marker in _GBK_MOJIBAKE_MARKERS if marker in text) >= 2


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
    cleaned = _PROVIDER_SENTINEL_PATTERN.sub("", text)
    cleaned = _THINK_BLOCK_PATTERN.sub("", cleaned)
    cleaned = _OPEN_THINK_BLOCK_PATTERN.sub("", cleaned)
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


_STRONG_INPUT_CORRUPTION_MARKERS = (
    "cannot read",
    "can't read",
    "could not read",
    "only saw",
    "only see",
    "\u53ea\u80fd\u770b\u5230\u4e00\u4e32",
    "\u770b\u8d77\u6765\u4f60\u53d1\u8fc7\u6765\u7684\u5185\u5bb9\u91cc\u4e2d\u6587\u90fd\u53d8\u6210\u4e86\u95ee\u53f7",
    "\u53d8\u6210\u4e86\u95ee\u53f7",
    "\u5168\u662f\u95ee\u53f7",
    "\u90fd\u662f\u95ee\u53f7",
    "\u5168\u662f\u4e71\u7801",
    "\u90fd\u662f\u4e71\u7801",
    "turned into question marks",
    "came through as question marks",
    "message arrived garbled",
    "input arrived garbled",
    "came through garbled",
    "your message looks garbled",
    "your input looks garbled",
)


def _looks_like_input_corruption_reply(
    reply: str,
    *,
    expected_probe: str | None = None,
) -> bool:
    visible = _compact_visible_text(reply, limit=400)
    if not visible:
        return False
    lowered = visible.casefold()
    if expected_probe and expected_probe in visible:
        return False
    has_strong_marker = any(
        marker.casefold() in lowered for marker in _STRONG_INPUT_CORRUPTION_MARKERS
    )
    has_marker = any(marker.casefold() in lowered for marker in _INPUT_CORRUPTION_MARKERS)
    if _QUESTION_RUN_PATTERN.search(visible) and has_marker:
        return True
    if has_strong_marker and (
        "?" in visible
        or "question mark" in lowered
        or "\u95ee\u53f7" in visible
        or "\u4e71\u7801" in visible
        or "corrupted" in lowered
        or "garbled" in lowered
    ):
        return True
    if expected_probe:
        if has_marker and (
            "?" in visible
            or "question mark" in lowered
            or "\u95ee\u53f7" in visible
            or "\u4e71\u7801" in visible
        ):
            return True
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


def _allows_cjk_response_language(response_language: str | None) -> bool:
    if _prefers_chinese(response_language):
        return True
    normalized = str(response_language or "").strip().lower()
    return normalized.startswith(("ja", "zh"))


def _unexpected_cjk_corruption_fragments(
    reply: str,
    *,
    message: str | None = None,
    response_language: str | None = None,
) -> list[str]:
    visible = _compact_visible_text(reply, limit=480)
    if not visible or not _contains_cjk(visible):
        return []
    if _allows_cjk_response_language(response_language):
        return []
    if message and _contains_cjk(message):
        return []
    # Strip backtick code spans and quoted strings so referencing a CJK filename
    # or UI label inside an English coaching reply is not misclassified.
    visible = re.sub(r"`[^`]*`|\"[^\"]*\"|'[^']*'", " ", visible)
    if not _contains_cjk(visible):
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
    if _allows_cjk_response_language(response_language):
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
    full_visible = _visible_model_text(reply).strip()
    if not full_visible or _contains_cjk(full_visible):
        return None
    # Strip fenced and inline code BEFORE truncating so a code block longer
    # than 480 chars does not lose its closing fence and look like prose.
    prose = re.sub(r"```[\s\S]*?```", "", full_visible)
    prose = re.sub(r"```[\s\S]*\Z", "", prose)
    prose = re.sub(r"`[^`]*`", "", prose)
    prose = " ".join(prose.split()).strip()[:480]
    latin_words = re.findall(r"[A-Za-z]{3,}", prose)
    # A one-line technical answer ("False", "It returns False immediately")
    # is not language corruption; only reject prose-length English. This keeps
    # short code answers usable without accepting a full English coaching turn.
    if len(latin_words) < 10:
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
    if _THINK_TAG_PATTERN.fullmatch(lowered):
        return True
    # A fragment of a tag whose rest has not arrived yet ("<thi", "</mm:th").
    return any(tag.startswith(lowered) for tag in _PROTOCOL_TOKEN_PREFIXES if tag.startswith("<"))


def _protocol_prefix_start(text: str) -> int | None:
    """Start of a trailing fragment that may be the beginning of a tag or provider marker.

    A tag or marker can be split across two stream chunks. Whatever might still turn into one
    stays in the buffer; everything before it is released.
    """
    lowered = text.lower()
    best: int | None = None
    for token in _PROTOCOL_TOKEN_PREFIXES:
        for length in range(len(token), 0, -1):
            if lowered.endswith(token[:length].lower()):
                start = len(text) - length
                if best is None or start < best:
                    best = start
                break
    return best


def _reasoning_prefix_start(text: str) -> int | None:
    last_lt = text.rfind("<")
    if last_lt < 0:
        return None
    if _is_think_tag_prefix(text[last_lt:]):
        return last_lt
    return None


def _trim_trailing_reasoning_prefix(text: str) -> str:
    prefix_start = _reasoning_prefix_start(text)
    if prefix_start is None:
        return text
    return text[:prefix_start]


def _prefers_chinese(response_language: str | None) -> bool:
    return bool(response_language and response_language.lower().startswith("zh"))


class ReasoningBlockFilter:
    """Keeps reasoning and provider protocol out of the visible stream.

    Hidden: ``<think>`` / ``<mm:think>`` blocks, the MiniMax control marker ``]<]minimax[>[``,
    and ``<tool_call>`` blocks — a model that tries to call a tool on a request that carries none
    sends the attempt as content. Text before a hidden construct is released at once; a construct
    split across chunks is held until its rest arrives.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._inside_think = False
        self._inside_tool_call = False

    def push(self, chunk: str) -> str:
        self._buffer += chunk
        return self._drain(final=False)

    def flush(self) -> str:
        buffered = self._drain(final=True)
        self._buffer = ""
        return buffered

    @staticmethod
    def _tail(text: str, length: int) -> str:
        return text[-length:] if len(text) > length else text

    def _drain(self, *, final: bool) -> str:
        emitted: list[str] = []

        while self._buffer:
            if self._inside_tool_call:
                close_match = _PSEUDO_TOOL_CALL_CLOSE_PATTERN.search(self._buffer)
                if close_match:
                    self._buffer = self._buffer[close_match.end() :]
                    self._inside_tool_call = False
                    continue
                # Still inside the block: keep only what could be the start of its closing tag.
                self._buffer = "" if final else self._tail(self._buffer, _TOOL_CALL_CLOSE_TAIL)
                break

            if self._inside_think:
                close_match = _THINK_CLOSE_TAG_PATTERN.search(self._buffer)
                if close_match:
                    self._buffer = self._buffer[close_match.end() :]
                    self._inside_think = False
                    continue
                self._buffer = "" if final else self._tail(self._buffer, _THINK_CLOSE_TAIL)
                break

            found: list[tuple[int, str, re.Match[str]]] = []
            for kind, pattern in (
                ("block", _THINK_BLOCK_PATTERN),
                ("open", _THINK_OPEN_TAG_PATTERN),
                ("close", _THINK_CLOSE_TAG_PATTERN),
                ("marker", _PROVIDER_CONTROL_MARKER_PATTERN),
                ("sentinel", _PROVIDER_SENTINEL_PATTERN),
                ("tool", _PSEUDO_TOOL_CALL_OPEN_PATTERN),
                ("tool_close", _PSEUDO_TOOL_CALL_CLOSE_PATTERN),
            ):
                match = pattern.search(self._buffer)
                if match:
                    found.append((match.start(), kind, match))
            if found:
                start, kind, match = min(found, key=lambda item: item[0])
                emitted.append(self._buffer[:start])
                self._buffer = self._buffer[match.end() :]
                if kind == "open":
                    self._inside_think = True
                elif kind == "tool":
                    self._inside_tool_call = True
                continue

            # Nothing hidden in the buffer: release it, but hold a trailing fragment that may
            # still become a tag or marker. At the end of the stream a fragment is just text.
            hold = None if final else _protocol_prefix_start(self._buffer)
            if hold is None:
                emitted.append(self._buffer)
                self._buffer = ""
            elif hold > 0:
                emitted.append(self._buffer[:hold])
                self._buffer = self._buffer[hold:]
            break

        return "".join(emitted)
