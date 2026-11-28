from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ...core.models import (
    CapabilityFlags,
    FirstLookSummary,
    LearningPlan,
    PlanStage,
    ProviderConfig,
    ProviderProtocol,
    ResourceRecord,
    ResponseLanguage,
    TaskSpec,
    UserProfile,
    WorkbenchSnapshot,
    WorkspaceUnderstandingSnapshot,
)

if TYPE_CHECKING:
    from ...llm.provider_service import ProviderService


class _CurrentWorkspaceIdCall(Protocol):
    def __call__(
        self,
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> str: ...


class _TrustedWriteWorkspaceIdCall(Protocol):
    def __call__(
        self,
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> str: ...


class _CurrentSnapshotCall(Protocol):
    def __call__(
        self,
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> WorkbenchSnapshot: ...


class _HydrateSnapshotCall(Protocol):
    def __call__(
        self,
        snapshot: WorkbenchSnapshot,
        *,
        response_language: str | None,
        answer_mode: str | None,
        scenario: str | None = None,
        learner_signal: str | None = None,
        message: str | None = None,
        current_file: Any = None,
        grounding_context: dict[str, object] | None = None,
        active_view: str | None = None,
        session_workspace_id: str | None = None,
        preserve_session_history: bool = False,
        preserve_turn_coaching_state: bool = False,
    ) -> WorkbenchSnapshot: ...


class _EffectiveResponseLanguageCall(Protocol):
    def __call__(
        self,
        workspace_id: str,
        requested: str | None,
        message: str | None = None,
    ) -> ResponseLanguage | None: ...


class _OperationReliabilityRecordCall(Protocol):
    def __call__(
        self,
        *,
        phase: str,
        outcome: str,
        request_id: str | None = None,
    ) -> dict[str, object]: ...


class _AttachPlanRuntimeStatusCall(Protocol):
    def __call__(
        self,
        *,
        workspace_id: str,
        snapshot: WorkbenchSnapshot,
        response_language: str | None,
        profile: UserProfile | None,
        coach_turn: dict[str, object] | None = None,
        agent_meta: dict[str, object] | None = None,
    ) -> dict[str, object]: ...


class _CoachSuggestedActionsCall(Protocol):
    def __call__(
        self,
        response_language: str | None,
        *,
        scenario: str = 'general',
        snapshot: WorkbenchSnapshot | None = None,
    ) -> list[dict[str, str]]: ...


class _EnsureCoachProviderReadyCall(Protocol):
    def __call__(
        self,
        coaching_service: ProviderService,
        *,
        response_language: str | None,
    ) -> None: ...


class _PersistPlanToSandboxCall(Protocol):
    def __call__(
        self,
        workspace_id: str,
        plan: LearningPlan | None,
        *,
        reason: str,
    ) -> None: ...


class _StatefulFocusAreaCall(Protocol):
    def __call__(
        self,
        task: TaskSpec | None,
        plan: LearningPlan | None,
        evaluation: Any = None,
        *,
        snapshot: WorkbenchSnapshot | None = None,
        runtime: dict[str, object] | None = None,
    ) -> str | None: ...


class _StructuredSuggestedActionsCall(Protocol):
    def __call__(
        self,
        labels: Sequence[str | dict[str, str]],
        *,
        response_language: str | None = None,
        scenario: str | None = None,
        focus_area: str | None = None,
    ) -> list[dict[str, object]]: ...



@dataclass(frozen=True, slots=True)
class RouterDeps:
    """Closure helpers owned by ``build_router`` and shared with extracted routers.

    Every member carries the signature of the function ``build_router_deps`` installs, so call sites in
    the extracted routers are checked against the real contract: a plain positional function is a
    ``Callable``; anything with keyword-only parameters or defaults is a ``Protocol`` with ``__call__``,
    which keeps those too.
    """

    current_workspace_id: _CurrentWorkspaceIdCall
    trusted_write_workspace_id: _TrustedWriteWorkspaceIdCall
    current_snapshot: _CurrentSnapshotCall
    refresh_workspace_sessions: Callable[[str], None]
    hydrate_snapshot: _HydrateSnapshotCall
    effective_response_language: _EffectiveResponseLanguageCall
    persist_first_look_summary: Callable[[str, FirstLookSummary], WorkspaceUnderstandingSnapshot]
    provider_config_from_payload: Callable[[dict[str, Any]], ProviderConfig | None]
    provider_api_key_from_payload: Callable[[dict[str, Any]], str | None]
    normalize_trainer_root_path: Callable[[str], str]
    routing_learner_state: Callable[[str], dict[str, object]]
    operation_reliability_record: _OperationReliabilityRecordCall
    provider_capabilities_from_payload: Callable[[dict[str, Any]], CapabilityFlags]
    provider_connection_type_from_payload: Callable[[dict[str, Any]], str | None]
    provider_protocol_from_payload: Callable[[dict[str, Any]], ProviderProtocol | None]
    provider_model_policy_detail: Callable[[ProviderConfig, str, str | None], str]
    provider_model_policy_violation: Callable[[ProviderConfig], str | None]
    require_sandbox_service: Callable[[], Any]
    apply_host_workspace_trust_attestation: Callable[[str, dict[str, Any]], None]
    workspace_learning_project_state: Callable[[str], dict[str, str]]
    active_plan_stage: Callable[[LearningPlan | None], PlanStage | None]
    attach_plan_runtime_status: _AttachPlanRuntimeStatusCall
    coach_suggested_actions: _CoachSuggestedActionsCall
    ensure_coach_provider_ready: _EnsureCoachProviderReadyCall
    frozen_plan_mutation_notice: Callable[[str | None], str]
    leftover_runtime_for_workspace: Callable[[str], tuple[LearningPlan | None, dict[str, object]]]
    persist_plan_to_sandbox: _PersistPlanToSandboxCall
    provider_is_live_usable: Callable[[ProviderService, dict[str, Any]], bool]
    stateful_focus_area: _StatefulFocusAreaCall
    structured_suggested_actions: _StructuredSuggestedActionsCall
    workspace_first_look_summary: Callable[[str], FirstLookSummary | None]
    sync_resource_record_to_sandbox: Callable[[str, ResourceRecord], ResourceRecord]
