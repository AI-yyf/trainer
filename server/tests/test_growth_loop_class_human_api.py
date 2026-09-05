"""Class-human growth loop over real routers: understand → verify → evidence → transfer."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

from fastapi.testclient import TestClient

from app.core.models import (
    ActiveCardSelectionResult,
    AffectState,
    LearningPlan,
    PlanStage,
    ProviderConfig,
    ResourceRecord,
    TrainingCardCandidateSnapshot,
    UserProfile,
)
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app
from app.memory.transfer_skills import describe_transfer_skill_state
from app.memory.workspace_recovery import leftover_formal_plan_is_live_for_fill
from tests.test_api import build_client
from tests.test_plan_formal_mutation import configure_tool_capable_provider
from tests.test_router_stream_scenarios import completed_stream_response, streamed_status_phases


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer class-human loop test",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer.db",
        default_session_stage="intake",
        summary_message_limit=6,
    )


def _runtime_field(record: dict[str, object] | None, *names: str) -> object:
    payload = record or {}
    for name in names:
        value = payload.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def test_class_human_understand_verify_evidence_transfer_does_not_paint_b(tmp_path: Path) -> None:
    workspace_a = "workspace-a-class-human"
    workspace_b = "workspace-b-class-human"
    next_step = "Add a token expiry test"
    project_a = tmp_path / "auth-expiry-lab"
    project_a.mkdir()
    (project_a / "auth.py").write_text(
        "def require_fresh_token(token):\n    if not token:\n        raise ValueError('expired')\n    return token\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_a,
                "workspace_name": "Auth expiry lab",
                "workspace_path": str(project_a),
            },
        )
        assert started.status_code == 200
        started_body = started.json()
        started_memory = started_body.get("memory") or {}
        understanding = (
            started_memory.get("workspace_understanding")
            or started_memory.get("workspaceUnderstanding")
            or {}
        )
        first_look = understanding.get("firstLookSummary") or understanding.get("first_look_summary") or {}
        assert first_look
        first_look_next = str(
            first_look.get("recommendedNextStep") or first_look.get("recommended_next_step") or ""
        ).strip()
        assert first_look_next
        assert started_body.get("plan") in (None, {})
        assert not (started_body.get("currentTask") or started_body.get("current_task") or {}).get("title")
        from app.pedagogy.plan_orientation import derive_plan_orientation

        first_look_why = str(
            first_look.get("whyThisGuess") or first_look.get("why_this_guess") or ""
        ).strip()
        plan_orientation = derive_plan_orientation(
            has_formal_plan=False,
            first_look_recommended_next=first_look_next,
            first_look_why=first_look_why,
            language="en-US",
        )
        assert plan_orientation.get("primary_action") != "generate_plan"
        assert plan_orientation.get("primary_action") == "continue_without_plan"
        assert plan_orientation.get("next_step") == first_look_next
        session_id = started_body.get("session_id") or started_body.get("sessionId")
        assert session_id
        ready_provider = ProviderConfig(
            name="ready-provider",
            baseUrl="http://example.test/v1",
            apiKeyRef="ready-ref",
            model="ready-model",
        )
        state_a = app.state.runtime.get_session(str(session_id))
        assert state_a is not None
        state_a.snapshot.provider = ready_provider
        state_a.snapshot.sidecar_status = "ready"
        ready_a = client.get(
            f"/memory/summary?workspace_id={workspace_a}&session_id={session_id}"
        )
        assert ready_a.status_code == 200
        orientation_a = ready_a.json().get("coach_orientation") or ready_a.json().get("coachOrientation") or {}
        assert (orientation_a.get("next_step") or orientation_a.get("nextStep")) == first_look_next
        assert (orientation_a.get("object_kind") or orientation_a.get("objectKind")) == "conversation"
        assert (orientation_a.get("primary_action") or orientation_a.get("primaryAction")) == "compose"
        assert (orientation_a.get("object_kind") or orientation_a.get("objectKind")) != "provider"
        assert "Save and test a provider" not in str(orientation_a.get("next_step") or orientation_a.get("nextStep") or "")
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_a) is None

        card = TrainingCardCandidateSnapshot(
            card_id="class-human-card-a",
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
        assert pending[0]["source"] == "training_handoff_return"
        assert pending[0]["verified"] is True
        persisted = app.state.runtime.memory_service.recover_workspace_facts(workspace_a)[
            "latest_plan_runtime"
        ]
        assert persisted.get("resume_state") == "waiting"
        assert persisted.get("current_step") == "Keep one auth check"
        assert persisted.get("next_after_current") == next_step
        assert persisted.get("evidence_binding") == pending[0]["id"]
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_a) is None

        adopt = client.post(
            "/evidence/adopt",
            json={"workspace_id": workspace_a, "evidence_id": pending[0]["id"]},
        )
        assert adopt.status_code == 200
        assert adopt.json()["plan_updated"] is False

        after_a = client.get(f"/memory/summary?workspace_id={workspace_a}").json()["memory"]
        advanced = app.state.runtime.memory_service.recover_workspace_facts(workspace_a)[
            "latest_plan_runtime"
        ]
        assert advanced.get("resume_state") == "in_progress"
        assert advanced.get("current_step") == next_step
        next_hop = (after_a.get("workspace") or {}).get("latest_training_next_hop") or {}
        assert _runtime_field(next_hop, "title", "cardTitle", "card_title") == next_step
        transfer_a = (after_a.get("workspace") or {}).get("latest_transfer_state") or {}
        assert transfer_a.get("state") == "awaiting_second_scene"
        assert transfer_a.get("state") != "transferable"
        assert transfer_a.get("concept") == "auth expiry"
        assert workspace_a in (transfer_a.get("workspace_ids") or transfer_a.get("workspaceIds") or [])
        assert not after_a.get("global_memory", {}).get("capability_profile")
        assert app.state.runtime.memory_service.global_memory().capability_profile == {}
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_a) is None

        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        session_b = started_b.json().get("session_id") or started_b.json().get("sessionId")
        assert session_b
        state_b = app.state.runtime.get_session(str(session_b))
        assert state_b is not None
        state_b.snapshot.provider = ready_provider
        state_b.snapshot.sidecar_status = "ready"
        summary_b = client.get(
            f"/memory/summary?workspace_id={workspace_b}&session_id={session_b}"
        )
        assert summary_b.status_code == 200
        body_b = summary_b.json()["memory"]
        assert body_b["evidence_queue"]["pending"] == []
        foreign_runtime = (body_b.get("workspace") or {}).get("latest_plan_runtime") or {}
        assert _runtime_field(foreign_runtime, "currentStep", "current_step") not in {
            "Keep one auth check",
            next_step,
        }
        foreign_hop = (body_b.get("workspace") or {}).get("latest_training_next_hop") or {}
        assert _runtime_field(foreign_hop, "title", "card_title", "cardTitle") != next_step
        assert (body_b.get("workspace") or {}).get("selected_card_title") != "Keep one auth check"
        transfer_b = (body_b.get("workspace") or {}).get("latest_transfer_state") or {}
        assert transfer_b.get("state") != "transferable"
        assert transfer_b.get("concept") != "auth expiry"
        understanding_b = body_b.get("workspace_understanding") or body_b.get("workspaceUnderstanding") or {}
        first_look_b = (
            understanding_b.get("firstLookSummary") or understanding_b.get("first_look_summary") or {}
        )
        assert "auth-expiry-lab" not in str(first_look_b)
        assert "auth expiry" not in str(understanding_b).lower()
        assert not body_b.get("global_memory", {}).get("capability_profile")
        assert started_b.json().get("plan") in (None, {})
        orientation_b = summary_b.json().get("coach_orientation") or summary_b.json().get("coachOrientation") or {}
        assert (orientation_b.get("next_step") or orientation_b.get("nextStep")) != first_look_next
        assert "auth-expiry-lab" not in str(orientation_b)
        assert "auth expiry" not in str(orientation_b).lower()
        assert (orientation_b.get("object_kind") or orientation_b.get("objectKind")) != "plan"
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None


def test_class_human_training_return_adopt_leftover_plan_does_not_paint_b(
    tmp_path: Path,
) -> None:
    """Leftover plan stays stored on A; summary does not paint it live; B stays unpainted.

    Recovered runtime without matching plan_id means leftover is not live snapshot.plan.
    plan_runtime_status may hint recovered step text only — never resurrect formal leftover.
    """
    workspace_a = "workspace-a-leftover-return"
    workspace_b = "workspace-b-leftover-return"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    next_step = "Add a token expiry test"
    project_a = tmp_path / "auth-expiry-lab"
    project_a.mkdir()
    (project_a / "auth.py").write_text(
        "def require_fresh_token(token):\n    if not token:\n        raise ValueError('expired')\n    return token\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_a,
                "workspace_name": "Auth expiry lab",
                "workspace_path": str(project_a),
            },
        )
        assert started.status_code == 200
        leftover = LearningPlan(
            id="plan-formal-old",
            title=leftover_title,
            current_step=leftover_step,
            why_now="Keep the leftover why",
            next_after_current="Then review the leftover path",
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Auth",
                    goal="Keep one check",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        app.state.runtime.memory_service.repository.save_plan(workspace_a, leftover)
        card = TrainingCardCandidateSnapshot(
            card_id="class-human-leftover-card-a",
            card_type="practice",
            title=leftover_step,
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
        stored_after_return = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
        assert stored_after_return is not None
        assert stored_after_return.id == leftover.id
        assert stored_after_return.current_step == leftover_step
        summary_a = client.get(f"/memory/summary?workspace_id={workspace_a}")
        assert summary_a.status_code == 200
        body = summary_a.json()
        snapshot_plan = body.get("plan") or {}
        # Fail-closed: stored leftover must not resurrect as live snapshot.plan.
        assert body.get("plan") in (None, {})
        assert not (snapshot_plan.get("id") or snapshot_plan.get("plan_id"))
        assert leftover.id not in str(snapshot_plan)
        assert leftover_title not in str(snapshot_plan.get("title") or "")
        assert not (body.get("current_task") or body.get("currentTask") or {}).get("title")
        pending = (body.get("memory") or {}).get("evidence_queue", {}).get("pending") or []
        assert len(pending) == 1
        assert pending[0]["source"] == "training_handoff_return"
        runtime = app.state.runtime.memory_service.recover_workspace_facts(workspace_a)[
            "latest_plan_runtime"
        ]
        assert runtime.get("resume_state") == "waiting"
        assert runtime.get("current_step") == leftover_step
        assert runtime.get("next_after_current") == next_step
        assert runtime.get("plan_id") in {None, ""}
        assert not leftover_formal_plan_is_live_for_fill(
            plan=leftover,
            runtime=runtime,
            existing=runtime,
        )
        status = body.get("plan_runtime_status") or body.get("planRuntimeStatus") or {}
        # Hint-only recovered step; empty plan_id keeps chips from claiming live formal plan.
        assert (status.get("current_step") or status.get("currentStep")) == leftover_step
        assert (status.get("plan_id") or status.get("planId") or "") in {"", None}
        actions = [
            str(item.get("action") or "")
            for item in (body.get("suggested_actions") or body.get("suggestedActions") or [])
        ]
        assert "plan" not in actions
        assert "next_task" not in actions
        assert "task" not in actions
        orientation = body.get("coach_orientation") or body.get("coachOrientation") or {}
        object_label = str(orientation.get("object_label") or orientation.get("objectLabel") or "")
        assert leftover_title not in object_label
        adopt = client.post(
            "/evidence/adopt",
            json={"workspace_id": workspace_a, "evidence_id": pending[0]["id"]},
        )
        assert adopt.status_code == 200
        assert adopt.json()["plan_updated"] is False
        stored_after_adopt = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
        assert stored_after_adopt is not None
        assert stored_after_adopt.id == leftover.id
        assert stored_after_adopt.current_step == leftover_step
        assert stored_after_adopt.stages[0].status == "active"
        advanced = app.state.runtime.memory_service.recover_workspace_facts(workspace_a)[
            "latest_plan_runtime"
        ]
        assert advanced.get("resume_state") == "in_progress"
        assert advanced.get("current_step") == next_step
        assert advanced.get("plan_id") in {None, ""}
        assert not leftover_formal_plan_is_live_for_fill(
            plan=leftover,
            runtime=advanced,
            existing=advanced,
        )
        after_a = client.get(f"/memory/summary?workspace_id={workspace_a}").json()
        assert after_a.get("plan") in (None, {})
        assert not (after_a.get("current_task") or after_a.get("currentTask") or {}).get("title")
        transfer_a = ((after_a.get("memory") or {}).get("workspace") or {}).get(
            "latest_transfer_state"
        ) or {}
        assert transfer_a.get("state") == "awaiting_second_scene"
        assert transfer_a.get("state") != "transferable"
        assert not (after_a.get("memory") or {}).get("global_memory", {}).get("capability_profile")
        assert app.state.runtime.memory_service.global_memory().capability_profile == {}
        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        summary_b = client.get(f"/memory/summary?workspace_id={workspace_b}")
        assert summary_b.status_code == 200
        body_b = summary_b.json()
        memory_b = body_b.get("memory") or {}
        assert (memory_b.get("evidence_queue") or {}).get("pending") == []
        foreign_runtime = (memory_b.get("workspace") or {}).get("latest_plan_runtime") or {}
        assert _runtime_field(foreign_runtime, "currentStep", "current_step") not in {
            leftover_step,
            leftover_title,
            next_step,
        }
        foreign_plan = body_b.get("plan") or {}
        assert body_b.get("plan") in (None, {})
        assert foreign_plan.get("id") not in {leftover.id, leftover.id}
        assert (foreign_plan.get("title") or "") != leftover_title
        assert leftover_step not in str(foreign_plan)
        assert leftover_title not in str(body_b.get("coach_orientation") or {})
        assert leftover_step not in str(body_b.get("plan_runtime_status") or {})
        assert not (body_b.get("current_task") or body_b.get("currentTask") or {}).get("title")
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None


def _seed_leftover_independent_runtime(
    *,
    app,
    client: TestClient,
    tmp_path: Path,
    workspace_a: str,
    leftover_title: str,
    leftover_step: str,
    next_step: str,
    leftover_frozen: bool = False,
) -> tuple[LearningPlan, str]:
    project_a = tmp_path / "auth-expiry-lab"
    project_a.mkdir(exist_ok=True)
    (project_a / "auth.py").write_text(
        "def require_fresh_token(token):\n    if not token:\n        raise ValueError('expired')\n    return token\n",
        encoding="utf-8",
    )
    started = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_a,
            "workspace_name": "Auth expiry lab",
            "workspace_path": str(project_a),
        },
    )
    assert started.status_code == 200
    session_id = str(started.json().get("session_id") or started.json().get("sessionId") or "")
    leftover = LearningPlan(
        id="plan-formal-old",
        title=leftover_title,
        current_step=leftover_step,
        why_now="Keep the leftover why",
        next_after_current="Then review the leftover path",
        frozen=leftover_frozen,
        stages=[
            PlanStage(
                id="stage-1",
                title="Auth",
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    app.state.runtime.memory_service.repository.save_plan(workspace_a, leftover)
    card = TrainingCardCandidateSnapshot(
        card_id="class-human-leftover-card-a",
        card_type="practice",
        title=leftover_step,
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
    pending = (summary_a.json().get("memory") or {}).get("evidence_queue", {}).get("pending") or []
    assert len(pending) == 1
    adopt = client.post(
        "/evidence/adopt",
        json={"workspace_id": workspace_a, "evidence_id": pending[0]["id"]},
    )
    assert adopt.status_code == 200
    assert adopt.json()["plan_updated"] is False
    advanced = app.state.runtime.memory_service.recover_workspace_facts(workspace_a)[
        "latest_plan_runtime"
    ]
    assert advanced.get("resume_state") == "in_progress"
    assert advanced.get("plan_id") in {None, ""}
    return leftover, session_id


def _verified_return_adopt(
    *,
    app,
    client: TestClient,
    workspace_id: str,
    card_id: str,
    title: str,
    target_skill: str,
    focus_area: str,
    next_step: str,
    summary: str,
    reflection: str,
) -> dict[str, object]:
    card = TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type="practice",
        title=title,
        status="active",
        focus_area=focus_area,
        target_skill=target_skill,
        next_after_completion=next_step,
    )
    app.state.runtime.memory_service.upsert_card(workspace_id, card)
    # Mirror what /training/generate-card does: the card must be live-selected
    # before reflect/return, otherwise the leftover identity gate fail-closes.
    app.state.runtime.memory_service.persist_active_card_selection(
        workspace_id,
        ActiveCardSelectionResult(
            selected_card=card,
            selected_card_id=card.card_id,
            selection_score=80.0,
            why_this_card="Test-seeded verified card.",
            fallback_action="Return to coach with blocker details.",
            next_after_completion=next_step,
            candidate_count=1,
            eligible_count=1,
        ),
    )
    seeded = app.state.runtime.memory_service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=card.card_id,
        passed=True,
        summary=summary,
        next_step="Return the verified result.",
        focus_area=card.focus_area,
        evidence_source="ide_current_file",
        verified_by_evaluator=True,
    )
    handoff_id = seeded["latest_training_handoff"]["handoff_id"]
    reflect = client.post(
        "/training/reflect",
        json={
            "workspace_id": workspace_id,
            "card_id": card.card_id,
            "handoff_id": handoff_id,
            "reflection": reflection,
        },
    )
    assert reflect.status_code == 200
    returned = client.post(
        "/training/return",
        json={"workspace_id": workspace_id, "card_id": card.card_id, "handoff_id": handoff_id},
    )
    assert returned.status_code == 200
    pending = (
        client.get(f"/memory/summary?workspace_id={workspace_id}").json().get("memory") or {}
    ).get("evidence_queue", {}).get("pending") or []
    assert pending
    adopt = client.post(
        "/evidence/adopt",
        json={"workspace_id": workspace_id, "evidence_id": pending[0]["id"]},
    )
    assert adopt.status_code == 200
    assert adopt.json()["plan_updated"] is False
    return client.get(f"/memory/summary?workspace_id={workspace_id}").json()


def test_class_human_explicit_plan_generate_after_independent_runtime_binds_new_plan(
    tmp_path: Path,
) -> None:
    workspace_a = "workspace-a-leftover-generate"
    workspace_b = "workspace-b-leftover-generate"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    next_step = "Add a token expiry test"
    generate_goal = "Build a token-refresh learning path"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover, session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
        )
        _seed_runtime_provider(app)
        cards_before = [
            card.card_id for card in app.state.runtime.memory_service.get_cards(workspace_a)
        ]
        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_a,
                "objectives": [generate_goal],
            },
        )
        assert generated.status_code == 200, generated.text
        reliability = generated.json().get("reliability") or {}
        assert reliability.get("phase") == "acked"
        assert reliability.get("outcome") == "success"
        generated_plan = generated.json().get("plan") or generated.json()
        generated_id = str(generated_plan.get("id") or generated_plan.get("plan_id") or "")
        generated_title = str(generated_plan.get("title") or "")
        generated_step = str(generated_plan.get("current_step") or generated_plan.get("currentStep") or "")
        assert generated_id
        assert generated_id != leftover.id
        assert leftover_title not in generated_title
        assert leftover_step not in generated_title
        assert generated_step != leftover_step
        stored_leftover = app.state.runtime.memory_service.repository.get_plan_by_id(leftover.id)
        assert stored_leftover is not None
        leftover_workspace, leftover_record = stored_leftover
        assert leftover_workspace == workspace_a
        assert leftover_record.id == leftover.id
        assert leftover_record.title == leftover_title
        assert leftover_record.current_step == leftover_step
        latest = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
        assert latest is not None
        assert latest.id == generated_id
        bound = app.state.runtime.memory_service.recover_workspace_facts(workspace_a)[
            "latest_plan_runtime"
        ]
        assert bound.get("plan_id") == generated_id
        assert bound.get("current_step") == generated_step
        assert leftover_title not in str(bound.get("current_step") or "")
        assert leftover_step not in str(bound.get("why_now") or "")
        summary_a = client.get(f"/memory/summary?workspace_id={workspace_a}")
        assert summary_a.status_code == 200
        body_a = summary_a.json()
        snapshot_plan = body_a.get("plan") or {}
        assert (snapshot_plan.get("id") or snapshot_plan.get("plan_id")) == generated_id
        assert leftover_title not in str(snapshot_plan.get("title") or "")
        assert not (body_a.get("current_task") or body_a.get("currentTask") or {}).get("title")
        cards_after = [
            card.card_id for card in app.state.runtime.memory_service.get_cards(workspace_a)
        ]
        assert cards_after == cards_before
        action_blob = str(body_a.get("suggested_actions") or body_a.get("suggestedActions") or [])
        assert leftover_title not in action_blob
        assert leftover_step not in action_blob
        orientation = body_a.get("coach_orientation") or body_a.get("coachOrientation") or {}
        object_label = str(orientation.get("object_label") or orientation.get("objectLabel") or "")
        assert leftover_title not in object_label
        transfer_a = ((body_a.get("memory") or {}).get("workspace") or {}).get(
            "latest_transfer_state"
        ) or {}
        assert transfer_a.get("state") == "awaiting_second_scene"
        assert transfer_a.get("state") != "transferable"
        assert not (body_a.get("memory") or {}).get("global_memory", {}).get("capability_profile")
        assert app.state.runtime.memory_service.global_memory().capability_profile == {}
        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        summary_b = client.get(f"/memory/summary?workspace_id={workspace_b}")
        assert summary_b.status_code == 200
        body_b = summary_b.json()
        memory_b = body_b.get("memory") or {}
        foreign_runtime = (memory_b.get("workspace") or {}).get("latest_plan_runtime") or {}
        assert _runtime_field(foreign_runtime, "currentStep", "current_step") not in {
            leftover_step,
            leftover_title,
            next_step,
            generated_step,
        }
        foreign_plan = body_b.get("plan") or {}
        assert foreign_plan.get("id") not in {leftover.id, generated_id}
        assert leftover_title not in str(foreign_plan)
        assert leftover_step not in str(foreign_plan)
        assert generated_title not in str(foreign_plan)
        assert leftover_title not in str(body_b.get("coach_orientation") or {})
        assert leftover_step not in str(body_b.get("plan_runtime_status") or {})
        assert generated_step not in str(body_b.get("plan_runtime_status") or {})
        assert not (body_b.get("current_task") or body_b.get("currentTask") or {}).get("title")
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None


def test_class_human_non_session_plan_generate_after_leftover_binds_plan_id_under_high_urgency(
    tmp_path: Path,
) -> None:
    """Non-session /plan/generate must copy bound plan_id onto plan_runtime_status."""
    workspace_a = "workspace-a-leftover-generate-nonsession"
    workspace_b = "workspace-b-leftover-generate-nonsession"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    next_step = "Add a token expiry test"
    generate_goal = "Build a token-refresh learning path"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover, _session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
        )
        _seed_runtime_provider(app)
        app.state.runtime.memory_service.persist_turn_context_pressure(
            workspace_a,
            affect_state=AffectState(urgency_level="high", frustration_level=0.9),
        )
        generated = client.post(
            "/plan/generate",
            json={
                "workspace_id": workspace_a,
                "profile": UserProfile(long_term_goal=generate_goal).model_dump(mode="json"),
                "goals": [generate_goal],
            },
        )
        assert generated.status_code == 200, generated.text
        body = generated.json()
        plan = body.get("plan") or body
        plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
        generated_step = str(plan.get("current_step") or plan.get("currentStep") or "")
        generated_title = str(plan.get("title") or "")
        assert plan_id
        assert plan_id != leftover.id
        assert generated_step != leftover_step
        status = body.get("plan_runtime_status") or body.get("planRuntimeStatus") or {}
        workspace = (body.get("memory") or {}).get("workspace") or {}
        live_runtime = workspace.get("latest_plan_runtime") or workspace.get("latestPlanRuntime") or {}
        assert str(live_runtime.get("plan_id") or live_runtime.get("planId") or "").strip() == plan_id
        assert str(status.get("plan_id") or status.get("planId") or "").strip() == plan_id
        assert plan_id == str(plan.get("id") or plan.get("plan_id") or "").strip()
        assert leftover_step not in str(status.get("current_step") or status.get("currentStep") or "")
        assert leftover_title not in str(status)
        assert not leftover_formal_plan_is_live_for_fill(
            plan=leftover,
            runtime=live_runtime,
            existing=live_runtime,
        )
        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        summary_b = client.get(f"/memory/summary?workspace_id={workspace_b}")
        assert summary_b.status_code == 200
        _assert_workspace_b_unpainted_of_a(
            summary_b.json(),
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            generated_id=plan_id,
            generated_title=generated_title,
            generated_step=generated_step,
        )


def test_class_human_explicit_generate_after_leftover_does_not_paint_leftover_on_five_views(
    tmp_path: Path,
) -> None:
    workspace_a = "workspace-a-leftover-generate-five-views"
    workspace_b = "workspace-b-leftover-generate-five-views"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    leftover_why = "Keep the leftover why"
    next_step = "Add a token expiry test"
    generate_goal = "Build a token-refresh learning path"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover, session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
        )
        _seed_leftover_five_view_chrome(
            app,
            workspace_a,
            leftover_title,
            leftover_step,
        )
        _ready_session_provider(app, session_id)
        _seed_runtime_provider(app)
        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_a,
                "objectives": [generate_goal],
            },
        )
        assert generated.status_code == 200, generated.text
        generated_plan = generated.json().get("plan") or generated.json()
        generated_id = str(generated_plan.get("id") or generated_plan.get("plan_id") or "")
        generated_title = str(generated_plan.get("title") or "")
        generated_step = str(
            generated_plan.get("current_step") or generated_plan.get("currentStep") or ""
        )
        assert generated_id
        assert generated_id != leftover.id
        assert generated_step != leftover_step
        stored_leftover = app.state.runtime.memory_service.repository.get_plan_by_id(leftover.id)
        assert stored_leftover is not None
        leftover_workspace, leftover_record = stored_leftover
        assert leftover_workspace == workspace_a
        assert leftover_record.id == leftover.id
        assert leftover_record.title == leftover_title
        assert leftover_record.current_step == leftover_step
        _assert_five_views_new_live_plan_not_leftover(
            generated.json(),
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            leftover_why=leftover_why,
            generated_id=generated_id,
            generated_title=generated_title,
            generated_step=generated_step,
        )
        summary_a = client.get(f"/memory/summary?workspace_id={workspace_a}")
        assert summary_a.status_code == 200
        _assert_five_views_new_live_plan_not_leftover(
            summary_a.json(),
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            leftover_why=leftover_why,
            generated_id=generated_id,
            generated_title=generated_title,
            generated_step=generated_step,
        )
        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        summary_b = client.get(f"/memory/summary?workspace_id={workspace_b}")
        assert summary_b.status_code == 200
        _assert_workspace_b_unpainted_of_a(
            summary_b.json(),
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            generated_id=generated_id,
            generated_title=generated_title,
            generated_step=generated_step,
        )
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None


def test_class_human_explicit_plan_generate_failure_does_not_clobber_leftover(
    tmp_path: Path,
) -> None:
    workspace_a = "workspace-a-leftover-generate-fail"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    next_step = "Add a token expiry test"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover, session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
            leftover_frozen=True,
        )
        _seed_runtime_provider(app)
        cards_before = [
            card.card_id for card in app.state.runtime.memory_service.get_cards(workspace_a)
        ]
        with patch.object(
            app.state.runtime.planner_service,
            "generate_plan",
            side_effect=RuntimeError("planner unavailable"),
        ):
            failed = client.post(
                "/plan/generate",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_a,
                    "objectives": ["Build a token-refresh learning path"],
                },
            )
        assert failed.status_code == 500
        assert "unchanged" in str(failed.json().get("detail") or failed.text).lower()
        stored = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
        assert stored is not None
        assert stored.id == leftover.id
        assert stored.title == leftover_title
        assert stored.current_step == leftover_step
        assert stored.frozen is True
        runtime = app.state.runtime.memory_service.recover_workspace_facts(workspace_a)[
            "latest_plan_runtime"
        ]
        assert runtime.get("plan_id") in {None, ""}
        assert runtime.get("current_step") == next_step
        summary_a = client.get(f"/memory/summary?workspace_id={workspace_a}").json()
        assert not (summary_a.get("current_task") or summary_a.get("currentTask") or {}).get("title")
        cards_after = [
            card.card_id for card in app.state.runtime.memory_service.get_cards(workspace_a)
        ]
        assert cards_after == cards_before
        frozen_generate = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_a,
                "objectives": ["Build a token-refresh learning path"],
            },
        )
        assert frozen_generate.status_code == 200, frozen_generate.text
        generated_id = str(
            (frozen_generate.json().get("plan") or frozen_generate.json()).get("id")
            or (frozen_generate.json().get("plan") or frozen_generate.json()).get("plan_id")
            or ""
        )
        assert generated_id
        assert generated_id != leftover.id
        leftover_after = app.state.runtime.memory_service.repository.get_plan_by_id(leftover.id)
        assert leftover_after is not None
        assert leftover_after[1].frozen is True
        assert leftover_after[1].title == leftover_title


def test_class_human_understand_then_diagnose_then_review_does_not_invent_objects(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-class-human-diagnose"
    project = tmp_path / "auth-expiry-lab"
    project.mkdir()
    auth_path = project / "auth.py"
    auth_path.write_text(
        "def require_fresh_token(token):\n    if not token:\n        raise ValueError('expired')\n    return token\n",
        encoding="utf-8",
    )

    with build_client(tmp_path / "trainer-data") as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Auth expiry lab",
                "workspace_path": str(project),
            },
        )
        assert started.status_code == 200
        started_body = started.json()
        session_id = started_body.get("session_id") or started_body.get("sessionId")
        assert session_id
        assert started_body.get("plan") in (None, {})
        assert not (started_body.get("currentTask") or started_body.get("current_task") or {}).get("title")
        state = client.app.state.runtime.get_session(str(session_id))
        assert state is not None
        state.snapshot.provider = ProviderConfig(
            name="ready-provider",
            baseUrl="http://example.test/v1",
            apiKeyRef="ready-ref",
            model="ready-model",
        )
        state.snapshot.sidecar_status = "ready"

        diagnose = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Help me diagnose why auth.py fails before we generate a plan or a task.",
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert diagnose.status_code == 200, diagnose.text
        diagnose_body = diagnose.json()
        assert diagnose_body["coach_turn"]["scenario"] != "principle"
        diagnose_actions = [
            str(item.get("action") or "") for item in diagnose_body.get("suggested_actions") or []
        ]
        assert diagnose_actions
        assert "task" not in diagnose_actions
        assert "plan" not in diagnose_actions
        assert "next_task" not in diagnose_actions
        assert diagnose_body.get("plan") in (None, {})
        assert not (diagnose_body.get("current_task") or diagnose_body.get("currentTask") or {}).get(
            "title"
        )
        lowered_next = str(
            diagnose_body["coach_turn"].get("next_step") or diagnose_body["coach_turn"].get("nextStep") or ""
        ).lower()
        assert "generate a plan" not in lowered_next
        assert "training card" not in lowered_next
        assert client.app.state.runtime.memory_service.repository.get_latest_plan(workspace_id) is None

        review = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "review",
                "message": "Review this implementation and tell me the first thing to fix.",
                "response_language": "en-US",
                "answer_mode": "coach-first",
                "current_file": {
                    "path": str(auth_path),
                    "language_id": "python",
                    "content": auth_path.read_text(encoding="utf-8"),
                    "diagnostics": ["ValueError on empty token is not covered by a test."],
                },
            },
        )
        assert review.status_code == 200, review.text
        review_body = review.json()
        assert review_body["coach_turn"]["scenario"] == "review"
        review_actions = [
            str(item.get("action") or "") for item in review_body.get("suggested_actions") or []
        ]
        assert "plan" not in review_actions
        assert "next_task" not in review_actions
        assert review_body.get("plan") in (None, {})
        assert client.app.state.runtime.memory_service.repository.get_latest_plan(workspace_id) is None

        teach = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": (
                    "Explain the principle of fail-closed token checks. "
                    "Why must an empty token raise before we generate a task?"
                ),
                "response_language": "en-US",
                "answer_mode": "coach-first",
            },
        )
        assert teach.status_code == 200, teach.text
        teach_body = teach.json()
        assert teach_body["coach_turn"]["scenario"] == "principle"
        teach_actions = [
            str(item.get("action") or "") for item in teach_body.get("suggested_actions") or []
        ]
        assert teach_actions
        assert "task" not in teach_actions
        assert "plan" not in teach_actions
        assert "next_task" not in teach_actions
        assert teach_body.get("plan") in (None, {})
        assert not (teach_body.get("current_task") or teach_body.get("currentTask") or {}).get("title")

        auth_path.write_text(
            "def require_fresh_token(token):\n"
            "    if not token:\n"
            "        raise ValueError('expired')\n"
            "    return token\n"
            "\n"
            "def test_empty_token_is_rejected():\n"
            "    try:\n"
            "        require_fresh_token('')\n"
            "    except ValueError:\n"
            "        return True\n"
            "    raise AssertionError('empty token must fail closed')\n",
            encoding="utf-8",
        )
        verify = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "review",
                "message": "I added a fail-closed check. Review this and record the evidence.",
                "response_language": "en-US",
                "answer_mode": "coach-first",
                "current_file": {
                    "path": str(auth_path),
                    "language_id": "python",
                    "content": auth_path.read_text(encoding="utf-8"),
                    "diagnostics": [],
                },
            },
        )
        assert verify.status_code == 200, verify.text
        verify_body = verify.json()
        memory = (verify_body.get("snapshot") or {}).get("memory") or verify_body.get("memory") or {}
        if not memory:
            summary = client.get(f"/memory/summary?workspace_id={workspace_id}&session_id={session_id}")
            assert summary.status_code == 200
            memory = summary.json().get("memory") or {}
        outcomes = memory.get("learning_outcomes") or memory.get("learningOutcomes") or []
        assert outcomes
        latest = outcomes[0]
        assert str(latest.get("outcome") or "").strip()
        assert str(latest.get("concept") or latest.get("focus_area") or "").strip()
        workspace_memory = memory.get("workspace") if isinstance(memory.get("workspace"), dict) else {}
        assert workspace_memory.get("latest_evaluation_feedback") or workspace_memory.get(
            "latestEvaluationFeedback"
        ) or latest.get("outcome") in {"verification_pending", "evaluation", "code_landed", "tests_passed"}
        global_memory = memory.get("global_memory") or memory.get("globalMemory") or {}
        assert not global_memory.get("capability_profile")
        assert client.app.state.runtime.memory_service.global_memory().capability_profile == {}
        assert client.app.state.runtime.memory_service.repository.get_latest_plan(workspace_id) is None

        started_b = client.post(
            "/session/start",
            json={"workspace_id": "workspace-class-human-diagnose-b", "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        summary_b = client.get("/memory/summary?workspace_id=workspace-class-human-diagnose-b")
        assert summary_b.status_code == 200
        memory_b = summary_b.json().get("memory") or {}
        assert not (memory_b.get("learning_outcomes") or memory_b.get("learningOutcomes"))
        workspace_b = memory_b.get("workspace") if isinstance(memory_b.get("workspace"), dict) else {}
        feedback_b = str(
            workspace_b.get("latest_evaluation_feedback")
            or workspace_b.get("latestEvaluationFeedback")
            or ""
        )
        assert "auth" not in feedback_b.lower()
        assert client.app.state.runtime.memory_service.repository.get_latest_plan(
            "workspace-class-human-diagnose-b"
        ) is None


def test_class_human_second_workspace_promotes_global_without_painting_leftover(
    tmp_path: Path,
) -> None:
    workspace_a = "workspace-a-transfer-promote"
    workspace_b = "workspace-b-transfer-promote"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    next_step = "Add a token expiry test"
    target_skill = "auth expiry"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover, _session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
        )
        after_a = client.get(f"/memory/summary?workspace_id={workspace_a}").json()
        transfer_a = ((after_a.get("memory") or {}).get("workspace") or {}).get(
            "latest_transfer_state"
        ) or {}
        assert transfer_a.get("state") == "awaiting_second_scene"
        assert transfer_a.get("state") != "transferable"
        assert transfer_a.get("concept") == target_skill
        assert app.state.runtime.memory_service.global_memory().capability_profile == {}
        stored_leftover = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
        assert stored_leftover is not None
        assert stored_leftover.id == leftover.id
        assert stored_leftover.current_step == leftover_step

        same_workspace = _verified_return_adopt(
            app=app,
            client=client,
            workspace_id=workspace_a,
            card_id="class-human-same-workspace-card-a",
            title="Keep the leftover fail-closed check in a second card",
            target_skill=target_skill,
            focus_area="session tokens",
            next_step="Review the leftover path again",
            summary="Same workspace proved the leftover check again.",
            reflection="The leftover object is still this workspace.",
        )
        transfer_repeat = ((same_workspace.get("memory") or {}).get("workspace") or {}).get(
            "latest_transfer_state"
        ) or {}
        assert transfer_repeat.get("state") == "awaiting_second_scene"
        assert transfer_repeat.get("state") != "transferable"
        assert app.state.runtime.memory_service.global_memory().capability_profile == {}
        leftover_after_repeat = app.state.runtime.memory_service.repository.get_latest_plan(
            workspace_a
        )
        assert leftover_after_repeat is not None
        assert leftover_after_repeat.id == leftover.id
        assert leftover_after_repeat.current_step == leftover_step
        assert leftover_after_repeat.title == leftover_title

        project_b = tmp_path / "billing-guard-lab"
        project_b.mkdir()
        (project_b / "billing.py").write_text(
            "def require_fresh_token(token):\n    if not token:\n        raise ValueError('expired')\n    return token\n",
            encoding="utf-8",
        )
        started_b = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_b,
                "workspace_name": "Billing guard lab",
                "workspace_path": str(project_b),
            },
        )
        assert started_b.status_code == 200
        session_b = started_b.json().get("session_id") or started_b.json().get("sessionId")
        assert session_b
        ready_provider = ProviderConfig(
            name="ready-provider",
            baseUrl="http://example.test/v1",
            apiKeyRef="ready-ref",
            model="ready-model",
        )
        state_b = app.state.runtime.get_session(str(session_b))
        assert state_b is not None
        state_b.snapshot.provider = ready_provider
        state_b.snapshot.sidecar_status = "ready"
        body_b = _verified_return_adopt(
            app=app,
            client=client,
            workspace_id=workspace_b,
            card_id="class-human-transfer-card-b",
            title="Keep one billing expiry check",
            target_skill=target_skill,
            focus_area="billing tokens",
            next_step="Add a billing expiry test",
            summary="Independent billing workspace proved the same expiry guard.",
            reflection="The same fail-closed expiry decision held in this other project.",
        )
        transfer_b = ((body_b.get("memory") or {}).get("workspace") or {}).get(
            "latest_transfer_state"
        ) or {}
        expected = describe_transfer_skill_state("transferable", target_skill, "en-US")
        assert transfer_b.get("state") == "transferable"
        assert transfer_b.get("concept") == target_skill
        assert transfer_b.get("why") == expected["why"]
        assert transfer_b.get("next") == expected["next"]
        assert workspace_a in (transfer_b.get("workspace_ids") or [])
        assert workspace_b in (transfer_b.get("workspace_ids") or [])
        profile = app.state.runtime.memory_service.global_memory().capability_profile
        assert target_skill in profile
        assert leftover_title not in profile
        assert leftover_step not in profile
        assert leftover.id not in str(profile)
        assert str(project_b) not in str(profile)
        capability = profile[target_skill]
        assert capability.last_outcome == "tests_passed"
        assert workspace_b in capability.workspace_ids
        snapshot_plan_b = body_b.get("plan") or {}
        assert snapshot_plan_b.get("id") not in {leftover.id, leftover.id}
        assert leftover_title not in str(snapshot_plan_b)
        assert leftover_step not in str(snapshot_plan_b)
        assert leftover_title not in str(body_b.get("coach_orientation") or {})
        assert leftover_step not in str(body_b.get("plan_runtime_status") or {})
        assert not (body_b.get("current_task") or body_b.get("currentTask") or {}).get("title")
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None
        actions_b = [
            str(item.get("action") or "")
            for item in (body_b.get("suggested_actions") or body_b.get("suggestedActions") or [])
        ]
        assert "plan" not in actions_b
        assert "next_task" not in actions_b
        assert "task" not in actions_b
        orientation_b = body_b.get("coach_orientation") or body_b.get("coachOrientation") or {}
        object_kind = orientation_b.get("object_kind") or orientation_b.get("objectKind")
        orientation_state = orientation_b.get("state")
        advanced_b = str(
            orientation_b.get("advanced_where") or orientation_b.get("advancedWhere") or ""
        )
        if orientation_state == "ready" and object_kind in {"conversation", "plan"}:
            assert (orientation_b.get("next_step") or orientation_b.get("nextStep")) == expected["next"]
            assert expected["why"] in advanced_b

        leftover_after_b = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
        assert leftover_after_b is not None
        assert leftover_after_b.id == leftover.id
        assert leftover_after_b.title == leftover_title
        assert leftover_after_b.current_step == leftover_step
        scenes_a = app.state.runtime.memory_service._structured_for(workspace_a)._workspace.get(
            "verified_skill_scenes"
        ) or []
        assert any(
            str(item.get("concept") or "") == target_skill
            and str(item.get("workspace_id") or "") == workspace_a
            for item in scenes_a
            if isinstance(item, dict)
        )

        app.state.runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_b,
            concepts=[target_skill],
            outcome="repeated_error",
            summary="Billing project failed after the skill was already transferable.",
            verified_result="local regression",
            verified_by_evaluator=True,
            focus_area=target_skill,
        )
        after_fail = app.state.runtime.memory_service.global_memory().capability_profile
        assert target_skill in after_fail
        assert after_fail[target_skill].verified_count == profile[target_skill].verified_count
        assert after_fail[target_skill].last_outcome == "tests_passed"
        leftover_after_fail = app.state.runtime.memory_service.repository.get_latest_plan(
            workspace_a
        )
        assert leftover_after_fail is not None
        assert leftover_after_fail.id == leftover.id
        assert leftover_after_fail.current_step == leftover_step
        scenes_a_after = app.state.runtime.memory_service._structured_for(workspace_a)._workspace.get(
            "verified_skill_scenes"
        ) or []
        assert scenes_a_after == scenes_a
        transfer_a_after = (
            app.state.runtime.memory_service.snapshot(workspace_a).workspace.get(
                "latest_transfer_state"
            )
            or {}
        )
        assert transfer_a_after.get("concept") == target_skill
        assert workspace_a in (transfer_a_after.get("workspace_ids") or [])


def _snapshot_plan(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
    plan = payload.get("plan") or snapshot.get("plan") or {}
    return plan if isinstance(plan, dict) else {}


def _runtime_plan_id(app, workspace_id: str) -> str:
    runtime = app.state.runtime.memory_service.recover_workspace_facts(workspace_id)[
        "latest_plan_runtime"
    ]
    return str(runtime.get("plan_id") or runtime.get("planId") or "")


def _card_ids(app, workspace_id: str) -> list[str]:
    return [card.card_id for card in app.state.runtime.memory_service.get_cards(workspace_id)]


def _suggested_action_names(payload: dict[str, Any]) -> list[str]:
    items: list[object] = []
    for key in ("suggested_actions", "suggestedActions"):
        value = payload.get(key)
        if isinstance(value, list):
            items.extend(value)
    snapshot = payload.get("snapshot")
    if isinstance(snapshot, dict):
        for key in ("suggested_actions", "suggestedActions"):
            value = snapshot.get(key)
            if isinstance(value, list):
                items.extend(value)
    memory = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
    workspace = memory.get("workspace") if isinstance(memory.get("workspace"), dict) else {}
    turn = workspace.get("latest_coach_turn") or workspace.get("latestCoachTurn") or {}
    if isinstance(turn, dict):
        for key in ("suggested_actions", "suggestedActions"):
            value = turn.get(key)
            if isinstance(value, list):
                items.extend(value)
    names: list[str] = []
    for item in items:
        if isinstance(item, dict):
            names.append(str(item.get("action") or ""))
        elif isinstance(item, str):
            names.append(item)
    return names


def _seed_leftover_minting_chips(app, workspace_id: str) -> None:
    app.state.runtime.memory_service.update_workspace_state(
        workspace_id,
        latest_coach_turn={
            "suggested_actions": [
                {"id": "leftover-plan", "label": "Generate a plan", "action": "plan"},
                {"id": "leftover-task", "label": "Start a task", "action": "task"},
                {"id": "leftover-next", "label": "Next challenge", "action": "next_task"},
                {"id": "leftover-review", "label": "Review current file", "action": "review"},
            ]
        },
    )


def _assert_no_minting_chips(payload: dict[str, Any]) -> None:
    actions = _suggested_action_names(payload)
    assert "plan" not in actions
    assert "task" not in actions
    assert "next_task" not in actions


def _assert_leftover_not_painted_as_live(
    payload: dict[str, Any],
    *,
    leftover_id: str,
    leftover_title: str,
    leftover_step: str,
) -> None:
    _assert_no_minting_chips(payload)
    snapshot_plan = _snapshot_plan(payload)
    plan_id = str(snapshot_plan.get("id") or snapshot_plan.get("plan_id") or "")
    assert plan_id != leftover_id
    assert leftover_title not in str(snapshot_plan.get("title") or "")
    plan_step = str(snapshot_plan.get("current_step") or snapshot_plan.get("currentStep") or "")
    assert plan_step != leftover_step
    orientation = payload.get("coach_orientation") or payload.get("coachOrientation") or {}
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
    if not isinstance(orientation, dict) or not orientation:
        orientation = snapshot.get("coach_orientation") or snapshot.get("coachOrientation") or {}
    object_kind = str(orientation.get("object_kind") or orientation.get("objectKind") or "")
    object_label = str(orientation.get("object_label") or orientation.get("objectLabel") or "")
    assert leftover_title not in object_label
    assert leftover_id not in object_label
    if object_kind == "plan":
        assert leftover_step not in object_label
        assert leftover_title not in str(orientation)
    memory = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
    if not memory:
        memory = snapshot.get("memory") if isinstance(snapshot.get("memory"), dict) else {}
    workspace = memory.get("workspace") if isinstance(memory.get("workspace"), dict) else {}
    resources = memory.get("resources") or payload.get("resources") or snapshot.get("resources") or []
    assert leftover_step not in str(resources)
    assert leftover_title not in str(resources)
    sandbox = workspace.get("sandbox_preview") or workspace.get("sandboxPreview") or {}
    assert leftover_step not in str(sandbox.get("title") or "")
    assert leftover_title not in str(sandbox.get("title") or "")
    selected = str(workspace.get("selected_card_title") or workspace.get("selectedCardTitle") or "")
    assert leftover_step not in selected
    assert leftover_title not in selected
    handoff = workspace.get("latest_training_handoff") or workspace.get("latestTrainingHandoff") or {}
    assert leftover_step not in str(handoff.get("card_title") or handoff.get("cardTitle") or "")
    assert leftover_title not in str(handoff.get("card_title") or handoff.get("cardTitle") or "")
    assert leftover_title not in str(workspace.get("onboarding_request") or workspace.get("onboardingRequest") or "")
    assert leftover_title not in str(workspace.get("project_context") or workspace.get("projectContext") or "")
    assert not (payload.get("current_task") or payload.get("currentTask") or {}).get("title")


def _orientation_kind(payload: dict[str, Any]) -> str:
    orientation = payload.get("coach_orientation") or payload.get("coachOrientation") or {}
    if not isinstance(orientation, dict):
        return ""
    return str(orientation.get("object_kind") or orientation.get("objectKind") or "")


def _seed_leftover_five_view_chrome(
    app,
    workspace_id: str,
    leftover_title: str,
    leftover_step: str,
) -> None:
    app.state.runtime.repository.save_resource(
        workspace_id,
        ResourceRecord(
            id="resource-leftover-plan-identity",
            kind="markdown",
            name=leftover_step,
            source="leftover-plan.md",
            summary=leftover_title,
        ),
    )
    app.state.runtime.memory_service.update_workspace_state(
        workspace_id,
        sandbox_preview={
            "path": "leftover-plan.md",
            "title": leftover_step,
            "excerpt": leftover_title,
        },
        onboarding_request=leftover_step,
        project_context=leftover_title,
        selected_card_title=leftover_step,
    )


def _assert_five_views_new_live_plan_not_leftover(
    body: dict[str, Any],
    *,
    leftover_id: str,
    leftover_title: str,
    leftover_step: str,
    leftover_why: str,
    generated_id: str,
    generated_title: str,
    generated_step: str,
) -> None:
    orientation = body.get("coach_orientation") or body.get("coachOrientation") or {}
    snapshot = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else {}
    if not isinstance(orientation, dict) or not orientation:
        orientation = snapshot.get("coach_orientation") or snapshot.get("coachOrientation") or {}
    object_kind = str(orientation.get("object_kind") or orientation.get("objectKind") or "")
    object_label = str(orientation.get("object_label") or orientation.get("objectLabel") or "")
    assert leftover_title not in object_label
    assert leftover_step not in object_label
    assert leftover_id not in object_label
    assert leftover_title not in str(orientation)
    assert leftover_step not in str(orientation)
    if object_kind == "plan":
        assert leftover_step not in object_label
        assert generated_step in object_label or generated_title in object_label or generated_id in str(
            orientation
        )
    assert object_kind != "training" or leftover_step not in object_label
    action_blob = str(
        body.get("suggested_actions")
        or body.get("suggestedActions")
        or snapshot.get("suggested_actions")
        or snapshot.get("suggestedActions")
        or []
    )
    assert leftover_title not in action_blob
    assert leftover_step not in action_blob

    plan = _snapshot_plan(body)
    assert (plan.get("id") or plan.get("plan_id")) == generated_id
    assert leftover_title not in str(plan.get("title") or "")
    plan_step = str(plan.get("current_step") or plan.get("currentStep") or "")
    assert plan_step != leftover_step
    status = (
        body.get("plan_runtime_status")
        or body.get("planRuntimeStatus")
        or snapshot.get("plan_runtime_status")
        or snapshot.get("planRuntimeStatus")
        or {}
    )
    status_step = str(status.get("current_step") or status.get("currentStep") or "")
    assert leftover_step not in status_step
    assert leftover_title not in str(status)
    assert leftover_step not in str(status.get("current_main_thread") or status.get("currentMainThread") or {})
    assert leftover_why not in str(status.get("why_now") or status.get("whyNow") or "")
    assert (status.get("plan_id") or status.get("planId") or "") == generated_id
    assert not (
        body.get("current_task")
        or body.get("currentTask")
        or snapshot.get("current_task")
        or snapshot.get("currentTask")
        or {}
    ).get("title")

    memory = body.get("memory") or snapshot.get("memory") or {}
    workspace = memory.get("workspace") or {}
    selected = str(workspace.get("selected_card_title") or workspace.get("selectedCardTitle") or "")
    assert leftover_step not in selected
    assert leftover_title not in selected
    handoff = workspace.get("latest_training_handoff") or workspace.get("latestTrainingHandoff") or {}
    assert leftover_step not in str(handoff.get("card_title") or handoff.get("cardTitle") or "")
    assert leftover_title not in str(handoff.get("card_title") or handoff.get("cardTitle") or "")
    routing = workspace.get("active_training_card_routing") or workspace.get("activeTrainingCardRouting") or {}
    assert leftover_step not in str(routing.get("why_this_card") or routing.get("whyThisCard") or "")
    next_hop = workspace.get("latest_training_next_hop") or workspace.get("latestTrainingNextHop") or {}
    assert leftover_step not in str(next_hop.get("title") or "")
    assert leftover_step not in str(next_hop.get("card_title") or next_hop.get("cardTitle") or "")
    runtime = workspace.get("latest_plan_runtime") or workspace.get("latestPlanRuntime") or {}
    assert (runtime.get("plan_id") or runtime.get("planId")) == generated_id
    assert leftover_step not in str(runtime.get("current_step") or runtime.get("currentStep") or "")

    sandbox = workspace.get("sandbox_preview") or workspace.get("sandboxPreview") or {}
    assert leftover_step not in str(sandbox.get("title") or "")
    assert leftover_title not in str(sandbox.get("title") or "")
    resources = memory.get("resources") or body.get("resources") or snapshot.get("resources") or []
    assert leftover_step not in str(resources)
    assert leftover_title not in str(resources)
    selected_detail = memory.get("selected_resource_detail") or {}
    assert leftover_step not in str(selected_detail)
    assert leftover_title not in str(selected_detail)

    assert leftover_step not in str(workspace.get("onboarding_request") or workspace.get("onboardingRequest") or "")
    assert leftover_title not in str(workspace.get("onboarding_request") or workspace.get("onboardingRequest") or "")
    assert leftover_step not in str(workspace.get("project_context") or workspace.get("projectContext") or "")
    assert leftover_title not in str(workspace.get("project_context") or workspace.get("projectContext") or "")


def _assert_workspace_b_unpainted_of_a(
    body_b: dict[str, Any],
    *,
    leftover_id: str,
    leftover_title: str,
    leftover_step: str,
    generated_id: str,
    generated_title: str,
    generated_step: str,
) -> None:
    foreign_plan = body_b.get("plan") or {}
    assert foreign_plan.get("id") not in {leftover_id, generated_id}
    assert leftover_title not in str(foreign_plan)
    assert leftover_step not in str(foreign_plan)
    assert generated_title not in str(foreign_plan)
    assert leftover_title not in str(body_b.get("coach_orientation") or body_b.get("coachOrientation") or {})
    assert leftover_step not in str(body_b.get("plan_runtime_status") or body_b.get("planRuntimeStatus") or {})
    assert generated_step not in str(body_b.get("plan_runtime_status") or body_b.get("planRuntimeStatus") or {})
    assert leftover_step not in str((body_b.get("memory") or {}).get("workspace") or {})
    assert leftover_title not in str((body_b.get("memory") or {}).get("resources") or body_b.get("resources") or [])
    assert not (body_b.get("current_task") or body_b.get("currentTask") or {}).get("title")


def _ready_session_provider(app, session_id: str) -> None:
    state = app.state.runtime.get_session(str(session_id))
    assert state is not None
    state.snapshot.provider = ProviderConfig(
        name="ready-provider",
        baseUrl="http://example.test/v1",
        apiKeyRef="ready-ref",
        model="ready-model",
    )
    state.snapshot.sidecar_status = "ready"


def _seed_runtime_provider(app) -> None:
    """Runtime-level provider + verified capabilities for provider-gated routes."""
    from provider_fixtures import seed_verified_capabilities

    provider = ProviderConfig(
        name="test-openai-compatible",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={"chat": True, "tools": False, "streaming": True},
    )
    app.state.runtime.provider_config = provider
    app.state.runtime.provider_api_key = "sk-test"
    app.state.runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
    app.state.runtime.provider_service_cache.clear()
    seed_verified_capabilities(app.state.runtime, provider, "sk-test", tools=False)


async def _commit_new_formal_plan(*args: object, **kwargs: object) -> dict[str, object]:
    coach_context = kwargs["coach_context"]
    assert isinstance(coach_context, dict)
    tool_context = ToolContext(
        runtime=coach_context["__runtime__"],
        workspace_id=str(coach_context["workspace_id"]),
        session_id=str(coach_context["session_id"]),
        profile=args[0],
        response_language=kwargs.get("response_language"),
        extra={"formal_plan_mutation": True, "allow_coach_only_tools": True},
    )
    tool_result = await build_default_tool_registry().invoke(
        tool_context,
        "save_formal_plan",
        {
            "title": "Token-refresh learning path",
            "summary": "Build a grounded token-refresh path from the live conversation.",
            "current_step": "Inspect one refresh boundary and verify one request path.",
            "verify_method": ["One focused refresh test passes."],
            "stages": [
                {
                    "id": "stage-refresh",
                    "title": "Refresh boundary",
                    "goal": "Explain refresh ownership and fail-closed expiry.",
                    "outcomes": ["Name the refresh boundary", "Verify one request path"],
                    "status": "active",
                }
            ],
        },
    )
    assert tool_result["ok"] is True
    return {
        "content": "I committed a new formal plan from this explicit generate turn.",
        "summary": "The refresh-boundary plan is committed.",
        "next_step": "Inspect one refresh path.",
        "stop_reason": "completed",
        "tool_events": [{"type": "tool_result", "name": "save_formal_plan", "result": tool_result}],
        "fell_back": False,
    }


async def _commit_new_formal_plan_stream(*args: object, **kwargs: object):
    result = await _commit_new_formal_plan(*args, **kwargs)
    for event in result.get("tool_events") or []:
        if isinstance(event, dict):
            yield dict(event)
    content = str(result.get("content") or "")
    if content:
        yield {"type": "text", "delta": content, "safe_to_stream": True}
    yield {
        "type": "final",
        "content": content,
        "summary": result.get("summary"),
        "next_step": result.get("next_step"),
        "stop_reason": result.get("stop_reason") or "completed",
        "tool_events": result.get("tool_events") or [],
        "fell_back": False,
    }


async def _coaching_leftover_plain_stream(*_args: object, **_kwargs: object):
    yield "Keep coaching this recovered step. Do not generate or save a plan."


async def _coaching_leftover_stream(*_args: object, **_kwargs: object):
    yield {
        "type": "text",
        "delta": "Keep coaching this recovered step. Do not generate or save a plan.",
        "safe_to_stream": True,
    }
    yield {
        "type": "final",
        "content": "Keep coaching this recovered step. Do not generate or save a plan.",
        "summary": "Stay with the recovered step.",
        "next_step": "Keep one focused auth check.",
        "stop_reason": "completed",
        "fell_back": False,
    }


def test_class_human_coaching_turn_does_not_resurrect_leftover(tmp_path: Path) -> None:
    workspace_a = "workspace-a-turn-leftover-coach"
    workspace_b = "workspace-b-turn-leftover-coach"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    leftover_why = "Keep the leftover why"
    next_step = "Add a token expiry test"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover, session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
        )
        _seed_leftover_five_view_chrome(app, workspace_a, leftover_title, leftover_step)
        cards_before = _card_ids(app, workspace_a)
        unusable = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_a,
                "intent": "coach",
                "message": "Diagnose the current auth check. Do not generate a plan.",
            },
        )
        assert unusable.status_code == 400, unusable.text
        stored = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
        assert stored is not None
        assert stored.id == leftover.id
        assert stored.current_step == leftover_step
        assert stored.title == leftover_title
        assert _runtime_plan_id(app, workspace_a) == ""
        assert _card_ids(app, workspace_a) == cards_before
        capability = (
            client.get(f"/memory/summary?workspace_id={workspace_a}").json().get("memory") or {}
        ).get("workspace", {}).get("latest_provider_capability") or {}
        assert capability.get("tools_ready") is not True
        assert capability.get("ok") is not True

        from provider_fixtures import seed_verified_capabilities

        provider = ProviderConfig(
            name="test-openai-compatible",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={"chat": True, "tools": False, "streaming": True},
        )
        app.state.runtime.provider_config = provider
        app.state.runtime.provider_api_key = "sk-test"
        app.state.runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        app.state.runtime.provider_service_cache.clear()
        seed_verified_capabilities(app.state.runtime, provider, "sk-test", tools=False)
        _ready_session_provider(app, session_id)
        coached = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_a,
                "intent": "coach",
                "message": "Keep coaching this recovered step. Do not generate or save a plan.",
                "response_language": "en-US",
            },
        )
        assert coached.status_code == 200, coached.text
        body = coached.json()
        _assert_leftover_not_painted_as_live(
            body,
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
        )
        stored_after = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
        assert stored_after is not None
        assert stored_after.id == leftover.id
        assert stored_after.current_step == leftover_step
        assert stored_after.title == leftover_title
        leftover_stored = app.state.runtime.memory_service.repository.get_plan_by_id(leftover.id)
        assert leftover_stored is not None
        assert leftover_stored[1].why_now == leftover_why
        assert _runtime_plan_id(app, workspace_a) == ""
        assert _card_ids(app, workspace_a) == cards_before
        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        body_b = client.get(f"/memory/summary?workspace_id={workspace_b}").json()
        foreign_plan = body_b.get("plan") or {}
        assert foreign_plan.get("id") != leftover.id
        assert leftover_title not in str(foreign_plan)
        assert leftover_step not in str(foreign_plan)
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None


def test_class_human_turn_unusable_provider_does_not_invent_or_mint_chips(
    tmp_path: Path,
) -> None:
    workspace_a = "workspace-a-unusable-provider-chips"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    next_step = "Add a token expiry test"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover, session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
        )
        cards_before = _card_ids(app, workspace_a)
        provider = ProviderConfig(
            name="test-openai-compatible",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={"chat": True, "tools": False, "streaming": True},
        )
        app.state.runtime.provider_config = provider
        app.state.runtime.provider_api_key = "sk-test"
        app.state.runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        app.state.runtime.provider_service_cache.clear()
        _ready_session_provider(app, session_id)
        _seed_leftover_minting_chips(app, workspace_a)

        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply",
                new=AsyncMock(return_value="Coach kept the recovered step."),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(
                    return_value={
                        "content": "Coach kept the recovered step.",
                        "stop_reason": "completed",
                    }
                ),
            ),
        ):
            for intent, message in (
                ("coach", "Keep coaching this recovered step. Do not generate a plan."),
                ("next_task", "Give me the next task."),
                ("task", "Turn this into a task."),
                ("plan", "Generate a learning plan."),
            ):
                turned = client.post(
                    "/turn",
                    json={
                        "session_id": session_id,
                        "workspace_id": workspace_a,
                        "intent": intent,
                        "message": message,
                        "response_language": "en-US",
                    },
                )
                assert turned.status_code == 200, turned.text
                body = turned.json()
                _assert_no_minting_chips(body)
                if intent != "coach":
                    blob = str(body)
                    assert (
                        "connection is not ready" in blob.lower()
                        or "连接还不能用" in blob
                        or "Repair the provider" in blob
                    )
                stored = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
                assert stored is not None
                assert stored.id == leftover.id
                assert stored.current_step == leftover_step
                assert stored.title == leftover_title
                assert _runtime_plan_id(app, workspace_a) == ""
                assert _card_ids(app, workspace_a) == cards_before
                assert not (body.get("current_task") or body.get("currentTask") or {}).get("title")
                capability = (
                    client.get(f"/memory/summary?workspace_id={workspace_a}").json().get("memory") or {}
                ).get("workspace", {}).get("latest_provider_capability") or {}
                assert capability.get("tools_ready") is not True
                assert capability.get("ok") is not True
                reliability = body.get("reliability") or (body.get("agent_meta") or {}).get(
                    "reliability"
                ) or {}
                assert reliability.get("phase") == "acked"
                assert reliability.get("outcome") == "failure"

            unknown = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_a,
                    "intent": "next_task",
                    "message": "Give me the next task.",
                    "response_language": "en-US",
                    "api_key": "sk-test",
                    "provider": {
                        "name": "unknown-gateway",
                        "baseUrl": "http://127.0.0.1:9/v1",
                        "model": "MiniMax-M2.7",
                        "protocol": "newapi_channel_conn",
                    },
                },
            )
            assert unknown.status_code == 200, unknown.text
            unknown_body = unknown.json()
            _assert_no_minting_chips(unknown_body)
            assert "sk-test" not in str(unknown_body)
            stored_after = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
            assert stored_after is not None
            assert stored_after.id == leftover.id
            assert _card_ids(app, workspace_a) == cards_before


def test_class_human_stream_unusable_provider_does_not_invent_or_mint_chips(
    tmp_path: Path,
) -> None:
    workspace_a = "workspace-a-stream-unusable-provider"
    workspace_b = "workspace-b-stream-unusable-provider"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    next_step = "Add a token expiry test"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    async def _model_must_not_run(*_args: object, **_kwargs: object):
        raise AssertionError("unusable provider stream must not call the model")
        yield  # pragma: no cover

    with TestClient(app) as client:
        leftover, session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
        )
        cards_before = _card_ids(app, workspace_a)
        provider = ProviderConfig(
            name="test-openai-compatible",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={"chat": True, "tools": False, "streaming": True},
        )
        app.state.runtime.provider_config = provider
        app.state.runtime.provider_api_key = "sk-test"
        app.state.runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        app.state.runtime.provider_service_cache.clear()
        _ready_session_provider(app, session_id)
        _seed_leftover_minting_chips(app, workspace_a)

        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=_model_must_not_run,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_stream",
                new=_model_must_not_run,
            ),
        ):
            for path, intent, message in (
                (
                    "/turn/stream",
                    "coach",
                    "Keep coaching this recovered step. Do not generate a plan.",
                ),
                ("/turn/stream", "next_task", "Give me the next task."),
                ("/turn/stream", "task", "Turn this into a task."),
                ("/turn/stream", "plan", "Generate a learning plan."),
                (
                    "/session/message/stream",
                    "coach",
                    "Stay with the recovered step. Do not generate a plan or mint a task.",
                ),
            ):
                streamed = client.post(
                    path,
                    json={
                        "session_id": session_id,
                        "workspace_id": workspace_a,
                        "intent": intent,
                        "message": message,
                        "response_language": "en-US",
                    },
                )
                assert streamed.status_code == 200, streamed.text
                phases = streamed_status_phases(streamed.text)
                assert "pending" in phases
                assert "executing" in phases
                assert "failed" in phases
                assert "acked" in phases
                assert phases.index("pending") < phases.index("executing")
                assert phases.index("executing") < phases.index("failed")
                assert phases.index("failed") < phases.index("acked")
                body = completed_stream_response(streamed.text)
                reliability = body.get("reliability") or {}
                assert reliability.get("phase") == "acked"
                assert reliability.get("outcome") == "failure"
                _assert_no_minting_chips(body)
                blob = str(body)
                assert (
                    "connection is not ready" in blob.lower()
                    or "连接还不能用" in blob
                    or "Repair the provider" in blob
                )
                stored = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
                assert stored is not None
                assert stored.id == leftover.id
                assert stored.current_step == leftover_step
                assert stored.title == leftover_title
                assert _runtime_plan_id(app, workspace_a) == ""
                assert _card_ids(app, workspace_a) == cards_before
                assert not (body.get("current_task") or body.get("currentTask") or {}).get("title")
                capability = (
                    client.get(f"/memory/summary?workspace_id={workspace_a}").json().get("memory")
                    or {}
                ).get("workspace", {}).get("latest_provider_capability") or {}
                assert capability.get("tools_ready") is not True
                assert capability.get("ok") is not True

            unknown = client.post(
                "/turn/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_a,
                    "intent": "next_task",
                    "message": "Give me the next task.",
                    "response_language": "en-US",
                    "api_key": "sk-test",
                    "provider": {
                        "name": "unknown-gateway",
                        "baseUrl": "http://127.0.0.1:9/v1",
                        "model": "MiniMax-M2.7",
                        "protocol": "newapi_channel_conn",
                    },
                },
            )
            assert unknown.status_code == 200, unknown.text
            unknown_phases = streamed_status_phases(unknown.text)
            assert "pending" in unknown_phases
            assert "failed" in unknown_phases
            assert "acked" in unknown_phases
            unknown_body = completed_stream_response(unknown.text)
            _assert_no_minting_chips(unknown_body)
            assert "sk-test" not in str(unknown_body)
            assert (unknown_body.get("reliability") or {}).get("outcome") == "failure"
            stored_after = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
            assert stored_after is not None
            assert stored_after.id == leftover.id
            assert _card_ids(app, workspace_a) == cards_before

        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        body_b = client.get(f"/memory/summary?workspace_id={workspace_b}").json()
        foreign_plan = body_b.get("plan") or {}
        assert foreign_plan.get("id") != leftover.id
        assert leftover_title not in str(foreign_plan)
        assert leftover_step not in str(foreign_plan)
        assert leftover_title not in str(body_b.get("coach_orientation") or body_b.get("coachOrientation") or {})
        assert leftover_step not in str(body_b.get("plan_runtime_status") or body_b.get("planRuntimeStatus") or {})
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None


def test_class_human_explicit_generate_in_turn_binds_new_plan_after_leftover(
    tmp_path: Path,
) -> None:
    workspace_a = "workspace-a-turn-leftover-generate"
    workspace_b = "workspace-b-turn-leftover-generate"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    leftover_why = "Keep the leftover why"
    next_step = "Add a token expiry test"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover, session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
            leftover_frozen=True,
        )
        _seed_leftover_five_view_chrome(app, workspace_a, leftover_title, leftover_step)
        cards_before = _card_ids(app, workspace_a)
        configure_tool_capable_provider(app.state.runtime)
        _ready_session_provider(app, session_id)
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(side_effect=_commit_new_formal_plan),
            ),
        ):
            generated = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_a,
                    "intent": "plan",
                    "formalPlanMutation": True,
                    "message": "Generate and save a formal learning plan for token refresh.",
                    "use_agent_loop": True,
                },
            )
        assert generated.status_code == 200, generated.text
        body = generated.json()
        assert body.get("agent_meta", {}).get("formal_plan_mutation_blocked") is not True
        generated_plan = _snapshot_plan(body)
        generated_id = str(generated_plan.get("id") or generated_plan.get("plan_id") or "")
        generated_title = str(generated_plan.get("title") or "")
        generated_step = str(
            generated_plan.get("current_step") or generated_plan.get("currentStep") or ""
        )
        assert generated_id
        assert generated_id != leftover.id
        assert leftover_title not in str(generated_plan.get("title") or "")
        assert leftover_step not in generated_step
        leftover_after = app.state.runtime.memory_service.repository.get_plan_by_id(leftover.id)
        assert leftover_after is not None
        leftover_workspace, leftover_record = leftover_after
        assert leftover_workspace == workspace_a
        assert leftover_record.id == leftover.id
        assert leftover_record.title == leftover_title
        assert leftover_record.current_step == leftover_step
        assert leftover_record.frozen is True
        latest = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
        assert latest is not None
        assert latest.id == generated_id
        assert _runtime_plan_id(app, workspace_a) == generated_id
        assert _card_ids(app, workspace_a) == cards_before
        _assert_five_views_new_live_plan_not_leftover(
            body,
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            leftover_why=leftover_why,
            generated_id=generated_id,
            generated_title=generated_title,
            generated_step=generated_step,
        )
        summary_a = client.get(f"/memory/summary?workspace_id={workspace_a}")
        assert summary_a.status_code == 200
        _assert_five_views_new_live_plan_not_leftover(
            summary_a.json(),
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            leftover_why=leftover_why,
            generated_id=generated_id,
            generated_title=generated_title,
            generated_step=generated_step,
        )
        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        body_b = client.get(f"/memory/summary?workspace_id={workspace_b}").json()
        _assert_workspace_b_unpainted_of_a(
            body_b,
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            generated_id=generated_id,
            generated_title=generated_title,
            generated_step=generated_step,
        )
        foreign_plan = body_b.get("plan") or {}
        assert foreign_plan.get("id") not in {leftover.id, generated_id}
        assert leftover_title not in str(foreign_plan)
        assert leftover_step not in str(foreign_plan)
        assert generated_step not in str(body_b.get("plan_runtime_status") or {})
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None


def test_class_human_promotion_review_and_next_challenge_do_not_mint_live_card(
    tmp_path: Path,
) -> None:
    workspace_a = "workspace-a-turn-promote-review"
    workspace_b = "workspace-b-turn-promote-review"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    next_step = "Add a token expiry test"
    target_skill = "auth expiry"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover, _session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
        )
        project_b = tmp_path / "billing-guard-lab"
        project_b.mkdir()
        billing = project_b / "billing.py"
        billing.write_text(
            "def require_fresh_token(token):\n    if not token:\n        raise ValueError('expired')\n    return token\n",
            encoding="utf-8",
        )
        started_b = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_b,
                "workspace_name": "Billing guard lab",
                "workspace_path": str(project_b),
            },
        )
        assert started_b.status_code == 200
        session_b = str(started_b.json().get("session_id") or started_b.json().get("sessionId") or "")
        assert session_b
        body_b = _verified_return_adopt(
            app=app,
            client=client,
            workspace_id=workspace_b,
            card_id="class-human-turn-transfer-card-b",
            title="Keep one billing expiry check",
            target_skill=target_skill,
            focus_area="billing tokens",
            next_step="Add a billing expiry test",
            summary="Independent billing workspace proved the same expiry guard.",
            reflection="The same fail-closed expiry decision held in this other project.",
        )
        transfer_b = ((body_b.get("memory") or {}).get("workspace") or {}).get(
            "latest_transfer_state"
        ) or {}
        assert transfer_b.get("state") == "transferable"
        due_reviews = (body_b.get("memory") or {}).get("due_reviews") or body_b.get("dueReviews") or []
        if not due_reviews:
            due_reviews = (body_b.get("memory") or {}).get("dueReviews") or []
        assert due_reviews
        review_item = due_reviews[0]
        assert str(review_item.get("concept") or "") == target_skill
        assert "transfer" in str(review_item.get("linked_context") or review_item.get("linkedContext") or "")
        cards_b_before = _card_ids(app, workspace_b)
        from provider_fixtures import seed_verified_capabilities

        provider = ProviderConfig(
            name="test-openai-compatible",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
            model="gpt-4o-mini",
            capabilities={"chat": True, "tools": False, "streaming": True},
        )
        app.state.runtime.provider_config = provider
        app.state.runtime.provider_api_key = "sk-test"
        app.state.runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        app.state.runtime.provider_service_cache.clear()
        seed_verified_capabilities(app.state.runtime, provider, "sk-test", tools=False)
        _ready_session_provider(app, session_b)
        next_challenge = client.post(
            "/turn",
            json={
                "session_id": session_b,
                "workspace_id": workspace_b,
                "intent": "next_task",
                "message": "Give me the next challenge after this transferable review.",
                "response_language": "en-US",
            },
        )
        assert next_challenge.status_code == 200, next_challenge.text
        next_body = next_challenge.json()
        assert not (next_body.get("current_task") or next_body.get("currentTask") or {}).get("title")
        snapshot_plan_b = _snapshot_plan(next_body)
        assert snapshot_plan_b.get("id") not in {leftover.id}
        assert leftover_title not in str(snapshot_plan_b)
        assert leftover_step not in str(snapshot_plan_b)
        assert _runtime_plan_id(app, workspace_b) == ""
        assert _card_ids(app, workspace_b) == cards_b_before
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None
        review = client.post(
            "/turn",
            json={
                "session_id": session_b,
                "workspace_id": workspace_b,
                "intent": "review",
                "message": "Review this transferable skill. Do not mint a new card or plan.",
                "response_language": "en-US",
                "current_file": {
                    "path": str(billing),
                    "language_id": "python",
                    "content": billing.read_text(encoding="utf-8"),
                    "diagnostics": [],
                },
            },
        )
        assert review.status_code == 200, review.text
        review_body = review.json()
        assert not (review_body.get("current_task") or review_body.get("currentTask") or {}).get("title")
        assert _card_ids(app, workspace_b) == cards_b_before
        leftover_after = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
        assert leftover_after is not None
        assert leftover_after.id == leftover.id
        assert leftover_after.current_step == leftover_step
        assert leftover_after.title == leftover_title
        foreign = client.get(f"/memory/summary?workspace_id={workspace_b}").json()
        foreign_plan = foreign.get("plan") or {}
        assert leftover_title not in str(foreign_plan)
        assert leftover_step not in str(foreign_plan)
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None
        next_actions = [
            str(item.get("action") or "")
            for item in (next_body.get("suggested_actions") or next_body.get("suggestedActions") or [])
        ]
        assert "plan" not in next_actions
        assert "task" not in next_actions
        assert "next_task" not in next_actions


def test_class_human_session_start_and_memory_summary_do_not_mint_leftover_not_live(
    tmp_path: Path,
) -> None:
    workspace_a = "workspace-a-session-leftover-chips"
    workspace_b = "workspace-b-session-leftover-chips"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    next_step = "Add a token expiry test"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover, _session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
        )
        _seed_leftover_minting_chips(app, workspace_a)
        resumed = client.post(
            "/session/start",
            json={"workspace_id": workspace_a, "workspace_name": "Auth expiry lab"},
        )
        assert resumed.status_code == 200, resumed.text
        started = resumed.json()
        _assert_no_minting_chips(started)
        assert _runtime_plan_id(app, workspace_a) == ""
        runtime_status = started.get("plan_runtime_status") or started.get("planRuntimeStatus") or {}
        recovered_step = str(
            runtime_status.get("current_step") or runtime_status.get("currentStep") or ""
        )
        assert recovered_step
        assert leftover_title not in recovered_step
        assert _orientation_kind(started) != "plan"
        _assert_leftover_not_painted_as_live(
            started,
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
        )
        summary = client.get(f"/memory/summary?workspace_id={workspace_a}")
        assert summary.status_code == 200, summary.text
        summary_body = summary.json()
        _assert_no_minting_chips(summary_body)
        assert _orientation_kind(summary_body) != "plan"
        _assert_leftover_not_painted_as_live(
            summary_body,
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
        )
        summary_runtime = (
            summary_body.get("plan_runtime_status") or summary_body.get("planRuntimeStatus") or {}
        )
        assert str(
            summary_runtime.get("current_step") or summary_runtime.get("currentStep") or ""
        )
        assert not (summary_body.get("current_task") or summary_body.get("currentTask") or {}).get(
            "title"
        )
        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        body_b = client.get(f"/memory/summary?workspace_id={workspace_b}").json()
        foreign_plan = body_b.get("plan") or {}
        assert foreign_plan.get("id") != leftover.id
        assert leftover_title not in str(foreign_plan)
        assert leftover_step not in str(foreign_plan)
        _assert_no_minting_chips(body_b)
        assert leftover_title not in str(body_b.get("coach_orientation") or body_b.get("coachOrientation") or {})
        assert leftover_step not in str(body_b.get("plan_runtime_status") or body_b.get("planRuntimeStatus") or {})
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None


def test_class_human_streaming_turn_does_not_resurrect_leftover(tmp_path: Path) -> None:
    workspace_a = "workspace-a-stream-leftover-coach"
    workspace_b = "workspace-b-stream-leftover-coach"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    next_step = "Add a token expiry test"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover, session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
        )
        leftover_why = "Keep the leftover why"
        _seed_leftover_five_view_chrome(app, workspace_a, leftover_title, leftover_step)
        _seed_leftover_minting_chips(app, workspace_a)
        cards_before = _card_ids(app, workspace_a)
        configure_tool_capable_provider(app.state.runtime)
        _ready_session_provider(app, session_id)
        resumed = client.post(
            "/session/start",
            json={"workspace_id": workspace_a, "workspace_name": "Auth expiry lab"},
        )
        assert resumed.status_code == 200, resumed.text
        _assert_leftover_not_painted_as_live(
            resumed.json(),
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
        )
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=_coaching_leftover_stream,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_stream",
                new=_coaching_leftover_plain_stream,
            ),
        ):
            streamed = client.post(
                "/turn/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_a,
                    "intent": "coach",
                    "message": "Keep coaching this recovered step. Do not generate or save a plan.",
                    "response_language": "en-US",
                    "use_agent_loop": True,
                },
            )
            assert streamed.status_code == 200, streamed.text
            body = completed_stream_response(streamed.text)
            message_streamed = client.post(
                "/session/message/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_a,
                    "message": "Stay with the recovered step. Do not generate a plan or mint a task.",
                    "response_language": "en-US",
                    "use_agent_loop": True,
                },
            )
            assert message_streamed.status_code == 200, message_streamed.text
            message_body = completed_stream_response(message_streamed.text)
        _assert_leftover_not_painted_as_live(
            body,
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
        )
        _assert_leftover_not_painted_as_live(
            message_body,
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
        )
        stored_after = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
        assert stored_after is not None
        assert stored_after.id == leftover.id
        assert stored_after.current_step == leftover_step
        assert stored_after.title == leftover_title
        leftover_stored = app.state.runtime.memory_service.repository.get_plan_by_id(leftover.id)
        assert leftover_stored is not None
        assert leftover_stored[1].why_now == leftover_why
        assert _runtime_plan_id(app, workspace_a) == ""
        assert _card_ids(app, workspace_a) == cards_before
        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        body_b = client.get(f"/memory/summary?workspace_id={workspace_b}").json()
        foreign_plan = body_b.get("plan") or {}
        assert foreign_plan.get("id") != leftover.id
        assert leftover_title not in str(foreign_plan)
        assert leftover_step not in str(foreign_plan)
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None


def test_class_human_explicit_generate_in_turn_stream_binds_new_plan_after_leftover(
    tmp_path: Path,
) -> None:
    workspace_a = "workspace-a-stream-leftover-generate"
    workspace_b = "workspace-b-stream-leftover-generate"
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    next_step = "Add a token expiry test"
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        leftover, session_id = _seed_leftover_independent_runtime(
            app=app,
            client=client,
            tmp_path=tmp_path,
            workspace_a=workspace_a,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            next_step=next_step,
            leftover_frozen=True,
        )
        leftover_why = "Keep the leftover why"
        _seed_leftover_five_view_chrome(app, workspace_a, leftover_title, leftover_step)
        cards_before = _card_ids(app, workspace_a)
        configure_tool_capable_provider(app.state.runtime)
        _ready_session_provider(app, session_id)
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic_stream",
                new=_commit_new_formal_plan_stream,
            ),
        ):
            generated = client.post(
                "/turn/stream",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_a,
                    "intent": "plan",
                    "formalPlanMutation": True,
                    "message": "Generate and save a formal learning plan for token refresh.",
                    "use_agent_loop": True,
                    "response_language": "en-US",
                },
            )
        assert generated.status_code == 200, generated.text
        body = completed_stream_response(generated.text)
        assert body.get("agent_meta", {}).get("formal_plan_mutation_blocked") is not True
        generated_plan = _snapshot_plan(body)
        generated_id = str(generated_plan.get("id") or generated_plan.get("plan_id") or "")
        generated_title = str(generated_plan.get("title") or "")
        generated_step = str(
            generated_plan.get("current_step") or generated_plan.get("currentStep") or ""
        )
        assert generated_id
        assert generated_id != leftover.id
        assert leftover_title not in str(generated_plan.get("title") or "")
        assert leftover_step not in generated_step
        leftover_after = app.state.runtime.memory_service.repository.get_plan_by_id(leftover.id)
        assert leftover_after is not None
        leftover_workspace, leftover_record = leftover_after
        assert leftover_workspace == workspace_a
        assert leftover_record.id == leftover.id
        assert leftover_record.title == leftover_title
        assert leftover_record.current_step == leftover_step
        assert leftover_record.frozen is True
        latest = app.state.runtime.memory_service.repository.get_latest_plan(workspace_a)
        assert latest is not None
        assert latest.id == generated_id
        assert _runtime_plan_id(app, workspace_a) == generated_id
        assert _card_ids(app, workspace_a) == cards_before
        _assert_five_views_new_live_plan_not_leftover(
            body,
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            leftover_why=leftover_why,
            generated_id=generated_id,
            generated_title=generated_title,
            generated_step=generated_step,
        )
        summary_a = client.get(f"/memory/summary?workspace_id={workspace_a}")
        assert summary_a.status_code == 200
        _assert_five_views_new_live_plan_not_leftover(
            summary_a.json(),
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            leftover_why=leftover_why,
            generated_id=generated_id,
            generated_title=generated_title,
            generated_step=generated_step,
        )
        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        body_b = client.get(f"/memory/summary?workspace_id={workspace_b}").json()
        _assert_workspace_b_unpainted_of_a(
            body_b,
            leftover_id=leftover.id,
            leftover_title=leftover_title,
            leftover_step=leftover_step,
            generated_id=generated_id,
            generated_title=generated_title,
            generated_step=generated_step,
        )
        foreign_plan = body_b.get("plan") or {}
        assert foreign_plan.get("id") not in {leftover.id, generated_id}
        assert leftover_title not in str(foreign_plan)
        assert leftover_step not in str(foreign_plan)
        assert generated_step not in str(body_b.get("plan_runtime_status") or {})
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None


def test_class_human_consecutive_fail_streak_without_live_plan_does_not_mint(
    tmp_path: Path,
) -> None:
    workspace_a = "ws-class-human-fail-streak-a"
    workspace_b = "ws-class-human-fail-streak-b"
    miss_one = "First consecutive miss on the blocked slice."
    miss_two = "Same miss again on the blocked slice."
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_a, "workspace_name": "Fail streak lab"},
        )
        assert started.status_code == 200
        session_id = started.json()["session_id"]
        assert started.json().get("plan") in (None, {})
        cards_before = _card_ids(app, workspace_a)
        first = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": workspace_a,
                "concepts": ["blocked slice"],
                "outcome": "evaluation",
                "summary": miss_one,
                "action_type": "evaluate_current_file",
                "focus_area": "blocked slice",
                "scenario": "review_reflection",
                "repetition_count": 2,
            },
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": workspace_a,
                "concepts": ["blocked slice"],
                "outcome": "repeated_error",
                "summary": miss_two,
                "action_type": "evaluate_current_file",
                "focus_area": "blocked slice",
                "scenario": "review_reflection",
                "repetition_count": 2,
            },
        )
        assert second.status_code == 200, second.text
        assert second.json().get("plan") in (None, {})
        assert _card_ids(app, workspace_a) == cards_before
        coaching = (second.json().get("memory") or {}).get("coaching_adaptation") or {}
        assert int(coaching.get("failure_streak") or 0) >= 2
        assert coaching.get("next_plan_step") == "shrink"
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_a) is None
        configure_tool_capable_provider(app.state.runtime)
        _ready_session_provider(app, session_id)
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply",
                new=AsyncMock(return_value="Stay with a smaller hint. Do not generate a plan."),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(
                    return_value={
                        "content": "Stay with a smaller hint. Do not generate a plan.",
                        "stop_reason": "completed",
                    }
                ),
            ),
        ):
            for intent, message in (
                ("coach", "I failed twice. What should I do next?"),
                ("next_task", "Give me the next task."),
                ("task", "Turn this into a task."),
                ("plan", "Generate a learning plan."),
            ):
                turned = client.post(
                    "/turn",
                    json={
                        "session_id": session_id,
                        "workspace_id": workspace_a,
                        "intent": intent,
                        "message": message,
                        "response_language": "en-US",
                    },
                )
                assert turned.status_code == 200, turned.text
                body = turned.json()
                snapshot_plan = _snapshot_plan(body)
                assert not snapshot_plan.get("id")
                assert not snapshot_plan.get("current_step")
                assert _card_ids(app, workspace_a) == cards_before
                _assert_no_minting_chips(body)
                actions = body.get("suggested_actions") or body.get("suggestedActions") or []
                assert actions
                joined = " ".join(str(item.get("label") or "") for item in actions).lower()
                assert "smaller hint" in joined or "review" in joined or "hint" in joined
                assert not (body.get("current_task") or body.get("currentTask") or {}).get("title")
                snapshot = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else {}
                assert not (snapshot.get("current_task") or snapshot.get("currentTask") or {}).get("title")
                assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_a) is None
        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        body_b = started_b.json()
        assert body_b.get("plan") in (None, {})
        assert miss_one not in str(body_b)
        assert miss_two not in str(body_b)
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None


def test_class_human_consecutive_success_on_project_a_does_not_mint_or_promote(
    tmp_path: Path,
) -> None:
    workspace_a = "ws-class-human-success-streak-a"
    workspace_b = "ws-class-human-success-streak-b"
    win_one = "First verified success on project A."
    win_two = "Second success on the same project."
    settings = _settings(tmp_path / "trainer-data")
    app = create_app(settings)

    with TestClient(app) as client:
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_a, "workspace_name": "Success streak lab"},
        )
        assert started.status_code == 200
        session_id = started.json()["session_id"]
        cards_before = _card_ids(app, workspace_a)
        first = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": workspace_a,
                "concepts": ["project A slice"],
                "outcome": "tests_passed",
                "summary": win_one,
                "action_type": "evaluate_current_file",
                "focus_area": "project A slice",
                "scenario": "review_reflection",
            },
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": workspace_a,
                "concepts": ["project A slice"],
                "outcome": "tests_passed",
                "summary": win_two,
                "action_type": "evaluate_current_file",
                "focus_area": "project A slice",
                "scenario": "review_reflection",
            },
        )
        assert second.status_code == 200, second.text
        body = second.json()
        memory = body.get("memory") or {}
        coaching = memory.get("coaching_adaptation") or {}
        # Unverified tests_passed labels do not form a verified success streak.
        assert int(coaching.get("success_streak") or 0) == 0
        assert coaching.get("challenge_level") == "steady"
        assert coaching.get("material_recommendation") != "transfer"
        assert (memory.get("mastery") or []) == []
        assert "project A slice" not in app.state.runtime.memory_service._structured_for(
            workspace_a
        )._mastery
        transfer = (memory.get("workspace") or {}).get("latest_transfer_state") or {}
        assert transfer.get("state") not in {"transferable"}
        assert body.get("plan") in (None, {})
        assert _card_ids(app, workspace_a) == cards_before
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_a) is None
        configure_tool_capable_provider(app.state.runtime)
        _ready_session_provider(app, session_id)
        with (
            patch.object(
                ProviderService,
                "has_api_key",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(
                ProviderService,
                "coaching_reply",
                new=AsyncMock(return_value="Stay on this project. Verification is still required."),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(
                    return_value={
                        "content": "Stay on this project. Verification is still required.",
                        "stop_reason": "completed",
                    }
                ),
            ),
        ):
            turned = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_a,
                    "intent": "next_task",
                    "message": "I claimed two passes. Give me the next thing.",
                    "response_language": "en-US",
                },
            )
        assert turned.status_code == 200, turned.text
        turned_body = turned.json()
        snapshot_plan = _snapshot_plan(turned_body)
        assert not snapshot_plan.get("id")
        assert not snapshot_plan.get("current_step")
        assert not (turned_body.get("current_task") or turned_body.get("currentTask") or {}).get("title")
        assert _card_ids(app, workspace_a) == cards_before
        _assert_no_minting_chips(turned_body)
        started_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": "Other lab"},
        )
        assert started_b.status_code == 200
        body_b = started_b.json()
        assert body_b.get("plan") in (None, {})
        assert win_one not in str(body_b)
        assert win_two not in str(body_b)
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_b) is None
        assert app.state.runtime.memory_service.repository.get_latest_plan(workspace_a) is None
