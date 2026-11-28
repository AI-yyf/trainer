"""(s) Research: the coach's preparation engine is deterministic, grounded and owned
    by its workspace.

Guarantees covered:
  * the research scheduler and repository are deterministic and owner-scoped;
  * briefs and their assets persist as traceable library assets;
  * literature verification layers are deterministic locally and honest about what was not verified.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_research_repository.py
  * server/tests/test_research_flow_integration.py
  * server/tests/test_research_scheduler_properties.py
  * server/tests/test_research.py
  * server/tests/test_research_briefing.py
  * server/tests/test_literature_verifier.py
"""

from __future__ import annotations

import unittest
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.db.research_repository import ResearchRepository
from app.evaluator.hooks import (
    BannedPhrasesHook,
    ParagraphStructureHook,
    QuoteBalanceHook,
    WordCountHook,
    hooks_from_card_config,
    unit_count,
)
from app.evaluator.models import CheckStatus
from app.evaluator.verifiers import LocalRubricReviewer, RubricItem, RubricSpec, combine_verdict
from app.pedagogy.research_hints import collect_research_hints
from app.pedagogy.stage_material_composer import StageMaterialComposer
from app.research.briefing import ProviderRoleBriefing
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
from app.research.scheduler import ResearchScheduler
from app.research.service import ResearchOrchestratorService

# ---------------------------------------------------------------------------
# Restored from test_research_repository.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> ResearchRepository:
    return ResearchRepository(tmp_path / "test_research.db")


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


# ---------------------------------------------------------------------------
# Restored from test_research_flow_integration.py (commit df0a3e2a^)
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


# ---------------------------------------------------------------------------
# Restored from test_research_scheduler_properties.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


# Custom strategies for generating test data
@st.composite
def valid_duration_weeks(draw):
    """Generate valid duration in weeks (1-52)."""
    return draw(st.integers(min_value=1, max_value=52))


@st.composite
def schedule_cadence(draw):
    """Generate a valid ScheduleCadence."""
    return draw(st.sampled_from([
        ScheduleCadence.DAILY,
        ScheduleCadence.WEEKLY,
        ScheduleCadence.BIWEEKLY,
        ScheduleCadence.MONTHLY,
    ]))


@st.composite
def research_theme(draw):
    """Generate a ResearchTheme with random parameters."""
    duration_weeks = draw(st.integers(min_value=1, max_value=12))
    cadence = draw(schedule_cadence())
    theme = ResearchTheme.create(
        title=f"Theme {draw(st.integers(min_value=1, max_value=100))}",
        description="Test theme",
        duration_weeks=duration_weeks,
        cadence=cadence,
    )
    # Optionally activate
    if draw(st.booleans()):
        theme.activate()
    return theme


@st.composite
def research_theme_with_progress(draw):
    """Generate a ResearchTheme with some checkpoints completed."""
    duration_weeks = draw(st.integers(min_value=1, max_value=12))
    cadence = draw(schedule_cadence())
    theme = ResearchTheme.create(
        title="Test Theme",
        description="Test",
        duration_weeks=duration_weeks,
        cadence=cadence,
    )
    # Complete some checkpoints
    if theme.schedule and theme.schedule.checkpoints:
        num_to_complete = draw(st.integers(min_value=0, max_value=len(theme.schedule.checkpoints)))
        for i in range(num_to_complete):
            theme.schedule.checkpoints[i].completed = True
    return theme


