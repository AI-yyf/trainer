from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)

CoachRequestAnswerMode = Literal["auto", "coach-first", "guided", "balanced", "direct"]
ResponseLanguage = Literal[
    "zh-CN",
    "en-US",
    "es-ES",
    "fr-FR",
    "de-DE",
    "ja-JP",
    "ko-KR",
    "pt-BR",
]
CoachActionType = Literal["plan", "next_task", "review", "hint", "retry_review", "task"]
CoachScenario = Literal[
    "general",
    "onboarding",
    "idea_implementation",
    "project_idea",
    "project_adaptation",
    "project_sourcing",
    "principle",
    "remote_workspace",
    "debug_loop",
    "function_guidance",
    "review",
    "plan",
    "task",
    "next_task",
]
LearnerSignal = Literal["steady", "blocked", "uncertain", "curious"]
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
ToneName = Literal["steady", "encouraging", "concise_rescue", "reflective"]
VerbosityBias = Literal["short", "medium", "expanded"]
CoachArtifactKind = Literal[
    "task",
    "plan",
    "evaluation",
    "idea_implementation",
    "project_idea",
    "project_adaptation",
    "project_source",
    "principle",
    "review",
    "plan_update",
    "next_step",
]
CoachMemoryScope = Literal["project", "personal", "session"]
MemoryShareCategory = Literal["preferences", "mastery"]
WorkingSetMode = Literal["focused", "balanced", "broad"]
ReviewCadence = Literal["light", "steady", "active"]
ReviewReminderMode = Literal["due", "ahead", "digest"]
ResourceTrustState = Literal["trusted", "unknown", "stale", "untrusted"]

RESOURCE_TRAINING_BLOCKING_QUALITY_FLAGS = frozenset(
    {
        "network_disabled",
        "fetch_failed",
        "blocked_source",
        "no_content",
        "source_conflict",
    }
)


def derive_resource_trust_state(
    trust_score: float,
    freshness: str,
    quality_flags: list[str],
) -> ResourceTrustState:
    normalized_flags = {
        normalized
        for flag in quality_flags
        if (normalized := str(flag or "").strip().lower())
    }
    if RESOURCE_TRAINING_BLOCKING_QUALITY_FLAGS & normalized_flags:
        return "untrusted"
    if str(freshness or "").strip().lower() == "stale":
        return "stale"
    if trust_score >= 0.75 and not normalized_flags:
        return "trusted"
    if trust_score >= 0.45:
        return "unknown"
    return "untrusted"
