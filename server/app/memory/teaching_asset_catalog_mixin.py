"""Teaching-asset catalog/ranking domain mixin for :class:`MemoryService`.

Knowledge-catalog grouping, asset ranking/effectiveness/relevance scoring,
recalled-memory lesson/evidence/match-reason extraction, and workspace
material routing. Methods are extracted verbatim from ``memory/service.py``
(pure code motion, zero behavior change); the shared ``MemoryService``
state they touch is declared under ``TYPE_CHECKING`` only and is assigned
in ``MemoryService.__init__`` or defined elsewhere on the class.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable

from ..core.models import MemorySnapshot, TeachingKnowledgeAsset
from ..pedagogy.evidence_controls import analyze_learning_evidence, resolve_pedagogy_controls
from ..pedagogy.material_recommendation import (
    MaterialRoutingDecision,
    resolve_material_routing,
    teaching_asset_scope_bias,
)
from .transfer_skills import normalize_transfer_skill_state_record

if TYPE_CHECKING:
    from .service import StructuredMemoryService


class TeachingAssetCatalogMixin:
    """Hosts the teaching-asset catalog/ranking methods of ``MemoryService``."""

    if TYPE_CHECKING:
        # Shared MemoryService collaborators used by the methods below.
        def _structured_for(self, workspace_id: str) -> StructuredMemoryService: ...
        _context_pressure_from_lane: Callable[..., Any]
        list_teaching_assets: Callable[..., list[TeachingKnowledgeAsset]]

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
