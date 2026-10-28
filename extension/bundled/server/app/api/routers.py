from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import posixpath
import re
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Literal, Sequence, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from ..core.models import (
    ActiveCardSelectionResult,
    AffectState,
    AgentCheckpointAccessRequest,
    CapabilityFlags,
    CardGenerationContext,
    CardGenerationRequest,
    CardGenerationResponse,
    ChatMessage,
    CoachArtifact,
    CoachDefaults,
    CoachingState,
    CoachScenario,
    CoachTurnSummary,
    DependencyUsageEvidence,
    EvaluateCurrentFileRequest,
    EvaluateSnippetRequest,
    EvaluationCheck,
    EvaluationReport,
    FirstLookSummary,
    ImplementationGuide,
    LearnerState,
    LearningPlan,
    MemorySnapshot,
    PlanStage,
    PrincipleNotes,
    ProjectAdaptationGuide,
    ProjectIdea,
    ProjectProvisioning,
    ProjectSourceSuggestion,
    ProviderConfig,
    ProviderCredentialMode,
    ProviderProtocol,
    ResourceComposerIntent,
    ResourceKnowledgeEvidence,
    ResourceRecord,
    ResponseLanguage,
    ReviewQueueItem,
    SandboxWriteRequest,
    SessionMessageRequest,
    SessionMessageResponse,
    TaskSpec,
    TeachingDecision,
    TeachingKnowledgeAsset,
    ToneDecision,
    TrainingCardCandidateSnapshot,
    TrainingPlanBinding,
    TurnRequest,
    UserProfile,
    WorkbenchSnapshot,
    WorkspaceUnderstandingSnapshot,
)
from ..llm.prompts import infer_coaching_scenario as infer_message_coaching_scenario
from ..llm.prompts import infer_learner_signal as infer_message_learner_signal
from ..llm.provider_gateway import (
    NEWAPI_CONNECTION_TYPE,
    normalize_provider_connection_type,
)
from ..llm.provider_protocols import (
    default_capabilities_for_protocol,
    normalize_provider_protocol,
)
from ..llm.provider_service import (
    ProviderService,
    _build_language_corruption_recovery_override,
    redact_provider_error,
)
from ..llm.reply_continuity import visible_next_step
from ..llm.training_review_context import active_training_review
from ..llm.turn_grounding import (
    GroundingDecision,
    WorkspaceEvidence,
    build_teaching_turn_facts,
    evaluate_next_step_grounding,
    evaluate_turn_grounding,
    grounding_correction_instruction,
    grounding_outcome,
    looks_like_narration_opening,
    memory_provenance_summary,
    trim_ungrounded_segments,
)
from ..memory.models import utc_now
from ..memory.workspace_recovery import (
    AFFECT_STATE_KEY,
    CURRENT_TASK_KEY,
    PLAN_RUNTIME_KEY,
    accept_in_progress_plan_runtime_turn,
    accept_plan_runtime_resume_request,
    apply_live_training_mint_to_card,
    coach_focus_runtime_from_snapshot,
    extract_structured_plan_runtime_facts,
    formal_task_is_live_runtime_identity,
    leftover_formal_plan_is_live_for_fill,
    leftover_frozen_plan_blocks_generation,
    live_coach_focus_area,
    live_coach_stage_label,
    live_language_detection_hint,
    live_plan_lane_copy,
    live_plan_refresh_step_why,
    live_plan_snapshot_persist_chrome,
    live_plan_update_heading,
    live_plan_update_persist_chrome,
    live_task_clean_step_candidates,
    live_task_focus_area,
    live_task_heading,
    live_task_label,
    live_task_suggested_reason,
    live_task_suggested_title,
    live_task_training_concepts,
    live_training_lane_copy,
    live_training_open_copy,
    live_training_why_this_card,
    plan_runtime_status_from_recovery,
    recovered_resume_turn_succeeded,
    select_latest_current_task,
    select_plan_runtime_for_scope,
)
from ..training.card_generator import (
    CardGenerationProviderFailure,
    CardGenerationService,
    _make_guided_scenario_pack_card,
)
from ..training.card_request import message_requests_explicit_training_card
from ..training.plan_binding import validated_mint_binding
from ..workspace.classifier import (
    classify_heuristic,
    is_code_like_current_file,
    is_code_like_entry_point,
)
from ..workspace.provisioning import (
    ProjectProvisioningConflictError,
    ProjectProvisioningIntegrityError,
)
from . import coach_support
from ._helpers import (
    GBK_MOJIBAKE_FRAGMENTS,
    SUPPORTED_RESPONSE_LANGUAGES,
    contains_cjk_text,
    localized_text,
    looks_like_mojibake_text,
    prefers_chinese,
    supported_response_language,
)
from ._singleflight import (
    claim_session_request_singleflight as claim_session_request_singleflight,
)
from ._singleflight import (
    fail_session_request_singleflight as fail_session_request_singleflight,
)
from ._singleflight import (
    publish_session_request_singleflight as publish_session_request_singleflight,
)
from .coach_support import CoachSupportDeps, CoachTurnPayload
from .router_support import (
    _apply_pedagogy_controls_to_card_request,
    _normalize_resource_turn_request,
    _pedagogy_controls_for_workspace,
    _request_requires_agent_tools,
    _workspace_training_mint_overlay,
    looks_like_schemeless_provider_host,
    provider_recovery_resumed_next_step_text,
    provider_recovery_resumed_summary_text,
    resolve_provider_url_scheme,
)
from .router_support import (
    _attach_requested_workspace_files as _attach_requested_workspace_files,
)
from .router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from .router_support import (
    _resolve_agent_loop_enabled as _resolve_agent_loop_enabled,
)
from .router_support import (
    overlay_session_response_honesty_stamps as overlay_session_response_honesty_stamps,
)
from .router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from .routes._deps import RouterDeps
from .routes.browser import build_browser_router
from .routes.core import CoreRouteDeps, build_core_router
from .routes.learning import build_learning_router
from .routes.mcp import build_mcp_router
from .routes.memory import build_memory_router
from .routes.plan import build_plan_router
from .routes.provider import build_provider_router
from .routes.resources import build_resources_router
from .routes.sandbox import build_sandbox_router
from .routes.workspace import build_workspace_router
from .runtime import SessionState, TrainerRuntime, WorkspaceBindingError
from .training_card_identity import (
    require_live_selected_card_for_status as require_live_selected_card_for_status_impl,
)
from .training_card_identity import (
    training_card_is_live_for_verify as training_card_is_live_for_verify_impl,
)
from .training_skill_evidence import record_executed_training_evidence

logger = logging.getLogger(__name__)


_SCHEMELESS_PROVIDER_HOST_RE = re.compile(
    r"^(?:localhost|(?:\d{1,3}\.){3}\d{1,3}|(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,})"
    r"(?::\d{1,5})?(?:/\S*)?$",
    re.IGNORECASE,
)
_SCHEMELESS_LOCAL_HOST_WITH_PORT_RE = re.compile(
    r"^[a-z0-9][a-z0-9-]*(?::\d{1,5})(?:/\S*)?$",
    re.IGNORECASE,
)
_LOCAL_PROVIDER_HOST_RE = re.compile(
    r"^(?:localhost|host\.docker\.internal|::1"
    r"|(?:127|10)\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|.+\.(?:localhost|local|test))$",
    re.IGNORECASE,
)
# Scheme resolution probes each host once per sidecar process; a relay's TLS
# support does not change mid-session, and every request path
# (test/models/turn) re-normalizes the base URL.
_PROVIDER_SCHEME_CACHE: dict[str, str] = {}



def build_router(runtime: TrainerRuntime) -> APIRouter:
    router = APIRouter()
    action_id_counter = 0
    resource_training_card_locks: dict[str, Lock] = {}
    resource_training_card_locks_guard = Lock()

    # Stream cancellation is deliberately scoped to this router/runtime. The
    # sidecar is a local process, so an in-memory registry gives the active
    # request and the explicit cancel endpoint a shared, bounded signal
    # without persisting transient transport state in the learner session.
    stream_cancellation_events: dict[str, asyncio.Event] = {}
    stream_cancellation_guard = Lock()
    completed_session_requests: dict[tuple[str, str, str], dict[str, object]] = {}
    completed_session_requests_guard = Lock()
    # First-pass same request_id must not double-mint; waiters share owner result.
    # Shared across /session/message(+stream) and /turn(+stream): same
    # (workspace_id, session_id, request_id) key is one inflight/completed entry.
    inflight_session_requests: dict[tuple[str, str, str], asyncio.Future] = {}
    # Explicit /training/generate-card/stream — separate from coach session/turn so
    # a coaching request_id never collapses with a card mint (or vice versa).
    completed_training_card_requests: dict[tuple[str, str, str], dict[str, object]] = {}
    completed_training_card_requests_guard = Lock()
    inflight_training_card_requests: dict[tuple[str, str, str], asyncio.Future] = {}

    def save_plan_or_conflict(
        workspace_id: str,
        plan: LearningPlan,
        *,
        expected_revision: int,
    ) -> int:
        """Optimistic-lock plan persistence: 409 with the current revision
        when another writer moved the plan between this request's read and
        write (design §9)."""
        from ..training.plan_revision import PlanRevisionConflict, save_plan_checked

        try:
            saved = save_plan_checked(
                runtime.repository,
                workspace_id,
                plan,
                expected_revision=expected_revision,
            )
        except PlanRevisionConflict as conflict:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "plan_revision_conflict",
                    "plan_id": plan.id,
                    "expected_revision": conflict.expected_revision,
                    "current_revision": conflict.actual_revision,
                },
            ) from conflict
        return saved["revision"]

    def head_plan_revision(workspace_id: str, plan_id: str) -> int:
        return runtime.repository.get_plan_revision(workspace_id, plan_id)


    def resolve_stream_id(payload: object) -> str:
        value = None
        if isinstance(payload, dict):
            value = payload.get("stream_id") or payload.get("streamId")
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > 256:
            return f"stream_{uuid4().hex}"
        return normalized

    def register_stream_cancellation(stream_id: str) -> None:
        # Idempotent replace: a crashed stream teardown can leave a stale entry,
        # and rejecting the re-registration would permanently wedge every later
        # send that reuses the id. Concurrent double-run protection lives in the
        # request_id singleflight claim, not here.
        with stream_cancellation_guard:
            stream_cancellation_events[stream_id] = asyncio.Event()

    def unregister_stream_cancellation(stream_id: str) -> None:
        with stream_cancellation_guard:
            stream_cancellation_events.pop(stream_id, None)

    def request_stream_cancellation(stream_id: str) -> bool:
        with stream_cancellation_guard:
            event = stream_cancellation_events.get(stream_id)
            if event is None:
                return False
            event.set()
            return True

    def stream_cancellation_requested(stream_id: str) -> bool:
        with stream_cancellation_guard:
            event = stream_cancellation_events.get(stream_id)
            return bool(event and event.is_set())

    def resource_training_card_lock(workspace_id: str) -> Lock:
        """Keep one workspace's resource-card route and active selection in sync."""

        with resource_training_card_locks_guard:
            return resource_training_card_locks.setdefault(workspace_id, Lock())


    def extract_coach_turn_payload(value: object) -> CoachTurnPayload:
        """Restore the stable coach-turn contract after legacy recovery helpers."""

        if not isinstance(value, dict):
            raise TypeError("Coach turn payload must be a mapping.")
        scenario = value.get("scenario")
        learner_signal = value.get("learner_signal")
        coach_context = value.get("coach_context")
        suggested_actions = value.get("suggested_actions")
        artifacts = value.get("artifacts")
        coach_turn = value.get("coach_turn")
        stream = value.get("stream")
        if not isinstance(scenario, str) or not isinstance(learner_signal, str):
            raise TypeError("Coach turn payload is missing its text fields.")
        if not isinstance(coach_context, dict) or not isinstance(artifacts, dict):
            raise TypeError("Coach turn payload is missing its mapping fields.")
        if not isinstance(suggested_actions, list) or not all(
            isinstance(action, dict) for action in suggested_actions
        ):
            raise TypeError("Coach turn payload has invalid suggested actions.")
        if not isinstance(coach_turn, CoachTurnSummary) or not isinstance(stream, bool):
            raise TypeError("Coach turn payload is missing its summary fields.")
        return cast(CoachTurnPayload, value)

    def coach_turn_mapping(value: CoachTurnPayload) -> dict[str, object]:
        """Adapt the stable payload to existing mutable-dict helper boundaries."""

        return cast(dict[str, object], value)

    coach_summary_scenarios = {
        "general",
        "onboarding",
        "idea_implementation",
        "project_idea",
        "project_idea_mining",
        "project_adaptation",
        "project_sourcing",
        "principle",
        "principle_explanation",
        "remote_workspace",
        "debug_loop",
        "function_guidance",
        "review",
        "review_reflection",
        "plan",
        "task",
        "next_task",
    }

    def localized_actions(
        response_language: str | None,
        english: list[str],
        chinese: list[str],
    ) -> list[str]:
        if not prefers_chinese(response_language):
            return english
        resolved: list[str] = []
        for index, label in enumerate(chinese):
            fallback = english[index] if index < len(english) else ""
            visible_label = fallback if not label or looks_like_mojibake_text(label) else label
            if visible_label:
                resolved.append(visible_label)
        return resolved

    def provider_api_key_from_payload(payload: dict) -> str | None:
        api_key_raw = payload.get("api_key") or payload.get("apiKey")
        return api_key_raw.strip() if isinstance(api_key_raw, str) else None

    def normalize_provider_base_url(value: object, protocol: ProviderProtocol) -> str:
        """Keep a pasted request endpoint from becoming the client's base URL."""
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""

        # Scheme-less service hosts ("minimax.example.com", "localhost:1234/v1",
        # "ollama:11434") get a probed scheme so http-only relays and local
        # servers both work instead of failing later with an opaque error.
        # Mirrors the webview draft checks in shared TS providerProtocols.
        candidate = raw_value
        if not candidate.lower().startswith(("http://", "https://")) and looks_like_schemeless_provider_host(
            candidate
        ):
            candidate = f"{resolve_provider_url_scheme(candidate)}://{candidate}"

        try:
            parsed = urlsplit(candidate)
        except ValueError:
            return raw_value.rstrip("/")

        if not parsed.scheme or not parsed.netloc:
            return raw_value.rstrip("/")

        path = parsed.path.rstrip("/")
        lowered_path = path.lower()
        if protocol in {
            "openai_responses",
            "openai_chat_completions",
            "openai_chat_completions_compatible",
        }:
            for suffix in ("/chat/completions", "/responses"):
                if lowered_path.endswith(suffix):
                    path = path[: -len(suffix)] or "/"
                    break
        elif protocol == "anthropic_messages" and lowered_path.endswith("/messages"):
            path = path[: -len("/messages")] or "/"
        elif protocol == "gemini_generate_content":
            model_marker = "/models/"
            marker_index = lowered_path.rfind(model_marker)
            if marker_index >= 0 and lowered_path.endswith(":generatecontent"):
                path = path[:marker_index] or "/"

        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))

    def provider_connection_type_from_payload(provider_payload: dict) -> str | None:
        raw = (
            provider_payload.get("connection_type")
            or provider_payload.get("connectionType")
            or provider_payload.get("_type")
            or provider_payload.get("protocol")
        )
        if not isinstance(raw, str):
            return None
        return normalize_provider_connection_type(raw)

    def provider_protocol_from_payload(provider_payload: dict) -> ProviderProtocol | None:
        raw = provider_payload.get("protocol") or provider_payload.get("api") or ""
        value = str(raw or "").strip().lower()
        if not value:
            return None
        if normalize_provider_connection_type(value) is not None:
            return None
        if value in {"anthropic_messages", "anthropic", "claude"}:
            return "anthropic_messages"
        if value in {"openai_responses", "responses"}:
            return "openai_responses"
        if value in {"gemini_generate_content", "gemini", "google"}:
            return "gemini_generate_content"
        if value in {"openai_chat_completions", "openai"}:
            return "openai_chat_completions"
        if value in {"openai_chat_completions_compatible", "openai-compatible", "compatible"}:
            return "openai_chat_completions_compatible"
        return normalize_provider_protocol(value)

    def provider_mode_from_payload(
        provider_payload: dict,
    ) -> Literal["direct", "gateway"] | None:
        raw_mode = provider_payload.get("mode")
        if not isinstance(raw_mode, str):
            return None
        normalized_mode = raw_mode.strip()
        if normalized_mode == "direct":
            return "direct"
        if normalized_mode == "gateway":
            return "gateway"
        return None

    def provider_credential_mode_from_payload(
        provider_payload: dict,
    ) -> ProviderCredentialMode | None:
        raw_mode = provider_payload.get("credential_mode") or provider_payload.get("credentialMode")
        if not isinstance(raw_mode, str):
            return None
        normalized_mode = raw_mode.strip()
        if normalized_mode == "workspace_secret":
            return "workspace_secret"
        if normalized_mode == "ui_proxy":
            return "ui_proxy"
        return None

    def provider_payload_declares_protocol(provider_payload: dict) -> bool:
        for key in ("protocol", "api", "provider_key", "providerKey"):
            raw_value = provider_payload.get(key)
            if isinstance(raw_value, str) and raw_value.strip():
                return True
        return False

    def provider_capabilities_from_payload(provider_payload: dict) -> CapabilityFlags:
        explicit_capabilities = provider_payload.get("capabilities")
        if isinstance(explicit_capabilities, dict) and explicit_capabilities:
            return CapabilityFlags.model_validate(explicit_capabilities)
        protocol = provider_protocol_from_payload(provider_payload) or (
            "openai_chat_completions_compatible"
        )
        defaults = default_capabilities_for_protocol(protocol)
        if not provider_payload_declares_protocol(provider_payload):
            defaults = defaults.model_copy(
                update={
                    "embeddings": False,
                    "tools": False,
                    "json_schema": False,
                    "structured_output": False,
                }
            )
        return defaults

    def provider_config_from_payload(payload: dict) -> ProviderConfig | None:
        provider_payload = payload.get("provider")
        if not isinstance(provider_payload, dict):
            return None
        provider_protocol = provider_protocol_from_payload(provider_payload)
        declared_protocol_raw = provider_payload.get("protocol") or provider_payload.get("api")
        declared_protocol = (
            isinstance(declared_protocol_raw, str) and bool(str(declared_protocol_raw).strip())
        )
        connection_type = provider_connection_type_from_payload(provider_payload)
        if declared_protocol and provider_protocol is None:
            return None
        if provider_protocol is None and connection_type == NEWAPI_CONNECTION_TYPE:
            return None
        if provider_protocol is None:
            provider_protocol = "openai_chat_completions_compatible"
        provider_name_raw = (
            provider_payload.get("name")
            or provider_payload.get("label")
            or provider_payload.get("provider_key")
            or provider_payload.get("providerKey")
            or provider_payload.get("api")
            or "custom-openai-compatible"
        )
        return ProviderConfig(
            name=str(provider_name_raw).strip() or "custom-openai-compatible",
            baseUrl=normalize_provider_base_url(
                provider_payload.get("base_url") or provider_payload.get("baseUrl", ""),
                provider_protocol,
            ),
            apiKeyRef=provider_payload.get("api_key_ref")
            or provider_payload.get("apiKeyRef", "trainer.default"),
            model=(provider_payload.get("model", "") or "").strip(),
            protocol=provider_protocol,
            label=(provider_payload.get("label") or provider_payload.get("name") or "").strip() or None,
            mode=provider_mode_from_payload(provider_payload),
            connectionType=connection_type,
            credentialMode=provider_credential_mode_from_payload(provider_payload),
            availableModels=list(provider_payload.get("available_models") or provider_payload.get("availableModels") or []),
            allowedModels=list(provider_payload.get("allowed_models") or provider_payload.get("allowedModels") or []),
            deniedModels=list(provider_payload.get("denied_models") or provider_payload.get("deniedModels") or []),
            modelAliases=dict(provider_payload.get("model_aliases") or provider_payload.get("modelAliases") or {}),
            modelCapabilities=dict(
                provider_payload.get("model_capabilities") or provider_payload.get("modelCapabilities") or {}
            ),
            modelTokenLimits=dict(
                provider_payload.get("model_token_limits") or provider_payload.get("modelTokenLimits") or {}
            ),
            taskBindings=dict(provider_payload.get("task_bindings") or provider_payload.get("taskBindings") or {}),
            contextWindowTokens=provider_payload.get("context_window_tokens")
            or provider_payload.get("contextWindowTokens"),
            maxOutputTokens=provider_payload.get("max_output_tokens")
            or provider_payload.get("maxOutputTokens"),
            embeddingModel=provider_payload.get("embedding_model")
            or provider_payload.get("embeddingModel"),
            catalogSource=(provider_payload.get("catalog_source") or provider_payload.get("catalogSource") or "").strip()
            or None,
            cacheTtlSeconds=provider_payload.get("cache_ttl_seconds")
            or provider_payload.get("cacheTtlSeconds"),
            profileId=(provider_payload.get("profile_id") or provider_payload.get("profileId") or "").strip()
            or None,
            profileLabel=(provider_payload.get("profile_label") or provider_payload.get("profileLabel") or "").strip()
            or None,
            profileMode=(provider_payload.get("profile_mode") or provider_payload.get("profileMode") or "").strip()
            or None,
            requestDefaults=provider_payload.get("request_defaults")
            or provider_payload.get("requestDefaults")
            or {},
            capabilities=provider_capabilities_from_payload(provider_payload),
        )

    def should_probe_language_integrity(message: str | None, response_language: str | None) -> bool:
        return prefers_chinese(response_language) or contains_cjk_text(message)

    KNOWN_CONTEXT_TRANSLATIONS_ZH: tuple[tuple[str, str], ...] = (
        ("function contract and call-site reading", "\u51fd\u6570\u5951\u7ea6\u4e0e call site \u5224\u65ad"),
        ("the smallest trustworthy debug loop", "最小可信的 debug loop"),
        ("remote workspace boundary", "远程工作区边界"),
        ("VS Code remote workflow", "VS Code 远程工作区"),
        ("Code remote workflow", "远程工作区边界"),
        ("VS Code remote workspace", "VS Code 远程工作区"),
        ("VS Code function guidance", "VS Code 函数提示"),
        ("function contract recovery", "\u6062\u590d\u51fd\u6570\u5951\u7ea6"),
        ("function contract reading", "\u51fd\u6570\u5951\u7ea6\u5224\u65ad"),
        ("VS Code debug loop", "VS Code 调试闭环"),
    )

    def localize_known_context_phrases(
        value: str,
        response_language: str | None,
    ) -> str:
        if not value or not prefers_chinese(response_language):
            return value

        cleaned = value
        lane_match = re.match(
            r"""^Continue\s+['"](?P<focus>.+?)['"]\s+and do not open a new lane before this next move lands:\s*(?P<rest>.+)$""",
            cleaned,
            flags=re.IGNORECASE,
        )
        if lane_match:
            localized_focus = localize_known_context_phrases(
                lane_match.group("focus").strip(),
                response_language,
            )
            localized_rest = localize_known_context_phrases(
                lane_match.group("rest").strip(),
                response_language,
            )
            return f"继续沿着「{localized_focus}」这条主线，先别开新线：{localized_rest}".strip()

        for source, target in KNOWN_CONTEXT_TRANSLATIONS_ZH:
            cleaned = re.sub(re.escape(source), target, cleaned, flags=re.IGNORECASE)

        exact_focus_map = {
            "debug loop": "调试闭环",
            "function contract": "\u51fd\u6570\u5951\u7ea6\u5224\u65ad",
            "call-site reading": "call site 判断",
        }
        normalized_cleaned = cleaned.strip()
        localized_exact = exact_focus_map.get(normalized_cleaned.casefold())
        if localized_exact:
            return localized_exact

        return cleaned

    def language_aligned_context_text(
        value: object,
        response_language: str | None,
    ) -> str:
        if not isinstance(value, str):
            return ""
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized:
            return ""
        if prefers_chinese(response_language) and looks_like_mojibake_text(normalized):
            return ""
        if not prefers_chinese(response_language) and contains_cjk_text(normalized):
            latin_fragments = [
                re.sub(r"\s+", " ", fragment).strip(" \t\r\n-:;,.!?/|()[]{}<>")
                for fragment in re.split(r"[\u3400-\u9fff]+", normalized)
            ]
            salvage = " ".join(
                fragment
                for fragment in latin_fragments
                if fragment and re.search(r"[A-Za-z0-9`]", fragment)
            ).strip()
            return normalize_visible_coach_text(salvage)
        return localize_known_context_phrases(
            normalize_visible_coach_text(normalized),
            response_language,
        )

    def language_aligned_context_list(
        value: object,
        response_language: str | None,
        *,
        limit: int | None = None,
    ) -> list[str]:
        if not isinstance(value, list):
            return []
        aligned: list[str] = []
        for item in value:
            normalized = language_aligned_context_text(item, response_language)
            if not normalized or normalized in aligned:
                continue
            aligned.append(normalized)
            if limit is not None and len(aligned) >= limit:
                break
        return aligned

    def language_aligned_flat_payload(
        value: dict[str, object] | None,
        response_language: str | None,
        *,
        list_limit: int = 6,
    ) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        aligned = dict(value)
        for key, item in list(aligned.items()):
            if isinstance(item, str):
                aligned[key] = language_aligned_context_text(item, response_language)
                continue
            if isinstance(item, list):
                if all(not isinstance(entry, dict) for entry in item):
                    aligned[key] = language_aligned_context_list(
                        item,
                        response_language,
                        limit=list_limit,
                    )
        return aligned

    _VISIBLE_COACH_TEXT_FIELDS = {
        "blocked_reason",
        "blockedReason",
        "continuity_summary",
        "continuitySummary",
        "current_focus",
        "currentFocus",
        "current_step",
        "currentStep",
        "focus_area",
        "focusArea",
        "next_after_current",
        "nextAfterCurrent",
        "next_step",
        "nextStep",
        "resume_thread",
        "resumeThread",
        "review_queue_summary",
        "reviewQueueSummary",
        "review_rhythm",
        "reviewRhythm",
        "strategy_preference_summary",
        "strategyPreferenceSummary",
        "summary",
        "teaching_goal",
        "teachingGoal",
        "teaching_note",
        "teachingNote",
        "verified_result",
        "verifiedResult",
        "why_now",
        "whyNow",
    }
    _VISIBLE_COACH_META_PREFIXES = (
        "current coaching focus:",
        "current focus:",
        "current focus to continue:",
        "review rhythm:",
        "preferred teaching asset:",
        "reusable teaching asset:",
        "resume the live thread around",
        "build on the verified result:",
        "keep the blocker in view:",
        "coach confidence:",
        "memory scope is",
        "evidence to anchor on:",
        "this follows the teaching lane from",
        "reuse the saved teaching asset",
        "\u5f53\u524d\u805a\u7126\uff1a",
        "\u5f53\u524d\u805a\u7126\u70b9\uff1a",
        "\u590d\u4e60\u8282\u594f\uff1a",
        "\u8bb0\u5fc6\u8303\u56f4\u662f",
    )
    _VISIBLE_COACH_META_LABELS = {
        "general coaching",
        "idea implementation guidance",
        "next step after review",
        "next task coaching",
        "plan and review rhythm",
        "principle explanation",
        "project adaptation",
        "project idea mining",
        "project implementation",
        "review and reflection coaching",
        "task execution coaching",
    }
    _VISIBLE_COACH_PREFIX_PATTERNS = (
        re.compile(r"^resume the live thread(?: around)?\s*", re.IGNORECASE),
        re.compile(r"^resume from the current coaching lane,?\s*", re.IGNORECASE),
        re.compile(r"^['\"][^'\"]+['\"]\.?\s*do this next before widening scope:\s*", re.IGNORECASE),
        re.compile(r"^do this next before widening scope:\s*", re.IGNORECASE),
    )
    _VISIBLE_COACH_INLINE_PATTERNS = (
        re.compile(r"\bcurrent coaching focus:\s*", re.IGNORECASE),
        re.compile(r"\bcurrent focus(?: to continue)?:\s*", re.IGNORECASE),
        re.compile(r"\breview rhythm:\s*", re.IGNORECASE),
        re.compile(r"\bpreferred teaching asset:\s*", re.IGNORECASE),
        re.compile(r"\breusable teaching asset:\s*", re.IGNORECASE),
        re.compile(r"\bresume the live thread around\s*", re.IGNORECASE),
        re.compile(r"\bresume from the current coaching lane,?\s*", re.IGNORECASE),
        re.compile(r"\bbuild on the verified result:\s*", re.IGNORECASE),
        re.compile(r"\bkeep the blocker in view:\s*", re.IGNORECASE),
        re.compile(r"\bcoach confidence:\s*", re.IGNORECASE),
        re.compile(r"\bevidence to anchor on:\s*", re.IGNORECASE),
    )
    _INTERNAL_VISIBLE_REPLY_MARKERS = (
        "<system-reminder>",
        "</system-reminder>",
        "system-reminder",
        "workspace file",
        "current file snapshot",
        "current file snap",
        "real tool call",
        "real workspace environment",
        "真实工程环境",
        "真实工具调用",
        "上一轮没有可用的 workspace file",
        "上一轮没有可用的 current file",
        "current file 或 workspace file",
    )

    def normalize_visible_coach_text(value: object) -> str:
        raw_text = str(value or "").strip()
        if not raw_text:
            return ""
        if looks_like_mojibake_text(raw_text):
            return ""

        cleaned = re.sub(r"\s+", " ", raw_text).strip()
        prefix_removed = False
        stripped_label = cleaned.casefold().strip(" -:*_#>~`[](){}")
        if stripped_label in _VISIBLE_COACH_META_LABELS:
            return ""
        for label in _VISIBLE_COACH_META_LABELS:
            if cleaned.casefold().startswith(label):
                cleaned = cleaned[len(label) :].lstrip(" .:-")
                prefix_removed = True
                break
        for prefix in _VISIBLE_COACH_META_PREFIXES:
            if cleaned.casefold().startswith(prefix):
                cleaned = cleaned[len(prefix) :].lstrip(" .:-")
                prefix_removed = True
                break
        for pattern in _VISIBLE_COACH_PREFIX_PATTERNS:
            next_cleaned = pattern.sub("", cleaned).lstrip(" .:-")
            if next_cleaned != cleaned:
                cleaned = next_cleaned
                prefix_removed = True
        for pattern in _VISIBLE_COACH_INLINE_PATTERNS:
            next_cleaned = pattern.sub("", cleaned)
            if next_cleaned != cleaned:
                cleaned = next_cleaned
                prefix_removed = True
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if prefix_removed:
            cleaned = re.sub(
                r"([.!?])\s+([a-z])",
                lambda match: f"{match.group(1)} {match.group(2).upper()}",
                cleaned,
            )
        if prefix_removed and cleaned[:1].isascii() and cleaned[:1].islower():
            cleaned = f"{cleaned[:1].upper()}{cleaned[1:]}"
        return cleaned

    def visible_reply_segment_looks_internal(value: object) -> bool:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
        if not cleaned:
            return False
        return any(marker.casefold() in cleaned for marker in _INTERNAL_VISIBLE_REPLY_MARKERS)

    def sanitize_visible_coach_reply_content(
        value: object,
        response_language: str | None = None,
    ) -> str:
        raw_text = str(value or "").strip()
        if not raw_text:
            return ""

        if looks_like_mojibake_text(raw_text):
            return localized_text(
                "I could not read that reply. Please send the same question again.",
                "这条回复没有读清。请把刚才的问题再发一次。",
                response_language,
            )

        cleaned = raw_text.replace("<system-reminder>", "").replace("</system-reminder>", "").strip()
        internal_marker_seen = visible_reply_segment_looks_internal(raw_text) or visible_reply_segment_looks_internal(
            cleaned
        )
        paragraphs = [segment.strip() for segment in re.split(r"\n\s*\n", cleaned) if segment.strip()]
        while len(paragraphs) > 1 and visible_reply_segment_looks_internal(paragraphs[0]):
            paragraphs.pop(0)
            internal_marker_seen = True
        cleaned = "\n\n".join(paragraphs) if paragraphs else cleaned
        if internal_marker_seen:
            sentence_segments = [
                segment.strip()
                for segment in re.split(r"(?<=[.!?。！？])\s+", cleaned)
                if segment.strip()
            ]
            if sentence_segments:
                while len(sentence_segments) > 1 and visible_reply_segment_looks_internal(sentence_segments[0]):
                    sentence_segments.pop(0)
                cleaned = " ".join(sentence_segments).strip()
        cleaned = re.sub(r"^(?:<[^>\n]+>\s*)+", "", cleaned).strip()
        return cleaned

    def repair_legacy_assistant_messages(
        snapshot: WorkbenchSnapshot,
        response_language: str | None,
    ) -> bool:
        repaired = False
        for index, message in enumerate(snapshot.messages):
            if str(message.role or "").strip().lower() != "assistant":
                continue
            content = str(message.content or "").strip()
            cleaned = sanitize_visible_coach_reply_content(content, response_language)
            if cleaned == content:
                continue
            snapshot.messages[index] = message.model_copy(update={"content": cleaned})
            repaired = True
        return repaired

    def strip_visible_next_step_prefix(value: object) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            return ""
        cleaned = re.sub(r"(?i)^(?:next(?: step)?\s*:\s*)+", "", cleaned).strip()
        cleaned = re.sub(r"^(?:\u4e0b\u4e00\u6b65[:\uff1a]\s*)+", "", cleaned).strip()
        return cleaned

    def sanitize_visible_coach_payload(value: object) -> object:
        if isinstance(value, dict):
            sanitized: dict[object, object] = {}
            for key, item in value.items():
                if key in _VISIBLE_COACH_TEXT_FIELDS and isinstance(item, str):
                    sanitized[key] = normalize_visible_coach_text(item)
                else:
                    sanitized[key] = sanitize_visible_coach_payload(item)
            return sanitized
        if isinstance(value, list):
            return [sanitize_visible_coach_payload(item) for item in value]
        return value

    def ensure_coach_turn_payload(
        value: dict[str, object] | None,
        fallback: dict[str, object],
    ) -> dict[str, object]:
        return value if value is not None else fallback

    def language_aligned_thread_payload(
        value: dict[str, object] | None,
        response_language: str | None,
    ) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        aligned = dict(value)
        if "scenario" in aligned:
            aligned["scenario"] = str(aligned.get("scenario") or "").strip()
        for key in (
            "focus_area",
            "summary",
            "next_step",
            "blocker",
            "verified_result",
            "decision",
            "teaching_note",
            "confidence",
        ):
            if key in aligned:
                aligned[key] = language_aligned_context_text(aligned.get(key), response_language)
        if "evidence" in aligned:
            aligned["evidence"] = language_aligned_context_list(
                aligned.get("evidence"),
                response_language,
                limit=4,
            )
        return aligned

    def language_aligned_memory_payload(
        value: dict[str, object] | None,
        response_language: str | None,
    ) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        aligned = dict(value)
        for key in (
            "current_focus",
            "recent_summary",
            "review_rhythm",
            "coach_anchor",
            "top_weakness",
            "pace_signal",
        ):
            if key in aligned:
                aligned[key] = language_aligned_context_text(aligned.get(key), response_language)
        for key in (
            "weaknesses",
            "recent_wins",
            "lowest_mastery_concepts",
            "teaching_observations",
        ):
            if key in aligned:
                aligned[key] = language_aligned_context_list(aligned.get(key), response_language)
        if "active_thread" in aligned:
            aligned["active_thread"] = language_aligned_thread_payload(
                normalized_object_mapping(aligned.get("active_thread")),
                response_language,
            )
        return aligned

    def language_aligned_coaching_state_payload(
        value: dict[str, object] | None,
        response_language: str | None,
    ) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        aligned = dict(value)
        for key in (
            "summary",
            "next_step",
            "decision",
            "blocker",
            "teaching_note",
            "confidence",
            "encouragement",
            "intervention_strategy",
            "teaching_goal",
            "resume_thread",
            "support_strategy",
        ):
            if key in aligned:
                aligned[key] = language_aligned_context_text(aligned.get(key), response_language)
        if "evidence" in aligned:
            aligned["evidence"] = language_aligned_context_list(
                aligned.get("evidence"),
                response_language,
                limit=4,
            )
        return aligned

    def language_aligned_review_rhythm(
        value: object,
        response_language: str | None,
    ) -> str | None:
        normalized = language_aligned_context_text(value, response_language)
        return normalized or None

    GENERIC_FOCUS_LABELS = {
        "",
        "implementation",
        "current lane",
        "current focus",
        "current task",
        "current stage",
        "current thread",
        "active thread",
        "coach",
        "coaching",
        "task",
        "plan",
        "review",
        "evaluation",
        "practice",
        "training",
        "general",
        "coach-turn",
        # Bare acknowledgments / filler. "好,给我第一个最小练习" splits on the
        # comma into first clause "好", which then surfaced in the reply as
        # 「好」 being the coaching focus.
        "ok",
        "okay",
        "alright",
        "sure",
        "yes",
        "yeah",
        "yep",
        "yup",
        "go",
        "go ahead",
        "continue",
        "next",
        "please",
        "thanks",
        "thank you",
        "好",
        "好的",
        "好嘞",
        "好呀",
        "好啦",
        "好嘛",
        "好滴",
        "嗯",
        "嗯嗯",
        "嗯呐",
        "行",
        "行吧",
        "可以",
        "成",
        "中",
        "妥",
        "继续",
        "接着来",
        "来吧",
        "开始吧",
        "下一步",
        "麻烦了",
        "谢谢",
        "多谢",
    }

    GENERIC_FOCUS_DISPLAY_LABELS = {
        "implementation": ("implementation slice", "实现切片"),
        "vs code remote workspace": ("VS Code remote workspace", "VS Code 远程工作区"),
        "vs code debug loop": ("VS Code debug loop", "VS Code 调试闭环"),
        "function contract": ("function contract reading", "\u51fd\u6570\u5951\u7ea6\u5224\u65ad"),
        "remote workspace boundary": ("remote workspace boundary", "远程工作区边界"),
        "the smallest trustworthy debug loop": ("the smallest trustworthy debug loop", "最小可信的 debug loop"),
        "function contract and call-site reading": (
            "function contract and call-site reading",
            "\u51fd\u6570\u5951\u7ea6\u4e0e call site \u5224\u65ad",
        ),
    }

    def normalize_focus_candidate(value: object) -> str:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip()
        return normalized.strip(
            " \t\r\n\"'`\u201c\u201d\u2018\u2019\u300c\u300d\u300e\u300f\uFF08\uFF09()[]{}<>:\uFF1A\uFF0C\u3002\uFF01\uFF1F\uFF1B;\u3001,."
        )

    def display_focus_label(value: object, response_language: str | None) -> str:
        cleaned = normalize_focus_candidate(value)
        if not cleaned:
            return ""
        localized = GENERIC_FOCUS_DISPLAY_LABELS.get(cleaned.lower())
        if localized is None:
            return cleaned
        return localized_text(localized[0], localized[1], response_language)

    def canonical_focus_for_scenario(
        scenario: str | None,
        response_language: str | None,
    ) -> str | None:
        if scenario == "remote_workspace":
            return localized_text("VS Code remote workspace", "VS Code 远程工作区", response_language)
        if scenario == "debug_loop":
            return localized_text("VS Code debug loop", "VS Code 调试闭环", response_language)
        if scenario == "function_guidance":
            return localized_text("function contract reading", "\u51fd\u6570\u5951\u7ea6\u5224\u65ad", response_language)
        return None

    def localized_training_defaults_for_scenario(
        scenario: str,
        response_language: str | None,
    ) -> tuple[str, str] | None:
        if scenario == "remote_workspace":
            return (
                localized_text(
                    "VS Code remote workspace",
                    "VS Code 远程工作区",
                    response_language,
                ),
                localized_text(
                    "remote workspace boundary",
                    "远程工作区边界",
                    response_language,
                ),
            )
        if scenario == "debug_loop":
            return (
                localized_text(
                    "VS Code debug loop",
                    "VS Code 调试闭环",
                    response_language,
                ),
                localized_text(
                    "the smallest trustworthy debug loop",
                    "最小可信的 debug loop",
                    response_language,
                ),
            )
        if scenario == "function_guidance":
            return (
                localized_text(
                    "function contract reading",
                    "\u51fd\u6570\u5951\u7ea6\u5224\u65ad",
                    response_language,
                ),
                localized_text(
                    "function contract and call-site reading",
                    "\u51fd\u6570\u5951\u7ea6\u4e0e call site \u5224\u65ad",
                    response_language,
                ),
            )
        return None

    def focus_looks_like_request_sentence(value: object) -> bool:
        cleaned = normalize_focus_candidate(value)
        if not cleaned:
            return False
        lowered = cleaned.lower()
        if lowered.startswith(
            (
                "teach me ",
                "help me ",
                "show me ",
                "tell me ",
                "walk me through ",
                "how to ",
                "this is ",
                "i want ",
                "create ",
                "generate ",
                "please ",
                "continue ",
            )
        ):
            return True
        return len(cleaned.split()) >= 7 and any(
            token in lowered
            for token in (
                "remote workspace",
                "debug loop",
                "typescript function",
                "function",
            )
        )

    GUIDED_LANE_SCENARIOS = {
        "remote_workspace",
        "debug_loop",
        "function_guidance",
        "project_adaptation",
    }
    GUIDED_VISIBLE_REPAIR_SCENARIOS = {
        "remote_workspace",
        "debug_loop",
        "function_guidance",
    }

    def guided_lane_comparison_requested(message: str | None) -> bool:
        lowered = str(message or "").casefold()
        if not lowered:
            return False
        markers = (
            "compare",
            "comparison",
            "difference",
            "different",
            "versus",
            "compared to",
            "对比",
            "区别",
            "相比",
        )
        return any(marker.casefold() in lowered for marker in markers)

    def guided_lane_visible_marker_map() -> dict[str, tuple[str, ...]]:
        return {
            "remote_workspace": (
                "remote workspace",
                "remote lane",
                "remote ssh",
                "ssh",
                "tunnels",
                "dev container",
                "devcontainer",
                "wsl",
                "credential",
                "credential mode",
                "credential move",
                "host",
                "host label",
                "workspace label",
                "远程工作区",
                "远程工作区边界",
                "远程主线",
                "远程 ssh",
                "远程边界",
                "开发容器",
                "凭据",
                "凭据模式",
                "host label",
                "workspace label",
            ),
            "debug_loop": (
                "debug loop",
                "breakpoint",
                "launch.json",
                "stack frame",
                "call stack",
                "watch value",
                "state change",
                "调试闭环",
                "断点",
                "调用栈",
                "单步",
                "变量值",
            ),
            "function_guidance": (
                "function contract",
                "call site",
                "hover",
                "signature help",
                "go to definition",
                "查看定义",
                "函数 contract",
                "函数契约",
                "调用点",
                "调用位置",
                "签名提示",
            ),
        }

    def text_contaminates_guided_lane(
        value: object,
        *,
        scenario: str,
        learner_message: str | None,
    ) -> bool:
        normalized_scenario = str(scenario or "").strip().lower()
        if normalized_scenario not in GUIDED_VISIBLE_REPAIR_SCENARIOS:
            return False
        if guided_lane_comparison_requested(learner_message):
            return False
        cleaned = normalize_visible_coach_text(value) or str(value or "").strip()
        if not cleaned:
            return False
        lowered = re.sub(r"\s+", " ", cleaned).casefold()
        marker_map = guided_lane_visible_marker_map()
        other_lane_markers = [
            marker.casefold()
            for lane, markers in marker_map.items()
            if lane != normalized_scenario
            for marker in markers
        ]
        return any(marker in lowered for marker in other_lane_markers)

    def guided_focus_display_value(
        focus: object,
        *,
        scenario: str | None,
        response_language: str | None,
    ) -> str:
        raw_focus = normalize_focus_candidate(focus)
        aligned_focus = language_aligned_context_text(raw_focus, response_language) if raw_focus else ""
        canonical_focus = canonical_focus_for_scenario(scenario, response_language) or ""
        if scenario not in GUIDED_LANE_SCENARIOS:
            return aligned_focus or raw_focus or canonical_focus
        if canonical_focus:
            return canonical_focus
        if not raw_focus or focus_looks_like_request_sentence(raw_focus):
            return canonical_focus or aligned_focus or raw_focus
        if prefers_chinese(response_language):
            phrase_like_focus = bool(re.search(r"[A-Za-z]", raw_focus)) and len(raw_focus.split()) >= 2
            mixed_lane_focus = bool(
                re.search(r"[A-Za-z]{3,}.*[\u3400-\u9fff]|[\u3400-\u9fff].*[A-Za-z]{3,}", aligned_focus)
            )
            if phrase_like_focus and (not contains_cjk_text(aligned_focus) or mixed_lane_focus):
                return canonical_focus or aligned_focus or raw_focus
        return aligned_focus or raw_focus or canonical_focus

    _GUIDED_LANE_CONTINUATION_PATTERN = re.compile(
        r"""(?i)^continue\s+['"].+?['"]\s+and do not open a new lane before this next move lands:"""
    )

    def guided_lane_focus_needs_response_repair(
        value: object,
        *,
        scenario: str | None,
        learner_message: str | None = None,
    ) -> bool:
        normalized_scenario = str(scenario or "").strip().lower()
        if normalized_scenario not in GUIDED_LANE_SCENARIOS:
            return False
        cleaned = str(value or "").strip()
        if not cleaned:
            return False
        visible_cleaned = normalize_visible_coach_text(cleaned) or cleaned
        if _GUIDED_LANE_CONTINUATION_PATTERN.match(cleaned) or _GUIDED_LANE_CONTINUATION_PATTERN.match(
            visible_cleaned
        ):
            return True
        if focus_looks_like_request_sentence(cleaned) or focus_looks_like_request_sentence(
            visible_cleaned
        ):
            return True
        return text_contaminates_guided_lane(
            visible_cleaned,
            scenario=normalized_scenario,
            learner_message=learner_message,
        )

    def repair_guided_lane_memory_snapshot_for_response(
        memory: MemorySnapshot,
        *,
        scenario: str | None,
        response_language: str | None,
        learner_message: str | None = None,
    ) -> MemorySnapshot:
        normalized_scenario = str(scenario or "").strip().lower()
        if normalized_scenario not in GUIDED_LANE_SCENARIOS:
            aligned_payload = language_aligned_memory_payload(memory.model_dump(), response_language)
            if isinstance(aligned_payload, dict):
                return type(memory).model_validate(aligned_payload)
            return memory

        repaired_memory = memory
        current_focus = str(memory.current_focus or "").strip()
        if guided_lane_focus_needs_response_repair(
            current_focus,
            scenario=normalized_scenario,
            learner_message=learner_message,
        ):
            repaired_focus = canonical_focus_for_scenario(
                normalized_scenario,
                response_language,
            ) or guided_focus_display_value(
                current_focus,
                scenario=normalized_scenario,
                response_language=response_language,
            )
            if repaired_focus:
                repaired_memory = repaired_memory.model_copy(update={"current_focus": repaired_focus})

        active_thread = repaired_memory.active_thread
        if active_thread is not None:
            thread_focus = str(active_thread.focus_area or "").strip()
            if guided_lane_focus_needs_response_repair(
                thread_focus,
                scenario=normalized_scenario,
                learner_message=learner_message,
            ):
                repaired_thread_focus = canonical_focus_for_scenario(
                    normalized_scenario,
                    response_language,
                ) or guided_focus_display_value(
                    thread_focus,
                    scenario=normalized_scenario,
                    response_language=response_language,
                )
                if repaired_thread_focus:
                    repaired_memory = repaired_memory.model_copy(
                        update={
                            "active_thread": active_thread.model_copy(
                                update={"focus_area": repaired_thread_focus}
                            )
                        }
                    )

        aligned_payload = language_aligned_memory_payload(
            repaired_memory.model_dump(),
            response_language,
        )
        if isinstance(aligned_payload, dict):
            return type(repaired_memory).model_validate(aligned_payload)
        return repaired_memory

    def is_specific_focus_candidate(value: object) -> bool:
        cleaned = normalize_focus_candidate(value)
        if not cleaned:
            return False
        lowered = cleaned.lower()
        if lowered in GENERIC_FOCUS_LABELS:
            return False
        if lowered.startswith("current coaching focus:") or cleaned.startswith(
            ("\u5f53\u524d\u805a\u7126\uff1a", "\u5f53\u524d\u805a\u7126\u70b9\uff1a")
        ):
            return False
        if len(cleaned) > 96 or len(cleaned.split()) > 12:
            return False
        return True

    def extract_focus_hint_from_message(
        message: str | None,
        *,
        allow_message_prefix: bool = True,
    ) -> str | None:
        normalized_message = re.sub(r"\s+", " ", str(message or "")).strip()
        if not normalized_message:
            return None

        named_concept_patterns = (
            r"""\b(?P<topic>[A-Z][A-Za-z0-9_-]{2,}(?:\s+[A-Z][A-Za-z0-9_-]{2,}){0,2}\s+(?:protocol|workflow|pattern|boundary|contract|guide|checklist|loop|api))\b""",
            r"""\b(?P<topic>[A-Z][A-Za-z0-9_-]{2,}\s+(?:protocol|workflow|pattern|boundary|contract|guide|checklist|loop|api))\b""",
        )
        for pattern in named_concept_patterns:
            match = re.search(pattern, normalized_message, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = normalize_focus_candidate(match.groupdict().get("topic"))
            if is_specific_focus_candidate(candidate):
                return candidate

        patterns = (
            r"""["'“”‘’「」『』]([^"'“”‘’「」『』\n]{3,80})["'“”‘’「」『』]""",
            r"""(?:围绕|聚焦|关注|关于)\s*["'“”‘’「」『』]?(?P<topic>[^,，。！？；;\n]{2,60}?)(?=[，。！？；,\n]|\s+(?:先|再|然后)\b|$)""",
            r"""(?:focus on|stay on|keep the focus on|guide me through|work on)\s*["'“”‘’「」『』]?(?P<topic>[^,.!?，。！？；;\n]{3,80}?)(?=\s+(?:and|first|before|then)\b|[,.!?，。！？；;\n]|$)""",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized_message, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = normalize_focus_candidate(match.groupdict().get("topic") or match.group(1))
            if is_specific_focus_candidate(candidate):
                return candidate

        if not allow_message_prefix:
            # Memory-anchor path: the raw opening clause of the learner message
            # is not a technical concept. Returning nothing lets the anchor
            # fall back to the previous anchor instead of drifting onto the
            # message prefix (2026-10-08 real-teaching review, cases 01-03).
            return None
        first_clause = re.split(r"[，。！？；,.!?\n]", normalized_message, maxsplit=1)[0]
        first_clause = re.sub(
            r"^(?:please|can you|could you|help me|guide me|show me|tell me|请|现在|先帮我)\s+",
            "",
            first_clause,
            flags=re.IGNORECASE,
        )
        first_clause = normalize_focus_candidate(first_clause)
        if is_specific_focus_candidate(first_clause):
            return first_clause
        return None

    def strip_resource_lookup_lead_in(value: object) -> str:
        cleaned = normalize_focus_candidate(value)
        if not cleaned:
            return ""
        cleaned = re.sub(
            r"^(?:please|can you|could you|would you|help me|teach me|show me|tell me|walk me through|guide me|请(?:直接)?|直接|请先|先|现在|麻烦你|帮我|请告诉我|告诉我|教我|讲解(?:一下)?|解释(?:一下)?|说明(?:一下)?)\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^(?:以及它|以及|并且|并|然后|再|它)\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return normalize_focus_candidate(cleaned)

    def rewrite_resource_lookup_terms(value: object) -> str:
        cleaned = normalize_focus_candidate(value)
        if not cleaned:
            return ""
        rewritten = cleaned
        replacements = (
            ("Coach 视图", "Coach view"),
            ("Plan 视图", "Plan view"),
            ("Resources 视图", "Resources view"),
            ("Training 视图", "Training view"),
            ("Settings 视图", "Settings view"),
            ("对话视图", "Coach view"),
            ("计划视图", "Plan view"),
            ("资料视图", "Resources view"),
            ("资源视图", "Resources view"),
            ("训练视图", "Training view"),
            ("设置视图", "Settings view"),
            ("首屏承诺", "first viewport promise"),
            ("首屏", "first viewport"),
            ("绝不能变成", "must not become"),
            ("不能变成", "must not become"),
            ("不能成为", "must not become"),
            ("不应该变成", "must not become"),
            ("设计文档", "design doc"),
            ("设计规范", "design spec"),
            ("规范文档", "design spec"),
            ("原始文件系统浏览器", "raw filesystem browser"),
            ("文件系统浏览器", "filesystem browser"),
            ("可追溯", "provenance"),
        )
        for source, target in replacements:
            rewritten = rewritten.replace(source, target)
        return normalize_focus_candidate(rewritten)

    def canonical_resource_view_terms(message: str | None) -> list[str]:
        normalized_message = str(message or "")
        lowered = normalized_message.lower()
        view_markers = (
            (("coach view", "coach 视图", "对话视图"), "Coach"),
            (("plan view", "plan 视图", "计划视图"), "Plan"),
            (
                ("resources view", "resource view", "resources 视图", "resource 视图", "资料视图", "资源视图"),
                "Resources",
            ),
            (("training view", "training 视图", "训练视图"), "Training"),
            (("settings view", "settings 视图", "设置视图"), "Settings"),
        )
        resolved: list[str] = []
        for markers, canonical in view_markers:
            if any(marker in lowered for marker in markers):
                resolved.append(canonical)
        return resolved

    def mapped_resource_lookup_phrases(message: str | None) -> list[str]:
        normalized_message = str(message or "")
        lowered = normalized_message.lower()
        mappings = (
            ("首屏承诺", "first viewport promise"),
            ("首屏", "first viewport"),
            ("绝不能变成", "must not become"),
            ("不能变成", "must not become"),
            ("不能成为", "must not become"),
            ("不应该变成", "must not become"),
            ("原始文件系统浏览器", "raw filesystem browser"),
            ("文件系统浏览器", "filesystem browser"),
            ("可追溯", "provenance"),
        )
        resolved: list[str] = []
        for source, target in mappings:
            if source in normalized_message:
                resolved.append(target)
        if "first viewport" in lowered and "promise" in lowered:
            resolved.append("first viewport promise")
        if "first viewport" in lowered:
            resolved.append("first viewport")
        if "promise" in lowered:
            resolved.append("promise")
        if "must not become" in lowered:
            resolved.append("must not become")
        if "raw filesystem browser" in lowered:
            resolved.append("raw filesystem browser")
        return resolved

    def resource_contract_stream_recovery_requested(message: str | None) -> bool:
        """Allow a grounded non-stream recovery only after the live stream fails."""

        if not canonical_resource_view_terms(message):
            return False
        facets = {
            str(item or "").strip().casefold()
            for item in mapped_resource_lookup_phrases(message)
            if str(item or "").strip()
        }
        return {"first viewport promise", "must not become"}.issubset(facets)

    def latin_resource_lookup_tokens(message: str | None) -> list[str]:
        normalized_message = str(message or "")
        stopwords = {
            "a",
            "an",
            "and",
            "are",
            "be",
            "can",
            "could",
            "directly",
            "do",
            "does",
            "for",
            "how",
            "i",
            "in",
            "is",
            "it",
            "me",
            "my",
            "of",
            "or",
            "please",
            "show",
            "tell",
            "the",
            "through",
            "to",
            "walk",
            "what",
            "why",
            "you",
        }
        resolved: list[str] = []
        seen_tokens: set[str] = set()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9._:/-]{0,40}", normalized_message):
            lowered = token.lower()
            if lowered in stopwords or lowered in seen_tokens:
                continue
            seen_tokens.add(lowered)
            resolved.append(token)
        return resolved

    def resource_lookup_clause_describes_import_action(value: object) -> bool:
        cleaned = normalize_focus_candidate(value)
        if not cleaned:
            return False
        lowered = cleaned.lower()
        import_markers = (
            "import",
            "imported",
            "upload",
            "uploaded",
            "导入",
            "上传",
        )
        document_markers = (
            "design doc",
            "design document",
            "design spec",
            "document",
            "markdown",
            "设计文档",
            "设计规范",
            "规范文档",
            "文档",
        )
        learning_markers = (
            "coach",
            "plan",
            "resources",
            "training",
            "settings",
            "remote",
            "debug",
            "function",
            "api",
            "protocol",
            "contract",
            "guide",
            "view",
            "first viewport",
            "promise",
            "must not become",
            "对话",
            "计划",
            "资料",
            "资源",
            "训练",
            "设置",
            "远程",
            "调试",
            "函数",
            "协议",
            "首屏",
            "承诺",
        )
        return (
            any(marker in lowered for marker in import_markers)
            and any(marker in lowered for marker in document_markers)
            and not any(marker in lowered for marker in learning_markers)
        )

    def resource_lookup_query_candidates(message: str | None) -> list[str]:
        normalized_message = normalize_focus_candidate(message)
        if not normalized_message:
            return []

        candidates: list[str] = []
        seen_candidates: set[str] = set()

        def add_candidate(value: object) -> None:
            stripped = strip_resource_lookup_lead_in(value)
            cleaned = normalize_focus_candidate(stripped)
            if not cleaned:
                return
            lowered = cleaned.lower()
            if lowered in seen_candidates:
                return
            seen_candidates.add(lowered)
            candidates.append(cleaned)

        focus_hint = extract_focus_hint_from_message(normalized_message)
        if (
            focus_hint
            and not focus_looks_like_request_sentence(focus_hint)
            and not resource_lookup_clause_describes_import_action(focus_hint)
        ):
            add_candidate(focus_hint)
            rewritten_focus = rewrite_resource_lookup_terms(focus_hint)
            if rewritten_focus and rewritten_focus.lower() != focus_hint.lower():
                add_candidate(rewritten_focus)

        clauses = [
            normalize_focus_candidate(part)
            for part in re.split(r"[，,。！？!?；;\n]+", normalized_message)
        ]
        for clause in clauses:
            if not clause:
                continue
            if resource_lookup_clause_describes_import_action(clause):
                continue
            add_candidate(clause)
            rewritten_clause = rewrite_resource_lookup_terms(clause)
            if rewritten_clause and rewritten_clause.lower() != clause.lower():
                add_candidate(rewritten_clause)

        composite_terms: list[str] = []
        for term in canonical_resource_view_terms(normalized_message):
            if term not in composite_terms:
                composite_terms.append(term)
        for term in mapped_resource_lookup_phrases(normalized_message):
            if term not in composite_terms:
                composite_terms.append(term)
        for term in latin_resource_lookup_tokens(rewrite_resource_lookup_terms(normalized_message) or normalized_message):
            if term not in composite_terms:
                composite_terms.append(term)
            if len(composite_terms) >= 8:
                break
        if composite_terms:
            add_candidate(" ".join(composite_terms))

        rewritten_message = rewrite_resource_lookup_terms(normalized_message)
        if rewritten_message and rewritten_message.lower() != normalized_message.lower():
            add_candidate(rewritten_message)

        add_candidate(normalized_message)
        return candidates

    def resolve_focus_hint(
        *,
        user_message: str | None,
        candidates: list[object],
        fallback_current_file: str | None = None,
        allow_message_prefix: bool = True,
    ) -> str | None:
        def anchor_admissible(value: object) -> bool:
            cleaned = normalize_focus_candidate(value)
            if not cleaned:
                return False
            if allow_message_prefix:
                return True
            # Memory-anchor path (2026-10-08 + real-model maturity runs): a
            # narration opening ("我的脚本 assert 失败了", "我亲自写了下面的
            # 修改（用 None 哨兵") is the learner's phrasing — coach_context
            # may still carry it as focus chrome, but it must never win the
            # persisted anchor over the grounded current-file/task focus.
            return not looks_like_narration_opening(cleaned)

        for candidate in candidates:
            if is_specific_focus_candidate(candidate) and anchor_admissible(candidate):
                return normalize_focus_candidate(candidate)
        extracted = extract_focus_hint_from_message(
            user_message,
            allow_message_prefix=allow_message_prefix,
        )
        if extracted:
            return extracted
        if fallback_current_file:
            file_focus = normalize_focus_candidate(fallback_current_file)
            if file_focus:
                return file_focus
        for candidate in candidates:
            if anchor_admissible(candidate):
                return normalize_focus_candidate(candidate)
        return None

    def resolve_turn_focus_hint(
        *,
        user_message: str | None,
        current_file_name: str | None = None,
        task_focus: str | None = None,
        stage_focus: str | None = None,
    ) -> str:
        if message_deserves_library_first_lookup(user_message):
            for candidate in resource_lookup_query_candidates(user_message):
                cleaned = normalize_focus_candidate(candidate)
                if cleaned and not resource_lookup_clause_describes_import_action(cleaned):
                    return cleaned
        extracted = extract_focus_hint_from_message(user_message)
        if extracted:
            # Memory-anchor anti-drift (real-model maturity runs): a narration
            # first clause ("我的脚本 assert 失败了", "我亲自写了下面的修改")
            # is the learner's phrasing, not a topic label — fall through to
            # the grounded current-file/task/stage focus instead.
            if not looks_like_narration_opening(extracted):
                return extracted
        for candidate in (current_file_name, task_focus, stage_focus):
            cleaned = normalize_focus_candidate(candidate)
            if cleaned:
                return cleaned
        return ""

    def function_guidance_current_file_name(
        current_file: object | None,
        *,
        scenario: str | None,
    ) -> str:
        current_file_payload = normalize_current_file_payload(current_file)
        if current_file_payload is None:
            return ""
        current_file_name = (
            str(current_file_payload.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1]
        )
        if scenario == "function_guidance" and not is_code_like_current_file(current_file_payload):
            return ""
        return current_file_name

    def function_guidance_entry_points(
        entry_points: object | None,
        *,
        scenario: str | None,
    ) -> list[str]:
        if not isinstance(entry_points, list) or not entry_points:
            return []
        cleaned_entry_points = [str(item).strip() for item in entry_points if str(item).strip()]
        if scenario != "function_guidance":
            return cleaned_entry_points
        return [entry_point for entry_point in cleaned_entry_points if is_code_like_entry_point(entry_point)]

    def function_guidance_starter_language(
        message: str | None,
        current_file: object | None,
        coach_context: dict[str, object] | None = None,
    ) -> str:
        current_file_payload = normalize_current_file_payload(current_file)
        language_hint = ""
        if isinstance(current_file_payload, dict):
            language_hint = str(current_file_payload.get("language_id") or "").strip().lower()
        if not language_hint and isinstance(coach_context, dict):
            language_hint = str(coach_context.get("language_id") or "").strip().lower()
        if any(token in language_hint for token in ("python", "py", "ipynb")):
            return "python"
        if any(
            token in language_hint
            for token in ("typescript", "javascript", "tsx", "jsx", "ts", "js", "node")
        ):
            return "typescript"

        lowered_message = str(message or "").lower()
        if any(
            token in lowered_message
            for token in ("python", "pytest", "fastapi", "asyncio", "pydantic", "django", "uvicorn")
        ):
            return "python"
        if any(
            token in lowered_message
            for token in (
                "typescript",
                "javascript",
                "fetch",
                "node",
                "react",
                "next.js",
                "nextjs",
                "npm",
            )
        ):
            return "typescript"

        preferred_stack = str(coach_context.get("preferred_stack") or "").lower() if isinstance(coach_context, dict) else ""
        if "python" in preferred_stack:
            return "python"
        return "typescript"

    def function_guidance_starter_specs(language: str) -> dict[str, object]:
        if language == "python":
            relative_root = "knowledge/function-guidance/python"
            definition_path = f"{relative_root}/client.py"
            call_site_path = f"{relative_root}/usage.py"
            return {
                "language_id": "python",
                "label": "Trainer function guidance starter (Python)",
                "relative_root": relative_root,
                "definition_path": definition_path,
                "call_site_path": call_site_path,
                "definition_symbol": "build_headers",
                "call_site_symbol": "build_headers",
                "definition_content": (
                    "from collections.abc import Mapping\n\n"
                    "def build_headers(\n"
                    "    token: str | None,\n"
                    "    extra: Mapping[str, str] | None = None,\n"
                    ") -> dict[str, str]:\n"
                    "    headers = {\"Accept\": \"application/json\"}\n"
                    "    if token:\n"
                    "        headers[\"Authorization\"] = f\"Bearer {token}\"\n"
                    "    if extra:\n"
                    "        headers.update(dict(extra))\n"
                    "    return headers\n"
                ),
                "call_site_content": (
                    "from client import build_headers\n\n"
                    "def load_user(user_id: str, token: str | None) -> dict[str, object]:\n"
                    "    headers = build_headers(token, {\"X-User-Id\": user_id})\n"
                    "    return {\n"
                    "        \"path\": f\"/users/{user_id}\",\n"
                    "        \"headers\": headers,\n"
                    "    }\n"
                ),
            }

        relative_root = "knowledge/function-guidance/typescript/src"
        definition_path = f"{relative_root}/client.ts"
        call_site_path = f"{relative_root}/usage.ts"
        return {
            "language_id": "typescript",
            "label": "Trainer function guidance starter (TypeScript)",
            "relative_root": "knowledge/function-guidance/typescript",
            "definition_path": definition_path,
            "call_site_path": call_site_path,
            "definition_symbol": "fetchJson",
            "call_site_symbol": "fetchJson",
            "definition_content": (
                "export type FetchJsonOptions = {\n"
                "  method?: \"GET\" | \"POST\";\n"
                "  headers?: Record<string, string>;\n"
                "  retry?: number;\n"
                "};\n\n"
                "export async function fetchJson<T>(\n"
                "  url: string,\n"
                "  options: FetchJsonOptions = {},\n"
                "): Promise<T> {\n"
                "  const response = await fetch(url, {\n"
                "    method: options.method ?? \"GET\",\n"
                "    headers: options.headers,\n"
                "  });\n"
                "  if (!response.ok) {\n"
                "    throw new Error(`Request failed: ${response.status}`);\n"
                "  }\n"
                "  return (await response.json()) as T;\n"
                "}\n"
            ),
            "call_site_content": (
                "import { fetchJson } from \"./client\";\n\n"
                "type User = {\n"
                "  id: string;\n"
                "  name: string;\n"
                "};\n\n"
                "export async function loadUser(userId: string): Promise<User> {\n"
                "  return fetchJson<User>(`/api/users/${userId}`, {\n"
                "    headers: { \"x-trace-id\": userId },\n"
                "    retry: 1,\n"
                "  });\n"
                "}\n"
            ),
        }

    def should_prepare_function_guidance_starter(
        *,
        scenario: str | None,
        current_file: object | None,
        coach_context: dict[str, object] | None,
    ) -> bool:
        if scenario != "function_guidance":
            return False
        if function_guidance_current_file_name(current_file, scenario=scenario):
            return False
        if not isinstance(coach_context, dict):
            return False
        if isinstance(coach_context.get("function_guidance_starter"), dict):
            return False
        project_entry_points = function_guidance_entry_points(
            coach_context.get("project_entry_points"),
            scenario=scenario,
        )
        return not project_entry_points

    def prepare_function_guidance_starter(
        *,
        workspace_id: str,
        message: str | None,
        current_file: object | None,
        coach_context: dict[str, object] | None,
        response_language: str | None,
    ) -> dict[str, object] | None:
        sandbox_service = runtime.sandbox_service
        if sandbox_service is None:
            return None
        starter_language = function_guidance_starter_language(
            message,
            current_file,
            coach_context,
        )
        spec = function_guidance_starter_specs(starter_language)
        definition_preview = sandbox_service.write(
            workspace_id,
            SandboxWriteRequest(
                workspace_id=workspace_id,
                path=str(spec["definition_path"]),
                content=str(spec["definition_content"]),
                create=True,
            ),
        )
        call_site_preview = sandbox_service.write(
            workspace_id,
            SandboxWriteRequest(
                workspace_id=workspace_id,
                path=str(spec["call_site_path"]),
                content=str(spec["call_site_content"]),
                create=True,
            ),
        )
        sandbox_root = sandbox_service.ensure_workspace_root(workspace_id)
        definition_symbol = str(spec["definition_symbol"])
        return {
            "status": "ready",
            "label": str(spec["label"]),
            "language_id": str(spec["language_id"]),
            "relative_root": str(spec["relative_root"]),
            "workspace_root_path": str(sandbox_root),
            "definition_symbol": definition_symbol,
            "call_site_symbol": str(spec["call_site_symbol"]),
            "definition_path": definition_preview.relative_path or str(spec["definition_path"]),
            "call_site_path": call_site_preview.relative_path or str(spec["call_site_path"]),
            "definition_content": definition_preview.content or str(spec["definition_content"]),
            "call_site_content": call_site_preview.content or str(spec["call_site_content"]),
            "definition_excerpt": definition_preview.excerpt or str(spec["definition_content"]),
            "call_site_excerpt": call_site_preview.excerpt or str(spec["call_site_content"]),
            "boundary_note": localized_text(
                "Trainer-owned sandbox starter. Use it as a practice scaffold until a real project call site is available.",
                "这是 Trainer 自己管理的 sandbox starter。在真实项目里的 call site 就位之前，先把它当成练习脚手架。",
                response_language,
            ),
            "coach_instruction": localized_text(
                "Use this starter as the live call site for learn-first teaching instead of asking the learner for project code first.",
                "先用这个 starter 当作 live call site 来教学，不要一上来就要求学习者先提供项目代码。",
                response_language,
            ),
            "suggested_sequence": localized_actions(
                response_language,
                [
                    f"Open `{call_site_preview.relative_path or spec['call_site_path']}` and place the cursor on `{definition_symbol}`.",
                    "Use hover first, then signature help inside the argument list.",
                    f"Jump to definition in `{definition_preview.relative_path or spec['definition_path']}` and name the parameter and return contract.",
                ],
                [
                    f"先打开 `{call_site_preview.relative_path or spec['call_site_path']}`，把光标放到 `{definition_symbol}` 上。",
                    "先看 hover，再在参数位置里看 signature help。",
                    f"再跳到 `{definition_preview.relative_path or spec['definition_path']}` 的 definition，说明参数 contract 和返回 contract。",
                ],
            ),
        }

    def detect_provider_language_corruption(
        coaching_service: ProviderService,
        *,
        message: str | None,
        response_language: str | None,
        coach_context: dict[str, object] | None = None,
    ):
        provider_config = getattr(coaching_service, "_config", None)
        provider_api_key = getattr(coaching_service, "_api_key", None)
        if (
            provider_config is None
            or not provider_api_key
            or not should_probe_language_integrity(message, response_language)
        ):
            return None
        if message_requests_lane_continuation(message):
            return None
        if coach_context_has_prepared_library_grounding(coach_context):
            return None
        if coaching_service.has_recent_language_integrity_success(
            message=message,
            response_language=response_language,
        ):
            return None
        probe_result = coaching_service.test(
            provider_config,
            provider_api_key,
            probe_message=message,
            response_language=response_language,
        )
        if (
            not probe_result.ok
            and probe_result.error_category == "language_corruption"
            and probe_result.provider_reachable is True
            and isinstance(probe_result.status_code, int)
        ):
            return probe_result
        return None

    def isolate_preflight_language_corruption_turn(
        coach_turn: dict[str, object],
        *,
        message: str | None,
        current_file: dict[str, object] | None,
    ) -> dict[str, object]:
        if message_requests_lane_continuation(message):
            return coach_turn

        scenario = infer_message_coaching_scenario(
            str(message or ""),
            current_file,
            {"history_mode": "fresh_lane"},
            default="general",
        )
        context = normalized_object_mapping(coach_turn.get("coach_context")) or {}
        context.update(
            {
                "scenario": scenario,
                "active_thread": None,
                "history_mode": "fresh_lane",
            }
        )
        return {
            **coach_turn,
            "scenario": scenario,
            "coach_context": context,
        }

    def recover_guided_language_corruption(
        *,
        coaching_service: ProviderService,
        snapshot: WorkbenchSnapshot,
        coach_turn: dict[str, object],
        message: str | None,
        response_language: str | None,
        detail: str = "",
        failure: dict[str, object] | None = None,
    ) -> tuple[str, dict[str, object], dict[str, object]] | None:
        coach_context = normalized_object_mapping(coach_turn.get("coach_context"))
        recovery_override = _build_language_corruption_recovery_override(
            str(message or ""),
            current_file=None,
            coach_context=coach_context,
            response_language=response_language,
        )
        if not isinstance(recovery_override, dict):
            return None

        scenario = str(
            coach_turn.get("scenario") or recovery_override.get("scenario") or ""
        ).strip()
        if not scenario:
            return None

        summary = str(recovery_override.get("summary") or "").strip()
        if not summary:
            summary = coaching_service.language_corruption_summary(
                response_language,
                scenario=scenario,
            )

        next_step = str(recovery_override.get("next_step") or "").strip()
        if not next_step:
            next_step = coaching_service.language_corruption_next_step(
                response_language,
                scenario=scenario,
            )

        teaching_note = str(recovery_override.get("teaching_note") or "").strip()
        if not teaching_note:
            teaching_note = localized_text(
                "Keep the same coaching lane and turn the next move into one local, verifiable step.",
                "\u7ee7\u7eed\u7559\u5728\u540c\u4e00\u6761\u6559\u7ec3\u4e3b\u7ebf\u91cc\uff0c\u628a\u4e0b\u4e00\u6b65\u6536\u675f\u6210\u4e00\u4e2a\u672c\u5730\u53ef\u9a8c\u8bc1\u7684\u5c0f\u52a8\u4f5c\u3002",
                response_language,
            )

        resume_thread = str(recovery_override.get("resume_thread") or "").strip()
        reply = str(recovery_override.get("reply") or "").strip()

        if message_requests_lane_continuation(message):
            local_resume_step = resolve_local_continuation_step(
                snapshot=snapshot,
                coach_turn=coach_turn,
                fallback_next_step=next_step,
            )
            if not local_resume_step:
                local_resume_step = local_continuation_step_for_scenario(
                    scenario,
                    response_language,
                )
            if local_resume_step:
                next_step = local_resume_step
                teaching_note = localized_text(
                    "Keep the same learning lane. When a short continuation is corrupted, resume from the saved thread locally and verify the next visible move.",
                    "\u7ee7\u7eed\u7559\u5728\u540c\u4e00\u6761\u5b66\u4e60\u4e3b\u7ebf\u91cc\u3002\u5f53\u77ed continuation \u88ab\u7834\u574f\u65f6\uff0c\u5148\u4ece\u5df2\u4fdd\u5b58\u7684 thread \u5728\u672c\u5730\u7eed\u4e0a\uff0c\u518d\u9a8c\u8bc1\u4e0b\u4e00\u4e2a\u53ef\u89c1\u52a8\u4f5c\u3002",
                    response_language,
                )
                resume_thread = localized_text(
                    f"Continue the saved coaching thread. Next: {next_step}",
                    f"\u7ee7\u7eed\u6cbf\u7740\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u63a8\u8fdb\u3002\u4e0b\u4e00\u6b65\uff1a{next_step}",
                    response_language,
                )
                reply = localized_text(
                    f"{summary}\n\nThe provider did not preserve this short continuation cleanly, so Trainer resumed the saved thread locally instead of repeating the provider setup blocker.\n\nNext step: {next_step}",
                    f"{summary}\n\nprovider \u6ca1\u6709\u7a33\u5b9a\u4fdd\u7559\u8fd9\u6761\u5f88\u77ed\u7684 continuation\uff0c\u6240\u4ee5 Trainer \u5148\u6309\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u5728\u672c\u5730\u7eed\u4e0a\uff0c\u4e0d\u518d\u91cd\u590d provider \u914d\u7f6e\u963b\u585e\u3002\n\n\u4e0b\u4e00\u6b65\uff1a{next_step}",
                    response_language,
                )

        if not resume_thread:
            resume_thread = build_resume_thread_text(
                summary,
                next_step,
                response_language=response_language,
            )
        if not reply:
            reply = summary

        if snapshot.coaching_state:
            snapshot.coaching_state = snapshot.coaching_state.model_copy(
                update={
                    "summary": summary,
                    "next_step": next_step,
                    "resume_thread": resume_thread,
                }
            )

        blocker = detail or summary
        meta: dict[str, object] = {
            "summary": summary,
            "next_step": next_step,
            "blocker": blocker,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
            "scenario": scenario,
            "stop_reason": str(
                recovery_override.get("stop_reason") or "language_corruption_recovered"
            ).strip()
            or "language_corruption_recovered",
            "fell_back": True,
        }
        if detail:
            meta["detail"] = detail
        if isinstance(failure, dict):
            meta.update(
                {
                    "error_category": str(
                        failure.get("error_category") or "language_corruption"
                    ).strip()
                    or "language_corruption",
                    "retryable": bool(failure.get("retryable")),
                    "status_code": failure.get("status_code"),
                    "provider_reachable": failure.get("provider_reachable"),
                    "model_supported": failure.get("model_supported"),
                }
            )

        return (
            reply,
            ensure_coach_turn_payload(
                merge_agent_finalize_into_coach_turn(
                    coach_turn,
                    summary=summary,
                    next_step=next_step,
                    blocker=blocker,
                    resume_thread=resume_thread,
                    teaching_note=teaching_note,
                ),
                coach_turn,
            ),
            meta,
        )

    def apply_language_corruption_override(
        *,
        coaching_service: ProviderService,
        snapshot: WorkbenchSnapshot,
        coach_turn: dict[str, object],
        message: str | None,
        response_language: str | None,
        reply_corruption: bool = False,
        allow_guided_recovery: bool = True,
    ) -> tuple[str, dict[str, object], dict[str, object]]:
        scenario = str(coach_turn.get("scenario") or "").strip()
        normalized_message = str(message or "").strip().lower()
        coach_context = normalized_object_mapping(coach_turn.get("coach_context")) or {}
        fresh_lane = str(coach_context.get("history_mode") or "").strip().lower() == "fresh_lane"
        if (
            scenario == "general"
            and normalized_message
            and any(
                token in normalized_message
                for token in (
                    "prototype",
                    "mvp",
                    "i have an idea",
                    "turn this idea into",
                    "make it real",
                    "\u843d\u5730",
                    "\u539f\u578b",
                    "\u6700\u5c0f\u539f\u578b",
                    "\u6700\u5c0f\u53ef\u9a8c\u8bc1",
                    "\u505a\u51fa\u6765",
                    "\u505a\u6210\u539f\u578b",
                    "\u60f3\u5b9e\u73b0",
                    "\u60f3\u505a",
                    "\u6211\u6709\u4e2aidea",
                    "\u6211\u6709\u4e00\u4e2aidea",
                    "\u6211\u6709\u4e2aai idea",
                    "\u6211\u6709\u4e00\u4e2aai idea",
                )
            )
        ):
            scenario = "idea_implementation"
            coach_turn = dict(coach_turn)
            coach_turn["scenario"] = scenario
        if scenario == "general":
            active_thread = coach_context.get("active_thread")
            scenario = inherit_active_thread_scenario_for_continuation(
                scenario,
                message=message,
                active_thread=(
                    active_thread
                    if isinstance(active_thread, dict)
                    else snapshot.memory.active_thread
                ),
            )
            if str(coach_turn.get("scenario") or "").strip() != scenario:
                coach_turn = dict(coach_turn)
                coach_turn["scenario"] = scenario
        if scenario == "general" and not fresh_lane:
            latest_user_message = ""
            for historical_message in reversed(snapshot.messages):
                role = str(getattr(historical_message, "role", "") or "").strip().lower()
                if role != "user":
                    continue
                latest_user_message = str(
                    getattr(historical_message, "content", "") or ""
                ).strip()
                if latest_user_message:
                    break
            if latest_user_message:
                inferred_scenario = infer_message_coaching_scenario(
                    latest_user_message,
                    None,
                    normalized_object_mapping(coach_turn.get("coach_context")),
                )
                if inferred_scenario and inferred_scenario != "general":
                    scenario = inferred_scenario
                    coach_turn = dict(coach_turn)
                    coach_turn["scenario"] = scenario
        if str(coach_turn.get("scenario") or "").strip() != scenario:
            coach_turn = dict(coach_turn)
            coach_turn["scenario"] = scenario
        if allow_guided_recovery:
            recovered_override = recover_guided_language_corruption(
                coaching_service=coaching_service,
                snapshot=snapshot,
                coach_turn=coach_turn,
                message=message,
                response_language=response_language,
            )
            if recovered_override is not None:
                return recovered_override
        if reply_corruption:
            summary = coaching_service.provider_failure_summary(
                "language_corruption",
                response_language,
            )
            next_step = coaching_service.provider_failure_next_step(
                "language_corruption",
                response_language,
            )
        else:
            summary = coaching_service.language_corruption_summary(
                response_language,
                scenario=scenario,
            )
            next_step = coaching_service.language_corruption_next_step(
                response_language,
                scenario=scenario,
            )
        blocker = summary
        if message_requests_lane_continuation(message):
            local_resume_step = resolve_local_continuation_step(
                snapshot=snapshot,
                coach_turn=coach_turn,
                fallback_next_step=next_step,
            )
            if not local_resume_step:
                local_resume_step = local_continuation_step_for_scenario(
                    scenario,
                    response_language,
                )
            if local_resume_step:
                next_step = local_resume_step
                teaching_note = localized_text(
                    "Keep the same learning lane. When a short continuation is corrupted, resume from the saved thread locally and verify the next visible move.",
                    "\u7ee7\u7eed\u7559\u5728\u540c\u4e00\u6761\u5b66\u4e60\u4e3b\u7ebf\u91cc\u3002\u5f53\u77ed continuation \u88ab\u7834\u574f\u65f6\uff0c\u5148\u4ece\u5df2\u4fdd\u5b58\u7684 thread \u5728\u672c\u5730\u7eed\u4e0a\uff0c\u518d\u9a8c\u8bc1\u4e0b\u4e00\u4e2a\u53ef\u89c1\u52a8\u4f5c\u3002",
                    response_language,
                )
                resume_thread = localized_text(
                    f"Continue the saved coaching thread. Next: {next_step}",
                    f"\u7ee7\u7eed\u6cbf\u7740\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u63a8\u8fdb\u3002\u4e0b\u4e00\u6b65\uff1a{next_step}",
                    response_language,
                )
                if snapshot.coaching_state:
                    snapshot.coaching_state = snapshot.coaching_state.model_copy(
                        update={
                            "summary": summary,
                            "next_step": next_step,
                            "resume_thread": resume_thread,
                        }
                    )
                return (
                    localized_text(
                        f"{summary}\n\nThe provider did not preserve this short continuation cleanly, so Trainer resumed the saved thread locally instead of repeating the provider setup blocker.\n\nNext step: {next_step}",
                        f"{summary}\n\nprovider \u6ca1\u6709\u7a33\u5b9a\u4fdd\u7559\u8fd9\u6761\u5f88\u77ed\u7684 continuation\uff0c\u6240\u4ee5 Trainer \u5148\u6309\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u5728\u672c\u5730\u7eed\u4e0a\uff0c\u4e0d\u518d\u91cd\u590d provider \u914d\u7f6e\u963b\u585e\u3002\n\n\u4e0b\u4e00\u6b65\uff1a{next_step}",
                        response_language,
                    ),
                    ensure_coach_turn_payload(
                        merge_agent_finalize_into_coach_turn(
                            coach_turn,
                            summary=summary,
                            next_step=next_step,
                            blocker=blocker,
                            resume_thread=resume_thread,
                            teaching_note=teaching_note,
                        ),
                        coach_turn,
                    ),
                    {
                        "summary": summary,
                        "next_step": next_step,
                        "blocker": blocker,
                        "teaching_note": teaching_note,
                        "resume_thread": resume_thread,
                        "scenario": scenario,
                        "stop_reason": "language_corruption",
                        "fell_back": True,
                    },
                )
        teaching_note = localized_text(
            "Pause the lesson until the provider path preserves the original sentence.",
            "\u5148\u8ba9 provider \u94fe\u8def\u5b8c\u6574\u4fdd\u7559\u539f\u53e5\uff0c\u518d\u7ee7\u7eed\u8fd9\u6761\u6559\u5b66\u4e3b\u7ebf\u3002",
            response_language,
        )
        resume_thread = build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
        if snapshot.coaching_state:
            snapshot.coaching_state = snapshot.coaching_state.model_copy(
                update={
                    "summary": summary,
                    "next_step": next_step,
                    "resume_thread": resume_thread,
                }
            )
        return (
            coaching_service.provider_failure_reply(
                "language_corruption",
                None,
                response_language,
            )
            if reply_corruption
            else coaching_service.language_corruption_reply(
                response_language,
                scenario=scenario,
            ),
            ensure_coach_turn_payload(
                merge_agent_finalize_into_coach_turn(
                    coach_turn,
                    summary=summary,
                    next_step=next_step,
                    blocker=blocker,
                    resume_thread=resume_thread,
                    teaching_note=teaching_note,
                ),
                coach_turn,
            ),
            {
                "summary": summary,
                "next_step": next_step,
                "blocker": blocker,
                "teaching_note": teaching_note,
                "resume_thread": resume_thread,
                "scenario": scenario,
                "stop_reason": "language_corruption",
                "fell_back": True,
            },
        )

    PROVIDER_REPLY_STOP_REASONS = {
        "invalid_key_or_permission",
        "language_corruption",
        "model_unsupported",
        "model_not_found",
        "malformed_response",
        "truncated_or_empty",
        "rate_limit",
        "upstream_unavailable",
        "timeout",
        "network",
        "unknown",
    }

    # First-turn lanes ship a canonical, hand-composed next step; the grounding
    # retry must not replace that ruling with a model rewrite.
    DETERMINISTIC_LANE_SCENARIOS = {
        "remote_workspace",
        "debug_loop",
        "function_guidance",
        "project_adaptation",
    }

    NON_LEARNING_RECOVERY_STOP_REASONS = {
        *PROVIDER_REPLY_STOP_REASONS,
        "empty_response",
        "language_corruption_recovered",
        "max_steps",
        "no_progress",
        "provider_error",
    }

    def recovery_turn_has_no_learning_evidence(
        *,
        stop_reason: str | None,
        recovered_stop_reason: str | None = None,
        local_sequence_fallback: bool = False,
    ) -> bool:
        reasons = (
            str(stop_reason or "").strip(),
            str(recovered_stop_reason or "").strip(),
        )
        # A local sequence can still be a successful, evidence-bearing lesson.
        # Only the underlying provider/recovery reason makes the turn non-learning.
        return any(
            reason in NON_LEARNING_RECOVERY_STOP_REASONS or reason.startswith("agent_error")
            for reason in reasons
            if reason
        )

    def is_provider_recovery_thread_payload(active_thread: object | None) -> bool:
        """Identify a saved provider-recovery lane before it is normalized away."""
        if not isinstance(active_thread, dict):
            return False
        recovery_state = str(active_thread.get("recovery_state") or "").strip().lower()
        if recovery_state == "provider_or_local":
            return True
        combined = " ".join(
            str(active_thread.get(key) or "").strip().lower()
            for key in ("blocker", "next_step", "teaching_note")
        )
        return "provider" in combined and any(
            marker in combined
            for marker in (
                "gateway",
                "question mark",
                "question marks",
                "english",
            )
        )

    def provider_recovery_resumed_summary(response_language: str | None) -> str:
        return provider_recovery_resumed_summary_text(response_language)

    def provider_recovery_resumed_next_step(
        scenario: str,
        response_language: str | None,
    ) -> str:
        return provider_recovery_resumed_next_step_text(
            scenario,
            response_language,
        )

    def consume_provider_reply_failure_override(
        *,
        coaching_service: ProviderService,
        snapshot: WorkbenchSnapshot,
        coach_turn: dict[str, object],
        message: str | None,
        response_language: str | None,
        workspace_id: str | None = None,
    ) -> tuple[str, dict[str, object], dict[str, object]] | None:
        failure = coaching_service.consume_last_reply_failure()
        if not isinstance(failure, dict):
            return None
        category = str(failure.get("error_category") or "").strip() or "unknown"
        if category not in PROVIDER_REPLY_STOP_REASONS:
            return None
        detail = str(failure.get("detail") or "").strip()
        if category == "language_corruption":
            scenario = str(coach_turn.get("scenario") or "").strip()
            normalized_message = str(message or "").strip().lower()
            if (
                scenario == "general"
                and normalized_message
                and any(
                    token in normalized_message
                    for token in (
                        "prototype",
                        "mvp",
                        "i have an idea",
                        "turn this idea into",
                        "make it real",
                        "\u843d\u5730",
                        "\u539f\u578b",
                        "\u6700\u5c0f\u539f\u578b",
                        "\u6700\u5c0f\u53ef\u9a8c\u8bc1",
                        "\u505a\u51fa\u6765",
                        "\u505a\u6210\u539f\u578b",
                        "\u60f3\u5b9e\u73b0",
                        "\u60f3\u505a",
                        "\u6211\u6709\u4e2aidea",
                        "\u6211\u6709\u4e00\u4e2aidea",
                        "\u6211\u6709\u4e2aai idea",
                        "\u6211\u6709\u4e00\u4e2aai idea",
                    )
                )
            ):
                leftover_blocks_lane = bool(
                    workspace_id and recovered_overlay_without_live_object(workspace_id)
                )
                if not leftover_blocks_lane:
                    scenario = "idea_implementation"
                    coach_turn = dict(coach_turn)
                    coach_turn["scenario"] = scenario
            if scenario == "general":
                coach_context = coach_turn.get("coach_context")
                active_thread = (
                    coach_context.get("active_thread")
                    if isinstance(coach_context, dict)
                    else None
                )
                scenario = inherit_active_thread_scenario_for_continuation(
                    scenario,
                    message=message,
                    active_thread=(
                        active_thread
                        if isinstance(active_thread, dict)
                        else snapshot.memory.active_thread
                    ),
                )
                if str(coach_turn.get("scenario") or "").strip() != scenario:
                    coach_turn = dict(coach_turn)
                    coach_turn["scenario"] = scenario
            if scenario == "general":
                latest_user_message = ""
                for historical_message in reversed(snapshot.messages):
                    role = str(getattr(historical_message, "role", "") or "").strip().lower()
                    if role != "user":
                        continue
                    latest_user_message = str(
                        getattr(historical_message, "content", "") or ""
                    ).strip()
                    if latest_user_message:
                        break
                if latest_user_message:
                    inferred_scenario = infer_message_coaching_scenario(
                        latest_user_message,
                        None,
                        normalized_object_mapping(coach_turn.get("coach_context")),
                    )
                    if inferred_scenario and inferred_scenario != "general":
                        scenario = inferred_scenario
                        coach_turn = dict(coach_turn)
                        coach_turn["scenario"] = scenario
            if str(coach_turn.get("scenario") or "").strip() != scenario:
                coach_turn = dict(coach_turn)
                coach_turn["scenario"] = scenario
            recovered_override = recover_guided_language_corruption(
                coaching_service=coaching_service,
                snapshot=snapshot,
                coach_turn=coach_turn,
                message=message,
                response_language=response_language,
                detail=detail,
                failure=failure,
            )
            if recovered_override is not None:
                return recovered_override
            summary = coaching_service.provider_failure_summary(
                "language_corruption",
                response_language,
            )
            next_step = coaching_service.provider_failure_next_step(
                "language_corruption",
                response_language,
            )
            blocker = summary
            if message_requests_lane_continuation(message):
                local_resume_step = resolve_local_continuation_step(
                    snapshot=snapshot,
                    coach_turn=coach_turn,
                    fallback_next_step=next_step,
                )
                if not local_resume_step:
                    local_resume_step = local_continuation_step_for_scenario(
                        scenario,
                        response_language,
                    )
                if local_resume_step:
                    next_step = local_resume_step
                    teaching_note = localized_text(
                        "Keep the same learning lane. When a short continuation is corrupted, resume from the saved thread locally and verify the next visible move.",
                        "\u7ee7\u7eed\u7559\u5728\u540c\u4e00\u6761\u5b66\u4e60\u4e3b\u7ebf\u91cc\u3002\u5f53\u77ed continuation \u88ab\u7834\u574f\u65f6\uff0c\u5148\u4ece\u5df2\u4fdd\u5b58\u7684 thread \u5728\u672c\u5730\u7eed\u4e0a\uff0c\u518d\u9a8c\u8bc1\u4e0b\u4e00\u4e2a\u53ef\u89c1\u52a8\u4f5c\u3002",
                        response_language,
                    )
                    resume_thread = localized_text(
                        f"Continue the saved coaching thread. Next: {next_step}",
                        f"\u7ee7\u7eed\u6cbf\u7740\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u63a8\u8fdb\u3002\u4e0b\u4e00\u6b65\uff1a{next_step}",
                        response_language,
                    )
                    if snapshot.coaching_state:
                        snapshot.coaching_state = snapshot.coaching_state.model_copy(
                            update={
                                "summary": summary,
                                "next_step": next_step,
                                "resume_thread": resume_thread,
                            }
                        )
                    recovered_failure_meta: dict[str, object] = {
                        "summary": summary,
                        "next_step": next_step,
                        "blocker": blocker,
                        "teaching_note": teaching_note,
                        "resume_thread": resume_thread,
                        "scenario": scenario,
                        "stop_reason": category,
                        "error_category": category,
                        "detail": detail,
                        "retryable": bool(failure.get("retryable")),
                        "status_code": failure.get("status_code"),
                        "provider_reachable": failure.get("provider_reachable"),
                        "model_supported": failure.get("model_supported"),
                        "fell_back": True,
                    }
                    return (
                        localized_text(
                            f"{summary}\n\nThe provider did not preserve this short continuation cleanly, so Trainer resumed the saved thread locally instead of repeating the provider setup blocker.\n\nNext step: {next_step}",
                            f"{summary}\n\nprovider \u6ca1\u6709\u7a33\u5b9a\u4fdd\u7559\u8fd9\u6761\u5f88\u77ed\u7684 continuation\uff0c\u6240\u4ee5 Trainer \u5148\u6309\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u5728\u672c\u5730\u7eed\u4e0a\uff0c\u4e0d\u518d\u91cd\u590d provider \u914d\u7f6e\u963b\u585e\u3002\n\n\u4e0b\u4e00\u6b65\uff1a{next_step}",
                            response_language,
                        ),
                        ensure_coach_turn_payload(
                            merge_agent_finalize_into_coach_turn(
                                coach_turn,
                                summary=summary,
                                next_step=next_step,
                                blocker=blocker,
                                resume_thread=resume_thread,
                                teaching_note=teaching_note,
                            ),
                            coach_turn,
                        ),
                        recovered_failure_meta,
                    )
            teaching_note = localized_text(
                "Pause the lesson until the provider path preserves the original sentence.",
                "\u5148\u8ba9 provider \u94fe\u8def\u5b8c\u6574\u4fdd\u7559\u539f\u53e5\uff0c\u518d\u7ee7\u7eed\u8fd9\u6761\u6559\u5b66\u4e3b\u7ebf\u3002",
                response_language,
            )
            resume_thread = build_resume_thread_text(
                summary,
                next_step,
                response_language=response_language,
            )
            if snapshot.coaching_state:
                snapshot.coaching_state = snapshot.coaching_state.model_copy(
                    update={
                        "summary": summary,
                        "next_step": next_step,
                        "resume_thread": resume_thread,
                    }
                )
            language_failure_meta: dict[str, object] = {
                "summary": summary,
                "next_step": next_step,
                "blocker": blocker,
                "teaching_note": teaching_note,
                "resume_thread": resume_thread,
                "scenario": scenario,
                "stop_reason": category,
                "error_category": category,
                "detail": detail,
                "retryable": bool(failure.get("retryable")),
                "status_code": failure.get("status_code"),
                "provider_reachable": failure.get("provider_reachable"),
                "model_supported": failure.get("model_supported"),
                "fell_back": True,
            }
            return (
                coaching_service.provider_failure_reply(
                    "language_corruption",
                    detail,
                    response_language,
                ),
                ensure_coach_turn_payload(
                    merge_agent_finalize_into_coach_turn(
                        coach_turn,
                        summary=summary,
                        next_step=next_step,
                        blocker=blocker,
                        resume_thread=resume_thread,
                        teaching_note=teaching_note,
                    ),
                    coach_turn,
                ),
                language_failure_meta,
            )
        summary = coaching_service.provider_failure_summary(category, response_language)
        next_step = coaching_service.provider_failure_next_step(category, response_language)
        blocker = summary
        teaching_note = localized_text(
            "Keep the current plan and thread intact; unblock the provider path first, then resume from the same next step.",
            "\u5148\u4fdd\u6301\u5f53\u524d\u8ba1\u5212\u548c thread \u4e0d\u53d8\uff0c\u5148\u628a provider \u94fe\u8def\u4fee\u901a\uff0c\u518d\u4ece\u540c\u4e00\u4e2a\u4e0b\u4e00\u6b65\u7ee7\u7eed\u3002",
            response_language,
        )
        resume_thread = build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
        if snapshot.coaching_state:
            snapshot.coaching_state = snapshot.coaching_state.model_copy(
                update={
                    "summary": summary,
                    "next_step": next_step,
                    "resume_thread": resume_thread,
                }
            )
        provider_failure_meta: dict[str, object] = {
            "summary": summary,
            "next_step": next_step,
            "blocker": blocker,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
            "stop_reason": category,
            "error_category": category,
            "detail": detail,
            "retryable": bool(failure.get("retryable")),
            "status_code": failure.get("status_code"),
            "provider_reachable": failure.get("provider_reachable"),
            "model_supported": failure.get("model_supported"),
            "fell_back": True,
        }
        return (
            coaching_service.provider_failure_reply(
                category,
                None,
                response_language,
            ),
            ensure_coach_turn_payload(
                merge_agent_finalize_into_coach_turn(
                    coach_turn,
                    summary=summary,
                    next_step=next_step,
                    blocker=blocker,
                    resume_thread=resume_thread,
                    teaching_note=teaching_note,
                ),
                coach_turn,
            ),
            provider_failure_meta,
        )

    def build_empty_response_visible_reply(
        *,
        summary: object,
        next_step: object,
        response_language: str | None,
    ) -> str:
        summary_text = str(summary or "").strip() or localized_text(
            "The provider returned an empty visible answer, so this turn cannot be treated as complete.",
            "\u0070\u0072\u006f\u0076\u0069\u0064\u0065\u0072 \u8fd4\u56de\u4e86\u7a7a\u7684\u53ef\u89c1\u56de\u7b54\uff0c\u6240\u4ee5\u8fd9\u8f6e\u4e0d\u80fd\u7b97\u5b8c\u6210\u3002",
            response_language,
        )
        next_step_text = str(next_step or "").strip() or localized_text(
            "Retry the turn and require one visible, verifiable conclusion.",
            "\u91cd\u8bd5\u8fd9\u4e00\u8f6e\uff0c\u5e76\u8981\u6c42\u8fd4\u56de\u4e00\u4e2a\u53ef\u89c1\u3001\u53ef\u9a8c\u8bc1\u7684\u7ed3\u8bba\u3002",
            response_language,
        )
        return localized_text(
            (
                f"{summary_text}\n\n"
                "The provider returned an empty visible answer, so Trainer kept this turn "
                "recoverable instead of pretending the model completed it.\n\n"
                f"Next step: {next_step_text}"
            ),
            (
                f"{summary_text}\n\n"
                "\u0070\u0072\u006f\u0076\u0069\u0064\u0065\u0072 \u8fd4\u56de\u4e86\u7a7a\u7684\u53ef\u89c1\u56de\u7b54\uff0c\u6240\u4ee5 Trainer "
                "\u4f1a\u628a\u8fd9\u4e00\u8f6e\u4fdd\u6301\u4e3a\u53ef\u6062\u590d\u72b6\u6001\uff0c\u800c\u4e0d\u662f\u5047\u88c5 model "
                "\u5df2\u7ecf\u5b8c\u6210\u3002\n\n"
                f"\u4e0b\u4e00\u6b65\uff1a{next_step_text}"
            ),
            response_language,
        )
    def consume_provider_empty_reply_override(
        *,
        coaching_service: ProviderService,
        snapshot: WorkbenchSnapshot,
        coach_turn: dict[str, object],
        response_language: str | None,
        assistant_content: str,
    ) -> tuple[str, dict[str, object], dict[str, object]] | None:
        override = coaching_service.consume_last_reply_override()
        if not isinstance(override, dict):
            return None
        stop_reason = str(override.get("stop_reason") or "").strip()
        if stop_reason != "empty_response":
            return None
        summary = str(override.get("summary") or "").strip() or localized_text(
            "The provider returned an empty visible answer, so I kept the same coaching thread moving locally.",
            "provider \u8fd4\u56de\u4e86\u7a7a\u7684\u53ef\u89c1\u7b54\u6848\uff0c\u6240\u4ee5\u6211\u5148\u5728\u672c\u5730\u628a\u540c\u4e00\u6761\u6559\u7ec3 thread \u63a5\u7eed\u4e0b\u53bb\u3002",
            response_language,
        )
        next_step = str(override.get("next_step") or "").strip() or localized_text(
            "Retry the same turn and require one visible conclusion.",
            "\u91cd\u8bd5\u540c\u4e00\u8f6e\uff0c\u5e76\u8981\u6c42\u7ed9\u51fa\u4e00\u4e2a\u53ef\u89c1\u7ed3\u8bba\u3002",
            response_language,
        )
        blocker = str(override.get("blocker") or "").strip() or summary
        teaching_note = str(override.get("teaching_note") or "").strip() or localized_text(
            "Keep the same learning lane and ask for one visible, verifiable conclusion on the next turn.",
            "\u7ee7\u7eed\u7559\u5728\u540c\u4e00\u6761\u5b66\u4e60\u4e3b\u7ebf\u91cc\uff0c\u4e0b\u4e00\u8f6e\u53ea\u8981\u6c42\u4e00\u4e2a\u53ef\u89c1\u3001\u53ef\u9a8c\u8bc1\u7684\u7ed3\u8bba\u3002",
            response_language,
        )
        resume_thread = str(override.get("resume_thread") or "").strip() or build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
        if snapshot.coaching_state:
            snapshot.coaching_state = snapshot.coaching_state.model_copy(
                update={
                    "summary": summary,
                    "next_step": next_step,
                    "resume_thread": resume_thread,
                }
            )
        visible_reply = localized_text(
            f"{summary}\n\nThe provider returned an empty visible answer, so Trainer kept this turn recoverable instead of pretending the model completed it.\n\nNext step: {next_step}",
            f"{summary}\n\nprovider 返回了空的可见答案，所以 Trainer 先把这一轮保持为可恢复状态，而不是假装 model 已经完成。\n\n下一步：{next_step}",
            response_language,
        )
        visible_reply = build_empty_response_visible_reply(
            summary=summary,
            next_step=next_step,
            response_language=response_language,
        )
        empty_response_meta: dict[str, object] = {
            "summary": summary,
            "next_step": next_step,
            "blocker": blocker,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
            "stop_reason": "empty_response",
            "fell_back": True,
        }
        return (
            visible_reply,
            ensure_coach_turn_payload(
                merge_agent_finalize_into_coach_turn(
                    coach_turn,
                    summary=summary,
                    next_step=next_step,
                    blocker=blocker,
                    resume_thread=resume_thread,
                    teaching_note=teaching_note,
                ),
                coach_turn,
            ),
            empty_response_meta,
        )

    GUIDED_SEQUENCE_SCENARIOS = {"remote_workspace", "debug_loop", "function_guidance"}

    def coach_context_scenario_value(coach_context: dict[str, object] | None) -> str:
        if not isinstance(coach_context, dict):
            return ""
        raw_candidates: list[object] = [coach_context.get("scenario")]
        for key in ("coaching_state", "coach_context", "coach_turn"):
            nested = coach_context.get(key)
            if isinstance(nested, dict):
                raw_candidates.append(nested.get("scenario"))
        for candidate in raw_candidates:
            normalized = str(candidate or "").strip()
            if normalized:
                return normalized
        return ""

    def infer_sequence_guidance_scenario(sequence: dict[str, object] | None) -> str:
        if not isinstance(sequence, dict):
            return ""
        explicit = str(sequence.get("scenario") or "").strip()
        if explicit in GUIDED_SEQUENCE_SCENARIOS:
            return explicit
        evidence_bits = [
            str(sequence.get("title") or "").strip(),
            str(sequence.get("source") or "").strip(),
            str(sequence.get("boundary_sentinel") or "").strip(),
        ]
        raw_steps = sequence.get("steps")
        if isinstance(raw_steps, list):
            for item in raw_steps[:6]:
                if not isinstance(item, dict):
                    continue
                evidence_bits.append(str(item.get("label") or "").strip())
                evidence_bits.append(str(item.get("text") or item.get("body") or "").strip())
        inferred = infer_message_coaching_scenario(
            " ".join(bit for bit in evidence_bits if bit).strip(),
            default="general",
        )
        return inferred if inferred in GUIDED_SEQUENCE_SCENARIOS else ""

    def sequence_visible_follow_up_copy(
        scenario: str,
        *,
        title: str,
        response_language: str | None,
    ) -> tuple[str, str, str, str]:
        if scenario == "remote_workspace":
            close_line = localized_text(
                "For the smallest next move, tell me your current workspace label, path, or the exact step that feels unclear, and I'll keep coaching from this same sequence.",
                "现在先做最小验证：告诉我你当前的工作区标签、路径，或者你正卡在哪一步，我就按同一套顺序继续带你走。",
                response_language,
            )
            summary = f"Reuse the exact {title} sequence from the library and keep the reply grounded."
            next_step = "Ask for the learner's current workspace evidence or the exact step that feels unclear."
            teaching_note = "When the provider blanks, keep the same grounded sequence visible and continue from that lane."
            return close_line, summary, next_step, teaching_note
        if scenario == "debug_loop":
            close_line = localized_text(
                "For the smallest next move, tell me the breakpoint file, stack frame, watch value, or the exact debug-loop step that feels unclear, and I'll keep coaching from this same loop.",
                "现在先做最小验证：告诉我断点所在文件、当前 stack frame、watch value，或者 debug loop 里哪一步开始不符合预期，我就沿着同一条调试链继续带你走。",
                response_language,
            )
            summary = (
                f"Reuse the exact {title} sequence from the library and keep the reply anchored on the current VS Code debug loop."
            )
            next_step = (
                "Ask for the breakpoint file, current stack frame, watch value, or the exact debug-loop step that feels unclear."
            )
            teaching_note = (
                "When the provider blanks, keep the same debug loop visible and continue from the same breakpoint evidence."
            )
            return close_line, summary, next_step, teaching_note
        if scenario == "function_guidance":
            close_line = localized_text(
                "For the smallest next move, tell me the function name, one call site, or which hover / signature help / definition detail still feels unclear, and I'll keep coaching from this same function-guidance lane.",
                "现在先做最小验证：告诉我函数名、一个 call site，或者 hover / signature help / definition 里哪一处还没看懂，我就沿着同一条 function-guidance 主线继续带你走。",
                response_language,
            )
            summary = (
                f"Reuse the exact {title} sequence from the library and keep the reply anchored on one live call site."
            )
            next_step = (
                "Ask for the function name, one call site, or the hover / signature help / definition evidence that still feels unclear."
            )
            teaching_note = (
                "When the provider blanks, keep the same function-contract sequence visible and continue from one call site."
            )
            return close_line, summary, next_step, teaching_note
        close_line = localized_text(
            "For the smallest next move, tell me the exact step that feels unclear, and I'll keep coaching from this same sequence.",
            "现在先做最小验证：告诉我哪一步最不确定，我就沿着同一套顺序继续带你走。",
            response_language,
        )
        summary = f"Reuse the exact {title} sequence from the library and keep the reply visible."
        next_step = "Ask for the exact step that feels unclear."
        teaching_note = "When the provider blanks, keep the same sequence visible and continue from that lane."
        return close_line, summary, next_step, teaching_note

    def build_local_sequence_visible_fallback(
        *,
        coach_context: dict[str, object] | None,
        response_language: str | None,
    ) -> dict[str, str] | None:
        if not isinstance(coach_context, dict):
            return None
        raw_sequences = coach_context.get("resource_sequence_guidance")
        if not isinstance(raw_sequences, list) or not raw_sequences:
            return None
        first_sequence = raw_sequences[0]
        if not isinstance(first_sequence, dict):
            return None
        raw_steps = first_sequence.get("steps")
        if not isinstance(raw_steps, list):
            return None
        steps: list[tuple[str, str]] = []
        for item in raw_steps[:6]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            text = str(item.get("text") or item.get("body") or "").strip()
            if not label or not text:
                continue
            steps.append((label, text))
        if len(steps) < 2:
            return None
        title = str(first_sequence.get("title") or "the library sequence").strip()
        coach_scenario = coach_context_scenario_value(coach_context)
        sequence_scenario = infer_sequence_guidance_scenario(first_sequence)
        if (
            coach_scenario in GUIDED_SEQUENCE_SCENARIOS
            and sequence_scenario
            and sequence_scenario != coach_scenario
        ):
            return None
        effective_scenario = (
            coach_scenario
            if coach_scenario in GUIDED_SEQUENCE_SCENARIOS
            else sequence_scenario
        )
        boundary = str(first_sequence.get("boundary_sentinel") or "").strip()
        close_line, summary, next_step, teaching_note = sequence_visible_follow_up_copy(
            effective_scenario,
            title=title,
            response_language=response_language,
        )
        if prefers_chinese(response_language):
            lines = [f"我先按资料库里的原始顺序把 {title} 摆出来，不额外加步骤：", ""]
            for label, text in steps:
                lines.append(f"- **{label}**：{text}")
            if boundary:
                lines.append("")
                lines.append(f"边界哨兵：**{boundary}**。")
            lines.append("")
            lines.append(close_line)
        else:
            lines = [f"I'll restate the exact {title} sequence from the library before we continue:", ""]
            for label, text in steps:
                lines.append(f"- **{label}**: {text}")
            if boundary:
                lines.append("")
                lines.append(f"Boundary sentinel: **{boundary}**.")
            lines.append("")
            lines.append(close_line)
        reply = "\n".join(lines).strip()
        resume_thread = build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
        return {
            "reply": reply,
            "summary": summary,
            "next_step": next_step,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
        }

    def resource_reply_mentions_promise(reply: str) -> bool:
        lowered = str(reply or "").lower()
        if "first viewport promise" in lowered or "first viewport" in lowered:
            return True
        return any(token in reply for token in ("首屏", "第一视口")) and any(
            token in reply for token in ("承诺", "promise")
        )

    def resource_reply_mentions_boundary(reply: str) -> bool:
        lowered = str(reply or "").lower()
        if "must not become" in lowered or "raw filesystem browser" in lowered:
            return True
        has_boundary = any(
            token in reply
            for token in ("绝不能", "不能变成", "不能成为", "不应该变成", "不能退化成", "不能退化为")
        )
        has_target = any(
            token in lowered for token in ("raw filesystem browser", "filesystem browser", "cms")
        ) or any(token in reply for token in ("文件系统浏览器", "原始文件系统浏览器", "CMS"))
        return has_boundary and has_target

    def grounded_resource_contract_needs_repair(
        reply: str,
        *,
        coach_context: dict[str, object] | None,
    ) -> bool:
        if not isinstance(coach_context, dict):
            return False
        if coach_context_scenario_value(coach_context) != "principle":
            return False
        raw_facets = coach_context.get("resource_question_facets")
        facets = {
            str(item or "").strip().casefold()
            for item in raw_facets
            if str(item or "").strip()
        } if isinstance(raw_facets, list) else set()
        if not facets:
            return False
        if "first viewport promise" in facets and not resource_reply_mentions_promise(reply):
            return True
        if "must not become" in facets and not resource_reply_mentions_boundary(reply):
            return True
        return False

    def normalize_resource_contract_source_text(value: object) -> str:
        text = str(value or "").replace("\r\n", "\n").strip()
        if not text:
            return ""
        text = re.sub(r"</?mark>", "", text, flags=re.IGNORECASE)
        return text

    def ordered_resource_contract_candidates(
        workspace_id: str,
        *,
        agent_meta: dict[str, object] | None,
    ) -> list[ResourceRecord]:
        resources = runtime.resource_service.repository.list_resources(workspace_id)
        if not resources:
            return []
        by_id = {item.id: item for item in resources}
        by_title = {item.name.strip().lower(): item for item in resources if item.name.strip()}
        ordered: list[ResourceRecord] = []
        seen_ids: set[str] = set()

        tool_events = agent_meta.get("tool_events") if isinstance(agent_meta, dict) else None
        for event in tool_events if isinstance(tool_events, list) else []:
            if not isinstance(event, dict):
                continue
            if str(event.get("name") or "").strip() != "search_resources":
                continue
            result_payload = event.get("result")
            if not isinstance(result_payload, dict):
                continue
            hits = result_payload.get("hits")
            if not isinstance(hits, list):
                continue
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                resource_id = str(hit.get("resource_id") or hit.get("id") or "").strip()
                title_key = str(hit.get("title") or "").strip().lower()
                record = by_id.get(resource_id) or by_title.get(title_key)
                if record is None or record.id in seen_ids:
                    continue
                seen_ids.add(record.id)
                ordered.append(record)
        for record in resources:
            if record.id in seen_ids:
                continue
            seen_ids.add(record.id)
            ordered.append(record)
        return ordered[:6]

    def load_resource_record_text(resource: ResourceRecord) -> str:
        raw_paths = (
            resource.sandbox_path,
            resource.extracted_artifact_path,
            resource.canonical_source,
            resource.source,
        )
        for raw_path in raw_paths:
            path_text = str(raw_path or "").strip()
            if not path_text or re.match(r"^[a-z]+://", path_text, re.IGNORECASE):
                continue
            try:
                path = Path(path_text).expanduser()
            except OSError:
                continue
            if not path.exists() or not path.is_file():
                continue
            try:
                return path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                try:
                    return path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
            except OSError:
                continue
        fragments: list[str] = []
        for fragment in resource.knowledge_fragments[:6]:
            if not isinstance(fragment, dict):
                continue
            for key in ("snippet", "summary", "evidence_summary"):
                candidate = normalize_resource_contract_source_text(fragment.get(key))
                if candidate and candidate not in fragments:
                    fragments.append(candidate)
        return "\n\n".join(fragments)

    def extract_view_contract_section(text: str, *, view_name: str | None) -> str:
        normalized = normalize_resource_contract_source_text(text)
        if not normalized:
            return ""
        if not view_name:
            return normalized
        for depth in ("###", "##", "#"):
            match = re.search(
                rf"(?ims)^{re.escape(depth)}\s+[^\n]*\b{re.escape(view_name)}\b[^\n]*\n(?P<body>.*?)(?=^{re.escape(depth)}\s+|^\#\s+|\Z)",
                normalized,
            )
            if match:
                return str(match.group("body") or "").strip()
        return normalized

    def extract_labelled_contract_block(section_text: str, label: str) -> str:
        normalized = normalize_resource_contract_source_text(section_text)
        if not normalized:
            return ""
        match = re.search(
            rf"(?ims)^\s*(?:[-*]\s*)?{re.escape(label)}\s*:\s*(?P<body>.*?)(?=^\s*(?:[-*]\s*)?(?:First viewport promise|Must provide|Must not become)\s*:|^\s*###\s+|^\s*##\s+|\Z)",
            normalized,
        )
        return str(match.group("body") or "").strip() if match else ""

    def resource_contract_items(block_text: str) -> list[str]:
        normalized = normalize_resource_contract_source_text(block_text)
        if not normalized:
            return []
        items: list[str] = []
        for line in normalized.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("-", "*")):
                item = re.sub(r"[ .;,]+$", "", stripped[1:].strip())
                if item:
                    items.append(item)
                continue
            if not items:
                items.append(re.sub(r"[ .;,]+$", "", stripped))
        return items

    def extract_view_contract_details(
        text: str,
        *,
        view_name: str | None,
    ) -> tuple[str, list[str]]:
        section_text = extract_view_contract_section(text, view_name=view_name)
        promise_items = resource_contract_items(
            extract_labelled_contract_block(section_text, "First viewport promise")
        )
        boundary_items = resource_contract_items(
            extract_labelled_contract_block(section_text, "Must not become")
        )
        promise_text = promise_items[0] if promise_items else ""
        return promise_text, boundary_items

    def localize_resource_contract_item(text: str, *, response_language: str | None) -> str:
        cleaned = re.sub(r"[ .;,]+$", "", str(text or "").strip())
        if not cleaned:
            return ""
        if not prefers_chinese(response_language):
            return cleaned
        lowered = cleaned.casefold()
        replacements = {
            "the learner can find, trust, preview, and convert resources without losing provenance": "让学习者在不丢失 provenance 的前提下找到、信任、预览并转化资料",
            "a cms": "CMS",
            "a raw filesystem browser": "raw filesystem browser",
            "a place that writes into user project code by surprise": "会悄悄写入用户项目代码的地方",
        }
        return replacements.get(lowered, cleaned)

    def join_visible_contract_items(items: list[str], *, response_language: str | None) -> str:
        cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if prefers_chinese(response_language):
            if len(cleaned) == 2:
                return f"{cleaned[0]} 或 {cleaned[1]}"
            return f"{'、'.join(cleaned[:-1])}，或 {cleaned[-1]}"
        if len(cleaned) == 2:
            return f"{cleaned[0]} or {cleaned[1]}"
        return f"{', '.join(cleaned[:-1])}, or {cleaned[-1]}"

    def punctuate_visible_contract_line(text: str, *, response_language: str | None) -> str:
        cleaned = re.sub(r"[ .;,。；]+$", "", str(text or "").strip())
        if not cleaned:
            return ""
        return f"{cleaned}{'。' if prefers_chinese(response_language) else '.'}"

    def build_grounded_resource_contract_visible_fallback(
        *,
        workspace_id: str,
        coach_context: dict[str, object] | None,
        agent_meta: dict[str, object] | None,
        response_language: str | None,
    ) -> dict[str, str] | None:
        if not isinstance(coach_context, dict):
            return None
        raw_facets = coach_context.get("resource_question_facets")
        if not isinstance(raw_facets, list) or not raw_facets:
            return None
        view_name = next(
            (
                facet
                for facet in raw_facets
                if str(facet or "").strip() in {"Coach", "Plan", "Resources", "Training", "Settings"}
            ),
            None,
        )
        promise_text = ""
        boundary_items: list[str] = []
        for resource in ordered_resource_contract_candidates(workspace_id, agent_meta=agent_meta):
            source_text = load_resource_record_text(resource)
            if not source_text:
                continue
            promise_text, boundary_items = extract_view_contract_details(
                source_text,
                view_name=str(view_name or "").strip() or None,
            )
            if promise_text or boundary_items:
                break
        if not promise_text and not boundary_items:
            return None

        localized_promise = punctuate_visible_contract_line(
            localize_resource_contract_item(promise_text, response_language=response_language),
            response_language=response_language,
        )
        localized_boundary_items = [
            localize_resource_contract_item(item, response_language=response_language)
            for item in boundary_items[:3]
        ]
        boundary_visible = join_visible_contract_items(
            localized_boundary_items,
            response_language=response_language,
        )
        localized_view_name = str(view_name or "this view").strip() or "this view"

        if prefers_chinese(response_language):
            lines = ["我先直接按当前资料命中的 contract 回答：", ""]
            if localized_promise:
                lines.append(f"- `first viewport promise`：{localized_promise}")
            if boundary_visible:
                lines.append(f"- `must not become`：不能变成 {punctuate_visible_contract_line(boundary_visible, response_language=response_language)}")
            lines.extend(
                [
                    "",
                    f"下一步我可以把这两条 contract 变成一个可验证 checklist，再回到 {localized_view_name} 视图逐项核对。",
                ]
            )
            summary = f"先按资料把 {localized_view_name} 的 contract 直接答清，再决定是否扩展。"
            next_step = f"把这两条 contract 变成 checklist，再回到 {localized_view_name} 视图逐项核对。"
            teaching_note = "当 grounded resource turn 漂移时，先用已命中的资料 contract 修正可见回答。"
        else:
            lines = ["I will answer directly from the grounded library contract first:", ""]
            if localized_promise:
                lines.append(f"- `first viewport promise`: {localized_promise}")
            if boundary_visible:
                lines.append(
                    f"- `must not become`: {punctuate_visible_contract_line(boundary_visible, response_language=response_language)}"
                )
            lines.extend(
                [
                    "",
                    f"Next I can turn these two contract lines into a verifiable checklist and walk back through the {localized_view_name} view.",
                ]
            )
            summary = f"Answer the grounded {localized_view_name} contract directly before widening."
            next_step = (
                f"Turn these two contract lines into a checklist and verify them in the {localized_view_name} view."
            )
            teaching_note = (
                "When a grounded resource turn drifts, repair the visible answer from the retrieved contract first."
            )
        reply = "\n".join(lines).strip()
        resume_thread = build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
        return {
            "reply": reply,
            "summary": summary,
            "next_step": next_step,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
        }

    def reply_explicitly_lists_prepared_sequence(
        reply: str,
        *,
        coach_context: dict[str, object] | None,
    ) -> bool:
        if not isinstance(coach_context, dict):
            return True
        raw_sequences = coach_context.get("resource_sequence_guidance")
        if not isinstance(raw_sequences, list) or not raw_sequences:
            return True
        if re.search(
            r"(^|\n)\s*(?:[-*]\s*)?(?:Step\s*\d+|第\s*[0-9一二三四五六七八九十]+\s*步|\d+\.)",
            str(reply or ""),
            re.IGNORECASE | re.MULTILINE,
        ):
            return True
        return False

    def guided_lane_visible_summary(
        scenario: str,
        *,
        response_language: str | None,
    ) -> str:
        normalized = str(scenario or "").strip().lower()
        if normalized == "remote_workspace":
            return localized_text(
                "Establish the VS Code remote workspace boundary before widening the lesson.",
                "先建立 VS Code remote workspace 的边界，再扩大这一轮教学。",
                response_language,
            )
        if normalized == "debug_loop":
            return localized_text(
                "Build one trustworthy VS Code debug loop before widening the investigation.",
                "先建立一条可信的 VS Code debug loop，再扩大这一轮排查。",
                response_language,
            )
        if normalized == "function_guidance":
            return localized_text(
                "Anchor function guidance to one live call site before widening the explanation.",
                "先把 function guidance 锚定到一个真实 call site，再扩展说明。",
                response_language,
            )
        return ""

    def function_guidance_visible_repair_reply_parts(
        coach_context: dict[str, object] | None,
        *,
        response_language: str | None,
    ) -> tuple[str, str]:
        chinese = prefers_chinese(response_language)
        if isinstance(coach_context, dict):
            starter = coach_context.get("function_guidance_starter")
            if isinstance(starter, dict) and str(starter.get("status") or "").strip() == "ready":
                call_site_path = str(starter.get("call_site_path") or "").strip() or "the prepared call site"
                definition_path = str(starter.get("definition_path") or "").strip() or "the prepared definition"
                symbol = (
                    str(starter.get("definition_symbol") or "").strip()
                    or str(starter.get("call_site_symbol") or "").strip()
                    or "the prepared function"
                )
                if chinese:
                    return (
                        f"这一轮我会先把函数理解锚定在准备好的 live call site `{call_site_path}`，再用 hover、signature help 和 Go to Definition 读稳 `{symbol}` 的 contract。",
                        f"下一步：打开 `{call_site_path}`，把光标放到 `{symbol}` 上，先看 hover 和 signature help，再跳到 `{definition_path}` 说清参数 contract 和返回 contract。",
                    )
                return (
                    f"I will keep this anchored to the prepared live call site in `{call_site_path}`, then use hover, signature help, and Go to Definition to read `{symbol}` with a stable contract.",
                    f"Next step: open `{call_site_path}`, place the cursor on `{symbol}`, check hover and signature help, then jump to `{definition_path}` and name the parameter and return contract.",
                )
        if chinese:
            return (
                "这一轮先只围绕一个真实 call site 读函数 contract。先用 hover、signature help 和 Go to Definition 看清它要什么、返回什么，再决定要不要展开实现。",
                "下一步：带回函数名、它期望什么，以及哪个 call site 证明了这个判断。",
            )
        return (
            "I will keep this turn anchored to one live call site and read the function contract before widening the explanation. Use hover, signature help, and Go to Definition to confirm what the function expects and what it returns.",
            "Next step: return the function name, what it expects, and which call site proves that reading.",
        )

    def build_guided_lane_visible_fallback(
        *,
        scenario: str,
        response_language: str | None,
        coach_context: dict[str, object] | None,
    ) -> dict[str, str] | None:
        normalized = str(scenario or "").strip().lower()
        if normalized not in GUIDED_VISIBLE_REPAIR_SCENARIOS:
            return None
        summary = guided_lane_visible_summary(normalized, response_language=response_language)
        next_step = ""
        if normalized == "remote_workspace":
            if prefers_chinese(response_language):
                lines = [
                    "这一轮先只守住 VS Code remote workspace 的边界。先讲清工作区边界和文件到底落在哪台机器上，再做一个最小验证动作，确认 Trainer 不会越界写错地方。",
                    "下一步：在你当前的 VS Code 窗口里，给我一个能证明工作区落点的真实信号，比如 Explorer 里的路径、终端里的 `pwd`，或者左下角的 remote host 标签。",
                ]
            else:
                lines = [
                    "I will keep this turn inside one real VS Code remote lane and lock the workspace boundary first. Teach where the files actually live, then do one minimal verification move before any wider setup talk.",
                    "Next step: return one real boundary signal from the current VS Code window, such as an Explorer path, `pwd`, or the remote host label.",
                ]
            next_step = local_continuation_step_for_scenario(normalized, response_language)
        elif normalized == "debug_loop":
            if prefers_chinese(response_language):
                lines = [
                    "这一轮先只搭一条可信的 VS Code debug loop。先定一个 breakpoint 或 `launch.json` 动作，只停一次，只核对一个 value、branch 或 stack frame。",
                    "下一步：先选一个 breakpoint 或 `launch.json` 动作，再告诉我你准备停在哪里，以及要核对哪一个 value、branch 或 stack frame。",
                ]
            else:
                lines = [
                    "I will keep this turn inside one trustworthy VS Code debug loop. Pick one breakpoint or one `launch.json` move, pause once, and inspect one value, branch, or stack frame before widening anything.",
                    "Next step: choose one breakpoint or `launch.json` move, then tell me where you will pause and what single value, branch, or stack frame you expect to inspect there.",
                ]
            next_step = local_continuation_step_for_scenario(normalized, response_language)
        else:
            lines = list(
                function_guidance_visible_repair_reply_parts(
                    coach_context,
                    response_language=response_language,
                )
            )
            next_step = lines[1] if len(lines) > 1 else ""
        next_step = strip_visible_next_step_prefix(next_step or (lines[1] if len(lines) > 1 else ""))
        if next_step[:1].isascii() and next_step[:1].islower():
            # Stripping a "Next step:" label leaves a mid-sentence remainder;
            # the structured next step is a standalone sentence, so restore the
            # sentence-initial capital (same rule as normalize_visible_coach_text).
            next_step = f"{next_step[:1].upper()}{next_step[1:]}"
        teaching_note = localized_text(
            "When visible coach text drifts across guided lanes, rebuild the answer from the active lane before persisting it.",
            "当可见教练回复串到别的 guided lane 时，先按当前主线重建回答，再把结果持久化。",
            response_language,
        )
        reply = "\n\n".join(part for part in lines if str(part or "").strip()).strip()
        resume_thread = build_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
        return {
            "reply": reply,
            "summary": summary,
            "next_step": next_step,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
        }

    def guided_lane_visible_reply_is_generic(value: object) -> bool:
        cleaned = normalize_visible_coach_text(value) or str(value or "").strip()
        if not cleaned:
            return True
        lowered = re.sub(r"\s+", " ", cleaned).casefold()
        if len(cleaned) <= 10:
            return True
        generic_replies = {
            "ok",
            "okay",
            "got it",
            "sounds good",
            "好的",
            "好",
            "明白",
            "收到",
            "继续",
        }
        return lowered in generic_replies

    def build_guided_lane_stable_visible_reply(
        *,
        scenario: str,
        response_language: str | None,
        coach_context: dict[str, object] | None,
    ) -> dict[str, str] | None:
        fallback = build_guided_lane_visible_fallback(
            scenario=scenario,
            response_language=response_language,
            coach_context=coach_context,
        )
        if fallback is None:
            return None
        return fallback

    def guided_lane_visible_reply_has_foreign_markers(
        value: object,
        *,
        scenario: str | None,
    ) -> bool:
        normalized_scenario = str(scenario or "").strip().lower()
        if normalized_scenario not in GUIDED_VISIBLE_REPAIR_SCENARIOS:
            return False
        cleaned = normalize_visible_coach_text(value) or str(value or "").strip()
        if not cleaned:
            return False
        lowered = re.sub(r"\s+", " ", cleaned).casefold()
        marker_map = guided_lane_visible_marker_map()
        for lane, markers in marker_map.items():
            if lane == normalized_scenario:
                continue
            for marker in markers:
                if marker.casefold() in lowered:
                    return True
        return False

    def apply_guided_lane_visible_fallback(
        *,
        reply: str,
        scenario: str,
        learner_message: str | None,
        response_language: str | None,
        coach_turn: dict[str, object] | None,
        agent_meta: dict[str, object] | None,
    ) -> tuple[str, dict[str, object] | None, dict[str, object], bool]:
        normalized = str(scenario or "").strip().lower()
        normalized_agent_meta = dict(agent_meta or {})
        # An explanation or worked-example request needs its answer first.
        if message_requests_explicit_explanation_or_example(learner_message):
            return reply, coach_turn, normalized_agent_meta, False
        if normalized not in GUIDED_VISIBLE_REPAIR_SCENARIOS:
            return reply, coach_turn, normalized_agent_meta, False
        texts_to_check = [
            reply,
            normalized_agent_meta.get("summary"),
            normalized_agent_meta.get("next_step"),
            normalized_agent_meta.get("resume_thread"),
            normalized_agent_meta.get("teaching_note"),
        ]
        if not any(
            text_contaminates_guided_lane(
                value,
                scenario=normalized,
                learner_message=learner_message,
            )
            for value in texts_to_check
        ):
            return reply, coach_turn, normalized_agent_meta, False
        coach_context = (
            normalized_object_mapping(coach_turn.get("coach_context"))
            if isinstance(coach_turn, dict)
            else None
        )
        fallback = build_guided_lane_visible_fallback(
            scenario=normalized,
            response_language=response_language,
            coach_context=coach_context,
        )
        if fallback is None:
            return reply, coach_turn, normalized_agent_meta, False
        normalized_agent_meta["summary"] = fallback["summary"]
        normalized_agent_meta["next_step"] = fallback["next_step"]
        normalized_agent_meta["teaching_note"] = fallback["teaching_note"]
        normalized_agent_meta["resume_thread"] = fallback["resume_thread"]
        normalized_agent_meta["scenario"] = normalized
        normalized_agent_meta["guided_lane_visible_repaired"] = True
        repaired_coach_turn = coach_turn
        if isinstance(coach_turn, dict):
            repaired_coach_turn = merge_agent_finalize_into_coach_turn(
                {
                    **coach_turn,
                    "scenario": normalized,
                },
                summary=fallback["summary"],
                next_step=fallback["next_step"],
                blocker=normalized_agent_meta.get("blocker"),
                resume_thread=fallback["resume_thread"],
                decision=normalized_agent_meta.get("decision"),
                teaching_note=fallback["teaching_note"],
                confidence=normalized_agent_meta.get("confidence"),
                evidence=normalized_agent_meta.get("evidence"),
            )
        return fallback["reply"], repaired_coach_turn, normalized_agent_meta, True

    def ensure_coach_provider_ready(
        coaching_service: ProviderService,
        *,
        response_language: str | None,
    ) -> None:
        provider = getattr(coaching_service, "_config", None)
        if isinstance(provider, ProviderConfig):
            policy_violation = provider_model_policy_violation(provider)
            if policy_violation is not None:
                raise HTTPException(
                    status_code=400,
                    detail=provider_model_policy_detail(
                        provider,
                        policy_violation,
                        response_language,
                    ),
                )
        if coaching_service.has_api_key:
            return
        detail = localized_text(
            "Trainer needs a saved model provider and API key before a coaching turn can start.",
            "Trainer \u9700\u8981\u5148\u4fdd\u5b58\u53ef\u7528\u7684 model provider \u548c API key\uff0c\u6559\u7ec3\u5bf9\u8bdd\u624d\u80fd\u5f00\u59cb\u3002",
            response_language,
        )
        raise HTTPException(status_code=400, detail=detail)
        raise HTTPException(
            status_code=400,
            detail=localized_text(
                "Trainer needs a saved model provider and API key before a coaching turn can start.",
                "Trainer \u9700\u8981\u5148\u4fdd\u5b58\u53ef\u7528\u7684 model provider \u548c API key\uff0c\u6559\u7ec3\u5bf9\u8bdd\u624d\u80fd\u5f00\u59cb\u3002",
                response_language,
            ),
        )

    def ensure_agent_tools_ready(
        request: TurnRequest | SessionMessageRequest,
        coaching_service: ProviderService,
    ) -> None:
        """Reject grounded/tool lanes instead of silently degrading to plain chat."""
        if not _request_requires_agent_tools(request):
            return
        if (
            coaching_service.has_api_key
            and runtime.provider_connection_verified(coaching_service)
            and runtime.provider_capability_state_for(coaching_service, "tools") == "verified"
        ):
            return
        raise HTTPException(
            status_code=409,
            detail=localized_text(
                "This action needs a verified tools-capable provider. Test a provider with tool calls in Settings before continuing.",
                "\u8fd9\u4e2a\u52a8\u4f5c\u9700\u8981\u5df2\u9a8c\u8bc1\u652f\u6301\u5de5\u5177\u8c03\u7528\u7684 Provider\u3002\u8bf7\u5148\u5728\u8bbe\u7f6e\u4e2d\u6d4b\u8bd5\u652f\u6301 tools \u7684 Provider\u3002",
                request.response_language,
            ),
        )

    def ensure_streaming_ready(
        coaching_service: ProviderService,
        response_language: str | None,
    ) -> None:
        """Never enter an SSE route without an observed streaming capability."""

        if (
            coaching_service.has_api_key
            and runtime.provider_connection_verified(coaching_service)
            and runtime.provider_capability_state_for(coaching_service, "streaming") == "verified"
        ):
            return
        raise HTTPException(
            status_code=409,
            detail=localized_text(
                "This streaming action needs a provider that passed the real streaming probe. Test the connection in Settings before continuing.",
                "这个流式动作需要通过真实流式探测的 Provider。请先在设置中测试连接，再继续。",
                response_language,
            ),
        )

    def provider_payload_declares_unknown_protocol(payload: dict) -> bool:
        provider_payload = payload.get("provider")
        if not isinstance(provider_payload, dict):
            return False
        provider_protocol = provider_protocol_from_payload(provider_payload)
        connection_type = provider_connection_type_from_payload(provider_payload)
        declared_protocol_raw = provider_payload.get("protocol") or provider_payload.get("api")
        declared_unknown = (
            isinstance(declared_protocol_raw, str)
            and bool(str(declared_protocol_raw).strip())
            and provider_protocol is None
        )
        return declared_unknown or (
            provider_protocol is None and connection_type == NEWAPI_CONNECTION_TYPE
        )

    def provider_transport_is_configured(
        name: object = "",
        base_url: object = "",
        model: object = "",
    ) -> bool:
        return bool(str(name or "").strip() and str(base_url or "").strip() and str(model or "").strip())

    def provider_is_live_usable(coaching_service: ProviderService, payload: dict) -> bool:
        if provider_payload_declares_unknown_protocol(payload):
            return False
        provider_payload = payload.get("provider") if isinstance(payload, dict) else None
        if isinstance(provider_payload, dict) and provider_payload:
            if not provider_transport_is_configured(
                provider_payload.get("name") or provider_payload.get("label"),
                provider_payload.get("base_url") or provider_payload.get("baseUrl"),
                provider_payload.get("model"),
            ):
                return False
        config = getattr(coaching_service, "_config", None)
        if isinstance(config, ProviderConfig):
            if not provider_transport_is_configured(config.name, config.base_url, config.model):
                return False
            raw_protocol = getattr(config, "protocol", None)
            if raw_protocol and normalize_provider_protocol(raw_protocol) is None:
                return False
        # A caller-supplied API key is an explicit one-request provider override;
        # the request itself is the connectivity probe, so requiring a prior
        # Settings test would reject valid preview and integration callers.
        if isinstance(payload, dict) and provider_api_key_from_payload(payload):
            return bool(getattr(coaching_service, "has_api_key", False))
        return runtime.provider_connection_verified(coaching_service)

    def provider_service_allows_object_minting(
        provider_service: ProviderService | None = None,
    ) -> bool:
        service = provider_service or runtime.provider_service
        return provider_is_live_usable(service, {})

    def honest_suggested_actions_without_usable_provider(
        actions: list[dict[str, object]],
        *,
        response_language: str | None,
        snapshot: WorkbenchSnapshot | None = None,
        current_task: TaskSpec | None = None,
        current_plan: LearningPlan | None = None,
        current_evaluation: EvaluationReport | None = None,
    ) -> list[dict[str, object]]:
        kept = list(actions)
        if kept:
            return kept
        return structured_suggested_actions(
            [
                {
                    "label": localized_text(
                        "Repair the provider in Settings, then resend this turn.",
                        "先在设置里修好连接，再重发这一轮。",
                        response_language,
                    ),
                    "action": "hint",
                }
            ],
            response_language=response_language,
            scenario="general",
            focus_area=stateful_focus_area(
                current_task,
                current_plan,
                current_evaluation,
                snapshot=snapshot,
            ),
        )

    def honest_unusable_provider_coach_turn(
        *,
        response_language: str | None,
        snapshot: WorkbenchSnapshot,
        coaching_service: ProviderService,
        object_kind: Literal["task", "plan", "coach"] = "coach",
        scenario: CoachScenario = "general",
    ) -> CoachTurnPayload:
        if object_kind == "plan":
            summary = localized_text(
                "This connection is not ready. Test it in Settings, then resend this turn. Trainer did not invent a plan.",
                "当前连接还不能用。请先在设置里测试，再重发这一轮。Trainer 没有生成新计划。",
                response_language,
            )
        elif object_kind == "task":
            summary = localized_text(
                "This connection is not ready. Test it in Settings, then resend this turn. Trainer did not invent a task.",
                "当前连接还不能用。请先在设置里测试，再重发这一轮。Trainer 没有生成新任务。",
                response_language,
            )
        else:
            summary = localized_text(
                "This connection is not ready. Test it in Settings, then resend this turn.",
                "当前连接还不能用。请先在设置里测试，再重发这一轮。",
                response_language,
            )
        next_step = coaching_service.provider_failure_next_step("unknown", response_language)
        actions = honest_suggested_actions_without_usable_provider(
            [],
            response_language=response_language,
            snapshot=snapshot,
            current_task=snapshot.current_task,
            current_plan=snapshot.plan,
            current_evaluation=snapshot.evaluation,
        )
        return {
            "scenario": scenario,
            "learner_signal": "steady",
            "coach_context": {},
            "suggested_actions": actions,
            "artifacts": {},
            "coach_turn": CoachTurnSummary(
                scenario=scenario,
                learner_signal="steady",
                summary=summary,
                next_step=next_step,
            ),
            "stream": False,
        }

    def normalized_provider_model_names(values: object) -> set[str]:
        if not isinstance(values, list):
            return set()
        return {
            str(value).strip().casefold()
            for value in values
            if str(value).strip()
        }

    def provider_model_policy_violation(provider: ProviderConfig) -> str | None:
        selected_model = str(provider.model or "").strip()
        if not selected_model:
            return None
        normalized_model = selected_model.casefold()
        denied_models = normalized_provider_model_names(provider.denied_models)
        if normalized_model in denied_models:
            return "model_denied"
        allowed_models = normalized_provider_model_names(provider.allowed_models)
        if allowed_models and normalized_model not in allowed_models:
            return "model_not_allowed"
        return None

    def provider_model_policy_detail(
        provider: ProviderConfig,
        policy_violation: str,
        response_language: str | None,
    ) -> str:
        model = str(provider.model or "").strip()
        if policy_violation == "model_denied":
            return localized_text(
                f"The selected model '{model}' is blocked for this connection. Choose a different model and try again.",
                f"\u5f53\u524d\u8fde\u63a5\u5df2\u7981\u6b62\u4f7f\u7528\u6a21\u578b\u300c{model}\u300d\u3002\u8bf7\u4ece\u6a21\u578b\u5217\u8868\u4e2d\u66f4\u6362\u4e00\u4e2a\u540e\u518d\u8bd5\u3002",
                response_language,
            )
        return localized_text(
            f"The selected model '{model}' is not in this connection's allowed model list. Choose a model from the list and try again.",
            f"\u5f53\u524d\u9009\u62e9\u7684\u6a21\u578b\u300c{model}\u300d\u4e0d\u5728\u6b64\u8fde\u63a5\u5141\u8bb8\u4f7f\u7528\u7684\u6a21\u578b\u5217\u8868\u4e2d\u3002\u8bf7\u4ece\u5217\u8868\u4e2d\u9009\u62e9\u4e00\u4e2a\u6a21\u578b\u540e\u518d\u8bd5\u3002",
            response_language,
        )

    def requested_resource_context(
        workspace_id: str,
        resource_ids: list[str] | None,
    ) -> dict[str, object]:
        if not resource_ids:
            return {}
        ids = list(resource_ids)
        # Just-in-time teaching digestion: the learner pointed the coach at
        # these materials, so each gets digested (总结/预备题目/直观案例) once
        # per content version — fire-and-forget, never blocking the turn, and
        # never a blanket sweep over the whole library.
        runtime.request_resource_digestion(workspace_id, ids)
        return runtime.resource_service.build_requested_resource_context(workspace_id, ids)

    def request_resource_ids(request: TurnRequest | SessionMessageRequest) -> list[str]:
        # Composer IDs describe a Resources search scope, not attached materials.
        return list(request.resource_ids)

    def resource_composer_context(
        intent: ResourceComposerIntent | None,
    ) -> dict[str, object]:
        if intent is None:
            return {}
        return {
            "resource_composer_intent": {
                "mode": intent.mode,
                "resource_ids": list(intent.resource_ids),
            }
        }

    def workspace_understanding_resource_context(
        workspace_id: str,
        resource_ids: list[str] | None,
    ) -> dict[str, object]:
        if not resource_ids:
            return {}
        return runtime.resource_service.build_workspace_understanding_context(workspace_id, list(resource_ids))

    def message_deserves_library_first_lookup(message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        explicit_markers = (
            "search my resources",
            "search the resources",
            "search my library",
            "search the library",
            "search my notes",
            "search my uploads",
            "look in my resources",
            "look in my library",
            "资料库",
            "资源库",
            "我的资料",
            "我的资源",
            "上传的资料",
            "搜索资料",
            "搜索我的资料",
            "搜索资料库",
            "搜索我的资料库",
        )
        if any(marker in lowered for marker in explicit_markers):
            return True
        teaching_markers = (
            "teach me",
            "explain",
            "walk me through",
            "help me understand",
            "tell me",
            "why does",
            "how do i",
            "what is",
            "remote",
            "ssh",
            "debug",
            "breakpoint",
            "api",
            "protocol",
            "function",
            "signature help",
            "hover",
            "教我",
            "解释",
            "讲解",
            "告诉我",
            "为什么",
            "怎么",
            "如何",
            "远程",
            "调试",
            "断点",
            "函数",
            "协议",
        )
        if any(marker in lowered for marker in teaching_markers):
            return True
        import_markers = (
            "imported",
            "uploaded",
            "indexed",
            "just imported",
            "just uploaded",
            "导入",
            "上传",
            "索引",
        )
        document_markers = (
            "design doc",
            "design document",
            "design spec",
            "spec",
            "specification",
            "view contract",
            "documentation",
            "document",
            "markdown",
            "设计文档",
            "设计规范",
            "规范文档",
            "文档",
        )
        view_markers = (
            "coach view",
            "plan view",
            "resources view",
            "training view",
            "settings view",
            "coach 视图",
            "plan 视图",
            "resources 视图",
            "training 视图",
            "settings 视图",
            "对话视图",
            "计划视图",
            "资料视图",
            "资源视图",
            "训练视图",
            "设置视图",
            "first viewport",
            "viewport promise",
            "首屏",
            "承诺",
        )
        references_imported_material = any(marker in lowered for marker in import_markers) and any(
            marker in lowered for marker in (*document_markers, *view_markers)
        )
        discusses_doc_contract = any(marker in lowered for marker in document_markers) and any(
            marker in lowered for marker in view_markers
        )
        return references_imported_material or discusses_doc_contract

    def coach_context_has_prepared_library_grounding(
        coach_context: dict[str, object] | None,
    ) -> bool:
        if not isinstance(coach_context, dict):
            return False
        resource_fragments = coach_context.get("resource_fragments")
        if isinstance(resource_fragments, list) and resource_fragments:
            return True
        requested_resources = coach_context.get("requested_resources")
        if isinstance(requested_resources, list) and requested_resources:
            return True
        if coach_context.get("auto_resource_lookup") is True:
            return bool(auto_resource_lookup_tool_events(coach_context, None))
        return False

    def resource_grounding_turn_prefers_fresh_lane(
        message: str | None,
        grounding_context: dict[str, object] | None,
    ) -> bool:
        if message_requests_lane_continuation(message):
            return False
        if not coach_context_has_prepared_library_grounding(grounding_context):
            return False
        return message_deserves_library_first_lookup(message)

    def fresh_lane_keeps_review_signals(scenario: str | None) -> bool:
        return str(scenario or "").strip().lower() in {
            "next_task",
            "review",
            "review_reflection",
        }

    def turn_keeps_review_signals(
        scenario: str | None,
        teaching_decision: object | None = None,
    ) -> bool:
        if fresh_lane_keeps_review_signals(scenario):
            return True
        if isinstance(teaching_decision, dict):
            mode = teaching_decision.get("mode")
        else:
            mode = getattr(teaching_decision, "mode", None)
        return str(mode or "").strip().lower() in {"review", "review_reflection"}

    def collect_auto_resource_search_hits(
        raw_hits: object,
        *,
        limit: int,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        if not isinstance(raw_hits, list):
            return [], []

        requested_resources: list[dict[str, object]] = []
        resource_fragments: list[dict[str, object]] = []
        seen_resource_ids: set[str] = set()
        for hit in raw_hits:
            hit_payload = asdict(hit) if is_dataclass(hit) and not isinstance(hit, type) else hit
            if not isinstance(hit_payload, dict):
                continue
            trust_state = str(hit_payload.get("trust_state") or "").strip().lower()
            index_state = str(hit_payload.get("index_state") or "").strip().lower()
            snippet = str(hit_payload.get("snippet") or hit_payload.get("summary") or "").strip()
            resource_id = str(hit_payload.get("resource_id") or "").strip()
            if not resource_id or resource_id in seen_resource_ids:
                continue
            if trust_state in {"blocked", "rejected"}:
                continue
            if index_state not in {"indexed", "ready", ""}:
                continue
            if not snippet:
                continue
            seen_resource_ids.add(resource_id)
            requested_resources.append(
                {
                    "id": resource_id,
                    "title": str(hit_payload.get("title") or resource_id),
                    "kind": str(hit_payload.get("kind") or "resource"),
                    "summary": str(hit_payload.get("summary") or snippet),
                    "source": str(hit_payload.get("source") or ""),
                    "trust_score": str(hit_payload.get("trust_score") or ""),
                    "freshness": str(hit_payload.get("freshness") or ""),
                }
            )
            resource_fragments.append(
                {
                    "id": resource_id,
                    "resource_id": resource_id,
                    "title": str(hit_payload.get("title") or resource_id),
                    "snippet": snippet,
                    "summary": str(hit_payload.get("summary") or snippet),
                    "source": str(hit_payload.get("source") or ""),
                    "source_type": str(hit_payload.get("source_type") or "resource_search"),
                    "kind": str(hit_payload.get("kind") or "resource"),
                    "trust_score": hit_payload.get("trust_score"),
                    "trust_state": str(hit_payload.get("trust_state") or ""),
                    "freshness": str(hit_payload.get("freshness") or ""),
                    "citation_id": str(hit_payload.get("citation_id") or ""),
                    "evidence_summary": str(hit_payload.get("match_summary") or snippet),
                    "rank_reasons": list(hit_payload.get("rank_reasons") or []),
                }
            )
            if len(resource_fragments) >= limit:
                break
        return requested_resources, resource_fragments

    def resource_context_ids(resource_context: dict[str, object] | None) -> list[str]:
        if not isinstance(resource_context, dict):
            return []
        collected: list[str] = []
        seen_ids: set[str] = set()
        requested_resource_ids = resource_context.get("requested_resource_ids")
        for item in requested_resource_ids if isinstance(requested_resource_ids, list) else []:
            resource_id = str(item or "").strip()
            if not resource_id or resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            collected.append(resource_id)
        if collected:
            return collected
        requested_resources = resource_context.get("requested_resources")
        for item in requested_resources if isinstance(requested_resources, list) else []:
            if not isinstance(item, dict):
                continue
            resource_id = str(item.get("id") or item.get("resource_id") or "").strip()
            if not resource_id or resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            collected.append(resource_id)
        if collected:
            return collected
        resource_fragments = resource_context.get("resource_fragments")
        for item in resource_fragments if isinstance(resource_fragments, list) else []:
            if not isinstance(item, dict):
                continue
            resource_id = str(item.get("resource_id") or item.get("id") or "").strip()
            if not resource_id or resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            collected.append(resource_id)
        return collected

    def load_resource_source_text(
        workspace_id: str,
        resource_id: str,
        *,
        max_chars: int = 12000,
    ) -> tuple[ResourceRecord | None, str]:
        resource = runtime.repository.get_resource(workspace_id, resource_id)
        if resource is None:
            return None, ""
        if str(resource.kind or "").strip().lower() not in {"markdown", "text", "code"}:
            return resource, ""
        local_source_path = None
        try:
            local_source_path = runtime.resource_service._local_source_path(resource.source)
        except Exception:
            local_source_path = None
        if local_source_path is None or not local_source_path.exists() or not local_source_path.is_file():
            return resource, ""
        try:
            raw_text = local_source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                raw_text = local_source_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return resource, ""
        except OSError:
            return resource, ""
        return resource, raw_text[:max_chars]

    def extract_explicit_sequence_guidance(
        resource: ResourceRecord,
        text: str,
    ) -> dict[str, object] | None:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return None
        title_match = re.search(r"^\s*#\s+(.+?)\s*$", normalized_text, re.MULTILINE)
        resource_title = (
            str(title_match.group(1)).strip()
            if title_match
            else str(resource.name or resource.id).strip() or "resource"
        )
        step_pattern = re.compile(
            r"^\s*(?P<label>(?:Step\s+\d+)|(?:第\s*[0-9一二三四五六七八九十]+\s*步))\s*(?:[-:：.]|\)|\s)\s*(?P<body>.+?)\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        steps: list[dict[str, str]] = []
        for match in step_pattern.finditer(normalized_text):
            label = " ".join(str(match.group("label") or "").split()).strip()
            body = " ".join(str(match.group("body") or "").split()).strip()
            if not label or not body:
                continue
            steps.append({"label": label, "text": body})
        if len(steps) < 2:
            return None
        boundary_match = re.search(
            r"^\s*(?:Boundary sentinel|Boundary|边界哨兵|边界提示)\s*[:：-]\s*(?P<body>.+?)\s*$",
            normalized_text,
            re.IGNORECASE | re.MULTILINE,
        )
        boundary_sentinel = (
            " ".join(str(boundary_match.group("body") or "").split()).strip()
            if boundary_match
            else ""
        )
        scenario = infer_message_coaching_scenario(
            f"{resource_title}\n{normalized_text}",
            default="general",
        )
        return {
            "resource_id": resource.id,
            "title": resource_title,
            "source": resource.canonical_source or resource.source,
            "step_count": len(steps),
            "steps": steps[:6],
            "boundary_sentinel": boundary_sentinel,
            "scenario": scenario if scenario in GUIDED_SEQUENCE_SCENARIOS else "",
        }

    def attach_resource_sequence_guidance(
        workspace_id: str,
        resource_context: dict[str, object],
    ) -> dict[str, object]:
        resource_ids = resource_context_ids(resource_context)
        if not resource_ids:
            return resource_context
        sequences: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for resource_id in resource_ids[:3]:
            if resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            resource, source_text = load_resource_source_text(workspace_id, resource_id)
            if resource is None or not source_text:
                continue
            sequence = extract_explicit_sequence_guidance(resource, source_text)
            if sequence is None:
                continue
            sequences.append(sequence)
            if len(sequences) >= 2:
                break
        if not sequences:
            return resource_context
        enriched = dict(resource_context)
        enriched["resource_sequence_guidance"] = sequences
        first_sequence = sequences[0]
        first_title = str(first_sequence.get("title") or "This resource").strip()
        raw_step_count = first_sequence.get("step_count")
        first_step_count = raw_step_count if isinstance(raw_step_count, int) else 0
        if first_step_count >= 2:
            enriched["resource_sequence_summary"] = (
                f"{first_title} carries an exact {first_step_count}-step library sequence; "
                "restate every step in order, and preserve its step count and labels unless you clearly mark an extension."
            )
        return enriched

    def automatic_resource_context(
        workspace_id: str,
        message: str | None,
        *,
        limit: int = 4,
    ) -> dict[str, object]:
        if not message_deserves_library_first_lookup(message):
            return {}
        workspace_resources = runtime.repository.list_resources(workspace_id)
        if not workspace_resources:
            return {}
        requested_resources: list[dict[str, object]] = []
        resource_fragments: list[dict[str, object]] = []
        selected_query = ""
        queries_tried: list[str] = []
        for candidate in resource_lookup_query_candidates(message)[:6]:
            queries_tried.append(candidate)
            try:
                search_response = runtime.resource_service.search_resources(
                    workspace_id,
                    candidate,
                    top_k=max(limit * 2, limit + 2),
                    project_scope=workspace_id,
                )
            except Exception:
                continue
            requested_resources, resource_fragments = collect_auto_resource_search_hits(
                getattr(search_response, "results", None),
                limit=limit,
            )
            if resource_fragments:
                selected_query = candidate
                break
        if not resource_fragments:
            return {}

        top_titles = ", ".join(
            str(item.get("title") or "").strip()
            for item in requested_resources[:2]
            if str(item.get("title") or "").strip()
        )
        summary = (
            f"Auto-grounded this turn in {len(resource_fragments)} likely library hits"
            + (f": {top_titles}" if top_titles else ".")
        )
        return {
            "requested_resources": requested_resources,
            "requested_resource_ids": [str(item["id"]) for item in requested_resources if item.get("id")],
            "requested_resource_summary": summary,
            "resource_brief": summary,
            "resource_fragments": resource_fragments,
            "auto_resource_lookup": True,
            "auto_resource_query": selected_query or (queries_tried[0] if queries_tried else ""),
            "auto_resource_queries_tried": queries_tried,
        }

    def compact_tool_preview(value: object, *, max_chars: int = 420) -> str:
        preview = " ".join(str(value or "").split()).strip()
        if len(preview) <= max_chars:
            return preview
        return f"{preview[: max_chars - 3].rstrip()}..."

    def auto_resource_lookup_tool_events(
        resource_context: dict[str, object] | None,
        message: str | None,
    ) -> list[dict[str, object]]:
        if not isinstance(resource_context, dict):
            return []
        if resource_context.get("auto_resource_lookup") is not True:
            return []
        raw_fragments = resource_context.get("resource_fragments")
        if not isinstance(raw_fragments, list) or not raw_fragments:
            return []

        hits: list[dict[str, object]] = []
        for item in raw_fragments[:3]:
            if not isinstance(item, dict):
                continue
            resource_id = str(item.get("resource_id") or item.get("id") or "").strip()
            title = str(item.get("title") or resource_id or "resource").strip()
            snippet = compact_tool_preview(
                item.get("snippet") or item.get("summary") or item.get("evidence_summary") or "",
                max_chars=360,
            )
            if not resource_id and not snippet:
                continue
            hit: dict[str, object] = {
                "resource_id": resource_id,
                "title": title,
                "snippet": snippet,
            }
            source = str(item.get("source") or "").strip()
            if source:
                hit["source"] = source
            kind = str(item.get("kind") or "").strip()
            if kind:
                hit["kind"] = kind
            citation_id = str(item.get("citation_id") or "").strip()
            if citation_id:
                hit["citation_id"] = citation_id
            rank_reasons = item.get("rank_reasons")
            if isinstance(rank_reasons, list):
                hit["rank_reasons"] = [
                    compact_tool_preview(reason, max_chars=120)
                    for reason in rank_reasons[:3]
                    if str(reason or "").strip()
                ]
            hits.append(hit)

        if not hits:
            return []

        query = compact_tool_preview(message, max_chars=240)
        selected_query = compact_tool_preview(
            resource_context.get("auto_resource_query") or query,
            max_chars=240,
        )
        summary = compact_tool_preview(
            resource_context.get("requested_resource_summary")
            or resource_context.get("resource_brief")
            or f"Auto-grounded this turn in {len(raw_fragments)} likely library hits.",
            max_chars=360,
        )
        result: dict[str, object] = {
            "query": selected_query,
            "summary": summary,
            "total": len(raw_fragments),
            "hits": hits,
            "auto": True,
        }
        queries_tried = resource_context.get("auto_resource_queries_tried")
        if isinstance(queries_tried, list) and queries_tried:
            result["queries_tried"] = [
                compact_tool_preview(candidate, max_chars=120)
                for candidate in queries_tried[:6]
                if str(candidate or "").strip()
            ]
        sequence_guidance = resource_context.get("resource_sequence_guidance")
        if isinstance(sequence_guidance, list) and sequence_guidance:
            result["prepared_sequences"] = sequence_guidance[:2]

        call_id = "auto-search-resources"
        return [
            {
                "type": "tool_call",
                "id": call_id,
                "name": "search_resources",
                "arguments": {
                    "query": selected_query,
                    "mode": "narrow",
                    "auto": True,
                },
                "step": 0,
                "auto": True,
            },
            {
                "type": "tool_result",
                "id": call_id,
                "name": "search_resources",
                "ok": True,
                "result": result,
                "step": 0,
                "auto": True,
            },
        ]

    def merge_auto_resource_tool_events(
        raw_events: object,
        auto_events: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        events = [dict(item) for item in raw_events if isinstance(item, dict)] if isinstance(raw_events, list) else []
        if not auto_events:
            return events
        already_has_auto_resource_evidence = any(
            str(item.get("name") or "").strip() == "search_resources"
            and (
                str(item.get("id") or "").strip() == "auto-search-resources"
                or item.get("auto") is True
            )
            for item in events
        )
        if already_has_auto_resource_evidence:
            return events
        return [*auto_events, *events]

    def apply_auto_resource_agent_evidence(
        agent_meta: dict[str, object] | None,
        auto_events: list[dict[str, object]],
    ) -> dict[str, object]:
        merged_meta = dict(agent_meta or {})
        merged_events = merge_auto_resource_tool_events(merged_meta.get("tool_events"), auto_events)
        if merged_events:
            merged_meta["tool_events"] = merged_events
            merged_meta["auto_resource_lookup"] = True
            merged_meta.setdefault("agentic", False)
            merged_meta.setdefault("stop_reason", "completed")
            merged_meta.setdefault(
                "summary",
                "Prepared library grounding from Resources before answering.",
            )
            merged_meta.setdefault(
                "teaching_note",
                "Resources were checked automatically because this looked like a teach/debug/remote/API/protocol turn.",
            )
        return merged_meta

    def should_attach_auto_resource_events(agent_meta: dict[str, object] | None) -> bool:
        if not isinstance(agent_meta, dict):
            return True
        stop_reason = str(agent_meta.get("stop_reason") or "").strip()
        return stop_reason not in {
            "invalid_key_or_permission",
            "model_unsupported",
            "model_not_found",
            "malformed_response",
            "rate_limit",
            "upstream_unavailable",
            "timeout",
            "network",
            "unknown",
            "provider_error",
            "language_corruption",
        }

    def compose_resource_context(
        workspace_id: str,
        resource_ids: list[str] | None,
        *,
        message: str | None = None,
        resource_composer_intent: ResourceComposerIntent | None = None,
    ) -> dict[str, object]:
        requested = requested_resource_context(workspace_id, resource_ids)
        workspace_context = workspace_understanding_resource_context(workspace_id, resource_ids)
        auto_context = automatic_resource_context(workspace_id, message) if not requested else {}
        composer_context = resource_composer_context(resource_composer_intent)
        merged: dict[str, object] = {}
        if workspace_context:
            merged.update(workspace_context)
        if auto_context:
            merged.update(auto_context)
        if requested:
            merged.update(requested)
        if composer_context:
            merged.update(composer_context)
        if not merged:
            return merged
        if message:
            question_facets: list[str] = []
            for facet in canonical_resource_view_terms(message):
                if facet not in question_facets:
                    question_facets.append(facet)
            for facet in mapped_resource_lookup_phrases(message):
                if facet not in question_facets:
                    question_facets.append(facet)
            if question_facets:
                merged["resource_question_facets"] = question_facets[:6]
        return attach_resource_sequence_guidance(workspace_id, merged)

    def load_curated_background_references(
        workspace_id: str,
        *,
        focus_area: str | None = None,
        limit: int = 4,
    ) -> list[dict[str, object]]:
        references = runtime.resource_service.curated_background_references(
            workspace_id,
            max_fragments=limit,
            focus_area=focus_area,
        )
        if not references and focus_area:
            references = runtime.resource_service.curated_background_references(
                workspace_id,
                max_fragments=limit,
            )
        return references

    def load_recent_background_findings(
        workspace_id: str,
        *,
        focus_area: str | None = None,
        limit: int = 4,
    ) -> list[dict[str, object]]:
        references = runtime.research_service.recent_background_references(
            workspace_id=workspace_id,
            focus_area=focus_area,
            min_confidence=0.35,
            limit=limit,
        )
        if not references and focus_area:
            references = runtime.research_service.recent_background_references(
                workspace_id=workspace_id,
                min_confidence=0.35,
                limit=limit,
            )
        return references

    def workspace_first_look_summary(workspace_id: str) -> FirstLookSummary | None:
        memory_snapshot = runtime.memory_service.snapshot(workspace_id)
        understanding = memory_snapshot.workspace_understanding
        if understanding is None:
            return None
        return understanding.first_look_summary

    def first_look_recommended_next_from_snapshot(snapshot: WorkbenchSnapshot | None) -> str:
        if snapshot is None or snapshot.memory is None:
            return ""
        understanding = snapshot.memory.workspace_understanding
        if understanding is None or understanding.first_look_summary is None:
            return ""
        return str(understanding.first_look_summary.recommended_next_step or "").strip()

    def persist_first_look_summary(
        workspace_id: str,
        first_look_summary: FirstLookSummary,
    ) -> WorkspaceUnderstandingSnapshot:
        memory_snapshot = runtime.memory_service.snapshot(workspace_id)
        existing = memory_snapshot.workspace_understanding
        if existing is None:
            understanding = WorkspaceUnderstandingSnapshot(firstLookSummary=first_look_summary)
        else:
            understanding = existing.model_copy(deep=True)
            understanding.first_look_summary = first_look_summary
        runtime.memory_service.save_workspace_understanding(workspace_id, understanding)
        return understanding

    def maybe_persist_first_look_from_path(
        workspace_id: str,
        folder_path: str | None,
        *,
        response_language: str | None = None,
        workspace_file_snapshot: dict | None = None,
        remote_name: str | None = None,
    ) -> FirstLookSummary | None:
        path = str(folder_path or "").strip()
        snapshot = workspace_file_snapshot if isinstance(workspace_file_snapshot, dict) else None
        remote = bool(
            str(remote_name or "").strip()
            or (isinstance(snapshot, dict) and snapshot.get("is_remote") is True)
            or "://" in path
        )
        local_dir = False
        if path and "://" not in path:
            try:
                candidate = Path(path).expanduser()
                local_dir = candidate.exists() and candidate.is_dir()
            except OSError:
                local_dir = False
        if not local_dir and not snapshot and not remote:
            return None
        if not path and not snapshot:
            return None
        summary = classify_heuristic(
            path,
            response_language=response_language,
            workspace_file_snapshot=snapshot,
            remote_name=remote_name,
        )
        persist_first_look_summary(workspace_id, summary)
        return summary

    def first_look_focus_hint(workspace_id: str) -> str | None:
        summary = workspace_first_look_summary(workspace_id)
        if summary is None:
            return None
        candidates = [
            summary.training_opportunities[0] if summary.training_opportunities else "",
            summary.recommended_next_step,
            summary.project_type_guess.replace("_", " ") if summary.project_type_guess else "",
            summary.folder_role.replace("_", " ") if summary.folder_role else "",
            summary.entry_points[0] if summary.entry_points else "",
        ]
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text:
                return text
        return None

    def resolve_external_references(
        *,
        workspace_id: str,
        resource_context: dict[str, object] | None,
        focus_area: str | None = None,
        limit: int = 4,
        additional_curated_fragments: list[dict[str, object]] | None = None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
        resource_fragments = (
            resource_context.get("resource_fragments", [])
            if isinstance(resource_context, dict)
            else []
        )
        curated_background_references = load_curated_background_references(
            workspace_id,
            focus_area=focus_area,
            limit=limit,
        )
        if additional_curated_fragments:
            curated_background_references = runtime.resource_service.merge_external_references(
                curated_fragments=curated_background_references + additional_curated_fragments,
                focus_area=focus_area,
                limit=limit,
            )
        recent_background_findings = load_recent_background_findings(
            workspace_id,
            focus_area=focus_area,
            limit=limit,
        )
        external_references = runtime.resource_service.merge_external_references(
            requested_fragments=resource_fragments if isinstance(resource_fragments, list) else [],
            curated_fragments=curated_background_references,
            research_findings=recent_background_findings,
            focus_area=focus_area,
            limit=limit,
        )
        return external_references, curated_background_references, recent_background_findings

    def infer_action_type(label: str) -> str:
        lowered = label.lower()
        if "plan" in lowered or "\u8ba1\u5212" in label:
            return "plan"
        if "next task" in lowered or "\u4e0b\u4e00\u9898" in label:
            return "next_task"
        if "review" in lowered or "\u8bc4\u5ba1" in label or "fix" in lowered or "\u4fee\u590d" in label:
            return "retry_review" if "again" in lowered or "\u91cd\u65b0" in label else "review"
        if "task" in lowered or "\u4efb\u52a1" in label or "practice" in lowered or "\u8bad\u7ec3\u9898" in label:
            return "task"
        return "hint"

    def teaching_strategy_context_from_snapshot(snapshot: WorkbenchSnapshot) -> dict[str, str] | None:
        adaptation = snapshot.memory.coaching_adaptation if snapshot.memory else None
        if adaptation is None:
            return None
        return {
            "challenge_level": adaptation.challenge_level,
            "hint_depth": adaptation.hint_depth,
            "review_urgency": adaptation.review_urgency,
            "explanation_mode": adaptation.explanation_mode,
            "next_step_bias": adaptation.next_step_bias,
        }

    def action_defaults(
        action: str,
        response_language: str | None,
        *,
        scenario: str | None = None,
        focus_area: str | None = None,
    ) -> dict[str, str | None]:
        if action == "plan":
            return {
                "artifact_kind": "plan_update",
                "rationale": localized_text(
                    "Use this when the next move needs sequencing around the current focus, not more explanation.",
                    "\u5f53\u4f60\u73b0\u5728\u66f4\u9700\u8981\u56f4\u7ed5\u5f53\u524d\u805a\u7126\u70b9\u6392\u987a\u5e8f\uff0c\u800c\u4e0d\u662f\u7ee7\u7eed\u89e3\u91ca\u65f6\uff0c\u7528\u8fd9\u4e2a\u3002",
                    response_language,
                ),
                "prompt": localized_text(
                    "Break this into a tighter plan around the current stage and the next visible slice.",
                    "\u56f4\u7ed5\u5f53\u524d\u9636\u6bb5\u548c\u4e0b\u4e00\u4e2a\u53ef\u89c1\u5207\u7247\uff0c\u628a\u8fd9\u4ef6\u4e8b\u62c6\u6210\u66f4\u7d27\u7684\u8ba1\u5212\u3002",
                    response_language,
                ),
                "focus_area": focus_area,
            }
        if action == "next_task":
            return {
                "artifact_kind": "next_step",
                "rationale": localized_text(
                    "Use this when you want the coach to pick the next thin implementation slice for the current lane.",
                    "当你想围绕当前主线直接得到下一小步的实现练习时，用这个。",
                    response_language,
                ),
                "prompt": localized_text(
                    "Choose the next thin task from my current project, current focus, and weak spots.",
                    "\u7ed3\u5408\u6211\u5f53\u524d\u7684 project\u3001\u5f53\u524d\u805a\u7126\u70b9\u548c\u8584\u5f31\u70b9\uff0c\u7ed9\u6211\u4e0b\u4e00\u9053\u6700\u8584\u7684\u8bad\u7ec3\u9898\u3002",
                    response_language,
                ),
                "focus_area": focus_area,
            }
        if action == "retry_review":
            return {
                "artifact_kind": "review",
                "rationale": localized_text(
                    "Use this after you land a patch and want the next review loop to stay priority-ordered.",
                    "\u5f53\u4f60\u5df2\u7ecf\u843d\u4e0b\u4e00\u7248 patch\uff0c\u60f3\u8ba9\u4e0b\u4e00\u8f6e review \u7ee7\u7eed\u4fdd\u6301\u4f18\u5148\u7ea7\u987a\u5e8f\u65f6\uff0c\u7528\u8fd9\u4e2a\u3002",
                    response_language,
                ),
                "prompt": localized_text(
                    "Review again after the latest patch and show the next highest-leverage remaining issue.",
                    "\u57fa\u4e8e\u6700\u65b0\u7684 patch \u91cd\u65b0 review\uff0c\u5e76\u6307\u51fa\u4e0b\u4e00\u4e2a\u6700\u5173\u952e\u7684\u5269\u4f59\u95ee\u9898\u3002",
                    response_language,
                ),
                "focus_area": focus_area,
            }
        if action == "review":
            return {
                "artifact_kind": "review",
                "rationale": localized_text(
                    "Use this when code or diagnostics need a coach-led, priority-ordered fix path.",
                    "\u5f53 code \u6216 diagnostics \u9700\u8981\u4e00\u6761\u7531 Coach \u4e3b\u5bfc\u3001\u6309\u4f18\u5148\u7ea7\u6392\u5e8f\u7684\u4fee\u590d\u8def\u5f84\u65f6\uff0c\u7528\u8fd9\u4e2a\u3002",
                    response_language,
                ),
                "prompt": localized_text(
                    "Review the current implementation and name the first fix before widening scope.",
                    "review \u5f53\u524d\u5b9e\u73b0\uff0c\u5e76\u5728\u6269\u5927\u8303\u56f4\u524d\u5148\u70b9\u51fa\u7b2c\u4e00\u4e2a\u4f18\u5148\u4fee\u590d\u70b9\u3002",
                    response_language,
                ),
                "focus_area": focus_area,
            }
        if action == "task":
            artifact_kind = (
                "project_idea"
                if scenario == "project_idea"
                else "project_source"
                if scenario == "project_sourcing"
                else "task"
            )
            return {
                "artifact_kind": artifact_kind,
                "rationale": localized_text(
                    "Use this when you want to turn the current focus into one thin exercise instead of broad discussion.",
                    "\u5f53\u4f60\u60f3\u628a\u5f53\u524d\u805a\u7126\u70b9\u6536\u675f\u6210\u4e00\u9053\u5f88\u8584\u7684\u8bad\u7ec3\u9898\uff0c\u800c\u4e0d\u662f\u7ee7\u7eed\u6cdb\u8c08\u65f6\uff0c\u7528\u8fd9\u4e2a\u3002",
                    response_language,
                ),
                "prompt": localized_text(
                    "Turn this into one focused implementation exercise with clear verification and a tight review loop.",
                    "\u628a\u8fd9\u91cc\u6536\u675f\u6210\u4e00\u9053\u805a\u7126\u7684\u5b9e\u73b0\u9898\uff0c\u5e76\u7ed9\u51fa\u6e05\u695a\u7684\u9a8c\u8bc1\u65b9\u5f0f\u548c\u7d27\u51d1\u7684 review loop\u3002",
                    response_language,
                ),
                "focus_area": focus_area,
            }
        if action == "hint" and scenario == "onboarding":
            return {
                "artifact_kind": "idea_implementation",
                "rationale": localized_text(
                    "Stay with conversation and the first-look next. Do not generate a plan, card, or task yet.",
                    "先顺着对话和第一眼判断的下一步走，先不要生成计划、卡片或任务。",
                    response_language,
                ),
                "prompt": localized_text(
                    "Continue from the first-look next. Do not generate a plan, card, or task.",
                    "顺着第一眼判断的下一步继续。不要生成计划、卡片或任务。",
                    response_language,
                ),
                "focus_area": focus_area,
            }
        return {
            "artifact_kind": "principle" if scenario == "principle" else "idea_implementation",
            "rationale": localized_text(
                "Use this when you want a smaller coaching nudge tied to the exact code boundary, not a full branch of work.",
                "\u5f53\u4f60\u53ea\u9700\u8981\u4e00\u4e2a\u8d34\u7740\u5177\u4f53 code \u8fb9\u754c\u7684\u5c0f\u63d0\u793a\uff0c\u800c\u4e0d\u662f\u65b0\u5f00\u4e00\u6761\u4efb\u52a1\u5206\u652f\u65f6\uff0c\u7528\u8fd9\u4e2a\u3002",
                response_language,
            ),
            "prompt": localized_text(
                "Give me a smaller hint grounded in the current code, current focus, and goal.",
                "\u7ed3\u5408\u5f53\u524d code\u3001\u5f53\u524d\u805a\u7126\u70b9\u548c\u76ee\u6807\uff0c\u7ed9\u6211\u4e00\u4e2a\u66f4\u5c0f\u7684\u63d0\u793a\u3002",
                response_language,
            ),
            "focus_area": focus_area,
        }

    def structured_suggested_actions(
        labels: Sequence[str | dict[str, str]],
        *,
        response_language: str | None = None,
        scenario: str | None = None,
        focus_area: str | None = None,
    ) -> list[dict[str, object]]:
        nonlocal action_id_counter
        actions: list[dict[str, object]] = []
        for label_item in labels:
            if isinstance(label_item, dict):
                label = str(label_item.get("label", "")).strip()
                explicit_action = str(label_item.get("action", "")).strip() or None
            else:
                label = str(label_item).strip()
                explicit_action = None
            if not label:
                continue
            action_id_counter += 1
            action = explicit_action or infer_action_type(label)
            defaults = action_defaults(
                action,
                response_language,
                scenario=scenario,
                focus_area=focus_area,
            )
            actions.append(
                {
                    "id": f"suggested-{action_id_counter}",
                    "label": label,
                    "action": action,
                    "rationale": defaults["rationale"],
                    "artifact_kind": defaults["artifact_kind"],
                    "prompt": defaults["prompt"],
                    "focus_area": defaults["focus_area"],
                }
            )
        return actions


    def coach_artifact_title(
        scenario: str,
        response_language: str | None,
        *,
        task: TaskSpec | None = None,
        plan: LearningPlan | None = None,
        evaluation_summary: str | None = None,
        snapshot: WorkbenchSnapshot | None = None,
        runtime: dict[str, object] | None = None,
    ) -> str:
        if scenario == "idea_implementation":
            return localized_text(
                "Implementation path",
                "实现路径",
                response_language,
            )
        if scenario == "onboarding":
            return localized_text(
                "Coach intake",
                "\u6559\u7ec3\u521d\u6b21\u4e86\u89e3",
                response_language,
            )
        if scenario == "project_idea":
            return localized_text(
                "Training opportunity",
                "训练机会",
                response_language,
            )
        if scenario == "project_adaptation":
            return localized_text(
                "Adaptation boundary",
                "\u6539\u9020\u8fb9\u754c",
                response_language,
            )
        if scenario == "project_sourcing":
            return localized_text(
                "Source recommendation",
                "\u9879\u76ee\u6765\u6e90\u5efa\u8bae",
                response_language,
            )
        if scenario == "principle":
            return localized_text(
                "Principle to hold onto",
                "\u6838\u5fc3\u539f\u7406",
                response_language,
            )
        if scenario == "review":
            return localized_text(
                "Review focus",
                "评审重点",
                response_language,
            )
        if scenario == "plan":
            return live_plan_update_heading(
                plan=plan,
                runtime=runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot),
                existing=runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot),
                fallback=localized_text("Plan update", "\u8ba1\u5212\u66f4\u65b0", response_language),
            )
        if scenario in {"task", "next_task"}:
            leftover_runtime = runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot)
            return live_task_heading(
                plan=plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                task_title=task.title if task else "",
                fallback=localized_text("Practice task", "训练任务", response_language),
            )
        return localized_text("Coach note", "\u6559\u7ec3\u63d0\u793a", response_language)

    def stateful_focus_area(
        task: TaskSpec | None,
        plan: LearningPlan | None,
        evaluation=None,
        *,
        snapshot: WorkbenchSnapshot | None = None,
        runtime: dict[str, object] | None = None,
    ) -> str | None:
        resolved_runtime = runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot)
        focus = live_coach_focus_area(
            plan=plan,
            task=task,
            evaluation=evaluation,
            runtime=resolved_runtime,
            existing=resolved_runtime,
        )
        return focus or None

    def live_stage_object_label(
        plan: LearningPlan | None,
        *,
        snapshot: WorkbenchSnapshot | None = None,
        runtime: dict[str, object] | None = None,
        stage: PlanStage | None = None,
    ) -> str:
        resolved_runtime = runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot)
        return live_coach_stage_label(
            plan=plan,
            runtime=resolved_runtime,
            existing=resolved_runtime,
            stage_title=str(getattr(stage, "title", "") or "") if stage is not None else "",
        )

    def artifact_payload(
        *,
        kind: str,
        title: str,
        summary: str,
        content: str | None = None,
        bullets: list[str] | None = None,
        teaser: str | None = None,
        recommended_action: str | None = None,
        rationale: str | None = None,
        focus_area: str | None = None,
        verification: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return CoachArtifact.model_validate(
            {
                "kind": kind,
                "title": title,
                "summary": summary,
                "content": content,
                "bullets": [item for item in bullets or [] if item],
                "teaser": teaser,
                "recommended_action": recommended_action,
                "rationale": rationale,
                "focus_area": focus_area,
                "verification": [item for item in verification or [] if item],
                "metadata": metadata or {},
            }
        ).model_dump()

    def render_artifact_content(
        *,
        title: str,
        summary: str,
        bullets: list[str] | None = None,
        verification: list[str] | None = None,
        rationale: str | None = None,
        metadata: dict[str, object] | None = None,
        response_language: str | None = None,
        extras: list[str] | None = None,
    ) -> str:
        bullet_lines = [f"- {item}" for item in (bullets or []) if item]
        verification_lines = [f"- {item}" for item in (verification or []) if item]
        sections: list[str] = [f"## {title}", summary]

        if bullet_lines:
            sections.extend(
                [
                    "",
                    localized_text("### Action path", "### \u63a8\u8fdb\u8def\u5f84", response_language),
                    *bullet_lines,
                ]
            )

        if verification_lines:
            sections.extend(
                [
                    "",
                    localized_text("### Verify", "### \u9a8c\u8bc1\u65b9\u5f0f", response_language),
                    *verification_lines,
                ]
            )

        if rationale:
            sections.extend(
                [
                    "",
                    localized_text("### Why this matters", "### \u4e3a\u4ec0\u4e48\u8fd9\u6837\u63a8\u8fdb", response_language),
                    rationale,
                ]
            )

        coach_focus = metadata.get("coach_focus") if isinstance(metadata, dict) else None
        if isinstance(coach_focus, dict):
            current_focus = coach_focus.get("current_focus")
            next_step = coach_focus.get("next_step")
            review_rhythm = coach_focus.get("review_rhythm")
            focus_rows = [
                (
                    localized_text("Current focus", "\u5f53\u524d\u805a\u7126\u70b9", response_language),
                    current_focus,
                ),
                (
                    localized_text("Next step", "\u4e0b\u4e00\u6b65", response_language),
                    next_step,
                ),
                (
                    localized_text("Review rhythm", "\u590d\u76d8\u8282\u594f", response_language),
                    review_rhythm,
                ),
            ]
            focus_rows = [(label, value) for label, value in focus_rows if isinstance(value, str) and value]
            if focus_rows:
                sections.extend(
                    [
                        "",
                        localized_text("### Coach focus", "### \u6559\u7ec3\u89c6\u89d2", response_language),
                        f"| {localized_text('Field', '\u5b57\u6bb5', response_language)} | {localized_text('Detail', '\u5185\u5bb9', response_language)} |",
                        "| --- | --- |",
                        *[f"| {label} | {value} |" for label, value in focus_rows],
                    ]
                )

        background_mode = metadata.get("background_mode") if isinstance(metadata, dict) else None
        due_at = metadata.get("due_at") if isinstance(metadata, dict) else None
        if background_mode == "embedded" or due_at:
            notes: list[str] = []
            if background_mode == "embedded":
                notes.append(
                    localized_text(
                        "Background research stays embedded in this coaching turn.",
                        "\u540e\u53f0 research \u4fdd\u6301\u5d4c\u5165\u5728\u5f53\u524d\u6559\u7ec3\u56de\u5408\u91cc\u3002",
                        response_language,
                    )
                )
            if isinstance(due_at, str) and due_at:
                notes.append(
                    localized_text(
                        f"Follow-up review due: {due_at}",
                        f"\u540e\u7eed\u590d\u4e60\u5230\u671f\u65f6\u95f4\uff1a{due_at}",
                        response_language,
                    )
                )
            if notes:
                sections.extend(
                    [
                        "",
                        localized_text("### Notes", "### \u5907\u6ce8", response_language),
                        *[f"- {note}" for note in notes],
                    ]
                )

        if extras:
            sections.extend(["", *[extra for extra in extras if extra]])

        return "\n".join(section for section in sections if section is not None).strip()

    def exercise_lines(
        exercise_prompt: dict[str, object] | None,
        response_language: str | None,
    ) -> list[str]:
        if not isinstance(exercise_prompt, dict):
            return []
        prompt = str(exercise_prompt.get("prompt", "") or "").strip()
        success_signal = str(exercise_prompt.get("success_signal", "") or "").strip()
        fallback_step = str(exercise_prompt.get("fallback_step", "") or "").strip()
        raw_constraints = exercise_prompt.get("constraints", [])
        constraints = [
            str(item).strip()
            for item in raw_constraints
            if str(item).strip()
        ] if isinstance(raw_constraints, list) else []
        lines: list[str] = []
        if prompt:
            lines.append(
                localized_text("### Try it now", "### \u73b0\u5728\u8bd5\u7740\u505a", response_language)
            )
            lines.append(prompt)
        if success_signal:
            lines.extend(
                [
                    "",
                    localized_text("### Success signal", "### \u6210\u529f\u4fe1\u53f7", response_language),
                    f"- {success_signal}",
                ]
            )
        if fallback_step:
            lines.extend(
                [
                    "",
                    localized_text("### If this still feels too big", "### \u5982\u679c\u8fd8\u662f\u592a\u5927", response_language),
                    fallback_step,
                ]
            )
        if constraints:
            lines.extend(
                [
                    "",
                    localized_text("### Keep these boundaries", "### \u5148\u5b88\u4f4f\u8fd9\u4e9b\u8fb9\u754c", response_language),
                    *[f"- {item}" for item in constraints[:3]],
                ]
            )
        return lines

    def build_turn_summary(
        *,
        snapshot: WorkbenchSnapshot,
        scenario: str,
        learner_signal: str,
        artifacts: dict[str, object],
        suggested_actions: list[dict[str, object]],
        coach_context: dict[str, object] | None = None,
        response_language: str | None = None,
    ) -> CoachTurnSummary:
        coaching_state = snapshot.coaching_state or CoachingState()
        evaluation = snapshot.evaluation
        active_stage = None
        if snapshot.plan:
            active_stage = next(
                (
                    stage
                    for stage in snapshot.plan.stages
                    if stage.id == snapshot.plan.current_stage_id or stage.status == "active"
                ),
                snapshot.plan.stages[0] if snapshot.plan.stages else None,
            )
        failing_checks: list[str] = []
        if evaluation:
            failing_checks = [
                check.label
                for check in [*evaluation.static_checks, *evaluation.dynamic_checks, *evaluation.semantic_checks]
                if check.status in {"failed", "warning"}
            ]
        artifact_kinds = [str(kind) for kind in artifacts.keys()]
        suggested_action_types = [str(item.get("action", "")) for item in suggested_actions if item.get("action")]
        active_thread = snapshot.memory.active_thread
        active_thread_scenario = (
            str(active_thread.scenario or "").strip()
            if active_thread is not None
            else ""
        )
        history_mode = (
            str(coach_context.get("history_mode") or "").strip().lower()
            if isinstance(coach_context, dict)
            else ""
        )
        fresh_lane = history_mode == "fresh_lane" or (
            bool(active_thread_scenario)
            and scenario != "general"
            and active_thread_scenario != scenario
        )
        suppress_review_signals = fresh_lane and not fresh_lane_keeps_review_signals(scenario)
        summary_text = coaching_state.summary or snapshot.memory.current_focus
        next_step_text = coaching_state.next_step
        thread_decision = coaching_state.decision or ""
        thread_blocker = coaching_state.blocker or ""
        thread_teaching_note = coaching_state.teaching_note or ""
        thread_confidence = coaching_state.confidence or ""
        thread_evidence: list[str] = []
        if not fresh_lane and active_thread is not None:
            if not thread_decision:
                thread_decision = active_thread.decision
            if not thread_blocker:
                thread_blocker = active_thread.blocker
            if not thread_teaching_note:
                thread_teaching_note = active_thread.teaching_note
            if not thread_confidence:
                thread_confidence = active_thread.confidence
        evidence_sources = [coaching_state.evidence]
        if not fresh_lane and active_thread is not None:
            evidence_sources.append(active_thread.evidence)
        for source in evidence_sources:
            for item in source or []:
                text = str(item or "").strip()
                if text and text not in thread_evidence:
                    thread_evidence.append(text)
                if len(thread_evidence) >= 4:
                    break
            if len(thread_evidence) >= 4:
                break
        due_review = (
            None
            if suppress_review_signals
            else snapshot.memory.due_reviews[0] if snapshot.memory.due_reviews else None
        )
        teaching_mode = {
            "onboarding": "coach",
            "review": "review",
            "plan": "plan",
            "task": "practice",
            "next_task": "practice",
            "principle": "principle",
            "project_sourcing": "practice",
        }.get(scenario, "coach")
        emotional_tone = {
            "blocked": "supportive",
            "uncertain": "supportive",
            "curious": "challenging",
            "steady": "steady",
        }.get(learner_signal, "steady")
        if snapshot.tone_decision:
            emotional_tone = {
                "steady": "steady",
                "encouraging": "supportive",
                "concise_rescue": "supportive",
                "reflective": "challenging",
            }.get(snapshot.tone_decision.tone, emotional_tone)
        top_teaching_observation = (
            ""
            if fresh_lane
            else snapshot.memory.teaching_observations[0] if snapshot.memory.teaching_observations else ""
        )
        review_note = localized_text(
            (
                f"Review rhythm: after this slice lands, revisit '{due_review.concept}' through one narrow patch."
                if due_review
                else "Review rhythm: finish this slice, verify it, then decide whether to expand."
            ),
            (
                f"\u590d\u76d8\u8282\u594f\uff1a\u8fd9\u4e00\u6b65\u843d\u5730\u540e\uff0c\u518d\u56f4\u7ed5\u300c{due_review.concept}\u300d\u505a\u4e00\u6b21\u5f88\u7a84\u7684 patch \u5f0f\u56de\u770b\u3002"
                if due_review
                else "\u590d\u76d8\u8282\u594f\uff1a\u5148\u5b8c\u6210\u8fd9\u4e00\u5c0f\u6b65\u5e76\u9a8c\u8bc1\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u7ee7\u7eed\u5c55\u5f00\u3002"
            ),
            response_language,
        )
        if scenario == "idea_implementation":
            summary_text = localized_text(
                "Current focus: turn the idea into one thin, verifiable patch before widening scope.",
                "当前聚焦点：先把这个想法收成一个很小、可验证的 patch，再扩大范围。",
                response_language,
            )
        elif scenario == "onboarding":
            summary_text = localized_text(
                "Current focus: first understand your goal, current level, and project situation before choosing the coaching lane.",
                "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u5148\u7406\u89e3\u4f60\u7684\u76ee\u6807\u3001\u5f53\u524d\u6c34\u5e73\u548c project \u5904\u5883\uff0c\u518d\u4e00\u8d77\u5b9a\u6559\u7ec3\u4e3b\u7ebf\u3002",
                response_language,
            )
            first_look_next = first_look_recommended_next_from_snapshot(snapshot)
            next_step_text = first_look_next or localized_text(
                "Clarify the first lane, the current blocker, and the rhythm you want the coach to keep.",
                "\u5148\u660e\u786e\u7b2c\u4e00\u6761\u4e3b\u7ebf\u3001\u5f53\u524d\u5361\u70b9\uff0c\u4ee5\u53ca\u4f60\u5e0c\u671b Coach \u4fdd\u6301\u7684\u8282\u594f\u3002",
                response_language,
            )
        elif scenario == "project_sourcing":
            summary_text = localized_text(
                "Current focus: choose one outside project that is realistic enough to train on immediately.",
                "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u9009\u4e00\u4e2a\u73b0\u5b9e\u53ef\u7528\u3001\u80fd\u7acb\u523b\u62ff\u6765\u8bad\u7ec3\u7684\u5916\u90e8 project \u6765\u6e90\u3002",
                response_language,
            )
            next_step_text = localized_text(
                "Pick the smallest credible source, filter out setup-heavy repos, then ask the coach to extract the first task from it.",
                "\u5148\u6311\u6700\u53ef\u4fe1\u4e14\u6700\u5c0f\u7684\u6765\u6e90\uff0c\u8fc7\u6ee4\u6389\u642d\u5efa\u6210\u672c\u8fc7\u9ad8\u7684 repo\uff0c\u518d\u8ba9 Coach \u4ece\u91cc\u9762\u63d0\u70bc\u7b2c\u4e00\u9053\u4efb\u52a1\u3002",
                response_language,
            )
        first_look_next = first_look_recommended_next_from_snapshot(snapshot)
        live_task_title = (
            str(
                snapshot.current_task.title
                or snapshot.current_task.natural_language_goal
                or ""
            ).strip()
            if snapshot.current_task is not None
            else ""
        )
        if (
            first_look_next
            and not live_task_title
            and scenario in {"onboarding", "general"}
        ):
            next_step_text = first_look_next
        if scenario in {"review", "task", "next_task", "plan"} and not suppress_review_signals:
            summary_text = f"{summary_text} {review_note}".strip()
        if scenario in {"idea_implementation", "project_adaptation", "principle"} and not suppress_review_signals:
            next_step_text = f"{next_step_text} {review_note}".strip()
        next_step_text = strip_visible_next_step_prefix(next_step_text)
        return CoachTurnSummary.model_validate(
            {
                "scenario": scenario if scenario in coach_summary_scenarios else "general",
                "learner_signal": learner_signal,
                "summary": summary_text,
                "next_step": next_step_text,
                "encouragement": coaching_state.encouragement,
                "teaching_mode": teaching_mode,
                "emotional_tone": emotional_tone,
                "review_rhythm": "" if suppress_review_signals else snapshot.memory.review_rhythm,
                "teaching_observation": top_teaching_observation,
                "intervention_strategy": coaching_state.intervention_strategy,
                "teaching_goal": coaching_state.teaching_goal,
                "resume_thread": coaching_state.resume_thread,
                "decision": thread_decision,
                "blocker": thread_blocker,
                "teaching_note": thread_teaching_note,
                "confidence": thread_confidence,
                "evidence": thread_evidence,
                "support_strategy": coaching_state.support_strategy,
                "decision_reason": ""
                if suppress_review_signals
                else snapshot.teaching_decision.reason if snapshot.teaching_decision else "",
                "tone": snapshot.tone_decision.tone if snapshot.tone_decision else "steady",
                "verbosity_bias": snapshot.tone_decision.verbosity_bias if snapshot.tone_decision else "medium",
                "active_stage": live_stage_object_label(
                    snapshot.plan,
                    snapshot=snapshot,
                    stage=active_stage,
                )
                or None,
                "active_task": live_plan_update_persist_chrome(
                    plan=snapshot.plan,
                    runtime=coach_focus_runtime_from_snapshot(snapshot),
                    existing=coach_focus_runtime_from_snapshot(snapshot),
                    stage_title=active_stage.title if active_stage else "",
                    task_title=snapshot.current_task.title if snapshot.current_task else "",
                )["active_task"]
                or None,
                "due_review_count": 0 if suppress_review_signals else len(snapshot.memory.due_reviews),
                "review_queue_summary": "" if suppress_review_signals else snapshot.review_queue_summary,
                "failing_checks": failing_checks,
                "artifact_kinds": artifact_kinds,
                "suggested_action_types": suggested_action_types,
                "background_mode": "embedded",
            }
        )

    def coach_focus_bundle(
        *,
        memory,
        response_language: str | None,
        scenario: str,
        coaching_state: CoachingState | None,
        message: str | None = None,
        task: TaskSpec | None = None,
        plan: LearningPlan | None = None,
        grounding_context: dict[str, object] | None = None,
        snapshot: WorkbenchSnapshot | None = None,
    ) -> dict[str, object]:
        bundle_stage = None
        if plan:
            bundle_stage = next(
                (
                    stage
                    for stage in plan.stages
                    if stage.id == plan.current_stage_id or stage.status == "active"
                ),
                plan.stages[0] if plan.stages else None,
            )
        persist_chrome = live_plan_update_persist_chrome(
            plan=plan,
            runtime=coach_focus_runtime_from_snapshot(snapshot),
            existing=coach_focus_runtime_from_snapshot(snapshot),
            stage_title=bundle_stage.title if bundle_stage else "",
            task_title=task.title if task else "",
        )
        stage_focus = persist_chrome["stage_focus"] or None
        task_focus = persist_chrome["active_task"] or None
        scenario_focus = canonical_focus_for_scenario(scenario, response_language) or ""
        turn_focus_hint = resolve_turn_focus_hint(
            user_message=message,
            task_focus=task_focus,
            stage_focus=stage_focus,
        )
        preserve_active_thread = should_preserve_active_thread_for_turn(
            scenario,
            memory.active_thread,
            message=message,
            grounding_context=grounding_context,
        )
        fresh_lane = not preserve_active_thread and (scenario != "general" or bool(turn_focus_hint))
        suppress_review_signals = fresh_lane and not fresh_lane_keeps_review_signals(scenario)
        lane_focus = (
            turn_focus_hint
            or scenario_focus
            or task_focus
            or stage_focus
            or (coaching_state.summary if coaching_state else "")
        )
        due_review_concepts = {
            str(getattr(item, "concept", "") or "").strip().lower()
            for item in getattr(memory, "due_reviews", []) or []
        }
        synthetic_due_reviews = bool(due_review_concepts) and due_review_concepts.issubset(
            {"new-workspace", "plan-discipline", "resource-grounding"}
        )
        relationship_stage = "active" if (
            memory.active_thread
            or memory.learning_outcomes
            or (memory.due_reviews and not synthetic_due_reviews)
        ) else "intake"
        if scenario == "onboarding":
            relationship_stage = "intake"
        elif fresh_lane:
            relationship_stage = "intake"
        first_turn_priority = (
            "orient, reassure, clarify learner goal and choose one coaching lane"
            if relationship_stage == "intake"
            else ""
        )
        if fresh_lane:
            first_turn_priority = "re-anchor on the newly requested coaching lane and keep the first move compact"
        strategy_preference_summary = ""
        teaching_strategy_effectiveness = getattr(memory, "teaching_strategy_effectiveness", []) or []
        if teaching_strategy_effectiveness and not fresh_lane:
            top_strategy = teaching_strategy_effectiveness[0]
            if isinstance(top_strategy, dict):
                focus_label = top_strategy.get("focus_area") or top_strategy.get("scenario") or "current lane"
                strategy_preference_summary = (
                    f"{focus_label}: {top_strategy.get('success_count')}/{top_strategy.get('total_count')} useful outcomes with "
                    f"{top_strategy.get('challenge_level')}/{top_strategy.get('hint_depth')}/"
                    f"{top_strategy.get('explanation_mode')}/{top_strategy.get('next_step_bias')}"
                )
        recent_teaching_signals: list[str] = []
        workspace = getattr(memory, "workspace", {}) or {}
        if not fresh_lane:
            for candidate in (
                workspace.get("latest_turn_teaching_signal") if isinstance(workspace, dict) else None,
                memory.teaching_observations[0] if getattr(memory, "teaching_observations", []) else None,
            ):
                normalized = str(candidate or "").strip()
                if normalized and normalized not in recent_teaching_signals:
                    recent_teaching_signals.append(normalized)
        current_focus = memory.current_focus
        review_rhythm = memory.review_rhythm
        if (
            not review_rhythm
            and scenario in {"next_task", "review", "review_reflection"}
            and memory.due_reviews
        ):
            due_concept = str(memory.due_reviews[0].concept or "current review").strip()
            review_rhythm = localized_text(
                f"Review '{due_concept}' before opening another lane.",
                f"先回看「{due_concept}」，再开启新的主线。",
                response_language,
            )
        teaching_observations = list(memory.teaching_observations[:3])
        recent_wins = list(memory.recent_wins[:2])
        if fresh_lane:
            current_focus = lane_focus or current_focus
            if suppress_review_signals:
                review_rhythm = ""
            teaching_observations = []
            recent_wins = []
        elif not current_focus and coaching_state:
            current_focus = coaching_state.summary
        visible_current_focus = guided_focus_display_value(
            current_focus,
            scenario=scenario,
            response_language=response_language,
        )
        visible_review_rhythm = (
            language_aligned_context_text(review_rhythm, response_language) or str(review_rhythm or "").strip()
        )
        visible_next_step = strip_visible_next_step_prefix(
            language_aligned_context_text(
                coaching_state.next_step if coaching_state else "",
                response_language,
            )
            or (coaching_state.next_step if coaching_state else "")
        )
        visible_strategy_preference_summary = language_aligned_context_text(
            strategy_preference_summary,
            response_language,
        ) or strategy_preference_summary
        return {
            "current_focus": visible_current_focus,
            "review_rhythm": visible_review_rhythm,
            "next_step": visible_next_step,
            "active_stage": stage_focus,
            "active_task": task_focus,
            "scenario": scenario,
            "relationship_stage": relationship_stage,
            "first_turn_priority": first_turn_priority,
            "strategy_preference_summary": visible_strategy_preference_summary,
            "teaching_observations": language_aligned_context_list(
                teaching_observations,
                response_language,
            ),
            "recent_wins": language_aligned_context_list(
                recent_wins,
                response_language,
            ),
            "recent_teaching_signals": language_aligned_context_list(
                recent_teaching_signals[:2],
                response_language,
            ),
            "due_review_count": len(memory.due_reviews),
            "language": response_language or "en-US",
        }


    def _resolve_context_tier(
        request: TurnRequest | SessionMessageRequest,
    ) -> str:
        """Classify a turn as a pure conversational Q&A ("minimal") or "full".

        Minimal turns carry no code anchors, no resources, no attachments, no
        agent-loop demand, and stay on the coach view. They need the coaching
        identity plus the question — not the learner archive, resource
        retrieval, or the run's pedagogy injections. Anything ambiguous
        classifies as full; minimal is only ever a prompt/IO reduction, never
        a behavior gate.
        """
        try:
            if getattr(request, "use_agent_loop", None):
                return "full"
            if getattr(request, "formal_plan_mutation", False):
                return "full"
            if getattr(request, "plan_runtime_recovery", None):
                return "full"
            if getattr(request, "current_file", None) is not None:
                return "full"
            if getattr(request, "workspace_file_snapshot", None):
                return "full"
            if getattr(request, "attachments", None):
                return "full"
            if getattr(request, "resource_ids", None) or getattr(
                request, "resource_composer_intent", None
            ):
                return "full"
            if request_resource_ids(request):
                return "full"
            intent = str(getattr(request, "intent", "") or "coach").strip().lower()
            active_view = str(getattr(request, "active_view", "") or "").strip().lower()
            if intent not in {"", "coach"}:
                return "full"
            if active_view and active_view != "coach":
                return "full"
        except Exception:
            return "full"
        return "minimal"


    def build_user_message_metadata(
        request: TurnRequest | SessionMessageRequest,
        profile: UserProfile | None,
        attachment_delivery: dict[str, object] | None = None,
        *,
        stream_id: str | None = None,
        stream_state: str | None = None,
    ) -> dict[str, object]:
        current_file = request.current_file
        diagnostics = current_file.diagnostics if current_file else []
        metadata: dict[str, object] = {
            "response_language": request.response_language or ("zh-CN" if prefers_chinese(request.response_language) else "en-US"),
            "answer_mode": request.answer_mode or (profile.answer_policy if profile else "auto"),
        }
        if request.active_view:
            metadata["active_view"] = request.active_view
        if isinstance(request, TurnRequest):
            metadata["intent"] = request.intent
        if current_file:
            metadata["current_file"] = current_file.path
            if current_file.content_strategy:
                metadata["content_strategy"] = current_file.content_strategy
            if current_file.content_line_span:
                metadata["content_line_span"] = current_file.content_line_span
            if current_file.selection_range:
                metadata["selection_range"] = current_file.selection_range
            if diagnostics:
                metadata["diagnostics_count"] = len(diagnostics)
            if current_file.recent_files:
                metadata["recent_files"] = current_file.recent_files[:5]
            if current_file.recent_edited_files:
                metadata["recent_edited_files"] = current_file.recent_edited_files[:5]
            if current_file.related_files:
                metadata["related_files"] = current_file.related_files[:4]
                metadata["related_files_count"] = len(current_file.related_files[:4])
            metadata["context_note"] = (
                f"Attached {current_file.language_id} file context"
                if not prefers_chinese(request.response_language)
                else f"\u5df2\u9644\u5e26 {current_file.language_id} \u6587\u4ef6\u4e0a\u4e0b\u6587"
            )
        apply_attachment_delivery_metadata(metadata, attachment_delivery)
        if stream_id:
            metadata["stream_id"] = stream_id
        if stream_state:
            metadata["stream_state"] = stream_state
        attachment_line = attachment_delivery_line(
            attachment_delivery,
            response_language=request.response_language,
        )
        if attachment_line:
            metadata["support"] = {
                "preview": localized_text(
                    "Attached image status",
                    "\u56fe\u7247\u9644\u4ef6\u72b6\u6001",
                    request.response_language,
                ),
                "lines": [attachment_line],
            }
        return metadata

    def streaming_checkpoint_provider_scope(state: SessionState) -> dict[str, str]:
        provider = getattr(state.snapshot, "provider", None)
        return {
            "provider_profile_id": str(getattr(provider, "profile_id", "") or "").strip(),
            "provider_name": str(getattr(provider, "name", "") or "").strip(),
            "base_url": str(getattr(provider, "base_url", "") or "").strip(),
            "model": str(getattr(provider, "model", "") or "").strip(),
        }

    def prepare_stream_user_message(
        *,
        state: SessionState,
        request: TurnRequest | SessionMessageRequest,
        profile: UserProfile | None,
        attachment_delivery: dict[str, object] | None,
        stream_id: str,
    ) -> tuple[ChatMessage, bool]:
        """Durably record one stream's user turn before provider work starts.

        ``stream_id`` is the retry/idempotency key supplied by the webview. A
        retry of the same stream must reuse its already-persisted user message
        rather than append another copy.
        """

        for message in reversed(state.snapshot.messages):
            if message.role != "user" or not isinstance(message.metadata, dict):
                continue
            if str(message.metadata.get("stream_id") or "").strip() != stream_id:
                continue
            if message.content != request.message:
                raise ValueError("stream_id was already used for a different message.")
            return message, False

        user_message = ChatMessage(
            id=f"message-{uuid4().hex[:10]}",
            role="user",
            content=request.message,
            timestamp=datetime.now(UTC),
            metadata=build_user_message_metadata(
                request,
                profile,
                attachment_delivery,
                stream_id=stream_id,
                stream_state="in_progress",
            ),
        )
        state.snapshot.messages.append(user_message)
        state.snapshot.profile = profile
        runtime.memory_service.record_session_message(
            state.session_id,
            f"user: {request.message}",
            workspace_id=state.workspace_id,
        )
        runtime.memory_service.persist_streaming_checkpoint(
            state.workspace_id,
            request_id=stream_id,
            phase="streaming",
            session_id=state.session_id,
            stream_message_id=user_message.id,
            **streaming_checkpoint_provider_scope(state),
        )
        runtime.save_session_state(state.session_id)
        return user_message, True

    def finalize_stream_persistence(
        *,
        state: SessionState,
        user_message: ChatMessage | None,
        stream_id: str,
        committed: bool,
        assistant_message_ids: set[str],
        stream_state: str,
    ) -> None:
        """Persist stream lifecycle state without promoting an unfinished reply."""

        if not committed and assistant_message_ids:
            state.snapshot.messages[:] = [
                message
                for message in state.snapshot.messages
                if message.id not in assistant_message_ids
            ]
        if user_message is not None:
            user_message.metadata["stream_state"] = stream_state
        runtime.memory_service.persist_streaming_checkpoint(
            state.workspace_id,
            request_id=stream_id,
            phase=stream_state,
            session_id=state.session_id,
            stream_message_id=user_message.id if user_message is not None else "",
            stop_reason="" if stream_state == "completed" else stream_state,
            **streaming_checkpoint_provider_scope(state),
        )
        runtime.save_session_state(state.session_id)

    def build_conversation_history(
        messages: list[ChatMessage],
        *,
        drop_latest_user: bool = False,
    ) -> list[dict[str, str]]:
        history_source = list(messages)
        if (
            drop_latest_user
            and history_source
            and history_source[-1].role == "user"
        ):
            history_source = history_source[:-1]

        history: list[dict[str, str]] = []
        for item in history_source:
            if item.role not in {"user", "assistant"}:
                continue
            content = str(item.content or "").strip()
            if not content:
                continue
            if item.role == "assistant" and looks_like_mojibake_text(content):
                continue
            history.append({"role": item.role, "content": content})
        return history

    def completion_stream_delta(streamed_content: str, final_content: str) -> str:
        if not final_content:
            return ""
        if not streamed_content:
            return final_content
        if final_content.startswith(streamed_content):
            return final_content[len(streamed_content) :]
        return ""

    _STREAM_STATUS_PHASES = {
        "preparing_context",
        "requesting_model",
        "intent",
        "pending",
        "executing",
        "succeeded",
        "failed",
        "acked",
        "cancelled",
    }

    def operation_reliability_record(
        *,
        phase: str,
        outcome: str,
        request_id: str | None = None,
    ) -> dict[str, object]:
        record: dict[str, object] = {"phase": phase, "outcome": outcome}
        if request_id:
            record["request_id"] = request_id
        return record

    def attach_operation_reliability(
        payload: dict[str, object],
        *,
        phase: str,
        outcome: str,
        request_id: str | None = None,
    ) -> dict[str, object]:
        record = operation_reliability_record(
            phase=phase,
            outcome=outcome,
            request_id=request_id,
        )
        attached = dict(payload)
        attached["reliability"] = record
        agent_meta = attached.get("agent_meta")
        if isinstance(agent_meta, dict):
            attached["agent_meta"] = {**agent_meta, "reliability": record}
        agent = attached.get("agent")
        if isinstance(agent, dict):
            attached["agent"] = {**agent, "reliability": record}
        return attached

    def reliability_outcome_from_payload(
        payload: dict[str, object],
        *,
        provider_live_usable: bool = True,
        provider_failure_detected: bool = False,
    ) -> str:
        if not provider_live_usable or provider_failure_detected:
            return "failure"
        existing = payload.get("reliability")
        if isinstance(existing, dict):
            outcome = str(existing.get("outcome") or "").strip().lower()
            if outcome in {"success", "failure", "cancelled"}:
                return outcome
        agent_meta = payload.get("agent_meta")
        if not isinstance(agent_meta, dict):
            agent_meta = payload.get("agent")
        if isinstance(agent_meta, dict):
            nested = agent_meta.get("reliability")
            if isinstance(nested, dict):
                outcome = str(nested.get("outcome") or "").strip().lower()
                if outcome in {"success", "failure", "cancelled"}:
                    return outcome
            stop_reason = str(agent_meta.get("stop_reason") or "").strip().lower()
            if stop_reason in {
                "empty_response",
                "language_corruption",
                "truncated",
                "reasoning_only",
                "truncated_or_empty",
            }:
                return "failure"
        return "success"

    # Per-request slim decision for stream complete frames (F3): routes that
    # parsed `fields=slim` from the client payload set this for their task.
    _stream_snapshot_fields: contextvars.ContextVar[str] = contextvars.ContextVar(
        "stream_snapshot_fields", default="full"
    )

    def sse_complete_frame(
        *,
        tokens: int,
        response_data: dict[str, object],
        stream_id: str,
        outcome: str | None = None,
        request_id: str | None = None,
        provider_live_usable: bool = True,
        provider_failure_detected: bool = False,
        snapshot_fields: str = "slim",
    ) -> str:
        resolved_outcome = outcome or reliability_outcome_from_payload(
            response_data,
            provider_live_usable=provider_live_usable,
            provider_failure_detected=provider_failure_detected,
        )
        attached = attach_operation_reliability(
            response_data,
            phase="acked",
            outcome=resolved_outcome,
            request_id=request_id,
        )
        # Snapshot slimming (F3): the stream frame carries only the snapshot
        # revision pointer; callers needing the full snapshot set
        # response_data["_snapshot_fields"] = "full" before calling.
        snapshot_fields = str(response_data.get("_snapshot_fields") or _stream_snapshot_fields.get())
        attached = {
            key: value
            for key, value in attached.items()
            if key != "_snapshot_fields"
        }
        if snapshot_fields != "full" and isinstance(attached, dict) and "snapshot" in attached:
            slim_snapshot = attached.get("snapshot")
            slim_revision = 0
            if isinstance(slim_snapshot, dict):
                slim_revision = int(
                    slim_snapshot.get("snapshotRevision")
                    or slim_snapshot.get("snapshot_revision")
                    or 0
                )
            slim_keep = (
                "reply",
                "session_id",
                "suggested_actions",
                "reliability",
            )
            attached = {
                key: value for key, value in attached.items() if key in slim_keep
            }
            attached["snapshot_revision"] = slim_revision
            attached["snapshot_dirty"] = ["snapshot"]
        return (
            "event: complete\n"
            f"data: {json.dumps({'tokens': tokens, 'response': attached, 'stream_id': stream_id, 'reliability': attached.get('reliability')}, ensure_ascii=False)}\n\n"
        )

    def turn_request_from_stream_payload(
        payload: dict,
        *,
        intent: str = "coach",
    ) -> TurnRequest:
        turn_payload = dict(payload)
        turn_payload.setdefault("intent", intent)
        parsed = TurnRequest.model_validate(turn_payload)
        if not isinstance(parsed, TurnRequest):
            raise TypeError("Stream payload did not produce a TurnRequest.")
        return _normalize_resource_turn_request(parsed)

    async def honest_unusable_provider_stream(
        request: TurnRequest,
        payload: dict,
        *,
        stream_id: str,
        original_intent: str,
        http_request: Request,
        publish_complete=None,
        fail_inflight=None,
    ):
        """Local honest completion: no model call, no invented objects, visible timeline."""

        stream_committed = False
        stream_failed = False
        stream_singleflight_published = False
        request_id = str(request.request_id or "").strip() or None

        async def _abort_fail_closed(
            *,
            error_detail: object | None = None,
            status_code: int | None = None,
        ):
            """Emit failed→acked + publish failure complete so same request_id cannot remint."""
            nonlocal stream_failed, stream_singleflight_published
            stream_failed = True
            failure_payload: dict[str, object] = attach_operation_reliability(
                {},
                phase="acked",
                outcome="failure",
                request_id=request_id,
            )
            if publish_complete is not None and not stream_singleflight_published:
                failure_payload = publish_complete(failure_payload)
                stream_singleflight_published = True
            yield stream_status_event("failed", stream_id)
            if error_detail is not None:
                error_payload: dict[str, object] = {
                    "error": error_detail,
                    "stream_id": stream_id,
                    "terminal": True,
                }
                if status_code is not None:
                    error_payload["status_code"] = status_code
                yield f"event: error\ndata: {json.dumps(error_payload)}\n\n"
            yield stream_status_event("acked", stream_id)
            yield sse_complete_frame(
                tokens=0,
                response_data=failure_payload,
                stream_id=stream_id,
                outcome="failure",
                request_id=request_id,
                provider_live_usable=False,
            )

        try:
            yield stream_status_event("pending", stream_id)
            yield stream_status_event("executing", stream_id)
            try:
                if stream_cancellation_requested(stream_id):
                    # Fail-closed OS timeline: pending→executing→failure→ack (not silent success).
                    async for _abort_frame in _abort_fail_closed():
                        yield _abort_frame
                    return
                try:
                    if await http_request.is_disconnected():
                        async for _abort_frame in _abort_fail_closed():
                            yield _abort_frame
                        return
                except RuntimeError:
                    pass
                response, artifacts, _service = await coach_support.execute_turn(coach_support_deps, 
                    request,
                    payload,
                    stream=False,
                )
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                async for _abort_frame in _abort_fail_closed(
                    error_detail=redact_provider_error(detail),
                    status_code=exc.status_code,
                ):
                    yield _abort_frame
                return
            response_data = json_object_payload(response)
            if artifacts:
                response_data["artifacts"] = artifacts
            response_data["intent"] = original_intent
            response_data = attach_operation_reliability(
                response_data,
                phase="acked",
                outcome="failure",
                request_id=request_id,
            )
            reply_record = response_data.get("reply")
            visible_content = (
                str(reply_record.get("content") or "").strip()
                if isinstance(reply_record, dict)
                else ""
            )
            token_count = 0
            if visible_content:
                token_count = 1
                yield f"data: {json.dumps({'chunk': visible_content})}\n\n"
            yield stream_status_event("failed", stream_id)
            yield stream_status_event("acked", stream_id)
            stream_committed = True
            if publish_complete is not None:
                response_data = publish_complete(response_data)
                stream_singleflight_published = True
            yield sse_complete_frame(
                tokens=token_count,
                response_data=response_data,
                stream_id=stream_id,
                outcome="failure",
                request_id=request_id,
                provider_live_usable=False,
            )
        except asyncio.CancelledError:
            # Fail-closed: failed→acked + publish failure complete (no remint).
            async for _abort_frame in _abort_fail_closed():
                yield _abort_frame
            return
        except GeneratorExit:
            # Client disconnected before the stream committed or failed; stop
            # cleanly without publishing (the finally below still unregisters).
            if not stream_committed and not stream_failed:
                return
            raise
        except Exception as exc:
            async for _abort_frame in _abort_fail_closed(
                error_detail=redact_provider_error(exc),
            ):
                yield _abort_frame
        finally:
            if fail_inflight is not None and not stream_singleflight_published:
                fail_inflight(
                    RuntimeError(
                        "unusable provider stream failed"
                        if stream_failed
                        else "unusable provider stream completed without publishing a payload"
                    )
                )
            unregister_stream_cancellation(stream_id)

    def stream_status_event(phase: str, stream_id: str | None = None) -> str:
        if phase not in _STREAM_STATUS_PHASES:
            raise ValueError(f"Unsupported stream status phase: {phase}")
        payload: dict[str, object] = {"phase": phase}
        if stream_id:
            payload["stream_id"] = stream_id
        return f"event: status\ndata: {json.dumps(payload)}\n\n"

    def stream_event_payload(value: object, stream_id: str) -> object:
        """Attach the transport identity without mutating agent event objects."""

        if not isinstance(value, dict):
            return value
        return {**value, "stream_id": stream_id}

    def stream_frame(event: str, value: object, stream_id: str) -> str:
        return (
            f"event: {event}\n"
            f"data: {json.dumps(stream_event_payload(value, stream_id))}\n\n"
        )

    def safe_stream_delta(
        pending_content: str,
        delta: str,
        full_content: str,
    ) -> tuple[str, str]:
        if looks_like_mojibake_text(full_content):
            return "", ""

        candidate = f"{pending_content}{delta}"
        if looks_like_mojibake_text(candidate):
            return "", ""

        held_suffix_length = max(
            (
                suffix_length
                for fragment in GBK_MOJIBAKE_FRAGMENTS
                for suffix_length in range(1, min(len(candidate), len(fragment) - 1) + 1)
                if candidate.endswith(fragment[:suffix_length])
            ),
            default=0,
        )
        if held_suffix_length:
            return candidate[:-held_suffix_length], candidate[-held_suffix_length:]
        return candidate, ""

    def summarize_support_categories(
        categories: list[str],
        response_language: str | None,
    ) -> str | None:
        normalized = [item.strip() for item in categories if item and item.strip()]
        if not normalized:
            return None
        if prefers_chinese(response_language):
            if len(normalized) == 1:
                return f"\u53c2\u8003\u4e86{normalized[0]}"
            return f"\u53c2\u8003\u4e86{'\u3001'.join(normalized[:-1])}\u548c{normalized[-1]}"
        if len(normalized) == 1:
            return f"Used {normalized[0]}"
        if len(normalized) == 2:
            return f"Used {normalized[0]} and {normalized[1]}"
        return f"Used {', '.join(normalized[:-1])}, and {normalized[-1]}"

    def describe_request_attachment_delivery(
        request: TurnRequest | SessionMessageRequest,
        coaching_service: ProviderService,
        *,
        use_agent_loop: bool,
    ) -> dict[str, object]:
        attachments_payload = [attachment.model_dump() for attachment in request.attachments]
        return coaching_service.describe_attachment_delivery(
            attachments=attachments_payload,
            protocol=getattr(coaching_service._config, "protocol", None) if coaching_service._config else None,
            use_agent_loop=use_agent_loop,
        )

    def normalize_attachment_delivery_payload(
        value: dict[str, object] | None,
    ) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        attachments_present = bool(value.get("attachments_present"))
        raw_image_count = value.get("image_attachment_count")
        image_attachment_count = raw_image_count if isinstance(raw_image_count, int) else 0
        attachments_delivered_to_model = bool(value.get("attachments_delivered_to_model"))
        attachments_delivery_path = str(value.get("attachments_delivery_path") or "").strip() or "not_sent"
        attachments_delivery_reason = str(value.get("attachments_delivery_reason") or "").strip()
        if not attachments_present or image_attachment_count <= 0:
            return None
        return {
            "attachments_present": attachments_present,
            "image_attachment_count": image_attachment_count,
            "attachments_delivered_to_model": attachments_delivered_to_model,
            "attachments_delivery_path": attachments_delivery_path,
            "attachments_delivery_reason": attachments_delivery_reason,
        }

    def apply_attachment_delivery_metadata(
        metadata: dict[str, object],
        attachment_delivery: dict[str, object] | None,
    ) -> None:
        normalized = normalize_attachment_delivery_payload(attachment_delivery)
        if not normalized:
            return
        metadata.update(normalized)

    def attachment_delivery_line(
        attachment_delivery: dict[str, object] | None,
        *,
        response_language: str | None,
    ) -> str | None:
        normalized = normalize_attachment_delivery_payload(attachment_delivery)
        if not normalized:
            return None
        raw_image_attachment_count = normalized.get("image_attachment_count")
        image_attachment_count = (
            raw_image_attachment_count
            if isinstance(raw_image_attachment_count, int)
            else 0
        )
        if image_attachment_count <= 0:
            return None
        attachments_delivered_to_model = bool(normalized.get("attachments_delivered_to_model"))
        attachments_delivery_reason = str(normalized.get("attachments_delivery_reason") or "").strip()
        count_label = localized_text(
            f"{image_attachment_count} image attachment{'s' if image_attachment_count != 1 else ''}",
            f"{image_attachment_count} \u5f20\u56fe\u7247\u9644\u4ef6",
            response_language,
        )
        if attachments_delivered_to_model:
            return localized_text(
                f"{count_label} reached the model as image input.",
                f"{count_label} \u5df2\u4f5c\u4e3a\u56fe\u50cf\u8f93\u5165\u53d1\u9001\u7ed9\u6a21\u578b\u3002",
                response_language,
            )
        reason_suffix = localized_text(
            "The current coach turn could not send images to the model.",
            "\u5f53\u524d\u8fd9\u8f6e\u6559\u7ec3\u5bf9\u8bdd\u8fd8\u4e0d\u80fd\u628a\u56fe\u7247\u53d1\u9001\u7ed9\u6a21\u578b\u3002",
            response_language,
        )
        if attachments_delivery_reason == "agent_loop_disabled":
            reason_suffix = localized_text(
                "This turn stayed on the plain reply path, so images were not forwarded to the model.",
                "",
                response_language,
            )
        elif attachments_delivery_reason == "vision_not_available":
            reason_suffix = localized_text(
                "The current provider turn is not vision-ready, so images were not forwarded to the model.",
                "",
                response_language,
            )
        elif attachments_delivery_reason == "tools_not_available":
            reason_suffix = localized_text(
                "This provider turn was not running on the tool-enabled coach path, so images were not forwarded to the model.",
                "",
                response_language,
            )
        elif attachments_delivery_reason == "non_image_attachments_not_supported":
            reason_suffix = localized_text(
                "Attached files are not forwarded to the model in this coach turn yet.",
                "\u5f53\u524d\u8fd9\u8f6e\u6559\u7ec3\u5bf9\u8bdd\u8fd8\u4e0d\u4f1a\u628a\u6587\u4ef6\u9644\u4ef6\u76f4\u63a5\u53d1\u9001\u7ed9\u6a21\u578b\u3002",
                response_language,
            )
        return localized_text(
            f"{count_label} did not reach the model. {reason_suffix}",
            f"{count_label} \u6ca1\u6709\u9001\u8fbe\u6a21\u578b\u3002{reason_suffix}",
            response_language,
        )

    def build_message_support(
        request: TurnRequest | SessionMessageRequest,
        coach_turn: dict[str, object] | None = None,
        attachment_delivery: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        response_language = request.response_language
        current_file = request.current_file
        coach_context = (
            normalized_object_mapping(coach_turn.get("coach_context"))
            if isinstance(coach_turn, dict)
            else None
        ) or {}
        coach_scenario = str(coach_turn.get("scenario") or "").strip() if isinstance(coach_turn, dict) else ""
        if coach_scenario == "function_guidance" and not is_code_like_current_file(
            normalize_current_file_payload(current_file)
        ):
            current_file = None
        categories: list[str] = []
        lines: list[str] = []

        def push_category(value: str) -> None:
            normalized = value.strip()
            if normalized and normalized not in categories:
                categories.append(normalized)

        def push_line(value: str | None) -> None:
            normalized = str(value or "").strip()
            if normalized and normalized not in lines:
                lines.append(normalized)

        if current_file:
            current_file_name = str(current_file.path or "").replace("\\", "/").rsplit("/", 1)[-1]
            if current_file_name:
                push_category(localized_text("the current file", "\u5f53\u524d\u6587\u4ef6", response_language))
                push_line(
                    localized_text(
                        f"Current file: {current_file_name}",
                        f"\u5f53\u524d\u6587\u4ef6\uff1a{current_file_name}",
                        response_language,
                    )
                )
            if current_file.selection_range:
                push_category(localized_text("the current selection", "\u5f53\u524d\u9009\u533a", response_language))
                push_line(
                    localized_text(
                        f"Selection: {current_file.selection_range}",
                        f"\u9009\u533a\uff1a{current_file.selection_range}",
                        response_language,
                    )
                )
            diagnostics = current_file.diagnostics or []
            if diagnostics:
                push_category(localized_text("recent diagnostics", "\u6700\u8fd1\u8bca\u65ad", response_language))
                push_line(
                    localized_text(
                        f"Diagnostics: {len(diagnostics)} item(s)",
                        f"\u8bca\u65ad\uff1a{len(diagnostics)} \u9879",
                        response_language,
                    )
                )
            related_files = current_file.related_files or []
            related_names: list[str] = []
            for item in related_files[:3]:
                path_value = item.get("path")
                normalized = str(path_value or "").replace("\\", "/").rsplit("/", 1)[-1]
                if normalized:
                    related_names.append(normalized)
            if related_names:
                push_category(localized_text("related files", "\u76f8\u5173\u6587\u4ef6", response_language))
                push_line(
                    localized_text(
                        f"Related files: {', '.join(related_names)}",
                        f"\u76f8\u5173\u6587\u4ef6\uff1a{'\u3001'.join(related_names)}",
                        response_language,
                    )
                )

        requested_resources = coach_context.get("requested_resources")
        if isinstance(requested_resources, list) and requested_resources:
            resource_titles: list[str] = []
            for item in requested_resources[:3]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or item.get("name") or item.get("id") or "").strip()
                if title:
                    resource_titles.append(title)
            if resource_titles:
                push_category(localized_text("attached resources", "\u9644\u5e26\u8d44\u6599", response_language))
                push_line(
                    localized_text(
                        f"Attached resources: {', '.join(resource_titles)}",
                        f"\u9644\u5e26\u8d44\u6599\uff1a{'\u3001'.join(resource_titles)}",
                        response_language,
                    )
                )
        external_references = coach_context.get("external_references")
        if not isinstance(external_references, list) or not external_references:
            external_references = coach_context.get("resource_fragments")
        if isinstance(external_references, list) and external_references:
            first_reference = external_references[0]
            if isinstance(first_reference, dict):
                snippet = str(first_reference.get("snippet") or "").strip()
                source = str(first_reference.get("source") or "").strip()
                trust = first_reference.get("trust_score")
                if snippet:
                    push_category(localized_text("external grounding", "\u5916\u90e8\u53c2\u8003", response_language))
                    suffix = ""
                    if source:
                        suffix = localized_text(
                            f" (source: {source})",
                            f"\uff08\u6765\u6e90\uff1a{source}\uff09",
                            response_language,
                        )
                    if trust is not None:
                        suffix += localized_text(
                            f" [trust {trust}]",
                            "",
                            response_language,
                        )
                    push_line(
                        localized_text(
                            f"Referenced material: {snippet}{suffix}",
                            f"\u53c2\u8003\u8d44\u6599\uff1a{snippet}{suffix}",
                            response_language,
                        )
                    )

        memory_parts: list[str] = []
        current_focus = str(coach_context.get("current_focus") or "").strip()
        if current_focus:
            memory_parts.append(
                localized_text(
                    f"focus on {current_focus[:72]}",
                    f"\u6cbf\u7740\u5f53\u524d\u805a\u7126\u70b9\u7ee7\u7eed\uff1a{current_focus[:48]}",
                    response_language,
                )
            )
        review_rhythm = str(coach_context.get("review_rhythm") or "").strip()
        if review_rhythm:
            memory_parts.append(
                localized_text(
                    f"review rhythm: {review_rhythm[:72]}",
                    f"\u590d\u4e60\u8282\u594f\uff1a{review_rhythm[:48]}",
                    response_language,
                )
            )
        due_review_count = coach_context.get("due_review_count")
        if isinstance(due_review_count, int) and due_review_count > 0:
            memory_parts.append(
                localized_text(
                    f"{due_review_count} due review item(s)",
                    f"{due_review_count} \u9879\u5f85\u590d\u4e60",
                    response_language,
                )
            )
        if memory_parts:
            push_category(localized_text("long-term memory", "长期记忆", response_language))
            push_line(
                localized_text(
                    f"Memory kept in view: {'; '.join(memory_parts)}",
                    f"\u8fd9\u6b21\u4e5f\u5e26\u4e0a\u4e86\u957f\u671f\u8bb0\u5fc6\uff1a{'\uff1b'.join(memory_parts)}",
                    response_language,
                )
            )

        attachment_line = attachment_delivery_line(
            attachment_delivery,
            response_language=response_language,
        )
        if attachment_line:
            push_category(localized_text("attached images", "\u56fe\u7247\u9644\u4ef6", response_language))
            push_line(attachment_line)

        preview = summarize_support_categories(categories, response_language)
        if not preview and not lines:
            return None
        return {
            "preview": preview or localized_text("Used supporting context", "\u53c2\u8003\u4e86\u8865\u5145\u4e0a\u4e0b\u6587", response_language),
            "lines": lines[:6],
        }

    def persist_external_references_as_background(
        *,
        workspace_id: str,
        scenario: str,
        coach_turn_data: dict[str, object] | None,
    ) -> None:
        coach_context = (
            normalized_object_mapping(coach_turn_data.get("coach_context"))
            if isinstance(coach_turn_data, dict)
            else None
        ) or {}
        external_references = coach_context.get("external_references")
        if not isinstance(external_references, list) or not external_references:
            return
        fallback_focus = str(
            coach_context.get("current_focus")
            or coach_context.get("summary")
            or scenario
            or "Current training focus"
        ).strip()
        for item in external_references[:3]:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source", "") or "").strip()
            snippet = str(item.get("snippet", "") or "").strip()
            if not source or not snippet:
                continue
            created_at_raw = str(item.get("created_at") or item.get("fetched_at") or "").strip()
            created_at = None
            if created_at_raw:
                try:
                    created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
                except ValueError:
                    created_at = None
            runtime.research_service.record_background_reference(
                workspace_id=workspace_id,
                focus_area=str(item.get("focus_area", "") or fallback_focus).strip(),
                source=source,
                content=snippet,
                trust_score=float(item.get("trust_score", 0.0) or 0.0),
                tags=[
                    "coach-turn",
                    f"scenario:{scenario}",
                    str(item.get("reference_origin", "") or "external-reference"),
                ],
                created_at=created_at,
                source_type=str(item.get("source_type", "") or "").strip() or None,
                freshness=str(item.get("freshness", "") or "").strip() or None,
                fetched_at=str(item.get("fetched_at", "") or "").strip() or None,
                why_it_matters=str(item.get("why_it_matters", "") or "").strip() or None,
            )

    def normalize_agent_tool_arguments(value: object) -> dict[str, object]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {"_raw_arguments": raw}
            if isinstance(parsed, dict):
                return parsed
            return {"_raw_arguments": parsed}
        if value is None:
            return {}
        return {"_raw_arguments": value}

    def localized_agent_tool_label(
        tool_name: str,
        response_language: str | None,
    ) -> str:
        labels = {
            "search_resources": ("resource search", "资料搜索"),
            "read_workspace_file": ("file read", "代码读取"),
            "list_workspace_files": ("file listing", "文件浏览"),
            "recall_memory": ("memory recall", "记忆回看"),
            "record_learning_note": ("note save", "学习记录"),
            "inspect_plan": ("plan check", "计划核对"),
            "generate_training_card": ("training card", "训练卡生成"),
            "run_diagnostics": ("diagnostics", "诊断检查"),
            "coach_finalize": ("wrap-up", "收束"),
        }
        english, chinese = labels.get(tool_name, (tool_name.replace("_", " ").strip() or tool_name, tool_name))
        return localized_text(english, chinese, response_language)

    def unique_text_items(values: list[str] | None, *, limit: int = 3) -> list[str]:
        items: list[str] = []
        for raw_value in values or []:
            normalized = str(raw_value or "").strip()
            if not normalized or normalized in items:
                continue
            items.append(normalized)
            if len(items) >= limit:
                break
        return items

    def coach_turn_summary_text(
        turn_summary: CoachTurnSummary | dict[str, object] | None,
        field: str,
    ) -> str:
        if isinstance(turn_summary, CoachTurnSummary):
            return str(getattr(turn_summary, field, "") or "").strip()
        if isinstance(turn_summary, dict):
            return str(turn_summary.get(field) or "").strip()
        return ""

    def normalized_object_mapping(value: object | None) -> dict[str, object] | None:
        """Copy JSON-like mappings into the router's string-keyed payload shape."""

        if not isinstance(value, dict):
            return None
        return {key: item for key, item in value.items() if isinstance(key, str)}

    def build_next_step_hint(
        *,
        snapshot: WorkbenchSnapshot,
        response_language: str | None,
        current_step: str = "",
        why_now: str = "",
        verify_method: list[str] | None = None,
        coach_turn: dict[str, object] | None = None,
        agent_meta: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        raw_coach_context = coach_turn.get("coach_context") if isinstance(coach_turn, dict) else None
        coach_context = normalized_object_mapping(raw_coach_context) or {}
        raw_turn_summary = coach_turn.get("coach_turn") if isinstance(coach_turn, dict) else None
        turn_summary: CoachTurnSummary | dict[str, object] | None = (
            raw_turn_summary
            if isinstance(raw_turn_summary, CoachTurnSummary)
            else normalized_object_mapping(raw_turn_summary)
        )
        active_stage = active_plan_stage(snapshot.plan)
        active_thread = snapshot.memory.active_thread
        coaching_state = snapshot.coaching_state
        resolved_scenario = (
            coach_turn_summary_text(turn_summary, "scenario")
            or str(getattr(coaching_state, "scenario", "") or "").strip()
            or "general"
        )
        preserve_active_thread = should_preserve_active_thread_for_scenario(
            resolved_scenario,
            active_thread,
        )
        if not preserve_active_thread:
            active_thread = None
        active_thread_focus = str(getattr(active_thread, "focus_area", "") or "").strip()
        active_thread_summary = str(getattr(active_thread, "summary", "") or "").strip()
        active_thread_next_step = str(getattr(active_thread, "next_step", "") or "").strip()
        evaluation = snapshot.evaluation
        task = snapshot.current_task
        implementation_guide = snapshot.implementation_guide
        review_item = snapshot.memory.due_reviews[0] if snapshot.memory.due_reviews else None
        verify_items = unique_text_items(verify_method)
        leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
        if (
            not verify_items
            and snapshot.plan
            and leftover_formal_plan_is_live_for_fill(
                plan=snapshot.plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
        ):
            verify_items = unique_text_items(list(snapshot.plan.verify_method))
        if not verify_items and task:
            verify_items = unique_text_items(list(task.verification_strategy))

        title = str(current_step or "").strip()
        reason = str(why_now or "").strip()
        agent_next_step = str(agent_meta.get("next_step") or "").strip() if isinstance(agent_meta, dict) else ""
        agent_summary = str(agent_meta.get("summary") or "").strip() if isinstance(agent_meta, dict) else ""
        turn_next_step = coach_turn_summary_text(turn_summary, "next_step")
        turn_summary_value = coach_turn_summary_text(turn_summary, "summary")
        action = "task"
        source = "plan"
        continue_in = "plan"
        # Leftover plan_runtime current_step without a formal plan is pressure-only.
        # Do not mint a plan/task next-step hint from it (tight budget / urgency must not invent a live task).
        if title and snapshot.plan is None:
            title = ""

        if agent_next_step:
            title = agent_next_step
            source = "agent_loop"
            continue_in = "coach"
            if not reason:
                reason = agent_summary
        elif title:
            if evaluation and title == evaluation.next_step.strip():
                source = "evaluation"
                action = "review"
                continue_in = "coach"
            elif implementation_guide and title == implementation_guide.current_step.strip():
                source = "implementation_guide"
            elif active_thread_next_step and title == active_thread_next_step:
                source = "active_thread"
                continue_in = "coach"
                if active_thread_summary and active_thread_summary != title:
                    reason = active_thread_summary
            elif coaching_state and title == coaching_state.next_step.strip():
                source = "coaching_state"
                continue_in = "coach"
            elif turn_next_step and title == turn_next_step:
                source = "coach_turn"
                continue_in = "coach"
            elif task and title in {task.natural_language_goal.strip(), task.title.strip()}:
                source = "task"
        elif turn_next_step:
            title = turn_next_step
            source = "coach_turn"
            continue_in = "coach"
            reason = reason or turn_summary_value
        elif active_thread_next_step:
            title = active_thread_next_step
            source = "active_thread"
            continue_in = "coach"
            reason = reason or active_thread_summary
        elif coaching_state and coaching_state.next_step.strip():
            title = coaching_state.next_step.strip()
            source = "coaching_state"
            continue_in = "coach"
            reason = reason or coaching_state.summary.strip()
        elif evaluation and evaluation.next_step.strip():
            title = evaluation.next_step.strip()
            source = "evaluation"
            action = "review"
            continue_in = "coach"
            reason = reason or evaluation.summary.strip()
        elif task and task.natural_language_goal.strip():
            title = task.natural_language_goal.strip()
            source = "task"
            leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
            reason = live_task_suggested_reason(
                plan=snapshot.plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                reason=reason,
                task_title=task.title,
            )
        elif review_item:
            review_concept = str(getattr(review_item, "concept", "") or "").strip()
            review_reason = str(getattr(review_item, "reason", "") or "").strip()
            review_hint = str(getattr(review_item, "task_hint", "") or "").strip()
            if review_concept:
                title = localized_text(
                    f"Revisit {review_concept} before widening scope.",
                    "",
                    response_language,
                )
            else:
                title = localized_text(
                    "Run one quick review pass before widening scope.",
                    "",
                    response_language,
                )
            source = "review"
            action = "review"
            continue_in = "training"
            reason = reason or review_reason
            if review_hint:
                verify_items = unique_text_items([*verify_items, review_hint])

        leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
        title = live_task_suggested_title(
            plan=snapshot.plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            title=title.strip(),
            goal=task.natural_language_goal if task else "",
            task_title=task.title if task else "",
        )
        # Orphaned runtime current_step (no formal plan) must not become a
        # plan/task-shaped next-step hint under pressure / urgency.
        if snapshot.plan is None and title:
            orphaned_step = str(
                leftover_runtime.get("current_step")
                or leftover_runtime.get("currentStep")
                or ""
            ).strip() if isinstance(leftover_runtime, dict) else ""
            if orphaned_step and title == orphaned_step:
                return None
        if not title:
            return None

        reason = live_task_suggested_reason(
            plan=snapshot.plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            reason=reason,
            task_title=task.title if task else "",
        )
        live_task_focus = live_task_label(
            plan=snapshot.plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=task.title if task else "",
        )
        live_stage_focus = live_coach_stage_label(
            plan=snapshot.plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            stage_title=str(getattr(active_stage, "title", "") or "").strip() if active_stage else "",
        )

        focus_area = ""
        for candidate in (
            active_thread_focus,
            str(coach_context.get("current_focus") or "").strip(),
            snapshot.memory.current_focus,
            live_task_focus,
            live_stage_focus,
        ):
            normalized = str(candidate or "").strip()
            if normalized:
                focus_area = normalized
                break

        if title == active_thread_next_step and active_thread_summary and active_thread_summary != title:
            reason = active_thread_summary

        summary_candidates = [
            reason,
            agent_summary if agent_summary != title else "",
            turn_summary_value if turn_summary_value != title else "",
            active_thread_summary if active_thread_summary != title else "",
            str(coaching_state.summary or "").strip()
            if coaching_state and coaching_state.summary.strip() != title
            else "",
            str(evaluation.summary or "").strip()
            if evaluation and evaluation.summary.strip() != title and source == "evaluation"
            else "",
        ]
        summary_text = next((item for item in summary_candidates if item), "")
        if not summary_text and verify_items:
            summary_text = localized_text(
                f"Keep this slice narrow and verify it with: {verify_items[0]}",
                f"先把这一小步做稳，再用这条验证它：{verify_items[0]}",
                response_language,
            )
        elif not summary_text and focus_area:
            summary_text = localized_text(
                f"Stay on {focus_area} until this step is verified.",
                f"\u5148\u6cbf\u7740\u300c{focus_area}\u300d\u8fd9\u6761\u4e3b\u7ebf\u63a8\u8fdb\uff0c\u9a8c\u8bc1\u901a\u8fc7\u540e\u518d\u6269\u5c55\u3002",
                response_language,
            )
        elif not summary_text:
            summary_text = localized_text(
                "Keep this next move small enough to verify before widening scope.",
                "",
                response_language,
            )

        prompt = localized_text(
            f'Guide me through "{title}" and keep it to this one small step.',
            f'\u8bf7\u56f4\u7ed5\u300c{title}\u300d\u7ee7\u7eed\u6307\u5bfc\u6211\uff0c\u5148\u53ea\u505a\u8fd9\u4e00\u5c0f\u6b65\u3002',
            response_language,
        )
        if action == "review":
            prompt = localized_text(
                f"Review my result against {title} once I try it.",
                f"\u6211\u5c1d\u8bd5\u5b8c\u300c{title}\u300d\u540e\uff0c\u8bf7\u5e2e\u6211\u505a\u4e00\u8f6e\u590d\u76d8\u3002",
                response_language,
            )

        hint_payload: dict[str, object] = {
            "title": title,
            "recommended_action": action,
            "source": source,
            "continue_in": continue_in,
        }
        if summary_text and summary_text != title:
            hint_payload["summary"] = summary_text
        if focus_area:
            hint_payload["focus_area"] = focus_area
        if prompt:
            hint_payload["prompt"] = prompt
        if verify_items:
            hint_payload["verification"] = verify_items[:3]
        resume_thread = str(coach_context.get("resume_thread") or "").strip()
        if not resume_thread and agent_next_step:
            coach_context_summary = str(coach_context.get("summary") or "").strip()
            resume_thread = build_resume_thread_text(
                coach_context_summary or summary_text or agent_summary or title,
                title,
                response_language=response_language,
            )
        if resume_thread:
            hint_payload["resume_thread"] = resume_thread
        return hint_payload

    def build_resume_thread_text(
        summary_text: str,
        next_step_text: str,
        *,
        response_language: str | None,
    ) -> str:
        summary_text = str(summary_text or "").strip()
        next_step_text = strip_visible_next_step_prefix(next_step_text)
        if not summary_text and not next_step_text:
            return ""
        if summary_text and summary_text[-1] not in ".!?\u3002\uff01\uff1f":
            summary_text = f"{summary_text}."
        if summary_text and next_step_text:
            return localized_text(
                f"Resume the live thread around {summary_text} Next: {next_step_text}",
                f"\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u7ee7\u7eed\uff1a{summary_text} \u4e0b\u4e00\u6b65\uff1a{next_step_text}",
                response_language,
            )
        if summary_text:
            return localized_text(
                f"Resume the live thread around {summary_text}",
                f"\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u7ee7\u7eed\uff1a{summary_text}",
                response_language,
            )
        return localized_text(
            f"Resume the live thread. Next: {next_step_text}",
            f"\u7ee7\u7eed\u5f53\u524d\u4e3b\u7ebf\u3002\u4e0b\u4e00\u6b65\uff1a{next_step_text}",
            response_language,
        )


    def build_agent_message_parts(
        agent_meta: dict[str, object] | None,
        *,
        response_language: str | None,
    ) -> list[dict[str, object]]:
        if not isinstance(agent_meta, dict):
            return []
        raw_events = agent_meta.get("tool_events")
        if not isinstance(raw_events, list) or not raw_events:
            return []

        parts: list[dict[str, object]] = []
        for index, item in enumerate(raw_events, start=1):
            if not isinstance(item, dict):
                continue
            event_type = str(item.get("type") or "").strip()
            call_id = str(
                item.get("id")
                or item.get("call_id")
                or item.get("tool_call_id")
                or item.get("name")
                or f"tool-{index}"
            )
            step = item.get("step") if isinstance(item.get("step"), int) else None
            if event_type == "tool_call":
                parts.append(
                    {
                        "type": "tool_call",
                        "id": call_id,
                        "name": str(item.get("name") or "tool"),
                        "status": "called",
                        "args": normalize_agent_tool_arguments(item.get("arguments")),
                        "step": step,
                    }
                )
                continue
            if event_type == "tool_result":
                result_payload = item.get("result")
                tool_name = str(item.get("name") or item.get("tool_name") or "").strip()
                error_text: str | None = None
                if isinstance(result_payload, dict) and result_payload.get("error"):
                    error_text = str(result_payload["error"])
                elif item.get("ok") is False:
                    error_text = localized_text(
                        "Tool execution failed.",
                        "",
                        response_language,
                    )
                part: dict[str, object] = {
                    "type": "tool_result",
                    "callId": call_id,
                    "result": result_payload,
                    "step": step,
                }
                if tool_name:
                    part["name"] = tool_name
                if (
                    tool_name == "verify_practice_current_file"
                    and isinstance(result_payload, dict)
                ):
                    part["displayKind"] = "practice_verification"
                    if result_payload.get("status"):
                        part["status"] = str(result_payload["status"])
                    if "passed" in result_payload:
                        part["passed"] = bool(result_payload.get("passed"))
                    if result_payload.get("path"):
                        part["path"] = str(result_payload["path"])
                    if result_payload.get("summary"):
                        part["summary"] = str(result_payload["summary"])
                    next_step_value = result_payload.get("next_step") or result_payload.get("nextStep")
                    if next_step_value:
                        part["nextStep"] = str(next_step_value)
                if error_text:
                    part["error"] = error_text
                parts.append(part)
        return parts

    def build_agent_finalize_artifact(
        agent_meta: dict[str, object] | None,
        *,
        requires_confirmation: bool = False,
    ) -> dict[str, object] | None:
        if not isinstance(agent_meta, dict):
            return None
        next_step_text = str(agent_meta.get("next_step") or "").strip()
        summary_text = str(agent_meta.get("summary") or "").strip()
        decision_text = str(agent_meta.get("decision") or "").strip()
        blocker_text = str(agent_meta.get("blocker") or "").strip()
        teaching_note_text = str(
            agent_meta.get("teaching_note") or agent_meta.get("teachingNote") or ""
        ).strip()
        resume_thread_text = str(
            agent_meta.get("resume_thread") or agent_meta.get("resumeThread") or ""
        ).strip()
        confidence_text = str(agent_meta.get("confidence") or "").strip()
        evidence_items: list[str] = []
        raw_evidence = agent_meta.get("evidence")
        if isinstance(raw_evidence, list):
            for item in raw_evidence:
                text = str(item).strip()
                if text:
                    evidence_items.append(text)
                if len(evidence_items) >= 3:
                    break
        if not next_step_text:
            return None
        artifact_entry: dict[str, object] = {
            "kind": "next_step",
            "title": next_step_text,
            "recommended_action": "task",
        }
        if summary_text and summary_text != next_step_text:
            artifact_entry["summary"] = summary_text
        metadata: dict[str, object] = {}
        if decision_text:
            metadata["decision"] = decision_text
        if blocker_text:
            metadata["blocker"] = blocker_text
        if teaching_note_text:
            metadata["teaching_note"] = teaching_note_text
        if resume_thread_text:
            metadata["resume_thread"] = resume_thread_text
        if confidence_text:
            metadata["confidence"] = confidence_text
        if evidence_items:
            metadata["evidence"] = evidence_items
            artifact_entry["verification"] = evidence_items
        # Grounding downgrade carrier (§2.5⑤): the webview renders the next-step
        # card as "confirm before acting" from this metadata; the turn's
        # downgraded flag and the agent_meta stamp both light it up.
        require_confirmation = bool(requires_confirmation) or bool(
            agent_meta.get("next_step_requires_confirmation")
            or agent_meta.get("nextStepRequiresConfirmation")
        )
        if require_confirmation:
            metadata["next_step_requires_confirmation"] = True
        grounding_outcome_text = str(agent_meta.get("grounding_outcome") or "").strip()
        if grounding_outcome_text:
            metadata["grounding_outcome"] = grounding_outcome_text
        if metadata:
            artifact_entry["metadata"] = metadata
        return artifact_entry

    def merge_agent_finalize_into_coach_turn(
        coach_turn_data: dict[str, object] | None,
        *,
        summary: object = None,
        next_step: object = None,
        blocker: object = None,
        resume_thread: object = None,
        decision: object = None,
        teaching_note: object = None,
        confidence: object = None,
        evidence: object = None,
    ) -> dict[str, object] | None:
        if not isinstance(coach_turn_data, dict):
            return coach_turn_data

        normalized_summary = str(summary or "").strip()
        normalized_next_step = strip_visible_next_step_prefix(next_step)
        normalized_blocker = str(blocker or "").strip()
        normalized_resume_thread = str(resume_thread or "").strip()
        normalized_decision = str(decision or "").strip()
        normalized_teaching_note = str(teaching_note or "").strip()
        normalized_confidence = str(confidence or "").strip()
        normalized_evidence: list[str] = []
        if isinstance(evidence, list):
            for item in evidence:
                text = str(item or "").strip()
                if text and text not in normalized_evidence:
                    normalized_evidence.append(text)
                if len(normalized_evidence) >= 4:
                    break
        if not any(
            (
                normalized_summary,
                normalized_next_step,
                normalized_blocker,
                normalized_resume_thread,
                normalized_decision,
                normalized_teaching_note,
                normalized_confidence,
                normalized_evidence,
            )
        ):
            return coach_turn_data

        merged = dict(coach_turn_data)
        context_payload = normalized_object_mapping(merged.get("coach_context")) or {}
        fresh_lane = str(context_payload.get("history_mode") or "").strip().lower() == "fresh_lane"
        active_thread = (
            {} if fresh_lane else normalized_object_mapping(context_payload.get("active_thread")) or {}
        )

        scenario = (
            str(merged.get("scenario") or "").strip()
            or str(context_payload.get("scenario") or "").strip()
            or str(active_thread.get("scenario") or "").strip()
        )
        focus_area = (
            str(active_thread.get("focus_area") or "").strip()
            or str(context_payload.get("coach_anchor") or "").strip()
            or str(context_payload.get("current_focus") or "").strip()
            or str(context_payload.get("active_task") or "").strip()
            or str(context_payload.get("active_stage") or "").strip()
        )
        if scenario:
            active_thread["scenario"] = scenario
        if focus_area:
            active_thread["focus_area"] = focus_area
        suppress_review_signals = fresh_lane and not fresh_lane_keeps_review_signals(scenario)
        if fresh_lane:
            for stale_key in ("decision", "blocker", "teaching_note", "confidence", "resume_thread", "evidence"):
                context_payload.pop(stale_key, None)
        if suppress_review_signals:
            context_payload["review_rhythm"] = ""
            context_payload["review_queue_summary"] = ""
            context_payload["due_reviews"] = []
            context_payload["due_review_count"] = 0
        if normalized_summary:
            active_thread["summary"] = normalized_summary
            context_payload["summary"] = normalized_summary
        if normalized_next_step:
            active_thread["next_step"] = normalized_next_step
            context_payload["next_step"] = normalized_next_step
        if normalized_blocker:
            active_thread["blocker"] = normalized_blocker
            context_payload["blocker"] = normalized_blocker
        if normalized_resume_thread:
            context_payload["resume_thread"] = normalized_resume_thread
        if normalized_decision:
            active_thread["decision"] = normalized_decision
            context_payload["decision"] = normalized_decision
        if normalized_teaching_note:
            active_thread["teaching_note"] = normalized_teaching_note
            context_payload["teaching_note"] = normalized_teaching_note
        if normalized_confidence:
            active_thread["confidence"] = normalized_confidence
            context_payload["confidence"] = normalized_confidence
        if normalized_evidence:
            active_thread["evidence"] = normalized_evidence
            context_payload["evidence"] = normalized_evidence
        if active_thread:
            context_payload["active_thread"] = active_thread
        if context_payload:
            merged["coach_context"] = context_payload

        turn_summary = merged.get("coach_turn")
        if isinstance(turn_summary, CoachTurnSummary):
            summary_update: dict[str, object] = {}
            if fresh_lane:
                summary_update.update(
                    {
                        "teaching_observation": "",
                        "resume_thread": "",
                        "decision": "",
                        "blocker": "",
                        "teaching_note": "",
                        "confidence": "",
                        "evidence": [],
                        "decision_reason": "",
                    }
                )
            if suppress_review_signals:
                summary_update.update(
                    {
                        "review_rhythm": "",
                        "due_review_count": 0,
                        "review_queue_summary": "",
                    }
                )
            if normalized_summary:
                summary_update["summary"] = normalized_summary
            if normalized_next_step:
                summary_update["next_step"] = normalized_next_step
            if normalized_resume_thread:
                summary_update["resume_thread"] = normalized_resume_thread
            if normalized_decision:
                summary_update["decision"] = normalized_decision
            if normalized_blocker:
                summary_update["blocker"] = normalized_blocker
            if normalized_teaching_note:
                summary_update["teaching_note"] = normalized_teaching_note
            if normalized_confidence:
                summary_update["confidence"] = normalized_confidence
            if normalized_evidence:
                summary_update["evidence"] = normalized_evidence
            if summary_update:
                merged["coach_turn"] = turn_summary.model_copy(update=summary_update)

        return merged

    def build_assistant_metadata(
        request: TurnRequest | SessionMessageRequest,
        artifacts: dict[str, object],
        snapshot: WorkbenchSnapshot,
        summary: str | None = None,
        coach_turn: dict[str, object] | None = None,
        agent_meta: dict[str, object] | None = None,
        attachment_delivery: dict[str, object] | None = None,
    ) -> dict[str, object]:
        response_language = request.response_language
        metadata: dict[str, object] = {
            "intent": request.intent if isinstance(request, TurnRequest) else "coach",
            "response_language": response_language or ("zh-CN" if prefers_chinese(response_language) else "en-US"),
        }
        if request.active_view:
            metadata["active_view"] = request.active_view
        artifact_entries: list[dict[str, object]] = []
        for kind, artifact in artifacts.items():
            if isinstance(artifact, dict):
                title = artifact.get("title") or artifact.get("summary") or kind
                artifact_entry: dict[str, object] = {"kind": kind, "title": str(title)}
                if artifact.get("summary"):
                    artifact_entry["summary"] = str(artifact["summary"])
                if artifact.get("content"):
                    artifact_entry["content"] = str(artifact["content"])
                if artifact.get("recommended_action"):
                    artifact_entry["recommended_action"] = str(artifact["recommended_action"])
                if artifact.get("rationale"):
                    artifact_entry["rationale"] = str(artifact["rationale"])
                if artifact.get("focus_area"):
                    artifact_entry["focus_area"] = str(artifact["focus_area"])
                if isinstance(artifact.get("verification"), list):
                    artifact_entry["verification"] = [str(item) for item in artifact["verification"][:3]]
                if kind == "task":
                    constraints = artifact.get("constraints")
                    outputs = artifact.get("outputs") or artifact.get("verification_strategy")
                    if isinstance(constraints, list):
                        artifact_entry["bullets"] = [str(item) for item in constraints[:3]]
                    if isinstance(outputs, list):
                        artifact_entry["summary"] = ", ".join(str(item) for item in outputs[:2])
                elif kind == "plan":
                    phases = artifact.get("phases") or artifact.get("stages")
                    if isinstance(phases, list):
                        artifact_entry["summary"] = localized_text(
                            f"{len(phases)} stages",
                            "",
                            response_language,
                        )
                        artifact_entry["bullets"] = [
                            str((phase or {}).get("title", "")) for phase in phases[:3] if isinstance(phase, dict)
                        ]
                elif kind == "evaluation":
                    summary_text = artifact.get("summary")
                    next_step = artifact.get("next_step")
                    if summary_text:
                        artifact_entry["summary"] = str(summary_text)
                    if next_step:
                        artifact_entry["bullets"] = [str(next_step)]
                elif isinstance(artifact.get("bullets"), list):
                    artifact_entry["bullets"] = [str(item) for item in artifact["bullets"][:3]]
                if isinstance(artifact.get("metadata"), dict):
                    artifact_entry["metadata"] = artifact["metadata"]
                artifact_entries.append(artifact_entry)
        finalize_coach_turn_summary = (
            coach_turn.get("coach_turn") if isinstance(coach_turn, dict) else None
        )
        agent_finalize_artifact = build_agent_finalize_artifact(
            agent_meta,
            requires_confirmation=bool(
                isinstance(finalize_coach_turn_summary, CoachTurnSummary)
                and finalize_coach_turn_summary.requires_confirmation
            ),
        )
        if agent_finalize_artifact and not any(
            isinstance(entry, dict)
            and entry.get("kind") == "next_step"
            and (
                entry.get("title") == agent_finalize_artifact.get("title")
                or entry.get("summary") == agent_finalize_artifact.get("summary")
            )
            for entry in artifact_entries
        ):
            artifact_entries.append(agent_finalize_artifact)
        if artifact_entries:
            metadata["artifacts"] = artifact_entries
        if summary:
            metadata["context_note"] = summary
        effective_attachment_delivery = (
            attachment_delivery
            if isinstance(attachment_delivery, dict)
            else agent_meta
            if isinstance(agent_meta, dict)
            else None
        )
        apply_attachment_delivery_metadata(metadata, effective_attachment_delivery)
        support = build_message_support(request, coach_turn, effective_attachment_delivery)
        if support:
            metadata["support"] = support
        structured_signal = structured_plan_progress_signal(
            snapshot=snapshot,
            coach_turn=coach_turn,
        )
        verify_method_value = structured_signal.get("verify_method")
        verify_method = (
            [str(item).strip() for item in verify_method_value if str(item).strip()]
            if isinstance(verify_method_value, list)
            else None
        )
        next_step_hint = build_next_step_hint(
            snapshot=snapshot,
            response_language=response_language,
            current_step=str(structured_signal.get("current_step") or "").strip(),
            why_now=str(structured_signal.get("why_now") or "").strip(),
            verify_method=verify_method,
            coach_turn=coach_turn,
            agent_meta=agent_meta,
        )
        if next_step_hint:
            metadata["next_step_hint"] = next_step_hint
        coach_visible_status = coach_support.build_coach_visible_status(coach_support_deps,
            agent_meta,
            response_language=response_language,
        )
        agent_parts = build_agent_message_parts(
            agent_meta,
            response_language=response_language,
        )
        if coach_visible_status:
            metadata["coach_visible_status"] = coach_visible_status
            agent_parts = [coach_visible_status, *agent_parts]
        if agent_parts:
            metadata["parts"] = agent_parts
        if coach_turn:
            coach_context = coach_turn.get("coach_context")
            if isinstance(coach_context, dict):
                external_references = coach_context.get("external_references")
                if isinstance(external_references, list) and external_references:
                    metadata["external_references"] = external_references[:3]
                else:
                    resource_fragments = coach_context.get("resource_fragments")
                    if isinstance(resource_fragments, list) and resource_fragments:
                        metadata["external_references"] = resource_fragments[:3]
                    else:
                        background_references = coach_context.get("background_references")
                        recent_background_findings = coach_context.get("recent_background_findings")
                        if isinstance(background_references, list) and background_references:
                            metadata["external_references"] = background_references[:3]
                        elif isinstance(recent_background_findings, list) and recent_background_findings:
                            metadata["external_references"] = recent_background_findings[:3]
            turn_summary = coach_turn.get("coach_turn")
            coach_turn_metadata: dict[str, object] = {
                "scenario": str(coach_turn.get("scenario", "general")),
                "learner_signal": str(coach_turn.get("learner_signal", "steady")),
            }
            metadata["coach_turn"] = coach_turn_metadata
            if isinstance(turn_summary, CoachTurnSummary):
                coach_turn_metadata["summary"] = turn_summary.summary
                coach_turn_metadata["next_step"] = strip_visible_next_step_prefix(
                    turn_summary.next_step
                )
                coach_turn_metadata["review_queue_summary"] = turn_summary.review_queue_summary
                coach_turn_metadata["teaching_mode"] = turn_summary.teaching_mode
                coach_turn_metadata["emotional_tone"] = turn_summary.emotional_tone
                coach_turn_metadata["review_rhythm"] = turn_summary.review_rhythm
                coach_turn_metadata["teaching_observation"] = turn_summary.teaching_observation
                coach_turn_metadata["decision_reason"] = turn_summary.decision_reason
                coach_turn_metadata["decision"] = turn_summary.decision
                coach_turn_metadata["blocker"] = turn_summary.blocker
                coach_turn_metadata["teaching_note"] = turn_summary.teaching_note
                coach_turn_metadata["confidence"] = turn_summary.confidence
                coach_turn_metadata["evidence"] = turn_summary.evidence
                coach_turn_metadata["tone"] = turn_summary.tone
                coach_turn_metadata["verbosity_bias"] = turn_summary.verbosity_bias
            if isinstance(coach_context, dict):
                metadata["coach_focus"] = {
                    "current_focus": coach_context.get("current_focus"),
                    "review_rhythm": coach_context.get("review_rhythm"),
                    "next_step": coach_context.get("next_step"),
                    "next_step_hint": next_step_hint or coach_context.get("next_step_hint"),
                    "scenario": coach_context.get("scenario"),
                    "relationship_stage": coach_context.get("relationship_stage"),
                    "first_turn_priority": coach_context.get("first_turn_priority"),
                    "strategy_preference_summary": coach_context.get("strategy_preference_summary"),
                    "continuity_summary": coach_context.get("continuity_summary"),
                    "recent_teaching_signals": coach_context.get("recent_teaching_signals"),
                    "active_stage": coach_context.get("active_stage"),
                    "active_task": coach_context.get("active_task"),
                    "teaching_observations": coach_context.get("teaching_observations"),
                    "recent_wins": coach_context.get("recent_wins"),
                    "due_review_count": coach_context.get("due_review_count"),
                    "requested_resources": coach_context.get("requested_resources"),
                    "requested_resource_count": coach_context.get("requested_resource_count"),
                    "coach_defaults": coach_context.get("coach_defaults"),
                }
                if coach_context.get("pressure_blocks_live_object_mint") is True:
                    metadata["coach_focus"]["pressure_blocks_live_object_mint"] = True
                if coach_context.get("streak_blocks_live_object_mint") is True:
                    metadata["coach_focus"]["streak_blocks_live_object_mint"] = True
                if coach_context.get("closed_loop_return_blocks_task_mint") is True:
                    metadata["coach_focus"]["closed_loop_return_blocks_task_mint"] = True
                resume_thread = str(coach_context.get("resume_thread") or "").strip()
                if resume_thread:
                    coach_turn_metadata["resume_thread"] = resume_thread
        return metadata

    def agent_meta_coaching_state_update(
        agent_meta: dict[str, object] | None,
        *,
        response_scenario: str,
    ) -> dict[str, object]:
        if not isinstance(agent_meta, dict):
            return {}
        stop_reason = str(agent_meta.get("stop_reason") or "").strip()
        if stop_reason not in {
            "coach_finalize",
            "empty_response",
            "formal_plan_commit_missing",
            "language_corruption",
            "language_corruption_recovered",
            *PROVIDER_REPLY_STOP_REASONS,
        }:
            return {}
        update: dict[str, object] = {
            "scenario": response_scenario or "general",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        for target_key, source_keys in {
            "summary": ("summary",),
            "next_step": ("next_step", "nextStep"),
            "resume_thread": ("resume_thread", "resumeThread"),
            "decision": ("decision",),
            "blocker": ("blocker",),
            "teaching_note": ("teaching_note", "teachingNote"),
            "confidence": ("confidence",),
        }.items():
            for source_key in source_keys:
                value = str(agent_meta.get(source_key) or "").strip()
                if value:
                    if target_key == "next_step":
                        value = strip_visible_next_step_prefix(value)
                    update[target_key] = value
                    break
        evidence: list[str] = []
        raw_evidence = agent_meta.get("evidence")
        if isinstance(raw_evidence, list):
            for item in raw_evidence:
                text = str(item or "").strip()
                if text and text not in evidence:
                    evidence.append(text)
                if len(evidence) >= 4:
                    break
        if evidence:
            update["evidence"] = evidence
        return {key: value for key, value in update.items() if value not in ("", [], None)}

    def apply_agent_meta_to_coaching_state(
        snapshot: WorkbenchSnapshot,
        agent_meta: dict[str, object] | None,
        *,
        response_scenario: str,
    ) -> None:
        update = agent_meta_coaching_state_update(
            agent_meta,
            response_scenario=response_scenario,
        )
        if not update:
            return
        current_state = snapshot.coaching_state or CoachingState()
        snapshot.coaching_state = current_state.model_copy(update=update)

    def requires_formal_plan_commit(request: TurnRequest | SessionMessageRequest) -> bool:
        return bool(
            getattr(request, "formal_plan_mutation", False)
            and str(getattr(request, "intent", "") or "").strip().lower() == "plan"
        )

    def formal_plan_commit_tool_succeeded(tool_events: object) -> bool:
        if not isinstance(tool_events, list):
            return False
        for raw_event in tool_events:
            if not isinstance(raw_event, dict):
                continue
            if str(raw_event.get("type") or "").strip() != "tool_result":
                continue
            if str(raw_event.get("name") or "").strip() != "save_formal_plan":
                continue
            result = raw_event.get("result")
            if not isinstance(result, dict):
                continue
            if result.get("ok") is True and result.get("committed") is True:
                return True
        return False

    def formal_plan_commit_verified(
        *,
        state: SessionState,
        request: TurnRequest | SessionMessageRequest,
        agent_meta: dict[str, object] | None,
    ) -> bool:
        if not requires_formal_plan_commit(request):
            return True
        if not formal_plan_commit_tool_succeeded(
            agent_meta.get("tool_events") if isinstance(agent_meta, dict) else None
        ):
            return False
        return runtime.repository.get_latest_plan(state.workspace_id) is not None

    def formal_plan_commit_missing_reply(response_language: str | None) -> str:
        return localized_text(
            "Trainer has not committed a formal plan because the explicit save step did not complete. Confirm the goal, available time, and selected resource evidence, then save the plan in a new plan turn.",
            "正式计划还没有写入，因为明确保存计划的步骤没有完成。请确认目标、可投入时间和已选资料证据，然后在新的计划回合中保存。",
            response_language,
        )

    def formal_plan_commit_missing_next_step(response_language: str | None) -> str:
        return localized_text(
            "Clarify the remaining scope or evidence, then ask Trainer to save the formal plan again.",
            "补齐仍不清楚的范围或证据后，再让 Trainer 重新保存正式计划。",
            response_language,
        )

    def turn_grounding_code_text(request: TurnRequest | SessionMessageRequest) -> str:
        """Code facts a next step may cite: current file content + learner message."""
        parts: list[str] = []
        current_file_payload = normalize_current_file_payload(
            getattr(request, "current_file", None)
        )
        if isinstance(current_file_payload, dict):
            for key in ("path", "Path", "content", "Content"):
                value = str(current_file_payload.get(key) or "").strip()
                if value:
                    parts.append(value)
        message_text = str(getattr(request, "message", "") or "").strip()
        if message_text:
            parts.append(message_text)
        return "\n".join(parts)

    def turn_history_text(snapshot: object) -> str:
        """Prior conversation facts (user + assistant) the next step may cite.

        A next step may legitimately keep referencing a symbol or file that an
        earlier turn introduced (tool call result, earlier reply), so the
        running conversation joins the grounding corpus.
        """
        parts: list[str] = []
        for message in getattr(snapshot, "messages", None) or []:
            role = str(getattr(message, "role", "") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            content = str(getattr(message, "content", "") or "").strip()
            if content:
                parts.append(content)
        return "\n".join(parts[-12:])

    def apply_next_step_grounding_policy(
        *,
        coach_turn: CoachTurnSummary,
        reply_content: str,
        request: TurnRequest | SessionMessageRequest,
        agent_meta: dict[str, object] | None,
        coach_turn_data: CoachTurnPayload | dict[str, object] | None = None,
        history_text: str = "",
    ) -> CoachTurnSummary:
        """Teaching-turn grounding gate (legacy synchronous path).

        Prefer ``resolve_turn_grounding_async`` + ``apply_grounding_decision`` at
        the four persistence points; this synchronous gate remains only for
        response-building paths that never ran the resolve step (no cached
        decision). A wire path must always use the cached decision so each turn
        is decided at most once.
        """
        next_step_text = str(coach_turn.next_step or "").strip()
        if not next_step_text or coach_turn.requires_confirmation:
            return coach_turn
        decision = evaluate_next_step_grounding(
            next_step_text,
            reply_content,
            turn_grounding_code_text(request),
            extra_context=history_text,
        )
        if decision.grounded:
            return coach_turn
        logger.warning(
            "coach turn next_step downgraded to requires_confirmation; "
            "ungrounded symbols: %s; correction: %s",
            ", ".join(decision.referenced_symbols) or "-",
            grounding_correction_instruction(request.response_language),
        )
        # Only attach the diagnostic stamp to EXISTING agent chrome: a clean
        # reply must keep agent_meta absent/empty (sanitization contract).
        # coach_turn.requires_confirmation is the canonical user-facing signal.
        if isinstance(agent_meta, dict) and agent_meta:
            agent_meta["next_step_requires_confirmation"] = True
        if isinstance(coach_turn_data, dict):
            coach_turn_data["requires_confirmation"] = True
        return coach_turn.model_copy(update={"requires_confirmation": True})

    # Grounding assembly (DESIGN.md §2.3/§2.5): one decision per turn, cached on
    # the payload; the four persistence points call resolve → apply in order.
    GROUNDING_DECISION_CACHE_KEY = "_grounding_decision"
    GROUNDING_MEMORY_PROVENANCE_CACHE_KEY = "_grounding_memory_provenance"
    GROUNDING_EVALUATED_NEXT_STEP_CACHE_KEY = "_grounding_evaluated_next_step"

    def grounding_next_step_text(coach_turn_data: object) -> str:
        """The next step currently carried by a coach-turn payload."""
        if not isinstance(coach_turn_data, dict):
            return ""
        turn_summary = coach_turn_data.get("coach_turn")
        if not isinstance(turn_summary, CoachTurnSummary):
            return ""
        return str(turn_summary.next_step or "").strip()

    def grounding_decision_from_payload(coach_turn_data: object) -> GroundingDecision | None:
        """Read the turn's cached decision — only while it still fits the text.

        The decision is keyed to the next-step text it was made for: a second
        execution pass (e.g. ``/turn/stream`` re-running the streamed turn)
        that delivers a different next step invalidates the cache instead of
        shipping the earlier "grounded" conclusion with an unevaluated step.
        """
        if not isinstance(coach_turn_data, dict):
            return None
        cached = coach_turn_data.get(GROUNDING_DECISION_CACHE_KEY)
        if not isinstance(cached, GroundingDecision):
            return None
        evaluated_text = coach_turn_data.get(GROUNDING_EVALUATED_NEXT_STEP_CACHE_KEY)
        if evaluated_text != grounding_next_step_text(coach_turn_data):
            return None
        return cached

    def turn_grounding_turn_id(request: TurnRequest | SessionMessageRequest) -> str:
        explicit = str(getattr(request, "request_id", None) or "").strip()
        if explicit:
            return explicit
        session_part = str(getattr(request, "session_id", None) or "").strip() or "turn"
        return f"{session_part}-{uuid4().hex[:12]}"

    def turn_grounding_file_exists(workspace_root: str, candidate: str) -> bool | None:
        """Workspace-scoped existence for file-pointer claims.

        ``None`` means unverifiable (outside the workspace root, URI paths,
        null bytes, unreadable state) — never a fabricated verdict.
        """
        raw = str(candidate or "").strip().strip("`").strip("\"'")
        if not raw or "\x00" in raw or "://" in raw:
            return None
        try:
            resolved_root = Path(workspace_root).resolve()
            target = Path(raw)
            resolved = (
                target.resolve()
                if target.is_absolute()
                else (resolved_root / target).resolve()
            )
            resolved.relative_to(resolved_root)
            return resolved.exists()
        except (OSError, ValueError):
            return None

    def turn_grounding_workspace_evidence(
        request: TurnRequest | SessionMessageRequest,
    ) -> WorkspaceEvidence:
        """Workspace verification input; remote/URI workspaces stay unverifiable."""
        workspace_id = current_workspace_id(
            session_id=getattr(request, "session_id", None),
            workspace_id=getattr(request, "workspace_id", None),
        )
        workspace_root = runtime.resolve_workspace_path(workspace_id)
        workspace = runtime.memory_service.snapshot(workspace_id).workspace
        if not workspace_root or "://" in workspace_root or bool(workspace.get("remote_name")):
            return WorkspaceEvidence(unverifiable=True)
        return WorkspaceEvidence(
            file_exists=lambda candidate: turn_grounding_file_exists(workspace_root, candidate)
        )

    def grounding_response_coach_turn(
        *,
        coach_turn: CoachTurnSummary,
        decision: GroundingDecision,
    ) -> CoachTurnSummary:
        """Apply a decided outcome to one summary without re-evaluating."""
        updated = coach_turn
        if decision.corrected_next_step and not decision.requires_confirmation:
            updated = updated.model_copy(update={"next_step": decision.corrected_next_step})
        if decision.requires_confirmation and not updated.requires_confirmation:
            updated = updated.model_copy(update={"requires_confirmation": True})
        return updated

    def apply_grounding_decision(
        *,
        coach_turn_payload: CoachTurnPayload | dict[str, object] | None,
        decision: GroundingDecision,
        agent_meta: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        """Cache one decision on the payload and apply it (per evaluated text).

        Idempotent for the same next-step text; when a later execution pass
        replaced the text, the previous decision no longer fits and the new one
        is applied, its flag state replacing the stale one. Writes the
        corrected next step back (``model_copy``), mirrors the downgrade flag,
        stamps the fixed agent_meta keys, and keys the cache to the delivered
        text so ``build_session_response`` never re-evaluates a decided turn.
        """
        if not isinstance(coach_turn_payload, dict):
            return None
        previous_decision = coach_turn_payload.get(GROUNDING_DECISION_CACHE_KEY)
        re_applying = isinstance(previous_decision, GroundingDecision)
        if re_applying:
            evaluated_text = coach_turn_payload.get(GROUNDING_EVALUATED_NEXT_STEP_CACHE_KEY)
            if evaluated_text == grounding_next_step_text(coach_turn_payload):
                return None
        coach_turn_payload[GROUNDING_DECISION_CACHE_KEY] = decision
        turn_summary = coach_turn_payload.get("coach_turn")
        if isinstance(turn_summary, CoachTurnSummary):
            updated_summary = grounding_response_coach_turn(
                coach_turn=turn_summary,
                decision=decision,
            )
            if re_applying and not decision.requires_confirmation:
                # The new text is grounded: a stale downgrade flag from the
                # replaced text must not survive its re-evaluation.
                updated_summary = updated_summary.model_copy(
                    update={"requires_confirmation": False}
                )
            coach_turn_payload["coach_turn"] = updated_summary
            coach_context = coach_turn_payload.get("coach_context")
            if (
                isinstance(coach_context, dict)
                and decision.corrected_next_step
                and not decision.requires_confirmation
            ):
                active_thread = coach_context.get("active_thread")
                if (
                    isinstance(active_thread, dict)
                    and str(active_thread.get("next_step") or "").strip()
                ):
                    active_thread["next_step"] = decision.corrected_next_step
        if decision.requires_confirmation:
            coach_turn_payload["requires_confirmation"] = True
        elif re_applying and "requires_confirmation" in coach_turn_payload:
            coach_turn_payload["requires_confirmation"] = False
        # Key the cache to the text actually delivered (post write-back).
        coach_turn_payload[GROUNDING_EVALUATED_NEXT_STEP_CACHE_KEY] = grounding_next_step_text(
            coach_turn_payload
        )
        # Attach stamps to existing agent chrome. A clean grounded reply keeps
        # agent_meta absent/empty (sanitization contract). A non-clean decision
        # (corrected next step or requires-confirmation downgrade) is surfaced
        # even on guided-lane turns that have no agent chrome — the learner and
        # the maturity harness must be able to see the server verdict — via a
        # minimal honest chrome that stays ``agentic: False``. Returns the
        # agent chrome carrying the stamps (or None) so response builders can
        # adopt it when the caller had none.
        outcome = grounding_outcome(decision)
        clean_pass = outcome == "grounded" and not decision.requires_confirmation
        if isinstance(agent_meta, dict) and agent_meta:
            stamped = agent_meta
        elif clean_pass:
            return None
        else:
            stamped: dict[str, object] = {"agentic": False}
        stamped["grounding_outcome"] = outcome
        stamped["grounding_ungrounded_symbols"] = list(decision.referenced_symbols)
        stamped["grounding_retry_used"] = bool(decision.retry_used)
        stamped["next_step_requires_confirmation"] = bool(decision.requires_confirmation)
        return stamped

    def turn_grounding_retry_eligible(
        *,
        agent_meta: dict[str, object] | None,
        coaching_service: ProviderService | None,
        scenario: str | None = None,
    ) -> bool:
        """A retry needs a model-authored next step and a live-usable provider.

        The regeneration exists to rewrite a next step the model authored; it
        must never run for locally composed steps (lane composition, visible
        repair, recovery/fallback lanes) or for turns with no model chrome at
        all — those go straight to the honest downgrade.
        """
        def _blocked(reason: str) -> bool:
            logger.warning("[grounding] retry blocked: %s", reason)
            return False

        if coaching_service is None:
            return _blocked("no coaching service")
        if str(scenario or "").strip() in DETERMINISTIC_LANE_SCENARIOS:
            # First-turn lanes ship a canonical, hand-composed step (remote
            # boundary, debug loop, function guidance, project adaptation);
            # rewriting it with the model would replace the ruling.
            return _blocked("deterministic lane scenario")
        # The turn just produced a provider reply, so the turn itself is the
        # live proof: only the transport must be configured (no prior Settings
        # test is required for a grounded rewrite).
        if not bool(getattr(coaching_service, "has_api_key", False)):
            return _blocked("no api key")
        service_config = getattr(coaching_service, "_config", None)
        if isinstance(service_config, ProviderConfig) and not provider_transport_is_configured(
            service_config.name,
            service_config.base_url,
            service_config.model,
        ):
            return _blocked("transport not configured")
        if not isinstance(agent_meta, dict) or not agent_meta:
            # The plain guided lane carries no agent chrome, but its reply and
            # next step are still provider-authored (fallbacks set fell_back,
            # so they never arrive here empty). Allowing the rewrite is what
            # turns an ungrounded guided step into a grounded one.
            return True
        if not str(agent_meta.get("next_step") or "").strip():
            return _blocked("no model-authored next step")
        if bool(agent_meta.get("fell_back")):
            return _blocked("fell back")
        if bool(agent_meta.get("local_sequence_fallback")):
            return _blocked("local sequence fallback")
        if bool(agent_meta.get("guided_lane_visible_repaired")):
            return _blocked("visible repaired")
        if str(agent_meta.get("stop_reason") or "").strip() in PROVIDER_REPLY_STOP_REASONS:
            return _blocked("provider reply stop reason")
        return True

    def grounding_retry_first_line(raw: object) -> str:
        """Take the first meaningful line of a regenerated next step."""
        text = str(raw or "").strip().strip("`")
        if not text:
            return ""
        for line in text.splitlines():
            candidate = line.strip().strip("`").strip("\"'").strip()
            if not candidate:
                continue
            lowered = candidate.lower()
            for prefix in ("next step:", "next_step:", "下一步：", "下一步:"):
                if lowered.startswith(prefix):
                    candidate = candidate[len(prefix) :].strip()
                    break
            if candidate.startswith(("-", "*")):
                candidate = candidate[1:].strip()
            return candidate[:300]
        return ""

    async def request_grounding_regeneration(
        *,
        coaching_service: ProviderService,
        request: TurnRequest | SessionMessageRequest,
        reply_content: str,
        next_step_text: str,
        ungrounded: list[str] | None = None,
    ) -> str:
        """One bounded regeneration attempt; any failure degrades to downgrade."""
        code_text = turn_grounding_code_text(request)
        forbidden = [str(item).strip() for item in (ungrounded or []) if str(item).strip()]
        context_parts = [
            f"Learner message:\n{str(request.message or '').strip()[:2000]}",
            f"Coach reply (already delivered):\n{str(reply_content or '').strip()[:2000]}",
            f"Current code:\n{code_text[:2000]}" if code_text.strip() else "",
            f"Rejected next step (references symbols or files that do not exist):\n{next_step_text[:500]}",
            # Naming the forbidden references explicitly prevents the model from
            # copying them out of the rejected step it was just shown.
            f"Do NOT mention any of these unverified references: {', '.join(forbidden)}."
            if forbidden
            else "",
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Trainer's coding coach. "
                    f"{grounding_correction_instruction(request.response_language)} "
                    "Rewrite ONLY the next step as one short actionable sentence. "
                    "Reply with the next step text only, no quotes or prefixes."
                ),
            },
            {
                "role": "user",
                "content": "\n\n".join(part for part in context_parts if part.strip()),
            },
        ]
        try:
            raw = await coaching_service.chat_completion(messages, temperature=0.2, max_tokens=160)
        except Exception:
            # Bounded best-effort retry: a failed regeneration degrades to the
            # honest downgrade instead of masking the failure or crashing the turn.
            logger.warning("grounding retry regeneration failed; downgrading next step")
            return ""
        return grounding_retry_first_line(raw)

    async def resolve_turn_grounding_async(
        *,
        coach_turn_payload: CoachTurnPayload | dict[str, object] | None,
        reply_content: str,
        request: TurnRequest | SessionMessageRequest,
        agent_meta: dict[str, object] | None,
        history_text: str = "",
        coaching_service: ProviderService | None = None,
    ) -> GroundingDecision:
        """Decide this turn's grounding once, with at most one provider retry.

        Runs after the reply completes and before persistence; the returned
        decision is applied via ``apply_grounding_decision`` and cached, so the
        response builder consumes it without evaluating again.
        """
        if not isinstance(coach_turn_payload, dict):
            return GroundingDecision(grounded=True)
        turn_summary = coach_turn_payload.get("coach_turn")
        next_step_text = (
            str(turn_summary.next_step or "").strip()
            if isinstance(turn_summary, CoachTurnSummary)
            else ""
        )
        if not next_step_text:
            return GroundingDecision(grounded=True)
        if isinstance(turn_summary, CoachTurnSummary) and turn_summary.requires_confirmation:
            return GroundingDecision(
                grounded=False,
                referenced_symbols=[],
                retry_used=False,
                requires_confirmation=True,
            )
        facts = build_teaching_turn_facts(
            turn_id=turn_grounding_turn_id(request),
            reply_text=str(reply_content or ""),
            code_text=turn_grounding_code_text(request),
            history_text=history_text,
            user_message=str(request.message or ""),
            workspace_evidence=turn_grounding_workspace_evidence(request),
            agent_evidence=agent_meta,
            next_step_text=next_step_text,
        )
        decision = evaluate_turn_grounding(facts)
        retry_eligible = (
            not decision.grounded
            and coaching_service is not None
            and turn_grounding_retry_eligible(
                agent_meta=agent_meta,
                coaching_service=coaching_service,
                scenario=(
                    str(getattr(turn_summary, "scenario", "") or "")
                    if isinstance(turn_summary, CoachTurnSummary)
                    else ""
                ),
            )
        )
        if retry_eligible and coaching_service is not None:
            regenerated = await request_grounding_regeneration(
                coaching_service=coaching_service,
                request=request,
                reply_content=str(reply_content or ""),
                next_step_text=next_step_text,
                ungrounded=decision.referenced_symbols,
            )
            # `retry_used` means "a retry was attempted" in the rules layer; an
            # empty regeneration is still an attempt, so the re-check runs with
            # the (possibly empty) regenerated text and both layers agree.
            decision = evaluate_turn_grounding(facts, retry_generate=lambda: regenerated)
        if not decision.grounded:
            # Deterministic lane steps and exhausted retries: drop exactly the
            # segments carrying ungrounded references instead of shipping a
            # fabricated demand or replacing the lane ruling.
            trimmed = trim_ungrounded_segments(next_step_text, decision.referenced_symbols)
            if trimmed and trimmed != next_step_text.strip():
                trimmed_facts = build_teaching_turn_facts(
                    turn_id=turn_grounding_turn_id(request),
                    reply_text=str(reply_content or ""),
                    code_text=turn_grounding_code_text(request),
                    history_text=history_text,
                    user_message=str(request.message or ""),
                    workspace_evidence=turn_grounding_workspace_evidence(request),
                    agent_evidence=agent_meta,
                    next_step_text=trimmed,
                )
                if evaluate_turn_grounding(trimmed_facts).grounded:
                    decision = GroundingDecision(
                        grounded=True,
                        referenced_symbols=[],
                        # A correction was attempted and shipped (deterministic
                        # trim, no provider call).
                        retry_used=True,
                        requires_confirmation=False,
                        corrected_next_step=trimmed,
                    )
        if not decision.grounded:
            # One diagnostic line per ungrounded turn: which references failed,
            # whether a retry was allowed, and whether it corrected the step.
            logger.warning(
                "[grounding] ungrounded=%s retry_eligible=%s retry_used=%s corrected=%s",
                decision.referenced_symbols,
                retry_eligible,
                decision.retry_used,
                bool(decision.corrected_next_step),
            )
        # Field-level memory admission mapping (§2.6/§2.7) travels with the
        # decision so persistence can pass it to the memory writer.
        coach_turn_payload[GROUNDING_MEMORY_PROVENANCE_CACHE_KEY] = memory_provenance_summary(
            facts,
            decision,
        )
        return decision

    def repair_generic_finalize_next_step(
        reply_content: str,
        agent_meta: dict[str, object] | None,
        coach_turn_data: dict[str, object] | None,
        *,
        response_language: str | None,
    ) -> dict[str, object] | None:
        """T-0027 repair: when the finalize next_step is generic filler (goal
        restatement, "do a small action" phrasing) or a pasted prose blob
        (markdown headings / code fences / over the extractor's 240-char
        action cap) while the visible reply carries a concrete labelled next
        action, prefer the reply's own labelled action so the structured next
        step matches what the learner is actually told to do. Mutates
        agent_meta in place and re-merges the repaired step into
        coach_turn_data (T-0035), returning the payload to persist. Callers
        must run this BEFORE grounding and memory persistence so every
        consumer — memory thread, grounding gate, response surfaces — sees
        the same shipped step (T-0048)."""
        if not reply_content or not isinstance(agent_meta, dict):
            return coach_turn_data
        finalize_next_step = str(agent_meta.get("next_step") or "").strip()
        generic_fillers = (
            "先做一个小动作",
            "把结果带回来",
            "do a small action",
            # ImplementationCoach rescue/fallback template shapes (T-0029):
            # unanchored by construction unless the target was derived from
            # this turn; prefer the reply's own labelled action.
            "压成一个很小的补丁目标",
            "先交付一个小而可复盘的",
        )
        weighted_length = sum(
            2 if ord(ch) > 0x2E80 else 1 for ch in finalize_next_step
        )
        looks_generic = (
            not finalize_next_step
            or any(filler in finalize_next_step for filler in generic_fillers)
            # CJK-aware short threshold (T-0036): a 6-11 hanzi step can be
            # fully concrete ("先跑一次测试"); counting hanzi as 2 keeps
            # it while still catching 6-letter English fragments.
            or weighted_length < 12
            or len(finalize_next_step) > 240
            or "```" in finalize_next_step
            or "## " in finalize_next_step
        )
        if not looks_generic:
            return coach_turn_data
        reply_action = visible_next_step(reply_content)
        if not reply_action:
            return coach_turn_data
        agent_meta["next_step"] = reply_action
        # T-0035: the pre-repair filler also lives in resume_thread and the
        # coach-turn summary; rebuild both from the repaired step or the
        # generic filler resurfaces next turn through the continuation path.
        repaired_resume = build_resume_thread_text(
            str(agent_meta.get("summary") or ""),
            reply_action,
            response_language=response_language,
        )
        if repaired_resume:
            agent_meta["resume_thread"] = repaired_resume
        if isinstance(coach_turn_data, dict):
            coach_turn_data = merge_agent_finalize_into_coach_turn(
                coach_turn_data,
                summary=str(agent_meta.get("summary") or "") or None,
                next_step=reply_action,
                resume_thread=repaired_resume or None,
            )
        return coach_turn_data


    def to_json_payload(value: object) -> object:
        return sanitize_visible_coach_payload(jsonable_encoder(value))

    def json_object_payload(value: object) -> dict[str, object]:
        encoded_value = to_json_payload(value)
        if not isinstance(encoded_value, dict):
            raise TypeError("Response payload must be a mapping.")
        return {str(key): item for key, item in encoded_value.items()}

    def persist_recovered_plan_resume_after_turn(
        *,
        workspace_id: str,
        request: TurnRequest | SessionMessageRequest,
        reply_content: str,
        agent_meta: dict[str, object] | None,
        coach_context: dict[str, object] | None,
        recovered_status: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        if getattr(request, "formal_plan_mutation", False):
            return None
        accepted = None
        if isinstance(coach_context, dict):
            context_recovery = coach_context.get("plan_runtime_recovery")
            if isinstance(context_recovery, dict) and context_recovery.get("recovered") is True:
                accepted = context_recovery
        if accepted is None:
            accepted = accept_plan_runtime_resume_request(
                getattr(request, "plan_runtime_recovery", None),
                recovered_status=recovered_status,
            )
        reply_facts = extract_structured_plan_runtime_facts(agent_meta)
        if accepted is None:
            scoped_status = plan_runtime_status_from_recovery(
                runtime.memory_service.recover_workspace_facts(workspace_id).get(PLAN_RUNTIME_KEY),
                workspace_id,
            )
            in_progress_status = next(
                (
                    candidate
                    for candidate in (scoped_status, recovered_status)
                    if isinstance(candidate, dict)
                    and str(candidate.get("resume_state") or "").replace("-", "_") == "in_progress"
                ),
                scoped_status or recovered_status,
            )
            accepted = accept_in_progress_plan_runtime_turn(
                intent=str(getattr(request, "intent", "") or ""),
                formal_plan_mutation=bool(getattr(request, "formal_plan_mutation", False)),
                recovered_status=in_progress_status,
            )
            if accepted is None or reply_facts is None:
                return None
        request_id = str(getattr(request, "request_id", "") or "").strip()
        stop_reason = str((agent_meta or {}).get("stop_reason") or "").strip()
        if not recovered_resume_turn_succeeded(reply_content=reply_content, stop_reason=stop_reason):
            return None
        return runtime.memory_service.persist_plan_runtime_resume(
            workspace_id,
            accepted=accepted,
            request_id=request_id,
            reply_facts=reply_facts,
        )


    def persist_response_reflection(
        *,
        workspace_id: str,
        session_id: str | None,
        user_message: str | None = None,
        scenario: str,
        response_language: str | None,
        answer_mode: str | None,
        coach_defaults: CoachDefaults | dict[str, object] | None,
        response: SessionMessageResponse,
    ) -> None:
        response_agent_meta = response.agent_meta if isinstance(response.agent_meta, dict) else {}
        coach_support.persist_turn_reflection(coach_support_deps,
            workspace_id=workspace_id,
            session_id=session_id,
            user_message=user_message,
            scenario=scenario,
            response_language=response_language,
            answer_mode=answer_mode,
            coach_defaults=coach_defaults,
            coach_turn_data={"coach_turn": response.coach_turn},
            stop_reason=str(response_agent_meta.get("stop_reason") or ""),
            recovered_stop_reason=str(response_agent_meta.get("recovered_stop_reason") or ""),
            local_sequence_fallback=bool(response_agent_meta.get("local_sequence_fallback")),
        )

    def current_workspace_id(session_id: str | None = None, workspace_id: str | None = None) -> str:
        return runtime.resolve_workspace_id(session_id=session_id, workspace_id=workspace_id)

    def trusted_write_workspace_id(
        session_id: str | None = None, workspace_id: str | None = None
    ) -> str:
        """Strict workspace binding for trust-sensitive writes (409, no fallback).

        A stale or mismatched caller must not land evidence/asset writes in an
        unrelated workspace: an explicit workspace_id has to agree with the
        session binding, and an unresolvable binding is refused instead of
        falling back to the latest session or the default workspace.
        """
        try:
            return runtime.resolve_workspace_id_for_write(
                session_id=session_id,
                workspace_id=workspace_id,
            )
        except WorkspaceBindingError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc

    def apply_host_workspace_trust_attestation(workspace_id: str, payload: dict) -> None:
        """Apply host-attested workspace_trusted + remote_name before authority/capability."""
        has_remote = "remote_name" in payload or "remoteName" in payload
        has_trusted = (
            "workspace_trusted" in payload
            or "workspaceTrusted" in payload
            or "trusted" in payload
        )
        if not has_remote and not has_trusted:
            return
        trust_patch: dict[str, object] = {}
        if has_remote:
            remote_value = str(
                payload.get("remote_name", payload.get("remoteName") or "") or ""
            ).strip()
            trust_patch["remote_name"] = remote_value
            trust_patch["is_remote_workspace"] = bool(remote_value)
        if has_trusted:
            trust_patch["workspace_trusted"] = bool(
                payload.get(
                    "workspace_trusted",
                    payload.get("workspaceTrusted", payload.get("trusted", False)),
                )
            )
        runtime.memory_service.update_workspace_state(workspace_id, **trust_patch)
        runtime.workspace_authority(workspace_id)

    def require_sandbox_service():
        if runtime.sandbox_service is None:
            raise HTTPException(status_code=503, detail="Sandbox service is not configured.")
        runtime.sandbox_service.set_workspace_sandbox_root_resolver(
            runtime.resolve_workspace_sandbox_root
        )
        return runtime.sandbox_service

    def sync_resource_record_to_sandbox(workspace_id: str, resource: ResourceRecord) -> ResourceRecord:
        sandbox_service = require_sandbox_service()
        synced = sandbox_service.sync_resource(workspace_id, resource)
        runtime.repository.save_resource(workspace_id, synced)
        return synced

    def persist_plan_to_sandbox(
        workspace_id: str,
        plan: LearningPlan | None,
        *,
        reason: str,
    ) -> None:
        if runtime.sandbox_service is None or plan is None:
            return
        try:
            memory = runtime.memory_service.snapshot(workspace_id)
            workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
            recovered = select_plan_runtime_for_scope(
                workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
                workspace_id,
            )
            leftover_runtime = recovered if isinstance(recovered, dict) else {}
            overlay = live_plan_snapshot_persist_chrome(
                plan=plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            runtime.sandbox_service.persist_plan_snapshot(
                workspace_id,
                plan,
                reason=reason,
                overlay=overlay,
                leftover_runtime=leftover_runtime,
            )
        except Exception:
            logger.exception(
                "Failed to persist plan snapshot into Trainer sandbox.",
                extra={"workspace_id": workspace_id},
            )

    def persist_training_card_to_sandbox(
        workspace_id: str,
        card,
        *,
        mark_current: bool = True,
    ) -> None:
        if runtime.sandbox_service is None or card is None:
            return
        leftover = leftover_plan_state_fields(workspace_id)
        leftover_runtime = leftover.get("leftover_runtime")
        try:
            runtime.sandbox_service.persist_training_card(
                workspace_id,
                card,
                mark_current=mark_current,
                leftover_plan=leftover.get("leftover_plan"),
                leftover_runtime=leftover_runtime if isinstance(leftover_runtime, dict) else {},
                leftover_task_title=str(leftover.get("leftover_task_title") or ""),
            )
        except Exception:
            logger.exception(
                "Failed to persist training card into Trainer sandbox.",
                extra={"workspace_id": workspace_id, "card_id": getattr(card, "card_id", "")},
            )

    def persist_training_evaluation_note_to_sandbox(
        *,
        workspace_id: str,
        card,
        passed: bool,
        summary: str,
        next_step: str,
        focus_area: str,
        failed_checks: list[str],
        missing_requirements: list[str],
        evidence_source: str,
    ) -> None:
        if runtime.sandbox_service is None:
            return
        leftover = leftover_plan_state_fields(workspace_id)
        leftover_runtime = leftover.get("leftover_runtime")
        try:
            runtime.sandbox_service.persist_training_evaluation_note(
                workspace_id,
                card=card,
                passed=passed,
                summary=summary,
                next_step=next_step,
                focus_area=focus_area,
                failed_checks=failed_checks,
                missing_requirements=missing_requirements,
                evidence_source=evidence_source,
                leftover_plan=leftover.get("leftover_plan"),
                leftover_runtime=leftover_runtime if isinstance(leftover_runtime, dict) else {},
                leftover_task_title=str(leftover.get("leftover_task_title") or ""),
            )
        except Exception:
            logger.exception(
                "Failed to persist training evaluation note into Trainer sandbox.",
                extra={"workspace_id": workspace_id, "card_id": getattr(card, "card_id", "")},
            )

    def workspace_learning_project_state(workspace_id: str) -> dict[str, str]:
        workspace = runtime.memory_service.snapshot(workspace_id).workspace
        if not isinstance(workspace, dict):
            return {}
        return {
            "prompt_status": str(workspace.get("learning_project_prompt_status") or "").strip().lower(),
            "sandbox_root_override": str(workspace.get("sandbox_root_override") or "").strip(),
            "source_path": str(workspace.get("learning_project_source_path") or "").strip(),
            "folder_name": str(workspace.get("learning_project_folder_name") or "").strip(),
        }

    def workspace_learning_project_prompt_needed(workspace_id: str) -> bool:
        workspace_path = str(runtime.resolve_workspace_path(workspace_id) or "").strip()
        if not workspace_path:
            return False
        state = workspace_learning_project_state(workspace_id)
        return not state.get("prompt_status") and not state.get("sandbox_root_override")

    def workspace_learning_project_prompt_text(
        *,
        workspace_path: str,
        response_language: str | None,
    ) -> str:
        folder_name = Path(workspace_path).name or workspace_path
        return localized_text(
            f"Should Trainer treat the current VS Code folder `{folder_name}` as this workspace's learning project folder? Reply `use this folder` and I will create the matching project folder in Resources and keep it as the sandbox root.",
            f"要把当前 VS Code 打开的文件夹 `{folder_name}` 当作这个 workspace 的学习项目文件夹吗？你回复“用这个文件夹”，我就会在资料库里创建对应的项目文件夹，并把它固定成 sandbox root。",
            response_language,
        )

    def message_confirms_learning_project_folder(message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        return lowered in {
            "yes",
            "ok",
            "okay",
            "sure",
            "use this folder",
            "use current folder",
            "yes use it",
            "同意",
            "可以",
            "好",
            "好的",
            "用这个文件夹",
            "用当前文件夹",
            "就用这个文件夹",
        }

    def message_rejects_learning_project_folder(message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        return lowered in {
            "no",
            "no thanks",
            "not now",
            "skip",
            "不用",
            "先不用",
            "不要",
            "跳过",
        }

    def adopt_workspace_learning_project_folder(
        *,
        workspace_id: str,
        workspace_name: str,
        response_language: str | None,
    ) -> tuple[str, str]:
        sandbox_service = require_sandbox_service()
        workspace_path = str(runtime.resolve_workspace_path(workspace_id) or "").strip()
        suggested_root = runtime.resolve_workspace_sandbox_root(workspace_id)
        if not suggested_root:
            suggested_root = str(
                sandbox_service.suggest_workspace_project_root(
                    workspace_id,
                    workspace_name=workspace_name,
                    workspace_path=workspace_path,
                )
            )
        runtime.register_workspace_sandbox_root(workspace_id, suggested_root)
        runtime.memory_service.update_workspace_state(
            workspace_id,
            sandbox_root_override=suggested_root,
            learning_project_prompt_status="linked",
            learning_project_source_path=workspace_path,
            learning_project_folder_name=Path(suggested_root).name,
        )
        root = sandbox_service.ensure_workspace_root(workspace_id)
        sandbox_service.write(
            workspace_id,
            SandboxWriteRequest(
                workspace_id=workspace_id,
                path="notes/project-link.md",
                content=(
                    f"# {workspace_name or Path(root).name}\n\n"
                    f"- Workspace source: {workspace_path or '(unknown)'}\n"
                    f"- Sandbox root: {root}\n"
                    "- Status: linked as the learning project folder\n"
                ),
                create=True,
            ),
        )
        return str(root), localized_text(
            f"Linked the current VS Code folder to Trainer's learning project folder and fixed the sandbox root at `{root}`.",
            f"已经把当前 VS Code 文件夹绑定成 Trainer 的学习项目文件夹，并把 sandbox root 固定到 `{root}`。",
            response_language,
        )


    def current_snapshot(session_id: str | None = None, workspace_id: str | None = None) -> WorkbenchSnapshot:
        resolved_workspace_id = current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        _, state = resolve_session_history_state(
            session_id=session_id, workspace_id=resolved_workspace_id
        )
        snapshot = state.snapshot.model_copy(deep=True) if state and state.workspace_id == resolved_workspace_id else WorkbenchSnapshot()
        snapshot.context_id = resolved_workspace_id
        snapshot.memory = runtime.memory_service.snapshot(resolved_workspace_id)
        snapshot.profile = runtime.repository.get_profile(resolved_workspace_id)
        runtime.hydrate_plan_context(snapshot, resolved_workspace_id)
        workspace_memory = snapshot.memory.workspace if isinstance(snapshot.memory.workspace, dict) else {}
        workspace_response_language = (
            str(workspace_memory.get("response_language")).strip()
            if workspace_memory.get("response_language")
            else None
        )
        workspace_answer_mode = (
            str(workspace_memory.get("answer_mode")).strip()
            if workspace_memory.get("answer_mode")
            else None
        )
        coach_support.hydrate_snapshot(coach_support_deps,
            snapshot,
            response_language=workspace_response_language,
            answer_mode=workspace_answer_mode or (snapshot.profile.answer_policy if snapshot.profile else None),
            preserve_session_history=bool(state and state.workspace_id == resolved_workspace_id),
        )
        # Hydration may rebuild card routing; a recovered runtime step remains
        # authoritative for the visible training next hop.
        workspace = snapshot.memory.workspace if snapshot.memory is not None else {}
        runtime_record = workspace.get("latest_plan_runtime") if isinstance(workspace, dict) else None
        current_step = str((runtime_record or {}).get("current_step") or "").strip()
        if current_step and isinstance(workspace, dict):
            current_hop = workspace.get("latest_training_next_hop")
            workspace["latest_training_next_hop"] = {
                **(current_hop if isinstance(current_hop, dict) else {}),
                "title": current_step,
                "card_title": current_step,
            }
        return snapshot

    def resolve_session_history_state(
        *,
        session_id: str | None,
        workspace_id: str,
    ) -> tuple[str, SessionState] | tuple[None, None]:
        if session_id:
            state = runtime.get_session(session_id)
            if state is not None and state.workspace_id == workspace_id:
                return state.session_id, state
            restored_payload = runtime.repository.load_session(session_id)
            if restored_payload:
                restored = runtime._restore_session(restored_payload)
                if restored is not None and restored.workspace_id == workspace_id:
                    runtime.sessions[restored.session_id] = restored
                    return restored.session_id, restored

        latest = runtime.latest_session()
        if latest is not None and latest.workspace_id == workspace_id:
            return latest.session_id, latest

        restored_payload = runtime.repository.load_latest_session_for_workspace(workspace_id)
        if restored_payload:
            restored = runtime._restore_session(restored_payload)
            if restored is not None:
                runtime.sessions[restored.session_id] = restored
                return restored.session_id, restored
        return None, None

    def summarize_session_state(state: object) -> str:
        snapshot = getattr(state, "snapshot", None)
        messages = list(getattr(snapshot, "messages", []) or [])
        latest_user = next(
            (
                message
                for message in reversed(messages)
                if getattr(message, "role", "") == "user" and str(getattr(message, "content", "") or "").strip()
            ),
            None,
        )
        if latest_user is not None:
            return str(getattr(latest_user, "content", "") or "").strip()
        if messages:
            last_message = messages[-1]
            return str(getattr(last_message, "content", "") or "").strip()
        workspace = runtime.memory_service.snapshot(getattr(state, "workspace_id", "")).workspace
        if isinstance(workspace, dict):
            for key in ("latest_session_summary", "recent_summary", "summary"):
                value = str(workspace.get(key) or "").strip()
                if value:
                    return value
        workspace_name = str(getattr(state, "workspace_name", "") or "").strip()
        return workspace_name or "Trainer session"

    def refresh_workspace_sessions(workspace_id: str) -> None:
        for state in runtime.sessions.values():
            if state.workspace_id != workspace_id:
                continue
            state.snapshot.context_id = workspace_id
            state.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
            state.snapshot.profile = runtime.repository.get_profile(workspace_id)
            runtime.hydrate_plan_context(state.snapshot, workspace_id)
            runtime.save_session_state(state.session_id)

    def routing_plan_state(workspace_id: str) -> dict[str, object]:
        leftover_fields = leftover_plan_state_fields(workspace_id)
        plan = leftover_fields.get("leftover_plan")
        if not isinstance(plan, LearningPlan):
            return leftover_fields
        active_stage = next(
            (
                stage
                for stage in plan.stages
                if stage.id == plan.current_stage_id or stage.status == "active"
            ),
            plan.stages[0] if plan.stages else None,
        )
        if active_stage is None:
            return leftover_fields
        return {
            "active_stage_id": active_stage.id,
            "active_stage_skills": [item for item in active_stage.outcomes if item],
            "active_project_id": workspace_id,
            **leftover_fields,
        }

    def routing_learner_state(workspace_id: str) -> dict[str, object]:
        memory = runtime.memory_service.snapshot(workspace_id)
        workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
        recent_errors: list[str] = []
        for item in list(memory.learning_outcomes)[-6:]:
            outcome = str(getattr(item, "outcome", "") or "").strip().lower()
            if outcome not in {"fail", "blocked", "repeated_error", "abandoned", "partial"}:
                continue
            focus_area = str(getattr(item, "focus_area", "") or "").strip()
            if focus_area:
                recent_errors.append(focus_area)
            for concept in list(getattr(item, "concepts", []) or [])[:2]:
                cleaned = str(concept or "").strip()
                if cleaned:
                    recent_errors.append(cleaned)
        blocker_focus = str(workspace.get("latest_learning_focus_area") or "").strip()
        needs_rescue = bool(
            str(workspace.get("latest_learning_blocker") or "").strip()
            or str(workspace.get("latest_flashcard_recovery_mode") or "").strip()
        )
        from ..memory.transfer_skills import normalize_transfer_skill_state_record
        from ..pedagogy.evidence_controls import controls_from_profile, routing_learner_overrides

        overrides = routing_learner_overrides(controls_from_profile(memory.coaching_adaptation))
        transfer = normalize_transfer_skill_state_record(workspace.get("latest_transfer_state"))
        adaptation = memory.coaching_adaptation
        scene_count = 0
        if adaptation is not None:
            scene_count = int(getattr(adaptation, "transfer_scene_count", 0) or 0)
        if transfer and int(transfer.get("scene_count") or 0) > scene_count:
            scene_count = int(transfer.get("scene_count") or 0)
        return {
            "weaknesses": list(memory.weaknesses or []),
            "recent_errors": recent_errors,
            "difficulty_preference": overrides["difficulty_preference"],
            "needs_rescue": bool(overrides["needs_rescue"]) or needs_rescue,
            "active_blockers": [blocker_focus] if blocker_focus and needs_rescue else [],
            "preferred_practice_type": overrides.get("preferred_practice_type"),
            "review_frequency": overrides.get("review_frequency"),
            "material_recommendation": overrides.get("material_recommendation"),
            "transfer_scene_count": scene_count,
            "transfer_state": str((transfer or {}).get("state") or ""),
            "time_budget": overrides.get("time_budget"),
            "project_complexity": overrides.get("project_complexity"),
            "task_urgency": overrides.get("task_urgency"),
        }

    def resource_trust_state(resource: ResourceRecord) -> str:
        return resource.trust_state

    def leftover_runtime_for_workspace(workspace_id: str) -> tuple[LearningPlan | None, dict[str, object]]:
        plan = runtime.repository.get_latest_plan(workspace_id)
        memory = runtime.memory_service.snapshot(workspace_id)
        workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
        recovered = select_plan_runtime_for_scope(
            workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
            workspace_id,
        )
        return plan, recovered if isinstance(recovered, dict) else {}

    def require_live_selected_card_for_status(workspace_id: str, card_id: str) -> None:
        """Leftover-not-live dump must not skip/grade/reflect/return as live."""
        require_live_selected_card_for_status_impl(runtime, workspace_id, card_id)

    def training_card_is_live_for_verify(workspace_id: str, card_id: str) -> bool:
        return training_card_is_live_for_verify_impl(runtime, workspace_id, card_id)

    def leftover_task_title_for_workspace(workspace_id: str) -> str:
        memory = runtime.memory_service.snapshot(workspace_id)
        workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
        task = select_latest_current_task(
            workspace.get(CURRENT_TASK_KEY)
            or workspace.get("current_task")
            or workspace.get("currentTask"),
            workspace_id,
        ) or {}
        return str(task.get("title") or "").strip()

    def leftover_plan_state_fields(workspace_id: str) -> dict[str, object]:
        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        return {
            "leftover_plan": leftover_plan,
            "leftover_runtime": leftover_runtime,
            "leftover_task_title": leftover_task_title_for_workspace(workspace_id),
        }

    def leftover_frozen_blocks_turn_generation(workspace_id: str) -> bool:
        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        return leftover_frozen_plan_blocks_generation(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        )

    def recovered_overlay_without_live_object(workspace_id: str) -> bool:
        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        if leftover_plan is None and not leftover_runtime:
            return False
        # Empty recovered runtime (cold-start empty restore) is still a recovered
        # overlay: attach_plan_runtime_status stamps recovered=True for it, so the
        # leftover must read as not-live here too. leftover_formal_plan_is_live_for_fill
        # defaults to True on empty dicts (fill-permissive), hence the explicit guard.
        live_plan = bool(leftover_runtime) and leftover_formal_plan_is_live_for_fill(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        )
        live_task = bool(leftover_runtime) and formal_task_is_live_runtime_identity(
            recovered=True,
            runtime_current_step=str(
                leftover_runtime.get("current_step")
                or leftover_runtime.get("currentStep")
                or ""
            ),
            task_title=leftover_task_title_for_workspace(workspace_id),
        )
        return not live_plan and not live_task

    def closed_loop_return_blocks_task_mint(workspace_id: str) -> bool:
        """After Learn→Try→Verify→Reflect→Return with a live plan, do not invent TaskSpec.

        Explicit POST /task/next and /task/specify remain the mint paths. /turn next_task
        chips must stay hint/review only so the closed loop does not mint a parallel task.
        """
        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
        if not leftover_formal_plan_is_live_for_fill(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            return False
        workspace = runtime.memory_service.snapshot(workspace_id).workspace
        workspace = workspace if isinstance(workspace, dict) else {}
        handoff = workspace.get("latest_training_handoff") or workspace.get("latestTrainingHandoff")
        if not isinstance(handoff, dict) or not handoff:
            return False
        phase = str(handoff.get("phase") or "").strip().lower()
        status = str(handoff.get("status") or "").strip().lower()
        handoff_status = str(
            handoff.get("handoff_status") or handoff.get("handoffStatus") or ""
        ).strip().lower()
        continue_in = str(
            handoff.get("continue_in") or handoff.get("continueIn") or ""
        ).strip().lower()
        if phase == "return" and status in {"completed", "complete"}:
            return True
        return handoff_status == "verified" and continue_in in {"chat", "coach"}

    def live_formal_plan_for_explicit_task_next(workspace_id: str) -> LearningPlan | None:
        """Explicit POST /task/next may mint TaskSpec only for a live-bound formal plan.

        Empty recovered runtime or mismatched plan_id is leftover-not-live: do not invent.
        No formal plan at all: do not invent a plan+task pair (including under high urgency).
        /plan/generate remains the bind path; this route must not invent a LearningPlan.
        """
        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        if leftover_plan is None or not leftover_runtime:
            return None
        if not leftover_formal_plan_is_live_for_fill(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            return None
        return leftover_plan

    def should_remap_task_intent_without_live_plan(
        workspace_id: str,
        *,
        message: str | None = None,
        snapshot: WorkbenchSnapshot | None = None,
        current_task: TaskSpec | None = None,
        current_plan: LearningPlan | None = None,
    ) -> bool:
        """Shared gate: task/next_task intent → coach; no TaskSpec / minting chips.

        Used by request_with_workspace_defaults (/turn, /turn/stream), scenario coerce,
        and honest_suggested_actions (/session/message(+stream) chat parity).
        """
        return (
            live_formal_plan_for_explicit_task_next(workspace_id) is None
            or recovered_overlay_without_live_object(workspace_id)
            or closed_loop_return_blocks_task_mint(workspace_id)
            or streak_without_live_object_blocks_mint(
                workspace_id,
                snapshot=snapshot,
                current_task=current_task,
                current_plan=current_plan,
            )
            or pressure_without_live_object_blocks_mint(
                workspace_id,
                snapshot=snapshot,
                current_task=current_task,
                current_plan=current_plan,
                message=message,
            )
        )

    def require_live_formal_plan_for_explicit_task_next(
        workspace_id: str,
        *,
        route: str = "/task/next",
    ) -> LearningPlan:
        live = live_formal_plan_for_explicit_task_next(workspace_id)
        if live is not None:
            return live
        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        if leftover_plan is not None and leftover_runtime:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Recovered plan runtime is leftover-not-live. "
                    f"{route} will not invent a TaskSpec or resurrect the leftover as live."
                ),
            )
        raise HTTPException(
            status_code=409,
            detail=(
                "No live learning plan is bound. Generate a plan first; "
                f"{route} does not invent a plan or TaskSpec."
            ),
        )

    def streak_without_live_object_blocks_mint(
        workspace_id: str,
        *,
        snapshot: WorkbenchSnapshot | None = None,
        current_task: TaskSpec | None = None,
        current_plan: LearningPlan | None = None,
    ) -> bool:
        from ..pedagogy.evidence_controls import streak_adapts_without_inventing_live_objects

        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        plan = current_plan or leftover_plan
        if plan is None and snapshot is not None:
            plan = snapshot.plan
        task = current_task
        if task is None and snapshot is not None:
            task = snapshot.current_task
        if leftover_runtime:
            live_plan = leftover_formal_plan_is_live_for_fill(
                plan=plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            live_task = formal_task_is_live_runtime_identity(
                recovered=True,
                runtime_current_step=str(
                    leftover_runtime.get("current_step")
                    or leftover_runtime.get("currentStep")
                    or ""
                ),
                task_title=str(
                    getattr(task, "title", "") or leftover_task_title_for_workspace(workspace_id)
                ),
            )
        else:
            live_plan = plan is not None and bool(
                str(getattr(plan, "id", "") or getattr(plan, "plan_id", "") or "").strip()
                or str(getattr(plan, "current_step", "") or "").strip()
            )
            live_task = task is not None and bool(
                str(getattr(task, "title", "") or getattr(task, "natural_language_goal", "") or "").strip()
            )
        live_card = bool(
            workspace_id
            and runtime.memory_service.live_selected_training_card_id(workspace_id)
        )
        adaptation = None
        if snapshot is not None and snapshot.memory is not None:
            adaptation = getattr(snapshot.memory, "coaching_adaptation", None)
        if adaptation is None and workspace_id:
            adaptation = getattr(
                runtime.memory_service.snapshot(workspace_id),
                "coaching_adaptation",
                None,
            )
        failure_streak = int(getattr(adaptation, "failure_streak", 0) or 0) if adaptation is not None else 0
        success_streak = int(getattr(adaptation, "success_streak", 0) or 0) if adaptation is not None else 0
        return streak_adapts_without_inventing_live_objects(
            failure_streak=failure_streak,
            success_streak=success_streak,
            live_plan=live_plan,
            live_task=live_task,
            live_card=live_card,
        )

    def pressure_without_live_object_blocks_mint(
        workspace_id: str,
        *,
        snapshot: WorkbenchSnapshot | None = None,
        current_task: TaskSpec | None = None,
        current_plan: LearningPlan | None = None,
        message: str | None = None,
    ) -> bool:
        from ..pedagogy.context_pressure import (
            normalize_project_complexity,
            normalize_task_urgency,
            normalize_time_budget,
            pressure_adapts_without_inventing_live_objects,
        )

        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        plan = current_plan or leftover_plan
        if plan is None and snapshot is not None:
            plan = getattr(snapshot, "plan", None)
        task = current_task
        if task is None and snapshot is not None:
            task = getattr(snapshot, "current_task", None)
        if leftover_runtime:
            live_plan = leftover_formal_plan_is_live_for_fill(
                plan=plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
            )
            live_task = formal_task_is_live_runtime_identity(
                recovered=True,
                runtime_current_step=str(
                    leftover_runtime.get("current_step")
                    or leftover_runtime.get("currentStep")
                    or ""
                ),
                task_title=str(
                    getattr(task, "title", "") or leftover_task_title_for_workspace(workspace_id)
                ),
            )
        else:
            live_plan = plan is not None and bool(
                str(getattr(plan, "id", "") or getattr(plan, "plan_id", "") or "").strip()
                or str(getattr(plan, "current_step", "") or "").strip()
            )
            live_task = task is not None and bool(
                str(getattr(task, "title", "") or getattr(task, "natural_language_goal", "") or "").strip()
            )
        live_memory = runtime.memory_service.snapshot(workspace_id) if workspace_id else None
        memory = getattr(snapshot, "memory", None) if snapshot is not None else None
        workspace_state: dict[str, object] = {}
        if live_memory is not None and isinstance(getattr(live_memory, "workspace", None), dict):
            workspace_state = live_memory.workspace
        elif memory is not None and isinstance(getattr(memory, "workspace", None), dict):
            workspace_state = memory.workspace
        live_card = bool(
            workspace_id
            and runtime.memory_service.live_selected_training_card_id(workspace_id)
        )
        # Prefer live memory adaptation so just-persisted affect/urgency wins over a
        # stale snapshot coaching_adaptation (high urgency without weekly_hours).
        adaptation = (
            getattr(live_memory, "coaching_adaptation", None)
            if live_memory is not None
            else None
        )
        if adaptation is None and memory is not None:
            adaptation = getattr(memory, "coaching_adaptation", None)
        time_budget = (
            str(getattr(adaptation, "time_budget", "normal") or "normal")
            if adaptation is not None
            else "normal"
        )
        task_urgency = (
            str(getattr(adaptation, "task_urgency", "medium") or "medium")
            if adaptation is not None
            else "medium"
        )
        workspace_urgency = str(
            workspace_state.get("task_urgency")
            or workspace_state.get("taskUrgency")
            or ""
        ).strip()
        if workspace_urgency and normalize_task_urgency(workspace_urgency) == "high":
            task_urgency = "high"
        affect_payload = workspace_state.get(AFFECT_STATE_KEY) or workspace_state.get("affect_state")
        if isinstance(affect_payload, dict):
            affect_urgency = str(
                affect_payload.get("urgency_level") or affect_payload.get("urgencyLevel") or ""
            ).strip()
            if affect_urgency and normalize_task_urgency(affect_urgency) == "high":
                task_urgency = "high"
        # safe_activate runs before resolve_coach_turn persist; message-time high
        # urgency must still fail-close invent (same as tight budget).
        if message and normalize_task_urgency(task_urgency) != "high":
            memory_for_affect = memory if memory is not None else live_memory
            if memory_for_affect is not None:
                learner_state = (
                    getattr(snapshot, "learner_state", None) if snapshot is not None else None
                )
                if learner_state is None:
                    learner_state = LearnerState()
                turn_affect = runtime.affect_service.infer_state(
                    message=str(message or ""),
                    learner_state=learner_state,
                    memory_snapshot=memory_for_affect,
                )
                if (
                    turn_affect is not None
                    and normalize_task_urgency(turn_affect.urgency_level) == "high"
                ):
                    task_urgency = "high"
        if workspace_state.get("time_budget") and normalize_time_budget(
            workspace_state.get("time_budget")
        ) == "tight":
            time_budget = "tight"
        project_complexity = (
            str(getattr(adaptation, "project_complexity", "moderate") or "moderate")
            if adaptation is not None
            else "moderate"
        )
        if workspace_state.get("project_complexity") and normalize_project_complexity(
            workspace_state.get("project_complexity")
        ) == "complex":
            project_complexity = "complex"
        current_ability = str(
            workspace_state.get("current_ability")
            or workspace_state.get("currentAbility")
            or ""
        ).strip()
        user_preference = str(
            workspace_state.get("latest_user_feedback_kind")
            or workspace_state.get("latestUserFeedbackKind")
            or ""
        ).strip()
        if not user_preference:
            from ..pedagogy.context_pressure import preference_equivalent_from_strategy_bias

            user_preference = preference_equivalent_from_strategy_bias(
                challenge_level=(
                    str(getattr(adaptation, "challenge_level", "") or "")
                    if adaptation is not None
                    else ""
                ),
                hint_depth=(
                    str(getattr(adaptation, "hint_depth", "") or "")
                    if adaptation is not None
                    else ""
                ),
                next_step_bias=(
                    str(getattr(adaptation, "next_step_bias", "") or "")
                    if adaptation is not None
                    else ""
                ),
                feedback_next_step_bias=str(
                    workspace_state.get("feedback_next_step_bias")
                    or workspace_state.get("feedbackNextStepBias")
                    or ""
                ),
            )
        from ..pedagogy.evidence_controls import (
            analyze_learning_evidence,
            pedagogy_evidence_confidence,
        )

        outcomes: list[object] = []
        if live_memory is not None:
            outcomes = list(getattr(live_memory, "learning_outcomes", []) or [])
        elif memory is not None:
            outcomes = list(getattr(memory, "learning_outcomes", []) or [])
        evidence_signals = analyze_learning_evidence(outcomes)
        return pressure_adapts_without_inventing_live_objects(
            time_budget=time_budget,
            task_urgency=task_urgency,
            project_complexity=project_complexity,
            current_ability=current_ability,
            user_preference=user_preference,
            evidence_confidence=pedagogy_evidence_confidence(
                verified_success=bool(evidence_signals.verified_success),
                success_count=int(evidence_signals.success_count or 0),
                outcomes=outcomes,
            ),
            live_plan=live_plan,
            live_task=live_task,
            live_card=live_card,
        )

    def honest_suggested_actions_without_live_object(
        actions: list[dict[str, object]],
        *,
        workspace_id: str,
        response_language: str | None,
        snapshot: WorkbenchSnapshot | None = None,
        current_task: TaskSpec | None = None,
        current_plan: LearningPlan | None = None,
        current_evaluation: EvaluationReport | None = None,
        message: str | None = None,
        scenario: str = "general",
    ) -> list[dict[str, object]]:
        if not should_remap_task_intent_without_live_plan(
            workspace_id,
            message=message,
            snapshot=snapshot,
            current_task=current_task,
            current_plan=current_plan,
        ):
            return actions
        # Domain lanes keep their chips: on plan / idea / project scenarios the
        # lane itself is the honest context (plan generation is the documented
        # recovery path, and a task chip click re-enters /turn where the intent
        # remap stays fail-closed). On generic lanes (general / review /
        # remapped task lanes) no mint chip is honest without a live object.
        # Exception: a leftover plan recovered as not-live must never offer
        # mint chips on any lane — clicking one would resurrect or rebind the
        # leftover, which the recovery contract forbids.
        if scenario in {
            "plan",
            "idea_implementation",
            "project_adaptation",
            "project_idea",
            "project_sourcing",
        } and not recovered_overlay_without_live_object(workspace_id):
            return list(actions)
        mint_actions = {"plan", "task", "next_task"}
        kept = [
            item
            for item in actions
            if str(item.get("action") or "").strip() not in mint_actions
        ]
        if kept:
            return kept
        fallback_label = localized_text(
            "Continue from the recovered step",
            "从已恢复的这一步继续",
            response_language,
        )
        if closed_loop_return_blocks_task_mint(workspace_id):
            fallback_label = localized_text(
                "Stay with the live plan step. Do not mint a task or second plan.",
                "继续当前正式计划这一步，不要另造任务或第二份计划。",
                response_language,
            )
        elif not recovered_overlay_without_live_object(workspace_id):
            fallback_label = localized_text(
                "Stay with a smaller hint. Do not generate a plan, card, or task.",
                "先给更小的提示，不要生成计划、卡片或任务。",
                response_language,
            )
        return structured_suggested_actions(
            [
                {
                    "label": fallback_label,
                    "action": "hint",
                }
            ],
            response_language=response_language,
            scenario="general",
            focus_area=stateful_focus_area(
                current_task,
                current_plan,
                current_evaluation,
                snapshot=snapshot,
            ),
        )

    def select_active_training_card(workspace_id: str) -> ActiveCardSelectionResult:
        cards = runtime.memory_service.get_cards(workspace_id)
        live_id = runtime.memory_service.live_selected_training_card_id(workspace_id)
        response_language = workspace_response_language(workspace_id)
        zh = prefers_chinese(response_language)
        no_live_why = (
            "No live training card is selected yet."
            if not zh
            else "尚未选择有效的训练卡片。"
        )
        no_live_fallback = (
            "Generate a training card explicitly before continuing."
            if not zh
            else "请先显式生成一张训练卡片，再继续。"
        )
        no_live_next = (
            "Generate the next truthful training card."
            if not zh
            else "先生成下一张如实的训练卡片。"
        )
        current_card_why = (
            "This is the current training card."
            if not zh
            else "这是当前的训练卡片。"
        )
        blocker_fallback = (
            "Return to coach with the exact blocker and verification output."
            if not zh
            else "带着确切的阻塞点和验证输出回到 Coach。"
        )
        evidence_next = (
            "Update evidence and route the next training step."
            if not zh
            else "更新证据，然后路由下一个训练步骤。"
        )
        # Leftover stored cards / title / current_step must not invent selectedCardId.
        # Live only when recovered runtime still carries a matching card id.
        if not live_id:
            return ActiveCardSelectionResult(
                why_this_card=no_live_why,
                fallback_action=no_live_fallback,
                next_after_completion=no_live_next,
                candidate_count=len(cards),
                eligible_count=0,
            )
        live_card = next((card for card in cards if card.card_id == live_id), None)
        if live_card is None:
            return ActiveCardSelectionResult(
                why_this_card=no_live_why,
                fallback_action=no_live_fallback,
                next_after_completion=no_live_next,
                candidate_count=len(cards),
                eligible_count=0,
            )
        router_service = getattr(runtime, "card_router_service", None)
        if router_service is None:
            leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
            return ActiveCardSelectionResult(
                selected_card=live_card,
                selected_card_id=live_card.card_id,
                selection_score=100.0,
                why_this_card=live_training_why_this_card(
                    plan=leftover_plan,
                    runtime=leftover_runtime,
                    existing=leftover_runtime,
                    card_title=live_card.title,
                    why_now=live_card.why_now,
                    kind="current",
                )
                or current_card_why,
                fallback_action=blocker_fallback,
                next_after_completion=evidence_next,
                candidate_count=len(cards),
                eligible_count=1,
            )
        selection = router_service.select_active_card(
            cards,
            routing_learner_state(workspace_id),
            routing_plan_state(workspace_id),
            response_language=response_language,
        )
        # Router may prefer another leftover; keep live identity fail-closed.
        if selection.selected_card_id != live_id:
            leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
            return ActiveCardSelectionResult(
                selected_card=live_card,
                selected_card_id=live_card.card_id,
                selection_score=100.0,
                why_this_card=live_training_why_this_card(
                    plan=leftover_plan,
                    runtime=leftover_runtime,
                    existing=leftover_runtime,
                    card_title=live_card.title,
                    why_now=live_card.why_now,
                    kind="current",
                )
                or current_card_why,
                fallback_action=selection.fallback_action or blocker_fallback,
                next_after_completion=selection.next_after_completion or evidence_next,
                candidate_count=len(cards),
                eligible_count=1,
            )
        return selection

    def routing_changed(
        existing: ActiveCardSelectionResult | None,
        selection: ActiveCardSelectionResult,
    ) -> bool:
        if existing is None:
            return True
        return existing.model_dump(mode="json") != selection.model_dump(mode="json")

    def sync_active_training_card(workspace_id: str) -> ActiveCardSelectionResult:
        selection = select_active_training_card(workspace_id)
        existing = runtime.memory_service.snapshot(workspace_id).active_training_card_routing
        if routing_changed(existing, selection):
            selection = runtime.memory_service.persist_active_card_selection(workspace_id, selection)
            refresh_workspace_sessions(workspace_id)
        return selection

    def default_profile() -> UserProfile:
        return UserProfile(
            long_term_goal="Build stronger implementation habits",
            long_term_goals=["Build stronger implementation habits"],
            weekly_hours=4,
            teaching_style="auto",
            answer_policy="auto",
            preferred_libraries=[],
        )

    def resolved_profile(workspace_id: str) -> UserProfile:
        return runtime.repository.get_profile(workspace_id) or default_profile()

    def build_coaching_service(payload: dict) -> ProviderService:
        override_config = provider_config_from_payload(payload)
        api_key_override = provider_api_key_from_payload(payload)
        workspace_id = str(payload.get("workspace_id") or payload.get("workspaceId") or "").strip()
        last_test = payload.get("last_test_result") or payload.get("lastTestResult")
        last_test_payload = last_test if isinstance(last_test, dict) else None
        if override_config is not None or api_key_override is not None:
            service = runtime.provider_service_for(override_config, api_key_override)
            runtime.rehydrate_last_test(
                override_config or getattr(service, "_config", None),
                api_key_override if api_key_override is not None else getattr(service, "_api_key", None),
                last_test=last_test_payload,
                workspace_id=workspace_id,
            )
            return runtime.overlay_last_test_on_service(service)
        runtime.rehydrate_last_test(
            getattr(runtime.provider_service, "_config", None),
            getattr(runtime.provider_service, "_api_key", None),
            last_test=last_test_payload,
            workspace_id=workspace_id,
        )
        return runtime.overlay_last_test_on_service(runtime.provider_service)

    def normalize_answer_mode(value: str | None) -> str:
        if value == "auto":
            return "guided"
        if value == "coach-first":
            return "guided"
        if value in {"guided", "balanced", "direct"}:
            return value
        return "guided"

    def answer_mode_preference_for_persistence(
        raw_requested: str | None,
        saved_preference: str | None,
        effective_mode: str | None,
        fallback_mode: str | None,
    ) -> str | None:
        requested = str(raw_requested or "").strip()
        if requested:
            return requested
        if str(saved_preference or "").strip() == "auto":
            return "auto"
        return effective_mode or fallback_mode

    def normalize_teaching_style(value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"guided", "concept-first", "hands-on", "challenging"}:
            return normalized
        if normalized == "auto":
            return "guided"
        return "guided"

    def message_requests_direct_answer(message: str | None) -> bool:
        lowered = str(message or "").strip().lower()
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "just show me",
                "show me the fix",
                "give me the fix",
                "show me the code",
                "give me the code",
                "full code",
                "complete code",
                "just tell me the answer",
                "直接给我",
                "直接告诉我",
                "直接给答案",
                "给我完整代码",
                "完整代码",
                "直接修",
            )
        )

    def message_requests_concept_first(message: str | None) -> bool:
        lowered = str(message or "").strip().lower()
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "why does",
                "how does",
                "explain",
                "mechanism",
                "principle",
                "concept",
                "difference",
                "what is the idea",
                "原理",
                "机制",
                "解释",
                "概念",
                "区别",
                "为什么",
                "先讲",
            )
        )

    def message_requests_hands_on_style(message: str | None) -> bool:
        lowered = str(message or "").strip().lower()
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "implement with me",
                "build with me",
                "code with me",
                "walk me through the code",
                "pair on this",
                "hands-on",
                "带我实现",
                "边做边学",
                "一起写",
                "带我改",
                "跟我改",
                "实操",
                "动手",
            )
        )

    def message_requests_challenging_style(message: str | None) -> bool:
        lowered = str(message or "").strip().lower()
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "challenge me",
                "quiz me",
                "test me",
                "let me try first",
                "don't tell me yet",
                "hold back the answer",
                "让我先试",
                "先别告诉我",
                "先不要告诉我",
                "考考我",
                "挑战我",
                "先让我想",
            )
        )

    def message_requests_guided_coaching(message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "guide me",
                "keep guiding",
                "continue guiding",
                "coach me",
                "teach me",
                "walk me through",
                "help me learn",
                "practice with me",
                "带我",
                "引导我",
                "继续引导",
                "教我",
                "一步一步",
                "陪我练",
                "带我练",
                "给我训练题",
            )
        )

    def message_requests_explicit_explanation_or_example(message: str | None) -> bool:
        """Give a concise answer unless the learner explicitly asks to withhold it."""
        lowered = str(message or "").strip().lower()
        if not lowered or message_requests_challenging_style(message):
            return False
        example_markers = (
            "example",
            "worked example",
            "show an example",
            "give an example",
            "示例",
            "举例",
            "例子",
        )
        return message_requests_concept_first(message) or any(
            marker in lowered for marker in example_markers
        )

    def current_file_diagnostics_count(current_file: dict[str, object] | None) -> int:
        if not isinstance(current_file, dict):
            return 0
        diagnostics = current_file.get("diagnostics")
        if isinstance(diagnostics, list):
            return len(diagnostics)
        for key in ("diagnostic_errors", "diagnosticErrors"):
            value = current_file.get(key)
            if isinstance(value, int) and value > 0:
                return value
        return 0

    def resolve_auto_answer_mode(
        *,
        message: str | None,
        current_file: dict[str, object] | None,
        coach_context: dict[str, object] | None = None,
    ) -> str:
        normalized_message = str(message or "")
        normalized_current_file = current_file if isinstance(current_file, dict) else None
        normalized_context = coach_context if isinstance(coach_context, dict) else None

        if message_requests_direct_answer(normalized_message):
            return "direct"

        learner_signal = infer_message_learner_signal(
            normalized_message,
            normalized_current_file,
            normalized_context,
        )
        if learner_signal == "blocked":
            return "direct"

        scenario = infer_message_coaching_scenario(
            normalized_message,
            normalized_current_file,
            normalized_context,
            default="idea_implementation",
        )
        if message_requests_implicit_learn_first_training(
            normalized_message,
            requested_scenario=scenario,
        ):
            return "guided"
        if message_requests_guided_coaching(normalized_message) or message_requests_challenging_style(
            normalized_message
        ):
            return "guided"
        if message_requests_hands_on_style(normalized_message):
            return "balanced"
        return "direct"

    def resolve_auto_teaching_style(
        *,
        message: str | None,
        current_file: dict[str, object] | None,
        coach_context: dict[str, object] | None = None,
    ) -> str:
        normalized_message = str(message or "")
        normalized_current_file = current_file if isinstance(current_file, dict) else None
        normalized_context = coach_context if isinstance(coach_context, dict) else None

        if message_requests_direct_answer(normalized_message):
            return "hands-on"
        if message_requests_hands_on_style(normalized_message):
            return "hands-on"
        if message_requests_concept_first(normalized_message):
            return "concept-first"

        learner_signal = infer_message_learner_signal(
            normalized_message,
            normalized_current_file,
            normalized_context,
        )
        if learner_signal == "blocked":
            return "hands-on"

        scenario = infer_message_coaching_scenario(
            normalized_message,
            normalized_current_file,
            normalized_context,
            default="idea_implementation",
        )
        if scenario in {"remote_workspace", "debug_loop"}:
            return "hands-on"
        if scenario in {"function_guidance", "principle"}:
            return "concept-first"
        if current_file_diagnostics_count(normalized_current_file) > 0:
            return "hands-on"
        if message_requests_challenging_style(normalized_message) and learner_signal == "steady":
            return "challenging"
        return "guided"

    def preferred_answer_mode(
        workspace_id: str,
        requested: str | None,
        profile: UserProfile | None,
    ) -> str | None:
        if requested and requested.strip():
            return requested.strip()
        workspace = workspace_preferences(workspace_id)
        saved = workspace.get("answer_mode")
        if isinstance(saved, str) and saved.strip():
            return saved.strip()
        return profile.answer_policy if profile else None

    def preferred_teaching_style(
        requested: str | None,
        profile: UserProfile | None,
    ) -> str | None:
        if requested and requested.strip():
            return requested.strip()
        return profile.teaching_style if profile else None

    def workspace_preferences(workspace_id: str) -> dict[str, object]:
        snapshot = runtime.memory_service.snapshot(workspace_id)
        return snapshot.workspace if isinstance(snapshot.workspace, dict) else {}

    def persist_requested_response_language(
        workspace_id: str,
        requested: str | None,
    ) -> ResponseLanguage | None:
        response_language = supported_response_language(requested)
        if response_language is not None:
            runtime.memory_service.update_workspace_state(
                workspace_id,
                response_language=response_language,
            )
        return response_language

    def effective_response_language(
        workspace_id: str,
        requested: str | None,
        message: str | None = None,
    ) -> ResponseLanguage | None:
        requested_language = supported_response_language(requested)
        if requested_language is not None:
            return requested_language
        workspace = workspace_preferences(workspace_id)
        saved_language = supported_response_language(workspace.get("response_language"))
        if saved_language is not None:
            return saved_language
        if isinstance(message, str) and any("\u3400" <= char <= "\u9fff" for char in message):
            return "zh-CN"
        return None

    def effective_answer_mode(
        workspace_id: str,
        requested: str | None,
        profile: UserProfile | None,
        *,
        message: str | None = None,
        current_file: dict[str, object] | None = None,
        coach_context: dict[str, object] | None = None,
    ) -> str:
        requested_mode = str(requested or "").strip().lower()
        if (
            message_requests_explicit_explanation_or_example(message)
            and requested_mode != "coach-first"
        ):
            return "direct"
        preferred_mode = preferred_answer_mode(workspace_id, requested, profile)
        normalized_preference = str(preferred_mode or "").strip()
        if normalized_preference == "auto":
            return resolve_auto_answer_mode(
                message=message,
                current_file=current_file,
                coach_context=coach_context,
            )
        return normalize_answer_mode(normalized_preference or None)

    def effective_teaching_style(
        requested: str | None,
        profile: UserProfile | None,
        *,
        message: str | None = None,
        current_file: dict[str, object] | None = None,
        coach_context: dict[str, object] | None = None,
    ) -> str:
        preferred_style = preferred_teaching_style(requested, profile)
        normalized_preference = str(preferred_style or "").strip()
        if normalized_preference == "auto":
            return resolve_auto_teaching_style(
                message=message,
                current_file=current_file,
                coach_context=coach_context,
            )
        return normalize_teaching_style(normalized_preference or None)

    def profile_with_teaching_style(
        profile: UserProfile,
        teaching_style: str | None,
    ) -> UserProfile:
        normalized_style = str(teaching_style or "").strip().lower()
        if not normalized_style:
            return profile
        if str(profile.teaching_style or "").strip().lower() == normalized_style:
            return profile
        return profile.model_copy(update={"teaching_style": normalized_style})

    def effective_coach_defaults(
        workspace_id: str,
        requested: CoachDefaults | None,
    ) -> CoachDefaults | None:
        if requested is not None:
            return requested
        workspace = workspace_preferences(workspace_id)
        saved = workspace.get("coach_defaults")
        if isinstance(saved, CoachDefaults):
            return saved
        if isinstance(saved, dict):
            try:
                return CoachDefaults.model_validate(saved)
            except Exception:
                return None
        return None



    def request_with_workspace_defaults(
        request: TurnRequest | SessionMessageRequest,
        *,
        workspace_id: str,
        profile: UserProfile | None,
    ) -> TurnRequest | SessionMessageRequest:
        response_language = effective_response_language(workspace_id, request.response_language, request.message)
        request_current_file = (
            jsonable_encoder(request.current_file) if getattr(request, "current_file", None) is not None else None
        )
        answer_mode = effective_answer_mode(
            workspace_id,
            request.answer_mode,
            profile,
            message=request.message,
            current_file=request_current_file if isinstance(request_current_file, dict) else None,
        )
        teaching_style = effective_teaching_style(
            request.teaching_style,
            profile,
            message=request.message,
            current_file=request_current_file if isinstance(request_current_file, dict) else None,
        )
        coach_defaults = effective_coach_defaults(workspace_id, request.coach_defaults)
        update = {
            "response_language": response_language,
            "answer_mode": answer_mode,
            "teaching_style": teaching_style,
            "coach_defaults": coach_defaults,
        }
        if isinstance(request, TurnRequest) and request.intent == "plan":
            frozen_blocks = leftover_frozen_blocks_turn_generation(workspace_id)
            if not request.formal_plan_mutation or frozen_blocks:
                update["intent"] = "coach"
                # Discussion / frozen plan turns must not silently keep formalPlanMutation.
                update["formal_plan_mutation"] = False
            # Explicit plan generate/save keeps formal_plan_mutation even under high urgency
            # (same leftover pattern as /plan/generate and /training/generate-card).
        elif isinstance(request, TurnRequest):
            # Coaching / task / review / resources: never silent formalPlanMutation.
            if request.formal_plan_mutation:
                update["formal_plan_mutation"] = False
        elif getattr(request, "formal_plan_mutation", False):
            # /session/message has no plan intent - never formal mutate.
            update["formal_plan_mutation"] = False
        if isinstance(request, TurnRequest) and request.intent in {"next_task", "task"}:
            if should_remap_task_intent_without_live_plan(
                workspace_id,
                message=getattr(request, "message", None),
            ):
                update["intent"] = "coach"
        return request.model_copy(update=update)

    def frozen_plan_mutation_notice(response_language: str | None) -> str:
        messages = {
            "zh-CN": "这条计划已冻结。请先恢复为可编辑状态，再修改正式计划。",
            "en-US": "This plan is frozen. Resume it before changing the formal plan.",
            "es-ES": "Este plan está congelado. Reanúdalo antes de cambiar el plan principal.",
            "fr-FR": "Ce plan est gelé. Reprenez-le avant de modifier le plan principal.",
            "de-DE": "Dieser Plan ist eingefroren. Setzen Sie ihn fort, bevor Sie den Hauptplan ändern.",
            "ja-JP": "この計画は固定されています。正式な計画を変更する前に、再開してください。",
            "ko-KR": "이 계획은 고정되어 있습니다. 정식 계획을 바꾸기 전에 다시 시작하세요.",
            "pt-BR": "Este plano está congelado. Retome-o antes de alterar o plano principal.",
        }
        if response_language is None:
            return messages["en-US"]
        return messages.get(response_language, messages["en-US"])

    def normalize_current_file_payload(current_file: object | None) -> dict[str, object] | None:
        if current_file is None:
            return None
        if isinstance(current_file, dict):
            return current_file
        model_dump = getattr(current_file, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            return dumped if isinstance(dumped, dict) else None
        legacy_dict = getattr(current_file, "dict", None)
        if callable(legacy_dict):
            dumped = legacy_dict()
            return dumped if isinstance(dumped, dict) else None
        return None

    def current_file_fact_value(
        current_file: dict[str, object],
        snake_case: str,
        camel_case: str,
    ) -> object:
        value = current_file.get(snake_case)
        return value if value is not None else current_file.get(camel_case)

    def is_training_placeholder_or_uri(value: str) -> bool:
        lowered = value.casefold()
        if any(marker in value for marker in ("<", ">", "{{", "}}", "${")):
            return True
        if re.match(r"^[a-z][a-z0-9+.-]*://", value, flags=re.IGNORECASE):
            return True
        if re.match(r"^[a-z][a-z0-9+.-]*:", value, flags=re.IGNORECASE) and not re.match(
            r"^[a-z]:[\\/]", value, flags=re.IGNORECASE
        ):
            return True
        return any(token in lowered for token in ("[redacted", "placeholder", "live call site"))

    def normalize_training_path(value: object) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        if not raw or len(raw) > 480 or "\x00" in raw or is_training_placeholder_or_uri(raw):
            return ""
        normalized = posixpath.normpath(raw)
        if normalized in {"", ".", "/"} or normalized.startswith("../") or normalized == "..":
            return ""
        return normalized.rstrip("/")

    def is_absolute_training_path(value: str) -> bool:
        return value.startswith("/") or value.startswith("//") or bool(
            re.match(r"^[a-z]:/", value, flags=re.IGNORECASE)
        )

    def relative_training_file_path(value: object, workspace_root: object) -> str:
        path = normalize_training_path(value)
        if not path:
            return ""
        if not is_absolute_training_path(path):
            return path

        root = normalize_training_path(workspace_root)
        if not root or not is_absolute_training_path(root):
            return ""
        comparison_path = path.casefold() if re.match(r"^[a-z]:/", path, flags=re.IGNORECASE) else path
        comparison_root = root.casefold() if re.match(r"^[a-z]:/", root, flags=re.IGNORECASE) else root
        if comparison_path == comparison_root:
            return ""
        prefix = f"{comparison_root}/"
        if not comparison_path.startswith(prefix):
            return ""
        return path[len(root) + 1 :]

    def redact_training_fact_text(value: object, limit: int, *, collapse: bool = False) -> str:
        text = str(value or "").replace("\x00", "").strip()
        if not text:
            return ""
        text = text[: max(limit * 4, 1024)]
        text = re.sub(
            r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}",
            "Bearer [redacted]",
            text,
        )
        text = re.sub(
            r"(?i)(\b(?:api[_-]?key|access[_-]?token|auth(?:orization)?|password|"
            r"secret|client[_-]?secret|private[_-]?key)\b\s*(?:=|:)\s*)(?:['\"]?)[^\s,'\"`]+",
            r"\1[redacted]",
            text,
        )
        text = re.sub(
            r"(?i)\b(?:sk|rk|ghp|github_pat|xoxb|akia)[-_a-z0-9]{8,}\b",
            "[redacted token]",
            text,
        )
        text = re.sub(r"(?i)[a-z][a-z0-9+.-]*://[^\s'\"`]+", "[redacted URI]", text)
        text = re.sub(
            r"(?<![\w.-])(?:[a-z]:[\\/][^\s'\"`]+|/"
            r"(?:users|home|workspaces|tmp|var|etc|private|mnt)[^\s'\"`]*)",
            "[redacted path]",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"<[^>\n]{1,200}>", "[redacted placeholder]", text)
        text = re.sub(r"\{\{[^}\n]{1,200}\}\}", "[redacted placeholder]", text)
        if collapse:
            text = " ".join(text.split())
        return text[:limit].rstrip()

    def dependency_usage_evidence_from_current_file(
        *,
        path: str,
        content: str,
        content_excerpt: str,
        selection_text: str,
    ) -> list[DependencyUsageEvidence]:
        """Project import/call facts from the vetted current-file payload only."""

        if not path:
            return []
        source = "\n".join(
            part
            for part in (content, content_excerpt, selection_text)
            if part
        )
        if not source:
            return []

        evidence: list[DependencyUsageEvidence] = []
        seen: set[tuple[str, str]] = set()

        def append(kind: str, identifier: str) -> None:
            cleaned = identifier.strip()
            if not re.fullmatch(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", cleaned):
                return
            key = (kind, cleaned.casefold())
            if key in seen or len(evidence) >= 24:
                return
            seen.add(key)
            evidence.append(
                DependencyUsageEvidence(
                    filePath=path,
                    kind=kind,
                    identifier=cleaned,
                    summary=f"{kind} {cleaned}",
                )
            )

        def strip_comments_and_strings(line: str) -> str:
            result: list[str] = []
            quote = ""
            escaped = False
            index = 0
            while index < len(line):
                character = line[index]
                if quote:
                    if escaped:
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == quote:
                        quote = ""
                    result.append(" ")
                    index += 1
                    continue
                if character in {"'", '"', "`"}:
                    quote = character
                    result.append(" ")
                    index += 1
                    continue
                if character == "#" or line[index : index + 2] == "//":
                    break
                result.append(character)
                index += 1
            return "".join(result)

        call_keywords = {"if", "for", "while", "switch", "catch", "return", "new"}
        for line in source.splitlines():
            stripped = line.lstrip()
            if stripped.startswith(("//", "#")):
                continue
            python_from = re.match(
                r"from\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s+import\b",
                stripped,
            )
            python_import = re.match(
                r"import\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\b",
                stripped,
            )
            javascript_import = re.match(
                r"import\b.*?\bfrom\s+[\"']([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)[\"']",
                stripped,
            )
            commonjs_require = re.match(
                r"(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*require\(\s*"
                r"[\"']([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)[\"']\s*\)\s*;?\s*$",
                stripped,
            )
            for match in (python_from, python_import, javascript_import, commonjs_require):
                if match is not None:
                    append("import", match.group(1))

            code_line = strip_comments_and_strings(line)
            if re.match(r"(?:export\s+)?(?:async\s+)?(?:function|def|class)\b", code_line.lstrip()):
                continue
            for match in re.finditer(
                r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(",
                code_line,
            ):
                identifier = match.group(1)
                if identifier.casefold() not in call_keywords:
                    append("call", identifier)
        return evidence

    def safe_remote_workspace_name(value: object) -> str:
        raw = str(value or "").strip()
        if not raw or is_training_placeholder_or_uri(raw):
            return ""
        cleaned = redact_training_fact_text(raw, 120, collapse=True)
        if "[redacted" in cleaned or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+@-]{0,119}", cleaned):
            return ""
        return cleaned

    def training_card_guided_scenario(request: CardGenerationRequest) -> str:
        current_file = normalize_current_file_payload(request.current_file) or {}
        scenario_current_file = {
            "path": current_file_fact_value(current_file, "path", "path"),
            "language_id": current_file_fact_value(current_file, "language_id", "languageId"),
            "content": current_file_fact_value(current_file, "content", "content"),
            "content_excerpt": current_file_fact_value(
                current_file, "content_excerpt", "contentExcerpt"
            ),
            "selection_text": current_file_fact_value(
                current_file, "selection_text", "selectionText"
            ),
            "diagnostics": current_file_fact_value(current_file, "diagnostics", "diagnostics"),
        }
        scenario_text = "\n".join(
            value
            for value in (
                str(request.focus_area or "").strip(),
                str(request.target_skill or "").strip(),
                str(request.context_hint or "").strip(),
                str(request.why_now or "").strip(),
            )
            if value
        )
        scenario = infer_message_coaching_scenario(
            scenario_text,
            scenario_current_file,
            default="general",
        )
        return scenario if scenario in {"remote_workspace", "debug_loop", "function_guidance"} else "general"

    def trusted_training_card_request_from_api(request: CardGenerationRequest) -> CardGenerationRequest:
        """Replace client-supplied card anchors with facts derived by this process."""

        return request.model_copy(
            update={
                # Nested IDE input is consumed into vetted fields below; never carry raw input onward.
                "current_file": None,
                "resource_knowledge_evidence": None,
                "plan_stage_id": "",
                **guided_training_workspace_facts(
                    workspace_id=request.workspace_id,
                    scenario=training_card_guided_scenario(request),
                    current_file=request.current_file,
                ),
            }
        )

    def guided_training_workspace_facts(
        *,
        workspace_id: str,
        scenario: str,
        current_file: object | None,
    ) -> dict[str, object]:
        """Build minimal card anchors from the active workspace and IDE-file payload."""

        current_file_payload = normalize_current_file_payload(current_file) or {}
        raw_workspace_root = runtime.resolve_workspace_path(workspace_id)
        workspace_root = normalize_training_path(raw_workspace_root)
        has_workspace_root = bool(workspace_root and is_absolute_training_path(workspace_root))
        canonical_current_file = {
            "path": current_file_fact_value(current_file_payload, "path", "path"),
            "language_id": current_file_fact_value(current_file_payload, "language_id", "languageId"),
            "content": current_file_fact_value(current_file_payload, "content", "content"),
            "content_excerpt": current_file_fact_value(
                current_file_payload, "content_excerpt", "contentExcerpt"
            ),
            "selection_text": current_file_fact_value(
                current_file_payload, "selection_text", "selectionText"
            ),
            "selection_range": current_file_fact_value(
                current_file_payload, "selection_range", "selectionRange"
            ),
            "diagnostics": current_file_fact_value(current_file_payload, "diagnostics", "diagnostics"),
        }
        include_current_file = scenario != "function_guidance" or is_code_like_current_file(
            canonical_current_file
        )

        path = ""
        language_id = ""
        content = ""
        content_excerpt = ""
        selection_text = ""
        selection_range = ""
        diagnostics: list[str] = []
        trusted_current_file_path = False
        if include_current_file:
            raw_current_file_path = normalize_training_path(canonical_current_file["path"])
            path = relative_training_file_path(raw_current_file_path, workspace_root)
            if has_workspace_root and is_absolute_training_path(raw_current_file_path) and path:
                try:
                    resolved_current_file = Path(raw_current_file_path).resolve()
                    resolved_workspace_root = Path(workspace_root).resolve()
                    trusted_current_file_path = (
                        resolved_current_file.is_file()
                        and resolved_current_file.is_relative_to(resolved_workspace_root)
                    )
                except OSError:
                    trusted_current_file_path = False
            language_candidate = str(canonical_current_file["language_id"] or "").strip()
            if re.fullmatch(r"[A-Za-z0-9+_.-]{1,120}", language_candidate):
                language_id = language_candidate
            if path:
                content = redact_training_fact_text(canonical_current_file["content"], 12000)
                content_excerpt = redact_training_fact_text(
                    canonical_current_file["content_excerpt"], 4000
                )
                selection_text = redact_training_fact_text(
                    canonical_current_file["selection_text"], 4000
                )
                selection_range_candidate = str(
                    canonical_current_file["selection_range"] or ""
                ).strip()
                if re.fullmatch(r"\d+:\d+-\d+:\d+", selection_range_candidate):
                    selection_range = selection_range_candidate
            raw_diagnostics = canonical_current_file["diagnostics"]
            if isinstance(raw_diagnostics, list):
                diagnostics = [
                    redact_training_fact_text(item, 360, collapse=True)
                    for item in raw_diagnostics[:8]
                    if redact_training_fact_text(item, 360, collapse=True)
                ]
            if not path:
                diagnostics = []

        workspace_memory = runtime.memory_service.snapshot(workspace_id).workspace
        workspace_memory = workspace_memory if isinstance(workspace_memory, dict) else {}
        remote_name = safe_remote_workspace_name(workspace_memory.get("remote_name"))
        workspace_boundary = "workspace root" if has_workspace_root else ""
        remote_facts: list[str] = []
        if remote_name:
            remote_facts.append(f"remote identity: {remote_name}")
        if workspace_boundary:
            remote_facts.append(f"workspace boundary: {workspace_boundary}")
        if path:
            remote_facts.append(f"current file: {path}")

        dependency_usage_evidence = (
            dependency_usage_evidence_from_current_file(
                path=path,
                content=content,
                content_excerpt=content_excerpt,
                selection_text=selection_text,
            )
            if trusted_current_file_path
            else []
        )

        return {
            "current_file_path": path,
            "current_file_language_id": language_id,
            "current_file_content": content,
            "current_file_excerpt": content_excerpt,
            "current_file_selection": selection_text,
            "current_file_selection_range": selection_range,
            "current_file_diagnostics": diagnostics,
            "dependency_usage_evidence": dependency_usage_evidence,
            "workspace_root_path": workspace_boundary,
            "remote_workspace_name": remote_name,
            "remote_workspace_facts": remote_facts,
        }

    def infer_learner_signal(
        message: str,
        current_file: dict[str, object] | None = None,
    ) -> str:
        return infer_message_learner_signal(message, normalize_current_file_payload(current_file))

    def message_requests_project_sourcing(message: str | None) -> bool:
        lowered = " ".join(str(message or "").casefold().split())
        return any(
            marker in lowered
            for marker in (
                "public project source",
                "source project",
                "reference repo",
                "reference repository",
                "reference project",
                "training repo",
                "training repository",
                "find a repo",
                "\u516c\u5f00\u9879\u76ee",
                "\u627e\u9879\u76ee",
                "\u627e\u4ee3\u7801\u5e93",
                "\u627e\u53c2\u8003\u5b9e\u73b0",
                "\u9002\u5408\u8bad\u7ec3\u7684\u9879\u76ee",
            )
        )

    def infer_coaching_scenario(
        request: TurnRequest | SessionMessageRequest,
        *,
        current_task: TaskSpec | None = None,
        evaluation_summary: str | None = None,
    ) -> str:
        if isinstance(request, TurnRequest):
            if request.intent == "review":
                return "review"
            if request.intent == "plan":
                return "plan"
            if request.intent == "task":
                return "task"
            if request.intent == "next_task":
                return "next_task"

        if evaluation_summary:
            return "review"
        if message_requests_project_sourcing(request.message):
            return "project_sourcing"
        current_file = normalize_current_file_payload(getattr(request, "current_file", None))
        inferred = infer_message_coaching_scenario(
            request.message,
            current_file,
            default="general",
        )
        if current_task is not None:
            return "idea_implementation"
        return inferred

    def trusted_resource_knowledge_evidence(
        workspace_id: str,
        resource: ResourceRecord,
    ) -> ResourceKnowledgeEvidence | None:
        """Return one redacted indexed fragment for a resource-training card."""

        if resource.index_status != "indexed" or resource_trust_state(resource) != "trusted":
            return None
        requested_context = runtime.resource_service.build_requested_resource_context(
            workspace_id,
            [resource.id],
            max_items=1,
            summary_chars=220,
        )
        fragments = requested_context.get("resource_fragments")
        if not isinstance(fragments, list):
            return None
        for fragment in fragments:
            if not isinstance(fragment, dict):
                continue
            if str(fragment.get("resource_id") or "").strip() != resource.id:
                continue
            fragment_id = redact_training_fact_text(fragment.get("id"), 160, collapse=True)
            focus_area = redact_training_fact_text(fragment.get("focus_area"), 240, collapse=True)
            summary = ""
            for key in ("evidence_summary", "summary", "snippet"):
                summary = redact_training_fact_text(fragment.get(key), 240, collapse=True)
                if summary:
                    break
            raw_source_type = str(fragment.get("source_type") or resource.kind).strip().lower()
            source_type = (
                raw_source_type
                if re.fullmatch(r"[a-z0-9][a-z0-9._:+-]{0,119}", raw_source_type)
                else resource.kind
            )
            if fragment_id and focus_area and summary:
                return ResourceKnowledgeEvidence(
                    resourceId=resource.id,
                    fragmentId=fragment_id,
                    sourceType=source_type,
                    focusArea=focus_area,
                    summary=summary,
                )
        return None

    def eligible_resource_training_record(
        request: CardGenerationRequest,
    ) -> ResourceRecord | None:
        if request.source != "resource_knowledge":
            return None

        response_language = request.response_language
        try:
            provisioning = runtime.get_project_provisioning(request.workspace_id)
        except ProjectProvisioningIntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "This project needs to be reconnected to Trainer before creating review cards from resources.",
                    "这个项目需要先重新连接到 Trainer，才能用资料生成复习卡。",
                    response_language,
                ),
            ) from exc
        if provisioning is None:
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "Add this project to Trainer before creating review cards from resources.",
                    "请先把这个项目加入 Trainer，再用资料生成复习卡。",
                    response_language,
                ),
            )

        resource_id = request.resource_id.strip()
        resource = runtime.repository.get_resource(request.workspace_id, resource_id) if resource_id else None
        if resource is None:
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "This resource is no longer available. Refresh Resources and try again.",
                    "找不到这份资料。刷新资料页后再试一次。",
                    response_language,
                ),
            )

        if resource.parse_status != "parsed" or resource.index_status != "indexed":
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "This resource is still being prepared. Finish organizing and indexing it first.",
                    "这份资料还在整理中。完成整理和索引后就能生成复习卡。",
                    response_language,
                ),
            )
        if resource.freshness != "fresh":
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "Update this resource before creating a review card.",
                    "这份资料需要先更新，再生成复习卡。",
                    response_language,
                ),
            )

        quality_flags = {str(flag or "").strip().lower() for flag in resource.quality_flags}
        blocking_flags = {
            "network_disabled",
            "fetch_failed",
            "blocked_source",
            "no_content",
            "source_conflict",
        }
        if (
            resource.trust_score < 0.75
            or resource_trust_state(resource) != "trusted"
            or bool(blocking_flags & quality_flags)
        ):
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "Review this resource before creating a review card from it.",
                    "这份资料还需要确认内容后，才能生成复习卡。",
                    response_language,
                ),
            )
        if trusted_resource_knowledge_evidence(request.workspace_id, resource) is None:
            raise HTTPException(
                status_code=409,
                detail=localized_text(
                    "Trainer could not find usable knowledge in this resource yet. Finish indexing it and try again.",
                    "Trainer 还没有在这份资料里找到可用内容。完成索引后再试一次。",
                    response_language,
                ),
            )
        return resource

    def prepare_training_card_request(request: CardGenerationRequest) -> CardGenerationRequest:
        """Apply the same redaction, locale, and resource trust projection to both routes."""
        request_payload = request.model_copy(deep=True)
        request_payload = request_payload.model_copy(
            update={"plan_binding": current_training_plan_binding(request_payload)}
        )
        if request_payload.plan_binding is not None:
            request_payload = request_payload.model_copy(
                update={
                    "plan_stage_id": request_payload.plan_binding.stage_id,
                    "source": "plan_requirement" if request_payload.source == "formal_plan_step"
                    else request_payload.source,
                }
            )
        request_payload = request_payload.model_copy(
            update={
                "focus_area": redact_training_fact_text(request_payload.focus_area, 240, collapse=True),
                "target_skill": redact_training_fact_text(request_payload.target_skill, 240, collapse=True),
                "context_hint": redact_training_fact_text(request_payload.context_hint, 1200),
                "why_now": redact_training_fact_text(request_payload.why_now, 360, collapse=True),
            }
        )
        if not request_payload.response_language:
            memory_snapshot = runtime.memory_service.snapshot(request_payload.workspace_id)
            saved_language = memory_snapshot.workspace.get("response_language")
            resolved_language = (
                saved_language
                if isinstance(saved_language, str) and saved_language in SUPPORTED_RESPONSE_LANGUAGES
                else "en-US"
            )
            request_payload = request_payload.model_copy(update={"response_language": resolved_language})
        if request_payload.resource_id:
            request_payload = request_payload.model_copy(
                update={"resource_id": request_payload.resource_id.strip()}
            )
        mint_overlay = _workspace_training_mint_overlay(
            runtime,
            request_payload.workspace_id,
            request_payload,
        )
        request_payload = request_payload.model_copy(update=mint_overlay["anchors"])
        eligible_resource = eligible_resource_training_record(request_payload)
        if request_payload.resource_id:
            resource = eligible_resource or runtime.repository.get_resource(
                request_payload.workspace_id,
                request_payload.resource_id,
            )
            if resource is not None:
                resource_evidence = trusted_resource_knowledge_evidence(
                    request_payload.workspace_id,
                    resource,
                )
                request_payload = request_payload.model_copy(
                    update={
                        "resource_quality_flags": list(resource.quality_flags or []),
                        "resource_trust_score": float(resource.trust_score or 0.0),
                        "resource_trust_state": resource_trust_state(resource),
                        "resource_freshness": str(resource.freshness or "unknown"),
                        "resource_knowledge_evidence": resource_evidence,
                    }
                )
            else:
                request_payload = request_payload.model_copy(
                    update={
                        "resource_missing": True,
                        "resource_missing_reason": "Requested resource was not found in workspace memory.",
                        "resource_trust_state": "untrusted",
                    }
                )
        return _apply_pedagogy_controls_to_card_request(request_payload, runtime)

    def current_training_plan_binding(request: CardGenerationRequest) -> TrainingPlanBinding | None:
        plan, recovered = leftover_runtime_for_workspace(request.workspace_id)
        revision = runtime.repository.get_plan_revision(request.workspace_id, plan.id) if plan else 0
        try:
            return validated_mint_binding(
                request.plan_binding,
                source=request.source,
                plan=plan,
                runtime=recovered,
                revision=revision,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def existing_open_resource_training_card(
        request_payload: CardGenerationRequest,
    ) -> TrainingCardCandidateSnapshot | None:
        return next(
            (
                card
                for card in runtime.memory_service.get_cards(request_payload.workspace_id)
                if card.created_from == "resource"
                and card.resource_id == request_payload.resource_id
                and card.card_type == request_payload.card_type
                and card.status in {"candidate", "active", "needs_primer"}
            ),
            None,
        )

    def card_generation_service_for(
        provider_service: ProviderService | None,
    ) -> CardGenerationService:
        configured_service = getattr(runtime, "card_generation_service", None)
        if configured_service is None:
            raise HTTPException(status_code=503, detail="Card generation service is not configured.")
        if getattr(configured_service, "_provider", None) is provider_service:
            return configured_service
        return CardGenerationService(
            provider_service=provider_service,
            event_ledger=getattr(configured_service, "_event_ledger", None),
        )

    def training_generate_and_route_card(
        request: CardGenerationRequest,
        generated_card: TrainingCardCandidateSnapshot | None = None,
        provider_service_override: ProviderService | None = None,
    ) -> CardGenerationResponse:
        generator = card_generation_service_for(provider_service_override or runtime.provider_service)
        request_payload = prepare_training_card_request(request)

        def store_generated_card(
            generated_card: TrainingCardCandidateSnapshot | None = None,
        ) -> TrainingCardCandidateSnapshot:
            card = generated_card or generator.generate_card(request_payload.source, request_payload)
            card = card.model_copy(
                update={
                    "resource_id": request_payload.resource_id or card.resource_id,
                    "trust_state": request_payload.resource_trust_state or card.trust_state,
                    "difficulty": request_payload.difficulty or card.difficulty,
                }
            )
            mint_overlay = _workspace_training_mint_overlay(
                runtime,
                request_payload.workspace_id,
                request_payload,
            )
            card = apply_live_training_mint_to_card(
                card,
                anchors=mint_overlay["anchors"],
                leftover_labels=mint_overlay["leftover"],
                recovered_step=str(mint_overlay["recovered_step"] or ""),
            )
            # Recheck after the provider completes: a plan may change during generation.
            binding = current_training_plan_binding(request_payload)
            card = card.model_copy(update={
                "plan_binding": binding,
                "plan_links": [binding.stage_id] if binding else (
                    [request_payload.plan_stage_id] if request_payload.plan_stage_id else []
                ),
            })
            return runtime.memory_service.upsert_card(request_payload.workspace_id, card)

        def existing_open_resource_card() -> TrainingCardCandidateSnapshot | None:
            return existing_open_resource_training_card(request_payload)

        def route_stored_card(stored_card: TrainingCardCandidateSnapshot) -> CardGenerationResponse:
            leftover_plan, leftover_runtime = leftover_runtime_for_workspace(request_payload.workspace_id)
            active_card = stored_card
            if stored_card.card_type == "flash":
                topic = {str(value or "").strip().lower() for value in (stored_card.scenario_pack, stored_card.target_skill, stored_card.focus_area) if str(value or "").strip()}
                # Only an open practice card may remain the live handoff when
                # a flash card is minted.  Answered cards are intentionally
                # retained for review, but cannot transition back to active.
                active_card = next((card for card in runtime.memory_service.get_cards(request_payload.workspace_id) if card.card_type == "practice" and card.status in {"candidate", "active", "needs_primer"} and topic.intersection({str(value or "").strip().lower() for value in (card.scenario_pack, card.target_skill, card.focus_area) if str(value or "").strip()})), stored_card)
            # (same pattern as leftover /plan/generate). Do not let leftover pool
            # title-match replace the newly minted card.
            selection = runtime.memory_service.persist_active_card_selection(
                request_payload.workspace_id,
                ActiveCardSelectionResult(
                    selected_card=active_card,
                    selected_card_id=active_card.card_id,
                    selection_score=100.0,
                    why_this_card=live_training_why_this_card(
                        plan=leftover_plan,
                        runtime=leftover_runtime,
                        existing=leftover_runtime,
                        card_title=active_card.title,
                        why_now=active_card.why_now,
                        kind="next",
                    )
                    or "This is the next training card.",
                    fallback_action="Return to coach with the exact blocker and verification output.",
                    next_after_completion="Update evidence, then route the next card.",
                    candidate_count=len(runtime.memory_service.get_cards(request_payload.workspace_id)),
                    eligible_count=sum(1 for card in runtime.memory_service.get_cards(request_payload.workspace_id) if card.status not in {"implemented", "reviewed", "fed_back", "archived", "skipped"}),
                ),
            )
            persist_training_card_to_sandbox(
                request_payload.workspace_id,
                stored_card,
                mark_current=False,
            )
            persist_training_card_to_sandbox(
                request_payload.workspace_id,
                selection.selected_card or stored_card,
                mark_current=True,
            )
            refresh_workspace_sessions(request_payload.workspace_id)
            return CardGenerationResponse(
                card=stored_card,
                score=selection.selection_score,
                success=True,
                reason="",
                active_routing=selection,
            )

        if request_payload.source == "resource_knowledge" and request_payload.resource_id:
            with resource_training_card_lock(request_payload.workspace_id):
                try:
                    return route_stored_card(
                        existing_open_resource_card() or store_generated_card(generated_card)
                    )
                except (CardGenerationProviderFailure, HTTPException):
                    raise
                except Exception as exc:
                    # Explicit generate failure must not clobber leftover storage.
                    raise HTTPException(status_code=502, detail=str(exc)) from exc
        try:
            return route_stored_card(store_generated_card(generated_card))
        except (CardGenerationProviderFailure, HTTPException):
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def requested_training_card_type(message: str | None) -> Literal["practice", "flash"]:
        lowered = " ".join(str(message or "").strip().lower().split())
        direct_flash_tokens = (
            "flash card",
            "flashcard",
            "\u95ea\u5361",
            "\u95ea\u8bb0\u5361",
            "\u590d\u4e60\u5361",
        )
        if any(token in lowered for token in direct_flash_tokens):
            return "flash"

        practice_tokens = (
            "practice card",
            "learn-first",
            "hands-on",
            "primer",
            "before any test",
            "practice first",
            "do not test me first",
            "don't test me first",
            "before any quiz",
            "\u7ec3\u4e60\u5361",
            "\u5148\u5b66",
            "\u5148\u5b66\u4e60",
            "\u5148\u5b66\u518d\u7ec3\u4e60",
            "\u5148\u5b66\u540e\u7ec3",
            "\u5148\u8bb2\u518d\u7ec3",
            "\u4e0d\u8981\u5148\u8003\u8bd5",
            "\u4e0d\u8981\u5148\u6d4b\u8bd5",
        )
        if any(token in lowered for token in practice_tokens):
            return "practice"

        flash_cues = (
            "flash ",
            "recall card",
            "multiple choice",
            "quiz",
            "mcq",
        )
        if any(token in lowered for token in flash_cues):
            return "flash"
        return "practice"

    def validated_training_response_language(value: str | None) -> ResponseLanguage | None:
        return CardGenerationContext.model_validate({"response_language": value}).response_language

    def message_requests_general_learn_first_training(message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        learn_requested = any(
            token in lowered
            for token in (
                "learn first",
                "practice first",
                "teach me",
                "step by step",
                "before you test me",
                "before you quiz me",
                "first explain",
                "教我",
                "先教我",
                "先讲",
                "先学",
                "先学习",
                "先理解",
                "先讲解",
                "一步一步",
                "不要先考试",
                "不要先测试",
                "先学后练",
                "先学习再验证",
            )
        ) or bool(
            re.search(r"\blearn\b.{0,80}\bfirst\b", lowered)
            or re.search(r"\bunderstand\b.{0,80}\bfirst\b", lowered)
        )
        if not learn_requested:
            return False
        return any(
            token in lowered
            for token in (
                "tiny verified step",
                "small verified step",
                "tiny real step",
                "small real step",
                "tiny learning step",
                "small learning step",
                "small debug move",
                "smallest verifiable move",
                "tiny verified move",
                "tiny real move",
                "verifiable step",
                "verifiable move",
                "verifiable learning move",
                "verifiable value",
                "verify",
                "verified",
                "checkpoint",
                "validation step",
                "test my understanding",
                "before you test me",
                "before you quiz me",
                "再测试我",
                "再验证",
                "验证动作",
                "可验证",
                "很小的验证",
                "很小而且可验证",
                "很小的可验证",
                "很小的学习动作",
                "很小的训练动作",
            )
        )

    def message_requests_auto_training_handoff(message: str | None) -> bool:
        """Require an explicit learn-practice-verify loop before opening Training."""
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        learn_practice_markers = (
            "learn -> try -> verify",
            "learn, try, verify",
            "learn then practice",
            "learn then try",
            "learn first, then practice",
            "learn first, then try",
            "\u5148\u5b66\u518d\u7ec3",
            "\u5148\u5b66\u540e\u7ec3",
            "\u5148\u5b66\u518d\u5b9e\u8df5",
            "\u5148\u5b66\u540e\u5b9e\u8df5",
            "\u5148\u8bb2\u518d\u7ec3",
            "\u5148\u7406\u89e3\u518d\u7ec3",
        )
        verification_markers = (
            "verify",
            "verification",
            "test it",
            "check it",
            "\u9a8c\u6536",
            "\u9a8c\u8bc1",
            "\u68c0\u9a8c",
            "\u6d4b\u8bd5",
            "\u518d\u6d4b",
        )
        return any(marker in lowered for marker in learn_practice_markers) and any(
            marker in lowered for marker in verification_markers
        )

    def auto_answer_mode_allows_training_handoff(
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
    ) -> bool:
        for value in (
            requested_answer_mode,
            saved_answer_mode,
            profile.answer_policy if profile else None,
        ):
            normalized = str(value or "").strip().lower()
            if normalized:
                return normalized == "auto"
        return False

    def message_requests_implicit_learn_first_training(
        message: str | None,
        *,
        requested_scenario: str,
    ) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        if requested_scenario not in {
            "remote_workspace",
            "debug_loop",
            "function_guidance",
        }:
            return False
        if message_requests_general_learn_first_training(message):
            return True
        return False

    def message_requests_training_card_activation(
        message: str | None,
        *,
        requested_scenario: str,
    ) -> bool:
        del requested_scenario
        return message_requests_explicit_training_card(message)

    def auto_preference_requests_training_card(
        message: str | None,
        *,
        requested_scenario: str,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
    ) -> bool:
        del requested_scenario, requested_answer_mode, saved_answer_mode, profile
        return message_requests_explicit_training_card(message)

    def auto_lane_learn_first_force_training_card(
        message: str | None,
        *,
        requested_scenario: str,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
    ) -> bool:
        del requested_answer_mode, saved_answer_mode, profile
        return message_requests_implicit_learn_first_training(
            message,
            requested_scenario=requested_scenario,
        )

    def training_card_defaults_for_scenario(
        scenario: str,
        response_language: str | None,
    ) -> tuple[str, str]:
        localized_defaults = localized_training_defaults_for_scenario(
            scenario,
            response_language,
        )
        if localized_defaults is not None:
            return localized_defaults
        return (
            localized_text("current training focus", "当前训练重点", response_language),
            localized_text("learn-first practice", "先学习再练习", response_language),
        )

    GUIDED_SCENARIO_TRAINING_PACKS = {
        "remote_workspace",
        "debug_loop",
        "function_guidance",
    }

    def selected_training_card_scenario_pack(
        selection: ActiveCardSelectionResult | None,
    ) -> str:
        if selection is None or selection.selected_card is None:
            return ""
        return str(getattr(selection.selected_card, "scenario_pack", "") or "").strip()

    def active_training_card_satisfies_request(
        selection: ActiveCardSelectionResult | None,
        *,
        requested_scenario: str,
        message: str | None,
        force_training_card: bool,
    ) -> bool:
        if selection is None:
            return False
        if requested_scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return True
        if not force_training_card and not message_requests_training_card_activation(
            message,
            requested_scenario=requested_scenario,
        ):
            return True
        return selected_training_card_scenario_pack(selection) == requested_scenario

    def direct_guided_training_card_fallback(
        *,
        workspace_id: str,
        scenario: str,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        active_thread: object | None,
    ) -> bool:
        if scenario not in {"remote_workspace", "debug_loop", "function_guidance"}:
            return False

        current_file_payload = normalize_current_file_payload(current_file)
        current_file_name = function_guidance_current_file_name(
            current_file_payload,
            scenario=scenario,
        )

        default_focus, default_skill = training_card_defaults_for_scenario(
            scenario,
            response_language,
        )
        active_thread_scenario = active_thread_scenario_value(active_thread)
        focus_candidates: list[object] = []
        if active_thread is not None and active_thread_scenario in {"", scenario, "general"}:
            focus_candidates.append(getattr(active_thread, "focus_area", ""))
        focus_candidates.append(default_focus)
        focus_hint = resolve_focus_hint(
            user_message=message,
            candidates=focus_candidates,
            fallback_current_file=current_file_name or None,
        )
        if scenario == "function_guidance" and current_file_name and not focus_hint:
            focus_hint = current_file_name

        context_bits = [f"Coach request: {str(message or '').strip()}"]
        if current_file_name:
            context_bits.append(f"Current file: {current_file_name}")
        active_next_step = str(getattr(active_thread, "next_step", "") or "").strip() if active_thread else ""
        if active_next_step and active_thread_scenario in {"", scenario, "general"}:
            context_bits.append(f"Active thread: {active_next_step}")

        pedagogy_controls = _pedagogy_controls_for_workspace(runtime, workspace_id)
        context = CardGenerationContext(
            workspace_id=workspace_id,
            source="conversation_gap",
            card_type=requested_training_card_type(message),
            context_hint=" | ".join(bit for bit in context_bits if bit).strip()[:420],
            target_skill=default_skill,
            focus_area=focus_hint or default_focus,
            difficulty=pedagogy_controls.difficulty if pedagogy_controls is not None else "medium",
            hint_count=pedagogy_controls.hint_count if pedagogy_controls is not None else None,
            code_reveal=pedagogy_controls.code_reveal if pedagogy_controls is not None else "",
            practice_type=pedagogy_controls.practice_type if pedagogy_controls is not None else "",
            review_frequency=pedagogy_controls.review_frequency if pedagogy_controls is not None else "",
            material_recommendation=(
                pedagogy_controls.material_recommendation if pedagogy_controls is not None else ""
            ),
            next_plan_step=pedagogy_controls.next_plan_step if pedagogy_controls is not None else "",
            should_reveal_code=(
                pedagogy_controls.should_reveal_code if pedagogy_controls is not None else None
            ),
            pedagogy_mode=pedagogy_controls.pedagogy_mode if pedagogy_controls is not None else "",
            why_now=localized_text(
                "The learner asked Coach for one learn-first training move.",
                "\u5b66\u4e60\u8005\u8981\u6c42 Coach \u5148\u5b89\u6392\u4e00\u4e2a\u5148\u5b66\u540e\u7ec3\u7684\u8bad\u7ec3\u52a8\u4f5c\u3002",
                response_language,
            ),
            response_language=validated_training_response_language(response_language),
        )
        context = context.model_copy(
            update=guided_training_workspace_facts(
                workspace_id=workspace_id,
                scenario=scenario,
                current_file=current_file_payload,
            )
        )
        card = _make_guided_scenario_pack_card(
            scenario,
            context,
            requested_training_card_type(message),
            response_language or "en-US",
        )
        stored_card = runtime.memory_service.upsert_card(workspace_id, card)
        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        runtime.memory_service.persist_active_card_selection(
            workspace_id,
            ActiveCardSelectionResult(
                selected_card=stored_card,
                selected_card_id=stored_card.card_id,
                selection_score=100.0,
                why_this_card=live_training_why_this_card(
                    plan=leftover_plan,
                    runtime=leftover_runtime,
                    existing=leftover_runtime,
                    card_title=stored_card.title,
                    why_now=stored_card.why_now,
                    kind="next",
                )
                or "This is the next training card.",
                fallback_action=localized_text(
                    "Return to Coach with the exact blocker and verification output.",
                    "带着准确的 blocker 和验证输出来回到 Coach。",
                    response_language,
                ),
                next_after_completion=localized_text(
                    "Finish the card, update the evidence, then route the next card.",
                    "完成这张卡，更新证据，再决定下一张卡。",
                    response_language,
                ),
                candidate_count=1,
                eligible_count=1,
            ),
        )
        refresh_workspace_sessions(workspace_id)
        return True

    def guided_training_card_requested(
        *,
        scenario: str,
        message: str | None,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
        force_training_card: bool = False,
    ) -> bool:
        normalized_scenario = str(scenario or "").strip()
        if normalized_scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return False
        return force_training_card or message_requests_training_card_activation(
            message,
            requested_scenario=normalized_scenario,
        ) or auto_preference_requests_training_card(
            message,
            requested_scenario=normalized_scenario,
            requested_answer_mode=requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        ) or auto_lane_learn_first_force_training_card(
            message,
            requested_scenario=normalized_scenario,
            requested_answer_mode=requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        )

    def guarantee_guided_learn_first_training_card(
        *,
        workspace_id: str,
        scenario: str,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        active_thread: object | None,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
        force_training_card: bool = False,
    ) -> bool:
        # Composer chat stays hint-only for remote_workspace / debug_loop packs;
        # POST /training/generate-card remains the binder for those. Function
        # guidance is the exception: when the learner asks to learn from real
        # code but no code-like file is available, the honest move is a
        # needs_primer card naming the missing facts, not a fake scaffolded
        # call site written into the sandbox.
        if scenario != "function_guidance":
            return False
        if not provider_service_allows_object_minting():
            return False
        if pressure_without_live_object_blocks_mint(
            workspace_id,
            message=message,
        ) or streak_without_live_object_blocks_mint(workspace_id):
            return False
        if scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return False
        if message_requests_direct_answer(message) or message_requests_explicit_explanation_or_example(
            message
        ):
            return False
        if not guided_training_card_requested(
            scenario=scenario,
            message=message,
            requested_answer_mode=requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
            force_training_card=force_training_card,
        ):
            return False
        snapshot = runtime.memory_service.snapshot(workspace_id)
        if active_training_card_satisfies_request(
            snapshot.active_training_card_routing,
            requested_scenario=scenario,
            message=message,
            force_training_card=True,
        ):
            return False
        return direct_guided_training_card_fallback(
            workspace_id=workspace_id,
            scenario=scenario,
            message=message,
            current_file=current_file,
            response_language=response_language,
            active_thread=active_thread,
        )

    def should_bypass_agent_loop_for_guided_training(
        *,
        workspace_id: str,
        scenario: str,
        message: str | None,
        active_view: str | None = None,
        requested_answer_mode: str | None,
        saved_answer_mode: str | None,
        profile: UserProfile | None,
        force_training_card: bool = False,
    ) -> bool:
        # Training's Coach route is an explicit request for model-backed help.
        # The deterministic card handoff still creates/selects the card, but it
        # must not replace the learner's conversation with a local scaffold.
        if str(active_view or "").strip().lower() == "training":
            return False
        normalized_scenario = str(scenario or "").strip()
        if normalized_scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return False
        if message_requests_direct_answer(message) or message_requests_explicit_explanation_or_example(
            message
        ):
            return False
        visible_handoff_requested = force_training_card or auto_preference_requests_training_card(
            message,
            requested_scenario=normalized_scenario,
            requested_answer_mode=requested_answer_mode,
            saved_answer_mode=saved_answer_mode,
            profile=profile,
        )
        if not visible_handoff_requested:
            return False
        selection = runtime.memory_service.snapshot(workspace_id).active_training_card_routing
        return active_training_card_satisfies_request(
            selection,
            requested_scenario=normalized_scenario,
            message=message,
            force_training_card=True,
        )

    def build_guided_training_visible_fallback(
        *,
        workspace_id: str,
        response_language: str | None,
    ) -> dict[str, str] | None:
        selection = runtime.memory_service.snapshot(workspace_id).active_training_card_routing
        if selection is None or selection.selected_card is None:
            return None
        card = selection.selected_card
        if str(card.scenario_pack or "").strip() not in GUIDED_SCENARIO_TRAINING_PACKS:
            return None

        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        reason = live_training_why_this_card(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            card_title=card.title,
            why_now=str(selection.why_this_card or card.why_now or "").strip(),
            kind="current",
        )
        deliver = str(card.problem_statement or "").strip()
        if not deliver and card.learner_deliverables:
            deliver = "; ".join(
                str(item).strip() for item in card.learner_deliverables[:2] if str(item).strip()
            )
        verify = "; ".join(
            str(item).strip() for item in card.verification_steps[:2] if str(item).strip()
        )
        if not verify:
            verify = str(card.success_signal or card.validation_method or "").strip()
        return_with = str(card.return_with or selection.next_after_completion or "").strip()
        next_step = str(
            card.suggested_workspace_action
            or (card.verification_steps[0] if card.verification_steps else "")
            or selection.fallback_action
            or card.stuck_recovery
            or ""
        ).strip()
        primer_required = str(card.status or "").strip() == "needs_primer"
        open_copy = live_training_open_copy(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            card_title=str(card.title or "").strip(),
            next_step=next_step,
            primer_required=primer_required,
        )

        if prefers_chinese(response_language):
            lines = [
                "我先把这一轮收束成一张先学后练的训练卡，不先测试你。",
                "",
                open_copy["zh_current"],
            ]
            if reason:
                lines.append(f"- 为什么现在做：{reason}")
            if deliver:
                lines.append(f"- 你要完成：{deliver}")
            if verify:
                lines.append(f"- 这样验证：{verify}")
            if return_with:
                lines.append(f"- 完成后带回：{return_with}")
            lines.append("")
            if next_step:
                lines.append(f"先在 Training 做这一步：{next_step}")
            else:
                lines.append("先打开 Training，沿着这张卡继续。")
            lines.append(
                "先完成 primer，再进入验证。"
                if primer_required
                else "完成后把验证结果带回 Coach。"
            )
            summary = open_copy["zh_summary"]
            normalized_next_step = open_copy["zh_complete"]
            teaching_note = "训练默认闭环保持为 Learn -> Try -> Verify -> Reflect -> Return。"
        else:
            lines = [
                "I set up one learn-first training card before any quiz.",
                "",
                open_copy["en_current"],
            ]
            if reason:
                lines.append(f"- Why now: {reason}")
            if deliver:
                lines.append(f"- Deliver: {deliver}")
            if verify:
                lines.append(f"- Verify: {verify}")
            if return_with:
                lines.append(f"- Return with: {return_with}")
            lines.append("")
            if next_step:
                lines.append(f"Open Training and start with: {next_step}")
            else:
                lines.append("Open Training and continue with this card.")
            lines.append(
                "Finish the primer first, then move into verification."
                if primer_required
                else "Bring the verification result back to Coach when you finish."
            )
            summary = open_copy["en_summary"]
            normalized_next_step = open_copy["en_complete"]
            teaching_note = "Keep the training loop as Learn -> Try -> Verify -> Reflect -> Return."

        resume_thread = build_resume_thread_text(
            summary,
            normalized_next_step,
            response_language=response_language,
        )
        return {
            "reply": "\n".join(lines).strip(),
            "summary": summary,
            "next_step": normalized_next_step,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
        }

    def apply_guided_training_visible_fallback(
        *,
        coach_turn: dict[str, object],
        fallback: dict[str, str],
    ) -> tuple[str, dict[str, object], dict[str, object]]:
        repaired_coach_turn = merge_agent_finalize_into_coach_turn(
            coach_turn,
            summary=fallback["summary"],
            next_step=fallback["next_step"],
            blocker=None,
            resume_thread=fallback["resume_thread"],
            decision="training_handoff",
            teaching_note=fallback["teaching_note"],
            confidence=None,
            evidence=None,
        )
        agent_meta = {
            "stop_reason": "local_guided_training",
            "summary": fallback["summary"],
            "next_step": fallback["next_step"],
            "decision": "training_handoff",
            "blocker": None,
            "teaching_note": fallback["teaching_note"],
            "resume_thread": fallback["resume_thread"],
            "confidence": None,
            "evidence": None,
            "tool_events": [],
            "fell_back": False,
            "recovered_stop_reason": None,
            "agentic": False,
            "local_guided_training_fallback": True,
        }
        if repaired_coach_turn is None:
            repaired_coach_turn = coach_turn
        return fallback["reply"], repaired_coach_turn, agent_meta

    def maybe_activate_training_card_from_coach_request(
        *,
        workspace_id: str,
        snapshot: WorkbenchSnapshot,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        provider_service_override: ProviderService | None = None,
    ) -> CardGenerationResponse | None:
        # Composer chat (/turn, /turn/stream, /session/message) must not mint.
        # Explicit POST /training/generate-card binds a NEW card_id. Do not clobber
        # an already-live selected_card_id from chat either.
        return None
        current_file_payload = normalize_current_file_payload(current_file)
        active_thread = snapshot.memory.active_thread
        active_thread_scenario = active_thread_scenario_value(active_thread)
        requested_scenario = infer_message_coaching_scenario(
            str(message or ""),
            current_file_payload,
            default="general",
        )
        if (
            requested_scenario == "general"
            and message_requests_lane_continuation(message)
            and active_thread_scenario in {
                "remote_workspace",
                "debug_loop",
                "function_guidance",
            }
        ):
            requested_scenario = active_thread_scenario
        if not message_requests_training_card_activation(
            message,
            requested_scenario=requested_scenario,
        ):
            return None

        current_file_name = function_guidance_current_file_name(
            current_file_payload,
            scenario=requested_scenario,
        )

        default_focus, default_skill = training_card_defaults_for_scenario(
            requested_scenario,
            response_language,
        )
        focus_candidates: list[object] = []
        if active_thread is not None and active_thread_scenario in {"", requested_scenario, "general"}:
            focus_candidates.append(getattr(active_thread, "focus_area", ""))
        if requested_scenario == "general":
            focus_candidates.append(
                stateful_focus_area(
                    snapshot.current_task,
                    snapshot.plan,
                    snapshot.evaluation,
                    snapshot=snapshot,
                )
            )
        focus_candidates.append(default_focus)
        focus_hint = resolve_focus_hint(
            user_message=message,
            candidates=focus_candidates,
            fallback_current_file=current_file_name or None,
        )
        if requested_scenario == "function_guidance" and current_file_name and not focus_hint:
            focus_hint = current_file_name

        target_skill = default_skill if requested_scenario != "general" else (focus_hint or default_skill)
        context_bits = [f"Coach request: {str(message or '').strip()}"]
        if current_file_name:
            context_bits.append(f"Current file: {current_file_name}")
        active_next_step = str(getattr(active_thread, "next_step", "") or "").strip() if active_thread else ""
        if active_next_step and active_thread_scenario in {"", requested_scenario, "general"}:
            context_bits.append(f"Active thread: {active_next_step}")
        context_hint = " | ".join(bit for bit in context_bits if bit).strip()[:420]

        request_payload = CardGenerationRequest(
            workspace_id=workspace_id,
            source="conversation_gap",
            card_type=requested_training_card_type(message),
            focus_area=focus_hint or default_focus,
            target_skill=target_skill,
            context_hint=context_hint,
            why_now=localized_text(
                "The learner asked Coach for one learn-first training move.",
                "学习者请 Coach 提供一个先学习再练习的训练动作。",
                response_language,
            ),
            difficulty="medium",
            response_language=validated_training_response_language(response_language),
        )
        request_payload = request_payload.model_copy(
            update=guided_training_workspace_facts(
                workspace_id=workspace_id,
                scenario=requested_scenario,
                current_file=current_file_payload,
            )
        )
        return training_generate_and_route_card(
            request_payload,
            provider_service_override=provider_service_override,
        )

    def safe_activate_training_card_from_coach_request(
        *,
        workspace_id: str,
        snapshot: WorkbenchSnapshot,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        provider_service_override: ProviderService | None = None,
    ) -> CardGenerationResponse | None:
        # Composer chat must not mint (incl. guided fallback). HTTP generate-card may.
        return None
        if not provider_service_allows_object_minting(provider_service_override):
            return None
        if pressure_without_live_object_blocks_mint(
            workspace_id,
            snapshot=snapshot,
            current_task=snapshot.current_task,
            current_plan=snapshot.plan,
            message=message,
        ) or streak_without_live_object_blocks_mint(
            workspace_id,
            snapshot=snapshot,
            current_task=snapshot.current_task,
            current_plan=snapshot.plan,
        ):
            return None
        created: CardGenerationResponse | None = None
        try:
            created = maybe_activate_training_card_from_coach_request(
                workspace_id=workspace_id,
                snapshot=snapshot,
                message=message,
                current_file=current_file,
                response_language=response_language,
                provider_service_override=provider_service_override,
            )
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
        if created is not None:
            return created
        current_file_payload = normalize_current_file_payload(current_file)
        active_thread = snapshot.memory.active_thread
        active_thread_scenario = active_thread_scenario_value(active_thread)
        requested_scenario = infer_message_coaching_scenario(
            str(message or ""),
            current_file_payload,
            default="general",
        )
        if (
            requested_scenario == "general"
            and message_requests_lane_continuation(message)
            and active_thread_scenario in GUIDED_SCENARIO_TRAINING_PACKS
        ):
            requested_scenario = active_thread_scenario
        if requested_scenario not in GUIDED_SCENARIO_TRAINING_PACKS:
            return None
        if not message_requests_training_card_activation(
            message,
            requested_scenario=requested_scenario,
        ):
            return None
        if direct_guided_training_card_fallback(
            workspace_id=workspace_id,
            scenario=requested_scenario,
            message=message,
            current_file=current_file,
            response_language=response_language,
            active_thread=active_thread,
        ):
            selection = runtime.memory_service.snapshot(workspace_id).active_training_card_routing
            if selection is not None and selection.selected_card is not None:
                return CardGenerationResponse(
                    card=selection.selected_card,
                    score=selection.selection_score,
                    success=True,
                    reason="local_guided_fallback",
                    active_routing=selection,
                )
            fallback_context = CardGenerationContext(
                workspace_id=workspace_id,
                source="conversation_gap",
                card_type=requested_training_card_type(message),
                context_hint="",
                target_skill="guided fallback",
                focus_area="guided fallback",
                difficulty="medium",
                why_now="local_guided_fallback",
                response_language=validated_training_response_language(response_language),
            ).model_copy(
                update=guided_training_workspace_facts(
                    workspace_id=workspace_id,
                    scenario=requested_scenario,
                    current_file=current_file_payload,
                )
            )
            return CardGenerationResponse(
                card=_make_guided_scenario_pack_card(
                    requested_scenario,
                    fallback_context,
                    requested_training_card_type(message),
                    response_language or "en-US",
                ),
                score=100.0,
                success=True,
                reason="local_guided_fallback",
                active_routing=None,
            )
        return None

    def ensure_explicit_training_card_after_language_block(
        *,
        state: SessionState,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        fallback_scenario: str | None = None,
        force_training_card: bool = False,
        provider_service_override: ProviderService | None = None,
    ) -> None:
        # Composer chat must not mint or clobber. Keep live selected_card_id only.
        # Explicit POST /training/generate-card is the intentional mint path.
        live_id = runtime.memory_service.live_selected_training_card_id(state.workspace_id)
        if live_id:
            state.snapshot.memory = runtime.memory_service.snapshot(state.workspace_id)
        return
        if not provider_service_allows_object_minting(provider_service_override):
            return
        # Pressure/streak blocks invent on coach turns (including "create a card" in chat).
        # Explicit POST /training/generate-card is the intentional mint path.
        if pressure_without_live_object_blocks_mint(
            state.workspace_id,
            snapshot=state.snapshot,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
            message=message,
        ) or streak_without_live_object_blocks_mint(
            state.workspace_id,
            snapshot=state.snapshot,
            current_task=state.snapshot.current_task,
            current_plan=state.snapshot.plan,
        ):
            return
        snapshot = runtime.memory_service.snapshot(state.workspace_id)
        current_file_payload = normalize_current_file_payload(current_file)
        active_thread = state.snapshot.memory.active_thread
        active_thread_scenario = active_thread_scenario_value(active_thread)
        requested_scenario = infer_message_coaching_scenario(
            str(message or ""),
            current_file_payload,
            default="general",
        )
        normalized_fallback_scenario = str(fallback_scenario or "").strip()
        if (
            normalized_fallback_scenario in GUIDED_SCENARIO_TRAINING_PACKS
            and force_training_card
            and requested_scenario not in GUIDED_SCENARIO_TRAINING_PACKS
        ):
            requested_scenario = normalized_fallback_scenario
        if requested_scenario == "general" and normalized_fallback_scenario in GUIDED_SCENARIO_TRAINING_PACKS:
            requested_scenario = normalized_fallback_scenario
        if (
            requested_scenario == "general"
            and message_requests_lane_continuation(message)
            and active_thread_scenario in GUIDED_SCENARIO_TRAINING_PACKS
        ):
            requested_scenario = active_thread_scenario
        if active_training_card_satisfies_request(
            snapshot.active_training_card_routing,
            requested_scenario=requested_scenario,
            message=message,
            force_training_card=force_training_card,
        ):
            state.snapshot.memory = snapshot
            return
        created = safe_activate_training_card_from_coach_request(
            workspace_id=state.workspace_id,
            snapshot=state.snapshot,
            message=message,
            current_file=current_file,
            response_language=response_language,
            provider_service_override=provider_service_override,
        )
        if created is not None:
            refreshed_snapshot = runtime.memory_service.snapshot(state.workspace_id)
            if active_training_card_satisfies_request(
                refreshed_snapshot.active_training_card_routing,
                requested_scenario=requested_scenario,
                message=message,
                force_training_card=force_training_card,
            ):
                state.snapshot.memory = refreshed_snapshot
                return
        if not force_training_card and not message_requests_training_card_activation(
            message,
            requested_scenario=requested_scenario,
        ):
            return

        current_file_name = function_guidance_current_file_name(
            current_file_payload,
            scenario=requested_scenario,
        )
        default_focus, default_skill = training_card_defaults_for_scenario(
            requested_scenario,
            response_language,
        )
        focus_candidates: list[object] = []
        if active_thread is not None and active_thread_scenario in {"", requested_scenario, "general"}:
            focus_candidates.append(getattr(active_thread, "focus_area", ""))
        if requested_scenario == "general":
            focus_candidates.append(
                stateful_focus_area(
                    state.snapshot.current_task,
                    state.snapshot.plan,
                    state.snapshot.evaluation,
                    snapshot=state.snapshot,
                )
            )
        focus_candidates.append(default_focus)
        focus_hint = resolve_focus_hint(
            user_message=message,
            candidates=focus_candidates,
            fallback_current_file=current_file_name or None,
        )
        if requested_scenario == "function_guidance" and current_file_name and not focus_hint:
            focus_hint = current_file_name
        target_skill = default_skill if requested_scenario != "general" else (focus_hint or default_skill)
        context_bits = [f"Coach request: {str(message or '').strip()}"]
        if current_file_name:
            context_bits.append(f"Current file: {current_file_name}")
        active_next_step = str(getattr(active_thread, "next_step", "") or "").strip() if active_thread else ""
        if active_next_step and active_thread_scenario in {"", requested_scenario, "general"}:
            context_bits.append(f"Active thread: {active_next_step}")
        fallback_request = CardGenerationRequest(
            workspace_id=state.workspace_id,
            source="conversation_gap",
            card_type=requested_training_card_type(message),
            focus_area=focus_hint or default_focus,
            target_skill=target_skill,
            context_hint=" | ".join(bit for bit in context_bits if bit).strip()[:420],
            why_now=localized_text(
                "The learner asked Coach for one learn-first training move.",
                "学习者请 Coach 提供一个先学习再练习的训练动作。",
                response_language,
            ),
            difficulty="medium",
            response_language=validated_training_response_language(response_language),
        )
        fallback_request = fallback_request.model_copy(
            update=guided_training_workspace_facts(
                workspace_id=state.workspace_id,
                scenario=requested_scenario,
                current_file=current_file_payload,
            )
        )
        try:
            training_generate_and_route_card(
                fallback_request,
                provider_service_override=ProviderService(),
            )
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
        refreshed_snapshot = runtime.memory_service.snapshot(state.workspace_id)
        if not active_training_card_satisfies_request(
            refreshed_snapshot.active_training_card_routing,
            requested_scenario=requested_scenario,
            message=message,
            force_training_card=force_training_card,
        ):
            if direct_guided_training_card_fallback(
                workspace_id=state.workspace_id,
                scenario=requested_scenario,
                message=message,
                current_file=current_file,
                response_language=response_language,
                active_thread=active_thread,
            ):
                refreshed_snapshot = runtime.memory_service.snapshot(state.workspace_id)
        state.snapshot.memory = refreshed_snapshot

    def ensure_explicit_training_card_after_coach_reply(
        *,
        state: SessionState,
        message: str | None,
        current_file: object | None,
        response_language: str | None,
        fallback_scenario: str | None = None,
        force_training_card: bool = False,
        provider_service_override: ProviderService | None = None,
    ) -> None:
        ensure_explicit_training_card_after_language_block(
            state=state,
            message=message,
            current_file=current_file,
            response_language=response_language,
            fallback_scenario=fallback_scenario,
            force_training_card=force_training_card,
            provider_service_override=provider_service_override,
        )

    def active_thread_scenario_value(active_thread: object | None) -> str:
        if active_thread is None:
            return ""
        if isinstance(active_thread, dict):
            return str(active_thread.get("scenario") or "").strip()
        return str(getattr(active_thread, "scenario", "") or "").strip()

    def message_requests_lane_continuation(message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        compact = re.sub(r"[\s\.,!?:;\"'(){}\[\]/\\_-]+", "", lowered)
        if compact in {
            "continue",
            "continueplease",
            "pleasecontinue",
            "goon",
            "keepgoing",
            "carryon",
            "whatnext",
            "nextstep",
            "继续",
            "请继续",
            "继续吧",
            "继续一下",
            "继续一会",
            "继续这条线",
            "继续这一条线",
            "继续这个",
            "继续这一轮",
            "继续当前主线",
            "接着",
            "接着来",
            "接下来",
            "然后呢",
            "下一步",
            "下一步呢",
            "再往下",
        }:
            return True
        if re.search(r"\bcontinue(?:\s+\w+){0,4}\s+(?:lane|thread)\b", lowered):
            return True
        return any(
            marker in lowered
            for marker in (
                "same lane",
                "same thread",
                "current lane",
                "current thread",
                "live thread",
                "last step",
                "do not restart",
                "don't restart",
                "continue from the",
                "continue from there",
                "continue from that",
                "continue from last",
                "continue from the last",
                "continue from same",
                "continue the lane",
                "continue this lane",
                "pick up from there",
                "pick up from the",
                "stay on the same",
                "stay on that same",
                "keep this going",
                "keep it narrow",
            )
        )

    def message_is_relationship_reentry(message: str | None) -> bool:
        lowered = " ".join(str(message or "").strip().lower().split())
        if not lowered:
            return False
        compact = re.sub(r"[\s\.,!?:;\"'(){}\[\]/\\_\-，。！？、：；]+", "", lowered)
        return compact in {
            "hello",
            "hi",
            "hey",
            "hellotrainer",
            "hitrainer",
            "goodmorning",
            "goodafternoon",
            "goodevening",
            "你好",
            "您好",
            "嗨",
            "哈喽",
            "早上好",
            "下午好",
            "晚上好",
        }

    def message_keeps_existing_thread(message: str | None) -> bool:
        return message_requests_lane_continuation(message) or message_is_relationship_reentry(message)

    def normalize_active_view_name(active_view: str | None) -> str:
        normalized = str(active_view or "").strip().lower()
        return (
            normalized
            if normalized in {"coach", "plan", "resources", "training", "progress", "settings"}
            else ""
        )

    def active_view_owns_turn_lane(active_view: str | None) -> bool:
        return normalize_active_view_name(active_view) in {
            "plan",
            "resources",
            "training",
            "settings",
        }

    def extract_lane_continuation_step(text: str | None) -> str:
        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            return ""
        lower_normalized = normalized.lower()
        case_insensitive_markers = (
            "if you stay here,",
            "if you continue here,",
            "next:",
        )
        for marker in case_insensitive_markers:
            index = lower_normalized.find(marker)
            if index >= 0:
                candidate = normalized[index + len(marker) :].strip(" ,:;\uFF0C\u3002\uFF1A")
                if candidate:
                    return candidate
        markers = (
            "\u5982\u679c\u7ee7\u7eed\u7559\u5728\u8fd9\u91cc\uff0c\u8bf7",
            "\u5982\u679c\u4f60\u7ee7\u7eed\u7559\u5728\u8fd9\u91cc\uff0c",
            "\u7ee7\u7eed\u6cbf\u7740\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u63a8\u8fdb\u3002\u4e0b\u4e00\u6b65\uff1a",
            "\u7ee7\u7eed\u6cbf\u7740\u5df2\u4fdd\u5b58\u7684\u4e3b\u7ebf\u63a8\u8fdb\uff0c\u4e0b\u4e00\u6b65\uff1a",
            "\u7ee7\u7eed\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u63a8\u8fdb\u3002\u4e0b\u4e00\u6b65\uff1a",
            "\u7ee7\u7eed\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u63a8\u8fdb\uff0c\u4e0b\u4e00\u6b65\uff1a",
            "\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u7ee7\u7eed\u3002\u4e0b\u4e00\u6b65\uff1a",
            "\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u7ee7\u7eed\uff0c\u4e0b\u4e00\u6b65\uff1a",
            "\u4e0b\u4e00\u6b65\uff1a",
        )
        for marker in markers:
            index = normalized.find(marker)
            if index >= 0:
                candidate = normalized[index + len(marker) :].strip(" ,:;\uFF0C\u3002\uFF1A")
                if candidate:
                    return candidate
        lowered = normalized.lower()
        if (
            "switch provider or gateway" in lowered
            or "\u5148\u5207\u6362 provider \u6216 gateway" in normalized
            or "\u5148\u5207\u6362 provider / gateway" in normalized
        ):
            return ""
        return normalized
    def continuation_step_needs_local_repair(text: str | None) -> bool:
        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            return True
        lowered = normalized.casefold()
        provider_blocker_fragments = (
            "switch provider or gateway",
            "continue this debug lesson in english first",
            "continue this lesson in english first",
            "continue this coaching turn in english first",
            "先切换 provider",
            "先用 english",
            "先用 english 完成",
            "先用 english 继续",
            "回来继续 coach thread",
            "继续 coach thread",
        )
        if any(fragment in lowered or fragment in normalized for fragment in provider_blocker_fragments):
            return True
        extracted = extract_lane_continuation_step(normalized)
        if not extracted:
            return True
        return extracted != normalized

    def generic_guided_review_fallback_needs_repair(text: str | None) -> bool:
        normalized = " ".join(str(text or "").split()).strip().lower()
        if not normalized:
            return False
        generic_fallbacks = (
            "ignore secondary issues and only name the first fix plus one verification.",
            "ignore secondary issues and only describe the first fix plus one verification.",
        )
        return any(fragment in normalized for fragment in generic_fallbacks)

    def resolve_local_continuation_step(
        *,
        snapshot: WorkbenchSnapshot,
        coach_turn: dict[str, object],
        fallback_next_step: str,
    ) -> str:
        coach_context = coach_turn.get("coach_context")
        coach_active_thread = (
            coach_context.get("active_thread")
            if isinstance(coach_context, dict) and isinstance(coach_context.get("active_thread"), dict)
            else None
        )
        candidates: list[object] = []
        if snapshot.memory.active_thread:
            candidates.append(snapshot.memory.active_thread.next_step)
        if coach_active_thread is not None:
            candidates.append(coach_active_thread.get("next_step"))
        if snapshot.coaching_state:
            candidates.extend(
                [
                    snapshot.coaching_state.next_step,
                    snapshot.coaching_state.resume_thread,
                ]
            )
        candidates.extend([coach_turn.get("next_step"), fallback_next_step])
        for candidate in candidates:
            resolved = extract_lane_continuation_step(str(candidate or "").strip())
            if resolved and not continuation_step_needs_local_repair(resolved):
                return resolved
        return ""

    def local_continuation_step_for_scenario(
        scenario: str,
        response_language: str | None,
    ) -> str:
        normalized = str(scenario or "").strip().lower()
        if normalized == "remote_workspace":
            return localized_text(
                "Return one real boundary signal from the current VS Code window, such as an Explorer path, `pwd`, or the remote host label.",
                "\u5728\u4f60\u5f53\u524d\u7684 VS Code \u7a97\u53e3\u91cc\uff0c\u5e26\u56de\u4e00\u4e2a\u80fd\u8bc1\u660e\u5de5\u4f5c\u533a\u843d\u70b9\u7684\u771f\u5b9e\u4fe1\u53f7\uff0c\u6bd4\u5982 Explorer \u91cc\u7684\u8def\u5f84\u3001\u7ec8\u7aef\u91cc\u7684 `pwd`\uff0c\u6216\u8005\u5de6\u4e0b\u89d2\u7684 remote host \u6807\u7b7e\u3002",
                response_language,
            )
        if normalized == "debug_loop":
            return localized_text(
                "Tell me where you will pause first and which single value, branch, or stack frame you expect to inspect.",
                "告诉我你会先停在哪个断点，以及准备先检查哪一个值、分支或 stack frame。",
                response_language,
            )
        if normalized == "function_guidance":
            return localized_text(
                "Give me the function name and one call site you can open right now.",
                "给我函数名，以及你现在就能打开的一个 call site。",
                response_language,
            )
        if normalized == "project_adaptation":
            return localized_text(
                "Tell me what must stay stable, what must change, and the first boundary you want to adapt.",
                "告诉我什么必须保持稳定、什么必须变化，以及你想先适配的第一条边界。",
                response_language,
            )
        return ""

    def inherit_active_thread_scenario_for_continuation(
        resolved_scenario: str,
        *,
        message: str | None,
        active_thread: object | None,
    ) -> str:
        if resolved_scenario != "general":
            return resolved_scenario
        if not message_keeps_existing_thread(message):
            return resolved_scenario
        active_thread_scenario = active_thread_scenario_value(active_thread)
        if active_thread_scenario and active_thread_scenario != "general":
            return active_thread_scenario
        return resolved_scenario

    def preserve_requested_domain_scenario(
        *,
        requested_scenario: str,
        decided_scenario: str,
    ) -> str:
        first_class_domain_scenarios = {
            "remote_workspace",
            "debug_loop",
            "function_guidance",
        }
        generic_teaching_scenarios = {
            "general",
            "review",
            "idea_implementation",
            "project_idea",
            "principle",
            "plan",
            "task",
            "next_task",
            "guided",
            "concept_teaching",
            "planning",
            "engineering_challenge",
            "principle_explanation",
        }
        if (
            requested_scenario in first_class_domain_scenarios
            and decided_scenario not in first_class_domain_scenarios
            and decided_scenario in generic_teaching_scenarios
        ):
            return requested_scenario
        if requested_scenario not in {
            "remote_workspace",
            "debug_loop",
            "function_guidance",
            "idea_implementation",
            "project_adaptation",
            "project_sourcing",
            "project_idea",
            "principle",
        }:
            return decided_scenario
        if decided_scenario in {requested_scenario, "onboarding"}:
            return decided_scenario
        if requested_scenario == "principle" and decided_scenario == "review":
            return decided_scenario
        if decided_scenario in {"general", "review"}:
            return requested_scenario
        return decided_scenario

    def should_preserve_active_thread_for_scenario(
        resolved_scenario: str,
        active_thread: object | None,
    ) -> bool:
        if active_thread is None:
            return False
        active_thread_scenario = ""
        if isinstance(active_thread, dict):
            active_thread_scenario = str(active_thread.get("scenario") or "").strip()
        else:
            active_thread_scenario = str(getattr(active_thread, "scenario", "") or "").strip()
        if resolved_scenario == "general":
            return True
        if not active_thread_scenario:
            return True
        return active_thread_scenario == resolved_scenario

    def active_view_coaching_lane_override(
        *,
        active_view: str | None,
        snapshot: WorkbenchSnapshot,
        response_language: str | None,
    ) -> tuple[str, str] | None:
        normalized = normalize_active_view_name(active_view)
        if not normalized or normalized == "coach":
            return None

        if normalized == "plan":
            plan = snapshot.plan
            active_stage = (
                next(
                    (
                        stage
                        for stage in plan.stages
                        if stage.id == plan.current_stage_id or stage.status == "active"
                    ),
                    plan.stages[0] if plan.stages else None,
                )
                if plan is not None
                else None
            )
            lane = live_plan_lane_copy(
                plan=plan,
                runtime=coach_focus_runtime_from_snapshot(snapshot),
                existing=coach_focus_runtime_from_snapshot(snapshot),
                stage_title=str(active_stage.title or "").strip() if active_stage else "",
            )
            stage_title = lane["label"]
            summary = localized_text(lane["en"], lane["zh"], response_language)
            next_step = localized_text(
                (
                    "Explain why this stage is now, what counts as done, and whether the current result is ready to become formal evidence."
                    if stage_title
                    else "Turn the goal into a formal plan with stage, why now, verify method, and the next smallest step."
                ),
                (
                    "先说明这一阶段为什么是现在、怎样算完成，以及当前结果是否已经够格变成正式 evidence。"
                    if stage_title
                    else "先把目标压成正式计划，至少说清阶段、why now、verify method 和下一步。"
                ),
                response_language,
            )
            return summary, next_step

        if normalized == "resources":
            summary = localized_text(
                "Current lane: stay inside Resources and decide the next material to open, download, or reorganize.",
                "当前先留在 Resources 这条主线上，决定下一份该打开、下载或整理的资料。",
                response_language,
            )
            next_step = localized_text(
                "Locate the most relevant material, decide whether it should be opened or downloaded next, then say where it belongs under sources, knowledge, or cards.",
                "先定位最相关的资料，判断它下一步该打开还是下载，再说明它应当归到 sources、knowledge 还是 cards。",
                response_language,
            )
            return summary, next_step

        if normalized == "training":
            review = active_training_review(snapshot.memory, normalized)
            if review is not None:
                summary = localized_text(
                    f"Current recall review: {review.title or review.focus_area}.",
                    f"当前复习：{review.title or review.focus_area}。",
                    response_language,
                )
                next_step = review.guardrail or review.next_self_implementation_rule
                return summary, next_step
            active_training_routing = getattr(snapshot.memory, "active_training_card_routing", None)
            active_card = (
                active_training_routing.selected_card
                if active_training_routing and active_training_routing.selected_card is not None
                else None
            )
            leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
            lane = live_training_lane_copy(
                plan=snapshot.plan,
                task=snapshot.current_task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                task_title=snapshot.current_task.title if snapshot.current_task else "",
                card_title=str(active_card.title or "").strip() if active_card else "",
            )
            summary = localized_text(lane["en"], lane["zh"], response_language)
            next_step = localized_text(
                (
                    "Stay inside Learn -> Try -> Verify -> Reflect -> Return. "
                    "Study the current card first, then answer the prompt or record one visible verification result."
                ),
                (
                    "先留在 Learn -> Try -> Verify -> Reflect -> Return 这条训练闭环里。"
                    "先学当前卡片，再回答题目或记录一条可见的验证结果。"
                ),
                response_language,
            )
            return summary, next_step

        if normalized == "settings":
            summary = localized_text(
                "Current lane: stay inside Settings and verify provider, model, protocol, and runtime truth.",
                "当前先留在 Settings 这条主线上，核对 provider、model、protocol 和 runtime 的真实状态。",
                response_language,
            )
            next_step = localized_text(
                "Check what is truly available now, what is degraded, and which exact configuration detail must be fixed before resuming teaching.",
                "先核对现在真正可用的能力、哪些地方处于降级状态，以及恢复教学前必须修好的那一项配置。",
                response_language,
            )
            return summary, next_step

        return None

    def should_preserve_active_thread_for_turn(
        resolved_scenario: str,
        active_thread: object | None,
        *,
        message: str | None = None,
        grounding_context: dict[str, object] | None = None,
        active_view: str | None = None,
    ) -> bool:
        if resource_grounding_turn_prefers_fresh_lane(message, grounding_context):
            return False
        if active_view_owns_turn_lane(active_view):
            return False
        if resolved_scenario != "general" or message is None:
            return should_preserve_active_thread_for_scenario(
                resolved_scenario,
                active_thread,
            )
        if active_thread is None:
            return False
        return message_keeps_existing_thread(message)

    def should_preserve_relationship_continuity_for_turn(
        memory,
        *,
        message: str | None = None,
        grounding_context: dict[str, object] | None = None,
        active_view: str | None = None,
    ) -> bool:
        if not message_keeps_existing_thread(message):
            return False
        if resource_grounding_turn_prefers_fresh_lane(message, grounding_context):
            return False
        if active_view_owns_turn_lane(active_view):
            return False
        return bool(
            getattr(memory, "active_thread", None)
            or getattr(memory, "learning_outcomes", [])
        )

    def summarize_review_queue(
        due_reviews: list[ReviewQueueItem],
        response_language: str | None,
    ) -> str:
        if not due_reviews:
            return localized_text(
                "No immediate review item is due yet.",
                "暂时还没有必须立刻回看的复习项。",
                response_language,
            )
        if len(due_reviews) == 1:
            return localized_text(
                "One follow-up review is ready or due soon.",
                "有 1 个后续复习点已经就绪或即将到期。",
                response_language,
            )
        return localized_text(
            f"{len(due_reviews)} follow-up reviews are ready or due soon.",
            f"有 {len(due_reviews)} 个后续复习点已经就绪或即将到期。",
            response_language,
        )


    def apply_pedagogy_snapshot(
        *,
        snapshot: WorkbenchSnapshot,
        learner_state: LearnerState | None,
        teaching_decision: TeachingDecision | None,
        affect_state: AffectState | None,
        tone_decision: ToneDecision | None,
        implementation_guide: ImplementationGuide | None = None,
        project_ideas: list[ProjectIdea] | None = None,
        project_adaptation_guide: ProjectAdaptationGuide | None = None,
        project_sources: list[ProjectSourceSuggestion] | None = None,
        principle_notes: PrincipleNotes | None = None,
        selected_teaching_assets: list[TeachingKnowledgeAsset] | None = None,
        exercise_prompt: dict[str, object] | None = None,
    ) -> None:
        snapshot.learner_state = learner_state
        snapshot.teaching_decision = teaching_decision
        snapshot.affect_state = affect_state
        snapshot.tone_decision = tone_decision
        snapshot.implementation_guide = implementation_guide
        snapshot.project_ideas = list(project_ideas or [])
        snapshot.project_adaptation_guide = project_adaptation_guide
        snapshot.project_sources = list(project_sources or [])
        snapshot.principle_notes = principle_notes
        snapshot.selected_teaching_assets = list(selected_teaching_assets or [])
        snapshot.exercise_prompt = dict(exercise_prompt) if exercise_prompt is not None else None
        workspace = dict(snapshot.memory.workspace) if isinstance(snapshot.memory.workspace, dict) else {}
        if exercise_prompt is not None:
            workspace["exercise_prompt"] = dict(exercise_prompt)
        else:
            workspace.pop("exercise_prompt", None)
        snapshot.memory.workspace = workspace

    def model_learner_state(payload: object) -> LearnerState | None:
        if payload is None:
            return None
        if isinstance(payload, LearnerState):
            return payload
        if is_dataclass(payload) and not isinstance(payload, type):
            payload = asdict(payload)
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            learner_signal = str(payload.get("learner_signal", "steady") or "steady")
            hint_depth = str(payload.get("preferred_hint_depth", "medium") or "medium")
            normalized_hint_depth = (
                "small"
                if hint_depth in {"guided", "small"}
                else "medium"
                if hint_depth in {"balanced", "medium"}
                else "expanded"
                if hint_depth in {"direct", "expanded"}
                else "medium"
            )
            return LearnerState.model_validate(
                {
                    "current_confidence": float(payload.get("current_confidence", 0.5) or 0.5),
                    "frustration_level": float(payload.get("frustration_level", 0.0) or 0.0),
                    "attempt_count_recent": int(payload.get("attempt_count_recent", 0) or 0),
                    "needs_rescue": bool(payload.get("needs_rescue", False)),
                    "needs_review": bool(payload.get("needs_review", False)),
                    "preferred_hint_depth": normalized_hint_depth,
                    "learner_signal": learner_signal
                    if learner_signal in {"steady", "blocked", "uncertain", "curious"}
                    else "steady",
                    "active_focus": str(payload.get("active_focus", "") or ""),
                    "evidence": [str(item) for item in payload.get("evidence", []) if str(item).strip()],
                }
            )
        return None

    def model_teaching_decision(payload: object) -> TeachingDecision | None:
        if payload is None:
            return None
        if isinstance(payload, TeachingDecision):
            return payload
        if is_dataclass(payload) and not isinstance(payload, type):
            payload = asdict(payload)
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            mode = str(payload.get("mode", "guided") or "guided")
            return TeachingDecision.model_validate(
                {
                    "mode": mode
                    if mode
                    in {
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
                    }
                    else "guided",
                    "reason": str(payload.get("reason", "") or ""),
                    "primary_goal": str(payload.get("primary_goal", "") or ""),
                    "lesson_shape": str(payload.get("lesson_shape", "") or ""),
                    "exercise_shape": str(payload.get("exercise_shape", "") or ""),
                    "teaching_strategy": str(payload.get("teaching_strategy", "") or ""),
                    "closing_move": str(payload.get("closing_move", "") or ""),
                    "artifact_priority": [
                        str(item) for item in payload.get("artifact_priority", []) if str(item).strip()
                    ],
                    "should_end_with_question": bool(payload.get("should_end_with_question", False)),
                    "should_generate_exercise": bool(payload.get("should_generate_exercise", False)),
                    "should_reveal_code": bool(payload.get("should_reveal_code", False)),
                    "should_produce_plan_artifact": bool(
                        payload.get("should_produce_plan_artifact", False)
                    ),
                    "should_trigger_deep_analysis": bool(
                        payload.get("should_trigger_deep_analysis", False)
                    ),
                    "should_focus_on_implementation_steps": bool(
                        payload.get("should_focus_on_implementation_steps", True)
                    ),
                    "tone_profile": str(payload.get("tone_profile", "steady") or "steady"),
                    "focus_area": str(
                        payload.get("focus_area") or payload.get("focusArea") or ""
                    ),
                }
            )
        return None

    def model_affect_state(payload: object) -> AffectState | None:
        if payload is None:
            return None
        if isinstance(payload, AffectState):
            return payload
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            urgency = str(payload.get("urgency_level", "medium") or "medium")
            return AffectState.model_validate(
                {
                    "frustration_level": float(payload.get("frustration_level", 0.0) or 0.0),
                    "confidence_level": float(payload.get("confidence_level", 0.5) or 0.5),
                    "momentum_level": float(payload.get("momentum_level", 0.5) or 0.5),
                    "needs_reassurance": bool(payload.get("needs_reassurance", False)),
                    "urgency_level": urgency if urgency in {"low", "medium", "high"} else "medium",
                    "recovery_signal": (
                        str(payload.get("recovery_signal", "steady") or "steady")
                        if str(payload.get("recovery_signal", "steady") or "steady")
                        in {"steady", "recovering", "fragile", "overloaded"}
                        else "steady"
                    ),
                }
            )
        return None

    def model_tone_decision(payload: object) -> ToneDecision | None:
        if payload is None:
            return None
        if isinstance(payload, ToneDecision):
            return payload
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            tone = str(payload.get("tone", "steady") or "steady")
            verbosity = str(payload.get("verbosity_bias", "medium") or "medium")
            return ToneDecision.model_validate(
                {
                    "tone": tone
                    if tone in {"steady", "encouraging", "concise_rescue", "reflective"}
                    else "steady",
                    "verbosity_bias": verbosity
                    if verbosity in {"short", "medium", "expanded"}
                    else "medium",
                    "acknowledge_progress": bool(payload.get("acknowledge_progress", False)),
                    "avoid_overwhelm": bool(payload.get("avoid_overwhelm", False)),
                }
            )
        return None

    def model_implementation_guide(payload: object) -> ImplementationGuide | None:
        if payload is None:
            return None
        if isinstance(payload, ImplementationGuide):
            return payload
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            return ImplementationGuide(
                idea_summary=str(payload.get("idea_summary", "") or ""),
                scope_boundary=str(payload.get("scope_boundary", "") or ""),
                mvp_definition=str(payload.get("mvp_definition", "") or ""),
                current_step=str(payload.get("current_step", "") or ""),
                next_steps=[str(item) for item in payload.get("next_steps", []) if str(item).strip()],
                validation_strategy=[
                    str(item) for item in payload.get("validation_strategy", []) if str(item).strip()
                ],
                open_questions=[str(item) for item in payload.get("open_questions", []) if str(item).strip()],
                codebase_entry_points=[
                    str(item) for item in payload.get("codebase_entry_points", []) if str(item).strip()
                ],
                risk_notes=[str(item) for item in payload.get("risk_notes", []) if str(item).strip()],
                teaching_goal=str(payload.get("teaching_goal", "") or ""),
                success_signal=str(payload.get("success_signal", "") or ""),
                fallback_step=str(payload.get("fallback_step", "") or ""),
            )
        return None

    def model_project_adaptation_guide(payload: object) -> ProjectAdaptationGuide | None:
        if payload is None:
            return None
        if isinstance(payload, ProjectAdaptationGuide):
            return payload
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            return ProjectAdaptationGuide(
                target_outcome=str(payload.get("target_outcome", "") or ""),
                current_constraints=[
                    str(item) for item in payload.get("current_constraints", []) if str(item).strip()
                ],
                affected_areas=[str(item) for item in payload.get("affected_areas", []) if str(item).strip()],
                preserve_areas=[str(item) for item in payload.get("preserve_areas", []) if str(item).strip()],
                first_migration_step=str(payload.get("first_migration_step", "") or ""),
                migration_sequence=[str(item) for item in payload.get("migration_sequence", []) if str(item).strip()],
                validation_checkpoints=[
                    str(item) for item in payload.get("validation_checkpoints", []) if str(item).strip()
                ],
                rollback_notes=[str(item) for item in payload.get("rollback_notes", []) if str(item).strip()],
            )
        return None

    def model_project_ideas(payload: object) -> list[ProjectIdea]:
        if not isinstance(payload, list):
            return []
        ideas: list[ProjectIdea] = []
        for item in payload:
            if hasattr(item, "__dict__"):
                item = item.__dict__
            if not isinstance(item, dict):
                continue
            idea_kind = str(item.get("idea_kind", "feature") or "feature")
            difficulty = str(item.get("difficulty", "small") or "small")
            ideas.append(
                ProjectIdea.model_validate(
                    {
                        "id": str(item.get("id", "") or ""),
                        "title": str(item.get("title", "") or ""),
                        "summary": str(item.get("summary", "") or ""),
                        "source_area": str(item.get("source_area", "") or ""),
                        "idea_kind": idea_kind
                        if idea_kind
                        in {"feature", "refactor", "test", "architecture", "developer_experience"}
                        else "feature",
                        "learning_value": str(item.get("learning_value", "") or ""),
                        "engineering_value": str(item.get("engineering_value", "") or ""),
                        "difficulty": difficulty if difficulty in {"small", "medium", "stretch"} else "small",
                        "suggested_scope": str(item.get("suggested_scope", "") or ""),
                        "first_step": str(item.get("first_step", "") or ""),
                        "acceptance_signals": [
                            str(signal)
                            for signal in item.get("acceptance_signals", [])
                            if str(signal).strip()
                        ],
                        "why_now": str(item.get("why_now", "") or ""),
                    }
                )
            )
        return ideas

    def model_project_sources(payload: object) -> list[ProjectSourceSuggestion]:
        if not isinstance(payload, list):
            return []

        def visible_text(value: object) -> str:
            return normalize_visible_coach_text(value) or str(value or "").strip()

        suggestions: list[ProjectSourceSuggestion] = []
        for item in payload:
            if hasattr(item, "__dict__"):
                item = item.__dict__
            if not isinstance(item, dict):
                continue
            source_kind = str(item.get("source_kind", "reference_repo") or "reference_repo")
            suggestions.append(
                ProjectSourceSuggestion.model_validate(
                    {
                        "title": visible_text(item.get("title")),
                        "source_kind": source_kind
                        if source_kind in {"reference_repo", "reference_impl", "training_repo"}
                        else "reference_repo",
                        "repo_hint": visible_text(item.get("repo_hint")),
                        "fit_reason": visible_text(item.get("fit_reason")),
                        "training_value": visible_text(item.get("training_value")),
                        "first_filter": visible_text(item.get("first_filter")),
                        "first_task": visible_text(item.get("first_task")),
                        "caution": visible_text(item.get("caution")),
                        "tags": [visible_text(tag) for tag in item.get("tags", []) if visible_text(tag)],
                        "source_url": str(item.get("source_url", "") or ""),
                        "retrieved_at": str(item.get("retrieved_at", "") or ""),
                        "trust_score": float(item.get("trust_score", 0.0) or 0.0),
                        "quality_flags": [
                            str(flag) for flag in item.get("quality_flags", []) if str(flag).strip()
                        ],
                    }
                )
            )
        return suggestions

    def model_principle_notes(payload: object) -> PrincipleNotes | None:
        if payload is None:
            return None
        if isinstance(payload, PrincipleNotes):
            return payload
        if hasattr(payload, "__dict__"):
            payload = payload.__dict__
        if isinstance(payload, dict):
            return PrincipleNotes(
                current_principle=str(
                    payload.get("current_principle", "") or payload.get("principle", "") or ""
                ),
                why_it_matters=str(
                    payload.get("why_it_matters", "")
                    or payload.get("why_this_approach", "")
                    or ""
                ),
                common_mistake=str(
                    payload.get("common_mistake", "")
                    or payload.get("common_wrong_intuition", "")
                    or ""
                ),
                apply_now=str(
                    payload.get("apply_now", "") or payload.get("follow_up_exercise", "") or ""
                ),
                transfer_targets=[
                    str(item) for item in (
                        payload.get("transfer_targets")
                        or payload.get("related_checks")
                        or []
                    ) if str(item).strip()
                ],
                concrete_anchor=str(payload.get("concrete_anchor", "") or ""),
                transferable_lesson=str(
                    payload.get("transferable_lesson", "") or payload.get("transfer_lesson", "") or ""
                ),
                related_checks=[
                    str(item) for item in payload.get("related_checks", []) if str(item).strip()
                ],
                source_asset_title=str(payload.get("source_asset_title", "") or ""),
            )
        return None


    def active_plan_stage(plan: LearningPlan | None) -> PlanStage | None:
        if plan is None:
            return None
        return next(
            (
                stage
                for stage in plan.stages
                if stage.id == plan.current_stage_id or stage.status == "active"
            ),
            plan.stages[0] if plan.stages else None,
        )


    def attach_plan_runtime_status(
        *,
        workspace_id: str,
        snapshot: WorkbenchSnapshot,
        response_language: str | None,
        profile: UserProfile | None,
        coach_turn: dict[str, object] | None = None,
        agent_meta: dict[str, object] | None = None,
    ) -> dict[str, object]:
        previous = (
            snapshot.plan_runtime_status
            if isinstance(snapshot.plan_runtime_status, dict)
            else {}
        )
        built = coach_support.build_plan_runtime_status(coach_support_deps,
            workspace_id=workspace_id,
            snapshot=snapshot,
            response_language=response_language,
            profile=profile,
            coach_turn=coach_turn,
            agent_meta=agent_meta,
        )
        # Preserve explainable verify advance across hydrate rebuilds.
        prior_advance = previous.get("verify_plan_advance")
        if isinstance(prior_advance, dict) and prior_advance:
            built["verify_plan_advance"] = dict(prior_advance)
        elif (
            isinstance(built.get("verify_plan_advance"), dict)
            and built.get("verify_plan_advance")
        ):
            pass
        # Refresh rebuilds plan_runtime_status; keep leftover-not-live recovered stamp
        # (or re-evaluate) so /session/message + /turn (+ streams) still surface them.
        # Same drop risk as pressure_blocks_live_object_mint on coach_context refresh.
        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
        live_for_attach = bool(leftover_runtime) and leftover_formal_plan_is_live_for_fill(
            plan=snapshot.plan or leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        )
        if leftover_plan is not None and not live_for_attach:
            built["recovered"] = True
            leftover_id = str(
                getattr(leftover_plan, "id", "")
                or getattr(leftover_plan, "plan_id", "")
                or ""
            ).strip()
            status_plan_id = str(built.get("plan_id") or built.get("planId") or "").strip()
            if leftover_id and status_plan_id == leftover_id:
                built["plan_id"] = None
                built.pop("planId", None)
        elif (
            previous.get("recovered") is True
            and not live_for_attach
            and snapshot.plan is None
        ):
            built["recovered"] = True
        return built

    def structured_plan_progress_signal(
        *,
        snapshot: WorkbenchSnapshot,
        coach_turn: dict[str, object] | None,
    ) -> dict[str, object]:
        if snapshot.plan is None:
            return {}

        current_step = ""
        why_now = ""
        verify_method: list[str] = []
        blocked_reason = ""
        next_after_current = ""

        raw_coach_context = coach_turn.get("coach_context") if isinstance(coach_turn, dict) else None
        coach_context = normalized_object_mapping(raw_coach_context) or {}
        active_thread = normalized_object_mapping(coach_context.get("active_thread")) or {}
        turn_summary = coach_turn.get("coach_turn") if isinstance(coach_turn, dict) else None
        artifacts = coach_turn.get("artifacts") if isinstance(coach_turn, dict) else None

        if snapshot.project_adaptation_guide and snapshot.project_adaptation_guide.first_migration_step:
            guide = snapshot.project_adaptation_guide
            current_step = guide.first_migration_step
            why_now = guide.target_outcome or str(coach_context.get("summary") or "").strip()
            verify_method = [item for item in guide.validation_checkpoints[:3] if item]
            next_after_current = (
                guide.migration_sequence[0]
                if guide.migration_sequence
                else snapshot.plan.next_after_current
            )
        elif snapshot.project_sources:
            top_source = snapshot.project_sources[0]
            current_step = normalize_visible_coach_text(top_source.first_task) or top_source.first_task
            why_now = normalize_visible_coach_text(
                top_source.fit_reason or top_source.training_value or top_source.repo_hint
            ) or (top_source.fit_reason or top_source.training_value or top_source.repo_hint)
            verify_method = [
                normalize_visible_coach_text(item) or item
                for item in [top_source.first_filter, top_source.caution]
                if item
            ][:2]
            next_after_current = snapshot.plan.next_after_current
        elif snapshot.project_ideas:
            top_idea = snapshot.project_ideas[0]
            current_step = top_idea.first_step or ""
            why_now = top_idea.why_now or top_idea.summary
            verify_method = [item for item in top_idea.acceptance_signals[:3] if item]
            next_after_current = snapshot.plan.next_after_current
        elif snapshot.implementation_guide:
            guide = snapshot.implementation_guide
            current_step = guide.current_step or ""
            why_now = guide.mvp_definition or guide.idea_summary or guide.teaching_goal
            verify_method = [item for item in guide.validation_strategy[:3] if item]
            next_after_current = (
                guide.next_steps[0]
                if guide.next_steps
                else guide.fallback_step
                if guide.fallback_step
                else snapshot.plan.next_after_current
            )
            blocked_reason = guide.fallback_step or ""
        elif snapshot.principle_notes and snapshot.principle_notes.apply_now:
            principle = snapshot.principle_notes
            current_step = principle.apply_now
            why_now = principle.why_it_matters or principle.current_principle
            verify_method = [item for item in principle.related_checks[:3] if item]
            next_after_current = (
                principle.transfer_targets[0]
                if principle.transfer_targets
                else snapshot.plan.next_after_current
            )

        if isinstance(coach_context, dict):
            if not current_step:
                current_step = str(coach_context.get("next_step") or "").strip()
            if not why_now:
                why_now = str(coach_context.get("summary") or "").strip()
            blocked_reason = (
                str(active_thread.get("blocker") or blocked_reason).strip()
                if isinstance(active_thread, dict)
                else blocked_reason
            )

        exercise_prompt = snapshot.exercise_prompt if isinstance(snapshot.exercise_prompt, dict) else None
        if exercise_prompt:
            verify_candidates = [
                str(exercise_prompt.get("success_signal") or "").strip(),
                *[
                    str(item).strip()
                    for item in exercise_prompt.get("constraints", [])
                    if str(item).strip()
                ][:2],
            ]
            verify_method = [item for item in [*verify_method, *verify_candidates] if item]
            if not blocked_reason:
                blocked_reason = str(exercise_prompt.get("fallback_step") or "").strip()

        if isinstance(turn_summary, CoachTurnSummary):
            if not current_step:
                current_step = turn_summary.next_step.strip()
            if not why_now:
                why_now = turn_summary.summary.strip()

        if isinstance(artifacts, dict):
            plan_artifact = (
                artifacts.get("plan_update")
                or artifacts.get("idea_implementation")
                or artifacts.get("project_adaptation")
                or artifacts.get("project_idea")
                or artifacts.get("project_source")
                or artifacts.get("principle")
            )
            if isinstance(plan_artifact, dict):
                verification = plan_artifact.get("verification")
                if isinstance(verification, list) and verification:
                    verify_method = [
                        str(item).strip()
                        for item in [*verify_method, *verification]
                        if str(item).strip()
                    ]
                if not why_now:
                    why_now = str(plan_artifact.get("rationale") or "").strip()
                if not next_after_current:
                    next_after_current = str(plan_artifact.get("teaser") or "").strip()

        verify_method = list(dict.fromkeys(item for item in verify_method if item))
        refresh_runtime = coach_focus_runtime_from_snapshot(snapshot)
        refresh = live_plan_refresh_step_why(
            plan=snapshot.plan,
            runtime=refresh_runtime,
            existing=refresh_runtime,
            current_step=current_step,
            why_now=why_now,
            next_after_current=next_after_current,
            stage_title=getattr(active_plan_stage(snapshot.plan), "title", "") if snapshot.plan else "",
            task_title=snapshot.current_task.title if snapshot.current_task else "",
            stage_goal=getattr(active_plan_stage(snapshot.plan), "goal", "") if snapshot.plan else "",
        )
        payload = {
            "current_step": refresh["current_step"],
            "why_now": refresh["why_now"],
            "verify_method": verify_method,
            "blocked_reason": blocked_reason,
            "next_after_current": refresh["next_after_current"],
        }
        return {key: value for key, value in payload.items() if value}

    def plan_progress_signal(
        *,
        snapshot: WorkbenchSnapshot,
        reply_content: str,
        coach_turn: dict[str, object] | None,
    ) -> dict[str, object]:
        plan = snapshot.plan
        if plan is None:
            return {}
        active_stage = active_plan_stage(plan)
        turn_summary = coach_turn.get("coach_turn") if coach_turn else None
        next_step = ""
        blocker = ""
        reason = ""
        if isinstance(turn_summary, CoachTurnSummary):
            next_step = turn_summary.next_step.strip()
        coach_context = coach_turn.get("coach_context") if coach_turn else None
        if isinstance(coach_context, dict):
            next_step = str(coach_context.get("next_step") or next_step).strip()
            reason = str(coach_context.get("summary") or "").strip()
            blocker = str(coach_context.get("active_thread", {}).get("blocker") if isinstance(coach_context.get("active_thread"), dict) else "").strip()

        lowered_reply = reply_content.lower()
        blocked = any(token in lowered_reply for token in ("blocked", "\u5361\u4f4f", "\u4e0d\u4f1a", "\u6ca1\u6cd5", "\u95ee\u9898"))
        completed = any(token in lowered_reply for token in ("done", "\u5b8c\u6210", "\u5df2\u9a8c\u8bc1", "\u901a\u8fc7", "ok", "success"))
        plan_update = plan.model_copy(deep=True)

        if active_stage:
            persist_chrome = live_plan_update_persist_chrome(
                plan=plan,
                runtime=coach_focus_runtime_from_snapshot(snapshot),
                existing=coach_focus_runtime_from_snapshot(snapshot),
                stage_title=active_stage.title,
                task_title=snapshot.current_task.title if snapshot.current_task else "",
                stage_goal=active_stage.goal,
            )
            if blocked and blocker:
                plan_update.blocked_reason = blocker
                plan_update.current_step = next_step or persist_chrome["next_step"]
                plan_update.why_now = reason or persist_chrome["why_now"]
            elif completed and next_step:
                plan_update.blocked_reason = ""
                plan_update.current_step = next_step
                plan_update.why_now = reason or plan.why_now or "The current slice is ready to move forward."
                plan_update.next_after_current = next_step
            else:
                if next_step:
                    plan_update.current_step = next_step
                    plan_update.next_after_current = next_step
                if reason:
                    plan_update.why_now = reason
            refresh = live_plan_refresh_step_why(
                plan=plan,
                runtime=coach_focus_runtime_from_snapshot(snapshot),
                existing=coach_focus_runtime_from_snapshot(snapshot),
                current_step=plan_update.current_step,
                why_now=plan_update.why_now,
                next_after_current=plan_update.next_after_current,
                stage_title=active_stage.title,
                task_title=snapshot.current_task.title if snapshot.current_task else "",
                stage_goal=active_stage.goal,
            )
            plan_update.current_step = refresh["current_step"]
            plan_update.why_now = refresh["why_now"]
            plan_update.next_after_current = refresh["next_after_current"]
        if "verify" in lowered_reply or "\u9a8c\u8bc1" in reply_content:
            verify_lines = [
                line.strip("-\u2022?\t")
                for line in reply_content.splitlines()
                if "verify" in line.lower() or "\u9a8c\u8bc1" in line
            ]
            if verify_lines:
                plan_update.verify_method = [line for line in verify_lines if line]

        plan_update.updated_at = utc_now().isoformat()
        return plan_update.model_dump()

    def update_snapshot_plan_from_turn(
        *,
        state,
        reply_content: str,
        coach_turn: dict[str, object] | None,
        allow_formal_plan_mutation: bool = False,
    ) -> None:
        if not allow_formal_plan_mutation:
            return
        current_plan = runtime.repository.get_latest_plan(state.workspace_id)
        if current_plan is None:
            return
        leftover_runtime = leftover_runtime_for_workspace(state.workspace_id)[1]
        if not leftover_formal_plan_is_live_for_fill(
            plan=current_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            return
        # save_formal_plan already committed. Do not rewrite leftover identity from reply prose.
        state.snapshot.plan = current_plan


    def task_training_concepts(
        task: TaskSpec | None,
        *,
        snapshot: WorkbenchSnapshot | None = None,
        plan: LearningPlan | None = None,
        runtime: dict[str, object] | None = None,
    ) -> list[str]:
        if task is None:
            return []
        leftover_runtime = runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot)
        metadata = task.metadata if isinstance(task.metadata, dict) else {}
        raw_concepts = metadata.get("concepts")
        concepts = (
            [str(item).strip() for item in raw_concepts if str(item).strip()]
            if isinstance(raw_concepts, list)
            else []
        )
        return live_task_training_concepts(
            plan=plan if plan is not None else (snapshot.plan if snapshot is not None else None),
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            concepts=concepts,
            task_title=task.title,
        )

    def live_current_task_focus(
        snapshot: WorkbenchSnapshot | None,
        *,
        fallback: str = "",
        runtime: dict[str, object] | None = None,
    ) -> str:
        leftover_runtime = runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot)
        task = snapshot.current_task if snapshot is not None else None
        return live_task_focus_area(
            plan=snapshot.plan if snapshot is not None else None,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=task.title if task else "",
            fallback=fallback,
        )

    def evaluation_outcome_name(report, *, repeated_failure: bool = False) -> str:
        failed_checks = [
            check.label
            for check in [*report.static_checks, *report.dynamic_checks, *report.semantic_checks]
            if check.status == "failed"
        ]
        if report.passed and any(check.label == "pytest" for check in report.dynamic_checks if check.status == "passed"):
            return "tests_passed"
        if report.passed:
            return "code_landed"
        if failed_checks:
            return "repeated_error" if repeated_failure else "evaluation"
        return "evaluation"

    def report_learning_payload(report) -> tuple[list[str], list[str], list[str]]:
        checks = [*report.static_checks, *report.dynamic_checks, *report.semantic_checks]
        failed_checks = [check.label for check in checks if check.status == "failed"]
        learning_checks = [check.label for check in checks if check.status in {"failed", "warning"}]
        missing_requirements: list[str] = []
        for check in checks:
            if check.status not in {"failed", "warning"} or not check.detail:
                continue
            if check.label != "semantic-review":
                continue
            detail_lines = [
                line.strip()
                for line in str(check.detail).splitlines()
                if line.strip()
            ]
            detail_lines = [
                line
                for line in detail_lines
                if line.lower() != "implementation still misses requirement signals."
            ]
            missing_requirements.extend(detail_lines)
        deduped_missing: list[str] = []
        seen_missing: set[str] = set()
        for item in missing_requirements:
            lowered = item.lower()
            if lowered in seen_missing:
                continue
            seen_missing.add(lowered)
            deduped_missing.append(item)
        return failed_checks, learning_checks, deduped_missing

    def training_practice_blocked_report(
        request: EvaluateSnippetRequest,
        response_language: str | None = None,
    ) -> EvaluationReport:
        zh = prefers_chinese(response_language)
        blocked_next_step = (
            "Use Verify current file so Trainer can read the active IDE file and diagnostics."
            if not zh
            else "请使用“验证当前文件”，让 Trainer 读取活动 IDE 文件和诊断信息。"
        )
        return EvaluationReport(
            task_spec_id=request.task_spec_id,
            summary=(
                "Training practice verification needs current IDE file evidence before the card can complete."
                if not zh
                else "训练练习验证需要当前 IDE 文件证据，卡片才能完成。"
            ),
            static_checks=[
                EvaluationCheck(
                    id="current-file-required",
                    label="Current file required",
                    status="failed",
                    detail=(
                        "Training practice verification requires the active IDE file and diagnostics. "
                        "Snippet-only verification cannot complete this practice card."
                    )
                    if not zh
                    else (
                        "训练练习验证需要活动 IDE 文件和诊断信息。"
                        "仅凭代码片段验证无法完成这张练习卡。"
                    ),
                )
            ],
            dynamic_checks=[],
            semantic_checks=[],
            next_step=blocked_next_step,
            reflection=(
                "Snippet-only practice verification cannot complete a training practice card."
                if not zh
                else "仅凭代码片段的练习验证无法完成训练练习卡。"
            ),
            passed=False,
        )

    def record_training_practice_evaluation(
        *,
        workspace_id: str,
        state,
        request: EvaluateCurrentFileRequest | EvaluateSnippetRequest,
        report: EvaluationReport,
        evidence_source: str,
    ) -> None:
        if str(request.evaluation_source or "").strip().lower() != "training":
            return
        training_card_id = str(request.training_card_id or "").strip()
        if not training_card_id:
            return
        training_card = runtime.memory_service.get_card(workspace_id, training_card_id)
        if training_card is None:
            return
        # Leftover-not-live still returns the evaluation report; do not FSRS or persist status.
        if not training_card_is_live_for_verify(workspace_id, training_card_id):
            return
        live_request_title = (
            str(getattr(training_card, "title", "") or "").strip()
            or str(request.training_card_title or "").strip()
        )
        focus_area = (
            str(getattr(training_card, "focus_area", "") or "").strip()
            or "practice verification"
        )
        failed_checks, _, missing_requirements = report_learning_payload(report)
        runtime.memory_service.record_training_practice_evaluation_result(
            workspace_id=workspace_id,
            card_id=training_card_id,
            card_title=live_request_title,
            passed=bool(report.passed),
            summary=str(report.summary or ""),
            next_step=str(report.next_step or ""),
            focus_area=focus_area,
            failed_checks=failed_checks,
            missing_requirements=missing_requirements,
            evidence_source=evidence_source,
            verified_by_evaluator=bool(report.passed),
        )
        if isinstance(request, EvaluateCurrentFileRequest):
            record_executed_training_evidence(
                runtime, workspace_id=workspace_id, request=request, report=report
            )
        if bool(report.passed):
            runtime.memory_service.schedule_live_training_card_fsrs_after_verify(
                workspace_id,
                training_card_id=training_card_id,
                passed=True,
            )
        persist_training_card_to_sandbox(workspace_id, training_card, mark_current=True)
        persist_training_evaluation_note_to_sandbox(
            workspace_id=workspace_id,
            card=training_card,
            passed=bool(report.passed),
            summary=str(report.summary or ""),
            next_step=str(report.next_step or ""),
            focus_area=focus_area,
            failed_checks=failed_checks,
            missing_requirements=missing_requirements,
            evidence_source=evidence_source,
        )

    def workspace_response_language(workspace_id: str) -> str | None:
        """Learner language stored with the workspace (settings gear is canonical)."""
        try:
            memory = runtime.memory_service.snapshot(workspace_id)
        except Exception:
            return None
        workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
        saved = str(workspace.get("response_language") or "").strip()
        return saved or None

    def evaluation_failure_family(
        *,
        focus_area: str,
        failed_checks: list[str],
        missing_requirements: list[str],
    ) -> str:
        normalized_focus = focus_area.strip().lower() or "evaluation"
        normalized_checks = sorted({item.strip().lower() for item in failed_checks if item and item.strip()})
        normalized_missing = sorted({item.strip().lower() for item in missing_requirements if item and item.strip()})
        return " :: ".join(
            [
                normalized_focus,
                ",".join(normalized_checks) or "no-checks",
                ",".join(normalized_missing) or "no-missing",
            ]
        )

    def evaluation_requires_verification(report) -> bool:
        dynamic_checks = list(getattr(report, "dynamic_checks", []) or [])
        if any(str(check.status).strip().lower() == "passed" for check in dynamic_checks):
            return False
        summary_text = " ".join(
            part for part in [str(report.summary or ""), str(report.next_step or "")] if part
        ).lower()
        # Bilingual on purpose: the evaluator now localizes these sentences for
        # zh learners, and the honesty rule (no dynamic verifier ran) must hold
        # in every language.
        if any(
            phrase in summary_text
            for phrase in (
                "verification is still required",
                "run at least one dynamic verifier",
                "verify current file",
                "current ide file evidence",
                "current-file evidence",
                "仍需验证",
                "动态验证器",
                "验证当前文件",
                "当前 ide 文件证据",
                "当前文件证据",
            )
        ):
            return True
        return any(
            str(check.status).strip().lower() in {"skipped", "pending"}
            for check in dynamic_checks
        )

    def persist_evaluation_learning_loop(
        *,
        workspace_id: str,
        state,
        report,
        action_type: str,
        fallback_focus_area: str,
    ) -> None:
        task = state.snapshot.current_task
        bound_to_task = bool(task and report.task_spec_id and report.task_spec_id == task.id)
        concepts = task_training_concepts(
            state.snapshot.current_task,
            snapshot=state.snapshot,
            plan=state.snapshot.plan,
        ) if bound_to_task else []
        focus_area = (
            live_current_task_focus(state.snapshot, fallback=fallback_focus_area)
            if bound_to_task else fallback_focus_area
        )
        if not concepts and focus_area:
            concepts = [focus_area]
        if evaluation_requires_verification(report):
            runtime.memory_service.record_learning_outcome(
                workspace_id=workspace_id,
                concepts=concepts,
                outcome="verification_pending",
                summary=report.summary,
                checks=[],
                missing_requirements=[],
                action_type=action_type,
                repetition_count=1,
                focus_area=focus_area,
                scenario="review_reflection",
                verified_result="",
                blocked_reason=report.next_step,
                selected_teaching_asset_ids=[
                    item.id
                    for item in state.snapshot.selected_teaching_assets
                    if getattr(item, "id", "")
                ],
                teaching_strategy_context=teaching_strategy_context_from_snapshot(state.snapshot),
                verified_by_evaluator=False,
                bind_evidence_to_current_plan=bound_to_task,
            )
            return
        failed_checks, learning_checks, missing_requirements = report_learning_payload(report)
        runtime.memory_service.record_evaluation_feedback(
            workspace_id=workspace_id,
            concepts=concepts,
            failed_checks=failed_checks,
            missing_requirements=missing_requirements,
        )
        existing_outcomes = runtime.memory_service.snapshot(workspace_id).learning_outcomes
        failure_family = evaluation_failure_family(
            focus_area=focus_area,
            failed_checks=failed_checks,
            missing_requirements=missing_requirements,
        )
        same_family_count = sum(
            1
            for item in existing_outcomes[:8]
            if str(item.get("outcome", "")).strip().lower() in {"evaluation", "repeated_error"}
            and evaluation_failure_family(
                focus_area=str(item.get("concept", "") or focus_area),
                failed_checks=[str(value) for value in item.get("checks", []) if str(value).strip()],
                missing_requirements=[
                    str(value) for value in item.get("missing_requirements", []) if str(value).strip()
                ],
            )
            == failure_family
        )
        repetition_count = same_family_count + 1
        repeated_failure = repetition_count >= 2
        selected_teaching_asset_ids = [
            item.id
            for item in state.snapshot.selected_teaching_assets
            if getattr(item, "id", "")
        ]
        runtime.memory_service.record_learning_outcome(
            workspace_id=workspace_id,
            concepts=concepts,
            outcome=evaluation_outcome_name(report, repeated_failure=repeated_failure),
            summary=report.summary,
            checks=learning_checks,
            missing_requirements=missing_requirements,
            action_type=action_type,
            repetition_count=repetition_count,
            focus_area=focus_area,
            scenario="review_reflection",
            verified_result=report.summary if report.passed else "",
            blocked_reason=report.next_step if not report.passed else "",
            selected_teaching_asset_ids=selected_teaching_asset_ids,
            teaching_strategy_context=teaching_strategy_context_from_snapshot(state.snapshot),
            verified_by_evaluator=bool(report.passed),
            bind_evidence_to_current_plan=bound_to_task,
        )

    def advance_plan_after_evaluation(
        *,
        workspace_id: str,
        state,
        report,
    ) -> None:
        def stamp_verify_plan_advance(
            *,
            advanced: bool,
            what: str,
            why: str,
            next_step: str,
            plan_id: str = "",
        ) -> None:
            existing = (
                state.snapshot.plan_runtime_status
                if isinstance(state.snapshot.plan_runtime_status, dict)
                else {}
            )
            status = dict(existing)
            status["verify_plan_advance"] = {
                "advanced": advanced,
                "what": what,
                "why": why,
                "next": next_step,
                "plan_id": plan_id or None,
            }
            state.snapshot.plan_runtime_status = status
            runtime.memory_service.persist_verify_plan_advance_stamp(
                workspace_id,
                status["verify_plan_advance"],
            )

        task = state.snapshot.current_task
        if task is None or not report.task_spec_id or report.task_spec_id != task.id:
            stamp_verify_plan_advance(
                advanced=False,
                what="Plan progress unchanged",
                why="This file evaluation is not bound to the current formal task.",
                next_step=str(report.next_step or "").strip(),
                plan_id=str(getattr(state.snapshot.plan, "id", "") or ""),
            )
            return
        if evaluation_requires_verification(report):
            stamp_verify_plan_advance(
                advanced=False,
                what="Plan progress unchanged",
                why="Evaluator still requires a dynamic verifier before plan progress can move.",
                next_step=str(report.next_step or "").strip(),
            )
            return
        leftover_plan, leftover_runtime = leftover_runtime_for_workspace(workspace_id)
        plan = leftover_plan or state.snapshot.plan or runtime.repository.get_latest_plan(workspace_id)
        # Lock window: the revision this request based its advance decision on.
        plan_revision_at_load = (
            head_plan_revision(workspace_id, plan.id) if plan is not None else 0
        )
        if plan is None:
            stamp_verify_plan_advance(
                advanced=False,
                what="No live formal plan",
                why="Evaluator-acked project evidence was recorded, but no formal plan is bound to advance.",
                next_step=str(report.next_step or "").strip(),
            )
            return
        if not leftover_formal_plan_is_live_for_fill(
            plan=plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        ):
            carried = str(
                (leftover_runtime or {}).get("plan_id")
                or (leftover_runtime or {}).get("planId")
                or ""
            ).strip()
            formal = str(getattr(plan, "id", "") or getattr(plan, "plan_id", "") or "").strip()
            stamp_verify_plan_advance(
                advanced=False,
                what="Plan progress unchanged",
                why=(
                    "Recovered plan_runtime identity does not match the formal plan "
                    f"(runtime plan_id={carried or 'none'}, formal plan_id={formal or 'none'})."
                ),
                next_step="Resume or re-bind the live plan before verify can advance it.",
                plan_id=formal,
            )
            return
        memory_snapshot = runtime.memory_service.snapshot(workspace_id)
        existing_outcomes = memory_snapshot.learning_outcomes
        workspace = memory_snapshot.workspace if isinstance(memory_snapshot.workspace, dict) else {}
        recovered_runtime = select_plan_runtime_for_scope(
            workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
            workspace_id,
        )
        failed_checks, _learning_checks, missing_requirements = report_learning_payload(report)
        focus_area = live_current_task_focus(state.snapshot, fallback="evaluation")
        failure_family = evaluation_failure_family(
            focus_area=focus_area,
            failed_checks=failed_checks,
            missing_requirements=missing_requirements,
        )
        same_family_count = sum(
            1
            for item in existing_outcomes[:8]
            if str(item.get("outcome", "")).strip().lower() in {"evaluation", "repeated_error"}
            and evaluation_failure_family(
                focus_area=str(item.get("concept", "") or focus_area),
                failed_checks=[str(value) for value in item.get("checks", []) if str(value).strip()],
                missing_requirements=[
                    str(value) for value in item.get("missing_requirements", []) if str(value).strip()
                ],
            )
            == failure_family
        )
        repetition_count = same_family_count + (0 if report.passed else 1)
        if report.passed:
            updated = runtime.planner_service.advance_plan_after_success(
                plan,
                state.snapshot.current_task,
                passed=True,
                verified_result=report.summary,
                summary=report.summary,
                next_step=report.next_step,
                runtime=recovered_runtime,
                existing=recovered_runtime,
            )
        else:
            updated = runtime.planner_service.replan_after_failure(
                plan,
                state.snapshot.current_task,
                blocker=report.next_step,
                summary=report.summary,
                next_step=report.next_step,
                repeated_failure=repetition_count >= 2,
                focus_area=focus_area,
                runtime=recovered_runtime,
                existing=recovered_runtime,
            )
        if updated is None:
            stamp_verify_plan_advance(
                advanced=False,
                what="Plan progress unchanged",
                why="Planner returned no updated plan after evaluation.",
                next_step=str(report.next_step or "").strip(),
                plan_id=str(getattr(plan, "id", "") or getattr(plan, "plan_id", "") or "").strip(),
            )
            return
        state.snapshot.plan = updated
        formal_id = str(getattr(updated, "id", "") or getattr(updated, "plan_id", "") or "").strip()
        if updated.model_dump() != plan.model_dump():
            save_plan_or_conflict(
                workspace_id, updated, expected_revision=plan_revision_at_load
            )
            persist_plan_to_sandbox(workspace_id, updated, reason="evaluation")
        synced = runtime.memory_service.persist_plan_runtime_advance_after_verify(
            workspace_id,
            updated,
            request_id=formal_id,
        )
        state.snapshot.memory = runtime.memory_service.snapshot(workspace_id)
        response_language = None
        if isinstance(state.snapshot.memory.workspace, dict):
            response_language = str(
                state.snapshot.memory.workspace.get("response_language") or ""
            ).strip() or None
        rebuilt = attach_plan_runtime_status(
            workspace_id=workspace_id,
            snapshot=state.snapshot,
            response_language=response_language,
            profile=state.snapshot.profile,
        )
        state.snapshot.plan_runtime_status = rebuilt
        if synced is None:
            stamp_verify_plan_advance(
                advanced=False,
                what="Formal plan updated without runtime sync",
                why=(
                    "Evaluator advanced the formal plan, but recovered plan_runtime could not "
                    "be synced fail-closed to the same plan_id."
                ),
                next_step=str(getattr(updated, "current_step", "") or report.next_step or "").strip(),
                plan_id=formal_id,
            )
            return
        stamp_verify_plan_advance(
            advanced=True,
            what=str(getattr(updated, "current_step", "") or "").strip(),
            why=str(getattr(updated, "why_now", "") or report.summary or "").strip(),
            next_step=str(getattr(updated, "next_after_current", "") or report.next_step or "").strip(),
            plan_id=formal_id,
        )

    def clean_active_thread_task(
        task: TaskSpec,
        response_language: str | None,
        active_thread: object | None,
        *,
        plan: LearningPlan | None = None,
        snapshot: WorkbenchSnapshot | None = None,
        runtime: dict[str, object] | None = None,
    ) -> TaskSpec:
        if task.metadata.get("source") != "active_thread":
            return task

        def _thread_text(key: str) -> str:
            if active_thread is None:
                return ""
            if isinstance(active_thread, dict):
                return str(active_thread.get(key) or "").strip()
            return str(getattr(active_thread, key, "") or "").strip()

        def _first_clean_step() -> str:
            leftover_runtime = runtime if isinstance(runtime, dict) else coach_focus_runtime_from_snapshot(snapshot)
            candidates = live_task_clean_step_candidates(
                plan=plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                next_step=_thread_text("next_step"),
                goal=task.natural_language_goal,
                task_title=task.title,
            )
            for candidate in candidates:
                text = normalize_visible_coach_text(candidate)
                if not text:
                    continue
                if prefers_chinese(response_language):
                    provider_index = text.find("\u5148\u5207\u6362 provider")
                    if provider_index >= 0:
                        return text[provider_index:].strip(" \t\r\n:：。") + "\u3002"
                    if contains_cjk_text(text) and not looks_like_mojibake_text(text):
                        return text
                    continue
                if not looks_like_mojibake_text(text):
                    return text
            return localized_text(
                "Return to the current coaching thread and verify one small next move.",
                "\u5148\u5207\u6362 provider \u6216 gateway\uff0c\u518d\u56de\u5230\u5f53\u524d\u6559\u7ec3\u4e3b\u7ebf\u505a\u4e00\u4e2a\u5c0f\u9a8c\u8bc1\u3002",
                response_language,
            )

        needs_cleanup = any(
            looks_like_mojibake_text(value)
            for value in (
                task.title,
                task.natural_language_goal,
                *task.outputs,
                *task.constraints,
                *task.verification_strategy,
            )
        )
        if not prefers_chinese(response_language) and not needs_cleanup:
            return task

        focus = display_focus_label(
            _thread_text("focus_area")
            or (str(task.metadata.get("concepts", [""])[0]) if task.metadata.get("concepts") else ""),
            response_language,
        )
        next_step = _first_clean_step()
        if prefers_chinese(response_language):
            return task.model_copy(
                update={
                    "title": f"\u7ee7\u7eed\uff1a{focus}",
                    "natural_language_goal": (
                        "\u6cbf\u7740\u5f53\u524d\u6559\u7ec3\u4e3b\u7ebf\u7ee7\u7eed\u63a8\u8fdb\uff1a"
                        f"{next_step}"
                    ),
                    "inputs": ["\u5f53\u524d project context", "\u5f53\u524d\u6587\u4ef6\uff08\u5982\u679c\u76f8\u5173\uff09"],
                    "outputs": [
                        "\u4e00\u4e2a\u56f4\u7ed5\u5f53\u524d\u4e3b\u7ebf\u7684\u5c0f\u4fee\u6539",
                        "\u4e00\u4e2a\u5feb\u901f\u9a8c\u8bc1\u7ed3\u679c",
                    ],
                    "constraints": ["\u8fd9\u4e00\u6b65\u843d\u5730\u524d\uff0c\u4e0d\u8981\u6269\u5927\u8303\u56f4\u3002"],
                    "verification_strategy": [
                        "\u8865\u4e01\u843d\u5730\u540e\uff0c\u53ea\u9a8c\u8bc1\u5f53\u524d\u4e3b\u7ebf\u8fd9\u4e00\u6b65\u662f\u5426\u6210\u7acb\u3002"
                    ],
                }
            )
        return task.model_copy(
            update={
                "title": f"Continue: {focus}",
                "natural_language_goal": (
                    "Stay on the current coaching thread and finish one small verifiable move: "
                    f"{next_step}"
                ),
                "outputs": [
                    "One focused change on the active thread",
                    "One quick verification result",
                ],
                "constraints": ["Do not widen scope before this move lands."],
                "verification_strategy": [
                    "After the patch lands, verify only this active-thread step."
                ],
            }
        )

    def preview_coach_context(
        *,
        workspace_id: str,
        snapshot: WorkbenchSnapshot,
        profile: UserProfile | None,
        response_language: str | None,
        answer_mode: str | None,
        scenario: str | None,
        learner_signal: str | None,
    ) -> dict[str, object]:
        preview = snapshot.model_copy(deep=True)
        preview.profile = profile
        preview.memory = runtime.memory_service.snapshot(workspace_id)
        leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
        language_hint = live_language_detection_hint(
            plan=snapshot.plan,
            task=snapshot.current_task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            hint=snapshot.current_task.natural_language_goal if snapshot.current_task else "",
            goal=snapshot.current_task.natural_language_goal if snapshot.current_task else "",
            task_title=snapshot.current_task.title if snapshot.current_task else "",
        )
        resolved_response_language = effective_response_language(
            workspace_id,
            response_language,
            language_hint or None,
        )
        resolved_answer_mode = effective_answer_mode(
            workspace_id,
            answer_mode,
            profile,
            message=snapshot.messages[-1].content if snapshot.messages else None,
        )
        coach_support.hydrate_snapshot(coach_support_deps,
            preview,
            response_language=resolved_response_language,
            answer_mode=resolved_answer_mode,
            scenario=scenario,
            learner_signal=learner_signal,
            message=snapshot.messages[-1].content if snapshot.messages else None,
            session_workspace_id=workspace_id,
        )
        return coach_support.build_coach_context(coach_support_deps, 
            preview,
            response_language=resolved_response_language,
            message=snapshot.messages[-1].content if snapshot.messages else None,
        )




    def force_new_session_requested(payload: dict) -> bool:
        """Treat only an explicit truthy flag as a request to discard the active thread."""
        value = payload.get("force_new")
        if value is None:
            value = payload.get("forceNew")
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value == 1
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def normalize_trainer_root_path(value: str) -> str:
        raw_path = str(value or "").strip()
        if not raw_path:
            raise ProjectProvisioningConflictError("A Trainer workspace root is required.")
        try:
            normalized = Path(raw_path).expanduser().resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ProjectProvisioningConflictError(
                "The selected Trainer workspace root cannot be normalized."
            ) from exc
        if not normalized.is_dir():
            raise ProjectProvisioningConflictError(
                "The selected Trainer workspace root must be an available directory."
            )
        return str(normalized)

    def project_provisioning_repair_detail(response_language: str | None) -> dict[str, object]:
        return {
            "state": "repair_required",
            "status": "blocked",
            "recoverable": True,
            "detail": localized_text(
                "The managed project needs repair before it can be resumed.",
                "这个托管项目需要先修复，才能恢复会话。",
                response_language,
            ),
            "next_step": localized_text(
                "Restore the missing structured memory, then re-run /session/start.",
                "先恢复缺失的 structured_memory，然后重新调用 /session/start。",
                response_language,
            ),
        }

    def validate_project_provisioning_or_repair(workspace_id: str, response_language: str | None) -> ProjectProvisioning | None:
        try:
            return runtime.get_project_provisioning(workspace_id)
        except ProjectProvisioningIntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail=project_provisioning_repair_detail(response_language),
            ) from exc




    def summarize_session_list_payload(payload: dict[str, object]) -> dict[str, object] | None:
        snapshot = payload.get("snapshot")
        messages = list(snapshot.get("messages") or []) if isinstance(snapshot, dict) else []
        latest_user_message = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, dict)
                and message.get("role") == "user"
                and str(message.get("content") or "").strip()
            ),
            None,
        )
        latest_assistant_message = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, dict)
                and message.get("role") == "assistant"
                and str(message.get("content") or "").strip()
            ),
            None,
        )
        summary = str(
            (latest_user_message or {}).get("content")
            or (latest_assistant_message or {}).get("content")
            or payload.get("workspace_name")
            or ""
        ).strip()
        if not summary and not messages:
            return None
        updated_at = ""
        if messages:
            last_message = messages[-1]
            if isinstance(last_message, dict):
                updated_at = str(
                    last_message.get("created_at") or last_message.get("timestamp") or ""
                ).strip()
        item: dict[str, object] = {
            "session_id": str(payload.get("session_id") or "").strip(),
            "workspace_id": str(payload.get("workspace_id") or "").strip(),
            "workspace_name": str(payload.get("workspace_name") or "").strip(),
            "summary": summary,
            "message_count": len(messages),
            "updated_at": updated_at or None,
        }
        if latest_user_message is not None:
            item["latest_user_message"] = str(latest_user_message.get("content") or "").strip()
        if latest_assistant_message is not None:
            item["latest_assistant_message"] = str(latest_assistant_message.get("content") or "").strip()
        return item




    def read_agent_checkpoint_or_raise(
        *,
        checkpoint_id: str,
        scope: AgentCheckpointAccessRequest,
    ) -> dict[str, object]:
        try:
            checkpoint = runtime.read_agent_turn_checkpoint(
                checkpoint_id=checkpoint_id,
                workspace_id=scope.workspace_id,
                session_id=scope.session_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Checkpoint access was denied.") from exc
        if checkpoint is None:
            raise HTTPException(status_code=404, detail="Checkpoint was not found for this workspace.")
        return checkpoint




    def reject_blank_coach_message(request: TurnRequest) -> None:
        """Coach turns cost a live model call; a blank message is always a mistake."""
        if not request.message.strip():
            raise HTTPException(
                status_code=422,
                detail="Please type a message before sending. | 请输入消息内容后再发送。",
            )
















    def reject_if_provider_not_live_usable(
        coaching_service: ProviderService,
        payload: dict,
        response_language: str | None,
    ) -> None:
        overlay = getattr(runtime, "overlay_last_test_on_service", None)
        if callable(overlay):
            coaching_service = cast(ProviderService, overlay(coaching_service))
        if provider_is_live_usable(coaching_service, payload):
            return
        raise HTTPException(
            status_code=400,
            detail=localized_text(
                "This connection is not ready. Test it in Settings, then resend this turn.",
                "当前连接还不能用。请先在设置里测试，再重发这一轮。",
                response_language,
            ),
        )



















    deps = RouterDeps(
        current_workspace_id=current_workspace_id,
        trusted_write_workspace_id=trusted_write_workspace_id,
        current_snapshot=current_snapshot,
        refresh_workspace_sessions=refresh_workspace_sessions,
        hydrate_snapshot=lambda *args, **kwargs: coach_support.hydrate_snapshot(coach_support_deps, *args, **kwargs),
        effective_response_language=effective_response_language,
        persist_first_look_summary=persist_first_look_summary,
        provider_config_from_payload=provider_config_from_payload,
        provider_api_key_from_payload=provider_api_key_from_payload,
        normalize_trainer_root_path=normalize_trainer_root_path,
        routing_learner_state=routing_learner_state,
        operation_reliability_record=operation_reliability_record,
        provider_capabilities_from_payload=provider_capabilities_from_payload,
        provider_connection_type_from_payload=provider_connection_type_from_payload,
        provider_protocol_from_payload=provider_protocol_from_payload,
        provider_model_policy_detail=provider_model_policy_detail,
        provider_model_policy_violation=provider_model_policy_violation,
        require_sandbox_service=require_sandbox_service,
        apply_host_workspace_trust_attestation=apply_host_workspace_trust_attestation,
        workspace_learning_project_state=workspace_learning_project_state,
        active_plan_stage=active_plan_stage,
        attach_plan_runtime_status=attach_plan_runtime_status,
        coach_suggested_actions=lambda *args, **kwargs: coach_support.coach_suggested_actions(coach_support_deps, *args, **kwargs),
        ensure_coach_provider_ready=ensure_coach_provider_ready,
        frozen_plan_mutation_notice=frozen_plan_mutation_notice,
        leftover_runtime_for_workspace=leftover_runtime_for_workspace,
        persist_plan_to_sandbox=persist_plan_to_sandbox,
        provider_is_live_usable=provider_is_live_usable,
        stateful_focus_area=stateful_focus_area,
        structured_suggested_actions=structured_suggested_actions,
        workspace_first_look_summary=workspace_first_look_summary,
        sync_resource_record_to_sandbox=sync_resource_record_to_sandbox,
    )
    coach_support_deps = CoachSupportDeps(
        coach_suggested_actions=lambda *args, **kwargs: coach_support.coach_suggested_actions(coach_support_deps, *args, **kwargs),
        hydrate_snapshot=lambda *args, **kwargs: coach_support.hydrate_snapshot(coach_support_deps, *args, **kwargs),
        review_aware_next_task=lambda *args, **kwargs: coach_support.review_aware_next_task(coach_support_deps, *args, **kwargs),
        persist_turn_reflection=lambda *args, **kwargs: coach_support.persist_turn_reflection(coach_support_deps, *args, **kwargs),
        build_coaching_artifacts=lambda *args, **kwargs: coach_support.build_coaching_artifacts(coach_support_deps, *args, **kwargs),
        workspace_response_language=workspace_response_language,
        workspace_preferences=workspace_preferences,
        update_snapshot_plan_from_turn=update_snapshot_plan_from_turn,
        turn_keeps_review_signals=turn_keeps_review_signals,
        turn_history_text=turn_history_text,
        streak_without_live_object_blocks_mint=streak_without_live_object_blocks_mint,
        should_remap_task_intent_without_live_plan=should_remap_task_intent_without_live_plan,
        should_preserve_relationship_continuity_for_turn=should_preserve_relationship_continuity_for_turn,
        should_bypass_agent_loop_for_guided_training=should_bypass_agent_loop_for_guided_training,
        should_attach_auto_resource_events=should_attach_auto_resource_events,
        sanitize_visible_coach_reply_content=sanitize_visible_coach_reply_content,
        safe_activate_training_card_from_coach_request=safe_activate_training_card_from_coach_request,
        resolved_profile=resolved_profile,
        resolve_turn_grounding_async=resolve_turn_grounding_async,
        resolve_local_continuation_step=resolve_local_continuation_step,
        resolve_external_references=resolve_external_references,
        resolve_coach_turn=lambda *args, **kwargs: coach_support.resolve_coach_turn(coach_support_deps, *args, **kwargs),
        request_with_workspace_defaults=request_with_workspace_defaults,
        requires_formal_plan_commit=requires_formal_plan_commit,
        request_resource_ids=request_resource_ids,
        reply_explicitly_lists_prepared_sequence=reply_explicitly_lists_prepared_sequence,
        repair_legacy_assistant_messages=repair_legacy_assistant_messages,
        repair_guided_lane_memory_snapshot_for_response=repair_guided_lane_memory_snapshot_for_response,
        repair_generic_finalize_next_step=repair_generic_finalize_next_step,
        provider_is_live_usable=provider_is_live_usable,
        profile_with_teaching_style=profile_with_teaching_style,
        pressure_without_live_object_blocks_mint=pressure_without_live_object_blocks_mint,
        preserve_requested_domain_scenario=preserve_requested_domain_scenario,
        persist_recovered_plan_resume_after_turn=persist_recovered_plan_resume_after_turn,
        persist_external_references_as_background=persist_external_references_as_background,
        persist_evaluation_learning_loop=persist_evaluation_learning_loop,
        operation_reliability_record=operation_reliability_record,
        normalize_current_file_payload=normalize_current_file_payload,
        model_teaching_decision=model_teaching_decision,
        model_project_sources=model_project_sources,
        model_project_ideas=model_project_ideas,
        model_project_adaptation_guide=model_project_adaptation_guide,
        model_principle_notes=model_principle_notes,
        model_learner_state=model_learner_state,
        model_implementation_guide=model_implementation_guide,
        message_requests_project_sourcing=message_requests_project_sourcing,
        message_requests_explicit_explanation_or_example=message_requests_explicit_explanation_or_example,
        message_keeps_existing_thread=message_keeps_existing_thread,
        merge_agent_finalize_into_coach_turn=merge_agent_finalize_into_coach_turn,
        live_formal_plan_for_explicit_task_next=live_formal_plan_for_explicit_task_next,
        leftover_plan_state_fields=leftover_plan_state_fields,
        leftover_frozen_blocks_turn_generation=leftover_frozen_blocks_turn_generation,
        language_aligned_thread_payload=language_aligned_thread_payload,
        language_aligned_review_rhythm=language_aligned_review_rhythm,
        language_aligned_memory_payload=language_aligned_memory_payload,
        language_aligned_flat_payload=language_aligned_flat_payload,
        language_aligned_context_text=language_aligned_context_text,
        language_aligned_context_list=language_aligned_context_list,
        language_aligned_coaching_state_payload=language_aligned_coaching_state_payload,
        isolate_preflight_language_corruption_turn=isolate_preflight_language_corruption_turn,
        inherit_active_thread_scenario_for_continuation=inherit_active_thread_scenario_for_continuation,
        infer_learner_signal=infer_learner_signal,
        infer_coaching_scenario=infer_coaching_scenario,
        honest_unusable_provider_coach_turn=honest_unusable_provider_coach_turn,
        honest_suggested_actions_without_usable_provider=honest_suggested_actions_without_usable_provider,
        guided_lane_visible_reply_is_generic=guided_lane_visible_reply_is_generic,
        guided_lane_visible_reply_has_foreign_markers=guided_lane_visible_reply_has_foreign_markers,
        guarantee_guided_learn_first_training_card=guarantee_guided_learn_first_training_card,
        grounding_response_coach_turn=grounding_response_coach_turn,
        grounding_decision_from_payload=grounding_decision_from_payload,
        grounded_resource_contract_needs_repair=grounded_resource_contract_needs_repair,
        function_guidance_entry_points=function_guidance_entry_points,
        frozen_plan_mutation_notice=frozen_plan_mutation_notice,
        formal_plan_commit_verified=formal_plan_commit_verified,
        formal_plan_commit_missing_reply=formal_plan_commit_missing_reply,
        formal_plan_commit_missing_next_step=formal_plan_commit_missing_next_step,
        extract_focus_hint_from_message=extract_focus_hint_from_message,
        extract_coach_turn_payload=extract_coach_turn_payload,
        ensure_explicit_training_card_after_language_block=ensure_explicit_training_card_after_language_block,
        ensure_explicit_training_card_after_coach_reply=ensure_explicit_training_card_after_coach_reply,
        ensure_coach_provider_ready=ensure_coach_provider_ready,
        ensure_agent_tools_ready=ensure_agent_tools_ready,
        detect_provider_language_corruption=detect_provider_language_corruption,
        describe_request_attachment_delivery=describe_request_attachment_delivery,
        current_workspace_id=current_workspace_id,
        consume_provider_reply_failure_override=consume_provider_reply_failure_override,
        consume_provider_empty_reply_override=consume_provider_empty_reply_override,
        compose_resource_context=compose_resource_context,
        coach_turn_mapping=coach_turn_mapping,
        closed_loop_return_blocks_task_mint=closed_loop_return_blocks_task_mint,
        clean_active_thread_task=clean_active_thread_task,
        canonical_focus_for_scenario=canonical_focus_for_scenario,
        build_user_message_metadata=build_user_message_metadata,
        build_turn_summary=build_turn_summary,
        build_session_response=lambda *args, **kwargs: coach_support.build_session_response(coach_support_deps, *args, **kwargs),
        build_local_sequence_visible_fallback=build_local_sequence_visible_fallback,
        build_guided_training_visible_fallback=build_guided_training_visible_fallback,
        build_guided_lane_stable_visible_reply=build_guided_lane_stable_visible_reply,
        build_grounded_resource_contract_visible_fallback=build_grounded_resource_contract_visible_fallback,
        build_empty_response_visible_reply=build_empty_response_visible_reply,
        build_conversation_history=build_conversation_history,
        build_coaching_service=build_coaching_service,
        build_coach_context=lambda *args, **kwargs: coach_support.build_coach_context(coach_support_deps, *args, **kwargs),
        build_assistant_metadata=build_assistant_metadata,
        auto_resource_lookup_tool_events=auto_resource_lookup_tool_events,
        auto_preference_requests_training_card=auto_preference_requests_training_card,
        auto_lane_learn_first_force_training_card=auto_lane_learn_first_force_training_card,
        apply_pedagogy_snapshot=apply_pedagogy_snapshot,
        apply_next_step_grounding_policy=apply_next_step_grounding_policy,
        apply_language_corruption_override=apply_language_corruption_override,
        apply_guided_training_visible_fallback=apply_guided_training_visible_fallback,
        apply_guided_lane_visible_fallback=apply_guided_lane_visible_fallback,
        apply_grounding_decision=apply_grounding_decision,
        apply_auto_resource_agent_evidence=apply_auto_resource_agent_evidence,
        apply_attachment_delivery_metadata=apply_attachment_delivery_metadata,
        apply_agent_meta_to_coaching_state=apply_agent_meta_to_coaching_state,
        answer_mode_preference_for_persistence=answer_mode_preference_for_persistence,
        advance_plan_after_evaluation=advance_plan_after_evaluation,
        active_thread_scenario_value=active_thread_scenario_value,
        _resolve_context_tier=_resolve_context_tier,
        PROVIDER_REPLY_STOP_REASONS=PROVIDER_REPLY_STOP_REASONS,
        GUIDED_VISIBLE_REPAIR_SCENARIOS=GUIDED_VISIBLE_REPAIR_SCENARIOS,
        runtime=runtime,
        GROUNDING_MEMORY_PROVENANCE_CACHE_KEY=GROUNDING_MEMORY_PROVENANCE_CACHE_KEY,
        GUIDED_LANE_SCENARIOS=GUIDED_LANE_SCENARIOS,
        active_plan_stage=active_plan_stage,
        active_view_coaching_lane_override=active_view_coaching_lane_override,
        active_view_owns_turn_lane=active_view_owns_turn_lane,
        artifact_payload=artifact_payload,
        attach_plan_runtime_status=attach_plan_runtime_status,
        build_next_step_hint=build_next_step_hint,
        build_resume_thread_text=build_resume_thread_text,
        coach_artifact_title=coach_artifact_title,
        coach_focus_bundle=coach_focus_bundle,
        continuation_step_needs_local_repair=continuation_step_needs_local_repair,
        derive_coaching_state=lambda *args, **kwargs: coach_support.derive_coaching_state(coach_support_deps, *args, **kwargs),
        display_focus_label=display_focus_label,
        exercise_lines=exercise_lines,
        extract_lane_continuation_step=extract_lane_continuation_step,
        first_look_recommended_next_from_snapshot=first_look_recommended_next_from_snapshot,
        function_guidance_current_file_name=function_guidance_current_file_name,
        generic_guided_review_fallback_needs_repair=generic_guided_review_fallback_needs_repair,
        guided_focus_display_value=guided_focus_display_value,
        honest_suggested_actions_without_live_object=honest_suggested_actions_without_live_object,
        is_provider_recovery_thread_payload=is_provider_recovery_thread_payload,
        leftover_runtime_for_workspace=leftover_runtime_for_workspace,
        live_stage_object_label=live_stage_object_label,
        local_continuation_step_for_scenario=local_continuation_step_for_scenario,
        localized_actions=localized_actions,
        localized_agent_tool_label=localized_agent_tool_label,
        message_requests_lane_continuation=message_requests_lane_continuation,
        normalize_active_view_name=normalize_active_view_name,
        normalize_answer_mode=normalize_answer_mode,
        normalized_object_mapping=normalized_object_mapping,
        provider_recovery_resumed_next_step=provider_recovery_resumed_next_step,
        provider_recovery_resumed_summary=provider_recovery_resumed_summary,
        recovered_overlay_without_live_object=recovered_overlay_without_live_object,
        recovery_turn_has_no_learning_evidence=recovery_turn_has_no_learning_evidence,
        render_artifact_content=render_artifact_content,
        resolve_focus_hint=resolve_focus_hint,
        resolve_turn_focus_hint=resolve_turn_focus_hint,
        resource_grounding_turn_prefers_fresh_lane=resource_grounding_turn_prefers_fresh_lane,
        should_preserve_active_thread_for_turn=should_preserve_active_thread_for_turn,
        stateful_focus_area=stateful_focus_area,
        strip_visible_next_step_prefix=strip_visible_next_step_prefix,
        structured_plan_progress_signal=structured_plan_progress_signal,
        structured_suggested_actions=structured_suggested_actions,
        summarize_review_queue=summarize_review_queue,
    )

    core_route_seed = CoreRouteDeps(
        _stream_snapshot_fields=_stream_snapshot_fields,
        request_with_workspace_defaults=request_with_workspace_defaults,
        adopt_workspace_learning_project_folder=adopt_workspace_learning_project_folder,
        advance_plan_after_evaluation=advance_plan_after_evaluation,
        answer_mode_preference_for_persistence=answer_mode_preference_for_persistence,
        apply_attachment_delivery_metadata=apply_attachment_delivery_metadata,
        apply_auto_resource_agent_evidence=apply_auto_resource_agent_evidence,
        apply_grounding_decision=apply_grounding_decision,
        apply_guided_lane_visible_fallback=apply_guided_lane_visible_fallback,
        apply_guided_training_visible_fallback=apply_guided_training_visible_fallback,
        apply_host_workspace_trust_attestation=apply_host_workspace_trust_attestation,
        apply_language_corruption_override=apply_language_corruption_override,
        attach_operation_reliability=attach_operation_reliability,
        auto_lane_learn_first_force_training_card=auto_lane_learn_first_force_training_card,
        auto_preference_requests_training_card=auto_preference_requests_training_card,
        auto_resource_lookup_tool_events=auto_resource_lookup_tool_events,
        build_coaching_service=build_coaching_service,
        build_conversation_history=build_conversation_history,
        build_grounded_resource_contract_visible_fallback=build_grounded_resource_contract_visible_fallback,
        build_guided_training_visible_fallback=build_guided_training_visible_fallback,
        build_local_sequence_visible_fallback=build_local_sequence_visible_fallback,
        build_resume_thread_text=build_resume_thread_text,
        build_user_message_metadata=build_user_message_metadata,
        card_generation_service_for=card_generation_service_for,
        clean_active_thread_task=clean_active_thread_task,
        coach_support_deps=coach_support_deps,
        coach_turn_mapping=coach_turn_mapping,
        completed_session_requests=completed_session_requests,
        completed_session_requests_guard=completed_session_requests_guard,
        completed_training_card_requests=completed_training_card_requests,
        completed_training_card_requests_guard=completed_training_card_requests_guard,
        completion_stream_delta=completion_stream_delta,
        consume_provider_empty_reply_override=consume_provider_empty_reply_override,
        consume_provider_reply_failure_override=consume_provider_reply_failure_override,
        current_snapshot=current_snapshot,
        current_workspace_id=current_workspace_id,
        describe_request_attachment_delivery=describe_request_attachment_delivery,
        detect_provider_language_corruption=detect_provider_language_corruption,
        effective_response_language=effective_response_language,
        ensure_agent_tools_ready=ensure_agent_tools_ready,
        ensure_coach_provider_ready=ensure_coach_provider_ready,
        ensure_explicit_training_card_after_coach_reply=ensure_explicit_training_card_after_coach_reply,
        ensure_explicit_training_card_after_language_block=ensure_explicit_training_card_after_language_block,
        ensure_streaming_ready=ensure_streaming_ready,
        existing_open_resource_training_card=existing_open_resource_training_card,
        extract_coach_turn_payload=extract_coach_turn_payload,
        finalize_stream_persistence=finalize_stream_persistence,
        force_new_session_requested=force_new_session_requested,
        formal_plan_commit_tool_succeeded=formal_plan_commit_tool_succeeded,
        grounded_resource_contract_needs_repair=grounded_resource_contract_needs_repair,
        grounding_decision_from_payload=grounding_decision_from_payload,
        guarantee_guided_learn_first_training_card=guarantee_guided_learn_first_training_card,
        head_plan_revision=head_plan_revision,
        honest_suggested_actions_without_usable_provider=honest_suggested_actions_without_usable_provider,
        honest_unusable_provider_stream=honest_unusable_provider_stream,
        inflight_session_requests=inflight_session_requests,
        inflight_training_card_requests=inflight_training_card_requests,
        isolate_preflight_language_corruption_turn=isolate_preflight_language_corruption_turn,
        json_object_payload=json_object_payload,
        leftover_plan_state_fields=leftover_plan_state_fields,
        leftover_runtime_for_workspace=leftover_runtime_for_workspace,
        live_current_task_focus=live_current_task_focus,
        maybe_persist_first_look_from_path=maybe_persist_first_look_from_path,
        merge_agent_finalize_into_coach_turn=merge_agent_finalize_into_coach_turn,
        message_confirms_learning_project_folder=message_confirms_learning_project_folder,
        message_rejects_learning_project_folder=message_rejects_learning_project_folder,
        normalize_attachment_delivery_payload=normalize_attachment_delivery_payload,
        normalize_trainer_root_path=normalize_trainer_root_path,
        normalized_object_mapping=normalized_object_mapping,
        persist_evaluation_learning_loop=persist_evaluation_learning_loop,
        persist_external_references_as_background=persist_external_references_as_background,
        persist_plan_to_sandbox=persist_plan_to_sandbox,
        persist_recovered_plan_resume_after_turn=persist_recovered_plan_resume_after_turn,
        persist_requested_response_language=persist_requested_response_language,
        prepare_stream_user_message=prepare_stream_user_message,
        prepare_training_card_request=prepare_training_card_request,
        pressure_without_live_object_blocks_mint=pressure_without_live_object_blocks_mint,
        profile_with_teaching_style=profile_with_teaching_style,
        provider_api_key_from_payload=provider_api_key_from_payload,
        provider_config_from_payload=provider_config_from_payload,
        provider_is_live_usable=provider_is_live_usable,
        read_agent_checkpoint_or_raise=read_agent_checkpoint_or_raise,
        record_training_practice_evaluation=record_training_practice_evaluation,
        refresh_workspace_sessions=refresh_workspace_sessions,
        register_stream_cancellation=register_stream_cancellation,
        reject_blank_coach_message=reject_blank_coach_message,
        reject_if_provider_not_live_usable=reject_if_provider_not_live_usable,
        reliability_outcome_from_payload=reliability_outcome_from_payload,
        repair_generic_finalize_next_step=repair_generic_finalize_next_step,
        repair_guided_lane_memory_snapshot_for_response=repair_guided_lane_memory_snapshot_for_response,
        reply_explicitly_lists_prepared_sequence=reply_explicitly_lists_prepared_sequence,
        request_stream_cancellation=request_stream_cancellation,
        require_live_formal_plan_for_explicit_task_next=require_live_formal_plan_for_explicit_task_next,
        require_live_selected_card_for_status=require_live_selected_card_for_status,
        requires_formal_plan_commit=requires_formal_plan_commit,
        resolve_session_history_state=resolve_session_history_state,
        resolve_stream_id=resolve_stream_id,
        resolve_turn_grounding_async=resolve_turn_grounding_async,
        resolved_profile=resolved_profile,
        resource_contract_stream_recovery_requested=resource_contract_stream_recovery_requested,
        routing_changed=routing_changed,
        safe_activate_training_card_from_coach_request=safe_activate_training_card_from_coach_request,
        safe_stream_delta=safe_stream_delta,
        save_plan_or_conflict=save_plan_or_conflict,
        select_active_training_card=select_active_training_card,
        should_attach_auto_resource_events=should_attach_auto_resource_events,
        should_bypass_agent_loop_for_guided_training=should_bypass_agent_loop_for_guided_training,
        sse_complete_frame=sse_complete_frame,
        streak_without_live_object_blocks_mint=streak_without_live_object_blocks_mint,
        stream_cancellation_events=stream_cancellation_events,
        stream_cancellation_requested=stream_cancellation_requested,
        stream_frame=stream_frame,
        stream_status_event=stream_status_event,
        summarize_session_list_payload=summarize_session_list_payload,
        summarize_session_state=summarize_session_state,
        task_training_concepts=task_training_concepts,
        teaching_strategy_context_from_snapshot=teaching_strategy_context_from_snapshot,
        to_json_payload=to_json_payload,
        training_generate_and_route_card=training_generate_and_route_card,
        training_practice_blocked_report=training_practice_blocked_report,
        trusted_training_card_request_from_api=trusted_training_card_request_from_api,
        turn_history_text=turn_history_text,
        turn_request_from_stream_payload=turn_request_from_stream_payload,
        unregister_stream_cancellation=unregister_stream_cancellation,
        update_snapshot_plan_from_turn=update_snapshot_plan_from_turn,
        validate_project_provisioning_or_repair=validate_project_provisioning_or_repair,
        workspace_learning_project_prompt_needed=workspace_learning_project_prompt_needed,
        workspace_learning_project_prompt_text=workspace_learning_project_prompt_text,
        workspace_learning_project_state=workspace_learning_project_state,
        workspace_preferences=workspace_preferences,
        workspace_response_language=workspace_response_language,
    )
    router.include_router(build_core_router(runtime, deps, core_route_seed))
    router.include_router(build_workspace_router(runtime, deps))
    router.include_router(build_memory_router(runtime, deps))
    router.include_router(build_learning_router(runtime, deps))
    router.include_router(build_resources_router(runtime, deps))
    router.include_router(build_browser_router(runtime, deps))
    router.include_router(build_provider_router(runtime, deps))
    router.include_router(build_sandbox_router(runtime, deps))
    router.include_router(build_plan_router(runtime, deps))
    router.include_router(build_mcp_router(runtime, deps))



    return router