class TestResearchSchedulerProperties:
    """Property-based tests for ResearchScheduler."""

    @given(
        duration_weeks=valid_duration_weeks(),
        cadence=schedule_cadence(),
    )
    @settings(max_examples=50)
    def test_checkpoint_count_matches_duration(self, duration_weeks, cadence):
        """Property: More weeks -> more checkpoints (proportional to cadence)."""
        schedule = ScheduleSpec.create(duration_weeks=duration_weeks, cadence=cadence)
        
        # Calculate expected checkpoint count based on cadence
        if cadence == ScheduleCadence.DAILY:
            expected_max = duration_weeks * 7
        elif cadence == ScheduleCadence.WEEKLY:
            expected_max = duration_weeks
        elif cadence == ScheduleCadence.BIWEEKLY:
            expected_max = duration_weeks // 2 + (1 if duration_weeks % 2 else 0)
        else:  # MONTHLY
            expected_max = duration_weeks // 4 + (1 if duration_weeks % 4 else 0)
        
        # Checkpoint count should be reasonable
        assert len(schedule.checkpoints) >= 0
        assert len(schedule.checkpoints) <= expected_max + 1  # Allow for boundary conditions

    @given(
        duration_weeks=valid_duration_weeks(),
        cadence=schedule_cadence(),
    )
    @settings(max_examples=50)
    def test_checkpoint_dates_monotonic(self, duration_weeks, cadence):
        """Property: Checkpoint due dates should increase monotonically."""
        schedule = ScheduleSpec.create(duration_weeks=duration_weeks, cadence=cadence)
        
        for i in range(1, len(schedule.checkpoints)):
            assert schedule.checkpoints[i].due_date >= schedule.checkpoints[i - 1].due_date

    @given(
        theme=research_theme_with_progress(),
    )
    @settings(max_examples=50)
    def test_progress_calculation(self, theme):
        """Property: Progress should be in [0.0, 100.0]."""
        progress = ResearchScheduler.progress_percentage(theme)
        assert 0.0 <= progress <= 100.0

    @given(
        theme=research_theme_with_progress(),
    )
    @settings(max_examples=50)
    def test_progress_calculation_consistency(self, theme):
        """Property: Progress should match actual completed checkpoints."""
        if not theme.schedule or not theme.schedule.checkpoints:
            progress = ResearchScheduler.progress_percentage(theme)
            assert progress == 0.0
        else:
            completed = sum(1 for cp in theme.schedule.checkpoints if cp.completed)
            total = len(theme.schedule.checkpoints)
            expected_progress = (completed / total) * 100 if total > 0 else 0.0
            progress = ResearchScheduler.progress_percentage(theme)
            assert abs(progress - expected_progress) < 0.01

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_should_advance_only_for_active_themes(self, theme):
        """Property: should_advance should only return True for active themes."""
        result = ResearchScheduler.should_advance(theme)
        if theme.status != ThemeStatus.ACTIVE:
            assert result is False

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_schedule_status_has_required_fields(self, theme):
        """Property: schedule_status should return all required fields."""
        status = ResearchScheduler.schedule_status(theme)
        
        assert "theme_id" in status
        assert "theme_title" in status
        assert "status" in status
        assert "duration_weeks" in status
        assert "progress_percentage" in status
        assert "time_elapsed_percentage" in status
        assert "next_checkpoint" in status
        assert "overdue_checkpoints" in status
        assert "threads_count" in status
        assert "artifacts_count" in status

    @given(
        duration_weeks=valid_duration_weeks(),
        cadence=schedule_cadence(),
    )
    @settings(max_examples=50)
    def test_schedule_duration_matches_weeks(self, duration_weeks, cadence):
        """Property: Schedule duration should match specified weeks."""
        schedule = ScheduleSpec.create(duration_weeks=duration_weeks, cadence=cadence)
        expected_duration = timedelta(weeks=duration_weeks)
        
        # Allow for small floating point differences
        assert abs((schedule.duration - expected_duration).total_seconds()) < 1

    @given(
        theme=research_theme_with_progress(),
    )
    @settings(max_examples=50)
    def test_time_elapsed_in_valid_range(self, theme):
        """Property: Time elapsed percentage should be in [0.0, 100.0]."""
        elapsed = ResearchScheduler.time_elapsed_percentage(theme)
        assert 0.0 <= elapsed <= 100.0

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_mark_checkpoint_complete_idempotent(self, theme):
        """Property: Marking same checkpoint complete twice should return False."""
        if not theme.schedule or not theme.schedule.checkpoints:
            return
        
        cp_id = theme.schedule.checkpoints[0].id
        # First mark
        result1 = ResearchScheduler.mark_checkpoint_complete(theme, cp_id)
        # Second mark (should return False since already completed)
        result2 = ResearchScheduler.mark_checkpoint_complete(theme, cp_id)
        
        assert result1 is True
        assert result2 is False

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_next_checkpoint_returns_valid_structure(self, theme):
        """Property: next_checkpoint should return valid structure if checkpoint exists."""
        theme.activate()
        next_cp = ResearchScheduler.next_checkpoint(theme)
        
        if next_cp is not None:
            assert "id" in next_cp
            assert "label" in next_cp
            assert "due_date" in next_cp
            assert "days_remaining" in next_cp

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_overdue_checkpoints_returns_list(self, theme):
        """Property: overdue_checkpoints should always return a list."""
        theme.activate()
        overdue = ResearchScheduler.overdue_checkpoints(theme)
        assert isinstance(overdue, list)

    @given(
        duration_weeks=valid_duration_weeks(),
        cadence=schedule_cadence(),
    )
    @settings(max_examples=50)
    def test_checkpoints_have_valid_ids(self, duration_weeks, cadence):
        """Property: All checkpoints should have valid IDs."""
        schedule = ScheduleSpec.create(duration_weeks=duration_weeks, cadence=cadence)
        
        for cp in schedule.checkpoints:
            assert cp.id.startswith("cp_")
            assert len(cp.id) > 3

    @given(
        duration_weeks=valid_duration_weeks(),
        cadence=schedule_cadence(),
    )
    @settings(max_examples=50)
    def test_checkpoints_have_labels(self, duration_weeks, cadence):
        """Property: All checkpoints should have non-empty labels."""
        schedule = ScheduleSpec.create(duration_weeks=duration_weeks, cadence=cadence)
        
        for cp in schedule.checkpoints:
            assert len(cp.label) > 0

    @given(
        theme=research_theme_with_progress(),
    )
    @settings(max_examples=50)
    def test_progress_increases_with_completed_checkpoints(self, theme):
        """Property: More completed checkpoints -> higher progress."""
        if not theme.schedule or not theme.schedule.checkpoints:
            return
        
        completed_count = sum(1 for cp in theme.schedule.checkpoints if cp.completed)
        total = len(theme.schedule.checkpoints)
        progress = ResearchScheduler.progress_percentage(theme)
        
        # Progress should be proportional to completed count
        if total > 0:
            expected_min = (completed_count / total) * 100 - 0.01
            expected_max = (completed_count / total) * 100 + 0.01
            assert expected_min <= progress <= expected_max

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_theme_has_valid_id(self, theme):
        """Property: ResearchTheme should have a valid ID."""
        assert theme.id.startswith("theme_")
        assert len(theme.id) > 6

    @given(
        duration_weeks=valid_duration_weeks(),
        cadence=schedule_cadence(),
    )
    @settings(max_examples=50)
    def test_schedule_start_before_end(self, duration_weeks, cadence):
        """Property: Schedule start_date should be before end_date."""
        schedule = ScheduleSpec.create(duration_weeks=duration_weeks, cadence=cadence)
        assert schedule.start_date < schedule.end_date

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_threads_count_non_negative(self, theme):
        """Property: Threads count should always be non-negative."""
        status = ResearchScheduler.schedule_status(theme)
        assert status["threads_count"] >= 0

    @given(
        theme=research_theme(),
    )
    @settings(max_examples=50)
    def test_artifacts_count_non_negative(self, theme):
        """Property: Artifacts count should always be non-negative."""
        status = ResearchScheduler.schedule_status(theme)
        assert status["artifacts_count"] >= 0


