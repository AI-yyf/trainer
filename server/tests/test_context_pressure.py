from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import (
    FirstLookSummary,
    LearningPlan,
    PlanStage,
    TaskSpec,
    TrainingCardCandidateSnapshot,
    UserProfile,
    WorkspaceUnderstandingSnapshot,
)
from app.core.settings import AppSettings
from app.llm.prompts import build_coaching_system_prompt
from app.main import create_app
from app.pedagogy.context_pressure import derive_context_pressure
from app.pedagogy.evidence_controls import LearningEvidenceSignals, resolve_pedagogy_controls
from app.pedagogy.material_recommendation import resolve_material_routing
from app.training.card_router import CardRouterService

SUCCESS = LearningEvidenceSignals(
    success_streak=2,
    success_count=2,
    concept_success=True,
    verified_success=True,
)


def _card(**overrides: object) -> TrainingCardCandidateSnapshot:
    defaults: dict[str, object] = {
        "card_id": "card-1",
        "card_type": "practice",
        "title": "Test card",
        "focus_area": "testing",
        "target_skill": "unit tests",
        "difficulty": "medium",
        "problem_statement": "Write a unit test.",
        "deliverable": "A passing test file.",
        "validation_method": "pytest runs green.",
        "expected_answer": "N/A",
        "hint_ladder": ["Start with assert"],
        "created_from": "conversation",
        "status": "candidate",
        "project_id": "proj-1",
    }
    defaults.update(overrides)
    return TrainingCardCandidateSnapshot(**defaults)


def test_weekly_hours_and_rhythm_become_time_budget() -> None:
    tight = derive_context_pressure(profile=UserProfile(weekly_hours=2))
    assert tight.time_budget == "tight"
    ample = derive_context_pressure(profile=UserProfile(weekly_hours=8))
    assert ample.time_budget == "ample"
    rhythm = derive_context_pressure(
        profile=UserProfile(weekly_hours=4),
        workspace={"preferred_rhythm": "small-step"},
    )
    assert rhythm.time_budget == "tight"
    default = derive_context_pressure(profile=UserProfile(weekly_hours=4))
    assert default.time_budget == "normal"


def test_missing_repo_plan_uses_scoped_plan_runtime_for_pressure() -> None:
    blocked = derive_context_pressure(
        workspace={
            "workspace_id": "workspace-plan-a",
            "latest_plan_runtime": {
                "workspace_id": "workspace-plan-a",
                "blocked_reason": "auth check still fails",
                "current_step": "Keep one auth check",
            },
        }
    )
    assert blocked.task_urgency == "high"
    assert "blocker" in blocked.evidence

    hold = derive_context_pressure(
        workspace={
            "workspace_id": "workspace-plan-a",
            "latest_plan_runtime": {
                "workspace_id": "workspace-plan-a",
                "current_step": "Keep one auth check",
            },
        }
    )
    assert hold.task_urgency == "medium"
    assert "plan_runtime:current_step" in hold.evidence

    live_plan_wins = derive_context_pressure(
        plan=LearningPlan(title="Live plan", current_step="Stay on the live stage"),
        workspace={
            "workspace_id": "workspace-plan-a",
            "latest_plan_runtime": {
                "workspace_id": "workspace-plan-a",
                "blocked_reason": "stale blocker must not override a live plan",
                "current_step": "Stale step",
            },
        },
    )
    assert live_plan_wins.task_urgency == "medium"
    assert "blocker" not in live_plan_wins.evidence

    foreign = derive_context_pressure(
        workspace={
            "workspace_id": "workspace-plan-b",
            "latest_plan_runtime": {
                "workspace_id": "workspace-plan-a",
                "blocked_reason": "auth check still fails",
                "current_step": "Keep one auth check",
            },
        }
    )
    assert foreign.task_urgency == "medium"
    assert "blocker" not in foreign.evidence
    assert "plan_runtime:current_step" not in foreign.evidence

    incomplete = derive_context_pressure(
        workspace={
            "workspace_id": "workspace-plan-a",
            "latest_plan_runtime": {
                "workspace_id": "workspace-plan-a",
                "plan_id": "plan-missing-from-repo",
                "frozen": True,
            },
        }
    )
    assert incomplete.task_urgency == "medium"
    assert incomplete.evidence == ()


def test_urgency_comes_from_affect_blocker_and_due_reviews() -> None:
    affect = derive_context_pressure(affect_state={"urgency_level": "high"})
    assert affect.task_urgency == "high"
    blocked = derive_context_pressure(plan=LearningPlan(title="Plan", blocked_reason="stuck on auth"))
    assert blocked.task_urgency == "high"
    due = derive_context_pressure(
        due_reviews=[{"concept": "auth", "severity": "high", "source": "weakness", "surface_mode": "due"}]
    )
    assert due.task_urgency == "high"
    mastery_review = derive_context_pressure(
        due_reviews=[{"concept": "auth", "severity": "high", "source": "mastery", "surface_mode": "due"}]
    )
    assert mastery_review.task_urgency == "medium"
    calm = derive_context_pressure(affect_state={"urgency_level": "low"})
    assert calm.task_urgency == "low"


