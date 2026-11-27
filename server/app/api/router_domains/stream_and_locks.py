"""Stream cancellation, singleflight state, card locks, SSE framing, and reliability envelopes."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import cast
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder

from ...core.models import (
    ChatMessage,
    CoachTurnSummary,
    LearningPlan,
    SessionMessageRequest,
    TurnRequest,
    UserProfile,
)
from ...llm.conversation_scope import composer_conversation_scope
from ...llm.provider_service import (
    redact_provider_error,
)
from .. import coach_support
from .._helpers import (
    GBK_MOJIBAKE_FRAGMENTS,
    contains_cjk_text,
    localized_text,
    looks_like_mojibake_text,
    prefers_chinese,
)
from .._singleflight import (
    claim_session_request_singleflight as claim_session_request_singleflight,
)
from .._singleflight import (
    fail_session_request_singleflight as fail_session_request_singleflight,
)
from .._singleflight import (
    publish_session_request_singleflight as publish_session_request_singleflight,
)
from ..coach_support import CoachTurnPayload
from ..coach_text_sanitizer import (
    sanitize_visible_coach_payload,
)
from ..router_support import (
    _attach_requested_workspace_files as _attach_requested_workspace_files,
)
from ..router_support import (
    _normalize_resource_turn_request,
)
from ..router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from ..router_support import (
    _resolve_agent_loop_enabled as _resolve_agent_loop_enabled,
)
from ..router_support import (
    overlay_session_response_honesty_stamps as overlay_session_response_honesty_stamps,
)
from ..router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from ..runtime import SessionState
from ._base import RouterDomainBase
from .constants import (
    _STREAM_STATUS_PHASES,
)


class StreamAndLocksDomainMixin(RouterDomainBase):
    """Stream cancellation, singleflight state, card locks, SSE framing, and reliability envelopes."""

    def save_plan_or_conflict(self, 
        workspace_id: str,
        plan: LearningPlan,
        *,
        expected_revision: int,
    ) -> int:
        """Optimistic-lock plan persistence: 409 with the current revision
        when another writer moved the plan between this request's read and
        write (design §9)."""
        from ...training.plan_revision import PlanRevisionConflict, save_plan_checked

        try:
            saved = save_plan_checked(
                self.runtime.repository,
                workspace_id,
                plan,
                expected_revision=expected_revision,
            )
        except PlanRevisionConflict as conflict:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "plan_revision_conflict",
                    "plan_id": plan.id,
                    "expected_revision": conflict.expected_revision,
                    "current_revision": conflict.actual_revision,
                },
            ) from conflict
        return saved["revision"]

    def head_plan_revision(self, workspace_id: str, plan_id: str) -> int:
        return self.runtime.repository.get_plan_revision(workspace_id, plan_id)

    def resolve_stream_id(self, payload: object) -> str:
        value = None
        if isinstance(payload, dict):
            value = payload.get("stream_id") or payload.get("streamId")
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > 256:
            return f"stream_{uuid4().hex}"
        return normalized

    def register_stream_cancellation(self, stream_id: str) -> None:
        # Idempotent replace: a crashed stream teardown can leave a stale entry,
        # and rejecting the re-registration would permanently wedge every later
        # send that reuses the id. Concurrent double-run protection lives in the
        # request_id singleflight claim, not here.
        with self.stream_cancellation_guard:
            self.stream_cancellation_events[stream_id] = asyncio.Event()

    def unregister_stream_cancellation(self, stream_id: str) -> None:
        with self.stream_cancellation_guard:
            self.stream_cancellation_events.pop(stream_id, None)

    def request_stream_cancellation(self, stream_id: str) -> bool:
        with self.stream_cancellation_guard:
            event = self.stream_cancellation_events.get(stream_id)
            if event is None:
                return False
            event.set()
            return True

    def stream_cancellation_requested(self, stream_id: str) -> bool:
        with self.stream_cancellation_guard:
            event = self.stream_cancellation_events.get(stream_id)
            return bool(event and event.is_set())

    def training_card_lock(self, workspace_id: str) -> Lock:
        """Serialize changes to a workspace’s card library."""

        with self.training_card_locks_guard:
            return self.training_card_locks.setdefault(workspace_id, Lock())

    def extract_coach_turn_payload(self, value: object) -> CoachTurnPayload:
        """Restore the stable coach-turn contract after legacy recovery helpers."""

        if not isinstance(value, dict):
            raise TypeError("Coach turn payload must be a mapping.")
        scenario = value.get("scenario")
        learner_signal = value.get("learner_signal")
        coach_context = value.get("coach_context")
        suggested_actions = value.get("suggested_actions")
        artifacts = value.get("artifacts")
        coach_turn = value.get("coach_turn")
        stream = value.get("stream")
        if not isinstance(scenario, str) or not isinstance(learner_signal, str):
            raise TypeError("Coach turn payload is missing its text fields.")
        if not isinstance(coach_context, dict) or not isinstance(artifacts, dict):
            raise TypeError("Coach turn payload is missing its mapping fields.")
        if not isinstance(suggested_actions, list) or not all(
            isinstance(action, dict) for action in suggested_actions
        ):
            raise TypeError("Coach turn payload has invalid suggested actions.")
        if not isinstance(coach_turn, CoachTurnSummary) or not isinstance(stream, bool):
            raise TypeError("Coach turn payload is missing its summary fields.")
        return cast(CoachTurnPayload, value)

    def coach_turn_mapping(self, value: CoachTurnPayload) -> dict[str, object]:
        """Adapt the stable payload to existing mutable-dict helper boundaries."""

        return cast(dict[str, object], value)

    def localized_actions(self, 
        response_language: str | None,
        english: list[str],
        chinese: list[str],
    ) -> list[str]:
        if not prefers_chinese(response_language):
            return english
        resolved: list[str] = []
        for index, label in enumerate(chinese):
            fallback = english[index] if index < len(english) else ""
            visible_label = fallback if not label or looks_like_mojibake_text(label) else label
            if visible_label:
                resolved.append(visible_label)
        return resolved

    def should_probe_language_integrity(self, message: str | None, response_language: str | None) -> bool:
        return prefers_chinese(response_language) or contains_cjk_text(message)

    def _resolve_context_tier(self, 
        request: TurnRequest | SessionMessageRequest,
    ) -> str:
        """Classify a turn as a pure conversational Q&A ("minimal") or "full".

        Having an idle editor tab open in VS Code (current_file with no selection
        and a pure conceptual question that never mentions code/files/workspace)
        must NOT force the 5k-token full archive prompt.
        """
        try:
            if getattr(request, "use_agent_loop", None):
                return "full"
            if getattr(request, "formal_plan_mutation", False):
                return "full"
            if getattr(request, "plan_runtime_recovery", None):
                return "full"
            if getattr(request, "attachments", None):
                return "full"
            if getattr(request, "resource_ids", None) or getattr(
                request, "resource_composer_intent", None
            ):
                return "full"
            if self.request_resource_ids(request):
                return "full"
            intent = str(getattr(request, "intent", "") or "coach").strip().lower()
            active_view = str(getattr(request, "active_view", "") or "").strip().lower()
            if intent not in {"", "coach"}:
                return "full"
            if active_view and active_view != "coach":
                return "full"
            current_file = getattr(request, "current_file", None)
            snapshot = getattr(request, "workspace_file_snapshot", None)
            if current_file is not None or snapshot:
                cf_dict = (
                    current_file.model_dump()
                    if current_file is not None and hasattr(current_file, "model_dump")
                    else (current_file if isinstance(current_file, dict) else {})
                )
                if str(cf_dict.get("selection_text") or "").strip():
                    return "full"
                msg_lower = str(getattr(request, "message", "") or "").casefold()
                cf_path = str(cf_dict.get("path") or "").strip()
                cf_name = Path(cf_path).name.casefold() if cf_path else ""
                if cf_name and cf_name in msg_lower:
                    return "full"
                code_anchor_hints = (
                    "current file",
                    "this file",
                    "this function",
                    "this repo",
                    "this project",
                    "workspace",
                    "codebase",
                    "diagnostic",
                    "traceback",
                    "error",
                    "bug",
                    "当前文件",
                    "这个文件",
                    "这个函数",
                    "这段代码",
                    "当前项目",
                    "这个项目",
                    "工作区",
                    "代码库",
                    "报错",
                    "诊断",
                )
                if any(hint in msg_lower for hint in code_anchor_hints):
                    return "full"
        except Exception:
            return "full"
        return "minimal"

    def build_user_message_metadata(self, 
        request: TurnRequest | SessionMessageRequest,
        profile: UserProfile | None,
        attachment_delivery: dict[str, object] | None = None,
        *,
        stream_id: str | None = None,
        stream_state: str | None = None,
    ) -> dict[str, object]:
        current_file = request.current_file
        diagnostics = current_file.diagnostics if current_file else []
        metadata: dict[str, object] = {
            "response_language": request.response_language or ("zh-CN" if prefers_chinese(request.response_language) else "en-US"),
            "answer_mode": request.answer_mode or (profile.answer_policy if profile else "auto"),
        }
        if request.active_view:
            metadata["active_view"] = request.active_view
        if isinstance(request, TurnRequest):
            metadata["intent"] = request.intent
        if current_file:
            metadata["current_file"] = current_file.path
            if current_file.content_strategy:
                metadata["content_strategy"] = current_file.content_strategy
            if current_file.content_line_span:
                metadata["content_line_span"] = current_file.content_line_span
            if current_file.selection_range:
                metadata["selection_range"] = current_file.selection_range
            if diagnostics:
                metadata["diagnostics_count"] = len(diagnostics)
            if current_file.recent_files:
                metadata["recent_files"] = current_file.recent_files[:5]
            if current_file.recent_edited_files:
                metadata["recent_edited_files"] = current_file.recent_edited_files[:5]
            if current_file.related_files:
                metadata["related_files"] = current_file.related_files[:4]
                metadata["related_files_count"] = len(current_file.related_files[:4])
            metadata["context_note"] = (
                f"Attached {current_file.language_id} file context"
                if not prefers_chinese(request.response_language)
                else f"\u5df2\u9644\u5e26 {current_file.language_id} \u6587\u4ef6\u4e0a\u4e0b\u6587"
            )
            # The visible source footnote travels on its own channel: the
            # reader may see where the turn came from, while `context_note`
            # stays the internal management context.
            metadata["source_note"] = metadata["context_note"]
        self.apply_attachment_delivery_metadata(metadata, attachment_delivery)
        image_previews: list[dict[str, str]] = []
        allowed_preview_mimes = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
        for attachment in (getattr(request, "attachments", None) or [])[:4]:
            if str(getattr(attachment, "kind", "") or "").strip().lower() != "image":
                continue
            mime_type = str(getattr(attachment, "mime_type", "") or "").strip().lower()
            raw_b64 = str(getattr(attachment, "data_base64", "") or "").strip()
            if mime_type not in allowed_preview_mimes or not raw_b64 or len(raw_b64) > 2_800_000:
                continue
            item_id = str(getattr(attachment, "id", "") or "").strip() or f"img-{len(image_previews) + 1}"
            item_name = str(getattr(attachment, "name", "") or "").strip()
            preview_item: dict[str, str] = {
                "id": item_id,
                "mime_type": mime_type,
                "data_url": f"data:{mime_type};base64,{raw_b64}",
            }
            if item_name:
                preview_item["name"] = item_name
            image_previews.append(preview_item)
        if image_previews:
            metadata["image_previews"] = image_previews
        if stream_id:
            metadata["stream_id"] = stream_id
        if stream_state:
            metadata["stream_state"] = stream_state
        attachment_line = self.attachment_delivery_line(
            attachment_delivery,
            response_language=request.response_language,
        )
        if attachment_line:
            metadata["support"] = {
                "preview": localized_text(
                    "Attached image status",
                    "\u56fe\u7247\u9644\u4ef6\u72b6\u6001",
                    request.response_language,
                ),
                "lines": [attachment_line],
            }
        return metadata

    def streaming_checkpoint_provider_scope(self, state: SessionState) -> dict[str, str]:
        provider = getattr(state.snapshot, "provider", None)
        return {
            "provider_profile_id": str(getattr(provider, "profile_id", "") or "").strip(),
            "provider_name": str(getattr(provider, "name", "") or "").strip(),
            "base_url": str(getattr(provider, "base_url", "") or "").strip(),
            "model": str(getattr(provider, "model", "") or "").strip(),
        }

    def prepare_stream_user_message(self, 
        *,
        state: SessionState,
        request: TurnRequest | SessionMessageRequest,
        profile: UserProfile | None,
        attachment_delivery: dict[str, object] | None,
        stream_id: str,
    ) -> tuple[ChatMessage, bool]:
        """Durably record one stream's user turn before provider work starts.

        ``stream_id`` is the retry/idempotency key supplied by the webview. A
        retry of the same stream must reuse its already-persisted user message
        rather than append another copy.
        """

        for message in reversed(state.snapshot.messages):
            if message.role != "user" or not isinstance(message.metadata, dict):
                continue
            if str(message.metadata.get("stream_id") or "").strip() != stream_id:
                continue
            if message.content != request.message:
                raise ValueError("stream_id was already used for a different message.")
            return message, False

        user_message = ChatMessage(
            id=f"message-{uuid4().hex[:10]}",
            role="user",
            content=request.message,
            timestamp=datetime.now(UTC),
            metadata=self.build_user_message_metadata(
                request,
                profile,
                attachment_delivery,
                stream_id=stream_id,
                stream_state="in_progress",
            ),
        )
        state.snapshot.messages.append(user_message)
        state.snapshot.profile = profile
        self.runtime.memory_service.record_session_message(
            state.session_id,
            f"user: {request.message}",
            workspace_id=state.workspace_id,
        )
        self.runtime.memory_service.persist_streaming_checkpoint(
            state.workspace_id,
            request_id=stream_id,
            phase="streaming",
            session_id=state.session_id,
            stream_message_id=user_message.id,
            **self.streaming_checkpoint_provider_scope(state),
        )
        self.runtime.save_session_state(state.session_id)
        return user_message, True

    def finalize_stream_persistence(self, 
        *,
        state: SessionState,
        user_message: ChatMessage | None,
        stream_id: str,
        committed: bool,
        assistant_message_ids: set[str],
        stream_state: str,
    ) -> None:
        """Persist stream lifecycle state without promoting an unfinished reply."""

        if not committed and assistant_message_ids:
            state.snapshot.messages[:] = [
                message
                for message in state.snapshot.messages
                if message.id not in assistant_message_ids
            ]
        if user_message is not None:
            user_message.metadata["stream_state"] = stream_state
        self.runtime.memory_service.persist_streaming_checkpoint(
            state.workspace_id,
            request_id=stream_id,
            phase=stream_state,
            session_id=state.session_id,
            stream_message_id=user_message.id if user_message is not None else "",
            stop_reason="" if stream_state == "completed" else stream_state,
            **self.streaming_checkpoint_provider_scope(state),
        )
        self.runtime.save_session_state(state.session_id)

    def _summarize_message_tool_parts(self, metadata: dict[str, object] | None) -> str:
        if not isinstance(metadata, dict):
            return ""
        raw_parts = metadata.get("parts")
        if not isinstance(raw_parts, list) or not raw_parts:
            return ""
        entries: list[str] = []
        for part in raw_parts:
            if not isinstance(part, dict) or part.get("type") != "tool_result":
                continue
            name = str(part.get("name") or "").strip()
            if not name:
                continue
            result = part.get("result")
            if isinstance(result, dict):
                action = str(result.get("action") or "").strip()
                target = str(
                    result.get("path")
                    or result.get("sandbox_path")
                    or result.get("resource_id")
                    or result.get("query")
                    or result.get("url")
                    or ""
                ).strip()
                status = "ok" if result.get("ok") is not False else "err"
                label = f"{name}({action})" if action else name
                detail = f"{label}:{target[:48]}[{status}]" if target else f"{label}[{status}]"
            else:
                detail = name
            if detail and detail not in entries:
                entries.append(detail)
            if len(entries) >= 4:
                break
        if not entries:
            return ""
        return f"[Prior turn tool trace: {'; '.join(entries)}]"

    def build_conversation_history(self, 
        messages: list[ChatMessage],
        *,
        drop_latest_user: bool = False,
        active_view: str | None = None,
    ) -> list[dict[str, str]]:
        scope = composer_conversation_scope(active_view) if active_view else None
        history_source = [
            item
            for item in messages
            if not scope
            or composer_conversation_scope((item.metadata or {}).get("active_view")) == scope
        ]
        if (
            drop_latest_user
            and history_source
            and history_source[-1].role == "user"
        ):
            history_source = history_source[:-1]

        history: list[dict[str, str]] = []
        for item in history_source:
            if item.role not in {"user", "assistant"}:
                continue
            content = str(item.content or "").strip()
            if not content:
                continue
            if item.role == "assistant" and looks_like_mojibake_text(content):
                continue
            if item.role == "assistant":
                tool_trace = self._summarize_message_tool_parts(item.metadata)
                if tool_trace and tool_trace not in content:
                    content = f"{content}\n{tool_trace}"
            history.append({"role": item.role, "content": content})
        return history

    def completion_stream_delta(self, streamed_content: str, final_content: str) -> str:
        if not final_content:
            return ""
        if not streamed_content:
            return final_content
        if final_content.startswith(streamed_content):
            return final_content[len(streamed_content) :]
        return ""

    def operation_reliability_record(self, 
        *,
        phase: str,
        outcome: str,
        request_id: str | None = None,
    ) -> dict[str, object]:
        record: dict[str, object] = {"phase": phase, "outcome": outcome}
        if request_id:
            record["request_id"] = request_id
        return record

    def attach_operation_reliability(self, 
        payload: dict[str, object],
        *,
        phase: str,
        outcome: str,
        request_id: str | None = None,
    ) -> dict[str, object]:
        record = self.operation_reliability_record(
            phase=phase,
            outcome=outcome,
            request_id=request_id,
        )
        attached = dict(payload)
        attached["reliability"] = record
        agent_meta = attached.get("agent_meta")
        if isinstance(agent_meta, dict):
            attached["agent_meta"] = {**agent_meta, "reliability": record}
        agent = attached.get("agent")
        if isinstance(agent, dict):
            attached["agent"] = {**agent, "reliability": record}
        return attached

    def reliability_outcome_from_payload(self, 
        payload: dict[str, object],
        *,
        provider_live_usable: bool = True,
        provider_failure_detected: bool = False,
    ) -> str:
        if not provider_live_usable or provider_failure_detected:
            return "failure"
        existing = payload.get("reliability")
        if isinstance(existing, dict):
            outcome = str(existing.get("outcome") or "").strip().lower()
            if outcome in {"success", "failure", "cancelled"}:
                return outcome
        agent_meta = payload.get("agent_meta")
        if not isinstance(agent_meta, dict):
            agent_meta = payload.get("agent")
        if isinstance(agent_meta, dict):
            nested = agent_meta.get("reliability")
            if isinstance(nested, dict):
                outcome = str(nested.get("outcome") or "").strip().lower()
                if outcome in {"success", "failure", "cancelled"}:
                    return outcome
            stop_reason = str(agent_meta.get("stop_reason") or "").strip().lower()
            if stop_reason in {
                "empty_response",
                "language_corruption",
                "truncated",
                "reasoning_only",
                "truncated_or_empty",
            }:
                return "failure"
        return "success"

    def sse_complete_frame(self, 
        *,
        tokens: int,
        response_data: dict[str, object],
        stream_id: str,
        outcome: str | None = None,
        request_id: str | None = None,
        provider_live_usable: bool = True,
        provider_failure_detected: bool = False,
        snapshot_fields: str = "slim",
    ) -> str:
        resolved_outcome = outcome or self.reliability_outcome_from_payload(
            response_data,
            provider_live_usable=provider_live_usable,
            provider_failure_detected=provider_failure_detected,
        )
        attached = self.attach_operation_reliability(
            response_data,
            phase="acked",
            outcome=resolved_outcome,
            request_id=request_id,
        )
        # Snapshot slimming (F3): the stream frame carries only the snapshot
        # revision pointer; callers needing the full snapshot set
        # response_data["_snapshot_fields"] = "full" before calling.
        snapshot_fields = str(response_data.get("_snapshot_fields") or self._stream_snapshot_fields.get())
        attached = {
            key: value
            for key, value in attached.items()
            if key != "_snapshot_fields"
        }
        if snapshot_fields != "full" and isinstance(attached, dict) and "snapshot" in attached:
            slim_snapshot = attached.get("snapshot")
            slim_revision = 0
            if isinstance(slim_snapshot, dict):
                slim_revision = int(
                    slim_snapshot.get("snapshotRevision")
                    or slim_snapshot.get("snapshot_revision")
                    or 0
                )
            slim_keep = (
                "reply",
                "session_id",
                "suggested_actions",
                "reliability",
                "timings",
                "agent",
                "agent_meta",
                "coach_turn",
                "next_step_requires_confirmation",
                "provider_failure_detected",
                "requested_workspace_files",
            )
            attached = {
                key: value for key, value in attached.items() if key in slim_keep
            }
            attached["snapshot_revision"] = slim_revision
            attached["snapshot_dirty"] = ["snapshot"]
        return (
            "event: complete\n"
            f"data: {json.dumps({'tokens': tokens, 'response': attached, 'stream_id': stream_id, 'reliability': attached.get('reliability')}, ensure_ascii=False)}\n\n"
        )

    def turn_request_from_stream_payload(self, 
        payload: dict,
        *,
        intent: str = "coach",
    ) -> TurnRequest:
        turn_payload = dict(payload)
        turn_payload.setdefault("intent", intent)
        parsed = TurnRequest.model_validate(turn_payload)
        if not isinstance(parsed, TurnRequest):
            raise TypeError("Stream payload did not produce a TurnRequest.")
        return _normalize_resource_turn_request(parsed)

    async def honest_unusable_provider_stream(self, 
        request: TurnRequest,
        payload: dict,
        *,
        stream_id: str,
        original_intent: str,
        http_request: Request,
        publish_complete=None,
        fail_inflight=None,
    ):
        """Local honest completion: no model call, no invented objects, visible timeline."""

        stream_committed = False
        stream_failed = False
        stream_singleflight_published = False
        request_id = str(request.request_id or "").strip() or None

        async def _abort_fail_closed(
            *,
            error_detail: object | None = None,
            status_code: int | None = None,
        ):
            """Emit failed→acked + publish failure complete so same request_id cannot remint."""
            nonlocal stream_failed, stream_singleflight_published
            stream_failed = True
            failure_payload: dict[str, object] = self.attach_operation_reliability(
                {},
                phase="acked",
                outcome="failure",
                request_id=request_id,
            )
            if publish_complete is not None and not stream_singleflight_published:
                failure_payload = publish_complete(failure_payload)
                stream_singleflight_published = True
            yield self.stream_status_event("failed", stream_id)
            if error_detail is not None:
                error_payload: dict[str, object] = {
                    "error": error_detail,
                    "stream_id": stream_id,
                    "terminal": True,
                }
                if status_code is not None:
                    error_payload["status_code"] = status_code
                yield f"event: error\ndata: {json.dumps(error_payload)}\n\n"
            yield self.stream_status_event("acked", stream_id)
            yield self.sse_complete_frame(
                tokens=0,
                response_data=failure_payload,
                stream_id=stream_id,
                outcome="failure",
                request_id=request_id,
                provider_live_usable=False,
            )

        try:
            yield self.stream_status_event("pending", stream_id)
            yield self.stream_status_event("executing", stream_id)
            try:
                if self.stream_cancellation_requested(stream_id):
                    # Fail-closed OS timeline: pending→executing→failure→ack (not silent success).
                    async for _abort_frame in _abort_fail_closed():
                        yield _abort_frame
                    return
                try:
                    if await http_request.is_disconnected():
                        async for _abort_frame in _abort_fail_closed():
                            yield _abort_frame
                        return
                except RuntimeError:
                    pass
                response, artifacts, _service = await coach_support.execute_turn(self.coach_support_deps, 
                    request,
                    payload,
                    stream=False,
                )
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                async for _abort_frame in _abort_fail_closed(
                    error_detail=redact_provider_error(detail),
                    status_code=exc.status_code,
                ):
                    yield _abort_frame
                return
            response_data = self.json_object_payload(response)
            if artifacts:
                response_data["artifacts"] = artifacts
            response_data["intent"] = original_intent
            response_data = self.attach_operation_reliability(
                response_data,
                phase="acked",
                outcome="failure",
                request_id=request_id,
            )
            reply_record = response_data.get("reply")
            visible_content = (
                str(reply_record.get("content") or "").strip()
                if isinstance(reply_record, dict)
                else ""
            )
            token_count = 0
            if visible_content:
                token_count = 1
                yield f"data: {json.dumps({'chunk': visible_content})}\n\n"
            yield self.stream_status_event("failed", stream_id)
            yield self.stream_status_event("acked", stream_id)
            stream_committed = True
            if publish_complete is not None:
                response_data = publish_complete(response_data)
                stream_singleflight_published = True
            yield self.sse_complete_frame(
                tokens=token_count,
                response_data=response_data,
                stream_id=stream_id,
                outcome="failure",
                request_id=request_id,
                provider_live_usable=False,
            )
        except asyncio.CancelledError:
            # Fail-closed: failed→acked + publish failure complete (no remint).
            async for _abort_frame in _abort_fail_closed():
                yield _abort_frame
            return
        except GeneratorExit:
            # Client disconnected before the stream committed or failed; stop
            # cleanly without publishing (the finally below still unregisters).
            if not stream_committed and not stream_failed:
                return
            raise
        except Exception as exc:
            async for _abort_frame in _abort_fail_closed(
                error_detail=redact_provider_error(exc),
            ):
                yield _abort_frame
        finally:
            if fail_inflight is not None and not stream_singleflight_published:
                fail_inflight(
                    RuntimeError(
                        "unusable provider stream failed"
                        if stream_failed
                        else "unusable provider stream completed without publishing a payload"
                    )
                )
            self.unregister_stream_cancellation(stream_id)

    def stream_status_event(self, 
        phase: str,
        stream_id: str | None = None,
        *,
        detail: dict[str, object] | None = None,
    ) -> str:
        if phase not in _STREAM_STATUS_PHASES:
            raise ValueError(f"Unsupported stream status phase: {phase}")
        payload: dict[str, object] = {"phase": phase}
        if stream_id:
            payload["stream_id"] = stream_id
        if isinstance(detail, dict):
            for key, value in detail.items():
                if key not in {"phase", "stream_id"} and value is not None:
                    payload[key] = value
        return f"event: status\ndata: {json.dumps(payload)}\n\n"

    def stream_event_payload(self, value: object, stream_id: str) -> object:
        """Attach the transport identity without mutating agent event objects."""

        if not isinstance(value, dict):
            return value
        return {**value, "stream_id": stream_id}

    def stream_frame(self, event: str, value: object, stream_id: str) -> str:
        return (
            f"event: {event}\n"
            f"data: {json.dumps(self.stream_event_payload(value, stream_id))}\n\n"
        )

    def safe_stream_delta(self, 
        pending_content: str,
        delta: str,
        full_content: str,
    ) -> tuple[str, str]:
        if looks_like_mojibake_text(full_content[-256:]):
            return "", "" 

        candidate = f"{pending_content}{delta}"
        if looks_like_mojibake_text(candidate):
            return "", ""

        held_suffix_length = max(
            (
                suffix_length
                for fragment in GBK_MOJIBAKE_FRAGMENTS
                for suffix_length in range(1, min(len(candidate), len(fragment) - 1) + 1)
                if candidate.endswith(fragment[:suffix_length])
            ),
            default=0,
        )
        if held_suffix_length:
            return candidate[:-held_suffix_length], candidate[-held_suffix_length:]
        return candidate, ""

    def to_json_payload(self, value: object) -> object:
        return sanitize_visible_coach_payload(jsonable_encoder(value))

    def json_object_payload(self, value: object) -> dict[str, object]:
        encoded_value = self.to_json_payload(value)
        if not isinstance(encoded_value, dict):
            raise TypeError("Response payload must be a mapping.")
        return {str(key): item for key, item in encoded_value.items()}
