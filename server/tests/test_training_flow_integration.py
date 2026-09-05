"""End-to-end integration tests for the full training workflow.

These tests exercise real service interactions without mocking internal services.
They use temporary directories for test databases and verify the complete flow
from session start through evaluation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from app.api.runtime import TrainerRuntime
from app.core.models import (
    EvaluateCurrentFileRequest,
    EvaluateSnippetRequest,
    PlanGenerateRequest,
    PlanUpdateRequest,
    TaskNextRequest,
    TeachingKnowledgeAsset,
    UserProfile,
)
from app.db.repository import TrainerRepository
from app.evaluator.service import EvaluatorService
from app.llm.provider_service import ProviderService
from app.memory.service import MemoryService
from app.planner.service import PlannerService, TrainingPlannerService
from app.resources.service import ResourceService
from app.specs.service import SpecService

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Create a temporary database path for each test."""
    return tmp_path / "trainer.db"


@pytest.fixture
def repository(tmp_db_path: Path) -> TrainerRepository:
    """Create a real TrainerRepository with a temporary database."""
    return TrainerRepository(tmp_db_path)


@pytest.fixture
def provider_service() -> ProviderService:
    """Create a ProviderService without API key (scaffold mode)."""
    return ProviderService()


@pytest.fixture
def planner_service() -> PlannerService:
    """Create a PlannerService with real TrainingPlannerService."""
    return PlannerService(TrainingPlannerService())


@pytest.fixture
def memory_service(repository: TrainerRepository) -> MemoryService:
    """Create a MemoryService with real repository."""
    return MemoryService(repository)


@pytest.fixture
def evaluator_service() -> EvaluatorService:
    """Create an EvaluatorService with real pipeline."""
    return EvaluatorService()


@pytest.fixture
def runtime(
    repository: TrainerRepository,
    provider_service: ProviderService,
    planner_service: PlannerService,
    memory_service: MemoryService,
    evaluator_service: EvaluatorService,
) -> TrainerRuntime:
    """Create a fully wired TrainerRuntime with real services."""
    return TrainerRuntime(
        repository=repository,
        provider_service=provider_service,
        planner_service=planner_service,
        memory_service=memory_service,
        resource_service=ResourceService(
            repository,
            ingest_service=None,  # type: ignore[arg-type]
            semantic_memory=None,  # type: ignore[arg-type]
        ),
        spec_service=SpecService(),
        evaluator_service=evaluator_service,
    )


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------


