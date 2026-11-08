"""Pure evidence queue projection extracted from MemoryService."""

from __future__ import annotations

from app.core.models import EvidenceItem
from app.memory.evidence_view import build_evidence_queue_snapshot


def _item(item_id: str, **updates: object) -> EvidenceItem:
    values: dict[str, object] = {
        "id": item_id,
        "workspace_id": "workspace-a",
        "summary": f"evidence {item_id}",
        "source": "training_handoff_return",
    }
    values.update(updates)
    return EvidenceItem(**values)


def test_queue_projection_classifies_lifecycle_without_memory_service() -> None:
    items = [
        _item("pending"),
        _item("deferred", deferred_at="2026-11-08T00:00:00+00:00"),
        _item("adopted", adopted=True),
        _item("rejected", rejected_at="2026-11-08T00:00:00+00:00"),
    ]
    snapshot = build_evidence_queue_snapshot(
        items=items,
        workspace_id="workspace-a",
        recovered=None,
        recovered_runtime=False,
    )
    assert [item.id for item in snapshot.pending] == ["pending"]
    assert [item.id for item in snapshot.deferred] == ["deferred"]
    assert [item.id for item in snapshot.adopted] == ["adopted"]
    assert [item.id for item in snapshot.rejected] == ["rejected"]
    assert snapshot.total_count == 4


def test_queue_projection_keeps_workspace_scope() -> None:
    items = [
        _item("mine"),
        _item("foreign", workspace_id="workspace-b"),
    ]
    snapshot = build_evidence_queue_snapshot(
        items=items,
        workspace_id="workspace-a",
        recovered=None,
        recovered_runtime=False,
    )
    assert [item.id for item in snapshot.pending] == ["mine"]
    assert snapshot.total_count == 2
