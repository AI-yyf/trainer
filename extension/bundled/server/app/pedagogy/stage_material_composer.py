"""Stage material composition for learning-plan stages.

Composes a bounded set of teaching materials (study guide, cheat sheet,
exercise set, code examples) for one learning-plan stage. Generation asks the
LLM once for a single JSON payload covering all four material kinds; on
failure it retries once with a higher temperature, then falls back to a
deterministic, content-bearing skeleton assembled from the stage definition.
The composer never raises: callers always receive a usable list of assets.

Also exposes :func:`compose_principle_explainer_asset`, a deterministic
facade around :class:`PrincipleExplainerService` that converts a
``PrincipleNote`` into one persisted ``TeachingKnowledgeAsset``.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from ..core.models import TeachingAssetKind, TeachingKnowledgeAsset, TurnRequest
from ..training.card_generator import _parse_llm_json
from .principle_explainer import PrincipleExplainerService
from .service import LearnerState, TeachingDecision

logger = logging.getLogger(__name__)

_MAX_MATERIALS = 6
_MATERIAL_MAX_TOKENS = 4096
_DEFAULT_MATERIAL_LANGUAGE = "zh-CN"

# kind -> TeachingKnowledgeAsset text field that carries the full content.
_CONTENT_FIELD_BY_KIND: dict[str, str] = {
    "study_guide": "concept_card",
    "cheat_sheet": "exercise_seed",
    "exercise_set": "exercise_seed",
    "code_examples": "example",
}

_STAGE_MATERIAL_SYSTEM_PROMPT = (
    "You are a learning designer composing materials for one stage of a learning plan. "
    "Ground every material in the stage goal, outcomes, and exercises, the learner profile "
    "summary, and the provided indexed resource titles and teaching asset hints. Never cite "
    "a resource that was not provided.\n"
    "\n"
    "Respond with ONLY one JSON object, no prose and no code fences, shaped exactly like:\n"
    '{"materials": [{"kind": "<kind>", "title": "...", "summary": "...", "content": "...", '
    '"sources": ["..."]}]}\n'
    "Rules:\n"
    "- kind must be one of: study_guide, cheat_sheet, exercise_set, code_examples.\n"
    "- Include exactly one material for each of the four kinds.\n"
    "- content carries the full material text in markdown; summary is a one-sentence description.\n"
    "- sources lists the provided resource titles, teaching assets, or plan artifacts each "
    "material draws on."
)

_ZH_FALLBACK_LABELS: dict[str, str] = {
    "study_guide": "学习指南",
    "cheat_sheet": "速查表",
    "exercise_set": "练习集",
    "code_examples": "示例代码",
}

_EN_FALLBACK_LABELS: dict[str, str] = {
    "study_guide": "Study guide",
    "cheat_sheet": "Cheat sheet",
    "exercise_set": "Exercise set",
    "code_examples": "Code examples",
}


def _prefers_chinese(language: str | None) -> bool:
    return bool((language or "").strip().lower().startswith("zh"))


def _localized_text(english: str, chinese: str, language: str | None) -> str:
    return chinese if _prefers_chinese(language) else english


def _build_materials_user_prompt(
    *,
    plan_title: str,
    stage_title: str,
    stage_goal: str,
    stage_outcomes: list[str],
    stage_exercises: list[str],
    focus_area: str,
    profile_summary: str,
    indexed_resource_titles: list[str],
    teaching_asset_hints: list[str],
    language: str,
) -> str:
    lines = [
        f"Plan: {plan_title.strip() or '(untitled plan)'}",
        f"Stage: {stage_title.strip() or '(untitled stage)'}",
        f"Stage goal: {stage_goal.strip() or '(not provided)'}",
    ]
    if focus_area.strip():
        lines.append(f"Focus area: {focus_area.strip()}")
    lines.append("Stage outcomes:")
    lines.extend(f"- {outcome.strip()}" for outcome in stage_outcomes if outcome.strip())
    lines.append("Stage exercises:")
    lines.extend(f"- {exercise.strip()}" for exercise in stage_exercises if exercise.strip())
    lines.append(f"Learner profile summary: {profile_summary.strip() or '(not provided)'}")
    lines.append("Indexed resource titles available for grounding:")
    lines.extend(f"- {title.strip()}" for title in indexed_resource_titles if title.strip())
    lines.append("Existing teaching asset hints:")
    lines.extend(f"- {hint.strip()}" for hint in teaching_asset_hints if hint.strip())
    lines.append(f"Language: write every title, summary, content, and source note in {language}.")
    return "\n".join(lines)


def _extract_valid_materials(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Validate raw LLM materials: known kind, non-empty title and content, capped."""
    if not isinstance(data, dict):
        return []
    raw_materials = data.get("materials")
    if not isinstance(raw_materials, list):
        return []
    valid: list[dict[str, Any]] = []
    for item in raw_materials:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if kind not in _CONTENT_FIELD_BY_KIND or not title or not content:
            continue
        valid.append(item)
        if len(valid) >= _MAX_MATERIALS:
            break
    return valid


