from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.models import ProviderConfig, TrainingCardCandidateSnapshot
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.memory.transfer_skills import should_promote_transferable_skill
from app.pedagogy.evidence_controls import (
    LearningEvidenceSignals,
    analyze_learning_evidence,
    apply_controls_to_card,
    apply_review_frequency_bias,
    pedagogy_evidence_confidence,
    resolve_pedagogy_controls,
    review_after_days_for_frequency,
    routing_learner_overrides,
    streak_adapts_without_inventing_live_objects,
)
from app.training.fsrs_scheduler import FSRSTrainerCardScheduler, TrainingRating


def test_consecutive_failures_degrade_to_easier_scaffolding() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=0, failure_streak=2, failure_count=2, historical_error_count=2)
    )

    assert controls.difficulty == "easy"
    assert controls.hint_count == 3
    assert controls.should_reveal_code is True
    assert controls.code_reveal == "full"
    assert controls.practice_type == "recover"
    assert controls.review_frequency == "sooner"
    assert controls.material_recommendation == "simpler"
    assert controls.next_plan_step == "shrink"
    assert controls.challenge_level == "lower"
    assert controls.pedagogy_mode == "debug_guide"
    overrides = routing_learner_overrides(controls)
    assert overrides["difficulty_preference"] == "easy"
    assert overrides["needs_rescue"] is True
    assert review_after_days_for_frequency(controls.review_frequency) == 1


def test_consecutive_successes_upgrade_and_withhold_code() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(
            success_streak=2,
            failure_streak=0,
            success_count=2,
            concept_success=True,
            verified_success=True,
        )
    )

    assert controls.difficulty == "hard"
    assert controls.hint_count == 1
    assert controls.should_reveal_code is False
    assert controls.code_reveal == "withhold"
    assert controls.practice_type == "stretch"
    assert controls.review_frequency == "later"
    assert controls.next_plan_step == "widen"
    assert controls.challenge_level == "raise"
    assert routing_learner_overrides(controls)["difficulty_preference"] == "hard"
    assert review_after_days_for_frequency(controls.review_frequency) == 4


def test_success_streak_overrides_older_repeated_failure() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(
            success_streak=2,
            failure_streak=0,
            success_count=2,
            failure_count=2,
            repeated_failure=True,
            concept_success=True,
            verified_success=True,
            historical_error_count=2,
        )
    )
    assert controls.difficulty == "hard"
    assert controls.next_plan_step == "widen"
    assert controls.challenge_level == "raise"


def test_single_success_does_not_raise_difficulty() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=1, success_count=1, concept_success=True)
    )

    assert controls.difficulty == "medium"
    assert controls.challenge_level == "steady"
    assert controls.hint_count == 2
    assert controls.code_reveal == "scaffold"
    assert controls.should_reveal_code is False
    assert controls.explanation_mode == "transfer"


def test_one_scene_success_does_not_recommend_transfer_or_promote() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(
            success_streak=2,
            success_count=2,
            concept_success=True,
            verified_success=True,
        ),
        transfer_scene_count=1,
        transfer_state="awaiting_second_scene",
    )

    assert controls.difficulty == "hard"
    assert controls.material_recommendation == "current"
    assert controls.explanation_depth == "grounded"
    assert controls.transferable is False
    assert (
        should_promote_transferable_skill(
            concept="router design",
            workspace_id="project-a",
            current_scene_key="default",
            existing_scenes=[{"workspace_id": "project-a", "scene_key": "default"}],
            outcome_success=True,
        )
        is False
    )


def test_two_scenes_can_recommend_transfer_without_claiming_one_project_mastery() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=2, success_count=2, concept_success=True),
        transfer_scene_count=2,
        transfer_state="transferable",
    )
    assert controls.material_recommendation == "transfer"
    assert controls.explanation_depth == "transfer"
    assert controls.transferable is True
    assert (
        should_promote_transferable_skill(
            concept="router design",
            workspace_id="project-b",
            current_scene_key="default",
            existing_scenes=[{"workspace_id": "project-a", "scene_key": "default"}],
            outcome_success=True,
        )
        is True
    )


