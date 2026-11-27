"""Coach turn helpers moved out of build_router (§五十二 extraction).

The helpers share one dependency bundle (``CoachSupportDeps``) assembled by
``build_router``. Keeping the bundle explicit makes the closure graph visible
instead of hiding 45 names inside a 25k-line function.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from fastapi import HTTPException

from ...core.models import (
    AgentMeta,
    ChatMessage,
    CoachScenario,
    CoachTurnSummary,
    EvaluateCurrentFileRequest,
    SessionMessageRequest,
    SessionMessageResponse,
    SuggestedAction,
    TaskSpecifyRequest,
    TurnRequest,
    WorkbenchSnapshot,
)
from ...llm.prompts import infer_coaching_scenario as infer_message_coaching_scenario
from ...memory.workspace_recovery import (
    coach_focus_runtime_from_snapshot,
    leftover_formal_plan_is_live_for_fill,
    live_task_converted_copy,
    live_task_picked_copy,
    stamp_produced_workspace_record,
)
from .._helpers import (
    localized_text,
    looks_like_mojibake_text,
    supported_response_language,
)
from ..router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from ..router_support import (
    _resolve_agent_loop_enabled,
    _stamp_library_sandbox_work,
    register_request_workspace_path,
)
from ..router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from .types_and_deps import CoachSupportDeps, CoachTurnPayload


def build_session_response(deps: CoachSupportDeps, 
    *,
    state,
    request: TurnRequest | SessionMessageRequest,
    reply_content: str,
    artifacts: dict[str, object],
    suggested_actions: list[dict[str, object]],
    scenario: str,
    learner_signal: str,
    coach_turn_data: dict[str, object] | None = None,
    response_snapshot: WorkbenchSnapshot | None = None,
    agent_meta: dict[str, object] | None = None,
    attachment_delivery: dict[str, object] | None = None,
    streamed_prefix: str = "",
) -> SessionMessageResponse:
    if isinstance(agent_meta, dict):
        agent_meta = {key: value for key, value in agent_meta.items() if value is not None}
    snapshot_for_response = response_snapshot if response_snapshot is not None else state.snapshot
    snapshot_for_response.snapshot_revision = deps.runtime.next_snapshot_revision(state.workspace_id)
    deps.repair_legacy_assistant_messages(snapshot_for_response, request.response_language)
    response_scenario = scenario
    fresh_lane_coach_turn = False
    if isinstance(coach_turn_data, dict):
        coach_turn_scenario = str(coach_turn_data.get("scenario") or "").strip()
        coach_context = coach_turn_data.get("coach_context")
        fresh_lane_coach_turn = (
            isinstance(coach_context, dict)
            and str(coach_context.get("history_mode") or "").strip().lower() == "fresh_lane"
        )
        if fresh_lane_coach_turn and coach_turn_scenario == "general":
            response_scenario = "general"
        elif coach_turn_scenario and coach_turn_scenario != "general" and response_scenario == "general":
            response_scenario = coach_turn_scenario
    if isinstance(agent_meta, dict):
        agent_scenario = str(agent_meta.get("scenario") or "").strip()
        if (
            not fresh_lane_coach_turn
            and agent_scenario
            and agent_scenario != "general"
            and response_scenario == "general"
        ):
            response_scenario = agent_scenario
        latest_user_message = ""
        for message in reversed(snapshot_for_response.messages):
            role = str(getattr(message, "role", "") or "").strip().lower()
            if role != "user":
                continue
            latest_user_message = str(getattr(message, "content", "") or "").strip()
            if latest_user_message:
                break
        short_continuation_request = latest_user_message in {
            "continue",
            "Continue",
            "\u7ee7\u7eed",
            "\u8bf7\u7ee7\u7eed",
            "\u7ee7\u7eed\u5427",
            "\u63a5\u7740",
            "\u4e0b\u4e00\u6b65",
        } or deps.message_requests_lane_continuation(latest_user_message)
        if (
            str(agent_meta.get("stop_reason") or "").strip() == "language_corruption"
            and short_continuation_request
        ):
            continuation_active_thread = None
            if isinstance(coach_turn_data, dict):
                coach_context = coach_turn_data.get("coach_context")
                if isinstance(coach_context, dict) and isinstance(coach_context.get("active_thread"), dict):
                    continuation_active_thread = coach_context.get("active_thread")
            continuation_scenario = response_scenario
            if continuation_scenario == "general":
                continuation_scenario = deps.active_thread_scenario_value(
                    continuation_active_thread or snapshot_for_response.memory.active_thread
                ) or response_scenario
            if continuation_scenario and continuation_scenario != "general":
                response_scenario = continuation_scenario
            current_next_step = deps.strip_visible_next_step_prefix(agent_meta.get("next_step") or "")
            repaired_next_step = current_next_step
            if looks_like_mojibake_text(current_next_step):
                repaired_next_step = ""
            if deps.continuation_step_needs_local_repair(current_next_step) or deps.generic_guided_review_fallback_needs_repair(current_next_step):
                repaired_next_step = deps.resolve_local_continuation_step(
                    snapshot=snapshot_for_response,
                    coach_turn=coach_turn_data if isinstance(coach_turn_data, dict) else {},
                    fallback_next_step=current_next_step,
                )
            if deps.continuation_step_needs_local_repair(repaired_next_step) or deps.generic_guided_review_fallback_needs_repair(repaired_next_step):
                repaired_next_step = deps.extract_lane_continuation_step(current_next_step)
            if deps.continuation_step_needs_local_repair(repaired_next_step) or deps.generic_guided_review_fallback_needs_repair(repaired_next_step):
                repaired_next_step = deps.local_continuation_step_for_scenario(
                    response_scenario,
                    request.response_language,
                )
            if repaired_next_step and repaired_next_step != current_next_step:
                repaired_summary = str(agent_meta.get("summary") or "").strip()
                repaired_blocker = str(agent_meta.get("blocker") or repaired_summary).strip()
                repaired_teaching_note = localized_text(
                    "Keep the same learning lane. When a short continuation is corrupted, resume from the saved thread locally and verify the next visible move.",
                    "\u7ee7\u7eed\u7559\u5728\u540c\u4e00\u6761\u5b66\u4e60\u4e3b\u7ebf\u91cc\u3002\u5f53\u77ed continuation \u88ab\u7834\u574f\u65f6\uff0c\u5148\u4ece\u5df2\u4fdd\u5b58\u7684 thread \u5728\u672c\u5730\u7eed\u4e0a\uff0c\u518d\u9a8c\u8bc1\u4e0b\u4e00\u4e2a\u53ef\u89c1\u52a8\u4f5c\u3002",
                    request.response_language,
                )
                repaired_resume_thread = localized_text(
                    f"Continue the saved coaching thread. Next: {repaired_next_step}",
                    f"\u7ee7\u7eed\u6cbf\u7740\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u63a8\u8fdb\u3002\u4e0b\u4e00\u6b65\uff1a{repaired_next_step}",
                    request.response_language,
                )
                agent_meta = dict(agent_meta)
                agent_meta["next_step"] = repaired_next_step
                agent_meta["resume_thread"] = repaired_resume_thread
                agent_meta["teaching_note"] = repaired_teaching_note
                if response_scenario and response_scenario != "general":
                    agent_meta["scenario"] = response_scenario
                reply_content = localized_text(
                    f"{repaired_summary}\n\nThe provider did not preserve this short continuation cleanly, so Trainer resumed the saved thread locally instead of repeating the provider setup blocker.\n\nNext step: {repaired_next_step}",
                    f"{repaired_summary}\n\nprovider \u6ca1\u6709\u7a33\u5b9a\u4fdd\u7559\u8fd9\u6761\u5f88\u77ed\u7684 continuation\uff0c\u6240\u4ee5 Trainer \u5148\u6309\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u5728\u672c\u5730\u7eed\u4e0a\uff0c\u4e0d\u518d\u91cd\u590d provider \u914d\u7f6e\u963b\u585e\u3002\n\n\u4e0b\u4e00\u6b65\uff1a{repaired_next_step}",
                    request.response_language,
                )
                if snapshot_for_response.coaching_state:
                    snapshot_for_response.coaching_state = snapshot_for_response.coaching_state.model_copy(
                        update={
                            "summary": repaired_summary,
                            "next_step": repaired_next_step,
                            "resume_thread": repaired_resume_thread,
                        }
                    )
                if isinstance(coach_turn_data, dict):
                    coach_turn_data = deps.merge_agent_finalize_into_coach_turn(
                        {
                            **coach_turn_data,
                            "scenario": response_scenario,
                        },
                        summary=repaired_summary,
                        next_step=repaired_next_step,
                        blocker=repaired_blocker,
                        resume_thread=repaired_resume_thread,
                        teaching_note=repaired_teaching_note,
                    )
    refreshed_coach_turn_data = coach_turn_data
    if isinstance(coach_turn_data, dict):
        original_coach_context = (
            coach_turn_data.get("coach_context")
            if isinstance(coach_turn_data.get("coach_context"), dict)
            else None
        )
        original_turn_summary = (
            coach_turn_data.get("coach_turn")
            if isinstance(coach_turn_data.get("coach_turn"), CoachTurnSummary)
            else None
        )
        requested_resource_ids = deps.request_resource_ids(request)
        refreshed_resource_context = deps.compose_resource_context(
            state.workspace_id,
            requested_resource_ids,
            message=request.message,
            resource_composer_intent=request.resource_composer_intent,
        )
        refreshed_coach_context = deps.build_coach_context(
            snapshot_for_response,
            refreshed_resource_context,
            message=request.message,
            active_view=request.active_view,
            current_file=getattr(request, "current_file", None),
            response_language=request.response_language,
            plan_runtime_recovery=getattr(request, "plan_runtime_recovery", None),
        )
        if getattr(request, "goal_mode", False):
            refreshed_coach_context["goal_mode"] = True
        original_history_mode = (
            str(original_coach_context.get("history_mode") or "").strip().lower()
            if isinstance(original_coach_context, dict)
            else ""
        )
        if original_history_mode == "fresh_lane":
            refreshed_coach_context["history_mode"] = "fresh_lane"
            refreshed_coach_context["current_focus"] = (
                str(original_coach_context.get("current_focus") or "").strip()
                if isinstance(original_coach_context, dict)
                else ""
            )
            preserve_relationship_continuity = deps.should_preserve_relationship_continuity_for_turn(
                snapshot_for_response.memory,
                message=request.message,
                grounding_context=refreshed_resource_context,
                active_view=request.active_view,
            )
            refreshed_coach_context["memory_evidence"] = []
            refreshed_coach_context["recent_teaching_signals"] = []
            refreshed_coach_context["recent_wins"] = []
            refreshed_coach_context["teaching_observations"] = []
            if not preserve_relationship_continuity:
                refreshed_coach_context["continuity_summary"] = ""
            refreshed_coach_context["active_thread"] = None
            refreshed_memory_payload = deps.normalized_object_mapping(
                refreshed_coach_context.get("memory")
            )
            if refreshed_memory_payload is not None:
                refreshed_memory = refreshed_memory_payload
                refreshed_memory["current_focus"] = ""
                refreshed_memory["recent_summary"] = ""
                refreshed_memory["recent_wins"] = []
                refreshed_memory["teaching_observations"] = []
                refreshed_memory["memory_evidence"] = []
                refreshed_memory["active_thread"] = None
                if not deps.turn_keeps_review_signals(
                    response_scenario,
                    snapshot_for_response.teaching_decision,
                ):
                    refreshed_memory["due_reviews"] = []
                    refreshed_memory["due_review_count"] = 0
                    refreshed_memory["review_rhythm"] = ""
                refreshed_coach_context["memory"] = refreshed_memory
            if not deps.turn_keeps_review_signals(
                response_scenario,
                snapshot_for_response.teaching_decision,
            ):
                refreshed_coach_context["review_rhythm"] = ""
                refreshed_coach_context["review_queue_summary"] = ""
                refreshed_coach_context["due_reviews"] = []
                refreshed_coach_context["due_review_count"] = 0
        # Refresh rebuilds coach_context; keep mint-block stamps from resolve_coach_turn
        # (or re-evaluate) so /session/message + /turn (+ streams) still surface them.
        if (
            isinstance(original_coach_context, dict)
            and original_coach_context.get("pressure_blocks_live_object_mint") is True
        ) or deps.pressure_without_live_object_blocks_mint(
            state.workspace_id,
            snapshot=snapshot_for_response,
            current_task=snapshot_for_response.current_task,
            current_plan=snapshot_for_response.plan,
            message=getattr(request, "message", None),
        ):
            refreshed_coach_context["pressure_blocks_live_object_mint"] = True
        if (
            isinstance(original_coach_context, dict)
            and original_coach_context.get("streak_blocks_live_object_mint") is True
        ) or deps.streak_without_live_object_blocks_mint(
            state.workspace_id,
            snapshot=snapshot_for_response,
            current_task=snapshot_for_response.current_task,
            current_plan=snapshot_for_response.plan,
        ):
            refreshed_coach_context["streak_blocks_live_object_mint"] = True
        if (
            isinstance(original_coach_context, dict)
            and original_coach_context.get("live_formal_plan_for_task_mint") is True
        ) or deps.live_formal_plan_for_explicit_task_next(state.workspace_id) is not None:
            refreshed_coach_context["live_formal_plan_for_task_mint"] = True
        if (
            isinstance(original_coach_context, dict)
            and original_coach_context.get("closed_loop_return_blocks_task_mint") is True
        ) or deps.closed_loop_return_blocks_task_mint(state.workspace_id):
            refreshed_coach_context["closed_loop_return_blocks_task_mint"] = True
        refreshed_coach_turn_data = {
            "scenario": response_scenario,
            "learner_signal": learner_signal,
            "artifacts": artifacts,
            "suggested_actions": suggested_actions,
            "coach_context": refreshed_coach_context,
            "coach_turn": (
                original_turn_summary
                if original_turn_summary is not None
                else deps.build_turn_summary(
                snapshot=snapshot_for_response,
                scenario=response_scenario,
                learner_signal=learner_signal,
                artifacts=artifacts,
                suggested_actions=suggested_actions,
                coach_context=refreshed_coach_context,
                response_language=request.response_language,
                )
            ),
        }
    if isinstance(agent_meta, dict):
        refreshed_coach_turn_data = deps.merge_agent_finalize_into_coach_turn(
            refreshed_coach_turn_data,
            summary=agent_meta.get("summary"),
            next_step=agent_meta.get("next_step"),
            blocker=agent_meta.get("blocker"),
            resume_thread=agent_meta.get("resume_thread") or agent_meta.get("resumeThread"),
            decision=agent_meta.get("decision"),
            teaching_note=agent_meta.get("teaching_note") or agent_meta.get("teachingNote"),
            confidence=agent_meta.get("confidence"),
            evidence=agent_meta.get("evidence"),
        )
        normalized_agent_summary = str(agent_meta.get("summary") or "").strip()
        normalized_agent_next_step = deps.strip_visible_next_step_prefix(
            agent_meta.get("next_step") or ""
        )
        resume_thread = str(
            agent_meta.get("resume_thread") or agent_meta.get("resumeThread") or ""
        ).strip()
        if (
            normalized_agent_next_step
            and normalized_agent_summary
            and (not resume_thread or normalized_agent_next_step not in resume_thread)
        ):
            resume_thread = deps.build_resume_thread_text(
                normalized_agent_summary,
                normalized_agent_next_step,
                response_language=request.response_language,
            )
            agent_meta = dict(agent_meta)
            agent_meta["resume_thread"] = resume_thread
        if str(agent_meta.get("stop_reason") or "").strip() == "coach_finalize":
            if resume_thread and state.snapshot.coaching_state:
                state.snapshot.coaching_state = state.snapshot.coaching_state.model_copy(
                    update={"resume_thread": resume_thread}
                )
            if resume_thread and isinstance(refreshed_coach_turn_data, dict):
                coach_context = refreshed_coach_turn_data.get("coach_context")
                if isinstance(coach_context, dict):
                    coach_context["resume_thread"] = resume_thread
                refreshed_coach_turn_data = deps.merge_agent_finalize_into_coach_turn(
                    refreshed_coach_turn_data,
                    resume_thread=resume_thread,
                )
        if (
            str(agent_meta.get("stop_reason") or "").strip() == "empty_response"
            and agent_meta.get("local_sequence_fallback") is not True
        ):
            reply_content = deps.build_empty_response_visible_reply(
                summary=agent_meta.get("summary"),
                next_step=agent_meta.get("next_step"),
                response_language=request.response_language,
            )
    from ...llm.coaching_replies import preserve_streamed_reply_prefix

    raw_reply_before_repairs = reply_content
    candidate_reply, refreshed_coach_turn_data, repaired_agent_meta, _guided_lane_repaired = (
        deps.apply_guided_lane_visible_fallback(
            reply=reply_content,
            scenario=response_scenario,
            learner_message=getattr(request, "message", None),
            response_language=request.response_language,
            coach_turn=refreshed_coach_turn_data,
            agent_meta=agent_meta,
        )
    )
    sanitized_candidate = deps.sanitize_visible_coach_reply_content(
        candidate_reply,
        request.response_language,
    )
    reply_content = preserve_streamed_reply_prefix(
        streamed_prefix,
        sanitized_candidate,
        raw_reply_before_repairs,
        response_language=request.response_language,
    )
    agent_meta = repaired_agent_meta or None
    # T-0027/T-0035/T-0048 repair — see repair_generic_finalize_next_step.
    refreshed_coach_turn_data = deps.repair_generic_finalize_next_step(
        reply_content,
        agent_meta,
        refreshed_coach_turn_data,
        response_language=request.response_language,
    )
    if (
        not deps.message_requests_explicit_explanation_or_example(getattr(request, "message", None))
        and str(response_scenario or "").strip().lower() in deps.GUIDED_VISIBLE_REPAIR_SCENARIOS
        and (
            deps.guided_lane_visible_reply_is_generic(reply_content)
            or deps.guided_lane_visible_reply_has_foreign_markers(
                reply_content,
                scenario=response_scenario,
            )
        )
    ):
        coach_context = (
            deps.normalized_object_mapping(refreshed_coach_turn_data.get("coach_context"))
            if isinstance(refreshed_coach_turn_data, dict)
            else None
        )
        stable_reply = deps.build_guided_lane_stable_visible_reply(
            scenario=response_scenario,
            response_language=request.response_language,
            coach_context=coach_context,
        )
        if stable_reply is not None:
            reply_content = preserve_streamed_reply_prefix(
                streamed_prefix,
                stable_reply["reply"],
                reply_content,
                response_language=request.response_language,
            )
            stabilized_agent_meta = dict(agent_meta or {})
            stabilized_agent_meta["summary"] = stable_reply["summary"]
            stabilized_agent_meta["next_step"] = stable_reply["next_step"]
            stabilized_agent_meta["teaching_note"] = stable_reply["teaching_note"]
            stabilized_agent_meta["resume_thread"] = stable_reply["resume_thread"]
            stabilized_agent_meta["scenario"] = str(response_scenario or "").strip() or "general"
            stabilized_agent_meta["guided_lane_visible_repaired"] = True
            agent_meta = stabilized_agent_meta
            if isinstance(refreshed_coach_turn_data, dict):
                refreshed_coach_turn_data = deps.merge_agent_finalize_into_coach_turn(
                    {
                        **refreshed_coach_turn_data,
                        "scenario": str(response_scenario or "").strip() or "general",
                    },
                    summary=stable_reply["summary"],
                    next_step=stable_reply["next_step"],
                    blocker=stabilized_agent_meta.get("blocker"),
                    resume_thread=stable_reply["resume_thread"],
                    decision=stabilized_agent_meta.get("decision"),
                    teaching_note=stable_reply["teaching_note"],
                    confidence=stabilized_agent_meta.get("confidence"),
                    evidence=stabilized_agent_meta.get("evidence"),
                )
    plan_commit_verified = deps.formal_plan_commit_verified(
        state=state,
        request=request,
        agent_meta=agent_meta,
    )
    if deps.requires_formal_plan_commit(request) and not plan_commit_verified:
        reply_content = deps.formal_plan_commit_missing_reply(request.response_language)
        next_step = deps.formal_plan_commit_missing_next_step(request.response_language)
        blocker = localized_text(
            "The model did not complete the required learning_action(action='save_formal_plan') tool call, so no formal plan was committed.",
            "模型没有完成必须的 learning_action(action='save_formal_plan') 工具调用，因此没有正式计划被提交。",
            request.response_language,
        )
        agent_meta = {
            **(agent_meta or {}),
            "agentic": True,
            "formal_plan_commit": "missing",
            "stop_reason": "formal_plan_commit_missing",
            "summary": blocker,
            "next_step": next_step,
            "blocker": blocker,
        }
        refreshed_coach_turn_data = deps.merge_agent_finalize_into_coach_turn(
            refreshed_coach_turn_data,
            summary=blocker,
            next_step=next_step,
            blocker=blocker,
        )
    if isinstance(agent_meta, dict):
        deps.apply_agent_meta_to_coaching_state(
            snapshot_for_response,
            agent_meta,
            response_scenario=response_scenario,
        )
        if snapshot_for_response is not state.snapshot:
            deps.apply_agent_meta_to_coaching_state(
                state.snapshot,
                agent_meta,
                response_scenario=response_scenario,
            )
    repaired_memory_snapshot = deps.repair_guided_lane_memory_snapshot_for_response(
        snapshot_for_response.memory,
        scenario=response_scenario,
        response_language=request.response_language,
        learner_message=getattr(request, "message", None),
    )
    if repaired_memory_snapshot is not snapshot_for_response.memory:
        snapshot_for_response.memory = repaired_memory_snapshot
        if snapshot_for_response is not state.snapshot:
            state.snapshot.memory = deps.repair_guided_lane_memory_snapshot_for_response(
                state.snapshot.memory,
                scenario=response_scenario,
                response_language=request.response_language,
                learner_message=getattr(request, "message", None),
            )
    assistant_reply = ChatMessage(
        id=f"message-{uuid4().hex[:10]}",
        role="assistant",
        content=reply_content,
        timestamp=datetime.now(UTC),
        metadata=deps.build_assistant_metadata(
            request,
            artifacts,
            snapshot_for_response,
            snapshot_for_response.coaching_state.summary if snapshot_for_response.coaching_state else None,
            refreshed_coach_turn_data,
            agent_meta,
            attachment_delivery,
        ),
    )
    state.snapshot.messages.append(assistant_reply)
    # Make the matching session durable before its replay-only trace is committed.
    deps.runtime.save_session_state(state.session_id)
    if isinstance(agent_meta, dict) and agent_meta.get("agentic") is True:
        checkpoint = deps.runtime.record_agent_turn_checkpoint(
            state=state,
            request=request,
            assistant_reply=assistant_reply,
            agent_meta=agent_meta,
            coach_turn_data=refreshed_coach_turn_data,
        )
        agent_meta = dict(agent_meta)
        agent_meta["checkpoint_id"] = str(checkpoint.get("checkpoint_id") or "")
        recovery = checkpoint.get("recovery")
        agent_meta["recovery_available"] = bool(
            recovery.get("recovery_available") if isinstance(recovery, dict) else False
        )
        assistant_reply.metadata["agent_checkpoint"] = {
            "checkpoint_id": agent_meta["checkpoint_id"],
            "recovery_available": agent_meta["recovery_available"],
        }
    deps.runtime.memory_service.record_session_message(
        state.session_id,
        f"assistant: {assistant_reply.content}",
        workspace_id=state.workspace_id,
    )
    deps.update_snapshot_plan_from_turn(
        state=state,
        reply_content=reply_content,
        coach_turn=refreshed_coach_turn_data,
        allow_formal_plan_mutation=bool(
            deps.requires_formal_plan_commit(request) and plan_commit_verified
        ),
    )
    state.snapshot.plan_runtime_status = deps.attach_plan_runtime_status(
        workspace_id=state.workspace_id,
        snapshot=state.snapshot,
        response_language=request.response_language,
        profile=state.snapshot.profile,
        coach_turn=refreshed_coach_turn_data,
        agent_meta=agent_meta,
    )
    if snapshot_for_response is state.snapshot:
        response_payload_snapshot = state.snapshot.model_copy(deep=True)
    else:
        response_payload_snapshot = snapshot_for_response.model_copy(deep=True)
        response_payload_snapshot.messages.append(assistant_reply)
    response_payload_snapshot.plan_runtime_status = deps.attach_plan_runtime_status(
        workspace_id=state.workspace_id,
        snapshot=response_payload_snapshot,
        response_language=request.response_language,
        profile=response_payload_snapshot.profile,
        coach_turn=refreshed_coach_turn_data,
        agent_meta=agent_meta,
    )
    response_payload_snapshot.memory = deps.repair_guided_lane_memory_snapshot_for_response(
        response_payload_snapshot.memory,
        scenario=response_scenario,
        response_language=request.response_language,
        learner_message=getattr(request, "message", None),
    )
    if snapshot_for_response is not state.snapshot:
        response_payload_snapshot.memory = response_payload_snapshot.memory.model_copy(
            update={
                "due_reviews": [],
                "due_review_count": 0,
            }
        )
        response_payload_snapshot.review_queue_summary = deps.summarize_review_queue(
            [],
            request.response_language,
        )
        response_payload_snapshot.next_review_due = None
    response_payload_snapshot.memory = deps.repair_guided_lane_memory_snapshot_for_response(
        response_payload_snapshot.memory,
        scenario=response_scenario,
        response_language=request.response_language,
        learner_message=getattr(request, "message", None),
    )
    if response_payload_snapshot.coaching_state is not None:
        aligned_coaching_state_payload = deps.language_aligned_coaching_state_payload(
            response_payload_snapshot.coaching_state.model_dump(),
            request.response_language,
        )
        if isinstance(aligned_coaching_state_payload, dict):
            response_payload_snapshot.coaching_state = type(
                response_payload_snapshot.coaching_state
            ).model_validate(aligned_coaching_state_payload)
    deps.runtime.save_session_state(state.session_id)
    raw_response_coach_turn = (
        refreshed_coach_turn_data.get("coach_turn")
        if isinstance(refreshed_coach_turn_data, dict)
        else None
    )
    response_coach_context = (
        deps.normalized_object_mapping(refreshed_coach_turn_data.get("coach_context"))
        if isinstance(refreshed_coach_turn_data, dict)
        else None
    )
    if isinstance(raw_response_coach_turn, CoachTurnSummary):
        response_coach_turn = raw_response_coach_turn
    else:
        response_coach_turn = deps.build_turn_summary(
            snapshot=response_payload_snapshot,
            scenario=response_scenario,
            learner_signal=learner_signal,
            artifacts=artifacts,
            suggested_actions=suggested_actions,
            coach_context=response_coach_context,
            response_language=request.response_language,
        )
    if isinstance(agent_meta, dict):
        raw_agent_evidence = agent_meta.get("evidence")
        agent_turn_update = {
            key: value
            for key, value in {
                "summary": str(agent_meta.get("summary") or "").strip(),
                "next_step": deps.strip_visible_next_step_prefix(agent_meta.get("next_step") or ""),
                "resume_thread": str(
                    agent_meta.get("resume_thread") or agent_meta.get("resumeThread") or ""
                ).strip(),
                "decision": str(agent_meta.get("decision") or "").strip(),
                "blocker": str(agent_meta.get("blocker") or "").strip(),
                "teaching_note": str(
                    agent_meta.get("teaching_note") or agent_meta.get("teachingNote") or ""
                ).strip(),
                "confidence": str(agent_meta.get("confidence") or "").strip(),
                "evidence": [
                    str(item).strip()
                    for item in raw_agent_evidence
                    if str(item).strip()
                ]
                if isinstance(raw_agent_evidence, list)
                else [],
            }.items()
            if value
        }
        response_coach_turn = response_coach_turn.model_copy(update=agent_turn_update)
    if (
        isinstance(response_coach_context, dict)
        and response_coach_context.get("pressure_blocks_live_object_mint") is True
    ):
        # Non-agent paths pass agent_meta=None; still stamp so host adapter can camelCase.
        agent_meta = dict(agent_meta) if isinstance(agent_meta, dict) else {"agentic": False}
        agent_meta["pressure_blocks_live_object_mint"] = True
    if (
        isinstance(response_coach_context, dict)
        and response_coach_context.get("streak_blocks_live_object_mint") is True
    ):
        agent_meta = dict(agent_meta) if isinstance(agent_meta, dict) else {"agentic": False}
        agent_meta["streak_blocks_live_object_mint"] = True
    if (
        isinstance(response_coach_context, dict)
        and response_coach_context.get("closed_loop_return_blocks_task_mint") is True
    ):
        agent_meta = dict(agent_meta) if isinstance(agent_meta, dict) else {"agentic": False}
        agent_meta["closed_loop_return_blocks_task_mint"] = True
    suggested_actions = deps.honest_suggested_actions_without_live_object(
        suggested_actions,
        workspace_id=state.workspace_id,
        response_language=request.response_language,
        snapshot=snapshot_for_response,
        current_task=snapshot_for_response.current_task,
        current_plan=snapshot_for_response.plan,
        current_evaluation=snapshot_for_response.evaluation,
        message=getattr(request, "message", None),
        scenario=str(response_scenario or "general"),
    )
    response_suggested_actions = [
        SuggestedAction.model_validate(action) for action in suggested_actions
    ]
    response_cached_grounding_decision = deps.grounding_decision_from_payload(coach_turn_data)
    if response_cached_grounding_decision is not None:
        # Consume the per-turn decision resolved before persistence — the
        # response must never re-evaluate the turn (DESIGN.md §2.3).
        response_coach_turn = deps.grounding_response_coach_turn(
            coach_turn=response_coach_turn,
            decision=response_cached_grounding_decision,
        )
    else:
        # Legacy path: a caller that never ran the resolve step still gets
        # the synchronous gate (kept for compatibility, not for wire flows).
        response_coach_turn = deps.apply_next_step_grounding_policy(
            coach_turn=response_coach_turn,
            reply_content=reply_content,
            request=request,
            agent_meta=agent_meta,
            coach_turn_data=coach_turn_data,
            history_text=deps.turn_history_text(snapshot_for_response),
        )
    response_agent_meta = AgentMeta.model_validate(agent_meta) if isinstance(agent_meta, dict) else None
    return SessionMessageResponse(
        session_id=state.session_id,
        reply=assistant_reply,
        snapshot=response_payload_snapshot,
        suggested_actions=response_suggested_actions,
        artifacts=artifacts,
        coach_turn=response_coach_turn,
        agent_meta=response_agent_meta,
        agent=response_agent_meta,
    )


async def execute_turn(deps: CoachSupportDeps, 
    request: TurnRequest,
    payload: dict,
    *,
    stream: bool = False,
    stream_id: str | None = None,
) -> tuple[object, object, object]:
    workspace_id = deps.current_workspace_id(session_id=request.session_id, workspace_id=request.workspace_id)
    state = deps.runtime.ensure_session(request.session_id, workspace_id=workspace_id)
    register_request_workspace_path(deps.runtime, state.workspace_id, payload, request)
    profile = deps.resolved_profile(state.workspace_id)
    frozen_formal_plan_mutation_requested = bool(
        request.intent == "plan"
        and request.formal_plan_mutation
        and deps.leftover_frozen_blocks_turn_generation(state.workspace_id)
    )
    raw_requested_answer_mode = str(
        payload.get("answer_mode") or payload.get("answerMode") or ""
    ).strip()
    saved_answer_mode = str(deps.workspace_preferences(workspace_id).get("answer_mode") or "").strip()
    request = deps.request_with_workspace_defaults(
        request,
        workspace_id=workspace_id,
        profile=profile,
    )
    profile = deps.profile_with_teaching_style(profile, request.teaching_style)
    coaching_service = deps.build_coaching_service(payload)
    use_agent_loop = _resolve_agent_loop_enabled(
        request, coaching_service, stream=stream, payload=payload
    )
    deps.ensure_coach_provider_ready(
        coaching_service,
        response_language=request.response_language,
    )
    provider_live_usable = deps.provider_is_live_usable(coaching_service, payload)
    if provider_live_usable:
        deps.ensure_agent_tools_ready(request, coaching_service)
    attachments_payload = [a.model_dump() for a in request.attachments]
    attachment_delivery = deps.describe_request_attachment_delivery(
        request,
        coaching_service,
        use_agent_loop=use_agent_loop,
    )

    user_message = ChatMessage(
        id=f"message-{uuid4().hex[:10]}",
        role="user",
        content=request.message,
        timestamp=datetime.now(UTC),
        metadata=deps.build_user_message_metadata(
            request,
            profile,
            attachment_delivery,
            stream_id=stream_id,
            stream_state="in_progress" if stream_id else None,
        ),
    )
    state.snapshot.messages.append(user_message)
    state.snapshot.profile = profile
    if stream:
        deps.runtime.save_session_state(state.session_id)

    scenario = deps.infer_coaching_scenario(request)
    suggested_actions = deps.honest_suggested_actions_without_live_object(
        deps.structured_suggested_actions(
            deps.coach_suggested_actions(request.response_language,
                scenario=scenario,
                snapshot=state.snapshot,
            ),
            response_language=request.response_language,
            scenario=scenario,
            focus_area=deps.stateful_focus_area(
                state.snapshot.current_task,
                state.snapshot.plan,
                state.snapshot.evaluation,
                snapshot=state.snapshot,
            ),
        ),
        workspace_id=workspace_id,
        response_language=request.response_language,
        snapshot=state.snapshot,
        current_task=state.snapshot.current_task,
        current_plan=state.snapshot.plan,
        current_evaluation=state.snapshot.evaluation,
        message=request.message,
        scenario=scenario,
    )
    artifacts: dict[str, object] = {}
    assistant_content = ""
    learner_signal = deps.infer_learner_signal(request.message, getattr(request, "current_file", None))
    agent_meta: dict[str, object] = {}
    language_corruption_detected = False
    provider_failure_detected = False

    if request.intent == "coach" and provider_live_usable:
        if stream:
            return state, coaching_service, user_message
        deps.safe_activate_training_card_from_coach_request(
            workspace_id=state.workspace_id,
            snapshot=state.snapshot,
            message=request.message,
            current_file=request.current_file,
            response_language=request.response_language,
            provider_service_override=coaching_service,
        )
        state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.profile = profile
        coach_turn: CoachTurnPayload = deps.resolve_coach_turn(
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
        if deps.guarantee_guided_learn_first_training_card(
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
            state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
        scenario = str(coach_turn["scenario"])
        learner_signal = str(coach_turn["learner_signal"])
        if deps.infer_learner_signal(request.message, getattr(request, "current_file", None)) == "blocked":
            learner_signal = "blocked"
        artifacts = dict(coach_turn["artifacts"])
        suggested_actions = list(coach_turn["suggested_actions"])
        if not provider_live_usable:
            suggested_actions = deps.honest_suggested_actions_without_usable_provider(
                suggested_actions,
                response_language=request.response_language,
                snapshot=state.snapshot,
                current_task=state.snapshot.current_task,
                current_plan=state.snapshot.plan,
                current_evaluation=state.snapshot.evaluation,
            )
        guided_training_prefers_local_reply = deps.should_bypass_agent_loop_for_guided_training(
            workspace_id=state.workspace_id,
            scenario=scenario,
            message=request.message,
            active_view=request.active_view,
            requested_answer_mode=raw_requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        )
        guided_training_local_reply = (
            deps.build_guided_training_visible_fallback(
                workspace_id=state.workspace_id,
                response_language=request.response_language,
            )
            if guided_training_prefers_local_reply
            else None
        )
        preflight_language_probe = await asyncio.to_thread(
            deps.detect_provider_language_corruption,
            coaching_service,
            message=request.message,
            response_language=request.response_language,
            coach_context=dict(coach_turn["coach_context"]),
        )
        if preflight_language_probe is not None:
            language_corruption_detected = True
            coach_turn = deps.extract_coach_turn_payload(
                deps.isolate_preflight_language_corruption_turn(
                    deps.coach_turn_mapping(coach_turn),
                    message=request.message,
                    current_file=request.current_file.model_dump() if request.current_file else None,
                )
            )
            assistant_content, updated_coach_turn, agent_meta = deps.apply_language_corruption_override(
                coaching_service=coaching_service,
                snapshot=state.snapshot,
                coach_turn=deps.coach_turn_mapping(coach_turn),
                message=request.message,
                response_language=request.response_language,
                allow_guided_recovery=False,
            )
            coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
            deps.ensure_explicit_training_card_after_language_block(
                state=state,
                message=request.message,
                current_file=request.current_file,
                response_language=request.response_language,
                fallback_scenario=str(coach_turn.get("scenario") or scenario),
                force_training_card=(
                    deps.auto_preference_requests_training_card(
                        request.message,
                        requested_scenario=str(coach_turn.get("scenario") or scenario),
                        requested_answer_mode=raw_requested_answer_mode,
                        saved_answer_mode=saved_answer_mode,
                        profile=profile,
                    )
                    or deps.auto_lane_learn_first_force_training_card(
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
        else:
            if guided_training_local_reply is not None:
                assistant_content, updated_coach_turn, agent_meta = deps.apply_guided_training_visible_fallback(
                    coach_turn=deps.coach_turn_mapping(coach_turn),
                    fallback=guided_training_local_reply,
                )
                coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
            elif use_agent_loop and not guided_training_prefers_local_reply:
                agent_context = dict(coach_turn["coach_context"])
                agent_context["__runtime__"] = deps.runtime
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
                    history=deps.build_conversation_history(
                        state.snapshot.messages,
                        active_view=request.active_view,
                        drop_latest_user=True,
                    ),
                )
                assistant_content = str(agent_outcome.get("content") or "").strip()
                agent_resume_thread = str(agent_outcome.get("resume_thread") or "").strip()
                if not agent_resume_thread:
                    agent_resume_thread = deps.build_resume_thread_text(
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
                deps.apply_attachment_delivery_metadata(agent_meta, agent_outcome)
                original_agent_stop_reason = str(agent_outcome.get("stop_reason") or "").strip()
                local_sequence_fallback = deps.build_local_sequence_visible_fallback(
                    coach_context=dict(coach_turn["coach_context"]),
                    response_language=request.response_language,
                )
                force_local_sequence = bool(
                    local_sequence_fallback is not None
                    and (
                        original_agent_stop_reason == "empty_response"
                        or not deps.reply_explicitly_lists_prepared_sequence(
                            assistant_content,
                            coach_context=dict(coach_turn["coach_context"]),
                        )
                    )
                )
                if force_local_sequence and local_sequence_fallback is not None:
                    assistant_content = local_sequence_fallback["reply"]
                    coaching_service.clear_last_reply_override()
                    agent_meta["summary"] = (
                        agent_meta.get("summary") or local_sequence_fallback["summary"]
                    )
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
                            history=deps.build_conversation_history(
                                state.snapshot.messages,
                                active_view=request.active_view,
                                drop_latest_user=True,
                            ),
                        )
                    else:
                        assistant_content = local_sequence_fallback["reply"]
                        coaching_service.clear_last_reply_override()
                        agent_meta["summary"] = (
                            agent_meta.get("summary") or local_sequence_fallback["summary"]
                        )
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
                updated_coach_turn = deps.merge_agent_finalize_into_coach_turn(
                    deps.coach_turn_mapping(coach_turn),
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
                coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
            else:
                assistant_content = await coaching_service.coaching_reply(
                    profile,
                    request.message,
                    request.current_file.model_dump() if request.current_file else None,
                    response_language=request.response_language,
                    answer_mode=request.answer_mode,
                    coach_context=dict(coach_turn["coach_context"]),
                    history=deps.build_conversation_history(
                        state.snapshot.messages,
                        active_view=request.active_view,
                        drop_latest_user=True,
                    ),
                )
            provider_empty_reply_override = deps.consume_provider_empty_reply_override(
                coaching_service=coaching_service,
                snapshot=state.snapshot,
                coach_turn=deps.coach_turn_mapping(coach_turn),
                response_language=request.response_language,
                assistant_content=assistant_content,
            )
            if provider_empty_reply_override is not None:
                provider_failure_detected = True
                assistant_content, updated_coach_turn, override_meta = provider_empty_reply_override
                coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
                agent_meta.update(override_meta)
            else:
                provider_failure_override = deps.consume_provider_reply_failure_override(
                    coaching_service=coaching_service,
                    snapshot=state.snapshot,
                    coach_turn=deps.coach_turn_mapping(coach_turn),
                    message=request.message,
                    response_language=request.response_language,
                    workspace_id=state.workspace_id,
                )
                if provider_failure_override is not None:
                    provider_failure_detected = True
                    assistant_content, updated_coach_turn, override_meta = provider_failure_override
                    coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
                    agent_meta.update(override_meta)
                elif not language_corruption_detected and coaching_service.detect_language_corruption(
                    message=request.message,
                    reply=assistant_content,
                    response_language=request.response_language,
                ):
                    language_corruption_detected = True
                    assistant_content, updated_coach_turn, override_meta = deps.apply_language_corruption_override(
                        coaching_service=coaching_service,
                        snapshot=state.snapshot,
                        coach_turn=deps.coach_turn_mapping(coach_turn),
                        message=request.message,
                        response_language=request.response_language,
                        reply_corruption=True,
                    )
                    coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
                    deps.ensure_explicit_training_card_after_language_block(
                        state=state,
                        message=request.message,
                        current_file=request.current_file,
                        response_language=request.response_language,
                        fallback_scenario=str(coach_turn.get("scenario") or scenario),
                        force_training_card=(
                            deps.auto_preference_requests_training_card(
                                request.message,
                                requested_scenario=str(coach_turn.get("scenario") or scenario),
                                requested_answer_mode=raw_requested_answer_mode,
                                saved_answer_mode=saved_answer_mode,
                                profile=profile,
                            )
                            or deps.auto_lane_learn_first_force_training_card(
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
                if deps.grounded_resource_contract_needs_repair(
                    assistant_content,
                    coach_context=dict(coach_turn["coach_context"]),
                ):
                    resource_contract_fallback = deps.build_grounded_resource_contract_visible_fallback(
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
                    updated_coach_turn = deps.merge_agent_finalize_into_coach_turn(
                        deps.coach_turn_mapping(coach_turn),
                        summary=resource_contract_fallback["summary"],
                        next_step=resource_contract_fallback["next_step"],
                        blocker=agent_meta.get("blocker"),
                        resume_thread=resource_contract_fallback["resume_thread"],
                        decision=agent_meta.get("decision"),
                        teaching_note=resource_contract_fallback["teaching_note"],
                        confidence=agent_meta.get("confidence"),
                        evidence=agent_meta.get("evidence"),
                    )
                    coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
                assistant_content, updated_coach_turn, agent_meta, _guided_lane_repaired = (
                    deps.apply_guided_lane_visible_fallback(
                        reply=assistant_content,
                        scenario=str(coach_turn.get("scenario") or scenario),
                        learner_message=request.message,
                        response_language=request.response_language,
                        coach_turn=deps.coach_turn_mapping(coach_turn),
                        agent_meta=agent_meta,
                    )
                )
                coach_turn = deps.extract_coach_turn_payload(updated_coach_turn)
                deps.ensure_explicit_training_card_after_coach_reply(
                    state=state,
                    message=request.message,
                    current_file=request.current_file,
                    response_language=request.response_language,
                    fallback_scenario=str(coach_turn.get("scenario") or scenario),
                    force_training_card=deps.auto_preference_requests_training_card(
                        request.message,
                        requested_scenario=str(coach_turn.get("scenario") or scenario),
                        requested_answer_mode=raw_requested_answer_mode,
                        saved_answer_mode=saved_answer_mode,
                        profile=profile,
                    )
                    or deps.auto_lane_learn_first_force_training_card(
                        request.message,
                        requested_scenario=str(coach_turn.get("scenario") or scenario),
                        requested_answer_mode=raw_requested_answer_mode,
                        saved_answer_mode=saved_answer_mode,
                        profile=profile,
                    ),
                    provider_service_override=coaching_service,
                )
    elif request.intent == "coach":
        # Remapped task/next_task (no live plan) still uses task honesty copy so
        # the learner hears "did not invent a task" rather than bare coach failure.
        raw_intent = str(payload.get("intent") or "").strip()
        unusable_kind: Literal["task", "plan", "coach"] = (
            "task" if raw_intent in {"task", "next_task"} else "coach"
        )
        if scenario == "general":
            scenario = infer_message_coaching_scenario(
                request.message,
                deps.normalize_current_file_payload(getattr(request, "current_file", None)),
                default="general",
            )
            if deps.message_requests_project_sourcing(request.message):
                scenario = "project_sourcing"
        coach_turn = deps.honest_unusable_provider_coach_turn(
            response_language=request.response_language,
            snapshot=state.snapshot,
            coaching_service=coaching_service,
            object_kind=unusable_kind,
            # infer_coaching_scenario/infer_message_coaching_scenario only
            # return valid scenario names.
            scenario=cast(CoachScenario, scenario),
        )
        scenario = str(coach_turn["scenario"] or scenario)
        artifacts = {}
        suggested_actions = list(coach_turn["suggested_actions"])
        assistant_content = str(coach_turn["coach_turn"].summary)
        agent_meta = {
            "summary": coach_turn["coach_turn"].summary,
            "next_step": coach_turn["coach_turn"].next_step,
        }
    elif request.intent == "next_task":
        if not provider_live_usable:
            coach_turn = deps.honest_unusable_provider_coach_turn(
                response_language=request.response_language,
                snapshot=state.snapshot,
                coaching_service=coaching_service,
                object_kind="task",
            )
            scenario = "general"
            artifacts = {}
            suggested_actions = list(coach_turn["suggested_actions"])
            assistant_content = str(coach_turn["coach_turn"].summary)
            agent_meta = {
                "summary": coach_turn["coach_turn"].summary,
                "next_step": coach_turn["coach_turn"].next_step,
            }
        else:
            task = deps.review_aware_next_task(workspace_id=workspace_id,
                profile=profile,
                focus_area=request.focus_area,
                response_language=request.response_language,
            )
            task = deps.clean_active_thread_task(
                task,
                request.response_language,
                deps.runtime.memory_service.snapshot(state.workspace_id).active_thread,
                plan=state.snapshot.plan,
                snapshot=state.snapshot,
            )
            state.snapshot.current_task = task
            state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
            state.snapshot.profile = profile
            coach_turn = deps.resolve_coach_turn(
                state=state,
                profile=profile,
                request=request,
                message=request.message,
                coaching_service=coaching_service,
                current_task=task,
                current_plan=state.snapshot.plan,
                current_evaluation=state.snapshot.evaluation,
                force_scenario="next_task",
            )
            scenario = "next_task"
            learner_signal = str(coach_turn["learner_signal"])
            artifacts = dict(coach_turn["artifacts"])
            suggested_actions = list(coach_turn["suggested_actions"])
            leftover_runtime = coach_focus_runtime_from_snapshot(state.snapshot)
            picked = live_task_picked_copy(
                plan=state.snapshot.plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                task_title=task.title,
            )
            assistant_content = localized_text(picked["en"], picked["zh"], request.response_language)
    elif request.intent == "task":
        if not provider_live_usable:
            coach_turn = deps.honest_unusable_provider_coach_turn(
                response_language=request.response_language,
                snapshot=state.snapshot,
                coaching_service=coaching_service,
                object_kind="task",
            )
            scenario = "general"
            artifacts = {}
            suggested_actions = list(coach_turn["suggested_actions"])
            assistant_content = str(coach_turn["coach_turn"].summary)
            agent_meta = {
                "summary": coach_turn["coach_turn"].summary,
                "next_step": coach_turn["coach_turn"].next_step,
            }
        else:
            task = deps.runtime.spec_service.specify(
                TaskSpecifyRequest(
                    session_id=request.session_id,
                    workspace_id=workspace_id,
                    natural_language_goal=request.message,
                )
            )
            state.snapshot.current_task = task
            state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
            state.snapshot.profile = profile
            coach_turn = deps.resolve_coach_turn(
                state=state,
                profile=profile,
                request=request,
                message=request.message,
                coaching_service=coaching_service,
                current_task=task,
                current_plan=state.snapshot.plan,
                current_evaluation=state.snapshot.evaluation,
                force_scenario="task",
            )
            scenario = "task"
            learner_signal = str(coach_turn["learner_signal"])
            artifacts = dict(coach_turn["artifacts"])
            suggested_actions = list(coach_turn["suggested_actions"])
            leftover_runtime = coach_focus_runtime_from_snapshot(state.snapshot)
            converted = live_task_converted_copy(
                plan=state.snapshot.plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                task_title=task.title,
            )
            assistant_content = localized_text(converted["en"], converted["zh"], request.response_language)
    elif request.intent == "plan":
        # Formal plans are committed by the model through save_formal_plan.
        # Leftover stored plans stay stored. Do not paint them live without
        # recovered runtime identity, and do not synthesize a replacement.
        leftover_plan, leftover_runtime = deps.leftover_runtime_for_workspace(workspace_id)
        plan = (
            leftover_plan
            if leftover_formal_plan_is_live_for_fill(
                plan=leftover_plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            else None
        )
        deps.runtime.memory_service.record_profile(workspace_id, profile)
        state.snapshot.plan = plan
        state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.profile = profile
        if not provider_live_usable:
            coach_turn = deps.honest_unusable_provider_coach_turn(
                response_language=request.response_language,
                snapshot=state.snapshot,
                coaching_service=coaching_service,
                object_kind="plan",
                scenario="plan",
            )
            scenario = "plan"
            artifacts = {}
            suggested_actions = list(coach_turn["suggested_actions"])
            assistant_content = str(coach_turn["coach_turn"].summary)
            agent_meta = {
                "summary": coach_turn["coach_turn"].summary,
                "next_step": coach_turn["coach_turn"].next_step,
            }
        else:
            coach_turn = deps.resolve_coach_turn(
                state=state,
                profile=profile,
                request=request,
                message=request.message,
                coaching_service=coaching_service,
                current_task=state.snapshot.current_task,
                current_plan=plan,
                current_evaluation=state.snapshot.evaluation,
                force_scenario="plan",
            )
            stage_count = len(plan.phases) if plan is not None else 0
            scenario = "plan"
            learner_signal = str(coach_turn["learner_signal"])
            artifacts = dict(coach_turn["artifacts"])
            suggested_actions = list(coach_turn["suggested_actions"])
            assistant_content = (
                ""
                if request.formal_plan_mutation
                else localized_text(
                    (
                        f"I refreshed your learning plan with {stage_count} stages. "
                        "Anchor on the current stage first, then convert it into a small set of actions you can actually finish."
                    ),
                    f"\u6211\u5df2\u7ecf\u66f4\u65b0\u4e86\u4f60\u7684\u5b66\u4e60\u8ba1\u5212\uff0c\u5171 {stage_count} \u4e2a\u9636\u6bb5\u3002"
                    "\u5148\u56f4\u7ed5\u5f53\u524d\u9636\u6bb5\u63a8\u8fdb\uff0c\u518d\u628a\u5b83\u62c6\u6210\u4f60\u73b0\u5728\u80fd\u5b8c\u6210\u7684\u5c0f\u52a8\u4f5c\u3002",
                    request.response_language,
                )
            )
    elif request.intent == "review":
        if request.current_file is None:
            raise HTTPException(status_code=400, detail="Current file is required for review turns.")
        leftover = deps.leftover_plan_state_fields(workspace_id)
        leftover_runtime = leftover.get("leftover_runtime")
        report = stamp_produced_workspace_record(
            deps.runtime.evaluator_service.evaluate_current_file(
                EvaluateCurrentFileRequest(
                    session_id=request.session_id,
                    workspace_id=workspace_id,
                    task_spec_id=state.snapshot.current_task.id if state.snapshot.current_task else None,
                    file_path=request.current_file.path,
                    language_id=request.current_file.language_id,
                    content=request.current_file.content,
                ),
                state.snapshot.current_task,
                leftover_plan=leftover.get("leftover_plan"),
                leftover_runtime=leftover_runtime if isinstance(leftover_runtime, dict) else {},
                leftover_task_title=str(leftover.get("leftover_task_title") or ""),
                response_language=(
                    supported_response_language(request.response_language)
                    or deps.workspace_response_language(workspace_id)
                ),
            ),
            workspace_id,
        )
        state.snapshot.evaluation = report
        deps.persist_evaluation_learning_loop(
            workspace_id=workspace_id,
            state=state,
            report=report,
            action_type="review",
            fallback_focus_area=(
                Path(str(request.current_file.path or "")).stem.strip() or "review"
            ),
        )
        deps.advance_plan_after_evaluation(
            workspace_id=workspace_id,
            state=state,
            report=report,
        )
        state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.profile = profile
        coach_turn = deps.resolve_coach_turn(
            state=state,
            profile=profile,
            request=request,
            message=request.message,
            coaching_service=coaching_service,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
            current_evaluation=report,
            force_scenario="review",
        )
        scenario = "review"
        learner_signal = str(coach_turn["learner_signal"])
        artifacts = dict(coach_turn["artifacts"])
        suggested_actions = list(coach_turn["suggested_actions"])
        assistant_content = localized_text(
            f"Review finished. {report.summary} Highest-leverage next step: {report.next_step}",
            f"\u8bc4\u5ba1\u5b8c\u6210\u3002{report.summary} \u5f53\u524d\u6700\u503c\u5f97\u5148\u505a\u7684\u4e0b\u4e00\u6b65\uff1a{report.next_step}",
            request.response_language,
        )
    else:
        raise HTTPException(status_code=400, detail="Unsupported turn intent.")

    final_resource_context = deps.compose_resource_context(
        state.workspace_id,
        deps.request_resource_ids(request),
        message=request.message,
        resource_composer_intent=request.resource_composer_intent,
    )
    deps.runtime.memory_service.record_session_message(
        state.session_id,
        f"user: {request.message}",
        workspace_id=state.workspace_id,
    )
    request_coach_context = coach_turn.get("coach_context")
    if isinstance(request_coach_context, dict):
        request_coach_context = dict(request_coach_context)
        if final_resource_context:
            for key, value in final_resource_context.items():
                request_coach_context.setdefault(key, value)
    else:
        request_coach_context = deps.build_coach_context(
            state.snapshot,
            final_resource_context,
            message=request.message,
            active_view=request.active_view,
            current_file=request.current_file,
            response_language=request.response_language,
            plan_runtime_recovery=getattr(request, "plan_runtime_recovery", None),
        )
    if isinstance(request_coach_context, dict) and getattr(request, "goal_mode", False):
        request_coach_context["goal_mode"] = True
    if request.intent == "plan" and not stream and provider_live_usable:
        history = deps.build_conversation_history(
            state.snapshot.messages,
            active_view=request.active_view,
            drop_latest_user=True,
        )
        if use_agent_loop:
            agent_context = dict(request_coach_context or {})
            agent_context["__runtime__"] = deps.runtime
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
                history=history,
            )
            assistant_content = str(agent_outcome.get("content") or "").strip()
            agent_resume_thread = str(agent_outcome.get("resume_thread") or "").strip()
            if not agent_resume_thread:
                agent_resume_thread = deps.build_resume_thread_text(
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
            deps.apply_attachment_delivery_metadata(agent_meta, agent_outcome)
            if request.formal_plan_mutation:
                persisted_plan = deps.runtime.repository.get_latest_plan(workspace_id)
                _leftover_after, leftover_runtime_after = deps.leftover_runtime_for_workspace(
                    workspace_id
                )
                if persisted_plan is not None and leftover_formal_plan_is_live_for_fill(
                    plan=persisted_plan,
                    runtime=leftover_runtime_after,
                    existing=leftover_runtime_after,
                ):
                    state.snapshot.plan = persisted_plan
        else:
            # When the Agent loop is disabled, keep the legacy provider
            # reply path. It still cannot synthesize or persist a formal
            # plan because this branch is discussion-only.
            assistant_content = await coaching_service.coaching_reply(
                profile,
                request.message,
                request.current_file.model_dump() if request.current_file else None,
                response_language=request.response_language,
                answer_mode=request.answer_mode,
                coach_context=request_coach_context,
                history=history,
            )
    if deps.should_attach_auto_resource_events(agent_meta):
        agent_meta = deps.apply_auto_resource_agent_evidence(
            agent_meta,
            deps.auto_resource_lookup_tool_events(
                request_coach_context if isinstance(request_coach_context, dict) else None,
                request.message,
            ),
        )
    if not use_agent_loop and agent_meta:
        agent_meta["agentic"] = False
    request_turn_summary = coach_turn.get("coach_turn")
    coach_turn_payload = {
        "scenario": scenario,
        "learner_signal": learner_signal,
        "coach_context": request_coach_context,
        "coach_turn": (
            request_turn_summary
            if isinstance(request_turn_summary, CoachTurnSummary)
            else deps.build_turn_summary(
                snapshot=state.snapshot,
                scenario=scenario,
                learner_signal=learner_signal,
                artifacts=artifacts,
                suggested_actions=suggested_actions,
                coach_context=request_coach_context,
                response_language=request.response_language,
            )
        ),
    }
    if isinstance(agent_meta, dict):
        coach_turn_payload = deps.merge_agent_finalize_into_coach_turn(
            coach_turn_payload,
            summary=agent_meta.get("summary"),
            next_step=agent_meta.get("next_step"),
            blocker=agent_meta.get("blocker"),
            resume_thread=agent_meta.get("resume_thread") or agent_meta.get("resumeThread"),
            decision=agent_meta.get("decision"),
            teaching_note=agent_meta.get("teaching_note") or agent_meta.get("teachingNote"),
            confidence=agent_meta.get("confidence"),
            evidence=agent_meta.get("evidence"),
        )
        stop_reason = str(agent_meta.get("stop_reason") or "").strip()
        preserve_active_thread = deps.should_preserve_active_thread_for_turn(
            scenario,
            state.snapshot.memory.active_thread,
            message=request.message,
            grounding_context=request_coach_context if isinstance(request_coach_context, dict) else None,
            active_view=request.active_view,
        )
        if (
            not preserve_active_thread
            and stop_reason in deps.PROVIDER_REPLY_STOP_REASONS
            and isinstance(coach_turn_payload, dict)
        ):
            coach_context = coach_turn_payload.get("coach_context")
            turn_summary = coach_turn_payload.get("coach_turn")
            if isinstance(coach_context, dict) and isinstance(turn_summary, CoachTurnSummary):
                focus_hint = deps.extract_focus_hint_from_message(request.message) or ""
                visible_focus_hint = deps.guided_focus_display_value(
                    focus_hint,
                    scenario=scenario,
                    response_language=request.response_language,
                )
                if visible_focus_hint:
                    coach_context["current_focus"] = visible_focus_hint
                coach_context["active_thread"] = {
                    "scenario": scenario,
                    "focus_area": visible_focus_hint or focus_hint,
                    "summary": turn_summary.summary,
                    "next_step": turn_summary.next_step,
                    "blocker": turn_summary.blocker,
                    "decision": turn_summary.decision,
                    "teaching_note": turn_summary.teaching_note,
                    "confidence": turn_summary.confidence,
                    "evidence": list(turn_summary.evidence or []),
                }
    response_snapshot = state.snapshot.model_copy(deep=True)
    if stream and request.intent != "coach":
        # Non-coach streaming turns have not produced the real LLM reply yet.
        # Defer grounding and reflection persistence to /turn/stream once the
        # stream commits so cancelled/failed turns never pollute memory.
        if not provider_live_usable:
            suggested_actions = deps.honest_suggested_actions_without_usable_provider(
                suggested_actions,
                response_language=request.response_language,
                snapshot=state.snapshot,
                current_task=state.snapshot.current_task,
                current_plan=state.snapshot.plan,
                current_evaluation=state.snapshot.evaluation,
            )
        if agent_meta:
            agent_meta["reliability"] = deps.operation_reliability_record(
                phase="acked",
                outcome=(
                    "failure"
                    if not provider_live_usable or provider_failure_detected
                    else "success"
                ),
                request_id=str(request.request_id or "").strip() or None,
            )
        state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.profile = deps.runtime.repository.get_profile(workspace_id) or profile
        deps.hydrate_snapshot(
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
        if frozen_formal_plan_mutation_requested:
            assistant_content = "\n\n".join(
                part
                for part in (
                    deps.frozen_plan_mutation_notice(request.response_language),
                    assistant_content,
                )
                if part
            )
            agent_meta["formal_plan_mutation_blocked"] = True
        if not (scenario == "idea_implementation" and request.current_file is not None):
            response_snapshot = state.snapshot
        return (
            {
                "__turn_stream_preparation__": True,
                "state": state,
                "request": request,
                "profile": profile,
                "scenario": scenario,
                "learner_signal": learner_signal,
                "coach_turn_data": coach_turn_payload,
                "artifacts": artifacts,
                "suggested_actions": suggested_actions,
                "agent_meta": agent_meta,
                "response_snapshot": response_snapshot,
                "attachment_delivery": attachment_delivery,
                "fallback_reply": assistant_content,
                "use_agent_loop": use_agent_loop,
                "raw_requested_answer_mode": raw_requested_answer_mode,
                "saved_answer_mode": saved_answer_mode,
                "language_corruption_detected": language_corruption_detected,
                "provider_failure_detected": provider_failure_detected,
            },
            artifacts,
            coaching_service,
        )
    # T-0048: repair a generic finalize step BEFORE grounding and memory
    # persistence so the recorded thread, the grounding gate and the
    # response surfaces all ship the same step. Only a non-empty
    # agent_meta carries a finalize step; an empty dict is the legacy
    # (non-agent) lane and must stay empty or the turn surfaces as agentic.
    coach_turn_payload = deps.repair_generic_finalize_next_step(
        assistant_content,
        agent_meta if isinstance(agent_meta, dict) and agent_meta else None,
        coach_turn_payload,
        response_language=request.response_language,
    ) or coach_turn_payload
    grounding_decision = await deps.resolve_turn_grounding_async(
        coach_turn_payload=coach_turn_payload,
        reply_content=assistant_content,
        request=request,
        agent_meta=agent_meta if isinstance(agent_meta, dict) else None,
        history_text=deps.turn_history_text(state.snapshot),
        coaching_service=coaching_service,
    )
    agent_meta = deps.apply_grounding_decision(
        coach_turn_payload=coach_turn_payload,
        decision=grounding_decision,
        agent_meta=agent_meta if isinstance(agent_meta, dict) else None,
    ) or agent_meta
    deps.persist_turn_reflection(workspace_id=workspace_id,
        session_id=state.session_id,
        user_message=request.message,
        scenario=scenario,
        response_language=request.response_language,
        answer_mode=deps.answer_mode_preference_for_persistence(
            raw_requested_answer_mode,
            saved_answer_mode,
            request.answer_mode,
            profile.answer_policy,
        ),
        coach_defaults=request.coach_defaults,
        coach_turn_data=coach_turn_payload,
        grounding_decision=grounding_decision,
        stop_reason=str(agent_meta.get("stop_reason") or ""),
        recovered_stop_reason=str(agent_meta.get("recovered_stop_reason") or ""),
        local_sequence_fallback=bool(agent_meta.get("local_sequence_fallback")),
    )
    deps.persist_recovered_plan_resume_after_turn(
        workspace_id=workspace_id,
        request=request,
        reply_content=assistant_content,
        agent_meta=agent_meta if isinstance(agent_meta, dict) else None,
        coach_context=request_coach_context if isinstance(request_coach_context, dict) else None,
        recovered_status=state.snapshot.plan_runtime_status
        if isinstance(state.snapshot.plan_runtime_status, dict)
        else None,
    )
    if not language_corruption_detected and not provider_failure_detected:
        deps.persist_external_references_as_background(
            workspace_id=workspace_id,
            scenario=scenario,
            coach_turn_data=coach_turn_payload,
        )
    if not provider_live_usable:
        suggested_actions = deps.honest_suggested_actions_without_usable_provider(
            suggested_actions,
            response_language=request.response_language,
            snapshot=state.snapshot,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
            current_evaluation=state.snapshot.evaluation,
        )
    if agent_meta:
        # Stamp reliability only onto a real agent meta. Stamping an empty
        # dict would resurrect agent_meta for clean non-agent turns and the
        # AgentMeta default (agentic=True) would mislabel the reply lane.
        agent_meta["reliability"] = deps.operation_reliability_record(
            phase="acked",
            outcome=(
                "failure"
                if not provider_live_usable or provider_failure_detected
                else "success"
            ),
            request_id=str(request.request_id or "").strip() or None,
        )
    state.snapshot.memory = deps.runtime.memory_service.snapshot(state.workspace_id)
    state.snapshot.profile = deps.runtime.repository.get_profile(workspace_id) or profile
    deps.hydrate_snapshot(state.snapshot,
        response_language=request.response_language,
        answer_mode=request.answer_mode or profile.answer_policy,
        scenario=scenario,
        learner_signal=learner_signal,
        message=request.message,
        current_file=request.current_file,
        active_view=request.active_view,
        session_workspace_id=workspace_id,
    )
    if frozen_formal_plan_mutation_requested:
        assistant_content = "\n\n".join(
            part
            for part in (deps.frozen_plan_mutation_notice(request.response_language), assistant_content)
            if part
        )
        agent_meta["formal_plan_mutation_blocked"] = True
    if not (scenario == "idea_implementation" and request.current_file is not None):
        response_snapshot = state.snapshot

    return (
        deps.build_session_response(
            state=state,
            request=request,
            reply_content=assistant_content,
            artifacts=artifacts,
            suggested_actions=suggested_actions,
            scenario=scenario,
            learner_signal=learner_signal,
            coach_turn_data=coach_turn_payload,
            response_snapshot=response_snapshot,
            agent_meta=agent_meta or None,
            attachment_delivery=attachment_delivery,
        ),
        artifacts,
        coaching_service,
    )

