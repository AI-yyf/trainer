"""Domain constants for decomposed router services."""

from __future__ import annotations

import re

_SCHEMELESS_PROVIDER_HOST_RE = re.compile(
    r"^(?:localhost|(?:\d{1,3}\.){3}\d{1,3}|(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,})"
    r"(?::\d{1,5})?(?:/\S*)?$",
    re.IGNORECASE,
)
_SCHEMELESS_LOCAL_HOST_WITH_PORT_RE = re.compile(
    r"^[a-z0-9][a-z0-9-]*(?::\d{1,5})(?:/\S*)?$",
    re.IGNORECASE,
)
_LOCAL_PROVIDER_HOST_RE = re.compile(
    r"^(?:localhost|host\.docker\.internal|::1"
    r"|(?:127|10)\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|.+\.(?:localhost|local|test))$",
    re.IGNORECASE,
)


coach_summary_scenarios = {
    "general",
    "onboarding",
    "idea_implementation",
    "project_idea",
    "project_idea_mining",
    "project_adaptation",
    "project_sourcing",
    "principle",
    "principle_explanation",
    "remote_workspace",
    "debug_loop",
    "function_guidance",
    "review",
    "review_reflection",
    "plan",
    "task",
    "next_task",
}

GENERIC_FOCUS_LABELS = {
    "",
    "implementation",
    "current lane",
    "current focus",
    "current task",
    "current stage",
    "current thread",
    "active thread",
    "coach",
    "coaching",
    "task",
    "plan",
    "review",
    "evaluation",
    "practice",
    "training",
    "general",
    "coach-turn",
    # Bare acknowledgments / filler. "好,给我第一个最小练习" splits on the
    # comma into first clause "好", which then surfaced in the reply as
    # 「好」 being the coaching focus.
    "ok",
    "okay",
    "alright",
    "sure",
    "yes",
    "yeah",
    "yep",
    "yup",
    "go",
    "go ahead",
    "continue",
    "next",
    "please",
    "thanks",
    "thank you",
    "好",
    "好的",
    "好嘞",
    "好呀",
    "好啦",
    "好嘛",
    "好滴",
    "嗯",
    "嗯嗯",
    "嗯呐",
    "行",
    "行吧",
    "可以",
    "成",
    "中",
    "妥",
    "继续",
    "接着来",
    "来吧",
    "开始吧",
    "下一步",
    "麻烦了",
    "谢谢",
    "多谢",
}

GENERIC_FOCUS_DISPLAY_LABELS = {
    "implementation": ("implementation slice", "实现切片"),
    "vs code remote workspace": ("VS Code remote workspace", "VS Code 远程工作区"),
    "vs code debug loop": ("VS Code debug loop", "VS Code 调试闭环"),
    "function contract": ("function contract reading", "\u51fd\u6570\u5951\u7ea6\u5224\u65ad"),
    "remote workspace boundary": ("remote workspace boundary", "远程工作区边界"),
    "the smallest trustworthy debug loop": ("the smallest trustworthy debug loop", "最小可信的 debug loop"),
    "function contract and call-site reading": (
        "function contract and call-site reading",
        "\u51fd\u6570\u5951\u7ea6\u4e0e call site \u5224\u65ad",
    ),
}

GUIDED_LANE_SCENARIOS = {
    "remote_workspace",
    "debug_loop",
    "function_guidance",
    "project_adaptation",
}
GUIDED_VISIBLE_REPAIR_SCENARIOS = {
    "remote_workspace",
    "debug_loop",
    "function_guidance",
}

_GUIDED_LANE_CONTINUATION_PATTERN = re.compile(
    r"""(?i)^continue\s+['"].+?['"]\s+and do not open a new lane before this next move lands:"""
)

PROVIDER_REPLY_STOP_REASONS = {
    "invalid_key_or_permission",
    "language_corruption",
    "model_unsupported",
    "model_not_found",
    "malformed_response",
    "truncated_or_empty",
    "rate_limit",
    "upstream_unavailable",
    "timeout",
    "network",
    "unknown",
}

# First-turn lanes ship a canonical, hand-composed next step; the grounding
# retry must not replace that ruling with a model rewrite.
DETERMINISTIC_LANE_SCENARIOS = {
    "remote_workspace",
    "debug_loop",
    "function_guidance",
    "project_adaptation",
}

NON_LEARNING_RECOVERY_STOP_REASONS = {
    *PROVIDER_REPLY_STOP_REASONS,
    "empty_response",
    "language_corruption_recovered",
    "max_steps",
    "no_progress",
    "provider_error",
}

GUIDED_SEQUENCE_SCENARIOS = {"remote_workspace", "debug_loop", "function_guidance"}

_STREAM_STATUS_PHASES = {
    "preparing_context",
    "requesting_model",
    "model_reasoning",
    "tool_intent",
    "intent",
    "pending",
    "executing",
    "succeeded",
    "failed",
    "acked",
    "cancelled",
}

GROUNDING_DECISION_CACHE_KEY = "_grounding_decision"
GROUNDING_MEMORY_PROVENANCE_CACHE_KEY = "_grounding_memory_provenance"
GROUNDING_EVALUATED_NEXT_STEP_CACHE_KEY = "_grounding_evaluated_next_step"

GUIDED_SCENARIO_TRAINING_PACKS = {
    "remote_workspace",
    "debug_loop",
    "function_guidance",
}
