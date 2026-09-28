"""Coach reply drafts and final patches (§五十二: extracted from provider_service.py).

The small reply constructors (onboarding, error, missing-key) and the
final patch pass that tightens reviews, weaves recalled memory, and
checks success/failure signals before a reply reaches the learner.
"""

from __future__ import annotations

import re
from typing import Any

from ..core.models import UserProfile
from .coaching_first_turn import (
    _first_turn_lane_continuity_note,
    _first_turn_lane_next_step,
    _resolve_first_turn_guided_lane,
)
from .coaching_patches import _reply_has_action_signal, _reply_mentions_excerpt
from .coaching_recovery import (
    _clean_guided_domain_empty_reply,
    _infer_guided_coaching_domain,
    _prefers_chinese,
)
from .coaching_replies import (
    _looks_like_internal_coach_meta,
    _relevance_reanchor_visible_reply,
    _reply_needs_current_request_reanchor,
)
from .prompts import normalize_answer_policy
from .provider.redaction import redact_provider_error
from .provider.text import _contains_cjk, _visible_model_text


def _agent_result_visible_text(result: Any) -> str:
    return _visible_model_text(getattr(result, "final_content", "") or "")


def _agentic_has_grounded_resource_evidence(tool_events: list[dict[str, Any]]) -> bool:
    grounded_tool_names = {
        "search_learning_materials",
        "search_resources",
        "read_workspace_file",
    }
    for event in tool_events:
        if not isinstance(event, dict):
            continue
        name = str(event.get("name") or "").strip()
        if name in grounded_tool_names:
            return True
    return False


def _agentic_final_event_from_result(result: Any) -> dict[str, Any]:
    return {
        "type": "final",
        "content": _agent_result_visible_text(result),
        "summary": getattr(result, "summary", None),
        "next_step": getattr(result, "next_step", None),
        "stop_reason": getattr(result, "stop_reason", "completed"),
        "decision": getattr(result, "decision", None),
        "blocker": getattr(result, "blocker", None),
        "teaching_note": getattr(result, "teaching_note", None),
        "resume_thread": getattr(result, "resume_thread", None),
        "confidence": getattr(result, "confidence", None),
        "evidence": getattr(result, "evidence", None),
    }


def _message_probe_fragment(message: str | None, limit: int = 120) -> str:
    normalized = " ".join(str(message or "").split()).strip()
    if not normalized or not _contains_cjk(normalized):
        return ""
    if len(normalized) <= limit:
        return normalized
    cjk_index = next((index for index, char in enumerate(normalized) if _contains_cjk(char)), 0)
    start = max(0, min(cjk_index, max(0, len(normalized) - limit)))
    fragment = normalized[start : start + limit].strip()
    if not _contains_cjk(fragment):
        fragment = normalized[:limit].strip()
    ascii_match = re.search(r"[A-Za-z][A-Za-z0-9._/-]{1,}", normalized)
    if ascii_match:
        ascii_token = ascii_match.group(0)
        if ascii_token not in fragment:
            remaining = limit - len(fragment) - 1
            if remaining > 0:
                fragment = f"{fragment} {ascii_token[:remaining]}".strip()
    return fragment


def _message_probe_variant(message: str | None) -> tuple[str, str] | None:
    fragment = _message_probe_fragment(message)
    if not fragment:
        return None
    return (f"Repeat exactly: {fragment}", fragment)


def _agent_loop_max_steps(
    coach_context: dict[str, Any] | None,
    requested: int | None = None,
) -> int:
    """Resolve the last-resort safety ceiling for one agent turn.

    Pi's inner loop has no operational step cap: it continues until the model
    stops calling tools. Lane-specific 8/16/20 budgets were the wrong bound.
    ``requested`` still lets tests and callers pin a smaller ceiling.
    """

    _ = coach_context
    if requested is not None:
        return max(1, int(requested))
    from .agent_loop import SAFETY_MAX_STEPS

    return SAFETY_MAX_STEPS


def _guided_domain_empty_reply(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> str:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    return _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
    )


def _append_unique_paragraphs(reply: str, additions: list[str]) -> str:
    resolved: list[str] = []
    for item in additions:
        cleaned = item.strip()
        if not cleaned:
            continue
        if _reply_mentions_excerpt(reply, cleaned):
            continue
        if any(_reply_mentions_excerpt(existing, cleaned) for existing in resolved):
            continue
        resolved.append(cleaned)
    if not resolved:
        return reply
    return f"{reply}\n\n" + "\n\n".join(resolved)


