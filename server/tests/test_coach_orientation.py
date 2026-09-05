"""Coach orientation is derived from real facts, not conversation theater."""

from __future__ import annotations

from app.core.models import (
    FirstLookSummary,
    LearningPlan,
    MemorySnapshot,
    PlanStage,
    ProviderConfig,
    WorkbenchSnapshot,
    WorkspaceUnderstandingSnapshot,
)
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService
from app.memory.workspace_recovery import PLAN_RUNTIME_KEY
from app.pedagogy.coach_orientation import (
    build_coach_orientation_from_snapshot,
    derive_coach_orientation,
    normalize_coach_orientation,
)


def test_provider_and_runtime_facts_beat_conversation_theater() -> None:
    ready_talk = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        conversation_count=3,
        plan_current_step="Ship the parser guard",
        language="en-US",
    )
    assert ready_talk["object_kind"] == "plan"
    assert ready_talk["primary_action"] == "open_plan"

    blocked = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=False,
        conversation_count=3,
        plan_current_step="Ship the parser guard",
        language="en-US",
    )
    assert blocked["object_kind"] == "provider"
    assert blocked["state"] == "needs_setup"
    assert blocked["primary_action"] == "open_settings"

    runtime = derive_coach_orientation(
        sidecar_status="error",
        has_provider_model=True,
        conversation_count=3,
        language="en-US",
    )
    assert runtime["object_kind"] == "workspace"
    assert runtime["state"] == "blocked"


def test_training_reliability_and_handoff_are_authoritative() -> None:
    waiting = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        training_reliability_phase="executing",
        selected_card_title="Parser boundary",
        plan_current_step="Ignore this plan step",
        language="en-US",
    )
    assert waiting["object_kind"] == "training"
    assert waiting["state"] == "waiting"
    assert waiting["primary_action"] == "wait"
    assert waiting["object_label"] == "Parser boundary"

    failed = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        training_reliability_phase="failed",
        selected_card_title="Parser boundary",
        language="en-US",
    )
    assert failed["state"] == "blocked"
    assert failed["primary_action"] == "retry"

    returning = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        training_learning_phase="return",
        training_handoff_status="ready_to_return",
        selected_card_title="Parser boundary",
        language="zh-CN",
    )
    assert returning["object_kind"] == "training"
    assert returning["primary_action"] == "open_training"


def test_transfer_state_overlays_ready_plan_not_provider_blockers() -> None:
    transfer = {
        "concept": "shared rhythm",
        "state": "transferable",
        "scene_count": 2,
        "workspace_ids": ["project-one", "project-two"],
        "scene_keys": ["default"],
        "why": "This skill has evidence in more than one scene.",
        "next": "Schedule a review, or apply it in a new challenge.",
    }
    ready = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        conversation_count=2,
        plan_current_step="Keep the parser guard",
        language="en-US",
        transfer_state=transfer,
    )
    assert ready["object_kind"] == "plan"
    assert ready["next_step"] == "Schedule a review, or apply it in a new challenge."

    blocked = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=False,
        conversation_count=2,
        plan_current_step="Keep the parser guard",
        language="en-US",
        transfer_state=transfer,
    )
    assert blocked["object_kind"] == "provider"
    assert blocked["next_step"] == "Save and test a provider first."


def test_incomplete_orientation_is_not_current_truth() -> None:
    assert normalize_coach_orientation({"object_kind": "conversation", "state": "ready"}) is None
    assert (
        normalize_coach_orientation(
            derive_coach_orientation(
                sidecar_status="ready",
                has_provider_model=True,
                conversation_count=0,
                language="en-US",
            )
        )
        is not None
    )


