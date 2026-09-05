from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research.models import (
    AgentRole,
    AgentState,
    ArtifactKind,
    ResearchProject,
    ResearchTheme,
    ScheduleCadence,
    ScheduleSpec,
    ThemeStatus,
    ThreadDepth,
    WorkbenchGate,
    utc_now,
)
from app.research.scheduler import ResearchScheduler
from app.research.service import ResearchOrchestratorService


class TestResearchModels(unittest.TestCase):
    def test_schedule_spec_creates_checkpoints_based_on_cadence(self) -> None:
        schedule = ScheduleSpec.create(duration_weeks=4, cadence=ScheduleCadence.WEEKLY)
        self.assertEqual(schedule.duration, timedelta(weeks=4))
        self.assertEqual(len(schedule.checkpoints), 4)

    def test_schedule_spec_daily_cadence_creates_more_checkpoints(self) -> None:
        schedule = ScheduleSpec.create(duration_weeks=1, cadence=ScheduleCadence.DAILY)
        self.assertEqual(len(schedule.checkpoints), 7)

    def test_research_theme_creation(self) -> None:
        theme = ResearchTheme.create(
            title="Test Theme",
            description="A test research theme",
            duration_weeks=2,
            cadence=ScheduleCadence.WEEKLY,
        )
        self.assertEqual(theme.title, "Test Theme")
        self.assertEqual(theme.status, ThemeStatus.PLANNING)
        self.assertEqual(len(theme.schedule.checkpoints), 2)

    def test_research_theme_add_thread(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test")
        thread = theme.add_thread(angle="Historical analysis", depth=ThreadDepth.DEEP)
        self.assertEqual(len(theme.threads), 1)
        self.assertEqual(thread.angle, "Historical analysis")
        self.assertEqual(thread.depth, ThreadDepth.DEEP)

    def test_research_theme_add_finding(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test")
        thread = theme.add_thread(angle="Test angle")
        finding = theme.add_finding(
            thread_id=thread.id,
            content="Important discovery",
            source="Primary source",
            confidence=0.85,
            tags=["key", "verified"],
        )
        self.assertIsNotNone(finding)
        self.assertEqual(len(thread.findings), 1)
        self.assertEqual(finding.confidence, 0.85)

    def test_research_theme_add_artifact(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test")
        artifact = theme.add_artifact(
            title="Final Report",
            kind=ArtifactKind.REPORT,
            content="# Summary\n\nFindings...",
        )
        self.assertEqual(len(theme.artifacts), 1)
        self.assertEqual(artifact.kind, ArtifactKind.REPORT)
        self.assertEqual(artifact.version, 1)

    def test_research_theme_status_transitions(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test")
        self.assertEqual(theme.status, ThemeStatus.PLANNING)
        theme.activate()
        self.assertEqual(theme.status, ThemeStatus.ACTIVE)
        theme.pause()
        self.assertEqual(theme.status, ThemeStatus.PAUSED)
        theme.complete()
        self.assertEqual(theme.status, ThemeStatus.COMPLETED)

    def test_research_project_creation(self) -> None:
        project = ResearchProject.create(
            title="Climate Research",
            description="Multi-theme climate change study",
        )
        self.assertEqual(project.title, "Climate Research")
        self.assertEqual(len(project.themes), 0)
        self.assertEqual(len(project.gate.messages), 1)
        self.assertIn("created", project.gate.messages[0]["content"])

    def test_research_project_add_theme(self) -> None:
        project = ResearchProject.create(title="Project", description="Test")
        project.add_theme(
            title="Historical Trends",
            description="Analyze 50-year trends",
            duration_weeks=4,
        )
        self.assertEqual(len(project.themes), 1)
        self.assertGreaterEqual(len(project.gate.messages), 2)
        self.assertEqual(project.gate.messages[-1]["role"], "agent")

    def test_agent_state_role_switching(self) -> None:
        state = AgentState()
        self.assertEqual(state.current_role, AgentRole.RESEARCHER)
        state.switch_role(AgentRole.EDITOR)
        self.assertEqual(state.current_role, AgentRole.EDITOR)
        state.switch_role(AgentRole.CRITIC)
        self.assertEqual(state.current_role, AgentRole.CRITIC)

    def test_agent_state_thinking_log(self) -> None:
        state = AgentState()
        entry = state.add_thinking(
            role=AgentRole.RESEARCHER,
            question="What is the main hypothesis?",
            reasoning="Looking at the data...",
            conclusion="The hypothesis is X",
        )
        self.assertEqual(len(state.thinking_log), 1)
        self.assertEqual(entry.question, "What is the main hypothesis?")
        self.assertEqual(entry.role, AgentRole.RESEARCHER)

    def test_agent_state_iteration_tracking(self) -> None:
        state = AgentState()
        self.assertEqual(state.self_review_count, 0)
        can_continue = state.increment_review()
        self.assertTrue(can_continue)
        self.assertEqual(state.self_review_count, 1)
        self.assertEqual(state.current_iteration, 1)

    def test_agent_state_max_iterations(self) -> None:
        state = AgentState(max_review_rounds=2)
        state.increment_review()
        state.increment_review()
        can_continue = state.increment_review()
        self.assertFalse(can_continue)
        self.assertEqual(state.self_review_count, 3)

    def test_workbench_gate_messages(self) -> None:
        gate = WorkbenchGate()
        msg = gate.add_message("human", "Start research on topic X")
        self.assertEqual(len(gate.messages), 1)
        self.assertEqual(msg["role"], "human")
        self.assertEqual(msg["content"], "Start research on topic X")

    def test_workbench_gate_approval_flow(self) -> None:
        gate = WorkbenchGate()
        approval = gate.request_approval(
            title="Approve synthesis?",
            description="Final synthesis ready for review",
        )
        self.assertEqual(len(gate.approvals), 1)
        self.assertEqual(approval.status, "pending")
        pending = gate.pending_approvals()
        self.assertEqual(len(pending), 1)
        resolved = gate.resolve_approval(approval.id, approved=True)
        self.assertEqual(resolved.status, "approved")
        self.assertEqual(len(gate.pending_approvals()), 0)

    def test_approval_rejection(self) -> None:
        gate = WorkbenchGate()
        approval = gate.request_approval(title="Test", description="Test")
        resolved = gate.resolve_approval(approval.id, approved=False)
        self.assertEqual(resolved.status, "rejected")

    def test_to_dict_methods(self) -> None:
        theme = ResearchTheme.create(title="Test", description="Test")
        theme_dict = theme.to_dict()
        self.assertIn("id", theme_dict)
        self.assertIn("title", theme_dict)
        self.assertIn("schedule", theme_dict)

        project = ResearchProject.create(title="Project", description="Test")
        project_dict = project.to_dict()
        self.assertIn("id", project_dict)
        self.assertIn("agent_state", project_dict)
        self.assertIn("gate", project_dict)


class TestResearchScheduler(unittest.TestCase):
    def test_should_advance_returns_false_for_inactive_theme(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test")
        self.assertFalse(ResearchScheduler.should_advance(theme))

    def test_should_advance_returns_false_when_no_overdue_checkpoints(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test", duration_weeks=4)
        theme.activate()
        self.assertFalse(ResearchScheduler.should_advance(theme))

    def test_should_advance_returns_true_when_checkpoint_overdue(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test", duration_weeks=1)
        theme.activate()
        for cp in theme.schedule.checkpoints:
            cp.due_date = utc_now() - timedelta(days=1)
        self.assertTrue(ResearchScheduler.should_advance(theme))

    def test_progress_percentage(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test", duration_weeks=4)
        for cp in theme.schedule.checkpoints[:2]:
            cp.completed = True
        progress = ResearchScheduler.progress_percentage(theme)
        self.assertEqual(progress, 50.0)

    def test_time_elapsed_percentage(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test", duration_weeks=1)
        theme.schedule.start_date = utc_now() - timedelta(days=3)
        theme.schedule.end_date = utc_now() + timedelta(days=4)
        elapsed = ResearchScheduler.time_elapsed_percentage(theme)
        self.assertGreater(elapsed, 0)
        self.assertLess(elapsed, 100)

    def test_mark_checkpoint_complete(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test", duration_weeks=1)
        cp_id = theme.schedule.checkpoints[0].id
        result = ResearchScheduler.mark_checkpoint_complete(theme, cp_id)
        self.assertTrue(result)
        self.assertTrue(theme.schedule.checkpoints[0].completed)

    def test_next_checkpoint(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test", duration_weeks=1)
        theme.activate()
        next_cp = ResearchScheduler.next_checkpoint(theme)
        self.assertIsNotNone(next_cp)
        self.assertIn("id", next_cp)
        self.assertIn("label", next_cp)

    def test_overdue_checkpoints(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test", duration_weeks=4)
        theme.activate()
        for cp in theme.schedule.checkpoints:
            cp.due_date = utc_now() - timedelta(days=1)
        overdue = ResearchScheduler.overdue_checkpoints(theme)
        self.assertEqual(len(overdue), 4)

    def test_schedule_status(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test", duration_weeks=2)
        theme.activate()
        status = ResearchScheduler.schedule_status(theme)
        self.assertEqual(status["theme_id"], theme.id)
        self.assertEqual(status["status"], ThemeStatus.ACTIVE)
        self.assertIn("progress_percentage", status)


class TestResearchOrchestratorService(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ResearchOrchestratorService()

    def test_create_project(self) -> None:
        project = self.service.create_project(
            title="Test Project",
            description="A test research project",
        )
        self.assertIsNotNone(project.id)
        self.assertEqual(project.title, "Test Project")

    def test_get_project(self) -> None:
        created = self.service.create_project(title="Test", description="Test")
        retrieved = self.service.get_project(created.id)
        self.assertEqual(retrieved.id, created.id)

    def test_list_projects(self) -> None:
        self.service.create_project(title="A", description="Test")
        self.service.create_project(title="B", description="Test")
        projects = self.service.list_projects()
        self.assertEqual(len(projects), 2)

    def test_delete_project(self) -> None:
        project = self.service.create_project(title="Test", description="Test")
        self.assertTrue(self.service.delete_project(project.id))
        self.assertIsNone(self.service.get_project(project.id))

    def test_add_theme(self) -> None:
        project = self.service.create_project(title="Test", description="Test")
        theme = self.service.add_theme(
            project.id,
            title="Theme 1",
            description="First theme",
            duration_weeks=2,
        )
        self.assertIsNotNone(theme)
        self.assertEqual(len(project.themes), 1)

    def test_activate_theme(self) -> None:
        project = self.service.create_project(title="Test", description="Test")
        theme = self.service.add_theme(project.id, title="Theme", description="Test")
        activated = self.service.activate_theme(project.id, theme.id)
        self.assertIsNotNone(activated)
        self.assertEqual(activated.status, ThemeStatus.ACTIVE)

    def test_pause_theme(self) -> None:
        project = self.service.create_project(title="Test", description="Test")
        theme = self.service.add_theme(project.id, title="Theme", description="Test")
        self.service.activate_theme(project.id, theme.id)
        paused = self.service.pause_theme(project.id, theme.id)
        self.assertIsNotNone(paused)
        self.assertEqual(paused.status, ThemeStatus.PAUSED)

    def test_add_thread(self) -> None:
        project = self.service.create_project(title="Test", description="Test")
        theme = self.service.add_theme(project.id, title="Theme", description="Test")
        thread = self.service.add_thread(
            project.id,
            theme.id,
            angle="Historical analysis",
            depth=ThreadDepth.DEEP,
        )
        self.assertIsNotNone(thread)
        self.assertEqual(thread.angle, "Historical analysis")

    def test_add_finding(self) -> None:
        project = self.service.create_project(title="Test", description="Test")
        theme = self.service.add_theme(project.id, title="Theme", description="Test")
        thread = self.service.add_thread(project.id, theme.id, angle="Test")
        finding = self.service.add_finding(
            project.id,
            theme.id,
            thread.id,
            content="Key finding",
            source="Primary source",
            confidence=0.9,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.content, "Key finding")

    def test_add_artifact(self) -> None:
        project = self.service.create_project(title="Test", description="Test")
        theme = self.service.add_theme(project.id, title="Theme", description="Test")
        artifact = self.service.add_artifact(
            project.id,
            theme.id,
            title="Report",
            kind=ArtifactKind.REPORT,
            content="Content",
        )
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.title, "Report")

    def test_get_state(self) -> None:
        project = self.service.create_project(title="Test", description="Test")
        state = self.service.get_state(project.id)
        self.assertIsNotNone(state)
        self.assertIn("project", state)
        self.assertIn("schedule_status", state)

    def test_human_message(self) -> None:
        project = self.service.create_project(title="Test", description="Test")
        result = self.service.human_message(project.id, "Hello research agent")
        self.assertIsNotNone(result)
        self.assertIn("response", result)

    def test_advance_research(self) -> None:
        project = self.service.create_project(title="Test", description="Test")
        theme = self.service.add_theme(project.id, title="Theme", description="Test")
        self.service.activate_theme(project.id, theme.id)
        for cp in theme.schedule.checkpoints:
            cp.due_date = utc_now() - timedelta(days=1)
        result = self.service.advance_research(project.id)
        self.assertIn("themes_advanced", result)

    def test_approval_flow(self) -> None:
        project = self.service.create_project(title="Test", description="Test")
        theme = self.service.add_theme(project.id, title="Theme", description="Test")
        self.service.activate_theme(project.id, theme.id)
        for cp in theme.schedule.checkpoints:
            cp.due_date = utc_now() - timedelta(days=1)
        project.agent_state.current_iteration = 3
        self.service.advance_research(project.id)
        pending = self.service.get_pending_approvals(project.id)
        self.assertGreater(len(pending), 0)
        approval_result = self.service.resolve_approval(project.id, pending[0]["id"], approved=True)
        self.assertEqual(approval_result["status"], "approved")


if __name__ == "__main__":
    unittest.main()
