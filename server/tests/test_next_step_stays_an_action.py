"""The stored "next step" is an action the learner was told to take — never a fragment of the reply's
opening prose and never a step left over from an earlier turn.

Found with a real model on 2026-11-28: a reply that explains an error in sections (``## 发生了什么``,
``## 为什么会这样设计``, two code blocks) carried no ``下一步：`` label, so both continuity builders
fell back to the first 120 characters of the reply. ``next_step`` became
``## 发生了什么 `get(d, k)` 里执行的是 `d[k]`…`` (a heading plus the start of an explanation), and it
was fed back into the next turn's prompt as the step to continue. A bare "你好" then continued that
fragment: it re-read the file and produced a patch.

Extraction order is now: the reply's labelled action, then structured hints and thread state, then the
reply's closing instruction when it reads as one, then the neutral default. The reply's opening prose
is never used, and a label a model wraps in backticks or quotes is still read.
"""

from __future__ import annotations

import re

from app.core.model_domains.foundations_and_provider import ProviderConfig, UserProfile
from app.llm.agent_loop import _build_completion_continuity
from app.llm.coaching_replies import _agentic_completion_continuity
from app.llm.prompt_domains.scenario_and_context_blocks import build_coaching_system_prompt
from app.llm.provider_service import ProviderService
from app.llm.reply_continuity import closing_action_step, visible_next_step

# Excerpt of a real MiniMax-M2.7 reply (2026-11-28) to "这段为什么会报 KeyError？"; structure kept,
# middle shortened. The reply closes with an instruction that carries no "下一步" label.
REAL_SECTIONED_REPLY = """## 发生了什么

`get(d, k)` 里执行的是 `d[k]`，这是字典的**下标访问**语义：Python 要求 key 必须存在，否则立刻抛出 `KeyError`。你的 `config` 只有两个键：

```python
{"host": "localhost", "port": 8000}
```

## 为什么会这样设计

`d[k]` 表达的是「这个键**一定**在这里，我需要它的值」。

---

你现在知道：报错来自下标访问的严格契约，而下一步要验证的是--`retries` 到底是「必需但配置漏了」还是「本来就可选」，改哪一边取决于这个。

先跑一次 `python app.py` 确认前一行仍输出 `8000`、异常只在第二行抛出，就证明问题只在 `get` 的第二个调用点上。
"""

REAL_QUESTIONING_REPLY = """好，那我先闭嘴。为了让你说得准，我把要看的点拆成几个问题--只是问题，答案我不给，你对着 `payments.py` 逐条回答。

1. `charge` 往 `CHARGED` 里 append 一条记录就返回。这个函数在什么情况下会抛 `TimeoutError`？

2. `range(3)` 里的 3 是谁定的？它在 `app.py` 的 `config` 里有没有对应项？

你说完我再对：哪些判断成立，哪些是漏掉的，为什么漏掉的那几个在真实支付系统里会咬人。

顺序上别跳：先说 1、2、3 的结论，再谈第 4 条你打算怎么定义幂等。
"""

CLOSING_ACTION = (
    "先跑一次 `python app.py` 确认前一行仍输出 `8000`、异常只在第二行抛出，"
    "就证明问题只在 `get` 的第二个调用点上。"
)


def _is_reply_fragment(text: str) -> bool:
    return text.startswith("#") or "```" in text or text.startswith("## 发生了什么")


def test_agent_loop_continuity_does_not_store_the_reply_head() -> None:
    _summary, next_step = _build_completion_continuity(
        REAL_SECTIONED_REPLY, context=None, response_language="zh-CN"
    )

    assert not _is_reply_fragment(next_step), next_step
    assert next_step == CLOSING_ACTION


def test_agent_loop_continuity_reads_the_closing_instruction_of_a_questioning_reply() -> None:
    _summary, next_step = _build_completion_continuity(
        REAL_QUESTIONING_REPLY, context=None, response_language="zh-CN"
    )

    assert next_step == "顺序上别跳：先说 1、2、3 的结论，再谈第 4 条你打算怎么定义幂等。"


def test_a_thread_hint_outranks_an_unlabelled_closing_sentence() -> None:
    """The thread carries a concrete server-side step; a generic closing sentence does not replace it."""
    _summary, next_step = _agentic_completion_continuity(
        "hi",
        current_file=None,
        coach_context={"next_step_hint": "Patch the smallest failing branch first"},
        response_language="en-US",
        content="Keep the next move tiny and verify it immediately.",
    )

    assert next_step == "Patch the smallest failing branch first"