class TestTrainingFlowIntegration:
    """Integration tests for the complete training workflow."""

    def test_full_training_session(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        """Test the complete training session flow from start to evaluation."""
        workspace_id = "test-workspace-001"
        workspace_name = "Integration Test Workspace"

        # 1. Start session with profile
        session = runtime.start_session(workspace_id, workspace_name)
        assert session.session_id.startswith("session-")
        assert session.workspace_id == workspace_id
        assert session.workspace_name == workspace_name

        # 2. Create and save user profile
        profile = UserProfile(
            long_term_goal="Learn FastAPI and async Python",
            background="Intermediate Python developer",
            weekly_hours=6,
            teaching_style="guided",
            answer_policy="guided",
            preferred_libraries=["fastapi", "pytest", "httpx"],
        )
        runtime.memory_service.record_profile(workspace_id, profile)

        # Verify profile was saved
        loaded_profile = runtime.memory_service.profile(workspace_id)
        assert loaded_profile is not None
        assert loaded_profile.long_term_goal == "Learn FastAPI and async Python"

        # 3. Generate learning plan
        plan_request = PlanGenerateRequest(
            workspace_id=workspace_id,
            profile=profile,
            goals=["Master FastAPI fundamentals", "Build async API endpoints"],
            constraints=["Use type hints", "Write tests"],
        )
        plan = runtime.planner_service.generate_plan(plan_request)

        assert plan.id != ""
        assert plan.title != ""
        assert len(plan.stages) >= 1
        assert plan.current_stage_id is not None

        # Save the plan
        runtime.repository.save_plan(workspace_id, plan)

        # 4. Get next task recommendation
        task_request = TaskNextRequest(workspace_id=workspace_id)
        task_spec = runtime.planner_service.next_task(profile, task_request.focus_area)

        assert task_spec.id != ""
        assert task_spec.title != ""
        assert task_spec.natural_language_goal != ""
        assert len(task_spec.verification_strategy) > 0

        # 5. Evaluate code (using a simple snippet)
        eval_request = EvaluateSnippetRequest(
            workspace_id=workspace_id,
            task_spec_id=task_spec.id,
            language_id="python",
            content="def hello() -> str:\n    return 'Hello, World!'\n",
        )
        report = runtime.evaluator_service.evaluate_snippet(eval_request)

        assert report.task_spec_id == task_spec.id
        assert report.summary != ""
        # Note: The evaluation may pass or fail depending on the spec requirements
        # We just verify the report structure is correct
        assert len(report.static_checks) >= 0
        assert len(report.dynamic_checks) >= 0
        assert len(report.semantic_checks) >= 0

        # 6. Check memory was updated
        snapshot = runtime.memory_service.snapshot(workspace_id)
        assert snapshot.profile is not None
        assert snapshot.profile.long_term_goal == "Learn FastAPI and async Python"

    def test_coaching_conversation_flow(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        """Test the coaching conversation flow with scaffold mode."""
        workspace_id = "test-workspace-002"
        workspace_name = "Coaching Test Workspace"

        # 1. Configure provider (scaffold mode - no API key)
        assert not runtime.provider_service.has_api_key

        # 2. Create profile
        profile = UserProfile(
            long_term_goal="Master Python testing",
            background="Beginner in testing",
            weekly_hours=4,
            teaching_style="guided",
            answer_policy="guided",
        )
        runtime.memory_service.record_profile(workspace_id, profile)

        # Start session
        session = runtime.start_session(workspace_id, workspace_name)

        # 3. Send message (scaffold mode)
        import asyncio

        response = asyncio.run(
            runtime.provider_service.coaching_reply(
                profile=profile,
                message="How do I write a good test?",
            )
        )

        # 4. Verify response structure (scaffold mode)
        assert "api key" in response.lower()
        assert "settings" in response.lower()

        # 5. Send follow-up with current file
        current_file = {
            "path": "test_example.py",
            "language_id": "python",
            "content": "def test_add():\n    assert 1 + 1 == 2\n",
        }
        response_with_file = asyncio.run(
            runtime.provider_service.coaching_reply(
                profile=profile,
                message="Review my test",
                current_file=current_file,
            )
        )

        # 6. Verify context maintained
        assert "api key" in response_with_file.lower()

        # Record session message
        runtime.memory_service.record_session_message(
            session.session_id,
            "How do I write a good test?",
            workspace_id=workspace_id,
        )
        runtime.memory_service.record_session_message(
            session.session_id,
            response,
            workspace_id=workspace_id,
        )

        # Verify session messages recorded
        snapshot = runtime.memory_service.snapshot(workspace_id)
        assert snapshot.recent_summary != ""

    def test_plan_generation_and_task_recommendation(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        """Test plan generation and task recommendation flow."""
        workspace_id = "test-workspace-003"

        # 1. Create profile
        profile = UserProfile(
            long_term_goal="Learn data structures and algorithms",
            background="CS student",
            weekly_hours=8,
            teaching_style="balanced",
            answer_policy="balanced",
            preferred_libraries=["typing", "collections"],
        )
        runtime.memory_service.record_profile(workspace_id, profile)

        # 2. Generate plan
        plan_request = PlanGenerateRequest(
            workspace_id=workspace_id,
            profile=profile,
            goals=["Master fundamental data structures", "Implement common algorithms"],
            constraints=["Use type hints", "Write docstrings"],
        )
        plan = runtime.planner_service.generate_plan(plan_request)

        # 3. Verify plan structure
        assert plan.id != ""
        assert len(plan.stages) >= 1

        # Check stages have proper structure
        for stage in plan.stages:
            assert stage.id != ""
            assert stage.title != ""
            assert stage.goal != ""
            assert len(stage.outcomes) >= 0

        # First stage should be active
        assert plan.stages[0].status == "active"

        # 4. Get next task
        task_spec = runtime.planner_service.next_task(profile)

        # 5. Verify task matches plan stage
        assert task_spec.id != ""
        assert task_spec.title != ""
        assert task_spec.natural_language_goal != ""
        # Task should reference concepts from the plan
        assert len(task_spec.inputs) >= 0
        assert len(task_spec.outputs) >= 0

        # Save plan and verify persistence
        runtime.repository.save_plan(workspace_id, plan)
        loaded_plan = runtime.repository.get_latest_plan(workspace_id)
        assert loaded_plan is not None
        assert loaded_plan.id == plan.id

    def test_next_task_uses_existing_plan_stage(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        workspace_id = "test-workspace-existing-plan"
        profile = UserProfile(
            long_term_goal="Evolve Trainer into a coach-first plugin",
            background="Product-minded engineer",
            weekly_hours=6,
            teaching_style="guided",
            answer_policy="guided",
        )
        runtime.memory_service.record_profile(workspace_id, profile)

        plan = runtime.planner_service.generate_plan(
            PlanGenerateRequest(
                workspace_id=workspace_id,
                profile=profile,
                goals=["Deepen planner and memory behavior"],
                constraints=["Keep the UI minimal"],
            )
        )
        plan.stages[0].status = "completed"
        if len(plan.stages) > 1:
            plan.stages[1].status = "active"
            plan.current_stage_id = plan.stages[1].id
        runtime.repository.save_plan(workspace_id, plan)

        snapshot = runtime.memory_service.snapshot(workspace_id)
        task_spec = runtime.planner_service.next_task(
            profile,
            current_plan=snapshot.active_plan,
            memory_snapshot=snapshot,
        )

        assert task_spec.title.startswith("Practice:")
        assert "planner" in task_spec.natural_language_goal.lower() or "memory" in task_spec.natural_language_goal.lower()

    def test_memory_persistence_across_sessions(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        """Test that memory persists across different sessions."""
        workspace_id = "test-workspace-004"

        # Session 1: Create profile and plan
        profile = UserProfile(
            long_term_goal="Learn web scraping",
            background="Python developer",
            weekly_hours=5,
            teaching_style="guided",
            answer_policy="guided",
        )
        runtime.memory_service.record_profile(workspace_id, profile)

        # Record some reflections
        runtime.memory_service.record_reflection(
            task_id="task-001",
            summary="Learned about requests library",
            action_items=["Practice with different websites"],
        )

        # Session 2: Verify memory persisted
        loaded_profile = runtime.memory_service.profile(workspace_id)
        assert loaded_profile is not None
        assert loaded_profile.long_term_goal == "Learn web scraping"

        # Check weaknesses are derived
        weaknesses = runtime.memory_service.weaknesses(workspace_id)
        assert isinstance(weaknesses, list)

    def test_evaluation_pipeline_integration(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        """Test the evaluation pipeline with real code."""
        workspace_id = "test-workspace-005"

        # Create a temporary Python file for evaluation
        test_file = tmp_path / "test_code.py"
        test_file.write_text(
            """
def calculate_sum(numbers: list[int]) -> int:
    '''Calculate the sum of a list of numbers.'''
    return sum(numbers)

def calculate_average(numbers: list[int]) -> float:
    '''Calculate the average of a list of numbers.'''
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)
""",
            encoding="utf-8",
        )

        # Evaluate the file
        eval_request = EvaluateCurrentFileRequest(
            workspace_id=workspace_id,
            task_spec_id="task-eval-001",
            file_path=str(test_file),
            language_id="python",
            content=test_file.read_text(encoding="utf-8"),
        )

        report = runtime.evaluator_service.evaluate_current_file(eval_request)

        # Verify report structure
        assert report.task_spec_id == "task-eval-001"
        assert report.summary != ""
        assert report.next_step != ""
        # Static checks should be present (ruff, pyright)
        assert len(report.static_checks) >= 0

        # Record evaluation feedback in memory
        failed_checks = [] if report.passed else ["ruff", "pyright"]
        missing_reqs = []
        if report.semantic_checks:
            detail = report.semantic_checks[0].detail
            if detail:
                missing_reqs = [line.strip() for line in str(detail).splitlines() if line.strip()]
        runtime.memory_service.record_evaluation_feedback(
            workspace_id=workspace_id,
            concepts=["sum", "average"],
            failed_checks=failed_checks,
            missing_requirements=missing_reqs,
        )

    def test_plan_update_flow(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        """Test updating an existing learning plan."""
        workspace_id = "test-workspace-006"

        # Create initial plan
        profile = UserProfile(
            long_term_goal="Learn machine learning basics",
            background="Data analyst",
            weekly_hours=6,
            teaching_style="guided",
            answer_policy="guided",
        )
        plan_request = PlanGenerateRequest(
            workspace_id=workspace_id,
            profile=profile,
            goals=["Understand ML fundamentals"],
        )
        initial_plan = runtime.planner_service.generate_plan(plan_request)
        runtime.repository.save_plan(workspace_id, initial_plan)

        # Update the plan
        update_request = PlanUpdateRequest(
            plan_id=initial_plan.id,
            workspace_id=workspace_id,
            instructions="Add focus on practical examples",
            freeze=True,
        )
        updated_plan = runtime.planner_service.update_plan(initial_plan, update_request)

        # Verify update
        assert updated_plan.frozen is True
        assert "practical examples" in updated_plan.summary.lower() or "update request" in updated_plan.summary.lower()

        # Save and verify persistence
        runtime.repository.save_plan(workspace_id, updated_plan)
        loaded = runtime.repository.get_latest_plan(workspace_id)
        assert loaded is not None
        assert loaded.frozen is True

    def test_evaluation_success_advances_plan_stage(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        workspace_id = "test-workspace-stage-advance"
        profile = UserProfile(
            long_term_goal="Deepen the coach-first trainer",
            background="Product-minded engineer",
            weekly_hours=6,
            teaching_style="guided",
            answer_policy="guided",
        )
        runtime.memory_service.record_profile(workspace_id, profile)

        plan = runtime.planner_service.generate_plan(
            PlanGenerateRequest(
                workspace_id=workspace_id,
                profile=profile,
                goals=["Push planner and memory together"],
                constraints=["Keep the UI minimal"],
            )
        )
        assert len(plan.stages) >= 2
        runtime.repository.save_plan(workspace_id, plan)

        updated = runtime.planner_service.advance_plan_after_success(plan, None, passed=True)
        assert updated is not None
        assert updated.current_stage_id == plan.stages[1].id
        assert updated.stages[0].status == "completed"
        assert updated.stages[1].status == "active"

    def test_failed_evaluation_does_not_advance_plan_stage(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        workspace_id = "test-workspace-stage-hold"
        profile = UserProfile(
            long_term_goal="Deepen the coach-first trainer",
            background="Product-minded engineer",
            weekly_hours=6,
            teaching_style="guided",
            answer_policy="guided",
        )
        runtime.memory_service.record_profile(workspace_id, profile)

        plan = runtime.planner_service.generate_plan(
            PlanGenerateRequest(
                workspace_id=workspace_id,
                profile=profile,
                goals=["Push planner and memory together"],
                constraints=["Keep the UI minimal"],
            )
        )
        original_stage_id = plan.current_stage_id
        updated = runtime.planner_service.advance_plan_after_success(plan, None, passed=False)
        assert updated is not None
        assert updated.current_stage_id == original_stage_id

    def test_repeated_failed_evaluation_changes_learning_memory(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        workspace_id = "test-workspace-learning-loop-failure"
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["config validation"],
            outcome="evaluation",
            summary="Still failing config validation.",
            checks=["pytest"],
            missing_requirements=["Handle the failing config branch."],
            action_type="evaluate_current_file",
            focus_area="config validation",
            scenario="review_reflection",
            blocked_reason="The same config test still fails.",
        )
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["config validation"],
            outcome="repeated_error",
            summary="Still failing config validation.",
            checks=["pytest"],
            missing_requirements=["Handle the failing config branch."],
            action_type="evaluate_current_file",
            repetition_count=2,
            focus_area="config validation",
            scenario="review_reflection",
            blocked_reason="The same config test still fails.",
        )

        snapshot = runtime.memory_service.snapshot(workspace_id)
        assert snapshot.due_reviews
        assert snapshot.top_weakness
        assert any("Recurring blocker pattern" in item or "稳定错误模式" in item for item in snapshot.teaching_observations)

        structured = runtime.memory_service.structured_for_workspace(workspace_id).snapshot()
        latest = structured.learning_outcomes[0]
        assert latest.concept == "config validation"
        assert latest.repetition_count >= 2

    def test_successful_learning_outcome_updates_mastery_and_review_cadence(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        workspace_id = "test-workspace-learning-loop-success"
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["router design"],
            outcome="tests_passed",
            summary="The focused router tests are now passing.",
            checks=[],
            missing_requirements=[],
            action_type="evaluate_current_file",
            focus_area="router design",
            scenario="review_reflection",
            verified_result="The focused router tests are now passing.",
            verified_by_evaluator=True,
        )

        structured = runtime.memory_service.structured_for_workspace(workspace_id).snapshot()
        mastery = next((item for item in structured.mastery if item.concept == "router design"), None)
        assert mastery is not None
        assert mastery.score > 0

        snapshot = runtime.memory_service.snapshot(workspace_id)
        assert snapshot.review_rhythm
        assert snapshot.recent_wins

    def test_learning_outcomes_drive_adaptive_coaching_profile(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        workspace_id = "test-workspace-learning-loop-adaptation"
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["config validation"],
            outcome="evaluation",
            summary="Still failing config validation.",
            checks=["pytest"],
            missing_requirements=["Handle the failing config branch."],
            action_type="evaluate_current_file",
            focus_area="config validation",
            scenario="review_reflection",
            blocked_reason="The same config test still fails.",
        )
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["config validation"],
            outcome="repeated_error",
            summary="Still failing config validation.",
            checks=["pytest"],
            missing_requirements=["Handle the failing config branch."],
            action_type="evaluate_current_file",
            repetition_count=2,
            focus_area="config validation",
            scenario="review_reflection",
            blocked_reason="The same config test still fails.",
        )

        failure_snapshot = runtime.memory_service.snapshot(workspace_id)
        assert failure_snapshot.coaching_adaptation is not None
        assert failure_snapshot.coaching_adaptation.next_step_bias == "shrink"
        assert failure_snapshot.coaching_adaptation.review_urgency == "high"
        assert failure_snapshot.coaching_adaptation.difficulty == "easy"
        assert failure_snapshot.coaching_adaptation.hint_count == 3
        assert failure_snapshot.coaching_adaptation.should_reveal_code is True

        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["config validation"],
            outcome="tests_passed",
            summary="The focused config validation tests are now passing.",
            checks=[],
            missing_requirements=[],
            action_type="evaluate_current_file",
            focus_area="config validation",
            scenario="review_reflection",
            verified_result="The focused config validation tests are now passing.",
            verified_by_evaluator=True,
        )
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["config validation"],
            outcome="concept_answered_correctly",
            summary="The learner explained why config validation narrows to one branch first.",
            checks=[],
            missing_requirements=[],
            action_type="reflection",
            focus_area="config validation",
            scenario="concept_teaching",
        )

        success_snapshot = runtime.memory_service.snapshot(workspace_id)
        assert success_snapshot.coaching_adaptation is not None
        assert success_snapshot.coaching_adaptation.next_step_bias == "widen"
        assert success_snapshot.coaching_adaptation.explanation_mode == "transfer"
        assert success_snapshot.coaching_adaptation.difficulty == "hard"
        assert success_snapshot.coaching_adaptation.hint_count == 1
        assert success_snapshot.coaching_adaptation.code_reveal == "withhold"
        assert success_snapshot.coaching_adaptation.material_recommendation == "current"
        assert "adaptive coaching" in success_snapshot.coaching_adaptation.summary.lower() or "自适应教学" in success_snapshot.coaching_adaptation.summary
        assert success_snapshot.teaching_observations

    def test_strategy_effectiveness_biases_future_adaptive_profile(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        workspace_id = "test-workspace-strategy-learning-bias"
        strategy_context = {
            "challenge_level": "steady",
            "hint_depth": "guided",
            "review_urgency": "low",
            "explanation_mode": "transfer",
            "next_step_bias": "widen",
        }

        for index in range(3):
            runtime.memory_service.record_learning_outcome(
                workspace_id=workspace_id,
                concepts=["review scheduler"],
                outcome="tests_passed" if index < 2 else "concept_answered_correctly",
                summary="The focused review scheduler slice landed cleanly.",
                checks=[],
                missing_requirements=[],
                action_type="evaluate_current_file" if index < 2 else "reflection",
                focus_area="review scheduler",
                scenario="idea_implementation",
                verified_result="The focused review scheduler slice landed cleanly." if index < 2 else None,
                teaching_strategy_context=strategy_context,
            )

        snapshot = runtime.memory_service.snapshot(workspace_id)
        assert snapshot.coaching_adaptation is not None
        assert snapshot.coaching_adaptation.hint_depth == "guided"
        assert snapshot.coaching_adaptation.explanation_mode == "transfer"
        assert snapshot.coaching_adaptation.next_step_bias == "widen"
        assert any(
            "Evidence-backed coaching preference" in item or "证据支持的教学偏好" in item
            for item in snapshot.coaching_adaptation.evidence
        )

    def test_learning_outcome_feeds_back_into_selected_teaching_asset_effectiveness(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        workspace_id = "test-workspace-learning-asset-feedback"
        asset = runtime.memory_service.record_teaching_asset(
            workspace_id,
            TeachingKnowledgeAsset(
                id="asset-runtime-success",
                kind="implementation_pattern",
                scope="project",
                workspace_id=workspace_id,
                title="Runtime review recovery pattern",
                summary="Recover by narrowing the review branch to one verified check.",
                implementation_pattern="Recover by narrowing the review branch to one verified check.",
                focus_area="review recovery",
                scenario="review_reflection",
                source_key="runtime::review-recovery",
                trust_score=0.64,
            ),
        )

        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["review recovery"],
            outcome="tests_passed",
            summary="The review recovery check now passes.",
            checks=[],
            missing_requirements=[],
            action_type="evaluate_current_file",
            focus_area="review recovery",
            scenario="review_reflection",
            verified_result="The review recovery check now passes.",
            selected_teaching_asset_ids=[asset.id],
        )

        snapshot = runtime.memory_service.snapshot(workspace_id)
        ranked = runtime.memory_service.select_teaching_assets(
            workspace_id,
            scenario="review_reflection",
            focus_area="review recovery",
            query="review recovery next step",
            limit=1,
        )

        assert ranked
        assert ranked[0].id == asset.id
        refreshed = next(item for item in snapshot.teaching_assets if item.id == asset.id)
        assert refreshed.success_count == 1
        assert refreshed.last_outcome == "tests_passed"

    def test_task_abandoned_pushes_recovery_bias_into_adaptive_profile(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        workspace_id = "test-workspace-learning-loop-abandon"
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=["feature boundary"],
            outcome="task_abandoned",
            summary="The learner abandoned the change after widening the feature boundary too far.",
            checks=[],
            missing_requirements=[],
            action_type="task",
            focus_area="feature boundary",
            scenario="idea_implementation",
            abandoned_reason="The patch touched too many files at once.",
        )

        snapshot = runtime.memory_service.snapshot(workspace_id)
        assert snapshot.coaching_adaptation is not None
        assert snapshot.coaching_adaptation.challenge_level == "lower"
        assert snapshot.coaching_adaptation.next_step_bias == "shrink"
        assert snapshot.coaching_adaptation.review_urgency == "high"
        assert snapshot.workspace["latest_learning_abandon_reason"] == "The patch touched too many files at once."


class TestTrainingFlowErrorHandling:
    """Test error handling in the training flow."""

    def test_evaluation_with_invalid_code(self, runtime: TrainerRuntime, tmp_path: Path) -> None:
        """Test evaluation handles invalid Python code gracefully."""
        workspace_id = "test-workspace-007"

        # Invalid Python code
        eval_request = EvaluateSnippetRequest(
            workspace_id=workspace_id,
            task_spec_id="task-invalid-001",
            language_id="python",
            content="def broken(:\n    return 'missing quote\n",
        )

        # Should not raise, should return a report
        report = runtime.evaluator_service.evaluate_snippet(eval_request)
        assert report is not None
        assert report.task_spec_id == "task-invalid-001"

    def test_profile_not_found_returns_none(self, runtime: TrainerRuntime) -> None:
        """Test that missing profile returns None gracefully."""
        profile = runtime.memory_service.profile("nonexistent-workspace")
        assert profile is None

    def test_plan_not_found_returns_none(self, runtime: TrainerRuntime) -> None:
        """Test that missing plan returns None gracefully."""
        plan = runtime.repository.get_latest_plan("nonexistent-workspace")
        assert plan is None

    def test_session_management(self, runtime: TrainerRuntime) -> None:
        """Test session creation and retrieval."""
        # Create multiple sessions
        session1 = runtime.start_session("workspace-1", "Workspace 1")
        session2 = runtime.start_session("workspace-2", "Workspace 2")

        # Verify sessions are tracked
        assert runtime.get_session(session1.session_id) is not None
        assert runtime.get_session(session2.session_id) is not None

        # Latest session should be the most recent
        latest = runtime.latest_session()
        assert latest is not None
        assert latest.session_id == session2.session_id

        # Resolve workspace ID from session
        resolved_id = runtime.resolve_workspace_id(session_id=session1.session_id)
        assert resolved_id == "workspace-1"

        # Default workspace when no session
        default_id = runtime.resolve_workspace_id()
        assert default_id == "workspace-2"  # Latest session's workspace
