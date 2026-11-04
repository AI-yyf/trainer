"""Goal mode: one small goal, the learner does the work; no lecture, no evidence claims."""

from __future__ import annotations

from app.core.models import UserProfile
from app.llm.prompts import build_coaching_system_prompt


def test_goal_mode_prompt_requires_an_action_before_explanation() -> None:
    prompt = build_coaching_system_prompt(
        UserProfile(),
        coach_context={"goal_mode": True},
    )

    assert "Goal Mode" in prompt
    assert "the learner does the work" in prompt
    assert "Do not open with a lecture" in prompt
    assert "ONE tiny concrete action" in prompt
    assert "Wait for their attempt" in prompt
    assert "correct action alone is not mastery" in prompt
    assert "explain the reasoning" in prompt
    assert "correct teach-back and transfer" in prompt
    assert "Never declare the goal complete" in prompt
    assert "never accept a self-claim" in prompt
    assert "the learner ends it with the goal control" in prompt
    assert "Do not claim formal evidence" in prompt


def test_goal_mode_prompt_is_opt_in() -> None:
    prompt = build_coaching_system_prompt(UserProfile())

    assert "Goal Mode" not in prompt
