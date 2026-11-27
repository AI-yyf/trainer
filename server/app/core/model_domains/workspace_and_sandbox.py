from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .foundations_and_provider import (
    LearningSignalOutcome,
    PlanStage,
    ProviderConfig,
    ProviderModelTokenLimit,
    ProviderProtocol,
    ProviderProtocolFamily,
    ResourceRecord,
    SourceIntakeDeclaration,
    TrainingLearningPhase,
    UserFeedbackKind,
    UserProfile,
    utc_now_iso,
)


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
    # Formal UI saves must provide expected_revision; legacy callers can opt
    # into the compatibility path until their transport is migrated.
    formal_plan_mutation: bool = False
    expected_revision: int | None = None


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


class ProviderProbeUsage(BaseModel):
    """§二十一: provider-reported usage from the live provider-test probe.

    Fields are echoed only when the provider itself reported them — Trainer
    never estimates or fabricates cost numbers.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    input_tokens: int | None = Field(default=None, alias="inputTokens")
    output_tokens: int | None = Field(default=None, alias="outputTokens")
    total_tokens: int | None = Field(default=None, alias="totalTokens")
    input_cost: float | None = Field(default=None, alias="inputCost")
    output_cost: float | None = Field(default=None, alias="outputCost")
    total_cost: float | None = Field(default=None, alias="totalCost")


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
    probe_usage: ProviderProbeUsage | None = Field(default=None, alias="probeUsage")


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
    incomplete: bool = False


class ResourceUploadRequest(BaseModel):
    session_id: str | None = None
    workspace_id: str | None = None
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
    content: str | None = None
    content_encoding: Literal["utf-8", "base64"] | None = None
    content_language: str | None = None
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


class ResourceCanonicalizeRequest(BaseModel):
    """Batch canonical-document stages for imported library resources."""

    session_id: str | None = None
    workspace_id: str | None = None
    resource_ids: list[str] = Field(default_factory=list)


class ResourceDigestRequest(BaseModel):
    """One-resource teaching digestion (总结/预备题目/直观案例/常见误区)."""

    session_id: str | None = None
    workspace_id: str | None = None
    resource_id: str


class ResourceCaptureRequest(BaseModel):
    """Browser-capture intake: one URL handed over by the Trainer Capture extension.

    The extension stays a pure data channel — it never injects scripts and never
    sends page bodies. The sidecar performs the controlled fetch and extraction
    for every kind (see ``app.resources.capture``).
    """

    session_id: str | None = None
    workspace_id: str | None = None
    url: str
    kind: Literal["web", "pdf", "github_repo", "gitee_repo", "gitlab_repo", "repo"]
    title: str | None = None
    capture_mode: Literal["snapshot", "link", "selection"] = "snapshot"
    # Selection captures still store the full readable body; the excerpt is kept
    # as capture metadata so the source stays honest after the page changes.
    selection: str | None = None
    # Optional learning-focus binding (a plan stage id). An unknown focus is
    # reported per-field instead of failing the whole capture.
    bind_focus_id: str | None = None
    bind_plan_id: str | None = None
    bind_plan_revision: int | None = None
    # Client-generated idempotency key: a retry with the same id replays the
    # original result instead of capturing twice.
    client_capture_id: str | None = None
    # GitHub only: also snapshot the repository's docs/ listing.
    include_docs: bool = False
    # Task two (Trainer Library folder lane): also download the original
    # artifact — the PDF bytes for ``kind=pdf`` or the whole repository for
    # ``kind=github_repo`` — into a real folder inside the workspace.
    download: bool = False
    # Workspace-relative target folder for the download; created on demand and
    # validated against the workspace authority boundary. Defaults to
    # ``Trainer Library`` under the workspace root.
    target_dir: str | None = None

    @model_validator(mode="after")
    def require_capture_url(self) -> "ResourceCaptureRequest":
        if not self.url.strip():
            raise ValueError("Capture requires a non-empty source URL.")
        if self.capture_mode == "selection" and not str(self.selection or "").strip():
            raise ValueError("Selection capture requires a non-empty excerpt.")
        if self.capture_mode != "snapshot" and self.download:
            raise ValueError("Only a full source capture can download an artifact.")
        if str(self.target_dir or "").strip() and not self.download:
            raise ValueError("target_dir requires download=true.")
        return self


class ResourceOrganizeRequest(BaseModel):
    """User-driven library organization for one already-registered resource.

    The actions reuse the existing resource record structure (name, tags,
    collection_path/collection_root) — no second organizational model is
    introduced.
    """

    session_id: str | None = None
    workspace_id: str | None = None
    resource_id: str
    action: Literal["rename", "set_tags", "set_group"]
    title: str | None = None
    tags: list[str] | None = None
    group: str | None = None

    @model_validator(mode="after")
    def require_action_payload(self) -> "ResourceOrganizeRequest":
        if not self.resource_id.strip():
            raise ValueError("Organize requires a resource_id.")
        if self.action == "rename" and not str(self.title or "").strip():
            raise ValueError("rename requires a non-empty title.")
        if self.action == "set_tags" and self.tags is None:
            raise ValueError("set_tags requires the tags list (use [] to clear).")
        if self.action == "set_group":
            # An empty group clears the grouping (the resource returns to the
            # library root); None means the caller sent nothing at all.
            if self.group is None:
                raise ValueError("set_group requires the group value (use \"\" to clear).")
        return self


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
    verification_python: str | None = None
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
    # Explicit phase lets a failed Verify record FSRS AGAIN; without it the
    # legacy pass-only behavior is retained (Try and Verify share this route).
    training_phase: TrainingLearningPhase | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    learner_deliverables: list[str] = Field(default_factory=list)
    expected_symbols: list[str] = Field(default_factory=list)


class EvaluateSnippetRequest(BaseModel):
    verification_python: str | None = None
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
    workspace_epoch: int = 0
    seq: int = 0


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


class SandboxCapabilityStatus(BaseModel):
    status: str
    summary: str = ""
    policy: str = ""
    reason_code: str = ""
    reasons: list[str] = Field(default_factory=list)
    network_facts: SandboxNetworkExecutionFacts | dict[str, Any] | None = None


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
