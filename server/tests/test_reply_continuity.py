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


@pytest.mark.parametrize("label", [
    "第一步", "第一歩", "First step", "Primer paso", "Première étape",
    "Erster Schritt", "最初の一歩", "첫 번째 단계", "Primeiro passo",
])
def test_first_step_labels_are_read_as_reply_actions(label: str) -> None:
    """Coaches label the opening move `第一步`/`First step` — the same labelled
    action family as `下一步`, and the reply's own concrete first move."""
    assert visible_next_step(f"说明。\n\n## {label}：跑通一个并发计时实验\n\n新建 step1.py。") == (
        "跑通一个并发计时实验"
    )
    assert visible_next_step(f"**{label}**: run step1.py and paste the output") == (
        "run step1.py and paste the output"
    )


def test_opening_praise_line_is_never_read_as_an_action() -> None:
    """A line merely containing `第一步` mid-sentence is prose, not a label."""
    assert visible_next_step("好的，这是一个最小、可验证的第一步：具体见下。") == ""


def test_parenthetical_qualifier_between_label_and_colon_is_accepted() -> None:
    """`**第一步（今天 10 分钟）：让两个协程并发跑起来**` — real glm-5.3 reply
    shape from the T-0027 real-provider samples."""
    assert visible_next_step(
        "**第一步（今天 10 分钟）：让两个协程并发跑起来，并验证并发真的发生了。**\n\n"
        "新建一个文件 `step1_async.py`。",
    ) == "让两个协程并发跑起来，并验证并发真的发生了。"
    assert visible_next_step("Intro.\n\n**First step (10 min)**: run the probe") == "run the probe"


def test_label_heading_with_short_suffix_reads_following_line() -> None:
    """T-0029: `## 第一步代码` (label + short suffix noun) heads a section
    whose next line carries the action — real glm-5.3 reply shape from the
    T-0029 real-provider sample t0027-final-5."""
    assert visible_next_step(
        "好的！学 asyncio 的经典“最小第一步”是：**运行一个会并发 sleep 的协程**。\n\n"
        "## 第一步代码\n\n"
        "新建 `step1_asyncio.py`，只写这些：",
    ) == "新建 `step1_asyncio.py`，只写这些："
    assert visible_next_step(
        "Intro.\n\n### Next steps\n\nRun the two-call experiment.",
    ) == "Run the two-call experiment."
    # A short suffix outside the noun whitelist is prose, not a label.
    assert visible_next_step("下一步下雨了\n\n新建 step1.py") == ""


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


def test_past_tense_parenthetical_label_is_a_recap_not_an_action() -> None:
    """T-0036: `下一步（已完成）：跑通登录页` reports what the learner already
    did — it must never be read as the next move."""
    assert visible_next_step(
        " Recap of the last round.\n\n下一步（已完成）：跑通登录页\n\n先跑一次测试。",
    ) == ""
    # A forward-looking parenthetical still works.
    assert visible_next_step("Intro.\n\n下一步（今天 10 分钟）：跑通一个并发计时实验") == (
        "跑通一个并发计时实验"
    )


def test_recap_paren_variants_are_never_read_as_actions() -> None:
    """Deferred-P2 closure: `（已经完成）/（已解决）/（已验证）` are recap
    qualifiers just like `（已完成）` — a past-tense label never supplies the
    learner's next move."""
    assert visible_next_step("Recap.\n\n下一步（已经完成）：跑通登录页\n\n先跑一次测试。") == ""
    assert visible_next_step("Recap.\n\n**Next step (resolved)**: migrate the config\n\nRun the probe.") == ""
