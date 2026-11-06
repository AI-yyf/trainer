"""Phase 4 — coach_language_alignment 拆分后的独立行为锁."""

from __future__ import annotations

from app.api.coach_language_alignment import (
    ensure_coach_turn_payload,
    language_aligned_coaching_state_payload,
    language_aligned_context_list,
    language_aligned_context_text,
    language_aligned_flat_payload,
    language_aligned_memory_payload,
    language_aligned_review_rhythm,
    language_aligned_thread_payload,
    localize_known_context_phrases,
)


def test_localize_known_context_phrases_zh() -> None:
    assert localize_known_context_phrases("VS Code debug loop", "zh-CN") == "VS Code 调试闭环"
    assert localize_known_context_phrases("debug loop", "zh-CN") == "调试闭环"
    assert localize_known_context_phrases("plain english", "en-US") == "plain english"
    lane = localize_known_context_phrases(
        "Continue 'VS Code debug loop' and do not open a new lane before this next move lands: run pytest",
        "zh-CN",
    )
    assert "调试闭环" in lane and "run pytest" in lane


def test_context_text_language_guards() -> None:
    # Chinese learner with mojibake → dropped.
    assert language_aligned_context_text("涓嬩竴姝", "zh-CN") == ""
    # English learner with CJK → keep only latin fragments.
    aligned = language_aligned_context_text("先看门户 then run the test", "en-US")
    assert "then run the test" in aligned
    assert "先看" not in aligned
    # Non-string values → empty.
    assert language_aligned_context_text(None, "en-US") == ""


def test_context_list_dedupes_and_limits() -> None:
    assert language_aligned_context_list(["a", "a", "b"], "en-US") == ["a", "b"]
    assert language_aligned_context_list(["a", "b", "c"], "en-US", limit=2) == ["a", "b"]
    assert language_aligned_context_list("not-a-list", "en-US") == []


def test_flat_payload_aligns_strings_and_lists_only() -> None:
    aligned = language_aligned_flat_payload(
        {
            "summary": "VS Code debug loop",
            "steps": ["debug loop", "remote workspace boundary", "x"],
            "nested": [{"summary": "untouched"}],
        },
        "zh-CN",
        list_limit=2,
    )
    assert aligned is not None
    assert aligned["summary"] == "VS Code 调试闭环"
    assert aligned["steps"] == ["调试闭环", "远程工作区边界"]
    assert aligned["nested"] == [{"summary": "untouched"}]


def test_thread_and_memory_payloads_align_nested_fields() -> None:
    thread = language_aligned_thread_payload(
        {
            "scenario": "debug_loop",
            "summary": "VS Code debug loop",
            "evidence": ["e1", "e2", "e3", "e4", "e5"],
        },
        "zh-CN",
    )
    assert thread is not None
    assert thread["scenario"] == "debug_loop"
    assert thread["summary"] == "VS Code 调试闭环"
    assert len(thread["evidence"]) == 4

    memory = language_aligned_memory_payload(
        {
            "current_focus": "debug loop",
            "active_thread": {"summary": "VS Code debug loop"},
        },
        "zh-CN",
    )
    assert memory is not None
    assert memory["current_focus"] == "调试闭环"
    assert memory["active_thread"]["summary"] == "VS Code 调试闭环"


def test_coaching_state_payload_and_review_rhythm() -> None:
    state = language_aligned_coaching_state_payload(
        {"summary": "debug loop", "next_step": "plain step"},
        "zh-CN",
    )
    assert state is not None
    assert state["summary"] == "调试闭环"
    assert state["next_step"] == "plain step"
    assert language_aligned_review_rhythm("", "zh-CN") is None
    assert language_aligned_review_rhythm("debug loop", "zh-CN") == "调试闭环"


def test_ensure_coach_turn_payload_fallback() -> None:
    fallback = {"scenario": "general"}
    assert ensure_coach_turn_payload(None, fallback) is fallback
    assert ensure_coach_turn_payload({"scenario": "x"}, fallback) == {"scenario": "x"}
