"""Comprehensive tests for ResearchRepository CRUD operations."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.db.research_repository import ResearchRepository
from app.research.models import (
    AgentRole,
    AgentState,
    Approval,
    ApprovalStatus,
    Artifact,
    ArtifactKind,
    Checkpoint,
    Finding,
    ResearchProject,
    ResearchTheme,
    ResearchThread,
    ScheduleCadence,
    ScheduleSpec,
    ThemeStatus,
    ThinkingEntry,
    ThreadDepth,
    WorkbenchGate,
    utc_now,
)


@pytest.fixture
def repo(tmp_path: Path) -> ResearchRepository:
    return ResearchRepository(tmp_path / "test_research.db")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project() -> ResearchProject:
    return ResearchProject.create(title="Test Project", description="A test project")


def _make_theme() -> ResearchTheme:
    return ResearchTheme.create(
        title="Test Theme",
        description="A test theme",
        duration_weeks=2,
        cadence=ScheduleCadence.WEEKLY,
    )


def _make_thread() -> ResearchThread:
    return ResearchThread.create(angle="Test angle", depth=ThreadDepth.DEEP)


def _make_finding() -> Finding:
    return Finding.create(content="Test finding", source="Test source", confidence=0.9, tags=["tag1", "tag2"])


def _make_artifact() -> Artifact:
    return Artifact.create(title="Test Report", kind=ArtifactKind.REPORT, content="# Report content")


def _make_checkpoint() -> Checkpoint:
    return Checkpoint.create(label="Checkpoint 1", due_date=utc_now() + timedelta(days=7))


def _make_approval() -> Approval:
    return Approval.create(title="Approve this?", description="Please review", agent_context={"key": "value"})


# ===========================================================================
# TestProjectCRUD
# ===========================================================================


class TestProjectCRUD:
    def test_save_and_get(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)

        loaded = repo.get_project(project.id)
        assert loaded is not None
        assert loaded.id == project.id
        assert loaded.title == project.title
        assert loaded.description == project.description

    def test_get_nonexistent_returns_none(self, repo: ResearchRepository) -> None:
        assert repo.get_project("nonexistent") is None

    def test_list_projects(self, repo: ResearchRepository) -> None:
        p1 = _make_project()
        p2 = ResearchProject.create(title="Second", description="Second project")
        repo.save_project(p1)
        repo.save_project(p2)

        projects = repo.list_projects()
        assert len(projects) == 2
        ids = {p.id for p in projects}
        assert p1.id in ids
        assert p2.id in ids

    def test_delete_project(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        assert repo.delete_project(project.id) is True
        assert repo.get_project(project.id) is None

    def test_delete_nonexistent_returns_false(self, repo: ResearchRepository) -> None:
        assert repo.delete_project("nonexistent") is False

    def test_save_updates_existing(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)

        project.title = "Updated Title"
        repo.save_project(project)

        loaded = repo.get_project(project.id)
        assert loaded is not None
        assert loaded.title == "Updated Title"

    def test_cascade_delete_removes_themes(self, repo: ResearchRepository) -> None:
        project = _make_project()
        theme = _make_theme()
        project.themes.append(theme)
        repo.save_project(project)
        repo.save_theme(project.id, theme)

        repo.delete_project(project.id)
        assert repo.get_themes_by_project(project.id) == []

    def test_cascade_delete_removes_agent_state(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        repo.save_agent_state(project.id, project.agent_state)

        repo.delete_project(project.id)
        assert repo.get_agent_state(project.id) is None


# ===========================================================================
# TestThemeCRUD
# ===========================================================================


class TestThemeCRUD:
    def test_save_and_get(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        repo.save_theme(project.id, theme)

        themes = repo.get_themes_by_project(project.id)
        assert len(themes) == 1
        assert themes[0].id == theme.id
        assert themes[0].title == theme.title
        assert themes[0].description == theme.description

    def test_get_themes_empty(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        assert repo.get_themes_by_project(project.id) == []

    def test_update_theme_status(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        repo.save_theme(project.id, theme)

        repo.update_theme_status(theme.id, ThemeStatus.ACTIVE)

        themes = repo.get_themes_by_project(project.id)
        assert themes[0].status == ThemeStatus.ACTIVE

    def test_update_theme_status_nonexistent(self, repo: ResearchRepository) -> None:
        # Should not raise
        repo.update_theme_status("nonexistent", ThemeStatus.ACTIVE)

    def test_save_theme_with_schedule(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        assert theme.schedule is not None
        repo.save_theme(project.id, theme)

        themes = repo.get_themes_by_project(project.id)
        assert themes[0].schedule is not None
        assert len(themes[0].schedule.checkpoints) == len(theme.schedule.checkpoints)


# ===========================================================================
# TestThreadCRUD
# ===========================================================================


class TestThreadCRUD:
    def test_save_and_get(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        repo.save_theme(project.id, theme)
        thread = _make_thread()
        repo.save_thread(project.id, theme.id, thread)

        threads = repo.get_threads_by_theme(theme.id)
        assert len(threads) == 1
        assert threads[0].id == thread.id
        assert threads[0].angle == thread.angle
        assert threads[0].depth == thread.depth

    def test_get_threads_empty(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        repo.save_theme(project.id, theme)
        assert repo.get_threads_by_theme(theme.id) == []


# ===========================================================================
# TestFindingCRUD
# ===========================================================================


class TestFindingCRUD:
    def test_save_and_get(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        repo.save_theme(project.id, theme)
        thread = _make_thread()
        repo.save_thread(project.id, theme.id, thread)
        finding = _make_finding()
        repo.save_finding(project.id, theme.id, thread.id, finding)

        findings = repo.get_findings_by_thread(thread.id)
        assert len(findings) == 1
        assert findings[0].id == finding.id
        assert findings[0].content == finding.content
        assert findings[0].confidence == finding.confidence
        assert findings[0].tags == finding.tags

    def test_get_findings_empty(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        repo.save_theme(project.id, theme)
        thread = _make_thread()
        repo.save_thread(project.id, theme.id, thread)
        assert repo.get_findings_by_thread(thread.id) == []


# ===========================================================================
# TestArtifactCRUD
# ===========================================================================


class TestArtifactCRUD:
    def test_save_and_get(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        repo.save_theme(project.id, theme)
        artifact = _make_artifact()
        repo.save_artifact(project.id, theme.id, artifact)

        artifacts = repo.get_artifacts_by_theme(theme.id)
        assert len(artifacts) == 1
        assert artifacts[0].id == artifact.id
        assert artifacts[0].title == artifact.title
        assert artifacts[0].kind == artifact.kind
        assert artifacts[0].content == artifact.content

    def test_get_artifacts_empty(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        repo.save_theme(project.id, theme)
        assert repo.get_artifacts_by_theme(theme.id) == []


# ===========================================================================
# TestCheckpointCRUD
# ===========================================================================


class TestCheckpointCRUD:
    def test_save_and_get(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        repo.save_theme(project.id, theme)
        cp = _make_checkpoint()
        repo.save_checkpoint(project.id, theme.id, cp)

        checkpoints = repo.get_checkpoints_by_theme(theme.id)
        assert len(checkpoints) == 1
        assert checkpoints[0].id == cp.id
        assert checkpoints[0].label == cp.label
        assert checkpoints[0].completed is False

    def test_update_checkpoint_completion(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        repo.save_theme(project.id, theme)
        cp = _make_checkpoint()
        repo.save_checkpoint(project.id, theme.id, cp)

        now_iso = utc_now().isoformat()
        repo.update_checkpoint(cp.id, completed=True, completed_at=now_iso)

        checkpoints = repo.get_checkpoints_by_theme(theme.id)
        assert checkpoints[0].completed is True
        assert checkpoints[0].completed_at is not None

    def test_update_checkpoint_nonexistent(self, repo: ResearchRepository) -> None:
        # Should not raise
        repo.update_checkpoint("nonexistent", completed=True, completed_at=None)

    def test_get_checkpoints_empty(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        repo.save_theme(project.id, theme)
        assert repo.get_checkpoints_by_theme(theme.id) == []


# ===========================================================================
# TestApprovalCRUD
# ===========================================================================


class TestApprovalCRUD:
    def test_save_and_get_pending(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        approval = _make_approval()
        repo.save_approval(project.id, approval)

        pending = repo.get_pending_approvals(project.id)
        assert len(pending) == 1
        assert pending[0].id == approval.id
        assert pending[0].status == ApprovalStatus.PENDING

    def test_resolve_approval_approved(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        approval = _make_approval()
        repo.save_approval(project.id, approval)

        repo.resolve_approval(approval.id, approved=True)

        pending = repo.get_pending_approvals(project.id)
        assert len(pending) == 0

    def test_resolve_approval_rejected(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        approval = _make_approval()
        repo.save_approval(project.id, approval)

        repo.resolve_approval(approval.id, approved=False)

        pending = repo.get_pending_approvals(project.id)
        assert len(pending) == 0

    def test_resolve_nonexistent_approval(self, repo: ResearchRepository) -> None:
        # Should not raise
        repo.resolve_approval("nonexistent", approved=True)

    def test_get_pending_approvals_empty(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        assert repo.get_pending_approvals(project.id) == []


# ===========================================================================
# TestGateMessageCRUD
# ===========================================================================


class TestGateMessageCRUD:
    def test_save_and_get(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        msg = {
            "id": "gate_msg_abc123",
            "role": "human",
            "content": "Hello agent",
            "timestamp": utc_now().isoformat(),
            "metadata": {"key": "value"},
        }
        repo.save_gate_message(project.id, msg)

        messages = repo.get_gate_messages(project.id)
        assert len(messages) == 1
        assert messages[0]["role"] == "human"
        assert messages[0]["content"] == "Hello agent"
        assert messages[0]["metadata"] == {"key": "value"}

    def test_get_gate_messages_empty(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        assert repo.get_gate_messages(project.id) == []

    def test_multiple_messages(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        for i in range(3):
            repo.save_gate_message(project.id, {
                "id": f"gate_msg_{i}",
                "role": "agent",
                "content": f"Message {i}",
                "timestamp": utc_now().isoformat(),
                "metadata": {},
            })

        messages = repo.get_gate_messages(project.id)
        assert len(messages) == 3


# ===========================================================================
# TestAgentStateCRUD
# ===========================================================================


class TestAgentStateCRUD:
    def test_save_and_get(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        state = AgentState()
        state.switch_role(AgentRole.EDITOR)
        state.add_thinking(
            role=AgentRole.RESEARCHER,
            question="What?",
            reasoning="Because",
            conclusion="Therefore",
        )
        state.add_pending_question("Why?")
        state.increment_review()
        repo.save_agent_state(project.id, state)

        loaded = repo.get_agent_state(project.id)
        assert loaded is not None
        assert loaded.current_role == AgentRole.EDITOR
        assert len(loaded.thinking_log) == 1
        assert loaded.thinking_log[0].question == "What?"
        assert loaded.pending_questions == ["Why?"]
        assert loaded.self_review_count == 1
        assert loaded.current_iteration == 1

    def test_get_agent_state_nonexistent(self, repo: ResearchRepository) -> None:
        assert repo.get_agent_state("nonexistent") is None

    def test_update_agent_state(self, repo: ResearchRepository) -> None:
        project = _make_project()
        repo.save_project(project)
        state = AgentState()
        repo.save_agent_state(project.id, state)

        state.switch_role(AgentRole.CRITIC)
        state.increment_review()
        repo.save_agent_state(project.id, state)

        loaded = repo.get_agent_state(project.id)
        assert loaded is not None
        assert loaded.current_role == AgentRole.CRITIC
        assert loaded.self_review_count == 1


# ===========================================================================
# TestFullRoundTrip
# ===========================================================================


class TestFullRoundTrip:
    def test_persist_and_rebuild_full_project(self, repo: ResearchRepository) -> None:
        """Create a full project with nested data, persist, reload, and verify identity."""
        # Build a rich project
        project = ResearchProject.create(title="Full Round Trip", description="Complete project test")

        # Add a theme with schedule
        theme = project.add_theme(
            title="Deep Analysis",
            description="Comprehensive analysis theme",
            duration_weeks=2,
            cadence=ScheduleCadence.WEEKLY,
        )
        project.activate_theme(theme.id)

        # Add a thread with findings
        thread = theme.add_thread(angle="Historical trends", depth=ThreadDepth.DEEP)
        theme.add_finding(
            thread_id=thread.id,
            content="Key historical pattern found",
            source="Archive data",
            confidence=0.92,
            tags=["historical", "verified"],
        )
        theme.add_finding(
            thread_id=thread.id,
            content="Secondary pattern",
            source="Literature review",
            confidence=0.75,
            tags=["secondary"],
        )

        # Add an artifact
        theme.add_artifact(title="Analysis Report", kind=ArtifactKind.REPORT, content="# Analysis\n\nDetailed findings...")

        # Add agent state
        project.agent_state.switch_role(AgentRole.EDITOR)
        project.agent_state.add_thinking(
            role=AgentRole.RESEARCHER,
            question="What patterns emerge?",
            reasoning="Cross-referencing data",
            conclusion="Strong correlation found",
        )
        project.agent_state.add_pending_question("How to validate?")
        project.agent_state.increment_review()

        # Add gate messages and approvals
        project.gate.add_message("human", "Start the analysis")
        project.gate.add_message("agent", "Analysis underway")
        project.gate.add_notification("Theme activated")
        approval = project.gate.request_approval(
            title="Approve analysis plan?",
            description="Ready to proceed with deep analysis",
            agent_context={"theme_id": theme.id},
        )

        # --- Persist everything ---
        repo.save_project(project)
        repo.save_theme(project.id, theme)
        repo.save_thread(project.id, theme.id, thread)
        for finding in thread.findings:
            repo.save_finding(project.id, theme.id, thread.id, finding)
        for artifact in theme.artifacts:
            repo.save_artifact(project.id, theme.id, artifact)
        if theme.schedule:
            for cp in theme.schedule.checkpoints:
                repo.save_checkpoint(project.id, theme.id, cp)
        repo.save_agent_state(project.id, project.agent_state)
        for msg in project.gate.messages:
            repo.save_gate_message(project.id, msg)
        repo.save_approval(project.id, approval)

        # --- Reload and verify ---
        loaded_project = repo.get_project(project.id)
        assert loaded_project is not None
        assert loaded_project.id == project.id
        assert loaded_project.title == "Full Round Trip"
        assert loaded_project.description == "Complete project test"

        # Verify themes
        loaded_themes = repo.get_themes_by_project(project.id)
        assert len(loaded_themes) == 1
        loaded_theme = loaded_themes[0]
        assert loaded_theme.title == "Deep Analysis"
        assert loaded_theme.status == ThemeStatus.ACTIVE

        # Verify threads
        loaded_threads = repo.get_threads_by_theme(theme.id)
        assert len(loaded_threads) == 1
        loaded_thread = loaded_threads[0]
        assert loaded_thread.angle == "Historical trends"
        assert loaded_thread.depth == ThreadDepth.DEEP

        # Verify findings
        loaded_findings = repo.get_findings_by_thread(thread.id)
        assert len(loaded_findings) == 2
        assert loaded_findings[0].content == "Key historical pattern found"
        assert loaded_findings[0].confidence == 0.92
        assert loaded_findings[0].tags == ["historical", "verified"]
        assert loaded_findings[1].content == "Secondary pattern"

        # Verify artifacts
        loaded_artifacts = repo.get_artifacts_by_theme(theme.id)
        assert len(loaded_artifacts) == 1
        assert loaded_artifacts[0].title == "Analysis Report"
        assert loaded_artifacts[0].kind == ArtifactKind.REPORT

        # Verify checkpoints
        loaded_cps = repo.get_checkpoints_by_theme(theme.id)
        assert len(loaded_cps) == len(theme.schedule.checkpoints) if theme.schedule else 0

        # Verify agent state
        loaded_state = repo.get_agent_state(project.id)
        assert loaded_state is not None
        assert loaded_state.current_role == AgentRole.EDITOR
        assert len(loaded_state.thinking_log) == 1
        assert loaded_state.thinking_log[0].question == "What patterns emerge?"
        assert loaded_state.pending_questions == ["How to validate?"]
        assert loaded_state.self_review_count == 1

        # Verify gate messages
        loaded_msgs = repo.get_gate_messages(project.id)
        # project.create adds system message, add_theme adds agent message, plus our 2 explicit messages
        assert len(loaded_msgs) == 4
        msg_roles = [m["role"] for m in loaded_msgs]
        assert "system" in msg_roles
        assert "human" in msg_roles
        assert "agent" in msg_roles

        # Verify approvals
        loaded_pending = repo.get_pending_approvals(project.id)
        assert len(loaded_pending) == 1
        assert loaded_pending[0].title == "Approve analysis plan?"

    def test_round_trip_preserves_datetime_precision(self, repo: ResearchRepository) -> None:
        """Verify datetime fields survive serialization round-trip."""
        project = _make_project()
        original_created = project.created_at
        repo.save_project(project)

        loaded = repo.get_project(project.id)
        assert loaded is not None
        assert loaded.created_at == original_created

    def test_round_trip_preserves_enum_values(self, repo: ResearchRepository) -> None:
        """Verify enum fields survive serialization round-trip."""
        project = _make_project()
        repo.save_project(project)
        state = AgentState()
        state.switch_role(AgentRole.SYNTHESIZER)
        repo.save_agent_state(project.id, state)

        loaded = repo.get_agent_state(project.id)
        assert loaded is not None
        assert loaded.current_role == AgentRole.SYNTHESIZER

    def test_cascade_delete_removes_all_children(self, repo: ResearchRepository) -> None:
        """Deleting a project should cascade to all child tables."""
        project = _make_project()
        repo.save_project(project)
        theme = _make_theme()
        repo.save_theme(project.id, theme)
        thread = _make_thread()
        repo.save_thread(project.id, theme.id, thread)
        finding = _make_finding()
        repo.save_finding(project.id, theme.id, thread.id, finding)
        artifact = _make_artifact()
        repo.save_artifact(project.id, theme.id, artifact)
        cp = _make_checkpoint()
        repo.save_checkpoint(project.id, theme.id, cp)
        approval = _make_approval()
        repo.save_approval(project.id, approval)
        repo.save_gate_message(project.id, {
            "id": "gate_msg_test",
            "role": "human",
            "content": "Hello",
            "timestamp": utc_now().isoformat(),
            "metadata": {},
        })
        repo.save_agent_state(project.id, project.agent_state)

        # Delete project
        repo.delete_project(project.id)

        # Verify all child records are gone
        assert repo.get_themes_by_project(project.id) == []
        assert repo.get_threads_by_theme(theme.id) == []
        assert repo.get_findings_by_thread(thread.id) == []
        assert repo.get_artifacts_by_theme(theme.id) == []
        assert repo.get_checkpoints_by_theme(theme.id) == []
        assert repo.get_pending_approvals(project.id) == []
        assert repo.get_gate_messages(project.id) == []
        assert repo.get_agent_state(project.id) is None


# ===========================================================================
# TestFromDictRoundTrip
# ===========================================================================


class TestFromDictRoundTrip:
    """Verify that to_full_dict() → from_dict() produces identical objects."""

    def test_checkpoint_round_trip(self) -> None:
        cp = Checkpoint.create(label="Test CP", due_date=utc_now() + timedelta(days=3))
        cp.completed = True
        cp.completed_at = utc_now()
        cp.notes = "Some notes"
        restored = Checkpoint.from_dict(cp.to_full_dict())
        assert restored.id == cp.id
        assert restored.label == cp.label
        assert restored.completed == cp.completed
        assert restored.completed_at is not None
        assert restored.notes == cp.notes

    def test_schedule_spec_round_trip(self) -> None:
        spec = ScheduleSpec.create(duration_weeks=4, cadence=ScheduleCadence.BIWEEKLY)
        restored = ScheduleSpec.from_dict(spec.to_full_dict())
        assert restored.cadence == spec.cadence
        assert len(restored.checkpoints) == len(spec.checkpoints)

    def test_finding_round_trip(self) -> None:
        f = Finding.create(content="Test", source="Src", confidence=0.8, tags=["a", "b"])
        restored = Finding.from_dict(f.to_full_dict())
        assert restored.id == f.id
        assert restored.content == f.content
        assert restored.confidence == f.confidence
        assert restored.tags == f.tags

    def test_artifact_round_trip(self) -> None:
        a = Artifact.create(title="Doc", kind=ArtifactKind.DRAFT, content="Draft content")
        restored = Artifact.from_dict(a.to_full_dict())
        assert restored.id == a.id
        assert restored.kind == ArtifactKind.DRAFT
        assert restored.content == a.content

    def test_thread_round_trip(self) -> None:
        t = ResearchThread.create(angle="Test", depth=ThreadDepth.SHALLOW)
        t.findings.append(Finding.create(content="F1", source="S1"))
        restored = ResearchThread.from_dict(t.to_full_dict())
        assert restored.angle == t.angle
        assert restored.depth == ThreadDepth.SHALLOW
        assert len(restored.findings) == 1

    def test_thinking_entry_round_trip(self) -> None:
        te = ThinkingEntry.create(role=AgentRole.CRITIC, question="Q", reasoning="R", conclusion="C")
        restored = ThinkingEntry.from_dict(te.to_full_dict())
        assert restored.role == AgentRole.CRITIC
        assert restored.question == "Q"

    def test_agent_state_round_trip(self) -> None:
        s = AgentState()
        s.switch_role(AgentRole.EDITOR)
        s.add_thinking(role=AgentRole.RESEARCHER, question="Q", reasoning="R", conclusion="C")
        s.add_pending_question("PQ1")
        s.increment_review()
        restored = AgentState.from_dict(s.to_full_dict())
        assert restored.current_role == AgentRole.EDITOR
        assert len(restored.thinking_log) == 1
        assert restored.pending_questions == ["PQ1"]
        assert restored.self_review_count == 1

    def test_approval_round_trip(self) -> None:
        a = Approval.create(title="T", description="D", agent_context={"k": "v"})
        a.approve()
        restored = Approval.from_dict(a.to_full_dict())
        assert restored.status == ApprovalStatus.APPROVED
        assert restored.resolved_at is not None
        assert restored.agent_context == {"k": "v"}

    def test_workbench_gate_round_trip(self) -> None:
        g = WorkbenchGate()
        g.add_message("human", "Hello")
        g.add_notification("Notif")
        g.request_approval(title="A", description="D")
        restored = WorkbenchGate.from_dict(g.to_full_dict())
        assert len(restored.messages) == 1
        assert len(restored.notifications) == 1
        assert len(restored.approvals) == 1

    def test_research_theme_round_trip(self) -> None:
        t = ResearchTheme.create(title="T", description="D", duration_weeks=2, cadence=ScheduleCadence.WEEKLY)
        t.activate()
        t.add_thread(angle="A1", depth=ThreadDepth.DEEP)
        t.add_finding(thread_id=t.threads[0].id, content="F1", source="S1")
        t.add_artifact(title="Art", kind=ArtifactKind.SUMMARY, content="C")
        restored = ResearchTheme.from_dict(t.to_full_dict())
        assert restored.title == t.title
        assert restored.status == ThemeStatus.ACTIVE
        assert len(restored.threads) == 1
        assert len(restored.threads[0].findings) == 1
        assert len(restored.artifacts) == 1
        assert restored.schedule is not None

    def test_research_project_round_trip(self) -> None:
        p = ResearchProject.create(title="P", description="D")
        p.add_theme(title="T1", description="D1", duration_weeks=2)
        p.agent_state.switch_role(AgentRole.EDITOR)
        p.gate.add_message("human", "Hi")
        restored = ResearchProject.from_dict(p.to_full_dict())
        assert restored.title == p.title
        assert len(restored.themes) == 1
        assert restored.agent_state.current_role == AgentRole.EDITOR
        assert len(restored.gate.messages) >= 1
