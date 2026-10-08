"""Reply patch composition (§五十二: extracted from provider_service.py).

Builds the small repair patches applied to a coaching reply: missing
next-step synthesis, principle follow-through, scaffold paragraphs,
empty-reply overrides, and the excerpt/signal checks they rely on.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from ..core.models import ProviderConfig
from .coaching_recovery import (
    _agentic_resume_thread_text,
    _clean_guided_domain_empty_reply_override,
    _function_guidance_starter_reply_parts,
    _infer_guided_coaching_domain,
    _localized_text,
)
from .coaching_replies import (
    _agentic_practice_verification_context_active,
    _claims_verified_practice_completion,
    _current_file_practice_verification_result,
    _looks_like_generic_guided_review_fallback,
    _looks_like_internal_coach_meta,
    _normalize_coach_meta_candidate,
    _normalize_search_text,
    _reply_mentions_current_request_anchor,
    _strip_internal_coach_meta,
    _structured_view_has_lane_signal,
)
from .coaching_scaffold import (
    _practice_verification_arguments,
    _scenario_step_text,
    _surface_context_text,
)
from .provider.redaction import _compact_text
from .provider_protocols import normalize_provider_protocol


def _compatibility_intake_is_tool_free(
    *,
    provider_config: ProviderConfig | None,
    coach_context: dict[str, Any] | None,
    attachment_delivery: dict[str, Any],
    current_file: dict[str, object] | None,
) -> bool:
    if provider_config is None or not isinstance(coach_context, dict):
        return False
    if normalize_provider_protocol(getattr(provider_config, "protocol", None)) != "anthropic_messages":
        return False
    hostname = (urlsplit(str(getattr(provider_config, "base_url", "") or "")).hostname or "").lower()
    if hostname.endswith("anthropic.com"):
        return False
    if str(coach_context.get("relationship_stage") or "").strip() != "intake":
        return False
    if not str(coach_context.get("first_turn_priority") or "").startswith(
        "orient, reassure, clarify learner goal"
    ):
        return False
    if str(coach_context.get("scenario") or "").strip() not in {
        "remote_workspace",
        "debug_loop",
        "function_guidance",
    }:
        return False
    if current_file or attachment_delivery.get("attachments_present"):
        return False
    if coach_context.get("auto_resource_lookup") is True:
        return False
    if any(
        isinstance(coach_context.get(key), list) and coach_context[key]
        for key in ("resource_fragments", "requested_resources")
    ):
        return False
    active_view = str(coach_context.get("active_view") or "").strip().lower()
    return active_view in {"", "coach"}


async def _maybe_auto_verify_practice_current_file(
    *,
    registry: Any,
    context: Any,
    tool_events: list[dict[str, Any]],
    message: str,
    content: str,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if isinstance(coach_context, dict) and coach_context.get("completed_training_return_feedback") is True:
        return []
    if _current_file_practice_verification_result(tool_events) is not None:
        return []
    if not _agentic_practice_verification_context_active(
        message=message,
        current_file=current_file,
        coach_context=coach_context,
    ):
        return []
    if not _practice_verification_requested_or_claimed(message=message, content=content):
        return []
    if not isinstance(current_file, dict):
        return []
    file_content = current_file.get("content") or current_file.get("content_excerpt") or ""
    if not str(file_content).strip():
        return []
    arguments = _practice_verification_arguments(
        current_file=current_file,
        coach_context=coach_context,
    )
    if not arguments.get("acceptance_criteria") and not arguments.get("expected_symbols"):
        return []

    tool_id = "auto_verify_practice_current_file"
    tool_call = {
        "type": "tool_call",
        "id": tool_id,
        "name": "verify_practice_current_file",
        "arguments": arguments,
        "step": "auto",
        "auto": True,
    }
    tool_result = await registry.invoke(context, "verify_practice_current_file", arguments)
    return [
        tool_call,
        {
            "type": "tool_result",
            "id": tool_id,
            "name": "verify_practice_current_file",
            "ok": bool(tool_result.get("ok")) if isinstance(tool_result, dict) else False,
            "result": tool_result,
            "step": "auto",
            "auto": True,
        },
    ]


def _practice_verification_requested_or_claimed(*, message: str, content: str) -> bool:
    if _claims_verified_practice_completion(content):
        return True
    # A reply proposing a future experiment is not a request to verify the
    # learner's current file. Only the learner's request triggers that path.
    lowered = message.lower()
    return any(
        phrase in lowered
        for phrase in (
            "can i mark",
            "mark it",
            "mark this",
            "verify",
            "verification",
            "passed",
            "complete",
            "done",
            "review my practice",
            "验证",
            "核验",
            "验收",
            "通过",
            "完成",
            "评估我的练习",
            "评审我的练习",
            "检查我的训练",
        )
    )


def _guided_domain_empty_reply_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, str] | None:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    return _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
    )


def _compose_scaffold_paragraphs(
    *,
    scenario: str,
    mode: str,
    learner_signal: str,
    anchor: str,
    diagnosis: str,
    next_step: str,
    teaching_note: str,
    close: str,
    chinese: bool,
) -> list[str]:
    if chinese:
        if scenario in {"review", "task", "next_task", "engineering_challenge"}:
            return [
                anchor,
                f"{diagnosis} {next_step}".strip(),
                teaching_note,
                close,
            ]
        if scenario in {"principle", "plan", "concept_teaching"}:
            return [
                anchor,
                diagnosis,
                f"{next_step} {teaching_note}".strip(),
                close,
            ]
        if learner_signal == "blocked" or mode == "direct":
            return [
                anchor,
                f"{diagnosis} {next_step}".strip(),
                close,
            ]
        return [
            anchor,
            diagnosis,
            next_step,
            teaching_note,
            close,
        ]

    if scenario in {"review", "task", "next_task", "engineering_challenge"}:
        return [
            anchor,
            f"{diagnosis} {next_step}".strip(),
            teaching_note,
            close,
        ]
    if scenario in {"principle", "plan", "concept_teaching"}:
        return [
            anchor,
            diagnosis,
            f"{next_step} {teaching_note}".strip(),
            close,
        ]
    if learner_signal == "blocked" or mode == "direct":
        return [
            anchor,
            f"{diagnosis} {next_step}".strip(),
            close,
        ]
    return [
        anchor,
        diagnosis,
        next_step,
        teaching_note,
        close,
    ]


def _normalize_visible_resume_thread_text(text: str, *, chinese: bool) -> str:
    normalized = _strip_internal_coach_meta(text).strip()
    if not normalized:
        return ""
    if chinese:
        prefixes = (
            "回到同一条教练线程：",
            "沿着当前主线继续：",
            "继续当前主线。",
            "沿着同一条线继续。",
        )
        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                break
        normalized = re.sub(r"(下一步[:：]\s*){2,}", "下一步：", normalized)
        return normalized.strip()
    english_prefixes = (
        "Resume the live thread around ",
        "Resume the live thread. ",
        "Stay on that same thread: ",
    )
    lowered = normalized.casefold()
    for prefix in english_prefixes:
        if lowered.startswith(prefix.casefold()):
            normalized = normalized[len(prefix) :].strip()
            lowered = normalized.casefold()
            break
    normalized = re.sub(
        r"(?i)(next(?: step)?:\s*)(next(?: step)?:\s*)+",
        lambda match: match.group(1),
        normalized,
    )
    return normalized.strip()


def _structured_view_visible_reply_needs_repair(
    text: str,
    *,
    active_view: str,
    chinese: bool,
    learner_message: str | None = None,
    current_file: dict[str, object] | None = None,
) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    if _reply_mentions_current_request_anchor(
        normalized,
        message=learner_message,
        current_file=current_file,
    ):
        return False
    if active_view == "training":
        return False
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if _structured_view_has_lane_signal(normalized, active_view=active_view, chinese=chinese):
        return False
    normalized_search = _normalize_search_text(normalized)
    stale_markers: dict[str, tuple[str, ...]] = {
        "plan": (
            "codemechanism",
            "patch",
            "branch",
            "breakage",
            "callsite",
            "signaturehelp",
            "hover",
            "debugloop",
        ),
        "resources": (
            "codemechanism",
            "patch",
            "branch",
            "breakage",
            "debugloop",
            "signaturehelp",
            "formalplan",
        ),
        "settings": (
            "patch",
            "branch",
            "breakage",
            "callsite",
            "debugloop",
            "formalplan",
        ),
    }
    if any(marker in normalized_search for marker in stale_markers.get(active_view, ())):
        return True
    # A structured-view reply does not need to repeat the view's internal
    # vocabulary to be valid.  Once the provider has returned a substantive
    # answer, preserve it; only very short acknowledgements remain eligible
    # for the local lane-recovery copy above.
    return len(normalized) <= (12 if chinese else 18)


def _reply_mentions_excerpt(reply: str, source: str) -> bool:
    excerpt = _search_excerpt(source)
    if not excerpt:
        return False
    return _normalize_search_text(excerpt) in _normalize_search_text(reply)


def _search_excerpt(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return ""
    if any("\u4e00" <= char <= "\u9fff" for char in cleaned):
        compact = "".join(
            char for char in cleaned if ("\u4e00" <= char <= "\u9fff") or char.isascii() and char.isalnum()
        )
        return compact[:12]
    words = cleaned.split(" ")
    return " ".join(words[:6])[:48]


def _is_meta_step_hint(text: str) -> bool:
    normalized = _normalize_coach_meta_candidate(text)
    if not normalized:
        return False
    lowered = normalized.casefold()
    return (
        lowered.startswith("review rhythm:")
        or lowered.startswith("current coaching focus:")
        or lowered.startswith("\u590d\u4e60\u8282\u594f\uff1a")
        or lowered.startswith("\u5f53\u524d\u805a\u7126\uff1a")
        or _looks_like_internal_coach_meta(normalized)
    )


def _build_empty_reply_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, object]:
    domain_override = _guided_domain_empty_reply_override(
        message,
        current_file=current_file,
        coach_context=coach_context,
        response_language=response_language,
    )
    summary = str(domain_override.get("summary") or "").strip() if isinstance(domain_override, dict) else ""
    next_step = str(domain_override.get("next_step") or "").strip() if isinstance(domain_override, dict) else ""
    teaching_note = (
        str(domain_override.get("teaching_note") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    if not summary:
        summary = _localized_text(
            "The provider returned an empty visible answer.",
            "provider 没有返回可见内容。",
            response_language,
        )
    if not next_step:
        next_step = _localized_text(
            "Retry with a visible conclusion.",
            "先返回一个可见结论：目标行为、当前判断，以及下一步最小可验证动作。",
            response_language,
        )
    if not teaching_note:
        teaching_note = _localized_text(
            "Keep the same lane and ask for one visible, verifiable conclusion on the next turn.",
            "继续沿着同一条教学线走，下一轮先拿回一个可见且可验证的结论。",
            response_language,
        )
    resume_thread = _agentic_resume_thread_text(
        summary,
        next_step,
        response_language=response_language,
    )
    return {
        "summary": summary,
        "next_step": next_step,
        "blocker": summary,
        "teaching_note": teaching_note,
        "resume_thread": resume_thread,
        "stop_reason": "empty_response",
        "fell_back": True,
    }


def _mode_style_label(mode: str, chinese: bool) -> str:
    if chinese:
        return {
            "guided": "我先带你把",
            "balanced": "我们先把",
            "direct": "先直接把",
        }.get(mode, "我们先把")
    return {
        "guided": "In guided mode,",
        "balanced": "In balanced mode,",
        "direct": "In direct mode,",
    }.get(mode, "In guided mode,")


def _scaffold_next_step(
    *,
    scenario: str,
    mode: str,
    learner_signal: str,
    file_path: str | None,
    weak_spots: list[str],
    next_step_hint: str,
    chinese: bool,
) -> str:
    localized_hint = _surface_context_text(next_step_hint, chinese=chinese)
    if next_step_hint and (localized_hint or not chinese):
        visible_hint = localized_hint or next_step_hint
        if chinese:
            if scenario in {"project_idea", "engineering_challenge"}:
                return f"先别把它讲成更大的计划，先做这一步：{visible_hint}"
            if scenario == "principle":
                return f"先把这个原理落成动作：{visible_hint}"
            if learner_signal == "blocked":
                return f"这一轮先只做这一个动作：{visible_hint}"
            if mode == "direct":
                return f"先直接从这一步开始：{visible_hint}"
            return f"下一步先做这个：{visible_hint}"
        return f"The next move I recommend is this: {next_step_hint}"

    scenario_step = _scenario_step_text(
        scenario=scenario,
        file_path=file_path,
        weak_spots=weak_spots,
        chinese=chinese,
    )
    mode_prefix = _mode_style_label(mode, chinese)
    if chinese:
        if learner_signal == "blocked":
            return f"先别同时做太多，只做这一步：{scenario_step}"
        if mode == "direct":
            return f"先直接从这一步开始：{scenario_step}"
        return f"{mode_prefix}{scenario_step}。"
    if learner_signal == "blocked":
        return f"{mode_prefix} do not do too much at once; start by {scenario_step}"
    return f"{mode_prefix} the highest-value next move is to {scenario_step}"


def _compose_principle_followthrough_patch(
    *,
    reply: str,
    principle_note: dict[str, object] | None,
    chinese: bool,
) -> str:
    principle_note = principle_note or {}
    if not principle_note:
        return ""

    why_it_matters = str(principle_note.get("why_it_matters") or "").strip()
    apply_now = str(principle_note.get("apply_now") or principle_note.get("follow_up_exercise") or "").strip()
    source_asset_title = str(principle_note.get("source_asset_title") or "").strip()

    needs_reason = bool(why_it_matters) and not (
        _reply_mentions_excerpt(reply, why_it_matters) or _reply_has_reason_signal(reply, chinese)
    )
    needs_apply = bool(apply_now) and not (
        _reply_mentions_excerpt(reply, apply_now) or _reply_has_action_signal(reply, chinese)
    )
    needs_source = bool(source_asset_title) and not (
        _reply_mentions_excerpt(reply, source_asset_title)
    )

    parts: list[str] = []
    if chinese:
        if needs_reason:
            parts.append(f"它在这里重要，是因为{why_it_matters}。")
        if needs_apply:
            prefix = "你现在" if apply_now.startswith("先") else "你现在先"
            parts.append(f"{prefix}{apply_now}。")
        if needs_source:
            parts.append(f"继续沿着 `{source_asset_title}` 这条解释线。")
    else:
        if needs_reason:
            parts.append(f"It matters here because {why_it_matters}.")
        if needs_apply:
            parts.append(f"Apply it now by {apply_now}.")
        if needs_source:
            parts.append(f"Stay on `{source_asset_title}` for the next explanation move.")
    return " ".join(parts).strip()


def _compose_missing_next_step_patch(
    *,
    reply: str,
    scenario: str,
    next_step_hint: str,
    file_path: str | None,
    project_entry_points: list[str],
    learner_signal: str,
    mode: str,
    chinese: bool,
    coach_context: dict[str, Any] | None = None,
) -> str:
    step = next_step_hint.strip()
    if scenario == "function_guidance":
        starter_note, starter_next_step = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=chinese,
        )
        starter = coach_context.get("function_guidance_starter") if isinstance(coach_context, dict) else None
        starter_tokens = [
            _compact_text(starter.get("call_site_path"), 120) if isinstance(starter, dict) else None,
            _compact_text(starter.get("definition_path"), 120) if isinstance(starter, dict) else None,
            _compact_text(starter.get("definition_symbol"), 48) if isinstance(starter, dict) else None,
            _compact_text(starter.get("call_site_symbol"), 48) if isinstance(starter, dict) else None,
        ]
        if any(token and token in reply for token in starter_tokens):
            return ""
        if starter_note or starter_next_step:
            step = starter_next_step.strip() or step
    if not step:
        return ""
    if _is_meta_step_hint(step):
        return ""

    if _reply_mentions_excerpt(reply, step):
        return ""
    if _reply_has_action_signal(reply, chinese) and len(reply) > 120:
        return ""

    anchored_step = _anchor_step_to_workspace(
        step,
        file_path=file_path,
        project_entry_points=project_entry_points,
        chinese=chinese,
    )
    if chinese:
        if scenario in {"project_idea", "engineering_challenge"}:
            return f"先别把它讲成更大的计划，先做这一步：{anchored_step}"
        if scenario == "principle":
            return f"先把这个原理落成动作：{anchored_step}"
        if learner_signal == "blocked":
            return f"这一轮先只做这一个动作：{anchored_step}"
        if mode == "direct":
            return f"先直接从这一步开始：{anchored_step}"
        return f"下一步先做这个：{anchored_step}"

    if scenario in {"project_idea", "engineering_challenge"}:
        return f"Do not widen this into a larger plan yet. Take this first cut: {anchored_step}"
    if scenario == "principle":
        return f"Turn the principle into action with this move: {anchored_step}"
    if learner_signal == "blocked":
        return f"For this turn, do only this next move: {anchored_step}"
    if mode == "direct":
        return f"Start directly with this step: {anchored_step}"
    return f"The next move is this: {anchored_step}"


def _anchor_step_to_workspace(
    step: str,
    *,
    file_path: str | None,
    project_entry_points: list[str],
    chinese: bool,
) -> str:
    anchor = file_path or (project_entry_points[0] if project_entry_points else "")
    if not anchor or _reply_mentions_excerpt(step, anchor):
        return step
    if chinese:
        return f"{step}，先从 `{anchor}` 开始。"
    return f"{step} Start in `{anchor}`."


def _reply_has_reason_signal(reply: str, chinese: bool) -> bool:
    markers = ["because", "this matters", "the reason", "so that", "which helps", "why this matters"]
    if chinese:
        markers.extend(["因为", "这很重要", "原因", "这样就能", "为什么这一步重要", "它在这里重要"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def _reply_has_action_signal(reply: str, chinese: bool) -> bool:
    markers = [
        "next step",
        "start by",
        "start with",
        "begin with",
        "the next move",
        "apply it now",
        "try ",
        "run ",
        "verify",
        "check ",
        "implement ",
        "patch ",
    ]
    if chinese:
        markers.extend(["下一步", "现在先", "先做", "先跑", "先改", "先补", "先验证", "先检查", "先指出", "先确认", "直接从这一步"])
    lowered = reply.casefold()
    return any(marker.casefold() in lowered for marker in markers)
