"""The coach's local scaffold speaks the learner's language.

Without the agent loop — a model without tools — a turn the model cannot answer (a failure, an
empty reply) is answered from local state. Its default sentences are constants, and the Chinese
ones carried the lane names of the prompt in English: "把当前原理钉在一处 live code boundary 上",
"我们先把这一轮留在 function guidance 这条线上", "先动第一条 adaptation 边界", "再按现在的 review
rhythm 接着走", "还有 2 条 diagnostics", "保持 encouraging 这类语气". The contract (§3) asks for
formal natural language and forbids internal terms; English stays only for names the learner meets
in their own tools and in Trainer's settings.
"""

from __future__ import annotations

import re

import pytest

from app.llm.coaching_patches import _scaffold_next_step
from app.llm.coaching_reply_drafts import _scaffold_close
from app.llm.coaching_scaffold import (
    _scaffold_anchor,
    _scaffold_diagnosis,
    _scaffold_teaching_note,
    _scenario_step_text,
)

SCENARIOS = (
    "remote_workspace",
    "debug_loop",
    "function_guidance",
    "project_adaptation",
    "principle",
    "review",
    "task",
    "next_task",
    "plan",
    "concept_teaching",
    "project_idea",
    "engineering_challenge",
    "general",
)
LEARNER_FACING_NAMES = {"VS", "Code", "SSH", "WSL", "API", "Trainer", "dev", "container"}


def _default_sentences(scenario: str, learner_signal: str, mode: str) -> list[str]:
    return [
        _scaffold_anchor(scenario=scenario, goal="", file_path=None, current_focus="", chinese=True),
        _scaffold_diagnosis(
            scenario=scenario,
            learner_signal=learner_signal,
            diagnostics_count=2,
            weak_spots=[],
            teaching_observations=[],
            summary="",
            teaching_decision_reason="",
            chinese=True,
        ),
        _scaffold_next_step(
            scenario=scenario,
            mode=mode,
            learner_signal=learner_signal,
            file_path=None,
            weak_spots=[],
            next_step_hint="",
            chinese=True,
        ),
        _scenario_step_text(scenario, file_path="src/app.py", weak_spots=[], chinese=True),
        _scaffold_teaching_note(
            scenario=scenario,
            mode=mode,
            recent_wins=[],
            weak_spots=[],
            due_reviews=[],
            review_rhythm="",
            coach_defaults={},
            tone_name="encouraging",
            verbosity_bias="medium",
            chinese=True,
        ),
        _scaffold_close(learner_signal=learner_signal, mode=mode, verbosity_bias="medium", chinese=True),
    ]


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize(("learner_signal", "mode"), [("steady", "guided"), ("blocked", "direct")])
def test_a_chinese_default_sentence_carries_only_names_the_learner_knows(
    scenario: str, learner_signal: str, mode: str
) -> None:
    for sentence in _default_sentences(scenario, learner_signal, mode):
        without_code = re.sub(r"`[^`]*`", "", sentence)
        stray = sorted(set(re.findall(r"[A-Za-z]+", without_code)) - LEARNER_FACING_NAMES)
        assert not stray, (stray, sentence)
