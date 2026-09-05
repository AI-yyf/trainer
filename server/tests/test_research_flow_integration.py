"""End-to-end integration tests for the full research workflow.

These tests exercise real service interactions without mocking internal services.
They use temporary directories for test databases and verify the complete flow
from project creation through research advancement and persistence.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from app.db.research_repository import ResearchRepository
from app.research.models import (
    AgentRole,
    ArtifactKind,
    ScheduleCadence,
    ThemeStatus,
    ThreadDepth,
    utc_now,
)
from app.research.service import ResearchOrchestratorService

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Create a temporary database path for each test."""
    return tmp_path / "research.db"


@pytest.fixture
def research_repository(tmp_db_path: Path) -> ResearchRepository:
    """Create a real ResearchRepository with a temporary database."""
    return ResearchRepository(tmp_db_path)


@pytest.fixture
def research_service(research_repository: ResearchRepository) -> ResearchOrchestratorService:
    """Create a ResearchOrchestratorService with real repository."""
    return ResearchOrchestratorService(repository=research_repository)


@pytest.fixture
def research_service_no_repo() -> ResearchOrchestratorService:
    """Create a ResearchOrchestratorService without repository (in-memory)."""
    return ResearchOrchestratorService(repository=None)


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------


class TestResearchFlowIntegration:
    """Integration tests for the complete research workflow."""

    def test_full_research_project_lifecycle(self, research_service: ResearchOrchestratorService, tmp_path: Path) -> None:
        """Test the complete research project lifecycle from creation to completion."""
        # 1. Create project
        project = research_service.create_project(
            title="AI Safety Research",
            description="Investigating safety considerations in AI systems",
        )
        assert project.id.startswith("proj_")
        assert project.title == "AI Safety Research"
        assert len(project.gate.messages) >= 1  # System message

        # 2. Add theme with schedule
        theme = research_service.add_theme(
            project.id,
            title="Alignment Techniques",
            description="Study of AI alignment methods",
            duration_weeks=4,
            cadence=ScheduleCadence.WEEKLY,
        )
        assert theme is not None
        assert theme.title == "Alignment Techniques"
        assert theme.schedule is not None
        assert len(theme.schedule.checkpoints) >= 1  # Weekly cadence should create checkpoints

        # 3. Activate theme
        activated_theme = research_service.activate_theme(project.id, theme.id)
        assert activated_theme is not None
        assert activated_theme.status == ThemeStatus.ACTIVE

        # 4. Add thread and findings
        thread = research_service.add_thread(
            project.id,
            theme.id,
            angle="Constitutional AI approach",
            depth=ThreadDepth.DEEP,
        )
        assert thread is not None
        assert thread.angle == "Constitutional AI approach"

        # Add findings to the thread
        finding1 = research_service.add_finding(
            project.id,
            theme.id,
            thread.id,
            content="Constitutional AI uses explicit principles to guide behavior",
            source="Anthropic paper 2022",
            confidence=0.9,
            tags=["alignment", "principles"],
        )
        assert finding1 is not None
        assert finding1.confidence == 0.9

        finding2 = research_service.add_finding(
            project.id,
            theme.id,
            thread.id,
            content="RLHF is a foundational technique for alignment",
            source="OpenAI research",
            confidence=0.85,
            tags=["rlhf", "training"],
        )
        assert finding2 is not None

        # 5. Advance research (agent iteration)
        advance_result = research_service.advance_research(project.id, theme_id=theme.id)
        assert "themes_advanced" in advance_result
        assert len(advance_result["themes_advanced"]) == 1

        # Verify agent state changed
        project_after = research_service.get_project(project.id)
        assert project_after is not None
        assert project_after.agent_state.current_role == AgentRole.RESEARCHER

        # 6. Verify persistence (restart simulation)
        # Create a new service instance with the same repository
        new_service = ResearchOrchestratorService(
            repository=research_service._repository,
        )
        reloaded_project = new_service.get_project(project.id)

        assert reloaded_project is not None
        assert reloaded_project.id == project.id
        assert reloaded_project.title == "AI Safety Research"
        assert len(reloaded_project.themes) == 1
        assert reloaded_project.themes[0].status == ThemeStatus.ACTIVE

    def test_research_with_persistence(self, research_repository: ResearchRepository, tmp_path: Path) -> None:
        """Test that research data persists across service instances."""
        # 1. Create project with repository
        service1 = ResearchOrchestratorService(repository=research_repository)
        project = service1.create_project(
            title="Persistent Research",
            description="Testing persistence",
        )

        # Add theme, thread, and findings
        theme = service1.add_theme(
            project.id,
            title="Theme 1",
            description="Test theme",
            duration_weeks=2,
        )
        assert theme is not None
        thread = service1.add_thread(project.id, theme.id, angle="Test angle")
        assert thread is not None
        finding = service1.add_finding(
            project.id,
            theme.id,
            thread.id,
            content="Test finding",
            source="Test source",
        )
        assert finding is not None

        # Add artifact
        artifact = service1.add_artifact(
            project.id,
            theme.id,
            title="Research Notes",
            kind=ArtifactKind.NOTE,
            content="# Notes\n\nTest content",
        )
        assert artifact is not None

        # 2. Create new service instance with same repository
        service2 = ResearchOrchestratorService(repository=research_repository)

        # 3. Verify data persisted
        reloaded_project = service2.get_project(project.id)
        assert reloaded_project is not None
        assert reloaded_project.title == "Persistent Research"

        reloaded_themes = reloaded_project.themes
        assert len(reloaded_themes) == 1
        assert reloaded_themes[0].title == "Theme 1"

        assert len(reloaded_themes[0].threads) == 1
        assert reloaded_themes[0].threads[0].angle == "Test angle"

        assert len(reloaded_themes[0].threads[0].findings) == 1
        assert reloaded_themes[0].threads[0].findings[0].content == "Test finding"

        assert len(reloaded_themes[0].artifacts) == 1
        assert reloaded_themes[0].artifacts[0].title == "Research Notes"

    def test_research_gate_communication(self, research_service: ResearchOrchestratorService, tmp_path: Path) -> None:
        """Test the workbench gate communication flow."""
        # 1. Create project
        project = research_service.create_project(
            title="Gate Communication Test",
            description="Testing gate messages",
        )

        # 2. Send human message
        result = research_service.human_message(project.id, "I want to focus on interpretability research")
        assert result is not None
        assert "response" in result

        # Verify message was added to gate
        project_after = research_service.get_project(project.id)
        assert project_after is not None
        # Should have system message + agent response + our human message
        assert len(project_after.gate.messages) >= 2

        # 3. Add and activate theme
        theme = research_service.add_theme(
            project.id,
            title="Interpretability",
            description="Understanding model internals",
        )
        assert theme is not None
        research_service.activate_theme(project.id, theme.id)

        # 4. Request approval (via advance to synthesis phase)
        # Advance multiple times to reach synthesis
        for _ in range(4):
            research_service.advance_research(project.id, theme_id=theme.id)

        # Check for pending approvals
        pending = research_service.get_pending_approvals(project.id)
        assert len(pending) >= 1

        # 5. Resolve approval
        approval_id = pending[0]["id"]
        resolve_result = research_service.resolve_approval(project.id, approval_id, approved=True)
        assert resolve_result is not None
        assert resolve_result["status"] == "approved"

        # Verify theme completed
        project_final = research_service.get_project(project.id)
        assert project_final is not None
        completed_theme = next((t for t in project_final.themes if t.id == theme.id), None)
        assert completed_theme is not None
        assert completed_theme.status == ThemeStatus.COMPLETED

    def test_agent_role_progression(self, research_service: ResearchOrchestratorService, tmp_path: Path) -> None:
        """Test that agent roles progress correctly through iterations."""
        project = research_service.create_project(
            title="Agent Role Test",
            description="Testing role progression",
        )
        theme = research_service.add_theme(
            project.id,
            title="Test Theme",
            description="For role testing",
        )
        assert theme is not None
        research_service.activate_theme(project.id, theme.id)

        # Track role progression
        expected_roles = [
            AgentRole.RESEARCHER,
            AgentRole.EDITOR,
            AgentRole.CRITIC,
            AgentRole.SYNTHESIZER,
        ]

        for i, expected_role in enumerate(expected_roles):
            research_service.advance_research(project.id, theme_id=theme.id)
            project_state = research_service.get_project(project.id)
            assert project_state is not None
            assert project_state.agent_state.current_role == expected_role, (
                f"Iteration {i}: expected {expected_role}, got {project_state.agent_state.current_role}"
            )

    def test_multiple_themes_and_threads(self, research_service: ResearchOrchestratorService, tmp_path: Path) -> None:
        """Test managing multiple themes and threads within a project."""
        project = research_service.create_project(
            title="Multi-Theme Research",
            description="Testing multiple themes",
        )

        # Add multiple themes
        theme1 = research_service.add_theme(
            project.id,
            title="Theme A",
            description="First theme",
            duration_weeks=2,
        )
        theme2 = research_service.add_theme(
            project.id,
            title="Theme B",
            description="Second theme",
            duration_weeks=3,
        )
        assert theme1 is not None
        assert theme2 is not None

        # Activate first theme
        research_service.activate_theme(project.id, theme1.id)

        # Add multiple threads to theme1
        thread1 = research_service.add_thread(project.id, theme1.id, angle="Thread 1", depth=ThreadDepth.SHALLOW)
        thread2 = research_service.add_thread(project.id, theme1.id, angle="Thread 2", depth=ThreadDepth.DEEP)
        thread3 = research_service.add_thread(project.id, theme1.id, angle="Thread 3", depth=ThreadDepth.MEDIUM)

        assert thread1 is not None
        assert thread2 is not None
        assert thread3 is not None

        # Add findings to different threads
        research_service.add_finding(project.id, theme1.id, thread1.id, content="Finding 1", source="Source 1")
        research_service.add_finding(project.id, theme1.id, thread2.id, content="Finding 2", source="Source 2")
        research_service.add_finding(project.id, theme1.id, thread2.id, content="Finding 3", source="Source 3")

        # Verify structure
        project_state = research_service.get_project(project.id)
        assert project_state is not None
        assert len(project_state.themes) == 2
        assert len(project_state.themes[0].threads) == 3
        assert len(project_state.themes[0].threads[0].findings) == 1
        assert len(project_state.themes[0].threads[1].findings) == 2

    def test_checkpoint_management(self, research_service: ResearchOrchestratorService, tmp_path: Path) -> None:
        """Test checkpoint creation and completion."""
        project = research_service.create_project(
            title="Checkpoint Test",
            description="Testing checkpoints",
        )
        theme = research_service.add_theme(
            project.id,
            title="Checkpointed Theme",
            description="With checkpoints",
            duration_weeks=4,
            cadence=ScheduleCadence.WEEKLY,
        )
        assert theme is not None
        assert theme.schedule is not None

        # Verify checkpoints were auto-generated
        # Make a copy of the count to avoid reference issues
        initial_checkpoint_count = len(theme.schedule.checkpoints)
        assert initial_checkpoint_count >= 1

        # Add a custom checkpoint
        custom_cp = research_service.add_checkpoint(
            project.id,
            theme.id,
            label="Custom Review",
            due_date=utc_now() + timedelta(days=14),
        )
        assert custom_cp is not None
        assert custom_cp.label == "Custom Review"

        # Verify checkpoint was added
        project_state = research_service.get_project(project.id)
        assert project_state is not None
        theme_state = next(t for t in project_state.themes if t.id == theme.id)
        assert theme_state.schedule is not None
        assert len(theme_state.schedule.checkpoints) == initial_checkpoint_count + 1

    def test_project_deletion_cascades(self, research_service: ResearchOrchestratorService, tmp_path: Path) -> None:
        """Test that deleting a project removes all associated data."""
        # Create project with full data
        project = research_service.create_project(
            title="To Be Deleted",
            description="This will be deleted",
        )
        theme = research_service.add_theme(
            project.id,
            title="Theme",
            description="Theme to delete",
        )
        assert theme is not None
        thread = research_service.add_thread(project.id, theme.id, angle="Thread")
        assert thread is not None
        research_service.add_finding(project.id, theme.id, thread.id, content="Finding", source="Source")

        # Delete project
        deleted = research_service.delete_project(project.id)
        assert deleted is True

        # Verify project is gone
        assert research_service.get_project(project.id) is None

        # Verify themes are gone (via repository)
        if research_service._repository:
            themes = research_service._repository.get_themes_by_project(project.id)
            assert themes == []

    def test_human_message_commands(self, research_service: ResearchOrchestratorService, tmp_path: Path) -> None:
        """Test human message commands like /advance and /status."""
        project = research_service.create_project(
            title="Command Test",
            description="Testing commands",
        )
        theme = research_service.add_theme(
            project.id,
            title="Test Theme",
            description="For commands",
        )
        assert theme is not None
        research_service.activate_theme(project.id, theme.id)

        # Test /status command
        status_result = research_service.human_message(project.id, "/status")
        assert status_result is not None
        assert "project" in status_result

        # Test /advance command
        advance_result = research_service.human_message(project.id, "/advance")
        assert advance_result is not None
        assert "themes_advanced" in advance_result