def _asset_from_material(
    material: dict[str, Any],
    *,
    workspace_id: str,
    stage_id: str,
    focus_area: str,
) -> TeachingKnowledgeAsset:
    """Convert one validated LLM material into a TeachingKnowledgeAsset."""
    kind = cast(TeachingAssetKind, str(material.get("kind") or "").strip())
    title = str(material.get("title") or "").strip()
    content = str(material.get("content") or "").strip()
    summary = str(material.get("summary") or "").strip() or content
    sources = [
        source.strip()
        for source in material.get("sources") or []
        if isinstance(source, str) and source.strip()
    ]
    payload: dict[str, Any] = {
        "kind": kind,
        "scope": "project",
        "workspace_id": workspace_id,
        "title": title,
        "summary": summary,
        "plan_stage_id": stage_id,
        "focus_area": focus_area,
        "origin": "manual",
        "source_ids": [f"plan_stage:{stage_id}"] if stage_id else [],
        "evidence_snippets": sources,
        "tags": ["stage-material"],
    }
    payload[_CONTENT_FIELD_BY_KIND[kind]] = content
    return TeachingKnowledgeAsset(**payload)


def _fallback_asset(
    kind: str,
    *,
    workspace_id: str,
    stage_id: str,
    stage_title: str,
    stage_goal: str,
    outcomes: list[str],
    exercises: list[str],
    focus_area: str,
    language: str | None,
) -> TeachingKnowledgeAsset:
    """Deterministic, content-bearing skeleton for one material kind."""
    outcome_bullets = "\n".join(f"- {outcome}" for outcome in outcomes)
    exercise_lines = "\n".join(
        f"{index}. {exercise.strip()}" for index, exercise in enumerate(exercises, start=1)
    ) or _localized_text(
        "No explicit exercises were attached; run one small verifiable practice per outcome above.",
        "本阶段没有显式练习；针对上面每一条结果各做一次可验证的小练习。",
        language,
    )
    topic = focus_area.strip() or stage_goal.strip() or stage_title.strip()
    title = _localized_text(
        f"{_EN_FALLBACK_LABELS[kind]}: {stage_title}",
        f"{_ZH_FALLBACK_LABELS[kind]}：{stage_title}",
        language,
    )
    summary = _localized_text(
        f"Skeleton {_EN_FALLBACK_LABELS[kind].lower()} for stage '{stage_title}', built from the "
        "stage goal and outcomes.",
        f"阶段「{stage_title}」的{_ZH_FALLBACK_LABELS[kind]}骨架，基于阶段目标与结果生成。",
        language,
    )

    if kind == "study_guide":
        content = _localized_text(
            f"This study guide covers the stage '{stage_title}'.\n\n"
            f"Stage goal: {stage_goal.strip() or '(not provided)'}\n\n"
            f"After this stage you should be able to:\n{outcome_bullets}\n\n"
            "How to use it: read the linked resources first, then self-check against each "
            "outcome; return to the Coach conversation with a concrete question when stuck.",
            f"本学习指南覆盖阶段「{stage_title}」。\n\n"
            f"阶段目标：{stage_goal.strip() or '（未提供）'}\n\n"
            f"完成本阶段后你应当能够：\n{outcome_bullets}\n\n"
            "使用方式：先通读关联资料，再逐条结果自查；遇到卡点回到 Coach 对话，带着具体问题继续。",
            language,
        )
    elif kind == "cheat_sheet":
        content = _localized_text(
            f"Cheat sheet for '{stage_title}'.\n\nKey points:\n{outcome_bullets}\n\n"
            "How to use it: when stuck mid-practice, check this sheet first, then return to the "
            "full study guide for context.",
            f"「{stage_title}」速查表。\n\n要点：\n{outcome_bullets}\n\n"
            "用法：练习卡住时先回看本表，再回到完整学习指南核对上下文。",
            language,
        )
    elif kind == "exercise_set":
        content = _localized_text(
            f"Exercise set for '{stage_title}'. Work through in order:\n{exercise_lines}\n\n"
            "After each item, record the evidence that proves your answer is correct.",
            f"「{stage_title}」练习集。按顺序完成：\n{exercise_lines}\n\n"
            "每题完成后记录：你用了什么证据证明自己答对了。",
            language,
        )
    else:  # code_examples
        content = _localized_text(
            f"Code example scaffold for '{stage_title}'.\n\n"
            f"Build one minimal example around '{topic}':\n"
            "1. Pick the smallest relevant file or function in the project.\n"
            "2. Run the smallest possible check after the change.\n"
            "3. Record the output and name which stage outcome it proves.",
            f"「{stage_title}」示例代码骨架。\n\n"
            f"围绕「{topic}」写一个最小示例：\n"
            "1. 选择项目中最小相关的文件或函数。\n"
            "2. 实现或修改后运行最小检查。\n"
            "3. 记录输出，并说明它证明了哪一条阶段结果。",
            language,
        )

    return TeachingKnowledgeAsset(
        kind=cast(TeachingAssetKind, kind),
        scope="project",
        workspace_id=workspace_id,
        title=title,
        summary=summary,
        plan_stage_id=stage_id,
        focus_area=focus_area,
        origin="manual",
        source_ids=[f"plan_stage:{stage_id}"] if stage_id else [],
        tags=["stage-material", "stage-material-fallback"],
        **{_CONTENT_FIELD_BY_KIND[kind]: content},
    )


