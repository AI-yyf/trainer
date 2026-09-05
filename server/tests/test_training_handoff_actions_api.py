"""API coverage for the explicit Reflect and Return training transitions."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import TrainingCardCandidateSnapshot
from app.core.settings import AppSettings
from app.main import create_app


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer handoff action test",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer.db",
        default_session_stage="intake",
        summary_message_limit=6,
    )


def _seed_verified_handoff(app, workspace_id: str) -> tuple[TrainingCardCandidateSnapshot, str]:
    card = TrainingCardCandidateSnapshot(
        card_id="reflect-return-card",
        card_type="practice",
        title="Verify one parser boundary",
        status="active",
        focus_area="parser boundary",
        target_skill="guard parsing before tokenization",
        validation_method="Run the focused parser test.",
    )
    app.state.runtime.memory_service.upsert_card(workspace_id, card)
    workspace = app.state.runtime.memory_service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary="pytest tests/test_parser.py -k boundary: 1 passed",
        next_step="Record what the focused check proved.",
        focus_area=card.focus_area,
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )
    return card, workspace["latest_training_handoff"]["handoff_id"]


def test_reflect_then_return_persists_truthful_completion_across_restart(tmp_path: Path) -> None:
    workspace_id = "reflect-return-workspace"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        session = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Reflect Return"},
        )
        assert session.status_code == 200
        card, handoff_id = _seed_verified_handoff(app, workspace_id)

        premature_return = client.post(
            "/training/return",
            json={"workspace_id": workspace_id, "card_id": card.card_id, "handoff_id": handoff_id},
        )
        assert premature_return.status_code == 422
        assert (
            app.state.runtime.memory_service.get_card(workspace_id, card.card_id).status == "active"
        )
        premature_workspace = app.state.runtime.memory_service.snapshot(workspace_id).workspace
        assert premature_workspace["selected_card_id"] == card.card_id
        assert premature_workspace.get("latest_plan_runtime") is None

        reflected = client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace_id,
                "card_id": card.card_id,
                "handoff_id": handoff_id,
                "reflection": "The focused test proved the guard must run before token parsing.",
            },
        )
        assert reflected.status_code == 200
        reflected_workspace = reflected.json()["workspace"]
        assert reflected_workspace["latest_training_handoff"]["learning_phase"] == "reflect"
        assert reflected_workspace["latest_training_handoff"]["return_mode"] == "return_required"
        assert reflected_workspace["latest_training_next_hop"]["status"] == "return_required"
        session_id = session.json()["session_id"]
        assert (
            app.state.runtime.get_session(session_id).snapshot.memory.workspace[
                "latest_training_next_hop"
            ]["status"]
            == "return_required"
        )

    rebuilt_app = create_app(settings)
    with TestClient(rebuilt_app) as rebuilt_client:
        restored = rebuilt_client.get(f"/memory/summary?workspace_id={workspace_id}")
        assert restored.status_code == 200
        restored_workspace = restored.json()["memory"]["workspace"]
        assert restored_workspace["latest_training_handoff"]["learning_phase"] == "reflect"
        assert restored_workspace["latest_training_next_hop"]["status"] == "return_required"

        returned = rebuilt_client.post(
            "/training/return",
            json={"workspace_id": workspace_id, "card_id": card.card_id, "handoff_id": handoff_id},
        )
        assert returned.status_code == 200
        returned_workspace = returned.json()["workspace"]
        assert returned_workspace["latest_training_handoff"]["learning_phase"] == "return"
        assert returned_workspace["latest_training_handoff"]["status"] == "completed"
        assert returned_workspace["latest_training_handoff"]["return_mode"] == "result"
        assert returned_workspace["latest_training_next_hop"]["status"] == "continued_in_chat"
        assert returned_workspace["selected_card_status"] == "implemented"
        assert "1 passed" in returned_workspace["latest_learning_verified_result"]

        summary = rebuilt_client.get(f"/memory/summary?workspace_id={workspace_id}")
        evidence = summary.json()["memory"]["evidence_queue"]["pending"]
        assert len(evidence) == 1
        assert evidence[0]["verified"] is True
        assert evidence[0]["verification_source"] == "test_runner"
        assert evidence[0]["source_card_id"] == card.card_id

        repeated_return = rebuilt_client.post(
            "/training/return",
            json={"workspace_id": workspace_id, "card_id": card.card_id, "handoff_id": handoff_id},
        )
        assert repeated_return.status_code == 200
        repeated_summary = rebuilt_client.get(f"/memory/summary?workspace_id={workspace_id}")
        assert len(repeated_summary.json()["memory"]["evidence_queue"]["pending"]) == 1


def test_reflect_rejects_stale_handoff_and_untrusted_phase(tmp_path: Path) -> None:
    workspace_id = "reflect-stale-workspace"
    app = create_app(_settings(tmp_path / "trainer-data"))

    with TestClient(app) as client:
        card = TrainingCardCandidateSnapshot(
            card_id="untrusted-reflection-card",
            card_type="practice",
            title="Return a parser attempt",
            status="active",
            focus_area="parser boundary",
            target_skill="guard parsing before tokenization",
        )
        app.state.runtime.memory_service.upsert_card(workspace_id, card)
        workspace = app.state.runtime.memory_service.record_training_practice_evaluation_result(
            workspace_id=workspace_id,
            card_id=card.card_id,
            passed=True,
            summary="I think the parser guard is correct.",
            next_step="Run the focused test.",
            focus_area=card.focus_area,
            evidence_source="learner_return",
            verified_by_evaluator=False,
        )
        handoff_id = workspace["latest_training_handoff"]["handoff_id"]

        untrusted = client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace_id,
                "card_id": card.card_id,
                "handoff_id": handoff_id,
                "reflection": "This cannot count until a trusted verifier checks it.",
            },
        )
        assert untrusted.status_code == 422

        stale = client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace_id,
                "card_id": card.card_id,
                "handoff_id": "handoff-stale",
                "reflection": "This request must not mutate another handoff.",
            },
        )
        assert stale.status_code == 422


def test_return_adopt_advances_training_next_and_does_not_paint_workspace_b(tmp_path: Path) -> None:
    workspace_a = "workspace-a-loop"
    workspace_b = "workspace-b-loop"
    next_step = "Add a token expiry test"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        card = TrainingCardCandidateSnapshot(
            card_id="loop-card-a",
            card_type="practice",
            title="Keep one auth check",
            status="active",
            focus_area="session tokens",
            target_skill="auth expiry",
            next_after_completion=next_step,
        )
        app.state.runtime.memory_service.upsert_card(workspace_a, card)
        seeded = app.state.runtime.memory_service.record_training_practice_evaluation_result(
            workspace_id=workspace_a,
            card_id=card.card_id,
            passed=True,
            summary="Focused auth check passed.",
            next_step="Return the verified result.",
            focus_area=card.focus_area,
            evidence_source="ide_current_file",
            verified_by_evaluator=True,
        )
        handoff_id = seeded["latest_training_handoff"]["handoff_id"]
        reflect = client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace_a,
                "card_id": card.card_id,
                "handoff_id": handoff_id,
                "reflection": "The focused check proved expired tokens must fail closed.",
            },
        )
        assert reflect.status_code == 200
        returned = client.post(
            "/training/return",
            json={"workspace_id": workspace_a, "card_id": card.card_id, "handoff_id": handoff_id},
        )
        assert returned.status_code == 200
        summary_a = client.get(f"/memory/summary?workspace_id={workspace_a}")
        assert summary_a.status_code == 200
        body_a = summary_a.json()["memory"]
        pending = body_a["evidence_queue"]["pending"]
        assert len(pending) == 1
        persisted = app.state.runtime.memory_service.recover_workspace_facts(workspace_a)[
            "latest_plan_runtime"
        ]
        runtime = (
            (body_a.get("workspace") or {}).get("latest_plan_runtime")
            or (body_a.get("workspace") or {}).get("latestPlanRuntime")
            or {}
        )
        status = summary_a.json().get("plan_runtime_status") or {}
        assert persisted.get("resume_state") == "waiting"
        assert persisted.get("current_step") == "Keep one auth check"
        assert persisted.get("next_after_current") == next_step
        assert persisted.get("evidence_binding") == pending[0]["id"]
        assert (runtime.get("resumeState") or runtime.get("resume_state")) == "waiting"
        assert (runtime.get("currentStep") or runtime.get("current_step")) == "Keep one auth check"
        assert (runtime.get("nextAfterCurrent") or runtime.get("next_after_current")) == next_step
        assert (status.get("resumeState") or status.get("resume_state")) == "waiting"
        assert not body_a.get("global_memory", {}).get("capability_profile")

        adopt = client.post(
            "/evidence/adopt",
            json={"workspace_id": workspace_a, "evidence_id": pending[0]["id"]},
        )
        assert adopt.status_code == 200
        assert adopt.json()["plan_updated"] is False
        after_a = client.get(f"/memory/summary?workspace_id={workspace_a}").json()["memory"]
        advanced_persisted = app.state.runtime.memory_service.recover_workspace_facts(workspace_a)[
            "latest_plan_runtime"
        ]
        advanced = (
            (after_a.get("workspace") or {}).get("latest_plan_runtime")
            or (after_a.get("workspace") or {}).get("latestPlanRuntime")
            or {}
        )
        assert advanced_persisted.get("resume_state") == "in_progress"
        assert advanced_persisted.get("current_step") == next_step
        assert advanced_persisted.get("next_after_current") in {None, ""}
        assert advanced_persisted.get("evidence_binding") in {None, ""}
        assert (advanced.get("resumeState") or advanced.get("resume_state")) == "in_progress"
        assert (advanced.get("currentStep") or advanced.get("current_step")) == next_step
        next_hop = (after_a.get("workspace") or {}).get("latest_training_next_hop") or {}
        assert (next_hop.get("title") or next_hop.get("cardTitle") or next_hop.get("card_title")) == next_step
        transfer_a = (after_a.get("workspace") or {}).get("latest_transfer_state") or {}
        assert transfer_a.get("state") == "awaiting_second_scene"
        assert transfer_a.get("state") != "transferable"
        assert transfer_a.get("concept") == "auth expiry"
        assert not after_a.get("global_memory", {}).get("capability_profile")
        assert app.state.runtime.memory_service.global_memory().capability_profile == {}

        summary_b = client.get(f"/memory/summary?workspace_id={workspace_b}")
        assert summary_b.status_code == 200
        body_b = summary_b.json()["memory"]
        assert body_b["evidence_queue"]["pending"] == []
        foreign_runtime = (body_b.get("workspace") or {}).get("latest_plan_runtime") or {}
        assert (foreign_runtime.get("currentStep") or foreign_runtime.get("current_step")) not in {
            "Keep one auth check",
            next_step,
        }
        foreign_hop = (body_b.get("workspace") or {}).get("latest_training_next_hop") or {}
        assert (foreign_hop.get("title") or foreign_hop.get("card_title")) != next_step
        assert (body_b.get("workspace") or {}).get("selected_card_title") != "Keep one auth check"
        transfer = (body_b.get("workspace") or {}).get("latest_transfer_state") or {}
        assert transfer.get("state") != "transferable"