def test_plan_first_look_understand_does_not_make_generate_plan_the_only_next() -> None:
    from app.pedagogy.plan_orientation import derive_plan_orientation

    first_look_next = "Add a token expiry test"
    first_look_why = "auth.py already checks expired tokens."
    ready = derive_plan_orientation(
        has_formal_plan=False,
        first_look_recommended_next=first_look_next,
        first_look_why=first_look_why,
        language="en-US",
    )
    assert ready["primary_action"] != "generate_plan"
    assert ready["primary_action"] == "continue_without_plan"
    assert ready["next_step"] == first_look_next
    assert ready["why"] == first_look_why
    empty_recovered = derive_plan_orientation(
        has_formal_plan=False,
        recovered_runtime=True,
        current_step="",
        first_look_recommended_next=first_look_next,
        first_look_why=first_look_why,
        language="en-US",
    )
    assert empty_recovered["primary_action"] == "wait"
    assert empty_recovered["primary_action"] != "generate_plan"
    assert empty_recovered["next_step"] != first_look_next
    live = derive_plan_orientation(
        has_formal_plan=False,
        recovered_runtime=True,
        resume_state="in_progress",
        current_step=first_look_next,
        why_now=first_look_why,
        first_look_recommended_next="Invent a leftover first-look plan",
        language="en-US",
    )
    assert live["primary_action"] == "continue_step"
    assert live["primary_action"] != "generate_plan"
    assert live["primary_action"] != "continue_without_plan"
    empty = derive_plan_orientation(has_formal_plan=False, language="en-US")
    assert empty["primary_action"] == "generate_plan"


def test_ready_provider_uses_first_look_next_without_inventing_plan() -> None:
    first_look_next = "Add a token expiry test"
    first_look_why = "auth.py already checks expired tokens."
    ready = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        conversation_count=0,
        first_look_next=first_look_next,
        first_look_why=first_look_why,
        language="en-US",
    )
    assert ready["object_kind"] == "conversation"
    assert ready["primary_action"] == "compose"
    assert ready["next_step"] == first_look_next
    assert ready["why"] == first_look_why
    assert ready["object_kind"] != "provider"
    assert ready["primary_action"] != "open_plan"
    assert "Save and test a provider" not in ready["next_step"]

    blocked = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=False,
        conversation_count=0,
        first_look_next=first_look_next,
        first_look_why=first_look_why,
        language="en-US",
    )
    assert blocked["object_kind"] == "provider"
    assert blocked["primary_action"] == "open_settings"
    assert blocked["next_step"] == "Save and test a provider first."

    returning = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        training_learning_phase="return",
        training_handoff_status="ready_to_return",
        selected_card_title="Keep one auth check",
        first_look_next=first_look_next,
        language="en-US",
    )
    assert returning["object_kind"] == "training"
    assert returning["primary_action"] == "open_training"
    assert returning["next_step"] != first_look_next

    waiting = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        training_reliability_phase="executing",
        selected_card_title="Keep one auth check",
        first_look_next=first_look_next,
        language="en-US",
    )
    assert waiting["object_kind"] == "training"
    assert waiting["primary_action"] == "wait"
    assert waiting["next_step"] != first_look_next

    live_plan = derive_coach_orientation(
        sidecar_status="ready",
        has_provider_model=True,
        plan_current_step="Ship the parser guard",
        first_look_next=first_look_next,
        language="en-US",
    )
    assert live_plan["object_kind"] == "plan"
    assert live_plan["primary_action"] == "open_plan"
    assert live_plan["next_step"] != first_look_next


