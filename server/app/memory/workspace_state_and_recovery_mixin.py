from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from ..core.event_ledger import (
    EVENT_REVIEW_SCHEDULED,
)
from ..core.models import (
    EvidenceItem,
    ResourceRecord,
    TeachingKnowledgeAsset,
    UserProfile,
    WorkspaceUnderstandingSnapshot,
)
from .models import (
    UserFeedbackRecord,
    WeaknessRecord,
    utc_now,
)
from .proactive_budget import (
    PROACTIVE_BUDGET_KEY,
)
from .proactive_budget import (
    record_proactive_nudge as merge_proactive_nudge,
)
from .review_intervention import (
    REVIEW_INTERVENTION_KEY,
    ReviewInterventionBudget,
    derive_review_budget,
    merge_review_engagement,
    merge_review_offer,
    merge_review_refusal,
)
from .semantic_helpers import (
    _normalize_source_freshness,
)
from .structured_memory_service import (
    StructuredMemoryService,
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
    apply_training_chrome_scope,
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
    live_evidence_binding,
    normalize_latest_adaptation_guide,
    normalize_latest_affect_state,
    normalize_latest_coach_focus,
    normalize_latest_coach_turn,
    normalize_latest_coaching_adaptation,
    normalize_latest_current_task,
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
    select_plan_runtime_for_scope,
    select_provider_capability_for_scope,
    select_streaming_checkpoint_for_scope,
    select_training_chrome_for_scope,
    select_training_record_for_scope,
    stamp_workspace_scope,
)

logger = logging.getLogger(__name__)