def test_complexity_comes_from_first_look_plan_and_task() -> None:
    simple = derive_context_pressure(
        workspace_understanding=WorkspaceUnderstandingSnapshot(
            firstLookSummary=FirstLookSummary(folder_role="empty_new_project")
        )
    )
    assert simple.project_complexity == "simple"
    complex_role = derive_context_pressure(
        workspace_understanding=WorkspaceUnderstandingSnapshot(
            firstLookSummary=FirstLookSummary(folder_role="existing_engineering")
        )
    )
    assert complex_role.project_complexity == "complex"
    wide_plan = derive_context_pressure(
        plan=LearningPlan(
            title="Wide",
            stages=[
                PlanStage(id=f"s{index}", title=f"S{index}", goal="g", outcomes=["a"])
                for index in range(5)
            ],
        )
    )
    assert wide_plan.project_complexity == "complex"
    heavy_task = derive_context_pressure(
        current_task=TaskSpec(
            id="t1",
            title="Heavy",
            natural_language_goal="ship",
            constraints=["a", "b"],
            edge_cases=["c"],
            failure_conditions=["d"],
        )
    )
    assert heavy_task.project_complexity == "complex"


def test_tight_budget_changes_next_step_and_scaffolding() -> None:
    open_stretch = resolve_pedagogy_controls(SUCCESS)
    assert open_stretch.difficulty == "hard"
    assert open_stretch.next_plan_step == "widen"
    assert open_stretch.code_reveal == "withhold"
    assert open_stretch.hint_count == 1

    tight = resolve_pedagogy_controls(SUCCESS, time_budget="tight")
    assert tight.time_budget == "tight"
    assert tight.next_plan_step == "shrink"
    assert tight.next_step_bias == "shrink"
    assert tight.difficulty == "medium"
    assert tight.code_reveal == "scaffold"
    assert tight.hint_count >= 2
    assert tight.practice_type == "focused"
    assert tight.material_recommendation == "current"


def test_complexity_changes_scaffolding_without_dumping_a_huge_step() -> None:
    complex_controls = resolve_pedagogy_controls(SUCCESS, project_complexity="complex")
    assert complex_controls.project_complexity == "complex"
    assert complex_controls.next_plan_step == "hold"
    assert complex_controls.code_reveal == "scaffold"
    assert complex_controls.hint_count >= 2
    assert complex_controls.material_recommendation == "current"

    simple_stretch = resolve_pedagogy_controls(SUCCESS, project_complexity="simple")
    assert simple_stretch.next_plan_step == "widen"
    assert simple_stretch.difficulty == "hard"
    assert simple_stretch.code_reveal == "withhold"
    assert simple_stretch.practice_type == "stretch"


def test_urgency_does_not_override_transfer_fail_closed() -> None:
    blocked = resolve_pedagogy_controls(
        SUCCESS,
        transfer_scene_count=1,
        transfer_state="awaiting_second_scene",
        task_urgency="high",
    )
    assert blocked.task_urgency == "high"
    assert blocked.material_recommendation == "current"
    assert blocked.next_plan_step == "shrink"
    assert blocked.transferable is False

    routing = resolve_material_routing(
        "transfer",
        transfer_scene_count=1,
        transfer_state="awaiting_second_scene",
        task_urgency="high",
    )
    assert routing.recommendation == "current"
    assert routing.allow_transfer_materials is False
    assert routing.orientation_key == "transfer_blocked"

    deferred = resolve_material_routing(
        "transfer",
        transfer_scene_count=2,
        transfer_state="transferable",
        task_urgency="high",
    )
    assert deferred.recommendation == "current"
    assert deferred.allow_transfer_materials is False
    assert deferred.orientation_key == "current"


def test_tight_budget_changes_card_ranking() -> None:
    svc = CardRouterService()
    short = _card(
        card_id="card-short",
        title="Short current slice",
        difficulty="easy",
        created_from="conversation",
        project_id="proj-1",
    )
    rabbit = _card(
        card_id="card-rabbit",
        title="Hard transfer rabbit hole",
        difficulty="hard",
        created_from="resource",
        project_id="proj-2",
        knowledge_type="engineering_concept",
    )
    result = svc.select_active_card(
        candidates=[rabbit, short],
        learner_state={
            "weaknesses": [],
            "recent_errors": [],
            "difficulty_preference": "hard",
            "needs_rescue": False,
            "active_blockers": [],
            "material_recommendation": "transfer",
            "transfer_scene_count": 2,
            "transfer_state": "transferable",
            "time_budget": "tight",
        },
        plan_state={"active_stage_id": "stage-1", "active_stage_skills": ["unit tests"], "active_project_id": "proj-1"},
    )
    assert result.selected_card_id == "card-short"
    assert "short" in result.next_after_completion.lower() or "current" in result.next_after_completion.lower()


