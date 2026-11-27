from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..core.models import (
    CoachingAdaptationProfile,
    CurrentFilePayload,
    MemorySnapshot,
    TeachingKnowledgeAsset,
    TurnRequest,
    UserProfile,
    WorkspaceUnderstandingSnapshot,
)
from .principle_explainer import PrincipleNote
from .project_adaptation_coach import ProjectAdaptationGuide
from .project_idea_miner import ProjectIdea
from .service_types import (
    AdaptiveCoachingBias,
    ImplementationGuide,
    LearnerState,
    PedagogyArtifacts,
    TeachingDecision,
)


class GoalAndAdaptationMixin:
    if TYPE_CHECKING:
        _introduces_new_idea: Any
        _project_source_scout: Any
        _rejects_broad_plan: Any
        _requests_concrete_next_step: Any
        _requests_diagnosis: Any
        _requests_idea_implementation: Any
        _requests_language_coaching: Any
        _requests_project_idea_mining: Any

    def _classify_scenario(
        self,
        *,
        request: TurnRequest,
        memory_snapshot: MemorySnapshot | None,
        profile: UserProfile | None,
    ) -> tuple[str, str, list[str]]:
        message = request.message.lower()
        focus_area = request.focus_area or ""
        evidence: list[str] = []
        rejects_broad_plan = self._rejects_broad_plan(request.message)
        language_coaching = self._requests_language_coaching(request.message)
        idea_implementation_request = self._requests_idea_implementation(request.message)
        project_idea_request = self._requests_project_idea_mining(request.message)

        if self._requests_diagnosis(request.message):
            evidence.append("message_requests_diagnosis")
            return (
                "review_reflection",
                focus_area or self._pick_focus(request, memory_snapshot, profile),
                evidence,
            )

        if any(
            token in message
            for token in ("why", "principle", "mechanism", "tradeoff", "原理", "为什么", "机制", "取舍")
        ):
            evidence.append("message_requests_principle")
            return "principle_explanation", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

        if language_coaching:
            evidence.append("message_requests_language_coaching")
            return "general", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

        if (
            idea_implementation_request
            and rejects_broad_plan
            and not project_idea_request
        ):
            evidence.append("message_requests_idea_implementation")
            return "idea_implementation", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

        if any(
            token in message
            for token in (
                "adapt",
                "migration",
                "turn this project into",
                "reshape this project",
                "refactor this project",
                "change this project to",
                "make this project more like",
                "改造",
                "改成",
                "改造成",
                "迁移",
                "重构这个项目",
                "按我的意图改",
                "按我的心意改造",
                "变成",
            )
        ):
            evidence.append("message_requests_project_adaptation")
            return "project_adaptation", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

        if any(
            token in message
            for token in (
                "find project",
                "find a repo",
                "public project source",
                "source project",
                "reference repo",
                "reference repository",
                "reference project",
                "training repo",
                "training repository",
                "\u516c\u5f00\u9879\u76ee",
                "\u627e\u9879\u76ee",
                "\u627e\u4ee3\u7801\u5e93",
                "\u627e\u53c2\u8003\u5b9e\u73b0",
                "\u9002\u5408\u8bad\u7ec3\u7684\u9879\u76ee",
                "公开项目",
                "找项目",
                "找代码库",
                "找参考实现",
                "适合训练的项目",
            )
        ):
            evidence.append("message_requests_project_sourcing")
            return "project_sourcing", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

        if request.intent == "plan" or any(
            token in message
            for token in ("plan", "roadmap", "milestone", "cadence", "sequence", "计划", "路线图", "里程碑", "节奏")
        ):
            evidence.append("message_requests_planning")
            return "planning", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

        if any(
            token in message
            for token in (
                "concept",
                "teach me",
                "understand",
                "what is",
                "概念",
                "讲讲",
                "理解",
                "是什么意思",
            )
        ):
            evidence.append("message_requests_concept_teaching")
            return "concept_teaching", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

        if request.intent == "task" or any(
            token in message
            for token in (
                "challenge",
                "exercise",
                "drill",
                "give me a problem",
                "题目",
                "挑战",
                "练习",
                "出题",
            )
        ):
            evidence.append("message_requests_engineering_challenge")
            return "engineering_challenge", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

        if project_idea_request:
            evidence.append("message_requests_project_ideas")
            return "project_idea_mining", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

        if self._requests_concrete_next_step(request.message, request.current_file):
            evidence.append("message_requests_concrete_next_step")
            return "idea_implementation", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

        if idea_implementation_request and not project_idea_request:
            evidence.append("message_requests_idea_implementation")
            return "idea_implementation", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

        if any(
            token in message
            for token in (
                "implement",
                "build",
                "ship",
                "make this",
                "i want to build",
                "i want to make",
                "i have an idea",
                "prototype",
                "实现",
                "想实现",
                "做一个",
                "想做",
                "想让",
                "带我做",
                "怎么开始",
                "我想把",
            )
        ):
            evidence.append("message_requests_implementation")
            explicit_new_idea = any(
                token in message
                for token in ("i have an idea", "i want to build", "想做", "想实现", "我想把")
            )
            resolved_focus = focus_area if explicit_new_idea and not focus_area else (
                focus_area or self._pick_focus(request, memory_snapshot, profile)
            )
            return "idea_implementation", resolved_focus, evidence

        if request.intent == "review":
            evidence.append("request_intent_review")
            return "review_reflection", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

        return "guided", focus_area or self._pick_focus(request, memory_snapshot, profile), evidence

    def _pick_focus(
        self,
        request: TurnRequest,
        memory_snapshot: MemorySnapshot | None,
        profile: UserProfile | None,
    ) -> str:
        if not request.focus_area and self._introduces_new_idea(request.message):
            return ""
        for candidate in (
            request.focus_area,
            memory_snapshot.current_focus if memory_snapshot else "",
            memory_snapshot.coach_anchor if memory_snapshot else "",
            memory_snapshot.top_weakness if memory_snapshot else "",
            profile.long_term_goal if profile is not None else "",
        ):
            if candidate:
                return candidate
        return "current task"

    def _estimate_attempt_count(
        self,
        current_file: CurrentFilePayload | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> int:
        count = 0
        if current_file is not None:
            count += min(len(current_file.diagnostics), 3)
            if current_file.selection_text:
                count += 1
        if memory_snapshot and memory_snapshot.reflections and (
            memory_snapshot.active_thread
            or memory_snapshot.learning_outcomes
            or memory_snapshot.top_weakness
            or memory_snapshot.due_reviews
        ):
            count += min(len(memory_snapshot.reflections), 2)
        return count

    def _build_primary_goal(self, scenario: str, focus_area: str, active_focus: str) -> str:
        target = focus_area or active_focus
        goals = {
            "onboarding": f"Understand the learner around '{target}' well enough to choose the right coaching lane.",
            "idea_implementation": f"Turn '{target}' into the next safe implementation step.",
            "planning": f"Turn '{target}' into one visible learning sequence with a stable next move.",
            "concept_teaching": f"Explain '{target}' through one concrete code anchor and one failure mode.",
            "engineering_challenge": f"Turn '{target}' into one project-backed engineering exercise.",
            "project_idea_mining": f"Find a real, coach-worthy project idea around '{target}'.",
            "project_adaptation": f"Map a gradual adaptation path for '{target}'.",
            "project_sourcing": f"Find an outside project source that is actually worth training '{target}' on.",
            "principle_explanation": f"Explain the principle behind '{target}' in code-shaped terms.",
            "review_reflection": f"Reinforce the review loop around '{target}'.",
            "guided": f"Keep progress moving on '{target}' without widening scope.",
        }
        return goals.get(scenario, goals["guided"])

    def _build_exercise_prompt(
        self,
        *,
        request: TurnRequest,
        learner_state: LearnerState,
        decision: TeachingDecision,
        implementation_guide: ImplementationGuide | None,
        project_ideas: list[ProjectIdea],
        adaptation_guide: ProjectAdaptationGuide | None,
        principle_note: PrincipleNote | None,
        memory_snapshot: MemorySnapshot | None,
        selected_assets: list[TeachingKnowledgeAsset] | None = None,
    ) -> dict[str, Any]:
        current_file = request.current_file
        focus_area = decision.focus_area or learner_state.active_focus
        scenario = decision.mode if decision.mode == "review_reflection" else decision.scenario
        adaptive_bias = self._adaptive_bias(memory_snapshot)
        exercise_type = "implementation"
        title = "Thin implementation slice"
        prompt = "Complete one tiny, verifiable implementation slice before widening the work."
        success_signal = "One focused check proves the changed behavior."
        fallback = "Shrink the task to one branch or one function and restate the expected behavior."
        constraints = [
            "Keep the scope inside one behavior change.",
            "Verify before adding a second change.",
        ]
        teaching_catalog = (
            memory_snapshot.teaching_knowledge_catalog if memory_snapshot and memory_snapshot.teaching_knowledge_catalog else {}
        )
        catalog_focus_hint = self._catalog_focus_hint(teaching_catalog, scenario=scenario, focus_area=focus_area)
        if catalog_focus_hint:
            constraints.append(catalog_focus_hint)

        if scenario == "review_reflection":
            exercise_type = "review"
            title = "Close one review loop"
            due_review = memory_snapshot.due_reviews[0] if memory_snapshot and memory_snapshot.due_reviews else None
            active_thread = memory_snapshot.active_thread if memory_snapshot else None
            prompt = (
                due_review.task_hint
                if due_review is not None and due_review.task_hint
                else active_thread.next_step
                if active_thread is not None and active_thread.next_step
                else "Fix the first high-leverage issue, rerun the narrowest check, then report the result."
            )
            success_signal = (
                due_review.reason
                if due_review is not None and due_review.reason
                else "The first failing or warning path is resolved or better understood."
            )
            fallback = "Ignore secondary issues and only name the first fix plus one verification."
            constraints = [
                "Stay on the live project thread.",
                "Do not mix multiple fixes into one recovery loop.",
            ]
        elif scenario == "principle_explanation":
            exercise_type = "principle"
            title = "Explain the rule through the code"
            prompt = (
                principle_note.follow_up_exercise
                if principle_note is not None and principle_note.follow_up_exercise
                else "Point at one code boundary and explain what fails if this rule is ignored."
            )
            success_signal = "The learner can name the rule, the code boundary, and the failure mode."
            fallback = "Reduce the explanation to one branch, one boundary, and one breakage."
            constraints = [
                "Do not drift into general theory.",
                "Keep the explanation attached to one concrete code location.",
            ]
            if catalog_focus_hint:
                constraints.append(catalog_focus_hint)
        elif scenario == "concept_teaching":
            exercise_type = "principle"
            title = "Teach the concept through the code"
            prompt = (
                principle_note.follow_up_exercise
                if principle_note is not None and principle_note.follow_up_exercise
                else "Teach the concept back through one branch, one code boundary, and one failure mode."
            )
            success_signal = (
                "The learner can restate the concept in plain words, point at the code boundary, and name where it transfers next."
            )
            fallback = "Reduce the concept to one branch, one boundary, one bug it prevents, and one plain-language sentence."
            constraints = [
                "Start with plain language before returning to code.",
                "Keep the concept attached to one concrete code location.",
                "Name one nearby boundary where the same rule transfers next.",
            ]
            if catalog_focus_hint:
                constraints.append(catalog_focus_hint)
        elif scenario == "engineering_challenge":
            exercise_type = "implementation"
            title = "Project-backed engineering challenge"
            weak_spot = memory_snapshot.top_weakness if memory_snapshot and memory_snapshot.top_weakness else ""
            guide_step = (
                implementation_guide.current_step
                if implementation_guide is not None and implementation_guide.current_step
                else ""
            )
            if weak_spot:
                prompt = (
                    f"Use the live project to design and land one narrow patch that specifically exercises the weak spot around {weak_spot}. "
                    f"{guide_step or 'Keep the change inside one verifiable boundary.'}"
                )
                success_signal = (
                    implementation_guide.success_signal
                    if implementation_guide is not None and implementation_guide.success_signal
                    else f"One small project-backed slice is landed, verified, and clearly addresses the weak spot around {weak_spot}."
                )
                fallback = (
                    implementation_guide.fallback_step
                    if implementation_guide is not None and implementation_guide.fallback_step
                    else f"Shrink the challenge until {weak_spot} appears in only one function, one branch, or one explicit check."
                )
            else:
                prompt = (
                    guide_step
                    if guide_step
                    else "Choose one thin project-backed challenge and land the smallest verifiable patch."
                )
                success_signal = (
                    implementation_guide.success_signal
                    if implementation_guide is not None and implementation_guide.success_signal
                    else "One small implementation slice is landed and verified."
                )
                fallback = (
                    implementation_guide.fallback_step
                    if implementation_guide is not None and implementation_guide.fallback_step
                    else "Shrink the challenge to one function, one behavior, and one focused check."
                )
            constraints = [
                "Use the existing project instead of a toy example.",
                "Keep the first pass small enough for one review loop.",
            ]
            if weak_spot:
                constraints.insert(0, f"Make the challenge visibly exercise the weak spot around {weak_spot}.")
            if catalog_focus_hint:
                constraints.append(catalog_focus_hint)
        elif scenario == "project_adaptation":
            exercise_type = "adaptation"
            title = "First migration slice"
            prompt = (
                adaptation_guide.first_migration_step
                if adaptation_guide is not None and adaptation_guide.first_migration_step
                else "Name the first boundary to move, then adapt only that slice."
            )
            success_signal = (
                adaptation_guide.validation_checkpoints[0]
                if adaptation_guide is not None and adaptation_guide.validation_checkpoints
                else "One migration boundary is verified before the next one moves."
            )
            fallback = (
                adaptation_guide.rollback_notes[0]
                if adaptation_guide is not None and adaptation_guide.rollback_notes
                else "Shrink the migration so the first step can be reverted independently."
            )
            constraints = [
                adaptation_guide.preserve_areas[0]
                if adaptation_guide is not None and adaptation_guide.preserve_areas
                else "Keep unrelated flows stable during the first migration.",
                "Do not migrate two boundaries at once.",
            ]
            if catalog_focus_hint:
                constraints.append(catalog_focus_hint)
        elif scenario == "project_sourcing":
            exercise_type = "external_project"
            title = "Turn the source into the first training task"
            top_source = self._project_source_scout.suggest_sources(
                request=request,
                focus_area=focus_area,
                profile=None,
                memory_snapshot=memory_snapshot,
                external_references=[
                    {
                        "source": resource.canonical_source or resource.source,
                        "snippet": str((resource.knowledge_fragments[0] or {}).get("snippet", "")).strip(),
                        "trust_score": resource.trust_score,
                        "fetched_at": resource.fetched_at,
                        "focus_area": resource.name.strip() or resource.kind,
                        "quality_flags": list(resource.quality_flags),
                        "source_governance": resource.source_governance.model_dump(mode="json"),
                        "commercial_reuse_status": resource.source_governance.commercial_reuse_status,
                        "commercial_reuse_reason_codes": list(
                            resource.source_governance.commercial_reuse_reason_codes
                        ),
                    }
                    for resource in (memory_snapshot.resources[:3] if memory_snapshot is not None else [])
                    if resource.knowledge_fragments and isinstance(resource.knowledge_fragments[0], dict)
                ],
            )[:1]
            source_pick = top_source[0] if top_source else None
            prompt = (
                source_pick.first_task
                if source_pick is not None and source_pick.first_task
                else "Pick one outside source, reject setup-heavy options, and compress it into one first training slice."
            )
            success_signal = (
                f"The source is selected and the first training slice is clearly named around {focus_area}."
                if focus_area
                else "The source is selected and the first training slice is clearly named."
            )
            fallback = (
                "If the source still feels too large, reduce it to one module, one behavior, and one verification path before coding."
            )
            constraints = [
                "Reject sources whose setup cost is larger than the first training loop.",
                "Extract only one first task from the source before exploring more of the repo.",
            ]
            if source_pick is not None and source_pick.first_filter:
                constraints.insert(0, source_pick.first_filter)
            if catalog_focus_hint:
                constraints.append(catalog_focus_hint)
        elif scenario == "review_reflection":
            exercise_type = "review"
            title = "Close one review loop"
            prompt = "Fix the first high-leverage issue, rerun the narrowest check, then report the result."
            success_signal = "The first failing or warning path is resolved or better understood."
            fallback = "Ignore secondary issues and only describe the first fix plus one verification."
            constraints = [
                "Stay with the first issue only.",
                "Do not mix multiple fixes into one loop.",
            ]
            if catalog_focus_hint:
                constraints.append(catalog_focus_hint)
        elif project_ideas:
            top_idea = project_ideas[0]
            exercise_type = top_idea.idea_kind
            title = top_idea.title
            prompt = top_idea.first_step or prompt
            success_signal = top_idea.acceptance_signals[0] if top_idea.acceptance_signals else success_signal
            fallback = f"Reduce '{top_idea.title}' to one function, one behavior, and one check."
            constraints = [
                top_idea.suggested_scope or "Keep the task small enough for one short loop.",
                "Do not widen into a redesign.",
            ]
            if catalog_focus_hint:
                constraints.append(catalog_focus_hint)
        elif implementation_guide is not None:
            prompt = implementation_guide.current_step or prompt
            success_signal = implementation_guide.success_signal or success_signal
            fallback = implementation_guide.fallback_step or fallback
            constraints = [
                implementation_guide.scope_boundary or constraints[0],
                implementation_guide.mvp_definition or constraints[1],
            ]
            if catalog_focus_hint:
                constraints.append(catalog_focus_hint)

        if current_file is not None and current_file.path:
            constraints.append(f"Start in {current_file.path}.")
        if memory_snapshot and memory_snapshot.top_weakness:
            constraints.append(f"Watch for the repeated weak spot: {memory_snapshot.top_weakness}.")
        if learner_state.needs_rescue:
            constraints.append("If the patch still feels large, shrink it before writing more code.")
        if adaptive_bias.hint_depth == "direct":
            constraints.append("Do not branch into alternatives until the first explicit step is verified.")
        elif adaptive_bias.hint_depth == "lighter":
            constraints.append("Own the first implementation choice before asking for another hint.")
        if adaptive_bias.explanation_mode == "rebuild":
            constraints.append("Restate the broken mechanism in one sentence before changing more code.")
        elif adaptive_bias.explanation_mode == "transfer":
            constraints.append("Name one nearby boundary where this same rule should transfer next.")
        resolved_selected_assets = [
            asset
            for asset in (selected_assets or [])
            if isinstance(asset, TeachingKnowledgeAsset)
        ]
        if resolved_selected_assets:
            asset_hint = self._asset_exercise_constraint(resolved_selected_assets[0], scenario)
            if catalog_focus_hint:
                asset_hint = f"{asset_hint} {catalog_focus_hint}"
            constraints = [asset_hint, *constraints]
        if adaptive_bias.next_step_bias == "shrink":
            constraints = [
                "Keep this inside one visibly recoverable step.",
                "Do not widen into a second branch before the first check passes.",
                *constraints,
            ]
            fallback = "Reduce it to one branch, one function, or one failing check and confirm only that recovery."
        elif adaptive_bias.next_step_bias == "widen":
            constraints = [
                "Use the last verified understanding, but still keep verification explicit.",
                *constraints,
            ]
            success_signal = f"{success_signal} Then name the next nearby boundary where the same idea transfers."

        return {
            "type": exercise_type,
            "title": title,
            "prompt": prompt,
            "focus_area": focus_area,
            "success_signal": success_signal,
            "fallback_step": fallback,
            "constraints": constraints[:4],
            "scenario": scenario,
            "lesson_shape": decision.lesson_shape,
            "exercise_shape": decision.exercise_shape,
            "teaching_strategy": decision.teaching_strategy,
            "closing_move": decision.closing_move,
            "artifact_priority": list(decision.artifact_priority),
            "selected_teaching_asset_ids": [item.id for item in resolved_selected_assets],
            "selected_teaching_asset_titles": [item.title for item in resolved_selected_assets if item.title],
        }

    def _catalog_focus_hint(
        self,
        teaching_catalog: dict[str, Any] | None,
        *,
        scenario: str,
        focus_area: str,
    ) -> str:
        if not isinstance(teaching_catalog, dict) or not teaching_catalog:
            return ""
        top_assets = teaching_catalog.get("top_assets")
        if not isinstance(top_assets, list) or not top_assets:
            return ""
        first = top_assets[0]
        if not isinstance(first, dict):
            return ""
        title = str(first.get("title", "") or "").strip()
        kind = str(first.get("kind", "") or "").strip()
        origin = str(first.get("origin", "") or "").strip()
        if not title:
            return ""
        focus_note = focus_area or str(first.get("focus_area", "") or "").strip()
        if scenario in {"concept_teaching", "principle_explanation"}:
            return f"Teach from the knowledge base asset '{title}' before widening beyond {focus_note or 'the current focus'}."
        if origin == "learning_outcome":
            return f"Anchor the next move in the learned pattern '{title}' and keep verification visible."
        if kind == "common_pitfall":
            return f"Avoid the known pitfall '{title}' while staying inside {focus_note or 'the current focus'}."
        return f"Reuse the teaching asset '{title}' before inventing a broader path."

    def _relevant_teaching_assets(
        self,
        memory_snapshot: MemorySnapshot | None,
        *,
        scenario: str,
        focus_area: str,
        limit: int,
    ) -> list[TeachingKnowledgeAsset]:
        if memory_snapshot is None or not memory_snapshot.teaching_assets:
            return []
        normalized_scenario = {
            "review": "review_reflection",
            "principle": "principle_explanation",
            "project_idea": "project_idea_mining",
        }.get((scenario or "").strip().lower(), (scenario or "").strip().lower())
        focus_tokens = self._asset_tokens(" ".join([focus_area, normalized_scenario]))
        allowed_kinds: dict[str, set[str]] = {
            "onboarding": {"concept_card", "explanation_recipe", "implementation_pattern"},
            "idea_implementation": {"implementation_pattern", "exercise_seed", "common_pitfall"},
            "project_adaptation": {"implementation_pattern", "common_pitfall", "exercise_seed"},
            "engineering_challenge": {"exercise_seed", "implementation_pattern", "common_pitfall"},
            "concept_teaching": {"explanation_recipe", "concept_card", "common_pitfall"},
            "principle_explanation": {"explanation_recipe", "concept_card", "common_pitfall"},
            "review_reflection": {"common_pitfall", "implementation_pattern", "exercise_seed"},
            "planning": {"exercise_seed", "implementation_pattern"},
            "project_idea_mining": {"exercise_seed", "implementation_pattern", "common_pitfall"},
            "project_sourcing": {"exercise_seed", "implementation_pattern", "concept_card", "explanation_recipe"},
        }
        ranked = sorted(
            memory_snapshot.teaching_assets,
            key=lambda item: self._asset_rank(item, normalized_scenario, focus_area, focus_tokens),
            reverse=True,
        )
        filtered: list[TeachingKnowledgeAsset] = []
        for asset in ranked:
            if normalized_scenario in allowed_kinds and asset.kind not in allowed_kinds[normalized_scenario]:
                continue
            asset_scenario = asset.scenario.strip().lower()
            asset_focus = asset.focus_area.strip().lower()
            overlap = len(
                self._asset_tokens(
                    " ".join(
                        [
                            asset.title,
                            asset.summary,
                            asset.focus_area,
                            " ".join(asset.tags),
                        ]
                    )
                )
                & focus_tokens
            )
            scenario_match = (
                not asset_scenario
                or asset_scenario == normalized_scenario
                or normalized_scenario in asset_scenario
            )
            focus_match = bool(
                focus_area
                and (
                    focus_area.lower() in asset_focus
                    or asset_focus in focus_area.lower()
                )
            )
            if not scenario_match and not focus_match and overlap == 0:
                continue
            filtered.append(asset)
            if len(filtered) >= limit:
                break
        return filtered

    def _needs_onboarding_turn(
        self,
        *,
        request: TurnRequest,
        learner_state: LearnerState,
        memory_snapshot: MemorySnapshot | None,
        profile: UserProfile | None,
        scenario: str,
    ) -> bool:
        extracted = self._extract_onboarding_signals(request.message)
        synthetic_due_review = self._has_only_synthetic_due_reviews(memory_snapshot)
        synthetic_focus = self._looks_like_synthetic_focus(memory_snapshot)
        synthetic_active_thread = self._looks_like_synthetic_active_thread(memory_snapshot)
        if scenario in {"project_sourcing", "project_idea_mining"}:
            return False
        if memory_snapshot is not None:
            if memory_snapshot.active_thread and (
                memory_snapshot.active_thread.focus_area
                or memory_snapshot.active_thread.next_step
                or memory_snapshot.active_thread.summary
            ) and not synthetic_active_thread:
                return False
            if memory_snapshot.learning_outcomes:
                return False
            if (memory_snapshot.current_focus or memory_snapshot.coach_anchor) and not synthetic_focus:
                return False
        profile_ready = bool(
            profile
            and (
                (
                    profile.long_term_goal
                    and profile.long_term_goal.strip().lower() != "build stronger implementation habits"
                )
                or profile.background
                or profile.weekly_hours != 4
                or profile.target_project
            )
        )
        if profile_ready:
            return False
        if self._requests_concrete_next_step(request.message, request.current_file):
            return False
        if (
            memory_snapshot is not None
            and memory_snapshot.due_reviews
            and not synthetic_due_review
            and not extracted
        ):
            return False
        if request.current_file is not None and scenario == "idea_implementation" and extracted:
            return True
        if learner_state.needs_rescue and extracted:
            return True
        message = request.message.strip()
        if not message:
            return True
        if extracted:
            return True
        if self._looks_like_relationship_first_opening(
            message=message,
            memory_snapshot=memory_snapshot,
            profile=profile,
            has_current_file=request.current_file is not None,
        ):
            return True
        return False

    def _looks_like_relationship_first_opening(
        self,
        *,
        message: str,
        memory_snapshot: MemorySnapshot | None,
        profile: UserProfile | None,
        has_current_file: bool,
    ) -> bool:
        if has_current_file:
            return False
        synthetic_bootstrap = bool(
            memory_snapshot is not None
            and self._has_only_synthetic_due_reviews(memory_snapshot)
            and self._looks_like_synthetic_focus(memory_snapshot)
        )
        if memory_snapshot is not None and (
            (memory_snapshot.active_thread and not self._looks_like_synthetic_active_thread(memory_snapshot))
            or memory_snapshot.learning_outcomes
        ):
            return False
        if memory_snapshot is not None and not synthetic_bootstrap and (
            memory_snapshot.recent_wins
            or memory_snapshot.teaching_observations
        ):
            return False
        if memory_snapshot is not None and not synthetic_bootstrap and (
            (memory_snapshot.current_focus or memory_snapshot.coach_anchor)
            and not self._looks_like_synthetic_focus(memory_snapshot)
        ):
            return False
        profile_ready = bool(
            profile
            and (
                (
                    profile.long_term_goal
                    and profile.long_term_goal.strip().lower() != "build stronger implementation habits"
                )
                or profile.background
                or profile.target_project
            )
        )
        if profile_ready:
            return False
        lowered = message.lower()
        relationship_openers = (
            "how do we start",
            "where should we start",
            "help me get started",
            "before we start",
            "want to practice with you",
            "coach me through",
            "先聊聊",
            "先对齐",
            "怎么开始",
            "先帮我看看怎么开始",
            "一步一步带我",
            "先陪我看看",
            "先一起定一下",
        )
        return any(token in lowered for token in relationship_openers)

    def _onboarding_focus(
        self,
        request: TurnRequest,
        learner_state: LearnerState,
        profile: UserProfile | None,
        memory_snapshot: MemorySnapshot | None,
    ) -> str:
        extracted = self._extract_onboarding_signals(request.message)
        for candidate in (
            extracted.get("project_or_lane"),
            extracted.get("goal"),
            request.focus_area,
            learner_state.active_focus,
            memory_snapshot.current_focus if memory_snapshot else "",
            profile.long_term_goal if profile is not None else "",
        ):
            cleaned = str(candidate or "").strip()
            if cleaned:
                return cleaned
        return "first coaching lane"

    def _extract_onboarding_signals(self, message: str) -> dict[str, str]:
        signals: dict[str, str] = {}
        goal_match = re.search(r"(?:长期目标(?:是)?|目标是|我想要|我希望|我想)([^。！？\n]{4,80})", message, flags=re.IGNORECASE)
        if goal_match:
            signals["goal"] = goal_match.group(1).strip(" ：:，,。.!")
        background_match = re.search(r"(?:我现在是|我目前是|我是)([^。！？，,\n]{2,50})", message, flags=re.IGNORECASE)
        if background_match:
            signals["background"] = background_match.group(1).strip(" ：:，,。.!")
        blocker_match = re.search(r"(?:卡在|卡住了|问题是|报错是|不会的地方是)([^。！？\n]{3,80})", message, flags=re.IGNORECASE)
        if blocker_match:
            signals["blocker"] = blocker_match.group(1).strip(" ：:，,。.!")
        lane_match = re.search(r"(?:手上的项目|当前项目|这个项目|工程背景|项目背景)([^。！？\n]{3,60})", message, flags=re.IGNORECASE)
        if lane_match:
            signals["project_or_lane"] = lane_match.group(1).strip(" ：:，,。.!")
        return signals

    def _has_only_synthetic_due_reviews(self, memory_snapshot: MemorySnapshot | None) -> bool:
        if memory_snapshot is None or not memory_snapshot.due_reviews:
            return False
        synthetic = {"new-workspace", "plan-discipline", "resource-grounding"}
        concepts = {str(item.concept or "").strip().lower() for item in memory_snapshot.due_reviews}
        return bool(concepts) and concepts.issubset(synthetic)

    def _looks_like_synthetic_focus(self, memory_snapshot: MemorySnapshot | None) -> bool:
        if memory_snapshot is None:
            return False
        current_focus = str(memory_snapshot.current_focus or "").strip().lower()
        coach_anchor = str(memory_snapshot.coach_anchor or "").strip().lower()
        synthetic_focus_markers = (
            "current coaching focus:",
            "当前聚焦：先沿着「implementation」",
            "当前聚焦：先把事情压成一个可验证的小动作",
            "当前聚焦：继续围绕「implementation」",
        )
        return (
            any(current_focus.startswith(marker) for marker in synthetic_focus_markers)
            or coach_anchor == "implementation"
        )

    def _looks_like_synthetic_active_thread(self, memory_snapshot: MemorySnapshot | None) -> bool:
        active_thread = memory_snapshot.active_thread if memory_snapshot is not None else None
        if active_thread is None:
            return False
        focus_area = str(active_thread.focus_area or "").strip().lower()
        summary = str(active_thread.summary or "").strip().lower()
        next_step = str(active_thread.next_step or "").strip().lower()
        blocker = str(active_thread.blocker or "").strip().lower()
        verified = str(active_thread.verified_result or "").strip().lower()
        synthetic_review_tokens = {"new-workspace", "plan-discipline", "resource-grounding"}
        return (
            focus_area == "implementation"
            and not verified
            and (
                "当前聚焦点：先把这个想法收成一个很小、可验证的 patch" in summary
                or "one thin implementation slice" in summary
                or any(token in next_step for token in synthetic_review_tokens)
                or "后续复习点" in blocker
                or "review point" in blocker
            )
        )

    def _fallback_project_sourcing_assets(
        self,
        memory_snapshot: MemorySnapshot | None,
        *,
        limit: int,
    ) -> list[TeachingKnowledgeAsset]:
        if memory_snapshot is None or not memory_snapshot.teaching_assets:
            return []
        preferred_origins = {"resource": 3.0, "workspace_understanding": 2.0, "learning_outcome": 1.5, "manual": 1.0, "reflection": 0.8}
        candidates = [
            asset
            for asset in memory_snapshot.teaching_assets
            if asset.kind in {"exercise_seed", "implementation_pattern", "concept_card", "explanation_recipe"}
            and (asset.summary or asset.source_summary or asset.title).strip()
        ]
        ranked = sorted(
            candidates,
            key=lambda asset: (
                preferred_origins.get(asset.origin, 0.0),
                float(asset.trust_score or 0.0),
                1.0 if asset.scope == "project" else 0.0,
                asset.updated_at or "",
            ),
            reverse=True,
        )
        return ranked[:limit]

    def _asset_rank(
        self,
        asset: TeachingKnowledgeAsset,
        scenario: str,
        focus_area: str,
        focus_tokens: set[str],
    ) -> tuple[float, float, float, float, str]:
        kind_weights: dict[str, dict[str, float]] = {
            "idea_implementation": {"implementation_pattern": 6.0, "exercise_seed": 4.0, "common_pitfall": 4.0},
            "project_adaptation": {"implementation_pattern": 5.0, "common_pitfall": 5.0, "exercise_seed": 3.0},
            "engineering_challenge": {"exercise_seed": 6.0, "implementation_pattern": 5.0},
            "concept_teaching": {"explanation_recipe": 6.0, "concept_card": 5.0, "common_pitfall": 3.0},
            "principle_explanation": {"explanation_recipe": 6.0, "concept_card": 5.0, "common_pitfall": 3.0},
            "review_reflection": {"common_pitfall": 6.0, "implementation_pattern": 5.0, "exercise_seed": 3.0},
            "planning": {"exercise_seed": 4.0, "implementation_pattern": 3.0},
            "project_idea_mining": {"exercise_seed": 6.0, "implementation_pattern": 3.0},
            "project_sourcing": {"exercise_seed": 5.0, "implementation_pattern": 2.0},
        }
        scenario_score = kind_weights.get(scenario, {}).get(asset.kind, 1.0)
        asset_scenario = asset.scenario.strip().lower()
        if asset_scenario == scenario:
            scenario_score += 4.0
        elif asset_scenario and scenario and scenario in asset_scenario:
            scenario_score += 2.0

        overlap_score = 0.0
        if focus_area and focus_area.lower() in asset.focus_area.lower():
            overlap_score += 6.0
        asset_tokens = self._asset_tokens(
            " ".join(
                [
                    asset.title,
                    asset.summary,
                    asset.focus_area,
                    asset.scenario,
                    " ".join(asset.tags),
                ]
            )
        )
        overlap_score += float(len(asset_tokens & focus_tokens)) * 3.0 if focus_tokens else 0.0

        scope_score = 3.0 if asset.scope == "project" else 2.0 if asset.scope == "personal" else 1.0
        trust_and_usage = float(asset.trust_score or 0.0) + min(float(asset.usage_count or 0), 6.0) * 0.15
        return overlap_score, scenario_score, scope_score, trust_and_usage, asset.updated_at or ""

    def _asset_tokens(self, value: str) -> set[str]:
        cleaned = value.replace("/", " ").replace("-", " ").replace("_", " ")
        return {
            token
            for token in re.findall(r"[\w\u4e00-\u9fff]+", cleaned.lower())
            if len(token) > 1
        }

    def _asset_strategy_hint(self, asset: TeachingKnowledgeAsset, scenario: str) -> str:
        summary = asset.summary or asset.title
        if asset.kind == "implementation_pattern":
            return f"Reuse the verified pattern '{summary}' instead of inventing a wider path."
        if asset.kind == "common_pitfall":
            return f"Keep the learner away from the known pitfall '{summary}'."
        if asset.kind == "exercise_seed":
            return f"Use the saved exercise seed '{summary}' to keep the work concrete."
        if asset.kind == "explanation_recipe":
            return f"Teach through the saved explanation recipe '{summary}'."
        return f"Ground the next move in the saved teaching asset '{summary}'."

    def _asset_closing_hint(self, asset: TeachingKnowledgeAsset) -> str:
        focus = asset.focus_area or asset.title
        return f"Keep the learner attached to '{focus}' for one more verifiable loop."

    def _asset_exercise_constraint(self, asset: TeachingKnowledgeAsset, scenario: str) -> str:
        title = asset.title or asset.summary or "teaching asset"
        summary = asset.summary or asset.title
        if asset.kind == "implementation_pattern":
            return f"Reuse the teaching asset '{title}': {summary}."
        if asset.kind == "common_pitfall":
            return f"Avoid the teaching asset '{title}': {summary}."
        if asset.kind == "exercise_seed":
            return f"Stay aligned with the teaching asset '{title}': {summary}."
        if asset.kind == "explanation_recipe":
            return f"Use the teaching asset '{title}' as the explanation anchor: {summary}."
        if scenario in {"concept_teaching", "principle_explanation"}:
            return f"Keep the explanation anchored to the teaching asset '{title}': {summary}."
        return f"Use the teaching asset '{title}': {summary}."

    def _apply_workspace_understanding(
        self,
        *,
        artifacts: PedagogyArtifacts,
        request: TurnRequest,
        understanding: WorkspaceUnderstandingSnapshot,
    ) -> None:
        if artifacts.implementation_guide is not None:
            artifacts.implementation_guide.codebase_entry_points = self._merge_unique_text(
                artifacts.implementation_guide.codebase_entry_points,
                understanding.entry_points,
                limit=4,
            )
            artifacts.implementation_guide.risk_notes = self._merge_unique_text(
                artifacts.implementation_guide.risk_notes,
                understanding.risk_zones,
                limit=4,
            )
            artifacts.implementation_guide.next_steps = self._merge_unique_text(
                artifacts.implementation_guide.next_steps,
                understanding.feature_lanes[:1],
                limit=5,
            )

        if artifacts.adaptation_guide is not None:
            artifacts.adaptation_guide.affected_areas = self._merge_unique_text(
                artifacts.adaptation_guide.affected_areas,
                understanding.entry_points,
                limit=4,
            )
            artifacts.adaptation_guide.current_constraints = self._merge_unique_text(
                artifacts.adaptation_guide.current_constraints,
                understanding.risk_zones[:2],
                limit=4,
            )
            artifacts.adaptation_guide.validation_checkpoints = self._merge_unique_text(
                artifacts.adaptation_guide.validation_checkpoints,
                understanding.training_opportunities[:1],
                limit=4,
            )
            if request.current_file is None and understanding.entry_points:
                artifacts.adaptation_guide.first_migration_step = (
                    f"Start in {understanding.entry_points[0]} and move the first boundary before widening scope."
                )

        if artifacts.project_ideas:
            for index, idea in enumerate(artifacts.project_ideas):
                if understanding.entry_points and (
                    not idea.source_area
                    or idea.source_area == "workspace"
                    or idea.source_area == "current workflow"
                ):
                    idea.source_area = understanding.entry_points[min(index, len(understanding.entry_points) - 1)]

    def _merge_unique_text(
        self,
        current: list[str],
        extra: list[str],
        *,
        limit: int,
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for value in [*current, *extra]:
            cleaned = str(value or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            merged.append(cleaned)
            if len(merged) >= limit:
                break
        return merged

    def _review_recovery_focus(
        self,
        memory_snapshot: MemorySnapshot | None,
        focus_area: str,
        active_focus: str,
    ) -> str:
        if memory_snapshot is None:
            return focus_area or active_focus
        active_thread_focus = (
            memory_snapshot.active_thread.focus_area.strip()
            if memory_snapshot.active_thread is not None and memory_snapshot.active_thread.focus_area
            else ""
        )
        for candidate in (
            memory_snapshot.due_reviews[0].focus_area if memory_snapshot.due_reviews else "",
            active_thread_focus,
            focus_area,
            active_focus,
            memory_snapshot.top_weakness,
            memory_snapshot.due_reviews[0].concept if memory_snapshot.due_reviews else "",
        ):
            cleaned = candidate.strip() if isinstance(candidate, str) else ""
            if cleaned:
                return cleaned
        return focus_area or active_focus

    @staticmethod
    def _latest_learning_outcome(memory_snapshot: MemorySnapshot | None) -> dict[str, Any] | None:
        if memory_snapshot is None:
            return None
        outcomes = getattr(memory_snapshot, "learning_outcomes", None)
        if not isinstance(outcomes, list) or not outcomes:
            return None
        latest = outcomes[0]
        return latest if isinstance(latest, dict) else None

    @staticmethod
    def _adaptive_bias(memory_snapshot: MemorySnapshot | None) -> AdaptiveCoachingBias:
        if memory_snapshot is None:
            return AdaptiveCoachingBias()
        profile = getattr(memory_snapshot, "coaching_adaptation", None)
        if profile is None:
            return AdaptiveCoachingBias()
        if isinstance(profile, CoachingAdaptationProfile):
            return AdaptiveCoachingBias(
                challenge_level=profile.challenge_level,
                hint_depth=profile.hint_depth,
                review_urgency=profile.review_urgency,
                explanation_mode=profile.explanation_mode,
                next_step_bias=profile.next_step_bias,
                summary=profile.summary,
                evidence=list(profile.evidence),
                difficulty=profile.difficulty,
                hint_count=profile.hint_count,
                explanation_depth=profile.explanation_depth,
                code_reveal=profile.code_reveal,
                practice_type=profile.practice_type,
                review_frequency=profile.review_frequency,
                material_recommendation=profile.material_recommendation,
                should_reveal_code=profile.should_reveal_code,
                pedagogy_mode=profile.pedagogy_mode,
            )
        if isinstance(profile, dict):
            return AdaptiveCoachingBias(
                challenge_level=str(profile.get("challenge_level", "steady") or "steady"),
                hint_depth=str(profile.get("hint_depth", "guided") or "guided"),
                review_urgency=str(profile.get("review_urgency", "normal") or "normal"),
                explanation_mode=str(profile.get("explanation_mode", "grounded") or "grounded"),
                next_step_bias=str(profile.get("next_step_bias", "steady") or "steady"),
                summary=str(profile.get("summary", "") or ""),
                evidence=[str(item) for item in profile.get("evidence", []) if str(item).strip()],
                difficulty=str(profile.get("difficulty", "medium") or "medium"),
                hint_count=int(profile.get("hint_count", 2) or 2),
                explanation_depth=str(profile.get("explanation_depth", "grounded") or "grounded"),
                code_reveal=str(profile.get("code_reveal", "scaffold") or "scaffold"),
                practice_type=str(profile.get("practice_type", "focused") or "focused"),
                review_frequency=str(profile.get("review_frequency", "normal") or "normal"),
                material_recommendation=str(profile.get("material_recommendation", "current") or "current"),
                should_reveal_code=bool(profile.get("should_reveal_code", False)),
                pedagogy_mode=str(profile.get("pedagogy_mode", "direct") or "direct"),
            )
        return AdaptiveCoachingBias()
