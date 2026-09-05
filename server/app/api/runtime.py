from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, Callable
from uuid import uuid4

from ..affect.service import AffectService
from ..core.event_ledger import EVENT_AGENT_TURN_CHECKPOINTED, EventLedgerService
from ..core.models import (
    ProjectProvisioning,
    ProviderConfig,
    ResourceRecord,
    TrainerRoot,
    TurnRequest,
    WorkbenchSnapshot,
    utc_now_iso,
)
from ..db.repository import TrainerRepository
from ..evaluator.service import EvaluatorService
from ..llm.provider_protocols import normalize_provider_protocol
from ..llm.provider_service import ProviderService
from ..memory.service import MemoryService
from ..memory.workspace_recovery import (
    PROVIDER_CAPABILITY_KEY,
    leftover_formal_plan_is_live_for_fill,
    stamp_produced_workspace_record,
)
from ..pedagogy.service import PedagogyService
from ..planner.service import PlannerService
from ..research.service import ResearchOrchestratorService
from ..resources.service import ResourceService
from ..specs.service import SpecService
from ..workspace.adoption_index import ProjectAdoptionIndexService, ProjectAdoptionJobRecord
from ..workspace.authority import PermissionLevel, WorkspaceAuthority
from ..workspace.provisioning import ProjectProvisioningService

if TYPE_CHECKING:
    from ..db.research_repository import ResearchRepository
    from ..sandbox.service import SandboxService
    from ..training.card_generator import CardGenerationService
    from ..training.card_router import CardRouterService

DEFAULT_WORKSPACE_ID = "workspace-default"
DEFAULT_WORKSPACE_NAME = "Trainer"
AGENT_CHECKPOINT_ID_PATTERN = re.compile(r"agent-turn-[0-9a-f]{32}")
_CHECKPOINT_REDACTED_VALUE = "[redacted]"
_CHECKPOINT_SECRET_KEY_PARTS = ("api_key", "apikey", "authorization", "password", "secret", "token")


def _checkpoint_safe_value(value: Any, *, depth: int = 0) -> Any:
    """Keep durable replay useful while excluding credentials and oversized blobs."""
    if depth > 12:
        return "[depth-limited]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            lowered = key.lower().replace("-", "_")
            if lowered == "data_base64" or any(part in lowered for part in _CHECKPOINT_SECRET_KEY_PARTS):
                result[key] = _CHECKPOINT_REDACTED_VALUE
            else:
                result[key] = _checkpoint_safe_value(raw_value, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_checkpoint_safe_value(item, depth=depth + 1) for item in value[:200]]
    if isinstance(value, str):
        return value if len(value) <= 32_000 else f"{value[:32_000]}\n[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if hasattr(value, "model_dump"):
        return _checkpoint_safe_value(value.model_dump(mode="json"), depth=depth + 1)
    return str(value)


def _checkpoint_current_file_context(request: Any) -> dict[str, Any] | None:
    current_file = getattr(request, "current_file", None)
    if current_file is None:
        return None
    return {
        "path": str(getattr(current_file, "path", "") or ""),
        "language_id": str(getattr(current_file, "language_id", "") or ""),
        "selection_range": str(getattr(current_file, "selection_range", "") or ""),
        "diagnostics": _checkpoint_safe_value(getattr(current_file, "diagnostics", []) or []),
    }


def _provider_service_cache_key(
    provider_config: ProviderConfig | None,
    api_key: str | None,
) -> str:
    api_key_fingerprint = hashlib.sha256((api_key or "").strip().encode("utf-8")).hexdigest()
    if provider_config is None:
        return f"__default__::{api_key_fingerprint}"
    try:
        provider_payload = provider_config.model_dump(mode="json", by_alias=True, exclude_none=True)
        # Route payloads materialize the default protocol while persisted
        # provider configs may leave it implicit. Both describe the same
        # transport and must share capability/test cache truth.
        provider_payload["protocol"] = normalize_provider_protocol(
            getattr(provider_config, "protocol", None)
        )
        serialized = json.dumps(
            provider_payload,
            ensure_ascii=True,
            sort_keys=True,
        )
    except Exception:
        serialized = repr(provider_config)
    return "::".join([serialized, api_key_fingerprint])


def _provider_capability_cache_key(
    provider_config: ProviderConfig | None,
    api_key: str | None,
) -> str:
    """Identify a tested transport while ignoring display-only provider metadata.

    Declared capability flags and requestDefaults must not segment the cache:
    a failed/unknown last-test has to invalidate the same transport that a
    prior success observed, or tools_ready can stick from a sibling key.
    """

    api_key_fingerprint = hashlib.sha256((api_key or "").strip().encode("utf-8")).hexdigest()
    if provider_config is None:
        return f"__default__::{api_key_fingerprint}"
    try:
        full_payload = provider_config.model_dump(mode="json", by_alias=True, exclude_none=True)
        payload = {
            "baseUrl": str(full_payload.get("baseUrl") or "").strip().rstrip("/"),
            "model": str(full_payload.get("model") or "").strip(),
            "protocol": normalize_provider_protocol(getattr(provider_config, "protocol", None)),
        }
        serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    except Exception:
        serialized = repr(provider_config)
    return "::".join([serialized, api_key_fingerprint])


def _provider_capability_transport_markers(
    provider_config: ProviderConfig | None,
    api_key: str | None,
) -> tuple[str, str, str]:
    """Return (baseUrl, model, api_key_fingerprint) used to invalidate sibling keys."""

    api_key_fingerprint = hashlib.sha256((api_key or "").strip().encode("utf-8")).hexdigest()
    if provider_config is None:
        return ("", "", api_key_fingerprint)
    try:
        full_payload = provider_config.model_dump(mode="json", by_alias=True, exclude_none=True)
        base_url = str(full_payload.get("baseUrl") or "").strip().rstrip("/")
        model = str(full_payload.get("model") or "").strip()
    except Exception:
        base_url = str(getattr(provider_config, "base_url", "") or "").strip().rstrip("/")
        model = str(getattr(provider_config, "model", "") or "").strip()
    return (base_url, model, api_key_fingerprint)


