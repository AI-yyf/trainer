"""Coach visible-text sanitization (Phase 4 split).

Pure, state-free helpers extracted from ``api/routers.py`` (build_router
closure): strip internal meta prefixes/markers, repair legacy assistant
messages, and sanitize visible coach payloads. Behaviour is intentionally
unchanged — the router keeps local aliases with the original names so every
internal call site and RouterDeps binding stays identical.
"""

from __future__ import annotations

import re

from ..core.models import WorkbenchSnapshot
from ._helpers import localized_text, looks_like_mojibake_text

_VISIBLE_COACH_TEXT_FIELDS = {
    "blocked_reason",
    "blockedReason",
    "continuity_summary",
    "continuitySummary",
    "current_focus",
    "currentFocus",
    "current_step",
    "currentStep",
    "focus_area",
    "focusArea",
    "next_after_current",
    "nextAfterCurrent",
    "next_step",
    "nextStep",
    "resume_thread",
    "resumeThread",
    "review_queue_summary",
    "reviewQueueSummary",
    "review_rhythm",
    "reviewRhythm",
    "strategy_preference_summary",
    "strategyPreferenceSummary",
    "summary",
    "teaching_goal",
    "teachingGoal",
    "teaching_note",
    "teachingNote",
    "verified_result",
    "verifiedResult",
    "why_now",
    "whyNow",
}
_VISIBLE_COACH_META_PREFIXES = (
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
    "memory scope is",
    "evidence to anchor on:",
    "this follows the teaching lane from",
    "reuse the saved teaching asset",
    "\u5f53\u524d\u805a\u7126\uff1a",
    "\u5f53\u524d\u805a\u7126\u70b9\uff1a",
    "\u590d\u4e60\u8282\u594f\uff1a",
    "\u8bb0\u5fc6\u8303\u56f4\u662f",
)
_VISIBLE_COACH_META_LABELS = {
    "general coaching",
    "idea implementation guidance",
    "next step after review",
    "next task coaching",
    "plan and review rhythm",
    "principle explanation",
    "project adaptation",
    "project idea mining",
    "project implementation",
    "review and reflection coaching",
    "task execution coaching",
}
_VISIBLE_COACH_PREFIX_PATTERNS = (
    re.compile(r"^resume the live thread(?: around)?\s*", re.IGNORECASE),
    re.compile(r"^resume from the current coaching lane,?\s*", re.IGNORECASE),
    re.compile(r"^['\"][^'\"]+['\"]\.?\s*do this next before widening scope:\s*", re.IGNORECASE),
    re.compile(r"^do this next before widening scope:\s*", re.IGNORECASE),
)
_VISIBLE_COACH_INLINE_PATTERNS = (
    re.compile(r"\bcurrent coaching focus:\s*", re.IGNORECASE),
    re.compile(r"\bcurrent focus(?: to continue)?:\s*", re.IGNORECASE),
    re.compile(r"\breview rhythm:\s*", re.IGNORECASE),
    re.compile(r"\bpreferred teaching asset:\s*", re.IGNORECASE),
    re.compile(r"\breusable teaching asset:\s*", re.IGNORECASE),
    re.compile(r"\bresume the live thread around\s*", re.IGNORECASE),
    re.compile(r"\bresume from the current coaching lane,?\s*", re.IGNORECASE),
    re.compile(r"\bbuild on the verified result:\s*", re.IGNORECASE),
    re.compile(r"\bkeep the blocker in view:\s*", re.IGNORECASE),
    re.compile(r"\bcoach confidence:\s*", re.IGNORECASE),
    re.compile(r"\bevidence to anchor on:\s*", re.IGNORECASE),
)
_INTERNAL_VISIBLE_REPLY_MARKERS = (
    "<system-reminder>",
    "</system-reminder>",
    "system-reminder",
    "workspace file",
    "current file snapshot",
    "current file snap",
    "real tool call",
    "real workspace environment",
    "真实工程环境",
    "真实工具调用",
    "上一轮没有可用的 workspace file",
    "上一轮没有可用的 current file",
    "current file 或 workspace file",
)

