from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import CurrentFilePayload, MemorySnapshot, TurnRequest, UserProfile
from app.pedagogy.project_adaptation_coach import ProjectAdaptationCoachService


def _profile() -> UserProfile:
    return UserProfile(
        long_term_goal="Guide learners through real project reshaping",
        weekly_hours=5,
        teaching_style="guided",
        answer_policy="guided",
        preferred_libraries=["fastapi"],
    )


def _current_file() -> CurrentFilePayload:
    return CurrentFilePayload(
        path="server/app/api/routers.py",
        language_id="python",
        content="def route():\n    pass\n",
        diagnostics=["The route mixes orchestration and rendering details."],
        recent_files=["server/app/pedagogy/service.py"],
        recent_edited_files=["server/app/api/routers.py", "server/app/pedagogy/service.py"],
        related_files=[
            {"path": "server/tests/test_api.py", "reason": "verification"},
            {"path": "server/app/llm/prompts.py", "reason": "coach output"},
        ],
    )


def _memory() -> MemorySnapshot:
    return MemorySnapshot(
        current_focus="coach-first adaptation",
        coach_anchor="project reshaping",
        recent_wins=["Kept one patch reviewable"],
    )


class ProjectAdaptationCoachTests(unittest.TestCase):
    def test_build_guide_emphasizes_boundary_sequence_and_preservation(self) -> None:
        service = ProjectAdaptationCoachService()
        guide = service.build_guide(
            request=TurnRequest(
                message="按我的目标改造这个项目，让 Trainer 更像长期教练。",
                current_file=_current_file(),
                focus_area="long-term coaching flow",
            ),
            learner_state=type("LearnerState", (), {"needs_rescue": False})(),
            decision=type("Decision", (), {"focus_area": "long-term coaching flow"})(),
            profile=_profile(),
            memory_snapshot=_memory(),
        )
        self.assertIn("long-term coaching flow", guide.target_outcome)
        self.assertTrue(guide.affected_areas)
        self.assertTrue(guide.preserve_areas)
        self.assertTrue(guide.migration_sequence)
        self.assertTrue(guide.validation_checkpoints)
        self.assertTrue(any("boundary" in item.lower() for item in guide.migration_sequence))
        self.assertTrue(any("server/app/api/routers.py" in item for item in guide.migration_sequence))
        self.assertTrue(any("server/tests/test_api.py" in item for item in guide.validation_checkpoints))
        self.assertTrue(any("server/app/api/routers.py" in item for item in guide.rollback_notes))


if __name__ == "__main__":
    unittest.main()
