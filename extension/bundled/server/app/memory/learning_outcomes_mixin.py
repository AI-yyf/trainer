from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import HTTPException

from ..core.event_ledger import (
    EVENT_EVALUATION_FEEDBACK_RECORDED,
    EVENT_PRACTICE_SUBMISSION_RECORDED,
)
from ..core.models import (
    EvidenceItem,
    TeachingKnowledgeAsset,
    TheoryDrillHistoryEntry,
)
from ..pedagogy.evidence_controls import (
    analyze_learning_evidence,
    resolve_pedagogy_controls,
    review_after_days_for_frequency,
)
from ..training.handoff import (
    EvidenceRecord,
    HandoffStatus,
    TrainingHandoffGenerator,
    TrainingPhase,
)
from .coaching_adaptation_mixin import (
    _localized_memory_text,
    _workspace_language,
)
from .models import (
    LearningOutcomeRecord,
    TeachingStrategyEffectivenessRecord,
    utc_now,
)
from .models import (
    MemorySnapshot as LaneMemorySnapshot,
)
from .transfer_skills import (
    normalize_transfer_skill_state_record,
    resolve_skill_scene_key,
)
from .workspace_recovery import (
    PLAN_RUNTIME_KEY,
    stamp_workspace_scope,
)

logger = logging.getLogger(__name__)


