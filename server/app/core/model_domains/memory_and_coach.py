from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ..image_attachments import (
    MAX_IMAGE_BASE64_LENGTH,
    MAX_IMAGE_COUNT,
    MAX_TOTAL_IMAGE_BYTES,
    validate_image_payload,
)
from .foundations_and_provider import (
    CoachActionType,
    CoachArtifactKind,
    CoachMemoryScope,
    CoachRequestAnswerMode,
    CoachScenario,
    FolderRole,
    GlobalMemory,
    GlobalPlan,
    GlobalPlanProjectLink,
    LearnerSignal,
    LearningPlan,
    LibraryAssetCatalogSnapshot,
    MemoryShareCategory,
    ProjectTypeGuess,
    ProviderConfig,
    ResourceRecord,
    ResponseLanguage,
    ReviewCadence,
    ReviewReminderMode,
    SubPlan,
    TeachingMode,
    ToneName,
    UserProfile,
    VerbosityBias,
    WorkingSetMode,
    WorkspaceSubjectFamily,
    utc_now_iso,
)
from .resources_and_training import (
    ActiveCardSelectionResult,
    DependencyMasterySnapshot,
    DependencySkillMapHistoryEntry,
    DependencySkillMapSnapshot,
    EvaluationReport,
    EvidenceQueueSnapshot,
    FlashcardAttempt,
    FlashDeckSnapshot,
    PlanChangeCandidate,
    ReviewQueueAction,
    ReviewQueueItem,
    TaskSpec,
    TeachingKnowledgeAsset,
    TrainingCardCandidateSnapshot,
    TrainingReliabilityRequestFields,
)


class ReviewArtifactSnapshot(BaseModel):
    id: str
    title: str = ""
    focus_area: str = ""
    source: str = ""
    status: str = "active"
    summary: str = ""
    root_cause: str = ""
    guardrail: str = ""
    next_self_implementation_rule: str = ""
    recommended_recovery_mode: str = ""
    recommended_actions: list[str] = Field(default_factory=list)
    verified_result: str = ""
    blocker: str = ""
    blocked_reason: str = ""
    partial_progress: str = ""
    last_action: str = "reviewed"
    version: int = 1
    updated_at: str = Field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewArtifactHistoryEntry(BaseModel):
    entry_id: str
    review_artifact_id: str
    action: str
    version: int
    note: str = ""
    before_snapshot: dict[str, Any] = Field(default_factory=dict)
    after_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class ScenarioLab(BaseModel):
    id: str
    title: str = ""
    focus_area: str = ""
    status: str = "ready"
    summary: str = ""
    success_signal: str = ""
    review_outcome: str = ""
    learner_deliverables: list[str] = Field(default_factory=list)
    verification_steps: list[str] = Field(default_factory=list)
    migrate_back_guidance: list[str] = Field(default_factory=list)
    dependency_keys: list[str] = Field(default_factory=list)
    related_apis: list[str] = Field(default_factory=list)
    minimum_environment: list[str] = Field(default_factory=list)
    last_action: str = "created"
    version: int = 1
    updated_at: str = Field(default_factory=utc_now_iso)


class ScenarioLabHistoryEntry(BaseModel):
    entry_id: str
    scenario_lab_id: str
    action: str
    version: int
    note: str = ""
    before_snapshot: dict[str, Any] = Field(default_factory=dict)
    after_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class TheoryDrillQuestion(BaseModel):
    id: str
    prompt: str
    choices: list[str] = Field(default_factory=list)
    answer: str = ""
    explanation: str = ""
    dependency_key: str = ""
    dependency_layer: str = ""
    knowledge_type: str = ""
    question_style: str = ""


class TheoryDrillSnapshot(BaseModel):
    id: str
    title: str = ""
    focus_area: str = ""
    status: str = "ready"
    summary: str = ""
    success_signal: str = ""
    return_with: str = ""
    questions: list[TheoryDrillQuestion] = Field(default_factory=list)
    dependency_keys: list[str] = Field(default_factory=list)
    last_action: str = "created"
    version: int = 1
    updated_at: str = Field(default_factory=utc_now_iso)


class TheoryDrillHistoryEntry(BaseModel):
    entry_id: str
    theory_drill_id: str
    action: str
    version: int
    note: str = ""
    before_snapshot: dict[str, Any] = Field(default_factory=dict)
    after_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class FlashcardAnswerRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workspace_id: str
    card_id: str
    learner_answer: str = ""
    selected_option_index: int | None = None
    selected_option_indices: list[int] = Field(
        default_factory=list,
        alias="selectedOptionIndices",
    )
    fill_blank_answers: dict[str, str] = Field(
        default_factory=dict,
        alias="fillBlankAnswers",
    )
    sort_order: list[int] = Field(default_factory=list, alias="sortOrder")


class TheoryDrillAnswerRequest(BaseModel):
    workspace_id: str
    theory_drill_id: str
    question_id: str
    learner_answer: str = ""
    selected_option_index: int | None = None


class TrainingReliabilityRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(default="", alias="requestId")
    idempotency_key: str = Field(default="", alias="idempotencyKey")
    command_id: str = Field(default="", alias="commandId")
    card_id: str = Field(default="", alias="cardId")
    handoff_id: str = Field(default="", alias="handoffId")
    phase: Literal[
        "intent",
        "pending",
        "executing",
        "succeeded",
        "failed",
        "acked",
        "cancelled",
    ] = "intent"
    revision: int = 1
    snapshot_revision: int = Field(default=0, alias="snapshotRevision")
    created_at: str = Field(default="", alias="createdAt")
    updated_at: str = Field(default="", alias="updatedAt")
    acked_at: str = Field(default="", alias="ackedAt")
    timeout_at: str = Field(default="", alias="timeoutAt")
    cancel_requested: bool = Field(default=False, alias="cancelRequested")
    outcome: Literal["success", "failure", "cancelled", "timeout", ""] = ""
    error: str = ""
    recoverable: bool = False
    recovery_action: str = Field(default="", alias="recoveryAction")
    learning_phase: str = Field(default="", alias="learningPhase")


class TrainingReliabilityControlRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workspace_id: str
    request_id: str = Field(default="", alias="requestId")
    action: Literal["cancel", "recover", "expire"]
    card_id: str = Field(default="", alias="cardId")
    command_id: str = Field(default="", alias="commandId")
    idempotency_key: str = Field(default="", alias="idempotencyKey")
    revision: int = 0
    timeout_ms: int = Field(default=30_000, alias="timeoutMs")


class PracticeReturnRequest(TrainingReliabilityRequestFields):
    workspace_id: str
    card_id: str = ""
    passed: bool = False
    summary: str = ""
    next_step: str = ""
    focus_area: str = ""
    failed_checks: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    evidence_source: str = "learner_return"


class TrainingHandoffReflectionRequest(TrainingReliabilityRequestFields):
    workspace_id: str
    card_id: str
    handoff_id: str = ""
    reflection: str = Field(min_length=1, max_length=4000)


class TrainingHandoffReturnRequest(TrainingReliabilityRequestFields):
    workspace_id: str
    card_id: str
    handoff_id: str = ""


class TrainingHandoffActionResponse(BaseModel):
    ok: bool = True
    workspace: dict[str, Any] = Field(default_factory=dict)


class ReviewQueueActionRequest(BaseModel):
    workspace_id: str
    concept: str
    action: Literal["accept", "snooze", "reset", "skip", "done"]
    scope: str = "single"
    focus_area: str = ""
    task_hint: str = ""
    note: str = ""
    batch_limit: int = 4


class ReviewArtifactActionRequest(BaseModel):
    workspace_id: str
    review_artifact_id: str
    action: str
    note: str = ""
    edit_patch: dict[str, Any] = Field(default_factory=dict)


class RestoreHistoryRequest(BaseModel):
    workspace_id: str
    history_entry_id: str
    history_version: int
    note: str = ""


class ScenarioLabActionRequest(BaseModel):
    workspace_id: str
    scenario_lab_id: str
    action: str
    note: str = ""
    review_outcome: str = ""


class ScenarioLabRestoreRequest(RestoreHistoryRequest):
    scenario_lab_id: str


class TheoryDrillActionRequest(BaseModel):
    workspace_id: str
    theory_drill_id: str
    action: str
    note: str = ""


class TheoryDrillRestoreRequest(RestoreHistoryRequest):
    theory_drill_id: str


class ReviewArtifactRestoreRequest(RestoreHistoryRequest):
    review_artifact_id: str


class DependencySkillMapActionRequest(BaseModel):
    workspace_id: str
    dependency_key: str
    action: str
    note: str = ""
    focus_item_key: str = ""
    related_api: str = ""
    scenario: str = ""


class DependencySkillMapRestoreRequest(RestoreHistoryRequest):
    dependency_key: str


class EvidenceAdoptRequest(BaseModel):
    workspace_id: str
    evidence_id: str


class EvidenceRejectRequest(BaseModel):
    workspace_id: str
    evidence_id: str
    reason: str = ""


class EvidenceDeferRequest(BaseModel):
    workspace_id: str
    evidence_id: str
    reason: str = ""


class WorkspaceResetRequest(BaseModel):
    workspace_id: str


class CoachingState(BaseModel):
    scenario: CoachScenario = "general"
    answer_mode: Literal["guided", "balanced", "direct"] = "guided"
    learner_signal: LearnerSignal = "steady"
    summary: str = ""
    next_step: str = ""
    encouragement: str = ""
    intervention_strategy: str = ""
    teaching_goal: str = ""
    resume_thread: str = ""
    decision: str = ""
    blocker: str = ""
    teaching_note: str = ""
    confidence: str = ""
    evidence: list[str] = Field(default_factory=list)
    support_strategy: str = ""
    updated_at: str = Field(default_factory=utc_now_iso)


