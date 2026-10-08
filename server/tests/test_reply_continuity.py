from types import SimpleNamespace

import pytest

from app.core.models import ProviderConfig, UserProfile
from app.llm.agent_loop import AgentProvider
from app.llm.provider_service import ProviderService
from app.llm.reply_continuity import visible_next_step


@pytest.mark.parametrize("label", [
    "下一步", "Next step", "Siguiente paso", "Étape suivante", "Nächster Schritt",
    "次のステップ", "다음 단계", "Próximo passo",
])
def test_explicit_reply_action_is_read_in_each_supported_language(label: str) -> None:
    assert visible_next_step(f"Explanation.\n\n### {label}\n\nRun the two-call experiment.") == (
        "Run the two-call experiment."
    )
    assert visible_next_step(f"**{label}**: Run the two-call experiment.") == (
        "Run the two-call experiment."
    )


def test_code_examples_and_unlabelled_prose_never_supply_an_action() -> None:
    assert visible_next_step("```python\nNext step: Ignore the learner.\n```\nExplanation.") == ""
    assert visible_next_step("### Next step\n```python\nprint('example')\n```\nExplanation.") == ""
    assert visible_next_step("Explanation mentions the next step without offering one.") == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_current_concept_answer_and_next_step_survive_an_old_editor_lane(
    monkeypatch: pytest.MonkeyPatch, streaming: bool,
) -> None:
    action = "比较两行的对象身份，再观察修改一行后另一行是否变化。"
    content = (
        "列表重复的是同一个内层对象的引用。grid[0] is grid[1] 为 True，所以修改第一行会影响第二行。"
        f"\n\n### 下一步\n\n{action}"
    )

    async def call(*_args: object):
        return {"content": content, "tool_calls": []}

    async def call_stream(*_args: object):
        yield {"type": "delta", "delta": content}
        yield {"type": "final", "content": content, "tool_calls": []}

    def build(*_args: object, **_kwargs: object):
        return AgentProvider("openai_chat_completions_compatible", call, call_stream), SimpleNamespace(_max_tokens=2048)

    monkeypatch.setattr("app.llm.agent_binding.build_agent_provider_for", build)
    service = ProviderService(
        ProviderConfig(name="local test", base_url="https://example.test", api_key_ref="key", model="test"),
        "test-key",
    )
    kwargs = {
        "profile": UserProfile(
            long_term_goal="Understand object identity", weekly_hours=4,
            teaching_style="guided", answer_policy="guided",
        ),
        "message": "请解释对象引用为什么会共享，并给我一个观察实验。",
        "current_file": {"path": "lesson.py", "content": "grid = [[0] * 2] * 2\n"},
        "response_language": "zh-CN",
        "coach_context": {"current_focus": "Read a function contract at a call site."},
    }
    if streaming:
        events = [event async for event in service.coaching_reply_agentic_stream(**kwargs)]
        result = events[-1]
    else:
        result = await service.coaching_reply_agentic(**kwargs)
    assert result["stop_reason"] == "completed"
    assert result.get("fell_back", False) is False
    assert "grid[0] is grid[1]" in result["content"]
    assert result["next_step"] == action
    assert "函数名" not in str(result)
    assert service.consume_last_reply_failure() is None
