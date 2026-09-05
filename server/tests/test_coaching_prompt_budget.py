from __future__ import annotations

from app.core.models import UserProfile
from app.llm.prompts import _estimate_coaching_history_tokens, build_coaching_messages


def _profile() -> UserProfile:
    return UserProfile(
        long_term_goal="Keep coaching replies grounded in the active task.",
        weekly_hours=4,
        teaching_style="guided",
        answer_policy="guided",
    )


def test_history_budget_keeps_the_latest_question_answer_and_active_thread() -> None:
    old_user = "OLD_USER_CONTEXT " * 200
    old_assistant = "OLD_ASSISTANT_CONTEXT " * 200
    latest_user = "LATEST_USER: inspect the breakpoint value."
    latest_assistant = "LATEST_ASSISTANT: compare it with the expected branch."

    messages = build_coaching_messages(
        _profile(),
        "What should I check next?",
        history=[
            {"role": "user", "content": old_user},
            {"role": "assistant", "content": old_assistant},
            {"role": "user", "content": latest_user},
            {"role": "assistant", "content": latest_assistant},
        ],
        history_limit=12,
        history_token_budget=80,
        coach_context={
            "active_thread": {
                "summary": "Keep the current debug loop narrow.",
                "next_step": "Read the value at the breakpoint.",
            }
        },
    )

    history_messages = messages[1:-1]
    assert {item["content"] for item in history_messages} >= {latest_user, latest_assistant}
    assert all(item["content"] != old_user for item in history_messages)
    assert all(item["content"] != old_assistant for item in history_messages)
    assert sum(_estimate_coaching_history_tokens(item["content"]) for item in history_messages) <= 80
    assert "Active thread to resume:" in messages[0]["content"]
    assert "Keep the current debug loop narrow." in messages[0]["content"]


def test_history_budget_truncates_an_oversized_recent_pair_without_exceeding_budget() -> None:
    long_user = "LATEST_USER " * 120
    long_assistant = "LATEST_ASSISTANT " * 120

    messages = build_coaching_messages(
        _profile(),
        "Continue.",
        history=[
            {"role": "user", "content": "OLDER_TURN " * 120},
            {"role": "assistant", "content": "OLDER_REPLY " * 120},
            {"role": "user", "content": long_user},
            {"role": "assistant", "content": long_assistant},
        ],
        history_limit=12,
        history_token_budget=40,
    )

    history_messages = messages[1:-1]
    assert [item["role"] for item in history_messages] == ["user", "assistant"]
    assert history_messages[0]["content"].startswith("LATEST_USER")
    assert history_messages[1]["content"].startswith("LATEST_ASSISTANT")
    assert "earlier message shortened" in "\n".join(item["content"] for item in history_messages)
    assert sum(_estimate_coaching_history_tokens(item["content"]) for item in history_messages) <= 40


def test_fresh_lane_reanchors_on_the_current_question_over_stale_plan_and_training_context() -> None:
    current_question = "Explain Python generators in two sentences. Do not give me a practice task."

    messages = build_coaching_messages(
        _profile(),
        current_question,
        history=[
            {"role": "user", "content": "STALE_HISTORY: keep drilling remote debugging."},
            {"role": "assistant", "content": "STALE_HISTORY_REPLY: open the old training card."},
        ],
        coach_context={
            "history_mode": "fresh_lane",
            "scenario": "task",
            "learner_signal": "blocked",
            "current_focus": "STALE_FOCUS: finish the old debug plan",
            "active_thread": {
                "summary": "STALE_THREAD: resume the old SSH practice.",
                "next_step": "STALE_THREAD_STEP: inspect the old breakpoint.",
            },
            "review_queue_summary": "STALE_REVIEW: repeat the old card",
            "due_reviews": [{"concept": "STALE_DUE_REVIEW", "reason": "old practice"}],
            "failing_checks": ["STALE_FAILING_CHECK: old exercise test"],
            "exercise_prompt": {
                "prompt": "STALE_EXERCISE: complete the old training card",
                "fallback_step": "STALE_EXERCISE_FALLBACK: retry the old card",
            },
            "project_ideas": [
                {
                    "title": "STALE_PROJECT_IDEA",
                    "first_step": "build the unrelated old feature",
                }
            ],
            "teaching_decision": {"primary_goal": "STALE_TRAINING_GOAL"},
            "learner_state": {"needs_rescue": True},
        },
        history_limit=12,
        history_token_budget=80,
    )

    system_content = messages[0]["content"]
    assert len(messages) == 2
    assert messages[-1] == {"role": "user", "content": current_question}
    assert "Main lane: principle explanation." in system_content
    assert "Request precedence:" in system_content
    assert "The final learner message is the task for this turn." in system_content
    assert "STALE_" not in system_content


def test_formal_plan_turn_requires_model_commit_and_keeps_library_context() -> None:
    messages = build_coaching_messages(
        _profile(),
        "Create the formal plan from the uploaded route notes.",
        coach_context={
            "formal_plan_mutation": True,
            "allow_coach_only_tools": True,
            "requested_resource_ids": ["resource-route-notes"],
            "requested_resource_summary": "The uploaded route notes cover validation boundaries.",
            "resource_fragments": [
                {
                    "resource_id": "resource-route-notes",
                    "title": "Route notes",
                    "snippet": "Validate at the boundary, then verify the response path.",
                }
            ],
        },
    )
    system_content = messages[0]["content"]
    assert "Formal Plan Turn" in system_content
    assert "save_formal_plan" in system_content
    assert "resource-route-notes" in system_content
    assert "uploaded route notes" in system_content
