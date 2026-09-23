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


def test_failed_and_partial_evidence_never_become_assisted() -> None:
    failed = _ev("failed", "failed", assistance_level="hint_level_2")
    partial = _ev("partial", "partial", assistance_level="hint_level_2")

    failed_projection = project_skills([failed])
    partial_projection = project_skills([partial])

    assert failed_projection["implementation"]["state"] == "needs_review"
    assert partial_projection["implementation"]["state"] == "not_verified"
    assert failed_projection["implementation"]["state"] != "assisted"
    assert partial_projection["implementation"]["state"] != "assisted"


def test_assisted_requires_a_passed_non_independent_result() -> None:
    assisted = _ev("assisted", "passed", assistance_level="hint_level_1")
    interrupted = _ev(
        "interrupted",
        "failed",
        assistance_level="hint_level_1",
        execution_status="connection_lost",
    )

    assisted_projection = project_skills([assisted])
    interrupted_projection = project_skills([interrupted])

    assert assisted_projection["implementation"]["state"] == "assisted"
    assert interrupted_projection["implementation"]["state"] == "not_verified"
    assert interrupted_projection["implementation"]["score"] == 0


def test_repeat_verified_requires_distinct_attempts() -> None:
    same_attempt = [
        _ev("h1", attempt_id="attempt-1"),
        _ev("h2", attempt_id="attempt-1"),
    ]
    distinct_attempts = [
        _ev("h1", attempt_id="attempt-1"),
        _ev("h2", attempt_id="attempt-2"),
    ]

    same_projection = project_skills(same_attempt)
    distinct_projection = project_skills(distinct_attempts)

    assert same_projection["implementation"]["state"] == "independent"
    assert same_projection["implementation"]["independent_attempt_count"] == 1
    assert distinct_projection["implementation"]["state"] == "repeat_verified"
    assert distinct_projection["implementation"]["independent_attempt_count"] == 2


def test_transfer_requires_explicit_cross_scenario_fact() -> None:
    preview = _ev("preview", execution_location="preview")
    sandbox = _ev("sandbox", execution_location="sandbox")
    transferred = _ev(
        "transfer",
        execution_location="sandbox",
        scenario="new deployment scenario",
        environment={"runtime": "container"},
        constraints=["no helper script"],
    )

    without_fact = project_skills([preview, sandbox])
    with_fact = project_skills([transferred])

    assert without_fact["transfer"]["state"] == "not_verified"
    assert without_fact["transfer"]["evidence_ids"] == []
    assert with_fact["transfer"]["state"] == "independent"
    assert with_fact["transfer"]["evidence_ids"] == ["ev-transfer"]


def test_execution_interruptions_are_inconclusive_not_failed() -> None:
    records = [
        _ev(
            "interrupt",
            "failed",
            execution_status="interrupted",
        ),
        _ev(
            "connection",
            "failed",
            error_category="connection_loss",
        ),
    ]

    projection = project_skills(records)

    assert projection["implementation"]["state"] == "not_verified"
    assert projection["implementation"]["score"] == 0
    assert projection["debugging"]["state"] == "not_verified"
    assert projection["debugging"]["score"] == 0


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


# ---------------------------------------------------------------------------
# Internal plan writers stay revision-honest
# ---------------------------------------------------------------------------


def _revision_repository(tmp_path: Path):
    from app.core.models import LearningPlan
    from app.db.repository import TrainerRepository

    return TrainerRepository(tmp_path / "plans.db"), LearningPlan


def test_save_plan_advancing_revision_survives_concurrent_writes(tmp_path: Path) -> None:
    from app.training.plan_revision import save_plan_advancing_revision

    repository, LearningPlan = _revision_repository(tmp_path)
    plan = LearningPlan(id="plan-internal", title="Base", summary="s", stages=[])
    repository.save_plan("ws-internal", plan)
    base_revision = repository.get_plan_revision("ws-internal", "plan-internal")
    assert base_revision >= 1

    # A concurrent writer moves the plan after our read, before our write.
    moved = plan.model_copy(update={"title": "Moved by another window"})
    current = repository.get_plan_revision("ws-internal", "plan-internal")
    assert repository.save_plan_with_revision(
        "ws-internal", moved, expected_revision=current
    ) is not None

    # The internal writer retries against the new head instead of clobbering.
    updated = plan.model_copy(update={"title": "Internal advance"})
    new_revision = save_plan_advancing_revision(repository, "ws-internal", updated)
    assert new_revision == base_revision + 2
    stored = repository.get_latest_plan("ws-internal")
    assert stored.title == "Internal advance"
    assert repository.get_plan_revision("ws-internal", "plan-internal") == base_revision + 2


def test_save_plan_advancing_revision_falls_back_for_legacy_repositories(tmp_path: Path) -> None:
    from app.training.plan_revision import save_plan_advancing_revision

    class LegacyRepository:
        def __init__(self) -> None:
            self.plan = None

        def get_latest_plan(self, _workspace_id: str):
            return self.plan

        def save_plan(self, _workspace_id: str, plan) -> None:
            self.plan = plan

    repository = LegacyRepository()
    plan = object()
    assert save_plan_advancing_revision(repository, "ws-legacy", plan) is None
    assert repository.plan is plan


def test_legacy_save_plan_never_resets_the_revision_counter(tmp_path: Path) -> None:
    from app.training.plan_revision import save_plan_checked

    repository, LearningPlan = _revision_repository(tmp_path)
    plan = LearningPlan(id="plan-legacy", title="v1", summary="s", stages=[])
    repository.save_plan("ws-legacy", plan)
    first = repository.get_plan_revision("ws-legacy", "plan-legacy")
    assert first == 1

    checked = save_plan_checked(
        repository, "ws-legacy", plan.model_copy(update={"title": "v2"}), expected_revision=first
    )
    assert checked["revision"] == 2

    # A direct legacy save must not silently rewind the counter other
    # windows base their optimistic locking on.
    repository.save_plan("ws-legacy", plan.model_copy(update={"title": "v3"}))
    assert repository.get_plan_revision("ws-legacy", "plan-legacy") == 3
    stored = repository.get_latest_plan("ws-legacy")
    assert stored.title == "v3"


def test_evidence_is_current_for_hash_helper(tmp_path: Path) -> None:
    assert evidence_is_current_for_hash({"artifact_hash": "h1"}, "h1") is True
    assert evidence_is_current_for_hash({"artifact_hash": "h1"}, "h2") is False
    assert evidence_is_current_for_hash(
        {"artifact_hash": "h1", "superseded_by_evidence_id": "ev-newer"}, "h1",
    ) is False
