"""Session lifecycle, snapshot, checkpoints, synchronous turn, and stream control routes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from ...core.models import (
    AgentCheckpointAccessRequest,
    ChatMessage,
    SessionMessageRequest,
    SessionMessageResponse,
    SessionStartRequest,
    TurnRequest,
    UserProfile,
)
from ...llm.provider_service import ProviderService
from ...resources.research_brief import preparation_requested
from .. import coach_support
from .._helpers import localized_text
from .._singleflight import (
    claim_session_request_singleflight,
    publish_session_request_singleflight,
)
from ..coach_support import CoachTurnPayload
from ..router_support import (
    _attach_requested_workspace_files,
    _normalize_resource_turn_request,
    _resolve_agent_loop_enabled,
    _stamp_library_sandbox_work,
    _workspace_snapshot_from_payload,
    register_request_workspace_path,
)
from ..routes.resources import PrepareResearchTurn
from ..runtime import SessionState, TrainerRuntime
from .core_shared import (
    _record_coach_turn_event,
    finish_research_preparation,
    observe_goal_for_request,
    overlay_completed_session_or_turn_response,
)

if TYPE_CHECKING:
    from .core import CoreRouteDeps

SessionMessageHandler = Callable[[dict[str, Any]], Awaitable[object]]


def _make_owner_task_cleanup(
    core: CoreRouteDeps,
    *,
    owner_future: asyncio.Future[dict[str, object]] | None,
    request_key: tuple[str, str, str],
    missing_payload_message: str,
) -> Callable[[asyncio.Task[Any]], None]:
    def _cleanup(task: asyncio.Task[Any]) -> None:
        if owner_future is None or owner_future.done():
            return
        with core.domain.completed_session_requests_guard:
            core.domain.inflight_session_requests.pop(request_key, None)
            cached = core.domain.completed_session_requests.get(request_key)
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
        owner_future.set_exception(RuntimeError(missing_payload_message))

    return _cleanup


def _handle_intake_profile_session_start(
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    *,
    payload: dict[str, Any],
    requested_response_language: str | None,
) -> dict[str, object]:
    workspace_context = payload.get("workspace_context", {})
    workspace_id = core.domain.current_workspace_id(
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
    project_provisioning = core.domain.validate_project_provisioning_or_repair(
        workspace_id,
        requested_response_language,
    )
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
    core.domain.persist_requested_response_language(workspace_id, requested_response_language)
    start_response_language = core.domain.effective_response_language(
        workspace_id,
        requested_response_language,
        str(payload.get("initial_message") or "").strip() or None,
    )
    state = runtime.start_session(workspace_id, workspace_name)
    if workspace_path:
        core.domain.maybe_persist_first_look_from_path(
            workspace_id,
            str(workspace_path),
            response_language=start_response_language,
            workspace_file_snapshot=_workspace_snapshot_from_payload(payload),
            remote_name=str(remote_name or "").strip() or None,
        )
    should_seed_learning_project_prompt = core.domain.workspace_learning_project_prompt_needed(workspace_id)
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
                content=core.domain.workspace_learning_project_prompt_text(
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


def _maybe_handle_pending_learning_project_prompt(
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    *,
    state: SessionState,
    request: SessionMessageRequest,
    profile: UserProfile | None,
    attachment_delivery: dict[str, object] | None,
) -> dict[str, object] | None:
    learning_project_state = core.domain.workspace_learning_project_state(state.workspace_id)
    if learning_project_state.get("prompt_status") != "pending":
        return None
    handled_reply: str | None = None
    if core.domain.message_confirms_learning_project_folder(request.message):
        _linked_root, handled_reply = core.domain.adopt_workspace_learning_project_folder(
            workspace_id=state.workspace_id,
            workspace_name=state.workspace_name,
            response_language=request.response_language,
        )
    elif core.domain.message_rejects_learning_project_folder(request.message):
        runtime.memory_service.update_workspace_state(
            state.workspace_id,
            learning_project_prompt_status="dismissed",
        )
        handled_reply = localized_text(
            "Okay. Trainer will keep the current sandbox arrangement for now and will not create a learning project folder yet.",
            "好。Trainer 先保留当前的 sandbox 方式，暂时不创建学习项目文件夹。",
            request.response_language,
        )
    if not handled_reply:
        return None
    state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
    state.snapshot.profile = profile
    coach_support.hydrate_snapshot(
        core.coach_support_deps,
        state.snapshot,
        response_language=request.response_language,
        answer_mode=request.answer_mode or (profile.answer_policy if profile else None),
        scenario="general",
        learner_signal="steady",
        message=request.message,
        active_view=request.active_view,
    )
    response = coach_support.build_session_response(
        core.coach_support_deps,
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
    return core.domain.json_object_payload(response)


async def _generate_session_assistant_reply(
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    *,
    payload: dict[str, Any],
    request: SessionMessageRequest,
    workspace_id: str,
    state: SessionState,
    profile: UserProfile | None,
    coaching_service: ProviderService,
    coach_turn: CoachTurnPayload,
    scenario: str,
    use_agent_loop: bool,
    guided_training_prefers_local_reply: bool,
    guided_training_local_reply: dict[str, str] | None,
    attachments_payload: list[dict[str, Any]],
    raw_requested_answer_mode: str,
    saved_answer_mode: str,
) -> tuple[str, CoachTurnPayload, str, dict[str, object], bool]:
    agent_meta: dict[str, object] = {}
    language_corruption_detected = False

    preflight_language_probe = await asyncio.to_thread(
        core.domain.detect_provider_language_corruption,
        coaching_service,
        message=request.message,
        response_language=request.response_language,
        coach_context=dict(coach_turn["coach_context"]),
    )
    if preflight_language_probe is not None:
        language_corruption_detected = True
        coach_turn = core.domain.extract_coach_turn_payload(
            core.domain.isolate_preflight_language_corruption_turn(
                core.domain.coach_turn_mapping(coach_turn),
                message=request.message,
                current_file=request.current_file.model_dump() if request.current_file else None,
            )
        )
        assistant_content, updated_coach_turn, agent_meta = core.domain.apply_language_corruption_override(
            coaching_service=coaching_service,
            snapshot=state.snapshot,
            coach_turn=core.domain.coach_turn_mapping(coach_turn),
            message=request.message,
            response_language=request.response_language,
            allow_guided_recovery=False,
        )
        coach_turn = core.domain.extract_coach_turn_payload(updated_coach_turn)
        core.domain.ensure_explicit_training_card_after_language_block(
            state=state,
            message=request.message,
            current_file=request.current_file,
            response_language=request.response_language,
            fallback_scenario=str(coach_turn.get("scenario") or scenario),
            force_training_card=(
                core.domain.auto_preference_requests_training_card(
                    request.message,
                    requested_scenario=str(coach_turn.get("scenario") or scenario),
                    requested_answer_mode=raw_requested_answer_mode,
                    saved_answer_mode=saved_answer_mode,
                    profile=profile,
                )
                or core.domain.auto_lane_learn_first_force_training_card(
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
        return assistant_content, coach_turn, scenario, agent_meta, language_corruption_detected

    if guided_training_local_reply is not None:
        assistant_content, updated_coach_turn, agent_meta = core.domain.apply_guided_training_visible_fallback(
            coach_turn=core.domain.coach_turn_mapping(coach_turn),
            fallback=guided_training_local_reply,
        )
        coach_turn = core.domain.extract_coach_turn_payload(updated_coach_turn)
        return assistant_content, coach_turn, scenario, agent_meta, language_corruption_detected

    if use_agent_loop and not guided_training_prefers_local_reply:
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
            protocol=(
                getattr(coaching_service._config, "protocol", None)
                if coaching_service._config
                else None
            ),
            history=core.domain.build_conversation_history(
                state.snapshot.messages,
                active_view=request.active_view,
                drop_latest_user=True,
            ),
        )
        assistant_content = str(agent_outcome.get("content") or "").strip()
        agent_resume_thread = str(agent_outcome.get("resume_thread") or "").strip()
        if not agent_resume_thread:
            agent_resume_thread = core.domain.build_resume_thread_text(
                str(agent_outcome.get("summary") or "").strip(),
                str(agent_outcome.get("next_step") or "").strip(),
                response_language=request.response_language,
            )
        runtime.record_agentic_cost_entry(
            workspace_id=workspace_id,
            session_id=str(state.session_id or "") or None,
            outcome=agent_outcome,
            model=getattr(coaching_service._config, "model", None)
            if coaching_service._config
            else None,
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
        core.domain.apply_attachment_delivery_metadata(agent_meta, agent_outcome)
        original_agent_stop_reason = str(agent_outcome.get("stop_reason") or "").strip()
        local_sequence_fallback = core.domain.build_local_sequence_visible_fallback(
            coach_context=dict(coach_turn["coach_context"]),
            response_language=request.response_language,
        )
        force_local_sequence = bool(
            local_sequence_fallback is not None
            and (
                original_agent_stop_reason == "empty_response"
                or not core.domain.reply_explicitly_lists_prepared_sequence(
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
                    history=core.domain.build_conversation_history(
                        state.snapshot.messages,
                        active_view=request.active_view,
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
        updated_coach_turn = core.domain.merge_agent_finalize_into_coach_turn(
            core.domain.coach_turn_mapping(coach_turn),
            summary=agent_outcome.get("summary") or (local_sequence_fallback or {}).get("summary"),
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
        coach_turn = core.domain.extract_coach_turn_payload(updated_coach_turn)
        return assistant_content, coach_turn, scenario, agent_meta, language_corruption_detected

    assistant_content = await coaching_service.coaching_reply(
        profile,
        request.message,
        request.current_file.model_dump() if request.current_file else None,
        response_language=request.response_language,
        answer_mode=request.answer_mode,
        coach_context=dict(coach_turn["coach_context"]),
        history=core.domain.build_conversation_history(
            state.snapshot.messages,
            active_view=request.active_view,
            drop_latest_user=True,
        ),
    )
    return assistant_content, coach_turn, scenario, agent_meta, language_corruption_detected


def _apply_session_reply_overrides_and_fallbacks(
    core: CoreRouteDeps,
    *,
    workspace_id: str,
    state: SessionState,
    request: SessionMessageRequest,
    profile: UserProfile | None,
    coaching_service: ProviderService,
    assistant_content: str,
    coach_turn: CoachTurnPayload,
    scenario: str,
    agent_meta: dict[str, object],
    language_corruption_detected: bool,
    raw_requested_answer_mode: str,
    saved_answer_mode: str,
) -> tuple[str, CoachTurnPayload, str, dict[str, object], bool, bool]:
    provider_failure_detected = False
    provider_empty_reply_override = core.domain.consume_provider_empty_reply_override(
        coaching_service=coaching_service,
        snapshot=state.snapshot,
        coach_turn=core.domain.coach_turn_mapping(coach_turn),
        response_language=request.response_language,
        assistant_content=assistant_content,
    )
    if provider_empty_reply_override is not None:
        provider_failure_detected = True
        assistant_content, updated_coach_turn, override_meta = provider_empty_reply_override
        coach_turn = core.domain.extract_coach_turn_payload(updated_coach_turn)
        agent_meta.update(override_meta)
    else:
        provider_failure_override = core.domain.consume_provider_reply_failure_override(
            coaching_service=coaching_service,
            snapshot=state.snapshot,
            coach_turn=core.domain.coach_turn_mapping(coach_turn),
            message=request.message,
            response_language=request.response_language,
            workspace_id=state.workspace_id,
        )
        if provider_failure_override is not None:
            provider_failure_detected = True
            assistant_content, updated_coach_turn, override_meta = provider_failure_override
            coach_turn = core.domain.extract_coach_turn_payload(updated_coach_turn)
            agent_meta.update(override_meta)
        elif not language_corruption_detected and coaching_service.detect_language_corruption(
            message=request.message,
            reply=assistant_content,
            response_language=request.response_language,
        ):
            language_corruption_detected = True
            assistant_content, updated_coach_turn, override_meta = (
                core.domain.apply_language_corruption_override(
                    coaching_service=coaching_service,
                    snapshot=state.snapshot,
                    coach_turn=core.domain.coach_turn_mapping(coach_turn),
                    message=request.message,
                    response_language=request.response_language,
                    reply_corruption=True,
                )
            )
            coach_turn = core.domain.extract_coach_turn_payload(updated_coach_turn)
            core.domain.ensure_explicit_training_card_after_language_block(
                state=state,
                message=request.message,
                current_file=request.current_file,
                response_language=request.response_language,
                fallback_scenario=str(coach_turn.get("scenario") or scenario),
                force_training_card=(
                    core.domain.auto_preference_requests_training_card(
                        request.message,
                        requested_scenario=str(coach_turn.get("scenario") or scenario),
                        requested_answer_mode=raw_requested_answer_mode,
                        saved_answer_mode=saved_answer_mode,
                        profile=profile,
                    )
                    or core.domain.auto_lane_learn_first_force_training_card(
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
        if core.domain.grounded_resource_contract_needs_repair(
            assistant_content,
            coach_context=dict(coach_turn["coach_context"]),
        ):
            resource_contract_fallback = core.domain.build_grounded_resource_contract_visible_fallback(
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
            updated_coach_turn = core.domain.merge_agent_finalize_into_coach_turn(
                core.domain.coach_turn_mapping(coach_turn),
                summary=resource_contract_fallback["summary"],
                next_step=resource_contract_fallback["next_step"],
                blocker=agent_meta.get("blocker"),
                resume_thread=resource_contract_fallback["resume_thread"],
                decision=agent_meta.get("decision"),
                teaching_note=resource_contract_fallback["teaching_note"],
                confidence=agent_meta.get("confidence"),
                evidence=agent_meta.get("evidence"),
            )
            coach_turn = core.domain.extract_coach_turn_payload(updated_coach_turn)
        assistant_content, updated_coach_turn, agent_meta, _guided_lane_repaired = (
            core.domain.apply_guided_lane_visible_fallback(
                reply=assistant_content,
                scenario=str(coach_turn.get("scenario") or scenario),
                learner_message=request.message,
                response_language=request.response_language,
                coach_turn=core.domain.coach_turn_mapping(coach_turn),
                agent_meta=agent_meta,
            )
        )
        coach_turn = core.domain.extract_coach_turn_payload(updated_coach_turn)
        core.domain.ensure_explicit_training_card_after_coach_reply(
            state=state,
            message=request.message,
            current_file=request.current_file,
            response_language=request.response_language,
            fallback_scenario=str(coach_turn.get("scenario") or scenario),
            force_training_card=(
                core.domain.auto_preference_requests_training_card(
                    request.message,
                    requested_scenario=str(coach_turn.get("scenario") or scenario),
                    requested_answer_mode=raw_requested_answer_mode,
                    saved_answer_mode=saved_answer_mode,
                    profile=profile,
                )
                or core.domain.auto_lane_learn_first_force_training_card(
                    request.message,
                    requested_scenario=str(coach_turn.get("scenario") or scenario),
                    requested_answer_mode=raw_requested_answer_mode,
                    saved_answer_mode=saved_answer_mode,
                    profile=profile,
                )
            ),
            provider_service_override=coaching_service,
        )
    return (
        assistant_content,
        coach_turn,
        scenario,
        agent_meta,
        language_corruption_detected,
        provider_failure_detected,
    )


async def _run_session_message_locked(
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    *,
    payload: dict[str, Any],
    request: SessionMessageRequest,
    workspace_id: str,
    state: SessionState,
    finish_session_response: Callable[[dict[str, object]], dict[str, object]],
) -> object:
    register_request_workspace_path(runtime, state.workspace_id, payload, request)
    profile = core.domain.resolved_profile(state.workspace_id)
    raw_requested_answer_mode = str(
        payload.get("answer_mode") or payload.get("answerMode") or ""
    ).strip()
    saved_answer_mode = str(core.domain.workspace_preferences(workspace_id).get("answer_mode") or "").strip()
    request = core.domain.request_with_workspace_defaults(
        request,
        workspace_id=workspace_id,
        profile=profile,
    )
    profile = core.domain.profile_with_teaching_style(profile, request.teaching_style)

    coaching_service = runtime.provider_service
    override_config = core.domain.provider_config_from_payload(payload)
    api_key_override = core.domain.provider_api_key_from_payload(payload)
    if override_config is not None or api_key_override is not None:
        coaching_service = runtime.provider_service_for(override_config, api_key_override)
    elif (workspace_service := runtime.workspace_provider_service(state.workspace_id)) is not None:
        coaching_service = workspace_service
    if coaching_service is not None:
        runtime.adopt_request_provider_evidence(request, coaching_service)
    core.domain.ensure_coach_provider_ready(
        coaching_service,
        response_language=request.response_language,
    )
    provider_live_usable = core.domain.provider_is_live_usable(coaching_service, payload)
    if not provider_live_usable:
        turn_request = core.domain.turn_request_from_stream_payload(payload, intent="coach")
        response, artifacts, _ = await coach_support.execute_turn(
            core.coach_support_deps,
            turn_request,
            payload,
            stream=False,
        )
        response_payload = core.domain.json_object_payload(response)
        if artifacts:
            response_payload["artifacts"] = artifacts
        return finish_session_response(
            core.domain.attach_operation_reliability(
                response_payload,
                phase="acked",
                outcome="failure",
                request_id=str(request.request_id or "").strip() or None,
            )
        )

    core.domain.ensure_agent_tools_ready(request, coaching_service)
    use_agent_loop = _resolve_agent_loop_enabled(request, coaching_service, payload=payload)
    attachments_payload = [a.model_dump() for a in request.attachments]
    attachment_delivery = core.domain.describe_request_attachment_delivery(
        request,
        coaching_service,
        use_agent_loop=use_agent_loop,
    )

    user_message = ChatMessage(
        id=f"message-{uuid4().hex[:10]}",
        role="user",
        content=request.message,
        timestamp=datetime.now(UTC),
        metadata=core.domain.build_user_message_metadata(request, profile, attachment_delivery),
    )
    state.snapshot.messages.append(user_message)
    state.snapshot.profile = profile
    runtime.memory_service.record_session_message(
        state.session_id,
        f"user: {request.message}",
        workspace_id=state.workspace_id,
    )
    core.domain.safe_activate_training_card_from_coach_request(
        workspace_id=state.workspace_id,
        snapshot=state.snapshot,
        message=request.message,
        current_file=request.current_file,
        response_language=request.response_language,
        provider_service_override=coaching_service,
    )
    state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)

    prompt_response = _maybe_handle_pending_learning_project_prompt(
        runtime,
        core,
        state=state,
        request=request,
        profile=profile,
        attachment_delivery=attachment_delivery,
    )
    if prompt_response is not None:
        return finish_session_response(prompt_response)

    def _resolve_session_coach_turn_sync() -> tuple[
        CoachTurnPayload,
        str,
        list[dict[str, object]],
        bool,
        dict[str, str] | None,
    ]:
        resolved_turn: CoachTurnPayload = coach_support.resolve_coach_turn(
            core.coach_support_deps,
            state=state,
            profile=profile,
            request=request,
            message=request.message,
            coaching_service=coaching_service,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
            current_evaluation=state.snapshot.evaluation,
        )
        resolved_scenario = str(resolved_turn.get("scenario") or "general")
        if core.domain.guarantee_guided_learn_first_training_card(
            workspace_id=state.workspace_id,
            scenario=str(resolved_turn["scenario"] or ""),
            message=request.message,
            current_file=request.current_file,
            response_language=request.response_language,
            active_thread=state.snapshot.memory.active_thread,
            requested_answer_mode=raw_requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        ):
            state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        res_events = core.domain.auto_resource_lookup_tool_events(
            dict(resolved_turn["coach_context"]),
            request.message,
        )
        prefers_local = core.domain.should_bypass_agent_loop_for_guided_training(
            workspace_id=state.workspace_id,
            scenario=str(resolved_turn["scenario"] or resolved_scenario),
            message=request.message,
            active_view=request.active_view,
            requested_answer_mode=raw_requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        )
        local_reply = (
            core.domain.build_guided_training_visible_fallback(
                workspace_id=state.workspace_id,
                response_language=request.response_language,
            )
            if prefers_local
            else None
        )
        return resolved_turn, resolved_scenario, res_events, prefers_local, local_reply

    (
        coach_turn,
        scenario,
        auto_resource_events,
        guided_training_prefers_local_reply,
        guided_training_local_reply,
    ) = await asyncio.to_thread(_resolve_session_coach_turn_sync)

    (
        assistant_content,
        coach_turn,
        scenario,
        agent_meta,
        language_corruption_detected,
    ) = await _generate_session_assistant_reply(
        runtime,
        core,
        payload=payload,
        request=request,
        workspace_id=workspace_id,
        state=state,
        profile=profile,
        coaching_service=coaching_service,
        coach_turn=coach_turn,
        scenario=scenario,
        use_agent_loop=use_agent_loop,
        guided_training_prefers_local_reply=guided_training_prefers_local_reply,
        guided_training_local_reply=guided_training_local_reply,
        attachments_payload=attachments_payload,
        raw_requested_answer_mode=raw_requested_answer_mode,
        saved_answer_mode=saved_answer_mode,
    )

    (
        assistant_content,
        coach_turn,
        scenario,
        agent_meta,
        language_corruption_detected,
        provider_failure_detected,
    ) = _apply_session_reply_overrides_and_fallbacks(
        core,
        workspace_id=workspace_id,
        state=state,
        request=request,
        profile=profile,
        coaching_service=coaching_service,
        assistant_content=assistant_content,
        coach_turn=coach_turn,
        scenario=scenario,
        agent_meta=agent_meta,
        language_corruption_detected=language_corruption_detected,
        raw_requested_answer_mode=raw_requested_answer_mode,
        saved_answer_mode=saved_answer_mode,
    )

    if core.domain.should_attach_auto_resource_events(agent_meta):
        agent_meta = core.domain.apply_auto_resource_agent_evidence(agent_meta, auto_resource_events)
    if not use_agent_loop and agent_meta:
        agent_meta["agentic"] = False
    grounding_decision = await core.domain.resolve_turn_grounding_async(
        coach_turn_payload=coach_turn,
        reply_content=assistant_content,
        request=request,
        agent_meta=agent_meta if isinstance(agent_meta, dict) else None,
        history_text=core.domain.turn_history_text(state.snapshot),
        coaching_service=coaching_service,
    )
    agent_meta = (
        core.domain.apply_grounding_decision(
            coach_turn_payload=coach_turn,
            decision=grounding_decision,
            agent_meta=agent_meta if isinstance(agent_meta, dict) else None,
        )
        or agent_meta
    )
    def _persist_and_build_session_sync() -> dict[str, object]:
        coach_support.persist_turn_reflection(
            core.coach_support_deps,
            workspace_id=workspace_id,
            session_id=state.session_id,
            user_message=request.message,
            scenario=str(coach_turn["scenario"]),
            response_language=request.response_language,
            answer_mode=core.domain.answer_mode_preference_for_persistence(
                raw_requested_answer_mode,
                saved_answer_mode,
                request.answer_mode,
                profile.answer_policy if profile else None,
            ),
            coach_defaults=request.coach_defaults,
            coach_turn_data=core.domain.coach_turn_mapping(coach_turn),
            grounding_decision=grounding_decision,
            stop_reason=str(agent_meta.get("stop_reason") or ""),
            recovered_stop_reason=str(agent_meta.get("recovered_stop_reason") or ""),
            local_sequence_fallback=bool(agent_meta.get("local_sequence_fallback")),
        )
        core.domain.persist_recovered_plan_resume_after_turn(
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
            core.domain.persist_external_references_as_background(
                workspace_id=workspace_id,
                scenario=str(coach_turn["scenario"]),
                coach_turn_data=core.domain.coach_turn_mapping(coach_turn),
            )
        state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.profile = runtime.repository.get_profile(workspace_id) or profile
        runtime.hydrate_plan_context(state.snapshot, workspace_id)
        coach_support.hydrate_snapshot(
            core.coach_support_deps,
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
            session_suggested_actions = core.domain.honest_suggested_actions_without_usable_provider(
                session_suggested_actions,
                response_language=request.response_language,
                snapshot=state.snapshot,
                current_task=state.snapshot.current_task,
                current_plan=state.snapshot.plan,
                current_evaluation=state.snapshot.evaluation,
            )
        built = coach_support.build_session_response(
            core.coach_support_deps,
            state=state,
            request=request,
            reply_content=assistant_content,
            artifacts=dict(coach_turn["artifacts"]),
            suggested_actions=session_suggested_actions,
            scenario=str(coach_turn["scenario"]),
            learner_signal=str(coach_turn["learner_signal"]),
            coach_turn_data=core.domain.coach_turn_mapping(coach_turn),
            agent_meta=agent_meta or None,
            attachment_delivery=attachment_delivery,
        )
        runtime.save_session_state(state.session_id)
        return core.domain.json_object_payload(built)

    response_payload = await asyncio.to_thread(_persist_and_build_session_sync)
    if agent_meta:
        response_payload.setdefault("agent_meta", agent_meta)
    return finish_session_response(response_payload)


def _register_snapshot_and_session_lifecycle_routes(
    router: APIRouter,
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
) -> SessionMessageHandler:
    """Register snapshot, health, and session lifecycle routes."""

    @router.get("/snapshot")
    def get_snapshot(
        session_id: str | None = None,
        workspace_id: str | None = None,
        since_revision: int = -1,
        fields: str | None = None,
    ) -> dict[str, object]:
        resolved_workspace_id = core.domain.current_workspace_id(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        revision = runtime.snapshot_revision(resolved_workspace_id)
        if since_revision == revision and fields != "full":
            return {"snapshot_revision": revision, "unchanged": True}
        snapshot = core.domain.current_snapshot(session_id=session_id, workspace_id=resolved_workspace_id)
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
                "network_enabled": bool(
                    getattr(runtime.resource_service, "enable_network_fetch", False)
                ),
            },
        }

    @router.post("/session/start", response_model=None)
    def session_start(payload: dict) -> object:
        requested_response_language = (
            str(payload.get("response_language") or payload.get("responseLanguage") or "").strip()
            or None
        )
        if "user_profile" in payload:
            return _handle_intake_profile_session_start(
                runtime,
                core,
                payload=payload,
                requested_response_language=requested_response_language,
            )

        try:
            request = SessionStartRequest.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=exc.errors(include_context=False),
            ) from exc
        workspace_id = core.domain.current_workspace_id(workspace_id=request.workspace_id)
        project_provisioning = core.domain.validate_project_provisioning_or_repair(
            workspace_id,
            requested_response_language,
        )
        workspace_path = request.workspace_path
        if request.root_path:
            normalized_root_path = core.domain.normalize_trainer_root_path(request.root_path)
            root = runtime.repository.get_trainer_root(request.root_id) if request.root_id else None
            if root is None:
                root = runtime.repository.get_trainer_root_by_path(normalized_root_path)
            if root is None or root.root_path != normalized_root_path:
                raise HTTPException(
                    status_code=409,
                    detail="The selected Trainer workspace root is not registered.",
                )
            if project_provisioning is not None and project_provisioning.root_id != root.root_id:
                raise HTTPException(
                    status_code=409,
                    detail="The session project does not belong to the selected Trainer root.",
                )
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
            if (
                "workspace_trusted" in payload
                or "trusted" in payload
                or "workspaceTrusted" in payload
            ):
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
        core.domain.persist_requested_response_language(workspace_id, requested_response_language)
        start_response_language = core.domain.effective_response_language(
            workspace_id,
            requested_response_language,
            None,
        )

        initial_message = str(payload.get("initial_message") or "").strip()
        can_resume = (
            request.profile is None
            and not initial_message
            and not core.domain.force_new_session_requested(payload)
        )
        if can_resume:
            restored = runtime.restore_latest_session_for_workspace(workspace_id)
            if restored is not None:
                restored.workspace_name = request.workspace_name
                restored.snapshot.context_id = workspace_id
                restored.snapshot.profile = runtime.repository.get_profile(workspace_id)
                restored.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
                runtime.hydrate_plan_context(restored.snapshot, workspace_id)
                restored_workspace_memory = (
                    restored.snapshot.memory.workspace
                    if isinstance(restored.snapshot.memory.workspace, dict)
                    else {}
                )
                saved_response_language = (
                    str(restored_workspace_memory.get("response_language") or "").strip()
                    or start_response_language
                    or None
                )
                saved_answer_mode = (
                    str(restored_workspace_memory.get("answer_mode") or "").strip()
                    or (
                        restored.snapshot.profile.answer_policy
                        if restored.snapshot.profile
                        else None
                    )
                )
                coach_support.hydrate_snapshot(
                    core.coach_support_deps,
                    restored.snapshot,
                    response_language=saved_response_language,
                    answer_mode=saved_answer_mode,
                    preserve_session_history=True,
                )
                runtime.save_session_state(restored.session_id)
                snapshot_payload = restored.snapshot.model_dump(by_alias=True)
                snapshot_payload["session_id"] = restored.session_id
                return snapshot_payload

        state = runtime.start_session(workspace_id, request.workspace_name)
        if workspace_path:
            core.domain.maybe_persist_first_look_from_path(
                workspace_id,
                workspace_path,
                response_language=start_response_language,
                workspace_file_snapshot=_workspace_snapshot_from_payload(payload),
                remote_name=str(request.remote_name or "").strip() or None,
            )
        if core.domain.workspace_learning_project_prompt_needed(workspace_id):
            runtime.memory_service.update_workspace_state(
                workspace_id,
                learning_project_prompt_status="pending",
                learning_project_source_path=str(workspace_path or ""),
            )
            state.snapshot.messages.append(
                ChatMessage(
                    id=f"message-{uuid4().hex[:10]}",
                    role="assistant",
                    content=core.domain.workspace_learning_project_prompt_text(
                        workspace_path=str(workspace_path or ""),
                        response_language=start_response_language,
                    ),
                    timestamp=datetime.now(UTC),
                )
            )
        state.snapshot.profile = runtime.repository.get_profile(workspace_id)
        state.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
        coach_support.hydrate_snapshot(
            core.coach_support_deps,
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
        workspace_id = core.domain.current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        core.domain.apply_host_workspace_trust_attestation(workspace_id, payload)
        observe_goal_for_request(runtime, request, workspace_id)
        request_id = str(request.request_id or "").strip()
        request_key = (workspace_id, str(request.session_id or "").strip(), request_id)

        def _finish_session_response(payload_map: dict[str, object]) -> dict[str, object]:
            stamped = _attach_requested_workspace_files(payload_map, runtime, workspace_id)
            _record_coach_turn_event(
                runtime,
                workspace_id=workspace_id,
                session_id=str(request.session_id or ""),
                request_id=request_id,
                message=request.message,
            )
            if not request_id:
                return stamped
            return publish_session_request_singleflight(
                request_key,
                stamped,
                completed=core.domain.completed_session_requests,
                inflight=core.domain.inflight_session_requests,
                guard=core.domain.completed_session_requests_guard,
            )

        if request_id:
            kind, cached_response, shared_future = claim_session_request_singleflight(
                request_key,
                completed=core.domain.completed_session_requests,
                inflight=core.domain.inflight_session_requests,
                guard=core.domain.completed_session_requests_guard,
            )
            if kind == "wait":
                assert shared_future is not None
                shared_payload = await shared_future
                return overlay_completed_session_or_turn_response(
                    runtime,
                    core,
                    workspace_id=workspace_id,
                    session_id=request.session_id,
                    message=request.message,
                    request_key=request_key,
                    cached_response=shared_payload,
                )
            if kind == "cached":
                assert cached_response is not None
                return overlay_completed_session_or_turn_response(
                    runtime,
                    core,
                    workspace_id=workspace_id,
                    session_id=request.session_id,
                    message=request.message,
                    request_key=request_key,
                    cached_response=cached_response,
                )
            current_task = asyncio.current_task()
            if current_task is not None:
                current_task.add_done_callback(
                    _make_owner_task_cleanup(
                        core,
                        owner_future=shared_future,
                        request_key=request_key,
                        missing_payload_message="session request completed without publishing a payload",
                    )
                )

        state = await asyncio.to_thread(
            runtime.ensure_session,
            request.session_id,
            workspace_id=workspace_id,
        )
        async with runtime.acquire_session_lock(state.session_id):
            return await _run_session_message_locked(
                runtime,
                core,
                payload=payload,
                request=request,
                workspace_id=workspace_id,
                state=state,
                finish_session_response=_finish_session_response,
            )

    @router.get("/session/history", response_model=None)
    def session_history(
        session_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 12,
    ) -> list[dict[str, object]]:
        resolved_workspace_id = core.domain.current_workspace_id(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        _, state = core.domain.resolve_session_history_state(
            session_id=session_id,
            workspace_id=resolved_workspace_id,
        )
        if state is None:
            return []

        snapshot = getattr(state, "snapshot", None)
        messages = list(getattr(snapshot, "messages", []) or [])
        message_count = len(messages)
        latest_user_message = next(
            (
                message
                for message in reversed(messages)
                if getattr(message, "role", "") == "user"
                and str(getattr(message, "content", "") or "").strip()
            ),
            None,
        )
        latest_assistant_message = next(
            (
                message
                for message in reversed(messages)
                if getattr(message, "role", "") == "assistant"
                and str(getattr(message, "content", "") or "").strip()
            ),
            None,
        )
        session_memory = runtime.memory_service.snapshot(resolved_workspace_id)
        workspace_memory = (
            session_memory.workspace if isinstance(session_memory.workspace, dict) else {}
        )
        rolling_summary = str(
            workspace_memory.get("recent_summary") or session_memory.recent_summary or ""
        ).strip()
        summary = core.domain.summarize_session_state(state) or rolling_summary
        if not summary:
            summary = (
                rolling_summary
                or str(getattr(latest_assistant_message, "content", "") or "").strip()
            )
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
            history_item["latest_user_message"] = str(
                getattr(latest_user_message, "content", "") or ""
            ).strip()
        if latest_assistant_message is not None:
            history_item["latest_assistant_message"] = str(
                getattr(latest_assistant_message, "content", "") or ""
            ).strip()
        return [history_item][: max(1, min(limit, 50))]

    @router.get("/session/list", response_model=None)
    def session_list(
        workspace_id: str,
        session_id: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, object]]:
        resolved_workspace_id = core.domain.current_workspace_id(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        resolved_workspace_id = (
            runtime.repository.resolve_context_id(resolved_workspace_id) or resolved_workspace_id
        )
        payloads = runtime.repository.list_sessions_for_workspace(
            resolved_workspace_id,
            limit=max(1, min(limit, 100)),
        )
        items: list[dict[str, object]] = []
        active_session_id = str(session_id or "").strip() or getattr(
            runtime.latest_session(),
            "session_id",
            None,
        )
        for payload in payloads:
            item = core.domain.summarize_session_list_payload(payload)
            if item is None:
                continue
            item["is_active"] = bool(
                active_session_id and item.get("session_id") == active_session_id
            )
            items.append(item)
        return items

    @router.post("/session/activate", response_model=None)
    def session_activate(payload: dict) -> dict[str, object]:
        requested_session_id = str(
            payload.get("session_id") or payload.get("sessionId") or ""
        ).strip()
        resolved_workspace_id = core.domain.current_workspace_id(
            session_id=requested_session_id,
            workspace_id=str(
                payload.get("workspace_id") or payload.get("workspaceId") or ""
            ).strip()
            or None,
        )
        resolved_workspace_id = (
            runtime.repository.resolve_context_id(resolved_workspace_id) or resolved_workspace_id
        )
        resolved_session_id, state = core.domain.resolve_session_history_state(
            session_id=requested_session_id,
            workspace_id=resolved_workspace_id,
        )
        if state is None or not resolved_session_id:
            raise HTTPException(status_code=404, detail="Session was not found for this workspace.")
        if requested_session_id and resolved_session_id != requested_session_id:
            raise HTTPException(status_code=404, detail="Session was not found for this workspace.")
        snapshot = core.domain.current_snapshot(
            session_id=resolved_session_id,
            workspace_id=resolved_workspace_id,
        )
        return {
            "session_id": resolved_session_id,
            "workspace_id": resolved_workspace_id,
            "snapshot": snapshot.model_dump(mode="json"),
        }

    return session_message


def _register_checkpoint_turn_and_control_routes(
    router: APIRouter,
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    prepare_research_turn: PrepareResearchTurn,
) -> None:
    """Register session checkpoints, synchronous /turn, cancel, and steer routes."""

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
        return core.domain.read_agent_checkpoint_or_raise(checkpoint_id=checkpoint_id, scope=scope)

    @router.post("/session/checkpoints/{checkpoint_id}/replay", response_model=None)
    def replay_session_checkpoint(
        checkpoint_id: str,
        scope: AgentCheckpointAccessRequest,
    ) -> dict[str, object]:
        core.domain.read_agent_checkpoint_or_raise(checkpoint_id=checkpoint_id, scope=scope)
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
            raise HTTPException(
                status_code=404,
                detail="Checkpoint was not found for this workspace.",
            )
        return replay

    @router.post("/session/checkpoints/{checkpoint_id}/resume", response_model=None)
    def resume_session_checkpoint(
        checkpoint_id: str,
        scope: AgentCheckpointAccessRequest,
    ) -> dict[str, object]:
        core.domain.read_agent_checkpoint_or_raise(checkpoint_id=checkpoint_id, scope=scope)
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
            raise HTTPException(
                status_code=404,
                detail="Checkpoint was not found for this workspace.",
            )
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
        core.domain.reject_blank_coach_message(request)
        original_intent = request.intent
        request = _normalize_resource_turn_request(request)
        workspace_id = core.domain.current_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        core.domain.apply_host_workspace_trust_attestation(workspace_id, payload)
        observe_goal_for_request(runtime, request, workspace_id)
        request_id = str(request.request_id or "").strip()
        request_key = (workspace_id, str(request.session_id or "").strip(), request_id)

        def _finish_turn_response(payload_map: dict[str, object]) -> dict[str, object]:
            _record_coach_turn_event(
                runtime,
                workspace_id=workspace_id,
                session_id=str(request.session_id or ""),
                request_id=request_id,
                message=request.message,
            )
            if not request_id:
                return payload_map
            return publish_session_request_singleflight(
                request_key,
                payload_map,
                completed=core.domain.completed_session_requests,
                inflight=core.domain.inflight_session_requests,
                guard=core.domain.completed_session_requests_guard,
            )

        if request_id:
            kind, cached_response, shared_future = claim_session_request_singleflight(
                request_key,
                completed=core.domain.completed_session_requests,
                inflight=core.domain.inflight_session_requests,
                guard=core.domain.completed_session_requests_guard,
            )
            if kind == "wait":
                assert shared_future is not None
                shared_payload = await shared_future
                return overlay_completed_session_or_turn_response(
                    runtime,
                    core,
                    workspace_id=workspace_id,
                    session_id=request.session_id,
                    message=request.message,
                    request_key=request_key,
                    cached_response=shared_payload,
                )
            if kind == "cached":
                assert cached_response is not None
                return overlay_completed_session_or_turn_response(
                    runtime,
                    core,
                    workspace_id=workspace_id,
                    session_id=request.session_id,
                    message=request.message,
                    request_key=request_key,
                    cached_response=cached_response,
                )
            current_task = asyncio.current_task()
            if current_task is not None:
                current_task.add_done_callback(
                    _make_owner_task_cleanup(
                        core,
                        owner_future=shared_future,
                        request_key=request_key,
                        missing_payload_message="turn request completed without publishing a payload",
                    )
                )

        lock_session_id = runtime.ensure_session(
            request.session_id,
            workspace_id=workspace_id,
        ).session_id
        async with runtime.acquire_session_lock(lock_session_id):
            response, artifacts, _ = await coach_support.execute_turn(
                core.coach_support_deps,
                request,
                payload,
            )
            if isinstance(response, SessionMessageResponse):
                if preparation_requested(request.message):
                    await finish_research_preparation(
                        runtime,
                        prepare_research_turn,
                        request,
                        response,
                        workspace_id,
                        core.domain.build_coaching_service(payload),
                    )
                response.snapshot.memory = core.domain.repair_guided_lane_memory_snapshot_for_response(
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
                coach_support.hydrate_snapshot(
                    core.coach_support_deps,
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
            response_data = core.domain.json_object_payload(response)
            response_data["artifacts"] = artifacts
            response_data["intent"] = original_intent
            response_data = _attach_requested_workspace_files(
                response_data,
                runtime,
                workspace_id,
            )
            return _finish_turn_response(
                core.domain.attach_operation_reliability(
                    response_data,
                    phase="acked",
                    outcome=core.domain.reliability_outcome_from_payload(response_data),
                    request_id=request_id or None,
                )
            )

    @router.post("/stream/cancel")
    async def cancel_stream(payload: dict) -> dict[str, object]:
        stream_id = core.domain.resolve_stream_id(payload)
        requested = core.domain.request_stream_cancellation(stream_id)
        return {
            "ok": requested,
            "stream_id": stream_id,
            "status": "cancellation_requested" if requested else "not_found",
        }

    @router.post("/session/steer")
    async def session_steer(payload: dict) -> dict[str, object]:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        text = str(payload.get("message") or payload.get("text") or "").strip()
        if not session_id or not text:
            raise HTTPException(status_code=400, detail="session_id and message are required.")
        queued = runtime.enqueue_steer_message(session_id, text)
        return {"ok": queued, "session_id": session_id, "queued": queued}


def register_core_session_routes(
    router: APIRouter,
    runtime: TrainerRuntime,
    core: CoreRouteDeps,
    prepare_research_turn: PrepareResearchTurn,
) -> SessionMessageHandler:
    """Register snapshot, health, session, checkpoint, turn, cancel, and steer routes."""
    session_message = _register_snapshot_and_session_lifecycle_routes(router, runtime, core)
    _register_checkpoint_turn_and_control_routes(
        router,
        runtime,
        core,
        prepare_research_turn,
    )
    return session_message