class TestResearchProjectProperties:
    """Property-based tests for ResearchProject."""

    @given(
        title=st.text(min_size=1, max_size=50),
        description=st.text(min_size=1, max_size=200),
    )
    @settings(max_examples=50)
    def test_project_has_valid_id(self, title, description):
        """Property: ResearchProject should have a valid ID."""
        project = ResearchProject.create(title=title, description=description)
        assert project.id.startswith("proj_")
        assert len(project.id) > 5

    @given(
        title=st.text(min_size=1, max_size=50),
        description=st.text(min_size=1, max_size=200),
    )
    @settings(max_examples=50)
    def test_project_has_initial_message(self, title, description):
        """Property: New project should have initial gate message."""
        project = ResearchProject.create(title=title, description=description)
        assert len(project.gate.messages) >= 1

    @given(
        title=st.text(min_size=1, max_size=50),
        description=st.text(min_size=1, max_size=200),
        num_themes=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=30)
    def test_project_themes_count(self, title, description, num_themes):
        """Property: Project themes count should match added themes."""
        project = ResearchProject.create(title=title, description=description)
        for i in range(num_themes):
            project.add_theme(
                title=f"Theme {i}",
                description=f"Description {i}",
                duration_weeks=2,
            )
        assert len(project.themes) == num_themes


