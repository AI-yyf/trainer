"""Rank and select the next resource or card source from material_recommendation.

Fail-closed: ``transfer`` only applies when a second evidenced scene exists.
One project success stays on current-scene sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .context_pressure import (
    normalize_project_complexity,
    normalize_task_urgency,
    normalize_time_budget,
)
from .evidence_controls import _can_recommend_transfer, _casefold, _text

MaterialLane = Literal["simpler", "current", "transfer"]
OrientationKey = Literal["simpler", "current", "transfer", "transfer_blocked"]

SIMPLER_SOURCES = ("practice_feedback", "review_due", "dependency_mastery", "recovery", "conversation")
CURRENT_SOURCES = ("conversation", "plan", "resource", "conversation_gap", "plan_requirement")
TRANSFER_SOURCES = ("resource", "resource_knowledge", "conversation")


@dataclass(frozen=True, slots=True)
class MaterialRoutingDecision:
    requested: MaterialLane
    recommendation: MaterialLane
    allow_transfer_materials: bool
    prefer_recovery: bool
    prefer_current_project: bool
    preferred_card_sources: tuple[str, ...]
    preferred_difficulties: tuple[str, ...]
    preferred_asset_scopes: tuple[str, ...]
    rank_reason: str
    next_step: str
    orientation_key: OrientationKey
    transfer_scene_count: int = 0


def normalize_material_recommendation(value: Any) -> MaterialLane:
    normalized = _casefold(value)
    if normalized == "simpler":
        return "simpler"
    if normalized == "transfer":
        return "transfer"
    return "current"


def resolve_material_routing(
    recommendation: Any = None,
    *,
    transfer_scene_count: int = 0,
    transfer_state: str = "",
    time_budget: str = "",
    task_urgency: str = "",
    project_complexity: str = "",
) -> MaterialRoutingDecision:
    requested = normalize_material_recommendation(recommendation)
    allow_transfer = _can_recommend_transfer(
        transfer_scene_count=transfer_scene_count,
        transfer_state=transfer_state,
    )
    budget = normalize_time_budget(time_budget)
    urgency = normalize_task_urgency(task_urgency)
    complexity = normalize_project_complexity(project_complexity)
    compressed = budget == "tight" or urgency == "high"
    # Tight budget / high urgency never open transfer, even with a second scene.
    if requested == "transfer" and (not allow_transfer or compressed):
        blocked = not allow_transfer
        return MaterialRoutingDecision(
            requested="transfer",
            recommendation="current",
            allow_transfer_materials=False,
            prefer_recovery=False,
            prefer_current_project=True,
            preferred_card_sources=CURRENT_SOURCES,
            preferred_difficulties=("easy", "medium") if compressed else ("medium",),
            preferred_asset_scopes=("project", "personal"),
            rank_reason=(
                "Transfer sources stay closed until a second evidenced scene exists."
                if blocked
                else "A tight budget or high urgency stays on current-project sources."
            ),
            next_step=(
                "Stay with this project's sources. One scene is not transferable mastery."
                if blocked
                else "Keep the next slice short. Stay with this project's sources."
            ),
            orientation_key="transfer_blocked" if blocked else "current",
            transfer_scene_count=transfer_scene_count,
        )
    if requested == "simpler" or (compressed and requested != "transfer"):
        return MaterialRoutingDecision(
            requested=requested,
            recommendation="simpler" if requested == "simpler" else "current",
            allow_transfer_materials=False,
            prefer_recovery=requested == "simpler",
            prefer_current_project=True,
            preferred_card_sources=SIMPLER_SOURCES if requested == "simpler" else CURRENT_SOURCES,
            preferred_difficulties=("easy",) if requested == "simpler" else ("easy", "medium"),
            preferred_asset_scopes=("project",) if requested == "simpler" else ("project", "personal"),
            rank_reason=(
                "Recent misses prefer easier recovery sources in the current project."
                if requested == "simpler"
                else "A tight budget or high urgency prefers a shorter current-project card."
            ),
            next_step=(
                "Use a simpler recovery source in this project, not a transfer set."
                if requested == "simpler"
                else "Keep the next slice short. Stay with this project's sources."
            ),
            orientation_key="simpler" if requested == "simpler" else "current",
            transfer_scene_count=transfer_scene_count,
        )
    if requested == "transfer" and allow_transfer:
        return MaterialRoutingDecision(
            requested="transfer",
            recommendation="transfer",
            allow_transfer_materials=True,
            prefer_recovery=False,
            prefer_current_project=False,
            preferred_card_sources=TRANSFER_SOURCES,
            preferred_difficulties=("medium", "hard"),
            preferred_asset_scopes=("general", "personal", "project"),
            rank_reason="A second evidenced scene allows transfer sources.",
            next_step="A second scene is evidenced, so transfer sources are eligible.",
            orientation_key="transfer",
            transfer_scene_count=transfer_scene_count,
        )
    complex_project = complexity == "complex"
    return MaterialRoutingDecision(
        requested=requested,
        recommendation="current",
        allow_transfer_materials=False,
        prefer_recovery=False,
        prefer_current_project=True,
        preferred_card_sources=CURRENT_SOURCES,
        preferred_difficulties=("easy", "medium") if complex_project else ("medium",),
        preferred_asset_scopes=("project", "personal"),
        rank_reason=(
            "High project complexity stays on a smaller current-project slice."
            if complex_project
            else "Stay with current project and scene sources."
        ),
        next_step=(
            "Keep the next slice small. One scene is not transferable mastery."
            if complex_project
            else "Stay with this project's sources."
        ),
        orientation_key="current",
        transfer_scene_count=transfer_scene_count,
    )


def routing_from_learner_state(learner_state: dict[str, Any] | None) -> MaterialRoutingDecision:
    state = learner_state or {}
    scene_raw = state.get("transfer_scene_count", state.get("transferSceneCount", 0))
    try:
        scene_count = int(scene_raw or 0)
    except (TypeError, ValueError):
        scene_count = 0
    return resolve_material_routing(
        state.get("material_recommendation") or state.get("materialRecommendation"),
        transfer_scene_count=scene_count,
        transfer_state=str(state.get("transfer_state") or state.get("transferState") or ""),
        time_budget=str(state.get("time_budget") or state.get("timeBudget") or ""),
        task_urgency=str(state.get("task_urgency") or state.get("taskUrgency") or ""),
        project_complexity=str(state.get("project_complexity") or state.get("projectComplexity") or ""),
    )


def preferred_generation_source(current_source: str, routing: MaterialRoutingDecision) -> str:
    source = _text(current_source) or "conversation_gap"
    if source not in {"", "conversation_gap", "conversation"}:
        return source
    if routing.prefer_recovery:
        return "practice_feedback"
    if routing.allow_transfer_materials:
        return "resource_knowledge"
    return "conversation_gap"


def source_matches_routing(created_from: str, routing: MaterialRoutingDecision) -> bool:
    created = _casefold(created_from)
    return created in {_casefold(item) for item in routing.preferred_card_sources}


def apply_material_bias_to_factors(
    *,
    created_from: str,
    difficulty: str,
    project_id: str,
    active_project_id: str,
    knowledge_type: str,
    routing: MaterialRoutingDecision,
    difficulty_fit: float,
    project_fit: float,
    transfer_value: float,
    recovery_priority: float,
) -> tuple[float, float, float, float]:
    created = _casefold(created_from)
    card_difficulty = _casefold(difficulty)
    same_project = bool(project_id and active_project_id and project_id == active_project_id)
    other_project = bool(project_id and active_project_id and project_id != active_project_id)
    recovery_source = created in {"practice_feedback", "review_due", "dependency_mastery", "recovery"}
    transferish = created in {"resource", "resource_knowledge"} or _casefold(knowledge_type) in {
        "engineering_concept",
        "principle",
    }

    if routing.prefer_recovery:
        if card_difficulty == "easy" or recovery_source:
            recovery_priority = max(recovery_priority, 0.95)
            difficulty_fit = max(difficulty_fit, 0.95)
        if card_difficulty == "hard":
            difficulty_fit = min(difficulty_fit, 0.15)
        transfer_value = min(transfer_value, 0.2)
    if routing.prefer_current_project:
        if same_project:
            project_fit = max(project_fit, 0.95)
        elif other_project:
            project_fit = min(project_fit, 0.15)
            transfer_value = min(transfer_value, 0.1)
        elif not project_id:
            project_fit = max(project_fit, 0.55)
    if routing.allow_transfer_materials:
        if transferish or other_project:
            transfer_value = 1.0
            project_fit = max(project_fit, 0.9)
        elif same_project:
            project_fit = min(project_fit, 0.45)
    else:
        if other_project or (transferish and not same_project and project_id):
            transfer_value = min(transfer_value, 0.12)
            project_fit = min(project_fit, 0.2)
    if source_matches_routing(created, routing):
        recovery_priority = max(recovery_priority, 0.55 if not routing.prefer_recovery else recovery_priority)
        project_fit = max(project_fit, 0.7)
    preferred = {_casefold(item) for item in routing.preferred_difficulties}
    if card_difficulty in preferred:
        difficulty_fit = max(difficulty_fit, 0.9)
    elif preferred and card_difficulty == "hard" and "hard" not in preferred:
        difficulty_fit = min(difficulty_fit, 0.2)
    return difficulty_fit, project_fit, transfer_value, recovery_priority


def apply_material_recommendation_to_search_results(
    results: list[Any],
    routing: MaterialRoutingDecision,
    *,
    current_workspace_id: str,
) -> list[Any]:
    workspace = _casefold(current_workspace_id)
    scored: list[Any] = []
    for item in results:
        score = float(getattr(item, "rank_score", 0.0) or 0.0)
        reasons = list(getattr(item, "rank_reasons", []) or [])
        scope = _casefold(getattr(item, "project_scope", "") or "")
        same_scene = bool(workspace and scope and (scope == workspace or workspace in scope))
        other_scene = bool(scope and workspace and not same_scene)
        if routing.prefer_recovery or routing.prefer_current_project:
            if same_scene:
                score += 0.55 if routing.prefer_recovery else 0.4
                reasons.append("current scene source")
            if routing.prefer_recovery and same_scene:
                reasons.append("recovery source")
            if other_scene and not routing.allow_transfer_materials:
                score -= 0.6
                reasons.append("transfer blocked")
        if routing.allow_transfer_materials and other_scene:
            score += 0.55
            reasons.append("evidenced transfer source")
        elif routing.orientation_key == "transfer_blocked" and other_scene:
            score -= 0.6
            if "transfer blocked" not in reasons:
                reasons.append("transfer blocked")
        if hasattr(item, "rank_score"):
            item.rank_score = round(score, 3)
        if hasattr(item, "rank_reasons"):
            item.rank_reasons = reasons
        scored.append(item)
    scored.sort(
        key=lambda row: (
            float(getattr(row, "rank_score", 0.0) or 0.0),
            str(getattr(row, "title", "") or "").lower(),
        ),
        reverse=True,
    )
    return scored


def teaching_asset_scope_bias(asset_scope: str, asset_workspace_id: str, workspace_id: str, routing: MaterialRoutingDecision) -> float:
    scope = _casefold(asset_scope)
    same_workspace = _casefold(asset_workspace_id) in {_casefold(workspace_id), ""}
    if routing.prefer_recovery or routing.prefer_current_project:
        if scope == "project" and same_workspace:
            return 4.0
        if scope == "general" and not routing.allow_transfer_materials:
            return -3.0
        if scope == "personal" and same_workspace:
            return 1.5
    if routing.allow_transfer_materials and scope == "general":
        return 4.0
    if not routing.allow_transfer_materials and scope == "general":
        return -3.0
    return 0.0
