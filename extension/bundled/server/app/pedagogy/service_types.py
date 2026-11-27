from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from ..core.models import (
    TeachingKnowledgeAsset,
)
from .principle_explainer import PrincipleNote
from .project_adaptation_coach import ProjectAdaptationGuide
from .project_idea_miner import ProjectIdea
from .project_source_scout import ProjectSourceSuggestion

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
    depth_level: int = 1
    depth_label: str = ""
    direct_answer_override: bool = False
    offer_light_practice: bool = False
    turn_mode: str = "chat"
    turn_source: str = "unknown"
    turn_confidence: str = "unknown"
    turn_allow_question: bool = False
    turn_allow_formal_task: bool = False
    turn_allow_formal_plan: bool = False
    turn_allow_review: bool = False
    turn_may_interrupt: bool = False
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
