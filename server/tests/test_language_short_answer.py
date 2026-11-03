from __future__ import annotations

from app.llm.provider.text import _mixed_script_reply_corruption_detail


def test_short_english_technical_answer_is_not_language_corruption() -> None:
    detail = _mixed_script_reply_corruption_detail(
        "False. The lock is already held.",
        message="threading.Lock.acquire(blocking=False) 在锁已被占用时返回什么？",
        response_language="zh-CN",
    )
    assert detail is None


def test_prose_length_english_is_still_language_corruption() -> None:
    detail = _mixed_script_reply_corruption_detail(
        "First identify the host that owns the workspace, then verify one real path.",
        message="请解释 VS Code remote workspace boundary。",
        response_language="zh-CN",
    )
    assert detail is not None
    assert "English-only visible prose" in detail
