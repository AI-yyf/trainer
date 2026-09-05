"""FSRS on training verify: live existing card only; no mint; no global promote."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import (
    ActiveCardSelectionResult,
    EvaluationCheck,
    EvaluationReport,
    ProviderConfig,
    TrainingCardCandidateSnapshot,
)
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer live training FSRS verify",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-live-fsrs-verify.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _passed_report() -> EvaluationReport:
    return EvaluationReport(
        task_spec_id="",
        summary="Live training card verified under evaluator ack.",
        static_checks=[],
        dynamic_checks=[
            EvaluationCheck(
                id="dynamic-ok",
                label="dynamic-ok",
                status="passed",
                detail="Verifier ack.",
            )
        ],
        semantic_checks=[],
        next_step="Return through training handoff.",
        reflection="",
        passed=True,
    )


def _select(runtime: object, workspace_id: str, card: TrainingCardCandidateSnapshot) -> None:
    runtime.memory_service.persist_active_card_selection(
        workspace_id,
        ActiveCardSelectionResult(
            selected_card=card,
            selected_card_id=card.card_id,
            why_this_card="Live training card under verify.",
            next_after_completion="Return through training handoff.",
            fallback_action="Bring the blocker back to Coach.",
            candidate_count=1,
            eligible_count=1,
        ),
    )


def test_training_verify_schedules_fsrs_for_live_card_only(tmp_path: Path) -> None:
    workspace_id = "ws-live-fsrs-verify"
    card_id = "card-live-fsrs-1"
    settings = _settings(tmp_path / "data")
    app = create_app(settings)

    with TestClient(app) as client:
        runtime = app.state.runtime
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "FSRS lab"},
        )
        assert started.status_code == 200
        session_id = started.json()["session_id"]
        provider = ProviderConfig(
            name="test-openai-compatible",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={"chat": True, "streaming": True, "tools": False},
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()
        seed_verified_capabilities(runtime, provider, "sk-test", tools=False)

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Practice token expiry"],
            },
        )
        assert generated.status_code == 200, generated.text
        plan = generated.json().get("plan") or generated.json()
        plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
        assert plan_id

        card = TrainingCardCandidateSnapshot(
            card_id=card_id,
            card_type="practice",
            title="Expiry practice",
            status="active",
            focus_area="token expiry",
            target_skill="auth expiry",
        )
        runtime.memory_service.upsert_card(workspace_id, card)
        _select(runtime, workspace_id, card)
        cards_before = {
            str(getattr(item, "card_id", "") or "")
            for item in runtime.memory_service.get_cards(workspace_id)
        }
        assert card_id in cards_before

        runtime.evaluator_service.evaluate_current_file = MagicMock(return_value=_passed_report())
        evaluate = client.post(
            "/evaluate/current-file",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "file_path": str(tmp_path / "practice.py"),
                "language_id": "python",
                "content": "def require_fresh(token):\n    return bool(token)\n",
                "diagnostics": [],
                "evaluation_source": "training",
                "training_card_id": card_id,
                "training_card_title": "Expiry practice",
            },
        )
        assert evaluate.status_code == 200, evaluate.text
        assert evaluate.json().get("passed") is True

        memory = client.get(f"/memory/summary?workspace_id={workspace_id}").json()["memory"]
        workspace = memory.get("workspace") or {}
        fsrs_states = workspace.get("latest_training_fsrs_states") or {}
        assert card_id in fsrs_states
        assert set(fsrs_states.keys()) == {card_id}
        assert int(fsrs_states[card_id].get("reps") or 0) >= 1
        assert str(fsrs_states[card_id].get("state") or "")

        assert {
            str(getattr(item, "card_id", "") or "")
            for item in runtime.memory_service.get_cards(workspace_id)
        } == cards_before
        latest = runtime.repository.get_latest_plan(workspace_id)
        assert latest is not None
        assert str(getattr(latest, "id", "") or getattr(latest, "plan_id", "") or "").strip() == plan_id
        assert runtime.memory_service.global_memory().capability_profile == {}


def test_training_verify_skips_fsrs_when_selected_card_mismatches(tmp_path: Path) -> None:
    workspace_id = "ws-fsrs-mismatch"
    live_id = "card-live"
    other_id = "card-other"
    settings = _settings(tmp_path / "data")
    app = create_app(settings)

    with TestClient(app) as client:
        runtime = app.state.runtime
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "FSRS mismatch"},
        )
        assert started.status_code == 200
        session_id = started.json()["session_id"]

        live = TrainingCardCandidateSnapshot(
            card_id=live_id,
            card_type="practice",
            title="Live",
            status="active",
            focus_area="auth",
            target_skill="auth",
        )
        other = TrainingCardCandidateSnapshot(
            card_id=other_id,
            card_type="practice",
            title="Other",
            status="active",
            focus_area="auth",
            target_skill="auth",
        )
        runtime.memory_service.upsert_card(workspace_id, live)
        runtime.memory_service.upsert_card(workspace_id, other)
        _select(runtime, workspace_id, live)

        runtime.evaluator_service.evaluate_current_file = MagicMock(return_value=_passed_report())
        evaluate = client.post(
            "/evaluate/current-file",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "file_path": str(tmp_path / "other.py"),
                "language_id": "python",
                "content": "x = 1\n",
                "diagnostics": [],
                "evaluation_source": "training",
                "training_card_id": other_id,
                "training_card_title": "Other",
            },
        )
        assert evaluate.status_code == 200
        memory = client.get(f"/memory/summary?workspace_id={workspace_id}").json()["memory"]
        workspace = memory.get("workspace") or {}
        fsrs_states = workspace.get("latest_training_fsrs_states") or {}
        assert other_id not in fsrs_states
        assert live_id not in fsrs_states
        assert str(workspace.get("selected_card_id") or "").strip() == live_id
