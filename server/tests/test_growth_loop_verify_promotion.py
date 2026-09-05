"""Focused growth loop: evaluator verify → project evidence; global needs two workspaces."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.core.models import EvaluationCheck, EvaluationReport
from app.core.settings import AppSettings
from app.main import create_app


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer growth verify promotion",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-growth-verify.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _passed_report(summary: str) -> EvaluationReport:
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
        next_step="Keep practicing in this project.",
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


def test_evaluate_ack_updates_project_blocks_global_until_second_workspace(
    tmp_path: Path,
) -> None:
    workspace_a = "ws-growth-verify-a"
    workspace_b = "ws-growth-verify-b"
    concept = "auth expiry"
    summary_a = "Evaluator confirmed fail-closed expiry in project A."
    summary_b = "Evaluator confirmed the same expiry decision in project B."
    settings = _settings(tmp_path / "data")
    app = create_app(settings)

    with TestClient(app) as client:
        runtime = app.state.runtime
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_a, "workspace_name": "Verify A"},
        )
        assert started.status_code == 200
        session_a = started.json()["session_id"]
        cards_before = _card_ids(runtime, workspace_a)
        assert runtime.memory_service.repository.get_latest_plan(workspace_a) is None

        # Empty verified_result is not a scene.
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_a,
            concepts=[concept],
            outcome="tests_passed",
            summary="empty-result probe",
            verified_result="",
            verified_by_evaluator=True,
            scenario="review_reflection",
        )
        empty_ws = runtime.memory_service.snapshot(workspace_a).workspace or {}
        assert not (empty_ws.get("verified_skill_scenes") or [])
        assert (empty_ws.get("latest_transfer_state") or {}).get("state") != "transferable"
        assert runtime.memory_service.global_memory().capability_profile == {}

        runtime.evaluator_service.evaluate_snippet = MagicMock(
            return_value=_passed_report(summary_a)
        )
        evaluate = client.post(
            "/evaluate/snippet",
            json={
                "session_id": session_a,
                "workspace_id": workspace_a,
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

        memory_a = client.get(f"/memory/summary?workspace_id={workspace_a}").json()["memory"]
        outcomes = memory_a.get("learning_outcomes") or []
        assert any(
            summary_a in str(item.get("verified_result") or item.get("summary") or "")
            for item in outcomes
        ), outcomes
        assert runtime.memory_service.global_memory().capability_profile == {}
        assert runtime.memory_service.repository.get_latest_plan(workspace_a) is None
        assert _card_ids(runtime, workspace_a) == cards_before

        # Evaluator-acked project scene + same-workspace extra scene keys stay non-global.
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_a,
            concepts=[concept],
            outcome="tests_passed",
            summary=summary_a,
            verified_result=summary_a,
            verified_by_evaluator=True,
            scenario="review_reflection",
        )
        transfer_a = (
            runtime.memory_service.snapshot(workspace_a).workspace or {}
        ).get("latest_transfer_state") or {}
        assert transfer_a.get("state") == "awaiting_second_scene"
        assert transfer_a.get("state") != "transferable"
        assert runtime.memory_service.global_memory().capability_profile == {}

        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_a,
            concepts=[concept],
            outcome="tests_passed",
            summary="Second task same project.",
            verified_result="Second task same project.",
            verified_by_evaluator=True,
            transfer_source_context="billing route",
            transfer_target_context="docs sandbox",
            transfer_evidence_summary="Applied the same guard in a second task.",
            scenario="review_reflection",
        )
        assert runtime.memory_service.global_memory().capability_profile == {}
        transfer_repeat = (
            runtime.memory_service.snapshot(workspace_a).workspace or {}
        ).get("latest_transfer_state") or {}
        assert transfer_repeat.get("state") != "transferable"

        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Verify B"},
        )
        assert started_b.status_code == 200
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_b,
            concepts=[concept],
            outcome="tests_passed",
            summary=summary_b,
            verified_result=summary_b,
            verified_by_evaluator=True,
            scenario="review_reflection",
        )
        profile = runtime.memory_service.global_memory().capability_profile
        assert any(concept.casefold() == key.casefold() for key in profile)
        transfer_b = (
            runtime.memory_service.snapshot(workspace_b).workspace or {}
        ).get("latest_transfer_state") or {}
        assert transfer_b.get("state") == "transferable"
        assert runtime.memory_service.repository.get_latest_plan(workspace_b) is None
        assert runtime.memory_service.repository.get_latest_plan(workspace_a) is None