class StageMaterialComposer:
    """Compose the four stage material kinds for one learning-plan stage.

    Mirrors the card generator philosophy: LLM content first, one transparent
    retry, deterministic content-bearing templates only as fallback, and never
    an exception surfaced to the caller.
    """

    def __init__(self, provider_service: Any | None = None, event_ledger: Any | None = None) -> None:
        self._provider = provider_service
        self._event_ledger = event_ledger

    async def compose_stage_materials(
        self,
        *,
        workspace_id: str,
        plan_title: str,
        stage_id: str,
        stage_title: str,
        stage_goal: str,
        stage_outcomes: list[str],
        stage_exercises: list[str],
        focus_area: str = "",
        profile_summary: str = "",
        indexed_resource_titles: list[str] | None = None,
        teaching_asset_hints: list[str] | None = None,
        response_language: str | None = None,
    ) -> list[TeachingKnowledgeAsset]:
        language = (response_language or _DEFAULT_MATERIAL_LANGUAGE).strip()
        resource_titles = [title for title in (indexed_resource_titles or []) if title.strip()]
        asset_hints = [hint for hint in (teaching_asset_hints or []) if hint.strip()]
        outcomes = [outcome for outcome in stage_outcomes if outcome.strip()]
        exercises = [exercise for exercise in stage_exercises if exercise.strip()]

        materials: list[dict[str, Any]] = []
        generation_source = "deterministic_fallback"
        if self._provider is not None:
            messages = [
                {"role": "system", "content": _STAGE_MATERIAL_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_materials_user_prompt(
                        plan_title=plan_title,
                        stage_title=stage_title,
                        stage_goal=stage_goal,
                        stage_outcomes=outcomes,
                        stage_exercises=exercises,
                        focus_area=focus_area,
                        profile_summary=profile_summary,
                        indexed_resource_titles=resource_titles,
                        teaching_asset_hints=asset_hints,
                        language=language,
                    ),
                },
            ]
            for attempt, temperature in ((1, 0.7), (2, 0.9)):
                try:
                    raw = await self._provider.chat_completion(
                        messages,
                        temperature=temperature,
                        max_tokens=_MATERIAL_MAX_TOKENS,
                    )
                    materials = _extract_valid_materials(_parse_llm_json(raw))
                except Exception:
                    logger.warning(
                        "Stage material LLM attempt %s failed for stage=%s",
                        attempt,
                        stage_id,
                        exc_info=True,
                    )
                    materials = []
                if materials:
                    generation_source = "llm" if attempt == 1 else "llm_retry"
                    break

        if materials:
            assets = [
                _asset_from_material(
                    material,
                    workspace_id=workspace_id,
                    stage_id=stage_id,
                    focus_area=focus_area,
                )
                for material in materials
            ]
        else:
            fallback_outcomes = outcomes or (
                [stage_goal.strip() or stage_title.strip()] if (stage_goal or stage_title).strip() else []
            )
            assets = [
                _fallback_asset(
                    kind,
                    workspace_id=workspace_id,
                    stage_id=stage_id,
                    stage_title=stage_title,
                    stage_goal=stage_goal,
                    outcomes=fallback_outcomes,
                    exercises=exercises,
                    focus_area=focus_area,
                    language=language,
                )
                for kind in _CONTENT_FIELD_BY_KIND
            ]

        self._record_generation_event(
            assets=assets,
            workspace_id=workspace_id,
            stage_id=stage_id,
            stage_title=stage_title,
            plan_title=plan_title,
            generation_source=generation_source,
        )
        return assets

    def _record_generation_event(
        self,
        *,
        assets: list[TeachingKnowledgeAsset],
        workspace_id: str,
        stage_id: str,
        stage_title: str,
        plan_title: str,
        generation_source: str,
    ) -> None:
        if self._event_ledger is None:
            return
        try:
            self._event_ledger.record_event(
                "stage_material_generated",
                actor="system",
                scope="pedagogy",
                project_id=workspace_id,
                source_chain=["stage_material_composer", generation_source],
                payload_ref={
                    "plan_title": plan_title,
                    "stage_id": stage_id,
                    "stage_title": stage_title,
                    "generation_source": generation_source,
                    "material_count": len(assets),
                },
                before_state_ref={},
                after_state_ref={"asset_ids": [asset.id for asset in assets]},
                reversibility="reversible",
                audit_note=(
                    f"Composed {len(assets)} stage materials ({generation_source}) "
                    f"for stage '{stage_title}'"
                ),
            )
        except Exception:
            logger.warning("Failed to record stage_material_generated event", exc_info=True)


