from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.core.models import (
    EvidenceItem,
    FlashDeckSnapshot,
    LearningPlan,
    MemorySnapshot,
    PlanStage,
    ProviderConfig,
    ResourceRecord,
    ReviewArtifactHistoryEntry,
    ReviewArtifactSnapshot,
    ScenarioLab,
    ScenarioLabHistoryEntry,
    TaskSpec,
    TeachingKnowledgeAsset,
    TheoryDrillHistoryEntry,
    TheoryDrillQuestion,
    TheoryDrillSnapshot,
    TrainingCardCandidateSnapshot,
    WorkbenchSnapshot,
)
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService
from app.memory.workspace_recovery import (
    ADAPTATION_GUIDE_KEY,
    AFFECT_STATE_KEY,
    COACH_FOCUS_KEY,
    COACH_TURN_KEY,
    COACHING_ADAPTATION_KEY,
    COACHING_FOCUS_KEY,
    CURRENT_TASK_KEY,
    EVALUATION_KEY,
    LEARNER_STATE_KEY,
    NEXT_STEP_HINT_KEY,
    PLAN_RUNTIME_KEY,
    PRINCIPLE_NOTES_KEY,
    PROJECT_SOURCES_KEY,
    TEACHING_DECISION_KEY,
    TONE_DECISION_KEY,
    TRAINING_CHROME_KEY,
    WAITING_VERIFY_EVIDENCE_SOURCE,
    accept_in_progress_plan_runtime_turn,
    accept_plan_runtime_resume_request,
    apply_live_training_mint_to_card,
    apply_training_chrome_scope,
    attest_waiting_verify_on_adopt,
    build_plan_runtime_advance_after_adopt,
    build_plan_runtime_recovery,
    build_plan_runtime_resume,
    build_waiting_composer_evidence,
    build_waiting_verify_evidence,
    coach_focus_runtime_from_snapshot,
    extract_structured_next_step_runtime_facts,
    extract_structured_plan_runtime_facts,
    extract_structured_verify_method,
    formal_plan_identity_is_live,
    formal_plan_is_live_runtime_identity,
    formal_task_is_live_runtime_identity,
    is_authoritative_provider_capability_success,
    is_completed_streaming_checkpoint,
    leftover_bound_plan_competing_identity_labels,
    leftover_coach_conversation_is_not_live,
    leftover_coach_turn_chrome_is_not_live,
    leftover_evaluation_headline_is_not_live,
    leftover_first_look_headline_is_not_live,
    leftover_formal_plan_is_live_for_fill,
    leftover_formal_training_labels,
    leftover_resource_library_list_is_not_live,
    leftover_resource_sandbox_preview_is_not_live,
    leftover_resource_sandbox_state_is_not_live,
    leftover_resource_selected_detail_is_not_live,
    leftover_settings_learner_project_onboarding_is_not_live,
    leftover_settings_profile_rhythm_is_not_live,
    leftover_streaming_checkpoint_is_not_live,
    leftover_suggested_actions_is_not_live,
    leftover_task_guide_focus_is_not_live,
    leftover_training_focus_chrome_is_not_live,
    leftover_training_handoff_chrome_is_not_live,
    leftover_transfer_skill_has_real_multi_scene_proof,
    leftover_transfer_skill_is_not_live,
    live_coach_focus_area,
    live_coach_stage_label,
    live_coaching_next_step,
    live_evidence_binding,
    live_language_detection_hint,
    live_leftover_focus_candidate,
    live_memory_snapshot_overlay,
    live_plan_artifact_stage_chrome,
    live_plan_current_step_fill,
    live_plan_lane_copy,
    live_plan_mismatch_candidate_plan_id,
    live_plan_mismatch_candidate_step,
    live_plan_overlay_fields,
    live_plan_refresh_step_why,
    live_plan_snapshot_persist_chrome,
    live_plan_update_heading,
    live_plan_update_persist_chrome,
    live_runtime_frozen,
    live_runtime_next_text,
    live_runtime_next_verify_method,
    live_runtime_plan_id,
    live_runtime_stage_id,
    live_task_clean_step_candidates,
    live_task_converted_copy,
    live_task_focus_area,
    live_task_heading,
    live_task_next_action,
    live_task_picked_copy,
    live_task_suggested_reason,
    live_task_suggested_title,
    live_task_thin_slice_copy,
    live_task_training_concepts,
    live_training_focus_fallback,
    live_training_lane_copy,
    live_training_mint_anchors,
    live_training_open_copy,
    live_training_persist_chrome,
    live_training_why_this_card,
    normalize_formal_plan_identity,
    normalize_plan_runtime_recovery,
    normalize_provider_capability_recovery,
    normalize_training_chrome,
    overlay_plan_runtime_current_stage,
    overlay_plan_runtime_display_facts,
    plan_runtime_status_from_recovery,
    prefer_recovered_coach_task_chrome,
    prefer_recovered_coach_turn_chrome,
    prefer_recovered_resource_selected_detail,
    prefer_recovered_settings_learner_project_onboarding,
    prefer_recovered_settings_profile_rhythm,
    prefer_recovered_training_focus_chrome,
    prefer_recovered_training_handoff_chrome,
    prefer_recovered_transfer_skill,
    recover_streaming_checkpoint_after_restart,
    recovered_resume_turn_succeeded,
    scope_evidence_items_to_workspace,
    scope_evidence_queue_to_runtime_step,
    select_formal_plan_for_scope,
    select_latest_adaptation_guide,
    select_latest_affect_state,
    select_latest_coach_focus,
    select_latest_coach_turn,
    select_latest_coaching_adaptation,
    select_latest_coaching_focus,
    select_latest_current_task,
    select_latest_evaluation,
    select_latest_learner_state,
    select_latest_next_step_hint,
    select_latest_principle_notes,
    select_latest_project_sources,
    select_latest_teaching_decision,
    select_latest_tone_decision,
    select_plan_runtime_for_pressure,
    select_plan_runtime_for_scope,
    select_provider_capability_for_scope,
    select_resources_for_scope,
    select_streaming_checkpoint_for_scope,
    select_training_chrome_for_scope,
    structured_plan_step_finished,
    verified_adopt_allows_runtime_advance,
)
from app.pedagogy.coach_orientation import build_coach_orientation_from_snapshot
from app.planner.service import PlannerService
from app.sandbox.service import SandboxService

FORMAL_NEXT_WHY = "Expiry cases still skip the refresh path."
FORMAL_NEXT_BLOCK = "Refresh still fails after expiry."
FORMAL_NEXT_VERIFY = ["Run the expiry refresh check"]


def _plan_with_formal_next(plan: LearningPlan) -> SimpleNamespace:
    return SimpleNamespace(
        id=plan.id,
        plan_id=getattr(plan, "plan_id", None),
        current_stage_id=plan.current_stage_id,
        current_step=plan.current_step,
        why_now=plan.why_now,
        verify_method=list(plan.verify_method),
        blocked_reason=plan.blocked_reason,
        next_after_current=plan.next_after_current,
        frozen=plan.frozen,
        stages=plan.stages,
        next_why_now=FORMAL_NEXT_WHY,
        next_blocked_reason=FORMAL_NEXT_BLOCK,
        next_verify_method=list(FORMAL_NEXT_VERIFY),
    )


def build_memory_service(tmp_path: Path) -> MemoryService:
    return MemoryService(TrainerRepository(tmp_path / "trainer-workspace-recovery.db"))


def test_incomplete_records_are_not_success() -> None:
    assert select_plan_runtime_for_pressure(
        {
            "workspace_id": "workspace-plan",
            "plan_id": "plan-stale",
            "frozen": True,
        },
        "workspace-plan",
    ) is None
    assert select_plan_runtime_for_pressure(
        {
            "workspace_id": "workspace-other",
            "blocked_reason": "auth still fails",
            "current_step": "Keep one check",
        },
        "workspace-plan",
    ) is None
    recovered = plan_runtime_status_from_recovery(
        {
            "workspace_id": "workspace-plan",
            "current_step": "Keep one check",
            "blocked_reason": "auth still fails",
            "why_now": "The session still leaks.",
        },
        "workspace-plan",
    )
    assert recovered is not None
    assert recovered["recovered"] is True
    assert recovered["current_step"] == "Keep one check"
    assert recovered["blocked_reason"] == "auth still fails"
    assert recovered["current_stage"] is None
    assert recovered["resume_state"] == "interrupted"
    assert recovered.get("plan_id") in {None, ""}
    bound = plan_runtime_status_from_recovery(
        {
            "workspace_id": "workspace-plan",
            "plan_id": "plan-live-bound",
            "current_step": "Ship token refresh",
            "resume_state": "in_progress",
        },
        "workspace-plan",
    )
    assert bound is not None
    assert bound.get("plan_id") == "plan-live-bound"
    assert plan_runtime_status_from_recovery(
        {
            "workspace_id": "workspace-plan",
            "plan_id": "plan-stale",
        },
        "workspace-plan",
    ) is None
    assert normalize_plan_runtime_recovery({"revision": 1, "frozen": True}) is None
    recovered_without_step = normalize_plan_runtime_recovery(
        {
            "workspace_id": "workspace-plan",
            "resume_state": "in_progress",
        }
    )
    assert recovered_without_step is not None
    assert recovered_without_step["current_step"] is None
    assert recovered_without_step["resume_state"] == "in_progress"
    empty_overlay = plan_runtime_status_from_recovery(
        {
            "workspace_id": "workspace-plan",
            "resume_state": "in_progress",
            "current_step": "",
        },
        "workspace-plan",
    )
    assert empty_overlay is not None
    assert empty_overlay["recovered"] is True
    assert not str(empty_overlay.get("current_step") or "").strip()
    assert empty_overlay["current_stage"] is None
    assert plan_runtime_status_from_recovery(
        {
            "workspace_id": "workspace-b",
            "resume_state": "in_progress",
            "current_step": "",
        },
        "workspace-plan",
    ) is None
    assert normalize_provider_capability_recovery({"ok": True, "model": "MiniMax-M2.7"}) is None
    assert is_authoritative_provider_capability_success(
        {
            "ok": True,
            "provider_name": "minimax",
            "base_url": "http://example.test",
            "model": "MiniMax-M2.7",
            "checked_at": "2026-08-25T00:00:00+00:00",
            "tools_ready": True,
            "tool_probe_status": "unverified",
            "capability_evidence": [{"name": "tools", "declared": True, "observed": None, "state": "unverified"}],
        }
    )
    recovered = normalize_provider_capability_recovery(
        {
            "ok": True,
            "provider_name": "minimax",
            "base_url": "http://example.test",
            "model": "MiniMax-M2.7",
            "checked_at": "2026-08-25T00:00:00+00:00",
            "tools_ready": True,
            "tool_probe_status": "unverified",
            "capability_evidence": [{"name": "tools", "declared": True, "observed": None, "state": "unverified"}],
        }
    )
    assert recovered is not None
    assert recovered["tools_ready"] is False
    assert is_completed_streaming_checkpoint({"request_id": "stream-1"}) is False


def test_plan_runtime_survives_sidecar_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-workspace-recovery.db"
    service = MemoryService(TrainerRepository(db_path))
    plan = LearningPlan(
        id="plan-restore",
        title="Keep the current stage",
        current_stage_id="stage-1",
        current_step="Tighten the parser guard",
        why_now="The current file still leaks the boundary.",
        blocked_reason="",
        frozen=True,
        verify_method=["Run the focused test"],
        stages=[PlanStage(id="stage-1", title="Guard", goal="Keep one check", outcomes=["pass"], status="active")],
    )
    persisted = service.persist_plan_runtime_recovery(
        "workspace-plan",
        plan=_plan_with_formal_next(plan),
        plan_runtime={
            "current_step": "Tighten the parser guard",
            "why_now": "The current file still leaks the boundary.",
            "blocked_reason": "",
            "verify_method": ["Run the focused test"],
            "current_stage": {"id": "stage-1", "title": "Guard"},
        },
        evidence_binding="evidence-guard-1",
        request_id="plan-req-1",
    )
    assert persisted is not None
    assert persisted["frozen"] is True
    assert persisted["current_step"] == "Tighten the parser guard"
    assert persisted["next_why_now"] == FORMAL_NEXT_WHY
    assert persisted["next_blocked_reason"] == FORMAL_NEXT_BLOCK
    assert persisted["next_verify_method"] == FORMAL_NEXT_VERIFY

    restarted = MemoryService(TrainerRepository(db_path))
    restored = restarted.recover_workspace_facts("workspace-plan")["latest_plan_runtime"]
    assert restored is not None
    assert restored["plan_id"] == "plan-restore"
    assert restored["current_step"] == "Tighten the parser guard"
    assert restored["frozen"] is True
    assert restored["next_why_now"] == FORMAL_NEXT_WHY
    assert restored["next_blocked_reason"] == FORMAL_NEXT_BLOCK
    assert restored["next_verify_method"] == FORMAL_NEXT_VERIFY
    assert restored["evidence_binding"] == "evidence-guard-1"
    assert restored["request_id"] == "plan-req-1"


def test_provider_last_test_strips_secrets_and_survives_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-workspace-recovery.db"
    service = MemoryService(TrainerRepository(db_path))
    persisted = service.persist_provider_capability_recovery(
        "workspace-provider",
        {
            "ok": True,
            "provider_name": "minimax",
            "base_url": "http://example.test/v1",
            "model": "MiniMax-M2.7",
            "checked_at": "2026-08-25T00:00:00+00:00",
            "api_key": "should-never-persist",
            "tools_ready": True,
            "tool_probe_status": "verified",
            "capability_evidence": [
                {"name": "tools", "declared": True, "observed": True, "state": "verified"},
            ],
        },
    )
    assert persisted is not None
    assert "api_key" not in persisted
    assert persisted["tools_ready"] is True
    dumped = str(service.snapshot("workspace-provider").workspace)
    assert "should-never-persist" not in dumped

    restarted = MemoryService(TrainerRepository(db_path))
    restored = restarted.recover_workspace_facts("workspace-provider")["latest_provider_capability"]
    assert restored is not None
    assert restored["ok"] is True
    assert restored["model"] == "MiniMax-M2.7"
    assert "api_key" not in restored
    assert is_authoritative_provider_capability_success(restored) is True


