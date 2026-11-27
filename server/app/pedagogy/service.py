from __future__ import annotations

from typing import Any

from ..core.models import AffectState as CoreAffectState
from ..core.models import (
    CurrentFilePayload,
    MemorySnapshot,
    TurnRequest,
    UserProfile,
    WorkspaceUnderstandingSnapshot,
)
from .goal_and_adaptation_mixin import GoalAndAdaptationMixin
from .implementation_coach import ImplementationCoachService
from .principle_explainer import PrincipleExplainerService
from .project_adaptation_coach import ProjectAdaptationCoachService
from .project_idea_miner import ProjectIdeaMinerService
from .project_source_scout import ProjectSourceScoutService
from .service_types import (
    AdaptiveCoachingBias as AdaptiveCoachingBias,
)
from .service_types import (
    ImplementationGuide as ImplementationGuide,
)
from .service_types import (
    LearnerState as LearnerState,
)
from .service_types import (
    PedagogyArtifacts as PedagogyArtifacts,
)
from .service_types import (
    TeachingDecision as TeachingDecision,
)
from .service_types import (
    TeachingMode as TeachingMode,
)
from .smalltalk import is_casual_greeting_or_smalltalk, is_exploratory_or_research_query
from .turn_decision import TurnFacts, decide_turn


