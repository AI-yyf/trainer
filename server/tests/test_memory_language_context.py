from __future__ import annotations

from pathlib import Path

from app.db.repository import TrainerRepository
from app.memory.service import MemoryService


def contains_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def test_workspace_language_keeps_memory_copy_in_zh_cn_even_when_summary_is_english() -> None:
    database_path = Path(".tmp-test/memory-language-context.db")
    if database_path.exists():
        database_path.unlink()

    repository = TrainerRepository(database_path)
    service = MemoryService(repository)
    workspace_id = "workspace-memory-language-context"

    service.record_turn_memory(
        workspace_id=workspace_id,
        session_id="session-memory-language-context",
        scenario="coach",
        focus_area="remote workspace boundary",
        summary="Keep the next slice small and verifiable.",
        next_step="Patch one remote workspace edge case first.",
        response_language="zh-CN",
        answer_mode="guided",
    )

    snapshot = service.snapshot(workspace_id)

    assert contains_chinese(snapshot.current_focus)
    assert snapshot.teaching_observations
    assert any(contains_chinese(observation) for observation in snapshot.teaching_observations)


def test_workspace_language_localizes_generic_focus_labels_in_current_focus() -> None:
    database_path = Path(".tmp-test/memory-language-generic-focus.db")
    if database_path.exists():
        database_path.unlink()

    repository = TrainerRepository(database_path)
    service = MemoryService(repository)
    workspace_id = "workspace-memory-generic-focus"

    service.record_turn_memory(
        workspace_id=workspace_id,
        session_id="session-memory-generic-focus",
        scenario="idea_implementation",
        focus_area="implementation",
        summary="Keep the recovery lane narrow and honest.",
        next_step="Switch the provider or gateway before resuming the lesson.",
        response_language="zh-CN",
        answer_mode="guided",
    )

    snapshot = service.snapshot(workspace_id)

    assert snapshot.active_thread.focus_area == "implementation"
    assert "implementation" not in snapshot.current_focus.lower()
    assert contains_chinese(snapshot.current_focus)


def test_workspace_language_keeps_review_rhythm_in_en_us_even_when_turn_context_is_chinese() -> None:
    database_path = Path(".tmp-test/memory-language-review-rhythm-en.db")
    if database_path.exists():
        database_path.unlink()

    repository = TrainerRepository(database_path)
    service = MemoryService(repository)
    workspace_id = "workspace-memory-review-rhythm-en"

    service.record_turn_memory(
        workspace_id=workspace_id,
        session_id="session-memory-review-rhythm-en",
        scenario="review",
        focus_area="dependency injection",
        summary="先围绕 dependency injection 保持这一条主线。",
        next_step="先把 provider branch 补成一个可验证的小改动。",
        response_language="en-US",
        answer_mode="guided",
        review_note="这里的 provider branch 还没有被验证。",
    )
    structured = service.structured_for_workspace(workspace_id)
    structured.record_weakness(
        "dependency injection",
        "这里的 provider branch 还没有被验证。",
        severity=3,
        review_after_days=0,
        context="server/app/main.py",
    )

    snapshot = service.snapshot(workspace_id)

    assert snapshot.review_rhythm.startswith("Review rhythm:")
    assert not contains_chinese(snapshot.review_rhythm)
    assert snapshot.due_reviews
    assert snapshot.due_reviews[0].task_hint
    assert not contains_chinese(snapshot.due_reviews[0].task_hint)
