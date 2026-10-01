"""First-turn lane selection (§五十二: extracted from provider_service.py).

Chooses how the very first coaching reply of a scenario is framed: the
explicit-answer lanes, the guided-domain lane prompt, and how a concrete
first turn is compacted into a coachable reply.
"""

from __future__ import annotations

import re
from typing import Any

from .coaching_recovery import (
    _function_guidance_starter_reply_parts,
    _infer_guided_coaching_domain,
    _trim_sentence,
)
from .prompts import infer_coaching_scenario
from .provider.redaction import _compact_text


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


def _first_turn_lane_continuity_note(
    scenario: str,
    *,
    chinese: bool,
    coach_context: dict[str, Any] | None = None,
) -> str:
    if scenario == "remote_workspace":
        if chinese:
            return "我会继续把这一轮留在 VS Code remote 这条线上：先确认工作区边界和文件实际在哪台机器上，再收住一个最小验证动作。"
        return (
            "I will keep this in the VS Code remote lane: first prove the workspace boundary "
            "and where the files actually live, then line up one minimal verification move."
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
        if chinese:
            return "我会先把函数理解锚定在一个 live call site 上，再用 hover、signature help 和 definition 把 contract 读稳。"
        return (
            "I will keep this anchored to one live call site, then use hover, signature help, "
            "and definition until the function contract stops moving."
        )
    if scenario == "project_adaptation":
        if chinese:
            return "我会先理解你的目标、项目语境和当前阻塞点，再分清现有项目里哪些必须稳定、哪些必须改变，然后落一个窄范围 adaptation。"
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
            return "下一步：先把工作区落点说清楚：告诉我当前工作区是 SSH、tunnels、dev container、WSL 还是 local，再给我一个 Explorer 路径、`pwd` 结果或 remote host 标签。"
        return (
            "Next step: give me one minimal verification move for the workspace boundary - tell "
            "me whether this workspace is SSH, tunnels, dev container, WSL, or local, then show "
            "one Explorer path, `pwd`, or remote host label."
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
        if chinese:
            return "下一步：给我函数名和一个你现在就能打开的 call site，我们再从那里读参数、返回值和上下文。"
        return (
            "Next step: give me the function name and one call site you can open right now, "
            "and we will read the parameters, return value, and context from there."
        )
    if scenario == "project_adaptation":
        if chinese:
            return "下一步：带回一个真实例子或片段，告诉我哪条边界要先适配。"
        return (
            "Next step: bring back one real example and tell me which boundary "
            "to adapt first."
        )
    return ""


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
        return "下一步：给我一个你现在就能展开的真实例子或片段，我们接着做。"
    return (
        "Next step: give me one real example or snippet you can open right now, "
        "and we'll keep going."
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
