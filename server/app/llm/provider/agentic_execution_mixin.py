from __future__ import annotations

import sys as _sys
from typing import TYPE_CHECKING, Any

import httpx as _real_httpx

from ...core.models import (
    UserProfile,
)
from ..agent_tool_context import (
    _build_agent_tool_context_extra,
)
from ..coaching_patches import (
    _guided_domain_empty_reply_override,
    _maybe_auto_verify_practice_current_file,
    _normalize_visible_resume_thread_text,
)
from ..coaching_recovery import (
    _agentic_resume_thread_text,
    _build_language_corruption_recovery_override,
    _build_provider_error_recovery_override,
    _build_timeout_recovery_override,
    _prefers_chinese,
)
from ..coaching_replies import (
    _agentic_completion_continuity,
    _agentic_fallback_continuity,
    _agentic_practice_completion_guard,
    _current_file_practice_verification_result,
    _sanitize_agentic_continuity_text,
    _stream_holdback_chars,
    _streamable_visible_prefix,
    _strip_internal_coach_meta,
)
from ..coaching_reply_drafts import (
    _agent_loop_max_steps,
    _agent_result_visible_text,
    _agentic_has_grounded_resource_evidence,
    _guided_domain_empty_reply,
)
from ..harness import estimate_tokens
from ..learner_code_guard import LearnerCode, learner_code_note, streamable_learner_reply
from ..prompts import (
    build_coaching_messages as _real_build_coaching_messages,
)
from ..prompts import (
    extract_coaching_context,
)
from ..vision_challenge import build_vision_challenge as _real_build_vision_challenge
from .context_budget import (
    MIN_CONTEXT_OUTPUT_TOKENS as MIN_CONTEXT_OUTPUT_TOKENS,
)
from .errors import (
    ContextBudgetExhaustedError,
)
from .language_probes import (
    _LANGUAGE_PROBE_VARIANTS as _LANGUAGE_PROBE_VARIANTS,
)
from .language_probes import (
    _NATURAL_LANGUAGE_PROBE_FRAGMENTS as _NATURAL_LANGUAGE_PROBE_FRAGMENTS,
)
from .language_probes import (
    _NATURAL_LANGUAGE_PROBE_PROMPT as _NATURAL_LANGUAGE_PROBE_PROMPT,
)
from .model_catalog import (
    _ANTHROPIC_MODELS_PAGE_SIZE as _ANTHROPIC_MODELS_PAGE_SIZE,
)
from .model_catalog import (
    _GEMINI_MODELS_PAGE_SIZE as _GEMINI_MODELS_PAGE_SIZE,
)
from .model_catalog import (
    _NATIVE_MODEL_DISCOVERY_MAX_MODELS as _NATIVE_MODEL_DISCOVERY_MAX_MODELS,
)
from .model_catalog import (
    _NATIVE_MODEL_DISCOVERY_MAX_PAGES as _NATIVE_MODEL_DISCOVERY_MAX_PAGES,
)
from .redaction import redact_provider_error
from .runtime_shared import (
    _looks_like_tools_unsupported_error,
    logger,
)
from .service_support import (
    agent_tool_events as _agent_tool_events,
)
from .service_support import (
    agentic_recoverable_grounded_stop_reason as _agentic_recoverable_grounded_stop_reason,
)
from .service_support import (
    optional_text as _optional_text,
)
from .service_support import (
    timeout_recovery_should_replace_content as _timeout_recovery_should_replace_content,
)
from .text import (
    _mixed_script_reply_corruption_detail,
    _strip_short_cyrillic_noise,
    _visible_model_text,
)


class _ProviderHttpxProxy:
    def __getattr__(self, name: str) -> Any:
        ps_mod = _sys.modules.get("app.llm.provider_service")
        target = getattr(ps_mod, "httpx", _real_httpx) if ps_mod is not None else _real_httpx
        return getattr(target, name)


httpx: Any = _ProviderHttpxProxy()


def build_vision_challenge(*args: Any, **kwargs: Any) -> Any:
    ps_mod = _sys.modules.get("app.llm.provider_service")
    fn = getattr(ps_mod, "build_vision_challenge", _real_build_vision_challenge) if ps_mod is not None else _real_build_vision_challenge
    return fn(*args, **kwargs)


def build_coaching_messages(*args: Any, **kwargs: Any) -> Any:
    ps_mod = _sys.modules.get("app.llm.provider_service")
    fn = getattr(ps_mod, "build_coaching_messages", _real_build_coaching_messages) if ps_mod is not None else _real_build_coaching_messages
    return fn(*args, **kwargs)


def _has_passed_current_file_practice_verification(tool_events: list[dict[str, Any]]) -> bool:
    result = _current_file_practice_verification_result(tool_events)
    return isinstance(result, dict) and result.get("passed") is True


