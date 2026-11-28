from __future__ import annotations

from datetime import datetime, timezone
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
    "research_brief",
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


TrainingLearningFamily = Literal["code", "theory", "literature"]


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


ProviderCredentialMode = Literal["workspace_secret", "ui_proxy", "local_no_auth"]


FolderRole = Literal[
    "empty_new_project",
    "existing_engineering",
    "algorithm_model",
    "idea_scratchpad",
    "learning_materials",
    "mixed_uncertain",
]


WorkspaceSubjectFamily = Literal["code", "literature"]


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
    ignore_system_proxy: bool = Field(default=False, alias="ignoreSystemProxy")
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
    # extra="allow" keeps the stored `_plan_revision` optimistic-lock anchor
    # alive through parse/dump round-trips, so every snapshot carries the
    # revision the client must base its next formal save on.
    model_config = ConfigDict(populate_by_name=True, extra="allow")

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
        from app.core.workspace_live_identity import (
            is_formal_plan_live_for_fill as leftover_formal_plan_is_live_for_fill,
        )
        from app.core.workspace_scope_runtime import (
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
    kind: Literal[
        "pdf",
        "epub",
        "docx",
        "pptx",
        "html",
        "image",
        "text",
        "markdown",
        "code",
        "url",
        "video",
    ]
    name: str
    source: str
    tags: list[str] = Field(default_factory=list)
    # Preserve the capture identity when a learner edits the visible library tags.
    capture_provenance_tags: list[str] = Field(default_factory=list)
    source_items: list[str] = Field(default_factory=list)
    content_language: str | None = None
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
    # TR-059: SHA-256 of the uploaded content, pinned at upload time so
    # evidence records can cite the exact content version they were built on.
    content_hash: str | None = None
    version_id: str | None = None
    # Fingerprint of the fetched URL text before the library adds a title
    # and creates its canonical document and version.
    indexed_source_hash: str | None = None
    # Canonical Markdown digest of this resource (workspace-relative POSIX
    # path). Search, the reader, training cards and agent context read this
    # document; the original file stays untouched next to it in the library.
    canonical_markdown_path: str | None = None
    canonical_original_path: str | None = None
    parser: str = ""
    parser_version: str = ""
    page_count: int | None = None
    slide_count: int | None = None
    # Trainer Library bookkeeping: workspace-relative POSIX paths of downloaded
    # copies of this resource's source (see ``app.resources.library``). Empty
    # for captures that were never downloaded into a library folder; kept in
    # sync by library folder renames and trash moves.
    library_paths: list[str] = Field(default_factory=list)

    @computed_field(return_type=ResourceTrustState)
    @property
    def trust_state(self) -> ResourceTrustState:
        return derive_resource_trust_state(
            self.trust_score,
            self.freshness,
            self.quality_flags,
        )


class ResourceCaptureResponse(ResourceRecord):
    """Browser-capture result: the landed resource plus the capture envelope.

    The full resource record stays on the wire (the library, memory summary and
    evidence lanes all read it), and the three capture-specific fields let the
    browser extension render "added" vs "already in the library" and offer the
    deep link back into the workbench without a second request.
    """

    resource_id: str = ""
    deduped: bool = False
    deep_link: str = ""
    # Workspace-relative path of the downloaded artifact when the capture asked
    # to save its source into a library folder (``download=true``).
    saved_path: str | None = None


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


class LibraryGroupNode(BaseModel):
    """One real folder in the Trainer Library group tree.

    ``path`` is relative to the library management root (``Trainer Library``),
    ``workspace_path`` is relative to the workspace root.
    """

    path: str
    name: str
    workspace_path: str = ""
    resource_count: int = 0
    children: list["LibraryGroupNode"] = Field(default_factory=list)


class LibraryGroupsResponse(BaseModel):
    """The real-folder group tree under the library management root."""

    workspace_id: str
    managed_root: str = ""
    exists: bool = False
    trash_root: str = ""
    total_resource_count: int = 0
    groups: list[LibraryGroupNode] = Field(default_factory=list)


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
