"""Tests for training handoff system."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from app.training.handoff import (
    EvidenceRecord,
    HandoffStatus,
    ProjectHandoff,
    TrainingHandoffContent,
    TrainingHandoffGenerator,
)


class TestTrainingHandoffGenerator:
    """Test the training handoff generator."""

    def test_generate_handoff_basic(self):
        """Test basic handoff generation from a card."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-123",
            title="Understanding Python decorators",
            card_type="practice",
            concept="python-decorators",
            target_skill="decorator-pattern",
            scenario_pack="function_guidance",
            validation_method="Explain when to use @property vs @staticmethod",
            next_after_completion="Return with one decorator example from the project.",
            status="candidate",
        )

        generator = TrainingHandoffGenerator()
        result = generator.generate_handoff(
            card,
            {"correct": True, "mastery_delta": 0.15},
            mastery_delta=0.15,
        )

        assert result.card_id == "card-123"
        assert result.card_title == "Understanding Python decorators"
        assert result.card_type == "practice"
        assert result.concept_practiced == "python-decorators"
        assert result.scenario_pack == "function_guidance"
        assert result.next_after_completion == "Return with one decorator example from the project."
        assert result.status == HandoffStatus.GENERATED
        assert len(result.next_steps) > 0

    def test_generate_handoff_with_files(self):
        """Test handoff generation with file references."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-456",
            title="Fix async bug",
            card_type="practice",
            deliverable="Update src/main.py and src/utils.py",
            problem_statement="The async function in src/main.py has a race condition",
            status="candidate",
        )

        generator = TrainingHandoffGenerator()
        result = generator.generate_handoff(card, {"correct": True})

        assert result.files_to_touch == ["src/main.py", "src/utils.py"]
        assert len(result.verification_checklist) > 0

    def test_write_handoff_to_workspace(self):
        """Test writing handoff to a temporary workspace."""
        from datetime import datetime, timezone

        temp_dir = tempfile.mkdtemp()
        try:
            workspace_root = Path(temp_dir)

            content = TrainingHandoffContent(
                card_id="card-test",
                card_title="Test Card",
                card_type="practice",
                concept_practiced="test-concept",
                key_takeaway="Test takeaway",
                scenario_pack="remote_workspace",
                next_after_completion="Return with the route diff.",
                next_steps=["Step 1", "Step 2"],
                files_to_touch=["test.py"],
                verification_checklist=["Verify test"],
                success_signal="Test passed",
                project_scope="current",
                evidence_location="evidence",
                status=HandoffStatus.GENERATED,
            )

            handoff = ProjectHandoff(
                handoff_id="handoff-test",
                card_id="card-test",
                card_title="Test Card",
                evidence=[
                    EvidenceRecord(
                        id="ev-1",
                        card_id="card-test",
                        concept="test-concept",
                        content="Test evidence content",
                        source="learner",
                        created_at=datetime.now(timezone.utc),
                    )
                ],
                handoff_content=content,
                status=HandoffStatus.GENERATED,
            )

            generator = TrainingHandoffGenerator(workspace_root=workspace_root)
            written_path = generator.write_handoff_to_workspace(handoff, workspace_root)

            assert written_path is not None
            assert written_path.exists()
            assert written_path.relative_to(workspace_root) == Path(
                "notes/training-handoffs/current/card-test.md"
            )
            content_text = written_path.read_text()
            assert "Test Card" in content_text
            assert "Scenario Pack" in content_text
            assert "Next After Completion" in content_text
            assert "Step 1" in content_text
            assert "Test evidence content" in content_text

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_leftover_formal_card_title_does_not_live_in_handoff_markdown(self) -> None:
        from datetime import datetime, timezone

        from app.core.models import LearningPlan, PlanStage

        leftover_title = "Keep the current stage"
        leftover_stage = "Auth"
        leftover_step = "Keep one auth check"
        leftover_summary = "Leftover formal summary of the old stage path"
        leftover_plan_id = "plan-formal-old"
        leftover_card = f"Practice: {leftover_title}"
        recovered_step = "Add a token expiry test"
        plan = LearningPlan(
            id=leftover_plan_id,
            title=leftover_title,
            summary=leftover_summary,
            current_stage_id="stage-1",
            current_step=leftover_step,
            stages=[
                PlanStage(
                    id="stage-1",
                    title=leftover_stage,
                    goal="Keep one check",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        content = TrainingHandoffContent(
            card_id="card-leftover-handoff",
            card_title=leftover_card,
            card_type="practice",
            concept_practiced=recovered_step,
            key_takeaway="Recovered step only.",
            scenario_pack="auth-recovery",
            next_after_completion="Return with the expiry test.",
            next_steps=["Write the expiry test"],
            files_to_touch=[],
            verification_checklist=["pytest"],
            success_signal="Expiry test passes",
            project_scope="current",
            evidence_location="evidence",
            status=HandoffStatus.GENERATED,
        )
        handoff = ProjectHandoff(
            handoff_id="handoff-leftover",
            card_id="card-leftover-handoff",
            card_title=leftover_card,
            evidence=[
                EvidenceRecord(
                    id="ev-leftover",
                    card_id="card-leftover-handoff",
                    concept=recovered_step,
                    content="Recovered expiry evidence",
                    source="learner",
                    created_at=datetime.now(timezone.utc),
                )
            ],
            handoff_content=content,
            status=HandoffStatus.GENERATED,
        )
        generator = TrainingHandoffGenerator()
        advanced = {
            "current_step": recovered_step,
            "why_now": "Expired tokens still leak.",
            "resume_state": "in_progress",
            "workspace_id": "workspace-handoff-leftover",
        }
        heading = generator._render_handoff_markdown(
            handoff,
            leftover_plan=plan,
            leftover_runtime=advanced,
            leftover_task_title=leftover_title,
        ).splitlines()[0]
        assert leftover_title not in heading
        assert leftover_card not in heading
        assert leftover_stage not in heading
        assert leftover_step not in heading
        assert leftover_summary not in heading
        assert leftover_plan_id not in heading
        assert heading == f"# Training Handoff: {recovered_step}"
        empty_heading = generator._render_handoff_markdown(
            handoff,
            leftover_plan=plan,
            leftover_runtime={"current_step": "", "resume_state": "in_progress"},
            leftover_task_title=leftover_title,
        ).splitlines()[0]
        assert leftover_title not in empty_heading
        assert leftover_card not in empty_heading
        assert empty_heading == "# Training Handoff"
        still_heading = generator._render_handoff_markdown(
            handoff,
            leftover_plan=plan,
            leftover_runtime={
                "current_step": leftover_step,
                "plan_id": leftover_plan_id,
                "resume_state": "in_progress",
                "workspace_id": "workspace-handoff-still-on-plan",
            },
            leftover_task_title=leftover_title,
        ).splitlines()[0]
        assert leftover_card in still_heading

    def test_build_handoff_record(self):
        """Test building a complete handoff record."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-full",
            title="Full Card Test",
            card_type="practice",
            target_skill="transfer-skill",
            next_steps=["Apply to project", "Verify"],
            status="candidate",
        )

        generator = TrainingHandoffGenerator()
        result = generator.build_handoff_record(
            card,
            {"correct": True, "evidence": ["Learned this"]},
            mastery_delta=0.2,
        )

        assert result.handoff_id.startswith("handoff-card-full-")
        assert result.card_id == "card-full"
        assert len(result.evidence) == 1
        assert result.handoff_content.status == HandoffStatus.GENERATED

    def test_unverified_learner_submission_stays_provisional(self):
        """A learner-reported success cannot become a completion or mastery claim."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-unverified",
            title="Verify one route boundary",
            card_type="practice",
            target_skill="route boundary",
            validation_method="Run the focused route test and inspect the output.",
            reflection_prompt="What signal proved the boundary?",
            return_with="The test output and one sentence of reflection.",
        )

        handoff = TrainingHandoffGenerator().build_handoff_record(
            card,
            {
                "correct": True,
                "mastery_delta": 0.9,
                "evidence": ["I ran the route test locally."],
                "evidence_source": "learner_return",
            },
            mastery_delta=0.9,
        )

        assert handoff.status == HandoffStatus.GENERATED
        assert handoff.verification_state == "verification_required"
        assert handoff.return_state == "verify_then_return"
        assert handoff.evidence and handoff.evidence[0].verified is False
        assert "mastered" not in handoff.handoff_content.success_signal.lower()
        assert "server-side verification" in handoff.handoff_content.completion_claim
        assert any("learner self-report is not sufficient" in item for item in handoff.handoff_content.verification_checklist)

    def test_trusted_verification_supports_card_result_without_claiming_durable_mastery(self):
        """Verifier-attested evidence can support one card result, not broad mastery."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-verified",
            title="Verify one parser branch",
            card_type="practice",
            target_skill="parser branch",
            validation_method="Run the targeted parser test.",
        )
        handoff = TrainingHandoffGenerator().build_handoff_record(
            card,
            {
                "correct": True,
                "evidence": ["pytest tests/test_parser.py -k malformed_branch: 1 passed"],
                "evidence_source": "test_runner",
                "verified_by_evaluator": True,
            },
        )

        assert handoff.verification_state == "verified"
        assert handoff.return_state == "return_to_coach"
        assert handoff.evidence[0].verified is True
        assert handoff.evidence[0].verification_source == "test_runner"
        assert "supports one result" in handoff.handoff_content.success_signal
        assert "not a claim of durable mastery" in handoff.handoff_content.completion_claim

    def test_current_ide_file_verification_alias_remains_trusted_after_restart(self):
        """Older agent evidence must resolve to the canonical IDE verifier source."""
        from app.core.models import TrainingCardCandidateSnapshot

        card = TrainingCardCandidateSnapshot(
            card_id="card-current-ide-file",
            title="Verify one active IDE file",
            card_type="practice",
            target_skill="active file verification",
        )
        handoff = TrainingHandoffGenerator().build_handoff_record(
            card,
            {
                "correct": True,
                "evidence": ["Active IDE file matched the focused acceptance criteria."],
                "evidence_source": "current_ide_file",
                "verified_by_evaluator": True,
            },
        )

        assert handoff.verification_state == "verified"
        assert handoff.phase.value == "verify"
        assert handoff.evidence[0].source == "ide_current_file"
        assert handoff.evidence[0].verification_source == "ide_current_file"

    def test_handoff_can_resume_from_disk_and_rejects_untrusted_verification(self):
        """Persistence keeps return state intact across interruption and restart."""
        from app.core.models import TrainingCardCandidateSnapshot

        temp_dir = tempfile.mkdtemp()
        try:
            workspace_root = Path(temp_dir)
            card = TrainingCardCandidateSnapshot(
                card_id="card-resume",
                title="Resume one diagnostic check",
                card_type="practice",
                target_skill="diagnostic check",
                validation_method="Run the focused diagnostic check.",
            )
            generator = TrainingHandoffGenerator(workspace_root=workspace_root)
            handoff = generator.build_handoff_record(
                card,
                {
                    "correct": True,
                    "evidence": ["Learner copied a diagnostic summary."],
                    "evidence_source": "learner_return",
                },
            )
            written = generator.write_handoff_to_workspace(handoff)
            assert written is not None
            assert written.with_suffix(".json").exists()

            restarted = TrainingHandoffGenerator(workspace_root=workspace_root)
            restored = restarted.resume_handoff(handoff.handoff_id)
            assert restored is not None
            assert restored.verification_state == "verification_required"
            assert restored.return_state == "verify_then_return"
            assert restored.evidence[0].verified is False

            untrusted = restarted.record_verification(
                restored.handoff_id,
                "The learner says it passed.",
                evidence_source="learner_return",
                verified_by_evaluator=True,
            )
            assert untrusted is not None
            assert untrusted.verification_state == "verification_required"

            verified = restarted.record_verification(
                restored.handoff_id,
                "diagnostics: no errors; focused test: passed",
                evidence_source="test_runner",
                verified_by_evaluator=True,
                reflection="The focused check exposed the exact parser boundary.",
            )
            assert verified is not None
            assert verified.verification_state == "verified"
            assert verified.return_state == "return_to_coach"
            assert verified.reflected_at is not None
            assert verified.reflection == "The focused check exposed the exact parser boundary."

            restored_after_verification = TrainingHandoffGenerator(
                workspace_root=workspace_root
            ).resume_handoff(handoff.handoff_id)
            assert restored_after_verification is not None
            assert restored_after_verification.verification_state == "verified"
            assert restored_after_verification.reflection == verified.reflection
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
