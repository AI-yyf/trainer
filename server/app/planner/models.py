from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from app.core.models import ReviewQueueItem
from app.memory.models import MasteryRecord, WeaknessRecord
from app.resources.models import ResourceRecord


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass(slots=True)
class PlanPhase:
    id: str
    title: str
    objective: str
    concepts: list[str]
    success_criteria: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        title: str,
        objective: str,
        concepts: list[str],
        success_criteria: list[str] | None = None,
    ) -> "PlanPhase":
        return cls(
            id=f"phase_{uuid4().hex}",
            title=title,
            objective=objective,
            concepts=concepts,
            success_criteria=list(success_criteria or []),
        )


@dataclass(slots=True)
class LearningPlan:
    id: str
    title: str
    objective: str
    weekly_hours: int
    direct_answer_policy: str
    teaching_style: str
    phases: list[PlanPhase]
    frozen: bool = False
    current_phase_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        *,
        title: str,
        objective: str,
        weekly_hours: int,
        direct_answer_policy: str,
        teaching_style: str,
        phases: list[PlanPhase],
        metadata: dict[str, Any] | None = None,
    ) -> "LearningPlan":
        return cls(
            id=f"plan_{uuid4().hex}",
            title=title,
            objective=objective,
            weekly_hours=weekly_hours,
            direct_answer_policy=direct_answer_policy,
            teaching_style=teaching_style,
            phases=phases,
            current_phase_id=phases[0].id if phases else None,
            metadata=dict(metadata or {}),
        )


@dataclass(slots=True)
class NextTaskRecommendation:
    task_id: str
    title: str
    prompt: str
    concepts: list[str]
    resource_ids: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    verification_hints: list[str] = field(default_factory=list)
    difficulty: TaskDifficulty = TaskDifficulty.EASY
    reason: str = ""
    review: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NextTaskContext:
    plan: LearningPlan
    mastery: list[MasteryRecord] = field(default_factory=list)
    weaknesses: list[WeaknessRecord] = field(default_factory=list)
    due_reviews: list[ReviewQueueItem] = field(default_factory=list)
    resources: list[ResourceRecord] = field(default_factory=list)
    recent_attempts: list[dict[str, Any]] = field(default_factory=list)
    session_summary: str | None = None
    focus_override: str | None = None