LearningSignalOutcome = Literal[
    "code_landed",
    "tests_passed",
    "evaluation",
    "repeated_error",
    "concept_answered_correctly",
    "task_abandoned",
    "blocked",
]
UserFeedbackKind = Literal[
    "too_hard",
    "too_simple",
    "misunderstood",
    "resource_incorrect",
    "plan_mismatch",
    "card_unrealistic",
]
TeachingAssetKind = Literal[
    "concept_card",
    "implementation_pattern",
    "common_pitfall",
    "exercise_seed",
    "explanation_recipe",
    "study_guide",
    "cheat_sheet",
    "exercise_set",
    "code_examples",
]
TeachingAssetScope = Literal["general", "personal", "project"]
TeachingAssetOrigin = Literal[
    "resource",
    "workspace_understanding",
    "reflection",
    "learning_outcome",
    "manual",
]
LibraryAssetType = Literal[
    "knowledge",
    "project",
    "skill",
    "agent",
    "asset",
    "runtime_artifact",
    "external_source",
    "plan",
    "training_card",
    "memory",
    "habit",
    "skill_definition",
]
LibraryAssetScope = Literal["library", "personal", "project"]
LibraryAssetStatus = Literal["active", "deleted"]
AssetSourceKind = Literal[
    "url",
    "resource",
    "project",
    "context",
    "asset",
    "memory",
    "runtime",
    "manual",
]
AssetLinkRelation = Literal["available_to", "derived_from", "references", "pinned"]
TrainingCardType = Literal["practice", "flash", "drill", "transfer"]
TrainingLearningFamily = Literal["code", "theory"]
TrainingCardStatus = Literal[
    "candidate",
    "active",
    "needs_primer",
    "answered",
    "implemented",
    "completed",
    "reviewed",
    "fed_back",
    "archived",
    "skipped",
    "blocked",
]
TrainingLearningPhase = Literal["learn", "try", "verify", "reflect", "return"]
TrainingCardCreatedFrom = Literal[
    "conversation",
    "plan",
    "resource",
    "practice_feedback",
    "dependency_mastery",
    "review_due",
    "recovery",
]
TrainingCardTrustState = Literal["trusted", "fresh", "unknown", "stale", "untrusted"]
DependencyMasteryStage = Literal["understood", "recalled", "practiced", "applied", "transferable"]
ProviderCredentialMode = Literal["workspace_secret", "ui_proxy"]
FolderRole = Literal[
    "empty_new_project",
    "existing_engineering",
    "algorithm_model",
    "idea_scratchpad",
    "learning_materials",
    "mixed_uncertain",
]
ProjectTypeGuess = Literal[
    "web_app",
    "api_service",
    "cli_tool",
    "library_package",
    "ml_model",
    "notebook_research",
    "mobile_app",
    "desktop_app",
    "embedded_iot",
    "data_pipeline",
    "monorepo",
    "documentation",
    "game",
    "config_dotfiles",
    "unknown",
]
ProviderProtocol = Literal[
    "openai_responses",
    "openai_chat_completions",
    "anthropic_messages",
    "openai_chat_completions_compatible",
    "gemini_generate_content",
]
ProviderProtocolFamily = Literal["openai", "anthropic", "gemini"]
ProviderProtocolTestMode = Literal["openai_chat", "responses", "anthropic", "gemini"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CapabilityFlags(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    chat: bool = True
    responses: bool = True
    vision: bool = False
    embeddings: bool = True
    tools: bool = False
    json_schema: bool = Field(default=False, alias="jsonSchema")
    structured_output: bool = Field(default=False, alias="structuredOutput")
    streaming: bool = True
    thinking: bool = False


class ProviderProtocolCatalogEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    protocol: ProviderProtocol
    protocol_family: ProviderProtocolFamily = Field(alias="protocolFamily")
    client_kind: str = Field(alias="clientKind")
    completion_label: str = Field(alias="completionLabel")
    endpoint_hint: str = Field(alias="endpointHint")
    test_mode: ProviderProtocolTestMode = Field(alias="testMode")
    required_capability: str | None = Field(default=None, alias="requiredCapability")
    diagnostic_notes: list[str] = Field(default_factory=list, alias="diagnosticNotes")


class ProviderModelTokenLimit(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    context_window_tokens: int | None = Field(default=None, alias="contextWindowTokens")
    max_output_tokens: int | None = Field(default=None, alias="maxOutputTokens")


class ProviderConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str
    base_url: str = Field(alias="baseUrl")
    api_key_ref: str = Field(alias="apiKeyRef")
    model: str
    protocol: ProviderProtocol = "openai_chat_completions_compatible"
    label: str | None = None
    mode: Literal["direct", "gateway"] | None = None
    connection_type: str | None = Field(default=None, alias="connectionType")
    credential_mode: ProviderCredentialMode | None = Field(default=None, alias="credentialMode")
    available_models: list[str] = Field(default_factory=list, alias="availableModels")
    allowed_models: list[str] = Field(default_factory=list, alias="allowedModels")
    denied_models: list[str] = Field(default_factory=list, alias="deniedModels")
    model_aliases: dict[str, str] = Field(default_factory=dict, alias="modelAliases")
    model_capabilities: dict[str, CapabilityFlags] = Field(
        default_factory=dict,
        alias="modelCapabilities",
    )
    model_token_limits: dict[str, ProviderModelTokenLimit] = Field(
        default_factory=dict,
        alias="modelTokenLimits",
    )
    task_bindings: dict[str, Any] = Field(default_factory=dict, alias="taskBindings")
    context_window_tokens: int | None = Field(default=None, alias="contextWindowTokens")
    max_output_tokens: int | None = Field(default=None, alias="maxOutputTokens")
    embedding_model: str | None = Field(default=None, alias="embeddingModel")
    catalog_source: str | None = Field(default=None, alias="catalogSource")
    cache_ttl_seconds: int | None = Field(default=None, alias="cacheTtlSeconds")
    profile_id: str | None = Field(default=None, alias="profileId")
    profile_label: str | None = Field(default=None, alias="profileLabel")
    profile_mode: str | None = Field(default=None, alias="profileMode")
    request_defaults: dict[str, Any] = Field(default_factory=dict, alias="requestDefaults")
    capabilities: CapabilityFlags = Field(default_factory=CapabilityFlags)


class UserProfile(BaseModel):
    long_term_goal: str = ""
    long_term_goals: list[str] = Field(default_factory=list)
    background: str = ""
    weekly_hours: int = 4
    teaching_style: str = "auto"
    answer_policy: Literal["auto", "guided", "balanced", "direct"] = "auto"
    target_project: str | None = None
    preferred_libraries: list[str] = Field(default_factory=list)

    @field_validator("answer_policy", mode="before")
    @classmethod
    def normalize_answer_policy_aliases(cls, value: Any) -> Any:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return "auto"
        if normalized == "coach-first":
            return "guided"
        return normalized

    @model_validator(mode="after")
    def sync_goals(self) -> "UserProfile":
        if not self.long_term_goal and self.long_term_goals:
            self.long_term_goal = self.long_term_goals[0]
        if self.long_term_goal and not self.long_term_goals:
            self.long_term_goals = [self.long_term_goal]
        return self


class PlanPhase(BaseModel):
    title: str
    objective: str
    exercises: list[str] = Field(default_factory=list)
    completion_signal: str = ""


class PlanStage(BaseModel):
    id: str
    title: str
    goal: str
    outcomes: list[str]
    resources: list[str] = Field(default_factory=list)
    status: Literal["pending", "active", "completed"] = "pending"


class LearningPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    title: str
    summary: str = ""
    stages: list[PlanStage] = Field(default_factory=list)
    cadence: str = ""
    frozen: bool = False
    current_stage_id: str | None = None
    current_step: str = ""
    why_now: str = ""
    verify_method: list[str] = Field(default_factory=list)
    blocked_reason: str = ""
    next_after_current: str = ""
    plan_id: str | None = None
    session_id: str | None = None
    objective: str | None = None
    phases: list[PlanPhase] = Field(default_factory=list)
    weekly_cadence: str | None = None
    default_answer_policy: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    workspace_id: str = Field(default="", alias="workspaceId")

    @model_validator(mode="after")
    def sync_compat_fields(self, info: ValidationInfo) -> "LearningPlan":
        from app.memory.workspace_recovery import (
            leftover_formal_plan_is_live_for_fill,
            live_plan_current_step_fill,
            live_plan_next_after_current,
        )

        if not self.id and self.plan_id:
            self.id = self.plan_id
        if not self.plan_id:
            self.plan_id = self.id
        if not self.weekly_cadence:
            self.weekly_cadence = self.cadence
        if not self.cadence and self.weekly_cadence:
            self.cadence = self.weekly_cadence
        if not self.objective:
            self.objective = self.summary
        if not self.summary and self.objective:
            self.summary = self.objective
        if not self.default_answer_policy:
            self.default_answer_policy = "auto"
        if not self.created_at:
            self.created_at = utc_now_iso()
        if not self.updated_at:
            self.updated_at = utc_now_iso()
        context = info.context if isinstance(info.context, dict) else {}
        runtime = context.get("runtime")
        existing = context.get("existing")
        live_plan = leftover_formal_plan_is_live_for_fill(
            plan=self,
            runtime=runtime if isinstance(runtime, dict) else None,
            existing=existing if isinstance(existing, dict) else None,
        )
        active_stage_index = next(
            (
                index
                for index, stage in enumerate(self.stages)
                if stage.id == self.current_stage_id or stage.status == "active"
            ),
            0,
        )
        active_stage = self.stages[active_stage_index] if self.stages else None
        next_stage = self.stages[active_stage_index + 1] if active_stage and active_stage_index + 1 < len(self.stages) else None
        if not self.phases and self.stages:
            self.phases = [
                PlanPhase(
                    title=stage.title,
                    objective=stage.goal,
                    exercises=stage.outcomes,
                    completion_signal=", ".join(stage.outcomes),
                )
                for stage in self.stages
            ]
        if not self.stages and self.phases:
            self.stages = [
                PlanStage(
                    id=f"phase-{index}",
                    title=phase.title,
                    goal=phase.objective,
                    outcomes=phase.exercises or ([phase.completion_signal] if phase.completion_signal else []),
                    resources=[],
                    status="active" if index == 0 else "pending",
                )
                for index, phase in enumerate(self.phases)
            ]
        if not self.current_step:
            phase_objective = ""
            if self.phases:
                phase_objective = (
                    self.phases[active_stage_index].objective
                    if active_stage_index < len(self.phases)
                    else self.phases[0].objective
                )
            self.current_step = live_plan_current_step_fill(
                plan=self,
                runtime=runtime if isinstance(runtime, dict) else None,
                existing=existing if isinstance(existing, dict) else None,
                stage_goal=active_stage.goal if active_stage else "",
                phase_objective=phase_objective,
                summary=self.summary,
                objective=self.objective or "",
                title=self.title,
            )
        if not self.why_now:
            if self.current_step:
                self.why_now = "Stay on the current live step before widening scope."
            elif live_plan and self.summary:
                self.why_now = self.summary
            elif live_plan and self.objective:
                self.why_now = self.objective
            else:
                self.why_now = "Stay on the current live step before widening scope."
        if not self.verify_method:
            if active_stage and active_stage.outcomes:
                self.verify_method = [item for item in active_stage.outcomes if item]
            elif self.phases and active_stage_index < len(self.phases):
                phase = self.phases[active_stage_index]
                self.verify_method = [item for item in phase.exercises if item] or (
                    [phase.completion_signal] if phase.completion_signal else []
                )
            if not self.verify_method:
                self.verify_method = ["Run the smallest relevant check."]
        if not self.next_after_current:
            next_phase_objective = ""
            if len(self.phases) > active_stage_index + 1:
                next_phase_objective = self.phases[active_stage_index + 1].objective
            self.next_after_current = live_plan_next_after_current(
                plan=self,
                runtime=runtime if isinstance(runtime, dict) else None,
                existing=existing if isinstance(existing, dict) else None,
                next_stage_goal=next_stage.goal if next_stage else "",
                next_phase_objective=next_phase_objective,
            )
        return self


class GlobalPlan(BaseModel):
    """The local Trainer's explicit, cross-project learning plan."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    owner_id: str = Field(alias="ownerId")
    title: str
    summary: str = ""
    goals: list[str] = Field(default_factory=list)
    stages: list[PlanStage] = Field(default_factory=list)
    frozen: bool = False
    current_project_plan_id: str | None = Field(default=None, alias="currentProjectPlanId")
    current_stage_id: str | None = Field(default=None, alias="currentStageId")
    current_step: str = Field(default="", alias="currentStep")
    why_now: str = Field(default="", alias="whyNow")
    verify_method: list[str] = Field(default_factory=list, alias="verifyMethod")
    created_at: str = Field(default_factory=utc_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")

    @field_validator("id", "owner_id", "title")
    @classmethod
    def require_identity_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("global plan identity fields are required")
        return normalized


class GlobalPlanProjectLink(BaseModel):
    """An explicit association between one global plan and one project plan."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    global_plan_id: str = Field(alias="globalPlanId")
    workspace_id: str = Field(alias="workspaceId")
    project_plan_id: str = Field(alias="projectPlanId")
    linked_at: str = Field(default_factory=utc_now_iso, alias="linkedAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")

    @field_validator("global_plan_id", "workspace_id", "project_plan_id")
    @classmethod
    def require_link_identity_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("global plan project link identity fields are required")
        return normalized


class TrainerRoot(BaseModel):
    """A stable user-owned container for one or more managed projects."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    root_id: str = Field(alias="rootId")
    root_path: str = Field(alias="rootPath")
    display_name: str = Field(alias="displayName")
    path_history: list[str] = Field(default_factory=list, alias="pathHistory")
    revision: int = Field(default=1, ge=1, alias="revision")
    created_at: str = Field(default_factory=utc_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")

    @field_validator("root_id", "root_path", "display_name")
    @classmethod
    def require_root_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("trainer root identity fields are required")
        return normalized


class TrainerProject(BaseModel):
    """A stable project identity whose location may be reconciled over time."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    project_id: str = Field(alias="projectId")
    root_id: str = Field(alias="rootId")
    project_path: str = Field(alias="projectPath")
    project_name: str = Field(alias="projectName")
    path_history: list[str] = Field(default_factory=list, alias="pathHistory")
    revision: int = Field(default=1, ge=1, alias="revision")
    created_at: str = Field(default_factory=utc_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")

    @field_validator("project_id", "root_id", "project_path", "project_name")
    @classmethod
    def require_project_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("trainer project identity fields are required")
        return normalized


class ProjectContext(BaseModel):
    """The isolated runtime, memory, plan, and training lane for one project."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    context_id: str = Field(alias="contextId")
    root_id: str = Field(alias="rootId")
    project_id: str = Field(alias="projectId")
    project_memory_id: str = Field(alias="projectMemoryId")
    project_plan_id: str = Field(alias="projectPlanId")
    project_training_id: str = Field(alias="projectTrainingId")
    project_agent_context_id: str = Field(alias="projectAgentContextId")
    agent_session_id: str = Field(alias="agentSessionId")
    legacy_workspace_id: str | None = Field(default=None, alias="legacyWorkspaceId")
    global_plan_id: str | None = Field(default=None, alias="globalPlanId")
    status: Literal["provisioned"] = "provisioned"
    revision: int = Field(default=1, ge=1, alias="revision")
    created_at: str = Field(default_factory=utc_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")

    @field_validator(
        "context_id",
        "root_id",
        "project_id",
        "project_memory_id",
        "project_plan_id",
        "project_training_id",
        "project_agent_context_id",
        "agent_session_id",
    )
    @classmethod
    def require_context_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("project context identity fields are required")
        return normalized


class ProjectProvisioning(ProjectContext):
    """Durable project context plus its compatibility workspace alias."""

    workspace_id: str = Field(alias="workspaceId")
    project_path: str = Field(alias="projectPath")
    project_name: str = Field(alias="projectName")
    root_path: str = Field(alias="rootPath")
    root_revision: int = Field(default=1, ge=1, alias="rootRevision")
    project_revision: int = Field(default=1, ge=1, alias="projectRevision")

    @field_validator("workspace_id", "project_path", "project_name", "root_path")
    @classmethod
    def require_provisioning_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("project provisioning identity fields are required")
        return normalized

    @model_validator(mode="after")
    def sync_workspace_alias(self) -> "ProjectProvisioning":
        if self.workspace_id != self.context_id:
            raise ValueError("workspace_id is a compatibility alias for context_id")
        return self

    def adoption_artifacts(self) -> dict[str, str]:
        return {
            "root_id": self.root_id,
            "project_id": self.project_id,
            "context_id": self.context_id,
            "project_memory_id": self.project_memory_id,
            "project_plan_id": self.project_plan_id,
            "project_training_id": self.project_training_id,
            "project_agent_context_id": self.project_agent_context_id,
        }


class SubPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = ""
    parent_plan_id: str = Field(default="", alias="parentPlanId")
    title: str
    description: str = ""
    stages: list[PlanStage] = Field(default_factory=list)
    status: Literal["draft", "active", "completed", "archived"] = "draft"
    progress_percent: float = Field(default=0.0, alias="progressPercent")
    created_at: str = Field(default_factory=utc_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")


class SourceIntakeDeclaration(BaseModel):
    """Unverified source metadata supplied during resource intake.

    Declarations are preserved for a reviewer but never make a source eligible
    for commercial reuse by themselves. The derived governance record below
    distinguishes declarations from evidence observed in the imported content.
    """

    license_expression: str = ""
    license_evidence_uri: str = ""
    maintenance_updated_at: str = ""
    maintenance_evidence_uri: str = ""


class SourceIntakeGovernance(BaseModel):
    """Auditable policy result for a source that may be reused commercially."""

    policy_version: str = "source-intake-v1"
    assessed_at: str | None = None
    source_provenance_status: str = "unknown"
    license_status: Literal["unknown", "declared", "observed"] = "unknown"
    license_expression: str = ""
    license_evidence_kind: Literal["none", "user_declaration", "source_spdx"] = "none"
    license_evidence_source: str = ""
    license_evidence_excerpt: str = ""
    maintenance_status: Literal[
        "unknown", "declared", "reported_recent", "reported_stale"
    ] = "unknown"
    maintenance_updated_at: str | None = None
    maintenance_evidence_kind: Literal[
        "none", "user_declaration", "source_last_updated"
    ] = "none"
    maintenance_evidence_source: str = ""
    maintenance_evidence_excerpt: str = ""
    commercial_reuse_policy: str = "permissive-spdx-v1"
    commercial_reuse_status: Literal["eligible", "review_required", "blocked"] = (
        "review_required"
    )
    commercial_reuse_reason_codes: list[str] = Field(
        default_factory=lambda: [
            "controlled_provenance_missing",
            "license_unknown",
            "maintenance_unknown",
        ]
    )


class ResourceRecord(BaseModel):
    id: str
    kind: Literal["pdf", "image", "text", "markdown", "code", "url"]
    name: str
    source: str
    tags: list[str] = Field(default_factory=list)
    source_items: list[str] = Field(default_factory=list)
    # Stable display path inside a resource collection. This is intentionally
    # separate from the sandbox artifact path, which may include an isolation key.
    collection_path: str | None = None
    # Canonical local directory that proves the collection boundary for collection_path.
    collection_root: str | None = None
    summary: str = ""
    parse_status: Literal["pending", "parsed", "failed"] = "pending"
    index_status: Literal["pending", "indexed", "failed"] = "pending"
    source_type: str = ""
    canonical_source: str = ""
    fetched_at: str | None = None
    source_declaration: SourceIntakeDeclaration = Field(default_factory=SourceIntakeDeclaration)
    source_governance: SourceIntakeGovernance = Field(default_factory=SourceIntakeGovernance)
    trust_score: float = 0.0
    freshness: Literal["fresh", "stale", "unknown"] = "unknown"
    duplicate_key: str = ""
    quality_flags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    knowledge_fragments: list[dict[str, Any]] = Field(default_factory=list)
    sandbox_path: str | None = None
    sandbox_origin: str | None = None
    sandbox_synced_at: str | None = None
    sandbox_dirty: bool = False
    extracted_artifact_path: str | None = None

    @computed_field(return_type=ResourceTrustState)
    @property
    def trust_state(self) -> ResourceTrustState:
        return derive_resource_trust_state(
            self.trust_score,
            self.freshness,
            self.quality_flags,
        )


class ResourceTrashItem(BaseModel):
    """Minimal, display-safe projection of a deleted resource."""

    resource_id: str
    title: str
    collection_path: str | None = None
    deleted_at: str
    recoverable: bool


class ResourceTrashResponse(BaseModel):
    workspace_id: str
    items: list[ResourceTrashItem] = Field(default_factory=list)


class LocalOwner(BaseModel):
    """The local Trainer profile that owns a cross-project asset library."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    display_name: str = Field(default="", alias="displayName")
    created_at: str = Field(default_factory=utc_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")


class GlobalMemoryCapability(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    concept: str = Field(alias="concept")
    verified_count: int = Field(default=0, alias="verifiedCount")
    last_outcome: str = Field(default="", alias="lastOutcome")
    last_verified_at: str = Field(default_factory=utc_now_iso, alias="lastVerifiedAt")
    workspace_ids: list[str] = Field(default_factory=list, alias="workspaceIds")
    scene_count: int = Field(default=0, alias="sceneCount")


class GlobalMemoryGrowthRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    outcome: str = Field(alias="outcome")
    concepts: list[str] = Field(default_factory=list, alias="concepts")
    verified_at: str = Field(default_factory=utc_now_iso, alias="verifiedAt")


class GlobalMemory(BaseModel):
    """Owner-scoped memory that intentionally excludes project state."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    owner_id: str = Field(alias="ownerId")
    preferences: dict[str, str] = Field(default_factory=dict, alias="preferences")
    long_term_goals: list[str] = Field(default_factory=list, alias="longTermGoals")
    capability_profile: dict[str, GlobalMemoryCapability] = Field(
        default_factory=dict,
        alias="capabilityProfile",
    )
    growth_history: list[GlobalMemoryGrowthRecord] = Field(default_factory=list, alias="growthHistory")
    created_at: str = Field(default_factory=utc_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")

    @field_validator("long_term_goals")
    @classmethod
    def normalize_long_term_goals(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))[:24]


class AssetSourceReference(BaseModel):
    """A durable provenance entry for a canonical library asset."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    kind: AssetSourceKind = "manual"
    ref: str
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ref")
    @classmethod
    def require_source_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("asset source reference is required")
        return normalized


class LibraryAsset(BaseModel):
    """A durable, owner-scoped asset that may be linked into many workspaces."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    owner_id: str = Field(alias="ownerId")
    asset_type: LibraryAssetType = Field(alias="assetType")
    scope: LibraryAssetScope = "library"
    title: str
    canonical_source: str = Field(default="", alias="canonicalSource")
    source_chain: list[AssetSourceReference] = Field(default_factory=list, alias="sourceChain")
    project_id: str | None = Field(default=None, alias="projectId")
    context_id: str | None = Field(default=None, alias="contextId")
    status: LibraryAssetStatus = "active"
    deleted_at: str | None = Field(default=None, alias="deletedAt")
    deletion_reason: str = Field(default="", alias="deletionReason")
    current_revision_id: str | None = Field(default=None, alias="currentRevisionId")
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")

    @field_validator("id", "owner_id", "title")
    @classmethod
    def require_library_asset_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("library asset identity fields are required")
        return normalized

    @model_validator(mode="after")
    def normalize_asset_lifecycle(self) -> "LibraryAsset":
        self.canonical_source = self.canonical_source.strip()
        self.project_id = self.project_id.strip() if self.project_id else None
        self.context_id = self.context_id.strip() if self.context_id else None
        self.deletion_reason = self.deletion_reason.strip()
        if self.status == "active":
            self.deleted_at = None
            self.deletion_reason = ""
        return self


class AssetSourceState(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: AssetSourceKind
    ref: str
    state: Literal["available", "missing", "unknown", "unsupported"]


class LibraryAssetCatalogEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    asset: LibraryAsset
    capabilities: dict[str, Literal["supported", "unsupported"]] = Field(default_factory=dict)
    source_state: list[AssetSourceState] = Field(default_factory=list, alias="sourceState")


class LibraryAssetCatalogSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    context_id: str = Field(default="", alias="contextId")
    revision: str = ""
    active: list[LibraryAssetCatalogEntry] = Field(default_factory=list)
    deleted: list[LibraryAssetCatalogEntry] = Field(default_factory=list)


class AssetRevision(BaseModel):
    """One retained version of a library asset, including optional local snapshot metadata."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    asset_id: str = Field(alias="assetId")
    owner_id: str = Field(alias="ownerId")
    parent_revision_id: str | None = Field(default=None, alias="parentRevisionId")
    content_hash: str = Field(default="", alias="contentHash")
    storage_path: str | None = Field(default=None, alias="storagePath")
    media_type: str = Field(default="", alias="mediaType")
    source_url: str | None = Field(default=None, alias="sourceUrl")
    fetched_at: str | None = Field(default=None, alias="fetchedAt")
    extraction_metadata: dict[str, Any] = Field(default_factory=dict, alias="extractionMetadata")
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")


class AssetLink(BaseModel):
    """An owner-scoped relationship between an asset and a workspace or artifact."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str
    owner_id: str = Field(alias="ownerId")
    asset_id: str = Field(alias="assetId")
    workspace_id: str = Field(alias="workspaceId")
    project_id: str | None = Field(default=None, alias="projectId")
    context_id: str | None = Field(default=None, alias="contextId")
    relation: AssetLinkRelation = "available_to"
    source_ref: str = Field(default="", alias="sourceRef")
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso, alias="createdAt")
    updated_at: str = Field(default_factory=utc_now_iso, alias="updatedAt")

    @model_validator(mode="after")
    def sync_context_alias(self) -> "AssetLink":
        self.workspace_id = self.workspace_id.strip()
        self.project_id = self.project_id.strip() if self.project_id else None
        self.context_id = self.context_id.strip() if self.context_id else None
        if not self.workspace_id:
            raise ValueError("asset link workspace identity is required")
        if self.context_id and self.workspace_id != self.context_id:
            raise ValueError("asset link workspace_id must match context_id when both are provided")
        return self


class LibraryAssetUpsertRequest(BaseModel):
    """Public request contract for the durable Resources asset library."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    asset_id: str | None = Field(default=None, alias="assetId")
    asset_type: LibraryAssetType = Field(alias="assetType")
    scope: LibraryAssetScope = "library"
    title: str
    canonical_source: str = Field(default="", alias="canonicalSource")
    source_chain: list[AssetSourceReference] = Field(default_factory=list, alias="sourceChain")
    project_id: str | None = Field(default=None, alias="projectId")
    context_id: str | None = Field(default=None, alias="contextId")
    payload: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


class LibraryAssetLinkRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    context_id: str = Field(alias="contextId")
    project_id: str | None = Field(default=None, alias="projectId")
    relation: AssetLinkRelation = "available_to"
    source_ref: str = Field(default="", alias="sourceRef")
    payload: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


class LibraryAssetLifecycleRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    approved: bool = False
    reason: str = ""


class TeachingKnowledgeAsset(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = ""
    kind: TeachingAssetKind
    scope: TeachingAssetScope = "project"
    workspace_id: str = ""
    title: str
    summary: str = ""
    concept_card: str = ""
    implementation_pattern: str = ""
    common_pitfall: str = ""
    exercise_seed: str = ""
    explanation_recipe: str = ""
    why_it_matters: str = ""
    example: str = ""
    anti_pattern: str = ""
    focus_area: str = ""
    scenario: str = ""
    origin: TeachingAssetOrigin = "manual"
    source_key: str = ""
    source_ids: list[str] = Field(default_factory=list)
    source_fragments: list[str] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list)
    retrieval_hints: list[str] = Field(default_factory=list)
    source_summary: str = ""
    source_quality_flags: list[str] = Field(default_factory=list)
    source_freshness: Literal["fresh", "stale", "unknown"] = "unknown"
    source_retrieved_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    trust_score: float = 0.0
    usage_count: int = 0
    plan_stage_id: str = ""
    success_count: int = 0
    failure_count: int = 0
    last_outcome: str = ""
    last_effective_at: str | None = None
    effectiveness_by_scenario: dict[str, dict[str, int]] = Field(default_factory=dict)
    last_used_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def sync_identity(self) -> "TeachingKnowledgeAsset":
        if not self.workspace_id:
            # Empty general assets must not auto-promote into the global catalog.
            self.workspace_id = ""
        if not self.source_key:
            source_bits = [
                self.scope,
                self.kind,
                self.workspace_id or "__global__",
                self.focus_area or self.scenario or self.title,
                ",".join(sorted({item.strip() for item in self.source_ids if item.strip()})),
            ]
            cleaned_source_key = "::".join(
                item.strip().lower().replace(" ", "-")
                for item in source_bits
                if isinstance(item, str) and item.strip()
            )
            self.source_key = cleaned_source_key or f"{self.scope}::{self.kind}::{self.title}"
        if not self.id:
            self.id = f"asset-{sha1(self.source_key.encode('utf-8')).hexdigest()[:12]}"
        if not self.summary:
            for candidate in (
                self.concept_card,
                self.implementation_pattern,
                self.common_pitfall,
                self.exercise_seed,
                self.explanation_recipe,
                self.why_it_matters,
                self.example,
                self.anti_pattern,
            ):
                cleaned = candidate.strip()
                if cleaned:
                    self.summary = cleaned
                    break
        if not self.source_summary:
            for candidate in (
                self.why_it_matters,
                self.example,
                self.explanation_recipe,
                self.summary,
            ):
                cleaned = candidate.strip()
                if cleaned:
                    self.source_summary = cleaned
                    break
        if not self.evidence_snippets:
            derived_evidence = [
                item.strip()
                for item in [
                    self.example,
                    self.anti_pattern,
                    *self.source_fragments[:2],
                ]
                if isinstance(item, str) and item.strip()
            ]
            self.evidence_snippets = derived_evidence[:3]
        if not self.retrieval_hints:
            hints = [
                self.focus_area.strip(),
                self.scenario.strip(),
                *[item.strip() for item in self.tags if item.strip()],
                self.title.strip(),
            ]
            seen_hints: set[str] = set()
            normalized_hints: list[str] = []
            for item in hints:
                lowered = item.lower()
                if not item or lowered in seen_hints:
                    continue
                seen_hints.add(lowered)
                normalized_hints.append(item)
            self.retrieval_hints = normalized_hints[:8]
        if not self.created_at:
            self.created_at = utc_now_iso()
        if not self.updated_at:
            self.updated_at = utc_now_iso()
        return self


class TaskSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    natural_language_goal: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    edge_cases: list[str] = Field(default_factory=list)
    failure_conditions: list[str] = Field(default_factory=list)
    verification_strategy: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    workspace_id: str = Field(default="", alias="workspaceId")


class EvaluationCheck(BaseModel):
    id: str
    label: str
    status: Literal["passed", "failed", "warning", "skipped"]
    detail: str


class EvaluationReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_spec_id: str | None = None
    summary: str
    static_checks: list[EvaluationCheck] = Field(default_factory=list)
    dynamic_checks: list[EvaluationCheck] = Field(default_factory=list)
    semantic_checks: list[EvaluationCheck] = Field(default_factory=list)
    next_step: str
    reflection: str | None = None
    passed: bool
    workspace_id: str = Field(default="", alias="workspaceId")


class ReviewQueueItem(BaseModel):
    concept: str
    reason: str
    due_at: str | None = None
    source: Literal["weakness", "mastery", "reflection", "plan"] = "weakness"
    severity: Literal["low", "medium", "high"] = "medium"
    surface_mode: Literal["due", "ahead", "digest"] = "due"
    task_hint: str = ""
    focus_area: str = ""
    linked_context: str = ""
    interval_days: int | None = None
    mastery_score: float | None = None


class TrainingCardCandidateSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    card_id: str = ""
    card_type: TrainingCardType = "practice"
    title: str = ""
    status: TrainingCardStatus = "candidate"
    learning_phase: TrainingLearningPhase = "learn"
    created_from: TrainingCardCreatedFrom = "conversation"
    scenario_pack: str = ""
    why_now: str = ""
    focus_area: str = ""
    target_skill: str = ""
    learning_family: TrainingLearningFamily = "theory"
    learning_subtype: str = "concept"
    scenario: str = ""
    problem_statement: str = ""
    suggested_workspace_action: str = ""
    api_hints: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    deliverable: str = ""
    self_check: list[str] = Field(default_factory=list)
    expected_answer_shape: str = ""
    validation_method: str = ""
    grading_rubric: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    trainer_review_input: str = ""
    stuck_recovery: str = ""
    reflection_prompt: str = ""
    knowledge_type: str = ""
    question: str = ""
    context: str = ""
    answer_mode: str = "text"
    options: list[str] = Field(default_factory=list)
    correct_option_index: int | None = None
    correct_option_indices: list[int] = Field(default_factory=list)
    correct_sort_order: list[int] = Field(default_factory=list)
    fill_blank_answers: dict[str, str] = Field(default_factory=dict)
    expected_answer: str = ""
    rubric: list[str] = Field(default_factory=list)
    hint_ladder: list[str] = Field(default_factory=list)
    feedback: dict[str, str] = Field(default_factory=dict)
    last_feedback: dict[str, Any] = Field(default_factory=dict)
    learner_answer: str = ""
    learner_selected_option_indices: list[int] = Field(default_factory=list)
    learner_fill_blank_answers: dict[str, str] = Field(default_factory=dict)
    learner_sort_order: list[int] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)
    review_schedule: dict[str, Any] = Field(default_factory=dict)
    difficulty: str = "medium"
    plan_links: list[str] = Field(default_factory=list)
    source_chain: list[str] = Field(default_factory=list)
    project_id: str = ""
    project_scope: str = ""
    requires_project_context: bool = False
    project_context_ready: bool = True
    trust_state: TrainingCardTrustState = "unknown"
    trust_acknowledged: bool = False
    resource_id: str = ""
    dependency_key: str = ""
    dependency_layer: str = ""
    question_style: str = ""
    verification_method: str = ""
    next_steps: list[str] = Field(default_factory=list)
    files_to_touch: list[str] = Field(default_factory=list)
    learner_deliverables: list[str] = Field(default_factory=list)
    verification_steps: list[str] = Field(default_factory=list)
    expected_symbols: list[str] = Field(default_factory=list)
    success_signal: str = ""
    return_with: str = ""
    next_after_completion: str = ""
    created_at: str = ""
    updated_at: str = ""

    @model_validator(mode="after")
    def sync_training_defaults(self) -> "TrainingCardCandidateSnapshot":
        if not self.created_at:
            self.created_at = utc_now_iso()
        if not self.updated_at:
            self.updated_at = utc_now_iso()
        if not self.title:
            self.title = self.question or self.problem_statement or self.target_skill or self.focus_area or "Training Card"
        if not self.source_chain:
            self.source_chain = ["card_generation_router"]
        try:
            from app.training.subject_taxonomy import classify_learning_subject

            subject = classify_learning_subject(
                self.focus_area,
                self.target_skill,
                self.scenario,
                self.problem_statement,
                self.question,
                self.knowledge_type,
                self.verification_method,
                self.scenario_pack,
                self.suggested_workspace_action,
            )
            default_family = not self.learning_family or self.learning_family == "theory"
            default_subtype = not self.learning_subtype or self.learning_subtype == "concept"
            if default_family and (subject.family != "theory" or subject.subtype != "concept"):
                self.learning_family = subject.family
            if default_subtype and subject.subtype != "concept":
                self.learning_subtype = subject.subtype
        except Exception:
            pass
        self.learning_family = self.learning_family or "theory"
        self.learning_subtype = self.learning_subtype or "concept"
        if self.learning_phase not in {"learn", "try", "verify", "reflect", "return"}:
            self.learning_phase = "learn"
        return self


class ResourceKnowledgeEvidence(BaseModel):
    """Server-projected indexed fragment that may ground a resource training card."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    resource_id: str = Field(default="", alias="resourceId")
    fragment_id: str = Field(default="", alias="fragmentId")
    source_type: str = Field(default="", alias="sourceType")
    focus_area: str = Field(default="", alias="focusArea")
    summary: str = ""


class DependencyUsageEvidence(BaseModel):
    """Server-projected import, call, or declared dependency usage fact."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    file_path: str = Field(default="", alias="filePath")
    kind: str = ""
    identifier: str = ""
    summary: str = ""


class CardGenerationContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    workspace_id: str = ""
    source: str = "conversation_gap"
    card_type: TrainingCardType = "practice"
    context_hint: str = ""
    target_skill: str = ""
    focus_area: str = ""
    plan_stage_id: str = ""
    resource_id: str = ""
    difficulty: str = "medium"
    hint_count: int | None = None
    code_reveal: str = ""
    practice_type: str = ""
    review_frequency: str = ""
    material_recommendation: str = ""
    next_plan_step: str = ""
    should_reveal_code: bool | None = None
    pedagogy_mode: str = ""
    why_now: str = ""
    resource_quality_flags: list[str] = Field(default_factory=list)
    resource_trust_score: float = 0.0
    resource_trust_state: str = ""
    resource_missing: bool = False
    resource_missing_reason: str = ""
    resource_freshness: str = ""
    resource_knowledge_evidence: ResourceKnowledgeEvidence | None = Field(
        default=None,
        alias="resourceKnowledgeEvidence",
    )
    response_language: ResponseLanguage | None = None
    current_file_path: str = Field(default="", alias="currentFilePath")
    current_file_language_id: str = Field(default="", alias="currentFileLanguageId")
    current_file_content: str = Field(default="", alias="currentFileContent")
    current_file_excerpt: str = Field(default="", alias="currentFileExcerpt")
    current_file_selection: str = Field(default="", alias="currentFileSelection")
    current_file_selection_range: str = Field(default="", alias="currentFileSelectionRange")
    current_file_diagnostics: list[str] = Field(
        default_factory=list,
        alias="currentFileDiagnostics",
    )
    dependency_usage_evidence: list[DependencyUsageEvidence] = Field(
        default_factory=list,
        alias="dependencyUsageEvidence",
    )
    workspace_root_path: str = Field(default="", alias="workspaceRootPath")
    remote_workspace_name: str = Field(default="", alias="remoteWorkspaceName")
    remote_workspace_facts: list[str] = Field(
        default_factory=list,
        alias="remoteWorkspaceFacts",
    )

    @field_validator("source", mode="before")
    @classmethod
    def normalize_legacy_conversation_source(cls, value: object) -> str:
        """Keep older Training clients on the canonical card-generation path."""

        source = str(value or "").strip()
        if not source or source == "conversation":
            return "conversation_gap"
        return source


class CardGenerationRequest(CardGenerationContext):
    source: str = "conversation_gap"
    card_type: TrainingCardType = "practice"
    submode: str = ""
    current_file: dict[str, Any] | None = Field(default=None, alias="currentFile")
    # Stream cancel remint identity — same request_id must not double-mint.
    request_id: str = Field(default="", alias="requestId", max_length=128)
    provider: dict[str, Any] | None = None
    api_key: str | None = Field(default=None, alias="apiKey")
    last_test_result: dict[str, Any] | None = Field(default=None, alias="lastTestResult")


class TrainingCardScoreFactors(BaseModel):
    plan_relevance: float = 0.0
    blocking_power: float = 0.0
    evidence_gap: float = 0.0
    recency_need: float = 0.0
    resource_trust: float = 0.0
    difficulty_fit: float = 0.0
    project_fit: float = 0.0
    transfer_value: float = 0.0
    recovery_priority: float = 0.0


class BlockedCandidateDetail(BaseModel):
    card_id: str = ""
    card_type: TrainingCardType = "practice"
    title: str = ""
    reasons: list[str] = Field(default_factory=list)


class ActiveCardSelectionResult(BaseModel):
    selected_card: TrainingCardCandidateSnapshot | None = None
    selected_card_id: str | None = None
    selection_score: float = 0.0
    score_factors: TrainingCardScoreFactors = Field(default_factory=TrainingCardScoreFactors)
    why_this_card: str = ""
    why_not_others: list[str] = Field(default_factory=list)
    blocked_candidates: list[BlockedCandidateDetail] = Field(default_factory=list)
    fallback_action: str = ""
    next_after_completion: str = ""
    candidate_count: int = 0
    eligible_count: int = 0


class CardGenerationResponse(BaseModel):
    card: TrainingCardCandidateSnapshot
    score: float = 0.0
    success: bool = True
    reason: str = ""
    active_routing: ActiveCardSelectionResult | None = None


class TrainingReliabilityRequestFields(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(default="", alias="requestId")
    idempotency_key: str = Field(default="", alias="idempotencyKey")
    revision: int = 0
    timeout_ms: int = Field(default=30_000, alias="timeoutMs")
    cancel: bool = False


class CardStatusTransitionRequest(TrainingReliabilityRequestFields):
    workspace_id: str
    card_id: str
    new_status: TrainingCardStatus
    reason: str = ""


class EvidenceItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = ""
    workspace_id: str = ""
    summary: str = ""
    source: str = "card_result"
    source_card_id: str = ""
    concepts: list[str] = Field(default_factory=list)
    outcome: str = "partial"
    confidence: float = 0.0
    verified: bool = False
    verification_source: str = ""
    timestamp: str = ""
    target_plan_stage_id: str = ""
    adopted: bool = False
    adopted_at: str | None = None
    deferred_at: str | None = None
    deferral_reason: str = ""
    rejected_at: str | None = None
    rejection_reason: str = ""

    @model_validator(mode="after")
    def sync_evidence_defaults(self) -> "EvidenceItem":
        if not self.timestamp:
            self.timestamp = utc_now_iso()
        return self


class EvidenceQueueSnapshot(BaseModel):
    pending: list[EvidenceItem] = Field(default_factory=list)
    deferred: list[EvidenceItem] = Field(default_factory=list)
    adopted: list[EvidenceItem] = Field(default_factory=list)
    rejected: list[EvidenceItem] = Field(default_factory=list)
    history: list[EvidenceItem] = Field(default_factory=list)
    unscoped: list[EvidenceItem] = Field(default_factory=list)
    total_count: int = 0


PlanChangeCandidateStatus = Literal["pending", "acknowledged", "rejected"]


class PlanChangeCandidate(BaseModel):
    id: str = ""
    workspace_id: str
    plan_id: str = ""
    feedback_id: str = ""
    reason: str
    diff: dict[str, Any] = Field(default_factory=dict)
    impact: dict[str, Any] = Field(default_factory=dict)
    status: PlanChangeCandidateStatus = "pending"
    created_at: str = Field(default_factory=utc_now_iso)
    acknowledged_at: str | None = None
    acknowledgement_note: str = ""


class EvidenceAdoptResponse(BaseModel):
    evidence: EvidenceItem
    plan_updated: bool = False
    plan_change_summary: str = ""


class CardStatusTransitionResponse(BaseModel):
    card: TrainingCardCandidateSnapshot
    ledger_entry: dict[str, Any] | None = None
    evidence_item: EvidenceItem | None = None


class DependencyMasterySnapshot(BaseModel):
    dependency_key: str
    dependency_name: str = ""
    apis: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    weakest_points: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    mastery_stage: DependencyMasteryStage = "understood"
    mastery_stage_progress: list[str] = Field(default_factory=lambda: ["understood"])
    latest_transfer_blocked_reason: str = ""
    latest_transfer_evidence_id: str = ""
    latest_transfer_evidence_summary: str = ""
    latest_transfer_source_workspace_id: str = ""
    latest_transfer_target_workspace_id: str = ""
    latest_transfer_source_context: str = ""
    latest_transfer_target_context: str = ""
    updated_at: str = Field(default_factory=utc_now_iso)


class DependencySkillItemSnapshot(BaseModel):
    key: str
    label: str
    layer: str
    related_api: str = ""
    scenario: str = ""
    knowledge_type: str = ""
    question_style: str = ""
    verification_method: str = ""
    hint_ladder: list[str] = Field(default_factory=list)
    priority: float = 0.0

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "high":
                return 0.9
            if normalized == "medium":
                return 0.6
            if normalized == "low":
                return 0.3
            try:
                return float(normalized)
            except ValueError:
                return 0.0
        return 0.0


class DependencySkillMapSnapshot(BaseModel):
    dependency_key: str
    dependency_name: str = ""
    version: int = 1
    covered_layers: list[str] = Field(default_factory=list)
    items: list[DependencySkillItemSnapshot] = Field(default_factory=list)
    top_review_items: list[DependencySkillItemSnapshot] = Field(default_factory=list)
    priority_summary: str = ""
    project_first_cut: str = ""
    suggested_scenario_lab: list[str] = Field(default_factory=list)
    last_action: str = "derived"
    last_action_note: str = ""
    updated_at: str = Field(default_factory=utc_now_iso)

    @field_validator("project_first_cut", mode="before")
    @classmethod
    def normalize_project_first_cut(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, bool):
            return "Build one minimum project slice first." if value else ""
        return str(value)

    @field_validator("suggested_scenario_lab", mode="before")
    @classmethod
    def normalize_suggested_scenario_lab(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str):
            return [value] if value.strip() else []
        return [str(value)]


class DependencySkillMapHistoryEntry(BaseModel):
    entry_id: str
    dependency_key: str
    action: str
    version: int
    focus_item_key: str = ""
    focus_label: str = ""
    note: str = ""
    before_snapshot: dict[str, Any] = Field(default_factory=dict)
    after_snapshot: dict[str, Any] = Field(default_factory=dict)
    after_summary: str = ""
    created_at: str = Field(default_factory=utc_now_iso)


class FlashDeckSnapshot(BaseModel):
    id: str
    title: str = ""
    focus_area: str = ""
    cards: list[TrainingCardCandidateSnapshot] = Field(default_factory=list)
    generated_at: str = Field(default_factory=utc_now_iso)


class FlashcardAttempt(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    card_id: str
    correct: bool
    score: float = 0.0
    detail: str = ""
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
    answer_mode: str = "text"
    feedback: dict[str, Any] = Field(default_factory=dict)
    recorded_at: str = Field(default_factory=utc_now_iso)
    dependency_key: str = ""
    dependency_layer: str = ""
    question_style: str = ""
    knowledge_type: str = ""
    dependency_mastery: list[DependencyMasterySnapshot] = Field(default_factory=list)
    dependency_skill_map_history: list[DependencySkillMapHistoryEntry] = Field(default_factory=list)


class ReviewQueueAction(BaseModel):
    entry_id: str = ""
    concept: str
    action: str
    outcome: str
    focus_area: str = ""
    task_hint: str = ""
    note: str = ""
    scope: str = "single"
    created_at: str = Field(default_factory=utc_now_iso)

    @model_validator(mode="after")
    def sync_review_action_defaults(self) -> "ReviewQueueAction":
        if not self.entry_id:
            digest = sha1(f"{self.concept}:{self.action}:{self.created_at}".encode("utf-8")).hexdigest()[:10]
            self.entry_id = f"review-{digest}"
        return self


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


class MemorySnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    profile: UserProfile | None = None
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


class WorkbenchSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    context_id: str = Field(default="", alias="contextId")
    sidecar_status: Literal["unknown", "starting", "ready", "error"] = "ready"
    active_panel: Literal["chat", "plan", "task", "evaluate"] = "chat"
    snapshot_revision: int = Field(default=0, alias="snapshotRevision")
    messages: list[ChatMessage] = Field(default_factory=list)
    profile: UserProfile | None = None
    plan: LearningPlan | None = None
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
    data_base64: str | None = Field(default=None, alias="dataBase64")
    source_path: str | None = Field(default=None, alias="sourcePath")
    name: str | None = None
    caption: str | None = None
    byte_size: int | None = Field(default=None, alias="byteSize")


class WorkspaceMemoryToggles(BaseModel):
    decisions: bool = True
    patterns: bool = True
    resources: bool = True


class CoachDefaults(BaseModel):
    memory_scope: CoachMemoryScope = "project"
    working_set_mode: WorkingSetMode = "balanced"
    review_cadence: ReviewCadence = "steady"
    review_reminder_mode: ReviewReminderMode = "due"
    workspace_memory_toggles: WorkspaceMemoryToggles = Field(default_factory=WorkspaceMemoryToggles)


class ResourceComposerIntent(BaseModel):
    """Advisory Resources-composer context with no path or write authority."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    mode: Literal["locate", "download", "organize", "cards"]
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
    active_view: Literal["coach", "plan", "resources", "training", "settings"] | None = Field(
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
    teaching_style: str | None = None
    coach_defaults: CoachDefaults | None = None
    attachments: list[MessageAttachment] = Field(default_factory=list)
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


class CoachSettingsRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    response_language: ResponseLanguage | None = None
    answer_mode: CoachRequestAnswerMode | None = None
    teaching_style: str | None = None
    coach_defaults: CoachDefaults | None = None
    follow_current_file: bool | None = None
    context_detail: Literal["focused", "balanced", "full"] | None = None
    include_current_file: bool | None = None
    include_selection: bool | None = None
    include_diagnostics: bool | None = None
    include_related_files: bool | None = None


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


class AgentCheckpointAccessRequest(BaseModel):
    """Scope a checkpoint read to the workspace that owns it."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    workspace_id: str = Field(alias="workspaceId", min_length=1, max_length=256)
    session_id: str | None = Field(default=None, alias="sessionId", max_length=256)

    @field_validator("workspace_id")
    @classmethod
    def normalize_workspace_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("workspace_id must be a non-empty local identifier")
        return normalized

    @field_validator("session_id")
    @classmethod
    def normalize_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or "\x00" in normalized:
            raise ValueError("session_id must be a local identifier when supplied")
        return normalized


class PlanGenerateRequest(BaseModel):
    workspace_id: str | None = None
    profile: UserProfile
    goals: list[str]
    constraints: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)


class PlanUpdateRequest(BaseModel):
    plan_id: str
    workspace_id: str | None = None
    instructions: str = ""
    freeze: bool = False
    title: str | None = None
    frozen: bool | None = None
    weekly_cadence: str | None = None


class GlobalPlanUpdateRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    title: str | None = None
    summary: str | None = None
    goals: list[str] | None = None
    stages: list[PlanStage] | None = None
    frozen: bool | None = None
    current_project_plan_id: str | None = None
    current_stage_id: str | None = None
    current_step: str | None = None
    why_now: str | None = None
    verify_method: list[str] | None = None


class GlobalPlanProjectLinkRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    project_plan_id: str | None = None


class ProviderTestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    provider: ProviderConfig
    api_key: str | None = Field(default=None, alias="apiKey")
    probe_message: str | None = Field(default=None, alias="probeMessage")
    response_language: str | None = Field(default=None, alias="responseLanguage")


ProviderCapabilityState = Literal["verified", "unsupported", "unverified", "disabled"]


class ProviderCapabilityEvidence(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str
    declared: bool
    observed: bool | None = None
    state: ProviderCapabilityState


class ProviderTestResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ok: bool
    detail: str
    configured: bool = True
    api_key_supplied: bool = False
    success: bool = False
    provider_name: str | None = None
    base_url: str | None = None
    model: str | None = None
    protocol: ProviderProtocol | None = None
    protocol_family: ProviderProtocolFamily | None = None
    status: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error_category: str | None = None
    retryable: bool = False
    status_code: int | None = None
    diagnostics: list[str] = Field(default_factory=list)
    provider_reachable: bool = False
    model_supported: bool | None = None
    capability_evidence: list[ProviderCapabilityEvidence] = Field(
        default_factory=list,
        alias="capabilityEvidence",
    )
    tools_ready: bool = Field(default=False, alias="toolsReady")
    tool_probe_status: ProviderCapabilityState = Field(
        default="unverified",
        alias="toolProbeStatus",
    )
    streaming_ready: bool = Field(default=False, alias="streamingReady")
    stream_probe_status: ProviderCapabilityState = Field(
        default="unverified",
        alias="streamProbeStatus",
    )
    vision_ready: bool = Field(default=False, alias="visionReady")
    vision_probe_status: ProviderCapabilityState = Field(
        default="unverified",
        alias="visionProbeStatus",
    )
    thinking_ready: bool = Field(default=False, alias="thinkingReady")
    thinking_probe_status: ProviderCapabilityState = Field(
        default="unverified",
        alias="thinkingProbeStatus",
    )


class ProviderModelsRequest(BaseModel):
    provider: ProviderConfig
    api_key: str | None = None


class ProviderModelsResponse(BaseModel):
    ok: bool
    detail: str
    available_models: list[str] = Field(default_factory=list)
    resolved_model: str | None = None
    model_token_limits: dict[str, ProviderModelTokenLimit] = Field(default_factory=dict)
    resolved_from_input: bool = False
    listed: bool = False
    error_category: str | None = None
    retryable: bool = False
    status_code: int | None = None
    diagnostics: list[str] = Field(default_factory=list)
    cache_hit: bool = False


class ResourceUploadRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    kind: Literal["pdf", "image", "text", "markdown", "code", "url"]
    name: str
    source: str
    content: str | None = None
    content_encoding: Literal["utf-8", "base64"] | None = None
    tags: list[str] = Field(default_factory=list)
    source_type: Literal["file", "folder", "url"] = "file"
    source_items: list[str] = Field(default_factory=list)
    collection_path: str | None = None
    collection_root: str | None = None
    source_declaration: SourceIntakeDeclaration = Field(default_factory=SourceIntakeDeclaration)


class ResourceIndexRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    resource_id: str
    enable_network: bool | None = None


class ResourceSearchRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    query: str = ""
    top_k: int = 10
    semantic_rerank: bool = False
    provider_rerank: bool = False
    project_scope: str | None = None
    trust_state: str | None = None
    file_type: str | None = None
    source_type: str | None = None
    kind: str | None = None
    index_state: str | None = None

    @model_validator(mode="after")
    def reject_unavailable_reranking(self) -> "ResourceSearchRequest":
        if self.semantic_rerank:
            raise ValueError("semantic_rerank is not available; resource search is lexical only")
        if self.provider_rerank:
            raise ValueError("provider_rerank is not available; resource search is lexical only")
        return self


class ResourceDeleteRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    resource_id: str


class ResourceRestoreRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    resource_id: str


class TaskNextRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    focus_area: str | None = None
    response_language: str | None = None


class TaskSpecifyRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    natural_language_goal: str


class EvaluateCurrentFileRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    task_spec_id: str | None = None
    file_path: str
    language_id: str
    content: str
    diagnostics: list[str] = Field(default_factory=list)
    evaluation_source: str | None = None
    training_card_id: str | None = None
    training_card_title: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    learner_deliverables: list[str] = Field(default_factory=list)
    expected_symbols: list[str] = Field(default_factory=list)


class EvaluateSnippetRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    task_spec_id: str | None = None
    language_id: str
    content: str
    diagnostics: list[str] = Field(default_factory=list)
    evaluation_source: str | None = None
    training_card_id: str | None = None
    training_card_title: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    learner_deliverables: list[str] = Field(default_factory=list)
    expected_symbols: list[str] = Field(default_factory=list)


class LearningSignalRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    concepts: list[str] = Field(default_factory=list)
    outcome: LearningSignalOutcome
    summary: str = ""
    checks: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    action_type: str = ""
    repetition_count: int | None = None
    focus_area: str | None = None
    scenario: str | None = None
    verified_result: str | None = None
    blocked_reason: str | None = None
    abandoned_reason: str | None = None
    selected_teaching_asset_ids: list[str] = Field(default_factory=list)


class UserFeedbackRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
    kind: UserFeedbackKind
    message: str = ""
    focus_area: str | None = None
    scenario: str | None = None
    training_card_id: str | None = None
    plan_id: str | None = None

    @field_validator("message")
    @classmethod
    def require_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("feedback message is required")
        return normalized


class WorkspaceContext(BaseModel):
    name: str
    root_path: str | None = None


class SessionRecord(BaseModel):
    session_id: str
    stage: str
    summary: str
    user_profile: UserProfile
    workspace_context: WorkspaceContext
    created_at: str
    updated_at: str


EventReversibility = Literal["reversible", "compensatable", "irreversible", "append_only"]


class EventLedgerEntry(BaseModel):
    event_id: str = ""
    event_type: str
    occurred_at: str = Field(default_factory=utc_now_iso)
    actor: str = "system"
    scope: str = ""
    project_id: str = ""
    source_chain: list[str] = Field(default_factory=list)
    payload_ref: dict[str, Any] = Field(default_factory=dict)
    before_state_ref: dict[str, Any] = Field(default_factory=dict)
    after_state_ref: dict[str, Any] = Field(default_factory=dict)
    reversibility: EventReversibility = "irreversible"
    audit_note: str = ""


class WorkspaceAuthoritySummary(BaseModel):
    has_workspace_root: bool = False
    active_workspace_root: str = ""
    root_uri: str = ""
    root_detail: str = ""
    source: str = ""
    source_detail: str = ""
    authority_source: str = ""
    remote_name: str = ""
    is_remote_workspace: bool = False
    permission_level: str = ""
    permission_label: str = ""
    permission_detail: str = ""
    authority_mode: str = ""
    authority_scope: str = "project"
    resource_write_allowed: bool = False
    resource_write_evidence: dict[str, Any] = Field(default_factory=dict)
    allowed_operations: list[str] = Field(default_factory=list)
    allowed_operations_text: str = ""
    mounted_sources: list[str] = Field(default_factory=list)
    ledger_entry_count: int = 0
    checkpoint_count: int = 0
    counts_text: str = ""
    trash_root: str = ""
    trash_detail: str = ""
    next_safe_action: str = ""
    summary_text: str = ""


class SandboxPlatformInfo(BaseModel):
    os: Literal["windows", "macos", "linux"] | str = ""
    architecture: str = ""
    shell_family: Literal["powershell", "posix"] | str = ""
    path_separator: str = ""
    case_sensitivity: Literal["case-sensitive", "case-insensitive"] | str = ""
    default_encoding: str = "utf-8"
    workspace_trust_state: str = "unknown"


class SandboxCommandEntry(BaseModel):
    id: str
    command: str
    cwd: str
    status: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    started_at: str
    finished_at: str
    truncated: bool = False


class SandboxNode(BaseModel):
    path: str
    relative_path: str = ""
    name: str
    node_kind: Literal["file", "directory"] | str
    file_kind: str = ""
    resource_id: str | None = None
    source_uri: str | None = None
    size_bytes: int = 0
    updated_at: str = ""
    children_count: int = 0
    is_editable: bool = False
    children: list["SandboxNode"] = Field(default_factory=list)


class SandboxPreview(BaseModel):
    path: str
    relative_path: str = ""
    title: str = ""
    node_kind: Literal["file", "directory"] | str = "file"
    file_kind: str = ""
    preview_tier: Literal["rich", "converted", "metadata"] | str = "rich"
    preview_kind: str = "text"
    language_hint: str = ""
    rendered_from: str = ""
    content: str = ""
    html: str | None = None
    excerpt: str = ""
    is_binary: bool = False
    is_editable: bool = False
    can_native_open: bool = True
    structured_data: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SandboxCapabilityStatus(BaseModel):
    status: str
    summary: str = ""
    policy: str = ""
    reason_code: str = ""
    reasons: list[str] = Field(default_factory=list)
    network_facts: SandboxNetworkExecutionFacts | dict[str, Any] | None = None


class SandboxOsContainerExecutorProbe(BaseModel):
    availability: str
    selected_runtime: str = ""
    selected_executor_mode: str = ""
    selected_entry_runtime: str = ""
    supported_entry_runtimes: list[str] = Field(default_factory=list)
    reason_code: str = ""
    reason: str = ""
    checked_at: str = ""
    runtime_path: str = ""
    probe_command: list[str] = Field(default_factory=list)
    probe_stdout_excerpt: str = ""
    probe_stderr_excerpt: str = ""
    probe_exit_code: int | None = None
    image_reference: str = ""
    image_repo_digests: list[str] = Field(default_factory=list)
    selected_image_repo_digest: str = ""
    image_trust_policy: str = ""
    image_trust_status: str = ""


class SandboxOsContainerExecutionPlan(BaseModel):
    status: str
    runtime: str = ""
    executor_mode: str = ""
    selected_entry_runtime: str = ""
    container_root_path: str = ""
    container_workdir: str = ""
    container_input_path: str = ""
    container_output_paths: list[str] = Field(default_factory=list)
    mount_root_path: str = ""
    mount_root_read_only: bool = True
    network_allowlist: list[str] = Field(default_factory=list)
    runtime_command: list[str] = Field(default_factory=list)
    container_image: str = ""
    container_image_repo_digest: str = ""
    image_trust_policy: str = ""
    image_trust_status: str = ""
    reason_code: str = ""
    reason: str = ""


class SandboxNetworkExecutionFacts(BaseModel):
    audited_python: dict[str, Any] = Field(default_factory=dict)
    unaudited_python: dict[str, Any] = Field(default_factory=dict)
    non_python: dict[str, Any] = Field(default_factory=dict)
    child_process: dict[str, Any] = Field(default_factory=dict)
    os_container: dict[str, Any] = Field(default_factory=dict)
    os_container_probe: SandboxOsContainerExecutorProbe | None = None


class SandboxCapabilitySummary(BaseModel):
    platform: SandboxPlatformInfo
    permission_state: str = ""
    path_guard_status: SandboxCapabilityStatus
    archive_audit_status: SandboxCapabilityStatus
    skill_manifest_status: SandboxCapabilityStatus
    skill_runtime_status: SandboxCapabilityStatus
    network_execution_status: SandboxCapabilityStatus
    output_boundary_status: SandboxCapabilityStatus
    cross_system_degradation: list[str] = Field(default_factory=list)


class SandboxStateThreatSummary(BaseModel):
    archive_threat_count: int = 0
    path_escape_count: int = 0
    mutation_block_count: int = 0
    skill_threat_count: int = 0
    prompt_injection_count: int = 0
    credential_access_count: int = 0
    network_exfiltration_count: int = 0
    supply_chain_count: int = 0
    malicious_document_count: int = 0
    resource_threat_count: int = 0


class SandboxState(BaseModel):
    workspace_id: str
    root_path: str = ""
    sandbox_root_path: str = ""
    workspace_root_path: str = ""
    active_workspace_root: str = ""
    trash_root_path: str = ""
    managed_roots: list[str] = Field(default_factory=list)
    ready: bool = False
    linked_resource_count: int = 0
    total_files: int = 0
    total_directories: int = 0
    total_size_bytes: int = 0
    last_updated_at: str = ""
    nodes: list[SandboxNode] = Field(default_factory=list)
    selected_path: str | None = None
    preview: SandboxPreview | None = None
    recent_commands: list[SandboxCommandEntry] = Field(default_factory=list)
    latest_command: SandboxCommandEntry | None = None
    notes: list[str] = Field(default_factory=list)
    capability_summary: SandboxCapabilitySummary | None = None
    authority: WorkspaceAuthoritySummary | dict[str, Any] | None = None
    threat_summary: SandboxStateThreatSummary | None = None


class SandboxPreviewRequest(BaseModel):
    workspace_id: str
    path: str


class SandboxMkdirRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    workspace_id: str
    path: str
    explicit_destructive_policy: bool = Field(
        default=False,
        alias="explicitDestructivePolicy",
    )


class SandboxWriteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    workspace_id: str
    path: str
    content: str = ""
    create: bool = False
    encoding: str | None = None
    explicit_destructive_policy: bool = Field(
        default=False,
        alias="explicitDestructivePolicy",
    )


class SandboxDeleteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    workspace_id: str
    path: str
    explicit_destructive_policy: bool = Field(
        default=False,
        alias="explicitDestructivePolicy",
    )


class SandboxRestoreRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    workspace_id: str
    path: str
    restore_path: str | None = None
    explicit_destructive_policy: bool = Field(
        default=False,
        alias="explicitDestructivePolicy",
    )


class SandboxRenameRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    path: str
    new_path: str
    explicit_destructive_policy: bool = Field(
        default=False,
        alias="explicitDestructivePolicy",
    )


class SandboxRenamePathRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    workspace_id: str
    path: str
    new_path: str
    explicit_destructive_policy: bool = Field(
        default=False,
        alias="explicitDestructivePolicy",
    )


class SandboxBatchRenameRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    workspace_id: str
    items: list[SandboxRenameRequest] = Field(default_factory=list)
    explicit_destructive_policy: bool = Field(
        default=False,
        alias="explicitDestructivePolicy",
    )


class SandboxPatchOperation(BaseModel):
    op: str
    path: str = ""
    new_path: str = ""
    content: str = ""
    create: bool = False
    encoding: str | None = None
    source: str = ""
    target: str = ""


class SandboxPatchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    workspace_id: str
    label: str = ""
    note: str = ""
    items: list[SandboxPatchOperation] = Field(default_factory=list)
    explicit_destructive_policy: bool = Field(
        default=False,
        alias="explicitDestructivePolicy",
    )


class SandboxCommandRequest(BaseModel):
    workspace_id: str
    command: str
    cwd: str | None = None
    timeout_ms: int | None = None
    timeout_seconds: int = 30


class SandboxArchiveAuditFinding(BaseModel):
    category: str
    severity: str
    reason: str
    evidence: str = ""
    source_path: str = ""


class SandboxArchiveAuditEntry(BaseModel):
    name: str
    normalized_path: str = ""
    target_path: str = ""
    entry_kind: str = ""
    uncompressed_bytes: int = 0
    blocked: bool = False
    reasons: list[str] = Field(default_factory=list)


class SandboxArchiveAuditResult(BaseModel):
    workspace_id: str
    path: str
    archive_path: str
    destination_path: str
    archive_format: str
    status: str
    allowed: bool
    policy: str
    findings: list[SandboxArchiveAuditFinding] = Field(default_factory=list)
    entry_count: int = 0
    total_uncompressed_bytes: int = 0
    max_entries: int = 0
    max_total_uncompressed_bytes: int = 0
    entries: list[SandboxArchiveAuditEntry] = Field(default_factory=list)


class SandboxSkillManifestFinding(BaseModel):
    category: str
    severity: str
    reason: str
    evidence: str = ""
    source_path: str = ""


class SandboxSkillManifestAuditResult(BaseModel):
    workspace_id: str
    path: str
    manifest_path: str = ""
    skill_name: str = ""
    status: str
    allowed: bool
    policy: str
    findings: list[SandboxSkillManifestFinding] = Field(default_factory=list)
    requested_permissions: list[str] = Field(default_factory=list)
    network_allowlist: list[str] = Field(default_factory=list)
    execution_entrypoints: list[str] = Field(default_factory=list)
    audited_paths: list[str] = Field(default_factory=list)


class SandboxSkillRuntimePolicy(BaseModel):
    platform: Literal["cross_platform", "windows", "macos", "linux"] | str = "cross_platform"
    command_templates: list[str] = Field(default_factory=list)
    network_allowlist: list[str] = Field(default_factory=list)
    env_whitelist: list[str] = Field(default_factory=list)
    output_paths: list[str] = Field(default_factory=list)
    timeout_ms: int = 20_000


class SandboxSkillRuntimePreflightResult(BaseModel):
    workspace_id: str
    path: str
    manifest_path: str = ""
    skill_name: str = ""
    status: str
    allowed: bool
    policy: str
    manifest_policy: str = ""
    current_platform: str = ""
    runtime_platform: str = ""
    command_templates: list[str] = Field(default_factory=list)
    network_allowlist: list[str] = Field(default_factory=list)
    env_whitelist: list[str] = Field(default_factory=list)
    output_paths: list[str] = Field(default_factory=list)
    normalized_output_paths: list[str] = Field(default_factory=list)
    timeout_ms: int = 0
    max_timeout_ms: int = 0
    manifest_audit: SandboxSkillManifestAuditResult | None = None
    findings: list[SandboxSkillManifestFinding] = Field(default_factory=list)
    audited_paths: list[str] = Field(default_factory=list)


class SandboxSkillEgressDecision(BaseModel):
    policy: str
    status: str
    allowed: bool
    enforcement_available: bool
    requested_hosts: list[str] = Field(default_factory=list)
    allowed_hosts: list[str] = Field(default_factory=list)
    blocked_hosts: list[str] = Field(default_factory=list)
    lane: str = ""
    required_executor: str = ""
    required_executor_probe: SandboxOsContainerExecutorProbe | None = None
    container_execution_plan: SandboxOsContainerExecutionPlan | None = None
    enforcement_mode: str = ""
    verified_command_paths: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reason_code: str = ""
    reason: str = ""
    operation_log: list[str] = Field(default_factory=list)


class SandboxSkillRunResult(BaseModel):
    run_id: str
    workspace_id: str
    path: str
    manifest_path: str = ""
    skill_name: str = ""
    status: str
    allowed: bool
    dry_run: bool = False
    execution_status: str = ""
    execution_performed: bool = False
    execution_reason: str = ""
    policy: str
    preflight_policy: str = ""
    preflight: SandboxSkillRuntimePreflightResult | None = None
    egress_decision: SandboxSkillEgressDecision | None = None
    command_templates: list[str] = Field(default_factory=list)
    normalized_output_paths: list[str] = Field(default_factory=list)
    derived_artifact_paths: list[str] = Field(default_factory=list)
    impact_scope: list[str] = Field(default_factory=list)
    operation_log: list[str] = Field(default_factory=list)
    command_results: list[SandboxCommandEntry] = Field(default_factory=list)
    execution_cwd: str = ""
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    blockers: list[SandboxSkillManifestFinding] = Field(default_factory=list)
    requested_by: str = "trainer"
    reason: str = ""


class SandboxSkillRunRequest(BaseModel):
    workspace_id: str
    path: str
    runtime_policy: SandboxSkillRuntimePolicy
    current_platform: Literal["windows", "macos", "linux"] | None = None
    include_manifest_scripts: bool = True
    dry_run: bool = True
    requested_by: str = "trainer"
    reason: str = ""


ResourceRecord.model_rebuild()
SandboxNode.model_rebuild()
