"""Phase 4 — coach_text_sanitizer 拆分后的独立行为锁 (原 routers.py 闭包逻辑)."""

from __future__ import annotations

from app.api.coach_text_sanitizer import (
    normalize_visible_coach_text,
    repair_legacy_assistant_messages,
    sanitize_visible_coach_payload,
    sanitize_visible_coach_reply_content,
    strip_visible_next_step_prefix,
)
from app.core.models import ChatMessage, WorkbenchSnapshot


def test_normalize_strips_meta_labels_and_prefixes() -> None:
    assert normalize_visible_coach_text("Current focus: read the module map first") == (
        "Read the module map first"
    )
    assert normalize_visible_coach_text("general coaching") == ""
    assert normalize_visible_coach_text("当前聚焦：先看入口文件") == "先看入口文件"


def test_sanitize_reply_drops_internal_markers() -> None:
    raw = (
        "<system-reminder>workspace file snapshot</system-reminder>\n\n"
        "先看入口文件，再跑一个最小验证。"
    )
    assert sanitize_visible_coach_reply_content(raw, "zh-CN") == "先看入口文件，再跑一个最小验证。"
    mojibake = sanitize_visible_coach_reply_content("涓嬩竴姝ユ槸杩欐牱", "zh-CN")
    assert "再发一次" in mojibake or "send the same question" in mojibake


def test_strip_next_step_prefix_both_languages() -> None:
    assert strip_visible_next_step_prefix("Next step: run pytest -q") == "run pytest -q"
    assert strip_visible_next_step_prefix("下一步：运行 pytest") == "运行 pytest"


def test_payload_sanitizer_recurses_into_visible_fields() -> None:
    payload = {"summary": "Current focus: keep one move", "nested": [{"next_step": "Current focus: verify"}]}
    cleaned = sanitize_visible_coach_payload(payload)
    assert cleaned["summary"] == "Keep one move"
    assert cleaned["nested"][0]["next_step"] == "Verify"


def test_repair_legacy_assistant_messages_rewrites_history() -> None:
    snapshot = WorkbenchSnapshot(
        messages=[
            ChatMessage(role="user", content="current focus: mine"),
            ChatMessage(
                role="assistant",
                content="<system-reminder>workspace file snapshot</system-reminder>\n\nreal answer",
            ),
        ],
    )
    repaired = repair_legacy_assistant_messages(snapshot, "en-US")
    assert repaired is True
    assert snapshot.messages[1].content == "real answer"
    assert snapshot.messages[0].content == "current focus: mine"  # user text untouched