def _fresh_lane_reanchor_reply(
    scenario: str,
    *,
    response_language: str | None = None,
    coach_context: dict[str, Any] | None = None,
) -> str:
    chinese = _prefers_chinese(response_language)
    guided_note = _first_turn_lane_continuity_note(
        scenario,
        chinese=chinese,
        coach_context=coach_context,
    )
    guided_close = _first_turn_lane_next_step(
        scenario,
        chinese=chinese,
        coach_context=coach_context,
    )
    return "\n\n".join(part for part in (guided_note, guided_close) if part.strip())


def _should_preserve_visible_reply(
    message: str,
    *,
    answer_mode: str | None,
    profile: UserProfile,
) -> bool:
    if normalize_answer_policy(answer_mode or profile.answer_policy) == "direct":
        return True

    normalized = " ".join(str(message or "").casefold().split())
    explicit_answer_markers = (
        "directly answer",
        "just answer",
        "only answer",
        "in three sentences",
        "in 3 sentences",
        "do not ask",
        "don't ask",
        "no next step",
        "without asking",
        "\u8bf7\u76f4\u63a5\u56de\u7b54",
        "\u53ea\u8981\u56de\u7b54",
        "\u4e09\u53e5\u8bdd",
        "\u4e0d\u8981\u5148\u95ee",
        "\u4e0d\u8981\u7ed9\u6211\u4e0b\u4e00\u6b65",
    )
    return any(marker in normalized for marker in explicit_answer_markers)


def _reply_needs_first_turn_reframe(reply: str) -> bool:
    stripped = reply.strip()
    if not stripped:
        return False

    paragraphs = [part.strip() for part in stripped.split("\n\n") if part.strip()]
    if len(paragraphs) >= 3:
        return True
    if len(stripped) >= 260:
        return True

    lowered = stripped.lower()
    structural_signals = ("```", "## ", "### ", "\n- ", "\n* ", "\n1. ", "\n2. ")
    if any(signal in lowered for signal in structural_signals):
        return True

    return False


def _has_repeated_failure_signal(
    learning_outcomes: list[dict[str, object]],
    pace_signal: str,
    learner_signal: str,
) -> bool:
    if pace_signal in {"fragile", "stalled", "recovery"}:
        return True
    if learner_signal == "blocked":
        return True
    repeated_markers = {
        "repeated_error",
        "blocked",
        "repeated_failure",
        "regression",
        "forgotten",
        "failed_review",
        "retry",
    }
    for item in learning_outcomes:
        outcome = str(item.get("outcome") or "").strip().lower()
        summary = str(item.get("summary") or "").strip().lower()
        if outcome in repeated_markers:
            return True
        if "failed twice" in summary or "repeated" in summary or "again" in summary:
            return True
    return False


def _strip_generic_lane_prompt_artifacts(
    reply: str,
    scenario: str,
    learner_message: str,
    chinese: bool,
) -> str:
    resolved_scenario = _resolve_first_turn_guided_lane(
        scenario=scenario,
        learner_message=learner_message,
        reply=reply,
    )
    if resolved_scenario not in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return reply

    generic_paragraphs = {
        "I will first understand your goal, project, and blocker, remember that context for the next turn, then decide whether to guide the code, explain the principle, or shape the training thread first.",
        "Tell me which lane is closest right now: implementing an idea, adapting a project, or shaping the training thread first.",
        "Tell me which lane is closest right now: implementing an idea, adapting an existing project, or shaping the training thread first.",
    }
    if chinese:
        generic_paragraphs.update(
            {
                "我会先理解你的目标、项目和阻塞点，记住这些上下文，再决定先带你改代码、讲原理，还是先整理训练线程。",
                "请告诉我现在最接近哪条线：实现一个想法、适配一个项目，还是先整理训练线程。",
                "请告诉我现在最接近哪条线：实现一个想法、适配现有项目，还是先整理训练线程。",
            }
        )

    paragraphs = [part.strip() for part in reply.split("\n\n") if part.strip()]
    filtered = [part for part in paragraphs if part not in generic_paragraphs]
    if len(filtered) == len(paragraphs):
        return reply
    return "\n\n".join(filtered).strip()


