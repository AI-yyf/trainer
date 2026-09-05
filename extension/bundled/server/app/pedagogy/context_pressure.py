"""Derive time budget, project complexity, and urgency from existing fields.

Signals come from profile, workspace, plan, task, affect, and first-look
classification that already exist on the snapshot. Empty fields stay
neutral. Nothing here invents telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


def _text(value: Any) -> str:
    return str(value or "").strip()


def _casefold(value: Any) -> str:
    return _text(value).casefold()

TimeBudget = Literal["tight", "normal", "ample"]
ProjectComplexity = Literal["simple", "moderate", "complex"]
TaskUrgency = Literal["low", "medium", "high"]

TIGHT_BUDGET_MARKERS = frozenset(
    {"tight", "short", "small-step", "small_step", "limited", "scarce", "light"}
)
AMPLE_BUDGET_MARKERS = frozenset({"ample", "generous", "plenty", "open"})
HIGH_URGENCY_MARKERS = frozenset({"high", "urgent", "blocked", "due"})
LOW_URGENCY_MARKERS = frozenset({"low", "calm", "later"})
COMPLEX_ROLES = frozenset({"existing_engineering", "algorithm_model"})
SIMPLE_ROLES = frozenset({"empty_new_project", "idea_scratchpad", "learning_materials"})
COMPLEX_PROJECT_TYPES = frozenset(
    {"monorepo", "data_pipeline", "ml_model", "embedded_iot", "mobile_app"}
)
SIMPLE_PROJECT_TYPES = frozenset({"documentation", "config_dotfiles", "cli_tool"})


@dataclass(frozen=True, slots=True)
class ContextPressure:
    time_budget: TimeBudget = "normal"
    project_complexity: ProjectComplexity = "moderate"
    task_urgency: TaskUrgency = "medium"
    evidence: tuple[str, ...] = ()


def _get(source: Any, *names: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        for name in names:
            if name in source and source[name] not in (None, ""):
                return source[name]
        return default
    for name in names:
        value = getattr(source, name, None)
        if value not in (None, ""):
            return value
    return default


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return 0


def normalize_time_budget(value: Any) -> TimeBudget:
    token = _casefold(value).replace(" ", "-")
    if token in TIGHT_BUDGET_MARKERS:
        return "tight"
    if token in AMPLE_BUDGET_MARKERS:
        return "ample"
    return "normal"


def normalize_task_urgency(value: Any) -> TaskUrgency:
    token = _casefold(value)
    if token in HIGH_URGENCY_MARKERS:
        return "high"
    if token in LOW_URGENCY_MARKERS:
        return "low"
    return "medium"


def normalize_project_complexity(value: Any) -> ProjectComplexity:
    token = _casefold(value)
    if token in {"complex", "high"} or token in COMPLEX_ROLES or token in COMPLEX_PROJECT_TYPES:
        return "complex"
    if token in {"simple", "low"} or token in SIMPLE_ROLES or token in SIMPLE_PROJECT_TYPES:
        return "simple"
    return "moderate"


def _weekly_hours(
    profile: Any,
    workspace: dict[str, Any] | None,
    preferences: list[Any] | None,
) -> int | None:
    for source in (profile, workspace):
        hours = _as_int(_get(source, "weekly_hours", "weeklyHours"))
        if hours is not None and hours > 0:
            return hours
    for item in preferences or []:
        if _casefold(_get(item, "key")) == "weekly_hours":
            hours = _as_int(_get(item, "value"))
            if hours is not None and hours > 0:
                return hours
    return None


def _pressure_plan_runtime(
    *,
    plan: Any,
    plan_runtime: Any,
    workspace: dict[str, Any],
    workspace_id: str = "",
) -> dict[str, Any] | None:
    """Use scoped latest_plan_runtime only when the live repo plan is missing."""

    if plan is not None:
        return None
    from ..memory.workspace_recovery import PLAN_RUNTIME_KEY, select_plan_runtime_for_pressure

    scope_id = _text(workspace_id) or _text(workspace.get("workspace_id") or workspace.get("workspaceId"))
    raw = plan_runtime if plan_runtime is not None else workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime")
    return select_plan_runtime_for_pressure(raw, scope_id)


def derive_context_pressure(
    *,
    profile: Any = None,
    workspace: dict[str, Any] | None = None,
    plan: Any = None,
    plan_runtime: Any = None,
    current_task: Any = None,
    affect_state: Any = None,
    due_reviews: list[Any] | None = None,
    workspace_understanding: Any = None,
    session: Any = None,
    preferences: list[Any] | None = None,
    workspace_id: str = "",
) -> ContextPressure:
    """Map already-persisted snapshot fields into pedagogy pressure."""

    workspace = workspace if isinstance(workspace, dict) else {}
    evidence: list[str] = []
    coach_defaults = workspace.get("coach_defaults")
    if not isinstance(coach_defaults, dict):
        coach_defaults = {}
    runtime = _pressure_plan_runtime(
        plan=plan,
        plan_runtime=plan_runtime,
        workspace=workspace,
        workspace_id=workspace_id,
    )

    explicit_budget = normalize_time_budget(workspace.get("time_budget"))
    hours = _weekly_hours(profile, workspace, preferences)
    rhythm = _casefold(workspace.get("preferred_rhythm") or "")
    review_cadence = _casefold(coach_defaults.get("review_cadence") or "")
    working_set = _casefold(coach_defaults.get("working_set_mode") or "")

    if _text(workspace.get("time_budget")) and _casefold(workspace.get("time_budget")) in TIGHT_BUDGET_MARKERS | AMPLE_BUDGET_MARKERS | {"normal"}:
        time_budget = explicit_budget
        evidence.append(f"time_budget:{time_budget}")
    elif hours is not None and hours <= 3:
        time_budget = "tight"
        evidence.append(f"weekly_hours:{hours}")
    elif hours is not None and hours >= 8:
        time_budget = "ample"
        evidence.append(f"weekly_hours:{hours}")
    elif rhythm in TIGHT_BUDGET_MARKERS:
        time_budget = "tight"
        evidence.append(f"rhythm:{rhythm}")
    elif review_cadence == "light" and (hours is not None and hours <= 3):
        time_budget = "tight"
        evidence.append("review_cadence:light")
    elif review_cadence == "active" and (hours or 4) >= 6:
        time_budget = "ample"
        evidence.append("review_cadence:active")
    elif working_set == "focused" and hours is not None and hours <= 3:
        time_budget = "tight"
        evidence.append("working_set:focused")
    else:
        time_budget = "normal"

    explicit_urgency = _text(workspace.get("task_urgency"))
    affect_urgency = _get(affect_state, "urgency_level", "urgencyLevel")
    recovered_step = _text(_get(runtime, "current_step", "currentStep"))
    blocked = _text(
        _get(plan, "blocked_reason", "blockedReason")
        or _get(runtime, "blocked_reason", "blockedReason")
        or _get(session, "blocker")
        or workspace.get("latest_learning_blocker")
    )
    due = list(due_reviews or [])
    high_weakness_due = any(
        _casefold(_get(item, "source")) == "weakness" and _casefold(_get(item, "severity")) == "high"
        for item in due
    )
    if explicit_urgency:
        task_urgency = normalize_task_urgency(explicit_urgency)
        evidence.append(f"task_urgency:{task_urgency}")
    elif blocked:
        task_urgency = "high"
        evidence.append("blocker")
        if recovered_step:
            evidence.append("plan_runtime:current_step")
    elif recovered_step:
        task_urgency = "medium"
        evidence.append("plan_runtime:current_step")
    elif affect_urgency:
        task_urgency = normalize_task_urgency(affect_urgency)
        evidence.append(f"affect_urgency:{task_urgency}")
    elif high_weakness_due:
        task_urgency = "high"
        evidence.append("due_reviews")
    else:
        task_urgency = "medium"

    explicit_complexity = _text(workspace.get("project_complexity"))
    first_look = _get(workspace_understanding, "first_look_summary", "firstLookSummary")
    folder_role = _casefold(_get(first_look, "folder_role", "folderRole") or workspace.get("folder_role"))
    project_type = _casefold(
        _get(first_look, "project_type_guess", "projectTypeGuess") or workspace.get("project_type_guess")
    )
    stages = _get(plan, "stages") or []
    current_stage = None
    current_stage_id = _text(_get(plan, "current_stage_id", "currentStageId"))
    for stage in stages if isinstance(stages, list) else []:
        if _text(_get(stage, "id")) == current_stage_id or _casefold(_get(stage, "status")) == "active":
            current_stage = stage
            break
    if current_stage is None and isinstance(stages, list) and stages:
        current_stage = stages[0]
    outcome_count = _count(_get(current_stage, "outcomes"))
    constraint_count = (
        _count(_get(current_task, "constraints"))
        + _count(_get(current_task, "edge_cases", "edgeCases"))
        + _count(_get(current_task, "failure_conditions", "failureConditions"))
    )
    feature_lanes = _count(_get(workspace_understanding, "feature_lanes", "featureLanes"))
    risk_zones = _count(_get(workspace_understanding, "risk_zones", "riskZones")) or _count(
        _get(first_look, "risk_zones", "riskZones")
    )
    stage_count = _count(stages)

    if explicit_complexity:
        project_complexity = normalize_project_complexity(explicit_complexity)
        evidence.append(f"project_complexity:{project_complexity}")
    elif (
        folder_role in COMPLEX_ROLES
        or project_type in COMPLEX_PROJECT_TYPES
        or stage_count >= 5
        or outcome_count >= 4
        or constraint_count >= 4
        or feature_lanes >= 4
        or risk_zones >= 3
    ):
        project_complexity = "complex"
        evidence.append("complexity:complex")
    elif folder_role in SIMPLE_ROLES or project_type in SIMPLE_PROJECT_TYPES:
        project_complexity = "simple"
        evidence.append("complexity:simple")
    else:
        project_complexity = "moderate"

    return ContextPressure(
        time_budget=time_budget,
        project_complexity=project_complexity,
        task_urgency=task_urgency,
        evidence=tuple(evidence[:4]),
    )


# Preference kinds that adapt pedagogy (hints/pace/raise). Keep in sync with
# evidence_controls.DEGRADE_PREFERENCES / RAISE_PREFERENCES — no circular import.
PREFERENCE_HINT_KINDS = frozenset(
    {"too_hard", "misunderstood", "card_unrealistic", "resource_incorrect"}
)
PREFERENCE_RAISE_KINDS = frozenset({"too_simple"})
LOW_EVIDENCE_TRUST = 0.4


def preference_equivalent_from_strategy_bias(
    *,
    challenge_level: str = "",
    hint_depth: str = "",
    next_step_bias: str = "",
    feedback_next_step_bias: str = "",
) -> str:
    """Map strategy-bias / workspace next-step bias to preference kinds.

    Pedagogy can prefer hints via ``_apply_preferred_strategy_bias`` without
    ``latest_user_feedback_kind``. Mint gates must still see that as preference.
    """

    challenge = _casefold(challenge_level)
    hint = _casefold(hint_depth)
    next_bias = _casefold(next_step_bias)
    feedback_bias = _casefold(feedback_next_step_bias)
    if (
        challenge == "lower"
        or (hint == "direct" and next_bias == "shrink")
        or feedback_bias == "shrink"
    ):
        return "too_hard"
    if (
        challenge == "raise"
        or (hint == "lighter" and next_bias == "widen")
        or feedback_bias == "widen"
    ):
        return "too_simple"
    return ""


def pressure_adapts_without_inventing_live_objects(
    *,
    time_budget: str = "normal",
    task_urgency: str = "medium",
    project_complexity: str = "moderate",
    current_ability: str = "",
    user_preference: str = "",
    evidence_confidence: float | None = None,
    live_plan: bool = False,
    live_task: bool = False,
    live_card: bool = False,
) -> bool:
    """Tight budget / high urgency / complex / lower ability / preference / low trust: hints-pace only.

    Compressed, ability-mismatched, preference-driven, or low-trust sessions adapt
    to smaller hints and a shorter next slice. They must not mint a plan, task, or
    card that is not already live (selected_card_id / selectedCardId). Preference
    and unverified evidence never unlock mastery theater or invent live objects.
    """

    preference = _casefold(user_preference)
    preference_adapts = preference in PREFERENCE_HINT_KINDS or preference in PREFERENCE_RAISE_KINDS
    low_trust = (
        evidence_confidence is not None and float(evidence_confidence) < LOW_EVIDENCE_TRUST
    )
    gated = (
        normalize_time_budget(time_budget) == "tight"
        or normalize_task_urgency(task_urgency) == "high"
        or normalize_project_complexity(project_complexity) == "complex"
        or _casefold(current_ability) == "struggling"
        or preference_adapts
        or low_trust
    )
    if not gated:
        return False
    return not live_plan and not live_task and not live_card