def compose_principle_explainer_asset(
    *,
    workspace_id: str,
    principle: str,
    context: str = "",
    focus_area: str = "",
    response_language: str | None = None,
) -> TeachingKnowledgeAsset:
    """Deterministic facade: turn a :class:`PrincipleNote` into one concept asset.

    Never raises; on unexpected failure returns a minimal asset carrying the
    context text as the concept card.
    """
    normalized_principle = principle.strip()
    normalized_focus = focus_area.strip()
    try:
        request = TurnRequest(
            message=context.strip() or normalized_principle,
            workspace_id=workspace_id,
            response_language=response_language,
        )
        learner_state = LearnerState(
            current_confidence=0.5,
            frustration_level=0.2,
            attempt_count_recent=1,
            needs_rescue=False,
            needs_review=False,
            preferred_hint_depth="guided",
            learner_signal="steady",
            active_focus=normalized_focus,
        )
        decision = TeachingDecision(scenario="concept_teaching", focus_area=normalized_focus)
        note = PrincipleExplainerService().explain(
            request=request,
            learner_state=learner_state,
            decision=decision,
        )
        sections = [f"Principle: {note.current_principle}"]
        if context.strip():
            sections.append(f"Context: {context.strip()}")
        sections.extend(
            [
                f"Why this approach: {note.why_this_approach}",
                f"Common wrong intuition: {note.common_wrong_intuition}",
                f"Concrete anchor: {note.concrete_anchor}",
                f"Transferable lesson: {note.transferable_lesson}",
                f"Follow-up exercise: {note.follow_up_exercise}",
            ]
        )
        if note.related_checks:
            sections.append("Related checks:\n- " + "\n- ".join(note.related_checks))
        return TeachingKnowledgeAsset(
            kind="concept_card",
            scope="project",
            workspace_id=workspace_id,
            title=normalized_principle or note.current_principle,
            summary=note.why_this_approach,
            concept_card="\n\n".join(sections),
            why_it_matters=note.transferable_lesson,
            example=note.concrete_anchor,
            exercise_seed=note.follow_up_exercise,
            anti_pattern=note.common_wrong_intuition,
            focus_area=normalized_focus,
            scenario="concept_teaching",
            origin="manual",
            tags=["principle-explainer"],
        )
    except Exception:
        logger.warning("Principle explainer asset composition failed", exc_info=True)
        return TeachingKnowledgeAsset(
            kind="concept_card",
            scope="project",
            workspace_id=workspace_id,
            title=normalized_principle or normalized_focus or "Principle note",
            concept_card=context,
            focus_area=normalized_focus,
            scenario="concept_teaching",
            origin="manual",
            tags=["principle-explainer"],
        )
