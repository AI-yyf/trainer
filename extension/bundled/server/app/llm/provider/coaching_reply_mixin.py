from __future__ import annotations

import asyncio
import sys as _sys
from typing import TYPE_CHECKING, Any

import httpx as _real_httpx

from ...core.models import (
    ProviderConfig,
    UserProfile,
)
from ..coaching_first_turn import (
    _compact_first_turn_reply,
    _first_turn_concrete_followthrough,
    _first_turn_guided_lane,
    _first_turn_lane_continuity_note,
    _first_turn_lane_next_step,
    _fresh_lane_comparison_requested,
    _resolve_first_turn_guided_lane,
    _should_offer_generic_first_turn_lane_prompt,
)
from ..coaching_patches import (
    _build_empty_reply_override,
    _compose_principle_followthrough_patch,
    _compose_scaffold_paragraphs,
    _scaffold_next_step,
    _structured_view_visible_reply_needs_repair,
)
from ..coaching_recovery import (
    _GUIDED_DOMAIN_SCENARIOS,
    _build_active_view_recovery_override,
    _build_language_corruption_recovery_override,
    _coaching_active_view_name,
    _localized_text,
    _prefers_chinese,
    _trim_sentence,
)
from ..coaching_replies import (
    _extract_next_step_hint_text,
    _fresh_lane_marker_map,
    _prefer_structured_next_step,
    _reply_has_guided_lane_signal,
    _stream_holdback_chars,
    _strip_fresh_lane_cross_lane_carryover,
    _strip_internal_coach_meta,
    preserve_streamed_reply_prefix,
)
from ..coaching_reply_drafts import (
    _append_unique_paragraphs,
    _compose_recalled_memory_patch,
    _compose_review_tightening_patch,
    _compose_success_signal_patch,
    _fresh_lane_reanchor_reply,
    _guided_domain_empty_reply,
    _reanchor_visible_reply_to_current_request,
    _reply_needs_first_turn_reframe,
    _scaffold_close,
    _should_preserve_visible_reply,
    _strip_generic_lane_prompt_artifacts,
)
from ..coaching_scaffold import (
    _scaffold_anchor,
    _scaffold_diagnosis,
    _scaffold_teaching_note,
)
from ..library_practice import (
    build_library_practice,
    library_practice_requested,
    remove_model_practice,
)
from ..prompts import (
    build_coaching_messages as _real_build_coaching_messages,
)
from ..prompts import (
    extract_coaching_context,
    infer_learner_signal,
    normalize_answer_policy,
)
from ..provider_protocols import (
    normalize_provider_response,
)
from ..vision_challenge import build_vision_challenge as _real_build_vision_challenge
from .assessment import (
    _as_mapping,
)
from .context_budget import (
    DEFAULT_COACHING_MAX_OUTPUT_TOKENS,
)
from .context_budget import (
    MIN_CONTEXT_OUTPUT_TOKENS as MIN_CONTEXT_OUTPUT_TOKENS,
)
from .errors import (
    ContextBudgetExhaustedError,
    ProviderRuntimeResponseError,
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
    _looks_like_provider_html_shell,
    _malformed_provider_html_shell_detail,
    _require_provider_runtime_response,
    _strip_leading_html_shell_artifact,
    logger,
)
from .service_support import (
    has_successful_agent_tool_result as _has_successful_agent_tool_result,
)
from .streaming import (
    _await_provider_stream_with_cancellation,
    _iterate_provider_stream_with_cancellation,
    _stream_cancel_event,
    extract_non_sse_json_stream_payload,
)
from .text import (
    ReasoningBlockFilter,
    _contains_cjk,
    _mixed_script_reply_corruption_detail,
    _strip_short_cyrillic_noise,
    _wrong_language_cjk_reply_detail,
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


class CoachingReplyMixin:
    if TYPE_CHECKING:
        _agent_context_budget_states: Any
        _api_key: Any
        _classify_error: Any
        _coaching_requested_output_tokens: Any
        _completion_stream_via_agent_binding: Any
        _completion_via_agent_binding: Any
        _config: Any
        _context_budget_status_reply: Any
        _create_chat_completion: Any
        _detail_from_category: Any
        _effective_output_token_budget: Any
        _escalated_chat_budget: Any
        _get_client: Any
        _plain_completion_uses_agent_binding: Any
        _prepare_context_budget: Any
        _record_last_reply_failure: Any
        _record_last_reply_override: Any
        _record_reply_language_corruption: Any
        _resolve_model: Any
        _smart_coaching_history_budget: Any
        clear_language_integrity_success: Any
        clear_last_reply_state: Any
        has_usable_credential: Any
        mark_language_integrity_success: Any
        peek_last_reply_failure: Any
        provider_failure_reply: Any
        recommended_generation_max_tokens: Any
        reset_transport_client: Any

    async def coaching_reply(
        self,
        profile: UserProfile | None,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        self.clear_last_reply_state()
        if not self.has_usable_credential():
            if not profile:
                return self._missing_api_key_reply(response_language)
            return self._missing_api_key_reply_with_scaffold(
                profile,
                message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
        if not profile:
            return self._onboarding_reply(response_language)
        return await self._llm_reply(
            profile,
            message,
            current_file,
            response_language,
            answer_mode,
            coach_context=coach_context,
            history=history,
        )

    async def _llm_reply(
        self,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        history_limit, history_token_budget = self._smart_coaching_history_budget()
        messages = build_coaching_messages(
            profile,
            message,
            current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            history=history,
            history_limit=history_limit,
            history_token_budget=history_token_budget,
        )
        model = self._resolve_model()
        try:
            messages, max_tokens = self._prepare_context_budget(
                messages,
                model=model,
                requested_max_tokens=self._coaching_requested_output_tokens(message, coach_context),
                prefer_configured_output=True,
            )
            if self._plain_completion_uses_agent_binding():
                content = await self._completion_via_agent_binding(
                    messages,
                    temperature=0.7,
                    max_tokens=max_tokens,
                    prefer_configured_output=True,
                    allow_local_empty_fallback=True,
                )
                return self.finalize_coaching_reply(
                    content or "",
                    profile=profile,
                    message=message,
                    current_file=current_file,
                    response_language=response_language,
                    answer_mode=answer_mode,
                    coach_context=coach_context,
                )
            client = self._get_client()
            response, _ = await self._create_chat_completion(
                client=client,
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=max_tokens,
            )
            try:
                content = _require_provider_runtime_response(
                    "openai_chat_completions",
                    response,
                    api_key=self._api_key,
                    allow_local_empty_fallback=True,
                )
            except ProviderRuntimeResponseError as exc:
                # Reasoning-first models can exhaust the coaching budget on
                # hidden reasoning (truncated_or_empty). Escalate once before
                # falling back; nothing visible was produced yet.
                if getattr(exc, "provider_error_category", None) != "truncated_or_empty":
                    raise
                escalated = self._escalated_chat_budget(max_tokens)
                if escalated is None:
                    raise
                logger.warning(
                    "[provider] coaching reply truncated; retrying once with max_tokens=%s",
                    escalated,
                )
                response, _ = await self._create_chat_completion(
                    client=client,
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=escalated,
                )
                content = _require_provider_runtime_response(
                    "openai_chat_completions",
                    response,
                    api_key=self._api_key,
                    allow_local_empty_fallback=True,
                )
            return self.finalize_coaching_reply(
                content or "",
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
        except ContextBudgetExhaustedError:
            self._record_last_reply_override(
                stop_reason="context_budget_exhausted",
                fell_back=False,
                context_budget_exhausted=True,
            )
            return self._context_budget_status_reply(response_language)
        except Exception as exc:
            category, retryable, status_code, provider_reachable, model_supported = self._classify_error(exc)
            provider_config = self._config or ProviderConfig(
                name="unspecified-provider",
                baseUrl="",
                apiKeyRef="trainer.unspecified",
                model=self._resolve_model(),
            )
            detail = self._detail_from_category(
                category,
                provider=provider_config,
                error=exc,
            )
            self._record_last_reply_failure(
                category=category,
                detail=detail,
                retryable=retryable,
                status_code=status_code,
                provider_reachable=provider_reachable,
                model_supported=model_supported,
                error=exc,
            )
            return self._error_reply_with_scaffold(
                exc=exc,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )

    def finalize_coaching_reply(
        self,
        content: str,
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        grounded_completion: bool = False,
    ) -> str:
        visible_content = _strip_internal_coach_meta(content)
        visible_content = _strip_leading_html_shell_artifact(visible_content)
        if not visible_content.strip():
            if _looks_like_provider_html_shell(content):
                detail = _malformed_provider_html_shell_detail()
                self._record_last_reply_failure(
                    category="malformed_response",
                    detail=detail,
                    retryable=False,
                    status_code=200,
                    provider_reachable=True,
                    model_supported=None,
                    error=ValueError(detail),
                )
                return self.provider_failure_reply(
                    "malformed_response",
                    detail,
                    response_language,
                )
            return self._fallback_empty_reply(
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
        reply = self._postprocess_coaching_reply(
            visible_content,
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
            grounded_completion=grounded_completion,
        )
        if coach_context is not None and library_practice_requested(message, coach_context):
            practice = build_library_practice(coach_context, response_language)
            if practice and self.peek_last_reply_failure() is None:
                analysis = remove_model_practice(reply)
                return "\n\n".join(part for part in (analysis, practice) if part)
        if _should_preserve_visible_reply(
            message,
            answer_mode=answer_mode,
            profile=profile,
        ):
            return _reanchor_visible_reply_to_current_request(
                reply,
                message=message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
                grounded_completion=grounded_completion,
            )
        context = extract_coaching_context(message, current_file, coach_context)
        is_non_execution_intake = (
            str(context.get("relationship_stage") or "").strip().lower() == "intake"
            and not bool(context.get("execution_ready"))
        )
        if not is_non_execution_intake or not _reply_needs_first_turn_reframe(visible_content):
            return _reanchor_visible_reply_to_current_request(
                reply,
                message=message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
                grounded_completion=grounded_completion,
            )
        reframed_reply = self._postprocess_first_turn_reply(
            reply,
            response_language=response_language,
            learner_message=message,
            scenario=str(context.get("scenario") or "").strip() or None,
            coach_context=context,
        )
        return _reanchor_visible_reply_to_current_request(
            reframed_reply,
            message=message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
            grounded_completion=grounded_completion,
        )

    def _postprocess_coaching_reply(
        self,
        content: str,
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        grounded_completion: bool = False,
    ) -> str:
        reply = content.strip()
        if not reply:
            return self._fallback_empty_reply(
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )

        raw_reply_corruption_detail = _mixed_script_reply_corruption_detail(
            reply,
            message=message,
            response_language=response_language,
        )
        if raw_reply_corruption_detail:
            self.clear_language_integrity_success(
                message=message,
                response_language=response_language,
            )
            self._record_reply_language_corruption(raw_reply_corruption_detail)
            recovery_override = _build_language_corruption_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(recovery_override, dict):
                reply_override = str(recovery_override.get("reply") or "").strip()
                if reply_override:
                    return reply_override
            return self.provider_failure_reply(
                "language_corruption",
                raw_reply_corruption_detail,
                response_language,
            )

        reply = _strip_short_cyrillic_noise(reply, message=message)
        reply_corruption_detail = _mixed_script_reply_corruption_detail(
            reply,
            message=message,
            response_language=response_language,
        )
        if reply_corruption_detail:
            self.clear_language_integrity_success(
                message=message,
                response_language=response_language,
            )
            self._record_reply_language_corruption(reply_corruption_detail)
            recovery_override = _build_language_corruption_recovery_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
            if isinstance(recovery_override, dict):
                reply_override = str(recovery_override.get("reply") or "").strip()
                if reply_override:
                    return reply_override
            return self.provider_failure_reply(
                "language_corruption",
                reply_corruption_detail,
                response_language,
            )
        if _prefers_chinese(response_language):
            if _contains_cjk(reply):
                self.mark_language_integrity_success(
                    message=message,
                    response_language=response_language,
                )
        elif reply.strip() and not _wrong_language_cjk_reply_detail(
            reply,
            message=message,
            response_language=response_language,
        ):
            self.mark_language_integrity_success(
                message=message,
                response_language=response_language,
            )

        if _should_preserve_visible_reply(
            message,
            answer_mode=answer_mode,
            profile=profile,
        ):
            return _reanchor_visible_reply_to_current_request(
                reply,
                message=message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
                grounded_completion=grounded_completion,
            )

        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario") or "idea_implementation").strip()
        resolved_visible_scenario = _resolve_first_turn_guided_lane(
            scenario=scenario,
            learner_message=message,
            reply=reply,
        )
        if resolved_visible_scenario in _GUIDED_DOMAIN_SCENARIOS:
            scenario = resolved_visible_scenario
        history_mode = str(context.get("history_mode") or "").strip().lower()
        chinese = _prefers_chinese(response_language)
        learner_signal = str(
            context.get("learner_signal") or infer_learner_signal(message, current_file)
        ).strip()
        reply = _strip_generic_lane_prompt_artifacts(
            reply,
            scenario=scenario,
            learner_message=message,
            chinese=chinese,
        )
        should_strip_cross_lane = history_mode == "fresh_lane" or (
            scenario in _GUIDED_DOMAIN_SCENARIOS
            and not _fresh_lane_comparison_requested(message)
        )
        if should_strip_cross_lane and not grounded_completion:
            reply = _strip_fresh_lane_cross_lane_carryover(
                reply,
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
            )
            if (
                scenario in _GUIDED_DOMAIN_SCENARIOS
                and not _fresh_lane_comparison_requested(message)
                and not grounded_completion
                and _reply_mentions_other_guided_lane(
                reply,
                scenario=scenario,
                chinese=chinese,
                )
            ):
                repaired_reply = _fresh_lane_reanchor_reply(
                    scenario,
                    response_language=response_language,
                    coach_context=context,
                )
                if repaired_reply.strip():
                    reply = repaired_reply
        active_view = _coaching_active_view_name(context)
        active_view_override = (
            _build_active_view_recovery_override(
                active_view=active_view,
                response_language=response_language,
                reason="reanchor",
            )
            if active_view
            else None
        )
        if (
            isinstance(active_view_override, dict)
            and _structured_view_visible_reply_needs_repair(
                reply,
                active_view=active_view,
                chinese=chinese,
                learner_message=message,
                current_file=current_file,
            )
        ):
            repaired_reply = str(active_view_override.get("reply") or "").strip()
            if repaired_reply:
                return _reanchor_visible_reply_to_current_request(
                    repaired_reply,
                    message=message,
                    current_file=current_file,
                    coach_context=coach_context,
                    response_language=response_language,
                    grounded_completion=grounded_completion,
                    )
        pace_signal = str(context.get("pace_signal") or "").strip()

        implementation_guide = (
            context.get("implementation_guide") if isinstance(context.get("implementation_guide"), dict) else {}
        )
        adaptation_guide = (
            context.get("project_adaptation_guide")
            if isinstance(context.get("project_adaptation_guide"), dict)
            else context.get("adaptation_guide")
            if isinstance(context.get("adaptation_guide"), dict)
            else {}
        )
        principle_note = (
            context.get("principle_notes")
            if isinstance(context.get("principle_notes"), dict)
            else context.get("principle_note")
            if isinstance(context.get("principle_note"), dict)
            else {}
        )
        project_ideas = (
            [item for item in context.get("project_ideas", []) if isinstance(item, dict)]
            if isinstance(context.get("project_ideas"), list)
            else []
        )
        exercise_prompt = context.get("exercise_prompt") if isinstance(context.get("exercise_prompt"), dict) else {}
        failing_checks = [
            str(item).strip() for item in context.get("failing_checks", []) if str(item).strip()
        ] if isinstance(context.get("failing_checks"), list) else []
        project_entry_points = [
            str(item).strip() for item in context.get("project_entry_points", []) if str(item).strip()
        ] if isinstance(context.get("project_entry_points"), list) else []
        learning_outcomes = [
            item for item in context.get("learning_outcomes", []) if isinstance(item, dict)
        ] if isinstance(context.get("learning_outcomes"), list) else []
        recalled_coaching_memories = [
            item for item in context.get("recalled_coaching_memories", []) if isinstance(item, dict)
        ] if isinstance(context.get("recalled_coaching_memories"), list) else []

        has_structured_context = any(
            (
                current_file,
                implementation_guide,
                adaptation_guide,
                principle_note,
                project_ideas,
                exercise_prompt,
                failing_checks,
                project_entry_points,
                learning_outcomes,
                recalled_coaching_memories,
                pace_signal,
            )
        )
        if not has_structured_context:
            return reply

        additions: list[str] = []

        principle_patch = _compose_principle_followthrough_patch(
            reply=reply,
            principle_note=principle_note,
            chinese=chinese,
        )
        if principle_patch:
            additions.append(principle_patch)

        guided_lane_patch = _compose_guided_lane_continuity_patch(
            reply=reply,
            scenario=scenario,
            chinese=chinese,
        )
        if guided_lane_patch:
            additions.append(guided_lane_patch)

        # The next step no longer appends to the body: it reaches the learner
        # through the reply's icon strip (coach_turn.next_step / next_step_hint
        # metadata), so the text ends with the coach's own words.

        review_patch = _compose_review_tightening_patch(
            reply=reply,
            scenario=scenario,
            failing_checks=failing_checks,
            learning_outcomes=learning_outcomes,
            pace_signal=pace_signal,
            learner_signal=learner_signal,
            chinese=chinese,
        )
        if review_patch:
            additions.append(review_patch)

        success_signal_patch = _compose_success_signal_patch(
            reply=reply,
            exercise_prompt=exercise_prompt,
            chinese=chinese,
        )
        if success_signal_patch:
            additions.append(success_signal_patch)

        recalled_memory_patch = _compose_recalled_memory_patch(
            reply=reply,
            recalled_coaching_memories=recalled_coaching_memories,
            chinese=chinese,
        )
        if recalled_memory_patch:
            additions.append(recalled_memory_patch)

        if not additions:
            return reply
        return _append_unique_paragraphs(reply, additions[:3])

    def _sanitize_agentic_visible_reply(
        self,
        content: str,
        *,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
        tool_events: list[dict[str, Any]] | None = None,
    ) -> str:
        grounded_completion = _has_successful_agent_tool_result(tool_events)
        reply = _strip_internal_coach_meta(content).strip()
        if not reply:
            return reply

        if _mixed_script_reply_corruption_detail(
            reply,
            message=message,
            response_language=response_language,
        ):
            return reply

        reply = _strip_short_cyrillic_noise(reply, message=message)
        if _mixed_script_reply_corruption_detail(
            reply,
            message=message,
            response_language=response_language,
        ):
            return reply

        if _should_preserve_visible_reply(
            message,
            answer_mode=answer_mode,
            profile=profile,
        ):
            return _reanchor_visible_reply_to_current_request(
                reply,
                message=message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
                grounded_completion=grounded_completion,
            )

        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario") or "idea_implementation").strip()
        resolved_visible_scenario = _resolve_first_turn_guided_lane(
            scenario=scenario,
            learner_message=message,
            reply=reply,
        )
        if resolved_visible_scenario in _GUIDED_DOMAIN_SCENARIOS:
            scenario = resolved_visible_scenario
        history_mode = str(context.get("history_mode") or "").strip().lower()
        chinese = _prefers_chinese(response_language)
        reply = _strip_generic_lane_prompt_artifacts(
            reply,
            scenario=scenario,
            learner_message=message,
            chinese=chinese,
        )
        should_strip_cross_lane = history_mode == "fresh_lane" or (
            scenario in _GUIDED_DOMAIN_SCENARIOS
            and not _fresh_lane_comparison_requested(message)
        )
        if should_strip_cross_lane and not grounded_completion:
            reply = _strip_fresh_lane_cross_lane_carryover(
                reply,
                scenario=scenario,
                learner_message=message,
                chinese=chinese,
            )
            if (
                scenario in _GUIDED_DOMAIN_SCENARIOS
                and not _fresh_lane_comparison_requested(message)
                and not grounded_completion
                and _reply_mentions_other_guided_lane(
                reply,
                scenario=scenario,
                chinese=chinese,
                )
            ):
                repaired_reply = _fresh_lane_reanchor_reply(
                    scenario,
                    response_language=response_language,
                    coach_context=context,
                )
                if repaired_reply.strip():
                    reply = repaired_reply
        active_view = _coaching_active_view_name(context)
        active_view_override = (
            _build_active_view_recovery_override(
                active_view=active_view,
                response_language=response_language,
                reason="reanchor",
            )
            if active_view
            else None
        )
        if (
            isinstance(active_view_override, dict)
            and _structured_view_visible_reply_needs_repair(
                reply,
                active_view=active_view,
                chinese=chinese,
                learner_message=message,
                current_file=current_file,
            )
        ):
            repaired_reply = str(active_view_override.get("reply") or "").strip()
            if repaired_reply:
                return _reanchor_visible_reply_to_current_request(
                    repaired_reply,
                    message=message,
                    current_file=current_file,
                    coach_context=coach_context,
                    response_language=response_language,
                    grounded_completion=grounded_completion,
                )
        return _reanchor_visible_reply_to_current_request(
            reply,
            message=message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
            grounded_completion=grounded_completion,
        )

    def _postprocess_first_turn_reply(
        self,
        reply: str,
        *,
        response_language: str | None = None,
        learner_message: str,
        scenario: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        chinese = _prefers_chinese(response_language)
        is_non_execution_intake = (
            isinstance(coach_context, dict)
            and str(coach_context.get("relationship_stage") or "").strip().lower() == "intake"
            and not bool(coach_context.get("execution_ready"))
        )
        condensed = ""
        if not (is_non_execution_intake and _reply_needs_first_turn_reframe(reply)):
            condensed = _compact_first_turn_reply(
                reply,
                chinese=chinese,
                scenario=scenario,
                learner_message=learner_message,
                coach_context=coach_context,
            )
        if condensed:
            return condensed

        learner_excerpt = learner_message.strip()
        guided_lane = _resolve_first_turn_guided_lane(
            scenario=scenario,
            learner_message=learner_message,
            reply=reply,
        )
        guided_note = _first_turn_lane_continuity_note(
            guided_lane,
            chinese=chinese,
            coach_context=coach_context,
        )
        guided_close = _first_turn_lane_next_step(
            guided_lane,
            chinese=chinese,
            coach_context=coach_context,
        )
        if guided_note and guided_close:
            if chinese:
                lead = "\u5148\u522b\u76f4\u63a5\u7ed9\u7b54\u6848\u3002\u5148\u5b9a\u4f4f\u8fd9\u4e00\u8f6e\u7684\u8d77\u6b65\u52a8\u4f5c\uff0c\u518d\u7ee7\u7eed\u3002"
                if learner_excerpt:
                    lead += f" \u4f60\u521a\u521a\u5e26\u6765\u7684\u91cd\u70b9\u662f\uff1a{_trim_sentence(learner_excerpt, 72)}\u3002"
                return f"{lead}\n\n{guided_note}\n\n{guided_close}"

            lead = (
                "I do not want to jump straight into a solution yet. "
                "First I want to anchor this round in one trustworthy starting move and keep the thread continuous."
            )
            if learner_excerpt:
                lead += f" What you just brought in is: {_trim_sentence(learner_excerpt, 72)}."
            return f"{lead}\n\n{guided_note}\n\n{guided_close}"
        if not _should_offer_generic_first_turn_lane_prompt(
            scenario=scenario,
            learner_message=learner_message,
            reply=reply,
        ):
            lead = "I do not want to jump straight into a solution yet. First I want to stay on the concrete task you already named."
            if chinese:
                lead = "\u5148\u522b\u76f4\u63a5\u7ed9\u7b54\u6848\u3002\u5148\u6cbf\u7740\u4f60\u521a\u624d\u5df2\u7ecf\u8bf4\u6e05\u695a\u7684\u5177\u4f53\u4efb\u52a1\u7ee7\u7eed\u5f80\u524d\u3002"
            if learner_excerpt:
                lead += (
                    f" \u4f60\u521a\u521a\u5e26\u6765\u7684\u91cd\u70b9\u662f\uff1a{_trim_sentence(learner_excerpt, 72)}\u3002"
                    if chinese
                    else f" What you just brought in is: {_trim_sentence(learner_excerpt, 72)}."
                )
            return f"{lead}\n\n{_first_turn_concrete_followthrough(chinese=chinese)}"
        if chinese:
            lead = "\u5148\u522b\u76f4\u63a5\u7ed9\u7b54\u6848\u3002\u5148\u5bf9\u9f50\u8fd9\u4e00\u8f6e\uff0c\u518d\u9009\u5408\u9002\u7684\u5f15\u5bfc\u65b9\u5f0f\u3002"
            if learner_excerpt:
                lead += f" \u4f60\u521a\u521a\u5e26\u6765\u7684\u91cd\u70b9\u662f\uff1a{_trim_sentence(learner_excerpt, 72)}\u3002"
            return (
                f"{lead}\n\n"
                "\u7b2c\u4e00\u8f6e\u901a\u5e38\u4f1a\u5148\u843d\u5230\u4e09\u6761\u8def\u5f84\u4e4b\u4e00\uff1a\u5b9e\u73b0\u4e00\u4e2a idea\u3001\u6539\u9020\u73b0\u6709\u9879\u76ee\uff0c\u6216\u5148\u5b9a\u8bad\u7ec3\u4e3b\u7ebf\u3002\n\n\u544a\u8bc9\u6211\u73b0\u5728\u66f4\u63a5\u8fd1\u54ea\u4e00\u6761\u3002"
            )

        lead = "I do not want to jump straight into a solution yet. First I want to align on this round and choose the right way to guide you."
        if learner_excerpt:
            lead += f" What you just brought in is: {_trim_sentence(learner_excerpt, 72)}."
        return (
            f"{lead}\n\n"
            "I usually sort the first turn into one of three lanes: turning an idea into code, guiding changes inside an existing project, or shaping the longer training thread and rhythm first. I will also remember the goal, project context, and coaching preference we make clear here so the next turn can continue the same thread.\n\n"
            "Tell me which lane is closest right now: implementing an idea, adapting an existing project, or shaping the training thread first."
        )

    def _scaffold_reply(
        self,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        chinese = _prefers_chinese(response_language)
        mode = normalize_answer_policy(answer_mode or profile.answer_policy)
        context = extract_coaching_context(message, current_file, coach_context)
        scenario = str(context.get("scenario", "idea_implementation"))
        learner_signal = str(context.get("learner_signal", infer_learner_signal(message, current_file)))
        file_path = context.get("file_path")
        diagnostics_count = int(context.get("diagnostics_count", 0) or 0)
        current_focus = str(context.get("current_focus") or "").strip()
        recent_wins = [str(item) for item in context.get("recent_wins", []) if str(item).strip()]
        weak_spots = [str(item) for item in context.get("weak_spots", []) if str(item).strip()]
        due_reviews = context.get("due_reviews", [])
        review_rhythm = str(context.get("review_rhythm") or "").strip()
        teaching_observations = [
            str(item) for item in context.get("teaching_observations", []) if str(item).strip()
        ]
        coach_defaults = _as_mapping(context.get("coach_defaults")) or {}
        summary = str(context.get("thread_summary") or context.get("summary") or "").strip()
        next_step_hint = _extract_next_step_hint_text(
            context.get("thread_next_step") or context.get("resume_hint") or context.get("next_step_hint")
        )
        teaching_decision = _as_mapping(context.get("teaching_decision")) or {}
        tone_decision = _as_mapping(context.get("tone_decision")) or {}
        implementation_guide = (
            context.get("implementation_guide") if isinstance(context.get("implementation_guide"), dict) else {}
        )
        adaptation_guide = (
            context.get("project_adaptation_guide")
            if isinstance(context.get("project_adaptation_guide"), dict)
            else context.get("adaptation_guide")
            if isinstance(context.get("adaptation_guide"), dict)
            else {}
        )
        principle_note = (
            context.get("principle_notes")
            if isinstance(context.get("principle_notes"), dict)
            else context.get("principle_note")
            if isinstance(context.get("principle_note"), dict)
            else {}
        )
        project_ideas = [
            item for item in context.get("project_ideas", []) if isinstance(item, dict)
        ] if isinstance(context.get("project_ideas"), list) else []
        exercise_prompt = (
            context.get("exercise_prompt") if isinstance(context.get("exercise_prompt"), dict) else {}
        )
        verbosity_bias = str(tone_decision.get("verbosity_bias") or "medium").strip()
        tone_name = str(tone_decision.get("tone") or "").strip()

        goal_line = profile.long_term_goal or (profile.long_term_goals[0] if profile.long_term_goals else "")
        anchor = _scaffold_anchor(
            scenario=scenario,
            goal=goal_line,
            file_path=str(file_path) if file_path else None,
            current_focus=current_focus,
            chinese=chinese,
        )
        diagnosis = _scaffold_diagnosis(
            scenario=scenario,
            learner_signal=learner_signal,
            diagnostics_count=diagnostics_count,
            weak_spots=weak_spots,
            teaching_observations=teaching_observations,
            summary=summary,
            teaching_decision_reason=str(teaching_decision.get("reason") or "").strip(),
            chinese=chinese,
        )
        next_step = _scaffold_next_step(
            scenario=scenario,
            mode=mode,
            learner_signal=learner_signal,
            file_path=str(file_path) if file_path else None,
            weak_spots=weak_spots,
            next_step_hint=_prefer_structured_next_step(
                scenario=scenario,
                next_step_hint=next_step_hint,
                implementation_guide=implementation_guide,
                adaptation_guide=adaptation_guide,
                principle_note=principle_note,
                project_ideas=project_ideas,
                exercise_prompt=exercise_prompt,
            ),
            chinese=chinese,
        )
        teaching_note = _scaffold_teaching_note(
            scenario=scenario,
            mode=mode,
            recent_wins=recent_wins,
            weak_spots=weak_spots,
            due_reviews=due_reviews,
            review_rhythm=review_rhythm,
            coach_defaults=coach_defaults,
            tone_name=tone_name,
            verbosity_bias=verbosity_bias,
            chinese=chinese,
        )
        close = _scaffold_close(
            learner_signal=learner_signal,
            mode=mode,
            verbosity_bias=verbosity_bias,
            chinese=chinese,
        )

        paragraphs = _compose_scaffold_paragraphs(
            scenario=scenario,
            mode=mode,
            learner_signal=learner_signal,
            anchor=anchor,
            diagnosis=diagnosis,
            next_step=next_step,
            teaching_note=teaching_note,
            close=close,
            chinese=chinese,
        )
        resolved = [part for part in paragraphs if part.strip()]
        if verbosity_bias == "short":
            resolved = resolved[:3]
        return "\n\n".join(resolved)

    def _onboarding_reply(self, response_language: str | None = None) -> str:
        if _prefers_chinese(response_language):
            return (
                "先别急着直接上方案。先把你的目标、项目语境和当前卡点对齐。"
                "\n\n"
                "先告诉我最重要的几件事：你想达到的目标、手上的项目、当前水平、希望我怎样带你，以及最想推进或卡住的地方。"
                "\n\n"
                "我会记住这些判断，再决定这更适合从想法实现、已有项目改造、原理解释，还是一条可持续的训练主线开始。"
                "\n\n"
                "你现在更需要我带你做哪一类：实现一个想法、改造一个项目，还是先搭建训练主线？"
            )
        return (
            "Let's not jump straight into a solution yet. First I want to align on your goal, project context, and the coaching lane that fits you best."
            "\n\n"
            "Start with the few things that matter most right now: your goal, the project in front of you, your current level, "
            "how you prefer to be coached, and the point you most want to move forward or feel stuck on."
            "\n\n"
            "Then I can decide whether this should become an idea implementation discussion, an existing-project adaptation lane shaped around your intent, "
            "a principle explanation, or a training plan we shape together and keep over time."
            "\n\n"
            "If you want to keep it simple, answer just one thing first: do you mainly want to implement an idea, adapt a project, or shape the training thread?"
        )

    def _error_reply(self, exc: Exception, response_language: str | None = None) -> str:
        if _prefers_chinese(response_language):
            return (
                "这次连接教练服务时遇到了一点问题。请检查模型连接后再试。"
                "\n\n"
                "在恢复前，先把目标行为说清楚，找出当前最不确定的一点，再做一个能快速验证的小改动。"
            )
        return (
            "I hit an issue connecting to the coaching service. Please check your provider configuration and try again. "
            "While that is blocked, keep moving: restate the target behavior, identify the single highest-uncertainty point, "
            "and implement the smallest change you can verify quickly. "
            f"Error: {redact_provider_error(exc, api_key=self._api_key)}"
        )

    def _error_reply_with_scaffold(
        self,
        *,
        exc: Exception,
        profile: UserProfile,
        message: str,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        error_line = self._error_reply(exc, response_language=response_language).strip()
        scaffold = self._scaffold_reply(
            profile,
            message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        ).strip()
        if not scaffold:
            return error_line
        return f"{error_line}\n\n{scaffold}"

    def _missing_api_key_reply(self, response_language: str | None = None) -> str:
        if _prefers_chinese(response_language):
            return "还没有设置可用的 API 密钥。请到设置里填写模型服务和密钥，然后就可以开始对话。"
        return "Trainer cannot start working yet because there is no usable API key. Save a large-model provider and API key in Settings, then I can properly start coaching."

    def _missing_api_key_reply_with_scaffold(
        self,
        profile: UserProfile,
        message: str,
        *,
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        missing_key_line = self._missing_api_key_reply(response_language=response_language).strip()
        scaffold = self._scaffold_reply(
            profile,
            message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        ).strip()
        if not scaffold:
            return missing_key_line
        return f"{missing_key_line}\n\n{scaffold}"

    def _fallback_empty_reply(
        self,
        *,
        profile: UserProfile | None = None,
        message: str = "",
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        self._record_last_reply_override(
            **_build_empty_reply_override(
                message,
                current_file=current_file,
                coach_context=coach_context,
                response_language=response_language,
            )
        )
        return self._visible_empty_reply_guidance(
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        lead = _localized_text(
            "The provider finished this turn without any visible coaching reply, so I am keeping the same learning lane moving locally.",
            "",
            response_language,
        )
        guided_lane_reply = _guided_domain_empty_reply(
            message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if guided_lane_reply:
            return f"{lead}\n\n{guided_lane_reply}"

        if profile is not None:
            scaffold = self._scaffold_reply(
                profile,
                message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            ).strip()
            if scaffold:
                return f"{lead}\n\n{scaffold}"

        file_path = current_file.get("path") if current_file else None
        if file_path:
            return (
                f"I am still with you. Re-anchor on `{file_path}`, restate the target behavior, "
                "and tell me the one decision that feels most uncertain so we can reduce it to the next smallest verifiable step."
            )
        return (
            "I am still with you. Re-anchor on the target behavior and tell me the one decision that feels most uncertain "
            "so we can reduce it to the next smallest verifiable step."
        )

    def _visible_empty_reply_guidance(
        self,
        *,
        profile: UserProfile | None = None,
        message: str = "",
        current_file: dict[str, object] | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict[str, Any] | None = None,
    ) -> str:
        guided_lane_reply = _guided_domain_empty_reply(
            message,
            current_file=current_file,
            coach_context=coach_context,
            response_language=response_language,
        )
        if guided_lane_reply:
            return guided_lane_reply

        if profile is not None:
            scaffold = self._scaffold_reply(
                profile,
                message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            ).strip()
            if scaffold:
                return scaffold

        file_path = current_file.get("path") if current_file else None
        if file_path:
            return _localized_text(
                f"I am still with you. Re-anchor on `{file_path}`, restate the target behavior, and tell me the one decision that feels most uncertain so we can reduce it to the next smallest verifiable step.",
                f"\u6211\u8fd8\u5728\u8ddf\u7740\u4f60\u3002\u5148\u56de\u5230 `{file_path}` \u8fd9\u6761\u94fe\u8def\uff0c\u91cd\u65b0\u786e\u8ba4\u76ee\u6807\u884c\u4e3a\uff0c\u7136\u540e\u544a\u8bc9\u6211\u4f60\u6700\u4e0d\u786e\u5b9a\u7684\u90a3\u4e00\u4e2a\u5224\u65ad\u70b9\uff0c\u6211\u4eec\u628a\u5b83\u538b\u7f29\u6210\u4e00\u4e2a\u6700\u5c0f\u53ef\u9a8c\u8bc1\u52a8\u4f5c\u3002",
                response_language,
            )
        return _localized_text(
            "I am still with you. Re-anchor on the target behavior and tell me the one decision that feels most uncertain so we can reduce it to the next smallest verifiable step.",
            "\u6211\u8fd8\u5728\u8ddf\u7740\u4f60\u3002\u5148\u91cd\u65b0\u786e\u8ba4\u76ee\u6807\u884c\u4e3a\uff0c\u518d\u544a\u8bc9\u6211\u4f60\u73b0\u5728\u6700\u4e0d\u786e\u5b9a\u7684\u4e00\u70b9\uff0c\u6211\u4eec\u628a\u5b83\u538b\u7f29\u6210\u4e00\u4e2a\u6700\u5c0f\u53ef\u9a8c\u8bc1\u52a8\u4f5c\u3002",
            response_language,
        )

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        if not self.has_usable_credential():
            raise RuntimeError(
                "API key not configured. Please set up your provider API key in settings."
            )
        model = self._resolve_model(model)
        try:
            if self._plain_completion_uses_agent_binding():
                return await self._completion_via_agent_binding(
                    messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            client = self._get_client()
            response, _ = await self._create_chat_completion(
                client=client,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            try:
                return _require_provider_runtime_response(
                    "openai_chat_completions",
                    response,
                    api_key=self._api_key,
                )
            except ProviderRuntimeResponseError as exc:
                # Reasoning-first models can spend the whole budget on hidden
                # reasoning and end with no visible text (truncated_or_empty).
                # Escalate once before surfacing a provider failure: adaptive,
                # so non-reasoning models never pay for it.
                if getattr(exc, "provider_error_category", None) != "truncated_or_empty":
                    raise
                escalated = self._escalated_chat_budget(max_tokens)
                if escalated is None:
                    raise
                logger.warning(
                    "[provider] truncated reply; retrying once with max_tokens=%s",
                    escalated,
                )
                response, _ = await self._create_chat_completion(
                    client=client,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=escalated,
                )
                return _require_provider_runtime_response(
                    "openai_chat_completions",
                    response,
                    api_key=self._api_key,
                )
        except ContextBudgetExhaustedError as exc:
            raise RuntimeError(self._context_budget_status_reply(None)) from exc
        except Exception as exc:
            raise RuntimeError(redact_provider_error(exc, api_key=self._api_key)) from exc

    async def chat_completion_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        cancel_event: asyncio.Event | None = None,
    ):
        if not self.has_usable_credential():
            raise RuntimeError(
                "API key not configured. Please set up your provider API key in settings."
            )
        model = self._resolve_model(model)
        try:
            if self._plain_completion_uses_agent_binding():
                async for chunk in self._completion_stream_via_agent_binding(
                    messages,  # type: ignore[arg-type]
                    temperature=temperature,
                    max_tokens=max_tokens,
                    cancel_event=cancel_event,
                ):
                    yield chunk
                return
            client = self._get_client()
            stream, _ = await _await_provider_stream_with_cancellation(
                self._create_chat_completion(
                    client=client,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                ),
                cancel_event,
            )
            reasoning_filter = ReasoningBlockFilter()
            emitted_visible = False

            def _normalize_stream_chunk(text: str) -> str:
                nonlocal emitted_visible
                if emitted_visible:
                    return text
                trimmed = text.lstrip()
                if not trimmed:
                    return ""
                emitted_visible = True
                return trimmed

            raw_content = ""
            finish_reason: str | None = None

            def _finish_seen() -> bool:
                return finish_reason is not None

            async for chunk in _iterate_provider_stream_with_cancellation(
                stream,
                cancel_event,
                finish_seen=_finish_seen,
            ):
                choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
                candidate_finish_reason = getattr(choice, "finish_reason", None)
                if isinstance(candidate_finish_reason, str) and candidate_finish_reason.strip():
                    finish_reason = candidate_finish_reason
                delta = getattr(choice, "delta", None)
                if delta is not None and getattr(delta, "content", None):
                    visible_chunk = _normalize_stream_chunk(
                        reasoning_filter.push(delta.content)
                    )
                    if visible_chunk:
                        raw_content += visible_chunk
                        yield visible_chunk
            tail = _normalize_stream_chunk(reasoning_filter.flush())
            if tail:
                raw_content += tail
                yield tail
            if not raw_content.strip():
                json_fallback = extract_non_sse_json_stream_payload(stream)
                if json_fallback is not None:
                    recovered_json_text = _require_provider_runtime_response(
                        "openai_chat_completions",
                        json_fallback,
                        api_key=self._api_key,
                        allow_local_empty_fallback=True,
                    )
                    if recovered_json_text.strip():
                        raw_content = recovered_json_text
                        finish_reason = "stop"
                        yield recovered_json_text
            if not raw_content.strip():
                # Nothing visible was emitted, so an escalated retry cannot
                # duplicate content: recover reasoning-first truncation here
                # instead of surfacing an empty/failed stream.
                escalated = self._escalated_chat_budget(max_tokens)
                if escalated is not None:
                    logger.warning(
                        "[provider] empty stream; retrying once with max_tokens=%s",
                        escalated,
                    )
                    try:
                        retry_response, _ = await self._create_chat_completion(
                            client=self._get_client(),
                            model=model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=escalated,
                        )
                        retry_text = _require_provider_runtime_response(
                            "openai_chat_completions",
                            retry_response,
                            api_key=self._api_key,
                        )
                    except Exception as exc:  # noqa: BLE001 - fall through to the honest error
                        logger.debug("Suppressed exception in coaching_reply_mixin: %s", exc)
                        retry_text = ""
                    if retry_text.strip():
                        raw_content = retry_text
                        yield retry_text
            _require_provider_runtime_response(
                "openai_chat_completions",
                {
                    "choices": [
                        {
                            "message": {"content": raw_content},
                            "finish_reason": finish_reason,
                        }
                    ]
                },
                api_key=self._api_key,
            )
        except ContextBudgetExhaustedError as exc:
            raise RuntimeError(self._context_budget_status_reply(None)) from exc
        except Exception as exc:
            raise RuntimeError(redact_provider_error(exc, api_key=self._api_key)) from exc


    # ------------------------------------------------------------------
    # Agent-loop based coaching
    # ------------------------------------------------------------------

    def build_agent_provider(
        self,
        *,
        attachments: list[dict[str, Any]] | None = None,
        protocol: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        messages: list[dict[str, Any]] | None = None,
    ):
        """Return a (AgentProvider, binding) tuple for this provider instance.

        Imported lazily so the heavy ``agent_binding`` module is only loaded
        when an agent loop turn actually runs.
        """
        from ..agent_binding import build_agent_provider_for

        if protocol is None and self._config is not None:
            protocol = getattr(self._config, "protocol", None)
        effective_max_tokens = self._effective_output_token_budget(
            messages or [],
            requested_max_tokens=max_tokens,
            prefer_configured_output=True,
        )
        # Reasoning-first models can spend the whole coaching budget on hidden
        # thought before the visible answer (or after tool results). Give the
        # agent loop the same generous headroom the one-shot probes use.
        effective_max_tokens = self.recommended_generation_max_tokens(effective_max_tokens)
        provider_obj, binding = build_agent_provider_for(
            self,
            protocol=protocol,
            attachments=attachments,
            temperature=temperature,
            max_tokens=effective_max_tokens,
            emit_activity=True,
        )
        binding._max_tokens = effective_max_tokens  # noqa: SLF001 - request budget is set per call below
        original_call = provider_obj.call
        original_call_stream = provider_obj.call_stream
        context_budget_state: dict[str, ContextBudgetExhaustedError | None] = {"error": None}
        self._agent_context_budget_states[id(provider_obj)] = context_budget_state

        def record_transport_failure(error: Exception) -> None:
            category, retryable, status, reachable, supported = self._classify_error(error)
            if category in {"network", "timeout", "upstream_unavailable", "unknown"}:
                self.reset_transport_client()
            provider_obj.last_failure = {
                "error_category": category,
                "retryable": retryable,
                "status_code": status,
                "provider_reachable": reachable,
                "model_supported": supported,
            }

        async def guarded_call(
            call_messages: list[dict[str, Any]],
            tools: list[dict[str, Any]] | None,
        ) -> dict[str, Any]:
            try:
                prepared_messages, call_max_tokens = self._prepare_context_budget(
                    call_messages,
                    requested_max_tokens=effective_max_tokens,
                    prefer_configured_output=True,
                )
            except ContextBudgetExhaustedError as exc:
                context_budget_state["error"] = exc
                return {"content": "", "tool_calls": []}
            previous_max_tokens = binding._max_tokens  # noqa: SLF001 - binding owns protocol payloads
            binding._max_tokens = call_max_tokens  # noqa: SLF001 - binding owns protocol payloads
            try:
                provider_obj.last_failure = None
                return await original_call(prepared_messages, tools)
            except Exception as exc:
                record_transport_failure(exc)
                raise
            finally:
                binding._max_tokens = previous_max_tokens  # noqa: SLF001 - restore this binding for callers

        if original_call_stream is not None:

            async def guarded_call_stream(
                call_messages: list[dict[str, Any]],
                tools: list[dict[str, Any]] | None,
            ):
                try:
                    prepared_messages, call_max_tokens = self._prepare_context_budget(
                        call_messages,
                        requested_max_tokens=effective_max_tokens,
                        prefer_configured_output=True,
                    )
                except ContextBudgetExhaustedError as exc:
                    context_budget_state["error"] = exc
                    yield {
                        "type": "final",
                        "content": "",
                        "tool_calls": [],
                        "stop_reason": "context_budget_exhausted",
                    }
                    return
                previous_max_tokens = binding._max_tokens  # noqa: SLF001 - binding owns protocol payloads
                binding._max_tokens = call_max_tokens  # noqa: SLF001 - binding owns protocol payloads
                try:
                    provider_obj.last_failure = None
                    async for event in original_call_stream(prepared_messages, tools):
                        # AgentLoop only forwards tool-capable text deltas when
                        # the binding has explicitly identified them as
                        # visible model output. Tool argument fragments remain
                        # untouched and are handled by the binding's final
                        # tool-call envelope.
                        if tools and str(event.get("type") or "") in {"delta", "text"}:
                            yield {**event, "safe_to_stream": True}
                        else:
                            yield event
                except Exception as exc:
                    record_transport_failure(exc)
                    raise
                finally:
                    binding._max_tokens = previous_max_tokens  # noqa: SLF001 - restore this binding

            provider_obj.call_stream = guarded_call_stream

        provider_obj.call = guarded_call
        return provider_obj, binding


def _compose_guided_lane_continuity_patch(
    *,
    reply: str,
    scenario: str,
    chinese: bool,
) -> str:
    guided_lane = _first_turn_guided_lane(scenario, "")
    if guided_lane not in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        return ""
    if _reply_has_guided_lane_signal(reply, guided_lane, chinese):
        return ""
    return _first_turn_lane_continuity_note(guided_lane, chinese=chinese)


def _reply_mentions_other_guided_lane(reply: str, *, scenario: str, chinese: bool) -> bool:
    if not reply.strip() or scenario not in _GUIDED_DOMAIN_SCENARIOS:
        return False
    lowered = reply.casefold()
    lane_markers = _fresh_lane_marker_map(chinese=chinese)
    other_lane_markers = [
        marker
        for lane, markers in lane_markers.items()
        if lane != scenario
        for marker in markers
    ]
    return any(marker.casefold() in lowered for marker in other_lane_markers)


async def _provider_service_coaching_reply_stream(
    self,
    profile: UserProfile | None,
    message: str,
    current_file: dict[str, object] | None = None,
    response_language: str | None = None,
    answer_mode: str | None = None,
    coach_context: dict[str, Any] | None = None,
    history: list[dict[str, str]] | None = None,
    cancel_event: asyncio.Event | None = None,
):
    self.clear_last_reply_state()
    cancel_event = cancel_event or _stream_cancel_event(
        coach_context.get("stream_cancel_event") if isinstance(coach_context, dict) else None
    )
    if not self.has_usable_credential():
        if not profile:
            yield self._missing_api_key_reply(response_language)
            return
        yield self._missing_api_key_reply_with_scaffold(
            profile,
            message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        return
    if not profile:
        yield self._onboarding_reply(response_language)
        return

    model = self._resolve_model()
    history_limit, history_token_budget = self._smart_coaching_history_budget(model=model)
    messages = build_coaching_messages(
        profile,
        message,
        current_file,
        response_language=response_language,
        answer_mode=answer_mode,
        coach_context=coach_context,
        history=history,
        history_limit=history_limit,
        history_token_budget=history_token_budget,
    )
    resource_intent = coach_context.get("resource_composer_intent") if coach_context else None
    analysis_requested = (
        _coaching_active_view_name(coach_context) == "resources"
        and isinstance(resource_intent, dict)
        and resource_intent.get("mode") == "analyze"
    )
    output_budget = (
        self._coaching_requested_output_tokens(
            message,
            coach_context,
            analysis_requested=analysis_requested,
        )
        or self.recommended_generation_max_tokens(DEFAULT_COACHING_MAX_OUTPUT_TOKENS)
    )
    try:
        messages, max_tokens = self._prepare_context_budget(
            messages,
            model=model,
            requested_max_tokens=output_budget,
            prefer_configured_output=True,
        )
        if self._plain_completion_uses_agent_binding():
            raw_content = ""
            pending_visible = ""
            yielded_visible = False
            holdback_chars = _stream_holdback_chars(response_language)
            async for chunk in self._completion_stream_via_agent_binding(
                messages,
                temperature=0.7,
                max_tokens=max_tokens,
                prefer_configured_output=True,
                allow_local_empty_fallback=True,
                cancel_event=cancel_event,
            ):
                raw_content += chunk
                pending_visible += chunk
                if any("\u0370" <= ch <= "\u0e7f" for ch in chunk):
                    reply_corruption_detail = _mixed_script_reply_corruption_detail(
                        raw_content[-256:],
                        message=message,
                        response_language=response_language,
                    )
                    if reply_corruption_detail:
                        self._record_reply_language_corruption(reply_corruption_detail)
                        if not yielded_visible:
                            recovery_override = _build_language_corruption_recovery_override(
                                message,
                                current_file=current_file,
                                coach_context=coach_context,
                                response_language=response_language,
                            )
                            if isinstance(recovery_override, dict):
                                reply_override = str(recovery_override.get("reply") or "").strip()
                                if reply_override:
                                    yield reply_override
                        return
                if len(pending_visible) > holdback_chars:
                    if holdback_chars <= 0:
                        safe_prefix = pending_visible
                        pending_visible = ""
                    else:
                        safe_prefix = pending_visible[:-holdback_chars]
                        pending_visible = pending_visible[-holdback_chars:]
                    if safe_prefix:
                        yielded_visible = True
                        yield safe_prefix
            reply_corruption_detail = _mixed_script_reply_corruption_detail(
                raw_content,
                message=message,
                response_language=response_language,
            )
            if reply_corruption_detail:
                self._record_reply_language_corruption(reply_corruption_detail)
                if not yielded_visible:
                    recovery_override = _build_language_corruption_recovery_override(
                        message,
                        current_file=current_file,
                        coach_context=coach_context,
                        response_language=response_language,
                    )
                    if isinstance(recovery_override, dict):
                        reply_override = str(recovery_override.get("reply") or "").strip()
                        if reply_override:
                            yield reply_override
                return
            if pending_visible:
                yielded_visible = True
                yield pending_visible
            final_content = self.finalize_coaching_reply(
                raw_content,
                profile=profile,
                message=message,
                current_file=current_file,
                response_language=response_language,
                answer_mode=answer_mode,
                coach_context=coach_context,
            )
            if yielded_visible and raw_content and self.peek_last_reply_failure() is None:
                final_content = preserve_streamed_reply_prefix(
                    raw_content,
                    final_content,
                    raw_content,
                    response_language=response_language,
                )
            self._record_stream_finalization(raw_content, final_content)
            if not raw_content and final_content:
                yield final_content
                return
            if final_content.startswith(raw_content) and final_content != raw_content:
                yield final_content[len(raw_content) :]
            return
        client = self._get_client()
        stream, _ = await _await_provider_stream_with_cancellation(
            self._create_chat_completion(
                client=client,
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=max_tokens,
                stream=True,
            ),
            cancel_event,
        )
        reasoning_filter = ReasoningBlockFilter()
        emitted_visible = False
        yielded_visible = False

        def _normalize_stream_chunk(text: str) -> str:
            nonlocal emitted_visible
            if emitted_visible:
                return text
            trimmed = text.lstrip()
            if not trimmed:
                return ""
            emitted_visible = True
            return trimmed

        raw_content = ""
        pending_visible = ""
        holdback_chars = _stream_holdback_chars(response_language)
        finish_reason: str | None = None

        def _finish_seen() -> bool:
            return finish_reason is not None

        async for chunk in _iterate_provider_stream_with_cancellation(
            stream,
            cancel_event,
            finish_seen=_finish_seen,
        ):
            choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
            candidate_finish_reason = getattr(choice, "finish_reason", None)
            if isinstance(candidate_finish_reason, str) and candidate_finish_reason.strip():
                finish_reason = candidate_finish_reason
            delta = getattr(choice, "delta", None)
            if delta is not None and getattr(delta, "content", None):
                text = _normalize_stream_chunk(reasoning_filter.push(delta.content))
                if not text:
                    continue
                raw_content += text
                pending_visible += text
                if any("\u0370" <= ch <= "\u0e7f" for ch in text):
                    reply_corruption_detail = _mixed_script_reply_corruption_detail(
                        raw_content[-256:],
                        message=message,
                        response_language=response_language,
                    )
                    if reply_corruption_detail:
                        self._record_reply_language_corruption(reply_corruption_detail)
                        if not yielded_visible:
                            recovery_override = _build_language_corruption_recovery_override(
                                message,
                                current_file=current_file,
                                coach_context=coach_context,
                                response_language=response_language,
                            )
                            if isinstance(recovery_override, dict):
                                reply_override = str(recovery_override.get("reply") or "").strip()
                                if reply_override:
                                    yield reply_override
                        return
                if len(pending_visible) > holdback_chars:
                    if holdback_chars <= 0:
                        safe_prefix = pending_visible
                        pending_visible = ""
                    else:
                        safe_prefix = pending_visible[:-holdback_chars]
                        pending_visible = pending_visible[-holdback_chars:]
                    if safe_prefix:
                        yielded_visible = True
                        yield safe_prefix
        tail = _normalize_stream_chunk(reasoning_filter.flush())
        if tail:
            raw_content += tail
            pending_visible += tail
        if not raw_content.strip() and finish_reason is None:
            json_fallback = extract_non_sse_json_stream_payload(stream)
            if json_fallback is not None:
                recovered_json_text = _require_provider_runtime_response(
                    "openai_chat_completions",
                    json_fallback,
                    api_key=self._api_key,
                    allow_local_empty_fallback=True,
                )
                if recovered_json_text.strip():
                    raw_content = recovered_json_text
                    pending_visible = recovered_json_text
                    finish_reason = "stop"
        reply_corruption_detail = _mixed_script_reply_corruption_detail(
            raw_content,
            message=message,
            response_language=response_language,
        )
        if reply_corruption_detail:
            self._record_reply_language_corruption(reply_corruption_detail)
            if not yielded_visible:
                recovery_override = _build_language_corruption_recovery_override(
                    message,
                    current_file=current_file,
                    coach_context=coach_context,
                    response_language=response_language,
                )
                if isinstance(recovery_override, dict):
                    reply_override = str(recovery_override.get("reply") or "").strip()
                    if reply_override:
                        yield reply_override
            return
        def stream_response() -> dict[str, Any]:
            return {"choices": [{"message": {"content": raw_content}, "finish_reason": finish_reason}]}

        assessment = normalize_provider_response(
            "openai_chat_completions", stream_response(), api_key=self._api_key,
        )
        if not yielded_visible and (assessment.truncated or not raw_content.strip()):
            # The held-back prefix has not been emitted. A single retry can
            # replace it without duplicating text in the learner's reply.
            escalated = self._escalated_chat_budget(max_tokens)
            if escalated is not None:
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError
                logger.warning(
                    "[provider] coaching stream %s; retrying once with max_tokens=%s",
                    assessment.outcome, escalated,
                )
                try:
                    retry_response, _ = await _await_provider_stream_with_cancellation(
                        self._create_chat_completion(
                            client=client,
                            model=model,
                            messages=messages,
                            temperature=0.7,
                            max_tokens=escalated,
                        ),
                        cancel_event,
                    )
                    retry_text = _require_provider_runtime_response(
                        "openai_chat_completions",
                        retry_response,
                        api_key=self._api_key,
                        allow_local_empty_fallback=True,
                    )
                except Exception as exc:  # noqa: BLE001 - fall through to the honest error
                    logger.debug("Suppressed exception in coaching_reply_mixin: %s", exc)
                    retry_text = ""
                if retry_text.strip():
                    raw_content = retry_text
                    pending_visible = retry_text
                    # The recovered reply is complete: the original stream's
                    # truncated finish_reason must not mark it as truncated.
                    finish_reason = "stop"
                    retry_corruption = _mixed_script_reply_corruption_detail(
                        raw_content,
                        message=message,
                        response_language=response_language,
                    )
                    if retry_corruption:
                        self._record_reply_language_corruption(retry_corruption)
                        return
        _require_provider_runtime_response(
            "openai_chat_completions",
            stream_response(),
            api_key=self._api_key,
            allow_local_empty_fallback=True,
        )
        if pending_visible:
            yielded_visible = True
            yield pending_visible
        final_content = self.finalize_coaching_reply(
            raw_content,
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
        if yielded_visible and raw_content and self.peek_last_reply_failure() is None:
            final_content = preserve_streamed_reply_prefix(
                raw_content,
                final_content,
                raw_content,
                response_language=response_language,
            )
        self._record_stream_finalization(raw_content, final_content)
        if not raw_content and final_content:
            yield final_content
            return
        if final_content.startswith(raw_content) and final_content != raw_content:
            yield final_content[len(raw_content) :]
    except ContextBudgetExhaustedError:
        self._record_last_reply_override(
            stop_reason="context_budget_exhausted",
            fell_back=False,
            context_budget_exhausted=True,
        )
        yield self._context_budget_status_reply(response_language)
    except Exception as exc:
        category, retryable, status_code, provider_reachable, model_supported = self._classify_error(exc)
        provider_config = self._config or ProviderConfig(
            name="unspecified-provider",
            baseUrl="",
            apiKeyRef="trainer.unspecified",
            model=self._resolve_model(),
        )
        detail = self._detail_from_category(
            category,
            provider=provider_config,
            error=exc,
        )
        self._record_last_reply_failure(
            category=category,
            detail=detail,
            retryable=retryable,
            status_code=status_code,
            provider_reachable=provider_reachable,
            model_supported=model_supported,
            error=exc,
        )
        yield self._error_reply_with_scaffold(
            exc=exc,
            profile=profile,
            message=message,
            current_file=current_file,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_context=coach_context,
        )