def test_snapshot_first_look_leads_when_provider_ready() -> None:
    first_look_next = "Add a token expiry test"
    first_look_why = "auth.py already checks expired tokens."
    provider = ProviderConfig(
        name="ready-provider",
        baseUrl="http://example.test/v1",
        apiKeyRef="ready-ref",
        model="ready-model",
    )
    understanding = WorkspaceUnderstandingSnapshot(
        first_look_summary=FirstLookSummary(
            recommended_next_step=first_look_next,
            why_this_guess=first_look_why,
        )
    )
    ready = build_coach_orientation_from_snapshot(
        WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            memory=MemorySnapshot(
                workspace={"workspace_id": "workspace-first-look"},
                workspace_understanding=understanding,
            ),
        ),
        response_language="en-US",
    )
    assert ready["object_kind"] == "conversation"
    assert ready["primary_action"] == "compose"
    assert ready["next_step"] == first_look_next
    assert ready["why"] == first_look_why

    missing_provider = build_coach_orientation_from_snapshot(
        WorkbenchSnapshot(
            sidecar_status="ready",
            provider=None,
            memory=MemorySnapshot(
                workspace={"workspace_id": "workspace-first-look"},
                workspace_understanding=understanding,
            ),
        ),
        response_language="en-US",
    )
    assert missing_provider["object_kind"] == "provider"
    assert missing_provider["primary_action"] == "open_settings"
    assert missing_provider["next_step"] == "Save and test a provider first."

    foreign = build_coach_orientation_from_snapshot(
        WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            memory=MemorySnapshot(
                workspace={
                    "workspace_id": "workspace-b",
                    "workspace_understanding": {
                        "workspace_id": "workspace-a",
                        "firstLookSummary": {
                            "recommendedNextStep": first_look_next,
                            "whyThisGuess": first_look_why,
                        },
                    },
                }
            ),
        ),
        response_language="en-US",
    )
    assert foreign["next_step"] != first_look_next
    assert foreign["object_kind"] == "conversation"
    assert foreign["primary_action"] == "compose"

    leftover_title = "Keep the current stage"
    leftover_plan = LearningPlan(
        id="plan-formal-old",
        title=leftover_title,
        summary="Leftover formal summary of the old stage path",
        current_stage_id="stage-1",
        current_step="Keep one auth check",
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
    leftover = build_coach_orientation_from_snapshot(
        WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            plan=leftover_plan,
            plan_runtime_status={
                "recovered": True,
                "current_step": "",
                "plan_id": "",
                "why_now": "",
            },
            memory=MemorySnapshot(
                workspace={
                    "workspace_id": "workspace-leftover-first-look",
                    PLAN_RUNTIME_KEY: {
                        "current_step": "",
                        "resume_state": "in_progress",
                        "workspace_id": "workspace-leftover-first-look",
                    },
                },
                workspace_understanding=WorkspaceUnderstandingSnapshot(
                    first_look_summary=FirstLookSummary(
                        recommended_next_step=leftover_title,
                        why_this_guess="Leftover formal title must not become first-look next.",
                    )
                ),
            ),
        ),
        response_language="en-US",
    )
    assert leftover["next_step"] != leftover_title
    assert leftover["object_kind"] == "conversation"
    assert leftover["primary_action"] == "compose"
    assert leftover["primary_action"] != "open_plan"


def test_snapshot_and_restart_keep_persisted_orientation(tmp_path) -> None:
    snapshot = WorkbenchSnapshot(
        sidecar_status="ready",
        provider=ProviderConfig(
            name="minimax",
            baseUrl="http://example.test",
            apiKeyRef="secret-ref",
            model="MiniMax-M2.7",
        ),
        memory=MemorySnapshot(
            workspace={
                "latest_training_reliability": {
                    "phase": "acked",
                    "request_id": "req-1",
                },
                "latest_training_handoff": {
                    "learning_phase": "reflect",
                    "handoff_status": "needs_reflection",
                    "card_title": "Keep the loop on the card",
                },
                "selected_card_title": "Keep the loop on the card",
            }
        ),
    )
    orientation = build_coach_orientation_from_snapshot(snapshot, response_language="en-US")
    assert orientation["object_kind"] == "training"
    assert orientation["state"] == "ready"
    assert orientation["primary_action"] == "open_training"

    workspace_id = "workspace-coach-orientation"
    service = MemoryService(TrainerRepository(tmp_path / "coach-orientation.db"))
    service.update_workspace_state(workspace_id, latest_coach_orientation=orientation)
    restarted = MemoryService(TrainerRepository(tmp_path / "coach-orientation.db"))
    restored = restarted._structured_for(workspace_id)._workspace.get("latest_coach_orientation")
    assert normalize_coach_orientation(restored) == orientation


