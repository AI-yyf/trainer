"""Coach reply continuity and relevance guards (§五十二: extracted from provider_service.py).

Keeps coach replies anchored to the learner's current request: strips
internal coach-meta chatter, repairs stale guided-lane summaries/next
steps, re-anchors off-topic continuity, and detects when a reply already
covers practice-verification ground.
"""

from __future__ import annotations

import re
from typing import Any

from .coaching_first_turn import (
    _first_turn_lane_continuity_note,
    _first_turn_lane_next_step,
    _fresh_lane_comparison_requested,
    _resolve_first_turn_guided_lane,
)
from .coaching_recovery import (
    _GUIDED_DOMAIN_SCENARIOS,
    _agentic_resume_thread_text,
    _build_active_view_recovery_override,
    _coaching_active_view_name,
    _localized_text,
    _prefers_chinese,
    _trim_sentence,
)
from .prompts import extract_coaching_context
from .provider.quota_copy import provider_quota_copy, provider_quota_reply
from .provider.redaction import _compact_text, redact_provider_error
from .provider.text import _contains_cjk, _visible_model_text
from .reply_continuity import visible_next_step

_INTERNAL_COACH_META_MARKERS = (
    "current coaching focus:",
    "current focus:",
    "current focus to continue:",
    "review rhythm:",
    "memory scope is",
    "preferred teaching asset:",
    "reusable teaching asset:",
    "resume the live thread around",
    "evidence to anchor on:",
    "keep the next move as",
    "keep the blocker in view:",
    "build on the verified result:",
    "carry this teaching note forward:",
    "coach confidence:",
    "useful recalled memory:",
    "relevant recalled memory:",
    "continuity evidence:",
    "this follows the teaching lane from",
    "reuse the saved teaching asset",
    "saved teaching asset",
    "\u5f53\u524d\u805a\u7126\uff1a",
    "\u5f53\u524d\u805a\u7126\u70b9\uff1a",
    "\u590d\u4e60\u8282\u594f\uff1a",
    "\u8bb0\u5fc6\u8303\u56f4\u662f",
)


_INTERNAL_COACH_META_LABELS = {
    "project implementation",
    "idea implementation guidance",
    "project idea mining",
    "existing project adaptation",
    "project adaptation",
    "principle explanation",
    "review and reflection coaching",
    "plan and review rhythm",
    "plan and review",
    "task execution coaching",
    "next task coaching",
    "next step after review",
    "general coaching",
}


_INTERNAL_COACH_META_PREFIXES = (
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
    "\u5f53\u524d\u805a\u7126\uff1a",
    "\u5f53\u524d\u805a\u7126\u70b9\uff1a",
    "\u590d\u4e60\u8282\u594f\uff1a",
)


_VISIBLE_COACH_PARAGRAPH_SPLIT_PATTERN = re.compile(r"\n\s*\n")


_VISIBLE_COACH_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?\u3002\uff01\uff1f])\s+")


def _normalize_coach_meta_candidate(text: str) -> str:
    return " ".join(text.strip().split())


def _strip_leading_coach_meta_prefix(text: str) -> str:
    normalized = _normalize_coach_meta_candidate(text)
    lowered = normalized.casefold()
    for prefix in _INTERNAL_COACH_META_PREFIXES:
        if lowered.startswith(prefix):
            return normalized[len(prefix) :].strip()
    return normalized


def _looks_like_internal_coach_meta(text: str) -> bool:
    normalized = _normalize_coach_meta_candidate(text)
    if not normalized:
        return False
    lowered = normalized.casefold()
    if any(marker in lowered for marker in _INTERNAL_COACH_META_MARKERS):
        return True
    label = lowered.strip(" -:*_#>~`[](){}")
    return label in _INTERNAL_COACH_META_LABELS


def _strip_internal_coach_meta(text: str) -> str:
    # Prose cleanup must not rewrite code: indentation, empty lines and strings
    # that happen to contain coach metadata are part of the runnable example.
    normalized_text = _visible_model_text(text)
    segments: list[str] = []
    prose: list[str] = []
    code: list[str] = []
    fence = ""
    for line in normalized_text.splitlines(keepends=True):
        match = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
        if fence:
            code.append(line)
            if (
                match
                and match.group(1)[0] == fence[0]
                and len(match.group(1)) >= len(fence)
                and not line[match.end():].strip()
            ):
                segments.append("".join(code).rstrip("\r\n"))
                code = []
                fence = ""
        elif match:
            if prose:
                segments.append(_strip_internal_coach_prose("".join(prose)))
                prose = []
            fence = match.group(1)
            code.append(line)
        else:
            prose.append(line)
    if code:
        segments.append("".join(code).rstrip("\r\n"))
    if prose:
        segments.append(_strip_internal_coach_prose("".join(prose)))
    return "\n\n".join(segment for segment in segments if segment).strip()


