"""Card generation service with LLM-backed content generation.

Generates TrainingCardCandidateSnapshot instances from different sources:
conversation_gap, plan_requirement, resource_knowledge, practice_feedback,
dependency_mastery, review_due.

Each source method attempts LLM generation first. On failure, it falls back
to a deterministic template.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from ..core.models import (
    CardGenerationContext,
    TrainingCardCandidateSnapshot,
    TrainingCardTrustState,
)
from .card_generator_domains.defaults_and_templates import (
    _CARD_GENERATION_ATTEMPT_TIMEOUT_SECONDS as _CARD_GENERATION_ATTEMPT_TIMEOUT_SECONDS,
)
from .card_generator_domains.defaults_and_templates import (
    _CARD_STREAM_IDLE_TIMEOUT_SECONDS as _CARD_STREAM_IDLE_TIMEOUT_SECONDS,
)
from .card_generator_domains.defaults_and_templates import (
    _EXPLICIT_CARD_FALLBACK_COPY as _EXPLICIT_CARD_FALLBACK_COPY,
)
from .card_generator_domains.defaults_and_templates import (
    _FALLBACK_PROVENANCE_TEMPLATE_BY_LOCALE as _FALLBACK_PROVENANCE_TEMPLATE_BY_LOCALE,
)
from .card_generator_domains.defaults_and_templates import (
    _FALLBACK_REASON_BY_LOCALE as _FALLBACK_REASON_BY_LOCALE,
)
from .card_generator_domains.defaults_and_templates import (
    _GUIDED_SCENARIO_PACK_CATALOG as _GUIDED_SCENARIO_PACK_CATALOG,
)
from .card_generator_domains.defaults_and_templates import (
    _GUIDED_SCENARIO_PACK_DEBUG as _GUIDED_SCENARIO_PACK_DEBUG,
)
from .card_generator_domains.defaults_and_templates import (
    _GUIDED_SCENARIO_PACK_DEPENDENCY as _GUIDED_SCENARIO_PACK_DEPENDENCY,
)
from .card_generator_domains.defaults_and_templates import (
    _GUIDED_SCENARIO_PACK_FUNCTION as _GUIDED_SCENARIO_PACK_FUNCTION,
)
from .card_generator_domains.defaults_and_templates import (
    _GUIDED_SCENARIO_PACK_REMOTE as _GUIDED_SCENARIO_PACK_REMOTE,
)
from .card_generator_domains.defaults_and_templates import (
    _GUIDED_SCENARIO_PACK_RESOURCE as _GUIDED_SCENARIO_PACK_RESOURCE,
)
from .card_generator_domains.defaults_and_templates import (
    _PROVIDER_FAILURE_DETAIL_BY_LOCALE as _PROVIDER_FAILURE_DETAIL_BY_LOCALE,
)
from .card_generator_domains.defaults_and_templates import (
    _PROVIDER_QUOTA_DETAIL_BY_LOCALE as _PROVIDER_QUOTA_DETAIL_BY_LOCALE,
)
from .card_generator_domains.defaults_and_templates import (
    _PROVIDER_UNAVAILABLE_DETAIL_BY_LOCALE as _PROVIDER_UNAVAILABLE_DETAIL_BY_LOCALE,
)
from .card_generator_domains.defaults_and_templates import (
    _RESOURCE_BLOCKING_FLAGS as _RESOURCE_BLOCKING_FLAGS,
)
from .card_generator_domains.defaults_and_templates import (
    _SOURCE_MAP as _SOURCE_MAP,
)
from .card_generator_domains.defaults_and_templates import (
    _WHY_NOW_MESSAGES as _WHY_NOW_MESSAGES,
)
from .card_generator_domains.defaults_and_templates import (
    _WHY_NOW_MESSAGES_BY_LOCALE as _WHY_NOW_MESSAGES_BY_LOCALE,
)
from .card_generator_domains.defaults_and_templates import (
    _WHY_NOW_MESSAGES_ZH as _WHY_NOW_MESSAGES_ZH,
)
from .card_generator_domains.defaults_and_templates import (
    CardGenerationProviderFailure as CardGenerationProviderFailure,
)
from .card_generator_domains.defaults_and_templates import (
    CardGenerationStreamError as CardGenerationStreamError,
)
from .card_generator_domains.defaults_and_templates import (
    CardGenerationStreamEvent as CardGenerationStreamEvent,
)
from .card_generator_domains.defaults_and_templates import (
    CardGenerationStreamInterrupted as CardGenerationStreamInterrupted,
)
from .card_generator_domains.defaults_and_templates import (
    _apply_context_pedagogy_controls as _apply_context_pedagogy_controls,
)
from .card_generator_domains.defaults_and_templates import (
    _context_blob as _context_blob,
)
from .card_generator_domains.defaults_and_templates import (
    _derive_resource_trust_state as _derive_resource_trust_state,
)
from .card_generator_domains.defaults_and_templates import (
    _ensure_flash_contract as _ensure_flash_contract,
)
from .card_generator_domains.defaults_and_templates import (
    _fallback_provenance_copy as _fallback_provenance_copy,
)
from .card_generator_domains.defaults_and_templates import (
    _feedback_dict as _feedback_dict,
)
from .card_generator_domains.defaults_and_templates import (
    _flash_defaults as _flash_defaults,
)
from .card_generator_domains.defaults_and_templates import (
    _guided_fact_text as _guided_fact_text,
)
from .card_generator_domains.defaults_and_templates import (
    _guided_pack_focus as _guided_pack_focus,
)
from .card_generator_domains.defaults_and_templates import (
    _guided_pack_skill as _guided_pack_skill,
)
from .card_generator_domains.defaults_and_templates import (
    _load_guided_scenario_pack_catalog as _load_guided_scenario_pack_catalog,
)
from .card_generator_domains.defaults_and_templates import (
    _localized_8 as _localized_8,
)
from .card_generator_domains.defaults_and_templates import (
    _localized_string as _localized_string,
)
from .card_generator_domains.defaults_and_templates import (
    _localized_string_list as _localized_string_list,
)
from .card_generator_domains.defaults_and_templates import (
    _localized_text as _localized_text,
)
from .card_generator_domains.defaults_and_templates import (
    _localized_why_now as _localized_why_now,
)
from .card_generator_domains.defaults_and_templates import (
    _match_guided_scenario_pack as _match_guided_scenario_pack,
)
from .card_generator_domains.defaults_and_templates import (
    _normalize_card_locale as _normalize_card_locale,
)
from .card_generator_domains.defaults_and_templates import (
    _normalize_function_guidance_card as _normalize_function_guidance_card,
)
from .card_generator_domains.defaults_and_templates import (
    _normalize_function_guidance_terms as _normalize_function_guidance_terms,
)
from .card_generator_domains.defaults_and_templates import (
    _pick_localized_value as _pick_localized_value,
)
from .card_generator_domains.defaults_and_templates import (
    _practice_defaults as _practice_defaults,
)
from .card_generator_domains.defaults_and_templates import (
    _prefers_chinese as _prefers_chinese,
)
from .card_generator_domains.defaults_and_templates import (
    _provider_failure_reason as _provider_failure_reason,
)
from .card_generator_domains.defaults_and_templates import (
    _resource_knowledge_evidence as _resource_knowledge_evidence,
)
from .card_generator_domains.defaults_and_templates import (
    _string_list as _string_list,
)
from .card_generator_domains.defaults_and_templates import (
    _subject_lane as _subject_lane,
)
from .card_generator_domains.defaults_and_templates import (
    _subject_taxonomy as _subject_taxonomy,
)
from .card_generator_domains.guided_scenario_packs import (
    _DEPENDENCY_GENERIC_IDENTIFIERS as _DEPENDENCY_GENERIC_IDENTIFIERS,
)
from .card_generator_domains.guided_scenario_packs import (
    _MULTI_SCOPE_SEPARATOR as _MULTI_SCOPE_SEPARATOR,
)
from .card_generator_domains.guided_scenario_packs import (
    _UNVERIFIED_COMPLETION_CLAIM as _UNVERIFIED_COMPLETION_CLAIM,
)
from .card_generator_domains.guided_scenario_packs import (
    _apply_guided_workspace_facts as _apply_guided_workspace_facts,
)
from .card_generator_domains.guided_scenario_packs import (
    _build_guided_scenario_pack_card as _build_guided_scenario_pack_card,
)
from .card_generator_domains.guided_scenario_packs import (
    _dependency_identifier_candidates as _dependency_identifier_candidates,
)
from .card_generator_domains.guided_scenario_packs import (
    _enforce_learning_loop_contract as _enforce_learning_loop_contract,
)
from .card_generator_domains.guided_scenario_packs import (
    _ensure_practice_contract as _ensure_practice_contract,
)
from .card_generator_domains.guided_scenario_packs import (
    _guided_context_for_pack as _guided_context_for_pack,
)
from .card_generator_domains.guided_scenario_packs import (
    _guided_fact_path as _guided_fact_path,
)
from .card_generator_domains.guided_scenario_packs import (
    _guided_function_anchor as _guided_function_anchor,
)
from .card_generator_domains.guided_scenario_packs import (
    _guided_missing_fact_card as _guided_missing_fact_card,
)
from .card_generator_domains.guided_scenario_packs import (
    _guided_pack_label as _guided_pack_label,
)
from .card_generator_domains.guided_scenario_packs import (
    _guided_remote_name as _guided_remote_name,
)
from .card_generator_domains.guided_scenario_packs import (
    _guided_scenario_skeleton_source as _guided_scenario_skeleton_source,
)
from .card_generator_domains.guided_scenario_packs import (
    _guided_text as _guided_text,
)
from .card_generator_domains.guided_scenario_packs import (
    _guided_unique_items as _guided_unique_items,
)
from .card_generator_domains.guided_scenario_packs import (
    _make_guided_scenario_pack_card_from_catalog as _make_guided_scenario_pack_card_from_catalog,
)
from .card_generator_domains.guided_scenario_packs import (
    _matches_dependency_usage as _matches_dependency_usage,
)
from .card_generator_domains.guided_scenario_packs import (
    _single_problem_focus as _single_problem_focus,
)
from .card_generator_domains.guided_scenario_packs import (
    _truthful_completion_copy as _truthful_completion_copy,
)
from .card_generator_domains.guided_scenario_packs import (
    _verified_dependency_usage as _verified_dependency_usage,
)
from .card_generator_domains.prompt_and_validation import (
    _ACCEPTANCE_BACKTICK_PATTERN as _ACCEPTANCE_BACKTICK_PATTERN,
)
from .card_generator_domains.prompt_and_validation import (
    _ACCEPTANCE_DOTTED_SYMBOL_PATTERN as _ACCEPTANCE_DOTTED_SYMBOL_PATTERN,
)
from .card_generator_domains.prompt_and_validation import (
    _ACCEPTANCE_EXTRACTION_IDENTIFIER as _ACCEPTANCE_EXTRACTION_IDENTIFIER,
)
from .card_generator_domains.prompt_and_validation import (
    _ACCEPTANCE_KNOWN_SYMBOL_TOKENS as _ACCEPTANCE_KNOWN_SYMBOL_TOKENS,
)
from .card_generator_domains.prompt_and_validation import (
    _ACCEPTANCE_MAX_CRITERIA as _ACCEPTANCE_MAX_CRITERIA,
)
from .card_generator_domains.prompt_and_validation import (
    _ACCEPTANCE_MAX_SYMBOLS as _ACCEPTANCE_MAX_SYMBOLS,
)
from .card_generator_domains.prompt_and_validation import (
    _ACCEPTANCE_MIN_CRITERIA as _ACCEPTANCE_MIN_CRITERIA,
)
from .card_generator_domains.prompt_and_validation import (
    _CARD_CODE_SYMBOL_PATTERN as _CARD_CODE_SYMBOL_PATTERN,
)
from .card_generator_domains.prompt_and_validation import (
    _CARD_GENERATION_MAX_TOKENS as _CARD_GENERATION_MAX_TOKENS,
)
from .card_generator_domains.prompt_and_validation import (
    _CARD_IDENTIFIER_PATTERN as _CARD_IDENTIFIER_PATTERN,
)
from .card_generator_domains.prompt_and_validation import (
    _CARD_LANGUAGE_MARKERS as _CARD_LANGUAGE_MARKERS,
)
from .card_generator_domains.prompt_and_validation import (
    _FLASH_REQUIRED_FIELDS as _FLASH_REQUIRED_FIELDS,
)
from .card_generator_domains.prompt_and_validation import (
    _LLM_CARD_FIELD_MAP as _LLM_CARD_FIELD_MAP,
)
from .card_generator_domains.prompt_and_validation import (
    _PLAN_FILE_SYMBOL_TOKENS as _PLAN_FILE_SYMBOL_TOKENS,
)
from .card_generator_domains.prompt_and_validation import (
    _PRACTICE_REQUIRED_FIELDS as _PRACTICE_REQUIRED_FIELDS,
)
from .card_generator_domains.prompt_and_validation import (
    _PROJECT_CARD_CORE_PROSE as _PROJECT_CARD_CORE_PROSE,
)
from .card_generator_domains.prompt_and_validation import (
    _ZH_CARD_PROSE_FIELDS as _ZH_CARD_PROSE_FIELDS,
)
from .card_generator_domains.prompt_and_validation import (
    _ZH_CARD_TECHNICAL_WORDS as _ZH_CARD_TECHNICAL_WORDS,
)
from .card_generator_domains.prompt_and_validation import (
    _acceptance_criteria_for_payload as _acceptance_criteria_for_payload,
)
from .card_generator_domains.prompt_and_validation import (
    _build_prompt as _build_prompt,
)
from .card_generator_domains.prompt_and_validation import (
    _contains_chinese_text as _contains_chinese_text,
)
from .card_generator_domains.prompt_and_validation import (
    _criterion_has_code_signal as _criterion_has_code_signal,
)
from .card_generator_domains.prompt_and_validation import (
    _extract_acceptance_symbols as _extract_acceptance_symbols,
)
from .card_generator_domains.prompt_and_validation import (
    _generation_max_tokens as _generation_max_tokens,
)
from .card_generator_domains.prompt_and_validation import (
    _has_expected_card_language as _has_expected_card_language,
)
from .card_generator_domains.prompt_and_validation import (
    _has_requested_locale_prose as _has_requested_locale_prose,
)
from .card_generator_domains.prompt_and_validation import (
    _indexed_file_practice_material as _indexed_file_practice_material,
)
from .card_generator_domains.prompt_and_validation import (
    _indexed_file_practice_target as _indexed_file_practice_target,
)
from .card_generator_domains.prompt_and_validation import (
    _is_short_technical_card_text as _is_short_technical_card_text,
)
from .card_generator_domains.prompt_and_validation import (
    _is_zh_card_prose as _is_zh_card_prose,
)
from .card_generator_domains.prompt_and_validation import (
    _iter_card_prose as _iter_card_prose,
)
from .card_generator_domains.prompt_and_validation import (
    _localized_fallback_value as _localized_fallback_value,
)
from .card_generator_domains.prompt_and_validation import (
    _make_guided_scenario_pack_card as _make_guided_scenario_pack_card,
)
from .card_generator_domains.prompt_and_validation import (
    _model_card_from_fields as _model_card_from_fields,
)
from .card_generator_domains.prompt_and_validation import (
    _normalize_card_code_symbol as _normalize_card_code_symbol,
)
from .card_generator_domains.prompt_and_validation import (
    _parse_llm_json as _parse_llm_json,
)
from .card_generator_domains.prompt_and_validation import (
    _plan_acceptance_criteria as _plan_acceptance_criteria,
)
from .card_generator_domains.prompt_and_validation import (
    _plan_file_symbols as _plan_file_symbols,
)
from .card_generator_domains.prompt_and_validation import (
    _replace_mismatched_card_prose as _replace_mismatched_card_prose,
)
from .card_generator_domains.prompt_and_validation import (
    _resource_reliability_note as _resource_reliability_note,
)
from .card_generator_domains.prompt_and_validation import (
    _synthesize_acceptance_criteria as _synthesize_acceptance_criteria,
)
from .card_generator_domains.prompt_and_validation import (
    _utc_now_iso as _utc_now_iso,
)
from .card_generator_domains.prompt_and_validation import (
    _validate_fields as _validate_fields,
)
from .card_generator_domains.prompt_and_validation import (
    derive_acceptance_criteria as derive_acceptance_criteria,
)

if TYPE_CHECKING:
    from ..core.event_ledger import EventLedgerService

logger = logging.getLogger(__name__)


class CardGenerationService:
    """Generates training card candidates from various sources.

    When a ProviderService is supplied, each source handler attempts to use
    the LLM to generate richer content. On failure (LLM unavailable, parse
    error, missing fields), the handler falls back to a deterministic template.
    """

    def __init__(self, provider_service: Any | None = None, event_ledger: EventLedgerService | None = None) -> None:
        self._provider = provider_service
        self._event_ledger = event_ledger
        self._pending_llm_failure_reasons: dict[tuple[int, str, str], str] = {}

    def generate_card(
        self,
        source: str,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
        fallback_reason: str | None = None,
    ) -> TrainingCardCandidateSnapshot:
        """Main entry point — dispatches to the appropriate source handler."""
        guided_pack = _match_guided_scenario_pack(
            context, source=source, allow_resource_content=allow_llm and self._provider is not None,
        )
        if guided_pack:
            # Guided cards must never let a successful provider response replace the
            # verified-workspace-facts gate. This includes legacy conversation sources.
            card = _make_guided_scenario_pack_card(
                guided_pack,
                context,
                context.card_type or "practice",
                context.response_language or "en-US",
            )
            if source == "plan_requirement" and context.plan_stage_id:
                card.plan_links = [context.plan_stage_id]
        else:
            handler = {
                "conversation_gap": self._generate_from_conversation_gap,
                "plan_requirement": self._generate_from_plan_requirement,
                "resource_knowledge": self._generate_from_resource_knowledge,
                "practice_feedback": self._generate_from_practice_feedback,
                "dependency_mastery": self._generate_from_dependency_mastery,
                "review_due": self._generate_from_review_due,
            }.get(source)
            if handler is None:
                if allow_llm and self._provider is not None:
                    raise CardGenerationProviderFailure(
                        "unknown_source",
                        response_language=context.response_language,
                    )
                card = self._generate_stub(context, allow_llm=False)
            else:
                card = handler(context, allow_llm=allow_llm)
        pending_fallback_reason = self._take_llm_failure(
            context,
            source,
            context.card_type or "practice",
        )
        if allow_llm and not guided_pack and pending_fallback_reason and self._provider is not None:
            raise CardGenerationProviderFailure(
                pending_fallback_reason,
                response_language=context.response_language,
            )
        return self._finalize_card(
            card,
            source,
            context,
            fallback_reason=fallback_reason or pending_fallback_reason,
        )

    def _finalize_card(
        self,
        card: TrainingCardCandidateSnapshot,
        source: str,
        context: CardGenerationContext,
        *,
        fallback_reason: str | None = None,
        generation_source: str | None = None,
    ) -> TrainingCardCandidateSnapshot:
        """Apply shared card contracts and record the creation event."""
        # Ensure card_id is a full UUID (36 chars), not the model default short id
        if not card.card_id or len(card.card_id) < 36:
            card.card_id = str(uuid4())
        card.status = card.status or "candidate"
        card.created_from = _SOURCE_MAP.get(source, "conversation")
        if not card.source_chain:
            card.source_chain = ["card_generation_router"]
        if source == "resource_knowledge" and (
            card.scenario_pack == _GUIDED_SCENARIO_PACK_RESOURCE
            or _match_guided_scenario_pack(
                context, source=source, allow_resource_content=self._provider is not None,
            ) is None
        ):
            grounded = _apply_guided_workspace_facts(
                card, pack=_GUIDED_SCENARIO_PACK_RESOURCE, context=context,
            )
            card = card.model_copy(update={
                "source_chain": grounded.source_chain, "trust_state": grounded.trust_state,
                "scenario_pack": _GUIDED_SCENARIO_PACK_RESOURCE,
            })
        card = _ensure_flash_contract(card, context, source)
        card = _ensure_practice_contract(card, context)
        card = _replace_mismatched_card_prose(card, context)
        card = _enforce_learning_loop_contract(card, context)
        current_path = _guided_fact_path(context.current_file_path)
        indexed_target = _indexed_file_practice_target(context, source, card.card_type)
        if indexed_target:
            # One archived source is applied to the exact IDE file passed by
            # the host. Generated names cannot redirect its verification.
            card = card.model_copy(update={"files_to_touch": [indexed_target]})
        elif card.card_type == "practice" and current_path and (
            context.current_file_content or context.current_file_excerpt
        ) and source in {"conversation_gap", "practice_feedback"}:
            # The host supplied an exact target; a model-returned basename must
            # not accidentally select a same-named file at the workspace root.
            basename = current_path.replace("\\", "/").rsplit("/", 1)[-1]
            targets = [
                current_path if target.replace("\\", "/") == basename else target
                for target in card.files_to_touch
            ]
            card = card.model_copy(update={"files_to_touch": targets or [current_path]})
        card.why_now = card.why_now or _WHY_NOW_MESSAGES.get(source, f"Fallback card generated from {source or 'conversation_gap'}.")
        card.why_now = _localized_why_now(source, card.why_now, context.response_language)
        creation_payload: dict[str, Any] = {
            "card_id": card.card_id,
            "card_type": card.card_type,
            "created_from": card.created_from,
            "title": card.title,
            "focus_area": card.focus_area,
            "target_skill": card.target_skill,
        }
        if context.resource_id and context.resource_version_id and context.resource_content_hash:
            pinned_source = {
                "resource_id": context.resource_id,
                "resource_version_id": context.resource_version_id,
                "resource_content_hash": context.resource_content_hash,
                "resource_location": context.resource_location,
            }
            card = card.model_copy(update=pinned_source)
            creation_payload.update(pinned_source)
        if fallback_reason:
            source_marker, detail = _fallback_provenance_copy(
                fallback_reason,
                context.response_language,
            )
            source_chain = list(card.source_chain)
            if source_marker not in source_chain:
                source_chain.append(source_marker)
            card = card.model_copy(
                update={
                    "generation_source": "deterministic_fallback",
                    "generation_status": "degraded",
                    "generation_fallback_reason": fallback_reason,
                    "generation_recoverable": True,
                    "provider_attempted": True,
                    "model_output_valid": False,
                    "source_chain": source_chain,
                    "why_now": f"{card.why_now} {detail}".strip(),
                }
            )
            creation_payload.update(
                {
                    "generation_source": "deterministic_fallback",
                    "generation_status": "degraded",
                    "generation_fallback_reason": fallback_reason,
                    "generation_recoverable": True,
                }
            )
        elif generation_source:
            card = card.model_copy(
                update={
                    "generation_source": generation_source,
                    "generation_status": "complete",
                    "generation_recoverable": False,
                }
            )
            creation_payload.update(
                {
                    "generation_source": generation_source,
                    "generation_status": "complete",
                    "generation_recoverable": False,
                }
            )
        now = _utc_now_iso()
        if not card.created_at:
            card.created_at = now
        if not card.updated_at:
            card.updated_at = now
        card = _apply_context_pedagogy_controls(card, context)
        # Goal F2 guarantee: every card leaves the generator with symbol-anchored
        # acceptance criteria. Paths that never set them (governed scenario-pack
        # templates, catalog cards, unknown sources) are backfilled here; cards
        # that already carry criteria (LLM field map, deterministic templates)
        # are never overwritten.
        if not card.acceptance_criteria:
            card = card.model_copy(
                update={
                    "acceptance_criteria": derive_acceptance_criteria(
                        card.deliverable,
                        card.grading_rubric,
                        context.target_skill or context.focus_area or card.target_skill or "",
                        language=context.response_language,
                    )
                }
            )
        if not card.project_id and context.workspace_id:
            card = card.model_copy(update={"project_id": context.workspace_id})

        # §13.21 Record card creation event in unified event ledger
        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "card_candidate_created",
                actor="system",
                scope="card",
                project_id=context.workspace_id,
                source_chain=["card_generation_router", source],
                payload_ref=creation_payload,
                before_state_ref={},
                after_state_ref={
                    "card_id": card.card_id,
                    "status": card.status,
                },
                reversibility="reversible",
                audit_note=f"Card candidate '{card.card_id}' created from '{source}'",
            )

        return card

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_card(
        self,
        card: TrainingCardCandidateSnapshot,
        learner_state: dict,
    ) -> float:
        """Priority scoring in [0.0, 1.0].

        Skeleton heuristic: base 0.5, boost for explicit target_skill, boost
        for review_due source, penalise cards without a focus area.
        """
        score = 0.5
        if card.target_skill:
            score += 0.15
        if card.created_from == "review_due":
            score += 0.2
        if not card.focus_area:
            score -= 0.15
        # P1.4 candidate management: the learner's explicit priority and
        # importance tilt routing — the learner decides what is worth keeping
        # and practising first. Bounded so management never overrides the
        # status/weakness signals entirely.
        score += 0.04 * max(-5, min(5, int(getattr(card, "card_priority", 0) or 0)))
        if bool(getattr(card, "important", False)):
            score += 0.05
        # Boost if learner has prior weakness in this area.
        weaknesses = learner_state.get("weaknesses", [])
        if isinstance(weaknesses, list) and card.focus_area in weaknesses:
            score += 0.15
        return max(0.0, min(1.0, score))

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def _try_llm_generation(
        self,
        context: CardGenerationContext,
        source: str,
        card_type: str,
    ) -> TrainingCardCandidateSnapshot | None:
        """Try generating a card via LLM. Returns None on any failure.

        Reasoning-first providers frequently spend the response budget on
        hidden reasoning and return malformed JSON or field-incomplete cards,
        so each request gets exactly one silent synchronous retry at a higher
        temperature before any failure is recorded or surfaced.
        """
        provider = self._provider
        if provider is None:
            return None

        def _invoke_provider(temperature: float) -> str:
            """Run one async chat completion synchronously (thread off a live loop)."""
            import asyncio
            import concurrent.futures

            # Run the async LLM call synchronously.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            request = provider.chat_completion(
                messages,
                temperature=temperature,
                max_tokens=_generation_max_tokens(provider),
            )

            async def _bounded_request() -> str:
                return await asyncio.wait_for(
                    request,
                    timeout=_CARD_GENERATION_ATTEMPT_TIMEOUT_SECONDS,
                )

            if loop and loop.is_running():
                # We're already in an async context — use nest_asyncio or
                # run in a thread. For simplicity, use thread.
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, _bounded_request()).result()
            return asyncio.run(_bounded_request())

        try:
            messages = self._llm_messages(context, source, card_type)
            required = (
                _PRACTICE_REQUIRED_FIELDS
                if card_type == "practice"
                else _FLASH_REQUIRED_FIELDS
            )
            failure_reason = "exception"
            for attempt, temperature in enumerate((0.7, 0.9), start=1):
                try:
                    raw = _invoke_provider(temperature)
                except Exception as exc:
                    failure_reason = _provider_failure_reason(exc) or "exception"
                    if failure_reason != "exception":
                        # An outage is operationally different from malformed
                        # model output; keep it visible without upstream text.
                        logger.warning(
                            "LLM card generation provider failure for source=%s (attempt %d): %s",
                            source,
                            attempt,
                            failure_reason,
                        )
                    else:
                        logger.debug(
                            "LLM card generation failed for source=%s (attempt %d)",
                            source,
                            attempt,
                            exc_info=True,
                        )
                    continue

                data = _parse_llm_json(raw)
                if data is None:
                    logger.warning(
                        "LLM response was not valid JSON for source=%s (attempt %d)", source, attempt,
                    )
                    failure_reason = "invalid_json"
                    continue

                if not _validate_fields(data, required):
                    logger.warning(
                        "LLM response missing required fields for source=%s (attempt %d)",
                        source,
                        attempt,
                    )
                    failure_reason = "missing_required_fields"
                    continue

                if not _has_expected_card_language(
                    data, context.response_language, project_checks=bool(context.project_verification_steps),
                ):
                    logger.warning(
                        "LLM response does not match requested card language for source=%s (attempt %d)",
                        source,
                        attempt,
                    )
                    failure_reason = "language_mismatch"
                    continue

                try:
                    return _model_card_from_fields(data, context, source, card_type)
                except Exception:
                    logger.warning(
                        "LLM response could not be converted to a card for source=%s (attempt %d)",
                        source,
                        attempt,
                    )
                    failure_reason = "invalid_card"
                    continue

            self._record_llm_generation_failure(context, source, card_type, failure_reason)
            return None

        except Exception:
            logger.debug("LLM card generation failed for source=%s", source, exc_info=True)
            self._record_llm_generation_failure(
                context,
                source,
                card_type,
                "exception",
            )
            return None

    def _llm_failure_key(
        self,
        context: CardGenerationContext,
        source: str,
        card_type: str,
    ) -> tuple[int, str, str]:
        return (id(context), source, card_type)

    def _remember_llm_failure(
        self,
        context: CardGenerationContext,
        source: str,
        card_type: str,
        reason: str,
    ) -> None:
        self._pending_llm_failure_reasons[self._llm_failure_key(context, source, card_type)] = reason

    def _take_llm_failure(
        self,
        context: CardGenerationContext,
        source: str,
        card_type: str,
    ) -> str | None:
        return self._pending_llm_failure_reasons.pop(
            self._llm_failure_key(context, source, card_type),
            None,
        )

    def _record_llm_generation_failure(
        self,
        context: CardGenerationContext,
        source: str,
        card_type: str,
        reason: str,
    ) -> None:
        self._remember_llm_failure(context, source, card_type, reason)
        if self._event_ledger is not None:
            self._event_ledger.record_event(
                "card_generation_failed",
                actor="system",
                scope="card",
                project_id=context.workspace_id,
                payload_ref={"source": source, "card_type": card_type, "reason": reason},
                reversibility="irreversible",
                audit_note=f"Card generation failed ({reason}) for source='{source}'",
            )

    def _build_card_from_llm_data(
        self,
        data: dict[str, Any] | None,
        context: CardGenerationContext,
        source: str,
        card_type: str,
    ) -> TrainingCardCandidateSnapshot | None:
        """Validate one provider payload and convert it into a card candidate."""
        if data is None:
            logger.warning("LLM response was not valid JSON for source=%s", source)
            self._record_llm_generation_failure(context, source, card_type, "invalid_json")
            return None

        required = _PRACTICE_REQUIRED_FIELDS if card_type == "practice" else _FLASH_REQUIRED_FIELDS
        if not _validate_fields(data, required):
            logger.warning("LLM response missing required fields for source=%s", source)
            self._record_llm_generation_failure(context, source, card_type, "missing_required_fields")
            return None
        if not _has_expected_card_language(
            data, context.response_language, project_checks=bool(context.project_verification_steps),
        ):
            logger.warning("LLM response does not match requested card language for source=%s", source)
            self._record_llm_generation_failure(context, source, card_type, "language_mismatch")
            return None

        try:
            return _model_card_from_fields(data, context, source, card_type)
        except Exception:
            logger.warning("LLM response could not be converted to a card for source=%s", source)
            self._record_llm_generation_failure(context, source, card_type, "invalid_card")
            return None

    def _llm_messages(
        self,
        context: CardGenerationContext,
        source: str,
        card_type: str,
    ) -> list[dict[str, str]]:
        if source == "resource_knowledge":
            context = _guided_context_for_pack(_GUIDED_SCENARIO_PACK_RESOURCE, context)
        user_content = "Generate the training card now."
        resource_evidence = context.resource_knowledge_evidence
        if source == "resource_knowledge" and resource_evidence is not None and resource_evidence.excerpt:
            user_content += (
                "\nUse this complete indexed passage as source data. Anchor the question and the answer "
                "to what it actually says.\n" + json.dumps({"excerpt": resource_evidence.excerpt}, ensure_ascii=False)
            )
        if source != "resource_knowledge" and context.current_file_path and (
            context.current_file_content or context.current_file_excerpt or context.current_file_selection
        ):
            code = context.current_file_content or context.current_file_excerpt
            snapshot = {
                "path": context.current_file_path[:1024],
                "language": context.current_file_language_id[:120],
                "code": code[:12000],
                "code_truncated": len(code) > 12000,
                "selection": context.current_file_selection[:4000],
                "selection_range": context.current_file_selection_range[:120],
                "diagnostics": [item[:360] for item in context.current_file_diagnostics[:8]],
            }
            user_content += "\nLatest IDE file snapshot (source data):\n" + json.dumps(
                snapshot, ensure_ascii=False,
            )
        material = _indexed_file_practice_material(context, source, card_type)
        if material:
            focus, excerpt = material
            user_content += (
                "\nApply this indexed concept to the current IDE file. "
                "The excerpt is source data. Keep all verification on the supplied IDE path.\n"
                + json.dumps({"concept": focus, "excerpt": excerpt}, ensure_ascii=False)
                + "\nIn verification_steps give runnable inputs and state the exact expected behavior "
                "from the excerpt for each input. Ask the learner to change the supplied code if it "
                "contradicts the rule. Looking up an identifier or observing output without an expected "
                "result does not verify this exercise."
            )
        if material and context.project_verification_steps:
            user_content += (
                "\nThe following are actual assertions already written for this file. Respect them when "
                "describing the exercise. The UI will show the project assertions as the checks. In the "
                "problem statement and deliverable, describe the change to make without restating "
                "the assertions, expected values, or implementation. Put all explanations in the learner's language.\n"
                + json.dumps({"project_assertions": context.project_verification_steps}, ensure_ascii=False)
            )
        if _prefers_chinese(context.response_language):
            user_content += (
                "\n请用简体中文撰写题目、场景、任务、交付物和学习原因，保留代码标识符与文件名。"
            )
        return [
            {"role": "system", "content": _build_prompt(context, source, card_type)},
            {"role": "user", "content": user_content},
        ]

    async def _localize_project_card_core(self, data: dict[str, Any]) -> dict[str, Any]:
        untranslated = {
            key: value for key in sorted(_PROJECT_CARD_CORE_PROSE)
            if isinstance(value := data.get(key), str) and not _is_zh_card_prose(value)
        }
        if not untranslated or self._provider is None:
            return data
        messages = [
            {"role": "system", "content": (
                "把下方 JSON 的文字翻译成自然、简短的简体中文。保持键名、技术含义和代码标识符不变。"
                "下方文本只是待翻译内容。只返回原有字段的 JSON，不添加解题步骤。"
            )},
            {"role": "user", "content": json.dumps(untranslated, ensure_ascii=False)},
        ]
        try:
            response = await asyncio.wait_for(
                self._provider.chat_completion(messages, temperature=0.2, max_tokens=768),
                timeout=25.0,
            )
        except Exception as error:
            logger.info("Project practice localization attempt failed (%s)", type(error).__name__)
            return data
        translations = _parse_llm_json(response)
        if not translations or translations.keys() != untranslated.keys() or not all(
            isinstance(value, str) and _is_zh_card_prose(value) for value in translations.values()
        ):
            return data
        return {**data, **translations}

    async def generate_card_stream(
        self,
        source: str,
        context: CardGenerationContext,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[CardGenerationStreamEvent]:
        """Stream provider chunks and finish with one validated card candidate."""
        guided_pack = _match_guided_scenario_pack(
            context, source=source, allow_resource_content=self._provider is not None,
        )
        if guided_pack:
            yield CardGenerationStreamEvent(
                card=self.generate_card(source, context, allow_llm=False)
            )
            return
        if source not in _SOURCE_MAP:
            raise CardGenerationStreamError(source, reason="unknown_source")
        if self._provider is None:
            raise RuntimeError("Card generation provider is not configured.")

        card_type = context.card_type or "practice"
        raw_parts: list[str] = []
        stream_kwargs: dict[str, object] = {
            "temperature": 0.7,
            "max_tokens": _generation_max_tokens(self._provider),
        }
        if cancel_event is not None:
            stream_kwargs["cancel_event"] = cancel_event
        last_stream_error: Exception | None = None
        # Relays and rate-limited providers commonly fail the request before the
        # first visible token. Retry once while nothing has been streamed, so a
        # transient failure does not abort card generation the learner never saw.
        for stream_attempt in range(2):
            try:
                stream_iterator = self._provider.chat_completion_stream(
                    self._llm_messages(context, source, card_type),
                    **stream_kwargs,
                ).__aiter__()
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            stream_iterator.__anext__(),
                            timeout=_CARD_STREAM_IDLE_TIMEOUT_SECONDS,
                        )
                    except StopAsyncIteration:
                        break
                    if not isinstance(chunk, str) or not chunk:
                        continue
                    raw_parts.append(chunk)
                    yield CardGenerationStreamEvent(chunk=chunk)
                last_stream_error = None
                break
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError as exc:
                # No token for a full idle window: the provider is stalled, not
                # producing a partial card. The caller gets a deterministic
                # fallback below instead of hanging indefinitely. A timeout
                # after visible chunks is still an honest interruption.
                last_stream_error = exc
                break
            except Exception as exc:
                last_stream_error = exc
                if stream_attempt == 0 and not raw_parts:
                    await asyncio.sleep(1.5)
                    continue
                break
        if last_stream_error is not None:
            if isinstance(last_stream_error, asyncio.TimeoutError) and not raw_parts:
                # Explicit deterministic fallback only for a stalled stream: no
                # model text was visible, so a local card cannot conflict with
                # streamed content. A provider error stays an honest failure
                # (the UI keeps the retry path); it must not be disguised as a
                # model-authored or fallback card.
                fallback_source = (
                    "plan_requirement"
                    if str(context.plan_stage_id or "").strip()
                    else source
                )
                yield CardGenerationStreamEvent(
                    card=self.generate_card(
                        fallback_source,
                        context,
                        allow_llm=False,
                        fallback_reason="provider_stalled",
                    )
                )
                return
            if self._event_ledger is not None:
                self._event_ledger.record_event(
                    "card_generation_failed",
                    actor="system",
                    scope="card",
                    project_id=context.workspace_id,
                    payload_ref={
                        "source": source,
                        "card_type": card_type,
                        "reason": "stream_interrupted",
                        "retryable": True,
                        "recoverable": True,
                    },
                    reversibility="irreversible",
                    audit_note=(
                        "Card generation stream interrupted before validation; "
                        f"source='{source}' can be retried."
                    ),
                )
            raise CardGenerationStreamError(source) from last_stream_error

        raw_payload = "".join(raw_parts)
        parsed_payload = _parse_llm_json(raw_payload)
        if (
            parsed_payload and card_type == "practice" and context.project_verification_steps
            and _prefers_chinese(context.response_language)
            and _validate_fields(parsed_payload, _PRACTICE_REQUIRED_FIELDS)
            and (cancel_event is None or not cancel_event.is_set())
        ):
            parsed_payload = await self._localize_project_card_core(parsed_payload)
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError
        card = self._build_card_from_llm_data(
            parsed_payload,
            context,
            source,
            card_type,
        )
        if card is None:
            # Stream parsing failures use the deterministic source handler without
            # invoking the provider a second time.
            if parsed_payload is None:
                fallback_reason = "invalid_json"
            elif not _validate_fields(
                parsed_payload,
                _PRACTICE_REQUIRED_FIELDS
                if card_type == "practice"
                else _FLASH_REQUIRED_FIELDS,
            ):
                fallback_reason = "missing_required_fields"
            elif not _has_expected_card_language(
                parsed_payload, context.response_language, project_checks=bool(context.project_verification_steps),
            ):
                fallback_reason = "language_mismatch"
            else:
                fallback_reason = "invalid_card"
            if guided_pack:
                card = self.generate_card(
                    source,
                    context,
                    allow_llm=False,
                    fallback_reason=fallback_reason,
                )
            else:
                raise CardGenerationStreamError(source, reason=fallback_reason)
        else:
            card = self._finalize_card(
                card,
                source,
                context,
                generation_source="model",
            )
            if guided_pack:
                # Build governed facts only after the provider has completed.
                # Otherwise an interrupted stream would create a misleading
                # candidate event for a card that was never returned.
                guided_guardrail = self.generate_card(source, context, allow_llm=False)
                card = self._merge_guided_guardrail(card, guided_guardrail)
        yield CardGenerationStreamEvent(card=card)

    @staticmethod
    def _merge_guided_guardrail(
        model_card: TrainingCardCandidateSnapshot,
        guardrail: TrainingCardCandidateSnapshot,
    ) -> TrainingCardCandidateSnapshot:
        """Keep governed pack facts while accepting useful model-authored copy."""
        forced_fields = {
            "scenario_pack": guardrail.scenario_pack,
            "status": guardrail.status,
            "requires_project_context": guardrail.requires_project_context,
            "project_context_ready": guardrail.project_context_ready,
            "trust_state": guardrail.trust_state,
            "trust_acknowledged": guardrail.trust_acknowledged,
            "source_chain": guardrail.source_chain,
            "plan_links": guardrail.plan_links,
        }
        for field in (
            "verification_steps",
            "learner_deliverables",
            "expected_symbols",
            "constraints",
            "self_check",
            "hint_ladder",
            "common_mistakes",
        ):
            model_value = getattr(model_card, field, None)
            guardrail_value = getattr(guardrail, field, None)
            if not model_value and guardrail_value:
                forced_fields[field] = guardrail_value
        return model_card.model_copy(update=forced_fields)

    # ------------------------------------------------------------------
    # Fully implemented sources (enhanced with LLM)
    # ------------------------------------------------------------------

    def _generate_from_conversation_gap(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Generate a practice or flash card from a detected conversation gap."""
        card_type = context.card_type or "practice"
        guided_pack = _match_guided_scenario_pack(context, source="conversation_gap")
        if guided_pack:
            return _make_guided_scenario_pack_card(
                guided_pack,
                context,
                card_type,
                context.response_language or "en-US",
            )
        llm_card = (
            self._try_llm_generation(context, "conversation_gap", card_type)
            if allow_llm
            else None
        )
        if llm_card is not None:
            return llm_card
        if card_type == "flash":
            return self._make_fallback_card("conversation_gap", context)

        language = context.response_language
        practice_defaults = _practice_defaults(context, language)
        return TrainingCardCandidateSnapshot(
            card_type="practice",
            title=_localized_text(
                f"Practice: {context.focus_area or context.target_skill or 'unspecified area'}",
                f"练习：{context.focus_area or context.target_skill or '未指定领域'}",
                language,
            ),
            focus_area=context.focus_area or context.target_skill,
            target_skill=context.target_skill,
            scenario=_localized_text(
                context.context_hint or "Address a knowledge gap identified during coaching.",
                context.context_hint or "围绕教练发现的知识缺口做一次聚焦练习。",
                language,
            ),
            problem_statement=practice_defaults["problem_statement"],
            suggested_workspace_action=practice_defaults["suggested_workspace_action"],
            api_hints=practice_defaults["api_hints"],
            deliverable=practice_defaults["deliverable"],
            self_check=practice_defaults["self_check"],
            validation_method=practice_defaults["validation_method"],
            grading_rubric=practice_defaults["grading_rubric"],
            acceptance_criteria=derive_acceptance_criteria(
                practice_defaults["deliverable"],
                practice_defaults["grading_rubric"],
                context.target_skill or context.focus_area or "",
                language=language,
            ),
            learner_deliverables=practice_defaults["learner_deliverables"],
            verification_steps=practice_defaults["verification_steps"],
            success_signal=practice_defaults["success_signal"],
            stuck_recovery=practice_defaults["stuck_recovery"],
            reflection_prompt=practice_defaults["reflection_prompt"],
            return_with=practice_defaults["return_with"],
            next_after_completion=practice_defaults["next_after_completion"],
            difficulty="medium",
        )

    def _generate_from_plan_requirement(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Generate a training card targeting a plan stage skill."""
        card_type = context.card_type or "flash"
        llm_card = (
            self._try_llm_generation(context, "plan_requirement", card_type)
            if allow_llm
            else None
        )
        if llm_card is not None:
            if context.plan_stage_id:
                llm_card.plan_links = [context.plan_stage_id]
            return llm_card
        guided_pack = _match_guided_scenario_pack(context, source="plan_requirement")
        if guided_pack:
            card = _make_guided_scenario_pack_card(
                guided_pack,
                context,
                card_type,
                context.response_language or "en-US",
            )
            if context.plan_stage_id:
                card.plan_links = [context.plan_stage_id]
            return card

        language = context.response_language
        if card_type == "practice":
            skill = context.target_skill or context.focus_area or "plan skill"
            is_code_subject = _subject_lane(context) == "code"
            plan_deliverable = _localized_text(
                "One small patch or learner-authored artifact tied to the current plan stage."
                if is_code_subject
                else "One small learner-authored artifact tied to the current plan stage.",
                "一个与当前计划阶段直接相关的小补丁或学习产物。"
                if is_code_subject
                else "一个与当前计划阶段直接相关的小型学习产出。",
                language,
            )
            plan_rubric = [
                _localized_text(
                    "The action stayed tightly bounded.",
                    "行动边界保持得很紧。",
                    language,
                ),
                _localized_text(
                    "The result can be verified without extra guesswork.",
                    "结果可以在没有额外猜测的情况下验证。",
                    language,
                ),
            ]
            card = TrainingCardCandidateSnapshot(
                card_type="practice",
                title=_localized_text(
                    f"Practice: {skill}",
                    f"练习：{skill}",
                    language,
                ),
                focus_area=context.focus_area or context.target_skill,
                target_skill=context.target_skill,
                scenario=_localized_text(
                    context.context_hint or "This plan stage needs one small, verifiable move.",
                    context.context_hint or "当前 plan stage 需要一个小而可验证的推进动作。",
                    language,
                ),
                problem_statement=_localized_text(
                    f"Turn {skill} into one narrow implementation slice you can review in one pass."
                    if is_code_subject
                    else f"Turn {skill} into one narrow learning move you can review in one pass.",
                    f"把 {skill} 收窄成一个可以一遍评审完的小实现切片。"
                    if is_code_subject
                    else f"把 {skill} 收成一个范围很窄、可以快速复盘的学习动作。",
                    language,
                ),
                suggested_workspace_action=_localized_text(
                    "Make one narrow change that proves the current plan step is real."
                    if is_code_subject
                    else "Take one narrow action or produce one short artifact that proves the current plan step is real.",
                    "做一个很窄的改动，证明当前计划这一步是真的落地了。"
                    if is_code_subject
                    else "做一个很窄的动作，或产出一个很短的结果，证明当前计划这一步是真的落地了。",
                    language,
                ),
                deliverable=plan_deliverable,
                learner_deliverables=[
                    _localized_text(
                        "One focused patch on the current plan thread."
                        if is_code_subject
                        else "One focused artifact on the current plan thread.",
                        "当前计划主线上的一个聚焦补丁。"
                        if is_code_subject
                        else "当前计划主线上的一个聚焦产出。",
                        language,
                    ),
                    _localized_text(
                        "One short note explaining why this move is the right next step.",
                        "一段简短说明，解释为什么这一步是当前最合适的下一步。",
                        language,
                    ),
                ],
                validation_method=_localized_text(
                    "Run the smallest relevant check and explain why the result now holds.",
                    "运行最小相关检查，并说明为什么这次结果已经成立。",
                    language,
                ),
                verification_steps=[
                    _localized_text(
                        f"Check the exact behavior around {skill}.",
                        f"先检查 {skill} 附近的具体行为。",
                        language,
                    ),
                    _localized_text(
                        "Confirm the move still fits in one short review pass.",
                        "确认这一步仍然可以在一次很短的检查里看完。",
                        language,
                    ),
                ],
                self_check=[
                    _localized_text(
                        "Did you keep the slice tight enough to review quickly?",
                        "你有没有把切片保持得足够紧，能被快速评审？",
                        language,
                    ),
                    _localized_text(
                        "Can you point to one concrete proof that the move works?",
                        "你能不能指出一个具体证据，来证明这一步有效？",
                        language,
                    ),
                ],
                grading_rubric=plan_rubric,
                acceptance_criteria=(
                    _plan_acceptance_criteria(
                        context,
                        _plan_file_symbols(context),
                    )
                    or derive_acceptance_criteria(
                        plan_deliverable,
                        plan_rubric,
                        context.target_skill or context.focus_area or "",
                        language=language,
                    )
                ),
                expected_symbols=_plan_file_symbols(context),
                files_to_touch=(
                    [Path(str(context.current_file_path)).name]
                    if str(context.current_file_path or "").strip()
                    else []
                ),
                common_mistakes=[
                    _localized_text(
                        "Turning the plan step into a refactor instead of a narrow proof."
                        if is_code_subject
                        else "Turning one small plan step into a broad rewrite instead of a narrow proof.",
                        "把这一步做成重构，而不是一个范围很窄的证明动作。"
                        if is_code_subject
                        else "把一个很小的计划步骤做成大改写，而不是一个范围很窄的证明动作。",
                        language,
                    ),
                    _localized_text(
                        "Only explaining the plan without landing a visible artifact.",
                        "只讲计划，不落成一个可见的结果。",
                        language,
                    ),
                ],
                stuck_recovery=_localized_text(
                    "Return to the smallest boundary you can state, then prove only that boundary first.",
                    "回到你能说清楚的最小边界，先只证明这个边界。",
                    language,
                ),
                reflection_prompt=_localized_text(
                    "What did this step prove, and what did you deliberately leave out?",
                    "这一步证明了什么，又刻意没有包含什么？",
                    language,
                ),
                success_signal=_localized_text(
                    "One narrow plan step landed with a concrete check.",
                    "一个很窄的计划步骤已经落地，并带着具体验证结果。",
                    language,
                ),
                return_with=_localized_text(
                    "Return with the patch, the check result, and one sentence of reflection."
                    if is_code_subject
                    else "Return with the artifact, the check result, and one sentence of reflection.",
                    "带着补丁、验证结果和一句复盘说明回来。"
                    if is_code_subject
                    else "带着产出、验证结果和一句复盘说明回来。",
                    language,
                ),
                next_after_completion=_localized_text(
                    "Update evidence, then decide whether the next move should stay in practice or switch to flash review.",
                    "更新 evidence，然后决定下一步继续 practice 还是切回 flash 复习。",
                    language,
                ),
                difficulty="medium",
            )
            if context.plan_stage_id:
                card.plan_links = [context.plan_stage_id]
            return card

        card = TrainingCardCandidateSnapshot(
            card_type="flash",
            title=_localized_text(
                f"Flash: {context.target_skill or context.focus_area or 'plan skill'}",
                f"闪记：{context.target_skill or context.focus_area or '计划技能'}",
                language,
            ),
            focus_area=context.focus_area or context.target_skill,
            target_skill=context.target_skill,
            knowledge_type="engineering_concept",
            question=_localized_text(
                f"What is the core idea behind {context.target_skill or 'this skill'}?",
                f"{context.target_skill or '这个技能'} 的核心概念是什么？",
                language,
            ),
            context=_localized_text(
                context.context_hint or "This skill is required by your current plan stage.",
                context.context_hint or "这是你当前 plan stage 需要的技能。",
                language,
            ),
            answer_mode="text",
            expected_answer=_localized_text(
                "A concise explanation of the concept.",
                "对这个概念的简洁说明。",
                language,
            ),
            hint_ladder=[
                _localized_text("Think about what problem this technique solves.", "想一想这个技术解决了什么问题。", language),
                _localized_text("Consider the data flow or control flow involved.", "再想它涉及怎样的数据流或控制流。", language),
            ],
            difficulty="medium",
        )
        if context.plan_stage_id:
            card.plan_links = [context.plan_stage_id]
        return card

    # ------------------------------------------------------------------
    # Previously stub sources — now LLM-backed with template fallback
    # ------------------------------------------------------------------

    def _generate_from_resource_knowledge(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Generate a flash card from indexed resource knowledge."""
        card_type = context.card_type or "flash"
        guided_pack = _match_guided_scenario_pack(
            context, source="resource_knowledge",
            allow_resource_content=allow_llm and self._provider is not None,
        )
        if guided_pack:
            return _make_guided_scenario_pack_card(
                guided_pack,
                context,
                card_type,
                context.response_language or "en-US",
            )
        trust_state = _derive_resource_trust_state(context)
        reliability_note = _resource_reliability_note(context, context.response_language)
        llm_card = (
            self._try_llm_generation(context, "resource_knowledge", card_type)
            if allow_llm
            else None
        )
        if llm_card is not None:
            llm_card.trust_state = cast(TrainingCardTrustState, trust_state)
            if reliability_note:
                llm_card.why_now = (
                    f"{llm_card.why_now} {reliability_note}".strip()
                    if llm_card.why_now
                    else reliability_note
                )
            return llm_card

        # Template fallback
        if card_type == "flash":
            language = context.response_language
            question = (
                _localized_text(
                    f"What key concept from the resource relates to {context.focus_area or 'this topic'}?",
                    f"资料里与 {context.focus_area or '这个主题'} 相关的关键概念是什么？",
                    language,
                )
                if not context.resource_missing
                else _localized_text(
                    f"Why can't the coach safely turn {context.focus_area or 'this topic'} into a grounded flash card yet?",
                    f"为什么 coach 现在还不能把 {context.focus_area or '这个主题'} 安全地做成 grounded flash card？",
                    language,
                )
            )
            expected_answer = (
                _localized_text(
                    "The core concept explained in the resource.",
                    "资料里解释的核心概念。",
                    language,
                )
                if trust_state not in {"untrusted", "stale"}
                else _localized_text(
                    "State the trust or content problem first, then name what evidence is still missing.",
                    "先说明资料可信度或内容问题，再说还缺什么证据。",
                    language,
                )
            )
            hint_ladder = (
                [
                    _localized_text("Review the resource section on this topic.", "先看资料里这个主题对应的部分。", language),
                    _localized_text("Identify the key definition or pattern.", "找出关键定义或模式。", language),
                ]
                if trust_state not in {"untrusted", "stale"}
                else [
                    _localized_text("Check whether the resource was actually indexed successfully.", "先确认资料是不是已经成功索引。", language),
                    _localized_text("Name the missing proof before trying to memorize content from it.", "先说清楚缺的证据，再去记内容。", language),
                ]
            )
            feedback = (
                {
                    "correct": _localized_text("Well done! You've grasped the resource content.", "做得好，你已经抓住资料内容了。", language),
                    "incorrect": _localized_text("Review the resource again and focus on the key definition.", "再回去看一遍资料，重点放在关键定义上。", language),
                }
                if trust_state not in {"untrusted", "stale"}
                else {
                    "correct": _localized_text("Good catch. You noticed the coach still lacks a trustworthy source to teach from.", "发现得好。你注意到 coach 现在还没有足够可信的资料可教。", language),
                    "incorrect": _localized_text("Do not memorize from this yet. Resolve the resource trust or content gap first.", "现在先别记这个。先把资料可信度或内容缺口处理掉。", language),
                }
            )
            card = TrainingCardCandidateSnapshot(
                card_type="flash",
                title=_localized_text(
                    f"Flash: {context.focus_area or context.target_skill or 'resource concept'}",
                    f"闪记：{context.focus_area or context.target_skill or '资料概念'}",
                    language,
                ),
                focus_area=context.focus_area or context.target_skill,
                target_skill=context.target_skill,
                knowledge_type="engineering_concept",
                question=question,
                context=_localized_text(
                    context.context_hint or "Extracted from an indexed learning resource.",
                    context.context_hint or "从已索引的学习资料中提取。",
                    language,
                ),
                answer_mode="text",
                expected_answer=expected_answer,
                hint_ladder=hint_ladder,
                common_mistakes=[
                    _localized_text("Confusing the concept with a related but different idea.", "把这个概念和相近但不同的概念混在一起。", language),
                ],
                feedback=feedback,
                difficulty="medium",
            )
            card.trust_state = cast(TrainingCardTrustState, trust_state)
            if reliability_note:
                card.why_now = (
                    f"{card.why_now} {reliability_note}".strip()
                    if card.why_now
                    else reliability_note
                )
            return card
        card = self._make_fallback_card("resource_knowledge", context)
        card.trust_state = cast(TrainingCardTrustState, trust_state)
        if reliability_note:
            card.why_now = f"{card.why_now} {reliability_note}".strip()
        return card

    def _generate_from_practice_feedback(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Generate a practice card from recent practice feedback."""
        card_type = context.card_type or "practice"
        llm_card = (
            self._try_llm_generation(context, "practice_feedback", card_type)
            if allow_llm
            else None
        )
        if llm_card is not None:
            return llm_card
        guided_pack = _match_guided_scenario_pack(context, source="practice_feedback")
        if guided_pack and card_type == "practice":
            return _make_guided_scenario_pack_card(
                guided_pack,
                context,
                "practice",
                context.response_language or "en-US",
            )

        # Template fallback
        if card_type == "practice":
            language = context.response_language
            skill = context.focus_area or context.target_skill or "this skill"
            is_code_subject = _subject_lane(context) == "code"
            revised_deliverable = _localized_text(
                "An improved implementation addressing the feedback."
                if is_code_subject
                else "A revised artifact or explanation that addresses the feedback.",
                "一个针对反馈完成改进的实现。"
                if is_code_subject
                else "一个已经回应反馈的修订结果或解释。",
                language,
            )
            revised_rubric = [
                _localized_text("Feedback points addressed", "反馈点已处理", language),
                _localized_text(
                    "Quality or clarity maintained or improved",
                    "质量或清晰度保持住了，或者更好了",
                    language,
                ),
            ]
            return TrainingCardCandidateSnapshot(
                card_type="practice",
                title=_localized_text(
                    f"Practice: Improve {skill}",
                    f"练习：改进 {skill}",
                    language,
                ),
                focus_area=context.focus_area or context.target_skill,
                target_skill=context.target_skill,
                scenario=_localized_text(
                    context.context_hint or "Address feedback from a recent practice session.",
                    context.context_hint or "根据最近一次练习反馈来改进。",
                    language,
                ),
                problem_statement=_localized_text(
                    f"Based on recent feedback, improve your {skill} implementation."
                    if is_code_subject
                    else f"Based on recent feedback, improve your work on {skill}.",
                    f"根据最近反馈，改进你的 {skill} 实现。"
                    if is_code_subject
                    else f"根据最近反馈，改进你在 {skill} 上的这一步。",
                    language,
                ),
                suggested_workspace_action=_localized_text(
                    "Review feedback and refactor your code."
                    if is_code_subject
                    else "Review the feedback and revise one small part of the work.",
                    "回看反馈并重构代码。"
                    if is_code_subject
                    else "回看反馈，并只修改这份工作里很小的一处。",
                    language,
                ),
                api_hints=[
                    _localized_text(
                        "Review the most relevant note, example, or reference for this skill area.",
                        "回看这个技能最相关的一条笔记、例子或参考材料。",
                        language,
                    ),
                ],
                deliverable=revised_deliverable,
                self_check=[
                    _localized_text(
                        "Does the revision address the feedback points?",
                        "这次修订有回应反馈点吗？",
                        language,
                    ),
                    _localized_text(
                        "Is the improvement specific and visible?",
                        "这次改进是否足够具体，而且看得见？",
                        language,
                    ),
                ],
                grading_rubric=revised_rubric,
                acceptance_criteria=derive_acceptance_criteria(
                    revised_deliverable,
                    revised_rubric,
                    context.target_skill or context.focus_area or "",
                    language=language,
                ),
                stuck_recovery=_localized_text(
                    "Re-read the original feedback carefully and implement one fix at a time.",
                    "重新仔细阅读原始反馈，一次只做一个修复。",
                    language,
                ),
                reflection_prompt=_localized_text(
                    "What did the feedback reveal about your understanding?",
                    "这次反馈暴露了你理解里的什么问题？",
                    language,
                ),
                difficulty="medium",
            )
        return self._make_fallback_card("practice_feedback", context)

    def _generate_from_dependency_mastery(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Generate a flash card for a prerequisite skill not yet mastered."""
        card_type = context.card_type or "flash"
        guided_pack = _match_guided_scenario_pack(context, source="dependency_mastery")
        if guided_pack:
            return _make_guided_scenario_pack_card(
                guided_pack,
                context,
                card_type,
                context.response_language or "en-US",
            )
        llm_card = (
            self._try_llm_generation(context, "dependency_mastery", card_type)
            if allow_llm
            else None
        )
        if llm_card is not None:
            return llm_card

        # Template fallback
        if card_type == "flash":
            language = context.response_language
            skill = context.target_skill or context.focus_area or "prerequisite skill"
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                title=_localized_text(
                    f"Flash: Prerequisite {skill}",
                    f"闪记：前置技能 {skill}",
                    language,
                ),
                focus_area=context.focus_area or context.target_skill,
                target_skill=context.target_skill,
                knowledge_type="engineering_concept",
                question=_localized_text(
                    f"What is {skill} and why is it a prerequisite for your current work?",
                    f"{skill} 是什么，为什么它是你当前工作的前置技能？",
                    language,
                ),
                context=_localized_text(
                    context.context_hint or "This prerequisite skill needs mastery before advancing.",
                    context.context_hint or "这个前置技能需要先掌握，才能继续往下推进。",
                    language,
                ),
                answer_mode="text",
                expected_answer=_localized_text(
                    f"A clear explanation of {skill} and its role as a foundation.",
                    f"对 {skill} 及其作为基础能力的作用给出清晰解释。",
                    language,
                ),
                hint_ladder=[
                    _localized_text(f"Think about what {skill} enables.", f"先想想 {skill} 能让你做什么。", language),
                    _localized_text(
                        "Consider how this concept connects to what you're currently learning.",
                        "再考虑它和你现在学习的内容如何连接。",
                        language,
                    ),
                ],
                common_mistakes=[
                    _localized_text("Confusing this prerequisite with more advanced concepts.", "把这个前置技能和更高级的概念混淆。", language),
                    _localized_text("Skipping fundamentals too quickly.", "太快跳过基础。", language),
                ],
                feedback={
                    "correct": _localized_text("Great! You have the foundation needed to move forward.", "很好，你已经具备继续往前的基础了。", language),
                    "incorrect": _localized_text("Spend more time on this foundation before advancing.", "先把这个基础学稳，再继续往下。", language),
                },
                difficulty="easy",
            )
        return self._make_fallback_card("dependency_mastery", context)

    def _generate_from_review_due(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Generate a flash card for a concept due for review."""
        card_type = context.card_type or "flash"
        llm_card = (
            self._try_llm_generation(context, "review_due", card_type)
            if allow_llm
            else None
        )
        if llm_card is not None:
            return llm_card
        guided_pack = _match_guided_scenario_pack(context, source="review_due")
        if guided_pack and card_type == "flash":
            return _make_guided_scenario_pack_card(
                guided_pack,
                context,
                "flash",
                context.response_language or "en-US",
            )

        # Template fallback
        if card_type == "flash":
            language = context.response_language
            skill = context.focus_area or context.target_skill or "review concept"
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                title=_localized_text(
                    f"Review: {skill}",
                    f"复习：{skill}",
                    language,
                ),
                focus_area=context.focus_area or context.target_skill,
                target_skill=context.target_skill,
                knowledge_type="engineering_concept",
                question=_localized_text(
                    f"Explain the key aspects of {skill} from memory.",
                    f"请从记忆中说明 {skill} 的关键点。",
                    language,
                ),
                context=_localized_text(
                    context.context_hint or "Scheduled review - recall and reinforce this concept.",
                    context.context_hint or "计划中的复习 - 回忆并巩固这个概念。",
                    language,
                ),
                answer_mode="text",
                expected_answer=_localized_text(
                    f"A complete explanation of {skill} covering the main points.",
                    f"对 {skill} 的完整说明，覆盖主要要点。",
                    language,
                ),
                hint_ladder=[
                    _localized_text("Start with the core definition.", "先从核心定义开始。", language),
                    _localized_text("Think about when and why you would use this.", "想想你会在什么情况下、为什么使用它。", language),
                ],
                common_mistakes=[
                    _localized_text("Forgetting edge cases or limitations.", "遗漏边界情况或限制。", language),
                    _localized_text("Confusing with similar concepts.", "把它和相似概念混淆。", language),
                ],
                feedback={
                    "correct": _localized_text("Your recall is solid - this concept is well-reinforced.", "很好，你的回忆很稳，这个概念已经被巩固。", language),
                    "incorrect": _localized_text("This needs more reinforcement. Review the original material.", "这里还需要更多巩固。请回到原始材料。", language),
                },
                difficulty="medium",
            )
        return self._make_fallback_card("review_due", context)

    def _generate_stub(
        self,
        context: CardGenerationContext,
        *,
        allow_llm: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        """Fallback for unknown source types."""
        return self._make_fallback_card("conversation_gap", context)

    def _make_fallback_card(
        self,
        source_key: str,
        context: CardGenerationContext,
    ) -> TrainingCardCandidateSnapshot:
        """Create a truthful fallback card when the source is unknown or underspecified."""
        topic = context.focus_area or context.target_skill or "current work"
        language = context.response_language
        if context.card_type == "flash":
            return TrainingCardCandidateSnapshot(
                card_type="flash",
                title=_localized_text(
                    f"Flash: {topic}",
                    f"闪记：{topic}",
                    language,
                ),
                focus_area=context.focus_area or context.target_skill,
                target_skill=context.target_skill,
                knowledge_type="engineering_concept",
                question=_localized_text(
                    f"What is the smallest truthful explanation of {topic}?",
                    f"{topic} 的最小真实解释是什么？",
                    language,
                ),
                context=_localized_text(
                    context.context_hint or f"Fallback card generated from {source_key}.",
                    context.context_hint or f"来自 {source_key} 的回退卡片。",
                    language,
                ),
                answer_mode="text",
                expected_answer=_localized_text(
                    f"A concise explanation of {topic} and the boundary it sits within.",
                    f"对 {topic} 的简洁说明，以及它所处的边界。",
                    language,
                ),
                hint_ladder=[
                    _localized_text("Name the core idea first.", "先说核心概念。", language),
                    _localized_text("Add one concrete example or boundary condition.", "再举一个具体例子或边界条件。", language),
                ],
                common_mistakes=[
                    _localized_text("Jumping straight to implementation details without defining the concept.", "还没定义概念就直接讲实现细节。", language),
                ],
                feedback={
                    "correct": _localized_text("Good. You kept the explanation grounded.", "很好，你把解释控制在了真实边界内。", language),
                    "incorrect": _localized_text("Return to the smallest truthful explanation and name the boundary.", "回到最小真实解释，并说清楚边界。", language),
                },
                difficulty=context.difficulty,
            )

        practice_defaults = _practice_defaults(context, language)
        return TrainingCardCandidateSnapshot(
            card_type="practice",
            title=_localized_text(
                f"Practice: {topic}",
                f"练习：{topic}",
                language,
            ),
            focus_area=context.focus_area or context.target_skill,
            target_skill=context.target_skill,
            scenario=_localized_text(
                context.context_hint or f"Fallback card generated from {source_key}.",
                context.context_hint or f"来自 {source_key} 的回退卡片。",
                language,
            ),
            problem_statement=practice_defaults["problem_statement"],
            suggested_workspace_action=practice_defaults["suggested_workspace_action"],
            api_hints=practice_defaults["api_hints"],
            deliverable=practice_defaults["deliverable"],
            self_check=practice_defaults["self_check"],
            validation_method=practice_defaults["validation_method"],
            grading_rubric=practice_defaults["grading_rubric"],
            acceptance_criteria=derive_acceptance_criteria(
                practice_defaults["deliverable"],
                practice_defaults["grading_rubric"],
                context.target_skill or context.focus_area or "",
                language=language,
            ),
            learner_deliverables=practice_defaults["learner_deliverables"],
            verification_steps=practice_defaults["verification_steps"],
            success_signal=practice_defaults["success_signal"],
            stuck_recovery=practice_defaults["stuck_recovery"],
            reflection_prompt=practice_defaults["reflection_prompt"],
            return_with=practice_defaults["return_with"],
            next_after_completion=practice_defaults["next_after_completion"],
            difficulty=context.difficulty,
        )