def test_snapshot_orientation_reads_persisted_transfer_state() -> None:
    snapshot = WorkbenchSnapshot(
        sidecar_status="ready",
        provider=ProviderConfig(
            name="minimax",
            baseUrl="http://example.test",
            apiKeyRef="secret-ref",
            model="MiniMax-M2.7",
        ),
        memory=MemorySnapshot(
            workspace={
                "latest_transfer_state": {
                    "concept": "shared rhythm",
                    "state": "transferable",
                    "scene_count": 2,
                    "workspace_ids": ["project-one", "project-two"],
                    "why": "This skill has evidence in more than one scene.",
                    "next": "Schedule a review, or apply it in a new challenge.",
                }
            }
        ),
        plan=None,
    )
    orientation = build_coach_orientation_from_snapshot(snapshot, response_language="en-US")
    assert orientation["object_kind"] == "conversation"
    assert orientation["next_step"] == "Schedule a review, or apply it in a new challenge."


def test_leftover_formal_card_title_does_not_live_in_orientation_object_label() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_card = f"Practice: {leftover_title}"
    recovered_step = "Add a token expiry test"
    plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id="stage-1",
        current_step=leftover_step,
        stages=[
            PlanStage(
                id="stage-1",
                title=leftover_stage,
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    provider = ProviderConfig(
        name="minimax",
        baseUrl="http://example.test",
        apiKeyRef="secret-ref",
        model="MiniMax-M2.7",
    )

    def _snapshot(workspace_id: str, runtime: dict[str, object]) -> WorkbenchSnapshot:
        return WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            plan=plan,
            plan_runtime_status={
                "recovered": True,
                "current_step": str(runtime.get("current_step") or ""),
                "plan_id": str(runtime.get("plan_id") or ""),
                "why_now": str(runtime.get("why_now") or ""),
            },
            memory=MemorySnapshot(
                workspace={
                    "workspace_id": workspace_id,
                    PLAN_RUNTIME_KEY: runtime,
                    "latest_training_reliability": {"phase": "executing"},
                    "selected_card_title": leftover_card,
                    "latest_training_handoff": {"card_title": leftover_card},
                }
            ),
        )

    orientation = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-leftover-card",
            {
                "current_step": recovered_step,
                "why_now": "Expired tokens still leak.",
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-leftover-card",
            },
        ),
        response_language="en-US",
    )
    empty = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-empty-step",
            {
                "current_step": "",
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-empty-step",
            },
        ),
        response_language="en-US",
    )
    for text in (orientation["object_label"], empty["object_label"]):
        assert leftover_title not in text
        assert leftover_card not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
    assert orientation["object_kind"] == "training"
    assert orientation["object_label"] == recovered_step
    assert empty["object_label"] == "Current training card"
    still = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-still-on-plan",
            {
                "current_step": leftover_step,
                "plan_id": leftover_plan_id,
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-still-on-plan",
            },
        ),
        response_language="en-US",
    )
    assert leftover_card in still["object_label"]


