from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..core.models import TeachingKnowledgeAsset


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class MemoryDocument:
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    vector: list[float] | None = None


@dataclass(slots=True)
class SearchHit:
    document: MemoryDocument
    score: float


@dataclass(slots=True)
class SemanticCollectionInfo:
    backend: str
    collection_name: str
    document_count: int
    path: str | None = None


@dataclass(slots=True)
class MasteryRecord:
    concept: str
    score: float
    confidence: float
    state: str = "learning"
    retrievability: float = 0.0
    due_date: datetime | None = None
    updated_at: datetime = field(default_factory=utc_now)
    next_review_at: datetime | None = None


@dataclass(slots=True)
class WeaknessRecord:
    concept: str
    reason: str
    severity: int = 1
    recurrence_count: int = 1
    latest_example: str = ""
    last_seen_context: str = ""
    updated_at: datetime = field(default_factory=utc_now)
    next_review_at: datetime | None = None


@dataclass(slots=True)
class ReflectionRecord:
    task_id: str
    summary: str
    action_items: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class PreferenceRecord:
    key: str
    value: str
    source: str = "derived"
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class DecisionRecord:
    topic: str
    decision: str
    rationale: str = ""
    next_step: str = ""
    source: str = "coach"
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class ProgressRecord:
    lane: str
    focus_area: str
    summary: str
    next_step: str
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class SessionSummary:
    session_id: str
    rolling_summary: str = ""
    recent_messages: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    active_focus_area: str = ""
    last_scenario: str = ""
    latest_next_step: str = ""
    blocker: str = ""
    verified_result: str = ""
    teaching_signal: str = ""
    decision: str = ""
    teaching_note: str = ""
    confidence: str = ""
    evidence: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class TeachingSignalRecord:
    key: str
    signal: str
    source_focus: str = ""
    scenario: str = ""
    source: str = "coach"
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class UserFeedbackRecord:
    kind: str
    message: str
    focus_area: str = ""
    scenario: str = ""
    training_card_id: str = ""
    plan_id: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class LearningOutcomeRecord:
    concept: str
    outcome: str
    summary: str = ""
    checks: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    repetition_count: int = 1
    action_type: str = ""
    verified_by_evaluator: bool = False
    verified_result: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class TeachingStrategyEffectivenessRecord:
    key: str
    scenario: str
    focus_area: str = ""
    challenge_level: str = "steady"
    hint_depth: str = "guided"
    review_urgency: str = "normal"
    explanation_mode: str = "grounded"
    next_step_bias: str = "steady"
    success_count: int = 0
    failure_count: int = 0
    total_count: int = 0
    last_outcome: str = ""
    last_summary: str = ""
    last_verified_result: str = ""
    last_updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class MemorySnapshot:
    profile: dict[str, Any] = field(default_factory=dict)
    workspace: dict[str, Any] = field(default_factory=dict)
    mastery: list[MasteryRecord] = field(default_factory=list)
    weaknesses: list[WeaknessRecord] = field(default_factory=list)
    reflections: list[ReflectionRecord] = field(default_factory=list)
    preferences: list[PreferenceRecord] = field(default_factory=list)
    decisions: list[DecisionRecord] = field(default_factory=list)
    progress: list[ProgressRecord] = field(default_factory=list)
    teaching_signals: list[TeachingSignalRecord] = field(default_factory=list)
    user_feedback: list[UserFeedbackRecord] = field(default_factory=list)
    learning_outcomes: list[LearningOutcomeRecord] = field(default_factory=list)
    teaching_strategy_effectiveness: list[TeachingStrategyEffectivenessRecord] = field(default_factory=list)
    teaching_assets: list[TeachingKnowledgeAsset] = field(default_factory=list)
    session: SessionSummary | None = None
