"""Turn facts that must stay separate: explicit requests are not affect."""

from __future__ import annotations

import pytest

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


@pytest.mark.parametrize(
    "request_text",
    [
        "Ponme un ejercicio.",
        "Donne-moi un exercice.",
        "Gib mir eine Übung.",
        "練習問題を一問出してください。",
        "연습 문제를 한 개 내 주세요.",
        "Me dê um exercício.",
    ],
)
def test_learning_composer_exercise_requests_keep_their_turn_intent(request_text: str) -> None:
    decision = decide_turn(TurnFacts(message=request_text, answer_mode="direct"))
    assert decision.mode == "practice"
    assert decision.allow_question is True
    assert decision.allow_review is False
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


def test_refusal_overrides_inferred_and_explicit_review_routing() -> None:
    turn = decide_turn(TurnFacts(
        message="不要复习，今天只想聊聊。", requested_intent="review",
        needs_review=True, due_review_count=3,
    ))
    assert turn.mode == "chat"
    assert turn.allow_review is False


def test_practice_request_overrides_stored_direct_answer_preference() -> None:
    turn = decide_turn(TurnFacts(
        message="我平时喜欢直接回答，今天给我出一道题。", answer_mode="direct",
    ))
    assert turn.allow_formal_task is True
    assert turn.mode == "practice"


def test_refusal_does_not_block_a_later_different_request() -> None:
    turn = decide_turn(TurnFacts(message="今天不要复习，不过请给我出一道题。"))
    assert turn.mode == "practice"
    assert turn.allow_review is False
    assert turn.allow_formal_task is True


def test_referenced_actions_do_not_create_formal_learning_work() -> None:
    discussion = decide_turn(TurnFacts(message="这段文档为什么建议每天复习？"))
    refusal = decide_turn(TurnFacts(
        message="我不是要制定学习计划。", requested_intent="plan",
    ))
    assert discussion.mode == "teach" and not discussion.allow_review
    assert not refusal.allow_formal_plan


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
