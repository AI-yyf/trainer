"""One read projection for the learner model.

Coach, Plan, Training and Review all need the same facts about one workspace:

* Profile — background, habits and explicit teaching preferences.
* Goal — the one active capability focus, if any.
* Memory — current context, active thread, weaknesses, wins and review rhythm.
* Mastery — the skill projection, or ``insufficient_evidence`` when absent.
* Evidence — UnifiedEvidence from attempts, handoff and memory.
* Review — FSRS due state and queue items.

This module is read-only. Each source service owns its writes; the projection
never mutates a profile, goal, memory, evidence or schedule. Workspace scope is
explicit on every read, so a projection for A cannot contain B's facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .core.models import GoalSession, MemorySnapshot, UserProfile, utc_now_iso

if TYPE_CHECKING:
    from .db.repository import TrainerRepository
    from .evidence.contract import UnifiedEvidence
    from .goal.service import GoalService
    from .memory.service import MemoryService
    from .training.attempt_store import AttemptStore

FactConfidence = Literal["known", "unknown", "insufficient_evidence"]

STATE_OWNERSHIP: dict[str, str] = {
    "profile": "MemoryService.record_profile / TrainerRepository (write); projection reads",
    "goal": "GoalService (write); projection reads the current GoalSession",
    "memory": "MemoryService (write); projection reads a workspace-scoped snapshot",
    "mastery": "AttemptStore + UnifiedEvidence projection (write); projection reads only",
    "evidence": "AttemptStore / training handoff / memory evidence queue (write); projection reads",
    "review": "ReviewScheduler + FSRS training state (write); projection reads due state",
}


@dataclass(slots=True)
class FactEnvelope:
    value: Any
    source: str
    confidence: FactConfidence
    updated_at: str
    scope: str


@dataclass(slots=True)
class LearnerStateSnapshot:
    workspace_id: str
    generated_at: str
    profile: FactEnvelope
    goal: FactEnvelope
    memory: FactEnvelope
    mastery: FactEnvelope
    evidence: FactEnvelope
    review: FactEnvelope
    memory_snapshot: MemorySnapshot = field(repr=False)
    evidence_items: list["UnifiedEvidence"] = field(default_factory=list, repr=False)
    ownership: dict[str, str] = field(default_factory=lambda: dict(STATE_OWNERSHIP))

    def to_payload(self) -> dict[str, Any]:
        memory = self.memory.value
        mastery = self.mastery.value
        review = self.review.value
        return {
            "workspace_id": self.workspace_id,
            "generated_at": self.generated_at,
            "schema_version": 1,
            "ownership": dict(self.ownership),
            "profile": {
                "confidence": self.profile.confidence,
                "source": self.profile.source,
                "updated_at": self.profile.updated_at,
                "value": self.profile.value.model_dump(mode="json")
                if isinstance(self.profile.value, UserProfile)
                else None,
            },
            "goal": {
                "confidence": self.goal.confidence,
                "source": self.goal.source,
                "updated_at": self.goal.updated_at,
                "value": self.goal.value.model_dump(mode="json", by_alias=True)
                if isinstance(self.goal.value, GoalSession)
                else None,
            },
            "memory": {
                "confidence": self.memory.confidence,
                "source": self.memory.source,
                "updated_at": self.memory.updated_at,
                "current_focus": memory.get("current_focus", ""),
                "active_thread": memory.get("active_thread"),
                "top_weakness": memory.get("top_weakness", ""),
                "recent_wins": memory.get("recent_wins", []),
                "weaknesses": memory.get("weaknesses", []),
                "recent_summary": memory.get("recent_summary", ""),
                "review_rhythm": memory.get("review_rhythm", ""),
                "due_review_count": memory.get("due_review_count", 0),
            },
            "mastery": {
                "confidence": self.mastery.confidence,
                "source": self.mastery.source,
                "updated_at": self.mastery.updated_at,
                "dimensions": mastery.get("dimensions", {}),
                "lowest_mastery_concepts": mastery.get("lowest_mastery_concepts", []),
                "weaknesses": mastery.get("weaknesses", []),
            },
            "evidence": {
                "confidence": self.evidence.confidence,
                "source": self.evidence.source,
                "updated_at": self.evidence.updated_at,
                "total": len(self.evidence_items),
                "items": [item.model_dump(by_alias=True) for item in self.evidence_items],
            },
            "review": {
                "confidence": self.review.confidence,
                "source": self.review.source,
                "updated_at": self.review.updated_at,
                "due_count": review.get("due_count", 0),
                "due_items": review.get("due_items", []),
                "summary": review.get("summary", ""),
            },
            "limitations": [
                "Read-only projection: surfaces must not persist changes through this object.",
                "Missing profile/goal/mastery/evidence is reported as unknown or insufficient_evidence, never fabricated.",
            ],
        }


def collect_unified_evidence(
    *,
    memory_service: "MemoryService | None",
    attempt_store: "AttemptStore | None",
    workspace_id: str,
    limit: int = 50,
) -> list["UnifiedEvidence"]:
    """Collect the one evidence list used by memory/learner reads."""

    # Imported lazily: evidence.contract reaches training.handoff, which is
    # imported by memory.service; importing it at module load creates a cycle
    # in the bundled sidecar.
    from .evidence.contract import (
        evidence_from_attempt,
        evidence_from_handoff,
        evidence_from_memory,
        finalize_unified_evidence,
    )


    safe_limit = max(1, min(limit, 200))
    records: list[UnifiedEvidence] = []
    if attempt_store is not None:
        for item in attempt_store.list_workspace_evidence(
            workspace_id,
            limit=max(safe_limit * 2, 50),
        ):
            records.append(evidence_from_attempt(item, workspace_id=workspace_id))
    if memory_service is not None:
        handoff_id, handoff_records = memory_service.latest_handoff_evidence(workspace_id)
        for item in handoff_records:
            records.append(
                evidence_from_handoff(
                    item,
                    workspace_id=workspace_id,
                    handoff_id=handoff_id,
                )
            )
        queue = memory_service.evidence_queue(workspace_id)
        seen_memory_ids: set[str] = set()
        for item in (
            *queue.pending,
            *queue.deferred,
            *queue.adopted,
            *queue.rejected,
            *queue.history,
        ):
            if item.id in seen_memory_ids:
                continue
            seen_memory_ids.add(item.id)
            records.append(evidence_from_memory(item))
    return finalize_unified_evidence(records, limit=safe_limit)


def _scope(workspace_id: str) -> str:
    scope = str(workspace_id or "").strip()
    if not scope:
        raise ValueError("workspace_id_required")
    return scope


class LearnerStateService:
    """Workspace-scoped read facade over the existing owner services."""

    def __init__(
        self,
        repository: "TrainerRepository",
        memory_service: "MemoryService",
        goal_service: "GoalService",
        attempt_store: "AttemptStore | None" = None,
    ) -> None:
        self.repository = repository
        self.memory_service = memory_service
        self.goal_service = goal_service
        self.attempt_store = attempt_store

    def profile(self, workspace_id: str) -> UserProfile | None:
        """Read the profile fact without collecting the heavier evidence list."""

        return self.repository.get_profile(_scope(workspace_id))

    def snapshot(self, workspace_id: str, *, evidence_limit: int = 50) -> LearnerStateSnapshot:
        scope = _scope(workspace_id)
        now = utc_now_iso()
        profile = self.repository.get_profile(scope)
        goal = self.goal_service.current(scope)
        memory_snapshot = self.memory_service.snapshot(scope)
        workspace = memory_snapshot.workspace if isinstance(memory_snapshot.workspace, dict) else {}
        projection = workspace.get("training_skill_projection")
        dimensions = (
            projection.get("dimensions")
            if isinstance(projection, dict) and isinstance(projection.get("dimensions"), dict)
            else {}
        )
        evidence_items = collect_unified_evidence(
            memory_service=self.memory_service,
            attempt_store=self.attempt_store,
            workspace_id=scope,
            limit=evidence_limit,
        )
        due_items = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
            for item in (memory_snapshot.due_reviews or [])[:20]
        ]
        memory_value = {
            "current_focus": memory_snapshot.current_focus,
            "active_thread": (
                memory_snapshot.active_thread.model_dump(mode="json")
                if memory_snapshot.active_thread is not None
                else None
            ),
            "top_weakness": memory_snapshot.top_weakness,
            "recent_wins": list(memory_snapshot.recent_wins or []),
            "weaknesses": list(memory_snapshot.weaknesses or []),
            "recent_summary": memory_snapshot.recent_summary,
            "review_rhythm": memory_snapshot.review_rhythm,
            "due_review_count": memory_snapshot.due_review_count,
        }
        return LearnerStateSnapshot(
            workspace_id=scope,
            generated_at=now,
            profile=FactEnvelope(
                value=profile,
                source="TrainerRepository.get_profile",
                confidence="known" if profile is not None else "unknown",
                updated_at=now,
                scope=scope,
            ),
            goal=FactEnvelope(
                value=goal,
                source="GoalService.current",
                confidence="known" if goal is not None else "unknown",
                updated_at=goal.updated_at if goal is not None else now,
                scope=scope,
            ),
            memory=FactEnvelope(
                value=memory_value,
                source="MemoryService.snapshot",
                confidence="known",
                updated_at=now,
                scope=scope,
            ),
            mastery=FactEnvelope(
                value={
                    "dimensions": dimensions,
                    "lowest_mastery_concepts": list(memory_snapshot.lowest_mastery_concepts or []),
                    "weaknesses": list(memory_snapshot.weaknesses or []),
                },
                source="AttemptStore + UnifiedEvidence projection",
                confidence="known" if dimensions else "insufficient_evidence",
                updated_at=now,
                scope=scope,
            ),
            evidence=FactEnvelope(
                value=evidence_items,
                source="unified evidence (attempt/handoff/memory)",
                confidence="known" if evidence_items else "insufficient_evidence",
                updated_at=now,
                scope=scope,
            ),
            review=FactEnvelope(
                value={
                    "due_count": memory_snapshot.due_review_count,
                    "due_items": due_items,
                    "summary": memory_snapshot.review_rhythm,
                },
                source="ReviewScheduler + FSRS",
                confidence="known",
                updated_at=now,
                scope=scope,
            ),
            memory_snapshot=memory_snapshot,
            evidence_items=evidence_items,
        )


def learner_profile(runtime: object, workspace_id: str) -> UserProfile | None:
    """Return the profile fact from the unified projection, with a safe fallback."""

    service = getattr(runtime, "learner_state_service", None)
    if isinstance(service, LearnerStateService):
        return service.profile(workspace_id)
    repository = getattr(runtime, "repository", None)
    if repository is not None and hasattr(repository, "get_profile"):
        return repository.get_profile(workspace_id)
    raise ValueError("learner_profile_unavailable")


def learner_memory_snapshot(runtime: object, workspace_id: str) -> MemorySnapshot:
    """Return the memory fact from the unified projection, with a safe fallback."""

    service = getattr(runtime, "learner_state_service", None)
    if isinstance(service, LearnerStateService):
        return service.snapshot(workspace_id).memory_snapshot
    memory_service = getattr(runtime, "memory_service", None)
    if memory_service is not None and hasattr(memory_service, "snapshot"):
        return memory_service.snapshot(workspace_id)
    raise ValueError("learner_memory_unavailable")
