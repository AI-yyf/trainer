"""Card generation service with LLM-backed content generation.

Generates TrainingCardCandidateSnapshot instances from different sources:
conversation_gap, plan_requirement, resource_knowledge, practice_feedback,
dependency_mastery, review_due.

Each source method attempts LLM generation first. On failure, it falls back
to a deterministic template.
"""

from __future__ import annotations

import re
from typing import cast

from ...core.models import (
    CardGenerationContext,
    DependencyUsageEvidence,
    TrainingCardCandidateSnapshot,
    TrainingCardType,
)
from .defaults_and_templates import (
    _GUIDED_SCENARIO_PACK_DEBUG,
    _GUIDED_SCENARIO_PACK_DEPENDENCY,
    _GUIDED_SCENARIO_PACK_FUNCTION,
    _GUIDED_SCENARIO_PACK_REMOTE,
    _GUIDED_SCENARIO_PACK_RESOURCE,
    _derive_resource_trust_state,
    _feedback_dict,
    _guided_fact_text,
    _guided_pack_focus,
    _guided_pack_skill,
    _load_guided_scenario_pack_catalog,
    _localized_8,
    _localized_string,
    _localized_string_list,
    _localized_text,
    _normalize_function_guidance_card,
    _practice_defaults,
    _resource_knowledge_evidence,
    _string_list,
)


def _ensure_practice_contract(
    card: TrainingCardCandidateSnapshot,
    context: CardGenerationContext,
) -> TrainingCardCandidateSnapshot:
    """Fill the visible loop fields when an otherwise usable practice card omits them.

    Provider output is intentionally treated as a draft. A practice card is not
    routable as a learning unit until it names a try, a check, a reflection, and
    a return path. Filling only absent fields keeps successful provider output
    intact while retaining a deterministic fallback when the provider is vague.
    """
    if card.card_type != "practice":
        return card

    defaults = _practice_defaults(context, context.response_language)
    card.scenario = card.scenario or context.context_hint or defaults["problem_statement"]
    card.problem_statement = card.problem_statement or defaults["problem_statement"]
    card.suggested_workspace_action = (
        card.suggested_workspace_action or defaults["suggested_workspace_action"]
    )
    card.api_hints = card.api_hints or list(defaults["api_hints"])
    card.deliverable = card.deliverable or defaults["deliverable"]
    card.self_check = card.self_check or list(defaults["self_check"])
    card.validation_method = card.validation_method or defaults["validation_method"]
    card.grading_rubric = card.grading_rubric or list(defaults["grading_rubric"])
    card.learner_deliverables = card.learner_deliverables or list(defaults["learner_deliverables"])
    card.verification_steps = card.verification_steps or list(defaults["verification_steps"])
    card.success_signal = card.success_signal or defaults["success_signal"]
    card.stuck_recovery = card.stuck_recovery or defaults["stuck_recovery"]
    card.reflection_prompt = card.reflection_prompt or defaults["reflection_prompt"]
    card.return_with = card.return_with or defaults["return_with"]
    card.next_after_completion = card.next_after_completion or defaults["next_after_completion"]
    return card


_MULTI_SCOPE_SEPARATOR = re.compile(
    r"\s*(?:,|;|\band\b|\bthen\b|\balso\b|\u3001|\uff0c|\uff1b|\u548c|\u4ee5\u53ca|\u5e76\u4e14)\s*",
    re.IGNORECASE,
)


_UNVERIFIED_COMPLETION_CLAIM = re.compile(
    r"\b(?:master(?:ed|y)|fully\s+understood|complete(?:d|ion)?|ready\s+to\s+advance)\b|\u638c\u63e1|\u5df2\u5b8c\u6210",
    re.IGNORECASE,
)


def _single_problem_focus(*values: str) -> str:
    """Return the first explicit learning target from a potentially broad request."""
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        parts = [part.strip(" .:-") for part in _MULTI_SCOPE_SEPARATOR.split(cleaned) if part.strip(" .:-")]
        return parts[0] if parts else cleaned
    return "current learning target"


def _truthful_completion_copy(topic: str, language: str | None) -> str:
    return _localized_text(
        f"This card counts only after verifiable evidence confirms one result for {topic}; it does not establish long-term retention.",
        f"\u8fd9\u5f20\u5361\u53ea\u6709\u5728\u53ef\u9a8c\u8bc1\u8bc1\u636e\u786e\u8ba4 {topic} \u7684\u4e00\u4e2a\u7ed3\u679c\u540e\u624d\u80fd\u8ba1\u5165\u5b8c\u6210\uff1b\u5b83\u4e0d\u4ee3\u8868\u957f\u671f\u638c\u63e1\u3002",
        language,
    )


def _enforce_learning_loop_contract(
    card: TrainingCardCandidateSnapshot,
    context: CardGenerationContext,
) -> TrainingCardCandidateSnapshot:
    """Attach one-problem, evidence-first semantics without changing the public model.

    ``TrainingCardCandidateSnapshot`` deliberately allows extension fields. The
    metadata below is therefore backward compatible with existing consumers,
    while the visible fields continue to drive older webviews and API clients.
    """
    language = context.response_language
    original_focus = card.target_skill or card.focus_area or context.target_skill or context.focus_area
    focus = _single_problem_focus(card.target_skill, card.focus_area, context.target_skill, context.focus_area)

    if card.target_skill:
        card.target_skill = focus
    elif card.focus_area:
        card.focus_area = focus
    else:
        card.target_skill = focus

    if card.focus_area and _MULTI_SCOPE_SEPARATOR.search(card.focus_area):
        card.focus_area = focus
    if original_focus and original_focus != focus and card.title:
        card.title = card.title.replace(original_focus, focus)

    if _UNVERIFIED_COMPLETION_CLAIM.search(card.success_signal or ""):
        card.success_signal = _truthful_completion_copy(focus, language)
    if _UNVERIFIED_COMPLETION_CLAIM.search(card.next_after_completion or ""):
        card.next_after_completion = _localized_text(
            f"Return with the verification output for {focus}; decide the next step after the evidence is reviewed.",
            f"\u5e26\u7740 {focus} \u7684\u9a8c\u8bc1\u8f93\u51fa\u56de\u6765\uff0c\u5728\u5ba1\u67e5\u8bc1\u636e\u540e\u518d\u51b3\u5b9a\u4e0b\u4e00\u6b65\u3002",
            language,
        )
    feedback = dict(card.feedback)
    if _UNVERIFIED_COMPLETION_CLAIM.search(str(feedback.get("correct", ""))):
        feedback["correct"] = _localized_text(
            "The answer is a useful attempt. Verify it against the stated check before counting the card as complete.",
            "\u8fd9\u4e2a\u7b54\u6848\u662f\u4e00\u6b21\u6709\u4ef7\u503c\u7684\u5c1d\u8bd5\u3002\u5728\u5c06\u5361\u7247\u8ba1\u5165\u5b8c\u6210\u524d\uff0c\u8bf7\u5148\u6309\u58f0\u660e\u7684\u68c0\u67e5\u8fdb\u884c\u9a8c\u8bc1\u3002",
            language,
        )
        card.feedback = feedback

    learn = card.problem_statement or card.question or card.scenario
    try_step = card.suggested_workspace_action or card.deliverable
    verify = list(card.verification_steps) or ([card.validation_method] if card.validation_method else [])
    return card.model_copy(
        update={
            "learning_loop": {
                "learn": learn,
                "try": try_step,
                "verify": verify,
                "reflect": card.reflection_prompt,
                "return": card.return_with,
                "single_problem_focus": focus,
                "completion_requires_verification": True,
                "durable_mastery_claimed": False,
            },
            "single_problem_focus": focus,
            "completion_requires_verification": True,
        }
    )


