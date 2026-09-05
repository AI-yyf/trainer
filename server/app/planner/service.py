from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from ..core.models import (
    EvidenceAdoptResponse,
    EvidenceItem,
    PlanGenerateRequest,
    PlanStage,
    PlanUpdateRequest,
    ReviewQueueItem,
    SubPlan,
    UserProfile,
)
from ..core.models import (
    LearningPlan as ApiLearningPlan,
)
from ..core.models import (
    MemorySnapshot as ApiMemorySnapshot,
)
from ..core.models import (
    TaskSpec as ApiTaskSpec,
)
from ..db.repository import TrainerRepository
from ..memory.models import MasteryRecord, WeaknessRecord, utc_now
from ..memory.workspace_recovery import (
    formal_plan_is_live_runtime_identity,
    leftover_formal_plan_is_live_for_fill,
    live_coach_stage_label,
    live_memory_snapshot_overlay,
    live_plan_blocked_reason,
    live_plan_next_after_current,
)
from .models import LearningPlan, NextTaskContext, NextTaskRecommendation, PlanPhase, TaskDifficulty
from .subplan_store import delete_subplan, get_subplan, list_subplans, upsert_subplan

STOPWORDS = {
    "a",
    "an",
    "and",
    "api",
    "app",
    "backend",
    "behavior",
    "build",
    "coach",
    "coach-first",
    "code",
    "create",
    "deepen",
    "deeper",
    "evolve",
    "for",
    "forward",
    "from",
    "help",
    "idea",
    "implement",
    "implementation",
    "improve",
    "into",
    "learn",
    "make",
    "more",
    "plugin",
    "push",
    "project",
    "ship",
    "side",
    "stabilize",
    "that",
    "the",
    "this",
    "trainer",
    "turn",
    "with",
    "work",
}

PHRASE_HINTS = [
    "error handling",
    "state management",
    "code review",
    "unit testing",
    "integration testing",
    "review rhythm",
    "long term memory",
    "project adaptation",
    "idea implementation",
    "user interface",
    "design system",
    "context wiring",
]


def localized_text(en: str, zh: str, language: str | None) -> str:
    return zh if language == "zh-CN" else en


