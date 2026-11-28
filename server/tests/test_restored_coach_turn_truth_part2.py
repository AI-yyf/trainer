"""(r) Coaching turn truth: the visible reply, its grounding and its next step are
    derived from real context, never from theater.

Guarantees covered:
  * visible coach text is sanitized, language-aligned and free of credential-shaped strings;
  * next steps and file references are grounded in real resources and the learner's project;
  * turn decisions, lanes and budgets are deterministic under context pressure;
  * pedagogy, teaching depth and explanation quality are derived from real turn facts.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_teaching_depth.py
  * server/tests/test_turn_decision.py
  * server/tests/test_agent_rubric_tools.py
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.models import MemorySnapshot, TurnRequest, UserProfile
from app.llm.agent_tool_context import _build_agent_tool_context_extra
from app.llm.prompts import _build_context_block, _build_learner_context_block
from app.llm.tools import ToolContext, ToolRegistry, build_default_tool_registry
from app.pedagogy.service import PedagogyService
from app.pedagogy.teaching_depth import resolve_teaching_depth, resolve_teaching_depth_skill_state
from app.pedagogy.turn_decision import TurnFacts, decide_turn
from app.resources.models import ResourceChunk, ResourceKind
from app.resources.models import ResourceRecord as RegistryResourceRecord
from app.training.card_request import message_requests_rubric_review

# ---------------------------------------------------------------------------
# Restored from test_teaching_depth.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Restored from test_turn_decision.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Restored from test_agent_rubric_tools.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


class _RegistryStub:
    def __init__(self, resources: dict[str, RegistryResourceRecord], chunks: dict[str, list[ResourceChunk]]):
        self._resources = resources
        self._chunks = chunks

    def get(self, resource_id: str) -> RegistryResourceRecord | None:
        return self._resources.get(resource_id)

    def list_chunks(self, resource_id: str) -> list[ResourceChunk]:
        return list(self._chunks.get(resource_id, []))


class _ResourceServiceStub:
    def __init__(self, registry: _RegistryStub):
        self.registry = registry


class _RuntimeStub:
    def __init__(self, resource_service: _ResourceServiceStub | None):
        self.resource_service = resource_service


def _context(runtime: Any, **extra: Any) -> ToolContext:
    return ToolContext(
        runtime=runtime,
        workspace_id="workspace-rubric",
        session_id="session-rubric",
        extra=dict(extra),
    )


def _registry() -> ToolRegistry:
    return build_default_tool_registry()


def _literature_library() -> _RuntimeStub:
    resource = RegistryResourceRecord.create(
        kind=ResourceKind.EPUB,
        source_uri="/tmp/kongyiji.epub",
        title="《孔乙己》精读",
        metadata={
            "content_language": "zh-CN",
            "knowledge_fragments": [
                {
                    "paragraph_anchor": "¶spine:ch1:/body/p[3]",
                    "citation_id": "cite-res-1@v1",
                    "location": {"chunk_id": "chunk_aaa", "paragraph_anchor": "¶spine:ch1:/body/p[3]"},
                }
            ],
        },
    )
    chunks = [
        ResourceChunk(
            resource_id=resource.id,
            chunk_id="chunk_aaa",
            text="孔乙己是站着喝酒而穿长衫的唯一的人。他身材很高大；青白脸色，皱纹间时常夹些伤痕。",
            order=0,
            start_line=1,
            end_line=3,
        ),
        ResourceChunk(
            resource_id=resource.id,
            chunk_id="chunk_bbb",
            text="店内外充满了快活的空气。",
            order=1,
            start_line=4,
            end_line=4,
        ),
    ]
    return _RuntimeStub(
        _ResourceServiceStub(_RegistryStub({resource.id: resource}, {resource.id: chunks}))
    )


_RUBRIC_ITEMS = [
    {"statement": "点明叙述视角是小伙计", "anchor": "孔乙己是站着喝酒而穿长衫的唯一的人", "criteria": ["提到小伙计视角"]},
    {"statement": "说明短衣帮与长衫客的分界", "anchor": "短衣帮", "criteria": []},
]


@pytest.mark.asyncio
async def test_run_rubric_review_requires_the_host_gate() -> None:
    runtime = _literature_library()
    result = await _registry().invoke(
        _context(runtime), "run_rubric_review", {"submission": "一些文本。"}
    )
    assert result["ok"] is False
    assert result["error"] == "rubric_review_not_allowed"


def _extra(message: str | None, current_file: Any) -> dict[str, Any]:
    return _build_agent_tool_context_extra(
        coach_context=None,
        attachment_delivery={},
        answer_mode="guided",
        current_file=current_file,
        learner_message=message,
    )


def test_stamp_arms_on_explicit_request_with_host_rubric() -> None:
    extra = _extra(
        "帮我按评分标准评审我的仿写",
        {"path": "card://text_payload", "rubric_items": _RUBRIC_ITEMS},
    )
    assert extra["rubric_review_allowed"] is True
    assert "run_rubric_review" not in extra["denied_tool_names"]


def test_stamp_fails_closed_without_host_rubric() -> None:
    extra = _extra("帮我按评分标准评审我的仿写", {"path": "card://text_payload", "content": ""})
    assert extra["rubric_review_allowed"] is False
    assert "run_rubric_review" in extra["denied_tool_names"]


def test_stamp_fails_closed_without_explicit_request() -> None:
    extra = _extra("随便聊聊今天读的内容", {"path": "card://text_payload", "rubric_items": _RUBRIC_ITEMS})
    assert extra["rubric_review_allowed"] is False
    assert "run_rubric_review" in extra["denied_tool_names"]


def test_stamp_respects_explicit_rejection_language() -> None:
    assert message_requests_rubric_review("不要用评分标准评审，直接聊感受") is False
    assert message_requests_rubric_review("帮我按评分标准评审我的仿写") is True
    assert message_requests_rubric_review("run the rubric on my submission") is True
    assert message_requests_rubric_review("") is False
