"""Turn facts that must stay separate: explicit requests are not affect."""

from __future__ import annotations

from app.core.models import MemorySnapshot, TurnRequest
from app.pedagogy.service import PedagogyService
from app.pedagogy.turn_decision import TurnFacts, decide_turn


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


def test_central_decision_direct_answer_has_no_formal_actions() -> None:
    decision = decide_turn(TurnFacts(message="直接告诉我答案，别反问。"))
    assert decision.mode == "direct_answer"
    assert decision.confidence == "known"
    assert decision.allow_question is False
    assert decision.allow_formal_task is False
    assert decision.allow_formal_plan is False
    assert decision.allow_review is False


def test_inferred_task_intent_cannot_start_formal_practice() -> None:
    decision = decide_turn(
        TurnFacts(
            message="帮我看看这个函数为什么这么写。",
            requested_intent="task",
            intent_source="inferred",
            has_active_goal=True,
        )
    )
    assert decision.mode == "teach"
    assert decision.allow_formal_task is False
    assert decision.allow_formal_plan is False


def test_explicit_task_intent_starts_practice() -> None:
    decision = decide_turn(
        TurnFacts(message="开始练习", requested_intent="task", intent_source="explicit")
    )
    assert decision.mode == "practice"
    assert decision.allow_formal_task is True
    assert decision.allow_formal_plan is False


def test_explicit_review_and_plan_requests_are_honored() -> None:
    review = decide_turn(
        TurnFacts(message="帮我复习一下", requested_intent="review", intent_source="explicit")
    )
    plan = decide_turn(
        TurnFacts(message="制定学习计划", requested_intent="plan", intent_source="explicit")
    )
    assert review.mode == "review" and review.allow_review is True
    assert plan.mode == "plan" and plan.allow_formal_plan is True


def test_proactive_review_does_not_interrupt_a_blocked_activity() -> None:
    decision = decide_turn(
        TurnFacts(
            message="I am tracing this failure.",
            needs_review=True,
            due_review_count=5,
            activity_in_progress=True,
        )
    )
    assert decision.mode == "chat"
    assert decision.allow_review is False
    assert decision.evidence[-1] == "turn_context:unknown"


def test_due_review_can_be_offered_when_not_blocked() -> None:
    decision = decide_turn(
        TurnFacts(
            message="I have a few minutes before my next meeting.",
            needs_review=True,
            due_review_count=5,
        )
    )
    assert decision.mode == "review"
    assert decision.allow_review is True
    assert decision.may_interrupt is True


def test_unknown_turn_stays_conversational_and_does_not_invent_mastery() -> None:
    decision = decide_turn(TurnFacts(message="I have been thinking about this."))
    assert decision.mode == "chat"
    assert decision.source == "unknown"
    assert decision.confidence == "unknown"
    assert decision.allow_formal_task is False
    assert decision.allow_formal_plan is False


def test_needs_rescue_is_fix_first_without_formal_task() -> None:
    decision = decide_turn(TurnFacts(message="It is broken.", needs_rescue=True))
    assert decision.mode == "direct_answer"
    assert decision.source == "learner_state"
    assert decision.allow_formal_task is False


def _profile():
    from app.core.models import UserProfile

    return UserProfile(long_term_goal="Build reliable distributed systems")


def test_teaching_decision_exposes_the_central_turn_contract() -> None:
    service = PedagogyService()
    profile = _profile()
    memory = MemorySnapshot()

    inferred = service.decide_teaching(
        request=TurnRequest(
            message="帮我看看这个函数为什么这么写。",
            intent="task",
            intentSource="inferred",
        ),
        learner_state=service.infer_learner_state(
            request=TurnRequest(message="帮我看看这个函数为什么这么写。"), profile=profile, memory_snapshot=memory
        ),
        profile=profile,
        memory_snapshot=memory,
    )
    assert inferred.turn_mode == "teach"
    assert inferred.turn_allow_formal_task is False

    explicit_plan = service.decide_teaching(
        request=TurnRequest(message="制定学习计划", intent="plan", intentSource="explicit"),
        learner_state=service.infer_learner_state(
            request=TurnRequest(message="制定学习计划"), profile=profile, memory_snapshot=memory
        ),
        profile=profile,
        memory_snapshot=memory,
    )
    assert explicit_plan.turn_mode == "plan"
    assert explicit_plan.turn_allow_formal_plan is True
    assert explicit_plan.should_produce_plan_artifact is True

    explicit_review = service.decide_teaching(
        request=TurnRequest(message="帮我复习一下", intent="review", intentSource="explicit"),
        learner_state=service.infer_learner_state(
            request=TurnRequest(message="帮我复习一下"), profile=profile, memory_snapshot=memory
        ),
        profile=profile,
        memory_snapshot=memory,
    )
    assert explicit_review.turn_mode == "review"
    assert explicit_review.turn_allow_review is True


def test_onboarding_needs_one_question_without_minting_work() -> None:
    decision = decide_turn(
        TurnFacts(message="我的长期目标是成为更强的后端工程师。", onboarding_needed=True)
    )
    assert decision.mode == "clarify"
    assert decision.allow_question is True
    assert decision.allow_formal_task is False
    assert decision.allow_formal_plan is False
