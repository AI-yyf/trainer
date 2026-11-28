"""The model is told which project files exist before it answers.

The extension host hands the server the project's file list on every turn (`workspace_file_snapshot`).
The server kept it for the `project_read` tool only and never showed it to the model, so the model
could not know which files exist: every project question began with `project_read list`, then a read,
then the answer. Measured with a real model on 2026-11-28: "然后呢？" next to a file with a live error
took two to four model round trips, 7-23 s to its first visible word, and the first two calls were
`list` and a re-read of a file whose content was already in the prompt.

The file names (never the contents) are now part of the per-turn context.
"""

from __future__ import annotations

from typing import Any

from app.core.model_domains.foundations_and_provider import UserProfile
from app.llm.prompt_domains.messages_and_turn_signals import build_static_coaching_prefix
from app.llm.prompt_domains.scenario_and_context_blocks import (
    PROJECT_FILES_SHOWN_LIMIT,
    build_coaching_messages,
)
from app.llm.prompt_domains.templates_and_system import _agent_loop_core_instructions

PROFILE = UserProfile(long_term_goal="Understand the project", teaching_style="guided", answer_policy="guided")


def snapshot(paths: list[str]) -> dict[str, Any]:
    return {
        "is_remote": False,
        "root_uri": "file:///repo",
        "files": [{"path": p, "size": 120} for p in paths],
        "contents": {"app.py": {"content": "print('secret body')\n", "language_id": "python"}},
    }


def system_message(
    language: str,
    message: str,
    coach_context: dict[str, Any],
    *,
    agent_loop_enabled: bool = False,
) -> str:
    """The system message of a real turn: the product builds it through build_coaching_messages."""
    messages = build_coaching_messages(
        PROFILE,
        message,
        None,
        response_language=language,
        answer_mode="guided",
        coach_context=coach_context,
        agent_loop_enabled=agent_loop_enabled,
    )
    return str(messages[0]["content"])


def test_the_project_file_names_are_in_the_turn_context() -> None:
    prompt = system_message(
        "zh-CN",
        "讲解一下这个项目",
        {"workspace_file_snapshot": snapshot(["app.py", "src/payments.py", "README.md"])},
        agent_loop_enabled=True,
    )

    assert "Project files" in prompt
    listed = prompt[prompt.index("Project files"):]
    assert "- app.py" in listed and "- src/payments.py" in listed and "- README.md" in listed
    assert "do not call `project_read` with action `list` again" in listed
    # Names only: file bodies stay with the tool.
    assert "secret body" not in prompt


def test_the_open_file_is_marked_as_already_in_the_prompt() -> None:
    messages = build_coaching_messages(
        PROFILE,
        "然后呢？",
        {
            "path": "/repo/app.py",
            "language_id": "python",
            "content": "print(1)\n",
            "diagnostics": ["[Error] line 1: boom"],
        },
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={"workspace_file_snapshot": snapshot(["/repo/app.py", "payments.py"])},
    )
    listed = str(messages[0]["content"])
    listed = listed[listed.index("Project files"):]

    assert "- /repo/app.py — its content (the lines shown above) and its diagnostics are already in your context" in listed
    assert "\n- payments.py\n" in listed
    # The same file under a relative snapshot path is recognised too.
    messages = build_coaching_messages(
        PROFILE,
        "然后呢？",
        {"path": "/repo/src/app.py", "language_id": "python", "content": "print(1)\n"},
        response_language="zh-CN",
        answer_mode="guided",
        coach_context={"workspace_file_snapshot": snapshot(["app.py", "src/app.py"])},
    )
    listed = str(messages[0]["content"])
    assert "- src/app.py — its content (the lines shown above) and its diagnostics are already in your context" in listed
    assert "\n- app.py\n" in listed or listed.endswith("\n- app.py")


def test_without_a_snapshot_nothing_is_added() -> None:
    assert "Project files" not in system_message("zh-CN", "hi", {})
    assert "Project files" not in system_message(
        "zh-CN", "hi", {"workspace_file_snapshot": snapshot([])}
    )
    assert "Project files" not in system_message(
        "zh-CN", "hi", {"workspace_file_snapshot": {"files": "not a list"}}
    )


def test_a_long_project_is_cut_and_says_so() -> None:
    paths = [f"pkg/mod_{i:03d}.py" for i in range(PROJECT_FILES_SHOWN_LIMIT + 12)]
    prompt = system_message("en-US", "what is in here", {"workspace_file_snapshot": snapshot(paths)})
    listed = prompt[prompt.index("Project files"):]

    assert listed.count("\n- pkg/mod_") == PROJECT_FILES_SHOWN_LIMIT
    assert f"and {12} more" in listed
    assert "mod_071" not in listed


def test_a_short_follow_up_turn_still_sees_the_file_names() -> None:
    prompt = system_message(
        "zh-CN",
        "然后呢？",
        {"context_tier": "minimal", "workspace_file_snapshot": snapshot(["app.py", "payments.py"])},
    )

    assert "- payments.py" in prompt[prompt.index("Project files"):]
    # The invariant part still comes first; the list is turn-scoped material.
    assert prompt.index("## Learner Profile") < prompt.index("Project files")


def test_the_tool_instructions_point_at_the_list() -> None:
    instructions = _agent_loop_core_instructions()

    assert "file list is already in your context" in instructions
    # The tool instructions are part of the session-invariant prefix.
    assert "file list is already in your context" in build_static_coaching_prefix(
        PROFILE, "en-US", "guided", agent_loop_enabled=True
    )
