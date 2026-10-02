"""Restore only the latest material batch owned by the visible plan."""
from __future__ import annotations

from collections.abc import Iterable

from ..core.models import LearningPlan, StageMaterialItem, TeachingKnowledgeAsset


def stage_material_payload(asset: TeachingKnowledgeAsset) -> StageMaterialItem:
    return StageMaterialItem(
        id=asset.id, plan_stage_id=asset.plan_stage_id, kind=asset.kind,
        title=asset.title, summary=asset.summary,
        content=asset.concept_card or asset.example or asset.exercise_seed or asset.summary,
        focus_area=asset.focus_area, created_at=asset.created_at or "",
        generation_source="template" if "stage-material-fallback" in asset.tags else "model",
    )


def stage_material_state(
    plan: LearningPlan | None, assets: Iterable[TeachingKnowledgeAsset],
) -> dict[str, list[StageMaterialItem]]:
    if plan is None:
        return {}
    owner = f"plan:{plan.id or plan.plan_id}"
    stages = {stage.id for stage in plan.stages}
    owned = [asset for asset in assets if owner in asset.tags
             and "stage-material" in asset.tags and asset.plan_stage_id in stages]
    batches: dict[str, str] = {}
    for asset in owned:
        batch = next((tag for tag in asset.tags if tag.startswith("stage-batch:")), "")
        batches[asset.plan_stage_id] = max(batches.get(asset.plan_stage_id, ""), batch)
    result: dict[str, list[StageMaterialItem]] = {}
    for asset in owned:
        batch = next((tag for tag in asset.tags if tag.startswith("stage-batch:")), "")
        if batch == batches[asset.plan_stage_id]:
            result.setdefault(asset.plan_stage_id, []).append(stage_material_payload(asset))
    order = {kind: index for index, kind in enumerate(
        ("study_guide", "cheat_sheet", "exercise_set", "code_examples"))}
    for items in result.values():
        items.sort(key=lambda item: order.get(item.kind, len(order)))
    return result