# ---------------------------------------------------------------------------
# Restored from test_research.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


class TestResearchModels(unittest.TestCase):

    def test_schedule_spec_creates_checkpoints_based_on_cadence(self) -> None:
        schedule = ScheduleSpec.create(duration_weeks=4, cadence=ScheduleCadence.WEEKLY)
        self.assertEqual(schedule.duration, timedelta(weeks=4))
        self.assertEqual(len(schedule.checkpoints), 4)

    def test_schedule_spec_daily_cadence_creates_more_checkpoints(self) -> None:
        schedule = ScheduleSpec.create(duration_weeks=1, cadence=ScheduleCadence.DAILY)
        self.assertEqual(len(schedule.checkpoints), 7)

    def test_research_theme_add_thread(self) -> None:
        theme = ResearchTheme.create(title="Theme", description="Test")
        thread = theme.add_thread(angle="Historical analysis", depth=ThreadDepth.DEEP)
        self.assertEqual(len(theme.threads), 1)
        self.assertEqual(thread.angle, "Historical analysis")
        self.assertEqual(thread.depth, ThreadDepth.DEEP)

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



# ---------------------------------------------------------------------------
# Restored from test_research_briefing.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


class _FakeBriefing:
    def __init__(self, text: str | None = "Next: compare official docs with the saved repo anchor.") -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def brief(self, **kwargs: Any) -> str | None:
        self.calls.append(kwargs)
        if self.text is not None and self.text.startswith("raise:"):
            raise RuntimeError(self.text.removeprefix("raise:"))
        return self.text


class _FakeProvider:
    def __init__(self, raw: Any = None, error: Exception | None = None) -> None:
        self._raw = raw
        self._error = error
        self.messages: list[list[dict[str, str]]] = []

    async def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        self.messages.append(messages)
        if self._error is not None:
            raise self._error
        return self._raw


def _project_with_theme(service: ResearchOrchestratorService) -> tuple[Any, Any]:
    project = service.create_project(title="Preparation", description="coach prep")
    theme = service.add_theme(project.id, title="Attention masks", description="masking in coaching plan")
    assert theme is not None
    service.activate_theme(project.id, theme.id)
    return project, theme


class TestProviderRoleBriefing:
    def test_success_returns_collapsed_text(self) -> None:
        provider = _FakeProvider(raw="  Brief the learner on anchors.  \n")
        briefing = ProviderRoleBriefing(provider)
        text = briefing.brief(
            role=AgentRole.RESEARCHER,
            theme_title="T",
            theme_description="D",
            findings=["f1"],
            language="zh-CN",
        )
        assert text == "Brief the learner on anchors."
        assert provider.messages, "provider must be called"

    def test_blank_reply_falls_back(self) -> None:
        briefing = ProviderRoleBriefing(_FakeProvider(raw="   "))
        assert (
            briefing.brief(
                role=AgentRole.CRITIC,
                theme_title="T",
                theme_description="",
                findings=[],
                language="en-US",
            )
            is None
        )

    def test_provider_error_falls_back(self) -> None:
        briefing = ProviderRoleBriefing(_FakeProvider(error=RuntimeError("no key")))
        assert (
            briefing.brief(
                role=AgentRole.EDITOR,
                theme_title="T",
                theme_description="",
                findings=[],
                language="en-US",
            )
            is None
        )


