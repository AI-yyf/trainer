"""Workspace coaching preferences, training card context preparation, generation, and learn-first activation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException

from ...core.models import (
    ActiveCardSelectionResult,
    CardGenerationContext,
    CardGenerationRequest,
    CardGenerationResponse,
    CardLibraryActionRequest,
    CardStatusTransitionResponse,
    ExpectedResourceVersion,
    ResponseLanguage,
    TrainingCardCandidateSnapshot,
    TrainingPlanBinding,
    UserProfile,
    WorkbenchSnapshot,
)
from ...learner_state import learner_memory_snapshot
from ...llm.prompts import infer_coaching_scenario as infer_message_coaching_scenario
from ...llm.provider_service import (
    ProviderService,
)
from ...memory.workspace_recovery import (
    apply_live_training_mint_to_card,
    live_training_open_copy,
    live_training_why_this_card,
)
from ...training.card_generator import (
    CardGenerationProviderFailure,
    CardGenerationService,
    _make_guided_scenario_pack_card,
)
from ...training.card_request import message_requests_explicit_training_card
from ...training.plan_binding import validated_mint_binding
from ...training.project_checks import project_python_checks
from .._helpers import (
    SUPPORTED_RESPONSE_LANGUAGES,
    localized_text,
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
from ..router_support import (
    _apply_pedagogy_controls_to_card_request,
    _pedagogy_controls_for_workspace,
    _workspace_training_mint_overlay,
)
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
from .constants import (
    GUIDED_SCENARIO_TRAINING_PACKS,
)


class TrainingCardsActivationMixin:
    if TYPE_CHECKING:
        active_thread_scenario_value: Any
        build_resume_thread_text: Any
        eligible_resource_training_record: Any
        function_guidance_current_file_name: Any
        guided_training_workspace_facts: Any
        leftover_runtime_for_workspace: Any
        localized_training_defaults_for_scenario: Any
        merge_agent_finalize_into_coach_turn: Any
        message_requests_direct_answer: Any
        message_requests_explicit_explanation_or_example: Any
        message_requests_lane_continuation: Any
        normalize_current_file_payload: Any
        persist_training_card_to_sandbox: Any
        pressure_without_live_object_blocks_mint: Any
        provider_service_allows_object_minting: Any
        redact_training_fact_text: Any
        refresh_workspace_sessions: Any
        require_expected_training_resource_version: Any
        resolve_focus_hint: Any
        resource_trust_state: Any
        runtime: Any
        stateful_focus_area: Any
        streak_without_live_object_blocks_mint: Any
        training_card_lock: Any
        trusted_resource_knowledge_evidence: Any

    def prepare_training_card_request(self, request: CardGenerationRequest) -> CardGenerationRequest:
        """Apply the same redaction, locale, and resource trust projection to both routes."""
        request_payload = request.model_copy(deep=True, update={
            "resource_version_id": "", "resource_content_hash": "", "resource_location": {},
        })
        request_payload = request_payload.model_copy(
            update={"plan_binding": self.current_training_plan_binding(request_payload)}
        )
        if request_payload.plan_binding is not None:
            request_payload = request_payload.model_copy(
                update={
                    "plan_stage_id": request_payload.plan_binding.stage_id,
                    "source": "plan_requirement" if request_payload.source == "formal_plan_step"
                    else request_payload.source,
                }
            )
        request_payload = request_payload.model_copy(
            update={
                "focus_area": self.redact_training_fact_text(request_payload.focus_area, 240, collapse=True),
                "target_skill": self.redact_training_fact_text(request_payload.target_skill, 240, collapse=True),
                "context_hint": self.redact_training_fact_text(request_payload.context_hint, 1200),
                "why_now": self.redact_training_fact_text(request_payload.why_now, 360, collapse=True),
            }
        )
        if not request_payload.response_language:
            memory_snapshot = learner_memory_snapshot(self.runtime, request_payload.workspace_id)
            saved_language = memory_snapshot.workspace.get("response_language")
            resolved_language = (
                saved_language
                if isinstance(saved_language, str) and saved_language in SUPPORTED_RESPONSE_LANGUAGES
                else "en-US"
            )
            request_payload = request_payload.model_copy(update={"response_language": resolved_language})
        if request_payload.resource_id:
            request_payload = request_payload.model_copy(
                update={"resource_id": request_payload.resource_id.strip()}
            )
        self.require_expected_training_resource_version(request_payload)
        mint_overlay = _workspace_training_mint_overlay(
            self.runtime,
            request_payload.workspace_id,
            request_payload,
        )
        request_payload = request_payload.model_copy(update=mint_overlay["anchors"])
        eligible_resource = self.eligible_resource_training_record(request_payload)
        if request_payload.resource_id:
            resource = eligible_resource or self.runtime.repository.get_resource(
                request_payload.workspace_id,
                request_payload.resource_id,
            )
            if resource is not None:
                version = self.runtime.resource_version_store.current_version(
                    request_payload.workspace_id, resource.id
                ) if self.runtime.resource_version_store is not None else None
                resource_evidence = self.trusted_resource_knowledge_evidence(
                    request_payload.workspace_id,
                    resource,
                )
                if request_payload.expected_resource_version is not None and resource_evidence is None:
                    raise HTTPException(status_code=409, detail=localized_text(
                        "The confirmed source needs indexed content before it can be used for practice.",
                        "已确认的资料需要完成内容索引后才能用于练习。",
                        request_payload.response_language,
                    ))
                project_checks: list[str] = []
                if (
                    resource_evidence is not None and request_payload.current_file_path
                    and request_payload.card_type == "practice"
                    and request_payload.source in {"plan_requirement", "conversation_gap"}
                ):
                    root = self.runtime.resolve_workspace_path(request_payload.workspace_id)
                    if root:
                        project_checks = [
                            self.redact_training_fact_text(step, 280) for step in project_python_checks(
                                Path(root), request_payload.current_file_path, request_payload.context_hint,
                            )
                        ]
                request_payload = request_payload.model_copy(
                    update={
                        "resource_quality_flags": list(resource.quality_flags or []),
                        "resource_trust_score": float(resource.trust_score or 0.0),
                        "resource_trust_state": self.resource_trust_state(resource),
                        "resource_freshness": str(resource.freshness or "unknown"),
                        "resource_knowledge_evidence": resource_evidence,
                        "project_verification_steps": project_checks,
                        "resource_version_id": str((version or {}).get("version_id") or ""),
                        "resource_content_hash": str((version or {}).get("content_hash") or ""),
                        "resource_location": (version or {}).get("location") or {},
                    }
                )
            else:
                request_payload = request_payload.model_copy(
                    update={
                        "resource_missing": True,
                        "resource_missing_reason": "Requested resource was not found in workspace memory.",
                        "resource_trust_state": "untrusted",
                    }
                )
        return _apply_pedagogy_controls_to_card_request(request_payload, self.runtime)

    def current_training_plan_binding(self, request: CardGenerationRequest) -> TrainingPlanBinding | None:
        plan, recovered = self.leftover_runtime_for_workspace(request.workspace_id)
        revision = self.runtime.repository.get_plan_revision(request.workspace_id, plan.id) if plan else 0
        try:
            binding = validated_mint_binding(
                request.plan_binding,
                source=request.source,
                plan=plan,
                runtime=recovered,
                revision=revision,
            )
            if binding is not None and plan is not None and request.expected_resource_version is not None:
                stage = next((stage for stage in plan.stages if stage.id == binding.stage_id), None)
                if stage is None or request.resource_id not in stage.resources:
                    raise ValueError("Link the confirmed source to the current plan stage before practicing.")
            return binding
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def existing_open_resource_training_card(self, 
        request_payload: CardGenerationRequest,
    ) -> TrainingCardCandidateSnapshot | None:
        return next(
            (
                card
                for card in self.runtime.memory_service.get_cards(request_payload.workspace_id)
                if card.created_from == "resource"
                and card.resource_id == request_payload.resource_id
                and card.resource_content_hash == request_payload.resource_content_hash
                and (request_payload.expected_resource_version is None
                    or card.resource_version_id == request_payload.resource_version_id)
                and (request_payload.plan_binding is None or card.plan_binding == request_payload.plan_binding)
                and card.card_type == request_payload.card_type
                and card.status in {"candidate", "active", "needs_primer"}
            ),
            None,
        )

    def card_generation_service_for(self, 
        provider_service: ProviderService | None,
    ) -> CardGenerationService:
        configured_service = getattr(self.runtime, "card_generation_service", None)
        if configured_service is None:
            raise HTTPException(status_code=503, detail="Card generation service is not configured.")
        if getattr(configured_service, "_provider", None) is provider_service:
            return configured_service
        return CardGenerationService(
            provider_service=provider_service,
            event_ledger=getattr(configured_service, "_event_ledger", None),
        )

    def training_generate_candidate(self, 
        request: CardGenerationRequest,
        generated_card: TrainingCardCandidateSnapshot | None = None,
        provider_service_override: ProviderService | None = None,
    ) -> CardGenerationResponse:
        generator = self.card_generation_service_for(provider_service_override or self.runtime.provider_service)
        request_payload = self.prepare_training_card_request(request)

        def store_generated_card(
            generated_card: TrainingCardCandidateSnapshot | None = None,
        ) -> TrainingCardCandidateSnapshot:
            card = generated_card or generator.generate_card(request_payload.source, request_payload)
            card = card.model_copy(
                update={
                    "review_state": "pending",
                    "resource_id": request_payload.resource_id or card.resource_id,
                    "trust_state": request_payload.resource_trust_state or card.trust_state,
                    "difficulty": request_payload.difficulty or card.difficulty,
                }
            )
            mint_overlay = _workspace_training_mint_overlay(
                self.runtime,
                request_payload.workspace_id,
                request_payload,
            )
            card = apply_live_training_mint_to_card(
                card,
                anchors=mint_overlay["anchors"],
                leftover_labels=mint_overlay["leftover"],
                recovered_step=str(mint_overlay["recovered_step"] or ""),
            )
            # Recheck after the provider completes: a plan may change during generation.
            binding = self.current_training_plan_binding(request_payload)
            self.require_expected_training_resource_version(request_payload)
            card = card.model_copy(update={
                "plan_binding": binding,
                "plan_links": [binding.stage_id] if binding else (
                    [request_payload.plan_stage_id] if request_payload.plan_stage_id else []
                ),
            })
            return self.runtime.memory_service.upsert_card(request_payload.workspace_id, card)

        def existing_open_resource_card() -> TrainingCardCandidateSnapshot | None:
            return self.existing_open_resource_training_card(request_payload)

        def candidate_response(card: TrainingCardCandidateSnapshot) -> CardGenerationResponse:
            self.refresh_workspace_sessions(request_payload.workspace_id)
            return CardGenerationResponse(card=card)

        try:
            if request_payload.source == "resource_knowledge" and request_payload.resource_id:
                with self.training_card_lock(request_payload.workspace_id):
                    return candidate_response(
                        existing_open_resource_card() or store_generated_card(generated_card)
                    )
            return candidate_response(store_generated_card(generated_card))
        except (CardGenerationProviderFailure, HTTPException):
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def training_card_library_action(self, request: CardLibraryActionRequest) -> CardStatusTransitionResponse:
        workspace_id, card_id = request.workspace_id, request.card_id
        memory = self.runtime.memory_service
        with self.training_card_lock(workspace_id):
            card = memory.get_card(workspace_id, card_id)
            if card is None:
                raise HTTPException(status_code=404, detail="Training card not found.")
            if request.action == "start":
                if card.review_state != "saved" or card.status not in {
                    "candidate", "active", "needs_primer", "blocked", "skipped",
                }:
                    raise ValueError("Select an available card from your library.")
                if memory.live_selected_training_card_id(workspace_id) != card_id:
                    if card.trust_state in {"untrusted", "stale"} and not card.trust_acknowledged:
                        raise ValueError("Refresh or acknowledge the card's source before practicing.")
                    if card.resource_id and card.resource_version_id and card.resource_content_hash:
                        self.require_expected_training_resource_version(CardGenerationRequest(
                            workspace_id=workspace_id,
                            resource_id=card.resource_id,
                            expectedResourceVersion=ExpectedResourceVersion(
                                versionId=card.resource_version_id,
                                contentHash=card.resource_content_hash,
                            ),
                        ))
                    selection = memory.persist_active_card_selection(
                        workspace_id,
                        ActiveCardSelectionResult(
                            selected_card=card,
                            selected_card_id=card_id,
                            why_this_card=card.why_now,
                        ),
                    )
                    card = selection.selected_card or card
                    self.persist_training_card_to_sandbox(workspace_id, card)
            elif request.action == "archive":
                if card.status != "archived":
                    card = memory.transition_card_status(
                        workspace_id, card_id, "archived",
                        reason="Archived from the training library.",
                        archive_from_library=True,
                    ).card
            else:
                review_state: dict[str, Literal["saved", "deferred", "rejected"]] = {
                    "save": "saved", "defer": "deferred", "reject": "rejected",
                }
                card = memory.review_card_candidate(
                    workspace_id, card,
                    state=review_state[request.action],
                    prompt=request.prompt,
                    acceptance_criteria=request.acceptance_criteria,
                )
                if request.action == "save":
                    self.persist_training_card_to_sandbox(workspace_id, card, mark_current=False)
            self.refresh_workspace_sessions(workspace_id)
            return CardStatusTransitionResponse(card=card)

    def requested_training_card_type(self, message: str | None) -> Literal["practice", "flash"]:
        lowered = " ".join(str(message or "").strip().lower().split())
        direct_flash_tokens = (
            "flash card",
            "flashcard",
            "\u95ea\u5361",
            "\u95ea\u8bb0\u5361",
            "\u590d\u4e60\u5361",
        )
        if any(token in lowered for token in direct_flash_tokens):
            return "flash"

        practice_tokens = (
            "practice card",
            "learn-first",
            "hands-on",
            "primer",
            "before any test",
            "practice first",
            "do not test me first",
            "don't test me first",
            "before any quiz",
            "\u7ec3\u4e60\u5361",
            "\u5148\u5b66",
            "\u5148\u5b66\u4e60",
            "\u5148\u5b66\u518d\u7ec3\u4e60",
            "\u5148\u5b66\u540e\u7ec3",
            "\u5148\u8bb2\u518d\u7ec3",
            "\u4e0d\u8981\u5148\u8003\u8bd5",
            "\u4e0d\u8981\u5148\u6d4b\u8bd5",
        )
        if any(token in lowered for token in practice_tokens):
            return "practice"

        flash_cues = (
            "flash ",
            "recall card",
            "multiple choice",
            "quiz",
            "mcq",
        )
        if any(token in lowered for token in flash_cues):
            return "flash"
        return "practice"

    def validated_training_response_language(self, value: str | None) -> ResponseLanguage | None:
        return CardGenerationContext.model_validate({"response_language": value}).response_language

    def message_requests_general_learn_first_training(self, message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        learn_requested = any(
            token in lowered
            for token in (
                "learn first",
                "practice first",
                "teach me",
                "step by step",
                "before you test me",
                "before you quiz me",
                "first explain",
                "教我",
                "先教我",
                "先讲",
                "先学",
                "先学习",
                "先理解",
                "先讲解",
                "一步一步",
                "不要先考试",
                "不要先测试",
                "先学后练",
                "先学习再验证",
            )
        ) or bool(
            re.search(r"\blearn\b.{0,80}\bfirst\b", lowered)
            or re.search(r"\bunderstand\b.{0,80}\bfirst\b", lowered)
        )
        if not learn_requested:
            return False
        return any(
            token in lowered
            for token in (
                "tiny verified step",
                "small verified step",
                "tiny real step",
                "small real step",
                "tiny learning step",
                "small learning step",
                "small debug move",
                "smallest verifiable move",
                "tiny verified move",
                "tiny real move",
                "verifiable step",
                "verifiable move",
                "verifiable learning move",
                "verifiable value",
                "verify",
                "verified",
                "checkpoint",
                "validation step",
                "test my understanding",
                "before you test me",
                "before you quiz me",
                "再测试我",
                "再验证",
                "验证动作",
                "可验证",
                "很小的验证",
                "很小而且可验证",
                "很小的可验证",
                "很小的学习动作",
                "很小的训练动作",
            )
        )

    def message_requests_auto_training_handoff(self, message: str | None) -> bool:
        """Require an explicit learn-practice-verify loop before opening Training."""
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        learn_practice_markers = (
            "learn -> try -> verify",
            "learn, try, verify",
            "learn then practice",
            "learn then try",
            "learn first, then practice",
            "learn first, then try",
            "\u5148\u5b66\u518d\u7ec3",
            "\u5148\u5b66\u540e\u7ec3",
            "\u5148\u5b66\u518d\u5b9e\u8df5",
            "\u5148\u5b66\u540e\u5b9e\u8df5",
            "\u5148\u8bb2\u518d\u7ec3",
            "\u5148\u7406\u89e3\u518d\u7ec3",
        )
        verification_markers = (
            "verify",
            "verification",
            "test it",
            "check it",
            "\u9a8c\u6536",
            "\u9a8c\u8bc1",
            "\u68c0\u9a8c",
            "\u6d4b\u8bd5",
            "\u518d\u6d4b",
        )
        return any(marker in lowered for marker in learn_practice_markers) and any(
            marker in lowered for marker in verification_markers
        )

    def auto_answer_mode_allows_training_handoff(self, 
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
    ) -> bool:
        for value in (
            requested_answer_mode,
            saved_answer_mode,
            profile.answer_policy if profile else None,
        ):
            normalized = str(value or "").strip().lower()
            if normalized:
                return normalized == "auto"
        return False

    def message_requests_implicit_learn_first_training(self, 
        message: str | None,
        *,
        requested_scenario: str,
    ) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        if requested_scenario not in {
            "remote_workspace",
            "debug_loop",
            "function_guidance",
        }:
            return False
        if self.message_requests_general_learn_first_training(message):
            return True
        return False

    def message_requests_training_card_activation(self, 
        message: str | None,
        *,
        requested_scenario: str,
    ) -> bool:
        del requested_scenario
        return message_requests_explicit_training_card(message)

    def auto_preference_requests_training_card(self, 
        message: str | None,
        *,
        requested_scenario: str,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
    ) -> bool:
        del requested_scenario, requested_answer_mode, saved_answer_mode, profile
        return message_requests_explicit_training_card(message)

    def auto_lane_learn_first_force_training_card(self, 
        message: str | None,
        *,
        requested_scenario: str,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
    ) -> bool:
        del requested_answer_mode, saved_answer_mode, profile
        return self.message_requests_implicit_learn_first_training(
            message,
            requested_scenario=requested_scenario,
        )

    def training_card_defaults_for_scenario(self, 
        scenario: str,
        response_language: str | None,
    ) -> tuple[str, str]:
        localized_defaults = self.localized_training_defaults_for_scenario(
            scenario,
            response_language,
        )
        if localized_defaults is not None:
            return localized_defaults
        return (
            localized_text("current training focus", "当前训练重点", response_language),
            localized_text("learn-first practice", "先学习再练习", response_language),
        )

    def selected_training_card_scenario_pack(self, 
        selection: ActiveCardSelectionResult | None,
    ) -> str:
        if selection is None or selection.selected_card is None:
            return ""
        return str(getattr(selection.selected_card, "scenario_pack", "") or "").strip()

    def active_training_card_satisfies_request(self, 
        selection: ActiveCardSelectionResult | None,
        *,
        requested_scenario: str,
        message: str | None,
        force_training_card: bool,
    ) -> bool:
        if selection is None:
            return False
        if requested_scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return True
        if not force_training_card and not self.message_requests_training_card_activation(
            message,
            requested_scenario=requested_scenario,
        ):
            return True
        return self.selected_training_card_scenario_pack(selection) == requested_scenario

    def direct_guided_training_card_fallback(self, 
        *,
        workspace_id: str,
        scenario: str,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        active_thread: object | None,
    ) -> bool:
        if scenario not in {"remote_workspace", "debug_loop", "function_guidance"}:
            return False

        current_file_payload = self.normalize_current_file_payload(current_file)
        current_file_name = self.function_guidance_current_file_name(
            current_file_payload,
            scenario=scenario,
        )

        default_focus, default_skill = self.training_card_defaults_for_scenario(
            scenario,
            response_language,
        )
        active_thread_scenario = self.active_thread_scenario_value(active_thread)
        focus_candidates: list[object] = []
        if active_thread is not None and active_thread_scenario in {"", scenario, "general"}:
            focus_candidates.append(getattr(active_thread, "focus_area", ""))
        focus_candidates.append(default_focus)
        focus_hint = self.resolve_focus_hint(
            user_message=message,
            candidates=focus_candidates,
            fallback_current_file=current_file_name or None,
        )
        if scenario == "function_guidance" and current_file_name and not focus_hint:
            focus_hint = current_file_name

        context_bits = [f"Coach request: {str(message or '').strip()}"]
        if current_file_name:
            context_bits.append(f"Current file: {current_file_name}")
        active_next_step = str(getattr(active_thread, "next_step", "") or "").strip() if active_thread else ""
        if active_next_step and active_thread_scenario in {"", scenario, "general"}:
            context_bits.append(f"Active thread: {active_next_step}")

        pedagogy_controls = _pedagogy_controls_for_workspace(self.runtime, workspace_id)
        context = CardGenerationContext(
            workspace_id=workspace_id,
            source="conversation_gap",
            card_type=self.requested_training_card_type(message),
            context_hint=" | ".join(bit for bit in context_bits if bit).strip()[:420],
            target_skill=default_skill,
            focus_area=focus_hint or default_focus,
            difficulty=pedagogy_controls.difficulty if pedagogy_controls is not None else "medium",
            hint_count=pedagogy_controls.hint_count if pedagogy_controls is not None else None,
            code_reveal=pedagogy_controls.code_reveal if pedagogy_controls is not None else "",
            practice_type=pedagogy_controls.practice_type if pedagogy_controls is not None else "",
            review_frequency=pedagogy_controls.review_frequency if pedagogy_controls is not None else "",
            material_recommendation=(
                pedagogy_controls.material_recommendation if pedagogy_controls is not None else ""
            ),
            next_plan_step=pedagogy_controls.next_plan_step if pedagogy_controls is not None else "",
            should_reveal_code=(
                pedagogy_controls.should_reveal_code if pedagogy_controls is not None else None
            ),
            pedagogy_mode=pedagogy_controls.pedagogy_mode if pedagogy_controls is not None else "",
            why_now=localized_text(
                "The learner asked Coach for one learn-first training move.",
                "\u5b66\u4e60\u8005\u8981\u6c42 Coach \u5148\u5b89\u6392\u4e00\u4e2a\u5148\u5b66\u540e\u7ec3\u7684\u8bad\u7ec3\u52a8\u4f5c\u3002",
                response_language,
            ),
            response_language=self.validated_training_response_language(response_language),
        )
        context = context.model_copy(
            update=self.guided_training_workspace_facts(
                workspace_id=workspace_id,
                scenario=scenario,
                current_file=current_file_payload,
            )
        )
        card = _make_guided_scenario_pack_card(
            scenario,
            context,
            self.requested_training_card_type(message),
            response_language or "en-US",
        )
        stored_card = self.runtime.memory_service.upsert_card(workspace_id, card)
        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        self.runtime.memory_service.persist_active_card_selection(
            workspace_id,
            ActiveCardSelectionResult(
                selected_card=stored_card,
                selected_card_id=stored_card.card_id,
                selection_score=100.0,
                why_this_card=live_training_why_this_card(
                    plan=leftover_plan,
                    runtime=leftover_runtime,
                    existing=leftover_runtime,
                    card_title=stored_card.title,
                    why_now=stored_card.why_now,
                    kind="next",
                )
                or "This is the next training card.",
                fallback_action=localized_text(
                    "Return to Coach with the exact blocker and verification output.",
                    "带着准确的 blocker 和验证输出来回到 Coach。",
                    response_language,
                ),
                next_after_completion=localized_text(
                    "Finish the card, update the evidence, then route the next card.",
                    "完成这张卡，更新证据，再决定下一张卡。",
                    response_language,
                ),
                candidate_count=1,
                eligible_count=1,
            ),
        )
        self.refresh_workspace_sessions(workspace_id)
        return True

    def guided_training_card_requested(self, 
        *,
        scenario: str,
        message: str | None,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
        force_training_card: bool = False,
    ) -> bool:
        normalized_scenario = str(scenario or "").strip()
        if normalized_scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return False
        return force_training_card or self.message_requests_training_card_activation(
            message,
            requested_scenario=normalized_scenario,
        ) or self.auto_preference_requests_training_card(
            message,
            requested_scenario=normalized_scenario,
            requested_answer_mode=requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        ) or self.auto_lane_learn_first_force_training_card(
            message,
            requested_scenario=normalized_scenario,
            requested_answer_mode=requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        )

    def guarantee_guided_learn_first_training_card(self, 
        *,
        workspace_id: str,
        scenario: str,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        active_thread: object | None,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
        force_training_card: bool = False,
    ) -> bool:
        # Composer chat stays hint-only for remote_workspace / debug_loop packs;
        # POST /training/generate-card remains the binder for those. Function
        # guidance is the exception: when the learner asks to learn from real
        # code but no code-like file is available, the honest move is a
        # needs_primer card naming the missing facts, not a fake scaffolded
        # call site written into the sandbox.
        if scenario != "function_guidance":
            return False
        if not self.provider_service_allows_object_minting():
            return False
        if self.pressure_without_live_object_blocks_mint(
            workspace_id,
            message=message,
        ) or self.streak_without_live_object_blocks_mint(workspace_id):
            return False
        if scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return False
        if self.message_requests_direct_answer(message) or self.message_requests_explicit_explanation_or_example(
            message
        ):
            return False
        if not self.guided_training_card_requested(
            scenario=scenario,
            message=message,
            requested_answer_mode=requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
            force_training_card=force_training_card,
        ):
            return False
        snapshot = self.runtime.memory_service.snapshot(workspace_id)
        if self.active_training_card_satisfies_request(
            snapshot.active_training_card_routing,
            requested_scenario=scenario,
            message=message,
            force_training_card=True,
        ):
            return False
        return self.direct_guided_training_card_fallback(
            workspace_id=workspace_id,
            scenario=scenario,
            message=message,
            current_file=current_file,
            response_language=response_language,
            active_thread=active_thread,
        )

    def should_bypass_agent_loop_for_guided_training(self, 
        *,
        workspace_id: str,
        scenario: str,
        message: str | None,
        active_view: str | None = None,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
        force_training_card: bool = False,
    ) -> bool:
        # Training's Coach route is an explicit request for model-backed help.
        # The deterministic card handoff still creates/selects the card, but it
        # must not replace the learner's conversation with a local scaffold.
        if str(active_view or "").strip().lower() == "training":
            return False
        normalized_scenario = str(scenario or "").strip()
        if normalized_scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return False
        if self.message_requests_direct_answer(message) or self.message_requests_explicit_explanation_or_example(
            message
        ):
            return False
        visible_handoff_requested = force_training_card or self.auto_preference_requests_training_card(
            message,
            requested_scenario=normalized_scenario,
            requested_answer_mode=requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        )
        if not visible_handoff_requested:
            return False
        selection = self.runtime.memory_service.snapshot(workspace_id).active_training_card_routing
        return self.active_training_card_satisfies_request(
            selection,
            requested_scenario=normalized_scenario,
            message=message,
            force_training_card=True,
        )

    def build_guided_training_visible_fallback(self, 
        *,
        workspace_id: str,
        response_language: str | None,
    ) -> dict[str, str] | None:
        selection = self.runtime.memory_service.snapshot(workspace_id).active_training_card_routing
        if selection is None or selection.selected_card is None:
            return None
        card = selection.selected_card
        if str(card.scenario_pack or "").strip() not in GUIDED_SCENARIO_TRAINING_PACKS:
            return None

        leftover_plan, leftover_runtime = self.leftover_runtime_for_workspace(workspace_id)
        reason = live_training_why_this_card(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            card_title=card.title,
            why_now=str(selection.why_this_card or card.why_now or "").strip(),
            kind="current",
        )
        deliver = str(card.problem_statement or "").strip()
        if not deliver and card.learner_deliverables:
            deliver = "; ".join(
                str(item).strip() for item in card.learner_deliverables[:2] if str(item).strip()
            )
        verify = "; ".join(
            str(item).strip() for item in card.verification_steps[:2] if str(item).strip()
        )
        if not verify:
            verify = str(card.success_signal or card.validation_method or "").strip()
        return_with = str(card.return_with or selection.next_after_completion or "").strip()
        next_step = str(
            card.suggested_workspace_action
            or (card.verification_steps[0] if card.verification_steps else "")
            or selection.fallback_action
            or card.stuck_recovery
            or ""
        ).strip()
        primer_required = str(card.status or "").strip() == "needs_primer"
        open_copy = live_training_open_copy(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            card_title=str(card.title or "").strip(),
            next_step=next_step,
            primer_required=primer_required,
        )

        if prefers_chinese(response_language):
            lines = [
                "我先把这一轮收束成一张先学后练的训练卡，不先测试你。",
                "",
                open_copy["zh_current"],
            ]
            if reason:
                lines.append(f"- 为什么现在做：{reason}")
            if deliver:
                lines.append(f"- 你要完成：{deliver}")
            if verify:
                lines.append(f"- 这样验证：{verify}")
            if return_with:
                lines.append(f"- 完成后带回：{return_with}")
            lines.append("")
            if next_step:
                lines.append(f"先在 Training 做这一步：{next_step}")
            else:
                lines.append("先打开 Training，沿着这张卡继续。")
            lines.append(
                "先完成 primer，再进入验证。"
                if primer_required
                else "完成后把验证结果带回 Coach。"
            )
            summary = open_copy["zh_summary"]
            normalized_next_step = open_copy["zh_complete"]
            teaching_note = "训练默认闭环保持为 Learn -> Try -> Verify -> Reflect -> Return。"
        else:
            lines = [
                "I set up one learn-first training card before any quiz.",
                "",
                open_copy["en_current"],
            ]
            if reason:
                lines.append(f"- Why now: {reason}")
            if deliver:
                lines.append(f"- Deliver: {deliver}")
            if verify:
                lines.append(f"- Verify: {verify}")
            if return_with:
                lines.append(f"- Return with: {return_with}")
            lines.append("")
            if next_step:
                lines.append(f"Open Training and start with: {next_step}")
            else:
                lines.append("Open Training and continue with this card.")
            lines.append(
                "Finish the primer first, then move into verification."
                if primer_required
                else "Bring the verification result back to Coach when you finish."
            )
            summary = open_copy["en_summary"]
            normalized_next_step = open_copy["en_complete"]
            teaching_note = "Keep the training loop as Learn -> Try -> Verify -> Reflect -> Return."

        resume_thread = self.build_resume_thread_text(
            summary,
            normalized_next_step,
            response_language=response_language,
        )
        return {
            "reply": "\n".join(lines).strip(),
            "summary": summary,
            "next_step": normalized_next_step,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
        }

    def apply_guided_training_visible_fallback(self, 
        *,
        coach_turn: dict[str, object],
        fallback: dict[str, str],
    ) -> tuple[str, dict[str, object], dict[str, object]]:
        repaired_coach_turn = self.merge_agent_finalize_into_coach_turn(
            coach_turn,
            summary=fallback["summary"],
            next_step=fallback["next_step"],
            blocker=None,
            resume_thread=fallback["resume_thread"],
            decision="training_handoff",
            teaching_note=fallback["teaching_note"],
            confidence=None,
            evidence=None,
        )
        agent_meta = {
            "stop_reason": "local_guided_training",
            "summary": fallback["summary"],
            "next_step": fallback["next_step"],
            "decision": "training_handoff",
            "blocker": None,
            "teaching_note": fallback["teaching_note"],
            "resume_thread": fallback["resume_thread"],
            "confidence": None,
            "evidence": None,
            "tool_events": [],
            "fell_back": False,
            "recovered_stop_reason": None,
            "agentic": False,
            "local_guided_training_fallback": True,
        }
        if repaired_coach_turn is None:
            repaired_coach_turn = coach_turn
        return fallback["reply"], repaired_coach_turn, agent_meta

    def maybe_activate_training_card_from_coach_request(self, 
        *,
        workspace_id: str,
        snapshot: WorkbenchSnapshot,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        provider_service_override: ProviderService | None = None,
    ) -> CardGenerationResponse | None:
        # Composer chat (/turn, /turn/stream, /session/message) must not mint.
        # Explicit POST /training/generate-card binds a NEW card_id. Do not clobber
        # an already-live selected_card_id from chat either.
        return None
        current_file_payload = self.normalize_current_file_payload(current_file)
        active_thread = snapshot.memory.active_thread
        active_thread_scenario = self.active_thread_scenario_value(active_thread)
        requested_scenario = infer_message_coaching_scenario(
            str(message or ""),
            current_file_payload,
            default="general",
        )
        if (
            requested_scenario == "general"
            and self.message_requests_lane_continuation(message)
            and active_thread_scenario in {
                "remote_workspace",
                "debug_loop",
                "function_guidance",
            }
        ):
            requested_scenario = active_thread_scenario
        if not self.message_requests_training_card_activation(
            message,
            requested_scenario=requested_scenario,
        ):
            return None

        current_file_name = self.function_guidance_current_file_name(
            current_file_payload,
            scenario=requested_scenario,
        )

        default_focus, default_skill = self.training_card_defaults_for_scenario(
            requested_scenario,
            response_language,
        )
        focus_candidates: list[object] = []
        if active_thread is not None and active_thread_scenario in {"", requested_scenario, "general"}:
            focus_candidates.append(getattr(active_thread, "focus_area", ""))
        if requested_scenario == "general":
            focus_candidates.append(
                self.stateful_focus_area(
                    snapshot.current_task,
                    snapshot.plan,
                    snapshot.evaluation,
                    snapshot=snapshot,
                )
            )
        focus_candidates.append(default_focus)
        focus_hint = self.resolve_focus_hint(
            user_message=message,
            candidates=focus_candidates,
            fallback_current_file=current_file_name or None,
        )
        if requested_scenario == "function_guidance" and current_file_name and not focus_hint:
            focus_hint = current_file_name

        target_skill = default_skill if requested_scenario != "general" else (focus_hint or default_skill)
        context_bits = [f"Coach request: {str(message or '').strip()}"]
        if current_file_name:
            context_bits.append(f"Current file: {current_file_name}")
        active_next_step = str(getattr(active_thread, "next_step", "") or "").strip() if active_thread else ""
        if active_next_step and active_thread_scenario in {"", requested_scenario, "general"}:
            context_bits.append(f"Active thread: {active_next_step}")
        context_hint = " | ".join(bit for bit in context_bits if bit).strip()[:420]

        request_payload = CardGenerationRequest(
            workspace_id=workspace_id,
            source="conversation_gap",
            card_type=self.requested_training_card_type(message),
            focus_area=focus_hint or default_focus,
            target_skill=target_skill,
            context_hint=context_hint,
            why_now=localized_text(
                "The learner asked Coach for one learn-first training move.",
                "学习者请 Coach 提供一个先学习再练习的训练动作。",
                response_language,
            ),
            difficulty="medium",
            response_language=self.validated_training_response_language(response_language),
        )
        request_payload = request_payload.model_copy(
            update=self.guided_training_workspace_facts(
                workspace_id=workspace_id,
                scenario=requested_scenario,
                current_file=current_file_payload,
            )
        )
        return self.training_generate_candidate(
            request_payload,
            provider_service_override=provider_service_override,
        )

    def safe_activate_training_card_from_coach_request(self, 
        *,
        workspace_id: str,
        snapshot: WorkbenchSnapshot,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        provider_service_override: ProviderService | None = None,
    ) -> CardGenerationResponse | None:
        # Composer chat must not mint (incl. guided fallback). HTTP generate-card may.
        return None
        if not self.provider_service_allows_object_minting(provider_service_override):
            return None
        if self.pressure_without_live_object_blocks_mint(
            workspace_id,
            snapshot=snapshot,
            current_task=snapshot.current_task,
            current_plan=snapshot.plan,
            message=message,
        ) or self.streak_without_live_object_blocks_mint(
            workspace_id,
            snapshot=snapshot,
            current_task=snapshot.current_task,
            current_plan=snapshot.plan,
        ):
            return None
        created: CardGenerationResponse | None = None
        try:
            created = self.maybe_activate_training_card_from_coach_request(
                workspace_id=workspace_id,
                snapshot=snapshot,
                message=message,
                current_file=current_file,
                response_language=response_language,
                provider_service_override=provider_service_override,
            )
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
        if created is not None:
            return created
        current_file_payload = self.normalize_current_file_payload(current_file)
        active_thread = snapshot.memory.active_thread
        active_thread_scenario = self.active_thread_scenario_value(active_thread)
        requested_scenario = infer_message_coaching_scenario(
            str(message or ""),
            current_file_payload,
            default="general",
        )
        if (
            requested_scenario == "general"
            and self.message_requests_lane_continuation(message)
            and active_thread_scenario in GUIDED_SCENARIO_TRAINING_PACKS
        ):
            requested_scenario = active_thread_scenario
        if requested_scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return None
        if not self.message_requests_training_card_activation(
            message,
            requested_scenario=requested_scenario,
        ):
            return None
        if self.direct_guided_training_card_fallback(
            workspace_id=workspace_id,
            scenario=requested_scenario,
            message=message,
            current_file=current_file,
            response_language=response_language,
            active_thread=active_thread,
        ):
            selection = self.runtime.memory_service.snapshot(workspace_id).active_training_card_routing
            if selection is not None and selection.selected_card is not None:
                return CardGenerationResponse(
                    card=selection.selected_card,
                    score=selection.selection_score,
                    success=True,
                    reason="local_guided_fallback",
                    active_routing=selection,
                )
            fallback_context = CardGenerationContext(
                workspace_id=workspace_id,
                source="conversation_gap",
                card_type=self.requested_training_card_type(message),
                context_hint="",
                target_skill="guided fallback",
                focus_area="guided fallback",
                difficulty="medium",
                why_now="local_guided_fallback",
                response_language=self.validated_training_response_language(response_language),
            ).model_copy(
                update=self.guided_training_workspace_facts(
                    workspace_id=workspace_id,
                    scenario=requested_scenario,
                    current_file=current_file_payload,
                )
            )
            return CardGenerationResponse(
                card=_make_guided_scenario_pack_card(
                    requested_scenario,
                    fallback_context,
                    self.requested_training_card_type(message),
                    response_language or "en-US",
                ),
                score=100.0,
                success=True,
                reason="local_guided_fallback",
                active_routing=None,
            )
        return None

    def ensure_explicit_training_card_after_language_block(self, 
        *,
        state: SessionState,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        fallback_scenario: str | None = None,
        force_training_card: bool = False,
        provider_service_override: ProviderService | None = None,
    ) -> None:
        # Composer chat must not mint or clobber. Keep live selected_card_id only.
        # Explicit POST /training/generate-card is the intentional mint path.
        live_id = self.runtime.memory_service.live_selected_training_card_id(state.workspace_id)
        if live_id:
            state.snapshot.memory = self.runtime.memory_service.snapshot(state.workspace_id)
        return
        if not self.provider_service_allows_object_minting(provider_service_override):
            return
        # Pressure/streak blocks invent on coach turns (including "create a card" in chat).
        # Explicit POST /training/generate-card is the intentional mint path.
        if self.pressure_without_live_object_blocks_mint(
            state.workspace_id,
            snapshot=state.snapshot,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
            message=message,
        ) or self.streak_without_live_object_blocks_mint(
            state.workspace_id,
            snapshot=state.snapshot,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
        ):
            return
        snapshot = self.runtime.memory_service.snapshot(state.workspace_id)
        current_file_payload = self.normalize_current_file_payload(current_file)
        active_thread = state.snapshot.memory.active_thread
        active_thread_scenario = self.active_thread_scenario_value(active_thread)
        requested_scenario = infer_message_coaching_scenario(
            str(message or ""),
            current_file_payload,
            default="general",
        )
        normalized_fallback_scenario = str(fallback_scenario or "").strip()
        if (
            normalized_fallback_scenario in GUIDED_SCENARIO_TRAINING_PACKS
            and force_training_card
            and requested_scenario not in GUIDED_SCENARIO_TRAINING_PACKS
        ):
            requested_scenario = normalized_fallback_scenario
        if requested_scenario == "general" and normalized_fallback_scenario in GUIDED_SCENARIO_TRAINING_PACKS:
            requested_scenario = normalized_fallback_scenario
        if (
            requested_scenario == "general"
            and self.message_requests_lane_continuation(message)
            and active_thread_scenario in GUIDED_SCENARIO_TRAINING_PACKS
        ):
            requested_scenario = active_thread_scenario
        if self.active_training_card_satisfies_request(
            snapshot.active_training_card_routing,
            requested_scenario=requested_scenario,
            message=message,
            force_training_card=force_training_card,
        ):
            state.snapshot.memory = snapshot
            return
        created = self.safe_activate_training_card_from_coach_request(
            workspace_id=state.workspace_id,
            snapshot=state.snapshot,
            message=message,
            current_file=current_file,
            response_language=response_language,
            provider_service_override=provider_service_override,
        )
        if created is not None:
            refreshed_snapshot = self.runtime.memory_service.snapshot(state.workspace_id)
            if self.active_training_card_satisfies_request(
                refreshed_snapshot.active_training_card_routing,
                requested_scenario=requested_scenario,
                message=message,
                force_training_card=force_training_card,
            ):
                state.snapshot.memory = refreshed_snapshot
                return
        if not force_training_card and not self.message_requests_training_card_activation(
            message,
            requested_scenario=requested_scenario,
        ):
            return

        current_file_name = self.function_guidance_current_file_name(
            current_file_payload,
            scenario=requested_scenario,
        )
        default_focus, default_skill = self.training_card_defaults_for_scenario(
            requested_scenario,
            response_language,
        )
        focus_candidates: list[object] = []
        if active_thread is not None and active_thread_scenario in {"", requested_scenario, "general"}:
            focus_candidates.append(getattr(active_thread, "focus_area", ""))
        if requested_scenario == "general":
            focus_candidates.append(
                self.stateful_focus_area(
                    state.snapshot.current_task,
                    state.snapshot.plan,
                    state.snapshot.evaluation,
                    snapshot=state.snapshot,
                )
            )
        focus_candidates.append(default_focus)
        focus_hint = self.resolve_focus_hint(
            user_message=message,
            candidates=focus_candidates,
            fallback_current_file=current_file_name or None,
        )
        if requested_scenario == "function_guidance" and current_file_name and not focus_hint:
            focus_hint = current_file_name
        target_skill = default_skill if requested_scenario != "general" else (focus_hint or default_skill)
        context_bits = [f"Coach request: {str(message or '').strip()}"]
        if current_file_name:
            context_bits.append(f"Current file: {current_file_name}")
        active_next_step = str(getattr(active_thread, "next_step", "") or "").strip() if active_thread else ""
        if active_next_step and active_thread_scenario in {"", requested_scenario, "general"}:
            context_bits.append(f"Active thread: {active_next_step}")
        fallback_request = CardGenerationRequest(
            workspace_id=state.workspace_id,
            source="conversation_gap",
            card_type=self.requested_training_card_type(message),
            focus_area=focus_hint or default_focus,
            target_skill=target_skill,
            context_hint=" | ".join(bit for bit in context_bits if bit).strip()[:420],
            why_now=localized_text(
                "The learner asked Coach for one learn-first training move.",
                "学习者请 Coach 提供一个先学习再练习的训练动作。",
                response_language,
            ),
            difficulty="medium",
            response_language=self.validated_training_response_language(response_language),
        )
        fallback_request = fallback_request.model_copy(
            update=self.guided_training_workspace_facts(
                workspace_id=state.workspace_id,
                scenario=requested_scenario,
                current_file=current_file_payload,
            )
        )
        try:
            self.training_generate_candidate(
                fallback_request,
                provider_service_override=ProviderService(),
            )
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
        refreshed_snapshot = self.runtime.memory_service.snapshot(state.workspace_id)
        if not self.active_training_card_satisfies_request(
            refreshed_snapshot.active_training_card_routing,
            requested_scenario=requested_scenario,
            message=message,
            force_training_card=force_training_card,
        ):
            if self.direct_guided_training_card_fallback(
                workspace_id=state.workspace_id,
                scenario=requested_scenario,
                message=message,
                current_file=current_file,
                response_language=response_language,
                active_thread=active_thread,
            ):
                refreshed_snapshot = self.runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.memory = refreshed_snapshot

    def ensure_explicit_training_card_after_coach_reply(self, 
        *,
        state: SessionState,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        fallback_scenario: str | None = None,
        force_training_card: bool = False,
        provider_service_override: ProviderService | None = None,
    ) -> None:
        self.ensure_explicit_training_card_after_language_block(
            state=state,
            message=message,
            current_file=current_file,
            response_language=response_language,
            fallback_scenario=fallback_scenario,
            force_training_card=force_training_card,
            provider_service_override=provider_service_override,
        )
