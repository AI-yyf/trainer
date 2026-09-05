"""Map learning evidence into real pedagogy controls.

Consecutive failures degrade scaffolding. Consecutive successes raise
difficulty. One project scene never becomes global transferable mastery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .context_pressure import (
    PREFERENCE_HINT_KINDS,
    PREFERENCE_RAISE_KINDS,
    normalize_project_complexity,
    normalize_task_urgency,
    normalize_time_budget,
)

SUCCESS_OUTCOMES = frozenset({"code_landed", "tests_passed", "concept_answered_correctly"})
FAILURE_OUTCOMES = frozenset({"repeated_error", "evaluation", "task_abandoned", "blocked"})
DEGRADE_PREFERENCES = PREFERENCE_HINT_KINDS
RAISE_PREFERENCES = PREFERENCE_RAISE_KINDS


def pedagogy_evidence_confidence(
    *,
    verified_success: bool = False,
    success_count: int = 0,
    outcomes: list[Any] | None = None,
) -> float:
    """Map proof strength to confidence. Unverified success stays low-trust."""

    if verified_success:
        return 0.8
    if int(success_count or 0) > 0:
        return 0.25
    # Client-claimed pass/landed labels without evaluator+verified_result are not proof,
    # but they are still low-trust evidence that must not mint live objects.
    for item in outcomes or []:
        name = _outcome_name(item)
        if name in {"code_landed", "tests_passed"} and not _outcome_is_evaluator_verified(item):
            return 0.25
    return 0.5

Difficulty = Literal["easy", "medium", "hard"]
HintDepth = Literal["direct", "guided", "lighter"]
ChallengeLevel = Literal["lower", "steady", "raise"]
ExplanationMode = Literal["rebuild", "grounded", "transfer"]
ExplanationDepth = Literal["rebuild", "grounded", "transfer"]
CodeReveal = Literal["full", "scaffold", "withhold"]
PracticeType = Literal["recover", "focused", "stretch"]
ReviewFrequency = Literal["sooner", "normal", "later"]
MaterialRecommendation = Literal["simpler", "current", "transfer"]
NextPlanStep = Literal["shrink", "hold", "widen"]
PedagogyMode = Literal["socratic", "direct", "debug_guide"]


@dataclass(frozen=True, slots=True)
class LearningEvidenceSignals:
    success_streak: int = 0
    failure_streak: int = 0
    success_count: int = 0
    failure_count: int = 0
    repeated_failure: bool = False
    concept_success: bool = False
    abandoned: bool = False
    blocked: bool = False
    verified_success: bool = False
    historical_error_count: int = 0
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PedagogyControls:
    difficulty: Difficulty = "medium"
    hint_count: int = 2
    explanation_depth: ExplanationDepth = "grounded"
    code_reveal: CodeReveal = "scaffold"
    practice_type: PracticeType = "focused"
    review_frequency: ReviewFrequency = "normal"
    material_recommendation: MaterialRecommendation = "current"
    next_plan_step: NextPlanStep = "hold"
    should_reveal_code: bool = False
    challenge_level: ChallengeLevel = "steady"
    hint_depth: HintDepth = "guided"
    review_urgency: Literal["high", "normal", "low"] = "normal"
    explanation_mode: ExplanationMode = "grounded"
    next_step_bias: Literal["shrink", "steady", "widen"] = "steady"
    pedagogy_mode: PedagogyMode = "direct"
    success_streak: int = 0
    failure_streak: int = 0
    transfer_scene_count: int = 0
    transferable: bool = False
    time_budget: Literal["tight", "normal", "ample"] = "normal"
    project_complexity: Literal["simple", "moderate", "complex"] = "moderate"
    task_urgency: Literal["low", "medium", "high"] = "medium"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _casefold(value: Any) -> str:
    return _text(value).casefold()


def _outcome_name(item: Any) -> str:
    if isinstance(item, dict):
        return _casefold(item.get("outcome"))
    return _casefold(getattr(item, "outcome", ""))


def _outcome_summary(item: Any) -> str:
    if isinstance(item, dict):
        return _text(item.get("summary") or item.get("outcome"))
    return _text(getattr(item, "summary", "") or getattr(item, "outcome", ""))


def _missing_or_checks(item: Any) -> bool:
    if isinstance(item, dict):
        missing = item.get("missing_requirements") or item.get("missingRequirements") or []
        checks = item.get("checks") or []
        return bool(missing or checks)
    return bool(getattr(item, "missing_requirements", None) or getattr(item, "checks", None))


def _repetition_count(item: Any) -> int:
    if isinstance(item, dict):
        raw = item.get("repetition_count", item.get("repetitionCount", 1))
    else:
        raw = getattr(item, "repetition_count", 1)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _casefold(value) in {"1", "true", "yes"}


def _outcome_is_evaluator_verified(item: Any) -> bool:
    """Fail-closed: label alone is not proof. Need evaluator ack + non-empty verified_result."""

    if isinstance(item, dict):
        flag = item.get("verified_by_evaluator", item.get("verifiedByEvaluator", False))
        verified_result = _text(item.get("verified_result") or item.get("verifiedResult") or "")
    else:
        flag = getattr(item, "verified_by_evaluator", False)
        verified_result = _text(getattr(item, "verified_result", "") or "")
    return _truthy_flag(flag) and bool(verified_result)


def _counts_as_success_proof(item: Any) -> bool:
    name = _outcome_name(item)
    if name not in SUCCESS_OUTCOMES:
        return False
    if name in {"code_landed", "tests_passed"}:
        return _outcome_is_evaluator_verified(item)
    return True


def analyze_learning_evidence(outcomes: list[Any] | None, *, limit: int = 6) -> LearningEvidenceSignals:
    recent = list(outcomes or [])[: max(1, limit)]
    success_count = 0
    failure_count = 0
    repeated_failure = False
    concept_success = False
    abandoned = False
    blocked = False
    verified_success = False
    evidence: list[str] = []

    for item in recent:
        name = _outcome_name(item)
        # Overwrite key is concept+outcome+action; streak/count must use
        # repetition_count so identical consecutive signals still pace pedagogy.
        reps = max(1, _repetition_count(item))
        if _counts_as_success_proof(item):
            success_count += reps
        if name in FAILURE_OUTCOMES or _missing_or_checks(item):
            failure_count += reps
        if name in FAILURE_OUTCOMES and reps >= 2:
            repeated_failure = True
        if name == "concept_answered_correctly":
            concept_success = True
        if name == "task_abandoned":
            abandoned = True
        if name == "blocked":
            blocked = True
        if name in {"code_landed", "tests_passed"} and _outcome_is_evaluator_verified(item):
            verified_success = True
        if len(evidence) < 4:
            summary = _outcome_summary(item)
            if summary:
                evidence.append(summary)

    success_streak = 0
    for item in recent:
        if _counts_as_success_proof(item):
            success_streak += max(1, _repetition_count(item))
        else:
            break

    failure_streak = 0
    for item in recent:
        if _outcome_name(item) in FAILURE_OUTCOMES or _missing_or_checks(item):
            failure_streak += max(1, _repetition_count(item))
        else:
            break

    return LearningEvidenceSignals(
        success_streak=success_streak,
        failure_streak=failure_streak,
        success_count=success_count,
        failure_count=failure_count,
        repeated_failure=repeated_failure,
        concept_success=concept_success,
        abandoned=abandoned,
        blocked=blocked,
        verified_success=verified_success,
        historical_error_count=failure_count,
        evidence=tuple(evidence),
    )


def _can_recommend_transfer(*, transfer_scene_count: int, transfer_state: str) -> bool:
    return transfer_scene_count >= 2 or _casefold(transfer_state) == "transferable"


def resolve_pedagogy_controls(
    signals: LearningEvidenceSignals | None = None,
    *,
    success_streak: int | None = None,
    failure_streak: int | None = None,
    repeated_failure: bool = False,
    abandoned: bool = False,
    blocked: bool = False,
    concept_success: bool = False,
    verified_success: bool = False,
    historical_error_count: int = 0,
    transfer_scene_count: int = 0,
    transfer_state: str = "",
    user_preference: str = "",
    preferred_teaching_style: str = "",
    time_budget: str = "",
    task_urgency: str = "",
    evidence_confidence: float = 0.5,
    project_complexity: str = "",
    current_ability: str = "",
    affect_recovery: str = "",
) -> PedagogyControls:
    """Turn evidence into difficulty, hints, code reveal, review, and plan bias."""

    resolved = signals or LearningEvidenceSignals(
        success_streak=success_streak or 0,
        failure_streak=failure_streak or 0,
        success_count=max(success_streak or 0, 1 if concept_success or verified_success else 0),
        failure_count=max(failure_streak or 0, historical_error_count),
        repeated_failure=repeated_failure,
        concept_success=concept_success,
        abandoned=abandoned,
        blocked=blocked,
        verified_success=verified_success,
        historical_error_count=historical_error_count,
    )
    streak_success = resolved.success_streak if success_streak is None else success_streak
    streak_failure = resolved.failure_streak if failure_streak is None else failure_streak
    preference = _casefold(user_preference)
    style = _casefold(preferred_teaching_style)
    ability = _casefold(current_ability)
    urgency = normalize_task_urgency(task_urgency)
    budget = normalize_time_budget(time_budget)
    complexity = normalize_project_complexity(project_complexity)
    affect = _casefold(affect_recovery)
    transferable = _can_recommend_transfer(
        transfer_scene_count=transfer_scene_count,
        transfer_state=transfer_state,
    )

    live_struggle = (
        streak_failure >= 2
        or resolved.abandoned
        or abandoned
        or resolved.blocked
        or blocked
        or preference in DEGRADE_PREFERENCES
        or ability == "struggling"
        or affect == "overloaded"
    )
    lingering_failure = (
        streak_success == 0
        and (
            resolved.repeated_failure
            or repeated_failure
            or resolved.failure_count >= 3
        )
    )
    degrade = live_struggle or lingering_failure
    verified = resolved.verified_success or verified_success
    raise_ok = (
        not live_struggle
        and ability != "struggling"
        and (
            preference in RAISE_PREFERENCES
            or (
                evidence_confidence >= 0.4
                and ((streak_success >= 2 and verified) or (ability == "ahead" and verified))
            )
        )
    )

    if degrade:
        controls = PedagogyControls(
            difficulty="easy",
            hint_count=3,
            explanation_depth="rebuild",
            code_reveal="full",
            practice_type="recover",
            review_frequency="sooner",
            material_recommendation="simpler",
            next_plan_step="shrink",
            should_reveal_code=True,
            challenge_level="lower",
            hint_depth="direct",
            review_urgency="high",
            explanation_mode="rebuild",
            next_step_bias="shrink",
            pedagogy_mode="debug_guide",
            success_streak=streak_success,
            failure_streak=streak_failure,
            transfer_scene_count=transfer_scene_count,
            transferable=False,
        )
    elif raise_ok:
        controls = PedagogyControls(
            difficulty="hard",
            hint_count=1,
            explanation_depth="transfer" if transferable else "grounded",
            code_reveal="withhold",
            practice_type="stretch",
            review_frequency="later",
            material_recommendation="transfer" if transferable else "current",
            next_plan_step="widen",
            should_reveal_code=False,
            challenge_level="raise",
            hint_depth="lighter",
            review_urgency="low",
            explanation_mode="transfer" if resolved.concept_success or streak_success >= 2 else "grounded",
            next_step_bias="widen",
            pedagogy_mode=_raise_pedagogy_mode(style, affect),
            success_streak=streak_success,
            failure_streak=streak_failure,
            transfer_scene_count=transfer_scene_count,
            transferable=transferable,
        )
    else:
        hint_count = 2
        if historical_error_count >= 2 or resolved.failure_count >= 2:
            hint_count = 3
        if complexity == "complex":
            hint_count = min(3, hint_count + 1)
        explanation_mode: ExplanationMode = (
            "transfer" if resolved.concept_success else "grounded"
        )
        controls = PedagogyControls(
            difficulty="medium",
            hint_count=hint_count,
            explanation_depth="transfer" if transferable else "grounded",
            code_reveal="scaffold",
            practice_type="focused",
            review_frequency="normal",
            material_recommendation="transfer" if transferable else "current",
            next_plan_step="hold",
            should_reveal_code=False,
            challenge_level="steady",
            hint_depth="guided",
            review_urgency="low" if resolved.success_count >= 1 else "normal",
            explanation_mode=explanation_mode,
            next_step_bias="steady",
            pedagogy_mode=_steady_pedagogy_mode(style, affect, streak_failure),
            success_streak=streak_success,
            failure_streak=streak_failure,
            transfer_scene_count=transfer_scene_count,
            transferable=transferable,
        )
    return apply_context_pressure(
        controls,
        time_budget=budget,
        task_urgency=urgency,
        project_complexity=complexity,
        transferable=transferable,
    )


def apply_context_pressure(
    controls: PedagogyControls,
    *,
    time_budget: str = "normal",
    task_urgency: str = "medium",
    project_complexity: str = "moderate",
    transferable: bool | None = None,
) -> PedagogyControls:
    """Shorten scope and add scaffolding from real budget/complexity/urgency.

    Urgency and a tight budget never unlock transfer. High complexity refuses a
    huge next step. Low complexity plus a success streak can still stretch locally.
    """

    budget = normalize_time_budget(time_budget)
    urgency = normalize_task_urgency(task_urgency)
    complexity = normalize_project_complexity(project_complexity)
    can_transfer = controls.transferable if transferable is None else transferable
    compressed = budget == "tight" or urgency == "high"
    simple_stretch = complexity == "simple" and controls.success_streak >= 2 and not compressed

    difficulty = controls.difficulty
    hint_count = controls.hint_count
    explanation_depth = controls.explanation_depth
    code_reveal = controls.code_reveal
    practice_type = controls.practice_type
    review_frequency = controls.review_frequency
    material_recommendation = controls.material_recommendation
    next_plan_step = controls.next_plan_step
    should_reveal_code = controls.should_reveal_code
    challenge_level = controls.challenge_level
    hint_depth = controls.hint_depth
    review_urgency = controls.review_urgency
    explanation_mode = controls.explanation_mode
    next_step_bias = controls.next_step_bias
    pedagogy_mode = controls.pedagogy_mode

    if material_recommendation == "transfer" and not can_transfer:
        material_recommendation = "current"
        explanation_depth = "grounded" if explanation_depth == "transfer" else explanation_depth

    if compressed:
        next_plan_step = "shrink"
        next_step_bias = "shrink"
        hint_count = min(3, max(hint_count, 2))
        if hint_depth == "lighter":
            hint_depth = "guided"
        if code_reveal == "withhold":
            code_reveal = "scaffold"
            should_reveal_code = False
        if practice_type == "stretch":
            practice_type = "focused"
        if challenge_level == "raise":
            challenge_level = "steady"
        if difficulty == "hard":
            difficulty = "medium"
        if material_recommendation == "transfer":
            material_recommendation = "current"
        if urgency == "high":
            review_frequency = "sooner"
            review_urgency = "high"
            if pedagogy_mode == "socratic":
                pedagogy_mode = "direct"

    if complexity == "complex" and not simple_stretch:
        if next_plan_step == "widen":
            next_plan_step = "shrink" if compressed else "hold"
        if next_step_bias == "widen":
            next_step_bias = "shrink" if compressed else "steady"
        hint_count = min(3, max(hint_count, 2))
        if code_reveal == "withhold":
            code_reveal = "scaffold"
            should_reveal_code = False
        if material_recommendation == "transfer" and not can_transfer:
            material_recommendation = "current"

    return PedagogyControls(
        difficulty=difficulty,
        hint_count=hint_count,
        explanation_depth=explanation_depth,
        code_reveal=code_reveal,
        practice_type=practice_type,
        review_frequency=review_frequency,
        material_recommendation=material_recommendation,
        next_plan_step=next_plan_step,
        should_reveal_code=should_reveal_code,
        challenge_level=challenge_level,
        hint_depth=hint_depth,
        review_urgency=review_urgency,
        explanation_mode=explanation_mode,
        next_step_bias=next_step_bias,
        pedagogy_mode=pedagogy_mode,
        success_streak=controls.success_streak,
        failure_streak=controls.failure_streak,
        transfer_scene_count=controls.transfer_scene_count,
        transferable=can_transfer,
        time_budget=budget,
        project_complexity=complexity,
        task_urgency=urgency,
    )


def _raise_pedagogy_mode(style: str, affect: str) -> PedagogyMode:
    if affect in {"fragile", "overloaded"}:
        return "direct"
    if style in {"direct", "hands-on"}:
        return "direct"
    return "socratic"


def _steady_pedagogy_mode(style: str, affect: str, failure_streak: int) -> PedagogyMode:
    if affect == "overloaded" or failure_streak >= 1 and affect == "fragile":
        return "debug_guide"
    if style in {"socratic", "guided", "concept-first"}:
        return "socratic"
    if style in {"direct", "hands-on"}:
        return "direct"
    return "direct"


def refresh_controls_after_strategy(
    controls: PedagogyControls,
    *,
    challenge_level: str,
    hint_depth: str,
    review_urgency: str,
    explanation_mode: str,
    next_step_bias: str,
) -> PedagogyControls:
    """Keep strategy preference, then re-materialize structured training controls."""

    blended = resolve_pedagogy_controls(
        LearningEvidenceSignals(
            success_streak=controls.success_streak,
            failure_streak=controls.failure_streak,
            success_count=max(controls.success_streak, 1 if challenge_level == "raise" else 0),
            failure_count=max(controls.failure_streak, 1 if challenge_level == "lower" else 0),
            repeated_failure=challenge_level == "lower" and controls.failure_streak >= 1,
            concept_success=explanation_mode == "transfer",
            abandoned=next_step_bias == "shrink" and challenge_level == "lower",
            verified_success=challenge_level == "raise",
            historical_error_count=controls.failure_streak,
        ),
        transfer_scene_count=controls.transfer_scene_count,
        transfer_state="transferable" if controls.transferable else "",
        user_preference="too_hard" if challenge_level == "lower" else "too_simple" if challenge_level == "raise" else "",
        time_budget=controls.time_budget,
        task_urgency=controls.task_urgency,
        project_complexity=controls.project_complexity,
    )
    return apply_context_pressure(
        PedagogyControls(
            difficulty=blended.difficulty,
            hint_count=blended.hint_count,
            explanation_depth=blended.explanation_depth,
            code_reveal=blended.code_reveal,
            practice_type=blended.practice_type,
            review_frequency=blended.review_frequency,
            material_recommendation=blended.material_recommendation,
            next_plan_step=blended.next_plan_step,
            should_reveal_code=blended.should_reveal_code,
            challenge_level=(
                "lower" if challenge_level == "lower" else "raise" if challenge_level == "raise" else "steady"
            ),
            hint_depth="direct" if hint_depth == "direct" else "lighter" if hint_depth == "lighter" else "guided",
            review_urgency="high" if review_urgency == "high" else "low" if review_urgency == "low" else "normal",
            explanation_mode=(
                "rebuild"
                if explanation_mode == "rebuild"
                else "transfer"
                if explanation_mode == "transfer"
                else "grounded"
            ),
            next_step_bias="shrink" if next_step_bias == "shrink" else "widen" if next_step_bias == "widen" else "steady",
            pedagogy_mode=blended.pedagogy_mode,
            success_streak=controls.success_streak,
            failure_streak=controls.failure_streak,
            transfer_scene_count=controls.transfer_scene_count,
            transferable=blended.transferable,
            time_budget=controls.time_budget,
            project_complexity=controls.project_complexity,
            task_urgency=controls.task_urgency,
        ),
        time_budget=controls.time_budget,
        task_urgency=controls.task_urgency,
        project_complexity=controls.project_complexity,
        transferable=blended.transferable,
    )


def controls_from_profile(profile: Any) -> PedagogyControls | None:
    if profile is None:
        return None
    if isinstance(profile, dict):
        def getter(key: str, default: Any = None) -> Any:
            return profile.get(key, default)
    else:
        def getter(key: str, default: Any = None) -> Any:
            return getattr(profile, key, default)

    def pick(key: str, *aliases: str, default: str = "") -> str:
        for candidate in (key, *aliases):
            value = _casefold(getter(candidate, ""))
            if value:
                return value
        return default

    scene_count_raw = getter("transfer_scene_count", getter("transferSceneCount", 0))
    try:
        scene_count = int(scene_count_raw or 0)
    except (TypeError, ValueError):
        scene_count = 0
    hint_raw = getter("hint_count", getter("hintCount", 2))
    try:
        hint_count = max(1, min(5, int(hint_raw or 2)))
    except (TypeError, ValueError):
        hint_count = 2
    difficulty_value = pick("difficulty", default="medium")
    difficulty: Difficulty = (
        "easy" if difficulty_value == "easy" else "hard" if difficulty_value == "hard" else "medium"
    )
    depth_value = pick("explanation_depth", "explanationDepth", default="grounded")
    explanation_depth: ExplanationDepth = (
        "rebuild" if depth_value == "rebuild" else "transfer" if depth_value == "transfer" else "grounded"
    )
    reveal_value = pick("code_reveal", "codeReveal", default="scaffold")
    code_reveal: CodeReveal = (
        "full" if reveal_value == "full" else "withhold" if reveal_value == "withhold" else "scaffold"
    )
    practice_value = pick("practice_type", "practiceType", default="focused")
    practice_type: PracticeType = (
        "recover" if practice_value == "recover" else "stretch" if practice_value == "stretch" else "focused"
    )
    frequency_value = pick("review_frequency", "reviewFrequency", default="normal")
    review_frequency: ReviewFrequency = (
        "sooner" if frequency_value == "sooner" else "later" if frequency_value == "later" else "normal"
    )
    material_value = pick("material_recommendation", "materialRecommendation", default="current")
    material_recommendation: MaterialRecommendation = (
        "simpler" if material_value == "simpler" else "transfer" if material_value == "transfer" else "current"
    )
    next_plan_value = pick("next_plan_step", "nextPlanStep")
    bias_value = pick("next_step_bias", "nextStepBias", default="steady")
    next_plan_step: NextPlanStep = (
        "shrink"
        if next_plan_value == "shrink" or (not next_plan_value and bias_value == "shrink")
        else "widen"
        if next_plan_value == "widen" or (not next_plan_value and bias_value == "widen")
        else "hold"
    )
    challenge_value = pick("challenge_level", "challengeLevel", default="steady")
    challenge_level: ChallengeLevel = (
        "lower" if challenge_value == "lower" else "raise" if challenge_value == "raise" else "steady"
    )
    hint_value = pick("hint_depth", "hintDepth", default="guided")
    hint_depth: HintDepth = (
        "direct" if hint_value == "direct" else "lighter" if hint_value == "lighter" else "guided"
    )
    urgency_value = pick("review_urgency", "reviewUrgency", default="normal")
    review_urgency: Literal["high", "normal", "low"] = (
        "high" if urgency_value == "high" else "low" if urgency_value == "low" else "normal"
    )
    mode_value = pick("explanation_mode", "explanationMode", default="grounded")
    explanation_mode: ExplanationMode = (
        "rebuild" if mode_value == "rebuild" else "transfer" if mode_value == "transfer" else "grounded"
    )
    next_bias: Literal["shrink", "steady", "widen"] = (
        "shrink" if bias_value == "shrink" else "widen" if bias_value == "widen" else "steady"
    )
    pedagogy_value = pick("pedagogy_mode", "pedagogyMode", default="direct")
    pedagogy_mode: PedagogyMode = (
        "socratic"
        if pedagogy_value == "socratic"
        else "debug_guide"
        if pedagogy_value == "debug_guide"
        else "direct"
    )
    try:
        success_streak = int(getter("success_streak", getter("successStreak", 0)) or 0)
    except (TypeError, ValueError):
        success_streak = 0
    try:
        failure_streak = int(getter("failure_streak", getter("failureStreak", 0)) or 0)
    except (TypeError, ValueError):
        failure_streak = 0
    return PedagogyControls(
        difficulty=difficulty,
        hint_count=hint_count,
        explanation_depth=explanation_depth,
        code_reveal=code_reveal,
        practice_type=practice_type,
        review_frequency=review_frequency,
        material_recommendation=material_recommendation,
        next_plan_step=next_plan_step,
        should_reveal_code=bool(getter("should_reveal_code", getter("shouldRevealCode", False))),
        challenge_level=challenge_level,
        hint_depth=hint_depth,
        review_urgency=review_urgency,
        explanation_mode=explanation_mode,
        next_step_bias=next_bias,
        pedagogy_mode=pedagogy_mode,
        success_streak=success_streak,
        failure_streak=failure_streak,
        transfer_scene_count=scene_count,
        transferable=_can_recommend_transfer(
            transfer_scene_count=scene_count,
            transfer_state=_text(getter("transfer_state", getter("transferState", ""))),
        ),
        time_budget=normalize_time_budget(getter("time_budget", getter("timeBudget", "normal"))),
        project_complexity=normalize_project_complexity(
            getter("project_complexity", getter("projectComplexity", "moderate"))
        ),
        task_urgency=normalize_task_urgency(getter("task_urgency", getter("taskUrgency", "medium"))),
    )


def routing_learner_overrides(controls: PedagogyControls | None) -> dict[str, object]:
    if controls is None:
        return {"difficulty_preference": "medium", "needs_rescue": False}
    return {
        "difficulty_preference": controls.difficulty,
        "needs_rescue": controls.challenge_level == "lower" or controls.practice_type == "recover",
        "preferred_practice_type": controls.practice_type,
        "review_frequency": controls.review_frequency,
        "material_recommendation": controls.material_recommendation,
        "time_budget": controls.time_budget,
        "project_complexity": controls.project_complexity,
        "task_urgency": controls.task_urgency,
    }


def review_after_days_for_frequency(frequency: str, *, default: int = 2) -> int:
    normalized = _casefold(frequency)
    if normalized == "sooner":
        return 1
    if normalized == "later":
        return 4
    return default


def apply_review_frequency_bias(interval_days: int, frequency: str) -> int:
    normalized = _casefold(frequency)
    if normalized == "sooner":
        return max(1, interval_days // 2 or 1)
    if normalized == "later":
        return max(interval_days * 2, interval_days + 2)
    return max(0, interval_days)


def apply_controls_to_context(context: Any, controls: PedagogyControls | None) -> Any:
    if context is None or controls is None:
        return context
    update = {
        "difficulty": controls.difficulty,
        "hint_count": controls.hint_count,
        "code_reveal": controls.code_reveal,
        "practice_type": controls.practice_type,
        "review_frequency": controls.review_frequency,
        "material_recommendation": controls.material_recommendation,
        "next_plan_step": controls.next_plan_step,
        "should_reveal_code": controls.should_reveal_code,
        "pedagogy_mode": controls.pedagogy_mode,
    }
    copier = getattr(context, "model_copy", None)
    if callable(copier):
        return copier(update=update)
    for key, value in update.items():
        setattr(context, key, value)
    return context


def _localized(en: str, zh: str, language: str | None) -> str:
    return zh if _casefold(language).startswith("zh") else en


def _resize_hint_ladder(hints: list[str], count: int, language: str | None) -> list[str]:
    extras = [
        _localized("Name the smallest failing check first.", "先点名最小的失败检查。", language),
        _localized("Change one boundary, then re-run that check.", "只改一条边界，然后重跑那条检查。", language),
        _localized(
            "Write expected vs actual for that one check before widening.",
            "先写下这一条检查的期望与实际，再扩大范围。",
            language,
        ),
    ]
    cleaned = [item for item in hints if _text(item)]
    if len(cleaned) >= count:
        return cleaned[:count]
    for extra in extras:
        if extra not in cleaned:
            cleaned.append(extra)
        if len(cleaned) >= count:
            break
    return cleaned[:count] or extras[:count]


def _withhold_code_dump(text: str, language: str | None) -> str:
    cleaned = _text(text)
    looks_like_code = "```" in cleaned or "\ndef " in f"\n{cleaned}" or "\nfunction " in f"\n{cleaned}"
    if not looks_like_code:
        return cleaned
    return _localized(
        "Do not paste a full solution. Write the smallest next change yourself, then verify it.",
        "不要贴完整解法。自己写下最小的下一步改动，然后再验证。",
        language,
    )


def apply_controls_to_card(card: Any, controls: PedagogyControls | None, *, language: str | None = None) -> Any:
    if card is None or controls is None:
        return card
    hints = list(getattr(card, "hint_ladder", None) or [])
    update: dict[str, Any] = {
        "difficulty": controls.difficulty,
        "hint_ladder": _resize_hint_ladder(hints, controls.hint_count, language),
    }
    action = _text(getattr(card, "suggested_workspace_action", ""))
    if controls.code_reveal == "withhold" and action:
        update["suggested_workspace_action"] = _withhold_code_dump(action, language)
    if controls.next_plan_step == "shrink":
        update["next_after_completion"] = _localized(
            "Stay on this recovery slice until one check passes.",
            "先停在这个恢复切片，直到一条检查通过。",
            language,
        )
    elif controls.next_plan_step == "widen" and controls.transferable:
        update["next_after_completion"] = _localized(
            "Apply the same move in a second scene before calling it transferable.",
            "把同样的动作用到第二个场景，才能记为可迁移。",
            language,
        )
    elif controls.next_plan_step == "widen":
        update["next_after_completion"] = _localized(
            "Stretch the next local slice. Do not treat this project win as global mastery.",
            "把下一步做难一点，但不要把这次项目成功当成全局掌握。",
            language,
        )
    copier = getattr(card, "model_copy", None)
    if callable(copier):
        return copier(update=update)
    for key, value in update.items():
        setattr(card, key, value)
    return card


def profile_kwargs_from_controls(controls: PedagogyControls, *, summary: str, evidence: list[str]) -> dict[str, Any]:
    return {
        "challenge_level": controls.challenge_level,
        "hint_depth": controls.hint_depth,
        "review_urgency": controls.review_urgency,
        "explanation_mode": controls.explanation_mode,
        "next_step_bias": controls.next_step_bias,
        "summary": summary,
        "evidence": evidence[:4],
        "difficulty": controls.difficulty,
        "hint_count": controls.hint_count,
        "explanation_depth": controls.explanation_depth,
        "code_reveal": controls.code_reveal,
        "practice_type": controls.practice_type,
        "review_frequency": controls.review_frequency,
        "material_recommendation": controls.material_recommendation,
        "next_plan_step": controls.next_plan_step,
        "should_reveal_code": controls.should_reveal_code,
        "success_streak": controls.success_streak,
        "failure_streak": controls.failure_streak,
        "pedagogy_mode": controls.pedagogy_mode,
        "transfer_scene_count": controls.transfer_scene_count,
        "time_budget": controls.time_budget,
        "project_complexity": controls.project_complexity,
        "task_urgency": controls.task_urgency,
    }


def streak_adapts_without_inventing_live_objects(
    *,
    failure_streak: int = 0,
    success_streak: int = 0,
    live_plan: bool = False,
    live_task: bool = False,
    live_card: bool = False,
) -> bool:
    """Consecutive fail/success adapts hints and pace only when no live object exists.

    Failure without a live plan/task stays hints/review. Success without a live
    card stays a harder question or transfer prompt. Neither mints a plan, card,
    or task that is not already live.
    """

    if int(failure_streak or 0) >= 2 and not live_plan and not live_task:
        return True
    if int(success_streak or 0) >= 2 and not live_card:
        return True
    return False
