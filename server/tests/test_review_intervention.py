"""Review intervention budget and recall grading.

Failure-first coverage:
* a refusal/busy signal suppresses proactive review and persists a cooldown;
* one offer per session and a cross-session cooldown prevent repeated nudges;
* a focused/blocked thread is not interrupted;
* a long absence shows one highest-value item, not the backlog;
* recall answers map to explicit again/hard/good grades; no answer grades nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.models import LearningPlan
from app.memory.review_intervention import (
    derive_review_budget,
    review_refusal_signal,
)
from app.memory.review_scheduler import ReviewScheduler
from app.pedagogy.turn_decision import TurnFacts, decide_turn
from app.training.recall_evidence import recall_rating_for
from tests.test_api import build_client

NOW = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def test_no_due_reviews_never_interrupts() -> None:
    budget = derive_review_budget({}, due_count=0, now=NOW)
    assert budget.allowed is False
    assert budget.reason == "no_due_reviews"
    assert budget.visible_limit == 0


def test_refusal_persists_and_suppresses_interruption() -> None:
    budget = derive_review_budget(
        {
            "review_intervention": {
                "refused_until": _iso(NOW + timedelta(hours=2)),
            }
        },
        due_count=20,
        now=NOW,
    )
    assert budget.allowed is False
    assert budget.reason == "refused"
    assert budget.visible_limit == 1
    assert budget.deferred_count == 19
    assert budget.refused_until == _iso(NOW + timedelta(hours=2))


@pytest.mark.parametrize(
    "message",
    [
        "我现在很忙，晚点再说",
        "not now, I'm busy",
        "正在调试这个错误，先别提醒我",
        "skip the review for today",
        "I'm debugging this error, not now",
    ],
)
def test_busy_or_refusal_message_blocks_this_turn(message: str) -> None:
    budget = derive_review_budget({}, due_count=8, now=NOW, message=message)
    assert budget.message_refusal
    assert budget.allowed is False
    assert budget.visible_limit == 1


def test_normal_question_is_not_mistaken_for_refusal() -> None:
    assert review_refusal_signal("Can you explain how the queue lock works?") == ""
    assert review_refusal_signal("帮我解释一下这个边界条件") == ""
    budget = derive_review_budget({}, due_count=8, now=NOW, message="explain the lock")
    assert budget.allowed is True
    assert budget.visible_limit == 4


def test_one_offer_per_session_and_cross_session_cooldown() -> None:
    same_session = derive_review_budget(
        {
            "review_intervention": {
                "last_offer_at": _iso(NOW - timedelta(hours=5)),
                "last_offer_session_id": "session-a",
            }
        },
        due_count=8,
        now=NOW,
        session_id="session-a",
    )
    assert same_session.allowed is False
    assert same_session.reason == "same_session_interruption"

    recent_other_session = derive_review_budget(
        {
            "review_intervention": {
                "last_offer_at": _iso(NOW - timedelta(hours=1)),
                "last_offer_session_id": "session-a",
            }
        },
        due_count=8,
        now=NOW,
        session_id="session-b",
    )
    assert recent_other_session.allowed is False
    assert recent_other_session.reason == "offer_cooldown"

    later_session = derive_review_budget(
        {
            "review_intervention": {
                "last_offer_at": _iso(NOW - timedelta(hours=5)),
                "last_offer_session_id": "session-a",
            }
        },
        due_count=8,
        now=NOW,
        session_id="session-b",
    )
    assert later_session.allowed is True
    assert later_session.reason == "due_reviews"


def test_focused_or_blocked_thread_is_not_interrupted() -> None:
    budget = derive_review_budget(
        {
            "active_thread": {
                "focus_area": "debugging the lock path",
                "blocker": "test still fails",
            }
        },
        due_count=8,
        now=NOW,
    )
    assert budget.allowed is False
    assert budget.reason == "focused_activity"
    assert budget.visible_limit == 4


def test_long_offline_shows_one_curated_item_not_the_backlog() -> None:
    budget = derive_review_budget(
        {"last_active_at": _iso(NOW - timedelta(days=21))},
        due_count=30,
        now=NOW,
    )
    assert budget.allowed is True
    assert budget.reason == "long_offline_curated"
    assert budget.visible_limit == 1
    assert budget.deferred_count == 29
    assert budget.offline_days >= 21


def test_turn_decision_honors_the_budget_but_not_explicit_review() -> None:
    blocked = decide_turn(
        TurnFacts(
            message="Where should I go next?",
            needs_review=True,
            due_review_count=8,
            intervention_allowed=False,
            intervention_reason="refused",
            has_active_goal=True,
        )
    )
    assert blocked.mode != "review"
    assert "intervention_blocked:refused" in blocked.evidence

    explicit = decide_turn(
        TurnFacts(
            message="Review me now, please.",
            needs_review=True,
            due_review_count=8,
            intervention_allowed=False,
            intervention_reason="refused",
        )
    )
    assert explicit.mode == "review"
    assert explicit.source == "explicit_user"


def test_pedagogy_decision_carries_budget_block_reason() -> None:
    from app.core.models import LearnerState, MemorySnapshot, TurnRequest, UserProfile
    from app.pedagogy.service import PedagogyService

    service = PedagogyService()
    decision = service.decide_teaching(
        request=TurnRequest(message="What should I do next?", intent="coach"),
        learner_state=LearnerState(needs_review=True),
        profile=UserProfile(long_term_goal="Learn distributed systems"),
        memory_snapshot=MemorySnapshot(due_review_count=6),
        intervention_allowed=False,
        intervention_reason="refused",
    )

    assert decision.turn_mode != "review"
    assert "intervention_blocked:refused" in decision.evidence


def test_scheduler_caps_due_items_for_long_absence_and_refusal() -> None:
    from app.memory.models import MemorySnapshot as LaneMemorySnapshot
    from app.memory.models import WeaknessRecord

    scheduler = ReviewScheduler()
    weaknesses = [
        WeaknessRecord(
            concept=f"concept-{index}",
            reason="Needs one closed-book recall.",
            severity=3,
            next_review_at=NOW - timedelta(days=1),
        )
        for index in range(10)
    ]
    long_offline = LaneMemorySnapshot(
        workspace={"last_active_at": _iso(NOW - timedelta(days=14))}
    )
    normal = LaneMemorySnapshot(workspace={"last_active_at": _iso(NOW)})
    refused = LaneMemorySnapshot(
        workspace={
            "last_active_at": _iso(NOW),
            "review_intervention": {"refused_until": _iso(NOW + timedelta(hours=3))},
        }
    )

    # The scheduler reads the real clock; keep seeded due dates in its past.
    real_now = datetime.now(UTC)
    for item in weaknesses:
        item.next_review_at = real_now - timedelta(days=1)
    long_offline.workspace["last_active_at"] = (real_now - timedelta(days=14)).isoformat()
    normal.workspace["last_active_at"] = real_now.isoformat()
    refused.workspace["review_intervention"] = {
        "refused_until": (real_now + timedelta(hours=3)).isoformat()
    }

    long_items = scheduler.derive_due_reviews(
        plan=LearningPlan(id="plan", title="Plan", summary="", stages=[]),
        lane_snapshot=long_offline,
        weakness_records=weaknesses,
    )
    normal_items = scheduler.derive_due_reviews(
        plan=LearningPlan(id="plan", title="Plan", summary="", stages=[]),
        lane_snapshot=normal,
        weakness_records=weaknesses,
    )
    refused_items = scheduler.derive_due_reviews(
        plan=LearningPlan(id="plan", title="Plan", summary="", stages=[]),
        lane_snapshot=refused,
        weakness_records=weaknesses,
    )

    assert len(long_items) == 1
    assert len(normal_items) == 4
    assert len(refused_items) == 1


def test_memory_service_persists_offer_refusal_and_engagement(tmp_path) -> None:
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        workspace = "ws-intervention"
        memory = runtime.memory_service

        memory.record_review_offer(workspace, session_id="session-a", now=NOW)
        same = memory.review_intervention_budget(
            workspace,
            due_count=5,
            session_id="session-a",
            now=NOW + timedelta(hours=1),
        )
        assert same.allowed is False
        assert same.reason == "same_session_interruption"

        memory.record_review_refusal(workspace, reason="busy", session_id="session-a", now=NOW)
        refused = memory.review_intervention_budget(
            workspace,
            due_count=5,
            session_id="session-b",
            now=NOW + timedelta(hours=1),
        )
        assert refused.allowed is False
        assert refused.reason == "refused"

        memory.record_review_engagement(workspace, session_id="session-b", now=NOW)
        engaged = memory.review_intervention_budget(
            workspace,
            due_count=5,
            session_id="session-b",
            now=NOW + timedelta(hours=1),
        )
        assert engaged.refused_until is None
        assert engaged.reason == "offer_cooldown"
        after_cooldown = memory.review_intervention_budget(
            workspace,
            due_count=5,
            session_id="session-b",
            now=NOW + timedelta(hours=5),
        )
        assert after_cooldown.allowed is True
        assert after_cooldown.reason == "due_reviews"


def test_review_queue_skip_records_refusal_and_accept_clears_it(tmp_path) -> None:
    from app.memory.models import WeaknessRecord

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        workspace = "ws-queue-intervention"
        structured = runtime.memory_service.structured_for_workspace(workspace)
        structured._weaknesses["tuple slot"] = WeaknessRecord(
            concept="tuple slot",
            reason="Explain the assignment boundary.",
            severity=3,
            next_review_at=datetime.now(UTC) - timedelta(days=1),
        )
        runtime.memory_service._persist_structured(workspace)

        skipped = client.post(
            "/training/review-queue/action",
            json={"workspace_id": workspace, "concept": "tuple slot", "action": "skip"},
        )
        assert skipped.status_code == 200, skipped.text
        state = runtime.memory_service.structured_for_workspace(workspace)._workspace.get(
            "review_intervention"
        )
        assert state and state.get("refused_until")

        accepted = client.post(
            "/training/review-queue/action",
            json={"workspace_id": workspace, "concept": "tuple slot", "action": "accept"},
        )
        assert accepted.status_code == 200, accepted.text
        state = runtime.memory_service.structured_for_workspace(workspace)._workspace.get(
            "review_intervention"
        )
        assert state and not state.get("refused_until")


def test_recall_rating_maps_evidence_never_missing_assistance_to_independent() -> None:
    assert recall_rating_for(True, "none") == "good"
    assert recall_rating_for(True, "independent") == "good"
    assert recall_rating_for(True, "hint_level_2") == "hard"
    assert recall_rating_for(True, "unknown") == "hard"
    assert recall_rating_for(True, "") == "hard"
    assert recall_rating_for(False, "none") == "again"


def test_flashcard_recall_records_an_explicit_fsrs_grade(tmp_path) -> None:
    from app.core.models import TrainingCardCandidateSnapshot

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        workspace = "ws-recall-grade"
        client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Recall grading"},
        )
        card = TrainingCardCandidateSnapshot(
            card_id="card-grade",
            card_type="flash",
            status="active",
            title="Tuple immutability",
            focus_area="tuple immutability",
            answer_mode="single_choice",
            options=["mutable", "immutable"],
            correct_option_index=1,
        )
        runtime.memory_service.upsert_card(workspace, card)

        response = client.post(
            "/training/flashcard/answer",
            json={
                "workspace_id": workspace,
                "card_id": card.card_id,
                "selected_option_index": 1,
            },
        )
        assert response.status_code == 200, response.text
        recall = response.json()["recall_evidence"]
        assert recall["rating"] == "good"
        evidence = runtime.attempt_store.list_evidence(
            runtime.attempt_store.list_attempts(workspace_id=workspace, card_id=card.card_id)[-1][
                "attempt_id"
            ]
        )
        assert evidence[-1]["recall_rating"] == "good"