def test_card_application_adds_hints_on_failure_and_strips_code_on_success() -> None:
    starter = TrainingCardCandidateSnapshot(
        card_type="practice",
        title="Practice router",
        suggested_workspace_action="```python\ndef fix():\n    return True\n```",
        hint_ladder=["Name the failing test."],
        difficulty="medium",
    )
    easier = apply_controls_to_card(
        starter,
        resolve_pedagogy_controls(LearningEvidenceSignals(failure_streak=2, failure_count=2)),
        language="en-US",
    )
    assert easier.difficulty == "easy"
    assert len(easier.hint_ladder) == 3
    assert "```" in (easier.suggested_workspace_action or "")

    harder = apply_controls_to_card(
        starter,
        resolve_pedagogy_controls(
            LearningEvidenceSignals(success_streak=2, success_count=2, verified_success=True)
        ),
        language="en-US",
    )
    assert harder.difficulty == "hard"
    assert len(harder.hint_ladder) == 1
    assert "```" not in (harder.suggested_workspace_action or "")
    assert "full solution" in (harder.suggested_workspace_action or "").lower()


def test_fsrs_review_frequency_shortens_or_lengthens_interval() -> None:
    assert apply_review_frequency_bias(6, "sooner") == 3
    assert apply_review_frequency_bias(6, "later") == 12

    scheduler = FSRSTrainerCardScheduler()
    scheduler.create_card("card-soon", "concept")
    soon = scheduler.process_review("card-soon", TrainingRating.GOOD, review_frequency="sooner")
    scheduler.create_card("card-later", "concept")
    later = scheduler.process_review("card-later", TrainingRating.GOOD, review_frequency="later")
    assert soon.new_interval <= later.new_interval


def test_user_preference_can_raise_but_affect_overload_stays_degraded() -> None:
    raised = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=1, success_count=1),
        user_preference="too_simple",
    )
    assert raised.difficulty == "hard"
    assert raised.challenge_level == "raise"

    overloaded = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=2, success_count=2),
        user_preference="too_simple",
        affect_recovery="overloaded",
    )
    assert overloaded.difficulty == "easy"
    assert overloaded.pedagogy_mode == "debug_guide"


def _client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Evidence Controls Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-evidence-controls.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def _start(client: TestClient, workspace_id: str) -> str:
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": workspace_id,
            "profile": {
                "long_term_goal": "Let evidence change difficulty",
                "weekly_hours": 4,
                "teaching_style": "guided",
                "answer_policy": "guided",
            },
        },
    )
    assert response.status_code == 200
    return str(response.json()["session_id"])


def _signal(client: TestClient, session_id: str, workspace_id: str, outcome: str, summary: str) -> dict:
    response = client.post(
        "/learning/signal",
        json={
            "session_id": session_id,
            "workspace_id": workspace_id,
            "concepts": ["config validation"],
            "outcome": outcome,
            "summary": summary,
            "action_type": "evaluate_current_file",
            "focus_area": "config validation",
            "scenario": "review_reflection",
            "repetition_count": 2 if outcome in {"repeated_error", "evaluation"} else 1,
        },
    )
    assert response.status_code == 200
    return response.json()


def _model_practice_card_json() -> str:
    return json.dumps(
        {
            "title": "Practice config validation",
            "focus_area": "config validation",
            "target_skill": "verify one config branch",
            "scenario": "A config branch keeps failing and needs one verified slice.",
            "problem_statement": "Reproduce the failing config branch and verify one fix.",
            "api_hints": ["Run the config check", "Fix one failing branch"],
            "deliverable": "A snippet that validates the fixed branch.",
            "self_check": ["The branch passes", "No other branch changed"],
            "grading_rubric": ["Fixes the failing branch", "Includes verification output"],
            "stuck_recovery": "Write the expected config shape on paper first.",
            "reflection_prompt": "What assumption made the branch fail?",
        }
    )


def _configure_verified_provider(client: TestClient) -> None:
    provider = ProviderConfig(
        name="test",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.test",
        model="gpt-4o-mini",
        capabilities={"chat": True, "streaming": True},
    )
    runtime = client.app.state.runtime
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test")

    from tests.provider_fixtures import seed_verified_capabilities

    seed_verified_capabilities(runtime, provider, "sk-test", tools=False)


