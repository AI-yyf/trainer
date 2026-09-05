from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from ..core.models import AffectState as CoreAffectState
from ..core.models import (
    CoachingAdaptationProfile,
    CurrentFilePayload,
    MemorySnapshot,
    TeachingKnowledgeAsset,
    TurnRequest,
    UserProfile,
    WorkspaceUnderstandingSnapshot,
)
from .implementation_coach import ImplementationCoachService
from .principle_explainer import PrincipleExplainerService, PrincipleNote
from .project_adaptation_coach import ProjectAdaptationCoachService, ProjectAdaptationGuide
from .project_idea_miner import ProjectIdea, ProjectIdeaMinerService
from .project_source_scout import ProjectSourceScoutService, ProjectSourceSuggestion

TeachingMode = Literal[
    "onboarding",
    "idea_implementation",
    "project_idea_mining",
    "project_adaptation",
    "planning",
    "concept_teaching",
    "engineering_challenge",
    "review_reflection",
    "project_sourcing",
    "principle_explanation",
    "guided",
    "scaffold",
    "balanced",
    "direct_rescue",
    "challenge",
    "reflection",
]


@dataclass(slots=True)
class LearnerState:
    current_confidence: float
    frustration_level: float
    attempt_count_recent: int
    needs_rescue: bool
    needs_review: bool
    preferred_hint_depth: str
    learner_signal: str
    active_focus: str
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AdaptiveCoachingBias:
    challenge_level: str = "steady"
    hint_depth: str = "guided"
    review_urgency: str = "normal"
    explanation_mode: str = "grounded"
    next_step_bias: str = "steady"
    summary: str = ""
    evidence: list[str] = field(default_factory=list)
    difficulty: str = "medium"
    hint_count: int = 2
    explanation_depth: str = "grounded"
    code_reveal: str = "scaffold"
    practice_type: str = "focused"
    review_frequency: str = "normal"
    material_recommendation: str = "current"
    should_reveal_code: bool = False
    pedagogy_mode: str = "direct"


@dataclass(slots=True)
class TeachingDecision:
    mode: TeachingMode = "guided"
    reason: str = ""
    primary_goal: str = ""
    lesson_shape: str = ""
    exercise_shape: str = ""
    teaching_strategy: str = ""
    closing_move: str = ""
    artifact_priority: list[str] = field(default_factory=list)
    should_end_with_question: bool = False
    should_generate_exercise: bool = False
    should_reveal_code: bool = False
    should_produce_plan_artifact: bool = False
    should_trigger_deep_analysis: bool = False
    should_focus_on_implementation_steps: bool = False
    tone_profile: str = "steady"
    scenario: str = "guided"
    focus_area: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ImplementationGuide:
    idea_summary: str
    scope_boundary: str
    mvp_definition: str
    current_step: str
    next_steps: list[str] = field(default_factory=list)
    validation_strategy: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    codebase_entry_points: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    teaching_goal: str = ""
    success_signal: str = ""
    fallback_step: str = ""


@dataclass(slots=True)
class PedagogyArtifacts:
    selected_teaching_assets: list[TeachingKnowledgeAsset] = field(default_factory=list)
    implementation_guide: ImplementationGuide | None = None
    project_ideas: list[ProjectIdea] = field(default_factory=list)
    adaptation_guide: ProjectAdaptationGuide | None = None
    principle_note: PrincipleNote | None = None
    project_sources: list[ProjectSourceSuggestion] = field(default_factory=list)
    exercise_prompt: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.selected_teaching_assets:
            payload["selected_teaching_assets"] = [item.model_dump() for item in self.selected_teaching_assets]
        if self.implementation_guide is not None:
            payload["implementation_guide"] = asdict(self.implementation_guide)
        if self.project_ideas:
            payload["project_ideas"] = [asdict(item) for item in self.project_ideas]
        if self.adaptation_guide is not None:
            payload["adaptation_guide"] = asdict(self.adaptation_guide)
        if self.principle_note is not None:
            payload["principle_note"] = asdict(self.principle_note)
        if self.project_sources:
            payload["project_sources"] = [asdict(item) for item in self.project_sources]
        if self.exercise_prompt is not None:
            payload["exercise_prompt"] = dict(self.exercise_prompt)
        return payload


class PedagogyService:
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
            frustration_level += 0.15
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
        needs_rescue = frustration_level >= 0.65 or request.answer_mode == "direct"

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
            evidence=reason_parts,
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
        if artifacts.implementation_guide is None and decision.mode == "direct_rescue":
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
