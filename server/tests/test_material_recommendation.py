from __future__ import annotations

from datetime import datetime, timezone

from app.core.models import TrainingCardCandidateSnapshot
from app.pedagogy.material_recommendation import (
    apply_material_recommendation_to_search_results,
    resolve_material_routing,
    teaching_asset_scope_bias,
)
from app.resources.search import SearchResult
from app.training.card_router import CardRouterService


def _card(**overrides: object) -> TrainingCardCandidateSnapshot:
    defaults: dict[str, object] = {
        "card_id": "card-1",
        "card_type": "practice",
        "title": "Test card",
        "focus_area": "testing",
        "target_skill": "unit tests",
        "difficulty": "medium",
        "problem_statement": "Write a unit test.",
        "deliverable": "A passing test file.",
        "validation_method": "pytest runs green.",
        "expected_answer": "N/A",
        "hint_ladder": ["Start with assert"],
        "created_from": "conversation",
        "status": "candidate",
        "project_id": "proj-1",
    }
    defaults.update(overrides)
    return TrainingCardCandidateSnapshot(**defaults)


def _learner(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "weaknesses": [],
        "recent_errors": [],
        "difficulty_preference": "medium",
        "needs_rescue": False,
        "active_blockers": [],
        "material_recommendation": "current",
        "transfer_scene_count": 1,
        "transfer_state": "awaiting_second_scene",
    }
    state.update(overrides)
    return state


def _plan() -> dict[str, object]:
    return {
        "active_stage_id": "stage-1",
        "active_stage_skills": ["unit tests"],
        "active_project_id": "proj-1",
    }


def _hit(*, resource_id: str, title: str, project_scope: str, rank_score: float) -> SearchResult:
    return SearchResult(
        resource_id=resource_id,
        path=f"/{resource_id}.md",
        title=title,
        snippet=title,
        source=title,
        source_type="file",
        summary=title,
        trust_score=0.8,
        trust_state="trusted",
        freshness="fresh",
        file_type="md",
        project_scope=project_scope,
        kind="notes",
        index_state="indexed",
        citation_id=f"citation:{resource_id}",
        can_inject_training_card=True,
        updated_at=datetime.now(timezone.utc),
        rank_score=rank_score,
        rank_reasons=["title match"],
    )


def test_transfer_without_second_scene_fail_closes_to_current() -> None:
    routing = resolve_material_routing(
        "transfer",
        transfer_scene_count=1,
        transfer_state="awaiting_second_scene",
    )
    assert routing.requested == "transfer"
    assert routing.recommendation == "current"
    assert routing.allow_transfer_materials is False
    assert routing.prefer_current_project is True
    assert routing.orientation_key == "transfer_blocked"


def test_transfer_allowed_only_with_second_scene() -> None:
    routing = resolve_material_routing(
        "transfer",
        transfer_scene_count=2,
        transfer_state="transferable",
    )
    assert routing.recommendation == "transfer"
    assert routing.allow_transfer_materials is True
    assert routing.orientation_key == "transfer"


def test_router_prefers_simpler_recovery_after_failure_streak() -> None:
    svc = CardRouterService()
    recovery = _card(
        card_id="card-easy-recovery",
        title="Recover config branch",
        difficulty="easy",
        created_from="practice_feedback",
        project_id="proj-1",
    )
    stretch = _card(
        card_id="card-hard-transfer",
        title="Transfer protocol design",
        difficulty="hard",
        created_from="resource",
        project_id="proj-2",
        knowledge_type="engineering_concept",
        focus_area="protocols",
    )
    result = svc.select_active_card(
        candidates=[stretch, recovery],
        learner_state=_learner(
            material_recommendation="simpler",
            difficulty_preference="easy",
            needs_rescue=True,
        ),
        plan_state=_plan(),
    )
    assert result.selected_card_id == "card-easy-recovery"
    assert "recovery" in result.why_this_card.lower() or "easier" in result.why_this_card.lower()
    assert "Stay with this project's sources" in result.next_after_completion or "simpler" in result.next_after_completion.lower() or "recovery" in result.next_after_completion.lower()