class TestAdvanceBriefing:
    def test_without_briefing_keeps_template_path(self) -> None:
        service = ResearchOrchestratorService()
        project, theme = _project_with_theme(service)
        result = service.advance_research(project.id, theme_id=theme.id)
        assert result["themes_advanced"][0]["briefing_source"] == "template"
        messages = [m["content"] for m in project.gate.messages if m.get("role") == "agent"]
        assert any("Role: RESEARCHER" in message for message in messages)

    def test_with_briefing_uses_llm_copy(self) -> None:
        service = ResearchOrchestratorService(role_briefing=_FakeBriefing())
        project, theme = _project_with_theme(service)
        thread = service.add_thread(project.id, theme.id, angle="grounding")
        assert thread is not None
        service.add_finding(
            project.id,
            theme.id,
            thread.id,
            content="Tokenizer masks differ from kernel masks.",
            source="docs.example",
            confidence=0.8,
        )
        result = service.advance_research(project.id, theme_id=theme.id)
        assert result["themes_advanced"][0]["briefing_source"] == "llm"
        messages = [m["content"] for m in project.gate.messages if m.get("role") == "agent"]
        assert any("[RESEARCHER] Next: compare official docs" in message for message in messages)

    def test_briefing_failure_falls_back_to_template(self) -> None:
        service = ResearchOrchestratorService(role_briefing=_FakeBriefing("raise:boom"))
        project, theme = _project_with_theme(service)
        result = service.advance_research(project.id, theme_id=theme.id)
        assert result["themes_advanced"][0]["briefing_source"] == "template"

    def test_attach_role_briefing_replaces_source(self) -> None:
        service = ResearchOrchestratorService()
        service.attach_role_briefing(_FakeBriefing())
        project, theme = _project_with_theme(service)
        assert service.advance_research(project.id, theme_id=theme.id)["themes_advanced"][0]["briefing_source"] == "llm"
        service.attach_role_briefing(None)
        project2, theme2 = _project_with_theme(service)
        assert service.advance_research(project2.id, theme_id=theme2.id)["themes_advanced"][0]["briefing_source"] == "template"


class _FakeResearchService:
    def __init__(self, references: list[dict[str, Any]]) -> None:
        self._references = references

    def recent_background_references(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self._references)


_REFERENCES = [
    {
        "title": "Attention Is All You Need",
        "source": "https://arxiv.org/abs/1706.03762",
        "snippet": "Self-attention maps a query and key-value pairs...",
        "summary": "Introduces the transformer architecture.",
        "trust_score": 0.9,
        "why_it_matters": "Motivates why mask semantics matter in coaching examples.",
        "source_type": "paper",
    },
    {
        "title": "HF causal masking docs",
        "source": "https://huggingface.co/docs",
        "snippet": "Causal masks prevent attending to future tokens...",
        "summary": "Official docs on causal masking.",
        "trust_score": 0.8,
        "why_it_matters": "Current-practice anchor for the stage material.",
        "source_type": "doc",
    },
]


class TestCollectResearchHints:
    def test_empty_references_yield_no_hints(self) -> None:
        assert (
            collect_research_hints(
                research_service=_FakeResearchService([]),
                workspace_id="ws",
                topic="Attention masks",
            )
            == []
        )

    def test_missing_reader_yields_no_hints(self) -> None:
        assert (
            collect_research_hints(
                research_service=object(),
                workspace_id="ws",
                topic="Attention masks",
            )
            == []
        )

    def test_references_distill_into_bounded_hints(self) -> None:
        hints = collect_research_hints(
            research_service=_FakeResearchService(_REFERENCES),
            workspace_id="ws",
            topic="Attention masks",
        )
        assert hints, "expected distilled hints"
        assert len(hints) <= 8
        assert all(len(hint) <= 220 for hint in hints)
        joined = " ".join(hints)
        assert "Attention Is All You Need" in joined

    def test_hints_are_deduplicated(self) -> None:
        duplicated = _FakeResearchService([*_REFERENCES, *_REFERENCES])
        hints = collect_research_hints(
            research_service=duplicated,
            workspace_id="ws",
            topic="Attention masks",
        )
        assert len(hints) == len({hint.lower() for hint in hints})


