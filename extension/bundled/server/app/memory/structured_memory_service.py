from __future__ import annotations

import inspect
import logging
from dataclasses import asdict, fields, is_dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from ..core.models import (
    ActiveCardSelectionResult,
    DependencySkillMapHistoryEntry,
    DependencySkillMapSnapshot,
    EvidenceItem,
    FlashcardAttempt,
    FlashDeckSnapshot,
    ReviewArtifactHistoryEntry,
    ReviewArtifactSnapshot,
    ReviewQueueAction,
    ScenarioLab,
    ScenarioLabHistoryEntry,
    TeachingKnowledgeAsset,
    TheoryDrillHistoryEntry,
    TheoryDrillSnapshot,
    TrainingCardCandidateSnapshot,
)
from .coaching_adaptation_mixin import (
    _normalize_text_items,
)
from .models import (
    DecisionRecord,
    LearningOutcomeRecord,
    MasteryRecord,
    PreferenceRecord,
    ProgressRecord,
    ReflectionRecord,
    SessionSummary,
    TeachingSignalRecord,
    TeachingStrategyEffectivenessRecord,
    UserFeedbackRecord,
    WeaknessRecord,
    utc_now,
)
from .models import (
    MemorySnapshot as LaneMemorySnapshot,
)
from .remote_artifact_recovery import restore_return_artifact

logger = logging.getLogger(__name__)




# How strongly each preference source is trusted, and how long its value is
# meant to live. Explicit learner statements outrank one turn's phrasing; a
# repeated value strengthens, a changed value supersedes with an audit trail.
_PREFERENCE_SOURCE_PROFILES: dict[str, tuple[float, str]] = {
    "settings": (0.95, "durable"),
    "user": (0.95, "durable"),
    "learner": (0.95, "durable"),
    "explicit": (0.95, "durable"),
    "coach-defaults": (0.8, "durable"),
    "coach-intake": (0.8, "durable"),
    "coach-settings": (0.95, "durable"),
    "coach-turn": (0.55, "session"),
    "derived": (0.4, "turn"),
}
_PREFERENCE_DURABILITY_RANK: dict[str, int] = {"turn": 0, "session": 1, "durable": 2}


def _stronger_durability(left: str, right: str) -> str:
    left_rank = _PREFERENCE_DURABILITY_RANK.get(left, 0)
    right_rank = _PREFERENCE_DURABILITY_RANK.get(right, 0)
    return left if left_rank >= right_rank else right