def test_leftover_formal_plan_step_does_not_live_in_orientation_object_label() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_why = "Keep the leftover why"
    recovered_step = "Add a token expiry test"
    recovered_why = "Expired tokens still leak."
    plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id="stage-1",
        current_step=leftover_step,
        why_now=leftover_why,
        stages=[
            PlanStage(
                id="stage-1",
                title=leftover_stage,
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    provider = ProviderConfig(
        name="minimax",
        baseUrl="http://example.test",
        apiKeyRef="secret-ref",
        model="MiniMax-M2.7",
    )

    def _snapshot(workspace_id: str, runtime: dict[str, object]) -> WorkbenchSnapshot:
        return WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            plan=plan,
            plan_runtime_status={
                "recovered": True,
                "current_step": str(runtime.get("current_step") or ""),
                "plan_id": str(runtime.get("plan_id") or ""),
                "why_now": str(runtime.get("why_now") or ""),
            },
            memory=MemorySnapshot(
                workspace={
                    "workspace_id": workspace_id,
                    PLAN_RUNTIME_KEY: runtime,
                }
            ),
        )

    orientation = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-leftover-step",
            {
                "current_step": recovered_step,
                "why_now": recovered_why,
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-leftover-step",
            },
        ),
        response_language="en-US",
    )
    empty = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-empty-plan-step",
            {
                "current_step": "",
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-empty-plan-step",
            },
        ),
        response_language="en-US",
    )
    for text in (orientation["object_label"], orientation["why"], empty["object_label"], empty["why"]):
        assert leftover_title not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
        assert leftover_why not in text
    assert orientation["object_kind"] == "plan"
    assert orientation["object_label"] == recovered_step
    assert recovered_why in orientation["why"]
    assert leftover_step not in empty["object_label"]
    still = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-still-on-plan-step",
            {
                "current_step": leftover_step,
                "plan_id": leftover_plan_id,
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-still-on-plan-step",
            },
        ),
        response_language="en-US",
    )
    assert leftover_step in still["object_label"]


def test_leftover_formal_blocked_reason_does_not_live_in_orientation() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_blocked = "Keep the leftover blocker"
    recovered_step = "Add a token expiry test"
    recovered_blocked = "Expired tokens still leak the session."
    plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id="stage-1",
        current_step=leftover_step,
        blocked_reason=leftover_blocked,
        stages=[
            PlanStage(
                id="stage-1",
                title=leftover_stage,
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    provider = ProviderConfig(
        name="minimax",
        baseUrl="http://example.test",
        apiKeyRef="secret-ref",
        model="MiniMax-M2.7",
    )

    def _snapshot(workspace_id: str, runtime: dict[str, object]) -> WorkbenchSnapshot:
        return WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            plan=plan,
            plan_runtime_status={
                "recovered": True,
                "current_step": str(runtime.get("current_step") or ""),
                "plan_id": str(runtime.get("plan_id") or ""),
                "blocked_reason": str(runtime.get("blocked_reason") or ""),
            },
            memory=MemorySnapshot(
                workspace={
                    "workspace_id": workspace_id,
                    PLAN_RUNTIME_KEY: runtime,
                }
            ),
        )

    orientation = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-leftover-blocker",
            {
                "current_step": recovered_step,
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-leftover-blocker",
            },
        ),
        response_language="en-US",
    )
    recovered = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-recovered-blocker",
            {
                "current_step": recovered_step,
                "blocked_reason": recovered_blocked,
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-recovered-blocker",
            },
        ),
        response_language="en-US",
    )
    empty = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-empty-blocker",
            {
                "current_step": "",
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-empty-blocker",
            },
        ),
        response_language="en-US",
    )
    for text in (
        orientation["why"],
        orientation["object_label"],
        recovered["why"],
        recovered["object_label"],
        empty["why"],
        empty["object_label"],
    ):
        assert leftover_title not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
        assert leftover_blocked not in text
    assert orientation["object_kind"] == "plan"
    assert orientation["state"] != "blocked"
    assert leftover_blocked not in orientation["why"]
    assert recovered["state"] == "blocked"
    assert recovered["why"] == recovered_blocked
    assert leftover_blocked not in empty["why"]
    still = build_coach_orientation_from_snapshot(
        _snapshot(
            "workspace-orientation-still-on-plan-blocker",
            {
                "current_step": leftover_step,
                "plan_id": leftover_plan_id,
                "resume_state": "in_progress",
                "workspace_id": "workspace-orientation-still-on-plan-blocker",
            },
        ),
        response_language="en-US",
    )
    assert leftover_blocked in still["why"]
    assert still["state"] == "blocked"
