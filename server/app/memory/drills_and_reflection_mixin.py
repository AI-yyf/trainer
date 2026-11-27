from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import HTTPException

from ..core.event_ledger import (
    EVENT_PRACTICE_SUBMISSION_RECORDED,
)
from ..core.models import (
    CoachDefaults,
    DependencySkillMapHistoryEntry,
    DependencySkillMapSnapshot,
    ReviewArtifactHistoryEntry,
    ReviewArtifactSnapshot,
    ReviewQueueAction,
    ScenarioLab,
    ScenarioLabHistoryEntry,
    TheoryDrillHistoryEntry,
    TheoryDrillSnapshot,
    UserProfile,
)
from ..llm.turn_grounding import (
    sanitize_memory_anchor,
)
from ..training.handoff import (
    TrainingPhase,
)
from .coaching_adaptation_mixin import (
    _localized_memory_text,
    _normalize_text_items,
    _workspace_language,
)
from .models import (
    utc_now,
)
from .provenance_admission import (
    _BACKED_PROVENANCES,
    _admit_reflection_fields,
    _MemoryProvenanceAdmission,
    _resolve_memory_provenance_admission,
)
from .review_intervention import (
    REVIEW_INTERVENTION_KEY,
    merge_review_engagement,
    merge_review_refusal,
)
from .review_scheduler import ReviewRating
from .structured_memory_service import (
    StructuredMemoryService,
)
from .workspace_recovery import (
    COACHING_FOCUS_KEY,
    EVALUATION_KEY,
    normalize_latest_coaching_focus,
    normalize_latest_evaluation,
)

logger = logging.getLogger(__name__)