def test_generate_card_follows_failure_and_success_streaks(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _configure_verified_provider(client)
        fail_workspace = "workspace-evidence-failures"
        session_id = _start(client, fail_workspace)
        _signal(client, session_id, fail_workspace, "evaluation", "Config validation still fails.")
        fail_payload = _signal(
            client,
            session_id,
            fail_workspace,
            "repeated_error",
            "Config validation still fails.",
        )
        adaptation = fail_payload["memory"]["coaching_adaptation"]
        assert adaptation["difficulty"] == "easy"
        assert adaptation["hint_count"] == 3
        assert adaptation["should_reveal_code"] is True
        assert adaptation["failure_streak"] >= 2
        with patch.object(
            ProviderService,
            "chat_completion",
            new=AsyncMock(return_value=_model_practice_card_json()),
        ):
            generated = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": fail_workspace,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "config validation",
                    "context_hint": "The learner is stuck on one failing config branch.",
                    "response_language": "en-US",
                },
            )
        assert generated.status_code == 200
        fail_card = generated.json()["card"]
        assert fail_card["difficulty"] == "easy"
        assert len(fail_card.get("hint_ladder") or []) >= 3

        win_workspace = "workspace-evidence-successes"
        win_session = _start(client, win_workspace)
        # Client-claimed tests_passed via /learning/signal is low-trust: not proof.
        _signal(client, win_session, win_workspace, "tests_passed", "The focused tests now pass.")
        win_payload = _signal(
            client,
            win_session,
            win_workspace,
            "concept_answered_correctly",
            "The learner explained the config boundary correctly.",
        )
        win_adaptation = win_payload["memory"]["coaching_adaptation"]
        assert win_adaptation["difficulty"] == "medium"
        assert win_adaptation["challenge_level"] == "steady"
        assert win_adaptation["material_recommendation"] == "current"
        assert win_adaptation["next_plan_step"] == "hold"
        transfer = win_payload["memory"]["workspace"].get("latest_transfer_state") or {}
        assert transfer.get("state") in {"", None, "project_only", "awaiting_second_scene"}
        assert transfer.get("state") != "transferable"
        assert not (win_payload.get("global_memory") or {}).get("capability_profile")
        with patch.object(
            ProviderService,
            "chat_completion",
            new=AsyncMock(return_value=_model_practice_card_json()),
        ):
            win_card = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": win_workspace,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "config validation",
                    "context_hint": "The learner just verified one local slice.",
                    "response_language": "en-US",
                },
            )
        assert win_card.status_code == 200
        steady_card = win_card.json()["card"]
        assert steady_card["difficulty"] == "medium"


def test_socratic_mode_is_evidence_gated() -> None:
    socratic = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=2, success_count=2),
        preferred_teaching_style="guided",
    )
    assert socratic.pedagogy_mode == "socratic"
    assert socratic.should_reveal_code is False

    debug = resolve_pedagogy_controls(
        LearningEvidenceSignals(failure_streak=2, failure_count=2),
        preferred_teaching_style="socratic",
    )
    assert debug.pedagogy_mode == "debug_guide"
    assert debug.should_reveal_code is True


def test_unverified_success_streak_does_not_raise_or_claim_mastery() -> None:
    controls = resolve_pedagogy_controls(
        LearningEvidenceSignals(success_streak=2, success_count=2, concept_success=True)
    )
    assert controls.difficulty == "medium"
    assert controls.challenge_level == "steady"
    assert controls.next_plan_step == "hold"
    assert controls.transferable is False
    assert controls.material_recommendation == "current"
    assert pedagogy_evidence_confidence(verified_success=False, success_count=2) == 0.25
    assert pedagogy_evidence_confidence(verified_success=True, success_count=2) == 0.8
    assert pedagogy_evidence_confidence(verified_success=False, success_count=0) == 0.5
    assert (
        pedagogy_evidence_confidence(
            verified_success=False,
            success_count=0,
            outcomes=[
                {
                    "outcome": "tests_passed",
                    "summary": "Client claimed",
                    "verified_by_evaluator": False,
                }
            ],
        )
        == 0.25
    )

