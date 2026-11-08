"""Pure evidence-queue projection (§十一 Memory split).

MemoryService owns persistence and plan-runtime recovery; this module owns the
single read classification used by `/evidence/queue` and snapshots:
pending / deferred / adopted / rejected / scoped history.
"""

from __future__ import annotations

from typing import Any

from ..core.models import EvidenceItem, EvidenceQueueSnapshot
from .workspace_recovery import (
    scope_evidence_items_to_workspace,
    scope_evidence_queue_to_runtime_step,
)


def build_evidence_queue_snapshot(
    *,
    items: list[EvidenceItem],
    workspace_id: str,
    recovered: dict[str, Any] | None,
    recovered_runtime: bool,
    current_plan_id: str = "",
    current_stage_id: str = "",
    current_step: str = "",
) -> EvidenceQueueSnapshot:
    pending = [
        item
        for item in items
        if not item.adopted and not item.rejected_at and not item.deferred_at
    ]
    deferred = [
        item
        for item in items
        if not item.adopted and not item.rejected_at and bool(item.deferred_at)
    ]
    adopted = [item for item in items if item.adopted]
    rejected = [item for item in items if item.rejected_at]
    scoped = scope_evidence_queue_to_runtime_step(
        pending=scope_evidence_items_to_workspace(pending, workspace_id),
        deferred=scope_evidence_items_to_workspace(deferred, workspace_id),
        adopted=scope_evidence_items_to_workspace(adopted, workspace_id),
        rejected=scope_evidence_items_to_workspace(rejected, workspace_id),
        current_step=current_step,
        recovered=recovered_runtime,
        current_plan_id=current_plan_id,
        current_stage_id=current_stage_id,
    )
    return EvidenceQueueSnapshot(
        pending=list(scoped["pending"]),
        deferred=list(scoped["deferred"]),
        adopted=list(scoped["adopted"]),
        rejected=list(scoped["rejected"]),
        history=list(scoped["history"]),
        unscoped=list(scoped.get("unscoped", [])),
        total_count=len(items),
    )