class DrillsAndReflectionMixin:
    if TYPE_CHECKING:
        _build_dependency_skill_map: Any
        _build_theory_drill_snapshot: Any
        _coach_defaults_workspace_patch: Any
        _current_training_handoff: Any
        _dependency_mastery_snapshots: Any
        _ensure_stage_progress: Any
        _extract_answer_policy: Any
        _extract_background: Any
        _extract_blocker: Any
        _extract_learner_name: Any
        _extract_learning_mode: Any
        _extract_long_term_goal: Any
        _extract_onboarding_request: Any
        _extract_preferred_libraries: Any
        _extract_preferred_stack: Any
        _extract_project_context: Any
        _extract_rhythm_preference: Any
        _extract_teaching_style: Any
        _extract_weekly_hours: Any
        _normalize_dependency_key: Any
        _normalize_focus_area: Any
        _normalize_response_language_label: Any
        _persist_structured: Any
        _persist_training_handoff_progress: Any
        _preserve_highest_mastery_stage: Any
        _record_persisted_card_activity: Any
        _resolve_workspace_for_write: Any
        _review_scheduler: Any
        _structured_for: Any
        _sync_dependency_training_views: Any
        _training_handoff_records: Any
        build_scenario_lab: Any
        record_teaching_assets_from_reflection: Any
        repository: Any
        run_training_reliability: Any

    def restore_scenario_lab_history(
        self,
        workspace_id: str,
        scenario_lab_id: str,
        history_entry_id: str,
        history_version: int,
        note: str = "",
    ) -> tuple[ScenarioLab | None, list[ScenarioLabHistoryEntry]]:
        structured = self._structured_for(workspace_id)
        current = structured._scenario_lab
        target = next(
            (
                item
                for item in structured._scenario_lab_history
                if item.scenario_lab_id == scenario_lab_id
                and item.entry_id == history_entry_id
                and item.version == history_version
            ),
            None,
        )
        if current is None or target is None:
            return None, []
        restored = ScenarioLab.model_validate(target.before_snapshot or target.after_snapshot).model_copy(
            update={
                "version": current.version + 1,
                "last_action": "restore_history",
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._scenario_lab = restored
        structured._scenario_lab_history.append(
            ScenarioLabHistoryEntry(
                entry_id=f"hist-{uuid4().hex[:10]}",
                scenario_lab_id=restored.id,
                action="restore_history",
                version=restored.version,
                note=note,
                before_snapshot=current.model_dump(mode="json"),
                after_snapshot=restored.model_dump(mode="json"),
            )
        )
        structured.update_workspace(latest_training_submode="practice")
        self._persist_structured(workspace_id)
        return restored, list(reversed([item for item in structured._scenario_lab_history if item.scenario_lab_id == restored.id]))

    def apply_review_queue_action(
        self,
        workspace_id: str,
        concept: str,
        action: str,
        *,
        scope: str = "single",
        focus_area: str = "",
        task_hint: str = "",
        note: str = "",
        batch_limit: int = 4,
    ) -> list[ReviewQueueAction]:
        structured = self._structured_for(workspace_id)
        concept = concept.strip()
        concepts = [concept]
        if scope == "focus_area" and focus_area:
            concepts = [
                item.concept
                for item in structured._weaknesses.values()
                if item.last_seen_context == focus_area
            ][:max(1, min(batch_limit, 20))] or [concept]
        now = utc_now()
        outcomes = {
            "accept": "queued", "reset": "needs_more_practice", "snooze": "deferred",
            "skip": "dismissed", "done": "completed",
        }
        created: list[ReviewQueueAction] = []
        for entry_concept in concepts:
            deadline = None
            if action == "reset":
                structured.record_weakness(
                    entry_concept, note or "Review queue signaled more practice is needed.",
                    severity=2, review_after_days=0, context=focus_area,
                )
                mastery = structured._mastery.get(entry_concept)
                if mastery is not None:
                    structured._mastery[entry_concept] = self._review_scheduler.process_mastery_review(
                        mastery, ReviewRating.AGAIN,
                    )
            elif action in {"snooze", "skip", "done"}:
                deadline = now + timedelta(days=1)
                mastery = structured._mastery.get(entry_concept)
                # "Done" is self-reported completion, not a recall answer.
                # It may defer the queue, but it must not update FSRS stability
                # or mastery as if the learner had successfully recalled.
                if mastery is not None:
                    structured._mastery[entry_concept] = replace(
                        mastery, next_review_at=deadline, due_date=deadline,
                    )
                weakness = structured._weaknesses.get(entry_concept)
                if weakness is not None:
                    structured._weaknesses[entry_concept] = replace(
                        weakness, next_review_at=deadline, updated_at=now,
                    )
            created.append(ReviewQueueAction(
                entry_id=f"review-action-{uuid4().hex[:10]}", concept=entry_concept,
                action=action, outcome=outcomes[action], focus_area=focus_area,
                task_hint=task_hint, note=note, scope=scope, created_at=now.isoformat(),
                next_review_at=deadline.isoformat() if deadline else "",
            ))
        structured._review_queue_actions.extend(created)
        previous = structured._review_artifact
        same_review = bool(previous and previous.source == "review_queue" and previous.focus_area == concept)
        if action == "accept" or (action == "reset" and same_review):
            language = _workspace_language(structured._workspace)
            artifact = previous if same_review else ReviewArtifactSnapshot(
                id=f"review-{uuid4().hex[:10]}",
                title=_localized_memory_text(f"Review: {concept}", f"复习：{concept}", language),
                focus_area=concept, source="review_queue", status="active",
                summary=task_hint or note or _localized_memory_text(
                    f"Recall {concept} before the next attempt.", f"先回忆「{concept}」，再核对答案。", language,
                ),
                root_cause=note or _localized_memory_text(
                    f"Explain the boundary of {concept}.", f"解释「{concept}」的边界。", language,
                ),
                guardrail=_localized_memory_text(
                    "Recall first, then check one small example.", "先回忆，再用一个小例子核对答案。", language,
                ),
                next_self_implementation_rule=task_hint or _localized_memory_text(
                    "Explain the rule without looking at your notes.", "不看笔记，用一句话解释这条规则。", language,
                ),
                recommended_recovery_mode="review_queue",
                recommended_actions=[task_hint] if task_hint else [], last_action="reviewed", version=1,
            )
            assert artifact is not None
            if same_review:
                artifact = artifact.model_copy(update={
                    "status": "active", "summary": task_hint or note or artifact.summary,
                    "root_cause": note or artifact.root_cause, "last_action": "reviewed",
                    **({"verified_result": "", "blocker": "", "partial_progress": ""}
                       if artifact.status != "active" else {}),
                    "version": artifact.version + 1, "updated_at": now.isoformat(),
                })
            structured._review_artifact = artifact
            structured._review_artifact_history.append(ReviewArtifactHistoryEntry(
                entry_id=f"hist-{uuid4().hex[:10]}", review_artifact_id=artifact.id,
                action="reviewed", version=artifact.version, note=note,
                before_snapshot=previous.model_dump(mode="json") if same_review and previous else {},
                after_snapshot=artifact.model_dump(mode="json"),
            ))
            structured.update_workspace(latest_training_submode="review_queue")
        elif action == "done" and previous and previous.focus_area in concepts:
            structured._review_artifact = previous.model_copy(update={
                "status": "resolved", "last_action": "resolved",
                "version": previous.version + 1, "updated_at": now.isoformat(),
            })
            structured._review_artifact_history.append(ReviewArtifactHistoryEntry(
                entry_id=f"hist-{uuid4().hex[:10]}", review_artifact_id=previous.id,
                action="resolved", version=previous.version + 1, note=note,
                before_snapshot=previous.model_dump(mode="json"),
                after_snapshot=structured._review_artifact.model_dump(mode="json"),
            ))
        if action in {"snooze", "skip"}:
            intervention_state = merge_review_refusal(
                structured._workspace.get(REVIEW_INTERVENTION_KEY),
                now=now,
                reason=f"queue_{action}",
            )
        elif action in {"accept", "reset", "done"}:
            intervention_state = merge_review_engagement(
                structured._workspace.get(REVIEW_INTERVENTION_KEY),
                now=now,
            )
        else:
            intervention_state = None
        if intervention_state is not None:
            structured.update_workspace(
                review_intervention=intervention_state,
                last_active_at=now.isoformat(),
            )
        self._persist_structured(workspace_id)
        return created

    def apply_review_artifact_action(
        self,
        workspace_id: str,
        review_artifact_id: str,
        action: str,
        note: str = "",
        edit_patch: dict[str, Any] | None = None,
    ) -> tuple[ReviewArtifactSnapshot | None, list[ReviewArtifactHistoryEntry]]:
        structured = self._structured_for(workspace_id)
        artifact = structured._review_artifact
        if artifact is None or artifact.id != review_artifact_id:
            return None, []
        update_payload: dict[str, Any] = {
            "version": artifact.version + 1,
            "last_action": action,
            "updated_at": utc_now().isoformat(),
        }
        if action == "reviewed":
            update_payload["status"] = "active"
        elif action == "resolved":
            update_payload.update({"status": "resolved", "verified_result": artifact.verified_result or note, "blocker": "", "partial_progress": ""})
        elif action == "reopened":
            update_payload["status"] = "active"
        elif action == "archived":
            update_payload["status"] = "archived"
        elif action == "updated" and edit_patch:
            update_payload.update(edit_patch)
            update_payload["status"] = artifact.status
        updated = artifact.model_copy(update=update_payload)
        structured._review_artifact = updated
        if action == "resolved" and updated.focus_area:
            review_completed_at = utc_now()
            next_review_at = review_completed_at + timedelta(days=2)
            structured.update_mastery(
                updated.focus_area,
                delta=0.08,
                confidence=0.72,
                review_after_days=2,
            )
            weakness = structured._weaknesses.get(updated.focus_area)
            if weakness is not None:
                structured._weaknesses[updated.focus_area] = replace(
                    weakness,
                    updated_at=review_completed_at,
                    next_review_at=next_review_at,
                )
            structured._review_queue_actions.append(ReviewQueueAction(
                concept=updated.focus_area, action="done", outcome="completed", note=note,
                created_at=review_completed_at.isoformat(), next_review_at=next_review_at.isoformat(),
            ))
        structured._review_artifact_history.append(
            ReviewArtifactHistoryEntry(
                entry_id=f"hist-{uuid4().hex[:10]}",
                review_artifact_id=updated.id,
                action=action,
                version=updated.version,
                note=note,
                before_snapshot=artifact.model_dump(mode="json"),
                after_snapshot=updated.model_dump(mode="json"),
            )
        )
        structured.update_workspace(
            latest_training_submode="review" if action in {"reviewed", "resolved", "reopened", "updated"} else "review_queue",
            latest_learning_followup=updated.next_self_implementation_rule,
            latest_learning_verified_result=updated.verified_result,
        )
        self._persist_structured(workspace_id)
        return updated, list(reversed([item for item in structured._review_artifact_history if item.review_artifact_id == updated.id]))

    def restore_review_artifact_history(
        self,
        workspace_id: str,
        review_artifact_id: str,
        history_entry_id: str,
        history_version: int,
        note: str = "",
    ) -> tuple[ReviewArtifactSnapshot | None, list[ReviewArtifactHistoryEntry]]:
        structured = self._structured_for(workspace_id)
        current = structured._review_artifact
        target = next(
            (
                item
                for item in structured._review_artifact_history
                if item.review_artifact_id == review_artifact_id
                and item.entry_id == history_entry_id
                and item.version == history_version
            ),
            None,
        )
        if current is None or target is None:
            return None, []
        restored = ReviewArtifactSnapshot.model_validate(target.after_snapshot).model_copy(
            update={
                "version": current.version + 1,
                "last_action": "restore_history",
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._review_artifact = restored
        structured._review_artifact_history.append(
            ReviewArtifactHistoryEntry(
                entry_id=f"hist-{uuid4().hex[:10]}",
                review_artifact_id=restored.id,
                action="restore_history",
                version=restored.version,
                note=note,
                before_snapshot=current.model_dump(mode="json"),
                after_snapshot=restored.model_dump(mode="json"),
            )
        )
        structured.update_workspace(latest_training_submode="review")
        self._persist_structured(workspace_id)
        return restored, list(reversed([item for item in structured._review_artifact_history if item.review_artifact_id == restored.id]))

    def apply_theory_drill_action(
        self,
        workspace_id: str,
        theory_drill_id: str,
        action: str,
        note: str = "",
    ) -> tuple[TheoryDrillSnapshot | None, list[TheoryDrillHistoryEntry]]:
        structured = self._structured_for(workspace_id)
        self._sync_dependency_training_views(structured)
        if structured._theory_drill is None:
            structured._theory_drill = self._build_theory_drill_snapshot(structured)
        theory_drill = structured._theory_drill
        if theory_drill is None or theory_drill.id != theory_drill_id:
            return None, []
        status_map = {"archive": "archived", "reopen": "in_progress"}
        history_action = {"archive": "archived", "reopen": "reopened"}.get(action, action)
        updated = theory_drill.model_copy(
            update={
                "status": status_map.get(action, theory_drill.status),
                "last_action": history_action,
                "version": theory_drill.version + 1,
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._theory_drill = updated
        structured._theory_drill_history.append(
            TheoryDrillHistoryEntry(
                entry_id=f"hist-{uuid4().hex[:10]}",
                theory_drill_id=updated.id,
                action=history_action,
                version=updated.version,
                note=note,
                before_snapshot=theory_drill.model_dump(mode="json"),
                after_snapshot=updated.model_dump(mode="json"),
            )
        )
        structured.update_workspace(latest_training_submode="review", latest_learning_scenario="theory_drill")
        self._persist_structured(workspace_id)
        return updated, list(reversed([item for item in structured._theory_drill_history if item.theory_drill_id == updated.id]))

    def restore_theory_drill_history(
        self,
        workspace_id: str,
        theory_drill_id: str,
        history_entry_id: str,
        history_version: int,
        note: str = "",
    ) -> tuple[TheoryDrillSnapshot | None, list[TheoryDrillHistoryEntry]]:
        structured = self._structured_for(workspace_id)
        current = structured._theory_drill
        target = next(
            (
                item
                for item in structured._theory_drill_history
                if item.theory_drill_id == theory_drill_id
                and item.entry_id == history_entry_id
                and item.version == history_version
            ),
            None,
        )
        if current is None or target is None:
            return None, []
        restored = TheoryDrillSnapshot.model_validate(target.before_snapshot or target.after_snapshot).model_copy(
            update={
                "version": current.version + 1,
                "last_action": "restore_history",
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._theory_drill = restored
        structured._theory_drill_history.append(
            TheoryDrillHistoryEntry(
                entry_id=f"hist-{uuid4().hex[:10]}",
                theory_drill_id=restored.id,
                action="restore_history",
                version=restored.version,
                note=note,
                before_snapshot=current.model_dump(mode="json"),
                after_snapshot=restored.model_dump(mode="json"),
            )
        )
        structured.update_workspace(latest_training_submode="review", latest_learning_scenario="theory_drill")
        self._persist_structured(workspace_id)
        return restored, list(reversed([item for item in structured._theory_drill_history if item.theory_drill_id == restored.id]))

    def apply_dependency_skill_map_action(
        self,
        workspace_id: str,
        *,
        dependency_key: str,
        action: str,
        note: str = "",
        focus_item_key: str = "",
        related_api: str = "",
        scenario: str = "",
        verified_result: str = "",
        transfer_source_workspace_id: str = "",
        transfer_target_workspace_id: str = "",
        transfer_source_context: str = "",
        transfer_target_context: str = "",
        transfer_evidence_summary: str = "",
        verified_by_evaluator: bool = False,
        verification_source: str = "",
    ) -> tuple[list[DependencySkillMapSnapshot], list[DependencySkillMapHistoryEntry], ScenarioLab | None]:
        structured = self._structured_for(workspace_id)
        action = action.strip()
        trusted_verification_source = verification_source.strip()
        advancement_actions = {"mark_practiced", "mark_applied", "mark_transferable"}
        if action in advancement_actions:
            if not verified_by_evaluator or not trusted_verification_source:
                raise ValueError(
                    "Trainer needs current-file verification before it can update dependency mastery."
                )
        trusted_verified_result = verified_result.strip() if verified_by_evaluator else ""
        normalized_key = self._normalize_dependency_key(dependency_key)
        if normalized_key not in structured._dependency_mastery:
            raise HTTPException(
                status_code=404,
                detail="Dependency skill map not found. Refresh Training to load the current map.",
            )
        had_current_map = normalized_key in structured._dependency_skill_maps
        self._sync_dependency_training_views(structured)
        dependency = next(
            (item for item in self._dependency_mastery_snapshots(structured) if item.dependency_key == normalized_key),
            None,
        )
        current_map = structured._dependency_skill_maps.get(normalized_key)
        if dependency is None or current_map is None:
            raise HTTPException(
                status_code=409,
                detail="Dependency skill map is no longer current. Refresh Training and try again.",
            )
        current_payload = structured._dependency_mastery.get(normalized_key) or {}
        current_stage = str(current_payload.get("mastery_stage") or "understood")
        next_stage = current_stage
        progress = list(current_payload.get("mastery_stage_progress") or [])
        blocked_reason = str(current_payload.get("latest_transfer_blocked_reason") or "")
        transfer_evidence_id = str(current_payload.get("latest_transfer_evidence_id") or "")
        transfer_evidence_note = str(current_payload.get("latest_transfer_evidence_summary") or "")
        if action == "mark_practiced":
            next_stage = self._preserve_highest_mastery_stage(current_stage, "practiced")
            progress = self._ensure_stage_progress(progress, next_stage)
            blocked_reason = ""
        elif action == "mark_applied":
            next_stage = self._preserve_highest_mastery_stage(current_stage, "applied")
            progress = self._ensure_stage_progress(progress, next_stage)
            blocked_reason = ""
        elif action == "mark_transferable":
            if transfer_source_workspace_id and transfer_target_workspace_id and transfer_evidence_summary:
                next_stage = self._preserve_highest_mastery_stage(current_stage, "transferable")
                progress = self._ensure_stage_progress(progress, next_stage)
                blocked_reason = ""
                transfer_evidence_id = transfer_evidence_id or f"transfer-{uuid4().hex[:10]}"
                transfer_evidence_note = transfer_evidence_summary
            else:
                next_stage = self._preserve_highest_mastery_stage(current_stage, "applied")
                progress = self._ensure_stage_progress(progress, next_stage)
                blocked_reason = "Transferable mastery needs explicit cross-project migration evidence."
        structured.upsert_dependency_mastery(
            normalized_key,
            dependency_name=dependency.dependency_name,
            apis=list(dependency.apis),
            use_cases=list(dependency.use_cases),
            scenarios=list(dependency.scenarios),
            weakest_points=list(dependency.weakest_points),
            evidence=list(dependency.evidence),
            mastery_stage=next_stage,
            mastery_stage_progress=progress,
            latest_transfer_blocked_reason=blocked_reason,
            latest_transfer_evidence_id=transfer_evidence_id,
            latest_transfer_evidence_summary=transfer_evidence_note,
            latest_transfer_source_workspace_id=transfer_source_workspace_id,
            latest_transfer_target_workspace_id=transfer_target_workspace_id,
            latest_transfer_source_context=transfer_source_context,
            latest_transfer_target_context=transfer_target_context,
        )
        refreshed_dependency = next(
            (item for item in self._dependency_mastery_snapshots(structured) if item.dependency_key == normalized_key),
            dependency,
        )
        updated_map = self._build_dependency_skill_map(
            structured,
            refreshed_dependency,
            previous=current_map if had_current_map else None,
            action=action,
            note=note,
        )
        structured._dependency_skill_maps[normalized_key] = updated_map
        focus_item = next((item for item in updated_map.items if item.key == focus_item_key), None) or (
            updated_map.top_review_items[0] if updated_map.top_review_items else None
        )
        history_entry = DependencySkillMapHistoryEntry(
            entry_id=f"hist-{uuid4().hex[:10]}",
            dependency_key=normalized_key,
            action=action,
            version=updated_map.version,
            focus_item_key=focus_item.key if focus_item else focus_item_key,
            focus_label=focus_item.label if focus_item else "",
            note=note,
            before_snapshot=current_map.model_dump(mode="json"),
            after_snapshot=updated_map.model_dump(mode="json"),
            after_summary=updated_map.priority_summary,
        )
        structured._dependency_skill_map_history.append(history_entry)
        structured.update_workspace(
            latest_learning_followup=note or updated_map.project_first_cut,
            latest_learning_verified_result=(
                trusted_verified_result
                or str(structured._workspace.get("latest_learning_verified_result") or "")
            ),
            latest_training_submode="practice",
        )
        scenario_lab = self.build_scenario_lab(workspace_id)
        self._persist_structured(workspace_id)
        return list(structured._dependency_skill_maps.values()), list(reversed(structured._dependency_skill_map_history)), scenario_lab

    def restore_dependency_skill_map_history(
        self,
        workspace_id: str,
        *,
        dependency_key: str,
        history_entry_id: str,
        note: str = "",
    ) -> tuple[list[DependencySkillMapSnapshot], list[DependencySkillMapHistoryEntry]]:
        structured = self._structured_for(workspace_id)
        normalized_key = self._normalize_dependency_key(dependency_key)
        current_map = structured._dependency_skill_maps.get(normalized_key)
        target = next(
            (
                item
                for item in structured._dependency_skill_map_history
                if item.dependency_key == normalized_key and item.entry_id == history_entry_id
            ),
            None,
        )
        if current_map is None or target is None:
            return [], []
        restored = DependencySkillMapSnapshot.model_validate(target.before_snapshot or target.after_snapshot).model_copy(
            update={
                "version": current_map.version + 1,
                "last_action": "restore_history",
                "last_action_note": note,
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._dependency_skill_maps[normalized_key] = restored
        structured._dependency_skill_map_history.append(
            DependencySkillMapHistoryEntry(
                entry_id=f"hist-{uuid4().hex[:10]}",
                dependency_key=normalized_key,
                action="restore_history",
                version=restored.version,
                focus_item_key=target.focus_item_key,
                focus_label=target.focus_label,
                note=note,
                before_snapshot=current_map.model_dump(mode="json"),
                after_snapshot=restored.model_dump(mode="json"),
                after_summary=restored.priority_summary,
            )
        )
        self._persist_structured(workspace_id)
        return list(structured._dependency_skill_maps.values()), list(reversed(structured._dependency_skill_map_history))

    def record_session_message(
        self,
        session_id: str,
        message: str,
        workspace_id: str | None = None,
    ) -> None:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        self._structured_for(resolved_workspace_id).append_session_message(session_id, message)
        self._persist_structured(resolved_workspace_id)

    def record_recoverable_turn(
        self,
        *,
        workspace_id: str | None = None,
        session_id: str | None,
        user_message: str | None = None,
        scenario: str,
        focus_area: str | None,
        summary: str,
        next_step: str,
        blocker: str | None = None,
        decision: str | None = None,
        teaching_note: str | None = None,
        confidence: str | None = None,
        evidence: list[str] | None = None,
        answer_mode: str | None = None,
        response_language: str | None = None,
        coach_defaults: CoachDefaults | None = None,
        stop_reason: str = "",
    ) -> None:
        """Keep a failed turn resumable without turning it into learning evidence."""
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved_workspace_id)
        cleaned_focus = str(focus_area or "").strip()
        cleaned_summary = summary.strip()
        cleaned_next_step = next_step.strip()
        cleaned_blocker = str(blocker or "").strip()
        cleaned_decision = str(decision or "").strip()
        cleaned_teaching_note = str(teaching_note or "").strip()
        cleaned_confidence = str(confidence or "").strip()
        cleaned_evidence = _normalize_text_items(evidence, limit=4)
        cleaned_user_message = str(user_message or "").strip()
        # Anchor anti-drift (2026-10-08 real-teaching review): the persisted
        # focus must never be a verbatim prefix of the learner message.
        cleaned_focus = sanitize_memory_anchor(cleaned_focus, cleaned_user_message)

        recovery = {
            "scenario": scenario,
            "focus_area": cleaned_focus,
            "summary": cleaned_summary,
            "next_step": cleaned_next_step,
            "blocker": cleaned_blocker,
            "stop_reason": stop_reason.strip(),
            "updated_at": utc_now().isoformat(),
        }
        workspace_patch: dict[str, Any] = {"latest_recovery": recovery}
        if answer_mode:
            workspace_patch["answer_mode"] = answer_mode.strip()
        if response_language:
            workspace_patch["response_language"] = response_language.strip()
        if coach_defaults:
            workspace_patch.update(
                self._coach_defaults_workspace_patch(structured, coach_defaults)
            )
        structured.update_workspace(**workspace_patch)
        if cleaned_user_message:
            self._remember_onboarding_signals(
                resolved_workspace_id,
                structured,
                message=cleaned_user_message,
                summary=cleaned_summary,
                focus_area=cleaned_focus,
                response_language=str(response_language or "").strip(),
            )
        structured.update_active_thread(
            scenario=scenario,
            focus_area=cleaned_focus,
            summary=cleaned_summary,
            next_step=cleaned_next_step,
            blocker=cleaned_blocker,
            decision=cleaned_decision,
            teaching_note=cleaned_teaching_note,
            confidence=cleaned_confidence,
            evidence=cleaned_evidence,
            recovery_state="provider_or_local",
        )
        if session_id:
            structured.update_session_thread(
                session_id,
                focus_area=cleaned_focus,
                scenario=scenario,
                next_step=cleaned_next_step,
                blocker=cleaned_blocker,
                teaching_signal=cleaned_teaching_note or cleaned_blocker,
                decision=cleaned_decision,
                teaching_note=cleaned_teaching_note,
                confidence=cleaned_confidence,
                evidence=cleaned_evidence,
            )
        self._persist_structured(resolved_workspace_id)

    def record_turn_memory(
        self,
        *,
        workspace_id: str | None = None,
        session_id: str | None,
        user_message: str | None = None,
        scenario: str,
        focus_area: str | None,
        summary: str,
        next_step: str,
        answer_mode: str | None = None,
        response_language: str | None = None,
        review_note: str | None = None,
        coach_defaults: CoachDefaults | None = None,
        teaching_goal: str | None = None,
        exercise_prompt: dict[str, Any] | None = None,
        decision: str | None = None,
        teaching_note: str | None = None,
        confidence: str | None = None,
        evidence: list[str] | None = None,
        memory_provenance: Mapping[str, str] | None = None,
    ) -> None:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved_workspace_id)
        admission = _resolve_memory_provenance_admission(memory_provenance)
        admitted = _admit_reflection_fields(
            admission,
            focus_area=focus_area,
            summary=summary,
            next_step=next_step,
            review_note=review_note,
            decision=decision,
            teaching_note=teaching_note,
            evidence=evidence,
        )
        focus_area = admitted.focus_area
        summary = admitted.summary
        next_step = admitted.next_step
        review_note = admitted.review_note
        decision = admitted.decision
        teaching_note = admitted.teaching_note
        evidence = admitted.evidence
        summary_verification_trusted = admission.summary_verification_trusted()
        cleaned_summary = summary.strip()
        cleaned_next_step = next_step.strip()
        cleaned_focus = (focus_area or "").strip()
        normalized_answer_mode = (answer_mode or "").strip()
        normalized_response_language = (response_language or "").strip()
        normalized_teaching_goal = (teaching_goal or "").strip()
        normalized_user_message = (user_message or "").strip()
        normalized_decision = (decision or "").strip()
        normalized_teaching_note = (teaching_note or "").strip()
        normalized_confidence = (confidence or "").strip()
        normalized_evidence = _normalize_text_items(evidence, limit=4)
        # Anchor anti-drift (2026-10-08 real-teaching review): coach_anchor /
        # current_focus inherit this focus, so a verbatim message prefix must
        # never be persisted as focus_area.
        cleaned_focus = sanitize_memory_anchor(cleaned_focus, normalized_user_message)
        if answer_mode:
            structured.remember_preference("answer_mode", answer_mode, source="coach-turn")
        if response_language:
            structured.remember_preference("response_language", response_language, source="coach-turn")
        if cleaned_focus:
            structured.remember_preference("focus_area", cleaned_focus, source="coach-turn")
        if cleaned_focus:
            structured.remember_preference("last_focus_area", cleaned_focus, source="coach-turn")
        if normalized_teaching_goal:
            structured.remember_preference(
                "latest_teaching_goal",
                normalized_teaching_goal,
                source="coach-turn",
            )
        if normalized_decision:
            structured.remember_preference("latest_turn_decision", normalized_decision, source="coach-turn")
        if normalized_teaching_note:
            structured.remember_preference("latest_turn_teaching_note", normalized_teaching_note, source="coach-turn")
        if normalized_confidence:
            structured.remember_preference("latest_turn_confidence", normalized_confidence, source="coach-turn")
        if normalized_evidence:
            structured.remember_preference(
                "latest_turn_evidence",
                " | ".join(normalized_evidence),
                source="coach-turn",
            )
        if normalized_user_message:
            self._remember_onboarding_signals(
                resolved_workspace_id,
                structured,
                message=normalized_user_message,
                summary=cleaned_summary,
                focus_area=cleaned_focus,
                response_language=normalized_response_language,
            )
        if coach_defaults is not None:
            coach_defaults_dumped = coach_defaults.model_dump(exclude_unset=True)
            if "memory_scope" in coach_defaults_dumped:
                structured.remember_preference("memory_scope", coach_defaults.memory_scope, source="coach-defaults")
            if "working_set_mode" in coach_defaults_dumped:
                structured.remember_preference("working_set_mode", coach_defaults.working_set_mode, source="coach-defaults")
            if "review_cadence" in coach_defaults_dumped:
                structured.remember_preference("review_cadence", coach_defaults.review_cadence, source="coach-defaults")
            if "review_reminder_mode" in coach_defaults_dumped:
                structured.remember_preference(
                    "review_reminder_mode",
                    coach_defaults.review_reminder_mode,
                    source="coach-defaults",
                )
        blocker_text = ""
        if review_note:
            blocker_text = review_note.strip()
        existing_active_thread = structured.snapshot().workspace.get("active_thread")
        existing_verified_result = (
            str(existing_active_thread.get("verified_result") or "").strip()
            if isinstance(existing_active_thread, dict)
            else ""
        )
        verified_result = ""
        if cleaned_summary and summary_verification_trusted and (
            "verified" in cleaned_summary.lower()
            or "通过" in cleaned_summary
            or "完成" in cleaned_summary
        ):
            # DESIGN.md §2.7: a model-authored summary is never a verified-
            # mastery basis; only tool_verified / learner_provided summaries
            # may raise the recorded verified result (a previous verified
            # result still carries forward below).
            verified_result = cleaned_summary
        elif existing_verified_result and cleaned_focus:
            existing_focus = str(existing_active_thread.get("focus_area") or "").strip() if isinstance(existing_active_thread, dict) else ""
            if not existing_focus or existing_focus == cleaned_focus:
                verified_result = existing_verified_result
        teaching_signal = (
            normalized_teaching_note
            or normalized_teaching_goal
            or normalized_decision
            or blocker_text
            or cleaned_next_step
            or cleaned_summary
        ).strip()
        continuity_note = " | ".join(
            part
            for part in (
                cleaned_focus,
                cleaned_next_step,
                normalized_decision or blocker_text or normalized_teaching_goal,
            )
            if part
        ).strip()
        workspace_patch: dict[str, Any] = {
            "workspace_id": resolved_workspace_id,
            "latest_turn_scenario": scenario,
            "latest_turn_summary": cleaned_summary,
            "latest_turn_next_step": cleaned_next_step,
            "latest_turn_focus_area": cleaned_focus,
            "latest_turn_verified_result": verified_result,
            "latest_turn_blocker": blocker_text,
            "latest_turn_teaching_signal": teaching_signal,
            "latest_turn_continuity_note": continuity_note,
            "latest_turn_decision": normalized_decision,
            "latest_turn_teaching_note": normalized_teaching_note,
            "latest_turn_confidence": normalized_confidence,
            "latest_turn_evidence": normalized_evidence,
        }
        if normalized_answer_mode:
            workspace_patch["answer_mode"] = normalized_answer_mode
        if response_language:
            workspace_patch["response_language"] = response_language
        if teaching_goal:
            workspace_patch["latest_turn_teaching_goal"] = teaching_goal.strip()
        if isinstance(exercise_prompt, dict) and exercise_prompt:
            workspace_patch["exercise_prompt"] = dict(exercise_prompt)
        if coach_defaults:
            workspace_patch.update(
                self._coach_defaults_workspace_patch(structured, coach_defaults)
            )
        structured.update_workspace(**workspace_patch)
        structured.update_active_thread(
            scenario=scenario,
            focus_area=cleaned_focus,
            summary=cleaned_summary,
            next_step=cleaned_next_step,
            blocker=blocker_text,
            verified_result=verified_result,
            decision=normalized_decision,
            teaching_note=normalized_teaching_note,
            confidence=normalized_confidence,
            evidence=normalized_evidence,
        )
        if session_id:
            structured.update_session_thread(
                session_id,
                focus_area=cleaned_focus,
                scenario=scenario,
                next_step=cleaned_next_step,
                blocker=blocker_text,
                verified_result=verified_result,
                teaching_signal=teaching_signal,
                decision=normalized_decision,
                teaching_note=normalized_teaching_note,
                confidence=normalized_confidence,
                evidence=normalized_evidence,
            )
        topic = cleaned_focus or scenario or "coach-turn"
        toggles = (
            coach_defaults.workspace_memory_toggles.model_dump()
            if coach_defaults
            else {"decisions": True, "patterns": True, "resources": True}
        )
        if cleaned_summary or cleaned_next_step:
            if toggles.get("decisions", True):
                structured.remember_decision(
                    topic,
                    normalized_decision or cleaned_summary or cleaned_next_step,
                    rationale=normalized_teaching_note or review_note or "",
                    next_step=cleaned_next_step,
                )
            if toggles.get("patterns", True):
                structured.remember_progress(
                    scenario,
                    cleaned_focus,
                    cleaned_summary or cleaned_next_step,
                    cleaned_next_step,
                )
            if teaching_signal:
                structured.remember_teaching_signal(
                    key=topic,
                    signal=teaching_signal,
                    source_focus=cleaned_focus,
                    scenario=scenario,
                    source="coach-turn",
                )
        if session_id and cleaned_next_step and toggles.get("patterns", True):
            structured.add_session_highlight(session_id, cleaned_next_step)
        if session_id and cleaned_summary and toggles.get("decisions", True):
            structured.add_session_highlight(session_id, cleaned_summary)
        if normalized_answer_mode:
            structured.remember_preference("teaching_preference.answer_mode", normalized_answer_mode, source="coach-turn")
        if normalized_response_language:
            structured.remember_preference(
                "teaching_preference.response_language",
                normalized_response_language,
                source="coach-turn",
            )
        self._stamp_coach_provenance(resolved_workspace_id, structured, admission)
        self._persist_structured(resolved_workspace_id)

    def _stamp_coach_provenance(
        self,
        workspace_id: str,
        structured: StructuredMemoryService,
        admission: _MemoryProvenanceAdmission,
    ) -> None:
        """Stamp the turn's provenance map when the caller supplied one."""
        if not admission.requested:
            return
        structured.update_workspace(
            latest_coach_provenance=dict(admission.provenance),
            latest_coach_grounding_outcome=admission.outcome,
        )

    def _remember_onboarding_signals(
        self,
        workspace_id: str,
        structured: StructuredMemoryService,
        *,
        message: str,
        summary: str,
        focus_area: str,
        response_language: str,
    ) -> None:
        profile = self.repository.get_profile(workspace_id) or UserProfile()
        profile_updates: dict[str, Any] = {}

        long_term_goal = self._extract_long_term_goal(message)
        if long_term_goal:
            existing_goals = list(profile.long_term_goals or [])
            if not profile.long_term_goal:
                profile_updates["long_term_goal"] = long_term_goal
            if long_term_goal not in existing_goals:
                profile_updates["long_term_goals"] = [long_term_goal, *existing_goals][:4]
            structured.remember_preference("long_term_goal", long_term_goal, source="coach-intake")

        background = self._extract_background(message)
        if background and not profile.background:
            profile_updates["background"] = background
            structured.remember_preference("learner_background", background, source="coach-intake")

        weekly_hours = self._extract_weekly_hours(message)
        if weekly_hours is not None and weekly_hours > 0 and profile.weekly_hours == 4:
            profile_updates["weekly_hours"] = weekly_hours
            structured.remember_preference("weekly_hours", str(weekly_hours), source="coach-intake")
        elif weekly_hours is not None and weekly_hours > 0:
            structured.remember_preference("weekly_hours", str(weekly_hours), source="coach-intake")

        learner_name = self._extract_learner_name(message)
        if learner_name:
            structured.remember_preference("learner_name", learner_name, source="coach-intake")

        teaching_style = self._extract_teaching_style(message)
        if teaching_style and profile.teaching_style in {"guided", "auto"}:
            profile_updates["teaching_style"] = teaching_style
        if teaching_style:
            structured.remember_preference("teaching_style", teaching_style, source="coach-intake")

        answer_policy = self._extract_answer_policy(message)
        if answer_policy and profile.answer_policy in {"guided", "auto"}:
            profile_updates["answer_policy"] = answer_policy
        if answer_policy:
            structured.remember_preference("answer_policy", answer_policy, source="coach-intake")

        preferred_libraries = self._extract_preferred_libraries(message)
        if preferred_libraries:
            merged_libraries = list(dict.fromkeys([*profile.preferred_libraries, *preferred_libraries]))
            profile_updates["preferred_libraries"] = merged_libraries[:12]
            structured.remember_preference(
                "preferred_libraries",
                ", ".join(preferred_libraries[:6]),
                source="coach-intake",
            )

        project_context = self._extract_project_context(message, focus_area=focus_area)
        if project_context:
            structured.remember_preference("project_context", project_context, source="coach-intake")
            if not profile.target_project:
                profile_updates["target_project"] = project_context

        blocker = self._extract_blocker(message)
        if blocker:
            structured.remember_preference("current_blocker", blocker, source="coach-intake")

        rhythm_preference = self._extract_rhythm_preference(message)
        if rhythm_preference:
            structured.remember_preference("preferred_rhythm", rhythm_preference, source="coach-intake")

        preferred_stack = self._extract_preferred_stack(message)
        if preferred_stack:
            structured.remember_preference("preferred_stack", preferred_stack, source="coach-intake")

        learning_mode = self._extract_learning_mode(message)
        if learning_mode:
            structured.remember_preference("preferred_learning_mode", learning_mode, source="coach-intake")

        onboarding_request = self._extract_onboarding_request(message)
        if onboarding_request:
            structured.remember_preference("onboarding_request", onboarding_request, source="coach-intake")

        language_label = self._normalize_response_language_label(response_language, message=message)
        if language_label:
            structured.remember_preference("preferred_language", language_label, source="coach-intake")

        if profile_updates:
            updated_profile = profile.model_copy(update=profile_updates)
            self.repository.save_profile(workspace_id, updated_profile)
            structured.update_profile(**updated_profile.model_dump())

        relationship_notes: list[str] = []
        if long_term_goal:
            relationship_notes.append(
                _localized_memory_text(
                    f"Learner goal clarified: {long_term_goal}",
                    f"学员目标已明确：{long_term_goal}",
                    message,
                )
            )
        if background:
            relationship_notes.append(
                _localized_memory_text(
                    f"Current background: {background}",
                    f"当前基础：{background}",
                    message,
                )
            )
        if learner_name:
            relationship_notes.append(
                _localized_memory_text(
                    f"Learner prefers to be addressed as: {learner_name}",
                    f"学员称呼偏好：{learner_name}",
                    message,
                )
            )
        if blocker:
            relationship_notes.append(
                _localized_memory_text(
                    f"Current blocker to coach around: {blocker}",
                    f"当前需要围绕的卡点：{blocker}",
                    message,
                )
            )
        if rhythm_preference:
            relationship_notes.append(
                _localized_memory_text(
                    f"Preferred training rhythm: {rhythm_preference}",
                    f"偏好的训练节奏：{rhythm_preference}",
                    message,
                )
            )
        if project_context:
            relationship_notes.append(
                _localized_memory_text(
                    f"Project context worth preserving: {project_context}",
                    f"值得持续保留的项目语境：{project_context}",
                    message,
                )
            )
        if preferred_stack:
            relationship_notes.append(
                _localized_memory_text(
                    f"Preferred stack or direction: {preferred_stack}",
                    f"偏好的技术栈或方向：{preferred_stack}",
                    message,
                )
            )
        if learning_mode:
            relationship_notes.append(
                _localized_memory_text(
                    f"Preferred coaching mode: {learning_mode}",
                    f"偏好的教学方式：{learning_mode}",
                    message,
                )
            )
        if onboarding_request:
            relationship_notes.append(
                _localized_memory_text(
                    f"This round is primarily about: {onboarding_request}",
                    f"这轮主要想推进的是：{onboarding_request}",
                    message,
                )
            )
        for note in relationship_notes[:4]:
            structured.remember_teaching_signal(
                key=f"intake::{focus_area or long_term_goal or 'general'}::{abs(hash(note))}",
                signal=note,
                source_focus=focus_area or project_context or long_term_goal,
                scenario="onboarding",
                source="coach-intake",
            )
        if relationship_notes:
            structured.remember_progress(
                "onboarding",
                focus_area or project_context or long_term_goal or "relationship",
                summary or relationship_notes[0],
                next_step=blocker or summary or relationship_notes[-1],
            )
        workspace_updates: dict[str, Any] = {}
        if learner_name:
            workspace_updates["learner_name"] = learner_name
        if project_context:
            workspace_updates["project_context"] = project_context
        if preferred_stack:
            workspace_updates["preferred_stack"] = preferred_stack
        if rhythm_preference:
            workspace_updates["preferred_rhythm"] = rhythm_preference
        if learning_mode:
            workspace_updates["preferred_learning_mode"] = learning_mode
        if onboarding_request:
            workspace_updates["onboarding_request"] = onboarding_request
        if language_label:
            workspace_updates["preferred_language"] = language_label
        if workspace_updates:
            structured.update_workspace(**workspace_updates)

    def save_coach_settings(
        self,
        *,
        workspace_id: str | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        teaching_style: str | None = None,
        coach_defaults: CoachDefaults | None = None,
        follow_current_file: bool | None = None,
        context_detail: str | None = None,
        include_current_file: bool | None = None,
        include_selection: bool | None = None,
        include_diagnostics: bool | None = None,
        include_related_files: bool | None = None,
        resource_search_mode: str | None = None,
    ) -> None:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved_workspace_id)

        workspace_patch: dict[str, Any] = {
            "workspace_id": resolved_workspace_id,
        }

        if answer_mode:
            structured.remember_preference("answer_mode", answer_mode, source="coach-settings")
            workspace_patch["answer_mode"] = answer_mode
        if response_language:
            structured.remember_preference(
                "response_language",
                response_language,
                source="coach-settings",
            )
            workspace_patch["response_language"] = response_language
        normalized_teaching_style = (teaching_style or "").strip()
        if normalized_teaching_style:
            structured.remember_preference(
                "teaching_style",
                normalized_teaching_style,
                source="coach-settings",
            )
            existing_profile = self.repository.get_profile(resolved_workspace_id) or UserProfile()
            updated_profile = existing_profile.model_copy(
                update={"teaching_style": normalized_teaching_style}
            )
            self.repository.save_profile(resolved_workspace_id, updated_profile)
            structured.update_profile(**updated_profile.model_dump())
        if coach_defaults is not None:
            coach_defaults_dumped = coach_defaults.model_dump(exclude_unset=True)
            if "memory_scope" in coach_defaults_dumped:
                structured.remember_preference(
                    "memory_scope",
                    coach_defaults.memory_scope,
                    source="coach-settings",
                )
            if "working_set_mode" in coach_defaults_dumped:
                structured.remember_preference(
                    "working_set_mode",
                    coach_defaults.working_set_mode,
                    source="coach-settings",
                )
            if "review_cadence" in coach_defaults_dumped:
                structured.remember_preference(
                    "review_cadence",
                    coach_defaults.review_cadence,
                    source="coach-settings",
                )
            if "review_reminder_mode" in coach_defaults_dumped:
                structured.remember_preference(
                    "review_reminder_mode",
                    coach_defaults.review_reminder_mode,
                    source="coach-settings",
                )
            workspace_patch.update(
                self._coach_defaults_workspace_patch(structured, coach_defaults)
            )
        if follow_current_file is not None:
            workspace_patch["follow_current_file"] = follow_current_file
        if context_detail:
            workspace_patch["context_detail"] = context_detail
        if include_current_file is not None:
            workspace_patch["include_current_file"] = include_current_file
        if include_selection is not None:
            workspace_patch["include_selection"] = include_selection
        if include_diagnostics is not None:
            workspace_patch["include_diagnostics"] = include_diagnostics
        if include_related_files is not None:
            workspace_patch["include_related_files"] = include_related_files
        normalized_resource_search_mode = (resource_search_mode or "").strip()
        if normalized_resource_search_mode:
            workspace_patch["resource_search_mode"] = normalized_resource_search_mode
            structured.remember_preference(
                "resource_search_mode",
                normalized_resource_search_mode,
                source="coach-settings",
            )

        structured.update_workspace(**workspace_patch)
        self._persist_structured(resolved_workspace_id)

    def record_reflection(
        self,
        task_id: str,
        summary: str,
        action_items: list[str] | None = None,
        workspace_id: str | None = None,
    ) -> None:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        self._structured_for(resolved_workspace_id).add_reflection(task_id, summary, action_items)
        self._persist_structured(resolved_workspace_id)

    def record_coaching_reflection(
        self,
        *,
        workspace_id: str | None = None,
        scenario: str,
        focus_area: str | None,
        summary: str,
        next_step: str,
        review_note: str | None = None,
        decision: str | None = None,
        teaching_note: str | None = None,
        confidence: str | None = None,
        evidence: list[str] | None = None,
        user_message: str | None = None,
        memory_provenance: Mapping[str, str] | None = None,
    ) -> None:
        admission = _resolve_memory_provenance_admission(memory_provenance)
        admitted = _admit_reflection_fields(
            admission,
            focus_area=focus_area,
            summary=summary,
            next_step=next_step,
            review_note=review_note,
            decision=decision,
            teaching_note=teaching_note,
            evidence=evidence,
        )
        focus_area = admitted.focus_area
        summary = admitted.summary
        next_step = admitted.next_step
        review_note = admitted.review_note
        decision = admitted.decision
        teaching_note = admitted.teaching_note
        evidence = admitted.evidence
        cleaned_summary = summary.strip()
        cleaned_next_step = next_step.strip()
        cleaned_review_note = review_note.strip() if review_note else ""
        cleaned_decision = (decision or "").strip()
        cleaned_teaching_note = (teaching_note or "").strip()
        cleaned_confidence = (confidence or "").strip()
        cleaned_evidence = _normalize_text_items(evidence, limit=4)
        # Anchor anti-drift (2026-10-08 real-teaching review): latest_coach_focus_area
        # feeds memory.coach_anchor, so a verbatim message prefix is dropped here.
        cleaned_focus = sanitize_memory_anchor(
            str(focus_area or "").strip(),
            user_message,
        )
        reflection_parts = [
            cleaned_summary,
            cleaned_next_step,
            cleaned_decision,
            cleaned_teaching_note,
        ]
        if review_note:
            reflection_parts.append(cleaned_review_note)
        reflection_summary = " ".join(part for part in reflection_parts if part).strip()
        if not reflection_summary:
            if workspace_id:
                resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
                self._stamp_coach_provenance(
                    resolved_workspace_id,
                    self._structured_for(resolved_workspace_id),
                    admission,
                )
                self._persist_structured(resolved_workspace_id)
            return

        task_id = cleaned_focus or scenario or "coach-turn"
        action_items = [cleaned_next_step] if cleaned_next_step else []
        if cleaned_decision:
            action_items.append(cleaned_decision)
        if cleaned_teaching_note:
            action_items.append(cleaned_teaching_note)
        if cleaned_review_note:
            action_items.append(cleaned_review_note)
        if workspace_id:
            self.record_reflection(task_id, reflection_summary, action_items, workspace_id=workspace_id)
            structured = self._structured_for(workspace_id)
        else:
            return

        workspace_patch: dict[str, Any] = {
            "latest_coach_scenario": scenario,
            "latest_coach_summary": cleaned_summary,
            "latest_coach_next_step": cleaned_next_step,
            "latest_coach_review_note": cleaned_review_note,
            "latest_coach_focus_area": cleaned_focus,
            "latest_coach_reflection": reflection_summary,
            "latest_coach_teaching_signal": cleaned_teaching_note or cleaned_decision or cleaned_review_note or cleaned_next_step or cleaned_summary,
            "latest_coach_decision": cleaned_decision,
            "latest_coach_teaching_note": cleaned_teaching_note,
            "latest_coach_confidence": cleaned_confidence,
            "latest_coach_evidence": cleaned_evidence,
            COACHING_FOCUS_KEY: normalize_latest_coaching_focus(
                {
                    "summary": cleaned_summary,
                    "next_step": cleaned_next_step,
                    "focus_area": cleaned_focus,
                    "teaching_goal": cleaned_teaching_note,
                },
                workspace_id,
                adopt_scope=True,
            ),
        }
        workspace_patch["workspace_id"] = workspace_id
        structured.update_workspace(**workspace_patch)

        latest_session = structured.snapshot().session
        if latest_session:
            structured.update_session_thread(
                latest_session.session_id,
                focus_area=cleaned_focus,
                scenario=scenario,
                blocker=cleaned_review_note,
                teaching_signal=cleaned_teaching_note or cleaned_decision or cleaned_review_note or cleaned_next_step or cleaned_summary,
                decision=cleaned_decision,
                teaching_note=cleaned_teaching_note,
                confidence=cleaned_confidence,
                evidence=cleaned_evidence,
            )

        normalized_focus = self._normalize_focus_area(cleaned_focus)
        # DESIGN.md §2.7: mastery advances only on tool_verified /
        # learner_provided backing. ``admission.focus_backing()`` is ``None``
        # for legacy callers (ungated) and the turn's focus provenance when
        # ``memory_provenance`` was supplied by the assembly.
        focus_backing = admission.focus_backing()
        mastery_allowed = focus_backing is None or focus_backing in _BACKED_PROVENANCES

        if normalized_focus and mastery_allowed:
            structured.update_mastery(
                normalized_focus,
                delta=0.05,
                confidence=0.62,
                review_after_days=2,
            )

        if cleaned_next_step and normalized_focus and mastery_allowed:
            structured.update_mastery(
                f"{normalized_focus.lower().replace(' ', '-')}:next-step",
                delta=0.08,
                confidence=0.68,
                review_after_days=1,
            )

        if cleaned_review_note and normalized_focus:
            structured.record_weakness(
                normalized_focus.lower().replace(" ", "-"),
                cleaned_review_note,
                severity=2,
                review_after_days=2,
                context=cleaned_summary or cleaned_next_step,
            )
        elif cleaned_review_note:
            structured.record_weakness(
                f"{scenario}-review",
                cleaned_review_note,
                severity=2,
                review_after_days=2,
                context=cleaned_summary or cleaned_next_step,
            )
        if cleaned_review_note or cleaned_next_step or cleaned_summary:
            structured.remember_teaching_signal(
                key=normalized_focus or scenario or "coach-reflection",
                signal=cleaned_review_note or cleaned_next_step or cleaned_summary,
                source_focus=(focus_area or "").strip(),
                scenario=scenario,
                source="coach-reflection",
            )
        self.record_teaching_assets_from_reflection(
            workspace_id,
            scenario=scenario,
            focus_area=focus_area,
            summary=cleaned_summary,
            next_step=cleaned_next_step,
            review_note=cleaned_review_note or None,
        )
        self._stamp_coach_provenance(workspace_id, structured, admission)
        self._persist_structured(workspace_id)

    def record_turn_reflection(
        self,
        *,
        workspace_id: str | None = None,
        session_id: str | None = None,
        user_message: str | None = None,
        scenario: str,
        focus_area: str | None,
        summary: str,
        next_step: str,
        review_note: str | None = None,
        decision: str | None = None,
        teaching_note: str | None = None,
        confidence: str | None = None,
        evidence: list[str] | None = None,
        answer_mode: str | None = None,
        response_language: str | None = None,
        coach_defaults: CoachDefaults | None = None,
        teaching_goal: str | None = None,
        exercise_prompt: dict[str, Any] | None = None,
        memory_provenance: Mapping[str, str] | None = None,
    ) -> None:
        """Persist one coach turn under the DESIGN.md §2.7 field-level admission.

        ``memory_provenance`` is the mapping built by
        ``app.llm.turn_grounding.memory_provenance_summary``: per-field
        provenance values (``tool_verified`` / ``learner_provided`` /
        ``model_claim`` / ``local_fallback``) plus the reserved
        ``grounding_outcome`` and ``conflicted_claims`` keys. Without it the
        call keeps the legacy ungated behaviour (direct callers, tests).

        With it:

        - ``next_step`` is admitted only for ``grounded`` / ``corrected``
          outcomes — a downgraded step never reaches thread memory, action
          items or review hints;
        - a ``local_fallback`` turn writes no focus / anchor and no mastery
          bumps (§2.1);
        - mastery bumps require ``tool_verified`` / ``learner_provided`` focus
          backing (§2.7) — a pure ``model_claim`` turn does not advance
          mastery;
        - the summary may only raise the verified result when its provenance
          is fact-backed (§2.7);
        - conflicted claim texts are stripped from the admitted text fields
          (field + claim granularity, no paragraph-level NLP);
        - the normalized provenance map is stamped on the workspace
          (``latest_coach_provenance`` / ``latest_coach_grounding_outcome``).

        The admission itself lives in ``_admit_reflection_fields`` and runs
        inside the two writers (both accept ``memory_provenance``), so this
        entry point and the assembly's direct writer calls share one
        implementation.
        """
        self.record_coaching_reflection(
            workspace_id=workspace_id,
            scenario=scenario,
            focus_area=focus_area,
            summary=summary,
            next_step=next_step,
            review_note=review_note,
            decision=decision,
            teaching_note=teaching_note,
            confidence=confidence,
            evidence=evidence,
            user_message=user_message,
            memory_provenance=memory_provenance,
        )
        self.record_turn_memory(
            workspace_id=workspace_id,
            session_id=session_id,
            user_message=user_message,
            scenario=scenario,
            focus_area=focus_area,
            summary=summary,
            next_step=next_step,
            answer_mode=answer_mode,
            response_language=response_language,
            review_note=review_note,
            coach_defaults=coach_defaults,
            teaching_goal=teaching_goal,
            exercise_prompt=exercise_prompt,
            decision=decision,
            teaching_note=teaching_note,
            confidence=confidence,
            evidence=evidence,
            memory_provenance=memory_provenance,
        )

    def record_evaluation_feedback(
        self,
        *,
        workspace_id: str | None = None,
        concepts: list[str],
        failed_checks: list[str],
        missing_requirements: list[str],
    ) -> None:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved_workspace_id)
        normalized_concepts = [item.strip() for item in concepts if item and item.strip()]
        normalized_failed_checks = [item.strip() for item in failed_checks if item and item.strip()]
        normalized_missing = [item.strip() for item in missing_requirements if item and item.strip()]
        feedback_summary = "; ".join(normalized_failed_checks or normalized_missing or normalized_concepts)
        focus_anchor = normalized_concepts[0] if normalized_concepts else "evaluation"

        structured.update_workspace(
            **{
                "latest_evaluation_feedback": feedback_summary,
                "latest_evaluation_failed_checks": list(normalized_failed_checks),
                "latest_evaluation_missing_requirements": list(normalized_missing),
                EVALUATION_KEY: normalize_latest_evaluation(
                    {
                        "summary": feedback_summary,
                        "next_step": "; ".join(normalized_failed_checks or normalized_missing),
                        "headline": focus_anchor,
                    },
                    resolved_workspace_id,
                    adopt_scope=True,
                ),
            }
        )
        if feedback_summary:
            structured.remember_teaching_signal(
                key=f"{focus_anchor}::evaluation-feedback",
                signal=feedback_summary,
                source_focus=focus_anchor,
                scenario="review_reflection",
                source="evaluation-feedback",
            )
        self._persist_structured(resolved_workspace_id)

    def record_training_handoff_reflection(
        self,
        *,
        workspace_id: str,
        card_id: str,
        reflection: str,
        handoff_id: str = "",
        request_id: str = "",
        idempotency_key: str = "",
        revision: int = 0,
        timeout_ms: int = 30_000,
        cancel: bool = False,
    ) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            return self._record_training_handoff_reflection_body(
                workspace_id=workspace_id,
                card_id=card_id,
                reflection=reflection,
                handoff_id=handoff_id,
            )

        return self.run_training_reliability(
            workspace_id,
            request_id=request_id,
            command_id="trainer.training.reflect",
            card_id=card_id,
            handoff_id=handoff_id,
            idempotency_key=idempotency_key,
            revision=revision,
            timeout_ms=timeout_ms,
            cancel=cancel,
            learning_phase="reflect",
            work=work,
        )

    def _record_training_handoff_reflection_body(
        self,
        *,
        workspace_id: str,
        card_id: str,
        reflection: str,
        handoff_id: str = "",
    ) -> dict[str, Any]:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured, card, generator, handoff = self._current_training_handoff(
            resolved_workspace_id,
            card_id,
            handoff_id,
        )
        generator._handoff_cache[handoff.handoff_id] = handoff
        if handoff.verification_state == "self_reported" and handoff.phase is TrainingPhase.TRY:
            generator._advance_phase(
                handoff,
                TrainingPhase.VERIFY,
                detail="Migrated self-reported manual result before reflection.",
                recorded_at=utc_now(),
            )
            generator._sync_handoff_verification_state(handoff, "self_reported")
        if handoff.phase is TrainingPhase.REFLECT and handoff.reflection.strip():
            return dict(structured._workspace)
        if handoff.phase is TrainingPhase.RETURN:
            raise ValueError("A completed training handoff cannot be reflected again.")
        reflected = generator.record_reflection(handoff.handoff_id, reflection, handoff=handoff)
        if reflected is None:
            raise LookupError("Training handoff not found.")
        self._training_handoff_records[reflected.handoff_id] = reflected
        self.record_reflection(
            card.card_id,
            reflected.reflection,
            ["Complete Return to persist the verified result."],
            workspace_id=resolved_workspace_id,
        )
        persisted = self._persist_training_handoff_progress(
            workspace_id=resolved_workspace_id,
            structured=structured,
            card=card,
            handoff=reflected,
        )
        self._record_persisted_card_activity(
            resolved_workspace_id, card, EVENT_PRACTICE_SUBMISSION_RECORDED, reflected.handoff_id,
        )
        return persisted
