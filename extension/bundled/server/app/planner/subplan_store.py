"""Shared in-memory SubPlan store.

Module-level dict so both routers.py and PlannerService can access
the same sub-plan storage without circular imports or duplication.
"""

from __future__ import annotations

from ..core.models import SubPlan

_subplan_store: dict[str, list[SubPlan]] = {}


def get_store() -> dict[str, list[SubPlan]]:
    return _subplan_store


def list_subplans(plan_id: str) -> list[SubPlan]:
    return [item.model_copy(deep=True) for item in _subplan_store.get(plan_id, [])]


def get_subplan(plan_id: str, subplan_id: str) -> SubPlan | None:
    for item in _subplan_store.get(plan_id, []):
        if item.id == subplan_id:
            return item.model_copy(deep=True)
    return None


def upsert_subplan(plan_id: str, subplan: SubPlan) -> SubPlan:
    entries = _subplan_store.setdefault(plan_id, [])
    updated = subplan.model_copy(deep=True)
    if not updated.id:
        updated.id = f"subplan-{len(entries) + 1}"
    updated.parent_plan_id = updated.parent_plan_id or plan_id
    updated.updated_at = updated.updated_at or updated.created_at
    for index, existing in enumerate(entries):
        if existing.id == updated.id:
            entries[index] = updated
            return updated.model_copy(deep=True)
    entries.append(updated)
    return updated.model_copy(deep=True)


def delete_subplan(plan_id: str, subplan_id: str) -> bool:
    entries = _subplan_store.get(plan_id)
    if not entries:
        return False
    for index, existing in enumerate(entries):
        if existing.id == subplan_id:
            del entries[index]
            if not entries:
                _subplan_store.pop(plan_id, None)
            return True
    return False


def clear_subplans(plan_id: str) -> None:
    _subplan_store.pop(plan_id, None)