class AgenticExecutionMixin:
    if TYPE_CHECKING:
        _agent_loop_timeout_kwargs: Any
        _agent_provider_context_budget_exhausted: Any
        _api_key: Any
        _coaching_requested_output_tokens: Any
        _config: Any
        _context_budget_agentic_result: Any
        _context_budget_status_reply: Any
        _error_reply_with_scaffold: Any
        _last_reply_failure: Any
        _llm_reply: Any
        _missing_api_key_reply: Any
        _onboarding_reply: Any
        _prepare_context_budget: Any
        _record_reply_language_corruption: Any
        _sanitize_agentic_visible_reply: Any
        _scaffold_reply: Any
        _smart_coaching_history_budget: Any
        _visible_empty_reply_guidance: Any
        build_agent_provider: Any
        clear_last_reply_state: Any
        coaching_reply_stream: Any
        consume_last_reply_failure: Any
        consume_last_reply_override: Any
        describe_attachment_delivery: Any
        has_usable_credential: Any
        provider_failure_next_step: Any
        provider_failure_reply: Any
        provider_failure_summary: Any
        reset_transport_client: Any

    def _agent_provider_failure_result(
        self,
        provider: object,
        *,
        response_language: str | None,
        attachment_delivery: dict[str, Any],
        steps: list[dict[str, Any]],
        tool_events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        failure = getattr(provider, "last_failure", None)
        if not isinstance(failure, dict):
            return None
        category = str(failure.get("error_category") or "").strip()
        if not category:
            return None
        summary = self.provider_failure_summary(category, response_language)
        next_step = self.provider_failure_next_step(category, response_language)
        # The binding keeps only the category of the failure, never the provider's message, so the
        # reply carries no detail line. Passing the summary as the detail repeated it, and storing
        # the composed reply as the failure's detail let the route wrap that reply around itself.
        content = self.provider_failure_reply(category, None, response_language)
        # Restore only classified, safe facts in the request owner's task.
        # Never let the local teaching scaffold conceal an upstream failure.
        if category in {"network", "timeout", "upstream_unavailable", "unknown"}:
            self.reset_transport_client()
        self._last_reply_failure.set({**failure, "detail": "", "error": summary})
        return {
            "content": content,
            "summary": summary,
            "next_step": next_step,
            "resume_thread": _agentic_resume_thread_text(
                summary, next_step, response_language=response_language,
            ),
            "stop_reason": category,
            "steps": steps,
            "tool_events": tool_events,
            "evidence": [],
            "fell_back": True,
            "retryable": bool(failure.get("retryable")),
            "recoverable": True,
            **attachment_delivery,
        }

    def _build_agent_provider_with_budget(
        self,
        *,
        attachments: list[dict[str, Any]] | None,
        protocol: str | None,
        max_tokens: int,
        messages: list[dict[str, Any]],
    ):
        try:
            return self.build_agent_provider(
                attachments=attachments,
                protocol=protocol,
                max_tokens=max_tokens,
                messages=messages,
            )
        except TypeError as error:
            detail = str(error)
            if "unexpected keyword argument" not in detail or "max_tokens" not in detail:
                raise

        try:
            return self.build_agent_provider(
                attachments=attachments,
                protocol=protocol,
                messages=messages,
            )
        except TypeError as error:
            detail = str(error)
            if "unexpected keyword argument" not in detail or "messages" not in detail:
                raise

        return self.build_agent_provider(
            attachments=attachments,
            protocol=protocol,
        )

    async def coaching_reply_agentic(
        self,
        profile: UserProfile | None,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        max_steps: int | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Drive the coach agent loop and return a structured outcome.

        On any agent error, the result falls back to ``coaching_reply``'s
        text output so callers always have something to show. The dict
        shape is::

            {
              "content": str,           # final assistant text
              "steps": [...],           # AgentStep dicts (best-effort)
              "summary": str | None,
              "next_step": str | None,
              "stop_reason": str,
              "tool_events": [...],     # tool_call+tool_result pairs
              "fell_back": bool,
            }
        """
        self.clear_last_reply_state()
        attachment_delivery = self.describe_attachment_delivery(
            attachments=attachments,
            protocol=protocol,
            use_agent_loop=True,
        )
        provider_attachments = (
            list(attachments or [])
            if bool(attachment_delivery.get("attachments_delivered_to_model"))
            else None
        )
        if not self.has_usable_credential():
            return {
                "content": self._missing_api_key_reply(response_language),
                "steps": [],
                "summary": None,
                "next_step": None,
                "stop_reason": "missing_api_key",
                "tool_events": [],
                "fell_back": True,
                **attachment_delivery,
            }
        if not profile:
            return {
                "content": self._onboarding_reply(response_language),
                "steps": [],
                "summary": None,
                "next_step": None,
                "stop_reason": "onboarding",
                "tool_events": [],
                "fell_back": True,
                **attachment_delivery,
            }
        from ..agent_loop import CoachAgentLoop
        from ..mcp_client import build_coach_mcp_tools
        from ..tools import ToolContext, build_default_tool_registry

        history_limit, history_token_budget = self._smart_coaching_history_budget()
        # The tool scope is decided before the prompt: a turn that mounts no tools (a short
        # follow-up beside a live error) must not be told it is running inside a tool loop.
        tool_context_extra = _build_agent_tool_context_extra(
            coach_context=coach_context,
            attachment_delivery=attachment_delivery,
            answer_mode=answer_mode or profile.answer_policy,
            current_file=current_file,
            provider_config=self._config,
            learner_message=message,
        )
        messages = build_coaching_messages(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            agent_loop_enabled=tool_context_extra.get("allowed_tool_names") != [],
            history=history,
            history_limit=history_limit,
            history_token_budget=history_token_budget,
        )
        try:
            messages, max_tokens = self._prepare_context_budget(
                messages,
                requested_max_tokens=self._coaching_requested_output_tokens(
                    message,
                    coach_context,
                    agent_loop_enabled=True,
                ),
                prefer_configured_output=True,
            )
        except ContextBudgetExhaustedError:
            return self._context_budget_agentic_result(
                response_language=response_language,
                attachment_delivery=attachment_delivery,
            )
        provider_obj, binding = self._build_agent_provider_with_budget(
            attachments=provider_attachments,
            protocol=protocol,
            max_tokens=max_tokens,
            messages=messages,
        )
        runtime_obj = (coach_context or {}).get("__runtime__") if coach_context else None
        workspace_id = str((coach_context or {}).get("workspace_id") or "workspace-default")
        session_id = str((coach_context or {}).get("session_id") or "")
        # P1 Skills 深化: condition-triggered injection of activated skills.
        # The guidance block never expands tool authority; usage flows back
        # to memory after the loop completes (record_skill_usage).
        selected_skills: list[Any] = []
        skill_guidance = ""
        try:
            from ...skills.runtime import (
                build_skill_guidance_block,
                runtime_skill_registry,
                select_active_skills,
            )

            skill_registry = runtime_skill_registry(runtime_obj)
            if skill_registry is not None and str(message or "").strip():
                selected_skills = select_active_skills(
                    skill_registry, str(message), workspace_id=workspace_id
                )
                skill_guidance = build_skill_guidance_block(
                    selected_skills, workspace_id=workspace_id
                )
        except Exception:
            logger.warning("skill_guidance_selection_failed", exc_info=True)
        if skill_guidance:
            if messages and messages[0].get("role") == "system":
                messages = [
                    {**messages[0], "content": f"{messages[0].get('content', '')}\n\n{skill_guidance}"},
                    *messages[1:],
                ]
            else:
                messages = [{"role": "system", "content": skill_guidance}, *messages]
        registry = build_default_tool_registry(
            extra_tools=await build_coach_mcp_tools(runtime_obj, workspace_id)
        )
        context = ToolContext(
            runtime=runtime_obj,
            workspace_id=workspace_id,
            session_id=session_id or None,
            profile=profile,
            response_language=response_language,
            extra=tool_context_extra,
        )
        loop = CoachAgentLoop(
            provider=provider_obj,
            registry=registry,
            context=context,
            max_steps=_agent_loop_max_steps(coach_context, max_steps),
            **self._agent_loop_timeout_kwargs(),
        )
        try:
            result = await loop.run(messages)
        except ContextBudgetExhaustedError:
            return self._context_budget_agentic_result(
                response_language=response_language,
                attachment_delivery=attachment_delivery,
            )
        except Exception as exc:
            fallback = await self._llm_reply(
                profile,
                message,
                current_file,
                response_language,
                answer_mode,
                coach_context=coach_context,
                history=history,
            )
            fallback_summary, fallback_next_step = _agentic_fallback_continuity(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            fallback_resume_thread = _agentic_resume_thread_text(
                fallback_summary,
                fallback_next_step,
                response_language=response_language,
            )
            return {
                "content": fallback,
                "steps": [],
                "summary": fallback_summary,
                "next_step": fallback_next_step,
                "stop_reason": f"agent_error: {exc.__class__.__name__}",
                "resume_thread": fallback_resume_thread,
                "tool_events": [],
                "fell_back": True,
                **attachment_delivery,
            }
        if selected_skills:
            # 执行结果回流: skill usage facts → registry stats + memory highlight.
            try:
                from ...skills.runtime import record_skill_usage

                record_skill_usage(
                    runtime_obj,
                    workspace_id,
                    session_id,
                    selected_skills,
                    stop_reason=str(getattr(result, "stop_reason", "") or ""),
                    final_content=str(getattr(result, "final_content", "") or ""),
                    tool_events=[
                        dict(event)
                        for step in getattr(result, "steps", []) or []
                        for event in getattr(step, "tool_results", []) or []
                        if isinstance(event, dict)
                    ],
                )
            except Exception:
                logger.warning("skill_usage_record_failed", exc_info=True)
        if self._agent_provider_context_budget_exhausted(provider_obj):
            return self._context_budget_agentic_result(
                response_language=response_language,
                attachment_delivery=attachment_delivery,
            )
        if result.stop_reason == "provider_error":
            transport_failure = self._agent_provider_failure_result(
                provider_obj,
                response_language=response_language,
                attachment_delivery=attachment_delivery,
                steps=[self._step_to_dict(step) for step in result.steps],
                tool_events=_agent_tool_events(result),
            )
            if transport_failure is not None:
                return transport_failure
        fell_back = False
        recovered_stop_reason: str | None = None
        tool_events = _agent_tool_events(result)
        grounded_resource_evidence = _agentic_has_grounded_resource_evidence(tool_events)
        # When the model never produced text (e.g. only tool calls then max_steps)
        # surface a short scaffold so the bubble isn't empty.
        final_text = _agent_result_visible_text(result)
        if not final_text.strip() and result.stop_reason == "empty_response":
            if not tool_events:
                self.clear_last_reply_state()
                plain_reply = await self._llm_reply(
                    profile,
                    message,
                    current_file,
                    response_language,
                    answer_mode,
                    coach_context=coach_context,
                    history=history,
                )
                plain_failure = self.consume_last_reply_failure()
                plain_override = self.consume_last_reply_override()
                plain_stop_reason = (
                    str(plain_override.get("stop_reason") or "").strip()
                    if isinstance(plain_override, dict)
                    else ""
                )
                if (
                    plain_reply.strip()
                    and plain_failure is None
                    and plain_stop_reason != "empty_response"
                ):
                    final_text = plain_reply
                    result.stop_reason = "completed"
                    result.summary = None
                    result.next_step = None
                    result.resume_thread = None
            if not final_text.strip():
                guided_recovery = _guided_domain_empty_reply_override(
                    message,
                    current_file=current_file,
                    coach_context=coach_context,
                    response_language=response_language,
                )
                final_text = self._visible_empty_reply_guidance(
                    profile=profile,
                    message=message,
                    current_file=current_file,
                    response_language=response_language,
                    answer_mode=answer_mode,
                    coach_context=coach_context,
                )
                if isinstance(guided_recovery, dict) and final_text.strip():
                    recovered_stop_reason = "empty_response"
                    result.stop_reason = "completed"
                    result.summary = guided_recovery.get("summary") or result.summary
                    result.next_step = guided_recovery.get("next_step") or result.next_step
                    result.teaching_note = (
                        guided_recovery.get("teaching_note")
                        or getattr(result, "teaching_note", None)
                    )
                    result.resume_thread = _agentic_resume_thread_text(
                        result.summary,
                        result.next_step,
                        response_language=response_language,
                    )
        recoverable_grounded_stop_reason = (
            _agentic_recoverable_grounded_stop_reason(result.stop_reason)
            if grounded_resource_evidence
            else ""
        )
        if recoverable_grounded_stop_reason:
            self.clear_last_reply_state()
            plain_reply = await self._llm_reply(
                profile,
                message,
                current_file,
                response_language,
                answer_mode,
                coach_context=coach_context,
                history=history,
            )
            plain_failure = self.consume_last_reply_failure()
            plain_override = self.consume_last_reply_override()
            plain_stop_reason = (
                str(plain_override.get("stop_reason") or "").strip()
                if isinstance(plain_override, dict)
                else ""
            )
            if (
                plain_reply.strip()
                and plain_failure is None
                and plain_stop_reason not in {"empty_response", "max_steps", "no_progress"}
            ):
                final_text = plain_reply
                result.stop_reason = "completed"
                result.summary = None
                result.next_step = None
                result.resume_thread = None
                recovered_stop_reason = recoverable_grounded_stop_reason
                fell_back = True
        if str(result.stop_reason or "").strip() == "timeout":
            timeout_recovery = _build_timeout_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(timeout_recovery, dict):
                result.summary = _optional_text(timeout_recovery.get("summary")) or result.summary
                result.next_step = _optional_text(timeout_recovery.get("next_step")) or result.next_step
                result.teaching_note = _optional_text(timeout_recovery.get("teaching_note")) or result.teaching_note
                result.resume_thread = _optional_text(timeout_recovery.get("resume_thread")) or _agentic_resume_thread_text(
                    result.summary,
                    result.next_step,
                    response_language=response_language,
                )
                timeout_reply = str(timeout_recovery.get("reply") or "").strip()
                if timeout_reply and _timeout_recovery_should_replace_content(final_text):
                    final_text = timeout_reply
                fell_back = True
        if str(result.stop_reason or "").strip() == "provider_error":
            if not tool_events and _looks_like_tools_unsupported_error(getattr(result, "error", None)):
                self.clear_last_reply_state()
                try:
                    plain_reply = await self._llm_reply(
                        profile,
                        message,
                        current_file,
                        response_language,
                        answer_mode,
                        coach_context=coach_context,
                        history=history,
                    )
                except Exception as exc:
                    logger.debug("Suppressed exception in agentic_execution_mixin: %s", exc)
                    plain_reply = ""
                plain_failure = self.consume_last_reply_failure()
                plain_override = self.consume_last_reply_override()
                plain_stop_reason = (
                    str(plain_override.get("stop_reason") or "").strip()
                    if isinstance(plain_override, dict)
                    else ""
                )
                if (
                    plain_reply.strip()
                    and plain_failure is None
                    and plain_stop_reason not in {"empty_response", "provider_error"}
                ):
                    final_text = plain_reply
                    result.stop_reason = "completed"
                    result.summary = None
                    result.next_step = None
                    result.resume_thread = None
                    fell_back = True
            if str(result.stop_reason or "").strip() == "provider_error":
                provider_error_recovery = _build_provider_error_recovery_override(
                    message,
                    current_file=current_file,
                    coach_context=coach_context,
                    response_language=response_language,
                    error_detail=getattr(result, "error", None),
                )
                result.summary = _optional_text(provider_error_recovery.get("summary")) or result.summary
                result.next_step = _optional_text(provider_error_recovery.get("next_step")) or result.next_step
                result.teaching_note = _optional_text(provider_error_recovery.get("teaching_note")) or result.teaching_note
                result.resume_thread = _optional_text(provider_error_recovery.get("resume_thread")) or _agentic_resume_thread_text(
                    result.summary,
                    result.next_step,
                    response_language=response_language,
                )
                provider_error_reply = str(provider_error_recovery.get("reply") or "").strip()
                if provider_error_reply:
                    final_text = provider_error_reply
                fell_back = True
        if not final_text.strip() and result.stop_reason == "coach_finalize":
            self.clear_last_reply_state()
            try:
                plain_reply = await self._llm_reply(
                    profile,
                    message,
                    current_file,
                    response_language,
                    answer_mode,
                    coach_context=coach_context,
                    history=history,
                )
            except Exception as exc:
                logger.debug("Suppressed exception in agentic_execution_mixin: %s", exc)
                plain_reply = ""
            plain_failure = self.consume_last_reply_failure()
            plain_override = self.consume_last_reply_override()
            plain_stop_reason = (
                str(plain_override.get("stop_reason") or "").strip()
                if isinstance(plain_override, dict)
                else ""
            )
            if (
                plain_reply.strip()
                and plain_failure is None
                and plain_stop_reason != "empty_response"
            ):
                final_text = plain_reply
                result.stop_reason = "completed"
        if not final_text.strip():
            final_text = self._scaffold_reply(
                profile,
                message,
                current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
        final_text = self._sanitize_agentic_visible_reply(
            final_text,
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            tool_events=tool_events,
        )
        reply_corruption_detail = _mixed_script_reply_corruption_detail(
            final_text,
            message=message,
            response_language=response_language,
        )
        if reply_corruption_detail:
            self._record_reply_language_corruption(reply_corruption_detail)
            recovery_override = _build_language_corruption_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(recovery_override, dict):
                result.summary = str(recovery_override.get("summary") or "").strip() or (
                    self.provider_failure_summary("language_corruption", response_language)
                )
                result.next_step = str(recovery_override.get("next_step") or "").strip() or (
                    self.provider_failure_next_step("language_corruption", response_language)
                )
                result.teaching_note = str(recovery_override.get("teaching_note") or "").strip()
                result.blocker = reply_corruption_detail
                result.stop_reason = "language_corruption_recovered"
                result.resume_thread = str(recovery_override.get("resume_thread") or "").strip() or (
                    _agentic_resume_thread_text(
                        result.summary,
                        result.next_step,
                        response_language=response_language,
                    )
                )
                final_text = str(recovery_override.get("reply") or "").strip() or self.provider_failure_reply(
                    "language_corruption",
                    reply_corruption_detail,
                    response_language,
                )
                fell_back = True
            else:
                result.summary = self.provider_failure_summary(
                    "language_corruption",
                    response_language,
                )
                result.next_step = self.provider_failure_next_step(
                    "language_corruption",
                    response_language,
                )
                result.stop_reason = "language_corruption"
                result.resume_thread = _agentic_resume_thread_text(
                    result.summary,
                    result.next_step,
                    response_language=response_language,
                )
                final_text = self.provider_failure_reply(
                    "language_corruption",
                    reply_corruption_detail,
                    response_language,
                )
        tool_events.extend(
            await _maybe_auto_verify_practice_current_file(
                registry=registry,
                context=context,
                tool_events=tool_events,
                message=message,
                content=final_text,
                current_file=current_file,
                coach_context=coach_context,
            )
        )
        guard = _agentic_practice_completion_guard(
            content=final_text,
            tool_events=tool_events,
            message=message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if guard is not None:
            final_text = guard["content"]
            result.summary = guard["summary"]
            result.next_step = guard["next_step"]
            result.stop_reason = guard["stop_reason"]
        else:
            summary, next_step = _agentic_completion_continuity(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
                content=final_text,
            )
            if not str(result.summary or "").strip():
                result.summary = summary
            if not str(result.next_step or "").strip():
                result.next_step = next_step
        generated_image_ids = list(context.extra.get("generated_image_ids") or [])
        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario") or "").strip()
        history_mode = str(context.get("history_mode") or "").strip().lower()
        chinese = _prefers_chinese(response_language)
        summary_before_visible = str(result.summary or "").strip()
        next_step_before_visible = str(result.next_step or "").strip()
        if str(result.summary or "").strip():
            result.summary = _sanitize_agentic_continuity_text(
                str(result.summary or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="summary",
                response_language=response_language,
                coach_context=context,
                current_file=current_file,
            )
        if str(result.next_step or "").strip():
            result.next_step = _sanitize_agentic_continuity_text(
                str(result.next_step or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="next_step",
                response_language=response_language,
                coach_context=context,
                current_file=current_file,
            )
        summary_changed_for_visible = str(result.summary or "").strip() != summary_before_visible
        next_step_changed_for_visible = str(result.next_step or "").strip() != next_step_before_visible
        if (
            not str(getattr(result, "resume_thread", "") or "").strip()
            or summary_changed_for_visible
            or next_step_changed_for_visible
        ):
            result.resume_thread = _agentic_resume_thread_text(
                result.summary,
                result.next_step,
                response_language=response_language,
            )
        if str(getattr(result, "resume_thread", "") or "").strip():
            sanitized_resume_thread = _sanitize_agentic_continuity_text(
                str(getattr(result, "resume_thread", "") or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="resume_thread",
                response_language=response_language,
                coach_context=context,
                current_file=current_file,
            )
            if summary_changed_for_visible or next_step_changed_for_visible:
                result.resume_thread = _normalize_visible_resume_thread_text(
                    sanitized_resume_thread,
                    chinese=chinese,
                )
            else:
                result.resume_thread = sanitized_resume_thread
        if generated_image_ids or "trainer-image://" in final_text:
            from ..image_generation import resolve_generated_images_in_text

            final_text = resolve_generated_images_in_text(
                final_text,
                runtime_obj,
                generated_image_ids,
            )
        return {
            "content": final_text,
            "steps": [self._step_to_dict(step) for step in result.steps],
            "summary": result.summary,
            "next_step": result.next_step,
            "stop_reason": result.stop_reason,
            "decision": getattr(result, "decision", None),
            "blocker": getattr(result, "blocker", None),
            "teaching_note": getattr(result, "teaching_note", None),
            "resume_thread": getattr(result, "resume_thread", None),
            "confidence": getattr(result, "confidence", None),
            "evidence": getattr(result, "evidence", None),
            "tool_events": tool_events,
            "fell_back": fell_back,
            "recovered_stop_reason": recovered_stop_reason,
            # Cost ledger v1: Trainer-side estimates (chars/4), clearly labeled
            # so the ledger never passes estimates off as provider truth.
            "token_usage": {
                "estimate": "chars/4",
                "prompt_tokens_estimate": estimate_tokens(messages),
                "reply_tokens_estimate": estimate_tokens(
                    [{"role": "assistant", "content": final_text}]
                ),
                "tool_call_count": len(tool_events or []),
            },
            **attachment_delivery,
        }

    async def coaching_reply_agentic_stream(
        self,
        profile: UserProfile | None,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        max_steps: int | None = None,
        history: list[dict[str, str]] | None = None,
    ):
        """Yield typed agent events for the stream transport.

        Text is held until the final response has passed the same integrity
        checks as a non-streaming reply. Tool progress remains live.
        """
        self.clear_last_reply_state()
        attachment_delivery = self.describe_attachment_delivery(
            attachments=attachments,
            protocol=protocol,
            use_agent_loop=True,
        )
        provider_attachments = (
            list(attachments or [])
            if bool(attachment_delivery.get("attachments_delivered_to_model"))
            else None
        )
        if not self.has_usable_credential():
            yield {
                "type": "final",
                "content": self._missing_api_key_reply(response_language),
                "summary": None,
                "next_step": None,
                "stop_reason": "missing_api_key",
                **attachment_delivery,
            }
            return
        if not profile:
            yield {
                "type": "final",
                "content": self._onboarding_reply(response_language),
                "summary": None,
                "next_step": None,
                "stop_reason": "onboarding",
                **attachment_delivery,
            }
            return
        from ..agent_loop import CoachAgentLoop
        from ..mcp_client import build_coach_mcp_tools
        from ..tools import ToolContext, build_default_tool_registry

        history_limit, history_token_budget = self._smart_coaching_history_budget()
        # The tool scope is decided before the prompt: a turn that mounts no tools (a short
        # follow-up beside a live error) must not be told it is running inside a tool loop.
        tool_context_extra = _build_agent_tool_context_extra(
            coach_context=coach_context,
            attachment_delivery=attachment_delivery,
            answer_mode=answer_mode or profile.answer_policy,
            current_file=current_file,
            provider_config=self._config,
            learner_message=message,
        )
        messages = build_coaching_messages(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            agent_loop_enabled=tool_context_extra.get("allowed_tool_names") != [],
            history=history,
            history_limit=history_limit,
            history_token_budget=history_token_budget,
        )
        try:
            messages, max_tokens = self._prepare_context_budget(
                messages,
                requested_max_tokens=self._coaching_requested_output_tokens(
                    message,
                    coach_context,
                    agent_loop_enabled=True,
                ),
                prefer_configured_output=True,
            )
        except ContextBudgetExhaustedError:
            yield {
                "type": "final",
                "content": self._context_budget_status_reply(response_language),
                "summary": None,
                "next_step": None,
                "stop_reason": "context_budget_exhausted",
                "fell_back": False,
                **attachment_delivery,
            }
            return
        provider_obj, binding = self._build_agent_provider_with_budget(
            attachments=provider_attachments,
            protocol=protocol,
            max_tokens=max_tokens,
            messages=messages,
        )
        runtime_obj = (coach_context or {}).get("__runtime__") if coach_context else None
        workspace_id = str((coach_context or {}).get("workspace_id") or "workspace-default")
        session_id = str((coach_context or {}).get("session_id") or "")
        # P1 Skills 深化: condition-triggered injection of activated skills.
        # The guidance block never expands tool authority; usage flows back
        # to memory after the loop completes (record_skill_usage).
        selected_skills: list[Any] = []
        skill_guidance = ""
        try:
            from ...skills.runtime import (
                build_skill_guidance_block,
                runtime_skill_registry,
                select_active_skills,
            )

            skill_registry = runtime_skill_registry(runtime_obj)
            if skill_registry is not None and str(message or "").strip():
                selected_skills = select_active_skills(
                    skill_registry, str(message), workspace_id=workspace_id
                )
                skill_guidance = build_skill_guidance_block(
                    selected_skills, workspace_id=workspace_id
                )
        except Exception:
            logger.warning("skill_guidance_selection_failed", exc_info=True)
        if skill_guidance:
            if messages and messages[0].get("role") == "system":
                messages = [
                    {**messages[0], "content": f"{messages[0].get('content', '')}\n\n{skill_guidance}"},
                    *messages[1:],
                ]
            else:
                messages = [{"role": "system", "content": skill_guidance}, *messages]
        registry = build_default_tool_registry(
            extra_tools=await build_coach_mcp_tools(runtime_obj, workspace_id)
        )
        context = ToolContext(
            runtime=runtime_obj,
            workspace_id=workspace_id,
            session_id=session_id or None,
            profile=profile,
            response_language=response_language,
            extra=tool_context_extra,
        )
        loop = CoachAgentLoop(
            provider=provider_obj,
            registry=registry,
            context=context,
            max_steps=_agent_loop_max_steps(coach_context, max_steps),
            **self._agent_loop_timeout_kwargs(),
        )
        try:
            native_stream_available = provider_obj.call_stream is not None
            if not native_stream_available:
                # A stream endpoint must never silently downgrade to a buffered
                # completion. Callers can retry after choosing a stream-capable
                # provider and the UI can keep the lane explicitly blocked.
                detail = (
                    "The configured provider does not expose native streaming; "
                    "Trainer cannot continue this streaming action."
                )
                summary = self.provider_failure_summary(
                    "streaming_unavailable",
                    response_language,
                )
                next_step = self.provider_failure_next_step(
                    "streaming_unavailable",
                    response_language,
                )
                yield {
                    "type": "error",
                    "detail": detail,
                    "category": "streaming_unavailable",
                    "recoverable": True,
                    "terminal": True,
                    "degraded": False,
                }
                yield {
                    "type": "final",
                    "content": self.provider_failure_reply(
                        "streaming_unavailable",
                        detail,
                        response_language,
                    ),
                    "summary": summary,
                    "next_step": next_step,
                    "resume_thread": _agentic_resume_thread_text(
                        summary,
                        next_step,
                        response_language=response_language,
                    ),
                    "stop_reason": "streaming_unavailable",
                    "fell_back": False,
                    "recoverable": True,
                    **attachment_delivery,
                }
                return
            buffered_text = ""
            streamed_visible_text = ""
            tool_events: list[dict[str, Any]] = []
            holdback_chars = _stream_holdback_chars(response_language)
            # The learner's own code is never handed back rewritten (learner_code_guard). A fenced
            # block is shown whole once it closes, so what is shown is a prefix that only grows.
            # A block still open when the text ends stays unshown, like any other unfinished tail.
            learner = LearnerCode.for_turn(current_file=current_file, message=message)
            code_note = learner_code_note(chinese=_prefers_chinese(response_language))

            def guardable(buffered: str) -> str:
                return streamable_learner_reply(_streamable_visible_prefix(buffered), learner, note=code_note)

            def safe_direct_reply_prefix() -> str:
                if not native_stream_available or (
                    isinstance(coach_context, dict) and bool(coach_context.get("exercise_prompt"))
                ):
                    return ""
                visible = guardable(buffered_text)
                if "trainer-image://" in visible:
                    cut_idx = visible.find("trainer-image://")
                    bang_idx = visible.rfind("![", 0, cut_idx)
                    visible = visible[: bang_idx if bang_idx >= 0 else cut_idx].rstrip()
                tail_sample = visible[-256:]
                if (
                    not visible
                    or (
                        any("\u0370" <= ch <= "\u0e7f" for ch in tail_sample)
                        and (
                            _mixed_script_reply_corruption_detail(
                                tail_sample,
                                message=message,
                                response_language=response_language,
                            )
                            or _strip_short_cyrillic_noise(tail_sample, message=message) != tail_sample
                        )
                    )
                    or len(visible) <= holdback_chars
                ):
                    return ""
                available = visible if holdback_chars <= 0 else visible[:-holdback_chars]
                if not available.startswith(streamed_visible_text):
                    return ""
                return available[len(streamed_visible_text) :]

            pending_tool_error: dict[str, Any] | None = None
            async for event in loop.run_stream(messages):
                if self._agent_provider_context_budget_exhausted(provider_obj):
                    yield {
                        "type": "final",
                        "content": self._context_budget_status_reply(response_language),
                        "summary": None,
                        "next_step": None,
                        "stop_reason": "context_budget_exhausted",
                        "fell_back": False,
                        **attachment_delivery,
                    }
                    return
                event_type = str(event.get("type") or "")
                if event_type == "step":
                    # Separate prose emitted in distinct agent steps so a
                    # tool-calling preamble never glues directly onto the final
                    # answer without a paragraph break.
                    if buffered_text and not buffered_text.endswith("\n\n"):
                        buffered_text = buffered_text.rstrip() + "\n\n"
                    yield event
                    continue
                if event_type == "tool_call" or event_type == "tool_result":
                    tool_events.append(dict(event))
                if event_type == "text":
                    delta = str(event.get("delta") or "")
                    buffered_text += delta
                    if event.get("safe_to_stream") is True:
                        # Native tool-capable streams can expose visible model
                        # text before the tool decision arrives. Keep the
                        # guardrails that strip internal metadata and reject
                        # mixed-script corruption, while preserving single-newline
                        # fenced code blocks so long lectures stream incrementally.
                        visible = guardable(buffered_text)
                        tail_sample = visible[-256:]
                        has_non_latin_tail = any("\u0370" <= ch <= "\u0e7f" for ch in tail_sample)
                        if (
                            visible
                            and (
                                not has_non_latin_tail
                                or (
                                    _strip_short_cyrillic_noise(tail_sample, message=message) == tail_sample
                                    and not _mixed_script_reply_corruption_detail(
                                        tail_sample,
                                        message=message,
                                        response_language=response_language,
                                    )
                                )
                            )
                            and visible.startswith(streamed_visible_text)
                        ):
                            safe_delta = visible[len(streamed_visible_text) :]
                            if safe_delta:
                                streamed_visible_text = visible
                                yield {
                                    "type": "text",
                                    "delta": safe_delta,
                                    "safe_to_stream": True,
                                }
                        continue
                    safe_delta = safe_direct_reply_prefix()
                    if safe_delta:
                        streamed_visible_text += safe_delta
                        yield {
                            "type": "text",
                            "delta": safe_delta,
                            "safe_to_stream": True,
                        }
                    continue
                if event_type == "final":
                    if selected_skills:
                        # 执行结果回流 (streaming path): usage facts → registry
                        # stats + memory highlight, exactly like the buffered path.
                        try:
                            from ...skills.runtime import record_skill_usage

                            record_skill_usage(
                                runtime_obj,
                                workspace_id,
                                session_id,
                                selected_skills,
                                stop_reason=str(event.get("stop_reason") or ""),
                                final_content=str(event.get("content") or ""),
                                tool_events=tool_events,
                            )
                        except Exception:
                            logger.warning("skill_usage_record_failed", exc_info=True)
                    if event.get("stop_reason") == "provider_error":
                        if (
                            not tool_events
                            and not streamed_visible_text
                            and (
                                pending_tool_error is not None
                                or _looks_like_tools_unsupported_error(
                                    event.get("error") or event.get("detail")
                                )
                            )
                        ):
                            self.clear_last_reply_state()
                            plain_chunks: list[str] = []
                            try:
                                async for chunk in self.coaching_reply_stream(
                                    profile,
                                    message,
                                    current_file,
                                    response_language=response_language,
                                    answer_mode=answer_mode,
                                    coach_context=coach_context,
                                    history=history,
                                ):
                                    if chunk:
                                        plain_chunks.append(chunk)
                                        streamed_visible_text += chunk
                                        yield {
                                            "type": "text",
                                            "delta": chunk,
                                            "safe_to_stream": True,
                                        }
                            except Exception as exc:
                                logger.debug("Suppressed exception in agentic_execution_mixin: %s", exc)
                                plain_chunks = []
                            plain_failure = self.consume_last_reply_failure()
                            plain_text = "".join(plain_chunks).strip()
                            if plain_text and plain_failure is None:
                                yield {
                                    "type": "final",
                                    "content": plain_text,
                                    "summary": None,
                                    "next_step": None,
                                    "stop_reason": "completed",
                                    "fell_back": True,
                                    **attachment_delivery,
                                }
                                return
                        if pending_tool_error is not None:
                            yield pending_tool_error
                            pending_tool_error = None
                        transport_failure = self._agent_provider_failure_result(
                            provider_obj,
                            response_language=response_language,
                            attachment_delivery=attachment_delivery,
                            steps=[],
                            tool_events=tool_events,
                        )
                        if transport_failure is not None:
                            yield {"type": "final", **transport_failure}
                            return
                    if not str(event.get("content") or "").strip():
                        event = {**event, "content": buffered_text}
                    event = await self._recover_agentic_stream_final_event(
                        event,
                        profile=profile,
                        message=message,
                        current_file=current_file,
                        response_language=response_language,
                        answer_mode=answer_mode,
                        coach_context=coach_context,
                        history=history,
                        tool_events=tool_events,
                    )
                    auto_events = await _maybe_auto_verify_practice_current_file(
                        registry=registry,
                        context=context,
                        tool_events=tool_events,
                        message=message,
                        content=str(event.get("content") or ""),
                        current_file=current_file,
                        coach_context=coach_context,
                    )
                    for auto_event in auto_events:
                        tool_events.append(auto_event)
                        yield auto_event
                    event = self._visible_agentic_final_event(
                        event,
                        profile=profile,
                        message=message,
                        current_file=current_file,
                        response_language=response_language,
                        answer_mode=answer_mode,
                        coach_context=coach_context,
                        tool_events=tool_events,
                    )
                    generated_image_ids = list(context.extra.get("generated_image_ids") or [])
                    resolved_content = str(event.get("content") or "")
                    if generated_image_ids or "trainer-image://" in resolved_content:
                        from ..image_generation import resolve_generated_images_in_text

                        event = {
                            **event,
                            "content": resolve_generated_images_in_text(
                                resolved_content,
                                runtime_obj,
                                generated_image_ids,
                            ),
                        }
                elif event_type == "error":
                    # AgentLoop emits a recovery final after provider errors.
                    # Mark this frame explicitly so SSE consumers do not
                    # mistake it for a terminal stream failure.
                    event = {
                        **event,
                        "recoverable": event.get("recoverable", True),
                        "terminal": event.get("terminal", False),
                        "degraded": event.get("degraded", True),
                    }
                    transport_failure = self._agent_provider_failure_result(
                        provider_obj,
                        response_language=response_language,
                        attachment_delivery=attachment_delivery,
                        steps=[],
                        tool_events=tool_events,
                    )
                    if transport_failure is not None:
                        event = {
                            "type": "error",
                            "detail": transport_failure["content"],
                            "category": transport_failure["stop_reason"],
                            "retryable": transport_failure["retryable"],
                            "recoverable": True,
                            "terminal": False,
                            "degraded": True,
                        }
                    if (
                        not tool_events
                        and not streamed_visible_text
                        and _looks_like_tools_unsupported_error(event.get("detail"))
                    ):
                        pending_tool_error = dict(event)
                        continue
                yield event
        except ContextBudgetExhaustedError:
            yield {
                "type": "final",
                "content": self._context_budget_status_reply(response_language),
                "summary": None,
                "next_step": None,
                "stop_reason": "context_budget_exhausted",
                "fell_back": False,
                **attachment_delivery,
            }
        except Exception as exc:
            scaffold = self._error_reply_with_scaffold(
                exc=exc,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
            fallback_summary, fallback_next_step = _agentic_fallback_continuity(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            fallback_resume_thread = _agentic_resume_thread_text(
                fallback_summary,
                fallback_next_step,
                response_language=response_language,
            )
            yield {
                "type": "error",
                "detail": redact_provider_error(exc, api_key=self._api_key),
                "category": exc.__class__.__name__,
                "recoverable": True,
                "terminal": False,
                "degraded": True,
            }
            yield {
                "type": "final",
                "content": scaffold,
                "summary": fallback_summary,
                "next_step": fallback_next_step,
                "resume_thread": fallback_resume_thread,
                "stop_reason": "agent_error",
                **attachment_delivery,
            }

    async def _recover_agentic_stream_final_event(
        self,
        event: dict[str, Any],
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None,
        response_language: str | None,
        answer_mode: str | None,
        coach_context: dict[str, Any] | None,
        history: list[dict[str, str]] | None,
        tool_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        final_event = dict(event)
        content = _strip_internal_coach_meta(str(final_event.get("content") or ""))
        final_event["content"] = content
        stop_reason = str(final_event.get("stop_reason") or "").strip()
        grounded_resource_evidence = _agentic_has_grounded_resource_evidence(tool_events)
        needs_empty_response_recovery = not content.strip() and stop_reason == "empty_response"
        needs_finalize_visible_reply_recovery = (
            not content.strip() and stop_reason == "coach_finalize"
        )
        needs_timeout_recovery = stop_reason == "timeout"
        needs_provider_error_recovery = stop_reason == "provider_error"
        recoverable_grounded_stop_reason = (
            _agentic_recoverable_grounded_stop_reason(stop_reason)
            if grounded_resource_evidence
            else ""
        )
        needs_grounded_stop_recovery = bool(recoverable_grounded_stop_reason)
        if (
            not needs_empty_response_recovery
            and not needs_finalize_visible_reply_recovery
            and not needs_grounded_stop_recovery
            and not needs_timeout_recovery
            and not needs_provider_error_recovery
        ):
            return final_event
        if needs_timeout_recovery:
            timeout_recovery = _build_timeout_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(timeout_recovery, dict):
                recovery_content = str(timeout_recovery.get("reply") or "").strip()
                final_event["content"] = (
                    recovery_content
                    if recovery_content and _timeout_recovery_should_replace_content(content)
                    else content
                )
                final_event["summary"] = timeout_recovery.get("summary")
                final_event["next_step"] = timeout_recovery.get("next_step")
                final_event["teaching_note"] = timeout_recovery.get("teaching_note")
                final_event["resume_thread"] = timeout_recovery.get("resume_thread")
                final_event["fell_back"] = True
            return final_event
        if needs_provider_error_recovery:
            provider_error_recovery = _build_provider_error_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
                error_detail=str(final_event.get("error") or "").strip() or None,
            )
            final_event["content"] = str(provider_error_recovery.get("reply") or content).strip()
            final_event["summary"] = provider_error_recovery.get("summary")
            final_event["next_step"] = provider_error_recovery.get("next_step")
            final_event["teaching_note"] = provider_error_recovery.get("teaching_note")
            final_event["resume_thread"] = provider_error_recovery.get("resume_thread")
            final_event["fell_back"] = True
            return final_event
        if needs_empty_response_recovery and tool_events:
            return final_event

        self.clear_last_reply_state()
        plain_reply = await self._llm_reply(
            profile,
            message,
            current_file,
            response_language,
            answer_mode,
            coach_context=coach_context,
            history=history,
        )
        plain_failure = self.consume_last_reply_failure()
        plain_override = self.consume_last_reply_override()
        plain_stop_reason = (
            str(plain_override.get("stop_reason") or "").strip()
            if isinstance(plain_override, dict)
            else ""
        )
        if (
            plain_reply.strip()
            and plain_failure is None
            and plain_stop_reason not in {"empty_response", "max_steps", "no_progress"}
        ):
            final_event["content"] = plain_reply
            final_event["stop_reason"] = "completed"
            final_event["summary"] = None
            final_event["next_step"] = None
            final_event["resume_thread"] = None
            if needs_grounded_stop_recovery:
                final_event["recovered_stop_reason"] = recoverable_grounded_stop_reason
                final_event["fell_back"] = True
            return final_event
        if needs_grounded_stop_recovery:
            return final_event
        guided_recovery = _guided_domain_empty_reply_override(
            message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if isinstance(guided_recovery, dict):
            guided_reply = _guided_domain_empty_reply(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if guided_reply.strip():
                summary = guided_recovery.get("summary") or final_event.get("summary")
                next_step = guided_recovery.get("next_step") or final_event.get("next_step")
                final_event["content"] = guided_reply
                final_event["stop_reason"] = "completed"
                final_event["recovered_stop_reason"] = (
                    "coach_finalize"
                    if needs_finalize_visible_reply_recovery
                    else "empty_response"
                )
                final_event["summary"] = summary
                final_event["next_step"] = next_step
                final_event["teaching_note"] = guided_recovery.get("teaching_note")
                final_event["resume_thread"] = _agentic_resume_thread_text(
                    str(summary or "").strip(),
                    str(next_step or "").strip(),
                    response_language=response_language,
                )
        return final_event

    @staticmethod
    def _step_to_dict(step: Any) -> dict[str, Any]:
        return {
            "index": getattr(step, "index", -1),
            "assistant_content": getattr(step, "assistant_content", ""),
            "tool_calls": list(getattr(step, "tool_calls", []) or []),
            "tool_results": list(getattr(step, "tool_results", []) or []),
            "stop_reason": getattr(step, "stop_reason", None),
        }

    def _visible_agentic_final_event(
        self,
        event: dict[str, Any],
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None,
        response_language: str | None,
        answer_mode: str | None,
        coach_context: dict[str, Any] | None,
        tool_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        final_event = dict(event)
        content = self._sanitize_agentic_visible_reply(
            str(final_event.get("content") or ""),
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            tool_events=tool_events,
        )
        final_event["content"] = content
        if str(final_event.get("summary") or "").strip():
            final_event["summary"] = _strip_internal_coach_meta(str(final_event.get("summary") or ""))
        if str(final_event.get("next_step") or "").strip():
            final_event["next_step"] = _strip_internal_coach_meta(str(final_event.get("next_step") or ""))
        if str(final_event.get("resume_thread") or "").strip():
            final_event["resume_thread"] = _visible_model_text(
                str(final_event.get("resume_thread") or "")
            )
        reply_corruption_detail = _mixed_script_reply_corruption_detail(
            content,
            message=message,
            response_language=response_language,
        )
        if reply_corruption_detail:
            self._record_reply_language_corruption(reply_corruption_detail)
            recovery_override = _build_language_corruption_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(recovery_override, dict):
                summary = str(recovery_override.get("summary") or "").strip() or (
                    self.provider_failure_summary("language_corruption", response_language)
                )
                next_step = str(recovery_override.get("next_step") or "").strip() or (
                    self.provider_failure_next_step("language_corruption", response_language)
                )
                final_event.update(
                    {
                        "content": str(recovery_override.get("reply") or "").strip()
                        or self.provider_failure_reply(
                            "language_corruption",
                            reply_corruption_detail,
                            response_language,
                        ),
                        "summary": summary,
                        "next_step": next_step,
                        "stop_reason": "language_corruption_recovered",
                        "teaching_note": str(recovery_override.get("teaching_note") or "").strip(),
                        "blocker": reply_corruption_detail,
                        "resume_thread": str(recovery_override.get("resume_thread") or "").strip()
                        or _agentic_resume_thread_text(
                            summary,
                            next_step,
                            response_language=response_language,
                        ),
                        "fell_back": True,
                    }
                )
            else:
                summary = self.provider_failure_summary("language_corruption", response_language)
                next_step = self.provider_failure_next_step("language_corruption", response_language)
                final_event.update(
                    {
                        "content": self.provider_failure_reply(
                            "language_corruption",
                            reply_corruption_detail,
                            response_language,
                        ),
                        "summary": summary,
                        "next_step": next_step,
                        "stop_reason": "language_corruption",
                        "resume_thread": _agentic_resume_thread_text(
                            summary,
                            next_step,
                            response_language=response_language,
                        ),
                    }
                )
            return final_event
        guard = _agentic_practice_completion_guard(
            content=content,
            tool_events=tool_events or [],
            message=message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if guard is not None:
            final_event.update(guard)
            resume_thread = _agentic_resume_thread_text(
                final_event.get("summary"),
                final_event.get("next_step"),
                response_language=response_language,
            )
            if resume_thread:
                final_event["resume_thread"] = resume_thread
            return final_event

        summary, next_step = _agentic_completion_continuity(
            message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
            content=content,
        )
        if not str(final_event.get("summary") or "").strip():
            final_event["summary"] = _strip_internal_coach_meta(summary)
        if not str(final_event.get("next_step") or "").strip():
            final_event["next_step"] = _strip_internal_coach_meta(next_step)
        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario") or "").strip()
        history_mode = str(context.get("history_mode") or "").strip().lower()
        chinese = _prefers_chinese(response_language)
        summary_before_visible = str(final_event.get("summary") or "").strip()
        next_step_before_visible = str(final_event.get("next_step") or "").strip()
        if str(final_event.get("summary") or "").strip():
            final_event["summary"] = _sanitize_agentic_continuity_text(
                str(final_event.get("summary") or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="summary",
                response_language=response_language,
                coach_context=context,
                current_file=current_file,
            )
        if str(final_event.get("next_step") or "").strip():
            final_event["next_step"] = _sanitize_agentic_continuity_text(
                str(final_event.get("next_step") or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="next_step",
                response_language=response_language,
                coach_context=context,
                current_file=current_file,
            )
        summary_changed_for_visible = (
            str(final_event.get("summary") or "").strip() != summary_before_visible
        )
        next_step_changed_for_visible = (
            str(final_event.get("next_step") or "").strip() != next_step_before_visible
        )
        if (
            not str(final_event.get("resume_thread") or "").strip()
            or summary_changed_for_visible
            or next_step_changed_for_visible
        ):
            final_event["resume_thread"] = _agentic_resume_thread_text(
                final_event.get("summary"),
                final_event.get("next_step"),
                response_language=response_language,
            )
        if str(final_event.get("resume_thread") or "").strip():
            sanitized_resume_thread = _sanitize_agentic_continuity_text(
                str(final_event.get("resume_thread") or ""),
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
                history_mode=history_mode,
                field_kind="resume_thread",
                response_language=response_language,
                coach_context=context,
                current_file=current_file,
            )
            if summary_changed_for_visible or next_step_changed_for_visible:
                final_event["resume_thread"] = _normalize_visible_resume_thread_text(
                    sanitized_resume_thread,
                    chinese=chinese,
                )
            else:
                final_event["resume_thread"] = sanitized_resume_thread

        if content.strip():
            return final_event

        summary_text = str(final_event.get("summary") or "").strip()
        if summary_text:
            final_event["content"] = summary_text
            return final_event

        final_event["content"] = self._scaffold_reply(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        return final_event
