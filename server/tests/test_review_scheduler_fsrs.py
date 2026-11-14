from __future__ import annotations

from datetime import timedelta

from app.core.models import ReviewQueueAction
from app.memory.models import MasteryRecord, MemorySnapshot, utc_now
from app.memory.review_queue import visible_review_queue_items
from app.memory.review_scheduler import ReviewRating, ReviewScheduler
from app.training.fsrs_scheduler import TrainingCardState, card_state_to_payload


def test_review_scheduler_processes_fsrs_state_with_human_readable_state() -> None:
    scheduler = ReviewScheduler()
    mastery = MasteryRecord(
        concept="startup wiring",
        score=0.3,
        confidence=0.7,
        updated_at=utc_now() - timedelta(days=2),
        next_review_at=utc_now() - timedelta(hours=12),
        due_date=utc_now() - timedelta(hours=12),
    )

    updated = scheduler.process_mastery_review(mastery, ReviewRating.GOOD)

    assert updated.state in {"learning", "review", "relearning"}
    assert updated.next_review_at is not None
    assert updated.retrievability >= 0.0
    assert updated.review_source == "fsrs"
    assert updated.fsrs_reps >= 1


def test_fsrs_rating_changes_the_interval_not_a_fixed_table() -> None:
    scheduler = ReviewScheduler()
    mastery = MasteryRecord(
        concept="retry budget",
        score=0.3,
        confidence=0.6,
        updated_at=utc_now() - timedelta(days=1),
        next_review_at=utc_now() - timedelta(days=1),
        due_date=utc_now() - timedelta(days=1),
    )

    again = scheduler.process_mastery_review(mastery, ReviewRating.AGAIN)
    good = scheduler.process_mastery_review(mastery, ReviewRating.GOOD)

    assert again.review_source == good.review_source == "fsrs"
    assert again.next_review_at is not None and good.next_review_at is not None
    assert again.next_review_at < good.next_review_at


def test_persisted_card_schedules_are_visible_without_mastery_and_snooze_by_id() -> None:
    now = utc_now()
    due = now - timedelta(minutes=2)
    states = {
        card_id: card_state_to_payload(TrainingCardState(
            card_id=card_id, concept_id="Same title", next_due_at=due, reps=1,
        ))
        for card_id in ("card-one", "card-two")
    }
    snapshot = MemorySnapshot(workspace={"latest_training_fsrs_states": states})
    queue = ReviewScheduler().derive_due_reviews(
        plan=None, lane_snapshot=snapshot, weakness_records=[],
    )
    assert {item.training_card_id for item in queue} == set(states)
    assert all(item.due_at == due.isoformat() for item in queue)
    action = ReviewQueueAction(
        concept="Old title", training_card_id="card-one", action="snooze", outcome="deferred",
        created_at=now.isoformat(), next_review_at=(now + timedelta(days=1)).isoformat(),
    )
    visible = visible_review_queue_items(queue, [action], {}, now=now)
    assert [item.training_card_id for item in visible] == ["card-two"]
    assert states["card-one"]["next_due_at"] == due.isoformat()


def test_due_cards_survive_restart_and_snooze_updates_only_queue(tmp_path) -> None:
    from app.core.models import TrainingCardCandidateSnapshot
    from tests.test_api import build_client

    workspace = "fsrs-review-restart"
    now = utc_now()
    due = now - timedelta(days=2)
    states = {
        card_id: card_state_to_payload(TrainingCardState(
            card_id=card_id, concept_id="Same concept", next_due_at=due, reps=1,
        ))
        for card_id in ("card-one", "card-two")
    }
    with build_client(tmp_path) as client:
        service = client.app.state.runtime.memory_service
        for card_id in states:
            service.upsert_card(workspace, TrainingCardCandidateSnapshot(
                card_id=card_id, card_type="flash", status="active", title="Same concept",
                question="Which end of a queue is removed first?", expected_answer="The front.",
            ))
        service.update_workspace_state(workspace, latest_training_fsrs_states=states)

    with build_client(tmp_path) as client:
        memory = client.get("/memory/summary", params={"workspace_id": workspace})
        reviews = memory.json()["memory"]["due_reviews"]
        assert {item["training_card_id"] for item in reviews} == set(states)
        response = client.post("/training/review-queue/action", json={
            "workspace_id": workspace, "concept": "Same concept",
            "training_card_id": "card-one", "action": "snooze",
        })
        assert response.status_code == 200, response.text
        assert response.json()["actions"][0]["next_review_at"] != due.isoformat()

    with build_client(tmp_path) as client:
        memory = client.get("/memory/summary", params={"workspace_id": workspace}).json()["memory"]
        assert [item["training_card_id"] for item in memory["due_reviews"]] == ["card-two"]
        assert memory["workspace"]["latest_training_fsrs_states"] == states
