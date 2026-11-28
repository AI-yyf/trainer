"""The system prompt's opening bytes do not change between turns, so a provider's prefix cache holds.

A provider reuses the beginning of a request only while it stays byte-identical. The learner profile
used to open the prompt, and the pedagogy service adapts its goal, teaching style and answer policy
between turns, so the first request of every new turn diverged after about 190 tokens and only the
calls inside one turn (after tool results) hit the cache. Measured on 2026-11-28 against a MiniMax
gateway: 128-188 cached tokens of 8-10k at the start of each turn.

Order now: the session-invariant rules, request priority, tool instructions and reply language first;
then the learner profile and the per-turn biases.
"""

from __future__ import annotations

from typing import Any

from app.core.model_domains.foundations_and_provider import UserProfile
from app.llm.prompt_domains.messages_and_turn_signals import build_static_coaching_prefix
from app.llm.prompt_domains.templates_and_system import (
    COACHING_SYSTEM_TEMPLATE,
    LEARNER_PROFILE_BLOCK,
    MINIMAL_COACHING_SYSTEM_TEMPLATE,
    MINIMAL_LEARNER_PROFILE_BLOCK,
)

PROFILE_HEADING = "\n\n## Learner Profile"


def _profile(**overrides: Any) -> UserProfile:
    base = {
        "long_term_goal": "Build stronger implementation habits",
        "background": "Backend developer",
        "weekly_hours": 4,
        "teaching_style": "guided",
        "answer_policy": "guided",
        "target_project": "learner-project",
        "preferred_libraries": ["asyncio"],
    }
    return UserProfile.model_validate({**base, **overrides})


def _invariant(prompt: str) -> str:
    return prompt[: prompt.index(PROFILE_HEADING)]


def test_rules_precede_everything_that_changes_between_turns() -> None:
    tuesday = build_static_coaching_prefix(
        _profile(), "zh-CN", "guided", agent_loop_enabled=True
    )
    wednesday = build_static_coaching_prefix(
        _profile(
            long_term_goal="Understand idempotency",
            background="Not specified",
            teaching_style="hands-on",
            answer_policy="direct",
            target_project="other-repo",
            preferred_libraries=[],
        ),
        "zh-CN",
        "direct",
        agent_loop_enabled=True,
    )

    shared = _invariant(tuesday)
    assert wednesday.startswith(shared)
    for section in ("Core job:", "## Request Priority", "## Agent Loop & Tools", "## Language"):
        assert section in shared, section
    for scoped in ("Build stronger implementation habits", "Understand idempotency", "learner-project", "Active policy"):
        assert scoped not in shared, scoped
    # The scoped part still carries everything the old opening carried.
    tail = wednesday[len(shared):]
    for expected in ("## Learner Profile", "Goal: Understand idempotency", "Target project: other-repo", "Active style: hands-on"):
        assert expected in tail, expected


def test_the_opening_bytes_are_the_same_for_every_learner() -> None:
    openings = {
        build_static_coaching_prefix(_profile(long_term_goal=goal), "en-US", "guided", agent_loop_enabled=True)[:400]
        for goal in ("", "Learn Rust", "理解幂等")
    }

    assert len(openings) == 1
    assert openings.pop().startswith("You are Trainer, a long-term learning coach inside VS Code.\n\nCore job:")


def test_the_minimal_template_keeps_the_same_order() -> None:
    a = build_static_coaching_prefix(_profile(), "zh-CN", "guided", use_minimal_template=True)
    b = build_static_coaching_prefix(
        _profile(long_term_goal="Other goal", teaching_style="challenging", answer_policy="direct"),
        "zh-CN",
        "direct",
        use_minimal_template=True,
    )

    shared = _invariant(a)
    assert b.startswith(shared)
    assert shared.startswith("You are Trainer, a focused technical coding coach inside VS Code.")
    assert "## Language" in shared and "## Request Priority" in shared
    assert "Goal: Other goal" in b[len(shared):]


def test_a_short_turn_only_drops_the_teaching_method_tail() -> None:
    full = build_static_coaching_prefix(_profile(), "zh-CN", "guided")
    lean = build_static_coaching_prefix(_profile(), "zh-CN", "guided", minimal_context=True)

    assert lean == full[: full.index("\n\n## Teaching Method")]
    assert "## Answer Policy Bias" in lean


def test_the_guided_requirements_follow_the_policy_bias() -> None:
    guided = build_static_coaching_prefix(_profile(), "zh-CN", "guided")
    direct = build_static_coaching_prefix(_profile(), "zh-CN", "direct")

    assert guided.index("## Answer Policy Bias") < guided.index("- 先状态，后方案")
    assert "- 先状态，后方案" not in direct
    # Only the scoped tail differs; the invariant part is byte-identical.
    assert direct.startswith(_invariant(guided))


def test_the_templates_carry_no_profile_placeholders() -> None:
    for template in (COACHING_SYSTEM_TEMPLATE, MINIMAL_COACHING_SYSTEM_TEMPLATE):
        for placeholder in ("{goal}", "{background}", "{weekly_hours}", "{teaching_style}", "{answer_policy}", "{target_project}", "{libraries}"):
            assert placeholder not in template, (template[:40], placeholder)
    for block in (LEARNER_PROFILE_BLOCK, MINIMAL_LEARNER_PROFILE_BLOCK):
        assert block.startswith("## Learner Profile")
        assert "{goal}" in block and "{target_project}" in block
