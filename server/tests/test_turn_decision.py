"""Turn facts that must stay separate: explicit requests are not affect."""

from __future__ import annotations

from app.core.models import MemorySnapshot, TurnRequest
from app.pedagogy.service import PedagogyService


def test_direct_answer_request_does_not_raise_frustration() -> None:
    service = PedagogyService()
    baseline = service.infer_learner_state(
        request=TurnRequest(message="Please explain how the queue lock protects the write path."),
        profile=None,
        memory_snapshot=MemorySnapshot(),
    )
    direct = service.infer_learner_state(
        request=TurnRequest(message="直接告诉我答案，别反问。"),
        profile=None,
        memory_snapshot=MemorySnapshot(),
    )

    assert direct.frustration_level == baseline.frustration_level
    assert direct.needs_rescue is False
    assert "message_requests_rescue" in direct.evidence


def test_direct_answer_request_suppresses_question_exercise_and_plan() -> None:
    from app.core.models import UserProfile

    service = PedagogyService()
    request = TurnRequest(
        message="直接告诉我答案，别反问：Python 元组里的列表为什么还能修改？",
        intent="coach",
    )
    profile = UserProfile(long_term_goal="Build reliable distributed systems")
    memory = MemorySnapshot()
    learner = service.infer_learner_state(request=request, profile=profile, memory_snapshot=memory)

    decision = service.decide_teaching(
        request=request,
        learner_state=learner,
        profile=profile,
        memory_snapshot=memory,
    )

    assert decision.direct_answer_override is True
    assert decision.should_end_with_question is False
    assert decision.should_generate_exercise is False
    assert decision.should_produce_plan_artifact is False
    assert "direct_answer_override" in decision.reason
