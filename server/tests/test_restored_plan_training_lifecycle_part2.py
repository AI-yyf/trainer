"""(q) Plan and training lifecycle: plans, tasks, cards and handoffs move only
    through their explicit transitions and stay bound to the live plan and workspace.

Guarantees covered:
  * formal plans mutate only under optimistic locking and never from a leftover;
  * live-plan gates on task tools, task specification and plan updates fail closed;
  * training cards change status only through valid transitions and stay workspace-bound;
  * handoffs, returns, reflections and attestations record only what really happened;
  * card generation retries once, stays honest on provider failure, and never invents facts.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_training_handoff_phases.py
  * server/tests/test_course_fork.py
  * server/tests/test_dependency_mastery_stages.py
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.models import ResourceRecord, TrainingCardCandidateSnapshot, UserProfile
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService
from app.training.course_fork import FIRST_CARD_DEFERRED, FIRST_CARD_GENERATED, fork_course_manifest
from app.training.course_pack import (
    COURSE_MANIFEST_TYPE,
    COURSE_MANIFEST_VERSION,
    inspect_course_manifest,
)
from app.training.handoff import HandoffStatus, TrainingHandoffGenerator, TrainingPhase

# ---------------------------------------------------------------------------
# Restored from test_training_handoff_phases.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _card(card_id: str = "phase-card") -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type="practice",
        title="Verify one parser boundary",
        target_skill="parser boundary",
        validation_method="Run the focused parser test.",
    )


@pytest.mark.parametrize("display_phase", ["learn", "try", "verify", "reflect"])
def test_committed_return_timestamp_wins_over_stale_display_phase(display_phase: str) -> None:
    assert TrainingHandoffGenerator._restored_phase(
        {"learning_phase": display_phase, "returned_at": "2026-10-01T22:52:06+00:00"},
        verification_state="verified", reflection="Expected TypeError was caught.",
        status=HandoffStatus.COMPLETED,
    ) is TrainingPhase.RETURN


def test_handoff_blocks_verification_and_return_before_try() -> None:
    generator = TrainingHandoffGenerator()
    handoff = generator.build_handoff_record(_card(), {})

    assert handoff.phase is TrainingPhase.LEARN
    unchanged = generator.record_verification(
        handoff.handoff_id,
        "pytest: 1 passed",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )

    assert unchanged is handoff
    assert handoff.phase is TrainingPhase.LEARN
    assert handoff.verification_state == "evidence_required"
    assert handoff.status is not HandoffStatus.COMPLETED
    with pytest.raises(ValueError, match="Return requires Learn, Try"):
        generator.return_handoff(handoff.handoff_id)


def test_handoff_requires_reflection_before_return_and_never_claims_mastery() -> None:
    generator = TrainingHandoffGenerator()
    handoff = generator.build_handoff_record(_card(), {})

    tried = generator.record_try(handoff.handoff_id, "Implemented the parser guard and ran the target case.")
    assert tried is handoff
    assert handoff.phase is TrainingPhase.TRY

    verified = generator.record_verification(
        handoff.handoff_id,
        "pytest tests/test_parser.py -k boundary: 1 passed",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )
    assert verified is handoff
    assert handoff.phase is TrainingPhase.VERIFY
    assert handoff.verification_state == "verified"

    with pytest.raises(ValueError, match="Return requires Learn, Try"):
        generator.return_handoff(handoff.handoff_id)

    reflected = generator.record_reflection(
        handoff.handoff_id,
        "The failing edge case showed why the guard belongs before token parsing.",
    )
    assert reflected is handoff
    assert handoff.phase is TrainingPhase.REFLECT

    returned = generator.return_handoff(handoff.handoff_id)
    assert returned is handoff
    assert handoff.phase is TrainingPhase.RETURN
    assert handoff.status is HandoffStatus.COMPLETED
    assert handoff.returned_at is not None
    assert "mastered" not in handoff.handoff_content.success_signal.lower()
    assert [event.phase for event in handoff.phase_history] == [
        TrainingPhase.LEARN,
        TrainingPhase.TRY,
        TrainingPhase.VERIFY,
        TrainingPhase.REFLECT,
        TrainingPhase.RETURN,
    ]


def test_handoff_recovers_reflection_gate_after_interruption(tmp_path) -> None:
    generator = TrainingHandoffGenerator(workspace_root=tmp_path)
    handoff = generator.build_handoff_record(
        _card("resume-phase-card"),
        {
            "correct": True,
            "evidence": ["Learner supplied a local test summary."],
            "evidence_source": "learner_submission",
        },
    )
    generator.write_handoff_to_workspace(handoff)

    generator.record_verification(
        handoff.handoff_id,
        "pytest tests/test_parser.py -k boundary: 1 passed",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )
    generator.record_reflection(handoff.handoff_id, "The evidence separated a passing branch from a guess.")

    recovered = TrainingHandoffGenerator(workspace_root=tmp_path).resume_handoff(handoff.handoff_id)
    assert recovered is not None
    assert recovered.phase is TrainingPhase.REFLECT
    assert recovered.verification_state == "verified"
    assert recovered.status is HandoffStatus.WRITTEN

    returned = TrainingHandoffGenerator(workspace_root=tmp_path).return_handoff(handoff.handoff_id)
    assert returned is not None
    assert returned.phase is TrainingPhase.RETURN
    assert returned.status is HandoffStatus.COMPLETED

    resumed_after_return = TrainingHandoffGenerator(workspace_root=tmp_path).resume_handoff(handoff.handoff_id)
    assert resumed_after_return is not None
    assert resumed_after_return.phase is TrainingPhase.RETURN
    assert resumed_after_return.returned_at is not None


def test_verified_initial_evidence_still_requires_explicit_reflection() -> None:
    generator = TrainingHandoffGenerator()
    handoff = generator.build_handoff_record(
        _card("trusted-start"),
        {
            "correct": True,
            "evidence": ["focused test: passed"],
            "evidence_source": "test_runner",
            "verified_by_evaluator": True,
        },
    )

    assert handoff.phase is TrainingPhase.VERIFY
    assert handoff.verification_state == "verified"
    with pytest.raises(ValueError, match="Return requires Learn, Try"):
        generator.complete_return(handoff.handoff_id)


def test_practice_evaluation_keeps_active_card_pending_after_verify_only(tmp_path) -> None:
    workspace_id = "phase-memory-pending"
    service = MemoryService(TrainerRepository(tmp_path / "pending.db"))
    card = _card("pending-card").model_copy(update={"status": "active"})
    service.upsert_card(workspace_id, card)

    result = service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="pytest tests/test_parser.py -k boundary: 1 passed",
        next_step="Return to Coach with the test output.",
        focus_area="parser boundary",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )

    stored = service.get_card(workspace_id, card.card_id)
    assert stored is not None
    assert stored.status == "active"
    assert result["selected_card_status"] == "active"
    assert result["latest_training_handoff"]["learning_phase"] == "verify"
    assert result["latest_training_handoff"]["status"] != HandoffStatus.COMPLETED.value
    assert result["latest_training_handoff"]["return_mode"] == "reflection_required"
    assert result["latest_learning_verified_result"] == ""


def test_practice_evaluation_accepts_only_recovered_terminal_handoff(tmp_path) -> None:
    workspace_id = "phase-memory-returned"
    database_path = tmp_path / "returned.db"
    service = MemoryService(TrainerRepository(database_path))
    card = _card("returned-card").model_copy(update={"status": "active"})
    service.upsert_card(workspace_id, card)

    generator = TrainingHandoffGenerator()
    terminal = generator.build_handoff_record(
        card,
        {
            "correct": True,
            "evidence": ["pytest tests/test_parser.py -k boundary: 1 passed"],
            "evidence_source": "test_runner",
            "verified_by_evaluator": True,
        },
    )
    generator.record_reflection(terminal.handoff_id, "The check proved the guard belongs before parsing.")
    generator.return_handoff(terminal.handoff_id)

    structured = service._structured_for(workspace_id)
    structured.update_workspace(
        workspace_id=workspace_id,
        latest_training_handoff=TrainingHandoffGenerator._handoff_payload(terminal),
    )
    service._persist_structured(workspace_id)
    restarted = MemoryService(TrainerRepository(database_path))

    result = restarted.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="pytest tests/test_parser.py -k boundary: 1 passed",
        next_step="Continue with the next card.",
        focus_area="parser boundary",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )

    stored = restarted.get_card(workspace_id, card.card_id)
    assert stored is not None
    assert stored.status == "implemented"
    assert result["selected_card_status"] == "implemented"
    assert result["latest_training_handoff"]["learning_phase"] == "return"
    assert result["latest_training_handoff"]["status"] == HandoffStatus.COMPLETED.value


def test_card_learning_phase_persists_through_try_verify_reflect_return(tmp_path) -> None:
    database_path = tmp_path / "trainer-card-learning-phase.db"
    service = MemoryService(TrainerRepository(database_path))
    workspace_id = "workspace-learning-phase"
    card = service.upsert_card(
        workspace_id,
        TrainingCardCandidateSnapshot(
            card_id="loop-card",
            card_type="practice",
            title="Keep the learning loop on the card",
            target_skill="learning loop",
            validation_method="Run the focused loop test.",
            status="candidate",
        ),
    )
    assert card.learning_phase == "learn"

    active = service.transition_card_status(workspace_id, card.card_id, "active", reason="Start try.")
    assert active.card.learning_phase == "try"

    workspace = service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="pytest tests/test_loop.py: 1 passed",
        next_step="Record the reflection.",
        focus_area="learning loop",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )
    stored = service.get_card(workspace_id, card.card_id)
    assert stored is not None
    assert stored.learning_phase == "verify"
    assert workspace["latest_training_handoff"]["learning_phase"] == "verify"

    reflected = service.record_training_handoff_reflection(
        workspace_id=workspace_id,
        card_id=card.card_id,
        reflection="The failing case showed why the loop must stay on the card.",
        handoff_id=workspace["latest_training_handoff"]["handoff_id"],
    )
    stored = service.get_card(workspace_id, card.card_id)
    assert stored is not None
    assert stored.learning_phase == "reflect"
    assert reflected["latest_training_handoff"]["learning_phase"] == "reflect"

    returned = service.return_training_handoff(
        workspace_id=workspace_id,
        card_id=card.card_id,
        handoff_id=workspace["latest_training_handoff"]["handoff_id"],
    )
    stored = service.get_card(workspace_id, card.card_id)
    assert stored is not None
    assert stored.learning_phase == "return"
    assert returned["latest_training_handoff"]["learning_phase"] == "return"


# ---------------------------------------------------------------------------
# Restored from test_course_fork.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


_FRAGMENT_FOCUS = "叙事视角"


class _StubRepository:
    def __init__(self, records: list[ResourceRecord] | None = None) -> None:
        self.records = list(records or [])
        self.saved: list[tuple[str, Any]] = []

    def list_resources(self, workspace_id: str) -> list[ResourceRecord]:
        del workspace_id
        return list(self.records)

    def save_plan(self, workspace_id: str, plan: Any) -> None:
        self.saved.append((workspace_id, plan))


class _StubResourceService:
    def __init__(self, fragments: list[dict[str, Any]] | None = None) -> None:
        self.fragments = list(fragments or [])

    def build_requested_resource_context(
        self,
        workspace_id: str,
        resource_ids: list[str],
        *,
        max_items: int = 1,
        summary_chars: int = 220,
    ) -> dict[str, Any]:
        del workspace_id, max_items, summary_chars
        wanted = {str(rid) for rid in resource_ids}
        return {
            "resource_fragments": [
                fragment
                for fragment in self.fragments
                if str(fragment.get("resource_id") or "") in wanted
            ]
        }


def _runtime(
    records: list[ResourceRecord] | None = None,
    fragments: list[dict[str, Any]] | None = None,
) -> tuple[SimpleNamespace, _StubRepository]:
    repository = _StubRepository(records)
    runtime = SimpleNamespace(
        repository=repository,
        resource_service=_StubResourceService(fragments),
    )
    return runtime, repository


def _record(**overrides: Any) -> ResourceRecord:
    payload: dict[str, Any] = {
        "id": "res-1",
        "kind": "pdf",
        "name": "呐喊.pdf",
        "source": "library/nahan.pdf",
        "content_hash": "hash-nahan",
        "index_status": "indexed",
        "trust_score": 0.9,
        "freshness": "fresh",
    }
    payload.update(overrides)
    return ResourceRecord(**payload)


def _fragment(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "frag-1",
        "resource_id": "res-1",
        "source_type": "pdf",
        "focus_area": _FRAGMENT_FOCUS,
        "evidence_summary": "第一人称受限视角把叙述者排除在他人内心之外。",
    }
    payload.update(overrides)
    return payload


def _manifest(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "_type": COURSE_MANIFEST_TYPE,
        "version": COURSE_MANIFEST_VERSION,
        "title": "现代文学精读",
        "subject_family": "literature",
        "summary": "三阶段精读计划",
        "stages": [
            {"id": "s1", "title": "精读《呐喊》", "goal": "方法", "outcomes": [], "resources": ["呐喊.pdf"]},
            {"id": "s2", "title": "仿写", "goal": "迁移", "outcomes": []},
        ],
        "resources": [
            {"name": "呐喊.pdf", "kind": "pdf", "source": "library/nahan.pdf", "contentHash": "hash-nahan"}
        ],
        "card_pack": [],
    }
    payload.update(overrides)
    return payload


def _fork(payload: dict[str, Any], runtime: Any, **kwargs: Any):
    return fork_course_manifest(
        inspect_course_manifest(payload).manifest,
        runtime=runtime,
        workspace_id="workspace-course",
        **kwargs,
    )


def test_fork_writes_plan_and_resolves_stage_resources() -> None:
    runtime, repository = _runtime([_record()])
    result = _fork(_manifest(), runtime)
    assert repository.saved, "the fork must persist the plan"
    workspace_id, saved_plan = repository.saved[0]
    assert workspace_id == "workspace-course"
    assert [stage.id for stage in saved_plan.stages] == ["s1", "s2"]
    assert saved_plan.stages[0].resources == ["res-1"]
    assert saved_plan.current_stage_id == "s1"
    assert result.unresolved_resource_refs == []


def test_fork_keeps_and_reports_unresolved_refs() -> None:
    runtime, _ = _runtime([])
    result = _fork(_manifest(), runtime)
    assert result.plan.stages[0].resources == ["呐喊.pdf"]
    assert result.unresolved_resource_refs == ["呐喊.pdf"]


def test_fork_defers_first_card_without_any_library_resource() -> None:
    runtime, _ = _runtime([])
    result = _fork(_manifest(), runtime)
    assert result.first_card is None
    assert result.first_card_status == FIRST_CARD_DEFERRED
    assert result.first_card_reason == "the library has no resources yet"


def test_fork_defers_when_referenced_resource_is_not_indexed() -> None:
    runtime, _ = _runtime([_record(index_status="pending")], [_fragment()])
    result = _fork(_manifest(), runtime)
    assert result.first_card is None
    assert result.first_card_reason == "no referenced resource is indexed yet"


def test_fork_defers_when_resource_is_not_trusted() -> None:
    runtime, _ = _runtime([_record(trust_score=0.1)], [_fragment()])
    result = _fork(_manifest(), runtime)
    assert result.first_card is None
    assert result.first_card_reason == "no indexed resource is trusted yet"


def test_fork_defers_when_trusted_resource_has_no_fragment() -> None:
    runtime, _ = _runtime([_record()], [])
    result = _fork(_manifest(), runtime)
    assert result.first_card is None
    assert result.first_card_reason == "trusted indexed resources carry no usable knowledge fragment yet"


def test_fork_generates_first_card_through_the_resource_lane() -> None:
    runtime, _ = _runtime([_record()], [_fragment()])
    result = _fork(_manifest(), runtime)
    assert result.first_card is not None
    assert result.first_card_status == FIRST_CARD_GENERATED
    card = result.first_card
    assert card.card_type == "practice"
    assert card.trust_state == "trusted"
    # Grounded in the indexed evidence, not in manifest prose.
    assert _FRAGMENT_FOCUS in f"{card.focus_area} {card.target_skill} {card.why_now} {card.scenario}"
    assert card.plan_links == [] or card.plan_links == ["s1"]


def test_fork_matches_resource_by_content_hash() -> None:
    runtime, _ = _runtime([_record()], [_fragment()])
    payload = _manifest(
        stages=[{"id": "s1", "title": "精读", "goal": "方法", "resources": ["hash-nahan"]}]
    )
    result = _fork(payload, runtime)
    assert result.plan.stages[0].resources == ["res-1"]
    assert result.first_card_status == FIRST_CARD_GENERATED


# ---------------------------------------------------------------------------
# Restored from test_dependency_mastery_stages.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _make_service(tmp_path: Path) -> tuple[MemoryService, str]:
    repository = TrainerRepository(tmp_path / "dependency-mastery.db")
    service = MemoryService(repository)
    workspace_id = "workspace-dependency-mastery"
    repository.save_profile(
        workspace_id,
        UserProfile(
            long_term_goal="Master dependency APIs through practice",
            weekly_hours=4,
            teaching_style="guided",
            answer_policy="guided",
            preferred_libraries=["FastAPI"],
        ),
    )
    return service, workspace_id


def test_flashcard_success_promotes_dependency_to_recalled(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        scenarios=["Use dependency injection in one route"],
        weakest_points=["Still cannot recall when Depends fits best."],
        evidence=["Initial weakness from practice."],
    )

    deck = service.build_flash_deck(workspace_id)
    dependency_card = next(card for card in deck.cards if card.dependency_key == "fastapi")
    response = service.submit_flashcard_answer(
        workspace_id,
        card_id=dependency_card.card_id,
        learner_answer="Depends injects a dependency into a FastAPI route.",
        selected_option_index=0 if dependency_card.answer_mode == "choice" else None,
    )

    fastapi = next(item for item in response.dependency_mastery if item.dependency_key == "fastapi")
    assert fastapi.mastery_stage == "recalled"
    assert "recalled" in fastapi.mastery_stage_progress


def test_learning_signal_transfer_requires_explicit_cross_project_evidence(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)

    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["FastAPI"],
        outcome="tests_passed",
        summary="Used Depends correctly in the live route and verified the behavior.",
        focus_area="dependency injection",
        scenario="dependency_project",
        verified_result="The route now resolves the injected dependency correctly.",
        verified_by_evaluator=True,
    )
    first = next(item for item in service.snapshot(workspace_id).dependency_mastery if item.dependency_key == "fastapi")
    assert first.mastery_stage == "applied"

    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["FastAPI"],
        outcome="tests_passed",
        summary="Reused the same dependency injection pattern in another project slice.",
        focus_area="dependency injection transfer",
        scenario="cross_project_transfer",
        verified_result="The same pattern held in a second project scenario.",
        verified_by_evaluator=True,
    )
    second = next(item for item in service.snapshot(workspace_id).dependency_mastery if item.dependency_key == "fastapi")
    assert second.mastery_stage == "applied"
    assert second.latest_transfer_blocked_reason

    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["FastAPI"],
        outcome="tests_passed",
        summary="Migrated the same dependency injection judgment into a second workspace.",
        focus_area="dependency injection transfer",
        scenario="cross_project_transfer",
        verified_result="The same dependency boundary passed in a second workspace.",
        transfer_source_workspace_id=workspace_id,
        transfer_target_workspace_id="workspace-fastapi-transfer-target",
        transfer_source_context="Original FastAPI sidecar route",
        transfer_target_context="Second project route boundary",
        transfer_evidence_summary="Cross-project migration verified in a second workspace.",
        verified_by_evaluator=True,
    )
    third = next(item for item in service.snapshot(workspace_id).dependency_mastery if item.dependency_key == "fastapi")
    assert third.mastery_stage == "transferable"
    assert third.latest_transfer_evidence_id
    assert third.mastery_stage_progress == [
        "understood",
        "recalled",
        "practiced",
        "applied",
        "transferable",
    ]

    service.record_learning_outcome(
        workspace_id=workspace_id,
        concepts=["FastAPI"],
        outcome="tests_passed",
        summary="The evaluator confirmed another focused route test passed.",
        focus_area="dependency injection",
        scenario="dependency_project",
        verified_result="The focused route still resolves the dependency correctly.",
        verified_by_evaluator=True,
    )
    preserved = next(
        item for item in service.snapshot(workspace_id).dependency_mastery if item.dependency_key == "fastapi"
    )
    assert preserved.mastery_stage == "transferable"


def test_parameter_flashcard_requires_semantic_answer_and_writes_back_skill_item_key(tmp_path: Path) -> None:
    service, workspace_id = _make_service(tmp_path)
    structured = service.structured_for_workspace(workspace_id)
    structured.upsert_dependency_mastery(
        "fastapi",
        dependency_name="FastAPI",
        apis=["Depends"],
        scenarios=["Use dependency injection in one route"],
        weakest_points=["Still cannot explain the parameter meaning for Depends."],
        evidence=["The learner only repeats the API name."],
        mastery_stage="understood",
        mastery_stage_progress=["understood"],
    )

    deck = service.build_flash_deck(workspace_id)
    parameter_card = next(card for card in deck.cards if card.card_id.startswith("skill-fastapi-parameter-"))

    failed = service.submit_flashcard_answer(
        workspace_id,
        card_id=parameter_card.card_id,
        learner_answer="Depends",
    )
    assert not failed.correct
    assert failed.dependency_skill_map_history
    assert failed.dependency_skill_map_history[0].focus_item_key
    assert failed.dependency_skill_map_history[0].focus_item_key != parameter_card.card_id

    refreshed = service.snapshot(workspace_id)
    assert refreshed.recent_flash_attempts[0].dependency_layer == "parameter"
    assert refreshed.workspace["latest_flashcard_recovery_mode"] == "flashcards"
