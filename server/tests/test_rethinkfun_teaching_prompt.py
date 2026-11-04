"""RethinkFun state-driven teaching: lecture requests get the full contract,
short factual questions stay direct."""

from __future__ import annotations

from app.core.models import UserProfile
from app.llm.prompts import build_coaching_system_prompt


def test_lecture_request_gets_state_flow_and_claim_chain() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(),
        message="讲明白 KL 散度为什么需要，并推导它的形式。",
    )

    assert "State-Driven Teaching (RethinkFun)" in prompt
    assert "known, unknown, goal, obstacle" in prompt
    assert "Introduce a new object only because" in prompt
    assert "formulas arrive late" in prompt
    assert "This turn is a lecture/derivation request" in prompt
    assert "chain of claims" in prompt
    assert "predict each formula" in prompt
    assert "If the topic has no formula or no code, omit that part" in prompt


def test_short_factual_question_stays_direct() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(),
        message="with 退出时会释放锁吗？",
    )

    assert "State-Driven Teaching (RethinkFun)" in prompt
    assert "For a short factual question, answer it directly and stop." in prompt
    assert "This turn is a lecture/derivation request" not in prompt
