from __future__ import annotations

from types import SimpleNamespace

from app.memory.training_handoff_return_mixin import TrainingHandoffReturnMixin


def _credit(status: str):
    transitions: list[str] = []

    def transition(_workspace_id, _card_id, new_status, **_kwargs):
        transitions.append(new_status)
        return SimpleNamespace(card=SimpleNamespace(status=new_status, card_id="card-1"))

    owner = SimpleNamespace(transition_card_status=transition)
    result = TrainingHandoffReturnMixin._credit_returned_training_card(
        owner,
        "workspace-1",
        SimpleNamespace(status=status, card_id="card-1"),
    )
    return result, transitions


def test_answered_card_is_credited_on_return() -> None:
    result, transitions = _credit("answered")
    assert result.status == "implemented"
    assert transitions == ["implemented"]


def test_active_card_is_credited_on_return() -> None:
    result, transitions = _credit("active")
    assert result.status == "implemented"
    assert transitions == ["implemented"]


def test_implemented_card_is_not_transitioned_again() -> None:
    result, transitions = _credit("implemented")
    assert result.status == "implemented"
    assert transitions == []