def test_router_keeps_current_scene_after_one_success() -> None:
    svc = CardRouterService()
    current = _card(card_id="card-current", title="Current scene slice", project_id="proj-1")
    other = _card(
        card_id="card-other",
        title="Other scene transfer",
        project_id="proj-2",
        created_from="resource",
        knowledge_type="principle",
    )
    result = svc.select_active_card(
        candidates=[other, current],
        learner_state=_learner(material_recommendation="current", transfer_scene_count=1),
        plan_state=_plan(),
    )
    assert result.selected_card_id == "card-current"
    assert "current" in result.why_this_card.lower() or "project" in result.why_this_card.lower()


def test_router_blocks_transfer_materials_without_second_scene() -> None:
    svc = CardRouterService()
    current = _card(card_id="card-current", title="Local slice", project_id="proj-1")
    transfer = _card(
        card_id="card-transfer",
        title="Global mastery notes",
        project_id="proj-2",
        created_from="resource",
        knowledge_type="engineering_concept",
    )
    result = svc.select_active_card(
        candidates=[transfer, current],
        learner_state=_learner(
            material_recommendation="transfer",
            transfer_scene_count=1,
            transfer_state="awaiting_second_scene",
        ),
        plan_state=_plan(),
    )
    assert result.selected_card_id == "card-current"
    assert "second" in result.why_this_card.lower() or "closed" in result.why_this_card.lower()


def test_router_allows_transfer_materials_with_evidenced_second_scene() -> None:
    svc = CardRouterService()
    current = _card(card_id="card-current", title="Local slice", project_id="proj-1")
    transfer = _card(
        card_id="card-transfer",
        title="Second-scene protocol",
        project_id="proj-2",
        created_from="resource",
        knowledge_type="engineering_concept",
    )
    result = svc.select_active_card(
        candidates=[current, transfer],
        learner_state=_learner(
            material_recommendation="transfer",
            transfer_scene_count=2,
            transfer_state="transferable",
        ),
        plan_state=_plan(),
    )
    assert result.selected_card_id == "card-transfer"
    assert "second" in result.why_this_card.lower() or "transfer" in result.why_this_card.lower()


def test_search_ranking_respects_material_recommendation() -> None:
    def pair() -> tuple[SearchResult, SearchResult]:
        return (
            _hit(resource_id="res-current", title="Current notes", project_scope="proj-1", rank_score=0.40),
            _hit(resource_id="res-other", title="Other scene notes", project_scope="proj-2", rank_score=0.90),
        )

    current, other = pair()
    simpler = apply_material_recommendation_to_search_results(
        [other, current],
        resolve_material_routing("simpler", transfer_scene_count=1),
        current_workspace_id="proj-1",
    )
    assert simpler[0].resource_id == "res-current"
    assert any("recovery" in reason or "current scene" in reason for reason in simpler[0].rank_reasons)
    assert any("transfer blocked" in reason for reason in simpler[1].rank_reasons)

    current, other = pair()
    blocked = apply_material_recommendation_to_search_results(
        [other, current],
        resolve_material_routing("transfer", transfer_scene_count=1, transfer_state="awaiting_second_scene"),
        current_workspace_id="proj-1",
    )
    assert blocked[0].resource_id == "res-current"
    assert any("transfer blocked" in reason for reason in blocked[1].rank_reasons)

    current, other = pair()
    allowed = apply_material_recommendation_to_search_results(
        [current, other],
        resolve_material_routing("transfer", transfer_scene_count=2, transfer_state="transferable"),
        current_workspace_id="proj-1",
    )
    assert allowed[0].resource_id == "res-other"
    assert any("evidenced transfer" in reason for reason in allowed[0].rank_reasons)


def test_teaching_assets_do_not_promote_general_without_second_scene() -> None:
    blocked = resolve_material_routing("transfer", transfer_scene_count=1)
    assert teaching_asset_scope_bias("general", "__global__", "proj-1", blocked) < 0
    assert teaching_asset_scope_bias("project", "proj-1", "proj-1", blocked) > 0
    allowed = resolve_material_routing("transfer", transfer_scene_count=2, transfer_state="transferable")
    assert teaching_asset_scope_bias("general", "__global__", "proj-1", allowed) > 0