class TestResearchFlowErrorHandling:
    """Test error handling in the research flow."""

    def test_get_nonexistent_project(self, research_service: ResearchOrchestratorService) -> None:
        """Test getting a nonexistent project returns None."""
        result = research_service.get_project("nonexistent-project-id")
        assert result is None

    def test_add_theme_to_nonexistent_project(self, research_service: ResearchOrchestratorService) -> None:
        """Test adding a theme to a nonexistent project returns None."""
        result = research_service.add_theme(
            "nonexistent-project-id",
            title="Theme",
            description="Description",
        )
        assert result is None

    def test_add_thread_to_nonexistent_theme(self, research_service: ResearchOrchestratorService) -> None:
        """Test adding a thread to a nonexistent theme returns None."""
        project = research_service.create_project(title="Test", description="Test")
        result = research_service.add_thread(
            project.id,
            "nonexistent-theme-id",
            angle="Test angle",
        )
        assert result is None

    def test_add_finding_to_nonexistent_thread(self, research_service: ResearchOrchestratorService) -> None:
        """Test adding a finding to a nonexistent thread returns None."""
        project = research_service.create_project(title="Test", description="Test")
        theme = research_service.add_theme(project.id, title="Theme", description="Desc")
        assert theme is not None
        result = research_service.add_finding(
            project.id,
            theme.id,
            "nonexistent-thread-id",
            content="Finding",
            source="Source",
        )
        assert result is None

    def test_activate_nonexistent_theme(self, research_service: ResearchOrchestratorService) -> None:
        """Test activating a nonexistent theme returns None."""
        project = research_service.create_project(title="Test", description="Test")
        result = research_service.activate_theme(project.id, "nonexistent-theme-id")
        assert result is None

    def test_resolve_nonexistent_approval(self, research_service: ResearchOrchestratorService) -> None:
        """Test resolving a nonexistent approval returns None."""
        project = research_service.create_project(title="Test", description="Test")
        result = research_service.resolve_approval(project.id, "nonexistent-approval-id", approved=True)
        assert result is None

    def test_advance_nonexistent_project(self, research_service: ResearchOrchestratorService) -> None:
        """Test advancing a nonexistent project returns error."""
        result = research_service.advance_research("nonexistent-project-id")
        assert "error" in result
        assert result["error"] == "Project not found"

    def test_human_message_nonexistent_project(self, research_service: ResearchOrchestratorService) -> None:
        """Test sending a message to a nonexistent project returns None."""
        result = research_service.human_message("nonexistent-project-id", "Hello")
        assert result is None