class CoachingAdaptationProfile(BaseModel):
    challenge_level: Literal["lower", "steady", "raise"] = "steady"
    hint_depth: Literal["direct", "guided", "lighter"] = "guided"
    review_urgency: Literal["high", "normal", "low"] = "normal"
    explanation_mode: Literal["rebuild", "grounded", "transfer"] = "grounded"
    next_step_bias: Literal["shrink", "steady", "widen"] = "steady"
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    hint_count: int = 2
    explanation_depth: Literal["rebuild", "grounded", "transfer"] = "grounded"
    code_reveal: Literal["full", "scaffold", "withhold"] = "scaffold"
    practice_type: Literal["recover", "focused", "stretch"] = "focused"
    review_frequency: Literal["sooner", "normal", "later"] = "normal"
    material_recommendation: Literal["simpler", "current", "transfer"] = "current"
    next_plan_step: Literal["shrink", "hold", "widen"] = "hold"
    should_reveal_code: bool = False
    success_streak: int = 0
    failure_streak: int = 0
    pedagogy_mode: Literal["socratic", "direct", "debug_guide"] = "direct"
    transfer_scene_count: int = 0
    time_budget: Literal["tight", "normal", "ample"] = "normal"
    project_complexity: Literal["simple", "moderate", "complex"] = "moderate"
    task_urgency: Literal["low", "medium", "high"] = "medium"


class LearnerState(BaseModel):
    current_confidence: float = 0.5
    frustration_level: float = 0.0
    attempt_count_recent: int = 0
    needs_rescue: bool = False
    needs_review: bool = False
    preferred_hint_depth: Literal["small", "medium", "expanded"] = "medium"
    learner_signal: LearnerSignal = "steady"
    active_focus: str = ""
    evidence: list[str] = Field(default_factory=list)


class TeachingDecision(BaseModel):
    mode: TeachingMode = "guided"
    reason: str = ""
    primary_goal: str = ""
    lesson_shape: str = ""
    exercise_shape: str = ""
    teaching_strategy: str = ""
    closing_move: str = ""
    artifact_priority: list[str] = Field(default_factory=list)
    should_end_with_question: bool = False
    should_generate_exercise: bool = False
    should_reveal_code: bool = False
    should_produce_plan_artifact: bool = False
    should_trigger_deep_analysis: bool = False
    should_focus_on_implementation_steps: bool = True
    tone_profile: str = "steady"
    focus_area: str = ""


class AffectState(BaseModel):
    frustration_level: float = 0.0
    confidence_level: float = 0.5
    momentum_level: float = 0.5
    needs_reassurance: bool = False
    urgency_level: Literal["low", "medium", "high"] = "medium"
    recovery_signal: Literal["steady", "recovering", "fragile", "overloaded"] = "steady"


class ToneDecision(BaseModel):
    tone: ToneName = "steady"
    verbosity_bias: VerbosityBias = "medium"
    acknowledge_progress: bool = False
    avoid_overwhelm: bool = False


class ImplementationGuide(BaseModel):
    idea_summary: str = ""
    scope_boundary: str = ""
    mvp_definition: str = ""
    current_step: str = ""
    next_steps: list[str] = Field(default_factory=list)
    validation_strategy: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    codebase_entry_points: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    teaching_goal: str = ""
    success_signal: str = ""
    fallback_step: str = ""


class ProjectIdea(BaseModel):
    id: str
    title: str
    summary: str
    source_area: str = ""
    idea_kind: Literal["feature", "refactor", "test", "architecture", "developer_experience"] = "feature"
    learning_value: str = ""
    engineering_value: str = ""
    difficulty: Literal["small", "medium", "stretch"] = "small"
    suggested_scope: str = ""
    first_step: str = ""
    acceptance_signals: list[str] = Field(default_factory=list)
    why_now: str = ""


class ProjectOpportunitySignal(BaseModel):
    file_path: str = ""
    signal_type: Literal[
        "repetition",
        "missing_test",
        "diagnostic_cluster",
        "coupling_hotspot",
        "rough_edge",
        "feature_gap",
    ] = "feature_gap"
    evidence: str = ""
    confidence: float = 0.5


class ProjectAdaptationGuide(BaseModel):
    target_outcome: str = ""
    current_constraints: list[str] = Field(default_factory=list)
    affected_areas: list[str] = Field(default_factory=list)
    preserve_areas: list[str] = Field(default_factory=list)
    first_migration_step: str = ""
    migration_sequence: list[str] = Field(default_factory=list)
    validation_checkpoints: list[str] = Field(default_factory=list)
    rollback_notes: list[str] = Field(default_factory=list)


class ProjectSourceSuggestion(BaseModel):
    title: str
    source_kind: Literal["reference_repo", "reference_impl", "training_repo"] = "reference_repo"
    repo_hint: str = ""
    fit_reason: str = ""
    training_value: str = ""
    first_filter: str = ""
    first_task: str = ""
    caution: str = ""
    tags: list[str] = Field(default_factory=list)
    source_url: str = ""
    retrieved_at: str = ""
    trust_score: float = 0.0
    quality_flags: list[str] = Field(default_factory=list)