def _make_guided_scenario_pack_card_from_catalog(
    pack: str,
    context: CardGenerationContext,
    card_type: str,
    language: str = "en-US",
) -> TrainingCardCandidateSnapshot | None:
    raw_pack = _load_guided_scenario_pack_catalog().get(pack)
    if not raw_pack:
        return None

    raw_card = raw_pack.get(card_type)
    if not isinstance(raw_card, dict):
        return None

    def _fallback_pack_focus_label(pack_name: str, language_name: str) -> str:
        is_chinese = language_name == "zh-CN"
        if pack_name == _GUIDED_SCENARIO_PACK_REMOTE:
            return "VS Code 远程工作区" if is_chinese else "VS Code remote workspace"
        if pack_name == _GUIDED_SCENARIO_PACK_DEBUG:
            return "VS Code 调试闭环" if is_chinese else "VS Code debug loop"
        if pack_name == _GUIDED_SCENARIO_PACK_FUNCTION:
            return "\u51fd\u6570\u5951\u7ea6\u5224\u65ad" if is_chinese else "function contract reading"
        if pack_name == _GUIDED_SCENARIO_PACK_RESOURCE:
            return "\u8d44\u6e90\u5230\u53ef\u4fe1\u77e5\u8bc6" if is_chinese else "resource to trusted knowledge"
        if pack_name == _GUIDED_SCENARIO_PACK_DEPENDENCY:
            return "\u4f9d\u8d56\u4e0e API \u638c\u63e1" if is_chinese else "dependency and API mastery"
        return pack_name.replace("_", " ")

    current_focus = _localized_string(raw_pack.get("currentFocus"), language) or _fallback_pack_focus_label(
        pack,
        language,
    )
    target_skill = _localized_string(raw_card.get("targetSkill"), language) or current_focus
    scenario = context.context_hint or _localized_string(raw_card.get("scenario"), language)
    next_step_key = "practiceNextStep" if card_type == "practice" else "flashNextStep"

    card = TrainingCardCandidateSnapshot(
        card_type=cast(TrainingCardType, card_type),
        scenario_pack=pack,
        title=_localized_string(raw_card.get("title"), language),
        why_now=_localized_string(raw_card.get("whyNow"), language),
        focus_area=_guided_pack_focus(context, current_focus),
        target_skill=_guided_pack_skill(context, target_skill),
        scenario=scenario,
        problem_statement=_localized_string(raw_card.get("problemStatement"), language),
        suggested_workspace_action=_localized_string(
            raw_card.get("suggestedWorkspaceAction"),
            language,
        ),
        api_hints=_string_list(raw_card.get("apiHints")),
        constraints=_localized_string_list(raw_card.get("constraints"), language),
        deliverable=_localized_string(raw_card.get("deliverable"), language),
        self_check=_localized_string_list(raw_card.get("selfCheck"), language),
        validation_method=_localized_string(raw_card.get("validationMethod"), language),
        learner_deliverables=_localized_string_list(raw_card.get("learnerDeliverables"), language),
        verification_steps=_localized_string_list(raw_card.get("verificationSteps"), language),
        success_signal=_localized_string(raw_card.get("successSignal"), language),
        hint_ladder=_localized_string_list(raw_card.get("hintLadder"), language),
        common_mistakes=_localized_string_list(raw_card.get("commonMistakes"), language),
        stuck_recovery=_localized_string(raw_card.get("stuckRecovery"), language),
        reflection_prompt=_localized_string(raw_card.get("reflectionPrompt"), language),
        return_with=_localized_string(raw_card.get("returnWith"), language),
        next_after_completion=
            _localized_string(raw_pack.get(next_step_key), language)
            or _localized_string(raw_card.get("returnWith"), language),
        expected_symbols=_string_list(raw_card.get("expectedSymbols")),
        files_to_touch=_string_list(raw_card.get("filesToTouch")),
        source_chain=_localized_string_list(raw_pack.get("sourceChain"), language),
        difficulty=context.difficulty or "medium",
    )

    if pack == _GUIDED_SCENARIO_PACK_FUNCTION:
        card = _normalize_function_guidance_card(card, language)

    if card_type == "flash":
        card.knowledge_type = _localized_string(raw_card.get("knowledgeType"), language)
        card.question = _localized_string(raw_card.get("question"), language)
        card.context = context.context_hint or _localized_string(raw_card.get("context"), language)
        card.answer_mode = _localized_string(raw_card.get("answerMode"), language) or "text"
        card.expected_answer = _localized_string(raw_card.get("expectedAnswer"), language)
        card.feedback = _feedback_dict(raw_card.get("feedback"), language)

    return card


def _guided_fact_path(value: object) -> str:
    path = _guided_fact_text(value, limit=480).replace("\\", "/")
    if path.startswith("<") and path.endswith(">"):
        return ""
    return path


_DEPENDENCY_GENERIC_IDENTIFIERS = frozenset(
    {
        "api",
        "dependency",
        "dependencies",
        "library",
        "package",
        "sdk",
        "usage",
        "use",
    }
)


