from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.training_return_feedback import completed_return_feedback
from app.llm.coaching_patches import (
    _maybe_auto_verify_practice_current_file,
    _practice_verification_requested_or_claimed,
)
from app.llm.coaching_replies import _agentic_practice_completion_guard
from app.training.attempt_store import AttemptStore, content_hash


def _feedback(tmp_path):
    path = str(tmp_path / "lesson.py")
    content = "assert ([1], 2)[0] == [1]\n"
    store = AttemptStore(tmp_path / "trainer.sqlite3")
    attempt = store.start_attempt(workspace_id="context-one", card_id="card-one", file_path=path, file_hash=content_hash(content))
    store.record_evidence(attempt_id=attempt["attempt_id"], caller_workspace_id="context-one", artifact_hash=content_hash(content), result="passed", trust_level="controlled_check")
    store.close_attempt(attempt["attempt_id"], workspace_id="context-one")
    handoff = {"card_id": "card-one", "card_title": "嵌套元组边界", "status": "completed", "learning_phase": "return", "verification_state": "verified", "returned_at": "2026-10-02T00:00:00Z", "reflection": "槽位不可写，内部列表可变。"}
    memory = SimpleNamespace(workspace={"latest_training_handoff": handoff})
    runtime = SimpleNamespace(memory_service=SimpleNamespace(snapshot=lambda _: memory), attempt_store=store)
    request = SimpleNamespace(message="请评估我在「嵌套元组边界」中的提交和复盘。", current_file=SimpleNamespace(path=path, content=content))
    return runtime, request, handoff, attempt


def test_feedback_reuses_only_same_file_current_controlled_returned_evidence(tmp_path):
    runtime, request, _, _ = _feedback(tmp_path)
    assert completed_return_feedback(runtime, "context-one", request)
    assert not completed_return_feedback(runtime, "context-other", request)
    request.current_file.content += "# edited\n"
    assert not completed_return_feedback(runtime, "context-one", request)


@pytest.mark.parametrize("result", [
    "VS Code Testing 已重新执行 Ruff、Pyright、pytest、training-acceptance，4/4 通过。",
    "已经重新验证这份提交。", "不要重新执行，只评估复盘。",
    "I already rerun the checks. Please review the reflection.",
])
def test_return_bridge_past_checks_are_not_new_execution_requests(tmp_path, result):
    runtime, request, _, _ = _feedback(tmp_path)
    request.message += result
    assert completed_return_feedback(runtime, "context-one", request)
    request.message += "请重新验证。"
    assert not completed_return_feedback(runtime, "context-one", request)


@pytest.mark.parametrize("change", ["other_file", "other_card", "other_message", "rerun", "unreturned", "unreflected", "unverified", "self_reported", "deleted"])
def test_incomplete_or_unrelated_feedback_cannot_bypass_verification(tmp_path, change):
    runtime, request, handoff, attempt = _feedback(tmp_path)
    if change == "other_file":
        request.current_file.path += ".other"
    elif change == "other_card":
        handoff["card_id"] = "another-card"
    elif change == "other_message":
        request.message = "评估另外一张卡。"
    elif change == "rerun":
        request.message += "请重新验证。"
    elif change == "unreturned":
        handoff["status"] = "active"
    elif change == "unreflected":
        handoff["reflection"] = ""
    elif change == "unverified":
        handoff["verification_state"] = "unverified"
    else:
        evidence = runtime.attempt_store.list_evidence(attempt["attempt_id"])[0]
        evidence["trust_level" if change == "self_reported" else "source_deleted"] = "self_reported" if change == "self_reported" else True
        runtime.attempt_store._write_evidence_row(evidence["evidence_id"], evidence)
    assert not completed_return_feedback(runtime, "context-one", request)


@pytest.mark.parametrize("message", ["为什么元组内部的列表可以修改？", "Explain the current function.", "给我一个概念例子。"])
def test_plain_questions_do_not_always_request_execution(message):
    assert not _practice_verification_requested_or_claimed(message=message, content="先区分容器和它引用的对象。")
    assert not _practice_verification_requested_or_claimed(
        message=message,
        content="下一步，你可以做一个最小实验来验证这个原因。",
    )


@pytest.mark.parametrize("message", ["请核验我的训练提交。", "重新验证这张卡。", "Verify my practice."])
def test_explicit_execution_request_is_retained(message):
    assert _practice_verification_requested_or_claimed(message=message, content="")


@pytest.mark.asyncio
async def test_completed_return_feedback_does_not_auto_execute_or_reopen_practice():
    registry = MagicMock(invoke=AsyncMock())
    current_file = {"path": "/lesson.py", "content": "assert True"}
    context = {"completed_training_return_feedback": True, "exercise_prompt": {"success_signal": "assert True"}}
    arguments = dict(message="请评估训练提交。", content="这张卡的验证和复盘已通过。", current_file=current_file, coach_context=context)
    assert await _maybe_auto_verify_practice_current_file(registry=registry, context=SimpleNamespace(), tool_events=[], **arguments) == []
    registry.invoke.assert_not_called()
    assert _agentic_practice_completion_guard(tool_events=[], response_language="zh-CN", **arguments) is None
    failed = [{"type": "tool_result", "name": "verify_practice_current_file", "result": {"passed": False, "summary": "Current check failed"}}]
    assert _agentic_practice_completion_guard(tool_events=failed, response_language="zh-CN", **arguments) is not None


def test_verified_return_authority_survives_minimal_prompt_context():
    from app.core.models import UserProfile
    from app.llm.prompts import build_coaching_system_prompt

    profile = UserProfile()
    context = {"context_tier": "minimal", "completed_training_return_feedback": True}
    prompt = build_coaching_system_prompt(profile, message="请评估这次复盘", coach_context=context)
    assert "current server-controlled evidence" in prompt
    assert "not an unverified learner claim" in prompt
    assert "Plan adoption is a separate explicit action" in prompt
    for context in ({"context_tier": "minimal"}, {"completed_training_return_feedback": False}):
        prompt = build_coaching_system_prompt(profile, message="我说已经通过", coach_context=context)
        assert "Current returned training artifact:" not in prompt
