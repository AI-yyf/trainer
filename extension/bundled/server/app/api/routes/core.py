"""Core sidecar routes (§五十二 extraction).

Registered before the domain routers so overlapping paths keep their
historical match order. Handlers close over ``runtime``/``deps`` and read
every former build_router helper from ``CoreRouteDeps``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from ...core.models import (
    ActiveCardSelectionResult,
    AgentCheckpointAccessRequest,
    CardGenerationRequest,
    CardGenerationResponse,
    CardStatusTransitionRequest,
    CardStatusTransitionResponse,
    ChatMessage,
    DependencySkillMapActionRequest,
    DependencySkillMapRestoreRequest,
    EvaluateCurrentFileRequest,
    EvaluateSnippetRequest,
    FlashcardAnswerRequest,
    LearningSignalRequest,
    PlanChangeCandidate,
    PracticeReturnRequest,
    ReviewArtifactActionRequest,
    ReviewArtifactRestoreRequest,
    ReviewQueueActionRequest,
    ScenarioLabActionRequest,
    ScenarioLabRestoreRequest,
    SessionMessageRequest,
    SessionMessageResponse,
    SessionStartRequest,
    TaskNextRequest,
    TaskSpec,
    TaskSpecifyRequest,
    TheoryDrillAnswerRequest,
    TheoryDrillRestoreRequest,
    TrainingCardCandidateSnapshot,
    TurnRequest,
    UserFeedbackRequest,
    UserProfile,
    WorkbenchSnapshot,
)
from ...llm.provider_service import (
    ProviderService,
    redact_provider_error,
)
from ...llm.stream_agent_metadata import merge_stream_agent_metadata
from ...memory.workspace_recovery import (
    PLAN_RUNTIME_KEY,
    leftover_formal_plan_is_live_for_fill,
    live_plan_mismatch_candidate_plan_id,
    live_plan_mismatch_candidate_step,
    live_runtime_stage_id,
    select_plan_runtime_for_scope,
    stamp_produced_workspace_record,
)
from ...training.card_generator import (
    CardGenerationProviderFailure,
)
from .. import coach_support
from .._helpers import (
    localized_text,
)
from .._singleflight import (
    claim_session_request_singleflight,
    fail_session_request_singleflight,
    publish_session_request_singleflight,
)
from ..coach_support import CoachTurnPayload
from ..router_support import (
    _attach_requested_workspace_files,
    _normalize_resource_turn_request,
    _resolve_agent_loop_enabled,
    _stamp_library_sandbox_work,
    _workspace_snapshot_from_payload,
    overlay_session_response_honesty_stamps,
)
from ..router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from ..router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from ..routes._deps import RouterDeps
from ..runtime import SessionState, TrainerRuntime
from ..training_card_identity import (
    prepare_training_file_evaluation,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CoreRouteDeps:
    """Helper closures and handler cross-references for core routes."""

    _stream_snapshot_fields: Any
    adopt_workspace_learning_project_folder: Any
    advance_plan_after_evaluation: Any
    answer_mode_preference_for_persistence: Any
    apply_attachment_delivery_metadata: Any
    apply_auto_resource_agent_evidence: Any
    apply_grounding_decision: Any
    apply_guided_lane_visible_fallback: Any
    apply_guided_training_visible_fallback: Any
    apply_host_workspace_trust_attestation: Any
    apply_language_corruption_override: Any
    attach_operation_reliability: Any
    auto_lane_learn_first_force_training_card: Any
    auto_preference_requests_training_card: Any
    auto_resource_lookup_tool_events: Any
    build_coaching_service: Any
    build_conversation_history: Any
    build_grounded_resource_contract_visible_fallback: Any
    build_guided_training_visible_fallback: Any
    build_local_sequence_visible_fallback: Any
    build_resume_thread_text: Any
    build_user_message_metadata: Any
    card_generation_service_for: Any
    clean_active_thread_task: Any
    coach_support_deps: Any
    coach_turn_mapping: Any
    completed_session_requests: Any
    completed_session_requests_guard: Any
    completed_training_card_requests: Any
    completed_training_card_requests_guard: Any
    completion_stream_delta: Any
    consume_provider_empty_reply_override: Any
    consume_provider_reply_failure_override: Any
    current_snapshot: Any
    current_workspace_id: Any
    describe_request_attachment_delivery: Any
    detect_provider_language_corruption: Any
    effective_response_language: Any
    ensure_agent_tools_ready: Any
    ensure_coach_provider_ready: Any
    ensure_explicit_training_card_after_coach_reply: Any
    ensure_explicit_training_card_after_language_block: Any
    ensure_streaming_ready: Any
    existing_open_resource_training_card: Any
    extract_coach_turn_payload: Any
    finalize_stream_persistence: Any
    force_new_session_requested: Any
    formal_plan_commit_tool_succeeded: Any
    grounded_resource_contract_needs_repair: Any
    grounding_decision_from_payload: Any
    guarantee_guided_learn_first_training_card: Any
    head_plan_revision: Any
    honest_suggested_actions_without_usable_provider: Any
    honest_unusable_provider_stream: Any
    inflight_session_requests: Any
    inflight_training_card_requests: Any
    isolate_preflight_language_corruption_turn: Any
    json_object_payload: Any
    leftover_plan_state_fields: Any
    leftover_runtime_for_workspace: Any
    live_current_task_focus: Any
    maybe_persist_first_look_from_path: Any
    merge_agent_finalize_into_coach_turn: Any
    message_confirms_learning_project_folder: Any
    message_rejects_learning_project_folder: Any
    normalize_attachment_delivery_payload: Any
    normalize_trainer_root_path: Any
    normalized_object_mapping: Any
    persist_evaluation_learning_loop: Any
    persist_external_references_as_background: Any
    persist_plan_to_sandbox: Any
    persist_recovered_plan_resume_after_turn: Any
    persist_requested_response_language: Any
    prepare_stream_user_message: Any
    prepare_training_card_request: Any
    pressure_without_live_object_blocks_mint: Any
    profile_with_teaching_style: Any
    provider_api_key_from_payload: Any
    provider_config_from_payload: Any
    provider_is_live_usable: Any
    read_agent_checkpoint_or_raise: Any
    record_training_practice_evaluation: Any
    refresh_workspace_sessions: Any
    register_stream_cancellation: Any
    reject_blank_coach_message: Any
    reject_if_provider_not_live_usable: Any
    reliability_outcome_from_payload: Any
    repair_generic_finalize_next_step: Any
    repair_guided_lane_memory_snapshot_for_response: Any
    reply_explicitly_lists_prepared_sequence: Any
    request_stream_cancellation: Any
    request_with_workspace_defaults: Any
    require_live_formal_plan_for_explicit_task_next: Any
    require_live_selected_card_for_status: Any
    requires_formal_plan_commit: Any
    resolve_session_history_state: Any
    resolve_stream_id: Any
    resolve_turn_grounding_async: Any
    resolved_profile: Any
    resource_contract_stream_recovery_requested: Any
    routing_changed: Any
    safe_activate_training_card_from_coach_request: Any
    safe_stream_delta: Any
    save_plan_or_conflict: Any
    select_active_training_card: Any
    should_attach_auto_resource_events: Any
    should_bypass_agent_loop_for_guided_training: Any
    sse_complete_frame: Any
    streak_without_live_object_blocks_mint: Any
    stream_cancellation_events: Any
    stream_cancellation_requested: Any
    stream_frame: Any
    stream_status_event: Any
    summarize_session_list_payload: Any
    summarize_session_state: Any
    task_training_concepts: Any
    teaching_strategy_context_from_snapshot: Any
    to_json_payload: Any
    training_generate_and_route_card: Any
    training_practice_blocked_report: Any
    trusted_training_card_request_from_api: Any
    turn_history_text: Any
    turn_request_from_stream_payload: Any
    unregister_stream_cancellation: Any
    update_snapshot_plan_from_turn: Any
    validate_project_provisioning_or_repair: Any
    workspace_learning_project_prompt_needed: Any
    workspace_learning_project_prompt_text: Any
    workspace_learning_project_state: Any
    workspace_preferences: Any
    workspace_response_language: Any

    # Filled by build_core_router after the handlers are defined.
    acknowledge_plan_change_candidate: Any = None
    cancel_stream: Any = None
    evaluate_current_file: Any = None
    evaluate_snippet: Any = None
    get_snapshot: Any = None
    health: Any = None
    list_plan_change_candidates: Any = None
    list_session_checkpoints: Any = None
    read_session_checkpoint: Any = None
    record_learning_signal: Any = None
    record_user_feedback: Any = None
    reject_plan_change_candidate: Any = None
    replay_session_checkpoint: Any = None
    resume_session_checkpoint: Any = None
    session_activate: Any = None
    session_history: Any = None
    session_list: Any = None
    session_message: Any = None
    session_message_stream: Any = None
    session_start: Any = None
    session_steer: Any = None
    task_next: Any = None
    task_specify: Any = None
    training_active_card: Any = None
    training_card_status: Any = None
    training_dependency_skill_map_action: Any = None
    training_dependency_skill_map_restore: Any = None
    training_flashcard_answer: Any = None
    training_generate_card: Any = None
    training_generate_card_stream: Any = None
    training_practice_return: Any = None
    training_review_artifact_action: Any = None
    training_review_artifact_restore: Any = None
    training_review_queue_action: Any = None
    training_scenario_lab_action: Any = None
    training_scenario_lab_restore: Any = None
    training_theory_drill_answer: Any = None
    training_theory_drill_restore: Any = None
    turn: Any = None
    turn_stream: Any = None


def build_core_router(
    runtime: TrainerRuntime,
    deps: RouterDeps,
    seed: CoreRouteDeps,
) -> APIRouter:
    router = APIRouter()
    core = seed
    @router.get("/snapshot")
    def get_snapshot(
        session_id: str | None = None,
        workspace_id: str | None = None,
        since_revision: int = -1,
        fields: str | None = None,
    ) -> dict[str, object]:
        """F3 slim-payload companion: full snapshot fetch with revision gating.

        Clients receiving a slim stream frame (`snapshot_dirty`) call this with
        their known revision; when nothing changed the snapshot is omitted.
        """
        resolved_workspace_id = core.current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        revision = runtime.snapshot_revision(resolved_workspace_id)
        if since_revision == revision and fields != "full":
            return {"snapshot_revision": revision, "unchanged": True}
        snapshot = core.current_snapshot(session_id=session_id, workspace_id=resolved_workspace_id)
        snapshot.snapshot_revision = max(revision, snapshot.snapshot_revision)
        return {
            "snapshot_revision": snapshot.snapshot_revision,
            "unchanged": False,
            "snapshot": snapshot.model_dump(mode="json", by_alias=False),
        }

    @router.get("/health")
    def health(request: Request) -> dict[str, object]:
        database_path = str(runtime.repository.database_path)
        provider_config = runtime.provider_service._config  # noqa: SLF001
        provider_name = provider_config.name if provider_config else None
        provider_model = provider_config.model if provider_config else None
        provider_base_url = provider_config.base_url if provider_config else None
        return {
            "status": "ok",
            "initialized": True,
            "database_path": database_path,
            "provider": {
                "configured": provider_config is not None,
                "name": provider_name,
                "model": provider_model,
                "base_url": provider_base_url,
                "has_api_key": runtime.provider_service.has_api_key,
            },
            "research": {
                "provider_attached": True,
            },
            "resource_fetch": {
                "network_enabled": bool(getattr(runtime.resource_service, "enable_network_fetch", False)),
            },
        }

    @router.post("/session/start", response_model=None)
    def session_start(payload: dict) -> object:
        requested_response_language = (
            str(payload.get("response_language") or payload.get("responseLanguage") or "").strip() or None
        )
        if "user_profile" in payload:
            workspace_context = payload.get("workspace_context", {})
            workspace_id = core.current_workspace_id(
                workspace_id=str(workspace_context.get("workspace_id") or "workspace-default")
            )
            workspace_name = workspace_context.get("name", "Trainer")
            workspace_path = workspace_context.get("root_path") or workspace_context.get("workspace_path")
            remote_name = str(
                workspace_context.get("remote_name")
                or workspace_context.get("remoteName")
                or payload.get("remote_name")
                or payload.get("remoteName")
                or ""
            ).strip()
            project_provisioning = core.validate_project_provisioning_or_repair(workspace_id, requested_response_language)
            profile_payload = payload.get("user_profile", {})
            profile = UserProfile(
                long_term_goals=profile_payload.get("long_term_goals", []),
                weekly_hours=profile_payload.get("weekly_hours", 4),
                teaching_style=profile_payload.get("teaching_style", "auto"),
                answer_policy="direct" if profile_payload.get("allow_direct_answers") else "auto",
                preferred_libraries=profile_payload.get("focus_libraries", []),
            )
            runtime.memory_service.record_profile(workspace_id, profile)
            if workspace_path is None and project_provisioning is not None:
                workspace_path = project_provisioning.project_path
            runtime.register_workspace_path(workspace_id, workspace_path)
            runtime.memory_service.update_workspace_state(
                workspace_id,
                remote_name=remote_name,
                is_remote_workspace=bool(remote_name),
                workspace_trusted=bool(
                    workspace_context.get("workspace_trusted")
                    if "workspace_trusted" in workspace_context
                    else workspace_context.get("trusted")
                    if "trusted" in workspace_context
                    else payload.get("workspace_trusted", payload.get("trusted", False))
                ),
            )
            core.persist_requested_response_language(workspace_id, requested_response_language)
            start_response_language = core.effective_response_language(
                workspace_id,
                requested_response_language,
                str(payload.get("initial_message") or "").strip() or None,
            )
            state = runtime.start_session(workspace_id, workspace_name)
            if workspace_path:
                core.maybe_persist_first_look_from_path(
                    workspace_id,
                    str(workspace_path),
                    response_language=start_response_language,
                    workspace_file_snapshot=_workspace_snapshot_from_payload(payload),
                    remote_name=str(remote_name or "").strip() or None,
                )
            should_seed_learning_project_prompt = core.workspace_learning_project_prompt_needed(workspace_id)
            if should_seed_learning_project_prompt:
                runtime.memory_service.update_workspace_state(
                    workspace_id,
                    learning_project_prompt_status="pending",
                    learning_project_source_path=str(workspace_path or ""),
                )
            user_message = ChatMessage(
                id=f"message-{uuid4().hex[:10]}",
                role="user",
                content=payload.get("initial_message", "Let's begin."),
                timestamp=datetime.now(UTC),
            )
            assistant_message = ChatMessage(
                id=f"message-{uuid4().hex[:10]}",
                role="assistant",
                content=(
                    "We have a starting profile. Next, we should lock the target outcome, "
                    "decide the answer policy, and pick the first narrow exercise."
                ),
                timestamp=datetime.now(UTC),
            )
            seeded_messages = [user_message, assistant_message]
            if should_seed_learning_project_prompt:
                seeded_messages.append(
                    ChatMessage(
                        id=f"message-{uuid4().hex[:10]}",
                        role="assistant",
                        content=core.workspace_learning_project_prompt_text(
                            workspace_path=str(workspace_path or ""),
                            response_language=start_response_language,
                        ),
                        timestamp=datetime.now(UTC),
                    )
                )
            state.snapshot.messages.extend(seeded_messages)
            return {
                "session_id": state.session_id,
                "stage": "intake",
                "summary": f"Learning session for {workspace_name}; goals: {', '.join(profile.long_term_goals)}.",
                "messages": [message.model_dump() for message in seeded_messages],
            }

        try:
            request = SessionStartRequest.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=exc.errors(include_context=False),
            ) from exc
        workspace_id = core.current_workspace_id(workspace_id=request.workspace_id)
        project_provisioning = core.validate_project_provisioning_or_repair(workspace_id, requested_response_language)
        workspace_path = request.workspace_path
        if request.root_path:
            normalized_root_path = core.normalize_trainer_root_path(request.root_path)
            root = runtime.repository.get_trainer_root(request.root_id) if request.root_id else None
            if root is None:
                root = runtime.repository.get_trainer_root_by_path(normalized_root_path)
            if root is None or root.root_path != normalized_root_path:
                raise HTTPException(status_code=409, detail="The selected Trainer workspace root is not registered.")
            if project_provisioning is not None and project_provisioning.root_id != root.root_id:
                raise HTTPException(status_code=409, detail="The session project does not belong to the selected Trainer root.")
        if workspace_path is None and project_provisioning is not None:
            workspace_path = project_provisioning.project_path
        if request.profile:
            runtime.memory_service.record_profile(workspace_id, request.profile)
        if workspace_path is not None:
            runtime.register_workspace_path(workspace_id, workspace_path)
        if "remote_name" in payload or "remoteName" in payload:
            remote_name = str(request.remote_name or "").strip()
            trusted_patch: dict[str, object] = {
                "remote_name": remote_name,
                "is_remote_workspace": bool(remote_name),
            }
            if "workspace_trusted" in payload or "trusted" in payload or "workspaceTrusted" in payload:
                trusted_patch["workspace_trusted"] = bool(
                    payload.get(
                        "workspace_trusted",
                        payload.get("workspaceTrusted", payload.get("trusted", False)),
                    )
                )
            runtime.memory_service.update_workspace_state(workspace_id, **trusted_patch)
        elif "workspace_trusted" in payload or "trusted" in payload or "workspaceTrusted" in payload:
            runtime.memory_service.update_workspace_state(
                workspace_id,
                workspace_trusted=bool(
                    payload.get(
                        "workspace_trusted",
                        payload.get("workspaceTrusted", payload.get("trusted", False)),
                    )
                ),
            )
        core.persist_requested_response_language(workspace_id, requested_response_language)
        start_response_language = core.effective_response_language(
            workspace_id,
            requested_response_language,
            None,
        )

        # VS Code calls this route during rehydration without a session id. Keep that
        # ordinary path attached to the latest thread; starting over is explicit.
        initial_message = str(payload.get("initial_message") or "").strip()
        can_resume = (
            request.profile is None
            and not initial_message
            and not core.force_new_session_requested(payload)
        )
        if can_resume:
            restored = runtime.restore_latest_session_for_workspace(workspace_id)
            if restored is not None:
                restored.workspace_name = request.workspace_name
                restored.snapshot.context_id = workspace_id
                restored.snapshot.profile = runtime.repository.get_profile(workspace_id)
                restored.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
                runtime.hydrate_plan_context(restored.snapshot, workspace_id)
                coach_support.hydrate_snapshot(core.coach_support_deps,
                    restored.snapshot,
                    response_language=None,
                    answer_mode=(
                        restored.snapshot.profile.answer_policy
                        if restored.snapshot.profile
                        else None
                    ),
                    preserve_session_history=True,
                )
                runtime.save_session_state(restored.session_id)
                snapshot_payload = restored.snapshot.model_dump(by_alias=True)
                snapshot_payload["session_id"] = restored.session_id
                return snapshot_payload

        state = runtime.start_session(workspace_id, request.workspace_name)
        if workspace_path:
            core.maybe_persist_first_look_from_path(
                workspace_id,
                workspace_path,
                response_language=start_response_language,
                workspace_file_snapshot=_workspace_snapshot_from_payload(payload),
                remote_name=str(request.remote_name or "").strip() or None,
            )
        if core.workspace_learning_project_prompt_needed(workspace_id):
            runtime.memory_service.update_workspace_state(
                workspace_id,
                learning_project_prompt_status="pending",
                learning_project_source_path=str(workspace_path or ""),
            )
            state.snapshot.messages.append(
                ChatMessage(
                    id=f"message-{uuid4().hex[:10]}",
                    role="assistant",
                    content=core.workspace_learning_project_prompt_text(
                        workspace_path=str(workspace_path or ""),
                        response_language=start_response_language,
                    ),
                    timestamp=datetime.now(UTC),
                )
            )
        state.snapshot.profile = runtime.repository.get_profile(workspace_id)
        state.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
        coach_support.hydrate_snapshot(core.coach_support_deps,
            state.snapshot,
            response_language=None,
            answer_mode=state.snapshot.profile.answer_policy if state.snapshot.profile else None,
        )
        runtime.save_session_state(state.session_id)
        snapshot_payload = state.snapshot.model_dump(by_alias=True)
        snapshot_payload["session_id"] = state.session_id
        return snapshot_payload

    @router.post("/session/message", response_model=None)
    async def session_message(payload: dict) -> object:
        request = SessionMessageRequest.model_validate(payload)
        workspace_id = core.current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        # Mid-session host re-attest so trust flips apply before authority/capability.
        core.apply_host_workspace_trust_attestation(workspace_id, payload)
        request_id = str(request.request_id or "").strip()
        request_key = (workspace_id, str(request.session_id or "").strip(), request_id)
        owner_future: asyncio.Future | None = None

        def _overlay_completed_session_response(cached_response: dict[str, object]) -> dict[str, object]:
            # Fail-closed: never serve a completed/shared snapshot missing current
            # honesty stamps added by a later hydrate (leftover recovered / mint blocks).
            state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
            snapshot = state.snapshot
            pressure_blocks = core.pressure_without_live_object_blocks_mint(
                workspace_id,
                snapshot=snapshot,
                current_task=snapshot.current_task,
                current_plan=snapshot.plan,
                message=request.message,
            )
            streak_blocks = core.streak_without_live_object_blocks_mint(
                workspace_id,
                snapshot=snapshot,
                current_task=snapshot.current_task,
                current_plan=snapshot.plan,
            )
            live_status = (
                snapshot.plan_runtime_status
                if isinstance(snapshot.plan_runtime_status, dict)
                else {}
            )
            leftover_plan, leftover_runtime = core.leftover_runtime_for_workspace(workspace_id)
            leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
            live_for_attach = bool(leftover_runtime) and leftover_formal_plan_is_live_for_fill(
                plan=snapshot.plan or leftover_plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            recovered_leftover = False
            if not live_for_attach:
                if leftover_plan is not None:
                    recovered_leftover = True
                elif live_status.get("recovered") is True and snapshot.plan is None:
                    recovered_leftover = True
            stamped = overlay_session_response_honesty_stamps(
                cached_response,
                pressure_blocks=pressure_blocks,
                streak_blocks=streak_blocks,
                recovered_leftover=recovered_leftover,
            )
            if stamped is not cached_response:
                with core.completed_session_requests_guard:
                    core.completed_session_requests[request_key] = stamped
            return stamped

        def _finish_session_response(payload: dict[str, object]) -> dict[str, object]:
            stamped = _attach_requested_workspace_files(payload, runtime, workspace_id)
            if not request_id:
                return stamped
            return publish_session_request_singleflight(
                request_key,
                stamped,
                completed=core.completed_session_requests,
                inflight=core.inflight_session_requests,
                guard=core.completed_session_requests_guard,
            )

        def _owner_task_cleanup(task: asyncio.Task) -> None:
            if owner_future is None or owner_future.done():
                return
            with core.completed_session_requests_guard:
                core.inflight_session_requests.pop(request_key, None)
                cached = core.completed_session_requests.get(request_key)
            if cached is not None:
                owner_future.set_result(cached)
                return
            if task.cancelled():
                owner_future.set_exception(asyncio.CancelledError())
                return
            try:
                exc = task.exception()
            except asyncio.CancelledError as cancelled:
                owner_future.set_exception(cancelled)
                return
            if exc is not None:
                owner_future.set_exception(exc)
                return
            owner_future.set_exception(
                RuntimeError("session request completed without publishing a payload")
            )

        if request_id:
            kind, cached_response, shared_future = claim_session_request_singleflight(
                request_key,
                completed=core.completed_session_requests,
                inflight=core.inflight_session_requests,
                guard=core.completed_session_requests_guard,
            )
            if kind == "wait":
                assert shared_future is not None
                shared_payload = await shared_future
                return _overlay_completed_session_response(shared_payload)
            if kind == "cached":
                assert cached_response is not None
                return _overlay_completed_session_response(cached_response)
            owner_future = shared_future
            current_task = asyncio.current_task()
            if current_task is not None:
                current_task.add_done_callback(_owner_task_cleanup)
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        profile = core.resolved_profile(state.workspace_id)
        raw_requested_answer_mode = str(
            payload.get("answer_mode") or payload.get("answerMode") or ""
        ).strip()
        saved_answer_mode = str(core.workspace_preferences(workspace_id).get("answer_mode") or "").strip()
        request = core.request_with_workspace_defaults(
            request,
            workspace_id=workspace_id,
            profile=profile,
        )
        profile = core.profile_with_teaching_style(profile, request.teaching_style)

        # Per-request provider config override
        coaching_service = runtime.provider_service
        override_config = core.provider_config_from_payload(payload)
        api_key_override = core.provider_api_key_from_payload(payload)
        if override_config is not None or api_key_override is not None:
            coaching_service = runtime.provider_service_for(override_config, api_key_override)
        core.ensure_coach_provider_ready(
            coaching_service,
            response_language=request.response_language,
        )
        provider_live_usable = core.provider_is_live_usable(coaching_service, payload)
        if not provider_live_usable:
            turn_request = core.turn_request_from_stream_payload(payload, intent="coach")
            response, artifacts, _ = await coach_support.execute_turn(core.coach_support_deps, turn_request, payload, stream=False)
            response_payload = core.json_object_payload(response)
            if artifacts:
                response_payload["artifacts"] = artifacts
            return _finish_session_response(
                core.attach_operation_reliability(
                    response_payload,
                    phase="acked",
                    outcome="failure",
                    request_id=str(request.request_id or "").strip() or None,
                )
            )
        core.ensure_agent_tools_ready(request, coaching_service)
        use_agent_loop = _resolve_agent_loop_enabled(request, coaching_service, payload=payload)
        attachments_payload = [a.model_dump() for a in request.attachments]
        attachment_delivery = core.describe_request_attachment_delivery(
            request,
            coaching_service,
            use_agent_loop=use_agent_loop,
        )

        user_message = ChatMessage(
            id=f"message-{uuid4().hex[:10]}",
            role="user",
            content=request.message,
            timestamp=datetime.now(UTC),
            metadata=core.build_user_message_metadata(request, profile, attachment_delivery),
        )
        state.snapshot.messages.append(user_message)
        state.snapshot.profile = profile
        runtime.memory_service.record_session_message(
            state.session_id,
            f"user: {request.message}",
            workspace_id=state.workspace_id,
        )
        core.safe_activate_training_card_from_coach_request(
            workspace_id=state.workspace_id,
            snapshot=state.snapshot,
            message=request.message,
            current_file=request.current_file,
            response_language=request.response_language,
            provider_service_override=coaching_service,
        )
        state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        learning_project_state = core.workspace_learning_project_state(state.workspace_id)
        if learning_project_state.get("prompt_status") == "pending":
            handled_reply: str | None = None
            if core.message_confirms_learning_project_folder(request.message):
                _linked_root, handled_reply = core.adopt_workspace_learning_project_folder(
                    workspace_id=state.workspace_id,
                    workspace_name=state.workspace_name,
                    response_language=request.response_language,
                )
            elif core.message_rejects_learning_project_folder(request.message):
                runtime.memory_service.update_workspace_state(
                    state.workspace_id,
                    learning_project_prompt_status="dismissed",
                )
                handled_reply = localized_text(
                    "Okay. Trainer will keep the current sandbox arrangement for now and will not create a learning project folder yet.",
                    "好。Trainer 先保留当前的 sandbox 方式，暂时不创建学习项目文件夹。",
                    request.response_language,
                )
            if handled_reply:
                state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
                state.snapshot.profile = profile
                coach_support.hydrate_snapshot(core.coach_support_deps,
                    state.snapshot,
                    response_language=request.response_language,
                    answer_mode=request.answer_mode or (profile.answer_policy if profile else None),
                    scenario="general",
                    learner_signal="steady",
                    message=request.message,
                    active_view=request.active_view,
                )
                response = coach_support.build_session_response(core.coach_support_deps, 
                    state=state,
                    request=request,
                    reply_content=handled_reply,
                    artifacts={},
                    suggested_actions=[],
                    scenario="general",
                    learner_signal="steady",
                    coach_turn_data=None,
                    agent_meta=None,
                    attachment_delivery=attachment_delivery,
                )
                runtime.save_session_state(state.session_id)
                return _finish_session_response(core.json_object_payload(response))
        coach_turn: CoachTurnPayload = coach_support.resolve_coach_turn(core.coach_support_deps, 
            state=state,
            profile=profile,
            request=request,
            message=request.message,
            coaching_service=coaching_service,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
            current_evaluation=state.snapshot.evaluation,
        )
        scenario = str(coach_turn.get("scenario") or "general")
        if core.guarantee_guided_learn_first_training_card(
            workspace_id=state.workspace_id,
            scenario=str(coach_turn["scenario"] or ""),
            message=request.message,
            current_file=request.current_file,
            response_language=request.response_language,
            active_thread=state.snapshot.memory.active_thread,
            requested_answer_mode=raw_requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        ):
            state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        auto_resource_events = core.auto_resource_lookup_tool_events(
            dict(coach_turn["coach_context"]),
            request.message,
        )
        guided_training_prefers_local_reply = core.should_bypass_agent_loop_for_guided_training(
            workspace_id=state.workspace_id,
            scenario=str(coach_turn["scenario"] or scenario),
            message=request.message,
            active_view=request.active_view,
            requested_answer_mode=raw_requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        )
        guided_training_local_reply = (
            core.build_guided_training_visible_fallback(
                workspace_id=state.workspace_id,
                response_language=request.response_language,
            )
            if guided_training_prefers_local_reply
            else None
        )

        agent_meta: dict[str, object] = {}
        language_corruption_detected = False
        provider_failure_detected = False
        preflight_language_probe = core.detect_provider_language_corruption(
            coaching_service,
            message=request.message,
            response_language=request.response_language,
            coach_context=dict(coach_turn["coach_context"]),
        )
        if preflight_language_probe is not None:
            language_corruption_detected = True
            coach_turn = core.extract_coach_turn_payload(
                core.isolate_preflight_language_corruption_turn(
                    core.coach_turn_mapping(coach_turn),
                    message=request.message,
                    current_file=request.current_file.model_dump() if request.current_file else None,
                )
            )
            assistant_content, updated_coach_turn, agent_meta = core.apply_language_corruption_override(
                coaching_service=coaching_service,
                snapshot=state.snapshot,
                coach_turn=core.coach_turn_mapping(coach_turn),
                message=request.message,
                response_language=request.response_language,
                allow_guided_recovery=False,
            )
            coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
            core.ensure_explicit_training_card_after_language_block(
                state=state,
                message=request.message,
                current_file=request.current_file,
                response_language=request.response_language,
                fallback_scenario=str(coach_turn.get("scenario") or scenario),
                force_training_card=(
                    core.auto_preference_requests_training_card(
                        request.message,
                        requested_scenario=str(coach_turn.get("scenario") or scenario),
                        requested_answer_mode=raw_requested_answer_mode,
                        saved_answer_mode=saved_answer_mode,
                        profile=profile,
                    )
                    or core.auto_lane_learn_first_force_training_card(
                        request.message,
                        requested_scenario=str(coach_turn.get("scenario") or scenario),
                        requested_answer_mode=raw_requested_answer_mode,
                        saved_answer_mode=saved_answer_mode,
                        profile=profile,
                    )
                ),
                provider_service_override=coaching_service,
            )
            scenario = str(coach_turn.get("scenario") or scenario)
            agent_meta["scenario"] = scenario
        elif guided_training_local_reply is not None:
            assistant_content, updated_coach_turn, agent_meta = core.apply_guided_training_visible_fallback(
                coach_turn=core.coach_turn_mapping(coach_turn),
                fallback=guided_training_local_reply,
            )
            coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
        elif use_agent_loop and not guided_training_prefers_local_reply:
            agent_context = dict(coach_turn["coach_context"])
            agent_context["__runtime__"] = runtime
            agent_context["workspace_id"] = workspace_id
            agent_context["session_id"] = state.session_id
            _stamp_library_sandbox_work(agent_context, request, payload)
            agent_outcome = await coaching_service.coaching_reply_agentic(
                profile,
                request.message,
                request.current_file.model_dump() if request.current_file else None,
                response_language=request.response_language,
                answer_mode=request.answer_mode,
                coach_context=agent_context,
                attachments=attachments_payload,
                protocol=getattr(coaching_service._config, "protocol", None) if coaching_service._config else None,
                history=core.build_conversation_history(
                    state.snapshot.messages,
                    drop_latest_user=True,
                ),
            )
            assistant_content = str(agent_outcome.get("content") or "").strip()
            agent_resume_thread = str(agent_outcome.get("resume_thread") or "").strip()
            if not agent_resume_thread:
                agent_resume_thread = core.build_resume_thread_text(
                    str(agent_outcome.get("summary") or "").strip(),
                    str(agent_outcome.get("next_step") or "").strip(),
                    response_language=request.response_language,
                )
            agent_meta = {
                "stop_reason": agent_outcome.get("stop_reason"),
                "summary": agent_outcome.get("summary"),
                "next_step": agent_outcome.get("next_step"),
                "decision": agent_outcome.get("decision"),
                "blocker": agent_outcome.get("blocker"),
                "teaching_note": agent_outcome.get("teaching_note"),
                "resume_thread": agent_resume_thread,
                "confidence": agent_outcome.get("confidence"),
                "evidence": agent_outcome.get("evidence"),
                "steps": agent_outcome.get("steps", []),
                "tool_events": agent_outcome.get("tool_events", []),
                "fell_back": bool(agent_outcome.get("fell_back")),
                "recovered_stop_reason": agent_outcome.get("recovered_stop_reason"),
                "agentic": True,
            }
            core.apply_attachment_delivery_metadata(agent_meta, agent_outcome)
            original_agent_stop_reason = str(agent_outcome.get("stop_reason") or "").strip()
            local_sequence_fallback: dict[str, str] | None = None
            local_sequence_fallback = core.build_local_sequence_visible_fallback(
                coach_context=dict(coach_turn["coach_context"]),
                response_language=request.response_language,
            )
            force_local_sequence = bool(
                local_sequence_fallback is not None
                and (
                    str(agent_outcome.get("stop_reason") or "").strip() == "empty_response"
                    or not core.reply_explicitly_lists_prepared_sequence(
                        assistant_content,
                        coach_context=dict(coach_turn["coach_context"]),
                    )
                )
            )
            if force_local_sequence and local_sequence_fallback is not None:
                assistant_content = local_sequence_fallback["reply"]
                coaching_service.clear_last_reply_override()
                agent_meta["summary"] = agent_meta.get("summary") or local_sequence_fallback["summary"]
                agent_meta["next_step"] = (
                    agent_meta.get("next_step") or local_sequence_fallback["next_step"]
                )
                agent_meta["teaching_note"] = (
                    agent_meta.get("teaching_note") or local_sequence_fallback["teaching_note"]
                )
                if not str(agent_meta.get("resume_thread") or "").strip():
                    agent_meta["resume_thread"] = local_sequence_fallback["resume_thread"]
                if original_agent_stop_reason == "empty_response":
                    agent_meta["fell_back"] = True
                    agent_meta["recovered_stop_reason"] = original_agent_stop_reason
                    agent_meta["stop_reason"] = "completed"
                else:
                    agent_meta["grounded_sequence_enforced"] = True
                agent_meta["local_sequence_fallback"] = True
            elif not assistant_content:
                if local_sequence_fallback is None:
                    assistant_content = await coaching_service.coaching_reply(
                        profile,
                        request.message,
                        request.current_file.model_dump() if request.current_file else None,
                        response_language=request.response_language,
                        answer_mode=request.answer_mode,
                        coach_context=dict(coach_turn["coach_context"]),
                        history=core.build_conversation_history(
                            state.snapshot.messages,
                            drop_latest_user=True,
                        ),
                    )
                else:
                    assistant_content = local_sequence_fallback["reply"]
                    coaching_service.clear_last_reply_override()
                    agent_meta["summary"] = agent_meta.get("summary") or local_sequence_fallback["summary"]
                    agent_meta["next_step"] = (
                        agent_meta.get("next_step") or local_sequence_fallback["next_step"]
                    )
                    agent_meta["teaching_note"] = (
                        agent_meta.get("teaching_note") or local_sequence_fallback["teaching_note"]
                    )
                    if not str(agent_meta.get("resume_thread") or "").strip():
                        agent_meta["resume_thread"] = local_sequence_fallback["resume_thread"]
                agent_meta["fell_back"] = True
                if original_agent_stop_reason == "empty_response":
                    agent_meta["recovered_stop_reason"] = original_agent_stop_reason
                    agent_meta["stop_reason"] = "completed"
                agent_meta["local_sequence_fallback"] = local_sequence_fallback is not None
            updated_coach_turn = core.merge_agent_finalize_into_coach_turn(
                core.coach_turn_mapping(coach_turn),
                summary=agent_outcome.get("summary")
                or (local_sequence_fallback or {}).get("summary"),
                next_step=agent_outcome.get("next_step")
                or (local_sequence_fallback or {}).get("next_step"),
                blocker=agent_outcome.get("blocker"),
                resume_thread=agent_resume_thread
                or (local_sequence_fallback or {}).get("resume_thread"),
                decision=agent_outcome.get("decision"),
                teaching_note=agent_outcome.get("teaching_note")
                or (local_sequence_fallback or {}).get("teaching_note"),
                confidence=agent_outcome.get("confidence"),
                evidence=agent_outcome.get("evidence"),
            )
            coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
        else:
            assistant_content = await coaching_service.coaching_reply(
                profile,
                request.message,
                request.current_file.model_dump() if request.current_file else None,
                response_language=request.response_language,
                answer_mode=request.answer_mode,
                coach_context=dict(coach_turn["coach_context"]),
                history=core.build_conversation_history(
                    state.snapshot.messages,
                    drop_latest_user=True,
                ),
            )
        provider_empty_reply_override = core.consume_provider_empty_reply_override(
            coaching_service=coaching_service,
            snapshot=state.snapshot,
            coach_turn=core.coach_turn_mapping(coach_turn),
            response_language=request.response_language,
            assistant_content=assistant_content,
        )
        if provider_empty_reply_override is not None:
            provider_failure_detected = True
            assistant_content, updated_coach_turn, override_meta = provider_empty_reply_override
            coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
            agent_meta.update(override_meta)
        else:
            provider_failure_override = core.consume_provider_reply_failure_override(
                coaching_service=coaching_service,
                snapshot=state.snapshot,
                coach_turn=core.coach_turn_mapping(coach_turn),
                message=request.message,
                response_language=request.response_language,
                workspace_id=state.workspace_id,
            )
            if provider_failure_override is not None:
                provider_failure_detected = True
                assistant_content, updated_coach_turn, override_meta = provider_failure_override
                coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
                agent_meta.update(override_meta)
            elif not language_corruption_detected and coaching_service.detect_language_corruption(
                message=request.message,
                reply=assistant_content,
                response_language=request.response_language,
            ):
                language_corruption_detected = True
                assistant_content, updated_coach_turn, override_meta = core.apply_language_corruption_override(
                    coaching_service=coaching_service,
                    snapshot=state.snapshot,
                    coach_turn=core.coach_turn_mapping(coach_turn),
                    message=request.message,
                    response_language=request.response_language,
                    reply_corruption=True,
                )
                coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
                core.ensure_explicit_training_card_after_language_block(
                    state=state,
                    message=request.message,
                    current_file=request.current_file,
                    response_language=request.response_language,
                    fallback_scenario=str(coach_turn.get("scenario") or scenario),
                    force_training_card=(
                        core.auto_preference_requests_training_card(
                            request.message,
                            requested_scenario=str(coach_turn.get("scenario") or scenario),
                            requested_answer_mode=raw_requested_answer_mode,
                            saved_answer_mode=saved_answer_mode,
                            profile=profile,
                        )
                        or core.auto_lane_learn_first_force_training_card(
                            request.message,
                            requested_scenario=str(coach_turn.get("scenario") or scenario),
                            requested_answer_mode=raw_requested_answer_mode,
                            saved_answer_mode=saved_answer_mode,
                            profile=profile,
                        )
                    ),
                    provider_service_override=coaching_service,
                )
                scenario = str(coach_turn.get("scenario") or scenario)
                agent_meta.update(override_meta)
        if not provider_failure_detected:
            resource_contract_fallback = None
            if core.grounded_resource_contract_needs_repair(
                assistant_content,
                coach_context=dict(coach_turn["coach_context"]),
            ):
                resource_contract_fallback = core.build_grounded_resource_contract_visible_fallback(
                    workspace_id=workspace_id,
                    coach_context=dict(coach_turn["coach_context"]),
                    agent_meta=agent_meta,
                    response_language=request.response_language,
                )
            if resource_contract_fallback is not None:
                assistant_content = resource_contract_fallback["reply"]
                agent_meta["summary"] = resource_contract_fallback["summary"]
                agent_meta["next_step"] = resource_contract_fallback["next_step"]
                agent_meta["teaching_note"] = resource_contract_fallback["teaching_note"]
                agent_meta["resume_thread"] = resource_contract_fallback["resume_thread"]
                agent_meta["grounded_resource_contract_repaired"] = True
                agent_meta["scenario"] = str(coach_turn.get("scenario") or scenario)
                updated_coach_turn = core.merge_agent_finalize_into_coach_turn(
                    core.coach_turn_mapping(coach_turn),
                    summary=resource_contract_fallback["summary"],
                    next_step=resource_contract_fallback["next_step"],
                    blocker=agent_meta.get("blocker"),
                    resume_thread=resource_contract_fallback["resume_thread"],
                    decision=agent_meta.get("decision"),
                    teaching_note=resource_contract_fallback["teaching_note"],
                    confidence=agent_meta.get("confidence"),
                    evidence=agent_meta.get("evidence"),
                )
                coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
            assistant_content, updated_coach_turn, agent_meta, _guided_lane_repaired = (
                core.apply_guided_lane_visible_fallback(
                    reply=assistant_content,
                    scenario=str(coach_turn.get("scenario") or scenario),
                    learner_message=request.message,
                    response_language=request.response_language,
                    coach_turn=core.coach_turn_mapping(coach_turn),
                    agent_meta=agent_meta,
                )
            )
            coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
            core.ensure_explicit_training_card_after_coach_reply(
                state=state,
                message=request.message,
                current_file=request.current_file,
                response_language=request.response_language,
                fallback_scenario=str(coach_turn.get("scenario") or scenario),
                force_training_card=core.auto_preference_requests_training_card(
                    request.message,
                    requested_scenario=str(coach_turn.get("scenario") or scenario),
                    requested_answer_mode=raw_requested_answer_mode,
                    saved_answer_mode=saved_answer_mode,
                    profile=profile,
                )
                or core.auto_lane_learn_first_force_training_card(
                    request.message,
                    requested_scenario=str(coach_turn.get("scenario") or scenario),
                    requested_answer_mode=raw_requested_answer_mode,
                    saved_answer_mode=saved_answer_mode,
                    profile=profile,
                ),
                provider_service_override=coaching_service,
            )
        if core.should_attach_auto_resource_events(agent_meta):
            agent_meta = core.apply_auto_resource_agent_evidence(agent_meta, auto_resource_events)
        if not use_agent_loop and agent_meta:
            agent_meta["agentic"] = False
        grounding_decision = await core.resolve_turn_grounding_async(
            coach_turn_payload=coach_turn,
            reply_content=assistant_content,
            request=request,
            agent_meta=agent_meta if isinstance(agent_meta, dict) else None,
            history_text=core.turn_history_text(state.snapshot),
            coaching_service=coaching_service,
        )
        agent_meta = core.apply_grounding_decision(
            coach_turn_payload=coach_turn,
            decision=grounding_decision,
            agent_meta=agent_meta if isinstance(agent_meta, dict) else None,
        ) or agent_meta
        coach_support.persist_turn_reflection(core.coach_support_deps,
            workspace_id=workspace_id,
            session_id=state.session_id,
            user_message=request.message,
            scenario=str(coach_turn["scenario"]),
            response_language=request.response_language,
            answer_mode=core.answer_mode_preference_for_persistence(
                raw_requested_answer_mode,
                saved_answer_mode,
                request.answer_mode,
                profile.answer_policy if profile else None,
            ),
            coach_defaults=request.coach_defaults,
            coach_turn_data=core.coach_turn_mapping(coach_turn),
            grounding_decision=grounding_decision,
            stop_reason=str(agent_meta.get("stop_reason") or ""),
            recovered_stop_reason=str(agent_meta.get("recovered_stop_reason") or ""),
            local_sequence_fallback=bool(agent_meta.get("local_sequence_fallback")),
        )
        core.persist_recovered_plan_resume_after_turn(
            workspace_id=workspace_id,
            request=request,
            reply_content=assistant_content,
            agent_meta=agent_meta if isinstance(agent_meta, dict) else None,
            coach_context=coach_turn.get("coach_context") if isinstance(coach_turn, dict) else None,
            recovered_status=state.snapshot.plan_runtime_status
            if isinstance(state.snapshot.plan_runtime_status, dict)
            else None,
        )
        if not language_corruption_detected and not provider_failure_detected:
            core.persist_external_references_as_background(
                workspace_id=workspace_id,
                scenario=str(coach_turn["scenario"]),
                coach_turn_data=core.coach_turn_mapping(coach_turn),
            )
        state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.profile = runtime.repository.get_profile(workspace_id) or profile
        runtime.hydrate_plan_context(state.snapshot, workspace_id)
        coach_support.hydrate_snapshot(core.coach_support_deps,
            state.snapshot,
            response_language=request.response_language,
            answer_mode=request.answer_mode or (profile.answer_policy if profile else None),
            scenario=str(coach_turn["scenario"]),
            learner_signal=str(coach_turn["learner_signal"]),
            message=request.message,
            session_workspace_id=workspace_id,
        )
        session_suggested_actions = list(coach_turn["suggested_actions"])
        if not provider_live_usable:
            session_suggested_actions = core.honest_suggested_actions_without_usable_provider(
                session_suggested_actions,
                response_language=request.response_language,
                snapshot=state.snapshot,
                current_task=state.snapshot.current_task,
                current_plan=state.snapshot.plan,
                current_evaluation=state.snapshot.evaluation,
            )
        response = coach_support.build_session_response(core.coach_support_deps, 
            state=state,
            request=request,
            reply_content=assistant_content,
            artifacts=dict(coach_turn["artifacts"]),
            suggested_actions=session_suggested_actions,
            scenario=str(coach_turn["scenario"]),
            learner_signal=str(coach_turn["learner_signal"]),
            coach_turn_data=core.coach_turn_mapping(coach_turn),
            agent_meta=agent_meta or None,
            attachment_delivery=attachment_delivery,
        )
        runtime.save_session_state(state.session_id)
        response_payload = core.json_object_payload(response)
        if agent_meta:
            response_payload.setdefault("agent_meta", agent_meta)
        return _finish_session_response(response_payload)

    @router.get("/session/history", response_model=None)
    def session_history(
        session_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 12,
    ) -> list[dict[str, object]]:
        resolved_workspace_id = core.current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        _, state = core.resolve_session_history_state(session_id=session_id, workspace_id=resolved_workspace_id)
        if state is None:
            return []

        snapshot = getattr(state, "snapshot", None)
        messages = list(getattr(snapshot, "messages", []) or [])
        message_count = len(messages)
        latest_user_message = next(
            (
                message
                for message in reversed(messages)
                if getattr(message, "role", "") == "user" and str(getattr(message, "content", "") or "").strip()
            ),
            None,
        )
        latest_assistant_message = next(
            (
                message
                for message in reversed(messages)
                if getattr(message, "role", "") == "assistant" and str(getattr(message, "content", "") or "").strip()
            ),
            None,
        )
        session_memory = runtime.memory_service.snapshot(resolved_workspace_id)
        workspace_memory = session_memory.workspace if isinstance(session_memory.workspace, dict) else {}
        rolling_summary = str(workspace_memory.get("recent_summary") or session_memory.recent_summary or "").strip()
        summary = core.summarize_session_state(state) or rolling_summary
        if not summary:
            summary = rolling_summary or str(getattr(latest_assistant_message, "content", "") or "").strip()
        updated_at: str | None = None
        if messages:
            last_message = messages[-1]
            updated_at = str(getattr(last_message, "created_at", "") or "").strip()
            if not updated_at:
                timestamp = getattr(last_message, "timestamp", None)
                timestamp_isoformat = getattr(timestamp, "isoformat", None)
                if callable(timestamp_isoformat):
                    updated_at = str(timestamp_isoformat())
                elif timestamp is not None:
                    updated_at = str(timestamp)
        history_item: dict[str, object] = {
            "session_id": getattr(state, "session_id", session_id or ""),
            "workspace_id": getattr(state, "workspace_id", resolved_workspace_id),
            "workspace_name": getattr(state, "workspace_name", "") or "",
            "summary": summary,
            "message_count": message_count,
            "updated_at": updated_at,
        }
        if latest_user_message is not None:
            history_item["latest_user_message"] = str(getattr(latest_user_message, "content", "") or "").strip()
        if latest_assistant_message is not None:
            history_item["latest_assistant_message"] = str(
                getattr(latest_assistant_message, "content", "") or ""
            ).strip()
        return [history_item][:max(1, min(limit, 50))]

    @router.get("/session/list", response_model=None)
    def session_list(
        workspace_id: str,
        session_id: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, object]]:
        resolved_workspace_id = core.current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        resolved_workspace_id = runtime.repository.resolve_context_id(resolved_workspace_id) or resolved_workspace_id
        payloads = runtime.repository.list_sessions_for_workspace(
            resolved_workspace_id,
            limit=max(1, min(limit, 100)),
        )
        items: list[dict[str, object]] = []
        # The caller owns conversation selection; recency does not identify
        # the current conversation when the learner reopens older history.
        active_session_id = str(session_id or "").strip() or getattr(
            runtime.latest_session(), "session_id", None
        )
        for payload in payloads:
            item = core.summarize_session_list_payload(payload)
            if item is None:
                continue
            item["is_active"] = bool(
                active_session_id and item.get("session_id") == active_session_id
            )
            items.append(item)
        return items

    @router.post("/session/activate", response_model=None)
    def session_activate(payload: dict) -> dict[str, object]:
        requested_session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        resolved_workspace_id = core.current_workspace_id(
            session_id=requested_session_id,
            workspace_id=str(payload.get("workspace_id") or payload.get("workspaceId") or "").strip() or None,
        )
        resolved_workspace_id = runtime.repository.resolve_context_id(resolved_workspace_id) or resolved_workspace_id
        resolved_session_id, state = core.resolve_session_history_state(
            session_id=requested_session_id,
            workspace_id=resolved_workspace_id,
        )
        if state is None or not resolved_session_id:
            raise HTTPException(status_code=404, detail="Session was not found for this workspace.")
        # The helper falls back to the workspace's latest session; activation
        # must target the requested id or fail honestly.
        if requested_session_id and resolved_session_id != requested_session_id:
            raise HTTPException(status_code=404, detail="Session was not found for this workspace.")
        snapshot = core.current_snapshot(session_id=resolved_session_id, workspace_id=resolved_workspace_id)
        return {
            "session_id": resolved_session_id,
            "workspace_id": resolved_workspace_id,
            "snapshot": snapshot.model_dump(mode="json"),
        }

    @router.get("/session/checkpoints", response_model=None)
    def list_session_checkpoints(
        workspace_id: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        try:
            checkpoints = runtime.list_agent_turn_checkpoints(
                workspace_id=workspace_id,
                session_id=session_id,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"checkpoints": checkpoints}

    @router.post("/session/checkpoints/{checkpoint_id}/read", response_model=None)
    def read_session_checkpoint(
        checkpoint_id: str,
        scope: AgentCheckpointAccessRequest,
    ) -> dict[str, object]:
        return core.read_agent_checkpoint_or_raise(checkpoint_id=checkpoint_id, scope=scope)

    @router.post("/session/checkpoints/{checkpoint_id}/replay", response_model=None)
    def replay_session_checkpoint(
        checkpoint_id: str,
        scope: AgentCheckpointAccessRequest,
    ) -> dict[str, object]:
        # Replay is deliberately data-only. It never re-enters the agent loop.
        core.read_agent_checkpoint_or_raise(checkpoint_id=checkpoint_id, scope=scope)
        try:
            replay = runtime.replay_agent_turn_checkpoint(
                checkpoint_id=checkpoint_id,
                workspace_id=scope.workspace_id,
                session_id=scope.session_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Checkpoint access was denied.") from exc
        if replay is None:
            raise HTTPException(status_code=404, detail="Checkpoint was not found for this workspace.")
        return replay

    @router.post("/session/checkpoints/{checkpoint_id}/resume", response_model=None)
    def resume_session_checkpoint(
        checkpoint_id: str,
        scope: AgentCheckpointAccessRequest,
    ) -> dict[str, object]:
        # Resume prepares the saved local thread; the next user turn is explicit.
        core.read_agent_checkpoint_or_raise(checkpoint_id=checkpoint_id, scope=scope)
        try:
            resume = runtime.prepare_agent_turn_resume(
                checkpoint_id=checkpoint_id,
                workspace_id=scope.workspace_id,
                session_id=scope.session_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Checkpoint access was denied.") from exc
        if resume is None:
            raise HTTPException(status_code=404, detail="Checkpoint was not found for this workspace.")
        return resume

    @router.post("/turn", response_model=None)
    async def turn(payload: dict) -> object:
        try:
            request = TurnRequest.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=exc.errors(include_context=False),
            ) from exc
        core.reject_blank_coach_message(request)
        try:
            request = TurnRequest.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=exc.errors(include_context=False),
            ) from exc
        original_intent = request.intent
        request = _normalize_resource_turn_request(request)
        workspace_id = core.current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        # Mid-session host re-attest so trust flips apply before authority/capability.
        core.apply_host_workspace_trust_attestation(workspace_id, payload)
        # Fail-closed: claim before execute/unusable honesty so same request_id
        # cannot double-append. Waiters get shared result + honesty overlay.
        request_id = str(request.request_id or "").strip()
        request_key = (workspace_id, str(request.session_id or "").strip(), request_id)
        owner_future: asyncio.Future | None = None

        def _overlay_completed_turn_response(cached_response: dict[str, object]) -> dict[str, object]:
            state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
            snapshot = state.snapshot
            pressure_blocks = core.pressure_without_live_object_blocks_mint(
                workspace_id,
                snapshot=snapshot,
                current_task=snapshot.current_task,
                current_plan=snapshot.plan,
                message=request.message,
            )
            streak_blocks = core.streak_without_live_object_blocks_mint(
                workspace_id,
                snapshot=snapshot,
                current_task=snapshot.current_task,
                current_plan=snapshot.plan,
            )
            live_status = (
                snapshot.plan_runtime_status
                if isinstance(snapshot.plan_runtime_status, dict)
                else {}
            )
            leftover_plan, leftover_runtime = core.leftover_runtime_for_workspace(workspace_id)
            leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
            live_for_attach = bool(leftover_runtime) and leftover_formal_plan_is_live_for_fill(
                plan=snapshot.plan or leftover_plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            recovered_leftover = False
            if not live_for_attach:
                if leftover_plan is not None:
                    recovered_leftover = True
                elif live_status.get("recovered") is True and snapshot.plan is None:
                    recovered_leftover = True
            stamped = overlay_session_response_honesty_stamps(
                cached_response,
                pressure_blocks=pressure_blocks,
                streak_blocks=streak_blocks,
                recovered_leftover=recovered_leftover,
            )
            if stamped is not cached_response:
                with core.completed_session_requests_guard:
                    core.completed_session_requests[request_key] = stamped
            return stamped

        def _finish_turn_response(payload_map: dict[str, object]) -> dict[str, object]:
            if not request_id:
                return payload_map
            return publish_session_request_singleflight(
                request_key,
                payload_map,
                completed=core.completed_session_requests,
                inflight=core.inflight_session_requests,
                guard=core.completed_session_requests_guard,
            )

        def _owner_task_cleanup(task: asyncio.Task) -> None:
            if owner_future is None or owner_future.done():
                return
            with core.completed_session_requests_guard:
                core.inflight_session_requests.pop(request_key, None)
                cached = core.completed_session_requests.get(request_key)
            if cached is not None:
                owner_future.set_result(cached)
                return
            if task.cancelled():
                owner_future.set_exception(asyncio.CancelledError())
                return
            try:
                exc = task.exception()
            except asyncio.CancelledError as cancelled:
                owner_future.set_exception(cancelled)
                return
            if exc is not None:
                owner_future.set_exception(exc)
                return
            owner_future.set_exception(
                RuntimeError("turn request completed without publishing a payload")
            )

        if request_id:
            kind, cached_response, shared_future = claim_session_request_singleflight(
                request_key,
                completed=core.completed_session_requests,
                inflight=core.inflight_session_requests,
                guard=core.completed_session_requests_guard,
            )
            if kind == "wait":
                assert shared_future is not None
                shared_payload = await shared_future
                return _overlay_completed_turn_response(shared_payload)
            if kind == "cached":
                assert cached_response is not None
                return _overlay_completed_turn_response(cached_response)
            owner_future = shared_future
            current_task = asyncio.current_task()
            if current_task is not None:
                current_task.add_done_callback(_owner_task_cleanup)

        response, artifacts, _ = await coach_support.execute_turn(core.coach_support_deps, request, payload)
        if isinstance(response, SessionMessageResponse):
            response.snapshot.memory = core.repair_guided_lane_memory_snapshot_for_response(
                runtime.memory_service.snapshot(workspace_id),
                scenario=response.coach_turn.scenario if response.coach_turn else None,
                response_language=request.response_language,
                learner_message=request.message,
            )
            workspace_memory = (
                response.snapshot.memory.workspace
                if isinstance(response.snapshot.memory.workspace, dict)
                else {}
            )
            coach_support.hydrate_snapshot(core.coach_support_deps,
                response.snapshot,
                preserve_turn_coaching_state=True,
                response_language=request.response_language
                or str(workspace_memory.get("response_language") or "").strip()
                or None,
                answer_mode=(
                    str(workspace_memory.get("answer_mode") or "").strip()
                    or (
                        response.snapshot.profile.answer_policy
                        if response.snapshot.profile is not None
                        else None
                    )
                ),
                message=request.message,
                session_workspace_id=workspace_id,
            )
        response_data = core.json_object_payload(response)
        response_data["artifacts"] = artifacts
        response_data["intent"] = original_intent
        return _finish_turn_response(
            core.attach_operation_reliability(
                response_data,
                phase="acked",
                outcome=core.reliability_outcome_from_payload(response_data),
                request_id=request_id or None,
            )
        )

    @router.post("/stream/cancel")
    async def cancel_stream(payload: dict) -> dict[str, object]:
        """Request cooperative cancellation for one active SSE stream."""

        stream_id = core.resolve_stream_id(payload)
        requested = core.request_stream_cancellation(stream_id)
        return {
            "ok": requested,
            "stream_id": stream_id,
            "status": "cancellation_requested" if requested else "not_found",
        }

    @router.post("/session/steer")
    async def session_steer(payload: dict) -> dict[str, object]:
        """Queue a follow-up that the in-flight agent loop injects before the next LLM call."""

        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        text = str(payload.get("message") or payload.get("text") or "").strip()
        if not session_id or not text:
            raise HTTPException(status_code=400, detail="session_id and message are required.")
        queued = runtime.enqueue_steer_message(session_id, text)
        return {"ok": queued, "session_id": session_id, "queued": queued}

    @router.post("/session/message/stream")
    async def session_message_stream(payload: dict, http_request: Request):
        core._stream_snapshot_fields.set(
            "slim" if str(payload.get("fields") or "") == "slim" else "full"
        )

        """Streaming coaching response via SSE."""
        stream_id = core.resolve_stream_id(payload)
        request = SessionMessageRequest.model_validate(payload)
        workspace_id = core.current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        # Mid-session host re-attest so trust flips apply before authority/capability.
        core.apply_host_workspace_trust_attestation(workspace_id, payload)
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        profile = core.resolved_profile(state.workspace_id)
        raw_requested_answer_mode = str(
            payload.get("answer_mode") or payload.get("answerMode") or ""
        ).strip()
        saved_answer_mode = str(core.workspace_preferences(workspace_id).get("answer_mode") or "").strip()
        request = core.request_with_workspace_defaults(
            request,
            workspace_id=workspace_id,
            profile=profile,
        )
        profile = core.profile_with_teaching_style(profile, request.teaching_style)
        coaching_service = runtime.provider_service
        override_config = core.provider_config_from_payload(payload)
        api_key_override = core.provider_api_key_from_payload(payload)
        if override_config is not None or api_key_override is not None:
            coaching_service = runtime.provider_service_for(override_config, api_key_override)
        core.ensure_coach_provider_ready(
            coaching_service,
            response_language=request.response_language,
        )
        # Fail-closed: claim before unusable early-return so same request_id cannot
        # double-run honesty SSE. Live SSE is not fan-out-shared; waiters get
        # complete-frame replay with honesty stamps after owner publish.
        request_id = str(request.request_id or "").strip()
        request_key = (workspace_id, str(request.session_id or "").strip(), request_id)

        def _overlay_completed_session_response(cached_response: dict[str, object]) -> dict[str, object]:
            overlay_state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
            snapshot = overlay_state.snapshot
            pressure_blocks = core.pressure_without_live_object_blocks_mint(
                workspace_id,
                snapshot=snapshot,
                current_task=snapshot.current_task,
                current_plan=snapshot.plan,
                message=request.message,
            )
            streak_blocks = core.streak_without_live_object_blocks_mint(
                workspace_id,
                snapshot=snapshot,
                current_task=snapshot.current_task,
                current_plan=snapshot.plan,
            )
            live_status = (
                snapshot.plan_runtime_status
                if isinstance(snapshot.plan_runtime_status, dict)
                else {}
            )
            leftover_plan, leftover_runtime = core.leftover_runtime_for_workspace(workspace_id)
            leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
            live_for_attach = bool(leftover_runtime) and leftover_formal_plan_is_live_for_fill(
                plan=snapshot.plan or leftover_plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            recovered_leftover = False
            if not live_for_attach:
                if leftover_plan is not None:
                    recovered_leftover = True
                elif live_status.get("recovered") is True and snapshot.plan is None:
                    recovered_leftover = True
            stamped = overlay_session_response_honesty_stamps(
                cached_response,
                pressure_blocks=pressure_blocks,
                streak_blocks=streak_blocks,
                recovered_leftover=recovered_leftover,
            )
            if stamped is not cached_response:
                with core.completed_session_requests_guard:
                    core.completed_session_requests[request_key] = stamped
            return stamped

        def _publish_stream_session_response(payload: dict[str, object]) -> dict[str, object]:
            if not request_id:
                return payload
            return publish_session_request_singleflight(
                request_key,
                payload,
                completed=core.completed_session_requests,
                inflight=core.inflight_session_requests,
                guard=core.completed_session_requests_guard,
            )

        def _fail_stream_session_singleflight(error: BaseException) -> None:
            if not request_id:
                return
            wrapped = error if isinstance(error, Exception) else RuntimeError(str(error) or "session message failed")
            fail_session_request_singleflight(
                request_key,
                wrapped,
                inflight=core.inflight_session_requests,
                guard=core.completed_session_requests_guard,
            )

        async def _waiter_stream_generate(
            kind: Literal["wait", "cached"],
            cached_response: dict[str, object] | None,
            shared_future: asyncio.Future | None,
        ):
            try:
                shared_payload: dict[str, object]
                if kind == "wait":
                    assert shared_future is not None
                    shared_payload = cast("dict[str, object]", await shared_future)
                else:
                    assert cached_response is not None
                    shared_payload = cached_response
                stamped = _overlay_completed_session_response(shared_payload)
                yield core.sse_complete_frame(
                    tokens=0,
                    response_data=stamped,
                    stream_id=stream_id,
                    request_id=request_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Owner fail_inflight leaves no complete frame — still overlay honesty
                # stamps onto a failure complete so waiters do not drop recovered/
                # pressure/streak after cancel or mid-turn abort.
                failure_payload = core.attach_operation_reliability(
                    {},
                    phase="acked",
                    outcome="failure",
                    request_id=request_id or None,
                )
                stamped = _overlay_completed_session_response(failure_payload)
                yield core.stream_status_event("failed", stream_id)
                yield core.stream_status_event("acked", stream_id)
                yield (
                    "event: error\n"
                    f"data: {json.dumps({'error': redact_provider_error(exc, api_key=getattr(coaching_service, '_api_key', None)), 'stream_id': stream_id, 'terminal': True})}\n\n"
                )
                yield core.sse_complete_frame(
                    tokens=0,
                    response_data=stamped,
                    stream_id=stream_id,
                    outcome="failure",
                    request_id=request_id,
                    provider_failure_detected=True,
                )

        if request_id:
            kind, cached_response, shared_future = claim_session_request_singleflight(
                request_key,
                completed=core.completed_session_requests,
                inflight=core.inflight_session_requests,
                guard=core.completed_session_requests_guard,
            )
            if kind in ("wait", "cached"):
                # Do not register stream_id — owner already holds cancellation slot.
                return StreamingResponse(
                    _waiter_stream_generate(kind, cached_response, shared_future),
                    media_type="text/event-stream",
                )

        provider_live_usable = core.provider_is_live_usable(coaching_service, payload)
        if not provider_live_usable:
            turn_request = core.turn_request_from_stream_payload(payload, intent="coach")
            core.register_stream_cancellation(stream_id)
            return StreamingResponse(
                core.honest_unusable_provider_stream(
                    turn_request,
                    payload,
                    stream_id=stream_id,
                    original_intent="coach",
                    http_request=http_request,
                    publish_complete=_publish_stream_session_response if request_id else None,
                    fail_inflight=_fail_stream_session_singleflight if request_id else None,
                ),
                media_type="text/event-stream",
            )
        try:
            core.ensure_streaming_ready(coaching_service, request.response_language)
            core.ensure_agent_tools_ready(request, coaching_service)

            use_agent_stream = _resolve_agent_loop_enabled(
                request, cast(ProviderService, coaching_service), stream=True, payload=payload
            )
            attachment_delivery = core.describe_request_attachment_delivery(
                request,
                coaching_service,
                use_agent_loop=use_agent_stream,
            )
            attachments_payload = [a.model_dump() for a in request.attachments]
            stream_recovery_requested = core.resource_contract_stream_recovery_requested(request.message)
            learning_project_state = core.workspace_learning_project_state(state.workspace_id)
        except BaseException as exc:
            # Same singleflight fail-closed rule as /turn/stream (T-0033).
            _fail_stream_session_singleflight(exc)
            raise
        if learning_project_state.get("prompt_status") == "pending" and (
            core.message_confirms_learning_project_folder(request.message)
            or core.message_rejects_learning_project_folder(request.message)
        ):
            stream_recovery_requested = True

        async def stream_cancelled() -> bool:
            if core.stream_cancellation_requested(stream_id):
                return True
            try:
                return await http_request.is_disconnected()
            except RuntimeError:
                # Test clients and a few ASGI adapters do not expose a live
                # receive channel after the response starts.
                return False

        # Pyright gives up on this oversized async generator ("code is too
        # complex to analyze") and then misreads it as a coroutine, so the
        # complexity bailout is silenced here and the StreamingResponse call
        # site pins the async-iterator type explicitly.
        async def generate():  # pyright: ignore[reportGeneralTypeIssues]
            token_count = 0
            streamed_reply_content = ""
            pending_streamed_reply_content = ""
            stream_user_message: ChatMessage | None = None
            stream_assistant_message_ids: set[str] = set()
            stream_committed = False
            stream_failed = False
            stream_singleflight_published = False
            preexisting_assistant_ids = {
                message.id
                for message in state.snapshot.messages
                if message.role == "assistant"
            }

            async def _abort_fail_closed(*, error_detail: object | None = None):
                """Emit failed->acked and publish failure complete so same request_id cannot remint."""
                nonlocal stream_failed, stream_singleflight_published
                stream_failed = True
                failure_payload: dict[str, object] = core.attach_operation_reliability(
                    {},
                    phase="acked",
                    outcome="failure",
                    request_id=request_id or None,
                )
                if request_id and not stream_singleflight_published:
                    failure_payload = _publish_stream_session_response(failure_payload)
                    stream_singleflight_published = True
                yield core.stream_status_event("failed", stream_id)
                if error_detail is not None:
                    yield (
                        "event: error\n"
                        f"data: {json.dumps({'error': error_detail, 'stream_id': stream_id, 'terminal': True})}\n\n"
                    )
                yield core.stream_status_event("acked", stream_id)
                yield core.sse_complete_frame(
                    tokens=token_count,
                    response_data=failure_payload,
                    stream_id=stream_id,
                    outcome="failure",
                    request_id=request_id or None,
                    provider_failure_detected=True,
                )

            async def _abort_interrupted():
                """Client disconnected: no listener remains for a terminal frame.

                Mint no failure complete so the user turn stays recoverable as
                interrupted on reconnect instead of looking conclusively failed.
                """
                yield core.stream_status_event("cancelled", stream_id)

            async def _abort_for_cancellation():
                """Explicit /stream/cancel stays fail-closed; a client disconnect only interrupts."""
                if core.stream_cancellation_requested(stream_id):
                    async for _closed_frame in _abort_fail_closed():
                        yield _closed_frame
                    return
                async for _abort_frame in _abort_interrupted():
                    yield _abort_frame

            try:
                if await stream_cancelled():
                    async for _abort_frame in _abort_for_cancellation():
                        yield _abort_frame
                    return
                yield core.stream_status_event("preparing_context", stream_id)
                stream_user_message, _ = core.prepare_stream_user_message(
                    state=state,
                    request=request,
                    profile=profile,
                    attachment_delivery=attachment_delivery,
                    stream_id=stream_id,
                )
                core.safe_activate_training_card_from_coach_request(
                    workspace_id=state.workspace_id,
                    snapshot=state.snapshot,
                    message=request.message,
                    current_file=request.current_file,
                    response_language=request.response_language,
                    provider_service_override=coaching_service,
                )
                state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
                coach_turn: CoachTurnPayload = coach_support.resolve_coach_turn(core.coach_support_deps, 
                    state=state,
                    profile=profile,
                    request=request,
                    message=request.message,
                    coaching_service=coaching_service,
                    current_task=state.snapshot.current_task,
                    current_plan=state.snapshot.plan,
                    current_evaluation=state.snapshot.evaluation,
                )
                scenario = str(coach_turn.get("scenario") or "general")
                if core.guarantee_guided_learn_first_training_card(
                    workspace_id=state.workspace_id,
                    scenario=str(coach_turn["scenario"] or ""),
                    message=request.message,
                    current_file=request.current_file,
                    response_language=request.response_language,
                    active_thread=state.snapshot.memory.active_thread,
                    requested_answer_mode=raw_requested_answer_mode,
                    saved_answer_mode=saved_answer_mode,
                    profile=profile,
                ):
                    state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
                guided_training_prefers_local_reply = core.should_bypass_agent_loop_for_guided_training(
                    workspace_id=state.workspace_id,
                    scenario=str(coach_turn["scenario"] or scenario),
                    message=request.message,
                    active_view=request.active_view,
                    requested_answer_mode=raw_requested_answer_mode,
                    saved_answer_mode=saved_answer_mode,
                    profile=profile,
                )
                guided_training_local_reply = (
                    core.build_guided_training_visible_fallback(
                        workspace_id=state.workspace_id,
                        response_language=request.response_language,
                    )
                    if guided_training_prefers_local_reply
                    else None
                )
                auto_resource_events = core.auto_resource_lookup_tool_events(
                    dict(coach_turn["coach_context"]),
                    request.message,
                )

                full_content = ""
                agent_summary: str | None = None
                agent_next_step: str | None = None
                agent_stop_reason: str | None = None
                agent_decision: str | None = None
                agent_blocker: str | None = None
                agent_teaching_note: str | None = None
                agent_resume_thread: str | None = None
                agent_confidence: str | None = None
                agent_evidence: list[object] | None = None
                agent_tool_events: list[dict[str, object]] = []
                agent_steps: list[dict[str, object]] = []
                provider_failure_detected = False
                final_agent_meta: dict[str, object] = {}
                if guided_training_local_reply is None:
                    yield core.stream_status_event("requesting_model", stream_id)
                if guided_training_local_reply is not None:
                    full_content, updated_coach_turn, guided_meta = core.apply_guided_training_visible_fallback(
                        coach_turn=core.coach_turn_mapping(coach_turn),
                        fallback=guided_training_local_reply,
                    )
                    coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
                    final_agent_meta.update(guided_meta)
                    token_count += 1
                elif use_agent_stream and not guided_training_prefers_local_reply:
                    agent_context = dict(coach_turn["coach_context"])
                    agent_context["__runtime__"] = runtime
                    agent_context["workspace_id"] = workspace_id
                    agent_context["session_id"] = state.session_id
                    agent_context["stream_cancel_event"] = core.stream_cancellation_events.get(stream_id)
                    async for event in coaching_service.coaching_reply_agentic_stream(
                        profile,
                        request.message,
                        request.current_file.model_dump() if request.current_file else None,
                        response_language=request.response_language,
                        answer_mode=request.answer_mode,
                        coach_context=agent_context,
                        attachments=attachments_payload,
                        protocol=getattr(coaching_service._config, "protocol", None) if coaching_service._config else None,
                        history=core.build_conversation_history(
                            state.snapshot.messages,
                            drop_latest_user=True,
                        ),
                        ):
                            if await stream_cancelled():
                                async for _abort_frame in _abort_for_cancellation():
                                    yield _abort_frame
                                return
                            event_type = str(event.get("type") or "")
                            if event_type == "text":
                                delta = str(event.get("delta") or "")
                                if delta:
                                    full_content += delta
                                    token_count += 1
                                    if event.get("safe_to_stream") is True and (
                                        not core.requires_formal_plan_commit(request)
                                        or core.formal_plan_commit_tool_succeeded(agent_tool_events)
                                    ):
                                        visible_delta, pending_streamed_reply_content = core.safe_stream_delta(
                                            pending_streamed_reply_content,
                                            delta,
                                            full_content,
                                        )
                                        if visible_delta:
                                            streamed_reply_content += visible_delta
                                            yield f"data: {json.dumps({'chunk': visible_delta})}\n\n"
                            elif event_type == "tool_call":
                                agent_tool_events.append(dict(event))
                                yield core.stream_frame("tool_call", event, stream_id)
                            elif event_type == "tool_result":
                                agent_tool_events.append(dict(event))
                                yield core.stream_frame("tool_result", event, stream_id)
                            elif event_type == "step":
                                agent_steps.append(dict(event))
                                yield core.stream_frame("step", event, stream_id)
                            elif event_type == "final":
                                final_content = str(event.get("content") or "")
                                if final_content:
                                    full_content = final_content
                                agent_summary = event.get("summary")
                                agent_next_step = event.get("next_step")
                                agent_stop_reason = event.get("stop_reason")
                                agent_decision = event.get("decision")
                                agent_blocker = event.get("blocker")
                                agent_teaching_note = event.get("teaching_note")
                                agent_resume_thread = event.get("resume_thread")
                                agent_confidence = event.get("confidence")
                                agent_evidence = (
                                    list(event.get("evidence") or [])
                                    if isinstance(event.get("evidence"), list)
                                    else None
                                )
                            elif event_type == "error":
                                async for _abort_frame in _abort_fail_closed(
                                    error_detail=redact_provider_error(
                                        event.get("detail"),
                                        api_key=getattr(coaching_service, "_api_key", None),
                                    ),
                                ):
                                    yield _abort_frame
                                return
                    if full_content:
                        full_content = coaching_service.finalize_coaching_reply(
                            full_content,
                            profile=profile,
                            message=request.message,
                            current_file=request.current_file.model_dump() if request.current_file else None,
                            response_language=request.response_language,
                            answer_mode=request.answer_mode,
                            coach_context=dict(coach_turn["coach_context"]),
                        )
                    if not agent_resume_thread and (agent_summary or agent_next_step):
                        agent_resume_thread = core.build_resume_thread_text(
                            str(agent_summary or "").strip(),
                            str(agent_next_step or "").strip(),
                            response_language=request.response_language,
                        )
                    if not full_content:
                        local_sequence_fallback = core.build_local_sequence_visible_fallback(
                            coach_context=dict(coach_turn["coach_context"]),
                            response_language=request.response_language,
                        )
                        if local_sequence_fallback is not None:
                            full_content = local_sequence_fallback["reply"]
                            coaching_service.clear_last_reply_override()
                            agent_summary = agent_summary or local_sequence_fallback["summary"]
                            agent_next_step = agent_next_step or local_sequence_fallback["next_step"]
                            agent_teaching_note = (
                                agent_teaching_note or local_sequence_fallback["teaching_note"]
                            )
                            agent_resume_thread = (
                                agent_resume_thread or local_sequence_fallback["resume_thread"]
                            )
                            final_agent_meta["local_sequence_fallback"] = True
                            if str(agent_stop_reason or "").strip() == "empty_response":
                                final_agent_meta["fell_back"] = True
                                final_agent_meta["recovered_stop_reason"] = "empty_response"
                                final_agent_meta["stop_reason"] = "completed"
                        else:
                            full_content = coaching_service._fallback_empty_reply(
                                profile=profile,
                                message=request.message,
                                current_file=(
                                    request.current_file.model_dump() if request.current_file else None
                                ),
                                response_language=request.response_language,
                                answer_mode=request.answer_mode,
                                coach_context=dict(coach_turn["coach_context"]),
                            )
                        token_count += 1
                    updated_coach_turn = core.merge_agent_finalize_into_coach_turn(
                        core.coach_turn_mapping(coach_turn),
                        summary=agent_summary,
                        next_step=agent_next_step,
                        blocker=agent_blocker,
                        resume_thread=agent_resume_thread,
                        decision=agent_decision,
                        teaching_note=agent_teaching_note,
                        confidence=agent_confidence,
                        evidence=agent_evidence,
                    )
                    coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
                else:
                    try:
                        async for chunk in coaching_service.coaching_reply_stream(
                            profile,
                            request.message,
                            request.current_file.model_dump() if request.current_file else None,
                            response_language=request.response_language,
                            answer_mode=request.answer_mode,
                            coach_context=dict(coach_turn["coach_context"]),
                            history=core.build_conversation_history(
                                state.snapshot.messages,
                                drop_latest_user=True,
                            ),
                            cancel_event=core.stream_cancellation_events.get(stream_id),
                        ):
                            if await stream_cancelled():
                                async for _abort_frame in _abort_for_cancellation():
                                    yield _abort_frame
                                return
                            full_content += chunk
                            token_count += 1
                            visible_chunk, pending_streamed_reply_content = core.safe_stream_delta(
                                pending_streamed_reply_content,
                                chunk,
                                full_content,
                            )
                            if visible_chunk and not core.requires_formal_plan_commit(request):
                                streamed_reply_content += visible_chunk
                                yield f"data: {json.dumps({'chunk': visible_chunk})}\n\n"
                    except Exception:
                        if not stream_recovery_requested or streamed_reply_content or full_content:
                            raise
                        # A grounded resource/project confirmation may recover through
                        # the existing synchronous contract only after the live stream
                        # failed before any visible provider text was emitted.
                        # Nested /session/message must not re-claim this stream's request_id
                        # (owner future would deadlock waiters + this generator).
                        nested_payload = dict(payload)
                        nested_payload.pop("request_id", None)
                        nested_payload.pop("requestId", None)
                        response_data = await core.session_message(nested_payload)
                        response_payload = (
                            {str(key): value for key, value in response_data.items()}
                            if isinstance(response_data, dict)
                            else core.json_object_payload(response_data)
                        )
                        if "agent" not in response_payload and isinstance(
                            response_payload.get("agent_meta"),
                            dict,
                        ):
                            response_payload["agent"] = response_payload["agent_meta"]
                        reply_record = response_payload.get("reply")
                        reply_content = (
                            str(reply_record.get("content") or "").strip()
                            if isinstance(reply_record, dict)
                            else ""
                        )
                        if reply_content:
                            token_count += 1
                            yield f"data: {json.dumps({'chunk': reply_content})}\n\n"
                        response_payload = _publish_stream_session_response(response_payload)
                        stream_singleflight_published = True
                        yield core.sse_complete_frame(
                            tokens=token_count,
                            response_data=response_payload,
                            stream_id=stream_id,
                            provider_failure_detected=True,
                        )
                        return
                    stream_finalization = coaching_service.consume_stream_finalization()
                    if stream_finalization is not None:
                        full_content = stream_finalization[1]
                    else:
                        full_content = coaching_service.finalize_coaching_reply(
                            full_content,
                            profile=profile,
                            message=request.message,
                            current_file=request.current_file.model_dump() if request.current_file else None,
                            response_language=request.response_language,
                            answer_mode=request.answer_mode,
                            coach_context=dict(coach_turn["coach_context"]),
                        )

                if await stream_cancelled():
                    async for _abort_frame in _abort_for_cancellation():
                        yield _abort_frame
                    return
                provider_empty_reply_override = core.consume_provider_empty_reply_override(
                    coaching_service=coaching_service,
                    snapshot=state.snapshot,
                    coach_turn=core.coach_turn_mapping(coach_turn),
                    response_language=request.response_language,
                    assistant_content=full_content,
                )
                if provider_empty_reply_override is not None:
                    provider_failure_detected = True
                    full_content, updated_coach_turn, override_meta = provider_empty_reply_override
                    coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
                    final_agent_meta.update(override_meta)
                else:
                    provider_failure_override = core.consume_provider_reply_failure_override(
                        coaching_service=coaching_service,
                        snapshot=state.snapshot,
                        coach_turn=core.coach_turn_mapping(coach_turn),
                        message=request.message,
                        response_language=request.response_language,
                        workspace_id=state.workspace_id,
                    )
                    if provider_failure_override is not None:
                        provider_failure_detected = True
                        full_content, updated_coach_turn, override_meta = provider_failure_override
                        coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
                        final_agent_meta.update(override_meta)

                if not provider_failure_detected:
                    visible_agent_meta = {
                        "stop_reason": agent_stop_reason,
                        "summary": agent_summary,
                        "next_step": agent_next_step,
                        "decision": agent_decision,
                        "blocker": agent_blocker,
                        "teaching_note": agent_teaching_note,
                        "resume_thread": agent_resume_thread,
                        "confidence": agent_confidence,
                        "evidence": agent_evidence,
                        "steps": agent_steps,
                        "tool_events": agent_tool_events,
                        "agentic": use_agent_stream and not guided_training_prefers_local_reply,
                        **final_agent_meta,
                    }
                    full_content, updated_coach_turn, final_agent_meta, _guided_lane_repaired = (
                        core.apply_guided_lane_visible_fallback(
                            reply=full_content,
                            scenario=str(coach_turn.get("scenario") or scenario),
                            learner_message=request.message,
                            response_language=request.response_language,
                            coach_turn=core.coach_turn_mapping(coach_turn),
                            agent_meta=visible_agent_meta,
                        )
                    )
                    coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
                    repaired_summary = final_agent_meta.get("summary")
                    agent_summary = repaired_summary if isinstance(repaired_summary, str) else None
                    repaired_next_step = final_agent_meta.get("next_step")
                    agent_next_step = (
                        repaired_next_step if isinstance(repaired_next_step, str) else None
                    )
                    repaired_decision = final_agent_meta.get("decision")
                    agent_decision = repaired_decision if isinstance(repaired_decision, str) else None
                    repaired_blocker = final_agent_meta.get("blocker")
                    agent_blocker = repaired_blocker if isinstance(repaired_blocker, str) else None
                    repaired_teaching_note = final_agent_meta.get("teaching_note")
                    agent_teaching_note = (
                        repaired_teaching_note if isinstance(repaired_teaching_note, str) else None
                    )
                    repaired_resume_thread = final_agent_meta.get("resume_thread")
                    agent_resume_thread = (
                        repaired_resume_thread if isinstance(repaired_resume_thread, str) else None
                    )
                    repaired_confidence = final_agent_meta.get("confidence")
                    agent_confidence = (
                        repaired_confidence if isinstance(repaired_confidence, str) else None
                    )
                    repaired_evidence = final_agent_meta.get("evidence")
                    agent_evidence = (
                        list(repaired_evidence)
                        if isinstance(repaired_evidence, list)
                        else None
                    )
                    core.ensure_explicit_training_card_after_coach_reply(
                        state=state,
                        message=request.message,
                        current_file=request.current_file,
                        response_language=request.response_language,
                        fallback_scenario=str(coach_turn.get("scenario") or ""),
                        force_training_card=core.auto_preference_requests_training_card(
                            request.message,
                            requested_scenario=str(coach_turn.get("scenario") or scenario),
                            requested_answer_mode=raw_requested_answer_mode,
                            saved_answer_mode=saved_answer_mode,
                            profile=profile,
                        )
                        or core.auto_lane_learn_first_force_training_card(
                            request.message,
                            requested_scenario=str(coach_turn.get("scenario") or scenario),
                            requested_answer_mode=raw_requested_answer_mode,
                            saved_answer_mode=saved_answer_mode,
                            profile=profile,
                        ),
                        provider_service_override=coaching_service,
                    )

                if await stream_cancelled():
                    async for _abort_frame in _abort_for_cancellation():
                        yield _abort_frame
                    return
                grounding_decision = await core.resolve_turn_grounding_async(
                    coach_turn_payload=coach_turn,
                    reply_content=full_content,
                    request=request,
                    agent_meta=final_agent_meta if isinstance(final_agent_meta, dict) else None,
                    history_text=core.turn_history_text(state.snapshot),
                    coaching_service=coaching_service,
                )
                final_agent_meta = core.apply_grounding_decision(
                    coach_turn_payload=coach_turn,
                    decision=grounding_decision,
                    agent_meta=final_agent_meta if isinstance(final_agent_meta, dict) else None,
                ) or final_agent_meta
                # T-0048: repair a generic finalize step BEFORE the reflection
                # persists, so the memory thread and the shipped stream step
                # match what build_session_response will surface (its repair
                # alone runs after this persist).
                coach_turn = core.repair_generic_finalize_next_step(
                    full_content,
                    final_agent_meta if isinstance(final_agent_meta, dict) and final_agent_meta else None,
                    coach_turn,
                    response_language=request.response_language,
                ) or coach_turn
                coach_support.persist_turn_reflection(core.coach_support_deps,
                    workspace_id=workspace_id,
                    session_id=state.session_id,
                    user_message=request.message,
                    scenario=str(coach_turn["scenario"]),
                    response_language=request.response_language,
                    answer_mode=core.answer_mode_preference_for_persistence(
                        raw_requested_answer_mode,
                        saved_answer_mode,
                        request.answer_mode,
                        profile.answer_policy if profile else None,
                    ),
                    coach_defaults=request.coach_defaults,
                    coach_turn_data=core.coach_turn_mapping(coach_turn),
                    grounding_decision=grounding_decision,
                    stop_reason=str(final_agent_meta.get("stop_reason") or ""),
                    recovered_stop_reason=str(final_agent_meta.get("recovered_stop_reason") or ""),
                    local_sequence_fallback=bool(final_agent_meta.get("local_sequence_fallback")),
                )
                core.persist_recovered_plan_resume_after_turn(
                    workspace_id=workspace_id,
                    request=request,
                    reply_content=full_content,
                    agent_meta=final_agent_meta if isinstance(final_agent_meta, dict) else None,
                    coach_context=coach_turn.get("coach_context") if isinstance(coach_turn, dict) else None,
                    recovered_status=state.snapshot.plan_runtime_status
                    if isinstance(state.snapshot.plan_runtime_status, dict)
                    else None,
                )
                if not provider_failure_detected:
                    core.persist_external_references_as_background(
                        workspace_id=workspace_id,
                        scenario=str(coach_turn["scenario"]),
                        coach_turn_data=core.coach_turn_mapping(coach_turn),
                    )
                state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
                state.snapshot.profile = runtime.repository.get_profile(workspace_id) or profile
                runtime.hydrate_plan_context(state.snapshot, workspace_id)
                coach_support.hydrate_snapshot(core.coach_support_deps,
                    state.snapshot,
                    response_language=request.response_language,
                    answer_mode=request.answer_mode or (profile.answer_policy if profile else None),
                    scenario=str(coach_turn["scenario"]),
                    learner_signal=str(coach_turn["learner_signal"]),
                    message=request.message,
                    session_workspace_id=workspace_id,
                )

                if use_agent_stream and not guided_training_prefers_local_reply:
                    stream_agent_meta = {
                        "stop_reason": agent_stop_reason,
                        "summary": agent_summary,
                        "next_step": agent_next_step,
                        "decision": agent_decision,
                        "blocker": agent_blocker,
                        "teaching_note": agent_teaching_note,
                        "resume_thread": agent_resume_thread,
                        "confidence": agent_confidence,
                        "evidence": agent_evidence,
                        "steps": agent_steps,
                        "tool_events": agent_tool_events,
                        "agentic": True,
                        **(core.normalize_attachment_delivery_payload(attachment_delivery) or {}),
                    }
                    final_agent_meta = merge_stream_agent_metadata(
                        final_agent_meta, stream_agent_meta,
                        preserve_failure=provider_failure_detected,
                    )
                if core.should_attach_auto_resource_events(final_agent_meta):
                    final_agent_meta = core.apply_auto_resource_agent_evidence(
                        final_agent_meta,
                        auto_resource_events,
                    )
                response_data = core.json_object_payload(
                    coach_support.build_session_response(core.coach_support_deps, 
                        state=state,
                        request=request,
                        reply_content=full_content,
                        artifacts=dict(coach_turn["artifacts"]),
                        suggested_actions=list(coach_turn["suggested_actions"]),
                        scenario=str(coach_turn["scenario"]),
                        learner_signal=str(coach_turn["learner_signal"]),
                        coach_turn_data=core.coach_turn_mapping(coach_turn),
                        agent_meta=final_agent_meta or None,
                        attachment_delivery=attachment_delivery,
                    )
                )
                reply_record = response_data.get("reply")
                visible_content = (
                    str(reply_record.get("content") or "").strip()
                    if isinstance(reply_record, dict)
                    else ""
                )
                visible_delta = core.completion_stream_delta(streamed_reply_content, visible_content)
                if visible_delta:
                    token_count += 1
                    yield f"data: {json.dumps({'chunk': visible_delta})}\n\n"
                if final_agent_meta:
                    response_data["agent"] = final_agent_meta
                if await stream_cancelled():
                    if not core.stream_cancellation_requested(stream_id):
                        # Client disconnected: no listener remains for a terminal frame;
                        # leave the turn recoverable as interrupted, mint no fake complete.
                        yield core.stream_status_event("cancelled", stream_id)
                        return
                    # Built payload but aborted before commit: publish failure so same
                    # request_id cannot remint, waiters get stamped complete, not hang.
                    stream_failed = True
                    response_data = core.attach_operation_reliability(
                        response_data,
                        phase="acked",
                        outcome="failure",
                        request_id=request_id or None,
                    )
                    response_data = _publish_stream_session_response(response_data)
                    stream_singleflight_published = True
                    yield core.stream_status_event("failed", stream_id)
                    yield core.stream_status_event("acked", stream_id)
                    yield core.sse_complete_frame(
                        tokens=token_count,
                        response_data=response_data,
                        stream_id=stream_id,
                        outcome="failure",
                        request_id=request_id or None,
                        provider_failure_detected=True,
                    )
                    return
                stream_assistant_message_ids.update(
                    message.id
                    for message in state.snapshot.messages
                    if message.role == "assistant" and message.id not in preexisting_assistant_ids
                )
                runtime.save_session_state(state.session_id)
                stream_committed = True
                response_data = _publish_stream_session_response(response_data)
                stream_singleflight_published = True
                yield core.sse_complete_frame(
                    tokens=token_count,
                    response_data=response_data,
                    stream_id=stream_id,
                    provider_failure_detected=provider_failure_detected,
                )

            except asyncio.CancelledError:
                # Fail-closed: failed->acked + publish failure complete (no remint).
                logger.info("trainer_stream_cancelled", extra={"stream_id": stream_id})
                async for _abort_frame in _abort_fail_closed():
                    yield _abort_frame
                return
            except Exception as exc:
                async for _abort_frame in _abort_fail_closed(
                    error_detail=redact_provider_error(
                        exc,
                        api_key=getattr(coaching_service, "_api_key", None),
                    ),
                ):
                    yield _abort_frame
            finally:
                if request_id and not stream_singleflight_published:
                    fail_session_request_singleflight(
                        request_key,
                        RuntimeError(
                            "session stream failed"
                            if stream_failed
                            else "session stream completed without publishing a payload"
                        ),
                        inflight=core.inflight_session_requests,
                        guard=core.completed_session_requests_guard,
                    )
                core.finalize_stream_persistence(
                    state=state,
                    user_message=stream_user_message,
                    stream_id=stream_id,
                    committed=stream_committed,
                    assistant_message_ids=stream_assistant_message_ids,
                    stream_state=(
                        "completed"
                        if stream_committed
                        else ("failed" if stream_failed else "interrupted")
                    ),
                )
                core.unregister_stream_cancellation(stream_id)

        core.register_stream_cancellation(stream_id)
        return StreamingResponse(
            cast(AsyncIterator[bytes], generate()), media_type="text/event-stream"
        )

    @router.post("/turn/stream")
    async def turn_stream(payload: dict, http_request: Request):
        core._stream_snapshot_fields.set(
            "slim" if str(payload.get("fields") or "") == "slim" else "full"
        )

        stream_id = core.resolve_stream_id(payload)
        parsed_request = TurnRequest.model_validate(payload)
        if not isinstance(parsed_request, TurnRequest):
            raise TypeError("Turn stream payload did not produce a TurnRequest.")
        core.reject_blank_coach_message(parsed_request)
        request: TurnRequest = _normalize_resource_turn_request(parsed_request)
        original_intent = parsed_request.intent
        state: SessionState | None = None
        profile: UserProfile | None = None
        coaching_service: ProviderService | None = None
        use_agent_stream = False
        workspace_id = core.current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        # Mid-session host re-attest so trust flips apply before authority/capability.
        core.apply_host_workspace_trust_attestation(workspace_id, payload)
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        profile = core.resolved_profile(state.workspace_id)
        raw_requested_answer_mode = str(
            payload.get("answer_mode") or payload.get("answerMode") or ""
        ).strip()
        saved_answer_mode = str(
            core.workspace_preferences(workspace_id).get("answer_mode") or ""
        ).strip()
        request_with_defaults = core.request_with_workspace_defaults(
            request,
            workspace_id=workspace_id,
            profile=profile,
        )
        if not isinstance(request_with_defaults, TurnRequest):
            raise TypeError("Workspace defaults did not produce a TurnRequest.")
        request = request_with_defaults
        profile = core.profile_with_teaching_style(profile, request.teaching_style)
        # Validate every streaming lane before returning StreamingResponse.
        # Otherwise a formal Plan/tools request can be sent as HTTP 200 and
        # fail only after the SSE body has started, which makes capability
        # state look successful to the webview and prevents reliable recovery.
        coaching_service = core.build_coaching_service(payload)
        core.ensure_coach_provider_ready(
            coaching_service,
            response_language=request.response_language,
        )
        # Fail-closed: same request_id must not double-mint on /turn/stream.
        # Claim before unusable early-return; waiters get complete-frame + honesty overlay.
        request_id = str(request.request_id or "").strip()
        request_key = (workspace_id, str(request.session_id or "").strip(), request_id)

        def _overlay_completed_turn_response(cached_response: dict[str, object]) -> dict[str, object]:
            overlay_state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
            snapshot = overlay_state.snapshot
            pressure_blocks = core.pressure_without_live_object_blocks_mint(
                workspace_id,
                snapshot=snapshot,
                current_task=snapshot.current_task,
                current_plan=snapshot.plan,
                message=request.message,
            )
            streak_blocks = core.streak_without_live_object_blocks_mint(
                workspace_id,
                snapshot=snapshot,
                current_task=snapshot.current_task,
                current_plan=snapshot.plan,
            )
            live_status = (
                snapshot.plan_runtime_status
                if isinstance(snapshot.plan_runtime_status, dict)
                else {}
            )
            leftover_plan, leftover_runtime = core.leftover_runtime_for_workspace(workspace_id)
            leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
            live_for_attach = bool(leftover_runtime) and leftover_formal_plan_is_live_for_fill(
                plan=snapshot.plan or leftover_plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            recovered_leftover = False
            if not live_for_attach:
                if leftover_plan is not None:
                    recovered_leftover = True
                elif live_status.get("recovered") is True and snapshot.plan is None:
                    recovered_leftover = True
            stamped = overlay_session_response_honesty_stamps(
                cached_response,
                pressure_blocks=pressure_blocks,
                streak_blocks=streak_blocks,
                recovered_leftover=recovered_leftover,
            )
            if stamped is not cached_response:
                with core.completed_session_requests_guard:
                    core.completed_session_requests[request_key] = stamped
            return stamped

        def _publish_stream_turn_response(payload_map: dict[str, object]) -> dict[str, object]:
            if not request_id:
                return payload_map
            return publish_session_request_singleflight(
                request_key,
                payload_map,
                completed=core.completed_session_requests,
                inflight=core.inflight_session_requests,
                guard=core.completed_session_requests_guard,
            )

        def _fail_stream_turn_singleflight(error: BaseException) -> None:
            if not request_id:
                return
            # Waiters re-raise whatever the future holds; a bare CancelledError
            # would close their stream with zero frames, so they receive a
            # wrapped failure they can surface through the documented path.
            wrapped = error if isinstance(error, Exception) else RuntimeError(str(error) or "training turn failed")
            fail_session_request_singleflight(
                request_key,
                wrapped,
                inflight=core.inflight_session_requests,
                guard=core.completed_session_requests_guard,
            )

        if request_id:
            kind, cached_response, shared_future = claim_session_request_singleflight(
                request_key,
                completed=core.completed_session_requests,
                inflight=core.inflight_session_requests,
                guard=core.completed_session_requests_guard,
            )
            if kind in ("wait", "cached"):
                async def waiter_generate():
                    try:
                        if kind == "wait":
                            assert shared_future is not None
                            shared_payload = await shared_future
                        else:
                            assert cached_response is not None
                            shared_payload = cached_response
                        stamped = _overlay_completed_turn_response(shared_payload)
                        yield core.sse_complete_frame(
                            tokens=0,
                            response_data=stamped,
                            stream_id=stream_id,
                            request_id=request_id,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        # Owner fail_inflight leaves no complete frame — still overlay
                        # honesty stamps onto a failure complete for waiters.
                        failure_payload = core.attach_operation_reliability(
                            {},
                            phase="acked",
                            outcome="failure",
                            request_id=request_id or None,
                        )
                        stamped = _overlay_completed_turn_response(failure_payload)
                        yield core.stream_status_event("failed", stream_id)
                        yield core.stream_status_event("acked", stream_id)
                        yield (
                            "event: error\n"
                            f"data: {json.dumps({'error': redact_provider_error(exc, api_key=getattr(coaching_service, '_api_key', None)), 'stream_id': stream_id, 'terminal': True})}\n\n"
                        )
                        yield core.sse_complete_frame(
                            tokens=0,
                            response_data=stamped,
                            stream_id=stream_id,
                            outcome="failure",
                            request_id=request_id,
                            provider_failure_detected=True,
                        )

                return StreamingResponse(waiter_generate(), media_type="text/event-stream")

        provider_live_usable = core.provider_is_live_usable(coaching_service, payload)
        if not provider_live_usable:
            core.register_stream_cancellation(stream_id)
            return StreamingResponse(
                core.honest_unusable_provider_stream(
                    request,
                    payload,
                    stream_id=stream_id,
                    original_intent=original_intent,
                    http_request=http_request,
                    publish_complete=_publish_stream_turn_response if request_id else None,
                    fail_inflight=_fail_stream_turn_singleflight if request_id else None,
                ),
                media_type="text/event-stream",
            )
        try:
            core.ensure_streaming_ready(coaching_service, request.response_language)
            core.ensure_agent_tools_ready(request, coaching_service)
            use_agent_stream = _resolve_agent_loop_enabled(
                request, cast(ProviderService, coaching_service), stream=True, payload=payload
            )
        except BaseException as exc:
            # The owner already claimed the singleflight key (T-0033): a sync
            # setup failure must resolve the inflight future or a same-key
            # retry waits forever without ever receiving the failure.
            _fail_stream_turn_singleflight(exc)
            raise
        stream_recovery_requested = (
            request.intent == "coach"
            and core.resource_contract_stream_recovery_requested(request.message)
        )
        def json_response_payload(value: object) -> dict[str, object]:
            encoded_value = core.to_json_payload(value)
            if not isinstance(encoded_value, dict):
                raise TypeError("Turn response payload must be a mapping.")
            return {str(key): item for key, item in encoded_value.items()}

        async def stream_cancelled() -> bool:
            if core.stream_cancellation_requested(stream_id):
                return True
            try:
                return await http_request.is_disconnected()
            except RuntimeError:
                return False

        # Pyright gives up on this oversized async generator ("code is too
        # complex to analyze") and then misreads it as a coroutine, so the
        # complexity bailout is silenced here and the StreamingResponse call
        # site pins the async-iterator type explicitly.
        async def generate():  # pyright: ignore[reportGeneralTypeIssues]
            nonlocal coaching_service, profile, request, state, use_agent_stream, workspace_id
            token_count = 0
            streamed_reply_content = ""
            pending_streamed_reply_content = ""
            stream_user_message: ChatMessage | None = None
            stream_assistant_message_ids: set[str] = set()
            stream_committed = False
            stream_failed = False
            stream_singleflight_published = False
            preexisting_assistant_ids: set[str] = set()

            async def _abort_fail_closed(*, error_detail: object | None = None):
                """Emit failed->acked and publish failure complete so same request_id cannot remint."""
                nonlocal stream_failed, stream_singleflight_published
                stream_failed = True
                failure_payload: dict[str, object] = core.attach_operation_reliability(
                    {},
                    phase="acked",
                    outcome="failure",
                    request_id=request_id or None,
                )
                if request_id and not stream_singleflight_published:
                    failure_payload = _publish_stream_turn_response(failure_payload)
                    stream_singleflight_published = True
                yield core.stream_status_event("failed", stream_id)
                if error_detail is not None:
                    yield (
                        "event: error\n"
                        f"data: {json.dumps({'error': error_detail, 'stream_id': stream_id, 'terminal': True})}\n\n"
                    )
                yield core.stream_status_event("acked", stream_id)
                yield core.sse_complete_frame(
                    tokens=token_count,
                    response_data=failure_payload,
                    stream_id=stream_id,
                    outcome="failure",
                    request_id=request_id or None,
                    provider_failure_detected=True,
                )

            async def _abort_interrupted():
                """Client disconnected: no listener remains for a terminal frame.

                Mint no failure complete so the user turn stays recoverable as
                interrupted on reconnect instead of looking conclusively failed.
                """
                yield core.stream_status_event("cancelled", stream_id)

            async def _abort_for_cancellation():
                """Explicit /stream/cancel stays fail-closed; a client disconnect only interrupts."""
                if core.stream_cancellation_requested(stream_id):
                    async for _closed_frame in _abort_fail_closed():
                        yield _closed_frame
                    return
                async for _abort_frame in _abort_interrupted():
                    yield _abort_frame

            try:
                if await stream_cancelled():
                    async for _abort_frame in _abort_for_cancellation():
                        yield _abort_frame
                    return
                yield core.stream_status_event("preparing_context", stream_id)
                if request.intent != "coach":
                    preparation_or_response, prepared_artifacts, prepared_service = await coach_support.execute_turn(core.coach_support_deps, 
                        request,
                        payload,
                        stream=True,
                        stream_id=stream_id,
                    )
                    if not (
                        isinstance(preparation_or_response, dict)
                        and preparation_or_response.get("__turn_stream_preparation__") is True
                    ):
                        raise TypeError("Turn stream preparation was not produced for the requested turn.")

                    preparation = preparation_or_response
                    prepared_state = preparation.get("state")
                    prepared_request = preparation.get("request")
                    prepared_profile = preparation.get("profile")
                    prepared_coach_turn = preparation.get("coach_turn_data")
                    if not isinstance(prepared_state, SessionState):
                        raise TypeError("Turn stream preparation is missing session state.")
                    if not isinstance(prepared_request, TurnRequest):
                        raise TypeError("Turn stream preparation is missing the normalized request.")
                    if not isinstance(prepared_profile, UserProfile):
                        raise TypeError("Turn stream preparation is missing the learner profile.")
                    if not isinstance(prepared_coach_turn, dict):
                        raise TypeError("Turn stream preparation is missing coach-turn data.")
                    if not isinstance(prepared_service, ProviderService):
                        raise TypeError("Turn stream preparation is missing the provider service.")

                    state = prepared_state
                    preexisting_assistant_ids = {
                        message.id
                        for message in state.snapshot.messages
                        if message.role == "assistant"
                    }
                    stream_user_message = next(
                        (
                            message
                            for message in reversed(state.snapshot.messages)
                            if message.role == "user"
                            and str(message.metadata.get("stream_id") or "").strip() == stream_id
                        ),
                        None,
                    )
                    request = prepared_request
                    profile = prepared_profile
                    coaching_service = prepared_service
                    artifacts: dict[str, object] = core.normalized_object_mapping(
                        preparation.get("artifacts")
                    ) or {}
                    suggested_actions = list(preparation.get("suggested_actions") or [])
                    prepared_agent_meta = core.normalized_object_mapping(preparation.get("agent_meta")) or {}
                    coach_turn_data = dict(prepared_coach_turn)
                    response_snapshot = preparation.get("response_snapshot")
                    if not isinstance(response_snapshot, WorkbenchSnapshot):
                        response_snapshot = state.snapshot
                    scenario = str(preparation.get("scenario") or coach_turn_data.get("scenario") or "general")
                    learner_signal = str(preparation.get("learner_signal") or "")
                    attachment_delivery = preparation.get("attachment_delivery")
                    if not isinstance(attachment_delivery, dict):
                        attachment_delivery = None
                    fallback_reply = str(preparation.get("fallback_reply") or "").strip()
                    use_agent_stream = bool(preparation.get("use_agent_loop"))
                    attachments_payload = [attachment.model_dump() for attachment in request.attachments]
                    coach_context = coach_turn_data.get("coach_context")
                    if not isinstance(coach_context, dict):
                        coach_context = {}

                    full_content = ""
                    agent_summary: str | None = None
                    agent_next_step: str | None = None
                    agent_stop_reason: str | None = None
                    agent_decision: str | None = None
                    agent_blocker: str | None = None
                    agent_teaching_note: str | None = None
                    agent_resume_thread: str | None = None
                    agent_confidence: str | None = None
                    agent_evidence: list[object] | None = None
                    agent_tool_events: list[dict[str, object]] = []
                    agent_steps: list[dict[str, object]] = []
                    final_agent_meta: dict[str, object] = dict(prepared_agent_meta)
                    provider_failure_detected = False

                    yield core.stream_status_event("requesting_model", stream_id)
                    if use_agent_stream:
                        agent_context = dict(coach_context)
                        agent_context["__runtime__"] = runtime
                        agent_context["workspace_id"] = workspace_id
                        agent_context["session_id"] = state.session_id
                        agent_context["stream_cancel_event"] = core.stream_cancellation_events.get(stream_id)
                        async for event in coaching_service.coaching_reply_agentic_stream(
                            profile,
                            request.message,
                            request.current_file.model_dump() if request.current_file else None,
                            response_language=request.response_language,
                            answer_mode=request.answer_mode,
                            coach_context=agent_context,
                            attachments=attachments_payload,
                            protocol=(
                                getattr(coaching_service._config, "protocol", None)
                                if coaching_service._config
                                else None
                            ),
                            history=core.build_conversation_history(
                                state.snapshot.messages,
                                drop_latest_user=True,
                            ),
                        ):
                            if await stream_cancelled():
                                async for _abort_frame in _abort_for_cancellation():
                                    yield _abort_frame
                                return
                            if not isinstance(event, dict):
                                continue
                            event_type = str(event.get("type") or "")
                            if event_type == "text":
                                delta = str(event.get("delta") or "")
                                if delta:
                                    full_content += delta
                                    token_count += 1
                                    if event.get("safe_to_stream") is True and (
                                        not core.requires_formal_plan_commit(request)
                                        or core.formal_plan_commit_tool_succeeded(agent_tool_events)
                                    ):
                                        visible_delta, pending_streamed_reply_content = core.safe_stream_delta(
                                            pending_streamed_reply_content,
                                            delta,
                                            full_content,
                                        )
                                        if visible_delta:
                                            streamed_reply_content += visible_delta
                                            yield f"data: {json.dumps({'chunk': visible_delta})}\n\n"
                            elif event_type == "tool_call":
                                agent_tool_events.append(dict(event))
                                yield core.stream_frame("tool_call", event, stream_id)
                            elif event_type == "tool_result":
                                agent_tool_events.append(dict(event))
                                yield core.stream_frame("tool_result", event, stream_id)
                            elif event_type == "step":
                                agent_steps.append(dict(event))
                                yield core.stream_frame("step", event, stream_id)
                            elif event_type == "final":
                                final_content = str(event.get("content") or "")
                                if final_content:
                                    full_content = final_content
                                agent_summary = event.get("summary")
                                agent_next_step = event.get("next_step")
                                agent_stop_reason = event.get("stop_reason")
                                agent_decision = event.get("decision")
                                agent_blocker = event.get("blocker")
                                agent_teaching_note = event.get("teaching_note")
                                agent_resume_thread = event.get("resume_thread")
                                agent_confidence = event.get("confidence")
                                agent_evidence = (
                                    list(event.get("evidence") or [])
                                    if isinstance(event.get("evidence"), list)
                                    else None
                                )
                            elif event_type == "error":
                                async for _abort_frame in _abort_fail_closed(
                                    error_detail=redact_provider_error(
                                        event.get("detail"),
                                        api_key=getattr(coaching_service, "_api_key", None),
                                    ),
                                ):
                                    yield _abort_frame
                                return
                        if full_content:
                            full_content = coaching_service.finalize_coaching_reply(
                                full_content,
                                profile=profile,
                                message=request.message,
                                current_file=request.current_file.model_dump() if request.current_file else None,
                                response_language=request.response_language,
                                answer_mode=request.answer_mode,
                                coach_context=coach_context,
                            )
                        if not agent_resume_thread and (agent_summary or agent_next_step):
                            agent_resume_thread = core.build_resume_thread_text(
                                str(agent_summary or "").strip(),
                                str(agent_next_step or "").strip(),
                                response_language=request.response_language,
                            )
                    else:
                        async for chunk in coaching_service.coaching_reply_stream(
                            profile,
                            request.message,
                            request.current_file.model_dump() if request.current_file else None,
                            response_language=request.response_language,
                            answer_mode=request.answer_mode,
                            coach_context=coach_context,
                            history=core.build_conversation_history(
                                state.snapshot.messages,
                                drop_latest_user=True,
                            ),
                            cancel_event=core.stream_cancellation_events.get(stream_id),
                        ):
                            if await stream_cancelled():
                                async for _abort_frame in _abort_for_cancellation():
                                    yield _abort_frame
                                return
                            delta = str(chunk or "")
                            if not delta:
                                continue
                            full_content += delta
                            token_count += 1
                            visible_delta, pending_streamed_reply_content = core.safe_stream_delta(
                                pending_streamed_reply_content,
                                delta,
                                full_content,
                            )
                            if visible_delta and not core.requires_formal_plan_commit(request):
                                streamed_reply_content += visible_delta
                                yield f"data: {json.dumps({'chunk': visible_delta})}\n\n"
                        stream_finalization = coaching_service.consume_stream_finalization()
                        if stream_finalization is not None:
                            full_content = stream_finalization[1]
                        elif full_content:
                            full_content = coaching_service.finalize_coaching_reply(
                                full_content,
                                profile=profile,
                                message=request.message,
                                current_file=request.current_file.model_dump() if request.current_file else None,
                                response_language=request.response_language,
                                answer_mode=request.answer_mode,
                                coach_context=coach_context,
                            )

                    if not full_content:
                        full_content = fallback_reply
                    if not full_content:
                        full_content = coaching_service._fallback_empty_reply(
                            profile=profile,
                            message=request.message,
                            current_file=request.current_file.model_dump() if request.current_file else None,
                            response_language=request.response_language,
                            answer_mode=request.answer_mode,
                            coach_context=coach_context,
                        )
                        token_count += 1

                    provider_empty_reply_override = core.consume_provider_empty_reply_override(
                        coaching_service=coaching_service,
                        snapshot=state.snapshot,
                        coach_turn=coach_turn_data,
                        response_language=request.response_language,
                        assistant_content=full_content,
                    )
                    if provider_empty_reply_override is not None:
                        provider_failure_detected = True
                        full_content, updated_coach_turn, override_meta = provider_empty_reply_override
                        coach_turn_data = updated_coach_turn
                        final_agent_meta.update(override_meta)
                    else:
                        provider_failure_override = core.consume_provider_reply_failure_override(
                            coaching_service=coaching_service,
                            snapshot=state.snapshot,
                            coach_turn=coach_turn_data,
                            message=request.message,
                            response_language=request.response_language,
                            workspace_id=state.workspace_id,
                        )
                        if provider_failure_override is not None:
                            provider_failure_detected = True
                            full_content, updated_coach_turn, override_meta = provider_failure_override
                            coach_turn_data = updated_coach_turn
                            final_agent_meta.update(override_meta)

                    if use_agent_stream and not provider_failure_detected:
                        final_agent_meta = merge_stream_agent_metadata(final_agent_meta, {
                            "stop_reason": agent_stop_reason,
                            "summary": agent_summary,
                            "next_step": agent_next_step,
                            "decision": agent_decision,
                            "blocker": agent_blocker,
                            "teaching_note": agent_teaching_note,
                            "resume_thread": agent_resume_thread,
                            "confidence": agent_confidence,
                            "evidence": agent_evidence,
                            "steps": agent_steps,
                            "tool_events": agent_tool_events,
                            "agentic": True,
                        })
                        coach_turn_data = core.merge_agent_finalize_into_coach_turn(
                            coach_turn_data,
                            summary=agent_summary,
                            next_step=agent_next_step,
                            blocker=agent_blocker,
                            resume_thread=agent_resume_thread,
                            decision=agent_decision,
                            teaching_note=agent_teaching_note,
                            confidence=agent_confidence,
                            evidence=agent_evidence,
                        )

                    state.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
                    runtime.hydrate_plan_context(state.snapshot, workspace_id)
                    coach_support.hydrate_snapshot(core.coach_support_deps,
                        state.snapshot,
                        response_language=request.response_language,
                        answer_mode=request.answer_mode or profile.answer_policy,
                        scenario=scenario,
                        learner_signal=learner_signal,
                        message=request.message,
                        current_file=request.current_file,
                        active_view=request.active_view,
                        session_workspace_id=workspace_id,
                    )
                    if request.intent == "plan" and request.formal_plan_mutation:
                        persisted_plan = runtime.repository.get_latest_plan(workspace_id)
                        _leftover_after, leftover_runtime_after = core.leftover_runtime_for_workspace(
                            workspace_id
                        )
                        if persisted_plan is not None and leftover_formal_plan_is_live_for_fill(
                            plan=persisted_plan,
                            runtime=leftover_runtime_after,
                            existing=leftover_runtime_after,
                        ):
                            state.snapshot.plan = persisted_plan
                    response_snapshot = state.snapshot

                    # This streaming pass may have replaced the next step the
                    # preparation pass was decided on; the delivered text must
                    # be decided for itself (Fingerprint mismatch invalidates
                    # the cached decision) before the response consumes it.
                    if core.grounding_decision_from_payload(coach_turn_data) is None:
                        streaming_grounding_decision = await core.resolve_turn_grounding_async(
                            coach_turn_payload=coach_turn_data,
                            reply_content=full_content,
                            request=request,
                            agent_meta=final_agent_meta or None,
                            history_text=core.turn_history_text(state.snapshot),
                            coaching_service=coaching_service,
                        )
                        final_agent_meta = core.apply_grounding_decision(
                            coach_turn_payload=coach_turn_data,
                            decision=streaming_grounding_decision,
                            agent_meta=final_agent_meta or None,
                        ) or final_agent_meta

                    response_data = json_response_payload(
                        coach_support.build_session_response(core.coach_support_deps, 
                            state=state,
                            request=request,
                            reply_content=full_content,
                            artifacts=artifacts,
                            suggested_actions=suggested_actions,
                            scenario=scenario,
                            learner_signal=learner_signal,
                            coach_turn_data=coach_turn_data,
                            response_snapshot=response_snapshot,
                            agent_meta=final_agent_meta or None,
                            attachment_delivery=attachment_delivery,
                        )
                    )
                    response_data["artifacts"] = artifacts
                    response_data["intent"] = original_intent
                    reply_record = response_data.get("reply")
                    visible_content = (
                        str(reply_record.get("content") or "").strip()
                        if isinstance(reply_record, dict)
                        else ""
                    )
                    visible_delta = core.completion_stream_delta(streamed_reply_content, visible_content)
                    if visible_delta:
                        token_count += 1
                        yield f"data: {json.dumps({'chunk': visible_delta})}\n\n"
                    if final_agent_meta:
                        response_data["agent"] = final_agent_meta
                    if await stream_cancelled():
                        if not core.stream_cancellation_requested(stream_id):
                            # Client disconnected: no listener remains for a terminal frame;
                            # leave the turn recoverable as interrupted, mint no fake complete.
                            yield core.stream_status_event("cancelled", stream_id)
                            return
                        # Built payload but aborted before commit: publish failure so
                        # same request_id cannot remint; waiters get stamped complete.
                        stream_failed = True
                        response_data = core.attach_operation_reliability(
                            response_data,
                            phase="acked",
                            outcome="failure",
                            request_id=request_id or None,
                        )
                        response_data = _publish_stream_turn_response(response_data)
                        stream_singleflight_published = True
                        yield core.stream_status_event("failed", stream_id)
                        yield core.stream_status_event("acked", stream_id)
                        yield core.sse_complete_frame(
                            tokens=token_count,
                            response_data=response_data,
                            stream_id=stream_id,
                            outcome="failure",
                            request_id=request_id or None,
                            provider_failure_detected=True,
                        )
                        return
                    runtime.save_session_state(state.session_id)
                    response_data = _publish_stream_turn_response(response_data)
                    stream_singleflight_published = True
                    yield core.sse_complete_frame(
                        tokens=token_count,
                        response_data=response_data,
                        stream_id=stream_id,
                        provider_failure_detected=provider_failure_detected,
                    )
                    return

                workspace_id = core.current_workspace_id(
                    session_id=request.session_id, workspace_id=request.workspace_id
                )
                if state is None or profile is None:
                    raise RuntimeError("Coach stream state was not initialized.")
                coaching_service = core.build_coaching_service(payload)
                attachment_delivery = core.describe_request_attachment_delivery(
                    request,
                    coaching_service,
                    use_agent_loop=use_agent_stream,
                )
                attachments_payload = [a.model_dump() for a in request.attachments]

                preexisting_assistant_ids = {
                    message.id
                    for message in state.snapshot.messages
                    if message.role == "assistant"
                }
                stream_user_message, _ = core.prepare_stream_user_message(
                    state=state,
                    request=request,
                    profile=profile,
                    attachment_delivery=attachment_delivery,
                    stream_id=stream_id,
                )
                core.safe_activate_training_card_from_coach_request(
                    workspace_id=state.workspace_id,
                    snapshot=state.snapshot,
                    message=request.message,
                    current_file=request.current_file,
                    response_language=request.response_language,
                    provider_service_override=coaching_service,
                )
                state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
                coach_turn: CoachTurnPayload = coach_support.resolve_coach_turn(core.coach_support_deps, 
                    state=state,
                    profile=profile,
                    request=request,
                    message=request.message,
                    coaching_service=coaching_service,
                    current_task=state.snapshot.current_task,
                    current_plan=state.snapshot.plan,
                    current_evaluation=state.snapshot.evaluation,
                )
                scenario = str(coach_turn.get("scenario") or "general")
                if core.guarantee_guided_learn_first_training_card(
                    workspace_id=state.workspace_id,
                    scenario=str(coach_turn["scenario"] or ""),
                    message=request.message,
                    current_file=request.current_file,
                    response_language=request.response_language,
                    active_thread=state.snapshot.memory.active_thread,
                    requested_answer_mode=raw_requested_answer_mode,
                    saved_answer_mode=saved_answer_mode,
                    profile=profile,
                ):
                    state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
                guided_training_prefers_local_reply = core.should_bypass_agent_loop_for_guided_training(
                    workspace_id=state.workspace_id,
                    scenario=str(coach_turn["scenario"] or scenario),
                    message=request.message,
                    active_view=request.active_view,
                    requested_answer_mode=raw_requested_answer_mode,
                    saved_answer_mode=saved_answer_mode,
                    profile=profile,
                )
                guided_training_local_reply = (
                    core.build_guided_training_visible_fallback(
                        workspace_id=state.workspace_id,
                        response_language=request.response_language,
                    )
                    if guided_training_prefers_local_reply
                    else None
                )
                auto_resource_events = core.auto_resource_lookup_tool_events(
                    dict(coach_turn["coach_context"]),
                    request.message,
                )

                full_content = ""
                agent_summary: str | None = None
                agent_next_step: str | None = None
                agent_stop_reason: str | None = None
                agent_decision: str | None = None
                agent_blocker: str | None = None
                agent_teaching_note: str | None = None
                agent_resume_thread: str | None = None
                agent_confidence: str | None = None
                agent_evidence: list[object] | None = None
                agent_tool_events: list[dict[str, object]] = []
                agent_steps: list[dict[str, object]] = []
                provider_failure_detected = False
                final_agent_meta: dict[str, object] = {}
                if guided_training_local_reply is None:
                    yield core.stream_status_event("requesting_model", stream_id)
                if guided_training_local_reply is not None:
                    full_content, updated_coach_turn, guided_meta = core.apply_guided_training_visible_fallback(
                        coach_turn=core.coach_turn_mapping(coach_turn),
                        fallback=guided_training_local_reply,
                    )
                    coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
                    final_agent_meta.update(guided_meta)
                    token_count += 1
                elif use_agent_stream and not guided_training_prefers_local_reply:
                    agent_context = dict(coach_turn["coach_context"])
                    agent_context["__runtime__"] = runtime
                    agent_context["workspace_id"] = workspace_id
                    agent_context["session_id"] = state.session_id
                    agent_context["stream_cancel_event"] = core.stream_cancellation_events.get(stream_id)
                    async for event in coaching_service.coaching_reply_agentic_stream(
                        profile,
                        request.message,
                        request.current_file.model_dump() if request.current_file else None,
                        response_language=request.response_language,
                        answer_mode=request.answer_mode,
                        coach_context=agent_context,
                        attachments=attachments_payload,
                        protocol=getattr(coaching_service._config, "protocol", None)
                        if coaching_service._config
                        else None,
                        history=core.build_conversation_history(
                            state.snapshot.messages,
                            drop_latest_user=True,
                        ),
                        ):
                            if await stream_cancelled():
                                async for _abort_frame in _abort_for_cancellation():
                                    yield _abort_frame
                                return
                            event_type = str(event.get("type") or "")
                            if event_type == "text":
                                delta = str(event.get("delta") or "")
                                if delta:
                                    full_content += delta
                                    token_count += 1
                                    if event.get("safe_to_stream") is True and (
                                        not core.requires_formal_plan_commit(request)
                                        or core.formal_plan_commit_tool_succeeded(agent_tool_events)
                                    ):
                                        visible_delta, pending_streamed_reply_content = core.safe_stream_delta(
                                            pending_streamed_reply_content,
                                            delta,
                                            full_content,
                                        )
                                        if visible_delta:
                                            streamed_reply_content += visible_delta
                                            yield f"data: {json.dumps({'chunk': visible_delta})}\n\n"
                            elif event_type == "tool_call":
                                agent_tool_events.append(dict(event))
                                yield core.stream_frame("tool_call", event, stream_id)
                            elif event_type == "tool_result":
                                agent_tool_events.append(dict(event))
                                yield core.stream_frame("tool_result", event, stream_id)
                            elif event_type == "step":
                                agent_steps.append(dict(event))
                                yield core.stream_frame("step", event, stream_id)
                            elif event_type == "final":
                                final_content = str(event.get("content") or "")
                                if final_content:
                                    full_content = final_content
                                agent_summary = event.get("summary")
                                agent_next_step = event.get("next_step")
                                agent_stop_reason = event.get("stop_reason")
                                agent_decision = event.get("decision")
                                agent_blocker = event.get("blocker")
                                agent_teaching_note = event.get("teaching_note")
                                agent_resume_thread = event.get("resume_thread")
                                agent_confidence = event.get("confidence")
                                agent_evidence = (
                                    list(event.get("evidence") or [])
                                    if isinstance(event.get("evidence"), list)
                                    else None
                                )
                            elif event_type == "error":
                                async for _abort_frame in _abort_fail_closed(
                                    error_detail=redact_provider_error(
                                        event.get("detail"),
                                        api_key=getattr(coaching_service, "_api_key", None),
                                    ),
                                ):
                                    yield _abort_frame
                                return
                    if full_content:
                        full_content = coaching_service.finalize_coaching_reply(
                            full_content,
                            profile=profile,
                            message=request.message,
                            current_file=request.current_file.model_dump() if request.current_file else None,
                            response_language=request.response_language,
                            answer_mode=request.answer_mode,
                            coach_context=dict(coach_turn["coach_context"]),
                        )
                    if not full_content:
                        local_sequence_fallback = core.build_local_sequence_visible_fallback(
                            coach_context=dict(coach_turn["coach_context"]),
                            response_language=request.response_language,
                        )
                        if local_sequence_fallback is not None:
                            full_content = local_sequence_fallback["reply"]
                            coaching_service.clear_last_reply_override()
                            agent_summary = agent_summary or local_sequence_fallback["summary"]
                            agent_next_step = agent_next_step or local_sequence_fallback["next_step"]
                            agent_teaching_note = (
                                agent_teaching_note or local_sequence_fallback["teaching_note"]
                            )
                            agent_resume_thread = (
                                agent_resume_thread or local_sequence_fallback["resume_thread"]
                            )
                            final_agent_meta["local_sequence_fallback"] = True
                            if str(agent_stop_reason or "").strip() == "empty_response":
                                final_agent_meta["fell_back"] = True
                                final_agent_meta["recovered_stop_reason"] = "empty_response"
                                final_agent_meta["stop_reason"] = "completed"
                        else:
                            full_content = coaching_service._fallback_empty_reply(
                                profile=profile,
                                message=request.message,
                                current_file=(
                                    request.current_file.model_dump() if request.current_file else None
                                ),
                                response_language=request.response_language,
                                answer_mode=request.answer_mode,
                                coach_context=dict(coach_turn["coach_context"]),
                            )
                        token_count += 1
                    updated_coach_turn = core.merge_agent_finalize_into_coach_turn(
                        core.coach_turn_mapping(coach_turn),
                        summary=agent_summary,
                        next_step=agent_next_step,
                        blocker=agent_blocker,
                        resume_thread=agent_resume_thread,
                        decision=agent_decision,
                        teaching_note=agent_teaching_note,
                        confidence=agent_confidence,
                        evidence=agent_evidence,
                    )
                    coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
                else:
                    try:
                        async for chunk in coaching_service.coaching_reply_stream(
                            profile,
                            request.message,
                            request.current_file.model_dump() if request.current_file else None,
                            response_language=request.response_language,
                            answer_mode=request.answer_mode,
                            coach_context=dict(coach_turn["coach_context"]),
                            history=core.build_conversation_history(
                                state.snapshot.messages,
                                drop_latest_user=True,
                            ),
                            cancel_event=core.stream_cancellation_events.get(stream_id),
                        ):
                            if await stream_cancelled():
                                async for _abort_frame in _abort_for_cancellation():
                                    yield _abort_frame
                                return
                            full_content += chunk
                            token_count += 1
                            visible_chunk, pending_streamed_reply_content = core.safe_stream_delta(
                                pending_streamed_reply_content,
                                chunk,
                                full_content,
                            )
                            if visible_chunk and not core.requires_formal_plan_commit(request):
                                streamed_reply_content += visible_chunk
                                yield f"data: {json.dumps({'chunk': visible_chunk})}\n\n"
                    except Exception:
                        if not stream_recovery_requested or streamed_reply_content or full_content:
                            raise
                        # Grounding recovery is deliberately exceptional: the
                        # nominal path above is always provider-backed SSE.
                        fallback_response, fallback_artifacts, _ = await coach_support.execute_turn(core.coach_support_deps, 
                            request,
                            payload,
                            stream=False,
                        )
                        if isinstance(fallback_response, SessionMessageResponse):
                            fallback_workspace_id = core.current_workspace_id(
                                session_id=request.session_id,
                                workspace_id=request.workspace_id,
                            )
                            fallback_response.snapshot.memory = core.repair_guided_lane_memory_snapshot_for_response(
                                runtime.memory_service.snapshot(fallback_workspace_id),
                                scenario=(
                                    fallback_response.coach_turn.scenario
                                    if fallback_response.coach_turn
                                    else None
                                ),
                                response_language=request.response_language,
                                learner_message=request.message,
                            )
                            fallback_workspace_memory = (
                                fallback_response.snapshot.memory.workspace
                                if isinstance(fallback_response.snapshot.memory.workspace, dict)
                                else {}
                            )
                            coach_support.hydrate_snapshot(core.coach_support_deps,
                                fallback_response.snapshot,
                                preserve_turn_coaching_state=True,
                                response_language=request.response_language
                                or str(fallback_workspace_memory.get("response_language") or "").strip()
                                or None,
                                answer_mode=(
                                    str(fallback_workspace_memory.get("answer_mode") or "").strip()
                                    or (
                                        fallback_response.snapshot.profile.answer_policy
                                        if fallback_response.snapshot.profile is not None
                                        else None
                                    )
                                ),
                                message=request.message,
                                session_workspace_id=fallback_workspace_id,
                            )
                        response_data = json_response_payload(fallback_response)
                        response_data["artifacts"] = fallback_artifacts
                        response_data["intent"] = original_intent
                        if "agent" not in response_data and isinstance(
                            response_data.get("agent_meta"),
                            dict,
                        ):
                            response_data["agent"] = response_data["agent_meta"]
                        reply = response_data.get("reply")
                        reply_content = (
                            str(reply.get("content") or "").strip()
                            if isinstance(reply, dict)
                            else ""
                        )
                        if reply_content:
                            token_count += 1
                            yield f"data: {json.dumps({'chunk': reply_content})}\n\n"
                        response_data = _publish_stream_turn_response(response_data)
                        stream_singleflight_published = True
                        yield core.sse_complete_frame(
                            tokens=token_count,
                            response_data=response_data,
                            stream_id=stream_id,
                            provider_failure_detected=True,
                        )
                        return
                    stream_finalization = coaching_service.consume_stream_finalization()
                    if stream_finalization is not None:
                        full_content = stream_finalization[1]
                    else:
                        full_content = coaching_service.finalize_coaching_reply(
                            full_content,
                            profile=profile,
                            message=request.message,
                            current_file=request.current_file.model_dump() if request.current_file else None,
                            response_language=request.response_language,
                            answer_mode=request.answer_mode,
                            coach_context=dict(coach_turn["coach_context"]),
                        )

                provider_empty_reply_override = core.consume_provider_empty_reply_override(
                    coaching_service=coaching_service,
                    snapshot=state.snapshot,
                    coach_turn=core.coach_turn_mapping(coach_turn),
                    response_language=request.response_language,
                    assistant_content=full_content,
                )
                if provider_empty_reply_override is not None:
                    provider_failure_detected = True
                    full_content, updated_coach_turn, override_meta = provider_empty_reply_override
                    coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
                    final_agent_meta.update(override_meta)
                else:
                    provider_failure_override = core.consume_provider_reply_failure_override(
                        coaching_service=coaching_service,
                        snapshot=state.snapshot,
                        coach_turn=core.coach_turn_mapping(coach_turn),
                        message=request.message,
                        response_language=request.response_language,
                        workspace_id=state.workspace_id,
                    )
                    if provider_failure_override is not None:
                        provider_failure_detected = True
                        full_content, updated_coach_turn, override_meta = provider_failure_override
                        coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
                        final_agent_meta.update(override_meta)

                if not provider_failure_detected:
                    visible_agent_meta = {
                        "stop_reason": agent_stop_reason,
                        "summary": agent_summary,
                        "next_step": agent_next_step,
                        "decision": agent_decision,
                        "blocker": agent_blocker,
                        "teaching_note": agent_teaching_note,
                        "resume_thread": agent_resume_thread,
                        "confidence": agent_confidence,
                        "evidence": agent_evidence,
                        "steps": agent_steps,
                        "tool_events": agent_tool_events,
                        "agentic": use_agent_stream and not guided_training_prefers_local_reply,
                        **final_agent_meta,
                    }
                    full_content, updated_coach_turn, final_agent_meta, _guided_lane_repaired = (
                        core.apply_guided_lane_visible_fallback(
                            reply=full_content,
                            scenario=str(coach_turn.get("scenario") or scenario),
                            learner_message=request.message,
                            response_language=request.response_language,
                            coach_turn=core.coach_turn_mapping(coach_turn),
                            agent_meta=visible_agent_meta,
                        )
                    )
                    coach_turn = core.extract_coach_turn_payload(updated_coach_turn)
                    repaired_summary = final_agent_meta.get("summary")
                    agent_summary = (
                        repaired_summary if isinstance(repaired_summary, str) else None
                    )
                    repaired_next_step = final_agent_meta.get("next_step")
                    agent_next_step = (
                        repaired_next_step if isinstance(repaired_next_step, str) else None
                    )
                    repaired_decision = final_agent_meta.get("decision")
                    agent_decision = (
                        repaired_decision if isinstance(repaired_decision, str) else None
                    )
                    repaired_blocker = final_agent_meta.get("blocker")
                    agent_blocker = (
                        repaired_blocker if isinstance(repaired_blocker, str) else None
                    )
                    repaired_teaching_note = final_agent_meta.get("teaching_note")
                    agent_teaching_note = (
                        repaired_teaching_note if isinstance(repaired_teaching_note, str) else None
                    )
                    repaired_resume_thread = final_agent_meta.get("resume_thread")
                    agent_resume_thread = (
                        repaired_resume_thread if isinstance(repaired_resume_thread, str) else None
                    )
                    repaired_confidence = final_agent_meta.get("confidence")
                    agent_confidence = (
                        repaired_confidence if isinstance(repaired_confidence, str) else None
                    )
                    repaired_evidence = final_agent_meta.get("evidence")
                    agent_evidence = (
                        list(repaired_evidence)
                        if isinstance(repaired_evidence, list)
                        else None
                    )
                    core.ensure_explicit_training_card_after_coach_reply(
                        state=state,
                        message=request.message,
                        current_file=request.current_file,
                        response_language=request.response_language,
                        fallback_scenario=str(coach_turn.get("scenario") or ""),
                        force_training_card=core.auto_preference_requests_training_card(
                            request.message,
                            requested_scenario=str(coach_turn.get("scenario") or scenario),
                            requested_answer_mode=raw_requested_answer_mode,
                            saved_answer_mode=saved_answer_mode,
                            profile=profile,
                        )
                        or core.auto_lane_learn_first_force_training_card(
                            request.message,
                            requested_scenario=str(coach_turn.get("scenario") or scenario),
                            requested_answer_mode=raw_requested_answer_mode,
                            saved_answer_mode=saved_answer_mode,
                            profile=profile,
                        ),
                        provider_service_override=coaching_service,
                    )

                if await stream_cancelled():
                    async for _abort_frame in _abort_for_cancellation():
                        yield _abort_frame
                    return
                grounding_decision = await core.resolve_turn_grounding_async(
                    coach_turn_payload=coach_turn,
                    reply_content=full_content,
                    request=request,
                    agent_meta=final_agent_meta if isinstance(final_agent_meta, dict) else None,
                    history_text=core.turn_history_text(state.snapshot),
                    coaching_service=coaching_service,
                )
                final_agent_meta = core.apply_grounding_decision(
                    coach_turn_payload=coach_turn,
                    decision=grounding_decision,
                    agent_meta=final_agent_meta if isinstance(final_agent_meta, dict) else None,
                ) or final_agent_meta
                # T-0048: repair a generic finalize step BEFORE the reflection
                # persists, so the memory thread and the shipped stream step
                # match what build_session_response will surface (its repair
                # alone runs after this persist).
                coach_turn = core.repair_generic_finalize_next_step(
                    full_content,
                    final_agent_meta if isinstance(final_agent_meta, dict) and final_agent_meta else None,
                    coach_turn,
                    response_language=request.response_language,
                ) or coach_turn
                coach_support.persist_turn_reflection(core.coach_support_deps,
                    workspace_id=workspace_id,
                    session_id=state.session_id,
                    user_message=request.message,
                    scenario=str(coach_turn["scenario"]),
                    response_language=request.response_language,
                    answer_mode=core.answer_mode_preference_for_persistence(
                        raw_requested_answer_mode,
                        saved_answer_mode,
                        request.answer_mode,
                        profile.answer_policy,
                    ),
                    coach_defaults=request.coach_defaults,
                    coach_turn_data=core.coach_turn_mapping(coach_turn),
                    grounding_decision=grounding_decision,
                    stop_reason=str(final_agent_meta.get("stop_reason") or ""),
                    recovered_stop_reason=str(final_agent_meta.get("recovered_stop_reason") or ""),
                    local_sequence_fallback=bool(final_agent_meta.get("local_sequence_fallback")),
                )
                core.persist_recovered_plan_resume_after_turn(
                    workspace_id=workspace_id,
                    request=request,
                    reply_content=full_content,
                    agent_meta=final_agent_meta if isinstance(final_agent_meta, dict) else None,
                    coach_context=coach_turn.get("coach_context") if isinstance(coach_turn, dict) else None,
                    recovered_status=state.snapshot.plan_runtime_status
                    if isinstance(state.snapshot.plan_runtime_status, dict)
                    else None,
                )
                if not provider_failure_detected:
                    core.persist_external_references_as_background(
                        workspace_id=workspace_id,
                        scenario=str(coach_turn["scenario"]),
                        coach_turn_data=core.coach_turn_mapping(coach_turn),
                    )
                state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
                state.snapshot.profile = runtime.repository.get_profile(workspace_id) or profile
                runtime.hydrate_plan_context(state.snapshot, workspace_id)
                coach_support.hydrate_snapshot(core.coach_support_deps,
                    state.snapshot,
                    response_language=request.response_language,
                    answer_mode=request.answer_mode or profile.answer_policy,
                    scenario=str(coach_turn["scenario"]),
                    learner_signal=str(coach_turn["learner_signal"]),
                    message=request.message,
                    session_workspace_id=workspace_id,
                )
                core.update_snapshot_plan_from_turn(
                    state=state,
                    reply_content=full_content,
                    coach_turn=core.coach_turn_mapping(coach_turn),
                    # Session/coach streams never formal-mutate; only explicit plan intent.
                    allow_formal_plan_mutation=core.requires_formal_plan_commit(request),
                )
                if use_agent_stream and not guided_training_prefers_local_reply:
                    stream_agent_meta = {
                        "stop_reason": agent_stop_reason,
                        "summary": agent_summary,
                        "next_step": agent_next_step,
                        "decision": agent_decision,
                        "blocker": agent_blocker,
                        "teaching_note": agent_teaching_note,
                        "confidence": agent_confidence,
                        "evidence": agent_evidence,
                        "steps": agent_steps,
                        "tool_events": agent_tool_events,
                        "agentic": True,
                        **(core.normalize_attachment_delivery_payload(attachment_delivery) or {}),
                    }
                    final_agent_meta = merge_stream_agent_metadata(
                        final_agent_meta, stream_agent_meta,
                        preserve_failure=provider_failure_detected,
                    )
                if core.should_attach_auto_resource_events(final_agent_meta):
                    final_agent_meta = core.apply_auto_resource_agent_evidence(
                        final_agent_meta,
                        auto_resource_events,
                    )
                response_data = json_response_payload(
                    coach_support.build_session_response(core.coach_support_deps, 
                        state=state,
                        request=request,
                        reply_content=full_content,
                        artifacts=dict(coach_turn["artifacts"]),
                        suggested_actions=list(coach_turn["suggested_actions"]),
                        scenario=str(coach_turn["scenario"]),
                        learner_signal=str(coach_turn["learner_signal"]),
                        coach_turn_data=core.coach_turn_mapping(coach_turn),
                        agent_meta=final_agent_meta or None,
                        attachment_delivery=attachment_delivery,
                    )
                )
                response_data["artifacts"] = dict(coach_turn["artifacts"])
                response_data["intent"] = original_intent
                reply_record = response_data.get("reply")
                visible_content = (
                    str(reply_record.get("content") or "").strip()
                    if isinstance(reply_record, dict)
                    else ""
                )
                visible_delta = core.completion_stream_delta(streamed_reply_content, visible_content)
                if visible_delta:
                    token_count += 1
                    yield f"data: {json.dumps({'chunk': visible_delta})}\n\n"
                if final_agent_meta:
                    response_data["agent"] = final_agent_meta
                if await stream_cancelled():
                    if not core.stream_cancellation_requested(stream_id):
                        # Client disconnected: no listener remains for a terminal frame;
                        # leave the turn recoverable as interrupted, mint no fake complete.
                        yield core.stream_status_event("cancelled", stream_id)
                        return
                    # Built payload but aborted before commit: publish failure so same
                    # request_id cannot remint, waiters get stamped complete, not hang.
                    stream_failed = True
                    response_data = core.attach_operation_reliability(
                        response_data,
                        phase="acked",
                        outcome="failure",
                        request_id=request_id or None,
                    )
                    response_data = _publish_stream_turn_response(response_data)
                    stream_singleflight_published = True
                    yield core.stream_status_event("failed", stream_id)
                    yield core.stream_status_event("acked", stream_id)
                    yield core.sse_complete_frame(
                        tokens=token_count,
                        response_data=response_data,
                        stream_id=stream_id,
                        outcome="failure",
                        request_id=request_id or None,
                        provider_failure_detected=True,
                    )
                    return
                stream_assistant_message_ids.update(
                    message.id
                    for message in state.snapshot.messages
                    if message.role == "assistant" and message.id not in preexisting_assistant_ids
                )
                runtime.save_session_state(state.session_id)
                stream_committed = True

                response_data = _publish_stream_turn_response(response_data)
                stream_singleflight_published = True
                yield core.sse_complete_frame(
                    tokens=token_count,
                    response_data=response_data,
                    stream_id=stream_id,
                    provider_failure_detected=provider_failure_detected,
                )
            except asyncio.CancelledError:
                # Fail-closed: failed->acked + publish failure complete (no remint).
                logger.info("trainer_stream_cancelled", extra={"stream_id": stream_id})
                async for _abort_frame in _abort_fail_closed():
                    yield _abort_frame
                return
            except Exception as exc:
                provider_api_key = (
                    getattr(coaching_service, "_api_key", None)
                    if coaching_service is not None
                    else None
                )
                async for _abort_frame in _abort_fail_closed(
                    error_detail=redact_provider_error(exc, api_key=provider_api_key),
                ):
                    yield _abort_frame
            finally:
                if request_id and not stream_singleflight_published:
                    fail_session_request_singleflight(
                        request_key,
                        RuntimeError(
                            "turn stream failed"
                            if stream_failed
                            else "turn stream completed without publishing a payload"
                        ),
                        inflight=core.inflight_session_requests,
                        guard=core.completed_session_requests_guard,
                    )
                if state is not None:
                    core.finalize_stream_persistence(
                        state=state,
                        user_message=stream_user_message,
                        stream_id=stream_id,
                        committed=stream_committed,
                        assistant_message_ids=stream_assistant_message_ids,
                        stream_state=(
                            "completed"
                            if stream_committed
                            else ("failed" if stream_failed else "interrupted")
                        ),
                    )
                core.unregister_stream_cancellation(stream_id)

        core.register_stream_cancellation(stream_id)
        return StreamingResponse(
            cast(AsyncIterator[bytes], generate()), media_type="text/event-stream"
        )

    @router.post("/task/next", response_model=TaskSpec)
    def task_next(request: TaskNextRequest) -> TaskSpec:
        # Intentional super-entry: may bind/create TaskSpec for a live plan only.
        # Must not invent a second LearningPlan, resurrect leftover-not-live, or mint a card.
        workspace_id = core.current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        live_plan = core.require_live_formal_plan_for_explicit_task_next(workspace_id)
        plan_id = str(getattr(live_plan, "id", "") or getattr(live_plan, "plan_id", "") or "").strip()
        profile = runtime.repository.get_profile(workspace_id)
        resolved_response_language = core.effective_response_language(
            workspace_id,
            request.response_language,
        )
        task = coach_support.review_aware_next_task(core.coach_support_deps,
            workspace_id=workspace_id,
            profile=profile,
            focus_area=request.focus_area,
            response_language=resolved_response_language,
        )
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        task = core.clean_active_thread_task(
            task,
            resolved_response_language,
            runtime.memory_service.snapshot(workspace_id).active_thread,
            plan=state.snapshot.plan or live_plan,
            snapshot=state.snapshot,
        )
        meta = dict(task.metadata or {})
        meta["plan_id"] = plan_id
        task = task.model_copy(update={"metadata": meta})
        task = stamp_produced_workspace_record(task, workspace_id)
        state.snapshot.current_task = task
        # Keep live plan identity; do not replace or mint a second LearningPlan.
        if state.snapshot.plan is None:
            state.snapshot.plan = stamp_produced_workspace_record(live_plan, workspace_id)
        runtime.memory_service.persist_turn_context_pressure(workspace_id, current_task=task)
        runtime.save_session_state(state.session_id)
        return task

    @router.post("/task/specify", response_model=TaskSpec)
    def task_specify(request: TaskSpecifyRequest) -> TaskSpec:
        # Intentional super-entry: may mint TaskSpec for a live plan only.
        # Must not invent a second LearningPlan, resurrect leftover-not-live, or mint a card.
        workspace_id = core.current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        live_plan = core.require_live_formal_plan_for_explicit_task_next(
            workspace_id,
            route="/task/specify",
        )
        plan_id = str(getattr(live_plan, "id", "") or getattr(live_plan, "plan_id", "") or "").strip()
        task = stamp_produced_workspace_record(
            runtime.spec_service.specify(request),
            workspace_id,
        )
        meta = dict(task.metadata or {})
        meta["plan_id"] = plan_id
        task = task.model_copy(update={"metadata": meta})
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        state.snapshot.current_task = task
        # Keep live plan identity; do not replace or mint a second LearningPlan.
        if state.snapshot.plan is None:
            state.snapshot.plan = stamp_produced_workspace_record(live_plan, workspace_id)
        runtime.memory_service.persist_turn_context_pressure(workspace_id, current_task=task)
        runtime.save_session_state(state.session_id)
        return task

    @router.post("/evaluate/current-file")
    def evaluate_current_file(request: EvaluateCurrentFileRequest):
        workspace_id = core.current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        request = prepare_training_file_evaluation(runtime, workspace_id, request)
        leftover = core.leftover_plan_state_fields(workspace_id)
        leftover_runtime = leftover.get("leftover_runtime")
        report = stamp_produced_workspace_record(
            runtime.evaluator_service.evaluate_current_file(
                request,
                state.snapshot.current_task,
                leftover_plan=leftover.get("leftover_plan"),
                leftover_runtime=leftover_runtime if isinstance(leftover_runtime, dict) else {},
                leftover_task_title=str(leftover.get("leftover_task_title") or ""),
                response_language=core.workspace_response_language(workspace_id),
            ),
            workspace_id,
        )
        state.snapshot.evaluation = report
        core.persist_evaluation_learning_loop(
            workspace_id=workspace_id,
            state=state,
            report=report,
            action_type="evaluate_current_file",
            fallback_focus_area=(
                Path(str(request.file_path or "")).stem.strip() or "current-file"
            ),
        )
        core.advance_plan_after_evaluation(
            workspace_id=workspace_id,
            state=state,
            report=report,
        )
        core.record_training_practice_evaluation(
            workspace_id=workspace_id,
            state=state,
            request=request,
            report=report,
            evidence_source="ide_current_file",
        )
        state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        runtime.save_session_state(state.session_id)
        return report

    @router.post("/evaluate/snippet")
    def evaluate_snippet(request: EvaluateSnippetRequest):
        workspace_id = core.current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        if str(request.evaluation_source or "").strip().lower() == "training":
            core.require_live_selected_card_for_status(
                workspace_id, str(request.training_card_id or "")
            )
            report = stamp_produced_workspace_record(
                core.training_practice_blocked_report(
                    request,
                    response_language=core.workspace_response_language(workspace_id),
                ),
                workspace_id,
            )
            state.snapshot.evaluation = report
            core.persist_evaluation_learning_loop(
                workspace_id=workspace_id,
                state=state,
                report=report,
                action_type="evaluate_snippet",
                fallback_focus_area="snippet",
            )
            core.advance_plan_after_evaluation(
                workspace_id=workspace_id,
                state=state,
                report=report,
            )
            core.record_training_practice_evaluation(
                workspace_id=workspace_id,
                state=state,
                request=request,
                report=report,
                evidence_source="snippet_or_selection",
            )
            state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
            runtime.save_session_state(state.session_id)
            return report
        leftover = core.leftover_plan_state_fields(workspace_id)
        leftover_runtime = leftover.get("leftover_runtime")
        report = stamp_produced_workspace_record(
            runtime.evaluator_service.evaluate_snippet(
                request,
                state.snapshot.current_task,
                leftover_plan=leftover.get("leftover_plan"),
                leftover_runtime=leftover_runtime if isinstance(leftover_runtime, dict) else {},
                leftover_task_title=str(leftover.get("leftover_task_title") or ""),
                response_language=core.workspace_response_language(workspace_id),
            ),
            workspace_id,
        )
        state.snapshot.evaluation = report
        core.persist_evaluation_learning_loop(
            workspace_id=workspace_id,
            state=state,
            report=report,
            action_type="evaluate_snippet",
            fallback_focus_area="snippet",
        )
        core.advance_plan_after_evaluation(
            workspace_id=workspace_id,
            state=state,
            report=report,
        )
        state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        runtime.save_session_state(state.session_id)
        return report

    @router.post("/learning/signal", response_model=WorkbenchSnapshot)
    def record_learning_signal(request: LearningSignalRequest) -> WorkbenchSnapshot:
        workspace_id = core.current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        concepts = [item.strip() for item in request.concepts if item and item.strip()]
        if not concepts and state.snapshot.current_task is not None:
            concepts = core.task_training_concepts(
                state.snapshot.current_task,
                snapshot=state.snapshot,
                plan=state.snapshot.plan,
            )
        focus_area = (
            (request.focus_area or "").strip()
            or core.live_current_task_focus(state.snapshot)
            or "learning-signal"
        )
        adaptation_outcome = runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=concepts,
            outcome=request.outcome,
            summary=request.summary,
            checks=request.checks,
            missing_requirements=request.missing_requirements,
            action_type=request.action_type,
            # Client-supplied repetition_count is untrusted; server owns increment.
            repetition_count=None,
            focus_area=focus_area,
            scenario=request.scenario,
            verified_result=None,
            blocked_reason=request.blocked_reason,
            abandoned_reason=request.abandoned_reason,
            selected_teaching_asset_ids=request.selected_teaching_asset_ids
            or [item.id for item in state.snapshot.selected_teaching_assets if getattr(item, "id", "")],
            teaching_strategy_context=core.teaching_strategy_context_from_snapshot(state.snapshot),
            verified_by_evaluator=False,
        )
        server_repetition_count = int(getattr(adaptation_outcome, "repetition_count", 1) or 1)
        adaptation_snapshot = runtime.memory_service.snapshot(state.workspace_id)
        adaptation_profile = adaptation_snapshot.coaching_adaptation
        adaptation_workspace = (
            adaptation_snapshot.workspace if isinstance(adaptation_snapshot.workspace, dict) else {}
        )
        recovered_runtime = select_plan_runtime_for_scope(
            adaptation_workspace.get(PLAN_RUNTIME_KEY) or adaptation_workspace.get("latestPlanRuntime"),
            workspace_id,
        )
        updated_plan = None
        signal_base_plan = (
            state.snapshot.plan or runtime.repository.get_latest_plan(workspace_id)
        )
        # Lock window: the revision this request's advance decision builds on.
        signal_base_revision = (
            core.head_plan_revision(workspace_id, signal_base_plan.id)
            if signal_base_plan is not None
            else 0
        )
        if request.outcome not in {"code_landed", "tests_passed"}:
            updated_plan = runtime.planner_service.advance_plan_from_learning_signal(
                signal_base_plan,
                state.snapshot.current_task,
                outcome=request.outcome,
                summary=request.summary,
                verified_result=None,
                blocked_reason=request.blocked_reason,
                abandoned_reason=request.abandoned_reason,
                repetition_count=server_repetition_count,
                focus_area=focus_area,
                next_step_bias=adaptation_profile.next_step_bias if adaptation_profile else None,
                runtime=recovered_runtime,
                existing=recovered_runtime,
            )
        if updated_plan is not None:
            state.snapshot.plan = updated_plan
            core.save_plan_or_conflict(
                workspace_id, updated_plan, expected_revision=signal_base_revision
            )
            core.persist_plan_to_sandbox(workspace_id, updated_plan, reason="learning-signal")
        state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        runtime.save_session_state(state.session_id)
        return state.snapshot

    @router.post("/memory/feedback", response_model=WorkbenchSnapshot)
    def record_user_feedback(request: UserFeedbackRequest) -> WorkbenchSnapshot:
        workspace_id = core.current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
        state = runtime.ensure_session(request.session_id, workspace_id=workspace_id)
        focus_area = (request.focus_area or "").strip() or "general"
        runtime.memory_service.record_user_feedback(
            workspace_id=workspace_id,
            kind=request.kind,
            message=request.message,
            focus_area=focus_area,
            scenario=request.scenario or "coach",
            training_card_id=request.training_card_id or "",
            plan_id=request.plan_id or "",
        )
        state.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
        plan = runtime.repository.get_latest_plan(workspace_id)
        state.snapshot.memory.plan_change_candidates = runtime.repository.list_plan_change_candidates(workspace_id)
        candidate = None
        if request.kind == "plan_mismatch" and plan is not None:
            # Only the genuinely persisted runtime overlay counts here. The
            # attach-time recovered=True stamp (empty restore) synthesizes an
            # empty-step dict via coach_focus_runtime_from_snapshot, which would
            # blank the referenced plan's current_step from the candidate diff.
            _, mismatch_runtime = core.leftover_runtime_for_workspace(workspace_id)
            mismatch_step = live_plan_mismatch_candidate_step(
                plan=plan,
                runtime=mismatch_runtime,
                existing=mismatch_runtime,
                current_step=plan.current_step,
            )
            candidate = PlanChangeCandidate(
                id=f"plan-change:{uuid4().hex}",
                workspace_id=workspace_id,
                plan_id=live_plan_mismatch_candidate_plan_id(
                    plan=plan,
                    runtime=mismatch_runtime,
                    existing=mismatch_runtime,
                    request_plan_id=request.plan_id or "",
                    current_step=plan.current_step,
                ),
                feedback_id=f"feedback:{uuid4().hex}",
                reason=request.message,
                diff={
                    "current_step": mismatch_step,
                    "suggested_action": "Re-scope or reorder the current plan after explicit review.",
                },
                impact={
                    "stage_id": live_runtime_stage_id(
                        plan=plan,
                        runtime=mismatch_runtime,
                        existing=mismatch_runtime,
                        current_step=mismatch_step,
                    ),
                    "verification": plan.verify_method,
                    "formal_plan_changed": False,
                },
            )
            runtime.repository.save_plan_change_candidate(candidate)
            state.snapshot.memory.plan_change_candidates = runtime.repository.list_plan_change_candidates(workspace_id)
        runtime.save_session_state(state.session_id)
        return state.snapshot

    @router.get("/plan/change-candidates", response_model=list[PlanChangeCandidate])
    def list_plan_change_candidates(workspace_id: str, plan_id: str | None = None) -> list[PlanChangeCandidate]:
        return runtime.repository.list_plan_change_candidates(workspace_id, plan_id)

    @router.post("/plan/change-candidates/{candidate_id}/ack", response_model=PlanChangeCandidate)
    def acknowledge_plan_change_candidate(candidate_id: str, payload: dict[str, str] | None = None) -> PlanChangeCandidate:
        candidate = runtime.repository.get_plan_change_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Plan change candidate not found.")
        workspace_id = str((payload or {}).get("workspace_id") or "").strip()
        if workspace_id and workspace_id != candidate.workspace_id:
            raise HTTPException(status_code=409, detail="Candidate belongs to another workspace.")
        if candidate.status != "pending":
            return candidate
        acknowledged = candidate.model_copy(update={
            "status": "acknowledged",
            "acknowledged_at": datetime.now(UTC).isoformat(),
            "acknowledgement_note": str((payload or {}).get("note") or "").strip(),
        })
        runtime.repository.save_plan_change_candidate(acknowledged)
        return acknowledged

    @router.post("/plan/change-candidates/{candidate_id}/reject", response_model=PlanChangeCandidate)
    def reject_plan_change_candidate(candidate_id: str, payload: dict[str, str] | None = None) -> PlanChangeCandidate:
        candidate = runtime.repository.get_plan_change_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Plan change candidate not found.")
        workspace_id = str((payload or {}).get("workspace_id") or "").strip()
        if workspace_id and workspace_id != candidate.workspace_id:
            raise HTTPException(status_code=409, detail="Candidate belongs to another workspace.")
        if candidate.status != "pending":
            return candidate
        rejected = candidate.model_copy(update={
            "status": "rejected",
            "acknowledged_at": datetime.now(UTC).isoformat(),
            "acknowledgement_note": str((payload or {}).get("note") or "").strip(),
        })
        runtime.repository.save_plan_change_candidate(rejected)
        return rejected

    @router.post("/training/card-status", response_model=CardStatusTransitionResponse)
    def training_card_status(request: CardStatusTransitionRequest) -> CardStatusTransitionResponse:
        if request.new_status in {"implemented", "completed"}:
            raise HTTPException(
                status_code=422,
                detail="Use current-file verification before marking a training card implemented or completed.",
            )
        core.require_live_selected_card_for_status(request.workspace_id, request.card_id)
        if request.cancel:
            try:
                runtime.memory_service.cancel_training_reliability(
                    request.workspace_id,
                    request_id=request.request_id,
                    command_id="trainer.training.cardStatusTransition",
                    card_id=request.card_id,
                )
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            card = runtime.memory_service.get_card(request.workspace_id, request.card_id)
            if card is None:
                raise HTTPException(status_code=404, detail="Training card not found.")
            core.refresh_workspace_sessions(request.workspace_id)
            return CardStatusTransitionResponse(card=card)

        captured: list[CardStatusTransitionResponse] = []

        def work() -> dict[str, object]:
            captured.append(
                runtime.memory_service.transition_card_status(
                    request.workspace_id,
                    request.card_id,
                    request.new_status,
                    reason=request.reason,
                )
            )
            structured = runtime.memory_service._structured_for(request.workspace_id)
            return dict(structured._workspace)

        try:
            runtime.memory_service.run_training_reliability(
                request.workspace_id,
                request_id=request.request_id,
                command_id="trainer.training.cardStatusTransition",
                card_id=request.card_id,
                idempotency_key=request.idempotency_key,
                revision=request.revision,
                timeout_ms=request.timeout_ms,
                cancel=False,
                work=work,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        core.refresh_workspace_sessions(request.workspace_id)
        # Same request_id replay/coalesce skips work(); return current card (one mutation).
        if not captured:
            card = runtime.memory_service.get_card(request.workspace_id, request.card_id)
            if card is None:
                raise HTTPException(status_code=404, detail="Training card not found.")
            return CardStatusTransitionResponse(card=card)
        return captured[0]

    @router.post("/training/generate-card", response_model=CardGenerationResponse)
    def training_generate_card(request: CardGenerationRequest) -> CardGenerationResponse:
        # Explicit user generate: pressure blocks invent on coach turns only, not this route
        # (same pattern as leftover /plan/generate still binding a new plan).
        generate_payload: dict[str, object] = {
            "workspace_id": request.workspace_id,
        }
        if isinstance(request.provider, dict) and request.provider:
            generate_payload["provider"] = request.provider
        if request.api_key:
            generate_payload["api_key"] = request.api_key
        if request.last_test_result:
            generate_payload["lastTestResult"] = request.last_test_result
        coaching_service = core.build_coaching_service(generate_payload)
        core.ensure_coach_provider_ready(
            coaching_service,
            response_language=getattr(request, "response_language", None),
        )
        core.reject_if_provider_not_live_usable(
            coaching_service,
            generate_payload,
            getattr(request, "response_language", None),
        )
        try:
            return core.training_generate_and_route_card(
                core.trusted_training_card_request_from_api(request),
                provider_service_override=coaching_service,
            )
        except CardGenerationProviderFailure as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/training/generate-card/stream")
    async def training_generate_card_stream(
        request: CardGenerationRequest,
        http_request: Request,
    ) -> StreamingResponse:
        """Stream visible card-generation text, then persist and route the card."""

        try:
            raw_payload = await http_request.json()
        except Exception:
            raw_payload = {}
        stream_payload = raw_payload if isinstance(raw_payload, dict) else {}
        training_provider_service = runtime.overlay_last_test_on_service(
            core.build_coaching_service(stream_payload)
        )
        core.ensure_coach_provider_ready(
            training_provider_service,
            response_language=getattr(request, "response_language", None),
        )
        core.reject_if_provider_not_live_usable(
            training_provider_service,
            stream_payload,
            getattr(request, "response_language", None),
        )
        core.ensure_streaming_ready(
            training_provider_service,
            getattr(request, "response_language", None),
        )
        stream_id = core.resolve_stream_id(raw_payload)
        stream_id_payload = (
            {"stream_id": stream_id}
            if isinstance(raw_payload, dict)
            and str(raw_payload.get("stream_id") or raw_payload.get("streamId") or "").strip()
            else {}
        )
        request_id = str(getattr(request, "request_id", "") or "").strip()
        if not request_id and isinstance(raw_payload, dict):
            request_id = str(
                raw_payload.get("request_id") or raw_payload.get("requestId") or ""
            ).strip()
        workspace_id = str(getattr(request, "workspace_id", "") or "").strip()
        # Fail-closed when request_id present: same id cannot remint after cancel/fail.
        request_key = (workspace_id, "generate-card", request_id) if request_id else None

        def _publish_training_card_stream_response(payload: dict[str, object]) -> dict[str, object]:
            if request_key is None:
                return payload
            return publish_session_request_singleflight(
                request_key,
                payload,
                completed=core.completed_training_card_requests,
                inflight=core.inflight_training_card_requests,
                guard=core.completed_training_card_requests_guard,
            )

        def _fail_training_card_stream_singleflight(error: BaseException) -> None:
            if request_key is None:
                return
            fail_session_request_singleflight(
                request_key,
                error,
                inflight=core.inflight_training_card_requests,
                guard=core.completed_training_card_requests_guard,
            )

        async def _waiter_training_card_stream(
            kind: Literal["wait", "cached"],
            cached_response: dict[str, object] | None,
            shared_future: asyncio.Future | None,
        ):
            try:
                shared_payload: dict[str, object]
                if kind == "wait":
                    assert shared_future is not None
                    shared_payload = cast("dict[str, object]", await shared_future)
                else:
                    assert cached_response is not None
                    shared_payload = cached_response
                reliability = shared_payload.get("reliability")
                reliability_outcome = (
                    str(reliability.get("outcome") or "") if isinstance(reliability, dict) else ""
                )
                yield core.sse_complete_frame(
                    tokens=0,
                    response_data=shared_payload,
                    stream_id=stream_id,
                    request_id=request_id or None,
                    provider_live_usable=reliability_outcome != "failure",
                    provider_failure_detected=reliability_outcome == "failure",
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure_payload = core.attach_operation_reliability(
                    {},
                    phase="acked",
                    outcome="failure",
                    request_id=request_id or None,
                )
                yield core.stream_status_event("failed", stream_id)
                yield core.stream_status_event("acked", stream_id)
                yield (
                    "event: error\n"
                    f"data: {json.dumps({'error': redact_provider_error(exc, api_key=getattr(training_provider_service, '_api_key', None)), 'stream_id': stream_id, 'terminal': True})}\n\n"
                )
                yield core.sse_complete_frame(
                    tokens=0,
                    response_data=failure_payload,
                    stream_id=stream_id,
                    outcome="failure",
                    request_id=request_id or None,
                    provider_failure_detected=True,
                )

        if request_key is not None:
            kind, cached_response, shared_future = claim_session_request_singleflight(
                request_key,
                completed=core.completed_training_card_requests,
                inflight=core.inflight_training_card_requests,
                guard=core.completed_training_card_requests_guard,
            )
            if kind in ("wait", "cached"):
                # Do not register stream_id — owner already holds cancellation slot.
                return StreamingResponse(
                    _waiter_training_card_stream(kind, cached_response, shared_future),
                    media_type="text/event-stream",
                )

        core.register_stream_cancellation(stream_id)

        async def generate():
            token_count = 0
            generated_card: TrainingCardCandidateSnapshot | None = None
            stream_singleflight_published = False

            async def _abort_fail_closed(*, error_detail: object | None = None):
                """Emit failed→acked + publish failure complete so same request_id cannot remint."""
                nonlocal stream_singleflight_published
                failure_payload: dict[str, object] = core.attach_operation_reliability(
                    {},
                    phase="acked",
                    outcome="failure",
                    request_id=request_id or None,
                )
                if request_key is not None and not stream_singleflight_published:
                    failure_payload = _publish_training_card_stream_response(failure_payload)
                    stream_singleflight_published = True
                yield core.stream_status_event("failed", stream_id)
                if error_detail is not None:
                    yield (
                        "event: error\n"
                        f"data: {json.dumps({'error': error_detail, 'stream_id': stream_id, 'terminal': True, **stream_id_payload})}\n\n"
                    )
                yield core.stream_status_event("acked", stream_id)
                yield core.sse_complete_frame(
                    tokens=token_count,
                    response_data=failure_payload,
                    stream_id=stream_id,
                    outcome="failure",
                    request_id=request_id or None,
                    provider_failure_detected=True,
                )

            try:
                if core.stream_cancellation_requested(stream_id):
                    async for _abort_frame in _abort_fail_closed():
                        yield _abort_frame
                    return
                generator = core.card_generation_service_for(training_provider_service)
                trusted_request = core.trusted_training_card_request_from_api(request)
                request_payload = core.prepare_training_card_request(trusted_request)
                existing_card = (
                    core.existing_open_resource_training_card(request_payload)
                    if request_payload.source == "resource_knowledge" and request_payload.resource_id
                    else None
                )
                if existing_card is not None:
                    if core.stream_cancellation_requested(stream_id):
                        async for _abort_frame in _abort_fail_closed():
                            yield _abort_frame
                        return
                    response = core.training_generate_and_route_card(
                        trusted_request,
                        generated_card=existing_card,
                        provider_service_override=training_provider_service,
                    )
                    response_data = response.model_dump(mode="json")
                    response_data = core.attach_operation_reliability(
                        response_data,
                        phase="acked",
                        outcome="success",
                        request_id=request_id or None,
                    )
                    if request_key is not None:
                        response_data = _publish_training_card_stream_response(response_data)
                        stream_singleflight_published = True
                    yield core.sse_complete_frame(
                        tokens=0,
                        response_data=response_data,
                        stream_id=stream_id,
                        request_id=request_id or None,
                    )
                    return
                async for event in generator.generate_card_stream(
                    request_payload.source,
                    request_payload,
                    cancel_event=core.stream_cancellation_events.get(stream_id),
                ):
                    if core.stream_cancellation_requested(stream_id):
                        async for _abort_frame in _abort_fail_closed():
                            yield _abort_frame
                        return
                    if event.chunk:
                        token_count += 1
                        yield f"data: {json.dumps({'chunk': event.chunk, **stream_id_payload})}\n\n"
                    if event.card is not None:
                        generated_card = event.card
                if core.stream_cancellation_requested(stream_id):
                    # Built candidate but aborted before publish/bind: no remint, leftover intact.
                    async for _abort_frame in _abort_fail_closed():
                        yield _abort_frame
                    return
                if generated_card is None:
                    raise RuntimeError("Card generation stream ended without a card.")
                response = core.training_generate_and_route_card(
                    trusted_request,
                    generated_card=generated_card,
                    provider_service_override=training_provider_service,
                )
                response_data = response.model_dump(mode="json")
                response_data = core.attach_operation_reliability(
                    response_data,
                    phase="acked",
                    outcome="success",
                    request_id=request_id or None,
                )
                if request_key is not None:
                    response_data = _publish_training_card_stream_response(response_data)
                    stream_singleflight_published = True
                yield core.sse_complete_frame(
                    tokens=token_count,
                    response_data=response_data,
                    stream_id=stream_id,
                    request_id=request_id or None,
                )
            except asyncio.CancelledError:
                logger.info("trainer_training_card_stream_cancelled", extra={"stream_id": stream_id})
                async for _abort_frame in _abort_fail_closed():
                    yield _abort_frame
                return
            except Exception as exc:
                # Local admission/indexing gates are actionable domain errors,
                # not provider failures. Keep their safe explanation in SSE.
                error = exc.detail if isinstance(exc, HTTPException) else exc
                async for _abort_frame in _abort_fail_closed(
                    error_detail=redact_provider_error(
                        error,
                        api_key=getattr(training_provider_service, "_api_key", None),
                    ),
                ):
                    yield _abort_frame
            finally:
                if request_key is not None and not stream_singleflight_published:
                    _fail_training_card_stream_singleflight(
                        RuntimeError("training generate-card stream completed without publishing")
                    )
                core.unregister_stream_cancellation(stream_id)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @router.get("/training/active-card", response_model=ActiveCardSelectionResult)
    def training_active_card(workspace_id: str, session_id: str | None = None) -> ActiveCardSelectionResult:
        resolved_workspace_id = core.current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        selection = core.select_active_training_card(resolved_workspace_id)
        snapshot = runtime.memory_service.snapshot(resolved_workspace_id)
        existing = snapshot.active_training_card_routing
        if core.routing_changed(existing, selection):
            runtime.memory_service.persist_active_card_selection(resolved_workspace_id, selection)
            core.refresh_workspace_sessions(resolved_workspace_id)
        return runtime.memory_service.snapshot(resolved_workspace_id).active_training_card_routing or selection

    @router.post("/training/flashcard/answer")
    def training_flashcard_answer(request: FlashcardAnswerRequest) -> dict[str, object]:
        attempt = runtime.memory_service.submit_flashcard_answer(
            request.workspace_id,
            request.card_id,
            learner_answer=request.learner_answer,
            selected_option_index=request.selected_option_index,
            selected_option_indices=request.selected_option_indices,
            fill_blank_answers=request.fill_blank_answers,
            sort_order=request.sort_order,
        )
        core.refresh_workspace_sessions(request.workspace_id)
        card = runtime.memory_service.get_card(request.workspace_id, request.card_id)
        return {
            "correct": attempt.correct,
            "score": attempt.score,
            "detail": attempt.detail,
            "feedback": attempt.feedback,
            "card_status": card.status if card is not None else None,
            "retry_required": not attempt.correct,
            "attempt": attempt.model_dump(mode="json"),
        }

    @router.post("/training/theory-drill/answer")
    def training_theory_drill_answer(request: TheoryDrillAnswerRequest) -> dict[str, object]:
        snapshot = runtime.memory_service.snapshot(request.workspace_id)
        theory_drill = snapshot.theory_drill
        if theory_drill is None:
            raise HTTPException(
                status_code=404,
                detail="No current theory drill was found. Refresh Training and start a new drill.",
            )
        if theory_drill.id != request.theory_drill_id:
            raise HTTPException(
                status_code=409,
                detail="This theory drill is no longer current. Refresh Training to load the latest drill.",
            )
        question = next(
            (
                item for item in theory_drill.questions if item.id == request.question_id
            ),
            None,
        )
        if question is None:
            raise HTTPException(
                status_code=409,
                detail="This theory question is no longer current. Refresh Training to load the latest question.",
        )
        answer = re.sub(r"\s+", " ", request.learner_answer.strip().lower())
        reference = re.sub(r"\s+", " ", question.answer.strip().lower())
        if not reference:
            raise HTTPException(
                status_code=409,
                detail="This theory question has no answer key yet. Refresh Training to load a gradeable question.",
            )
        reference_tokens = {
            token for token in re.findall(r"[a-z0-9][a-z0-9_-]*", reference) if len(token) > 2
        }
        prompt_tokens = {
            token
            for token in re.findall(r"[a-z0-9][a-z0-9_-]*", question.prompt.lower())
            if len(token) > 2
        }
        answer_tokens = {
            token for token in re.findall(r"[a-z0-9][a-z0-9_-]*", answer) if len(token) > 2
        }
        grounded_terms = reference_tokens | prompt_tokens
        dependency_hint = re.sub(r"[^a-z0-9]+", "", question.dependency_key.lower())
        normalized_answer = re.sub(r"[^a-z0-9]+", "", answer)
        has_dependency_context = bool(dependency_hint and dependency_hint in normalized_answer)
        correct = bool(
            answer
            and (
                answer == reference
                or reference in answer
                or (
                    has_dependency_context
                    and len(answer_tokens & grounded_terms) >= 2
                )
                or (
                    not dependency_hint
                    and len(answer_tokens & grounded_terms) >= 2
                )
            )
        )
        detail = (
            "Theory drill answer is grounded enough to continue."
            if correct
            else "Answer is still too thin; rebuild the explanation before widening scope."
        )
        if correct:
            updated, _ = runtime.memory_service.apply_theory_drill_action(
                request.workspace_id,
                theory_drill_id=request.theory_drill_id,
                action="reopen",
                note="Theory drill answer recorded.",
            )
            if updated is None:
                raise HTTPException(
                    status_code=409,
                    detail="This theory drill changed before the answer could be saved. Refresh Training and try again.",
                )
        core.refresh_workspace_sessions(request.workspace_id)
        return {"ok": True, "detail": detail, "correct": correct}

    @router.post("/training/practice-return")
    def training_practice_return(request: PracticeReturnRequest) -> dict[str, object]:
        if runtime.memory_service.get_card(request.workspace_id, request.card_id) is None:
            raise HTTPException(status_code=404, detail="Training card not found.")
        updated = runtime.memory_service.record_training_practice_evaluation_result(
            workspace_id=request.workspace_id,
            card_id=request.card_id,
            passed=request.passed,
            summary=request.summary,
            next_step=request.next_step,
            focus_area=request.focus_area,
            failed_checks=request.failed_checks,
            missing_requirements=request.missing_requirements,
            evidence_source=request.evidence_source,
            verified_by_evaluator=False,
            request_id=request.request_id,
            idempotency_key=request.idempotency_key,
            revision=request.revision,
            timeout_ms=request.timeout_ms,
            cancel=request.cancel,
        )
        core.refresh_workspace_sessions(request.workspace_id)
        return {"ok": True, "workspace": updated}

    @router.post("/training/review-queue/action")
    def training_review_queue_action(request: ReviewQueueActionRequest) -> dict[str, object]:
        actions = runtime.memory_service.apply_review_queue_action(
            request.workspace_id,
            concept=request.concept,
            action=request.action,
            scope=request.scope,
            focus_area=request.focus_area,
            task_hint=request.task_hint,
            note=request.note,
            batch_limit=request.batch_limit,
        )
        core.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": True,
            "detail": f"Applied review queue action '{request.action}'.",
            "actions": [item.model_dump(mode="json") for item in actions],
        }

    @router.post("/training/review-artifact/action")
    def training_review_artifact_action(request: ReviewArtifactActionRequest) -> dict[str, object]:
        artifact, history = runtime.memory_service.apply_review_artifact_action(
            request.workspace_id,
            review_artifact_id=request.review_artifact_id,
            action=request.action,
            note=request.note,
            edit_patch=request.edit_patch,
        )
        core.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": artifact is not None,
            "detail": "Review result saved." if artifact is not None else "Review item was not found.",
            "review_artifact": artifact.model_dump(mode="json") if artifact is not None else None,
            "history": [item.model_dump(mode="json") for item in history],
        }

    @router.post("/training/scenario-lab/action")
    def training_scenario_lab_action(request: ScenarioLabActionRequest) -> dict[str, object]:
        try:
            scenario_lab, history = runtime.memory_service.apply_scenario_lab_action(
                request.workspace_id,
                scenario_lab_id=request.scenario_lab_id,
                action=request.action,
                note=request.note,
                review_outcome=request.review_outcome,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if scenario_lab is None:
            raise HTTPException(
                status_code=409,
                detail="This scenario lab is no longer current. Refresh Training to load the current lab.",
            )
        core.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": True,
            "detail": "Scenario lab updated.",
            "scenario_lab": scenario_lab.model_dump(mode="json"),
            "history": [item.model_dump(mode="json") for item in history],
        }

    @router.post("/training/scenario-lab/restore")
    def training_scenario_lab_restore(request: ScenarioLabRestoreRequest) -> dict[str, object]:
        scenario_lab, history = runtime.memory_service.restore_scenario_lab_history(
            request.workspace_id,
            scenario_lab_id=request.scenario_lab_id,
            history_entry_id=request.history_entry_id,
            history_version=request.history_version,
            note=request.note,
        )
        core.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": scenario_lab is not None,
            "scenario_lab": scenario_lab.model_dump(mode="json") if scenario_lab is not None else None,
            "history": [item.model_dump(mode="json") for item in history],
        }

    @router.post("/training/theory-drill/restore")
    def training_theory_drill_restore(request: TheoryDrillRestoreRequest) -> dict[str, object]:
        theory_drill, history = runtime.memory_service.restore_theory_drill_history(
            request.workspace_id,
            theory_drill_id=request.theory_drill_id,
            history_entry_id=request.history_entry_id,
            history_version=request.history_version,
            note=request.note,
        )
        core.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": theory_drill is not None,
            "theory_drill": theory_drill.model_dump(mode="json") if theory_drill is not None else None,
            "history": [item.model_dump(mode="json") for item in history],
        }

    @router.post("/training/review-artifact/restore")
    def training_review_artifact_restore(request: ReviewArtifactRestoreRequest) -> dict[str, object]:
        artifact, history = runtime.memory_service.restore_review_artifact_history(
            request.workspace_id,
            review_artifact_id=request.review_artifact_id,
            history_entry_id=request.history_entry_id,
            history_version=request.history_version,
            note=request.note,
        )
        core.refresh_workspace_sessions(request.workspace_id)
        return {
            "ok": artifact is not None,
            "review_artifact": artifact.model_dump(mode="json") if artifact is not None else None,
            "history": [item.model_dump(mode="json") for item in history],
        }

    @router.post("/training/dependency-skill-map/action")
    def training_dependency_skill_map_action(request: DependencySkillMapActionRequest) -> dict[str, object]:
        workspace_id = core.current_workspace_id(workspace_id=request.workspace_id)
        action = request.action.strip()
        if action in {"mark_practiced", "mark_applied", "mark_transferable"}:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Run Verify current file before Trainer updates dependency mastery. "
                    "Your current stage has not changed."
                ),
            )
        try:
            maps, history, scenario_lab = runtime.memory_service.apply_dependency_skill_map_action(
                workspace_id,
                dependency_key=request.dependency_key,
                action=action,
                note=request.note,
                focus_item_key=request.focus_item_key,
                related_api=request.related_api,
                scenario=request.scenario,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not maps or not history:
            raise HTTPException(
                status_code=409,
                detail="Dependency skill map changed before the action could be saved. Refresh Training and try again.",
            )
        core.refresh_workspace_sessions(workspace_id)
        return {
            "ok": True,
            "detail": (
                "Trainer is waiting for current-file verification before changing dependency mastery."
                if action == "request_verification"
                else "Dependency training action recorded."
            ),
            "maps": [item.model_dump(mode="json") for item in maps],
            "history": [item.model_dump(mode="json") for item in history],
            "scenario_lab": scenario_lab.model_dump(mode="json") if scenario_lab is not None else None,
        }

    @router.post("/training/dependency-skill-map/restore")
    def training_dependency_skill_map_restore(request: DependencySkillMapRestoreRequest) -> dict[str, object]:
        workspace_id = core.current_workspace_id(workspace_id=request.workspace_id)
        maps, history = runtime.memory_service.restore_dependency_skill_map_history(
            workspace_id,
            dependency_key=request.dependency_key,
            history_entry_id=request.history_entry_id,
            note=request.note,
        )
        core.refresh_workspace_sessions(workspace_id)
        return {
            "ok": bool(maps),
            "maps": [item.model_dump(mode="json") for item in maps],
            "history": [item.model_dump(mode="json") for item in history],
        }


    # Handler cross-references (e.g. /turn -> session_message).
    core.get_snapshot = get_snapshot
    core.health = health
    core.session_start = session_start
    core.session_message = session_message
    core.session_history = session_history
    core.session_list = session_list
    core.session_activate = session_activate
    core.list_session_checkpoints = list_session_checkpoints
    core.read_session_checkpoint = read_session_checkpoint
    core.replay_session_checkpoint = replay_session_checkpoint
    core.resume_session_checkpoint = resume_session_checkpoint
    core.turn = turn
    core.cancel_stream = cancel_stream
    core.session_steer = session_steer
    core.session_message_stream = session_message_stream
    core.turn_stream = turn_stream
    core.task_next = task_next
    core.task_specify = task_specify
    core.evaluate_current_file = evaluate_current_file
    core.evaluate_snippet = evaluate_snippet
    core.record_learning_signal = record_learning_signal
    core.record_user_feedback = record_user_feedback
    core.list_plan_change_candidates = list_plan_change_candidates
    core.acknowledge_plan_change_candidate = acknowledge_plan_change_candidate
    core.reject_plan_change_candidate = reject_plan_change_candidate
    core.training_card_status = training_card_status
    core.training_generate_card = training_generate_card
    core.training_generate_card_stream = training_generate_card_stream
    core.training_active_card = training_active_card
    core.training_flashcard_answer = training_flashcard_answer
    core.training_theory_drill_answer = training_theory_drill_answer
    core.training_practice_return = training_practice_return
    core.training_review_queue_action = training_review_queue_action
    core.training_review_artifact_action = training_review_artifact_action
    core.training_scenario_lab_action = training_scenario_lab_action
    core.training_scenario_lab_restore = training_scenario_lab_restore
    core.training_theory_drill_restore = training_theory_drill_restore
    core.training_review_artifact_restore = training_review_artifact_restore
    core.training_dependency_skill_map_action = training_dependency_skill_map_action
    core.training_dependency_skill_map_restore = training_dependency_skill_map_restore

    return router
