"""Agent tool-context assembly (§五十二: extracted from provider_service.py).

Builds the extra context block the coach agent loop receives: explicit
write-tool scoping, denied auto-mint tool reporting, and the
learner-pressure / streak / resume-hint annotations.
"""

from __future__ import annotations

from typing import Any

from ..core.models import ProviderConfig
from .coaching_patches import _compatibility_intake_is_tool_free
from .prompts import normalize_answer_policy
from .provider.redaction import _compact_text

_FORMAL_PLAN_TOOLS = (
    "learning_inspect",
    "learning_action",
    "project_read",
    "library_read",
    "web_fetch",
)


#: A nudge ("然后呢？", "下一步？", "这样对吗？") is at most this many characters. Longer messages
#: ask for something and keep their tools.
SHORT_FOLLOW_UP_MAX_CHARS = 24

#: Substrings with which a learner asks for something a tool has to fetch or run. Any hit keeps the
#: tools mounted: the lane only covers a nudge, and a wrongly tool-free turn costs more than a
#: needless round trip, so the list errs towards matching.
_TOOL_SEEKING_TOKENS: frozenset[str] = frozenset(
    {
        # Chinese
        "运行", "跑一", "跑下", "测试", "验证", "检查", "执行", "搜索", "搜一", "查找", "找一", "看看", "看一下",
        "读一", "读下", "打开", "项目", "工程", "文件夹", "目录", "整个", "所有", "其他", "别的", "另外", "资料",
        "讲讲", "讲解", "解释", "分析", "原理", "计划", "复习", "卡片", "笔记", "讲稿", "保存", "生成", "创建",
        "新建", "截图", "图片", "网页", "链接", "对比", "列出", "查",
        # The Latin product languages (English, Spanish, French, German, Portuguese)
        "run", "test", "verif", "verifica", "check", "search", "find", "look", "read", "open", "project",
        "repo", "folder", "file", "explain", "expli", "explique", "erklär", "analy", "analyse", "walk",
        "overview", "plan", "review", "save", "guarda", "speicher", "enregistre", "note", "card",
        "generate", "create", "fetch", "url", "link", "list", "liste", "show", "ejecu", "exécute",
        "ausführen", "prüf", "such", "cherch", "busca",
    }
)

#: Coaching-context flags that open another lane (plan, cards, notes, resources, verification).
#: Any of them keeps the tools.
_TOOL_LANE_FLAGS: tuple[str, ...] = (
    "formal_plan_mutation",
    "explicit_training_card_request",
    "explicit_learning_note_request",
    "explicit_lecture_note_save_request",
    "explicit_resource_import",
    "explicit_resource_organize",
    "auto_resource_lookup",
    "library_sandbox_work",
    "rubric_review_allowed",
    "completed_training_return_feedback",
)


def short_follow_up_next_to_live_error(
    *,
    message: str | None,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    attachments_present: bool = False,
) -> bool:
    """Whether a turn is a short follow-up typed beside a file that shows a live error.

    Everything the next nudge needs is already in the prompt — the open file, its diagnostics,
    the thread's last step — so the turn is answered in one model call with no tools mounted.
    Measured with a real model (2026-11-28): with tools the model spent two or three round trips
    (7-28 s to its first visible word); without, one call and a median of 3 s.

    The lane is narrow on purpose. It needs a short single-line message without code, without a
    word that asks for a tool, live diagnostics on the open file, no attachment, and no other
    coaching lane involved.
    """
    text = str(message or "").strip()
    if not text or not isinstance(current_file, dict):
        return False
    if len(text) > SHORT_FOLLOW_UP_MAX_CHARS or "\n" in text or "```" in text:
        return False
    diagnostics = current_file.get("diagnostics")
    if not isinstance(diagnostics, list) or not any(str(item or "").strip() for item in diagnostics):
        return False
    if attachments_present:
        return False
    lowered = text.lower()
    if any(token in lowered for token in _TOOL_SEEKING_TOKENS):
        return False
    context = coach_context if isinstance(coach_context, dict) else {}
    if any(context.get(flag) is True for flag in _TOOL_LANE_FLAGS):
        return False
    if context.get("resource_composer_intent") or context.get("resource_ids"):
        return False
    active_view = str(context.get("active_view") or "").strip().lower()
    return active_view in {"", "coach"}