def test_pressure_adapts_without_inventing_live_objects() -> None:
    from app.pedagogy.context_pressure import pressure_adapts_without_inventing_live_objects

    assert (
        pressure_adapts_without_inventing_live_objects(
            time_budget="tight",
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is True
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            task_urgency="high",
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is True
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            project_complexity="complex",
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is True
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            current_ability="struggling",
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is True
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            user_preference="too_hard",
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is True
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            user_preference="too_simple",
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is True
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            evidence_confidence=0.25,
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is True
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            project_complexity="complex",
            live_card=True,
        )
        is False
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            current_ability="struggling",
            live_plan=True,
        )
        is False
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            user_preference="too_hard",
            live_card=True,
        )
        is False
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            evidence_confidence=0.25,
            live_plan=True,
        )
        is False
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            evidence_confidence=0.8,
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is False
    )
    from app.pedagogy.context_pressure import preference_equivalent_from_strategy_bias

    assert (
        preference_equivalent_from_strategy_bias(
            challenge_level="lower",
            hint_depth="direct",
            next_step_bias="shrink",
        )
        == "too_hard"
    )
    assert (
        preference_equivalent_from_strategy_bias(
            hint_depth="direct",
            next_step_bias="shrink",
        )
        == "too_hard"
    )
    assert preference_equivalent_from_strategy_bias(feedback_next_step_bias="shrink") == "too_hard"
    assert (
        preference_equivalent_from_strategy_bias(
            challenge_level="raise",
            hint_depth="lighter",
            next_step_bias="widen",
        )
        == "too_simple"
    )
    assert preference_equivalent_from_strategy_bias(next_step_bias="shrink") == ""
    assert (
        pressure_adapts_without_inventing_live_objects(
            user_preference=preference_equivalent_from_strategy_bias(
                challenge_level="lower",
                hint_depth="direct",
                next_step_bias="shrink",
            ),
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is True
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            time_budget="tight",
            live_card=True,
        )
        is False
    )
    assert (
        pressure_adapts_without_inventing_live_objects(
            time_budget="normal",
            task_urgency="medium",
            project_complexity="moderate",
            current_ability="",
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is False
    )


def test_complexity_does_not_claim_mastery_theater() -> None:
    """Complex scaffolding must not unlock transfer or mastery theater."""
    complex_controls = resolve_pedagogy_controls(
        SUCCESS,
        project_complexity="complex",
        transfer_scene_count=1,
        transfer_state="awaiting_second_scene",
    )
    assert complex_controls.project_complexity == "complex"
    assert complex_controls.transferable is False
    assert complex_controls.material_recommendation == "current"
    assert complex_controls.next_plan_step == "hold"


def test_pedagogy_mode_rewrites_coach_system_prompt() -> None:
    profile = UserProfile(long_term_goal="learn routers", weekly_hours=4)
    socratic = build_coaching_system_prompt(
        profile,
        coach_context={"coaching_adaptation": {"pedagogy_mode": "socratic"}},
    )
    assert "## Pedagogy Mode" in socratic
    assert "Active mode: socratic" in socratic
    assert "Do not reveal the solution" in socratic

    debug = build_coaching_system_prompt(
        profile,
        coach_context={"coaching_adaptation": {"pedagogy_mode": "debug_guide"}},
    )
    assert "Active mode: debug_guide" in debug
    assert "Stay on one failing check" in debug

    direct = build_coaching_system_prompt(
        profile,
        coach_context={"coaching_adaptation": {"pedagogy_mode": "direct"}},
    )
    assert "Active mode: direct" in direct
    assert "one slice" in direct


def _client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Context Pressure Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-context-pressure.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_snapshot_weekly_hours_changes_adaptation_next_step(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-tight-budget",
                "workspace_name": "workspace-tight-budget",
                "profile": {
                    "long_term_goal": "Ship a thin slice",
                    "weekly_hours": 2,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert response.status_code == 200
        session_id = str(response.json()["session_id"])
        for summary in (
            "The focused tests now pass.",
            "The learner explained the config boundary correctly.",
        ):
            outcome = "tests_passed" if "tests" in summary else "concept_answered_correctly"
            signal = client.post(
                "/learning/signal",
                json={
                    "session_id": session_id,
                    "workspace_id": "workspace-tight-budget",
                    "concepts": ["config validation"],
                    "outcome": outcome,
                    "summary": summary,
                    "action_type": "evaluate_current_file",
                    "focus_area": "config validation",
                    "scenario": "review_reflection",
                    "repetition_count": 1,
                },
            )
            assert signal.status_code == 200
        adaptation = signal.json()["memory"]["coaching_adaptation"]
        assert adaptation["time_budget"] == "tight"
        assert adaptation["next_plan_step"] == "shrink"
        assert adaptation["next_step_bias"] == "shrink"
        assert adaptation["material_recommendation"] == "current"
        assert adaptation["hint_count"] >= 2
        assert adaptation["code_reveal"] == "scaffold"
