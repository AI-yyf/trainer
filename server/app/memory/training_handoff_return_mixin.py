"""Training-handoff return/evidence domain mixin for :class:`MemoryService`.

Verified handoff evidence extraction, card-return evidence + plan-runtime
binding, evidence enqueueing, returned-card crediting, current-handoff
lookup, and handoff progress persistence. Methods are extracted verbatim
from ``memory/service.py`` (pure code motion, zero behavior change); the
shared ``MemoryService`` state they touch is declared under
``TYPE_CHECKING`` only and is assigned in ``MemoryService.__init__`` or
defined elsewhere on the class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from ..core.models import EvidenceItem, TrainingCardCandidateSnapshot
from ..training.handoff import (
    HandoffStatus,
    ProjectHandoff,
    TrainingHandoffGenerator,
    TrainingPhase,
)
from ..training.plan_binding import binding_matches_plan
from ..workspace.remote_identity import validate_remote_verification_artifact
from .models import utc_now
from .workspace_recovery import (
    formal_plan_is_live_runtime_identity,
    leftover_formal_training_labels,
)

if TYPE_CHECKING:
    from .service import StructuredMemoryService


class TrainingHandoffReturnMixin:
    """Hosts the training-handoff return/evidence methods of ``MemoryService``."""

    if TYPE_CHECKING:
        # Shared MemoryService collaborators used by the methods below.
        _apply_card_learning_phase: Callable[..., Any]
        _leftover_persist_context: Callable[..., Any]
        _live_training_persist_chrome: Callable[..., Any]
        def _persist_structured(self, workspace_id: str) -> None: ...
        _record_training_event: Callable[..., Any]
        def _structured_for(self, workspace_id: str) -> StructuredMemoryService: ...
        _sync_live_evidence_binding: Callable[..., Any]
        def _training_handoff_generator(self, workspace_id: str) -> TrainingHandoffGenerator: ...
        enqueue_evidence: Callable[..., Any]
        evidence_queue: Callable[..., Any]
        get_card: Callable[..., Any]
        persist_plan_runtime_recovery: Callable[..., Any]
        transition_card_status: Callable[..., Any]

    @staticmethod
    def _verified_training_handoff_evidence(
        handoff: ProjectHandoff,
    ) -> tuple[str, str]:
        verified = [
            record
            for record in handoff.evidence
            if record.verified and record.content.strip()
        ]
        if not verified:
            raise ValueError("A completed Return requires trusted verification evidence.")
        summary = "\n".join(dict.fromkeys(record.content.strip() for record in verified[-3:]))
        source = next(
            (
                record.verification_source.strip()
                for record in reversed(verified)
                if record.verification_source.strip()
            ),
            "",
        )
        if not source:
            raise ValueError("Trusted verification evidence is missing its verifier source.")
        return summary, source

    def _training_return_evidence_for_card(
        self,
        workspace_id: str,
        card_id: str,
    ) -> EvidenceItem | None:
        queue = self.evidence_queue(workspace_id)
        for item in (*queue.pending, *queue.adopted, *queue.history, *queue.deferred):
            if item.source == "training_handoff_return" and item.source_card_id == card_id:
                return item
        return None

    def _training_return_plan_runtime_bind(
        self,
        workspace_id: str,
        card: TrainingCardCandidateSnapshot,
    ) -> dict[str, Any]:
        """Reuse recovered runtime and the existing card. Do not invent a plan or next step."""

        leftover_plan, leftover_runtime, leftover_task = self._leftover_persist_context(workspace_id)
        recovered = leftover_runtime if leftover_runtime else None
        recovered_step = str(
            (recovered or {}).get("current_step") or (recovered or {}).get("currentStep") or ""
        ).strip()
        recovered_next = str(
            (recovered or {}).get("next_after_current")
            or (recovered or {}).get("nextAfterCurrent")
            or ""
        ).strip()
        recovered_why = str(
            (recovered or {}).get("why_now") or (recovered or {}).get("whyNow") or ""
        ).strip()
        recovered_stage = str(
            (recovered or {}).get("current_stage_id")
            or (recovered or {}).get("currentStageId")
            or ""
        ).strip()
        live_plan = formal_plan_is_live_runtime_identity(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            current_step=recovered_step,
        )
        binding = card.plan_binding
        stale_binding = binding is not None and not binding_matches_plan(
            binding, leftover_plan, leftover_runtime or {}
        )
        leftover_labels = leftover_formal_training_labels(
            plan=leftover_plan,
            task_title=leftover_task,
            live_plan=live_plan,
            live_task=False,
        )
        leftover_stage_ids = {
            str(getattr(stage, "id", "") or "").strip()
            for stage in (getattr(leftover_plan, "stages", None) or [])
            if leftover_plan is not None and not live_plan and str(getattr(stage, "id", "") or "").strip()
        }
        card_title = (card.title or "").strip()
        card_next = (card.next_after_completion or "").strip()
        card_stage = card.plan_links[0] if card.plan_links else ""
        if live_plan:
            if recovered_step and recovered_step not in leftover_labels:
                current_step = recovered_step
            elif card_title and card_title not in leftover_labels:
                current_step = card_title
            else:
                current_step = recovered_step if recovered_step not in leftover_labels else ""
            if recovered_next and recovered_next not in leftover_labels:
                next_after = recovered_next
            elif card_next and card_next not in leftover_labels:
                next_after = card_next
            else:
                next_after = recovered_next if recovered_next not in leftover_labels else ""
            why_now = recovered_why if recovered_why not in leftover_labels else recovered_why
            if recovered_stage and recovered_stage not in leftover_stage_ids:
                current_stage_id = recovered_stage
            else:
                current_stage_id = recovered_stage or card_stage
        else:
            # Leftover formal identity may stay stored. Bind the live card/runtime, not leftover labels.
            current_step = (
                recovered_step
                if recovered_step and recovered_step not in leftover_labels
                else card_title
            )
            next_after = (
                recovered_next
                if recovered_next and recovered_next not in leftover_labels
                else card_next
            )
            why_now = recovered_why if recovered_why and recovered_why not in leftover_labels else ""
            current_stage_id = (
                recovered_stage
                if recovered_stage and recovered_stage not in leftover_stage_ids
                else ""
            )
        return {
            "current_step": current_step,
            "next_after_current": next_after,
            "why_now": why_now,
            "current_stage_id": current_stage_id,
            "leftover_labels": leftover_labels,
            "live_plan": live_plan,
            "stale_binding": stale_binding,
        }

    def _bind_training_return_evidence_to_plan_runtime(
        self,
        *,
        workspace_id: str,
        card: TrainingCardCandidateSnapshot,
        evidence: EvidenceItem,
    ) -> None:
        bind = self._training_return_plan_runtime_bind(workspace_id, card)
        if not bind["current_step"] or bind["stale_binding"]:
            return
        self.persist_plan_runtime_recovery(
            workspace_id,
            plan_runtime={
                "current_step": bind["current_step"],
                "current_stage_id": bind["current_stage_id"],
                "why_now": bind["why_now"],
                "next_after_current": bind["next_after_current"],
                "verify_method": [evidence.summary] if evidence.summary else [],
                "resume_state": "waiting",
            },
            evidence_binding=evidence.id,
            request_id=evidence.id,
            replace_evidence_binding=True,
        )
        self._sync_live_evidence_binding(workspace_id)

    def _enqueue_training_return_evidence(
        self,
        *,
        workspace_id: str,
        card: TrainingCardCandidateSnapshot,
        summary: str,
        verification_source: str,
    ) -> EvidenceItem:
        workspace = self._structured_for(workspace_id)._workspace
        latest = workspace.get("latest_training_verification")
        artifact = None
        if workspace.get("remote_name") or str(workspace.get("canonical_project_path") or "").startswith("vscode-remote://"):
            if not isinstance(latest, dict) or latest.get("card_id") != card.card_id or latest.get("passed") is not True:
                raise ValueError("Remote Return requires verified bytes for this card.")
            artifact = validate_remote_verification_artifact(
                latest.get("verification_artifact"), str(workspace.get("canonical_project_path") or ""),
            )
        existing = self._training_return_evidence_for_card(workspace_id, card.card_id)
        if existing is not None and existing.verified:
            self._bind_training_return_evidence_to_plan_runtime(
                workspace_id=workspace_id,
                card=card,
                evidence=existing,
            )
            return existing
        bind = self._training_return_plan_runtime_bind(workspace_id, card)
        leftover_labels = bind["leftover_labels"]
        live_plan = bool(bind["live_plan"])
        concepts: list[str] = []
        binding = card.plan_binding
        bound_step = binding.step if binding else bind["current_step"]
        for item in (card.target_skill, card.focus_area, bound_step):
            text = str(item or "").strip()
            if text and text not in leftover_labels and text not in concepts:
                concepts.append(text)
        card_title = (card.title or "").strip()
        if live_plan and card_title and card_title not in concepts:
            concepts.append(card_title)
        item = self.enqueue_evidence(
            workspace_id,
            EvidenceItem(
                summary=summary,
                source="training_handoff_return",
                source_card_id=card.card_id,
                concepts=concepts,
                outcome="pass",
                confidence=0.9,
                target_plan_stage_id=binding.stage_id if binding else (
                    card.plan_links[0] if card.plan_links else ""
                ),
                target_plan_id=binding.plan_id if binding else "",
            ).model_copy(update={"verification_artifact": artifact} if artifact is not None else {}),
            verified=True,
            verification_source=verification_source,
            auto_bind_current_plan=binding is None,
            bound_plan_step=binding.step if binding else "",
        )
        persisted = self._training_return_evidence_for_card(workspace_id, card.card_id)
        if persisted is None or persisted.id != item.id or not persisted.verified:
            raise RuntimeError("Training return evidence was not persisted.")
        self._bind_training_return_evidence_to_plan_runtime(
            workspace_id=workspace_id,
            card=card,
            evidence=persisted,
        )
        return persisted

    def _credit_returned_training_card(
        self,
        workspace_id: str,
        card: TrainingCardCandidateSnapshot,
    ) -> TrainingCardCandidateSnapshot:
        current_card = card
        if current_card.status in {"candidate", "needs_primer", "blocked", "skipped"}:
            current_card = self.transition_card_status(
                workspace_id,
                current_card.card_id,
                "active",
                reason="Return is applying already-trusted verification evidence.",
            ).card
        if current_card.status == "active":
            current_card = self.transition_card_status(
                workspace_id,
                current_card.card_id,
                "implemented",
                reason="Learn, Try, Verify, Reflect, and Return completed with persisted evidence.",
                verified_by_evaluator=True,
            ).card
        if current_card.status not in {"implemented", "completed"}:
            raise ValueError("Return can only credit a training card that is active or already implemented.")
        return current_card

    def _current_training_handoff(
        self,
        workspace_id: str,
        card_id: str,
        handoff_id: str = "",
    ) -> tuple[StructuredMemoryService, TrainingCardCandidateSnapshot, TrainingHandoffGenerator, ProjectHandoff]:
        structured = self._structured_for(workspace_id)
        card = self.get_card(workspace_id, card_id)
        if card is None:
            raise LookupError("Training card not found.")
        payload = structured._workspace.get("latest_training_handoff")
        if not isinstance(payload, dict):
            raise LookupError("No training handoff is available for this card.")
        generator = self._training_handoff_generator(workspace_id)
        handoff = generator.hydrate_handoff(payload)
        if handoff is None or not handoff.handoff_id:
            raise ValueError("The current training handoff is invalid.")
        if handoff.card_id != card.card_id:
            raise ValueError("The current training handoff belongs to a different card.")
        requested_handoff_id = handoff_id.strip()
        if requested_handoff_id and requested_handoff_id != handoff.handoff_id:
            raise ValueError("The requested training handoff is no longer current.")
        return structured, card, generator, handoff

    def _persist_training_handoff_progress(
        self,
        *,
        workspace_id: str,
        structured: StructuredMemoryService,
        card: TrainingCardCandidateSnapshot,
        handoff: ProjectHandoff,
        return_evidence_persisted: bool | None = None,
    ) -> dict[str, Any]:
        verified_summary, verification_source = self._verified_training_handoff_evidence(handoff)
        queued_return = self._training_return_evidence_for_card(workspace_id, card.card_id)
        evidence_persisted = (
            return_evidence_persisted
            if return_evidence_persisted is not None
            else bool(queued_return is not None and queued_return.verified)
        )
        evidence_failed = return_evidence_persisted is False or (
            handoff.phase is TrainingPhase.RETURN
            and handoff.status is HandoffStatus.COMPLETED
            and not evidence_persisted
        )
        returned = (
            handoff.phase is TrainingPhase.RETURN
            and handoff.status is HandoffStatus.COMPLETED
            and evidence_persisted
        )
        return_mode = "result" if returned else "return_required"
        next_hop_status = (
            "continued_in_chat"
            if returned
            else "evidence_unverified"
            if evidence_failed
            else "return_required"
        )
        continue_in = "chat" if returned else "training"
        accepted_into = "coach" if returned else "training"
        handoff_status = "verified" if returned else "unverified" if evidence_failed else "ready_to_return"
        next_after_completion = (
            "Return to Coach with the verified result, then route the next card."
            if returned
            else "Retry Return so the verified result is persisted as plan evidence."
            if evidence_failed
            else "Complete Return to persist the verified result and credit this card."
        )
        fallback_action = (
            "Ask Coach for the next training card."
            if returned
            else "Retry Return. The last evidence write did not persist."
            if evidence_failed
            else "Complete Return when the recorded reflection is accurate."
        )
        card = self._apply_card_learning_phase(workspace_id, card, handoff.phase.value)
        persist_chrome = self._live_training_persist_chrome(
            workspace_id,
            card_title=card.title,
        )
        live_card_title = persist_chrome["selected_card_title"]
        handoff_payload = TrainingHandoffGenerator._handoff_payload(handoff)
        latest = structured._workspace.get("latest_training_verification")
        if isinstance(latest, dict) and latest.get("card_id") == card.card_id:
            handoff_payload["verification_artifact"] = latest.get("verification_artifact")
        handoff_state = {
            "candidate_id": card.card_id,
            "candidate_type": "practice_candidate",
            "target_kind": "training_card",
            "target_id": card.card_id,
            "continue_in": continue_in,
            "accepted_into": accepted_into,
            "handoff_status": handoff_status,
            "handoff_summary": verified_summary,
            "blocked_by": "",
            "coach_only": False,
            "card_type": card.card_type,
            "card_title": live_card_title,
            "scenario_pack": card.scenario_pack,
            "verification_steps": [] if returned else ["Complete Return after reviewing the reflection."],
            "success_signal": verified_summary if returned else "",
            "return_with": verified_summary,
            "next_after_completion": card.next_after_completion or next_after_completion,
            "fallback_action": fallback_action,
            "return_mode": return_mode,
            "return_summary": verified_summary,
            "judged_at": utc_now().isoformat(),
            "source_chain": ["training", verification_source, "training_handoff"],
        }
        handoff_state.update(handoff_payload)
        handoff_state["card_title"] = live_card_title
        next_hop = {
            "candidate_id": card.card_id,
            "candidate_type": "practice_candidate",
            "title": live_card_title,
            "summary": verified_summary,
            "why_now": (
                "This card completed Learn, Try, Verify, Reflect, and Return with trusted evidence."
                if returned
                else "Return evidence was not persisted, so this card is not credited."
                if evidence_failed
                else "The reflection is recorded. Complete Return to persist the verified result."
            ),
            "project_scope": "current_project",
            "continue_in": continue_in,
            "target_kind": "training_card",
            "target_id": card.card_id,
            "accepted_into": accepted_into,
            "status": next_hop_status,
            "status_reason": verified_summary,
            "blocked_by": "",
            "handoff_status": handoff_status,
            "handoff_summary": verified_summary,
            "coach_only": False,
            "card_type": card.card_type,
            "card_title": live_card_title,
            "scenario_pack": card.scenario_pack,
            "return_mode": return_mode,
            "return_summary": verified_summary,
            "judged_at": utc_now().isoformat(),
            "next_after_completion": card.next_after_completion or next_after_completion,
            "fallback_action": fallback_action,
            "source_chain": ["training", verification_source, "training_handoff"],
            "handoff_id": handoff.handoff_id,
            "verification_state": handoff.verification_state,
            "return_state": handoff.return_state,
            "learning_phase": handoff.phase.value,
            "resume_token": handoff.resume_token,
            "completion_claim": handoff.handoff_content.completion_claim,
            "resume_action": handoff.handoff_content.resume_action,
        }
        workspace_update = structured.update_workspace(
            workspace_id=workspace_id,
            latest_training_submode="practice",
            latest_training_handoff=handoff_state,
            latest_training_next_hop=next_hop,
            latest_learning_focus_area=card.focus_area or card.target_skill,
            latest_learning_followup=card.next_after_completion or next_after_completion,
            latest_learning_verified_result=verified_summary if returned else "",
            latest_learning_blocker="",
            latest_learning_partial_progress="" if returned else handoff.reflection,
            latest_learning_outcome=(
                "tests_passed" if returned else "unverified" if evidence_failed else "return_required"
            ),
            selected_card_id=card.card_id,
            selected_card_type=card.card_type,
            selected_card_title=live_card_title,
            selected_card_status=card.status,
        )
        self._record_training_event(
            structured,
            event_type="training_handoff_returned" if returned else "training_handoff_reflection_recorded",
            payload={
                "selected_card_id": card.card_id,
                "candidate_status": card.status,
                "handoff_id": handoff.handoff_id,
                "learning_phase": handoff.phase.value,
                "return_mode": return_mode,
                "source_chain": ["training", verification_source, "training_handoff"],
            },
        )
        self._persist_structured(workspace_id)
        return dict(workspace_update)