def _denied_auto_mint_tool_names(extra: dict[str, Any]) -> list[str]:
    from .tools import PROJECT_WRITE_TOOL_NAMES

    denied: list[str] = []
    pressure_blocks = extra.get("pressure_blocks_live_object_mint") is True
    streak_blocks = extra.get("streak_blocks_live_object_mint") is True
    # Learning OS: never silently write learner project / business code.
    denied.extend(sorted(PROJECT_WRITE_TOOL_NAMES))
    # Composer chat never mints cards (even explicit "create a practice card").
    # Intentional mint is POST /training/generate-card only.
    denied.append("generate_training_card")
    if extra.get("completed_training_return_feedback") is True:
        denied.append("verify_practice_current_file")
    if extra.get("formal_plan_mutation") is not True:
        denied.append("save_formal_plan")
    if extra.get("explicit_learning_note_request") is not True:
        denied.append("record_learning_note")
    if (
        extra.get("explicit_lecture_note_save_request") is not True
        and extra.get("explicit_learning_note_request") is not True
    ):
        denied.append("save_lecture_note")
    # The learner works with the library (Resources view, sandbox work or an
    # explicit ask) far more often than not, so the flags are stamped above;
    # every other turn stays read-only instead of auto-minting write tools.
    if extra.get("explicit_resource_import") is not True:
        denied.append("import_resource_url")
    if extra.get("explicit_resource_organize") is not True:
        denied.append("organize_resources")
    # Host-gated rubric review (P2 #15): arms only on an explicit learner
    # request with a host card rubric present, or a host flag.
    if extra.get("rubric_review_allowed") is not True:
        denied.append("run_rubric_review")
    # Same live-plan identity as HTTP /task/next and /task/specify.
    if (
        pressure_blocks
        or streak_blocks
        or extra.get("live_formal_plan_for_task_mint") is not True
        or extra.get("closed_loop_return_blocks_task_mint") is True
    ):
        denied.append("specify_task")
        denied.append("next_task")
    return denied


def _host_rubric_items_present(extra: dict[str, Any]) -> bool:
    """Host-supplied card rubric present (P2 #15): text_submission or the
    host current_file carries non-empty ``rubric_items``. Model tool arguments
    are never consulted."""
    for key in ("text_submission", "current_file"):
        payload = extra.get(key)
        if isinstance(payload, dict):
            items = payload.get("rubric_items")
            if isinstance(items, list) and items:
                return True
    return False


def _stamp_explicit_write_tool_flags(
    extra: dict[str, Any],
    *,
    coach_context: dict[str, Any] | None,
    learner_message: str | None,
) -> None:
    from ..memory.note_request import (
        message_requests_explicit_learning_note,
        message_requests_lecture_note_save,
    )
    from .tools import resource_write_explicitly_requested

    extra["explicit_learning_note_request"] = (
        isinstance(coach_context, dict)
        and coach_context.get("explicit_learning_note_request") is True
    ) or message_requests_explicit_learning_note(learner_message)
    extra["explicit_lecture_note_save_request"] = (
        isinstance(coach_context, dict)
        and coach_context.get("explicit_lecture_note_save_request") is True
    ) or message_requests_lecture_note_save(learner_message)
    extra["explicit_resource_import"] = (
        isinstance(coach_context, dict)
        and coach_context.get("explicit_resource_import") is True
    ) or resource_write_explicitly_requested(extra, mode="download")
    extra["explicit_resource_organize"] = (
        isinstance(coach_context, dict)
        and coach_context.get("explicit_resource_organize") is True
    ) or resource_write_explicitly_requested(extra, mode="organize")
    from ..training.card_request import message_requests_rubric_review

    extra["rubric_review_allowed"] = (
        isinstance(coach_context, dict)
        and coach_context.get("rubric_review_allowed") is True
    ) or (
        message_requests_rubric_review(learner_message)
        and _host_rubric_items_present(extra)
    )
    if (
        extra.get("library_sandbox_work") is True
        or str(extra.get("active_view") or "").strip().lower() == "resources"
        or extra.get("resource_composer_intent")
        or (isinstance(coach_context, dict) and coach_context.get("library_sandbox_work") is True)
    ):
        extra["library_sandbox_work"] = True
        extra["explicit_resource_organize"] = True
        extra["explicit_resource_import"] = True
    extra["denied_tool_names"] = _denied_auto_mint_tool_names(extra)


