"""Language detection for provider replies (§五十二: extracted from provider_service.py)."""

from __future__ import annotations

import re

from .text import _visible_model_text

_CJK_CHAR_PATTERN = re.compile(r"[\u3400-\u9fff]")
_LATIN_CHAR_PATTERN = re.compile(r"[A-Za-z]")
_CYRILLIC_CHAR_PATTERN = re.compile(r"[\u0400-\u04FF]")


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


def _normalize_script_token(token: str) -> str:
    return re.sub(r"^[^A-Za-z\u0400-\u04FF]+|[^A-Za-z\u0400-\u04FF]+$", "", token)


def _normalize_cjk_script_token(token: str) -> str:
    return re.sub(r"^[^\u3400-\u9fff]+|[^\u3400-\u9fff]+$", "", token)
