"""Affect inference must use learner evidence, never backlog size as mood."""

from __future__ import annotations

from app.affect.service import AffectService
from app.core.models import LearnerState, MemorySnapshot

NEUTRAL_MESSAGE = "Can you explain how the queue lock protects the write path?"


def _infer(*, message: str = NEUTRAL_MESSAGE, learner: LearnerState | None = None, memory: MemorySnapshot | None = None):
    return AffectService().infer_state(
        message=message,
        learner_state=learner or LearnerState(),
        memory_snapshot=memory or MemorySnapshot(),
    )


def test_due_review_backlog_does_not_infer_frustration_or_urgency() -> None:
    baseline = _infer(memory=MemorySnapshot(due_review_count=0))
    backlog = _infer(memory=MemorySnapshot(due_review_count=12))

    assert backlog.frustration_level == baseline.frustration_level
    assert backlog.confidence_level == baseline.confidence_level
    assert backlog.momentum_level == baseline.momentum_level
    assert backlog.urgency_level == baseline.urgency_level
    assert backlog.recovery_signal == baseline.recovery_signal
    assert backlog.needs_reassurance == baseline.needs_reassurance
    assert backlog.recovery_signal == "steady"


def test_explicit_overload_signal_still_drives_rescue() -> None:
    state = _infer(message="I am stuck and overwhelmed; nothing is working.")
    assert state.recovery_signal == "overloaded"
    assert state.needs_reassurance is True


def test_needs_rescue_is_not_gated_by_due_review_count() -> None:
    learner = LearnerState(needs_rescue=True)
    without_backlog = _infer(learner=learner, memory=MemorySnapshot(due_review_count=0))
    with_backlog = _infer(learner=learner, memory=MemorySnapshot(due_review_count=9))

    assert without_backlog.recovery_signal == "overloaded"
    assert with_backlog.recovery_signal == "overloaded"
    assert with_backlog.frustration_level == without_backlog.frustration_level


def test_success_outcome_reaches_recovering_even_with_a_large_backlog() -> None:
    outcome = MemorySnapshot(
        due_review_count=12,
        learning_outcomes=[{"outcome": "tests_passed", "repetition_count": 1}],
    )
    state = _infer(memory=outcome)
    assert state.recovery_signal == "recovering"
    assert state.frustration_level < 0.58
