"""§八/§九 behavior tests: teaching depth ladder + over-teaching suppression.

The depth policy maps the learner's current skill state to a response depth
(L0 direct answer … L5 transfer) and honors the honesty rules:

* An explicit "just tell me" request overrides everything: answer directly,
  do not quiz, do not attach practice.
* Urgent rescue requests are fix-first (L0) with an optional light practice
  offer — never a forced lesson.
* Definition/lookup questions are capped at L1 even for strong learners.
* Otherwise the ladder follows the skill projection state.
"""

from __future__ import annotations

import pytest

from app.core.models import MemorySnapshot, TurnRequest, UserProfile
from app.llm.prompts import _build_context_block, _build_learner_context_block
from app.pedagogy.service import PedagogyService
from app.pedagogy.teaching_depth import (
    resolve_teaching_depth,
    resolve_teaching_depth_skill_state,
)


def test_direct_answer_request_overrides_to_level_zero() -> None:
    for message in (
        "直接告诉我答案，别问我问题。",
        "Just tell me the answer, no exercises please.",
        "把代码直接给我。",
    ):
        decision = resolve_teaching_depth(
            message=message,
            skill_state="repeat_verified",
        )
        assert decision.level == 0, message
        assert decision.direct_answer_override is True
        assert decision.offer_light_practice is False
        assert any("direct_answer_request" in item for item in decision.evidence)


def test_urgent_rescue_is_fix_first_with_optional_practice_offer() -> None:
    for message in (
        "线上服务挂了，赶紧帮我定位这个报错！",
        "Urgent: production is down, help me debug this stack trace now.",
    ):
        decision = resolve_teaching_depth(
            message=message,
            skill_state="independent",
        )
        assert decision.level == 0, message
        assert decision.direct_answer_override is False, (
            "rescue asks to fix, not to be told the answer"
        )
        assert decision.offer_light_practice is True, message
        assert any("urgent_rescue" in item for item in decision.evidence)


@pytest.mark.parametrize(
    ("skill_state", "expected_level"),
    [
        ("needs_review", 1),
        ("not_verified", 2),
        ("assisted", 3),
        ("independent", 4),
        ("repeat_verified", 5),
        (None, 1),
    ],
)
def test_skill_ladder_maps_to_depth_levels(skill_state: str | None, expected_level: int) -> None:
    decision = resolve_teaching_depth(
        message="这道题我想继续深入练一练。",
        skill_state=skill_state,
    )
    assert decision.level == expected_level
    assert decision.direct_answer_override is False
    assert decision.offer_light_practice is False


def test_definition_question_is_capped_even_for_strong_learners() -> None:
    for message in (
        "什么是装饰器？",
        "What is a decorator? Just a quick definition.",
    ):
        decision = resolve_teaching_depth(
            message=message,
            skill_state="repeat_verified",
        )
        assert decision.level <= 1, message
        assert decision.direct_answer_override is False


def test_high_independent_skill_without_cues_stays_on_the_ladder() -> None:
    decision = resolve_teaching_depth(
        message="我想继续深入练一练这块。",
        skill_state="repeat_verified",
    )
    assert decision.level == 5
    assert "skill_state:repeat_verified" in decision.evidence


def test_decide_teaching_surfaces_depth_fields() -> None:
    service = PedagogyService()
    request = TurnRequest(message="直接告诉我这个报错是什么意思。", current_file=None)
    learner_state = service.infer_learner_state(
        request=request,
        profile=UserProfile(),
        memory_snapshot=MemorySnapshot(),
    )
    decision = service.decide_teaching(
        request=request,
        learner_state=learner_state,
        profile=UserProfile(),
        memory_snapshot=MemorySnapshot(),
    )
    assert decision.depth_level == 0
    assert decision.direct_answer_override is True


def test_prompt_blocks_render_the_depth_directive() -> None:
    teaching_decision = {
        "mode": "guided",
        "primary_goal": "Land one focused edit",
        "depth_level": 4,
        "depth_label": "independent practice",
        "direct_answer_override": False,
        "offer_light_practice": False,
    }
    context = {"teaching_decision": teaching_decision}

    context_block = _build_context_block(context)
    learner_block = _build_learner_context_block(context)
    for block in (context_block, learner_block):
        assert "Teaching depth: L4 independent practice." in block
        assert "Do not hand over the finished solution" in block


def test_prompt_blocks_render_the_direct_answer_override() -> None:
    teaching_decision = {
        "mode": "direct_rescue",
        "depth_level": 0,
        "depth_label": "direct answer",
        "direct_answer_override": True,
        "offer_light_practice": False,
    }
    context = {"teaching_decision": teaching_decision}

    for block in (_build_context_block(context), _build_learner_context_block(context)):
        assert "The learner explicitly asked for the direct answer" in block
        assert "Do not quiz" in block


def test_prompt_blocks_render_the_optional_practice_offer() -> None:
    teaching_decision = {
        "mode": "direct_rescue",
        "depth_level": 0,
        "depth_label": "direct answer",
        "direct_answer_override": False,
        "offer_light_practice": True,
    }
    context = {"teaching_decision": teaching_decision}

    for block in (_build_context_block(context), _build_learner_context_block(context)):
        assert "optionally offer one short practice" in block


def test_select_skill_state_prefers_the_scenario_dimension() -> None:
    projection = {
        "dimensions": {
            "comprehension": {"state": "repeat_verified"},
            "debugging": {"state": "assisted"},
        }
    }
    assert (
        resolve_teaching_depth_skill_state(
            skill_projection=projection, scenario="debug_loop"
        )
        == "assisted"
    )
    assert (
        resolve_teaching_depth_skill_state(
            skill_projection=projection, scenario="concept_teaching"
        )
        == "repeat_verified"
    )


def test_select_skill_state_falls_back_to_the_weakest_dimension() -> None:
    projection = {
        "dimensions": {
            "comprehension": {"state": "repeat_verified"},
            "debugging": {"state": "assisted"},
            "transfer": {"state": "not_verified"},
        }
    }
    assert (
        resolve_teaching_depth_skill_state(skill_projection=projection, scenario=None)
        == "not_verified"
    )
    assert resolve_teaching_depth_skill_state(skill_projection=None, scenario=None) is None
    assert (
        resolve_teaching_depth_skill_state(
            skill_projection={"dimensions": {}}, scenario="debug_loop"
        )
        is None
    )


def test_ladder_honors_the_real_projection_state() -> None:
    decision = resolve_teaching_depth(
        message="这块我想继续深入。",
        skill_state="assisted",
    )
    assert decision.level == 3


def test_decide_teaching_uses_the_projection_state() -> None:
    service = PedagogyService()
    request = TurnRequest(message="这块我想继续深入练一练。", current_file=None)
    learner_state = service.infer_learner_state(
        request=request,
        profile=UserProfile(),
        memory_snapshot=MemorySnapshot(),
    )
    decision = service.decide_teaching(
        request=request,
        learner_state=learner_state,
        profile=UserProfile(),
        memory_snapshot=MemorySnapshot(),
        skill_state="independent",
    )
    assert decision.depth_level == 4
    assert decision.depth_label == "independent practice"
    assert any("skill_state:independent" in item for item in decision.evidence)