class PedagogyService(GoalAndAdaptationMixin):
    @staticmethod
    def _requests_concrete_next_step(
        message: str,
        current_file: CurrentFilePayload | None,
    ) -> bool:
        if not message or current_file is None:
            return False

        lowered = message.lower()
        next_step_tokens = (
            "next step",
            "next move",
            "first step",
            "smallest next step",
            "tiny next step",
            "give me the next step",
            "only tell me the next step",
            "what should i do next",
            "what do i do next",
            "what should i change first",
            "下一步",
            "下一手",
            "最小可验证动作",
            "最小动作",
            "先做什么",
            "先改哪里",
            "下一步该做什么",
            "只告诉我",
        )
        scope_tokens = (
            "small",
            "smallest",
            "tiny",
            "minimal",
            "thin",
            "narrow",
            "focused",
            "verifiable",
            "teaching value",
            "very small",
            "很小",
            "最小",
            "小步",
            "一小步",
            "可验证",
            "教学价值",
            "小补丁",
        )
        return any(token in lowered for token in next_step_tokens) and any(
            token in lowered for token in scope_tokens
        )

    @staticmethod
    def _rejects_broad_plan(message: str) -> bool:
        lowered = message.lower()
        return any(
            token in lowered
            for token in (
                "not a whole study plan",
                "not a full study plan",
                "without turning this into a full study plan",
                "don't turn this into a full study plan",
                "don't turn this into a study plan",
                "don't make this a plan",
                "先别展开成总计划",
                "不要把它变成完整学习计划",
                "不要把它变成学习计划",
                "别把它变成学习计划",
                "先别变成计划",
                "不要变成计划",
            )
        )

    @staticmethod
    def _requests_diagnosis(message: str) -> bool:
        lowered = message.lower()
        return any(
            token in lowered
            for token in (
                "diagnose",
                "diagnosis",
                "what's wrong",
                "whats wrong",
                "what is wrong",
                "why does this fail",
                "why is this failing",
                "why this fails",
                "failing test",
                "this error",
                "this bug",
                "stack trace",
                "traceback",
                "排查",
                "诊断",
                "报错",
                "为什么会挂",
                "为什么失败",
                "这个错误",
                "这个 bug",
            )
        )

    @staticmethod
    def _requests_language_coaching(message: str) -> bool:
        lowered = message.lower()
        return any(
            token in lowered
            for token in (
                "revise",
                "rewrite",
                "edit this paragraph",
                "project update paragraph",
                "improve this writing",
                "improve this sentence",
                "teach me the word",
                "vocabulary",
                "word meaning",
                "润色",
                "改写",
                "措辞",
                "段落",
                "句子",
                "单词",
                "词汇",
                "中文写作",
                "英文写作",
            )
        )

    @staticmethod
    def _requests_idea_implementation(message: str) -> bool:
        lowered = message.lower()
        return any(
            token in lowered
            for token in (
                "implement",
                "build",
                "ship",
                "make this",
                "i want to build",
                "i want to make",
                "i have an idea",
                "prototype",
                "落地",
                "原型",
                "最小原型",
                "最小可验证",
                "做出来",
                "做成原型",
                "想实现",
                "想做",
                "我有个 idea",
                "我有一个 idea",
                "我有个 ai idea",
                "我有一个 ai idea",
            )
        )

    @staticmethod
    def _introduces_new_idea(message: str) -> bool:
        lowered = message.lower()
        return any(
            token in lowered
            for token in (
                "i have an idea",
                "i want to build",
                "i want to make",
                "\u60f3\u505a",
                "\u60f3\u5b9e\u73b0",
                "\u6211\u60f3\u628a",
                "\u6211\u6709\u4e2a idea",
                "\u6211\u6709\u4e00\u4e2a idea",
                "\u6211\u6709\u4e2a ai idea",
                "\u6211\u6709\u4e00\u4e2a ai idea",
            )
        )

    @staticmethod
    def _requests_project_idea_mining(message: str) -> bool:
        lowered = message.lower()
        return any(
            token in lowered
            for token in (
                "idea from",
                "what should i build",
                "project idea",
                "extract from this codebase",
                "\u7ec3\u4ec0\u4e48",
                "\u503c\u5f97\u7ec3",
                "\u63d0\u70bc idea",
                "\u63d0\u70bc\u8bad\u7ec3\u9898",
                "\u9879\u76ee\u70b9\u5b50",
                "\u4ece\u9879\u76ee\u91cc\u63d0\u70bc",
                "\u4ece\u8fd9\u4e2a\u9879\u76ee\u91cc\u627e",
            )
        )

    def __init__(
        self,
        implementation_coach: ImplementationCoachService | None = None,
        project_idea_miner: ProjectIdeaMinerService | None = None,
        project_adaptation_coach: ProjectAdaptationCoachService | None = None,
        project_source_scout: ProjectSourceScoutService | None = None,
        principle_explainer: PrincipleExplainerService | None = None,
    ) -> None:
        self._implementation_coach = implementation_coach or ImplementationCoachService()
        self._project_idea_miner = project_idea_miner or ProjectIdeaMinerService()
        self._project_adaptation_coach = project_adaptation_coach or ProjectAdaptationCoachService()
        self._project_source_scout = project_source_scout or ProjectSourceScoutService()
        self._principle_explainer = principle_explainer or PrincipleExplainerService()

    def build_workspace_understanding(
        self,
        *,
        request: TurnRequest,
        memory_snapshot: MemorySnapshot | None = None,
        resource_context: dict[str, Any] | None = None,
    ) -> WorkspaceUnderstandingSnapshot | None:
        return self._project_idea_miner.build_workspace_understanding(
            request=request,
            memory_snapshot=memory_snapshot,
            resource_context=resource_context,
        )

    def analyze_turn(
        self,
        *,
        request: TurnRequest,
        profile: UserProfile | None = None,
        memory_snapshot: MemorySnapshot | None = None,
        affect_state: CoreAffectState | None = None,
        external_references: list[dict[str, object]] | None = None,
    ) -> tuple[LearnerState, TeachingDecision, PedagogyArtifacts]:
        learner_state = self.infer_learner_state(
            request=request,
            profile=profile,
            memory_snapshot=memory_snapshot,
        )
        decision = self.decide_teaching(
            request=request,
            learner_state=learner_state,
            profile=profile,
            memory_snapshot=memory_snapshot,
            affect_state=affect_state,
        )
        artifacts = self.build_artifacts(
            request=request,
            learner_state=learner_state,
            decision=decision,
            profile=profile,
            memory_snapshot=memory_snapshot,
            affect_state=affect_state,
            external_references=external_references,
        )
        return learner_state, decision, artifacts

    def infer_learner_state(
        self,
        *,
        request: TurnRequest,
        profile: UserProfile | None = None,
        memory_snapshot: MemorySnapshot | None = None,
    ) -> LearnerState:
        message = request.message.lower()
        evidence: list[str] = []

        frustration_level = 0.15
        if any(token in message for token in ("stuck", "blocked", "confused", "frustrated", "卡住", "不会", "报错")):
            frustration_level += 0.45
            evidence.append("message_signals_block")
        if any(token in message for token in ("urgent", "asap", "直接", "give me the code", "just tell me")):
            # An explicit request for a direct answer is a turn-decision
            # signal, not evidence that the learner is frustrated. Keep the
            # fact separate from affect inference.
            evidence.append("message_requests_rescue")
        if memory_snapshot and memory_snapshot.pace_signal in {"gentle", "fragile"}:
            frustration_level += 0.15
            evidence.append(f"pace_signal:{memory_snapshot.pace_signal}")
        if memory_snapshot and memory_snapshot.due_review_count > 0:
            evidence.append("due_reviews_present")
        if memory_snapshot and memory_snapshot.top_weakness:
            evidence.append(f"top_weakness:{memory_snapshot.top_weakness}")
        latest_outcome = self._latest_learning_outcome(memory_snapshot)
        if latest_outcome:
            outcome_name = str(latest_outcome.get("outcome", "")).strip()
            repetition_count = int(latest_outcome.get("repetition_count", 1) or 1)
            if outcome_name:
                evidence.append(f"latest_outcome:{outcome_name}")
            if outcome_name in {"repeated_error", "task_abandoned", "blocked"}:
                frustration_level += 0.18
                evidence.append("learning_outcome_failure")
            if outcome_name in {"repeated_error", "evaluation", "task_abandoned", "blocked"} and repetition_count >= 2:
                frustration_level += 0.12
                evidence.append("learning_outcome_repeated_failure")
            if outcome_name in {"code_landed", "tests_passed", "concept_answered_correctly"}:
                frustration_level = max(0.08, frustration_level - 0.08)
                evidence.append("learning_outcome_success")

        attempt_count_recent = self._estimate_attempt_count(request.current_file, memory_snapshot)
        if attempt_count_recent >= 2:
            frustration_level += 0.1
            evidence.append("multiple_recent_attempts")

        needs_review = bool(
            memory_snapshot
            and (
                memory_snapshot.due_review_count > 0
                or memory_snapshot.due_reviews
                or memory_snapshot.top_weakness
            )
        )
        casual_greeting = is_casual_greeting_or_smalltalk(request.message)
        needs_rescue = False if casual_greeting else (
            frustration_level >= 0.65 or request.answer_mode == "direct"
        )

        if needs_rescue:
            hint_depth = "direct"
        elif request.answer_mode == "balanced":
            hint_depth = "balanced"
        else:
            hint_depth = profile.teaching_style if profile is not None else "guided"
            if hint_depth == "auto":
                hint_depth = "guided"
        if memory_snapshot and memory_snapshot.coaching_adaptation is not None:
            adaptive_hint_depth = memory_snapshot.coaching_adaptation.hint_depth
            if adaptive_hint_depth == "direct":
                hint_depth = "direct"
            elif adaptive_hint_depth == "lighter" and hint_depth != "direct":
                hint_depth = "lighter"

        current_confidence = max(0.1, min(0.95, 0.85 - frustration_level))
        learner_signal = "blocked" if needs_rescue else "uncertain" if frustration_level >= 0.35 else "steady"
        active_focus = self._pick_focus(request=request, memory_snapshot=memory_snapshot, profile=profile)

        return LearnerState(
            current_confidence=round(current_confidence, 2),
            frustration_level=min(round(frustration_level, 2), 1.0),
            attempt_count_recent=attempt_count_recent,
            needs_rescue=needs_rescue,
            needs_review=needs_review,
            preferred_hint_depth=hint_depth,
            learner_signal=learner_signal,
            active_focus=active_focus,
            evidence=evidence,
        )

    def decide_teaching(
        self,
        *,
        request: TurnRequest,
        learner_state: LearnerState,
        profile: UserProfile | None = None,
        memory_snapshot: MemorySnapshot | None = None,
        affect_state: CoreAffectState | None = None,
        skill_state: str | None = None,
        skill_projection: dict[str, Any] | None = None,
        active_goal: bool | None = None,
        intervention_allowed: bool | None = None,
        intervention_reason: str = "",
    ) -> TeachingDecision:
        scenario, focus_area, scenario_evidence = self._classify_scenario(
            request=request,
            memory_snapshot=memory_snapshot,
            profile=profile,
        )
        onboarding_needed = self._needs_onboarding_turn(
            request=request,
            learner_state=learner_state,
            memory_snapshot=memory_snapshot,
            profile=profile,
            scenario=scenario,
        )
        affect_recovery_signal = affect_state.recovery_signal if affect_state is not None else ""
        affect_evidence: list[str] = []
        adaptive_bias = self._adaptive_bias(memory_snapshot)
        if affect_recovery_signal:
            affect_evidence.append(f"affect_recovery:{affect_recovery_signal}")
        if affect_state is not None and affect_state.needs_reassurance:
            affect_evidence.append("affect_needs_reassurance")
        if affect_state is not None and affect_state.urgency_level == "high":
            affect_evidence.append("affect_high_urgency")
        if adaptive_bias.summary:
            affect_evidence.append(f"adaptive_bias:{adaptive_bias.next_step_bias}")

        should_embed_review_recovery = bool(
            (
                affect_recovery_signal in {"fragile", "overloaded"}
                or adaptive_bias.review_urgency == "high"
            )
            and learner_state.needs_review
            and memory_snapshot is not None
            and memory_snapshot.due_reviews
            and scenario not in {"project_idea_mining", "principle_explanation", "project_sourcing"}
        )

        if onboarding_needed:
            mode = "onboarding"
            tone_profile = "steady"
            should_reveal_code = False
            scenario = "guided"
            focus_area = self._onboarding_focus(request, learner_state, profile, memory_snapshot)
            affect_evidence.append("relationship_first_onboarding")
        elif should_embed_review_recovery:
            mode: TeachingMode = "review_reflection"
            tone_profile = "concise_rescue" if affect_recovery_signal == "overloaded" else "review_loop"
            should_reveal_code = False
            focus_area = self._review_recovery_focus(memory_snapshot, focus_area, learner_state.active_focus)
            affect_evidence.append("affect_embeds_due_review")
        elif learner_state.needs_rescue and scenario not in {"project_idea_mining", "principle_explanation", "project_sourcing"}:
            mode: TeachingMode = "direct_rescue"
            tone_profile = "concise_rescue"
            should_reveal_code = True
        elif adaptive_bias.challenge_level == "raise" and scenario == "engineering_challenge":
            mode = "challenge"
            tone_profile = "challenge_coach"
            should_reveal_code = False
        elif scenario == "idea_implementation":
            mode = "idea_implementation"
            tone_profile = "guided_build"
            should_reveal_code = False
        elif scenario == "planning":
            mode = "planning"
            tone_profile = "plan_coach"
            should_reveal_code = False
        elif scenario == "concept_teaching":
            mode = "concept_teaching"
            tone_profile = "teaching_clarity"
            should_reveal_code = False
        elif scenario == "engineering_challenge":
            mode = "engineering_challenge"
            tone_profile = "challenge_coach"
            should_reveal_code = False
        elif scenario == "project_idea_mining":
            mode = "project_idea_mining"
            tone_profile = "proactive_coach"
            should_reveal_code = False
        elif scenario == "project_adaptation":
            mode = "project_adaptation"
            tone_profile = "steady_migration"
            should_reveal_code = False
        elif scenario == "project_sourcing":
            mode = "project_sourcing"
            tone_profile = "proactive_coach"
            should_reveal_code = False
        elif scenario == "principle_explanation":
            mode = "principle_explanation"
            tone_profile = "teaching_clarity"
            should_reveal_code = False
        elif learner_state.needs_review:
            mode = "review_reflection"
            tone_profile = "review_loop"
            should_reveal_code = False
        else:
            mode = "guided"
            tone_profile = "steady"
            should_reveal_code = False

        should_end_with_question = mode not in {
            "direct_rescue",
            "project_idea_mining",
            "project_sourcing",
            "planning",
        }
        if mode == "onboarding":
            should_end_with_question = True
        should_generate_exercise = scenario in {
            "idea_implementation",
            "project_idea_mining",
            "project_adaptation",
            "project_sourcing",
            "principle_explanation",
            "concept_teaching",
            "engineering_challenge",
            "review_reflection",
        } or mode == "review_reflection"
        if mode == "onboarding":
            should_generate_exercise = False
        should_produce_plan_artifact = scenario in {
            "project_adaptation",
            "project_idea_mining",
            "project_sourcing",
            "planning",
        }
        if mode == "onboarding":
            should_produce_plan_artifact = False
        should_trigger_deep_analysis = (
            scenario == "project_adaptation" and len(scenario_evidence + learner_state.evidence) >= 3
        )
        should_focus_on_implementation_steps = scenario in {
            "idea_implementation",
            "project_adaptation",
            "engineering_challenge",
        } or mode == "review_reflection"
        if mode == "onboarding":
            should_focus_on_implementation_steps = False

        if affect_recovery_signal == "overloaded":
            should_end_with_question = False
            should_generate_exercise = False
            should_focus_on_implementation_steps = True
        elif affect_recovery_signal == "fragile":
            if learner_state.needs_review:
                should_end_with_question = False
            if mode == "idea_implementation":
                should_generate_exercise = False
        if adaptive_bias.challenge_level == "lower":
            should_end_with_question = False
            should_focus_on_implementation_steps = True
        if adaptive_bias.next_step_bias == "shrink" and mode in {
            "idea_implementation",
            "engineering_challenge",
            "challenge",
        }:
            should_generate_exercise = True
        if mode not in {
            "onboarding",
            "planning",
            "project_idea_mining",
            "project_sourcing",
            "project_adaptation",
        }:
            if adaptive_bias.should_reveal_code or adaptive_bias.code_reveal == "full":
                should_reveal_code = True
            elif adaptive_bias.code_reveal == "withhold" and mode != "direct_rescue":
                should_reveal_code = False
            if adaptive_bias.pedagogy_mode == "debug_guide":
                should_end_with_question = False
                should_focus_on_implementation_steps = True
            elif adaptive_bias.pedagogy_mode == "socratic" and mode not in {"direct_rescue"}:
                should_reveal_code = False
                should_end_with_question = True
            elif adaptive_bias.pedagogy_mode == "direct":
                should_end_with_question = False
                should_focus_on_implementation_steps = True
        if mode == "direct_rescue":
            should_reveal_code = True

        primary_goal = self._build_primary_goal(scenario, focus_area, learner_state.active_focus)
        if mode == "onboarding":
            primary_goal = self._build_primary_goal("onboarding", focus_area, learner_state.active_focus)
        if mode == "review_reflection":
            primary_goal = self._build_primary_goal("review_reflection", focus_area, learner_state.active_focus)
        if mode == "direct_rescue" and focus_area:
            primary_goal = f"Stabilize '{focus_area}' with the next smallest move before widening scope."
        if adaptive_bias.next_step_bias == "shrink" and focus_area:
            primary_goal = f"Reduce '{focus_area}' to the smallest recoverable move before attempting a wider fix."
        elif adaptive_bias.next_step_bias == "widen" and focus_area and scenario in {"idea_implementation", "engineering_challenge"}:
            primary_goal = f"Use the verified progress on '{focus_area}' to stretch into the next slightly wider implementation move."

        lesson_shape, exercise_shape, teaching_strategy, closing_move, artifact_priority = self._mode_playbook(
            mode=mode,
            scenario=scenario,
            focus_area=focus_area or learner_state.active_focus,
            learner_state=learner_state,
            memory_snapshot=memory_snapshot,
            adaptive_bias=adaptive_bias,
            decision_should_generate_exercise=should_generate_exercise,
            decision_should_produce_plan_artifact=should_produce_plan_artifact,
        )

        reason_parts = scenario_evidence + learner_state.evidence + affect_evidence
        reason = "; ".join(reason_parts) if reason_parts else "default_guided_progression"

        from .teaching_depth import (
            resolve_teaching_depth,
            resolve_teaching_depth_skill_state,
        )

        effective_skill_state = skill_state or resolve_teaching_depth_skill_state(
            skill_projection=skill_projection,
            scenario=scenario,
        )
        depth = resolve_teaching_depth(
            message=request.message,
            skill_state=effective_skill_state,
            affect_urgency=(
                str(getattr(affect_state, "urgency_level", "") or "") if affect_state else None
            ),
            needs_rescue=learner_state.needs_rescue,
        )
        affect_allows_intervention = not (
            affect_state is not None
            and affect_state.recovery_signal in {"fragile", "overloaded"}
        )
        effective_intervention_allowed = affect_allows_intervention and (
            intervention_allowed is not False
        )
        effective_intervention_reason = (
            "affect_recovery"
            if not affect_allows_intervention
            else intervention_reason
        )
        turn = decide_turn(
            TurnFacts(
                message=request.message,
                requested_intent=getattr(request, "intent", "coach"),
                intent_source=getattr(request, "intent_source", "explicit"),
                answer_mode=profile.answer_policy if profile else None,
                needs_rescue=learner_state.needs_rescue,
                needs_review=learner_state.needs_review,
                due_review_count=memory_snapshot.due_review_count if memory_snapshot else 0,
                has_active_goal=(
                    bool(active_goal)
                    if active_goal is not None
                    else bool(profile and profile.long_term_goals)
                ),
                has_trusted_evidence=effective_skill_state
                in {"assisted", "independent", "repeat_verified"},
                activity_in_progress=bool(
                    memory_snapshot
                    and memory_snapshot.active_thread
                    and memory_snapshot.active_thread.blocker
                ),
                intervention_allowed=effective_intervention_allowed,
                intervention_reason=effective_intervention_reason,
                onboarding_needed=onboarding_needed,
            )
        )
        if depth.direct_answer_override or turn.mode == "direct_answer":
            # One turn decision, one set of constraints: an explicit direct
            # answer request must not still carry a quiz, exercise or formal
            # plan artifact through the teaching-decision contract.
            should_end_with_question = False
            should_generate_exercise = False
            should_produce_plan_artifact = False
            should_focus_on_implementation_steps = False
            exercise_shape = ""
            reason_parts.append("direct_answer_override")
        elif turn.mode == "chat":
            # Unknown or ordinary chat: keep the conversation open, but do not
            # mint a formal task, plan or forced check.
            should_end_with_question = False
            should_generate_exercise = False
            should_produce_plan_artifact = False
            if mode == "review_reflection" and not should_embed_review_recovery:
                mode = "guided"
                tone_profile = "steady"
        elif turn.mode == "review":
            mode = "review_reflection"
            tone_profile = "review_loop"
            should_produce_plan_artifact = False
        elif turn.mode == "practice":
            should_generate_exercise = True
            should_produce_plan_artifact = False
        elif turn.mode == "plan":
            should_produce_plan_artifact = True
            should_generate_exercise = False
        if not turn.allow_question:
            should_end_with_question = False
        reason_parts.append(f"turn:{turn.mode}:{turn.source}")
        reason = "; ".join(dict.fromkeys(reason_parts))
        evidence = list(dict.fromkeys(reason_parts + depth.evidence + turn.evidence))

        return TeachingDecision(
            mode=mode,
            reason=reason,
            primary_goal=primary_goal,
            lesson_shape=lesson_shape,
            exercise_shape=exercise_shape,
            teaching_strategy=teaching_strategy,
            closing_move=closing_move,
            artifact_priority=artifact_priority,
            should_end_with_question=should_end_with_question,
            should_generate_exercise=should_generate_exercise,
            should_reveal_code=should_reveal_code,
            should_produce_plan_artifact=should_produce_plan_artifact,
            should_trigger_deep_analysis=should_trigger_deep_analysis,
            should_focus_on_implementation_steps=should_focus_on_implementation_steps,
            tone_profile=tone_profile,
            scenario=scenario,
            focus_area=focus_area,
            depth_level=depth.level,
            depth_label=depth.label,
            direct_answer_override=depth.direct_answer_override,
            offer_light_practice=depth.offer_light_practice,
            turn_mode=turn.mode,
            turn_source=turn.source,
            turn_confidence=turn.confidence,
            turn_allow_question=turn.allow_question,
            turn_allow_formal_task=turn.allow_formal_task,
            turn_allow_formal_plan=turn.allow_formal_plan,
            turn_allow_review=turn.allow_review,
            turn_may_interrupt=turn.may_interrupt,
            evidence=evidence,
        )

    def _mode_playbook(
        self,
        *,
        mode: TeachingMode,
        scenario: str,
        focus_area: str,
        learner_state: LearnerState,
        memory_snapshot: MemorySnapshot | None,
        adaptive_bias: AdaptiveCoachingBias,
        decision_should_generate_exercise: bool,
        decision_should_produce_plan_artifact: bool,
    ) -> tuple[str, str, str, str, list[str]]:
        weak_spot = memory_snapshot.top_weakness if memory_snapshot and memory_snapshot.top_weakness else ""
        selected_assets = self._relevant_teaching_assets(
            memory_snapshot,
            scenario=mode if mode != "guided" else scenario,
            focus_area=focus_area or learner_state.active_focus,
            limit=2,
        )
        asset_hint = selected_assets[0].summary or selected_assets[0].title if selected_assets else ""
        latest_outcome = self._latest_learning_outcome(memory_snapshot)
        repeated_failure = bool(
            latest_outcome
            and str(latest_outcome.get("outcome", "")).strip() in {"repeated_error", "evaluation", "task_abandoned", "blocked"}
            and int(latest_outcome.get("repetition_count", 1) or 1) >= 2
        )
        artifact_priority: list[str] = []

        def apply_asset_hints(
            lesson_shape: str,
            exercise_shape: str,
            teaching_strategy: str,
            closing_move: str,
            priority: list[str],
        ) -> tuple[str, str, str, str, list[str]]:
            if adaptive_bias.summary:
                if adaptive_bias.next_step_bias == "shrink":
                    lesson_shape = f"{lesson_shape} Keep the scope even tighter than usual."
                    exercise_shape = f"{exercise_shape} Compress it into one branch, one function, or one observable behavior."
                    teaching_strategy = (
                        f"{teaching_strategy} Reduce breadth, deepen the hinting, and verify one recovery step before widening."
                    ).strip()
                    closing_move = (
                        f"{closing_move} Ask only for the smallest recovery check, not a broader progress report."
                    ).strip()
                elif adaptive_bias.next_step_bias == "widen":
                    lesson_shape = f"{lesson_shape} Use the recent win to transfer the idea to a nearby boundary."
                    exercise_shape = f"{exercise_shape} Let the learner own a slightly stronger next move."
                    teaching_strategy = (
                        f"{teaching_strategy} Hold back a little more detail and bias toward transfer."
                    ).strip()
            if adaptive_bias.hint_depth == "direct":
                teaching_strategy = (
                    f"{teaching_strategy} Be explicit about the first move, keep options narrow, and reduce branching choices."
                ).strip()
                closing_move = (
                    f"{closing_move} Ask for one concrete verification result, not a broad reflection."
                ).strip()
            elif adaptive_bias.hint_depth == "lighter":
                teaching_strategy = (
                    f"{teaching_strategy} Leave more ownership with the learner and avoid over-explaining the first attempt."
                ).strip()
            if adaptive_bias.explanation_mode == "rebuild":
                lesson_shape = f"{lesson_shape} Rebuild the mental model from one concrete failure path."
                teaching_strategy = (
                    f"{teaching_strategy} Re-explain the mechanism from the broken path before introducing variation."
                ).strip()
            elif adaptive_bias.explanation_mode == "transfer":
                lesson_shape = f"{lesson_shape} Push the learner to transfer the idea into a nearby code boundary."
                closing_move = (
                    f"{closing_move} Ask where the same rule should transfer next."
                ).strip()
            if selected_assets:
                best_asset = selected_assets[0]
                teaching_strategy = f"{teaching_strategy} {self._asset_strategy_hint(best_asset, mode)}".strip()
                closing_move = f"{closing_move} {self._asset_closing_hint(best_asset)}".strip()
            return lesson_shape, exercise_shape, teaching_strategy, closing_move, priority

        if decision_should_produce_plan_artifact:
            artifact_priority.append("plan")
        if decision_should_generate_exercise:
            artifact_priority.append("exercise")
        if mode in {"project_idea_mining", "project_sourcing"}:
            artifact_priority.append("idea")
        elif mode in {"project_adaptation"}:
            artifact_priority.append("migration")
        elif mode in {"principle_explanation", "concept_teaching"}:
            artifact_priority.append("principle")
        elif mode in {"review_reflection"}:
            artifact_priority.append("review")
        elif mode in {"engineering_challenge"}:
            artifact_priority.append("challenge")

        if mode == "idea_implementation":
            return apply_asset_hints(
                "One thin implementation slice anchored to a visible behavior.",
                "One patchable behavior with one verification loop.",
                "Coach the learner through the smallest working slice, then widen only after the first check passes.",
                "Ask for the next smallest change or the first check result.",
                artifact_priority or ["exercise", "implementation"],
            )
        if mode == "project_idea_mining":
            return apply_asset_hints(
                "A short mining pass that turns the workspace into 1-3 candidate drills.",
                "A ranked list of candidate project ideas with scope, first step, and acceptance signal.",
                "Mine opportunities from entry points, weaknesses, and diagnostics; keep the output concrete and project-backed.",
                "Ask which idea the learner wants to convert into the next practice loop.",
                artifact_priority or ["idea", "exercise", "plan"],
            )
        if mode == "project_adaptation":
            return apply_asset_hints(
                "A migration lane with one stable boundary and one preserved surface.",
                "One adaptation slice that names affected areas, preserve areas, and rollback points.",
                "Show the first boundary to move, then sequence the rest so the learner can adapt the real project safely.",
                "Ask the learner to confirm the first boundary before widening scope.",
                artifact_priority or ["migration", "plan", "exercise"],
            )
        if mode == "planning":
            return apply_asset_hints(
                "A sequencing conversation that turns the goal into a training cadence.",
                "A plan-shaped answer with stages, review rhythm, and the next step clearly named.",
                "Keep the learner in planning mode until the path is narrow enough to execute without confusion.",
                "Ask the learner to choose the next milestone or the highest-risk step.",
                artifact_priority or ["plan"],
            )
        if mode == "concept_teaching":
            return apply_asset_hints(
                "A concept-first explanation grounded in one code boundary and one failure mode.",
                "One explanation plus one concrete application check.",
                "Teach the mechanism through the code the learner can see right now, not abstract theory.",
                "Ask the learner to restate the mechanism in their own words.",
                artifact_priority or ["principle", "exercise"],
            )
        if mode == "engineering_challenge":
            return apply_asset_hints(
                "A project-backed drill that the learner must execute.",
                "One challenge prompt with explicit constraints, success criteria, and a fallback shrink step.",
                "Push the learner to produce a concrete implementation under realistic constraints.",
                "Ask for the first attempt or the smallest safe patch.",
                artifact_priority or ["challenge", "exercise"],
            )
        if mode == "review_reflection":
            return apply_asset_hints(
                "A recovery loop that turns review into the next coaching move.",
                "One review prompt focused on the first high-leverage fix.",
                (
                    "Use due reviews, repeated failures, weak spots, and the live blocker to keep the learner on the fastest recovery path."
                    if repeated_failure
                    else "Use due reviews, weak spots, and the live blocker to keep the learner on the fastest recovery path."
                ),
                "Ask what changed, what was verified, or what still blocks the next move.",
                artifact_priority or ["review", "plan", "exercise"],
            )
        if mode == "project_sourcing":
            return apply_asset_hints(
                "A sourcing pass that finds a real outside project worth training on.",
                "A short shortlist of candidate sources with filters and a first task.",
                "Match the learner's goal and weakness to a realistic external repo or case study.",
                "Ask which source the learner wants to inspect first.",
                artifact_priority or ["idea", "plan"],
            )
        if mode == "onboarding":
            return apply_asset_hints(
                "A relationship-first coaching turn that orients, reassures, and narrows the first real lane.",
                "One intake-style next move: clarify goal, level, project context, and the first coaching lane.",
                "Do not teach too much at once. First build trust, confirm the learner's goal, current level, and the lane that should guide the next turns.",
                "End with one proposed lane or one to three targeted questions that make the next coaching turn sharper.",
                artifact_priority or [],
            )
        if mode == "principle_explanation":
            return apply_asset_hints(
                "A principle-led explanation attached to one concrete anchor.",
                "One principle note plus one follow-up exercise to verify transfer.",
                "Explain the rule, the wrong intuition, and the smallest code boundary where it matters.",
                "Ask the learner to name the boundary and the failure mode.",
                artifact_priority or ["principle", "exercise"],
            )
        if mode == "direct_rescue":
            return apply_asset_hints(
                "A compressed rescue move that gets the learner unstuck immediately.",
                "One smallest safe fix with a single verification path.",
                "Reduce cognitive load, reveal the essential step, and stop before widening scope.",
                "Ask the learner to run the smallest check or confirm the fix.",
                artifact_priority or ["exercise"],
            )
        if mode == "challenge":
            return apply_asset_hints(
                "A higher-pressure stretch move that still stays reviewable.",
                "One stretch prompt with a narrow boundary and a verification hook.",
                "Hold the learner to a stronger standard without losing the one-step-at-a-time coaching style.",
                "Ask the learner to commit to the first implementation choice.",
                artifact_priority or ["challenge", "exercise"],
            )
        if mode == "reflection":
            return apply_asset_hints(
                "A reflective pass that consolidates what changed.",
                "One reflection note with the next review-worthy step.",
                "Turn the recent work into a clearer memory trace and a more intentional next move.",
                "Ask what was learned and what should be revisited later.",
                artifact_priority or ["review"],
            )
        if weak_spot:
            return apply_asset_hints(
                f"A steady coaching lane aimed at {weak_spot}.",
                "One narrow move with a check that fits the current weakness.",
                f"Use the learner's repeated weakness around {weak_spot} to decide the next smallest helpful move.",
                f"Ask the learner to confirm the first step around {weak_spot}.",
                artifact_priority or ["exercise"],
            )
        if asset_hint:
            return apply_asset_hints(
                f"A grounded coaching lane that reuses teaching asset '{asset_hint}'.",
                "One small move anchored to a teaching asset.",
                "Bias toward the most reusable teaching asset already learned from the workspace.",
                "Ask the learner to apply the asset to the current path.",
                artifact_priority or ["exercise"],
            )
        return apply_asset_hints(
            "A steady guided coaching lane.",
            "One small move and one check.",
            "Keep the learner moving with the smallest verifiable step.",
            "Ask for the next concrete step.",
            artifact_priority or ["exercise"],
        )

    def build_artifacts(
        self,
        *,
        request: TurnRequest,
        learner_state: LearnerState,
        decision: TeachingDecision,
        profile: UserProfile | None = None,
        memory_snapshot: MemorySnapshot | None = None,
        affect_state: CoreAffectState | None = None,
        external_references: list[dict[str, object]] | None = None,
    ) -> PedagogyArtifacts:
        artifacts = PedagogyArtifacts()
        effective_mode = "review_reflection" if decision.mode == "review_reflection" else decision.scenario
        selected_assets = self._relevant_teaching_assets(
            memory_snapshot,
            scenario=effective_mode or decision.mode,
            focus_area=decision.focus_area or learner_state.active_focus,
            limit=2,
        )
        if effective_mode == "project_sourcing" and not selected_assets:
            selected_assets = self._fallback_project_sourcing_assets(memory_snapshot, limit=2)
        artifacts.selected_teaching_assets = list(selected_assets)
        if effective_mode == "idea_implementation":
            artifacts.implementation_guide = self._implementation_coach.build_guide(
                request=request,
                learner_state=learner_state,
                decision=decision,
                profile=profile,
                memory_snapshot=memory_snapshot,
            )
        elif effective_mode == "engineering_challenge":
            artifacts.implementation_guide = self._implementation_coach.build_guide(
                request=request,
                learner_state=learner_state,
                decision=decision,
                profile=profile,
                memory_snapshot=memory_snapshot,
            )
        elif effective_mode == "project_idea_mining":
            artifacts.project_ideas = self._project_idea_miner.mine_ideas(
                request=request,
                learner_state=learner_state,
                decision=decision,
                profile=profile,
                memory_snapshot=memory_snapshot,
                selected_assets=selected_assets,
            )
        elif effective_mode == "project_adaptation":
            artifacts.adaptation_guide = self._project_adaptation_coach.build_guide(
                request=request,
                learner_state=learner_state,
                decision=decision,
                profile=profile,
                memory_snapshot=memory_snapshot,
            )
        elif effective_mode == "project_sourcing":
            resource_references = []
            if memory_snapshot is not None:
                resource_references = [
                    *[
                        item
                        for item in memory_snapshot.resources[:4]
                        if item.knowledge_fragments and item.trust_score >= 0.35
                    ]
                ]
            grounded_reference_payload = self._grounded_reference_payload(
                external_references,
                fallback_focus_area=decision.focus_area or learner_state.active_focus,
            )
            if not grounded_reference_payload:
                grounded_reference_payload = [
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
                        "title": f"Grounded source for {resource.name.strip() or resource.kind}",
                        "repo_hint": (
                            f"Start from {resource.canonical_source or resource.source} and turn the saved snippet into one narrow training lane."
                        ),
                        "first_task": (
                            f"Read the saved snippet for {resource.name.strip() or resource.kind}, then extract the first tiny coding move before opening a wider repo search."
                        ),
                        "tags": ["grounded-source", "external-reference"],
                    }
                    for resource in resource_references
                    if resource.knowledge_fragments and isinstance(resource.knowledge_fragments[0], dict)
                ]
            relevant_assets = selected_assets or self._fallback_project_sourcing_assets(memory_snapshot, limit=2)
            grounded_reference_payload.extend(
                [
                    {
                        "source": f"teaching-asset://{asset.id}",
                        "snippet": (
                            asset.exercise_seed
                            or asset.implementation_pattern
                            or asset.summary
                            or asset.title
                        ),
                        "trust_score": max(0.45, float(asset.trust_score or 0.0)),
                        "created_at": asset.updated_at or asset.created_at or "",
                        "focus_area": asset.focus_area or decision.focus_area or asset.title,
                        "quality_flags": ["teaching_asset_grounded"],
                        "title": f"Saved training pattern: {asset.title}",
                        "repo_hint": (
                            f"Use the saved teaching asset '{asset.title}' as the filter for choosing an outside project or repo lane."
                        ),
                        "fit_reason": (
                            f"This trainer has already learned that '{asset.summary or asset.title}' is a reusable coaching anchor."
                        ),
                        "training_value": (
                            "It keeps outside project selection aligned with a pattern that already worked in this workspace."
                        ),
                        "first_filter": (
                            f"Prefer repos where '{asset.focus_area or asset.title}' is visible in one module, one test path, or one adaptation boundary."
                        ),
                        "first_task": (
                            f"Pick one source that clearly exhibits '{asset.summary or asset.title}', then extract the first training slice around that pattern."
                        ),
                        "caution": "Do not pick a repo whose setup cost is larger than the first exercise loop.",
                        "source_kind": "training_repo",
                        "tags": ["teaching-asset", *asset.tags[:2]],
                    }
                    for asset in relevant_assets
                    if (asset.summary or asset.title).strip()
                ]
            )
            if memory_snapshot is not None and memory_snapshot.workspace_understanding is not None:
                understanding = memory_snapshot.workspace_understanding
                entry_point = understanding.entry_points[0] if understanding.entry_points else ""
                training_lane = understanding.training_opportunities[0] if understanding.training_opportunities else ""
                feature_lane = understanding.feature_lanes[0] if understanding.feature_lanes else ""
                understanding_snippet = (
                    training_lane
                    or feature_lane
                    or understanding.repo_summary
                    or understanding.resource_brief
                ).strip()
                if understanding_snippet:
                    grounded_reference_payload.append(
                        {
                            "source": f"workspace-understanding://{entry_point or 'current-workspace'}",
                            "snippet": understanding_snippet,
                            "trust_score": 0.64,
                            "created_at": understanding.updated_at,
                            "focus_area": decision.focus_area or training_lane or feature_lane or "workspace understanding",
                            "quality_flags": ["workspace_grounded"],
                            "title": "Current workspace training lane",
                            "repo_hint": (
                                f"Choose an outside source that reinforces the current workspace lane around {entry_point or training_lane or feature_lane or 'the current boundary'}."
                            ),
                            "fit_reason": (
                                "This keeps project sourcing aligned with the actual module boundary and training opportunity already detected in the current workspace."
                            ),
                            "training_value": (
                                "Good for selecting an outside project that mirrors the same engineering move before you return to the live repo."
                            ),
                            "first_filter": (
                                "Prefer sources where one boundary matches the current workspace entry point and can be verified with one cheap loop."
                            ),
                            "first_task": (
                                f"Map {entry_point or 'the current entry point'} to one similar boundary in the outside source, then name the first thin exercise."
                            ),
                            "caution": "Do not choose a source whose structure is so different that the transfer becomes abstract.",
                            "source_kind": "reference_repo",
                            "tags": ["workspace-grounding", "entry-point"],
                        }
                    )
            artifacts.project_sources = self._project_source_scout.suggest_sources(
                request=request,
                focus_area=decision.focus_area,
                profile=profile,
                memory_snapshot=memory_snapshot,
                external_references=grounded_reference_payload,
            )
        elif effective_mode == "principle_explanation":
            artifacts.principle_note = self._principle_explainer.explain(
                request=request,
                learner_state=learner_state,
                decision=decision,
                profile=profile,
                memory_snapshot=memory_snapshot,
                selected_assets=selected_assets,
            )
        elif effective_mode == "concept_teaching":
            artifacts.principle_note = self._principle_explainer.explain(
                request=request,
                learner_state=learner_state,
                decision=decision,
                profile=profile,
                memory_snapshot=memory_snapshot,
                selected_assets=selected_assets,
            )
        elif decision.mode == "onboarding":
            artifacts.selected_teaching_assets = list(selected_assets)
        if (
            artifacts.implementation_guide is None
            and decision.mode == "direct_rescue"
            and not is_casual_greeting_or_smalltalk(request.message)
            and not (
                is_exploratory_or_research_query(request.message)
                and learner_state.frustration_level < 0.65
                and request.current_file is None
            )
        ):
            artifacts.implementation_guide = self._implementation_coach.build_guide(
                request=request,
                learner_state=learner_state,
                decision=decision,
                profile=profile,
                memory_snapshot=memory_snapshot,
            )
        if artifacts.adaptation_guide is None and decision.scenario == "project_adaptation":
            artifacts.adaptation_guide = self._project_adaptation_coach.build_guide(
                request=request,
                learner_state=learner_state,
                decision=decision,
                profile=profile,
                memory_snapshot=memory_snapshot,
            )
        if decision.should_generate_exercise:
            artifacts.exercise_prompt = self._build_exercise_prompt(
                request=request,
                learner_state=learner_state,
                decision=decision,
                implementation_guide=artifacts.implementation_guide,
                project_ideas=artifacts.project_ideas,
                adaptation_guide=artifacts.adaptation_guide,
                principle_note=artifacts.principle_note,
                memory_snapshot=memory_snapshot,
                selected_assets=selected_assets,
            )
        if memory_snapshot and memory_snapshot.workspace_understanding:
            self._apply_workspace_understanding(
                artifacts=artifacts,
                request=request,
                understanding=memory_snapshot.workspace_understanding,
            )
        return artifacts

    def _grounded_reference_payload(
        self,
        external_references: list[dict[str, object]] | None,
        *,
        fallback_focus_area: str,
    ) -> list[dict[str, object]]:
        if not isinstance(external_references, list):
            return []
        payload: list[dict[str, object]] = []
        for item in external_references[:4]:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "") or "").strip()
            snippet = str(item.get("snippet", "") or "").strip()
            if not source or not snippet:
                continue
            focus_area = str(item.get("focus_area", "") or fallback_focus_area or "external reference").strip()
            raw_quality_flags = item.get("quality_flags")
            quality_flags = (
                [str(flag).strip() for flag in raw_quality_flags if str(flag).strip()]
                if isinstance(raw_quality_flags, list)
                else []
            )
            raw_tags = item.get("tags")
            tags = (
                [str(tag).strip() for tag in raw_tags if str(tag).strip()]
                if isinstance(raw_tags, list)
                else []
            )
            raw_trust_score = item.get("trust_score", 0.0)
            trust_score = (
                float(raw_trust_score or 0.0)
                if isinstance(raw_trust_score, (int, float, str))
                else 0.0
            )
            raw_commercial_reuse_reason_codes = item.get("commercial_reuse_reason_codes")
            commercial_reuse_reason_codes = (
                list(raw_commercial_reuse_reason_codes)
                if isinstance(raw_commercial_reuse_reason_codes, list)
                else []
            )
            payload.append(
                {
                    "source": source,
                    "snippet": snippet,
                    "trust_score": trust_score,
                    "fetched_at": item.get("fetched_at") or item.get("created_at") or "",
                    "focus_area": focus_area,
                    "quality_flags": quality_flags,
                    "source_governance": item.get("source_governance"),
                    "commercial_reuse_status": str(
                        item.get("commercial_reuse_status", "") or ""
                    ).strip(),
                    "commercial_reuse_reason_codes": commercial_reuse_reason_codes,
                    "title": str(item.get("title", "") or f"Grounded source for {focus_area}").strip(),
                    "repo_hint": str(
                        item.get("repo_hint", "")
                        or f"Start from {source} and turn the grounded snippet into one narrow training lane around {focus_area}."
                    ).strip(),
                    "fit_reason": str(
                        item.get("fit_reason", "")
                        or item.get("why_it_matters", "")
                        or "This source is already grounded in the trainer context, so it can drive a concrete project choice instead of a generic search."
                    ).strip(),
                    "training_value": str(
                        item.get("training_value", "")
                        or f"Good for turning material about {focus_area} into one scoped implementation or explanation exercise."
                    ).strip(),
                    "first_filter": str(
                        item.get("first_filter", "")
                        or "Prefer one behavior, one module boundary, and one cheap verification step."
                    ).strip(),
                    "first_task": str(
                        item.get("first_task", "")
                        or (
                            f"Read the grounded snippet '{snippet}', then extract the first tiny coding move for {focus_area} before widening scope."
                        )
                    ).strip(),
                    "caution": str(
                        item.get("caution", "")
                        or "Do not widen into a full rewrite before the first grounded slice is verified."
                    ).strip(),
                    "source_kind": str(item.get("source_kind", "") or "").strip(),
                    "tags": list(dict.fromkeys(["grounded-source", "external-reference", *tags]))[:6],
                }
            )
        return payload
