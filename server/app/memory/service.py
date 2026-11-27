from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from typing import Any, Callable
from uuid import uuid4

from ..core.event_ledger import (
    EVENT_EVALUATION_FEEDBACK_RECORDED,
    EventLedgerService,
)
from ..core.models import (
    CoachDefaults,
    DependencyMasterySnapshot,
    DependencySkillItemSnapshot,
    DependencySkillMapSnapshot,
    GlobalMemory,
    GlobalMemoryCapability,
    GlobalMemoryGrowthRecord,
    LearningActivityEntry,
    MemoryShareCategory,
    MemoryShareGrant,
    MemorySnapshot,
    ResourceRecord,
    TeachingKnowledgeAsset,
    TrainingCardCandidateSnapshot,
)
from ..db.repository import TrainerRepository
from ..resources.asset_library import AssetLibraryService
from ..training.handoff import (
    TrainingHandoffGenerator,
)
from .cards_and_evidence_mixin import CardsAndEvidenceMixin
from .coaching_adaptation_mixin import (
    CoachingAdaptationMixin,
    _localized_memory_text,
    _workspace_language,
)
from .drills_and_reflection_mixin import DrillsAndReflectionMixin
from .learning_outcomes_mixin import LearningOutcomesMixin
from .models import (
    MemorySnapshot as LaneMemorySnapshot,
)
from .models import (
    WeaknessRecord,
    utc_now,
)
from .onboarding_extraction import OnboardingExtractionMixin
from .review_scheduler import ReviewScheduler
from .semantic import HashingEmbedder as HashingEmbedder
from .semantic_helpers import SemanticMemoryService as SemanticMemoryService
from .snapshot_builder import build_memory_snapshot
from .structured_memory_service import StructuredMemoryService as StructuredMemoryService
from .teaching_asset_catalog_mixin import TeachingAssetCatalogMixin
from .training_handoff_return_mixin import TrainingHandoffReturnMixin
from .training_reliability_mixin import TrainingReliabilityMixin
from .transfer_skills import (
    build_transfer_skill_state_record,
    normalize_transfer_skill_state_record,
    resolve_skill_scene_key,
    should_promote_transferable_skill,
    unique_transfer_scenes,
)
from .workspace_recovery import (
    CURRENT_TASK_KEY,
    PLAN_RUNTIME_KEY,
    live_training_persist_chrome,
    normalize_latest_current_task,
    select_plan_runtime_for_scope,
)
from .workspace_state_and_recovery_mixin import WorkspaceStateAndRecoveryMixin

logger = logging.getLogger(__name__)


