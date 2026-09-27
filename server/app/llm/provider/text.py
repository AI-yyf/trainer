"""Text sanitization for provider responses (§五十二).

Handles reasoning-block stripping, mojibake detection, provider control
marker removal, and visible-text normalization.
"""

from __future__ import annotations

import re

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


def _normalize_cjk_script_token(token: str) -> str:
    return re.sub(r"^[^\u3400-\u9fff]+|[^\\u3400-\u9fff]+$", "", token)
