"""P1.4 candidate management: merge / mark important / adjust priority.

The learner decides which candidates are worth keeping. All three operations
ride the existing card records, the structured ledger and the unified event
ledger — the tests pin the endpoints, the merge semantics (archived in place
with ``merged_into``), the validations, and the routing-score tilt.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.models import TrainingCardCandidateSnapshot
from app.core.settings import AppSettings
from app.main import create_app


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer candidate management",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="candidate-management.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _candidate(card_id: str, title: str, **overrides: object) -> TrainingCardCandidateSnapshot:
    fields: dict[str, object] = {
        "card_id": card_id,
        "title": title,
        "card_type": "practice",
        "status": "candidate",
        "focus_area": "PPO 裁剪目标",
        "target_skill": "实现并解释 PPO 裁剪目标",
    }
    fields.update(overrides)
    return TrainingCardCandidateSnapshot.model_validate(fields)


@pytest.fixture()
def management_client(tmp_path: Path) -> tuple[TestClient, object]:
    app = create_app(_settings(tmp_path / "data"))
    with TestClient(app) as client:
        service = app.state.runtime.memory_service
        service.upsert_card("ws-mgmt", _candidate("card-keeper", "实现 PPO 裁剪目标"))
        service.upsert_card(
            "ws-mgmt",
            _candidate(
                "card-dup",
                "实现 PPO 裁剪目标（重复）",
                acceptance_criteria=["能独立写出裁剪损失函数"],
                common_mistakes=["把整条 reward 一起裁剪了"],
                hint_ladder=["先写比率项"],
                source_chain=["card_generation_router", "goal_teaching"],
                plan_links=["plan-world-models:stage-2"],
            ),
        )
        service.upsert_card(
            "ws-mgmt",
            _candidate("card-active", "已经开跑的卡", status="active"),
        )
        yield client, service


def test_mark_important_and_adjust_priority_endpoints(management_client) -> None:
    client, service = management_client

    marked = client.post(
        "/training/card/importance",
        json={"workspace_id": "ws-mgmt", "card_id": "card-keeper", "important": True},
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["card"]["important"] is True
    assert service.get_card("ws-mgmt", "card-keeper").important is True

    priority = client.post(
        "/training/card/priority",
        json={"workspace_id": "ws-mgmt", "card_id": "card-keeper", "priority": 9},
    )
    assert priority.status_code == 200, priority.text
    # The learner's priority is clamped to the bounded management range.
    assert priority.json()["card"]["cardPriority"] == 5  # camelCase alias on the wire
    assert service.get_card("ws-mgmt", "card-keeper").card_priority == 5

    unmarked = client.post(
        "/training/card/importance",
        json={"workspace_id": "ws-mgmt", "card_id": "card-keeper", "important": False},
    )
    assert unmarked.status_code == 200
    assert unmarked.json()["card"]["important"] is False

    missing = client.post(
        "/training/card/importance",
        json={"workspace_id": "ws-mgmt", "card_id": "card-nope", "important": True},
    )
    assert missing.status_code == 404

    # The management step rides the same card ledger as every other mutation.
    ledger_kinds = {
        entry.get("event_type")
        for entry in service._structured_for("ws-mgmt")._training_event_ledger
    }
    assert "training_card_importance_changed" in ledger_kinds


def test_merge_archives_duplicates_into_the_keeper(management_client) -> None:
    client, service = management_client

    merged = client.post(
        "/training/cards/merge",
        json={
            "workspace_id": "ws-mgmt",
            "keepCardId": "card-keeper",
            "duplicateCardIds": ["card-dup"],
        },
    )
    assert merged.status_code == 200, merged.text

    keeper = service.get_card("ws-mgmt", "card-keeper")
    # The keeper absorbs the duplicates' still-missing authored facts.
    assert "能独立写出裁剪损失函数" in keeper.acceptance_criteria
    assert "把整条 reward 一起裁剪了" in keeper.common_mistakes
    assert "先写比率项" in keeper.hint_ladder
    assert "goal_teaching" in keeper.source_chain
    assert "plan-world-models:stage-2" in keeper.plan_links

    duplicate = service.get_card("ws-mgmt", "card-dup")
    assert duplicate.status == "archived"
    assert duplicate.merged_into == "card-keeper"

    # The management step rides the same card ledger as every other mutation.
    ledger_kinds = {
        entry.get("event_type")
        for entry in service._structured_for("ws-mgmt")._training_event_ledger
    }
    assert "training_cards_merged" in ledger_kinds


def test_merge_validations_fail_closed(management_client) -> None:
    client, service = management_client

    # Only still-candidate duplicates merge; an in-flight card keeps its history.
    active = client.post(
        "/training/cards/merge",
        json={
            "workspace_id": "ws-mgmt",
            "keepCardId": "card-keeper",
            "duplicateCardIds": ["card-active"],
        },
    )
    assert active.status_code == 422
    assert service.get_card("ws-mgmt", "card-active").status == "active"

    # A merge needs at least one other card, and the keeper's id does not count.
    empty = client.post(
        "/training/cards/merge",
        json={
            "workspace_id": "ws-mgmt",
            "keepCardId": "card-keeper",
            "duplicateCardIds": [],
        },
    )
    assert empty.status_code == 422

    self_only = client.post(
        "/training/cards/merge",
        json={
            "workspace_id": "ws-mgmt",
            "keepCardId": "card-keeper",
            "duplicateCardIds": ["card-keeper"],
        },
    )
    assert self_only.status_code == 422

    missing = client.post(
        "/training/cards/merge",
        json={
            "workspace_id": "ws-mgmt",
            "keepCardId": "card-nope",
            "duplicateCardIds": ["card-dup"],
        },
    )
    assert missing.status_code == 404


def test_priority_and_importance_tilt_the_router_score() -> None:
    from app.training.card_generator import CardGenerationService

    service = object.__new__(CardGenerationService)
    base_card = _candidate("card-score", "计分基准卡")
    base = service._score_card(base_card, {})
    boosted = service._score_card(
        base_card.model_copy(update={"card_priority": 2, "important": True}),
        {},
    )
    assert boosted > base
    # The tilt is bounded: an extreme priority cannot exceed the score ceiling.
    extreme = service._score_card(
        base_card.model_copy(update={"card_priority": 5, "important": True}),
        {},
    )
    assert extreme <= 1.0
