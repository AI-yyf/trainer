"""Onboarding signal extraction mixin for :class:`MemoryService`.

Pure message-parsing statics (goal/background/name/hours/teaching-style/
answer-policy/libraries/project-context/blocker/rhythm/stack/learning-mode/
onboarding-request extraction plus response-language label normalization).
Extracted verbatim from ``memory/service.py`` (pure code motion, zero
behavior change); ``MemoryService`` keeps the public API via mixin
inheritance and re-imports ``_contains_chinese`` for its own text helpers.
"""

from __future__ import annotations

import re


def _contains_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


class OnboardingExtractionMixin:
    """Hosts the onboarding signal extraction statics of ``MemoryService``."""

    @staticmethod
    def _extract_long_term_goal(message: str) -> str:
        patterns = [
            r"(?:长期目标(?:是)?|目标是|我想要|我希望|我想)([^。！？\n]{4,80})",
            r"(?:long[- ]term goal(?:\s+is(?:\s+to)?)?|goal is|i want to|i want|i hope to)([^.!\n]{4,100})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _extract_background(message: str) -> str:
        patterns = [
            r"(?:我现在是|我目前是|我属于|我是)([^。！？，,\n]{2,50})",
            r"(?:i am|i'm|my background is)\s*(?:an?\s+)?([^.,!\n]{2,60})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _extract_learner_name(message: str) -> str:
        patterns = [
            r"(?:我叫|你可以叫我|叫我)([^。！？，,\n]{1,24})",
            r"(?:my name is|call me)([^.!\n]{1,24})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _extract_weekly_hours(message: str) -> int | None:
        zh = re.search(
            r"每周(?:大概|能|可以)?(?:投入|安排|学习)?\s*(\d{1,2})\s*(?:小时|h)",
            message,
            flags=re.IGNORECASE,
        )
        if zh:
            return int(zh.group(1))
        en = re.search(r"(\d{1,2})\s*(?:hours?|hrs?)\s*(?:a|per)?\s*week", message, flags=re.IGNORECASE)
        if en:
            return int(en.group(1))
        return None

    @staticmethod
    def _extract_teaching_style(message: str) -> str:
        lowered = message.lower()
        if any(token in lowered for token in ("引导式", "guided")):
            return "guided"
        if any(token in lowered for token in ("平衡式", "balanced")):
            return "balanced"
        if any(token in lowered for token in ("直接式", "直接一点", "direct")):
            return "direct"
        return ""

    @staticmethod
    def _extract_answer_policy(message: str) -> str:
        lowered = message.lower()
        if any(token in lowered for token in ("直接给代码", "直接告诉我", "just tell me", "give me the code")):
            return "direct"
        if any(token in lowered for token in ("引导", "guided")):
            return "guided"
        if any(token in lowered for token in ("平衡", "balanced")):
            return "balanced"
        return ""

    @staticmethod
    def _extract_preferred_libraries(message: str) -> list[str]:
        libraries = [
            "fastapi",
            "pytest",
            "react",
            "vue",
            "next.js",
            "nextjs",
            "typescript",
            "tailwind",
            "django",
            "flask",
            "sqlalchemy",
        ]
        lowered = message.lower()
        matched = [item for item in libraries if item in lowered]
        return list(dict.fromkeys(matched))

    @staticmethod
    def _extract_project_context(message: str, *, focus_area: str) -> str:
        normalized_message = " ".join(message.strip().lower().split())
        compact_message = re.sub(
            r"[\s\.,!?:;\"'(){}\[\]/\\_\-，。！？、：；]+",
            "",
            normalized_message,
        )
        if compact_message in {
            "hello",
            "hi",
            "hey",
            "hellotrainer",
            "hitrainer",
            "goodmorning",
            "goodafternoon",
            "goodevening",
            "你好",
            "您好",
            "嗨",
            "哈喽",
            "早上好",
            "下午好",
            "晚上好",
        }:
            return ""
        quoted = re.search(r"[“\"]([^”\"]{4,80})[”\"]", message)
        if quoted:
            return quoted.group(1).strip()
        if focus_area:
            return focus_area
        patterns = [
            r"(?:项目|工程|idea|功能|模块)([^。！？\n]{3,60})",
            r"(?:project|feature|module|idea)([^.!\n]{3,80})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _extract_blocker(message: str) -> str:
        patterns = [
            r"(?:卡在|卡住了|问题是|报错是|不会的地方是)([^。！？\n]{3,80})",
            r"(?:stuck on|blocked on|the issue is|the blocker is|error is)([^.!\n]{3,100})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _extract_rhythm_preference(message: str) -> str:
        lowered = message.lower()
        if any(token in lowered for token in ("一步一步", "慢一点", "small step", "step by step", "tiny step")):
            return "small-step"
        if any(token in lowered for token in ("快一点", "直接上", "move fast", "faster")):
            return "fast"
        if any(token in lowered for token in ("按计划", "稳一点", "steady", "systematic")):
            return "steady"
        return ""

    @staticmethod
    def _extract_preferred_stack(message: str) -> str:
        patterns = [
            r"(?:技术栈(?:是|想用)?|我想用|我主要用|偏向用)([^。！？\n]{3,72})",
            r"(?:stack is|prefer to use|mainly use|want to use)([^.!\n]{3,80})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _extract_learning_mode(message: str) -> str:
        lowered = message.lower()
        mapping = [
            (("先讲原理", "原理优先", "concept first"), "concept-first"),
            (("带我实现", "边做边学", "hands on", "implement with me"), "hands-on"),
            (("先定计划", "按计划练", "plan first"), "plan-first"),
            (("给我出题", "训练题", "exercise"), "exercise-first"),
            (("一步一步带我", "引导式", "guided"), "guided"),
        ]
        for tokens, label in mapping:
            if any(token in lowered for token in tokens):
                return label
        return ""

    @staticmethod
    def _extract_onboarding_request(message: str) -> str:
        patterns = [
            r"(?:我最想推进的是|这轮最想推进的是|我现在最需要的是)([^。！？\n]{4,80})",
            r"(?:what i most want to move forward is|what i need most right now is)([^.!\n]{4,100})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _normalize_response_language_label(response_language: str, *, message: str) -> str:
        normalized = response_language.strip().lower()
        if normalized.startswith("zh") or _contains_chinese(message):
            return "zh-CN"
        if normalized:
            return normalized
        if re.search(r"[a-zA-Z]", message):
            return "en-US"
        return ""