def _strip_internal_coach_prose(normalized_text: str) -> str:
    if not normalized_text.strip():
        return ""

    kept_paragraphs: list[str] = []
    for paragraph in _VISIBLE_COACH_PARAGRAPH_SPLIT_PATTERN.split(normalized_text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        kept_lines: list[str] = []
        for line in paragraph.splitlines():
            stripped_line = line.strip()
            if not stripped_line:
                continue
            stripped_line_without_prefix = _strip_leading_coach_meta_prefix(stripped_line)
            if (
                stripped_line_without_prefix
                and stripped_line_without_prefix != _normalize_coach_meta_candidate(stripped_line)
            ):
                stripped_line = stripped_line_without_prefix
            elif _looks_like_internal_coach_meta(stripped_line):
                continue
            kept_fragments: list[str] = []
            for fragment in _VISIBLE_COACH_SENTENCE_SPLIT_PATTERN.split(stripped_line):
                stripped_fragment = fragment.strip()
                if not stripped_fragment:
                    continue
                stripped_fragment_without_prefix = _strip_leading_coach_meta_prefix(stripped_fragment)
                if (
                    stripped_fragment_without_prefix
                    and stripped_fragment_without_prefix
                    != _normalize_coach_meta_candidate(stripped_fragment)
                ):
                    stripped_fragment = stripped_fragment_without_prefix
                elif _looks_like_internal_coach_meta(stripped_fragment):
                    continue
                kept_fragments.append(stripped_fragment)
            if not kept_fragments:
                continue
            joined = " ".join(kept_fragments)
            joined = re.sub(r"\s+([,.;:!?])", r"\1", joined).strip()
            if joined:
                kept_lines.append(joined)
        if kept_lines:
            kept_paragraphs.append("\n".join(kept_lines))

    cleaned = "\n\n".join(kept_paragraphs).strip()
    if not cleaned:
        return ""

    for prefix in _INTERNAL_COACH_META_PREFIXES:
        if cleaned.casefold().startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    return cleaned


def _agentic_practice_completion_guard(
    *,
    content: str,
    tool_events: list[dict[str, Any]],
    message: str,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, str] | None:
    # A formal-plan mutation may quote prior verified checks while outlining
    # work still to do. It does not close a practice card, and must not have
    # its successful plan-save reply replaced by a practice-verification gate.
    if isinstance(coach_context, dict) and coach_context.get("formal_plan_mutation") is True:
        return None
    if not _agentic_practice_verification_context_active(
        message=message,
        current_file=current_file,
        coach_context=coach_context,
    ):
        return None
    if not _claims_verified_practice_completion(content):
        return None
    verification_result = _current_file_practice_verification_result(tool_events)
    if isinstance(verification_result, dict) and verification_result.get("passed") is True:
        return None
    if verification_result is None and isinstance(coach_context, dict) and coach_context.get("completed_training_return_feedback") is True:
        return None

    chinese = _prefers_chinese(response_language)
    if isinstance(verification_result, dict):
        tool_summary = str(verification_result.get("summary") or "").strip()
        tool_next_step = str(verification_result.get("next_step") or "").strip()
        if chinese:
            summary = tool_summary or "\u5f53\u524d\u6587\u4ef6\u7684\u7ec3\u4e60\u9a8c\u8bc1\u8fd8\u6ca1\u901a\u8fc7\u3002"
            next_step = tool_next_step or "\u5148\u6839\u636e\u9a8c\u8bc1\u7ed3\u679c\u4fee\u8865\u5f53\u524d\u6587\u4ef6\uff0c\u7136\u540e\u518d\u9a8c\u8bc1\u4e00\u6b21\u3002"
            content = f"\u6211\u68c0\u67e5\u4e86 IDE \u91cc\u7684\u5f53\u524d\u6587\u4ef6\uff0c\u4f46\u8fd8\u4e0d\u80fd\u628a\u8fd9\u6b21\u52a8\u624b\u7ec3\u4e60\u6807\u8bb0\u4e3a\u901a\u8fc7\u3002\n\n{summary}\n\n{next_step}"
        else:
            summary = tool_summary or "Current-file practice verification did not pass."
            next_step = tool_next_step or "Patch the current file against the verification result, then verify again."
            content = (
                "I checked the active IDE file, but I cannot mark this practice as passed yet.\n\n"
                f"{summary}\n\n{next_step}"
            )
    elif chinese:
        summary = "\u8fd9\u6b21\u7ec3\u4e60\u8fd8\u6ca1\u6709\u53ef\u7528\u7684 current-file verification evidence\u3002"
        next_step = "\u6253\u5f00 implementation file\uff0c\u8fd0\u884c Verify current file\uff0c\u8ba9 Trainer \u68c0\u67e5\u6587\u4ef6\u3001diagnostics \u548c acceptance signals\u3002"
        content = (
            "\u6211\u8fd8\u4e0d\u80fd\u628a\u8fd9\u6b21\u52a8\u624b\u7ec3\u4e60\u6807\u8bb0\u4e3a\u901a\u8fc7\u3002"
            "Trainer \u8fd8\u9700\u8981\u6765\u81ea VS Code \u7684 current-file verification evidence\uff1a"
            "active file\u3001diagnostics \u548c acceptance signals\u3002\n\n"
            f"{next_step}"
        )
    else:
        summary = "Practice is not marked passed yet because current-file verification evidence is missing."
        next_step = "Open the implementation file and run Verify current file so Trainer can check the file, diagnostics, and acceptance signals."
        content = (
            "I cannot mark this hands-on practice as passed yet. The coach still needs current-file "
            "verification evidence from VS Code: the active file, diagnostics, and acceptance signals.\n\n"
            f"{next_step}"
        )
    return {
        "content": content,
        "summary": summary,
        "next_step": next_step,
        "stop_reason": "practice_verification_required",
    }


def _training_record_has_verification_clues(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    list_keys = (
        "acceptance_criteria",
        "acceptanceCriteria",
        "learner_deliverables",
        "learnerDeliverables",
        "verification_steps",
        "verificationSteps",
        "self_check",
        "selfCheck",
        "expected_symbols",
        "expectedSymbols",
        "api_hints",
        "apiHints",
    )
    for key in list_keys:
        value = record.get(key)
        if isinstance(value, list) and any(str(item or "").strip() for item in value):
            return True
    scalar_keys = (
        "training_card_id",
        "trainingCardId",
        "selected_card_id",
        "selectedCardId",
        "success_signal",
        "successSignal",
        "deliverable",
        "problem_statement",
        "problemStatement",
        "suggested_workspace_action",
        "suggestedWorkspaceAction",
    )
    for key in scalar_keys:
        if str(record.get(key) or "").strip():
            return True
    target_skill = str(record.get("target_skill") or record.get("targetSkill") or "").strip().lower()
    return bool(target_skill) and any(
        token in target_skill for token in ("practice", "current-file", "verification")
    )


def _coach_context_has_active_training_card(coach_context: dict[str, Any] | None) -> bool:
    if not isinstance(coach_context, dict):
        return False
    routing_candidates: list[Any] = [
        coach_context.get("active_training_card_routing"),
        coach_context.get("activeTrainingCardRouting"),
    ]
    memory = coach_context.get("memory")
    if isinstance(memory, dict):
        routing_candidates.extend(
            [
                memory.get("active_training_card_routing"),
                memory.get("activeTrainingCardRouting"),
            ]
        )
    for routing in routing_candidates:
        if not isinstance(routing, dict):
            continue
        selected_card = routing.get("selected_card") or routing.get("selectedCard")
        if _training_record_has_verification_clues(selected_card):
            return True
        if str(routing.get("selected_card_id") or routing.get("selectedCardId") or "").strip():
            return True
    return False


def _current_file_has_training_context(current_file: dict[str, object] | None) -> bool:
    if not isinstance(current_file, dict):
        return False
    if _training_record_has_verification_clues(current_file):
        return True
    return any(
        str(current_file.get(key) or "").strip().lower() == "training"
        for key in ("evaluation_source", "source", "mode")
    )


def _current_file_has_visible_content(current_file: dict[str, object] | None) -> bool:
    if not isinstance(current_file, dict):
        return False
    return any(
        str(current_file.get(key) or "").strip()
        for key in ("path", "content", "content_excerpt")
    )


def _agentic_practice_verification_context_active(
    *,
    message: str,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> bool:
    context = extract_coaching_context(message, current_file, coach_context)
    if isinstance(context.get("exercise_prompt"), dict):
        return True

    coaching_state = context.get("coaching_state")
    if isinstance(coaching_state, dict):
        teaching_mode = str(coaching_state.get("teaching_mode") or "").strip().lower()
        if teaching_mode == "practice":
            return True

    if _current_file_has_training_context(current_file):
        return True

    practice_focus_text = " ".join(
        str(value or "")
        for value in (
            message,
            context.get("summary"),
            context.get("current_focus"),
            context.get("next_step_hint"),
        )
    )
    practice_terms_present = _text_has_practice_verification_terms(practice_focus_text)
    if not practice_terms_present:
        return False

    if _current_file_has_visible_content(current_file):
        return True
    if _coach_context_has_active_training_card(coach_context):
        return True
    return False


def _text_has_practice_verification_terms(text: str) -> bool:
    lowered = text.lower()
    return any(
        term in lowered
        for term in (
            "practice",
            "training card",
            "hands-on",
            "acceptance",
            "练习",
            "训练卡片",
            "验收",
        )
    )


def _claims_verified_practice_completion(content: str) -> bool:
    lowered = content.lower()
    if any(
        phrase in lowered
        for phrase in (
            "not passed",
            "did not pass",
            "does not pass",
            "not verified",
            "cannot mark",
            "can't mark",
            "needs review",
            "need current-file",
            "needs current-file",
            "missing current-file",
            "\u8fd8\u6ca1\u901a\u8fc7",
            "\u4e0d\u80fd\u6807\u8bb0\u4e3a\u901a\u8fc7",
            "\u7f3a\u5c11 current-file",
            "verification evidence",
        )
    ):
        return False
    return any(
        phrase in lowered
        for phrase in (
            "practice passed",
            "you passed",
            "verification passed",
            "practice is verified",
            "verified from the current file",
            "verified by current-file evidence",
            "this passes",
            "meets the acceptance",
            "mark it complete",
            "mark this complete",
            "ready to mark complete",
            "passed the practice",
            "\u5df2\u901a\u8fc7",
            "\u9a8c\u8bc1\u5df2\u901a\u8fc7",
            "\u53ef\u4ee5\u6807\u8bb0\u5b8c\u6210",
        )
    )


def _current_file_practice_verification_result(tool_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in tool_events:
        if str(event.get("type") or "") != "tool_result":
            continue
        if str(event.get("name") or "") != "verify_practice_current_file":
            continue
        result = event.get("result")
        if isinstance(result, dict):
            return result
    return None


def _agentic_fallback_continuity(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> tuple[str, str]:
    context = extract_coaching_context(message, current_file, coach_context)
    chinese = _prefers_chinese(response_language)
    summary = str(
        context.get("thread_summary")
        or context.get("summary")
        or context.get("current_focus")
        or context.get("continuity_summary")
        or context.get("review_queue_summary")
        or ""
    ).strip()
    if not summary:
        summary = (
            "This turn needs a fresh provider retry, but the same thread can continue."
            if not chinese
            else "这轮需要重新连接模型服务，但同一条对话可以继续。"
        )

    scenario = str(context.get("scenario") or "general").strip()
    next_step_hint = _prefer_structured_next_step(
        scenario=scenario,
        next_step_hint=_extract_next_step_hint_text(
            context.get("thread_next_step") or context.get("resume_hint") or context.get("next_step_hint")
        ),
        implementation_guide=context.get("implementation_guide") if isinstance(context.get("implementation_guide"), dict) else {},
        adaptation_guide=context.get("project_adaptation_guide") if isinstance(context.get("project_adaptation_guide"), dict) else context.get("adaptation_guide") if isinstance(context.get("adaptation_guide"), dict) else {},
        principle_note=context.get("principle_notes") if isinstance(context.get("principle_notes"), dict) else context.get("principle_note") if isinstance(context.get("principle_note"), dict) else {},
        project_ideas=[item for item in context.get("project_ideas", []) if isinstance(item, dict)] if isinstance(context.get("project_ideas"), list) else [],
        exercise_prompt=context.get("exercise_prompt") if isinstance(context.get("exercise_prompt"), dict) else {},
    )
    next_step = str(
        next_step_hint
        or context.get("thread_next_step")
        or context.get("resume_hint")
        or context.get("next_step")
        or context.get("continuity_summary")
        or context.get("review_queue_summary")
        or ""
    ).strip()
    if not next_step:
        next_step = (
            "Retry from the smallest verified step after checking the provider connection."
            if not chinese
            else "检查模型服务后，从上一次已验证的最小步骤继续。"
        )
    return summary, next_step


def _agentic_completion_continuity(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
    content: str,
) -> tuple[str, str]:
    context = extract_coaching_context(message, current_file, coach_context)
    chinese = _prefers_chinese(response_language)

    summary_candidates: list[Any] = [
        context.get("thread_summary"),
        context.get("summary"),
        context.get("current_focus"),
        context.get("continuity_summary"),
        context.get("review_queue_summary"),
        context.get("project_summary"),
    ]
    active_thread = context.get("active_thread")
    if isinstance(active_thread, dict):
        summary_candidates.extend(
            [
                active_thread.get("summary"),
                active_thread.get("focus_area"),
                active_thread.get("verified_result"),
            ]
        )
    exercise_prompt = context.get("exercise_prompt")
    if isinstance(exercise_prompt, dict):
        summary_candidates.extend(
            [
                exercise_prompt.get("summary"),
                exercise_prompt.get("prompt"),
                exercise_prompt.get("success_signal"),
            ]
        )
    implementation_guide = context.get("implementation_guide")
    if isinstance(implementation_guide, dict):
        summary_candidates.extend(
            [
                implementation_guide.get("current_step"),
                implementation_guide.get("scope_boundary"),
            ]
        )

    summary = next(
        (
            text
            for text in (_compact_text(candidate, 140) for candidate in summary_candidates)
            if text
        ),
        "",
    )
    if not summary:
        summary = _trim_sentence(content, 140)
    if not summary:
        summary = (
            "This turn is complete; keep the same coaching thread moving."
            if not chinese
            else "\u8fd9\u4e00\u8f6e\u5df2\u7ecf\u6536\u675f\uff0c\u4fdd\u6301\u540c\u4e00\u6761\u6559\u7ec3\u7ebf\u7a0b\u7ee7\u7eed\u5f80\u524d\u8d70\u3002"
        )

    next_step = visible_next_step(content) or _prefer_structured_next_step(
        scenario=str(context.get("scenario") or "general").strip(),
        next_step_hint=_extract_next_step_hint_text(
            context.get("thread_next_step") or context.get("resume_hint") or context.get("next_step_hint")
        ),
        implementation_guide=implementation_guide if isinstance(implementation_guide, dict) else {},
        adaptation_guide=context.get("project_adaptation_guide")
        if isinstance(context.get("project_adaptation_guide"), dict)
        else context.get("adaptation_guide")
        if isinstance(context.get("adaptation_guide"), dict)
        else {},
        principle_note=context.get("principle_notes")
        if isinstance(context.get("principle_notes"), dict)
        else context.get("principle_note")
        if isinstance(context.get("principle_note"), dict)
        else {},
        project_ideas=[item for item in context.get("project_ideas", []) if isinstance(item, dict)]
        if isinstance(context.get("project_ideas"), list)
        else [],
        exercise_prompt=exercise_prompt if isinstance(exercise_prompt, dict) else {},
    )
    if not next_step and isinstance(active_thread, dict):
        for candidate_key in ("next_step", "blocker", "verified_result"):
            text = _compact_text(active_thread.get(candidate_key), 120)
            if text:
                next_step = text
                break
    if not next_step:
        next_step = _compact_text(context.get("thread_next_step"), 120) or ""
    if not next_step:
        next_step = _compact_text(context.get("resume_hint"), 120) or ""
    if not next_step:
        next_step = _trim_sentence(content, 120)
    if not next_step:
        next_step = (
            "Continue from the same thread and verify the smallest concrete result."
            if not chinese
            else "\u6cbf\u7740\u540c\u4e00\u6761\u7ebf\u7a0b\u7ee7\u7eed\uff0c\u5148\u9a8c\u8bc1\u6700\u5c0f\u7684\u5177\u4f53\u7ed3\u679c\u3002"
        )

    resolved_scenario = _resolve_first_turn_guided_lane(
        scenario=str(context.get("scenario") or "").strip(),
        learner_message=message,
        reply=content,
    )
    if resolved_scenario in _GUIDED_DOMAIN_SCENARIOS:
        if _looks_like_generic_guided_review_fallback(summary):
            repaired_summary = _first_turn_lane_continuity_note(
                resolved_scenario,
                chinese=chinese,
                coach_context=context,
            )
            if repaired_summary:
                summary = repaired_summary
        if _looks_like_generic_guided_review_fallback(next_step):
            repaired_next_step = _first_turn_lane_next_step(
                resolved_scenario,
                chinese=chinese,
                coach_context=context,
            )
            if repaired_next_step:
                next_step = repaired_next_step

    return summary, next_step


def _stream_holdback_chars(response_language: str | None) -> int:
    """Keep a shorter Chinese tail in reserve so real deltas appear sooner."""

    return 24 if _prefers_chinese(response_language) else 32


def _prefer_structured_next_step(
    *,
    scenario: str,
    next_step_hint: str,
    implementation_guide: dict[str, object] | None,
    adaptation_guide: dict[str, object] | None,
    principle_note: dict[str, object] | None,
    project_ideas: list[dict[str, object]],
    exercise_prompt: dict[str, object] | None,
) -> str:
    implementation_guide = implementation_guide or {}
    adaptation_guide = adaptation_guide or {}
    principle_note = principle_note or {}
    exercise_prompt = exercise_prompt or {}
    if scenario == "principle":
        value = principle_note.get("follow_up_exercise") or principle_note.get("apply_now")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if next_step_hint:
        return next_step_hint
    value = exercise_prompt.get("prompt")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if scenario == "idea_implementation":
        value = implementation_guide.get("current_step")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if scenario == "project_adaptation":
        value = adaptation_guide.get("first_migration_step")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if scenario == "project_idea" and project_ideas:
        value = project_ideas[0].get("first_step")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_next_step_hint_text(value: object | None) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("title", "label", "next_step", "nextStep", "summary"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


def _fresh_lane_marker_map(*, chinese: bool) -> dict[str, tuple[str, ...]]:
    # Ordinary code words (function, container, debugging, migration) are not
    # enough to establish a foreign workflow. Only specific lane signals may
    # remove model content or replace its continuity.
    lane_markers: dict[str, tuple[str, ...]] = {
        "remote_workspace": (
            "remote lane",
            "remote workspace",
            "remote workflow",
            "ssh",
            "tunnels",
            "devcontainer",
            "dev container",
            "wsl",
            "credential mode",
        ),
        "debug_loop": (
            "debug loop",
            "breakpoint",
            "launch.json",
            "call stack",
            "stack frame",
            "watch value",
        ),
        "function_guidance": (
            "function-guidance lane",
            "function contract",
            "live call site",
            "signature help",
            "go to definition",
        ),
        "project_adaptation": (
            "existing-project lane",
            "adaptation lane",
            "must stay stable",
            "must change",
        ),
    }
    if chinese:
        lane_markers["remote_workspace"] += (
            "\u8fdc\u7a0b",
            "\u8fdc\u7a0b\u5de5\u4f5c\u533a",
            "\u8fdc\u7a0b\u8fb9\u754c",
            "\u8fdc\u7a0b ssh",
            "\u5f00\u53d1\u5bb9\u5668",
            "\u96a7\u9053",
            "\u51ed\u636e\u6a21\u5f0f",
        )
        lane_markers["debug_loop"] += (
            "\u8c03\u8bd5\u95ed\u73af",
            "\u8c03\u7528\u6808",
            "\u5355\u6b65",
        )
        lane_markers["function_guidance"] += (
            "\u51fd\u6570\u5951\u7ea6",
            "\u8c03\u7528\u70b9",
            "\u8c03\u7528\u4f4d\u7f6e",
            "\u7b7e\u540d\u63d0\u793a",
            "\u67e5\u770b\u5b9a\u4e49",
        )
        lane_markers["project_adaptation"] += ("\u73b0\u6709\u9879\u76ee\u6539\u9020", "\u9879\u76ee\u8fc1\u79fb")
    return lane_markers


def _strip_fresh_lane_cross_lane_carryover(
    reply: str,
    *,
    scenario: str,
    learner_message: str,
    chinese: bool,
) -> str:
    if not reply.strip() or _fresh_lane_comparison_requested(learner_message):
        return reply

    lane_markers: dict[str, tuple[str, ...]] = {
        "remote_workspace": (
            "remote lane",
            "remote workspace",
            "remote workflow",
            "ssh",
            "tunnels",
            "devcontainer",
            "dev container",
            "container",
            "wsl",
            "credential mode",
        ),
        "debug_loop": (
            "debug loop",
            "breakpoint",
            "launch.json",
            "call stack",
            "stack frame",
            "watch value",
        ),
        "function_guidance": (
            "function-guidance lane",
            "function contract",
            "live call site",
            "call site",
            "signature help",
            "go to definition",
        ),
        "project_adaptation": (
            "existing-project lane",
            "adaptation lane",
            "must stay stable",
            "must change",
        ),
    }
    if chinese:
        lane_markers["remote_workspace"] += (
            "远程",
            "远程工作区",
            "远程边界",
            "远程 ssh",
            "容器",
            "开发容器",
            "隧道",
            "凭据模式",
        )
        lane_markers["debug_loop"] += (
            "调试",
            "断点",
            "调用栈",
            "单步",
            "变量值",
        )
        lane_markers["function_guidance"] += (
            "函数",
            "函数契约",
            "调用点",
            "调用位置",
            "签名提示",
            "查看定义",
        )
        lane_markers["project_adaptation"] += ("改造", "迁移", "适配")

    lane_markers = _fresh_lane_marker_map(chinese=chinese)

    bridge_markers = (
        "already were",
        "previous",
        "earlier",
        "same lane",
        "same line",
        "we were with",
        "coming out of",
        "fits where we already were",
        "keep circling",
        "keep circling back",
        "circling back",
        "keep coming back to",
        "from the debug loop",
        "from the remote lane",
        "沿着上一条",
        "上一条",
        "前一条",
        "刚才那条",
    )
    other_lane_markers = [
        marker
        for lane, markers in lane_markers.items()
        if lane != scenario
        for marker in markers
    ]
    if not other_lane_markers:
        return reply

    paragraphs = [part.strip() for part in reply.split("\n\n") if part.strip()]
    filtered: list[str] = []
    removed = False
    for part in paragraphs:
        lowered = part.casefold()
        mentions_other_lane = any(marker.casefold() in lowered for marker in other_lane_markers)
        has_bridge_cue = any(marker.casefold() in lowered for marker in bridge_markers)
        if mentions_other_lane and has_bridge_cue:
            removed = True
            continue
        filtered.append(part)

    if removed and filtered:
        reply = "\n\n".join(filtered).strip()
    elif removed:
        return reply

    sentence_filtered: list[str] = []
    sentence_removed = False
    for part in filtered:
        if "```" in part:
            sentence_filtered.append(part)
            continue
        kept_sentences: list[str] = []
        sentences = re.split(r"(?<=[.!?。！？])(?:\s+|(?=[^\s]))", part)
        for sentence in sentences:
            normalized = sentence.strip()
            if not normalized:
                continue
            lowered = normalized.casefold()
            mentions_other_lane = any(marker.casefold() in lowered for marker in other_lane_markers)
            if mentions_other_lane:
                sentence_removed = True
                continue
            kept_sentences.append(normalized)
        if kept_sentences:
            joiner = "" if chinese else " "
            sentence_filtered.append(joiner.join(kept_sentences).strip())

    if sentence_removed and sentence_filtered:
        return "\n\n".join(sentence_filtered).strip()
    return reply


def _sanitize_agentic_continuity_text(
    value: str,
    *,
    scenario: str,
    learner_message: str,
    chinese: bool,
    history_mode: str,
    field_kind: str = "summary",
    response_language: str | None = None,
    coach_context: dict[str, Any] | None = None,
    current_file: dict[str, object] | None = None,
) -> str:
    if field_kind == "resume_thread":
        text = _visible_model_text(value).strip()
    else:
        text = _strip_internal_coach_meta(value).strip()
    if not text:
        return text
    if _reply_needs_current_request_reanchor(
        text,
        message=learner_message,
        current_file=current_file,
        coach_context=coach_context,
    ):
        repaired = _reanchor_agentic_continuity_to_current_request(
            field_kind=field_kind,
            message=learner_message,
            current_file=current_file,
            response_language=response_language,
        )
        if repaired:
            return repaired
    if history_mode == "fresh_lane":
        text = _strip_fresh_lane_cross_lane_carryover(
            text,
            scenario=scenario,
            learner_message=learner_message,
            chinese=chinese,
        )
    resolved_scenario = _resolve_first_turn_guided_lane(
        scenario=scenario,
        learner_message=learner_message,
        reply=text,
    )
    active_view = _coaching_active_view_name(coach_context)
    active_view_override = (
        _build_active_view_recovery_override(
            active_view=active_view,
            response_language=response_language,
            reason="reanchor",
        )
        if active_view
        else None
    )
    if isinstance(active_view_override, dict):
        if field_kind == "summary" and _structured_view_summary_needs_repair(
            text,
            active_view=active_view,
            chinese=chinese,
            learner_message=learner_message,
            current_file=current_file,
        ):
            override_summary = str(active_view_override.get("summary") or "").strip()
            if override_summary:
                return override_summary
        if field_kind == "next_step" and _structured_view_next_step_needs_repair(
            text,
            active_view=active_view,
            chinese=chinese,
            learner_message=learner_message,
            current_file=current_file,
        ):
            override_next_step = str(active_view_override.get("next_step") or "").strip()
            if override_next_step:
                return override_next_step
    if field_kind == "summary" and resolved_scenario in _GUIDED_DOMAIN_SCENARIOS:
        repaired_summary = _first_turn_lane_continuity_note(
            resolved_scenario,
            chinese=chinese,
            coach_context=coach_context,
        )
        if repaired_summary and _guided_lane_summary_needs_repair(
            text,
            scenario=resolved_scenario,
            chinese=chinese,
        ):
            text = repaired_summary
    if field_kind == "next_step" and resolved_scenario in _GUIDED_DOMAIN_SCENARIOS:
        repaired_next_step = _first_turn_lane_next_step(
            resolved_scenario,
            chinese=chinese,
            coach_context=coach_context,
        )
        if repaired_next_step and _guided_lane_next_step_needs_repair(
            text,
            scenario=resolved_scenario,
            chinese=chinese,
        ):
            text = repaired_next_step
    if _looks_like_generic_guided_review_fallback(text):
        if resolved_scenario in _GUIDED_DOMAIN_SCENARIOS:
            repaired_summary = _first_turn_lane_continuity_note(
                resolved_scenario,
                chinese=chinese,
                coach_context=coach_context,
            )
            repaired_next_step = _first_turn_lane_next_step(
                resolved_scenario,
                chinese=chinese,
                coach_context=coach_context,
            )
            if field_kind == "next_step" and repaired_next_step:
                text = repaired_next_step
            elif field_kind == "resume_thread" and (repaired_summary or repaired_next_step):
                text = _agentic_resume_thread_text(
                    repaired_summary,
                    repaired_next_step,
                    response_language=response_language or ("zh-CN" if chinese else "en-US"),
                )
            elif repaired_summary:
                text = repaired_summary
    return text


def _looks_like_generic_guided_review_fallback(text: str) -> bool:
    normalized = " ".join(text.split()).strip().casefold()
    if not normalized:
        return False
    generic_fallbacks = (
        "ignore secondary issues and only name the first fix plus one verification.",
        "ignore secondary issues and only describe the first fix plus one verification.",
    )
    return any(fragment in normalized for fragment in generic_fallbacks)


def _reply_has_guided_lane_signal(reply: str, scenario: str, chinese: bool) -> bool:
    if not reply.strip():
        return False

    lowered = reply.casefold()
    english_markers: dict[str, tuple[str, ...]] = {
        "remote_workspace": (
            "vs code remote lane",
            "workspace boundary",
            "credential mode",
            "files actually live",
            "credential move",
        ),
        "debug_loop": (
            "trustworthy debug loop",
            "breakpoint",
            "state change",
            "pause at the first",
            "single value",
        ),
        "function_guidance": (
            "live call site",
            "signature help",
            "function contract",
            "hover",
            "go to definition",
        ),
        "project_adaptation": (
            "existing-project lane",
            "must stay stable",
            "must change",
            "narrow adaptation",
        ),
    }
    chinese_markers: dict[str, tuple[str, ...]] = {
        "remote_workspace": (
            "VS Code remote",
            "工作区边界",
            "credential mode",
            "API key",
            "文件实际在哪台机器",
        ),
        "debug_loop": (
            "debug loop",
            "断点",
            "state change",
            "调用栈",
            "stack frame",
        ),
        "function_guidance": (
            "live call site",
            "signature help",
            "function contract",
            "hover",
            "definition",
        ),
        "project_adaptation": (
            "project adaptation",
            "必须稳定",
            "必须改变",
            "适配",
            "边界",
        ),
    }
    markers = english_markers.get(scenario, ())
    if chinese:
        markers = markers + chinese_markers.get(scenario, ())
    return any(marker.casefold() in lowered for marker in markers)


def _guided_lane_summary_needs_repair(text: str, *, scenario: str, chinese: bool) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    lowered = normalized.casefold()
    if lowered.startswith("next step:") or lowered.startswith("next:"):
        return True
    if normalized.startswith(("下一步：", "下一步:")):
        return True
    ascii_tokens = re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", normalized)
    if ascii_tokens and len(ascii_tokens) <= 5:
        return True
    if not _reply_has_guided_lane_signal(normalized, scenario, chinese):
        return True
    if ascii_tokens and len(ascii_tokens) <= 8 and not any(char in normalized for char in ".!?。！？"):
        return True
    return len(normalized) <= (8 if chinese else 14)


def _guided_lane_next_step_needs_repair(text: str, *, scenario: str, chinese: bool) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return True
    normalized_search = _normalize_search_text(normalized)
    if scenario == "function_guidance":
        if "functionnameandonecallsiteyoucanopenrightnow" in normalized_search:
            return True
        if "给我函数名和一个你现在就能打开的callsite" in normalized_search:
            return True
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if chinese and not any("\u4e00" <= char <= "\u9fff" for char in normalized):
        return True
    if len(normalized) > 110:
        return True
    if normalized.count("。") + normalized.count(". ") + normalized.count("! ") + normalized.count("? ") >= 2:
        return True
    return False


def _structured_view_lane_markers(*, active_view: str, chinese: bool) -> tuple[str, ...]:
    english_markers: dict[str, tuple[str, ...]] = {
        "plan": (
            "planlane",
            "formalplan",
            "currentstage",
            "whynow",
            "verifymethod",
            "evidence",
            "blocker",
        ),
        "resources": (
            "resourceslane",
            "resourcelane",
            "resource",
            "sandbox",
            "library",
            "folder",
            "file",
            "sources",
            "knowledge",
            "cards",
            "download",
            "organize",
        ),
        "training": (
            "traininglane",
            "learn",
            "try",
            "verify",
            "reflect",
            "return",
            "currentcard",
            "card",
            "answer",
            "deliverable",
            "whynow",
        ),
        "settings": (
            "settingslane",
            "settings",
            "provider",
            "model",
            "protocol",
            "runtime",
            "apikey",
            "connection",
        ),
    }
    chinese_markers: dict[str, tuple[str, ...]] = {
        "plan": ("plan视图", "正式计划", "当前阶段", "whynow", "verifymethod", "证据", "阻塞"),
        "resources": ("resources视图", "资料库", "资源", "沙箱", "目录", "文件", "sources", "knowledge", "cards"),
        "training": ("training视图", "训练", "学习", "单卡", "作答", "验证", "复盘", "回流", "whynow"),
        "settings": ("settings视图", "设置", "provider", "model", "protocol", "runtime", "apikey"),
    }
    markers = english_markers.get(active_view, ())
    if chinese:
        markers = markers + chinese_markers.get(active_view, ())
    return markers


def _structured_view_has_lane_signal(text: str, *, active_view: str, chinese: bool) -> bool:
    normalized = _normalize_search_text(text)
    if not normalized:
        return False
    return any(
        marker in normalized
        for marker in _structured_view_lane_markers(active_view=active_view, chinese=chinese)
    )


def _structured_view_summary_needs_repair(
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
    lowered = normalized.casefold()
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if lowered.startswith("next step:") or lowered.startswith("next:"):
        return True
    if normalized.startswith(("下一步：", "下一步:")):
        return True
    if not _structured_view_has_lane_signal(normalized, active_view=active_view, chinese=chinese):
        return True
    return len(normalized) <= (10 if chinese else 18)


def _structured_view_next_step_needs_repair(
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
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if not _structured_view_has_lane_signal(normalized, active_view=active_view, chinese=chinese):
        return True
    return len(normalized) <= (10 if chinese else 18)


def _normalize_search_text(text: str) -> str:
    return "".join(
        char.casefold()
        for char in text
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    )


_REQUEST_ANCHOR_CODE_PATTERN = re.compile(r"`([^`\n]{2,80})`")


_REQUEST_ANCHOR_QUOTED_PATTERN = re.compile(r"[\"']([^\"'\n]{2,80})[\"']")


_REQUEST_ANCHOR_IDENTIFIER_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_./-]{1,}\b")


_REQUEST_ANCHOR_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]{2,}")


_REQUEST_ANCHOR_STOP_WORDS = frozenset(
    {
        "about",
        "answer",
        "because",
        "current",
        "directly",
        "does",
        "explain",
        "file",
        "help",
        "issue",
        "please",
        "problem",
        "question",
        "return",
        "returns",
        "step",
        "that",
        "the",
        "this",
        "typescript",
        "javascript",
        "python",
        "fastapi",
        "trainer",
        "what",
        "when",
        "why",
        "with",
    }
)


_STALE_VISIBLE_REPLY_MARKERS = (
    "current lane:",
    "i will keep this turn inside",
    "keep the work alive inside",
    "resume the live thread",
    "which lane is closest",
    "stay inside the formal plan lane",
    "stay inside the resource lane",
    "stay inside the configuration lane",
    "ignore secondary issues and only",
    "\u5f53\u524d\u5148\u7559\u5728",
    "\u8fd9\u4e00\u8f6e\u6211\u5148\u5728",
    "\u56de\u5230\u540c\u4e00\u6761\u6559\u7ec3\u7ebf\u7a0b",
    "\u8bf7\u544a\u8bc9\u6211\u73b0\u5728\u6700\u63a5\u8fd1\u54ea\u6761\u7ebf",
    "\u5148\u7559\u5728\u6b63\u5f0f\u8ba1\u5212",
    "\u5148\u7559\u5728\u8d44\u6599\u5e93",
    "\u5148\u7559\u5728\u914d\u7f6e",
)


_GENERIC_COMPLETION_MARKERS = (
    "next step",
    "continue",
    "completed",
    "keep going",
    "\u4e0b\u4e00\u6b65",
    "\u7ee7\u7eed",
    "\u5b8c\u6210",
)


def _clean_request_anchor_candidate(value: object | None) -> str:
    candidate = " ".join(str(value or "").split()).strip(" `\"'")
    if not candidate:
        return ""
    return candidate[:80]


def _request_relevance_anchor_terms(
    message: str | None,
    *,
    current_file: dict[str, object] | None = None,
) -> list[str]:
    """Extract user-visible nouns that a recovery reply can safely keep in view."""
    source = str(message or "")
    if not source.strip():
        return []

    candidates: list[str] = []
    candidates.extend(match.group(1) for match in _REQUEST_ANCHOR_CODE_PATTERN.finditer(source))
    candidates.extend(match.group(1) for match in _REQUEST_ANCHOR_QUOTED_PATTERN.finditer(source))
    has_explicit_subject = bool(candidates)
    for token_match in _REQUEST_ANCHOR_IDENTIFIER_PATTERN.finditer(source):
        token = token_match.group(0).strip()
        lowered = token.casefold()
        looks_specific = (
            bool(re.search(r"[a-z][A-Z]", token))
            or "_" in token
            or "." in token
            or "/" in token
            or "-" in token
        )
        if looks_specific and lowered not in _REQUEST_ANCHOR_STOP_WORDS:
            candidates.append(token)
            has_explicit_subject = True

    if has_explicit_subject:
        for cjk_match in _REQUEST_ANCHOR_CJK_PATTERN.finditer(source):
            phrase = cjk_match.group(0)
            phrase = re.sub(
                r"^(?:\u8bf7|\u5e2e\u6211|\u8bf7\u95ee|\u4e3a\u4ec0\u4e48|\u600e\u4e48|\u5982\u4f55|"
                r"\u89e3\u91ca|\u544a\u8bc9\u6211|\u9047\u5230|\u5173\u4e8e|\u5f53\u524d|\u8fd9\u4e2a|\u73b0\u5728)+",
                "",
                phrase,
            )
            if len(phrase) >= 2:
                candidates.append(phrase[:12])

    normalized_source = source.casefold()
    references_current_file = any(
        marker in normalized_source
        for marker in ("current file", "this file", "\u5f53\u524d\u6587\u4ef6", "\u8fd9\u4e2a\u6587\u4ef6", "\u5f53\u524d\u4ee3\u7801")
    )
    if isinstance(current_file, dict) and (has_explicit_subject or references_current_file):
        raw_path = _clean_request_anchor_candidate(current_file.get("path"))
        if raw_path:
            candidates.append(raw_path.replace("\\", "/").rsplit("/", 1)[-1])
        selection = _clean_request_anchor_candidate(current_file.get("selection_text"))
        if selection:
            candidates.extend(
                match.group(0)
                for match in _REQUEST_ANCHOR_IDENTIFIER_PATTERN.finditer(selection)
                if (
                    any(char.isupper() for char in match.group(0))
                    or "_" in match.group(0)
                    or len(match.group(0)) >= 8
                )
            )

    terms: list[str] = []
    seen: set[str] = set()
    for raw_candidate in candidates:
        candidate = _clean_request_anchor_candidate(raw_candidate)
        normalized = _normalize_search_text(candidate)
        if not normalized or normalized in seen:
            continue
        ascii_count = sum(char.isascii() and char.isalnum() for char in candidate)
        cjk_count = sum("\u3400" <= char <= "\u9fff" for char in candidate)
        if ascii_count < 3 and cjk_count < 2:
            continue
        seen.add(normalized)
        terms.append(candidate)
        if len(terms) >= 5:
            break
    return terms


def _reply_mentions_current_request_anchor(
    reply: str,
    *,
    message: str | None,
    current_file: dict[str, object] | None = None,
) -> bool:
    normalized_reply = _normalize_search_text(reply)
    if not normalized_reply:
        return False
    if any(
        (normalized_term := _normalize_search_text(term)) and normalized_term in normalized_reply
        for term in _request_relevance_anchor_terms(message, current_file=current_file)
    ):
        return True
    # A traceback often gives only a filename and exception type. A useful
    # explanation can instead name a symbol from the supplied code. Do not
    # demand that it repeat those incidental traceback labels.
    content = str((current_file or {}).get("content") or "")[:64_000]
    declarations = re.finditer(
        r"\b(?:def|class|function|const|let|var)\s+([A-Za-z_$][\w$]*)"
        r"|(?m:^[ \t]*([A-Za-z_]\w*)[ \t]*=(?!=))",
        content,
    )
    return any(
        re.search(r"(?<![\w$])" + re.escape(match.group(1) or match.group(2)) + r"(?![\w$])", reply)
        is not None
        for match in declarations
    )


def _reply_mentions_unrequested_lane(reply: str, *, message: str | None) -> bool:
    normalized_reply = _normalize_search_text(reply)
    normalized_request = _normalize_search_text(str(message or ""))
    if not normalized_reply or not normalized_request:
        return False
    for markers in _fresh_lane_marker_map(chinese=True).values():
        normalized_markers = [
            _normalize_search_text(marker)
            for marker in markers
            if _normalize_search_text(marker)
        ]
        if any(marker in normalized_reply for marker in normalized_markers) and not any(
            marker in normalized_request for marker in normalized_markers
        ):
            return True
    return False


def _reply_needs_current_request_reanchor(
    reply: str,
    *,
    message: str | None,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> bool:
    resolved_guided_scenario = _resolve_first_turn_guided_lane(
        scenario=str((coach_context or {}).get("scenario") or "").strip(),
        learner_message=str(message or ""),
        reply="",
    )
    if resolved_guided_scenario in _GUIDED_DOMAIN_SCENARIOS:
        return False
    if not _request_relevance_anchor_terms(message, current_file=current_file):
        return False
    if _reply_mentions_current_request_anchor(
        reply,
        message=message,
        current_file=current_file,
    ):
        return False

    normalized = " ".join(reply.split()).strip().casefold()
    if not normalized:
        return False
    if _looks_like_generic_guided_review_fallback(normalized):
        return True
    if any(marker.casefold() in normalized for marker in _STALE_VISIBLE_REPLY_MARKERS):
        return True
    if _reply_mentions_unrequested_lane(reply, message=message):
        return True

    active_view = _coaching_active_view_name(coach_context)
    if active_view:
        chinese = _contains_cjk(reply) or _contains_cjk(str(message or ""))
        reply_has_active_view_signal = _structured_view_has_lane_signal(
            reply,
            active_view=active_view,
            chinese=chinese,
        )
        request_has_active_view_signal = _structured_view_has_lane_signal(
            str(message or ""),
            active_view=active_view,
            chinese=chinese,
        )
        if reply_has_active_view_signal and not request_has_active_view_signal:
            return True
    return len(normalized) <= 160 and any(
        marker in normalized for marker in _GENERIC_COMPLETION_MARKERS
    )


def _format_request_anchor(term: str) -> str:
    cleaned = _clean_request_anchor_candidate(term)
    if not cleaned:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_./-]+", cleaned):
        return f"`{cleaned}`"
    return f"\u300c{cleaned}\u300d"


def _current_request_anchor_label(
    message: str | None,
    *,
    current_file: dict[str, object] | None,
) -> str:
    terms = _request_relevance_anchor_terms(message, current_file=current_file)
    formatted = [_format_request_anchor(term) for term in terms[:2]]
    return "\u3001".join(term for term in formatted if term)


def _relevance_reanchor_next_step(
    *,
    message: str | None,
    current_file: dict[str, object] | None,
    response_language: str | None,
) -> str:
    anchor = _current_request_anchor_label(message, current_file=current_file)
    path = ""
    if isinstance(current_file, dict):
        path = _clean_request_anchor_candidate(current_file.get("path"))
        if path:
            path = path.replace("\\", "/").rsplit("/", 1)[-1]
    if _prefers_chinese(response_language):
        if path:
            return (
                f"\u4e0b\u4e00\u6b65\uff1a\u56f4\u7ed5 {anchor} \uff0c\u5148\u5728 `{path}` \u91cc\u67e5\u770b\u4e0e\u8fd9\u4e2a\u95ee\u9898\u76f4\u63a5\u76f8\u8fde\u7684"
                "\u8f93\u5165\u3001\u5206\u652f\u6216\u8c03\u7528\uff0c\u5e26\u56de\u7b2c\u4e00\u6761\u5b9e\u9645\u8f93\u51fa\u6216\u62a5\u9519\u3002"
            )
        return f"\u4e0b\u4e00\u6b65\uff1a\u56f4\u7ed5 {anchor} \u5e26\u56de\u6700\u5c0f\u7684\u4ee3\u7801\u7247\u6bb5\u3001\u8f93\u5165\u8f93\u51fa\u6216\u62a5\u9519\uff0c\u6211\u4f1a\u53ea\u56f4\u7ed5\u8fd9\u4e2a\u70b9\u7ee7\u7eed\u3002"
    if path:
        return (
            f"Next step: stay with {anchor} and inspect the input, branch, or call directly connected to it in `{path}`, "
            "then bring back the first real output or error."
        )
    return (
        f"Next step: stay with {anchor}; bring back the smallest code fragment, input/output pair, or error, "
        "and I will stay on this exact question."
    )


def _relevance_reanchor_visible_reply(
    *,
    message: str | None,
    current_file: dict[str, object] | None,
    response_language: str | None,
) -> str:
    anchor = _current_request_anchor_label(message, current_file=current_file)
    if not anchor:
        return ""
    next_step = _relevance_reanchor_next_step(
        message=message,
        current_file=current_file,
        response_language=response_language,
    )
    if _prefers_chinese(response_language):
        return (
            f"\u6211\u5148\u56de\u5230\u4f60\u521a\u624d\u95ee\u7684 {anchor}\uff0c\u4e0d\u628a\u5b83\u5e26\u56de\u524d\u4e00\u6761\u4e3b\u7ebf\u3002\n\n"
            f"{next_step}"
        )
    return (
        f"I will return to your question about {anchor} instead of pulling this turn back to an earlier lane.\n\n"
        f"{next_step}"
    )


def _reanchor_agentic_continuity_to_current_request(
    *,
    field_kind: str,
    message: str | None,
    current_file: dict[str, object] | None,
    response_language: str | None,
) -> str:
    anchor = _current_request_anchor_label(message, current_file=current_file)
    if not anchor:
        return ""
    next_step = _relevance_reanchor_next_step(
        message=message,
        current_file=current_file,
        response_language=response_language,
    )
    if _prefers_chinese(response_language):
        summary = f"\u5f53\u524d\u95ee\u9898\uff1a{anchor}\u3002"
        if field_kind == "summary":
            return summary
        if field_kind == "next_step":
            return next_step
        return f"{summary}\n\n{next_step}"
    summary = f"Current request: {anchor}."
    if field_kind == "summary":
        return summary
    if field_kind == "next_step":
        return next_step
    return f"{summary} {next_step}"


def _clean_provider_failure_summary(
    self,
    category: str,
    response_language: str | None,
) -> str:
    if category == "quota_exhausted":
        return provider_quota_copy(response_language)[0]
    if category == "streaming_unavailable":
        return _localized_text(
            "The configured provider has no verified native streaming path for this turn.",
            "当前 provider 没有通过验证的原生流式路径，这一轮不能继续。",
            response_language,
        )
    summary_map: dict[str, tuple[str, str]] = {
        "invalid_key_or_permission": (
            "The provider rejected this turn's API key or permissions.",
            "这个 provider 拒绝了这一轮使用的 API key 或 permission。",
        ),
        "model_unsupported": (
            "The provider reached the endpoint, but this model name is not accepted there.",
            "这个 provider 可以连通，但当前 model name 不被这个 endpoint 接受。",
        ),
        "model_not_found": (
            "The provider reached the gateway, but no available channel matched this model.",
            "这个 provider 可以连通，但 gateway 里没有可用 channel 匹配当前 model。",
        ),
        "language_corruption": (
            "The provider returned a visibly corrupted coaching reply on this turn.",
            "这个 provider 可达，但这一轮返回了肉眼可见的乱码回复。",
        ),
        "language_probe_inconclusive": (
            "The provider reached the endpoint, but Trainer could not fully verify zh-CN input integrity yet.",
            "这个 provider 可达，但 Trainer 还不能完整验证这条链路的 zh-CN 输入保真度。",
        ),
        "empty_response": (
            "The provider reached the endpoint, but returned no usable visible reply.",
            "这个 provider 可达，但没有返回可用的可见回复。",
        ),
        "malformed_response": (
            "The endpoint responded, but the payload did not match the configured protocol.",
            "这个 endpoint 有响应，但 payload 不符合当前配置的 protocol。",
        ),
        "rate_limit": (
            "The provider rate-limited this turn before Trainer could continue.",
            "这个 provider 对这一轮请求触发了 rate limit，Trainer 暂时不能继续。",
        ),
        "upstream_unavailable": (
            "The provider answered, but its own upstream failed on this turn. Nothing "
            "needs changing in the connection — retrying shortly is the fix.",
            "provider 已经应答，但它自己的上游在这一轮失败了。连接配置不用改，稍后重试即可。",
        ),
        "timeout": (
            "Trainer could not get a response from the provider before the timeout.",
            "Trainer 在 timeout 前没有从 provider 收到响应。",
        ),
        "network": (
            "Trainer could not reach the provider over the network.",
            "Trainer 目前无法通过 network 连到这个 provider。",
        ),
    }
    english, chinese = summary_map.get(
        category,
        (
            "Trainer is blocked on the provider path for this turn.",
            "Trainer 这一轮被 provider path 卡住了。",
        ),
    )
    return _localized_text(english, chinese, response_language)


def _clean_provider_failure_next_step(
    self,
    category: str,
    response_language: str | None,
) -> str:
    if category == "quota_exhausted":
        return provider_quota_copy(response_language)[1]
    if category == "streaming_unavailable":
        return _localized_text(
            "Choose a provider and model with verified native streaming in Settings, retest it, and resend this exact turn.",
            "先在设置里选择已验证支持原生流式的 provider 和 model，重新测试后再重发这一轮。",
            response_language,
        )
    next_step_map: dict[str, tuple[str, str]] = {
        "invalid_key_or_permission": (
            "Check the API key or provider permissions, retest the connection, and resend this exact turn.",
            "先检查 API key 或 provider permission，重新测试连接后再重发这一轮。",
        ),
        "model_unsupported": (
            "Switch to a model name that this provider actually supports, retest, and resend this exact turn.",
            "先换成这个 provider 真正支持的 model name，重新测试后再重发这一轮。",
        ),
        "model_not_found": (
            "Pick a channel-backed model at this gateway, retest, and resend this exact turn.",
            "先换成这个 gateway 里真实可用的 model，重新测试后再重发这一轮。",
        ),
        "language_corruption": (
            "Switch provider or gateway first, then resend this same turn after the visible corruption disappears.",
            "先切换 provider 或 gateway，确认乱码消失后再重发这一轮。",
        ),
        "language_probe_inconclusive": (
            "Retest with a zh-CN probe before trusting this provider for Chinese coaching turns.",
            "先用 zh-CN probe 重新测试，再把这个 provider 用于中文 coaching。",
        ),
        "empty_response": (
            "Retest with a visible-text probe or switch to a model that returns visible text.",
            "先用 visible-text probe 重新测试，或切换到会返回可见文本的 model。",
        ),
        "malformed_response": (
            "Check that the endpoint really speaks the configured protocol, then retest and resend this exact turn.",
            "先确认这个 endpoint 真的支持当前配置的 protocol，再测试并重发这一轮。",
        ),
        "rate_limit": (
            "Wait briefly, then retry this same turn once the rate limit clears.",
            "先等一会儿，等 rate limit 过去后再重试这一轮。",
        ),
        "upstream_unavailable": (
            "The provider itself is up — its upstream is failing. Retry this same turn in a moment; "
            "do not change the connection settings.",
            "provider 本身是通的，是它的上游在报错。稍等一下重试这一轮即可，不用改连接配置。",
        ),
        "timeout": (
            "Retry once after checking provider latency or gateway load.",
            "先检查 provider 延迟或 gateway 负载，再重试这一轮。",
        ),
        "network": (
            "Check the network path or proxy settings, then resend this exact turn.",
            "先检查 network 路径或 proxy 设置，再重发这一轮。",
        ),
    }
    english, chinese = next_step_map.get(
        category,
        (
            "Repair the provider path, then resend this exact coaching turn.",
            "先修好 provider path，再重发这一轮 coaching。",
        ),
    )
    return _localized_text(english, chinese, response_language)


def _clean_provider_failure_reply(
    self,
    category: str,
    detail: str | None,
    response_language: str | None,
) -> str:
    if category == "quota_exhausted":
        return provider_quota_reply(response_language)
    detail_text = _compact_text(
        redact_provider_error({"upstream_body": detail}, api_key=self._api_key)
    )
    summary = self.provider_failure_summary(category, response_language)
    next_step = self.provider_failure_next_step(category, response_language)
    if _prefers_chinese(response_language):
        lines = [
            "Trainer 当前卡在 provider path，所以这轮 coaching 还不能继续。",
            "",
            summary,
        ]
        if detail_text:
            lines.append(f"详情：{detail_text}")
        lines.append(f"下一步：{next_step}")
        return "\n".join(lines)
    if detail_text:
        return (
            "Trainer is blocked on the provider path, so I cannot continue this coaching turn yet.\n\n"
            f"{summary}\nDetail: {detail_text}\nNext: {next_step}"
        )
    return (
        "Trainer is blocked on the provider path, so I cannot continue this coaching turn yet.\n\n"
        f"{summary}\nNext: {next_step}"
    )


def _clean_agentic_fallback_continuity(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> tuple[str, str]:
    context = extract_coaching_context(message, current_file, coach_context)
    chinese = _prefers_chinese(response_language)
    summary = str(
        context.get("thread_summary")
        or context.get("summary")
        or context.get("current_focus")
        or context.get("continuity_summary")
        or context.get("review_queue_summary")
        or ""
    ).strip()
    if not summary:
        summary = (
            "This turn needs a fresh provider retry, but the same thread can continue."
            if not chinese
            else "这轮 provider 需要重新连接，但同一条学习线可以继续。"
        )

    scenario = str(context.get("scenario") or "general").strip()
    next_step_hint = _prefer_structured_next_step(
        scenario=scenario,
        next_step_hint=_extract_next_step_hint_text(
            context.get("thread_next_step")
            or context.get("resume_hint")
            or context.get("next_step_hint")
        ),
        implementation_guide=(
            context.get("implementation_guide")
            if isinstance(context.get("implementation_guide"), dict)
            else {}
        ),
        adaptation_guide=(
            context.get("project_adaptation_guide")
            if isinstance(context.get("project_adaptation_guide"), dict)
            else context.get("adaptation_guide")
            if isinstance(context.get("adaptation_guide"), dict)
            else {}
        ),
        principle_note=(
            context.get("principle_notes")
            if isinstance(context.get("principle_notes"), dict)
            else context.get("principle_note")
            if isinstance(context.get("principle_note"), dict)
            else {}
        ),
        project_ideas=(
            [item for item in context.get("project_ideas", []) if isinstance(item, dict)]
            if isinstance(context.get("project_ideas"), list)
            else []
        ),
        exercise_prompt=(
            context.get("exercise_prompt")
            if isinstance(context.get("exercise_prompt"), dict)
            else {}
        ),
    )
    next_step = str(
        next_step_hint
        or context.get("thread_next_step")
        or context.get("resume_hint")
        or context.get("next_step")
        or context.get("continuity_summary")
        or context.get("review_queue_summary")
        or ""
    ).strip()
    if not next_step:
        next_step = (
            "Retry from the smallest verified step after checking the provider connection."
            if not chinese
            else "先检查 provider connection，再从已验证的最小步骤继续。"
        )
    return summary, next_step


_agentic_fallback_continuity = _clean_agentic_fallback_continuity
