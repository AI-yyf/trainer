"""Coach response-language alignment (Phase 4 split, second router slice).

Pure helpers extracted from ``api/routers.py`` (build_router closure): localize
known English focus phrases into Chinese, align context text/list payloads to
the learner's response language, and re-shape thread/memory/coaching-state
payloads. Behaviour unchanged — the router keeps aliases with the original
names so every call site and RouterDeps binding stays identical.
"""

from __future__ import annotations

import re

from ._helpers import (
    contains_cjk_text,
    looks_like_mojibake_text,
    normalized_object_mapping,
    prefers_chinese,
)
from .coach_text_sanitizer import normalize_visible_coach_text

KNOWN_CONTEXT_TRANSLATIONS_ZH: tuple[tuple[str, str], ...] = (
    ("function contract and call-site reading", "\u51fd\u6570\u5951\u7ea6\u4e0e call site \u5224\u65ad"),
    ("the smallest trustworthy debug loop", "最小可信的 debug loop"),
    ("remote workspace boundary", "远程工作区边界"),
    ("VS Code remote workflow", "VS Code 远程工作区"),
    ("Code remote workflow", "远程工作区边界"),
    ("VS Code remote workspace", "VS Code 远程工作区"),
    ("VS Code function guidance", "VS Code 函数提示"),
    ("function contract recovery", "\u6062\u590d\u51fd\u6570\u5951\u7ea6"),
    ("function contract reading", "\u51fd\u6570\u5951\u7ea6\u5224\u65ad"),
    ("VS Code debug loop", "VS Code 调试闭环"),
)

def localize_known_context_phrases(
    value: str,
    response_language: str | None,
) -> str:
    if not value or not prefers_chinese(response_language):
        return value

    cleaned = value
    lane_match = re.match(
        r"""^Continue\s+['"](?P<focus>.+?)['"]\s+and do not open a new lane before this next move lands:\s*(?P<rest>.+)$""",
        cleaned,
        flags=re.IGNORECASE,
    )
    if lane_match:
        localized_focus = localize_known_context_phrases(
            lane_match.group("focus").strip(),
            response_language,
        )
        localized_rest = localize_known_context_phrases(
            lane_match.group("rest").strip(),
            response_language,
        )
        return f"继续沿着「{localized_focus}」这条主线，先别开新线：{localized_rest}".strip()

    for source, target in KNOWN_CONTEXT_TRANSLATIONS_ZH:
        cleaned = re.sub(re.escape(source), target, cleaned, flags=re.IGNORECASE)

    exact_focus_map = {
        "debug loop": "调试闭环",
        "function contract": "\u51fd\u6570\u5951\u7ea6\u5224\u65ad",
        "call-site reading": "call site 判断",
    }
    normalized_cleaned = cleaned.strip()
    localized_exact = exact_focus_map.get(normalized_cleaned.casefold())
    if localized_exact:
        return localized_exact

    return cleaned

def language_aligned_context_text(
    value: object,
    response_language: str | None,
) -> str:
    if not isinstance(value, str):
        return ""
    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized:
        return ""
    if prefers_chinese(response_language) and looks_like_mojibake_text(normalized):
        return ""
    if not prefers_chinese(response_language) and contains_cjk_text(normalized):
        latin_fragments = [
            re.sub(r"\s+", " ", fragment).strip(" \t\r\n-:;,.!?/|()[]{}<>")
            for fragment in re.split(r"[\u3400-\u9fff]+", normalized)
        ]
        salvage = " ".join(
            fragment
            for fragment in latin_fragments
            if fragment and re.search(r"[A-Za-z0-9`]", fragment)
        ).strip()
        return normalize_visible_coach_text(salvage)
    return localize_known_context_phrases(
        normalize_visible_coach_text(normalized),
        response_language,
    )

def language_aligned_context_list(
    value: object,
    response_language: str | None,
    *,
    limit: int | None = None,
) -> list[str]:
    if not isinstance(value, list):
        return []
    aligned: list[str] = []
    for item in value:
        normalized = language_aligned_context_text(item, response_language)
        if not normalized or normalized in aligned:
            continue
        aligned.append(normalized)
        if limit is not None and len(aligned) >= limit:
            break
    return aligned

def language_aligned_flat_payload(
    value: dict[str, object] | None,
    response_language: str | None,
    *,
    list_limit: int = 6,
) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    aligned = dict(value)
    for key, item in list(aligned.items()):
        if isinstance(item, str):
            aligned[key] = language_aligned_context_text(item, response_language)
            continue
        if isinstance(item, list):
            if all(not isinstance(entry, dict) for entry in item):
                aligned[key] = language_aligned_context_list(
                    item,
                    response_language,
                    limit=list_limit,
                )
    return aligned

def ensure_coach_turn_payload(
    value: dict[str, object] | None,
    fallback: dict[str, object],
) -> dict[str, object]:
    return value if value is not None else fallback

def language_aligned_thread_payload(
    value: dict[str, object] | None,
    response_language: str | None,
) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    aligned = dict(value)
    if "scenario" in aligned:
        aligned["scenario"] = str(aligned.get("scenario") or "").strip()
    for key in (
        "focus_area",
        "summary",
        "next_step",
        "blocker",
        "verified_result",
        "decision",
        "teaching_note",
        "confidence",
    ):
        if key in aligned:
            aligned[key] = language_aligned_context_text(aligned.get(key), response_language)
    if "evidence" in aligned:
        aligned["evidence"] = language_aligned_context_list(
            aligned.get("evidence"),
            response_language,
            limit=4,
        )
    return aligned

def language_aligned_memory_payload(
    value: dict[str, object] | None,
    response_language: str | None,
) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    aligned = dict(value)
    for key in (
        "current_focus",
        "recent_summary",
        "review_rhythm",
        "coach_anchor",
        "top_weakness",
        "pace_signal",
    ):
        if key in aligned:
            aligned[key] = language_aligned_context_text(aligned.get(key), response_language)
    for key in (
        "weaknesses",
        "recent_wins",
        "lowest_mastery_concepts",
        "teaching_observations",
    ):
        if key in aligned:
            aligned[key] = language_aligned_context_list(aligned.get(key), response_language)
    if "active_thread" in aligned:
        aligned["active_thread"] = language_aligned_thread_payload(
            normalized_object_mapping(aligned.get("active_thread")),
            response_language,
        )
    return aligned

def language_aligned_coaching_state_payload(
    value: dict[str, object] | None,
    response_language: str | None,
) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    aligned = dict(value)
    for key in (
        "summary",
        "next_step",
        "decision",
        "blocker",
        "teaching_note",
        "confidence",
        "encouragement",
        "intervention_strategy",
        "teaching_goal",
        "resume_thread",
        "support_strategy",
    ):
        if key in aligned:
            aligned[key] = language_aligned_context_text(aligned.get(key), response_language)
    if "evidence" in aligned:
        aligned["evidence"] = language_aligned_context_list(
            aligned.get("evidence"),
            response_language,
            limit=4,
        )
    return aligned

def language_aligned_review_rhythm(
    value: object,
    response_language: str | None,
) -> str | None:
    normalized = language_aligned_context_text(value, response_language)
    return normalized or None

