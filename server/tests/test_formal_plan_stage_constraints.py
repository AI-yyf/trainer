from types import SimpleNamespace

import pytest

from app.llm.tools import (
    ToolContext,
    _explicit_formal_plan_stage_count,
    build_default_tool_registry,
)


@pytest.mark.parametrize(
    ('message', 'expected'),
    [
        ('分为3个阶段，从第1阶段开始，保留第3阶段', 3),
        ('生成三个阶段，每天20分钟', 3),
        ('Build a 3-stage plan. Start stage 1.', 3),
        ('Make a plan with 12 stages.', 12),
        ('解释第3阶段，保持第1阶段', None),
        ('Explain stage 3.', None),
    ],
)
def test_explicit_stage_count_does_not_confuse_stage_numbers(message, expected):
    assert _explicit_formal_plan_stage_count(message) == expected


@pytest.mark.parametrize('invalid_stage', [None, {'title': 'Missing goal'}, {'goal': 'Missing title'}])
async def test_formal_plan_cannot_silently_drop_an_invalid_stage(invalid_stage):
    saved = []
    runtime = SimpleNamespace(
        repository=SimpleNamespace(
            get_latest_plan=lambda _: None, save_plan=lambda _, plan: saved.append(plan)
        ),
        sandbox_service=None,
        sessions={},
    )
    result = await build_default_tool_registry().invoke(
        ToolContext(runtime=runtime, workspace_id='stage-constraints',
                    extra={'formal_plan_mutation': True, 'allow_coach_only_tools': True}),
        'save_formal_plan',
        {'title': 'Plan', 'summary': 'Cover all stages',
         'stages': [{'title': 'Valid', 'goal': 'Observe one result'}, invalid_stage]},
    )
    assert result['ok'] is False
    assert result['error'] == 'invalid_stages'
    assert saved == []


async def test_formal_plan_rejects_a_missing_explicitly_requested_stage():
    saved = []
    runtime = SimpleNamespace(
        repository=SimpleNamespace(
            get_latest_plan=lambda _: None, save_plan=lambda _, plan: saved.append(plan)
        ),
        sandbox_service=None,
        sessions={},
    )
    result = await build_default_tool_registry().invoke(
        ToolContext(runtime=runtime, workspace_id='stage-constraints', extra={
            'formal_plan_mutation': True, 'allow_coach_only_tools': True,
            'learner_message': '分为3个阶段，从第1阶段开始',
        }),
        'save_formal_plan',
        {'title': 'Three stages', 'summary': 'Observe, implement, test',
         'stages': [{'title': title, 'goal': title} for title in ['Observe', 'Implement']]},
    )
    assert result['ok'] is False
    assert result['error'] == 'stage_count_mismatch'
    assert result['expected_stage_count'] == 3
    assert result['actual_stage_count'] == 2
    assert saved == []