class PrincipleNotes(BaseModel):
    current_principle: str = ""
    why_it_matters: str = ""
    common_mistake: str = ""
    apply_now: str = ""
    transfer_targets: list[str] = Field(default_factory=list)
    concrete_anchor: str = ""
    transferable_lesson: str = ""
    related_checks: list[str] = Field(default_factory=list)
    source_asset_title: str = ""


class ActiveThreadSnapshot(BaseModel):
    scenario: str = ""
    focus_area: str = ""
    summary: str = ""
    next_step: str = ""
    blocker: str = ""
    verified_result: str = ""
    decision: str = ""
    teaching_note: str = ""
    confidence: str = ""
    evidence: list[str] = Field(default_factory=list)
    updated_at: str = ""


class FirstLookSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    folder_role: FolderRole = "mixed_uncertain"
    project_type_guess: ProjectTypeGuess = "unknown"
    subject_family: WorkspaceSubjectFamily = "code"
    confidence: float = 0.0
    why_this_guess: str = ""
    entry_points: list[str] = Field(default_factory=list)
    directory_anchors: list[str] = Field(default_factory=list)
    core_modules_or_materials: list[str] = Field(default_factory=list)
    risk_zones: list[str] = Field(default_factory=list)
    training_opportunities: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    recommended_next_step: str = ""
    classification_method: Literal["heuristic", "llm_enhanced"] = "heuristic"
    classified_at: str = Field(default_factory=utc_now_iso)

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, value: Any) -> float:
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, normalized))


class WorkspaceUnderstandingSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    repo_summary: str = ""
    entry_points: list[str] = Field(default_factory=list)
    feature_lanes: list[str] = Field(default_factory=list)
    risk_zones: list[str] = Field(default_factory=list)
    training_opportunities: list[str] = Field(default_factory=list)
    resource_brief: str = ""
    first_look_summary: FirstLookSummary | None = Field(default=None, alias="firstLookSummary")
    updated_at: str = Field(default_factory=utc_now_iso)


class MemoryShareGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_workspace_id: str
    target_workspace_id: str
    categories: list[MemoryShareCategory]
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    @field_validator("source_workspace_id", "target_workspace_id")
    @classmethod
    def require_workspace_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("workspace_id is required")
        return normalized

    @field_validator("categories")
    @classmethod
    def normalize_categories(cls, value: list[MemoryShareCategory]) -> list[MemoryShareCategory]:
        normalized = list(dict.fromkeys(value))
        if not normalized:
            raise ValueError("at least one memory share category is required")
        return normalized

    @model_validator(mode="after")
    def require_distinct_workspaces(self) -> "MemoryShareGrant":
        if self.source_workspace_id == self.target_workspace_id:
            raise ValueError("memory share source and target must differ")
        return self


class LearningActivityEntry(BaseModel):
    event_id: str
    event_type: str
    occurred_at: str
    title: str = ""
    card_id: str = ""
    resource_id: str = ""
    next_due: str = ""
    trust_level: str = ""
    result: str = ""


class MemorySnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    profile: UserProfile | None = None
    learning_activity: list[LearningActivityEntry] = Field(default_factory=list)
    global_memory: GlobalMemory | None = Field(default=None, alias="globalMemory")
    active_plan: LearningPlan | None = None
    subplans: list[SubPlan] = Field(default_factory=list)
    resources: list[ResourceRecord] = Field(default_factory=list)
    asset_catalog: LibraryAssetCatalogSnapshot = Field(
        default_factory=LibraryAssetCatalogSnapshot,
        alias="assetCatalog",
    )
    teaching_assets: list[TeachingKnowledgeAsset] = Field(default_factory=list)
    memory_share_grants: list[MemoryShareGrant] = Field(default_factory=list)
    teaching_knowledge_catalog: dict[str, Any] = Field(default_factory=dict)
    coaching_adaptation: CoachingAdaptationProfile | None = None
    teaching_strategy_effectiveness: list[dict[str, Any]] = Field(default_factory=list)
    learning_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    reflections: list[str] = Field(default_factory=list)
    recent_summary: str = ""
    current_focus: str = ""
    coach_anchor: str = ""
    top_weakness: str = ""
    lowest_mastery_concepts: list[str] = Field(default_factory=list)
    recent_wins: list[str] = Field(default_factory=list)
    review_rhythm: str = ""
    due_reviews: list[ReviewQueueItem] = Field(default_factory=list)
    due_review_count: int = 0
    pace_signal: str = ""
    teaching_observations: list[str] = Field(default_factory=list)
    user_feedback: list[dict[str, Any]] = Field(default_factory=list, alias="userFeedback")
    workspace: dict[str, Any] = Field(default_factory=dict)
    active_thread: ActiveThreadSnapshot | None = None
    memory_evidence: list[str] = Field(default_factory=list)
    workspace_understanding: WorkspaceUnderstandingSnapshot | None = None
    dependency_mastery: list[DependencyMasterySnapshot] = Field(default_factory=list)
    dependency_skill_maps: list[DependencySkillMapSnapshot] = Field(default_factory=list)
    dependency_skill_map_history: list[DependencySkillMapHistoryEntry] = Field(default_factory=list)
    flash_deck: FlashDeckSnapshot | None = None
    recent_flash_attempts: list[FlashcardAttempt] = Field(default_factory=list)
    theory_drill: TheoryDrillSnapshot | None = None
    theory_drill_history: list[TheoryDrillHistoryEntry] = Field(default_factory=list)
    scenario_lab: ScenarioLab | None = None
    scenario_lab_history: list[ScenarioLabHistoryEntry] = Field(default_factory=list)
    review_queue_actions: list[ReviewQueueAction] = Field(default_factory=list)
    review_artifact: ReviewArtifactSnapshot | None = None
    review_artifact_history: list[ReviewArtifactHistoryEntry] = Field(default_factory=list)
    training_card_candidates: list[TrainingCardCandidateSnapshot] = Field(default_factory=list)
    active_training_card_routing: ActiveCardSelectionResult | None = None
    training_event_ledger: list[dict[str, Any]] = Field(default_factory=list)
    evidence_queue: EvidenceQueueSnapshot | None = None
    plan_change_candidates: list[PlanChangeCandidate] = Field(default_factory=list, alias="planChangeCandidates")


