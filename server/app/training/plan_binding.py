"""Validate a practice's formal plan identity before minting or returning evidence."""

from typing import Any

from ..core.models import LearningPlan, TrainingPlanBinding
from ..memory.workspace_recovery import formal_plan_is_live_runtime_identity


def binding_matches_plan(
    binding: TrainingPlanBinding,
    plan: LearningPlan | None,
    runtime: dict[str, Any],
) -> bool:
    if plan is None or binding.plan_id != plan.id:
        return False
    if not formal_plan_is_live_runtime_identity(plan=plan, runtime=runtime, existing=runtime):
        return False
    step = str(runtime.get("current_step") or runtime.get("currentStep") or "").strip()
    stage = next((stage for stage in plan.stages if stage.id == plan.current_stage_id), None)
    return bool(
        stage is not None
        and stage.status == "active"
        and binding.stage_id == stage.id
        and binding.step.strip() == step
    )


def validated_mint_binding(
    binding: TrainingPlanBinding | None,
    *,
    source: str,
    plan: LearningPlan | None,
    runtime: dict[str, Any],
    revision: int,
) -> TrainingPlanBinding | None:
    if binding is None:
        if source == "formal_plan_step":
            raise ValueError("The current plan step is required. Refresh the plan before practicing.")
        return None
    if (
        not binding_matches_plan(binding, plan, runtime)
        or plan is None
        or plan.frozen
        or (binding.revision is not None and binding.revision != revision)
    ):
        raise ValueError("The plan changed or is frozen. Refresh the current step before practicing.")
    return binding.model_copy(update={"step": binding.step.strip(), "revision": revision})
