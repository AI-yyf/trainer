"""Five capability dimensions advance only from real, qualified evidence.

The ladder is intentionally strict:
* assisted needs a controlled pass with an explicitly assisted level;
* independent needs a controlled pass with explicitly no assistance;
* transfer needs an explicit cross-context fact, not an incidental scenario;
* delayed_recall needs an answered recall after a real retention interval;
* missing/unknown facts never become independent or verified.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, PropertyMock

import pytest

from app.llm.provider_service import ProviderService
from app.training.attempt_store import AttemptStore
from app.training.skill_projection import project_skills
from tests.test_api import build_client

DIMENSIONS = (
    "comprehension",
    "implementation",
    "debugging",
    "transfer",
    "delayed_recall",
)


def _ev(evidence_id: str, *, dimension: str, **overrides: object) -> dict:
    record = {
        "evidence_id": evidence_id,
        "attempt_id": f"attempt-{evidence_id}",
        "result": "passed",
        "trust_level": "controlled_check",
        "assistance_level": "independent",
        "is_current": True,
        "superseded_by_evidence_id": None,
        "dimension": dimension,
    }
    record.update(overrides)
    return record


def test_missing_assistance_never_advances_any_dimension() -> None:
    for dimension in DIMENSIONS:
        record = _ev(
            f"missing-{dimension}",
            dimension=dimension,
            evidence_kind="recall" if dimension == "delayed_recall" else "controlled_evaluation",
            recall_delay_days=2.0 if dimension == "delayed_recall" else None,
            scenario="new context" if dimension == "transfer" else None,
        )
        record.pop("assistance_level")
        projected = project_skills([record])[dimension]
        assert projected["state"] == "not_verified", dimension
        assert projected["independent_attempt_count"] == 0, dimension


@pytest.mark.parametrize("dimension", ["comprehension", "implementation", "debugging"])
def test_assisted_and_independent_stay_distinct(dimension: str) -> None:
    assisted = project_skills([
        _ev(f"assisted-{dimension}", dimension=dimension, assistance_level="hint_level_2")
    ])[dimension]
    independent = project_skills([
        _ev(f"independent-{dimension}", dimension=dimension)
    ])[dimension]

    assert assisted["state"] == "assisted"
    assert assisted["independent_attempt_count"] == 0
    assert independent["state"] == "independent"
    assert independent["independent_attempt_count"] == 1


def test_explicit_implementation_failure_does_not_claim_debugging() -> None:
    failed = _ev(
        "impl-failure",
        dimension="implementation",
        result="failed",
    )
    projected = project_skills([failed])

    assert projected["implementation"]["state"] == "needs_review"
    assert projected["debugging"]["state"] == "not_verified"
    assert projected["debugging"]["verified_count"] == 0


def test_transfer_needs_an_explicit_transfer_fact_not_an_incidental_scenario() -> None:
    implementation_with_scenario = _ev(
        "impl-scenario",
        dimension="implementation",
        scenario="new deployment context",
        environment={"runtime": "container"},
    )
    transfer = _ev(
        "transfer-context",
        dimension="transfer",
        scenario="new deployment context",
        environment={"runtime": "container"},
    )

    not_transfer = project_skills([implementation_with_scenario])
    assert not_transfer["implementation"]["state"] == "independent"
    assert not_transfer["transfer"]["state"] == "not_verified"
    assert not_transfer["transfer"]["evidence_ids"] == []

    assert project_skills([transfer])["transfer"]["state"] == "independent"


def test_transfer_repeat_verification_requires_distinct_contexts() -> None:
    same_context = [
        _ev(
            "transfer-same-1",
            dimension="transfer",
            scenario="same scenario",
            attempt_id="attempt-transfer-1",
        ),
        _ev(
            "transfer-same-2",
            dimension="transfer",
            scenario="same scenario",
            attempt_id="attempt-transfer-2",
        ),
    ]
    distinct_context = [
        _ev(
            "transfer-diff-1",
            dimension="transfer",
            scenario="scenario one",
            attempt_id="attempt-transfer-1",
        ),
        _ev(
            "transfer-diff-2",
            dimension="transfer",
            scenario="scenario two",
            attempt_id="attempt-transfer-2",
        ),
    ]

    assert project_skills(same_context)["transfer"]["state"] == "independent"
    assert project_skills(distinct_context)["transfer"]["state"] == "repeat_verified"


def test_immediate_or_missing_recall_delay_cannot_advance_delayed_recall() -> None:
    immediate = _ev(
        "immediate-recall",
        dimension="delayed_recall",
        evidence_kind="recall",
        recall_delay_days=0.25,
    )
    missing_delay = _ev(
        "missing-delay",
        dimension="delayed_recall",
        evidence_kind="recall",
    )
    wrong_kind = _ev(
        "code-check",
        dimension="delayed_recall",
        evidence_kind="controlled_evaluation",
        recall_delay_days=3.0,
    )

    for record, evidence_id in (
        (immediate, "immediate-recall"),
        (missing_delay, "missing-delay"),
        (wrong_kind, "code-check"),
    ):
        projected = project_skills([record])["delayed_recall"]
        assert projected["state"] == "not_verified", evidence_id
        assert projected["verified_count"] == 0, evidence_id
        assert projected["independent_attempt_count"] == 0, evidence_id
        row = next(item for item in projected["evidence"] if item["evidence_id"] == evidence_id)
        assert row["delayed_recall_qualified"] is False


def test_delayed_recall_ladder_and_failure() -> None:
    first = _ev(
        "recall-1",
        dimension="delayed_recall",
        evidence_kind="recall",
        recall_delay_days=2.0,
        attempt_id="attempt-recall-1",
    )
    second = _ev(
        "recall-2",
        dimension="delayed_recall",
        evidence_kind="recall",
        recall_delay_days=5.0,
        attempt_id="attempt-recall-2",
    )
    same_attempt = _ev(
        "recall-same-attempt",
        dimension="delayed_recall",
        evidence_kind="recall",
        recall_delay_days=5.0,
        attempt_id="attempt-recall-1",
    )
    failed = _ev(
        "recall-failed",
        dimension="delayed_recall",
        evidence_kind="recall",
        recall_delay_days=4.0,
        result="failed",
    )
    assisted = _ev(
        "recall-assisted",
        dimension="delayed_recall",
        evidence_kind="recall",
        recall_delay_days=4.0,
        assistance_level="hint_level_1",
    )

    assert project_skills([first])["delayed_recall"]["state"] == "independent"
    assert project_skills([first, second])["delayed_recall"]["state"] == "repeat_verified"
    assert project_skills([first, same_attempt])["delayed_recall"]["state"] == "independent"
    assert project_skills([failed])["delayed_recall"]["state"] == "needs_review"
    assert project_skills([assisted])["delayed_recall"]["state"] == "assisted"


def test_code_verification_cannot_advance_delayed_recall() -> None:
    code_pass = _ev(
        "code-pass",
        dimension="implementation",
        evidence_kind="controlled_evaluation",
    )
    projected = project_skills([code_pass])

    assert projected["implementation"]["state"] == "independent"
    assert projected["delayed_recall"]["state"] == "not_verified"
    assert projected["delayed_recall"]["verified_count"] == 0


def test_flashcard_recall_advances_only_after_a_real_delay(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-01T09:00:00Z")
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        workspace = "ws-delayed-recall"
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Recall lab"},
        )
        assert started.status_code == 200, started.text
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-recall-1",
            card_type="flash",
            status="active",
            title="Tuple immutability",
            focus_area="tuple immutability",
            answer_mode="single_choice",
            options=["mutable", "immutable"],
            correct_option_index=1,
        )
        runtime.memory_service.upsert_card(workspace, card)

        first = client.post(
            "/training/flashcard/answer",
            json={
                "workspace_id": workspace,
                "card_id": card.card_id,
                "selected_option_index": 1,
            },
        )
        assert first.status_code == 200, first.text
        first_evidence = first.json()["recall_evidence"]
        assert first_evidence is not None
        assert first_evidence["delayed_recall"] is False
        dimensions = (
            runtime.memory_service.snapshot(workspace).workspace or {}
        ).get("training_skill_projection", {}).get("dimensions", {})
        assert dimensions["delayed_recall"]["state"] == "not_verified"
        assert dimensions["comprehension"]["state"] == "not_verified"

        monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-03T09:00:00Z")
        second = client.post(
            "/training/flashcard/answer",
            json={
                "workspace_id": workspace,
                "card_id": card.card_id,
                "selected_option_index": 1,
            },
        )
        assert second.status_code == 200, second.text
        second_evidence = second.json()["recall_evidence"]
        assert second_evidence is not None
        assert second_evidence["delayed_recall"] is True
        assert second_evidence["delay_days"] >= 1.0
        dimensions = (
            runtime.memory_service.snapshot(workspace).workspace or {}
        ).get("training_skill_projection", {}).get("dimensions", {})
        assert dimensions["delayed_recall"]["state"] == "independent"


@pytest.mark.parametrize(
    ("provider_reply", "expected_correct", "rating"),
    [
        ('{"verdict":"correct","reason":"Distinguishes slots from values",'
         '"quote":"slots stay bound"}', True, "hard"),
        ('{"verdict":"incorrect","reason":"Confuses slots and values",'
         '"quote":"slots stay bound"}', False, "again"),
        ('{"verdict":"uncertain","reason":"Cannot determine the case",'
         '"quote":"slots stay bound"}', None, None),
        ('{"verdict":"correct","reason":"Distinguishes slots from values",'
         '"quote":"fabricated excerpt"}', None, None),
        (RuntimeError("provider unavailable"), None, None),
    ],
)
def test_model_review_preserves_assessment_scope_and_schedule(
    tmp_path, monkeypatch: pytest.MonkeyPatch, provider_reply, expected_correct, rating,
) -> None:
    from app.core.models import TrainingCardCandidateSnapshot
    from app.llm.training_review_context import apply_training_review_context

    monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-01T09:00:00Z")
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        workspace = "ws-open-recall"
        started = client.post(
            "/session/start", json={"workspace_id": workspace, "workspace_name": "Recall lab"},
        )
        assert started.status_code == 200, started.text
        card = TrainingCardCandidateSnapshot(
            card_id="open-recall",
            card_type="flash",
            status="active",
            title="Tuple contents",
            focus_area="tuples",
            question="What is fixed when a tuple contains a mutable list?",
            expected_answer="Tuple references are immutable while the list can change.",
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(workspace, selected_card_id=card.card_id)
        runtime.memory_service.initialize_training_card_review(workspace, training_card_id=card.card_id)
        before = runtime.memory_service.snapshot(workspace).workspace["latest_training_fsrs_states"][card.card_id]
        monkeypatch.setenv("TRAINER_TEST_NOW", "2026-11-03T09:00:00Z")
        monkeypatch.setattr(ProviderService, "has_api_key", PropertyMock(return_value=True))
        completion = (
            AsyncMock(side_effect=provider_reply) if isinstance(provider_reply, Exception)
            else AsyncMock(return_value=provider_reply)
        )
        monkeypatch.setattr(ProviderService, "chat_completion", completion)
        original = "The slots stay bound, but the list itself remains editable."
        response = client.post(
            "/training/flashcard/answer",
            json={"workspace_id": workspace, "card_id": card.card_id, "learner_answer": original},
        )
        assert response.status_code == 200, response.text
        completion.assert_awaited_once()
        result = response.json()
        snapshot = runtime.memory_service.snapshot(workspace)
        after = snapshot.workspace["latest_training_fsrs_states"][card.card_id]
        assert result["correct"] is expected_correct
        assert result["attempt"]["learner_answer"] == original
        assert snapshot.recent_flash_attempts[0].learner_answer == original
        followup = apply_training_review_context(
            {"learner_message": "What did my last recall show?"}, snapshot, "coach",
        )["recent_recall_result"]
        assert followup["correct"] is expected_correct
        if rating is None:
            assert result["recall_evidence"] is None
            assert result["retry_required"] is False
            assert result["card_status"] == "active"
            assert after == before
            assert runtime.attempt_store.list_workspace_evidence(workspace) == []
            recorded = runtime.attempt_store.list_attempts(workspace_id=workspace, card_id=card.card_id)
            assert any(item["answer_draft"] == original for item in recorded)
        else:
            receipt = result["recall_evidence"]
            assert receipt["trust_level"] == "model_review"
            assert receipt["rating"] == rating
            assert receipt["delayed_recall"]
            assert after["reps"] == before["reps"] + 1
            evidence = runtime.attempt_store.list_workspace_evidence(workspace)[0]
            assert evidence["environment"]["answer_quote"] == "slots stay bound"
            attempt = runtime.attempt_store.get_attempt_payload(evidence["attempt_id"])
            assert attempt and attempt["answer_draft"] == original
            dims = snapshot.workspace["training_skill_projection"]["dimensions"]
            assert dims["delayed_recall"]["state"] == "not_verified"
            assert dims["delayed_recall"]["independent_attempt_count"] == 0


def test_review_queue_done_without_an_answer_does_not_grade_fsrs(tmp_path) -> None:
    from app.memory.models import MasteryRecord, WeaknessRecord

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        workspace = "ws-review-done"
        structured = runtime.memory_service.structured_for_workspace(workspace)
        past = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
        structured._mastery["tuple slot"] = MasteryRecord(
            concept="tuple slot",
            score=0.6,
            confidence=0.7,
            review_source="fsrs",
            fsrs_stability=7.5,
            fsrs_difficulty=4.2,
            fsrs_reps=3,
            next_review_at=past,
            due_date=past,
        )
        structured._weaknesses["tuple slot"] = WeaknessRecord(
            concept="tuple slot",
            reason="Explain the assignment boundary.",
            severity=3,
            next_review_at=past,
        )
        runtime.memory_service._persist_structured(workspace)

        response = client.post(
            "/training/review-queue/action",
            json={"workspace_id": workspace, "concept": "tuple slot", "action": "done"},
        )
        assert response.status_code == 200, response.text

        refreshed = runtime.memory_service.structured_for_workspace(workspace)
        mastery = refreshed._mastery["tuple slot"]
        assert mastery.fsrs_stability == 7.5
        assert mastery.fsrs_difficulty == 4.2
        assert mastery.fsrs_reps == 3
        assert mastery.review_source == "fsrs"
        assert mastery.next_review_at is not None
        assert mastery.next_review_at == past


def test_return_card_controlled_pass_counts_as_transfer(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from app.core.models import (
        EvaluationCheck,
        EvaluationReport,
        TrainingCardCandidateSnapshot,
    )

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        workspace = "ws-return-transfer"
        session = client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Transfer lab"},
        ).json()["session_id"]
        path = str(tmp_path / "transfer.py")
        card = TrainingCardCandidateSnapshot(
            card_id="card-return-transfer",
            card_type="practice",
            status="active",
            learning_phase="return",
            title="Apply the lock pattern in the project",
            focus_area="lock pattern migration",
            scenario="new project context",
            files_to_touch=[path],
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(workspace, selected_card_id=card.card_id)
        attempt = runtime.attempt_store.start_attempt(
            workspace_id=workspace,
            card_id=card.card_id,
            file_path=path,
            assistance_level="none",
        )
        runtime.evaluator_service.evaluate_current_file = MagicMock(
            return_value=EvaluationReport(
                passed=True,
                verification_scope="behavior",
                summary="1 test passed",
                next_step="Reflect",
                reflection="",
                dynamic_checks=[
                    EvaluationCheck(
                        id="python-behavior",
                        label="python-behavior",
                        status="passed",
                        detail="1 passed",
                    )
                ],
            )
        )
        response = client.post(
            "/evaluate/current-file",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "evaluation_source": "training",
                "training_card_id": card.card_id,
                "training_phase": "verify",
                "file_path": path,
                "content": "def test_boundary():\n    assert True\n",
                "language_id": "python",
            },
        )
        assert response.status_code == 200, response.text
        evidence = runtime.attempt_store.list_evidence(attempt["attempt_id"])
        current = [item for item in evidence if item.get("is_current")]
        assert current and current[0]["dimension"] == "transfer"
        assert current[0]["transfer_metadata"] == {"source": "training_return"}
        dimensions = (
            runtime.memory_service.snapshot(workspace).workspace or {}
        ).get("training_skill_projection", {}).get("dimensions", {})
        assert dimensions["transfer"]["state"] == "independent"
        assert dimensions["implementation"]["state"] == "not_verified"


def test_unified_evidence_preserves_evidence_kind_and_delay() -> None:
    from app.evidence.contract import evidence_from_attempt

    item = evidence_from_attempt(
        {
            "evidence_id": "recall-unified",
            "attempt_id": "attempt-recall-unified",
            "workspace_id": "ws",
            "card_id": "card",
            "result": "passed",
            "trust_level": "controlled_check",
            "assistance_level": "none",
            "dimension": "delayed_recall",
            "evidence_kind": "recall",
            "recall_delay_days": 2.5,
            "recall_rating": "good",
            "artifact_hash": "hash",
            "created_at": "2026-11-04T09:00:00+00:00",
        },
        workspace_id="ws",
    )

    assert item.dimension == "delayed_recall"
    assert item.evidence_kind == "recall"
    assert item.recall_delay_days == 2.5
    assert item.recall_rating == "good"
    assert item.assistance_level == "none"


def test_theory_drill_answer_records_comprehension_not_delayed_recall(tmp_path) -> None:
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        workspace = "ws-theory-comprehension"
        structured = runtime.memory_service.structured_for_workspace(workspace)
        structured.upsert_dependency_mastery(
            "fastapi",
            dependency_name="FastAPI",
            apis=["Depends"],
            scenarios=["Inject a dependency into one route"],
            weakest_points=["Cannot yet explain the route boundary."],
            evidence=["Initial theory check."],
        )
        theory_drill = runtime.memory_service.snapshot(workspace).theory_drill
        assert theory_drill is not None
        question = theory_drill.questions[0]

        response = client.post(
            "/training/theory-drill/answer",
            json={
                "workspace_id": workspace,
                "theory_drill_id": theory_drill.id,
                "question_id": question.id,
                "learner_answer": question.answer,
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["correct"] is True
        assert payload["recall_evidence"]["dimension"] == "comprehension"
        assert payload["recall_evidence"]["delayed_recall"] is False
        dimensions = (
            runtime.memory_service.snapshot(workspace).workspace or {}
        ).get("training_skill_projection", {}).get("dimensions", {})
        assert dimensions["comprehension"]["state"] == "not_verified"
        assert dimensions["delayed_recall"]["state"] == "not_verified"


def test_attempt_store_keeps_unrecorded_assistance_unknown(tmp_path) -> None:
    store = AttemptStore(tmp_path / "attempts.db")
    attempt = store.start_attempt(workspace_id="ws", card_id="card")
    assert attempt["assistance_level"] == "unknown"

    evidence = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash",
        result="passed",
    )
    assert evidence is not None
    assert evidence["assistance_level"] == "unknown"
    projected = project_skills([evidence])["implementation"]
    assert projected["state"] == "not_verified"