def _build_agent_tool_context_extra(
    *,
    coach_context: dict[str, Any] | None,
    attachment_delivery: dict[str, Any],
    answer_mode: str | None,
    current_file: dict[str, object] | None,
    provider_config: ProviderConfig | None = None,
    learner_message: str | None = None,
) -> dict[str, Any]:
    from ..training.card_request import message_requests_explicit_training_card

    normalized_answer_mode = normalize_answer_policy(answer_mode)
    extra: dict[str, Any] = {
        "attachments_will_send": bool(attachment_delivery.get("attachments_delivered_to_model")),
        "answer_mode": normalized_answer_mode,
        "allow_coach_only_tools": normalized_answer_mode in {"guided", "balanced"},
    }
    if provider_config is not None:
        window = getattr(provider_config, "context_window_tokens", None)
        model_name = str(getattr(provider_config, "model", "") or "").strip()
        limits = getattr(provider_config, "model_token_limits", None)
        if model_name and isinstance(limits, dict):
            entry = limits.get(model_name)
            if isinstance(entry, dict):
                window = entry.get("contextWindowTokens") or entry.get("context_window_tokens") or window
            elif entry is not None:
                window = getattr(entry, "context_window_tokens", None) or window
        try:
            if window is not None and int(window) > 0:
                extra["context_window_tokens"] = int(window)
            else:
                from .harness import DEFAULT_CONTEXT_WINDOW_TOKENS

                extra["context_window_tokens"] = DEFAULT_CONTEXT_WINDOW_TOKENS
        except (TypeError, ValueError):
            from .harness import DEFAULT_CONTEXT_WINDOW_TOKENS

            extra["context_window_tokens"] = DEFAULT_CONTEXT_WINDOW_TOKENS
    if isinstance(coach_context, dict):
        coach_defaults = coach_context.get("coach_defaults")
        if isinstance(coach_defaults, dict):
            raw_custom_skills = coach_defaults.get("custom_skills") or coach_defaults.get("customSkills")
            if isinstance(raw_custom_skills, list):
                extra["custom_skills"] = list(raw_custom_skills)
    resolved_learner_message = learner_message
    if not isinstance(coach_context, dict):
        if isinstance(current_file, dict):
            extra["current_file"] = dict(current_file)
        extra["explicit_training_card_request"] = message_requests_explicit_training_card(
            resolved_learner_message
        )
        _stamp_explicit_write_tool_flags(
            extra,
            coach_context=None,
            learner_message=resolved_learner_message,
        )
        if isinstance(resolved_learner_message, str) and resolved_learner_message.strip():
            extra["learner_message"] = resolved_learner_message
        if "allowed_tool_names" not in extra:
            if short_follow_up_next_to_live_error(
                message=resolved_learner_message,
                current_file=current_file if isinstance(current_file, dict) else None,
                coach_context=None,
                attachments_present=bool(attachment_delivery.get("attachments_present")),
            ):
                extra["allowed_tool_names"] = []
                extra["tool_free_fast_lane"] = True
            else:
                from .tool_primitives import select_orthogonal_tools_for_turn

                extra["allowed_tool_names"] = select_orthogonal_tools_for_turn(
                    extra, resolved_learner_message
                )
        return extra

    if isinstance(current_file, dict):
        extra["current_file"] = dict(current_file)

    explicit_tool_scope = coach_context.get("allow_coach_only_tools")
    if isinstance(explicit_tool_scope, bool):
        extra["allow_coach_only_tools"] = explicit_tool_scope

    def _add_if_present(key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        extra[key] = value

    for key in (
        "scenario",
        "active_view",
        "library_sandbox_work",
        "workspace_file_snapshot",
        "resource_composer_intent",
        "learner_signal",
        "current_focus",
        "summary",
        "continuity_summary",
        "review_queue_summary",
        "next_step_hint",
        "pace_signal",
        "first_turn_priority",
        "formal_plan_mutation",
        # Host-gated rubric review (P2 #15): like formal_plan_mutation, this is
        # an explicit host decision about the turn's verification lane; the
        # model can never assert it.
        "rubric_review_allowed",
        "completed_training_return_feedback",
        # Host-declared subject family (P1 #9). Practice verification routes on
        # it; it is a fact about the workspace, so it only ever arrives from the
        # host — never from model-authored tool arguments.
        "subject_family",
        # Local-only cooperative cancellation signal for active SSE turns.
        "stream_cancel_event",
    ):
        _add_if_present(key, coach_context.get(key))

    if coach_context.get("formal_plan_mutation") is True:
        extra["formal_plan_mutation"] = True
        # Formal plan turns are an explicit, governed write lane. They must be
        # able to call the commit tool even when the learner's default answer
        # policy is guided and would otherwise hide coach-only writes.
        extra["allow_coach_only_tools"] = True
        extra["allowed_tool_names"] = list(_FORMAL_PLAN_TOOLS)

    if coach_context.get("pressure_blocks_live_object_mint") is True:
        extra["pressure_blocks_live_object_mint"] = True
    if coach_context.get("streak_blocks_live_object_mint") is True:
        extra["streak_blocks_live_object_mint"] = True
    if coach_context.get("closed_loop_return_blocks_task_mint") is True:
        extra["closed_loop_return_blocks_task_mint"] = True
    if coach_context.get("live_formal_plan_for_task_mint") is True:
        extra["live_formal_plan_for_task_mint"] = True

    # Host/user attestation only — never trust model tool-arg self-attestation.
    if coach_context.get("resource_organization_confirmed") is True:
        extra["resource_organization_confirmed"] = True

    if not isinstance(resolved_learner_message, str) or not resolved_learner_message.strip():
        context_message = coach_context.get("learner_message")
        if isinstance(context_message, str) and context_message.strip():
            resolved_learner_message = context_message
    extra["explicit_training_card_request"] = (
        coach_context.get("explicit_training_card_request") is True
        or message_requests_explicit_training_card(resolved_learner_message)
    )
    _stamp_explicit_write_tool_flags(
        extra,
        coach_context=coach_context,
        learner_message=resolved_learner_message,
    )
    if isinstance(resolved_learner_message, str) and resolved_learner_message.strip():
        extra["learner_message"] = resolved_learner_message

    thread_summary = _compact_text(coach_context.get("thread_summary"), 140)
    thread_next_step = _compact_text(coach_context.get("thread_next_step"), 110)
    resume_hint = _compact_text(coach_context.get("resume_hint"), 160)
    active_thread = coach_context.get("active_thread")
    if isinstance(active_thread, dict):
        if not thread_summary:
            thread_summary = _compact_text(active_thread.get("summary"), 140) or _compact_text(active_thread.get("focus_area"), 140)
        if not thread_next_step:
            thread_next_step = _compact_text(active_thread.get("next_step"), 110)
    if not resume_hint:
        resume_hint_parts: list[str] = []
        if thread_summary:
            resume_hint_parts.append(f"Resume the live thread around {thread_summary}.")
        if thread_next_step:
            resume_hint_parts.append(f"Keep the next move as {thread_next_step}.")
        if isinstance(active_thread, dict):
            blocker = _compact_text(active_thread.get("blocker"), 96)
            verified_result = _compact_text(active_thread.get("verified_result"), 96)
            if blocker:
                resume_hint_parts.append(f"Keep the blocker in view: {blocker}.")
            if verified_result:
                resume_hint_parts.append(f"Build on the verified result: {verified_result}.")
        resume_hint = " ".join(resume_hint_parts).strip()
    _add_if_present("thread_summary", thread_summary)
    _add_if_present("thread_next_step", thread_next_step)
    _add_if_present("resume_hint", resume_hint)

    implementation_guide = coach_context.get("implementation_guide")
    if isinstance(implementation_guide, dict):
        for key in ("current_step", "scope_boundary", "validation_strategy"):
            _add_if_present(f"implementation_{key}", implementation_guide.get(key))

    exercise_prompt = coach_context.get("exercise_prompt")
    if isinstance(exercise_prompt, dict):
        for key in ("prompt", "success_signal", "fallback_step"):
            _add_if_present(f"exercise_{key}", exercise_prompt.get(key))

    active_thread = coach_context.get("active_thread")
    if isinstance(active_thread, dict):
        for key in ("focus_area", "verified_result", "blocker", "next_step"):
            _add_if_present(f"thread_{key}", active_thread.get(key))

    if _compatibility_intake_is_tool_free(
        provider_config=provider_config,
        coach_context=coach_context,
        attachment_delivery=attachment_delivery,
        current_file=current_file,
    ):
        extra["allowed_tool_names"] = []
    elif short_follow_up_next_to_live_error(
        message=resolved_learner_message,
        current_file=current_file if isinstance(current_file, dict) else None,
        coach_context=coach_context,
        attachments_present=bool(attachment_delivery.get("attachments_present")),
    ):
        extra["allowed_tool_names"] = []
        extra["tool_free_fast_lane"] = True
    elif "allowed_tool_names" not in extra:
        from .tool_primitives import select_orthogonal_tools_for_turn

        extra["allowed_tool_names"] = select_orthogonal_tools_for_turn(
            extra, resolved_learner_message
        )

    return extra
