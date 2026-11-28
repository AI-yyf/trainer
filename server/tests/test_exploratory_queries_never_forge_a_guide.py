"""An explanation request is not an implementation task, and a guide never names a placeholder.

Contract §5: when the learner asks to be told or shown something, the coach tells them and
does not pull them into an exercise; `PedagogyService.analyze_turn` documents that a
project-tour or research query gets no implementation guide. On 2026-11-25 the broad
"讲解一下 / 介绍一下" tokens were removed from the exploratory-query list so that plain
explanation requests would not request tools. The same list decides whether an implementation
guide is built, so "讲解一下这个文件夹项目呢" in direct mode started to produce a guide that
treats the question as a feature to build.

Separately, with no focus, memory or long-term goal the pedagogy service falls back to the
generic label "current task". That label leaked verbatim into every guide for a new learner,
including for a real implementation request: "先把 current task 压成一个可验证的行为变化".
"""

from __future__ import annotations

import dataclasses

import pytest

from app.core.models import CoachRequestAnswerMode, TurnRequest
from app.pedagogy.service import PedagogyService
from app.pedagogy.service_types import GENERIC_FOCUS_LABEL

MODES: tuple[CoachRequestAnswerMode, ...] = ("auto", "guided", "balanced", "coach-first", "direct")


def _guide(message: str, mode: CoachRequestAnswerMode):
    _state, _decision, artifacts = PedagogyService().analyze_turn(
        request=TurnRequest(message=message, answer_mode=mode)
    )
    return artifacts


def test_casual_greetings_and_exploratory_queries_never_forge_a_patch_step() -> None:
    """Restored from test_autonomous_teacher_and_settings.py at df0a3e2a^ (assertions unchanged)."""
    for msg in (
        "你好",
        "hi",
        "hello!",
        "谢谢",
        "讲解一下这个文件夹项目呢",
        "你帮我找找目前的世界模型的研究进展可以吗",
    ):
        for mode in MODES:
            assert _guide(msg, mode).implementation_guide is None, (msg, mode)


@pytest.mark.parametrize(
    "message",
    [
        "介绍一下这个项目",
        "给我讲讲这个项目",
        "讲一下这个仓库",
        "讲解一下整个项目",
        "walk me through this project",
        "introduce this repo",
        "tell me about this codebase",
    ],
)
def test_project_tour_requests_in_every_phrasing_get_no_implementation_guide(message: str) -> None:
    for mode in MODES:
        assert _guide(message, mode).implementation_guide is None, (message, mode)


@pytest.mark.parametrize("message", ["帮我实现一个重试函数", "帮我写一个解析 CSV 的小工具"])
def test_a_real_implementation_request_still_gets_its_guide_when_the_learner_asks_directly(
    message: str,
) -> None:
    """The guard for the fix above: only explanation requests are excluded from the guide."""
    assert _guide(message, "direct").implementation_guide is not None, message
    # In the default modes the coach still chooses how to teach; it must not crash on them.
    for mode in MODES:
        _guide(message, mode)


@pytest.mark.parametrize(
    ("message", "mode"),
    [
        ("帮我实现一个重试函数", "auto"),
        ("帮我实现一个重试函数", "direct"),
        ("这里报错了，帮我看下", "direct"),
    ],
)
def test_no_guide_text_carries_the_generic_focus_placeholder(
    message: str, mode: CoachRequestAnswerMode
) -> None:
    guide = _guide(message, mode).implementation_guide
    assert guide is not None, (message, mode)

    fields = dataclasses.asdict(guide)
    offenders = [name for name, value in fields.items() if GENERIC_FOCUS_LABEL in str(value)]
    assert offenders == [], (message, mode, {name: fields[name] for name in offenders})
    # The idea summary speaks about what the learner asked for.
    assert any(part in guide.idea_summary for part in ("重试函数", "报错", message)), guide.idea_summary