def test_the_labelled_action_outranks_a_stale_thread_step() -> None:
    reply = REAL_SECTIONED_REPLY.replace(
        "先跑一次 `python app.py`", "下一步：先跑一次 `python app.py`"
    )
    _summary, next_step = _agentic_completion_continuity(
        "这段为什么会报 KeyError？",
        current_file=None,
        coach_context={"thread_next_step": "上一轮留下的旧步骤", "resume_hint": "更早的提示"},
        response_language="zh-CN",
        content=reply,
    )

    assert next_step == "先跑一次 `python app.py` 确认前一行仍输出 `8000`、异常只在第二行抛出，就证明问题只在 `get` 的第二个调用点上。"


def test_a_label_wrapped_in_backticks_is_still_read() -> None:
    """A real model wrote the label as `Next step:` inside a Chinese reply."""
    reply = "原因在 `d[k]` 的严格查找。\n\n`Next step:` 在 `app.py` 的 `get` 里加一个可选的 `default` 参数，然后运行 `python app.py`。"

    assert visible_next_step(reply) == "在 `app.py` 的 `get` 里加一个可选的 `default` 参数，然后运行 `python app.py`。"
    assert _build_completion_continuity(reply, context=None, response_language="zh-CN")[1] == (
        "在 `app.py` 的 `get` 里加一个可选的 `default` 参数，然后运行 `python app.py`。"
    )


def test_agentic_continuity_without_any_action_falls_back_to_the_neutral_default() -> None:
    lecture = "## 原理\n\n`d[k]` 是下标访问。\n\n```python\nd = {}\nprint(d['a'])\n```\n\n## 小结\n\n这意味着缺键被当作程序员错误。\n"

    loop_step = _build_completion_continuity(lecture, context=None, response_language="zh-CN")[1]
    agentic_step = _agentic_completion_continuity(
        "讲讲原理", current_file=None, coach_context={}, response_language="zh-CN", content=lecture
    )[1]

    for step in (loop_step, agentic_step):
        assert not _is_reply_fragment(step), step
        assert "`d[k]`" not in step, step


def test_a_labelled_action_still_wins_over_the_closing_paragraph() -> None:
    reply = "先别急着改代码。\n\n**下一步**：把 `get(config, \"retries\")` 换成 `config.get(\"retries\", 3)`，再运行一次。\n\n改完后把输出贴给我。"

    assert visible_next_step(reply) == '把 `get(config, "retries")` 换成 `config.get("retries", 3)`，再运行一次。'
    assert closing_action_step(reply) == "改完后把输出贴给我。"
    assert _build_completion_continuity(reply, context=None, response_language="zh-CN")[1] == (
        '把 `get(config, "retries")` 换成 `config.get("retries", 3)`，再运行一次。'
    )


def test_closing_action_step_reads_an_english_instruction() -> None:
    reply = "## What happened\n\n`d[k]` is a strict lookup.\n\n```python\nd = {\"host\": \"localhost\"}\n```\n\nRun `python app.py` once and confirm only the second call raises.\n"

    assert closing_action_step(reply) == "Run `python app.py` once and confirm only the second call raises."


def test_closing_action_step_refuses_explanatory_closings() -> None:
    assert closing_action_step("`d[k]` 抛出 `KeyError` 是因为键不存在。") == ""
    assert closing_action_step("## 小结\n\n这意味着缺键被当作程序员错误。") == ""
    assert closing_action_step("## 怎么改\n\n```python\nreturn d.get(k, None)\n```") == ""


def test_every_coaching_prompt_asks_for_one_labelled_closing_action() -> None:
    profile = UserProfile(
        long_term_goal="搞懂 Python 基础",
        background="初学者",
        weekly_hours=5,
        teaching_style="hands-on",
        answer_policy="guided",
    )

    for language in ("zh-CN", "en-US"):
        prompt = build_coaching_system_prompt(profile, language, "guided", agent_loop_enabled=True)

        assert "下一步：" in prompt or "Next step:" in prompt, language


def test_no_server_sentence_is_appended_after_the_coachs_own_labelled_action() -> None:
    """Seen with a real model: the coach's "下一步：…" line was followed by a server-composed
    "这一步算过的信号是：回到最近这一轮教练主线…" — a thread reminder, not a signal, riding on the
    coach's words. A reply that ends with its own action is left as it is."""
    from app.llm.coaching_reply_drafts import _compose_success_signal_patch

    reply = "提示：在 `refund()` 里，先用同一个 `order_id` 查一次。\n\n下一步：在 refund 里补上判断并让重复调用只记一笔"

    assert (
        _compose_success_signal_patch(
            reply=reply,
            exercise_prompt={"success_signal": "回到最近这一轮教练主线，先把这一步验证掉。"},
            chinese=True,
        )
        == ""
    )
    # A reply without an action of its own still gets the signal.
    assert (
        _compose_success_signal_patch(
            reply="提示：在 `refund()` 里，先用同一个 `order_id` 查一次。",
            exercise_prompt={"success_signal": "重复调用只记一笔"},
            chinese=True,
        )
        == "这一步算过的信号是：重复调用只记一笔。"
    )