class WorkspaceStateAndRecoveryMixin:
    if TYPE_CHECKING:
        _event_ledger: Any
        _leftover_persist_context: Any
        _live_training_persist_chrome: Any
        _persist_structured: Any
        _resolve_workspace_for_write: Any
        _save_teaching_asset: Any
        _structured_for: Any
        enqueue_evidence: Any
        evidence_queue: Any
        get_card: Any
        get_cards: Any
        repository: Any
        snapshot: Any
        upsert_card: Any

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

    def weakness_records(self, workspace_id: str) -> list[WeaknessRecord]:
        return list(self._structured_for(workspace_id)._weaknesses.values())

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

    def review_intervention_budget(
        self,
        workspace_id: str,
        *,
        due_count: int | None = None,
        session_id: str = "",
        message: str = "",
        now: datetime | None = None,
    ) -> ReviewInterventionBudget:
        """Read the current intervention budget for this workspace."""
        structured = self._structured_for(workspace_id)
        workspace = dict(structured._workspace)
        if due_count is None:
            due_count = len(self.snapshot(workspace_id).due_reviews)
        return derive_review_budget(
            workspace,
            due_count=due_count,
            now=now or utc_now(),
            session_id=session_id,
            message=message,
        )

    def mark_workspace_active(self, workspace_id: str, *, now: datetime | None = None) -> None:
        structured = self._structured_for(workspace_id)
        structured.update_workspace(last_active_at=(now or utc_now()).isoformat())
        self._persist_structured(workspace_id)

    def record_review_offer(
        self,
        workspace_id: str,
        *,
        session_id: str = "",
        now: datetime | None = None,
    ) -> None:
        moment = now or utc_now()
        structured = self._structured_for(workspace_id)
        state = merge_review_offer(
            structured._workspace.get(REVIEW_INTERVENTION_KEY),
            now=moment,
            session_id=session_id,
        )
        structured.update_workspace(
            review_intervention=state,
            last_active_at=moment.isoformat(),
        )
        self._persist_structured(workspace_id)

    def record_proactive_nudge(
        self,
        workspace_id: str,
        *,
        kind: str,
        dedup_key: str,
        session_id: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        moment = now or utc_now()
        structured = self._structured_for(workspace_id)
        state = merge_proactive_nudge(
            structured._workspace.get(PROACTIVE_BUDGET_KEY),
            now=moment,
            kind=kind,
            dedup_key=dedup_key,
            session_id=session_id,
        )
        structured.update_workspace(
            **{
                PROACTIVE_BUDGET_KEY: state,
                "last_active_at": moment.isoformat(),
            }
        )
        self._persist_structured(workspace_id)
        return state

    def record_review_refusal(
        self,
        workspace_id: str,
        *,
        reason: str = "decline",
        session_id: str = "",
        now: datetime | None = None,
    ) -> None:
        moment = now or utc_now()
        structured = self._structured_for(workspace_id)
        state = merge_review_refusal(
            structured._workspace.get(REVIEW_INTERVENTION_KEY),
            now=moment,
            reason=reason,
            session_id=session_id,
        )
        structured.update_workspace(
            review_intervention=state,
            last_active_at=moment.isoformat(),
        )
        self._persist_structured(workspace_id)

    def record_review_engagement(
        self,
        workspace_id: str,
        *,
        session_id: str = "",
        now: datetime | None = None,
    ) -> None:
        moment = now or utc_now()
        structured = self._structured_for(workspace_id)
        state = merge_review_engagement(
            structured._workspace.get(REVIEW_INTERVENTION_KEY),
            now=moment,
            session_id=session_id,
        )
        structured.update_workspace(
            review_intervention=state,
            last_active_at=moment.isoformat(),
        )
        self._persist_structured(workspace_id)

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
        leftover_plans: list[Any] | tuple[Any, ...] | None = []
        list_plans = getattr(self.repository, "list_plans", None)
        if callable(list_plans):
            leftover_plans = cast("list[Any]", list_plans(workspace_id))
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
        plan = self.repository.get_latest_plan(workspace_id)
        live_plan = formal_plan_is_live_runtime_identity(plan=plan, runtime=existing, existing=existing)
        if live_plan and plan and plan.frozen:
            return None
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
        if live_plan and plan:
            # Adoption advances the same formal plan. Leaving its old step in
            # SQLite would make the next hydrate reject the plan as leftover.
            plan.current_step = str(record.get("current_step") or "")
            plan.blocked_reason = str(record.get("blocked_reason") or "")
            plan.why_now = str(record.get("why_now") or "")
            plan.verify_method = list(record.get("verify_method") or [])
            plan.next_after_current = str(record.get("next_after_current") or "")
            plan.updated_at = utc_now().isoformat()
            record["current_stage_id"] = plan.current_stage_id
            from ..training.plan_revision import save_plan_advancing_revision

            save_plan_advancing_revision(self.repository, workspace_id, plan)
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
        if card_status in {"implemented", "completed", "archived", "skipped"}:
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
        if str(getattr(card, "status", "") or "").strip().lower() in {"skipped", "archived"}:
            return ""
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
        require_live: bool = True,
        rating: str | None = None,
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
        if require_live:
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
        concept = str(
            getattr(card, "target_skill", "")
            or getattr(card, "focus_area", "")
            or cleaned_card_id
        ).strip()
        if scheduler.get_card_state(cleaned_card_id) is None:
            created = scheduler.create_card(
                cleaned_card_id,
                concept or cleaned_card_id,
                card_type=str(getattr(card, "card_type", "") or "practice"),
                focus_area=str(getattr(card, "focus_area", "") or "").strip() or None,
            )
            created.project_scope = "current_project"

        rating_map = {
            "again": TrainingRating.AGAIN,
            "hard": TrainingRating.HARD,
            "good": TrainingRating.GOOD,
            "easy": TrainingRating.EASY,
        }
        requested_rating = rating_map.get(str(rating or "").strip().lower())
        rating_enum = requested_rating or (
            TrainingRating.GOOD if passed else TrainingRating.AGAIN
        )
        result = scheduler.process_review(cleaned_card_id, rating_enum)
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
        # One transaction boundary for verify: the card update, FSRS state and
        # mastery schedule are written by the single _persist_structured call
        # below. Persisting the card here first could leave a card marked
        # verified with no schedule if the second write failed.
        self.upsert_card(
            workspace_id,
            card.model_copy(
                update={
                    "difficulty": next_difficulty,
                    "review_schedule": review_schedule,
                }
            ),
            persist=False,
        )
        scheduled_mastery = None
        scheduled_concept = ""
        if result.next_due is not None:
            # A card's evidence is labelled with its target skill AND its focus
            # area, and mastery may have been recorded under either. Attach the
            # schedule to the first of them that already has a record — never
            # mint one. Trying only the target skill left every card whose
            # mastery lived under its focus area on the heuristic schedule,
            # so its recall round never landed as an FSRS row.
            for candidate in (
                concept,
                str(getattr(card, "focus_area", "") or "").strip(),
            ):
                if not candidate:
                    continue
                scheduled_mastery = structured.schedule_mastery_review(
                    candidate,
                    next_review_at=result.next_due,
                    due_date=result.next_due,
                    fsrs_state=updated_state.state,
                    stability=result.new_stability,
                    difficulty=result.new_difficulty,
                    reps=result.reps,
                    lapses=result.lapses,
                    step=result.step,
                    last_reviewed_at=result.last_reviewed_at,
                    interval=result.new_interval,
                    retrievability=result.retrievability,
                )
                if scheduled_mastery is not None:
                    scheduled_concept = candidate
                    break
        self._persist_structured(workspace_id)
        if result.next_due is not None and self._event_ledger is not None:
            due_at = result.next_due.isoformat()
            try:
                self._event_ledger.record_event(
                    EVENT_REVIEW_SCHEDULED, project_id=workspace_id, scope="learning",
                    idempotency_key=f"review-scheduled:{cleaned_card_id}:{due_at}",
                    payload_ref={"card_id": cleaned_card_id, "title": concept, "next_due": due_at},
                )
            except Exception:
                logger.exception("Could not record review scheduling in the event ledger")
        return {
            "card_id": cleaned_card_id,
            "rating": rating_enum.name.lower(),
            "interval_days": result.new_interval,
            "next_due": result.next_due.isoformat() if result.next_due else None,
            "stability": result.new_stability,
            "reps": result.reps,
            "lapses": result.lapses,
            "elapsed_days": result.elapsed_days,
            "difficulty": next_difficulty,
            "fsrs_difficulty": payload.get("difficulty"),
            "global_promoted": False,
            "minted_card": False,
            "mastery_review_at": (
                scheduled_mastery.next_review_at.isoformat()
                if scheduled_mastery and scheduled_mastery.next_review_at
                else None
            ),
            "mastery_concept": scheduled_concept or None,
        }

    def schedule_training_card_recall(
        self,
        workspace_id: str,
        *,
        training_card_id: str,
        passed: bool,
        rating: str | None = None,
    ) -> dict[str, Any] | None:
        """FSRS schedule for a recall answer.

        Unlike Verify, recall is not tied to the selected practice card: a due
        flashcard can be answered while another card is selected. The card must
        still exist in this workspace, and the scheduler's ``elapsed_days`` is
        what decides whether this answer is delayed-retention evidence.
        """
        return self.schedule_live_training_card_fsrs_after_verify(
            workspace_id,
            training_card_id=training_card_id,
            passed=passed,
            require_live=False,
            rating=rating,
        )

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
        hop: dict[str, Any] | None = None
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
        if current_step and hop is not None:
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