def normalize_visible_coach_text(value: object) -> str:
    raw_text = str(value or "").strip()
    if not raw_text:
        return ""
    if looks_like_mojibake_text(raw_text):
        return ""

    cleaned = re.sub(r"\s+", " ", raw_text).strip()
    prefix_removed = False
    stripped_label = cleaned.casefold().strip(" -:*_#>~`[](){}")
    if stripped_label in _VISIBLE_COACH_META_LABELS:
        return ""
    for label in _VISIBLE_COACH_META_LABELS:
        if cleaned.casefold().startswith(label):
            cleaned = cleaned[len(label) :].lstrip(" .:-")
            prefix_removed = True
            break
    for prefix in _VISIBLE_COACH_META_PREFIXES:
        if cleaned.casefold().startswith(prefix):
            cleaned = cleaned[len(prefix) :].lstrip(" .:-")
            prefix_removed = True
            break
    for pattern in _VISIBLE_COACH_PREFIX_PATTERNS:
        next_cleaned = pattern.sub("", cleaned).lstrip(" .:-")
        if next_cleaned != cleaned:
            cleaned = next_cleaned
            prefix_removed = True
    for pattern in _VISIBLE_COACH_INLINE_PATTERNS:
        next_cleaned = pattern.sub("", cleaned)
        if next_cleaned != cleaned:
            cleaned = next_cleaned
            prefix_removed = True
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if prefix_removed:
        cleaned = re.sub(
            r"([.!?])\s+([a-z])",
            lambda match: f"{match.group(1)} {match.group(2).upper()}",
            cleaned,
        )
    if prefix_removed and cleaned[:1].isascii() and cleaned[:1].islower():
        cleaned = f"{cleaned[:1].upper()}{cleaned[1:]}"
    return cleaned

def visible_reply_segment_looks_internal(value: object) -> bool:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    if not cleaned:
        return False
    return any(marker.casefold() in cleaned for marker in _INTERNAL_VISIBLE_REPLY_MARKERS)

def sanitize_visible_coach_reply_content(
    value: object,
    response_language: str | None = None,
) -> str:
    raw_text = str(value or "").strip()
    if not raw_text:
        return ""

    if looks_like_mojibake_text(raw_text):
        return localized_text(
            "I could not read that reply. Please send the same question again.",
            "这条回复没有读清。请把刚才的问题再发一次。",
            response_language,
        )

    cleaned = raw_text.replace("<system-reminder>", "").replace("</system-reminder>", "").strip()
    internal_marker_seen = visible_reply_segment_looks_internal(raw_text) or visible_reply_segment_looks_internal(
        cleaned
    )
    paragraphs = [segment.strip() for segment in re.split(r"\n\s*\n", cleaned) if segment.strip()]
    while len(paragraphs) > 1 and visible_reply_segment_looks_internal(paragraphs[0]):
        paragraphs.pop(0)
        internal_marker_seen = True
    cleaned = "\n\n".join(paragraphs) if paragraphs else cleaned
    if internal_marker_seen:
        sentence_segments = [
            segment.strip()
            for segment in re.split(r"(?<=[.!?。！？])\s+", cleaned)
            if segment.strip()
        ]
        if sentence_segments:
            while len(sentence_segments) > 1 and visible_reply_segment_looks_internal(sentence_segments[0]):
                sentence_segments.pop(0)
            cleaned = " ".join(sentence_segments).strip()
    cleaned = re.sub(r"^(?:<[^>\n]+>\s*)+", "", cleaned).strip()
    return cleaned

def repair_legacy_assistant_messages(
    snapshot: WorkbenchSnapshot,
    response_language: str | None,
) -> bool:
    repaired = False
    for index, message in enumerate(snapshot.messages):
        if str(message.role or "").strip().lower() != "assistant":
            continue
        content = str(message.content or "").strip()
        cleaned = sanitize_visible_coach_reply_content(content, response_language)
        if cleaned == content:
            continue
        snapshot.messages[index] = message.model_copy(update={"content": cleaned})
        repaired = True
    return repaired

def strip_visible_next_step_prefix(value: object) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"(?i)^(?:next(?: step)?\s*:\s*)+", "", cleaned).strip()
    cleaned = re.sub(r"^(?:\u4e0b\u4e00\u6b65[:\uff1a]\s*)+", "", cleaned).strip()
    return cleaned

def sanitize_visible_coach_payload(value: object) -> object:
    if isinstance(value, dict):
        sanitized: dict[object, object] = {}
        for key, item in value.items():
            if key in _VISIBLE_COACH_TEXT_FIELDS and isinstance(item, str):
                sanitized[key] = normalize_visible_coach_text(item)
            else:
                sanitized[key] = sanitize_visible_coach_payload(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_visible_coach_payload(item) for item in value]
    return value