class TrainingPlannerService:
    def __init__(self, repository: TrainerRepository | None = None) -> None:
        self._repository = repository

    def generate_plan(
        self,
        *,
        goal: str,
        weekly_hours: int,
        teaching_style: str,
        direct_answer_policy: str,
        resources: list[object] | None = None,
    ) -> LearningPlan:
        concepts = self._extract_concepts(goal)
        concept_budget = self._concept_budget(weekly_hours)
        anchor = concepts[0] if concepts else "core implementation"
        practice_anchor = concepts[1] if len(concepts) > 1 else anchor
        integration_anchor = concepts[2] if len(concepts) > 2 else practice_anchor

        stage_blueprint = [
            (
                "Foundation",
                f"Build enough vocabulary and one tiny working slice around {anchor}.",
            ),
            (
                "Practice",
                f"Repeat {practice_anchor} through constrained patches with clear feedback.",
            ),
            (
                "Integration",
                f"Combine {integration_anchor} into a project-shaped change you can still review easily.",
            ),
        ]

        phases: list[PlanPhase] = []
        for index, (title, objective) in enumerate(stage_blueprint):
            phase_concepts = self._phase_concepts(
                concepts=concepts,
                stage_index=index,
                concept_budget=concept_budget,
                fallback=anchor,
            )
            phases.append(
                PlanPhase.create(
                    title=title,
                    objective=objective,
                    concepts=phase_concepts,
                    success_criteria=self._success_criteria_for_phase(
                        title=title,
                        concepts=phase_concepts,
                        weekly_hours=weekly_hours,
                    ),
                )
            )

        return LearningPlan.create(
            title=f"Trainer plan for {goal[:60]}",
            objective=goal,
            weekly_hours=weekly_hours,
            direct_answer_policy=direct_answer_policy,
            teaching_style=teaching_style,
            phases=phases,
            metadata={
                "resource_count": len(resources or []),
                "pace": self._pace_label(weekly_hours, due_review_count=0),
                "current_step": f"Land the first visible slice around {anchor}.",
                "why_now": f"Focus on {anchor} first so the learner can verify one small win before expanding.",
                "verify_method": self._success_criteria_for_phase(
                    title=stage_blueprint[0][0],
                    concepts=phases[0].concepts if phases else [anchor],
                    weekly_hours=weekly_hours,
                ),
                "blocked_reason": "",
                "next_after_current": (
                    f"After {practice_anchor}, connect {integration_anchor} into the existing project boundary."
                    if integration_anchor
                    else "After this slice, review and decide whether to widen scope."
                ),
            },
        )

    def freeze_plan(self, plan: LearningPlan) -> LearningPlan:
        plan.frozen = True
        plan.updated_at = utc_now()
        return plan

    def get_subplans_for_plan(self, plan_id: str) -> list[SubPlan]:
        if self._repository is not None:
            return self._repository.list_subplans(plan_id)
        return list_subplans(plan_id)

    def get_subplan(self, plan_id: str, subplan_id: str) -> SubPlan | None:
        if self._repository is not None:
            return self._repository.get_subplan(plan_id, subplan_id)
        return get_subplan(plan_id, subplan_id)

    def create_subplan(self, plan_id: str, subplan: SubPlan) -> SubPlan:
        created = self._normalize_subplan(plan_id, subplan)
        if self._repository is not None:
            self._repository.save_subplan(plan_id, created)
            return created
        return upsert_subplan(plan_id, created)

    def update_subplan(self, plan_id: str, subplan_id: str, subplan: SubPlan) -> SubPlan | None:
        existing = self.get_subplan(plan_id, subplan_id)
        if existing is None:
            return None
        updated = self._normalize_subplan(plan_id, subplan, subplan_id=subplan_id)
        updated = updated.model_copy(update={"created_at": existing.created_at})
        if self._repository is not None:
            self._repository.save_subplan(plan_id, updated)
            return updated
        return upsert_subplan(plan_id, updated)

    def delete_subplan(self, plan_id: str, subplan_id: str) -> bool:
        if self._repository is not None:
            return self._repository.delete_subplan(plan_id, subplan_id)
        return delete_subplan(plan_id, subplan_id)

    def evaluate_subplan_progress(self, subplan: SubPlan, evidence_items: list[EvidenceItem]) -> SubPlan:
        matched_stage_ids: set[str] = set()
        evidence_tokens = self._evidence_tokens(evidence_items)
        for stage in subplan.stages:
            if self._stage_matches_evidence(stage, evidence_items, evidence_tokens):
                matched_stage_ids.add(stage.id)

        total_stages = len(subplan.stages)
        if total_stages <= 0:
            progress_percent = 100.0 if evidence_items else 0.0
        else:
            progress_percent = round((len(matched_stage_ids) / total_stages) * 100.0, 1)

        if progress_percent >= 100.0:
            status = "completed"
        elif progress_percent > 0.0:
            status = "active"
        else:
            status = subplan.status or "draft"

        return subplan.model_copy(
            update={
                "progress_percent": progress_percent,
                "status": status,
                "updated_at": utc_now().isoformat(),
            }
        )

    def _normalize_subplan(
        self,
        plan_id: str,
        subplan: SubPlan,
        *,
        subplan_id: str | None = None,
        created_at: str | None = None,
    ) -> SubPlan:
        normalized = subplan.model_copy(deep=True)
        normalized.id = (subplan_id or normalized.id or f"subplan-{uuid4().hex[:8]}").strip()
        normalized.parent_plan_id = plan_id
        normalized.title = normalized.title.strip() or "Sub-plan"
        normalized.description = normalized.description.strip()
        normalized.stages = [stage.model_copy(deep=True) for stage in normalized.stages]
        normalized.status = normalized.status or "draft"
        normalized.progress_percent = max(0.0, min(100.0, float(normalized.progress_percent or 0.0)))
        normalized.created_at = created_at or normalized.created_at or utc_now().isoformat()
        normalized.updated_at = utc_now().isoformat()
        return normalized

    def _stage_matches_evidence(
        self,
        stage: PlanStage,
        evidence_items: list[EvidenceItem],
        evidence_tokens: list[str],
    ) -> bool:
        stage_texts = [stage.id, stage.title, stage.goal, *stage.outcomes]
        normalized_stage_texts = [self._normalize_text(item) for item in stage_texts if item]
        if not normalized_stage_texts:
            return False

        for evidence in evidence_items:
            evidence_texts = [
                evidence.target_plan_stage_id,
                evidence.summary,
                evidence.outcome,
                evidence.source_card_id,
                *evidence.concepts,
            ]
            normalized_evidence_texts = [self._normalize_text(item) for item in evidence_texts if item]
            if evidence.target_plan_stage_id and evidence.target_plan_stage_id.strip() == stage.id.strip():
                return True
            for stage_text in normalized_stage_texts:
                for evidence_text in normalized_evidence_texts:
                    if stage_text == evidence_text or stage_text in evidence_text or evidence_text in stage_text:
                        return True
                for token in evidence_tokens:
                    if token and token in stage_text:
                        return True
        return False

    def _evidence_tokens(self, evidence_items: list[EvidenceItem]) -> list[str]:
        tokens: list[str] = []
        for evidence in evidence_items:
            for value in [
                evidence.summary,
                evidence.outcome,
                evidence.source_card_id,
                evidence.target_plan_stage_id,
                *evidence.concepts,
            ]:
                normalized = self._normalize_text(value)
                if not normalized:
                    continue
                if normalized not in tokens:
                    tokens.append(normalized)
        return tokens

    def _normalize_text(self, value: str) -> str:
        return " ".join(str(value or "").replace("_", " ").replace("-", " ").split()).strip().lower()

    def recommend_next_task(self, context: NextTaskContext) -> NextTaskRecommendation:
        due_review = self._pick_due_review(context.due_reviews, focus_override=context.focus_override)
        if due_review is not None:
            return self._review_recommendation_from_due_review(due_review, context)

        due_weakness = self._pick_due_weakness(context.weaknesses, focus_override=context.focus_override)
        if due_weakness is not None:
            return self._review_recommendation_from_weakness(due_weakness, context)

        active_phase = self._active_phase(context.plan, context.mastery)
        target_concepts = self._phase_targets(
            active_phase,
            context.mastery,
            weekly_hours=context.plan.weekly_hours,
            focus_override=context.focus_override,
        )
        difficulty = self._choose_difficulty(
            context.recent_attempts,
            target_concepts=target_concepts,
            mastery=context.mastery,
            weekly_hours=context.plan.weekly_hours,
        )
        title = active_phase.title if active_phase else "Next exercise"
        acceptance_criteria = self._acceptance_criteria_for_progression(
            title=title,
            concepts=target_concepts,
            difficulty=difficulty,
        )
        verification_hints = self._verification_hints_for_progression(target_concepts)

        return NextTaskRecommendation(
            task_id=f"task_{uuid4().hex}",
            title=f"{title}: {' / '.join(target_concepts[:2])}",
            prompt=(
                f"You are in the '{title}' phase. Write one small, reviewable change that practices "
                f"{', '.join(target_concepts)}. Stay inside the current project context, keep the slice narrow, "
                f"and match the teaching style '{context.plan.teaching_style}'."
            ),
            concepts=target_concepts,
            acceptance_criteria=acceptance_criteria,
            verification_hints=verification_hints,
            difficulty=difficulty,
            reason=self._progression_reason(active_phase, context, target_concepts),
            review=False,
            metadata={
                "source": "phase_progression",
                "phase_id": active_phase.id if active_phase else None,
                "pace": self._pace_label(context.plan.weekly_hours, len(context.due_reviews)),
                "focus_override": context.focus_override,
                "phase_ready_to_advance": self._phase_is_complete(active_phase, context.mastery),
                "current_step": self._current_step_for_phase(active_phase, target_concepts, difficulty),
                "why_now": self._why_now(active_phase, context, target_concepts),
                "verify_method": verification_hints,
                "blocked_reason": self._blocked_reason(context),
                "next_after_current": self._next_after_current(active_phase, context, target_concepts),
            },
        )

    def _extract_concepts(self, goal: str) -> list[str]:
        lowered = goal.lower()
        concepts: list[str] = []

        for phrase in PHRASE_HINTS:
            if phrase in lowered:
                concepts.append(phrase)

        tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", lowered)
        filtered_tokens = [token for token in tokens if len(token) > 2 and token not in STOPWORDS]
        counter = Counter(filtered_tokens)
        concepts.extend(token for token, _count in counter.most_common(8))

        deduped: list[str] = []
        for concept in concepts:
            normalized = concept.strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)

        return deduped[:6] or ["problem framing", "implementation", "verification"]

    def _pick_due_review(
        self,
        due_reviews: list[ReviewQueueItem],
        *,
        focus_override: str | None = None,
    ) -> ReviewQueueItem | None:
        eligible = [
            item
            for item in due_reviews
            if (
                item.source in {"weakness", "mastery", "reflection"}
                or item.severity == "high"
                or item.surface_mode == "due"
            )
            and not (
                item.severity == "low"
                and item.concept in {"plan-discipline", "new-workspace", "resource-grounding"}
            )
            and not (
                focus_override is not None
                and item.concept in {"new-workspace", "plan-discipline", "resource-grounding"}
            )
        ]
        if not eligible:
            return None

        def sort_key(item: ReviewQueueItem) -> tuple[int, int, datetime, float]:
            surface_rank = {"due": 0, "ahead": 1, "digest": 2}.get(item.surface_mode, 1)
            severity_rank = {"high": 0, "medium": 1, "low": 2}[item.severity]
            due_at = self._parse_due_at(item.due_at)
            mastery_score = item.mastery_score if item.mastery_score is not None else 1.0
            return surface_rank, severity_rank, due_at, mastery_score

        return sorted(eligible, key=sort_key)[0]

    def _pick_due_weakness(
        self,
        weaknesses: list[WeaknessRecord],
        *,
        focus_override: str | None = None,
    ) -> WeaknessRecord | None:
        due = [
            item
            for item in weaknesses
            if (item.next_review_at is None or item.next_review_at <= utc_now())
            and not (focus_override is not None and item.concept in {"new-workspace", "plan-discipline", "resource-grounding"})
        ]
        due.sort(key=lambda item: (item.severity, item.updated_at), reverse=True)
        return due[0] if due else None

    def _active_phase(self, plan: LearningPlan, mastery: list[MasteryRecord]) -> PlanPhase | None:
        if not plan.phases:
            return None

        current_index = 0
        for index, phase in enumerate(plan.phases):
            if phase.id == plan.current_phase_id:
                current_index = index
                break

        current_phase = plan.phases[current_index]
        if (
            self._phase_is_complete(current_phase, mastery)
            and current_index + 1 < len(plan.phases)
        ):
            return plan.phases[current_index + 1]
        return current_phase

    def _phase_targets(
        self,
        phase: PlanPhase | None,
        mastery: list[MasteryRecord],
        *,
        weekly_hours: int,
        focus_override: str | None = None,
    ) -> list[str]:
        if phase is None:
            return [focus_override] if focus_override else ["implementation"]

        mastery_map = {item.concept: item.score for item in mastery}
        ranked = sorted(phase.concepts, key=lambda concept: mastery_map.get(concept, 0.0))
        if focus_override:
            ranked = [focus_override, *[concept for concept in ranked if concept != focus_override]]
        target_budget = 1 if weekly_hours <= 3 else 2
        return ranked[:target_budget] or [focus_override or "implementation"]

    def _choose_difficulty(
        self,
        attempts: list[dict[str, object]],
        *,
        target_concepts: list[str],
        mastery: list[MasteryRecord],
        weekly_hours: int,
    ) -> TaskDifficulty:
        streak = 0
        for attempt in reversed(attempts):
            if bool(attempt.get("passed")):
                streak += 1
            else:
                break

        mastery_map = {item.concept: item.score for item in mastery}
        target_scores = [mastery_map.get(concept, 0.0) for concept in target_concepts]
        average_target_score = sum(target_scores) / len(target_scores) if target_scores else 0.0

        if streak >= 3:
            return TaskDifficulty.HARD
        if streak >= 1 or average_target_score >= 0.45:
            return TaskDifficulty.MEDIUM
        return TaskDifficulty.EASY

    def _review_recommendation_from_due_review(
        self,
        due_review: ReviewQueueItem,
        context: NextTaskContext,
    ) -> NextTaskRecommendation:
        concept = due_review.focus_area or due_review.concept
        surface_mode = due_review.surface_mode
        task_hint = due_review.task_hint.strip()
        linked_context = due_review.linked_context.strip()
        review_pressure = due_review.reason.strip()
        if task_hint:
            prompt = (
                f"Return to '{concept}' through one very small implementation move. "
                f"Use this exact next review move: {task_hint}"
            )
        else:
            prompt = (
                f"Return to '{concept}' through one very small implementation move. Focus on this specific review pressure: "
                f"{review_pressure}"
            )
        if linked_context:
            prompt += f" Keep it attached to this nearby context: {linked_context}"
        if surface_mode == "ahead":
            prompt = f"Surface this review before the learner fully changes lanes: {prompt}"
        elif surface_mode == "digest":
            prompt = f"Keep this review bundled with adjacent follow-ups instead of interrupting too often: {prompt}"

        acceptance = [
            f"Make one focused patch that proves '{concept}' in code.",
            "Keep the change narrow enough to review in one pass.",
            "Write one short note explaining what changed and why it now holds.",
        ]
        if task_hint:
            acceptance[0] = f"Land the specific review move around '{concept}': {task_hint}"
        if due_review.linked_context.strip():
            acceptance.append("Point at the exact nearby code path, branch, or file context this review is tied to.")
        if surface_mode == "digest":
            acceptance.append("Keep the patch small enough that nearby review items could still be bundled after this one.")

        verification_hints = [
            "Run the smallest relevant check or manual verification.",
            "Confirm the specific review reason is now resolved, not merely discussed.",
        ]
        if due_review.linked_context.strip():
            verification_hints.insert(0, "Verify the nearby linked context directly, not just the easiest happy path.")
        if due_review.mastery_score is not None and due_review.mastery_score < 0.45:
            verification_hints.append("Repeat the weak branch once more after the first pass so the concept sticks.")

        return NextTaskRecommendation(
            task_id=f"task_{uuid4().hex}",
            title=f"Review: {concept}",
            prompt=prompt,
            concepts=[concept],
            acceptance_criteria=acceptance,
            verification_hints=verification_hints,
            difficulty=TaskDifficulty.EASY,
            reason=(
                "A real review item is applying training pressure, so the coach should reinforce it before opening a new lane."
                if surface_mode == "due"
                else "The coach should surface this review pressure before the learner drifts too far from the current lane."
                if surface_mode == "ahead"
                else "The coach should keep this bundled review pressure alive while preserving the readability of the main thread."
            ),
            review=True,
            metadata={
                "source": "due_review",
                "review_source": due_review.source,
                "review_severity": due_review.severity,
                "review_surface_mode": due_review.surface_mode,
                "review_task_hint": due_review.task_hint,
                "review_focus_area": due_review.focus_area,
                "review_linked_context": due_review.linked_context,
                "review_interval_days": due_review.interval_days,
                "review_mastery_score": due_review.mastery_score,
                "pace": self._pace_label(context.plan.weekly_hours, len(context.due_reviews)),
            },
        )

    def _review_recommendation_from_weakness(
        self,
        weakness: WeaknessRecord,
        context: NextTaskContext,
    ) -> NextTaskRecommendation:
        return NextTaskRecommendation(
            task_id=f"task_{uuid4().hex}",
            title=f"Review: {weakness.concept}",
            prompt=(
                f"Re-implement a focused exercise on '{weakness.concept}' and explicitly avoid this failure mode: "
                f"{weakness.reason}."
            ),
            concepts=[weakness.concept],
            acceptance_criteria=[
                f"Land one small patch that exercises '{weakness.concept}'.",
                "Show the exact edge, branch, or boundary that used to fail.",
                "Explain how the new patch avoids repeating the same mistake.",
            ],
            verification_hints=[
                "Verify the previously weak path directly.",
                "Keep the patch smaller than a refactor.",
            ],
            difficulty=TaskDifficulty.EASY,
            reason="A weakness is due for review.",
            review=True,
            metadata={
                "source": "weakness_review",
                "pace": self._pace_label(context.plan.weekly_hours, len(context.due_reviews)),
            },
        )

    def _phase_concepts(
        self,
        *,
        concepts: list[str],
        stage_index: int,
        concept_budget: int,
        fallback: str,
    ) -> list[str]:
        ordered = concepts[stage_index::3] + concepts[:stage_index]
        deduped: list[str] = []
        for concept in ordered:
            if concept not in deduped:
                deduped.append(concept)
        return (deduped[:concept_budget] or [fallback])[: max(1, concept_budget)]

    def _success_criteria_for_phase(
        self,
        *,
        title: str,
        concepts: list[str],
        weekly_hours: int,
    ) -> list[str]:
        lead = concepts[0]
        criteria = [
            f"Implement one visible slice that proves {lead}.",
            "Verify the slice with at least one concrete check.",
        ]
        if weekly_hours >= 5 and len(concepts) > 1:
            criteria.append(f"Connect {concepts[1]} without broadening into a refactor.")
        if title == "Integration":
            criteria.append("Explain why this still fits the current project boundary.")
        return criteria

    def _acceptance_criteria_for_progression(
        self,
        *,
        title: str,
        concepts: list[str],
        difficulty: TaskDifficulty,
    ) -> list[str]:
        criteria = [
            f"Implement one narrow patch centered on {concepts[0]}.",
            "Add or run one check that proves the change, not only a happy path read-through.",
        ]
        if difficulty != TaskDifficulty.EASY and len(concepts) > 1:
            criteria.append(f"Connect {concepts[1]} without losing the narrow slice boundary.")
        if title == "Integration":
            criteria.append("State which existing file, feature boundary, or workflow this integrates with.")
        else:
            criteria.append("Write one short reflection about why this is the right next move now.")
        return criteria

    def _verification_hints_for_progression(self, concepts: list[str]) -> list[str]:
        return [
            f"Check the concrete behavior around {concepts[0]} first.",
            "Confirm the patch is still reviewable in one pass.",
        ]

    def _progression_reason(
        self,
        active_phase: PlanPhase | None,
        context: NextTaskContext,
        target_concepts: list[str],
    ) -> str:
        if context.focus_override:
            return (
                f"Stay inside the current phase while following the learner's requested focus on {context.focus_override}."
            )
        if active_phase and self._phase_is_complete(active_phase, context.mastery):
            return (
                f"The previous phase is strong enough to step forward, so the coach can now shift into '{active_phase.title}' "
                f"around {', '.join(target_concepts)}."
            )
        return (
            f"Advance the current learning phase through {', '.join(target_concepts)} while keeping the slice narrow and verifiable."
        )

    def _current_step_for_phase(
        self,
        phase: PlanPhase | None,
        target_concepts: list[str],
        difficulty: TaskDifficulty,
    ) -> str:
        if phase is None:
            return f"Implement one narrow slice around {target_concepts[0]}."
        if difficulty == TaskDifficulty.HARD and len(target_concepts) > 1:
            return f"Implement {target_concepts[0]} first, then connect {target_concepts[1]} without widening scope."
        return f"Implement one narrow slice around {target_concepts[0]} in the '{phase.title}' phase."

    def _why_now(
        self,
        phase: PlanPhase | None,
        context: NextTaskContext,
        target_concepts: list[str],
    ) -> str:
        if context.focus_override:
            return f"The learner explicitly asked to stay on {context.focus_override}, so keep the next move aligned."
        if phase and self._phase_is_complete(phase, context.mastery):
            return f"The current phase is strong enough to step forward through {', '.join(target_concepts)}."
        if context.due_reviews:
            return "A review item is already due, so keep the next move close to the live pressure point."
        return f"This is the smallest visible move that advances {', '.join(target_concepts)} without broadening the project."

    def _blocked_reason(self, context: NextTaskContext) -> str:
        if context.due_reviews:
            return "Due reviews are still active, so avoid widening the scope before the review loop is handled."
        if context.session_summary:
            summary = context.session_summary.strip()
            if summary:
                return f"Recent session context is still fresh: {summary}"
        return ""

    def _next_after_current(
        self,
        phase: PlanPhase | None,
        context: NextTaskContext,
        target_concepts: list[str],
    ) -> str:
        if phase is None:
            return f"Verify {target_concepts[0]} and then decide whether to broaden the slice."
        if self._phase_is_complete(phase, context.mastery):
            return f"Move into the next phase after confirming {', '.join(target_concepts)} still holds in code."
        if len(target_concepts) > 1:
            return f"Once {target_concepts[0]} is stable, connect {target_concepts[1]} and re-check the boundary."
        return "After this slice, verify it and decide whether to widen scope or repeat once more."

    def _phase_is_complete(self, phase: PlanPhase | None, mastery: list[MasteryRecord]) -> bool:
        if phase is None or not phase.concepts:
            return False
        mastery_map = {item.concept: item.score for item in mastery}
        tracked = [mastery_map.get(concept, 0.0) for concept in phase.concepts[:2]]
        if not tracked:
            return False
        return min(tracked) >= 0.72

    def _concept_budget(self, weekly_hours: int) -> int:
        if weekly_hours <= 3:
            return 1
        if weekly_hours <= 6:
            return 2
        return 3

    def _pace_label(self, weekly_hours: int, due_review_count: int) -> str:
        if due_review_count >= 3:
            return "gentle"
        if weekly_hours >= 8 and due_review_count == 0:
            return "intensive"
        return "steady"

    def _parse_due_at(self, value: str | None) -> datetime:
        if not value:
            return datetime.min.replace(tzinfo=utc_now().tzinfo)
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.min.replace(tzinfo=utc_now().tzinfo)