class StructuredMemoryService:
    def __init__(self) -> None:
        self._profile: dict[str, Any] = {}
        self._workspace: dict[str, Any] = {}
        self._mastery: dict[str, MasteryRecord] = {}
        self._dependency_mastery: dict[str, dict[str, Any]] = {}
        self._weaknesses: dict[str, WeaknessRecord] = {}
        self._reflections: list[ReflectionRecord] = []
        self._preferences: dict[str, PreferenceRecord] = {}
        self._decisions: dict[str, DecisionRecord] = {}
        self._progress: dict[str, ProgressRecord] = {}
        self._teaching_signals: dict[str, TeachingSignalRecord] = {}
        self._user_feedback: list[UserFeedbackRecord] = []
        self._learning_outcomes: dict[str, LearningOutcomeRecord] = {}
        self._teaching_strategy_effectiveness: dict[str, TeachingStrategyEffectivenessRecord] = {}
        self._teaching_assets: dict[str, TeachingKnowledgeAsset] = {}
        self._sessions: dict[str, SessionSummary] = {}
        self._training_cards: dict[str, TrainingCardCandidateSnapshot] = {}
        self._card_ledger: list[dict[str, Any]] = []
        self._active_training_card_routing: ActiveCardSelectionResult | None = None
        self._evidence_items: dict[str, EvidenceItem] = {}
        self._dependency_skill_maps: dict[str, DependencySkillMapSnapshot] = {}
        self._dependency_skill_map_history: list[DependencySkillMapHistoryEntry] = []
        self._flash_deck: FlashDeckSnapshot | None = None
        self._recent_flash_attempts: list[FlashcardAttempt] = []
        self._theory_drill: TheoryDrillSnapshot | None = None
        self._theory_drill_history: list[TheoryDrillHistoryEntry] = []
        self._scenario_lab: ScenarioLab | None = None
        self._scenario_lab_history: list[ScenarioLabHistoryEntry] = []
        self._review_queue_actions: list[ReviewQueueAction] = []
        self._review_artifact: ReviewArtifactSnapshot | None = None
        self._review_artifact_history: list[ReviewArtifactHistoryEntry] = []
        self._training_event_ledger: list[dict[str, Any]] = []

    def update_profile(self, **profile: Any) -> dict[str, Any]:
        self._profile.update({key: value for key, value in profile.items() if value is not None})
        return dict(self._profile)

    def schedule_mastery_review(
        self,
        concept: str,
        *,
        next_review_at: datetime,
        due_date: datetime | None = None,
        fsrs_state: str | None = None,
        stability: float | None = None,
        difficulty: float | None = None,
        reps: int | None = None,
        lapses: int | None = None,
        step: int | None = None,
        last_reviewed_at: datetime | None = None,
        interval: int | None = None,
        retrievability: float | None = None,
    ) -> MasteryRecord | None:
        """Attach a scheduler's next due date to an existing mastery record.

        Memory retention (FSRS) and capability evidence stay separate: this
        never changes the score and never creates a mastery record.
        """
        current = self._mastery.get(concept)
        if current is None:
            return None
        current.next_review_at = next_review_at
        current.due_date = due_date or next_review_at
        current.review_source = "fsrs"
        if fsrs_state:
            current.fsrs_state = fsrs_state
        if stability is not None:
            current.fsrs_stability = stability
        if difficulty is not None:
            current.fsrs_difficulty = difficulty
        if reps is not None:
            current.fsrs_reps = reps
        if lapses is not None:
            current.fsrs_lapses = lapses
        if step is not None:
            current.fsrs_step = max(0, step)
        if last_reviewed_at is not None:
            current.fsrs_last_review_at = last_reviewed_at
        if interval is not None:
            current.fsrs_interval = max(0, interval)
        if retrievability is not None:
            current.retrievability = max(0.0, min(1.0, retrievability))
        current.fsrs_due = next_review_at
        current.updated_at = utc_now()
        return current

    def update_workspace(self, **workspace: Any) -> dict[str, Any]:
        self._workspace.update({key: value for key, value in workspace.items() if value is not None})
        return dict(self._workspace)

    def update_mastery(
        self,
        concept: str,
        *,
        delta: float,
        confidence: float = 0.5,
        review_after_days: int = 3,
    ) -> MasteryRecord:
        current = self._mastery.get(concept, MasteryRecord(concept=concept, score=0.0, confidence=confidence))
        now = utc_now()
        fsrs_owns_schedule = (
            current.review_source == "fsrs" and current.next_review_at is not None
        )
        next_review_at = (
            current.next_review_at
            if fsrs_owns_schedule
            else now + timedelta(days=review_after_days)
        )
        updated = MasteryRecord(
            concept=concept,
            score=min(max(current.score + delta, 0.0), 1.0),
            confidence=confidence,
            state=current.state,
            retrievability=current.retrievability,
            due_date=current.due_date if fsrs_owns_schedule else next_review_at,
            updated_at=now,
            next_review_at=next_review_at,
            review_source=current.review_source if fsrs_owns_schedule else "heuristic",
            fsrs_stability=current.fsrs_stability,
            fsrs_difficulty=current.fsrs_difficulty,
            fsrs_reps=current.fsrs_reps,
            fsrs_lapses=current.fsrs_lapses,
            fsrs_state=current.fsrs_state,
            fsrs_step=current.fsrs_step,
            fsrs_last_review_at=current.fsrs_last_review_at,
            fsrs_due=current.fsrs_due,
            fsrs_interval=current.fsrs_interval,
        )
        self._mastery[concept] = updated
        return updated

    def upsert_dependency_mastery(
        self,
        dependency_key: str,
        *,
        dependency_name: str = "",
        apis: list[str] | None = None,
        use_cases: list[str] | None = None,
        scenarios: list[str] | None = None,
        weakest_points: list[str] | None = None,
        evidence: list[str] | None = None,
        mastery_stage: str = "understood",
        mastery_stage_progress: list[str] | None = None,
        latest_transfer_blocked_reason: str = "",
        latest_transfer_evidence_id: str = "",
        latest_transfer_evidence_summary: str = "",
        latest_transfer_source_workspace_id: str = "",
        latest_transfer_target_workspace_id: str = "",
        latest_transfer_source_context: str = "",
        latest_transfer_target_context: str = "",
    ) -> dict[str, Any]:
        cleaned_key = dependency_key.strip().lower()
        if not cleaned_key:
            raise ValueError("dependency_key is required")
        current = dict(self._dependency_mastery.get(cleaned_key) or {})
        progress = list(mastery_stage_progress or current.get("mastery_stage_progress") or [])
        if not progress:
            progress = ["understood"]
        if mastery_stage and mastery_stage not in progress:
            progress.append(mastery_stage)
        snapshot = {
            "dependency_key": cleaned_key,
            "dependency_name": dependency_name or current.get("dependency_name") or dependency_key,
            "apis": [item for item in (apis or current.get("apis") or []) if item],
            "use_cases": [item for item in (use_cases or current.get("use_cases") or []) if item],
            "scenarios": [item for item in (scenarios or current.get("scenarios") or []) if item],
            "weakest_points": [item for item in (weakest_points or current.get("weakest_points") or []) if item],
            "evidence": [item for item in (evidence or current.get("evidence") or []) if item],
            "mastery_stage": mastery_stage or current.get("mastery_stage") or "understood",
            "mastery_stage_progress": progress,
            "latest_transfer_blocked_reason": (
                latest_transfer_blocked_reason
                or current.get("latest_transfer_blocked_reason")
                or ""
            ),
            "latest_transfer_evidence_id": latest_transfer_evidence_id or current.get("latest_transfer_evidence_id") or "",
            "latest_transfer_evidence_summary": (
                latest_transfer_evidence_summary
                or current.get("latest_transfer_evidence_summary")
                or ""
            ),
            "latest_transfer_source_workspace_id": (
                latest_transfer_source_workspace_id
                or current.get("latest_transfer_source_workspace_id")
                or ""
            ),
            "latest_transfer_target_workspace_id": (
                latest_transfer_target_workspace_id
                or current.get("latest_transfer_target_workspace_id")
                or ""
            ),
            "latest_transfer_source_context": (
                latest_transfer_source_context
                or current.get("latest_transfer_source_context")
                or ""
            ),
            "latest_transfer_target_context": (
                latest_transfer_target_context
                or current.get("latest_transfer_target_context")
                or ""
            ),
            "updated_at": utc_now().isoformat(),
        }
        self._dependency_mastery[cleaned_key] = snapshot
        return dict(snapshot)

    def record_weakness(
        self,
        concept: str,
        reason: str,
        *,
        severity: int = 1,
        review_after_days: int = 1,
        context: str = "",
    ) -> WeaknessRecord:
        existing = self._weaknesses.get(concept)
        recurrence_count = (existing.recurrence_count + 1) if existing else 1
        weakness = WeaknessRecord(
            concept=concept,
            reason=reason,
            severity=max(severity, existing.severity) if existing else severity,
            recurrence_count=recurrence_count,
            latest_example=reason,
            last_seen_context=context,
            updated_at=utc_now(),
            next_review_at=utc_now() + timedelta(days=review_after_days),
        )
        self._weaknesses[concept] = weakness
        return weakness

    def resolve_weakness(self, concept: str) -> None:
        """Drop a weakness once verified success proves the gap is closed."""
        key = (concept or "").strip()
        if key:
            self._weaknesses.pop(key, None)

    def add_reflection(self, task_id: str, summary: str, action_items: list[str] | None = None) -> ReflectionRecord:
        reflection = ReflectionRecord(task_id=task_id, summary=summary, action_items=list(action_items or []))
        self._reflections.append(reflection)
        self._reflections = self._reflections[-18:]
        return reflection

    def append_session_message(self, session_id: str, message: str, *, max_messages: int = 12) -> SessionSummary:
        summary = self._sessions.setdefault(session_id, SessionSummary(session_id=session_id))
        summary.recent_messages.append(message)
        summary.recent_messages = summary.recent_messages[-max_messages:]
        summary.rolling_summary = "\n".join(summary.recent_messages[-3:])
        summary.updated_at = utc_now()
        return summary

    def add_session_highlight(self, session_id: str, highlight: str, *, max_highlights: int = 6) -> SessionSummary:
        cleaned = highlight.strip()
        summary = self._sessions.setdefault(session_id, SessionSummary(session_id=session_id))
        if not cleaned:
            return summary
        if cleaned in summary.highlights:
            summary.highlights.remove(cleaned)
        summary.highlights.append(cleaned)
        summary.highlights = summary.highlights[-max_highlights:]
        summary.updated_at = utc_now()
        return summary

    def update_session_thread(
        self,
        session_id: str,
        *,
        focus_area: str = "",
        scenario: str = "",
        next_step: str = "",
        blocker: str = "",
        verified_result: str = "",
        teaching_signal: str = "",
        decision: str = "",
        teaching_note: str = "",
        confidence: str = "",
        evidence: list[str] | None = None,
    ) -> SessionSummary:
        summary = self._sessions.setdefault(session_id, SessionSummary(session_id=session_id))
        if focus_area:
            summary.active_focus_area = focus_area
        if scenario:
            summary.last_scenario = scenario
        if next_step:
            summary.latest_next_step = next_step
        if blocker:
            summary.blocker = blocker
        if verified_result:
            summary.verified_result = verified_result
        if teaching_signal:
            summary.teaching_signal = teaching_signal
        if decision:
            summary.decision = decision
        if teaching_note:
            summary.teaching_note = teaching_note
        if confidence:
            summary.confidence = confidence
        if evidence:
            summary.evidence = _normalize_text_items(evidence, limit=4)
        summary.updated_at = utc_now()
        return summary

    def remember_preference(
        self,
        key: str,
        value: str,
        *,
        source: str = "derived",
        confidence: float | None = None,
        durability: str | None = None,
        context: str = "",
    ) -> PreferenceRecord:
        """Remember one preference value with evidence strength.

        Repeating the same value raises ``observations``/``confidence``;
        changing it records ``superseded_value`` so the correction is an
        explicit override, not a silent overwrite. Explicit learner sources
        outrank a single turn's phrasing via ``durability``.
        """
        normalized_source = source.strip().lower() or "derived"
        base_confidence, base_durability = _PREFERENCE_SOURCE_PROFILES.get(
            normalized_source, (0.5, "session")
        )
        resolved_confidence = base_confidence if confidence is None else confidence
        resolved_confidence = min(1.0, max(0.0, resolved_confidence))
        resolved_durability = durability or base_durability
        if resolved_durability not in _PREFERENCE_DURABILITY_RANK:
            resolved_durability = base_durability
        existing = self._preferences.get(key)
        if existing is None:
            record = PreferenceRecord(
                key=key,
                value=value,
                source=source,
                updated_at=utc_now(),
                confidence=resolved_confidence,
                observations=1,
                durability=resolved_durability,
                context=context,
            )
        elif existing.value == value:
            record = replace(
                existing,
                updated_at=utc_now(),
                confidence=min(1.0, max(existing.confidence, resolved_confidence) + 0.05),
                observations=min(99, existing.observations + 1),
                durability=_stronger_durability(existing.durability, resolved_durability),
                context=context or existing.context,
            )
        else:
            record = replace(
                existing,
                value=value,
                source=source,
                updated_at=utc_now(),
                confidence=resolved_confidence,
                observations=1,
                durability=resolved_durability,
                superseded_value=existing.value,
                context=context or existing.context,
            )
        self._preferences[key] = record
        return record

    def remember_decision(
        self,
        topic: str,
        decision: str,
        *,
        rationale: str = "",
        next_step: str = "",
        source: str = "coach",
    ) -> DecisionRecord:
        record = DecisionRecord(
            topic=topic,
            decision=decision,
            rationale=rationale,
            next_step=next_step,
            source=source,
            updated_at=utc_now(),
        )
        self._decisions[topic] = record
        return record

    def remember_progress(
        self,
        lane: str,
        focus_area: str,
        summary: str,
        next_step: str,
    ) -> ProgressRecord:
        key = focus_area.strip() or lane.strip() or "active-thread"
        record = ProgressRecord(
            lane=lane,
            focus_area=focus_area,
            summary=summary,
            next_step=next_step,
            updated_at=utc_now(),
        )
        self._progress[key] = record
        return record

    def remember_teaching_signal(
        self,
        key: str,
        signal: str,
        *,
        source_focus: str = "",
        scenario: str = "",
        source: str = "coach",
    ) -> TeachingSignalRecord:
        record = TeachingSignalRecord(
            key=key,
            signal=signal,
            source_focus=source_focus,
            scenario=scenario,
            source=source,
            updated_at=utc_now(),
        )
        self._teaching_signals[key] = record
        return record

    def remember_learning_outcome(
        self,
        concept: str,
        outcome: str,
        *,
        summary: str = "",
        checks: list[str] | None = None,
        missing_requirements: list[str] | None = None,
        repetition_count: int = 1,
        action_type: str = "",
        verified_by_evaluator: bool = False,
        verified_result: str = "",
    ) -> LearningOutcomeRecord:
        trusted = bool(verified_by_evaluator) and bool((verified_result or "").strip())
        record = LearningOutcomeRecord(
            concept=concept,
            outcome=outcome,
            summary=summary,
            checks=list(checks or []),
            missing_requirements=list(missing_requirements or []),
            repetition_count=max(1, repetition_count),
            action_type=action_type,
            verified_by_evaluator=trusted,
            verified_result=(verified_result or "").strip() if trusted else "",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        key = "::".join(
            [
                concept.strip().lower() or "concept",
                outcome.strip().lower() or "outcome",
                action_type.strip().lower() or "general",
            ]
        )
        self._learning_outcomes[key] = record
        return record

    def remember_teaching_strategy_effectiveness(
        self,
        *,
        scenario: str,
        focus_area: str = "",
        challenge_level: str = "steady",
        hint_depth: str = "guided",
        review_urgency: str = "normal",
        explanation_mode: str = "grounded",
        next_step_bias: str = "steady",
        outcome: str,
        summary: str = "",
        verified_result: str = "",
    ) -> TeachingStrategyEffectivenessRecord:
        normalized_scenario = scenario.strip().lower() or "general"
        key = "::".join(
            [
                normalized_scenario,
                challenge_level.strip().lower() or "steady",
                hint_depth.strip().lower() or "guided",
                review_urgency.strip().lower() or "normal",
                explanation_mode.strip().lower() or "grounded",
                next_step_bias.strip().lower() or "steady",
            ]
        )
        existing = self._teaching_strategy_effectiveness.get(key)
        success_outcomes = {"code_landed", "tests_passed", "concept_answered_correctly"}
        failure_outcomes = {"evaluation", "repeated_error", "task_abandoned", "blocked"}
        success_count = existing.success_count if existing else 0
        failure_count = existing.failure_count if existing else 0
        normalized_outcome_name = outcome.strip().lower()
        # Fail-closed: client tests_passed/code_landed labels need non-empty verified_result.
        trusted_label_success = (
            normalized_outcome_name == "concept_answered_correctly"
            or (
                normalized_outcome_name in {"code_landed", "tests_passed"}
                and bool(verified_result.strip())
            )
        )
        if normalized_outcome_name in success_outcomes and trusted_label_success:
            success_count += 1
        elif normalized_outcome_name in failure_outcomes:
            failure_count += 1
        total_count = success_count + failure_count
        record = TeachingStrategyEffectivenessRecord(
            key=key,
            scenario=normalized_scenario,
            focus_area=focus_area,
            challenge_level=challenge_level,
            hint_depth=hint_depth,
            review_urgency=review_urgency,
            explanation_mode=explanation_mode,
            next_step_bias=next_step_bias,
            success_count=success_count,
            failure_count=failure_count,
            total_count=total_count,
            last_outcome=outcome.strip(),
            last_summary=summary.strip(),
            last_verified_result=verified_result.strip(),
            last_updated_at=utc_now(),
        )
        self._teaching_strategy_effectiveness[key] = record
        return record

    def record_user_feedback(
        self,
        *,
        kind: str,
        message: str,
        focus_area: str = "",
        scenario: str = "",
        training_card_id: str = "",
        plan_id: str = "",
        reply_message_id: str = "",
    ) -> UserFeedbackRecord:
        normalized_kind = kind.strip().lower()
        if reply_message_id:
            for existing in self._user_feedback:
                if existing.reply_message_id == reply_message_id and existing.kind == normalized_kind:
                    return existing
        record = UserFeedbackRecord(
            kind=normalized_kind,
            message=message.strip(),
            focus_area=focus_area.strip(),
            scenario=scenario.strip(),
            training_card_id=training_card_id.strip(),
            plan_id=plan_id.strip(),
            reply_message_id=reply_message_id,
        )
        self._user_feedback.insert(0, record)
        self._user_feedback = self._user_feedback[:24]
        bias = {
            "too_hard": ("lower", "direct", "high", "rebuild", "shrink"),
            "misunderstood": ("lower", "direct", "high", "rebuild", "shrink"),
            "card_unrealistic": ("lower", "guided", "high", "grounded", "shrink"),
            "too_simple": ("raise", "lighter", "low", "transfer", "widen"),
            "resource_incorrect": ("lower", "guided", "high", "grounded", "shrink"),
            "plan_mismatch": ("steady", "guided", "normal", "grounded", "shrink"),
        }
        challenge, hints, urgency, explanation, next_bias = bias.get(
            normalized_kind, ("steady", "guided", "normal", "grounded", "steady")
        )
        if reply_message_id:
            # A request to reshape one explanation is a dated observation,
            # not evidence of mastery, a failure streak, or a standing preference.
            self.remember_teaching_strategy_effectiveness(
                scenario=record.scenario,
                focus_area=record.focus_area,
                challenge_level=challenge,
                hint_depth=hints,
                review_urgency=urgency,
                explanation_mode=explanation,
                next_step_bias=next_bias,
                outcome="user_feedback",
                summary=record.message,
            )
            return record
        self.update_workspace(
            latest_user_feedback_kind=normalized_kind,
            latest_user_feedback=record.message,
            latest_user_feedback_focus=record.focus_area,
            latest_user_feedback_at=record.created_at.isoformat(),
            feedback_next_step_bias=next_bias,
        )
        self.remember_teaching_signal(
            record.focus_area or normalized_kind,
            f"User feedback '{normalized_kind}' requires {next_bias} next step and {hints} support.",
            source_focus=record.focus_area,
            scenario=record.scenario or normalized_kind,
            source="user-feedback",
        )
        self.remember_teaching_strategy_effectiveness(
            scenario=record.scenario or normalized_kind,
            focus_area=record.focus_area,
            challenge_level=challenge,
            hint_depth=hints,
            review_urgency=urgency,
            explanation_mode=explanation,
            next_step_bias=next_bias,
            outcome="user_feedback",
            summary=record.message,
        )
        self.remember_learning_outcome(
            record.focus_area or normalized_kind,
            "repeated_error" if normalized_kind in {"too_hard", "misunderstood", "card_unrealistic", "resource_incorrect"} else "concept_answered_correctly" if normalized_kind == "too_simple" else "evaluation",
            summary=record.message,
            action_type="user_feedback",
            repetition_count=2 if normalized_kind in {"too_hard", "misunderstood"} else 1,
        )
        return record

    def upsert_teaching_asset(self, asset: TeachingKnowledgeAsset) -> TeachingKnowledgeAsset:
        normalized = asset.model_copy(update={"updated_at": utc_now().isoformat()})
        if not normalized.created_at:
            normalized = normalized.model_copy(update={"created_at": utc_now().isoformat()})
        self._teaching_assets[normalized.id] = normalized
        return normalized

    def list_teaching_assets(
        self,
        *,
        scope: str | None = None,
        workspace_id: str | None = None,
    ) -> list[TeachingKnowledgeAsset]:
        assets = list(self._teaching_assets.values())
        if scope is not None:
            assets = [item for item in assets if item.scope == scope]
        if workspace_id is not None:
            assets = [
                item
                for item in assets
                if item.workspace_id == workspace_id
                or (item.scope == "general" and item.workspace_id == "__global__")
            ]
        return sorted(assets, key=lambda item: (item.updated_at or "", item.usage_count), reverse=True)

    def update_active_thread(
        self,
        *,
        scenario: str,
        focus_area: str,
        summary: str,
        next_step: str,
        blocker: str = "",
        verified_result: str = "",
        decision: str = "",
        teaching_note: str = "",
        confidence: str = "",
        evidence: list[str] | None = None,
        recovery_state: str = "",
    ) -> dict[str, Any]:
        active_thread: dict[str, Any] = {
            "scenario": scenario,
            "focus_area": focus_area,
            "summary": summary,
            "next_step": next_step,
            "blocker": blocker,
            "verified_result": verified_result,
            "updated_at": utc_now().isoformat(),
        }
        if decision:
            active_thread["decision"] = decision
        if teaching_note:
            active_thread["teaching_note"] = teaching_note
        if confidence:
            active_thread["confidence"] = confidence
        if evidence:
            active_thread["evidence"] = _normalize_text_items(evidence, limit=4)
        if recovery_state:
            active_thread["recovery_state"] = recovery_state
        self._workspace["active_thread"] = active_thread
        return dict(active_thread)

    def snapshot(self) -> LaneMemorySnapshot:
        return LaneMemorySnapshot(
            profile=dict(self._profile),
            workspace=dict(self._workspace),
            mastery=sorted(self._mastery.values(), key=lambda item: item.updated_at, reverse=True),
            weaknesses=sorted(
                self._weaknesses.values(),
                key=lambda item: (item.severity, item.updated_at),
                reverse=True,
            ),
            reflections=list(self._reflections),
            preferences=sorted(self._preferences.values(), key=lambda item: item.updated_at, reverse=True),
            decisions=sorted(self._decisions.values(), key=lambda item: item.updated_at, reverse=True),
            progress=sorted(self._progress.values(), key=lambda item: item.updated_at, reverse=True),
            teaching_signals=sorted(
                self._teaching_signals.values(),
                key=lambda item: item.updated_at,
                reverse=True,
            ),
            user_feedback=sorted(self._user_feedback, key=lambda item: item.created_at, reverse=True),
            learning_outcomes=sorted(
                self._learning_outcomes.values(),
                key=lambda item: item.updated_at,
                reverse=True,
            ),
            teaching_strategy_effectiveness=sorted(
                self._teaching_strategy_effectiveness.values(),
                key=lambda item: item.last_updated_at,
                reverse=True,
            ),
            teaching_assets=self.list_teaching_assets(),
            session=max(self._sessions.values(), key=lambda item: item.updated_at, default=None),
        )

    @staticmethod
    def _serialize_model(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if is_dataclass(value):
            return StructuredMemoryService._serialize_dataclass(value)
        return value

    def sync_active_card_routing(self) -> None:
        """Keep the routing snapshot consistent with the canonical card map.

        The routing copy is a projection, not a second source of truth. A
        status transition (especially Return -> implemented) must be visible
        immediately, and persisted profiles written before that rule still
        carry a stale copy.
        """
        routing = self._active_training_card_routing
        if routing is None or not routing.selected_card_id:
            return
        card = self._training_cards.get(routing.selected_card_id)
        if card is None:
            return
        selected = routing.selected_card
        if (
            selected is not None
            and selected.status == card.status
            and selected.learning_phase == card.learning_phase
        ):
            return
        self._active_training_card_routing = routing.model_copy(
            update={"selected_card": card, "selected_card_id": card.card_id}
        )

    def export_state(self) -> dict[str, Any]:
        self.sync_active_card_routing()
        return {
            "profile": dict(self._profile),
            "workspace": dict(self._workspace),
            "mastery": [self._serialize_dataclass(item) for item in self._mastery.values()],
            "dependency_mastery": [dict(item) for item in self._dependency_mastery.values()],
            "weaknesses": [self._serialize_dataclass(item) for item in self._weaknesses.values()],
            "reflections": [self._serialize_dataclass(item) for item in self._reflections],
            "preferences": [self._serialize_dataclass(item) for item in self._preferences.values()],
            "decisions": [self._serialize_dataclass(item) for item in self._decisions.values()],
            "progress": [self._serialize_dataclass(item) for item in self._progress.values()],
            "teaching_signals": [self._serialize_dataclass(item) for item in self._teaching_signals.values()],
            "user_feedback": [self._serialize_dataclass(item) for item in self._user_feedback],
            "learning_outcomes": [self._serialize_dataclass(item) for item in self._learning_outcomes.values()],
            "teaching_strategy_effectiveness": [
                self._serialize_dataclass(item) for item in self._teaching_strategy_effectiveness.values()
            ],
            "teaching_assets": [item.model_dump() for item in self._teaching_assets.values()],
            "sessions": [self._serialize_dataclass(item) for item in self._sessions.values()],
            "training_cards": [item.model_dump(mode="json") for item in self._training_cards.values()],
            "card_ledger": [dict(item) for item in self._card_ledger],
            "active_training_card_routing": (
                self._active_training_card_routing.model_dump(mode="json")
                if self._active_training_card_routing
                else None
            ),
            "evidence_items": [item.model_dump(mode="json") for item in self._evidence_items.values()],
            "dependency_skill_maps": [item.model_dump(mode="json") for item in self._dependency_skill_maps.values()],
            "dependency_skill_map_history": [
                item.model_dump(mode="json") for item in self._dependency_skill_map_history
            ],
            "flash_deck": self._flash_deck.model_dump(mode="json") if self._flash_deck else None,
            "recent_flash_attempts": [item.model_dump(mode="json") for item in self._recent_flash_attempts],
            "theory_drill": self._theory_drill.model_dump(mode="json") if self._theory_drill else None,
            "theory_drill_history": [item.model_dump(mode="json") for item in self._theory_drill_history],
            "scenario_lab": self._scenario_lab.model_dump(mode="json") if self._scenario_lab else None,
            "scenario_lab_history": [item.model_dump(mode="json") for item in self._scenario_lab_history],
            "review_queue_actions": [item.model_dump(mode="json") for item in self._review_queue_actions],
            "review_artifact": self._review_artifact.model_dump(mode="json") if self._review_artifact else None,
            "review_artifact_history": [item.model_dump(mode="json") for item in self._review_artifact_history],
            "training_event_ledger": [dict(item) for item in self._training_event_ledger],
        }

    @classmethod
    def from_state(cls, payload: dict[str, Any] | None) -> "StructuredMemoryService":
        service = cls()
        if not payload:
            return service

        service._profile = dict(payload.get("profile") or {})
        service._workspace = dict(payload.get("workspace") or {})
        service._mastery = cls._restore_index(
            payload.get("mastery"),
            MasteryRecord,
            key_field="concept",
        )
        dependency_payload = payload.get("dependency_mastery")
        if isinstance(dependency_payload, dict):
            dependency_items = dependency_payload.values()
        else:
            dependency_items = dependency_payload if isinstance(dependency_payload, list) else []
        service._dependency_mastery = {
            str((item.get("dependency_key") or "")).strip().lower(): dict(item)
            for item in dependency_items
            if isinstance(item, dict) and str(item.get("dependency_key") or "").strip()
        }
        service._weaknesses = cls._restore_index(
            payload.get("weaknesses"),
            WeaknessRecord,
            key_field="concept",
        )
        service._reflections = cls._restore_list(payload.get("reflections"), ReflectionRecord)
        service._preferences = cls._restore_index(
            payload.get("preferences"),
            PreferenceRecord,
            key_field="key",
        )
        service._decisions = cls._restore_index(
            payload.get("decisions"),
            DecisionRecord,
            key_field="topic",
        )
        service._progress = cls._restore_index(
            payload.get("progress"),
            ProgressRecord,
            key_field="focus_area",
            fallback_field="lane",
        )
        service._teaching_signals = cls._restore_index(
            payload.get("teaching_signals"),
            TeachingSignalRecord,
            key_field="key",
        )
        service._user_feedback = cls._restore_list(payload.get("user_feedback"), UserFeedbackRecord)
        service._learning_outcomes = cls._restore_index(
            [],
            LearningOutcomeRecord,
            key_field="concept",
            fallback_field="outcome",
        )
        service._learning_outcomes = {}
        for item in cls._restore_list(payload.get("learning_outcomes"), LearningOutcomeRecord):
            key = "::".join(
                [
                    item.concept.strip().lower() or "concept",
                    item.outcome.strip().lower() or "outcome",
                    item.action_type.strip().lower() or "general",
                ]
            )
            service._learning_outcomes[key] = item
        service._teaching_strategy_effectiveness = cls._restore_index(
            payload.get("teaching_strategy_effectiveness"),
            TeachingStrategyEffectivenessRecord,
            key_field="key",
        )
        service._teaching_assets = cls._restore_index(
            payload.get("teaching_assets"),
            TeachingKnowledgeAsset,
            key_field="id",
        )
        service._sessions = cls._restore_index(
            payload.get("sessions"),
            SessionSummary,
            key_field="session_id",
        )
        service._training_cards = cls._restore_index(
            payload.get("training_cards"),
            TrainingCardCandidateSnapshot,
            key_field="card_id",
        )
        service._card_ledger = [
            dict(item) for item in payload.get("card_ledger", []) if isinstance(item, dict)
        ]
        active_training_card_routing = payload.get("active_training_card_routing")
        if isinstance(active_training_card_routing, dict):
            try:
                service._active_training_card_routing = ActiveCardSelectionResult.model_validate(
                    active_training_card_routing
                )
            except Exception:
                service._active_training_card_routing = None
        service._evidence_items = cls._restore_index(
            payload.get("evidence_items"),
            EvidenceItem,
            key_field="id",
        )
        service._evidence_items = restore_return_artifact(service._workspace, service._evidence_items)
        service._dependency_skill_maps = cls._restore_index(
            payload.get("dependency_skill_maps"),
            DependencySkillMapSnapshot,
            key_field="dependency_key",
        )
        service._dependency_skill_map_history = cls._restore_list(
            payload.get("dependency_skill_map_history"),
            DependencySkillMapHistoryEntry,
        )
        flash_deck_payload = payload.get("flash_deck")
        if isinstance(flash_deck_payload, dict):
            try:
                service._flash_deck = FlashDeckSnapshot.model_validate(flash_deck_payload)
            except Exception:
                service._flash_deck = None
        service._recent_flash_attempts = cls._restore_list(
            payload.get("recent_flash_attempts"),
            FlashcardAttempt,
        )
        theory_drill_payload = payload.get("theory_drill")
        if isinstance(theory_drill_payload, dict):
            try:
                service._theory_drill = TheoryDrillSnapshot.model_validate(theory_drill_payload)
            except Exception:
                service._theory_drill = None
        service._theory_drill_history = cls._restore_list(
            payload.get("theory_drill_history"),
            TheoryDrillHistoryEntry,
        )
        scenario_lab_payload = payload.get("scenario_lab")
        if isinstance(scenario_lab_payload, dict):
            try:
                service._scenario_lab = ScenarioLab.model_validate(scenario_lab_payload)
            except Exception:
                service._scenario_lab = None
        service._scenario_lab_history = cls._restore_list(
            payload.get("scenario_lab_history"),
            ScenarioLabHistoryEntry,
        )
        service._review_queue_actions = cls._restore_list(
            payload.get("review_queue_actions"),
            ReviewQueueAction,
        )
        review_artifact_payload = payload.get("review_artifact")
        if isinstance(review_artifact_payload, dict):
            try:
                service._review_artifact = ReviewArtifactSnapshot.model_validate(review_artifact_payload)
            except Exception:
                service._review_artifact = None
        service._review_artifact_history = cls._restore_list(
            payload.get("review_artifact_history"),
            ReviewArtifactHistoryEntry,
        )
        service._training_event_ledger = [
            dict(item) for item in payload.get("training_event_ledger", []) if isinstance(item, dict)
        ]
        return service

    @staticmethod
    def _serialize_dataclass(value: Any) -> dict[str, Any]:
        data = asdict(value)
        for key, item in list(data.items()):
            if hasattr(item, "isoformat"):
                data[key] = item.isoformat()
        return data

    @staticmethod
    def _parse_datetime_fields(payload: dict[str, Any], model: type) -> dict[str, Any]:
        annotations = getattr(model, "__annotations__", {})
        normalized = dict(payload)
        for key in list(normalized.keys()):
            value = normalized[key]
            if not isinstance(value, str):
                continue
            annotation = annotations.get(key)
            if annotation is None:
                continue
            annotation_text = str(annotation)
            if "datetime" not in annotation_text:
                continue
            try:
                normalized[key] = utc_now().fromisoformat(value)
            except ValueError:
                continue
        return normalized

    @classmethod
    def _restore_list(cls, payload: Any, model: type) -> list[Any]:
        if not isinstance(payload, list):
            return []
        accepted_fields: set[str] | None = None
        if hasattr(model, "model_fields"):
            accepted_fields = set(model.model_fields.keys())
        elif is_dataclass(model):
            accepted_fields = {field.name for field in fields(model)}
        else:
            try:
                accepted_fields = {
                    name
                    for name, parameter in inspect.signature(model).parameters.items()
                    if name != "self"
                    and parameter.kind
                    in (
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        inspect.Parameter.KEYWORD_ONLY,
                    )
                }
            except (TypeError, ValueError):
                accepted_fields = None
        restored: list[Any] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if not item:
                continue
            normalized = cls._parse_datetime_fields(item, model)
            if accepted_fields is not None:
                normalized = {
                    key: value
                    for key, value in normalized.items()
                    if key in accepted_fields
                }
            try:
                restored.append(model(**normalized))
            except Exception:
                continue
        return restored

    @classmethod
    def _restore_index(
        cls,
        payload: Any,
        model: type,
        *,
        key_field: str,
        fallback_field: str | None = None,
    ) -> dict[str, Any]:
        restored: dict[str, Any] = {}
        for item in cls._restore_list(payload, model):
            key = getattr(item, key_field, "") or ""
            if not key and fallback_field:
                key = getattr(item, fallback_field, "") or ""
            if not key:
                continue
            restored[str(key)] = item
        return restored
