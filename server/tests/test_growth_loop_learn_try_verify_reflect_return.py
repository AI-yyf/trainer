"""One class-human Learn→Try→Verify→Reflect→Return walk over real routers.

Not theater: understand without invent → explicit /plan/generate → explicit
/training/generate-card → evaluator-acked current-file verify (temp content) →
formal+runtime advance + FSRS for THAT live card → reflect/return → chips do
not mint TaskSpec/second plan; /session/message (+stream) stamps the same latch;
transferable stays blocked in one workspace until a distinct second root.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import (
    LearningPlan,
    PlanStage,
    ProviderConfig,
)
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.memory.workspace_recovery import leftover_formal_plan_is_live_for_fill


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer learn-try-verify-reflect-return",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-ltvrr.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


_PRACTICE_SOURCE = (
    "def require_fresh(token):\n"
    "    if not token:\n"
    "        raise ValueError('expired')\n"
    "    return token\n"
    "\n"
    "\n"
    "def test_require_fresh_rejects_empty() -> None:\n"
    "    try:\n"
    "        require_fresh('')\n"
    "    except ValueError:\n"
    "        pass\n"
    "    else:\n"
    "        raise AssertionError('empty token must fail')\n"
    "    assert require_fresh('tok') == 'tok'\n"
)


def _runtime(workspace: dict[str, Any]) -> dict[str, Any]:
    value = workspace.get("latest_plan_runtime") or workspace.get("latestPlanRuntime") or {}
    return value if isinstance(value, dict) else {}


def _card_ids(runtime: object, workspace_id: str) -> set[str]:
    memory = getattr(runtime, "memory_service", None)
    if memory is None:
        return set()
    return {
        str(getattr(card, "card_id", "") or "")
        for card in memory.get_cards(workspace_id)
        if str(getattr(card, "card_id", "") or "")
    }


def _seed_live_usable_provider(runtime: object, session_id: str) -> ProviderConfig:
    provider = ProviderConfig(
        name="test-openai-compatible",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
        capabilities={"chat": True, "tools": False, "streaming": True},
    )
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
    runtime.provider_service_cache.clear()
    seed_verified_capabilities(runtime, provider, "sk-test", tools=False)
    state = runtime.get_session(session_id)
    assert state is not None
    state.snapshot.provider = provider
    state.snapshot.sidecar_status = "ready"
    return provider


def _practice_model_card() -> str:
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


def _action_names(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("suggested_actions", "suggestedActions"):
        items = payload.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    names.append(str(item.get("action") or ""))
    return names


def test_class_human_learn_try_verify_reflect_return_closed_loop(tmp_path: Path) -> None:
    workspace_id = "ws-ltvrr-closed-loop"
    leftover_title = "Keep the leftover stage"
    leftover_step = "Keep one leftover auth check"
    project = tmp_path / "auth-expiry-lab"
    project.mkdir()
    practice = project / "practice_probe.py"
    practice.write_text(_PRACTICE_SOURCE, encoding="utf-8")
    settings = _settings(tmp_path / "data")
    app = create_app(settings)

    with TestClient(app) as client:
        runtime = app.state.runtime

        # 1) Understand — no invented plan/card
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Auth expiry lab",
                "workspace_path": str(project),
            },
        )
        assert started.status_code == 200, started.text
        start_body = started.json()
        session_id = str(start_body.get("session_id") or start_body.get("sessionId") or "")
        assert session_id
        start_memory = start_body.get("memory") or {}
        understanding = (
            start_memory.get("workspace_understanding")
            or start_memory.get("workspaceUnderstanding")
            or {}
        )
        assert understanding or start_memory.get("workspace") is not None
        assert runtime.repository.get_latest_plan(workspace_id) is None
        assert _card_ids(runtime, workspace_id) == set()
        assert not (start_body.get("current_task") or start_body.get("currentTask") or {}).get(
            "title"
        )
        assert "plan" not in _action_names(start_body)
        assert "task" not in _action_names(start_body)
        assert "next_task" not in _action_names(start_body)

        _seed_live_usable_provider(runtime, session_id)

        # Leftover stored, not live-bound via generate
        leftover = LearningPlan(
            id="plan-leftover-ltvrr",
            title=leftover_title,
            current_step=leftover_step,
            why_now="Keep the leftover why",
            next_after_current="Then review the leftover path",
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
        runtime.memory_service.repository.save_plan(workspace_id, leftover)

        # 2) Explicit /plan/generate binds live plan_id
        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "objectives": ["Ship token refresh auth"],
            },
        )
        assert generated.status_code == 200, generated.text
        gen_body = generated.json()
        plan = gen_body.get("plan") or gen_body
        plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
        step_before = str(plan.get("current_step") or plan.get("currentStep") or "").strip()
        assert plan_id
        assert plan_id != leftover.id
        assert step_before
        assert leftover_title not in str(plan.get("title") or "")
        assert leftover_step not in step_before
        live_runtime = _runtime((gen_body.get("memory") or {}).get("workspace") or {})
        assert str(live_runtime.get("plan_id") or live_runtime.get("planId") or "").strip() == plan_id

        # 3) Explicit training card generate — selectedCardId live
        async def fake_chat(*_args: object, **_kwargs: object) -> str:
            return _practice_model_card()

        with patch.object(ProviderService, "chat_completion", new=fake_chat):
            card_gen = client.post(
                "/training/generate-card",
                json={
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "source": "conversation_gap",
                    "card_type": "practice",
                    "focus_area": "token expiry",
                    "target_skill": "auth expiry",
                    "context_hint": "Practice fail-closed expiry under the live plan.",
                    "response_language": "en-US",
                },
            )
        assert card_gen.status_code == 200, card_gen.text
        card_payload = card_gen.json()
        card = card_payload.get("card") or {}
        card_id = str(card.get("card_id") or card.get("cardId") or "").strip()
        card_title = str(card.get("title") or "").strip()
        assert card_id
        routing = card_payload.get("active_routing") or card_payload.get("activeRouting") or {}
        selected = routing.get("selected_card") or routing.get("selectedCard") or {}
        selected_id = str(
            routing.get("selected_card_id")
            or routing.get("selectedCardId")
            or selected.get("card_id")
            or selected.get("cardId")
            or ""
        ).strip()
        assert selected_id == card_id
        assert leftover_step not in card_title
        cards_after_generate = _card_ids(runtime, workspace_id)
        assert card_id in cards_after_generate

        # 4) Try — current-file attempt without matching acceptance is not Verify
        probe = tmp_path / "tmp_verify_only.py"
        probe.write_text(_PRACTICE_SOURCE, encoding="utf-8")
        original_practice = practice.read_text(encoding="utf-8")
        try_evaluate = client.post(
            "/evaluate/current-file",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "file_path": str(probe),
                "language_id": "python",
                "content": probe.read_text(encoding="utf-8"),
                "diagnostics": [],
                "evaluation_source": "training",
                "training_card_id": card_id,
                "training_card_title": card_title or "Expiry practice",
                "expected_symbols": ["missing_expiry_guard"],
                "acceptance_criteria": ["Implement missing_expiry_guard for fail-closed expiry."],
            },
        )
        assert try_evaluate.status_code == 200, try_evaluate.text
        assert try_evaluate.json().get("passed") is not True
        try_memory = client.get(f"/memory/summary?workspace_id={workspace_id}").json()
        try_workspace = (try_memory.get("memory") or {}).get("workspace") or {}
        try_fsrs = try_workspace.get("latest_training_fsrs_states") or try_workspace.get(
            "latestTrainingFsrsStates"
        ) or {}
        assert card_id not in try_fsrs

        # Client-supplied learning signal is not evaluator ack and must not Verify.
        signal = client.post(
            "/learning/signal",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "concepts": ["auth expiry"],
                "outcome": "tests_passed",
                "summary": "I think the practice passed.",
                "focus_area": "auth expiry",
            },
        )
        assert signal.status_code == 200, signal.text
        signal_memory = client.get(f"/memory/summary?workspace_id={workspace_id}").json()
        signal_workspace = (signal_memory.get("memory") or {}).get("workspace") or {}
        signal_fsrs = signal_workspace.get("latest_training_fsrs_states") or signal_workspace.get(
            "latestTrainingFsrsStates"
        ) or {}
        assert card_id not in signal_fsrs
        assert runtime.memory_service.global_memory().capability_profile == {}

        # 5) Verify — real evaluator ack with matching symbols + tests
        evaluate = client.post(
            "/evaluate/current-file",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "file_path": str(probe),
                "language_id": "python",
                "content": probe.read_text(encoding="utf-8"),
                "diagnostics": [],
                "evaluation_source": "training",
                "training_card_id": card_id,
                "training_card_title": card_title or "Expiry practice",
                "expected_symbols": ["require_fresh"],
                "acceptance_criteria": ["Implement require_fresh for fail-closed expiry."],
            },
        )
        assert evaluate.status_code == 200, evaluate.text
        evaluate_body = evaluate.json()
        assert evaluate_body.get("passed") is True, evaluate_body
        verify_summary = str(evaluate_body.get("summary") or "").strip()
        assert verify_summary
        assert practice.read_text(encoding="utf-8") == original_practice

        # Evaluator-acked verify → formal+runtime advance + FSRS for THAT card
        latest = runtime.repository.get_latest_plan(workspace_id)
        assert latest is not None
        assert latest.id == plan_id
        assert latest.id != leftover.id

        memory = client.get(f"/memory/summary?workspace_id={workspace_id}").json()
        workspace = (memory.get("memory") or {}).get("workspace") or {}
        after_runtime = _runtime(workspace)
        assert str(after_runtime.get("plan_id") or after_runtime.get("planId") or "").strip() == plan_id
        assert leftover_formal_plan_is_live_for_fill(
            plan=latest,
            runtime=after_runtime,
            existing=after_runtime,
        )
        assert not leftover_formal_plan_is_live_for_fill(
            plan=leftover,
            runtime=after_runtime,
            existing=after_runtime,
        )

        session = runtime.ensure_session(session_id, workspace_id=workspace_id)
        advance = (session.snapshot.plan_runtime_status or {}).get("verify_plan_advance") or {}
        assert advance.get("advanced") is True
        assert str(advance.get("plan_id") or "").strip() == plan_id
        assert str(advance.get("what") or "").strip()
        assert str(advance.get("why") or "").strip()
        assert str(advance.get("next") or "").strip()

        fsrs_states = workspace.get("latest_training_fsrs_states") or workspace.get(
            "latestTrainingFsrsStates"
        ) or {}
        assert card_id in fsrs_states
        assert set(fsrs_states.keys()) == {card_id}
        assert int(fsrs_states[card_id].get("reps") or 0) >= 1
        live_card = runtime.memory_service.get_card(workspace_id, card_id)
        assert live_card is not None
        review_schedule = live_card.review_schedule or {}
        assert str(review_schedule.get("card_id") or "") == card_id
        assert review_schedule.get("fsrs_difficulty") is not None
        assert str(live_card.difficulty or "") in {"easy", "medium", "hard"}

        handoff = workspace.get("latest_training_handoff") or workspace.get(
            "latestTrainingHandoff"
        ) or {}
        handoff_id = str(handoff.get("handoff_id") or handoff.get("handoffId") or "").strip()
        assert handoff_id

        # 6) Reflect → Return: leftover not live; live identity still plan_id
        reflect = client.post(
            "/training/reflect",
            json={
                "workspace_id": workspace_id,
                "card_id": card_id,
                "handoff_id": handoff_id,
                "reflection": "Expired tokens must fail closed before any refresh path.",
            },
        )
        assert reflect.status_code == 200, reflect.text
        returned = client.post(
            "/training/return",
            json={"workspace_id": workspace_id, "card_id": card_id, "handoff_id": handoff_id},
        )
        assert returned.status_code == 200, returned.text
        return_body = returned.json()
        return_plan = return_body.get("plan") or (return_body.get("snapshot") or {}).get("plan") or {}
        return_plan_id = str(return_plan.get("id") or return_plan.get("plan_id") or "").strip()
        if return_plan_id:
            assert return_plan_id == plan_id
        assert leftover_title not in str(return_plan.get("title") or "")
        assert leftover_step not in str(
            return_plan.get("current_step") or return_plan.get("currentStep") or ""
        )

        after_return = client.get(
            f"/memory/summary?workspace_id={workspace_id}&session_id={session_id}"
        )
        assert after_return.status_code == 200
        after_body = after_return.json()
        after_mem = after_body.get("memory") or {}
        after_ws = after_mem.get("workspace") or {}
        after_rt = _runtime(after_ws)
        assert str(after_rt.get("plan_id") or after_rt.get("planId") or "").strip() == plan_id
        snapshot_plan = after_body.get("plan") or {}
        assert str(snapshot_plan.get("id") or snapshot_plan.get("plan_id") or "").strip() == plan_id
        assert leftover_title not in str(snapshot_plan.get("title") or "")
        assert leftover.id not in str(snapshot_plan.get("id") or "")
        selected_title = str(
            after_ws.get("selected_card_title") or after_ws.get("selectedCardTitle") or ""
        )
        assert leftover_step not in selected_title
        assert leftover_title not in selected_title
        stored_leftover = runtime.memory_service.repository.get_plan_by_id(leftover.id)
        assert stored_leftover is not None
        assert stored_leftover[1].title == leftover_title
        assert stored_leftover[1].current_step == leftover_step

        # 7) Next challenge / review chips: no TaskSpec, no second plan; transferable blocked
        transfer = after_ws.get("latest_transfer_state") or after_ws.get("latestTransferState") or {}
        assert transfer.get("state") != "transferable"
        assert runtime.memory_service.global_memory().capability_profile == {}
        cards_before_chips = _card_ids(runtime, workspace_id)
        assert "plan" not in _action_names(after_body)
        assert "task" not in _action_names(after_body)
        assert "next_task" not in _action_names(after_body)

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
                new=AsyncMock(return_value="Stay with the live plan. Do not mint a task."),
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                new=AsyncMock(
                    return_value={
                        "content": "Stay with the live plan. Do not mint a task.",
                        "stop_reason": "completed",
                    }
                ),
            ),
        ):
            next_challenge = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "next_task",
                    "message": "Give me the next challenge. Do not mint a task or second plan.",
                    "response_language": "en-US",
                },
            )
            assert next_challenge.status_code == 200, next_challenge.text
            next_body = next_challenge.json()
            next_task = (
                next_body.get("current_task")
                or next_body.get("currentTask")
                or (next_body.get("snapshot") or {}).get("current_task")
                or (next_body.get("snapshot") or {}).get("currentTask")
                or {}
            )
            assert not next_task.get("title")
            next_plan = next_body.get("plan") or (next_body.get("snapshot") or {}).get("plan") or {}
            assert str(next_plan.get("id") or next_plan.get("plan_id") or "").strip() in {
                "",
                plan_id,
            }
            assert leftover_title not in str(next_plan)
            assert _card_ids(runtime, workspace_id) == cards_before_chips
            assert runtime.repository.get_latest_plan(workspace_id).id == plan_id
            next_actions = _action_names(next_body)
            assert "plan" not in next_actions
            assert "task" not in next_actions
            assert "next_task" not in next_actions

            review = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "intent": "review",
                    "message": "Review the verified practice. Do not mint a card or plan.",
                    "response_language": "en-US",
                    "current_file": {
                        "path": str(probe),
                        "language_id": "python",
                        "content": probe.read_text(encoding="utf-8"),
                        "diagnostics": [],
                    },
                },
            )
            assert review.status_code == 200, review.text
            review_body = review.json()
            review_task = (
                review_body.get("current_task")
                or review_body.get("currentTask")
                or (review_body.get("snapshot") or {}).get("current_task")
                or (review_body.get("snapshot") or {}).get("currentTask")
                or {}
            )
            assert not review_task.get("title")
            assert _card_ids(runtime, workspace_id) == cards_before_chips
            assert runtime.repository.get_latest_plan(workspace_id).id == plan_id
            assert runtime.memory_service.global_memory().capability_profile == {}
            transfer_after = (
                (
                    client.get(f"/memory/summary?workspace_id={workspace_id}").json().get("memory")
                    or {}
                ).get("workspace")
                or {}
            ).get("latest_transfer_state") or {}
            assert transfer_after.get("state") != "transferable"

            # Stamp + honest chips also on /session/message (+ stream). Explicit
            # POST /task/next remains the composer super-entry for a live plan
            # (fail-closed without live identity — see test_task_next_live_plan_gate).
            from tests.test_router_stream_scenarios import completed_stream_response

            def _assert_return_blocks_task_mint(body: dict[str, Any]) -> None:
                actions = _action_names(body)
                assert "plan" not in actions
                assert "task" not in actions
                assert "next_task" not in actions
                reply_meta = (body.get("reply") or {}).get("metadata") or {}
                coach_focus = reply_meta.get("coach_focus") or {}
                agent_meta = body.get("agent_meta") or body.get("agentMeta") or {}
                assert coach_focus.get("closed_loop_return_blocks_task_mint") is True
                assert agent_meta.get("closed_loop_return_blocks_task_mint") is True
                task = (
                    body.get("current_task")
                    or body.get("currentTask")
                    or (body.get("snapshot") or {}).get("current_task")
                    or (body.get("snapshot") or {}).get("currentTask")
                    or {}
                )
                assert not task.get("title")
                plan = body.get("plan") or (body.get("snapshot") or {}).get("plan") or {}
                assert str(plan.get("id") or plan.get("plan_id") or "").strip() in {"", plan_id}

            _assert_return_blocks_task_mint(next_body)

            for session_path in ("/session/message", "/session/message/stream"):
                session_resp = client.post(
                    session_path,
                    json={
                        "session_id": session_id,
                        "workspace_id": workspace_id,
                        "message": (
                            "Give me the next challenge after return. "
                            "Do not mint a task or second plan."
                        ),
                        "response_language": "en-US",
                        "use_agent_loop": False,
                    },
                )
                assert session_resp.status_code == 200, session_resp.text
                session_body = (
                    completed_stream_response(session_resp.text)
                    if session_path.endswith("/stream")
                    else session_resp.json()
                )
                _assert_return_blocks_task_mint(session_body)
                assert _card_ids(runtime, workspace_id) == cards_before_chips
                assert runtime.repository.get_latest_plan(workspace_id).id == plan_id

        # 8) Return-then-second-workspace transfer stitch (promotion proven elsewhere;
        # here only that Return on A does not invent plan on B).
        concept = "auth expiry"
        summary_a = verify_summary
        summary_b = "Evaluator confirmed the same expiry decision in project B."
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=[concept],
            outcome="tests_passed",
            summary=summary_a,
            verified_result=summary_a,
            verified_by_evaluator=True,
            scenario="review_reflection",
        )
        transfer_a = (
            runtime.memory_service.snapshot(workspace_id).workspace or {}
        ).get("latest_transfer_state") or {}
        assert transfer_a.get("state") != "transferable"
        assert runtime.memory_service.global_memory().capability_profile == {}

        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=[concept],
            outcome="tests_passed",
            summary="Second task same project after return.",
            verified_result="Second task same project after return.",
            verified_by_evaluator=True,
            transfer_source_context="billing route",
            transfer_target_context="docs sandbox",
            transfer_evidence_summary="Applied the same guard in a second task.",
            scenario="review_reflection",
        )
        assert runtime.memory_service.global_memory().capability_profile == {}
        transfer_extra = (
            runtime.memory_service.snapshot(workspace_id).workspace or {}
        ).get("latest_transfer_state") or {}
        assert transfer_extra.get("state") != "transferable"

        workspace_b = "ws-ltvrr-closed-loop-b"
        project_b = tmp_path / "auth-expiry-lab-b"
        project_b.mkdir()
        started_b = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_b,
                "workspace_name": "Auth expiry lab B",
                "workspace_path": str(project_b),
            },
        )
        assert started_b.status_code == 200, started_b.text
        assert runtime.memory_service.repository.get_latest_plan(workspace_b) is None
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
        assert runtime.repository.get_latest_plan(workspace_id).id == plan_id
