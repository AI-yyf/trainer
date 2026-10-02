"""Practice generation and Return carry one formal identity through adoption/restart."""

import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.models import (
    LearningPlan,
    PlanStage,
    TrainingCardCandidateSnapshot,
    TrainingPlanBinding,
)
from app.llm.provider_service import ProviderService
from app.training.plan_binding import validated_mint_binding
from tests.test_api import build_client
from tests.test_training_generate_card_honesty import _practice_model_card, _sse_complete_response

WORKSPACE = "practice-plan-binding"
STEP = "Run the tuple boundary test"


def _seed(runtime):
    plan = LearningPlan(
        id="plan-current", title="Tuple boundaries", current_stage_id="verify", current_step=STEP,
        next_after_current="Explain the boundary",
        stages=[
            PlanStage(id="verify", title="Verify", goal=STEP, status="active", outcomes=["Boundary test passes"]),
            PlanStage(id="apply", title="Apply", goal="Implement nested sum", status="pending", outcomes=["Sum test passes"]),
        ],
    )
    runtime.repository.save_plan(WORKSPACE, plan)
    runtime.memory_service.persist_plan_runtime_recovery(
        WORKSPACE, plan=plan, plan_runtime={"current_step": STEP, "resume_state": "waiting"},
        request_id="seed-plan",
    )
    binding = TrainingPlanBinding(plan_id=plan.id, stage_id="verify", step=STEP,
        revision=runtime.repository.get_plan_revision(WORKSPACE, plan.id))
    return plan, binding


@pytest.mark.parametrize("change", ["missing", "plan", "stage", "step", "revision", "frozen"])
def test_generation_rejects_stale_identity_before_provider_call(tmp_path, change):
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        plan, binding = _seed(runtime)
        payload = binding.model_dump(by_alias=True)
        if change in {"plan", "stage", "step"}:
            payload[{"plan": "planId", "stage": "stageId", "step": "step"}[change]] = "old"
        elif change == "revision":
            payload["revision"] = 0
        elif change == "frozen":
            plan.frozen = True
            runtime.repository.save_plan(WORKSPACE, plan)
        with patch.object(ProviderService, "chat_completion") as provider:
            response = client.post("/training/generate-card", json={
                "workspace_id": WORKSPACE, "source": "formal_plan_step",
                "plan_binding": None if change == "missing" else payload,
            })
        assert response.status_code == 409, response.text
        provider.assert_not_called()
        assert not runtime.memory_service.get_cards(WORKSPACE)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("change_during_generation", [False, True])
def test_generated_identity_is_server_owned_and_rechecked(tmp_path, stream, change_during_generation):
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        plan, binding = _seed(runtime)
        raw = json.loads(_practice_model_card())
        raw.update(plan_links=["forged-stage"], plan_binding={
            "plan_id": "forged-plan", "stage_id": "forged-stage", "step": "forged-step"})

        def generate():
            if change_during_generation:
                plan.current_step = "Changed step"
                runtime.repository.save_plan(WORKSPACE, plan)
            return json.dumps(raw)

        async def chat(*_args, **_kwargs):
            return generate()

        async def chat_stream(*_args, **_kwargs):
            yield generate()

        with patch.object(ProviderService, "chat_completion", new=chat), patch.object(
            ProviderService, "chat_completion_stream", new=chat_stream
        ):
            response = client.post("/training/generate-card" + ("/stream" if stream else ""), json={
                "workspace_id": WORKSPACE, "source": "formal_plan_step", "focus_area": "tuple boundary",
                "plan_binding": binding.model_dump(by_alias=True), "response_language": "en-US",
            })
        cards = runtime.memory_service.get_cards(WORKSPACE)
        if change_during_generation:
            assert not cards
            if stream:
                assert not _sse_complete_response(response.text).get("card")
            else:
                assert response.status_code == 409, response.text
        else:
            assert response.status_code == 200, response.text
            assert len(cards) == 1
            assert cards[0].plan_binding == binding
            assert cards[0].plan_links == ["verify"]


@pytest.mark.parametrize("change", ["none", "frozen", "plan", "step", "stage"])
def test_return_and_adoption_never_rebind_old_practice(tmp_path, change):
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        plan, binding = _seed(runtime)
        service = runtime.memory_service
        card = service.upsert_card(WORKSPACE, TrainingCardCandidateSnapshot(
            card_id="bound-card", title="Tuple boundary", status="active",
            plan_links=[binding.stage_id], plan_binding=binding,
        ))
        if change != "none":
            if change == "frozen":
                plan.frozen = True
            elif change == "plan":
                plan.id = "new-plan-with-identical-step"
                plan.plan_id = plan.id
            elif change == "step":
                plan.current_step = "Another task in the same stage"
            else:
                plan.current_stage_id = "apply"
                plan.stages[0].status = "completed"
                plan.stages[1].status = "active"
            runtime.repository.save_plan(WORKSPACE, plan)
            service.bind_explicit_generated_plan(WORKSPACE, plan)
        before = service.snapshot(WORKSPACE).workspace["latest_plan_runtime"].copy()
        verified = service.record_training_practice_evaluation_result(
            workspace_id=WORKSPACE, card_id=card.card_id, passed=True, summary="pytest: 1 passed",
            next_step="Reflect", focus_area="tuple boundary", evidence_source="test_runner",
            verified_by_evaluator=True,
        )
        handoff = verified["latest_training_handoff"]["handoff_id"]
        service.record_training_handoff_reflection(workspace_id=WORKSPACE, card_id=card.card_id,
            handoff_id=handoff, reflection="Nested mutability differs from hashability.")
        service.return_training_handoff(workspace_id=WORKSPACE, card_id=card.card_id, handoff_id=handoff)
        item = service._training_return_evidence_for_card(WORKSPACE, card.card_id)
        assert item.verified and item.target_plan_id == binding.plan_id
        assert item.target_plan_stage_id == "verify" and item.target_plan_step == STEP
        if change in {"plan", "step", "stage"}:
            assert item.id in [item.id for item in service.evidence_queue(WORKSPACE).history]
            with pytest.raises(HTTPException) as error:
                service.adopt_evidence(WORKSPACE, item.id)
            assert error.value.status_code == 409
            after = service.snapshot(WORKSPACE).workspace["latest_plan_runtime"]
            for key in ("plan_id", "current_step", "current_stage_id"):
                assert after[key] == before[key]
        else:
            adopted = service.adopt_evidence(WORKSPACE, item.id)
            assert adopted.plan_updated is (change == "none")
            stored = runtime.repository.get_latest_plan(WORKSPACE)
            assert stored.current_stage_id == ("apply" if change == "none" else "verify")
            assert [stage.status for stage in stored.stages] == (
                ["completed", "active"] if change == "none" else ["active", "pending"])
    with build_client(tmp_path) as restarted:
        runtime = restarted.app.state.runtime
        card = runtime.memory_service.get_card(WORKSPACE, "bound-card")
        assert card.plan_binding == binding
        stored = runtime.repository.get_latest_plan(WORKSPACE)
        recovered = runtime.memory_service.snapshot(WORKSPACE).workspace["latest_plan_runtime"]
        assert recovered["current_step"] == stored.current_step
        assert recovered["current_stage_id"] == stored.current_stage_id


def test_unbound_request_cannot_invent_a_formal_identity():
    assert validated_mint_binding(None, source="conversation_gap", plan=None, runtime={}, revision=0) is None