def test_untrusted_outcome_labels_are_not_verified_proof() -> None:
    signals = analyze_learning_evidence(
        [
            {"outcome": "tests_passed", "summary": "Client claimed pass", "verified_by_evaluator": False},
            {
                "outcome": "tests_passed",
                "summary": "Empty verified_result",
                "verified_by_evaluator": True,
                "verified_result": "",
            },
            {"outcome": "concept_answered_correctly", "summary": "Explained locally"},
        ]
    )
    assert signals.verified_success is False
    # Untrusted labels break the streak; concept alone may still count but cannot raise.
    assert signals.success_streak == 0
    assert signals.success_count == 1
    controls = resolve_pedagogy_controls(signals)
    assert controls.difficulty == "medium"
    assert controls.challenge_level == "steady"
    assert controls.transferable is False

    trusted = analyze_learning_evidence(
        [
            {
                "outcome": "tests_passed",
                "summary": "Evaluator ack",
                "verified_by_evaluator": True,
                "verified_result": "Focused checks passed.",
            },
            {
                "outcome": "code_landed",
                "summary": "Second ack",
                "verified_by_evaluator": True,
                "verified_result": "Slice landed under the same boundary.",
            },
        ]
    )
    assert trusted.verified_success is True
    assert trusted.success_streak == 2
    raised = resolve_pedagogy_controls(trusted)
    assert raised.difficulty == "hard"
    assert raised.challenge_level == "raise"
    assert raised.transferable is False


