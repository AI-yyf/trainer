"""Attached resources/files must sit next to the learner's request."""

from __future__ import annotations

from app.core.models import UserProfile
from app.llm.prompts import build_coaching_messages


def test_requested_resource_and_current_file_are_repeated_in_user_turn() -> None:
    messages = build_coaching_messages(
        UserProfile(long_term_goal="learn queues"),
        "只根据资料回答：这个项目使用什么队列？",
        {"path": "/tmp/project/queue.py", "language_id": "python", "content": 'ALPHA_QUEUE = "AlphaQueue"\n'},
        coach_context={
            "requested_resources": [
                {"id": "res-1", "title": "project-a.md", "summary": "AlphaQueue protects shared items."}
            ],
            "requested_resource_summary": "project-a.md: AlphaQueue protects shared items.",
        },
    )
    user = messages[-1]
    assert user["role"] == "user"
    assert "## Attached material for this request" in user["content"]
    assert "AlphaQueue protects shared items." in user["content"]
    assert 'ALPHA_QUEUE = "AlphaQueue"' in user["content"]
    assert "只根据资料回答" in user["content"]


def test_plain_turn_does_not_add_attachment_block() -> None:
    messages = build_coaching_messages(
        UserProfile(long_term_goal="learn queues"),
        "PPO 是什么？",
    )
    assert messages[-1]["content"] == "PPO 是什么？"
