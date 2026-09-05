from __future__ import annotations

import inspect
import re
from collections import Counter
from dataclasses import asdict, fields, is_dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from fastapi import HTTPException

from ..core.models import (
    ActiveCardSelectionResult,
    ActiveThreadSnapshot,
    CardStatusTransitionResponse,
    CoachDefaults,
    CoachingAdaptationProfile,
    DependencyMasterySnapshot,
    DependencySkillItemSnapshot,
    DependencySkillMapHistoryEntry,
    DependencySkillMapSnapshot,
    EvidenceAdoptResponse,
    EvidenceItem,
    EvidenceQueueSnapshot,
    FlashcardAttempt,
    FlashDeckSnapshot,
    GlobalMemory,
    GlobalMemoryCapability,
    GlobalMemoryGrowthRecord,
    LearningPlan,
    LibraryAssetCatalogSnapshot,
    MemoryShareCategory,
    MemoryShareGrant,
    MemorySnapshot,
    ResourceRecord,
    ReviewArtifactHistoryEntry,
    ReviewArtifactSnapshot,
    ReviewQueueAction,
    ReviewQueueItem,
    ScenarioLab,
    ScenarioLabHistoryEntry,
    TeachingKnowledgeAsset,
    TheoryDrillHistoryEntry,
    TheoryDrillQuestion,
    TheoryDrillSnapshot,
    TrainingCardCandidateSnapshot,
    UserProfile,
    WorkspaceUnderstandingSnapshot,
)
from ..db.repository import TrainerRepository
from ..pedagogy.context_pressure import derive_context_pressure
from ..pedagogy.evidence_controls import (
    analyze_learning_evidence,
    pedagogy_evidence_confidence,
    profile_kwargs_from_controls,
    refresh_controls_after_strategy,
    resolve_pedagogy_controls,
    review_after_days_for_frequency,
)
from ..pedagogy.material_recommendation import (
    MaterialRoutingDecision,
    resolve_material_routing,
    teaching_asset_scope_bias,
)
from ..resources.asset_library import AssetLibraryService
from ..training.handoff import (
    HandoffStatus,
    ProjectHandoff,
    TrainingHandoffGenerator,
    TrainingPhase,
)
from ..training.reliability import (
    WORKSPACE_RELIABILITY_KEY,
    WORKSPACE_SNAPSHOT_REVISION_KEY,
    as_workspace_record,
    begin_record,
    expire_if_needed,
    mark_executing,
    mark_failed,
    mark_succeeded,
    recover_record,
    request_cancel,
    should_coalesce,
    should_replay,
)
from .models import (
    DecisionRecord,
    LearningOutcomeRecord,
    MasteryRecord,
    PreferenceRecord,
    ProgressRecord,
    ReflectionRecord,
    SearchHit,
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
from .review_scheduler import ReviewScheduler
from .semantic import HashingEmbedder, SemanticMemory
from .transfer_skills import (
    build_transfer_skill_state_record,
    describe_transfer_skill_state,
    normalize_transfer_skill_state_record,
    resolve_skill_scene_key,
    should_promote_transferable_skill,
    unique_transfer_scenes,
)
from .workspace_recovery import (
    ADAPTATION_GUIDE_KEY,
    AFFECT_STATE_KEY,
    COACH_FOCUS_KEY,
    COACH_TURN_KEY,
    COACHING_ADAPTATION_KEY,
    COACHING_FOCUS_KEY,
    CURRENT_TASK_KEY,
    EVALUATION_KEY,
    LEARNER_STATE_KEY,
    NEXT_STEP_HINT_KEY,
    PLAN_RUNTIME_KEY,
    PRINCIPLE_NOTES_KEY,
    PROJECT_SOURCES_KEY,
    PROVIDER_CAPABILITY_KEY,
    STREAMING_CHECKPOINT_KEY,
    TEACHING_DECISION_KEY,
    TONE_DECISION_KEY,
    TRAINING_CHROME_KEY,
    apply_affect_tone_scope,
    apply_coaching_focus_scope,
    apply_current_task_scope,
    apply_evaluation_chrome_scope,
    apply_teaching_artifact_scope,
    apply_training_chrome_scope,
    attest_waiting_verify_on_adopt,
    bind_explicit_generated_plan_runtime,
    bound_plan_leftover_training_live_identity_updates,
    build_plan_runtime_advance_after_adopt,
    build_plan_runtime_advance_after_verify,
    build_plan_runtime_recovery,
    build_plan_runtime_resume,
    build_streaming_checkpoint,
    build_waiting_composer_evidence,
    build_waiting_verify_evidence,
    formal_card_is_live_runtime_identity,
    formal_plan_is_live_runtime_identity,
    is_current_for_workspace,
    leftover_bound_plan_competing_identity_labels,
    leftover_formal_plan_is_live_for_fill,
    leftover_formal_training_labels,
    live_coach_focus_area,
    live_coach_stage_label,
    live_evidence_binding,
    live_memory_snapshot_overlay,
    live_plan_snapshot_persist_chrome,
    live_training_persist_chrome,
    normalize_latest_adaptation_guide,
    normalize_latest_affect_state,
    normalize_latest_coach_focus,
    normalize_latest_coach_turn,
    normalize_latest_coaching_adaptation,
    normalize_latest_coaching_focus,
    normalize_latest_current_task,
    normalize_latest_evaluation,
    normalize_latest_learner_state,
    normalize_latest_next_step_hint,
    normalize_latest_principle_notes,
    normalize_latest_project_sources,
    normalize_latest_teaching_decision,
    normalize_latest_tone_decision,
    normalize_plan_runtime_recovery,
    normalize_provider_capability_recovery,
    normalize_streaming_checkpoint,
    recover_streaming_checkpoint_after_restart,
    scope_evidence_items_to_workspace,
    scope_evidence_queue_to_runtime_step,
    select_latest_adaptation_guide,
    select_latest_affect_state,
    select_latest_coach_focus,
    select_latest_coach_turn,
    select_latest_coaching_adaptation,
    select_latest_coaching_focus,
    select_latest_current_task,
    select_latest_evaluation,
    select_latest_learner_state,
    select_latest_next_step_hint,
    select_latest_principle_notes,
    select_latest_project_sources,
    select_latest_teaching_decision,
    select_latest_tone_decision,
    select_plan_runtime_for_pressure,
    select_plan_runtime_for_scope,
    select_provider_capability_for_scope,
    select_resources_for_scope,
    select_streaming_checkpoint_for_scope,
    select_training_chrome_for_scope,
    select_training_record_for_scope,
    stamp_workspace_scope,
)


def _contains_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


_CJK_TEXT_CORRECT_THRESHOLD = 0.60


def _contains_cjk_answer_text(value: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in value)


def _cjk_normalized_answer(value: str) -> str:
    """Drop punctuation like the latin tokenizer, but keep CJK characters."""

    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", value)


def _dice_coefficient(left: str, right: str, *, size: int) -> float:
    if len(left) < size or len(right) < size:
        return 1.0 if left and left == right else 0.0
    left_counts = Counter(left[index : index + size] for index in range(len(left) - size + 1))
    right_counts = Counter(right[index : index + size] for index in range(len(right) - size + 1))
    overlap = sum((left_counts & right_counts).values())
    total = sum(left_counts.values()) + sum(right_counts.values())
    return (2.0 * overlap) / total if total else 0.0


def _cjk_answer_similarity(expected: str, answer: str) -> float:
    """Dice similarity for CJK text answers.

    Primary coefficient is the Dice score over character bigrams of the
    whitespace-collapsed strings (punctuation excluded, CJK kept). Short CJK
    paraphrases reorder words, which collapses bigram overlap, so the
    character-level Dice acts as a floor before the answer is failed.
    """

    normalized_expected = _cjk_normalized_answer(expected)
    normalized_answer = _cjk_normalized_answer(answer)
    coefficient = _dice_coefficient(normalized_expected, normalized_answer, size=2)
    if coefficient < _CJK_TEXT_CORRECT_THRESHOLD:
        coefficient = max(
            coefficient,
            _dice_coefficient(normalized_expected, normalized_answer, size=1),
        )
    return coefficient


def _localized_memory_text(en: str, zh: str, context: str = "") -> str:
    normalized_context = context.strip().lower()
    if normalized_context.startswith("zh"):
        return zh
    return zh if _contains_chinese(context) else en


def _prefers_chinese_text(context: str = "") -> bool:
    normalized_context = context.strip().lower()
    return normalized_context.startswith("zh") or _contains_chinese(context)


_GENERIC_FOCUS_DISPLAY_LABELS = {
    "implementation": ("implementation slice", "实现切片"),
}


def _display_focus_label(focus: str, context: str = "") -> str:
    cleaned = focus.strip()
    if not cleaned:
        return ""
    localized = _GENERIC_FOCUS_DISPLAY_LABELS.get(cleaned.lower())
    if localized is None:
        return cleaned
    return _localized_memory_text(localized[0], localized[1], context or cleaned)


def _focus_looks_like_request_sentence(value: str) -> bool:
    cleaned = str(value or "").strip()
    if not cleaned:
        return False
    lowered = cleaned.casefold()
    if lowered.startswith(
        (
            "teach me ",
            "help me ",
            "show me ",
            "tell me ",
            "walk me through ",
            "guide me ",
            "how to ",
            "please ",
        )
    ):
        return True
    return len(cleaned.split()) >= 7 and cleaned.endswith((".", "?", "。", "？"))


def _guided_lane_focus_label(scenario: str, context: str = "") -> str:
    normalized = str(scenario or "").strip().lower()
    if normalized == "remote_workspace":
        return _localized_memory_text(
            "VS Code remote workspace",
            "VS Code 远程工作区",
            context,
        )
    if normalized == "debug_loop":
        return _localized_memory_text(
            "VS Code debug loop",
            "VS Code 调试闭环",
            context,
        )
    if normalized == "function_guidance":
        return _localized_memory_text(
            "function contract reading",
            "\u51fd\u6570\u5951\u7ea6\u5224\u65ad",
            context,
        )
    return ""


def _workspace_language(workspace: dict[str, Any]) -> str:
    for key in ("response_language", "preferred_language"):
        language = str(workspace.get(key) or "").strip()
        if language:
            return language
    return ""


def _memory_language_context(workspace: dict[str, Any], *fallbacks: str) -> str:
    language = _workspace_language(workspace)
    if language:
        return language
    for value in fallbacks:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _strip_visible_next_step_prefix(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"(?i)^(?:next(?: step)?\s*:\s*)+", "", cleaned).strip()
    cleaned = re.sub(r"^(?:\u4e0b\u4e00\u6b65[:\uff1a]\s*)+", "", cleaned).strip()
    return cleaned


def _normalize_text_items(values: Any, *, limit: int = 4) -> list[str]:
    if not isinstance(values, list):
        return []
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in items:
            continue
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _normalize_source_freshness(value: object) -> Literal["fresh", "stale", "unknown"]:
    normalized = str(value or "").strip().lower()
    if normalized == "fresh":
        return "fresh"
    if normalized == "stale":
        return "stale"
    return "unknown"


_SYNTHETIC_BOOTSTRAP_CONCEPTS = {
    "new-workspace",
    "plan-discipline",
    "resource-grounding",
}


class SemanticMemoryService(SemanticMemory):
    def __init__(
        self,
        storage_path: Path | None = None,
        *,
        collection_name: str = "trainer_memory",
        embedder: HashingEmbedder | None = None,
        use_qdrant: bool = False,
    ) -> None:
        resolved_path = storage_path or Path(".trainer-memory")
        self.storage_path = resolved_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.collection = collection_name
        self.embedder = embedder or HashingEmbedder()
        self._documents = {}
        self._client = None
        if use_qdrant:
            super().__init__(
                storage_path=resolved_path,
                collection_name=collection_name,
                embedder=self.embedder,
            )

    def search(
        self,
        text: str,
        limit: int = 5,
        metadata_filter: dict[str, Any] | None = None,
        *,
        top_k: int | None = None,
    ) -> list[SearchHit]:
        return self.search_hits(text, top_k=top_k if top_k is not None else limit, metadata_filter=metadata_filter)


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
        updated = MasteryRecord(
            concept=concept,
            score=min(max(current.score + delta, 0.0), 1.0),
            confidence=confidence,
            updated_at=utc_now(),
            next_review_at=utc_now() + timedelta(days=review_after_days),
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

    def remember_preference(self, key: str, value: str, *, source: str = "derived") -> PreferenceRecord:
        record = PreferenceRecord(key=key, value=value, source=source, updated_at=utc_now())
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
    ) -> UserFeedbackRecord:
        normalized_kind = kind.strip().lower()
        record = UserFeedbackRecord(
            kind=normalized_kind,
            message=message.strip(),
            focus_area=focus_area.strip(),
            scenario=scenario.strip(),
            training_card_id=training_card_id.strip(),
            plan_id=plan_id.strip(),
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

    def export_state(self) -> dict[str, Any]:
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


class MemoryService:
    def __init__(self, repository: TrainerRepository, structured: StructuredMemoryService | None = None) -> None:
        self.repository = repository
        self._asset_library = AssetLibraryService(repository)
        self._structured_by_workspace: dict[str, StructuredMemoryService] = {}
        self._default_structured = structured
        self._review_scheduler = ReviewScheduler()
        self._resource_dedupe_hook: Callable[[list[ResourceRecord]], list[ResourceRecord]] | None = None
        self._card_ledger: list[dict[str, Any]] = []

    def set_resource_dedupe_hook(
        self,
        hook: Callable[[list[ResourceRecord]], list[ResourceRecord]],
    ) -> None:
        self._resource_dedupe_hook = hook

    def global_memory(self) -> GlobalMemory:
        return self.repository.ensure_default_global_memory()

    def update_global_memory(
        self,
        *,
        preferences: dict[str, str] | None = None,
        long_term_goals: list[str] | None = None,
    ) -> GlobalMemory:
        current = self.global_memory()
        next_preferences = (
            {
                str(key).strip(): str(value).strip()
                for key, value in preferences.items()
                if str(key).strip()
            }
            if preferences is not None
            else dict(current.preferences)
        )
        next_goals = list(long_term_goals) if long_term_goals is not None else list(current.long_term_goals)
        updated = GlobalMemory(
            ownerId=current.owner_id,
            preferences=next_preferences,
            longTermGoals=next_goals,
            capabilityProfile=current.capability_profile,
            growthHistory=current.growth_history,
            createdAt=current.created_at,
            updatedAt=utc_now().isoformat(),
        )
        self.repository.save_global_memory(updated)
        return updated

    _GLOBAL_PROMOTABLE_OUTCOMES = {
        "code_landed",
        "tests_passed",
        "concept_answered_correctly",
    }
    _GLOBAL_FAILURE_OUTCOMES = {
        "repeated_error",
        "task_abandoned",
        "blocked",
    }

    @staticmethod
    def _verified_concepts_from_structured(structured: StructuredMemoryService) -> set[str]:
        concepts: set[str] = set()
        for item in structured._mastery.values():
            if item.confidence < 0.72 or item.score <= 0:
                continue
            concept = (item.concept or "").strip()
            if concept:
                concepts.add(concept.casefold())
        return concepts

    def _iter_structured_workspaces(self) -> list[tuple[str, StructuredMemoryService]]:
        loaded: dict[str, StructuredMemoryService] = {}
        for workspace_id, structured in self._structured_by_workspace.items():
            loaded[workspace_id] = structured
        for workspace_id, payload in self.repository.list_structured_memory():
            if workspace_id in loaded:
                continue
            loaded[workspace_id] = StructuredMemoryService.from_state(payload)
        return list(loaded.items())

    def exclude_workspaces_from_transfer_promotion(self, workspace_ids: list[str]) -> list[str]:
        excluded: list[str] = []
        for workspace_id in workspace_ids:
            cleaned = workspace_id.strip()
            if not cleaned:
                continue
            self.repository.exclude_workspace_from_transfer_promotion(cleaned)
            excluded.append(cleaned)
        self._refresh_transfer_states_after_exclusion_change(mode="exclude", changed_ids=excluded)
        return excluded

    def include_workspaces_in_transfer_promotion(self, workspace_ids: list[str]) -> list[str]:
        included: list[str] = []
        for workspace_id in workspace_ids:
            cleaned = workspace_id.strip()
            if not cleaned:
                continue
            self.repository.include_workspace_in_transfer_promotion(cleaned)
            included.append(cleaned)
        self._refresh_transfer_states_after_exclusion_change(mode="include", changed_ids=included)
        return included

    def _transfer_promotion_excluded_ids(self) -> set[str]:
        return {item.casefold() for item in self.repository.list_transfer_promotion_exclusions()}

    def _transfer_promotion_exclusion_history_ids(self) -> set[str]:
        return {item.casefold() for item in self.repository.list_transfer_promotion_exclusion_history()}

    def _workspace_excluded_from_transfer_promotion(
        self,
        workspace_id: str,
        excluded: set[str] | None = None,
    ) -> bool:
        cleaned = workspace_id.strip()
        if not cleaned:
            return False
        blocked = excluded if excluded is not None else self._transfer_promotion_excluded_ids()
        return cleaned.casefold() in blocked

    def _local_verified_scenes_for_concept(self, workspace_id: str, concept: str) -> list[dict[str, str]]:
        cleaned_concept = concept.strip()
        cleaned_workspace = workspace_id.strip()
        if not cleaned_concept or not cleaned_workspace:
            return []
        structured = self._structured_for(cleaned_workspace)
        scenes: list[dict[str, str]] = []
        raw_scenes = structured._workspace.get("verified_skill_scenes") or []
        if isinstance(raw_scenes, list):
            for item in raw_scenes:
                if not isinstance(item, dict):
                    continue
                if str(item.get("concept") or "").strip().casefold() != cleaned_concept.casefold():
                    continue
                scene_workspace = str(item.get("workspace_id") or cleaned_workspace).strip() or cleaned_workspace
                if scene_workspace.casefold() != cleaned_workspace.casefold():
                    continue
                scenes.append(
                    {
                        "workspace_id": scene_workspace,
                        "scene_key": str(item.get("scene_key") or "default").strip() or "default",
                    }
                )
        if scenes:
            return unique_transfer_scenes(scenes)
        return []

    def _transfer_concept_for_workspace(self, workspace_id: str) -> str:
        structured = self._structured_for(workspace_id)
        existing = normalize_transfer_skill_state_record(structured._workspace.get("latest_transfer_state"))
        if existing and str(existing.get("concept") or "").strip():
            return str(existing.get("concept") or "").strip()
        raw_scenes = structured._workspace.get("verified_skill_scenes") or []
        if isinstance(raw_scenes, list):
            for item in raw_scenes:
                if not isinstance(item, dict):
                    continue
                concept = str(item.get("concept") or "").strip()
                if concept:
                    return concept
        concepts = sorted(self._verified_concepts_from_structured(structured))
        return concepts[0] if concepts else ""

    def _refresh_workspace_transfer_state(
        self,
        workspace_id: str,
        *,
        local_only: bool,
    ) -> None:
        concept = self._transfer_concept_for_workspace(workspace_id)
        if not concept:
            return
        scenes = (
            self._local_verified_scenes_for_concept(workspace_id, concept)
            if local_only
            else self._verified_scenes_for_concept(concept)
        )
        language = str(self._structured_for(workspace_id)._workspace.get("response_language") or "")
        record = build_transfer_skill_state_record(concept=concept, scenes=scenes, language=language)
        self._structured_for(workspace_id).update_workspace(latest_transfer_state=record)
        self._persist_structured(workspace_id)

    def _refresh_transfer_states_after_exclusion_change(
        self,
        *,
        mode: str,
        changed_ids: list[str],
    ) -> None:
        changed = {item.strip() for item in changed_ids if item.strip()}
        if mode == "include":
            for workspace_id in changed:
                self._refresh_workspace_transfer_state(workspace_id, local_only=True)
            return
        seen: set[str] = set()
        for workspace_id, _structured in self._iter_structured_workspaces():
            cleaned = workspace_id.strip()
            if not cleaned or cleaned.casefold() in seen:
                continue
            seen.add(cleaned.casefold())
            self._refresh_workspace_transfer_state(
                cleaned,
                local_only=cleaned.casefold() in {item.casefold() for item in changed}
                or self._workspace_excluded_from_transfer_promotion(cleaned),
            )

    def _verified_concepts_outside_workspace(self, workspace_id: str) -> set[str]:
        found: set[str] = set()
        excluded = self._transfer_promotion_excluded_ids()
        for other_id, structured in self._iter_structured_workspaces():
            if other_id == workspace_id:
                continue
            if self._workspace_excluded_from_transfer_promotion(other_id, excluded):
                continue
            found.update(self._verified_concepts_from_structured(structured))
        return found

    def _record_verified_skill_scene(
        self,
        *,
        workspace_id: str,
        concept: str,
        scene_key: str,
    ) -> None:
        cleaned_concept = concept.strip()
        cleaned_workspace = workspace_id.strip()
        cleaned_scene = (scene_key or "").strip() or "default"
        if not cleaned_concept or not cleaned_workspace:
            return
        structured = self._structured_for(cleaned_workspace)
        scenes = list(structured._workspace.get("verified_skill_scenes") or [])
        already = any(
            str(item.get("concept") or "").strip().casefold() == cleaned_concept.casefold()
            and str(item.get("workspace_id") or "").strip() == cleaned_workspace
            and str(item.get("scene_key") or "default").strip() == cleaned_scene
            for item in scenes
            if isinstance(item, dict)
        )
        if already:
            return
        scenes.append(
            {
                "concept": cleaned_concept,
                "workspace_id": cleaned_workspace,
                "scene_key": cleaned_scene,
                "verified_at": utc_now().isoformat(),
            }
        )
        structured.update_workspace(verified_skill_scenes=scenes)

    def _verified_scenes_for_concept(self, concept: str) -> list[dict[str, str]]:
        cleaned = concept.strip()
        if not cleaned:
            return []
        scenes: list[dict[str, str]] = []
        excluded = self._transfer_promotion_excluded_ids()
        for workspace_id, structured in self._iter_structured_workspaces():
            if self._workspace_excluded_from_transfer_promotion(workspace_id, excluded):
                continue
            raw_scenes = structured._workspace.get("verified_skill_scenes") or []
            if isinstance(raw_scenes, list):
                for item in raw_scenes:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("concept") or "").strip().casefold() != cleaned.casefold():
                        continue
                    scene_workspace = str(item.get("workspace_id") or workspace_id).strip()
                    if self._workspace_excluded_from_transfer_promotion(scene_workspace, excluded):
                        continue
                    scenes.append(
                        {
                            "workspace_id": scene_workspace,
                            "scene_key": str(item.get("scene_key") or "default").strip() or "default",
                        }
                    )
        return unique_transfer_scenes(scenes)

    def _should_promote_verified_outcome_to_global(
        self,
        *,
        concepts: list[str],
        workspace_id: str,
        transfer_source_workspace_id: str | None = None,
        transfer_target_workspace_id: str | None = None,
        transfer_source_context: str | None = None,
        transfer_target_context: str | None = None,
        transfer_evidence_summary: str | None = None,
        scenario: str | None = None,
    ) -> bool:
        for concept in concepts:
            if not concept.strip():
                continue
            scene_key = resolve_skill_scene_key(
                transfer_source_workspace_id=transfer_source_workspace_id or "",
                transfer_target_workspace_id=transfer_target_workspace_id or "",
                transfer_source_context=transfer_source_context or "",
                transfer_target_context=transfer_target_context or "",
                transfer_evidence_summary=transfer_evidence_summary or "",
                scenario=scenario or "",
            )
            if should_promote_transferable_skill(
                concept=concept,
                workspace_id=workspace_id,
                current_scene_key=scene_key,
                existing_scenes=self._verified_scenes_for_concept(concept),
                outcome_success=True,
                transfer_source_workspace_id=transfer_source_workspace_id or "",
                transfer_target_workspace_id=transfer_target_workspace_id or "",
                transfer_source_context=transfer_source_context or "",
                transfer_target_context=transfer_target_context or "",
                transfer_evidence_summary=transfer_evidence_summary or "",
                scenario=scenario or "",
            ):
                return True
        return False

    def _persist_transfer_skill_state(
        self,
        *,
        workspace_id: str,
        concept: str,
        language: str | None = None,
        schedule_review: bool = False,
    ) -> dict[str, Any]:
        scenes = self._verified_scenes_for_concept(concept)
        record = build_transfer_skill_state_record(concept=concept, scenes=scenes, language=language)
        review: dict[str, Any] | None = None
        if schedule_review and record["state"] == "transferable":
            review = {
                "concept": concept,
                "reason": record["next"],
                "source": "plan",
                "severity": "medium",
                "linked_context": "transfer",
                "focus_area": concept,
                "task_hint": record["why"],
            }
        workspace_ids = [item for item in record["workspace_ids"] if item]
        if workspace_id not in workspace_ids:
            workspace_ids.append(workspace_id)
        excluded = self._transfer_promotion_excluded_ids()
        historically_excluded = self._transfer_promotion_exclusion_history_ids()
        for target_id in workspace_ids:
            if target_id != workspace_id and (
                self._workspace_excluded_from_transfer_promotion(target_id, excluded)
                or target_id.casefold() in historically_excluded
            ):
                continue
            structured = self._structured_for(target_id)
            payload: dict[str, Any] = {"latest_transfer_state": record}
            if review is not None:
                payload["latest_transfer_review"] = review
            if target_id == workspace_id:
                payload["latest_learning_followup"] = record["next"]
            structured.update_workspace(**payload)
            if target_id != workspace_id:
                self._persist_structured(target_id)
        return record

    def _record_global_verified_outcome(
        self,
        concepts: list[str],
        outcome: str,
        *,
        workspace_id: str = "",
        scene_count: int = 0,
    ) -> None:
        if (outcome or "").strip() in self._GLOBAL_FAILURE_OUTCOMES:
            return
        normalized_concepts = list(dict.fromkeys(item.strip() for item in concepts if item and item.strip()))
        if not normalized_concepts:
            return
        current = self.global_memory()
        recorded_at = utc_now().isoformat()
        capability_profile = dict(current.capability_profile)
        for concept in normalized_concepts:
            key = concept.casefold()
            existing = capability_profile.get(key)
            workspace_ids = list(existing.workspace_ids) if existing else []
            if workspace_id and workspace_id not in workspace_ids:
                workspace_ids.append(workspace_id)
            capability_profile[key] = GlobalMemoryCapability(
                concept=concept,
                verifiedCount=(existing.verified_count if existing else 0) + 1,
                lastOutcome=outcome,
                lastVerifiedAt=recorded_at,
                workspaceIds=workspace_ids,
                sceneCount=max(
                    existing.scene_count if existing else 0,
                    scene_count,
                    len(workspace_ids),
                ),
            )
        growth_history = [
            *current.growth_history,
            GlobalMemoryGrowthRecord(
                outcome=outcome,
                concepts=normalized_concepts,
                verifiedAt=recorded_at,
            ),
        ][-100:]
        self.repository.save_global_memory(
            GlobalMemory(
                ownerId=current.owner_id,
                preferences=current.preferences,
                longTermGoals=current.long_term_goals,
                capabilityProfile=capability_profile,
                growthHistory=growth_history,
                createdAt=current.created_at,
                updatedAt=recorded_at,
            )
        )

    def _structured_for(self, workspace_id: str) -> StructuredMemoryService:
        existing = self._structured_by_workspace.get(workspace_id)
        if existing is not None:
            return existing

        if self._default_structured is not None and not self._structured_by_workspace:
            structured = self._default_structured
            self._default_structured = None
        else:
            payload = self.repository.load_structured_memory(workspace_id)
            structured = StructuredMemoryService.from_state(payload)
        self._structured_by_workspace[workspace_id] = structured
        return structured

    def _persist_structured(self, workspace_id: str) -> None:
        structured = self._structured_for(workspace_id)
        self.repository.save_structured_memory(workspace_id, structured.export_state())

    def list_memory_share_grants(self, target_workspace_id: str) -> list[MemoryShareGrant]:
        return self.repository.list_memory_share_grants(target_workspace_id)

    def save_memory_share_grant(
        self,
        *,
        source_workspace_id: str,
        target_workspace_id: str,
        categories: list[MemoryShareCategory],
    ) -> MemoryShareGrant:
        grant = MemoryShareGrant(
            source_workspace_id=source_workspace_id,
            target_workspace_id=target_workspace_id,
            categories=categories,
        )
        existing = self.repository.get_memory_share_grant(
            grant.source_workspace_id,
            grant.target_workspace_id,
        )
        if existing is not None:
            grant = grant.model_copy(update={"created_at": existing.created_at})
        self.repository.save_memory_share_grant(grant)
        return grant

    def revoke_memory_share_grant(self, *, source_workspace_id: str, target_workspace_id: str) -> bool:
        return self.repository.delete_memory_share_grant(
            source_workspace_id.strip(),
            target_workspace_id.strip(),
        )

    def _save_teaching_asset(self, workspace_id: str, asset: TeachingKnowledgeAsset) -> TeachingKnowledgeAsset:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved_workspace_id)
        owner_workspace_id = (
            "__global__"
            if asset.scope == "general"
            else resolved_workspace_id
            if asset.scope in {"project", "personal"}
            else (asset.workspace_id or resolved_workspace_id)
        )
        saved = structured.upsert_teaching_asset(asset.model_copy(update={"workspace_id": owner_workspace_id}))
        self.repository.save_teaching_asset(resolved_workspace_id, saved)
        self._persist_structured(resolved_workspace_id)
        return saved

    def _load_teaching_asset_for_update(
        self,
        workspace_id: str,
        asset_id: str,
    ) -> tuple[str, TeachingKnowledgeAsset] | None:
        cleaned_id = asset_id.strip()
        if not cleaned_id:
            return None
        candidates = {
            asset.id: asset
            for asset in self.list_teaching_assets(
                workspace_id,
                limit=32,
            )
        }
        asset = candidates.get(cleaned_id) or self.repository.load_teaching_asset(cleaned_id)
        if asset is None:
            return None
        owner_workspace_id = asset.workspace_id or workspace_id
        if asset.scope in {"project", "personal"} and owner_workspace_id != workspace_id:
            return None
        return owner_workspace_id, asset

    def _list_authorized_personal_memory_sources(
        self,
        current_workspace_id: str,
    ) -> list[tuple[str, StructuredMemoryService, set[str]]]:
        sources = [(current_workspace_id, self._structured_for(current_workspace_id), set())]
        for grant in self.repository.list_memory_share_grants(current_workspace_id):
            source_workspace_id = grant.source_workspace_id
            if source_workspace_id == current_workspace_id:
                continue
            existing = self._structured_by_workspace.get(source_workspace_id)
            if existing is not None:
                sources.append((source_workspace_id, existing, set(grant.categories)))
                continue
            payload = self.repository.load_structured_memory(source_workspace_id)
            if payload is None:
                continue
            sources.append(
                (
                    source_workspace_id,
                    StructuredMemoryService.from_state(payload),
                    set(grant.categories),
                )
            )
        return sources

    def _build_personal_lane_snapshot(
        self,
        workspace_id: str,
        lane_snapshot: LaneMemorySnapshot,
    ) -> LaneMemorySnapshot:
        sources = self._list_authorized_personal_memory_sources(workspace_id)
        aggregate = StructuredMemoryService()

        for source_workspace_id, structured, shared_categories in sources:
            snapshot = structured.snapshot()
            is_current_workspace = source_workspace_id == workspace_id

            if is_current_workspace:
                aggregate.update_profile(**snapshot.profile)
            elif "preferences" in shared_categories:
                profile_goal = str(snapshot.profile.get("long_term_goal") or "").strip()
                profile_teaching_style = str(snapshot.profile.get("teaching_style") or "").strip()
                profile_answer_policy = str(snapshot.profile.get("answer_policy") or "").strip()
                if profile_goal:
                    aggregate.remember_preference(
                        "long_term_goal",
                        profile_goal,
                        source=f"profile:{source_workspace_id}",
                    )
                if profile_teaching_style:
                    aggregate.remember_preference(
                        "teaching_style",
                        profile_teaching_style,
                        source=f"profile:{source_workspace_id}",
                    )
                if profile_answer_policy:
                    aggregate.remember_preference(
                        "answer_policy",
                        profile_answer_policy,
                        source=f"profile:{source_workspace_id}",
                    )

            if is_current_workspace or "preferences" in shared_categories:
                for preference in snapshot.preferences:
                    existing = aggregate._preferences.get(preference.key)
                    if existing is None or preference.updated_at >= existing.updated_at:
                        aggregate._preferences[preference.key] = preference

            if is_current_workspace:
                for decision in snapshot.decisions:
                    existing = aggregate._decisions.get(decision.topic)
                    if existing is None or decision.updated_at >= existing.updated_at:
                        aggregate._decisions[decision.topic] = decision

                for progress in snapshot.progress:
                    key = progress.focus_area.strip() or progress.lane.strip() or "active-thread"
                    existing = aggregate._progress.get(key)
                    if existing is None or progress.updated_at >= existing.updated_at:
                        aggregate._progress[key] = progress

                for teaching_signal in snapshot.teaching_signals:
                    existing = aggregate._teaching_signals.get(teaching_signal.key)
                    if existing is None or teaching_signal.updated_at >= existing.updated_at:
                        aggregate._teaching_signals[teaching_signal.key] = teaching_signal

                for strategy_record in snapshot.teaching_strategy_effectiveness:
                    existing = aggregate._teaching_strategy_effectiveness.get(strategy_record.key)
                    if existing is None or strategy_record.last_updated_at >= existing.last_updated_at:
                        aggregate._teaching_strategy_effectiveness[strategy_record.key] = strategy_record

            if is_current_workspace or "mastery" in shared_categories:
                for mastery in reversed(snapshot.mastery):
                    concept = mastery.concept.strip()
                    if not concept:
                        continue
                    existing = aggregate._mastery.get(concept)
                    if existing is None or mastery.updated_at >= existing.updated_at:
                        aggregate._mastery[concept] = mastery

            if is_current_workspace:
                for weakness in reversed(snapshot.weaknesses):
                    concept = weakness.concept.strip()
                    if not concept:
                        continue
                    existing = aggregate._weaknesses.get(concept)
                    if existing is None:
                        aggregate._weaknesses[concept] = weakness
                        continue
                    if weakness.updated_at >= existing.updated_at:
                        merged = WeaknessRecord(
                            concept=concept,
                            reason=weakness.reason,
                            severity=max(existing.severity, weakness.severity),
                            recurrence_count=max(existing.recurrence_count, weakness.recurrence_count),
                            latest_example=weakness.latest_example or existing.latest_example,
                            last_seen_context=weakness.last_seen_context or existing.last_seen_context,
                            updated_at=weakness.updated_at,
                            next_review_at=weakness.next_review_at or existing.next_review_at,
                        )
                        aggregate._weaknesses[concept] = merged
                    else:
                        merged = WeaknessRecord(
                            concept=concept,
                            reason=existing.reason,
                            severity=max(existing.severity, weakness.severity),
                            recurrence_count=max(existing.recurrence_count, weakness.recurrence_count),
                            latest_example=existing.latest_example or weakness.latest_example,
                            last_seen_context=existing.last_seen_context or weakness.last_seen_context,
                            updated_at=existing.updated_at,
                            next_review_at=existing.next_review_at or weakness.next_review_at,
                        )
                        aggregate._weaknesses[concept] = merged

                for reflection in snapshot.reflections:
                    aggregate._reflections.append(reflection)

                for session_id, session in structured._sessions.items():
                    existing = aggregate._sessions.get(session_id)
                    if existing is None or session.updated_at >= existing.updated_at:
                        aggregate._sessions[session_id] = session

        aggregate._reflections = sorted(
            aggregate._reflections,
            key=lambda item: item.created_at,
        )[-18:]

        # Keep the current workspace thread and runtime defaults as the live foreground context,
        # while the rest of the personal memory stays in the background aggregate.
        aggregate._workspace = dict(lane_snapshot.workspace)
        personal_snapshot = aggregate.snapshot()
        personal_snapshot.session = lane_snapshot.session
        return personal_snapshot

    @staticmethod
    def _coach_defaults_from_workspace(workspace: dict[str, Any]) -> dict[str, Any]:
        defaults = workspace.get("coach_defaults")
        return defaults if isinstance(defaults, dict) else {}

    @staticmethod
    def _workspace_memory_toggles(workspace: dict[str, Any]) -> dict[str, bool]:
        toggles = workspace.get("workspace_memory_toggles")
        if not isinstance(toggles, dict):
            return {"decisions": True, "patterns": True, "resources": True}
        return {
            "decisions": bool(toggles.get("decisions", True)),
            "patterns": bool(toggles.get("patterns", True)),
            "resources": bool(toggles.get("resources", True)),
        }

    @staticmethod
    def _memory_scope(workspace: dict[str, Any]) -> str:
        scope = str(workspace.get("memory_scope") or "").strip()
        return scope or "project"

    def _resolve_workspace_for_write(self, workspace_id: str | None) -> str:
        if workspace_id:
            return workspace_id
        if self._structured_by_workspace:
            return next(reversed(self._structured_by_workspace))
        if self._default_structured is not None:
            workspace_id = "workspace-default"
            self._structured_by_workspace[workspace_id] = self._default_structured
            self._default_structured = None
            return workspace_id
        return "workspace-default"

    def latest_session_id_for_workspace(self, workspace_id: str) -> str | None:
        structured = self._structured_for(workspace_id)
        snapshot = structured.snapshot()
        candidate_ids: list[str] = []
        if snapshot.session and snapshot.session.session_id:
            candidate_ids.append(snapshot.session.session_id)
        candidate_ids.extend(
            [
                session_id
                for session_id, session in sorted(
                    structured._sessions.items(),
                    key=lambda item: item[1].updated_at,
                    reverse=True,
                )
                if session_id not in candidate_ids
            ]
        )
        restored = self.repository.load_latest_session_by_ids(workspace_id, candidate_ids)
        if restored and isinstance(restored.get("session_id"), str):
            return str(restored["session_id"])
        latest = self.repository.load_latest_session_for_workspace(workspace_id)
        if latest and isinstance(latest.get("session_id"), str):
            return str(latest["session_id"])
        return None

    @staticmethod
    def _normalize_dependency_key(value: str) -> str:
        lowered = value.strip().lower()
        aliases = {
            "react.js": "react",
            "reactjs": "react",
            "fast api": "fastapi",
            "python decorators": "python-decorators",
            "css flexbox": "css-flexbox",
            "depends": "fastapi",
            "fastapi depends": "fastapi",
        }
        if lowered in aliases:
            return aliases[lowered]
        normalized = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
        return normalized

    def _dependency_mastery_snapshots(
        self,
        structured: StructuredMemoryService,
    ) -> list[DependencyMasterySnapshot]:
        snapshots: list[DependencyMasterySnapshot] = []
        for key, payload in structured._dependency_mastery.items():
            snapshot_payload = dict(payload)
            snapshot_payload["dependency_key"] = str(snapshot_payload.get("dependency_key") or key)
            snapshot_payload["dependency_name"] = str(snapshot_payload.get("dependency_name") or key)
            snapshot_payload["mastery_stage"] = str(snapshot_payload.get("mastery_stage") or "understood")
            progress = snapshot_payload.get("mastery_stage_progress")
            snapshot_payload["mastery_stage_progress"] = (
                [str(item) for item in progress if str(item).strip()]
                if isinstance(progress, list)
                else ["understood"]
            )
            snapshot_payload["apis"] = [str(item) for item in snapshot_payload.get("apis", []) or [] if str(item).strip()]
            snapshot_payload["use_cases"] = [
                str(item) for item in snapshot_payload.get("use_cases", []) or [] if str(item).strip()
            ]
            snapshot_payload["scenarios"] = [
                str(item) for item in snapshot_payload.get("scenarios", []) or [] if str(item).strip()
            ]
            snapshot_payload["weakest_points"] = [
                str(item) for item in snapshot_payload.get("weakest_points", []) or [] if str(item).strip()
            ]
            snapshot_payload["evidence"] = [
                str(item) for item in snapshot_payload.get("evidence", []) or [] if str(item).strip()
            ]
            for field in (
                "latest_transfer_blocked_reason",
                "latest_transfer_evidence_id",
                "latest_transfer_evidence_summary",
                "latest_transfer_source_workspace_id",
                "latest_transfer_target_workspace_id",
                "latest_transfer_source_context",
                "latest_transfer_target_context",
            ):
                snapshot_payload[field] = str(snapshot_payload.get(field) or "")
            snapshot_payload["updated_at"] = str(snapshot_payload.get("updated_at") or utc_now().isoformat())
            snapshots.append(DependencyMasterySnapshot.model_validate(snapshot_payload))
        return sorted(snapshots, key=lambda item: item.updated_at, reverse=True)

    @staticmethod
    def _ensure_stage_progress(progress: list[str] | None, stage: str) -> list[str]:
        ordered = ["understood", "recalled", "practiced", "applied", "transferable"]
        normalized = [item for item in (progress or []) if item in ordered]
        if not normalized:
            normalized = ["understood"]
        if stage in ordered:
            for candidate in ordered:
                if candidate == stage:
                    if candidate not in normalized:
                        normalized.append(candidate)
                    break
                if candidate not in normalized and ordered.index(candidate) < ordered.index(stage):
                    normalized.append(candidate)
            if stage not in normalized:
                normalized.append(stage)
        seen: set[str] = set()
        result: list[str] = []
        for item in ordered:
            if item in normalized and item not in seen:
                seen.add(item)
                result.append(item)
        return result

    @staticmethod
    def _preserve_highest_mastery_stage(current: str, requested: str) -> str:
        ordered = ["understood", "recalled", "practiced", "applied", "transferable"]
        current_index = ordered.index(current) if current in ordered else 0
        requested_index = ordered.index(requested) if requested in ordered else current_index
        return ordered[max(current_index, requested_index)]

    def _record_training_event(
        self,
        structured: StructuredMemoryService,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        entry = {
            "event_id": f"evt-{uuid4().hex[:10]}",
            "event_type": event_type,
            "created_at": utc_now().isoformat(),
            **payload,
        }
        structured._training_event_ledger.append(entry)
        structured._training_event_ledger = structured._training_event_ledger[-80:]
        return entry

    def _build_dependency_skill_map(
        self,
        structured: StructuredMemoryService,
        dependency: DependencyMasterySnapshot,
        *,
        previous: DependencySkillMapSnapshot | None = None,
        action: str = "derived",
        note: str = "",
    ) -> DependencySkillMapSnapshot:
        language = _workspace_language(structured._workspace)

        def t(en: str, zh: str) -> str:
            return _localized_memory_text(en, zh, language)

        items: list[DependencySkillItemSnapshot] = []
        apis = dependency.apis or []
        scenarios = dependency.scenarios or []
        weakest_text = " ".join(dependency.weakest_points).lower()
        evidence_text = " ".join(dependency.evidence).lower()

        for api in apis:
            items.append(
                DependencySkillItemSnapshot(
                    key=f"{dependency.dependency_key}-api-{api.lower()}",
                    label=t(f"API: {api}", f"API：{api}"),
                    layer="api",
                    related_api=api,
                    scenario=scenarios[0] if scenarios else "",
                    knowledge_type="engineering_concept",
                    question_style="short_answer",
                    verification_method=t(
                        f"Explain when {api} belongs before using it.",
                        f"先说明 {api} 什么时候该出现，再决定要不要用它。",
                    ),
                    hint_ladder=[
                        t(
                            f"Name what problem {api} solves.",
                            f"先说 {api} 解决了什么问题。",
                        ),
                        t(
                            "State the narrowest real scenario where it belongs.",
                            "再说它最小、最真实的适用场景。",
                        ),
                    ],
                    priority=0.82,
                )
            )
        if scenarios:
            items.append(
                DependencySkillItemSnapshot(
                    key=f"{dependency.dependency_key}-scenario",
                    label=t("Minimum scenario", "最小场景"),
                    layer="scenario",
                    related_api=apis[0] if apis else "",
                    scenario=scenarios[0],
                    knowledge_type="scenario_judgment",
                    question_style="scenario_answer",
                    verification_method=t("Build one minimum scenario before widening scope.", "先做一个最小场景，再扩大范围。"),
                    hint_ladder=[
                        t("Keep exactly one boundary alive.", "只保留一个边界。"),
                        t("Verify one route or function before adding another branch.", "先验证一个 route 或 function，再加别的分支。"),
                    ],
                    priority=0.9,
                )
            )
        if apis:
            items.append(
                DependencySkillItemSnapshot(
                    key=f"{dependency.dependency_key}-parameter",
                    label=t(f"Parameter semantics: {apis[0]}", f"参数语义：{apis[0]}"),
                    layer="parameter",
                    related_api=apis[0],
                    scenario=scenarios[0] if scenarios else "",
                    knowledge_type="parameter_semantics",
                    question_style="parameter_check",
                    verification_method=t(
                        f"Explain what gets passed into {apis[0]} and why.",
                        f"说明传入 {apis[0]} 的是什么，以及为什么要这么传。",
                    ),
                    hint_ladder=[
                        t("Describe the input boundary first.", "先说明输入边界。"),
                        t("Then explain what the dependency call contributes.", "再说明这次 dependency 调用贡献了什么。"),
                    ],
                    priority=0.95 if "parameter" in weakest_text else 0.72,
                )
            )
            items.append(
                DependencySkillItemSnapshot(
                    key=f"{dependency.dependency_key}-return-value",
                    label=t(f"Return value semantics: {apis[0]}", f"返回值语义：{apis[0]}"),
                    layer="return_value",
                    related_api=apis[0],
                    scenario=scenarios[0] if scenarios else "",
                    knowledge_type="return_value_semantics",
                    question_style="return_value_check",
                    verification_method=t(
                        f"State what {apis[0]} returns into the caller boundary.",
                        f"说清楚 {apis[0]} 返回给调用方边界的是什么。",
                    ),
                    hint_ladder=[
                        t("Name the output first.", "先说输出。"),
                        t("Then connect it back to the surrounding code path.", "再把它接回周围的 code path。"),
                    ],
                    priority=0.94 if "return" in weakest_text else 0.7,
                )
            )
            items.append(
                DependencySkillItemSnapshot(
                    key=f"{dependency.dependency_key}-misuse",
                    label=t(f"Misuse check: {apis[0]}", f"误用检查：{apis[0]}"),
                    layer="misuse",
                    related_api=apis[0],
                    scenario=scenarios[0] if scenarios else "",
                    knowledge_type="misuse_correction",
                    question_style="misuse_correction",
                    verification_method=t(
                        f"Name the smallest misuse risk around {apis[0]} before coding.",
                        f"先说出围绕 {apis[0]} 最小的误用风险，再开始写代码。",
                    ),
                    hint_ladder=[
                        t("Say what would be widened too early.", "先说什么会被过早扩大。"),
                        t("Then say the guardrail that keeps the slice minimal.", "再说哪条 guardrail 能把切片保持最小。"),
                    ],
                    priority=0.92 if ("misuse" in weakest_text or "confuses" in weakest_text) else 0.68,
                )
            )
        items.append(
            DependencySkillItemSnapshot(
                key=f"{dependency.dependency_key}-concept",
                label=t("Dependency selection", "依赖选择"),
                layer="concept",
                related_api=apis[0] if apis else "",
                scenario=scenarios[0] if scenarios else "",
                knowledge_type="dependency_selection",
                question_style="short_answer",
                verification_method=t(
                    "Explain why this dependency belongs instead of a generic alternative.",
                    "说明为什么这里该用这个 dependency，而不是一个泛化替代。",
                ),
                hint_ladder=[
                    t("State the concrete pressure first.", "先说具体压力点。"),
                    t("Then justify the dependency boundary.", "再说明这个 dependency 边界为什么成立。"),
                ],
                priority=0.66,
            )
        )
        items.append(
            DependencySkillItemSnapshot(
                key=f"{dependency.dependency_key}-verification",
                label=t("Verification method", "验证方法"),
                layer="verification",
                related_api=apis[0] if apis else "",
                scenario=scenarios[0] if scenarios else "",
                knowledge_type="verification_method",
                question_style="short_answer",
                verification_method=t(
                    "Name the smallest proof that the dependency behavior is correct.",
                    "说出能证明这个 dependency 行为正确的最小证据。",
                ),
                hint_ladder=[
                    t("Start with one observable result.", "先从一个可观察结果开始。"),
                    t("Keep the proof tied to the boundary you changed.", "让证明紧扣你改动的那个边界。"),
                ],
                priority=0.64 if evidence_text else 0.58,
            )
        )
        items.append(
            DependencySkillItemSnapshot(
                key=f"{dependency.dependency_key}-transfer",
                label=t("Cross-context transfer", "跨场景迁移"),
                layer="transfer",
                related_api=apis[0] if apis else "",
                scenario="cross_project_transfer",
                knowledge_type="cross_context_transfer",
                question_style="scenario_answer",
                verification_method=t(
                    "Describe how you would prove the same judgment in another project slice.",
                    "说明你会怎样在另一个 project slice 里证明同样的判断。",
                ),
                hint_ladder=[
                    t("Keep the pattern the same.", "保持模式不变。"),
                    t("Change only the project context and restate the proof.", "只换 project context，再重述一次证明。"),
                ],
                priority=0.62,
            )
        )
        top_review_items = sorted(items, key=lambda item: item.priority, reverse=True)[:4]
        covered_layers = sorted({item.layer for item in items if item.layer})
        priority_summary = (
            t(
                f"Review {top_review_items[0].label} before widening scope.",
                f"先复习 {top_review_items[0].label} 再扩大范围。",
            )
            if top_review_items
            else t("Review the smallest missing dependency skill first.", "先复习最小的缺失 dependency skill。")
        )
        return DependencySkillMapSnapshot(
            dependency_key=dependency.dependency_key,
            dependency_name=dependency.dependency_name,
            version=(
                previous.version + 1
                if previous and action != "derived"
                else previous.version
                if previous
                else 1
            ),
            covered_layers=covered_layers,
            items=items,
            top_review_items=top_review_items,
            priority_summary=priority_summary,
            project_first_cut=scenarios[0]
            if scenarios
            else t(
                f"Build one minimum {dependency.dependency_name or dependency.dependency_key} slice first.",
                f"先做一个最小的 {dependency.dependency_name or dependency.dependency_key} 切片。",
            ),
            suggested_scenario_lab=scenarios[:2]
            or [t(f"Build one minimal {dependency.dependency_name or dependency.dependency_key} scenario.", f"先做一个最小的 {dependency.dependency_name or dependency.dependency_key} 场景。")],
            last_action=action or "derived",
            last_action_note=note,
            updated_at=utc_now().isoformat(),
        )

    def _sync_dependency_training_views(self, structured: StructuredMemoryService) -> None:
        synced: dict[str, DependencySkillMapSnapshot] = {}
        for dependency in self._dependency_mastery_snapshots(structured):
            previous = structured._dependency_skill_maps.get(dependency.dependency_key)
            if previous and previous.last_action != "derived":
                synced[dependency.dependency_key] = previous
                continue
            synced[dependency.dependency_key] = self._build_dependency_skill_map(
                structured,
                dependency,
                previous=previous,
            )
        structured._dependency_skill_maps = synced
        if structured._dependency_mastery:
            dependency_keys = set(structured._dependency_skill_maps.keys())
            flash_deck_keys = {
                str(item.dependency_key or "").strip().lower()
                for item in (structured._flash_deck.cards if structured._flash_deck else [])
                if str(item.dependency_key or "").strip()
            }
            theory_drill_keys = {
                str(item or "").strip().lower()
                for item in (structured._theory_drill.dependency_keys if structured._theory_drill else [])
                if str(item or "").strip()
            }
            if structured._flash_deck is None or (flash_deck_keys and flash_deck_keys != dependency_keys):
                structured._flash_deck = self._build_flash_deck_snapshot(structured)
            if structured._theory_drill is None or (theory_drill_keys and theory_drill_keys != dependency_keys):
                structured._theory_drill = self._build_theory_drill_snapshot(structured)

    def _leftover_persist_context(
        self,
        workspace_id: str,
    ) -> tuple[Any, dict[str, Any], str]:
        plan = self.repository.get_latest_plan(workspace_id) if self.repository is not None else None
        structured = self._structured_for(workspace_id)
        workspace = structured._workspace if isinstance(getattr(structured, "_workspace", None), dict) else {}
        recovered = select_plan_runtime_for_scope(
            workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
            workspace_id,
        )
        runtime = recovered if isinstance(recovered, dict) else {}
        task = normalize_latest_current_task(
            workspace.get(CURRENT_TASK_KEY)
            or workspace.get("current_task")
            or workspace.get("currentTask"),
            workspace_id,
        ) or {}
        return plan, runtime, str(task.get("title") or "").strip()

    def _training_handoff_generator(self, workspace_id: str) -> TrainingHandoffGenerator:
        leftover_plan, leftover_runtime, leftover_task_title = self._leftover_persist_context(
            workspace_id
        )
        return TrainingHandoffGenerator(
            leftover_plan=leftover_plan,
            leftover_runtime=leftover_runtime,
            leftover_task_title=leftover_task_title,
        )

    def _live_training_persist_chrome(
        self,
        workspace_id: str,
        *,
        card_title: str,
        summary: str = "",
    ) -> dict[str, str]:
        plan, runtime, task_title = self._leftover_persist_context(workspace_id)
        return live_training_persist_chrome(
            plan=plan,
            runtime=runtime,
            existing=runtime,
            task_title=task_title,
            card_title=card_title,
            summary=summary,
        )

    @property
    def structured(self) -> StructuredMemoryService:
        workspace_id = self._resolve_workspace_for_write(None)
        return self._structured_for(workspace_id)

    def snapshot(self, workspace_id: str) -> MemorySnapshot:
        context_id = self.repository.resolve_context_id(workspace_id)
        asset_catalog = (
            self._asset_library.catalog(context_id)
            if context_id
            else LibraryAssetCatalogSnapshot()
        )
        profile = self.repository.get_profile(workspace_id)
        global_memory = self.global_memory()
        plan = self.repository.get_latest_plan(workspace_id)
        plan_id = (plan.id or plan.plan_id) if plan else ""
        subplans = self.repository.list_subplans(plan_id) if plan_id else []
        resources = self.repository.list_resources(workspace_id)
        if callable(self._resource_dedupe_hook):
            resources = self._resource_dedupe_hook(resources)
        resources = select_resources_for_scope(resources, workspace_id)
        structured_service = self._structured_for(workspace_id)
        self._sync_dependency_training_views(structured_service)
        lane_snapshot = structured_service.snapshot()
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        coach_defaults = self._coach_defaults_from_workspace(workspace)
        toggles = self._workspace_memory_toggles(workspace)
        memory_scope = self._memory_scope(workspace)
        personal_lane_snapshot = (
            self._build_personal_lane_snapshot(workspace_id, lane_snapshot)
            if memory_scope == "personal"
            else lane_snapshot
        )
        active_lane_snapshot = personal_lane_snapshot if memory_scope == "personal" else lane_snapshot
        active_thread = self._active_thread_snapshot(lane_snapshot)
        provider_recovery_blocked = self._is_provider_recovery_thread(
            lane_snapshot.workspace.get("active_thread")
        )
        workspace_understanding = self._workspace_understanding_snapshot(lane_snapshot)
        current_focus_context = _memory_language_context(
            workspace,
            self._workspace_value(active_lane_snapshot, "summary"),
            self._workspace_value(active_lane_snapshot, "focus_area"),
        )
        profile_goal = (
            profile.long_term_goal
            if profile and profile.long_term_goal
            else profile.long_term_goals[0]
            if profile and profile.long_term_goals
            else ""
        )
        if not profile_goal:
            for preference in getattr(active_lane_snapshot, "preferences", []):
                if preference.key == "long_term_goal":
                    profile_goal = preference.value.strip()
                    if profile_goal:
                        break
        raw_weakness_records = self._derive_weakness_records(resources, plan, active_lane_snapshot)
        visible_weakness_records = self._visible_weakness_records(raw_weakness_records)
        weaknesses = [item.reason for item in visible_weakness_records]
        reflections = [item.summary for item in active_lane_snapshot.reflections[-5:]]
        if not reflections:
            reflections = [
                _localized_memory_text(
                    "Prefer spec-first feedback over direct answers.",
                    "优先先对齐目标和约束，再决定要不要直接给答案。",
                    current_focus_context,
                ),
                _localized_memory_text(
                    "Track repeated boundary-condition misses.",
                    "持续盯住那些容易被跳过的边界条件和验证点。",
                    current_focus_context,
                ),
            ]
        if not toggles["decisions"]:
            reflections = reflections[:1]
        recent_summary = lane_snapshot.session.rolling_summary if lane_snapshot.session else ""
        session_highlights = lane_snapshot.session.highlights if lane_snapshot.session else []
        if not recent_summary:
            recent_summary = _localized_memory_text(
                "Trainer is maintaining a local memory snapshot for this workspace.",
                "教练正在为当前工作区持续维护一份本地训练记忆。",
                current_focus_context,
            )
        due_reviews = self._visible_due_reviews(
            self._prepend_transfer_review(
                self._derive_due_reviews(plan, active_lane_snapshot, raw_weakness_records),
                active_lane_snapshot,
            )
        )
        teaching_observations = self._derive_teaching_observations(
            plan,
            active_lane_snapshot,
            visible_weakness_records,
            language_context=current_focus_context,
        )
        recent_wins = self._derive_recent_wins(plan, resources, active_lane_snapshot)
        current_focus = self._derive_current_focus(
            plan,
            recent_summary,
            active_lane_snapshot,
            language_context=current_focus_context,
        )
        review_rhythm = self._derive_review_rhythm(due_reviews, active_lane_snapshot)
        coach_anchor = self._derive_coach_anchor(plan, active_lane_snapshot)
        top_weakness = self._top_actionable_weakness(raw_weakness_records)
        lowest_mastery_concepts = self._derive_lowest_mastery_concepts(active_lane_snapshot)
        pace_signal = self._derive_pace_signal(plan, due_reviews, active_lane_snapshot)
        remembered_preference_record = self._preferred_preference(active_lane_snapshot)
        remembered_preference_text = ""
        preference_summary = self._summarize_preferences(active_lane_snapshot)
        personal_transfer_summary = self._personal_transfer_observation(active_lane_snapshot)
        decision_summary = self._summarize_decisions(active_lane_snapshot)
        progress_summary = self._summarize_progress(active_lane_snapshot)
        goal_summary = self._summarize_goal(profile_goal, active_lane_snapshot)
        latest_turn_summary = self._summarize_latest_turn(active_lane_snapshot)
        teaching_signal_summary = self._summarize_teaching_signal(active_lane_snapshot)
        weakness_pattern_summary = self._summarize_weakness_patterns(active_lane_snapshot)
        prefers_chinese = _prefers_chinese_text(
            " ".join(
                [
                    current_focus_context,
                    recent_summary,
                    active_lane_snapshot.session.rolling_summary if active_lane_snapshot.session else "",
                ]
            )
        )
        if (
            remembered_preference_record
            and toggles["decisions"]
            and memory_scope != "session"
            and not provider_recovery_blocked
        ):
            remembered_preference_text = _localized_memory_text(
                f"Remembered preference: {remembered_preference_record.key} = {remembered_preference_record.value}",
                f"已记住你的偏好：{remembered_preference_record.key} = {remembered_preference_record.value}",
                current_focus_context or recent_summary or remembered_preference_record.value,
            )
        if provider_recovery_blocked:
            pass
        elif memory_scope == "session":
            thread_focus = active_thread.focus_area if active_thread else ""
            thread_next_step = (
                _strip_visible_next_step_prefix(active_thread.next_step) if active_thread else ""
            )
            session_anchor = thread_next_step or (lane_snapshot.session.rolling_summary if lane_snapshot.session else "")
            if thread_focus or session_anchor:
                current_focus = _localized_memory_text(
                    f"Current coaching focus: stay on the live session thread around '{thread_focus}' and keep the next reply attached to: {session_anchor}"
                    if thread_focus and session_anchor
                    else f"Current coaching focus: stay on the live session thread and keep the next reply attached to: {session_anchor or thread_focus}",
                    f"当前聚焦：先紧贴这次会话里正在推进的主线继续，不要切题。下一轮继续接着这一步：{session_anchor}"
                    if session_anchor
                    else f"当前聚焦：先紧贴这次会话里正在推进的主线继续，不要切题。当前主线是：{thread_focus}",
                    current_focus_context or recent_summary or thread_focus or session_anchor,
                )
            if lane_snapshot.session and lane_snapshot.session.rolling_summary:
                recent_summary = lane_snapshot.session.rolling_summary
            if lane_snapshot.session and lane_snapshot.session.highlights:
                recent_wins = lane_snapshot.session.highlights[-3:] + recent_wins
            due_reviews = due_reviews[:1]
            current_focus = (
                f"{current_focus} 当前记忆范围：仅本次会话。"
                if prefers_chinese
                else f"{current_focus} Memory scope is session."
            )
        elif memory_scope == "personal":
            base_focus = current_focus
            personal_prefix = (
                _localized_memory_text(
                    f"Long-term goal remains in view: {profile_goal}.",
                    f"长期目标仍在前面：{profile_goal}。",
                    current_focus_context or recent_summary or profile_goal,
                )
                if goal_summary
                else _localized_memory_text(
                    "Personal memory is active, so keep the reusable habits and judgment in play.",
                    "个人长期记忆已开启，继续把那些可迁移的习惯和判断带在身上。",
                    current_focus_context or recent_summary or current_focus,
                )
            )
            if preference_summary:
                personal_prefix = f"{personal_prefix} {preference_summary}".strip()
            current_focus = f"{base_focus} {personal_prefix}".strip()
            if remembered_preference_text:
                recent_wins = [remembered_preference_text] + recent_wins
            if personal_transfer_summary and personal_transfer_summary not in teaching_observations:
                teaching_observations = [personal_transfer_summary, *teaching_observations][:4]
            if teaching_signal_summary and teaching_signal_summary not in teaching_observations:
                teaching_observations = [teaching_signal_summary, *teaching_observations][:4]
            if weakness_pattern_summary and weakness_pattern_summary not in teaching_observations:
                teaching_observations = [weakness_pattern_summary, *teaching_observations][:4]
            if active_lane_snapshot.mastery:
                lowest_mastery_concepts = self._derive_lowest_mastery_concepts(active_lane_snapshot)[:2]
            current_focus = (
                f"{current_focus} 当前记忆范围：个人长期记忆。"
                if prefers_chinese
                else f"{current_focus} Memory scope is personal."
            )
        else:
            current_focus = current_focus.strip()
        if (
            not provider_recovery_blocked
            and coach_defaults.get("working_set_mode") == "focused"
            and current_focus
        ):
            current_focus = _localized_memory_text(
                f"{current_focus} Focused working set: stay tight on the smallest verifiable slice and only the nearest files.",
                f"{current_focus} 当前工作集策略：尽量只盯住最小可验证切片和最近的相关文件。",
                current_focus,
            )
        elif (
            not provider_recovery_blocked
            and coach_defaults.get("working_set_mode") == "broad"
            and current_focus
        ):
            current_focus = _localized_memory_text(
                f"{current_focus} You may widen into directly connected context if it helps verify the patch.",
                f"{current_focus} 如果有助于验证这次改动，可以适度带上直接相关的更宽上下文。",
                current_focus,
            )
        teaching_observations = teaching_observations[:4]

        def ensure_observation(value: str, preferred_index: int | None = None) -> None:
            nonlocal teaching_observations
            if not value:
                return
            if value in teaching_observations:
                return
            if preferred_index is None:
                if len(teaching_observations) < 4:
                    teaching_observations.append(value)
                else:
                    teaching_observations[-1] = value
                return
            bounded_index = max(0, min(preferred_index, len(teaching_observations)))
            teaching_observations.insert(bounded_index, value)
            teaching_observations = teaching_observations[:4]

        if not provider_recovery_blocked and preference_summary and toggles["decisions"]:
            ensure_observation(preference_summary, preferred_index=2)
        if not provider_recovery_blocked and goal_summary:
            ensure_observation(goal_summary, preferred_index=2)
        if not provider_recovery_blocked and teaching_signal_summary and toggles["patterns"]:
            ensure_observation(teaching_signal_summary)
        if not provider_recovery_blocked and weakness_pattern_summary:
            ensure_observation(weakness_pattern_summary)
        if not provider_recovery_blocked and remembered_preference_text and toggles["decisions"]:
            ensure_observation(remembered_preference_text, preferred_index=3)
        if not provider_recovery_blocked and latest_turn_summary:
            ensure_observation(latest_turn_summary, preferred_index=1)
        if (
            not provider_recovery_blocked
            and decision_summary
            and toggles["decisions"]
            and decision_summary not in recent_wins
        ):
            recent_wins = [decision_summary, *recent_wins][:3]
        if (
            not provider_recovery_blocked
            and goal_summary
            and goal_summary not in recent_wins
            and memory_scope == "personal"
        ):
            recent_wins = [goal_summary, *recent_wins][:3]
        if (
            not provider_recovery_blocked
            and personal_transfer_summary
            and personal_transfer_summary not in recent_wins
            and memory_scope == "personal"
        ):
            recent_wins = [personal_transfer_summary, *recent_wins][:3]
        if (
            not provider_recovery_blocked
            and
            remembered_preference_text
            and remembered_preference_text not in recent_wins
            and memory_scope == "personal"
        ):
            recent_wins = [remembered_preference_text, *recent_wins][:3]
        if session_highlights and memory_scope != "project":
            recent_summary = " ".join([recent_summary, *session_highlights[-2:]]).strip()
        active_thread_next_step = (
            str(active_thread.next_step or "").strip() if active_thread and active_thread.next_step else ""
        )
        progress_repeats_active_thread_next_step = (
            bool(active_thread_next_step)
            and active_thread_next_step in current_focus
            and active_thread_next_step in progress_summary
        )
        if (
            not provider_recovery_blocked
            and progress_summary
            and toggles["patterns"]
            and progress_summary not in current_focus
            and not progress_repeats_active_thread_next_step
        ):
            current_focus = f"{current_focus} {progress_summary}".strip()
        if not toggles["patterns"]:
            recent_wins = [item for item in recent_wins if "progress" not in item.lower()]
        if not toggles["resources"]:
            resources = []

        foreground_observation = teaching_observations[0] if teaching_observations else ""
        preferred_observation = remembered_preference_text or (
            preference_summary if toggles["decisions"] else ""
        )
        curated_teaching_observations: list[str] = []

        def append_curated_observation(value: str) -> None:
            cleaned = value.strip()
            if not cleaned or cleaned in curated_teaching_observations:
                return
            curated_teaching_observations.append(cleaned)

        if provider_recovery_blocked:
            for candidate in (
                foreground_observation,
                latest_turn_summary,
            ):
                append_curated_observation(candidate)
        elif memory_scope == "personal":
            for candidate in (
                weakness_pattern_summary,
                personal_transfer_summary,
                preferred_observation,
                goal_summary,
                latest_turn_summary,
                foreground_observation,
                teaching_signal_summary,
            ):
                append_curated_observation(candidate)
        else:
            for candidate in (
                foreground_observation,
                latest_turn_summary,
                self._onboarding_blocker_summary(active_lane_snapshot),
                preferred_observation,
                goal_summary,
                weakness_pattern_summary,
                teaching_signal_summary,
            ):
                append_curated_observation(candidate)

        for candidate in teaching_observations:
            append_curated_observation(candidate)

        transfer_observation = self._transfer_skill_observation(active_lane_snapshot)
        if transfer_observation:
            curated_teaching_observations = [
                transfer_observation,
                *[item for item in curated_teaching_observations if item != transfer_observation],
            ]
        teaching_observations = curated_teaching_observations[:4]
        workspace_payload = dict(lane_snapshot.workspace)
        workspace_payload.setdefault("workspace_id", workspace_id)
        user_feedback_items = [
            {
                "kind": item.kind,
                "message": item.message,
                "focus_area": item.focus_area,
                "scenario": item.scenario,
                "training_card_id": item.training_card_id,
                "plan_id": item.plan_id,
                "created_at": item.created_at.isoformat(),
            }
            for item in active_lane_snapshot.user_feedback[:8]
        ]
        teaching_strategy_items = [
            {
                "key": item.key,
                "scenario": item.scenario,
                "focus_area": item.focus_area,
                "challenge_level": item.challenge_level,
                "hint_depth": item.hint_depth,
                "review_urgency": item.review_urgency,
                "explanation_mode": item.explanation_mode,
                "next_step_bias": item.next_step_bias,
                "success_count": item.success_count,
                "failure_count": item.failure_count,
                "total_count": item.total_count,
                "last_outcome": item.last_outcome,
                "last_summary": item.last_summary,
                "last_verified_result": item.last_verified_result,
                "last_updated_at": item.last_updated_at.isoformat(),
            }
            for item in active_lane_snapshot.teaching_strategy_effectiveness[:6]
        ]
        learning_outcome_items = [
            {
                "concept": item.concept,
                "outcome": item.outcome,
                "summary": item.summary,
                "checks": list(item.checks),
                "missing_requirements": list(item.missing_requirements),
                "repetition_count": item.repetition_count,
                "action_type": item.action_type,
                "updated_at": item.updated_at.isoformat(),
            }
            for item in active_lane_snapshot.learning_outcomes[:8]
        ]
        recovered = select_plan_runtime_for_scope(
            workspace_payload.get(PLAN_RUNTIME_KEY) or workspace_payload.get("latestPlanRuntime"),
            workspace_id,
        )
        teaching_asset_items = self.list_teaching_assets(workspace_id=workspace_id)
        training_card_items = self.get_cards(workspace_id)
        leftover_plans = []
        list_plans = getattr(self.repository, "list_plans", None)
        if callable(list_plans):
            leftover_plans = list_plans(workspace_id)
        competing_identity = leftover_bound_plan_competing_identity_labels(
            plan=plan,
            runtime=recovered if isinstance(recovered, dict) else {},
            existing=recovered if isinstance(recovered, dict) else {},
            card_titles=[
                str(getattr(card, "title", "") or "")
                for card in training_card_items
            ],
            leftover_plans=leftover_plans,
        )
        if competing_identity:
            resources = [
                item
                for item in resources
                if str(getattr(item, "name", "") or getattr(item, "title", "") or "").strip()
                not in competing_identity
            ]
        review_artifact_item = structured_service._review_artifact
        dependency_mastery = self._dependency_mastery_snapshots(structured_service)
        flash_deck = structured_service._flash_deck or (
            self._build_flash_deck_snapshot(structured_service) if dependency_mastery else None
        )
        scenario_lab_item = structured_service._scenario_lab
        theory_drill = structured_service._theory_drill or self._build_theory_drill_snapshot(structured_service)
        snapshot_overlay = live_memory_snapshot_overlay(
            plan=plan,
            runtime=recovered,
            existing=recovered,
            recent_summary=recent_summary,
            workspace=workspace_payload,
            active_thread=active_thread,
            teaching_observations=teaching_observations,
            user_feedback=user_feedback_items,
            recent_wins=recent_wins,
            weaknesses=weaknesses,
            teaching_strategy_effectiveness=teaching_strategy_items,
            learning_outcomes=learning_outcome_items,
            top_weakness=top_weakness,
            reflections=reflections,
            lowest_mastery_concepts=lowest_mastery_concepts,
            due_reviews=[
                {
                    "concept": item.concept,
                    "reason": item.reason,
                    "focus_area": item.focus_area,
                    "task_hint": item.task_hint,
                }
                for item in due_reviews
            ],
            teaching_assets=[
                {
                    "title": item.title,
                    "summary": item.summary,
                    "focus_area": item.focus_area,
                    "concept_card": item.concept_card,
                    "source_summary": item.source_summary,
                }
                for item in teaching_asset_items
            ],
            training_cards=[
                {
                    "title": item.title,
                    "why_now": item.why_now,
                    "focus_area": item.focus_area,
                    "target_skill": item.target_skill,
                    "problem_statement": item.problem_statement,
                    "question": item.question,
                    "scenario": item.scenario,
                    "suggested_workspace_action": item.suggested_workspace_action,
                    "deliverable": item.deliverable,
                    "context": item.context,
                    "expected_answer": item.expected_answer,
                    "stuck_recovery": item.stuck_recovery,
                    "reflection_prompt": item.reflection_prompt,
                    "success_signal": item.success_signal,
                    "return_with": item.return_with,
                    "next_after_completion": item.next_after_completion,
                    "learner_deliverables": list(item.learner_deliverables),
                    "next_steps": list(item.next_steps),
                }
                for item in training_card_items
            ],
            review_artifact=(
                {
                    "title": review_artifact_item.title,
                    "focus_area": review_artifact_item.focus_area,
                    "summary": review_artifact_item.summary,
                    "root_cause": review_artifact_item.root_cause,
                    "guardrail": review_artifact_item.guardrail,
                    "verified_result": review_artifact_item.verified_result,
                    "blocker": review_artifact_item.blocker,
                }
                if review_artifact_item is not None
                else None
            ),
            review_artifact_history=[
                {
                    "note": item.note,
                    "before_snapshot": dict(item.before_snapshot),
                    "after_snapshot": dict(item.after_snapshot),
                }
                for item in structured_service._review_artifact_history
            ],
            scenario_lab=(
                {
                    "title": scenario_lab_item.title,
                    "focus_area": scenario_lab_item.focus_area,
                    "summary": scenario_lab_item.summary,
                    "success_signal": scenario_lab_item.success_signal,
                    "review_outcome": scenario_lab_item.review_outcome,
                    "learner_deliverables": list(scenario_lab_item.learner_deliverables),
                    "verification_steps": list(scenario_lab_item.verification_steps),
                    "migrate_back_guidance": list(scenario_lab_item.migrate_back_guidance),
                }
                if scenario_lab_item is not None
                else None
            ),
            scenario_lab_history=[
                {
                    "note": item.note,
                    "before_snapshot": dict(item.before_snapshot),
                    "after_snapshot": dict(item.after_snapshot),
                }
                for item in structured_service._scenario_lab_history
            ],
            flash_deck=(
                {
                    "title": flash_deck.title,
                    "focus_area": flash_deck.focus_area,
                    "cards": [
                        {
                            "title": card.title,
                            "why_now": card.why_now,
                            "focus_area": card.focus_area,
                            "target_skill": card.target_skill,
                            "problem_statement": card.problem_statement,
                            "question": card.question,
                            "scenario": card.scenario,
                            "deliverable": card.deliverable,
                            "success_signal": card.success_signal,
                        }
                        for card in flash_deck.cards
                    ],
                }
                if flash_deck is not None
                else None
            ),
            theory_drill=(
                {
                    "title": theory_drill.title,
                    "focus_area": theory_drill.focus_area,
                    "summary": theory_drill.summary,
                    "success_signal": theory_drill.success_signal,
                    "return_with": theory_drill.return_with,
                    "questions": [
                        {
                            "prompt": question.prompt,
                            "answer": question.answer,
                            "explanation": question.explanation,
                            "knowledge_type": question.knowledge_type,
                            "choices": list(question.choices),
                        }
                        for question in theory_drill.questions
                    ],
                }
                if theory_drill is not None
                else None
            ),
            theory_drill_history=[
                {
                    "note": item.note,
                    "before_snapshot": dict(item.before_snapshot),
                    "after_snapshot": dict(item.after_snapshot),
                }
                for item in structured_service._theory_drill_history
            ],
        )
        recent_summary = snapshot_overlay["recent_summary"]
        workspace_payload = apply_teaching_artifact_scope(
            apply_affect_tone_scope(
                apply_evaluation_chrome_scope(
                    apply_coaching_focus_scope(
                        apply_current_task_scope(
                            apply_training_chrome_scope(
                                snapshot_overlay["workspace"],
                                workspace_id,
                            ),
                            workspace_id,
                        ),
                        workspace_id,
                    ),
                    workspace_id,
                ),
                workspace_id,
            ),
            workspace_id,
        )
        # Keep the recovered runtime step visible after all scope/gating passes.
        current_runtime = structured_service._workspace.get(PLAN_RUNTIME_KEY)
        recovered_step = str(
            (current_runtime or {}).get("current_step")
            or (recovered or {}).get("current_step")
            or ""
        ).strip()
        if recovered_step:
            current_hop = workspace_payload.get("latest_training_next_hop")
            if not isinstance(current_hop, dict):
                current_hop = structured_service._workspace.get("latest_training_next_hop")
            workspace_payload["latest_training_next_hop"] = {
                **(current_hop if isinstance(current_hop, dict) else {}),
                "title": recovered_step,
                "card_title": recovered_step,
            }
        teaching_observations = snapshot_overlay["teaching_observations"]
        user_feedback_items = snapshot_overlay["user_feedback"]
        recent_wins = snapshot_overlay["recent_wins"]
        weaknesses = snapshot_overlay["weaknesses"]
        teaching_strategy_items = snapshot_overlay["teaching_strategy_effectiveness"]
        learning_outcome_items = snapshot_overlay["learning_outcomes"]
        top_weakness = snapshot_overlay["top_weakness"]
        reflections = snapshot_overlay["reflections"]
        lowest_mastery_concepts = snapshot_overlay["lowest_mastery_concepts"]
        due_reviews = [
            item.model_copy(
                update={
                    "concept": payload.get("concept", item.concept),
                    "reason": payload.get("reason", item.reason),
                    "focus_area": payload.get("focus_area", item.focus_area),
                    "task_hint": payload.get("task_hint", item.task_hint),
                }
            )
            for item, payload in zip(due_reviews, snapshot_overlay["due_reviews"], strict=True)
        ]
        teaching_asset_items = [
            item.model_copy(
                update={
                    "title": payload.get("title", item.title),
                    "summary": payload.get("summary", item.summary),
                    "focus_area": payload.get("focus_area", item.focus_area),
                    "concept_card": payload.get("concept_card", item.concept_card),
                    "source_summary": payload.get("source_summary", item.source_summary),
                }
            )
            for item, payload in zip(teaching_asset_items, snapshot_overlay["teaching_assets"], strict=True)
        ]
        training_card_items = [
            item.model_copy(
                update={
                    "title": payload.get("title", item.title),
                    "why_now": payload.get("why_now", item.why_now),
                    "focus_area": payload.get("focus_area", item.focus_area),
                    "target_skill": payload.get("target_skill", item.target_skill),
                    "problem_statement": payload.get("problem_statement", item.problem_statement),
                    "question": payload.get("question", item.question),
                    "scenario": payload.get("scenario", item.scenario),
                    "suggested_workspace_action": payload.get(
                        "suggested_workspace_action",
                        item.suggested_workspace_action,
                    ),
                    "deliverable": payload.get("deliverable", item.deliverable),
                    "context": payload.get("context", item.context),
                    "expected_answer": payload.get("expected_answer", item.expected_answer),
                    "stuck_recovery": payload.get("stuck_recovery", item.stuck_recovery),
                    "reflection_prompt": payload.get("reflection_prompt", item.reflection_prompt),
                    "success_signal": payload.get("success_signal", item.success_signal),
                    "return_with": payload.get("return_with", item.return_with),
                    "next_after_completion": payload.get(
                        "next_after_completion",
                        item.next_after_completion,
                    ),
                    "learner_deliverables": payload.get(
                        "learner_deliverables",
                        item.learner_deliverables,
                    ),
                    "next_steps": payload.get("next_steps", item.next_steps),
                }
            )
            for item, payload in zip(training_card_items, snapshot_overlay["training_cards"], strict=True)
        ]
        if review_artifact_item is not None and snapshot_overlay["review_artifact"]:
            gated_artifact = snapshot_overlay["review_artifact"]
            review_artifact_item = review_artifact_item.model_copy(
                update={
                    "title": gated_artifact.get("title", review_artifact_item.title),
                    "focus_area": gated_artifact.get("focus_area", review_artifact_item.focus_area),
                    "summary": gated_artifact.get("summary", review_artifact_item.summary),
                    "root_cause": gated_artifact.get("root_cause", review_artifact_item.root_cause),
                    "guardrail": gated_artifact.get("guardrail", review_artifact_item.guardrail),
                    "verified_result": gated_artifact.get(
                        "verified_result",
                        review_artifact_item.verified_result,
                    ),
                    "blocker": gated_artifact.get("blocker", review_artifact_item.blocker),
                }
            )
        review_artifact_history_items = [
            item.model_copy(
                update={
                    "note": payload.get("note", item.note),
                    "before_snapshot": payload.get("before_snapshot", item.before_snapshot),
                    "after_snapshot": payload.get("after_snapshot", item.after_snapshot),
                }
            )
            for item, payload in zip(
                structured_service._review_artifact_history,
                snapshot_overlay["review_artifact_history"],
                strict=True,
            )
        ]
        if scenario_lab_item is not None and snapshot_overlay["scenario_lab"]:
            gated_lab = snapshot_overlay["scenario_lab"]
            scenario_lab_item = scenario_lab_item.model_copy(
                update={
                    "title": gated_lab.get("title", scenario_lab_item.title),
                    "focus_area": gated_lab.get("focus_area", scenario_lab_item.focus_area),
                    "summary": gated_lab.get("summary", scenario_lab_item.summary),
                    "success_signal": gated_lab.get("success_signal", scenario_lab_item.success_signal),
                    "review_outcome": gated_lab.get("review_outcome", scenario_lab_item.review_outcome),
                    "learner_deliverables": gated_lab.get(
                        "learner_deliverables",
                        scenario_lab_item.learner_deliverables,
                    ),
                    "verification_steps": gated_lab.get(
                        "verification_steps",
                        scenario_lab_item.verification_steps,
                    ),
                    "migrate_back_guidance": gated_lab.get(
                        "migrate_back_guidance",
                        scenario_lab_item.migrate_back_guidance,
                    ),
                }
            )
        scenario_lab_history_items = [
            item.model_copy(
                update={
                    "note": payload.get("note", item.note),
                    "before_snapshot": payload.get("before_snapshot", item.before_snapshot),
                    "after_snapshot": payload.get("after_snapshot", item.after_snapshot),
                }
            )
            for item, payload in zip(
                structured_service._scenario_lab_history,
                snapshot_overlay["scenario_lab_history"],
                strict=True,
            )
        ]
        if flash_deck is not None and snapshot_overlay["flash_deck"]:
            gated_deck = snapshot_overlay["flash_deck"]
            gated_flash_cards = list(gated_deck.get("cards") or [])
            flash_deck = flash_deck.model_copy(
                update={
                    "title": gated_deck.get("title", flash_deck.title),
                    "focus_area": gated_deck.get("focus_area", flash_deck.focus_area),
                    "cards": [
                        card.model_copy(
                            update={
                                "title": payload.get("title", card.title),
                                "why_now": payload.get("why_now", card.why_now),
                                "focus_area": payload.get("focus_area", card.focus_area),
                                "target_skill": payload.get("target_skill", card.target_skill),
                                "problem_statement": payload.get(
                                    "problem_statement",
                                    card.problem_statement,
                                ),
                                "question": payload.get("question", card.question),
                                "scenario": payload.get("scenario", card.scenario),
                                "deliverable": payload.get("deliverable", card.deliverable),
                                "success_signal": payload.get("success_signal", card.success_signal),
                            }
                        )
                        for card, payload in zip(flash_deck.cards, gated_flash_cards, strict=True)
                    ],
                }
            )
        if theory_drill is not None and snapshot_overlay["theory_drill"]:
            gated_drill = snapshot_overlay["theory_drill"]
            gated_questions = list(gated_drill.get("questions") or [])
            theory_drill = theory_drill.model_copy(
                update={
                    "title": gated_drill.get("title", theory_drill.title),
                    "focus_area": gated_drill.get("focus_area", theory_drill.focus_area),
                    "summary": gated_drill.get("summary", theory_drill.summary),
                    "success_signal": gated_drill.get("success_signal", theory_drill.success_signal),
                    "return_with": gated_drill.get("return_with", theory_drill.return_with),
                    "questions": [
                        question.model_copy(
                            update={
                                "prompt": payload.get("prompt", question.prompt),
                                "answer": payload.get("answer", question.answer),
                                "explanation": payload.get("explanation", question.explanation),
                                "knowledge_type": payload.get(
                                    "knowledge_type",
                                    question.knowledge_type,
                                ),
                                "choices": payload.get("choices", question.choices),
                            }
                        )
                        for question, payload in zip(theory_drill.questions, gated_questions, strict=True)
                    ],
                }
            )
        theory_drill_history_items = [
            item.model_copy(
                update={
                    "note": payload.get("note", item.note),
                    "before_snapshot": payload.get("before_snapshot", item.before_snapshot),
                    "after_snapshot": payload.get("after_snapshot", item.after_snapshot),
                }
            )
            for item, payload in zip(
                structured_service._theory_drill_history,
                snapshot_overlay["theory_drill_history"],
                strict=True,
            )
        ]
        if active_thread is not None and snapshot_overlay["active_thread"]:
            active_thread = active_thread.model_copy(update=snapshot_overlay["active_thread"])
        dependency_skill_maps = list(structured_service._dependency_skill_maps.values())
        evidence_queue = self.evidence_queue(workspace_id)
        coaching_adaptation = self._derive_coaching_adaptation_profile(
            active_lane_snapshot,
            profile=profile,
            plan=plan,
            due_reviews=due_reviews,
            workspace_id=workspace_id,
        )
        if coaching_adaptation is not None:
            gated_adaptation = live_memory_snapshot_overlay(
                plan=plan,
                runtime=recovered,
                existing=recovered,
                coaching_adaptation={
                    "summary": coaching_adaptation.summary,
                    "evidence": list(coaching_adaptation.evidence),
                },
            )["coaching_adaptation"]
            coaching_adaptation = coaching_adaptation.model_copy(
                update={
                    "summary": gated_adaptation.get("summary", ""),
                    "evidence": list(gated_adaptation.get("evidence") or []),
                }
            )
        snapshot = MemorySnapshot(
            profile=profile,
            globalMemory=global_memory,
            active_plan=plan,
            subplans=subplans,
            resources=resources,
            assetCatalog=asset_catalog,
            teaching_assets=teaching_asset_items,
            memory_share_grants=self.list_memory_share_grants(workspace_id),
            coaching_adaptation=coaching_adaptation,
            teaching_strategy_effectiveness=teaching_strategy_items,
            learning_outcomes=learning_outcome_items,
            weaknesses=weaknesses,
            reflections=reflections,
            recent_summary=recent_summary,
            current_focus=current_focus,
            coach_anchor=coach_anchor,
            top_weakness=top_weakness,
            lowest_mastery_concepts=lowest_mastery_concepts,
            recent_wins=recent_wins,
            review_rhythm=review_rhythm,
            due_reviews=due_reviews,
            due_review_count=len(due_reviews),
            pace_signal=pace_signal,
            teaching_observations=teaching_observations,
            user_feedback=user_feedback_items,
            workspace=workspace_payload,
            active_thread=active_thread,
            workspace_understanding=workspace_understanding,
            dependency_mastery=dependency_mastery,
            dependency_skill_maps=dependency_skill_maps,
            dependency_skill_map_history=list(structured_service._dependency_skill_map_history),
            flash_deck=flash_deck,
            recent_flash_attempts=list(structured_service._recent_flash_attempts),
            theory_drill=theory_drill,
            theory_drill_history=theory_drill_history_items,
            scenario_lab=scenario_lab_item,
            scenario_lab_history=scenario_lab_history_items,
            review_queue_actions=list(structured_service._review_queue_actions),
            review_artifact=review_artifact_item,
            review_artifact_history=review_artifact_history_items,
            training_card_candidates=training_card_items,
            active_training_card_routing=structured_service._active_training_card_routing,
            training_event_ledger=list(structured_service._training_event_ledger),
            evidence_queue=evidence_queue,
            planChangeCandidates=self.repository.list_plan_change_candidates(workspace_id),
        )
        snapshot.teaching_knowledge_catalog = self.teaching_knowledge_catalog(workspace_id, snapshot=snapshot)
        snapshot.memory_evidence = live_memory_snapshot_overlay(
            plan=plan,
            runtime=recovered,
            existing=recovered,
            memory_evidence=self._build_memory_evidence(snapshot, limit=5),
        )["memory_evidence"]
        # The persisted runtime is authoritative over any stale gated chrome.
        current_runtime = structured_service._workspace.get(PLAN_RUNTIME_KEY)
        current_step = str((current_runtime or {}).get("current_step") or "").strip()
        if current_step and isinstance(snapshot.workspace, dict):
            current_hop = snapshot.workspace.get("latest_training_next_hop")
            snapshot.workspace["latest_training_next_hop"] = {
                **(current_hop if isinstance(current_hop, dict) else {}),
                "title": current_step,
                "card_title": current_step,
            }
        self._persist_structured(workspace_id)
        return snapshot

    def list_teaching_assets(
        self,
        workspace_id: str,
        *,
        scope: str | None = None,
        limit: int = 8,
    ) -> list[TeachingKnowledgeAsset]:
        structured = self._structured_for(workspace_id)
        in_memory_assets = structured.list_teaching_assets(scope=scope, workspace_id=workspace_id)
        repository_assets = self.repository.list_teaching_assets(workspace_id=workspace_id, scope=scope)
        merged: dict[str, TeachingKnowledgeAsset] = {}
        for asset in [*repository_assets, *in_memory_assets]:
            if scope is not None and asset.scope != scope:
                continue
            if asset.scope in {"project", "personal"} and asset.workspace_id not in {"", workspace_id}:
                continue
            if asset.scope == "general" and asset.workspace_id not in {"__global__", workspace_id}:
                continue
            existing = merged.get(asset.id)
            if existing is None or (asset.updated_at or "") >= (existing.updated_at or ""):
                merged[asset.id] = asset
        ranked = sorted(
            merged.values(),
            key=lambda item: (
                0 if item.scope == "project" else 1 if item.scope == "personal" else 2,
                -self._teaching_asset_effectiveness_score(item),
                -(item.trust_score or 0.0),
                -(item.usage_count or 0),
                item.updated_at or "",
            ),
        )
        return ranked[:limit]

    def select_teaching_assets(
        self,
        workspace_id: str,
        *,
        scenario: str | None = None,
        focus_area: str | None = None,
        query: str | None = None,
        scope: str | None = None,
        limit: int = 4,
    ) -> list[TeachingKnowledgeAsset]:
        candidates = self.list_teaching_assets(
            workspace_id,
            scope=scope,
            limit=max(limit * 5, 20),
        )
        normalized_scenario = self._normalize_teaching_asset_scenario(scenario)
        normalized_focus = (focus_area or "").strip().lower()
        normalized_query = (query or "").strip().lower()
        focus_tokens = self._teaching_asset_tokens(" ".join([normalized_focus, normalized_query, normalized_scenario]))
        material_routing = self._material_routing_for_workspace(workspace_id)

        ranked = sorted(
            candidates,
            key=lambda item: self._teaching_asset_rank(
                item,
                workspace_id=workspace_id,
                scenario=normalized_scenario,
                normalized_focus=normalized_focus,
                normalized_query=normalized_query,
                focus_tokens=focus_tokens,
                material_routing=material_routing,
            ),
            reverse=True,
        )
        selected: list[TeachingKnowledgeAsset] = []
        seen_source_keys: set[str] = set()
        for asset in ranked:
            if not self._teaching_asset_is_relevant(
                asset,
                scenario=normalized_scenario,
                normalized_focus=normalized_focus,
                focus_tokens=focus_tokens,
            ):
                continue
            source_key = asset.source_key.strip().lower()
            if source_key and source_key in seen_source_keys:
                continue
            if source_key:
                seen_source_keys.add(source_key)
            selected.append(asset)
            if len(selected) >= limit:
                break
        if not selected and ranked:
            selected.append(ranked[0])
        return selected

    def recalled_coaching_memories(
        self,
        workspace_id: str,
        *,
        scenario: str | None = None,
        focus_area: str | None = None,
        query: str | None = None,
        exclude_asset_ids: list[str] | None = None,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        candidates = self.list_teaching_assets(
            workspace_id,
            limit=max(limit * 6, 24),
        )
        normalized_scenario = self._normalize_teaching_asset_scenario(scenario)
        normalized_focus = (focus_area or "").strip().lower()
        normalized_query = (query or "").strip().lower()
        focus_tokens = self._teaching_asset_tokens(
            " ".join([normalized_focus, normalized_query, normalized_scenario])
        )
        excluded_ids = {
            str(item).strip()
            for item in (exclude_asset_ids or [])
            if str(item).strip()
        }

        material_routing = self._material_routing_for_workspace(workspace_id)
        ranked = sorted(
            candidates,
            key=lambda item: self._teaching_asset_rank(
                item,
                workspace_id=workspace_id,
                scenario=normalized_scenario,
                normalized_focus=normalized_focus,
                normalized_query=normalized_query,
                focus_tokens=focus_tokens,
                material_routing=material_routing,
            ),
            reverse=True,
        )

        recalled: list[dict[str, Any]] = []
        seen_source_keys: set[str] = set()
        for asset in ranked:
            if asset.id in excluded_ids:
                continue
            if not self._teaching_asset_is_relevant(
                asset,
                scenario=normalized_scenario,
                normalized_focus=normalized_focus,
                focus_tokens=focus_tokens,
            ):
                continue
            signature = asset.source_key.strip().lower() or asset.id.strip().lower()
            if signature and signature in seen_source_keys:
                continue
            lesson = self._recalled_memory_lesson(asset)
            if not lesson:
                continue
            if signature:
                seen_source_keys.add(signature)
            evidence = self._recalled_memory_evidence(asset)
            match_reasons = self._recalled_memory_match_reasons(
                asset,
                scenario=normalized_scenario,
                normalized_focus=normalized_focus,
                normalized_query=normalized_query,
                focus_tokens=focus_tokens,
            )
            recalled.append(
                {
                    "id": asset.id,
                    "title": asset.title,
                    "kind": asset.kind,
                    "scope": asset.scope,
                    "focus_area": asset.focus_area,
                    "scenario": asset.scenario,
                    "summary": asset.summary,
                    "lesson": lesson,
                    "evidence": evidence,
                    "retrieval_hints": list(asset.retrieval_hints[:4]),
                    "trust_score": round(float(asset.trust_score or 0.0), 4),
                    "usage_count": int(asset.usage_count or 0),
                    "success_count": int(asset.success_count or 0),
                    "failure_count": int(asset.failure_count or 0),
                    "effectiveness_score": round(self._teaching_asset_effectiveness_score(asset), 4),
                    "last_effective_at": asset.last_effective_at,
                    "updated_at": asset.updated_at,
                    "match_reasons": match_reasons,
                }
            )
            if len(recalled) >= limit:
                break
        return recalled

    def teaching_asset_library(
        self,
        workspace_id: str,
        *,
        scope: str | None = None,
        scenario: str | None = None,
        focus_area: str | None = None,
        query: str | None = None,
        kind: str | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        assets = self.list_teaching_assets(workspace_id, scope=scope, limit=max(limit * 3, 24))
        if kind:
            assets = [asset for asset in assets if asset.kind == kind]
        if scenario or focus_area or query:
            assets = self.select_teaching_assets(
                workspace_id,
                scenario=scenario,
                focus_area=focus_area,
                query=query,
                scope=scope,
                limit=limit,
            )
            if kind:
                assets = [asset for asset in assets if asset.kind == kind]
        else:
            assets = assets[:limit]
        return {
            "total": len(assets),
            "scope": scope or "all",
            "scenario": scenario or "",
            "focus_area": focus_area or "",
            "kind": kind or "",
            "items": [self._asset_catalog_entry(asset) for asset in assets],
        }

    def mark_teaching_assets_used(
        self,
        workspace_id: str,
        asset_ids: list[str],
    ) -> list[TeachingKnowledgeAsset]:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        touched: list[TeachingKnowledgeAsset] = []
        for asset_id in {item.strip() for item in asset_ids if item and item.strip()}:
            loaded = self._load_teaching_asset_for_update(resolved_workspace_id, asset_id)
            if loaded is None:
                continue
            owner_workspace_id, asset = loaded
            updated = asset.model_copy(
                update={
                    "usage_count": int(asset.usage_count or 0) + 1,
                    "last_used_at": utc_now().isoformat(),
                }
            )
            if owner_workspace_id and owner_workspace_id != "__global__":
                structured = self._structured_for(owner_workspace_id)
                structured.upsert_teaching_asset(updated)
                self._persist_structured(owner_workspace_id)
            self.repository.save_teaching_asset(owner_workspace_id or resolved_workspace_id, updated)
            touched.append(updated)
        return touched

    def record_teaching_asset_effectiveness(
        self,
        workspace_id: str | None,
        *,
        asset_ids: list[str],
        outcome: str,
        scenario: str = "",
        effective_at: str | None = None,
    ) -> list[TeachingKnowledgeAsset]:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        normalized_outcome = outcome.strip().lower()
        if not normalized_outcome:
            return []
        normalized_scenario = self._normalize_teaching_asset_scenario(scenario)
        success_outcomes = {"code_landed", "tests_passed", "concept_answered_correctly"}
        failure_outcomes = {"evaluation", "repeated_error", "task_abandoned", "blocked"}
        touched: list[TeachingKnowledgeAsset] = []
        changed_at = effective_at or utc_now().isoformat()

        for asset_id in {item.strip() for item in asset_ids if item and item.strip()}:
            loaded = self._load_teaching_asset_for_update(resolved_workspace_id, asset_id)
            if loaded is None:
                continue
            owner_workspace_id, asset = loaded
            scenario_counts = {
                str(key): {
                    "success": int(value.get("success", 0)),
                    "failure": int(value.get("failure", 0)),
                }
                for key, value in asset.effectiveness_by_scenario.items()
                if isinstance(value, dict)
            }
            bucket = scenario_counts.setdefault(
                normalized_scenario or "general",
                {"success": 0, "failure": 0},
            )

            success_count = int(asset.success_count or 0)
            failure_count = int(asset.failure_count or 0)
            trust_score = float(asset.trust_score or 0.0)

            if normalized_outcome in success_outcomes:
                success_count += 1
                bucket["success"] += 1
                trust_score = min(1.0, trust_score + 0.06)
            elif normalized_outcome in failure_outcomes:
                failure_count += 1
                bucket["failure"] += 1
                trust_score = max(0.0, trust_score - 0.04)

            updated = asset.model_copy(
                update={
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "last_outcome": normalized_outcome,
                    "last_effective_at": changed_at,
                    "effectiveness_by_scenario": scenario_counts,
                    "trust_score": round(trust_score, 4),
                    "updated_at": changed_at,
                }
            )
            if owner_workspace_id and owner_workspace_id != "__global__":
                structured = self._structured_for(owner_workspace_id)
                structured.upsert_teaching_asset(updated)
                self._persist_structured(owner_workspace_id)
            self.repository.save_teaching_asset(owner_workspace_id or resolved_workspace_id, updated)
            touched.append(updated)
        return touched

    def record_teaching_asset(
        self,
        workspace_id: str | None,
        asset: TeachingKnowledgeAsset,
    ) -> TeachingKnowledgeAsset:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        return self._save_teaching_asset(resolved_workspace_id, asset)

    def record_teaching_assets_from_resource(
        self,
        workspace_id: str | None,
        resource: ResourceRecord,
    ) -> list[TeachingKnowledgeAsset]:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        saved_assets: list[TeachingKnowledgeAsset] = []
        if not resource.knowledge_fragments:
            return []
        blocking_quality_flags = {
            "duplicate",
            "source_conflict",
            "fetch_failed",
            "blocked_source",
            "network_disabled",
            "placeholder",
            "no_content",
        }
        if any(flag in blocking_quality_flags for flag in resource.quality_flags):
            return []
        if resource.trust_score < 0.35:
            return []
        fragments = [
            fragment
            for fragment in resource.knowledge_fragments[:3]
            if isinstance(fragment, dict) and str(fragment.get("snippet", "")).strip()
        ]
        if not fragments:
            return []
        focus_area = resource.name.strip() or resource.kind
        for index, fragment in enumerate(fragments):
            snippet = str(fragment.get("snippet", "")).strip()
            source = str(fragment.get("source", resource.canonical_source or resource.source)).strip()
            trust_score = float(fragment.get("trust_score", resource.trust_score) or resource.trust_score)
            kind = "concept_card" if index == 0 else "explanation_recipe" if index == 1 else "common_pitfall"
            asset = TeachingKnowledgeAsset(
                kind=kind,
                scope="project",
                workspace_id=resolved_workspace_id,
                title=f"{resource.name} · {kind.replace('_', ' ')}",
                summary=snippet,
                concept_card=snippet if kind == "concept_card" else "",
                explanation_recipe=snippet if kind == "explanation_recipe" else "",
                common_pitfall=snippet if kind == "common_pitfall" else "",
                why_it_matters=str(fragment.get("why_it_matters", "") or "").strip(),
                example=snippet,
                origin="resource",
                source_key=f"resource::{resource.id}::{kind}::{index}",
                source_ids=[resource.id],
                source_fragments=[source],
                evidence_snippets=[
                    snippet,
                    str(fragment.get("summary", "") or "").strip(),
                    str(fragment.get("why_it_matters", "") or "").strip(),
                ],
                retrieval_hints=[
                    focus_area,
                    resource.kind,
                    *resource.tags[:2],
                ],
                source_summary=str(fragment.get("summary", "") or snippet).strip(),
                source_quality_flags=[
                    str(flag).strip()
                    for flag in fragment.get("quality_flags", resource.quality_flags)
                    if str(flag).strip()
                ],
                source_freshness=_normalize_source_freshness(
                    fragment.get("freshness", resource.freshness) or resource.freshness
                ),
                source_retrieved_at=(
                    str(fragment.get("fetched_at", resource.fetched_at)).strip()
                    if fragment.get("fetched_at", resource.fetched_at)
                    else None
                ),
                tags=[resource.kind, *(resource.tags[:2])],
                focus_area=focus_area,
                scenario="resource_ingest",
                trust_score=trust_score,
            )
            saved_assets.append(self._save_teaching_asset(resolved_workspace_id, asset))
        return saved_assets

    def record_teaching_assets_from_understanding(
        self,
        workspace_id: str | None,
        understanding: WorkspaceUnderstandingSnapshot,
    ) -> list[TeachingKnowledgeAsset]:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        saved_assets: list[TeachingKnowledgeAsset] = []
        for index, opportunity in enumerate(understanding.training_opportunities[:2]):
            title = opportunity.strip()
            if not title:
                continue
            asset = TeachingKnowledgeAsset(
                kind="exercise_seed",
                scope="project",
                workspace_id=resolved_workspace_id,
                title=f"{title} · exercise seed",
                summary=title,
                exercise_seed=title,
                explanation_recipe=title,
                why_it_matters=understanding.repo_summary or understanding.resource_brief,
                example=understanding.entry_points[index] if index < len(understanding.entry_points) else "",
                anti_pattern=understanding.risk_zones[index] if index < len(understanding.risk_zones) else "",
                focus_area=title,
                scenario="workspace_understanding",
                origin="workspace_understanding",
                source_key=f"understanding::{resolved_workspace_id}::{index}::{title.lower()}",
                source_ids=[],
                source_fragments=list(understanding.entry_points[:2]),
                evidence_snippets=[
                    title,
                    understanding.repo_summary,
                    understanding.resource_brief,
                ],
                retrieval_hints=[
                    title,
                    "workspace",
                    *understanding.entry_points[:2],
                ],
                source_summary=understanding.repo_summary or understanding.resource_brief or title,
                tags=["workspace", "training-opportunity"],
                trust_score=0.65,
            )
            saved_assets.append(self._save_teaching_asset(resolved_workspace_id, asset))
        for index, risk in enumerate(understanding.risk_zones[:1]):
            title = risk.strip()
            if not title:
                continue
            asset = TeachingKnowledgeAsset(
                kind="common_pitfall",
                scope="project",
                workspace_id=resolved_workspace_id,
                title=f"{title} · pitfall",
                summary=title,
                common_pitfall=title,
                explanation_recipe=understanding.resource_brief or understanding.repo_summary,
                why_it_matters=understanding.resource_brief or understanding.repo_summary,
                focus_area=title,
                scenario="workspace_risk",
                origin="workspace_understanding",
                source_key=f"risk::{resolved_workspace_id}::{index}::{title.lower()}",
                source_ids=[],
                source_fragments=list(understanding.risk_zones[:2]),
                evidence_snippets=[
                    title,
                    understanding.resource_brief,
                ],
                retrieval_hints=[
                    title,
                    "workspace-risk",
                    *understanding.entry_points[:2],
                ],
                source_summary=understanding.resource_brief or understanding.repo_summary or title,
                tags=["workspace", "pitfall"],
                trust_score=0.62,
            )
            saved_assets.append(self._save_teaching_asset(resolved_workspace_id, asset))
        return saved_assets

    def record_teaching_assets_from_reflection(
        self,
        workspace_id: str | None,
        *,
        scenario: str,
        focus_area: str | None,
        summary: str,
        next_step: str,
        review_note: str | None = None,
    ) -> list[TeachingKnowledgeAsset]:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        cleaned_focus = (focus_area or "").strip()
        cleaned_summary = summary.strip()
        cleaned_next_step = next_step.strip()
        cleaned_review_note = (review_note or "").strip()
        if not (cleaned_focus or cleaned_summary or cleaned_next_step or cleaned_review_note):
            return []
        title_anchor = cleaned_focus or scenario or "coach-reflection"
        assets: list[TeachingKnowledgeAsset] = []
        scope = "general" if scenario in {"principle", "review"} and not cleaned_focus else "project"
        if cleaned_summary:
            assets.append(
                TeachingKnowledgeAsset(
                    kind="concept_card",
                    scope=scope,
                    workspace_id=resolved_workspace_id,
                    title=f"{title_anchor} · reflection",
                    summary=cleaned_summary,
                    concept_card=cleaned_summary,
                    explanation_recipe=cleaned_next_step or cleaned_summary,
                    why_it_matters=cleaned_review_note or cleaned_next_step or cleaned_summary,
                    focus_area=cleaned_focus or title_anchor,
                    scenario=scenario,
                    origin="reflection",
                    source_key=f"reflection::{resolved_workspace_id}::{scenario}::{cleaned_focus or title_anchor}".lower(),
                    source_ids=[],
                    source_fragments=[cleaned_next_step, cleaned_review_note] if cleaned_review_note else [cleaned_next_step],
                    evidence_snippets=[cleaned_summary, cleaned_next_step, cleaned_review_note],
                    retrieval_hints=[cleaned_focus or title_anchor, scenario, "reflection"],
                    source_summary=cleaned_review_note or cleaned_next_step or cleaned_summary,
                    tags=["reflection", scenario],
                    trust_score=0.55,
                )
            )
        if cleaned_review_note:
            assets.append(
                TeachingKnowledgeAsset(
                    kind="common_pitfall",
                    scope="project",
                    workspace_id=resolved_workspace_id,
                    title=f"{title_anchor} · pitfall",
                    summary=cleaned_review_note,
                    common_pitfall=cleaned_review_note,
                    explanation_recipe=cleaned_next_step or cleaned_summary,
                    why_it_matters=cleaned_summary or cleaned_next_step or cleaned_review_note,
                    focus_area=cleaned_focus or title_anchor,
                    scenario=scenario,
                    origin="reflection",
                    source_key=f"reflection-pitfall::{resolved_workspace_id}::{scenario}::{cleaned_focus or title_anchor}".lower(),
                    source_ids=[],
                    source_fragments=[cleaned_review_note],
                    evidence_snippets=[cleaned_review_note, cleaned_summary, cleaned_next_step],
                    retrieval_hints=[cleaned_focus or title_anchor, scenario, "pitfall"],
                    source_summary=cleaned_review_note,
                    tags=["reflection", "pitfall"],
                    trust_score=0.6,
                )
            )
        return [self._save_teaching_asset(resolved_workspace_id, asset) for asset in assets]

    def record_teaching_assets_from_learning_outcome(
        self,
        workspace_id: str | None,
        *,
        scenario: str,
        focus_area: str | None,
        outcome: str,
        summary: str,
        next_step: str,
        checks: list[str] | None = None,
        verified_result: str | None = None,
        blocked_reason: str | None = None,
    ) -> list[TeachingKnowledgeAsset]:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        cleaned_focus = (focus_area or "").strip()
        cleaned_summary = summary.strip()
        cleaned_next_step = next_step.strip()
        cleaned_verified = (verified_result or "").strip()
        cleaned_blocker = (blocked_reason or "").strip()
        normalized_outcome = outcome.strip().lower()
        title_anchor = cleaned_focus or scenario or normalized_outcome or "learning-outcome"
        assets: list[TeachingKnowledgeAsset] = []
        success_outcomes = {"code_landed", "tests_passed", "concept_answered_correctly"}

        if normalized_outcome in success_outcomes and (cleaned_verified or cleaned_summary):
            assets.append(
                TeachingKnowledgeAsset(
                    kind="implementation_pattern",
                    scope="project",
                    workspace_id=resolved_workspace_id,
                    title=f"{title_anchor} · verified pattern",
                    summary=cleaned_verified or cleaned_summary,
                    implementation_pattern=cleaned_verified or cleaned_summary,
                    explanation_recipe=cleaned_next_step or cleaned_verified or cleaned_summary,
                    why_it_matters=(
                        "This pattern already produced a verified result and should be reused before widening scope."
                    ),
                    example="; ".join(item.strip() for item in (checks or []) if item and item.strip()) or cleaned_verified,
                    anti_pattern=cleaned_blocker,
                    focus_area=cleaned_focus or title_anchor,
                    scenario=scenario,
                    origin="learning_outcome",
                    source_key=f"learning-pattern::{resolved_workspace_id}::{scenario}::{title_anchor}".lower(),
                    source_ids=[],
                    source_fragments=[cleaned_summary, cleaned_next_step] if cleaned_next_step else [cleaned_summary],
                    evidence_snippets=[
                        cleaned_verified or cleaned_summary,
                        "; ".join(item.strip() for item in (checks or []) if item and item.strip()),
                        cleaned_blocker,
                    ],
                    retrieval_hints=[cleaned_focus or title_anchor, scenario, normalized_outcome, "verified-pattern"],
                    source_summary=cleaned_verified or cleaned_summary,
                    tags=["learning-outcome", "verified-pattern", scenario or normalized_outcome],
                    trust_score=0.74 if cleaned_verified else 0.68,
                )
            )

        if normalized_outcome == "concept_answered_correctly" and (cleaned_summary or cleaned_next_step):
            assets.append(
                TeachingKnowledgeAsset(
                    kind="explanation_recipe",
                    scope="personal",
                    workspace_id=resolved_workspace_id,
                    title=f"{title_anchor} · explanation recipe",
                    summary=cleaned_summary or cleaned_next_step,
                    explanation_recipe=cleaned_summary or cleaned_next_step,
                    why_it_matters="This explanation worked well enough for the learner to explain the concept back.",
                    example=cleaned_next_step or cleaned_summary,
                    focus_area=cleaned_focus or title_anchor,
                    scenario=scenario,
                    origin="learning_outcome",
                    source_key=f"learning-explanation::{resolved_workspace_id}::{scenario}::{title_anchor}".lower(),
                    source_ids=[],
                    source_fragments=[cleaned_summary, cleaned_next_step] if cleaned_next_step else [cleaned_summary],
                    evidence_snippets=[cleaned_summary, cleaned_next_step],
                    retrieval_hints=[cleaned_focus or title_anchor, scenario, normalized_outcome, "explanation"],
                    source_summary=cleaned_summary or cleaned_next_step,
                    tags=["learning-outcome", "explanation", scenario or normalized_outcome],
                    trust_score=0.7,
                )
            )

        return [self._save_teaching_asset(resolved_workspace_id, asset) for asset in assets]

    def profile(self, workspace_id: str) -> UserProfile | None:
        return self.repository.get_profile(workspace_id)

    def weaknesses(self, workspace_id: str) -> list[str]:
        return self.snapshot(workspace_id).weaknesses

    def reviews(self, workspace_id: str) -> list[str]:
        snapshot = self.snapshot(workspace_id)
        if snapshot.due_reviews:
            return [
                f"{item.concept}: {item.reason}"
                + (f" (due {item.due_at})" if item.due_at else "")
                for item in snapshot.due_reviews[:4]
            ]
        return snapshot.reflections or [
            "Spec adherence before code style",
            "Boundary conditions before convenience helpers",
            "Reflection recorded after each pass",
        ]

    def save_workspace_understanding(
        self,
        workspace_id: str | None,
        understanding: WorkspaceUnderstandingSnapshot,
    ) -> None:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved_workspace_id)
        structured.update_workspace(
            workspace_id=resolved_workspace_id,
            workspace_understanding=understanding.model_dump(),
        )
        self.record_teaching_assets_from_understanding(resolved_workspace_id, understanding)
        self._persist_structured(resolved_workspace_id)

    def record_profile(self, workspace_id: str, profile: UserProfile) -> None:
        self.repository.save_profile(workspace_id, profile)
        self._structured_for(workspace_id).update_profile(**profile.model_dump())
        self._persist_structured(workspace_id)

    def structured_for_workspace(self, workspace_id: str) -> StructuredMemoryService:
        return self._structured_for(workspace_id)

    def record_user_feedback(self, *, workspace_id: str, **feedback: Any) -> UserFeedbackRecord:
        record = self._structured_for(workspace_id).record_user_feedback(**feedback)
        self._persist_structured(workspace_id)
        return record

    def update_workspace_state(self, workspace_id: str, **workspace_patch: Any) -> dict[str, Any]:
        structured = self._structured_for(workspace_id)
        updated = structured.update_workspace(**workspace_patch)
        self._persist_structured(workspace_id)
        return updated

    def persist_turn_context_pressure(
        self,
        workspace_id: str,
        *,
        current_task: Any = None,
        affect_state: Any = None,
        learner_state: Any = None,
        teaching_decision: Any = None,
        tone_decision: Any = None,
        adaptation_guide: Any = None,
        project_sources: Any = None,
        principle_notes: Any = None,
        coach_focus: Any = None,
        coach_turn: Any = None,
        next_step_hint: Any = None,
        coaching_adaptation: Any = None,
    ) -> dict[str, Any]:
        """Persist the turn's current task, affect, and teaching chrome onto workspace latest_* facts."""

        patch: dict[str, Any] = {}
        task_record = normalize_latest_current_task(current_task, workspace_id, adopt_scope=True)
        affect_record = normalize_latest_affect_state(affect_state, workspace_id, adopt_scope=True)
        learner_record = normalize_latest_learner_state(learner_state, workspace_id, adopt_scope=True)
        teaching_record = normalize_latest_teaching_decision(
            teaching_decision,
            workspace_id,
            adopt_scope=True,
        )
        tone_record = normalize_latest_tone_decision(tone_decision, workspace_id, adopt_scope=True)
        adaptation_record = normalize_latest_adaptation_guide(
            adaptation_guide,
            workspace_id,
            adopt_scope=True,
        )
        sources_record = normalize_latest_project_sources(
            project_sources,
            workspace_id,
            adopt_scope=True,
        )
        principle_record = normalize_latest_principle_notes(
            principle_notes,
            workspace_id,
            adopt_scope=True,
        )
        coach_focus_record = normalize_latest_coach_focus(
            coach_focus,
            workspace_id,
            adopt_scope=True,
        )
        coach_turn_record = normalize_latest_coach_turn(
            coach_turn,
            workspace_id,
            adopt_scope=True,
        )
        hint_record = normalize_latest_next_step_hint(
            next_step_hint,
            workspace_id,
            adopt_scope=True,
        )
        adaptation_profile_record = normalize_latest_coaching_adaptation(
            coaching_adaptation,
            workspace_id,
            adopt_scope=True,
        )
        if task_record is not None:
            patch[CURRENT_TASK_KEY] = task_record
        if affect_record is not None:
            patch[AFFECT_STATE_KEY] = affect_record
            patch["task_urgency"] = affect_record.get("urgency_level") or "medium"
        if learner_record is not None:
            patch[LEARNER_STATE_KEY] = learner_record
        if teaching_record is not None:
            patch[TEACHING_DECISION_KEY] = teaching_record
        if tone_record is not None:
            patch[TONE_DECISION_KEY] = tone_record
        if adaptation_record is not None:
            patch[ADAPTATION_GUIDE_KEY] = adaptation_record
        if sources_record is not None:
            patch[PROJECT_SOURCES_KEY] = sources_record
        if principle_record is not None:
            patch[PRINCIPLE_NOTES_KEY] = principle_record
        if coach_focus_record is not None:
            patch[COACH_FOCUS_KEY] = coach_focus_record
        if coach_turn_record is not None:
            patch[COACH_TURN_KEY] = coach_turn_record
        if hint_record is not None:
            patch[NEXT_STEP_HINT_KEY] = hint_record
        if adaptation_profile_record is not None:
            patch[COACHING_ADAPTATION_KEY] = adaptation_profile_record
        if not patch:
            return dict(self._structured_for(workspace_id)._workspace)
        return self.update_workspace_state(workspace_id, **patch)

    def persist_plan_runtime_recovery(
        self,
        workspace_id: str,
        *,
        plan: Any | None = None,
        plan_runtime: dict[str, Any] | None = None,
        evidence_binding: str = "",
        request_id: str = "",
        replace_evidence_binding: bool = False,
    ) -> dict[str, Any] | None:
        structured = self._structured_for(workspace_id)
        record = build_plan_runtime_recovery(
            plan=plan,
            plan_runtime=plan_runtime,
            existing=structured._workspace.get(PLAN_RUNTIME_KEY)
            if isinstance(structured._workspace.get(PLAN_RUNTIME_KEY), dict)
            else None,
            evidence_binding=evidence_binding,
            request_id=request_id,
            workspace_id=workspace_id,
            replace_evidence_binding=replace_evidence_binding,
        )
        if record is None:
            return None
        record = stamp_workspace_scope(record, workspace_id)
        if record is None:
            return None
        structured.update_workspace(**{PLAN_RUNTIME_KEY: record})
        self._persist_structured(workspace_id)
        return record

    def bind_explicit_generated_plan(
        self,
        workspace_id: str,
        plan: Any,
    ) -> dict[str, Any] | None:
        """User-visible generate makes this plan live. Do not text-match leftover into it."""

        _leftover_plan, leftover_runtime, _leftover_task = self._leftover_persist_context(workspace_id)
        existing = leftover_runtime if isinstance(leftover_runtime, dict) else {}
        structured = self._structured_for(workspace_id)
        record = bind_explicit_generated_plan_runtime(
            plan=plan,
            existing=existing,
            workspace_id=workspace_id,
            evidence_binding=str(existing.get("evidence_binding") or existing.get("evidenceBinding") or ""),
            request_id=str(
                existing.get("request_id")
                or existing.get("requestId")
                or getattr(plan, "id", "")
                or getattr(plan, "plan_id", "")
                or ""
            ),
        )
        if record is None:
            return None
        record = stamp_workspace_scope(record, workspace_id)
        if record is None:
            return None
        patch: dict[str, Any] = {PLAN_RUNTIME_KEY: record}
        turn = structured._workspace.get(COACH_TURN_KEY)
        if not isinstance(turn, dict):
            turn = structured._workspace.get("latestCoachTurn")
        if isinstance(turn, dict):
            cleaned = dict(turn)
            cleaned["suggested_actions"] = []
            cleaned.pop("suggestedActions", None)
            patch[COACH_TURN_KEY] = cleaned
        leftover_plans = []
        list_plans = getattr(self.repository, "list_plans", None)
        if callable(list_plans):
            leftover_plans = list_plans(workspace_id)
        competing_labels = leftover_bound_plan_competing_identity_labels(
            plan=plan,
            runtime=record,
            existing=record,
            card_titles=[
                str(getattr(card, "title", "") or "")
                for card in self.get_cards(workspace_id)
            ],
            leftover_plans=leftover_plans,
        )
        leftover_training = bound_plan_leftover_training_live_identity_updates(
            workspace_id=workspace_id,
            generated_step=str(record.get("current_step") or ""),
            workspace=structured._workspace if isinstance(structured._workspace, dict) else {},
            competing_labels=competing_labels,
        )
        patch.update(leftover_training)
        structured.update_workspace(**patch)
        self._persist_structured(workspace_id)
        return record

    def persist_plan_runtime_resume(
        self,
        workspace_id: str,
        *,
        accepted: dict[str, Any] | None,
        request_id: str,
        reply_facts: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        structured = self._structured_for(workspace_id)
        existing = structured._workspace.get(PLAN_RUNTIME_KEY)
        record = build_plan_runtime_resume(
            existing=existing,
            accepted=accepted,
            request_id=request_id,
            workspace_id=workspace_id,
            reply_facts=reply_facts,
        )
        if record is None:
            return None
        record = stamp_workspace_scope(record, workspace_id)
        if record is None:
            return None
        structured.update_workspace(**{PLAN_RUNTIME_KEY: record})
        self._persist_structured(workspace_id)
        self.enqueue_waiting_verify_evidence(workspace_id, record)
        latest = structured._workspace.get(PLAN_RUNTIME_KEY)
        return latest if isinstance(latest, dict) else record

    def _enqueue_waiting_verify_payload(
        self,
        workspace_id: str,
        runtime: dict[str, Any] | None,
        payload: dict[str, Any],
    ) -> EvidenceItem | None:
        concepts = payload.get("concepts")
        current_step = str(concepts[0] if isinstance(concepts, list) and concepts else "").strip()
        if not current_step:
            return None
        existing = next(
            (
                item
                for item in self.evidence_queue(workspace_id).pending
                if item.source == payload["source"]
                and item.summary == payload["summary"]
                and current_step in item.concepts
            ),
            None,
        )
        item = existing or self.enqueue_evidence(
            workspace_id,
            EvidenceItem(
                summary=payload["summary"],
                source=payload["source"],
                concepts=list(payload["concepts"]),
                outcome=payload["outcome"],
                target_plan_stage_id=payload["target_plan_stage_id"],
            ),
            verified=False,
        )
        if runtime is not None and not str(runtime.get("evidence_binding") or "").strip():
            runtime["evidence_binding"] = item.id
            structured = self._structured_for(workspace_id)
            structured.update_workspace(**{PLAN_RUNTIME_KEY: runtime})
            self._persist_structured(workspace_id)
        return item

    def enqueue_waiting_verify_evidence(
        self,
        workspace_id: str,
        runtime: dict[str, Any] | None,
    ) -> EvidenceItem | None:
        payload = build_waiting_verify_evidence(runtime=runtime, workspace_id=workspace_id)
        if payload is None:
            return None
        return self._enqueue_waiting_verify_payload(workspace_id, runtime, payload)

    def enqueue_waiting_composer_evidence(
        self,
        workspace_id: str,
        submitted_text: str,
    ) -> EvidenceItem | None:
        structured = self._structured_for(workspace_id)
        existing = structured._workspace.get(PLAN_RUNTIME_KEY)
        current = normalize_plan_runtime_recovery(existing)
        payload = build_waiting_composer_evidence(
            runtime=current,
            workspace_id=workspace_id,
            submitted_text=submitted_text,
            pending_count=len(self.evidence_queue(workspace_id).pending),
        )
        if payload is None or current is None:
            return None
        item = self._enqueue_waiting_verify_payload(workspace_id, current, payload)
        if item is None:
            return None
        stamped = build_plan_runtime_recovery(
            plan=None,
            plan_runtime={
                "current_step": current.get("current_step"),
                "current_stage_id": current.get("current_stage_id"),
                "blocked_reason": current.get("blocked_reason"),
                "why_now": current.get("why_now"),
                "verify_method": [payload["summary"]],
                "next_after_current": current.get("next_after_current") or "",
                "next_why_now": current.get("next_why_now") or "",
                "next_blocked_reason": current.get("next_blocked_reason") or "",
                "next_verify_method": list(current.get("next_verify_method") or []),
                "resume_state": "waiting",
            },
            existing=current,
            evidence_binding=item.id,
            request_id=str(current.get("request_id") or item.id),
            workspace_id=workspace_id,
        )
        stamped = stamp_workspace_scope(stamped, workspace_id)
        if stamped is None:
            return item
        structured.update_workspace(**{PLAN_RUNTIME_KEY: stamped})
        self._persist_structured(workspace_id)
        return item

    def persist_plan_runtime_advance_after_adopt(
        self,
        workspace_id: str,
        evidence: Any,
        *,
        request_id: str = "",
    ) -> dict[str, Any] | None:
        structured = self._structured_for(workspace_id)
        existing = structured._workspace.get(PLAN_RUNTIME_KEY)
        # Capture live id before advance mutates runtime overlay.
        live_id = self.live_selected_training_card_id(workspace_id)
        record = build_plan_runtime_advance_after_adopt(
            existing=existing,
            evidence=evidence,
            request_id=request_id or str(getattr(evidence, "id", "") or "").strip(),
            workspace_id=workspace_id,
        )
        if record is None:
            return None
        record = self._stamp_live_selected_card_id_on_advance(
            workspace_id,
            record,
            live_id=live_id,
        )
        record = stamp_workspace_scope(record, workspace_id)
        if record is None:
            return None
        structured.update_workspace(**{PLAN_RUNTIME_KEY: record})
        self._refresh_training_next_challenge_after_runtime_advance(workspace_id, record)
        self._persist_structured(workspace_id)
        return record

    def persist_plan_runtime_advance_after_verify(
        self,
        workspace_id: str,
        plan: Any,
        *,
        request_id: str = "",
    ) -> dict[str, Any] | None:
        """Keep recovered plan_runtime on the same live plan_id after evaluator verify."""

        structured = self._structured_for(workspace_id)
        existing = structured._workspace.get(PLAN_RUNTIME_KEY)
        live_id = self.live_selected_training_card_id(workspace_id)
        record = build_plan_runtime_advance_after_verify(
            plan=plan,
            existing=existing,
            workspace_id=workspace_id,
            request_id=request_id,
        )
        if record is None:
            return None
        record = self._stamp_live_selected_card_id_on_advance(
            workspace_id,
            record,
            live_id=live_id,
        )
        record = stamp_workspace_scope(record, workspace_id)
        if record is None:
            return None
        structured.update_workspace(**{PLAN_RUNTIME_KEY: record})
        self._refresh_training_next_challenge_after_runtime_advance(workspace_id, record)
        self._persist_structured(workspace_id)
        return record

    def _stamp_live_selected_card_id_on_advance(
        self,
        workspace_id: str,
        record: dict[str, Any],
        *,
        live_id: str | None = None,
    ) -> dict[str, Any]:
        """Fail-closed: stamp only live selected_card_id; never leftover title invent."""

        resolved = (
            live_id
            if live_id is not None
            else self.live_selected_training_card_id(workspace_id)
        )
        stamped = dict(record)
        # Preserve live id under every advance builder; clear leftover painted ids.
        stamped["selected_card_id"] = (resolved or None)
        return stamped

    def persist_verify_plan_advance_stamp(
        self,
        workspace_id: str,
        advance: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Persist explainable verify advance onto live plan_runtime so hydrate can resurface it."""
        payload = dict(advance) if isinstance(advance, dict) else {}
        if not payload:
            return None
        structured = self._structured_for(workspace_id)
        existing = structured._workspace.get(PLAN_RUNTIME_KEY)
        if not isinstance(existing, dict) or not existing:
            return None
        plan_id = str(payload.get("plan_id") or payload.get("planId") or "").strip()
        existing_plan_id = str(existing.get("plan_id") or existing.get("planId") or "").strip()
        if plan_id and existing_plan_id and plan_id != existing_plan_id:
            return None
        record = dict(existing)
        record["verify_plan_advance"] = {
            "advanced": bool(payload.get("advanced")),
            "what": str(payload.get("what") or "").strip(),
            "why": str(payload.get("why") or "").strip(),
            "next": str(payload.get("next") or "").strip(),
            "plan_id": plan_id or existing_plan_id or None,
        }
        record = stamp_workspace_scope(record, workspace_id)
        if record is None:
            return None
        structured.update_workspace(**{PLAN_RUNTIME_KEY: record})
        self._persist_structured(workspace_id)
        return record["verify_plan_advance"]

    def _training_handoff_owner_card_id(self, workspace_id: str) -> str:
        """Return the open handoff owner id when it maps to a stored, actionable card.

        The handoff owner is the one card whose Learn..Return flow is in flight,
        so it stays live even after a later mint moved the selection elsewhere.
        Terminal (completed return) handoffs and finished cards never count.
        """

        structured = self._structured_for(workspace_id)
        payload = structured._workspace.get("latest_training_handoff")
        if not isinstance(payload, dict):
            return ""
        owner_id = str(payload.get("card_id") or payload.get("candidate_id") or "").strip()
        if not owner_id:
            return ""
        learning_phase = str(payload.get("learning_phase") or "").strip().lower()
        handoff_status = str(payload.get("status") or "").strip().lower()
        if learning_phase == "return" and handoff_status == "completed":
            return ""
        card = self.get_card(workspace_id, owner_id)
        if card is None:
            return ""
        card_status = str(getattr(card, "status", "") or "").strip().lower()
        if card_status in {"implemented", "completed", "archived"}:
            return ""
        return owner_id

    def live_selected_training_card_id(self, workspace_id: str) -> str:
        """Return the live selected training card id, or empty when none is live.

        Leftover stored card / title / current_step text never counts as live.
        Same identity rule as plans: live only when recovered runtime still
        carries a matching card id (not title match).
        Guard exception: the current ``latest_training_handoff`` owner may pass
        live checks (reflect/return/grade/activate) so its handoff can finish;
        unrelated leftover cards stay guarded.
        """
        structured = self._structured_for(workspace_id)
        workspace = structured._workspace if isinstance(structured._workspace, dict) else {}
        selected = str(
            workspace.get("selected_card_id") or workspace.get("selectedCardId") or ""
        ).strip()
        routing_selected = ""
        if structured._active_training_card_routing is not None:
            routing_selected = str(
                structured._active_training_card_routing.selected_card_id or ""
            ).strip()
        candidate = selected or routing_selected
        handoff_owner = self._training_handoff_owner_card_id(workspace_id)
        if not candidate:
            # No selection painted: the open handoff owner is the live card.
            return handoff_owner
        card = self.get_card(workspace_id, candidate)
        if card is None:
            return handoff_owner
        leftover_plan, leftover_runtime, _leftover_task = self._leftover_persist_context(
            workspace_id
        )
        if leftover_runtime:
            carried = str(
                leftover_runtime.get("selected_card_id")
                or leftover_runtime.get("selectedCardId")
                or ""
            ).strip()
            # Live formal plan may still bind via workspace selection when runtime
            # has not yet stamped selected_card_id; leftover-not-live never does.
            if not carried and leftover_formal_plan_is_live_for_fill(
                plan=leftover_plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            ):
                carried = candidate
            if not formal_card_is_live_runtime_identity(
                card=card,
                card_id=candidate,
                selected_card_id=carried,
            ):
                # Handoff-owner exception: the owner card stays live even when
                # the recovered runtime carries another (or no) card id.
                return handoff_owner if handoff_owner == candidate else ""
            return candidate
        # No recovered runtime overlay: workspace selected id matching stored card is live.
        return candidate

    def schedule_live_training_card_fsrs_after_verify(
        self,
        workspace_id: str,
        *,
        training_card_id: str,
        passed: bool,
    ) -> dict[str, Any] | None:
        """FSRS schedule for the live selected card only. Never mint. No global promote."""
        from ..training.fsrs_scheduler import (
            TrainingRating,
            card_state_from_payload,
            card_state_to_payload,
            create_training_scheduler,
        )

        cleaned_card_id = str(training_card_id or "").strip()
        if not cleaned_card_id:
            return None
        live_id = self.live_selected_training_card_id(workspace_id)
        # Fail-closed: leftover-not-live / missing selectedCardId must not FSRS.
        if not live_id or live_id != cleaned_card_id:
            return None
        card = self.get_card(workspace_id, cleaned_card_id)
        if card is None:
            return None

        structured = self._structured_for(workspace_id)
        workspace = structured._workspace if isinstance(structured._workspace, dict) else {}
        raw_states = workspace.get("latest_training_fsrs_states") or workspace.get(
            "latestTrainingFsrsStates"
        )
        state_map: dict[str, Any] = dict(raw_states) if isinstance(raw_states, dict) else {}
        # Fail-closed: never invent sibling cards — only touch this card_id.
        other_ids = [key for key in state_map if str(key).strip() and str(key).strip() != cleaned_card_id]
        _ = other_ids  # preserved as-is; we do not mint or wipe siblings

        scheduler = create_training_scheduler(deck_id=f"ws:{workspace_id}")
        existing_payload = state_map.get(cleaned_card_id)
        if isinstance(existing_payload, dict):
            existing_state = card_state_from_payload(existing_payload)
            if existing_state is not None:
                scheduler.load_card_states([existing_state])
        if scheduler.get_card_state(cleaned_card_id) is None:
            concept = str(
                getattr(card, "target_skill", "")
                or getattr(card, "focus_area", "")
                or cleaned_card_id
            ).strip()
            created = scheduler.create_card(
                cleaned_card_id,
                concept or cleaned_card_id,
                card_type=str(getattr(card, "card_type", "") or "practice"),
                focus_area=str(getattr(card, "focus_area", "") or "").strip() or None,
            )
            created.project_scope = "current_project"

        rating = TrainingRating.GOOD if passed else TrainingRating.AGAIN
        result = scheduler.process_review(cleaned_card_id, rating)
        updated_state = scheduler.get_card_state(cleaned_card_id)
        if updated_state is None:
            return None
        payload = card_state_to_payload(updated_state)
        previous = existing_payload if isinstance(existing_payload, dict) else {}
        try:
            success_streak = int(previous.get("success_streak") or 0)
        except (TypeError, ValueError):
            success_streak = 0
        try:
            fail_streak = int(previous.get("fail_streak") or 0)
        except (TypeError, ValueError):
            fail_streak = 0
        if passed:
            success_streak += 1
            fail_streak = 0
        else:
            fail_streak += 1
            success_streak = 0
        payload["success_streak"] = success_streak
        payload["fail_streak"] = fail_streak
        ladder = ("easy", "medium", "hard")
        current_difficulty = str(getattr(card, "difficulty", "") or "medium").strip().lower()
        if current_difficulty not in ladder:
            current_difficulty = "medium"
        index = ladder.index(current_difficulty)
        if passed and success_streak >= 2 and index < len(ladder) - 1:
            index += 1
        elif (not passed) and fail_streak >= 2 and index > 0:
            index -= 1
        next_difficulty = ladder[index]
        payload["pedagogy_difficulty"] = next_difficulty
        state_map[cleaned_card_id] = payload
        structured.update_workspace(latest_training_fsrs_states=state_map)
        review_schedule = dict(getattr(card, "review_schedule", None) or {})
        review_schedule.update(
            {
                "card_id": cleaned_card_id,
                "fsrs_difficulty": payload.get("difficulty"),
                "pedagogy_difficulty": next_difficulty,
                "reps": result.reps,
                "lapses": result.lapses,
                "success_streak": success_streak,
                "fail_streak": fail_streak,
            }
        )
        self.upsert_card(
            workspace_id,
            card.model_copy(
                update={
                    "difficulty": next_difficulty,
                    "review_schedule": review_schedule,
                }
            ),
        )
        self._persist_structured(workspace_id)
        return {
            "card_id": cleaned_card_id,
            "rating": rating.name.lower(),
            "interval_days": result.new_interval,
            "next_due": result.next_due.isoformat() if result.next_due else None,
            "stability": result.new_stability,
            "reps": result.reps,
            "lapses": result.lapses,
            "difficulty": next_difficulty,
            "fsrs_difficulty": payload.get("difficulty"),
            "global_promoted": False,
            "minted_card": False,
        }

    def _refresh_training_next_challenge_after_runtime_advance(
        self,
        workspace_id: str,
        runtime: dict[str, Any] | None,
    ) -> None:
        """Training chrome follows recovered current_step, not leftover formal titles."""

        if not isinstance(runtime, dict):
            return
        current_step = str(runtime.get("current_step") or "").strip()
        persist_chrome = self._live_training_persist_chrome(
            workspace_id,
            card_title=current_step,
        )
        # A recovered runtime step is authoritative; cleanup must not blank it.
        live_title = current_step or persist_chrome["selected_card_title"]
        structured = self._structured_for(workspace_id)
        handoff = structured._workspace.get("latest_training_handoff")
        next_hop = structured._workspace.get("latest_training_next_hop")
        recovered_why = str(runtime.get("why_now") or "").strip()
        updates: dict[str, Any] = {
            "selected_card_title": live_title,
            TRAINING_CHROME_KEY: stamp_workspace_scope(
                {"selected_card_title": live_title},
                workspace_id,
            ),
        }
        if isinstance(handoff, dict):
            updates["latest_training_handoff"] = stamp_workspace_scope(
                {**handoff, "card_title": live_title},
                workspace_id,
            )
        if current_step:
            hop = {
                **(next_hop if isinstance(next_hop, dict) else {}),
                "title": live_title,
                "card_title": live_title,
            }
            leftover_why = str(hop.get("why_now") or "").strip()
            if recovered_why:
                hop["why_now"] = recovered_why
            elif leftover_why:
                leftover_plan, leftover_runtime, leftover_task = self._leftover_persist_context(
                    workspace_id
                )
                live_plan = formal_plan_is_live_runtime_identity(
                    plan=leftover_plan,
                    runtime=leftover_runtime,
                    existing=leftover_runtime,
                )
                leftover_labels = leftover_formal_training_labels(
                    plan=leftover_plan,
                    task_title=leftover_task,
                    live_plan=live_plan,
                    live_task=False,
                )
                if leftover_why in leftover_labels:
                    hop["why_now"] = ""
            updates["latest_training_next_hop"] = stamp_workspace_scope(hop, workspace_id)
        elif isinstance(next_hop, dict):
            cleared_hop = dict(next_hop)
            cleared_hop["title"] = ""
            cleared_hop["card_title"] = ""
            cleared_hop.pop("cardTitle", None)
            updates["latest_training_next_hop"] = stamp_workspace_scope(
                cleared_hop,
                workspace_id,
            )
        structured.update_workspace(**updates)
        if current_step:
            # Runtime advance is authoritative for the next training hop, even
            # when leftover-plan cleanup would otherwise blank its title.
            structured.update_workspace(
                latest_training_next_hop=stamp_workspace_scope(hop, workspace_id),
            )

    def _sync_live_evidence_binding(self, workspace_id: str) -> dict[str, Any] | None:
        structured = self._structured_for(workspace_id)
        existing = structured._workspace.get(PLAN_RUNTIME_KEY)
        current = normalize_plan_runtime_recovery(existing)
        if current is None or not is_current_for_workspace(current, workspace_id):
            return current
        pending_ids = [item.id for item in self.evidence_queue(workspace_id).pending]
        live = live_evidence_binding(
            binding=str(current.get("evidence_binding") or ""),
            pending_ids=pending_ids,
            recovered=True,
            current_step=str(current.get("current_step") or ""),
        )
        stored = str(current.get("evidence_binding") or "").strip()
        if live == stored:
            return current
        record = build_plan_runtime_recovery(
            plan=None,
            plan_runtime=current,
            existing=current,
            evidence_binding=live,
            replace_evidence_binding=True,
            request_id=str(current.get("request_id") or ""),
            workspace_id=workspace_id,
        )
        record = stamp_workspace_scope(record, workspace_id)
        if record is None:
            return current
        structured.update_workspace(**{PLAN_RUNTIME_KEY: record})
        self._persist_structured(workspace_id)
        return record

    def persist_provider_capability_recovery(
        self,
        workspace_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        stamped = {
            **payload,
            "workspace_id": workspace_id,
            "provider_profile_id": (
                payload.get("provider_profile_id")
                or payload.get("providerProfileId")
                or payload.get("profile_id")
                or payload.get("profileId")
                or ""
            ),
        }
        record = normalize_provider_capability_recovery(stamped)
        if record is None:
            return None
        record = stamp_workspace_scope(record, workspace_id)
        if record is None:
            return None
        existing = normalize_provider_capability_recovery(
            self._structured_for(workspace_id)._workspace.get(PROVIDER_CAPABILITY_KEY)
        )
        if existing:
            record["revision"] = int(existing.get("revision") or 0) + 1
        self.update_workspace_state(workspace_id, **{PROVIDER_CAPABILITY_KEY: record})
        return record

    def persist_streaming_checkpoint(
        self,
        workspace_id: str,
        *,
        request_id: str,
        phase: str,
        checkpoint_id: str = "",
        session_id: str = "",
        stream_message_id: str = "",
        stop_reason: str = "",
        error: str = "",
        provider_profile_id: str = "",
        provider_name: str = "",
        base_url: str = "",
        model: str = "",
    ) -> dict[str, Any] | None:
        structured = self._structured_for(workspace_id)
        record = build_streaming_checkpoint(
            request_id=request_id,
            phase=phase,
            existing=structured._workspace.get(STREAMING_CHECKPOINT_KEY)
            if isinstance(structured._workspace.get(STREAMING_CHECKPOINT_KEY), dict)
            else None,
            checkpoint_id=checkpoint_id,
            session_id=session_id,
            stream_message_id=stream_message_id,
            stop_reason=stop_reason,
            error=error,
            workspace_id=workspace_id,
            provider_profile_id=provider_profile_id,
            provider_name=provider_name,
            base_url=base_url,
            model=model,
        )
        if record is None:
            return None
        structured.update_workspace(**{STREAMING_CHECKPOINT_KEY: record})
        self._persist_structured(workspace_id)
        return record

    def recover_workspace_facts(self, workspace_id: str) -> dict[str, Any]:
        structured = self._structured_for(workspace_id)
        streaming = recover_streaming_checkpoint_after_restart(
            structured._workspace.get(STREAMING_CHECKPOINT_KEY)
        )
        if streaming and streaming != structured._workspace.get(STREAMING_CHECKPOINT_KEY):
            structured.update_workspace(**{STREAMING_CHECKPOINT_KEY: streaming})
            self._persist_structured(workspace_id)
        workspace = structured._workspace if isinstance(structured._workspace, dict) else {}
        chrome = apply_training_chrome_scope(workspace, workspace_id)
        return {
            PLAN_RUNTIME_KEY: stamp_workspace_scope(
                normalize_plan_runtime_recovery(workspace.get(PLAN_RUNTIME_KEY)),
                workspace_id,
            ),
            PROVIDER_CAPABILITY_KEY: stamp_workspace_scope(
                normalize_provider_capability_recovery(
                    workspace.get(PROVIDER_CAPABILITY_KEY)
                ),
                workspace_id,
            ),
            STREAMING_CHECKPOINT_KEY: stamp_workspace_scope(
                normalize_streaming_checkpoint(
                    workspace.get(STREAMING_CHECKPOINT_KEY)
                ),
                workspace_id,
            ),
            TRAINING_CHROME_KEY: chrome.get(TRAINING_CHROME_KEY),
            "latest_training_handoff": chrome.get("latest_training_handoff"),
            "latest_training_next_hop": chrome.get("latest_training_next_hop"),
            "selected_card_title": chrome.get("selected_card_title") or "",
            CURRENT_TASK_KEY: select_latest_current_task(
                workspace.get(CURRENT_TASK_KEY)
                or workspace.get("latestCurrentTask")
                or workspace.get("current_task")
                or workspace.get("currentTask"),
                workspace_id,
            ),
            COACHING_FOCUS_KEY: select_latest_coaching_focus(
                workspace.get(COACHING_FOCUS_KEY) or workspace.get("latestCoachingFocus"),
                workspace_id,
            ),
            EVALUATION_KEY: select_latest_evaluation(
                workspace.get(EVALUATION_KEY) or workspace.get("latestEvaluation"),
                workspace_id,
            ),
            LEARNER_STATE_KEY: select_latest_learner_state(
                workspace.get(LEARNER_STATE_KEY) or workspace.get("latestLearnerState"),
                workspace_id,
            ),
            TEACHING_DECISION_KEY: select_latest_teaching_decision(
                workspace.get(TEACHING_DECISION_KEY) or workspace.get("latestTeachingDecision"),
                workspace_id,
            ),
            AFFECT_STATE_KEY: select_latest_affect_state(
                workspace.get(AFFECT_STATE_KEY) or workspace.get("latestAffectState"),
                workspace_id,
            ),
            TONE_DECISION_KEY: select_latest_tone_decision(
                workspace.get(TONE_DECISION_KEY) or workspace.get("latestToneDecision"),
                workspace_id,
            ),
            ADAPTATION_GUIDE_KEY: select_latest_adaptation_guide(
                workspace.get(ADAPTATION_GUIDE_KEY) or workspace.get("latestAdaptationGuide"),
                workspace_id,
            ),
            PROJECT_SOURCES_KEY: select_latest_project_sources(
                workspace.get(PROJECT_SOURCES_KEY) or workspace.get("latestProjectSources"),
                workspace_id,
            ),
            PRINCIPLE_NOTES_KEY: select_latest_principle_notes(
                workspace.get(PRINCIPLE_NOTES_KEY) or workspace.get("latestPrincipleNotes"),
                workspace_id,
            ),
            COACH_FOCUS_KEY: select_latest_coach_focus(
                workspace.get(COACH_FOCUS_KEY) or workspace.get("latestCoachFocus"),
                workspace_id,
            ),
            COACH_TURN_KEY: select_latest_coach_turn(
                workspace.get(COACH_TURN_KEY) or workspace.get("latestCoachTurn"),
                workspace_id,
            ),
            NEXT_STEP_HINT_KEY: select_latest_next_step_hint(
                workspace.get(NEXT_STEP_HINT_KEY) or workspace.get("latestNextStepHint"),
                workspace_id,
            ),
            COACHING_ADAPTATION_KEY: select_latest_coaching_adaptation(
                workspace.get(COACHING_ADAPTATION_KEY) or workspace.get("latestCoachingAdaptation"),
                workspace_id,
            ),
        }

    def recover_workspace_facts_for_scope(
        self,
        workspace_id: str,
        *,
        provider_profile_id: str = "",
        provider_name: str = "",
        base_url: str = "",
        model: str = "",
    ) -> dict[str, Any]:
        recovered = self.recover_workspace_facts(workspace_id)
        return {
            PLAN_RUNTIME_KEY: select_plan_runtime_for_scope(
                recovered.get(PLAN_RUNTIME_KEY),
                workspace_id,
            ),
            PROVIDER_CAPABILITY_KEY: select_provider_capability_for_scope(
                recovered.get(PROVIDER_CAPABILITY_KEY),
                workspace_id=workspace_id,
                provider_profile_id=provider_profile_id,
                provider_name=provider_name,
                base_url=base_url,
                model=model,
            ),
            STREAMING_CHECKPOINT_KEY: select_streaming_checkpoint_for_scope(
                recovered.get(STREAMING_CHECKPOINT_KEY),
                workspace_id=workspace_id,
                provider_profile_id=provider_profile_id,
                provider_name=provider_name,
                base_url=base_url,
                model=model,
            ),
            TRAINING_CHROME_KEY: select_training_chrome_for_scope(
                recovered.get(TRAINING_CHROME_KEY),
                workspace_id,
            ),
            "latest_training_handoff": select_training_record_for_scope(
                recovered.get("latest_training_handoff"),
                workspace_id,
            ),
            "latest_training_next_hop": select_training_record_for_scope(
                recovered.get("latest_training_next_hop"),
                workspace_id,
            ),
            "selected_card_title": (
                (select_training_chrome_for_scope(recovered.get(TRAINING_CHROME_KEY), workspace_id) or {}).get(
                    "selected_card_title"
                )
                or ""
            ),
            CURRENT_TASK_KEY: select_latest_current_task(
                recovered.get(CURRENT_TASK_KEY),
                workspace_id,
            ),
            COACHING_FOCUS_KEY: select_latest_coaching_focus(
                recovered.get(COACHING_FOCUS_KEY),
                workspace_id,
            ),
            EVALUATION_KEY: select_latest_evaluation(
                recovered.get(EVALUATION_KEY),
                workspace_id,
            ),
            LEARNER_STATE_KEY: select_latest_learner_state(
                recovered.get(LEARNER_STATE_KEY),
                workspace_id,
            ),
            TEACHING_DECISION_KEY: select_latest_teaching_decision(
                recovered.get(TEACHING_DECISION_KEY),
                workspace_id,
            ),
            AFFECT_STATE_KEY: select_latest_affect_state(
                recovered.get(AFFECT_STATE_KEY),
                workspace_id,
            ),
            TONE_DECISION_KEY: select_latest_tone_decision(
                recovered.get(TONE_DECISION_KEY),
                workspace_id,
            ),
            ADAPTATION_GUIDE_KEY: select_latest_adaptation_guide(
                recovered.get(ADAPTATION_GUIDE_KEY),
                workspace_id,
            ),
            PROJECT_SOURCES_KEY: select_latest_project_sources(
                recovered.get(PROJECT_SOURCES_KEY),
                workspace_id,
            ),
            PRINCIPLE_NOTES_KEY: select_latest_principle_notes(
                recovered.get(PRINCIPLE_NOTES_KEY),
                workspace_id,
            ),
            COACH_FOCUS_KEY: select_latest_coach_focus(
                recovered.get(COACH_FOCUS_KEY),
                workspace_id,
            ),
            COACH_TURN_KEY: select_latest_coach_turn(
                recovered.get(COACH_TURN_KEY),
                workspace_id,
            ),
            NEXT_STEP_HINT_KEY: select_latest_next_step_hint(
                recovered.get(NEXT_STEP_HINT_KEY),
                workspace_id,
            ),
            COACHING_ADAPTATION_KEY: select_latest_coaching_adaptation(
                recovered.get(COACHING_ADAPTATION_KEY),
                workspace_id,
            ),
        }

    def clear_workspace_memory(self, workspace_id: str) -> None:
        self._structured_by_workspace.pop(workspace_id, None)

    def reset_workspace_training_state(self, workspace_id: str) -> dict[str, Any]:
        structured = self._structured_for(workspace_id)
        structured._training_cards = {}
        structured._card_ledger = []
        structured._active_training_card_routing = None
        structured._evidence_items = {}
        structured._dependency_skill_map_history = []
        structured._flash_deck = None
        structured._recent_flash_attempts = []
        structured._theory_drill = None
        structured._theory_drill_history = []
        structured._scenario_lab = None
        structured._scenario_lab_history = []
        structured._review_queue_actions = []
        structured._review_artifact = None
        structured._review_artifact_history = []
        structured._training_event_ledger = []
        structured.update_workspace(
            selected_card_id="",
            selected_card_status="",
            latest_training_submode="",
            latest_training_next_hop={},
            latest_flashcard_recovery_mode="",
        )
        self._persist_structured(workspace_id)
        self._card_ledger = [entry for entry in self._card_ledger if entry.get("workspace_id") != workspace_id]
        return {"workspace_id": workspace_id, "ok": True}

    def _build_flash_deck_snapshot(self, structured: StructuredMemoryService) -> FlashDeckSnapshot:
        language = _workspace_language(structured._workspace)

        def t(en: str, zh: str) -> str:
            return _localized_memory_text(en, zh, language)

        cards: list[TrainingCardCandidateSnapshot] = []
        for dependency_key, skill_map in structured._dependency_skill_maps.items():
            dependency_name = skill_map.dependency_name or dependency_key
            for index, item in enumerate(skill_map.items):
                layer_label = {
                    "api": t("API", "API"),
                    "scenario": t("Minimum scenario", "最小场景"),
                    "parameter": t("Parameter semantics", "参数语义"),
                    "return_value": t("Return value semantics", "返回值语义"),
                    "misuse": t("Misuse check", "误用检查"),
                    "concept": t("Dependency selection", "依赖选择"),
                    "verification": t("Verification method", "验证方法"),
                    "transfer": t("Cross-context transfer", "跨场景迁移"),
                }.get(item.layer, t("skill", "技能"))
                question = {
                    "parameter": t(
                        f"What does the parameter passed through {item.related_api or dependency_name} represent?",
                        f"经由 {item.related_api or dependency_name} 传入的这个参数到底表示什么？",
                    ),
                    "return_value": t(
                        f"What value comes back from {item.related_api or dependency_name} into the caller?",
                        f"{item.related_api or dependency_name} 返回给调用方的值是什么？",
                    ),
                    "misuse": t(
                        f"What is the most common misuse to avoid around {item.related_api or dependency_name}?",
                        f"围绕 {item.related_api or dependency_name} 最常见、需要避免的误用是什么？",
                    ),
                    "verification": t(
                        f"What is the smallest verification step for {dependency_name} here?",
                        f"这里要验证 {dependency_name}，最小的一步是什么？",
                    ),
                    "transfer": t(
                        f"How would you transfer this {dependency_name} judgment into a second project slice?",
                        f"如果换到第二个项目切片里，你会怎样迁移这次对 {dependency_name} 的判断？",
                    ),
                    "concept": t(
                        f"Why is {dependency_name} the right dependency choice for this boundary?",
                        f"为什么在这个边界上，{dependency_name} 是合适的依赖选择？",
                    ),
                    "scenario": t(
                        f"What is the minimum scenario that proves {dependency_name} belongs here?",
                        f"什么样的最小场景可以证明 {dependency_name} 应该放在这里？",
                    ),
                    "api": t(
                        f"When does {item.related_api or dependency_name} belong in the current slice?",
                        f"在当前切片里，{item.related_api or dependency_name} 应该在什么情况下出现？",
                    ),
                }.get(
                    item.layer,
                    t(
                        f"What should you verify about {dependency_name} next?",
                        f"下一步你最该验证 {dependency_name} 的哪一点？",
                    ),
                )
                expected_answer = {
                    "parameter": t(
                        "State the parameter meaning, the boundary it crosses, and why that input matters.",
                        "说明这个参数的含义、它穿过的边界，以及为什么这个输入重要。",
                    ),
                    "return_value": t(
                        "State what value returns into the caller and how that value proves the dependency behavior.",
                        "说明返回给调用方的值是什么，以及这个值如何证明依赖行为成立。",
                    ),
                    "misuse": t(
                        "Name the misuse, the boundary it breaks, and the guardrail that keeps the slice minimal.",
                        "指出误用方式、它会破坏哪条边界，以及保持切片最小的保护规则是什么。",
                    ),
                    "verification": t(
                        "Name one concrete verification method tied to the smallest changed boundary.",
                        "说出一个和最小改动边界直接对应的具体验证方法。",
                    ),
                    "transfer": t(
                        "Name the same judgment, the new context, and the proof that it still holds.",
                        "说出同样的判断、迁移后的新语境，以及它依然成立的证据。",
                    ),
                    "concept": t(
                        "Explain the concrete pressure, the dependency choice, and why a simpler boundary is not enough.",
                        "解释具体压力、依赖选择，以及为什么更简单的边界还不够。",
                    ),
                    "scenario": t(
                        "Describe the minimum scenario, the boundary, and the proof you expect back.",
                        "描述最小场景、目标边界，以及你期待看到的验证结果。",
                    ),
                    "api": t(
                        "Explain when the API belongs and what concrete pressure justifies it.",
                        "解释这个 API 何时该出现，以及是什么具体压力让它合理。",
                    ),
                }.get(
                    item.layer,
                    t(
                        "Give the smallest truthful explanation and one concrete proof.",
                        "给出最小但真实的解释，再补一个具体证据。",
                    ),
                )
                card = TrainingCardCandidateSnapshot(
                    card_id=f"skill-{dependency_key}-{item.layer}-{index}",
                    card_type="flash",
                    title=t(
                        f"Flash: {dependency_name} {item.layer or 'skill'}",
                        f"闪记卡：{dependency_name} {layer_label}",
                    ),
                    status="active",
                    created_from="dependency_mastery",
                    why_now=skill_map.priority_summary,
                    focus_area=skill_map.priority_summary,
                    target_skill=dependency_name,
                    knowledge_type=item.knowledge_type,
                    question=question,
                    answer_mode="text",
                    expected_answer=expected_answer,
                    hint_ladder=list(
                        item.hint_ladder
                        or [
                            t("State the boundary first.", "先把边界说清楚。"),
                            t("Then name the proof.", "再把证据说出来。"),
                        ]
                    ),
                    common_mistakes=[t("Widening scope before stating the boundary.", "还没说明边界，就先把范围放大了。")],
                    feedback={
                        "correct": t("Good. The dependency explanation stayed grounded.", "很好，这次对依赖的解释是贴着真实边界的。"),
                        "incorrect": t(
                            "Return to the smallest boundary and explain the meaning before coding.",
                            "先回到最小边界，把含义说清楚，再决定要不要动手写代码。",
                        ),
                    },
                    dependency_key=dependency_key,
                    dependency_layer=item.layer,
                    question_style=item.question_style,
                    verification_method=item.verification_method,
                )
                cards.append(card)
                structured._training_cards[card.card_id] = card
            fallback_card = TrainingCardCandidateSnapshot(
                card_id=f"skill-{dependency_key}-fallback",
                card_type="flash",
                title=t(
                    f"Flash: {dependency_name} scenario judgment",
                    f"闪记卡：{dependency_name} 场景判断",
                ),
                status="active",
                created_from="dependency_mastery",
                why_now=skill_map.priority_summary,
                focus_area=skill_map.priority_summary,
                target_skill=dependency_name,
                knowledge_type="scenario_judgment",
                question=t(
                    f"What is the smallest scenario that proves {dependency_name} belongs here?",
                    f"什么样的最小场景可以证明 {dependency_name} 应该放在这里？",
                ),
                answer_mode="text",
                expected_answer=t(
                    "State the minimum scenario, the dependency boundary, and one proof the behavior is correct.",
                    "先说最小场景、依赖边界，再补一个证明行为正确的证据。",
                ),
                hint_ladder=[
                    t("Name the scenario before the abstraction.", "先讲场景，再讲抽象。"),
                    t("Keep the slice to one boundary and one proof.", "只保留一条边界和一个证据。"),
                ],
                common_mistakes=[t("Naming the dependency without naming the real pressure first.", "先说依赖名字，却没有先说真实压力。")],
                feedback={
                    "correct": t("Good. The scenario stayed concrete.", "很好，这个场景保持得很具体。"),
                    "incorrect": t(
                        "Return to the concrete pressure before naming the dependency again.",
                        "先回到具体压力，再重新判断这项依赖。",
                    ),
                },
                dependency_key=dependency_key,
                dependency_layer="",
                question_style="scenario_answer",
                verification_method=t("Prove the same judgment in one minimum scenario.", "用一个最小场景证明这次判断依然成立。"),
            )
            cards.append(fallback_card)
            structured._training_cards[fallback_card.card_id] = fallback_card
        return FlashDeckSnapshot(
            id=f"flash-{uuid4().hex[:10]}",
            title=t("Dependency mastery flash deck", "dependency mastery 闪记卡组"),
            focus_area=t("dependency mastery", "dependency mastery"),
            cards=cards,
        )

    def _build_theory_drill_snapshot(self, structured: StructuredMemoryService) -> TheoryDrillSnapshot | None:
        language = _workspace_language(structured._workspace)

        def t(en: str, zh: str) -> str:
            return _localized_memory_text(en, zh, language)

        if not structured._dependency_skill_maps:
            return None
        questions: list[TheoryDrillQuestion] = []
        dependency_keys = list(structured._dependency_skill_maps.keys())
        for dependency_key, skill_map in structured._dependency_skill_maps.items():
            for index, item in enumerate(skill_map.items[:6]):
                questions.append(
                    TheoryDrillQuestion(
                        id=f"theory-{dependency_key}-{item.layer}-{index}",
                        prompt=f"{item.label}: {item.verification_method or skill_map.priority_summary}",
                        choices=[],
                        answer=t(
                            "Give the smallest grounded explanation and one concrete proof.",
                            "给出最小、贴着真实边界的解释，再补一个具体证据。",
                        ),
                        explanation=skill_map.priority_summary,
                        dependency_key=dependency_key,
                        dependency_layer=item.layer,
                        knowledge_type=item.knowledge_type,
                        question_style=item.question_style,
                    )
                )
        if not questions:
            return None
        return TheoryDrillSnapshot(
            id=f"theory-{uuid4().hex[:10]}",
            title=t("Theory drill: dependency mastery", "理论演练：dependency mastery"),
            focus_area=t("dependency mastery", "dependency mastery"),
            status="ready",
            summary=t("Rebuild the dependency judgment before widening scope.", "先重新建立对 dependency 的判断，再扩大范围。"),
            success_signal=t("The learner can explain the dependency boundary without bluffing.", "学习者能不靠猜测地讲清 dependency 边界。"),
            return_with=t("Return with the smallest explanation and one concrete proof.", "带着最小解释和一个具体证据回来。"),
            questions=questions,
            dependency_keys=dependency_keys,
        )

    _LEARNING_PHASE_ORDER = {
        "learn": 0,
        "try": 1,
        "verify": 2,
        "reflect": 3,
        "return": 4,
    }

    @staticmethod
    def _normalize_learning_phase(value: object | None) -> str:
        phase = str(value or "").strip().lower()
        return phase if phase in MemoryService._LEARNING_PHASE_ORDER else "learn"

    @classmethod
    def _learning_phase_for_card_status(cls, status: str, current_phase: str | None = None) -> str:
        current = cls._normalize_learning_phase(current_phase) if current_phase else "learn"
        if status in {"candidate", "needs_primer"}:
            return "learn"
        if status in {"active", "answered"}:
            return "try"
        if status in {"implemented", "completed"}:
            return "verify"
        if status == "reviewed":
            return "reflect"
        if status in {"fed_back", "archived"}:
            return "return"
        return current

    def _apply_card_learning_phase(
        self,
        workspace_id: str,
        card: TrainingCardCandidateSnapshot,
        phase: str,
    ) -> TrainingCardCandidateSnapshot:
        next_phase = self._normalize_learning_phase(phase)
        if card.learning_phase == next_phase:
            return card
        updated = card.model_copy(
            update={"learning_phase": next_phase, "updated_at": utc_now().isoformat()}
        )
        structured = self._structured_for(workspace_id)
        structured._training_cards[updated.card_id] = updated
        return updated

    def upsert_card(
        self,
        workspace_id: str,
        card: TrainingCardCandidateSnapshot,
    ) -> TrainingCardCandidateSnapshot:
        structured = self._structured_for(workspace_id)
        normalized = card.model_copy(
            update={
                "card_id": card.card_id or str(uuid4()),
                "learning_phase": self._normalize_learning_phase(
                    getattr(card, "learning_phase", None) or self._learning_phase_for_card_status(card.status)
                ),
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._training_cards[normalized.card_id] = normalized
        self._record_training_event(
            structured,
            event_type="training_card_upserted",
            payload={
                "card_candidate_id": normalized.card_id,
                "card_candidate_type": normalized.card_type,
                "card_candidate_title": normalized.title,
            },
        )
        self._persist_structured(workspace_id)
        return normalized

    def get_card(
        self,
        workspace_id: str,
        card_id: str,
    ) -> TrainingCardCandidateSnapshot | None:
        structured = self._structured_for(workspace_id)
        card = structured._training_cards.get(card_id)
        if card is not None:
            return card
        if structured._flash_deck is not None:
            return next((item for item in structured._flash_deck.cards if item.card_id == card_id), None)
        return None

    def get_cards(self, workspace_id: str) -> list[TrainingCardCandidateSnapshot]:
        structured = self._structured_for(workspace_id)
        priority = {
            "needs_primer": 0,
            "active": 1,
            "candidate": 2,
            "answered": 3,
            "implemented": 4,
            "reviewed": 5,
            "fed_back": 6,
            "blocked": 7,
            "skipped": 8,
            "archived": 9,
        }
        cards = [
            item
            for item in structured._training_cards.values()
            if item.status not in {"archived"}
        ]
        return sorted(
            cards,
            key=lambda item: (priority.get(item.status, 9), item.updated_at, item.card_id),
        )

    def persist_active_card_selection(
        self,
        workspace_id: str,
        selection: ActiveCardSelectionResult,
    ) -> ActiveCardSelectionResult:
        structured = self._structured_for(workspace_id)
        selected_card = selection.selected_card
        selected_card_scenario_pack = (
            getattr(selected_card, "scenario_pack", "") or ""
        ).strip()
        if selected_card is not None:
            existing = self.get_card(workspace_id, selected_card.card_id)
            if existing is None:
                existing = self.upsert_card(workspace_id, selected_card)
            target_status = (
                "needs_primer"
                if (selected_card.status == "needs_primer" or existing.status == "needs_primer")
                else "active"
            )
            if existing.status != target_status:
                transition = self.transition_card_status(
                    workspace_id,
                    existing.card_id,
                    target_status,
                    reason="Persist active training card selection.",
                )
                selected_card = transition.card
            else:
                selected_card = existing
            selected_card_id = selected_card.card_id
            for other_card_id, other_card in list(structured._training_cards.items()):
                if other_card_id == selected_card_id or other_card.status != "active":
                    continue
                structured._training_cards[other_card_id] = other_card.model_copy(
                    update={
                        "status": "candidate",
                        "updated_at": utc_now().isoformat(),
                    }
                )
                self._record_training_event(
                    structured,
                    event_type="training_card_deactivated",
                    payload={
                        "card_candidate_id": other_card_id,
                        "previous_status": "active",
                        "new_status": "candidate",
                        "reason": "Single-card-first active routing selected another card.",
                    },
                )
            if selected_card_scenario_pack and not getattr(selected_card, "scenario_pack", "").strip():
                selected_card = selected_card.model_copy(
                    update={"scenario_pack": selected_card_scenario_pack}
                )
                structured._training_cards[selected_card.card_id] = selected_card
            selection = selection.model_copy(update={"selected_card": selected_card, "selected_card_id": selected_card.card_id})
        structured._active_training_card_routing = selection
        existing_next_hop = structured._workspace.get("latest_training_next_hop")
        next_hop = {
            **(existing_next_hop if isinstance(existing_next_hop, dict) else {}),
            "selected_card_id": selection.selected_card_id,
            "scenario_pack": selected_card_scenario_pack,
            "next_after_completion": selection.next_after_completion,
            "fallback_action": selection.fallback_action,
        }
        workspace_patch = {
            "selected_card_id": selection.selected_card_id or "",
            "selected_card_status": selection.selected_card.status if selection.selected_card else "",
            "latest_training_next_hop": next_hop,
        }
        if selection.selected_card is not None:
            workspace_patch["latest_training_submode"] = selection.selected_card.card_type
        # Explicit bind: stamp card id onto recovered plan runtime (like /plan/generate
        # stamps plan_id) so leftover title/current_step cannot fake live identity.
        existing_runtime = structured._workspace.get(PLAN_RUNTIME_KEY)
        if not isinstance(existing_runtime, dict):
            existing_runtime = structured._workspace.get("latestPlanRuntime")
        if isinstance(existing_runtime, dict):
            runtime_record = dict(existing_runtime)
            runtime_record["selected_card_id"] = selection.selected_card_id or ""
            scoped = stamp_workspace_scope(runtime_record, workspace_id)
            if scoped is not None:
                workspace_patch[PLAN_RUNTIME_KEY] = scoped
        structured.update_workspace(**workspace_patch)
        self._record_training_event(
            structured,
            event_type="active_training_card_persisted",
            payload={
                "selected_card_id": selection.selected_card_id or "",
                "why_this_card": selection.why_this_card,
                "candidate_count": selection.candidate_count,
                "eligible_count": selection.eligible_count,
            },
        )
        self._persist_structured(workspace_id)
        return selection

    def transition_card_status(
        self,
        workspace_id: str,
        card_id: str,
        new_status: str,
        reason: str = "",
        *,
        verified_by_evaluator: bool = False,
    ) -> CardStatusTransitionResponse:
        structured = self._structured_for(workspace_id)
        card = self.get_card(workspace_id, card_id)
        if card is None:
            raise ValueError(f"Card {card_id!r} not found")
        allowed = {
            "candidate": {"active", "needs_primer", "skipped", "blocked"},
            "active": {"needs_primer", "answered", "implemented", "completed", "skipped", "blocked"},
            "needs_primer": {"active", "skipped", "blocked"},
            "answered": {"reviewed"},
            "implemented": {"reviewed", "completed"},
            "completed": {"reviewed"},
            "reviewed": {"fed_back", "archived"},
            "fed_back": {"archived"},
            "blocked": {"active"},
            "skipped": {"active"},
            "archived": set(),
        }
        if new_status not in allowed.get(card.status, set()):
            raise ValueError(f"Invalid transition from {card.status} to {new_status}")
        if new_status in {"implemented", "completed"} and not verified_by_evaluator:
            raise ValueError(
                "A training card can only be marked implemented or completed after server-side verification."
            )
        if card.card_type == "practice" and new_status in {"reviewed", "fed_back", "archived"}:
            has_verified_evidence = any(
                evidence.verified and evidence.source_card_id == card_id
                for evidence in structured._evidence_items.values()
            )
            if not has_verified_evidence:
                raise ValueError(
                    "A practice card needs server-side evidence before it can be reviewed, fed back, or archived."
                )
        updated = card.model_copy(
            update={
                "status": new_status,
                "learning_phase": self._learning_phase_for_card_status(
                    new_status,
                    getattr(card, "learning_phase", None),
                ),
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._training_cards[card_id] = updated
        ledger_entry = {
            "card_id": card_id,
            "workspace_id": workspace_id,
            "previous_status": card.status,
            "new_status": new_status,
            "reason": reason,
            "transitioned_at": utc_now().isoformat(),
        }
        structured._card_ledger.append(ledger_entry)
        self._card_ledger.append(dict(ledger_entry))
        self._record_training_event(
            structured,
            event_type="training_card_status_changed",
            payload={
                "candidate_id": card_id,
                "candidate_status": new_status,
                "candidate_status_reason": reason,
            },
        )
        self._persist_structured(workspace_id)
        return CardStatusTransitionResponse(card=updated, ledger_entry=ledger_entry)

    def enqueue_evidence(
        self,
        workspace_id: str,
        item: EvidenceItem,
        *,
        verified: bool = False,
        verification_source: str = "",
    ) -> EvidenceItem:
        structured = self._structured_for(workspace_id)
        normalized = item.model_copy(
            update={
                "id": item.id or f"ev-{uuid4().hex[:10]}",
                "workspace_id": workspace_id,
                "timestamp": item.timestamp or utc_now().isoformat(),
                "verified": verified,
                "verification_source": verification_source.strip() if verified else "",
            }
        )
        if not str(normalized.target_plan_stage_id or "").strip():
            # Auto-bind unscoped evidence to the recovered runtime's current step
            # so it stays live pending instead of draining into history.
            recovered = normalize_plan_runtime_recovery(structured._workspace.get(PLAN_RUNTIME_KEY))
            if recovered is not None and is_current_for_workspace(recovered, workspace_id):
                current_step = str(recovered.get("current_step") or "").strip()
                if current_step:
                    normalized = normalized.model_copy(update={"target_plan_stage_id": current_step})
        structured._evidence_items[normalized.id] = normalized
        try:
            self._persist_structured(workspace_id)
        except Exception:
            structured._evidence_items.pop(normalized.id, None)
            raise
        return normalized

    def evidence_queue(self, workspace_id: str) -> EvidenceQueueSnapshot:
        structured = self._structured_for(workspace_id)
        items = list(structured._evidence_items.values())
        pending = [
            item
            for item in items
            if not item.adopted and not item.rejected_at and not item.deferred_at
        ]
        deferred = [
            item
            for item in items
            if not item.adopted and not item.rejected_at and bool(item.deferred_at)
        ]
        adopted = [item for item in items if item.adopted]
        rejected = [item for item in items if item.rejected_at]
        recovered = normalize_plan_runtime_recovery(structured._workspace.get(PLAN_RUNTIME_KEY))
        recovered_runtime = bool(recovered) and is_current_for_workspace(recovered, workspace_id)
        pending = scope_evidence_items_to_workspace(pending, workspace_id)
        deferred = scope_evidence_items_to_workspace(deferred, workspace_id)
        adopted = scope_evidence_items_to_workspace(adopted, workspace_id)
        rejected = scope_evidence_items_to_workspace(rejected, workspace_id)
        scoped = scope_evidence_queue_to_runtime_step(
            pending=pending,
            deferred=deferred,
            adopted=adopted,
            rejected=rejected,
            current_step=str((recovered or {}).get("current_step") or ""),
            recovered=recovered_runtime,
        )
        return EvidenceQueueSnapshot(
            pending=list(scoped["pending"]),
            deferred=list(scoped["deferred"]),
            adopted=list(scoped["adopted"]),
            rejected=list(scoped["rejected"]),
            history=list(scoped["history"]),
            unscoped=list(scoped.get("unscoped", [])),
            total_count=len(items),
        )

    def _adopted_return_transfer_concepts(
        self,
        workspace_id: str,
        evidence: EvidenceItem,
    ) -> list[str]:
        leftover_plan, leftover_runtime, leftover_task = self._leftover_persist_context(workspace_id)
        recovered_step = str(
            (leftover_runtime or {}).get("current_step")
            or (leftover_runtime or {}).get("currentStep")
            or ""
        ).strip()
        live_plan = formal_plan_is_live_runtime_identity(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            current_step=recovered_step,
        )
        leftover_labels = leftover_formal_training_labels(
            plan=leftover_plan,
            task_title=leftover_task,
            live_plan=live_plan,
            live_task=False,
        )
        concepts: list[str] = []
        for item in evidence.concepts:
            text = str(item or "").strip()
            if text and text not in leftover_labels and text not in concepts:
                concepts.append(text)
        return concepts

    def _record_adopted_return_transfer(
        self,
        workspace_id: str,
        evidence: EvidenceItem,
    ) -> None:
        """Project-scoped until a second distinct workspace proves the same skill. Never invent a plan."""

        if evidence.source != "training_handoff_return":
            return
        if not evidence.verified or evidence.outcome != "pass":
            return
        if not (evidence.summary or "").strip():
            return
        concepts = self._adopted_return_transfer_concepts(workspace_id, evidence)
        if not concepts:
            return
        concept = concepts[0]
        self._record_verified_skill_scene(
            workspace_id=workspace_id,
            concept=concept,
            scene_key=resolve_skill_scene_key(scenario=evidence.source),
        )
        structured = self._structured_for(workspace_id)
        structured.remember_learning_outcome(
            concept,
            "tests_passed",
            summary=evidence.summary,
            action_type="training_handoff_return",
            verified_by_evaluator=True,
            verified_result=evidence.summary,
        )
        should_promote = self._should_promote_verified_outcome_to_global(
            concepts=[concept],
            workspace_id=workspace_id,
        )
        self._persist_transfer_skill_state(
            workspace_id=workspace_id,
            concept=concept,
            language=str(structured._workspace.get("response_language") or ""),
            schedule_review=should_promote,
        )
        if should_promote and (evidence.summary or "").strip():
            scenes = self._verified_scenes_for_concept(concept)
            self._record_global_verified_outcome(
                [concept],
                "tests_passed",
                workspace_id=workspace_id,
                scene_count=len(scenes),
            )

    def adopt_evidence(self, workspace_id: str, evidence_id: str) -> EvidenceAdoptResponse:
        structured = self._structured_for(workspace_id)
        evidence = structured._evidence_items.get(evidence_id)
        if evidence is None or evidence.adopted or evidence.rejected_at:
            raise HTTPException(status_code=404, detail="Evidence item not found.")
        adopted = evidence.model_copy(
            update={
                "adopted": True,
                "adopted_at": utc_now().isoformat(),
                **attest_waiting_verify_on_adopt(evidence),
            }
        )
        structured._evidence_items[evidence_id] = adopted

        plan_updated = False
        plan_change_summary = ""
        plan = self.repository.get_latest_plan(workspace_id)
        recovered_runtime = select_plan_runtime_for_scope(
            structured._workspace.get(PLAN_RUNTIME_KEY),
            workspace_id,
        )
        leftover_plan_is_live = formal_plan_is_live_runtime_identity(
            plan=plan,
            runtime=recovered_runtime,
            existing=recovered_runtime,
        )
        if (
            leftover_plan_is_live
            and plan
            and not plan.frozen
            and adopted.outcome == "pass"
            and adopted.verified
        ):
            active_index = next(
                (
                    index
                    for index, stage in enumerate(plan.stages)
                    if stage.id == (adopted.target_plan_stage_id or plan.current_stage_id) or stage.status == "active"
                ),
                0,
            )
            if 0 <= active_index < len(plan.stages):
                active_stage = plan.stages[active_index]
                concept_set = {self._normalize_dependency_key(item) for item in adopted.concepts}
                outcome_set = {self._normalize_dependency_key(item) for item in active_stage.outcomes}
                if adopted.target_plan_stage_id == active_stage.id or concept_set & outcome_set:
                    active_stage.status = "completed"
                    next_stage = plan.stages[active_index + 1] if active_index + 1 < len(plan.stages) else None
                    if next_stage is not None:
                        next_stage.status = "active"
                        plan.current_stage_id = next_stage.id
                        plan_change_summary = f"Advanced from {active_stage.title} to {next_stage.title}."
                    else:
                        plan.current_stage_id = active_stage.id
                        plan_change_summary = f"Completed {active_stage.title}."
                    from_label = live_coach_stage_label(
                        plan=plan,
                        runtime=recovered_runtime,
                        existing=recovered_runtime,
                        stage_title=active_stage.title,
                    )
                    to_label = (
                        live_coach_stage_label(
                            plan=plan,
                            runtime=recovered_runtime,
                            existing=recovered_runtime,
                            stage_title=next_stage.title,
                        )
                        if next_stage is not None
                        else ""
                    )
                    if from_label and to_label:
                        plan_change_summary = f"Advanced from {from_label} to {to_label}."
                    elif from_label:
                        plan_change_summary = f"Completed {from_label}."
                    else:
                        plan_change_summary = live_memory_snapshot_overlay(
                            plan=plan,
                            runtime=recovered_runtime,
                            existing=recovered_runtime,
                            plan_change_summary=plan_change_summary,
                        )["plan_change_summary"]
                    plan_updated = True
                    self.repository.save_plan(workspace_id, plan)
        advanced = self.persist_plan_runtime_advance_after_adopt(workspace_id, adopted)
        self._refresh_training_next_challenge_after_runtime_advance(
            workspace_id,
            advanced or recovered_runtime,
        )
        if not isinstance(advanced, dict) or not str(advanced.get("current_step") or "").strip():
            leftover_training = bound_plan_leftover_training_live_identity_updates(
                workspace_id=workspace_id,
                generated_step="",
                workspace=structured._workspace if isinstance(structured._workspace, dict) else {},
            )
            if leftover_training:
                structured.update_workspace(**leftover_training)
        self._record_adopted_return_transfer(workspace_id, adopted)
        self._sync_live_evidence_binding(workspace_id)
        refreshed_runtime = advanced or recovered_runtime
        if isinstance(refreshed_runtime, dict) and str(refreshed_runtime.get("current_step") or "").strip():
            structured = self._structured_for(workspace_id)
            current_title = str(refreshed_runtime["current_step"]).strip()
            current_hop = structured._workspace.get("latest_training_next_hop")
            if isinstance(current_hop, dict):
                structured.update_workspace(
                    latest_training_next_hop=stamp_workspace_scope(
                        {**current_hop, "title": current_title, "card_title": current_title},
                        workspace_id,
                    ),
                    selected_card_title=current_title,
                    **{
                        TRAINING_CHROME_KEY: stamp_workspace_scope(
                            {"selected_card_title": current_title},
                            workspace_id,
                        )
                    },
                )
        self._persist_structured(workspace_id)
        return EvidenceAdoptResponse(
            evidence=adopted,
            plan_updated=plan_updated,
            plan_change_summary=plan_change_summary or "Evidence adopted without plan stage changes.",
        )

    def reject_evidence(self, workspace_id: str, evidence_id: str, reason: str = "") -> EvidenceItem:
        structured = self._structured_for(workspace_id)
        evidence = structured._evidence_items.get(evidence_id)
        if evidence is None or evidence.adopted or evidence.rejected_at:
            raise HTTPException(status_code=404, detail="Evidence item not found.")
        rejected = evidence.model_copy(
            update={
                "rejected_at": utc_now().isoformat(),
                "rejection_reason": reason,
            }
        )
        structured._evidence_items[evidence_id] = rejected
        self._persist_structured(workspace_id)
        self._sync_live_evidence_binding(workspace_id)
        return rejected

    def defer_evidence(self, workspace_id: str, evidence_id: str, reason: str = "") -> EvidenceItem:
        structured = self._structured_for(workspace_id)
        evidence = structured._evidence_items.get(evidence_id)
        if evidence is None or evidence.adopted or evidence.rejected_at:
            raise HTTPException(status_code=404, detail="Evidence item not found.")
        deferred = evidence.model_copy(
            update={
                "deferred_at": utc_now().isoformat(),
                "deferral_reason": reason,
            }
        )
        structured._evidence_items[evidence_id] = deferred
        self._persist_structured(workspace_id)
        self._sync_live_evidence_binding(workspace_id)
        return deferred

    def build_flash_deck(self, workspace_id: str) -> FlashDeckSnapshot:
        structured = self._structured_for(workspace_id)
        self._sync_dependency_training_views(structured)
        if structured._flash_deck is None:
            structured._flash_deck = self._build_flash_deck_snapshot(structured)
        self._persist_structured(workspace_id)
        return structured._flash_deck

    def submit_flashcard_answer(
        self,
        workspace_id: str,
        card_id: str,
        learner_answer: str = "",
        selected_option_index: int | None = None,
        selected_option_indices: list[int] | None = None,
        fill_blank_answers: dict[str, str] | None = None,
        sort_order: list[int] | None = None,
    ) -> FlashcardAttempt:
        structured = self._structured_for(workspace_id)
        self._sync_dependency_training_views(structured)
        card = self.get_card(workspace_id, card_id)
        answer_text = learner_answer.strip()
        selected_indices = sorted(
            {
                int(index)
                for index in (selected_option_indices or [])
                if isinstance(index, int) and index >= 0
            }
        )
        if selected_option_index is not None and selected_option_index >= 0 and selected_option_index not in selected_indices:
            selected_indices.append(selected_option_index)
            selected_indices.sort()
        submitted_blanks = {
            str(key): str(value).strip()
            for key, value in (fill_blank_answers or {}).items()
            if str(value).strip()
        }
        submitted_sort_order = [
            int(index)
            for index in (sort_order or [])
            if isinstance(index, int) and index >= 0
        ]
        dependency_history: list[DependencySkillMapHistoryEntry] = []
        if card is None:
            raise HTTPException(
                status_code=404,
                detail="Flashcard not found. Refresh Training to load the current cards.",
            )

        answer_mode = str(card.answer_mode or "text").strip().lower()
        answer_mode = {
            "choice": "single_choice",
            "single": "single_choice",
            "multiple": "multiple_choice",
            "multi": "multiple_choice",
            "fill": "fill_blank",
            "truefalse": "true_false",
            "boolean": "true_false",
        }.get(answer_mode, answer_mode)
        expected_indices = sorted(
            {
                int(index)
                for index in (card.correct_option_indices or [])
                if isinstance(index, int) and index >= 0
            }
        )
        if not expected_indices and card.correct_option_index is not None:
            expected_indices = [card.correct_option_index]
        expected_blanks = {
            str(key): str(value).strip()
            for key, value in (card.fill_blank_answers or {}).items()
            if str(value).strip()
        }
        expected_sort_order = [
            int(index)
            for index in (card.correct_sort_order or [])
            if isinstance(index, int) and index >= 0
        ]
        score = 0.0
        mismatches: list[str] = []
        correct = False
        if answer_mode in {"single_choice", "true_false"}:
            correct = bool(expected_indices and selected_indices == expected_indices)
            score = 1.0 if correct else 0.0
            if not correct:
                mismatches.append("selected_option")
        elif answer_mode == "multiple_choice":
            expected_set = set(expected_indices)
            selected_set = set(selected_indices)
            if expected_set:
                score = len(expected_set & selected_set) / len(expected_set)
            correct = bool(expected_set and selected_set == expected_set)
            if selected_set - expected_set:
                mismatches.append("extra_options")
            if expected_set - selected_set:
                mismatches.append("missing_options")
        elif answer_mode == "sorting":
            if expected_sort_order:
                matched = sum(
                    expected == actual
                    for expected, actual in zip(expected_sort_order, submitted_sort_order, strict=False)
                )
                score = matched / len(expected_sort_order)
            correct = bool(expected_sort_order and submitted_sort_order == expected_sort_order)
            if not correct:
                mismatches.append("sort_order")
        elif answer_mode == "fill_blank" and expected_blanks:
            expected_values = [
                expected_blanks[key]
                for key in sorted(expected_blanks, key=lambda value: int(value) if value.isdigit() else value)
            ]
            submitted_values = [
                submitted_blanks[key]
                for key in sorted(submitted_blanks, key=lambda value: int(value) if value.isdigit() else value)
            ]
            if len(expected_values) == len(submitted_values):
                matched = sum(
                    re.sub(r"\s+", " ", expected.lower()) == re.sub(r"\s+", " ", actual.lower())
                    for expected, actual in zip(expected_values, submitted_values, strict=False)
                )
                score = matched / len(expected_values) if expected_values else 0.0
            correct = bool(expected_values and score == 1.0)
            if not correct:
                mismatches.append("fill_blank")
        elif card.expected_answer:
            expected = re.sub(r"\s+", " ", card.expected_answer.strip().lower())
            answer = re.sub(r"\s+", " ", answer_text.lower())
            exact = answer and answer == expected
            containment = answer and (answer in expected or expected in answer)
            stop_words = {"a", "an", "and", "are", "for", "in", "is", "of", "on", "or", "the", "to", "use", "with"}
            expected_tokens = {
                token for token in re.split(r"[^a-z0-9]+", expected)
                if len(token) > 2 and token not in stop_words
            }
            answer_tokens = {
                token for token in re.split(r"[^a-z0-9]+", answer)
                if len(token) > 2 and token not in stop_words
            }
            overlap = len(expected_tokens & answer_tokens)
            overlap_threshold = max(3, (len(expected_tokens) + 1) // 2)
            correct = bool(exact or containment or (expected_tokens and overlap >= overlap_threshold))
            if not correct and card.dependency_key:
                normalized_answer = answer.replace(" ", "")
                dependency_hint = card.dependency_key.replace("-", "")
                correct = dependency_hint in normalized_answer
            score = 1.0 if correct else 0.0
            if not correct and (_contains_cjk_answer_text(expected) or _contains_cjk_answer_text(answer)):
                # CJK fallback: latin tokenization yields no tokens for Chinese
                # text, so grade paraphrases by CJK bigram/unigram Dice instead.
                coefficient = _cjk_answer_similarity(expected, answer)
                if coefficient >= _CJK_TEXT_CORRECT_THRESHOLD:
                    correct = True
                    score = coefficient
            if not correct:
                mismatches.append("text_answer")
        else:
            correct = False
            mismatches.append("missing_answer_key")

        if card.status == "active":
            next_status = "answered" if correct else "needs_primer"
            transition_reason = (
                "Flashcard answer submitted."
                if correct
                else "Flashcard answer was incorrect; keep the card for retry and reinforcement."
            )
            self.transition_card_status(
                workspace_id,
                card.card_id,
                next_status,
                reason=transition_reason,
            )
            card = self.get_card(workspace_id, card.card_id) or card

        detail = (
            "Flashcard answer matches the answer key."
            if correct
            else "Flashcard answer needs another pass against the answer key."
        )
        feedback: dict[str, Any] = {
            "kind": "flashcard_answer",
            "answer_mode": answer_mode,
            "correct": correct,
            "score": round(score, 3),
            "detail": detail,
            "retry_required": not correct,
            "mismatches": mismatches,
            "expected_option_indices": expected_indices,
            "selected_option_indices": selected_indices,
            "expected_sort_order": expected_sort_order,
            "submitted_sort_order": submitted_sort_order,
            "expected_fill_blank_answers": expected_blanks,
            "submitted_fill_blank_answers": submitted_blanks,
        }
        updated_card = card.model_copy(
            update={
                "last_feedback": feedback,
                "learner_answer": learner_answer,
                "learner_selected_option_indices": selected_indices,
                "learner_fill_blank_answers": submitted_blanks,
                "learner_sort_order": submitted_sort_order,
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._training_cards[card.card_id] = updated_card
        card = updated_card

        if card.focus_area:
            structured.update_mastery(
                card.focus_area,
                delta=0.08 if correct else -0.02,
                confidence=0.72 if correct else 0.55,
                review_after_days=2 if correct else 1,
            )

        if card.dependency_key:
            dependency_key = self._normalize_dependency_key(card.dependency_key)
            current = structured._dependency_mastery.get(dependency_key) or {}
            current_stage = str(current.get("mastery_stage") or "understood")
            next_stage = "recalled" if correct else current_stage
            if correct:
                structured.upsert_dependency_mastery(
                    dependency_key,
                    dependency_name=str(current.get("dependency_name") or dependency_key),
                    apis=list(current.get("apis") or []),
                    use_cases=list(current.get("use_cases") or []),
                    scenarios=list(current.get("scenarios") or []),
                    weakest_points=list(current.get("weakest_points") or []),
                    evidence=list(current.get("evidence") or []),
                    mastery_stage=next_stage,
                    mastery_stage_progress=self._ensure_stage_progress(
                        list(current.get("mastery_stage_progress") or []),
                        next_stage,
                    ),
                )
            else:
                structured.update_workspace(latest_flashcard_recovery_mode="flashcards")
                self._sync_dependency_training_views(structured)
                current_map = structured._dependency_skill_maps.get(dependency_key)
                focus_item = next(
                    (
                        item
                        for item in (current_map.top_review_items if current_map else [])
                        if item.layer == card.dependency_layer
                    ),
                    None,
                ) or (current_map.top_review_items[0] if current_map and current_map.top_review_items else None)
                if current_map is not None and focus_item is not None:
                    entry = DependencySkillMapHistoryEntry(
                        entry_id=f"hist-{uuid4().hex[:10]}",
                        dependency_key=dependency_key,
                        action="flash_retry",
                        version=current_map.version,
                        focus_item_key=focus_item.key,
                        focus_label=focus_item.label,
                        note="Flashcard answer showed the dependency layer is still unstable.",
                        before_snapshot=current_map.model_dump(mode="json"),
                        after_snapshot=current_map.model_dump(mode="json"),
                        after_summary=current_map.priority_summary,
                    )
                    structured._dependency_skill_map_history.append(entry)
                    dependency_history = [entry]

        attempt = FlashcardAttempt(
            card_id=card.card_id,
            correct=correct,
            score=round(score, 3),
            detail=detail,
            learner_answer=learner_answer,
            selected_option_index=selected_option_index,
            selected_option_indices=selected_indices,
            fill_blank_answers=submitted_blanks,
            sort_order=submitted_sort_order,
            answer_mode=answer_mode,
            feedback=feedback,
            dependency_key=card.dependency_key,
            dependency_layer=card.dependency_layer,
            question_style=card.question_style,
            knowledge_type=card.knowledge_type,
            dependency_mastery=self._dependency_mastery_snapshots(structured),
            dependency_skill_map_history=dependency_history,
        )
        structured._recent_flash_attempts.insert(0, attempt)
        structured._recent_flash_attempts = structured._recent_flash_attempts[:16]
        self._persist_structured(workspace_id)
        return attempt

    def build_scenario_lab(self, workspace_id: str) -> ScenarioLab | None:
        structured = self._structured_for(workspace_id)
        self._sync_dependency_training_views(structured)
        dependency_items = self._dependency_mastery_snapshots(structured)
        if not dependency_items:
            return None
        primary = dependency_items[0]
        workspace = structured._workspace
        scenario_lab = ScenarioLab(
            id=f"scenario-{uuid4().hex[:10]}",
            title=f"Scenario lab: {workspace.get('latest_learning_focus_area') or primary.dependency_name or primary.dependency_key}",
            focus_area=str(workspace.get("latest_learning_focus_area") or primary.dependency_name or primary.dependency_key),
            status="ready",
            summary=str(workspace.get("latest_learning_blocker") or "Rebuild the dependency judgment in one minimum scenario."),
            success_signal=str(
                workspace.get("latest_turn_success_signal")
                or "The minimum scenario proves the dependency behavior without widening scope."
            ),
            learner_deliverables=[
                str(workspace.get("latest_turn_expected_artifact") or "One minimum implementation artifact."),
            ],
            verification_steps=list(workspace.get("latest_turn_coach_checks") or ["Verify the boundary before widening scope."]),
            migrate_back_guidance=[
                str(workspace.get("latest_turn_after_try") or "Bring back the proof before migrating into the main project."),
                str(workspace.get("latest_turn_teach_back_prompt") or "Teach back why the dependency belongs."),
            ],
            dependency_keys=[primary.dependency_key],
            related_apis=list(primary.apis[:3]),
            minimum_environment=[
                "One isolated file, route, or function boundary.",
                "Exactly one dependency judgment under test.",
            ],
            last_action="created",
            version=1,
        )
        structured._scenario_lab = scenario_lab
        history = ScenarioLabHistoryEntry(
            entry_id=f"hist-{uuid4().hex[:10]}",
            scenario_lab_id=scenario_lab.id,
            action="created",
            version=1,
            note="Created from current dependency mastery and workspace signals.",
            before_snapshot={},
            after_snapshot=scenario_lab.model_dump(mode="json"),
        )
        structured._scenario_lab_history.append(history)
        structured.update_workspace(latest_training_submode="practice")
        self._persist_structured(workspace_id)
        return scenario_lab

    def apply_scenario_lab_action(
        self,
        workspace_id: str,
        scenario_lab_id: str,
        action: str,
        note: str = "",
        review_outcome: str = "",
        *,
        verified_by_evaluator: bool = False,
        verification_source: str = "",
    ) -> tuple[ScenarioLab | None, list[ScenarioLabHistoryEntry]]:
        structured = self._structured_for(workspace_id)
        if structured._scenario_lab is None or structured._scenario_lab.id != scenario_lab_id:
            return None, []
        scenario_lab = structured._scenario_lab
        if scenario_lab is None:
            return None, []
        if action == "complete":
            if scenario_lab.status != "in_progress":
                raise ValueError("Start the current scenario lab before completing it.")
            if not verified_by_evaluator or not verification_source.strip():
                raise ValueError(
                    "Scenario lab completion needs server-side verification. Run a Trainer evaluation, then refresh this lab."
                )
        status_map = {"start": "in_progress", "complete": "completed", "archive": "archived"}
        history_action = {"start": "started", "complete": "completed", "archive": "archived"}.get(action, action)
        updated = scenario_lab.model_copy(
            update={
                "status": status_map.get(action, scenario_lab.status),
                "last_action": action,
                "review_outcome": review_outcome or scenario_lab.review_outcome,
                "version": scenario_lab.version + 1,
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._scenario_lab = updated
        history_entry = ScenarioLabHistoryEntry(
            entry_id=f"hist-{uuid4().hex[:10]}",
            scenario_lab_id=updated.id,
            action=history_action,
            version=updated.version,
            note=note,
            before_snapshot=scenario_lab.model_dump(mode="json"),
            after_snapshot=updated.model_dump(mode="json"),
        )
        structured._scenario_lab_history.append(history_entry)
        structured.update_workspace(latest_training_submode="practice")
        if action == "complete":
            self.record_learning_outcome(
                workspace_id=workspace_id,
                concepts=updated.dependency_keys or [updated.focus_area],
                outcome="tests_passed",
                summary=note or "Scenario lab completed.",
                focus_area=updated.focus_area,
                scenario="scenario_lab",
                verified_result=review_outcome or updated.success_signal,
                verified_by_evaluator=True,
            )
            artifact = ReviewArtifactSnapshot(
                id=f"review-{uuid4().hex[:10]}",
                title=f"Review artifact: {updated.focus_area}",
                focus_area=updated.focus_area,
                source="scenario_lab",
                status="resolved",
                summary=note or updated.summary,
                root_cause=updated.summary,
                guardrail="Keep the same minimum boundary when migrating back.",
                next_self_implementation_rule="Migrate the same proven slice back into the project without widening scope.",
                recommended_recovery_mode="review",
                recommended_actions=["Move the same proven slice back into the project."],
                verified_result=review_outcome or updated.success_signal,
                last_action="resolved",
                version=1,
                metadata={"verification_source": verification_source.strip()},
            )
            structured._review_artifact = artifact
            structured._review_artifact_history.append(
                ReviewArtifactHistoryEntry(
                    entry_id=f"hist-{uuid4().hex[:10]}",
                    review_artifact_id=artifact.id,
                    action="resolved",
                    version=artifact.version,
                    note="Created from completed scenario lab.",
                    before_snapshot={},
                    after_snapshot=artifact.model_dump(mode="json"),
                )
            )
        self._persist_structured(workspace_id)
        return updated, list(reversed([item for item in structured._scenario_lab_history if item.scenario_lab_id == updated.id]))

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
        concepts = [concept]
        if scope == "focus_area" and focus_area:
            concepts = [
                item.concept
                for item in structured._weaknesses.values()
                if item.last_seen_context == focus_area
            ][:batch_limit] or [concept]
        created: list[ReviewQueueAction] = []
        for entry_concept in concepts:
            created.append(
                ReviewQueueAction(
                    entry_id=f"review-action-{uuid4().hex[:10]}",
                    concept=entry_concept,
                    action=action,
                    outcome="queued" if action == "accept" else "needs_more_practice" if action == "reset" else action,
                    focus_area=focus_area,
                    task_hint=task_hint,
                    note=note,
                    scope=scope,
                )
            )
        structured._review_queue_actions.extend(created)
        if action == "reset":
            structured.record_weakness(
                concept,
                note or "Review queue signaled more practice is needed.",
                severity=2,
                review_after_days=0,
                context=focus_area,
            )
        artifact = structured._review_artifact or ReviewArtifactSnapshot(
            id=f"review-{uuid4().hex[:10]}",
            title=f"Review artifact: {concept}",
            focus_area=concept,
            source="review_queue",
            status="active",
            summary=task_hint or note or f"Review {concept} before the next attempt.",
            root_cause=note or f"{concept} still needs a tighter review loop.",
            guardrail="Keep the review attached to the smallest failing boundary.",
            next_self_implementation_rule=task_hint or "Rebuild one minimum slice before widening scope.",
            recommended_recovery_mode="review_queue",
            recommended_actions=[task_hint or "Rebuild one minimum slice before widening scope."],
            last_action="reviewed",
            version=1,
        )
        if structured._review_artifact is not None:
            artifact = artifact.model_copy(
                update={
                    "status": "active",
                    "summary": task_hint or note or artifact.summary,
                    "root_cause": note or artifact.root_cause,
                    "last_action": "reviewed",
                    "version": artifact.version + 1,
                    "updated_at": utc_now().isoformat(),
                }
            )
        structured._review_artifact = artifact
        structured._review_artifact_history.append(
            ReviewArtifactHistoryEntry(
                entry_id=f"hist-{uuid4().hex[:10]}",
                review_artifact_id=artifact.id,
                action="reviewed",
                version=artifact.version,
                note=note,
                before_snapshot={},
                after_snapshot=artifact.model_dump(mode="json"),
            )
        )
        structured.update_workspace(latest_training_submode="review_queue")
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
                    updated_at=utc_now(),
                    next_review_at=utc_now() + timedelta(days=2),
                )
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
                {
                    "coach_defaults": coach_defaults.model_dump(),
                    "memory_scope": coach_defaults.memory_scope,
                    "working_set_mode": coach_defaults.working_set_mode,
                    "review_cadence": coach_defaults.review_cadence,
                    "review_reminder_mode": coach_defaults.review_reminder_mode,
                    "workspace_memory_toggles": coach_defaults.workspace_memory_toggles.model_dump(),
                }
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
    ) -> None:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved_workspace_id)
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
        if coach_defaults:
            structured.remember_preference("memory_scope", coach_defaults.memory_scope, source="coach-defaults")
            structured.remember_preference("working_set_mode", coach_defaults.working_set_mode, source="coach-defaults")
            structured.remember_preference("review_cadence", coach_defaults.review_cadence, source="coach-defaults")
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
        if cleaned_summary and ("verified" in cleaned_summary.lower() or "通过" in cleaned_summary or "完成" in cleaned_summary):
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
                {
                    "coach_defaults": coach_defaults.model_dump(),
                    "memory_scope": coach_defaults.memory_scope,
                    "working_set_mode": coach_defaults.working_set_mode,
                    "review_cadence": coach_defaults.review_cadence,
                    "review_reminder_mode": coach_defaults.review_reminder_mode,
                    "workspace_memory_toggles": coach_defaults.workspace_memory_toggles.model_dump(),
                }
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
        self._persist_structured(resolved_workspace_id)

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
        if coach_defaults:
            structured.remember_preference(
                "memory_scope",
                coach_defaults.memory_scope,
                source="coach-settings",
            )
            structured.remember_preference(
                "working_set_mode",
                coach_defaults.working_set_mode,
                source="coach-settings",
            )
            structured.remember_preference(
                "review_cadence",
                coach_defaults.review_cadence,
                source="coach-settings",
            )
            structured.remember_preference(
                "review_reminder_mode",
                coach_defaults.review_reminder_mode,
                source="coach-settings",
            )
            workspace_patch.update(
                {
                    "coach_defaults": coach_defaults.model_dump(),
                    "memory_scope": coach_defaults.memory_scope,
                    "working_set_mode": coach_defaults.working_set_mode,
                    "review_cadence": coach_defaults.review_cadence,
                    "review_reminder_mode": coach_defaults.review_reminder_mode,
                    "workspace_memory_toggles": coach_defaults.workspace_memory_toggles.model_dump(),
                }
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
    ) -> None:
        cleaned_summary = summary.strip()
        cleaned_next_step = next_step.strip()
        cleaned_review_note = review_note.strip() if review_note else ""
        cleaned_decision = (decision or "").strip()
        cleaned_teaching_note = (teaching_note or "").strip()
        cleaned_confidence = (confidence or "").strip()
        cleaned_evidence = _normalize_text_items(evidence, limit=4)
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
            return

        task_id = focus_area or scenario or "coach-turn"
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
            "latest_coach_focus_area": focus_area or "",
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
                    "focus_area": focus_area or "",
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
                focus_area=(focus_area or "").strip(),
                scenario=scenario,
                blocker=cleaned_review_note,
                teaching_signal=cleaned_teaching_note or cleaned_decision or cleaned_review_note or cleaned_next_step or cleaned_summary,
                decision=cleaned_decision,
                teaching_note=cleaned_teaching_note,
                confidence=cleaned_confidence,
                evidence=cleaned_evidence,
            )

        normalized_focus = self._normalize_focus_area(focus_area)

        if normalized_focus:
            structured.update_mastery(
                normalized_focus,
                delta=0.05,
                confidence=0.62,
                review_after_days=2,
            )

        if cleaned_next_step and normalized_focus:
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
        self._persist_structured(workspace_id)

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
        summary = "\n".join(record.content.strip() for record in verified[-3:])
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
        }

    def _bind_training_return_evidence_to_plan_runtime(
        self,
        *,
        workspace_id: str,
        card: TrainingCardCandidateSnapshot,
        evidence: EvidenceItem,
    ) -> None:
        bind = self._training_return_plan_runtime_bind(workspace_id, card)
        if not bind["current_step"]:
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
        for item in (card.target_skill, card.focus_area, bind["current_step"]):
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
                target_plan_stage_id=card.plan_links[0] if card.plan_links else "",
            ),
            verified=True,
            verification_source=verification_source,
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

    def _load_training_reliability(self, structured: StructuredMemoryService) -> dict[str, Any] | None:
        payload = structured._workspace.get(WORKSPACE_RELIABILITY_KEY)
        return dict(payload) if isinstance(payload, dict) else None

    def _save_training_reliability(
        self,
        workspace_id: str,
        structured: StructuredMemoryService,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_revision = int(record.get("snapshot_revision") or 0)
        workspace = structured.update_workspace(
            workspace_id=workspace_id,
            **{
                WORKSPACE_RELIABILITY_KEY: as_workspace_record(record),
                WORKSPACE_SNAPSHOT_REVISION_KEY: snapshot_revision or None,
            },
        )
        self._persist_structured(workspace_id)
        return dict(workspace)

    def latest_training_reliability(self, workspace_id: str) -> dict[str, Any] | None:
        structured = self._structured_for(self._resolve_workspace_for_write(workspace_id))
        record = expire_if_needed(self._load_training_reliability(structured))
        if record is None:
            return None
        if record != self._load_training_reliability(structured):
            self._save_training_reliability(workspace_id, structured, record)
        return as_workspace_record(record)

    def cancel_training_reliability(
        self,
        workspace_id: str,
        *,
        request_id: str,
        command_id: str = "",
        card_id: str = "",
    ) -> dict[str, Any]:
        resolved = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved)
        record = expire_if_needed(self._load_training_reliability(structured))
        if record is None:
            raise LookupError("No training reliability request is available to cancel.")
        if request_id.strip() and str(record.get("request_id") or "") != request_id.strip():
            if command_id and str(record.get("command_id") or "") != command_id:
                raise LookupError("The cancel request does not match the current training save.")
            if card_id and str(record.get("card_id") or "") != card_id:
                raise LookupError("The cancel request does not match the current training card.")
        cancelled = request_cancel(record)
        return self._save_training_reliability(resolved, structured, cancelled)

    def recover_training_reliability(
        self,
        workspace_id: str,
        *,
        request_id: str,
        revision: int = 0,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        resolved = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved)
        record = expire_if_needed(self._load_training_reliability(structured))
        if record is None:
            raise LookupError("No training reliability request is available to recover.")
        recovered = recover_record(
            record,
            request_id=request_id,
            revision=revision,
            timeout_ms=timeout_ms,
        )
        return self._save_training_reliability(resolved, structured, recovered)

    def expire_training_reliability(self, workspace_id: str) -> dict[str, Any]:
        resolved = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved)
        record = expire_if_needed(self._load_training_reliability(structured))
        if record is None:
            raise LookupError("No training reliability request is available to expire.")
        return self._save_training_reliability(resolved, structured, record)

    def run_training_reliability(
        self,
        workspace_id: str | None,
        *,
        request_id: str,
        command_id: str,
        card_id: str = "",
        handoff_id: str = "",
        idempotency_key: str = "",
        revision: int = 0,
        timeout_ms: int = 30_000,
        cancel: bool = False,
        learning_phase: str = "",
        work: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        resolved = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved)
        existing = expire_if_needed(self._load_training_reliability(structured))
        if existing is not None and existing != self._load_training_reliability(structured):
            self._save_training_reliability(resolved, structured, existing)
            structured = self._structured_for(resolved)

        if cancel:
            if existing is None:
                raise LookupError("No training reliability request is available to cancel.")
            cancelled = request_cancel(existing)
            return self._save_training_reliability(resolved, structured, cancelled)

        if should_replay(existing, request_id, idempotency_key):
            return dict(structured._workspace)

        if should_coalesce(
            existing,
            request_id=request_id,
            command_id=command_id,
            card_id=card_id,
        ):
            return dict(structured._workspace)

        if existing is not None and str(existing.get("phase") or "") in {"failed", "cancelled"}:
            if (
                str(existing.get("command_id") or "") == command_id
                and str(existing.get("card_id") or "") == card_id
            ):
                record = recover_record(
                    existing,
                    request_id=request_id or str(existing.get("request_id") or ""),
                    revision=revision,
                    timeout_ms=timeout_ms,
                )
            else:
                record = begin_record(
                    request_id=request_id,
                    command_id=command_id,
                    card_id=card_id,
                    handoff_id=handoff_id,
                    idempotency_key=idempotency_key,
                    revision=revision or 1,
                    timeout_ms=timeout_ms,
                    learning_phase=learning_phase,
                )
        else:
            record = begin_record(
                request_id=request_id,
                command_id=command_id,
                card_id=card_id,
                handoff_id=handoff_id,
                idempotency_key=idempotency_key,
                revision=revision or 1,
                timeout_ms=timeout_ms,
                learning_phase=learning_phase,
            )

        record = mark_executing(record)
        self._save_training_reliability(resolved, structured, record)

        try:
            result = work()
        except Exception as exc:
            structured = self._structured_for(resolved)
            failed = mark_failed(record, str(exc))
            self._save_training_reliability(resolved, structured, failed)
            raise

        structured = self._structured_for(resolved)
        next_snapshot = int(structured._workspace.get(WORKSPACE_SNAPSHOT_REVISION_KEY) or 0) + 1
        latest_handoff = structured._workspace.get("latest_training_handoff")
        persisted_phase = learning_phase
        if isinstance(latest_handoff, dict):
            persisted_phase = str(latest_handoff.get("learning_phase") or persisted_phase)
        finished = mark_succeeded(
            record,
            snapshot_revision=next_snapshot,
            learning_phase=persisted_phase,
        )
        workspace = self._save_training_reliability(resolved, structured, finished)
        if isinstance(result, dict):
            merged = dict(result)
            merged[WORKSPACE_RELIABILITY_KEY] = workspace.get(WORKSPACE_RELIABILITY_KEY)
            merged[WORKSPACE_SNAPSHOT_REVISION_KEY] = workspace.get(WORKSPACE_SNAPSHOT_REVISION_KEY)
            return merged
        return workspace

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
        if handoff.phase is TrainingPhase.REFLECT and handoff.reflection.strip():
            return dict(structured._workspace)
        if handoff.phase is TrainingPhase.RETURN:
            raise ValueError("A completed training handoff cannot be reflected again.")
        reflected = generator.record_reflection(handoff.handoff_id, reflection)
        if reflected is None:
            raise LookupError("Training handoff not found.")
        self.record_reflection(
            card.card_id,
            reflected.reflection,
            ["Complete Return to persist the verified result."],
            workspace_id=resolved_workspace_id,
        )
        return self._persist_training_handoff_progress(
            workspace_id=resolved_workspace_id,
            structured=structured,
            card=card,
            handoff=reflected,
        )

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
                except Exception:
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
        except Exception:
            return self._persist_training_handoff_progress(
                workspace_id=resolved_workspace_id,
                structured=structured,
                card=card,
                handoff=handoff,
                return_evidence_persisted=False,
            )
        returned = generator.return_handoff(handoff.handoff_id)
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
        handoff = generator.hydrate_handoff(payload) if isinstance(payload, dict) else None
        if handoff is not None and handoff.handoff_id:
            rebound_title = str(getattr(card, "title", "") or "").strip() or handoff.card_title
            handoff = replace(
                handoff,
                card_id=card.card_id,
                handoff_id=f"handoff-{card.card_id}-{uuid4().hex[:12]}",
                card_title=rebound_title,
                handoff_content=replace(
                    handoff.handoff_content,
                    card_id=card.card_id,
                    card_title=rebound_title,
                ),
                evidence=[
                    record if record.card_id == card.card_id else replace(record, card_id=card.card_id)
                    for record in handoff.evidence
                ],
            )
        else:
            handoff = generator.build_handoff_record(card, {})
        handoff_payload = TrainingHandoffGenerator._handoff_payload(handoff)
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
        request_id: str = "",
        idempotency_key: str = "",
        revision: int = 0,
        timeout_ms: int = 30_000,
        cancel: bool = False,
    ) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            return self._record_training_practice_evaluation_result_body(
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
            )
        pending_verification_markers = (
            "verification is still required",
            "run at least one dynamic verifier",
            "verify current file",
            "current ide file evidence",
            "current-file evidence",
        )
        summary_next_step_text = " ".join([cleaned_summary, cleaned_next_step]).lower()
        if (
            not passed
            and not verified_by_evaluator
            and any(marker in summary_next_step_text for marker in pending_verification_markers)
        ):
            handoff_generator._sync_handoff_verification_state(handoff_record, "verification_required")
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
                    if verified_pass and not handoff_completed
                    else ["Verify the current IDE file."] if verification_pending else []
                )
            ),
            "success_signal": cleaned_summary if handoff_completed else "",
            "return_with": cleaned_summary if verification_pending or handoff_completed else blocked_by,
            "next_after_completion": next_after_completion,
            "fallback_action": fallback_action,
            "return_mode": return_mode,
            "return_summary": cleaned_summary or blocked_by,
            "judged_at": now,
            "source_chain": ["training", cleaned_evidence_source, evidence_origin],
        }
        handoff.update(handoff_payload)
        handoff["card_title"] = title
        next_hop = {
            "candidate_id": selected_card_id,
            "candidate_type": "practice_candidate",
            "title": title,
            "summary": cleaned_summary,
            "why_now": (
                "This card completed Learn, Try, Verify, Reflect, and Return with trusted evidence."
                if handoff_completed
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
                ),
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
                if verified_pass
                else "verification_pending"
                if verification_pending
                else "evaluation"
            ),
            selected_card_id=selected_card_id,
            selected_card_type="practice",
            selected_card_title=title,
            selected_card_status=status,
        )
        self._record_training_event(
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
            },
        )
        self._persist_structured(resolved_workspace_id)
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
    ) -> LearningOutcomeRecord:
        resolved_workspace_id = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(resolved_workspace_id)
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
                next_step="Widen the scope only after the verified result is preserved.",
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
                next_step="Reduce the next step and tighten verification." if repeated_failure else "Keep the next move attached to the verified result.",
                source="learning-outcome",
            )
        if normalized_summary or normalized_outcome:
            structured.remember_progress(
                scenario or normalized_outcome,
                focus_area or focus_anchor,
                normalized_summary or normalized_outcome,
                "Tighten the next practice loop." if repeated_failure else "Continue with the verified slice.",
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

    @staticmethod
    def _extract_long_term_goal(message: str) -> str:
        patterns = [
            r"(?:长期目标(?:是)?|目标是|我想要|我希望|我想)([^。！？\n]{4,80})",
            r"(?:long[- ]term goal(?:\s+is(?:\s+to)?)?|goal is|i want to|i want|i hope to)([^.!\n]{4,100})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _extract_background(message: str) -> str:
        patterns = [
            r"(?:我现在是|我目前是|我属于|我是)([^。！？，,\n]{2,50})",
            r"(?:i am|i'm|my background is)\s*(?:an?\s+)?([^.,!\n]{2,60})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _extract_learner_name(message: str) -> str:
        patterns = [
            r"(?:我叫|你可以叫我|叫我)([^。！？，,\n]{1,24})",
            r"(?:my name is|call me)([^.!\n]{1,24})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _extract_weekly_hours(message: str) -> int | None:
        zh = re.search(
            r"每周(?:大概|能|可以)?(?:投入|安排|学习)?\s*(\d{1,2})\s*(?:小时|h)",
            message,
            flags=re.IGNORECASE,
        )
        if zh:
            return int(zh.group(1))
        en = re.search(r"(\d{1,2})\s*(?:hours?|hrs?)\s*(?:a|per)?\s*week", message, flags=re.IGNORECASE)
        if en:
            return int(en.group(1))
        return None

    @staticmethod
    def _extract_teaching_style(message: str) -> str:
        lowered = message.lower()
        if any(token in lowered for token in ("引导式", "guided")):
            return "guided"
        if any(token in lowered for token in ("平衡式", "balanced")):
            return "balanced"
        if any(token in lowered for token in ("直接式", "直接一点", "direct")):
            return "direct"
        return ""

    @staticmethod
    def _extract_answer_policy(message: str) -> str:
        lowered = message.lower()
        if any(token in lowered for token in ("直接给代码", "直接告诉我", "just tell me", "give me the code")):
            return "direct"
        if any(token in lowered for token in ("引导", "guided")):
            return "guided"
        if any(token in lowered for token in ("平衡", "balanced")):
            return "balanced"
        return ""

    @staticmethod
    def _extract_preferred_libraries(message: str) -> list[str]:
        libraries = [
            "fastapi",
            "pytest",
            "react",
            "vue",
            "next.js",
            "nextjs",
            "typescript",
            "tailwind",
            "django",
            "flask",
            "sqlalchemy",
        ]
        lowered = message.lower()
        matched = [item for item in libraries if item in lowered]
        return list(dict.fromkeys(matched))

    @staticmethod
    def _extract_project_context(message: str, *, focus_area: str) -> str:
        quoted = re.search(r"[“\"]([^”\"]{4,80})[”\"]", message)
        if quoted:
            return quoted.group(1).strip()
        if focus_area:
            return focus_area
        patterns = [
            r"(?:项目|工程|idea|功能|模块)([^。！？\n]{3,60})",
            r"(?:project|feature|module|idea)([^.!\n]{3,80})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _extract_blocker(message: str) -> str:
        patterns = [
            r"(?:卡在|卡住了|问题是|报错是|不会的地方是)([^。！？\n]{3,80})",
            r"(?:stuck on|blocked on|the issue is|the blocker is|error is)([^.!\n]{3,100})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _extract_rhythm_preference(message: str) -> str:
        lowered = message.lower()
        if any(token in lowered for token in ("一步一步", "慢一点", "small step", "step by step", "tiny step")):
            return "small-step"
        if any(token in lowered for token in ("快一点", "直接上", "move fast", "faster")):
            return "fast"
        if any(token in lowered for token in ("按计划", "稳一点", "steady", "systematic")):
            return "steady"
        return ""

    @staticmethod
    def _extract_preferred_stack(message: str) -> str:
        patterns = [
            r"(?:技术栈(?:是|想用)?|我想用|我主要用|偏向用)([^。！？\n]{3,72})",
            r"(?:stack is|prefer to use|mainly use|want to use)([^.!\n]{3,80})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _extract_learning_mode(message: str) -> str:
        lowered = message.lower()
        mapping = [
            (("先讲原理", "原理优先", "concept first"), "concept-first"),
            (("带我实现", "边做边学", "hands on", "implement with me"), "hands-on"),
            (("先定计划", "按计划练", "plan first"), "plan-first"),
            (("给我出题", "训练题", "exercise"), "exercise-first"),
            (("一步一步带我", "引导式", "guided"), "guided"),
        ]
        for tokens, label in mapping:
            if any(token in lowered for token in tokens):
                return label
        return ""

    @staticmethod
    def _extract_onboarding_request(message: str) -> str:
        patterns = [
            r"(?:我最想推进的是|这轮最想推进的是|我现在最需要的是)([^。！？\n]{4,80})",
            r"(?:what i most want to move forward is|what i need most right now is)([^.!\n]{4,100})",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ：:，,。.!")
        return ""

    @staticmethod
    def _normalize_response_language_label(response_language: str, *, message: str) -> str:
        normalized = response_language.strip().lower()
        if normalized.startswith("zh") or _contains_chinese(message):
            return "zh-CN"
        if normalized:
            return normalized
        if re.search(r"[a-zA-Z]", message):
            return "en-US"
        return ""

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

    def _derive_weakness_records(
        self,
        resources: list[ResourceRecord],
        plan: LearningPlan | None,
        lane_snapshot: LaneMemorySnapshot | None = None,
    ) -> list[WeaknessRecord]:
        derived = list(lane_snapshot.weaknesses if lane_snapshot else [])
        if resources and not derived:
            derived.append(
                WeaknessRecord(
                    concept="resource-grounding",
                    reason="Resource grounding coverage needs verification",
                    severity=1,
                )
            )
        if plan and not plan.frozen:
            derived.append(
                WeaknessRecord(
                    concept="plan-discipline",
                    reason="Plan still mutable; freeze milestones after alignment",
                    severity=1,
                )
            )
        if not derived:
            derived.append(
                WeaknessRecord(
                    concept="new-workspace",
                    reason="Start with one tiny review-oriented move before opening a broader lane.",
                    severity=2,
                )
            )
        return derived

    def _normalize_teaching_asset_scenario(self, scenario: str | None) -> str:
        normalized = (scenario or "").strip().lower()
        return {
            "review": "review_reflection",
            "principle": "principle_explanation",
            "project_idea": "project_idea_mining",
        }.get(normalized, normalized)

    def teaching_knowledge_catalog(
        self,
        workspace_id: str,
        *,
        snapshot: MemorySnapshot | None = None,
        limit_per_group: int = 3,
    ) -> dict[str, Any]:
        assets = list(snapshot.teaching_assets) if snapshot is not None else self.list_teaching_assets(workspace_id, limit=24)
        by_scope: dict[str, list[TeachingKnowledgeAsset]] = {"project": [], "personal": [], "general": []}
        by_kind: dict[str, list[TeachingKnowledgeAsset]] = {}
        by_origin: dict[str, list[TeachingKnowledgeAsset]] = {}
        for asset in assets:
            by_scope.setdefault(asset.scope, []).append(asset)
            by_kind.setdefault(asset.kind, []).append(asset)
            by_origin.setdefault(asset.origin, []).append(asset)
        return {
            "total": len(assets),
            "by_scope": {key: self._catalog_group_summary(value, limit_per_group) for key, value in by_scope.items() if value},
            "by_kind": {key: self._catalog_group_summary(value, limit_per_group) for key, value in by_kind.items() if value},
            "by_origin": {key: self._catalog_group_summary(value, limit_per_group) for key, value in by_origin.items() if value},
            "top_assets": [self._asset_catalog_entry(asset) for asset in assets[:limit_per_group]],
        }

    def _catalog_group_summary(
        self,
        assets: list[TeachingKnowledgeAsset],
        limit: int,
    ) -> dict[str, Any]:
        ranked = sorted(
            assets,
            key=lambda item: (
                -(item.trust_score or 0.0),
                -(item.usage_count or 0),
                item.updated_at or "",
            ),
            reverse=False,
        )
        ranked.reverse()
        return {
            "count": len(assets),
            "examples": [self._asset_catalog_entry(asset) for asset in ranked[:limit]],
        }

    def _asset_catalog_entry(self, asset: TeachingKnowledgeAsset) -> dict[str, Any]:
        return {
            "id": asset.id,
            "title": asset.title,
            "kind": asset.kind,
            "scope": asset.scope,
            "origin": asset.origin,
            "focus_area": asset.focus_area,
            "scenario": asset.scenario,
            "summary": asset.summary,
            "source_summary": asset.source_summary,
            "source_quality_flags": list(asset.source_quality_flags[:5]),
            "source_freshness": asset.source_freshness,
            "source_retrieved_at": asset.source_retrieved_at,
            "source_ids": list(asset.source_ids[:3]),
            "source_fragments": list(asset.source_fragments[:3]),
            "evidence_snippets": list(asset.evidence_snippets[:3]),
            "retrieval_hints": list(asset.retrieval_hints[:5]),
            "trust_score": asset.trust_score,
            "usage_count": asset.usage_count,
        }

    def _teaching_asset_tokens(self, value: str) -> set[str]:
        cleaned = value.replace("/", " ").replace("-", " ").replace("_", " ")
        return {
            token
            for token in re.findall(r"[\w\u4e00-\u9fff]+", cleaned.lower())
            if len(token) > 1
        }

    def _teaching_asset_kind_weight(self, kind: str, scenario: str) -> float:
        scenario_weights: dict[str, dict[str, float]] = {
            "idea_implementation": {
                "implementation_pattern": 6.0,
                "exercise_seed": 4.0,
                "common_pitfall": 4.0,
                "concept_card": 2.0,
                "explanation_recipe": 2.0,
            },
            "engineering_challenge": {
                "exercise_seed": 6.0,
                "implementation_pattern": 5.0,
                "common_pitfall": 3.0,
            },
            "project_adaptation": {
                "implementation_pattern": 5.0,
                "common_pitfall": 5.0,
                "exercise_seed": 3.0,
                "concept_card": 2.0,
            },
            "planning": {
                "exercise_seed": 5.0,
                "implementation_pattern": 3.0,
                "concept_card": 3.0,
            },
            "concept_teaching": {
                "explanation_recipe": 6.0,
                "concept_card": 5.0,
                "common_pitfall": 3.0,
            },
            "principle_explanation": {
                "explanation_recipe": 6.0,
                "concept_card": 5.0,
                "common_pitfall": 3.0,
            },
            "review_reflection": {
                "common_pitfall": 6.0,
                "implementation_pattern": 5.0,
                "exercise_seed": 3.0,
            },
            "project_idea_mining": {
                "exercise_seed": 6.0,
                "implementation_pattern": 3.0,
                "concept_card": 2.0,
            },
            "project_sourcing": {
                "exercise_seed": 5.0,
                "implementation_pattern": 2.0,
                "concept_card": 2.0,
            },
        }
        return scenario_weights.get(scenario, {}).get(kind, 1.0)

    def _material_routing_for_workspace(self, workspace_id: str) -> MaterialRoutingDecision:
        structured = self._structured_for(workspace_id)
        lane = structured.snapshot()
        transfer = normalize_transfer_skill_state_record(structured._workspace.get("latest_transfer_state"))
        pressure = self._context_pressure_from_lane(lane, workspace_id=workspace_id)
        controls = resolve_pedagogy_controls(
            analyze_learning_evidence(list(getattr(lane, "learning_outcomes", []) or [])),
            transfer_scene_count=int((transfer or {}).get("scene_count") or 0),
            transfer_state=str((transfer or {}).get("state") or ""),
            user_preference=str(structured._workspace.get("latest_user_feedback_kind") or ""),
            time_budget=pressure.time_budget,
            task_urgency=pressure.task_urgency,
            project_complexity=pressure.project_complexity,
        )
        return resolve_material_routing(
            controls.material_recommendation,
            transfer_scene_count=controls.transfer_scene_count,
            transfer_state=str((transfer or {}).get("state") or ""),
            time_budget=controls.time_budget,
            task_urgency=controls.task_urgency,
            project_complexity=controls.project_complexity,
        )

    def _teaching_asset_rank(
        self,
        asset: TeachingKnowledgeAsset,
        *,
        workspace_id: str,
        scenario: str,
        normalized_focus: str,
        normalized_query: str,
        focus_tokens: set[str],
        material_routing: MaterialRoutingDecision | None = None,
    ) -> tuple[float, float, float, float, str]:
        scope_score = (
            3.0
            if asset.scope == "project" and asset.workspace_id == workspace_id
            else 2.0
            if asset.scope == "personal"
            else 1.0
        )
        scenario_score = self._teaching_asset_kind_weight(asset.kind, scenario)
        asset_scenario = self._normalize_teaching_asset_scenario(asset.scenario)
        if scenario and asset_scenario == scenario:
            scenario_score += 4.0
        elif scenario and asset_scenario and scenario in asset_scenario:
            scenario_score += 2.0

        asset_text = " ".join(
            [
                asset.title,
                asset.summary,
                asset.source_summary,
                asset.focus_area,
                asset.scenario,
                " ".join(asset.tags),
                " ".join(asset.retrieval_hints[:4]),
                " ".join(asset.evidence_snippets[:2]),
                " ".join(asset.source_fragments[:2]),
            ]
        ).lower()
        asset_tokens = self._teaching_asset_tokens(asset_text)
        overlap_score = float(len(asset_tokens & focus_tokens)) * 3.0 if focus_tokens else 0.0
        if normalized_focus and normalized_focus in asset.focus_area.lower():
            overlap_score += 6.0
        if normalized_focus and normalized_focus in asset.title.lower():
            overlap_score += 4.0
        if normalized_query and normalized_query in asset.summary.lower():
            overlap_score += 2.0

        trust_and_usage = float(asset.trust_score or 0.0) + min(float(asset.usage_count or 0), 6.0) * 0.15
        effectiveness_score = self._teaching_asset_effectiveness_score(asset)
        freshness_penalty = 0.35 if asset.source_freshness == "stale" else 0.0
        quality_penalty = 0.18 * len(
            [
                flag
                for flag in asset.source_quality_flags
                if flag in {"thin_content", "vision_disabled", "stale"}
            ]
        )
        if material_routing is None:
            material_routing = self._material_routing_for_workspace(workspace_id)
        scope_score = scope_score + teaching_asset_scope_bias(
            asset.scope,
            asset.workspace_id,
            workspace_id,
            material_routing,
        )
        return (
            overlap_score,
            scenario_score,
            scope_score,
            trust_and_usage + effectiveness_score - freshness_penalty - quality_penalty,
            asset.updated_at or "",
        )

    def _teaching_asset_effectiveness_score(self, asset: TeachingKnowledgeAsset) -> float:
        success = float(asset.success_count or 0)
        failure = float(asset.failure_count or 0)
        if success <= 0 and failure <= 0:
            return 0.0
        scenario_bonus = 0.0
        for value in asset.effectiveness_by_scenario.values():
            if not isinstance(value, dict):
                continue
            scenario_bonus += min(float(value.get("success", 0)), 3.0) * 0.08
            scenario_bonus -= min(float(value.get("failure", 0)), 3.0) * 0.05
        return success * 0.22 - failure * 0.16 + scenario_bonus

    def _teaching_asset_is_relevant(
        self,
        asset: TeachingKnowledgeAsset,
        *,
        scenario: str,
        normalized_focus: str,
        focus_tokens: set[str],
    ) -> bool:
        asset_scenario = self._normalize_teaching_asset_scenario(asset.scenario)
        if scenario and asset_scenario == scenario:
            return True
        if normalized_focus:
            focus_fields = " ".join([asset.title, asset.summary, asset.focus_area]).lower()
            if normalized_focus in focus_fields:
                return True
        asset_tokens = self._teaching_asset_tokens(
            " ".join(
                [
                    asset.title,
                    asset.summary,
                    asset.source_summary,
                    asset.focus_area,
                    asset.scenario,
                    " ".join(asset.tags),
                    " ".join(asset.retrieval_hints[:4]),
                    " ".join(asset.evidence_snippets[:2]),
                ]
            )
        )
        return bool(asset_tokens & focus_tokens)

    def _recalled_memory_lesson(self, asset: TeachingKnowledgeAsset) -> str:
        for candidate in (
            asset.implementation_pattern,
            asset.common_pitfall,
            asset.explanation_recipe,
            asset.exercise_seed,
            asset.why_it_matters,
            asset.summary,
            asset.source_summary,
            asset.example,
            asset.anti_pattern,
            next((item for item in asset.source_fragments if item.strip()), ""),
        ):
            cleaned = str(candidate or "").strip()
            if cleaned:
                return cleaned
        return ""

    def _recalled_memory_evidence(self, asset: TeachingKnowledgeAsset) -> str:
        for candidate in [
            *asset.evidence_snippets[:2],
            *asset.source_fragments[:2],
            asset.source_summary,
            asset.summary,
        ]:
            cleaned = str(candidate or "").strip()
            if cleaned:
                return cleaned
        return ""

    def _recalled_memory_match_reasons(
        self,
        asset: TeachingKnowledgeAsset,
        *,
        scenario: str,
        normalized_focus: str,
        normalized_query: str,
        focus_tokens: set[str],
    ) -> list[str]:
        reasons: list[str] = []
        asset_scenario = self._normalize_teaching_asset_scenario(asset.scenario)
        if scenario and asset_scenario == scenario:
            reasons.append("scenario_match")
        elif scenario and asset_scenario and scenario in asset_scenario:
            reasons.append("scenario_adjacent")

        focus_text = " ".join(
            [
                asset.title,
                asset.summary,
                asset.focus_area,
                " ".join(asset.retrieval_hints[:3]),
            ]
        ).lower()
        if normalized_focus and normalized_focus in focus_text:
            reasons.append("focus_match")
        if normalized_query and normalized_query in focus_text:
            reasons.append("query_match")

        asset_tokens = self._teaching_asset_tokens(
            " ".join(
                [
                    asset.title,
                    asset.summary,
                    asset.focus_area,
                    asset.scenario,
                    " ".join(asset.retrieval_hints[:4]),
                    " ".join(asset.evidence_snippets[:2]),
                ]
            )
        )
        if focus_tokens and asset_tokens & focus_tokens:
            reasons.append("token_overlap")
        if int(asset.success_count or 0) > 0:
            reasons.append("worked_before")
        elif int(asset.usage_count or 0) > 0:
            reasons.append("used_before")
        if float(asset.trust_score or 0.0) >= 0.7:
            reasons.append("high_trust")
        return reasons[:4]

    def _transfer_skill_observation(self, lane_snapshot: LaneMemorySnapshot) -> str:
        record = normalize_transfer_skill_state_record(lane_snapshot.workspace.get("latest_transfer_state"))
        if not record:
            return ""
        language = str(lane_snapshot.workspace.get("response_language") or "")
        copy = describe_transfer_skill_state(record["state"], record["concept"], language)
        return f"{copy['why']} {copy['next']}".strip()

    def _prepend_transfer_review(
        self,
        due_reviews: list[ReviewQueueItem],
        lane_snapshot: LaneMemorySnapshot,
    ) -> list[ReviewQueueItem]:
        transfer = normalize_transfer_skill_state_record(lane_snapshot.workspace.get("latest_transfer_state"))
        review = lane_snapshot.workspace.get("latest_transfer_review")
        if not transfer or transfer.get("state") != "transferable" or not isinstance(review, dict):
            return due_reviews
        concept = str(review.get("concept") or transfer.get("concept") or "").strip()
        reason = str(review.get("reason") or transfer.get("next") or "").strip()
        if not concept or not reason:
            return due_reviews
        if any(item.concept.strip().casefold() == concept.casefold() and "transfer" in str(item.linked_context or "") for item in due_reviews):
            return due_reviews
        return [
            ReviewQueueItem(
                concept=concept,
                reason=reason,
                source="plan",
                severity="medium",
                linked_context="transfer",
                focus_area=str(review.get("focus_area") or concept),
                task_hint=str(review.get("task_hint") or transfer.get("why") or ""),
            ),
            *due_reviews,
        ]

    def _derive_due_reviews(
        self,
        plan: LearningPlan | None,
        lane_snapshot: LaneMemorySnapshot,
        weakness_records: list[WeaknessRecord],
    ) -> list[ReviewQueueItem]:
        due_reviews = self._review_scheduler.derive_due_reviews(
            plan=plan,
            lane_snapshot=lane_snapshot,
            weakness_records=weakness_records,
        )
        active_thread = lane_snapshot.workspace.get("active_thread")
        if not self._is_provider_recovery_thread(active_thread) or not isinstance(active_thread, dict):
            return due_reviews

        focus_area = str(active_thread.get("focus_area") or "").strip()
        next_step = str(active_thread.get("next_step") or "").strip()
        if not focus_area or not next_step:
            return due_reviews

        # Keep historical review evidence visible, but never enqueue the provider-recovery thread itself.
        return [
            item
            for item in due_reviews
            if not (
                item.source == "reflection"
                and item.concept.strip() == focus_area
                and next_step in str(item.linked_context or "")
            )
        ]

    def _derive_teaching_observations(
        self,
        plan: LearningPlan | None,
        lane_snapshot: LaneMemorySnapshot,
        weakness_records: list[WeaknessRecord],
        *,
        language_context: str | None = None,
    ) -> list[str]:
        observations: list[str] = []
        language_context = language_context or _memory_language_context(
            lane_snapshot.workspace,
            self._workspace_value(lane_snapshot, "summary"),
            self._workspace_value(lane_snapshot, "focus_area"),
        )
        active_thread = lane_snapshot.workspace.get("active_thread")
        if isinstance(active_thread, dict):
            thread_focus = str(active_thread.get("focus_area") or "").strip()
            thread_next_step = _strip_visible_next_step_prefix(active_thread.get("next_step") or "")
            thread_blocker = str(active_thread.get("blocker") or "").strip()
            thread_verified = str(active_thread.get("verified_result") or "").strip()
            thread_decision = str(active_thread.get("decision") or "").strip()
            thread_teaching_note = str(active_thread.get("teaching_note") or "").strip()
            thread_confidence = str(active_thread.get("confidence") or "").strip()
            thread_evidence = _normalize_text_items(active_thread.get("evidence"), limit=2)
            if self._is_provider_recovery_thread(active_thread):
                if thread_focus and thread_next_step:
                    observations.append(
                        _localized_memory_text(
                            f"Keep the coaching thread parked on '{thread_focus}' and resume it after this recovery step: {thread_next_step}",
                            f"先把这条教练主线稳在「{thread_focus}」上，先完成这个恢复动作，再回来继续：{thread_next_step}",
                            language_context or thread_focus or thread_next_step,
                        )
                    )
                elif thread_focus:
                    observations.append(
                        _localized_memory_text(
                            f"Keep the coaching thread parked on '{thread_focus}' until the provider path is trustworthy again.",
                            f"先把这条教练主线稳在「{thread_focus}」上，等 provider 链路恢复可信后再继续。",
                            language_context or thread_focus or thread_blocker,
                        )
                    )
                if thread_blocker:
                    observations.append(
                        _localized_memory_text(
                            f"Provider recovery blocker: {thread_blocker}",
                            f"当前需要先解开的 provider 恢复卡点：{thread_blocker}",
                            language_context or thread_blocker,
                        )
                    )
                return observations[:2]
            if thread_focus and thread_next_step:
                observations.append(
                    _localized_memory_text(
                        f"Active thread is still '{thread_focus}'. The next reply should continue this exact move: {thread_next_step}",
                        f"当前还在沿着「{thread_focus}」这条主线推进，下一轮也应该继续接这一步：{thread_next_step}",
                        language_context or thread_focus or thread_next_step,
                    )
                )
            if thread_blocker:
                observations.append(
                    _localized_memory_text(
                        f"Current blocker to respect: {thread_blocker}",
                        f"当前需要尊重的卡点：{thread_blocker}",
                        language_context or thread_blocker,
                    )
                )
            if thread_verified:
                observations.append(
                    _localized_memory_text(
                        f"Last verified result to build on: {thread_verified}",
                        f"上一轮已经验证过、可以继续接着走的结果：{thread_verified}",
                        language_context or thread_verified,
                    )
                )
            if thread_decision:
                observations.append(
                    _localized_memory_text(
                        f"Latest finalized decision to preserve: {thread_decision}",
                        f"要继续保留的最终决定：{thread_decision}",
                        language_context or thread_decision,
                    )
                )
            if thread_teaching_note:
                observations.append(
                    _localized_memory_text(
                        f"Teaching note to preserve: {thread_teaching_note}",
                        f"要继续保留的教学提示：{thread_teaching_note}",
                        language_context or thread_teaching_note,
                    )
                )
            if thread_confidence:
                observations.append(
                    _localized_memory_text(
                        f"Coach confidence signal: {thread_confidence}",
                        f"教练置信信号：{thread_confidence}",
                        language_context or thread_confidence,
                    )
                )
            if thread_evidence:
                observations.append(
                    _localized_memory_text(
                        f"Evidence trail to reuse: {'; '.join(thread_evidence)}",
                        f"可继续复用的证据链：{'; '.join(thread_evidence)}",
                        language_context or thread_evidence[0],
                    )
                )
        latest_focus_area = self._workspace_value(lane_snapshot, "focus_area")
        latest_next_step = _strip_visible_next_step_prefix(
            self._workspace_value(lane_snapshot, "next_step")
        )
        latest_review_note = str(lane_snapshot.workspace.get("latest_coach_review_note") or "").strip()
        latest_scenario = self._workspace_value(lane_snapshot, "scenario")
        latest_preference = lane_snapshot.preferences[0] if lane_snapshot.preferences else None
        latest_decision = lane_snapshot.decisions[0] if lane_snapshot.decisions else None

        if latest_focus_area and latest_next_step:
            observations.append(
                _localized_memory_text(
                    f"The last coach turn already narrowed the work to '{latest_focus_area}'. Keep going on that same line with: {latest_next_step}",
                    f"上一轮已经把范围压到「{latest_focus_area}」，这一轮继续沿着同一条主线推进：{latest_next_step}",
                    language_context or latest_focus_area or latest_next_step,
                )
            )
        elif latest_scenario and latest_next_step:
            observations.append(
                _localized_memory_text(
                    f"Latest {latest_scenario.replace('_', ' ')} turn already has a concrete next move; keep following it before expanding scope.",
                    "最近这一轮已经有了一个清楚的下一步，在它落地前先不要扩范围。",
                    language_context or latest_next_step or latest_scenario,
                )
            )

        if latest_review_note and not self._is_synthetic_bootstrap_review_text(latest_review_note):
            observations.append(
                _localized_memory_text(
                    f"Recent coaching friction to preserve: {latest_review_note}",
                    f"最近需要继续盯住的训练摩擦点：{latest_review_note}",
                    language_context or latest_review_note,
                )
            )
        if latest_preference:
            observations.append(
                _localized_memory_text(
                    f"Remembered learner preference: {latest_preference.key} = {latest_preference.value}.",
                    f"已记住你的偏好：{latest_preference.key} = {latest_preference.value}。",
                    language_context or latest_preference.value,
                )
            )
        if latest_decision:
            observations.append(
                _localized_memory_text(
                    f"Latest coaching decision to preserve: {latest_decision.decision}",
                    f"最近这条教练判断要继续保留：{latest_decision.decision}",
                    language_context or latest_decision.decision,
                )
            )

        active_stage = self._active_stage(plan)
        if active_stage:
            workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
            recovered_runtime = select_plan_runtime_for_scope(
                workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
                str(workspace.get("workspace_id") or "").strip(),
            )
            stage_label = live_coach_stage_label(
                plan=plan,
                runtime=recovered_runtime,
                existing=recovered_runtime,
                stage_title=active_stage.title,
            )
            if stage_label:
                observations.append(
                    _localized_memory_text(
                        f"Stay inside '{stage_label}' until one verifiable slice is complete.",
                        f"在拿到一个可验证结果之前，先别离开「{stage_label}」这个阶段。",
                        language_context or stage_label,
                    )
                )

        if weakness_records:
            concepts = ", ".join(record.concept for record in weakness_records[:2])
            observations.append(
                _localized_memory_text(
                    f"Repeated friction is clustering around {concepts}; keep the next step narrower than your first instinct.",
                    f"反复卡顿主要集中在 {concepts} 附近，这一轮下一步要比你第一反应再小一点。",
                    language_context or concepts,
                )
            )

        if lane_snapshot.reflections:
            observations.append(
                _localized_memory_text(
                    f"Recent reflection to reuse: {lane_snapshot.reflections[-1].summary}",
                    f"最近这条复盘值得继续拿来用：{lane_snapshot.reflections[-1].summary}",
                    language_context or lane_snapshot.reflections[-1].summary,
                )
            )

        if lane_snapshot.mastery:
            lowest = sorted(lane_snapshot.mastery, key=lambda item: item.score)[:1]
            if lowest:
                observations.append(
                    _localized_memory_text(
                        f"Keep revisiting {lowest[0].concept} through code, not only explanation.",
                        f"像「{lowest[0].concept}」这种薄弱概念，后面还要继续放回代码里练，不要只停在讲解上。",
                        language_context or lowest[0].concept,
                    )
                )

        if not observations:
            observations.append(
                _localized_memory_text(
                    "No repeated coaching pattern has solidified yet.",
                    "还没有形成特别稳定的训练模式，先继续沿着当前主线积累。",
                    language_context,
                )
            )

        return observations[:4]

    def _derive_recent_wins(
        self,
        plan: LearningPlan | None,
        resources: list[ResourceRecord],
        lane_snapshot: LaneMemorySnapshot,
    ) -> list[str]:
        wins: list[str] = []
        language_context = self._workspace_value(lane_snapshot, "summary") or self._workspace_value(
            lane_snapshot,
            "focus_area",
        )
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        toggles = self._workspace_memory_toggles(workspace)
        active_thread = lane_snapshot.workspace.get("active_thread")
        if isinstance(active_thread, dict):
            verified_result = str(active_thread.get("verified_result") or "").strip()
            if verified_result:
                wins.append(
                    _localized_memory_text(
                        f"Last verified result is still available as the next coaching anchor: {verified_result}",
                        f"上一次已经验证过的结果还在，可以直接作为下一轮继续推进的起点：{verified_result}",
                        language_context or verified_result,
                    )
                )
        latest_focus_area = self._workspace_value(lane_snapshot, "focus_area")
        latest_summary = self._workspace_value(lane_snapshot, "summary")
        latest_next_step = _strip_visible_next_step_prefix(
            self._workspace_value(lane_snapshot, "next_step")
        )
        latest_progress = lane_snapshot.progress[0] if lane_snapshot.progress else None

        if latest_focus_area and latest_next_step:
            wins.append(
                _localized_memory_text(
                    f"The latest coach turn already reduced '{latest_focus_area}' into a concrete next move you can act on now.",
                    f"上一轮已经把「{latest_focus_area}」压成了一个可以直接动手的下一步。",
                    language_context or latest_focus_area,
                )
            )
        elif latest_summary:
            wins.append(
                _localized_memory_text(
                    f"The coach already condensed the current thread into a usable summary: {latest_summary}",
                    f"教练已经把当前这条主线压成了一段可直接接续的摘要：{latest_summary}",
                    language_context or latest_summary,
                )
            )
        elif latest_progress:
            anchor = latest_progress.focus_area or latest_progress.lane
            wins.append(
                _localized_memory_text(
                    f"Trainer kept a reusable progress thread for {anchor}.",
                    f"教练已经为「{anchor}」保留了一条可继续接上的进度主线。",
                    language_context or anchor,
                )
            )

        active_stage = self._active_stage(plan)
        if active_stage:
            recovered_runtime = select_plan_runtime_for_scope(
                workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
                str(workspace.get("workspace_id") or "").strip(),
            )
            stage_label = live_coach_stage_label(
                plan=plan,
                runtime=recovered_runtime,
                existing=recovered_runtime,
                stage_title=active_stage.title,
            )
            if stage_label:
                wins.append(
                    _localized_memory_text(
                        f"You already have a live stage to work inside: {stage_label}.",
                        f"你已经有一个正在推进的训练阶段：{stage_label}。",
                        language_context or stage_label,
                    )
                )

        if resources and toggles["resources"]:
            wins.append(
                _localized_memory_text(
                    "Workspace resources are available for grounded follow-up guidance.",
                    "当前工作区资料已经可用，后续回复可以更稳地贴着资料和代码继续推进。",
                    language_context,
                )
            )

        if lane_snapshot.reflections and toggles["decisions"]:
            wins.append(
                _localized_memory_text(
                    "A reflection trail now exists for future coaching loops.",
                    "现在已经积累了复盘轨迹，后续教练可以继续沿着你的真实训练过程来带。",
                    language_context,
                )
            )

        if not wins:
            wins.append(
                _localized_memory_text(
                    "The training workspace is ready for the first focused implementation loop.",
                    "当前工作区已经准备好开始第一轮聚焦实现了。",
                    language_context,
                )
            )

        return wins[:3]

    def _derive_current_focus(
        self,
        plan: LearningPlan | None,
        recent_summary: str,
        lane_snapshot: LaneMemorySnapshot | None = None,
        *,
        language_context: str | None = None,
    ) -> str:
        language_context = language_context or _memory_language_context(
            lane_snapshot.workspace if lane_snapshot else {},
            recent_summary,
        )
        active_thread = lane_snapshot.workspace.get("active_thread") if lane_snapshot else None
        if isinstance(active_thread, dict):
            thread_focus = str(active_thread.get("focus_area") or "").strip()
            thread_scenario = str(active_thread.get("scenario") or "").strip()
            thread_next_step = _strip_visible_next_step_prefix(active_thread.get("next_step") or "")
            thread_blocker = str(active_thread.get("blocker") or "").strip()
            thread_verified = str(active_thread.get("verified_result") or "").strip()
            if thread_focus:
                if _focus_looks_like_request_sentence(thread_focus):
                    guided_lane_focus = _guided_lane_focus_label(
                        thread_scenario,
                        language_context or thread_focus or thread_next_step or thread_blocker,
                    )
                    if guided_lane_focus:
                        thread_focus = guided_lane_focus
                visible_thread_focus = _display_focus_label(
                    thread_focus,
                    language_context or thread_focus or thread_next_step or thread_blocker,
                )
                if self._is_provider_recovery_thread(active_thread):
                    return _localized_memory_text(
                        f"Current coaching focus: keep '{visible_thread_focus}' parked until the provider path preserves the original sentence. Next step: {thread_next_step}"
                        if thread_next_step
                        else f"Current coaching focus: keep '{visible_thread_focus}' parked until the provider path preserves the original sentence.",
                        f"当前聚焦：先把「{visible_thread_focus}」这条主线稳住，等 provider 链路能完整保留原句后再继续。下一步：{thread_next_step}"
                        if thread_next_step
                        else f"当前聚焦：先把「{visible_thread_focus}」这条主线稳住，等 provider 链路能完整保留原句后再继续。",
                        language_context or visible_thread_focus or thread_next_step or thread_blocker,
                    )
                focus_line = _localized_memory_text(
                    f"Current coaching focus: continue '{visible_thread_focus}' and do not open a new lane before this next move lands: {thread_next_step}"
                    if thread_next_step
                    else f"Current coaching focus: continue '{visible_thread_focus}' before widening scope.",
                    f"当前聚焦：先沿着「{visible_thread_focus}」这条主线继续推进，在这一步落地前先不要新开分支。下一步是：{thread_next_step}"
                    if thread_next_step
                    else f"当前聚焦：先沿着「{visible_thread_focus}」继续推进，再考虑扩展范围。",
                    language_context or visible_thread_focus or thread_next_step,
                )
                if thread_blocker:
                    focus_line += _localized_memory_text(
                        f" Current blocker: {thread_blocker}",
                        f" 当前卡点：{thread_blocker}",
                        language_context or thread_blocker,
                    )
                elif thread_verified:
                    focus_line += _localized_memory_text(
                        f" Last verified result: {thread_verified}",
                        f" 上一次已验证结果：{thread_verified}",
                        language_context or thread_verified,
                    )
                return focus_line
        workspace = lane_snapshot.workspace if lane_snapshot and isinstance(lane_snapshot.workspace, dict) else {}
        recovered = select_plan_runtime_for_scope(
            workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
            str(workspace.get("workspace_id") or "").strip(),
        )
        persist_chrome = live_plan_snapshot_persist_chrome(
            plan=plan,
            runtime=recovered,
            existing=recovered,
        )
        latest_focus_area = self._workspace_value(lane_snapshot, "focus_area") if lane_snapshot else ""
        latest_focus_area = live_coach_focus_area(
            plan=plan,
            runtime=recovered,
            existing=recovered,
            candidate=latest_focus_area,
        )
        latest_next_step = (
            _strip_visible_next_step_prefix(self._workspace_value(lane_snapshot, "next_step"))
            if lane_snapshot
            else ""
        )
        latest_summary = self._workspace_value(lane_snapshot, "summary") if lane_snapshot else ""
        latest_progress = lane_snapshot.progress[0] if lane_snapshot and lane_snapshot.progress else None
        if latest_focus_area:
            visible_latest_focus = _display_focus_label(
                latest_focus_area,
                language_context or latest_focus_area or latest_next_step or latest_summary or recent_summary,
            )
            detail = latest_next_step or latest_summary or recent_summary
            if detail:
                return _localized_memory_text(
                    f"Current coaching focus: stay with '{visible_latest_focus}' and keep the next loop attached to this latest move: {detail}",
                    f"当前聚焦：继续围绕「{visible_latest_focus}」推进，下一轮也先贴着这一步来做：{detail}",
                    language_context or visible_latest_focus or detail,
                )
            return _localized_memory_text(
                f"Current coaching focus: stay with '{visible_latest_focus}' until the learner lands one visible, verifiable step.",
                f"当前聚焦：继续围绕「{visible_latest_focus}」推进，先落下一个明确可验证的小结果。",
                language_context or visible_latest_focus,
            )
        if latest_progress:
            detail = latest_progress.next_step or latest_progress.summary
            anchor = latest_progress.focus_area or latest_progress.lane
            visible_anchor = _display_focus_label(
                anchor,
                language_context or anchor or detail,
            )
            return _localized_memory_text(
                f"Current coaching focus: continue the tracked {latest_progress.lane} lane around "
                f"'{visible_anchor}' and keep the next loop attached to: {detail}",
                f"当前聚焦：继续沿着已跟踪的「{visible_anchor}」主线推进，下一轮先接着这一步来做：{detail}",
                language_context or visible_anchor or detail,
            )

        live_focus = persist_chrome["focus"] or persist_chrome["stage_title"]
        if live_focus:
            return _localized_memory_text(
                f"Current coaching focus: stay inside '{live_focus}', land one visible slice, "
                "and keep the next reply tied to the exact patch you can verify.",
                f"当前聚焦：先在「{live_focus}」这个阶段里落下一个清楚的小切片，下一轮继续贴着你能验证的那段改动来推进。",
                language_context or live_focus,
            )
        if recent_summary:
            return _localized_memory_text(
                "Current coaching focus: keep following the learner's latest concrete thread, "
                f"especially this signal from the recent loop: {recent_summary}",
                f"当前聚焦：继续顺着你最近这条最具体的主线往前走，特别注意这条信号：{recent_summary}",
                language_context,
            )
        return _localized_memory_text(
            "Current coaching focus: reduce the work to one verifiable move, then keep the next turn attached to that result.",
            "当前聚焦：先把事情压成一个可验证的小动作，下一轮也继续贴着这个结果来推进。",
            language_context,
        )

    def _derive_review_rhythm(
        self,
        due_reviews: list[ReviewQueueItem],
        lane_snapshot: LaneMemorySnapshot,
    ) -> str:
        return self._review_scheduler.derive_review_rhythm(
            due_reviews=due_reviews,
            lane_snapshot=lane_snapshot,
        )

    def _is_synthetic_bootstrap_concept(self, concept: str | None) -> bool:
        return str(concept or "").strip().lower() in _SYNTHETIC_BOOTSTRAP_CONCEPTS

    def _is_synthetic_bootstrap_review_text(self, text: str | None) -> bool:
        normalized = str(text or "").strip().lower()
        return bool(normalized) and any(
            token in normalized for token in _SYNTHETIC_BOOTSTRAP_CONCEPTS
        )

    def _visible_weakness_records(
        self,
        weakness_records: list[WeaknessRecord],
    ) -> list[WeaknessRecord]:
        return [
            record
            for record in weakness_records
            if not self._is_synthetic_bootstrap_concept(record.concept)
        ]

    def _visible_due_reviews(
        self,
        due_reviews: list[ReviewQueueItem],
    ) -> list[ReviewQueueItem]:
        return [
            item
            for item in due_reviews
            if not self._is_synthetic_bootstrap_concept(item.concept)
        ]

    def _active_stage(self, plan: LearningPlan | None):
        if not plan:
            return None
        for stage in plan.stages:
            if stage.id == plan.current_stage_id or stage.status == "active":
                return stage
        return plan.stages[0] if plan.stages else None

    def _severity_label(self, severity: int) -> str:
        if severity >= 3:
            return "high"
        if severity == 2:
            return "medium"
        return "low"

    def _derive_coach_anchor(
        self,
        plan: LearningPlan | None,
        lane_snapshot: LaneMemorySnapshot,
    ) -> str:
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        recovered = select_plan_runtime_for_scope(
            workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
            str(workspace.get("workspace_id") or "").strip(),
        )
        persist_chrome = live_plan_snapshot_persist_chrome(
            plan=plan,
            runtime=recovered,
            existing=recovered,
        )
        latest_focus_area = live_coach_focus_area(
            plan=plan,
            runtime=recovered,
            existing=recovered,
            candidate=self._workspace_value(lane_snapshot, "focus_area"),
        )
        if latest_focus_area:
            return latest_focus_area
        if lane_snapshot.progress:
            latest_progress = lane_snapshot.progress[0]
            progress_focus = live_coach_focus_area(
                plan=plan,
                runtime=recovered,
                existing=recovered,
                candidate=latest_progress.focus_area.strip() or latest_progress.lane.strip(),
            )
            if progress_focus:
                return progress_focus
        if persist_chrome["focus"] or persist_chrome["stage_title"]:
            return persist_chrome["focus"] or persist_chrome["stage_title"]
        if lane_snapshot.mastery:
            return sorted(lane_snapshot.mastery, key=lambda item: item.score)[0].concept
        return "implementation"

    def _derive_lowest_mastery_concepts(self, lane_snapshot: LaneMemorySnapshot) -> list[str]:
        if not lane_snapshot.mastery:
            return []
        ranked = sorted(
            lane_snapshot.mastery,
            key=lambda item: (item.score, item.updated_at),
        )
        concepts: list[str] = []
        for item in ranked:
            concept = item.concept.strip()
            if concept and ":next-step" not in concept and concept not in concepts:
                concepts.append(concept)
            if len(concepts) == 3:
                break
        return concepts

    def _derive_pace_signal(
        self,
        plan: LearningPlan | None,
        due_reviews: list[ReviewQueueItem],
        lane_snapshot: LaneMemorySnapshot,
    ) -> str:
        if len(due_reviews) >= 3:
            return "gentle"
        if any(item.surface_mode == "due" and item.severity == "high" for item in due_reviews):
            return "gentle"
        if plan and plan.cadence and "8" in plan.cadence and not due_reviews:
            return "intensive"
        if lane_snapshot.session and len(lane_snapshot.session.recent_messages) >= 6 and not due_reviews:
            return "steady"
        return "steady"

    def _normalize_focus_area(self, focus_area: str | None) -> str | None:
        if not focus_area:
            return None
        cleaned = focus_area.strip()
        if not cleaned:
            return None
        if cleaned.lower().startswith("current coaching focus:"):
            return None
        if len(cleaned.split()) > 8:
            return None
        return cleaned

    def _top_actionable_weakness(self, weakness_records: list[WeaknessRecord]) -> str:
        for record in weakness_records:
            if not self._is_synthetic_bootstrap_concept(record.concept):
                return record.concept
        return ""

    def _preferred_preference(self, lane_snapshot: LaneMemorySnapshot) -> PreferenceRecord | None:
        if not getattr(lane_snapshot, "preferences", None):
            return None
        ignored_keys = {
            "focus_area",
            "memory_scope",
            "working_set_mode",
            "review_cadence",
            "review_reminder_mode",
            "response_language",
            "answer_mode",
        }
        for preference in lane_snapshot.preferences:
            if preference.key not in ignored_keys:
                return preference
        return lane_snapshot.preferences[0]

    def _personal_transfer_observation(self, lane_snapshot: LaneMemorySnapshot) -> str:
        language_context = self._workspace_value(lane_snapshot, "summary") or self._workspace_value(
            lane_snapshot,
            "focus_area",
        )
        current_focus = self._workspace_value(lane_snapshot, "focus_area").strip().lower()

        for progress in lane_snapshot.progress:
            anchor = (progress.focus_area or progress.lane).strip()
            if not anchor or anchor.lower() == current_focus:
                continue
            detail = progress.next_step.strip() or progress.summary.strip()
            if not detail:
                continue
            return _localized_memory_text(
                f"Carry forward a reusable lesson from '{anchor}': {detail}",
                f"个人长期记忆里还有一条可以迁移过来的经验，来自「{anchor}」：{detail}",
                language_context or anchor or detail,
            )

        for decision in lane_snapshot.decisions:
            topic = decision.topic.strip()
            if not topic or topic.lower() == current_focus:
                continue
            detail = decision.next_step.strip() or decision.decision.strip()
            if not detail:
                continue
            return _localized_memory_text(
                f"Keep a reusable judgment from '{topic}' available: {detail}",
                f"个人长期记忆里保留着一条可复用判断，来自「{topic}」：{detail}",
                language_context or topic or detail,
            )

        return ""

    def memory_evidence(self, workspace_id: str, *, limit: int = 5) -> list[str]:
        snapshot = self.snapshot(workspace_id)
        return self._build_memory_evidence(snapshot, limit=limit)

    def _build_memory_evidence(self, snapshot: MemorySnapshot, *, limit: int) -> list[str]:
        evidence: list[str] = []

        if snapshot.active_thread:
            if snapshot.active_thread.verified_result:
                evidence.append(
                    _localized_memory_text(
                        f"Last verified result: {snapshot.active_thread.verified_result}",
                        f"上次已经验证过的结果：{snapshot.active_thread.verified_result}",
                        snapshot.active_thread.verified_result,
                    )
                )
            if snapshot.active_thread.blocker:
                evidence.append(
                    _localized_memory_text(
                        f"Current blocker: {snapshot.active_thread.blocker}",
                        f"当前卡点：{snapshot.active_thread.blocker}",
                        snapshot.active_thread.blocker,
                    )
                )
            if snapshot.active_thread.decision:
                evidence.append(
                    _localized_memory_text(
                        f"Latest finalized decision: {snapshot.active_thread.decision}",
                        f"最新最终决策：{snapshot.active_thread.decision}",
                        snapshot.active_thread.decision,
                    )
                )
            if snapshot.active_thread.teaching_note:
                evidence.append(
                    _localized_memory_text(
                        f"Teaching note: {snapshot.active_thread.teaching_note}",
                        f"教学提示：{snapshot.active_thread.teaching_note}",
                        snapshot.active_thread.teaching_note,
                    )
                )
            if snapshot.active_thread.confidence:
                evidence.append(
                    _localized_memory_text(
                        f"Coach confidence: {snapshot.active_thread.confidence}",
                        f"教练置信信号：{snapshot.active_thread.confidence}",
                        snapshot.active_thread.confidence,
                    )
                )
            if snapshot.active_thread.evidence:
                joined_evidence = "; ".join(snapshot.active_thread.evidence[:2])
                evidence.append(
                    _localized_memory_text(
                        f"Evidence trail: {joined_evidence}",
                        f"证据链：{joined_evidence}",
                        joined_evidence,
                    )
                )
            if snapshot.active_thread.focus_area and snapshot.active_thread.next_step:
                evidence.append(
                    _localized_memory_text(
                        f"Continue {snapshot.active_thread.focus_area} with this next move: {snapshot.active_thread.next_step}",
                        f"继续沿着「{snapshot.active_thread.focus_area}」推进，下一步是：{snapshot.active_thread.next_step}",
                        snapshot.active_thread.summary or snapshot.active_thread.next_step,
                    )
                )
            elif snapshot.active_thread.summary:
                evidence.append(snapshot.active_thread.summary)

        if snapshot.current_focus:
            evidence.append(snapshot.current_focus)

        goal = (
            snapshot.profile.long_term_goal
            if snapshot.profile and snapshot.profile.long_term_goal
            else snapshot.profile.long_term_goals[0]
            if snapshot.profile and snapshot.profile.long_term_goals
            else ""
        )
        if goal:
            evidence.append(
                _localized_memory_text(
                    f"Long-term goal: {goal}",
                    f"长期目标：{goal}",
                    goal,
                )
            )

        if snapshot.recent_wins:
            evidence.extend(snapshot.recent_wins[:1])

        if snapshot.teaching_observations:
            evidence.extend(snapshot.teaching_observations[:1])

        if snapshot.coaching_adaptation and snapshot.coaching_adaptation.summary:
            evidence.append(snapshot.coaching_adaptation.summary)

        if snapshot.teaching_assets:
            first_asset = snapshot.teaching_assets[0]
            summary = first_asset.summary.strip() or first_asset.title.strip()
            if summary:
                evidence.append(
                    _localized_memory_text(
                        f"Reusable teaching asset: {first_asset.kind} - {summary}",
                        f"可复用教学资产：{first_asset.kind} - {summary}",
                        summary,
                    )
                )

        if snapshot.due_reviews:
            for item in snapshot.due_reviews[:1]:
                evidence.append(
                    _localized_memory_text(
                        f"Due review: {item.concept} - {item.reason}",
                        f"待回看：{item.concept} - {item.reason}",
                        item.reason or item.concept,
                    )
                )

        deduped: list[str] = []
        seen: set[str] = set()
        for item in evidence:
            normalized = item.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
            if len(deduped) >= limit:
                break
        return deduped

    def _context_pressure_from_lane(
        self,
        lane_snapshot: LaneMemorySnapshot,
        *,
        profile: UserProfile | dict[str, Any] | None = None,
        plan: LearningPlan | None = None,
        due_reviews: list[Any] | None = None,
        workspace_id: str = "",
    ):
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        scope_id = str(workspace_id or workspace.get("workspace_id") or "").strip()
        current_task = normalize_latest_current_task(
            workspace.get(CURRENT_TASK_KEY) or workspace.get("current_task") or workspace.get("currentTask"),
            scope_id,
        )
        affect_state = normalize_latest_affect_state(
            workspace.get(AFFECT_STATE_KEY) or workspace.get("affect_state") or workspace.get("affectState"),
            scope_id,
        )
        return derive_context_pressure(
            profile=profile if profile is not None else lane_snapshot.profile,
            workspace=workspace,
            plan=plan,
            plan_runtime=select_plan_runtime_for_pressure(
                workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
                scope_id,
            ),
            current_task=current_task,
            affect_state=affect_state,
            due_reviews=due_reviews,
            workspace_understanding=self._workspace_understanding_snapshot(lane_snapshot),
            session=lane_snapshot.session,
            preferences=list(getattr(lane_snapshot, "preferences", []) or []),
            workspace_id=scope_id,
        )

    def _derive_coaching_adaptation_profile(
        self,
        lane_snapshot: LaneMemorySnapshot,
        *,
        profile: UserProfile | None = None,
        plan: LearningPlan | None = None,
        due_reviews: list[Any] | None = None,
        workspace_id: str = "",
    ) -> CoachingAdaptationProfile | None:
        outcomes = list(getattr(lane_snapshot, "learning_outcomes", []) or [])
        signals = analyze_learning_evidence(outcomes)
        focus_anchor = self._workspace_value(lane_snapshot, "focus_area")
        language_context = self._workspace_value(lane_snapshot, "summary") or focus_anchor
        workspace = lane_snapshot.workspace if isinstance(lane_snapshot.workspace, dict) else {}
        transfer_record = normalize_transfer_skill_state_record(workspace.get("latest_transfer_state"))
        coach_defaults = workspace.get("coach_defaults")
        teaching_style = ""
        if isinstance(coach_defaults, dict):
            teaching_style = str(coach_defaults.get("teaching_style") or "")
        pressure = self._context_pressure_from_lane(
            lane_snapshot,
            profile=profile,
            plan=plan,
            due_reviews=due_reviews,
            workspace_id=workspace_id,
        )
        scope_id = str(workspace_id or workspace.get("workspace_id") or "").strip()
        persisted_task = normalize_latest_current_task(
            workspace.get(CURRENT_TASK_KEY) or workspace.get("current_task") or workspace.get("currentTask"),
            scope_id,
        )
        persisted_affect = normalize_latest_affect_state(
            workspace.get(AFFECT_STATE_KEY) or workspace.get("affect_state") or workspace.get("affectState"),
            scope_id,
        )
        persisted_plan_runtime = (
            None
            if plan is not None
            else select_plan_runtime_for_pressure(
                workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
                scope_id,
            )
        )
        has_outcomes = bool(outcomes)
        has_pressure = bool(
            persisted_task
            or persisted_affect
            or persisted_plan_runtime
            or pressure.time_budget != "normal"
            or pressure.task_urgency != "medium"
            or pressure.project_complexity != "moderate"
            or pressure.evidence
        )
        if not has_outcomes and not has_pressure:
            return None

        controls = resolve_pedagogy_controls(
            signals,
            transfer_scene_count=int((transfer_record or {}).get("scene_count") or 0),
            transfer_state=str((transfer_record or {}).get("state") or ""),
            user_preference=str(workspace.get("latest_user_feedback_kind") or ""),
            preferred_teaching_style=teaching_style,
            time_budget=pressure.time_budget,
            task_urgency=pressure.task_urgency,
            project_complexity=pressure.project_complexity,
            current_ability=str(workspace.get("current_ability") or ""),
            evidence_confidence=pedagogy_evidence_confidence(
                verified_success=bool(signals.verified_success),
                success_count=int(signals.success_count or 0),
                outcomes=outcomes,
            ),
        )

        latest_outcome_action = ""
        if outcomes:
            latest = outcomes[0]
            latest_outcome_action = str(
                getattr(latest, "action_type", "") or (latest.get("action_type") if isinstance(latest, dict) else "")
                or ""
            )
        current_scenario = self._workspace_value(lane_snapshot, "scenario") or latest_outcome_action
        preferred_strategy = self._preferred_strategy_record(
            lane_snapshot,
            scenario=current_scenario,
            focus_area=focus_anchor,
        )
        strategy_preference_applied = False
        challenge_level = controls.challenge_level
        hint_depth = controls.hint_depth
        review_urgency = controls.review_urgency
        explanation_mode = controls.explanation_mode
        next_step_bias = controls.next_step_bias
        evidence = list(signals.evidence)
        if preferred_strategy is not None and has_outcomes:
            (
                challenge_level,
                hint_depth,
                review_urgency,
                explanation_mode,
                next_step_bias,
            ), strategy_preference_applied = self._apply_preferred_strategy_bias(
                preferred_record=preferred_strategy,
                challenge_level=challenge_level,
                hint_depth=hint_depth,
                review_urgency=review_urgency,
                explanation_mode=explanation_mode,
                next_step_bias=next_step_bias,
                repeated_failure=signals.repeated_failure,
                abandoned=signals.abandoned,
            )
            if strategy_preference_applied:
                evidence.insert(
                    0,
                    self._strategy_preference_evidence(
                        preferred_strategy,
                        language_context=language_context,
                    ),
                )
                controls = refresh_controls_after_strategy(
                    controls,
                    challenge_level=challenge_level,
                    hint_depth=hint_depth,
                    review_urgency=review_urgency,
                    explanation_mode=explanation_mode,
                    next_step_bias=next_step_bias,
                )

        summary = ""
        if challenge_level == "lower":
            summary = _localized_memory_text(
                "Adaptive coaching: recent failures mean the next loop should shrink scope, deepen hints, and close one recovery check first.",
                "自适应教学：最近失败较多，下一轮应继续缩小范围、加深提示，并先收口一个恢复性验证。",
                language_context,
            )
        elif challenge_level == "raise":
            summary = _localized_memory_text(
                "Adaptive coaching: recent wins justify lighter hints, wider transfer, and a slightly stronger next challenge.",
                "自适应教学：最近已有连续进展，下一轮可以少给一点提示，更多强调迁移，并适度提高挑战。",
                language_context,
            )
        elif signals.concept_success:
            summary = _localized_memory_text(
                "Adaptive coaching: the learner recently explained the concept back correctly, so connect the next step to transfer in real code.",
                "自适应教学：最近概念反馈是正确的，下一轮应把理解迁回真实代码里做迁移练习。",
                language_context,
            )
        elif signals.success_count or signals.failure_count:
            summary = _localized_memory_text(
                "Adaptive coaching: keep the next step grounded in the latest outcome instead of reopening a broader lane.",
                "自适应教学：下一轮继续贴着最近的结果推进，不要重新打开更宽的话题分支。",
                language_context,
            )
        if strategy_preference_applied and preferred_strategy is not None:
            strategy_summary = self._strategy_preference_evidence(
                preferred_strategy,
                language_context=language_context,
            )
            summary = f"{summary} {strategy_summary}".strip() if summary else strategy_summary

        if not has_outcomes and has_pressure:
            for item in pressure.evidence:
                if item and item not in evidence:
                    evidence.append(item)
                if len(evidence) >= 4:
                    break
            if persisted_affect is not None:
                evidence.append(f"affect_urgency:{persisted_affect.get('urgency_level') or pressure.task_urgency}")
            if persisted_task is not None:
                task_label = str(persisted_task.get("title") or persisted_task.get("id") or "current task").strip()
                if task_label:
                    evidence.append(f"current_task:{task_label}")
            evidence = evidence[:4]
            if not summary:
                if pressure.task_urgency == "high" or pressure.time_budget == "tight" or pressure.project_complexity == "complex":
                    summary = _localized_memory_text(
                        "Adaptive coaching: keep the next slice short and stay on this project. No learning outcome yet, so this is not global mastery.",
                        "自适应教学：先把下一步收短，停在当前项目。还没有学习结果，所以这不是全局掌握。",
                        language_context,
                    )
                else:
                    summary = _localized_memory_text(
                        "Adaptive coaching: next step follows current time, urgency, and project scope. No learning outcome yet.",
                        "自适应教学：下一步先跟着当前的时间、紧迫度和项目范围走。还没有学习结果。",
                        language_context,
                    )

        if not summary and not evidence:
            return None

        return CoachingAdaptationProfile(
            **profile_kwargs_from_controls(controls, summary=summary, evidence=evidence)
        )

    def _summarize_preferences(self, lane_snapshot: LaneMemorySnapshot) -> str:
        latest = self._preferred_preference(lane_snapshot)
        if latest is None:
            return ""
        language_context = self._workspace_value(lane_snapshot, "summary") or latest.value
        return _localized_memory_text(
            f"Keep honoring the remembered preference {latest.key} = {latest.value}.",
            f"继续遵守已经记住的偏好：{latest.key} = {latest.value}。",
            language_context,
        )

    def _summarize_decisions(self, lane_snapshot: LaneMemorySnapshot) -> str:
        if not getattr(lane_snapshot, "decisions", None):
            return ""
        latest = lane_snapshot.decisions[0]
        language_context = self._workspace_value(lane_snapshot, "summary") or latest.decision
        return _localized_memory_text(
            f"Trainer retained a reusable coaching decision on {latest.topic}.",
            f"教练已经保留了一条可复用的判断，主题是：{latest.topic}。",
            language_context,
        )

    def _summarize_goal(self, goal: str, lane_snapshot: LaneMemorySnapshot) -> str:
        cleaned_goal = goal.strip()
        if not cleaned_goal:
            return ""
        language_context = self._workspace_value(lane_snapshot, "summary") or cleaned_goal
        return _localized_memory_text(
            f"Long-term goal still in view: {cleaned_goal}.",
            f"长期目标仍然在前面：{cleaned_goal}。",
            language_context,
        )

    def _summarize_latest_turn(self, lane_snapshot: LaneMemorySnapshot) -> str:
        latest_review_note = str(lane_snapshot.workspace.get("latest_coach_review_note") or "").strip()
        latest_next_step = _strip_visible_next_step_prefix(
            self._workspace_value(lane_snapshot, "next_step")
        )
        latest_focus_area = self._workspace_value(lane_snapshot, "focus_area")
        latest_scenario = self._workspace_value(lane_snapshot, "scenario")
        language_context = (
            self._workspace_value(lane_snapshot, "summary")
            or latest_review_note
            or latest_next_step
            or latest_focus_area
            or latest_scenario
        )
        if latest_review_note:
            return _localized_memory_text(
                f"Recent coaching friction to preserve: {latest_review_note}",
                f"最近需要继续盯住的训练摩擦点：{latest_review_note}",
                language_context,
            )
        if latest_focus_area and latest_next_step:
            return _localized_memory_text(
                f"The last coach turn already narrowed the work to '{latest_focus_area}'. Keep going on that same line and continue with: {latest_next_step}",
                f"上一轮已经把范围压到「{latest_focus_area}」，这一轮就沿着同一条主线继续：{latest_next_step}",
                language_context,
            )
        if latest_scenario and latest_next_step:
            return _localized_memory_text(
                f"Latest {latest_scenario.replace('_', ' ')} turn already has a concrete next move; keep following it before expanding scope.",
                "最近这一轮已经有了一个清楚的下一步，在它落地前先不要扩范围。",
                language_context,
            )
        return ""

    def _onboarding_blocker_summary(self, lane_snapshot: LaneMemorySnapshot) -> str:
        blocker = ""
        for key in ("current_blocker", "project_context"):
            candidate = next(
                (
                    item.value
                    for item in getattr(lane_snapshot, "preferences", [])
                    if item.key == key and str(item.value).strip()
                ),
                "",
            )
            if candidate:
                blocker = str(candidate).strip()
                break
        if not blocker:
            return ""
        language_context = self._workspace_value(lane_snapshot, "summary") or blocker
        return _localized_memory_text(
            f"Onboarding anchor still matters: {blocker}",
            f"首轮建联里提到的关键锚点仍然重要：{blocker}",
            language_context,
        )

    def _summarize_teaching_signal(self, lane_snapshot: LaneMemorySnapshot) -> str:
        if not getattr(lane_snapshot, "teaching_signals", None):
            return ""
        latest = lane_snapshot.teaching_signals[0]
        signal = latest.signal.strip()
        if not signal:
            return ""
        language_context = self._workspace_value(lane_snapshot, "summary") or signal
        focus = latest.source_focus.strip()
        if focus:
            return _localized_memory_text(
                f"Reusable teaching signal from '{focus}': {signal}",
                f"从「{focus}」这条主线里沉淀出一条可迁移的教学信号：{signal}",
                language_context,
            )
        return _localized_memory_text(
            f"Reusable teaching signal: {signal}",
            f"可迁移的教学信号：{signal}",
            language_context,
        )

    def _summarize_weakness_patterns(self, lane_snapshot: LaneMemorySnapshot) -> str:
        recurring = [
            item
            for item in getattr(lane_snapshot, "weaknesses", [])
            if item.recurrence_count >= 2
            and not self._is_synthetic_bootstrap_concept(item.concept)
        ]
        if not recurring:
            return ""
        recurring.sort(
            key=lambda item: (
                -item.recurrence_count,
                -item.severity,
                item.updated_at,
            ),
            reverse=False,
        )
        top = recurring[0]
        language_context = self._workspace_value(lane_snapshot, "summary") or top.reason or top.concept
        return _localized_memory_text(
            f"Recurring blocker pattern: {top.concept} has surfaced {top.recurrence_count} times. Latest example: {top.latest_example or top.reason}",
            f"稳定错误模式：{top.concept} 已经反复出现 {top.recurrence_count} 次。最近一次表现是：{top.latest_example or top.reason}",
            language_context,
        )

    @staticmethod
    def _is_provider_recovery_thread(
        active_thread: ActiveThreadSnapshot | dict[str, Any] | None,
    ) -> bool:
        if active_thread is None:
            return False
        if isinstance(active_thread, dict):
            recovery_state = str(active_thread.get("recovery_state") or "").strip().lower()
            blocker = str(active_thread.get("blocker") or "").strip().lower()
            next_step = str(active_thread.get("next_step") or "").strip().lower()
            teaching_note = str(active_thread.get("teaching_note") or "").strip().lower()
        else:
            recovery_state = ""
            blocker = str(active_thread.blocker or "").strip().lower()
            next_step = str(active_thread.next_step or "").strip().lower()
            teaching_note = str(active_thread.teaching_note or "").strip().lower()
        if recovery_state == "provider_or_local":
            return True
        combined = " ".join(part for part in (blocker, next_step, teaching_note) if part)
        return "provider" in combined and (
            "gateway" in combined
            or "question mark" in combined
            or "question marks" in combined
            or "english" in combined
            or "问号" in combined
            or "原句" in combined
        )

    def _summarize_progress(self, lane_snapshot: LaneMemorySnapshot) -> str:
        active_thread = lane_snapshot.workspace.get("active_thread")
        if isinstance(active_thread, dict):
            thread_verified = str(active_thread.get("verified_result") or "").strip()
            thread_blocker = str(active_thread.get("blocker") or "").strip()
            thread_focus = str(active_thread.get("focus_area") or "").strip()
            thread_next_step = _strip_visible_next_step_prefix(active_thread.get("next_step") or "")
            language_context = (
                self._workspace_value(lane_snapshot, "summary")
                or thread_verified
                or thread_blocker
                or thread_next_step
                or thread_focus
            )
            if thread_verified and thread_next_step:
                return _localized_memory_text(
                    f"Build from the verified result '{thread_verified}' and continue with: {thread_next_step}",
                    f"基于已经验证过的结果「{thread_verified}」继续推进，下一步是：{thread_next_step}",
                    language_context,
                )
            if thread_blocker and thread_next_step:
                return _localized_memory_text(
                    f"Current blocker is '{thread_blocker}'. Resolve it with: {thread_next_step}",
                    f"当前卡点是「{thread_blocker}」，先用这一步把它解开：{thread_next_step}",
                    language_context,
                )
            if thread_next_step:
                return _localized_memory_text(
                    f"Active thread next step: {thread_next_step}",
                    f"当前主线的下一步是：{thread_next_step}",
                    language_context,
                )
        if not getattr(lane_snapshot, "progress", None):
            return ""
        latest = lane_snapshot.progress[0]
        latest_next_step = _strip_visible_next_step_prefix(latest.next_step)
        language_context = self._workspace_value(lane_snapshot, "summary") or latest.summary or latest_next_step
        if latest_next_step:
            return _localized_memory_text(
                f"Latest saved progress: {latest_next_step}",
                f"最近记录下来的进度下一步是：{latest_next_step}",
                language_context or latest_next_step,
            )
        if latest.summary:
            return _localized_memory_text(
                f"Latest saved progress: {latest.summary}",
                f"最近记录下来的进度摘要是：{latest.summary}",
                language_context,
            )
        return ""

    def _active_thread_snapshot(
        self,
        lane_snapshot: LaneMemorySnapshot | None,
    ) -> ActiveThreadSnapshot | None:
        if lane_snapshot is None:
            return None
        candidate = lane_snapshot.workspace.get("active_thread")
        if not isinstance(candidate, dict):
            return None

        def _normalized(key: str) -> str:
            value = str(candidate.get(key) or "").strip()
            if key == "next_step":
                return _strip_visible_next_step_prefix(value)
            return value

        if not any(
            _normalized(field)
            for field in ("focus_area", "summary", "next_step", "blocker", "verified_result", "decision", "teaching_note", "confidence")
        ):
            return None
        evidence = _normalize_text_items(candidate.get("evidence"), limit=4)
        return ActiveThreadSnapshot(
            scenario=_normalized("scenario"),
            focus_area=_normalized("focus_area"),
            summary=_normalized("summary"),
            next_step=_normalized("next_step"),
            blocker=_normalized("blocker"),
            verified_result=_normalized("verified_result"),
            decision=_normalized("decision"),
            teaching_note=_normalized("teaching_note"),
            confidence=_normalized("confidence"),
            evidence=evidence,
            updated_at=_normalized("updated_at"),
        )

    def _workspace_understanding_snapshot(
        self,
        lane_snapshot: LaneMemorySnapshot | None,
    ) -> WorkspaceUnderstandingSnapshot | None:
        if lane_snapshot is None:
            return None
        candidate = lane_snapshot.workspace.get("workspace_understanding")
        if not isinstance(candidate, dict):
            return None
        try:
            snapshot = WorkspaceUnderstandingSnapshot.model_validate(candidate)
        except Exception:
            return None
        if not (
            snapshot.repo_summary
            or snapshot.entry_points
            or snapshot.feature_lanes
            or snapshot.risk_zones
            or snapshot.training_opportunities
            or snapshot.resource_brief
            or snapshot.first_look_summary is not None
        ):
            return None
        return snapshot

    def _workspace_value(self, lane_snapshot: LaneMemorySnapshot, field: str) -> str:
        preferred = str(lane_snapshot.workspace.get(f"latest_coach_{field}") or "").strip()
        if preferred:
            return preferred
        return str(lane_snapshot.workspace.get(f"latest_turn_{field}") or "").strip()