class LearningOutcomesMixin:
    if TYPE_CHECKING:
        _GLOBAL_FAILURE_OUTCOMES: Any
        _GLOBAL_PROMOTABLE_OUTCOMES: Any
        _apply_card_learning_phase: Any
        _authoritative_training_handoffs: Any
        _build_theory_drill_snapshot: Any
        _credit_returned_training_card: Any
        _current_training_handoff: Any
        _enqueue_training_return_evidence: Any
        _ensure_stage_progress: Any
        _live_training_persist_chrome: Any
        _normalize_dependency_key: Any
        _persist_structured: Any
        _persist_training_handoff_progress: Any
        _persist_transfer_skill_state: Any
        _preserve_highest_mastery_stage: Any
        _record_global_verified_outcome: Any
        _record_persisted_card_activity: Any
        _record_training_event: Any
        _record_verified_skill_scene: Any
        _resolve_workspace_for_write: Any
        _save_teaching_asset: Any
        _should_promote_verified_outcome_to_global: Any
        _structured_for: Any
        _sync_dependency_training_views: Any
        _training_handoff_generator: Any
        _training_handoff_records: Any
        _training_return_evidence_for_card: Any
        _verified_scenes_for_concept: Any
        _verified_training_handoff_evidence: Any
        apply_dependency_skill_map_action: Any
        enqueue_evidence: Any
        get_card: Any
        record_teaching_asset_effectiveness: Any
        record_teaching_assets_from_learning_outcome: Any
        record_teaching_assets_from_reflection: Any
        repository: Any
        run_training_reliability: Any
        transition_card_status: Any

    def return_training_handoff(
        self,
        *,
        workspace_id: str,
        card_id: str,
        handoff_id: str = "",
        request_id: str = "",
        idempotency_key: str = "",
        revision: int = 0,
        timeout_ms: int = 30_000,
        cancel: bool = False,
    ) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            return self._return_training_handoff_body(
                workspace_id=workspace_id,
                card_id=card_id,
                handoff_id=handoff_id,
            )

        return self.run_training_reliability(
            workspace_id,
            request_id=request_id,
            command_id="trainer.training.return",
            card_id=card_id,
            handoff_id=handoff_id,
            idempotency_key=idempotency_key,
            revision=revision,
            timeout_ms=timeout_ms,
            cancel=cancel,
            learning_phase="return",
            work=work,
        )

    def _return_training_handoff_body(
        self,
        *,
        workspace_id: str,
        card_id: str,
        handoff_id: str = "",
    ) -> dict[str, Any]:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured, card, generator, handoff = self._current_training_handoff(
            resolved_workspace_id,
            card_id,
            handoff_id,
        )
        if handoff.verification_state == "self_reported":
            if handoff.phase is not TrainingPhase.REFLECT:
                raise ValueError("Return requires a recorded reflection before completion.")
            returned = generator.return_handoff(handoff.handoff_id, handoff=handoff)
            if returned is None:
                raise LookupError("Training handoff not found.")
            self._training_handoff_records[returned.handoff_id] = returned
            return self._persist_training_handoff_progress(
                workspace_id=resolved_workspace_id,
                structured=structured,
                card=card,
                handoff=returned,
                return_evidence_persisted=True,
            )
        verified_summary, verification_source = self._verified_training_handoff_evidence(handoff)
        already_returned = (
            handoff.phase is TrainingPhase.RETURN and handoff.status is HandoffStatus.COMPLETED
        )
        if already_returned:
            existing = self._training_return_evidence_for_card(resolved_workspace_id, card.card_id)
            if existing is None or not existing.verified:
                try:
                    self._enqueue_training_return_evidence(
                        workspace_id=resolved_workspace_id,
                        card=card,
                        summary=verified_summary,
                        verification_source=verification_source,
                    )
                except Exception as exc:
                    logger.warning("Failed to record card progress for %s, falling back to handoff progress: %s", resolved_workspace_id, exc)
                    return self._persist_training_handoff_progress(
                        workspace_id=resolved_workspace_id,
                        structured=structured,
                        card=card,
                        handoff=handoff,
                        return_evidence_persisted=False,
                    )
            credited = self._credit_returned_training_card(resolved_workspace_id, card)
            return self._persist_training_handoff_progress(
                workspace_id=resolved_workspace_id,
                structured=structured,
                card=credited,
                handoff=handoff,
                return_evidence_persisted=True,
            )
        if handoff.phase is not TrainingPhase.REFLECT:
            raise ValueError("Return requires Learn, Try, trusted Verify, and Reflect in that order.")
        try:
            self._enqueue_training_return_evidence(
                workspace_id=resolved_workspace_id,
                card=card,
                summary=verified_summary,
                verification_source=verification_source,
            )
        except Exception as exc:
            logger.warning("Failed to record outcome progress for %s, falling back to handoff progress: %s", resolved_workspace_id, exc)
            return self._persist_training_handoff_progress(
                workspace_id=resolved_workspace_id,
                structured=structured,
                card=card,
                handoff=handoff,
                return_evidence_persisted=False,
            )
        returned = generator.return_handoff(handoff.handoff_id, handoff=handoff)
        if returned is None:
            raise LookupError("Training handoff not found.")
        credited = self._credit_returned_training_card(resolved_workspace_id, card)
        return self._persist_training_handoff_progress(
            workspace_id=resolved_workspace_id,
            structured=structured,
            card=credited,
            handoff=returned,
            return_evidence_persisted=True,
        )

    def rebind_training_handoff(self, workspace_id: str, card_id: str) -> dict[str, Any]:
        """Rebind the current training handoff to an existing card.

        Minting a second card moves the live selection, which used to strand the
        first card's handoff forever: reflect/return and card activation all
        fail-closed on the leftover-not-live guard. Rebinding re-points the open
        handoff (and the live selection stamps) at the requested card so its
        Learn..Return flow can finish. Unrelated leftover cards stay guarded.
        """

        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved_workspace_id)
        card = self.get_card(resolved_workspace_id, card_id)
        if card is None:
            raise LookupError("Training card not found.")
        card_status = str(getattr(card, "status", "") or "").strip().lower()
        if card_status in {"implemented", "completed"}:
            raise ValueError("This training card is already finished; there is no handoff to rebind.")

        generator = self._training_handoff_generator(resolved_workspace_id)
        payload = structured._workspace.get("latest_training_handoff")
        current = generator.hydrate_handoff(payload) if isinstance(payload, dict) else None
        # Rebind must never transfer another card's evidence. When the live
        # handoff belongs to a different card, rebuild this card's own handoff
        # from its own evidence (trusted or self-reported); otherwise start it
        # fresh at Learn.
        phase_rank = {
            TrainingPhase.LEARN: 0,
            TrainingPhase.TRY: 1,
            TrainingPhase.VERIFY: 2,
            TrainingPhase.REFLECT: 3,
            TrainingPhase.RETURN: 4,
        }
        own_records = [
            item
            for item in self._training_handoff_records.values()
            if item.card_id == card.card_id
            and item.status is not HandoffStatus.COMPLETED
        ]
        if current is not None and current.card_id == card.card_id:
            handoff = current
        elif own_records:
            handoff = max(
                own_records,
                key=lambda item: (phase_rank.get(item.phase, 0), item.handoff_id),
            )
        else:
            handoff = generator.build_handoff_record(
                card,
                {},
                response_language=_workspace_language(structured._workspace),
            )
            own_evidence = [
                item
                for item in structured._evidence_items.values()
                if item.source_card_id == card.card_id
                and str(getattr(item, "summary", "") or "").strip()
            ]
            trusted = [item for item in own_evidence if item.verified]
            self_reported = [
                item
                for item in own_evidence
                if not item.verified and item.verification_source == "self_reported"
            ]
            supporting = trusted or self_reported
            if supporting:
                for item in supporting[-3:]:
                    handoff.evidence.append(
                        EvidenceRecord(
                            id=f"ev-{card.card_id}-{uuid4().hex[:10]}",
                            card_id=card.card_id,
                            concept=handoff.handoff_content.concept_practiced,
                            content=item.summary,
                            source=str(item.source or "learner_return"),
                            created_at=utc_now(),
                            verified=bool(item.verified),
                            verification_source=str(item.verification_source or ""),
                        )
                    )
                generator._advance_phase(
                    handoff,
                    TrainingPhase.TRY,
                    detail="Rebind restored this card's own recorded attempt.",
                    recorded_at=utc_now(),
                )
                generator._advance_phase(
                    handoff,
                    TrainingPhase.VERIFY,
                    detail="Rebind restored this card's own evidence.",
                    recorded_at=utc_now(),
                )
                generator._sync_handoff_verification_state(
                    handoff, "verified" if trusted else "self_reported"
                )
        handoff_payload = TrainingHandoffGenerator._handoff_payload(handoff)
        self._authoritative_training_handoffs[(resolved_workspace_id, card.card_id)] = handoff
        self._training_handoff_records[handoff.handoff_id] = handoff
        # Rebind is an explicit live-selection bind: mirror
        # persist_active_card_selection so the leftover guard treats the
        # handoff owner as live for reflect/return/activation.
        workspace_patch: dict[str, Any] = {
            "latest_training_handoff": stamp_workspace_scope(handoff_payload, resolved_workspace_id),
            "selected_card_id": card.card_id,
            "selected_card_status": card.status,
        }
        existing_runtime = structured._workspace.get(PLAN_RUNTIME_KEY)
        if not isinstance(existing_runtime, dict):
            existing_runtime = structured._workspace.get("latestPlanRuntime")
        if isinstance(existing_runtime, dict):
            runtime_record = dict(existing_runtime)
            runtime_record["selected_card_id"] = card.card_id
            scoped_runtime = stamp_workspace_scope(runtime_record, resolved_workspace_id)
            if scoped_runtime is not None:
                workspace_patch[PLAN_RUNTIME_KEY] = scoped_runtime
        structured.update_workspace(**workspace_patch)
        self._persist_structured(resolved_workspace_id)
        return {"handoff": handoff_payload, "card": card.model_dump()}

    def record_training_practice_evaluation_result(
        self,
        *,
        workspace_id: str | None = None,
        card_id: str | None = None,
        card_title: str | None = None,
        passed: bool,
        summary: str,
        next_step: str,
        focus_area: str,
        failed_checks: list[str] | None = None,
        missing_requirements: list[str] | None = None,
        evidence_source: str = "ide_current_file",
        verified_by_evaluator: bool = False,
        manual_verification: bool = False,
        request_id: str = "",
        idempotency_key: str = "",
        revision: int = 0,
        timeout_ms: int = 30_000,
        cancel: bool = False,
        verification_artifact: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        evaluation_started_at = utc_now().isoformat()

        def work() -> dict[str, Any]:
            return self._record_training_practice_evaluation_result_body(
                evaluation_started_at=evaluation_started_at,
                workspace_id=workspace_id,
                card_id=card_id,
                card_title=card_title,
                passed=passed,
                summary=summary,
                next_step=next_step,
                focus_area=focus_area,
                failed_checks=failed_checks,
                missing_requirements=missing_requirements,
                evidence_source=evidence_source,
                verified_by_evaluator=verified_by_evaluator,
                manual_verification=manual_verification,
                verification_artifact=verification_artifact,
            )

        return self.run_training_reliability(
            workspace_id,
            request_id=request_id,
            command_id="trainer.training.practiceReturn",
            card_id=card_id or "",
            idempotency_key=idempotency_key,
            revision=revision,
            timeout_ms=timeout_ms,
            cancel=cancel,
            learning_phase="verify",
            work=work,
        )

    def _record_training_practice_evaluation_result_body(
        self,
        *,
        evaluation_started_at: str = "",
        workspace_id: str | None = None,
        card_id: str | None = None,
        card_title: str | None = None,
        passed: bool,
        summary: str,
        next_step: str,
        focus_area: str,
        failed_checks: list[str] | None = None,
        missing_requirements: list[str] | None = None,
        evidence_source: str = "ide_current_file",
        verified_by_evaluator: bool = False,
        manual_verification: bool = False,
        verification_artifact: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved_workspace_id)
        cleaned_card_id = (card_id or "").strip()
        cleaned_summary = summary.strip()
        cleaned_next_step = next_step.strip()
        cleaned_focus = focus_area.strip() or "practice verification"
        normalized_failed_checks = [
            item.strip() for item in (failed_checks or []) if item and item.strip()
        ]
        normalized_missing = [
            item.strip() for item in (missing_requirements or []) if item and item.strip()
        ]
        cleaned_evidence_source = evidence_source.strip() or "ide_current_file"

        if not cleaned_card_id:
            raise ValueError("A training card is required for practice verification.")
        card = self.get_card(resolved_workspace_id, cleaned_card_id)
        if card is None:
            raise ValueError(f"Training card {cleaned_card_id!r} not found")
        if card.review_state != "saved" or card.status == "archived":
            raise HTTPException(status_code=409, detail="Select an available card from your library.")
        if card.reviewed_at and card.status == "candidate":
            raise HTTPException(status_code=409, detail="Open this card for practice before verifying.")

        # Late-result fence (T-0014): an older verification that STARTED before
        # the learner's selection moved may still update its own card/evidence,
        # but it must never re-capture the selection. The selection stamp is
        # written by whichever result legitimately moved it last.
        selection_moved_at = str(
            structured._workspace.get("selected_card_updated_at") or ""
        )
        historical_result = bool(
            selection_moved_at
            and evaluation_started_at
            and selection_moved_at > evaluation_started_at
        )

        # Keep the runtime state aligned with the handoff's evidence trust boundary.
        # A positive client result alone must never advance a card to implemented.
        recovered_handoff = None
        live_open_handoff = None
        previous_handoff = structured._workspace.get("latest_training_handoff")
        if isinstance(previous_handoff, dict):
            candidate_handoff = TrainingHandoffGenerator._handoff_from_payload(previous_handoff)
            if candidate_handoff is not None and candidate_handoff.card_id == card.card_id:
                if (
                    candidate_handoff.phase is TrainingPhase.RETURN
                    and candidate_handoff.status is HandoffStatus.COMPLETED
                    and candidate_handoff.verification_state == "verified"
                    and candidate_handoff.reflection.strip()
                ):
                    recovered_handoff = candidate_handoff
                else:
                    live_open_handoff = candidate_handoff

        handoff_generator = self._training_handoff_generator(resolved_workspace_id)
        if recovered_handoff is not None and passed and not verified_by_evaluator:
            # A returned card already owns its trusted evidence identity.
            # A later self-report is a replay of that result, never a new verifier.
            return dict(structured._workspace)
        if recovered_handoff is not None and passed:
            handoff_record = recovered_handoff
        elif live_open_handoff is not None and passed and verified_by_evaluator:
            # Advance the live handoff through the generator's own trusted chain
            # (Learn -> Try -> Verify) so reflect/return operate on the same
            # record instead of a freshly built one they can never observe.
            handoff_generator._handoff_cache[live_open_handoff.handoff_id] = live_open_handoff
            advanced = live_open_handoff
            if advanced.phase is TrainingPhase.LEARN:
                advanced = (
                    handoff_generator.record_try(
                        advanced.handoff_id,
                        [cleaned_summary or "practice attempt submitted"],
                        source=cleaned_evidence_source,
                    )
                    or advanced
                )
            if verified_by_evaluator:
                advanced = (
                    handoff_generator.record_verification(
                        advanced.handoff_id,
                        [cleaned_summary] if cleaned_summary else [],
                        evidence_source=cleaned_evidence_source,
                        verified_by_evaluator=True,
                    )
                    or advanced
                )
            handoff_record = advanced
            structured._workspace["latest_training_handoff"] = (
                TrainingHandoffGenerator._handoff_payload(handoff_record)
            )
            self._persist_structured(resolved_workspace_id)
        else:
            handoff_record = handoff_generator.build_handoff_record(
                card,
                {
                    "correct": passed,
                    "evidence": [cleaned_summary] if passed and cleaned_summary else [],
                    "evidence_source": cleaned_evidence_source,
                    "verified_by_evaluator": verified_by_evaluator,
                },
                response_language=_workspace_language(structured._workspace),
            )
        pending_verification_markers = (
            # Bilingual on purpose: the evaluator localizes these sentences for
            # zh learners and the "no dynamic verifier ran" honesty rule must
            # hold in every language.
            "verification is still required",
            "run at least one dynamic verifier",
            "verify current file",
            "current ide file evidence",
            "current-file evidence",
            "仍需验证",
            "动态验证器",
            "验证当前文件",
            "当前 ide 文件证据",
            "当前文件证据",
        )
        summary_next_step_text = " ".join([cleaned_summary, cleaned_next_step]).lower()
        if (
            not passed
            and not verified_by_evaluator
            and any(marker in summary_next_step_text for marker in pending_verification_markers)
        ):
            handoff_generator._sync_handoff_verification_state(handoff_record, "verification_required")
        manual_pass = bool(manual_verification and passed and not verified_by_evaluator)
        if manual_pass:
            if handoff_record.phase is TrainingPhase.LEARN:
                handoff_generator._advance_phase(
                    handoff_record, TrainingPhase.TRY,
                    detail="Self-reported manual attempt recorded.", recorded_at=utc_now(),
                )
            if handoff_record.phase is TrainingPhase.TRY:
                handoff_generator._advance_phase(
                    handoff_record, TrainingPhase.VERIFY,
                    detail="Self-reported manual result recorded; reflection required.",
                    recorded_at=utc_now(),
                )
            handoff_generator._sync_handoff_verification_state(handoff_record, "self_reported")
            if cleaned_summary and not any(
                record.content.strip() == cleaned_summary and not record.verified
                for record in handoff_record.evidence
            ):
                handoff_record.evidence.append(
                    EvidenceRecord(
                        id=f"ev-{handoff_record.card_id}-{uuid4().hex[:10]}",
                        card_id=handoff_record.card_id,
                        concept=handoff_record.handoff_content.concept_practiced,
                        content=cleaned_summary,
                        source="learner_return",
                        created_at=utc_now(),
                        verified=False,
                        verification_source="self_reported",
                    )
                )
        self._authoritative_training_handoffs[(resolved_workspace_id, card.card_id)] = handoff_record
        self._training_handoff_records[handoff_record.handoff_id] = handoff_record
        handoff_payload = TrainingHandoffGenerator._handoff_payload(handoff_record)
        verification_state = handoff_record.verification_state
        handoff_completed = recovered_handoff is not None and passed
        verified_pass = verification_state == "verified"
        verification_pending = not handoff_completed and verification_state in {
            "verified",
            "verification_required",
            "evidence_required",
        }
        dependency_key = self._normalize_dependency_key(str(getattr(card, "dependency_key", "") or ""))
        dependency_mastery = structured._dependency_mastery.get(dependency_key) or {}
        current_dependency_stage = str(dependency_mastery.get("mastery_stage") or "understood")
        should_advance_dependency = (
            verified_by_evaluator
            and passed
            and verified_pass
            and bool(dependency_key)
            and dependency_key in structured._dependency_mastery
            and self._preserve_highest_mastery_stage(current_dependency_stage, "applied")
            != current_dependency_stage
        )
        if should_advance_dependency:
            self.apply_dependency_skill_map_action(
                resolved_workspace_id,
                dependency_key=dependency_key,
                action="mark_applied",
                note=cleaned_summary or "Current-file practice verified.",
                verified_result=cleaned_summary,
                verified_by_evaluator=True,
                verification_source=cleaned_evidence_source,
            )
        evidence_origin = "evaluation" if handoff_completed else "learner_return"
        updated_card = card
        try:
            current_card = card
            if handoff_completed:
                if current_card.status in {"candidate", "needs_primer", "blocked"}:
                    transition = self.transition_card_status(
                        resolved_workspace_id,
                        current_card.card_id,
                        "active",
                        reason="Practice verification resumed with new evidence.",
                    )
                    current_card = transition.card
                if current_card.status == "active":
                    transition = self.transition_card_status(
                        resolved_workspace_id,
                        current_card.card_id,
                        "implemented",
                        reason=cleaned_summary or "Practice verification passed from evidence.",
                        verified_by_evaluator=True,
                    )
                    current_card = transition.card
            elif manual_pass:
                if current_card.status in {"candidate", "needs_primer", "blocked"}:
                    current_card = self.transition_card_status(
                        resolved_workspace_id, current_card.card_id, "active",
                        reason="Self-reported manual result; reflection and return are still required.",
                    ).card
                if current_card.status == "active":
                    current_card = self.transition_card_status(
                        resolved_workspace_id, current_card.card_id, "answered",
                        reason="Self-reported manual result recorded; reflection and return are required.",
                    ).card
            elif verification_pending:
                if current_card.status in {"candidate", "needs_primer", "blocked"}:
                    pending_reason = (
                        "Trusted verification is recorded; reflection and an explicit return are still required."
                        if verified_pass
                        else "Learner result submitted; waiting for server-side verification."
                    )
                    transition = self.transition_card_status(
                        resolved_workspace_id,
                        current_card.card_id,
                        "active",
                        reason=pending_reason,
                    )
                    current_card = transition.card
            elif current_card.status in {"candidate", "active", "needs_primer"}:
                transition = self.transition_card_status(
                    resolved_workspace_id,
                    current_card.card_id,
                    "blocked",
                    reason=cleaned_summary or cleaned_next_step or "Practice verification returned with a blocker.",
                )
                current_card = transition.card
            updated_card = current_card
        except ValueError:
            updated_card = self.get_card(resolved_workspace_id, card.card_id) or card

        title = (
            (updated_card.title if updated_card is not None else "")
            or (card_title or "").strip()
            or cleaned_focus
        )
        persist_chrome = self._live_training_persist_chrome(
            resolved_workspace_id,
            card_title=title,
            summary=cleaned_summary,
        )
        title = persist_chrome["selected_card_title"]
        verification_summary = persist_chrome["verification_summary"]
        selected_card_id = cleaned_card_id or (updated_card.card_id if updated_card is not None else "")
        status = updated_card.status if updated_card is not None else (
            "implemented" if handoff_completed else "active" if verification_pending else "blocked"
        )
        selected_card_scenario_pack = (
            getattr(updated_card, "scenario_pack", "") or getattr(card, "scenario_pack", "") or ""
        ).strip()
        selected_card_next_after_completion = (
            getattr(updated_card, "next_after_completion", "")
            or getattr(card, "next_after_completion", "")
            or ""
        ).strip()
        if (
            updated_card is not None
            and selected_card_scenario_pack
            and not getattr(updated_card, "scenario_pack", "").strip()
        ):
            updated_card = updated_card.model_copy(
                update={"scenario_pack": selected_card_scenario_pack}
            )
        if updated_card is not None:
            updated_card = self._apply_card_learning_phase(
                resolved_workspace_id,
                updated_card,
                handoff_record.phase.value,
            )
            structured._training_cards[updated_card.card_id] = updated_card
        if handoff_completed:
            return_mode = "result"
            blocked_by = ""
            handoff_status = "verified"
            continue_in = "chat"
            accepted_into = "coach"
            next_hop_status = "continued_in_chat"
            default_next_after_completion = "Return to Coach with the verified result, then route the next card."
            fallback_action = "Ask Coach for the next training card."
        elif manual_pass:
            return_mode = "reflection_required"
            blocked_by = ""
            handoff_status = "needs_reflection"
            continue_in = "training"
            accepted_into = "training"
            next_hop_status = "reflection_required"
            default_next_after_completion = (
                "Record one reflection, then complete Return. This result is self-reported, not host-verified."
            )
            fallback_action = "Explain the evidence in your own words, then return through the training handoff."
        elif verified_pass:
            return_mode = "reflection_required"
            blocked_by = ""
            handoff_status = "needs_reflection"
            continue_in = "training"
            accepted_into = "training"
            next_hop_status = "reflection_required"
            default_next_after_completion = "Record one reflection, then complete Return before this card can count."
            fallback_action = "Explain what the verifier proved, then return through the training handoff."
        elif verification_pending:
            return_mode = "verification_required"
            blocked_by = ""
            handoff_status = "needs_verification"
            continue_in = "training"
            accepted_into = "training"
            next_hop_status = "verification_required"
            default_next_after_completion = "Run Verify current file before this result can count as mastery."
            fallback_action = "Run Verify current file, then return with the evaluation result."
        else:
            return_mode = "blocker"
            blocked_by = cleaned_next_step or cleaned_summary
            handoff_status = "needs_revision"
            continue_in = "training"
            accepted_into = "training"
            next_hop_status = "blocked"
            default_next_after_completion = "Fix the first failing signal, then re-run current file verification."
            fallback_action = "Bring the blocker back to Coach if the same check fails twice."
        next_after_completion = selected_card_next_after_completion or default_next_after_completion
        now = utc_now().isoformat()
        handoff = {
            "candidate_id": selected_card_id,
            "candidate_type": "practice_candidate",
            "target_kind": "training_card",
            "target_id": selected_card_id,
            "continue_in": continue_in,
            "accepted_into": accepted_into,
            "handoff_status": handoff_status,
            "handoff_summary": cleaned_summary,
            "blocked_by": blocked_by,
            "coach_only": False,
            "card_type": "practice",
            "card_title": title,
            "scenario_pack": selected_card_scenario_pack,
            "verification_steps": (
                normalized_failed_checks[:3]
                or normalized_missing[:3]
                or (
                    ["Record one reflection, then complete Return."]
                    if (verified_pass or manual_pass) and not handoff_completed
                    else ["Verify the current IDE file."] if verification_pending else []
                )
            ),
            "success_signal": cleaned_summary if handoff_completed else "",
            "return_with": cleaned_summary if verification_pending or handoff_completed or manual_pass else blocked_by,
            "next_after_completion": next_after_completion,
            "fallback_action": fallback_action,
            "return_mode": return_mode,
            "return_summary": cleaned_summary or blocked_by,
            "judged_at": now,
            "source_chain": ["training", cleaned_evidence_source, evidence_origin],
        }
        handoff.update(handoff_payload)
        handoff["card_title"] = title
        handoff["learning_phase"] = handoff_record.phase.value
        handoff["verification_state"] = verification_state
        handoff["handoff_status"] = handoff_status
        if verification_artifact is not None:
            handoff["verification_artifact"] = dict(verification_artifact)
        next_hop = {
            "candidate_id": selected_card_id,
            "candidate_type": "practice_candidate",
            "title": title,
            "summary": cleaned_summary,
            "why_now": (
                "This card completed Learn, Try, Verify, Reflect, and Return with trusted evidence."
                if handoff_completed
                else (
                    "A self-reported manual result is recorded; reflection and an explicit Return are required "
                    "before this card can leave the training flow."
                    if manual_pass
                    else (
                    "Trusted evidence is recorded, but reflection and an explicit Return are required "
                    "before this card can count as implemented."
                    if verified_pass
                    else (
                        "The learner submitted a result; run current-file verification before it counts as mastery."
                        if verification_pending
                        else "This card still has a concrete verification blocker."
                    )
                    )
                )
            ),
            "project_scope": "current_project",
            "continue_in": continue_in,
            "target_kind": "training_card",
            "target_id": selected_card_id,
            "accepted_into": accepted_into,
            "status": next_hop_status,
            "status_reason": cleaned_summary or blocked_by,
            "blocked_by": blocked_by,
            "handoff_status": handoff_status,
            "handoff_summary": cleaned_summary,
            "coach_only": False,
            "card_type": "practice",
            "card_title": title,
            "scenario_pack": selected_card_scenario_pack,
            "return_mode": return_mode,
            "return_summary": cleaned_summary or blocked_by,
            "judged_at": now,
            "next_after_completion": next_after_completion,
            "fallback_action": fallback_action,
            "source_chain": ["training", cleaned_evidence_source, evidence_origin],
            "handoff_id": handoff_record.handoff_id,
            "verification_state": verification_state,
            "return_state": handoff_record.return_state,
            "learning_phase": handoff_record.phase.value,
            "resume_token": handoff_record.resume_token,
            "completion_claim": handoff_record.handoff_content.completion_claim,
            "resume_action": handoff_record.handoff_content.resume_action,
        }

        if manual_pass and updated_card is not None:
            self.enqueue_evidence(
                resolved_workspace_id,
                EvidenceItem(
                    summary=cleaned_summary,
                    source="learner_return",
                    source_card_id=updated_card.card_id,
                    concepts=[item for item in [updated_card.target_skill, updated_card.focus_area] if item],
                    outcome="partial",
                    confidence=0.4,
                ),
                verified=False,
                verification_source="self_reported",
            )
        if handoff_completed and updated_card is not None:
            self.enqueue_evidence(
                resolved_workspace_id,
                EvidenceItem(
                    summary=verification_summary,
                    source="evaluation",
                    source_card_id=updated_card.card_id,
                    concepts=[item for item in [updated_card.target_skill, updated_card.focus_area] if item],
                    outcome="pass",
                    confidence=0.9,
                    target_plan_stage_id=updated_card.plan_links[0] if updated_card.plan_links else "",
                ).model_copy(update={"verification_artifact": verification_artifact} if verification_artifact is not None else {}),
                verified=True,
                verification_source=cleaned_evidence_source,
            )

        if (
            structured._active_training_card_routing is not None
            and updated_card is not None
            and structured._active_training_card_routing.selected_card_id == updated_card.card_id
        ):
            structured._active_training_card_routing = (
                structured._active_training_card_routing.model_copy(
                    update={
                        "selected_card": updated_card,
                        "selected_card_id": updated_card.card_id,
                    }
                )
            )

        workspace_update = structured.update_workspace(
            workspace_id=resolved_workspace_id,
            latest_training_submode="practice",
            latest_training_handoff=handoff,
            latest_training_next_hop=next_hop,
            latest_learning_focus_area=cleaned_focus,
            latest_learning_followup=cleaned_next_step or next_after_completion,
            latest_learning_verified_result=(
                cleaned_summary if handoff_completed or should_advance_dependency else ""
            ),
            latest_learning_blocker=blocked_by,
            latest_learning_partial_progress="" if handoff_completed else cleaned_summary,
            latest_learning_outcome=(
                "tests_passed"
                if handoff_completed
                else "reflection_required"
                if verified_pass or manual_pass
                else "verification_pending"
                if verification_pending
                else "evaluation"
            ),
            # A historical result updates its own card/evidence but leaves the
            # learner's current selection untouched (T-0014). A legitimate
            # selection move stamps its ordering time for the next fence.
            **(
                {}
                if historical_result
                else {
                    "selected_card_id": selected_card_id,
                    "selected_card_type": "practice",
                    "selected_card_title": title,
                    "selected_card_status": status,
                    "selected_card_updated_at": utc_now().isoformat(),
                }
            ),
            **({"latest_training_verification": {
                "card_id": selected_card_id, "passed": passed,
                "verification_artifact": dict(verification_artifact),
            }} if verification_artifact is not None else {}),
        )
        event = self._record_training_event(
            structured,
            event_type="practice_evaluation_recorded",
            payload={
                "selected_card_id": selected_card_id,
                "selected_card_type": "practice",
                "selected_card_title": title,
                "candidate_status": status,
                "candidate_status_reason": cleaned_summary or blocked_by,
                "return_mode": return_mode,
                "return_summary": cleaned_summary or blocked_by,
                "source_chain": ["training", cleaned_evidence_source, evidence_origin],
                **({"verification_artifact": dict(verification_artifact)} if verification_artifact is not None else {}),
            },
        )
        self._persist_structured(resolved_workspace_id)
        activity_type = (
            EVENT_EVALUATION_FEEDBACK_RECORDED
            if verified_by_evaluator or verification_artifact is not None
            else EVENT_PRACTICE_SUBMISSION_RECORDED
        )
        self._record_persisted_card_activity(
            resolved_workspace_id, card, activity_type, event["event_id"],
        )
        return dict(workspace_update)

    def record_learning_outcome(
        self,
        *,
        workspace_id: str | None = None,
        concepts: list[str],
        outcome: str,
        summary: str = "",
        checks: list[str] | None = None,
        missing_requirements: list[str] | None = None,
        action_type: str = "",
        repetition_count: int | None = None,
        focus_area: str | None = None,
        scenario: str | None = None,
        verified_result: str | None = None,
        blocked_reason: str | None = None,
        abandoned_reason: str | None = None,
        selected_teaching_asset_ids: list[str] | None = None,
        teaching_strategy_context: dict[str, str] | None = None,
        transfer_source_workspace_id: str | None = None,
        transfer_target_workspace_id: str | None = None,
        transfer_source_context: str | None = None,
        transfer_target_context: str | None = None,
        transfer_evidence_summary: str | None = None,
        verified_by_evaluator: bool = False,
        bind_evidence_to_current_plan: bool = True,
    ) -> LearningOutcomeRecord:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved_workspace_id)
        language = _workspace_language(structured._workspace)
        normalized_concepts = [item.strip() for item in concepts if item and item.strip()]
        normalized_outcome = outcome.strip() or "unknown"
        normalized_summary = summary.strip()
        blocked_reason = (blocked_reason or "").strip()
        abandoned_reason = (abandoned_reason or "").strip()
        if normalized_outcome == "blocked" and not (
            blocked_reason or abandoned_reason or normalized_summary
        ):
            blocked_reason = "The current slice is blocked."
        normalized_checks = [item.strip() for item in (checks or []) if item and item.strip()]
        normalized_missing = [item.strip() for item in (missing_requirements or []) if item and item.strip()]
        primary_concept = normalized_concepts[0] if normalized_concepts else ""
        focus_anchor = (focus_area or "").strip() or primary_concept or (scenario or "").strip() or "general"
        repetition = repetition_count or (
            1
            + sum(
                1
                for item in structured._learning_outcomes.values()
                if item.outcome == normalized_outcome
                and item.concept.strip().lower() == focus_anchor.lower()
            )
        )
        record = structured.remember_learning_outcome(
            focus_anchor,
            normalized_outcome,
            summary=normalized_summary,
            checks=normalized_checks,
            missing_requirements=normalized_missing,
            repetition_count=repetition,
            action_type=action_type,
            verified_by_evaluator=verified_by_evaluator,
            verified_result=(verified_result or "").strip(),
        )

        is_success = (
            verified_by_evaluator and normalized_outcome in self._GLOBAL_PROMOTABLE_OUTCOMES
        )
        scene_key = resolve_skill_scene_key(
            transfer_source_workspace_id=transfer_source_workspace_id or "",
            transfer_target_workspace_id=transfer_target_workspace_id or "",
            transfer_source_context=transfer_source_context or "",
            transfer_target_context=transfer_target_context or "",
            transfer_evidence_summary=transfer_evidence_summary or "",
            scenario=scenario or "",
        )
        if is_success and (verified_result or "").strip():
            for concept in normalized_concepts:
                self._record_verified_skill_scene(
                    workspace_id=resolved_workspace_id,
                    concept=concept,
                    scene_key=scene_key,
                )
        should_promote_to_global = (
            is_success
            and bool((verified_result or "").strip())
            and self._should_promote_verified_outcome_to_global(
                concepts=normalized_concepts,
                workspace_id=resolved_workspace_id,
                transfer_source_workspace_id=transfer_source_workspace_id,
                transfer_target_workspace_id=transfer_target_workspace_id,
                transfer_source_context=transfer_source_context,
                transfer_target_context=transfer_target_context,
                transfer_evidence_summary=transfer_evidence_summary,
                scenario=scenario,
            )
        )
        transfer_language = str(structured._workspace.get("response_language") or "")
        if is_success and normalized_concepts:
            for concept in normalized_concepts:
                self._persist_transfer_skill_state(
                    workspace_id=resolved_workspace_id,
                    concept=concept,
                    language=transfer_language,
                    schedule_review=should_promote_to_global,
                )
        elif normalized_outcome in self._GLOBAL_FAILURE_OUTCOMES:
            existing_transfer = normalize_transfer_skill_state_record(
                structured._workspace.get("latest_transfer_state")
            )
            if existing_transfer and existing_transfer.get("state") == "transferable":
                structured.update_workspace(latest_transfer_state=existing_transfer)
        if should_promote_to_global and (verified_result or "").strip():
            primary_scenes = self._verified_scenes_for_concept(normalized_concepts[0]) if normalized_concepts else []
            self._record_global_verified_outcome(
                normalized_concepts,
                normalized_outcome,
                workspace_id=resolved_workspace_id,
                scene_count=len(primary_scenes),
            )
        is_failure = normalized_outcome in self._GLOBAL_FAILURE_OUTCOMES or bool(normalized_missing or normalized_checks)
        repeated_failure = is_failure and repetition >= 2
        recent_outcomes = sorted(
            structured._learning_outcomes.values(),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        transfer_record = normalize_transfer_skill_state_record(
            structured._workspace.get("latest_transfer_state")
        )
        evidence_controls = resolve_pedagogy_controls(
            analyze_learning_evidence(recent_outcomes),
            transfer_scene_count=int((transfer_record or {}).get("scene_count") or 0),
            transfer_state=str((transfer_record or {}).get("state") or ""),
            user_preference=str(structured._workspace.get("latest_user_feedback_kind") or ""),
        )
        review_days = review_after_days_for_frequency(
            evidence_controls.review_frequency,
            default=1 if repeated_failure else 2,
        )

        for concept in normalized_concepts:
            # Fail-closed: tests_passed/code_landed labels without evaluator proof
            # must not mint or bump mastery. Unverified success is not mastery.
            if is_success:
                structured.update_mastery(concept, delta=0.12, confidence=0.72, review_after_days=review_days)
                # Verified success closes the recorded gap; a stale high-severity
                # weakness would keep review urgency pinned at high and block widening.
                structured.resolve_weakness(concept)
            elif is_failure:
                structured.update_mastery(concept, delta=-0.12, confidence=0.58, review_after_days=review_days)
                structured.record_weakness(
                    concept,
                    normalized_summary or "Learning outcome signaled a failure.",
                    severity=3 if repeated_failure else 2,
                    review_after_days=review_days,
                    context="; ".join(part for part in [blocked_reason, abandoned_reason, verified_result] if part),
                )

        if normalized_missing:
            for missing in normalized_missing:
                structured.record_weakness(
                    focus_anchor,
                    missing,
                    severity=3 if repeated_failure else 2,
                    review_after_days=review_days,
                    context=normalized_summary,
                )

        if is_success and verified_result:
            structured.update_active_thread(
                scenario=scenario or normalized_outcome,
                focus_area=focus_area or focus_anchor,
                summary=normalized_summary or verified_result,
                next_step=_localized_memory_text(
                    "Widen the scope only after the verified result is preserved.",
                    "先保留已验证结果，再扩大范围。",
                    language,
                ),
                verified_result=verified_result,
            )
        if (
            blocked_reason
            or abandoned_reason
            or normalized_outcome in {"blocked", "verification_pending"}
        ):
            structured.update_workspace(
                latest_learning_blocker=blocked_reason or abandoned_reason or normalized_summary,
                latest_learning_abandon_reason=abandoned_reason or "",
                latest_learning_outcome=normalized_outcome,
            )
        elif normalized_outcome in self._GLOBAL_PROMOTABLE_OUTCOMES:
            # A fresh success resolves the stale blocker; otherwise context
            # pressure stays pinned at high urgency and forces shrink forever.
            structured.update_workspace(
                latest_learning_blocker="",
                latest_learning_abandon_reason="",
                latest_learning_outcome=normalized_outcome,
            )
        if normalized_summary or normalized_outcome:
            improvement_signal = self._learning_outcome_strategy_signal(
                outcome=normalized_outcome,
                repeated_failure=repeated_failure,
                is_success=is_success,
                scenario=scenario or normalized_outcome,
                focus_area=focus_area or focus_anchor,
                blocked_reason=blocked_reason or abandoned_reason,
                verified_result=verified_result,
            )
            structured.remember_teaching_signal(
                key=(focus_anchor or normalized_outcome),
                signal=improvement_signal or normalized_summary or normalized_outcome,
                source_focus=focus_area or focus_anchor,
                scenario=scenario or normalized_outcome,
                source="learning-outcome",
            )
        if normalized_summary or normalized_outcome:
            structured.remember_decision(
                topic=focus_area or focus_anchor,
                decision=normalized_outcome,
                rationale=normalized_summary,
                next_step=(
                    _localized_memory_text(
                        "Reduce the next step and tighten verification.",
                        "缩小下一步并收紧验证。",
                        language,
                    )
                    if repeated_failure
                    else _localized_memory_text(
                        "Keep the next move attached to the verified result.",
                        "让下一步紧贴已验证结果。",
                        language,
                    )
                ),
                source="learning-outcome",
            )
        if normalized_summary or normalized_outcome:
            structured.remember_progress(
                scenario or normalized_outcome,
                focus_area or focus_anchor,
                normalized_summary or normalized_outcome,
                (
                    _localized_memory_text(
                        "Tighten the next practice loop.",
                        "收紧下一轮练习。",
                        language,
                    )
                    if repeated_failure
                    else _localized_memory_text(
                        "Continue with the verified slice.",
                        "继续已验证的切片。",
                        language,
                    )
                ),
            )
        evidence_outcome = (
            "pass"
            if verified_by_evaluator and normalized_outcome in {"code_landed", "tests_passed"}
            else "fail"
            if normalized_outcome in {"repeated_error", "task_abandoned", "evaluation", "blocked"}
            else "partial"
        )
        self.enqueue_evidence(
            resolved_workspace_id,
            EvidenceItem(
                summary=normalized_summary or normalized_outcome,
                source="learning_signal",
                concepts=normalized_concepts or ([focus_anchor] if focus_anchor else []),
                outcome=evidence_outcome,
                confidence=0.7 if is_success else 0.45,
            ),
            auto_bind_current_plan=bind_evidence_to_current_plan,
        )
        profile = self.repository.get_profile(resolved_workspace_id)
        preferred_libraries = {
            self._normalize_dependency_key(item)
            for item in ((profile.preferred_libraries if profile else []) or [])
            if item
        }
        dependency_candidates = {
            key for key in structured._dependency_mastery.keys()
        }
        for concept in normalized_concepts:
            normalized_key = self._normalize_dependency_key(concept)
            if normalized_key in preferred_libraries or normalized_key in dependency_candidates:
                current = structured._dependency_mastery.get(normalized_key) or {}
                next_stage = str(current.get("mastery_stage") or "understood")
                progress = list(current.get("mastery_stage_progress") or [])
                blocked_transfer_reason = str(current.get("latest_transfer_blocked_reason") or "")
                transfer_id = str(current.get("latest_transfer_evidence_id") or "")
                transfer_summary = str(current.get("latest_transfer_evidence_summary") or "")
                if is_success and normalized_outcome in {"code_landed", "tests_passed"}:
                    if (scenario or "").strip() == "cross_project_transfer":
                        if transfer_source_workspace_id and transfer_target_workspace_id and transfer_evidence_summary:
                            next_stage = self._preserve_highest_mastery_stage(
                                next_stage,
                                "transferable",
                            )
                            progress = self._ensure_stage_progress(progress, next_stage)
                            transfer_id = transfer_id or f"transfer-{uuid4().hex[:10]}"
                            transfer_summary = transfer_evidence_summary
                            blocked_transfer_reason = ""
                        else:
                            next_stage = self._preserve_highest_mastery_stage(next_stage, "applied")
                            progress = self._ensure_stage_progress(progress, next_stage)
                            blocked_transfer_reason = "Transferable mastery needs explicit cross-project migration evidence."
                    else:
                        next_stage = self._preserve_highest_mastery_stage(next_stage, "applied")
                        progress = self._ensure_stage_progress(progress, next_stage)
                        blocked_transfer_reason = ""
                structured.upsert_dependency_mastery(
                    normalized_key,
                    dependency_name=current.get("dependency_name") or concept,
                    apis=list(current.get("apis") or []),
                    use_cases=list(current.get("use_cases") or []),
                    scenarios=list(current.get("scenarios") or []),
                    weakest_points=list(current.get("weakest_points") or []),
                    evidence=list(current.get("evidence") or [normalized_summary or normalized_outcome]),
                    mastery_stage=next_stage,
                    mastery_stage_progress=progress,
                    latest_transfer_blocked_reason=blocked_transfer_reason,
                    latest_transfer_evidence_id=transfer_id,
                    latest_transfer_evidence_summary=transfer_summary,
                    latest_transfer_source_workspace_id=transfer_source_workspace_id or "",
                    latest_transfer_target_workspace_id=transfer_target_workspace_id or "",
                    latest_transfer_source_context=transfer_source_context or "",
                    latest_transfer_target_context=transfer_target_context or "",
                )
        self._sync_dependency_training_views(structured)
        if repeated_failure and structured._dependency_mastery:
            if structured._theory_drill is None:
                structured._theory_drill = self._build_theory_drill_snapshot(structured)
                if structured._theory_drill is not None:
                    structured._theory_drill_history.append(
                        TheoryDrillHistoryEntry(
                            entry_id=f"hist-{uuid4().hex[:10]}",
                            theory_drill_id=structured._theory_drill.id,
                            action="created",
                            version=structured._theory_drill.version,
                            note="Created after repeated learning failure.",
                            before_snapshot={},
                            after_snapshot=structured._theory_drill.model_dump(mode="json"),
                        )
                    )
            structured.update_workspace(
                latest_training_submode="review",
                latest_learning_scenario="theory_drill",
            )
        if normalized_summary or normalized_outcome:
            next_practice_step = (
                "Tighten the next practice loop." if repeated_failure else "Continue with the verified slice."
            )
            saved_learning_assets = self.record_teaching_assets_from_learning_outcome(
                resolved_workspace_id,
                scenario=scenario or normalized_outcome,
                focus_area=focus_area or focus_anchor,
                outcome=normalized_outcome,
                summary=normalized_summary or normalized_outcome,
                next_step=next_practice_step,
                checks=normalized_checks,
                verified_result=verified_result,
                blocked_reason=blocked_reason or abandoned_reason,
            )
            saved_reflection_assets = self.record_teaching_assets_from_reflection(
                resolved_workspace_id,
                scenario=scenario or normalized_outcome,
                focus_area=focus_area or focus_anchor,
                summary=normalized_summary or normalized_outcome,
                next_step=next_practice_step,
                review_note=blocked_reason or abandoned_reason or None,
            )
            if (
                should_promote_to_global
                and normalized_summary
                and normalized_outcome in {"code_landed", "tests_passed"}
            ):
                self.record_general_teaching_asset(
                    workspace_id=resolved_workspace_id,
                    title=f"{focus_anchor} · reusable pattern",
                    summary=normalized_summary,
                    explanation_recipe=next_practice_step,
                    why_it_matters=verified_result or normalized_summary,
                    source_ids=[asset.id for asset in saved_learning_assets[:2] + saved_reflection_assets[:1]],
                    source_fragments=[normalized_summary, next_practice_step],
                    tags=["general", normalized_outcome],
                    focus_area=focus_area or focus_anchor,
                    scenario=scenario or normalized_outcome,
                )
        if selected_teaching_asset_ids:
            self.record_teaching_asset_effectiveness(
                resolved_workspace_id,
                asset_ids=[str(item) for item in selected_teaching_asset_ids if str(item).strip()],
                outcome=normalized_outcome,
                scenario=scenario or normalized_outcome,
            )
        normalized_strategy_context = self._normalize_teaching_strategy_context(teaching_strategy_context)
        if normalized_strategy_context is not None and normalized_outcome in {
            "code_landed",
            "tests_passed",
            "concept_answered_correctly",
            "evaluation",
            "repeated_error",
            "task_abandoned",
            "blocked",
        }:
            structured.remember_teaching_strategy_effectiveness(
                scenario=scenario or normalized_outcome,
                focus_area=focus_area or focus_anchor,
                challenge_level=normalized_strategy_context["challenge_level"],
                hint_depth=normalized_strategy_context["hint_depth"],
                review_urgency=normalized_strategy_context["review_urgency"],
                explanation_mode=normalized_strategy_context["explanation_mode"],
                next_step_bias=normalized_strategy_context["next_step_bias"],
                outcome=normalized_outcome,
                summary=normalized_summary or normalized_outcome,
                verified_result=verified_result or "",
            )
        self._persist_structured(resolved_workspace_id)
        return record

    def record_general_teaching_asset(
        self,
        *,
        workspace_id: str | None,
        title: str,
        summary: str,
        explanation_recipe: str = "",
        why_it_matters: str = "",
        source_ids: list[str] | None = None,
        source_fragments: list[str] | None = None,
        tags: list[str] | None = None,
        focus_area: str = "",
        scenario: str = "",
    ) -> TeachingKnowledgeAsset | None:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        cleaned_summary = summary.strip()
        cleaned_explanation = explanation_recipe.strip()
        if not cleaned_summary and not cleaned_explanation:
            return None
        asset = TeachingKnowledgeAsset(
            kind="implementation_pattern" if cleaned_explanation else "concept_card",
            scope="general",
            workspace_id="__global__",
            title=title,
            summary=cleaned_summary or cleaned_explanation,
            concept_card=cleaned_summary if not cleaned_explanation else "",
            implementation_pattern=cleaned_explanation,
            explanation_recipe=cleaned_explanation,
            why_it_matters=why_it_matters.strip() or cleaned_summary,
            focus_area=focus_area.strip() or title,
            scenario=scenario.strip() or "general",
            origin="learning_outcome",
            source_key=f"general::{resolved_workspace_id}::{title}".lower(),
            source_ids=list(source_ids or []),
            source_fragments=list(source_fragments or []),
            evidence_snippets=[
                cleaned_summary,
                cleaned_explanation,
                why_it_matters.strip(),
            ],
            retrieval_hints=[focus_area.strip() or title, scenario.strip() or "general", *(tags or [])[:3]],
            source_summary=why_it_matters.strip() or cleaned_summary or cleaned_explanation,
            tags=list(tags or []) or ["general"],
            trust_score=0.72,
        )
        return self._save_teaching_asset(resolved_workspace_id, asset)

    def _learning_outcome_strategy_signal(
        self,
        *,
        outcome: str,
        repeated_failure: bool,
        is_success: bool,
        scenario: str,
        focus_area: str,
        blocked_reason: str | None,
        verified_result: str | None,
    ) -> str:
        anchor = focus_area.strip() or scenario.strip() or "current focus"
        language_context = blocked_reason or verified_result or anchor
        if repeated_failure:
            return _localized_memory_text(
                (
                    f"Teaching strategy update for {anchor}: switch to a tighter recovery loop, "
                    "more explicit hints, and one verification-first step."
                ),
                (
                    f"教学策略更新：围绕「{anchor}」切到更紧的恢复回路，"
                    "给更明确的提示，并先收口一个验证优先的步骤。"
                ),
                language_context,
            )
        if outcome == "task_abandoned":
            return _localized_memory_text(
                (
                    f"Teaching strategy update for {anchor}: reduce challenge, rebuild confidence, "
                    "and restart from a smaller code boundary."
                ),
                (
                    f"教学策略更新：围绕「{anchor}」先降低挑战、重建信心，"
                    "并从更小的代码边界重新开始。"
                ),
                language_context,
            )
        if is_success and outcome == "concept_answered_correctly":
            return _localized_memory_text(
                (
                    f"Teaching strategy update for {anchor}: the concept is landing, so shift the next loop toward transfer."
                ),
                f"教学策略更新：「{anchor}」的概念已经在落地，下一轮应更强调迁移应用。",
                language_context,
            )
        if is_success:
            return _localized_memory_text(
                (
                    f"Teaching strategy update for {anchor}: recent progress is verified, "
                    "so the next loop can widen slightly with lighter hints."
                ),
                (
                    f"教学策略更新：「{anchor}」最近的进展已经验证通过，"
                    "下一轮可以稍微放宽一点，并减少提示。"
                ),
                language_context,
            )
        return _localized_memory_text(
            (
                f"Teaching strategy update for {anchor}: keep the next loop narrow, "
                "stay attached to the latest blocker, and verify before widening."
            ),
            (
                f"教学策略更新：围绕「{anchor}」继续保持窄回路，"
                "贴着最近卡点推进，先验证再扩范围。"
            ),
            language_context,
        )


    def _normalize_teaching_strategy_context(
        self,
        context: dict[str, str] | None,
    ) -> dict[str, str] | None:
        if not isinstance(context, dict):
            return None

        def normalized(
            key: str,
            *,
            allowed: set[str],
            default: str,
        ) -> str:
            candidate = str(context.get(key, "") or "").strip().lower()
            return candidate if candidate in allowed else default

        return {
            "challenge_level": normalized(
                "challenge_level",
                allowed={"lower", "steady", "raise"},
                default="steady",
            ),
            "hint_depth": normalized(
                "hint_depth",
                allowed={"direct", "guided", "lighter"},
                default="guided",
            ),
            "review_urgency": normalized(
                "review_urgency",
                allowed={"high", "normal", "low"},
                default="normal",
            ),
            "explanation_mode": normalized(
                "explanation_mode",
                allowed={"rebuild", "grounded", "transfer"},
                default="grounded",
            ),
            "next_step_bias": normalized(
                "next_step_bias",
                allowed={"shrink", "steady", "widen"},
                default="steady",
            ),
        }

    def _preferred_strategy_record(
        self,
        lane_snapshot: LaneMemorySnapshot,
        *,
        scenario: str,
        focus_area: str,
    ) -> TeachingStrategyEffectivenessRecord | None:
        records = list(getattr(lane_snapshot, "teaching_strategy_effectiveness", []) or [])
        if not records:
            return None

        normalized_scenario = scenario.strip().lower()
        normalized_focus = focus_area.strip().lower()
        candidates = [item for item in records if item.total_count >= 3]
        if not candidates:
            return None

        scenario_matches = [
            item
            for item in candidates
            if normalized_scenario and item.scenario.strip().lower() == normalized_scenario
        ]
        focus_matches = [
            item
            for item in scenario_matches
            if normalized_focus and item.focus_area.strip().lower() == normalized_focus
        ]
        candidate_pool = focus_matches or scenario_matches or candidates
        positive_candidates = [
            item
            for item in candidate_pool
            if item.success_count >= 2 and item.total_count > 0 and (item.success_count / item.total_count) >= 0.67
        ]
        if not positive_candidates:
            return None
        return max(
            positive_candidates,
            key=lambda item: (
                1 if normalized_focus and item.focus_area.strip().lower() == normalized_focus else 0,
                1 if normalized_scenario and item.scenario.strip().lower() == normalized_scenario else 0,
                item.success_count / item.total_count if item.total_count else 0.0,
                item.success_count,
                item.total_count,
                item.last_updated_at,
            ),
        )

    def _apply_preferred_strategy_bias(
        self,
        *,
        preferred_record: TeachingStrategyEffectivenessRecord,
        challenge_level: str,
        hint_depth: str,
        review_urgency: str,
        explanation_mode: str,
        next_step_bias: str,
        repeated_failure: bool,
        abandoned: bool,
    ) -> tuple[tuple[str, str, str, str, str], bool]:
        safety_locked = repeated_failure or abandoned or next_step_bias == "shrink"

        def apply_value(current: str, preferred: str, *, blocked: set[str]) -> str:
            if safety_locked and preferred in blocked:
                return current
            return preferred

        blended = (
            apply_value(challenge_level, preferred_record.challenge_level, blocked={"raise"}),
            apply_value(hint_depth, preferred_record.hint_depth, blocked={"lighter"}),
            apply_value(review_urgency, preferred_record.review_urgency, blocked={"low"}),
            apply_value(explanation_mode, preferred_record.explanation_mode, blocked={"transfer"}),
            apply_value(next_step_bias, preferred_record.next_step_bias, blocked={"widen"}),
        )
        changed = blended != (
            challenge_level,
            hint_depth,
            review_urgency,
            explanation_mode,
            next_step_bias,
        )
        return blended, changed

    def _strategy_preference_evidence(
        self,
        preferred_record: TeachingStrategyEffectivenessRecord,
        *,
        language_context: str,
    ) -> str:
        focus_label = preferred_record.focus_area.strip() or preferred_record.scenario.strip() or "current lane"
        strategy_label = (
            f"{preferred_record.challenge_level}/{preferred_record.hint_depth}/"
            f"{preferred_record.explanation_mode}/{preferred_record.next_step_bias}"
        )
        return _localized_memory_text(
            (
                f"Evidence-backed coaching preference for {focus_label}: "
                f"{preferred_record.success_count}/{preferred_record.total_count} useful outcomes with "
                f"{strategy_label}."
            ),
            (
                f"证据支持的教学偏好：在「{focus_label}」这类训练里，"
                f"{preferred_record.success_count}/{preferred_record.total_count} 次更有效，"
                f"策略组合是 {strategy_label}。"
            ),
            language_context or focus_label,
        )
