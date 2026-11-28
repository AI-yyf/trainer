"""(h) Learning plan lifecycle: projection, confirmation and revision keep plan state honest.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real objects;
nothing here asserts on source text or code shape):
  * server/tests/test_phase_d_projection_and_revision.py
  * server/tests/test_phase_d_slice2.py
  * server/tests/test_phase_e_resource_and_plan.py
  * server/tests/test_plan_fallback_card.py

Guarantees covered:
  * plan projection and revision carry the right stage, step and task;
  * plan updates and fallback cards stay bound to the live plan and workspace.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from app.api.runtime import TrainerRuntime
from app.core.models import CardGenerationContext, LearningPlan, TrainingPlanBinding
from app.db.repository import TrainerRepository
from app.evaluator.service import EvaluatorService
from app.resources.versioning import (
    ResourceVersionStore,
    check_remote_runner_boundary,
    compute_content_hash,
)
from app.training.attempt_store import AttemptStore
from app.training.card_generator import CardGenerationService
from app.training.plan_revision import PlanRevisionConflict, PlanRevisionStore
from app.training.skill_projection import evidence_is_current_for_hash, project_skills

# ---------------------------------------------------------------------------
# Restored from test_phase_d_projection_and_revision.py (commit df0a3e2a^)
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
        workspace_id="ws-1",
        plan_id="plan-1",
        payload={"v": 2},
        expected_revision=1,
    )
    # Window B tries to save with expected_revision=1 — must conflict.
    with pytest.raises(PlanRevisionConflict) as exc_info:
        store.save_with_revision(
            workspace_id="ws-1",
            plan_id="plan-1",
            payload={"v": "stale"},
            expected_revision=1,
        )
    assert exc_info.value.actual_revision == 2


def test_plan_revision_workspace_isolation(tmp_path: Path) -> None:
    store = PlanRevisionStore(tmp_path / "plan.db")
    store.save_with_revision(workspace_id="ws-1", plan_id="plan-1", payload={"scope": "ws-1"})
    store.save_with_revision(workspace_id="ws-2", plan_id="plan-1", payload={"scope": "ws-2"})

    ws1 = store.get_latest_payload("ws-1", "plan-1")
    ws2 = store.get_latest_payload("ws-2", "plan-1")
    assert ws1 is not None, "ws-1 must keep its own revision payload"
    assert ws2 is not None, "ws-2 must keep its own revision payload"
    assert ws1["scope"] == "ws-1"
    assert ws2["scope"] == "ws-2"


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
    assert (
        repository.save_plan_with_revision("ws-internal", moved, expected_revision=current)
        is not None
    )

    # The internal writer retries against the new head instead of clobbering.
    updated = plan.model_copy(update={"title": "Internal advance"})
    new_revision = save_plan_advancing_revision(repository, "ws-internal", updated)
    assert new_revision == base_revision + 2
    stored = repository.get_latest_plan("ws-internal")
    assert stored is not None, "the internal advance must be stored"
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
    assert stored is not None, "the legacy save must be stored"
    assert stored.title == "v3"


def test_plan_roundtrip_surfaces_the_revision_anchor_in_snapshots(tmp_path: Path) -> None:
    """Snapshots serialize the plan's revision anchor so clients can base
    their next formal save on the real head (restart-safe optimistic lock)."""
    from app.core.models import LearningPlan
    from app.db.repository import TrainerRepository

    repository = TrainerRepository(tmp_path / "plans.db")
    plan = LearningPlan(id="plan-anchor", title="Anchor", summary="s", stages=[])
    repository.save_plan_with_revision("ws-anchor", plan, expected_revision=0)

    revived = repository.get_latest_plan("ws-anchor")
    assert revived is not None
    dumped = revived.model_dump(mode="json")
    assert dumped.get("_plan_revision") == 1


def test_evidence_is_current_for_hash_helper(tmp_path: Path) -> None:
    assert evidence_is_current_for_hash({"artifact_hash": "h1"}, "h1") is True
    assert evidence_is_current_for_hash({"artifact_hash": "h1"}, "h2") is False
    assert (
        evidence_is_current_for_hash(
            {"artifact_hash": "h1", "superseded_by_evidence_id": "ev-newer"},
            "h1",
        )
        is False
    )


def test_transfer_repeat_verified_requires_distinct_contexts() -> None:
    """同一场景反复验证不增长迁移能力;两个不同上下文才构成 repeat_verified。"""
    same_context = [
        _ev(
            "t1",
            attempt_id="attempt-1",
            scenario="deployment",
            environment={"runtime": "container"},
        ),
        _ev(
            "t2",
            attempt_id="attempt-2",
            scenario="deployment",
            environment={"runtime": "container"},
        ),
    ]
    distinct_context = [
        same_context[0],
        _ev(
            "t2",
            attempt_id="attempt-2",
            scenario="incident triage",
            environment={"runtime": "bare metal"},
            constraints=["no container runtime"],
        ),
    ]

    same_projection = project_skills(same_context)
    distinct_projection = project_skills(distinct_context)

    assert same_projection["transfer"]["state"] == "independent"
    assert same_projection["transfer"]["independent_attempt_count"] == 2
    assert distinct_projection["transfer"]["state"] == "repeat_verified"


def test_projection_carries_evidence_drilldown_rows_newest_first() -> None:
    """§十八: every dimension lists contributing evidence (time · assistance ·
    scenario), newest first, so the UI can answer why a state was judged."""
    records = [
        _ev(
            "h1",
            attempt_id="attempt-1",
            created_at="2026-09-27T10:00:00Z",
            scenario="q-learning update",
        ),
        _ev(
            "h2",
            attempt_id="attempt-2",
            created_at="2026-09-28T10:00:00Z",
            scenario="terminal-state variant",
        ),
    ]

    projection = project_skills(records)
    rows = projection["implementation"]["evidence"]

    assert [row["evidence_id"] for row in rows] == ["ev-h2", "ev-h1"]
    assert rows[0]["timestamp"].startswith("2026-09-28")
    assert rows[0]["assistance_level"] == "independent"
    assert rows[1]["scenario"] == "q-learning update"


def _lit_ev(evidence_id: str, **overrides: Any) -> dict:
    return _ev(evidence_id, evidence_id=evidence_id, **overrides)


def test_literature_dimension_set_projects_without_engineering_rows() -> None:
    from app.training.skill_projection import LITERATURE_DIMENSIONS

    records = [
        _lit_ev("lit-1", attempt_id="a1"),
        _lit_ev("lit-2", attempt_id="a2"),
    ]
    projection = project_skills(
        records,
        card_id="card-lit",
        dimensions=LITERATURE_DIMENSIONS,
        default_dimension="comprehension",
    )
    assert set(projection) == {
        "comprehension",
        "expression",
        "appreciation",
        "transfer",
        "delayed_recall",
    }
    # No explicit dimension field → comprehension (the submission's first
    # obligation is the text response), and two distinct attempts make it
    # repeat_verified under the same governance ladder.
    assert projection["comprehension"]["state"] == "repeat_verified"
    assert projection["comprehension"]["verified_count"] == 2
    for dim in ("expression", "appreciation", "transfer", "delayed_recall"):
        assert projection[dim]["state"] == "not_verified"
        assert projection[dim]["verified_count"] == 0


def test_explicit_literature_dimension_field_still_routs() -> None:
    from app.training.skill_projection import LITERATURE_DIMENSIONS

    records = [
        _lit_ev("lit-a", attempt_id="a1", dimension="expression"),
        _lit_ev("lit-b", attempt_id="a2", dimension="appreciation"),
    ]
    projection = project_skills(
        records, dimensions=LITERATURE_DIMENSIONS, default_dimension="comprehension"
    )
    assert projection["expression"]["verified_count"] == 1
    assert projection["appreciation"]["verified_count"] == 1
    assert projection["comprehension"]["verified_count"] == 0


def test_default_call_keeps_the_historical_code_vocabulary() -> None:
    projection = project_skills([_ev("h1")])
    assert list(projection) == [
        "comprehension",
        "implementation",
        "debugging",
        "transfer",
        "delayed_recall",
    ]
    assert projection["implementation"]["verified_count"] == 1


def test_unknown_duplicate_or_out_of_set_dimensions_fail_closed() -> None:
    with pytest.raises(ValueError):
        project_skills([], dimensions=("comprehension", "gibberish"))
    with pytest.raises(ValueError):
        project_skills([], dimensions=("comprehension", "comprehension"))
    with pytest.raises(ValueError):
        project_skills([], dimensions=())
    with pytest.raises(ValueError):
        project_skills([], dimensions=None, default_dimension="appreciation")
    # The literature default is inside its own set — sanity mirror.
    from app.training.skill_projection import LITERATURE_DIMENSIONS

    project_skills([], dimensions=LITERATURE_DIMENSIONS, default_dimension="comprehension")


class _StoreStub:
    def __init__(self, attempts: list[dict], evidence: dict[str, list[dict]]):
        self._attempts = attempts
        self._evidence = evidence

    def list_attempts(self, *, workspace_id: str) -> list[dict]:
        return [a for a in self._attempts if a["workspace_id"] == workspace_id]

    def list_evidence(self, attempt_id: str) -> list[dict]:
        return list(self._evidence.get(attempt_id, []))


class _MemoryStub:
    def __init__(self, cards: dict[str, object]):
        self._cards = cards

    def get_card(self, workspace_id: str, card_id: str):
        return self._cards.get(card_id)

    def update_workspace_state(self, workspace_id: str, **kwargs: object) -> None:
        self.saved = kwargs


class _RuntimeStub:
    def __init__(self, store, memory):
        self.attempt_store = store
        self.memory_service = memory


def _lit_card(card_id: str):
    from app.core.models import TrainingCardCandidateSnapshot

    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type="practice",
        title="《孔乙己》批注练习",
        target_skill="annotation",
        scenario_pack="literature_close_reading",
        validation_method="Run the anchored rubric review.",
    )


def test_resolve_workspace_scope_votes_majority_and_ties_to_code() -> None:
    from app.api.training_skill_evidence import resolve_workspace_projection_scope

    lit_card = _lit_card("card-lit")
    code_card = None  # unknown card id → code family
    store = _StoreStub(
        [
            {"workspace_id": "ws", "card_id": "card-lit"},
            {"workspace_id": "ws", "card_id": "card-lit"},
            {"workspace_id": "ws", "card_id": "card-code"},
        ],
        {},
    )
    runtime = _RuntimeStub(store, _MemoryStub({"card-lit": lit_card, "card-code": code_card}))
    family, dimensions, default_dimension = resolve_workspace_projection_scope(
        # Duck-typed test double standing in for TrainerRuntime.
        cast(TrainerRuntime, runtime), "ws"
    )
    assert family == "literature"
    assert dimensions == (
        "comprehension",
        "expression",
        "appreciation",
        "transfer",
        "delayed_recall",
    )
    assert default_dimension == "comprehension"

    tie = _StoreStub(
        [
            {"workspace_id": "ws2", "card_id": "card-lit"},
            {"workspace_id": "ws2", "card_id": "card-code"},
        ],
        {},
    )
    family2, dimensions2, default2 = resolve_workspace_projection_scope(
        # Duck-typed test double standing in for TrainerRuntime.
        cast(TrainerRuntime, _RuntimeStub(tie, _MemoryStub({"card-lit": lit_card}))),
        "ws2",
    )
    assert family2 == "code"
    assert dimensions2 == (
        "comprehension",
        "implementation",
        "debugging",
        "transfer",
        "delayed_recall",
    )
    assert default2 == "implementation"


"""Phase-D second slice tests:

