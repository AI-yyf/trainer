"""Phase-D second slice tests:

- Skill projection: evidence → skill states, recalculable, version-expiry aware
- Plan proposal versioning: optimistic locking, conflict detection
- Cross-workspace isolation for attempts and evidence
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.training.plan_revision import PlanRevisionConflict, PlanRevisionStore
from app.training.skill_projection import evidence_is_current_for_hash, project_skills

# ---------------------------------------------------------------------------
# Skill projection (TR-059 extension)
# ---------------------------------------------------------------------------


def _ev(hash_: str, result: str = "passed", **overrides: object) -> dict:
    base = {
        "evidence_id": f"ev-{hash_}",
        "artifact_hash": hash_,
        "result": result,
        "trust_level": "controlled_check",
        "assistance_level": "independent",
        "execution_location": "workspace",
        "is_current": True,
        "superseded_by_evidence_id": None,
    }
    base.update(overrides)
    return base


def test_current_evidence_drives_skill_state(tmp_path: Path) -> None:
    records = [
        _ev("h1", "passed"),
        _ev("h2", "passed"),
        _ev("h3", "passed"),
    ]
    for i, rec in enumerate(records):
        rec["evidence_id"] = f"ev-{i}"

    projection = project_skills(records, card_id="card-1")
    impl = projection["implementation"]
    assert impl["verified_count"] == 3
    assert impl["state"] == "repeat_verified"
    assert impl["score"] > 0


def test_stale_evidence_excluded_from_projection(tmp_path: Path) -> None:
    current = _ev("h2", "passed")
    current["evidence_id"] = "ev-current"
    stale = _ev("h1", "passed")
    stale["evidence_id"] = "ev-stale"
    stale["is_current"] = False
    stale["superseded_by_evidence_id"] = "ev-current"

    projection = project_skills([stale, current])
    assert projection["implementation"]["evidence_ids"] == ["ev-current"]


def test_superseded_evidence_excluded_even_if_is_current_flag_is_stale(tmp_path: Path) -> None:
    rec = _ev("h1", "passed")
    rec["superseded_by_evidence_id"] = "ev-newer"
    # Even if the caller forgot to clear is_current, the supersession wins.
    projection = project_skills([rec])
    assert projection["implementation"]["evidence_ids"] == []


def test_failed_evidence_contributes_to_debugging_not_implementation(tmp_path: Path) -> None:
    rec = _ev("h1", "failed", execution_location="workspace")
    projection = project_skills([rec])
    assert projection["implementation"]["score"] <= 0
    assert projection["debugging"]["score"] < 0


def test_assisted_evidence_scores_lower_than_independent(tmp_path: Path) -> None:
    independent = _ev("h1", "passed", assistance_level="independent")
    assisted = _ev("h2", "passed", assistance_level="hint_level_2")
    p_ind = project_skills([independent])
    p_asi = project_skills([assisted])
    assert p_ind["implementation"]["score"] > p_asi["implementation"]["score"]


# ---------------------------------------------------------------------------
# Plan revision optimistic locking (multi-window conflict detection)
# ---------------------------------------------------------------------------


def test_plan_revision_increments_on_each_save(tmp_path: Path) -> None:
    store = PlanRevisionStore(tmp_path / "plan.db")
    payload = {"title": "RL fundamentals"}

    r1 = store.save_with_revision(workspace_id="ws-1", plan_id="plan-1", payload=payload)
    assert r1["revision"] == 1

    r2 = store.save_with_revision(workspace_id="ws-1", plan_id="plan-1", payload=payload)
    assert r2["revision"] == 2

    latest = store.get_latest_payload("ws-1", "plan-1")
    assert latest == payload


def test_plan_revision_conflict_on_stale_expected_revision(tmp_path: Path) -> None:
    store = PlanRevisionStore(tmp_path / "plan.db")
    # Window A saves revision 1.
    store.save_with_revision(workspace_id="ws-1", plan_id="plan-1", payload={"v": 1})
    # Window B also sees revision 1 but hasn't saved yet.
    # Window A saves revision 2.
    store.save_with_revision(
        workspace_id="ws-1", plan_id="plan-1", payload={"v": 2}, expected_revision=1,
    )
    # Window B tries to save with expected_revision=1 — must conflict.
    with pytest.raises(PlanRevisionConflict) as exc_info:
        store.save_with_revision(
            workspace_id="ws-1", plan_id="plan-1",
            payload={"v": "stale"}, expected_revision=1,
        )
    assert exc_info.value.actual_revision == 2


def test_plan_revision_workspace_isolation(tmp_path: Path) -> None:
    store = PlanRevisionStore(tmp_path / "plan.db")
    store.save_with_revision(workspace_id="ws-1", plan_id="plan-1", payload={"scope": "ws-1"})
    store.save_with_revision(workspace_id="ws-2", plan_id="plan-1", payload={"scope": "ws-2"})

    ws1 = store.get_latest_payload("ws-1", "plan-1")
    ws2 = store.get_latest_payload("ws-2", "plan-1")
    assert ws1["scope"] == "ws-1"
    assert ws2["scope"] == "ws-2"


def test_evidence_is_current_for_hash_helper(tmp_path: Path) -> None:
    assert evidence_is_current_for_hash({"artifact_hash": "h1"}, "h1") is True
    assert evidence_is_current_for_hash({"artifact_hash": "h1"}, "h2") is False
    assert evidence_is_current_for_hash(
        {"artifact_hash": "h1", "superseded_by_evidence_id": "ev-newer"}, "h1",
    ) is False