def _review_context() -> dict[str, object]:
    return {
        "scenario": "review",
        "failing_checks": ["tests/test_retry.py"],
        "exercise_prompt": {"prompt": "Restore the first failing check.", "success_signal": "The check passes."},
    }


def _service() -> ProviderService:
    return ProviderService(
        config=ProviderConfig(
            name="postprocess",
            baseUrl="https://api.openai.com/v1",
            apiKeyRef="trainer.test",
            model="gpt-4o-mini",
        ),
        api_key="sk-test",
    )


def test_no_server_sentence_of_any_kind_follows_the_coachs_own_labelled_action() -> None:
    """Seen with a real model: "下一步：在 `app.py` 改用…" was followed by the server's "先别扩范围。
    先恢复一条最小反馈链…". Every server-composed addition now stops before a reply that ends
    with the coach's own action."""
    service = _service()
    reply = "现在入口已能读取 `port`，但缺少 `retries`。\n\n下一步：在 `app.py` 改用带回退值的字典读取，再运行。"

    assert (
        service._postprocess_coaching_reply(
            reply,
            profile=UserProfile(long_term_goal="x", weekly_hours=4, teaching_style="guided", answer_policy="guided"),
            message="然后呢？",
            current_file={"path": "app.py", "language_id": "python", "content": "print(1)"},
            response_language="zh-CN",
            answer_mode="guided",
            coach_context=_review_context(),
        )
        == reply
    )
    # The same context still adds its guidance to a reply that has no action of its own.
    unlabelled = "现在入口已能读取 `port`，但缺少 `retries`。"
    patched = service._postprocess_coaching_reply(
        unlabelled,
        profile=UserProfile(long_term_goal="x", weekly_hours=4, teaching_style="guided", answer_policy="guided"),
        message="然后呢？",
        current_file={"path": "app.py", "language_id": "python", "content": "print(1)"},
        response_language="zh-CN",
        answer_mode="guided",
        coach_context=_review_context(),
    )
    assert patched.startswith(unlabelled)
    assert patched != unlabelled


def test_a_review_reminder_is_not_passed_off_as_the_signal_of_success() -> None:
    """Seen with a real model: a one-line hint was followed by "这一步算过的信号是：回到最近这一轮
    教练主线，先把这一步验证掉：…" — the review scheduler's reminder, dressed as a verification
    signal. The scheduler's sentences name what to redo; a signal names what will be observed."""
    from app.llm.coaching_reply_drafts import _compose_success_signal_patch

    hint = "提示：给每次退款请求一个幂等键，把键到结果的对应记在独立的表里。"
    for reminder in (
        "回到最近这一轮教练主线，先把这一步验证掉：在 charge 里让 append 之后抛 TimeoutError。",
        "回到上一轮教练已经压好的这一步，先做完或验证它：补上 retries 配置。",
        "Return to the latest coach turn and verify this next move: add the retries key.",
    ):
        patch = _compose_success_signal_patch(
            reply=hint, exercise_prompt={"success_signal": reminder}, chinese=True
        )
        assert patch == "", reminder
    assert (
        _compose_success_signal_patch(
            reply=hint, exercise_prompt={"success_signal": "连续调用两次 refund 后 REFUNDED 只有一条"}, chinese=True
        )
        == "这一步算过的信号是：连续调用两次 refund 后 REFUNDED 只有一条。"
    )


def test_a_pronoun_fragment_is_not_an_anchor_of_the_learner_s_request() -> None:
    """Seen with a real model: the stored next step read "围绕 `refunds.py`、「我在」，先在 …" —
    "我在" is the start of "我在 refunds.py 里也碰到…", not a subject."""
    from app.llm.coaching_replies import _request_relevance_anchor_terms

    terms = _request_relevance_anchor_terms(
        "我在 refunds.py 里也碰到类似的超时重试问题，这次我想自己修，只给我一句提示就好。",
        current_file={"path": "/repo/refunds.py"},
    )

    assert "refunds.py" in terms
    assert all(not re.match(r"^(我|你|他|她|它|我们|你们|在|的)", term) for term in terms), terms