class ChatMessage(BaseModel):
    id: str = Field(default="message")
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None

    @model_validator(mode="after")
    def sync_created_at(self) -> "ChatMessage":
        if not self.created_at:
            self.created_at = self.timestamp.isoformat()
        return self


class StageMaterialItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    plan_stage_id: str = Field(alias="planStageId")
    kind: str
    title: str
    summary: str
    content: str
    focus_area: str = Field(default="", alias="focusArea")
    created_at: str = Field(default="", alias="createdAt")
    generation_source: Literal["model", "template"] = Field(alias="generationSource")


class GoalActivity(BaseModel):
    """One real learning activity attributed to a goal.

    Only evidence-bearing surfaces (evaluation, training attempt, host
    attestation, review) create activities; ordinary chat never does.
    """

    model_config = ConfigDict(populate_by_name=True)

    activity_id: str = Field(alias="activityId")
    kind: Literal["evaluation", "training_attempt", "verification", "review"] = "evaluation"
    summary: str = ""
    result: Literal["passed", "failed", "pending", "completed", "unknown"] = "unknown"
    concept: str = ""
    occurred_at: str = Field(default_factory=utc_now_iso, alias="occurredAt")
    evidence_refs: list[str] = Field(default_factory=list, alias="evidenceRefs")
    event_key: str = Field(default="", alias="eventKey")


class GoalSession(BaseModel):
    """Server-owned continuous capability goal.

    ``GoalBar`` renders and operates this record but never owns its truth.
    A goal is not mastery: completing or pausing it only ends the focus, it
    never promotes competency or rewrites history.
    """

    model_config = ConfigDict(populate_by_name=True)

    goal_id: str = Field(alias="goalId")
    workspace_id: str = Field(default="", alias="workspaceId")
    session_id: str | None = Field(default=None, alias="sessionId")
    title: str
    concept: str = ""
    capability: str = ""
    plan_id: str | None = Field(default=None, alias="planId")
    stage_id: str | None = Field(default=None, alias="stageId")
    status: Literal["active", "paused", "completed"] = "active"
    source: Literal["user_explicit", "coach_detected", "plan_stage"] = "user_explicit"
    current_position: str = Field(default="", alias="currentPosition")
    latest_activity: GoalActivity | None = Field(default=None, alias="latestActivity")
    activities: list[GoalActivity] = Field(default_factory=list)
    activity_count: int = Field(default=0, alias="activityCount")
    evidence_count: int = Field(default=0, alias="evidenceCount")
    started_at: str = Field(default_factory=utc_now_iso, alias="startedAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")
    last_activity_at: str | None = Field(default=None, alias="lastActivityAt")
    completed_at: str | None = Field(default=None, alias="completedAt")


class WorkbenchSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    context_id: str = Field(default="", alias="contextId")
    sidecar_status: Literal["unknown", "starting", "ready", "error"] = "ready"
    active_panel: Literal["chat", "plan", "task", "evaluate"] = "chat"
    snapshot_revision: int = Field(default=0, alias="snapshotRevision")
    messages: list[ChatMessage] = Field(default_factory=list)
    stage_materials: dict[str, list[StageMaterialItem]] = Field(default_factory=dict, alias="stageMaterials")
    session_history_restored: bool = Field(default=False, alias="sessionHistoryRestored")
    profile: UserProfile | None = None
    plan: LearningPlan | None = None
    goal: GoalSession | None = None
    global_plan: GlobalPlan | None = None
    project_plan_link: GlobalPlanProjectLink | None = None
    current_task: TaskSpec | None = None
    evaluation: EvaluationReport | None = None
    memory: MemorySnapshot = Field(default_factory=MemorySnapshot)
    provider: ProviderConfig | None = None
    coaching_state: CoachingState | None = None
    learner_state: LearnerState | None = None
    teaching_decision: TeachingDecision | None = None
    affect_state: AffectState | None = None
    tone_decision: ToneDecision | None = None
    implementation_guide: ImplementationGuide | None = None
    project_ideas: list[ProjectIdea] = Field(default_factory=list)
    project_adaptation_guide: ProjectAdaptationGuide | None = None
    project_sources: list[ProjectSourceSuggestion] = Field(default_factory=list)
    principle_notes: PrincipleNotes | None = None
    selected_teaching_assets: list[TeachingKnowledgeAsset] = Field(default_factory=list)
    exercise_prompt: dict[str, Any] | None = None
    review_queue_summary: str = ""
    next_review_due: str | None = None
    plan_runtime_status: dict[str, Any] | None = None
    coach_orientation: dict[str, Any] | None = Field(default=None, alias="coachOrientation")
    workspace_projection: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("workspace_projection", "workspaceProjection"),
    )
    suggested_actions: list["SuggestedAction"] = Field(default_factory=list, alias="suggestedActions")


class SessionStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    profile: UserProfile | None = None
    workspace_id: str
    workspace_name: str
    workspace_path: str | None = None
    root_id: str | None = Field(default=None, alias="rootId")
    root_path: str | None = Field(default=None, alias="rootPath")
    remote_name: str | None = Field(default=None, alias="remoteName")
    workspace_trusted: bool | None = Field(default=None, alias="workspaceTrusted")

    @field_validator("workspace_id")
    @classmethod
    def normalize_workspace_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("workspace_id must be a non-empty local identifier")
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise ValueError("workspace_id must not contain control characters")

        path_segments = [segment for segment in normalized.replace("\\", "/").split("/") if segment]
        if any(segment in {".", ".."} for segment in path_segments):
            raise ValueError("workspace_id must not contain path traversal segments")

        # Workspace paths are retained as read-compatible aliases by the host
        # during project admission and rehydration. Relative path-shaped IDs
        # are rejected while absolute aliases remain valid.
        has_separator = "/" in normalized or "\\" in normalized
        is_absolute_path = normalized.startswith(("/", "\\")) or (
            len(normalized) >= 3
            and normalized[1] == ":"
            and normalized[2] in {"/", "\\"}
        )
        if has_separator and not is_absolute_path:
            raise ValueError("workspace_id must be an opaque identifier or absolute workspace path")
        return normalized


class CurrentFilePayload(BaseModel):
    path: str
    language_id: str
    content: str
    content_excerpt: str | None = None
    content_line_span: str | None = None
    content_strategy: str | None = None
    selection_text: str | None = None
    selection_range: str | None = None
    diagnostics: list[str] = Field(default_factory=list)
    recent_files: list[str] = Field(default_factory=list)
    recent_edited_files: list[str] = Field(default_factory=list)
    related_files: list[dict[str, str]] = Field(default_factory=list)


class MessageAttachment(BaseModel):
    """A multimodal attachment carried alongside a user coaching message.

    `kind="image"` items are forwarded to vision-capable models as content
    parts; the agent loop also surfaces them as `tool_result`/`reasoning`
    grounding so non-vision models still see *that* an image was attached.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = ""
    kind: Literal["image", "file"] = "image"
    mime_type: str = Field(default="image/png", alias="mimeType")
    data_base64: str | None = Field(default=None, alias="dataBase64", max_length=MAX_IMAGE_BASE64_LENGTH)
    source_path: str | None = Field(default=None, alias="sourcePath")
    name: str | None = None
    caption: str | None = None
    byte_size: int | None = Field(default=None, alias="byteSize", ge=0)

    @model_validator(mode="after")
    def validate_image_transport(self) -> MessageAttachment:
        if self.kind == "image" and self.data_base64 is not None:
            self.byte_size = validate_image_payload(self.data_base64, self.mime_type, self.byte_size)
        return self


class WorkspaceMemoryToggles(BaseModel):
    decisions: bool = True
    patterns: bool = True
    resources: bool = True


class CustomSkill(BaseModel):
    """A user-authored `$trigger` prompt persisted with the workspace coach defaults.

    Custom skills are created, imported, and removed entirely through the
    coach-settings channel; the agent loop never executes them directly — the
    webview expands a skill into a normal coach prompt before sending.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = Field(default="", max_length=120)
    trigger: str = Field(default="", max_length=64)
    title: str = Field(default="", max_length=200)
    detail: str = Field(default="", max_length=500)
    prompt: str = Field(default="", max_length=4000)
    keywords: list[str] = Field(default_factory=list, max_length=16)
    created_at: str | None = Field(default=None, alias="createdAt")


class CoachDefaults(BaseModel):
    # The extension sends camelCase keys (memoryScope, workspaceMemoryToggles,
    # customSkills) while stored snapshots are snake_case; populate_by_name keeps
    # both representations valid.
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    memory_scope: CoachMemoryScope = Field(default="project", alias="memoryScope")
    working_set_mode: WorkingSetMode = Field(default="balanced", alias="workingSetMode")
    review_cadence: ReviewCadence = Field(default="steady", alias="reviewCadence")
    review_reminder_mode: ReviewReminderMode = Field(default="due", alias="reviewReminderMode")
    workspace_memory_toggles: WorkspaceMemoryToggles = Field(
        default_factory=WorkspaceMemoryToggles, alias="workspaceMemoryToggles"
    )
    custom_skills: list[CustomSkill] = Field(default_factory=list, alias="customSkills", max_length=24)