class _RecordingComposerProvider:
    def __init__(self) -> None:
        self.seen: list[list[dict[str, str]]] = []

    async def chat_completion(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.seen.append(messages)
        return (
            '{"materials":[{"kind":"study_guide","title":"Guide",'
            '"concept_card":"Grounded content."}]}'
        )


class TestComposerResearchHints:
    async def _compose(self, research_hints: list[str] | None) -> tuple[list[Any], list[list[dict[str, str]]]]:
        provider = _RecordingComposerProvider()
        composer = StageMaterialComposer(provider_service=provider)
        assets = await composer.compose_stage_materials(
            workspace_id="ws",
            plan_title="Plan",
            stage_id="stage-1",
            stage_title="Attention masks",
            stage_goal="Understand masking",
            stage_outcomes=["Outcome"],
            stage_exercises=["Exercise"],
            research_hints=research_hints,
            response_language="en-US",
        )
        return assets, provider.seen

    def test_hints_reach_llm_prompt(self) -> None:
        import asyncio

        assets, seen = asyncio.run(self._compose(["Lane: read the official docs first."]))
        assert assets, "LLM materials should be used when provider succeeds"
        user_prompt = seen[0][1]["content"]
        assert "Background preparation collected for this stage" in user_prompt
        assert "Lane: read the official docs first." in user_prompt

    def test_absent_hints_keep_prompt_unchanged(self) -> None:
        import asyncio

        _assets, seen = asyncio.run(self._compose(None))
        user_prompt = seen[0][1]["content"]
        assert "Background preparation collected for this stage" not in user_prompt


# ---------------------------------------------------------------------------
# Restored from test_literature_verifier.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def test_unit_counts_cjk_chars_and_latin_words() -> None:
    assert unit_count("白描手法") == 4
    assert unit_count("plain words here") == 3
    # 2 CJK characters + 3 whitespace-separated latin words.
    assert unit_count("白描 with two words") == 5


def test_word_count_hook_window() -> None:
    hook = WordCountHook(min_units=10, max_units=20)
    inside = hook.run("一" * 15)
    below = hook.run("一" * 3)
    assert inside.status is CheckStatus.PASSED
    assert below.status is CheckStatus.FAILED
    with pytest.raises(ValueError):
        WordCountHook(min_units=20, max_units=10)


def test_banned_phrases_hook_hits_any_language() -> None:
    hook = BannedPhrasesHook(phrases=("非常", "amazing"))
    hit = hook.run("这片景色非常美丽")
    clean = hook.run("这片景色很美")
    latin = hook.run("This is amazing work")
    assert hit.status is CheckStatus.FAILED
    assert clean.status is CheckStatus.PASSED
    assert latin.status is CheckStatus.FAILED
    with pytest.raises(ValueError):
        BannedPhrasesHook(phrases=("  ", ""))


def test_paragraph_structure_hook_counts_blank_line_blocks() -> None:
    hook = ParagraphStructureHook(min_paragraphs=2)
    ok = hook.run("第一段。\n\n第二段。")
    single = hook.run("只有一段。")
    assert ok.status is CheckStatus.PASSED
    assert single.status is CheckStatus.FAILED


def test_quote_balance_hook_detects_stray_quotes() -> None:
    hook = QuoteBalanceHook()
    balanced = hook.run("他说：“来了。”然后就走了。")
    stray = hook.run("他说：“来了。然后就走了。")
    assert balanced.status is CheckStatus.PASSED
    assert stray.status is CheckStatus.FAILED


def test_hooks_from_card_config_builds_declared_set() -> None:
    hooks = hooks_from_card_config(
        {
            "word_count": {"min": 50, "max": 150},
            "banned_phrases": ["众所周知"],
            "min_paragraphs": 2,
            "quote_balance": True,
        }
    )
    names = [getattr(hook, "name", "") for hook in hooks]
    assert names == ["word-count", "banned-phrases", "paragraph-structure", "quote-balance"]
    assert hooks_from_card_config({}) == ()
    with pytest.raises(ValueError):
        hooks_from_card_config({"word_count": {"min": 200, "max": 100}})


def test_rubric_item_requires_anchor_and_caps_criteria() -> None:
    with pytest.raises(ValueError, match="anchor"):
        RubricItem(statement="用白描手法", anchor="  ")
    with pytest.raises(ValueError, match="statement"):
        RubricItem(statement="", anchor="原文")
    with pytest.raises(ValueError, match="at most 3"):
        RubricItem(statement="s", anchor="a", criteria=("1", "2", "3", "4"))
    item = RubricItem(statement="s", anchor="a", criteria=("1", "2", "3"))
    assert item.criteria == ("1", "2", "3")


def test_local_rubric_reviewer_matches_only_anchored_items() -> None:
    spec = RubricSpec(
        items=(
            RubricItem(statement="提到小伙计视角", anchor="小伙计"),
            RubricItem(statement="引用原文句子", anchor="孔乙己是站着喝酒而穿长衫的唯一的人"),
        )
    )
    review = LocalRubricReviewer().review(
        spec,
        "从“孔乙己是站着喝酒而穿长衫的唯一的人”可见叙述者是旁观的小伙计。",
    )
    assert review.status is CheckStatus.PASSED
    assert len(review.matched) == 2

    partial = LocalRubricReviewer().review(spec, "小伙计是旁观者，但我记不清原文了。")
    assert partial.status is CheckStatus.FAILED
    assert partial.matched == ["提到小伙计视角"]
    assert "引用原文句子" in partial.missing


def test_local_rubric_reviewer_skips_empty_spec() -> None:
    review = LocalRubricReviewer().review(RubricSpec(items=()), "任意提交")
    assert review.status is CheckStatus.SKIPPED


def test_combine_verdict_never_lets_llm_review_verify_alone() -> None:
    from app.evaluator.models import CheckResult

    passing_rubric = LocalRubricReviewer().review(
        RubricSpec(items=(RubricItem(statement="s", anchor="a"),)),
        "包含 a 的提交",
    )
    assert passing_rubric.status is CheckStatus.PASSED
    # No deterministic hooks ran at all → PENDING, never PASSED.
    verdict = combine_verdict((), passing_rubric)
    assert verdict.status is CheckStatus.PENDING
    assert "not evidence" in verdict.summary
    # Human adoption breaks the tie explicitly.
    adopted = combine_verdict((), passing_rubric, human_adopted=True)
    assert adopted.status is CheckStatus.PASSED
    # A failed hook still blocks even with adoption.
    blocked = combine_verdict(
        (CheckResult(name="x", status=CheckStatus.FAILED, summary="no"),),
        passing_rubric,
        human_adopted=True,
    )
    assert blocked.status is CheckStatus.FAILED


def test_literature_submission_verifier_end_to_end() -> None:
    from app.evaluator.verifiers import LiteratureSubmissionVerifier

    hooks = hooks_from_card_config({"word_count": {"min": 4, "max": 50}, "banned_phrases": ["非常"]})
    rubric = RubricSpec(
        items=(
            RubricItem(statement="出现锚点意象", anchor="月亮"),
            RubricItem(statement="引用原句", anchor="月光如水"),
        )
    )
    verifier = LiteratureSubmissionVerifier(hooks=hooks, rubric=rubric)

    good = verifier.verify("他说月光如水，月亮挂在楼角。")
    assert good.status is CheckStatus.PASSED

    banned = verifier.verify("月光如水，月亮很亮，非常安静地照着大地和原野。")
    assert banned.status is CheckStatus.FAILED  # banned phrase wins

    unanchored = verifier.verify("完全无关的一段文字，不算短，也没有任何锚点可用。")
    assert unanchored.status is CheckStatus.FAILED  # rubric missing → FAILED

    llm_only = LiteratureSubmissionVerifier(hooks=(), rubric=rubric)
    pending = llm_only.verify("月光如水，月亮挂在楼角。")
    assert pending.status is CheckStatus.PENDING  # rubric alone is not evidence
