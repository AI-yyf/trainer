from __future__ import annotations

import re
from typing import cast

from ..core.models import ResponseLanguage

SUPPORTED_RESPONSE_LANGUAGES = frozenset(
    {"zh-CN", "en-US", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR"}
)

def prefers_chinese(response_language: str | None) -> bool:
    return bool(response_language and response_language.lower().startswith("zh"))

def contains_cjk_text(value: str | None) -> bool:
    return bool(value and any("\u3400" <= char <= "\u9fff" for char in value))

LATIN1_MOJIBAKE_PATTERN = re.compile(
    r"(?:[\u00C2\u00C3\u00C4\u00C5\u00C6\u00C7\u00C8\u00C9\u00CF\u00D0\u00E2\u00E3\u00E4\u00E5\u00E6\u00E7\u00E8\u00E9\u00EF\u00F0][\u0080-\u00BF]{1,2}){2,}"
)
GBK_MOJIBAKE_MARKERS = (
    "\u6d93",
    "\u7f01",
    "\u93c8",
    "\u59e3",
    "\u8930",
    "\u93b4",
    "\u9410",
    "\u7487",
    "\u95c4",
    "\u9359",
    "\u9365",
    "\u5a0c",
    "\u741b",
    "\u5bf0",
)
GBK_MOJIBAKE_FRAGMENTS = (
    "\u6d93\u5b29\u7af4",
    "\u7f01\u0445\u753b",
    "\u6fe1\u509b\u7049",
    "\u8930\u64b3\u58a0",
    "\u59e3\u5fd3\u59e9",
    "\u93c8\u20ac",
    "\u95c4\u52eb",
    "\u9365\u5267\u5896",
    "\u741b\u30e4\u7af5",
)

def looks_like_mojibake_text(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    suspicious_markers = ("�", "鈧", "偓", "閸", "鐠", "娑", "缂", "濞", "瑜", "绱", "顒", "鍐")
    return any("\ue000" <= character <= "\uf8ff" for character in text) or any(
        marker in text for marker in suspicious_markers
    ) or any(fragment in text for fragment in GBK_MOJIBAKE_FRAGMENTS) or sum(
        marker in text for marker in GBK_MOJIBAKE_MARKERS
    ) >= 2 or bool(LATIN1_MOJIBAKE_PATTERN.search(text))

def localized_text(english: str, chinese: str, response_language: str | None) -> str:
    if prefers_chinese(response_language):
        extended_markers = ("\ufffd", "\ue000", "\ue1ec", "鈧", "閸", "鐠", "娑", "缂")
        if looks_like_mojibake_text(chinese) or any(marker in chinese for marker in extended_markers):
            return english
    return chinese if prefers_chinese(response_language) else english

def supported_response_language(value: object | None) -> ResponseLanguage | None:
    candidate = str(value or "").strip()
    if candidate in SUPPORTED_RESPONSE_LANGUAGES:
        return cast(ResponseLanguage, candidate)
    return None