class TestResearchServiceWithoutRepository:
    """Test ResearchOrchestratorService without repository (in-memory mode)."""

    def test_in_memory_operations(self, research_service_no_repo: ResearchOrchestratorService) -> None:
        """Test that service works without repository in memory-only mode."""
        # Create project
        project = research_service_no_repo.create_project(
            title="In-Memory Project",
            description="No persistence",
        )
        assert project is not None

        # Add theme
        theme = research_service_no_repo.add_theme(
            project.id,
            title="Theme",
            description="In-memory theme",
        )
        assert theme is not None

        # Activate
        activated = research_service_no_repo.activate_theme(project.id, theme.id)
        assert activated is not None
        assert activated.status == ThemeStatus.ACTIVE

        # List projects
        projects = research_service_no_repo.list_projects()
        assert len(projects) == 1
        assert projects[0].id == project.id

        # Delete
        deleted = research_service_no_repo.delete_project(project.id)
        assert deleted is True

        # Verify gone
        assert research_service_no_repo.get_project(project.id) is None
        assert len(research_service_no_repo.list_projects()) == 0

    def test_in_memory_no_persistence(self, research_service_no_repo: ResearchOrchestratorService) -> None:
        """Test that in-memory mode doesn't persist to repository."""
        # Create project
        project = research_service_no_repo.create_project(
            title="Temporary",
            description="Will not persist",
        )

        # Create new service instance (no repository)
        new_service = ResearchOrchestratorService(repository=None)

        # Project should not be available in new instance
        result = new_service.get_project(project.id)
        assert result is None

    def test_background_reference_dedupes_minor_variations(self, research_service: ResearchOrchestratorService) -> None:
        """Test that near-identical grounding is stored once."""
        workspace_id = "workspace-background-dedupe"
        research_service.record_background_reference(
            workspace_id=workspace_id,
            focus_area="boundary discipline",
            source="https://example.com/boundary-note",
            content="Keep one verified boundary before widening scope.",
            trust_score=0.9,
            tags=["background", "grounding"],
        )
        research_service.record_background_reference(
            workspace_id=workspace_id,
            focus_area="boundary discipline",
            source="https://example.com/boundary-note",
            content="Keep the verified boundary before widening the scope!",
            trust_score=0.88,
            tags=["background", "grounding"],
        )

        references = research_service.recent_background_references(
            workspace_id=workspace_id,
            focus_area="boundary discipline",
            min_confidence=0.3,
            limit=10,
        )

        assert len(references) == 1
        assert references[0]["duplicate_key"]

    def test_recent_background_references_exposes_evidence_summary(self, research_service: ResearchOrchestratorService) -> None:
        """Test that the first-screen projection can avoid repeating the raw lead."""
        workspace_id = "workspace-background-evidence"
        research_service.record_background_reference(
            workspace_id=workspace_id,
            focus_area="evidence projection",
            source="https://example.com/evidence-note",
            content="Evidence note: one narrow boundary is enough.\nThis line explains the concrete proof path.",
            trust_score=0.91,
            tags=["background", "grounding"],
        )

        references = research_service.recent_background_references(
            workspace_id=workspace_id,
            focus_area="evidence projection",
            min_confidence=0.3,
            limit=10,
        )

        assert len(references) == 1
        assert references[0]["snippet"].startswith("Evidence note:")
        assert references[0]["evidence_summary"]
        assert references[0]["evidence_summary"] != references[0]["snippet"]
        assert "proof path" in references[0]["evidence_summary"].lower()

    def test_record_background_reference_upgrades_existing_entry_summary(self, research_service: ResearchOrchestratorService) -> None:
        """Test that re-recording an existing grounding entry backfills the summary projection."""
        workspace_id = "workspace-background-upgrade"
        first = research_service.record_background_reference(
            workspace_id=workspace_id,
            focus_area="upgrade path",
            source="https://example.com/upgrade-note",
            content="Upgrade note: one narrow boundary is enough.\nThe concrete proof path is here.",
            trust_score=0.9,
            tags=["background", "grounding"],
        )
        assert first.evidence_summary
        first.evidence_summary = ""

        second = research_service.record_background_reference(
            workspace_id=workspace_id,
            focus_area="upgrade path",
            source="https://example.com/upgrade-note",
            content="Upgrade note: one narrow boundary is enough.\nThe concrete proof path is here.",
            trust_score=0.88,
            tags=["background", "grounding"],
        )

        assert second.id == first.id
        assert second.evidence_summary


