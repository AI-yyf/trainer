"""Fail-closed: live evaluate → /memory/summary must not JSON-emit plan:null.

Host treats explicit plan:null as leftover-not-live and strips live chrome.
After live plan+card, summary must send the live plan object (or omit the key) —
never null leftover. Leftover-not-live may still emit plan:null + recovered.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import (
    ActiveCardSelectionResult,
    EvaluationCheck,
    EvaluationReport,
    LearningPlan,
    PlanStage,
    ProviderConfig,
    TrainingCardCandidateSnapshot,
)
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer memory summary plan omit",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-memory-summary-plan-omit.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _passed_report() -> EvaluationReport:
    return EvaluationReport(
        task_spec_id="",
        summary="Live evaluate under bound plan+card.",
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
        next_step="Keep the live card.",
        reflection="",
        passed=True,
    )


def _raw_has_plan_null(raw: bytes | str) -> bool:
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    compact = text.replace(" ", "")
    return '"plan":null' in compact


def _seed_provider(app) -> None:
    """Seed an offline provider with observed capabilities so provider-gated routes pass."""

    provider = ProviderConfig(
        name="test-openai-compatible",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={
            "chat": True,
            "responses": True,
            "vision": False,
            "embeddings": False,
            "tools": False,
            "json_schema": False,
            "streaming": True,
        },
    )
    runtime = app.state.runtime
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test-not-a-real-key-aaaaaaaa"
    runtime.provider_service = ProviderService(
        config=provider,
        api_key="sk-test-not-a-real-key-aaaaaaaa",
    )
    runtime.provider_service_cache.clear()
    seed_verified_capabilities(
        runtime,
        provider,
        "sk-test-not-a-real-key-aaaaaaaa",
        tools=False,
    )


def test_live_evaluate_then_memory_summary_sends_live_plan_not_null(
    tmp_path: Path,
) -> None:
    workspace_id = "ws-eval-summary-live-plan-omit"
    card_id = "card-live-eval-summary-1"
    settings = _settings(tmp_path / "data")
    app = create_app(settings)
    _seed_provider(app)

    with TestClient(app) as client:
        runtime = app.state.runtime
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Omit lab"},
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Ship token refresh auth"],
            },
        )
        assert generated.status_code == 200, generated.text
        plan = generated.json().get("plan") or generated.json()
        plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
        assert plan_id

        card = TrainingCardCandidateSnapshot(
            card_id=card_id,
            card_type="practice",
            title="Auth expiry practice",
            status="active",
            focus_area="token expiry",
            target_skill="auth expiry",
        )
        runtime.memory_service.upsert_card(workspace_id, card)
        runtime.memory_service.persist_active_card_selection(
            workspace_id,
            ActiveCardSelectionResult(
                selected_card=card,
                selected_card_id=card.card_id,
                why_this_card="Live card under evaluate summary omit proof.",
                next_after_completion="Return through training handoff.",
                fallback_action="Bring the blocker back to Coach.",
                candidate_count=1,
                eligible_count=1,
            ),
        )

        runtime.evaluator_service.evaluate_current_file = MagicMock(
            return_value=_passed_report()
        )
        evaluate = client.post(
            "/evaluate/current-file",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "file_path": str(tmp_path / "auth.py"),
                "language_id": "python",
                "content": "def require_fresh(token):\n    return bool(token)\n",
                "diagnostics": [],
                "evaluation_source": "training",
                "training_card_id": card_id,
                "training_card_title": "Auth expiry practice",
            },
        )
        assert evaluate.status_code == 200, evaluate.text
        # Evaluate returns the report only — must not smuggle plan:null.
        assert "plan" not in evaluate.json()
        assert not _raw_has_plan_null(evaluate.content)

        summary = client.get(
            f"/memory/summary?workspace_id={workspace_id}&session_id={session_id}"
        )
        assert summary.status_code == 200, summary.text
        assert not _raw_has_plan_null(summary.content), (
            "live summary must not emit plan:null (host would strip live chrome)"
        )
        body = summary.json()
        assert "plan" in body
        summary_plan = body.get("plan")
        assert isinstance(summary_plan, dict)
        assert str(summary_plan.get("id") or summary_plan.get("plan_id") or "").strip() == plan_id

        workspace = (body.get("memory") or {}).get("workspace") or {}
        selected = str(
            workspace.get("selected_card_id") or workspace.get("selectedCardId") or ""
        ).strip()
        assert selected == card_id

        runtime_overlay = (
            workspace.get("latest_plan_runtime") or workspace.get("latestPlanRuntime") or {}
        )
        assert str(runtime_overlay.get("plan_id") or runtime_overlay.get("planId") or "").strip() == (
            plan_id
        )
        # Leftover-not-live overlay is OFF: live plan object present (host strips only on
        # explicit plan:null). recovered may still be True when runtime facts exist.
        status = body.get("plan_runtime_status") or body.get("planRuntimeStatus") or {}
        leftover_overlay = body.get("plan") is None and status.get("recovered") is True
        assert leftover_overlay is False


def test_leftover_not_live_memory_summary_may_emit_plan_null_with_recovered(
    tmp_path: Path,
) -> None:
    workspace_id = "ws-eval-summary-leftover-plan-null"
    leftover_step = "Keep one auth check"
    settings = _settings(tmp_path / "data-leftover")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover = LearningPlan(
            id="plan-leftover-summary-null",
            title="Keep the leftover stage",
            current_step=leftover_step,
            stages=[
                PlanStage(
                    id="stage-leftover",
                    title="Leftover",
                    goal="Stay leftover-not-live",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        app.state.runtime.repository.save_plan(workspace_id, leftover)

        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Leftover null lab"},
        )
        assert started.status_code == 200, started.text
        assert _raw_has_plan_null(started.content)
        start_status = (
            started.json().get("plan_runtime_status")
            or started.json().get("planRuntimeStatus")
            or {}
        )
        assert start_status.get("recovered") is True

        summary = client.get(f"/memory/summary?workspace_id={workspace_id}")
        assert summary.status_code == 200, summary.text
        assert _raw_has_plan_null(summary.content)
        body = summary.json()
        assert body.get("plan") is None
        status = body.get("plan_runtime_status") or body.get("planRuntimeStatus") or {}
        assert status.get("recovered") is True
