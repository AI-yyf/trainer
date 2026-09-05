"""Leftover stored card identity: live only when runtime carries matching card id."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.models import (
    EvaluationCheck,
    EvaluationReport,
    LearningPlan,
    PlanStage,
    ProviderConfig,
    ResourceRecord,
    TrainingCardCandidateSnapshot,
    ActiveCardSelectionResult,
)
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app
from app.memory.workspace_recovery import PLAN_RUNTIME_KEY


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer leftover card identity",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-leftover-card-identity.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(_settings(tmp_path / "data"))
    provider = ProviderConfig(
        name="test-openai-compatible",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        protocol="openai_chat_completions_compatible",
        capabilities={
            "chat": True,
            "responses": True,
            "vision": False,
            "embeddings": True,
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
    from app.core.models import ProviderCapabilityEvidence, ProviderTestResponse

    runtime.remember_provider_capability_test(
        provider,
        "sk-test-not-a-real-key-aaaaaaaa",
        ProviderTestResponse(
            ok=True,
            detail="stream probe seeded for leftover identity tests",
            capability_evidence=[
                ProviderCapabilityEvidence(
                    name="streaming",
                    declared=True,
                    observed=True,
                    state="verified",
                ),
                ProviderCapabilityEvidence(
                    name="tools",
                    declared=False,
                    observed=None,
                    state="disabled",
                ),
            ],
            tools_ready=False,
            tool_probe_status="disabled",
        ),
    )
    return TestClient(app)


def _model_card_payload() -> str:
    """Model-authored practice card payload for /training/generate-card mocks."""
    return json.dumps(
        {
            "title": "Practice fail-closed token expiry",
            "focus_area": "token expiry",
            "target_skill": "auth expiry",
            "scenario": "A helper must reject an expired token before refresh.",
            "problem_statement": "Implement require_fresh so empty tokens fail closed.",
            "api_hints": ["Call require_fresh()", "Raise on empty token"],
            "deliverable": "A require_fresh helper that rejects empty tokens.",
            "self_check": ["Empty token raises", "Valid token returns"],
            "grading_rubric": ["Fail-closed on empty", "Returns a live token"],
            "stuck_recovery": "Write the empty-token branch first.",
            "reflection_prompt": "What happens if expiry is checked after refresh?",
            "verification_steps": ["Run the expiry probe", "Confirm empty tokens raise"],
            "success_signal": "Empty tokens raise before any refresh path.",
            "return_with": "The helper and the failing empty-token case.",
            "learner_deliverables": ["require_fresh", "empty-token test"],
        }
    )


def _seed_leftover_card_not_live(
    runtime: object,
    workspace_id: str,
    *,
    leftover_card_id: str = "card-leftover-stored-a",
    leftover_step: str = "Keep one auth check",
    leftover_plan_id: str = "plan-formal-old",
    leftover_runtime_plan_id: str = "plan-runtime-other",
) -> str:
    plan = LearningPlan(
        id=leftover_plan_id,
        title="Keep the current stage",
        current_step=leftover_step,
        why_now="Leftover formal why",
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
    runtime.repository.save_plan(workspace_id, plan)
    runtime.memory_service.upsert_card(
        workspace_id,
        TrainingCardCandidateSnapshot(
            card_id=leftover_card_id,
            card_type="practice",
            title=leftover_step,
            status="active",
            focus_area="session tokens",
            target_skill="auth expiry",
            why_now=f"{leftover_step} is the leftover training card.",
        ),
    )
    # Title matches recovered step; workspace selected_card_id set; runtime does NOT
    # carry matching card id → leftover-not-live (same rule as plans).
    runtime.memory_service.update_workspace_state(
        workspace_id,
        **{
            PLAN_RUNTIME_KEY: {
                "workspace_id": workspace_id,
                "plan_id": leftover_runtime_plan_id,
                "current_step": leftover_step,
                "why_now": "Recovered runtime does not match leftover formal",
                "status": "in_progress",
                # Intentionally omit selected_card_id — title must not invent live id.
            },
            "selected_card_id": leftover_card_id,
            "selected_card_title": leftover_step,
        },
    )
    return leftover_card_id


def _seed_live_selected_card(runtime: object, workspace_id: str) -> str:
    live_card_id = "card-live-selected"
    live_step = "Keep one auth check"
    plan = LearningPlan(
        id="plan-live-selected",
        title="Live selected plan",
        current_step=live_step,
        why_now="Live why",
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
    runtime.repository.save_plan(workspace_id, plan)
    runtime.memory_service.update_workspace_state(
        workspace_id,
        **{
            PLAN_RUNTIME_KEY: {
                "workspace_id": workspace_id,
                "plan_id": "plan-live-selected",
                "current_step": live_step,
                "why_now": "Live why",
                "resume_state": "in_progress",
            },
        },
    )
    live_card = TrainingCardCandidateSnapshot(
        card_id=live_card_id,
        card_type="practice",
        title=live_step,
        status="active",
        focus_area="session tokens",
        target_skill="auth expiry",
        why_now="Live selected training card.",
    )
    runtime.memory_service.upsert_card(workspace_id, live_card)
    runtime.memory_service.persist_active_card_selection(
        workspace_id,
        ActiveCardSelectionResult(
            selected_card=live_card,
            selected_card_id=live_card.card_id,
            why_this_card="Live selected card.",
            next_after_completion="Verify.",
            fallback_action="Return to coach.",
            candidate_count=1,
            eligible_count=1,
        ),
    )
    return live_card_id


def test_leftover_stored_card_not_live_selected_card_id(tmp_path: Path) -> None:
    workspace_id = "ws-leftover-card-not-live"
    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        runtime = client.app.state.runtime
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_id)

        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""

        summary = client.get(f"/memory/summary?workspace_id={workspace_id}")
        assert summary.status_code == 200
        workspace = summary.json()["memory"].get("workspace") or {}
        painted = str(workspace.get("selected_card_id") or workspace.get("selectedCardId") or "").strip()
        # Response chrome may strip leftover selection; live helper must stay empty.
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""
        assert leftover_card_id not in painted or painted == ""
        assert runtime.memory_service.get_card(workspace_id, leftover_card_id) is not None


def test_leftover_card_verify_does_not_fsrs_without_live_id(tmp_path: Path) -> None:
    workspace_id = "ws-leftover-card-no-fsrs"
    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        session_id = start.json()["session_id"]
        runtime = client.app.state.runtime
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_id)

        runtime.evaluator_service.evaluate_current_file = MagicMock(
            return_value=EvaluationReport(
                task_spec_id="",
                summary="Leftover verify must not FSRS.",
                static_checks=[],
                dynamic_checks=[
                    EvaluationCheck(id="ok", label="ok", status="passed", detail="ok")
                ],
                semantic_checks=[],
                next_step="stay",
                reflection="",
                passed=True,
            )
        )
        evaluate = client.post(
            "/evaluate/current-file",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "file_path": str(tmp_path / "auth.py"),
                "language_id": "python",
                "content": "x = 1\n",
                "diagnostics": [],
                "evaluation_source": "training",
                "training_card_id": leftover_card_id,
                "training_card_title": "Keep one auth check",
            },
        )
        assert evaluate.status_code == 200
        memory = client.get(f"/memory/summary?workspace_id={workspace_id}").json()["memory"]
        fsrs_states = (memory.get("workspace") or {}).get("latest_training_fsrs_states") or {}
        assert leftover_card_id not in fsrs_states


def test_turn_chips_do_not_mint_second_card_from_leftover_title(tmp_path: Path) -> None:
    from tests.test_router_stream_scenarios import mark_provider_capabilities_verified

    workspace_id = "ws-leftover-card-no-mint"
    urgent = (
        "I am stuck and blocked and overwhelmed and frustrated. "
        "This is not working, broken, error, struggling!! "
        "Generate a training card for Keep one auth check."
    )
    with (
        _client(tmp_path) as client,
        patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value="Stay on one slice.")),
    ):
        start = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": workspace_id,
                "profile": {
                    "long_term_goal": "Ship one auth check",
                    "weekly_hours": 2,
                    "teaching_style": "guided",
                    "answer_policy": "guided",
                },
            },
        )
        assert start.status_code == 200
        session_id = start.json()["session_id"]
        runtime = client.app.state.runtime
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_id)
        before = {card.card_id for card in runtime.memory_service.get_cards(workspace_id)}
        assert leftover_card_id in before

        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": urgent,
                "response_language": "en-US",
            },
        )
        assert turn.status_code == 200, turn.text
        after = {card.card_id for card in runtime.memory_service.get_cards(workspace_id)}
        assert after == before
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""


def test_explicit_generate_card_binds_new_live_id_without_clobber_on_failure(
    tmp_path: Path,
) -> None:
    workspace_id = "ws-leftover-card-explicit-bind"
    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        runtime = client.app.state.runtime
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_id)
        cards_before = {
            card.card_id: card.title
            for card in runtime.memory_service.get_cards(workspace_id)
        }

        # Failure path must not wipe leftover storage (patch class: route builds a fresh generator).
        with patch(
            "app.training.card_generator.CardGenerationService.generate_card",
            side_effect=RuntimeError("provider down"),
        ):
            failed = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "Add a token expiry test",
                    "target_skill": "token expiry",
                    "why_now": "Explicit leftover binder.",
                },
            )
        assert failed.status_code >= 400, failed.text
        still = {
            card.card_id: card.title
            for card in runtime.memory_service.get_cards(workspace_id)
        }
        assert still == cards_before
        assert leftover_card_id in still

        async def fake_chat(*_args: object, **_kwargs: object) -> str:
            return _model_card_payload()

        with patch.object(ProviderService, "chat_completion", new=fake_chat):
            minted = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "Add a token expiry test",
                    "target_skill": "token expiry",
                    "why_now": "Explicit leftover binder.",
                },
            )
        assert minted.status_code == 200, minted.text
        body = minted.json()
        new_id = str((body.get("card") or {}).get("card_id") or "").strip()
        assert new_id
        assert new_id != leftover_card_id
        routing = body.get("active_routing") or {}
        assert str(routing.get("selected_card_id") or "").strip() == new_id
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == new_id
        assert runtime.memory_service.get_card(workspace_id, leftover_card_id) is not None


@pytest.mark.asyncio
async def test_react_generate_training_card_denies_leftover_not_live(tmp_path: Path) -> None:
    from app.db.repository import TrainerRepository
    from app.memory.service import MemoryService
    from app.training.card_generator import CardGenerationService

    workspace_id = "ws-tool-leftover-deny"
    leftover_step = "Keep one auth check"
    repository = TrainerRepository(tmp_path / "trainer-tool-leftover-deny.db")
    memory_service = MemoryService(repository)
    plan = LearningPlan(
        id="plan-formal-old",
        title="Keep the current stage",
        current_step=leftover_step,
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
    repository.save_plan(workspace_id, plan)
    memory_service.upsert_card(
        workspace_id,
        TrainingCardCandidateSnapshot(
            card_id="card-leftover-tool",
            card_type="practice",
            title=leftover_step,
            status="active",
            focus_area="auth",
            target_skill="auth",
        ),
    )
    memory_service.update_workspace_state(
        workspace_id,
        **{
            PLAN_RUNTIME_KEY: {
                "workspace_id": workspace_id,
                "plan_id": "plan-runtime-other",
                "current_step": leftover_step,
                "status": "in_progress",
            },
            "selected_card_id": "card-leftover-tool",
            "selected_card_title": leftover_step,
        },
    )
    runtime = SimpleNamespace(
        memory_service=memory_service,
        repository=repository,
        card_generation_service=CardGenerationService(),
        card_router_service=None,
    )
    context = ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id="session-tool-leftover-deny",
        response_language="en-US",
        extra={"allow_coach_only_tools": True, "explicit_training_card_request": True},
    )
    result = await build_default_tool_registry().invoke(
        context,
        "generate_training_card",
        {
            "focus_area": leftover_step,
            "target_skill": leftover_step,
            "card_type": "practice",
            "why_now": f"{leftover_step} is the leftover training card.",
        },
    )
    assert result["ok"] is False
    assert result["error"] in {
        "leftover_not_live_card",
        "live_training_card_required",
        "explicit_http_generate_card_required",
    }
    assert [card.card_id for card in memory_service.get_cards(workspace_id)] == [
        "card-leftover-tool"
    ]


def test_stream_generate_card_failure_does_not_clobber_leftover(tmp_path: Path) -> None:
    """HTTP stream mint path is POST /training/generate-card/stream only.

    /turn/stream and /session/message/stream do not call training_generate_and_route_card
    as an HTTP generate-card binder (ReAct tool path is separate and leftover-denied).
    On stream failure: leftover stored card stays; failed→acked + failure complete (no remint);
    selected_card_id is not overwritten with a fake live id.
    """

    workspace_id = "ws-leftover-card-stream-fail"

    async def fake_stream(*_args: object, **_kwargs: object):
        raise RuntimeError("provider down for stream generate-card")
        yield "unreachable"

    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        runtime = client.app.state.runtime
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_id)
        cards_before = {
            card.card_id: card.title
            for card in runtime.memory_service.get_cards(workspace_id)
        }
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""

        with patch.object(ProviderService, "chat_completion_stream", new=fake_stream):
            response = client.post(
                "/training/generate-card/stream",
                json={
                    "workspace_id": workspace_id,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "Add a token expiry test",
                    "target_skill": "token expiry",
                    "response_language": "en-US",
                },
            )

        assert response.status_code == 200, response.text
        assert "event: error" in response.text
        assert "event: complete" in response.text
        assert '"phase": "failed"' in response.text
        assert '"phase": "acked"' in response.text
        still = {
            card.card_id: card.title
            for card in runtime.memory_service.get_cards(workspace_id)
        }
        assert still == cards_before
        assert leftover_card_id in still
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""
        workspace = runtime.memory_service.snapshot(workspace_id).workspace or {}
        runtime_overlay = workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime") or {}
        assert str(runtime_overlay.get("selected_card_id") or "").strip() in {"", leftover_card_id}
        # Leftover painted workspace selection must not become live after stream fail.
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""


def test_advance_verify_stamps_live_selected_card_id_only(tmp_path: Path) -> None:
    """Verify advance preserves live selected_card_id; never title invent; isolate workspaces."""

    from app.core.models import ActiveCardSelectionResult

    workspace_a = "ws-advance-stamp-a"
    workspace_b = "ws-advance-stamp-b"
    with _client(tmp_path) as client:
        for workspace_id in (workspace_a, workspace_b):
            started = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": workspace_id},
            )
            assert started.status_code == 200
        runtime = client.app.state.runtime

        plan_a = LearningPlan(
            id="plan-live-a",
            title="Live plan A",
            current_step="Keep one auth check",
            why_now="Live why A",
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
        plan_a_advanced = plan_a.model_copy(
            update={"current_step": "Add a token expiry test"}
        )
        runtime.repository.save_plan(workspace_a, plan_a)
        runtime.memory_service.update_workspace_state(
            workspace_a,
            **{
                PLAN_RUNTIME_KEY: {
                    "workspace_id": workspace_a,
                    "plan_id": "plan-live-a",
                    "current_step": "Keep one auth check",
                    "why_now": "Live why A",
                    "resume_state": "in_progress",
                }
            },
        )
        live_card = TrainingCardCandidateSnapshot(
            card_id="card-live-a",
            card_type="practice",
            title="Keep one auth check",
            status="active",
            focus_area="session tokens",
            target_skill="auth expiry",
            why_now="Live card under A.",
        )
        runtime.memory_service.upsert_card(workspace_a, live_card)
        runtime.memory_service.persist_active_card_selection(
            workspace_a,
            ActiveCardSelectionResult(
                selected_card=live_card,
                selected_card_id=live_card.card_id,
                why_this_card="Live card stamp.",
                next_after_completion="Verify.",
                fallback_action="Return to coach.",
                candidate_count=1,
                eligible_count=1,
            ),
        )
        assert runtime.memory_service.live_selected_training_card_id(workspace_a) == "card-live-a"

        # Workspace B: leftover title dumped into selected_card_id must not become live,
        # and must not inherit A's live card id after A advances.
        leftover_step = "Keep the other login path"
        runtime.memory_service.update_workspace_state(
            workspace_b,
            **{
                PLAN_RUNTIME_KEY: {
                    "workspace_id": workspace_b,
                    "plan_id": "plan-other-b",
                    "current_step": leftover_step,
                    "selected_card_id": leftover_step,
                    "why_now": "Leftover B",
                    "resume_state": "in_progress",
                },
                "selected_card_id": leftover_step,
            },
        )
        before_b = runtime.memory_service.recover_workspace_facts(workspace_b)[PLAN_RUNTIME_KEY]

        synced = runtime.memory_service.persist_plan_runtime_advance_after_verify(
            workspace_a,
            plan_a_advanced,
            request_id="plan-live-a",
        )
        assert synced is not None
        assert str(synced.get("selected_card_id") or "").strip() == "card-live-a"
        assert str(synced.get("current_step") or "").strip() == "Add a token expiry test"
        assert runtime.memory_service.live_selected_training_card_id(workspace_a) == "card-live-a"

        after_b = runtime.memory_service.recover_workspace_facts(workspace_b)[PLAN_RUNTIME_KEY]
        assert after_b["current_step"] == before_b["current_step"]
        assert str(after_b.get("selected_card_id") or "").strip() != "card-live-a"
        assert runtime.memory_service.live_selected_training_card_id(workspace_b) == ""

        # Leftover-not-live A': title in selected_card_id cleared on advance.
        leftover_ws = "ws-advance-stamp-leftover"
        client.post(
            "/session/start",
            json={"workspace_id": leftover_ws, "workspace_name": leftover_ws},
        )
        leftover_plan = LearningPlan(
            id="plan-leftover-advance",
            title="Leftover formal",
            current_step=leftover_step,
            stages=[
                PlanStage(
                    id="stage-1",
                    title="Other",
                    goal="Keep other",
                    outcomes=["pass"],
                    status="active",
                )
            ],
        )
        runtime.repository.save_plan(leftover_ws, leftover_plan)
        runtime.memory_service.update_workspace_state(
            leftover_ws,
            **{
                PLAN_RUNTIME_KEY: {
                    "workspace_id": leftover_ws,
                    "plan_id": "plan-leftover-advance",
                    "current_step": leftover_step,
                    "selected_card_id": leftover_step,
                    "why_now": "Title dump is not a card id",
                    "resume_state": "in_progress",
                },
                "selected_card_id": leftover_step,
            },
        )
        advanced_leftover = leftover_plan.model_copy(
            update={"current_step": "Wire the other guard."}
        )
        cleared = runtime.memory_service.persist_plan_runtime_advance_after_verify(
            leftover_ws,
            advanced_leftover,
            request_id="plan-leftover-advance",
        )
        assert cleared is not None
        assert not str(cleared.get("selected_card_id") or "").strip()
        assert str(cleared.get("current_step") or "").strip() == "Wire the other guard."
        assert leftover_step not in str(cleared.get("selected_card_id") or "")
        assert runtime.memory_service.live_selected_training_card_id(leftover_ws) == ""


def test_evidence_adopt_http_keeps_live_selected_card_id_only(tmp_path: Path) -> None:
    """HTTP /evidence/adopt: live id kept; leftover title not copied; no second plan/card mint."""

    from app.core.models import ActiveCardSelectionResult, EvidenceItem

    workspace_live = "ws-adopt-http-live"
    workspace_leftover = "ws-adopt-http-leftover"
    next_step = "Add a token expiry test"
    leftover_step = "Keep the other login path"

    with _client(tmp_path) as client:
        for workspace_id in (workspace_live, workspace_leftover):
            started = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": workspace_id},
            )
            assert started.status_code == 200
        runtime = client.app.state.runtime
        memory = runtime.memory_service

        live_card = TrainingCardCandidateSnapshot(
            card_id="card-adopt-live-a",
            card_type="practice",
            title="Keep one auth check",
            status="active",
            focus_area="session tokens",
            target_skill="auth expiry",
            why_now="Live card under adopt HTTP.",
            next_after_completion=next_step,
        )
        memory.upsert_card(workspace_live, live_card)
        memory.persist_active_card_selection(
            workspace_live,
            ActiveCardSelectionResult(
                selected_card=live_card,
                selected_card_id=live_card.card_id,
                why_this_card="Live adopt stamp.",
                next_after_completion=next_step,
                fallback_action="Return to coach.",
                candidate_count=1,
                eligible_count=1,
            ),
        )
        memory.persist_plan_runtime_recovery(
            workspace_live,
            plan_runtime={
                "current_step": "Keep one auth check",
                "why_now": "Expired tokens still leak the session.",
                "next_after_current": next_step,
                "verify_method": ["Run the focused auth check"],
                "resume_state": "waiting",
                "selected_card_id": live_card.card_id,
            },
            request_id="adopt-http-live-waiting",
        )
        assert memory.live_selected_training_card_id(workspace_live) == live_card.card_id
        before_live_cards = {card.card_id for card in memory.get_cards(workspace_live)}
        assert memory.repository.get_latest_plan(workspace_live) is None

        live_item = memory.enqueue_evidence(
            workspace_live,
            EvidenceItem(summary="Auth check passed", outcome="pass"),
            verified=True,
            verification_source="focused_auth_check",
        )
        adopt_live = client.post(
            "/evidence/adopt",
            json={"workspace_id": workspace_live, "evidence_id": live_item.id},
        )
        assert adopt_live.status_code == 200, adopt_live.text
        assert adopt_live.json()["plan_updated"] is False

        advanced = memory.recover_workspace_facts(workspace_live)[PLAN_RUNTIME_KEY]
        assert advanced["resume_state"] == "in_progress"
        assert advanced["current_step"] == next_step
        assert str(advanced.get("selected_card_id") or "").strip() == live_card.card_id
        assert memory.live_selected_training_card_id(workspace_live) == live_card.card_id
        assert memory.repository.get_latest_plan(workspace_live) is None
        after_live_cards = {card.card_id for card in memory.get_cards(workspace_live)}
        assert after_live_cards == before_live_cards
        assert leftover_step not in str(advanced.get("selected_card_id") or "")
        assert advanced["current_step"] not in str(advanced.get("selected_card_id") or "")

        # Leftover-not-live: title dumped into selected_card_id must not resurrect as live.
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_leftover)
        memory.update_workspace_state(
            workspace_leftover,
            **{
                PLAN_RUNTIME_KEY: {
                    "workspace_id": workspace_leftover,
                    "plan_id": "plan-runtime-other",
                    "current_step": leftover_step,
                    "why_now": "Leftover waiting runtime",
                    "next_after_current": "Wire the other guard.",
                    "resume_state": "waiting",
                    "selected_card_id": leftover_step,
                },
                "selected_card_id": leftover_card_id,
                "selected_card_title": leftover_step,
            },
        )
        assert memory.live_selected_training_card_id(workspace_leftover) == ""
        before_leftover_cards = {card.card_id for card in memory.get_cards(workspace_leftover)}
        leftover_plan_before = memory.repository.get_latest_plan(workspace_leftover)
        assert leftover_plan_before is not None
        leftover_plan_id = leftover_plan_before.id

        leftover_item = memory.enqueue_evidence(
            workspace_leftover,
            EvidenceItem(summary="Other path passed", outcome="pass"),
            verified=True,
            verification_source="other_login_check",
        )
        adopt_leftover = client.post(
            "/evidence/adopt",
            json={"workspace_id": workspace_leftover, "evidence_id": leftover_item.id},
        )
        assert adopt_leftover.status_code == 200, adopt_leftover.text

        after_leftover = memory.recover_workspace_facts(workspace_leftover)[PLAN_RUNTIME_KEY]
        assert after_leftover["resume_state"] == "in_progress"
        assert after_leftover["current_step"] == "Wire the other guard."
        assert not str(after_leftover.get("selected_card_id") or "").strip()
        assert leftover_step not in str(after_leftover.get("selected_card_id") or "")
        assert leftover_card_id not in str(after_leftover.get("selected_card_id") or "")
        assert memory.live_selected_training_card_id(workspace_leftover) == ""
        assert memory.get_card(workspace_leftover, leftover_card_id) is not None
        after_leftover_cards = {card.card_id for card in memory.get_cards(workspace_leftover)}
        assert after_leftover_cards == before_leftover_cards
        leftover_plan_after = memory.repository.get_latest_plan(workspace_leftover)
        assert leftover_plan_after is not None
        assert leftover_plan_after.id == leftover_plan_id
        # Live workspace must stay isolated from leftover adopt.
        assert memory.live_selected_training_card_id(workspace_live) == live_card.card_id


def _assert_snapshot_has_no_live_invent(body: dict, *, memory_service: object, workspace_id: str) -> None:
    """Fail-closed: coach turn must not mint card / TaskSpec / LearningPlan when none live."""
    snapshot = body.get("snapshot") or body
    mem = snapshot.get("memory") or {}
    workspace = mem.get("workspace") or {}
    routing = mem.get("active_training_card_routing") or mem.get("activeTrainingCardRouting") or {}
    selected = str(
        workspace.get("selected_card_id")
        or workspace.get("selectedCardId")
        or routing.get("selected_card_id")
        or routing.get("selectedCardId")
        or ""
    ).strip()
    assert not selected
    assert memory_service.live_selected_training_card_id(workspace_id) == ""
    assert list(memory_service.get_cards(workspace_id)) == []
    assert memory_service.repository.get_latest_plan(workspace_id) is None
    plan = snapshot.get("plan") or {}
    assert plan in (None, {}) or not str(plan.get("id") or plan.get("plan_id") or "").strip()
    task = snapshot.get("current_task") or snapshot.get("currentTask") or {}
    assert task in (None, {}) or not str(task.get("id") or task.get("title") or "").strip()


def test_training_return_live_card_does_not_paint_foreign_workspace(tmp_path: Path) -> None:
    """Return on A with live selected_card_id must not paint that card live on B.

    Also fail-closed: B `/turn` + `/turn/stream` + `/session/message` +
    `/session/message/stream` with no live plan/card must not mint any card /
    TaskSpec / LearningPlan — including chat "Create a practice card". Explicit
    `/plan/generate` and `/training/generate-card` on B still bind NEW ids.
    """

    from app.core.models import ActiveCardSelectionResult
    from tests.test_router_stream_scenarios import mark_provider_capabilities_verified

    workspace_a = "ws-return-live-a"
    workspace_b = "ws-return-empty-b"
    live_card_id = "card-return-live-a"

    with (
        _client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Stay with the first-look next. Do not invent."),
        ),
    ):
        for workspace_id in (workspace_a, workspace_b):
            started = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": workspace_id},
            )
            assert started.status_code == 200
        runtime = client.app.state.runtime
        memory = runtime.memory_service
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

        live_plan_id = "plan-return-live-a"
        live_plan_title = "Keep the current stage"
        live_step = "Keep one auth check"
        leftover_library_title = "Keep the leftover A library notes"
        live_plan = LearningPlan(
            id=live_plan_id,
            title=live_plan_title,
            current_step=live_step,
            why_now="Expired tokens still leak the session.",
            next_after_current="Add a token expiry test",
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
        memory.repository.save_plan(workspace_a, live_plan)
        runtime.repository.save_resource(
            workspace_a,
            ResourceRecord(
                id="resource-return-live-a",
                kind="markdown",
                name=leftover_library_title,
                source="notes.md",
                summary="A leftover library item on A",
            ),
        )
        live_card = TrainingCardCandidateSnapshot(
            card_id=live_card_id,
            card_type="practice",
            title=live_step,
            status="active",
            focus_area="session tokens",
            target_skill="auth expiry",
            next_after_completion="Add a token expiry test",
        )
        memory.upsert_card(workspace_a, live_card)
        memory.persist_active_card_selection(
            workspace_a,
            ActiveCardSelectionResult(
                selected_card=live_card,
                selected_card_id=live_card.card_id,
                why_this_card="Live return card.",
                next_after_completion="Add a token expiry test",
                fallback_action="Return to coach.",
                candidate_count=1,
                eligible_count=1,
            ),
        )
        memory.persist_plan_runtime_recovery(
            workspace_a,
            plan_runtime={
                "plan_id": live_plan_id,
                "current_step": live_step,
                "why_now": "Expired tokens still leak the session.",
                "next_after_current": "Add a token expiry test",
                "resume_state": "in_progress",
                "selected_card_id": live_card_id,
            },
            request_id="return-live-a-runtime",
        )
        assert memory.live_selected_training_card_id(workspace_a) == live_card_id
        assert memory.repository.get_latest_plan(workspace_a) is not None
        assert any(
            item.name == leftover_library_title
            for item in memory.snapshot(workspace_a).resources
        )

        seeded = memory.record_training_practice_evaluation_result(
            workspace_id=workspace_a,
            card_id=live_card_id,
            passed=True,
            summary="Focused auth check passed.",
            next_step="Return the verified result.",
            focus_area=live_card.focus_area,
            evidence_source="ide_current_file",
            verified_by_evaluator=True,
        )
        handoff_id = seeded["latest_training_handoff"]["handoff_id"]
        reflect = client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace_a,
                "card_id": live_card_id,
                "handoff_id": handoff_id,
                "reflection": "The focused check proved expired tokens must fail closed.",
            },
        )
        assert reflect.status_code == 200, reflect.text
        returned = client.post(
            "/training/return",
            json={
                "workspace_id": workspace_a,
                "card_id": live_card_id,
                "handoff_id": handoff_id,
            },
        )
        assert returned.status_code == 200, returned.text
        assert memory.live_selected_training_card_id(workspace_a) == live_card_id

        # B start: distinct workspace must stay empty/honest — no A's live card.
        start_b = client.post(
            "/session/start",
            json={"workspace_id": workspace_b, "workspace_name": workspace_b},
        )
        assert start_b.status_code == 200
        session_b = start_b.json().get("session_id") or start_b.json().get("sessionId")
        assert session_b

        # Five-view first-screen: B /session/start must stay empty/honest.
        start_body = start_b.json()
        start_plan = start_body.get("plan") or {}
        assert start_plan in (None, {}) or not str(
            start_plan.get("id") or start_plan.get("plan_id") or ""
        ).strip()
        assert live_plan_id not in str(start_plan)
        assert live_plan_title not in str(start_plan)
        assert live_step not in str(start_plan)
        start_resources = (
            (start_body.get("memory") or {}).get("resources")
            or start_body.get("resources")
            or []
        )
        assert leftover_library_title not in str(start_resources)
        start_actions = [
            str(item.get("action") or "")
            for item in (
                start_body.get("suggested_actions")
                or start_body.get("suggestedActions")
                or []
            )
        ]
        assert "plan" not in start_actions
        assert "task" not in start_actions
        assert "next_task" not in start_actions
        assert "card" not in start_actions

        summary_b = client.get(
            f"/memory/summary?workspace_id={workspace_b}&session_id={session_b}"
        )
        assert summary_b.status_code == 200
        summary_payload = summary_b.json()
        body_b = summary_payload["memory"]
        workspace_payload = body_b.get("workspace") or {}
        painted = str(
            workspace_payload.get("selected_card_id")
            or workspace_payload.get("selectedCardId")
            or ""
        ).strip()
        assert painted != live_card_id
        assert not painted
        assert memory.live_selected_training_card_id(workspace_b) == ""
        assert memory.get_card(workspace_b, live_card_id) is None
        assert memory.repository.get_latest_plan(workspace_b) is None
        summary_plan = summary_payload.get("plan") or {}
        assert summary_plan in (None, {}) or not str(
            summary_plan.get("id") or summary_plan.get("plan_id") or ""
        ).strip()
        assert leftover_library_title not in str(
            body_b.get("resources") or summary_payload.get("resources") or []
        )
        summary_actions = [
            str(item.get("action") or "")
            for item in (
                summary_payload.get("suggested_actions")
                or summary_payload.get("suggestedActions")
                or []
            )
        ]
        assert "plan" not in summary_actions
        assert "task" not in summary_actions
        assert "next_task" not in summary_actions
        assert "card" not in summary_actions
        foreign_runtime = (
            workspace_payload.get("latest_plan_runtime")
            or workspace_payload.get("latestPlanRuntime")
            or {}
        )
        assert str(
            foreign_runtime.get("selected_card_id")
            or foreign_runtime.get("selectedCardId")
            or ""
        ).strip() != live_card_id
        assert str(
            foreign_runtime.get("plan_id") or foreign_runtime.get("planId") or ""
        ).strip() != live_plan_id

        # B coach turns must not invent ANY card/plan/task (not merely reject A's id).
        turn_b = client.post(
            "/turn",
            json={
                "session_id": session_b,
                "workspace_id": workspace_b,
                "intent": "coach",
                "message": "What should I do next?",
                "response_language": "en-US",
            },
        )
        assert turn_b.status_code == 200, turn_b.text
        turn_body = turn_b.json()
        _assert_snapshot_has_no_live_invent(turn_body, memory_service=memory, workspace_id=workspace_b)
        turn_snapshot = turn_body.get("snapshot") or turn_body
        turn_resources = (
            (turn_snapshot.get("memory") or {}).get("resources")
            or turn_snapshot.get("resources")
            or []
        )
        assert leftover_library_title not in str(turn_resources)
        turn_actions = [
            str(item.get("action") or "")
            for item in (
                turn_snapshot.get("suggested_actions")
                or turn_snapshot.get("suggestedActions")
                or turn_body.get("suggested_actions")
                or turn_body.get("suggestedActions")
                or []
            )
        ]
        assert "plan" not in turn_actions
        assert "task" not in turn_actions
        assert "next_task" not in turn_actions
        assert "card" not in turn_actions
        assert memory.get_card(workspace_b, live_card_id) is None
        after_b = memory.recover_workspace_facts(workspace_b).get(PLAN_RUNTIME_KEY) or {}
        assert str(after_b.get("selected_card_id") or "").strip() != live_card_id
        assert memory.live_selected_training_card_id(workspace_a) == live_card_id

        # Chat-explicit "Create a practice card" on empty B must still not mint.
        turn_b_card = client.post(
            "/turn",
            json={
                "session_id": session_b,
                "workspace_id": workspace_b,
                "intent": "coach",
                "message": "Create a practice card for debugging a Python traceback in VS Code.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert turn_b_card.status_code == 200, turn_b_card.text
        _assert_snapshot_has_no_live_invent(
            turn_b_card.json(),
            memory_service=memory,
            workspace_id=workspace_b,
        )

        # Last unproven path: /turn/stream after A Return → empty B.
        from tests.test_router_stream_scenarios import completed_stream_response

        async def _fake_stream(*_args: object, **_kwargs: object):
            yield "Stay with the first-look next. Do not invent."

        with patch.object(ProviderService, "coaching_reply_stream", new=_fake_stream):
            stream_b = client.post(
                "/turn/stream",
                json={
                    "session_id": session_b,
                    "workspace_id": workspace_b,
                    "intent": "coach",
                    "message": "Create a practice card for auth expiry checks.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )
        assert stream_b.status_code == 200, stream_b.text
        stream_body = completed_stream_response(stream_b.text)
        _assert_snapshot_has_no_live_invent(
            stream_body,
            memory_service=memory,
            workspace_id=workspace_b,
        )
        assert memory.live_selected_training_card_id(workspace_b) == ""
        assert list(memory.get_cards(workspace_b)) == []

        session_b_msg = client.post(
            "/session/message",
            json={
                "session_id": session_b,
                "workspace_id": workspace_b,
                "message": "What should I do next?",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert session_b_msg.status_code == 200, session_b_msg.text
        _assert_snapshot_has_no_live_invent(
            session_b_msg.json(),
            memory_service=memory,
            workspace_id=workspace_b,
        )

        # Same fail-closed helpers as /turn/stream: empty B chat must not mint.
        with patch.object(ProviderService, "coaching_reply_stream", new=_fake_stream):
            session_b_stream = client.post(
                "/session/message/stream",
                json={
                    "session_id": session_b,
                    "workspace_id": workspace_b,
                    "message": "Create a practice card for debugging a Python traceback in VS Code.",
                    "response_language": "en-US",
                    "use_agent_loop": False,
                },
            )
        assert session_b_stream.status_code == 200, session_b_stream.text
        session_stream_body = completed_stream_response(session_b_stream.text)
        _assert_snapshot_has_no_live_invent(
            session_stream_body,
            memory_service=memory,
            workspace_id=workspace_b,
        )
        assert memory.live_selected_training_card_id(workspace_b) == ""
        assert list(memory.get_cards(workspace_b)) == []

        # Explicit HTTP mint paths on empty B still bind NEW identities.
        plan_resp = client.post(
            "/plan/generate",
            json={
                "session_id": session_b,
                "workspace_id": workspace_b,
                "objectives": ["Ship one auth check on B"],
            },
        )
        assert plan_resp.status_code == 200, plan_resp.text
        plan_body = plan_resp.json()
        plan = plan_body.get("plan") or plan_body
        new_plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
        assert new_plan_id
        assert new_plan_id != live_card_id
        latest_plan = memory.repository.get_latest_plan(workspace_b)
        assert latest_plan is not None
        assert latest_plan.id == new_plan_id

        async def fake_card_chat(*_args: object, **_kwargs: object) -> str:
            return _model_card_payload()

        with patch.object(ProviderService, "chat_completion", new=fake_card_chat):
            card_resp = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_b,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "auth check on B",
                    "context_hint": "Explicit generate on empty B after A return.",
                    "response_language": "en-US",
                },
            )
        assert card_resp.status_code == 200, card_resp.text
        card_payload = card_resp.json()
        assert card_payload.get("success") is True
        new_card = card_payload.get("card") or {}
        new_card_id = str(new_card.get("card_id") or new_card.get("id") or "").strip()
        assert new_card_id
        assert new_card_id != live_card_id
        routing = card_payload.get("active_routing") or {}
        assert str(routing.get("selected_card_id") or "").strip() == new_card_id
        assert memory.live_selected_training_card_id(workspace_b) == new_card_id
        assert memory.get_card(workspace_b, live_card_id) is None
        assert memory.live_selected_training_card_id(workspace_a) == live_card_id


def test_live_card_chat_create_practice_does_not_clobber(tmp_path: Path) -> None:
    """Workspace with LIVE selected_card_id: chat "Create a practice card" keeps it.

    `/turn` (+ `/turn/stream`) must not mint a second card or clobber selected_card_id.
    Same fail-closed helpers as empty-B deny; ReAct handler also returns
    live_card_already_selected. Explicit POST /training/generate-card may replace.
    """
    from app.core.models import ActiveCardSelectionResult
    from tests.test_router_stream_scenarios import (
        completed_stream_response,
        mark_provider_capabilities_verified,
    )

    workspace_id = "ws-live-no-clobber"
    live_card_id = "card-live-no-clobber"

    async def _fake_stream(*_args: object, **_kwargs: object):
        yield "Keep the live card. Do not invent a second one."

    with (
        _client(tmp_path) as client,
        patch.object(
            ProviderService,
            "coaching_reply",
            new=AsyncMock(return_value="Keep the live card. Do not invent a second one."),
        ),
        patch.object(ProviderService, "coaching_reply_stream", new=_fake_stream),
    ):
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert started.status_code == 200
        session_id = str(started.json()["session_id"])
        runtime = client.app.state.runtime
        memory = runtime.memory_service
        mark_provider_capabilities_verified(
            runtime,
            runtime.provider_config,
            "sk-test-not-a-real-key-aaaaaaaa",
            tools=False,
        )

        live_card = TrainingCardCandidateSnapshot(
            card_id=live_card_id,
            card_type="practice",
            title="Keep one auth check",
            status="active",
            focus_area="session tokens",
            target_skill="auth expiry",
            next_after_completion="Add a token expiry test",
        )
        memory.upsert_card(workspace_id, live_card)
        memory.persist_active_card_selection(
            workspace_id,
            ActiveCardSelectionResult(
                selected_card=live_card,
                selected_card_id=live_card.card_id,
                why_this_card="Live card under chat pressure.",
                next_after_completion="Add a token expiry test",
                fallback_action="Stay on the live card.",
                candidate_count=1,
                eligible_count=1,
            ),
        )
        memory.persist_plan_runtime_recovery(
            workspace_id,
            plan_runtime={
                "current_step": "Keep one auth check",
                "why_now": "Expired tokens still leak the session.",
                "next_after_current": "Add a token expiry test",
                "resume_state": "in_progress",
                "selected_card_id": live_card_id,
            },
            request_id="live-no-clobber-runtime",
        )
        assert memory.live_selected_training_card_id(workspace_id) == live_card_id
        before_ids = {card.card_id for card in memory.get_cards(workspace_id)}

        turn = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Create a practice card for debugging a Python traceback in VS Code.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert turn.status_code == 200, turn.text
        assert memory.live_selected_training_card_id(workspace_id) == live_card_id
        assert {card.card_id for card in memory.get_cards(workspace_id)} == before_ids
        after_runtime = memory.recover_workspace_facts(workspace_id).get(PLAN_RUNTIME_KEY) or {}
        assert str(after_runtime.get("selected_card_id") or "").strip() == live_card_id

        stream = client.post(
            "/turn/stream",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "Create a practice card for auth expiry checks.",
                "response_language": "en-US",
                "use_agent_loop": False,
            },
        )
        assert stream.status_code == 200, stream.text
        _ = completed_stream_response(stream.text)
        assert memory.live_selected_training_card_id(workspace_id) == live_card_id
        assert {card.card_id for card in memory.get_cards(workspace_id)} == before_ids
        after_stream = memory.recover_workspace_facts(workspace_id).get(PLAN_RUNTIME_KEY) or {}
        assert str(after_stream.get("selected_card_id") or "").strip() == live_card_id


def test_leftover_not_live_card_status_does_not_skip_or_bind(tmp_path: Path) -> None:
    workspace_id = "ws-leftover-card-status-skip"
    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        runtime = client.app.state.runtime
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_id)
        leftover_step = "Keep one auth check"
        before_ids = {card.card_id for card in runtime.memory_service.get_cards(workspace_id)}
        leftover = runtime.memory_service.get_card(workspace_id, leftover_card_id)
        assert leftover is not None
        assert leftover.status == "active"
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""

        skipped = client.post(
            "/training/card-status",
            json={
                "workspace_id": workspace_id,
                "card_id": leftover_card_id,
                "new_status": "skipped",
                "reason": "Learner skipped",
            },
        )
        assert skipped.status_code == 409
        assert "leftover-not-live" in skipped.json()["detail"]
        assert "sk-" not in skipped.json()["detail"].lower()

        graded = client.post(
            "/training/card-status",
            json={
                "workspace_id": workspace_id,
                "card_id": leftover_card_id,
                "new_status": "reviewed",
                "reason": "Self-grade: good",
            },
        )
        assert graded.status_code == 409
        assert "leftover-not-live" in graded.json()["detail"]

        titled = client.post(
            "/training/card-status",
            json={
                "workspace_id": workspace_id,
                "card_id": leftover_step,
                "new_status": "skipped",
                "reason": "Title is not identity",
            },
        )
        assert titled.status_code == 409
        assert "leftover-not-live" in titled.json()["detail"]

        after = runtime.memory_service.get_card(workspace_id, leftover_card_id)
        assert after is not None
        assert after.status == "active"
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""
        assert {card.card_id for card in runtime.memory_service.get_cards(workspace_id)} == before_ids
        overlay = runtime.memory_service.recover_workspace_facts(workspace_id).get(PLAN_RUNTIME_KEY) or {}
        assert str(overlay.get("selected_card_id") or "").strip() in {"", leftover_card_id}
        assert leftover_card_id not in str(
            runtime.memory_service.live_selected_training_card_id(workspace_id)
        )


def test_live_selected_card_status_skip_replays_request_id(tmp_path: Path) -> None:
    workspace_id = "ws-live-card-status-skip"
    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        runtime = client.app.state.runtime
        live_card_id = _seed_live_selected_card(runtime, workspace_id)
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == live_card_id
        request_id = "training-persistence-live-card-status-1"
        payload = {
            "workspace_id": workspace_id,
            "card_id": live_card_id,
            "new_status": "skipped",
            "reason": "Learner skipped",
            "request_id": request_id,
            "idempotency_key": request_id,
        }

        first = client.post("/training/card-status", json=payload)
        second = client.post("/training/card-status", json=payload)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["card"]["status"] == "skipped"
        assert second.json()["card"]["status"] == "skipped"
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == live_card_id
        ledger = [
            entry
            for entry in runtime.memory_service._card_ledger
            if entry.get("card_id") == live_card_id
            and entry.get("workspace_id") == workspace_id
            and entry.get("new_status") == "skipped"
        ]
        assert len(ledger) == 1


def test_workspace_b_cannot_skip_workspace_a_leftover_card_status(tmp_path: Path) -> None:
    workspace_a = "ws-leftover-card-status-a"
    workspace_b = "ws-leftover-card-status-b"
    with _client(tmp_path) as client:
        for workspace_id in (workspace_a, workspace_b):
            started = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": workspace_id},
            )
            assert started.status_code == 200
        runtime = client.app.state.runtime
        leftover_a = _seed_leftover_card_not_live(
            runtime,
            workspace_a,
            leftover_card_id="card-leftover-a",
            leftover_plan_id="plan-leftover-a",
            leftover_runtime_plan_id="plan-runtime-a-other",
        )
        leftover_b = _seed_leftover_card_not_live(
            runtime,
            workspace_b,
            leftover_card_id="card-leftover-b",
            leftover_step="Keep the other login path",
            leftover_plan_id="plan-leftover-b",
            leftover_runtime_plan_id="plan-runtime-b-other",
        )
        assert leftover_a != leftover_b
        assert runtime.memory_service.live_selected_training_card_id(workspace_a) == ""
        assert runtime.memory_service.live_selected_training_card_id(workspace_b) == ""

        foreign = client.post(
            "/training/card-status",
            json={
                "workspace_id": workspace_b,
                "card_id": leftover_a,
                "new_status": "skipped",
                "reason": "Workspace B must not skip A leftover",
            },
        )
        assert foreign.status_code == 409
        assert "leftover-not-live" in foreign.json()["detail"]

        card_a = runtime.memory_service.get_card(workspace_a, leftover_a)
        card_b = runtime.memory_service.get_card(workspace_b, leftover_b)
        assert card_a is not None and card_a.status == "active"
        assert card_b is not None and card_b.status == "active"
        assert runtime.memory_service.get_card(workspace_b, leftover_a) is None
        assert runtime.memory_service.live_selected_training_card_id(workspace_a) == ""
        assert runtime.memory_service.live_selected_training_card_id(workspace_b) == ""


def _seed_live_verified_handoff(runtime: object, workspace_id: str) -> tuple[str, str]:
    live_card_id = _seed_live_selected_card(runtime, workspace_id)
    workspace = runtime.memory_service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id=live_card_id,
        passed=True,
        summary="pytest tests/test_auth.py -k expiry: 1 passed",
        next_step="Record what the focused check proved.",
        focus_area="session tokens",
        evidence_source="test_runner",
        verified_by_evaluator=True,
    )
    handoff = workspace.get("latest_training_handoff") or {}
    return live_card_id, str(handoff.get("handoff_id") or "")


def test_leftover_not_live_reflect_return_does_not_bind(tmp_path: Path) -> None:
    workspace_id = "ws-leftover-reflect-return"
    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        runtime = client.app.state.runtime
        leftover_step = "Keep one auth check"
        leftover_card_id = _seed_leftover_card_not_live(runtime, workspace_id)
        leftover = runtime.memory_service.get_card(workspace_id, leftover_card_id)
        assert leftover is not None
        assert leftover.status == "active"
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""
        before_ids = {card.card_id for card in runtime.memory_service.get_cards(workspace_id)}
        before_handoff = (runtime.memory_service.snapshot(workspace_id).workspace or {}).get(
            "latest_training_handoff"
        )

        reflected = client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace_id,
                "card_id": leftover_card_id,
                "reflection": "Leftover dump must not reflect as live.",
            },
        )
        assert reflected.status_code == 409, reflected.text
        assert "leftover-not-live" in reflected.json()["detail"]
        assert "sk-" not in reflected.json()["detail"].lower()

        titled = client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace_id,
                "card_id": leftover_step,
                "reflection": "Title is not identity.",
            },
        )
        assert titled.status_code == 409
        assert "leftover-not-live" in titled.json()["detail"]

        returned = client.post(
            "/training/return",
            json={"workspace_id": workspace_id, "card_id": leftover_card_id},
        )
        assert returned.status_code == 409, returned.text
        assert "leftover-not-live" in returned.json()["detail"]

        after = runtime.memory_service.get_card(workspace_id, leftover_card_id)
        assert after is not None
        assert after.status == "active"
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == ""
        assert {card.card_id for card in runtime.memory_service.get_cards(workspace_id)} == before_ids
        after_handoff = (runtime.memory_service.snapshot(workspace_id).workspace or {}).get(
            "latest_training_handoff"
        )
        assert after_handoff == before_handoff


def test_live_selected_card_reflect_return_replays_request_id(tmp_path: Path) -> None:
    workspace_id = "ws-live-reflect-return"
    with _client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": workspace_id},
        )
        assert start.status_code == 200
        runtime = client.app.state.runtime
        live_card_id, handoff_id = _seed_live_verified_handoff(runtime, workspace_id)
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == live_card_id
        reflect_id = "training-persistence-live-reflect-1"
        reflect_payload = {
            "workspace_id": workspace_id,
            "card_id": live_card_id,
            "handoff_id": handoff_id,
            "reflection": "The focused check proved expired tokens must fail closed.",
            "request_id": reflect_id,
            "idempotency_key": reflect_id,
        }

        first_reflect = client.post("/training/reflect", json=reflect_payload)
        replay_reflect = client.post(
            "/training/reflect",
            json={
                **reflect_payload,
                "reflection": "A second mutation must not land.",
            },
        )
        assert first_reflect.status_code == 200, first_reflect.text
        assert replay_reflect.status_code == 200, replay_reflect.text
        first_handoff = first_reflect.json()["workspace"]["latest_training_handoff"]
        replay_handoff = replay_reflect.json()["workspace"]["latest_training_handoff"]
        assert first_handoff["learning_phase"] == "reflect"
        assert replay_handoff["learning_phase"] == "reflect"
        assert "fail closed" in str(replay_handoff.get("reflection") or "").lower()
        assert "second mutation" not in str(replay_handoff.get("reflection") or "").lower()
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == live_card_id

        return_id = "training-persistence-live-return-1"
        return_payload = {
            "workspace_id": workspace_id,
            "card_id": live_card_id,
            "handoff_id": handoff_id,
            "request_id": return_id,
            "idempotency_key": return_id,
        }
        first_return = client.post("/training/return", json=return_payload)
        replay_return = client.post("/training/return", json=return_payload)
        assert first_return.status_code == 200, first_return.text
        assert replay_return.status_code == 200, replay_return.text
        assert first_return.json()["workspace"]["latest_training_handoff"]["learning_phase"] == "return"
        assert replay_return.json()["workspace"]["latest_training_handoff"]["learning_phase"] == "return"
        assert first_return.json()["workspace"]["latest_training_handoff"]["status"] == "completed"
        assert replay_return.json()["workspace"]["latest_training_handoff"]["status"] == "completed"
        assert runtime.memory_service.live_selected_training_card_id(workspace_id) == live_card_id
        summary = client.get(f"/memory/summary?workspace_id={workspace_id}")
        assert summary.status_code == 200
        evidence = summary.json()["memory"]["evidence_queue"]["pending"]
        assert len(evidence) == 1
        assert evidence[0]["source_card_id"] == live_card_id


def test_workspace_b_cannot_reflect_or_return_workspace_a_leftover(tmp_path: Path) -> None:
    workspace_a = "ws-leftover-reflect-a"
    workspace_b = "ws-leftover-reflect-b"
    with _client(tmp_path) as client:
        for workspace_id in (workspace_a, workspace_b):
            started = client.post(
                "/session/start",
                json={"workspace_id": workspace_id, "workspace_name": workspace_id},
            )
            assert started.status_code == 200
        runtime = client.app.state.runtime
        leftover_a = _seed_leftover_card_not_live(
            runtime,
            workspace_a,
            leftover_card_id="card-leftover-reflect-a",
            leftover_plan_id="plan-leftover-reflect-a",
            leftover_runtime_plan_id="plan-runtime-reflect-a-other",
        )
        leftover_b = _seed_leftover_card_not_live(
            runtime,
            workspace_b,
            leftover_card_id="card-leftover-reflect-b",
            leftover_step="Keep the other login path",
            leftover_plan_id="plan-leftover-reflect-b",
            leftover_runtime_plan_id="plan-runtime-reflect-b-other",
        )
        assert leftover_a != leftover_b
        assert runtime.memory_service.live_selected_training_card_id(workspace_a) == ""
        assert runtime.memory_service.live_selected_training_card_id(workspace_b) == ""

        foreign_reflect = client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace_b,
                "card_id": leftover_a,
                "reflection": "Workspace B must not reflect A leftover.",
            },
        )
        foreign_return = client.post(
            "/training/return",
            json={"workspace_id": workspace_b, "card_id": leftover_a},
        )
        assert foreign_reflect.status_code == 409
        assert "leftover-not-live" in foreign_reflect.json()["detail"]
        assert foreign_return.status_code == 409
        assert "leftover-not-live" in foreign_return.json()["detail"]

        card_a = runtime.memory_service.get_card(workspace_a, leftover_a)
        card_b = runtime.memory_service.get_card(workspace_b, leftover_b)
        assert card_a is not None and card_a.status == "active"
        assert card_b is not None and card_b.status == "active"
        assert runtime.memory_service.get_card(workspace_b, leftover_a) is None
        assert runtime.memory_service.live_selected_training_card_id(workspace_a) == ""
        assert runtime.memory_service.live_selected_training_card_id(workspace_b) == ""
