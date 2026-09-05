"""Live formal plan must advance after evaluator-acked verify (runtime + formal)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import EvaluationCheck, EvaluationReport, ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.memory.workspace_recovery import leftover_formal_plan_is_live_for_fill


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer live plan verify advance",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-live-plan-verify.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _passed_report(summary: str, next_step: str) -> EvaluationReport:
    return EvaluationReport(
        task_spec_id="",
        summary=summary,
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
        next_step=next_step,
        reflection="",
        passed=True,
    )


def _card_ids(runtime: object, workspace_id: str) -> set[str]:
    memory = getattr(runtime, "memory_service", None)
    if memory is None:
        return set()
    return {
        str(getattr(card, "card_id", "") or "")
        for card in memory.get_cards(workspace_id)
        if str(getattr(card, "card_id", "") or "")
    }


def _runtime(workspace: dict) -> dict:
    return workspace.get("latest_plan_runtime") or workspace.get("latestPlanRuntime") or {}


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


def test_evaluator_ack_advances_live_plan_runtime_without_mint_or_global(
    tmp_path: Path,
) -> None:
    workspace_id = "ws-live-plan-verify-advance"
    summary = "Evaluator confirmed the auth expiry slice under the live plan."
    next_step = "Add one expiry regression check."
    settings = _settings(tmp_path / "data")
    app = create_app(settings)
    _seed_provider(app)

    with TestClient(app) as client:
        runtime = app.state.runtime
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Live plan lab"},
        )
        assert started.status_code == 200
        session_id = started.json()["session_id"]
        cards_before = _card_ids(runtime, workspace_id)

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Ship token refresh auth"],
            },
        )
        assert generated.status_code == 200, generated.text
        body = generated.json()
        plan = body.get("plan") or body
        plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
        step_before = str(plan.get("current_step") or "").strip()
        stage_before = str(plan.get("current_stage_id") or "").strip()
        assert plan_id
        assert step_before
        live_runtime = _runtime((body.get("memory") or {}).get("workspace") or {})
        assert str(live_runtime.get("plan_id") or "").strip() == plan_id
        assert str(live_runtime.get("current_step") or "").strip() == step_before

        runtime.evaluator_service.evaluate_snippet = MagicMock(
            return_value=_passed_report(summary, next_step)
        )
        evaluate = client.post(
            "/evaluate/snippet",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "language_id": "python",
                "content": (
                    "def require_fresh(token):\n"
                    "    if not token:\n"
                    "        raise ValueError('expired')\n"
                ),
            },
        )
        assert evaluate.status_code == 200, evaluate.text
        assert evaluate.json().get("passed") is True

        latest = runtime.repository.get_latest_plan(workspace_id)
        assert latest is not None
        assert latest.id == plan_id
        assert latest.current_step != step_before
        assert latest.current_stage_id != stage_before or latest.current_step == next_step

        memory = client.get(f"/memory/summary?workspace_id={workspace_id}").json()["memory"]
        workspace = memory.get("workspace") or {}
        after_runtime = _runtime(workspace)
        assert str(after_runtime.get("plan_id") or "").strip() == plan_id
        assert str(after_runtime.get("current_step") or "").strip() == str(
            latest.current_step or ""
        ).strip()
        assert leftover_formal_plan_is_live_for_fill(
            plan=latest,
            runtime=after_runtime,
            existing=after_runtime,
        )

        outcomes = memory.get("learning_outcomes") or []
        assert any(
            summary in str(item.get("verified_result") or item.get("summary") or "")
            or str(item.get("verified_by_evaluator") or item.get("verifiedByEvaluator") or "")
            in {"True", "true", "1"}
            for item in outcomes
        ), outcomes

        session = runtime.ensure_session(session_id, workspace_id=workspace_id)
        advance = (session.snapshot.plan_runtime_status or {}).get("verify_plan_advance") or {}
        assert advance.get("advanced") is True
        assert str(advance.get("plan_id") or "").strip() == plan_id
        assert str(advance.get("what") or "").strip()
        assert str(advance.get("why") or "").strip()
        assert str(advance.get("next") or "").strip()

        # Stamp must survive hydrate rebuild on memory/summary.
        summary = client.get(f"/memory/summary?workspace_id={workspace_id}").json()
        summary_advance = (summary.get("plan_runtime_status") or {}).get("verify_plan_advance") or {}
        assert summary_advance.get("advanced") is True
        assert str(summary_advance.get("plan_id") or "").strip() == plan_id
        assert str(summary_advance.get("what") or "").strip()
        assert str(summary_advance.get("next") or "").strip()

        assert _card_ids(runtime, workspace_id) == cards_before
        assert not str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        assert runtime.memory_service.global_memory().capability_profile == {}

        # Second verify must still be able to advance (no identity desync theater).
        stage_mid = latest.current_stage_id
        runtime.evaluator_service.evaluate_snippet = MagicMock(
            return_value=_passed_report(
                "Second evaluator ack on the same live plan.",
                "Preserve the verified expiry guard.",
            )
        )
        second = client.post(
            "/evaluate/snippet",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "language_id": "python",
                "content": "def ok():\n    return True\n",
            },
        )
        assert second.status_code == 200, second.text
        latest2 = runtime.repository.get_latest_plan(workspace_id)
        assert latest2 is not None
        assert latest2.id == plan_id
        after2 = _runtime(
            (client.get(f"/memory/summary?workspace_id={workspace_id}").json()["memory"].get("workspace") or {})
        )
        assert str(after2.get("plan_id") or "").strip() == plan_id
        assert str(after2.get("current_step") or "").strip() == str(latest2.current_step or "").strip()
        assert leftover_formal_plan_is_live_for_fill(
            plan=latest2,
            runtime=after2,
            existing=after2,
        )
        assert (
            latest2.current_stage_id != stage_mid
            or latest2.current_step != latest.current_step
        )
        assert runtime.memory_service.global_memory().capability_profile == {}
        assert _card_ids(runtime, workspace_id) == cards_before