def test_in_flight_stream_becomes_interrupted_after_restart_not_completed(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-workspace-recovery.db"
    service = MemoryService(TrainerRepository(db_path))
    started = service.persist_streaming_checkpoint(
        "workspace-stream",
        request_id="stream-restore-1",
        phase="streaming",
        session_id="session-1",
        stream_message_id="message-1",
    )
    assert started is not None
    assert started["phase"] == "streaming"
    assert is_completed_streaming_checkpoint(started) is False

    restarted = MemoryService(TrainerRepository(db_path))
    restored = restarted.recover_workspace_facts("workspace-stream")["latest_streaming_checkpoint"]
    assert restored is not None
    assert restored["request_id"] == "stream-restore-1"
    assert restored["phase"] == "interrupted"
    assert is_completed_streaming_checkpoint(restored) is False
    assert recover_streaming_checkpoint_after_restart(started)["phase"] == "interrupted"


def test_completed_stream_stays_completed_after_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-workspace-recovery.db"
    service = MemoryService(TrainerRepository(db_path))
    service.persist_streaming_checkpoint(
        "workspace-stream",
        request_id="stream-done-1",
        phase="streaming",
        session_id="session-1",
    )
    completed = service.persist_streaming_checkpoint(
        "workspace-stream",
        request_id="stream-done-1",
        phase="completed",
        session_id="session-1",
    )
    assert completed is not None
    assert completed["phase"] == "completed"

    restarted = MemoryService(TrainerRepository(db_path))
    restored = restarted.recover_workspace_facts("workspace-stream")["latest_streaming_checkpoint"]
    assert restored is not None
    assert restored["phase"] == "completed"
    assert is_completed_streaming_checkpoint(restored) is True


def test_interrupted_stream_drives_coach_orientation_resume() -> None:
    snapshot = WorkbenchSnapshot(
        sidecar_status="ready",
        provider=ProviderConfig(
            name="minimax",
            baseUrl="http://example.test",
            apiKeyRef="secret-ref",
            model="MiniMax-M2.7",
        ),
        memory={
            "workspace": {
                "latest_streaming_checkpoint": {
                    "revision": 2,
                    "request_id": "stream-restore-1",
                    "phase": "interrupted",
                    "stop_reason": "interrupted",
                }
            }
        },
    )
    orientation = build_coach_orientation_from_snapshot(snapshot, response_language="en-US")
    assert orientation["state"] == "interrupted"
    assert orientation["primary_action"] == "resume_checkpoint"


def _provider_payload(profile_id: str) -> dict[str, object]:
    return {
        "ok": True,
        "provider_name": "minimax",
        "base_url": "http://example.test/v1",
        "model": "MiniMax-M2.7",
        "checked_at": "2026-08-25T00:00:00+00:00",
        "provider_profile_id": profile_id,
        "tools_ready": True,
        "tool_probe_status": "verified",
        "capability_evidence": [
            {"name": "tools", "declared": True, "observed": True, "state": "verified"},
        ],
    }


def test_workspace_switch_does_not_inherit_previous_recovery(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    plan = LearningPlan(
        id="plan-a",
        title="Workspace A plan",
        current_stage_id="stage-a",
        current_step="Stay on workspace A",
        stages=[PlanStage(id="stage-a", title="A", goal="A", outcomes=["pass"], status="active")],
    )
    service.persist_plan_runtime_recovery("workspace-a", plan=plan, plan_runtime={"current_step": "Stay on workspace A"})
    service.persist_provider_capability_recovery("workspace-a", _provider_payload("profile-a"))
    service.persist_streaming_checkpoint(
        "workspace-a",
        request_id="stream-a",
        phase="streaming",
        provider_profile_id="profile-a",
        provider_name="minimax",
        base_url="http://example.test/v1",
        model="MiniMax-M2.7",
    )

    workspace_b = service.recover_workspace_facts("workspace-b")
    assert workspace_b["latest_plan_runtime"] is None
    assert workspace_b["latest_provider_capability"] is None
    assert workspace_b["latest_streaming_checkpoint"] is None

    workspace_a = service.recover_workspace_facts("workspace-a")
    assert workspace_a["latest_plan_runtime"] is not None
    assert workspace_a["latest_plan_runtime"]["workspace_id"] == "workspace-a"
    assert workspace_a["latest_provider_capability"]["provider_profile_id"] == "profile-a"
    assert workspace_a["latest_streaming_checkpoint"]["phase"] == "interrupted"


def test_workspace_switch_does_not_inherit_adopted_training_chrome(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    leftover = LearningPlan(
        id="plan-formal-old",
        title="Keep the current stage",
        current_step="Keep one auth check",
        stages=[
            PlanStage(id="stage-1", title="Auth", goal="Keep one check", outcomes=["pass"], status="active")
        ],
    )
    service.repository.save_plan("workspace-a", leftover)
    service.persist_plan_runtime_recovery(
        "workspace-a",
        plan_runtime={
            "current_step": "Add a token expiry test",
            "next_after_current": "Review the refresh path",
            "why_now": "Expired tokens still leak.",
            "resume_state": "in_progress",
            "plan_id": "",
        },
        request_id="chrome-scope-1",
    )
    structured = service._structured_for("workspace-a")
    structured.update_workspace(
        selected_card_title="Practice: Keep the current stage",
        latest_training_handoff={"card_title": "Practice: Keep the current stage"},
        latest_training_next_hop={
            "title": "Practice: Keep the current stage",
            "card_title": "Practice: Keep the current stage",
        },
    )
    item = service.enqueue_evidence(
        "workspace-a",
        EvidenceItem(
            summary="Return checks passed",
            source="training_handoff_return",
            outcome="pass",
            concepts=["Add a token expiry test"],
        ),
        verified=True,
        verification_source="ide_current_file",
    )
    service.adopt_evidence("workspace-a", item.id)
    recovered_a = service.recover_workspace_facts("workspace-a")
    assert recovered_a[TRAINING_CHROME_KEY] is not None
    assert recovered_a["selected_card_title"] == "Review the refresh path"
    assert recovered_a[PLAN_RUNTIME_KEY]["current_step"] == "Review the refresh path"

    recovered_b = service.recover_workspace_facts("workspace-b")
    assert recovered_b[PLAN_RUNTIME_KEY] is None
    assert recovered_b[TRAINING_CHROME_KEY] is None
    assert recovered_b["selected_card_title"] in {None, ""}
    assert recovered_b["latest_training_handoff"] is None
    assert "Review the refresh path" not in str(recovered_b.get("selected_card_title") or "")

    leaked = apply_training_chrome_scope(
        {
            "workspace_id": "workspace-b",
            "selected_card_title": "Review the refresh path",
            TRAINING_CHROME_KEY: recovered_a[TRAINING_CHROME_KEY],
            "latest_training_handoff": recovered_a["latest_training_handoff"],
            "latest_training_next_hop": recovered_a["latest_training_next_hop"],
        },
        "workspace-b",
    )
    assert leaked["selected_card_title"] in {None, ""}
    assert leaked["latest_training_handoff"] is None
    assert leaked[TRAINING_CHROME_KEY] is None

    restored_a = service.recover_workspace_facts("workspace-a")
    assert restored_a["selected_card_title"] == "Review the refresh path"
    assert restored_a[TRAINING_CHROME_KEY]["workspace_id"] == "workspace-a"
    assert service.repository.get_latest_plan("workspace-b") is None
    global_memory = service.global_memory()
    assert "Review the refresh path" not in global_memory.capability_profile
    assert all("error handling" not in record.concepts for record in global_memory.growth_history)
    assert normalize_training_chrome({"revision": 1}) is None
    assert select_training_chrome_for_scope(
        {"selected_card_title": "Review the refresh path"},
        "workspace-b",
    ) is None
    foreign_pending = scope_evidence_items_to_workspace(
        [EvidenceItem(summary="A pending", workspace_id="workspace-a", source="training_handoff_return")],
        "workspace-b",
    )
    assert foreign_pending == []


def test_workspace_switch_does_not_inherit_leftover_plan_or_resources(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    leftover = LearningPlan(
        id="plan-formal-old",
        title="Keep the current stage",
        current_step="Keep one auth check",
        summary="Leftover formal summary of the old stage path",
        stages=[
            PlanStage(id="stage-1", title="Auth", goal="Keep one check", outcomes=["pass"], status="active")
        ],
    )
    service.repository.save_plan("workspace-a", leftover)
    service.repository.save_resource(
        "workspace-a",
        ResourceRecord(
            id="resource-a",
            kind="markdown",
            name="Workspace A notes",
            source="notes.md",
            summary="A leftover resource",
        ),
    )

    snapshot_a = service.snapshot("workspace-a")
    assert snapshot_a.active_plan is not None
    assert snapshot_a.active_plan.title == "Keep the current stage"
    assert any(item.name == "Workspace A notes" for item in snapshot_a.resources)

    snapshot_b = service.snapshot("workspace-b")
    assert snapshot_b.active_plan is None
    assert snapshot_b.resources == []
    assert service.repository.get_latest_plan("workspace-b") is None
    assert formal_plan_identity_is_live({}) is False
    assert formal_plan_identity_is_live({"workspace_id": "workspace-a"}) is False
    assert normalize_formal_plan_identity({"revision": 1}) is None
    assert select_formal_plan_for_scope(leftover, "workspace-b") is None
    assert select_formal_plan_for_scope(
        {
            "workspace_id": "workspace-a",
            "id": leftover.id,
            "title": leftover.title,
            "summary": leftover.summary,
            "current_step": leftover.current_step,
        },
        "workspace-a",
    )["title"] == "Keep the current stage"
    assert (
        select_resources_for_scope(
            [{"workspace_id": "workspace-a", "title": "Workspace A notes"}],
            "workspace-b",
        )
        == []
    )
    unscoped_incoming = select_resources_for_scope(
        [{"title": "Unscoped incoming notes"}],
        "workspace-a",
    )
    assert unscoped_incoming[0]["title"] == "Unscoped incoming notes"

    restored_a = service.snapshot("workspace-a")
    assert restored_a.active_plan is not None
    assert restored_a.active_plan.title == "Keep the current stage"
    assert any(item.name == "Workspace A notes" for item in restored_a.resources)
    assert service.repository.get_latest_plan("workspace-a") is not None


def test_workspace_switch_does_not_inherit_leftover_current_task(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    leftover_task = TaskSpec(
        id="task-formal-old",
        title="Ship one auth check",
        natural_language_goal="Keep the leftover A task",
    )
    service.persist_turn_context_pressure("workspace-a", current_task=leftover_task)

    recovered_a = service.recover_workspace_facts("workspace-a")
    assert recovered_a[CURRENT_TASK_KEY] is not None
    assert recovered_a[CURRENT_TASK_KEY]["title"] == "Ship one auth check"
    assert recovered_a[CURRENT_TASK_KEY]["workspace_id"] == "workspace-a"

    recovered_b = service.recover_workspace_facts("workspace-b")
    assert recovered_b[CURRENT_TASK_KEY] is None
    snapshot_b = service.snapshot("workspace-b")
    assert select_latest_current_task(snapshot_b.workspace.get(CURRENT_TASK_KEY), "workspace-b") is None
    assert select_latest_current_task(
        {"title": "Ship one auth check", "natural_language_goal": "Keep the leftover A task"},
        "workspace-b",
    ) is None
    assert select_latest_current_task({"revision": 1}, "workspace-a") is None

    restored_a = service.recover_workspace_facts("workspace-a")
    assert restored_a[CURRENT_TASK_KEY]["title"] == "Ship one auth check"
    assert service.repository.get_latest_plan("workspace-b") is None


def test_coach_orientation_omits_stamped_foreign_leftover_plan() -> None:
    snapshot = SimpleNamespace(
        sidecar_status="ready",
        messages=[],
        provider=None,
        current_task=None,
        plan_runtime_status={},
        plan=SimpleNamespace(
            workspace_id="workspace-a",
            title="Keep the current stage",
            current_step="Keep one auth check",
            why_now="",
            next_after_current="",
            blocked_reason="",
            verify_method=[],
        ),
        memory=SimpleNamespace(
            workspace={"workspace_id": "workspace-b"},
            active_thread=None,
        ),
    )
    orientation = build_coach_orientation_from_snapshot(snapshot)
    object_label = str(orientation.get("object_label") or "")
    assert "Keep the current stage" not in object_label
    assert "Keep one auth check" not in object_label


def test_workspace_switch_does_not_inherit_leftover_coaching_focus(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    service.record_coaching_reflection(
        workspace_id="workspace-a",
        scenario="task",
        focus_area="Keep the leftover A coaching focus",
        summary="Keep the leftover A coaching summary",
        next_step="Stay on leftover A",
        teaching_note="Ship one auth check",
    )
    recovered_a = service.recover_workspace_facts("workspace-a")
    assert recovered_a[COACHING_FOCUS_KEY] is not None
    assert recovered_a[COACHING_FOCUS_KEY]["summary"] == "Keep the leftover A coaching summary"
    assert recovered_a[COACHING_FOCUS_KEY]["workspace_id"] == "workspace-a"

    recovered_b = service.recover_workspace_facts("workspace-b")
    assert recovered_b[COACHING_FOCUS_KEY] is None
    snapshot_b = service.snapshot("workspace-b")
    assert select_latest_coaching_focus(snapshot_b.workspace.get(COACHING_FOCUS_KEY), "workspace-b") is None
    assert "Keep the leftover A coaching focus" not in (snapshot_b.current_focus or "")
    assert "Keep the leftover A coaching summary" not in (snapshot_b.current_focus or "")
    assert snapshot_b.active_thread is None or "Keep the leftover A coaching" not in str(snapshot_b.active_thread)
    assert select_latest_coaching_focus(
        {
            "summary": "Keep the leftover A coaching summary",
            "focus_area": "Keep the leftover A coaching focus",
        },
        "workspace-b",
    ) is None
    assert select_latest_coaching_focus({"revision": 1}, "workspace-a") is None

    restored_a = service.recover_workspace_facts("workspace-a")
    assert restored_a[COACHING_FOCUS_KEY]["focus_area"] == "Keep the leftover A coaching focus"
    snapshot_a = service.snapshot("workspace-a")
    assert "Keep the leftover A coaching focus" in (snapshot_a.current_focus or "")


def test_workspace_switch_does_not_inherit_leftover_evaluation_chrome(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    service.record_evaluation_feedback(
        workspace_id="workspace-a",
        concepts=["Keep the leftover A evaluation headline"],
        failed_checks=["Keep the leftover A evaluation summary"],
        missing_requirements=["Stay on leftover A eval"],
    )
    service.persist_turn_context_pressure(
        "workspace-a",
        learner_state={
            "active_focus": "Keep the leftover A learner focus",
            "evidence": ["A leftover eval evidence"],
        },
        teaching_decision={
            "reason": "Keep the leftover A teaching reason",
            "primary_goal": "Keep the leftover A teaching goal",
            "teaching_strategy": "Stay on leftover A",
            "closing_move": "Keep one auth check",
        },
    )
    recovered_a = service.recover_workspace_facts("workspace-a")
    assert recovered_a[EVALUATION_KEY] is not None
    assert recovered_a[EVALUATION_KEY]["summary"] == "Keep the leftover A evaluation summary"
    assert recovered_a[EVALUATION_KEY]["workspace_id"] == "workspace-a"
    assert recovered_a[LEARNER_STATE_KEY]["active_focus"] == "Keep the leftover A learner focus"
    assert recovered_a[TEACHING_DECISION_KEY]["primary_goal"] == "Keep the leftover A teaching goal"

    recovered_b = service.recover_workspace_facts("workspace-b")
    assert recovered_b[EVALUATION_KEY] is None
    assert recovered_b[LEARNER_STATE_KEY] is None
    assert recovered_b[TEACHING_DECISION_KEY] is None
    snapshot_b = service.snapshot("workspace-b")
    assert select_latest_evaluation(snapshot_b.workspace.get(EVALUATION_KEY), "workspace-b") is None
    assert select_latest_learner_state(snapshot_b.workspace.get(LEARNER_STATE_KEY), "workspace-b") is None
    assert select_latest_teaching_decision(
        snapshot_b.workspace.get(TEACHING_DECISION_KEY),
        "workspace-b",
    ) is None
    assert "Keep the leftover A evaluation summary" not in " ".join(snapshot_b.recent_wins)
    assert "Keep the leftover A teaching goal" not in " ".join(snapshot_b.teaching_observations)
    assert select_latest_evaluation(
        {"summary": "Keep the leftover A evaluation summary"},
        "workspace-b",
    ) is None
    assert select_latest_evaluation({"revision": 1}, "workspace-a") is None
    assert select_latest_learner_state({"revision": 1}, "workspace-a") is None
    assert select_latest_teaching_decision({"revision": 1}, "workspace-a") is None

    restored_a = service.recover_workspace_facts("workspace-a")
    assert restored_a[EVALUATION_KEY]["headline"] == "Keep the leftover A evaluation headline"
    assert restored_a[LEARNER_STATE_KEY]["active_focus"] == "Keep the leftover A learner focus"
    assert restored_a[TEACHING_DECISION_KEY]["reason"] == "Keep the leftover A teaching reason"


def test_coach_orientation_omits_stamped_foreign_leftover_task() -> None:
    snapshot = SimpleNamespace(
        sidecar_status="ready",
        messages=[],
        provider=None,
        current_task=SimpleNamespace(
            workspace_id="workspace-a",
            title="Ship one auth check",
            natural_language_goal="Keep the leftover A task",
            metadata={"workspace_id": "workspace-a"},
        ),
        plan_runtime_status={},
        plan=None,
        memory=SimpleNamespace(
            workspace={"workspace_id": "workspace-b"},
            active_thread=None,
        ),
    )
    orientation = build_coach_orientation_from_snapshot(snapshot)
    rendered = str(orientation)
    assert "Ship one auth check" not in rendered
    assert "Keep the leftover A task" not in rendered


def test_coach_orientation_omits_stamped_foreign_leftover_focus() -> None:
    snapshot = SimpleNamespace(
        sidecar_status="ready",
        messages=[],
        provider=None,
        current_task=None,
        plan_runtime_status={},
        plan=None,
        memory=SimpleNamespace(
            workspace={"workspace_id": "workspace-b"},
            active_thread=SimpleNamespace(
                workspace_id="workspace-a",
                focus_area="Keep the leftover A coaching focus",
                summary="Keep the leftover A coaching summary",
            ),
        ),
    )
    orientation = build_coach_orientation_from_snapshot(snapshot)
    rendered = str(orientation)
    assert "Keep the leftover A coaching focus" not in rendered
    assert "Keep the leftover A coaching summary" not in rendered


def test_workspace_switch_does_not_inherit_leftover_affect_tone(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    service.persist_turn_context_pressure(
        "workspace-a",
        affect_state={
            "urgency_level": "high",
            "needs_reassurance": True,
            "frustration_level": 0.9,
            "confidence_level": 0.1,
            "momentum_level": 0.2,
            "recovery_signal": "Keep the leftover A affect",
        },
        tone_decision={
            "tone": "concise_rescue",
            "verbosity_bias": "short",
            "acknowledge_progress": True,
            "avoid_overwhelm": True,
        },
    )
    recovered_a = service.recover_workspace_facts("workspace-a")
    assert recovered_a[AFFECT_STATE_KEY] is not None
    assert recovered_a[AFFECT_STATE_KEY]["urgency_level"] == "high"
    assert recovered_a[AFFECT_STATE_KEY]["workspace_id"] == "workspace-a"
    assert recovered_a[AFFECT_STATE_KEY]["recovery_signal"] == "Keep the leftover A affect"
    assert recovered_a[TONE_DECISION_KEY]["tone"] == "concise_rescue"

    recovered_b = service.recover_workspace_facts("workspace-b")
    assert recovered_b[AFFECT_STATE_KEY] is None
    assert recovered_b[TONE_DECISION_KEY] is None
    snapshot_b = service.snapshot("workspace-b")
    assert select_latest_affect_state(snapshot_b.workspace.get(AFFECT_STATE_KEY), "workspace-b") is None
    assert select_latest_tone_decision(snapshot_b.workspace.get(TONE_DECISION_KEY), "workspace-b") is None
    assert select_latest_affect_state(
        {"urgency_level": "high", "needs_reassurance": True, "recovery_signal": "Keep the leftover A affect"},
        "workspace-b",
    ) is None
    assert select_latest_affect_state({"revision": 1}, "workspace-a") is None
    assert select_latest_tone_decision({"revision": 1}, "workspace-a") is None

    restored_a = service.recover_workspace_facts("workspace-a")
    assert restored_a[AFFECT_STATE_KEY]["needs_reassurance"] is True
    assert restored_a[TONE_DECISION_KEY]["acknowledge_progress"] is True


def test_workspace_switch_does_not_inherit_leftover_teaching_artifacts(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    service.persist_turn_context_pressure(
        "workspace-a",
        adaptation_guide={
            "target_outcome": "Keep the leftover A adaptation outcome",
            "first_migration_step": "Keep the leftover A adaptation step",
        },
        project_sources=[
            {
                "title": "Keep the leftover A project source",
                "fit_reason": "A leftover project source",
            }
        ],
        principle_notes={
            "current_principle": "Keep the leftover A principle",
            "why_it_matters": "Keep the leftover A principle why",
            "apply_now": "Keep the leftover A principle apply",
        },
    )
    recovered_a = service.recover_workspace_facts("workspace-a")
    assert recovered_a[ADAPTATION_GUIDE_KEY] is not None
    assert recovered_a[ADAPTATION_GUIDE_KEY]["target_outcome"] == "Keep the leftover A adaptation outcome"
    assert recovered_a[ADAPTATION_GUIDE_KEY]["workspace_id"] == "workspace-a"
    assert recovered_a[PROJECT_SOURCES_KEY]["sources"][0]["title"] == "Keep the leftover A project source"
    assert recovered_a[PRINCIPLE_NOTES_KEY]["current_principle"] == "Keep the leftover A principle"

    recovered_b = service.recover_workspace_facts("workspace-b")
    assert recovered_b[ADAPTATION_GUIDE_KEY] is None
    assert recovered_b[PROJECT_SOURCES_KEY] is None
    assert recovered_b[PRINCIPLE_NOTES_KEY] is None
    snapshot_b = service.snapshot("workspace-b")
    assert select_latest_adaptation_guide(snapshot_b.workspace.get(ADAPTATION_GUIDE_KEY), "workspace-b") is None
    assert select_latest_project_sources(snapshot_b.workspace.get(PROJECT_SOURCES_KEY), "workspace-b") is None
    assert select_latest_principle_notes(snapshot_b.workspace.get(PRINCIPLE_NOTES_KEY), "workspace-b") is None
    assert (
        select_latest_adaptation_guide(
            {
                "target_outcome": "Keep the leftover A adaptation outcome",
                "first_migration_step": "Keep the leftover A adaptation step",
            },
            "workspace-b",
        )
        is None
    )
    assert select_latest_adaptation_guide({"revision": 1}, "workspace-a") is None
    assert select_latest_project_sources({"revision": 1}, "workspace-a") is None
    assert select_latest_principle_notes({"revision": 1}, "workspace-a") is None

    restored_a = service.recover_workspace_facts("workspace-a")
    assert restored_a[ADAPTATION_GUIDE_KEY]["first_migration_step"] == "Keep the leftover A adaptation step"
    assert restored_a[PROJECT_SOURCES_KEY]["sources"][0]["fit_reason"] == "A leftover project source"
    assert restored_a[PRINCIPLE_NOTES_KEY]["apply_now"] == "Keep the leftover A principle apply"


def test_workspace_switch_does_not_inherit_leftover_coach_focus(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    service.persist_turn_context_pressure(
        "workspace-a",
        coach_focus={
            "current_focus": "Keep the leftover A coach focus",
            "next_step": "Stay on leftover A",
            "first_turn_priority": "Keep the leftover A recommended",
            "continuity_summary": "Keep the leftover A coach focus summary",
            "strategy_preference_summary": "Keep the leftover A coach focus recommended",
        },
    )
    recovered_a = service.recover_workspace_facts("workspace-a")
    assert recovered_a[COACH_FOCUS_KEY] is not None
    assert recovered_a[COACH_FOCUS_KEY]["current_focus"] == "Keep the leftover A coach focus"
    assert recovered_a[COACH_FOCUS_KEY]["workspace_id"] == "workspace-a"
    assert recovered_a[COACH_FOCUS_KEY]["first_turn_priority"] == "Keep the leftover A recommended"
    assert recovered_a[COACH_FOCUS_KEY]["continuity_summary"] == "Keep the leftover A coach focus summary"

    recovered_b = service.recover_workspace_facts("workspace-b")
    assert recovered_b[COACH_FOCUS_KEY] is None
    snapshot_b = service.snapshot("workspace-b")
    assert select_latest_coach_focus(snapshot_b.workspace.get(COACH_FOCUS_KEY), "workspace-b") is None
    assert (
        select_latest_coach_focus(
            {
                "current_focus": "Keep the leftover A coach focus",
                "first_turn_priority": "Keep the leftover A recommended",
                "continuity_summary": "Keep the leftover A coach focus summary",
            },
            "workspace-b",
        )
        is None
    )
    assert select_latest_coach_focus({"revision": 1}, "workspace-a") is None

    restored_a = service.recover_workspace_facts("workspace-a")
    assert restored_a[COACH_FOCUS_KEY]["current_focus"] == "Keep the leftover A coach focus"
    assert restored_a[COACH_FOCUS_KEY]["first_turn_priority"] == "Keep the leftover A recommended"


def test_workspace_switch_does_not_inherit_leftover_coach_turn(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    service.persist_turn_context_pressure(
        "workspace-a",
        coach_turn={
            "summary": "Keep the leftover A coach turn summary",
            "next_step": "Keep the leftover A coach turn next",
            "teaching_goal": "Keep the leftover A coach turn goal",
        },
    )
    recovered_a = service.recover_workspace_facts("workspace-a")
    assert recovered_a[COACH_TURN_KEY] is not None
    assert recovered_a[COACH_TURN_KEY]["summary"] == "Keep the leftover A coach turn summary"
    assert recovered_a[COACH_TURN_KEY]["workspace_id"] == "workspace-a"

    recovered_b = service.recover_workspace_facts("workspace-b")
    assert recovered_b[COACH_TURN_KEY] is None
    assert (
        select_latest_coach_turn(
            {
                "summary": "Keep the leftover A coach turn summary",
                "next_step": "Keep the leftover A coach turn next",
            },
            "workspace-b",
        )
        is None
    )
    assert select_latest_coach_turn({"revision": 1}, "workspace-a") is None

    restored_a = service.recover_workspace_facts("workspace-a")
    assert restored_a[COACH_TURN_KEY]["teaching_goal"] == "Keep the leftover A coach turn goal"


def test_workspace_switch_does_not_inherit_leftover_next_step_hint(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    service.persist_turn_context_pressure(
        "workspace-a",
        next_step_hint={
            "title": "Keep the leftover A next-step hint",
            "summary": "Keep the leftover A next-step summary",
            "recommended_action": "task",
        },
    )
    recovered_a = service.recover_workspace_facts("workspace-a")
    assert recovered_a[NEXT_STEP_HINT_KEY] is not None
    assert recovered_a[NEXT_STEP_HINT_KEY]["title"] == "Keep the leftover A next-step hint"
    assert recovered_a[NEXT_STEP_HINT_KEY]["workspace_id"] == "workspace-a"
    assert recovered_a[NEXT_STEP_HINT_KEY]["summary"] == "Keep the leftover A next-step summary"

    recovered_b = service.recover_workspace_facts("workspace-b")
    assert recovered_b[NEXT_STEP_HINT_KEY] is None
    snapshot_b = service.snapshot("workspace-b")
    assert select_latest_next_step_hint(snapshot_b.workspace.get(NEXT_STEP_HINT_KEY), "workspace-b") is None
    assert (
        select_latest_next_step_hint(
            {
                "title": "Keep the leftover A next-step hint",
                "summary": "Keep the leftover A next-step summary",
                "recommended_action": "task",
            },
            "workspace-b",
        )
        is None
    )
    assert select_latest_next_step_hint({"revision": 1}, "workspace-a") is None

    restored_a = service.recover_workspace_facts("workspace-a")
    assert restored_a[NEXT_STEP_HINT_KEY]["recommended_action"] == "task"


def test_workspace_switch_does_not_inherit_leftover_coaching_adaptation(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    service.persist_turn_context_pressure(
        "workspace-a",
        coaching_adaptation={
            "summary": "Keep the leftover A adaptation summary",
            "evidence": ["Keep the leftover A adaptation evidence"],
        },
    )
    recovered_a = service.recover_workspace_facts("workspace-a")
    assert recovered_a[COACHING_ADAPTATION_KEY] is not None
    assert recovered_a[COACHING_ADAPTATION_KEY]["summary"] == "Keep the leftover A adaptation summary"
    assert recovered_a[COACHING_ADAPTATION_KEY]["workspace_id"] == "workspace-a"
    assert recovered_a[COACHING_ADAPTATION_KEY]["evidence"] == ["Keep the leftover A adaptation evidence"]

    recovered_b = service.recover_workspace_facts("workspace-b")
    assert recovered_b[COACHING_ADAPTATION_KEY] is None
    snapshot_b = service.snapshot("workspace-b")
    assert select_latest_coaching_adaptation(
        snapshot_b.workspace.get(COACHING_ADAPTATION_KEY),
        "workspace-b",
    ) is None
    assert (
        select_latest_coaching_adaptation(
            {
                "summary": "Keep the leftover A adaptation summary",
                "evidence": ["Keep the leftover A adaptation evidence"],
            },
            "workspace-b",
        )
        is None
    )
    assert select_latest_coaching_adaptation({"revision": 1}, "workspace-a") is None

    restored_a = service.recover_workspace_facts("workspace-a")
    assert restored_a[COACHING_ADAPTATION_KEY]["evidence"] == ["Keep the leftover A adaptation evidence"]
    if snapshot_b.coaching_adaptation is not None:
        assert "Keep the leftover A adaptation summary" not in snapshot_b.coaching_adaptation.summary
        assert "Keep the leftover A adaptation evidence" not in " ".join(
            snapshot_b.coaching_adaptation.evidence
        )


def test_coach_orientation_omits_stamped_foreign_leftover_evaluation() -> None:
    snapshot = SimpleNamespace(
        sidecar_status="ready",
        messages=[],
        provider=None,
        current_task=None,
        plan_runtime_status={},
        plan=None,
        evaluation=SimpleNamespace(
            workspace_id="workspace-a",
            summary="Keep the leftover A evaluation summary",
            next_step="Stay on leftover A eval",
        ),
        learner_state=SimpleNamespace(
            workspace_id="workspace-a",
            active_focus="Keep the leftover A learner focus",
        ),
        teaching_decision=SimpleNamespace(
            workspace_id="workspace-a",
            reason="Keep the leftover A teaching reason",
            primary_goal="Keep the leftover A teaching goal",
        ),
        memory=SimpleNamespace(
            workspace={"workspace_id": "workspace-b"},
            active_thread=None,
        ),
    )
    orientation = build_coach_orientation_from_snapshot(snapshot)
    rendered = str(orientation)
    assert "Keep the leftover A evaluation summary" not in rendered
    assert "Stay on leftover A eval" not in rendered
    assert "Keep the leftover A learner focus" not in rendered
    assert "Keep the leftover A teaching goal" not in rendered


def test_coach_orientation_omits_stamped_foreign_leftover_affect_tone() -> None:
    snapshot = SimpleNamespace(
        sidecar_status="ready",
        messages=[],
        provider=None,
        current_task=None,
        plan_runtime_status={},
        plan=None,
        affect_state=SimpleNamespace(
            workspace_id="workspace-a",
            urgency_level="high",
            recovery_signal="Keep the leftover A affect",
            needs_reassurance=True,
        ),
        tone_decision=SimpleNamespace(
            workspace_id="workspace-a",
            tone="concise_rescue",
            verbosity_bias="short",
        ),
        memory=SimpleNamespace(
            workspace={"workspace_id": "workspace-b"},
            active_thread=None,
        ),
    )
    orientation = build_coach_orientation_from_snapshot(snapshot)
    rendered = str(orientation)
    assert "Keep the leftover A affect" not in rendered
    assert "concise_rescue" not in rendered


def test_coach_orientation_omits_stamped_foreign_leftover_teaching_artifacts() -> None:
    snapshot = SimpleNamespace(
        sidecar_status="ready",
        messages=[],
        provider=None,
        current_task=None,
        plan_runtime_status={},
        plan=None,
        project_adaptation_guide=SimpleNamespace(
            workspace_id="workspace-a",
            target_outcome="Keep the leftover A adaptation outcome",
            first_migration_step="Keep the leftover A adaptation step",
        ),
        project_sources=[
            SimpleNamespace(
                workspace_id="workspace-a",
                title="Keep the leftover A project source",
                fit_reason="A leftover project source",
            )
        ],
        principle_notes=SimpleNamespace(
            workspace_id="workspace-a",
            current_principle="Keep the leftover A principle",
            why_it_matters="Keep the leftover A principle why",
            apply_now="Keep the leftover A principle apply",
        ),
        memory=SimpleNamespace(
            workspace={"workspace_id": "workspace-b"},
            active_thread=None,
        ),
    )
    orientation = build_coach_orientation_from_snapshot(snapshot)
    rendered = str(orientation)
    assert "Keep the leftover A adaptation outcome" not in rendered
    assert "Keep the leftover A adaptation step" not in rendered
    assert "Keep the leftover A project source" not in rendered
    assert "Keep the leftover A principle" not in rendered
    assert "Keep the leftover A principle apply" not in rendered


def test_coach_orientation_omits_stamped_foreign_leftover_coach_focus() -> None:
    snapshot = SimpleNamespace(
        sidecar_status="ready",
        messages=[],
        provider=None,
        current_task=None,
        plan_runtime_status={},
        plan=None,
        coach_focus=SimpleNamespace(
            workspace_id="workspace-a",
            current_focus="Keep the leftover A coach focus",
            first_turn_priority="Keep the leftover A recommended",
            continuity_summary="Keep the leftover A coach focus summary",
            strategy_preference_summary="Keep the leftover A coach focus recommended",
        ),
        memory=SimpleNamespace(
            workspace={"workspace_id": "workspace-b"},
            active_thread=None,
        ),
    )
    orientation = build_coach_orientation_from_snapshot(snapshot)
    rendered = str(orientation)
    assert "Keep the leftover A coach focus" not in rendered
    assert "Keep the leftover A recommended" not in rendered
    assert "Keep the leftover A coach focus summary" not in rendered


def test_coach_orientation_omits_stamped_foreign_leftover_next_step_hint() -> None:
    snapshot = SimpleNamespace(
        sidecar_status="ready",
        messages=[],
        provider=None,
        current_task=None,
        plan_runtime_status={},
        plan=None,
        next_step_hint={
            "workspace_id": "workspace-a",
            "title": "Keep the leftover A next-step hint",
            "summary": "Keep the leftover A next-step summary",
            "recommended_action": "task",
        },
        memory=SimpleNamespace(
            workspace={"workspace_id": "workspace-b"},
            active_thread=None,
        ),
    )
    orientation = build_coach_orientation_from_snapshot(snapshot)
    rendered = str(orientation)
    assert "Keep the leftover A next-step hint" not in rendered
    assert "Keep the leftover A next-step summary" not in rendered


def test_coach_orientation_omits_stamped_foreign_leftover_coaching_adaptation() -> None:
    snapshot = SimpleNamespace(
        sidecar_status="ready",
        messages=[],
        provider=None,
        current_task=None,
        plan_runtime_status={},
        plan=None,
        memory=SimpleNamespace(
            workspace={"workspace_id": "workspace-b"},
            active_thread=None,
            coaching_adaptation=SimpleNamespace(
                workspace_id="workspace-a",
                summary="Keep the leftover A adaptation summary",
                evidence=["Keep the leftover A adaptation evidence"],
                challenge_level="raise",
                next_step_bias="widen",
            ),
        ),
    )
    orientation = build_coach_orientation_from_snapshot(snapshot)
    rendered = str(orientation)
    assert "Keep the leftover A adaptation summary" not in rendered
    assert "Keep the leftover A adaptation evidence" not in rendered


def test_provider_switch_does_not_inherit_previous_last_test_or_stream(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    service.persist_provider_capability_recovery("workspace-shared", _provider_payload("profile-a"))
    service.persist_streaming_checkpoint(
        "workspace-shared",
        request_id="stream-a",
        phase="interrupted",
        provider_profile_id="profile-a",
        provider_name="minimax",
        base_url="http://example.test/v1",
        model="MiniMax-M2.7",
    )

    scoped_b = service.recover_workspace_facts_for_scope(
        "workspace-shared",
        provider_profile_id="profile-b",
        provider_name="minimax",
        base_url="http://example.test/v1",
        model="MiniMax-M2.7",
    )
    assert scoped_b["latest_provider_capability"] is None
    assert scoped_b["latest_streaming_checkpoint"] is None

    scoped_a = service.recover_workspace_facts_for_scope(
        "workspace-shared",
        provider_profile_id="profile-a",
        provider_name="minimax",
        base_url="http://example.test/v1",
        model="MiniMax-M2.7",
    )
    assert scoped_a["latest_provider_capability"] is not None
    assert scoped_a["latest_provider_capability"]["ok"] is True
    assert scoped_a["latest_streaming_checkpoint"]["request_id"] == "stream-a"


def test_unscoped_records_are_not_current_for_another_workspace() -> None:
    record = {
        "revision": 1,
        "workspace_id": "workspace-a",
        "plan_id": "plan-a",
        "current_step": "Stay on A",
        "frozen": False,
        "verify_method": [],
    }
    assert select_plan_runtime_for_scope(record, "workspace-b") is None
    assert select_provider_capability_for_scope(
        {**_provider_payload("profile-a"), "workspace_id": "workspace-a"},
        workspace_id="workspace-b",
        provider_profile_id="profile-a",
    ) is None
    assert select_streaming_checkpoint_for_scope(
        {
            "revision": 1,
            "workspace_id": "workspace-a",
            "provider_profile_id": "profile-a",
            "request_id": "stream-a",
            "phase": "interrupted",
        },
        workspace_id="workspace-b",
        provider_profile_id="profile-a",
    ) is None


def test_resume_request_binds_recovered_step_and_blocker() -> None:
    recovered = {
        "recovered": True,
        "current_step": "Keep one auth check",
        "current_stage_id": "step-auth-1",
        "blocked_reason": "The auth guard still fails on expired tokens.",
        "why_now": "Expired tokens still leak the session.",
        "current_stage": None,
    }
    continue_step = accept_plan_runtime_resume_request(
        {
            "action": "continue_step",
            "recovered": True,
            "currentStep": "Keep one auth check",
            "currentStepId": "step-auth-1",
            "formalPlanMutation": False,
        },
        recovered_status=recovered,
    )
    assert continue_step is not None
    assert continue_step["action"] == "continue_step"
    assert continue_step["current_step"] == "Keep one auth check"
    assert continue_step["current_step_id"] == "step-auth-1"
    assert continue_step["formal_plan_mutation"] is False
    clear_blocker = accept_plan_runtime_resume_request(
        {
            "action": "clear_blocker",
            "recovered": True,
            "blockedReason": "The auth guard still fails on expired tokens.",
            "currentStep": "Keep one auth check",
        },
        recovered_status=recovered,
    )
    assert clear_blocker is not None
    assert clear_blocker["blocked_reason"] == "The auth guard still fails on expired tokens."
    assert clear_blocker["formal_plan_mutation"] is False
    assert accept_plan_runtime_resume_request(
        {
            "action": "continue_step",
            "recovered": True,
            "currentStep": "Invented theater step",
        },
        recovered_status=recovered,
    ) is None
    assert accept_plan_runtime_resume_request(
        {
            "action": "continue_step",
            "recovered": True,
            "currentStep": "Keep one auth check",
            "formalPlanMutation": True,
        },
        recovered_status=recovered,
    ) is None
    assert accept_plan_runtime_resume_request(
        {
            "action": "continue_step",
            "recovered": True,
            "currentStep": "Keep one auth check",
        },
        recovered_status={"current_step": "Keep one auth check"},
    ) is None
    assert accept_plan_runtime_resume_request(
        {
            "action": "generate_plan",
            "recovered": True,
            "currentStep": "Keep one auth check",
        },
        recovered_status=recovered,
    ) is None


def test_resume_persist_stamps_request_id_and_fails_closed_on_workspace_mismatch() -> None:
    existing = {
        "revision": 1,
        "workspace_id": "workspace-plan",
        "current_step": "Keep one auth check",
        "blocked_reason": "The auth guard still fails on expired tokens.",
        "resume_state": "interrupted",
        "verify_method": [],
    }
    accepted = {
        "action": "continue_step",
        "recovered": True,
        "current_step": "Keep one auth check",
        "blocked_reason": "The auth guard still fails on expired tokens.",
        "formal_plan_mutation": False,
    }
    stamped = build_plan_runtime_resume(
        existing=existing,
        accepted=accepted,
        request_id="plan-resume-continue-1",
        workspace_id="workspace-plan",
    )
    assert stamped is not None
    assert stamped["request_id"] == "plan-resume-continue-1"
    assert stamped["revision"] == 2
    assert stamped["resume_state"] == "in_progress"
    assert stamped["current_step"] == "Keep one auth check"
    assert stamped["workspace_id"] == "workspace-plan"
    assert build_plan_runtime_resume(
        existing=existing,
        accepted=accepted,
        request_id="plan-resume-continue-1",
        workspace_id="workspace-other",
    ) is None
    assert build_plan_runtime_resume(
        existing=existing,
        accepted=accepted,
        request_id="",
        workspace_id="workspace-plan",
    ) is None
    assert recovered_resume_turn_succeeded(reply_content="Stay on the check.") is True
    assert recovered_resume_turn_succeeded(reply_content="", stop_reason="completed") is False
    assert recovered_resume_turn_succeeded(
        reply_content="Stay on the check.",
        stop_reason="timeout",
    ) is False


def test_resume_persist_overlays_structured_reply_facts_and_fails_closed_without_them() -> None:
    existing = {
        "revision": 2,
        "workspace_id": "workspace-plan",
        "current_step": "Keep one auth check",
        "blocked_reason": "The auth guard still fails on expired tokens.",
        "why_now": "Expired tokens still leak the session.",
        "next_after_current": "Return with the focused test.",
        "resume_state": "in_progress",
        "verify_method": [],
    }
    accepted = {
        "action": "continue_step",
        "recovered": True,
        "current_step": "Keep one auth check",
        "blocked_reason": "The auth guard still fails on expired tokens.",
        "why_now": "Expired tokens still leak the session.",
        "formal_plan_mutation": False,
    }
    assert extract_structured_plan_runtime_facts(None) is None
    assert extract_structured_plan_runtime_facts({"stop_reason": "completed"}) is None
    assert extract_structured_plan_runtime_facts("Add a token expiry test in prose.") is None
    facts = extract_structured_plan_runtime_facts(
        {
            "next_step": "Add a token expiry test",
            "blocker": "Token refresh still returns 401.",
            "summary": "Expired tokens still leak the session.",
            "next_after_current": "Wire the guard into the login path.",
        }
    )
    assert facts == {
        "current_step": "Add a token expiry test",
        "blocked_reason": "Token refresh still returns 401.",
        "why_now": "Expired tokens still leak the session.",
        "next_after_current": "Wire the guard into the login path.",
    }
    stamped = build_plan_runtime_resume(
        existing=existing,
        accepted=accepted,
        request_id="plan-resume-facts-1",
        workspace_id="workspace-plan",
        reply_facts=facts,
    )
    assert stamped is not None
    assert stamped["current_step"] == "Add a token expiry test"
    assert stamped["blocked_reason"] == "Token refresh still returns 401."
    assert stamped["why_now"] == "Expired tokens still leak the session."
    assert stamped["next_after_current"] == "Wire the guard into the login path."
    assert stamped["resume_state"] == "in_progress"
    kept = build_plan_runtime_resume(
        existing=existing,
        accepted=accepted,
        request_id="plan-resume-facts-2",
        workspace_id="workspace-plan",
        reply_facts=None,
    )
    assert kept is not None
    assert kept["current_step"] == "Keep one auth check"
    assert kept["blocked_reason"] == "The auth guard still fails on expired tokens."
    assert kept["next_after_current"] == "Return with the focused test."
    assert kept["resume_state"] == "in_progress"
    recovered = {
        "recovered": True,
        "resume_state": "in_progress",
        "current_step": "Keep one auth check",
        "blocked_reason": "The auth guard still fails on expired tokens.",
    }
    follow = accept_in_progress_plan_runtime_turn(
        intent="plan",
        formal_plan_mutation=False,
        recovered_status=recovered,
    )
    assert follow is not None
    assert follow["action"] == "clear_blocker"
    assert follow["current_step"] == "Keep one auth check"
    assert accept_in_progress_plan_runtime_turn(
        intent="coach",
        formal_plan_mutation=False,
        recovered_status=recovered,
    ) is None
    interrupted = accept_in_progress_plan_runtime_turn(
        intent="plan",
        formal_plan_mutation=False,
        recovered_status={**recovered, "resume_state": "interrupted"},
    )
    assert interrupted is not None
    assert interrupted["current_step"] == "Keep one auth check"
    assert accept_in_progress_plan_runtime_turn(
        intent="plan",
        formal_plan_mutation=True,
        recovered_status=recovered,
    ) is None


def test_structured_finish_leaves_in_progress_and_keeps_verify_method() -> None:
    existing = {
        "revision": 2,
        "workspace_id": "workspace-plan",
        "current_step": "Keep one auth check",
        "why_now": "Expired tokens still leak the session.",
        "resume_state": "in_progress",
        "verify_method": [],
    }
    accepted = {
        "action": "continue_step",
        "recovered": True,
        "current_step": "Keep one auth check",
        "why_now": "Expired tokens still leak the session.",
        "formal_plan_mutation": False,
    }
    assert structured_plan_step_finished({"decision": "The auth check is done, please verify."}) is False
    assert structured_plan_step_finished({"stop_reason": "completed"}) is False
    assert structured_plan_step_finished({"decision": "verify"}) is True
    assert structured_plan_step_finished({"learning_phase": "verify"}) is True
    assert extract_structured_verify_method({"evidence": ["Run the focused auth check"]}) == [
        "Run the focused auth check"
    ]
    assert extract_structured_verify_method({"summary": "Run pytest on auth.py"}) == []
    unfinished = extract_structured_plan_runtime_facts(
        {
            "next_step": "Keep one auth check",
            "decision": "The auth check is done, please verify.",
            "evidence": ["Run the focused auth check"],
        }
    )
    assert unfinished is not None
    assert unfinished.get("resume_state") != "waiting"
    assert unfinished["verify_method"] == ["Run the focused auth check"]
    kept = build_plan_runtime_resume(
        existing=existing,
        accepted=accepted,
        request_id="plan-resume-unfinished-1",
        workspace_id="workspace-plan",
        reply_facts=unfinished,
    )
    assert kept is not None
    assert kept["resume_state"] == "in_progress"
    assert kept["verify_method"] == ["Run the focused auth check"]
    finished = extract_structured_plan_runtime_facts(
        {
            "next_step": "Keep one auth check",
            "decision": "verify",
            "verify_method": ["Run the focused auth check"],
        }
    )
    assert finished is not None
    assert finished["resume_state"] == "waiting"
    assert finished["verify_method"] == ["Run the focused auth check"]
    stamped = build_plan_runtime_resume(
        existing=existing,
        accepted=accepted,
        request_id="plan-resume-finished-1",
        workspace_id="workspace-plan",
        reply_facts=finished,
    )
    assert stamped is not None
    assert stamped["resume_state"] == "waiting"
    assert stamped["resume_state"] != "in_progress"
    assert stamped["verify_method"] == ["Run the focused auth check"]
    assert stamped.get("plan_id") in {None, ""}
    status = plan_runtime_status_from_recovery(stamped, "workspace-plan")
    assert status is not None
    assert status["resume_state"] == "waiting"
    assert status["verify_method"] == ["Run the focused auth check"]


def test_waiting_verify_evidence_uses_structured_method_only() -> None:
    waiting = {
        "workspace_id": "workspace-plan",
        "current_step": "Keep one auth check",
        "verify_method": ["Run the focused auth check"],
        "resume_state": "waiting",
    }
    payload = build_waiting_verify_evidence(runtime=waiting, workspace_id="workspace-plan")
    assert payload is not None
    assert payload["summary"] == "Run the focused auth check"
    assert payload["source"] == WAITING_VERIFY_EVIDENCE_SOURCE
    assert payload["concepts"] == ["Keep one auth check"]
    assert payload["outcome"] == "partial"
    assert payload["verification_source"] == "Run the focused auth check"
    assert (
        build_waiting_verify_evidence(
            runtime={**waiting, "verify_method": []},
            workspace_id="workspace-plan",
        )
        is None
    )
    assert (
        build_waiting_verify_evidence(
            runtime={**waiting, "resume_state": "in_progress"},
            workspace_id="workspace-plan",
        )
        is None
    )
    assert (
        build_waiting_verify_evidence(runtime=waiting, workspace_id="workspace-other") is None
    )
    attest = attest_waiting_verify_on_adopt(
        {"source": WAITING_VERIFY_EVIDENCE_SOURCE, "summary": "Run the focused auth check"}
    )
    assert attest["verified"] is True
    assert attest["outcome"] == "pass"
    assert attest_waiting_verify_on_adopt({"source": "card_result", "summary": "Invented"}) == {}


def test_verified_adopt_advances_to_structured_next_and_leaves_waiting() -> None:
    waiting = {
        "revision": 3,
        "workspace_id": "workspace-plan",
        "current_step": "Keep one auth check",
        "current_stage_id": "stage-1",
        "why_now": "Expired tokens still leak the session.",
        "next_after_current": "Add a token expiry test",
        "verify_method": ["Run the focused auth check"],
        "resume_state": "waiting",
    }
    evidence = {
        "id": "ev-auth-pass-1",
        "adopted": True,
        "outcome": "pass",
        "verified": True,
    }
    assert verified_adopt_allows_runtime_advance(evidence) is True
    advanced = build_plan_runtime_advance_after_adopt(
        existing=waiting,
        evidence=evidence,
        request_id="ev-auth-pass-1",
        workspace_id="workspace-plan",
    )
    assert advanced is not None
    assert advanced["current_step"] == "Add a token expiry test"
    assert advanced.get("next_after_current") in {None, ""}
    assert advanced["resume_state"] == "in_progress"
    assert advanced["resume_state"] != "waiting"
    assert advanced["verify_method"] == []
    assert advanced.get("why_now") in {None, ""}
    assert advanced.get("why_now") != "Expired tokens still leak the session."
    assert advanced.get("blocked_reason") in {None, ""}
    assert advanced.get("next_why_now") in {None, ""}
    assert advanced.get("evidence_binding") in {None, ""}
    assert advanced.get("current_stage_id") in {None, ""}
    assert live_evidence_binding(
        binding="ev-auth-pass-1",
        pending_ids=[],
        recovered=True,
        current_step="Add a token expiry test",
    ) == ""
    assert advanced.get("plan_id") in {None, ""}
    status = plan_runtime_status_from_recovery(advanced, "workspace-plan")
    assert status is not None
    assert status["resume_state"] == "in_progress"
    assert status["current_step"] == "Add a token expiry test"
    assert not status.get("next_after_current")
    assert not status.get("why_now")
    assert status.get("plan_id") in {None, ""}


def test_leftover_adopted_binding_is_not_live_review(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    workspace_id = "workspace-plan-leftover-binding"
    leftover_id = "ev-old-auth"
    persisted = service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Add a token expiry test",
            "resume_state": "in_progress",
        },
        evidence_binding=leftover_id,
        request_id="plan-leftover-binding-1",
    )
    assert persisted is not None
    assert persisted["evidence_binding"] == leftover_id
    restored = service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
    assert restored["evidence_binding"] == leftover_id
    assert (
        live_evidence_binding(
            binding=restored.get("evidence_binding") or "",
            pending_ids=[item.id for item in service.evidence_queue(workspace_id).pending],
            recovered=True,
            current_step=restored["current_step"],
        )
        == ""
    )
    assert service.evidence_queue(workspace_id).pending == []
    assert service.repository.get_latest_plan(workspace_id) is None


def test_advance_uses_structured_next_why_and_does_not_invent_from_prose() -> None:
    waiting = {
        "workspace_id": "workspace-plan",
        "current_step": "Keep one auth check",
        "blocked_reason": "The auth guard still fails on expired tokens.",
        "why_now": "Expired tokens still leak the session.",
        "next_after_current": "Add a token expiry test",
        "next_why_now": "Expiry cases still skip the refresh path.",
        "verify_method": ["Run the focused auth check"],
        "resume_state": "waiting",
    }
    evidence = {
        "id": "ev-auth-pass-next-why",
        "adopted": True,
        "outcome": "pass",
        "verified": True,
    }
    assert extract_structured_next_step_runtime_facts(
        {"summary": "Invent a why from this prose.", "why_now": "Expired tokens still leak the session."}
    ) == {}
    facts = extract_structured_plan_runtime_facts(
        {
            "decision": "verify",
            "next_after_current": "Add a token expiry test",
            "summary": "Expired tokens still leak the session.",
            "next_why_now": "Expiry cases still skip the refresh path.",
        }
    )
    assert facts is not None
    assert facts["why_now"] == "Expired tokens still leak the session."
    assert facts["next_why_now"] == "Expiry cases still skip the refresh path."
    advanced = build_plan_runtime_advance_after_adopt(
        existing=waiting,
        evidence=evidence,
        request_id="ev-auth-pass-next-why",
        workspace_id="workspace-plan",
    )
    assert advanced is not None
    assert advanced["current_step"] == "Add a token expiry test"
    assert advanced["why_now"] == "Expiry cases still skip the refresh path."
    assert advanced["why_now"] != "Expired tokens still leak the session."
    assert advanced.get("blocked_reason") in {None, ""}
    assert advanced["verify_method"] == []
    assert advanced.get("next_after_current") in {None, ""}
    assert advanced.get("next_why_now") in {None, ""}
    assert advanced.get("plan_id") in {None, ""}
    status = plan_runtime_status_from_recovery(advanced, "workspace-plan")
    assert status is not None
    assert status["why_now"] == "Expiry cases still skip the refresh path."
    assert status["current_step"] == "Add a token expiry test"
    assert not status.get("blocked_reason")
    assert not status.get("next_after_current")


def test_formal_plan_old_why_does_not_win_over_advanced_runtime() -> None:
    plan_fields = {
        "current_step": "Keep one auth check",
        "why_now": "Expired tokens still leak the session.",
        "verify_method": ["Run the focused auth check"],
        "blocked_reason": "The auth guard still fails on expired tokens.",
        "next_after_current": "Add a token expiry test",
    }
    advanced = {
        "current_step": "Add a token expiry test",
        "why_now": "",
        "verify_method": [],
        "blocked_reason": "",
        "next_after_current": "",
        "resume_state": "in_progress",
    }
    overlaid = overlay_plan_runtime_display_facts(plan_fields=plan_fields, recovered=advanced)
    assert overlaid["current_step"] == "Add a token expiry test"
    assert overlaid["why_now"] == ""
    assert overlaid["why_now"] != "Expired tokens still leak the session."
    assert overlaid["verify_method"] == []
    assert overlaid["blocked_reason"] == ""
    assert overlaid["next_after_current"] == ""
    structured = overlay_plan_runtime_display_facts(
        plan_fields=plan_fields,
        recovered={**advanced, "why_now": "Expiry cases still skip the refresh path."},
    )
    assert structured["why_now"] == "Expiry cases still skip the refresh path."
    assert overlay_plan_runtime_display_facts(plan_fields=plan_fields, recovered=None)[
        "why_now"
    ] == "Expired tokens still leak the session."


def test_leftover_formal_plan_fields_do_not_live_in_overlay_fields() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_why = "Keep the leftover why"
    leftover_verify = "Keep the leftover verify"
    leftover_blocked = "Keep the leftover blocker"
    leftover_next = "Then review the leftover path"
    recovered_step = "Add a token expiry test"
    recovered_why = "Expired tokens still leak."
    recovered_blocked = "Expired tokens still leak the session."
    plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id="stage-1",
        current_step=leftover_step,
        why_now=leftover_why,
        verify_method=[leftover_verify],
        blocked_reason=leftover_blocked,
        next_after_current=leftover_next,
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
    advanced = {
        "current_step": recovered_step,
        "why_now": recovered_why,
        "resume_state": "in_progress",
        "workspace_id": "workspace-overlay-leftover",
    }
    leftover_fields = live_plan_overlay_fields(plan=plan, runtime=advanced, existing=advanced)
    overlaid = overlay_plan_runtime_display_facts(
        plan_fields=leftover_fields,
        recovered=advanced,
    )
    empty_fields = live_plan_overlay_fields(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
    )
    empty_overlaid = overlay_plan_runtime_display_facts(
        plan_fields=empty_fields,
        recovered=None,
    )
    leftover_copy = (
        leftover_fields["current_step"],
        leftover_fields["why_now"],
        leftover_fields["blocked_reason"],
        leftover_fields["next_after_current"],
        *leftover_fields["verify_method"],
        overlaid["current_step"],
        overlaid["why_now"],
        overlaid["blocked_reason"],
        overlaid["next_after_current"],
        *overlaid["verify_method"],
        empty_fields["current_step"],
        empty_fields["why_now"],
        empty_fields["blocked_reason"],
        empty_overlaid["current_step"],
        empty_overlaid["why_now"],
        empty_overlaid["blocked_reason"],
    )
    for text in leftover_copy:
        assert leftover_title not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
        assert leftover_why not in text
        assert leftover_verify not in text
        assert leftover_blocked not in text
        assert leftover_next not in text
    assert leftover_fields["current_step"] == recovered_step
    assert leftover_fields["why_now"] == recovered_why
    assert leftover_fields["blocked_reason"] == ""
    assert leftover_fields["verify_method"] == []
    assert leftover_fields["next_after_current"] == ""
    assert overlaid["current_step"] == recovered_step
    assert overlaid["why_now"] == recovered_why
    assert overlaid["blocked_reason"] == ""
    assert empty_fields["current_step"] == ""
    assert empty_overlaid["why_now"] == ""
    recovered_blocker = live_plan_overlay_fields(
        plan=plan,
        runtime={**advanced, "blocked_reason": recovered_blocked},
        existing={**advanced, "blocked_reason": recovered_blocked},
    )
    assert recovered_blocker["blocked_reason"] == recovered_blocked
    assert leftover_blocked not in recovered_blocker["blocked_reason"]
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "blocked_reason": leftover_blocked,
        "why_now": leftover_why,
        "verify_method": [leftover_verify],
        "resume_state": "in_progress",
        "workspace_id": "workspace-overlay-still-on-plan",
    }
    still = live_plan_overlay_fields(plan=plan, runtime=still_on_plan, existing=still_on_plan)
    assert leftover_step in still["current_step"]
    assert leftover_why in still["why_now"]
    assert leftover_blocked in still["blocked_reason"]
    assert leftover_verify in still["verify_method"]
    still_overlaid = overlay_plan_runtime_display_facts(
        plan_fields=still,
        recovered=still_on_plan,
        plan=plan,
    )
    assert leftover_step in still_overlaid["current_step"]
    assert leftover_blocked in still_overlaid["blocked_reason"]
    advanced_from_next_plan = plan.model_copy(update={"next_after_current": recovered_step})
    assert not leftover_formal_plan_is_live_for_fill(
        plan=advanced_from_next_plan,
        runtime=advanced,
        existing=advanced,
    )
    from_next_fields = live_plan_overlay_fields(
        plan=advanced_from_next_plan,
        runtime=advanced,
        existing=advanced,
    )
    assert leftover_blocked not in (from_next_fields["blocked_reason"] or "")
    assert leftover_verify not in from_next_fields["verify_method"]
    assert leftover_why not in (from_next_fields["why_now"] or "")
    assert leftover_step not in (from_next_fields["current_step"] or "")
    leftover_persist = PlannerService().replan_after_failure(
        advanced_from_next_plan,
        None,
        blocker=leftover_blocked,
        runtime=advanced,
        existing=advanced,
    )
    assert leftover_persist is not None
    assert leftover_blocked not in (leftover_persist.blocked_reason or "")
    still_persist = PlannerService().replan_after_failure(
        plan,
        None,
        blocker=leftover_blocked,
        runtime=still_on_plan,
        existing=still_on_plan,
    )
    assert still_persist is not None
    assert leftover_blocked in (still_persist.blocked_reason or "")
    empty_runtime = {"current_step": "", "resume_state": "in_progress"}
    assert formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is False
    assert leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=empty_runtime,
        existing=empty_runtime,
    ) is False
    matching_step_without_plan_id = {
        "current_step": leftover_step,
        "resume_state": "waiting",
        "plan_id": "",
        "workspace_id": "workspace-overlay-leftover",
    }
    assert formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=matching_step_without_plan_id,
        existing=matching_step_without_plan_id,
        current_step=leftover_step,
    ) is False
    assert leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=matching_step_without_plan_id,
        existing=matching_step_without_plan_id,
    ) is False
    assert live_runtime_plan_id(
        plan=plan,
        runtime=matching_step_without_plan_id,
        existing=matching_step_without_plan_id,
        current_step=leftover_step,
    ) == ""
    assert live_runtime_plan_id(
        plan=plan,
        runtime={"current_step": leftover_step, "resume_state": "in_progress"},
        existing=None,
        current_step=leftover_step,
    ) == leftover_plan_id
    assert formal_task_is_live_runtime_identity(
        recovered=True,
        runtime_current_step="",
        task_title=leftover_title,
    ) is False
    assert live_runtime_plan_id(
        plan=plan,
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) == ""
    assert live_runtime_frozen(
        plan=plan.model_copy(update={"frozen": True}),
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is False
    persisted_empty = build_plan_runtime_recovery(
        plan=plan,
        plan_runtime=empty_runtime,
        existing=empty_runtime,
        workspace_id="workspace-overlay-leftover",
        request_id="leftover-empty-step",
    )
    assert persisted_empty is not None
    for text in (
        persisted_empty.get("current_step") or "",
        persisted_empty.get("why_now") or "",
        persisted_empty.get("blocked_reason") or "",
        persisted_empty.get("plan_id") or "",
        *(persisted_empty.get("verify_method") or []),
    ):
        assert leftover_title not in text
        assert leftover_step not in text
        assert leftover_why not in text
        assert leftover_blocked not in text
        assert leftover_verify not in text
        assert leftover_plan_id not in text
    empty_replan = PlannerService().replan_after_failure(
        plan,
        None,
        blocker=leftover_blocked,
        runtime=empty_runtime,
        existing=empty_runtime,
    )
    assert empty_replan is not None
    assert leftover_blocked not in (empty_replan.blocked_reason or "")
    assert leftover_title not in (empty_replan.current_step or "")
    assert leftover_step not in (empty_replan.current_step or "")


def test_leftover_bound_plan_competing_identity_labels_after_new_live_plan() -> None:
    leftover = LearningPlan(
        id="plan-formal-old",
        title="Keep the current stage",
        current_step="Keep one auth check",
        why_now="Keep the leftover why",
        frozen=True,
        stages=[],
    )
    live = LearningPlan(
        id="plan-generated-new",
        title="Token-refresh learning path",
        current_step="Inspect one refresh boundary",
        stages=[],
    )
    runtime = {
        "plan_id": live.id,
        "current_step": live.current_step,
        "resume_state": "in_progress",
    }
    labels = leftover_bound_plan_competing_identity_labels(
        plan=live,
        runtime=runtime,
        existing=runtime,
        card_titles=["Keep one auth check"],
        leftover_plans=[leftover, live],
    )
    assert "Keep one auth check" in labels
    assert "Keep the current stage" in labels
    assert "Keep the leftover why" in labels
    assert live.current_step not in labels
    assert live.title not in labels
    recovered_matching_step = {
        "current_step": leftover.current_step,
        "resume_state": "waiting",
        "plan_id": "",
    }
    matching_labels = leftover_bound_plan_competing_identity_labels(
        plan=leftover,
        runtime=recovered_matching_step,
        existing=recovered_matching_step,
        card_titles=[leftover.current_step],
        leftover_plans=[leftover],
    )
    assert leftover.current_step not in matching_labels
    assert leftover.title in matching_labels
    assert leftover.why_now in matching_labels
    recovered_without_plan_id = {
        "current_step": "Add a token expiry test",
        "resume_state": "in_progress",
        "plan_id": "",
    }
    independent_labels = leftover_bound_plan_competing_identity_labels(
        plan=leftover,
        runtime=recovered_without_plan_id,
        existing=recovered_without_plan_id,
        card_titles=[leftover.current_step, "Keep the leftover A sandbox preview"],
        leftover_plans=[leftover],
    )
    assert leftover.current_step in independent_labels
    assert leftover.title in independent_labels
    assert leftover.why_now in independent_labels
    assert "Keep the leftover A sandbox preview" in independent_labels
    assert "Add a token expiry test" not in independent_labels


def test_leftover_formal_plan_empty_recovered_step_is_not_live_identity(tmp_path: Path) -> None:
    leftover_title = "Keep the current stage"
    leftover_step = "Keep one auth check"
    leftover_why = "Keep the leftover why"
    leftover_blocked = "Keep the leftover blocker"
    leftover_plan_id = "plan-formal-old"
    recovered_step = "Add a token expiry test"
    workspace_a = "workspace-leftover-empty-step-a"
    workspace_b = "workspace-leftover-empty-step-b"
    leftover = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary="Leftover formal summary of the old stage path",
        current_stage_id="stage-1",
        current_step=leftover_step,
        why_now=leftover_why,
        blocked_reason=leftover_blocked,
        verify_method=["Keep the leftover verify"],
        frozen=True,
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
    service = build_memory_service(tmp_path)
    service.repository.save_plan(workspace_a, leftover)
    empty_runtime = {
        "current_step": "",
        "resume_state": "in_progress",
        "workspace_id": workspace_a,
    }
    persisted = service.persist_plan_runtime_recovery(
        workspace_a,
        plan=leftover,
        plan_runtime=empty_runtime,
        request_id="leftover-empty-live-1",
    )
    assert persisted is not None
    stored = service.repository.get_latest_plan(workspace_a)
    assert stored is not None
    assert stored.id == leftover_plan_id
    assert stored.title == leftover_title
    assert stored.current_step == leftover_step
    recovered = service.recover_workspace_facts(workspace_a)["latest_plan_runtime"]
    assert not str(recovered.get("current_step") or "").strip()
    assert leftover_title not in str(recovered.get("current_step") or "")
    assert leftover_step not in str(recovered.get("why_now") or "")
    assert leftover_blocked not in str(recovered.get("blocked_reason") or "")
    assert formal_plan_is_live_runtime_identity(
        plan=stored,
        runtime=recovered,
        existing=recovered,
        current_step="",
    ) is False
    overlay = live_plan_overlay_fields(plan=stored, runtime=recovered, existing=recovered)
    assert overlay["current_step"] == ""
    assert leftover_title not in overlay["why_now"]
    assert leftover_blocked not in overlay["blocked_reason"]
    provider = ProviderConfig(
        name="ready-provider",
        baseUrl="http://example.test/v1",
        apiKeyRef="ready-ref",
        model="ready-model",
    )
    orientation = build_coach_orientation_from_snapshot(
        WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            plan=stored,
            plan_runtime_status={
                "recovered": True,
                "current_step": "",
                "plan_id": "",
                "why_now": "",
            },
            memory=MemorySnapshot(
                workspace={
                    "workspace_id": workspace_a,
                    PLAN_RUNTIME_KEY: recovered,
                }
            ),
        ),
        response_language="en-US",
    )
    for text in (
        orientation["object_label"],
        orientation["why"],
        orientation["next_step"],
    ):
        assert leftover_title not in text
        assert leftover_step not in text
        assert leftover_why not in text
        assert leftover_blocked not in text
        assert leftover_plan_id not in text
    assert orientation["object_kind"] != "plan"
    assert orientation["primary_action"] != "open_plan"
    live = service.persist_plan_runtime_recovery(
        workspace_a,
        plan=stored,
        plan_runtime={
            "current_step": recovered_step,
            "why_now": "Expired tokens still leak.",
            "resume_state": "in_progress",
            "workspace_id": workspace_a,
        },
        request_id="leftover-empty-live-2",
    )
    assert live is not None
    assert live["current_step"] == recovered_step
    live_orientation = build_coach_orientation_from_snapshot(
        WorkbenchSnapshot(
            sidecar_status="ready",
            provider=provider,
            plan=stored,
            plan_runtime_status={
                "recovered": True,
                "current_step": recovered_step,
                "plan_id": "",
                "why_now": "Expired tokens still leak.",
            },
            memory=MemorySnapshot(
                workspace={
                    "workspace_id": workspace_a,
                    PLAN_RUNTIME_KEY: live,
                }
            ),
        ),
        response_language="en-US",
    )
    assert live_orientation["object_kind"] == "conversation"
    assert live_orientation["object_label"] == recovered_step
    assert leftover_title not in live_orientation["object_label"]
    assert live_orientation["primary_action"] != "open_plan"
    hydrate_b = service.recover_workspace_facts(workspace_b)
    runtime_b = hydrate_b.get("latest_plan_runtime") or {}
    assert leftover_step not in str(runtime_b)
    assert leftover_title not in str(runtime_b)
    assert leftover_blocked not in str(runtime_b)
    assert leftover_plan_id not in str(runtime_b)
    assert service.repository.get_latest_plan(workspace_b) is None


def test_previous_step_adopted_evidence_is_history_not_live() -> None:
    old_item = {
        "id": "ev-old-auth",
        "summary": "Auth check passed",
        "concepts": ["Keep one auth check"],
        "adopted": True,
    }
    live_item = {
        "id": "ev-new-expiry",
        "summary": "Expiry test still missing",
        "concepts": ["Add a token expiry test"],
    }
    scoped = scope_evidence_queue_to_runtime_step(
        pending=[live_item],
        deferred=[],
        adopted=[old_item],
        rejected=[],
        current_step="Add a token expiry test",
        recovered=True,
    )
    assert [item["id"] for item in scoped["pending"]] == ["ev-new-expiry"]
    assert scoped["adopted"] == []
    assert [item["id"] for item in scoped["history"]] == ["ev-old-auth"]
    empty_live = scope_evidence_queue_to_runtime_step(
        pending=[],
        deferred=[],
        adopted=[old_item],
        rejected=[],
        current_step="Add a token expiry test",
        recovered=True,
    )
    assert empty_live["pending"] == []
    assert empty_live["adopted"] == []
    assert [item["id"] for item in empty_live["history"]] == ["ev-old-auth"]


def test_formal_plan_stage_is_not_live_current_after_runtime_advances() -> None:
    formal_stage = {
        "id": "stage-1",
        "title": "Auth",
        "goal": "Keep one check",
        "status": "active",
    }
    advanced = {
        "current_step": "Add a token expiry test",
        "current_stage_id": "stage-1",
        "resume_state": "in_progress",
    }
    assert (
        overlay_plan_runtime_current_stage(
            plan_stage=formal_stage,
            plan_current_step="Keep one auth check",
            recovered=advanced,
        )
        is None
    )
    still_on_stage = overlay_plan_runtime_current_stage(
        plan_stage=formal_stage,
        plan_current_step="Keep one auth check",
        recovered={**advanced, "current_step": "Keep one auth check"},
    )
    assert still_on_stage is not None
    assert still_on_stage["title"] == "Auth"
    assert (
        overlay_plan_runtime_current_stage(
            plan_stage=formal_stage,
            plan_current_step="Keep one auth check",
            recovered=None,
        )
        == formal_stage
    )


def test_persist_does_not_backfill_empty_advanced_why_from_formal_plan() -> None:
    plan = LearningPlan(
        id="plan-formal-old",
        title="Keep the current stage",
        current_stage_id="stage-1",
        current_step="Keep one auth check",
        why_now="Expired tokens still leak the session.",
        next_after_current="Add a token expiry test",
        frozen=True,
        verify_method=["Run the focused auth check"],
        blocked_reason="The auth guard still fails on expired tokens.",
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
    formal = _plan_with_formal_next(plan)
    persisted = build_plan_runtime_recovery(
        plan=formal,
        plan_runtime={
            "current_step": "Add a token expiry test",
            "why_now": "",
            "verify_method": [],
            "blocked_reason": "",
            "next_after_current": "",
            "resume_state": "in_progress",
        },
        workspace_id="workspace-plan",
        request_id="plan-formal-persist-1",
    )
    assert persisted is not None
    assert persisted["current_step"] == "Add a token expiry test"
    assert persisted.get("current_stage_id") in {None, ""}
    assert persisted.get("current_stage_id") != "stage-1"
    assert persisted.get("plan_id") in {None, ""}
    assert persisted.get("plan_id") != "plan-formal-old"
    assert persisted.get("frozen") is False
    assert persisted.get("next_why_now") in {None, ""}
    assert persisted.get("next_why_now") != FORMAL_NEXT_WHY
    assert persisted.get("next_blocked_reason") in {None, ""}
    assert persisted.get("next_blocked_reason") != FORMAL_NEXT_BLOCK
    assert persisted.get("next_verify_method") in (None, [])
    assert FORMAL_NEXT_VERIFY[0] not in (persisted.get("next_verify_method") or [])
    assert live_runtime_frozen(
        plan=formal,
        runtime={"current_step": "Add a token expiry test", "resume_state": "in_progress"},
        current_step="Add a token expiry test",
    ) is False
    assert live_runtime_next_text(
        field="next_why_now",
        plan=formal,
        runtime={"current_step": "Add a token expiry test", "resume_state": "in_progress"},
        current_step="Add a token expiry test",
    ) == ""
    assert live_runtime_next_verify_method(
        plan=formal,
        runtime={"current_step": "Add a token expiry test", "resume_state": "in_progress"},
        current_step="Add a token expiry test",
    ) == []
    assert live_runtime_plan_id(
        plan=formal,
        runtime={"current_step": "Add a token expiry test", "resume_state": "in_progress"},
        current_step="Add a token expiry test",
    ) == ""
    assert live_runtime_stage_id(
        plan=formal,
        runtime={"current_step": "Add a token expiry test", "resume_state": "in_progress"},
        current_step="Add a token expiry test",
    ) == ""
    hydrate_again = build_plan_runtime_recovery(
        plan=formal,
        plan_runtime=persisted,
        existing=persisted,
        workspace_id="workspace-plan",
        request_id="plan-formal-persist-2",
    )
    assert hydrate_again is not None
    assert hydrate_again["current_step"] == "Add a token expiry test"
    assert hydrate_again.get("current_stage_id") in {None, ""}
    assert hydrate_again.get("plan_id") in {None, ""}
    assert hydrate_again.get("plan_id") != "plan-formal-old"
    assert hydrate_again.get("frozen") is False
    assert hydrate_again.get("next_why_now") in {None, ""}
    assert hydrate_again.get("next_blocked_reason") in {None, ""}
    assert hydrate_again.get("next_verify_method") in (None, [])
    already_stamped = build_plan_runtime_recovery(
        plan=formal,
        plan_runtime={
            "current_step": "Add a token expiry test",
            "plan_id": "plan-formal-old",
            "resume_state": "in_progress",
        },
        existing={
            "current_step": "Add a token expiry test",
            "plan_id": "plan-formal-old",
            "frozen": True,
            "next_why_now": FORMAL_NEXT_WHY,
            "next_blocked_reason": FORMAL_NEXT_BLOCK,
            "next_verify_method": list(FORMAL_NEXT_VERIFY),
            "resume_state": "in_progress",
        },
        workspace_id="workspace-plan",
        request_id="plan-formal-persist-stamped",
    )
    assert already_stamped is not None
    assert already_stamped.get("plan_id") in {None, ""}
    assert already_stamped.get("plan_id") != "plan-formal-old"
    assert already_stamped.get("frozen") is False
    assert already_stamped.get("next_why_now") in {None, ""}
    assert already_stamped.get("next_blocked_reason") in {None, ""}
    assert already_stamped.get("next_verify_method") in (None, [])
    assert plan.current_stage_id == "stage-1"
    assert plan.id == "plan-formal-old"
    assert plan.frozen is True
    assert persisted.get("why_now") in {None, ""}
    assert persisted.get("why_now") != "Expired tokens still leak the session."
    assert not persisted.get("next_after_current")
    assert persisted.get("verify_method") in (None, [])
    seeded = build_plan_runtime_recovery(
        plan=formal,
        plan_runtime=None,
        workspace_id="workspace-plan",
        request_id="plan-formal-seed-1",
    )
    assert seeded is not None
    assert seeded["current_step"] == "Keep one auth check"
    assert seeded["current_stage_id"] == "stage-1"
    assert seeded["plan_id"] == "plan-formal-old"
    assert seeded["frozen"] is True
    assert seeded["why_now"] == "Expired tokens still leak the session."
    assert seeded["next_why_now"] == FORMAL_NEXT_WHY
    assert seeded["next_blocked_reason"] == FORMAL_NEXT_BLOCK
    assert seeded["next_verify_method"] == FORMAL_NEXT_VERIFY
    assert formal.next_why_now == FORMAL_NEXT_WHY
    assert formal.next_blocked_reason == FORMAL_NEXT_BLOCK
    assert formal.next_verify_method == FORMAL_NEXT_VERIFY


def test_leftover_formal_mutate_does_not_clobber_advanced_runtime() -> None:
    plan = LearningPlan(
        id="plan-formal-old",
        title="Keep the current stage",
        current_stage_id="stage-1",
        current_step="Keep one auth check",
        why_now="Expired tokens still leak the session.",
        next_after_current="Add a token expiry test",
        frozen=False,
        verify_method=["Run the focused auth check"],
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
    advanced = {
        "current_step": "Add a token expiry test",
        "why_now": "",
        "verify_method": [],
        "blocked_reason": "",
        "next_after_current": "",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    assert formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        current_step="Add a token expiry test",
    ) is False
    mutated = plan.model_copy(
        update={
            "frozen": True,
            "current_step": "Push async error handling through one narrow slice.",
            "why_now": "User steering changed toward async; keep the live stage narrow and verifiable.",
        }
    )
    echoed = build_plan_runtime_recovery(
        plan=mutated,
        plan_runtime={
            "current_step": mutated.current_step,
            "why_now": mutated.why_now,
            "verify_method": list(mutated.verify_method),
            "blocked_reason": mutated.blocked_reason,
            "next_after_current": mutated.next_after_current,
            "resume_state": "in_progress",
        },
        existing=advanced,
        workspace_id="workspace-plan",
        request_id="plan-formal-mutate-1",
    )
    assert echoed is not None
    assert echoed["current_step"] == "Add a token expiry test"
    assert echoed.get("plan_id") in {None, ""}
    assert echoed.get("plan_id") != "plan-formal-old"
    assert echoed.get("why_now") in {None, ""}
    assert echoed.get("why_now") != mutated.why_now
    assert echoed.get("frozen") is False
    assert mutated.frozen is True
    assert mutated.current_step == "Push async error handling through one narrow slice."
    assert plan.current_step == "Keep one auth check"


def test_leftover_formal_title_does_not_mint_card_why_or_skill_after_advance() -> None:
    leftover_title = "Keep the current stage"
    plan = LearningPlan(
        id="plan-formal-old",
        title=leftover_title,
        summary=leftover_title,
        current_stage_id="stage-1",
        current_step="Keep one auth check",
        why_now="Expired tokens still leak the session.",
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
    advanced = {
        "current_step": "Add a token expiry test",
        "why_now": "",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    minted = live_training_mint_anchors(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_title,
        why_now=leftover_title,
        target_skill=leftover_title,
        focus_area=leftover_title,
    )
    assert minted["why_now"] == ""
    assert minted["why_now"] != leftover_title
    assert minted["target_skill"] == ""
    assert minted["target_skill"] != leftover_title
    assert minted["focus_area"] == "Add a token expiry test"
    card = SimpleNamespace(
        why_now=leftover_title,
        target_skill=leftover_title,
        focus_area=leftover_title,
        title=f"Practice: {leftover_title}",
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=leftover_title,
        live_plan=False,
        live_task=False,
    )
    scrubbed = apply_live_training_mint_to_card(
        card,
        anchors=minted,
        leftover_labels=leftover,
        recovered_step="Add a token expiry test",
    )
    assert scrubbed.why_now != leftover_title
    assert scrubbed.target_skill != leftover_title
    assert leftover_title not in (scrubbed.title or "")
    still_on_plan = {
        "current_step": "Keep one auth check",
        "why_now": leftover_title,
        "plan_id": "plan-formal-old",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_minted = live_training_mint_anchors(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        task_title=leftover_title,
        why_now=leftover_title,
        target_skill=leftover_title,
        focus_area=leftover_title,
    )
    assert still_minted["why_now"] == leftover_title
    assert still_minted["target_skill"] == leftover_title


def test_leftover_formal_title_does_not_label_coach_focus_after_advance() -> None:
    leftover_title = "Keep the current stage"
    plan = LearningPlan(
        id="plan-formal-old",
        title=leftover_title,
        current_stage_id="stage-1",
        current_step="Keep one auth check",
        stages=[
            PlanStage(
                id="stage-1",
                title=leftover_title,
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    task = SimpleNamespace(title=leftover_title)
    advanced = {
        "current_step": "Add a token expiry test",
        "why_now": "",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    focus = live_coach_focus_area(
        plan=plan,
        task=task,
        runtime=advanced,
        existing=advanced,
    )
    assert focus == "Add a token expiry test"
    assert focus != leftover_title
    empty_recovered = live_coach_focus_area(
        plan=plan,
        task=task,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
    )
    assert empty_recovered == ""
    assert empty_recovered != leftover_title
    still_on_plan = {
        "current_step": "Keep one auth check",
        "plan_id": "plan-formal-old",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_focus = live_coach_focus_area(
        plan=plan,
        task=task,
        runtime=still_on_plan,
        existing=still_on_plan,
    )
    assert still_focus == leftover_title
    snapshot = SimpleNamespace(
        workspace_id="workspace-plan",
        memory=SimpleNamespace(
            workspace={
                "workspace_id": "workspace-plan",
                "latest_plan_runtime": advanced,
            }
        ),
        plan_runtime_status=None,
    )
    snapshot_focus = live_coach_focus_area(
        plan=plan,
        task=task,
        runtime=coach_focus_runtime_from_snapshot(snapshot),
        existing=coach_focus_runtime_from_snapshot(snapshot),
    )
    assert snapshot_focus == "Add a token expiry test"
    assert snapshot_focus != leftover_title


def test_leftover_current_task_and_coach_chrome_not_live_when_recovered_step_empty() -> None:
    leftover_task = "Ship one auth check"
    leftover_guide = "Keep the leftover A implementation step"
    leftover_focus = "Keep the leftover A coach focus"
    empty_runtime = {"current_step": "", "resume_state": "in_progress"}
    assert leftover_task_guide_focus_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    assert formal_task_is_live_runtime_identity(
        recovered=True,
        runtime_current_step="",
        task_title=leftover_task,
    ) is False
    empty_chrome = prefer_recovered_coach_task_chrome(
        runtime=empty_runtime,
        existing=empty_runtime,
        task_title=leftover_task,
        idea_summary="Keep the leftover A implementation idea",
        scope_boundary=leftover_guide,
        guide_current_step=leftover_guide,
        teaching_goal=leftover_task,
        current_focus=leftover_focus,
        active_task=leftover_task,
        next_step=leftover_guide,
    )
    assert empty_chrome.get("live_task_title") == ""
    assert leftover_task not in empty_chrome.get("live_task_title", "")
    assert leftover_guide not in (empty_chrome.get("current_step") or "")
    assert leftover_guide not in (empty_chrome.get("scope_boundary") or "")
    assert leftover_focus not in (empty_chrome.get("current_focus") or "")
    assert leftover_task not in (empty_chrome.get("active_task") or "")
    live_runtime = {
        "current_step": "Add a token expiry test",
        "resume_state": "in_progress",
    }
    live_chrome = prefer_recovered_coach_task_chrome(
        runtime=live_runtime,
        existing=live_runtime,
        task_title=leftover_task,
        guide_current_step=leftover_guide,
        current_focus=leftover_focus,
        active_task=leftover_task,
    )
    assert live_chrome.get("live_task_title") == ""
    assert leftover_guide not in (live_chrome.get("current_step") or "")
    assert leftover_task not in (live_chrome.get("active_task") or "")
    matching = prefer_recovered_coach_task_chrome(
        runtime=live_runtime,
        existing=live_runtime,
        task_title="Add a token expiry test",
        guide_current_step="Add a token expiry test",
        current_focus="Add a token expiry test",
        active_task="Add a token expiry test",
    )
    assert matching["live_task_title"] == "Add a token expiry test"
    assert matching["current_step"] == "Add a token expiry test"
    assert matching["active_task"] == "Add a token expiry test"


def test_leftover_coach_turn_and_evaluation_next_step_not_live_when_recovered_step_empty() -> None:
    leftover_turn = "Keep the leftover A coach turn next"
    leftover_state = "Stay on leftover A"
    leftover_eval = "Stay on leftover A eval"
    leftover_resume = "Keep the leftover A resume thread"
    leftover_support = "Keep the leftover A support strategy"
    leftover_review = "Keep the leftover A review queue"
    leftover_teaser = "Keep the leftover A artifact teaser"
    leftover_rationale = "Keep the leftover A artifact rationale"
    leftover_continuity = "Keep the leftover A coach focus summary"
    leftover_judgment = "Keep the leftover A coach judgment"
    leftover_judgment_goal = "Ship leftover A"
    empty_runtime = {"current_step": "", "resume_state": "in_progress"}
    assert leftover_coach_turn_chrome_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    empty_chrome = prefer_recovered_coach_turn_chrome(
        runtime=empty_runtime,
        existing=empty_runtime,
        coach_turn_next_step=leftover_turn,
        coaching_state_next_step=leftover_state,
        evaluation_next_step=leftover_eval,
        next_step_hint_title=leftover_turn,
        resume_thread=leftover_resume,
        support_strategy=leftover_support,
        review_queue_summary=leftover_review,
        artifact_teaser=leftover_teaser,
        artifact_rationale=leftover_rationale,
        continuity_summary=leftover_continuity,
        coach_judgment_summary=leftover_judgment,
        coach_judgment_teaching_goal=leftover_judgment_goal,
    )
    assert leftover_turn not in (empty_chrome.get("coach_turn_next_step") or "")
    assert leftover_state not in (empty_chrome.get("coaching_state_next_step") or "")
    assert leftover_eval not in (empty_chrome.get("evaluation_next_step") or "")
    assert leftover_resume not in (empty_chrome.get("resume_thread") or "")
    assert leftover_support not in (empty_chrome.get("support_strategy") or "")
    assert leftover_review not in (empty_chrome.get("review_queue_summary") or "")
    assert leftover_teaser not in (empty_chrome.get("artifact_teaser") or "")
    assert leftover_rationale not in (empty_chrome.get("artifact_rationale") or "")
    assert leftover_continuity not in (empty_chrome.get("continuity_summary") or "")
    assert leftover_judgment not in (empty_chrome.get("coach_judgment_summary") or "")
    assert leftover_judgment_goal not in (empty_chrome.get("coach_judgment_teaching_goal") or "")
    live_runtime = {
        "current_step": "Add a token expiry test",
        "resume_state": "in_progress",
    }
    live_chrome = prefer_recovered_coach_turn_chrome(
        runtime=live_runtime,
        existing=live_runtime,
        coach_turn_next_step=leftover_turn,
        coaching_state_next_step=leftover_state,
        evaluation_next_step=leftover_eval,
        resume_thread=leftover_resume,
        support_strategy=leftover_support,
        review_queue_summary=leftover_review,
        artifact_teaser=leftover_teaser,
        artifact_rationale=leftover_rationale,
        continuity_summary=leftover_continuity,
        coach_judgment_summary=leftover_judgment,
        coach_judgment_teaching_goal=leftover_judgment_goal,
    )
    assert leftover_turn not in (live_chrome.get("coach_turn_next_step") or "")
    assert leftover_eval not in (live_chrome.get("evaluation_next_step") or "")
    assert leftover_resume not in (live_chrome.get("resume_thread") or "")
    assert leftover_teaser not in (live_chrome.get("artifact_teaser") or "")
    assert leftover_continuity not in (live_chrome.get("continuity_summary") or "")
    assert leftover_judgment not in (live_chrome.get("coach_judgment_summary") or "")
    matching = prefer_recovered_coach_turn_chrome(
        runtime=live_runtime,
        existing=live_runtime,
        coach_turn_next_step="Add a token expiry test",
        coaching_state_next_step="Add a token expiry test",
        evaluation_next_step="Add a token expiry test",
        resume_thread="Add a token expiry test",
        support_strategy="Add a token expiry test",
        review_queue_summary="Add a token expiry test",
        artifact_teaser="Add a token expiry test",
        artifact_rationale="Add a token expiry test",
        continuity_summary="Add a token expiry test",
        coach_judgment_summary="Add a token expiry test",
        coach_judgment_teaching_goal="Add a token expiry test",
    )
    assert matching["coach_turn_next_step"] == "Add a token expiry test"
    assert matching["coaching_state_next_step"] == "Add a token expiry test"
    assert matching["evaluation_next_step"] == "Add a token expiry test"
    assert matching["resume_thread"] == "Add a token expiry test"
    assert matching["support_strategy"] == "Add a token expiry test"
    assert matching["review_queue_summary"] == "Add a token expiry test"
    assert matching["artifact_teaser"] == "Add a token expiry test"
    assert matching["artifact_rationale"] == "Add a token expiry test"
    assert matching["continuity_summary"] == "Add a token expiry test"
    assert matching["coach_judgment_summary"] == "Add a token expiry test"
    assert matching["coach_judgment_teaching_goal"] == "Add a token expiry test"


def test_leftover_teaching_decision_and_learner_focus_not_live_when_recovered_step_empty() -> None:
    leftover_focus = "Keep the leftover A teaching focus"
    leftover_learner = "Keep the leftover A learner focus"
    leftover_learning = "Keep the leftover A learning focus"
    leftover_card = "Keep the leftover A card focus"
    empty_runtime = {"current_step": "", "resume_state": "in_progress"}
    assert leftover_training_focus_chrome_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    empty_chrome = prefer_recovered_training_focus_chrome(
        runtime=empty_runtime,
        existing=empty_runtime,
        teaching_decision_focus_area=leftover_focus,
        learner_state_active_focus=leftover_learner,
        latest_learning_focus_area=leftover_learning,
        card_focus_area=leftover_card,
    )
    assert leftover_focus not in (empty_chrome.get("teaching_decision_focus_area") or "")
    assert leftover_learner not in (empty_chrome.get("learner_state_active_focus") or "")
    assert leftover_learning not in (empty_chrome.get("latest_learning_focus_area") or "")
    assert leftover_card not in (empty_chrome.get("card_focus_area") or "")
    live_runtime = {
        "current_step": "Add a token expiry test",
        "resume_state": "in_progress",
    }
    live_chrome = prefer_recovered_training_focus_chrome(
        runtime=live_runtime,
        existing=live_runtime,
        teaching_decision_focus_area=leftover_focus,
        learner_state_active_focus=leftover_learner,
        latest_learning_focus_area=leftover_learning,
        card_focus_area=leftover_card,
    )
    assert leftover_focus not in (live_chrome.get("teaching_decision_focus_area") or "")
    assert leftover_learner not in (live_chrome.get("learner_state_active_focus") or "")
    matching = prefer_recovered_training_focus_chrome(
        runtime=live_runtime,
        existing=live_runtime,
        teaching_decision_focus_area="Add a token expiry test",
        learner_state_active_focus="Add a token expiry test",
        latest_learning_focus_area="Add a token expiry test",
        card_focus_area="Add a token expiry test",
    )
    assert matching == {}


def test_leftover_training_handoff_card_chrome_not_live_when_recovered_step_empty() -> None:
    leftover_signal = "Keep the leftover A success signal"
    leftover_return = "Keep the leftover A return with"
    leftover_card = "Keep the leftover A handoff card"
    leftover_selected = "Review the leftover A selected card"
    leftover_followup = "Keep the leftover A learning followup"
    leftover_blocker = "Keep the leftover A learning blocker"
    leftover_summary = "Keep the leftover A handoff summary"
    leftover_next_after = "Keep the leftover A next after completion"
    leftover_fallback = "Keep the leftover A fallback action"
    leftover_next_hop_title = "Keep the leftover A next hop title"
    leftover_next_hop_card = "Keep the leftover A next hop card"
    leftover_why = "Keep the leftover A why this card"
    leftover_return_summary = "Keep the leftover A return summary"
    leftover_next_hop_summary = "Keep the leftover A next hop summary"
    leftover_resource_title = "Workspace A notes"
    empty_runtime = {"current_step": "", "resume_state": "in_progress"}
    assert leftover_training_handoff_chrome_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    empty_chrome = prefer_recovered_training_handoff_chrome(
        runtime=empty_runtime,
        existing=empty_runtime,
        success_signal=leftover_signal,
        return_with=leftover_return,
        card_title=leftover_card,
        selected_card_title=leftover_selected,
        followup=leftover_followup,
        blocker=leftover_blocker,
        handoff_summary=leftover_summary,
        next_after_completion=leftover_next_after,
        fallback_action=leftover_fallback,
        next_hop_title=leftover_next_hop_title,
        next_hop_card_title=leftover_next_hop_card,
        next_hop_handoff_summary=leftover_summary,
        next_hop_next_after_completion=leftover_next_after,
        next_hop_fallback_action=leftover_fallback,
        routing_next_after_completion=leftover_next_after,
        routing_fallback_action=leftover_fallback,
        why_this_card=leftover_why,
        ledger_why_this_card=leftover_why,
        return_summary=leftover_return_summary,
        next_hop_return_summary=leftover_return_summary,
        next_hop_summary=leftover_next_hop_summary,
        next_hop_why_now=leftover_why,
    )
    assert leftover_signal not in (empty_chrome.get("success_signal") or "")
    assert leftover_return not in (empty_chrome.get("return_with") or "")
    assert leftover_card not in (empty_chrome.get("card_title") or "")
    assert leftover_selected not in (empty_chrome.get("selected_card_title") or "")
    assert leftover_followup not in (empty_chrome.get("followup") or "")
    assert leftover_blocker not in (empty_chrome.get("blocker") or "")
    assert leftover_summary not in (empty_chrome.get("handoff_summary") or "")
    assert leftover_next_after not in (empty_chrome.get("next_after_completion") or "")
    assert leftover_fallback not in (empty_chrome.get("fallback_action") or "")
    assert leftover_next_hop_title not in (empty_chrome.get("next_hop_title") or "")
    assert leftover_next_hop_card not in (empty_chrome.get("next_hop_card_title") or "")
    assert leftover_why not in (empty_chrome.get("why_this_card") or "")
    assert leftover_return_summary not in (empty_chrome.get("return_summary") or "")
    assert leftover_next_hop_summary not in (empty_chrome.get("next_hop_summary") or "")
    assert leftover_resource_selected_detail_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    assert leftover_resource_sandbox_preview_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    assert leftover_resource_sandbox_state_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    assert leftover_resource_library_list_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    assert leftover_coach_conversation_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    assert leftover_suggested_actions_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    assert leftover_first_look_headline_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    assert leftover_evaluation_headline_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    assert leftover_streaming_checkpoint_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    assert leftover_transfer_skill_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    leftover_transfer = {
        "concept": "Keep the leftover A transfer skill",
        "state": "transferable",
        "scene_count": 1,
        "workspace_ids": ["workspace-a"],
        "scene_keys": ["default"],
        "why": "Keep the leftover A transfer why",
        "next": "Keep the leftover A transfer next",
    }
    assert leftover_transfer_skill_has_real_multi_scene_proof(leftover_transfer) is False
    fake_scene_keys = {
        **leftover_transfer,
        "scene_count": 2,
        "workspace_ids": ["workspace-a"],
        "scene_keys": ["default", "transfer:docs sandbox"],
    }
    assert leftover_transfer_skill_has_real_multi_scene_proof(fake_scene_keys) is False
    empty_transfer = prefer_recovered_transfer_skill(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
        transfer=leftover_transfer,
    )
    assert (empty_transfer or {}).get("state") != "transferable"
    assert (empty_transfer or {}).get("state") == "awaiting_second_scene"
    assert "Keep the leftover A transfer next" not in str((empty_transfer or {}).get("next") or "")
    assert "Keep the leftover A transfer why" not in str((empty_transfer or {}).get("why") or "")
    real_multi = {
        **leftover_transfer,
        "scene_count": 2,
        "workspace_ids": ["workspace-a", "workspace-c"],
        "scene_keys": ["default", "workspace:workspace-c"],
    }
    assert leftover_transfer_skill_has_real_multi_scene_proof(real_multi) is True
    kept_multi = prefer_recovered_transfer_skill(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
        transfer=real_multi,
    )
    assert (kept_multi or {}).get("state") == "transferable"
    assert (kept_multi or {}).get("workspace_ids") == ["workspace-a", "workspace-c"]
    leftover_rhythm = "Keep the leftover A rhythm"
    leftover_learning_mode = "Keep the leftover A learning mode"
    leftover_scope = "personal"
    leftover_cadence = "active"
    leftover_learner = "Keep the leftover A learner"
    leftover_onboarding = "Keep the leftover A onboarding"
    leftover_project = "Keep the leftover A project context"
    assert leftover_settings_profile_rhythm_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    assert leftover_settings_learner_project_onboarding_is_not_live(
        runtime=empty_runtime,
        existing=empty_runtime,
        current_step="",
    ) is True
    empty_settings = prefer_recovered_settings_profile_rhythm(
        runtime=empty_runtime,
        existing=empty_runtime,
        preferred_rhythm=leftover_rhythm,
        preferred_learning_mode=leftover_learning_mode,
        memory_scope=leftover_scope,
        review_cadence=leftover_cadence,
        working_set_mode="broad",
        review_reminder_mode="ahead",
    )
    assert leftover_rhythm not in (empty_settings.get("preferred_rhythm") or "")
    assert leftover_scope not in (empty_settings.get("memory_scope") or "")
    assert leftover_cadence not in (empty_settings.get("review_cadence") or "")
    empty_learner_project = prefer_recovered_settings_learner_project_onboarding(
        runtime=empty_runtime,
        existing=empty_runtime,
        learner_name=leftover_learner,
        target_project=leftover_project,
        onboarding_request=leftover_onboarding,
        project_context=leftover_project,
    )
    assert leftover_learner not in (empty_learner_project.get("learner_name") or "")
    assert leftover_onboarding not in (empty_learner_project.get("onboarding_request") or "")
    assert leftover_project not in (empty_learner_project.get("project_context") or "")
    empty_resource = prefer_recovered_resource_selected_detail(
        runtime=empty_runtime,
        existing=empty_runtime,
        title=leftover_resource_title,
        summary=leftover_next_hop_summary,
        match_summary=leftover_next_hop_summary,
    )
    assert leftover_resource_title not in (empty_resource.get("title") or "")
    live_runtime = {
        "current_step": "Add a token expiry test",
        "resume_state": "in_progress",
    }
    assert leftover_settings_profile_rhythm_is_not_live(
        runtime=live_runtime,
        existing=live_runtime,
    ) is True
    assert leftover_streaming_checkpoint_is_not_live(
        runtime=live_runtime,
        existing=live_runtime,
    ) is False
    assert leftover_settings_learner_project_onboarding_is_not_live(
        runtime=live_runtime,
        existing=live_runtime,
    ) is True
    live_settings = prefer_recovered_settings_profile_rhythm(
        runtime=live_runtime,
        existing=live_runtime,
        preferred_rhythm=leftover_rhythm,
        preferred_learning_mode=leftover_learning_mode,
        memory_scope=leftover_scope,
        review_cadence=leftover_cadence,
        working_set_mode="broad",
        review_reminder_mode="ahead",
    )
    assert leftover_rhythm not in (live_settings.get("preferred_rhythm") or "")
    assert leftover_scope not in (live_settings.get("memory_scope") or "")
    assert leftover_cadence not in (live_settings.get("review_cadence") or "")
    live_learner_project = prefer_recovered_settings_learner_project_onboarding(
        runtime=live_runtime,
        existing=live_runtime,
        learner_name=leftover_learner,
        target_project=leftover_project,
        onboarding_request=leftover_onboarding,
        project_context=leftover_project,
    )
    assert leftover_learner not in (live_learner_project.get("learner_name") or "")
    assert leftover_onboarding not in (live_learner_project.get("onboarding_request") or "")
    assert leftover_project not in (live_learner_project.get("project_context") or "")
    assert leftover_resource_sandbox_preview_is_not_live(
        runtime=live_runtime,
        existing=live_runtime,
    ) is True
    assert leftover_resource_sandbox_state_is_not_live(
        runtime=live_runtime,
        existing=live_runtime,
    ) is True
    assert leftover_resource_library_list_is_not_live(
        runtime=live_runtime,
        existing=live_runtime,
    ) is True
    leftover_stored = LearningPlan(
        id="plan-formal-old",
        title="Keep the current stage",
        current_step="Keep one auth check",
        stages=[],
    )
    leftover_not_live_runtime = {
        "current_step": "Add a token expiry test",
        "plan_id": "",
        "resume_state": "in_progress",
    }
    assert leftover_training_handoff_chrome_is_not_live(
        runtime=leftover_not_live_runtime,
        existing=leftover_not_live_runtime,
        plan=leftover_stored,
    ) is True
    assert leftover_training_focus_chrome_is_not_live(
        runtime=leftover_not_live_runtime,
        existing=leftover_not_live_runtime,
        plan=leftover_stored,
    ) is True
    assert leftover_resource_sandbox_preview_is_not_live(
        runtime=leftover_not_live_runtime,
        existing=leftover_not_live_runtime,
        plan=leftover_stored,
    ) is True
    assert leftover_resource_library_list_is_not_live(
        runtime=leftover_not_live_runtime,
        existing=leftover_not_live_runtime,
    ) is True
    leftover_not_live_chrome = prefer_recovered_training_handoff_chrome(
        runtime=leftover_not_live_runtime,
        existing=leftover_not_live_runtime,
        plan=leftover_stored,
        card_title=leftover_card,
        selected_card_title=leftover_selected,
        success_signal="Add a token expiry test",
    )
    assert leftover_not_live_chrome == {}
    leftover_matching_step_without_plan = {
        "current_step": leftover_stored.current_step,
        "plan_id": "",
        "resume_state": "in_progress",
    }
    assert leftover_training_handoff_chrome_is_not_live(
        runtime=leftover_matching_step_without_plan,
        existing=leftover_matching_step_without_plan,
        plan=leftover_stored,
    ) is True
    leftover_still_live_runtime = {
        "current_step": leftover_stored.current_step,
        "plan_id": leftover_stored.id,
        "resume_state": "in_progress",
    }
    assert leftover_training_handoff_chrome_is_not_live(
        runtime=leftover_still_live_runtime,
        existing=leftover_still_live_runtime,
        plan=leftover_stored,
    ) is False
    assert leftover_resource_library_list_is_not_live(
        runtime=leftover_still_live_runtime,
        existing=leftover_still_live_runtime,
        plan=leftover_stored,
    ) is True
    still_live_matching = prefer_recovered_training_handoff_chrome(
        runtime=leftover_still_live_runtime,
        existing=leftover_still_live_runtime,
        plan=leftover_stored,
        success_signal=leftover_stored.current_step,
        card_title=leftover_stored.current_step,
        selected_card_title=leftover_stored.current_step,
    )
    assert still_live_matching["success_signal"] == leftover_stored.current_step
    assert still_live_matching["card_title"] == leftover_stored.current_step
    assert leftover_coach_conversation_is_not_live(
        runtime=live_runtime,
        existing=live_runtime,
    ) is False
    live_chrome = prefer_recovered_training_handoff_chrome(
        runtime=live_runtime,
        existing=live_runtime,
        success_signal=leftover_signal,
        return_with=leftover_return,
        card_title=leftover_card,
        selected_card_title=leftover_selected,
        followup=leftover_followup,
        blocker=leftover_blocker,
        handoff_summary=leftover_summary,
        next_after_completion=leftover_next_after,
        fallback_action=leftover_fallback,
        next_hop_title=leftover_next_hop_title,
        next_hop_card_title=leftover_next_hop_card,
    )
    assert leftover_signal not in (live_chrome.get("success_signal") or "")
    assert leftover_card not in (live_chrome.get("card_title") or "")
    assert leftover_summary not in (live_chrome.get("handoff_summary") or "")
    assert leftover_next_after not in (live_chrome.get("next_after_completion") or "")
    assert leftover_next_hop_title not in (live_chrome.get("next_hop_title") or "")
    matching = prefer_recovered_training_handoff_chrome(
        runtime=live_runtime,
        existing=live_runtime,
        success_signal="Add a token expiry test",
        return_with="Add a token expiry test",
        card_title="Add a token expiry test",
        selected_card_title="Add a token expiry test",
        followup="Add a token expiry test",
        blocker="Add a token expiry test",
        handoff_summary="Add a token expiry test",
        next_after_completion="Add a token expiry test",
        fallback_action="Add a token expiry test",
        next_hop_title="Add a token expiry test",
        next_hop_card_title="Add a token expiry test",
        next_hop_handoff_summary="Add a token expiry test",
        next_hop_next_after_completion="Add a token expiry test",
        next_hop_fallback_action="Add a token expiry test",
        routing_next_after_completion="Add a token expiry test",
        routing_fallback_action="Add a token expiry test",
        why_this_card="Add a token expiry test",
        return_summary="Add a token expiry test",
        next_hop_return_summary="Add a token expiry test",
        next_hop_summary="Add a token expiry test",
        next_hop_why_now="Add a token expiry test",
    )
    assert matching == {}
    matching_resource = prefer_recovered_resource_selected_detail(
        runtime=live_runtime,
        existing=live_runtime,
        title="Add a token expiry test",
        summary="Add a token expiry test",
        match_summary="Add a token expiry test",
    )
    assert matching_resource == {}


def test_leftover_settings_profile_rhythm_and_sandbox_preview_stay_stored_not_live_when_step_empty(
    tmp_path: Path,
) -> None:
    leftover_rhythm = "Keep the leftover A rhythm"
    leftover_mode = "Keep the leftover A learning mode"
    leftover_learner = "Keep the leftover A learner"
    leftover_onboarding = "Keep the leftover A onboarding"
    leftover_project = "Keep the leftover A project context"
    leftover_sandbox_title = "Keep the leftover A sandbox preview"
    leftover_library_title = "Keep the leftover A library notes"
    leftover_conversation = "Keep the leftover A conversation"
    leftover_conversation_focus = "Keep the leftover A conversation focus"
    leftover_stream = "Keep the leftover A stream"
    leftover_stream_interrupt = "Keep the leftover A stream interrupt"
    leftover_sandbox_path = r"F:\workspace-a\notes.md"
    leftover_sandbox_root = r"F:\workspace-a"
    workspace_a = "workspace-leftover-settings-a"
    workspace_b = "workspace-leftover-settings-b"
    live_step = "Add a token expiry test"
    service = build_memory_service(tmp_path)
    empty_runtime = {
        "current_step": "",
        "resume_state": "in_progress",
        "workspace_id": workspace_a,
    }
    persisted = service.persist_plan_runtime_recovery(
        workspace_a,
        plan_runtime=empty_runtime,
        request_id="leftover-settings-empty-1",
    )
    assert persisted is not None
    service.update_workspace_state(
        workspace_a,
        preferred_rhythm=leftover_rhythm,
        preferred_learning_mode=leftover_mode,
        learner_name=leftover_learner,
        project_context=leftover_project,
        onboarding_request=leftover_onboarding,
        coach_defaults={
            "memory_scope": "personal",
            "working_set_mode": "broad",
            "review_cadence": "active",
            "review_reminder_mode": "ahead",
        },
        sandbox_preview={
            "path": leftover_sandbox_path,
            "title": leftover_sandbox_title,
            "excerpt": "A leftover sandbox preview",
        },
        sandbox_state={
            "root_path": leftover_sandbox_root,
            "selected_path": leftover_sandbox_path,
            "ready": True,
            "linked_resource_count": 3,
            "total_files": 4,
        },
        latest_conversation=[
            {
                "id": "msg-leftover-a",
                "role": "assistant",
                "content": leftover_conversation,
            }
        ],
        active_thread={
            "focus_area": leftover_conversation_focus,
            "summary": leftover_conversation,
            "next_step": leftover_conversation,
        },
    )
    persisted_stream = service.persist_streaming_checkpoint(
        workspace_a,
        request_id="stream-leftover-a",
        phase="interrupted",
        stream_message_id=leftover_stream,
        stop_reason=leftover_stream_interrupt,
        error=leftover_stream_interrupt,
        provider_name="Local Compatible",
        base_url="http://localhost:1234/v1",
        model="demo-model",
    )
    assert persisted_stream is not None
    service.repository.save_resource(
        workspace_a,
        ResourceRecord(
            id="resource-leftover-a",
            kind="markdown",
            name=leftover_library_title,
            source="notes.md",
            summary="A leftover library item",
        ),
    )
    stored = service.snapshot(workspace_a).workspace
    assert stored.get("preferred_rhythm") == leftover_rhythm
    assert stored.get("preferred_learning_mode") == leftover_mode
    assert stored.get("learner_name") == leftover_learner
    assert stored.get("project_context") == leftover_project
    assert stored.get("onboarding_request") == leftover_onboarding
    assert (stored.get("coach_defaults") or {}).get("memory_scope") == "personal"
    assert (stored.get("sandbox_preview") or {}).get("title") == leftover_sandbox_title
    assert (stored.get("sandbox_state") or {}).get("selected_path") == leftover_sandbox_path
    assert leftover_conversation in str(stored.get("latest_conversation") or "")
    assert leftover_conversation_focus in str(stored.get("active_thread") or "")
    assert leftover_stream in str(stored.get("latest_streaming_checkpoint") or "")
    assert leftover_stream_interrupt in str(stored.get("latest_streaming_checkpoint") or "")
    assert any(item.name == leftover_library_title for item in service.snapshot(workspace_a).resources)
    recovered = service.recover_workspace_facts(workspace_a).get(PLAN_RUNTIME_KEY) or {}
    assert leftover_settings_profile_rhythm_is_not_live(
        runtime=recovered,
        existing=recovered,
        current_step="",
    ) is True
    assert leftover_settings_learner_project_onboarding_is_not_live(
        runtime=recovered,
        existing=recovered,
        current_step="",
    ) is True
    assert leftover_resource_sandbox_preview_is_not_live(
        runtime=recovered,
        existing=recovered,
        current_step="",
    ) is True
    assert leftover_resource_sandbox_state_is_not_live(
        runtime=recovered,
        existing=recovered,
        current_step="",
    ) is True
    assert leftover_resource_library_list_is_not_live(
        runtime=recovered,
        existing=recovered,
        current_step="",
    ) is True
    assert leftover_coach_conversation_is_not_live(
        runtime=recovered,
        existing=recovered,
        current_step="",
    ) is True
    assert leftover_suggested_actions_is_not_live(
        runtime=recovered,
        existing=recovered,
        current_step="",
    ) is True
    assert leftover_first_look_headline_is_not_live(
        runtime=recovered,
        existing=recovered,
        current_step="",
    ) is True
    assert leftover_evaluation_headline_is_not_live(
        runtime=recovered,
        existing=recovered,
        current_step="",
    ) is True
    assert leftover_streaming_checkpoint_is_not_live(
        runtime=recovered,
        existing=recovered,
        current_step="",
    ) is True
    assert leftover_transfer_skill_is_not_live(
        runtime=recovered,
        existing=recovered,
        current_step="",
    ) is True
    omitted = prefer_recovered_settings_profile_rhythm(
        runtime=recovered,
        existing=recovered,
        preferred_rhythm=str(stored.get("preferred_rhythm") or ""),
        preferred_learning_mode=str(stored.get("preferred_learning_mode") or ""),
        memory_scope=str((stored.get("coach_defaults") or {}).get("memory_scope") or ""),
        review_cadence=str((stored.get("coach_defaults") or {}).get("review_cadence") or ""),
    )
    assert leftover_rhythm not in (omitted.get("preferred_rhythm") or "")
    assert leftover_mode not in (omitted.get("preferred_learning_mode") or "")
    omitted_learner = prefer_recovered_settings_learner_project_onboarding(
        runtime=recovered,
        existing=recovered,
        learner_name=str(stored.get("learner_name") or ""),
        target_project=str(stored.get("project_context") or ""),
        onboarding_request=str(stored.get("onboarding_request") or ""),
        project_context=str(stored.get("project_context") or ""),
    )
    assert leftover_learner not in (omitted_learner.get("learner_name") or "")
    assert leftover_onboarding not in (omitted_learner.get("onboarding_request") or "")
    live = service.persist_plan_runtime_recovery(
        workspace_a,
        plan_runtime={
            "current_step": live_step,
            "why_now": "Expired tokens still leak.",
            "resume_state": "waiting",
            "workspace_id": workspace_a,
        },
        request_id="leftover-settings-live-1",
    )
    assert live is not None
    assert leftover_settings_profile_rhythm_is_not_live(runtime=live, existing=live) is True
    assert leftover_resource_sandbox_state_is_not_live(runtime=live, existing=live) is True
    assert leftover_resource_library_list_is_not_live(runtime=live, existing=live) is True
    assert leftover_coach_conversation_is_not_live(runtime=live, existing=live) is False
    assert leftover_suggested_actions_is_not_live(runtime=live, existing=live) is False
    assert leftover_first_look_headline_is_not_live(runtime=live, existing=live) is False
    assert leftover_evaluation_headline_is_not_live(runtime=live, existing=live) is False
    assert leftover_streaming_checkpoint_is_not_live(runtime=live, existing=live) is False
    assert leftover_transfer_skill_is_not_live(runtime=live, existing=live) is False
    live_leftover_transfer = prefer_recovered_transfer_skill(
        runtime=live,
        existing=live,
        transfer={
            "concept": "Keep the leftover A transfer skill",
            "state": "transferable",
            "scene_count": 1,
            "workspace_ids": ["workspace-a"],
            "scene_keys": ["default"],
            "why": "Keep the leftover A transfer why",
            "next": "Keep the leftover A transfer next",
        },
    )
    assert (live_leftover_transfer or {}).get("state") == "transferable"
    live_settings = prefer_recovered_settings_profile_rhythm(
        runtime=live,
        existing=live,
        preferred_rhythm=leftover_rhythm,
        preferred_learning_mode=leftover_mode,
        memory_scope="personal",
        review_cadence="active",
    )
    assert leftover_rhythm not in (live_settings.get("preferred_rhythm") or "")
    assert live_settings.get("memory_scope") != "personal"
    hydrate_b = service.snapshot(workspace_b).workspace
    assert leftover_rhythm not in str(hydrate_b.get("preferred_rhythm") or "")
    assert leftover_mode not in str(hydrate_b.get("preferred_learning_mode") or "")
    assert leftover_learner not in str(hydrate_b.get("learner_name") or "")
    assert leftover_onboarding not in str(hydrate_b.get("onboarding_request") or "")
    assert leftover_project not in str(hydrate_b.get("project_context") or "")
    assert leftover_sandbox_title not in str(hydrate_b.get("sandbox_preview") or "")
    assert leftover_sandbox_path not in str(hydrate_b.get("sandbox_state") or "")
    assert leftover_library_title not in str([item.name for item in service.snapshot(workspace_b).resources])
    assert leftover_conversation not in str(hydrate_b.get("latest_conversation") or "")
    assert leftover_conversation_focus not in str(hydrate_b.get("active_thread") or "")
    assert leftover_stream not in str(hydrate_b.get("latest_streaming_checkpoint") or "")
    assert leftover_stream_interrupt not in str(hydrate_b.get("latest_streaming_checkpoint") or "")
    assert leftover_rhythm not in str(hydrate_b.get("coach_defaults") or "")


def test_leftover_formal_stage_does_not_paint_artifact_or_coach_stage_after_advance() -> None:
    leftover_stage = "Auth"
    plan = LearningPlan(
        id="plan-formal-old",
        title="Keep the current stage",
        current_stage_id="stage-1",
        current_step="Keep one auth check",
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
    advanced = {
        "current_step": "Add a token expiry test",
        "why_now": "",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    chrome = live_plan_artifact_stage_chrome(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        stage_title=leftover_stage,
        coaching_next_step="",
    )
    assert chrome["bullet"] == "Add a token expiry test"
    assert chrome["teaser"] == "Add a token expiry test"
    assert chrome["active_stage"] == "Add a token expiry test"
    assert chrome["stage_focus"] == "Add a token expiry test"
    assert chrome["lane_focus"] == "Add a token expiry test"
    assert chrome["summary_object"] == "Add a token expiry test"
    assert leftover_stage not in chrome.values()
    assert live_coach_stage_label(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        stage_title=leftover_stage,
    ) != leftover_stage
    empty_chrome = live_plan_artifact_stage_chrome(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        stage_title=leftover_stage,
    )
    assert empty_chrome["active_stage"] == ""
    assert empty_chrome["bullet"] == ""
    assert empty_chrome["teaser"] == ""
    still_on_plan = {
        "current_step": "Keep one auth check",
        "plan_id": "plan-formal-old",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_chrome = live_plan_artifact_stage_chrome(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        stage_title=leftover_stage,
    )
    assert still_chrome["active_stage"] == leftover_stage
    assert still_chrome["bullet"] == leftover_stage
    assert still_chrome["stage_focus"] == leftover_stage
    assert still_chrome["lane_focus"] == leftover_stage
    assert still_chrome["summary_object"] == leftover_stage


def test_leftover_formal_stage_does_not_fill_plan_update_or_persist_focus() -> None:
    leftover_stage = "Auth"
    plan = LearningPlan(
        id="plan-formal-old",
        title="Keep the current stage",
        current_stage_id="stage-1",
        current_step="Keep one auth check",
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
    advanced = {
        "current_step": "Add a token expiry test",
        "why_now": "",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    leftover_goal = "Keep one check"
    leftover_task = "Add login form"
    chrome = live_plan_update_persist_chrome(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        stage_title=leftover_stage,
        task_title=leftover_task,
        stage_goal=leftover_goal,
    )
    assert chrome["summary_object"] == "Add a token expiry test"
    assert chrome["stage_focus"] == "Add a token expiry test"
    assert chrome["lane_focus"] == "Add a token expiry test"
    assert chrome["next_step"] == "Add a token expiry test"
    assert chrome["active_task"] == "Add a token expiry test"
    assert chrome["focus_area"] == "Add a token expiry test"
    assert leftover_stage not in chrome["why_now"]
    assert leftover_task not in chrome["active_task"]
    assert leftover_stage not in chrome["summary_en"]
    assert leftover_stage not in chrome["summary_zh"]
    assert leftover_stage not in {chrome["summary_object"], chrome["stage_focus"], chrome["lane_focus"]}
    assert leftover_goal != chrome["next_step"]
    assert chrome["summary_en"] == "Plan tightened around Add a token expiry test."
    assert chrome["why_now"] == "Keep the live stage 'Add a token expiry test' small enough to recover."
    assert (
        live_leftover_focus_candidate(
            plan=plan,
            runtime=advanced,
            existing=advanced,
            stage_title=leftover_stage,
            task_title=leftover_task,
            candidate=leftover_stage,
            fallback="project-idea",
        )
        == "Add a token expiry test"
    )
    assert (
        live_leftover_focus_candidate(
            plan=plan,
            runtime=advanced,
            existing=advanced,
            stage_title=leftover_stage,
            candidate="auth/session",
            fallback="project-idea",
        )
        == "auth/session"
    )
    empty = live_plan_update_persist_chrome(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        stage_title=leftover_stage,
        task_title=leftover_task,
        stage_goal=leftover_goal,
    )
    assert empty["summary_object"] == ""
    assert empty["stage_focus"] == ""
    assert empty["lane_focus"] == ""
    assert empty["next_step"] == ""
    assert empty["active_task"] == ""
    assert empty["focus_area"] == ""
    assert leftover_stage not in empty["why_now"]
    assert leftover_task not in empty["active_task"]
    assert leftover_stage not in empty["summary_en"]
    still_on_plan = {
        "current_step": "Keep one auth check",
        "plan_id": "plan-formal-old",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still = live_plan_update_persist_chrome(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        stage_title=leftover_stage,
        task_title=leftover_task,
        stage_goal=leftover_goal,
    )
    assert still["summary_object"] == leftover_stage
    assert still["stage_focus"] == leftover_stage
    assert still["lane_focus"] == leftover_stage
    assert still["next_step"] == leftover_goal
    assert still["active_task"] == leftover_task
    assert still["focus_area"] == leftover_stage
    assert leftover_stage in still["why_now"]
    assert leftover_stage in still["summary_en"]
    assert (
        live_leftover_focus_candidate(
            plan=plan,
            runtime=still_on_plan,
            existing=still_on_plan,
            stage_title=leftover_stage,
            task_title=leftover_task,
            candidate=leftover_stage,
            fallback="adaptation",
        )
        == leftover_stage
    )


def test_leftover_formal_plan_fields_do_not_write_on_remaining_refresh_branches() -> None:
    leftover_step = "Keep one auth check"
    leftover_why = "Keep the leftover why"
    leftover_stage = "Auth"
    plan = LearningPlan(
        id="plan-formal-old",
        title="Keep the current stage",
        current_stage_id="stage-1",
        current_step=leftover_step,
        why_now=leftover_why,
        next_after_current="Then review the leftover path",
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
    advanced = {
        "current_step": "Add a token expiry test",
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    leftover_next = "Then review the leftover path"
    completed = live_plan_refresh_step_why(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        current_step=leftover_step,
        why_now=leftover_why,
        next_after_current=leftover_next,
        stage_title=leftover_stage,
    )
    assert completed["current_step"] == "Add a token expiry test"
    assert completed["why_now"] == "Expired tokens still leak."
    assert completed["next_after_current"] == ""
    assert leftover_step not in completed.values()
    assert leftover_why not in completed.values()
    assert leftover_next not in completed.values()
    else_branch = live_plan_refresh_step_why(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        current_step=leftover_step,
        why_now=leftover_why,
        next_after_current=leftover_next,
        stage_title=leftover_stage,
    )
    assert else_branch["current_step"] == "Add a token expiry test"
    assert else_branch["why_now"] == "Expired tokens still leak."
    assert else_branch["next_after_current"] == ""
    fresh = live_plan_refresh_step_why(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        current_step="Land one expiry test",
        why_now="The current slice is ready to move forward.",
        next_after_current="Land one expiry test",
        stage_title=leftover_stage,
    )
    assert fresh["current_step"] == "Land one expiry test"
    assert fresh["why_now"] == "The current slice is ready to move forward."
    assert fresh["next_after_current"] == "Land one expiry test"
    empty = live_plan_refresh_step_why(
        plan=plan,
        runtime={"current_step": "", "why_now": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        current_step=leftover_step,
        why_now=leftover_why,
        next_after_current=leftover_next,
        stage_title=leftover_stage,
    )
    assert empty["current_step"] == ""
    assert empty["why_now"] == ""
    assert empty["next_after_current"] == ""
    still_on_plan = {
        "current_step": leftover_step,
        "why_now": leftover_why,
        "plan_id": "plan-formal-old",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still = live_plan_refresh_step_why(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        current_step=leftover_step,
        why_now=leftover_why,
        next_after_current=leftover_next,
        stage_title=leftover_stage,
    )
    assert still["current_step"] == leftover_step
    assert still["why_now"] == leftover_why
    assert still["next_after_current"] == leftover_next
    recovered_next = {
        **advanced,
        "next_after_current": "Wire the guard into the login path.",
    }
    with_recovered_next = live_plan_refresh_step_why(
        plan=plan,
        runtime=recovered_next,
        existing=recovered_next,
        current_step=leftover_step,
        why_now=leftover_why,
        next_after_current=leftover_next,
        stage_title=leftover_stage,
    )
    assert with_recovered_next["next_after_current"] == "Wire the guard into the login path."
    assert leftover_next not in with_recovered_next.values()
    assert live_plan_mismatch_candidate_step(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        current_step=leftover_step,
        stage_title=leftover_stage,
    ) == "Add a token expiry test"
    assert live_plan_mismatch_candidate_step(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        current_step=leftover_step,
        stage_title=leftover_stage,
    ) == ""
    assert live_plan_mismatch_candidate_step(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        current_step=leftover_step,
        stage_title=leftover_stage,
    ) == leftover_step


def test_leftover_formal_titles_do_not_persist_in_sandbox_mismatch_or_memory_focus(tmp_path: Path) -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_stage_id = "stage-1"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_goal = "Keep one check"
    leftover_plan_id = "plan-formal-old"
    plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_stage_id=leftover_stage_id,
        current_step=leftover_step,
        why_now="Keep the leftover why",
        next_after_current="Then review the leftover path",
        stages=[
            PlanStage(
                id=leftover_stage_id,
                title=leftover_stage,
                goal=leftover_goal,
                outcomes=["pass"],
                status="active",
            )
        ],
    )
    advanced = {
        "current_step": "Add a token expiry test",
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    chrome = live_plan_snapshot_persist_chrome(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        stage_title=leftover_stage,
    )
    assert chrome["plan_title"] == "Add a token expiry test"
    assert chrome["current_step"] == "Add a token expiry test"
    assert chrome["stage_title"] == "Add a token expiry test"
    assert chrome["focus"] == "Add a token expiry test"
    assert chrome["stage_id"] == ""
    assert chrome["summary"] == ""
    assert chrome["show_stages"] == ""
    assert chrome["plan_id"] == ""
    assert leftover_title not in chrome.values()
    assert leftover_stage not in chrome.values()
    assert leftover_stage_id not in chrome.values()
    assert leftover_step not in chrome.values()
    assert leftover_summary not in chrome.values()
    assert leftover_plan_id not in chrome.values()
    empty = live_plan_snapshot_persist_chrome(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        stage_title=leftover_stage,
    )
    assert empty["plan_title"] == ""
    assert empty["current_step"] == ""
    assert empty["stage_title"] == ""
    assert empty["focus"] == ""
    assert empty["stage_id"] == ""
    assert empty["summary"] == ""
    assert empty["show_stages"] == ""
    assert empty["plan_id"] == ""
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still = live_plan_snapshot_persist_chrome(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        stage_title=leftover_stage,
    )
    assert still["plan_title"] == leftover_title
    assert still["stage_title"] == leftover_stage
    assert still["stage_id"] == leftover_stage_id
    assert still["current_step"] == leftover_step
    assert still["focus"] == leftover_stage
    assert still["summary"] == leftover_summary
    assert still["show_stages"] == "1"
    assert still["plan_id"] == leftover_plan_id
    sandbox = SandboxService(data_root=tmp_path)
    leftover_md = Path(
        sandbox.persist_plan_snapshot(
            "workspace-plan",
            plan,
            reason="updated",
            overlay=chrome,
        ).path
    ).read_text(encoding="utf-8")
    assert leftover_summary not in leftover_md
    assert leftover_title not in leftover_md
    assert leftover_stage not in leftover_md
    assert leftover_goal not in leftover_md
    assert leftover_step not in leftover_md
    assert leftover_plan_id not in leftover_md
    assert "- Plan ID:" not in leftover_md
    assert "## Stages" not in leftover_md
    assert "Add a token expiry test" in leftover_md
    still_md = Path(
        sandbox.persist_plan_snapshot(
            "workspace-plan",
            plan,
            reason="updated",
            overlay=still,
        ).path
    ).read_text(encoding="utf-8")
    assert leftover_summary in still_md
    assert leftover_title in still_md
    assert leftover_stage in still_md
    assert leftover_goal in still_md
    assert "## Stages" in still_md
    assert f"- Plan ID: {leftover_plan_id}" in still_md
    assert live_plan_mismatch_candidate_plan_id(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        request_plan_id=leftover_plan_id,
    ) == ""
    assert live_plan_mismatch_candidate_plan_id(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        request_plan_id=leftover_plan_id,
    ) == ""
    assert live_plan_mismatch_candidate_plan_id(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        request_plan_id=leftover_plan_id,
    ) == leftover_plan_id


def test_leftover_formal_titles_do_not_live_in_remaining_memory_snapshots(tmp_path: Path) -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
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
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    leftover_workspace = {
        "latest_coach_focus_area": leftover_title,
        "latest_turn_summary": leftover_summary,
        "plan_id": leftover_plan_id,
        "active_thread": {
            "focus_area": leftover_title,
            "summary": leftover_title,
            "next_step": leftover_step,
        },
        PLAN_RUNTIME_KEY: advanced,
    }
    leftover_thread = {
        "focus_area": leftover_title,
        "summary": leftover_title,
        "next_step": leftover_step,
    }
    leftover_feedback = [
        {
            "kind": "plan_mismatch",
            "message": "This path is stale.",
            "focus_area": leftover_title,
            "plan_id": leftover_plan_id,
        }
    ]
    leftover_observation = f"Active thread is still '{leftover_title}'. Continue."
    leftover_win = f"You already have a live stage to work inside: {leftover_title}."
    leftover_weakness = f"Stuck on {leftover_title} after the leftover path."
    leftover_strategies = [
        {
            "scenario": "coach",
            "focus_area": leftover_title,
            "last_summary": leftover_summary,
        }
    ]
    leftover_outcomes = [
        {
            "concept": leftover_title,
            "outcome": "evaluation",
            "summary": leftover_summary,
        }
    ]
    leftover_reflection = f"Keep going from '{leftover_title}' before opening a new lane."
    leftover_adaptation = {
        "summary": f"Adaptive coaching still named '{leftover_title}'.",
        "evidence": [f"Continue '{leftover_title}' before widening."],
    }
    leftover_evidence = [f"Continue {leftover_title} with this next move: {leftover_step}"]
    leftover_plan_change = f"Advanced from {leftover_stage} to {leftover_title}."
    leftover_reviews = [
        {
            "concept": leftover_title,
            "reason": leftover_summary,
            "focus_area": leftover_title,
            "task_hint": leftover_step,
        }
    ]
    leftover_assets = [
        {
            "title": leftover_title,
            "summary": leftover_summary,
            "focus_area": leftover_title,
            "concept_card": leftover_title,
            "source_summary": leftover_summary,
        }
    ]
    leftover_cards = [
        {
            "title": leftover_title,
            "why_now": leftover_summary,
            "focus_area": leftover_title,
            "target_skill": leftover_title,
            "problem_statement": leftover_summary,
            "question": leftover_title,
            "scenario": leftover_title,
            "suggested_workspace_action": leftover_title,
            "deliverable": leftover_title,
            "success_signal": leftover_title,
            "next_after_completion": leftover_summary,
            "learner_deliverables": [leftover_title],
        }
    ]
    leftover_lab = {
        "title": leftover_title,
        "focus_area": leftover_title,
        "summary": leftover_summary,
        "success_signal": leftover_title,
        "review_outcome": leftover_summary,
        "learner_deliverables": [leftover_title],
        "verification_steps": [leftover_summary],
        "migrate_back_guidance": [leftover_title],
    }
    leftover_lab_history = [
        {
            "note": leftover_summary,
            "before_snapshot": leftover_lab,
            "after_snapshot": leftover_lab,
        }
    ]
    leftover_flash = {
        "title": leftover_title,
        "focus_area": leftover_title,
        "cards": leftover_cards,
    }
    leftover_drill = {
        "title": leftover_title,
        "focus_area": leftover_title,
        "summary": leftover_summary,
        "success_signal": leftover_title,
        "return_with": leftover_summary,
        "questions": [
            {
                "prompt": leftover_title,
                "answer": leftover_summary,
                "explanation": leftover_title,
                "knowledge_type": leftover_title,
                "choices": [leftover_title],
            }
        ],
    }
    leftover_drill_history = [
        {
            "note": leftover_summary,
            "before_snapshot": leftover_drill,
            "after_snapshot": leftover_drill,
        }
    ]
    leftover_artifact = {
        "title": leftover_title,
        "focus_area": leftover_title,
        "summary": leftover_summary,
        "root_cause": leftover_title,
        "guardrail": leftover_summary,
        "verified_result": leftover_title,
        "blocker": leftover_title,
    }
    leftover_history = [
        {
            "note": leftover_summary,
            "before_snapshot": leftover_artifact,
            "after_snapshot": leftover_artifact,
        }
    ]
    overlay = live_memory_snapshot_overlay(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        recent_summary=leftover_title,
        workspace=leftover_workspace,
        active_thread=leftover_thread,
        teaching_observations=[leftover_observation],
        user_feedback=leftover_feedback,
        recent_wins=[leftover_win],
        weaknesses=[leftover_weakness],
        teaching_strategy_effectiveness=leftover_strategies,
        learning_outcomes=leftover_outcomes,
        top_weakness=leftover_title,
        reflections=[leftover_reflection],
        lowest_mastery_concepts=[leftover_title],
        coaching_adaptation=leftover_adaptation,
        memory_evidence=leftover_evidence,
        plan_change_summary=leftover_plan_change,
        due_reviews=leftover_reviews,
        teaching_assets=leftover_assets,
        training_cards=leftover_cards,
        review_artifact=leftover_artifact,
        review_artifact_history=leftover_history,
        scenario_lab=leftover_lab,
        scenario_lab_history=leftover_lab_history,
        flash_deck=leftover_flash,
        theory_drill=leftover_drill,
        theory_drill_history=leftover_drill_history,
    )
    assert leftover_title not in overlay["recent_summary"]
    assert leftover_summary not in overlay["recent_summary"]
    assert overlay["workspace"]["latest_coach_focus_area"] == recovered_step
    assert overlay["workspace"]["latest_turn_summary"] == recovered_step
    assert overlay["workspace"]["plan_id"] == ""
    assert leftover_title not in overlay["workspace"]["active_thread"].values()
    assert leftover_step not in overlay["workspace"]["active_thread"].values()
    assert overlay["workspace"][PLAN_RUNTIME_KEY]["current_step"] == recovered_step
    assert overlay["active_thread"]["focus_area"] == recovered_step
    assert leftover_title not in overlay["teaching_observations"][0]
    assert leftover_plan_id not in [item.get("plan_id") for item in overlay["user_feedback"]]
    assert leftover_title not in [item.get("focus_area") for item in overlay["user_feedback"]]
    assert leftover_title not in " ".join(overlay["recent_wins"])
    assert leftover_title not in " ".join(overlay["weaknesses"])
    assert leftover_title not in [item.get("focus_area") for item in overlay["teaching_strategy_effectiveness"]]
    assert leftover_summary not in [item.get("last_summary") for item in overlay["teaching_strategy_effectiveness"]]
    assert leftover_title not in [item.get("concept") for item in overlay["learning_outcomes"]]
    assert leftover_summary not in [item.get("summary") for item in overlay["learning_outcomes"]]
    assert leftover_title not in overlay["top_weakness"]
    assert leftover_title not in " ".join(overlay["reflections"])
    assert leftover_title not in overlay["lowest_mastery_concepts"]
    assert leftover_title not in overlay["coaching_adaptation"].get("summary", "")
    assert leftover_title not in " ".join(overlay["coaching_adaptation"].get("evidence") or [])
    assert leftover_title not in " ".join(overlay["memory_evidence"])
    assert leftover_title not in overlay["plan_change_summary"]
    assert leftover_stage not in overlay["plan_change_summary"]
    assert leftover_title not in [item.get("concept") for item in overlay["due_reviews"]]
    assert leftover_summary not in [item.get("reason") for item in overlay["due_reviews"]]
    assert leftover_title not in [item.get("title") for item in overlay["teaching_assets"]]
    assert leftover_summary not in [item.get("summary") for item in overlay["teaching_assets"]]
    assert leftover_title not in [item.get("title") for item in overlay["training_cards"]]
    assert leftover_title not in [item.get("focus_area") for item in overlay["training_cards"]]
    assert leftover_title not in overlay["review_artifact"].get("title", "")
    assert leftover_summary not in overlay["review_artifact"].get("summary", "")
    assert leftover_title not in overlay["review_artifact"].get("root_cause", "")
    assert leftover_summary not in [item.get("problem_statement") for item in overlay["training_cards"]]
    assert leftover_title not in [item.get("question") for item in overlay["training_cards"]]
    assert leftover_title not in [item.get("scenario") for item in overlay["training_cards"]]
    assert leftover_title not in overlay["review_artifact_history"][0]["before_snapshot"].get("title", "")
    assert leftover_summary not in overlay["review_artifact_history"][0].get("note", "")
    assert leftover_title not in overlay["review_artifact_history"][0]["after_snapshot"].get("title", "")
    assert leftover_title not in [item.get("deliverable") for item in overlay["training_cards"]]
    assert leftover_title not in [item.get("success_signal") for item in overlay["training_cards"]]
    assert leftover_title not in overlay["scenario_lab"].get("title", "")
    assert leftover_summary not in overlay["scenario_lab"].get("summary", "")
    assert leftover_title not in overlay["scenario_lab"].get("learner_deliverables", [])
    assert leftover_title not in overlay["scenario_lab_history"][0]["before_snapshot"].get("title", "")
    assert leftover_title not in overlay["flash_deck"].get("title", "")
    assert leftover_title not in overlay["flash_deck"].get("focus_area", "")
    assert leftover_title not in [item.get("title") for item in overlay["flash_deck"].get("cards") or []]
    assert leftover_title not in overlay["theory_drill"].get("title", "")
    assert leftover_summary not in overlay["theory_drill"].get("summary", "")
    assert leftover_title not in overlay["theory_drill"].get("focus_area", "")
    assert leftover_title not in [item.get("prompt") for item in overlay["theory_drill"].get("questions") or []]
    assert leftover_title not in overlay["theory_drill_history"][0]["before_snapshot"].get("title", "")
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still = live_memory_snapshot_overlay(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        recent_summary=leftover_title,
        workspace={**leftover_workspace, PLAN_RUNTIME_KEY: still_on_plan},
        active_thread=leftover_thread,
        teaching_observations=[leftover_observation],
        user_feedback=leftover_feedback,
        recent_wins=[leftover_win],
        weaknesses=[leftover_weakness],
        teaching_strategy_effectiveness=leftover_strategies,
        learning_outcomes=leftover_outcomes,
        top_weakness=leftover_title,
        reflections=[leftover_reflection],
        lowest_mastery_concepts=[leftover_title],
        coaching_adaptation=leftover_adaptation,
        memory_evidence=leftover_evidence,
        plan_change_summary=leftover_plan_change,
        due_reviews=leftover_reviews,
        teaching_assets=leftover_assets,
        training_cards=leftover_cards,
        review_artifact=leftover_artifact,
        review_artifact_history=leftover_history,
        scenario_lab=leftover_lab,
        scenario_lab_history=leftover_lab_history,
        flash_deck=leftover_flash,
        theory_drill=leftover_drill,
        theory_drill_history=leftover_drill_history,
    )
    assert leftover_title in still["recent_summary"]
    assert still["workspace"]["latest_coach_focus_area"] == leftover_title
    assert still["workspace"]["plan_id"] == leftover_plan_id
    assert still["active_thread"]["focus_area"] == leftover_title
    assert leftover_title in still["teaching_observations"][0]
    assert still["user_feedback"][0]["plan_id"] == leftover_plan_id
    assert leftover_title in " ".join(still["recent_wins"])
    assert leftover_title in " ".join(still["weaknesses"])
    assert still["teaching_strategy_effectiveness"][0]["focus_area"] == leftover_title
    assert still["learning_outcomes"][0]["concept"] == leftover_title
    assert still["top_weakness"] == leftover_title
    assert leftover_title in " ".join(still["reflections"])
    assert leftover_title in still["lowest_mastery_concepts"]
    assert leftover_title in still["coaching_adaptation"]["summary"]
    assert leftover_title in " ".join(still["memory_evidence"])
    assert leftover_title in still["plan_change_summary"]
    assert leftover_stage in still["plan_change_summary"]
    assert still["due_reviews"][0]["concept"] == leftover_title
    assert still["teaching_assets"][0]["title"] == leftover_title
    assert still["training_cards"][0]["title"] == leftover_title
    assert still["training_cards"][0]["problem_statement"] == leftover_summary
    assert still["review_artifact"]["title"] == leftover_title
    assert still["review_artifact"]["root_cause"] == leftover_title
    assert still["review_artifact_history"][0]["before_snapshot"]["title"] == leftover_title
    assert leftover_summary in still["review_artifact_history"][0]["note"]
    assert still["training_cards"][0]["deliverable"] == leftover_title
    assert still["scenario_lab"]["title"] == leftover_title
    assert still["flash_deck"]["title"] == leftover_title
    assert still["flash_deck"]["cards"][0]["title"] == leftover_title
    assert still["theory_drill"]["title"] == leftover_title
    assert still["theory_drill"]["questions"][0]["prompt"] == leftover_title
    service = build_memory_service(tmp_path)
    service.repository.save_plan("workspace-plan", plan)
    service.persist_plan_runtime_recovery(
        "workspace-plan",
        plan=plan,
        plan_runtime=advanced,
    )
    service.update_workspace_state(
        "workspace-plan",
        latest_coach_focus_area=leftover_title,
        latest_turn_summary=leftover_summary,
        plan_id=leftover_plan_id,
        active_thread=leftover_thread,
    )
    structured = service.structured_for_workspace("workspace-plan")
    structured.append_session_message("session-plan", leftover_title)
    structured.update_active_thread(
        scenario="coach",
        focus_area=leftover_title,
        summary=leftover_title,
        next_step=leftover_step,
    )
    service.record_user_feedback(
        workspace_id="workspace-plan",
        kind="plan_mismatch",
        message="This path is stale.",
        focus_area=leftover_title,
        plan_id=leftover_plan_id,
    )
    structured.record_weakness(leftover_title, leftover_weakness)
    structured.remember_teaching_strategy_effectiveness(
        scenario="coach",
        focus_area=leftover_title,
        outcome="user_feedback",
        summary=leftover_summary,
    )
    structured.remember_learning_outcome(
        leftover_title,
        "evaluation",
        summary=leftover_summary,
        action_type="user_feedback",
    )
    structured.add_reflection("task-leftover", leftover_reflection)
    structured.update_mastery(leftover_title, delta=-0.4, confidence=0.2)
    structured.upsert_teaching_asset(
        TeachingKnowledgeAsset(
            kind="concept_card",
            title=leftover_title,
            summary=leftover_summary,
            focus_area=leftover_title,
            workspace_id="workspace-plan",
        )
    )
    service.upsert_card(
        "workspace-plan",
        TrainingCardCandidateSnapshot(
            card_id="card-leftover",
            title=leftover_title,
            why_now=leftover_summary,
            focus_area=leftover_title,
            target_skill=leftover_title,
            problem_statement=leftover_summary,
            question=leftover_title,
            scenario=leftover_title,
            suggested_workspace_action=leftover_title,
            deliverable=leftover_title,
            success_signal=leftover_title,
            next_after_completion=leftover_summary,
            learner_deliverables=[leftover_title],
        ),
    )
    structured._review_artifact = ReviewArtifactSnapshot(
        id="review-leftover",
        title=leftover_title,
        focus_area=leftover_title,
        summary=leftover_summary,
        root_cause=leftover_title,
        guardrail=leftover_summary,
        verified_result=leftover_title,
        blocker=leftover_title,
    )
    structured._scenario_lab = ScenarioLab(
        id="lab-leftover",
        title=leftover_title,
        focus_area=leftover_title,
        summary=leftover_summary,
        success_signal=leftover_title,
        review_outcome=leftover_summary,
        learner_deliverables=[leftover_title],
        verification_steps=[leftover_summary],
        migrate_back_guidance=[leftover_title],
    )
    structured._scenario_lab_history.append(
        ScenarioLabHistoryEntry(
            entry_id="lab-hist-leftover",
            scenario_lab_id="lab-leftover",
            action="created",
            version=1,
            note=leftover_summary,
            before_snapshot={"title": leftover_title, "summary": leftover_summary},
            after_snapshot={"title": leftover_title, "summary": leftover_summary},
        )
    )
    structured._theory_drill = TheoryDrillSnapshot(
        id="drill-leftover",
        title=leftover_title,
        focus_area=leftover_title,
        summary=leftover_summary,
        success_signal=leftover_title,
        return_with=leftover_summary,
        questions=[
            TheoryDrillQuestion(
                id="q-leftover",
                prompt=leftover_title,
                answer=leftover_summary,
                explanation=leftover_title,
                knowledge_type=leftover_title,
                choices=[leftover_title],
            )
        ],
    )
    structured._theory_drill_history.append(
        TheoryDrillHistoryEntry(
            entry_id="drill-hist-leftover",
            theory_drill_id="drill-leftover",
            action="created",
            version=1,
            note=leftover_summary,
            before_snapshot={"title": leftover_title, "summary": leftover_summary},
            after_snapshot={"title": leftover_title, "summary": leftover_summary},
        )
    )
    structured._flash_deck = FlashDeckSnapshot(
        id="flash-leftover",
        title=leftover_title,
        focus_area=leftover_title,
        cards=[
            TrainingCardCandidateSnapshot(
                card_id="flash-card-leftover",
                title=leftover_title,
                focus_area=leftover_title,
                question=leftover_title,
                deliverable=leftover_title,
            )
        ],
    )
    structured._review_artifact_history.append(
        ReviewArtifactHistoryEntry(
            entry_id="hist-leftover",
            review_artifact_id="review-leftover",
            action="reviewed",
            version=1,
            note=leftover_summary,
            before_snapshot={
                "title": leftover_title,
                "focus_area": leftover_title,
                "summary": leftover_summary,
            },
            after_snapshot={
                "title": leftover_title,
                "focus_area": leftover_title,
                "summary": leftover_summary,
            },
        )
    )
    snap = service.snapshot("workspace-plan")
    assert leftover_title not in snap.recent_summary
    assert leftover_title not in str(snap.workspace.get("latest_coach_focus_area") or "")
    assert leftover_summary not in str(snap.workspace.get("latest_turn_summary") or "")
    assert leftover_plan_id not in str(snap.workspace.get("plan_id") or "")
    assert snap.active_thread is not None
    assert leftover_title not in snap.active_thread.focus_area
    assert leftover_title not in " ".join(snap.teaching_observations)
    assert leftover_plan_id not in [item.get("plan_id") for item in snap.user_feedback]
    assert leftover_title not in " ".join(snap.recent_wins)
    assert leftover_title not in " ".join(snap.weaknesses)
    assert leftover_title not in [item.get("focus_area") for item in snap.teaching_strategy_effectiveness]
    assert leftover_title not in [item.get("concept") for item in snap.learning_outcomes]
    assert leftover_summary not in [item.get("summary") for item in snap.learning_outcomes]
    assert leftover_title not in snap.top_weakness
    assert leftover_title not in " ".join(snap.reflections)
    assert leftover_title not in snap.lowest_mastery_concepts
    if snap.coaching_adaptation is not None:
        assert leftover_title not in snap.coaching_adaptation.summary
        assert leftover_title not in " ".join(snap.coaching_adaptation.evidence)
    assert leftover_title not in " ".join(snap.memory_evidence)
    assert leftover_title not in [item.concept for item in snap.due_reviews]
    assert leftover_summary not in [item.reason for item in snap.due_reviews]
    assert leftover_title not in [item.title for item in snap.teaching_assets]
    assert leftover_summary not in [item.summary for item in snap.teaching_assets]
    leftover_stage_observation = "Stay inside 'Auth'"
    assert leftover_stage_observation not in " ".join(snap.teaching_observations)
    assert leftover_title not in [item.title for item in snap.training_card_candidates]
    assert leftover_title not in [item.focus_area for item in snap.training_card_candidates]
    assert leftover_summary not in [item.problem_statement for item in snap.training_card_candidates]
    assert leftover_title not in [item.question for item in snap.training_card_candidates]
    assert leftover_title not in [item.scenario for item in snap.training_card_candidates]
    assert leftover_title not in [item.deliverable for item in snap.training_card_candidates]
    assert leftover_title not in [item.success_signal for item in snap.training_card_candidates]
    assert snap.scenario_lab is not None
    assert leftover_title not in snap.scenario_lab.title
    assert leftover_summary not in snap.scenario_lab.summary
    assert leftover_title not in snap.scenario_lab.learner_deliverables
    assert leftover_title not in [item.before_snapshot.get("title", "") for item in snap.scenario_lab_history]
    assert snap.flash_deck is not None
    assert leftover_title not in snap.flash_deck.title
    assert leftover_title not in snap.flash_deck.focus_area
    assert leftover_title not in [item.title for item in snap.flash_deck.cards]
    assert snap.theory_drill is not None
    assert leftover_title not in snap.theory_drill.title
    assert leftover_summary not in snap.theory_drill.summary
    assert leftover_title not in snap.theory_drill.focus_area
    assert leftover_title not in [item.prompt for item in snap.theory_drill.questions]
    assert leftover_title not in [item.before_snapshot.get("title", "") for item in snap.theory_drill_history]
    assert snap.review_artifact is not None
    assert leftover_title not in snap.review_artifact.title
    assert leftover_summary not in snap.review_artifact.summary
    assert leftover_title not in snap.review_artifact.root_cause
    assert leftover_title not in [item.before_snapshot.get("title", "") for item in snap.review_artifact_history]
    assert leftover_summary not in [item.note for item in snap.review_artifact_history]
    planner = PlannerService()
    planner_plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        current_stage_id="stage-1",
        current_step=leftover_step,
        stages=[
            PlanStage(
                id="stage-1",
                title=leftover_stage,
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            ),
            PlanStage(
                id="stage-2",
                title=leftover_title,
                goal="Keep the leftover title live",
                outcomes=["pass"],
                status="pending",
            ),
        ],
    )
    evidence = EvidenceItem(id="ev-leftover", summary="pass", concepts=["pass"], outcome="pass")
    leftover_advance = planner.evaluate_evidence_for_plan(
        evidence,
        planner_plan,
        runtime=advanced,
        existing=advanced,
    )
    assert leftover_title not in leftover_advance.plan_change_summary
    assert leftover_stage not in leftover_advance.plan_change_summary
    still_plan = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        current_stage_id="stage-1",
        current_step=leftover_step,
        stages=[
            PlanStage(
                id="stage-1",
                title=leftover_stage,
                goal="Keep one check",
                outcomes=["pass"],
                status="active",
            ),
            PlanStage(
                id="stage-2",
                title=leftover_title,
                goal="Keep the leftover title live",
                outcomes=["pass"],
                status="pending",
            ),
        ],
    )
    still_advance = planner.evaluate_evidence_for_plan(
        evidence,
        still_plan,
        runtime=still_on_plan,
        existing=still_on_plan,
    )
    assert leftover_stage in still_advance.plan_change_summary
    assert leftover_title in still_advance.plan_change_summary
    assert leftover_title not in plan.why_now
    assert leftover_stage not in plan.why_now
    leftover_empty = LearningPlan.model_validate(
        {
            "id": leftover_plan_id,
            "title": leftover_title,
            "summary": leftover_summary,
            "current_step": "",
        },
        context={"runtime": advanced, "existing": advanced},
    )
    assert leftover_empty.current_step == ""
    assert leftover_title not in leftover_empty.current_step
    assert leftover_summary not in leftover_empty.current_step
    assert leftover_title not in leftover_empty.why_now
    assert leftover_summary not in leftover_empty.why_now
    leftover_goal = LearningPlan.model_validate(
        {
            "id": leftover_plan_id,
            "title": leftover_title,
            "summary": leftover_summary,
            "current_step": "",
            "stages": [
                {
                    "id": "stage-1",
                    "title": leftover_stage,
                    "goal": "Keep one check",
                    "outcomes": ["pass"],
                    "status": "active",
                }
            ],
        },
        context={"runtime": advanced, "existing": advanced},
    )
    assert leftover_goal.current_step == ""
    assert leftover_goal.current_step != "Keep one check"
    still_empty = LearningPlan(
        id=leftover_plan_id,
        title=leftover_title,
        summary=leftover_summary,
        current_step="",
    )
    assert leftover_title in still_empty.current_step or leftover_summary in still_empty.current_step
    assert live_plan_current_step_fill(
        plan=LearningPlan(id=leftover_plan_id, title=leftover_title, summary=leftover_summary),
        runtime=advanced,
        existing=advanced,
        summary=leftover_summary,
        title=leftover_title,
    ) == ""
    assert leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
    )
    leftover_success = planner.advance_plan_after_success(
        LearningPlan(
            id=leftover_plan_id,
            title=leftover_title,
            current_stage_id="stage-1",
            current_step=leftover_step,
            stages=[
                PlanStage(
                    id="stage-1",
                    title=leftover_stage,
                    goal="Keep one check",
                    outcomes=["pass"],
                    status="active",
                ),
                PlanStage(
                    id="stage-2",
                    title=leftover_title,
                    goal="Keep the leftover title live",
                    outcomes=["pass"],
                    status="pending",
                ),
            ],
        ),
        None,
        passed=True,
        runtime=advanced,
        existing=advanced,
    )
    assert leftover_success is not None
    assert leftover_title not in leftover_success.why_now
    assert leftover_stage not in leftover_success.why_now
    assert leftover_step not in leftover_success.why_now
    assert leftover_title not in leftover_success.current_step
    assert leftover_stage not in leftover_success.current_step
    assert leftover_step not in leftover_success.current_step
    leftover_next = planner.advance_plan_after_success(
        LearningPlan(
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
                ),
                PlanStage(
                    id="stage-2",
                    title=leftover_title,
                    goal="Keep the leftover title live",
                    outcomes=["pass"],
                    status="pending",
                ),
                PlanStage(
                    id="stage-3",
                    title=leftover_title,
                    goal=leftover_summary,
                    outcomes=["pass"],
                    status="pending",
                ),
            ],
        ),
        None,
        passed=True,
        runtime=advanced,
        existing=advanced,
    )
    assert leftover_next is not None
    assert leftover_summary not in leftover_next.next_after_current
    assert leftover_title not in leftover_next.next_after_current
    assert leftover_stage not in leftover_next.next_after_current
    still_next = planner.advance_plan_after_success(
        LearningPlan(
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
                ),
                PlanStage(
                    id="stage-2",
                    title=leftover_title,
                    goal="Keep the leftover title live",
                    outcomes=["pass"],
                    status="pending",
                ),
                PlanStage(
                    id="stage-3",
                    title=leftover_title,
                    goal=leftover_summary,
                    outcomes=["pass"],
                    status="pending",
                ),
            ],
        ),
        None,
        passed=True,
        runtime=still_on_plan,
        existing=still_on_plan,
    )
    assert still_next is not None
    assert leftover_summary in still_next.next_after_current
    still_success = planner.advance_plan_after_success(
        LearningPlan(
            id=leftover_plan_id,
            title=leftover_title,
            current_stage_id="stage-1",
            current_step=leftover_step,
            stages=[
                PlanStage(
                    id="stage-1",
                    title=leftover_stage,
                    goal="Keep one check",
                    outcomes=["pass"],
                    status="active",
                ),
                PlanStage(
                    id="stage-2",
                    title=leftover_title,
                    goal="Keep the leftover title live",
                    outcomes=["pass"],
                    status="pending",
                ),
            ],
        ),
        None,
        passed=True,
        runtime=still_on_plan,
        existing=still_on_plan,
    )
    assert still_success is not None
    assert leftover_title in still_success.why_now
    leftover_replan = planner.replan_after_failure(
        LearningPlan(
            id=leftover_plan_id,
            title=leftover_title,
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
        ),
        None,
        blocker="The expiry check still fails.",
        runtime=advanced,
        existing=advanced,
    )
    assert leftover_replan is not None
    assert leftover_title not in leftover_replan.why_now
    assert leftover_stage not in leftover_replan.why_now
    assert leftover_step not in leftover_replan.why_now
    assert leftover_title not in leftover_replan.current_step
    assert leftover_stage not in leftover_replan.current_step
    assert leftover_step not in leftover_replan.current_step
    still_replan = planner.replan_after_failure(
        LearningPlan(
            id=leftover_plan_id,
            title=leftover_title,
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
        ),
        None,
        blocker="The expiry check still fails.",
        runtime=still_on_plan,
        existing=still_on_plan,
    )
    assert still_replan is not None
    assert leftover_stage in still_replan.why_now
    assert leftover_stage in still_replan.current_step


def test_leftover_formal_titles_do_not_live_in_plan_lane_or_update_heading() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
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
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    lane = live_plan_lane_copy(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        stage_title=leftover_stage,
    )
    heading = live_plan_update_heading(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        fallback="Plan update",
    )
    assert leftover_title not in lane["en"]
    assert leftover_title not in lane["zh"]
    assert leftover_title not in heading
    assert leftover_stage not in lane["en"]
    assert leftover_stage not in lane["zh"]
    assert leftover_stage not in heading
    assert leftover_step not in lane["en"]
    assert leftover_step not in lane["zh"]
    assert leftover_step not in heading
    assert leftover_summary not in lane["en"]
    assert leftover_summary not in heading
    assert leftover_plan_id not in lane["en"]
    assert leftover_plan_id not in heading
    assert recovered_step in lane["en"]
    assert recovered_step in lane["zh"]
    assert heading == recovered_step
    empty = live_plan_lane_copy(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        stage_title=leftover_stage,
    )
    empty_heading = live_plan_update_heading(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        fallback="Plan update",
    )
    assert leftover_title not in empty["en"]
    assert leftover_title not in empty["zh"]
    assert leftover_title not in empty_heading
    assert leftover_stage not in empty["en"]
    assert leftover_stage not in empty["zh"]
    assert leftover_stage not in empty_heading
    assert leftover_step not in empty["en"]
    assert leftover_step not in empty_heading
    assert leftover_summary not in empty["en"]
    assert leftover_plan_id not in empty["en"]
    assert empty["label"] == ""
    assert empty_heading == "Plan update"
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_lane = live_plan_lane_copy(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        stage_title=leftover_stage,
    )
    still_heading = live_plan_update_heading(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        fallback="Plan update",
    )
    assert leftover_stage in still_lane["en"]
    assert leftover_stage in still_lane["zh"]
    assert still_heading == leftover_title


def test_leftover_formal_task_title_does_not_live_in_heading_or_thin_slice() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_task = leftover_title
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
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    heading = live_task_heading(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
        fallback="Practice task",
    )
    thin = live_task_thin_slice_copy(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
    )
    picked = live_task_picked_copy(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
    )
    converted = live_task_converted_copy(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
    )
    training = live_training_lane_copy(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
        card_title=f"Practice: {leftover_task}",
    )
    live_copy = (
        heading,
        thin["en"],
        thin["zh"],
        picked["en"],
        picked["zh"],
        converted["en"],
        converted["zh"],
        training["en"],
        training["zh"],
    )
    for text in live_copy:
        assert leftover_task not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
    assert heading == recovered_step
    assert recovered_step in thin["en"]
    assert recovered_step in thin["zh"]
    assert recovered_step in picked["en"]
    assert recovered_step in converted["en"]
    assert recovered_step in training["en"]
    empty_runtime = {"current_step": "", "resume_state": "in_progress"}
    empty_heading = live_task_heading(
        plan=plan,
        runtime=empty_runtime,
        existing={"current_step": ""},
        task_title=leftover_task,
        fallback="Practice task",
    )
    empty_thin = live_task_thin_slice_copy(
        plan=plan,
        runtime=empty_runtime,
        existing={"current_step": ""},
        task_title=leftover_task,
    )
    empty_training = live_training_lane_copy(
        plan=plan,
        runtime=empty_runtime,
        existing={"current_step": ""},
        task_title=leftover_task,
        card_title=f"Practice: {leftover_task}",
    )
    assert leftover_task not in empty_heading
    assert leftover_task not in empty_thin["en"]
    assert leftover_task not in empty_thin["zh"]
    assert leftover_task not in empty_training["en"]
    assert leftover_step not in empty_heading
    assert leftover_step not in empty_thin["en"]
    assert leftover_summary not in empty_heading
    assert leftover_plan_id not in empty_heading
    assert empty_heading == "Practice task"
    assert empty_thin["label"] == ""
    assert empty_training["label"] == ""
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_heading = live_task_heading(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        task_title=leftover_task,
        fallback="Practice task",
    )
    still_thin = live_task_thin_slice_copy(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        task_title=leftover_task,
    )
    still_training = live_training_lane_copy(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        task_title=leftover_task,
        card_title=f"Practice: {leftover_task}",
    )
    assert still_heading == leftover_task
    assert leftover_task in still_thin["en"]
    assert leftover_task in still_thin["zh"]
    assert leftover_task in still_training["en"]
    still_on_live_task = {
        "current_step": leftover_task,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    live_task_heading_copy = live_task_heading(
        plan=plan,
        runtime=still_on_live_task,
        existing=still_on_live_task,
        task_title=leftover_task,
        fallback="Practice task",
    )
    live_task_thin = live_task_thin_slice_copy(
        plan=plan,
        runtime=still_on_live_task,
        existing=still_on_live_task,
        task_title=leftover_task,
    )
    assert live_task_heading_copy == leftover_task
    assert leftover_task in live_task_thin["en"]


def test_leftover_formal_task_title_does_not_live_in_artifact_focus_area() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_task = leftover_title
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
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    focus = live_task_focus_area(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
        fallback="implementation",
    )
    next_action = live_task_next_action(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        goal="",
        task_title=leftover_task,
    )
    leftover_goal_action = live_task_next_action(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        goal=leftover_task,
        task_title=leftover_task,
    )
    candidates = live_task_clean_step_candidates(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        next_step="",
        goal="",
        task_title=leftover_task,
    )
    leftover_goal_candidates = live_task_clean_step_candidates(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        next_step=leftover_step,
        goal=leftover_task,
        task_title=leftover_task,
    )
    assert focus == recovered_step
    assert leftover_task not in {focus, next_action, leftover_goal_action}
    assert leftover_stage not in {focus, next_action}
    assert leftover_step not in {focus, next_action}
    assert leftover_summary not in {focus, next_action}
    assert leftover_plan_id not in {focus, next_action}
    assert next_action == recovered_step
    assert leftover_goal_action == recovered_step
    assert leftover_task not in candidates
    assert leftover_task not in leftover_goal_candidates
    assert leftover_step not in leftover_goal_candidates
    assert leftover_goal_candidates == [recovered_step]
    assert recovered_step in candidates
    empty_runtime = {"current_step": "", "resume_state": "in_progress"}
    empty_focus = live_task_focus_area(
        plan=plan,
        runtime=empty_runtime,
        existing={"current_step": ""},
        task_title=leftover_task,
        fallback="implementation",
    )
    empty_action = live_task_next_action(
        plan=plan,
        runtime=empty_runtime,
        existing={"current_step": ""},
        goal=leftover_task,
        task_title=leftover_task,
    )
    empty_candidates = live_task_clean_step_candidates(
        plan=plan,
        runtime=empty_runtime,
        existing={"current_step": ""},
        next_step="",
        goal="",
        task_title=leftover_task,
    )
    assert leftover_task not in {empty_focus, empty_action}
    assert leftover_step not in {empty_focus, empty_action}
    assert leftover_task not in empty_candidates
    assert empty_focus == "implementation"
    assert empty_action == ""
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_focus = live_task_focus_area(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        task_title=leftover_task,
        fallback="implementation",
    )
    still_action = live_task_next_action(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        goal="",
        task_title=leftover_task,
    )
    still_candidates = live_task_clean_step_candidates(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        next_step="",
        goal="",
        task_title=leftover_task,
    )
    assert still_focus == leftover_task
    assert still_action == leftover_task
    assert leftover_task in still_candidates
    still_on_live_task = {
        "current_step": leftover_task,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    live_task_focus = live_task_focus_area(
        plan=plan,
        runtime=still_on_live_task,
        existing=still_on_live_task,
        task_title=leftover_task,
        fallback="implementation",
    )
    assert live_task_focus == leftover_task


def test_leftover_formal_task_title_does_not_live_in_suggested_action_reason() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_task = leftover_title
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
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    reason = live_task_suggested_reason(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        reason="",
        task_title=leftover_task,
    )
    leftover_reason = live_task_suggested_reason(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        reason=leftover_task,
        task_title=leftover_task,
    )
    assert reason == recovered_step
    assert leftover_reason == recovered_step
    assert leftover_task not in {reason, leftover_reason}
    assert leftover_stage not in {reason, leftover_reason}
    assert leftover_step not in {reason, leftover_reason}
    assert leftover_summary not in {reason, leftover_reason}
    assert leftover_plan_id not in {reason, leftover_reason}
    empty_reason = live_task_suggested_reason(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        reason=leftover_task,
        task_title=leftover_task,
    )
    assert leftover_task not in {empty_reason}
    assert leftover_step not in {empty_reason}
    assert leftover_summary not in {empty_reason}
    assert leftover_plan_id not in {empty_reason}
    assert empty_reason == ""
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_reason = live_task_suggested_reason(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        reason="",
        task_title=leftover_task,
    )
    assert still_reason == leftover_task
    still_on_live_task = {
        "current_step": leftover_task,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    live_task_reason = live_task_suggested_reason(
        plan=plan,
        runtime=still_on_live_task,
        existing=still_on_live_task,
        reason="",
        task_title=leftover_task,
    )
    assert live_task_reason == leftover_task


def test_leftover_formal_task_goal_does_not_live_in_suggested_action_title() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_task = leftover_title
    leftover_goal = "Write leftover auth check"
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
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    title = live_task_suggested_title(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        title=leftover_goal,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    leftover_step_title = live_task_suggested_title(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        title=leftover_step,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    fresh_title = live_task_suggested_title(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        title="Fix the expiry leak",
        goal=leftover_goal,
        task_title=leftover_task,
    )
    next_action = live_task_next_action(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        goal=leftover_goal,
        task_title=leftover_task,
        task_goal=leftover_goal,
    )
    assert title == recovered_step
    assert leftover_step_title == recovered_step
    assert fresh_title == "Fix the expiry leak"
    assert next_action == recovered_step
    assert leftover_goal not in {title, leftover_step_title, next_action}
    assert leftover_task not in {title, leftover_step_title, next_action}
    assert leftover_step not in {title, leftover_step_title, next_action}
    assert leftover_summary not in {title, leftover_step_title, next_action}
    assert leftover_plan_id not in {title, leftover_step_title, next_action}
    empty_title = live_task_suggested_title(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        title=leftover_goal,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    empty_fresh = live_task_suggested_title(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        title="Fix the expiry leak",
        goal=leftover_goal,
        task_title=leftover_task,
    )
    assert leftover_goal not in {empty_title}
    assert leftover_task not in {empty_title}
    assert leftover_step not in {empty_title}
    assert leftover_summary not in {empty_title}
    assert leftover_plan_id not in {empty_title}
    assert empty_title == ""
    assert empty_fresh == "Fix the expiry leak"
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_title = live_task_suggested_title(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        title=leftover_goal,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    still_action = live_task_next_action(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        goal=leftover_goal,
        task_title=leftover_task,
        task_goal=leftover_goal,
    )
    assert still_title == leftover_goal
    assert still_action == leftover_goal
    still_on_live_task = {
        "current_step": leftover_task,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    live_task_title = live_task_suggested_title(
        plan=plan,
        runtime=still_on_live_task,
        existing=still_on_live_task,
        title=leftover_goal,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    assert live_task_title == leftover_goal


def test_leftover_formal_task_goal_does_not_live_in_coaching_next_step() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_task = leftover_title
    leftover_goal = "Write leftover auth check"
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
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    next_step = live_coaching_next_step(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        next_step=leftover_goal,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    concepts = live_task_training_concepts(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        concepts=[leftover_task],
        task_title=leftover_task,
    )
    title_focus = live_task_focus_area(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
        fallback="evaluation",
    )
    assert next_step == recovered_step
    assert leftover_goal not in {next_step, title_focus}
    assert leftover_task not in {next_step, title_focus}
    assert leftover_step not in {next_step, title_focus}
    assert leftover_summary not in {next_step, title_focus}
    assert leftover_plan_id not in {next_step, title_focus}
    assert leftover_task not in concepts
    assert leftover_goal not in concepts
    assert leftover_step not in concepts
    assert leftover_summary not in concepts
    assert leftover_plan_id not in concepts
    assert concepts == [recovered_step]
    assert title_focus == recovered_step
    empty_step = live_coaching_next_step(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        next_step=leftover_goal,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    empty_concepts = live_task_training_concepts(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        concepts=[leftover_task],
        task_title=leftover_task,
    )
    empty_focus = live_task_focus_area(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        task_title=leftover_task,
        fallback="evaluation",
    )
    assert leftover_goal not in {empty_step, empty_focus}
    assert leftover_task not in {empty_step, empty_focus}
    assert leftover_step not in {empty_step, empty_focus}
    assert leftover_task not in empty_concepts
    assert leftover_goal not in empty_concepts
    assert empty_step == ""
    assert empty_concepts == []
    assert empty_focus == "evaluation"
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_step = live_coaching_next_step(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        next_step=leftover_goal,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    still_concepts = live_task_training_concepts(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        concepts=[leftover_task],
        task_title=leftover_task,
    )
    still_focus = live_task_focus_area(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        task_title=leftover_task,
        fallback="evaluation",
    )
    assert still_step == leftover_goal
    assert leftover_task in still_concepts
    assert still_focus == leftover_task
    still_on_live_task = {
        "current_step": leftover_task,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    live_task_step = live_coaching_next_step(
        plan=plan,
        runtime=still_on_live_task,
        existing=still_on_live_task,
        next_step=leftover_goal,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    assert live_task_step == leftover_goal


def test_leftover_formal_task_goal_does_not_live_in_language_detection_hint() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_task = leftover_title
    leftover_goal = "继续沿用旧的正式目标"
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
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    hint = live_language_detection_hint(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        hint=leftover_goal,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    assert hint == recovered_step
    assert leftover_goal not in {hint}
    assert leftover_task not in {hint}
    assert leftover_step not in {hint}
    assert leftover_summary not in {hint}
    assert leftover_plan_id not in {hint}
    empty_hint = live_language_detection_hint(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        hint=leftover_goal,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    assert leftover_goal not in {empty_hint}
    assert leftover_task not in {empty_hint}
    assert leftover_step not in {empty_hint}
    assert leftover_summary not in {empty_hint}
    assert leftover_plan_id not in {empty_hint}
    assert empty_hint == ""
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_hint = live_language_detection_hint(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        hint=leftover_goal,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    assert still_hint == leftover_goal
    still_on_live_task = {
        "current_step": leftover_task,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    live_task_hint = live_language_detection_hint(
        plan=plan,
        runtime=still_on_live_task,
        existing=still_on_live_task,
        hint=leftover_goal,
        goal=leftover_goal,
        task_title=leftover_task,
    )
    assert live_task_hint == leftover_goal


def test_leftover_formal_card_title_does_not_live_in_training_card_chrome() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_task = leftover_title
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
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    why = live_training_why_this_card(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
        card_title=leftover_card,
        why_now=leftover_title,
        kind="current",
    )
    next_why = live_training_why_this_card(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
        card_title=leftover_card,
        why_now="",
        kind="next",
    )
    open_copy = live_training_open_copy(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
        card_title=leftover_card,
        next_step="",
        primer_required=False,
    )
    live_copy = (why, next_why, open_copy["en_complete"], open_copy["zh_complete"], open_copy["en_summary"], open_copy["zh_summary"])
    for text in live_copy:
        assert leftover_title not in text
        assert leftover_card not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
    assert recovered_step in why
    assert recovered_step in next_why
    assert recovered_step in open_copy["en_complete"]
    empty = live_training_open_copy(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        task_title=leftover_task,
        card_title=leftover_card,
        next_step="",
        primer_required=False,
    )
    empty_why = live_training_why_this_card(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        task_title=leftover_task,
        card_title=leftover_card,
        why_now=leftover_title,
        kind="current",
    )
    assert leftover_title not in empty["en_complete"]
    assert leftover_card not in empty["en_complete"]
    assert leftover_title not in empty_why
    assert leftover_card not in empty_why
    assert "Open Training and complete the current card." == empty["en_complete"]
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_why = live_training_why_this_card(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        task_title=leftover_task,
        card_title=leftover_card,
        why_now=leftover_title,
        kind="current",
    )
    still_open = live_training_open_copy(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        task_title=leftover_task,
        card_title=leftover_card,
        next_step="",
        primer_required=False,
    )
    assert leftover_title in still_why
    assert leftover_card in still_open["en_complete"]
    assert leftover_card in still_open["zh_complete"]


def test_leftover_formal_card_title_does_not_live_in_tool_why_this_card() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_task = leftover_title
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
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    leftover_why = f"{leftover_card} is the current training card."
    why = live_training_why_this_card(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
        card_title=leftover_card,
        why_now=leftover_why,
        kind="current",
    )
    empty_why = live_training_why_this_card(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
        card_title=leftover_card,
        why_now="",
        kind="current",
    )
    for text in (why, empty_why):
        assert leftover_title not in text
        assert leftover_card not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
        assert recovered_step in text
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_why = live_training_why_this_card(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        task_title=leftover_task,
        card_title=leftover_card,
        why_now=leftover_why,
        kind="current",
    )
    still_empty = live_training_why_this_card(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        task_title=leftover_task,
        card_title=leftover_card,
        why_now="",
        kind="current",
    )
    assert leftover_card in still_why
    assert leftover_card in still_empty


def test_leftover_formal_card_title_does_not_live_in_persist_chrome() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_task = leftover_title
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
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    leftover_why = f"{leftover_card} passed current-file verification."
    chrome = live_training_persist_chrome(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
        card_title=leftover_card,
        summary="",
    )
    leftover_summary_chrome = live_training_persist_chrome(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
        card_title=leftover_card,
        summary=leftover_why,
    )
    empty_chrome = live_training_persist_chrome(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        task_title=leftover_task,
        card_title=leftover_card,
        summary=leftover_why,
    )
    for text in (
        chrome["selected_card_title"],
        chrome["verification_summary"],
        leftover_summary_chrome["selected_card_title"],
        leftover_summary_chrome["verification_summary"],
        empty_chrome["selected_card_title"],
        empty_chrome["verification_summary"],
    ):
        assert leftover_title not in text
        assert leftover_card not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
    assert chrome["selected_card_title"] == recovered_step
    assert recovered_step in chrome["verification_summary"]
    assert leftover_summary_chrome["verification_summary"] == f"{recovered_step} passed current-file verification."
    assert empty_chrome["selected_card_title"] == ""
    assert empty_chrome["verification_summary"] == "Current-file verification passed."
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_chrome = live_training_persist_chrome(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        task_title=leftover_task,
        card_title=leftover_card,
        summary="",
    )
    assert leftover_card in still_chrome["selected_card_title"]
    assert leftover_card in still_chrome["verification_summary"]


def test_leftover_formal_card_title_does_not_live_in_current_task_focus_fallback() -> None:
    leftover_title = "Keep the current stage"
    leftover_stage = "Auth"
    leftover_step = "Keep one auth check"
    leftover_summary = "Leftover formal summary of the old stage path"
    leftover_plan_id = "plan-formal-old"
    leftover_task = leftover_title
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
    advanced = {
        "current_step": recovered_step,
        "why_now": "Expired tokens still leak.",
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    focus = live_training_focus_fallback(
        plan=plan,
        runtime=advanced,
        existing=advanced,
        task_title=leftover_task,
        card_title=leftover_card,
        fallback="practice verification",
    )
    empty_focus = live_training_focus_fallback(
        plan=plan,
        runtime={"current_step": "", "resume_state": "in_progress"},
        existing={"current_step": ""},
        task_title=leftover_task,
        card_title=leftover_card,
        fallback="practice verification",
    )
    live_request = live_training_focus_fallback(
        plan=None,
        runtime={},
        existing={},
        task_title="",
        card_title="Refactor the async boundary",
        fallback="practice verification",
    )
    for text in (focus, empty_focus):
        assert leftover_title not in text
        assert leftover_card not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
    assert focus == recovered_step
    assert empty_focus == "practice verification"
    assert live_request == "Refactor the async boundary"
    still_on_plan = {
        "current_step": leftover_step,
        "plan_id": leftover_plan_id,
        "resume_state": "in_progress",
        "workspace_id": "workspace-plan",
    }
    still_focus = live_training_focus_fallback(
        plan=plan,
        runtime=still_on_plan,
        existing=still_on_plan,
        task_title=leftover_task,
        card_title=leftover_card,
        fallback="practice verification",
    )
    assert leftover_card in still_focus or leftover_step in still_focus or leftover_title in still_focus


def test_leftover_formal_card_title_does_not_live_in_memory_persist_chrome(tmp_path: Path) -> None:
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
    workspace_id = "workspace-persist-leftover-card"
    repository = TrainerRepository(tmp_path / "trainer-persist-leftover-card.db")
    service = MemoryService(repository)
    repository.save_plan(workspace_id, plan)
    service.persist_plan_runtime_recovery(
        workspace_id,
        plan=plan,
        plan_runtime={
            "current_step": recovered_step,
            "why_now": "Expired tokens still leak.",
            "resume_state": "in_progress",
            "workspace_id": workspace_id,
        },
    )
    service.upsert_card(
        workspace_id,
        TrainingCardCandidateSnapshot(
            card_id="card-leftover-persist",
            card_type="practice",
            title=leftover_card,
            status="active",
            target_skill=recovered_step,
            focus_area=recovered_step,
        ),
    )
    workspace = service.record_training_practice_evaluation_result(
        workspace_id=workspace_id,
        card_id="card-leftover-persist",
        card_title=leftover_card,
        passed=True,
        summary=f"{leftover_card} passed current-file verification.",
        next_step="Return to Coach.",
        focus_area=recovered_step,
        evidence_source="learner_return",
    )
    persist_copy = (
        str(workspace.get("selected_card_title") or ""),
        str((workspace.get("latest_training_next_hop") or {}).get("card_title") or ""),
        str((workspace.get("latest_training_handoff") or {}).get("card_title") or ""),
    )
    for text in persist_copy:
        assert leftover_title not in text
        assert leftover_card not in text
        assert leftover_stage not in text
        assert leftover_step not in text
        assert leftover_summary not in text
        assert leftover_plan_id not in text
        assert recovered_step in text

    still_workspace = "workspace-persist-still-on-plan-card"
    repository.save_plan(still_workspace, plan)
    service.persist_plan_runtime_recovery(
        still_workspace,
        plan=plan,
        plan_runtime={
            "current_step": leftover_step,
            "plan_id": leftover_plan_id,
            "resume_state": "in_progress",
            "workspace_id": still_workspace,
        },
    )
    service.upsert_card(
        still_workspace,
        TrainingCardCandidateSnapshot(
            card_id="card-still-persist",
            card_type="practice",
            title=leftover_card,
            status="active",
            target_skill=leftover_title,
            focus_area=leftover_title,
        ),
    )
    still = service.record_training_practice_evaluation_result(
        workspace_id=still_workspace,
        card_id="card-still-persist",
        card_title=leftover_card,
        passed=True,
        summary=f"{leftover_card} passed current-file verification.",
        next_step="Return to Coach.",
        focus_area=leftover_title,
        evidence_source="learner_return",
    )
    still_title = str(still.get("selected_card_title") or "")
    assert leftover_card in still_title or leftover_title in still_title


def test_leftover_formal_card_title_does_not_live_in_tool_persistence_context(tmp_path: Path) -> None:
    from app.llm.tools import ToolContext, _training_card_context_for_persistence

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
    workspace_id = "workspace-tool-persist-leftover-card"
    repository = TrainerRepository(tmp_path / "trainer-tool-persist-leftover-card.db")
    service = MemoryService(repository)
    repository.save_plan(workspace_id, plan)
    service.persist_plan_runtime_recovery(
        workspace_id,
        plan=plan,
        plan_runtime={
            "current_step": recovered_step,
            "why_now": "Expired tokens still leak.",
            "resume_state": "in_progress",
            "workspace_id": workspace_id,
        },
    )
    runtime = SimpleNamespace(memory_service=service, repository=repository)
    context = ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id="session-tool-persist-leftover-card",
    )
    leftover_args = {
        "training_card_id": "card-leftover-persist",
        "training_card_title": leftover_card,
        "focus_area": leftover_card,
    }
    card_id, card_title, focus_area = _training_card_context_for_persistence(
        context,
        args=leftover_args,
        current_file={},
    )
    selected_runtime = SimpleNamespace(
        memory_service=SimpleNamespace(
            _leftover_persist_context=service._leftover_persist_context,
            snapshot=lambda _workspace_id: SimpleNamespace(
                active_training_card_routing=SimpleNamespace(
                    selected_card_id="card-leftover-selected",
                    selected_card=SimpleNamespace(
                        card_id="card-leftover-selected",
                        title=leftover_card,
                        focus_area=leftover_card,
                        target_skill=leftover_card,
                    ),
                )
            ),
        ),
        repository=repository,
    )
    selected_id, selected_title, selected_focus = _training_card_context_for_persistence(
        ToolContext(
            runtime=selected_runtime,
            workspace_id=workspace_id,
            session_id="session-tool-persist-selected-card",
        ),
        args={},
        current_file={},
    )
    empty_runtime = SimpleNamespace(
        memory_service=SimpleNamespace(
            _leftover_persist_context=lambda _workspace_id: (
                plan,
                {"current_step": "", "resume_state": "in_progress"},
                leftover_title,
            ),
            snapshot=lambda _workspace_id: SimpleNamespace(active_training_card_routing=None),
        ),
        repository=repository,
    )
    _, empty_title, empty_focus = _training_card_context_for_persistence(
        ToolContext(
            runtime=empty_runtime,
            workspace_id="workspace-tool-persist-empty-step",
            session_id="session-tool-persist-empty-step",
        ),
        args=leftover_args,
        current_file={"training_card_title": leftover_card},
    )
    for label, text in (
        ("args_title", card_title),
        ("args_focus", focus_area),
        ("selected_title", selected_title),
        ("selected_focus", selected_focus),
        ("empty_title", empty_title),
        ("empty_focus", empty_focus),
    ):
        assert leftover_title not in text, label
        assert leftover_card not in text, label
        assert leftover_stage not in text, label
        assert leftover_step not in text, label
        assert leftover_summary not in text, label
        assert leftover_plan_id not in text, label
    assert card_id == "card-leftover-persist"
    assert card_title == recovered_step
    assert focus_area == recovered_step
    assert selected_id == "card-leftover-selected"
    assert selected_title == recovered_step
    assert selected_focus == recovered_step
    assert empty_title == ""
    assert empty_focus == ""

    still_workspace = "workspace-tool-persist-still-on-plan-card"
    repository.save_plan(still_workspace, plan)
    service.persist_plan_runtime_recovery(
        still_workspace,
        plan=plan,
        plan_runtime={
            "current_step": leftover_step,
            "plan_id": leftover_plan_id,
            "resume_state": "in_progress",
            "workspace_id": still_workspace,
        },
    )
    _, still_title, still_focus = _training_card_context_for_persistence(
        ToolContext(
            runtime=runtime,
            workspace_id=still_workspace,
            session_id="session-tool-persist-still-on-plan-card",
        ),
        args=leftover_args,
        current_file={},
    )
    assert leftover_card in still_title
    assert leftover_card in still_focus

    live_workspace = "workspace-tool-persist-live-card"
    _, live_title, live_focus = _training_card_context_for_persistence(
        ToolContext(
            runtime=runtime,
            workspace_id=live_workspace,
            session_id="session-tool-persist-live-card",
        ),
        args={
            "training_card_id": "card-live",
            "training_card_title": "Refactor the async boundary",
            "focus_area": "async boundary",
        },
        current_file={},
    )
    assert live_title == "Refactor the async boundary"
    assert live_focus == "async boundary"


def test_adopt_without_structured_next_does_not_invent_a_step() -> None:
    waiting = {
        "workspace_id": "workspace-plan",
        "current_step": "Keep one auth check",
        "why_now": "Expired tokens still leak the session.",
        "next_after_current": "",
        "resume_state": "waiting",
    }
    evidence = {"id": "ev-auth-pass-2", "adopted": True, "outcome": "pass", "verified": True}
    assert (
        build_plan_runtime_advance_after_adopt(
            existing=waiting,
            evidence=evidence,
            request_id="ev-auth-pass-2",
            workspace_id="workspace-plan",
        )
        is None
    )


def test_failed_or_unverified_adopt_does_not_leave_waiting() -> None:
    waiting = {
        "workspace_id": "workspace-plan",
        "current_step": "Keep one auth check",
        "next_after_current": "Add a token expiry test",
        "resume_state": "waiting",
    }
    assert verified_adopt_allows_runtime_advance(
        {"adopted": True, "outcome": "pass", "verified": False}
    ) is False
    assert verified_adopt_allows_runtime_advance(
        {"adopted": True, "outcome": "fail", "verified": True}
    ) is False
    assert verified_adopt_allows_runtime_advance(
        {"adopted": True, "outcome": "pass", "verified": True, "rejected_at": "2026-08-25T00:00:00Z"}
    ) is False
    assert (
        build_plan_runtime_advance_after_adopt(
            existing=waiting,
            evidence={"id": "ev-fail", "adopted": True, "outcome": "fail", "verified": True},
            request_id="ev-fail",
            workspace_id="workspace-plan",
        )
        is None
    )
    assert (
        build_plan_runtime_advance_after_adopt(
            existing=waiting,
            evidence={"id": "ev-unverified", "adopted": True, "outcome": "pass", "verified": False},
            request_id="ev-unverified",
            workspace_id="workspace-plan",
        )
        is None
    )
    assert (
        build_plan_runtime_advance_after_adopt(
            existing={**waiting, "resume_state": "in_progress"},
            evidence={"id": "ev-not-waiting", "adopted": True, "outcome": "pass", "verified": True},
            request_id="ev-not-waiting",
            workspace_id="workspace-plan",
        )
        is None
    )
    advanced = build_plan_runtime_advance_after_adopt(
        existing={**waiting, "resume_state": "in_progress"},
        evidence={
            "id": "ev-return",
            "adopted": True,
            "outcome": "pass",
            "verified": True,
            "source": "training_handoff_return",
        },
        request_id="ev-return",
        workspace_id="workspace-plan",
    )
    assert advanced is not None
    assert advanced["current_step"] == "Add a token expiry test"
    assert advanced["resume_state"] == "in_progress"
    assert advanced.get("plan_id") in {None, ""}
    assert (
        build_plan_runtime_advance_after_adopt(
            existing=waiting,
            evidence={"id": "ev-other-ws", "adopted": True, "outcome": "pass", "verified": True},
            request_id="ev-other-ws",
            workspace_id="workspace-other",
        )
        is None
    )


def test_adopt_return_evidence_advances_in_progress_without_clobbering_leftover_plan(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    workspace_id = "workspace-plan-return-adopt"
    leftover = LearningPlan(
        id="plan-formal-old",
        title="Keep the current stage",
        current_step="Keep one auth check",
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
    service.repository.save_plan(workspace_id, leftover)
    persisted = service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Add a token expiry test",
            "next_after_current": "Review the refresh path",
            "why_now": "Expired tokens still leak.",
            "resume_state": "in_progress",
            "plan_id": "",
        },
        request_id="return-adopt-1",
    )
    assert persisted is not None
    service.upsert_card(
        workspace_id,
        TrainingCardCandidateSnapshot(
            card_id="card-leftover-after-adopt",
            card_type="practice",
            title="Practice: Keep the current stage",
            status="implemented",
            target_skill="Keep the current stage",
            focus_area="Keep the current stage",
        ),
    )
    structured = service._structured_for(workspace_id)
    structured.update_workspace(
        selected_card_title="Practice: Keep the current stage",
        latest_training_handoff={"card_title": "Practice: Keep the current stage"},
        latest_training_next_hop={
            "title": "Practice: Keep the current stage",
            "card_title": "Practice: Keep the current stage",
            "why_now": "Keep the leftover why",
        },
    )
    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(
            summary="Return checks passed",
            source="training_handoff_return",
            outcome="pass",
            concepts=["Add a token expiry test"],
        ),
        verified=True,
        verification_source="ide_current_file",
    )
    response = service.adopt_evidence(workspace_id, item.id)
    assert response.plan_updated is False
    stored = service.repository.get_latest_plan(workspace_id)
    assert stored is not None
    assert stored.id == "plan-formal-old"
    assert stored.title == "Keep the current stage"
    assert stored.current_step == "Keep one auth check"
    advanced = service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
    assert advanced["current_step"] == "Review the refresh path"
    assert advanced["resume_state"] == "in_progress"
    assert advanced.get("plan_id") in {None, ""}
    assert advanced.get("why_now") != "Keep the leftover why"
    workspace = service._structured_for(workspace_id)._workspace
    chrome = (
        str(workspace.get("selected_card_title") or ""),
        str((workspace.get("latest_training_handoff") or {}).get("card_title") or ""),
        str((workspace.get("latest_training_next_hop") or {}).get("title") or ""),
        str((workspace.get("latest_training_next_hop") or {}).get("card_title") or ""),
    )
    for text in chrome:
        assert text == "Review the refresh path"
        assert "Keep the current stage" not in text
        assert "Keep one auth check" not in text
    leftover_plan, leftover_runtime, leftover_task = service._leftover_persist_context(workspace_id)
    mint = live_training_mint_anchors(
        plan=leftover_plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
        task_title=leftover_task,
        why_now="Keep the leftover why",
        target_skill="Keep the current stage",
        focus_area="Keep the current stage",
    )
    assert mint["focus_area"] == "Review the refresh path"
    assert mint["target_skill"] == ""
    assert mint["why_now"] != "Keep the leftover why"
    leftover_labels = leftover_formal_training_labels(
        plan=leftover_plan,
        task_title=leftover_task,
        live_plan=False,
        live_task=False,
    )
    minted = apply_live_training_mint_to_card(
        TrainingCardCandidateSnapshot(
            card_id="card-mint-after-adopt",
            card_type="practice",
            title="Practice: Keep the current stage",
            status="candidate",
            target_skill="Keep the current stage",
            focus_area="Keep the current stage",
            why_now="Keep the leftover why",
        ),
        anchors=mint,
        leftover_labels=leftover_labels,
        recovered_step="Review the refresh path",
    )
    assert minted.title == "Review the refresh path"
    assert minted.target_skill == ""
    assert minted.focus_area == "Review the refresh path"
    orientation = build_coach_orientation_from_snapshot(
        WorkbenchSnapshot(
            sidecar_status="ready",
            provider=ProviderConfig(
                name="minimax",
                baseUrl="http://example.test",
                apiKeyRef="secret-ref",
                model="MiniMax-M2.7",
            ),
            plan=stored,
            plan_runtime_status={
                "recovered": True,
                "current_step": advanced["current_step"],
                "plan_id": advanced.get("plan_id") or "",
                "why_now": advanced.get("why_now") or "",
            },
            memory=MemorySnapshot(workspace=dict(workspace)),
        ),
        response_language="en-US",
    )
    assert orientation["object_label"] == "Review the refresh path"
    assert "Keep the current stage" not in orientation["object_label"]
    assert service.repository.get_latest_plan(workspace_id).id == "plan-formal-old"
    global_memory = service.global_memory()
    assert "Keep the current stage" not in global_memory.capability_profile
    assert all("error handling" not in record.concepts for record in global_memory.growth_history)


def test_adopt_without_recovered_next_does_not_fill_leftover_training_title(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    workspace_id = "workspace-plan-return-empty-next"
    leftover = LearningPlan(
        id="plan-formal-empty-next",
        title="Keep the current stage",
        current_step="Keep one auth check",
        stages=[
            PlanStage(id="stage-1", title="Auth", goal="Keep one check", outcomes=["pass"], status="active")
        ],
    )
    service.repository.save_plan(workspace_id, leftover)
    persisted = service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "",
            "next_after_current": "",
            "resume_state": "in_progress",
            "plan_id": "",
        },
        request_id="return-empty-next-1",
    )
    assert persisted is not None
    assert not str(persisted.get("current_step") or "").strip()
    structured = service._structured_for(workspace_id)
    structured.update_workspace(
        selected_card_title="Practice: Keep the current stage",
        latest_training_handoff={"card_title": "Practice: Keep the current stage"},
        latest_training_next_hop={
            "title": "Practice: Keep the current stage",
            "card_title": "Practice: Keep the current stage",
        },
    )
    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(
            summary="Return checks passed",
            source="training_handoff_return",
            outcome="pass",
            concepts=["error handling"],
        ),
        verified=True,
        verification_source="ide_current_file",
    )
    service.adopt_evidence(workspace_id, item.id)
    workspace = service._structured_for(workspace_id)._workspace
    assert workspace.get("selected_card_title") in {None, ""}
    assert (workspace.get("latest_training_handoff") or {}).get("card_title") in {None, ""}
    assert (workspace.get("latest_training_next_hop") or {}).get("title") in {None, ""}
    stored = service.repository.get_latest_plan(workspace_id)
    assert stored is not None
    assert stored.id == "plan-formal-empty-next"
    assert stored.title == "Keep the current stage"


def test_adopt_still_on_plan_keeps_formal_training_identity(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    workspace_id = "workspace-plan-return-still"
    leftover = LearningPlan(
        id="plan-formal-still",
        title="Keep the current stage",
        current_step="Keep one auth check",
        stages=[
            PlanStage(id="stage-1", title="Auth", goal="Keep one check", outcomes=["pass"], status="active")
        ],
    )
    service.repository.save_plan(workspace_id, leftover)
    service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Keep one auth check",
            "next_after_current": "Add a token expiry test",
            "plan_id": leftover.id,
            "resume_state": "in_progress",
        },
        request_id="return-still-1",
    )
    structured = service._structured_for(workspace_id)
    structured.update_workspace(
        selected_card_title="Practice: Keep the current stage",
        latest_training_handoff={"card_title": "Practice: Keep the current stage"},
        latest_training_next_hop={
            "title": "Practice: Keep the current stage",
            "card_title": "Practice: Keep the current stage",
        },
    )
    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(
            summary="Return checks passed",
            source="training_handoff_return",
            outcome="pass",
            concepts=["Keep one auth check"],
        ),
        verified=True,
        verification_source="ide_current_file",
    )
    before = live_training_persist_chrome(
        plan=leftover,
        runtime={
            "current_step": "Keep one auth check",
            "plan_id": leftover.id,
            "resume_state": "in_progress",
            "workspace_id": workspace_id,
        },
        existing={
            "current_step": "Keep one auth check",
            "plan_id": leftover.id,
            "resume_state": "in_progress",
            "workspace_id": workspace_id,
        },
        card_title="Practice: Keep the current stage",
    )
    assert before["selected_card_title"] == "Practice: Keep the current stage"
    service.adopt_evidence(workspace_id, item.id)
    workspace = service._structured_for(workspace_id)._workspace
    assert workspace.get("selected_card_title") == "Add a token expiry test"
    stored = service.repository.get_latest_plan(workspace_id)
    assert stored is not None
    assert stored.id == "plan-formal-still"
    assert stored.title == "Keep the current stage"


def test_adopt_evidence_advances_waiting_runtime_without_inventing_a_plan(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    workspace_id = "workspace-plan-adopt-advance"
    persisted = service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Keep one auth check",
            "why_now": "Expired tokens still leak the session.",
            "next_after_current": "Add a token expiry test",
            "verify_method": ["Run the focused auth check"],
            "resume_state": "waiting",
        },
        request_id="plan-waiting-adopt-1",
    )
    assert persisted is not None
    assert service.repository.get_latest_plan(workspace_id) is None
    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(summary="Auth check passed", outcome="pass"),
        verified=True,
        verification_source="focused_auth_check",
    )
    response = service.adopt_evidence(workspace_id, item.id)
    assert response.plan_updated is False
    assert service.repository.get_latest_plan(workspace_id) is None
    advanced = service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
    assert advanced["resume_state"] == "in_progress"
    assert advanced["current_step"] == "Add a token expiry test"
    assert advanced.get("next_after_current") in {None, ""}
    assert advanced["verify_method"] == []
    assert advanced.get("why_now") in {None, ""}
    assert advanced.get("why_now") != "Expired tokens still leak the session."
    assert advanced.get("blocked_reason") in {None, ""}
    assert advanced.get("plan_id") in {None, ""}


def test_adopt_evidence_without_next_or_failed_verify_stays_waiting(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    empty_next_ws = "workspace-plan-adopt-empty-next"
    failed_ws = "workspace-plan-adopt-failed"
    service.persist_plan_runtime_recovery(
        empty_next_ws,
        plan_runtime={
            "current_step": "Keep one auth check",
            "why_now": "Expired tokens still leak the session.",
            "resume_state": "waiting",
        },
        request_id="plan-waiting-empty-1",
    )
    empty_item = service.enqueue_evidence(
        empty_next_ws,
        EvidenceItem(summary="Auth check passed", outcome="pass"),
        verified=True,
        verification_source="focused_auth_check",
    )
    empty_response = service.adopt_evidence(empty_next_ws, empty_item.id)
    assert empty_response.evidence.adopted is True
    empty_runtime = service.recover_workspace_facts(empty_next_ws)[PLAN_RUNTIME_KEY]
    assert empty_runtime["resume_state"] == "waiting"
    assert empty_runtime["current_step"] == "Keep one auth check"
    assert empty_runtime.get("next_after_current") in {None, ""}
    assert service.repository.get_latest_plan(empty_next_ws) is None

    service.persist_plan_runtime_recovery(
        failed_ws,
        plan_runtime={
            "current_step": "Keep one auth check",
            "next_after_current": "Add a token expiry test",
            "resume_state": "waiting",
        },
        request_id="plan-waiting-fail-1",
    )
    failed_item = service.enqueue_evidence(
        failed_ws,
        EvidenceItem(summary="Auth check failed", outcome="fail"),
        verified=True,
        verification_source="focused_auth_check",
    )
    failed_response = service.adopt_evidence(failed_ws, failed_item.id)
    assert failed_response.evidence.adopted is True
    failed_runtime = service.recover_workspace_facts(failed_ws)[PLAN_RUNTIME_KEY]
    assert failed_runtime["resume_state"] == "waiting"
    assert failed_runtime["current_step"] == "Keep one auth check"
    assert failed_runtime["next_after_current"] == "Add a token expiry test"
    assert service.repository.get_latest_plan(failed_ws) is None


def test_reject_evidence_does_not_advance_waiting_runtime(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    workspace_id = "workspace-plan-adopt-reject"
    service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Keep one auth check",
            "next_after_current": "Add a token expiry test",
            "resume_state": "waiting",
        },
        request_id="plan-waiting-reject-1",
    )
    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(
            summary="Auth check passed",
            outcome="pass",
            concepts=["Keep one auth check"],
        ),
        verified=True,
        verification_source="focused_auth_check",
    )
    assert service.evidence_queue(workspace_id).pending[0].id == item.id
    service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Keep one auth check",
            "next_after_current": "Add a token expiry test",
            "resume_state": "waiting",
        },
        evidence_binding=item.id,
        request_id="plan-waiting-reject-1",
    )
    assert service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]["evidence_binding"] == item.id
    rejected = service.reject_evidence(workspace_id, item.id, "Not enough proof")
    assert rejected.rejected_at
    queue = service.evidence_queue(workspace_id)
    assert queue.pending == []
    assert any(entry.id == item.id for entry in queue.rejected)
    runtime = service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
    assert runtime["resume_state"] == "waiting"
    assert runtime["current_step"] == "Keep one auth check"
    assert runtime["next_after_current"] == "Add a token expiry test"
    assert runtime.get("evidence_binding") in {None, ""}


def test_defer_evidence_does_not_advance_waiting_runtime(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    workspace_id = "workspace-plan-adopt-defer"
    service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Keep one auth check",
            "next_after_current": "Add a token expiry test",
            "resume_state": "waiting",
        },
        request_id="plan-waiting-defer-1",
    )
    item = service.enqueue_evidence(
        workspace_id,
        EvidenceItem(
            summary="Auth check passed",
            outcome="pass",
            concepts=["Keep one auth check"],
        ),
        verified=True,
        verification_source="focused_auth_check",
    )
    assert service.evidence_queue(workspace_id).pending[0].id == item.id
    service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Keep one auth check",
            "next_after_current": "Add a token expiry test",
            "resume_state": "waiting",
        },
        evidence_binding=item.id,
        request_id="plan-waiting-defer-1",
    )
    assert service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]["evidence_binding"] == item.id
    deferred = service.defer_evidence(workspace_id, item.id, "Need a tighter check")
    assert deferred.deferred_at
    assert not deferred.adopted
    queue = service.evidence_queue(workspace_id)
    assert queue.pending == []
    assert any(entry.id == item.id for entry in queue.deferred)
    assert all(entry.id != item.id for entry in queue.adopted)
    runtime = service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
    assert runtime["resume_state"] == "waiting"
    assert runtime["current_step"] == "Keep one auth check"
    assert runtime["next_after_current"] == "Add a token expiry test"
    assert runtime.get("evidence_binding") in {None, ""}
    assert service.repository.get_latest_plan(workspace_id) is None


def _waiting_resume_accepted() -> dict:
    return {
        "action": "continue_step",
        "recovered": True,
        "current_step": "Keep one auth check",
        "why_now": "Expired tokens still leak the session.",
        "formal_plan_mutation": False,
    }


def test_structured_waiting_finish_enqueues_one_verify_evidence(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    workspace_id = "workspace-plan-waiting-enqueue"
    service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Keep one auth check",
            "why_now": "Expired tokens still leak the session.",
            "next_after_current": "Add a token expiry test",
        },
        request_id="plan-waiting-seed-1",
    )
    assert service.evidence_queue(workspace_id).pending == []
    stamped = service.persist_plan_runtime_resume(
        workspace_id,
        accepted=_waiting_resume_accepted(),
        request_id="plan-waiting-enqueue-1",
        reply_facts={
            "current_step": "Keep one auth check",
            "why_now": "Expired tokens still leak the session.",
            "next_after_current": "Add a token expiry test",
            "verify_method": ["Run the focused auth check"],
            "resume_state": "waiting",
        },
    )
    assert stamped is not None
    assert stamped["resume_state"] == "waiting"
    pending = service.evidence_queue(workspace_id).pending
    assert len(pending) == 1
    item = pending[0]
    assert item.summary == "Run the focused auth check"
    assert item.source == WAITING_VERIFY_EVIDENCE_SOURCE
    assert item.concepts == ["Keep one auth check"]
    assert item.adopted is False
    assert item.verified is False
    assert item.outcome == "partial"
    assert stamped["evidence_binding"] == item.id
    assert service.repository.get_latest_plan(workspace_id) is None
    again = service.persist_plan_runtime_resume(
        workspace_id,
        accepted=_waiting_resume_accepted(),
        request_id="plan-waiting-enqueue-2",
        reply_facts={
            "current_step": "Keep one auth check",
            "verify_method": ["Run the focused auth check"],
            "resume_state": "waiting",
        },
    )
    assert again is not None
    assert len(service.evidence_queue(workspace_id).pending) == 1
    adopted = service.adopt_evidence(workspace_id, item.id)
    assert adopted.evidence.adopted is True
    assert adopted.evidence.verified is True
    assert adopted.evidence.outcome == "pass"
    advanced = service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
    assert advanced["resume_state"] == "in_progress"
    assert advanced["current_step"] == "Add a token expiry test"
    assert advanced.get("evidence_binding") in {None, ""}
    assert live_evidence_binding(
        binding=item.id,
        pending_ids=[entry.id for entry in service.evidence_queue(workspace_id).pending],
        recovered=True,
        current_step=advanced["current_step"],
    ) == ""
    assert service.repository.get_latest_plan(workspace_id) is None


def test_empty_or_unstructured_finish_does_not_invent_evidence(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    empty_ws = "workspace-plan-waiting-empty-verify"
    unfinished_ws = "workspace-plan-unfinished-no-evidence"
    other_ws = "workspace-plan-waiting-other"
    service.persist_plan_runtime_recovery(
        empty_ws,
        plan_runtime={"current_step": "Keep one auth check"},
        request_id="plan-empty-seed",
    )
    service.persist_plan_runtime_recovery(
        unfinished_ws,
        plan_runtime={"current_step": "Keep one auth check"},
        request_id="plan-unfinished-seed",
    )
    service.persist_plan_runtime_recovery(
        other_ws,
        plan_runtime={"current_step": "Keep the other login path"},
        request_id="plan-other-seed",
    )
    empty = service.persist_plan_runtime_resume(
        empty_ws,
        accepted=_waiting_resume_accepted(),
        request_id="plan-empty-verify-1",
        reply_facts={
            "current_step": "Keep one auth check",
            "resume_state": "waiting",
        },
    )
    assert empty is not None
    assert empty["resume_state"] == "waiting"
    assert service.evidence_queue(empty_ws).pending == []
    unfinished = service.persist_plan_runtime_resume(
        unfinished_ws,
        accepted=_waiting_resume_accepted(),
        request_id="plan-unfinished-1",
        reply_facts={
            "current_step": "Keep one auth check",
            "verify_method": ["Run the focused auth check"],
        },
    )
    assert unfinished is not None
    assert unfinished["resume_state"] == "in_progress"
    assert service.evidence_queue(unfinished_ws).pending == []
    service.persist_plan_runtime_resume(
        other_ws,
        accepted={
            **_waiting_resume_accepted(),
            "current_step": "Keep the other login path",
        },
        request_id="plan-other-waiting-1",
        reply_facts={
            "current_step": "Keep the other login path",
            "verify_method": ["Run the other check"],
            "resume_state": "waiting",
        },
    )
    assert len(service.evidence_queue(other_ws).pending) == 1
    assert service.evidence_queue(empty_ws).pending == []
    assert service.evidence_queue(unfinished_ws).pending == []


def test_waiting_composer_evidence_uses_submitted_text_only() -> None:
    waiting = {
        "workspace_id": "workspace-plan",
        "current_step": "Keep one auth check",
        "why_now": "Expired tokens still leak the session.",
        "next_after_current": "Add a token expiry test",
        "resume_state": "waiting",
    }
    payload = build_waiting_composer_evidence(
        runtime=waiting,
        workspace_id="workspace-plan",
        submitted_text="I ran the focused auth check on the login path.",
    )
    assert payload is not None
    assert payload["summary"] == "I ran the focused auth check on the login path."
    assert payload["source"] == WAITING_VERIFY_EVIDENCE_SOURCE
    assert payload["concepts"] == ["Keep one auth check"]
    assert payload["outcome"] == "partial"
    assert (
        build_waiting_composer_evidence(
            runtime=waiting,
            workspace_id="workspace-plan",
            submitted_text="   ",
        )
        is None
    )
    assert (
        build_waiting_composer_evidence(
            runtime={**waiting, "resume_state": "in_progress"},
            workspace_id="workspace-plan",
            submitted_text="I ran the focused auth check on the login path.",
        )
        is None
    )
    stamped = {
        **waiting,
        "verify_method": ["Run the focused auth check"],
    }
    replacement = build_waiting_composer_evidence(
        runtime=stamped,
        workspace_id="workspace-plan",
        submitted_text="I ran a replacement auth check.",
        pending_count=0,
    )
    assert replacement is not None
    assert replacement["summary"] == "I ran a replacement auth check."
    assert (
        build_waiting_composer_evidence(
            runtime=stamped,
            workspace_id="workspace-plan",
            submitted_text="I ran a replacement auth check.",
            pending_count=1,
        )
        is None
    )
    assert (
        build_waiting_composer_evidence(
            runtime=waiting,
            workspace_id="workspace-other",
            submitted_text="I ran the focused auth check on the login path.",
        )
        is None
    )


def test_waiting_composer_submit_enqueues_one_item_without_advancing(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    workspace_id = "workspace-plan-composer-enqueue"
    other_ws = "workspace-plan-composer-other"
    service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Keep one auth check",
            "why_now": "Expired tokens still leak the session.",
            "next_after_current": "Add a token expiry test",
            "resume_state": "waiting",
        },
        request_id="plan-composer-seed-1",
    )
    service.persist_plan_runtime_recovery(
        other_ws,
        plan_runtime={
            "current_step": "Keep the other login path",
            "resume_state": "waiting",
        },
        request_id="plan-composer-other-seed",
    )
    assert service.enqueue_waiting_composer_evidence(workspace_id, "   ") is None
    assert service.evidence_queue(workspace_id).pending == []
    item = service.enqueue_waiting_composer_evidence(
        workspace_id,
        "I ran the focused auth check on the login path.",
    )
    assert item is not None
    pending = service.evidence_queue(workspace_id).pending
    assert len(pending) == 1
    assert pending[0].id == item.id
    assert pending[0].summary == "I ran the focused auth check on the login path."
    assert pending[0].concepts == ["Keep one auth check"]
    assert pending[0].verified is False
    assert pending[0].outcome == "partial"
    assert pending[0].adopted is False
    runtime = service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
    assert runtime["resume_state"] == "waiting"
    assert runtime["current_step"] == "Keep one auth check"
    assert runtime["verify_method"] == ["I ran the focused auth check on the login path."]
    assert runtime["evidence_binding"] == item.id
    assert runtime.get("plan_id") in {None, ""}
    assert service.repository.get_latest_plan(workspace_id) is None
    assert service.evidence_queue(other_ws).pending == []
    assert (
        service.enqueue_waiting_composer_evidence(
            workspace_id,
            "A second invented verify result.",
        )
        is None
    )
    assert len(service.evidence_queue(workspace_id).pending) == 1
    adopted = service.adopt_evidence(workspace_id, item.id)
    assert adopted.evidence.adopted is True
    assert adopted.evidence.verified is True
    assert adopted.evidence.outcome == "pass"
    advanced = service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
    assert advanced["resume_state"] == "in_progress"
    assert advanced["current_step"] == "Add a token expiry test"
    assert advanced.get("evidence_binding") in {None, ""}
    assert live_evidence_binding(
        binding=item.id,
        pending_ids=[entry.id for entry in service.evidence_queue(workspace_id).pending],
        recovered=True,
        current_step=advanced["current_step"],
    ) == ""
    assert service.repository.get_latest_plan(workspace_id) is None


def test_waiting_composer_replace_after_reject_enqueues_one_and_adopt_advances(
    tmp_path: Path,
) -> None:
    service = build_memory_service(tmp_path)
    workspace_id = "workspace-plan-composer-replace"
    service.persist_plan_runtime_recovery(
        workspace_id,
        plan_runtime={
            "current_step": "Keep one auth check",
            "why_now": "Expired tokens still leak the session.",
            "next_after_current": "Add a token expiry test",
            "resume_state": "waiting",
        },
        request_id="plan-composer-replace-seed",
    )
    first = service.enqueue_waiting_composer_evidence(
        workspace_id,
        "I ran the focused auth check on the login path.",
    )
    assert first is not None
    rejected = service.reject_evidence(workspace_id, first.id, "Not enough proof")
    assert rejected.rejected_at
    after_reject = service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
    assert after_reject["resume_state"] == "waiting"
    assert after_reject["current_step"] == "Keep one auth check"
    assert after_reject["verify_method"] == ["I ran the focused auth check on the login path."]
    assert service.evidence_queue(workspace_id).pending == []
    assert service.enqueue_waiting_composer_evidence(workspace_id, "   ") is None
    assert service.evidence_queue(workspace_id).pending == []
    replacement = service.enqueue_waiting_composer_evidence(
        workspace_id,
        "I reran the focused auth check with the expiry case.",
    )
    assert replacement is not None
    assert replacement.id != first.id
    pending = service.evidence_queue(workspace_id).pending
    assert len(pending) == 1
    assert pending[0].id == replacement.id
    assert pending[0].summary == "I reran the focused auth check with the expiry case."
    assert pending[0].concepts == ["Keep one auth check"]
    assert pending[0].verified is False
    assert pending[0].outcome == "partial"
    runtime = service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
    assert runtime["resume_state"] == "waiting"
    assert runtime["verify_method"] == ["I reran the focused auth check with the expiry case."]
    assert runtime["evidence_binding"] == replacement.id
    assert runtime.get("plan_id") in {None, ""}
    assert (
        service.enqueue_waiting_composer_evidence(
            workspace_id,
            "A duplicate invented verify result.",
        )
        is None
    )
    assert len(service.evidence_queue(workspace_id).pending) == 1
    adopted = service.adopt_evidence(workspace_id, replacement.id)
    assert adopted.evidence.adopted is True
    assert adopted.evidence.verified is True
    advanced = service.recover_workspace_facts(workspace_id)[PLAN_RUNTIME_KEY]
    assert advanced["resume_state"] == "in_progress"
    assert advanced["current_step"] == "Add a token expiry test"
    assert service.repository.get_latest_plan(workspace_id) is None


def test_orphaned_pressure_runtime_does_not_invent_live_task_chrome() -> None:
    """Tight budget / leftover blocker without a formal plan must not mint active_task."""

    orphan = {
        "workspace_id": "workspace-pressure-orphan",
        "blocked_reason": "auth still fails",
        "current_step": "Keep one auth check",
        "resume_state": "in_progress",
    }
    assert live_coach_stage_label(runtime=orphan, existing=orphan, stage_title="") == ""
    chrome = live_plan_update_persist_chrome(
        plan=None,
        runtime=orphan,
        existing=orphan,
        stage_title="",
        task_title="",
    )
    assert chrome["active_task"] == ""
    assert chrome["active_stage"] == ""
    assert chrome["summary_object"] == ""
    assert "Keep one auth check" not in chrome["active_task"]