def _reanchor_visible_reply_to_current_request(
    reply: str,
    *,
    message: str | None,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> str:
    if not _reply_needs_current_request_reanchor(
        reply,
        message=message,
        current_file=current_file,
        coach_context=coach_context,
    ):
        return reply
    repaired = _relevance_reanchor_visible_reply(
        message=message,
        current_file=current_file,
        response_language=response_language,
    )
    return repaired or reply


def _contains_meta_coach_context(text: str) -> bool:
    return _looks_like_internal_coach_meta(text)


def _provider_service_onboarding_reply(self, response_language: str | None = None) -> str:
    if _prefers_chinese(response_language):
        return (
            "先别急着直接上方案。第一轮我更想先把你的目标、项目语境和你更适合的带法对齐起来。\n\n"
            "你可以直接告诉我你现在手上的项目、想学到哪一步、卡在哪里，我会把这些判断记住，后面继续沿着同一条线带你，不会每一轮都重开。\n\n"
            "你现在更需要我带你做哪一类：实现一个 idea、改造现有项目，还是先把训练主线和节奏定下来？"
        )
    return (
        "Let's not jump straight into a solution. On the first turn I want to line up the few things that matter most: "
        "your goal, the project context, and how you prefer to be coached.\n\n"
        "Tell me what you are working on, where you want to get to, and where the thread feels unstable right now. "
        "I will remember that context so the next turn can continue the same lane instead of restarting.\n\n"
        "Which lane is closest right now: implement an idea, adapt a project, or shape the training thread first?"
    )


def _provider_service_error_reply(self, exc: Exception, response_language: str | None = None) -> str:
    detail = redact_provider_error(exc, api_key=self._api_key)
    if _prefers_chinese(response_language):
        return (
            "连接教练服务时遇到了一点问题，所以这一轮我先用本地教练逻辑把你接住。"
            f" 这次的错误是：{detail}。"
        )
    return (
        "I hit an issue connecting to the coach service, so I am keeping this turn moving locally. "
        f"The error was: {detail}."
    )


def _provider_service_missing_api_key_reply(
    self,
    response_language: str | None = None,
) -> str:
    if _prefers_chinese(response_language):
        return (
            "还没有设置可用的 API 密钥。"
            "请到设置里填写模型服务和密钥，然后就可以开始对话。"
        )
    return (
        "Trainer cannot start working yet because there is no usable API key. "
        "Open Settings, save a provider, model, and API key, and I can continue from there."
    )


def _scaffold_close(
    *,
    learner_signal: str,
    mode: str,
    verbosity_bias: str,
    chinese: bool,
) -> str:
    if chinese:
        if learner_signal == "blocked":
            return "如果你一动手又卡住，就把那一小段原样带回来，我帮你再缩一层。"
        if mode == "direct":
            return "做完别只说“好了”，告诉我你验证到了什么，我再帮你选下一步。"
        if verbosity_bias == "short":
            return "先做这一步，再把结果带回来。"
        return "先做这一步，再把结果带回来，我们再决定是扩展、复盘，还是继续收紧。"
    if learner_signal == "blocked":
        return "If you get stuck again as soon as you start, show me the exact small section you were about to change and I will help you reduce it one step further."
    if mode == "direct":
        return "When you finish, do not just say 'done'; tell me what result you verified and I will help you choose the next move."
    if verbosity_bias == "short":
        return "Take that one step first, then bring back the result."
    return "Take that one step first, then bring back the result and we can decide whether to expand, review, or tighten the loop."


def _compose_review_tightening_patch(
    *,
    reply: str,
    scenario: str,
    failing_checks: list[str],
    learning_outcomes: list[dict[str, object]],
    pace_signal: str,
    learner_signal: str,
    chinese: bool,
) -> str:
    repeated_failure = _has_repeated_failure_signal(learning_outcomes, pace_signal, learner_signal)
    review_pressure = scenario in {"review", "task", "next_task", "plan", "project_adaptation"} or bool(
        failing_checks or repeated_failure
    )
    if not review_pressure:
        return ""
    if _reply_has_scope_tightening_signal(reply, chinese) and _reply_has_verification_signal(reply, chinese):
        return ""

    check = failing_checks[0] if failing_checks else ""
    if chinese:
        if check:
            return f"先别扩范围。先把 `{check}` 这一条最小反馈链恢复出来，确认它通过，再决定要不要扩。"
        return "先别扩范围。先恢复一条最小反馈链，确认这一步通过，再决定要不要扩。"

    if check:
        return f"Do not widen scope on this turn. First restore one minimal feedback loop around `{check}`, confirm it passes, then decide whether to expand."
    return "Do not widen scope on this turn. First restore one minimal feedback loop, confirm this step passes, then decide whether to expand."


def _compose_success_signal_patch(
    *,
    reply: str,
    exercise_prompt: dict[str, object] | None,
    chinese: bool,
) -> str:
    exercise_prompt = exercise_prompt or {}
    if not exercise_prompt:
        return ""
    success_signal = str(exercise_prompt.get("success_signal") or "").strip()
    if not success_signal:
        return ""
    if _contains_meta_coach_context(success_signal):
        return ""
    if _reply_mentions_excerpt(reply, success_signal):
        return ""
    if _reply_has_verification_signal(reply, chinese) and len(reply) > 180:
        return ""
    if chinese:
        return f"这一步算过的信号是：{success_signal}。"
    return f"You can count this slice as done when: {success_signal}."


def _compose_recalled_memory_patch(
    *,
    reply: str,
    recalled_coaching_memories: list[dict[str, object]],
    chinese: bool,
) -> str:
    if not recalled_coaching_memories:
        return ""
    if _reply_has_recall_signal(reply, chinese):
        return ""

    first = recalled_coaching_memories[0]
    lesson = str(first.get("lesson") or first.get("summary") or "").strip()
    title = str(first.get("title") or "").strip()
    if not lesson:
        return ""
    if _reply_mentions_excerpt(reply, lesson) or (title and _reply_mentions_excerpt(reply, title)):
        return ""
    if (
        len(reply) > 220
        and _reply_has_action_signal(reply, chinese)
        and _reply_has_verification_signal(reply, chinese)
    ):
        return ""
    if chinese:
        return f"先沿着之前已经验证过的做法走：{lesson}。"
    return f"Stay on the line that already worked before: {lesson}."


def _reply_has_verification_signal(reply: str, chinese: bool) -> bool:
    markers = ["verify", "check", "run", "test", "confirm", "passes", "feedback loop"]
    if chinese:
        markers.extend(["验证", "检查", "确认", "跑一次", "通过", "反馈链", "验收信号", "可验证"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_scope_tightening_signal(reply: str, chinese: bool) -> bool:
    markers = ["do not widen", "reduce scope", "tighten", "smallest", "minimal", "one branch", "one patch"]
    if chinese:
        markers.extend(["先别扩范围", "不要扩范围", "收紧", "最小反馈链", "最小可验证", "缩小范围"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_recall_signal(reply: str, chinese: bool) -> bool:
    markers = ["previous", "earlier", "already worked", "reuse", "stay on the line", "keep this lane"]
    if chinese:
        markers.extend(["之前", "前面", "已经验证过", "复用", "沿着这条线", "继续这条线"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _clean_provider_service_onboarding_reply(
    self,
    response_language: str | None = None,
) -> str:
    if _prefers_chinese(response_language):
        return (
            "先别急着直接上方案。第一轮我想先把你的目标、项目语境、"
            "以及更适合你的带法对齐起来。\n\n"
            "你可以直接告诉我现在手上的项目、想学到哪一步、卡在哪里。"
            "我会记住这些判断，后面继续沿着同一条线带你，不会每一轮都重开。\n\n"
            "你现在更需要我带你做哪一类：实现一个 idea、改造现有项目，"
            "还是先把训练主线和节奏定下来？"
        )
    return (
        "Let's not jump straight into a solution. On the first turn I want to line up the few things that matter most: "
        "your goal, the project context, and how you prefer to be coached.\n\n"
        "Tell me what you are working on, where you want to get to, and where the thread feels unstable right now. "
        "I will remember that context so the next turn can continue the same lane instead of restarting.\n\n"
        "Which lane is closest right now: implement an idea, adapt a project, or shape the training thread first?"
    )


def _clean_provider_service_error_reply(
    self,
    exc: Exception,
    response_language: str | None = None,
) -> str:
    detail = redact_provider_error(exc, api_key=self._api_key)
    if _prefers_chinese(response_language):
        return (
            "连接教练服务时遇到问题，所以这轮我先用本地恢复逻辑接住你。"
            f"这次错误是：{detail}。"
        )
    return (
        "I hit an issue connecting to the coach service, so I am keeping this turn moving locally. "
        f"The error was: {detail}."
    )


def _clean_provider_service_missing_api_key_reply(
    self,
    response_language: str | None = None,
) -> str:
    if _prefers_chinese(response_language):
        return (
            "还没有设置可用的 API 密钥。"
            "请到设置里填写模型服务和密钥，然后就可以开始对话。"
        )
    return (
        "Trainer cannot start working yet because there is no usable API key. "
        "Open Settings, save a provider, model, and API key, and I can continue from there."
    )