def test_streak_adapts_without_inventing_live_objects() -> None:
    assert (
        streak_adapts_without_inventing_live_objects(
            failure_streak=2,
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is True
    )
    assert (
        streak_adapts_without_inventing_live_objects(
            failure_streak=2,
            live_plan=True,
            live_task=False,
            live_card=False,
        )
        is False
    )
    assert (
        streak_adapts_without_inventing_live_objects(
            success_streak=2,
            live_plan=False,
            live_task=False,
            live_card=False,
        )
        is True
    )
    assert (
        streak_adapts_without_inventing_live_objects(
            success_streak=2,
            live_card=True,
        )
        is False
    )


def test_consecutive_unverified_tests_passed_does_not_mark_mastery_or_mint(
    tmp_path: Path,
) -> None:
    """Client tests_passed without evaluator+verified_result is not mastery."""

    workspace_id = "workspace-unverified-tests-passed-streak"
    with _client(tmp_path) as client:
        session_id = _start(client, workspace_id)
        first = _signal(
            client,
            session_id,
            workspace_id,
            "tests_passed",
            "Client claimed pass one.",
        )
        second = _signal(
            client,
            session_id,
            workspace_id,
            "tests_passed",
            "Client claimed pass two.",
        )
        coaching = (second.get("memory") or {}).get("coaching_adaptation") or {}
        assert int(coaching.get("success_streak") or 0) == 0
        assert coaching.get("challenge_level") == "steady"
        assert coaching.get("next_plan_step") == "hold"
        assert coaching.get("material_recommendation") != "transfer"
        assert second.get("plan") in (None, {})
        assert not (second.get("current_task") or second.get("currentTask") or {}).get("title")
        mastery = (second.get("memory") or {}).get("mastery") or []
        assert mastery == []
        structured = client.app.state.runtime.memory_service._structured_for(workspace_id)
        assert "config validation" not in structured._mastery
        transfer = ((second.get("memory") or {}).get("workspace") or {}).get("latest_transfer_state") or {}
        assert transfer.get("state") not in {"transferable"}
        # First payload also must not have raised from a lone unverified label.
        first_coaching = (first.get("memory") or {}).get("coaching_adaptation") or {}
        assert int(first_coaching.get("success_streak") or 0) == 0


def test_consecutive_failure_signal_adapts_hints_without_live_objects(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-fail-streak-hint-only"
    with _client(tmp_path) as client:
        session_id = _start(client, workspace_id)
        _signal(client, session_id, workspace_id, "evaluation", "Still failing check A.")
        payload = _signal(
            client,
            session_id,
            workspace_id,
            "repeated_error",
            "Still failing check A again.",
        )
        coaching = (payload.get("memory") or {}).get("coaching_adaptation") or {}
        assert int(coaching.get("failure_streak") or 0) >= 2
        assert coaching.get("hint_count") == 3
        assert coaching.get("challenge_level") == "lower"
        assert coaching.get("next_plan_step") == "shrink"
        assert payload.get("plan") in (None, {})
        assert not (payload.get("current_task") or payload.get("currentTask") or {}).get("title")
        assert streak_adapts_without_inventing_live_objects(
            failure_streak=int(coaching.get("failure_streak") or 0),
            live_plan=False,
            live_task=False,
            live_card=False,
        )


def test_identical_failure_signals_still_raise_consecutive_streak(
    tmp_path: Path,
) -> None:
    """Same concept+outcome+action overwrites one record; streak uses repetition."""

    workspace_id = "workspace-identical-fail-overwrite"
    with _client(tmp_path) as client:
        session_id = _start(client, workspace_id)
        body = {
            "session_id": session_id,
            "workspace_id": workspace_id,
            "concepts": ["config validation"],
            "outcome": "evaluation",
            "summary": "Same failing check.",
            "action_type": "evaluate_current_file",
            "focus_area": "config validation",
            "scenario": "review_reflection",
        }
        first = client.post("/learning/signal", json=body)
        assert first.status_code == 200
        second = client.post(
            "/learning/signal",
            json={**body, "summary": "Same failing check again."},
        )
        assert second.status_code == 200
        payload = second.json()
        coaching = (payload.get("memory") or {}).get("coaching_adaptation") or {}
        assert int(coaching.get("failure_streak") or 0) >= 2
        assert coaching.get("hint_count") == 3
        assert coaching.get("challenge_level") == "lower"
        structured = client.app.state.runtime.memory_service._structured_for(workspace_id)
        assert len(structured._learning_outcomes) == 1
        only = next(iter(structured._learning_outcomes.values()))
        assert int(only.repetition_count or 0) >= 2
        assert payload.get("plan") in (None, {})
        assert not (payload.get("current_task") or payload.get("currentTask") or {}).get("title")
        assert streak_adapts_without_inventing_live_objects(
            failure_streak=int(coaching.get("failure_streak") or 0),
            live_plan=False,
            live_task=False,
            live_card=False,
        )


def test_client_repetition_count_99_is_not_mastery_theater(tmp_path: Path) -> None:
    """Client-claimed repetition_count must not inflate streak/mastery theater."""
    workspace_id = "workspace-client-rep-99"
    with _client(tmp_path) as client:
        session_id = _start(client, workspace_id)
        response = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "concepts": ["config validation"],
                "outcome": "evaluation",
                "summary": "Client claims ninety-nine repeats of the same miss.",
                "action_type": "evaluate_current_file",
                "focus_area": "config validation",
                "scenario": "review_reflection",
                "repetition_count": 99,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        coaching = (payload.get("memory") or {}).get("coaching_adaptation") or {}
        assert int(coaching.get("failure_streak") or 0) < 99
        assert int(coaching.get("success_streak") or 0) < 99
        assert int(coaching.get("failure_streak") or 0) <= 1
        mastery = (payload.get("memory") or {}).get("mastery") or []
        assert mastery == []
        structured = client.app.state.runtime.memory_service._structured_for(workspace_id)
        only = next(iter(structured._learning_outcomes.values()))
        assert int(only.repetition_count or 0) == 1
        assert "config validation" not in structured._mastery


def test_analyze_learning_evidence_counts_repetition_as_streak() -> None:
    signals = analyze_learning_evidence(
        [
            {
                "outcome": "evaluation",
                "repetition_count": 2,
                "summary": "Same miss twice via overwrite key.",
            }
        ]
    )
    assert signals.failure_streak >= 2
    assert signals.failure_count >= 2
    assert signals.repeated_failure is True