class MemoryService(
    CoachingAdaptationMixin,
    OnboardingExtractionMixin,
    TeachingAssetCatalogMixin,
    TrainingHandoffReturnMixin,
    TrainingReliabilityMixin,
    WorkspaceStateAndRecoveryMixin,
    CardsAndEvidenceMixin,
    DrillsAndReflectionMixin,
    LearningOutcomesMixin,
):
    def __init__(self, repository: TrainerRepository, structured: StructuredMemoryService | None = None,
                 *, event_ledger: EventLedgerService | None = None) -> None:
        self.repository = repository
        self._event_ledger = event_ledger
        self._asset_library = AssetLibraryService(repository)
        self._structured_by_workspace: dict[str, StructuredMemoryService] = {}
        # The revision this process loaded, and the payload it loaded it from.
        # They let a write tell "the stored record changed under me" from
        # "nothing else touched it", so two sidecars on one LibraryRoot do not
        # erase each other's keys.
        self._structured_revisions: dict[str, int] = {}
        self._structured_baselines: dict[str, dict[str, Any]] = {}
        self._default_structured = structured
        self._review_scheduler = ReviewScheduler()
        self._resource_dedupe_hook: Callable[[list[ResourceRecord]], list[ResourceRecord]] | None = None
        self._card_ledger: list[dict[str, Any]] = []
        self._authoritative_training_handoffs: dict[tuple[str, str], Any] = {}
        self._training_handoff_records: dict[str, Any] = {}
        # Per-workspace memoization of snapshot(): every lane/repository mutation
        # funnels through _persist_structured (MemoryService-owned counter) or a
        # direct TrainerRepository write (write_generation), so a cache entry is
        # reused only while both counters are unchanged. A 1s wall-clock bucket
        # keeps clock-derived derivations (FSRS due reviews) effectively fresh.
        self._persist_generation = 0
        self._snapshot_cache: dict[str, tuple[int, int, int, MemorySnapshot]] = {}
        # One training event fans out into memory, card, mastery and review
        # writes. A batch defers those individual structured-memory writes so
        # the event lands as one revision instead of a chain of partial ones.
        self._deferred_write_depth: dict[str, int] = {}
        self._deferred_write_dirty: set[str] = set()

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

    def _canonical_workspace_id(self, workspace_id: str) -> str:
        """Resolve a legacy workspace path to its provisioned project context.

        The same project can be addressed by its folder path (the visible
        session) or by its provisioned context id (training/plan writes). Both
        must read and persist one structured-memory row, otherwise review
        queues and mastery written by training are invisible to the chat
        session that started from the folder path.
        """
        resolved = self.repository.resolve_context_id(workspace_id)
        return resolved or workspace_id

    def _structured_for(self, workspace_id: str) -> StructuredMemoryService:
        workspace_id = self._canonical_workspace_id(workspace_id)
        existing = self._structured_by_workspace.get(workspace_id)
        if existing is not None:
            return existing

        if self._default_structured is not None and not self._structured_by_workspace:
            structured = self._default_structured
            self._default_structured = None
            self._structured_baselines[workspace_id] = structured.export_state()
        else:
            entry = self.repository.load_structured_memory_entry(workspace_id)
            payload, revision = entry if entry is not None else (None, 0)
            structured = StructuredMemoryService.from_state(payload)
            self._structured_revisions[workspace_id] = revision
            # The baseline is the raw row, not the normalized export: fields
            # ``from_state`` repairs while loading (for example a stripped
            # verification artifact restored from trusted persistence) must
            # count as this process's changes and survive the next merge.
            self._structured_baselines[workspace_id] = (
                payload if payload is not None else structured.export_state()
            )
        self._structured_by_workspace[workspace_id] = structured
        return structured

    @contextmanager
    def structured_write_batch(self, workspace_id: str):
        """Land every structured-memory mutation in this block as one write.

        Nested ``_persist_structured`` calls only mark the workspace dirty; the
        outermost successful block writes once. An exception discards the
        pending write so a half-finished cross-domain event is not persisted.
        The snapshot generation still advances per mutation, so in-memory
        readers inside the block never see a stale cache.
        """
        key = self._canonical_workspace_id(workspace_id)
        depth = self._deferred_write_depth.get(key, 0)
        self._deferred_write_depth[key] = depth + 1
        try:
            yield
        except BaseException:
            if depth == 0:
                self._deferred_write_depth.pop(key, None)
                self._deferred_write_dirty.discard(key)
            else:
                self._deferred_write_depth[key] = depth
            raise
        else:
            if depth == 0:
                self._deferred_write_depth.pop(key, None)
                if key in self._deferred_write_dirty:
                    self._deferred_write_dirty.remove(key)
                    self._persist_structured(key)
            else:
                self._deferred_write_depth[key] = depth

    def _persist_structured(self, workspace_id: str) -> None:
        workspace_id = self._canonical_workspace_id(workspace_id)
        self._persist_generation += 1
        if self._deferred_write_depth.get(workspace_id, 0) > 0:
            self._deferred_write_dirty.add(workspace_id)
            return
        structured = self._structured_for(workspace_id)
        state = structured.export_state()
        expected_revision = self._structured_revisions.get(workspace_id)
        revision, stored = self.repository.save_structured_memory(
            workspace_id,
            state,
            expected_revision=expected_revision,
            base_payload=self._structured_baselines.get(workspace_id),
        )
        if expected_revision is not None and revision != expected_revision + 1:
            # Another sidecar wrote this workspace since our last write; only
            # the parts of our state that changed were applied over its copy.
            logger.warning(
                "Structured memory for %s advanced from revision %s to %s while "
                "another sidecar was writing; merged our changes into it.",
                workspace_id,
                expected_revision,
                revision,
            )
        self._structured_revisions[workspace_id] = revision
        # The baseline is what *this* process last exported, not what was
        # stored: the cache still lacks the other sidecar's additions, so the
        # next write must keep merging instead of reading those additions as
        # deletions. See TrainerRepository._merge_structured_state.
        self._structured_baselines[workspace_id] = state

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

    def _coach_defaults_workspace_patch(
        self,
        structured: "StructuredMemoryService",
        coach_defaults: CoachDefaults,
    ) -> dict[str, Any]:
        """Merge incoming coach defaults into the stored record.

        Turn/settings payloads may carry a partial CoachDefaults (older clients,
        or lanes that only touch a subset of fields). Storing a bare model_dump
        would silently reset untouched fields — including custom_skills — back
        to defaults, so only explicitly provided fields overwrite the snapshot.
        """
        dumped = coach_defaults.model_dump(exclude_unset=True)
        existing = self._coach_defaults_from_workspace(structured.snapshot().workspace)
        existing_toggles = existing.get("workspace_memory_toggles")
        incoming_toggles = dumped.get("workspace_memory_toggles")
        if isinstance(existing_toggles, dict) and isinstance(incoming_toggles, dict):
            dumped["workspace_memory_toggles"] = {**existing_toggles, **incoming_toggles}
        patch: dict[str, Any] = {"coach_defaults": {**existing, **dumped}}
        for key in (
            "memory_scope",
            "working_set_mode",
            "review_cadence",
            "review_reminder_mode",
            "workspace_memory_toggles",
        ):
            if key in dumped:
                patch[key] = dumped[key]
        return patch

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

    def _record_persisted_card_activity(
        self,
        workspace_id: str,
        card: TrainingCardCandidateSnapshot,
        event_type: str,
        event_key: str,
        result: str = "",
    ) -> None:
        if self._event_ledger is None:
            return
        binding = card.plan_binding
        try:
            self._event_ledger.record_event(
                event_type,
                project_id=self._canonical_workspace_id(workspace_id),
                scope="training",
                actor="system" if event_type == EVENT_EVALUATION_FEEDBACK_RECORDED else "learner",
                idempotency_key=f"{event_type}:{card.card_id}:{event_key}",
                payload_ref={
                    "card_id": card.card_id,
                    "title": card.title,
                    "result": result,
                    "plan_id": binding.plan_id if binding else "",
                    "stage_id": binding.stage_id if binding else "",
                    "resource_id": card.resource_id,
                    "resource_version_id": card.resource_version_id,
                    "resource_content_hash": card.resource_content_hash,
                },
            )
        except Exception:
            logger.exception("Could not record persisted training activity in the event ledger")

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
        snapshot = build_memory_snapshot(self, workspace_id)
        if self._event_ledger is not None:
            snapshot.learning_activity = [
                LearningActivityEntry(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    occurred_at=event.occurred_at,
                    **{key: str(event.payload_ref.get(key) or "") for key in (
                        "title", "card_id", "resource_id", "next_due", "trust_level", "result",
                    )},
                )
                for event in self._event_ledger.recent_learning_activity(workspace_id)
            ]
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
