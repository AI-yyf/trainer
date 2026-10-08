from __future__ import annotations

from app.core.models import UserProfile
from app.llm.provider_service import ProviderService


def _profile() -> UserProfile:
    return UserProfile(
        long_term_goal="Build reliable developer tools",
        background="Intermediate Python developer",
        weekly_hours=6,
        teaching_style="guided",
        answer_policy="guided",
        preferred_libraries=["pytest"],
    )


def test_current_file_answer_is_not_replaced_by_active_resources_lane() -> None:
    service = ProviderService(api_key="sk-test-key")
    reply = service.finalize_coaching_reply(
        (
            "`parsePayload` returns None because its empty-header branch treats an empty string as "
            "missing. In `parser.py`, inspect that branch before changing the fallback."
        ),
        profile=_profile(),
        message="Why does `parsePayload` return None when the `X-Mode` header is empty?",
        current_file={
            "path": "src/parser.py",
            "language_id": "python",
            "content": "def parsePayload(header):\n    return None if not header else header\n",
        },
        response_language="en-US",
        coach_context={
            "active_view": "resources",
            "current_focus": "Sort imported reference material into the library.",
        },
    )

    assert "parsePayload" in reply
    assert "empty-header branch" in reply
    assert "Resources lane" not in reply


def test_chinese_agent_finalize_reanchors_generic_summary_and_next_step() -> None:
    service = ProviderService(api_key="sk-test-key")
    final_event = service._visible_agentic_final_event(
        {
            "type": "final",
            "content": "这一轮我先在 Resources 视图里用一个更小的资料动作把它接住。",
            "summary": "当前先留在 Resources 这条主线上。",
            "next_step": "先定位最相关的资料，再整理进 sources、knowledge、cards。",
            "stop_reason": "coach_finalize",
        },
        profile=_profile(),
        message="请解释为什么 `renderCard` 遇到空标题时显示占位内容？",
        current_file={
            "path": "src/Card.tsx",
            "language_id": "typescriptreact",
            "content": "export function renderCard(title: string) { return title || 'Untitled'; }",
        },
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={
            "active_view": "resources",
            "current_focus": "整理当前资料库。",
        },
        tool_events=[],
    )

    assert "renderCard" in str(final_event["content"])
    assert "空标题" in str(final_event["content"])
    assert "Resources 视图" not in str(final_event["content"])
    assert "renderCard" in str(final_event["summary"])
    assert "renderCard" in str(final_event["next_step"])
    assert "sources、knowledge、cards" not in str(final_event["next_step"])


def test_traceback_question_preserves_an_explanation_grounded_in_current_code_symbols() -> None:
    service = ProviderService(api_key="sk-test-key")
    model_reply = (
        "`append_item` 的默认参数在函数定义时创建一次，后续调用共享同一个列表。"
        "在调试时打印每次调用前后的 items，可以观察对象是否被复用。\n\n"
        "下一步：比较两次调用前后列表的内容和对象身份。"
    )
    reply = service.finalize_coaching_reply(
        model_reply,
        profile=_profile(),
        message="lesson.py 报 AssertionError，请解释原因，然后给我一个最小实验。",
        current_file={
            "path": "lesson.py", "language_id": "python",
            "content": "def append_item(value, items=[]):\n    items.append(value)\n    return items\n",
        },
        response_language="zh-CN",
        coach_context={"active_view": "coach", "current_focus": "整理旧资料库"},
    )
    assert "默认参数在函数定义时创建一次" in reply
    assert "观察对象是否被复用" in reply
    assert "我先回到你刚才问的" not in reply


def test_common_code_vocabulary_does_not_prove_an_unrequested_workflow() -> None:
    from app.llm.coaching_replies import _reply_needs_current_request_reanchor

    assert _reply_needs_current_request_reanchor(
        "默认参数在函数定义时创建，调试时可以比较两次调用使用的对象身份。",
        message="lesson.py 报 AssertionError，为什么列表被共享？",
        current_file={"path": "lesson.py", "content": ""},
        coach_context={"active_view": "coach"},
    ) is False


def test_explicit_foreign_workflow_still_reanchors_without_a_current_code_symbol() -> None:
    from app.llm.coaching_replies import _reply_needs_current_request_reanchor

    assert _reply_needs_current_request_reanchor(
        "First keep the remote workspace boundary stable and inspect credential mode.",
        message="lesson.py 报 AssertionError，为什么列表被共享？",
        current_file={"path": "lesson.py", "content": "def append_item(value): return value"},
        coach_context={"active_view": "coach"},
    ) is True
