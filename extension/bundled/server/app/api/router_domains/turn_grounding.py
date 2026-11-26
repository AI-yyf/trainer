"""Formal plan commit verification, async turn grounding & regeneration, and reflection persistence."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from ...core.models import (
    CoachDefaults,
    CoachTurnSummary,
    ProviderConfig,
    SessionMessageRequest,
    SessionMessageResponse,
    TurnRequest,
)
from ...llm.provider_service import (
    ProviderService,
)
from ...llm.reply_continuity import visible_next_step
from ...llm.turn_grounding import (
    GroundingDecision,
    WorkspaceEvidence,
    build_teaching_turn_facts,
    evaluate_next_step_grounding,
    evaluate_turn_grounding,
    grounding_correction_instruction,
    grounding_outcome,
    memory_provenance_summary,
    trim_ungrounded_segments,
)
from ...memory.workspace_recovery import (
    PLAN_RUNTIME_KEY,
    accept_in_progress_plan_runtime_turn,
    accept_plan_runtime_resume_request,
    extract_structured_plan_runtime_facts,
    plan_runtime_status_from_recovery,
    recovered_resume_turn_succeeded,
)
from .. import coach_support
from .._helpers import (
    localized_text,
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
from ..router_support import (
    _attach_requested_workspace_files as _attach_requested_workspace_files,
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
    DETERMINISTIC_LANE_SCENARIOS,
    GROUNDING_DECISION_CACHE_KEY,
    GROUNDING_EVALUATED_NEXT_STEP_CACHE_KEY,
    GROUNDING_MEMORY_PROVENANCE_CACHE_KEY,
    PROVIDER_REPLY_STOP_REASONS,
)

logger = logging.getLogger(__name__)


class TurnGroundingDomainMixin(RouterDomainBase):
    """Formal plan commit verification, async turn grounding & regeneration, and reflection persistence."""

    def requires_formal_plan_commit(self, request: TurnRequest | SessionMessageRequest) -> bool:
        return bool(
            getattr(request, "formal_plan_mutation", False)
            and str(getattr(request, "intent", "") or "").strip().lower() == "plan"
        )

    def formal_plan_commit_tool_succeeded(self, tool_events: object) -> bool:
        if not isinstance(tool_events, list):
            return False
        for raw_event in tool_events:
            if not isinstance(raw_event, dict):
                continue
            if str(raw_event.get("type") or "").strip() != "tool_result":
                continue
            event_name = str(raw_event.get("name") or "").strip()
            if event_name not in {"learning_action", "save_formal_plan"}:
                continue
            result = raw_event.get("result")
            if not isinstance(result, dict):
                continue
            if (
                event_name == "learning_action"
                and str(result.get("action") or "save_formal_plan").strip().lower()
                != "save_formal_plan"
            ):
                continue
            if result.get("ok") is True and result.get("committed") is True:
                return True
        return False

    def formal_plan_commit_verified(self, 
        *,
        state: SessionState,
        request: TurnRequest | SessionMessageRequest,
        agent_meta: dict[str, object] | None,
    ) -> bool:
        if not self.requires_formal_plan_commit(request):
            return True
        if not self.formal_plan_commit_tool_succeeded(
            agent_meta.get("tool_events") if isinstance(agent_meta, dict) else None
        ):
            return False
        return self.runtime.repository.get_latest_plan(state.workspace_id) is not None

    def formal_plan_commit_missing_reply(self, response_language: str | None) -> str:
        return localized_text(
            "Trainer has not committed a formal plan because the explicit save step did not complete. Confirm the goal, available time, and selected resource evidence, then save the plan in a new plan turn.",
            "正式计划还没有写入，因为明确保存计划的步骤没有完成。请确认目标、可投入时间和已选资料证据，然后在新的计划回合中保存。",
            response_language,
        )

    def formal_plan_commit_missing_next_step(self, response_language: str | None) -> str:
        return localized_text(
            "Clarify the remaining scope or evidence, then ask Trainer to save the formal plan again.",
            "补齐仍不清楚的范围或证据后，再让 Trainer 重新保存正式计划。",
            response_language,
        )

    def turn_grounding_code_text(self, request: TurnRequest | SessionMessageRequest) -> str:
        """Code facts a next step may cite: current file content + learner message."""
        parts: list[str] = []
        current_file_payload = self.normalize_current_file_payload(
            getattr(request, "current_file", None)
        )
        if isinstance(current_file_payload, dict):
            for key in ("path", "Path", "content", "Content"):
                value = str(current_file_payload.get(key) or "").strip()
                if value:
                    parts.append(value)
        message_text = str(getattr(request, "message", "") or "").strip()
        if message_text:
            parts.append(message_text)
        return "\n".join(parts)

    def turn_history_text(self, snapshot: object) -> str:
        """Prior conversation facts (user + assistant) the next step may cite.

        A next step may legitimately keep referencing a symbol or file that an
        earlier turn introduced (tool call result, earlier reply), so the
        running conversation joins the grounding corpus.
        """
        parts: list[str] = []
        for message in getattr(snapshot, "messages", None) or []:
            role = str(getattr(message, "role", "") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            content = str(getattr(message, "content", "") or "").strip()
            if content:
                parts.append(content)
        return "\n".join(parts[-12:])

    def apply_next_step_grounding_policy(self, 
        *,
        coach_turn: CoachTurnSummary,
        reply_content: str,
        request: TurnRequest | SessionMessageRequest,
        agent_meta: dict[str, object] | None,
        coach_turn_data: CoachTurnPayload | dict[str, object] | None = None,
        history_text: str = "",
    ) -> CoachTurnSummary:
        """Teaching-turn grounding gate (legacy synchronous path).

        Prefer ``resolve_turn_grounding_async`` + ``apply_grounding_decision`` at
        the four persistence points; this synchronous gate remains only for
        response-building paths that never ran the resolve step (no cached
        decision). A wire path must always use the cached decision so each turn
        is decided at most once.
        """
        next_step_text = str(coach_turn.next_step or "").strip()
        if not next_step_text or coach_turn.requires_confirmation:
            return coach_turn
        decision = evaluate_next_step_grounding(
            next_step_text,
            reply_content,
            self.turn_grounding_code_text(request),
            extra_context=history_text,
        )
        if decision.grounded:
            return coach_turn
        logger.warning(
            "coach turn next_step downgraded to requires_confirmation; "
            "ungrounded symbols: %s; correction: %s",
            ", ".join(decision.referenced_symbols) or "-",
            grounding_correction_instruction(request.response_language),
        )
        # Only attach the diagnostic stamp to EXISTING agent chrome: a clean
        # reply must keep agent_meta absent/empty (sanitization contract).
        # coach_turn.requires_confirmation is the canonical user-facing signal.
        if isinstance(agent_meta, dict) and agent_meta:
            agent_meta["next_step_requires_confirmation"] = True
        if isinstance(coach_turn_data, dict):
            coach_turn_data["requires_confirmation"] = True
        return coach_turn.model_copy(update={"requires_confirmation": True})

    def grounding_next_step_text(self, coach_turn_data: object) -> str:
        """The next step currently carried by a coach-turn payload."""
        if not isinstance(coach_turn_data, dict):
            return ""
        turn_summary = coach_turn_data.get("coach_turn")
        if not isinstance(turn_summary, CoachTurnSummary):
            return ""
        return str(turn_summary.next_step or "").strip()

    def grounding_decision_from_payload(self, coach_turn_data: object) -> GroundingDecision | None:
        """Read the turn's cached decision — only while it still fits the text.

        The decision is keyed to the next-step text it was made for: a second
        execution pass (e.g. ``/turn/stream`` re-running the streamed turn)
        that delivers a different next step invalidates the cache instead of
        shipping the earlier "grounded" conclusion with an unevaluated step.
        """
        if not isinstance(coach_turn_data, dict):
            return None
        cached = coach_turn_data.get(GROUNDING_DECISION_CACHE_KEY)
        if not isinstance(cached, GroundingDecision):
            return None
        evaluated_text = coach_turn_data.get(GROUNDING_EVALUATED_NEXT_STEP_CACHE_KEY)
        if evaluated_text != self.grounding_next_step_text(coach_turn_data):
            return None
        return cached

    def turn_grounding_turn_id(self, request: TurnRequest | SessionMessageRequest) -> str:
        explicit = str(getattr(request, "request_id", None) or "").strip()
        if explicit:
            return explicit
        session_part = str(getattr(request, "session_id", None) or "").strip() or "turn"
        return f"{session_part}-{uuid4().hex[:12]}"

    def turn_grounding_file_exists(self, workspace_root: str, candidate: str) -> bool | None:
        """Workspace-scoped existence for file-pointer claims.

        ``None`` means unverifiable (outside the workspace root, URI paths,
        null bytes, unreadable state) — never a fabricated verdict.
        """
        raw = str(candidate or "").strip().strip("`").strip("\"'")
        if not raw or "\x00" in raw or "://" in raw:
            return None
        try:
            resolved_root = Path(workspace_root).resolve()
            target = Path(raw)
            resolved = (
                target.resolve()
                if target.is_absolute()
                else (resolved_root / target).resolve()
            )
            resolved.relative_to(resolved_root)
            return resolved.exists()
        except (OSError, ValueError):
            return None

    def turn_grounding_workspace_evidence(self, 
        request: TurnRequest | SessionMessageRequest,
    ) -> WorkspaceEvidence:
        """Workspace verification input; remote/URI workspaces stay unverifiable."""
        workspace_id = self.current_workspace_id(
            session_id=getattr(request, "session_id", None),
            workspace_id=getattr(request, "workspace_id", None),
        )
        workspace_root = self.runtime.resolve_workspace_path(workspace_id)
        workspace = self.runtime.memory_service.snapshot(workspace_id).workspace
        if not workspace_root or "://" in workspace_root or bool(workspace.get("remote_name")):
            return WorkspaceEvidence(unverifiable=True)
        return WorkspaceEvidence(
            file_exists=lambda candidate: self.turn_grounding_file_exists(workspace_root, candidate)
        )

    def grounding_response_coach_turn(self, 
        *,
        coach_turn: CoachTurnSummary,
        decision: GroundingDecision,
    ) -> CoachTurnSummary:
        """Apply a decided outcome to one summary without re-evaluating."""
        updated = coach_turn
        if decision.corrected_next_step and not decision.requires_confirmation:
            updated = updated.model_copy(update={"next_step": decision.corrected_next_step})
        if decision.requires_confirmation and not updated.requires_confirmation:
            updated = updated.model_copy(update={"requires_confirmation": True})
        return updated

    def apply_grounding_decision(self, 
        *,
        coach_turn_payload: CoachTurnPayload | dict[str, object] | None,
        decision: GroundingDecision,
        agent_meta: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        """Cache one decision on the payload and apply it (per evaluated text).

        Idempotent for the same next-step text; when a later execution pass
        replaced the text, the previous decision no longer fits and the new one
        is applied, its flag state replacing the stale one. Writes the
        corrected next step back (``model_copy``), mirrors the downgrade flag,
        stamps the fixed agent_meta keys, and keys the cache to the delivered
        text so ``build_session_response`` never re-evaluates a decided turn.
        """
        if not isinstance(coach_turn_payload, dict):
            return None
        previous_decision = coach_turn_payload.get(GROUNDING_DECISION_CACHE_KEY)
        re_applying = isinstance(previous_decision, GroundingDecision)
        if re_applying:
            evaluated_text = coach_turn_payload.get(GROUNDING_EVALUATED_NEXT_STEP_CACHE_KEY)
            if evaluated_text == self.grounding_next_step_text(coach_turn_payload):
                return None
        coach_turn_payload[GROUNDING_DECISION_CACHE_KEY] = decision
        turn_summary = coach_turn_payload.get("coach_turn")
        if isinstance(turn_summary, CoachTurnSummary):
            updated_summary = self.grounding_response_coach_turn(
                coach_turn=turn_summary,
                decision=decision,
            )
            if re_applying and not decision.requires_confirmation:
                # The new text is grounded: a stale downgrade flag from the
                # replaced text must not survive its re-evaluation.
                updated_summary = updated_summary.model_copy(
                    update={"requires_confirmation": False}
                )
            coach_turn_payload["coach_turn"] = updated_summary
            coach_context = coach_turn_payload.get("coach_context")
            if (
                isinstance(coach_context, dict)
                and decision.corrected_next_step
                and not decision.requires_confirmation
            ):
                active_thread = coach_context.get("active_thread")
                if (
                    isinstance(active_thread, dict)
                    and str(active_thread.get("next_step") or "").strip()
                ):
                    active_thread["next_step"] = decision.corrected_next_step
        if decision.requires_confirmation:
            coach_turn_payload["requires_confirmation"] = True
        elif re_applying and "requires_confirmation" in coach_turn_payload:
            coach_turn_payload["requires_confirmation"] = False
        # Key the cache to the text actually delivered (post write-back).
        coach_turn_payload[GROUNDING_EVALUATED_NEXT_STEP_CACHE_KEY] = self.grounding_next_step_text(
            coach_turn_payload
        )
        # Attach stamps to existing agent chrome. A clean grounded reply keeps
        # agent_meta absent/empty (sanitization contract). A non-clean decision
        # (corrected next step or requires-confirmation downgrade) is surfaced
        # even on guided-lane turns that have no agent chrome — the learner and
        # the maturity harness must be able to see the server verdict — via a
        # minimal honest chrome that stays ``agentic: False``. Returns the
        # agent chrome carrying the stamps (or None) so response builders can
        # adopt it when the caller had none.
        outcome = grounding_outcome(decision)
        clean_pass = outcome == "grounded" and not decision.requires_confirmation
        if isinstance(agent_meta, dict) and agent_meta:
            stamped = agent_meta
        elif clean_pass:
            return None
        else:
            stamped: dict[str, object] = {"agentic": False}
        stamped["grounding_outcome"] = outcome
        stamped["grounding_ungrounded_symbols"] = list(decision.referenced_symbols)
        stamped["grounding_retry_used"] = bool(decision.retry_used)
        stamped["next_step_requires_confirmation"] = bool(decision.requires_confirmation)
        return stamped

    def turn_grounding_retry_eligible(self, 
        *,
        agent_meta: dict[str, object] | None,
        coaching_service: ProviderService | None,
        scenario: str | None = None,
    ) -> bool:
        """A retry needs a model-authored next step and a live-usable provider.

        The regeneration exists to rewrite a next step the model authored; it
        must never run for locally composed steps (lane composition, visible
        repair, recovery/fallback lanes) or for turns with no model chrome at
        all — those go straight to the honest downgrade.
        """
        def _blocked(reason: str) -> bool:
            logger.warning("[grounding] retry blocked: %s", reason)
            return False

        if coaching_service is None:
            return _blocked("no coaching service")
        if str(scenario or "").strip() in DETERMINISTIC_LANE_SCENARIOS:
            # First-turn lanes ship a canonical, hand-composed step (remote
            # boundary, debug loop, function guidance, project adaptation);
            # rewriting it with the model would replace the ruling.
            return _blocked("deterministic lane scenario")
        # The turn just produced a provider reply, so the turn itself is the
        # live proof: only the transport must be configured (no prior Settings
        # test is required for a grounded rewrite).
        if not bool(getattr(coaching_service, "has_api_key", False)):
            return _blocked("no api key")
        service_config = getattr(coaching_service, "_config", None)
        if isinstance(service_config, ProviderConfig) and not self.provider_transport_is_configured(
            service_config.name,
            service_config.base_url,
            service_config.model,
        ):
            return _blocked("transport not configured")
        if not isinstance(agent_meta, dict) or not agent_meta:
            # The plain guided lane carries no agent chrome, but its reply and
            # next step are still provider-authored (fallbacks set fell_back,
            # so they never arrive here empty). Allowing the rewrite is what
            # turns an ungrounded guided step into a grounded one.
            return True
        if not str(agent_meta.get("next_step") or "").strip():
            return _blocked("no model-authored next step")
        if bool(agent_meta.get("fell_back")):
            return _blocked("fell back")
        if bool(agent_meta.get("local_sequence_fallback")):
            return _blocked("local sequence fallback")
        if bool(agent_meta.get("guided_lane_visible_repaired")):
            return _blocked("visible repaired")
        if str(agent_meta.get("stop_reason") or "").strip() in PROVIDER_REPLY_STOP_REASONS:
            return _blocked("provider reply stop reason")
        return True

    def grounding_retry_first_line(self, raw: object) -> str:
        """Take the first meaningful line of a regenerated next step."""
        text = str(raw or "").strip().strip("`")
        if not text:
            return ""
        for line in text.splitlines():
            candidate = line.strip().strip("`").strip("\"'").strip()
            if not candidate:
                continue
            lowered = candidate.lower()
            for prefix in ("next step:", "next_step:", "下一步：", "下一步:"):
                if lowered.startswith(prefix):
                    candidate = candidate[len(prefix) :].strip()
                    break
            if candidate.startswith(("-", "*")):
                candidate = candidate[1:].strip()
            return candidate[:300]
        return ""

    async def request_grounding_regeneration(self, 
        *,
        coaching_service: ProviderService,
        request: TurnRequest | SessionMessageRequest,
        reply_content: str,
        next_step_text: str,
        ungrounded: list[str] | None = None,
    ) -> str:
        """One bounded regeneration attempt; any failure degrades to downgrade."""
        code_text = self.turn_grounding_code_text(request)
        forbidden = [str(item).strip() for item in (ungrounded or []) if str(item).strip()]
        context_parts = [
            f"Learner message:\n{str(request.message or '').strip()[:2000]}",
            f"Coach reply (already delivered):\n{str(reply_content or '').strip()[:2000]}",
            f"Current code:\n{code_text[:2000]}" if code_text.strip() else "",
            f"Rejected next step (references symbols or files that do not exist):\n{next_step_text[:500]}",
            # Naming the forbidden references explicitly prevents the model from
            # copying them out of the rejected step it was just shown.
            f"Do NOT mention any of these unverified references: {', '.join(forbidden)}."
            if forbidden
            else "",
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Trainer's coding coach. "
                    f"{grounding_correction_instruction(request.response_language)} "
                    "Rewrite ONLY the next step as one short actionable sentence. "
                    "Reply with the next step text only, no quotes or prefixes."
                ),
            },
            {
                "role": "user",
                "content": "\n\n".join(part for part in context_parts if part.strip()),
            },
        ]
        try:
            raw = await coaching_service.chat_completion(messages, temperature=0.2, max_tokens=160)
        except Exception:
            # Bounded best-effort retry: a failed regeneration degrades to the
            # honest downgrade instead of masking the failure or crashing the turn.
            logger.warning("grounding retry regeneration failed; downgrading next step")
            return ""
        return self.grounding_retry_first_line(raw)

    async def resolve_turn_grounding_async(self, 
        *,
        coach_turn_payload: CoachTurnPayload | dict[str, object] | None,
        reply_content: str,
        request: TurnRequest | SessionMessageRequest,
        agent_meta: dict[str, object] | None,
        history_text: str = "",
        coaching_service: ProviderService | None = None,
    ) -> GroundingDecision:
        """Decide this turn's grounding once, with at most one provider retry.

        Runs after the reply completes and before persistence; the returned
        decision is applied via ``apply_grounding_decision`` and cached, so the
        response builder consumes it without evaluating again.
        """
        if not isinstance(coach_turn_payload, dict):
            return GroundingDecision(grounded=True)
        turn_summary = coach_turn_payload.get("coach_turn")
        next_step_text = (
            str(turn_summary.next_step or "").strip()
            if isinstance(turn_summary, CoachTurnSummary)
            else ""
        )
        if not next_step_text:
            return GroundingDecision(grounded=True)
        if isinstance(turn_summary, CoachTurnSummary) and turn_summary.requires_confirmation:
            return GroundingDecision(
                grounded=False,
                referenced_symbols=[],
                retry_used=False,
                requires_confirmation=True,
            )
        facts = build_teaching_turn_facts(
            turn_id=self.turn_grounding_turn_id(request),
            reply_text=str(reply_content or ""),
            code_text=self.turn_grounding_code_text(request),
            history_text=history_text,
            user_message=str(request.message or ""),
            workspace_evidence=self.turn_grounding_workspace_evidence(request),
            agent_evidence=agent_meta,
            next_step_text=next_step_text,
        )
        decision = evaluate_turn_grounding(facts)
        retry_eligible = (
            not decision.grounded
            and coaching_service is not None
            and self.turn_grounding_retry_eligible(
                agent_meta=agent_meta,
                coaching_service=coaching_service,
                scenario=(
                    str(getattr(turn_summary, "scenario", "") or "")
                    if isinstance(turn_summary, CoachTurnSummary)
                    else ""
                ),
            )
        )
        if retry_eligible and coaching_service is not None:
            regenerated = await self.request_grounding_regeneration(
                coaching_service=coaching_service,
                request=request,
                reply_content=str(reply_content or ""),
                next_step_text=next_step_text,
                ungrounded=decision.referenced_symbols,
            )
            # `retry_used` means "a retry was attempted" in the rules layer; an
            # empty regeneration is still an attempt, so the re-check runs with
            # the (possibly empty) regenerated text and both layers agree.
            decision = evaluate_turn_grounding(facts, retry_generate=lambda: regenerated)
        if not decision.grounded:
            # Deterministic lane steps and exhausted retries: drop exactly the
            # segments carrying ungrounded references instead of shipping a
            # fabricated demand or replacing the lane ruling.
            trimmed = trim_ungrounded_segments(next_step_text, decision.referenced_symbols)
            if trimmed and trimmed != next_step_text.strip():
                trimmed_facts = build_teaching_turn_facts(
                    turn_id=self.turn_grounding_turn_id(request),
                    reply_text=str(reply_content or ""),
                    code_text=self.turn_grounding_code_text(request),
                    history_text=history_text,
                    user_message=str(request.message or ""),
                    workspace_evidence=self.turn_grounding_workspace_evidence(request),
                    agent_evidence=agent_meta,
                    next_step_text=trimmed,
                )
                if evaluate_turn_grounding(trimmed_facts).grounded:
                    decision = GroundingDecision(
                        grounded=True,
                        referenced_symbols=[],
                        # A correction was attempted and shipped (deterministic
                        # trim, no provider call).
                        retry_used=True,
                        requires_confirmation=False,
                        corrected_next_step=trimmed,
                    )
        if not decision.grounded:
            # One diagnostic line per ungrounded turn: which references failed,
            # whether a retry was allowed, and whether it corrected the step.
            logger.warning(
                "[grounding] ungrounded=%s retry_eligible=%s retry_used=%s corrected=%s",
                decision.referenced_symbols,
                retry_eligible,
                decision.retry_used,
                bool(decision.corrected_next_step),
            )
        # Field-level memory admission mapping (§2.6/§2.7) travels with the
        # decision so persistence can pass it to the memory writer.
        coach_turn_payload[GROUNDING_MEMORY_PROVENANCE_CACHE_KEY] = memory_provenance_summary(
            facts,
            decision,
        )
        return decision

    def repair_generic_finalize_next_step(self, 
        reply_content: str,
        agent_meta: dict[str, object] | None,
        coach_turn_data: dict[str, object] | None,
        *,
        response_language: str | None,
    ) -> dict[str, object] | None:
        """T-0027 repair: when the finalize next_step is generic filler (goal
        restatement, "do a small action" phrasing) or a pasted prose blob
        (markdown headings / code fences / over the extractor's 240-char
        action cap) while the visible reply carries a concrete labelled next
        action, prefer the reply's own labelled action so the structured next
        step matches what the learner is actually told to do. Mutates
        agent_meta in place and re-merges the repaired step into
        coach_turn_data (T-0035), returning the payload to persist. Callers
        must run this BEFORE grounding and memory persistence so every
        consumer — memory thread, grounding gate, response surfaces — sees
        the same shipped step (T-0048)."""
        if not reply_content or not isinstance(agent_meta, dict):
            return coach_turn_data
        finalize_next_step = str(agent_meta.get("next_step") or "").strip()
        generic_fillers = (
            "先做一个小动作",
            "把结果带回来",
            "do a small action",
            # ImplementationCoach rescue/fallback template shapes (T-0029):
            # unanchored by construction unless the target was derived from
            # this turn; prefer the reply's own labelled action.
            "压成一个很小的补丁目标",
            "先交付一个小而可复盘的",
        )
        weighted_length = sum(
            2 if ord(ch) > 0x2E80 else 1 for ch in finalize_next_step
        )
        looks_generic = (
            not finalize_next_step
            or any(filler in finalize_next_step for filler in generic_fillers)
            # CJK-aware short threshold (T-0036): a 6-11 hanzi step can be
            # fully concrete ("先跑一次测试"); counting hanzi as 2 keeps
            # it while still catching 6-letter English fragments.
            or weighted_length < 12
            or len(finalize_next_step) > 240
            or "```" in finalize_next_step
            or "## " in finalize_next_step
        )
        if not looks_generic:
            return coach_turn_data
        reply_action = visible_next_step(reply_content)
        if not reply_action:
            return coach_turn_data
        agent_meta["next_step"] = reply_action
        # T-0035: the pre-repair filler also lives in resume_thread and the
        # coach-turn summary; rebuild both from the repaired step or the
        # generic filler resurfaces next turn through the continuation path.
        repaired_resume = self.build_resume_thread_text(
            str(agent_meta.get("summary") or ""),
            reply_action,
            response_language=response_language,
        )
        if repaired_resume:
            agent_meta["resume_thread"] = repaired_resume
        if isinstance(coach_turn_data, dict):
            coach_turn_data = self.merge_agent_finalize_into_coach_turn(
                coach_turn_data,
                summary=str(agent_meta.get("summary") or "") or None,
                next_step=reply_action,
                resume_thread=repaired_resume or None,
            )
        return coach_turn_data

    def persist_recovered_plan_resume_after_turn(self, 
        *,
        workspace_id: str,
        request: TurnRequest | SessionMessageRequest,
        reply_content: str,
        agent_meta: dict[str, object] | None,
        coach_context: dict[str, object] | None,
        recovered_status: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        if getattr(request, "formal_plan_mutation", False):
            return None
        accepted = None
        if isinstance(coach_context, dict):
            context_recovery = coach_context.get("plan_runtime_recovery")
            if isinstance(context_recovery, dict) and context_recovery.get("recovered") is True:
                accepted = context_recovery
        if accepted is None:
            accepted = accept_plan_runtime_resume_request(
                getattr(request, "plan_runtime_recovery", None),
                recovered_status=recovered_status,
            )
        reply_facts = extract_structured_plan_runtime_facts(agent_meta)
        if accepted is None:
            scoped_status = plan_runtime_status_from_recovery(
                self.runtime.memory_service.recover_workspace_facts(workspace_id).get(PLAN_RUNTIME_KEY),
                workspace_id,
            )
            in_progress_status = next(
                (
                    candidate
                    for candidate in (scoped_status, recovered_status)
                    if isinstance(candidate, dict)
                    and str(candidate.get("resume_state") or "").replace("-", "_") == "in_progress"
                ),
                scoped_status or recovered_status,
            )
            accepted = accept_in_progress_plan_runtime_turn(
                intent=str(getattr(request, "intent", "") or ""),
                formal_plan_mutation=bool(getattr(request, "formal_plan_mutation", False)),
                recovered_status=in_progress_status,
            )
            if accepted is None or reply_facts is None:
                return None
        request_id = str(getattr(request, "request_id", "") or "").strip()
        stop_reason = str((agent_meta or {}).get("stop_reason") or "").strip()
        if not recovered_resume_turn_succeeded(reply_content=reply_content, stop_reason=stop_reason):
            return None
        return self.runtime.memory_service.persist_plan_runtime_resume(
            workspace_id,
            accepted=accepted,
            request_id=request_id,
            reply_facts=reply_facts,
        )

    def persist_response_reflection(self, 
        *,
        workspace_id: str,
        session_id: str | None,
        user_message: str | None = None,
        scenario: str,
        response_language: str | None,
        answer_mode: str | None,
        coach_defaults: CoachDefaults | dict[str, object] | None,
        response: SessionMessageResponse,
    ) -> None:
        response_agent_meta = response.agent_meta if isinstance(response.agent_meta, dict) else {}
        coach_support.persist_turn_reflection(self.coach_support_deps,
            workspace_id=workspace_id,
            session_id=session_id,
            user_message=user_message,
            scenario=scenario,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_defaults=coach_defaults,
            coach_turn_data={"coach_turn": response.coach_turn},
            stop_reason=str(response_agent_meta.get("stop_reason") or ""),
            recovered_stop_reason=str(response_agent_meta.get("recovered_stop_reason") or ""),
            local_sequence_fallback=bool(response_agent_meta.get("local_sequence_fallback")),
        )