def _dependency_identifier_candidates(dependency: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw_identifier in re.findall(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", dependency):
        parts = [part.casefold() for part in raw_identifier.split(".")]
        if not parts or all(part in _DEPENDENCY_GENERIC_IDENTIFIERS for part in parts):
            continue
        for end in range(len(parts), 0, -1):
            candidate = ".".join(parts[:end])
            if (
                len(candidate) >= 3
                and candidate not in _DEPENDENCY_GENERIC_IDENTIFIERS
                and candidate not in seen
            ):
                candidates.append(candidate)
                seen.add(candidate)
    return candidates


def _matches_dependency_usage(dependency: str, identifier: str) -> bool:
    evidence_identifier = _guided_fact_text(identifier, limit=240).casefold().strip(".")
    if not evidence_identifier:
        return False
    return any(
        evidence_identifier == candidate
        or candidate.startswith(f"{evidence_identifier}.")
        or evidence_identifier.startswith(f"{candidate}.")
        for candidate in _dependency_identifier_candidates(dependency)
    )


def _verified_dependency_usage(
    context: CardGenerationContext,
    dependency: str,
) -> DependencyUsageEvidence | None:
    for evidence in context.dependency_usage_evidence:
        kind = _guided_fact_text(evidence.kind, limit=40).lower()
        identifier = _guided_fact_text(evidence.identifier, limit=240)
        summary = _guided_fact_text(evidence.summary, limit=320)
        path = _guided_fact_path(evidence.file_path)
        if not identifier or not summary or not _matches_dependency_usage(dependency, identifier):
            continue
        if kind in {"import", "call"} and path:
            return evidence
        if kind == "declaration" and _guided_fact_text(evidence.summary, limit=320):
            return evidence
    return None


def _guided_unique_items(*groups: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            cleaned = _guided_fact_text(value)
            if cleaned and cleaned not in seen:
                result.append(cleaned)
                seen.add(cleaned)
    return result


def _guided_remote_name(context: CardGenerationContext) -> str:
    direct_name = _guided_fact_text(context.remote_workspace_name)
    if direct_name:
        return direct_name
    for fact in context.remote_workspace_facts:
        cleaned = _guided_fact_text(fact)
        lowered = cleaned.lower()
        for prefix in ("remote identity:", "remote_name:", "remote:"):
            if lowered.startswith(prefix):
                return cleaned[len(prefix) :].strip()
    return ""


def _guided_function_anchor(context: CardGenerationContext, path: str) -> str:
    source = _guided_fact_text(
        context.current_file_selection
        or context.current_file_excerpt
        or context.current_file_content,
        limit=2400,
    )
    if not source:
        return ""
    for pattern in (
        r"\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)",
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
    ):
        match = re.search(pattern, source)
        if match:
            symbol = match.group(1)
            return _localized_8(
                {
                    "en-US": f"function `{symbol}` in `{path}`",
                    "zh-CN": f"\u51fd\u6570`{symbol}`\u4f4d\u4e8e`{path}`",
                    "es-ES": f"función `{symbol}` en `{path}`",
                    "fr-FR": f"fonction `{symbol}` dans `{path}`",
                    "de-DE": f"Funktion `{symbol}` in `{path}`",
                    "ja-JP": f"`{path}` 内の関数 `{symbol}`",
                    "ko-KR": f"`{path}`의 함수 `{symbol}`",
                    "pt-BR": f"função `{symbol}` em `{path}`",
                },
                context.response_language,
            )
    selection_range = _guided_fact_text(context.current_file_selection_range, limit=120)
    if context.current_file_selection:
        range_label = selection_range or _localized_8(
            {
                "en-US": "range not supplied",
                "zh-CN": "\u672a\u63d0\u4f9b\u8303\u56f4",
                "es-ES": "rango no indicado",
                "fr-FR": "plage non fournie",
                "de-DE": "Bereich nicht angegeben",
                "ja-JP": "範囲未指定",
                "ko-KR": "범위가 제공되지 않음",
                "pt-BR": "intervalo não informado",
            },
            context.response_language,
        )
        return _localized_8(
            {
                "en-US": f"selected code ({range_label}) in `{path}`",
                "zh-CN": f"`{path}`\u4e2d\u7684\u9009\u4e2d\u4ee3\u7801\uff08{range_label}\uff09",
                "es-ES": f"código seleccionado ({range_label}) en `{path}`",
                "fr-FR": f"code sélectionné ({range_label}) dans `{path}`",
                "de-DE": f"ausgewählter Code ({range_label}) in `{path}`",
                "ja-JP": f"`{path}` の選択コード（{range_label}）",
                "ko-KR": f"`{path}`의 선택된 코드({range_label})",
                "pt-BR": f"código selecionado ({range_label}) em `{path}`",
            },
            context.response_language,
        )
    return _localized_8(
        {
            "en-US": f"current code in `{path}`",
            "zh-CN": f"`{path}`\u4e2d\u7684\u5f53\u524d\u4ee3\u7801",
            "es-ES": f"código actual en `{path}`",
            "fr-FR": f"code actuel dans `{path}`",
            "de-DE": f"aktueller Code in `{path}`",
            "ja-JP": f"`{path}` 内の現在のコード",
            "ko-KR": f"`{path}`의 현재 코드",
            "pt-BR": f"código atual em `{path}`",
        },
        context.response_language,
    )


def _guided_text(context: CardGenerationContext, english: str, chinese: str) -> str:
    return _localized_text(english, chinese, context.response_language)


def _guided_pack_label(pack: str, language: str | None) -> str:
    labels = {
        _GUIDED_SCENARIO_PACK_FUNCTION: ("function guidance", "\u51fd\u6570\u63d0\u793a"),
        _GUIDED_SCENARIO_PACK_DEBUG: ("debug loop", "\u8c03\u8bd5\u95ed\u73af"),
        _GUIDED_SCENARIO_PACK_REMOTE: ("remote workspace", "\u8fdc\u7a0b\u5de5\u4f5c\u533a"),
        _GUIDED_SCENARIO_PACK_RESOURCE: ("resource knowledge", "\u8d44\u6e90\u77e5\u8bc6"),
        _GUIDED_SCENARIO_PACK_DEPENDENCY: ("dependency and API mastery", "\u4f9d\u8d56\u4e0e API \u638c\u63e1"),
    }
    english, chinese = labels.get(pack, (pack.replace("_", " "), pack.replace("_", " ")))
    return _localized_text(english, chinese, language)


def _guided_scenario_skeleton_source(context: CardGenerationContext) -> str:
    return _guided_text(
        context,
        "Guided scenario skeleton",
        "\u5f15\u5bfc\u573a\u666f\u9aa8\u67b6",
    )


def _guided_missing_fact_card(
    card: TrainingCardCandidateSnapshot,
    *,
    pack: str,
    missing: str,
    missing_chinese: str,
    context: CardGenerationContext,
) -> TrainingCardCandidateSnapshot:
    missing_display = _guided_text(context, missing, missing_chinese)
    label = _guided_pack_label(pack, context.response_language)
    note = _guided_text(
        context,
        f"Grounding unavailable: {missing_display}.",
        f"\u7f3a\u5c11\u53ef\u9a8c\u8bc1\u4e8b\u5b9e\uff1a{missing_display}\u3002",
    )
    return card.model_copy(
        update={
            "status": "needs_primer",
            "files_to_touch": [],
            "why_now": (
                f"{card.why_now} {note} "
                + _guided_text(
                    context,
                    "Trainer will not treat catalog examples or placeholders as workspace facts.",
                    "Trainer \u4e0d\u4f1a\u628a\u76ee\u5f55\u793a\u4f8b\u6216\u5360\u4f4d\u7b26\u5f53\u4f5c\u5de5\u4f5c\u533a\u4e8b\u5b9e\u3002",
                )
            ).strip(),
            "suggested_workspace_action": _guided_text(
                context,
                f"Provide {missing_display}; then regenerate this {label} card from those facts.",
                f"\u8bf7\u63d0\u4f9b{missing_display}\uff0c\u518d\u7528\u8fd9\u4e9b\u4e8b\u5b9e\u91cd\u65b0\u751f\u6210\u8fd9\u5f20{label}\u5361\u3002",
            ),
            "constraints": _guided_unique_items(
                card.constraints,
                [
                    note,
                    _guided_text(
                        context,
                        "Do not treat catalog paths or placeholders as current workspace facts.",
                        "\u4e0d\u8981\u628a\u76ee\u5f55\u8def\u5f84\u6216\u5360\u4f4d\u7b26\u5f53\u4f5c\u5f53\u524d\u5de5\u4f5c\u533a\u4e8b\u5b9e\u3002",
                    ),
                ],
            ),
            "learner_deliverables": [
                _guided_text(
                    context,
                    f"Provide {missing_display}.",
                    f"\u8bf7\u63d0\u4f9b{missing_display}\u3002",
                ),
                _guided_text(
                    context,
                    "Name the supplied fact that will anchor the next card.",
                    "\u8bf4\u660e\u54ea\u6761\u63d0\u4f9b\u7684\u4e8b\u5b9e\u5c06\u9501\u5b9a\u4e0b\u4e00\u5f20\u5361\u3002",
                ),
            ],
            "verification_steps": [
                _guided_text(
                    context,
                    f"Provide {missing_display}.",
                    f"\u8bf7\u63d0\u4f9b{missing_display}\u3002",
                ),
                _guided_text(
                    context,
                    "Regenerate the card only after the facts can be verified.",
                    "\u53ea\u5728\u8fd9\u4e9b\u4e8b\u5b9e\u53ef\u9a8c\u8bc1\u540e\u518d\u91cd\u65b0\u751f\u6210\u5361\u7247\u3002",
                ),
            ],
            "validation_method": _guided_text(
                context,
                f"Validate the supplied {missing_display} before attempting the exercise.",
                f"\u5f00\u59cb\u7ec3\u4e60\u524d\uff0c\u5148\u9a8c\u8bc1\u63d0\u4f9b\u7684{missing_display}\u3002",
            ),
            "success_signal": _guided_text(
                context,
                f"Verified workspace facts are available for this {label} card.",
                f"\u8fd9\u5f20{label}\u5361\u5df2\u5177\u5907\u53ef\u9a8c\u8bc1\u7684\u5de5\u4f5c\u533a\u4e8b\u5b9e\u3002",
            ),
            "return_with": _guided_text(
                context,
                f"Return with {missing_display}.",
                f"\u8bf7\u5e26\u56de{missing_display}\u3002",
            ),
            "source_chain": [
                _guided_scenario_skeleton_source(context),
                note,
            ],
        }
    )


def _apply_guided_workspace_facts(
    card: TrainingCardCandidateSnapshot,
    *,
    pack: str,
    context: CardGenerationContext,
) -> TrainingCardCandidateSnapshot:
    if pack not in {
        _GUIDED_SCENARIO_PACK_REMOTE,
        _GUIDED_SCENARIO_PACK_DEBUG,
        _GUIDED_SCENARIO_PACK_FUNCTION,
        _GUIDED_SCENARIO_PACK_RESOURCE,
        _GUIDED_SCENARIO_PACK_DEPENDENCY,
    }:
        return card

    if pack == _GUIDED_SCENARIO_PACK_RESOURCE:
        resource_id = _guided_fact_text(context.resource_id, limit=160)
        evidence, fragment_id, source_type, knowledge_focus, source_context = _resource_knowledge_evidence(
            context
        )
        trust_state = _derive_resource_trust_state(context)
        evidence_resource_id = _guided_fact_text(
            evidence.resource_id if evidence is not None else "",
            limit=160,
        )
        if (
            not resource_id
            or evidence_resource_id != resource_id
            or not fragment_id
            or not source_type
            or not knowledge_focus
            or not source_context
        ):
            return _guided_missing_fact_card(
                card,
                pack=pack,
                missing="a trusted indexed resource fragment and knowledge atom",
                missing_chinese="\u53ef\u4fe1\u5df2\u7d22\u5f15\u8d44\u6599\u7684\u7247\u6bb5\u4e0e\u77e5\u8bc6\u539f\u5b50",
                context=context,
            ).model_copy(update={"trust_state": trust_state})
        if trust_state != "trusted":
            return _guided_missing_fact_card(
                card,
                pack=pack,
                missing="a trusted indexed resource",
                missing_chinese="\u4e00\u4efd\u53ef\u4fe1\u4e14\u5df2\u7d22\u5f15\u7684\u8d44\u6599",
                context=context,
            ).model_copy(update={"trust_state": trust_state})
        return card.model_copy(
            update={
                "status": "candidate",
                "trust_state": trust_state,
                "files_to_touch": [],
                "why_now": _guided_text(
                    context,
                    f"{card.why_now} Coach confirmed trusted resource `{resource_id}` for `{knowledge_focus}`.",
                    f"{card.why_now} Coach \u5df2\u786e\u8ba4\u53ef\u4fe1\u8d44\u6599`{resource_id}`\u53ef\u7528\u4e8e`{knowledge_focus}`\u3002",
                ).strip(),
                "suggested_workspace_action": _guided_text(
                    context,
                    f"Read trusted resource `{resource_id}`, state one knowledge atom about `{knowledge_focus}`, then queue one next card.",
                    f"\u9605\u8bfb\u53ef\u4fe1\u8d44\u6599`{resource_id}`\uff0c\u8bf4\u660e\u4e00\u4e2a\u5173\u4e8e`{knowledge_focus}`\u7684\u77e5\u8bc6\u539f\u5b50\uff0c\u518d\u6392\u5165\u4e00\u5f20\u4e0b\u4e00\u6b65\u5361\u7247\u3002",
                ),
                "verification_steps": _guided_unique_items(
                    card.verification_steps,
                    [
                        _guided_text(
                            context,
                            f"Confirm that `{resource_id}` remains trusted before extracting `{knowledge_focus}`.",
                            f"\u63d0\u53d6`{knowledge_focus}`\u524d\uff0c\u786e\u8ba4`{resource_id}`\u4ecd\u5904\u4e8e\u53ef\u4fe1\u72b6\u6001\u3002",
                        ),
                        _guided_text(
                            context,
                            "Return one knowledge atom and the next card it should create.",
                            "\u5e26\u56de\u4e00\u4e2a\u77e5\u8bc6\u539f\u5b50\u53ca\u5176\u5e94\u751f\u6210\u7684\u4e0b\u4e00\u5f20\u5361\u7247\u3002",
                        ),
                    ],
                ),
                "source_chain": [
                    _guided_text(context, f"Resource ID: {resource_id}", f"\u8d44\u6599 ID\uff1a{resource_id}"),
                    _guided_text(context, f"Fragment ID: {fragment_id}", f"\u7247\u6bb5 ID\uff1a{fragment_id}"),
                    _guided_text(context, f"Source type: {source_type}", f"\u6765\u6e90\u7c7b\u578b\uff1a{source_type}"),
                    _guided_text(context, f"Trust state: {trust_state}", f"\u53ef\u4fe1\u72b6\u6001\uff1a{trust_state}"),
                    _guided_text(context, f"Knowledge atom: {knowledge_focus}", f"\u77e5\u8bc6\u539f\u5b50\uff1a{knowledge_focus}"),
                    _guided_text(context, f"Evidence: {source_context}", f"\u8bc1\u636e\uff1a{source_context}"),
                ],
            }
        )

    if pack == _GUIDED_SCENARIO_PACK_DEPENDENCY:
        dependency = _guided_fact_text(context.target_skill or context.focus_area, limit=240)
        usage_evidence = _verified_dependency_usage(context, dependency)
        if not dependency or usage_evidence is None:
            return _guided_missing_fact_card(
                card,
                pack=pack,
                missing="a dependency/API name and a verified import, call, or declaration",
                missing_chinese="\u4f9d\u8d56/API \u540d\u79f0\u53ca\u5df2\u9a8c\u8bc1\u7684\u5bfc\u5165\u3001\u8c03\u7528\u6216\u58f0\u660e",
                context=context,
            )
        evidence_path = _guided_fact_path(usage_evidence.file_path)
        evidence_kind = _guided_fact_text(usage_evidence.kind, limit=40).lower()
        evidence_identifier = _guided_fact_text(usage_evidence.identifier, limit=240)
        evidence_summary = _guided_fact_text(usage_evidence.summary, limit=320)
        if evidence_kind == "declaration":
            context_source = _guided_text(
                context,
                f"Verified declaration: {evidence_summary}",
                f"\u5df2\u9a8c\u8bc1\u58f0\u660e\uff1a{evidence_summary}",
            )
        else:
            context_source = _guided_text(
                context,
                f"Verified {evidence_kind}: {evidence_summary} in {evidence_path}",
                f"\u5df2\u9a8c\u8bc1{evidence_kind}\uff1a{evidence_summary}\uff0c\u4f4d\u4e8e{evidence_path}",
            )
        return card.model_copy(
            update={
                "status": "candidate",
                "files_to_touch": [evidence_path] if evidence_path else [],
                "why_now": _guided_text(
                    context,
                    f"{card.why_now} Coach verified `{dependency}` through {evidence_kind} `{evidence_identifier}`.",
                    f"{card.why_now} Coach \u901a\u8fc7{evidence_kind}\u9a8c\u8bc1\u4e86`{dependency}`\uff08`{evidence_identifier}`\uff09\u3002",
                ).strip(),
                "suggested_workspace_action": _guided_text(
                    context,
                    f"Use `{dependency}` through the verified usage, then record one output before claiming mastery.",
                    f"\u901a\u8fc7\u5df2\u9a8c\u8bc1\u7684\u4f7f\u7528\u65b9\u5f0f\u4f7f\u7528`{dependency}`\uff0c\u5e76\u5728\u58f0\u79f0\u638c\u63e1\u524d\u8bb0\u5f55\u4e00\u4e2a\u8f93\u51fa\u3002",
                ),
                "verification_steps": _guided_unique_items(
                    card.verification_steps,
                    [
                        _guided_text(
                            context,
                            f"Exercise one real capability of `{dependency}` through the verified usage.",
                            f"\u901a\u8fc7\u5df2\u9a8c\u8bc1\u7684\u4f7f\u7528\u65b9\u5f0f\u7ec3\u4e60`{dependency}`\u7684\u4e00\u9879\u771f\u5b9e\u80fd\u529b\u3002",
                        ),
                        _guided_text(
                            context,
                            "Return one verified output, response, or assertion and one sharp edge you checked.",
                            "\u5e26\u56de\u4e00\u4e2a\u5df2\u9a8c\u8bc1\u7684\u8f93\u51fa\u3001\u54cd\u5e94\u6216\u65ad\u8a00\uff0c\u4ee5\u53ca\u4e00\u4e2a\u5df2\u68c0\u67e5\u7684\u8fb9\u7f18\u6761\u4ef6\u3002",
                        ),
                    ],
                ),
                "source_chain": [
                    _guided_text(context, f"Dependency/API: {dependency}", f"\u4f9d\u8d56/API\uff1a{dependency}"),
                    context_source,
                    _guided_text(
                        context,
                        "Verification target: one real output",
                        "\u9a8c\u8bc1\u76ee\u6807\uff1a\u4e00\u4e2a\u771f\u5b9e\u8f93\u51fa",
                    ),
                ],
            }
        )

    path = _guided_fact_path(context.current_file_path)
    workspace_root = _guided_fact_path(context.workspace_root_path)

    if pack == _GUIDED_SCENARIO_PACK_FUNCTION:
        anchor = _guided_function_anchor(context, path) if path else ""
        if not anchor:
            return _guided_missing_fact_card(
                card,
                pack=pack,
                missing="a code-file path and selected code or file content",
                missing_chinese="\u4ee3\u7801\u6587\u4ef6\u8def\u5f84\u4e0e\u9009\u4e2d\u4ee3\u7801\u6216\u6587\u4ef6\u5185\u5bb9",
                context=context,
            )
        return card.model_copy(
            update={
                "files_to_touch": [path],
                "why_now": _guided_text(
                    context,
                    f"{card.why_now} Coach supplied {anchor}; use that real code instead of a template call site.",
                    f"{card.why_now} Coach \u5df2\u63d0\u4f9b{anchor}\uff1b\u8bf7\u4f7f\u7528\u8fd9\u6bb5\u771f\u5b9e\u4ee3\u7801\uff0c\u800c\u4e0d\u662f\u6a21\u677f\u8c03\u7528\u70b9\u3002",
                ).strip(),
                "suggested_workspace_action": _guided_text(
                    context,
                    f"Open `{path}`, inspect {anchor} with Hover or Signature Help, then state its contract before editing.",
                    f"\u6253\u5f00`{path}`\uff0c\u7528 Hover \u6216 Signature Help \u68c0\u67e5{anchor}\uff0c\u518d\u5728\u7f16\u8f91\u524d\u8bf4\u6e05\u5176 contract\u3002",
                ),
                "constraints": _guided_unique_items(
                    card.constraints,
                    [
                        _guided_text(
                            context,
                            f"Keep the investigation anchored to {anchor}.",
                            f"\u5c06\u8c03\u67e5\u9501\u5b9a\u5728{anchor}\u3002",
                        )
                    ],
                ),
                "verification_steps": _guided_unique_items(
                    card.verification_steps,
                    [
                        _guided_text(
                            context,
                            f"Inspect {anchor} in `{path}` with editor guidance.",
                            f"\u5728`{path}`\u4e2d\u7528\u7f16\u8f91\u5668\u63d0\u793a\u68c0\u67e5{anchor}\u3002",
                        ),
                        _guided_text(
                            context,
                            f"Record the parameter and return contract supported by the current code in `{path}`.",
                            f"\u8bb0\u5f55`{path}`\u5f53\u524d\u4ee3\u7801\u652f\u6301\u7684\u53c2\u6570\u548c return contract\u3002",
                        ),
                    ],
                ),
                "source_chain": [
                    _guided_scenario_skeleton_source(context),
                    _guided_text(context, f"Current file: {path}", f"\u5f53\u524d\u6587\u4ef6\uff1a{path}"),
                    _guided_text(context, f"Code anchor: {anchor}", f"\u4ee3\u7801\u951a\u70b9\uff1a{anchor}"),
                ],
            }
        )

    if pack == _GUIDED_SCENARIO_PACK_DEBUG:
        diagnostics = [
            _guided_fact_text(item, limit=360)
            for item in context.current_file_diagnostics
            if _guided_fact_text(item, limit=360)
        ]
        if not path or not diagnostics:
            return _guided_missing_fact_card(
                card,
                pack=pack,
                missing="a current file path and at least one diagnostic",
                missing_chinese="\u5f53\u524d\u6587\u4ef6\u8def\u5f84\u4e0e\u81f3\u5c11\u4e00\u6761\u8bca\u65ad",
                context=context,
            )
        diagnostic = diagnostics[0]
        return card.model_copy(
            update={
                "files_to_touch": [path],
                "why_now": _guided_text(
                    context,
                    f"{card.why_now} Coach supplied a diagnostic for `{path}`: `{diagnostic}`.",
                    f"{card.why_now} Coach \u5df2\u63d0\u4f9b`{path}`\u7684\u8bca\u65ad\uff1a`{diagnostic}`\u3002",
                ).strip(),
                "suggested_workspace_action": _guided_text(
                    context,
                    f"Reproduce the diagnostic in `{path}` before editing, then pause at the first useful state boundary.",
                    f"\u7f16\u8f91\u524d\u5148\u5728`{path}`\u4e2d\u590d\u73b0\u8bca\u65ad\uff0c\u7136\u540e\u5728\u7b2c\u4e00\u4e2a\u6709\u7528\u7684\u72b6\u6001\u8fb9\u754c\u6682\u505c\u3002",
                ),
                "constraints": _guided_unique_items(
                    card.constraints,
                    [
                        _guided_text(
                            context,
                            f"Keep the debug loop anchored to the reported diagnostic in `{path}`.",
                            f"\u5c06\u8c03\u8bd5\u95ed\u73af\u9501\u5b9a\u5728`{path}`\u4e2d\u5df2\u62a5\u544a\u7684\u8bca\u65ad\u3002",
                        )
                    ],
                ),
                "verification_steps": _guided_unique_items(
                    card.verification_steps,
                    [
                        _guided_text(
                            context,
                            f"Reproduce the reported diagnostic in `{path}`: `{diagnostic}`.",
                            f"\u5728`{path}`\u4e2d\u590d\u73b0\u5df2\u62a5\u544a\u7684\u8bca\u65ad\uff1a`{diagnostic}`\u3002",
                        ),
                        _guided_text(
                            context,
                            f"Record the first verified bad state before changing `{path}`.",
                            f"\u4fee\u6539`{path}`\u524d\uff0c\u8bb0\u5f55\u7b2c\u4e00\u4e2a\u5df2\u9a8c\u8bc1\u7684\u9519\u8bef\u72b6\u6001\u3002",
                        ),
                    ],
                ),
                "source_chain": [
                    _guided_scenario_skeleton_source(context),
                    _guided_text(context, f"Current file: {path}", f"\u5f53\u524d\u6587\u4ef6\uff1a{path}"),
                    _guided_text(context, f"Diagnostic: {diagnostic}", f"\u8bca\u65ad\uff1a{diagnostic}"),
                ],
            }
        )

    remote_name = _guided_remote_name(context)
    boundary = workspace_root or path
    if not remote_name or not boundary:
        return _guided_missing_fact_card(
            card,
            pack=pack,
            missing="a remote identity and a current workspace path or file path",
            missing_chinese="\u8fdc\u7a0b\u8eab\u4efd\u4e0e\u5f53\u524d\u5de5\u4f5c\u533a\u8def\u5f84\u6216\u6587\u4ef6\u8def\u5f84",
            context=context,
        )
    files_to_touch = [path] if path else []
    return card.model_copy(
        update={
            "files_to_touch": files_to_touch,
            "why_now": _guided_text(
                context,
                f"{card.why_now} Coach supplied remote identity `{remote_name}` and boundary `{boundary}`.",
                f"{card.why_now} Coach \u5df2\u63d0\u4f9b\u8fdc\u7a0b\u8eab\u4efd`{remote_name}`\u548c\u8fb9\u754c`{boundary}`\u3002",
            ).strip(),
            "suggested_workspace_action": _guided_text(
                context,
                f"Inspect remote identity `{remote_name}` against workspace boundary `{boundary}` before making a credential decision.",
                f"\u5728\u505a\u51ed\u636e\u51b3\u7b56\u524d\uff0c\u5148\u5bf9\u7167\u8fdc\u7a0b\u8eab\u4efd`{remote_name}`\u4e0e\u5de5\u4f5c\u533a\u8fb9\u754c`{boundary}`\u3002",
            ),
            "constraints": _guided_unique_items(
                card.constraints,
                [
                    _guided_text(
                        context,
                        f"Use only the reported remote identity `{remote_name}` and boundary `{boundary}`.",
                        f"\u53ea\u4f7f\u7528\u5df2\u62a5\u544a\u7684\u8fdc\u7a0b\u8eab\u4efd`{remote_name}`\u548c\u8fb9\u754c`{boundary}`\u3002",
                    )
                ],
            ),
            "verification_steps": _guided_unique_items(
                card.verification_steps,
                [
                    _guided_text(
                        context,
                        f"Confirm remote identity `{remote_name}` for workspace boundary `{boundary}`.",
                        f"\u786e\u8ba4\u5de5\u4f5c\u533a\u8fb9\u754c`{boundary}`\u5bf9\u5e94\u7684\u8fdc\u7a0b\u8eab\u4efd`{remote_name}`\u3002",
                    ),
                    _guided_text(
                        context,
                        f"State the credential decision for `{remote_name}` before touching project code.",
                        f"\u89e6\u78b0\u9879\u76ee\u4ee3\u7801\u524d\uff0c\u8bf4\u660e`{remote_name}`\u7684\u51ed\u636e\u51b3\u7b56\u3002",
                    ),
                ],
            ),
            "source_chain": [
                _guided_scenario_skeleton_source(context),
                _guided_text(
                    context,
                    f"Remote identity: {remote_name}",
                    f"\u8fdc\u7a0b\u8eab\u4efd\uff1a{remote_name}",
                ),
                _guided_text(
                    context,
                    f"Workspace boundary: {boundary}",
                    f"\u5de5\u4f5c\u533a\u8fb9\u754c\uff1a{boundary}",
                ),
            ],
        }
    )


def _build_guided_scenario_pack_card(
    pack: str,
    context: CardGenerationContext,
    card_type: str,
    language: str = "en-US",
) -> TrainingCardCandidateSnapshot:
    catalog_card = _make_guided_scenario_pack_card_from_catalog(pack, context, card_type, language)
    if catalog_card is not None:
        if card_type == "practice":
            catalog_card = catalog_card.model_copy(update={"status": "needs_primer"})
        return catalog_card

    if pack == _GUIDED_SCENARIO_PACK_RESOURCE:
        focus = _guided_pack_focus(context, _guided_text(context, "resource knowledge", "\u8d44\u6599\u77e5\u8bc6"))
        if card_type == "flash":
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                scenario_pack=pack,
                title=_guided_text(context, "Flash: Resource provenance", "\u95ea\u8bb0\uff1a\u8d44\u6599\u6eaf\u6e90"),
                why_now=_guided_text(
                    context,
                    "Recall the source and concept before treating resource content as learned knowledge.",
                    "\u5728\u5c06\u8d44\u6599\u5185\u5bb9\u5f53\u4f5c\u5df2\u638c\u63e1\u77e5\u8bc6\u524d\uff0c\u5148\u56de\u5fc6\u6765\u6e90\u4e0e\u6982\u5ff5\u3002",
                ),
                focus_area=focus,
                target_skill=_guided_pack_skill(context, focus),
                knowledge_type="resource_knowledge",
                question=_guided_text(
                    context,
                    "What provenance and concept must a trusted resource knowledge atom retain?",
                    "\u4e00\u4e2a\u53ef\u4fe1\u8d44\u6599\u77e5\u8bc6\u539f\u5b50\u5fc5\u987b\u4fdd\u7559\u54ea\u4e9b\u6765\u6e90\u548c\u6982\u5ff5\u4fe1\u606f\uff1f",
                ),
                context=_guided_text(context, "Tie the answer to the indexed resource, not a generic summary.", "\u5c06\u7b54\u6848\u7ed1\u5b9a\u5230\u5df2\u7d22\u5f15\u8d44\u6599\uff0c\u4e0d\u8981\u53ea\u7ed9\u51fa\u6cdb\u5316\u6458\u8981\u3002"),
                answer_mode="text",
                expected_answer=_guided_text(
                    context,
                    "Name the resource, its trust state, the extracted concept, and the next card it supports.",
                    "\u8bf4\u660e\u8d44\u6599\u3001\u5176\u53ef\u4fe1\u72b6\u6001\u3001\u63d0\u53d6\u6982\u5ff5\u548c\u5b83\u652f\u6301\u7684\u4e0b\u4e00\u5f20\u5361\u3002",
                ),
                validation_method=_guided_text(context, "Check the indexed resource and its trust state.", "\u6838\u5bf9\u5df2\u7d22\u5f15\u8d44\u6599\u53ca\u5176\u53ef\u4fe1\u72b6\u6001\u3002"),
                status="needs_primer",
            )
        return TrainingCardCandidateSnapshot(
            card_type="practice",
            scenario_pack=pack,
            title=_guided_text(context, "Practice: Turn a resource into trusted knowledge", "\u7ec3\u4e60\uff1a\u628a\u8d44\u6599\u53d8\u6210\u53ef\u4fe1\u77e5\u8bc6"),
            why_now=_guided_text(context, "A resource becomes useful only when its provenance and one concept are explicit.", "\u53ea\u6709\u6765\u6e90\u548c\u4e00\u4e2a\u6982\u5ff5\u660e\u786e\u65f6\uff0c\u8d44\u6599\u624d\u80fd\u771f\u6b63\u7528\u4e8e\u5b66\u4e60\u3002"),
            focus_area=focus,
            target_skill=_guided_pack_skill(context, focus),
            problem_statement=_guided_text(context, "Extract one trusted knowledge atom and queue its next card.", "\u63d0\u53d6\u4e00\u4e2a\u53ef\u4fe1\u77e5\u8bc6\u539f\u5b50\uff0c\u5e76\u6392\u5165\u5b83\u7684\u4e0b\u4e00\u5f20\u5361\u3002"),
            suggested_workspace_action=_guided_text(context, "Read the resource before extracting one precise concept.", "\u63d0\u53d6\u4e00\u4e2a\u7cbe\u786e\u6982\u5ff5\u524d\uff0c\u5148\u9605\u8bfb\u8d44\u6599\u3002"),
            deliverable=_guided_text(context, "One knowledge atom with provenance and one next card.", "\u4e00\u4e2a\u5e26\u6765\u6e90\u7684\u77e5\u8bc6\u539f\u5b50\u548c\u4e00\u5f20\u4e0b\u4e00\u6b65\u5361\u3002"),
            validation_method=_guided_text(context, "Confirm the resource is trusted before using it.", "\u4f7f\u7528\u524d\u786e\u8ba4\u8d44\u6599\u53ef\u4fe1\u3002"),
            status="needs_primer",
        )

    if pack == _GUIDED_SCENARIO_PACK_DEPENDENCY:
        focus = _guided_pack_focus(context, _guided_text(context, "dependency and API mastery", "\u4f9d\u8d56\u4e0e API \u638c\u63e1"))
        if card_type == "flash":
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                scenario_pack=pack,
                title=_guided_text(context, "Flash: Dependency/API safe usage", "\u95ea\u8bb0\uff1a\u4f9d\u8d56/API \u5b89\u5168\u4f7f\u7528"),
                why_now=_guided_text(context, "Recall a capability, sharp edge, and safe rule before relying on the API.", "\u4f9d\u8d56 API \u524d\uff0c\u5148\u56de\u5fc6\u4e00\u9879\u80fd\u529b\u3001\u4e00\u4e2a\u8fb9\u7f18\u4e0e\u4e00\u6761\u5b89\u5168\u89c4\u5219\u3002"),
                focus_area=focus,
                target_skill=_guided_pack_skill(context, focus),
                knowledge_type="dependency_mastery",
                question=_guided_text(context, "What capability, sharp edge, and safe usage rule matter for this dependency/API?", "\u8fd9\u4e2a\u4f9d\u8d56/API \u7684\u54ea\u9879\u80fd\u529b\u3001\u8fb9\u7f18\u548c\u5b89\u5168\u4f7f\u7528\u89c4\u5219\u6700\u91cd\u8981\uff1f"),
                context=_guided_text(context, "Answer from one declared dependency/API context.", "\u4ece\u4e00\u4e2a\u5df2\u58f0\u660e\u7684\u4f9d\u8d56/API \u4e0a\u4e0b\u6587\u4f5c\u7b54\u3002"),
                answer_mode="text",
                expected_answer=_guided_text(context, "State one capability, one sharp edge, and one safe rule tied to the real context.", "\u8bf4\u660e\u4e00\u9879\u80fd\u529b\u3001\u4e00\u4e2a\u8fb9\u7f18\u548c\u4e00\u6761\u7ed1\u5b9a\u771f\u5b9e\u4e0a\u4e0b\u6587\u7684\u5b89\u5168\u89c4\u5219\u3002"),
                validation_method=_guided_text(context, "Check the answer against one real usage context.", "\u7528\u4e00\u4e2a\u771f\u5b9e\u4f7f\u7528\u4e0a\u4e0b\u6587\u6838\u5bf9\u7b54\u6848\u3002"),
                hint_ladder=[
                    _guided_text(
                        context,
                        "Start with the verified import, call, or declaration.",
                        "\u5148\u4ece\u5df2\u9a8c\u8bc1\u7684\u5bfc\u5165\u3001\u8c03\u7528\u6216\u58f0\u660e\u5f00\u59cb\u3002",
                    ),
                    _guided_text(
                        context,
                        "Name one observable output before describing an edge case.",
                        "\u5148\u8bf4\u660e\u4e00\u4e2a\u53ef\u89c2\u5bdf\u8f93\u51fa\uff0c\u518d\u63cf\u8ff0\u8fb9\u7f18\u60c5\u51b5\u3002",
                    ),
                ],
                common_mistakes=[
                    _guided_text(
                        context,
                        "Treating a package name or free-form hint as proof of usage.",
                        "\u628a\u5305\u540d\u6216\u81ea\u7531\u63d0\u793a\u5f53\u4f5c\u4f7f\u7528\u8bc1\u636e\u3002",
                    ),
                    _guided_text(
                        context,
                        "Claiming mastery without one checked output.",
                        "\u6ca1\u6709\u4e00\u4e2a\u5df2\u68c0\u67e5\u8f93\u51fa\u5c31\u58f0\u79f0\u5df2\u638c\u63e1\u3002",
                    ),
                ],
                feedback={
                    "correct": _guided_text(
                        context,
                        "Good. The API claim is tied to a verified use and output.",
                        "\u5f88\u597d\u3002\u8fd9\u4e2a API \u5224\u65ad\u5df2\u7ed1\u5b9a\u5230\u53ef\u9a8c\u8bc1\u7684\u4f7f\u7528\u4e0e\u8f93\u51fa\u3002",
                    ),
                    "incorrect": _guided_text(
                        context,
                        "Return to the verified usage and record one observable output.",
                        "\u56de\u5230\u5df2\u9a8c\u8bc1\u7684\u4f7f\u7528\u5904\uff0c\u8bb0\u5f55\u4e00\u4e2a\u53ef\u89c2\u5bdf\u8f93\u51fa\u3002",
                    ),
                },
                next_after_completion=_guided_text(
                    context,
                    "Return with the verified output and one checked edge case.",
                    "\u5e26\u56de\u5df2\u9a8c\u8bc1\u8f93\u51fa\u548c\u4e00\u4e2a\u5df2\u68c0\u67e5\u7684\u8fb9\u7f18\u60c5\u51b5\u3002",
                ),
                status="needs_primer",
            )
        return TrainingCardCandidateSnapshot(
            card_type="practice",
            scenario_pack=pack,
            title=_guided_text(context, "Practice: Verify one dependency/API capability", "\u7ec3\u4e60\uff1a\u9a8c\u8bc1\u4e00\u9879\u4f9d\u8d56/API \u80fd\u529b"),
            why_now=_guided_text(context, "Mastery needs one verified output in the real API context.", "\u638c\u63e1\u9700\u8981\u5728\u771f\u5b9e API \u4e0a\u4e0b\u6587\u4e2d\u4ea7\u751f\u4e00\u4e2a\u5df2\u9a8c\u8bc1\u8f93\u51fa\u3002"),
            focus_area=focus,
            target_skill=_guided_pack_skill(context, focus),
            problem_statement=_guided_text(context, "Use one real dependency/API capability and verify one output.", "\u4f7f\u7528\u4e00\u9879\u771f\u5b9e\u4f9d\u8d56/API \u80fd\u529b\u5e76\u9a8c\u8bc1\u4e00\u4e2a\u8f93\u51fa\u3002"),
            suggested_workspace_action=_guided_text(context, "Keep the exercise to one API call and one check.", "\u5c06\u7ec3\u4e60\u9650\u5b9a\u4e3a\u4e00\u6b21 API \u8c03\u7528\u548c\u4e00\u6b21\u68c0\u67e5\u3002"),
            deliverable=_guided_text(context, "One verified output and one safe usage note.", "\u4e00\u4e2a\u5df2\u9a8c\u8bc1\u8f93\u51fa\u548c\u4e00\u6761\u5b89\u5168\u4f7f\u7528\u7b14\u8bb0\u3002"),
            validation_method=_guided_text(context, "Run one focused check against the dependency/API output.", "\u9488\u5bf9\u4f9d\u8d56/API \u8f93\u51fa\u8fd0\u884c\u4e00\u6b21\u805a\u7126\u68c0\u67e5\u3002"),
            status="needs_primer",
        )

    if card_type == "flash":
        if pack == _GUIDED_SCENARIO_PACK_REMOTE:
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                scenario_pack=pack,
                title="Flash: Remote workspace boundary",
                focus_area=_guided_pack_focus(context, "VS Code remote workspace"),
                target_skill=_guided_pack_skill(context, "remote workspace boundary"),
                knowledge_type="engineering_concept",
                question="When should Trainer keep the API key local instead of storing it in the workspace for a remote VS Code session?",
                context=context.context_hint or "Use the remote workspace boundary before trusting deeper coaching.",
                answer_mode="text",
                expected_answer=(
                    "Keep the key local with ui_proxy when the remote host is shared or not fully trusted. "
                    "Use workspace_secret only when the remote machine and file boundary are understood and trustworthy."
                ),
                hint_ladder=[
                    "Start with the workspace type: SSH, tunnels, dev container, WSL, or local.",
                    "Then ask which host owns the files and secret storage.",
                    "Only after that decide whether credentials should stay local or remote.",
                ],
                common_mistakes=[
                    "Assuming every remote machine should store the API key remotely.",
                    "Treating the resource sandbox like the project workspace boundary.",
                ],
                feedback={
                    "correct": "Good. You tied credential mode to trust and host ownership.",
                    "incorrect": "Decide the host and trust boundary first, then choose the credential mode.",
                },
                next_after_completion="Return with the boundary rule, then continue the paired remote practice step.",
                difficulty="medium",
            )
        if pack == _GUIDED_SCENARIO_PACK_DEBUG:
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                scenario_pack=pack,
                title="Flash: Minimal debug loop",
                focus_area=_guided_pack_focus(context, "VS Code debugging"),
                target_skill=_guided_pack_skill(context, "debug loop design"),
                knowledge_type="engineering_concept",
                question="What is the smallest trustworthy debug loop before you change code?",
                context=context.context_hint or "The goal is to prove where the bad state begins, not to tour the whole stack.",
                answer_mode="text",
                expected_answer=(
                    "Reproduce the failure, pause at the first useful breakpoint or exception boundary, "
                    "and record the first verified wrong value or branch before editing."
                ),
                hint_ladder=[
                    "Start with a failing repro you can repeat.",
                    "Then pause where the state first changes, not where the symptom ends.",
                    "Only after that record the first wrong value or branch.",
                ],
                common_mistakes=[
                    "Changing code before the failure is reproducible.",
                    "Putting breakpoints after the state is already corrupted.",
                ],
                feedback={
                    "correct": "Nice. The loop is small enough to trust.",
                    "incorrect": "Shrink the loop to one repro, one pause, and one verified finding.",
                },
                next_after_completion="Return with the debug rule, then open the paired practice card in the real failure path.",
                difficulty="medium",
            )
        return TrainingCardCandidateSnapshot(
            card_type="flash",
            scenario_pack=pack,
            title="Flash: Function guidance contract",
            focus_area=_guided_pack_focus(context, "function guidance"),
            target_skill=_guided_pack_skill(context, "function contract recovery"),
            knowledge_type="engineering_concept",
            question="What do hover, signature help, and go-to-definition each prove about a function?",
            context=context.context_hint or "Use editor guidance to verify a contract before you edit a live call site.",
            answer_mode="text",
            expected_answer=(
                "Hover gives the quick summary, signature help confirms parameters at the call site, "
                "and go-to-definition plus real references prove the actual implementation boundary."
            ),
            hint_ladder=[
                "Hover is the fast summary, not the final proof.",
                "Signature help is strongest when you are inside a real call site.",
                "Definition and references confirm what really owns the contract.",
            ],
            common_mistakes=[
                "Treating autocomplete as a verified contract.",
                "Reading the hover text without checking a real caller or definition.",
            ],
            feedback={
                "correct": "Good. You separated quick hints from the real source of truth.",
                "incorrect": "Distinguish quick editor hints from the definition and live call sites that prove the contract.",
            },
            next_after_completion="Return with the contract rule, then recover one real call site in the paired practice step.",
            difficulty="medium",
        )

    if pack == _GUIDED_SCENARIO_PACK_REMOTE:
        return TrainingCardCandidateSnapshot(
            card_type="practice",
            status="needs_primer",
            scenario_pack=pack,
            title="Practice: Verify the remote workspace boundary",
            focus_area=_guided_pack_focus(context, "VS Code remote workspace"),
            target_skill=_guided_pack_skill(context, "remote workspace boundary"),
            scenario=(
                context.context_hint
                or "You are coaching through Remote SSH, WSL, tunnels, or a dev container and need one honest boundary check before deeper work."
            ),
            problem_statement=(
                "Prove which machine owns the workspace files, which credential mode is safe, "
                "and how Trainer should explain that boundary before any deeper coaching continues."
            ),
            suggested_workspace_action=(
                "Inspect one real workspace URI or path, then explain the safe credential mode in one sentence before touching code."
            ),
            api_hints=[
                "detectRemoteWorkspaceType(uri)",
                "getRecommendedCredentialMode(workspaceType)",
                "isCredentialModeSecureForWorkspace(mode, workspaceType)",
            ],
            constraints=[
                "Do not patch project files just to test the remote boundary.",
                "Keep the proof to one workspace path, one credential decision, and one recovery note.",
            ],
            deliverable="A short remote-boundary judgment with one confirmed workspace path and one credential-mode decision.",
            self_check=[
                "Can you name which host owns the workspace files?",
                "Can you explain whether the API key should stay local or remote here?",
                "Did you verify one real path or storage boundary without changing project code?",
            ],
            validation_method="Read the current workspace metadata, name the remote type, and confirm one concrete path or credential boundary.",
            learner_deliverables=[
                "Name the remote workspace type and the host that owns the files.",
                "Confirm whether the API key should stay local or remote for this workspace.",
                "Bring back one concrete path or setting that proves the boundary.",
            ],
            verification_steps=[
                "Capture the current remote surface (SSH / tunnels / dev container / WSL / local).",
                "Confirm one resolved workspace path or mount point.",
                "Explain the safe credential mode and why Trainer should use it here.",
            ],
            expected_symbols=[
                "detectRemoteWorkspaceType",
                "getRecommendedCredentialMode",
                "isCredentialModeSecureForWorkspace",
            ],
            hint_ladder=[
                "Start with the workspace URI or remote name.",
                "Then decide whether credentials should stay local or remote.",
                "Finally prove the boundary with one real path or storage fact.",
            ],
            common_mistakes=[
                "Assuming every remote machine should store the API key remotely.",
                "Treating the resource sandbox like the project workspace boundary.",
            ],
            stuck_recovery="If the path story is fuzzy, stop and prove only one thing: which host owns the workspace files.",
            reflection_prompt="Which part of the remote boundary was unclear before you checked a real path?",
            success_signal="You can explain the remote boundary in one sentence and support it with one real path or credential fact.",
            return_with="Return with the remote type, the confirmed path, and the credential decision.",
            next_after_completion="Return with the remote boundary proof",
            difficulty="medium",
        )
    if pack == _GUIDED_SCENARIO_PACK_DEBUG:
        return TrainingCardCandidateSnapshot(
            card_type="practice",
            status="needs_primer",
            scenario_pack=pack,
            title="Practice: Narrow the debug loop",
            focus_area=_guided_pack_focus(context, "VS Code debugging"),
            target_skill=_guided_pack_skill(context, "debug loop design"),
            scenario=context.context_hint or "A file is failing and you need one minimal VS Code debug loop before changing more code.",
            problem_statement=(
                "Build one minimal debug loop that reproduces the issue, stops where the state first changes, "
                "and returns one verified finding."
            ),
            suggested_workspace_action="Pick one failing command or file, set the first useful breakpoint at the state boundary, and run the smallest repro.",
            api_hints=[
                "launch.json configurations",
                "Conditional breakpoints and exception breakpoints",
                "Watch expressions or Debug Console for the first bad value",
            ],
            constraints=[
                "Do not refactor while you still cannot reproduce the bug.",
                "Prefer one breakpoint and one failing path over a full debug tour.",
            ],
            deliverable="A reproducible failing step plus one verified explanation of where the state diverges.",
            self_check=[
                "Can you reproduce the failure on demand?",
                "Did at least one breakpoint or exception pause at the right boundary?",
                "Can you name the first wrong value or branch, not just the final symptom?",
            ],
            validation_method="Reproduce once, pause at the boundary, and record the first verified bad state.",
            learner_deliverables=[
                "Write down the smallest repro step.",
                "Pause at the first useful breakpoint or exception boundary.",
                "Record the first verified wrong value, branch, or missing state.",
            ],
            verification_steps=[
                "Run the smallest failing repro.",
                "Pause at the first useful breakpoint or exception.",
                "Write down the first verified wrong value or branch.",
            ],
            expected_symbols=["launch.json", "breakpoint", "Debug Console"],
            hint_ladder=[
                "Start by making the failure repeat on demand.",
                "Then move the breakpoint earlier until the state first changes.",
                "Only after that record the first wrong value or branch.",
            ],
            common_mistakes=[
                "Changing code before the failure is reproducible.",
                "Setting breakpoints after the state is already corrupted.",
            ],
            stuck_recovery="If every breakpoint feels noisy, move it earlier and choose the first state transition you can explain.",
            reflection_prompt="What did the debugger prove that logs or guesswork did not?",
            success_signal="You can state where the bad state first appears and what evidence proved it.",
            return_with="Return with the repro step, the pause location, and the first wrong value.",
            next_after_completion="Return with the debug evidence",
            difficulty="medium",
        )
    return TrainingCardCandidateSnapshot(
        card_type="practice",
        status="needs_primer",
        scenario_pack=pack,
        title="Practice: Recover a function contract with editor guidance",
        focus_area=_guided_pack_focus(context, "function guidance"),
        target_skill=_guided_pack_skill(context, "function contract recovery"),
        scenario=context.context_hint or "You need to understand an unfamiliar function using hover, signature help, definition, and one real call site.",
        problem_statement=(
            "Use VS Code function guidance to recover one function's contract: what it expects, "
            "what it returns, and which call site proves it."
        ),
        suggested_workspace_action="Start from one live call site, then inspect hover, signature help, and definition before editing anything.",
        api_hints=[
            "Hover / Peek Definition",
            "Signature Help (parameter hints)",
            "Go to Definition / Find All References",
        ],
        constraints=[
            "Do not copy an implementation before you understand the contract.",
            "Keep the investigation to one function and one call site.",
        ],
        deliverable="A short function-contract note plus one learner-authored change or explanation that respects it.",
        self_check=[
            "Can you name the parameters and return shape?",
            "Did you inspect at least one real caller?",
            "Can you explain one common misuse before editing?",
        ],
        validation_method="Cross-check hover, signature help, and one real reference until the contract is stable.",
        learner_deliverables=[
            "Open one real call site.",
            "Confirm the parameter and return contract from editor guidance or definition.",
            "Explain one misuse or edge case before editing.",
        ],
        verification_steps=[
            "Check hover or signature help from a live call site.",
            "Open the definition or a real caller/reference.",
            "Write down the contract and one safe next edit.",
        ],
        expected_symbols=["Hover", "Signature Help", "Go to Definition"],
        hint_ladder=[
            "Hover is the fast summary, not the final proof.",
            "Signature help is strongest when you are inside a real call site.",
            "Definition and references confirm what really owns the contract.",
        ],
        common_mistakes=[
            "Treating autocomplete as a verified contract.",
            "Reading the hover text without checking a real caller or definition.",
        ],
        stuck_recovery="If the signature is still vague, stop editing and inspect one more real caller or type definition.",
        reflection_prompt="Which editor hint gave the missing piece: hover, signature help, definition, or references?",
        success_signal="You can explain the function contract and make one small safe change without guessing.",
        return_with="Return with the function contract, one checked call site, and the safe next edit.",
        next_after_completion="Return with the function contract",
        difficulty="medium",
    )


def _guided_context_for_pack(
    pack: str,
    context: CardGenerationContext,
) -> CardGenerationContext:
    if pack == _GUIDED_SCENARIO_PACK_DEPENDENCY:
        # A free-form hint must never masquerade as dependency usage evidence.
        return context.model_copy(update={"context_hint": ""})
    if pack != _GUIDED_SCENARIO_PACK_RESOURCE:
        return context
    evidence, _, _, focus, summary = _resource_knowledge_evidence(context)
    if evidence is None or _guided_fact_text(evidence.resource_id, limit=160) != _guided_fact_text(
        context.resource_id,
        limit=160,
    ):
        focus = ""
        summary = ""
    return context.model_copy(
        update={
            # Resource focus and prose must come from the indexed evidence projection,
            # never from the client-supplied card fields.
            "focus_area": focus,
            "target_skill": focus,
            "context_hint": summary,
        }
    )