class PlannerService:
    def __init__(
        self,
        planner: TrainingPlannerService | None = None,
        repository: TrainerRepository | None = None,
    ) -> None:
        self._planner = planner or TrainingPlannerService(repository=repository)

    def _normalize_token(self, value: str) -> str:
        lowered = str(value or "").strip().lower()
        tokens = re.findall(r"[a-z0-9]+", lowered)
        return " ".join(tokens)

    def _live_plan_change_summary(
        self,
        *,
        plan: ApiLearningPlan,
        from_title: str,
        to_title: str = "",
        complete: bool = False,
        runtime: dict[str, Any] | None = None,
        existing: dict[str, Any] | None = None,
    ) -> str:
        from_label = live_coach_stage_label(
            plan=plan,
            runtime=runtime,
            existing=existing,
            stage_title=from_title,
        )
        to_label = (
            live_coach_stage_label(
                plan=plan,
                runtime=runtime,
                existing=existing,
                stage_title=to_title,
            )
            if to_title
            else ""
        )
        if complete:
            raw = f"Complete {from_title}; the plan is now complete."
            if from_label:
                return f"Complete {from_label}; the plan is now complete."
            return live_memory_snapshot_overlay(
                plan=plan,
                runtime=runtime,
                existing=existing,
                plan_change_summary=raw,
            )["plan_change_summary"]
        raw = f"Advance from {from_title} to {to_title}."
        if from_label and to_label:
            return f"Advance from {from_label} to {to_label}."
        return live_memory_snapshot_overlay(
            plan=plan,
            runtime=runtime,
            existing=existing,
            plan_change_summary=raw,
        )["plan_change_summary"]

    def _live_chrome_text(
        self,
        *,
        plan: ApiLearningPlan,
        text: str,
        runtime: dict[str, Any] | None = None,
        existing: dict[str, Any] | None = None,
    ) -> str:
        return live_memory_snapshot_overlay(
            plan=plan,
            runtime=runtime,
            existing=existing,
            plan_change_summary=text,
        )["plan_change_summary"]

    def _live_recovered_step(
        self,
        *,
        runtime: dict[str, Any] | None = None,
        existing: dict[str, Any] | None = None,
    ) -> str:
        runtime = runtime if isinstance(runtime, dict) else {}
        existing = existing if isinstance(existing, dict) else {}
        return str(runtime.get("current_step") or existing.get("current_step") or "").strip()

    def _formal_plan_is_live(
        self,
        *,
        plan: ApiLearningPlan,
        runtime: dict[str, Any] | None = None,
        existing: dict[str, Any] | None = None,
    ) -> bool:
        return formal_plan_is_live_runtime_identity(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=self._live_recovered_step(runtime=runtime, existing=existing),
        )

    def evaluate_evidence_for_plan(
        self,
        evidence: EvidenceItem,
        plan: ApiLearningPlan,
        *,
        runtime: dict[str, Any] | None = None,
        existing: dict[str, Any] | None = None,
    ) -> EvidenceAdoptResponse:
        if plan.frozen:
            return EvidenceAdoptResponse(
                evidence=evidence,
                plan_updated=False,
                plan_change_summary="Plan is frozen, so evidence cannot advance it right now.",
            )
        if not plan.stages:
            return EvidenceAdoptResponse(
                evidence=evidence,
                plan_updated=False,
                plan_change_summary="Plan has no stages to evaluate.",
            )

        active_index = next(
            (
                index
                for index, stage in enumerate(plan.stages)
                if stage.id == plan.current_stage_id or stage.status == "active"
            ),
            0,
        )
        active_stage = plan.stages[active_index]
        if evidence.target_plan_stage_id and evidence.target_plan_stage_id != active_stage.id:
            return EvidenceAdoptResponse(
                evidence=evidence,
                plan_updated=False,
                plan_change_summary="Evidence targets a stage that is not the active stage.",
            )

        evidence_concepts = {self._normalize_token(item) for item in evidence.concepts if item}
        stage_outcomes = {self._normalize_token(item) for item in active_stage.outcomes if item}
        if evidence_concepts and not (evidence_concepts & stage_outcomes):
            return EvidenceAdoptResponse(
                evidence=evidence,
                plan_updated=False,
                plan_change_summary="Evidence concepts do not match the active stage outcomes.",
            )

        if evidence.outcome != "pass":
            if evidence.outcome == "partial":
                return EvidenceAdoptResponse(
                    evidence=evidence,
                    plan_updated=False,
                    plan_change_summary="Evidence suggests more review is needed before advancing.",
                )
            return EvidenceAdoptResponse(
                evidence=evidence,
                plan_updated=False,
                plan_change_summary="Evidence did not demonstrate a passing result.",
            )

        active_stage.status = "completed"
        if active_index + 1 < len(plan.stages):
            next_stage = plan.stages[active_index + 1]
            next_stage.status = "active"
            plan.current_stage_id = next_stage.id
            return EvidenceAdoptResponse(
                evidence=evidence,
                plan_updated=True,
                plan_change_summary=self._live_plan_change_summary(
                    plan=plan,
                    from_title=active_stage.title,
                    to_title=next_stage.title,
                    runtime=runtime,
                    existing=existing,
                ),
            )
        plan.current_stage_id = active_stage.id
        return EvidenceAdoptResponse(
            evidence=evidence,
            plan_updated=True,
            plan_change_summary=self._live_plan_change_summary(
                plan=plan,
                from_title=active_stage.title,
                complete=True,
                runtime=runtime,
                existing=existing,
            ),
        )

    def get_subplans_for_plan(self, plan_id: str) -> list[SubPlan]:
        return self._planner.get_subplans_for_plan(plan_id)

    def get_subplan(self, plan_id: str, subplan_id: str) -> SubPlan | None:
        return self._planner.get_subplan(plan_id, subplan_id)

    def create_subplan(self, plan_id: str, subplan: SubPlan) -> SubPlan:
        return self._planner.create_subplan(plan_id, subplan)

    def update_subplan(self, plan_id: str, subplan_id: str, subplan: SubPlan) -> SubPlan | None:
        return self._planner.update_subplan(plan_id, subplan_id, subplan)

    def delete_subplan(self, plan_id: str, subplan_id: str) -> bool:
        return self._planner.delete_subplan(plan_id, subplan_id)

    def evaluate_subplan_progress(self, subplan: SubPlan, evidence_items: list[EvidenceItem]) -> SubPlan:
        return self._planner.evaluate_subplan_progress(subplan, evidence_items)

    def generate_plan(self, request: PlanGenerateRequest) -> ApiLearningPlan:
        profile = request.profile
        goal = request.goals[0] if request.goals else profile.long_term_goal
        plan = self._planner.generate_plan(
            goal=goal,
            weekly_hours=profile.weekly_hours,
            teaching_style=profile.teaching_style,
            direct_answer_policy=profile.answer_policy,
            resources=cast(list[object], list(request.resource_ids)),
        )
        return self._domain_plan_to_api(
            plan,
            resource_ids=list(request.resource_ids),
            summary=self._plan_summary(goal, profile.weekly_hours),
        )

    def localize_plan(self, plan: ApiLearningPlan, response_language: str | None) -> ApiLearningPlan:
        if response_language != "zh-CN":
            return plan

        localized = plan.model_copy(deep=True)
        localized.title = self._localize_plan_title(localized.title, localized.objective)
        localized.summary = self._localize_plan_summary(localized.summary, localized.objective)
        localized.stages = [self._localize_plan_stage(stage) for stage in localized.stages]
        localized.current_step = self._localize_plan_line(localized.current_step)
        localized.why_now = self._localize_plan_line(localized.why_now)
        localized.verify_method = [self._localize_plan_line(item) for item in localized.verify_method if item]
        localized.next_after_current = self._localize_plan_line(localized.next_after_current)
        localized.blocked_reason = self._localize_plan_line(localized.blocked_reason)
        metadata = getattr(localized, "metadata", None)
        if isinstance(metadata, dict):
            try:
                localized.metadata = self._localize_plan_metadata(metadata)
            except AttributeError:
                pass
        return localized

    def update_plan(self, current: ApiLearningPlan, request: PlanUpdateRequest) -> ApiLearningPlan:
        updated = current.model_copy(deep=True)
        if request.title:
            updated.title = request.title
        if request.weekly_cadence:
            updated.cadence = request.weekly_cadence
            updated.weekly_cadence = request.weekly_cadence
        updated.frozen = request.freeze if request.freeze else bool(request.frozen) if request.frozen is not None else updated.frozen

        if request.instructions.strip():
            focus_concepts = self._planner._extract_concepts(request.instructions)
            if focus_concepts:
                primary_focus = focus_concepts[0]
                updated.summary = (
                    f"Refocused on {request.instructions.strip()}. Keep the next stage narrow, verifiable, and aligned with the learner's latest instruction."
                )
                if updated.stages:
                    active_index = next(
                        (index for index, stage in enumerate(updated.stages) if stage.id == updated.current_stage_id or stage.status == "active"),
                        0,
                    )
                    active_stage = updated.stages[active_index]
                    active_stage.goal = f"Push {primary_focus} through one narrow implementation slice before broadening scope."
                    outcomes = list(active_stage.outcomes)
                    if outcomes:
                        outcomes[0] = f"Ship one visible patch around {primary_focus}"
                        active_stage.outcomes = outcomes
                    updated.current_step = active_stage.goal
                    updated.why_now = f"User steering changed toward {primary_focus}; keep the live stage narrow and verifiable."
                    updated.verify_method = list(active_stage.outcomes or [f"Verify the patch around {primary_focus}."])
                    updated.next_after_current = (
                        updated.stages[active_index + 1].goal
                        if active_index + 1 < len(updated.stages)
                        else "Review the patch and decide whether to widen scope."
                    )
                    updated.blocked_reason = ""
            else:
                updated.summary = f"{updated.summary} Update request: {request.instructions}".strip()
                updated.why_now = updated.summary
        return updated

    def _localize_plan_title(self, title: str, objective: str) -> str:
        if title.startswith("Trainer plan for "):
            anchor = objective[:60].strip() or title.removeprefix("Trainer plan for ").strip()
            return f"训练计划：{anchor}"
        return self._localize_plan_phase_title(title)

    def _localize_plan_summary(self, summary: str, objective: str) -> str:
        anchor = objective[:48].strip() or objective.strip() or "当前目标"
        if summary.startswith("Keep the plan for '") and "land one thin slice, verify it, then expand only after review." in summary:
            return f"围绕「{anchor}」把计划保持得足够窄：先落地一个薄切片，验证后再扩展。"
        if summary.startswith("Use the plan for '") and "without losing patch discipline." in summary:
            return f"围绕「{anchor}」在快速实现、复核和项目化整合之间切换，同时不丢补丁纪律。"
        if summary.startswith("Move '") and "through thin implementation slices, repeated checks, and staged integration." in summary:
            return f"围绕「{anchor}」通过薄切片、重复检查和分阶段整合往前推。"
        if summary.startswith("Refocused on ") and "Keep the next stage narrow, verifiable, and aligned with the learner's latest instruction." in summary:
            return "围绕最新指令重新聚焦：保持下一阶段足够窄、可验证，并和学习者当前要求一致。"
        return summary

    def _localize_plan_stage(self, stage: PlanStage) -> PlanStage:
        localized_title = self._localize_plan_phase_title(stage.title)
        localized_goal = self._localize_plan_goal(stage.goal)
        localized_outcomes = [self._localize_plan_line(item) for item in stage.outcomes if item]
        return stage.model_copy(update={"title": localized_title, "goal": localized_goal, "outcomes": localized_outcomes})

    def _localize_plan_phase_title(self, title: str) -> str:
        return {
            "Foundation": "基础",
            "Practice": "练习",
            "Integration": "整合",
            "Next exercise": "下一练习",
        }.get(title, title)

    def _localize_plan_goal(self, goal: str) -> str:
        if goal.startswith("Build enough vocabulary and one tiny working slice around ") and goal.endswith("."):
            anchor = goal.removeprefix("Build enough vocabulary and one tiny working slice around ").removesuffix(".")
            return f"先围绕 {anchor} 建立必要上下文，再做一个很小的可运行切片。"
        if goal.startswith("Repeat ") and goal.endswith(" through constrained patches with clear feedback."):
            anchor = goal.removeprefix("Repeat ").removesuffix(" through constrained patches with clear feedback.")
            return f"围绕 {anchor} 通过受限补丁反复练习，并拿到清晰反馈。"
        if goal.startswith("Combine ") and goal.endswith(" into a project-shaped change you can still review easily."):
            anchor = goal.removeprefix("Combine ").removesuffix(" into a project-shaped change you can still review easily.")
            return f"把 {anchor} 组合进一个仍然容易评审的项目形改动里。"
        if goal.startswith("Push ") and goal.endswith(" through one narrow implementation slice before broadening scope."):
            anchor = goal.removeprefix("Push ").removesuffix(" through one narrow implementation slice before broadening scope.")
            return f"围绕 {anchor} 推进一个窄实现切片，再决定要不要扩展范围。"
        return goal

    def _localize_plan_line(self, line: str) -> str:
        if line.startswith("Land the first visible slice around ") and line.endswith("."):
            anchor = line.removeprefix("Land the first visible slice around ").removesuffix(".")
            return f"先落地围绕 {anchor} 的第一个可见切片。"
        if line.startswith("Focus on ") and line.endswith(" first so the learner can verify one small win before expanding."):
            anchor = line.removeprefix("Focus on ").removesuffix(" first so the learner can verify one small win before expanding.")
            return f"先聚焦 {anchor}，让学习者先验证一个小成果，再考虑扩展。"
        if line.startswith("After ") and line.endswith(" into the existing project boundary."):
            anchor = line.removeprefix("After ").removesuffix(" into the existing project boundary.")
            return f"完成 {anchor} 后，再把后续概念接入现有项目边界。"
        if line == "Review the result and decide whether to widen scope.":
            return "复核结果，再决定是否扩大范围。"
        mappings = {
            "Implement one visible slice that proves ": "实现一个可见切片来证明 ",
            "Verify the slice with at least one concrete check.": "至少用一个具体检查验证这个切片。",
            "Connect ": "连接 ",
            " without broadening into a refactor.": "，但不要扩展成重构。",
            "Explain why this still fits the current project boundary.": "说明为什么这仍然符合当前项目边界。",
            "Implement one narrow patch centered on ": "实现一个围绕 ",
            "Add or run one check that proves the change, not only a happy path read-through.": "添加或运行一个检查来证明改动成立，而不只是走读 happy path。",
            "Write one short reflection about why this is the right next move now.": "写一段简短复盘，说明为什么这是现在正确的下一步。",
            "Check the concrete behavior around ": "先检查 ",
            " first.": " 附近的具体行为。",
            "Confirm the patch is still reviewable in one pass.": "确认这个补丁仍然能一遍看完。",
            "Run the smallest relevant check.": "运行最小相关检查。",
            "Explain why the patch now holds.": "说明为什么这次补丁现在成立。",
            "Keep the patch smaller than a refactor.": "把补丁控制在小于一次重构的范围内。",
            "Run the smallest relevant check or manual verification.": "运行最小相关检查，或者做一次最小手动验证。",
            "Confirm the specific review reason is now resolved, not merely discussed.": "确认这次真正解决了具体的复习原因，而不只是讨论它。",
            "Verify the nearby linked context directly, not just the easiest happy path.": "直接验证附近的关联上下文，而不是只看最容易的 happy path。",
            "Repeat the weak branch once more after the first pass so the concept sticks.": "第一次通过后再把薄弱分支重复一遍，让概念真正留下来。",
            "Land one small patch that exercises ": "落地一个围绕 ",
            "Show the exact edge, branch, or boundary that used to fail.": "展示之前会失败的那个精确边缘、分支或边界。",
            "Explain how the new patch avoids repeating the same mistake.": "说明这次新补丁如何避免重复同一个错误。",
            "Verify the previously weak path directly.": "直接验证之前薄弱的路径。",
        }
        for prefix, localized_prefix in mappings.items():
            if line == prefix:
                return localized_prefix
            if line.startswith(prefix) and line.endswith(".") and prefix.endswith(" "):
                return localized_prefix + line.removeprefix(prefix).removesuffix(".") + "。"
            if line.startswith(prefix) and prefix == "Connect " and " without broadening into a refactor." in line:
                anchor = line.removeprefix("Connect ").removesuffix(" without broadening into a refactor.")
                return f"连接 {anchor}，但不要扩展成重构。"
            if line.startswith(prefix) and prefix == "Implement one narrow patch centered on ":
                anchor = line.removeprefix(prefix).removesuffix(".")
                return f"实现一个围绕 {anchor} 的窄补丁。"
            if line.startswith(prefix) and prefix == "Implement one visible slice that proves ":
                anchor = line.removeprefix(prefix).removesuffix(".")
                return f"实现一个可见切片来证明 {anchor}。"
            if line.startswith(prefix) and prefix == "Verify the slice with at least one concrete check.":
                return localized_prefix
            if line.startswith(prefix) and prefix == "Add or run one check that proves the change, not only a happy path read-through.":
                return localized_prefix
            if line.startswith(prefix) and prefix == "Write one short reflection about why this is the right next move now.":
                return localized_prefix
            if line.startswith(prefix) and prefix == "Check the concrete behavior around " and line.endswith(" first."):
                anchor = line.removeprefix(prefix).removesuffix(" first.")
                return f"先检查 {anchor} 附近的具体行为。"
            if line.startswith(prefix) and prefix == "Run the smallest relevant check or manual verification.":
                return localized_prefix
            if line.startswith(prefix) and prefix == "Confirm the specific review reason is now resolved, not merely discussed.":
                return localized_prefix
            if line.startswith(prefix) and prefix == "Verify the nearby linked context directly, not just the easiest happy path.":
                return localized_prefix
            if line.startswith(prefix) and prefix == "Repeat the weak branch once more after the first pass so the concept sticks.":
                return localized_prefix
            if line.startswith(prefix) and prefix == "Land one small patch that exercises ":
                anchor = line.removeprefix(prefix).removesuffix(".")
                return f"落地一个围绕 {anchor} 的小补丁。"
            if line.startswith(prefix) and prefix == "Show the exact edge, branch, or boundary that used to fail.":
                return localized_prefix
            if line.startswith(prefix) and prefix == "Explain how the new patch avoids repeating the same mistake.":
                return localized_prefix
            if line.startswith(prefix) and prefix == "Verify the previously weak path directly.":
                return localized_prefix
        return line

    def _localize_plan_metadata(self, metadata: dict[str, object]) -> dict[str, object]:
        localized = dict(metadata)
        if "current_step" in localized and isinstance(localized["current_step"], str):
            localized["current_step"] = self._localize_plan_line(localized["current_step"])
        if "why_now" in localized and isinstance(localized["why_now"], str):
            localized["why_now"] = self._localize_plan_line(localized["why_now"])
        if "next_after_current" in localized and isinstance(localized["next_after_current"], str):
            localized["next_after_current"] = self._localize_plan_line(localized["next_after_current"])
        if "blocked_reason" in localized and isinstance(localized["blocked_reason"], str):
            localized["blocked_reason"] = self._localize_plan_line(localized["blocked_reason"])
        if "verify_method" in localized and isinstance(localized["verify_method"], list):
            localized["verify_method"] = [
                self._localize_plan_line(str(item))
                for item in localized["verify_method"]
                if str(item).strip()
            ]
        return localized

    def refresh_plan_lifecycle(
        self,
        plan: ApiLearningPlan,
        *,
        current_step: str | None = None,
        why_now: str | None = None,
        verify_method: list[str] | None = None,
        blocked_reason: str | None = None,
        next_after_current: str | None = None,
    ) -> ApiLearningPlan:
        updated = plan.model_copy(deep=True)
        if current_step is not None:
            updated.current_step = current_step
        if why_now is not None:
            updated.why_now = why_now
        if verify_method is not None:
            updated.verify_method = [item for item in verify_method if item]
        if blocked_reason is not None:
            updated.blocked_reason = blocked_reason
        if next_after_current is not None:
            updated.next_after_current = next_after_current
        # model_copy(deep=True) resets every stage status to the persisted default
        # ("pending"), which would silently drop the current active stage. Re-apply
        # the live stage status after the copy so refresh never claims the plan has
        # no active stage.
        active_stage_id = plan.current_stage_id or (
            plan.stages[0].id if plan.stages else None
        )
        if active_stage_id:
            for stage in updated.stages:
                if stage.id == active_stage_id and stage.status != "active":
                    stage.status = "active"
        updated.updated_at = utc_now().isoformat()
        return updated

    def next_task(
        self,
        profile: UserProfile | None,
        focus_area: str | None = None,
        *,
        current_plan: ApiLearningPlan | None = None,
        memory_snapshot: ApiMemorySnapshot | None = None,
        response_language: str | None = None,
        recent_attempts: list[dict[str, object]] | None = None,
        coach_defaults: dict[str, object] | None = None,
    ) -> ApiTaskSpec:
        if profile is None:
            profile = UserProfile(long_term_goal="Build a reliable coding habit", weekly_hours=4)

        plan_source = current_plan or (memory_snapshot.active_plan if memory_snapshot and memory_snapshot.active_plan else None)
        plan = (
            self._api_plan_to_domain(plan_source, profile)
            if plan_source is not None
            else self._planner.generate_plan(
                goal=profile.long_term_goal,
                weekly_hours=profile.weekly_hours,
                teaching_style=profile.teaching_style,
                direct_answer_policy=profile.answer_policy,
            )
        )

        resolved_focus_area = focus_area or (memory_snapshot.coach_anchor if memory_snapshot else None) or None
        resolved_defaults = coach_defaults or {}
        review_cadence = str(resolved_defaults.get("review_cadence") or "").strip()
        review_reminder_mode = str(resolved_defaults.get("review_reminder_mode") or "").strip()
        working_set_mode = str(resolved_defaults.get("working_set_mode") or "").strip()
        derived_weaknesses: list[WeaknessRecord] = []
        if memory_snapshot and memory_snapshot.top_weakness and not resolved_focus_area:
            derived_weaknesses.append(
                WeaknessRecord(
                    concept=memory_snapshot.top_weakness,
                    reason=(
                        memory_snapshot.weaknesses[0]
                        if memory_snapshot.weaknesses
                        else "Recent coaching friction is clustering here."
                    ),
                    severity=2,
                    updated_at=utc_now(),
                    next_review_at=utc_now(),
                )
            )

        recommendation = self._planner.recommend_next_task(
            NextTaskContext(
                plan=plan,
                weaknesses=derived_weaknesses,
                mastery=[],
                due_reviews=list(memory_snapshot.due_reviews) if memory_snapshot else [],
                resources=[],
                recent_attempts=list(recent_attempts or []),
                session_summary=memory_snapshot.recent_summary if memory_snapshot else None,
                focus_override=resolved_focus_area,
            )
        )
        if review_cadence == "active" and recommendation.review:
            recommendation.reason = "Active review cadence keeps this due item in the foreground."
        elif review_cadence == "light" and recommendation.review:
            recommendation.reason = "Light review cadence keeps this due item in the background until it is needed."
        if review_reminder_mode == "ahead" and recommendation.review:
            if recommendation.metadata.get("review_surface_mode") != "ahead":
                recommendation.prompt = f"Surface this review ahead of the next lane change: {recommendation.prompt}"
        elif review_reminder_mode == "digest" and recommendation.review:
            if recommendation.metadata.get("review_surface_mode") != "digest":
                recommendation.prompt = f"Bundle this review with adjacent follow-ups rather than interrupting often: {recommendation.prompt}"
        if working_set_mode == "focused" and not recommendation.review:
            recommendation.prompt = f"Use a focused working set and stay inside the smallest local boundary: {recommendation.prompt}"
        elif working_set_mode == "focused" and recommendation.review:
            recommendation.prompt = f"Use a focused working set while you revisit this review item: {recommendation.prompt}"
        elif working_set_mode == "broad" and not recommendation.review:
            recommendation.prompt = f"It is okay to reference directly connected context while still keeping the slice narrow: {recommendation.prompt}"
        return self._recommendation_to_task_spec(recommendation, response_language)

    def _recommendation_to_task_spec(
        self,
        recommendation: NextTaskRecommendation,
        response_language: str | None,
    ) -> ApiTaskSpec:
        localized_title = self._localize_task_title(
            recommendation.title,
            recommendation.review,
            response_language,
        )
        localized_prompt = self._localize_task_prompt(
            recommendation.prompt,
            recommendation.title,
            response_language,
        )
        acceptance_items = [
            self._localize_task_line(item, response_language)
            for item in recommendation.acceptance_criteria
        ]
        verification_items = [
            self._localize_task_line(item, response_language)
            for item in recommendation.verification_hints
        ]
        acceptance_lines = "\n".join(f"- {item}" for item in acceptance_items)
        verification_lines = "\n".join(f"- {item}" for item in verification_items)
        natural_language_goal = localized_prompt
        if acceptance_lines:
            natural_language_goal += (
                localized_text("\n\nAcceptance:\n", "\n\n验收标准：\n", response_language)
                + acceptance_lines
            )
        if verification_lines:
            natural_language_goal += (
                localized_text("\n\nVerify by:\n", "\n\n先这样验证：\n", response_language)
                + verification_lines
            )

        return ApiTaskSpec(
            id=recommendation.task_id,
            title=localized_title,
            natural_language_goal=natural_language_goal,
            inputs=[
                localized_text("Current project context", "当前项目上下文", response_language),
                localized_text("Current file or selected code when relevant", "当前文件或相关选区", response_language),
                localized_text("Existing plan and memory state", "当前计划与训练记忆", response_language),
            ],
            outputs=[
                localized_text("One reviewable implementation slice", "一个可评审的小实现切片", response_language),
                localized_text("A concrete verification result", "一个具体的验证结果", response_language),
                localized_text("A short reflection note", "一段简短复盘", response_language),
            ],
            constraints=[
                localized_text("Do not broaden into a refactor.", "不要扩散成重构。", response_language),
                localized_text("Keep the change small enough to review in one pass.", "改动必须小到可以一遍看完。", response_language),
            ],
            edge_cases=[
                localized_text("What should fail if the patch is still wrong?", "如果这次补丁仍然错误，哪里应该先暴露问题？", response_language),
                localized_text("Which boundary or branch needs explicit coverage?", "哪个边界或分支需要显式覆盖？", response_language),
            ],
            failure_conditions=[
                localized_text("The task turns into explanation without a visible patch.", "任务只停留在解释，没有落成可见补丁。", response_language),
                localized_text("The learner solves the easy path but skips the stated pressure point.", "只解决了简单路径，没有真正碰到这轮压力点。", response_language),
            ],
            verification_strategy=verification_items
            or [
                localized_text("Run the smallest relevant check.", "运行最小相关检查。", response_language),
                localized_text("Explain why the patch now holds.", "说明为什么这次补丁现在成立。", response_language),
            ],
            metadata={
                "concepts": list(recommendation.concepts),
                "acceptance_criteria": acceptance_items,
                "source": recommendation.metadata.get("source"),
                "source_phase_id": recommendation.metadata.get("phase_id"),
                "pace": recommendation.metadata.get("pace"),
                "review": recommendation.review,
                "focus_override": recommendation.metadata.get("focus_override"),
            },
        )
    def _localize_task_title(self, title: str, is_review: bool, language: str | None) -> str:
        if language != "zh-CN":
            return title
        if is_review and title.startswith("Review: "):
            return "复习：" + title.removeprefix("Review: ")
        if ": " in title:
            phase, remainder = title.split(": ", 1)
            phase_map = {
                "Foundation": "基础",
                "Practice": "练习",
                "Integration": "整合",
                "Next exercise": "下一练习",
            }
            localized_phase = phase_map.get(phase)
            if localized_phase:
                return f"{localized_phase}：{remainder}"
        return title

    def _localize_task_prompt(
        self,
        prompt: str,
        title: str,
        language: str | None,
    ) -> str:
        if language != "zh-CN":
            return prompt

        localized = prompt
        prefix_replacements = {
            "Use a focused working set and stay inside the smallest local boundary: ": "使用聚焦 working set，并把边界收在最小本地范围内：",
            "Use a focused working set while you revisit this review item: ": "复习这个条目时也保持聚焦 working set：",
            "It is okay to reference directly connected context while still keeping the slice narrow: ": "可以参考直接相关的上下文，但仍要把切片保持得很窄：",
            "Surface this review ahead of the next lane change: ": "在切换到下一条主线前，先把这个复习项提到前面：",
            "Bundle this review with adjacent follow-ups rather than interrupting often: ": "把这个复习项和相邻跟进动作打包处理，不要频繁打断：",
        }
        for english_prefix, chinese_prefix in prefix_replacements.items():
            if localized.startswith(english_prefix):
                localized = chinese_prefix + localized.removeprefix(english_prefix)
                break

        title_head = title.split(": ", 1)[0]
        phase_map = {
            "Foundation": "基础",
            "Practice": "练习",
            "Integration": "整合",
            "Next exercise": "下一练习",
        }
        localized_phase = phase_map.get(title_head, title_head)
        progression_prefix = f"You are in the '{title_head}' phase. Write one small, reviewable change that practices "
        progression_suffix = ". Stay inside the current project context, keep the slice narrow, and match the teaching style "
        if localized.startswith(progression_prefix) and progression_suffix in localized:
            concepts, _, tail = localized[len(progression_prefix) :].partition(progression_suffix)
            teaching_style = tail.strip().strip(".").strip("'")
            return (
                f"你现在处在「{localized_phase}」阶段。写一个小而可评审的改动来练习 {concepts}。"
                f"保持在当前项目上下文里，把切片收窄，并遵循「{teaching_style}」的 teaching style。"
            )

        weakness_prefix = "Re-implement a focused exercise on '"
        weakness_mid = "' and explicitly avoid this failure mode: "
        if localized.startswith(weakness_prefix) and weakness_mid in localized:
            concept, _, reason = localized[len(weakness_prefix) :].partition(weakness_mid)
            return f"围绕「{concept}」重新做一个聚焦练习，并明确避开这个失败模式：{reason.rstrip('.')}"

        return localized

    def _localize_task_line(self, line: str, language: str | None) -> str:
        if language != "zh-CN":
            return line

        direct_map = {
            "Add or run one check that proves the change, not only a happy path read-through.": "添加或运行一个检查来证明这次改动成立，而不只是走读最简单的 happy path。",
            "State which existing file, feature boundary, or workflow this integrates with.": "说明这次改动接入了哪个现有文件、功能边界或工作流。",
            "Write one short reflection about why this is the right next move now.": "写一段简短复盘，说明为什么这一步是当前最合适的下一步。",
            "Confirm the patch is still reviewable in one pass.": "确认这次补丁仍然可以一遍评审完。",
            "Point at the exact nearby code path, branch, or file context this review is tied to.": "指出这个复习项所对应的精确附近代码路径、分支或文件上下文。",
            "Keep the patch small enough that nearby review items could still be bundled after this one.": "让补丁保持足够小，这样附近的复习项之后仍然可以继续打包处理。",
            "Run the smallest relevant check or manual verification.": "运行最小相关检查，或做一次最小手动验证。",
            "Confirm the specific review reason is now resolved, not merely discussed.": "确认这次真正解决了具体复习原因，而不只是口头讨论。",
            "Verify the nearby linked context directly, not just the easiest happy path.": "直接验证附近关联上下文，不要只验证最容易的 happy path。",
            "Repeat the weak branch once more after the first pass so the concept sticks.": "第一遍通过后，把薄弱分支再走一遍，让这个概念真正留下来。",
            "Show the exact edge, branch, or boundary that used to fail.": "展示过去会失败的那个精确边界、分支或条件。",
            "Explain how the new patch avoids repeating the same mistake.": "说明这次新补丁是怎样避免重复同一个错误的。",
            "Verify the previously weak path directly.": "直接验证之前薄弱的那条路径。",
            "Keep the patch smaller than a refactor.": "把补丁控制在小于一次重构的范围内。",
        }
        if line in direct_map:
            return direct_map[line]

        if line.startswith("Implement one narrow patch centered on ") and line.endswith("."):
            concept = line.removeprefix("Implement one narrow patch centered on ").removesuffix(".")
            return f"围绕 {concept} 实现一个收口很窄的小补丁。"

        if line.startswith("Connect ") and line.endswith(" without losing the narrow slice boundary."):
            concept = line.removeprefix("Connect ").removesuffix(" without losing the narrow slice boundary.")
            return f"把 {concept} 连接进来，但不要丢掉这次窄切片的边界。"

        if line.startswith("Check the concrete behavior around ") and line.endswith(" first."):
            concept = line.removeprefix("Check the concrete behavior around ").removesuffix(" first.")
            return f"先检查 {concept} 附近的具体行为。"

        if line.startswith("Land the specific review move around '") and "': " in line:
            concept, _, task_hint = line.removeprefix("Land the specific review move around '").partition("': ")
            return f"围绕「{concept}」落下这次明确的复习动作：{task_hint}"

        if line.startswith("Land one small patch that exercises '") and line.endswith("'."):
            concept = line.removeprefix("Land one small patch that exercises '").removesuffix("'.")
            return f"落一个围绕「{concept}」的小补丁来完成这次练习。"

        return line

    def _api_plan_to_domain(self, plan: ApiLearningPlan, profile: UserProfile) -> LearningPlan:
        phases: list[PlanPhase] = []
        phase_title_tokens = {"foundation", "practice", "integration"}
        if plan.phases:
            for index, phase in enumerate(plan.phases):
                phase_id = plan.stages[index].id if index < len(plan.stages) else f"phase_{index}"
                source_text = " ".join([phase.title, phase.objective, *phase.exercises]).strip()
                extracted_concepts = [
                    concept
                    for concept in self._planner._extract_concepts(source_text)
                    if concept not in phase_title_tokens
                ]
                phases.append(
                    PlanPhase(
                        id=phase_id,
                        title=phase.title,
                        objective=phase.objective,
                        concepts=(
                            extracted_concepts[: max(1, self._planner._concept_budget(profile.weekly_hours))]
                            or ["implementation"]
                        ),
                        success_criteria=list(phase.exercises or ([phase.completion_signal] if phase.completion_signal else [])),
                    )
                )
        elif plan.stages:
            for stage in plan.stages:
                source_text = " ".join([stage.title, stage.goal, *stage.outcomes]).strip()
                extracted_concepts = [
                    concept
                    for concept in self._planner._extract_concepts(source_text)
                    if concept not in phase_title_tokens
                ]
                phases.append(
                    PlanPhase(
                        id=stage.id,
                        title=stage.title,
                        objective=stage.goal,
                        concepts=(
                            extracted_concepts[: max(1, self._planner._concept_budget(profile.weekly_hours))]
                            or ["implementation"]
                        ),
                        success_criteria=list(stage.outcomes),
                    )
                )
        else:
            regenerated = self._planner.generate_plan(
                goal=plan.objective or plan.summary or profile.long_term_goal,
                weekly_hours=profile.weekly_hours,
                teaching_style=profile.teaching_style,
                direct_answer_policy=profile.answer_policy,
            )
            return regenerated

        return LearningPlan(
            id=plan.id or plan.plan_id or f"plan_{uuid4().hex}",
            title=plan.title,
            objective=plan.objective or plan.summary or profile.long_term_goal,
            weekly_hours=profile.weekly_hours,
            direct_answer_policy=profile.answer_policy,
            teaching_style=profile.teaching_style,
            phases=phases,
            frozen=plan.frozen,
            current_phase_id=plan.current_stage_id or (phases[0].id if phases else None),
            metadata={
                "source": "api-plan",
                "current_step": plan.current_step,
                "why_now": plan.why_now,
                "verify_method": list(plan.verify_method),
                "blocked_reason": plan.blocked_reason,
                "next_after_current": plan.next_after_current,
            },
        )

    def _domain_plan_to_api(
        self,
        plan: LearningPlan,
        *,
        resource_ids: list[str],
        summary: str,
    ) -> ApiLearningPlan:
        current_phase = plan.phases[next(
            (index for index, phase in enumerate(plan.phases) if phase.id == plan.current_phase_id),
            0,
        )] if plan.phases else None
        next_phase = None
        if current_phase and plan.phases:
            current_index = next(
                (index for index, phase in enumerate(plan.phases) if phase.id == current_phase.id),
                0,
            )
            if current_index + 1 < len(plan.phases):
                next_phase = plan.phases[current_index + 1]
        return ApiLearningPlan(
            id=plan.id,
            title=plan.title,
            summary=summary,
            stages=[
                PlanStage(
                    id=phase.id,
                    title=phase.title,
                    goal=phase.objective,
                    outcomes=phase.success_criteria or [f"Practice {concept}" for concept in phase.concepts],
                    resources=list(resource_ids),
                    status="active" if phase.id == plan.current_phase_id else "pending",
                )
                for phase in plan.phases
            ],
            cadence=f"{plan.weekly_hours} hours/week",
            frozen=plan.frozen,
            current_stage_id=plan.current_phase_id,
            current_step=str(
                plan.metadata.get("current_step")
                or (current_phase.success_criteria[0] if current_phase and current_phase.success_criteria else current_phase.objective if current_phase else summary)
            ),
            why_now=str(plan.metadata.get("why_now") or summary),
            verify_method=list(plan.metadata.get("verify_method") or (current_phase.success_criteria if current_phase else [])),
            blocked_reason=str(plan.metadata.get("blocked_reason") or ""),
            next_after_current=str(
                plan.metadata.get("next_after_current")
                or (next_phase.objective if next_phase else "Review the result and decide whether to widen scope.")
            ),
        )

    def _plan_summary(self, goal: str, weekly_hours: int) -> str:
        if weekly_hours <= 3:
            return (
                f"Keep the plan for '{goal[:48]}' intentionally narrow: land one thin slice, verify it, then expand only after review."
            )
        if weekly_hours >= 8:
            return (
                f"Use the plan for '{goal[:48]}' to alternate fast implementation, review, and project-shaped integration without losing patch discipline."
            )
        return (
            f"Move '{goal[:48]}' forward through thin implementation slices, repeated checks, and staged integration."
        )

    def _active_stage_index(self, plan: ApiLearningPlan) -> int:
        if not plan.stages:
            return 0
        return next(
            (
                index
                for index, stage in enumerate(plan.stages)
                if stage.id == plan.current_stage_id or stage.status == "active"
            ),
            0,
        )

    def _stage_verify_method(
        self,
        stage: PlanStage | None,
        *,
        fallback: list[str] | None = None,
    ) -> list[str]:
        stage_outcomes = [item.strip() for item in (stage.outcomes if stage else []) if item and item.strip()]
        if stage_outcomes:
            return stage_outcomes[:3]
        fallback_lines = [item.strip() for item in (fallback or []) if item and item.strip()]
        return fallback_lines or ["Run the smallest relevant check."]

    def _normalize_subplan(
        self,
        plan_id: str,
        subplan: SubPlan,
        *,
        subplan_id: str | None = None,
        created_at: str | None = None,
    ) -> SubPlan:
        normalized = subplan.model_copy(deep=True)
        normalized.id = (subplan_id or normalized.id or f"subplan-{uuid4().hex[:8]}").strip()
        normalized.parent_plan_id = plan_id
        normalized.title = normalized.title.strip() or "Sub-plan"
        normalized.description = normalized.description.strip()
        normalized.stages = [stage.model_copy(deep=True) for stage in normalized.stages]
        normalized.status = normalized.status or "draft"
        normalized.progress_percent = max(0.0, min(100.0, float(normalized.progress_percent or 0.0)))
        normalized.created_at = created_at or normalized.created_at or utc_now().isoformat()
        normalized.updated_at = utc_now().isoformat()
        return normalized

    def _stage_matches_evidence(
        self,
        stage: PlanStage,
        evidence_items: list[EvidenceItem],
        evidence_tokens: list[str],
    ) -> bool:
        stage_texts = [stage.id, stage.title, stage.goal, *stage.outcomes]
        normalized_stage_texts = [self._normalize_text(item) for item in stage_texts if item]
        if not normalized_stage_texts:
            return False

        for evidence in evidence_items:
            evidence_texts = [
                evidence.target_plan_stage_id,
                evidence.summary,
                evidence.outcome,
                evidence.source_card_id,
                *evidence.concepts,
            ]
            normalized_evidence_texts = [self._normalize_text(item) for item in evidence_texts if item]
            if evidence.target_plan_stage_id and evidence.target_plan_stage_id.strip() == stage.id.strip():
                return True
            for stage_text in normalized_stage_texts:
                for evidence_text in normalized_evidence_texts:
                    if stage_text == evidence_text or stage_text in evidence_text or evidence_text in stage_text:
                        return True
                for token in evidence_tokens:
                    if token and token in stage_text:
                        return True
        return False

    def _evidence_tokens(self, evidence_items: list[EvidenceItem]) -> list[str]:
        tokens: list[str] = []
        for evidence in evidence_items:
            for value in [evidence.summary, evidence.outcome, evidence.source_card_id, evidence.target_plan_stage_id, *evidence.concepts]:
                normalized = self._normalize_text(value)
                if not normalized:
                    continue
                if normalized not in tokens:
                    tokens.append(normalized)
        return tokens

    def _normalize_text(self, value: str) -> str:
        return " ".join(str(value or "").replace("_", " ").replace("-", " ").split()).strip().lower()

    def _default_next_after_current(
        self,
        plan: ApiLearningPlan,
        *,
        stage_index: int,
        runtime: dict[str, Any] | None = None,
        existing: dict[str, Any] | None = None,
    ) -> str:
        candidate = ""
        if plan.stages and stage_index + 1 < len(plan.stages):
            candidate = plan.stages[stage_index + 1].goal.strip()
        return live_plan_next_after_current(
            plan=plan,
            runtime=runtime,
            existing=existing,
            next_after_current=candidate,
            next_stage_goal=candidate,
        )

    def _recovery_verify_method(
        self,
        *,
        blocker: str,
        fallback: list[str],
        repeated_failure: bool,
    ) -> list[str]:
        lines: list[str] = []
        if blocker:
            lines.append(f"Reproduce the blocker directly: {blocker}")
        lines.append("Run the smallest relevant check before widening again.")
        if repeated_failure:
            lines.append("Do not broaden the patch until this reduced recovery step passes once.")
        if not lines:
            return fallback or ["Run the smallest relevant check."]
        return list(dict.fromkeys([item for item in lines if item]))[:3]

    def advance_plan_after_success(
        self,
        current: ApiLearningPlan | None,
        task: ApiTaskSpec | None,
        *,
        passed: bool,
        verified_result: str | None = None,
        summary: str | None = None,
        next_step: str | None = None,
        runtime: dict[str, Any] | None = None,
        existing: dict[str, Any] | None = None,
    ) -> ApiLearningPlan | None:
        if current is None or not passed or not current.stages:
            return current

        updated = current.model_copy(deep=True)
        current_index = self._active_stage_index(updated)
        cleaned_summary = (summary or "").strip()
        cleaned_next_step = (next_step or "").strip()
        current_stage = updated.stages[current_index]
        recovered_step = self._live_recovered_step(runtime=runtime, existing=existing)
        live_plan = self._formal_plan_is_live(plan=current, runtime=runtime, existing=existing)

        for index, stage in enumerate(updated.stages):
            if index < current_index:
                stage.status = "completed"
            elif index == current_index:
                stage.status = "completed"
            else:
                stage.status = "pending"

        if current_index < len(updated.stages) - 1:
            next_stage = updated.stages[current_index + 1]
            next_stage.status = "active"
            updated.current_stage_id = next_stage.id
            next_label = live_coach_stage_label(
                plan=current,
                runtime=runtime,
                existing=existing,
                stage_title=next_stage.title,
            )
            if cleaned_next_step:
                updated.current_step = cleaned_next_step
            elif not live_plan:
                updated.current_step = recovered_step or next_stage.goal or ""
            else:
                updated.current_step = next_stage.goal or updated.current_step
            updated.why_now = cleaned_summary or (
                f"The previous slice passed, so move into '{next_label}' through one narrow, reviewable step."
                if next_label
                else "The previous slice passed, so move into the recovered next step through one narrow, reviewable step."
            )
            updated.verify_method = self._stage_verify_method(next_stage, fallback=current.verify_method)
            updated.next_after_current = self._default_next_after_current(
                current,
                stage_index=current_index + 1,
                runtime=runtime,
                existing=existing,
            )
        else:
            updated.current_stage_id = current_stage.id
            updated.current_step = (
                cleaned_next_step
                or "Preserve the verified result, then decide whether to widen scope or open a new training loop."
            )
            updated.why_now = cleaned_summary or (
                "The active stage passed, so preserve the verified result before widening the work."
            )
            updated.verify_method = self._stage_verify_method(current_stage, fallback=current.verify_method)
            updated.next_after_current = (
                "Review the verified result and decide whether the learner is ready for a fresh stage."
            )
        updated.blocked_reason = ""
        if task and not cleaned_next_step and not updated.current_step:
            updated.current_step = task.title
        updated.current_step = self._live_chrome_text(
            plan=current,
            text=updated.current_step,
            runtime=runtime,
            existing=existing,
        )
        updated.why_now = self._live_chrome_text(
            plan=current,
            text=updated.why_now,
            runtime=runtime,
            existing=existing,
        )
        updated.updated_at = utc_now().isoformat()
        return updated

    def replan_after_failure(
        self,
        current: ApiLearningPlan | None,
        task: ApiTaskSpec | None,
        *,
        blocker: str | None = None,
        summary: str | None = None,
        next_step: str | None = None,
        repeated_failure: bool = False,
        focus_area: str | None = None,
        runtime: dict[str, Any] | None = None,
        existing: dict[str, Any] | None = None,
    ) -> ApiLearningPlan | None:
        if current is None:
            return current

        updated = current.model_copy(deep=True)
        current_index = self._active_stage_index(updated)
        current_stage = updated.stages[current_index] if updated.stages else None
        stage_label = live_coach_stage_label(
            plan=current,
            runtime=runtime,
            existing=existing,
            stage_title=current_stage.title if current_stage else "",
        )
        previous_step = self._live_chrome_text(
            plan=current,
            text=(
                current.current_step.strip()
                or (current_stage.goal.strip() if current_stage and current_stage.goal else "")
                or (task.title.strip() if task else "")
                or (focus_area or "").strip()
                or current.summary
                or current.title
            ),
            runtime=runtime,
            existing=existing,
        )
        blocker_text = (blocker or "").strip() or (summary or "").strip() or "The current slice is blocked."
        narrowed_seed = self._live_chrome_text(
            plan=current,
            text=(
                (next_step or "").strip()
                or (focus_area or "").strip()
                or (task.title.strip() if task else "")
                or (current_stage.goal.strip() if current_stage and current_stage.goal else "")
                or previous_step
            ),
            runtime=runtime,
            existing=existing,
        )
        if repeated_failure:
            recovery_step = (
                f"Shrink the slice to one boundary: {narrowed_seed}"
                if narrowed_seed
                else "Shrink the slice to one boundary and re-run the smallest relevant check."
            )
        elif (next_step or "").strip():
            recovery_step = (next_step or "").strip()
        elif stage_label:
            recovery_step = f"Recover the smallest failing boundary inside '{stage_label}'."
        elif narrowed_seed:
            recovery_step = f"Recover the smallest failing boundary around {narrowed_seed}."
        else:
            recovery_step = "Recover the smallest failing boundary first."

        if current_stage:
            current_stage.status = "active"
            updated.current_stage_id = current_stage.id

        leftover_live = leftover_formal_plan_is_live_for_fill(
            plan=current,
            runtime=runtime,
            existing=existing,
        )
        leftover_formal_block = str(current.blocked_reason or "").strip()
        if leftover_live:
            updated.blocked_reason = blocker_text
        elif blocker_text and blocker_text != leftover_formal_block:
            updated.blocked_reason = blocker_text
        else:
            updated.blocked_reason = live_plan_blocked_reason(
                plan=current,
                runtime=runtime,
                existing=existing,
                blocked_reason="",
            )
        updated.current_step = self._live_chrome_text(
            plan=current,
            text=recovery_step,
            runtime=runtime,
            existing=existing,
        )
        updated.why_now = self._live_chrome_text(
            plan=current,
            text=(
                "Repeated failure means the plan should shrink the live move before widening again."
                if repeated_failure
                else (summary or "").strip()
                or (
                    f"Stay inside '{stage_label}' and recover the smallest failing boundary first."
                    if stage_label
                    else "Recover the smallest failing boundary first."
                )
            ),
            runtime=runtime,
            existing=existing,
        )
        updated.verify_method = self._recovery_verify_method(
            blocker=blocker_text,
            fallback=list(current.verify_method),
            repeated_failure=repeated_failure,
        )
        if previous_step and updated.current_step.strip() != previous_step.strip():
            updated.next_after_current = f"After this recovery step passes, return to: {previous_step}"
        else:
            updated.next_after_current = current.next_after_current or self._default_next_after_current(
                current,
                stage_index=current_index,
                runtime=runtime,
                existing=existing,
            )
        updated.next_after_current = self._live_chrome_text(
            plan=current,
            text=updated.next_after_current,
            runtime=runtime,
            existing=existing,
        )
        updated.updated_at = utc_now().isoformat()
        return updated

    def advance_plan_from_learning_signal(
        self,
        current: ApiLearningPlan | None,
        task: ApiTaskSpec | None,
        *,
        outcome: str,
        summary: str | None = None,
        verified_result: str | None = None,
        blocked_reason: str | None = None,
        abandoned_reason: str | None = None,
        repetition_count: int | None = None,
        focus_area: str | None = None,
        next_step_bias: str | None = None,
        runtime: dict[str, Any] | None = None,
        existing: dict[str, Any] | None = None,
    ) -> ApiLearningPlan | None:
        if current is None:
            return current

        normalized_outcome = outcome.strip().lower()
        cleaned_summary = (summary or "").strip()
        cleaned_verified = (verified_result or "").strip()
        blocker = (blocked_reason or "").strip() or (abandoned_reason or "").strip()
        repeated_failure = (
            normalized_outcome in {"repeated_error", "task_abandoned", "blocked"}
            or (repetition_count or 0) >= 2
            or (next_step_bias or "").strip().lower() == "shrink"
        )

        if normalized_outcome in {"code_landed", "tests_passed"}:
            return self.advance_plan_after_success(
                current,
                task,
                passed=True,
                verified_result=cleaned_verified,
                summary=cleaned_summary or cleaned_verified,
                runtime=runtime,
                existing=existing,
            )

        if normalized_outcome == "concept_answered_correctly":
            updated = current.model_copy(deep=True)
            updated.blocked_reason = ""
            if cleaned_summary:
                updated.why_now = cleaned_summary
            updated.next_after_current = (
                "Apply this understanding in the next implementation slice, then verify it in code."
            )
            updated.updated_at = utc_now().isoformat()
            return updated

        if normalized_outcome in {"repeated_error", "task_abandoned", "evaluation", "blocked"} or blocker:
            return self.replan_after_failure(
                current,
                task,
                blocker=blocker or cleaned_summary,
                summary=cleaned_summary,
                next_step=None,
                repeated_failure=repeated_failure,
                focus_area=focus_area,
                runtime=runtime,
                existing=existing,
            )

        return current