@dataclass
class SessionState:
    session_id: str
    workspace_id: str
    workspace_name: str
    snapshot: WorkbenchSnapshot


@dataclass
class TrainerRuntime:
    repository: TrainerRepository
    provider_service: ProviderService
    planner_service: PlannerService
    memory_service: MemoryService
    resource_service: ResourceService
    spec_service: SpecService
    evaluator_service: EvaluatorService
    pedagogy_service: PedagogyService = field(default_factory=PedagogyService)
    affect_service: AffectService = field(default_factory=AffectService)
    research_repository: ResearchRepository | None = None
    research_service: ResearchOrchestratorService = field(default_factory=ResearchOrchestratorService)
    research_network_fetch_enabled: bool = False
    sessions: dict[str, SessionState] = field(default_factory=dict)
    provider_config: ProviderConfig | None = None
    provider_api_key: str | None = None
    provider_service_cache: dict[str, ProviderService] = field(default_factory=dict)
    # Capability observations are request-gating truth, not provider declarations.
    # Keys include only a serialized provider config and a one-way API-key digest.
    provider_capability_cache: dict[str, dict[str, str]] = field(default_factory=dict)
    workspace_paths: dict[str, str] = field(default_factory=dict)
    workspace_authorities: dict[str, "WorkspaceAuthority"] = field(default_factory=dict)
    # Workspace → monotonically increasing snapshot revision for slim payloads.
    snapshot_revisions: dict[str, int] = field(default_factory=dict)
    sandbox_root_overrides: dict[str, str] = field(default_factory=dict)
    resource_organization_history: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Workspace → pending organize_resources proposal (proposal-first gate).
    # Direct API resourceOrganizationConfirmed without a prior proposal must not commit.
    resource_organization_pending: dict[str, dict[str, Any]] = field(default_factory=dict)
    sandbox_service: SandboxService | None = None
    card_generation_service: CardGenerationService | None = None
    card_router_service: CardRouterService | None = None
    project_provisioning_service: ProjectProvisioningService | None = None
    project_adoption_index_service: ProjectAdoptionIndexService | None = None
    event_ledger: EventLedgerService | None = None
    steer_queues: dict[str, list[str]] = field(default_factory=dict)
    sandbox_operation_log: dict[str, dict[str, Any]] = field(default_factory=dict)
    requested_workspace_files: dict[str, list[str]] = field(default_factory=dict)
    _steer_guard: Lock = field(default_factory=Lock, repr=False, compare=False)

    def enqueue_steer_message(self, session_id: str, text: str) -> bool:
        key = str(session_id or "").strip()
        cleaned = str(text or "").strip()
        if not key or not cleaned:
            return False
        with self._steer_guard:
            self.steer_queues.setdefault(key, []).append(cleaned)
        return True

    def remember_requested_workspace_file(self, workspace_id: str | None, path: str) -> None:
        key = str(workspace_id or "").strip()
        relative = str(path or "").replace("\\", "/").lstrip("./").strip()
        if not key or not relative:
            return
        current = self.requested_workspace_files.setdefault(key, [])
        if relative not in current:
            current.append(relative)

    def requested_workspace_file_paths(self, workspace_id: str | None) -> list[str]:
        key = str(workspace_id or "").strip()
        if not key:
            return []
        return list(self.requested_workspace_files.get(key) or [])

    def fulfill_requested_workspace_files(
        self, workspace_id: str | None, present: object = None
    ) -> None:
        key = str(workspace_id or "").strip()
        if not key:
            return
        pending = self.requested_workspace_files.get(key) or []
        if not pending:
            return
        present_paths = {
            str(item or "").replace("\\", "/").lstrip("./").strip()
            for item in (present or [])
            if str(item or "").strip()
        }
        remaining = [path for path in pending if path not in present_paths]
        if remaining:
            self.requested_workspace_files[key] = remaining
        else:
            self.requested_workspace_files.pop(key, None)

    def drain_steer_messages(self, session_id: str) -> list[str]:
        key = str(session_id or "").strip()
        if not key:
            return []
        with self._steer_guard:
            queued = self.steer_queues.get(key) or []
            self.steer_queues[key] = []
        return [str(item).strip() for item in queued if str(item).strip()]

    def __post_init__(self) -> None:
        if self.provider_config is not None or self.provider_api_key is not None:
            self.provider_service = ProviderService(
                config=self.provider_config,
                api_key=self.provider_api_key,
            )
        if self.research_repository is not None:
            self.research_service = ResearchOrchestratorService(
                repository=self.research_repository,
                network_enabled=self.research_network_fetch_enabled,
            )
        if self.project_provisioning_service is None:
            self.project_provisioning_service = ProjectProvisioningService(
                repository=self.repository,
                memory_service=self.memory_service,
                planner_service=self.planner_service,
            )
        if self.project_adoption_index_service is None:
            self.project_adoption_index_service = ProjectAdoptionIndexService()

    def _persist_session(self, state: SessionState) -> None:
        self.repository.save_session(
            state.session_id,
            state.workspace_id,
            {
                "session_id": state.session_id,
                "workspace_id": state.workspace_id,
                "workspace_name": state.workspace_name,
                "snapshot": state.snapshot.model_dump(mode="json"),
            },
        )

    def _restore_session(self, payload: dict[str, Any]) -> SessionState | None:
        session_id = str(payload.get("session_id") or "").strip()
        workspace_id = self.repository.resolve_context_id(payload.get("workspace_id")) or str(
            payload.get("workspace_id") or ""
        ).strip()
        workspace_name = str(payload.get("workspace_name") or DEFAULT_WORKSPACE_NAME).strip() or DEFAULT_WORKSPACE_NAME
        snapshot_payload = payload.get("snapshot")
        if not session_id or not workspace_id or not isinstance(snapshot_payload, dict):
            return None
        snapshot = WorkbenchSnapshot.model_validate(snapshot_payload)
        snapshot.context_id = workspace_id
        snapshot.memory = self.memory_service.snapshot(workspace_id)
        snapshot.profile = self.repository.get_profile(workspace_id)
        self.hydrate_plan_context(snapshot, workspace_id)
        provisioning = self.repository.get_project_provisioning(workspace_id)
        if provisioning is not None and provisioning.agent_session_id == session_id:
            self.register_workspace_path(workspace_id, provisioning.project_path)
        return SessionState(
            session_id=session_id,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            snapshot=snapshot,
        )

    def start_session(self, workspace_id: str, workspace_name: str) -> SessionState:
        workspace_id = self.repository.resolve_context_id(workspace_id) or workspace_id
        session_id = f"session-{uuid4().hex[:10]}"
        snapshot = WorkbenchSnapshot(
            contextId=workspace_id,
            memory=self.memory_service.snapshot(workspace_id),
        )
        self.hydrate_plan_context(snapshot, workspace_id)
        state = SessionState(
            session_id=session_id,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            snapshot=snapshot,
        )
        self.sessions[session_id] = state
        self._persist_session(state)
        return state

    def get_session(self, session_id: str) -> SessionState | None:
        return self.sessions.get(session_id)

    def latest_session(self) -> SessionState | None:
        latest_session_id = next(reversed(self.sessions), None)
        if latest_session_id is None:
            return None
        return self.sessions[latest_session_id]

    def save_session_state(self, session_id: str) -> None:
        state = self.sessions.get(session_id)
        if state is None:
            return
        self._persist_session(state)

    def refresh_workspace_sessions(self, workspace_id: str) -> int:
        """Refresh active session snapshots after a resource or memory mutation."""

        resolved_workspace_id = self.repository.resolve_context_id(workspace_id) or workspace_id
        matching_states = [
            state for state in self.sessions.values() if state.workspace_id == resolved_workspace_id
        ]
        if not matching_states:
            return 0

        # Read workspace-level state once; each session receives independent copies so
        # later session-local mutations cannot alter another session's snapshot.
        memory = self.memory_service.snapshot(resolved_workspace_id)
        profile = self.repository.get_profile(resolved_workspace_id)
        workspace_snapshot = WorkbenchSnapshot(
            contextId=resolved_workspace_id,
            memory=memory,
            profile=profile,
        )
        self.hydrate_plan_context(workspace_snapshot, resolved_workspace_id)

        for state in matching_states:
            state.snapshot.context_id = resolved_workspace_id
            state.snapshot.memory = deepcopy(workspace_snapshot.memory)
            state.snapshot.profile = deepcopy(workspace_snapshot.profile)
            state.snapshot.plan = deepcopy(workspace_snapshot.plan)
            state.snapshot.global_plan = deepcopy(workspace_snapshot.global_plan)
            state.snapshot.project_plan_link = deepcopy(workspace_snapshot.project_plan_link)
            self.save_session_state(state.session_id)
        return len(matching_states)

    def postprocess_indexed_resource(
        self,
        workspace_id: str,
        indexed: ResourceRecord,
        *,
        refresh_sessions: bool = True,
    ) -> tuple[ResourceRecord, dict[str, Any]]:
        """Run the canonical post-index resource closure.

        Resource ingestion is intentionally shared by the HTTP route and the
        Agent URL-import tool. Keeping this closure here prevents one path from
        silently skipping sandbox sync, teaching assets, workspace
        understanding, research references, or live session refresh.
        """

        resolved_workspace_id = self.repository.resolve_context_id(workspace_id) or workspace_id
        summary: dict[str, Any] = {
            "sandbox_synced": False,
            "teaching_assets_created": 0,
            "workspace_understanding_refreshed": False,
            "research_references_recorded": 0,
            "sessions_refreshed": 0,
        }

        if self.sandbox_service is not None:
            set_resolver = getattr(self.sandbox_service, "set_workspace_sandbox_root_resolver", None)
            if callable(set_resolver):
                set_resolver(self.resolve_workspace_sandbox_root)
            before_path = str(indexed.sandbox_path or "")
            indexed = self.sandbox_service.sync_resource(resolved_workspace_id, indexed)
            self.repository.save_resource(resolved_workspace_id, indexed)
            summary["sandbox_synced"] = bool(
                indexed.sandbox_path
                and (str(indexed.sandbox_path) != before_path or not before_path)
            )

        assets = self.memory_service.record_teaching_assets_from_resource(
            resolved_workspace_id,
            indexed,
        )
        summary["teaching_assets_created"] = len(assets or [])

        all_resource_ids = [
            item.id
            for item in self.repository.list_resources(resolved_workspace_id)
            if item.index_status == "indexed"
        ]
        if all_resource_ids:
            workspace_context = self.resource_service.build_workspace_understanding_context(
                resolved_workspace_id,
                all_resource_ids,
            )
            if workspace_context:
                workspace_understanding = self.pedagogy_service.build_workspace_understanding(
                    request=TurnRequest(
                        workspace_id=resolved_workspace_id,
                        message="Refresh workspace understanding from indexed resources.",
                        resource_ids=all_resource_ids,
                        intent="coach",
                    ),
                    memory_snapshot=self.memory_service.snapshot(resolved_workspace_id),
                    resource_context=workspace_context,
                )
                if workspace_understanding is not None:
                    self.memory_service.save_workspace_understanding(
                        resolved_workspace_id,
                        workspace_understanding,
                    )
                    summary["workspace_understanding_refreshed"] = True

        if indexed.knowledge_fragments and self.resource_service.is_curatable_resource(indexed):
            focus_area = indexed.name.strip() or indexed.kind
            for fragment in indexed.knowledge_fragments[:2]:
                if not isinstance(fragment, dict):
                    continue
                self.research_service.record_background_reference(
                    workspace_id=resolved_workspace_id,
                    focus_area=focus_area,
                    source=str(fragment.get("source", indexed.canonical_source or indexed.source)),
                    content=str(fragment.get("snippet", indexed.summary or indexed.name)),
                    trust_score=float(fragment.get("trust_score", indexed.trust_score) or indexed.trust_score),
                    tags=[
                        "resource-index",
                        indexed.kind,
                        *[str(flag) for flag in indexed.quality_flags[:2]],
                    ],
                )
                summary["research_references_recorded"] += 1

        if refresh_sessions:
            summary["sessions_refreshed"] = self.refresh_workspace_sessions(resolved_workspace_id)
        return indexed, summary

    @staticmethod
    def _validate_agent_checkpoint_id(checkpoint_id: str) -> str:
        normalized = checkpoint_id.strip()
        if not AGENT_CHECKPOINT_ID_PATTERN.fullmatch(normalized):
            raise ValueError("Checkpoint id is invalid.")
        return normalized

    @staticmethod
    def _validate_checkpoint_workspace_id(workspace_id: str) -> str:
        normalized = workspace_id.strip()
        if not normalized or len(normalized) > 256 or "\x00" in normalized:
            raise ValueError("Workspace id is invalid.")
        return normalized

    def record_agent_turn_checkpoint(
        self,
        *,
        state: SessionState,
        request: Any,
        assistant_reply: Any,
        agent_meta: dict[str, Any],
        coach_turn_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Persist the completed turn after all visible-response repairs have run."""
        checkpoint_id = f"agent-turn-{uuid4().hex}"
        created_at = utc_now_iso()
        context_id = str(getattr(state.snapshot, "context_id", "") or state.workspace_id).strip()
        current_task = getattr(state.snapshot, "current_task", None)
        plan = getattr(state.snapshot, "plan", None)
        raw_turn_summary = (coach_turn_data or {}).get("coach_turn")
        model_dump = getattr(raw_turn_summary, "model_dump", None)
        if callable(model_dump):
            turn_summary = model_dump(mode="json")
        elif isinstance(raw_turn_summary, dict):
            turn_summary = dict(raw_turn_summary)
        else:
            turn_summary = {}
        steps = agent_meta.get("steps") if isinstance(agent_meta.get("steps"), list) else []
        tool_events = (
            agent_meta.get("tool_events") if isinstance(agent_meta.get("tool_events"), list) else []
        )
        stop_reason = str(agent_meta.get("stop_reason") or "").strip()
        recovery = {
            "stop_reason": stop_reason,
            "recovered_stop_reason": str(agent_meta.get("recovered_stop_reason") or "").strip(),
            "fell_back": bool(agent_meta.get("fell_back")),
            "local_sequence_fallback": bool(agent_meta.get("local_sequence_fallback")),
            "resume_thread": str(agent_meta.get("resume_thread") or "").strip(),
            "next_step": str(agent_meta.get("next_step") or "").strip(),
            "recovery_available": bool(
                str(agent_meta.get("resume_thread") or "").strip()
                or str(agent_meta.get("next_step") or "").strip()
            ),
        }
        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "version": 1,
            "created_at": created_at,
            "workspace_id": state.workspace_id,
            "session_id": state.session_id,
            "context_id": context_id,
            "session": {
                "session_id": state.session_id,
                "workspace_name": state.workspace_name,
            },
            "context": {
                "active_view": str(getattr(request, "active_view", "") or ""),
                "active_panel": str(getattr(state.snapshot, "active_panel", "") or ""),
                "plan_id": str(getattr(plan, "id", "") or ""),
                "current_task": {
                    "id": str(getattr(current_task, "id", "") or ""),
                    "title": str(getattr(current_task, "title", "") or ""),
                },
                "current_file": _checkpoint_current_file_context(request),
            },
            "request": {
                "message": str(getattr(request, "message", "") or ""),
                "response_language": str(getattr(request, "response_language", "") or ""),
                "answer_mode": str(getattr(request, "answer_mode", "") or ""),
                "resource_ids": _checkpoint_safe_value(getattr(request, "resource_ids", []) or []),
                "attachments": [
                    {
                        "id": str(getattr(item, "id", "") or ""),
                        "kind": str(getattr(item, "kind", "") or ""),
                        "name": str(getattr(item, "name", "") or ""),
                    }
                    for item in list(getattr(request, "attachments", []) or [])[:20]
                ],
            },
            "trace": {
                "steps": _checkpoint_safe_value(steps),
                "tool_events": _checkpoint_safe_value(tool_events),
            },
            "final": {
                "message_id": str(getattr(assistant_reply, "id", "") or ""),
                "content": str(getattr(assistant_reply, "content", "") or ""),
                "created_at": str(getattr(assistant_reply, "created_at", "") or ""),
                "coach_turn": _checkpoint_safe_value(turn_summary),
                "agent_meta": _checkpoint_safe_value(agent_meta),
            },
            "recovery": recovery,
        }
        safe_checkpoint = _checkpoint_safe_value(checkpoint)
        self.repository.save_agent_turn_checkpoint(
            checkpoint_id=checkpoint_id,
            workspace_id=state.workspace_id,
            session_id=state.session_id,
            context_id=context_id,
            created_at=created_at,
            payload=safe_checkpoint,
        )
        if self.event_ledger is not None:
            self.event_ledger.record_event(
                EVENT_AGENT_TURN_CHECKPOINTED,
                actor="trainer",
                scope="agent_checkpoint",
                project_id=state.workspace_id,
                payload_ref={
                    "checkpoint_id": checkpoint_id,
                    "session_id": state.session_id,
                    "stop_reason": stop_reason,
                },
                after_state_ref={"recovery_available": recovery["recovery_available"]},
                reversibility="append_only",
                audit_note="Persisted a replay-only agent turn checkpoint.",
            )
        return safe_checkpoint

    def list_agent_turn_checkpoints(
        self,
        *,
        workspace_id: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        requested_workspace_id = self._validate_checkpoint_workspace_id(workspace_id)
        resolved_workspace_id = self.repository.resolve_context_id(requested_workspace_id) or requested_workspace_id
        if session_id and "\x00" in session_id:
            raise ValueError("Session id is invalid.")
        records = self.repository.list_agent_turn_checkpoints(
            resolved_workspace_id,
            session_id=session_id.strip() if session_id else None,
            limit=limit,
        )
        return [
            {
                "checkpoint_id": str(record.get("checkpoint_id") or ""),
                "created_at": str(record.get("created_at") or ""),
                "session_id": str(record.get("session_id") or ""),
                "context_id": str(record.get("context_id") or ""),
                "stop_reason": str(
                    (record.get("recovery") or {}).get("stop_reason")
                    if isinstance(record.get("recovery"), dict)
                    else ""
                ),
                "next_step": str(
                    (record.get("recovery") or {}).get("next_step")
                    if isinstance(record.get("recovery"), dict)
                    else ""
                ),
                "recovery_available": bool(
                    (record.get("recovery") or {}).get("recovery_available")
                    if isinstance(record.get("recovery"), dict)
                    else False
                ),
            }
            for record in records
        ]

    def read_agent_turn_checkpoint(
        self,
        *,
        checkpoint_id: str,
        workspace_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_id = self._validate_agent_checkpoint_id(checkpoint_id)
        requested_workspace_id = self._validate_checkpoint_workspace_id(workspace_id)
        resolved_workspace_id = self.repository.resolve_context_id(requested_workspace_id) or requested_workspace_id
        checkpoint = self.repository.load_agent_turn_checkpoint(normalized_id, resolved_workspace_id)
        if checkpoint is None:
            return None
        if (
            str(checkpoint.get("checkpoint_id") or "") != normalized_id
            or str(checkpoint.get("workspace_id") or "") != resolved_workspace_id
        ):
            raise ValueError("Checkpoint data is invalid.")
        if session_id and str(checkpoint.get("session_id") or "") != session_id.strip():
            raise PermissionError("Checkpoint does not belong to this session.")
        return checkpoint

    def replay_agent_turn_checkpoint(
        self,
        *,
        checkpoint_id: str,
        workspace_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return a stored trace only. This method never invokes providers or tools."""
        checkpoint = self.read_agent_turn_checkpoint(
            checkpoint_id=checkpoint_id,
            workspace_id=workspace_id,
            session_id=session_id,
        )
        if checkpoint is None:
            return None
        return {
            "mode": "stored_trace",
            "replayed": True,
            "executed": False,
            "checkpoint": checkpoint,
        }

    def prepare_agent_turn_resume(
        self,
        *,
        checkpoint_id: str,
        workspace_id: str,
        session_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Restore local session availability and return the saved next step, without execution."""
        checkpoint = self.read_agent_turn_checkpoint(
            checkpoint_id=checkpoint_id,
            workspace_id=workspace_id,
            session_id=session_id,
        )
        if checkpoint is None:
            return None
        checkpoint_session_id = str(checkpoint.get("session_id") or "").strip()
        persisted_session = self.repository.load_session(checkpoint_session_id)
        if persisted_session is None:
            raise ValueError("The checkpoint session is no longer available.")
        restored = self._restore_session(persisted_session)
        if restored is None or restored.workspace_id != str(checkpoint.get("workspace_id") or ""):
            raise ValueError("The checkpoint session cannot be restored safely.")
        self.sessions[restored.session_id] = restored
        raw_recovery = checkpoint.get("recovery")
        recovery: dict[str, Any] = raw_recovery if isinstance(raw_recovery, dict) else {}
        return {
            "checkpoint_id": str(checkpoint.get("checkpoint_id") or ""),
            "session_id": restored.session_id,
            "workspace_id": restored.workspace_id,
            "context_id": str(checkpoint.get("context_id") or ""),
            "resume_thread": str(recovery.get("resume_thread") or ""),
            "next_step": str(recovery.get("next_step") or ""),
            "requires_new_turn": True,
            "executed": False,
        }

    def hydrate_plan_context(self, snapshot: WorkbenchSnapshot, workspace_id: str) -> WorkbenchSnapshot:
        """Refresh the authoritative project plan, global plan, and their current link.

        Empty / recovered-without-plan restore must not resurrect leftover stored
        formal plan as live. Live only when recovered runtime already carries a
        matching plan_id (leftover stays stored either way).
        """
        latest = stamp_produced_workspace_record(
            self.repository.get_latest_plan(workspace_id),
            workspace_id,
        )
        leftover_plan, leftover_runtime, _leftover_task = self.memory_service._leftover_persist_context(
            workspace_id
        )
        # leftover_formal_plan_is_live_for_fill treats no-runtime as first-persist
        # live; hydrate/start must fail closed instead of auto-binding leftover.
        live_plan = bool(leftover_runtime) and leftover_formal_plan_is_live_for_fill(
            plan=leftover_plan or latest,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        )
        snapshot.plan = latest if live_plan else None
        snapshot.global_plan = self.repository.get_default_global_plan()
        current_plan = snapshot.plan
        snapshot.project_plan_link = (
            self.repository.get_global_plan_project_link(
                snapshot.global_plan.id,
                workspace_id,
                current_plan.id,
            )
            if snapshot.global_plan is not None and current_plan is not None and current_plan.id
            else None
        )
        return snapshot

    def resolve_workspace_id(self, session_id: str | None = None, workspace_id: str | None = None) -> str:
        explicit_workspace_id = (workspace_id or "").strip()
        if explicit_workspace_id:
            return self.repository.resolve_context_id(explicit_workspace_id) or explicit_workspace_id
        if session_id:
            state = self.get_session(session_id)
            if state:
                return state.workspace_id
            restored_payload = self.repository.load_session(session_id)
            if restored_payload:
                restored = self._restore_session(restored_payload)
                if restored is not None:
                    self.sessions[session_id] = restored
                    return restored.workspace_id
        latest = self.latest_session()
        if latest:
            return latest.workspace_id
        return DEFAULT_WORKSPACE_ID

    def restore_latest_session_for_workspace(self, workspace_id: str) -> SessionState | None:
        workspace_id = self.repository.resolve_context_id(workspace_id) or workspace_id
        preferred_session_id = self.memory_service.latest_session_id_for_workspace(workspace_id)
        if preferred_session_id:
            restored_payload = self.repository.load_session(preferred_session_id)
            if restored_payload:
                restored = self._restore_session(restored_payload)
                if restored is not None:
                    self.sessions[restored.session_id] = restored
                    return restored
        restored_payload = self.repository.load_latest_session_for_workspace(workspace_id)
        if not restored_payload:
            return None
        restored = self._restore_session(restored_payload)
        if restored is None:
            return None
        self.sessions[restored.session_id] = restored
        return restored

    def next_snapshot_revision(self, workspace_id: str) -> int:
        """Bump and return the workspace snapshot revision (slim-payload support)."""
        next_revision = self.snapshot_revisions.get(workspace_id, 0) + 1
        self.snapshot_revisions[workspace_id] = next_revision
        return next_revision

    def snapshot_revision(self, workspace_id: str) -> int:
        return self.snapshot_revisions.get(workspace_id, 0)

    def ensure_session(
        self,
        session_id: str | None,
        workspace_id: str | None = None,
        workspace_name: str = DEFAULT_WORKSPACE_NAME,
    ) -> SessionState:
        explicit_workspace_id = self.repository.resolve_context_id(workspace_id) or (workspace_id or "").strip()
        if session_id and session_id in self.sessions:
            state = self.sessions[session_id]
            if not explicit_workspace_id or state.workspace_id == explicit_workspace_id:
                return state
        if session_id:
            restored_payload = self.repository.load_session(session_id)
            if restored_payload:
                restored = self._restore_session(restored_payload)
                if restored is not None and (
                    not explicit_workspace_id or restored.workspace_id == explicit_workspace_id
                ):
                    self.sessions[session_id] = restored
                    return restored
        return self.start_session(explicit_workspace_id or DEFAULT_WORKSPACE_ID, workspace_name)

    def provision_project_adoption(
        self,
        *,
        workspace_id: str | None,
        project_path: str,
        project_name: str,
        context_id: str | None = None,
        root_id: str | None = None,
        root_path: str | None = None,
    ) -> ProjectProvisioning:
        """Create or restore the durable project lane behind an explicit adoption."""
        if self.project_provisioning_service is None:
            raise RuntimeError("Project provisioning service is unavailable.")
        provisioning = self.project_provisioning_service.provision(
            workspace_id=workspace_id,
            context_id=context_id,
            root_id=root_id,
            root_path=root_path,
            project_path=project_path,
            project_name=project_name,
        )
        self.register_workspace_path(provisioning.context_id, provisioning.project_path)
        state = self.ensure_session(
            provisioning.agent_session_id,
            workspace_id=provisioning.context_id,
            workspace_name=provisioning.project_name,
        )
        state.workspace_name = provisioning.project_name
        state.snapshot.profile = self.repository.get_profile(provisioning.context_id)
        state.snapshot.memory = self.memory_service.snapshot(provisioning.context_id)
        self.hydrate_plan_context(state.snapshot, provisioning.context_id)
        self._persist_session(state)
        return provisioning

    def get_project_provisioning(self, workspace_id: str) -> ProjectProvisioning | None:
        if self.project_provisioning_service is None:
            return None
        return self.project_provisioning_service.get(workspace_id)

    def start_project_adoption_job(
        self,
        *,
        job_id: str | None = None,
        workspace_id: str,
        discovery_id: str,
        project_path: str,
        project_name: str,
        root_id: str | None,
        root_path: str,
        context_id: str | None,
        finalize: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> ProjectAdoptionJobRecord:
        if self.project_adoption_index_service is None:
            raise RuntimeError("Project adoption index service is unavailable.")
        return self.project_adoption_index_service.start(
            job_id=job_id,
            workspace_id=workspace_id,
            discovery_id=discovery_id,
            project_path=project_path,
            project_name=project_name,
            root_id=root_id,
            root_path=root_path,
            context_id=context_id,
            finalize=finalize,
        )

    def get_project_adoption_job(
        self,
        *,
        root_path: str,
        job_id: str,
    ) -> ProjectAdoptionJobRecord | None:
        if self.project_adoption_index_service is None:
            return None
        return self.project_adoption_index_service.get(root_path=root_path, job_id=job_id)

    def project_identity_payload(
        self,
        provisioning: ProjectProvisioning,
        *,
        idempotency: str,
        pending: bool = False,
        reconcile_state: str = "current",
    ) -> dict[str, object]:
        return {
            "rootId": provisioning.root_id,
            "canonicalRootPath": provisioning.root_path,
            "projectId": provisioning.project_id,
            "contextId": provisioning.context_id,
            "canonicalProjectPath": provisioning.project_path,
            "legacyWorkspaceId": provisioning.legacy_workspace_id,
            "legacyAliases": self.repository.list_context_aliases(provisioning.context_id),
            "revisions": {
                "root": provisioning.root_revision,
                "project": provisioning.project_revision,
                "context": provisioning.revision,
            },
            "idempotency": {
                "state": idempotency,
                "contextId": provisioning.context_id,
            },
            "pending": pending,
            "reconcile": {
                "root": {"state": reconcile_state, "rootPath": provisioning.root_path},
                "project": {"state": reconcile_state, "projectPath": provisioning.project_path},
            },
        }

    def reconcile_trainer_root(self, root_id: str, root_path: str):
        normalized_path = str(Path(root_path).expanduser().resolve(strict=False))
        return self.repository.reconcile_trainer_root(root_id, normalized_path)

    def register_trainer_root(self, *, root_id: str | None, root_path: str):
        normalized_path = str(Path(root_path).expanduser().resolve(strict=False))
        if not Path(normalized_path).is_dir():
            raise ValueError("The selected Trainer workspace root must be an available directory.")
        normalized_id = str(root_id or "").strip() or f"root-{uuid4().hex}"
        return self.repository.register_trainer_root(
            TrainerRoot(
                rootId=normalized_id,
                rootPath=normalized_path,
                displayName=Path(normalized_path).name or "Trainer Workspace",
            )
        )

    def reconcile_project_location(
        self,
        *,
        root_id: str,
        project_id: str,
        project_path: str,
        project_name: str | None = None,
    ):
        normalized_path = str(Path(project_path).expanduser().resolve(strict=False))
        updated = self.repository.reconcile_project_location(
            root_id=root_id,
            project_id=project_id,
            project_path=normalized_path,
            project_name=project_name,
        )
        context = self.repository.get_project_context_for_project(updated.project_id)
        if context is not None:
            self.register_workspace_path(context.context_id, updated.project_path)
        return updated

    def overlay_last_test_on_service(self, provider_service: ProviderService) -> ProviderService:
        """Stamp last-test capability truth onto a live ProviderService.

        Default OpenAI-compatible templates pin ``tools`` false. A successful
        connection test must overlay that pin on the default runtime service
        used by coach send and generate-card, not only on a cache clone.
        """
        config = getattr(provider_service, "_config", None)
        api_key = getattr(provider_service, "_api_key", None)
        states = self.provider_capability_cache.get(
            _provider_capability_cache_key(config, api_key),
        )
        if not states:
            return provider_service
        replace_observed = getattr(provider_service, "replace_observed_capability_states", None)
        if callable(replace_observed):
            replace_observed(states)
            return provider_service
        apply_observed = getattr(provider_service, "apply_observed_capability_states", None)
        if callable(apply_observed):
            apply_observed(states)
        return provider_service

    def _overlay_last_test_on_matching_services(
        self,
        provider_config: ProviderConfig,
        api_key: str | None,
        states: dict[str, str],
    ) -> None:
        target_key = _provider_capability_cache_key(provider_config, api_key)
        seen: set[int] = set()
        for service in (self.provider_service, *self.provider_service_cache.values()):
            marker = id(service)
            if marker in seen:
                continue
            seen.add(marker)
            config = getattr(service, "_config", None)
            service_key = getattr(service, "_api_key", None)
            if _provider_capability_cache_key(config, service_key) != target_key:
                continue
            replace_observed = getattr(service, "replace_observed_capability_states", None)
            if callable(replace_observed):
                replace_observed(states)
                continue
            apply_observed = getattr(service, "apply_observed_capability_states", None)
            if callable(apply_observed):
                apply_observed(states)

    def provider_service_for(
        self,
        provider_config: ProviderConfig | None,
        api_key: str | None,
    ) -> ProviderService:
        if provider_config is None and api_key is None:
            return self.overlay_last_test_on_service(self.provider_service)

        key = _provider_service_cache_key(provider_config, api_key)
        cached = self.provider_service_cache.get(key)
        if cached is not None:
            return self.overlay_last_test_on_service(cached)

        created = ProviderService(config=provider_config, api_key=api_key)
        self.provider_service_cache[key] = created
        if len(self.provider_service_cache) > 16:
            oldest_key = next(iter(self.provider_service_cache))
            if oldest_key != key:
                self.provider_service_cache.pop(oldest_key, None)
        return self.overlay_last_test_on_service(created)

    def remember_provider_capability_test(
        self,
        provider_config: ProviderConfig,
        api_key: str | None,
        result: Any,
    ) -> None:
        """Cache observed provider capabilities without retaining credentials."""

        key = _provider_capability_cache_key(provider_config, api_key)
        live_ok = bool(getattr(result, "ok", False))
        evidence = getattr(result, "capability_evidence", None) or []
        if isinstance(result, dict):
            live_ok = bool(result.get("ok"))
            evidence = result.get("capability_evidence") or result.get("capabilityEvidence") or []
        states: dict[str, str] = {
            "connection": "verified" if live_ok else "unverified",
        }
        if live_ok:
            for item in evidence:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip().lower()
                    state = str(item.get("state") or "").strip().lower()
                else:
                    name = str(getattr(item, "name", "") or "").strip().lower()
                    state = str(getattr(item, "state", "") or "").strip().lower()
                if name and state:
                    states[name] = state
        # Failed/unknown/never must not leave sibling transport keys marking tools ready.
        if not live_ok:
            base_url, model, api_key_fingerprint = _provider_capability_transport_markers(
                provider_config, api_key
            )
            for cache_key in list(self.provider_capability_cache):
                if api_key_fingerprint and api_key_fingerprint not in cache_key:
                    continue
                if base_url and base_url not in cache_key:
                    continue
                if model and model not in cache_key:
                    continue
                self.provider_capability_cache[cache_key] = {"connection": "unverified"}
        self.provider_capability_cache[key] = states
        if len(self.provider_capability_cache) > 16:
            oldest_key = next(iter(self.provider_capability_cache))
            if oldest_key != key:
                self.provider_capability_cache.pop(oldest_key, None)
        self._overlay_last_test_on_matching_services(provider_config, api_key, states)

    @staticmethod
    def _normalize_transport_marker(value: object) -> str:
        return str(value or "").strip().rstrip("/").casefold()

    def _last_test_targets_provider(
        self,
        provider_config: ProviderConfig,
        last_test: dict[str, Any],
    ) -> bool:
        test_base = self._normalize_transport_marker(
            last_test.get("base_url") or last_test.get("baseUrl")
        )
        test_model = self._normalize_transport_marker(last_test.get("model"))
        config_base = self._normalize_transport_marker(getattr(provider_config, "base_url", ""))
        config_model = self._normalize_transport_marker(getattr(provider_config, "model", ""))
        if not test_base or not test_model or not config_base or not config_model:
            return False
        return test_base == config_base and test_model == config_model

    def rehydrate_last_test(
        self,
        provider_config: ProviderConfig | None,
        api_key: str | None,
        *,
        last_test: dict[str, Any] | None = None,
        workspace_id: str | None = None,
    ) -> None:
        """Restore last-test capability truth after a sidecar restart.

        Host last-test and workspace recovery records are observations from a
        prior live /provider/test. They must match the current transport.
        """
        if provider_config is None:
            return
        if isinstance(last_test, dict) and self._last_test_targets_provider(provider_config, last_test):
            self.remember_provider_capability_test(provider_config, api_key, last_test)
            return
        workspace = str(workspace_id or "").strip()
        if not workspace:
            return
        try:
            snapshot = self.memory_service.snapshot(workspace)
        except Exception:
            return
        record = None
        raw_workspace = getattr(snapshot, "workspace", None)
        if isinstance(raw_workspace, dict):
            record = raw_workspace.get(PROVIDER_CAPABILITY_KEY)
        if isinstance(record, dict) and self._last_test_targets_provider(provider_config, record):
            self.remember_provider_capability_test(provider_config, api_key, record)

    def provider_capability_state_for(self, provider_service: ProviderService, name: str) -> str:
        """Return the last observed state for a service, never a declared claim."""

        config = getattr(provider_service, "_config", None)
        api_key = getattr(provider_service, "_api_key", None)
        key = _provider_capability_cache_key(config, api_key)
        return self.provider_capability_cache.get(key, {}).get(
            str(name).strip().lower(),
            "unverified",
        )

    def provider_connection_verified(self, provider_service: ProviderService) -> bool:
        return self.provider_capability_state_for(provider_service, "connection") == "verified"

    def deduped_resources(self, workspace_id: str):
        return self.resource_service.dedupe_resources(self.repository.list_resources(workspace_id))

    def register_workspace_path(self, workspace_id: str, workspace_path: str | None) -> None:
        """Remember a workspace's filesystem root.

        Tools (e.g. ``read_workspace_file``, ``run_diagnostics``) need the
        workspace path so they can scope reads safely. The extension passes
        ``workspace_path`` on ``/session/start``; we store it here so any
        later turn for the same workspace can resolve it.
        """
        if not workspace_id:
            return
        resolved_workspace_id = self.repository.resolve_context_id(workspace_id) or workspace_id
        if workspace_path and workspace_path.strip():
            self.workspace_paths[resolved_workspace_id] = workspace_path.strip()
        else:
            self.workspace_paths.pop(resolved_workspace_id, None)

    def resolve_workspace_path(self, workspace_id: str | None) -> str | None:
        if not workspace_id:
            return None
        resolved_workspace_id = self.repository.resolve_context_id(workspace_id) or workspace_id
        path = self.workspace_paths.get(resolved_workspace_id)
        if path:
            return path
        provisioning = self.repository.get_project_provisioning(resolved_workspace_id)
        return provisioning.project_path if provisioning is not None else None

    @staticmethod
    def _local_filesystem_root(path: str | None) -> str | None:
        """Return a local directory path, or None for remote/missing project roots.

        Trainer storage stays on the sidecar machine. A Remote SSH project path
        is identity only and must not become a local sandbox/root.
        """
        raw = str(path or "").strip()
        if not raw or "://" in raw:
            return None
        try:
            candidate = Path(raw).expanduser()
            if candidate.exists() and candidate.is_dir():
                return str(candidate.resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            return None
        return None

    def workspace_authority(self, workspace_id: str | None) -> WorkspaceAuthority | None:
        """Return project authority for a workspace, never a sandbox fallback."""
        if not workspace_id:
            return None
        resolved_workspace_id = self.repository.resolve_context_id(workspace_id) or workspace_id
        raw_root = self.resolve_workspace_path(resolved_workspace_id)
        root = self._local_filesystem_root(raw_root)
        workspace = self.memory_service.snapshot(resolved_workspace_id).workspace
        remote_name = ""
        trusted_value = None
        if isinstance(workspace, dict):
            remote_name = str(workspace.get("remote_name") or "").strip()
            trusted_value = workspace.get("workspace_trusted")
        authority = self.workspace_authorities.get(resolved_workspace_id)
        if root:
            if authority is None or not authority.active_workspace_root:
                authority = WorkspaceAuthority(
                    root_path=root, initial_permission=PermissionLevel.INSPECT
                )
                self.workspace_authorities[resolved_workspace_id] = authority
            elif authority.active_workspace_root != str(
                Path(root).expanduser().resolve(strict=False)
            ):
                authority.set_active_workspace(root)
        else:
            if not remote_name and not raw_root:
                return None
            if authority is None or authority.active_workspace_root:
                authority = WorkspaceAuthority()
                self.workspace_authorities[resolved_workspace_id] = authority
        authority.set_workspace_context(
            remote_name=remote_name,
            replace_remote=True,
            workspace_trusted=(bool(trusted_value) if trusted_value is not None else None),
        )
        return authority

    def register_workspace_sandbox_root(self, workspace_id: str, sandbox_root_path: str | None) -> None:
        if not workspace_id:
            return
        resolved_workspace_id = self.repository.resolve_context_id(workspace_id) or workspace_id
        if sandbox_root_path and sandbox_root_path.strip():
            self.sandbox_root_overrides[resolved_workspace_id] = sandbox_root_path.strip()
        else:
            self.sandbox_root_overrides.pop(resolved_workspace_id, None)

    def resolve_workspace_sandbox_root(self, workspace_id: str | None) -> str | None:
        if not workspace_id:
            return None
        resolved_workspace_id = self.repository.resolve_context_id(workspace_id) or workspace_id
        configured = self.sandbox_root_overrides.get(resolved_workspace_id)
        if configured and configured.strip():
            return configured.strip()
        workspace = self.memory_service.snapshot(resolved_workspace_id).workspace
        if isinstance(workspace, dict):
            candidate = str(workspace.get("sandbox_root_override") or "").strip()
            if candidate:
                return candidate
        return None
