"""Phase-D slice 2 integration tests: skill projection, plan revision
optimistic locking, cross-workspace isolation, and version expiry."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.core.models import LearningPlan
from app.db.repository import TrainerRepository
from app.training.attempt_store import AttemptStore
from app.training.plan_revision import PlanRevisionConflict, PlanRevisionStore
from app.training.skill_projection import project_skills


# ---------------------------------------------------------------------------
# Skill projection
# ---------------------------------------------------------------------------


def test_projection_current_only():
    records = [
        {"evidence_id": "e1", "is_current": True, "superseded_by_evidence_id": None,
         "result": "passed", "trust_level": "controlled_check", "assistance_level": "independent",
         "artifact_hash": "h1"},
        {"evidence_id": "e2", "is_current": False, "superseded_by_evidence_id": "e3",
         "result": "passed", "trust_level": "controlled_check", "assistance_level": "independent",
         "artifact_hash": "h0"},
        {"evidence_id": "e3", "is_current": True, "superseded_by_evidence_id": None,
         "result": "passed", "trust_level": "controlled_check", "assistance_level": "independent",
         "artifact_hash": "h2"},
    ]
    p = project_skills(records)
    assert p["implementation"]["verified_count"] == 2
    assert p["implementation"]["state"] in ("independent", "repeat_verified")


def test_projection_failed_goes_to_debugging():
    records = [
        {"evidence_id": "e1", "is_current": True, "superseded_by_evidence_id": None,
         "result": "failed", "trust_level": "controlled_check", "assistance_level": "independent",
         "artifact_hash": "h1"},
    ]
    p = project_skills(records)
    assert p["debugging"]["score"] < 0
    assert p["implementation"]["score"] <= 0


def test_projection_empty_evidence():
    p = project_skills([])
    for dim in p.values():
        assert dim["state"] == "not_verified"
        assert dim["score"] == 0


# ---------------------------------------------------------------------------
# Attempt + evidence: workspace isolation and version expiry (TR-059)
# ---------------------------------------------------------------------------


def test_attempt_workspace_isolation(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "t.db")
    a = store.start_attempt(workspace_id="ws-A", card_id="card-1", file_hash="hash-A")
    eid = a["attempt_id"]

    # Cross-workspace read returns None.
    assert store.get_attempt(eid, workspace_id="ws-B") is None
    # Same workspace read works.
    assert store.get_attempt(eid, workspace_id="ws-A") is not None

    # Cross-workspace update is a no-op.
    result = store.update_attempt_for_workspace(
        eid, workspace_id="ws-B", answer_draft="hijack"
    )
    assert result is None
    # Original attempt is unchanged.
    loaded = store.get_attempt_payload(eid)
    assert loaded["answer_draft"] == ""


def test_evidence_stale_on_hash_change(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "t.db")
    a = store.start_attempt(workspace_id="ws-1", card_id="card-1", file_hash="hash-v1")

    ev1 = store.record_evidence(
        attempt_id=a["attempt_id"], artifact_hash="hash-v1", result="passed"
    )
    assert ev1["is_current"] is True

    # File changes: old evidence becomes stale.
    store.update_attempt(a["attempt_id"], file_hash="hash-v2")
    items = store.list_evidence(a["attempt_id"])
    assert items[0]["is_current"] is False, (
        "old evidence must not read as current after file change"
    )

    # New evidence on the new hash is current.
    ev2 = store.record_evidence(
        attempt_id=a["attempt_id"], artifact_hash="hash-v2", result="passed"
    )
    assert ev2["is_current"] is True
    assert ev2["artifact_hash"] == "hash-v2"


# ---------------------------------------------------------------------------
# Plan revision optimistic locking (multi-window conflict)
# ---------------------------------------------------------------------------


class TestPlanRevisionOptimisticLock:
    def test_revision_increments(self, tmp_path: Path) -> None:
        repo = TrainerRepository(tmp_path / "t.db")
        plan = LearningPlan(id="plan-1", title="Test")
        repo.save_plan_with_revision("ws-1", plan, expected_revision=0)
        r2 = repo.save_plan_with_revision("ws-1", plan, expected_revision=1)
        assert r2["revision"] == 2

    def test_conflict_on_stale_revision(self, tmp_path: Path) -> None:
        repo = TrainerRepository(tmp_path / "t.db")
        plan = LearningPlan(id="plan-1", title="Test")
        repo.save_plan_with_revision("ws-1", plan, expected_revision=0)
        repo.save_plan_with_revision("ws-1", plan, expected_revision=1)

        # Stale save (expected_revision=0) should fail.
        result = repo.save_plan_with_revision("ws-1", plan, expected_revision=0)
        assert result is None

    def test_different_workspace_no_conflict(self, tmp_path: Path) -> None:
        repo = TrainerRepository(tmp_path / "t.db")
        plan = LearningPlan(id="plan-1", title="Test")
        repo.save_plan_with_revision("ws-1", plan, expected_revision=0)

        # Different workspace: no conflict.
        repo.save_plan_with_revision("ws-2", plan, expected_revision=0)
        r = repo.get_plan_revision("ws-2", "plan-1")
        assert r == 1

    def test_revision_survives_save_plan_roundtrip(self, tmp_path: Path) -> None:
        repo = TrainerRepository(tmp_path / "t.db")
        plan = LearningPlan(id="plan-1", title="Test")
        repo.save_plan_with_revision("ws-1", plan, expected_revision=0)
        repo.save_plan_with_revision("ws-1", plan, expected_revision=1)

        revision = repo.get_plan_revision("ws-1", "plan-1")
        assert revision == 2