class ResourceComposerIntent(BaseModel):
    """Advisory Resources-composer context with no path or write authority."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    mode: Literal["locate", "analyze", "download", "organize", "cards"]
    resource_ids: list[str] = Field(default_factory=list, alias="resourceIds", max_length=12)

    @field_validator("resource_ids")
    @classmethod
    def normalize_opaque_resource_ids(cls, value: list[str]) -> list[str]:
        normalized_ids: list[str] = []
        for raw_id in value:
            resource_id = raw_id.strip()
            if (
                not resource_id
                or len(resource_id) > 160
                or "\x00" in resource_id
                or "/" in resource_id
                or "\\" in resource_id
                or ".." in resource_id
            ):
                raise ValueError("resource composer IDs must be opaque resource identifiers")
            if resource_id not in normalized_ids:
                normalized_ids.append(resource_id)
        return normalized_ids


class SessionMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    session_id: str | None = None
    workspace_id: str | None = None
    message: str
    # The client reports whether its intent came from an explicit user action
    # (slash command, skill button, review/task control) or from natural
    # language inference. Only an explicit source may start formal flows.
    intent_source: Literal["explicit", "inferred", "none"] = Field(
        default="explicit", alias="intentSource"
    )
    # Host-recorded live test evidence. The streaming route adopts it for this
    # exact provider when a project admission restarted the sidecar and the
    # in-process capability cache is empty. Snake case and the camelCase alias
    # both parse (the host sends both).
    last_test_result: dict[str, Any] | None = Field(default=None, alias="lastTestResult")
    active_view: Literal[
        "coach",
        "plan",
        "resources",
        "training",
        "progress",
        "settings",
    ] | None = Field(
        default=None,
        alias="activeView",
    )
    resource_ids: list[str] = Field(default_factory=list)
    resource_composer_intent: ResourceComposerIntent | None = Field(
        default=None,
        alias="resourceComposerIntent",
    )
    current_file: CurrentFilePayload | None = None
    workspace_file_snapshot: dict[str, Any] | None = Field(
        default=None,
        alias="workspaceFileSnapshot",
    )
    response_language: str | None = Field(default=None, alias="responseLanguage")
    answer_mode: CoachRequestAnswerMode | None = None
    # Goal mode: one small learning goal, learner does the work. The flag only
    # changes the coaching contract; explicit plan/card actions stay separate.
    goal_mode: bool = Field(default=False, alias="goalMode")
    # The title shown in GoalBar. Persisted as the server-owned GoalSession;
    # the webview no longer owns goal truth across restarts.
    goal_text: str | None = Field(default=None, alias="goalText", max_length=240)
    teaching_style: str | None = None
    coach_defaults: CoachDefaults | None = None
    attachments: list[MessageAttachment] = Field(default_factory=list, max_length=MAX_IMAGE_COUNT)
    use_agent_loop: bool | None = Field(default=None, alias="useAgentLoop")
    formal_plan_mutation: bool = Field(default=False, alias="formalPlanMutation")
    # Host/user attestation only — never trust model tool-arg self-attestation.
    resource_organization_confirmed: bool = Field(
        default=False,
        alias="resourceOrganizationConfirmed",
    )
    request_id: str | None = Field(default=None, alias="requestId", max_length=128)
    plan_runtime_recovery: dict[str, Any] | None = Field(
        default=None,
        alias="planRuntimeRecovery",
    )

    @model_validator(mode="after")
    def validate_attachment_budget(self) -> SessionMessageRequest:
        if sum(item.byte_size or 0 for item in self.attachments if item.kind == "image") > MAX_TOTAL_IMAGE_BYTES:
            raise ValueError("attachment_image_total_size_exceeded")
        return self


class GoalControlRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    session_id: str | None = None
    workspace_id: str | None = None
    action: Literal["start", "pause", "resume", "complete"]
    title: str | None = Field(default=None, max_length=240)
    goal_id: str | None = Field(default=None, alias="goalId")


class CoachSettingsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    session_id: str | None = Field(default=None, alias="sessionId")
    workspace_id: str | None = Field(default=None, alias="workspaceId")
    response_language: ResponseLanguage | None = Field(default=None, alias="responseLanguage")
    answer_mode: CoachRequestAnswerMode | None = Field(default=None, alias="answerMode")
    teaching_style: str | None = Field(default=None, alias="teachingStyle")
    coach_defaults: CoachDefaults | None = Field(default=None, alias="coachDefaults")
    follow_current_file: bool | None = Field(default=None, alias="followCurrentFile")
    context_detail: Literal["focused", "balanced", "full"] | None = Field(
        default=None,
        alias="contextDetail",
    )
    include_current_file: bool | None = Field(default=None, alias="includeCurrentFile")
    include_selection: bool | None = Field(default=None, alias="includeSelection")
    include_diagnostics: bool | None = Field(default=None, alias="includeDiagnostics")
    include_related_files: bool | None = Field(default=None, alias="includeRelatedFiles")
    resource_search_mode: str | None = Field(default=None, alias="resourceSearchMode")


class GlobalMemoryUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    session_id: str | None = Field(default=None, alias="sessionId")
    workspace_id: str | None = Field(default=None, alias="workspaceId")
    preferences: dict[str, str] | None = Field(default=None, alias="preferences")
    long_term_goals: list[str] | None = Field(default=None, alias="longTermGoals")


class MemoryShareGrantUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    workspace_id: str | None = None
    source_workspace_id: str
    categories: list[MemoryShareCategory]

    @field_validator("source_workspace_id")
    @classmethod
    def require_source_workspace_id(cls, value: str) -> str:
        return MemoryShareGrant.require_workspace_id(value)

    @field_validator("categories")
    @classmethod
    def require_categories(cls, value: list[MemoryShareCategory]) -> list[MemoryShareCategory]:
        return MemoryShareGrant.normalize_categories(value)


class TransferPromotionScopeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    session_id: str | None = Field(default=None, alias="sessionId")
    workspace_id: str | None = Field(default=None, alias="workspaceId")
    workspace_ids: list[str] = Field(default_factory=list, alias="workspaceIds")


class MemoryShareGrantRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    workspace_id: str | None = None
    source_workspace_id: str

    @field_validator("source_workspace_id")
    @classmethod
    def require_source_workspace_id(cls, value: str) -> str:
        return MemoryShareGrant.require_workspace_id(value)


class TurnRequest(SessionMessageRequest):
    intent: Literal["coach", "next_task", "review", "plan", "task", "resources"] = "coach"
    goals: list[str] = Field(default_factory=list)
    focus_area: str | None = None


class SuggestedAction(BaseModel):
    id: str
    label: str
    action: CoachActionType
    rationale: str | None = None
    artifact_kind: CoachArtifactKind | None = None
    prompt: str | None = None
    focus_area: str | None = None


class CoachArtifact(BaseModel):
    kind: CoachArtifactKind
    title: str
    summary: str = ""
    content: str | None = None
    bullets: list[str] = Field(default_factory=list)
    teaser: str | None = None
    recommended_action: CoachActionType | None = None
    rationale: str | None = None
    focus_area: str | None = None
    verification: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CoachTurnSummary(BaseModel):
    scenario: CoachScenario
    learner_signal: LearnerSignal
    summary: str
    next_step: str
    encouragement: str = ""
    teaching_mode: Literal["coach", "practice", "review", "principle", "plan"] = "coach"
    emotional_tone: Literal["steady", "supportive", "challenging"] = "steady"
    review_rhythm: str = ""
    teaching_observation: str = ""
    intervention_strategy: str = ""
    teaching_goal: str = ""
    resume_thread: str = ""
    decision: str = ""
    blocker: str = ""
    teaching_note: str = ""
    confidence: str = ""
    evidence: list[str] = Field(default_factory=list)
    support_strategy: str = ""
    decision_reason: str = ""
    tone: ToneName = "steady"
    verbosity_bias: VerbosityBias = "medium"
    active_stage: str | None = None
    active_task: str | None = None
    due_review_count: int = 0
    review_queue_summary: str = ""
    failing_checks: list[str] = Field(default_factory=list)
    artifact_kinds: list[CoachArtifactKind] = Field(default_factory=list)
    suggested_action_types: list[CoachActionType] = Field(default_factory=list)
    background_mode: Literal["embedded"] = "embedded"
    # Teaching-turn grounding downgrade: True when next_step referenced code
    # symbols that appear nowhere in the reply/code facts (see
    # app/llm/turn_grounding.py). The UI renders such a next step as a
    # suggestion needing confirmation instead of a plan-ready instruction.
    requires_confirmation: bool = False


class AgentMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    agentic: bool = True
    summary: str = ""
    next_step: str = ""
    stop_reason: str = ""
    decision: str = ""
    blocker: str = ""
    teaching_note: str = ""
    confidence: str = ""
    evidence: list[str] = Field(default_factory=list)
    resume_thread: str = ""
    fell_back: bool = False
    tool_events: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    attachments_present: bool = False
    image_attachment_count: int = 0
    attachments_delivered_to_model: bool = False
    attachments_delivery_path: str = ""
    attachments_delivery_reason: str = ""
    coach_visible_status: dict[str, Any] | None = None
    next_step_hint: dict[str, Any] | None = None
    checkpoint_id: str = ""
    recovery_available: bool = False


class SessionMessageResponse(BaseModel):
    session_id: str
    reply: ChatMessage
    snapshot: WorkbenchSnapshot
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    coach_turn: CoachTurnSummary | None = None
    agent_meta: AgentMeta | None = None
    agent: AgentMeta | None = None