class TestResearchStateRetrieval:
    """Test state retrieval and serialization."""

    def test_get_state(self, research_service: ResearchOrchestratorService) -> None:
        """Test getting full project state."""
        project = research_service.create_project(
            title="State Test",
            description="Testing state retrieval",
        )
        theme = research_service.add_theme(
            project.id,
            title="Theme",
            description="For state test",
        )
        assert theme is not None
        research_service.activate_theme(project.id, theme.id)

        state = research_service.get_state(project.id)
        assert state is not None
        assert "project" in state
        assert "schedule_status" in state
        assert state["project"]["id"] == project.id

    def test_get_state_nonexistent(self, research_service: ResearchOrchestratorService) -> None:
        """Test getting state for nonexistent project returns None."""
        state = research_service.get_state("nonexistent-id")
        assert state is None

    def test_list_projects_empty(self, research_service: ResearchOrchestratorService) -> None:
        """Test listing projects when empty."""
        projects = research_service.list_projects()
        assert projects == []

    def test_list_projects_multiple(self, research_service: ResearchOrchestratorService) -> None:
        """Test listing multiple projects."""
        p1 = research_service.create_project(title="Project 1", description="First")
        p2 = research_service.create_project(title="Project 2", description="Second")
        p3 = research_service.create_project(title="Project 3", description="Third")

        projects = research_service.list_projects()
        assert len(projects) == 3

        ids = {p.id for p in projects}
        assert p1.id in ids
        assert p2.id in ids
        assert p3.id in ids