- Skill projection: evidence → skill states, recalculable, version-expiry aware
- Plan proposal versioning: optimistic locking, conflict detection
- Cross-workspace isolation for attempts and evidence
"""

# ---------------------------------------------------------------------------
# Restored from test_phase_d_slice2.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_projection_current_only():
    records = [
        {
            "evidence_id": "e1",
            "is_current": True,
            "superseded_by_evidence_id": None,
            "result": "passed",
            "trust_level": "controlled_check",
            "assistance_level": "independent",
            "artifact_hash": "h1",
        },
        {
            "evidence_id": "e2",
            "is_current": False,
            "superseded_by_evidence_id": "e3",
            "result": "passed",
            "trust_level": "controlled_check",
            "assistance_level": "independent",
            "artifact_hash": "h0",
        },
        {
            "evidence_id": "e3",
            "is_current": True,
            "superseded_by_evidence_id": None,
            "result": "passed",
            "trust_level": "controlled_check",
            "assistance_level": "independent",
            "artifact_hash": "h2",
        },
    ]
    p = project_skills(records)
    assert p["implementation"]["verified_count"] == 2
    assert p["implementation"]["state"] in ("independent", "repeat_verified")


def test_projection_failed_goes_to_debugging():
    records = [
        {
            "evidence_id": "e1",
            "is_current": True,
            "superseded_by_evidence_id": None,
            "result": "failed",
            "trust_level": "controlled_check",
            "assistance_level": "independent",
            "artifact_hash": "h1",
        },
    ]
    p = project_skills(records)
    assert p["debugging"]["score"] < 0
    assert p["implementation"]["score"] <= 0


def test_projection_empty_evidence():
    p = project_skills([])
    for dim in p.values():
        assert dim["state"] == "not_verified"
        assert dim["score"] == 0


def test_attempt_workspace_isolation(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "t.db")
    a = store.start_attempt(workspace_id="ws-A", card_id="card-1", file_hash="hash-A")
    eid = a["attempt_id"]

    # Cross-workspace read returns None.
    assert store.get_attempt(eid, workspace_id="ws-B") is None
    # Same workspace read works.
    assert store.get_attempt(eid, workspace_id="ws-A") is not None

    # Cross-workspace update is a no-op.
    result = store.update_attempt_for_workspace(eid, workspace_id="ws-B", answer_draft="hijack")
    assert result is None
    # Original attempt is unchanged.
    loaded = store.get_attempt_payload(eid)
    assert loaded is not None, "the original attempt must still be readable"
    assert loaded["answer_draft"] == ""


def test_evidence_stale_on_hash_change(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "t.db")
    a = store.start_attempt(workspace_id="ws-1", card_id="card-1", file_hash="hash-v1")

    ev1 = store.record_evidence(
        attempt_id=a["attempt_id"], artifact_hash="hash-v1", result="passed"
    )
    assert ev1 is not None, "evidence on the first hash must be recorded"
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
    assert ev2 is not None, "evidence on the new hash must be recorded"
    assert ev2["is_current"] is True
    assert ev2["artifact_hash"] == "hash-v2"


class TestPlanRevisionOptimisticLock:
    def test_revision_increments(self, tmp_path: Path) -> None:
        repo = TrainerRepository(tmp_path / "t.db")
        plan = LearningPlan(id="plan-1", title="Test")
        repo.save_plan_with_revision("ws-1", plan, expected_revision=0)
        r2 = repo.save_plan_with_revision("ws-1", plan, expected_revision=1)
        assert r2 is not None, "the second save must return its revision record"
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
        plan_a = LearningPlan(id="plan-a", title="A")
        plan_b = LearningPlan(id="plan-b", title="B")
        repo.save_plan_with_revision("ws-1", plan_a, expected_revision=0)
        repo.save_plan_with_revision("ws-2", plan_b, expected_revision=0)
        assert repo.get_plan_revision("ws-1", "plan-a") == 1
        assert repo.get_plan_revision("ws-2", "plan-b") == 1

    def test_cross_workspace_plan_id_collision_rejected(self, tmp_path: Path) -> None:
        repo = TrainerRepository(tmp_path / "t.db")
        plan = LearningPlan(id="plan-1", title="Test")
        saved = repo.save_plan_with_revision("ws-1", plan, expected_revision=0)
        assert saved is not None
        # Plan ids are globally unique: another workspace using the same id
        # is a collision, rejected instead of a silent overwrite.
        assert repo.save_plan_with_revision("ws-2", plan, expected_revision=0) is None
        assert repo.get_plan_revision("ws-1", "plan-1") == 1
        assert repo.get_plan_revision("ws-2", "plan-1") == 0

    def test_revision_survives_save_plan_roundtrip(self, tmp_path: Path) -> None:
        repo = TrainerRepository(tmp_path / "t.db")
        plan = LearningPlan(id="plan-1", title="Test")
        repo.save_plan_with_revision("ws-1", plan, expected_revision=0)
        repo.save_plan_with_revision("ws-1", plan, expected_revision=1)

        revision = repo.get_plan_revision("ws-1", "plan-1")
        assert revision == 2


"""Phase-D slice 2 integration tests: skill projection, plan revision
optimistic locking, cross-workspace isolation, and version expiry."""

# ---------------------------------------------------------------------------
# Restored from test_phase_e_resource_and_plan.py (commit df0a3e2a^)
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


def test_remote_runner_boundary_allows_local_workspace() -> None:
    assert check_remote_runner_boundary(is_remote_workspace=False) is None


def test_remote_runner_boundary_blocks_remote_without_runner() -> None:
    result = check_remote_runner_boundary(is_remote_workspace=True, has_remote_runner=False)
    assert result is not None
    assert "Remote workspace" in result
    assert "no remote verification runner" in result


def test_remote_runner_boundary_allows_remote_with_runner() -> None:
    assert check_remote_runner_boundary(is_remote_workspace=True, has_remote_runner=True) is None


def test_plan_conflict_detected_on_stale_revision(tmp_path: Path) -> None:
    store = PlanRevisionStore(tmp_path / "plan.db")
    store.save_with_revision(workspace_id="ws-1", plan_id="plan-1", payload={"title": "v1"})

    # Window A saves revision 2.
    store.save_with_revision(
        workspace_id="ws-1",
        plan_id="plan-1",
        payload={"title": "v2"},
        expected_revision=1,
    )

    # Window B still has revision 1 and tries to save — conflict.
    with pytest.raises(PlanRevisionConflict):
        store.save_with_revision(
            workspace_id="ws-1",
            plan_id="plan-1",
            payload={"title": "conflicting"},
            expected_revision=1,
        )

    # The stored revision is still 2, not overwritten.
    assert store.current_revision("ws-1", "plan-1") == 2


def test_plan_no_conflict_when_revision_matches(tmp_path: Path) -> None:
    store = PlanRevisionStore(tmp_path / "plan.db")
    store.save_with_revision(workspace_id="ws-1", plan_id="plan-1", payload={"title": "v1"})

    r2 = store.save_with_revision(
        workspace_id="ws-1",
        plan_id="plan-1",
        payload={"title": "v2"},
        expected_revision=1,
    )
    assert r2["revision"] == 2

    r3 = store.save_with_revision(
        workspace_id="ws-1",
        plan_id="plan-1",
        payload={"title": "v3"},
        expected_revision=2,
    )
    assert r3["revision"] == 3


"""Phase-E regression tests: resource versioning, deletion propagation,
remote runner boundary, buffer vs saved disk, multi-window plan conflict."""

# ---------------------------------------------------------------------------
# Restored from test_plan_fallback_card.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------

QUEUE_LOCK_CODE = '''"""Lock-protected queue practice."""

import threading


class Queue:
    def __init__(self):
        self._items = []
        self._lock = threading.Lock()

    def push(self, item):
        with self._lock:
            self._items.append(item)

    def pop(self):
        with self._lock:
            if not self._items:
                raise IndexError("empty")
            return self._items.pop(0)

    def try_pop(self):
        self._lock.acquire()
        try:
            if not self._items:
                raise IndexError("empty")
            return self._items.pop(0)
        finally:
            self._lock.release()
'''


def _plan_context() -> CardGenerationContext:
    return CardGenerationContext(
        workspace_id="ws-plan-fallback",
        response_language="zh-CN",
        card_type="practice",
        plan_stage_id="stage-lock",
        planBinding=TrainingPlanBinding(
            planId="plan-lock",
            stageId="stage-lock",
            step="在 queue_lock.py 中标出 with self._lock 的进入、退出和异常路径",
            revision=3,
        ),
        focus_area="验证异常释放",
        target_skill="证明 with/finally 在异常路径释放锁",
        currentFilePath="src/queue_lock.py",
        currentFileLanguageId="python",
        currentFileContent=QUEUE_LOCK_CODE,
    )


def test_plan_fallback_card_uses_real_file_symbols_and_passes_acceptance() -> None:
    card = CardGenerationService(provider_service=None).generate_card(
        "plan_requirement",
        _plan_context(),
        allow_llm=False,
        fallback_reason="provider_stalled",
    )

    assert card.plan_links == ["stage-lock"]
    assert card.files_to_touch == ["queue_lock.py"]
    assert {"self._lock", "acquire", "release", "finally"} <= set(card.expected_symbols)
    assert all("`" in criterion for criterion in card.acceptance_criteria)
    # generation_* provenance is an undeclared extra (extra="allow") attached via
    # model_copy in CardGenerationService._finalize_card, so read it via model_extra.
    provenance = card.model_extra
    assert provenance is not None, "candidate snapshots keep extras (extra=allow)"
    assert provenance["generation_status"] == "degraded"
    assert provenance["generation_fallback_reason"] == "provider_stalled"
    assert provenance["generation_recoverable"] is True

    check = EvaluatorService()._training_acceptance_check(
        source="training",
        code=QUEUE_LOCK_CODE,
        language_id="python",
        acceptance_criteria=card.acceptance_criteria,
        learner_deliverables=[],
        expected_symbols=card.expected_symbols,
        execution_passed=False,
    )
    assert check is not None
    assert check.status == "passed", check.detail
    assert "7/7 acceptance signals matched" in check.detail


class _StallingStreamProvider:
    async def chat_completion_stream(self, *args, **kwargs):
        del args, kwargs
        await asyncio.sleep(30)
        yield ""


def test_stalled_plan_stream_falls_back_to_the_plan_card() -> None:
    service = CardGenerationService(provider_service=_StallingStreamProvider())

    async def collect():
        return [
            event
            async for event in service.generate_card_stream(
                "plan_requirement",
                _plan_context(),
            )
        ]

    with patch(
        "app.training.card_generator._CARD_STREAM_IDLE_TIMEOUT_SECONDS",
        0.01,
    ):
        events = asyncio.run(collect())

    cards = [event.card for event in events if event.card is not None]
    assert len(cards) == 1
    card = cards[0]
    assert card.plan_links == ["stage-lock"]
    # generation_fallback_reason is an undeclared extra (extra="allow"), see above.
    provenance = card.model_extra
    assert provenance is not None, "candidate snapshots keep extras (extra=allow)"
    assert provenance["generation_fallback_reason"] == "provider_stalled"
    assert card.files_to_touch == ["queue_lock.py"]
    assert "`self._lock`" in card.acceptance_criteria[0]


class _PartialThenFailingProvider:
    async def chat_completion_stream(self, *args, **kwargs):
        del args, kwargs
        yield '{"title": "partial'
        raise RuntimeError("upstream reset")


def test_partial_stream_still_fails_honestly_instead_of_faking_a_card() -> None:
    service = CardGenerationService(provider_service=_PartialThenFailingProvider())

    async def collect():
        return [
            event
            async for event in service.generate_card_stream(
                "plan_requirement",
                _plan_context(),
            )
        ]

    try:
        asyncio.run(collect())
    except Exception as exc:  # noqa: BLE001 - the stream error type is the assertion
        assert "plan_requirement" in str(exc) or "card" in str(exc).lower()
    else:
        raise AssertionError("partial provider text must not be replaced by a fallback card")


def test_statement_symbol_and_reflection_evidence_pass_the_model_card_contract() -> None:
    check = EvaluatorService()._training_acceptance_check(
        source="training",
        code=QUEUE_LOCK_CODE,
        language_id="python",
        acceptance_criteria=[
            "使用 `with self._lock` 标出进入、正常退出和异常退出边界。",
            "通过 `self._lock` 的再次获取结果证明异常发生后锁已释放。",
            "定义 `self._lock` 异常退出时必须保留的上下文管理器释放路径。",
            "通过 `queue_lock.py` 的 Debug Console 或测试输出记录异常传播与释放证据。",
        ],
        learner_deliverables=[],
        expected_symbols=["self._lock", "with self._lock"],
        execution_passed=False,
    )
    assert check is not None
    assert check.status == "passed", check.detail
    assert "5/6 acceptance signals matched" in check.detail
    assert "Deferred to reflection" in check.detail


def test_file_target_verification_criterion_matches_the_current_file() -> None:
    check = EvaluatorService()._training_acceptance_check(
        source="training",
        code=QUEUE_LOCK_CODE,
        language_id="python",
        acceptance_criteria=[
            "使用 `with` 完成交付物中的关键一步",
            "定义 `finally` 并让它出现在提交的代码里",
            "通过 `queue_lock.py` 验证最终结果",
            "运行时无 `SyntaxError` 或 `RuntimeError`",
        ],
        learner_deliverables=[],
        expected_symbols=["queue_lock.py", "with", "finally"],
        execution_passed=True,
    )
    assert check is not None
    assert check.status == "passed", check.detail
    assert "6/6 acceptance signals matched" in check.detail


def test_file_target_criterion_stays_missing_without_target_evidence() -> None:
    check = EvaluatorService()._training_acceptance_check(
        source="training",
        code=QUEUE_LOCK_CODE,
        language_id="python",
        acceptance_criteria=["通过 `other_file.py` 验证最终结果"],
        learner_deliverables=[],
        expected_symbols=["with"],
        execution_passed=False,
    )
    assert check is not None
    assert check.status == "failed"
    assert "other_file.py" in check.detail


def test_implementation_file_criterion_is_not_credited_by_the_file_target() -> None:
    check = EvaluatorService()._training_acceptance_check(
        source="training",
        code=QUEUE_LOCK_CODE,
        language_id="python",
        acceptance_criteria=["实现 `queue_lock.py` 中的真实行为"],
        learner_deliverables=[],
        expected_symbols=["queue_lock.py"],
        execution_passed=True,
    )
    assert check is not None
    assert check.status == "failed"
