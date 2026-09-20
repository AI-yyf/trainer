from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import TrainingCardCandidateSnapshot
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService


class LibraryManagementTests(unittest.TestCase):
    """The Resources library owns every learner artifact: cards, plans, sessions."""

    def setUp(self) -> None:
        database_path = Path(f".tmp-test/library-management-{id(self)}.db")
        if database_path.exists():
            database_path.unlink()
        self.repository = TrainerRepository(database_path)
        self.service = MemoryService(self.repository)
        self.workspace_id = "ws-library-management"

    def tearDown(self) -> None:
        database_path = Path(f".tmp-test/library-management-{id(self)}.db")
        if database_path.exists():
            database_path.unlink()

    def test_delete_training_card_removes_card_and_clears_selection(self) -> None:
        self.service.upsert_card(
            self.workspace_id,
            TrainingCardCandidateSnapshot(
                card_id="card-delete-001",
                card_type="practice",
                title="Library-managed card",
                status="active",
            ),
        )
        structured = self.service._structured_for(self.workspace_id)
        structured.update_workspace(selected_card_id="card-delete-001", selected_card_status="active")
        self.service._persist_structured(self.workspace_id)

        self.assertTrue(self.service.delete_training_card(self.workspace_id, "card-delete-001"))
        self.assertIsNone(self.service.get_card(self.workspace_id, "card-delete-001"))
        self.assertEqual(self.service.get_cards(self.workspace_id), [])
        workspace = self.service._structured_for(self.workspace_id).snapshot().workspace
        self.assertEqual(workspace.get("selected_card_id"), "")

        structured = self.service._structured_for(self.workspace_id)
        self.assertTrue(
            any(
                entry.get("event_type") == "training_card_deleted"
                for entry in structured._training_event_ledger
            ),
        )

        self.assertFalse(self.service.delete_training_card(self.workspace_id, "card-delete-001"))
        self.assertFalse(self.service.delete_training_card(self.workspace_id, ""))

    def test_delete_plan_removes_plan_and_subplans(self) -> None:
        from app.core.models import LearningPlan

        plan = LearningPlan(
            id="plan-lib-001",
            title="Own the library plan lifecycle",
            stages=[],
        )
        self.repository.save_plan(self.workspace_id, plan)
        from app.core.models import SubPlan

        self.repository.save_subplan(
            "plan-lib-001",
            SubPlan(id="subplan-lib-001", parent_plan_id="plan-lib-001", title="First subplan"),
        )

        self.assertTrue(self.repository.delete_plan(self.workspace_id, "plan-lib-001"))
        self.assertEqual(self.repository.list_plans(self.workspace_id), [])
        self.assertFalse(self.repository.delete_plan(self.workspace_id, "plan-lib-001"))

    def test_delete_session_removes_history(self) -> None:
        self.repository.save_session(
            "session-lib-001",
            self.workspace_id,
            {"messages": [{"role": "user", "body": "hello"}]},
        )
        sessions = self.repository.list_sessions_for_workspace(self.workspace_id)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], "session-lib-001")

        self.assertTrue(self.repository.delete_session(self.workspace_id, "session-lib-001"))
        self.assertEqual(self.repository.list_sessions_for_workspace(self.workspace_id), [])
        self.assertFalse(self.repository.delete_session(self.workspace_id, "session-lib-001"))

    def test_library_activity_is_append_only_and_workspace_scoped(self) -> None:
        first = self.repository.record_library_activity(
            self.workspace_id,
            item_type="plan",
            item_id="plan-audit-001",
            action="deleted",
            payload={"title": "Audit this deletion"},
        )
        self.repository.record_library_activity(
            "another-workspace",
            item_type="session",
            item_id="session-other",
            action="deleted",
        )

        entries = self.repository.list_library_activity(self.workspace_id)
        self.assertEqual(entries, [first])
        self.assertEqual(entries[0]["payload"]["title"], "Audit this deletion")


if __name__ == "__main__":
    unittest.main()
