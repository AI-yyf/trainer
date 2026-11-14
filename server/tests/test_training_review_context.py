import copy

import pytest

from app.core.models import MemorySnapshot, ReviewArtifactSnapshot
from app.llm.training_review_context import active_training_review, apply_training_review_context


def review_memory(status="active", mode="review_queue"):
    return MemorySnapshot(workspace={"latest_training_submode": mode}, review_artifact=ReviewArtifactSnapshot(
        id="review-one", title="复习：元组槽位", focus_area="元组槽位", status=status,
        summary="解释槽位与引用对象的区别。", guardrail="先闭卷，再核对例子。",
        verified_result="我的概念复述。" if status == "resolved" else "",
    ))


@pytest.mark.parametrize("status", ["active", "resolved"])
@pytest.mark.parametrize("mode", ["review", "review_queue", "review-queue"])
def test_review_feedback_does_not_inherit_old_practice_contract(status, mode):
    context = {"current_focus": "旧实现", "exercise_prompt": {"acceptance_criteria": ["旧断言"]},
               "review_rhythm": "旧断言", "weak_spots": ["旧断言"],
               "plan_runtime_recovery": {"current_step": "旧断言"},
               "active_training_card_routing": {"selected_card": {"title": "旧卡"}},
               "memory": {"review_rhythm": "旧断言", "weaknesses": ["旧断言"],
                          "workspace": {"latest_training_handoff": {"status": "completed"}},
                          "training_event_ledger": [{"verification_steps": ["旧断言"]}]}}
    before = copy.deepcopy(context)
    result = apply_training_review_context(context, review_memory(status, mode), "training")
    assert result["review_artifact"]["id"] == "review-one"
    assert result["review_evidence_scope"] == "self_reported_recall"
    assert result["current_focus"] == "元组槽位"
    assert result["exercise_prompt"] is None
    assert result["review_rhythm"] == ""
    assert result["weak_spots"] == []
    assert result["plan_runtime_recovery"] is None
    assert result["memory"]["review_rhythm"] == ""
    assert result["memory"]["weaknesses"] == []
    assert "active_training_card_routing" not in result
    assert "training_event_ledger" not in result["memory"]
    assert "latest_training_handoff" not in result["memory"]["workspace"]
    assert context == before


@pytest.mark.parametrize("view,mode,status", [("coach", "review", "active"),
                                               ("training", "practice", "active"),
                                               ("training", "review", "archived")])
def test_review_context_only_applies_to_the_selected_review_surface(view, mode, status):
    memory = review_memory(status, mode)
    context = {"current_focus": "Current practice"}
    assert active_training_review(memory, view) is None
    assert apply_training_review_context(context, memory, view) is context


def test_current_review_prompt_reaches_the_model_without_old_coding_history():
    from app.core.models import UserProfile
    from app.llm.prompts import build_coaching_messages

    context = apply_training_review_context({"scenario": "review"}, review_memory("resolved"),
                                            "training")
    messages = build_coaching_messages(UserProfile(long_term_goal="Learn Python"),
        "评价我的概念复习。", None, response_language="zh-CN", coach_context=context,
        history=[{"role": "assistant", "content": "旧断言已经通过4条，追加第5条。"}])
    prompt = str(messages)
    assert "Current Recall Review" in prompt
    assert "解释槽位与引用对象的区别。" in prompt
    assert "我的概念复述。" in prompt
    assert "self-reported concept recall" in prompt
    assert "旧断言" not in prompt


def test_coach_followup_uses_the_completed_card_result():
    from app.core.models import FlashcardAttempt, TrainingCardCandidateSnapshot, UserProfile
    from app.llm.prompts import build_coaching_messages
    from app.training.skill_projection import project_skills

    card = TrainingCardCandidateSnapshot(
        card_id="tuple-card", title="元组槽位", status="answered",
        question="重绑定槽位和修改对象有什么区别？", expected_answer="REFERENCE_ONLY",
    )
    memory = MemorySnapshot(
        training_card_candidates=[card],
        recent_flash_attempts=[FlashcardAttempt(card_id=card.card_id, correct=True)],
        workspace={"training_skill_projection": {"dimensions": project_skills([
            {
                "card_id": card.card_id, "is_current": True, "dimension": "implementation",
                "trust_level": "controlled_check", "result": "passed",
                "assistance_level": "hint_level_1",
            },
            {
                "card_id": "other-card", "is_current": True, "dimension": "implementation",
                "trust_level": "controlled_check", "result": "failed",
            },
        ], card_id="other-card")}},
    )
    message = "我刚完成了复习。根据这次复习的表现，下一步该做什么？"
    context = apply_training_review_context({"learner_message": message}, memory, "coach")
    messages = build_coaching_messages(
        UserProfile(long_term_goal="Learn Python"), message, None,
        response_language="zh-CN", coach_context=context,
    )
    prompt = str(messages)
    assert "Recorded verdict: correct" in prompt
    assert card.question in prompt
    assert card.expected_answer not in prompt
    assert "already passed controlled behavior checks (recorded assistance: hint_level_1)" in prompt
    assert "changed constraint or input" in prompt
    assert "latest controlled implementation check failed" not in prompt

    unrelated = {"learner_message": "解释 Python 的异常传播。"}
    assert apply_training_review_context(unrelated, memory, "coach") is unrelated
