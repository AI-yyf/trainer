"""Phase-E regression tests: resource versioning, deletion propagation,
remote runner boundary, buffer vs saved disk, multi-window plan conflict."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.resources.versioning import (
    ResourceVersionStore,
    check_remote_runner_boundary,
    compute_content_hash,
)
from app.training.plan_revision import PlanRevisionConflict, PlanRevisionStore

# ---------------------------------------------------------------------------
# Resource versioning (E-1: TR-059 / TR-071)
# ---------------------------------------------------------------------------


def test_resource_version_increments_on_reupload(tmp_path: Path) -> None:
    store = ResourceVersionStore(tmp_path / "rv.db")
    v1 = store.record_version(workspace_id="ws-1", resource_id="res-1", content="version one")
    assert v1["version"] == 1
    v2 = store.record_version(workspace_id="ws-1", resource_id="res-1", content="version two")
    assert v2["version"] == 2
    assert v2["content_hash"] != v1["content_hash"]


def test_resource_version_content_hash_deterministic(tmp_path: Path) -> None:
    store = ResourceVersionStore(tmp_path / "rv.db")
    store.record_version(workspace_id="ws-1", resource_id="res-1", content="same content")
    store.record_version(workspace_id="ws-1", resource_id="res-1", content="same content")
    current = store.current_content_hash("ws-1", "res-1")
    expected = compute_content_hash("same content")
    assert current == expected


def test_resource_version_workspace_isolation(tmp_path: Path) -> None:
    store = ResourceVersionStore(tmp_path / "rv.db")
    store.record_version(workspace_id="ws-1", resource_id="res-1", content="ws1 content")
    current = store.current_content_hash("ws-2", "res-1")
    assert current is None, "cross-workspace resource lookup must return None"


# ---------------------------------------------------------------------------
# TR-100: remote workspace runner boundary
# ---------------------------------------------------------------------------


def test_remote_runner_boundary_allows_local_workspace() -> None:
    assert check_remote_runner_boundary(is_remote_workspace=False) is None


def test_remote_runner_boundary_blocks_remote_without_runner() -> None:
    result = check_remote_runner_boundary(is_remote_workspace=True, has_remote_runner=False)
    assert result is not None
    assert "Remote workspace" in result
    assert "no remote verification runner" in result


def test_remote_runner_boundary_allows_remote_with_runner() -> None:
    assert check_remote_runner_boundary(is_remote_workspace=True, has_remote_runner=True) is None


# ---------------------------------------------------------------------------
# Multi-window plan conflict (§4 / TR-044)
# ---------------------------------------------------------------------------


def test_plan_conflict_detected_on_stale_revision(tmp_path: Path) -> None:
    store = PlanRevisionStore(tmp_path / "plan.db")
    store.save_with_revision(workspace_id="ws-1", plan_id="plan-1", payload={"title": "v1"})

    # Window A saves revision 2.
    store.save_with_revision(
        workspace_id="ws-1", plan_id="plan-1",
        payload={"title": "v2"}, expected_revision=1,
    )

    # Window B still has revision 1 and tries to save — conflict.
    with pytest.raises(PlanRevisionConflict):
        store.save_with_revision(
            workspace_id="ws-1", plan_id="plan-1",
            payload={"title": "conflicting"}, expected_revision=1,
        )

    # The stored revision is still 2, not overwritten.
    assert store.current_revision("ws-1", "plan-1") == 2


def test_plan_no_conflict_when_revision_matches(tmp_path: Path) -> None:
    store = PlanRevisionStore(tmp_path / "plan.db")
    store.save_with_revision(workspace_id="ws-1", plan_id="plan-1", payload={"title": "v1"})

    r2 = store.save_with_revision(
        workspace_id="ws-1", plan_id="plan-1",
        payload={"title": "v2"}, expected_revision=1,
    )
    assert r2["revision"] == 2

    r3 = store.save_with_revision(
        workspace_id="ws-1", plan_id="plan-1",
        payload={"title": "v3"}, expected_revision=2,
    )
    assert r3["revision"] == 3
